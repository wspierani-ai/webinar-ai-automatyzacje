"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="ADHD Reminder Bot", version="1.0.0")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "healthy"})


# Routers registered after all modules are implemented
# app.include_router(webhook_router)
# app.include_router(internal_router)
# app.include_router(stripe_router)
# app.include_router(admin_router)
