from __future__ import annotations

import math
from typing import Dict

from config import workflow_weights, strategy
from vnstock.agents.prompting import BACKTEST_CONTEXT
from vnstock.core.llm import LLMError, call_llm
from vnstock.tools.quant_tool import QuantToolkit
from vnstock.workflows.base import AgentOutput
from vnstock.workflows.debate.autogen_debate import run_autogen_debate
from vnstock.workflows.utils import safe_json_extract


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _probability_from_alpha(alpha_score: float, hist_win_rate: float | None = None) -> float:
    """Blend alpha-based sigmoid with historical win rate for a balanced estimate.

    Vietnamese stocks typically have alpha scores 10-50 and daily win rates ~50-55%.
    The sigmoid maps alpha into a directional conviction signal,
    while historical win rate provides a data-grounded base rate.
    """
    # Sigmoid with center=20, scale=25 — more aggressive, makes alpha=15 → 0.42, alpha=50 → 0.78
    centered = (alpha_score - 20.0) / 25.0
    alpha_p = 1.0 / (1.0 + math.exp(-centered))

    if hist_win_rate is not None and 0.0 < hist_win_rate < 1.0:
        # Blend: 30% alpha signal + 70% historical data (trust the data more)
        blended = 0.3 * alpha_p + 0.7 * hist_win_rate
    else:
        blended = alpha_p

    return _clamp(blended, 0.05, 0.95)


def _historical_odds_from_prices(df_price: object) -> tuple[float, float, dict[str, float]]:
    """Return (b_data, hist_win_rate, diagnostics) from historical price data."""
    if df_price is None or len(df_price) < 2:
        return 1.0, 0.5, {
            "avg_upside_return": 0.0,
            "avg_downside_return": 0.0,
            "positive_return_days": 0.0,
            "negative_return_days": 0.0,
            "hist_win_rate": 0.5,
        }

    returns = df_price["close"].astype(float).pct_change().dropna()
    positive_returns = returns[returns > 0.0]
    negative_returns = returns[returns < 0.0].abs()

    avg_upside = float(positive_returns.mean()) if not positive_returns.empty else 0.0
    avg_downside = float(negative_returns.mean()) if not negative_returns.empty else 0.0
    if avg_upside <= 0.0 or avg_downside <= 0.0:
        b_data = 1.0
    else:
        b_data = max(avg_upside / avg_downside, 0.1)

    total_days = len(positive_returns) + len(negative_returns)
    hist_win_rate = float(len(positive_returns)) / total_days if total_days > 0 else 0.5

    return b_data, hist_win_rate, {
        "avg_upside_return": round(avg_upside, 6),
        "avg_downside_return": round(avg_downside, 6),
        "positive_return_days": float(len(positive_returns)),
        "negative_return_days": float(len(negative_returns)),
        "hist_win_rate": round(hist_win_rate, 4),
    }


class KellyCriterionWorkflow:
    """Probability-focused debate and Kelly sizing."""

    def __init__(self, model: str | None = None) -> None:
        from config import models

        self.model = model or models.t4_cio_model

    def _compute_data_driven_kelly_inputs(
        self,
        *,
        ticker: str,
        ref_date: str,
    ) -> tuple[float, float, dict[str, float]]:
        toolkit = QuantToolkit()
        try:
            alpha_result = toolkit.calculate_alpha_score(ticker, ref_date)
            df_price = toolkit.repo.get_price_history(
                ticker,
                end_date=alpha_result.ref_date,
                days=120,
            )
        finally:
            toolkit.close()
        b_data, hist_win_rate, odds_diagnostics = _historical_odds_from_prices(df_price)
        p_data = _probability_from_alpha(alpha_result.alpha_score, hist_win_rate=hist_win_rate)
        kelly_f = p_data - (1.0 - p_data) / b_data if b_data > 0.0 else 0.0
        kelly_70_pct = max(0.0, kelly_f * 0.7 * 100.0)
        diagnostics = {
            "alpha_score": round(alpha_result.alpha_score, 4),
            "kelly_fraction": round(kelly_f, 6),
            "kelly_70_pct": round(kelly_70_pct, 4),
            **odds_diagnostics,
        }
        return p_data, b_data, diagnostics

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
        p_data, b_data, kelly_inputs = self._compute_data_driven_kelly_inputs(
            ticker=ticker,
            ref_date=ref_date,
        )

        cio_system = (
            f"{BACKTEST_CONTEXT} "
            "Bạn là CIO của quỹ đầu tư multi-agent sử dụng Kelly Criterion. Suy luận từng bước bằng tiếng Việt:\n"
            "1) MULTI-AGENT ANALYSIS: Phân tích consensus vs conflict giữa 5 chuyên gia (Macro, News, Technical, Quant, Financial).\n"
            "   - Xác định điểm đồng thuận (consensus): Các agent nào cùng quan điểm? Bằng chứng nào trùng lặp?\n"
            "   - Xác định điểm xung đột (conflict): Agent nào bất đồng? Lý do gốc rễ của disagreement?\n"
            "2) CROSS-AGENT RATIONALE: Tổng hợp reasoning xuyên suốt các agent.\n"
            "   - Bull case: Tổng hợp luận điểm tích cực từ tất cả agents (không chỉ Bull trong debate).\n"
            "   - Bear case: Tổng hợp luận điểm tiêu cực từ tất cả agents (không chỉ Bear trong debate).\n"
            "   - Evidence quality: Đánh giá độ tin cậy của bằng chứng (hard data vs speculation).\n"
            "3) KELLY CRITERION VALIDATION: Rà soát Kelly inputs đã được cung cấp.\n"
            "   - Tuân thủ đúng các đầu vào Kelly lấy từ dữ liệu (p_data, b_data), không được tự bịa số mới.\n"
            "   - Kelly f = P - (1-P)/B như tín hiệu định cỡ vị thế.\n"
            "4) PORTFOLIO CONTEXT: Kiểm tra portfolio_snapshot (cash, qty, avg_price, available_qty).\n"
            "   - Nếu đã có vị thế: Cân nhắc BUY_MORE vs SELL vs HOLD dựa trên P&L hiện tại.\n"
            "   - Nếu chưa có vị thế: Đánh giá độ mạnh điểm vào (conviction level).\n"
            "5) FINAL DECISION: Xuất action kèm reasoning chi tiết. Chỉ trả JSON hợp lệ theo schema."
        )
        cio_user = (
            "Bạn là quỹ đầu tư chiến lược, KHÔNG phải day-trader.\n"
            "Hành động hợp lệ: BUY (mới), BUY_MORE (đã có vị thế), HOLD, SELL (chỉ khi có vị thế), IGNORE.\n"
            "Không được short. Nếu không có vị thế mà SELL => INVALID.\n"
            "KHÔNG suy luận P/B mới. Phải dùng đúng dữ liệu đã cung cấp: inferred_p = p_data, inferred_b = b_data.\n"
            "Dùng Kelly f=P-(1-P)/B như tín hiệu định cỡ vị thế; CIO chỉ validate/finalize action + reasoning.\n"
            "Nếu BUY/BUY_MORE, weight_pct phải > vị thế hiện tại; nếu không, HOLD.\n\n"
            "=== TAKE-PROFIT RULES (ƯU TIÊN CAO) ===\n"
            f"P&L hiện tại: {portfolio_snapshot.get('unrealized_pnl_pct', 0):.2f}%\n"
            "- Nếu P&L > +15% VÀ (verdict bearish HOẶC final_score < 0) → SELL để chốt lời\n"
            "- Nếu P&L > +20% → SELL toàn bộ bất kể verdict\n"
            "- Nếu P&L < -5% VÀ verdict bearish → SELL để cắt lỗ sớm\n"
            "- Nếu P&L trong khoảng -5% đến +15% → Theo Kelly signal và debate\n\n"
            "REASONING STRUCTURE (bắt buộc):\n"
            "  - Consensus: [Điểm đồng thuận giữa agents]\n"
            "  - Conflict: [Điểm xung đột và cách giải quyết]\n"
            "  - Evidence: [Bằng chứng chính hỗ trợ quyết định]\n"
            "  - Kelly Signal: [Phân tích Kelly f và ý nghĩa]\n"
            "  - P&L Check: [Kiểm tra take-profit/stop-loss]\n"
            "  - Decision: [Quyết định cuối cùng và lý do]\n"
            f"Schema: {{\"action\": \"BUY\"|\"BUY_MORE\"|\"HOLD\"|\"SELL\"|\"IGNORE\", \"weight_pct\": float, \"inferred_p\": float, \"inferred_b\": float, \"reasoning\": <string>}}.\n"
            f"Data-driven Kelly inputs: p_data={p_data:.6f}, b_data={b_data:.6f}, diagnostics={kelly_inputs}.\n"
            f"Vị thế hiện tại: {current_weight_pct:.2f}% NAV. Portfolio snapshot: {portfolio_snapshot}. Final_score={final_score:.3f}."
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
            "inferred_p": round(p_data, 6),
            "inferred_b": round(b_data, 6),
            "reasoning": "Fallback: invalid JSON from CIO.",
        }
        if isinstance(parsed, dict):
            action = str(parsed.get("action", "")).upper()
            p = p_data
            b = b_data
            weight = float(parsed.get("weight_pct", 0.0) or 0.0)
            if b <= 0:
                action = "HOLD"
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
                # 0.7-Kelly clamp: more aggressive than half-Kelly
                if b > 0 and 0 < p < 1:
                    kelly_f = p - (1.0 - p) / b
                    kelly_70_pct = max(0.0, kelly_f * 0.7 * 100.0)
                    weight = min(weight, kelly_70_pct, workflow_weights.kelly_max_weight_pct)
                elif action in {"BUY", "BUY_MORE"}:
                    action = "HOLD"
                decision = {
                    "action": action,
                    "weight_pct": weight,
                    "inferred_p": round(_clamp(p, 0.0, 1.0), 6),
                    "inferred_b": round(b, 6),
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
