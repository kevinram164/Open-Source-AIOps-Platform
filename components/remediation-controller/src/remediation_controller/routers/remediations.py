"""Remediation API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from remediation_controller import actions
from remediation_controller.policy import load_policy
from remediation_controller.schemas import (
    RemediationCreate,
    RemediationOut,
    RemediationStatus,
)

router = APIRouter(prefix="/api/v1")

_STORE: dict[str, RemediationOut] = {}


def _now() -> datetime:
    return datetime.now(UTC)


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
async def create_remediation(body: RemediationCreate) -> RemediationOut:
    policy = load_policy()
    if not policy.allows_action(body.action):
        raise HTTPException(status_code=400, detail=f"action not allowed: {body.action}")
    if not policy.allows_namespace(body.namespace):
        raise HTTPException(
            status_code=403,
            detail=f"namespace denied by policy Mode {policy.policy_mode}: {body.namespace}",
        )
    if body.action == "scale-deployment":
        replicas = int(body.parameters.get("replicas", 1))
        if replicas < 0 or replicas > policy.max_scale_replicas:
            raise HTTPException(status_code=400, detail="replicas out of policy range")

    item = RemediationOut(
        id=uuid4(),
        incident_id=body.incident_id,
        action=body.action,
        namespace=body.namespace,
        target=body.target,
        parameters=body.parameters,
        status=RemediationStatus.pending,
        reason=body.reason,
        requested_by=body.requested_by,
        approved_by=None,
        result=None,
        error=None,
        created_at=_now(),
        updated_at=_now(),
    )
    _STORE[str(item.id)] = item
    return item


@router.get("/remediations", response_model=list[RemediationOut])
async def list_remediations() -> list[RemediationOut]:
    return sorted(_STORE.values(), key=lambda x: x.created_at, reverse=True)


@router.get("/remediations/{remediation_id}", response_model=RemediationOut)
async def get_remediation(remediation_id: str) -> RemediationOut:
    item = _STORE.get(remediation_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    return item


@router.post("/remediations/{remediation_id}/approve", response_model=RemediationOut)
async def approve(remediation_id: str, approved_by: str = "oncall") -> RemediationOut:
    item = _STORE.get(remediation_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    if item.status not in {RemediationStatus.pending}:
        raise HTTPException(status_code=409, detail=f"cannot approve from status={item.status}")
    item.status = RemediationStatus.approved
    item.approved_by = approved_by
    item.updated_at = _now()
    return item


@router.post("/remediations/{remediation_id}/reject", response_model=RemediationOut)
async def reject(remediation_id: str, approved_by: str = "oncall") -> RemediationOut:
    item = _STORE.get(remediation_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    item.status = RemediationStatus.rejected
    item.approved_by = approved_by
    item.updated_at = _now()
    return item


@router.post("/remediations/{remediation_id}/execute", response_model=RemediationOut)
async def execute(remediation_id: str) -> RemediationOut:
    policy = load_policy()
    item = _STORE.get(remediation_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    if policy.require_approval and item.status != RemediationStatus.approved:
        raise HTTPException(status_code=409, detail="approval required before execute")
    if not policy.allows_namespace(item.namespace):
        raise HTTPException(status_code=403, detail="namespace denied by policy")

    item.status = RemediationStatus.executing
    item.updated_at = _now()
    try:
        if item.action == "restart-deployment":
            result = actions.restart_deployment(item.namespace, item.target)
        elif item.action == "scale-deployment":
            replicas = int(item.parameters.get("replicas", 1))
            result = actions.scale_deployment(item.namespace, item.target, replicas)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported action {item.action}")
        item.result = result
        item.status = RemediationStatus.completed
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        item.error = str(exc)
        item.status = RemediationStatus.failed
    item.updated_at = _now()
    return item
