#!/usr/bin/env python3
"""End-to-end video harness: real RTSP → Frigate → MQTT → brain → incidents.jsonl."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CSV = ROOT / "test_videos" / "expected.csv"
INCIDENTS_LOG = ROOT / "logs" / "incidents.jsonl"
CAMERA_SCRIPT = ROOT / "scripts" / "start_camera.sh"
RESULTS_DIR = ROOT / "test_results"
DEFAULT_WAIT_S = 40.0
DEFAULT_SETTLE_S = 10.0

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


@dataclass
class ExpectRow:
    file: str
    expect_alert: bool
    expect_category: str
    expect_action: str


@dataclass
class CaseResult:
    file: str
    expected: str
    got_alert: str
    got_category: str
    confidence: str
    vision_source: str
    action: str
    passed: bool
    note: str = ""


def _now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_now_local().tzinfo)
    return dt


def check_frigate(base_url: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/api/version"
    try:
        with urlopen(url, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status == 200:
                return True, f"Frigate OK ({body or 'version unknown'})"
            return False, f"Frigate HTTP {resp.status} at {url}"
    except URLError as exc:
        return False, f"Frigate not reachable at {url}: {exc}"
    except Exception as exc:
        return False, f"Frigate check failed: {exc}"


def check_mosquitto(host: str, port: int) -> tuple[bool, str]:
    try:
        import socket

        with socket.create_connection((host, port), timeout=2):
            return True, f"Mosquitto OK ({host}:{port})"
    except OSError as exc:
        return False, f"Mosquitto not reachable at {host}:{port}: {exc}"


def check_brain() -> tuple[bool, str]:
    try:
        out = subprocess.check_output(["pgrep", "-fl", "brain.main"], text=True)
    except subprocess.CalledProcessError:
        return False, "brain not running (no process matching brain.main)"
    lines = [ln for ln in out.splitlines() if "brain.main" in ln]
    if not lines:
        return False, "brain not running (no process matching brain.main)"
    return True, f"brain OK ({lines[0].strip()})"


def print_start_hints(frigate_ok: bool, mqtt_ok: bool, brain_ok: bool) -> None:
    print("\nHow to start missing pieces:\n")
    if not frigate_ok or not mqtt_ok:
        print("  # Frigate + Mosquitto")
        print(f"  cd {ROOT}")
        print("  docker compose up -d")
        print()
    if not brain_ok:
        print("  # Brain (separate terminal; COOLDOWN_SECONDS=30 recommended for harness)")
        print(f"  cd {ROOT}")
        print("  source .venv/bin/activate  # if you use a venv")
        print("  python -m brain.main")
        print()


def load_expected(path: Path, only: Optional[str]) -> list[ExpectRow]:
    rows: list[ExpectRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            file_name = (raw.get("file") or "").strip()
            if not file_name:
                continue
            if only and file_name != only and Path(file_name).stem != Path(only).stem:
                continue
            alert = (raw.get("expect_alert") or "").strip().lower()
            rows.append(
                ExpectRow(
                    file=file_name,
                    expect_alert=alert in {"yes", "y", "true", "1"},
                    expect_category=(raw.get("expect_category") or "").strip(),
                    expect_action=(raw.get("expect_action") or "").strip() or "none",
                )
            )
    return rows


def read_incidents_in_window(
    path: Path, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_iso(str(rec.get("time") or ""))
            if ts is None:
                continue
            if start <= ts <= end:
                out.append(rec)
    return out


def pick_incident(
    incidents: list[dict[str, Any]], expect: ExpectRow
) -> Optional[dict[str, Any]]:
    if not incidents:
        return None
    if expect.expect_category:
        matched = [i for i in incidents if i.get("category") == expect.expect_category]
        if matched:
            return matched[0]
    # Prefer a non-failsafe vision hit when scoring alert cases.
    non_fs = [i for i in incidents if not str(i.get("vision_source") or "").startswith("failsafe")]
    return (non_fs or incidents)[0]


def score_case(expect: ExpectRow, incidents: list[dict[str, Any]]) -> CaseResult:
    expected_label = (
        f"alert={('yes' if expect.expect_alert else 'no')}"
        + (f"/{expect.expect_category}" if expect.expect_category else "")
        + f"/{expect.expect_action}"
    )
    if not expect.expect_alert:
        passed = len(incidents) == 0
        return CaseResult(
            file=expect.file,
            expected=expected_label,
            got_alert="yes" if incidents else "no",
            got_category=(incidents[0].get("category") or "") if incidents else "",
            confidence=(incidents[0].get("confidence") or "") if incidents else "",
            vision_source=(incidents[0].get("vision_source") or "") if incidents else "",
            action=(incidents[0].get("action") or "none") if incidents else "none",
            passed=passed,
            note="" if passed else f"{len(incidents)} unexpected incident(s)",
        )

    hit = pick_incident(incidents, expect)
    if hit is None:
        return CaseResult(
            file=expect.file,
            expected=expected_label,
            got_alert="no",
            got_category="",
            confidence="",
            vision_source="",
            action="none",
            passed=False,
            note="no incident in window",
        )

    got_cat = str(hit.get("category") or "")
    got_action = str(hit.get("action") or "none")
    source = str(hit.get("vision_source") or "")
    cat_ok = (not expect.expect_category) or got_cat == expect.expect_category
    action_ok = got_action == expect.expect_action
    passed = cat_ok and action_ok
    notes = []
    if not cat_ok:
        notes.append(f"category want {expect.expect_category!r} got {got_cat!r}")
    if not action_ok:
        notes.append(f"action want {expect.expect_action!r} got {got_action!r}")
    if expect.expect_action == "call_owner" and source.startswith("failsafe"):
        notes.append("vision source is failsafe")
        passed = False
    return CaseResult(
        file=expect.file,
        expected=expected_label,
        got_alert="yes",
        got_category=got_cat,
        confidence=str(hit.get("confidence") or ""),
        vision_source=source,
        action=got_action,
        passed=passed,
        note="; ".join(notes),
    )


def stop_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def run_video_case(
    expect: ExpectRow,
    *,
    wait_s: float,
    settle_s: float,
) -> CaseResult:
    video_path = ROOT / "test_videos" / expect.file
    if not video_path.is_file():
        return CaseResult(
            file=expect.file,
            expected=f"alert={('yes' if expect.expect_alert else 'no')}/{expect.expect_action}",
            got_alert="?",
            got_category="",
            confidence="",
            vision_source="",
            action="",
            passed=False,
            note=f"missing video: {video_path}",
        )

    print(f"\n=== {expect.file} ===")
    print(f"publishing {video_path} for {wait_s:.0f}s …")
    env = os.environ.copy()
    env["PEHREDAAR_KEEP_MTX"] = "1"
    start = _now_local()
    proc = subprocess.Popen(
        ["bash", str(CAMERA_SCRIPT), "--video", str(video_path)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        time.sleep(wait_s)
    finally:
        print("stopping publisher …")
        stop_process(proc)

    if settle_s > 0:
        print(f"settle {settle_s:.0f}s for Frigate review end …")
        time.sleep(settle_s)
    end = _now_local()

    incidents = read_incidents_in_window(INCIDENTS_LOG, start, end)
    print(f"incidents in window: {len(incidents)}")
    for rec in incidents:
        print(
            "  -",
            rec.get("time"),
            rec.get("category"),
            rec.get("action"),
            rec.get("vision_source"),
        )
    return score_case(expect, incidents)


def format_table(results: list[CaseResult]) -> str:
    headers = [
        "file",
        "expected",
        "got alert?",
        "got category",
        "confidence",
        "vision source",
        "action",
        "PASS/FAIL",
    ]
    rows = [
        [
            r.file,
            r.expected,
            r.got_alert,
            r.got_category,
            r.confidence,
            r.vision_source,
            r.action,
            "PASS" if r.passed else "FAIL",
        ]
        for r in results
    ]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    lines = [fmt(headers), "-|-".join("-" * w for w in widths)]
    for row in rows:
        lines.append(fmt(row))
    failed = [r for r in results if not r.passed]
    lines.append("")
    lines.append(f"Summary: {len(results) - len(failed)}/{len(results)} passed")
    for r in failed:
        if r.note:
            lines.append(f"  FAIL {r.file}: {r.note}")
    return "\n".join(lines)


def write_markdown(results: list[CaseResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Video test results — {path.stem}",
        "",
        f"Generated: {_now_local().isoformat(timespec='seconds')}",
        "",
        "| file | expected | got alert? | got category | confidence | vision source | action | PASS/FAIL |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    r.file,
                    r.expected,
                    r.got_alert,
                    r.got_category or "—",
                    r.confidence or "—",
                    r.vision_source or "—",
                    r.action or "—",
                    "PASS" if r.passed else "FAIL",
                ]
            )
            + " |"
        )
    failed = [r for r in results if not r.passed]
    lines.append("")
    lines.append(f"**Summary:** {len(results) - len(failed)}/{len(results)} passed")
    for r in failed:
        if r.note:
            lines.append(f"- FAIL `{r.file}`: {r.note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait",
        type=float,
        default=float(os.getenv("VIDEO_TEST_WAIT_S", DEFAULT_WAIT_S)),
        help=f"seconds to publish each video (default {DEFAULT_WAIT_S})",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=float(os.getenv("VIDEO_TEST_SETTLE_S", DEFAULT_SETTLE_S)),
        help=f"seconds to wait after stop for Frigate to end review (default {DEFAULT_SETTLE_S})",
    )
    parser.add_argument(
        "--only",
        default="",
        help="run a single CSV file row, e.g. intruder.mp4",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="do not require Frigate/Mosquitto/brain to be up",
    )
    args = parser.parse_args()

    frigate_url = os.getenv("FRIGATE_BASE_URL", "http://localhost:5001")
    mqtt_host = os.getenv("MQTT_HOST", "localhost")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))

    frigate_ok, frigate_msg = check_frigate(frigate_url)
    mqtt_ok, mqtt_msg = check_mosquitto(mqtt_host, mqtt_port)
    brain_ok, brain_msg = check_brain()

    print("Preflight:")
    print(f"  {'OK' if frigate_ok else 'MISSING'} — {frigate_msg}")
    print(f"  {'OK' if mqtt_ok else 'MISSING'} — {mqtt_msg}")
    print(f"  {'OK' if brain_ok else 'MISSING'} — {brain_msg}")

    if not args.skip_checks and not (frigate_ok and mqtt_ok and brain_ok):
        print_start_hints(frigate_ok, mqtt_ok, brain_ok)
        return 2

    if not EXPECTED_CSV.is_file():
        print(f"Missing {EXPECTED_CSV}", file=sys.stderr)
        return 2

    rows = load_expected(EXPECTED_CSV, args.only or None)
    if not rows:
        print("No rows to run (check --only / expected.csv)", file=sys.stderr)
        return 2

    cooldown_s = float(os.getenv("COOLDOWN_SECONDS", "30"))
    results: list[CaseResult] = []
    prev_had_alert = False
    for i, row in enumerate(rows):
        if i > 0 and prev_had_alert and cooldown_s > 0:
            print(f"\ninter-test cooldown gap {cooldown_s:.0f}s …")
            time.sleep(cooldown_s)
        result = run_video_case(row, wait_s=args.wait, settle_s=args.settle)
        results.append(result)
        prev_had_alert = result.got_alert == "yes"

    table = format_table(results)
    print("\n" + table)

    stamp = _now_local().strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"{stamp}.md"
    write_markdown(results, out_path)
    print(f"\nWrote {out_path}")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
