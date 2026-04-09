"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bot.webhook import router as webhook_router
from bot.handlers.internal_triggers import router as internal_router
from bot.handlers.cleanup_handler import router as cleanup_router
from bot.handlers.stripe_webhook_handler import router as stripe_router

app = FastAPI(title="ADHD Reminder Bot", version="1.0.0")

app.include_router(webhook_router)
app.include_router(internal_router)
app.include_router(cleanup_router)
app.include_router(stripe_router)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "healthy"})
