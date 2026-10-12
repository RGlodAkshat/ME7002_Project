"""Real HTTP contract checks for isolated simulator infrastructure."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).parent
EVENTS = []


class Callback(BaseHTTPRequestHandler):
    def do_POST(self):
        EVENTS.append((self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_):
        pass


class InfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.callback = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
        threading.Thread(target=cls.callback.serve_forever, daemon=True).start()
        with socket.socket() as temporary:
            temporary.bind(("127.0.0.1", 0))
            cls.port = temporary.getsockname()[1]
        cls.token = secrets.token_urlsafe(32)
        cls.callback_url = f"http://127.0.0.1:{cls.callback.server_port}/api/machine/events"
        cls.process = subprocess.Popen(["python3", str(ROOT / "machine-simulator/server.py")],
            env={**os.environ, "PORT": str(cls.port), "MACHINE_EVENT_TOKEN": cls.token,
                 "PLATFORM_CALLBACK_URL": cls.callback_url, "SIMULATOR_OPERATION_SECONDS": "0.1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                cls.request("/health")
                break
            except URLError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Simulator did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.callback.shutdown()
        cls.callback.server_close()

    @classmethod
    def request(cls, path, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token is None and path.startswith("/api/v1/machines/"):
            token = cls.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(f"http://127.0.0.1:{cls.port}{path}",
                          data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

    def command(self, identifier, machine="mill"):
        return {"action": "start", "task_id": f"task-{identifier}", "order_id": "order",
                "dispatch_id": identifier, "external_id": identifier, "callback_url": self.callback_url}

    def wait_for_event(self, identifier, event):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            matches = [(token, item) for token, item in EVENTS if item["dispatch_id"] == identifier and item["event"] == event]
            if matches:
                return matches[0]
            time.sleep(0.02)
        self.fail(f"No {event} callback for {identifier}")

    def test_health_and_capabilities(self):
        self.assertEqual(self.request("/health")[1]["status"], "ok")
        self.assertIn("start", self.request("/v1/capabilities")[1]["commands"])

    def test_idempotent_command_and_authenticated_callbacks(self):
        body = self.command("dedup")
        first = self.request("/api/v1/machines/mill/commands", body)
        self.assertEqual(first, self.request("/api/v1/machines/mill/commands", body))
        token, event = self.wait_for_event("dedup", "completed")
        self.assertEqual(token, f"Bearer {self.token}")
        self.assertEqual(event["external_id"], "dedup:completed")
        self.assertEqual(event["machine_id"], "mill")
        self.assertEqual(len([item for _, item in EVENTS if item["dispatch_id"] == "dedup" and item["event"] == "completed"]), 1)
        with self.assertRaises(HTTPError) as failure:
            self.request("/api/v1/machines/mill/commands", {**body, "task_id": "different"})
        self.assertEqual(failure.exception.code, 409)

    def test_fault_control_requires_token_and_emits_failure(self):
        with self.assertRaises(HTTPError) as failure:
            self.request("/_simulator/faults", {"machine_id": "faulted", "mode": "failed"})
        self.assertEqual(failure.exception.code, 401)
        self.request("/_simulator/faults", {"machine_id": "faulted", "mode": "failed"}, self.token)
        self.request("/api/v1/machines/faulted/commands", self.command("faulted"))
        self.wait_for_event("faulted", "failed")
        self.request("/_simulator/faults", {"machine_id": "faulted", "mode": "healthy"}, self.token)

    def test_callback_cannot_forward_integration_secret(self):
        with self.assertRaises(HTTPError) as failure:
            self.request("/api/v1/machines/mill/commands", {**self.command("bad-url"), "callback_url": "https://other.invalid/events"})
        self.assertEqual(failure.exception.code, 422)

    def test_commands_require_token_and_stop_suppresses_completion(self):
        body = self.command("stop-test")
        with self.assertRaises(HTTPError) as failure:
            self.request("/api/v1/machines/mill/commands", body, "wrong-token")
        self.assertEqual(failure.exception.code, 401)
        self.request("/api/v1/machines/mill/commands", body)
        stop_body = {**body, "action": "stop"}
        acknowledgement = self.request("/api/v1/machines/mill/commands", stop_body)
        self.assertEqual(acknowledgement[1]["status"], "stopped")
        self.assertEqual(acknowledgement, self.request("/api/v1/machines/mill/commands", stop_body))
        time.sleep(0.2)
        self.assertFalse(any(item["dispatch_id"] == "stop-test" and item["event"] == "completed" for _, item in EVENTS))

    def test_secrets_generated_once_and_existing_values_preserved(self):
        module_spec = importlib.util.spec_from_file_location("prepare_secrets", ROOT / "prepare-secrets.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text("OPENAI_MODEL=existing-model\nMACHINE_EVENT_TOKEN=\n")
            module.prepare(env_file, True)
            content = env_file.read_text()
            module.prepare(env_file, True)
            self.assertEqual(content, env_file.read_text())
            self.assertIn("OPENAI_MODEL=existing-model", content)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            values = dict(line.split("=", 1) for line in content.splitlines())
            self.assertGreaterEqual(len(values["MACHINE_EVENT_TOKEN"]), 48)
            self.assertNotEqual(values["MACHINE_EVENT_TOKEN"], values["ADMIN_INTEGRATION_TOKEN"])


if __name__ == "__main__":
    unittest.main()
