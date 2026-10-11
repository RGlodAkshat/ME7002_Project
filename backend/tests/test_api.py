def create_order(client, color="red"):
    response = client.post("/api/orders", json={"configuration": {"color": color}})
    assert response.status_code == 201, response.text
    return response.json()


def test_catalog_validation_and_invalid_option(client):
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["options"] == {"color": ["red", "green", "blue", "white"]}
    validated = client.post("/api/configurations/validate", json={"color": "red"})
    assert validated.status_code == 200
    assert next(part for part in validated.json()["bom"] if part["component"] == "Pin1")["quantity"] == 5
    assert client.post("/api/configurations/validate", json={"color": "purple"}).status_code == 422


def test_order_creates_and_assigns_sequential_workflow(client):
    order = create_order(client)
    assert [task["name"] for task in order["tasks"]] == [
        "Kitting", "CNC machining", "Assembly stage 1", "Automated line", "Final assembly"
    ]
    assert order["tasks"][0]["status"] == "assigned"
    assert all(task["status"] == "blocked" for task in order["tasks"][1:])
    assert order["tasks"][0]["assigned_operator"]["name"] == "Asha"


def test_verified_manual_step_advances_to_machine_task(client):
    order = create_order(client)
    task_id = order["tasks"][0]["id"]
    assert client.post(f"/api/tasks/{task_id}/accept").status_code == 200
    upload = client.post(f"/api/tasks/{task_id}/evidence", files={"file": ("kit.jpg", b"demo image", "image/jpeg")})
    assert upload.status_code == 201, upload.text
    completed = client.post(f"/api/tasks/{task_id}/complete")
    assert completed.json()["status"] == "awaiting_verification"
    verification = client.post(f"/api/tasks/{task_id}/verify")
    assert verification.status_code == 200, verification.text
    assert verification.json()["outcome"] == "approved"
    refreshed = client.get(f"/api/orders/{order['id']}").json()
    assert refreshed["tasks"][0]["status"] == "completed"
    assert refreshed["tasks"][1]["status"] == "assigned"
    assert refreshed["tasks"][1]["machine_id"] is not None


def test_operator_unavailability_reassigns_compatible_task(client):
    order = create_order(client)
    task = order["tasks"][0]
    old_operator = task["assigned_operator_id"]
    response = client.put(f"/api/operators/{old_operator}/availability", json={"available": False})
    assert response.status_code == 200
    refreshed = client.get(f"/api/tasks/{task['id']}").json()
    assert refreshed["assigned_operator_id"] != old_operator
    assert refreshed["status"] == "assigned"


def test_machine_down_reroutes_active_machine_task(client):
    order = create_order(client)
    kitting = order["tasks"][0]
    client.post(f"/api/tasks/{kitting['id']}/accept")
    client.post(f"/api/tasks/{kitting['id']}/evidence", files={"file": ("kit.jpg", b"image", "image/jpeg")})
    client.post(f"/api/tasks/{kitting['id']}/complete")
    client.post(f"/api/tasks/{kitting['id']}/verify")
    machine_task = client.get(f"/api/orders/{order['id']}").json()["tasks"][1]
    old_machine = machine_task["machine_id"]
    response = client.put(f"/api/machines/{old_machine}/status", json={"status": "down"})
    assert response.status_code == 200
    rerouted = client.get(f"/api/tasks/{machine_task['id']}").json()
    assert rerouted["machine_id"] != old_machine
    assert rerouted["status"] == "assigned"


def test_gateway_settings_persist_validate_and_test_mock(client):
    default = client.get("/api/settings/machine-gateway")
    assert default.status_code == 200
    assert default.json()["host"] == "mock-devices"
    update = client.put("/api/settings/machine-gateway", json={
        "host": "lab-gateway.local", "port": 9002, "protocol": "http", "enabled": True, "use_mock": True
    })
    assert update.status_code == 200
    assert client.get("/api/settings/machine-gateway").json()["host"] == "lab-gateway.local"
    result = client.post("/api/settings/machine-gateway/test").json()
    assert result["reachable"] is True
    assert result["error"] is None
    assert client.put("/api/settings/machine-gateway", json={
        "host": "http://unsafe/path", "port": 9002, "protocol": "http", "enabled": True, "use_mock": False
    }).status_code == 422


def test_machine_completion_requires_machine_task(client):
    response = client.post("/api/mock/machines/1/complete")
    assert response.status_code == 409


def test_machine_events_are_idempotent(client):
    order = create_order(client)
    kitting = order["tasks"][0]
    client.post(f"/api/tasks/{kitting['id']}/accept")
    client.post(f"/api/tasks/{kitting['id']}/evidence", files={"file": ("kit.jpg", b"image", "image/jpeg")})
    client.post(f"/api/tasks/{kitting['id']}/complete")
    client.post(f"/api/tasks/{kitting['id']}/verify")
    machine_task = client.get(f"/api/orders/{order['id']}").json()["tasks"][1]
    event = {"event": "completed", "external_id": "cnc-evt-001"}
    first = client.post(f"/api/machines/tasks/{machine_task['id']}/event", json=event)
    assert first.status_code == 200
    duplicate = client.post(f"/api/machines/tasks/{machine_task['id']}/event", json=event)
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "completed"


def test_events_are_persisted(client):
    order = create_order(client)
    events = client.get("/api/events").json()
    assert any(event["event_type"] == "order.created" and event["entity_id"] == order["id"] for event in events)


def test_complete_color_only_workflow(client):
    order = create_order(client, "white")
    for expected_position in range(1, 6):
        current = client.get(f"/api/orders/{order['id']}").json()
        task = current["tasks"][expected_position - 1]
        assert task["position"] == expected_position
        assert task["status"] == "assigned"
        if task["kind"] == "machine":
            response = client.post(f"/api/mock/machines/{task['machine_id']}/complete")
            assert response.status_code == 200, response.text
        else:
            assert client.post(f"/api/tasks/{task['id']}/accept").status_code == 200
            upload = client.post(
                f"/api/tasks/{task['id']}/evidence",
                files={"file": (f"step-{expected_position}.jpg", b"demo image", "image/jpeg")},
            )
            assert upload.status_code == 201, upload.text
            assert client.post(f"/api/tasks/{task['id']}/complete").status_code == 200
            verification = client.post(f"/api/tasks/{task['id']}/verify")
            assert verification.status_code == 200, verification.text
            assert verification.json()["outcome"] == "approved"
    finished = client.get(f"/api/orders/{order['id']}").json()
    assert finished["status"] == "completed"
    assert all(task["status"] == "completed" for task in finished["tasks"])


def test_mock_manual_review_can_be_demonstrated(client):
    order = create_order(client)
    task_id = order["tasks"][0]["id"]
    client.post(f"/api/tasks/{task_id}/accept")
    client.post(
        f"/api/tasks/{task_id}/evidence",
        files={"file": ("manual-review.jpg", b"demo image", "image/jpeg")},
    )
    client.post(f"/api/tasks/{task_id}/complete")
    verification = client.post(f"/api/tasks/{task_id}/verify")
    assert verification.status_code == 200, verification.text
    assert verification.json()["outcome"] == "manual_review"
    attempt_id = verification.json()["verification_id"]
    pending = client.get("/api/verifications?status=manual_review").json()
    assert any(item["id"] == attempt_id for item in pending)
    evidence_url = next(item["evidence_url"] for item in pending if item["id"] == attempt_id)
    assert client.get(evidence_url).content == b"demo image"
    reviewed = client.post(
        f"/api/verifications/{attempt_id}/review",
        json={"decision": "approve", "reason": "Supervisor confirmed the complete kit."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "completed"
