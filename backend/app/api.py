from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import get_db
from .events import broadcaster
from .models import Event, Evidence, Machine, Operator, Order, Task, VerificationAttempt
from .schemas import (
    AvailabilityUpdate, ConfigurationProposal, ConfigurationValidation, ConversationRequest,
    ConversationResponse, EventRead, EvidenceRead, HandoffRequest,
    MachineEvent, MachineGatewayRead, MachineGatewayUpdate, MachineRead, MachineStatusUpdate,
    ManualReview, OperatorRead, OrderCreate, OrderRead, ProductConfiguration, TaskAcceptRequest,
    TaskRead, VerificationDecision, VerificationRead,
)
from .services import (
    DomainError, bom, gateway_adapter, get_gateway_setting, update_gateway_setting, workflow_service,
)


router = APIRouter(prefix="/api")


def handle(error: DomainError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.message) from error


async def announce(kind: str, entity_id: int) -> None:
    await broadcaster.publish({"type": kind, "entity_id": entity_id})


@router.get("/catalog")
def catalog() -> dict:
    return {
        "product": "Table fan",
        "options": {
            "color": ["red", "green", "blue", "white"],
        },
        "variants": {color: {"bom": bom(ProductConfiguration(color=color))} for color in ("red", "green", "blue", "white")},
        "compatibility": "All variants share one fixed design; color selects the part and bin identifiers.",
    }


@router.post("/configurations/validate", response_model=ConfigurationValidation)
def validate_configuration(configuration: ProductConfiguration) -> ConfigurationValidation:
    return ConfigurationValidation(valid=True, configuration=configuration, bom=bom(configuration))


def _mock_proposal(data: ConversationRequest) -> ConfigurationProposal:
    text = data.message.lower()
    color = next((value for value in ("red", "green", "blue", "white") if value in text), None)
    if data.current_configuration:
        color = color or data.current_configuration.color
    if color:
        reply = f"I propose the {color} fan variant. Please confirm to place the order."
    else:
        reply = "Please choose red, green, blue, or white."
    return ConfigurationProposal(color=color, reply=reply)


@router.post("/configurations/converse", response_model=ConversationResponse)
async def converse_configuration(data: ConversationRequest, db: Session = Depends(get_db),
                                 settings: Settings = Depends(get_settings)):
    proposal: ConfigurationProposal
    if settings.openai_api_key:
        try:
            from openai import OpenAI
            proposal = OpenAI(api_key=settings.openai_api_key).responses.parse(
                model=settings.openai_model,
                input=[{"role": "system", "content": (
                    "You configure table fans. Color is the only configurable option; valid colors are red, green, "
                    "blue, and white. Extract only a valid color. Ask concisely for missing information and, once "
                    "complete, ask the customer to confirm. Never claim an order was placed."
                )}, {"role": "user", "content": data.message}],
                text_format=ConfigurationProposal,
            ).output_parsed or _mock_proposal(data)
        except Exception:
            proposal = _mock_proposal(data)
    else:
        proposal = _mock_proposal(data)
    configuration = None
    if proposal.color:
        configuration = ProductConfiguration(color=proposal.color)
    if data.confirmed:
        if data.current_configuration and data.current_configuration.color:
            configuration = ProductConfiguration(color=data.current_configuration.color)
        if not configuration:
            raise HTTPException(409, "A complete configuration is required before confirmation")
        order = workflow_service.create_order(
            db, OrderCreate(customer_name=data.customer_name, configuration=configuration, confirmed=True)
        )
        await announce("order.created", order.id)
        return ConversationResponse(message=f"Order {order.id} has been placed.", proposed_configuration=configuration,
                                    configuration=configuration, requires_confirmation=False, order_id=order.id)
    return ConversationResponse(message=proposal.reply, proposed_configuration=configuration,
                                configuration=configuration, requires_confirmation=configuration is not None)


@router.post("/orders", response_model=OrderRead, status_code=201)
async def create_order(data: OrderCreate, db: Session = Depends(get_db)):
    try:
        order = workflow_service.create_order(db, data)
    except DomainError as error:
        handle(error)
    await announce("order.created", order.id)
    return order


@router.get("/orders", response_model=list[OrderRead])
def list_orders(db: Session = Depends(get_db)):
    return db.scalars(select(Order).options(selectinload(Order.tasks).selectinload(Task.evidence)).order_by(Order.id.desc())).all()


@router.get("/orders/{order_id}", response_model=OrderRead)
def get_order(order_id: int, db: Session = Depends(get_db)):
    try:
        return workflow_service.get_order(db, order_id)
    except DomainError as error:
        handle(error)


@router.get("/operators", response_model=list[OperatorRead])
def list_operators(db: Session = Depends(get_db)):
    return db.scalars(select(Operator).order_by(Operator.id)).all()


@router.get("/operators/{operator_id}/tasks", response_model=list[TaskRead])
def operator_tasks(operator_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(Task).options(selectinload(Task.evidence), selectinload(Task.assigned_operator), selectinload(Task.machine))
        .where(Task.assigned_operator_id == operator_id, Task.status != "completed").order_by(Task.id)
    ).all()


@router.put("/operators/{operator_id}/availability", response_model=OperatorRead)
@router.post("/operators/{operator_id}/availability", response_model=OperatorRead, include_in_schema=False)
async def operator_availability(operator_id: int, data: AvailabilityUpdate, db: Session = Depends(get_db)):
    try:
        operator = workflow_service.set_operator_availability(db, operator_id, data.available)
    except DomainError as error:
        handle(error)
    await announce("operator.updated", operator.id)
    return operator


@router.get("/machines", response_model=list[MachineRead])
def list_machines(db: Session = Depends(get_db)):
    return db.scalars(select(Machine).order_by(Machine.id)).all()


@router.put("/machines/{machine_id}/status", response_model=MachineRead)
@router.post("/machines/{machine_id}/status", response_model=MachineRead, include_in_schema=False)
async def machine_status(machine_id: int, data: MachineStatusUpdate, db: Session = Depends(get_db)):
    try:
        machine = workflow_service.set_machine_status(db, machine_id, data.status)
    except DomainError as error:
        handle(error)
    await announce("machine.updated", machine.id)
    return machine


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)):
    try:
        return workflow_service._task(db, task_id)
    except DomainError as error:
        handle(error)


@router.post("/tasks/{task_id}/accept", response_model=TaskRead)
async def accept_task(task_id: int, data: TaskAcceptRequest | None = None, db: Session = Depends(get_db)):
    try:
        task = workflow_service.accept(db, task_id, data.operator_id if data else None)
    except DomainError as error:
        handle(error)
    await announce("task.updated", task.id)
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskRead)
async def start_task(task_id: int, db: Session = Depends(get_db)):
    try:
        task = workflow_service.start(db, task_id)
    except DomainError as error:
        handle(error)
    if task.kind == "machine":
        setting = get_gateway_setting(db)
        if setting.enabled:
            try:
                gateway_adapter(setting).send_task_event(task, "start")
            except Exception as error:
                raise HTTPException(502, "Machine gateway command failed") from error
    await announce("task.updated", task.id)
    return task


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: int, db: Session = Depends(get_db)):
    try:
        task = workflow_service.complete(db, task_id)
    except DomainError as error:
        handle(error)
    await announce("task.updated", task.id)
    return task


@router.post("/tasks/{task_id}/handoff", response_model=TaskRead)
async def handoff_task(task_id: int, data: HandoffRequest, db: Session = Depends(get_db)):
    try:
        task = workflow_service.handoff(db, task_id, data.to_operator_id)
    except DomainError as error:
        handle(error)
    await announce("task.updated", task.id)
    return task


@router.post("/tasks/{task_id}/evidence", response_model=EvidenceRead, status_code=201)
async def upload_evidence(task_id: int, file: Annotated[UploadFile, File()], db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings)):
    try:
        evidence = await workflow_service.save_evidence(db, task_id, file, settings.evidence_dir)
    except DomainError as error:
        handle(error)
    await announce("evidence.created", task_id)
    return evidence


@router.get("/evidence/{evidence_id}/file")
def evidence_file(evidence_id: int, db: Session = Depends(get_db)):
    evidence = db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(404, "Evidence not found")
    return FileResponse(evidence.file_path, media_type=evidence.content_type)


@router.post("/tasks/{task_id}/verify")
async def verify_task(task_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        task, attempt = workflow_service.verify(db, task_id, settings)
    except DomainError as error:
        handle(error)
    await announce("verification.decided", task.id)
    return {"task": TaskRead.model_validate(task), "verification_id": attempt.id,
            "outcome": attempt.outcome, "confidence": attempt.confidence, "reason": attempt.reason}


@router.post("/verifications/{verification_id}/review", response_model=TaskRead)
async def review_verification(verification_id: int, data: ManualReview, db: Session = Depends(get_db)):
    outcome = "approved" if data.decision in {"approve", "approved"} else "rejected"
    try:
        task = workflow_service.manual_review(
            db, verification_id, VerificationDecision(outcome=outcome, confidence=100, reason=data.reason)
        )
    except DomainError as error:
        handle(error)
    await announce("verification.reviewed", task.id)
    return task


@router.get("/verifications", response_model=list[VerificationRead])
def list_verifications(status: str | None = Query(None), db: Session = Depends(get_db)):
    query = select(VerificationAttempt).join(Task, Task.id == VerificationAttempt.task_id).order_by(VerificationAttempt.id.desc())
    if status in {"manual_review", "awaiting_manual_review"}:
        query = query.where(Task.status == "awaiting_manual_review")
    elif status:
        query = query.where(VerificationAttempt.outcome == status)
    attempts = db.scalars(query).all()
    result = []
    for attempt in attempts:
        task = db.get(Task, attempt.task_id)
        if not task:
            continue
        evidence = db.scalar(
            select(Evidence).where(Evidence.task_id == task.id).order_by(Evidence.id.desc())
        )
        result.append({
            "id": attempt.id,
            "task_id": task.id,
            "order_id": task.order_id,
            "provider": attempt.provider,
            "outcome": attempt.outcome,
            "confidence": attempt.confidence,
            "reason": attempt.reason,
            "created_at": attempt.created_at,
            "evidence_url": f"/api/evidence/{evidence.id}/file" if evidence else None,
        })
    return result


@router.post("/machines/tasks/{task_id}/event", response_model=TaskRead)
async def machine_task_event(task_id: int, data: MachineEvent, db: Session = Depends(get_db)):
    try:
        task = workflow_service.machine_event(db, task_id, data.event, data.external_id)
    except DomainError as error:
        handle(error)
    await announce(f"machine.{data.event}", task.id)
    return task


@router.post("/mock/machines/{machine_id}/complete", response_model=TaskRead)
async def mock_machine_complete(machine_id: int, db: Session = Depends(get_db)):
    active_task = db.scalar(
        select(Task).where(Task.machine_id == machine_id, Task.kind == "machine",
                           Task.status.in_(("assigned", "in_progress"))).order_by(Task.id)
    )
    if not active_task:
        raise HTTPException(409, "Machine has no active task")
    try:
        task = workflow_service.machine_event(db, active_task.id, "completed")
    except DomainError as error:
        handle(error)
    await announce("machine.completed", task.id)
    return task


@router.get("/supervisor/tasks", response_model=list[TaskRead])
def supervisor_tasks(status: str | None = Query(None), db: Session = Depends(get_db)):
    query = select(Task).options(selectinload(Task.evidence), selectinload(Task.assigned_operator), selectinload(Task.machine)).order_by(Task.id)
    if status:
        query = query.where(Task.status == status)
    return db.scalars(query).all()


@router.post("/supervisor/tasks/{task_id}/review", response_model=TaskRead)
async def review_task_alias(task_id: int, data: ManualReview, db: Session = Depends(get_db)):
    attempt = db.scalar(select(VerificationAttempt).where(VerificationAttempt.task_id == task_id).order_by(VerificationAttempt.id.desc()))
    if not attempt:
        raise HTTPException(404, "Verification attempt not found")
    return await review_verification(attempt.id, data, db)


@router.get("/events", response_model=list[EventRead])
def list_events(after_id: int = 0, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return db.scalars(select(Event).where(Event.id > after_id).order_by(Event.id).limit(limit)).all()


def gateway_response(setting, test: bool = False) -> MachineGatewayRead:
    reachable = error = None
    if test:
        if not setting.enabled:
            reachable, error = False, "gateway is disabled"
        else:
            reachable, error = gateway_adapter(setting).test_connection()
    return MachineGatewayRead(host=setting.host, port=setting.port, protocol=setting.protocol,
                              enabled=setting.enabled, use_mock=setting.use_mock, configured=True,
                              reachable=reachable, error=error)


@router.get("/settings/machine-gateway", response_model=MachineGatewayRead)
@router.get("/supervisor/gateway", response_model=MachineGatewayRead, include_in_schema=False)
def read_gateway(db: Session = Depends(get_db)):
    return gateway_response(get_gateway_setting(db))


@router.put("/settings/machine-gateway", response_model=MachineGatewayRead)
@router.put("/supervisor/gateway", response_model=MachineGatewayRead, include_in_schema=False)
async def write_gateway(data: MachineGatewayUpdate, db: Session = Depends(get_db)):
    setting = update_gateway_setting(db, data)
    await announce("settings.machine_gateway_updated", setting.id)
    return gateway_response(setting)


@router.post("/settings/machine-gateway/test", response_model=MachineGatewayRead)
@router.post("/supervisor/gateway/test", response_model=MachineGatewayRead, include_in_schema=False)
def test_gateway(db: Session = Depends(get_db)):
    return gateway_response(get_gateway_setting(db), test=True)
