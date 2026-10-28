"""Hindi spoken event_time formatting."""

from datetime import datetime

from brain.caller import format_event_time_hi


def test_raat_early_morning():
    assert format_event_time_hi(datetime(2026, 10, 29, 2, 38)) == "raat 2:38 baje"


def test_subah():
    assert format_event_time_hi(datetime(2026, 10, 29, 7, 5)) == "subah 7:05 baje"


def test_dopahar():
    assert format_event_time_hi(datetime(2026, 10, 29, 13, 0)) == "dopahar 1:00 baje"


def test_shaam():
    assert format_event_time_hi(datetime(2026, 10, 29, 18, 45)) == "shaam 6:45 baje"


def test_raat_evening():
    assert format_event_time_hi(datetime(2026, 10, 29, 22, 1)) == "raat 10:01 baje"


def test_build_payload_uses_hindi_time_and_shop_name():
    from brain.caller import build_payload

    payload = build_payload(
        agent_id="a",
        owner_phone="+910000000000",
        shop_name="Pehredaar Demo Shop",
        camera_name="shopcam",
        threat_hi="टेस्ट",
        event_time=datetime(2026, 10, 29, 2, 38),
    )
    assert payload["user_data"]["shop_name"] == "Pehredaar Demo Shop"
    assert payload["user_data"]["event_time"] == "raat 2:38 baje"


if __name__ == "__main__":
    test_raat_early_morning()
    test_subah()
    test_dopahar()
    test_shaam()
    test_raat_evening()
    test_build_payload_uses_hindi_time_and_shop_name()
    print("caller time ok")
