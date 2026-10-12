from app.db import SessionLocal
from app.platform_models import Order, Task
from app import platform_providers
from test_platform import admin, apply, spec, user, order, login, IMAGE


def cancel(client, headers, identifier):
    return client.post(f"/api/orders/{identifier}/cancel", headers=headers, json={"reason": "Demo cancelled by customer"})


def test_waiting_order_cancels_without_resurrection(client):
    headers = admin(client)
    apply(client, headers, spec())
    placed = order(client)
    result = cancel(client, headers, placed["id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "cancelled"
    assert all(task["status"] == "cancelled" for task in result.json()["tasks"])
    user(client, headers)
    assert client.get(f"/api/orders/{placed['id']}").json()["status"] == "cancelled"
    assert cancel(client, headers, placed["id"]).json()["status"] == "cancelled"
    assert client.get(f"/api/orders/{placed['id']}/graph").status_code == 200


def test_operator_cannot_cancel_and_cancelled_work_cannot_complete(client):
    headers = admin(client)
    apply(client, headers, spec())
    worker = user(client, headers)
    placed = order(client)
    worker_headers = login(client, worker["email"])
    assert cancel(client, worker_headers, placed["id"]).status_code == 403
    headers = login(client, "owner@example.test")
    assert cancel(client, headers, placed["id"]).json()["status"] == "cancelled"
    worker_headers = login(client, worker["email"])
    assert client.post(f"/api/tasks/{placed['tasks'][0]['id']}/complete", headers=worker_headers).status_code == 409
    assert client.get("/api/operator/tasks").json() == []


def test_observed_cancellation_holds_until_confirmed_physical_stop(client):
    headers = admin(client)
    configuration = spec(machine=True)
    next(item for item in configuration["entities"] if item["id"] == "prepare")["properties"]["execution_mode"] = "observed"
    apply(client, headers, configuration)
    worker = user(client, headers)
    placed = order(client)
    task = placed["tasks"][0]
    worker_headers = login(client, worker["email"])
    assert client.post(f"/api/tasks/{task['id']}/run", headers=worker_headers).status_code == 200
    headers = login(client, "owner@example.test")
    result = cancel(client, headers, placed["id"])
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "cancelling" and body["tasks"][0]["status"] == "paused"
    assert body["tasks"][0]["machine_id"] == task["machine_id"]
    assert body["tasks"][0]["cancellation_pending"]
    machines = client.get("/api/machines").json()
    assert next(item for item in machines if item["id"] == task["machine_id"])["task_id"] == task["id"]
    dispatch = body["tasks"][0]["command_id"]
    event = client.post("/api/machine/events", headers={"Authorization": "Bearer test-machine-integration-token"}, json={
        "task_id": task["id"], "machine_id": task["machine_id"], "dispatch_id": dispatch, "event": "completed", "external_id": "late-cancelled-cycle"})
    assert event.status_code == 200
    body = client.get(f"/api/orders/{placed['id']}").json()
    assert body["status"] == "cancelling" and body["tasks"][0]["status"] == "paused"
    assert client.post(f"/api/tasks/{task['id']}/confirm-stopped", headers=headers, json={"physical_stop_confirmed": True}).status_code == 200
    body = client.get(f"/api/orders/{placed['id']}").json()
    assert body["status"] == "cancelled"
    assert task["id"] in body["cancellation"]["physical_stops"]
    assert all(item["status"] == "cancelled" for item in body["tasks"])


def test_failed_command_stop_keeps_reservation_then_retries(client, monkeypatch):
    class Gateway:
        fails = True
        def dispatch(self, machine, body):
            if body["action"] == "stop" and self.fails:
                raise ConnectionError("Unavailable")
    gateway = Gateway()
    monkeypatch.setattr(platform_providers, "machine_gateway", lambda config: gateway)
    headers = admin(client)
    apply(client, headers, spec(machine=True))
    worker = user(client, headers)
    placed = order(client)
    task = placed["tasks"][0]
    worker_headers = login(client, worker["email"])
    client.post(f"/api/tasks/{task['id']}/run", headers=worker_headers)
    headers = login(client, "owner@example.test")
    body = cancel(client, headers, placed["id"]).json()
    assert body["status"] == "cancelling" and body["tasks"][0]["machine_id"]
    gateway.fails = False
    body = client.get(f"/api/orders/{placed['id']}").json()
    assert body["status"] == "cancelled"
    assert body["tasks"][0]["machine_id"] is None


def test_completed_order_cannot_be_cancelled(client):
    headers = admin(client)
    apply(client, headers, spec())
    placed = order(client)
    with SessionLocal() as db:
        db.get(Order, placed["id"]).status = "completed"
        for task in db.query(Task).filter_by(order_id=placed["id"]):
            task.status = "completed"
        db.commit()
    assert cancel(client, headers, placed["id"]).status_code == 409


def test_cancellation_retains_evidence_and_invalidates_pending_review(client):
    headers = admin(client)
    apply(client, headers, spec(verification=True))
    worker = user(client, headers)
    placed = order(client)
    identifier = placed["tasks"][0]["id"]
    worker_headers = login(client, worker["email"])
    assert client.post(f"/api/tasks/{identifier}/scrap", headers=worker_headers, json={"quantity": 0, "reason": ""}).status_code == 200
    assert client.post(f"/api/tasks/{identifier}/evidence", headers=worker_headers, files={"file": ("kit.jpg", IMAGE, "image/jpeg")}).status_code == 200
    assert client.post(f"/api/tasks/{identifier}/complete", headers=worker_headers).json()["status"] == "awaiting_review"
    headers = login(client, "owner@example.test")
    review = client.get("/api/reviews").json()[0]
    body = cancel(client, headers, placed["id"]).json()
    assert body["status"] == "cancelled" and len(body["tasks"][0]["evidence"]) == 1
    assert client.get("/api/reviews").json() == []
    assert client.post(f"/api/reviews/{review['id']}", headers=headers, json={"decision": "approve", "reason": "Late decision"}).status_code == 409
    assert client.get(f"/api/orders/{placed['id']}/graph").status_code == 200
