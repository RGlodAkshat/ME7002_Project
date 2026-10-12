from datetime import datetime, timezone
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, text

from app.platform_configuration import validate_specification
from app.platform_models import Observation
from app.platform_telemetry import apply_signal, identifier, normalize_program, read_rows, source_engine, status
from test_platform import admin, apply, spec, user


@pytest.mark.parametrize("raw,expected", [("/N_MILLMAIN.MPF", "MILLMAIN"), ("O2001", "2001"), ("02001", "2001"), ("S_G1", "S_G1")])
def test_program_normalization(raw, expected):
    assert normalize_program(raw) == expected


def test_complete_sequence_required_after_running_signals():
    rule = {"kind": "program_sequence", "status": "Running", "subprograms": ["S_G1", "S_G2"], "main_program": "MILLMAIN"}
    state = {}
    for program in ["MILLMAIN", "S_G1", "S_G2", "MILLMAIN"]:
        state, completed = apply_signal(rule, state, {"prog": program, "status": "Online"})
        assert not completed
    for program, expected in [("MILLMAIN", False), ("S_G2", False), ("S_G1", False), ("S_G1", False), ("S_G2", False), ("MILLMAIN", True)]:
        state, completed = apply_signal(rule, state, {"prog": program, "status": "Running"})
        assert completed == expected


def test_falling_edge_requires_a_prior_true_signal():
    rule = {"kind": "falling_edge", "column": "Conveyor1_ON"}
    state, complete = apply_signal(rule, {}, {"Conveyor1_ON": False})
    assert not complete
    state, complete = apply_signal(rule, state, {"Conveyor1_ON": True})
    assert not complete
    state, complete = apply_signal(rule, state, {"Conveyor1_ON": False})
    assert complete
    assert not apply_signal(rule, state, {"Conveyor1_ON": False})[1]
    assert not apply_signal({"kind": "manual_review"}, {}, {"status": "Online"})[1]


def test_monotonic_cursor_filters_duplicate_timestamps_and_old_batches():
    # SQLite is only a SQL-shape test; real PostgreSQL lab connectivity remains a
    # commissioning check. Integer cursor avoids losing equal-timestamp samples.
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "telemetry_MC1" (platform_ingest_id INTEGER, ts DATETIME, machine_id TEXT, prog TEXT)'))
        for identifier_, timestamp, machine in [(1, "2026-10-12 00:00:00", "MC1"), (2, "2026-10-12 01:00:01", "MC1"), (3, "2026-10-12 01:00:01", "MC1"), (4, "2026-10-12 01:00:02", "MC2")]:
            connection.execute(text('INSERT INTO "telemetry_MC1" VALUES (:id,:ts,:machine,:prog)'), {"id": identifier_, "ts": timestamp, "machine": machine, "prog": "S_G1"})
        config = {"table": "telemetry_MC1", "timestamp_column": "ts", "identity_column": "machine_id", "identity": "MC1"}
        observation = Observation(task_id="task", dispatch_id="batch", started_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc), cursor=None)
        rows = read_rows(connection, config, observation)
        assert [row["_cursor"] for row in rows] == ["2", "3"]
        observation.cursor = "2"
        assert [row["_cursor"] for row in read_rows(connection, config, observation)] == ["3"]
        assert read_rows(connection, config, None)[0]["_cursor"] == "3"


def test_unsafe_source_identifiers_and_non_postgres_connections_rejected():
    with pytest.raises(ValueError):
        identifier('telemetry_MC1"; DROP TABLE orders; --')
    with pytest.raises(ValueError):
        source_engine("sqlite:///anything.db")
    assert "password" not in status()


def test_selected_skills_must_come_from_configured_processes(client):
    headers = admin(client)
    apply(client, headers, spec())
    worker = user(client, headers)
    assert client.patch(f"/api/users/{worker['id']}", headers=headers, json={"skills": ["typo-build"]}).status_code == 400


def test_invalid_telemetry_configuration_is_not_applied():
    value = deepcopy(spec(machine=True))
    machine = next(entity for entity in value["entities"] if entity["type"] == "machine")
    machine["properties"]["telemetry"] = {"table": "unsafe table", "timestamp_column": "ts", "completion": {"kind": "idle_means_done"}}
    assert validate_specification(value)
