from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

from .models import Machine, Operator, Task
from .schemas import VerificationDecision


class AssignmentStrategy(Protocol):
    def choose(self, db: Session, task: Task) -> Operator | None: ...


class MachineAdapter(Protocol):
    def choose(self, db: Session, capability: str, exclude_id: int | None = None) -> Machine | None: ...


class VerificationProvider(Protocol):
    name: str

    def verify(self, task: Task, evidence: list[Path], references: list[Path]) -> VerificationDecision: ...


class MachineGatewayAdapter(Protocol):
    name: str

    def test_connection(self) -> tuple[bool, str | None]: ...

    def send_task_event(self, task: Task, event: str) -> None: ...
