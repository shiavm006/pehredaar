"""Snapshot → Gemini → Gemini fallback → Groq → fail-safe verdict."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("pehredaar.vision")

CATEGORIES = (
    "intrusion_after_hours",
    "forced_entry",
    "violence",
    "loitering",
    "no_threat",
)
CONFIDENCES = ("high", "medium", "low")

VISION_BUDGET_S = 8.0
GEMINI_RETRY_SLEEP_S = 1.0

VISION_PROMPT = """You are a shop security camera analyst for after-hours monitoring.

Look at this single CCTV snapshot. Reply with JSON ONLY (no markdown), exactly:
{
  "category": one of ["intrusion_after_hours", "forced_entry", "violence", "loitering", "no_threat"],
  "confidence": "high" | "medium" | "low",
  "description_en": one plain factual sentence,
  "description_hi": the same meaning in simple spoken Hindi using Devanagari script
}

Rules:
- Describe ONLY what is clearly visible in the image.
- Never guess weapons, intent, identity, or anything not visible.
- If a person is visible inside the shop after hours with no clear forced entry or violence, use intrusion_after_hours.
- If nothing concerning is visible, use no_threat.
"""

FAILSAFE_HI = "दुकान में शायद कोई घुसपैठ हुई है। कृपया कैमरा तुरंत देखें।"


@dataclass
class VisionVerdict:
    category: str
    confidence: str
    description_en: str
    description_hi: str
    source: str  # e.g. gemini:gemini-3.8-flash | groq:<model> | failsafe

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "description_en": self.description_en,
            "description_hi": self.description_hi,
            "source": self.source,
        }


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _normalize(raw: dict[str, Any], source: str) -> VisionVerdict:
    category = str(raw.get("category", "")).strip()
    confidence = str(raw.get("confidence", "")).strip().lower()
    description_en = str(raw.get("description_en", "")).strip()
    description_hi = str(raw.get("description_hi", "")).strip()

    if category not in CATEGORIES:
        raise ValueError(f"invalid category: {category!r}")
    if confidence not in CONFIDENCES:
        raise ValueError(f"invalid confidence: {confidence!r}")
    if not description_en or not description_hi:
        raise ValueError("missing description_en or description_hi")

    return VisionVerdict(
        category=category,
        confidence=confidence,
        description_en=description_en,
        description_hi=description_hi,
        source=source,
    )


def _failsafe() -> VisionVerdict:
    return VisionVerdict(
        category="intrusion_after_hours",
        confidence="low",
        description_en="Possible after-hours intrusion; camera review needed.",
        description_hi=FAILSAFE_HI,
        source="failsafe",
    )


def _is_transient(exc: BaseException) -> bool:
    """True for 503 / 429 / timeout-like failures worth one retry."""
    if isinstance(exc, (TimeoutError, FuturesTimeout)):
        return True
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in (429, 503):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (429, 503):
        return True
    text = str(exc).lower()
    needles = (
        "429",
        "503",
        "timeout",
        "timed out",
        "unavailable",
        "resource_exhausted",
        "resource exhausted",
        "rate limit",
        "too many requests",
        "service unavailable",
    )
    return any(n in text for n in needles)


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _run_within(fn: Callable[[], VisionVerdict], deadline: float, label: str) -> VisionVerdict:
    rem = _remaining(deadline)
    if rem <= 0.05:
        raise TimeoutError(f"vision budget exhausted before {label}")
    log.info("vision attempt: %s (%.1fs left)", label, rem)
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=rem)
        except FuturesTimeout as exc:
            raise TimeoutError(f"{label} exceeded remaining budget") from exc


def _gemini(jpeg: bytes, api_key: str, model: str) -> VisionVerdict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    image_part = types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")
    response = client.models.generate_content(
        model=model,
        contents=[VISION_PROMPT, image_part],
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    text = getattr(response, "text", None) or ""
    if not text and getattr(response, "candidates", None):
        parts = response.candidates[0].content.parts
        text = "".join(getattr(p, "text", "") or "" for p in parts)
    return _normalize(_extract_json(text), f"gemini:{model}")


def _groq(jpeg: bytes, api_key: str, model: str) -> VisionVerdict:
    from groq import Groq

    b64 = base64.b64encode(jpeg).decode("ascii")
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    )
    text = completion.choices[0].message.content or ""
    return _normalize(_extract_json(text), f"groq:{model}")


def _try_gemini(
    jpeg: bytes,
    api_key: str,
    model: str,
    deadline: float,
    *,
    retry_transient: bool,
) -> VisionVerdict:
    label = f"gemini:{model}"

    def call() -> VisionVerdict:
        return _gemini(jpeg, api_key, model)

    try:
        return _run_within(call, deadline, label)
    except Exception as exc:
        if not retry_transient or not _is_transient(exc):
            raise
        sleep_for = min(GEMINI_RETRY_SLEEP_S, max(0.0, _remaining(deadline) - 0.2))
        log.warning(
            "%s transient failure (%s) — retry in %.1fs",
            label,
            exc,
            sleep_for,
        )
        if sleep_for > 0:
            time.sleep(sleep_for)
        return _run_within(call, deadline, f"{label}:retry")


def analyze_snapshot(
    jpeg: bytes,
    *,
    gemini_api_key: str,
    groq_api_key: str,
    gemini_model: str = "gemini-3.8-flash",
    gemini_fallback_model: str = "",
    groq_model: str = "",
) -> VisionVerdict:
    """Gemini (+ transient retry) → Gemini fallback → Groq → fail-safe.

    Whole check is capped at ~VISION_BUDGET_S so a slow model never stalls the call.
    """
    deadline = time.monotonic() + VISION_BUDGET_S

    if gemini_api_key and gemini_model:
        try:
            verdict = _try_gemini(
                jpeg,
                gemini_api_key,
                gemini_model,
                deadline,
                retry_transient=True,
            )
            log.info("vision answered via %s", verdict.source)
            return verdict
        except Exception as exc:
            log.warning("Gemini primary failed: %s", exc)
    elif not gemini_api_key:
        log.warning("GEMINI_API_KEY missing")
    else:
        log.warning("GEMINI_MODEL empty")

    if gemini_api_key and gemini_fallback_model and gemini_fallback_model != gemini_model:
        if _remaining(deadline) <= 0.05:
            log.warning("vision budget exhausted — skip Gemini fallback")
        else:
            try:
                verdict = _try_gemini(
                    jpeg,
                    gemini_api_key,
                    gemini_fallback_model,
                    deadline,
                    retry_transient=False,
                )
                log.info("vision answered via %s", verdict.source)
                return verdict
            except Exception as exc:
                log.warning("Gemini fallback failed: %s", exc)
    elif gemini_fallback_model and gemini_fallback_model == gemini_model:
        log.info("GEMINI_FALLBACK_MODEL same as primary — skip")

    if groq_model and groq_api_key:
        if _remaining(deadline) <= 0.05:
            log.warning("vision budget exhausted — skip Groq")
        else:
            try:
                verdict = _run_within(
                    lambda: _groq(jpeg, groq_api_key, groq_model),
                    deadline,
                    f"groq:{groq_model}",
                )
                log.info("vision answered via %s", verdict.source)
                return verdict
            except Exception as exc:
                log.warning("Groq failed: %s", exc)
    elif groq_model and not groq_api_key:
        log.warning("GROQ_API_KEY missing — skip Groq")
    elif not groq_model:
        log.info("GROQ_VISION_MODEL empty — skip Groq")

    verdict = _failsafe()
    log.warning("Fail-safe verdict after budget/attempts: %s", verdict.as_dict())
    return verdict
