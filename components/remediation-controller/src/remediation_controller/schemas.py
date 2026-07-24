"""API schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RemediationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"


class RemediationCreate(BaseModel):
    incident_id: str | None = None
    action: str
    namespace: str
    target: str  # deployment name
    parameters: dict = Field(default_factory=dict)
    reason: str | None = None
    requested_by: str = "api"


class RemediationOut(BaseModel):
    id: UUID
    incident_id: str | None
    action: str
    namespace: str
    target: str
    parameters: dict
    status: RemediationStatus
    reason: str | None = None
    requested_by: str
    approved_by: str | None = None
    result: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
