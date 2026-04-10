"""Admin dashboard API + Web UI router.

Endpoints:
  GET  /admin                                  → dashboard page
  GET  /admin/users                            → users list page
  GET  /admin/users/{user_id}                  → user detail page
  GET  /admin/api/overview                     → JSON overview stats
  GET  /admin/api/users                        → JSON users list
  GET  /admin/api/users/{user_id}              → JSON user detail
  PATCH /admin/api/users/{user_id}/subscription → update subscription
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bot.admin.auth import create_audit_log
from bot.admin.middleware import AdminSession, require_admin, require_admin_write
from bot.admin.queries import get_overview_stats, get_user_detail, get_users_list
from bot.services.firestore_client import get_firestore_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


def _get_templates():
    """Return Jinja2 templates instance."""
    from jinja2 import Environment, FileSystemLoader

    template_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "templates",
        "admin",
    )
    return Environment(loader=FileSystemLoader(template_dir), autoescape=True)


# --- Web UI (HTML) ---


@router.get("", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    session: AdminSession = Depends(require_admin),
) -> HTMLResponse:
    """Render admin dashboard page."""
    env = _get_templates()
    template = env.get_template("dashboard.html")
    html = template.render(email=session.email, role=session.role)
    return HTMLResponse(content=html)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    session: AdminSession = Depends(require_admin),
) -> HTMLResponse:
    """Render users list page."""
    env = _get_templates()
    template = env.get_template("users.html")
    html = template.render(email=session.email, role=session.role)
    return HTMLResponse(content=html)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail_page(
    user_id: str,
    request: Request,
    session: AdminSession = Depends(require_admin),
) -> HTMLResponse:
    """Render user detail page."""
    env = _get_templates()
    template = env.get_template("user_detail.html")
    html = template.render(
        email=session.email,
        role=session.role,
        user_id=user_id,
    )
    return HTMLResponse(content=html)


# --- API (JSON) ---


@router.get("/api/overview")
async def api_overview(
    session: AdminSession = Depends(require_admin),
) -> JSONResponse:
    """Return overview stats as JSON."""
    db = get_firestore_client()
    stats = await get_overview_stats(db)
    return JSONResponse(content=stats)


@router.get("/api/users")
async def api_users(
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    session: AdminSession = Depends(require_admin),
) -> JSONResponse:
    """Return paginated user list as JSON."""
    db = get_firestore_client()
    result = await get_users_list(
        db, status_filter=status, search=search, page=page, limit=limit
    )
    return JSONResponse(content=result)


@router.get("/api/users/{user_id}")
async def api_user_detail(
    user_id: str,
    session: AdminSession = Depends(require_admin),
) -> JSONResponse:
    """Return user detail as JSON."""
    db = get_firestore_client()
    detail = await get_user_detail(db, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    return JSONResponse(content=detail)


@router.patch("/api/users/{user_id}/subscription")
async def api_update_subscription(
    user_id: str,
    request: Request,
    session: AdminSession = Depends(require_admin_write),
) -> JSONResponse:
    """Update user subscription (unblock, extend trial).

    Body: {"action": "unblock" | "extend_trial_days", "days": int (optional)}
    """
    body = await request.json()
    action = body.get("action", "")

    db = get_firestore_client()
    doc_ref = db.collection("users").document(user_id)
    doc = await doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(tz=timezone.utc)

    if action == "unblock":
        await doc_ref.update({
            "subscription_status": "active",
            "updated_at": now,
        })
    elif action == "extend_trial_days":
        days = body.get("days", 7)
        await doc_ref.update({
            "subscription_status": "trial",
            "trial_ends_at": now + timedelta(days=days),
            "updated_at": now,
        })
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    # Create audit log
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    await create_audit_log(
        db=db,
        admin_email=session.email,
        action=f"subscription_{action}",
        target=user_id,
        ip=ip,
        user_agent=user_agent,
    )

    return JSONResponse(content={"status": "ok", "action": action, "user_id": user_id})
