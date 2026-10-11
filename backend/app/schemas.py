from datetime import datetime
from ipaddress import ip_address
import re
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


Color = Literal["red", "green", "blue", "white"]


class ProductConfiguration(BaseModel):
    color: Color


class PartialProductConfiguration(BaseModel):
    color: Color | None = None


class ConfigurationValidation(BaseModel):
    valid: bool
    configuration: ProductConfiguration
    bom: list[dict]


class ConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    current_configuration: PartialProductConfiguration | None = Field(
        default=None, validation_alias=AliasChoices("current_configuration", "configuration")
    )
    history: list[dict[str, str]] = []
    confirmed: bool = False
    customer_name: str = Field(default="Demo Customer", min_length=1, max_length=100)


class ConfigurationProposal(BaseModel):
    color: Color | None = None
    reply: str


class ConversationResponse(BaseModel):
    message: str
    proposed_configuration: ProductConfiguration | None = None
    configuration: ProductConfiguration | None = None
    requires_confirmation: bool
    order_id: int | None = None


class OrderCreate(BaseModel):
    customer_name: str = Field(default="Demo Customer", min_length=1, max_length=100)
    configuration: ProductConfiguration
    confirmed: bool = True


class OperatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    skills: list[str]
    available: bool


class MachineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    capabilities: list[str]
    status: str


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_name: str
    content_type: str
    created_at: datetime


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    position: int
    name: str
    kind: str
    required_skill: str
    machine_capability: str | None
    requires_verification: bool
    status: str
    assigned_operator_id: int | None
    machine_id: int | None
    instructions: str
    started_at: datetime | None
    completed_at: datetime | None
    evidence: list[EvidenceRead] = []
    assigned_operator: OperatorRead | None = None
    machine: MachineRead | None = None


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_name: str
    configuration: dict
    status: str
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskRead] = []


class HandoffRequest(BaseModel):
    to_operator_id: int = Field(validation_alias=AliasChoices("to_operator_id", "operator_id"))


class TaskAcceptRequest(BaseModel):
    operator_id: int | None = None


class AvailabilityUpdate(BaseModel):
    available: bool


class MachineStatusUpdate(BaseModel):
    status: Literal["available", "down", "maintenance"]


class ManualReview(BaseModel):
    decision: Literal["approve", "reject", "approved", "rejected"] = Field(
        validation_alias=AliasChoices("decision", "outcome")
    )
    reason: str = Field(min_length=1)


class MachineEvent(BaseModel):
    event: Literal["started", "completed", "failed"]
    external_id: str | None = None


class VerificationDecision(BaseModel):
    outcome: Literal["approved", "rejected", "manual_review"]
    confidence: int = Field(ge=0, le=100)
    reason: str


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    entity_type: str
    entity_id: int
    payload: dict
    created_at: datetime


class VerificationRead(BaseModel):
    id: int
    task_id: int
    order_id: int
    provider: str
    outcome: str
    confidence: int
    reason: str
    created_at: datetime
    evidence_url: str | None = None


class MachineGatewayUpdate(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["http"] = "http"
    enabled: bool = True
    use_mock: bool = True

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        value = value.strip()
        try:
            ip_address(value)
            return value
        except ValueError:
            pass
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value):
            raise ValueError("host must be an IP address or hostname without a scheme or path")
        if ".." in value:
            raise ValueError("invalid host")
        return value


class MachineGatewayRead(MachineGatewayUpdate):
    configured: bool
    reachable: bool | None = None
    error: str | None = None
