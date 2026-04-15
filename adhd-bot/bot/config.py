"""Bot configuration with fail-fast validation."""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    telegram_bot_token: str = field(default="")
    telegram_secret_token: str = field(default="")
    gcp_project_id: str = field(default="")
    gcp_region: str = field(default="europe-central2")
    cloud_tasks_reminders_queue: str = field(default="reminders")
    cloud_tasks_nudges_queue: str = field(default="nudges")
    cloud_run_service_url: str = field(default="")
    stripe_api_key: str = field(default="")
    stripe_webhook_secret: str = field(default="")
    stripe_price_id: str = field(default="")
    admin_jwt_secret: str = field(default="")
    admin_email_whitelist: list[str] = field(default_factory=list)
    google_client_id: str = field(default="")
    google_client_secret: str = field(default="")

    REQUIRED_FIELDS = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_SECRET_TOKEN",
        "GCP_PROJECT_ID",
        "CLOUD_RUN_SERVICE_URL",
    ]

    def __post_init__(self) -> None:
        missing = [f for f in self.REQUIRED_FIELDS if not os.environ.get(f)]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

    @classmethod
    def from_env(cls) -> "Config":
        whitelist_raw = os.environ.get("ADMIN_EMAIL_WHITELIST", "")
        whitelist = [e.strip() for e in whitelist_raw.split(",") if e.strip()]
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_secret_token=os.environ.get("TELEGRAM_SECRET_TOKEN", ""),
            gcp_project_id=os.environ.get("GCP_PROJECT_ID", ""),
            gcp_region=os.environ.get("GCP_REGION", "europe-central2"),
            cloud_tasks_reminders_queue=os.environ.get(
                "CLOUD_TASKS_REMINDERS_QUEUE", "reminders"
            ),
            cloud_tasks_nudges_queue=os.environ.get(
                "CLOUD_TASKS_NUDGES_QUEUE", "nudges"
            ),
            cloud_run_service_url=os.environ.get("CLOUD_RUN_SERVICE_URL", ""),
            stripe_api_key=os.environ.get("STRIPE_API_KEY", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_id=os.environ.get("STRIPE_PRICE_ID", ""),
            admin_jwt_secret=os.environ.get("ADMIN_JWT_SECRET", ""),
            admin_email_whitelist=whitelist,
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        )
