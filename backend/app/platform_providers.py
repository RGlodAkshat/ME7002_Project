"""Replaceable machine and verification boundaries. No simulation in the platform."""
import base64
import json
import mimetypes
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from .config import get_settings


class MachineGateway(Protocol):
    def dispatch(self, machine_id: str, command: dict) -> None: ...
    def health(self) -> dict: ...


class HttpMachineGateway:
    def __init__(self, configuration: dict):
        host = configuration["host"]
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        self.base_url = f"{configuration['protocol']}://{host}:{configuration['port']}"

    def dispatch(self, machine_id: str, command: dict) -> None:
        response = httpx.post(f"{self.base_url}/api/v1/machines/{quote(machine_id, safe='')}/commands",
                              json=command, timeout=get_settings().gateway_timeout,
                              headers={"Authorization": f"Bearer {get_settings().machine_event_token or ''}"})
        response.raise_for_status()
        acknowledgement = response.json()
        expected_status = "stopped" if command["action"] == "stop" else "accepted"
        if not isinstance(acknowledgement, dict) or acknowledgement.get("dispatch_id") != command["dispatch_id"] or acknowledgement.get("status") != expected_status:
            raise ValueError("Equipment did not acknowledge the expected command and dispatch identifier")

    def health(self) -> dict:
        response = httpx.get(f"{self.base_url}/health", timeout=get_settings().gateway_timeout)
        response.raise_for_status()
        return response.json()


class VerificationProvider(Protocol):
    def verify(self, protocol: dict, task: dict, evidence: list) -> dict: ...


class HumanVerification:
    def verify(self, protocol: dict, task: dict, evidence: list) -> dict:
        return {"outcome": "review", "confidence": 0, "reason": "The configured protocol requires specialist review."}


def image_data(path: Path, content_type: str | None = None) -> str:
    mime = content_type or mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class OpenAIVerification:
    def verify(self, protocol: dict, task: dict, evidence: list) -> dict:
        from openai import OpenAI
        settings = get_settings()
        if not settings.openai_api_key:
            return {"outcome": "review", "confidence": 0, "reason": "Image verification service is unavailable. A specialist must review this submission."}
        content = [{"type": "text", "text": json.dumps({
            "task": task["name"], "parts": task["parts"], "instructions": protocol.get("instructions", []),
            "response": {"outcome": "approved or rejected or review", "confidence": "0-100 integer", "reason": "brief explanation"},
            "instruction": "Evaluate only visible evidence. Missing or ambiguous evidence must require review. Return JSON. The first images are operator evidence; subsequent images are references."})}]
        for item in evidence:
            content.append({"type": "image_url", "image_url": {"url": image_data(Path(item.file_path), item.content_type)}})
        for name in protocol.get("reference_images", []):
            reference = settings.reference_image_dir / name
            if not reference.is_file():
                return {"outcome": "review", "confidence": 0, "reason": "A configured reference image is unavailable."}
            content.append({"type": "image_url", "image_url": {"url": image_data(reference)}})
        try:
            result = OpenAI(api_key=settings.openai_api_key, timeout=30).chat.completions.create(
                model=settings.openai_model, messages=[{"role": "user", "content": content}], response_format={"type": "json_object"})
            answer = json.loads(result.choices[0].message.content)
            if answer.get("outcome") not in {"approved", "rejected", "review"} or not isinstance(answer.get("confidence"), (int, float)) or not 0 <= answer["confidence"] <= 100 or not isinstance(answer.get("reason"), str):
                raise ValueError("Invalid verification response")
            if answer["confidence"] < protocol.get("min_confidence", 80):
                answer["outcome"] = "review"
            return answer
        except Exception:
            return {"outcome": "review", "confidence": 0, "reason": "The image verification service could not complete this submission. Specialist review is required."}


VERIFICATION_PROVIDERS: dict[str, VerificationProvider] = {"human": HumanVerification(), "openai": OpenAIVerification()}


def machine_gateway(configuration: dict) -> MachineGateway:
    return HttpMachineGateway(configuration)
