from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.agent.contracts import AgentStatus, AgentTrace, ChatRequest, ChatResult, Citation
from app.agent.runtime import AgentService
from app.api.dependencies import Admin, Current
from app.core.errors import DomainError
from app.schemas.api import ErrorRead
from app.services.portal import public_trace

router = APIRouter(
    prefix="/agent",
    tags=["stage3-agent"],
    responses={code: {"model": ErrorRead} for code in (401, 403, 404, 409, 422, 500, 503)},
)


def service(request: Request) -> AgentService:
    return request.app.state.agent


Agent = Annotated[AgentService, Depends(service)]


@router.get("/status", response_model=AgentStatus)
def status(identity: Current, agent: Agent):
    cfg = agent.settings
    return AgentStatus(
        configured=bool(cfg.llm_model and cfg.llm_api_key.get_secret_value()),
        model=cfg.llm_model,
        max_steps=cfg.agent_max_steps,
        max_tools=cfg.agent_max_tools,
        timeout_seconds=cfg.agent_timeout_seconds,
    )


@router.post("/runs", response_model=ChatResult)
def chat(data: ChatRequest, identity: Current, agent: Agent, response: Response):
    if identity.user_id is None:
        raise DomainError("CUSTOMER_REQUIRED", "请使用客户账号发起售后会话", 401)
    result = agent.chat(identity.user_id, data)
    if result.status == "RUNNING":
        response.status_code = 202
    return result


@router.get("/runs/{run_id}", response_model=ChatResult)
def get_run(run_id: int, identity: Current, agent: Agent):
    return agent.get_run(run_id, None if identity.role == "admin" else identity.user_id)


@router.get("/runs/{run_id}/trace", response_model=AgentTrace)
def trace(run_id: int, identity: Admin, agent: Agent):
    return public_trace(agent.trace(run_id).model_dump(mode="json"))


@router.post("/runs/{run_id}/recover", response_model=ChatResult)
def recover(run_id: int, identity: Admin, agent: Agent):
    return agent.recover(run_id)


@router.get("/policies/{document_id}", response_model=Citation)
def policy(document_id: str, identity: Current, agent: Agent):
    return agent.knowledge.get(document_id)
