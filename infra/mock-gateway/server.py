"""Minimal HTTP/JSON stand-in for the single lab machine-gateway PC."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import time
import uuid


class Handler(BaseHTTPRequestHandler):
    server_version = "SmartOperatorMockGateway/1.0"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._reply(200, {"status": "ok", "adapter": "mock", "version": "1.0"})
            return
        if self.path == "/v1/capabilities":
            self._reply(200, {"protocolVersion": "1.0", "commands": ["start", "stop", "reset"]})
            return
        self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/commands":
            self._reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._reply(400, {"error": "invalid_json"})
            return
        required = {"commandId", "machineId", "action"}
        if not required.issubset(payload):
            self._reply(422, {"error": "missing_fields", "required": sorted(required)})
            return
        self._reply(
            202,
            {
                "commandId": payload["commandId"],
                "gatewayEventId": str(uuid.uuid4()),
                "status": "accepted",
                "timestamp": int(time.time()),
            },
        )

    def log_message(self, fmt: str, *args: object) -> None:
        print("gateway", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "9002"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
