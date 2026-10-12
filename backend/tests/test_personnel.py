from copy import deepcopy
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.platform_configuration import Graph, validate_specification
from app.platform_models import User, UserQualification
from app.platform_personnel import effective_skills, option_skills, qualifications, qualified_user, requirements
from app.platform_rdf import convert_turtle
from app import platform_service
from app.platform_configuration import apply_configuration
from app.platform_models import Task

SOURCE = Path(__file__).resolve().parents[2] / "smart_factory_v2_modular_3_final_updated.ttl"


@pytest.fixture(scope="module")
def lab():
    return convert_turtle(SOURCE.read_text())


def test_personnel_is_executable_graph_not_free_text(lab):
    graph = Graph(lab)
    assert requirements(graph, "RS-PR1-2") == {"skills": ["skill-WS2"], "qualifications": ["qualification-WS2"]}
    assert "required_skills" not in graph.entity("RS-PR1-2")["properties"]
    assert len(option_skills(graph)) == 8
    assert len(qualifications(graph)) == 8
    first = next(item for item in qualifications(graph) if item["id"] == "qualification-WS1")
    assert first["roles"] == ["role-operator"] and first["skills"] == ["skill-WS1"]
    assert len(first["processes"]) == 4
    assert not any(entity["type"] in {"user", "login", "session"} for entity in lab["entities"])


def test_manual_skill_strings_cannot_bypass_required_qualification(client, lab):
    graph = Graph(lab)
    with SessionLocal() as db:
        user = User(name="Trained worker", email="worker@personnel.test", password_hash="not-a-login-password", role="operator", skills=["skill-WS1", "skill-WS2"])
        db.add(user)
        db.flush()
        assert not qualified_user(db, user, graph, "RS-PR1-2")
        issued = UserQualification(user_id=user.id, qualification_id="qualification-WS2", active=True)
        db.add(issued)
        db.flush()
        assert qualified_user(db, user, graph, "RS-PR1-2")
        assert not qualified_user(db, user, graph, "RS-PR1-1")
        user.skills = []
        assert effective_skills(db, user, graph) == ["skill-WS2"]
        assert qualified_user(db, user, graph, "RS-PR1-2")
        issued.active = False
        db.flush()
        assert not qualified_user(db, user, graph, "RS-PR1-2")


def test_availability_and_role_are_independent_qualification_gates(client, lab):
    graph = Graph(lab)
    with SessionLocal() as db:
        user = User(name="Worker", email="unavailable@personnel.test", password_hash="not-a-login-password", role="operator", skills=[])
        db.add(user)
        db.flush()
        db.add(UserQualification(user_id=user.id, qualification_id="qualification-WS1", active=True))
        db.flush()
        assert qualified_user(db, user, graph, "RS-PR1-1")
        for attribute in ("available", "active"):
            setattr(user, attribute, False)
            assert not qualified_user(db, user, graph, "RS-PR1-1")
            setattr(user, attribute, True)
        user.role = "admin"
        assert not qualified_user(db, user, graph, "RS-PR1-1")


def test_legacy_configs_keep_skill_list_contract(client):
    graph = Graph({"entities": [{"id": "build", "type": "stage", "name": "Build", "properties": {"required_skills": ["assembly"]}}], "relationships": []})
    with SessionLocal() as db:
        user = User(name="Legacy worker", email="legacy@personnel.test", password_hash="not-a-login-password", role="operator", skills=["assembly"])
        db.add(user)
        db.flush()
        assert requirements(graph, "build") == {"skills": ["assembly"], "qualifications": []}
        assert qualified_user(db, user, graph, "build")
        user.skills = []
        assert not qualified_user(db, user, graph, "build")


def test_relationship_edits_change_eligibility_without_stage_strings(client, lab):
    changed = deepcopy(lab)
    graph = Graph(changed)
    with SessionLocal() as db:
        user = User(name="Qualified worker", email="relationships@personnel.test", password_hash="not-a-login-password", role="operator", skills=[])
        db.add(user)
        db.flush()
        db.add(UserQualification(user_id=user.id, qualification_id="qualification-WS2", active=True))
        db.flush()
        assert qualified_user(db, user, graph, "RS-PR1-2")
        grant = next(link for link in graph.links if link["source"] == "qualification-WS2" and link["type"] == "qualification_grants_skill")
        grant["target"] = "skill-WS1"
        assert not qualified_user(db, user, graph, "RS-PR1-2")
        required = next(link for link in graph.links if link["source"] == "RS-PR1-2" and link["type"] == "requires_skill")
        required["target"] = "skill-WS1"
        assert qualified_user(db, user, graph, "RS-PR1-2")
        assert validate_specification(changed) == []


def test_personnel_relationships_cannot_spoof_endpoint_semantics(lab):
    changed = deepcopy(lab)
    relation = next(item for item in changed["relationships"] if item["type"] == "requires_qualification")
    relation["target"] = "MC1"
    declaration = next(item for item in changed["ontology"]["relation_types"] if item["id"] == "requires_qualification")
    declaration["to_types"] = ["machine"]
    assert any("invalid platform relationship endpoints" in error for error in validate_specification(changed))


def test_core_assignments_use_issued_qualifications_and_recover_revocation(client, lab):
    with SessionLocal() as db:
        apply_configuration(db, lab, 0)
        unqualified = User(id="01-unqualified", name="Free text only", email="unqualified@core.test", password_hash="not-a-login-password", role="operator", skills=["skill-WS1"])
        qualified = User(id="02-qualified", name="Issued qualification", email="qualified@core.test", password_hash="not-a-login-password", role="operator", skills=[])
        db.add_all([unqualified, qualified])
        db.flush()
        issued = UserQualification(user_id=qualified.id, qualification_id="qualification-WS1", active=True)
        db.add(issued)
        db.flush()
        order = platform_service.create_order(db, "PR1", {}, "Guest")
        first = db.query(Task).filter(Task.order_id == order.id, Task.position == 0).one()
        assert first.assigned_operator_id == qualified.id
        assert first.required_skills == ["skill-WS1"]
        issued.active = False
        platform_service.schedule(db)
        assert first.assigned_operator_id is None and first.status == "paused"
        db.add(UserQualification(user_id=unqualified.id, qualification_id="qualification-WS1", active=True))
        platform_service.schedule(db)
        assert first.assigned_operator_id == unqualified.id and first.status == "in_progress"


def test_replaceable_assignment_cannot_bypass_core_qualification_gate(client, lab, monkeypatch):
    with SessionLocal() as db:
        apply_configuration(db, lab, 0)
        unqualified = User(id="01-unqualified", name="Unqualified", email="unsafe@strategy.test", password_hash="not-a-login-password", role="operator", skills=["skill-WS1"])
        qualified = User(id="02-qualified", name="Qualified", email="safe@strategy.test", password_hash="not-a-login-password", role="operator", skills=[])
        db.add_all([unqualified, qualified])
        db.flush()
        db.add(UserQualification(user_id=qualified.id, qualification_id="qualification-WS1", active=True))
        db.flush()
        class UnsafeStrategy(platform_service.SkilledAvailabilityAssignment):
            def operator(self, users, task, busy):
                assert all(user.id != unqualified.id for user in users)
                return unqualified
        monkeypatch.setattr(platform_service, "ASSIGNMENT_STRATEGY", UnsafeStrategy())
        order = platform_service.create_order(db, "PR1", {}, "Guest")
        first = db.query(Task).filter(Task.order_id == order.id, Task.position == 0).one()
        assert first.assigned_operator_id is None and first.status == "queued"
