"""Remediation API (Postgres-backed)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from remediation_controller import actions, store
from remediation_controller.db import get_session
from remediation_controller.models import Remediation, RemediationStatusDB
from remediation_controller.policy import load_policy
from remediation_controller.schemas import (
    RemediationCreate,
    RemediationOut,
)

router = APIRouter(prefix="/api/v1")


@router.get("/policy")
async def get_policy() -> dict:
    p = load_policy()
    return {
        "policyMode": p.policy_mode,
        "requireApproval": p.require_approval,
        "denyNamespacePrefixes": p.deny_namespace_prefixes,
        "denyNamespaces": p.deny_namespaces,
        "allowedActions": p.allowed_actions,
        "maxScaleReplicas": p.max_scale_replicas,
    }


@router.post("/remediations", response_model=RemediationOut)
async def create_remediation(
    body: RemediationCreate,
    session: AsyncSession = Depends(get_session),
) -> RemediationOut:
    policy = load_policy()
    if not policy.allows_action(body.action):
        raise HTTPException(status_code=400, detail=f"action not allowed: {body.action}")
    if body.action != "ansible-runbook" and not policy.allows_namespace(body.namespace):
        raise HTTPException(
            status_code=403,
            detail=f"namespace denied by policy Mode {policy.policy_mode}: {body.namespace}",
        )
    if body.action in {"scale-deployment", "gitops-scale"}:
        replicas = int(body.parameters.get("replicas", 1))
        if replicas < 0 or replicas > policy.max_scale_replicas:
            raise HTTPException(status_code=400, detail="replicas out of policy range")
    if body.action == "ansible-runbook":
        playbook = body.parameters.get("playbook", "node-diagnostics")
        if playbook not in {"node-diagnostics"}:
            raise HTTPException(status_code=400, detail=f"unsupported playbook: {playbook}")

    row = Remediation(
        id=uuid4(),
        incident_id=body.incident_id,
        action=body.action,
        namespace=body.namespace,
        target=body.target,
        parameters=body.parameters,
        status=RemediationStatusDB.pending,
        reason=body.reason,
        requested_by=body.requested_by,
    )
    return await store.create_remediation(session, row)


@router.get("/remediations", response_model=list[RemediationOut])
async def list_remediations(session: AsyncSession = Depends(get_session)) -> list[RemediationOut]:
    return await store.list_remediations(session)


@router.get("/remediations/{remediation_id}", response_model=RemediationOut)
async def get_remediation(
    remediation_id: str,
    session: AsyncSession = Depends(get_session),
) -> RemediationOut:
    row = await store.get_remediation(session, remediation_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return store.to_out(row)


@router.post("/remediations/{remediation_id}/approve", response_model=RemediationOut)
async def approve(
    remediation_id: str,
    approved_by: str = "oncall",
    session: AsyncSession = Depends(get_session),
) -> RemediationOut:
    row = await store.get_remediation(session, remediation_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    if row.status != RemediationStatusDB.pending:
        raise HTTPException(status_code=409, detail=f"cannot approve from status={row.status.value}")
    row.status = RemediationStatusDB.approved
    row.approved_by = approved_by
    return await store.save(session, row, actor=approved_by, action_type="remediation.approve")


@router.post("/remediations/{remediation_id}/reject", response_model=RemediationOut)
async def reject(
    remediation_id: str,
    approved_by: str = "oncall",
    session: AsyncSession = Depends(get_session),
) -> RemediationOut:
    row = await store.get_remediation(session, remediation_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    row.status = RemediationStatusDB.rejected
    row.approved_by = approved_by
    return await store.save(session, row, actor=approved_by, action_type="remediation.reject")


@router.post("/remediations/{remediation_id}/execute", response_model=RemediationOut)
async def execute(
    remediation_id: str,
    session: AsyncSession = Depends(get_session),
) -> RemediationOut:
    policy = load_policy()
    row = await store.get_remediation(session, remediation_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    if policy.require_approval and row.status != RemediationStatusDB.approved:
        raise HTTPException(status_code=409, detail="approval required before execute")
    if row.action != "ansible-runbook" and not policy.allows_namespace(row.namespace):
        raise HTTPException(status_code=403, detail="namespace denied by policy")

    row.status = RemediationStatusDB.executing
    await store.save(session, row, actor="system", action_type="remediation.executing")

    try:
        if row.action == "restart-deployment":
            result = actions.restart_deployment(row.namespace, row.target)
        elif row.action == "scale-deployment":
            replicas = int((row.parameters or {}).get("replicas", 1))
            result = actions.scale_deployment(row.namespace, row.target, replicas)
        elif row.action == "gitops-scale":
            replicas = int((row.parameters or {}).get("replicas", 1))
            result = actions.gitops_scale(row.namespace, row.target, replicas, row.reason)
        elif row.action == "ansible-runbook":
            playbook = (row.parameters or {}).get("playbook", "node-diagnostics")
            result = actions.ansible_runbook(
                playbook=playbook,
                namespace=row.namespace,
                target=row.target,
                parameters=row.parameters or {},
                remediation_id=str(row.id),
            )
        else:
            raise HTTPException(status_code=400, detail=f"unsupported action {row.action}")
        row.result = result
        row.status = RemediationStatusDB.completed
        row.error = None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        row.error = str(exc)
        row.status = RemediationStatusDB.failed

    return await store.save(
        session,
        row,
        actor=row.approved_by or "system",
        action_type="remediation.execute",
    )
