"""Market endpoints: latest prices, recent news, manual sync."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services import market_service

router = APIRouter()


@router.get("/market/prices")
async def get_prices(tickers: str = Query("", description="Comma-separated tickers")) -> Dict[str, float]:
    items = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    return market_service.get_latest_prices(items)


@router.get("/market/news")
def get_news(limit: int = Query(20, ge=1, le=100)) -> List[Dict[str, Any]]:
    return market_service.get_recent_news(limit=limit)


class SyncBody(BaseModel):
    tickers: List[str] = []
    force: bool = False
    include_news: bool = True


@router.post("/market/sync")
async def sync_market(body: SyncBody) -> Dict[str, Any]:
    """Manually trigger price sync + optional news crawl."""
    out: Dict[str, Any] = {}
    tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    if tickers:
        out["prices"] = await market_service.sync_prices_today_async(
            tickers, force=body.force
        )
    if body.include_news:
        out["news"] = await market_service.crawl_news_lite_async(force=body.force)
    return out
