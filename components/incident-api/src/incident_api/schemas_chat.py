"""Chat API schemas — investigator response."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(
        min_length=3,
        examples=["Why is Payment Service down?", "Có pod nào CrashLoopBackOff không?"],
    )
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
    intent: str | None = Field(
        default=None,
        description="investigate | ops_query | command_restart | general",
    )
    answer: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    symptom: str | None = None
    symptom_confidence: float | None = None
    probable_root_cause: str | None = None
    root_cause_confidence: float | None = None
    confidence: float | None = None
    error_subtype: str | None = None
    impact_scope: dict | None = None
    incident: dict | None = None
    nba: dict | None = None
    remediations: list[dict] = Field(default_factory=list)
    ops_snapshot: dict | None = None
    model: str | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            text = v.strip()
            if not text:
                return []
            if "\n" in text:
                return [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
            return [text]
        if isinstance(v, list):
            # Repair accidental list("NodeUsage...") → chars
            if v and all(isinstance(x, str) and len(x) == 1 for x in v):
                joined = "".join(v).strip()
                return [joined] if joined else []
            return [
                str(x).strip()
                for x in v
                if str(x).strip() and not (isinstance(x, str) and len(x) == 1)
            ]
        return [str(v)]
