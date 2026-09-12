import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.agent.runtime import AgentService
from app.api.agent_routes import router as agent_router
from app.api.auth_routes import router as auth_router
from app.api.portal_routes import router as portal_router
from app.api.routes import router
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.types import utcnow
from app.db.session import make_engine, make_sessions
from app.services.auth import AuthService
from app.services.business import BusinessService
from app.services.portal import PortalService
from app.services.workflow import WorkflowService

logger = logging.getLogger("aftersale")


def create_app(settings: Settings | None = None, clock: Callable[[], datetime] = utcnow) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = make_engine(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(_):
        yield
        engine.dispose()

    app = FastAPI(
        title="AfterSale Copilot — Local Simulation",
        version="0.3.0",
        lifespan=lifespan,
        description="Stages 1–3: single Agent with deterministic after-sales controls. No real payments. "
        "Business APIs require authenticated sessions and CSRF. Amounts are CNY strings.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = make_sessions(engine)
    app.state.auth = AuthService(app.state.sessions)
    app.state.portal = PortalService(app.state.sessions)
    app.state.business = BusinessService(app.state.sessions)
    app.state.workflow = WorkflowService(app.state.sessions, settings, clock)
    app.state.agent = AgentService(app.state.sessions, settings, app.state.business, app.state.workflow)

    def error_response(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", ""),
                }
            },
        )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled failure request_id=%s", request.state.request_id)
            response = error_response(
                request, 500, "INTERNAL_ERROR", "服务内部错误，请根据请求编号查看本地日志"
            )
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.headers.get("content-type") == "application/json":
            # Explicit charset also supports Windows PowerShell 5.1 JSON clients.
            response.headers["Content-Type"] = "application/json; charset=utf-8"
        logger.info(
            "request_id=%s method=%s path=%s status=%s latency_ms=%.1f",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return error_response(request, error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Do not echo submitted input or framework exception contexts.
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        return error_response(request, 422, "VALIDATION_ERROR", "字段校验失败：" + ", ".join(fields))

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        logger.warning("Database constraint conflict request_id=%s", request.state.request_id)
        return error_response(request, 409, "DATA_CONFLICT", "数据违反唯一性、关系或业务约束")

    @app.exception_handler(OperationalError)
    async def operational_error(request, error):
        logger.warning("Database unavailable request_id=%s", request.state.request_id)
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂不可用，请稍后重试")

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(request, error.status_code, "HTTP_ERROR", str(error.detail))

    app.include_router(router)
    app.include_router(agent_router)
    app.include_router(auth_router)
    app.include_router(portal_router)
    return app


app = create_app()
