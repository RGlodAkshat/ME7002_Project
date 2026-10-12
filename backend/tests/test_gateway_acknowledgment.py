"""A successful HTTP response alone must not authorize physical reassignment."""
import httpx
import pytest

from app.platform_providers import HttpMachineGateway


@pytest.mark.parametrize("action,status", [("start", "accepted"), ("stop", "stopped")])
def test_acknowledgment_matches_action_and_dispatch(monkeypatch, action, status):
    def response(*args, **kwargs):
        return httpx.Response(202, json={"dispatch_id": "current-dispatch", "status": status}, request=httpx.Request("POST", "http://gateway/commands"))
    monkeypatch.setattr(httpx, "post", response)
    HttpMachineGateway({"host": "gateway", "port": 9002, "protocol": "http"}).dispatch("station", {"action": action, "dispatch_id": "current-dispatch"})


@pytest.mark.parametrize("acknowledgement", [
    {"dispatch_id": "current-dispatch", "status": "accepted"},
    {"dispatch_id": "different-dispatch", "status": "stopped"},
    {"status": "stopped"},
    None,
])
def test_unconfirmed_stop_is_rejected_even_on_http_success(monkeypatch, acknowledgement):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json=acknowledgement, request=httpx.Request("POST", "http://gateway/commands")))
    with pytest.raises(ValueError):
        HttpMachineGateway({"host": "gateway", "port": 9002, "protocol": "http"}).dispatch("station", {"action": "stop", "dispatch_id": "current-dispatch"})
