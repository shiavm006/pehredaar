"""Quick checks for armed-hours + incident gate."""

from datetime import datetime

from brain.rules import IncidentGate, is_armed


def test_armed_flag_override():
    assert is_armed("true", "09:00-17:00") is True
    assert is_armed("false", "00:00-23:59") is False


def test_hours_cross_midnight():
    noon = datetime(2026, 1, 1, 12, 0)
    night = datetime(2026, 1, 1, 22, 0)
    morning = datetime(2026, 1, 1, 6, 0)
    assert is_armed(None, "21:00-07:00", now=noon) is False
    assert is_armed(None, "21:00-07:00", now=night) is True
    assert is_armed(None, "21:00-07:00", now=morning) is True


def test_hours_same_day():
    assert is_armed(None, "09:00-17:00", now=datetime(2026, 1, 1, 10, 0)) is True
    assert is_armed(None, "09:00-17:00", now=datetime(2026, 1, 1, 18, 0)) is False


def test_default_armed_when_empty():
    assert is_armed(None, "") is True
    assert is_armed("", "") is True


def test_incident_dedupe_and_cooldown():
    gate = IncidentGate(cooldown_seconds=60)
    ok, _ = gate.allow("rev-1", "shopcam")
    assert ok
    ok2, reason = gate.allow("rev-1", "shopcam")
    assert not ok2 and "duplicate" in reason
    ok3, reason3 = gate.allow("rev-2", "shopcam")
    assert not ok3 and "cooldown" in reason3


if __name__ == "__main__":
    test_armed_flag_override()
    test_hours_cross_midnight()
    test_hours_same_day()
    test_default_armed_when_empty()
    test_incident_dedupe_and_cooldown()
    print("rules ok")
