"""HTTP tool wrappers for the HR Action Agent.

Every tool in this module calls an existing REST endpoint of this app
in-process (httpx ASGI transport, no network hop), forwarding the
logged-in user's own JWT. Tools never open a DB session and never accept
an employee_id — identity always comes from the token, so acting on
another user's behalf is structurally impossible rather than merely
refused. Validation and business rules stay in the endpoints; this layer
only translates arguments in and error envelopes out.

Every tool returns the app's standard envelope:
    {"success": bool, "data": ..., "error": {"code", "message"} | None}
and never raises — upstream/network failures are normalized to an
UPSTREAM_ERROR envelope so raw errors can't leak into chat output.

Known limitation of the underlying API (relevant to the future
approve/reject tools): POST /leaves/requests/{id}/approve and /reject
check role only, not team membership — any manager can act on any
employee's leave. The AI permissions matrix requires managers to act on
their own team only, so the tool layer must verify the target employee's
manager_id against the calling manager before invoking those endpoints.
Do not add approve/reject tools here until that check exists in the
permissions layer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

API_PREFIX = "/api/v1"


def _make_client() -> httpx.AsyncClient:
    # Imported lazily: this module is imported from chat endpoints,
    # which app.main imports at startup. The ASGI transport calls the
    # app object directly in-process, so a per-call client is free —
    # there is no connection pool worth caching.
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://hrms.internal",
        timeout=httpx.Timeout(30.0),
    )


def _auth_headers(token: str) -> dict[str, str]:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:]
    return {"Authorization": f"Bearer {token}"}


def _tool_error(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "data": None, "error": {"code": code, "message": message}}


def _iso_date(value: date | str, field: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a date in YYYY-MM-DD format")


def _summarize_validation_errors(detail: Any) -> str:
    # FastAPI 422 detail: [{"loc": ["body", "reason"], "msg": ...}, ...]
    if not isinstance(detail, list):
        return "The request was invalid."
    parts = []
    for item in detail[:5]:
        if isinstance(item, dict):
            loc = item.get("loc") or []
            field = str(loc[-1]) if loc else "request"
            parts.append(f"{field}: {item.get('msg', 'invalid value')}")
    return "; ".join(parts) or "The request was invalid."


def _normalize_response(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        return _tool_error("UPSTREAM_ERROR", "The HR service returned an unexpected response.")

    if resp.status_code < 400:
        if isinstance(body, dict) and body.get("success") is True:
            return {"success": True, "data": body.get("data"), "error": None}
        return _tool_error("UPSTREAM_ERROR", "The HR service returned an unexpected response.")

    detail = body.get("detail") if isinstance(body, dict) else None
    # Endpoints raise HTTPException(detail=error_response(...)), so the
    # envelope arrives nested under "detail".
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        return {"success": False, "data": None, "error": detail["error"]}
    if resp.status_code == 422:
        return _tool_error("VALIDATION_ERROR", _summarize_validation_errors(detail))
    if resp.status_code in (401, 403):
        return _tool_error("NOT_AUTHORIZED", "You are not authorized to perform this action.")
    return _tool_error("UPSTREAM_ERROR", "The HR service could not process the request.")


async def _request(method: str, path: str, token: str, **kwargs: Any) -> dict[str, Any]:
    try:
        async with _make_client() as client:
            resp = await client.request(
                method, f"{API_PREFIX}{path}", headers=_auth_headers(token), **kwargs
            )
    except httpx.HTTPError:
        return _tool_error("UPSTREAM_ERROR", "The HR service is currently unavailable.")
    return _normalize_response(resp)


async def create_leave_request(
    token: str,
    *,
    leave_type: str,
    start_date: date | str,
    end_date: date | str,
    reason: str,
    is_half_day: bool = False,
    half_day_period: str | None = None,
) -> dict[str, Any]:
    """Create a leave request for the calling user (lands as PENDING;
    auto-approved by the API if the caller is an admin)."""
    try:
        payload = {
            "leave_type": leave_type,
            "start_date": _iso_date(start_date, "start_date"),
            "end_date": _iso_date(end_date, "end_date"),
            "reason": reason,
            "is_half_day": is_half_day,
            "half_day_period": half_day_period,
        }
    except ValueError as exc:
        return _tool_error("VALIDATION_ERROR", str(exc))
    return await _request("POST", "/leaves/requests", token, json=payload)


async def get_my_leave_balance(token: str) -> dict[str, Any]:
    """Fetch the calling user's leave balances (casual/sick/earned)."""
    return await _request("GET", "/leaves/balances/me", token)


async def get_my_leave_requests(
    token: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Fetch the calling user's leave requests, newest first."""
    params = {"limit": min(max(limit, 1), 100), "offset": max(offset, 0)}
    return await _request("GET", "/leaves/requests/me", token, params=params)
