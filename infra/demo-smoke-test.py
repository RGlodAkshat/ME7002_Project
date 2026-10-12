#!/usr/bin/env python3
"""Explicit isolated-demo integration check; creates orders and approves test images.

Never use against a working lab installation. Independent publishers must be running.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import time

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def checked(response):
    assert response.is_success, f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text[:300]}"
    return response.json()


def authenticate(api, account):
    client = httpx.Client(base_url=api, timeout=15)
    answer = checked(client.post("/api/auth/login", json={key: account[key] for key in ("email", "password")}))
    client.headers["X-CSRF-Token"] = answer["csrf_token"]
    return client, answer["user"]


def run(args):
    directory = args.directory.resolve()
    assert directory.is_relative_to(ROOT / ".run"), "Only ignored isolated demo directories are allowed"
    accounts = json.loads((directory / "credentials.json").read_text())["accounts"]
    clients = []
    admin_account = next(account for account in accounts if account["role"] == "admin")
    admin, _ = authenticate(args.api, admin_account)
    clients.append(admin)
    workers = {}
    for account in accounts:
        if account["role"] == "operator":
            client, user = authenticate(args.api, account)
            clients.append(client)
            workers[user["id"]] = (client, user)
    picture = BytesIO()
    Image.new("RGB", (96, 96), "green").save(picture, "PNG")
    report = {"stages": [], "completed": False, "pending_cancellation": False, "safe_started_cancellation": False}
    specification = checked(admin.get("/api/configuration"))["specification"]
    rules = {entity["id"]: entity.get("properties", {}).get("telemetry", {}).get("completion", {})
             for entity in specification["entities"] if entity["type"] == "machine"}

    def create_order(label):
        return checked(admin.post("/api/shop/orders", json={"product_id": "PR1", "selections": {},
                                                               "customer_name": label, "confirmed": True}))

    def current(order_id):
        return checked(admin.get(f"/api/orders/{order_id}"))

    def finish(order_id, task):
        operator, user = workers[task["assigned_operator_id"]]
        assert user["qualifications"], "Lab assignment must use an issued ontology qualification"
        if task["kind"] == "machine":
            if not task["command_id"]:
                checked(operator.post(f"/api/tasks/{task['id']}/run", json={}))
            if rules[task["machine_id"]].get("kind") in {"program_sequence", "falling_edge"}:
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    task = next(item for item in current(order_id)["tasks"] if item["id"] == task["id"])
                    if task["machine_completed"]:
                        break
                    time.sleep(0.5)
                assert task["machine_completed"], "Actual PostgreSQL observations must complete the configured signal rule before review"
            else:
                assert task["verification"]["provider"] == "human", "Unknown raw completion semantics require specialist review"
        if task.get("scrap"):
            checked(operator.post(f"/api/tasks/{task['id']}/scrap", json={"quantity": 0, "reason": ""}))
        if task.get("verification"):
            checked(operator.post(f"/api/tasks/{task['id']}/evidence", files={"file": ("integration-test.png", picture.getvalue(), "image/png")}))
        submitted = checked(operator.post(f"/api/tasks/{task['id']}/complete", json={}))
        if submitted["status"] == "awaiting_review":
            review = next(item for item in checked(admin.get("/api/reviews")) if item["task_id"] == task["id"])
            checked(admin.post(f"/api/reviews/{review['id']}", json={"decision": "approve", "reason": "Isolated synthetic-image integration test only"}))
        print(f"Verified {task['name']}: qualified worker, signal gate and configured review.", flush=True)

    try:
        unfinished = [order for order in checked(admin.get("/api/orders")) if order["customer_name"] == "Isolated demo full-route integration test"
                      and order["status"] not in {"completed", "cancelled", "cancelling"}]
        order = unfinished[0] if unfinished else create_order("Isolated demo full-route integration test")
        report["stages"] = [task["name"] for task in order["tasks"] if task["status"] == "completed"]
        for _ in range(8 - len(report["stages"])):
            order = current(order["id"])
            task = next(task for task in order["tasks"] if task["status"] == "in_progress")
            finish(order["id"], task)
            report["stages"].append(task["name"])
        order = current(order["id"])
        assert order["status"] == "completed"
        graph = checked(admin.get(f"/api/orders/{order['id']}/graph"))
        assert graph["nodes"] and graph["relationships"]
        report.update(completed=True, order_id=order["id"], graph_nodes=len(graph["nodes"]), graph_relationships=len(graph["relationships"]))
        pending = create_order("Isolated pending cancellation test")
        cancelled = checked(admin.post(f"/api/orders/{pending['id']}/cancel", json={"reason": "Pending test order withdrawn"}))
        assert cancelled["status"] == "cancelled"
        assert all(task["status"] == "cancelled" for task in cancelled["tasks"])
        report["pending_cancellation"] = True
        started = create_order("Isolated running cancellation test")
        finish(started["id"], next(task for task in started["tasks"] if task["status"] == "in_progress"))
        stage = next(task for task in current(started["id"])["tasks"] if task["status"] == "in_progress")
        operator, _ = workers[stage["assigned_operator_id"]]
        checked(operator.post(f"/api/tasks/{stage['id']}/run", json={}))
        held = checked(admin.post(f"/api/orders/{started['id']}/cancel", json={"reason": "Stop simulation safely"}))
        assert held["status"] == "cancelling"
        held_task = next(task for task in held["tasks"] if task["id"] == stage["id"])
        assert held_task["status"] == "paused" and held_task["machine_id"] and held_task["assigned_operator_id"]
        assert operator.post(f"/api/tasks/{stage['id']}/complete", json={}).status_code == 409
        checked(admin.post(f"/api/tasks/{stage['id']}/confirm-stopped", json={"physical_stop_confirmed": True}))
        assert current(started["id"])["status"] == "cancelled"
        report["safe_started_cancellation"] = True
        (directory / "smoke-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Full lab route, actual PostgreSQL completion, order graph and both cancellation paths passed.", flush=True)
    finally:
        for client in clients:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    run(parser.parse_args())
