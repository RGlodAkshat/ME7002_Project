"""MCP must share configuration state, permissions and conflict rules with HTTP."""
from copy import deepcopy
import json
from pathlib import Path


def admin_headers(client):
    result = client.post("/api/auth/setup", json={"name": "Owner", "email": "owner@example.test", "password": "Correct-test-password-72"})
    assert result.status_code == 200, result.text
    return {"Accept": "application/json, text/event-stream", "X-CSRF-Token": result.json()["csrf_token"], "MCP-Protocol-Version": "2025-11-25"}


def rpc(client, headers, method, params=None, request_id=1):
    return client.post("/api/mcp", headers=headers, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


def specification():
    return json.loads((Path(__file__).resolve().parents[2] / "configs/examples/lab-fan.json").read_text())


def test_mcp_auth_transport_and_discovery(client):
    assert rpc(client, {"Accept": "application/json, text/event-stream"}, "tools/list").status_code == 401
    headers = admin_headers(client)
    initialized = rpc(client, headers, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
    notification = client.post("/api/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notification.status_code == 202 and not notification.content
    tools = rpc(client, headers, "tools/list").json()["result"]["tools"]
    assert {"get_configuration", "apply_configuration", "upsert_entity", "upsert_relationship"} <= {item["name"] for item in tools}
    assert client.get("/api/mcp", headers=headers).status_code == 405
    assert rpc(client, {**headers, "Accept": "application/json"}, "tools/list").status_code == 406
    assert rpc(client, {**headers, "Origin": "https://unrelated.invalid"}, "tools/list").status_code == 403
    assert rpc(client, {**headers, "Origin": "http://testserver:invalid"}, "tools/list").status_code == 403
    assert rpc(client, {**headers, "Origin": "http://testserver/unsafe/path"}, "tools/list").status_code == 403
    assert rpc(client, {**headers, "MCP-Protocol-Version": "unknown"}, "tools/list").status_code == 400
    assert rpc(client, headers, "nonexistent").json()["error"]["code"] == -32601


def test_mcp_edit_export_and_revision_conflicts_share_http_service(client):
    headers = admin_headers(client)
    spec = specification()
    applied = rpc(client, headers, "tools/call", {"name": "apply_configuration", "arguments": {"specification": spec, "expected_revision": 0}}).json()["result"]
    assert not applied["isError"], applied
    revision = applied["structuredContent"]["revision"]
    entity = deepcopy(next(item for item in spec["entities"] if item["type"] == "machine"))
    entity["name"] = "Configured through MCP"
    edited = rpc(client, headers, "tools/call", {"name": "upsert_entity", "arguments": {"entity": entity, "expected_revision": revision}}).json()["result"]
    assert not edited["isError"], edited
    exported = client.get("/api/configuration/export").json()
    assert next(item for item in exported["entities"] if item["id"] == entity["id"])["name"] == entity["name"]
    conflict = rpc(client, headers, "tools/call", {"name": "upsert_entity", "arguments": {"entity": entity, "expected_revision": revision}}).json()["result"]
    assert conflict["isError"]
    resource = rpc(client, headers, "resources/read", {"uri": "manufacturing://configuration"}).json()["result"]
    current = json.loads(resource["contents"][0]["text"])
    assert current["revision"] == revision + 1
    assert current["specification"] == exported
    invalid = deepcopy(exported)
    invalid["relationships"][0]["target"] = "does-not-exist"
    validation = rpc(client, headers, "tools/call", {"name": "validate_configuration", "arguments": {"specification": invalid}}).json()["result"]
    assert not validation["structuredContent"]["valid"]
    assert client.get("/api/configuration").json()["revision"] == current["revision"]


def test_mcp_operator_and_bad_arguments_are_rejected(client):
    headers = admin_headers(client)
    created = client.post("/api/users", headers=headers, json={"name": "Worker", "email": "worker@example.test", "password": "Worker-password-38", "role": "operator", "skills": ["assembly"]})
    assert created.status_code in {200, 201}, created.text
    client.post("/api/auth/logout", headers=headers)
    login = client.post("/api/auth/login", json={"email": "worker@example.test", "password": "Worker-password-38"})
    worker_headers = {**headers, "X-CSRF-Token": login.json()["csrf_token"]}
    assert rpc(client, worker_headers, "tools/list").status_code == 403
    client.post("/api/auth/logout", headers=worker_headers)
    login = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "Correct-test-password-72"})
    headers["X-CSRF-Token"] = login.json()["csrf_token"]
    for arguments in ({"expected_revision": True, "specification": {}}, {"expected_revision": -1, "specification": {}}, {"expected_revision": 0, "specification": {}, "unexpected": "field"}):
        result = rpc(client, headers, "tools/call", {"name": "apply_configuration", "arguments": arguments}).json()["result"]
        assert result["isError"]


def test_mcp_integration_credential_and_audit_actor(client, monkeypatch):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.platform_models import ConfigurationChange
    monkeypatch.setattr(get_settings(), "admin_integration_token", "integration-token-for-test-only")
    headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer integration-token-for-test-only"}
    result = rpc(client, headers, "tools/call", {"name": "apply_configuration", "arguments": {"specification": specification(), "expected_revision": 0}}).json()["result"]
    assert not result["isError"]
    with SessionLocal() as db:
        change = db.query(ConfigurationChange).one()
        assert change.actor == "mcp-integration" and change.revision == 1
    assert rpc(client, {**headers, "Authorization": "Bearer invalid-token"}, "tools/list").status_code == 401
