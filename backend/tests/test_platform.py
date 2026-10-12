from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from io import BytesIO
from PIL import Image

from app.platform_configuration import CORE_TYPES, SEMANTICS
from app.db import SessionLocal
from app.platform_models import Configuration, Task, User
from app.platform_service import validate_product
from app.platform_configuration import Graph, validate_specification


PASSWORD = "Strong-password-for-test-73"
image_buffer = BytesIO()
Image.new("RGB", (20, 20), (30, 50, 80)).save(image_buffer, "JPEG")
IMAGE = image_buffer.getvalue()


def admin(client):
    response = client.post("/api/auth/setup", json={"name": "Factory owner", "email": "owner@example.test", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def user(client, headers, name="Worker", skills=None, **kwargs):
    response = client.post("/api/users", headers=headers, json={"name": name, "email": f"{name.lower()}@example.test", "password": PASSWORD,
                          "role": "operator", "skills": skills or ["build"], **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def spec(machine=False, verification=False, parallel=False):
    entities = [
        {"id": "plant", "type": "plant", "name": "Workshop", "properties": {}},
        {"id": "product", "type": "product", "name": "A different manufactured item", "properties": {}},
        {"id": "part", "type": "part", "name": "Shell", "properties": {}},
        {"id": "small", "type": "variant", "name": "Small shell", "properties": {"size": "small", "bin": "S1"}},
        {"id": "large", "type": "variant", "name": "Large shell", "properties": {"size": "large", "bin": "L1"}},
        {"id": "path", "type": "path", "name": "Manufacturing path", "properties": {}},
        {"id": "guide", "type": "guidance", "name": "Shell preparation", "properties": {"instructions": ["Prepare {parts.shell.name} from bin {parts.shell.bin} for {product.name}."]}},
    ]
    links = []

    def edge(kind, source, target, **props):
        links.append({"id": f"r{len(links)}", "type": kind, "source": source, "target": target, "properties": props})

    edge("variant_of", "small", "part")
    edge("variant_of", "large", "part")
    edge("has_slot", "product", "part", slot_id="shell", quantity=2, configurable=True)
    edge("uses_path", "product", "path")
    edge("located_at", "product", "plant")
    stage_ids = ["prepare", "left", "right", "join"] if parallel else ["prepare", "finish"]
    for stage_id in stage_ids:
        entities.append({"id": stage_id, "type": "stage", "name": stage_id.title(), "properties": {"kind": "machine" if machine and stage_id == "prepare" else "manual", "required_skills": ["build"]}})
        edge("has_stage", "path", stage_id)
        edge("uses_guidance", stage_id, "guide")
        edge("consumes", stage_id, "part", slot_id="shell")
    if parallel:
        for source, target in [("prepare", "left"), ("prepare", "right"), ("left", "join"), ("right", "join")]:
            edge("precedes", source, target)
    else:
        edge("precedes", "prepare", "finish")
    if machine:
        entities.append({"id": "capability", "type": "capability", "name": "Cut", "properties": {}})
        edge("requires_capability", "prepare", "capability")
        for machine_id in ("machine-a", "machine-b"):
            entities.append({"id": machine_id, "type": "machine", "name": machine_id, "properties": {}})
            edge("has_capability", machine_id, "capability")
            edge("located_at", machine_id, "plant")
    if verification:
        entities.extend([
            {"id": "verify", "type": "verification", "name": "Inspect work", "properties": {"provider": "human", "instructions": "Confirm both shells are seated.", "reference_images": [], "min_confidence": 80}},
            {"id": "scrap", "type": "scrap", "name": "Waste reporting", "properties": {"required": True, "max_quantity": 2, "reasons": ["Damaged"]}},
        ])
        edge("uses_verification", "prepare", "verify")
        edge("uses_scrap", "prepare", "scrap")
    return {"schema_version": "1.0", "environment": {"id": "workshop", "name": "Workshop"},
            "ontology": {"entity_types": sorted(CORE_TYPES), "relation_types": [{"id": key, "from_types": sorted(value[0]), "to_types": sorted(value[1])} for key, value in SEMANTICS.items()]},
            "entities": entities, "relationships": links, "constraints": [], "gateway": {"host": "127.0.0.1", "port": 9002, "protocol": "http"}}


def apply(client, headers, specification, revision=0):
    response = client.put("/api/configuration", headers=headers, json={"specification": specification, "expected_revision": revision})
    assert response.status_code == 200, response.text
    return response.json()


def order(client):
    response = client.post("/api/shop/orders", json={"product_id": "product", "selections": {"shell": "small"}, "customer_name": "Purchaser", "confirmed": True})
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_installation_auth_and_role_isolation(client):
    assert client.get("/api/auth/status").json() == {"needs_setup": True}
    assert client.get("/api/shop/catalog").json()["products"] == []
    assert client.get("/api/configuration").status_code == 401
    headers = admin(client)
    assert client.post("/api/auth/setup", json={"name": "Other", "email": "other@test", "password": PASSWORD}).status_code == 409
    assert client.post("/api/users", json={"name": "Bad", "email": "bad@test", "password": PASSWORD}).status_code == 403
    worker = user(client, headers)
    apply(client, headers, spec())
    placed = order(client)
    task = placed["tasks"][0]
    assert task["status"] == "in_progress" and task["assigned_operator_id"] == worker["id"]
    with SessionLocal() as db:
        assert not db.query(User).filter(User.password_hash == PASSWORD).count()
    worker_headers = login(client, worker["email"])
    for path in ("/api/users", "/api/configuration", "/api/orders", "/api/machines", "/api/reviews"):
        assert client.get(path).status_code == 403
    assert client.post(f"/api/tasks/{task['id']}/accept", headers=worker_headers).status_code == 404
    assert client.post("/api/auth/logout", headers=worker_headers).status_code == 200
    assert client.get("/api/operator/tasks").status_code == 401


def test_config_roundtrip_conflicts_graph_cycles_templates_and_second_company(client):
    headers = admin(client)
    original = spec()
    assert not validate_specification(original)
    apply(client, headers, original)
    modified = deepcopy(original)
    modified["entities"][0]["name"] = "Updated server-side plant"
    apply(client, headers, modified, 1)
    exported = client.get("/api/configuration/export").json()
    assert exported == modified
    assert client.put("/api/configuration", headers=headers, json={"specification": original, "expected_revision": 1}).status_code == 409
    apply(client, headers, exported, 2)
    broken = deepcopy(original)
    broken["relationships"].append({"id": "cycle", "type": "precedes", "source": "finish", "target": "prepare", "properties": {}})
    assert any("cycle" in error for error in validate_specification(broken))
    broken = deepcopy(original)
    next(entity for entity in broken["entities"] if entity["id"] == "guide")["properties"]["instructions"] = ["Use {unknown.placeholder}"]
    assert validate_specification(broken)
    broken["relationships"][0]["target"] = "missing"
    assert client.put("/api/configuration", headers=headers, json={"specification": broken, "expected_revision": 3}).status_code == 400
    for filename in ("lab-fan.json", "storage-workshop.json"):
        other = json.loads((Path(__file__).resolve().parents[2] / "configs/examples" / filename).read_text())
        assert not validate_specification(other), validate_specification(other)
        revision = client.get("/api/configuration").json()["revision"]
        apply(client, headers, other, revision)
        assert client.get("/api/shop/catalog").json()["environment"] == other["environment"]


def test_parallel_dependency_gates_and_resource_reservations(client):
    headers = admin(client)
    workers = [user(client, headers, name=f"Worker{index}") for index in range(3)]
    apply(client, headers, spec(parallel=True))
    placed = order(client)
    mapping = {task["name"].lower(): task for task in placed["tasks"]}
    assert mapping["prepare"]["status"] == "in_progress"
    assert all(mapping[name]["status"] == "queued" for name in ("left", "right", "join"))
    assigned = next(worker for worker in workers if worker["id"] == mapping["prepare"]["assigned_operator_id"])
    wh = login(client, assigned["email"])
    assert client.post(f"/api/tasks/{mapping['join']['id']}/complete", headers=wh).status_code == 403
    assert client.post(f"/api/tasks/{mapping['prepare']['id']}/complete", headers=wh).status_code == 200
    ah = login(client, "owner@example.test")
    advanced = client.get(f"/api/orders/{placed['id']}").json()
    active = [task for task in advanced["tasks"] if task["status"] == "in_progress"]
    assert {task["name"] for task in active} == {"Left", "Right"}
    assert len({task["assigned_operator_id"] for task in active}) == 2
    for task in active:
        worker = next(worker for worker in workers if worker["id"] == task["assigned_operator_id"])
        wh = login(client, worker["email"])
        assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 200
    login(client, "owner@example.test")
    completed = client.get(f"/api/orders/{placed['id']}").json()
    assert completed["tasks"][0]["assigned_operator_id"] == mapping["prepare"]["assigned_operator_id"]
    assert completed["tasks"][-1]["status"] == "in_progress"
    assert len(completed["route"]["edges"]) == 4


def test_verification_scrap_resubmission_cross_operator_evidence(client):
    headers = admin(client)
    workers = [user(client, headers, name=f"Worker{index}") for index in range(2)]
    apply(client, headers, spec(verification=True))
    placed = order(client)
    task = placed["tasks"][0]
    owner = next(worker for worker in workers if worker["id"] == task["assigned_operator_id"])
    other = next(worker for worker in workers if worker["id"] != task["assigned_operator_id"])
    wh = login(client, owner["email"])
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/scrap", headers=wh, json={"quantity": 4, "reason": "Damaged"}).status_code == 400
    assert client.post(f"/api/tasks/{task['id']}/scrap", headers=wh, json={"quantity": 0, "reason": ""}).status_code == 200
    image = client.post(f"/api/tasks/{task['id']}/evidence", headers=wh, files={"file": ("evidence.jpg", IMAGE, "image/jpeg")}).json()["evidence"][0]
    oh = login(client, other["email"])
    assert client.get(image["url"]).status_code == 403
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=oh).status_code == 403
    wh = login(client, owner["email"])
    submission = client.post(f"/api/tasks/{task['id']}/complete", headers=wh)
    assert submission.json()["status"] == "awaiting_review"
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 409
    ah = login(client, "owner@example.test")
    pending = client.get("/api/reviews").json()[0]
    assert client.post(f"/api/reviews/{pending['id']}", headers=ah, json={"decision": "reject", "reason": "Wrong count"}).status_code == 200
    wh = login(client, owner["email"])
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 409
    client.post(f"/api/tasks/{task['id']}/evidence", headers=wh, files={"file": ("corrected.jpg", IMAGE, "image/jpeg")})
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).json()["status"] == "awaiting_review"
    ah = login(client, "owner@example.test")
    pending = client.get("/api/reviews").json()[0]
    assert client.post(f"/api/reviews/{pending['id']}", headers=ah, json={"decision": "approve"}).json()["status"] == "completed"
    assert client.get(f"/api/orders/{placed['id']}").json()["tasks"][1]["status"] == "in_progress"


def test_machine_cycle_failure_reroutes_and_stale_callbacks_cannot_advance(client, monkeypatch):
    from app import platform_providers
    commands = []

    class Gateway:
        def dispatch(self, machine_id, command):
            commands.append((machine_id, command))

    monkeypatch.setattr(platform_providers, "machine_gateway", lambda _: Gateway())
    headers = admin(client)
    worker = user(client, headers)
    apply(client, headers, spec(machine=True))
    placed = order(client)
    task = placed["tasks"][0]
    assert commands == []  # assignment never starts machinery before physical preparation
    wh = login(client, worker["email"])
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 409
    started = client.post(f"/api/tasks/{task['id']}/run", headers=wh).json()
    assert started["machine_started"] and len(commands) == 1
    command = commands[-1][1]
    event = {"task_id": task["id"], "machine_id": started["machine_id"], "event": "failed", "external_id": "first-failure", "dispatch_id": command["dispatch_id"]}
    assert client.post("/api/machine/events", json=event).status_code == 401
    mh = {"Authorization": "Bearer test-machine-integration-token"}
    assert client.post("/api/machine/events", headers=mh, json=event).status_code == 200
    assert client.post("/api/machine/events", headers=mh, json=event).json()["duplicate"]
    changed = client.get("/api/operator/tasks").json()[0]
    assert changed["machine_id"] != started["machine_id"] and not changed["machine_started"]
    stale = {**event, "event": "completed", "external_id": "old-completion"}
    assert client.post("/api/machine/events", headers=mh, json=stale).status_code == 409
    restarted = client.post(f"/api/tasks/{task['id']}/run", headers=wh).json()
    done = {**stale, "machine_id": restarted["machine_id"], "dispatch_id": restarted["command_id"], "external_id": "new-completion"}
    assert client.post("/api/machine/events", headers=mh, json=done).status_code == 200
    assert client.post("/api/machine/events", headers=mh, json=done).json()["duplicate"]
    login(client, "owner@example.test")
    route = client.get(f"/api/orders/{placed['id']}").json()
    assert route["tasks"][0]["status"] == "completed" and route["tasks"][0]["machine_id"] == restarted["machine_id"]
    assert route["tasks"][1]["status"] == "in_progress"


def test_snapshots_machine_removal_and_configuration_updates(client):
    headers = admin(client)
    worker = user(client, headers)
    source = spec(machine=True)
    apply(client, headers, source)
    placed = order(client)
    machine_id = placed["tasks"][0]["machine_id"]
    updated = deepcopy(source)
    next(entity for entity in updated["entities"] if entity["id"] == "guide")["properties"]["instructions"] = ["Changed future guidance"]
    apply(client, headers, updated, 1)
    existing = client.get(f"/api/orders/{placed['id']}").json()
    assert existing["configuration_revision"] == 1
    assert existing["tasks"][0]["instructions"] == placed["tasks"][0]["instructions"]
    removed = deepcopy(updated)
    removed["entities"] = [entity for entity in removed["entities"] if entity["id"] != machine_id]
    removed["relationships"] = [link for link in removed["relationships"] if machine_id not in {link["source"], link["target"]}]
    assert client.put("/api/configuration", headers=headers, json={"specification": removed, "expected_revision": 2}).status_code == 409
    assert client.get("/api/configuration").json()["revision"] == 2
    next_task = client.get(f"/api/orders/{placed['id']}").json()["tasks"][0]
    assert client.patch(f"/api/users/{worker['id']}", headers=headers, json={"available": False}).status_code == 200
    assert client.get(f"/api/orders/{placed['id']}").json()["tasks"][0]["status"] == "paused"
    client.patch(f"/api/users/{worker['id']}", headers=headers, json={"available": True})
    assert client.get(f"/api/orders/{placed['id']}").json()["tasks"][0]["status"] == "in_progress"


def test_concurrent_orders_reserve_resources_once_and_concurrent_config_cas(client):
    headers = admin(client)
    worker = user(client, headers)
    source = spec(machine=True)
    apply(client, headers, source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: order(client), range(2)))
    active = [task for result in results for task in result["tasks"] if task["status"] == "in_progress"]
    assert len(active) == 1 and active[0]["assigned_operator_id"] == worker["id"]
    edited = deepcopy(source)
    edited["environment"]["name"] = "Changed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.put("/api/configuration", headers=headers, json={"specification": edited, "expected_revision": 1}), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_generic_combination_rules_and_fixed_parts():
    source = spec()
    source["relationships"].append({"id": "second-slot", "type": "has_slot", "source": "product", "target": "part", "properties": {"slot_id": "lid", "quantity": 1}})
    graph = Graph(source)
    source["constraints"] = [{"id": "matching", "product_id": "product", "kind": "match_property", "name": "Shell and lid sizes must match", "slots": ["shell", "lid"], "property": "size"}]
    assert not validate_product(graph, "product", {"shell": "small", "lid": "large"})["valid"]
    assert validate_product(graph, "product", {"shell": "small", "lid": "small"})["valid"]
    source["constraints"] = [{"id": "requires", "product_id": "product", "kind": "requires", "when": {"shell": "small"}, "then": {"lid": "small"}}]
    assert not validate_product(graph, "product", {"shell": "small", "lid": "large"})["valid"]
    source["constraints"] = [{"id": "excludes", "product_id": "product", "kind": "excludes", "when": {"shell": "large", "lid": "large"}}]
    assert not validate_product(graph, "product", {"shell": "large", "lid": "large"})["valid"]


def test_unavailable_operator_machine_stop_must_acknowledge_before_reassignment(client, monkeypatch):
    from app import platform_providers
    can_stop = False
    commands = []

    class Gateway:
        def dispatch(self, machine_id, command):
            commands.append((machine_id, command))
            if command["action"] == "stop" and not can_stop:
                raise ConnectionError("Equipment is unreachable")

    monkeypatch.setattr(platform_providers, "machine_gateway", lambda _: Gateway())
    headers = admin(client)
    workers = [user(client, headers, name=f"Worker{index}") for index in range(2)]
    source = spec(machine=True)
    apply(client, headers, source)
    placed = order(client)
    task = placed["tasks"][0]
    owner = next(worker for worker in workers if worker["id"] == task["assigned_operator_id"])
    wh = login(client, owner["email"])
    running = client.post(f"/api/tasks/{task['id']}/run", headers=wh).json()
    ah = login(client, "owner@example.test")
    assert client.patch(f"/api/users/{owner['id']}", headers=ah, json={"available": False}).status_code == 200
    held = client.get(f"/api/orders/{placed['id']}").json()["tasks"][0]
    assert held["status"] == "paused" and held["machine_id"] == running["machine_id"]
    assert held["assigned_operator_id"] == owner["id"]
    assert commands[-1][1]["action"] == "stop" and commands[-1][1]["dispatch_id"] == running["command_id"]
    can_stop = True
    reassigned = client.get(f"/api/orders/{placed['id']}").json()["tasks"][0]
    assert reassigned["status"] == "in_progress" and reassigned["assigned_operator_id"] != owner["id"]
    assert not reassigned["machine_started"]


def test_configured_plant_boundaries_and_environment_guard(client):
    headers = admin(client)
    user(client, headers)
    source = spec(machine=True)
    source["entities"].append({"id": "elsewhere", "type": "plant", "name": "Other plant", "properties": {}})
    for link in source["relationships"]:
        if link["type"] == "located_at" and link["source"].startswith("machine"):
            link["target"] = "elsewhere"
    apply(client, headers, source)
    placed = order(client)
    assert placed["tasks"][0]["status"] == "queued" and placed["tasks"][0]["machine_id"] is None
    replaced = deepcopy(source)
    replaced["environment"]["id"] = "another-company"
    assert client.put("/api/configuration", headers=headers, json={"specification": replaced, "expected_revision": 1}).status_code == 409


def test_assistant_interprets_configured_aliases_and_refuses_ambiguous_options(client):
    headers = admin(client)
    source = spec()
    for entity in source["entities"]:
        if entity["id"] == "small":
            entity["properties"]["aliases"] = ["compact casing"]
    apply(client, headers, source)
    result = client.post("/api/shop/converse", json={"product_id": "product", "selections": {}, "message": "Please use the compact casing"}).json()
    assert result["selections"] == {"shell": "small"} and result["requires_confirmation"]
    ambiguous = client.post("/api/shop/converse", json={"product_id": "product", "selections": {}, "message": "small shell and large shell"}).json()
    assert not ambiguous["selections"] and not ambiguous["requires_confirmation"]


def test_provider_failures_and_low_confidence_require_manual_review(client, monkeypatch):
    from app import platform_providers

    class LowConfidence:
        def verify(self, protocol, task, evidence):
            return {"outcome": "approved", "confidence": 12, "reason": "Unsure"}

    headers = admin(client)
    worker = user(client, headers)
    source = spec(verification=True)
    apply(client, headers, source)
    placed = order(client)
    task = placed["tasks"][0]
    wh = login(client, worker["email"])
    assert client.post(f"/api/tasks/{task['id']}/evidence", headers=wh, files={"file": ("invalid.jpg", b"\xff\xd8\xffinvalid", "image/jpeg")}).status_code == 400
    assert client.post(f"/api/tasks/{task['id']}/evidence", headers=wh, files={"file": ("real.jpg", IMAGE, "image/jpeg")}).status_code == 200
    client.post(f"/api/tasks/{task['id']}/scrap", headers=wh, json={"quantity": 0, "reason": ""})
    monkeypatch.setitem(platform_providers.VERIFICATION_PROVIDERS, "human", LowConfidence())
    submitted = client.post(f"/api/tasks/{task['id']}/complete", headers=wh).json()
    assert submitted["status"] == "awaiting_review"
    assert "confidence" in submitted["verification_reason"]


def test_guidance_expands_part_names_bins_and_validates_scope():
    source = spec()
    guide = next(entity for entity in source["entities"] if entity["id"] == "guide")
    guide["properties"]["part_instructions"] = ["Collect {part.quantity} × {part.name} from bin {part.bin}."]
    assert not validate_specification(source)
    guide["properties"]["part_instructions"] = ["Collect {product.password}."]
    assert validate_specification(source)


def test_machine_completion_cannot_bypass_photo_scrap_or_review_gates(client, monkeypatch):
    from app import platform_providers

    class Gateway:
        def dispatch(self, machine_id, command):
            pass

    monkeypatch.setattr(platform_providers, "machine_gateway", lambda _: Gateway())
    headers = admin(client)
    worker = user(client, headers)
    source = spec(machine=True, verification=True)
    guide = next(entity for entity in source["entities"] if entity["id"] == "guide")
    guide["properties"]["completion_instructions"] = ["Unload {parts.shell.name} from {machine.name} and inspect the result."]
    apply(client, headers, source)
    placed = order(client)
    task = placed["tasks"][0]
    wh = login(client, worker["email"])
    running = client.post(f"/api/tasks/{task['id']}/run", headers=wh).json()
    assert running["instruction_phase"] == "preparation"
    assert running["instructions"][0].startswith("Prepare ")
    event = {"task_id": task["id"], "machine_id": running["machine_id"], "dispatch_id": running["command_id"], "event": "completed", "external_id": "cycle-completion"}
    mh = {"Authorization": "Bearer test-machine-integration-token"}
    assert client.post("/api/machine/events", headers=mh, json=event).status_code == 200
    current = client.get("/api/operator/tasks").json()[0]
    assert current["machine_completed"] and current["status"] == "in_progress"
    assert current["instruction_phase"] == "completion"
    assert current["instructions"] == [f"Unload Small shell from {running['machine_name']} and inspect the result."]
    late = client.post("/api/machine/events", headers=mh, json={**event, "event": "failed", "external_id": "late-cycle-failure"})
    assert late.status_code == 200 and late.json()["ignored"]
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).status_code == 409
    client.post(f"/api/tasks/{task['id']}/scrap", headers=wh, json={"quantity": 0, "reason": ""})
    client.post(f"/api/tasks/{task['id']}/evidence", headers=wh, files={"file": ("work.jpg", IMAGE, "image/jpeg")})
    assert client.post(f"/api/tasks/{task['id']}/complete", headers=wh).json()["status"] == "awaiting_review"
    login(client, "owner@example.test")
    workflow = client.get(f"/api/orders/{placed['id']}").json()
    assert workflow["tasks"][1]["status"] == "queued"
    assert workflow["tasks"][0]["machine_completed"]


def test_completion_guidance_templates_use_product_scope():
    source = spec(machine=True)
    guide = next(entity for entity in source["entities"] if entity["id"] == "guide")
    guide["properties"]["completion_instructions"] = ["Unload {parts.shell.name} for {product.name} from {machine.name}."]
    assert not validate_specification(source)
    guide["properties"]["completion_instructions"] = ["Unload {parts.missing_slot.name}."]
    assert validate_specification(source)
    guide["properties"]["completion_instructions"] = "Not a list"
    assert validate_specification(source)


def test_login_throttle_and_readable_input_errors(client):
    from app.platform_auth import LOGIN_FAILURES
    LOGIN_FAILURES.clear()
    admin(client)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "incorrect"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 429
    LOGIN_FAILURES.clear()
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 200
    invalid = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "x" * 257})
    assert invalid.status_code == 422 and isinstance(invalid.json()["detail"], str)


def test_password_whitespace_is_preserved_for_setup_creation_and_reset(client):
    spaced_password = f" {PASSWORD}  "
    created = client.post("/api/auth/setup", json={"name": " Owner ", "email": " owner@example.test ", "password": spaced_password})
    assert created.status_code == 200
    headers = {"X-CSRF-Token": created.json()["csrf_token"]}
    assert created.json()["user"]["name"] == "Owner"
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": spaced_password}).status_code == 200
    headers = {"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]}
    worker = client.post("/api/users", headers=headers, json={"name": "Worker", "email": "worker@example.test", "password": spaced_password, "role": "operator"}).json()
    reset = f"  New-{PASSWORD} "
    assert client.patch(f"/api/users/{worker['id']}", headers=headers, json={"password": reset}).status_code == 200
    assert client.post("/api/auth/login", json={"email": worker["email"], "password": reset.strip()}).status_code == 401
    assert client.post("/api/auth/login", json={"email": worker["email"], "password": reset}).status_code == 200


def test_non_ascii_auth_headers_are_rejected_without_server_error(client):
    admin(client)
    response = client.post("/api/auth/logout", headers={b"X-CSRF-Token": b"invalid-\xff"})
    assert response.status_code == 403
    response = client.post("/api/machine/events", headers={b"Authorization": b"Bearer invalid-\xff"}, json={"task_id": "unknown", "machine_id": "unknown", "dispatch_id": "unknown", "event": "started", "external_id": "unknown"})
    assert response.status_code == 401
