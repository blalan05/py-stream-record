from __future__ import annotations

import logging
import secrets

from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.config import get_config

log = logging.getLogger(__name__)

SESSION_KEY = "theater_auth"


def install_session_middleware(app) -> None:
    cfg = get_config()
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg["app"].get("secret_key") or secrets.token_hex(32),
        session_cookie="theater_session",
        max_age=60 * 60 * 12,
        same_site="lax",
        https_only=False,
    )


def verify_pin(pin: str) -> bool:
    return pin == get_config()["app"].get("pin", "")


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def login(request: Request, pin: str) -> bool:
    if verify_pin(pin):
        request.session[SESSION_KEY] = True
        return True
    return False


def logout(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


def require_auth(request: Request) -> RedirectResponse | None:
    if is_authenticated(request):
        return None
    return RedirectResponse("/login", status_code=303)


def auth_dependency(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return None
