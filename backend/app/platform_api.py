"""Role-specific HTTP API backed by graph configuration and workflow services."""
import hmac
import re
from io import BytesIO
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session
from PIL import Image, UnidentifiedImageError

from .config import get_settings
from .db import get_db
from .platform_auth import COOKIE, check_login_rate, create_session, current_user, hash_password, public_user, record_login, require_admin, require_operator, session_for, verify_password
from .platform_configuration import STATE_LOCK, acquire_state_lock, apply_configuration, get_configuration, validate_specification
from .platform_models import Evidence, LoginSession, MachineEvent, MachineState, Order, Review, Task, User, UserQualification, now, uid
from . import platform_service as service
from .platform_providers import machine_gateway

router = APIRouter(prefix="/api")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Password = Annotated[str, StringConstraints(strip_whitespace=False)]


class Credentials(Input):
    email: str = Field(min_length=3, max_length=254)
    password: Password = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if "@" not in value or any(char.isspace() for char in value):
            raise ValueError("Enter a valid email address")
        return value.lower()


class Setup(Credentials):
    name: str = Field(min_length=1, max_length=120)


class NewUser(Setup):
    role: Literal["admin", "operator"] = "operator"
    skills: list[str] = Field(default_factory=list, max_length=100)
    qualifications: list[str] = Field(default_factory=list, max_length=100)
    available: bool = True
    active: bool = True


class UserPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: Password | None = Field(default=None, min_length=10, max_length=256)
    role: Literal["admin", "operator"] | None = None
    skills: list[str] | None = None
    qualifications: list[str] | None = Field(default=None, max_length=100)
    available: bool | None = None
    active: bool | None = None
    email: str | None = Field(default=None, min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return Credentials.valid_email(value) if value is not None else value


class Availability(Input):
    available: bool


class SpecInput(Input):
    specification: dict


class TurtleInput(Input):
    turtle: str = Field(min_length=1, max_length=2_000_000)


class StopConfirmation(Input):
    physical_stop_confirmed: Literal[True]


class CancellationInput(Input):
    reason: str = Field(min_length=1, max_length=2000)


class ApplySpec(SpecInput):
    expected_revision: int = Field(ge=0, strict=True)


class Selection(Input):
    product_id: str
    selections: dict[str, str] = Field(default_factory=dict)


class NewOrder(Selection):
    customer_name: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class Conversation(Selection):
    message: str = Field(min_length=1, max_length=2000)


class Scrap(Input):
    quantity: int = Field(ge=0, strict=True)
    reason: str = Field(max_length=300)


class Decision(Input):
    decision: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=2000)


class MachinePatch(Input):
    status: Literal["available", "down", "maintenance"]


class EventInput(Input):
    task_id: str
    machine_id: str
    event: Literal["started", "completed", "failed"]
    external_id: str = Field(min_length=1, max_length=200)
    dispatch_id: str = Field(min_length=1, max_length=36)


@contextmanager
def transaction(db: Session):
    with STATE_LOCK:
        acquire_state_lock(db)
        try:
            yield
            db.commit()
        except Exception:
            db.rollback()
            raise


@router.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    return {"needs_setup": not bool(db.query(User).first())}


@router.post("/auth/setup")
def setup(body: Setup, response: Response, db: Session = Depends(get_db)):
    with transaction(db):
        if db.query(User).first():
            raise HTTPException(409, "Initial administrator has already been created")
        user = User(name=body.name, email=body.email, password_hash=hash_password(body.password), role="admin", skills=[])
        db.add(user)
        db.flush()
        return create_session(db, user, response)


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    check_login_rate(ip, body.email)
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        record_login(ip, body.email, False)
        raise HTTPException(401, "Email or password is incorrect")
    record_login(ip, body.email, True)
    return create_session(db, user, response)


@router.get("/auth/me")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": public_user(user), "csrf_token": session_for(request, db).csrf_token}


@router.post("/auth/logout")
def logout(request: Request, response: Response, _: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(session_for(request, db))
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/users")
def users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [public_user(user) for user in db.query(User).order_by(User.name).all()]


@router.get("/skills")
def skill_options(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .platform_graphs import skills
    return skills(db)


@router.post("/users")
def add_user(body: NewUser, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        validate_user_skills(db, body.skills)
        if db.query(User).filter(User.email == body.email).first():
            raise HTTPException(409, "An account with this email already exists")
        user = User(**body.model_dump(exclude={"password", "qualifications"}), password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
        issue_qualifications(db, user, body.qualifications, admin)
        service.schedule(db)
        return public_user(user)


@router.patch("/users/{user_id}")
def edit_user(user_id: str, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        updates = body.model_dump(exclude_unset=True)
        if any(value is None for value in updates.values()):
            raise HTTPException(400, "Account fields cannot be null")
        if "skills" in updates:
            validate_user_skills(db, updates["skills"], user.skills)
        if "email" in updates and db.query(User).filter(User.email == updates["email"], User.id != user.id).first():
            raise HTTPException(409, "An account with this email already exists")
        if user.role == "admin" and (updates.get("role", user.role) != "admin" or updates.get("active", True) is False):
            if not db.query(User).filter(User.role == "admin", User.active.is_(True), User.id != user.id).count():
                raise HTTPException(409, "The last active administrator cannot be disabled or demoted")
        if "password" in updates:
            user.password_hash = hash_password(updates.pop("password"))
            for session in db.query(LoginSession).filter(LoginSession.user_id == user.id).all():
                db.delete(session)
        selected = updates.pop("qualifications", None)
        for key, value in updates.items():
            setattr(user, key, value)
        if selected is not None:
            issue_qualifications(db, user, selected, admin)
        db.flush()
        service.schedule(db)
        return public_user(user)


@router.get("/qualifications")
def qualification_options(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .platform_personnel import qualifications
    if get_configuration(db)["specification"] is None:
        return []
    graph = service.active_graph(db)
    return [{**item, "skills": [{"id": identifier, "name": graph.entity(identifier)["name"]} for identifier in item["skills"]]} for item in qualifications(graph)]


def issue_qualifications(db: Session, user: User, selected: list[str], admin: User) -> None:
    from .platform_personnel import role_allows
    existing = {row.qualification_id: row for row in db.query(UserQualification).filter_by(user_id=user.id).all()}
    graph = service.active_graph(db) if get_configuration(db)["specification"] else None
    for identifier in selected:
        definition = graph.entities.get(identifier) if graph else None
        if not definition or definition["type"] != "qualification":
            if identifier in existing and existing[identifier].active:
                continue  # Preserve an obsolete award until an admin explicitly removes it.
            raise HTTPException(400, "Choose a qualification from the configured ontology")
        if not role_allows(graph, user.role, identifier):
            raise HTTPException(400, "This qualification is not compatible with the account role")
    for identifier in set(existing) | set(selected):
        row = existing.get(identifier)
        if row is None:
            row = UserQualification(user_id=user.id, qualification_id=identifier)
            db.add(row)
        enabled = identifier in selected
        if row.active != enabled or row.assigned_by is None:
            row.assigned_by = admin.id
            row.assigned_at = now()
        row.active = enabled
    db.flush()


def validate_user_skills(db: Session, selected: list[str], retained: list[str] | None = None) -> None:
    from .platform_graphs import skills
    if get_configuration(db)["specification"] is None:
        return  # Existing installations can provision accounts before importing.
    allowed = {option["id"] for option in skills(db)} | set(retained or [])
    if any(skill not in allowed for skill in selected):
        raise HTTPException(400, "Select qualifications required by configured processes")


@router.patch("/operator/availability")
def availability(body: Availability, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    with transaction(db):
        user.available = body.available
        db.flush()
        service.schedule(db)
        return public_user(user)


@router.get("/configuration")
def configuration(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return get_configuration(db)


@router.post("/configuration/validate")
def validate(body: SpecInput, _: User = Depends(require_admin)):
    errors = validate_specification(body.specification)
    return {"valid": not errors, "errors": errors}


@router.put("/configuration")
def apply(body: ApplySpec, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return apply_configuration(db, body.specification, body.expected_revision, actor=actor.id)


@router.get("/configuration/export")
def export(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    specification = get_configuration(db)["specification"]
    if not specification:
        raise HTTPException(404, "No manufacturing configuration has been applied")
    return specification


@router.get("/configuration/schema")
def schema(_: User = Depends(require_admin)):
    from .platform_configuration import CORE_TYPES, SEMANTICS
    return {"schema_version": "1.0", "entity_types": sorted(CORE_TYPES),
            "relation_types": [{"id": key, "from_types": sorted(value[0]), "to_types": sorted(value[1])} for key, value in SEMANTICS.items()],
            "required_fields": ["schema_version", "environment", "ontology", "entities", "relationships", "constraints"],
            "constraints": ["requires", "excludes", "match_property"], "verification_providers": ["human", "openai"]}


@router.get("/shop/catalog")
def shop_catalog(db: Session = Depends(get_db)):
    return service.catalog(db)


@router.post("/configuration/import-turtle")
def import_turtle(body: TurtleInput, _: User = Depends(require_admin)):
    from .platform_rdf import convert_turtle
    try:
        specification = convert_turtle(body.turtle)
        errors = validate_specification(specification)
        return {"specification": specification, "valid": not errors, "errors": errors}
    except ValueError as error:
        return {"specification": None, "valid": False, "errors": [str(error)]}


@router.post("/shop/validate")
def shop_validate(body: Selection, db: Session = Depends(get_db)):
    return service.validate_product(service.active_graph(db), body.product_id, body.selections)


@router.post("/shop/converse")
def converse(body: Conversation, db: Session = Depends(get_db)):
    graph = service.active_graph(db)
    product = graph.entities.get(body.product_id)
    if not product or product["type"] != "product":
        raise HTTPException(404, "Product not found")
    selections, proposals = dict(body.selections), []
    lower = body.message.lower()
    tokens = lambda text: set(re.findall(r"[\w-]+", text.lower()))
    phrases = [tokens(phrase) for phrase in re.split(r"\band\b|[,;\n]", lower)]
    for slot in graph.slots(body.product_id):
        matches = []
        common = set.intersection(*(tokens(variant["name"]) for variant in slot["variants"])) if slot["variants"] else set()
        slot_words = tokens(slot["label"]) | tokens(slot["id"])
        for variant in slot["variants"]:
            aliases = [variant["name"], *variant.get("properties", {}).get("aliases", [])]
            exact = any(isinstance(alias, str) and re.search(r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)", lower) for alias in aliases)
            distinctive = tokens(variant["name"]) - common
            contextual = distinctive and any(distinctive <= phrase and (slot_words & phrase or {"all", "every"} & phrase) for phrase in phrases)
            if exact or contextual:
                matches.append(variant)
        if len(matches) == 1:
            selections[slot["id"]] = matches[0]["id"]
            proposals.append(f"{slot['label']}: {matches[0]['name']}")
        elif len(matches) > 1:
            proposals.append(f"Please choose one {slot['label']}; your request matches several options")
    result = service.validate_product(graph, body.product_id, selections)
    message = "I matched " + "; ".join(proposals) + ". " if proposals else "I can match configured part names in your request. "
    message += "Review the configuration and confirm your order." if result["valid"] else " ".join(result["errors"])
    return {"message": message, "selections": result.get("selections", selections), "requires_confirmation": result["valid"]}


@router.post("/shop/orders")
def place_order(body: NewOrder, db: Session = Depends(get_db)):
    with transaction(db):
        order = service.create_order(db, body.product_id, body.selections, body.customer_name)
        return service.order_view(db, order)


@router.get("/orders")
def orders(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        return [service.order_view(db, order) for order in db.query(Order).order_by(Order.created_at.desc()).all()]


@router.get("/orders/{order_id}")
def order_detail(order_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        order = db.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        return service.order_view(db, order)


@router.get("/orders/{order_id}/graph")
def order_knowledge_graph(order_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .platform_graphs import order_graph
    with transaction(db):
        service.schedule(db)
        order = db.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        return order_graph(db, order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, body: CancellationInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .platform_cancellation import request
    with transaction(db):
        order = db.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        request(db, order, admin, body.reason)
        service.schedule(db)
        return service.order_view(db, order)


@router.get("/operator/tasks")
def operator_tasks(user: User = Depends(require_operator), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        return [service.task_view(db, task) for task in db.query(Task).filter(Task.assigned_operator_id == user.id, Task.status.notin_(["completed", "cancelled"])).order_by(Task.position).all()]


@router.post("/tasks/{task_id}/evidence")
async def upload(task_id: str, file: UploadFile = File(...), user: User = Depends(require_operator), db: Session = Depends(get_db)):
    content = await file.read(12 * 1024 * 1024 + 1)
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(413, "Image must be no larger than 12 MB")
    try:
        image = Image.open(BytesIO(content))
        image_type = image.format
        if image.width * image.height > 20_000_000 or image_type not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Unsupported image")
        image.verify()
        mime, suffix = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}[image_type]
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "Upload a JPEG, PNG or WebP image")
    with transaction(db):
        service.schedule(db)
        task = service.own_task(db, task_id, user)
        if task.status not in {"in_progress", "rejected"} or not service.task_view(db, task)["verification"]:
            raise HTTPException(409, "Evidence is not accepted at this stage")
        identifier = uid()
        path = get_settings().evidence_dir / f"{identifier}{suffix}"
        path.write_bytes(content)
        db.add(Evidence(id=identifier, task_id=task.id, file_path=str(path), content_type=mime, name=Path(file.filename or "Evidence").name[:255]))
        db.flush()
        return service.task_view(db, task)


@router.get("/evidence/{evidence_id}")
def evidence_file(evidence_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Evidence, evidence_id)
    if not item:
        raise HTTPException(404, "Evidence not found")
    task = db.get(Task, item.task_id)
    if user.role != "admin" and task.assigned_operator_id != user.id:
        raise HTTPException(403, "Evidence is outside your assigned work")
    if not Path(item.file_path).is_file():
        raise HTTPException(404, "Evidence asset is unavailable")
    return FileResponse(item.file_path, media_type=item.content_type)


@router.get("/shop/reference/{filename:path}")
def reference_file(filename: str, db: Session = Depends(get_db)):
    graph = service.active_graph(db)
    allowed = {name for entity in graph.entities.values() if entity["type"] == "verification" for name in entity.get("properties", {}).get("reference_images", [])}
    allowed.update(entity.get("properties", {}).get("image_url", "").removeprefix("/api/shop/reference/") for entity in graph.entities.values() if isinstance(entity.get("properties", {}).get("image_url", ""), str))
    root = get_settings().reference_image_dir.resolve()
    path = (root / filename).resolve()
    if filename not in allowed or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Reference image not found")
    return FileResponse(path)


@router.post("/tasks/{task_id}/complete")
def complete(task_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        task = service.own_task(db, task_id, user)
        service.complete_task(db, task)
        return service.task_view(db, task)


@router.post("/tasks/{task_id}/run")
def run(task_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        task = service.own_task(db, task_id, user)
        if task.kind != "machine" or task.status != "in_progress" or task.command_id:
            raise HTTPException(409, "This machine cycle cannot be started in its current state")
        task.command_id = uid()
        service.dispatch_task(db, task)
        return service.task_view(db, task)


@router.post("/tasks/{task_id}/scrap")
def scrap(task_id: str, body: Scrap, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    with transaction(db):
        task = service.own_task(db, task_id, user)
        protocol = service.task_view(db, task)["scrap"]
        if task.status not in {"in_progress", "rejected"} or not protocol:
            raise HTTPException(409, "Scrap reporting is not configured for this stage")
        if body.quantity > protocol.get("max_quantity", 0) or (body.quantity > 0 and body.reason not in protocol.get("reasons", [])):
            raise HTTPException(400, "Use the configured scrap quantity and reason")
        task.scrap_report = body.model_dump()
        return service.task_view(db, task)


@router.get("/reviews")
def reviews(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": review.id, "task_id": review.task_id, "task_name": db.get(Task, review.task_id).name, "order_id": db.get(Task, review.task_id).order_id,
             "reason": review.reason, "evidence": service.task_view(db, db.get(Task, review.task_id))["evidence"],
             "task": service.task_view(db, db.get(Task, review.task_id))}
            for review in db.query(Review).filter(Review.status == "pending").all()]


@router.post("/reviews/{review_id}")
def decide_review(review_id: str, body: Decision, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        review = db.get(Review, review_id)
        if not review:
            raise HTTPException(404, "Review not found")
        task = db.get(Task, review.task_id)
        if review.status != "pending" or task.status != "awaiting_review":
            raise HTTPException(409, "This submission has already been reviewed")
        review.status = "approved" if body.decision == "approve" else "rejected"
        task.verification_outcome = review.status
        task.verification_reason = body.reason or f"Specialist {review.status} this submission."
        task.status = "completed" if body.decision == "approve" else "rejected"
        if body.decision == "approve" and task.kind == "machine":
            task.machine_completed = True
        db.flush()
        service.schedule(db)
        return service.task_view(db, task)


@router.get("/machines")
def machine_list(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        service.schedule(db)
        return service.machines(db)


@router.patch("/machines/{machine_id}")
def machine_status(machine_id: str, body: MachinePatch, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    with transaction(db):
        if machine_id not in {machine["id"] for machine in service.machines(db)}:
            raise HTTPException(404, "Machine not found")
        state = db.get(MachineState, machine_id)
        if not state:
            state = MachineState(id=machine_id)
            db.add(state)
        state.status = body.status
        db.flush()
        service.schedule(db)
        return next(machine for machine in service.machines(db) if machine["id"] == machine_id)


@router.post("/gateway/test")
def gateway_test(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    configuration = service.active_graph(db).spec.get("gateway")
    if not configuration:
        raise HTTPException(400, "Configure a machine gateway first")
    try:
        return {"connected": True, "details": machine_gateway(configuration).health()}
    except Exception:
        return {"connected": False, "detail": "The configured machine gateway could not be reached"}


@router.get("/telemetry/status")
def telemetry_status(_: User = Depends(require_admin)):
    from .platform_telemetry import status
    return status()


@router.post("/telemetry/sync")
def telemetry_sync(_: User = Depends(require_admin)):
    from .platform_telemetry import status, sync_once
    sync_once()
    return status()


@router.post("/tasks/{task_id}/confirm-stopped")
def confirm_stopped(task_id: str, body: StopConfirmation, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from .platform_telemetry import observed
    with transaction(db):
        task = db.get(Task, task_id)
        if not task or task.kind != "machine" or task.status != "paused" or not observed(db, task):
            raise HTTPException(409, "Only a paused monitored operation can be released after a confirmed physical stop")
        if db.get(Order, task.order_id).status == "cancelling":
            from .platform_cancellation import confirm
            confirm(db, task, admin)
        else:
            service.release(task)
        service.schedule(db)
        return service.task_view(db, task)


@router.post("/machine/events")
def machine_event(body: EventInput, request: Request, db: Session = Depends(get_db)):
    expected = get_settings().machine_event_token
    actual = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(actual.encode(), expected.encode()):
        raise HTTPException(401, "Machine integration authentication required")
    with transaction(db):
        existing = db.get(MachineEvent, body.external_id)
        if existing:
            if (existing.task_id, existing.machine_id, existing.event, existing.dispatch_id) != (body.task_id, body.machine_id, body.event, body.dispatch_id):
                raise HTTPException(409, "This event identifier has already been used")
            return {"accepted": True, "duplicate": True}
        task = db.get(Task, body.task_id)
        if not task or task.kind != "machine":
            raise HTTPException(404, "Machine task not found")
        if task.machine_id != body.machine_id or task.command_id != body.dispatch_id or task.status not in {"in_progress", "awaiting_review", "rejected", "paused"}:
            raise HTTPException(409, "Event does not match the current machine assignment")
        db.add(MachineEvent(**body.model_dump()))
        if db.get(Order, task.order_id).status in {"cancelling", "cancelled"}:
            # Late callbacks cannot complete or restart cancelled workflow work.
            if body.event == "completed":
                task.machine_completed = True
            db.flush()
            service.schedule(db)
            return {"accepted": True, "duplicate": False, "cancellation_pending": True}
        if task.machine_completed and body.event != "completed":
            return {"accepted": True, "duplicate": False, "ignored": True}
        if body.event == "failed":
            state = db.get(MachineState, body.machine_id)
            if not state:
                state = MachineState(id=body.machine_id)
                db.add(state)
            state.status = "down"
            for review in db.query(Review).filter(Review.task_id == task.id, Review.status == "pending").all():
                review.status = "cancelled"
            task.status = "paused"
            service.release(task)
        elif body.event == "completed":
            task.machine_completed = True
            view = service.task_view(db, task)
            if not view["verification"] and not (view["scrap"] and view["scrap"].get("required")):
                task.status = "completed"
        db.flush()
        service.schedule(db)
        return {"accepted": True, "duplicate": False}
