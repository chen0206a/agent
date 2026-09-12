from fastapi import APIRouter, Request

from app.api.dependencies import Admin, Current
from app.api.routes import Limit, Offset
from app.core.enums import ExecutionStatus, RiskLevel
from app.schemas.api import ActionRead
from app.schemas.portal import DashboardRead, RunRead

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/actions", response_model=list[ActionRead])
def actions(
    request: Request,
    identity: Current,
    risk: RiskLevel | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    status: ExecutionStatus | None = None,
):
    return request.app.state.portal.actions(
        None if identity.role == "admin" else identity.user_id, risk, limit, offset, status
    )


@router.get("/runs", response_model=list[RunRead])
def runs(
    request: Request, identity: Current, order_id: int | None = None, limit: Limit = 50, offset: Offset = 0
):
    return request.app.state.portal.runs(
        None if identity.role == "admin" else identity.user_id, order_id, limit, offset
    )


@router.get("/dashboard", response_model=DashboardRead)
def dashboard(request: Request, identity: Admin):
    return request.app.state.portal.dashboard()
