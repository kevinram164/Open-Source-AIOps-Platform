"""ORM models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from incident_api.db import Base


class IncidentStatus(str, enum.Enum):
    open = "open"
    analyzing = "analyzing"
    analyzed = "analyzed"
    resolved = "resolved"


class IncidentSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"), default=IncidentStatus.open
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity"), default=IncidentSeverity.medium
    )
    namespace: Mapped[str | None] = mapped_column(String(253), nullable=True)
    workload: Mapped[str | None] = mapped_column(String(253), nullable=True)
    alert_fingerprints: Mapped[list] = mapped_column(JSONB, default=list)
    labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_alerts: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RcaResult(Base):
    __tablename__ = "rca_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
