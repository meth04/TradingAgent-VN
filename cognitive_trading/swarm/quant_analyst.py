"""Quant ReAct analyst for cognitive_trading."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.swarm.base_analyst import BaseAnalyst, ToolSpec
from vnstock.tools.quant_tool import QuantToolkit


class QuantAnalyst(BaseAnalyst):
    """Quant analyst using factor-based alpha diagnostics."""

    agent_name = "quant"
    analysis_brief = "Đánh giá sức mạnh factor, alpha score, dòng tiền ngoại và lợi thế định lượng."

    def __init__(
        self,
        *,
        quant_toolkit: QuantToolkit,
        config: CognitiveConfig | None = None,
    ) -> None:
        resolved_config = config or CognitiveConfig()
        super().__init__(
            model=resolved_config.quant_analyst_model,
            
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
        def factor_report(_: str) -> str:
            context_quant = context.get("quant_context", {})
            if context_quant:
                payload = {
                    "alpha_score": context_quant.get("alpha_score"),
                    "momentum_score": context_quant.get("momentum_score"),
                    "flow_score": context_quant.get("flow_score"),
                    "sentiment_score": context_quant.get("sentiment_score"),
                    "value_score": context_quant.get("value_score"),
                    "quality_score": context_quant.get("quality_score"),
                    "atr": context_quant.get("atr14_vnd"),
                    "components": {
                        "ema20": context_quant.get("ema20_vnd"),
                        "ema50": context_quant.get("ema50_vnd"),
                        "rsi14": context_quant.get("rsi14"),
                        "atr14": context_quant.get("atr14_vnd"),
                        "foreign_flow_5d": context_quant.get("foreign_flow_5d"),
                        "sentiment_score": context_quant.get("sentiment_score"),
                        "sentiment_conf": None,
                        "pe": context_quant.get("pe"),
                        "pb": context_quant.get("pb"),
                        "roe": context_quant.get("roe"),
                        "roa": context_quant.get("roa"),
                        "beta": context_quant.get("beta"),
                        "debt_equity": context_quant.get("debt_equity"),
                        "revenue_yoy": context_quant.get("revenue_yoy"),
                        "net_profit_yoy": context_quant.get("net_profit_yoy"),
                    },
                    "context_quant": context_quant,
                    "from_context_cache": True,
                }
            else:
                result = self.quant_toolkit.calculate_alpha_score(ticker, ref_date)
                payload = {
                    "alpha_score": result.alpha_score,
                    "momentum_score": result.momentum_score,
                    "flow_score": result.flow_score,
                    "sentiment_score": result.sentiment_score,
                    "value_score": result.value_score,
                    "quality_score": result.quality_score,
                    "atr": result.atr,
                    "components": {
                        "ema20": result.components.ema20,
                        "ema50": result.components.ema50,
                        "rsi14": result.components.rsi14,
                        "atr14": result.components.atr14,
                        "foreign_flow_5d": result.components.foreign_flow_5d,
                        "sentiment_score": result.components.sentiment_score,
                        "sentiment_conf": result.components.sentiment_conf,
                        "pe": result.components.pe,
                        "pb": result.components.pb,
                        "roe": result.components.roe,
                        "roa": result.components.roa,
                        "beta": result.components.beta,
                        "debt_equity": result.components.debt_equity,
                        "revenue_yoy": result.components.revenue_yoy,
                        "net_profit_yoy": result.components.net_profit_yoy,
                    },
                    "context_quant": context_quant,
                    "from_context_cache": False,
                }
            return json.dumps(payload, ensure_ascii=False, default=str)

        return (
            ToolSpec(
                name="factor_report",
                description="Trả về phân tích factor và alpha mang tính định lượng cho mã cổ phiếu.",
                function=factor_report,
            ),
        )


__all__ = ["QuantAnalyst"]
