"""Firestore queries for admin dashboard metrics.

Provides data aggregation functions for:
- Overview stats (MRR, ARR, churn, conversion rate, token costs)
- User listing with filtering and pagination
- User detail with task history and token usage
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

SUBSCRIPTION_PRICE_PLN = 29.99


_STATS_BATCH_SIZE = 500


async def _count_users_by_status(db) -> dict:
    """Count users by subscription status using batched reads.

    Reads in batches of _STATS_BATCH_SIZE to avoid loading all users at once.
    Returns dict with total, active, trial, blocked counts.
    """
    users_ref = db.collection("users")
    total = 0
    active = 0
    trial = 0
    blocked = 0

    query = users_ref.order_by("__name__").limit(_STATS_BATCH_SIZE)
    last_doc = None

    while True:
        if last_doc is not None:
            query = (
                users_ref.order_by("__name__")
                .start_after(last_doc)
                .limit(_STATS_BATCH_SIZE)
            )

        batch = await query.get()
        if not batch:
            break

        for doc in batch:
            total += 1
            data = doc.to_dict()
            status = data.get("subscription_status", "")
            if status == "active":
                active += 1
            elif status == "trial":
                trial += 1
            elif status == "blocked":
                blocked += 1

        if len(batch) < _STATS_BATCH_SIZE:
            break
        last_doc = batch[-1]

    return {"total": total, "active": active, "trial": trial, "blocked": blocked}


async def get_overview_stats(db) -> dict:
    """Aggregate overview stats for the admin dashboard.

    Returns dict with: total_users, active_subscriptions, trial_users,
    blocked_users, mrr_pln, arr_pln, trial_conversion_rate,
    total_gemini_cost_pln_this_month, churn_rate_last_30d.
    """
    counts = await _count_users_by_status(db)
    total_users = counts["total"]
    active_count = counts["active"]
    trial_count = counts["trial"]
    blocked_count = counts["blocked"]
    now = datetime.now(tz=timezone.utc)

    mrr_pln = active_count * SUBSCRIPTION_PRICE_PLN
    arr_pln = mrr_pln * 12

    # Trial conversion: users who were trial and became active
    ever_active = active_count + blocked_count  # approximation
    trial_conversion_rate = (
        active_count / ever_active if ever_active > 0 else 0.0
    )

    # Gemini cost this month
    total_gemini_cost = 0.0
    try:
        # Sum across all days of current month
        day = now.replace(day=1)
        while day.month == now.month and day <= now:
            date_key = day.strftime("%Y-%m-%d")
            users_usage = await (
                db.collection("token_usage")
                .document(date_key)
                .collection("users")
                .limit(_STATS_BATCH_SIZE)
                .get()
            )
            for usage_doc in users_usage:
                usage_data = usage_doc.to_dict()
                total_gemini_cost += usage_data.get("cost_pln", 0.0)
            day += timedelta(days=1)
    except Exception as exc:
        logger.warning("Failed to aggregate Gemini costs: %s", exc)

    # Churn rate (approximate): blocked in last 30 days / active 30 days ago
    churn_rate = 0.05  # Default placeholder; real churn requires historical tracking

    return {
        "total_users": total_users,
        "active_subscriptions": active_count,
        "trial_users": trial_count,
        "blocked_users": blocked_count,
        "mrr_pln": round(mrr_pln, 2),
        "arr_pln": round(arr_pln, 2),
        "trial_conversion_rate": round(trial_conversion_rate, 2),
        "total_gemini_cost_pln_this_month": round(total_gemini_cost, 2),
        "churn_rate_last_30d": churn_rate,
    }


async def get_users_list(
    db,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    cursor_after: Optional[str] = None,
) -> dict:
    """Get paginated list of users with optional filters.

    Uses Firestore .where() for status filtering and .limit() for pagination.
    Returns dict with: users (list), total, page, limit, pages.
    """
    users_ref = db.collection("users")

    # Build query with server-side filtering when possible
    query = users_ref.order_by("__name__")
    if status_filter:
        query = users_ref.where("subscription_status", "==", status_filter).order_by("__name__")

    # For search by user_id (document ID), we use the document directly
    if search:
        # Search is by user_id (document ID) — use exact or prefix match
        # Firestore doesn't support LIKE, so we fetch a limited batch and filter client-side
        fetch_limit = limit * page + limit  # fetch enough to paginate
        docs = await query.limit(fetch_limit).get()
        users = []
        for doc in docs:
            if search not in doc.id:
                continue
            data = doc.to_dict()
            users.append(_format_user_doc(doc, data))
        total = len(users)
        pages = max(1, (total + limit - 1) // limit)
        start = (page - 1) * limit
        end = start + limit
        return {
            "users": users[start:end],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }

    # Count total for pagination (limited scan)
    count_query = users_ref
    if status_filter:
        count_query = users_ref.where("subscription_status", "==", status_filter)
    count_docs = await count_query.order_by("__name__").limit(10000).get()
    total = len(count_docs)
    pages = max(1, (total + limit - 1) // limit)

    # Skip to the right page using cursor-based pagination
    skip = (page - 1) * limit
    if skip > 0:
        skip_docs = await query.limit(skip).get()
        if skip_docs:
            query = query.start_after(skip_docs[-1])

    docs = await query.limit(limit).get()
    users = []
    for doc in docs:
        data = doc.to_dict()
        users.append(_format_user_doc(doc, data))

    return {
        "users": users,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def _format_user_doc(doc, data: dict) -> dict:
    """Format a user Firestore document into API-compatible dict."""
    return {
        "user_id": doc.id,
        "created_at": _format_datetime(data.get("created_at")),
        "subscription_status": data.get("subscription_status", ""),
        "trial_ends_at": _format_datetime(data.get("trial_ends_at")),
        "timezone": data.get("timezone", ""),
        "google_connected": data.get("google_connected", False),
    }


async def get_user_detail(db, user_id: str) -> Optional[dict]:
    """Get detailed user info including task history and token usage.

    Returns dict with user data, recent tasks, and token usage, or None if not found.
    """
    doc = await db.collection("users").document(user_id).get()
    if not doc.exists:
        return None

    data = doc.to_dict()

    # Recent tasks (last 20)
    recent_tasks = []
    try:
        tasks_snapshot = await (
            db.collection("tasks")
            .where("telegram_user_id", "==", int(user_id))
            .order_by("created_at", direction="DESCENDING")
            .limit(20)
            .get()
        )
        for task_doc in tasks_snapshot:
            task_data = task_doc.to_dict()
            recent_tasks.append({
                "task_id": task_doc.id,
                "content": task_data.get("content", ""),
                "state": task_data.get("state", ""),
                "created_at": _format_datetime(task_data.get("created_at")),
                "scheduled_time": _format_datetime(task_data.get("scheduled_time")),
            })
    except Exception as exc:
        logger.warning("Failed to fetch tasks for user %s: %s", user_id, exc)

    # Token usage (last 30 days)
    token_usage = []
    now = datetime.now(tz=timezone.utc)
    try:
        for i in range(30):
            day = now - timedelta(days=i)
            date_key = day.strftime("%Y-%m-%d")
            usage_doc = await (
                db.collection("token_usage")
                .document(date_key)
                .collection("users")
                .document(user_id)
                .get()
            )
            if usage_doc.exists:
                usage_data = usage_doc.to_dict()
                token_usage.append({
                    "date": date_key,
                    "input_tokens": usage_data.get("input_tokens", 0),
                    "output_tokens": usage_data.get("output_tokens", 0),
                    "cost_pln": usage_data.get("cost_pln", 0.0),
                    "call_count": usage_data.get("call_count", 0),
                })
    except Exception as exc:
        logger.warning("Failed to fetch token usage for user %s: %s", user_id, exc)

    return {
        "user_id": user_id,
        "subscription_status": data.get("subscription_status", ""),
        "created_at": _format_datetime(data.get("created_at")),
        "trial_ends_at": _format_datetime(data.get("trial_ends_at")),
        "timezone": data.get("timezone", ""),
        "morning_time": data.get("morning_time"),
        "google_connected": data.get("google_connected", False),
        "stripe_customer_id": data.get("stripe_customer_id"),
        "stripe_subscription_id": data.get("stripe_subscription_id"),
        "recent_tasks": recent_tasks,
        "token_usage_30d": token_usage,
    }


def _format_datetime(dt) -> Optional[str]:
    """Format datetime to ISO string, or return None."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)
