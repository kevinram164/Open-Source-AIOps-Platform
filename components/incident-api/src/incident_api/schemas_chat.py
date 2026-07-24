"""Chat API schemas."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, examples=["Why is Payment Service down?"])
    namespace: str | None = Field(
        default=None, description="Optional namespace hint (e.g. npd-banking)"
    )
    incident_id: str | None = Field(
        default=None, description="UUID or external_id (INC-XXXXXXXX)"
    )
    auto_analyze: bool = Field(
        default=True,
        description="If true and no RCA yet, run RCA + NBA before answering",
    )


class ChatResponse(BaseModel):
    answer: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    probable_root_cause: str | None = None
    confidence: float | None = None
    incident: dict | None = None
    nba: dict | None = None
    remediations: list[dict] = Field(default_factory=list)
    model: str | None = None
