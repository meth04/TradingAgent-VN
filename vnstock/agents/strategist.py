"""Strategist Agent using real LLM reflection."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, Tuple
import json

from config import models
from vnstock.agents.prompting import LEGACY_ACTION_ALIASES, inject_json_cot
from vnstock.core.llm import call_llm


@dataclass
class StrategyParams:
    # Tier 1 thresholds (Sentinel)
    price_change_threshold: float = 1.5
    vol_ratio_threshold: float = 1.5
    news_min_count: int = 1

    # Tier 2 thresholds (Decision)
    alpha_threshold: float = 25.0
    sell_threshold_offset: float = 10.0
    atr_scale: float = 1.0

    # Alpha-Beta weights
    weight_alpha: float = 0.5
    weight_beta: float = 0.5


class StrategistAgent:
    def __init__(self) -> None:
        pass

    @staticmethod
    def _action_enum_help() -> str:
        aliases = ", ".join(f"{k}->{v.value}" for k, v in LEGACY_ACTION_ALIASES.items())
        return (
            "Hành động hợp lệ (enum, viết hoa): BUY, BUY_MORE, SELL, TRIMMING, PASS, HOLD. "
            f"Alias: {aliases}."
        )

    @staticmethod
    def _schema() -> str:
        schema_body = """
        {
          "action": "BUY|BUY_MORE|SELL|TRIMMING|PASS|HOLD",
          "weight_pct": "float >=0",
          "reasoning": "rationale",
          "notes": "optional"
        }
        """
        return inject_json_cot(schema_body)

    def _build_prompts(self, history: Dict[str, Any], current_params: StrategyParams) -> Tuple[str, str]:
        system = (
            "Bạn là Meta-Strategist cho hệ thống giao dịch cổ phiếu VN30. "
            "Hãy đọc các chỉ số hiệu suất và bộ tham số hiện tại, sau đó đề xuất tham số tối ưu hơn. "
            "Bạn có thể điều chỉnh cả ngưỡng quét cơ hội lẫn ngưỡng ra quyết định. "
            "Chỉ được trả về JSON hợp lệ đúng schema và action cho phép. "
            + self._action_enum_help()
            + " CoT schema prefix (khóa đầu tiên bắt buộc): "
            + self._schema()
        )
        user = (
            f"Hiệu suất: {json.dumps(history, ensure_ascii=False)}\n"
            f"Tham số hiện tại: {json.dumps(asdict(current_params), ensure_ascii=False)}\n"
            "Quy tắc:\n"
            "- price_change_threshold: 0.5-5.0 (thấp hơn = nhiều tín hiệu hơn)\n"
            "- vol_ratio_threshold: 1.0-3.0\n"
            "- news_min_count: 0-5\n"
            "- alpha_threshold: 15-50 (thấp hơn = nhiều lệnh mua hơn)\n"
            "- sell_threshold_offset: 5-20\n"
            "- atr_scale: 0.5-2.0\n"
            "- weight_alpha + weight_beta nên xấp xỉ 1.0\n"
            "Trả về duy nhất một JSON theo đúng schema trên và viết reasoning bằng tiếng Việt."
        )
        return system, user

    async def reflect(self, history: Dict[str, Any], current_params: StrategyParams) -> StrategyParams:
        system, user = self._build_prompts(history, current_params)
        try:
            resp = await call_llm(
                system,
                user,
                temperature=0.2,
                model=models.t4_cio_model,
                
            )
        except Exception:
            return current_params

        try:
            obj = json.loads(resp)
        except Exception:
            raise ValueError("Strategist response is not valid JSON")

        if "_thought_process" not in obj and "analysis_steps" not in obj:
            raise ValueError("Missing analysis_steps/_thought_process in strategist reflection output")

        return StrategyParams(
            price_change_threshold=float(obj.get("price_change_threshold", current_params.price_change_threshold)),
            vol_ratio_threshold=float(obj.get("vol_ratio_threshold", current_params.vol_ratio_threshold)),
            news_min_count=int(obj.get("news_min_count", current_params.news_min_count)),
            alpha_threshold=float(obj.get("alpha_threshold", current_params.alpha_threshold)),
            sell_threshold_offset=float(obj.get("sell_threshold_offset", current_params.sell_threshold_offset)),
            atr_scale=float(obj.get("atr_scale", current_params.atr_scale)),
            weight_alpha=float(obj.get("weight_alpha", current_params.weight_alpha)),
            weight_beta=float(obj.get("weight_beta", current_params.weight_beta)),
        )
