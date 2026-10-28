"""Map vision category → action."""

from __future__ import annotations

from dataclasses import dataclass

from brain.vision import VisionVerdict


@dataclass(frozen=True)
class Action:
    name: str  # log_only | call_owner
    detail: str


def decide(verdict: VisionVerdict) -> Action:
    if verdict.category in ("no_threat", "loitering"):
        return Action("log_only", f"{verdict.category} — log only")
    return Action("call_owner", f"{verdict.category} — call owner")
