"""Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from incident_api.models import IncidentSeverity, IncidentStatus


class IncidentCreate(BaseModel):
    title: str
    severity: IncidentSeverity = IncidentSeverity.medium
    namespace: str | None = None
    workload: str | None = None
    alert_fingerprints: list[str] = Field(default_factory=list)
    labels: dict = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    status: IncidentStatus | None = None
    severity: IncidentSeverity | None = None
    title: str | None = None


class IncidentOut(BaseModel):
    id: UUID
    external_id: str
    title: str
    status: IncidentStatus
    severity: IncidentSeverity
    namespace: str | None
    workload: str | None
    alert_fingerprints: list
    labels: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertmanagerWebhook(BaseModel):
    version: str | None = None
    status: str | None = None
    receiver: str | None = None
    groupLabels: dict = Field(default_factory=dict)
    commonLabels: dict = Field(default_factory=dict)
    commonAnnotations: dict = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[dict] = Field(default_factory=list)
