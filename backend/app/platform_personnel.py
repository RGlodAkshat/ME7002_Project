"""Executable personnel requirements from ontology relationships.

Portable role/skill/qualification definitions are separate from operational user
credentials and administrator-issued qualification facts. Legacy configurations
without personnel relationships retain their original skill-list behavior.
"""
from .platform_models import UserQualification


def requirements(graph, stage_id: str) -> dict:
    skill_links = graph.related(stage_id, "requires_skill")
    qualification_links = graph.related(stage_id, "requires_qualification")
    skills = [item["id"] for item in skill_links]
    for qualification in qualification_links:
        skills.extend(item["id"] for item in graph.related(qualification["id"], "qualification_grants_skill"))
    if not skill_links and not qualification_links:
        skills = graph.entity(stage_id).get("properties", {}).get("required_skills", [])
    return {"skills": sorted(set(skills)), "qualifications": sorted(item["id"] for item in qualification_links)}


def role_allows(graph, auth_role: str, qualification_id: str) -> bool:
    roles = [edge["source"] for edge in graph.links
             if edge["type"] == "role_allows_qualification" and edge["target"] == qualification_id]
    return not roles or any(graph.entity(role).get("properties", {}).get("auth_role", role.removeprefix("role-")) == auth_role for role in roles)


def user_qualifications(db, user, graph) -> list[str]:
    return sorted(row.qualification_id for row in db.query(UserQualification).filter(
        UserQualification.user_id == user.id, UserQualification.active.is_(True)).all()
        if row.qualification_id in graph.entities and graph.entity(row.qualification_id)["type"] == "qualification"
        and role_allows(graph, user.role, row.qualification_id))


def effective_skills(db, user, graph) -> list[str]:
    granted = set(user.skills or [])
    for qualification_id in user_qualifications(db, user, graph):
        granted.update(item["id"] for item in graph.related(qualification_id, "qualification_grants_skill"))
    return sorted(granted)


def qualified_user(db, user, graph, stage_id: str) -> bool:
    if user.role != "operator" or not user.active or not user.available:
        return False
    needed = requirements(graph, stage_id)
    issued = set(user_qualifications(db, user, graph))
    return set(needed["qualifications"]) <= issued and set(needed["skills"]) <= set(effective_skills(db, user, graph))


def option_skills(graph) -> list[dict]:
    result = {entity["id"]: {"id": entity["id"], "name": entity["name"], "processes": []}
              for entity in graph.entities.values() if entity["type"] == "skill"}
    for stage in graph.entities.values():
        if stage["type"] != "stage":
            continue
        for skill_id in requirements(graph, stage["id"])["skills"]:
            option = result.setdefault(skill_id, {"id": skill_id, "name": skill_id.replace("_", " ").title(), "processes": []})
            option["processes"].append({"id": stage["id"], "name": stage["name"]})
    return sorted(result.values(), key=lambda item: (item["name"], item["id"]))


def qualifications(graph) -> list[dict]:
    result = []
    for entity in graph.entities.values():
        if entity["type"] != "qualification":
            continue
        identifier = entity["id"]
        granted = sorted(item["id"] for item in graph.related(identifier, "qualification_grants_skill"))
        processes = [{"id": stage["id"], "name": stage["name"]} for stage in graph.entities.values()
                     if stage["type"] == "stage" and identifier in requirements(graph, stage["id"])["qualifications"]]
        roles = sorted(link["source"] for link in graph.links if link["type"] == "role_allows_qualification" and link["target"] == identifier)
        result.append({"id": identifier, "name": entity["name"], "skills": granted, "processes": processes,
                       "roles": roles, "description": entity.get("properties", {}).get("description", "")})
    return sorted(result, key=lambda item: (item["name"], item["id"]))
