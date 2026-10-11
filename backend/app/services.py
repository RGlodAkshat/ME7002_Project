from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .adapters.assignment import LeastLoadedQualifiedAssignment
from .adapters.gateway import HttpMachineGatewayAdapter, MockMachineGatewayAdapter
from .adapters.machines import DatabaseMachineAdapter
from .adapters.verification import MockVerificationProvider, OpenAIVisionVerificationProvider
from .config import Settings
from .models import (Event, Evidence, Machine, MachineGatewaySetting, Operator, Order,
                     ProcessedMachineEvent, Task, VerificationAttempt, utcnow)
from .schemas import MachineGatewayUpdate, OrderCreate, ProductConfiguration, VerificationDecision


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


WORKFLOW = (
    ("Kitting", "manual", "kitting", None, True, "Collect the configured fan parts, arrange them in the kit, and photograph the complete kit."),
    ("CNC machining", "machine", "machining", "cnc", False, "Load the workpiece, confirm the CNC program, and start the assigned CNC machine."),
    ("Assembly stage 1", "manual", "assembly", None, True, "Assemble the base and blade subassembly, then photograph it clearly."),
    ("Automated line", "machine", "automation", "automated_line", False, "Load the assembly on the assigned automated line and confirm the cycle."),
    ("Final assembly", "manual", "assembly", None, True, "Complete final assembly and submit a clear photograph of the finished fan."),
)


def bom(configuration: ProductConfiguration) -> list[dict]:
    variants = {
        "red": {"product_code": "PR1", "parts": (("Base", "CLR", "B6a"), ("Upper", "CUR", "B6b"), ("Handle", "HR", "B7"), ("Blade", "BLR", "B8"), ("Pin2", "P2R", "B9"), ("Pin1", "P1R", "B10"))},
        "green": {"product_code": "PR2", "parts": (("Base", "CLG", "B11a"), ("Upper", "CUG", "B11b"), ("Handle", "HG", "B12"), ("Blade", "BLG", "B13"), ("Pin2", "P2G", "B14"), ("Pin1", "P1G", "B15"))},
        "blue": {"product_code": "PR3", "parts": (("Base", "CLB", "B16a"), ("Upper", "CUB", "B16b"), ("Handle", "HB", "B17"), ("Blade", "BLB", "B18"), ("Pin2", "P2B", "B19"), ("Pin1", "P1B", "B20"))},
        "white": {"product_code": "PR4", "parts": (("Base", "CLW", "B21a"), ("Upper", "CUW", "B21b"), ("Handle", "HW", "B22"), ("Blade", "BLW", "B23"), ("Pin2", "P2W", "B24"), ("Pin1", "P1W", "B25"))},
    }
    common = (("Gear1", "G1", "B1"), ("Gear2", "G2", "B2"), ("Gear3", "G3", "B3"),
              ("Gear4", "G4", "B4"), ("Gear5", "G5", "B5"))
    variant = variants[configuration.color]
    result = [{"component": name, "part_id": part_id, "bin_id": bin_id, "quantity": 1,
               "product_code": variant["product_code"]} for name, part_id, bin_id in common]
    for name, part_id, bin_id in variant["parts"]:
        result.append({"component": name, "part_id": part_id, "bin_id": bin_id,
                       "quantity": 5 if name == "Pin1" else 1, "product_code": variant["product_code"]})
    return result


def add_event(db: Session, event_type: str, entity_type: str, entity_id: int, payload: dict | None = None) -> Event:
    event = Event(event_type=event_type, entity_type=entity_type, entity_id=entity_id, payload=payload or {})
    db.add(event)
    db.flush()
    return event


class WorkflowService:
    def __init__(self) -> None:
        self.assignment = LeastLoadedQualifiedAssignment()
        self.machines = DatabaseMachineAdapter()

    def _task(self, db: Session, task_id: int) -> Task:
        task = db.scalar(select(Task).options(selectinload(Task.evidence)).where(Task.id == task_id))
        if task is None:
            raise DomainError("Task not found", 404)
        return task

    def _assign(self, db: Session, task: Task) -> None:
        task.assigned_operator = self.assignment.choose(db, task)
        if task.machine_capability:
            task.machine = self.machines.choose(db, task.machine_capability)
        if task.assigned_operator and (not task.machine_capability or task.machine):
            task.status = "assigned"
            db.flush()
            add_event(db, "task.assigned", "task", task.id, {"operator_id": task.assigned_operator.id, "machine_id": task.machine_id})
        else:
            task.status = "ready"

    def create_order(self, db: Session, data: OrderCreate) -> Order:
        if not data.confirmed:
            raise DomainError("Order must be explicitly confirmed")
        order = Order(customer_name=data.customer_name, configuration=data.configuration.model_dump(), status="in_progress")
        db.add(order)
        db.flush()
        for position, definition in enumerate(WORKFLOW, start=1):
            name, kind, skill, capability, verify, instructions = definition
            db.add(Task(order_id=order.id, position=position, name=name, kind=kind, required_skill=skill,
                        machine_capability=capability, requires_verification=verify,
                        status="ready" if position == 1 else "blocked", instructions=instructions))
        db.flush()
        first = db.scalar(select(Task).where(Task.order_id == order.id, Task.position == 1))
        assert first is not None
        self._assign(db, first)
        add_event(db, "order.created", "order", order.id, {"configuration": order.configuration})
        db.commit()
        return self.get_order(db, order.id)

    def get_order(self, db: Session, order_id: int) -> Order:
        order = db.scalar(select(Order).options(selectinload(Order.tasks).selectinload(Task.evidence)).where(Order.id == order_id))
        if order is None:
            raise DomainError("Order not found", 404)
        return order

    def accept(self, db: Session, task_id: int, operator_id: int | None = None) -> Task:
        task = self._task(db, task_id)
        if task.status not in {"assigned", "ready"}:
            raise DomainError(f"Cannot accept a task in {task.status} state", 409)
        if operator_id is not None:
            operator = db.get(Operator, operator_id)
            if not operator or not operator.available or task.required_skill not in operator.skills:
                raise DomainError("Operator is unavailable or lacks the required skill", 409)
            task.assigned_operator = operator
        if not task.assigned_operator:
            self._assign(db, task)
        if not task.assigned_operator:
            raise DomainError("No compatible operator is available", 409)
        task.status = "in_progress"
        task.started_at = task.started_at or utcnow()
        add_event(db, "task.accepted", "task", task.id, {"operator_id": task.assigned_operator_id})
        db.commit()
        return self._task(db, task.id)

    def start(self, db: Session, task_id: int) -> Task:
        task = self._task(db, task_id)
        if task.status == "assigned":
            return self.accept(db, task_id)
        if task.status != "in_progress":
            raise DomainError(f"Cannot start a task in {task.status} state", 409)
        return task

    def complete(self, db: Session, task_id: int) -> Task:
        task = self._task(db, task_id)
        if task.status not in {"in_progress", "rejected"}:
            raise DomainError(f"Cannot complete a task in {task.status} state", 409)
        if task.kind == "machine":
            raise DomainError("Machine tasks complete only through a machine event", 409)
        if task.requires_verification:
            if not task.evidence:
                raise DomainError("Photo evidence is required before completion", 409)
            task.status = "awaiting_verification"
            add_event(db, "task.awaiting_verification", "task", task.id)
        else:
            self._finish(db, task)
        db.commit()
        return self._task(db, task.id)

    def machine_event(self, db: Session, task_id: int, event: str, external_id: str | None = None) -> Task:
        task = self._task(db, task_id)
        if task.kind != "machine":
            raise DomainError("Task is not machine-driven", 409)
        if external_id:
            existing = db.scalar(select(ProcessedMachineEvent).where(ProcessedMachineEvent.external_id == external_id))
            if existing:
                if existing.task_id != task_id or existing.event != event:
                    raise DomainError("Machine event ID was already used for a different event", 409)
                return task
            db.add(ProcessedMachineEvent(external_id=external_id, task_id=task_id, event=event))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return self._task(db, task_id)
        if event == "started":
            if task.status not in {"assigned", "in_progress"}:
                raise DomainError(f"Cannot start machine task in {task.status} state", 409)
            task.status, task.started_at = "in_progress", task.started_at or utcnow()
        elif event == "completed":
            if task.status not in {"assigned", "in_progress"}:
                raise DomainError(f"Cannot complete machine task in {task.status} state", 409)
            self._finish(db, task)
        elif event == "failed":
            task.status = "paused"
            if task.machine:
                task.machine.status = "down"
                replacement = self.machines.choose(db, task.machine_capability or "", task.machine.id)
                task.machine = replacement
                task.status = "assigned" if replacement and task.assigned_operator else "ready"
        add_event(db, f"machine.{event}", "task", task.id, {"machine_id": task.machine_id})
        db.commit()
        return self._task(db, task.id)

    def _finish(self, db: Session, task: Task) -> None:
        task.status, task.completed_at = "completed", utcnow()
        add_event(db, "task.completed", "task", task.id)
        next_task = db.scalar(select(Task).where(Task.order_id == task.order_id, Task.position == task.position + 1))
        if next_task:
            next_task.status = "ready"
            self._assign(db, next_task)
        else:
            order = db.get(Order, task.order_id)
            assert order is not None
            order.status = "completed"
            add_event(db, "order.completed", "order", order.id)

    def handoff(self, db: Session, task_id: int, operator_id: int) -> Task:
        task = self._task(db, task_id)
        if task.status not in {"assigned", "in_progress", "rejected"}:
            raise DomainError(f"Cannot hand off a task in {task.status} state", 409)
        operator = db.get(Operator, operator_id)
        if not operator or not operator.available or task.required_skill not in operator.skills:
            raise DomainError("Target operator is unavailable or lacks the required skill", 409)
        old = task.assigned_operator_id
        task.assigned_operator = operator
        task.status = "assigned"
        add_event(db, "task.handed_off", "task", task.id, {"from_operator_id": old, "to_operator_id": operator.id})
        db.commit()
        return self._task(db, task.id)

    async def save_evidence(self, db: Session, task_id: int, upload: UploadFile, directory: Path) -> Evidence:
        task = self._task(db, task_id)
        if task.status not in {"assigned", "in_progress", "rejected"}:
            raise DomainError(f"Cannot add evidence in {task.status} state", 409)
        if not upload.content_type or not upload.content_type.startswith("image/"):
            raise DomainError("Evidence must be an image")
        directory.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename or "image.jpg").suffix.lower() or ".jpg"
        path = directory / f"{uuid4().hex}{suffix}"
        size = 0
        with path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    path.unlink(missing_ok=True)
                    raise DomainError("Evidence image exceeds 10 MB", 413)
                output.write(chunk)
        evidence = Evidence(task_id=task.id, file_path=str(path), content_type=upload.content_type,
                            original_name=upload.filename or path.name)
        db.add(evidence)
        add_event(db, "evidence.created", "task", task.id)
        db.commit()
        db.refresh(evidence)
        return evidence

    def verify(self, db: Session, task_id: int, settings: Settings) -> tuple[Task, VerificationAttempt]:
        task = self._task(db, task_id)
        if task.status != "awaiting_verification":
            raise DomainError("Task is not awaiting verification", 409)
        provider = verification_provider(settings)
        color = task.order.configuration.get("color", "red")
        reference = settings.reference_image_dir / f"{color}.jpg"
        decision = provider.verify(task, [Path(item.file_path) for item in task.evidence], [reference] if reference.exists() else [])
        attempt = VerificationAttempt(task_id=task.id, provider=provider.name, outcome=decision.outcome,
                                      confidence=decision.confidence, reason=decision.reason)
        db.add(attempt)
        if decision.outcome == "approved":
            self._finish(db, task)
        elif decision.outcome == "rejected":
            task.status = "rejected"
        else:
            task.status = "awaiting_manual_review"
        add_event(db, "verification.decided", "task", task.id, decision.model_dump())
        db.commit()
        db.refresh(attempt)
        return self._task(db, task.id), attempt

    def manual_review(self, db: Session, attempt_id: int, decision: VerificationDecision) -> Task:
        attempt = db.get(VerificationAttempt, attempt_id)
        if not attempt:
            raise DomainError("Verification attempt not found", 404)
        task = self._task(db, attempt.task_id)
        if task.status != "awaiting_manual_review":
            raise DomainError("Task is not awaiting manual review", 409)
        attempt.outcome, attempt.confidence, attempt.reason = decision.outcome, 100, decision.reason
        if decision.outcome == "approved":
            self._finish(db, task)
        else:
            task.status = "rejected"
        add_event(db, "verification.reviewed", "task", task.id, decision.model_dump())
        db.commit()
        return self._task(db, task.id)

    def set_operator_availability(self, db: Session, operator_id: int, available: bool) -> Operator:
        operator = db.get(Operator, operator_id)
        if not operator:
            raise DomainError("Operator not found", 404)
        operator.available = available
        if not available:
            tasks = db.scalars(select(Task).where(Task.assigned_operator_id == operator.id,
                                                   Task.status.in_(("assigned", "in_progress", "rejected")))).all()
            for task in tasks:
                task.assigned_operator = None
                task.status = "ready"
                self._assign(db, task)
        add_event(db, "operator.availability_changed", "operator", operator.id, {"available": available})
        db.commit()
        db.refresh(operator)
        return operator

    def set_machine_status(self, db: Session, machine_id: int, status: str) -> Machine:
        machine = db.get(Machine, machine_id)
        if not machine:
            raise DomainError("Machine not found", 404)
        machine.status = status
        if status != "available":
            tasks = db.scalars(select(Task).where(Task.machine_id == machine.id,
                                                   Task.status.in_(("assigned", "in_progress")))).all()
            for task in tasks:
                replacement = self.machines.choose(db, task.machine_capability or "", machine.id)
                task.machine = replacement
                task.status = "assigned" if replacement and task.assigned_operator else "ready"
                add_event(db, "task.rerouted", "task", task.id, {"machine_id": task.machine_id})
        add_event(db, "machine.status_changed", "machine", machine.id, {"status": status})
        db.commit()
        db.refresh(machine)
        return machine


def verification_provider(settings: Settings):
    if settings.verification_provider == "openai" and not settings.openai_api_key:
        raise DomainError("OPENAI_API_KEY is required for the OpenAI verification provider", 503)
    if settings.openai_api_key and settings.verification_provider in {"auto", "openai"}:
        return OpenAIVisionVerificationProvider(settings.openai_api_key, settings.openai_model)
    return MockVerificationProvider()


def get_gateway_setting(db: Session) -> MachineGatewaySetting:
    setting = db.get(MachineGatewaySetting, 1)
    if not setting:
        setting = MachineGatewaySetting(id=1, host="mock-devices", port=9002, protocol="http", enabled=True, use_mock=True)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def gateway_adapter(setting: MachineGatewaySetting):
    if setting.use_mock:
        return MockMachineGatewayAdapter()
    return HttpMachineGatewayAdapter(setting.host, setting.port)


def update_gateway_setting(db: Session, data: MachineGatewayUpdate) -> MachineGatewaySetting:
    setting = get_gateway_setting(db)
    for key, value in data.model_dump().items():
        setattr(setting, key, value)
    add_event(db, "settings.machine_gateway_updated", "machine_gateway", setting.id,
              {"host": setting.host, "port": setting.port, "protocol": setting.protocol,
               "enabled": setting.enabled, "use_mock": setting.use_mock})
    db.commit()
    db.refresh(setting)
    return setting


workflow_service = WorkflowService()
