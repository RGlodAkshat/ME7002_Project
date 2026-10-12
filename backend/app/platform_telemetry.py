"""Read the central telemetry database; never connect to industrial equipment.

Raw rows are observations, not authenticated order-completion events. A machine
reservation and an explicitly opened observation window are required, and only
configured signal rules can establish completion. Ambiguity stays in human review.
"""
import asyncio
import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from .config import get_settings
from .db import SessionLocal
from .platform_configuration import Graph, STATE_LOCK, acquire_state_lock, get_configuration
from .platform_models import Observation, Order, Task, now

LATEST: dict[str, dict] = {}
CONNECTION = {"connected": False, "reason": "Central telemetry database is not configured."}


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Invalid telemetry table or column identifier")
    return f'"{value}"'


@lru_cache(maxsize=2)
def source_engine(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Central telemetry requires a PostgreSQL connection")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0,
                         connect_args={"connect_timeout": 3, "options": "-c statement_timeout=2000 -c default_transaction_read_only=on"}, hide_parameters=True)


def normalize_program(value) -> str:
    name = str(value or "").replace("\\", "/").split("/")[-1].upper()
    name = re.sub(r"\.MPF$", "", name)
    name = re.sub(r"^N_", "", name)
    if re.fullmatch(r"[O0]?\d+", name):
        return str(int(name.removeprefix("O")))
    return name


def apply_signal(rule: dict, state: dict, row: dict) -> tuple[dict, bool]:
    """Pure configured signal reducer. Never treat Online/idle as completion."""
    state = dict(state)
    if rule.get("kind") == "program_sequence":
        if row.get("status") != rule.get("status", "Running"):
            return state, False
        program = normalize_program(row.get(rule.get("program_column", "prog")))
        expected = [normalize_program(code) for code in rule.get("subprograms", [])]
        seen = list(state.get("seen_programs", []))
        if expected and program in expected:
            # Require the configured sequence, not arbitrary programs or a count
            # gathered before this assignment. Repeated same-program samples are fine.
            position = len(seen)
            if position < len(expected) and program == expected[position]:
                seen.append(program)
            elif program not in seen:
                seen = [program] if program == expected[0] else []
            state["seen_programs"] = seen
        completed = bool(expected) and seen == expected and program == normalize_program(rule.get("main_program"))
        return state, completed
    if rule.get("kind") == "falling_edge":
        value = row.get(rule.get("column"))
        if value not in (True, False, 0, 1):
            return state, False
        previous = state.get("previous_signal")
        state["previous_signal"] = bool(value)
        return state, previous is True and value in (False, 0)
    return state, False


def observed(db, task: Task) -> bool:
    order = db.get(Order, task.order_id)
    return Graph(order.snapshot).entity(task.stage_id).get("properties", {}).get("execution_mode") == "observed"


def begin_observation(db, task: Task) -> None:
    item = db.get(Observation, task.id)
    if item is None:
        db.add(Observation(task_id=task.id, dispatch_id=task.command_id, started_at=now(), state={}))
    elif item.dispatch_id != task.command_id:
        item.dispatch_id, item.started_at, item.cursor, item.state = task.command_id, now(), None, {}
    task.dispatch_error = None


def status() -> dict:
    url = get_settings().telemetry_database_url
    source = None
    if url:
        try:
            parsed = make_url(url)
            source = {"host": parsed.host, "port": parsed.port or 5432, "database": parsed.database}
        except Exception:
            pass
    return {"configured": bool(url), "source": source, **CONNECTION, "machines": LATEST.copy()}


def clean_row(row) -> dict:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in dict(row).items()}


def read_rows(connection, config: dict, observation: Observation | None) -> list[dict]:
    table, timestamp = config["table"], config.get("timestamp_column", "ts")
    identifier(table); identifier(timestamp)
    columns = {item["name"] for item in inspect(connection).get_columns(table)}
    if timestamp not in columns:
        raise ValueError("Configured timestamp column is missing")
    identity = config.get("identity_column")
    conditions, params = [], {}
    if identity:
        identifier(identity)
        if identity not in columns:
            raise ValueError("Configured machine identity column is missing")
        conditions.append(f"{identifier(identity)} = :machine")
        params["machine"] = config["identity"]
    watermark = "platform_ingest_id" if "platform_ingest_id" in columns else timestamp
    if observation:
        if observation.cursor:
            conditions.append(f"{identifier(watermark)} > :cursor")
            params["cursor"] = int(observation.cursor) if watermark == "platform_ingest_id" else datetime.fromisoformat(observation.cursor)
        started = observation.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if timestamp == "Timestamp":
            started = started.astimezone(ZoneInfo(get_settings().telemetry_timezone)).replace(tzinfo=None)
        conditions.append(f"{identifier(timestamp)} >= :started")
        params["started"] = started
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order = "ASC" if observation else "DESC"
    limit = 1000 if observation else 1
    query = f"SELECT * FROM {identifier(table)}{where} ORDER BY {identifier(watermark)} {order} LIMIT {limit}"
    rows = [clean_row(row) for row in connection.execute(text(query), params).mappings()]
    for row in rows:
        row["_cursor"] = str(row[watermark])
    return rows


def sync_once() -> None:
    url = get_settings().telemetry_database_url
    if not url:
        return
    from . import platform_service as service
    try:
        with source_engine(url).connect() as source, STATE_LOCK, SessionLocal() as db:
            # Never hold a platform transaction while waiting for a network connect.
            acquire_state_lock(db)
            config = get_configuration(db)["specification"]
            if not config:
                return
            for machine in config["entities"]:
                telemetry = machine.get("properties", {}).get("telemetry")
                if machine["type"] != "machine" or not telemetry:
                    continue
                try:
                    rows = read_rows(source, telemetry, None)
                    LATEST[machine["id"]] = {"connected": True, "latest": rows[0] if rows else None, "checked_at": now().isoformat()}
                except Exception:
                    # A missing optional table must not block other machine sources.
                    source.rollback()
                    LATEST[machine["id"]] = {"connected": False, "reason": "Telemetry table or configured columns are unavailable."}
            for task in db.query(Task).filter(Task.kind == "machine", Task.status.in_(["in_progress", "paused"]), Task.command_id.is_not(None), Task.machine_completed.is_(False)).all():
                if db.get(Order, task.order_id).status in {"cancelling", "cancelled"}:
                    continue
                observation = db.get(Observation, task.id)
                if not observation or observation.dispatch_id != task.command_id:
                    continue
                graph = Graph(db.get(Order, task.order_id).snapshot)
                machine = graph.entities.get(task.machine_id) or next((entity for entity in config["entities"] if entity["id"] == task.machine_id), {})
                telemetry = machine.get("properties", {}).get("telemetry")
                if not telemetry or not observed(db, task):
                    continue
                try:
                    rows = read_rows(source, telemetry, observation)
                    state = dict(observation.state)
                    for row in rows:
                        state, complete = apply_signal(telemetry.get("completion", {}), state, row)
                        state["latest"] = row
                        observation.cursor = row["_cursor"]
                        if complete:
                            task.machine_completed = True
                            view = service.task_view(db, task)
                            task.status = "in_progress" if view["verification"] or (view["scrap"] and view["scrap"].get("required")) else "completed"
                            break
                    observation.state = state
                except Exception:
                    source.rollback()
                    task.dispatch_error = "Central telemetry is unavailable. Completion requires specialist review."
            db.flush()
            service.schedule(db)
            db.commit()
        CONNECTION.update(connected=True, reason="Central database connected; completion remains subject to configured rules and verification.")
    except Exception:
        # Database errors may embed connection strings. Do not expose/log them.
        CONNECTION.update(connected=False, reason="Central telemetry database could not be read. Check connection settings and read permissions.")


async def monitor() -> None:
    while True:
        if get_settings().telemetry_database_url:
            await asyncio.to_thread(sync_once)
        await asyncio.sleep(max(1.0, get_settings().telemetry_poll_seconds))
