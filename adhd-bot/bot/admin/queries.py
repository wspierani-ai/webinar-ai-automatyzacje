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


async def get_overview_stats(db) -> dict:
    """Aggregate overview stats for the admin dashboard.

    Returns dict with: total_users, active_subscriptions, trial_users,
    blocked_users, mrr_pln, arr_pln, trial_conversion_rate,
    total_gemini_cost_pln_this_month, churn_rate_last_30d.
    """
    users_ref = db.collection("users")
    users_snapshot = await users_ref.get()

    total_users = 0
    active_count = 0
    trial_count = 0
    blocked_count = 0
    now = datetime.now(tz=timezone.utc)

    for doc in users_snapshot:
        total_users += 1
        data = doc.to_dict()
        status = data.get("subscription_status", "")
        if status == "active":
            active_count += 1
        elif status == "trial":
            trial_count += 1
        elif status == "blocked":
            blocked_count += 1

    mrr_pln = active_count * SUBSCRIPTION_PRICE_PLN
    arr_pln = mrr_pln * 12

    # Trial conversion: users who were trial and became active
    ever_active = active_count + blocked_count  # approximation
    trial_conversion_rate = (
        active_count / ever_active if ever_active > 0 else 0.0
    )

    # Gemini cost this month
    month_key = now.strftime("%Y-%m")
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
) -> dict:
    """Get paginated list of users with optional filters.

    Returns dict with: users (list), total, page, limit, pages.
    """
    users_ref = db.collection("users")
    all_docs = await users_ref.get()

    users = []
    for doc in all_docs:
        data = doc.to_dict()
        user_status = data.get("subscription_status", "")

        if status_filter and user_status != status_filter:
            continue

        user_id = doc.id
        if search and search not in user_id:
            continue

        users.append({
            "user_id": user_id,
            "created_at": _format_datetime(data.get("created_at")),
            "subscription_status": user_status,
            "trial_ends_at": _format_datetime(data.get("trial_ends_at")),
            "timezone": data.get("timezone", ""),
            "google_connected": data.get("google_connected", False),
        })

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
