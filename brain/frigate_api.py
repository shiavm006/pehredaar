"""Frigate HTTP helpers.

Snapshot endpoint (Frigate 0.18 docs):
  GET /api/events/{event_id}/snapshot.jpg
  https://docs.frigate.video/integrations/api/event-snapshot-events-event-id-snapshot-jpg-get
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger("pehredaar.frigate")


class FrigateError(RuntimeError):
    pass


def first_detection_id(review_after: dict[str, Any]) -> str:
    data = review_after.get("data") or {}
    detections = data.get("detections") or []
    if not detections:
        raise FrigateError("review has no detections[] — cannot fetch snapshot")
    return str(detections[0])


def fetch_event_snapshot(
    base_url: str,
    event_id: str,
    *,
    timeout: float = 15.0,
) -> bytes:
    """Download JPEG snapshot for a tracked-object / event id."""
    url = f"{base_url.rstrip('/')}/api/events/{event_id}/snapshot.jpg"
    log.info("GET %s", url)
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise FrigateError(f"snapshot request failed: {exc}") from exc

    if resp.status_code != 200:
        raise FrigateError(
            f"snapshot HTTP {resp.status_code} for event_id={event_id}: {resp.text[:200]}"
        )
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "jpeg" not in ctype and "jpg" not in ctype and not resp.content.startswith(b"\xff\xd8"):
        raise FrigateError(f"unexpected Content-Type {ctype!r} for snapshot")
    if len(resp.content) < 100:
        raise FrigateError("snapshot response too small")
    return resp.content
