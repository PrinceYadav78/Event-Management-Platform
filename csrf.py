"""CSRF protection via the double-submit-cookie pattern.

A random token is stored in a (JS-readable) cookie by the security middleware,
and the browser echoes it back on every unsafe request — either as a hidden
form field `csrf_token` or an `X-CSRF-Token` header (injected by JS in base.html
/ login.html). This dependency, attached to every router, compares the two.
"""
import secrets

from fastapi import Request, Form, HTTPException

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def csrf_protect(request: Request, csrf_token: str = Form(default=None)):
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get("csrf_token")
    submitted = csrf_token or request.headers.get("x-csrf-token")
    if not cookie or not submitted or submitted != cookie:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid. Reload the page and try again.")
