"""POST /api/v1/chat — AIOps conversational demo API (Phase 6)."""

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

    Pass ``session_id`` to keep multi-turn memory. Does **not** execute remediations.
    """
    result = await handle_chat(
        session,
        question=body.question,
        namespace=body.namespace,
        incident_ref=body.incident_id,
        auto_analyze=body.auto_analyze,
        session_id=body.session_id,
    )
    return ChatResponse(**result)
