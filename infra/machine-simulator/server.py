"""Standalone gateway simulator: the platform uses the same HTTP boundary as equipment.

Only Python's standard library is required. Callback deliveries retry with stable event
IDs. Fault controls are infrastructure APIs, never manufacturing product features.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote


def environment_value(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value is not None:
        return value
    env_file = Path(os.environ.get("PLATFORM_ENV_FILE", "backend/.env"))
    if env_file.exists():
        for line in reversed(env_file.read_text().splitlines()):
            if line.startswith(f"{key}="):
                return line.partition("=")[2].strip().strip("\"'")
    return default


CALLBACK_URL = environment_value("PLATFORM_CALLBACK_URL", "http://127.0.0.1:8083/api/machine/events")
EVENT_TOKEN = environment_value("MACHINE_EVENT_TOKEN")
DURATION = float(environment_value("SIMULATOR_OPERATION_SECONDS", "4"))
LOCK = threading.RLock()
COMMANDS: dict[str, dict] = {}
FAULTS: dict[str, str] = {}


def callback(command: dict, event: str) -> bool:
    event_id = f"{command['dispatch_id']}:{event}"
    payload = {
        "task_id": command["task_id"], "machine_id": command["machine_id"],
        "event": event, "external_id": event_id, "dispatch_id": command["dispatch_id"],
    }
    request = Request(command.get("callback_url") or CALLBACK_URL, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {EVENT_TOKEN}",
    })
    for attempt in range(8):
        try:
            with urlopen(request, timeout=5) as response:
                if response.status < 300:
                    return True
        except HTTPError as error:
            # A task superseded during recovery must not be resurrected by late telemetry.
            if error.code in (404, 409):
                print(f"callback {event_id} no longer applicable: HTTP {error.code}", flush=True)
                return False
            print(f"callback {event_id} attempt {attempt + 1}: HTTP {error.code}", flush=True)
        except (URLError, TimeoutError, OSError):
            print(f"callback {event_id} attempt {attempt + 1}: connection unavailable", flush=True)
        time.sleep(min(0.5 * (2 ** attempt), 8))
    return False


def run_operation(command: dict) -> None:
    with LOCK:
        if COMMANDS[command["dispatch_id"]]["state"] == "stopped":
            return
    callback(command, "started")
    time.sleep(DURATION)
    with LOCK:
        fault = FAULTS.get(command["machine_id"])
        current = COMMANDS[command["dispatch_id"]]
        if current["state"] == "stopped":
            return
        event = "failed" if fault else "completed"
        current["state"] = event
    delivered = callback(command, event)
    with LOCK:
        COMMANDS[command["dispatch_id"]]["callback_delivered"] = delivered


class Handler(BaseHTTPRequestHandler):
    server_version = "MachineGateway/1.0"

    def reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self.reply(200, {"status": "ok", "version": "1.0"})
        elif self.path == "/v1/capabilities":
            self.reply(200, {"protocolVersion": "1.0", "commands": ["start", "stop"], "events": ["started", "completed", "failed"]})
        elif self.path.startswith("/v1/commands/"):
            with LOCK:
                command = COMMANDS.get(self.path.removeprefix("/v1/commands/"))
                self.reply(200, command) if command else self.reply(404, {"detail": "Unknown command"})
        else:
            self.reply(404, {"detail": "Unknown endpoint"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 100_000:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected JSON object")
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {"detail": "Invalid JSON request"})
            return
        if self.path == "/_simulator/faults":
            if self.headers.get("Authorization") != f"Bearer {EVENT_TOKEN}" or not EVENT_TOKEN:
                self.reply(401, {"detail": "Integration token required"})
                return
            machine_id = body.get("machine_id")
            if not isinstance(machine_id, str) or body.get("mode") not in ("failed", "healthy"):
                self.reply(422, {"detail": "machine_id and mode failed|healthy are required"})
                return
            with LOCK:
                if body["mode"] == "healthy":
                    FAULTS.pop(machine_id, None)
                else:
                    FAULTS[machine_id] = body["mode"]
            self.reply(200, {"machine_id": machine_id, "mode": body["mode"]})
            return
        prefix = "/api/v1/machines/"
        if not self.path.startswith(prefix) or not self.path.endswith("/commands"):
            self.reply(404, {"detail": "Unknown endpoint"})
            return
        if self.headers.get("Authorization") != f"Bearer {EVENT_TOKEN}" or not EVENT_TOKEN:
            self.reply(401, {"detail": "Integration token required"})
            return
        machine_id = unquote(self.path[len(prefix):-len("/commands")])
        body = {**body, "machine_id": machine_id}
        if any(not isinstance(body.get(key), str) or not body[key] for key in ("dispatch_id", "machine_id", "task_id", "order_id")) or body.get("action") not in ("start", "stop"):
            self.reply(422, {"detail": "dispatch_id, task_id, order_id and action=start|stop required"})
            return
        if body.get("callback_url", CALLBACK_URL) != CALLBACK_URL:
            self.reply(422, {"detail": "callback_url must match the configured platform callback"})
            return
        with LOCK:
            prior = COMMANDS.get(body["dispatch_id"])
            if body["action"] == "stop":
                if not prior:
                    self.reply(404, {"detail": "Unknown dispatch attempt"})
                    return
                if any(prior["request"][key] != body[key] for key in ("machine_id", "task_id", "order_id")):
                    self.reply(409, {"detail": "Dispatch does not belong to this machine/task"})
                    return
                if prior["state"] not in ("running", "stopped"):
                    self.reply(409, {"detail": "Operation already finished; reconcile its callback"})
                    return
                prior["state"] = "stopped"
                acknowledgement = prior.setdefault("stop_acknowledgement", {"dispatch_id": body["dispatch_id"], "status": "stopped", "timestamp": int(time.time())})
                self.reply(202, acknowledgement)
                return
            if prior and prior["request"] != body:
                self.reply(409, {"detail": "Command ID already used with different content"})
                return
            if prior:
                self.reply(202, prior["acknowledgement"])
                return
            acknowledgement = {"dispatch_id": body["dispatch_id"], "status": "accepted", "timestamp": int(time.time())}
            COMMANDS[body["dispatch_id"]] = {"request": body, "state": "running", "acknowledgement": acknowledgement}
        self.reply(202, acknowledgement)
        threading.Thread(target=run_operation, args=(body,), daemon=True).start()

    def log_message(self, fmt: str, *args: object) -> None:
        print("gateway", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    if not EVENT_TOKEN:
        raise SystemExit("Set MACHINE_EVENT_TOKEN or PLATFORM_ENV_FILE before starting the simulator")
    port = int(environment_value("PORT", "9002"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
