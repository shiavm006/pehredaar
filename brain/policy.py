"""Map vision category → action."""

from __future__ import annotations

from dataclasses import dataclass

from brain.vision import VisionVerdict


@dataclass(frozen=True)
class Action:
    name: str  # log_only | whatsapp_placeholder | call_owner
    detail: str


def decide(verdict: VisionVerdict) -> Action:
    if verdict.category == "no_threat":
        return Action("log_only", "no_threat — log only")
    if verdict.category == "loitering":
        return Action(
            "whatsapp_placeholder",
            "loitering — WhatsApp placeholder (log only for now)",
        )
    return Action("call_owner", f"{verdict.category} — call owner")
