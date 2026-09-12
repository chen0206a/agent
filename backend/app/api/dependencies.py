import hmac
import ipaddress
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import DomainError
from app.services.business import BusinessService
from app.services.workflow import WorkflowService


@dataclass(frozen=True)
class Principal:
    role: str
    user_id: int | None
    actor: str

    def require_owner(self, user_id: int) -> None:
        if self.role != "admin" and self.user_id != user_id:
            raise DomainError("FORBIDDEN", "不能访问其他用户的数据", 403)


def local_request(request):
    try:
        local = request.client and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise DomainError("LOCAL_ONLY", "当前版本仅供本机访问", 403)


def check_origin(request):
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.frontend_origins.split(","):
        raise DomainError("ORIGIN_DENIED", "请求来源不受信任", 403)


def principal(request: Request) -> Principal:
    local_request(request)
    account, csrf = request.app.state.auth.authenticate(request.cookies.get("asc_session"))
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not hmac.compare_digest(csrf.encode(), request.headers.get("X-CSRF-Token", "").encode()):
            raise DomainError("CSRF_FAILED", "请求校验失效，请刷新页面后重试", 403)
    return Principal(account.role, account.user_id, f"{account.role}:{account.username}")


Current = Annotated[Principal, Depends(principal)]


def admin(identity: Current) -> Principal:
    if identity.role != "admin":
        raise DomainError("ADMIN_REQUIRED", "此操作需要管理员权限", 403)
    return identity


Admin = Annotated[Principal, Depends(admin)]


def business(request: Request) -> BusinessService:
    return request.app.state.business


def workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


Business = Annotated[BusinessService, Depends(business)]
Workflow = Annotated[WorkflowService, Depends(workflow)]
