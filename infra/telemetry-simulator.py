#!/usr/bin/env python3
"""Independent demo publishers: insert real lab-shaped PostgreSQL telemetry rows.

Uses ordinary read-only admin HTTP requests to discover opened observation windows.
Never changes platform tasks, approves reviews, or sends machine callbacks.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import signal
import time
from zoneinfo import ZoneInfo

import httpx
import psycopg
from psycopg import sql

RUNNING = True


def stop(*_):
    global RUNNING
    RUNNING = False


def write_row(connection, machine, program=None, active=False):
    config = machine["properties"]["telemetry"]
    timestamp = config.get("timestamp_column", "ts")
    columns = [timestamp]
    values = [datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)] if timestamp == "Timestamp" else [datetime.now().astimezone()]
    if timestamp == "ts":
        columns.extend(["machine_id", "status", "x_pos", "z_pos", "feed", "speed", "prog", "mode", "alarm"])
        values.extend([config.get("identity", machine["id"]), "Running" if active else "Online", 0.0, 0.0,
                       120.0 if active else 0.0, 1000.0 if active else 0.0, program or "---", "AUTO", "NORMAL"])
        if machine["id"] != "MC2":
            columns.append("y_pos")
            values.append(0.0)
    else:
        rule = config.get("completion", {})
        if rule.get("kind") == "falling_edge":
            columns.append(rule["column"])
            values.append(active)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(config["table"]), sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns))
    connection.execute(query, values)


def events(machine):
    rule = machine["properties"]["telemetry"].get("completion", {})
    if rule.get("kind") == "program_sequence":
        return [(code, True) for code in rule.get("subprograms", [])] + [(rule["main_program"], True)]
    if rule.get("kind") == "falling_edge":
        return [(None, True), (None, True), (None, False)]
    return []  # Unknown rules must never be simulated as completion.


def run(args):
    private = json.loads(args.secrets.read_text())
    accounts = json.loads(args.credentials.read_text())["accounts"]
    administrator = next(account for account in accounts if account.get("role") == "admin" and account.get("password"))
    with httpx.Client(base_url=args.api, timeout=10) as client, psycopg.connect(private["writer_url"], autocommit=True) as connection:
        response = client.post("/api/auth/login", json={key: administrator[key] for key in ("email", "password")})
        response.raise_for_status()
        cycles = {}
        finished = set()
        print("Independent CNC and conveyor publishers started; writing PostgreSQL raw tables.", flush=True)
        while RUNNING:
            try:
                configuration = client.get("/api/configuration")
                configuration.raise_for_status()
                specification = configuration.json()["specification"]
                machines = {entity["id"]: entity for entity in specification["entities"]
                            if entity["type"] == "machine" and entity.get("properties", {}).get("telemetry")}
                response = client.get("/api/orders")
                response.raise_for_status()
                active_tasks = {task["machine_id"]: task for order in response.json() for task in order["tasks"]
                                if task.get("execution_mode") == "observed" and task.get("command_id")
                                and task["status"] == "in_progress" and not task.get("machine_completed")}
                for machine_id, machine in machines.items():
                    task = active_tasks.get(machine_id)
                    dispatch = task["command_id"] if task else None
                    if dispatch and dispatch not in finished:
                        if cycles.get(machine_id, {}).get("dispatch") != dispatch:
                            cycles[machine_id] = {"dispatch": dispatch, "events": events(machine), "position": 0}
                            print(f"Publisher {machine_id}: observation window opened; simulated process starting.", flush=True)
                        cycle = cycles[machine_id]
                        if cycle["position"] < len(cycle["events"]):
                            program, active = cycle["events"][cycle["position"]]
                            write_row(connection, machine, program, active)
                            cycle["position"] += 1
                        if cycle["position"] == len(cycle["events"]):
                            finished.add(dispatch)
                    else:
                        write_row(connection, machine)
                        cycles.pop(machine_id, None)
            except (httpx.HTTPError, psycopg.Error, KeyError, TypeError):
                # Connection exceptions can include credentials. Keep logs redacted.
                print("Publishers temporarily unable to read assignments or write telemetry; retrying.", flush=True)
            deadline = time.monotonic() + args.interval
            while RUNNING and time.monotonic() < deadline:
                time.sleep(0.1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8083")
    parser.add_argument("--secrets", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.2:
        parser.error("interval must be at least 0.2 seconds")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        run(args)
    except Exception:
        raise SystemExit("Telemetry publishers could not start. Check private demo credentials and database access.") from None
