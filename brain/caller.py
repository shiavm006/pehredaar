"""Bolna outbound call. DRY_RUN prints the exact payload instead of POSTing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests

log = logging.getLogger("pehredaar.caller")

BOLNA_CALL_URL = "https://api.bolna.ai/call"


@dataclass
class CallResult:
    dry_run: bool
    payload: dict[str, Any]
    execution_id: Optional[str]
    raw: Optional[dict[str, Any]]
    error: Optional[str] = None


def format_event_time_hi(dt: datetime) -> str:
    """Spoken Hindi 12-hour time, e.g. 'raat 2:38 baje'."""
    hour = dt.hour
    minute = dt.minute
    hour12 = hour % 12 or 12
    if 4 <= hour < 12:
        period = "subah"
    elif 12 <= hour < 16:
        period = "dopahar"
    elif 16 <= hour < 21:
        period = "shaam"
    else:
        period = "raat"
    return f"{period} {hour12}:{minute:02d} baje"


def build_payload(
    *,
    agent_id: str,
    owner_phone: str,
    shop_name: str,
    camera_name: str,
    threat_hi: str,
    event_time: datetime | str,
) -> dict[str, Any]:
    if isinstance(event_time, datetime):
        event_time_s = format_event_time_hi(event_time)
    else:
        event_time_s = str(event_time)
    return {
        "agent_id": agent_id,
        "recipient_phone_number": owner_phone,
        "user_data": {
            "shop_name": shop_name,
            "camera_name": camera_name,
            "threat_hi": threat_hi,
            "event_time": event_time_s,
        },
    }


def place_call(
    payload: dict[str, Any],
    *,
    api_key: str,
    dry_run: bool = True,
    timeout: float = 30.0,
) -> CallResult:
    if dry_run:
        log.info("DRY_RUN=true — would POST %s\n%s", BOLNA_CALL_URL, json.dumps(payload, ensure_ascii=False, indent=2))
        print("=== DRY_RUN Bolna payload ===", flush=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        print("=== end DRY_RUN ===", flush=True)
        return CallResult(dry_run=True, payload=payload, execution_id=None, raw=None)

    if not api_key:
        return CallResult(
            dry_run=False,
            payload=payload,
            execution_id=None,
            raw=None,
            error="BOLNA_API_KEY missing",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(BOLNA_CALL_URL, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return CallResult(
            dry_run=False,
            payload=payload,
            execution_id=None,
            raw=None,
            error=str(exc),
        )

    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text}

    if resp.status_code >= 400:
        return CallResult(
            dry_run=False,
            payload=payload,
            execution_id=None,
            raw=body if isinstance(body, dict) else None,
            error=f"HTTP {resp.status_code}: {body}",
        )

    execution_id = None
    if isinstance(body, dict):
        execution_id = body.get("execution_id")
    log.info("Bolna call queued execution_id=%s body=%s", execution_id, body)
    return CallResult(
        dry_run=False,
        payload=payload,
        execution_id=execution_id,
        raw=body if isinstance(body, dict) else None,
    )
