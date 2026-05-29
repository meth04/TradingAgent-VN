"""News ReAct analyst for cognitive_trading."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.swarm.base_analyst import BaseAnalyst, ToolSpec
from vnstock.tools.search_tool import SearchToolkit


class NewsAnalyst(BaseAnalyst):
    """Ticker-specific news sentiment analyst using tracking_news search."""

    agent_name = "news"
    analysis_brief = "Đánh giá sắc thái tin tức riêng của mã, catalyst và rủi ro sự kiện."

    def __init__(
        self,
        *,
        search_toolkit: type[SearchToolkit] = SearchToolkit,
        config: CognitiveConfig | None = None,
    ) -> None:
        resolved_config = config or CognitiveConfig()
        super().__init__(
            model=resolved_config.news_analyst_model,
            
            config=resolved_config,
        )
        self.search_toolkit = search_toolkit

    def build_tools(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> Sequence[ToolSpec]:
        async def ticker_news(query: str) -> str:
            del query
            news_context = dict(context.get("news_context", {}))
            summary = str(news_context.get("summary") or "Không tìm thấy bài viết liên quan.")
            top_articles = news_context.get("top_articles") or []
            if not top_articles:
                return summary
            headlines = "\n".join(
                f"- {item.get('published_date')}: {item.get('title')}"
                for item in top_articles
                if isinstance(item, Mapping) and item.get("title")
            )
            return f"{summary}\n{headlines}".strip()

        return (
            ToolSpec(
                name="ticker_news",
                description="Lấy tóm tắt tin tức riêng cho mã tại hoặc trước ref_date.",
                function=ticker_news,
            ),
        )


__all__ = ["NewsAnalyst"]
