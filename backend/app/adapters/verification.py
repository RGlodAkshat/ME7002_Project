import base64
from pathlib import Path

from ..models import Task
from ..schemas import VerificationDecision


class MockVerificationProvider:
    name = "mock"

    def verify(self, task: Task, evidence: list[Path], references: list[Path]) -> VerificationDecision:
        if not evidence:
            return VerificationDecision(outcome="rejected", confidence=100, reason="Photo evidence is required.")
        names = {item.original_name.lower() for item in task.evidence}
        if any("manual" in name for name in names):
            return VerificationDecision(
                outcome="manual_review",
                confidence=50,
                reason="Mock verification routed this submission to manual review.",
            )
        if any("reject" in name for name in names):
            return VerificationDecision(
                outcome="rejected",
                confidence=90,
                reason="Mock verification rejected this submission for the demo.",
            )
        return VerificationDecision(
            outcome="approved",
            confidence=90,
            reason="Mock verification approved the submitted evidence for the demo.",
        )


class OpenAIVisionVerificationProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    @staticmethod
    def _image(path: Path) -> str:
        suffix = path.suffix.lower().lstrip(".")
        media = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        return f"data:image/{media};base64,{base64.b64encode(path.read_bytes()).decode()}"

    def verify(self, task: Task, evidence: list[Path], references: list[Path]) -> VerificationDecision:
        content: list[dict] = [{
            "type": "input_text",
            "text": (
                f"Verify manufacturing step '{task.name}'. Instructions: {task.instructions}. "
                "Compare submitted evidence with reference images when supplied. Approve only when the "
                "required work is visibly complete; use manual_review when uncertain."
            ),
        }]
        for path in references[:3]:
            content.extend(({"type": "input_text", "text": "Reference image:"}, {"type": "input_image", "image_url": self._image(path)}))
        for path in evidence:
            content.extend(({"type": "input_text", "text": "Submitted evidence:"}, {"type": "input_image", "image_url": self._image(path)}))
        response = self.client.responses.parse(
            model=self.model,
            input=[{"role": "user", "content": content}],
            text_format=VerificationDecision,
        )
        if response.output_parsed is None:
            return VerificationDecision(outcome="manual_review", confidence=0, reason="AI returned no structured decision.")
        return response.output_parsed
