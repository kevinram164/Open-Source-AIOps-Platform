"""RCA output and request schemas."""

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
    """Typed Next Best Action for remediation-controller (still requires human approve)."""

    action: str = Field(
        description="restart-deployment | gitops-scale | scale-deployment | ansible-runbook"
    )
    namespace: str | None = None
    target: str | None = None
    parameters: dict = Field(default_factory=dict)
    reason: str | None = None


class RcaOutput(BaseModel):
    incident_id: str
    status: str = "analyzed"
    affected_service: str | None = None
    affected_namespace: str | None = None
    probable_root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    business_impact: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    automation_available: bool = False
    automation_requires_approval: bool = True
    recommended_runbook: str | None = None
    model: str | None = None
