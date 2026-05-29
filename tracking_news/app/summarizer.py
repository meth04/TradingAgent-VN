"""Summarization helper for MCP tools using LLM via proxy."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

try:  # Optional dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback when dotenv not installed

    def load_dotenv(*_args: Any, **_kwargs: Any) -> None:  # type: ignore
        return None


# Load env from vnstock/.env (fallback to project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VNSTOCK_ENV = _PROJECT_ROOT / "vnstock" / ".env"
load_dotenv(dotenv_path=_VNSTOCK_ENV)
if not os.getenv("CLIPROXY_API_KEY"):
    load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

MODEL_NAME = "coder-model"


def _build_prompt(articles: list[dict[str, Any]], agent_type: str, ticker: str | None) -> str:
    count = len(articles)
    if agent_type == "macro":
        return (
            f"Tóm tắt {count} tin vĩ mô. Mỗi tin nêu: (1) Sự kiện chính (2) "
            "Tác động TTCK VN (3) Mức quan trọng 1-5. Đưa ra nhận định tổng hợp."
        )
    target = ticker or "VN30"
    return (
        f"Tóm tắt {count} tin về {target}. Mỗi tin nêu: (1) Sự kiện (2) "
        "Tác động ngắn/dài hạn (3) Sentiment."
    )


async def summarize_for_agent(
    articles: list[dict[str, Any]], agent_type: str, ticker: str | None = None
) -> str:
    """
    Summarize a list of articles for a given agent type.

    Uses call_llm so all API requests go through the central semaphore,
    preventing uncontrolled concurrent requests to ProxyPal.
    """

    if not articles:
        return "No articles to summarize."

    prompt = _build_prompt(articles, agent_type, ticker)
    snippets = [f"- {a.get('title', '')}: {a.get('content_text', '')[:400]}" for a in articles]
    user_content = prompt + "\n" + "\n".join(snippets)

    try:
        from vnstock.core.llm import call_llm

        return await call_llm(
            system_prompt="Bạn là trợ lý tài chính.",
            user_prompt=user_content,
            model=MODEL_NAME,
        )
    except Exception as exc:
        return (
            "Summarizer unavailable; use raw snippets. "
            f"Reason: {exc} | Articles: \n" + "\n".join(snippets)
        )


async def close_session() -> None:
    """No-op — session is managed by vnstock.core.llm now."""
    pass


def summarize_for_agent_sync(
    articles: list[dict[str, Any]], agent_type: str, ticker: str | None = None
) -> str:
    """Synchronous wrapper for test convenience."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(summarize_for_agent(articles, agent_type, ticker))
    return loop.run_until_complete(summarize_for_agent(articles, agent_type, ticker))
