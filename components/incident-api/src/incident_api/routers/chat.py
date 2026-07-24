"""POST /api/v1/chat — AIOps conversational demo API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_api.chat import handle_chat
from incident_api.db import get_session
from incident_api.schemas_chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Ask a natural-language question; returns evidence-backed answer + NBA remediations.

    Does **not** execute remediations — approve/execute via remediation-controller.
    """
    result = await handle_chat(
        session,
        question=body.question,
        namespace=body.namespace,
        incident_ref=body.incident_id,
        auto_analyze=body.auto_analyze,
    )
    return ChatResponse(**result)
