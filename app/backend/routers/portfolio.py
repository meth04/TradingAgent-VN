"""Portfolio CRUD + value endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services import portfolio_service

router = APIRouter()


class Position(BaseModel):
    ticker: str
    quantity: int = Field(ge=0)
    avg_price: float = Field(ge=0)


class PortfolioBody(BaseModel):
    cash: float = 0
    positions: List[Position] = []


@router.get("/portfolio")
def get_portfolio() -> Dict[str, Any]:
    return portfolio_service.load_portfolio()


@router.post("/portfolio")
def post_portfolio(body: PortfolioBody) -> Dict[str, Any]:
    payload = {
        "cash": body.cash,
        "positions": [p.model_dump() for p in body.positions],
    }
    return portfolio_service.save_portfolio(payload)


@router.get("/portfolio/value")
def portfolio_value() -> Dict[str, Any]:
    return portfolio_service.compute_value()
