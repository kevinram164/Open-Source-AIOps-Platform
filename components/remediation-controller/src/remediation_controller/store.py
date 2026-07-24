"""Repository helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from remediation_controller.models import AuditLog, Remediation, RemediationStatusDB
from remediation_controller.schemas import RemediationOut, RemediationStatus


def _to_out(row: Remediation) -> RemediationOut:
    return RemediationOut(
        id=row.id,
        incident_id=row.incident_id,
        action=row.action,
        namespace=row.namespace,
        target=row.target,
        parameters=row.parameters or {},
        status=RemediationStatus(row.status.value),
        reason=row.reason,
        requested_by=row.requested_by,
        approved_by=row.approved_by,
        result=row.result,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_out(row: Remediation) -> RemediationOut:
    return _to_out(row)


async def audit(
    session: AsyncSession,
    *,
    actor: str,
    action_type: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor=actor,
            action_type=action_type,
            resource_id=resource_id,
            details=details or {},
        )
    )


async def create_remediation(session: AsyncSession, row: Remediation) -> RemediationOut:
    session.add(row)
    await audit(
        session,
        actor=row.requested_by,
        action_type="remediation.create",
        resource_id=str(row.id),
        details={"action": row.action, "namespace": row.namespace, "target": row.target},
    )
    await session.commit()
    await session.refresh(row)
    return _to_out(row)


async def list_remediations(session: AsyncSession) -> list[RemediationOut]:
    result = await session.execute(select(Remediation).order_by(Remediation.created_at.desc()))
    return [_to_out(r) for r in result.scalars().all()]


async def get_remediation(session: AsyncSession, remediation_id: str) -> Remediation | None:
    try:
        uid = uuid.UUID(remediation_id)
    except ValueError:
        return None
    return await session.get(Remediation, uid)


async def save(session: AsyncSession, row: Remediation, *, actor: str, action_type: str) -> RemediationOut:
    row.updated_at = datetime.now(UTC)
    await audit(
        session,
        actor=actor,
        action_type=action_type,
        resource_id=str(row.id),
        details={"status": row.status.value, "action": row.action},
    )
    await session.commit()
    await session.refresh(row)
    return _to_out(row)


def status_enum(s: RemediationStatus) -> RemediationStatusDB:
    return RemediationStatusDB(s.value)
