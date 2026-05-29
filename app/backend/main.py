"""FastAPI entry point for the Multi-Agent Stock Analyzer backend."""

from __future__ import annotations

# Path setup MUST run first.
from bootstrap import ROOT, APP_DIR, APP_DATA_DIR  # noqa: F401  (also has side effects)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import analysis, history, market, portfolio

app = FastAPI(title="Multi-Agent Stock Analyzer API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(market.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
