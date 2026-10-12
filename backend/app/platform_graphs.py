"""Configuration-derived access skills and order-specific runtime graphs."""
from copy import deepcopy

from sqlalchemy.orm import Session

from .platform_configuration import Graph, get_configuration
from .platform_models import Evidence, Observation, Order, Task, User
from .platform_personnel import effective_skills, option_skills, user_qualifications


def skills(db: Session) -> list[dict]:
    spec = get_configuration(db)["specification"]
    return option_skills(Graph(spec)) if spec else []


def order_graph(db: Session, order: Order) -> dict:
    graph = Graph(order.snapshot)
    tasks = db.query(Task).filter(Task.order_id == order.id).order_by(Task.position).all()
    included = {order.product_id, order.path_id, *order.selections.values()}
    included.update(task.stage_id for task in tasks)
    for slot in graph.slots(order.product_id):
        included.add(slot["part_id"])
    # Include the actual selected route's requirements, templates and protocols,
    # not alternate products or unrelated branches of the factory.
    for task in tasks:
        for link in graph.links:
            if link["source"] == task.stage_id and link["type"] != "precedes":
                included.add(link["target"])
        if task.machine_id:
            included.add(task.machine_id)
        if task.assigned_operator_id:
            user = db.get(User, task.assigned_operator_id)
            included.update(user_qualifications(db, user, graph))
    # Qualification grants and authorization roles are part of the order's
    # actual process requirements, not unrelated factory personnel definitions.
    for link in graph.links:
        if link["type"] == "qualification_grants_skill" and link["source"] in included:
            included.add(link["target"])
        if link["type"] == "role_allows_qualification" and link["target"] in included:
            included.add(link["source"])
    nodes = [deepcopy(entity) for entity in graph.entities.values() if entity["id"] in included]
    current = get_configuration(db)
    # Newly configured compatible resources can be assigned to an old order.
    # Include the actual resource definition, with provenance, instead of leaving
    # its runtime assignment edge dangling or rewriting the order's snapshot.
    for identifier in included - set(graph.entities):
        resource = next((node for node in (current["specification"] or {}).get("entities", []) if node["id"] == identifier), None)
        if resource:
            resource = deepcopy(resource)
            resource["properties"]["resource_configuration_revision"] = current["revision"]
            nodes.append(resource)
    edges = [deepcopy(link) for link in graph.links if link["source"] in included and link["target"] in included]
    nodes.append({"id": order.id, "type": "order", "name": f"{order.product_name} · {order.customer_name}",
                  "properties": {"status": order.status, "configuration_revision": order.configuration_revision}})

    def edge(source, kind, target, properties=None):
        edges.append({"id": f"{source}:{kind}:{target}", "type": kind, "source": source, "target": target, "properties": properties or {}})

    edge(order.id, "manufactures", order.product_id)
    edge(order.id, "follows_path", order.path_id)
    for slot, variant in order.selections.items():
        edge(order.id, "selects_variant", variant, {"slot_id": slot})
    for task in tasks:
        observation = db.get(Observation, task.id)
        nodes.append({"id": task.id, "type": "operation", "name": task.name, "properties": {
            "status": task.status, "machine_completed": task.machine_completed,
            "verification_outcome": task.verification_outcome, "scrap_report": task.scrap_report,
            "dispatch_id": task.command_id, "dispatch_error": task.dispatch_error,
            "observed_progress": {"programs_seen": observation.state.get("seen_programs", []), "cursor": observation.cursor} if observation and observation.dispatch_id == task.command_id else None}})
        edge(order.id, "has_operation", task.id)
        edge(task.id, "executes_stage", task.stage_id)
        for dependency in task.dependencies:
            edge(dependency, "precedes", task.id)
        if task.machine_id:
            edge(task.id, "assigned_machine", task.machine_id)
        if task.assigned_operator_id:
            user = db.get(User, task.assigned_operator_id)
            if not any(node["id"] == user.id for node in nodes):
                issued = user_qualifications(db, user, graph)
                earned_skills = effective_skills(db, user, graph)
                nodes.append({"id": user.id, "type": "operator", "name": user.name,
                              "properties": {"skills": earned_skills, "qualifications": issued,
                                             "active": user.active, "available": user.available}})
                for qualification_id in issued:
                    edge(user.id, "qualified_for", qualification_id, {"source": "administrator-issued active qualification"})
                for skill_id in earned_skills:
                    if skill_id in included:
                        edge(user.id, "has_skill", skill_id)
                for role in graph.entities.values():
                    if role["type"] == "personnel_role" and role.get("properties", {}).get("auth_role", role["id"].removeprefix("role-")) == user.role:
                        if not any(node["id"] == role["id"] for node in nodes):
                            nodes.append(deepcopy(role))
                        edge(user.id, "has_personnel_role", role["id"])
            edge(task.id, "assigned_operator", user.id)
        for evidence in db.query(Evidence).filter(Evidence.task_id == task.id).all():
            nodes.append({"id": evidence.id, "type": "evidence", "name": evidence.name, "properties": {"url": f"/api/evidence/{evidence.id}"}})
            edge(task.id, "has_evidence", evidence.id)
    return {"order_id": order.id, "configuration_revision": order.configuration_revision, "nodes": nodes, "relationships": edges}
