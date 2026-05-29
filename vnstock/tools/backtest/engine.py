from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from vnstock.agents.prompting import Action, normalize_action
from vnstock.core.llm import call_llm
from vnstock.core.timing import Timer
from vnstock.tools.backtest.benchmark import BenchmarkAnalyzer
from vnstock.workflows.base import AgentOutput, SharedAgentPool
from vnstock.workflows.traditional_scoring import TraditionalScoringWorkflow
from vnstock.workflows.kelly_criterion import KellyCriterionWorkflow
from vnstock.workflows.markowitz_frontier import MarkowitzFrontierWorkflow
from config import paths, strategy, models, trading
from vnstock.tools.backtest.portfolio import (
    Portfolio,
    START_CAPITAL,
    StrategyParams,
    _ensure_dir,
    LOT_SIZE,
    BUY_FEE_RATE,
    SELL_FEE_RATE,
)
from vnstock.tools.backtest.trading_calendar import is_trading_day, next_trading_day
from vnstock.engine.risk_engine import RiskEngine, RiskLimits
from cognitive_trading.governance.schemas import (
    ARTIFACT_VERSION,
    NormalizedAgentArtifact,
    WorkflowArtifactEnvelope,
    WorkflowTickerArtifact,
)

BACKTEST_ROOT = paths.backtest_results_dir
_BACKTEST_ROOT_READY = False
WEIGHT_INCREMENT_BUFFER_PCT = strategy.weight_increment_buffer_pct
TAKE_PROFIT_TRIM_TRIGGER_PCT = 8.0
TAKE_PROFIT_TRIM_FRACTION = 0.25
_REENTRY_EXIT_ACTIONS = {Action.SELL.value, Action.TRIMMING.value}


def _prepare_backtest_root() -> Path:
    global BACKTEST_ROOT, _BACKTEST_ROOT_READY
    if _BACKTEST_ROOT_READY:
        return BACKTEST_ROOT

    candidate = BACKTEST_ROOT
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe_path = candidate / ".write_probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
    except PermissionError:
        candidate = Path("/tmp") / f"vnstock-backtest-{os.getpid()}"
        candidate.mkdir(parents=True, exist_ok=True)
        BACKTEST_ROOT = candidate
        print(f"[backtest] Đã tự chuyển output VNStock sang đường dẫn ghi được: {candidate}")

    _BACKTEST_ROOT_READY = True
    return BACKTEST_ROOT

WORKFLOW_ALIASES = {
    "traditional": "Traditional",
    "trad": "Traditional",
    "kelly": "Kelly",
    "markowitz": "Markowitz",
}

DEFAULT_WORKFLOWS = ["Traditional", "Kelly", "Markowitz"]


def select_workflows(raw: str | None) -> List[str]:
    if raw is None:
        return list(DEFAULT_WORKFLOWS)
    selected: List[str] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        key = name.lower()
        resolved = WORKFLOW_ALIASES.get(key) or name.title()
        if resolved in DEFAULT_WORKFLOWS:
            selected.append(resolved)
        else:
            print(f"[backtest.select_workflows] Unknown workflow '{name}', skipping.")
    return selected


class WorkflowResultArena:
    def __init__(self, name: str, portfolio: Portfolio, params: StrategyParams):
        self.name = name
        self.portfolio = portfolio
        self.params = params
        self.strategist_log: List[str] = []
        self.daily_trade_ledger: List[dict] = []
        self.benchmark_metrics: Dict[str, Dict[str, float | int | str]] = {}
        self.equity_curve_points: List[Dict[str, float | str]] = []
        self.timing_by_date: Dict[str, Dict[str, Dict[str, float | int]]] = {}

    def metrics(self, final_prices: Dict[str, float]) -> Dict[str, float | int]:
        equity_curve = [float(value) for value in self.portfolio.equity_history if float(value) > 0.0]
        final_equity = (
            self.portfolio.equity(final_prices)
            if final_prices
            else (equity_curve[-1] if equity_curve else START_CAPITAL)
        )
        ret_pct = (final_equity - START_CAPITAL) / START_CAPITAL * 100.0
        daily_rets: List[float] = []
        for previous, current in zip(equity_curve, equity_curve[1:]):
            if previous > 0:
                daily_rets.append((current - previous) / previous)

        mean_ret = sum(daily_rets) / len(daily_rets) if daily_rets else 0.0
        variance = (
            sum((ret - mean_ret) ** 2 for ret in daily_rets) / (len(daily_rets) - 1)
            if len(daily_rets) > 1
            else 0.0
        )
        std = math.sqrt(variance) if variance > 0.0 else 0.0
        sharpe = (mean_ret / std) * math.sqrt(252.0) if std > 1e-9 else 0.0

        downside_variance = (
            sum(min(ret, 0.0) ** 2 for ret in daily_rets) / len(daily_rets)
            if daily_rets
            else 0.0
        )
        downside_std = math.sqrt(downside_variance) if downside_variance > 0.0 else 0.0
        sortino = (mean_ret / downside_std) * math.sqrt(252.0) if downside_std > 1e-9 else 0.0

        peak_equity = equity_curve[0] if equity_curve else START_CAPITAL
        max_drawdown = 0.0
        for equity in equity_curve:
            peak_equity = max(peak_equity, equity)
            if peak_equity > 0.0:
                max_drawdown = min(max_drawdown, (equity - peak_equity) / peak_equity)

        periods = len(daily_rets)
        annualized_return = (
            (final_equity / START_CAPITAL) ** (252.0 / periods) - 1.0
            if periods > 0 and final_equity > 0.0
            else 0.0
        )
        calmar = annualized_return / abs(max_drawdown) if max_drawdown < -1e-9 else 0.0

        if daily_rets:
            returns_series = pd.Series(daily_rets, dtype="float64")
            var_95 = float(returns_series.quantile(0.05))
            tail_losses = returns_series[returns_series <= var_95]
            cvar_95 = float(tail_losses.mean()) if not tail_losses.empty else var_95
            daily_win_rate = float((returns_series > 0).mean() * 100.0)
        else:
            var_95 = 0.0
            cvar_95 = 0.0
            daily_win_rate = 0.0

        gross_profit = sum(ret for ret in daily_rets if ret > 0.0)
        gross_loss = abs(sum(ret for ret in daily_rets if ret < 0.0))
        if gross_loss > 1e-9:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 1e-9:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        total_pnl = final_equity - START_CAPITAL
        # Win rate based on closed trades (sells) only, not total trades (buys+sells)
        closed_trades = self.portfolio.sells
        trade_win_rate = (
            (self.portfolio.wins / closed_trades * 100.0) if closed_trades > 0 else 0.0
        )
        return {
            "account_value": final_equity,
            "return_pct": ret_pct,
            "annualized_return_pct": annualized_return * 100.0,
            "total_pnl": total_pnl,
            "win_rate": trade_win_rate,
            "daily_win_rate": daily_win_rate,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "trades": self.portfolio.trades,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown * 100.0,
            "var_95": var_95,
            "var_95_pct": var_95 * 100.0,
            "cvar_95": cvar_95,
            "cvar_95_pct": cvar_95 * 100.0,
            "profit_factor": profit_factor,
        }


def _write_json(path: Path, data: Dict[str, object]) -> None:
    import json

    _ensure_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    _ensure_dir(path)
    path.write_text(text, encoding="utf-8")


def _legacy_agent_artifact(
    *,
    workflow: str,
    ticker: str,
    ref_date: str,
    agent_name: str,
    raw_analysis: str,
    confidence: float,
    evidence: List[str],
    key_data_points: Dict[str, Any],
) -> dict[str, Any]:
    artifact = NormalizedAgentArtifact(
        workflow=workflow.lower(),
        artifact_origin="adapted",
        analysis_depth="sparse",
        ticker=ticker,
        ref_date=ref_date,
        agent_name=agent_name,
        action=None,
        confidence_raw=max(0.0, min(float(confidence or 0.0) * 100.0, 100.0)),
        confidence_calibrated=None,
        upside_pct=None,
        downside_pct=None,
        reasoning_summary=str(raw_analysis or ""),
        key_considerations=list(evidence or []),
        evidence_ids=list(evidence or []),
        analysis_steps=[],
        source_agents=[agent_name],
        metadata={
            "adapted_from": "AgentOutput",
            "key_data_points": dict(key_data_points or {}),
        },
    )
    return artifact.model_dump(mode="json")


def _persist_normalized_legacy_workflow_artifact(
    *,
    workflow: str,
    date_str: str,
    ticker: str,
    ref_date: str,
    agent_outputs: Dict[str, AgentOutput],
    decision: Dict[str, Any],
    debate_transcript: str | None,
    ledger_entry: Dict[str, Any] | None,
    portfolio_snapshot: Dict[str, Any] | None,
) -> None:
    normalized_dir = BACKTEST_ROOT / date_str / ticker / workflow.lower() / "normalized"
    analysis_cards = [
        _legacy_agent_artifact(
            workflow=workflow,
            ticker=ticker,
            ref_date=ref_date,
            agent_name=agent_name,
            raw_analysis=agent_output.raw_analysis,
            confidence=agent_output.confidence,
            evidence=agent_output.evidence,
            key_data_points=agent_output.key_data_points,
        )
        for agent_name, agent_output in sorted(agent_outputs.items())
    ]
    ticker_artifact = WorkflowTickerArtifact(
        workflow=workflow.lower(),
        artifact_origin="adapted",
        analysis_depth="sparse",
        ticker=ticker,
        ref_date=ref_date,
        planner=None,
        cards=[NormalizedAgentArtifact.model_validate(card) for card in analysis_cards],
        debate={
            "triggered": bool(debate_transcript),
            "transcript": debate_transcript,
        } if debate_transcript else None,
        cio_intent=dict(decision or {}),
        risk={
            "portfolio_snapshot": dict(portfolio_snapshot or {}),
            "legacy_surface": True,
        },
        trade=dict(ledger_entry or {}) if isinstance(ledger_entry, dict) else None,
        metadata={
            "legacy_workflow": workflow,
            "adaptation_note": "Legacy workflows expose adapted sparse agent artifacts; native intermediate depth is unavailable.",
        },
    )
    envelope = WorkflowArtifactEnvelope(
        workflow=workflow.lower(),
        artifact_origin="adapted",
        analysis_depth="sparse",
        as_of_date=date_str,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        locale="vi-VN",
        summary={
            "date": date_str,
            "ticker": ticker,
            "workflow": workflow,
            "legacy_surface": True,
        },
        portfolio_state=dict(portfolio_snapshot or {}),
        ledger=[dict(ledger_entry)] if isinstance(ledger_entry, dict) else [],
        analysis={ticker: ticker_artifact},
        risk_report={"legacy_surface": True},
        calibration=[],
        equity_curve=[],
        metadata={
            "schema_version": ARTIFACT_VERSION,
            "adaptation_note": "Legacy workflow artifact adapted into normalized envelope without fabricating unavailable sub-agent depth.",
        },
    )
    _write_json(normalized_dir / "workflow_artifact.json", envelope.model_dump(mode="json"))


def _quarterly_return_pct(equity_curve_points: List[Dict[str, float | str]]) -> float:
    if len(equity_curve_points) < 2:
        return 0.0
    start_equity = float(equity_curve_points[0].get("equity", START_CAPITAL) or START_CAPITAL)
    end_equity = float(equity_curve_points[-1].get("equity", start_equity) or start_equity)
    if start_equity <= 0:
        return 0.0
    return ((end_equity - start_equity) / start_equity) * 100.0


def _trade_quality_metrics(ledger_root: Path, workflow: str) -> Dict[str, float | int]:
    ledger_files = sorted((ledger_root / "ledgers").glob(f"*/{workflow}.json"))
    realized_returns_pct: List[float] = []
    realized_pnl_vnd: List[float] = []
    for ledger_file in ledger_files:
        try:
            entries = json.loads(ledger_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            realized_pnl = entry.get("realized_pnl")
            if realized_pnl is None:
                continue
            basis = float(entry.get("cost_basis") or 0.0)
            pnl_value = float(realized_pnl)
            realized_pnl_vnd.append(pnl_value)
            if basis > 0:
                realized_returns_pct.append((pnl_value / basis) * 100.0)

    wins = [value for value in realized_pnl_vnd if value > 0.0]
    losses = [value for value in realized_pnl_vnd if value < 0.0]
    closed_trades = len(realized_pnl_vnd)
    avg_profit_pct = (
        sum(value for value in realized_returns_pct if value > 0.0) / len([value for value in realized_returns_pct if value > 0.0])
        if any(value > 0.0 for value in realized_returns_pct)
        else 0.0
    )
    avg_loss_pct = (
        sum(value for value in realized_returns_pct if value < 0.0) / len([value for value in realized_returns_pct if value < 0.0])
        if any(value < 0.0 for value in realized_returns_pct)
        else 0.0
    )
    reward_risk_ratio = abs(avg_profit_pct / avg_loss_pct) if avg_loss_pct < 0.0 else 0.0
    return {
        "closed_trades": closed_trades,
        "winning_closed_trades": len(wins),
        "losing_closed_trades": len(losses),
        "avg_profit_pct": round(avg_profit_pct, 4),
        "avg_loss_pct": round(avg_loss_pct, 4),
        "reward_risk_ratio": round(reward_risk_ratio, 4),
        "avg_realized_pnl_vnd": round(sum(realized_pnl_vnd) / closed_trades, 4) if closed_trades else 0.0,
    }


def _normalize_markdown_report(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _persist_ledger_placeholder(workflow: str, date_str: str, ledger: List[dict]) -> None:
    # Ledger persistence hook; writes sorted, JSON-serializable daily trade ledger to disk.
    ledger_path = BACKTEST_ROOT / "ledgers" / date_str / f"{workflow}.json"

    def _make_serializable(entry: Dict[str, Any]) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for k, v in entry.items():
            if k == "cio_reasoning":
                # Trim to a JSON-safe projection; drop non-serializable fields.
                if isinstance(v, dict):
                    safe[k] = {kk: vv for kk, vv in v.items() if isinstance(vv, (str, int, float, bool, list, dict, type(None)))}
                else:
                    safe[k] = v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else str(v)
            else:
                if isinstance(v, (str, int, float, bool)):
                    safe[k] = v
                elif isinstance(v, list):
                    safe[k] = v
                elif isinstance(v, dict):
                    safe[k] = {kk: vv for kk, vv in v.items() if isinstance(vv, (str, int, float, bool, list, dict, type(None)))}
                elif v is None:
                    safe[k] = None
                else:
                    safe[k] = str(v)
        return safe

    sorted_ledger = sorted(ledger, key=lambda e: (str(e.get("ticker", "")), str(e.get("action", ""))))
    safe_ledger = [_make_serializable(entry) for entry in sorted_ledger]
    _write_json(ledger_path, safe_ledger)


TRUNCATE_TRANSCRIPT_CHARS = 400
LEGACY_REPORT_TIMEOUT_SECONDS = 300


WORKFLOW_REPORT_GUIDANCE = {
    "Traditional": {
        "title": "Báo cáo Traditional",
        "system_style": (
            "Giữ format chung với các workflow khác, nhưng viết như trưởng bộ phận đầu tư theo trường phái discretionary, "
            "chỉ bám chặt vào executed trades, state và normalized artifact; không suy diễn vượt quá những gì dữ liệu thực sự xác nhận."
        ),
    },
    "Kelly": {
        "title": "Báo cáo Kelly",
        "system_style": (
            "Giữ format chung với các workflow khác, nhưng viết theo phong cách Kelly: nhấn vào xác suất thắng, edge, payoff và sizing. "
            "Khi nói về tiền phải tuyệt đối dùng đúng đơn vị thực tế từ dữ liệu và không được suy diễn triệu thành tỷ."
        ),
    },
    "Markowitz": {
        "title": "Báo cáo Markowitz",
        "system_style": (
            "Giữ format chung với các workflow khác, nhưng viết như CIO phân bổ tài sản, nhấn vào tối ưu hóa danh mục, diversification và rebalance. "
            "Nếu dữ liệu ledger hoặc report context không đủ sạch để diễn giải chắc chắn, phải nói rõ giới hạn thay vì kể quá đà."
        ),
    },
}

COMMON_REPORT_SECTIONS = [
    "## Bối cảnh thị trường",
    "## Tín hiệu nổi bật",
    "## Quyết định giao dịch",
    "## Tranh luận và bất đồng",
    "## Rủi ro và kế hoạch tiếp theo",
]


def _truncate_text(text: Optional[str], max_len: int = TRUNCATE_TRANSCRIPT_CHARS) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "…"


def _legacy_report_config(workflow: str) -> Dict[str, object]:
    return WORKFLOW_REPORT_GUIDANCE.get(workflow, WORKFLOW_REPORT_GUIDANCE["Traditional"])


def _legacy_analysis_rows(normalized_envelope: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not isinstance(normalized_envelope, dict):
        return []
    analysis = normalized_envelope.get("analysis")
    if not isinstance(analysis, dict):
        return []

    rows: List[Dict[str, Any]] = []
    for ticker, payload in sorted(analysis.items()):
        if not isinstance(payload, dict):
            continue
        cio = payload.get("cio_intent") if isinstance(payload.get("cio_intent"), dict) else {}
        debate = payload.get("debate") if isinstance(payload.get("debate"), dict) else {}
        rows.append(
            {
                "ticker": ticker,
                "action": cio.get("action"),
                "weight_pct": cio.get("weight_pct"),
                "reasoning": cio.get("reasoning"),
                "verdict": cio.get("verdict"),
                "net_score": cio.get("net_score"),
                "debate": debate,
                "optimizer": cio.get("optimizer") if isinstance(cio.get("optimizer"), dict) else {},
                "basket": cio.get("basket") if isinstance(cio.get("basket"), list) else [],
                "raw": payload,
            }
        )
    return rows


async def _generate_daily_report(
    workflow: str,
    date_str: str,
    ledger: List[dict],
    normalized_envelope: Dict[str, Any] | None = None,
) -> str:
    required_directive = (
        "ROLE: BẠN LÀ TỔNG BIÊN TẬP TẠP CHÍ TÀI CHÍNH. YÊU CẦU BẮT BUỘC: TOÀN BỘ BÁO CÁO PHẢI THUẦN TIẾNG VIỆT CHUYÊN NGÀNH TÀI CHÍNH. "
        "TUYỆT ĐỐI KHÔNG DÙNG TIẾNG ANH ĐỂ TÓM TẮT JSON DỮ LIỆU CỦA HỆ THỐNG."
    )
    report_cfg = _legacy_report_config(workflow)
    system_prompt = required_directive + f" {report_cfg['system_style']}"

    allowed_actions = {a.value for a in Action}
    normalized_ledger = []
    for entry in ledger:
        norm_action = normalize_action(entry.get("action"))
        if norm_action is None:
            continue
        if norm_action.value not in allowed_actions:
            continue
        normalized_ledger.append({**entry, "action": norm_action.value})

    analysis_rows = _legacy_analysis_rows(normalized_envelope)
    if not normalized_ledger and not analysis_rows:
        return (
            f"# {report_cfg['title']} ngày {date_str}\n"
            f"{COMMON_REPORT_SECTIONS[0]}\n"
            "- Không có biến động hay bối cảnh nổi bật cần nhấn mạnh trong ngày.\n\n"
            f"{COMMON_REPORT_SECTIONS[1]}\n"
            "- Không có tín hiệu đủ mạnh để hành động.\n\n"
            f"{COMMON_REPORT_SECTIONS[2]}\n"
            "- Không có giao dịch được thực hiện trong ngày.\n\n"
            f"{COMMON_REPORT_SECTIONS[3]}\n"
            "- Không có tranh luận hoặc bất đồng đáng kể được ghi nhận.\n\n"
            f"{COMMON_REPORT_SECTIONS[4]}\n"
            "- Tiếp tục duy trì quan sát và chờ dữ liệu rõ ràng hơn ở phiên sau."
        )

    def _safe_json(obj: object) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)

    def _gross_value(entry: Dict[str, Any]) -> float:
        invest = float(entry.get("invest_amount") or 0.0)
        sold = float(entry.get("sold_amount") or 0.0)
        return max(abs(invest), abs(sold))

    def _extract_reason(decision: object) -> str:
        if isinstance(decision, dict):
            if isinstance(decision.get("_thought_process"), list) and decision["_thought_process"]:
                return str(decision["_thought_process"][0])
            if isinstance(decision.get("cio_reasoning"), str):
                return str(decision["cio_reasoning"])
            if isinstance(decision.get("reasoning"), str):
                return str(decision["reasoning"])
        return str(decision) if decision is not None else ""

    sorted_trades = sorted(normalized_ledger, key=_gross_value, reverse=True)
    top_trades = []
    for entry in sorted_trades[:5]:
        reason_text = _extract_reason(entry.get("cio_reasoning"))
        reason_text = _truncate_text(reason_text, 240)
        price = entry.get("price")
        sold_amount = entry.get("sold_amount")
        invest_amount = entry.get("invest_amount")
        top_trades.append(
            {
                "ticker": entry.get("ticker"),
                "action": entry.get("action"),
                "price": round(float(price), 2) if price is not None else None,
                "quantity": entry.get("quantity"),
                "invest_amount": round(float(invest_amount), 2) if invest_amount is not None else None,
                "sold_amount": round(float(sold_amount), 2) if sold_amount is not None else None,
                "gross_value": round(_gross_value(entry), 2),
                "reason_hint": reason_text,
                "verdict": entry.get("verdict"),
                "net_score": entry.get("net_score"),
            }
        )

    debate_clips = []
    for entry in normalized_ledger:
        clip = _truncate_text(entry.get("debate_transcript"))
        if not clip:
            continue
        debate_clips.append({
            "ticker": entry.get("ticker"),
            "action": entry.get("action"),
            "clip": clip,
        })

    user_prompt = (
        "Hãy viết báo cáo daily backtest bằng tiếng Việt chuẩn tài chính, dùng cùng một format chung với các workflow khác và không thêm mục ngoài yêu cầu:\n"
        f"# {report_cfg['title']} ngày {date_str}\n"
        + "\n".join(COMMON_REPORT_SECTIONS)
        + "\n"
        "Yêu cầu bổ sung:\n"
        "- Traditional phải nhấn vào scoring, chất lượng tín hiệu và quyết định vào/không vào lệnh.\n"
        "- Kelly phải nhấn vào xác suất, payoff, edge và sizing theo Kelly.\n"
        "- Markowitz phải nhấn vào tối ưu hóa danh mục, diversification, Sharpe/volatility và rebalance.\n"
        "- Nếu không có giao dịch, vẫn phải giải thích rõ vì sao workflow giữ nguyên trạng thái.\n"
        "- Chỉ sử dụng các action trong enum {" + ", ".join(sorted(allowed_actions)) + "}. Không phát minh action mới.\n"
        "- Không tóm tắt bằng tiếng Anh.\n"
        "- Khi nói về khối lượng, phải hiểu `quantity` trong ledger legacy là số lô; cần đổi sang số cổ phiếu bằng quantity * 100 khi diễn giải cho người đọc.\n"
        "- Khi nói về số tiền, phải giữ đúng đơn vị thực tế từ dữ liệu JSON; không được tự đổi triệu thành tỷ hoặc ngược lại.\n"
        "- Không được kể thêm quyết định / hành động / tranh luận nếu ledger, state, normalized artifact chưa xác nhận rõ.\n"
        "- Nếu report không đủ dữ liệu sạch để diễn giải chắc chắn, phải nói thẳng là dữ liệu chưa đủ rõ thay vì khẳng định quá mức.\n"
        "Sử dụng dữ liệu JSON sau:\n"
        "DATA:\n"
        f"{_safe_json({
            'workflow': workflow,
            'date': date_str,
            'executed_trades_sorted': top_trades,
            'debate_clips': debate_clips,
            'analysis_rows': analysis_rows,
            'normalized_artifact': normalized_envelope or {},
            'fallbacks': {
                'no_trades': 'Không có giao dịch được thực hiện trong ngày.',
                'no_debate': 'Không có tranh luận được ghi nhận trong ngày.',
                'no_risk': 'Chưa có khuyến nghị mới cho danh mục.',
            },
            'limits': {
                'max_summary_bullets': 3,
                'max_trades': 5,
                'max_debate_bullets': 3,
                'max_risk_bullets': 2,
                'transcript_truncate_chars': TRUNCATE_TRANSCRIPT_CHARS,
            },
        })}"
    )

    response = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=models.daily_report_model,
        temperature=0.3,
    )
    return _normalize_markdown_report(response)


def _safe_json_dump(obj: object) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


async def _run_daily_report(
    workflow: str,
    date_str: str,
    ledger: List[dict],
    normalized_envelope: Dict[str, Any] | None = None,
) -> None:
    report_path = BACKTEST_ROOT / "blog_posts" / f"{date_str}_{workflow}_Daily_Report.md"
    if report_path.exists():
        return
    try:
        body = await asyncio.wait_for(
            _generate_daily_report(workflow, date_str, ledger, normalized_envelope),
            timeout=LEGACY_REPORT_TIMEOUT_SECONDS,
        )
        content = body if body.startswith("# ") else f"# Báo cáo ngày {workflow} ({date_str})\n\n{body}"
        if not body or not str(body).strip():
            content = (
                f"# Báo cáo ngày {workflow} ({date_str})\n\n"
                f"Không nhận được nội dung báo cáo. Ngữ cảnh ledger:\n```\n{_safe_json_dump(ledger)}\n```"
            )
    except Exception as exc:
        content = (
            f"# Báo cáo ngày {workflow} ({date_str})\n\n"
            f"Quá trình tạo báo cáo bị lỗi hoặc timeout: {exc}\n\n"
            f"Ngữ cảnh ledger:\n```\n{_safe_json_dump(ledger)}\n```"
        )
    _write_text(report_path, content)


def _clear_ledger_placeholder(workflow: str) -> None:
    # Ledger clearing hook; no-op placeholder to keep canonical ordering.
    return


VN30_TICKERS = [
    "ACB",
    "BCM",
    "BID",
    "CTG",
    "DGC",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "LPB",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
]


def get_latest_financial_quarter(ref_date: datetime) -> Tuple[int, int]:
    month = ref_date.month
    year = ref_date.year
    if month <= 3:
        return year - 1, 4
    if month <= 6:
        return year, 1
    if month <= 9:
        return year, 2
    return year, 3


def load_fundamental_score(ticker: str, ref_date: datetime) -> float:
    # Deprecated legacy scoring retained for compatibility; not used in V6.0.
    return 0.5


def load_market_data(start: str, end: str, tickers: Optional[List[str]] = None) -> Dict[str, pd.DataFrame]:
    from vnstock.database.repo import DataRepository

    repo = DataRepository()
    data: Dict[str, pd.DataFrame] = {}
    tickers = tickers or VN30_TICKERS
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    try:
        for ticker in tickers:
            df = repo.get_price_history(
                ticker,
                start_date=start_ts,
                end_date=end_ts,
            )
            if df.empty:
                continue
            data[ticker] = df.sort_values("date").reset_index(drop=True)
    finally:
        repo.close()
    return data


def load_benchmark_data(start: str, end: str, benchmark_ticker: str = "VN30") -> pd.DataFrame:
    market_data = load_market_data(start, end, [benchmark_ticker])
    return market_data.get(benchmark_ticker, pd.DataFrame())


def _build_benchmark_curve(
    day_price_maps: List[Tuple[pd.Timestamp, Dict[str, float]]],
    benchmark_prices_by_date: Dict[pd.Timestamp, float],
) -> List[float]:
    curve: List[float] = []
    last_benchmark_price: float | None = None
    for date, _ in day_price_maps:
        if not is_trading_day(pd.to_datetime(date).strftime("%Y-%m-%d")):
            continue
        # Normalize both dates to ensure matching
        normalized_date = pd.to_datetime(date).normalize()
        benchmark_price = benchmark_prices_by_date.get(normalized_date)
        if benchmark_price and benchmark_price > 0.0:
            last_benchmark_price = float(benchmark_price)
        if last_benchmark_price is not None:
            curve.append(last_benchmark_price)
    return curve


def _has_position_for_ticker(portfolio_snapshot: Dict[str, object], ticker: str, current_weight_pct: float) -> bool:
    positions = portfolio_snapshot.get("positions") or {}
    if isinstance(positions, dict) and str(ticker).upper() in {str(name).upper() for name in positions.keys()}:
        return True
    return current_weight_pct > 0.0


def _next_trading_day(value: str) -> str:
    return next_trading_day(value)


def _seed_recent_exits(ledger_root: Path) -> Dict[str, Dict[str, str]]:
    seeded: Dict[str, Dict[str, str]] = {name: {} for name in DEFAULT_WORKFLOWS}
    if not ledger_root.exists():
        return seeded
    for workflow in DEFAULT_WORKFLOWS:
        for ledger_file in sorted((ledger_root / "ledgers").glob(f"*/{workflow}.json"), reverse=True):
            try:
                entries = json.loads(ledger_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(entries, list):
                continue
            for entry in reversed(entries):
                if not isinstance(entry, dict):
                    continue
                action = str(entry.get("action") or "").upper()
                ticker = str(entry.get("ticker") or "").upper()
                date_str = str(entry.get("date") or ledger_file.parent.name)
                if action in _REENTRY_EXIT_ACTIONS and ticker and ticker != "PORTFOLIO":
                    seeded[workflow].setdefault(ticker, date_str)
            if seeded[workflow]:
                break
    return seeded


def _is_reentry_blocked(
    recent_exits_by_workflow: Dict[str, Dict[str, str]],
    *,
    workflow: str,
    ticker: str,
    date_str: str,
) -> bool:
    exit_date = recent_exits_by_workflow.get(workflow, {}).get(str(ticker).upper())
    if not exit_date:
        return False
    return _next_trading_day(exit_date) == date_str


def _record_recent_exit(
    recent_exits_by_workflow: Dict[str, Dict[str, str]],
    *,
    workflow: str,
    ticker: str,
    action: str,
    date_str: str,
) -> None:
    if str(action).upper() not in _REENTRY_EXIT_ACTIONS:
        return
    if not ticker or str(ticker).upper() == "PORTFOLIO":
        return
    recent_exits_by_workflow.setdefault(workflow, {})[str(ticker).upper()] = date_str


def _maybe_take_profit_trim_decision(
    *,
    ticker: str,
    portfolio_snapshot: Dict[str, object],
    current_weight_pct: float,
    decision: Dict[str, object],
    allow_on_buy_intent: bool = False,
) -> Dict[str, object]:
    action = normalize_action(decision.get("action"))
    if action == Action.SELL:
        return decision
    if not allow_on_buy_intent and action in {Action.BUY, Action.BUY_MORE}:
        return decision
    if not _has_position_for_ticker(portfolio_snapshot, ticker, current_weight_pct):
        return decision
    unrealized_pnl_pct = float(portfolio_snapshot.get("unrealized_pnl_pct", 0.0) or 0.0)
    if unrealized_pnl_pct < TAKE_PROFIT_TRIM_TRIGGER_PCT:
        return decision
    return {
        **decision,
        "action": Action.TRIMMING.value,
        "percent": TAKE_PROFIT_TRIM_FRACTION,
        "reasoning": str(decision.get("reasoning", "")) or "Auto take-profit trim from engine overlay.",
        "_take_profit_trim": True,
        "trigger_pnl_pct": round(unrealized_pnl_pct, 2),
        "rule": f">= +{TAKE_PROFIT_TRIM_TRIGGER_PCT:.0f}% unrealized profit -> trim {int(TAKE_PROFIT_TRIM_FRACTION * 100)}%",
    }


def _apply_decision(
    portfolio: Portfolio,
    ticker: str,
    price_map: Dict[str, float],
    decision: Dict[str, object],
    current_weight_pct: float,
    ledger: List[dict],
    *,
    workflow: str,
    date_str: str,
    debate_transcript: str | None = None,
    verdict: object | None = None,
    net_score: object | None = None,
    risk_engine: RiskEngine | None = None,
    halt_buys: bool = False,
    recent_exits_by_workflow: Dict[str, Dict[str, str]] | None = None,
) -> None:
    if decision.get("_llm_error"):
        return
    action_raw = decision.get("action")
    action = normalize_action(action_raw)
    weight_pct = max(0.0, min(float(decision.get("weight_pct", 0.0) or 0.0), float(trading.max_trade_pct)))
    price = price_map.get(ticker)
    if action is None:
        print(f"[backtest._apply_decision] Unknown action '{action_raw}' for {ticker}; skipping.")
        return
    if price is None or price <= 0:
        return
    if halt_buys and action in {Action.BUY, Action.BUY_MORE}:
        return
    equity_before = portfolio.equity(price_map)

    def _append_buy_entry(qty: float, invest_amount: float) -> None:
        ledger.append(
            {
                "ticker": ticker,
                "action": action.value,
                "price": round(price, 2),
                "quantity": int(qty // LOT_SIZE),
                "invest_amount": round(invest_amount, 2),
                "cio_reasoning": decision,
                "debate_transcript": debate_transcript,
                "verdict": verdict,
                "net_score": net_score,
                "workflow": workflow,
                "date": date_str,
                "current_weight_pct": current_weight_pct,
                "target_weight_pct": weight_pct,
                "equity_snapshot": round(equity_before, 2),
            }
        )

    def _append_sell_entry(qty: float, proceeds: float) -> None:
        ledger.append(
            {
                "ticker": ticker,
                "action": action.value,
                "price": round(price, 2),
                "quantity": int(qty // LOT_SIZE),
                "sold_amount": round(proceeds, 2),
                "cio_reasoning": decision,
                "debate_transcript": debate_transcript,
                "verdict": verdict,
                "net_score": net_score,
                "workflow": workflow,
                "date": date_str,
                "current_weight_pct": current_weight_pct,
                "target_weight_pct": weight_pct,
                "equity_snapshot": round(equity_before, 2),
            }
        )

    if action in {Action.BUY, Action.BUY_MORE}:
        if recent_exits_by_workflow and _is_reentry_blocked(
            recent_exits_by_workflow,
            workflow=workflow,
            ticker=ticker,
            date_str=date_str,
        ):
            print(f"[backtest._apply_decision] Skip {action.value} for {workflow}/{ticker}: next-day re-entry cooldown active.")
            return
        if weight_pct <= current_weight_pct + strategy.weight_increment_buffer_pct:
            return
        if risk_engine:
            allowed, reason = risk_engine.check_buy_allowed(
                portfolio=portfolio,
                ticker=ticker,
                price=price,
                price_map=price_map,
                target_weight_pct=weight_pct,
            )
            if not allowed:
                print(reason)
                return
            from vnstock.database.repo import DataRepository

            repo = DataRepository()
            try:
                sector = repo.resolve_sector_bucket(ticker)
            finally:
                repo.close()
            sector_allowed, sector_reason = risk_engine.check_sector_exposure(
                portfolio=portfolio,
                price_map=price_map,
                ticker=ticker,
                sector=sector,
                target_weight_pct=weight_pct,
            )
            if not sector_allowed:
                print(sector_reason)
                return
        equity_now = portfolio.equity(price_map)
        target_notional = equity_now * (weight_pct / 100.0)
        current_notional = (portfolio.positions.get(ticker).total_qty * price) if portfolio.positions.get(ticker) else 0.0
        incremental = max(0.0, target_notional - current_notional)
        invest = min(portfolio.cash, incremental)
        success, cost = portfolio.buy(ticker, price, invest)
        if success:
            qty = (cost / (price * (1 + BUY_FEE_RATE))) if price > 0 else 0.0
            _append_buy_entry(qty, cost)
    elif action == Action.SELL:
        try:
            pos = portfolio.positions.get(ticker)
            qty = pos.settled_qty if pos else 0.0
            realized_pnl = portfolio.sell_all_settled(ticker, price)
            proceeds = qty * price * (1 - SELL_FEE_RATE)
            cost_basis = proceeds - realized_pnl
            _append_sell_entry(qty, proceeds)
            ledger[-1]["realized_pnl"] = round(realized_pnl, 2)
            ledger[-1]["cost_basis"] = round(cost_basis, 2)
            if recent_exits_by_workflow is not None:
                _record_recent_exit(
                    recent_exits_by_workflow,
                    workflow=workflow,
                    ticker=ticker,
                    action=action.value,
                    date_str=date_str,
                )
        except ValueError:
            print("Bỏ qua Lệnh: Chưa đủ khối lượng T+2")
            return
    elif action == Action.TRIMMING:
        fraction = decision.get("percent") if decision.get("percent") is not None else 0.5
        try:
            pos = portfolio.positions.get(ticker)
            qty_before = pos.settled_qty if pos else 0.0
            realized_pnl = portfolio.sell_fraction_settled(ticker, price, fraction)
            pos_after = portfolio.positions.get(ticker)
            qty_after = pos_after.settled_qty if pos_after else 0.0
            qty_sold = qty_before - qty_after
            if qty_sold > 0:
                proceeds = qty_sold * price * (1 - SELL_FEE_RATE)
                cost_basis = proceeds - realized_pnl
                _append_sell_entry(qty_sold, proceeds)
                ledger[-1]["realized_pnl"] = round(realized_pnl, 2)
                ledger[-1]["cost_basis"] = round(cost_basis, 2)
                if recent_exits_by_workflow is not None:
                    _record_recent_exit(
                        recent_exits_by_workflow,
                        workflow=workflow,
                        ticker=ticker,
                        action=action.value,
                        date_str=date_str,
                    )
        except ValueError:
            print("Bỏ qua Lệnh: Chưa đủ khối lượng T+2")
            return
    elif action == Action.PASS:
        return


def _apply_basket(
    wf: WorkflowResultArena,
    price_map: Dict[str, float],
    decision: Dict[str, object],
    current_weights: Dict[str, float],
    date_str: str,
    *,
    risk_engine: RiskEngine | None = None,
    halt_buys: bool = False,
    recent_exits_by_workflow: Dict[str, Dict[str, str]] | None = None,
) -> None:
    action = str(decision.get("action", "")).upper()
    if action != "BASKET_CREATED":
        wf.daily_trade_ledger.append(
            {
                "ticker": "MARKOWITZ_BASKET",
                "action": action or "PASS",
                "cio_reasoning": decision,
                "workflow": wf.name,
                "date": date_str,
            }
        )
        return
    basket = decision.get("basket", [])
    if not isinstance(basket, list):
        wf.daily_trade_ledger.append(
            {
                "ticker": "MARKOWITZ_BASKET",
                "action": "PASS",
                "cio_reasoning": decision,
                "workflow": wf.name,
                "date": date_str,
            }
        )
        return
    if halt_buys:
        return
    for item in basket:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", ""))
        if not ticker:
            continue
        weight_pct = float(item.get("weight_pct", 0.0) or 0.0)
        if weight_pct <= current_weights.get(ticker, 0.0) + strategy.weight_increment_buffer_pct:
            continue
        if recent_exits_by_workflow and _is_reentry_blocked(
            recent_exits_by_workflow,
            workflow=wf.name,
            ticker=ticker,
            date_str=date_str,
        ):
            print(f"[backtest._apply_basket] Skip BUY for {wf.name}/{ticker}: next-day re-entry cooldown active.")
            continue
        price = price_map.get(ticker)
        if price is None or price <= 0 or weight_pct <= 0:
            continue
        if risk_engine:
            allowed, reason = risk_engine.check_buy_allowed(
                portfolio=wf.portfolio,
                ticker=ticker,
                price=price,
                price_map=price_map,
                target_weight_pct=weight_pct,
            )
            if not allowed:
                print(reason)
                continue
            from vnstock.database.repo import DataRepository

            repo = DataRepository()
            try:
                sector = repo.resolve_sector_bucket(ticker)
            finally:
                repo.close()
            sector_allowed, sector_reason = risk_engine.check_sector_exposure(
                portfolio=wf.portfolio,
                price_map=price_map,
                ticker=ticker,
                sector=sector,
                target_weight_pct=weight_pct,
            )
            if not sector_allowed:
                print(sector_reason)
                continue
        equity_now = wf.portfolio.equity(price_map)
        target_notional = equity_now * (weight_pct / 100.0)
        current_notional = (wf.portfolio.positions.get(ticker).total_qty * price) if wf.portfolio.positions.get(ticker) else 0.0
        incremental = max(0.0, target_notional - current_notional)
        invest = min(wf.portfolio.cash, incremental)
        success, spent = wf.portfolio.buy(ticker, price, invest)
        if success:
            qty = spent / (price * (1 + BUY_FEE_RATE)) if price > 0 else 0.0
            wf.daily_trade_ledger.append(
                {
                    "ticker": ticker,
                    "action": "BUY",
                    "price": round(price, 2),
                    "quantity": int(qty // LOT_SIZE),
                    "invested_amount": round(spent, 2),
                    "cio_reasoning": item.get("reasoning", decision.get("reasoning", "")),
                    "confidence": item.get("confidence", decision.get("confidence", 0.0)),
                    "workflow": wf.name,
                    "date": date_str,
                }
            )


def _execute_stop_loss_hit(
    wf: WorkflowResultArena,
    hit: Dict[str, object],
    price_map: Dict[str, float],
    date_str: str,
) -> bool:
    ticker = str(hit.get("ticker", ""))
    if not ticker or not wf.portfolio.positions.get(ticker):
        return False
    price = float(price_map.get(ticker, 0.0) or 0.0)
    settled_qty = float(hit.get("settled_qty", 0.0) or 0.0)
    if price <= 0 or settled_qty < LOT_SIZE:
        return False
    try:
        realized_pnl = wf.portfolio.sell_fraction_settled(ticker, price, 1.0)
        proceeds = settled_qty * price * (1 - SELL_FEE_RATE)
        wf.daily_trade_ledger.append(
            {
                "ticker": ticker,
                "action": "SELL",
                "price": round(price, 2),
                "quantity": int(settled_qty // LOT_SIZE),
                "sold_amount": round(proceeds, 2),
                "realized_pnl": round(realized_pnl, 2),
                "cost_basis": round(proceeds - realized_pnl, 2),
                "cio_reasoning": {"_stop_loss": True, "loss_pct": hit.get("loss_pct")},
                "workflow": wf.name,
                "date": date_str,
            }
        )
        return True
    except Exception:
        return False


def _current_weight_pct(portfolio: Portfolio, ticker: str, price_map: Dict[str, float]) -> float:
    equity_now = portfolio.equity(price_map)
    if equity_now <= 0:
        return 0.0
    pos = portfolio.positions.get(ticker)
    if not pos:
        return 0.0
    price = price_map.get(ticker, 0.0)
    if price <= 0:
        return 0.0
    return (pos.total_qty * price) / equity_now * 100.0


def _load_portfolio_for_window(path: Path, start: str) -> Portfolio:
    portfolio = Portfolio.load_state(path)
    last_date = portfolio.last_date
    if last_date and pd.to_datetime(last_date) >= pd.to_datetime(start):
        print(
            "[backtest.run_portfolio_backtest] "
            f"Resetting {path.stem} state because saved last_date={last_date} overlaps start={start}."
        )
        return Portfolio()
    return portfolio


async def run_portfolio_backtest(
    start: str = "2026-01-01",
    end: str = "2026-02-01",
    tickers: Optional[List[str]] = None,
    workflows: Optional[List[str]] = None,
) -> List[WorkflowResultArena]:
    Timer.reset(prefix="vnstock.")
    state_source_dir = paths.backtest_results_dir / "state"
    state_dir = _prepare_backtest_root() / "state"
    if tickers is None:
        tickers = VN30_TICKERS

    with Timer.track("vnstock.load_market_data"):
        market_data = load_market_data(start, end, tickers)
    if not market_data:
        return []

    benchmark_prices_by_name: Dict[str, Dict[pd.Timestamp, float]] = {}
    with Timer.track("vnstock.load_benchmark_data"):
        for benchmark_name in ("VN30", "VNINDEX"):
            benchmark_df = load_benchmark_data(start, end, benchmark_name)
            if benchmark_df.empty:
                print(f"⚠️ [Benchmark] Không có dữ liệu {benchmark_name} trong DB. Chạy: python run.py crawl-vnstock --tickers {benchmark_name}", flush=True)
            # CRITICAL: DB stores in thousands, multiply by 1000 ONCE
            benchmark_prices_by_name[benchmark_name] = {
                pd.to_datetime(row["date"]).normalize(): float(row["close"]) * 1000.0
                for _, row in benchmark_df.iterrows()
                if float(row["close"]) > 0.0
            }
            # Validate benchmark prices after conversion to prevent corrupt curves
            for date, price_vnd in benchmark_prices_by_name[benchmark_name].items():
                if not (1_000 < price_vnd < 5_000_000):
                    raise ValueError(
                        f"Invalid {benchmark_name} price after conversion: {price_vnd} VND at {date}. "
                        f"Expected range: 1,000 - 5,000,000 VND. Check DB data integrity."
                    )

    day_price_maps: List[Tuple[pd.Timestamp, Dict[str, float]]] = []
    unique_dates = sorted({d for df in market_data.values() for d in df["date"].tolist()})
    for date in unique_dates:
        price_map: Dict[str, float] = {}
        for ticker, df in market_data.items():
            row = df[df["date"] == date]
            if not row.empty:
                # Vnstock data format is in 1,000 VND (e.g. 65.5), scale to raw VND
                price_map[ticker] = float(row.iloc[0]["close"]) * 1000.0
                if not (1_000 <= price_map[ticker] <= 5_000_000):
                    print(f"[WARN] {ticker} price {price_map[ticker]} out of valid range, skipping")
                    del price_map[ticker]
                    continue
        if price_map:
            day_price_maps.append((date, price_map))

    benchmark_curves = {
        benchmark_name: _build_benchmark_curve(day_price_maps, benchmark_prices_by_date)
        for benchmark_name, benchmark_prices_by_date in benchmark_prices_by_name.items()
    }

    workflows_map: Dict[str, WorkflowResultArena] = {}
    selected_names = workflows or getattr(strategy, "selected_workflows", None)
    if selected_names is None:
        selected_names = list(DEFAULT_WORKFLOWS)
    if isinstance(selected_names, str):
        selected_names = [selected_names]
    for name in selected_names:
        if name not in DEFAULT_WORKFLOWS:
            print(f"[backtest.run_portfolio_backtest] Unknown workflow '{name}', skipping instantiation.")
            continue
        wf_portfolio = _load_portfolio_for_window(state_source_dir / f"{name}.json", start)
        workflows_map[name] = WorkflowResultArena(name, wf_portfolio, StrategyParams())
    recent_exits_by_workflow = _seed_recent_exits(_prepare_backtest_root())
    if not workflows_map:
        print("[backtest.run_portfolio_backtest] No valid workflows to run.")
        return []

    last_processed = {name: wf.portfolio.last_date for name, wf in workflows_map.items()}

    agent_pool = SharedAgentPool()
    trad_wf = TraditionalScoringWorkflow(model=models.primary_model)
    kelly_wf = KellyCriterionWorkflow(model=models.primary_model)
    markowitz_wf = MarkowitzFrontierWorkflow(model=models.primary_model)
    llm_semaphore = asyncio.Semaphore(models.llm_concurrency)
    risk_engine = RiskEngine(RiskLimits())
    benchmark_analyzers = {
        benchmark_name: BenchmarkAnalyzer(benchmark_name=benchmark_name)
        for benchmark_name in ("VN30", "VNINDEX")
    }
    halt_buys_map: Dict[str, bool] = {}
    TICKER_BATCH_SIZE = 15  # 80 ProxyPal accounts — 2 batches for 30 tickers

    try:
        for date, price_map in day_price_maps:
            date_str = pd.to_datetime(date).strftime("%Y-%m-%d")
            day_timer_snapshot = Timer.snapshot()

            # Skip weekends for backtest consistency
            if not is_trading_day(pd.to_datetime(date).strftime("%Y-%m-%d")):
                continue

            # Resume skip logic per workflow
            if all(lp and date_str <= lp for lp in last_processed.values()):
                continue

            for wf in workflows_map.values():
                # If this workflow already processed this date, skip its actions
                if wf.portfolio.last_date and date_str <= wf.portfolio.last_date:
                    continue
                wf.portfolio.rollover_day()

            # Pre-market risk checks: detect stop-loss hits per workflow, but defer execution
            pending_stop_losses: Dict[str, Dict[str, Dict[str, object]]] = {}
            for wf_name, wf in workflows_map.items():
                stop_hits = risk_engine.check_stop_loss(wf.portfolio, price_map)
                if stop_hits:
                    pending_stop_losses[wf_name] = {
                        str(hit.get("ticker", "")).upper(): hit
                        for hit in stop_hits
                        if str(hit.get("ticker", ""))
                    }

            selected_tickers = sorted(price_map.keys())
            print(f"[VNSTOCK] Date: {date_str}")
            print(f"Processing tickers trực tiếp: {selected_tickers}")

            with Timer.track("vnstock.daily_macro"):
                daily_macro_output = AgentOutput(
                    agent_name="macro",
                    raw_analysis=await agent_pool.macro.analyze(ref_date=date_str),
                )

            agent_outputs_map: Dict[str, Dict[str, AgentOutput]] = {}
            markowitz_candidates: List[str] = []
            current_weights_map: Dict[str, float] = {}
            normalized_ticker_artifacts: Dict[str, Dict[str, Any]] = {}

            # Phase A: collect Tier-2 outputs only
            for batch_start in range(0, len(selected_tickers), TICKER_BATCH_SIZE):
                batch = selected_tickers[batch_start : batch_start + TICKER_BATCH_SIZE]
                print(f"  [BATCH] Processing tickers {batch_start+1}-{min(batch_start+TICKER_BATCH_SIZE, len(selected_tickers))}/{len(selected_tickers)}: {batch}")
                tier2_tasks = []
                for ticker in batch:
                    tier2_tasks.append(
                        asyncio.create_task(
                            _collect_tier2(
                                ticker=ticker,
                                date_str=date_str,
                                market_data=market_data,
                                agent_pool=agent_pool,
                                macro_cached=daily_macro_output,
                                llm_semaphore=llm_semaphore,
                                workflows=workflows_map,
                                price_map=price_map,
                                agent_outputs_map=agent_outputs_map,
                                markowitz_candidates=markowitz_candidates,
                                current_weights_map=current_weights_map,
                            )
                        )
                    )
                if tier2_tasks:
                    with Timer.track("vnstock.ticker_batch"):
                        await asyncio.gather(*tier2_tasks)

            # Phase B: run Traditional/Kelly per ticker and Markowitz basket-level in parallel
            per_ticker_tasks = []
            for ticker in selected_tickers:
                if ticker in agent_outputs_map:
                    per_ticker_tasks.append(
                        asyncio.create_task(
                            _finalize_ticker_workflows(
                                ticker=ticker,
                                date_str=date_str,
                                price_map=price_map,
                                workflows=workflows_map,
                                agent_outputs=agent_outputs_map[ticker],
                                risk_engine=risk_engine,
                                halt_buys_map=halt_buys_map,
                                normalized_ticker_artifacts=normalized_ticker_artifacts,
                                pending_stop_losses=pending_stop_losses,
                                recent_exits_by_workflow=recent_exits_by_workflow,
                            )
                        )
                    )

            markowitz_task = None
            if markowitz_candidates:
                mk_wf = workflows_map.get("Markowitz")
                if mk_wf:
                    mk_snapshot = mk_wf.portfolio.snapshot("MARKOWITZ_BASKET", price_map)
                    markowitz_task = asyncio.create_task(
                        _run_markowitz_workflow(
                            date_str=date_str,
                            price_map=price_map,
                            markowitz_wf=markowitz_wf,
                            mk_wf=mk_wf,
                            markowitz_candidates=markowitz_candidates,
                            agent_outputs_map=agent_outputs_map,
                            current_weights_map=current_weights_map,
                            llm_semaphore=llm_semaphore,
                            normalized_ticker_artifacts=normalized_ticker_artifacts,
                            risk_engine=risk_engine,
                            halt_buys=halt_buys_map.get("Markowitz", False),
                            pending_stop_losses=pending_stop_losses.get("Markowitz", {}),
                            recent_exits_by_workflow=recent_exits_by_workflow,
                        )
                    )

            if per_ticker_tasks or markowitz_task:
                tasks = [*per_ticker_tasks, *([markowitz_task] if markowitz_task else [])]
                await asyncio.gather(*tasks)

            # Phase 1: Sync operations (persist, equity, drawdown, save state)
            report_tasks = []
            normalized_daily_dir = BACKTEST_ROOT / date_str / "normalized"
            for wf_name, wf in workflows_map.items():
                if wf.portfolio.last_date and date_str <= wf.portfolio.last_date:
                    continue

                # Canonical order: ledger persist -> portfolio save -> reporter -> ledger clear
                _persist_ledger_placeholder(wf_name, date_str, wf.daily_trade_ledger)
                equity_now = wf.portfolio.equity(price_map)
                wf.portfolio.equity_history.append(equity_now)
                invested_value = max(equity_now - wf.portfolio.cash, 0.0)
                peak_equity = max([float(point.get("equity", START_CAPITAL)) for point in wf.equity_curve_points], default=START_CAPITAL)
                peak_equity = max(peak_equity, equity_now, START_CAPITAL)
                drawdown_pct = ((equity_now - peak_equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0
                wf.equity_curve_points.append(
                    {
                        "date": date_str,
                        "equity": round(equity_now, 4),
                        "cash": round(wf.portfolio.cash, 4),
                        "invested": round(invested_value, 4),
                        "drawdown_pct": round(drawdown_pct, 4),
                    }
                )
                # Drawdown halt check after equity update for the day
                halted, dd_pct = risk_engine.check_drawdown(
                    wf.portfolio.equity_history, equity_now, START_CAPITAL
                )
                if halted:
                    wf.daily_trade_ledger.append(
                        {
                            "ticker": "PORTFOLIO",
                            "action": "HALT_BUYS",
                            "cio_reasoning": {"_drawdown_halt": True, "drawdown_pct": dd_pct},
                            "workflow": wf_name,
                            "date": date_str,
                        }
                    )
                    halt_buys_map[wf_name] = True
                wf.portfolio.last_date = date_str
                state_path = state_dir / f"{wf_name}.json"
                wf.portfolio.save_state(state_path)
                normalized_entries = normalized_ticker_artifacts.get(wf_name, {})
                normalized_envelope = WorkflowArtifactEnvelope(
                    workflow=wf_name.lower(),
                    artifact_origin="adapted",
                    analysis_depth="sparse",
                    as_of_date=date_str,
                    generated_at=datetime.now().isoformat(timespec="seconds"),
                    locale="vi-VN",
                    summary={
                        "date": date_str,
                        "workflow": wf_name,
                        "equity": round(equity_now, 4),
                        "cash": round(wf.portfolio.cash, 4),
                        "drawdown_pct": round(drawdown_pct, 4),
                        "trade_count": len(wf.daily_trade_ledger),
                    },
                    portfolio_state={
                        "cash": wf.portfolio.cash,
                        "positions": {
                            ticker: {
                                "lots": [
                                    {"qty": lot.qty, "price": lot.price, "days_held": lot.days_held}
                                    for lot in pos.lots
                                ]
                            }
                            for ticker, pos in wf.portfolio.positions.items()
                        },
                        "trades": wf.portfolio.trades,
                        "sells": wf.portfolio.sells,
                        "wins": wf.portfolio.wins,
                        "equity_history": list(wf.portfolio.equity_history),
                        "last_date": wf.portfolio.last_date,
                        "buys_per_ticker": dict(wf.portfolio.buys_per_ticker),
                    },
                    ledger=list(wf.daily_trade_ledger),
                    analysis={
                        ticker_key: WorkflowTickerArtifact.model_validate(artifact_payload)
                        if isinstance(artifact_payload, dict) and "version" in artifact_payload
                        else WorkflowTickerArtifact(
                            workflow=wf_name.lower(),
                            artifact_origin="adapted",
                            analysis_depth="sparse",
                            ticker=ticker_key,
                            ref_date=date_str,
                            planner=None,
                            cards=[],
                            debate=None,
                            cio_intent=dict(artifact_payload.get("decision") or {}) if isinstance(artifact_payload, dict) else {},
                            risk={"legacy_surface": True},
                            trade=None,
                            metadata=dict(artifact_payload) if isinstance(artifact_payload, dict) else {},
                        )
                        for ticker_key, artifact_payload in normalized_entries.items()
                    },
                    risk_report={
                        "drawdown_halt": halt_buys_map.get(wf_name, False),
                        "legacy_surface": True,
                    },
                    calibration=[],
                    equity_curve=list(wf.equity_curve_points),
                    metadata={
                        "schema_version": ARTIFACT_VERSION,
                        "adaptation_note": "Legacy workflow envelope; sparse/adapted fields only where native depth is unavailable.",
                    },
                )
                normalized_envelope_json = normalized_envelope.model_dump(mode="json")
                _write_json(normalized_daily_dir / f"{wf_name.lower()}_workflow_artifact.json", normalized_envelope_json)
                # Snapshot ledger before clearing for parallel report generation
                report_tasks.append(_run_daily_report(wf_name, date_str, list(wf.daily_trade_ledger), normalized_envelope_json))
                _clear_ledger_placeholder(wf_name)
                wf.daily_trade_ledger.clear()

            # Phase 2: Run all daily reports in parallel
            if report_tasks:
                with Timer.track("vnstock.daily_reports"):
                    await asyncio.gather(*report_tasks)

            day_timing = Timer.summary_since(day_timer_snapshot, prefix="vnstock.")
            if day_timing:
                for wf in workflows_map.values():
                    if wf.portfolio.last_date == date_str:
                        wf.timing_by_date[date_str] = day_timing
                _write_json(BACKTEST_ROOT / "evaluation" / "timing" / f"{date_str}.json", day_timing)
                print(f"[{date_str}] Timing summary: {json.dumps(day_timing, ensure_ascii=False)}")
            print(f"[{date_str}] Trading day complete.")

        evaluation_root = BACKTEST_ROOT / "evaluation"
        for wf in workflows_map.values():
            wf.benchmark_metrics = {
                benchmark_name: analyzer.compare(
                    equity_curve=wf.portfolio.equity_history,
                    benchmark_prices=benchmark_curves.get(benchmark_name, []),
                    start_capital=START_CAPITAL,
                )
                for benchmark_name, analyzer in benchmark_analyzers.items()
            }
            workflow_eval_dir = evaluation_root / wf.name.lower()
            equity_curve_path = workflow_eval_dir / "equity_curve.json"
            timing_path = workflow_eval_dir / "timing.json"
            summary_path = workflow_eval_dir / "summary.json"
            _write_json(equity_curve_path, {"workflow": wf.name, "points": wf.equity_curve_points})
            _write_json(timing_path, {"workflow": wf.name, "timing_by_date": wf.timing_by_date})
            metrics = wf.metrics(final_prices={})
            summary_payload = {
                "workflow": wf.name,
                "start": start,
                "end": end,
                "tickers": tickers,
                "trading_days": len(wf.equity_curve_points),
                "metrics": metrics,
                "quarterly_return_pct": round(_quarterly_return_pct(wf.equity_curve_points), 4),
                "benchmarks": wf.benchmark_metrics,
                "trade_quality": _trade_quality_metrics(BACKTEST_ROOT, wf.name),
                "artifacts": {
                    "equity_curve": str(equity_curve_path.relative_to(BACKTEST_ROOT)),
                    "timing": str(timing_path.relative_to(BACKTEST_ROOT)),
                    "state": str((state_dir / f"{wf.name}.json").relative_to(BACKTEST_ROOT)),
                },
            }
            _write_json(summary_path, summary_payload)

        return list(workflows_map.values())
    finally:
        try:
            from vnstock.core import llm as llm_core

            await llm_core.close_session()
        except Exception:
            pass
        try:
            from tracking_news.app.summarizer import close_session as news_close_session

            await news_close_session()
        except Exception:
            pass


async def _collect_tier2(
    *,
    ticker: str,
    date_str: str,
    market_data: Dict[str, pd.DataFrame],
    agent_pool: SharedAgentPool,
    macro_cached: AgentOutput,
    llm_semaphore: asyncio.Semaphore,
    workflows: Dict[str, WorkflowResultArena],
    price_map: Dict[str, float],
    agent_outputs_map: Dict[str, Dict[str, AgentOutput]],
    markowitz_candidates: List[str],
    current_weights_map: Dict[str, float],
) -> None:
    # ── Tier 2: Expert Agents (parallel internally, rate-limited by call_llm) ──
    dt = pd.to_datetime(date_str)
    df_price = market_data[ticker]
    price_dates = pd.to_datetime(df_price["date"]).dt.normalize()
    if not (price_dates == dt.normalize()).any():
        return
    fin_year, fin_quarter = get_latest_financial_quarter(dt)

    agent_outputs = await agent_pool.run_all(
        ticker=ticker,
        ref_date=date_str,
        year=str(fin_year),
        quarter=f"Q{fin_quarter}",
        llm_semaphore=llm_semaphore,
        macro_cached=macro_cached,
    )
    agent_outputs_map[ticker] = agent_outputs

    ticker_dir = BACKTEST_ROOT / date_str / ticker
    shared_dir = ticker_dir / "tier1_shared"
    _write_json(
        shared_dir / "agents.json",
        {
            "ticker": ticker,
            "ref_date": date_str,
            "shared_agent_outputs": {k: v.raw_analysis for k, v in agent_outputs.items()},
        },
    )

    markowitz_wf_inst = workflows.get("Markowitz")
    if markowitz_wf_inst:
        current_weights_map[ticker] = _current_weight_pct(markowitz_wf_inst.portfolio, ticker, price_map)
        markowitz_candidates.append(ticker)
    else:
        current_weights_map[ticker] = 0.0


async def _finalize_ticker_workflows(
    *,
    ticker: str,
    date_str: str,
    price_map: Dict[str, float],
    workflows: Dict[str, WorkflowResultArena],
    agent_outputs: Dict[str, AgentOutput],
    risk_engine: RiskEngine,
    halt_buys_map: Dict[str, bool],
    normalized_ticker_artifacts: Dict[str, Dict[str, Any]],
    pending_stop_losses: Dict[str, Dict[str, Dict[str, object]]],
    recent_exits_by_workflow: Dict[str, Dict[str, str]],
) -> None:
    ticker_dir = BACKTEST_ROOT / date_str / ticker
    trad_wf_inst = workflows.get("Traditional")
    kelly_wf_inst = workflows.get("Kelly")

    current_weight_trad = _current_weight_pct(trad_wf_inst.portfolio, ticker, price_map) if trad_wf_inst else 0.0
    trad_snapshot = trad_wf_inst.portfolio.snapshot(ticker, price_map) if trad_wf_inst else {}
    current_weight_kelly = _current_weight_pct(kelly_wf_inst.portfolio, ticker, price_map) if kelly_wf_inst else 0.0
    kelly_snapshot = kelly_wf_inst.portfolio.snapshot(ticker, price_map) if kelly_wf_inst else {}

    shared_debate_res = None
    if trad_wf_inst or kelly_wf_inst:
        from config import models
        from vnstock.workflows.debate.autogen_debate import run_autogen_debate

        shared_debate_res = await run_autogen_debate(
            ticker=ticker,
            ref_date=date_str,
            agent_outputs=agent_outputs,
            model=models.t3_debate_model,
        )

    coros = []
    if trad_wf_inst:
        coros.append(
            TraditionalScoringWorkflow(model=trad_wf_inst.name and None).run(
                ticker=ticker,
                ref_date=date_str,
                agent_outputs=agent_outputs,
                current_weight_pct=current_weight_trad,
                portfolio_snapshot=trad_snapshot,
                debate_res=shared_debate_res,
            )
        )
    else:
        coros.append(asyncio.sleep(0))

    if kelly_wf_inst:
        coros.append(
            KellyCriterionWorkflow(model=kelly_wf_inst.name and None).run(
                ticker=ticker,
                ref_date=date_str,
                agent_outputs=agent_outputs,
                current_weight_pct=current_weight_kelly,
                portfolio_snapshot=kelly_snapshot,
                debate_res=shared_debate_res,
            )
        )
    else:
        coros.append(asyncio.sleep(0))

    trad_res, kelly_res = await asyncio.gather(*coros)

    if trad_wf_inst:
        trad_dir = ticker_dir / "traditional"
        _write_text(trad_dir / "tier2_debate_transcript.txt", trad_res["transcript"])
        trad_decision = {**trad_res["decision"], "ticker": ticker, "portfolio_snapshot": trad_snapshot}
        _write_json(trad_dir / "tier3_cio_decision.json", trad_decision)
        trad_action = normalize_action(trad_decision.get("action"))
        trad_pending_hit = pending_stop_losses.get("Traditional", {}).get(ticker.upper())
        ledger_len_before = len(trad_wf_inst.daily_trade_ledger)
        if trad_pending_hit and trad_action not in {Action.BUY, Action.BUY_MORE}:
            _execute_stop_loss_hit(trad_wf_inst, trad_pending_hit, price_map, date_str)
        else:
            trad_execution_decision = _maybe_take_profit_trim_decision(
                ticker=ticker,
                portfolio_snapshot=trad_snapshot,
                current_weight_pct=current_weight_trad,
                decision=trad_decision,
            )
            _apply_decision(
                trad_wf_inst.portfolio,
                ticker,
                price_map,
                trad_execution_decision,
                current_weight_trad,
                trad_wf_inst.daily_trade_ledger,
                workflow="Traditional",
                date_str=date_str,
                debate_transcript=trad_res.get("transcript"),
                verdict=trad_res["decision"].get("verdict"),
                net_score=trad_res["decision"].get("net_score"),
                risk_engine=risk_engine,
                halt_buys=halt_buys_map.get("Traditional", False),
                recent_exits_by_workflow=recent_exits_by_workflow,
            )
        trad_ledger_entry = trad_wf_inst.daily_trade_ledger[-1] if len(trad_wf_inst.daily_trade_ledger) > ledger_len_before else None
        _persist_normalized_legacy_workflow_artifact(
            workflow="Traditional",
            date_str=date_str,
            ticker=ticker,
            ref_date=date_str,
            agent_outputs=agent_outputs,
            decision=trad_decision,
            debate_transcript=trad_res.get("transcript"),
            ledger_entry=trad_ledger_entry,
            portfolio_snapshot=trad_snapshot,
        )
        normalized_ticker_artifacts.setdefault("Traditional", {})[ticker] = {
            "date": date_str,
            "ticker": ticker,
            "workflow": "Traditional",
            "artifact_origin": "adapted",
            "analysis_depth": "sparse",
        }

    if kelly_wf_inst:
        kelly_dir = ticker_dir / "kelly"
        _write_text(kelly_dir / "tier2_debate_transcript.txt", kelly_res["transcript"])
        kelly_decision = {**kelly_res["decision"], "ticker": ticker, "portfolio_snapshot": kelly_snapshot}
        _write_json(kelly_dir / "tier3_cio_decision.json", kelly_decision)
        kelly_action = normalize_action(kelly_decision.get("action"))
        kelly_pending_hit = pending_stop_losses.get("Kelly", {}).get(ticker.upper())
        ledger_len_before = len(kelly_wf_inst.daily_trade_ledger)
        if kelly_pending_hit and kelly_action not in {Action.BUY, Action.BUY_MORE}:
            _execute_stop_loss_hit(kelly_wf_inst, kelly_pending_hit, price_map, date_str)
        else:
            kelly_execution_decision = _maybe_take_profit_trim_decision(
                ticker=ticker,
                portfolio_snapshot=kelly_snapshot,
                current_weight_pct=current_weight_kelly,
                decision=kelly_decision,
            )
            _apply_decision(
                kelly_wf_inst.portfolio,
                ticker,
                price_map,
                kelly_execution_decision,
                current_weight_kelly,
                kelly_wf_inst.daily_trade_ledger,
                workflow="Kelly",
                date_str=date_str,
                debate_transcript=kelly_res.get("transcript"),
                verdict=kelly_res["decision"].get("verdict"),
                net_score=kelly_res["decision"].get("net_score"),
                risk_engine=risk_engine,
                halt_buys=halt_buys_map.get("Kelly", False),
                recent_exits_by_workflow=recent_exits_by_workflow,
            )
        kelly_ledger_entry = kelly_wf_inst.daily_trade_ledger[-1] if len(kelly_wf_inst.daily_trade_ledger) > ledger_len_before else None
        _persist_normalized_legacy_workflow_artifact(
            workflow="Kelly",
            date_str=date_str,
            ticker=ticker,
            ref_date=date_str,
            agent_outputs=agent_outputs,
            decision=kelly_decision,
            debate_transcript=kelly_res.get("transcript"),
            ledger_entry=kelly_ledger_entry,
            portfolio_snapshot=kelly_snapshot,
        )
        normalized_ticker_artifacts.setdefault("Kelly", {})[ticker] = {
            "date": date_str,
            "ticker": ticker,
            "workflow": "Kelly",
            "artifact_origin": "adapted",
            "analysis_depth": "sparse",
        }


async def _run_markowitz_workflow(
    *,
    date_str: str,
    price_map: Dict[str, float],
    markowitz_wf: MarkowitzFrontierWorkflow,
    mk_wf: WorkflowResultArena,
    markowitz_candidates: List[str],
    agent_outputs_map: Dict[str, Dict[str, AgentOutput]],
    current_weights_map: Dict[str, float],
    llm_semaphore: asyncio.Semaphore,
    normalized_ticker_artifacts: Dict[str, Dict[str, Any]],
    risk_engine: RiskEngine | None = None,
    halt_buys: bool = False,
    pending_stop_losses: Dict[str, Dict[str, object]] | None = None,
    recent_exits_by_workflow: Dict[str, Dict[str, str]] | None = None,
) -> None:
    mk_snapshot = mk_wf.portfolio.snapshot("MARKOWITZ_BASKET", price_map)
    with Timer.track("vnstock.markowitz_workflow"):
        mk_res = await markowitz_wf.run(
            tickers=markowitz_candidates,
            ref_date=date_str,
            agent_outputs_map=agent_outputs_map,
            current_weights=current_weights_map,
            portfolio_snapshot=mk_snapshot,
            llm_semaphore=llm_semaphore,
        )
    marko_dir = BACKTEST_ROOT / date_str / "markowitz"
    _write_text(marko_dir / "tier2_debate_transcript.txt", mk_res["transcript"])
    _write_json(marko_dir / "tier3_cio_decision.json", mk_res["decision"])
    basket = mk_res["decision"].get("basket", []) if isinstance(mk_res["decision"], dict) else []
    buy_intent_tickers = {
        str(item.get("ticker", "")).upper()
        for item in basket
        if isinstance(item, dict)
        and str(item.get("ticker", ""))
        and float(item.get("weight_pct", 0.0) or 0.0) > current_weights_map.get(str(item.get("ticker", "")).upper(), 0.0) + strategy.weight_increment_buffer_pct
    }
    for ticker, hit in (pending_stop_losses or {}).items():
        if ticker.upper() in buy_intent_tickers:
            continue
        _execute_stop_loss_hit(mk_wf, hit, price_map, date_str)
    for held_ticker in list(mk_wf.portfolio.positions.keys()):
        if held_ticker.upper() in buy_intent_tickers:
            continue
        current_weight_pct = current_weights_map.get(held_ticker.upper(), 0.0)
        trim_snapshot = mk_wf.portfolio.snapshot(held_ticker, price_map)
        trim_decision = _maybe_take_profit_trim_decision(
            ticker=held_ticker,
            portfolio_snapshot=trim_snapshot,
            current_weight_pct=current_weight_pct,
            decision={"action": Action.PASS.value, "weight_pct": current_weight_pct},
        )
        if normalize_action(trim_decision.get("action")) == Action.TRIMMING:
            _apply_decision(
                mk_wf.portfolio,
                held_ticker,
                price_map,
                trim_decision,
                current_weight_pct,
                mk_wf.daily_trade_ledger,
                workflow="Markowitz",
                date_str=date_str,
                debate_transcript=mk_res.get("transcript"),
                verdict=mk_res.get("decision", {}).get("verdict") if isinstance(mk_res.get("decision"), dict) else None,
                net_score=mk_res.get("decision", {}).get("net_score") if isinstance(mk_res.get("decision"), dict) else None,
                risk_engine=risk_engine,
                halt_buys=halt_buys,
                recent_exits_by_workflow=recent_exits_by_workflow,
            )
    _apply_basket(
        mk_wf,
        price_map,
        mk_res["decision"],
        current_weights_map,
        date_str,
        risk_engine=risk_engine,
        halt_buys=halt_buys,
        recent_exits_by_workflow=recent_exits_by_workflow,
    )
    normalized_ticker_artifacts.setdefault("Markowitz", {})["MARKOWITZ_BASKET"] = {
        "date": date_str,
        "ticker": "MARKOWITZ_BASKET",
        "workflow": "Markowitz",
        "artifact_origin": "adapted",
        "analysis_depth": "sparse",
        "decision": mk_res["decision"],
    }


def persist_metrics(results: List[WorkflowResultArena], start: str, end: str) -> None:
    from vnstock.database.models import BacktestMetric, SessionLocal

    session = SessionLocal()
    try:
        for res in results:
            metrics = res.metrics(final_prices={})
            record = BacktestMetric(
                workflow_name=res.name,
                ticker="VN30_PORTFOLIO",
                start_date=pd.to_datetime(start),
                end_date=pd.to_datetime(end),
                account_value=metrics["account_value"],
                return_pct=metrics["return_pct"],
                total_pnl=metrics["total_pnl"],
                win_rate=metrics["win_rate"],
                sharpe=metrics["sharpe"],
                trades=metrics["trades"],
            )
            session.add(record)
        session.commit()
    finally:
        session.close()


def markdown_summary(results: List[WorkflowResultArena], final_prices: Dict[str, float]) -> str:
    header = (
        "| Workflow | Acct Value | Return % | Total PnL | Trades | Sharpe | Sortino | Calmar | "
        "MDD | VaR95 | CVaR95 | PF | Win Rate | VN30 | Active | Alpha | Beta | IR |"
    )
    sep = (
        "|----------|------------|----------|-----------|--------|--------|---------|--------|------|-------|--------|"
        "----|----------|------|--------|-------|------|----|"
    )
    rows = []
    for res in results:
        m = res.metrics(final_prices)
        benchmark = res.benchmark_metrics or {}
        profit_factor = m["profit_factor"]
        profit_factor_display = "inf" if math.isinf(float(profit_factor)) else f"{float(profit_factor):.2f}"
        rows.append(
            "| "
            f"{res.name} | "
            f"{float(m['account_value']):,.0f} | "
            f"{float(m['return_pct']):.2f}% | "
            f"{float(m['total_pnl']):,.0f} | "
            f"{int(m['trades'])} | "
            f"{float(m['sharpe']):.2f} | "
            f"{float(m['sortino']):.2f} | "
            f"{float(m['calmar']):.2f} | "
            f"{float(m['max_drawdown_pct']):.2f}% | "
            f"{float(m['var_95_pct']):.2f}% | "
            f"{float(m['cvar_95_pct']):.2f}% | "
            f"{profit_factor_display} | "
            f"{float(m['win_rate']):.2f}% | "
            f"{float(benchmark.get('benchmark_return_pct', 0.0)):.2f}% | "
            f"{float(benchmark.get('active_return_pct', 0.0)):.2f}% | "
            f"{float(benchmark.get('alpha_annualized_pct', 0.0)):.2f}% | "
            f"{float(benchmark.get('beta', 0.0)):.2f} | "
            f"{float(benchmark.get('information_ratio', 0.0)):.2f} |"
        )
    return "\n".join([header, sep] + rows)
