"""Graph-driven catalog and dependency-aware manufacturing execution."""
from copy import deepcopy
from string import Formatter
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .platform_configuration import Graph, get_configuration, validate_selection_mapping
from .platform_models import Evidence, MachineState, Order, Review, Task, User, uid
from . import platform_providers as providers

ACTIVE = {"in_progress", "awaiting_verification", "awaiting_review", "rejected"}
STOP_PENDING = "Equipment stop was not acknowledged. This assignment is reserved while the system retries."


def active_graph(db: Session) -> Graph:
    specification = get_configuration(db)["specification"]
    if not specification:
        raise HTTPException(409, "The manufacturing environment has not been configured")
    return Graph(specification)


def catalog(db: Session) -> dict:
    wrapper = get_configuration(db)
    if not wrapper["specification"]:
        return {"environment": None, "products": []}
    graph = Graph(wrapper["specification"])
    return {"environment": graph.spec["environment"], "products": [
        {"id": entity["id"], "name": entity["name"], "description": entity.get("properties", {}).get("description", ""),
         "slots": graph.slots(entity["id"]), "visual": entity.get("properties", {}).get("visual", [])}
        for entity in graph.entities.values() if entity["type"] == "product"]}


def validate_product(graph: Graph, product_id: str, selections: dict) -> dict:
    product = graph.entities.get(product_id)
    if not product or product["type"] != "product":
        return {"valid": False, "errors": ["Unknown product"], "bom": [], "paths": []}
    selections = deepcopy(selections)
    slots = graph.slots(product_id)
    for slot in slots:
        if not slot["configurable"] and slot["id"] not in selections:
            selections[slot["id"]] = slot["variants"][0]["id"]
    errors = validate_selection_mapping(graph, product_id, selections, "Configuration")
    errors += [f"Choose {slot['label']}" for slot in slots if slot["id"] not in selections]
    bom = []
    if not errors:
        for slot in slots:
            variant = graph.entity(selections[slot["id"]])
            props = variant.get("properties", {})
            bom.append({"slot_id": slot["id"], "part_id": slot["part_id"], "variant_id": variant["id"], "name": variant["name"],
                        "quantity": slot["quantity"], "bin": props.get("bin", ""), "image_url": props.get("image_url"), "color": props.get("color")})
        for rule in graph.spec.get("constraints", []):
            if rule["product_id"] != product_id:
                continue
            matches = all(selections.get(key) == value for key, value in rule.get("when", {}).items())
            invalid = (rule["kind"] == "requires" and matches and not all(selections.get(key) == value for key, value in rule["then"].items()))
            invalid |= rule["kind"] == "excludes" and matches
            if rule["kind"] == "match_property":
                values = [graph.entity(selections[slot]).get("properties", {}).get(rule["property"]) for slot in rule["slots"]]
                invalid = any(value is None for value in values) or any(value != values[0] for value in values[1:])
            if invalid:
                errors.append(rule.get("name", f"Configuration violates {rule['id']}"))
    paths = []
    if not errors:
        for link in sorted(graph.outgoing(product_id, "uses_path"), key=lambda item: item.get("properties", {}).get("priority", 0), reverse=True):
            if all(selections.get(slot) == variant for slot, variant in link.get("properties", {}).get("conditions", {}).items()):
                path = graph.entity(link["target"])
                paths.append({"id": path["id"], "name": path["name"]})
        if not paths:
            errors.append("No manufacturing path supports these selections")
    return {"valid": not errors, "errors": errors, "bom": bom, "paths": paths, "selections": selections}


class RoutingStrategy(Protocol):
    def choose_path(self, graph: Graph, paths: list[dict], machines: list[dict]) -> str: ...


class CapabilityRouting:
    """Prefer executable paths, then configured priority; reserve resources later."""
    def choose_path(self, graph: Graph, paths: list[dict], machines: list[dict]) -> str:
        for path in paths:
            if all(stage.get("properties", {}).get("kind") != "machine" or any(
                set(cap["id"] for cap in graph.related(stage["id"], "requires_capability")) <= set(machine["capabilities"])
                and machine["status"] == "available" and not machine.get("task_id") for machine in machines)
                for stage in graph.related(path["id"], "has_stage")):
                return path["id"]
        return paths[0]["id"]


ROUTING_STRATEGY: RoutingStrategy = CapabilityRouting()


class AssignmentStrategy(Protocol):
    def operator(self, users: list[User], task: Task, busy: set) -> User | None: ...
    def machine(self, machines: list[dict], task: Task, busy: set) -> dict | None: ...


class SkilledAvailabilityAssignment:
    def operator(self, users: list[User], task: Task, busy: set) -> User | None:
        return next((user for user in users if user.id not in busy and set(task.required_skills) <= set(user.skills)), None)

    def machine(self, machines: list[dict], task: Task, busy: set) -> dict | None:
        return next((machine for machine in machines if machine["id"] not in busy and machine["status"] == "available" and set(task.capabilities) <= set(machine["capabilities"])), None)


ASSIGNMENT_STRATEGY: AssignmentStrategy = SkilledAvailabilityAssignment()


def machines(db: Session) -> list[dict]:
    wrapper = get_configuration(db)
    if not wrapper["specification"]:
        return []
    graph = Graph(wrapper["specification"])
    reservations = {task.machine_id: task for task in db.query(Task).filter(Task.status.in_(ACTIVE | {"paused"}), Task.machine_id.is_not(None)).all()}
    result = []
    for entity in graph.entities.values():
        if entity["type"] != "machine":
            continue
        state = db.get(MachineState, entity["id"])
        reservation = reservations.get(entity["id"])
        result.append({"id": entity["id"], "name": entity["name"],
                       "capabilities": [cap["id"] for cap in graph.related(entity["id"], "has_capability")],
                       "plants": [plant["id"] for plant in graph.related(entity["id"], "located_at")],
                       "status": state.status if state else "available", "task_id": reservation.id if reservation else None,
                       "assigned_operator_id": reservation.assigned_operator_id if reservation else None})
    return result


def create_order(db: Session, product_id: str, selections: dict, customer_name: str) -> Order:
    wrapper = get_configuration(db)
    graph = active_graph(db)
    result = validate_product(graph, product_id, selections)
    if not result["valid"]:
        raise HTTPException(400, "; ".join(result["errors"]))
    product_plants = {plant["id"] for plant in graph.related(product_id, "located_at")}
    available_machines = [machine for machine in machines(db) if not product_plants or product_plants & set(machine["plants"])]
    path_id = ROUTING_STRATEGY.choose_path(graph, result["paths"], available_machines)
    order = Order(id=uid(), customer_name=customer_name, product_id=product_id, product_name=graph.entity(product_id)["name"],
                  selections=result["selections"], configuration_revision=wrapper["revision"], snapshot=deepcopy(graph.spec), path_id=path_id)
    db.add(order)
    stages = graph.ordered_stages(path_id)
    mapping = {stage["id"]: uid() for stage in stages}
    for position, stage in enumerate(stages):
        props = stage.get("properties", {})
        db.add(Task(id=mapping[stage["id"]], order_id=order.id, stage_id=stage["id"], position=position,
                    name=stage["name"], kind=props["kind"], required_skills=props.get("required_skills", []),
                    capabilities=[cap["id"] for cap in graph.related(stage["id"], "requires_capability")],
                    dependencies=[mapping[edge["source"]] for edge in graph.links if edge["type"] == "precedes" and edge["target"] == stage["id"] and edge["source"] in mapping]))
    db.flush()
    schedule(db)
    return order


def release(task: Task) -> None:
    task.assigned_operator_id = None
    task.machine_id = None
    task.command_id = None
    task.machine_completed = False


def dispatch_task(db: Session, task: Task) -> None:
    configuration = get_configuration(db)["specification"].get("gateway")
    try:
        if not configuration:
            raise ValueError("No machine gateway is configured")
        providers.machine_gateway(configuration).dispatch(task.machine_id, {
            "action": "start", "task_id": task.id, "order_id": task.order_id,
            "dispatch_id": task.command_id, "external_id": task.command_id,
            "callback_url": get_settings().machine_callback_url})
        task.dispatch_error = None
    except Exception:
        task.dispatch_error = "The equipment command could not be acknowledged. The system will retry."


def stop_task(db: Session, task: Task) -> bool:
    if not task.command_id or task.machine_completed:
        return True
    configuration = get_configuration(db)["specification"].get("gateway")
    try:
        if not configuration:
            raise ValueError("No gateway")
        providers.machine_gateway(configuration).dispatch(task.machine_id, {
            "action": "stop", "task_id": task.id, "order_id": task.order_id,
            "dispatch_id": task.command_id, "external_id": task.command_id,
            "callback_url": get_settings().machine_callback_url})
        return True
    except Exception:
        return False


def schedule(db: Session) -> None:
    """Called within a serialized reservation transaction. Dependencies never rely on UI state."""
    db.flush()
    machine_list = machines(db)
    by_machine = {machine["id"]: machine for machine in machine_list}
    users = db.query(User).filter(User.role == "operator", User.active.is_(True), User.available.is_(True)).order_by(User.id).all()
    by_user = {user.id: user for user in users}
    tasks = db.query(Task).order_by(Task.order_id, Task.position).all()
    all_tasks = {task.id: task for task in tasks}
    busy_users, busy_machines = set(), set()
    for task in tasks:
        if task.status == "paused" and task.machine_id and task.dispatch_error == STOP_PENDING:
            if stop_task(db, task):
                release(task)
            else:
                busy_users.add(task.assigned_operator_id)
                busy_machines.add(task.machine_id)
            continue
        if task.status not in ACTIVE:
            continue
        operator = by_user.get(task.assigned_operator_id)
        machine = by_machine.get(task.machine_id) if task.kind == "machine" else None
        order = db.get(Order, task.order_id)
        graph = Graph(order.snapshot)
        plants = {plant["id"] for plant in graph.related(order.product_id, "located_at")}
        valid_operator = operator is not None and set(task.required_skills) <= set(operator.skills)
        valid_machine = task.kind != "machine" or (machine is not None and machine["status"] == "available" and set(task.capabilities) <= set(machine["capabilities"]) and (not plants or plants & set(machine["plants"])))
        if task.status == "awaiting_review":
            # A submitted verification remains attached to its owner until review resolves.
            if task.assigned_operator_id:
                busy_users.add(task.assigned_operator_id)
            if task.machine_id:
                busy_machines.add(task.machine_id)
            continue
        if not valid_operator or not valid_machine:
            task.status = "paused"
            if task.kind == "machine" and not stop_task(db, task):
                task.dispatch_error = STOP_PENDING
                busy_users.add(task.assigned_operator_id)
                busy_machines.add(task.machine_id)
            else:
                task.dispatch_error = "Required operator or equipment is unavailable. The system is selecting a compatible assignment."
                release(task)
        else:
            busy_users.add(task.assigned_operator_id)
            if task.machine_id:
                busy_machines.add(task.machine_id)
    for task in tasks:
        if task.status not in {"queued", "paused"} or task.machine_id or any(all_tasks[dependency].status != "completed" for dependency in task.dependencies):
            continue
        operator = ASSIGNMENT_STRATEGY.operator(users, task, busy_users)
        if not operator:
            continue
        machine = None
        if task.kind == "machine":
            order = db.get(Order, task.order_id)
            graph = Graph(order.snapshot)
            plants = {plant["id"] for plant in graph.related(order.product_id, "located_at")}
            compatible = [machine for machine in machine_list if not plants or plants & set(machine["plants"])]
            machine = ASSIGNMENT_STRATEGY.machine(compatible, task, busy_machines)
            if not machine:
                continue
        task.assigned_operator_id = operator.id
        task.machine_id = machine["id"] if machine else None
        task.status = "in_progress"
        task.dispatch_error = None
        task.machine_completed = False
        busy_users.add(operator.id)
        if machine:
            busy_machines.add(machine["id"])
    for task in tasks:
        if task.status == "in_progress" and task.kind == "machine" and task.dispatch_error and task.machine_id and task.command_id:
            dispatch_task(db, task)
    for order in db.query(Order).all():
        order_tasks = [task for task in tasks if task.order_id == order.id]
        order.status = "completed" if all(task.status == "completed" for task in order_tasks) else ("in_progress" if any(task.status in ACTIVE for task in order_tasks) else "queued")


def task_view(db: Session, task: Task) -> dict:
    order = db.get(Order, task.order_id)
    graph = Graph(order.snapshot)
    result = validate_product(graph, order.product_id, order.selections)
    consumes = graph.outgoing(task.stage_id, "consumes")
    parts = result["bom"]
    if consumes:
        parts = [part for part in parts if any(link["target"] == part["part_id"] and (not link.get("properties", {}).get("slot_id") or link["properties"]["slot_id"] == part["slot_id"]) for link in consumes)]
    machine_name = None
    if task.machine_id:
        current = get_configuration(db)["specification"]
        archived_name = graph.entities.get(task.machine_id, {}).get("name", task.machine_id)
        machine_name = next((entity["name"] for entity in current["entities"] if entity["id"] == task.machine_id), archived_name) if current else archived_name
    values = {"product.name": order.product_name, "machine.name": machine_name or "assigned equipment",
              "parts": ", ".join(f"{part['quantity']} × {part['name']}" + (f" from bin {part['bin']}" if part["bin"] else "") for part in parts)}
    for part in result["bom"]:
        for key in ("name", "bin", "quantity", "color"):
            values[f"parts.{part['slot_id']}.{key}"] = str(part.get(key) or "")
    instructions = []
    for guidance in graph.related(task.stage_id, "uses_guidance"):
        properties = guidance.get("properties", {})
        completion_phase = task.kind == "machine" and task.machine_completed and properties.get("completion_instructions")
        if not completion_phase:
            for part in parts:
                part_values = {f"part.{key}": str(part.get(key) or "") for key in ("name", "quantity", "bin", "slot_id", "color")}
                for template in properties.get("part_instructions", []):
                    instructions.append("".join(literal + (part_values[field] if field is not None else "") for literal, field, _, _ in Formatter().parse(template)))
        for template in properties.get("completion_instructions" if completion_phase else "instructions", []):
            instructions.append("".join(literal + (values[field] if field is not None else "") for literal, field, _, _ in Formatter().parse(template)))
    verification = graph.related(task.stage_id, "uses_verification")
    scrap = graph.related(task.stage_id, "uses_scrap")
    evidence = db.query(Evidence).filter(Evidence.task_id == task.id).order_by(Evidence.created_at).all()
    reviewed_ids = {identifier for review in db.query(Review).filter(Review.task_id == task.id).all() for identifier in review.evidence_ids}
    return {"id": task.id, "order_id": task.order_id, "name": task.name, "kind": task.kind, "status": task.status,
            "dependencies": task.dependencies, "assigned_operator_id": task.assigned_operator_id,
            "machine_id": task.machine_id, "machine_name": machine_name, "product_name": order.product_name,
            "instructions": instructions, "parts": parts,
            "instruction_phase": "completion" if task.kind == "machine" and task.machine_completed else ("preparation" if task.kind == "machine" else "work"),
            "verification": deepcopy(verification[0].get("properties", {})) if verification else None,
            "scrap": deepcopy(scrap[0].get("properties", {})) if scrap else None, "scrap_report": task.scrap_report,
            "machine_completed": task.machine_completed, "dispatch_error": task.dispatch_error,
            "command_id": task.command_id, "machine_started": task.command_id is not None,
            "evidence": [{"id": item.id, "url": f"/api/evidence/{item.id}", "name": item.name} for item in evidence],
            "has_fresh_evidence": any(item.id not in reviewed_ids for item in evidence),
            "verification_outcome": task.verification_outcome, "verification_reason": task.verification_reason}


def order_view(db: Session, order: Order) -> dict:
    tasks = [task_view(db, task) for task in db.query(Task).filter(Task.order_id == order.id).order_by(Task.position).all()]
    graph = Graph(order.snapshot)
    return {"id": order.id, "customer_name": order.customer_name, "product_id": order.product_id,
            "product_name": order.product_name, "selections": order.selections, "status": order.status,
            "configuration_revision": order.configuration_revision, "created_at": order.created_at.isoformat(), "tasks": tasks,
            "route": {"path_id": order.path_id, "path_name": graph.entity(order.path_id)["name"], "nodes": tasks,
                      "edges": [{"source": dependency, "target": task["id"]} for task in tasks for dependency in task["dependencies"]]}}


def own_task(db: Session, task_id: str, user: User) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.assigned_operator_id != user.id:
        raise HTTPException(403, "This work is assigned to another operator")
    return task


def complete_task(db: Session, task: Task) -> None:
    if task.status not in {"in_progress", "rejected"}:
        raise HTTPException(409, "This task cannot be completed in its current state")
    view = task_view(db, task)
    if task.kind == "machine" and not task.machine_completed:
        raise HTTPException(409, "Equipment completion must be confirmed by the machine interface")
    if view["scrap"] and view["scrap"].get("required") and task.scrap_report is None:
        raise HTTPException(409, "Submit the required scrap report before finishing")
    if view["verification"]:
        evidence = db.query(Evidence).filter(Evidence.task_id == task.id).order_by(Evidence.created_at).all()
        if not evidence:
            raise HTTPException(409, "Capture or upload evidence before submitting this stage")
        previous = db.query(Review).filter(Review.task_id == task.id).all()
        reviewed_ids = {identifier for review in previous for identifier in review.evidence_ids}
        if task.verification_outcome == "rejected" and not any(item.id not in reviewed_ids for item in evidence):
            raise HTTPException(409, "Upload new evidence before resubmitting rejected work")
        if task.verification_outcome == "rejected":
            evidence = [item for item in evidence if item.id not in reviewed_ids]
        provider = providers.VERIFICATION_PROVIDERS[view["verification"]["provider"]]
        try:
            answer = provider.verify(view["verification"], view, evidence)
            if not isinstance(answer, dict) or answer.get("outcome") not in {"approved", "rejected", "review"} or not isinstance(answer.get("reason"), str):
                raise ValueError("Invalid verification result")
            if answer["outcome"] == "approved" and (not isinstance(answer.get("confidence"), (int, float)) or answer["confidence"] < view["verification"].get("min_confidence", 80)):
                answer = {"outcome": "review", "reason": "The verification confidence is below the configured threshold. Specialist review is required."}
        except Exception:
            answer = {"outcome": "review", "reason": "Verification could not be completed. Specialist review is required."}
        task.verification_outcome = answer["outcome"]
        task.verification_reason = answer["reason"]
        if answer["outcome"] == "approved":
            task.status = "completed"
        elif answer["outcome"] == "rejected":
            task.status = "rejected"
            db.add(Review(task_id=task.id, reason=answer["reason"], status="rejected", evidence_ids=[item.id for item in evidence]))
        else:
            task.status = "awaiting_review"
            db.add(Review(task_id=task.id, reason=answer["reason"], evidence_ids=[item.id for item in evidence]))
    else:
        task.status = "completed"
    db.flush()
    schedule(db)
