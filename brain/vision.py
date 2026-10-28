"""Snapshot → Gemini (primary) → Groq vision (retry) → fail-safe verdict."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("pehredaar.vision")

CATEGORIES = (
    "intrusion_after_hours",
    "forced_entry",
    "violence",
    "loitering",
    "no_threat",
)
CONFIDENCES = ("high", "medium", "low")

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
    source: str  # gemini | groq | failsafe

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


def _gemini(jpeg: bytes, api_key: str) -> VisionVerdict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    image_part = types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[VISION_PROMPT, image_part],
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    text = getattr(response, "text", None) or ""
    if not text and getattr(response, "candidates", None):
        # Fallback scrape
        parts = response.candidates[0].content.parts
        text = "".join(getattr(p, "text", "") or "" for p in parts)
    return _normalize(_extract_json(text), "gemini")


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
    return _normalize(_extract_json(text), "groq")


def analyze_snapshot(
    jpeg: bytes,
    *,
    gemini_api_key: str,
    groq_api_key: str,
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
) -> VisionVerdict:
    """Gemini first; on failure retry once with Groq; then fail-safe."""
    if gemini_api_key:
        try:
            verdict = _gemini(jpeg, gemini_api_key)
            log.info("Gemini verdict: %s", verdict.as_dict())
            return verdict
        except Exception as exc:
            log.warning("Gemini failed: %s — trying Groq", exc)
    else:
        log.warning("GEMINI_API_KEY missing — trying Groq")

    if groq_api_key:
        try:
            verdict = _groq(jpeg, groq_api_key, groq_model)
            log.info("Groq verdict: %s", verdict.as_dict())
            return verdict
        except Exception as exc:
            log.warning("Groq failed: %s — fail-safe", exc)
    else:
        log.warning("GROQ_API_KEY missing — fail-safe")

    verdict = _failsafe()
    log.warning("Fail-safe verdict: %s", verdict.as_dict())
    return verdict
