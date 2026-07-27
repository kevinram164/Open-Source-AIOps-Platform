"""RCA output and request schemas — investigator fields."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    incident_id: str
    external_id: str | None = None
    title: str = ""
    namespace: str | None = None
    workload: str | None = None
    severity: str | None = None
    labels: dict = Field(default_factory=dict)
    alert_fingerprints: list[str] = Field(default_factory=list)
    raw_alerts: list[dict] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    action: str = Field(
        description="restart-deployment | gitops-scale | scale-deployment | ansible-runbook"
    )
    namespace: str | None = None
    target: str | None = None
    parameters: dict = Field(default_factory=dict)
    reason: str | None = None


class TopologyNeighbor(BaseModel):
    namespace: str | None = None
    name: str | None = None
    id: str | None = None
    hops: int | None = None
    kind: str | None = None


class ImpactScope(BaseModel):
    namespaces: list[str] = Field(default_factory=list)
    workloads: list[str] = Field(default_factory=list)
    pods: list[str] = Field(default_factory=list)
    nodes: list[str] = Field(default_factory=list)
    blast_radius: str | None = Field(
        default=None, description="service | namespace | cluster | unknown"
    )
    upstream: list[TopologyNeighbor] = Field(default_factory=list)
    downstream: list[TopologyNeighbor] = Field(default_factory=list)
    topology_source: str | None = None


class RcaOutput(BaseModel):
    incident_id: str
    status: str = "analyzed"
    affected_service: str | None = None
    affected_namespace: str | None = None
    # Symptom vs root cause (investigator)
    symptom: str | None = None
    symptom_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    probable_root_cause: str
    root_cause_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, description="Overall confidence (compat)")
    error_subtype: str | None = Field(
        default=None,
        description="ImagePullBackOff|CrashLoopBackOff|OOMKilled|NodePressure|Unknown",
    )
    impact_scope: ImpactScope | None = None
    supporting_evidence: list[str] = Field(default_factory=list)
    business_impact: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    automation_available: bool = False
    automation_requires_approval: bool = True
    recommended_runbook: str | None = None
    model: str | None = None
