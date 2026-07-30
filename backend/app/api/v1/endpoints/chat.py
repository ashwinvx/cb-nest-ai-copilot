from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import error_response, success_response
from app.db.session import get_db
from app.models.employee import Employee
from app.schemas.chat import (
    ChatActionConfirmRequest,
    ChatActionsRequest,
    ChatMessageCreate,
    ChatPolicyRequest,
    ChatSessionCreate,
)
from app.services.ai.action_agent import execute_pending_action, run_action_agent
from app.services.ai.policy_rag import run_policy_rag
from app.services.auth import get_current_user, oauth2_scheme

router = APIRouter()


@router.post("/policy")
async def chat_policy(
    payload: ChatPolicyRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Policy RAG Assistant: answers HR policy questions with citations.
    Retrieval-only — this agent has no tools and no write paths."""
    result = await run_policy_rag(
        db,
        user_id=current_user.id,
        role=current_user.role,
        message=payload.message,
    )
    return success_response(result)


@router.post("/actions")
async def chat_actions(
    payload: ChatActionsRequest,
    current_user: Employee = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """HR Task Automation Agent: natural language leave actions, executed
    via the existing REST endpoints with the caller's own JWT."""
    result = await run_action_agent(
        db,
        user_id=current_user.id,
        role=current_user.role,
        token=token,
        message=payload.message,
        history=[turn.model_dump() for turn in payload.history],
    )
    return success_response(result)


@router.post("/actions/confirm")
async def chat_actions_confirm(
    payload: ChatActionConfirmRequest,
    current_user: Employee = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Execute (or decline) a pending action proposed by the agent. The
    signed action token is verified against the calling user; execution
    still goes through the same tool layer and REST endpoints."""
    result = await execute_pending_action(
        db,
        user_id=current_user.id,
        role=current_user.role,
        token=token,
        action_token=payload.action_token,
        approve=payload.approve,
    )
    return success_response(result)


@router.post("/sessions")
async def create_chat_session(
    payload: ChatSessionCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat session creation is a Phase-3 stub and not implemented yet"),
    )


@router.post("/sessions/{session_id}/messages")
async def post_chat_message(
    session_id: str,
    payload: ChatMessageCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = session_id
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat messaging is a Phase-3 stub and not implemented yet"),
    )
