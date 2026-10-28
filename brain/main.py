"""MQTT subscriber: frigate/reviews → vision → policy → Bolna call."""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from brain.caller import build_payload, place_call
from brain.config import Settings, load_settings
from brain.frigate_api import FrigateError, fetch_event_snapshot, first_detection_id
from brain.logging_util import append_incident
from brain.policy import decide
from brain.rules import IncidentGate, is_armed
from brain.vision import analyze_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pehredaar.brain")


class Brain:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gate = IncidentGate(cooldown_seconds=settings.cooldown_seconds)

    def handle_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "new":
            log.debug("ignore type=%s", payload.get("type"))
            return

        after = payload.get("after") or {}
        if after.get("severity") != "alert":
            log.debug("ignore severity=%s", after.get("severity"))
            return

        incident_id = str(after.get("id") or "")
        camera = str(after.get("camera") or "unknown")
        if not incident_id:
            log.warning("alert missing after.id — skip")
            return

        if not is_armed(self.settings.armed, self.settings.armed_hours):
            log.info("DISARMED — skip incident=%s camera=%s", incident_id, camera)
            return

        allowed, reason = self.gate.allow(incident_id, camera)
        if not allowed:
            log.info("SUPPRESS %s", reason)
            return

        log.info("ALERT incident=%s camera=%s", incident_id, camera)
        self._process_alert(incident_id, camera, after)

    def _process_alert(self, incident_id: str, camera: str, after: dict[str, Any]) -> None:
        settings = self.settings
        started = datetime.now(timezone.utc).astimezone()
        event_time = after.get("start_time")
        if isinstance(event_time, (int, float)):
            event_dt = datetime.fromtimestamp(event_time).astimezone()
        else:
            event_dt = started

        record: dict[str, Any] = {
            "time": started.isoformat(timespec="seconds"),
            "review_id": incident_id,
            "camera": camera,
            "category": None,
            "confidence": None,
            "description_en": None,
            "description_hi": None,
            "vision_source": None,
            "action": None,
            "call_result": None,
            "error": None,
        }

        try:
            detection_id = first_detection_id(after)
            jpeg = fetch_event_snapshot(settings.frigate_base_url, detection_id)
            log.info("snapshot %d bytes for detection=%s", len(jpeg), detection_id)

            verdict = analyze_snapshot(
                jpeg,
                gemini_api_key=settings.gemini_api_key,
                groq_api_key=settings.groq_api_key,
                gemini_model=settings.gemini_model,
                gemini_fallback_model=settings.gemini_fallback_model,
                groq_model=settings.groq_vision_model,
            )
            print("=== vision verdict ===", flush=True)
            print(json.dumps(verdict.as_dict(), ensure_ascii=False, indent=2), flush=True)
            print("=== end verdict ===", flush=True)

            record.update(
                {
                    "category": verdict.category,
                    "confidence": verdict.confidence,
                    "description_en": verdict.description_en,
                    "description_hi": verdict.description_hi,
                    "vision_source": verdict.source,
                }
            )

            action = decide(verdict)
            record["action"] = action.name
            log.info("policy → %s (%s)", action.name, action.detail)

            if action.name == "call_owner":
                agent_id = settings.bolna_agent_id or "DRY_RUN_AGENT_ID"
                owner_phone = settings.owner_phone or "+10000000000"
                if not settings.dry_run and (
                    not settings.bolna_agent_id or not settings.owner_phone
                ):
                    record["error"] = "BOLNA_AGENT_ID or OWNER_PHONE missing"
                    log.error(record["error"])
                else:
                    if settings.dry_run and (
                        not settings.bolna_agent_id or not settings.owner_phone
                    ):
                        log.warning(
                            "DRY_RUN with placeholder agent/phone — set BOLNA_AGENT_ID and OWNER_PHONE for real calls"
                        )
                    payload = build_payload(
                        agent_id=agent_id,
                        owner_phone=owner_phone,
                        shop_name=settings.shop_name,
                        camera_name=camera,
                        threat_hi=verdict.description_hi,
                        event_time=event_dt,
                    )
                    result = place_call(
                        payload,
                        api_key=settings.bolna_api_key,
                        dry_run=settings.dry_run,
                    )
                    record["call_result"] = {
                        "dry_run": result.dry_run,
                        "execution_id": result.execution_id,
                        "error": result.error,
                        "payload": result.payload,
                    }
                    if result.error:
                        log.error("call failed: %s", result.error)
                    elif result.execution_id:
                        log.info("call execution_id=%s", result.execution_id)
            else:
                log.info("%s — no outbound notify", action.name)

        except FrigateError as exc:
            record["error"] = str(exc)
            log.error("frigate: %s", exc)
        except Exception as exc:
            record["error"] = str(exc)
            log.exception("alert processing failed: %s", exc)
        finally:
            append_incident(settings.incidents_log, record)
            log.info("logged → %s", settings.incidents_log)


def run(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    brain = Brain(settings)

    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        # paho-mqtt v2 CallbackAPIVersion.VERSION2
        rc = getattr(reason_code, "value", reason_code)
        if rc != 0:
            log.error("MQTT connect failed rc=%s", reason_code)
            return
        client.subscribe(settings.mqtt_topic)
        log.info(
            "subscribed %s @ %s:%s dry_run=%s armed=%s cooldown=%ss",
            settings.mqtt_topic,
            settings.mqtt_host,
            settings.mqtt_port,
            settings.dry_run,
            is_armed(settings.armed, settings.armed_hours),
            int(settings.cooldown_seconds),
        )

    def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            log.warning("bad JSON on %s: %s", msg.topic, exc)
            return
        brain.handle_payload(payload)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"pehredaar-brain-{int(time.time())}",
    )
    client.on_connect = on_connect
    client.on_message = on_message

    stop = False

    def _stop(*_args: Any) -> None:
        nonlocal stop
        stop = True
        client.disconnect()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("connecting MQTT %s:%s …", settings.mqtt_host, settings.mqtt_port)
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_forever()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
