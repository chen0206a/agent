from fastapi import APIRouter, Request, Response

from app.api.dependencies import Current, check_origin, local_request
from app.schemas.portal import AccountRead, LoginInput

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AccountRead)
def login(data: LoginInput, request: Request, response: Response):
    local_request(request)
    check_origin(request)
    token, csrf, account = request.app.state.auth.login(
        data.username, data.password.get_secret_value(), request.client.host
    )
    response.set_cookie(
        "asc_session",
        token,
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.cookie_secure,
        max_age=43200,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return AccountRead(username=account.username, role=account.role, user_id=account.user_id, csrf_token=csrf)


@router.get("/me", response_model=AccountRead)
def me(request: Request, response: Response, identity: Current):
    account, csrf = request.app.state.auth.authenticate(request.cookies.get("asc_session"))
    response.headers["Cache-Control"] = "no-store"
    return AccountRead(username=account.username, role=account.role, user_id=account.user_id, csrf_token=csrf)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, identity: Current):
    request.app.state.auth.logout(request.cookies.get("asc_session"))
    response.delete_cookie("asc_session", path="/")
