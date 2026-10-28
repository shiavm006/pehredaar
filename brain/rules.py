"""Armed schedule + incident / cooldown gates."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Optional


def _parse_hhmm(value: str) -> dt_time:
    hour, minute = value.strip().split(":")
    return dt_time(int(hour), int(minute))


def is_armed(armed_flag: Optional[str], armed_hours: str, now: Optional[datetime] = None) -> bool:
    """
    ARMED=true/false overrides the schedule.
    Otherwise ARMED_HOURS like "21:00-07:00" (supports midnight wrap).
    Empty hours with no flag → armed (safe default for after-hours testing).
    """
    if armed_flag is not None and str(armed_flag).strip() != "":
        return str(armed_flag).strip().lower() in {"1", "true", "yes", "on"}

    hours = (armed_hours or "").strip()
    if not hours:
        return True

    start_s, end_s = hours.split("-", 1)
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    now = now or datetime.now()
    current = now.time().replace(second=0, microsecond=0)

    if start <= end:
        # Same-day window, e.g. 09:00-17:00
        return start <= current < end
    # Crosses midnight, e.g. 21:00-07:00 → armed if >= start OR < end
    return current >= start or current < end


@dataclass
class IncidentGate:
    """One call per review/incident id, plus per-camera cooldown."""

    cooldown_seconds: float = 180.0
    _seen_incidents: set[str] = field(default_factory=set)
    _camera_last_call: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, incident_id: str, camera: str) -> tuple[bool, str]:
        """Return (allowed, reason). reason is empty when allowed."""
        with self._lock:
            if incident_id in self._seen_incidents:
                return False, f"duplicate incident id={incident_id}"

            last = self._camera_last_call.get(camera)
            now = time.monotonic()
            if last is not None and (now - last) < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - (now - last))
                return False, f"camera cooldown ({remaining}s left) camera={camera}"

            self._seen_incidents.add(incident_id)
            self._camera_last_call[camera] = now
            return True, ""
