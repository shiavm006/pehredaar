"""Event ids arrive over an anonymous MQTT broker — treat them as untrusted."""

import pytest

from brain.frigate_api import FrigateError, fetch_event_snapshot


@pytest.mark.parametrize(
    "evil",
    [
        "../../../../api/config",
        "1793221724.483321-ybdijc/../../config",
        "foo/bar",
        "",
        "a" * 200,
        "id with spaces",
        "id;rm -rf /",
    ],
)
def test_malformed_event_id_rejected_before_any_request(evil):
    with pytest.raises(FrigateError, match="malformed event_id"):
        fetch_event_snapshot("http://localhost:5001", evil)


def test_real_frigate_id_shape_is_accepted():
    # Must fail on the network call, not on validation.
    with pytest.raises(FrigateError) as exc:
        fetch_event_snapshot("http://127.0.0.1:1", "1793221724.483321-ybdijc", timeout=0.2)
    assert "malformed" not in str(exc.value)
