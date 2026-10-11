import json
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import Task


class MockMachineGatewayAdapter:
    name = "mock"

    def test_connection(self) -> tuple[bool, str | None]:
        return True, None

    def send_task_event(self, task: Task, event: str) -> None:
        return None


class HttpMachineGatewayAdapter:
    name = "http"

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        url_host = f"[{host}]" if ":" in host else host
        self.base_url = f"http://{url_host}:{port}"
        self.timeout = timeout

    def test_connection(self) -> tuple[bool, str | None]:
        try:
            with urlopen(f"{self.base_url}/health", timeout=self.timeout) as response:
                if 200 <= response.status < 300:
                    return True, None
                return False, f"gateway returned HTTP {response.status}"
        except HTTPError as exc:
            return False, f"gateway returned HTTP {exc.code}"
        except (URLError, TimeoutError, OSError):
            return False, "gateway is unreachable"

    def send_task_event(self, task: Task, event: str) -> None:
        body = json.dumps({
            "commandId": str(uuid4()),
            "machineId": task.machine.code if task.machine else None,
            "action": event,
        }).encode()
        request = Request(
            f"{self.base_url}/v1/commands",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout):
            pass
