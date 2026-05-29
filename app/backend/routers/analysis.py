"""Job-based analysis API.

POST /api/analyze        → start a new analysis, returns {"job_id"}.
GET  /api/analyze/{id}   → return the current job snapshot for polling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.analysis_service import (
    AnalysisRequest,
    create_job,
    get_job_snapshot,
)

router = APIRouter()


class AnalyzeBody(BaseModel):
    tickers: List[str] = Field(..., min_length=1)
    workflow: str = "cognitive"
    portfolio: Optional[Dict[str, Any]] = None


@router.post("/analyze")
async def analyze(body: AnalyzeBody) -> Dict[str, Any]:
    tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="Cần ít nhất 1 ticker")
    job_id = create_job(
        AnalysisRequest(
            tickers=tickers,
            workflow=body.workflow.lower(),
            portfolio=body.portfolio,
        )
    )
    return {"job_id": job_id, "status": "running"}


@router.get("/analyze/{job_id}")
async def analyze_status(job_id: str) -> Dict[str, Any]:
    snap = get_job_snapshot(job_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    return snap
