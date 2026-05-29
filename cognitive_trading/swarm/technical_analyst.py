"""Technical ReAct analyst for cognitive_trading."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.swarm.base_analyst import BaseAnalyst, ToolSpec
from vnstock.tools.quant_tool import QuantToolkit


class TechnicalAnalyst(BaseAnalyst):
    """Technical analyst using deterministic RSI, MACD, and alpha context."""

    agent_name = "technical"
    analysis_brief = "Đánh giá tín hiệu kỹ thuật, xu hướng, RSI, MACD và trạng thái động lượng."

    def __init__(
        self,
        *,
        quant_toolkit: QuantToolkit,
        config: CognitiveConfig | None = None,
    ) -> None:
        resolved_config = config or CognitiveConfig()
        super().__init__(
            model=resolved_config.technical_analyst_model,
            
            config=resolved_config,
        )
        self.quant_toolkit = quant_toolkit

    def build_tools(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> Sequence[ToolSpec]:
        def technical_snapshot(_: str) -> str:
            payload = {
                "price_context": context.get("price_context", {}),
                "quant_context": context.get("quant_context", {}),
            }
            if not payload["quant_context"]:
                payload["quick_report"] = self.quant_toolkit.quick_report(ticker, ref_date)
            return json.dumps(payload, ensure_ascii=False, default=str)

        return (
            ToolSpec(
                name="technical_snapshot",
                description="Trả về RSI, MACD, alpha score và ngữ cảnh giá cho mã cổ phiếu.",
                function=technical_snapshot,
            ),
        )


__all__ = ["TechnicalAnalyst"]
