"""History list / detail endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from services import history_service

router = APIRouter()


@router.get("/history")
def list_history() -> List[Dict[str, Any]]:
    return history_service.list_analyses()


@router.get("/history/{analysis_id}")
def get_history(analysis_id: str) -> Dict[str, Any]:
    data = history_service.get_analysis(analysis_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phân tích")
    return data
