from __future__ import annotations

from typing import Dict

from vnstock.agents.prompting import BACKTEST_CONTEXT
from vnstock.core.llm import call_llm, LLMError
from vnstock.workflows.base import AgentOutput
from vnstock.workflows.debate.autogen_debate import run_autogen_debate
from vnstock.workflows.utils import safe_json_extract
from config import workflow_weights, strategy, models


class TraditionalScoringWorkflow:
    """Tier-3 debate + Tier-4 CIO for baseline qualitative workflow."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or models.t4_cio_model

    async def run(
        self,
        *,
        ticker: str,
        ref_date: str,
        agent_outputs: Dict[str, AgentOutput],
        current_weight_pct: float,
        portfolio_snapshot: Dict[str, object],
        llm_semaphore=None,
        debate_res: Dict[str, object] | None = None,
    ) -> Dict[str, object]:
        from config import models

        if debate_res is None:
            debate_res = await run_autogen_debate(
                ticker=ticker,
                ref_date=ref_date,
                agent_outputs=agent_outputs,
                llm_semaphore=llm_semaphore,
                model=models.t3_debate_model,
            )
        transcript = str(debate_res.get("transcript") or "")
        final_score = float(debate_res.get("final_score") or 0.0)

        cio_system = (
            f"{BACKTEST_CONTEXT} "
            "Bạn là Strategic CIO của quỹ đầu tư multi-agent. Suy luận từng bước bằng tiếng Việt:\n"
            "1) MULTI-AGENT ANALYSIS: Phân tích consensus vs conflict giữa 5 chuyên gia (Macro, News, Technical, Quant, Financial).\n"
            "   - Xác định điểm đồng thuận (consensus): Các agent nào cùng quan điểm? Bằng chứng nào trùng lặp?\n"
            "   - Xác định điểm xung đột (conflict): Agent nào bất đồng? Lý do gốc rễ của disagreement?\n"
            "2) CROSS-AGENT RATIONALE: Tổng hợp reasoning xuyên suốt các agent.\n"
            "   - Bull case: Tổng hợp luận điểm tích cực từ tất cả agents (không chỉ Bull trong debate).\n"
            "   - Bear case: Tổng hợp luận điểm tiêu cực từ tất cả agents (không chỉ Bear trong debate).\n"
            "   - Evidence quality: Đánh giá độ tin cậy của bằng chứng (hard data vs speculation).\n"
            "3) DEBATE SYNTHESIS: Tổng hợp kết luận từ Bull-Bear debate (verdict, final_score).\n"
            "4) PORTFOLIO CONTEXT: Kiểm tra portfolio_snapshot (cash, qty, avg_price, available_qty).\n"
            "   - Nếu đã có vị thế: Cân nhắc BUY_MORE vs SELL vs HOLD dựa trên P&L hiện tại.\n"
            "   - Nếu chưa có vị thế: Đánh giá độ mạnh điểm vào (conviction level).\n"
            "5) FINAL DECISION: Xuất action kèm reasoning chi tiết. Chỉ trả JSON hợp lệ theo schema."
        )
        cio_user = (
            "Bạn là quỹ đầu tư chiến lược, KHÔNG phải day-trader.\n"
            "Hành động hợp lệ: BUY (mới), BUY_MORE (đã có vị thế), HOLD, SELL (chỉ khi có vị thế), IGNORE.\n"
            "Không được short. Nếu không có vị thế mà SELL => INVALID.\n"
            f"Vị thế hiện tại: {current_weight_pct:.2f}% NAV. Portfolio snapshot: {portfolio_snapshot}.\n"
            f"Nếu BUY/BUY_MORE, weight_pct phải > hiện tại và mục tiêu ~{workflow_weights.trad_target_weight}%. Nếu không, HOLD.\n\n"
            "=== TAKE-PROFIT RULES (ƯU TIÊN CAO) ===\n"
            f"P&L hiện tại: {portfolio_snapshot.get('unrealized_pnl_pct', 0):.2f}%\n"
            "- Nếu P&L > +15% VÀ (verdict bearish HOẶC final_score < 0) → SELL để chốt lời\n"
            "- Nếu P&L > +20% → SELL toàn bộ bất kể verdict\n"
            "- Nếu P&L < -5% VÀ verdict bearish → SELL để cắt lỗ sớm\n"
            "- Nếu P&L trong khoảng -5% đến +15% → Theo debate verdict\n\n"
            "REASONING STRUCTURE (bắt buộc):\n"
            "  - Consensus: [Điểm đồng thuận giữa agents]\n"
            "  - Conflict: [Điểm xung đột và cách giải quyết]\n"
            "  - Evidence: [Bằng chứng chính hỗ trợ quyết định]\n"
            "  - P&L Check: [Kiểm tra take-profit/stop-loss]\n"
            "  - Decision: [Quyết định cuối cùng và lý do]\n"
            "Schema bắt buộc: {\"action\": \"BUY\"|\"BUY_MORE\"|\"HOLD\"|\"SELL\"|\"IGNORE\", \"weight_pct\": float, \"reasoning\": <string>}. Không thêm text khác.\n"
            f"Đầu vào: final_score={final_score:.3f}."
        )
        try:
            decision_text = await call_llm(
                cio_system,
                f"Transcript:\n{transcript}\n\n{cio_user}",
                model=models.t4_cio_model,
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            return {
                "transcript": transcript,
                "decision": {"action": "HOLD", "weight_pct": current_weight_pct, "_llm_error": True, "error": str(exc)},
                "raw_decision": str(exc),
            }

        parsed, raw = safe_json_extract(decision_text)
        decision = {
            "action": "HOLD",
            "weight_pct": current_weight_pct,
            "reasoning": "Fallback: invalid JSON from CIO.",
        }
        if isinstance(parsed, dict):
            action = str(parsed.get("action", "")).upper()
            weight = float(parsed.get("weight_pct", 0.0) or 0.0)
            if action in {"BUY", "BUY_MORE"} and weight <= current_weight_pct + strategy.weight_increment_buffer_pct:
                action = "HOLD"
            has_position = current_weight_pct > 0.0 or str(ticker).upper() in {
                str(name).upper() for name in (portfolio_snapshot.get("positions") or {}).keys()
            }
            if action == "SELL" and not has_position:
                action = "IGNORE"
            # HOLD bug fix: if no position exists, HOLD should be IGNORE
            if action == "HOLD" and current_weight_pct == 0.0:
                action = "IGNORE"
            if action in {"BUY", "BUY_MORE", "HOLD", "SELL", "IGNORE"}:
                decision = {
                    "action": action,
                    "weight_pct": weight,
                    "reasoning": str(parsed.get("reasoning", "")) or "",
                }
        decision["final_score"] = final_score
        decision["verdict"] = debate_res.get("verdict")
        decision["net_score"] = debate_res.get("net_score")
        return {
            "transcript": transcript,
            "decision": decision,
            "raw_decision": raw,
        }
