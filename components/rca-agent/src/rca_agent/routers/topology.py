"""Topology API — Phase 7."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from rca_agent.topology.graph import get_topology_async, related_workloads_async

router = APIRouter(prefix="/api/v1")


class TopologyQuery(BaseModel):
    namespace: str | None = None
    workload: str | None = None
    hops: int = Field(default=2, ge=1, le=3)


class RelatedQuery(BaseModel):
    namespace_a: str | None = None
    workload_a: str | None = None
    namespace_b: str | None = None
    workload_b: str | None = None
    hops: int = Field(default=2, ge=1, le=3)


@router.get("/topology")
async def topology_get(
    namespace: str | None = None,
    workload: str | None = None,
    hops: int = Query(default=2, ge=1, le=3),
) -> dict[str, Any]:
    return await get_topology_async(namespace, workload, hops=hops)


@router.post("/topology")
async def topology_post(req: TopologyQuery) -> dict[str, Any]:
    return await get_topology_async(req.namespace, req.workload, hops=req.hops)


@router.post("/topology/related")
async def topology_related(req: RelatedQuery) -> dict[str, bool]:
    return {
        "related": await related_workloads_async(
            req.namespace_a,
            req.workload_a,
            req.namespace_b,
            req.workload_b,
            hops=req.hops,
        )
    }
