"""Load settings from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    frigate_base_url: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str
    groq_api_key: str
    groq_vision_model: str
    bolna_api_key: str
    bolna_agent_id: str
    owner_phone: str
    shop_name: str
    dry_run: bool
    armed: str | None
    armed_hours: str
    cooldown_seconds: float
    incidents_log: Path
    project_root: Path


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(env_file: Path | None = None) -> Settings:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(env_file or (root / ".env"))

    armed_raw = os.getenv("ARMED")
    return Settings(
        mqtt_host=os.getenv("MQTT_HOST", "localhost"),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_topic=os.getenv("MQTT_TOPIC", "frigate/reviews"),
        frigate_base_url=os.getenv("FRIGATE_BASE_URL", "http://localhost:5001"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
        or "gemini-3.8-flash",
        gemini_fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_vision_model=os.getenv("GROQ_VISION_MODEL", "").strip(),
        bolna_api_key=os.getenv("BOLNA_API_KEY", "").strip(),
        bolna_agent_id=os.getenv("BOLNA_AGENT_ID", "").strip(),
        owner_phone=os.getenv("OWNER_PHONE", "").strip(),
        shop_name=os.getenv("SHOP_NAME", "Shop").strip() or "Shop",
        dry_run=_truthy(os.getenv("DRY_RUN"), default=True),
        armed=armed_raw,
        armed_hours=os.getenv("ARMED_HOURS", "").strip(),
        cooldown_seconds=float(os.getenv("COOLDOWN_SECONDS", "180")),
        incidents_log=root / "logs" / "incidents.jsonl",
        project_root=root,
    )
