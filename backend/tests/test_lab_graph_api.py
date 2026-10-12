"""Lab configuration uses the same authenticated APIs and workflow core."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app import platform_providers
from app.platform_rdf import convert_turtle

PASSWORD = "Lab-graph-test-password-73"
SOURCE = Path(__file__).resolve().parents[2] / "smart_factory_v2_modular_3_final_updated.ttl"


@pytest.fixture(scope="module")
def lab_spec():
    return convert_turtle(SOURCE.read_text())


def setup(client, specification):
    result = client.post("/api/auth/setup", json={"name": "Administrator", "email": "admin@lab.test", "password": PASSWORD})
    assert result.status_code == 200, result.text
    headers = {"X-CSRF-Token": result.json()["csrf_token"]}
    applied = client.put("/api/configuration", headers=headers, json={"specification": specification, "expected_revision": 0})
    assert applied.status_code == 200, applied.text
    return headers


def login(client, email):
    result = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def worker(client, headers, email, skills):
    result = client.post("/api/users", headers=headers, json={"name": email, "email": email, "password": PASSWORD, "role": "operator",
                        "skills": [], "qualifications": [f"qualification-{skill}" for skill in skills]})
    assert result.status_code == 200, result.text
    return result.json()


def place(client, product="PR1"):
    response = client.post("/api/shop/orders", json={"product_id": product, "selections": {}, "customer_name": "Guest purchaser", "confirmed": True})
    assert response.status_code == 200, response.text
    return response.json()


def test_turtle_preview_does_not_apply_and_is_admin_only(client):
    assert client.post("/api/configuration/import-turtle", json={"turtle": SOURCE.read_text()}).status_code == 401
    result = client.post("/api/auth/setup", json={"name": "Admin", "email": "admin@lab.test", "password": PASSWORD})
    headers = {"X-CSRF-Token": result.json()["csrf_token"]}
    preview = client.post("/api/configuration/import-turtle", headers=headers, json={"turtle": SOURCE.read_text()})
    assert preview.status_code == 200 and preview.json()["valid"]
    assert client.get("/api/configuration").json()["specification"] is None
    malformed = client.post("/api/configuration/import-turtle", headers=headers, json={"turtle": "invalid Turtle"})
    assert not malformed.json()["valid"] and malformed.json()["errors"]
    applied = client.put("/api/configuration", headers=headers, json={"specification": preview.json()["specification"], "expected_revision": 0})
    assert applied.status_code == 200, applied.text
    worker(client, headers, "worker@lab.test", ["WS1"])
    headers = login(client, "worker@lab.test")
    assert client.post("/api/configuration/import-turtle", headers=headers, json={"turtle": SOURCE.read_text()}).status_code == 403


def test_process_derived_skills_and_live_order_assignments(client, lab_spec):
    headers = setup(client, lab_spec)
    options = client.get("/api/skills").json()
    assert {option["id"] for option in options} == {f"skill-{wid}" for wid in ("WS1", "WS2", "WS3", "WS4", "WS5", "WS6", "WS7", "WS9")}
    assert all(option["processes"] for option in options)
    first = worker(client, headers, "first@lab.test", ["WS1"])
    second = worker(client, headers, "second@lab.test", ["WS1"])
    order = place(client)
    # Assignment uses UUID ordering, not account creation time.
    if order["tasks"][0]["assigned_operator_id"] == second["id"]:
        first, second = second, first
    assert order["tasks"][0]["assigned_operator_id"] == first["id"]
    runtime = client.get(f"/api/orders/{order['id']}/graph").json()
    assert runtime["configuration_revision"] == 1
    assert {node["id"] for node in runtime["nodes"] if node["type"] == "product"} == {"PR1"}
    assert len([node for node in runtime["nodes"] if node["type"] == "operation"]) == 8
    assert any(edge["type"] == "assigned_operator" and edge["target"] == first["id"] for edge in runtime["relationships"])
    assert any(edge["type"] == "qualified_for" and edge["source"] == first["id"] and edge["target"] == "qualification-WS1" for edge in runtime["relationships"])
    assert any(edge["type"] == "has_skill" and edge["source"] == first["id"] and edge["target"] == "skill-WS1" for edge in runtime["relationships"])
    changed = client.patch(f"/api/users/{first['id']}", headers=headers, json={"available": False})
    assert changed.status_code == 200
    updated = client.get(f"/api/orders/{order['id']}/graph").json()
    assert any(edge["type"] == "assigned_operator" and edge["target"] == second["id"] for edge in updated["relationships"])
    assert not any(edge["type"] == "assigned_operator" and edge["target"] == first["id"] for edge in updated["relationships"])
    login(client, second["email"])
    assert client.get(f"/api/orders/{order['id']}/graph").status_code == 403
    assert client.get("/api/skills").status_code == 403


def test_configuration_changes_do_not_rewrite_order_knowledge(client, lab_spec):
    headers = setup(client, lab_spec)
    order = place(client, "PR2")
    changed = deepcopy(lab_spec)
    next(entity for entity in changed["entities"] if entity["id"] == "PR2")["name"] = "Updated catalog label"
    result = client.put("/api/configuration", headers=headers, json={"specification": changed, "expected_revision": 1})
    assert result.status_code == 200, result.text
    runtime = client.get(f"/api/orders/{order['id']}/graph").json()
    assert runtime["configuration_revision"] == 1
    assert next(node for node in runtime["nodes"] if node["id"] == "PR2")["name"] == "Blue product"
    assert next(product for product in client.get("/api/shop/catalog").json()["products"] if product["id"] == "PR2")["name"] == "Updated catalog label"


def test_guest_order_full_observed_workflow_requires_review_not_gateway(client, lab_spec, monkeypatch):
    headers = setup(client, lab_spec)
    worker(client, headers, "operator@lab.test", ["WS1", "WS2", "WS3", "WS4", "WS5", "WS6", "WS7", "WS9"])
    def forbidden_command(*args, **kwargs):
        raise AssertionError("Observed lab tasks must never issue physical machine commands")
    monkeypatch.setattr(platform_providers.HttpMachineGateway, "dispatch", forbidden_command)
    order = place(client)
    image = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="JPEG")
    for task in order["tasks"]:
        operator_headers = login(client, "operator@lab.test")
        current = next(item for item in client.get("/api/operator/tasks").json() if item["id"] == task["id"])
        assert current["status"] == "in_progress"
        if current["kind"] == "machine":
            assert client.post(f"/api/tasks/{task['id']}/complete", headers=operator_headers).status_code == 409
            started = client.post(f"/api/tasks/{task['id']}/run", headers=operator_headers)
            assert started.status_code == 200, started.text
            assert started.json()["execution_mode"] == "observed"
            assert not started.json()["machine_completed"]
            assert started.json()["dispatch_error"] is None
        uploaded = client.post(f"/api/tasks/{task['id']}/evidence", headers=operator_headers, files={"file": ("evidence.jpg", image.getvalue(), "image/jpeg")})
        assert uploaded.status_code == 200, uploaded.text
        submitted = client.post(f"/api/tasks/{task['id']}/complete", headers=operator_headers)
        assert submitted.status_code == 200 and submitted.json()["status"] == "awaiting_review", submitted.text
        headers = login(client, "admin@lab.test")
        pending = client.get("/api/reviews").json()
        review = next(item for item in pending if item["task_id"] == task["id"])
        approved = client.post(f"/api/reviews/{review['id']}", headers=headers, json={"decision": "approve", "reason": "Specialist verified the entire assigned batch and its evidence"})
        assert approved.status_code == 200, approved.text
    final = client.get(f"/api/orders/{order['id']}").json()
    assert final["status"] == "completed"
    graph = client.get(f"/api/orders/{order['id']}/graph").json()
    assert len([node for node in graph["nodes"] if node["type"] == "evidence"]) == 8
