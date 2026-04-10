"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from bot.admin.auth import router as admin_auth_router
from bot.admin.middleware import AdminAuditMiddleware
from bot.admin.router import router as admin_dashboard_router
from bot.handlers.cleanup_handler import router as cleanup_router
from bot.handlers.google_oauth_handler import router as google_oauth_router
from bot.handlers.gtasks_polling_handler import router as gtasks_polling_router
from bot.handlers.internal_triggers import router as internal_router
from bot.handlers.stripe_webhook_handler import router as stripe_router
from bot.security.headers import SecurityHeadersMiddleware
from bot.security.rate_limiter import limiter, rate_limit_exceeded_handler
from bot.webhook import router as webhook_router

app = FastAPI(title="ADHD Reminder Bot", version="1.0.0")

# Security middleware (order matters — outermost first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AdminAuditMiddleware)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Bot routes
app.include_router(webhook_router)
app.include_router(internal_router)
app.include_router(cleanup_router)
app.include_router(stripe_router)
app.include_router(google_oauth_router)
app.include_router(gtasks_polling_router)

# Admin routes
app.include_router(admin_auth_router)
app.include_router(admin_dashboard_router)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "healthy"})
