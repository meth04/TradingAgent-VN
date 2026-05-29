"""Job-based multi-agent analysis orchestrator.

POST /api/analyze creates a job, schedules it on the asyncio loop, and returns
the job_id immediately. The frontend polls GET /api/analyze/{job_id} every ~1s
to pick up newly-finished agents, the CIO decision per ticker, and finally the
Markdown report. Job state lives in memory; the last N jobs stay accessible
after they finish so a slow poll can still fetch the final snapshot.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services import market_service, portfolio_service

AGENT_NAMES: Tuple[str, ...] = ("macro", "technical", "quant", "news", "financial")

WORKFLOW_LABELS = {
    "traditional": "Traditional Scoring",
    "kelly": "Kelly Criterion",
    "markowitz": "Markowitz Frontier",
    "cognitive": "Cognitive Swarm",
}

# Keep the most recent N jobs in memory after completion; older ones are
# evicted (history is already persisted to app/data/history/ so this is a
# pure runtime cache for polling).
MAX_JOBS_IN_MEMORY = 30


@dataclass
class AnalysisRequest:
    tickers: List[str]
    workflow: str
    portfolio: Optional[Dict[str, Any]] = None


@dataclass
class _AgentSlot:
    ticker: str
    agent: str
    output: str = ""
    confidence: Optional[float] = None
    action: Optional[str] = None
    error: Optional[str] = None
    # pending → running → completed | error
    status: str = "pending"


@dataclass
class _Job:
    id: str
    request: AnalysisRequest
    workflow: str
    ref_date: str
    status: str  # "running" | "done" | "error"
    started_at: float
    finished_at: Optional[float] = None
    phase: str = "init"  # init | crawl | agents | cio | report | done
    agents: Dict[Tuple[str, str], _AgentSlot] = field(default_factory=dict)
    cio: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    debate: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    report: str = ""
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    analysis_id: Optional[str] = None


_JOBS: Dict[str, _Job] = {}
_JOBS_ORDER: List[str] = []


# ── Public API ──────────────────────────────────────────────────────────────


def create_job(request: AnalysisRequest) -> str:
    """Register a new job and schedule it. Returns the job_id immediately.

    Dedupes near-duplicate POSTs (within 10s, same tickers + workflow, still
    running) by returning the existing job id — guards against React Strict
    Mode double-firing the analysis effect in dev.
    """
    now = time.time()
    new_key = (
        tuple(sorted(t.upper() for t in request.tickers)),
        (request.workflow or "cognitive").lower(),
    )
    for jid in reversed(_JOBS_ORDER):
        existing = _JOBS.get(jid)
        if existing is None or existing.status != "running":
            continue
        if (now - existing.started_at) > 10:
            continue
        existing_key = (
            tuple(sorted(t.upper() for t in existing.request.tickers)),
            existing.workflow,
        )
        if existing_key == new_key:
            return existing.id
    job = _new_job(request)
    asyncio.create_task(_run_job(job))
    return job.id


def get_job_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    job = _JOBS.get(job_id)
    if job is None:
        return None
    return _snapshot(job)


# ── Job lifecycle helpers ───────────────────────────────────────────────────


def _new_job(request: AnalysisRequest) -> _Job:
    workflow = (request.workflow or "cognitive").lower()
    if workflow not in WORKFLOW_LABELS:
        workflow = "cognitive"
    job = _Job(
        id=uuid.uuid4().hex[:12],
        request=request,
        workflow=workflow,
        ref_date=datetime.now().strftime("%Y-%m-%d"),
        status="running",
        started_at=time.time(),
    )
    # Pre-populate slots so the snapshot is uniform from t=0 onward.
    for t in request.tickers:
        for a in AGENT_NAMES:
            job.agents[(t, a)] = _AgentSlot(ticker=t, agent=a)
    _JOBS[job.id] = job
    _JOBS_ORDER.append(job.id)
    while len(_JOBS_ORDER) > MAX_JOBS_IN_MEMORY:
        old = _JOBS_ORDER.pop(0)
        _JOBS.pop(old, None)
    return job


def _snapshot(job: _Job) -> Dict[str, Any]:
    agents_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for t in job.request.tickers:
        agents_by_ticker[t] = []
        for a in AGENT_NAMES:
            s = job.agents.get((t, a))
            if s is None:
                continue
            agents_by_ticker[t].append(
                {
                    "agent": s.agent,
                    "ticker": s.ticker,
                    "status": s.status,
                    "output": s.output,
                    "confidence": s.confidence,
                    "action": s.action,
                    "error": s.error,
                }
            )
    end = job.finished_at or time.time()
    return {
        "job_id": job.id,
        "status": job.status,
        "phase": job.phase,
        "started_at": job.started_at,
        "elapsed_s": round(end - job.started_at, 1),
        "tickers": job.request.tickers,
        "workflow": job.workflow,
        "ref_date": job.ref_date,
        "agents": agents_by_ticker,
        "cio": job.cio,
        "debate": job.debate,
        "report": job.report,
        "logs": list(job.logs),
        "error": job.error,
        "analysis_id": job.analysis_id,
    }


def _log(job: _Job, message: str) -> None:
    job.logs.append(message)
    # Keep logs bounded so a misbehaving agent can't blow up memory.
    if len(job.logs) > 200:
        job.logs = job.logs[-200:]


# ── Orchestrator ────────────────────────────────────────────────────────────


async def _run_job(job: _Job) -> None:
    """Execute the full pipeline, writing into `job` in place."""
    try:
        from vnstock.agents.macro_agent import MacroAgent
        from vnstock.agents.news_agent import NewsAgent
        from vnstock.agents.technical_agent import TechnicalAgent
        from vnstock.agents.quant_agent import QuantAgent
        from vnstock.agents.financial_agent import FinancialAgent
        from vnstock.tools.backtest.engine import get_latest_financial_quarter
        from vnstock.core.llm import call_llm
        from config import models
    except Exception as exc:  # pragma: no cover
        job.error = f"Không import được vnstock modules: {exc}"
        job.status = "error"
        job.finished_at = time.time()
        return

    request = job.request
    portfolio = request.portfolio or portfolio_service.load_portfolio()
    year, q_num = get_latest_financial_quarter(datetime.now())
    quarter = f"Q{q_num}"

    _log(
        job,
        f"Bắt đầu phân tích {','.join(request.tickers)} | workflow={job.workflow} | "
        f"ref_date={job.ref_date} | financial={year}-{quarter}",
    )

    # ── Phase 0: sync prices + crawl news (best-effort) ────────────────────
    job.phase = "crawl"
    try:
        sync_res = await market_service.sync_prices_today_async(request.tickers)
        if sync_res.get("error"):
            _log(job, f"⚠️ Sync giá lỗi: {sync_res['error']}")
        else:
            synced = sync_res.get("synced") or []
            skipped = sync_res.get("skipped") or []
            _log(
                job,
                f"Sync giá xong: {len(synced)} mã mới (skip {len(skipped)}) "
                f"trong {sync_res.get('duration_s', 0)}s",
            )
    except Exception as exc:
        _log(job, f"⚠️ Sync giá raise: {exc}")

    try:
        news_res = await market_service.crawl_news_lite_async()
        if news_res.get("status") == "ok":
            _log(
                job,
                f"Crawl tin xong: +{news_res.get('added', 0)} bài "
                f"trong {news_res.get('duration_s', 0)}s",
            )
        else:
            _log(job, f"Crawl tin: {news_res.get('reason', 'unknown')}")
    except Exception as exc:
        _log(job, f"⚠️ Crawl tin raise: {exc}")

    # ── Resolve cached financial quarter per ticker ────────────────────────
    ticker_quarter: Dict[str, Tuple[int, int]] = {}
    for t in request.tickers:
        fy, fq = _find_latest_cached_quarter(t, year, q_num)
        ticker_quarter[t] = (fy, fq)
        if (fy, fq) != (year, q_num):
            _log(job, f"📁 {t}: dùng cached báo cáo {fy}-Q{fq} (mới hơn không có)")

    # ── Phase A: 5 agents per ticker, in parallel ──────────────────────────
    job.phase = "agents"
    macro_agent = MacroAgent()

    async def run_macro_once() -> None:
        # Mark every ticker's macro slot as running so the UI sees activity.
        for t in request.tickers:
            job.agents[(t, "macro")].status = "running"
        try:
            text = await macro_agent.analyze(ref_date=job.ref_date)
        except Exception as exc:
            for t in request.tickers:
                s = job.agents[(t, "macro")]
                s.status = "error"
                s.error = str(exc)
                s.output = f"❌ Macro agent lỗi: {exc}"
            return
        action, conf = _infer_action_from_text(text, "macro")
        clean = _strip_thinking(text)
        for t in request.tickers:
            s = job.agents[(t, "macro")]
            s.status = "completed"
            s.output = clean
            s.action = action
            s.confidence = conf

    async def run_simple(ticker: str, agent_name: str, coro_factory) -> None:
        s = job.agents[(ticker, agent_name)]
        s.status = "running"
        try:
            text = await coro_factory()
        except Exception as exc:
            s.status = "error"
            s.error = str(exc)
            s.output = f"❌ {agent_name} lỗi: {exc}"
            return
        action, conf = _infer_action_from_text(text, agent_name)
        s.status = "completed"
        s.output = _strip_thinking(text)
        s.action = action
        s.confidence = conf

    tasks: List[asyncio.Task] = [asyncio.create_task(run_macro_once())]
    for ticker in request.tickers:
        tech = TechnicalAgent()
        quant = QuantAgent()
        news = NewsAgent()
        fin = FinancialAgent()
        fy, fq = ticker_quarter[ticker]
        fy_s, fq_s = str(fy), f"Q{fq}"
        tasks.append(
            asyncio.create_task(
                run_simple(
                    ticker,
                    "technical",
                    lambda t=ticker: tech.analyze(ticker=t, ref_date=job.ref_date),
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                run_simple(
                    ticker,
                    "quant",
                    lambda t=ticker: quant.analyze(ticker=t, ref_date=job.ref_date),
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                run_simple(
                    ticker,
                    "news",
                    lambda t=ticker: news.analyze(ticker=t, ref_date=job.ref_date),
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                run_simple(
                    ticker,
                    "financial",
                    lambda t=ticker, y=fy_s, qq=fq_s: fin.analyze(
                        ticker=t, year=y, quarter=qq
                    ),
                )
            )
        )

    await asyncio.gather(*tasks, return_exceptions=True)
    _log(job, "Đã nhận đủ agent outputs.")

    # ── Phase A.5: workflow-specific quantitative logic ────────────────────
    # Traditional/Kelly/Markowitz make the final decision here (their own
    # scoring / Kelly fraction / mean-variance optimizer). Cognitive runs a
    # Bull/Bear/Judge debate whose result feeds the CIO in Phase B.
    job.phase = "workflow"
    run_cio = True
    try:
        run_cio = await _run_workflow_logic(job, portfolio)
    except Exception as exc:
        _log(job, f"⚠️ Workflow {job.workflow} lỗi: {exc} → fallback sang CIO thuần")
        run_cio = True

    # ── Phase B: CIO per ticker (cognitive, or fallback) ───────────────────
    if run_cio:
        job.phase = "cio"
        _log(job, "Bắt đầu CIO...")
        cio_tasks: List[asyncio.Task] = []
        for ticker in request.tickers:
            ticker_slots = [job.agents[(ticker, a)] for a in AGENT_NAMES]
            cio_tasks.append(
                asyncio.create_task(
                    _run_cio_into_job(
                        job=job,
                        ticker=ticker,
                        slots=ticker_slots,
                        portfolio=portfolio,
                        call_llm=call_llm,
                        model_id=models.t4_cio_model,
                    )
                )
            )
        await asyncio.gather(*cio_tasks, return_exceptions=True)
        _log(job, "CIO xong. Đang sinh báo cáo tổng hợp...")
    else:
        _log(
            job,
            f"Workflow {WORKFLOW_LABELS.get(job.workflow, job.workflow)} đã ra "
            f"quyết định trực tiếp (bỏ qua CIO). Đang sinh báo cáo...",
        )

    # ── Phase C: Markdown report ───────────────────────────────────────────
    job.phase = "report"
    try:
        report_md = await _build_report(
            request=request,
            workflow=job.workflow,
            ref_date=job.ref_date,
            slots=job.agents,
            cio_results=job.cio,
            portfolio=portfolio,
            call_llm=call_llm,
            model_id=models.daily_report_model,
            debate=job.debate,
        )
    except Exception as exc:
        report_md = _fallback_report(
            workflow=WORKFLOW_LABELS[job.workflow],
            ref_date=job.ref_date,
            tickers=request.tickers,
            cio_results=job.cio,
            error=str(exc),
        )
    job.report = report_md

    # ── Phase D: persist to history ────────────────────────────────────────
    analysis_id = _make_analysis_id(job.ref_date, request.tickers, job.workflow)
    snapshot = _serialize_history(
        analysis_id=analysis_id,
        request=request,
        workflow=job.workflow,
        ref_date=job.ref_date,
        slots=job.agents,
        cio_results=job.cio,
        report_md=report_md,
        debate=job.debate,
    )
    try:
        from services import history_service

        history_service.save_analysis(analysis_id, snapshot)
    except Exception as exc:
        _log(job, f"⚠️ Không lưu được history: {exc}")
    job.analysis_id = analysis_id

    job.phase = "done"
    job.status = "done"
    job.finished_at = time.time()


# ── Helpers (unchanged from the SSE version, only signatures cleaned up) ────


def _find_latest_cached_quarter(
    ticker: str, start_year: int, start_quarter: int
) -> Tuple[int, int]:
    """Walk backward until we find a cached financial report .md, fall back
    to (start_year, start_quarter) if nothing is on disk."""
    try:
        from vnstock.agents.financial_agent import ANALYSIS_ROOT
    except Exception:
        return start_year, start_quarter
    year, q = start_year, start_quarter
    for _ in range(12):
        p = ANALYSIS_ROOT / f"{ticker.upper()}_{year}_Q{q}.md"
        if p.exists():
            return year, q
        q -= 1
        if q <= 0:
            q = 4
            year -= 1
    return start_year, start_quarter


def _extract_predicted_impact_pct(text: str) -> Optional[float]:
    if not text:
        return None
    # LLM emits the impact in many wrappers: `: +2.5%`, `: **-0.5%**`,
    # ` (+13.3%)`, `: [+6%]`, ` +1.2%`. Stop at the first digit/sign that
    # follows the phrase, skipping any markdown / bracket noise in between.
    m = re.search(
        r"Dự đoán ảnh hưởng[^\n0-9+\-]*([+-]?\d+(?:[\.,]\d+)?)",
        text,
    )
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


_THINK_RE = re.compile(r"<thinking>.*?</thinking>\s*", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<thinking>\s*", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"\s*</thinking>", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove <thinking>…</thinking> chain-of-thought blocks from agent output.

    Keeps only the concise conclusion the user wants to read. Falls back to the
    original text if stripping would empty it (e.g. agent put everything inside
    the tag, or only an unmatched tag is present).
    """
    if not text or "<thinking>" not in text.lower():
        return text or ""
    cleaned = _THINK_RE.sub("", text)
    # Drop any dangling/unbalanced thinking tags too.
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    return cleaned or text.strip()


def _infer_action_from_text(text: str, agent: str) -> Tuple[Optional[str], Optional[float]]:
    if not text:
        return None, None

    json_match = re.search(r"\{[\s\S]*?\"action\"[\s\S]*?\}", text)
    if json_match:
        try:
            obj = json.loads(json_match.group(0))
            action = str(obj.get("action") or "").upper() or None
            conf_raw = obj.get("confidence_raw") or obj.get("confidence")
            confidence = None
            if conf_raw is not None:
                try:
                    cv = float(conf_raw)
                    confidence = cv / 100.0 if cv > 1 else cv
                except (TypeError, ValueError):
                    confidence = None
            if action:
                return action, confidence
        except Exception:
            pass

    impact = _extract_predicted_impact_pct(text)
    if impact is None:
        return None, None
    if impact >= 1.5:
        return "BUY", min(0.95, 0.55 + impact / 20.0)
    if impact <= -1.5:
        return "SELL", min(0.95, 0.55 + abs(impact) / 20.0)
    return "PASS", 0.5


def _portfolio_total_equity(portfolio: Dict[str, Any]) -> float:
    cash = float(portfolio.get("cash") or 0)
    pos_value = 0.0
    for p in portfolio.get("positions") or []:
        pos_value += float(p.get("quantity") or 0) * float(p.get("avg_price") or 0)
    return cash + pos_value


def _current_weight_pct(ticker: str, portfolio: Dict[str, Any]) -> float:
    total = _portfolio_total_equity(portfolio) or 1.0
    for p in portfolio.get("positions") or []:
        if (p.get("ticker") or "").upper() == ticker.upper():
            pv = float(p.get("quantity") or 0) * float(p.get("avg_price") or 0)
            return round(100.0 * pv / total, 2)
    return 0.0


def _build_workflow_inputs(
    job: _Job, portfolio: Dict[str, Any]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """_AgentSlot → {ticker: {agent_name: AgentOutput}} + portfolio snapshot."""
    from vnstock.workflows.base import AgentOutput

    by_ticker: Dict[str, Dict[str, Any]] = {}
    for ticker in job.request.tickers:
        outs: Dict[str, Any] = {}
        for agent_name in AGENT_NAMES:
            slot = job.agents[(ticker, agent_name)]
            outs[agent_name] = AgentOutput(
                agent_name=agent_name,
                raw_analysis=slot.output or "",
                signal=(slot.action or "neutral"),
                confidence=float(slot.confidence if slot.confidence is not None else 0.5),
            )
        by_ticker[ticker] = outs
    snapshot = {
        "cash": float(portfolio.get("cash") or 0),
        "positions": list(portfolio.get("positions") or []),
        "total_equity": _portfolio_total_equity(portfolio),
    }
    return by_ticker, snapshot


def _workflow_decision_to_cio(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy workflow `.decision` dict → app's job.cio entry shape.

    `final_score` is the debate's normalized *bullish probability* (0..1), not a
    confidence. Translate it into a recommendation confidence that depends on
    the chosen action so the UI shows a sensible number:
      - BUY/BUY_MORE  → confidence == bullish prob (high prob = confident buy)
      - SELL/TRIMMING → confidence == 1 - bullish prob
      - PASS/HOLD     → certainty of "no strong edge" = 0.5 + |prob - 0.5|
    IGNORE (no position + weak signal) is surfaced as PASS for UI consistency.
    """
    fs = decision.get("final_score")
    prob = float(fs) if isinstance(fs, (int, float)) else 0.5
    prob = max(0.0, min(1.0, prob))

    action = str(decision.get("action") or "PASS").upper()
    if action == "IGNORE":
        action = "PASS"

    if action in ("BUY", "BUY_MORE"):
        conf = prob
    elif action in ("SELL", "TRIMMING"):
        conf = 1.0 - prob
    else:  # PASS / HOLD
        conf = 0.5 + abs(prob - 0.5)
    conf = max(0.05, min(0.95, round(conf, 2)))

    verdict = decision.get("verdict")
    net = decision.get("net_score")
    return {
        "action": action,
        "weight_pct": float(decision.get("weight_pct") or 0),
        "confidence": conf,
        "reasoning": str(
            decision.get("reasoning") or verdict or "Quyết định từ workflow."
        ),
        "debate_summary": (
            f"Debate verdict: {verdict or 'N/A'}"
            + (f" | net_score: {net}" if net is not None else "")
            + f" | P(bullish)≈{prob:.2f}"
        ),
    }


async def _run_workflow_logic(job: _Job, portfolio: Dict[str, Any]) -> bool:
    """Phase A.5 router. Returns True if Phase B (LLM CIO) should still run.

    - traditional/kelly: per-ticker workflow.run() → job.cio[ticker]; return False.
    - markowitz: basket-level optimizer → job.cio per ticker; return False.
    - cognitive: Bull/Bear/Judge debate per ticker → job.debate; return True.
    """
    by_ticker, snapshot = _build_workflow_inputs(job, portfolio)
    wf_name = job.workflow

    if wf_name in ("traditional", "kelly"):
        if wf_name == "traditional":
            from vnstock.workflows.traditional_scoring import (
                TraditionalScoringWorkflow as WF,
            )
        else:
            from vnstock.workflows.kelly_criterion import KellyCriterionWorkflow as WF
        async def _run_one(ticker: str) -> None:
            try:
                # New WF() per ticker — the internal autogen debate keeps state,
                # so a shared instance is not safe under asyncio.gather.
                res = await WF().run(
                    ticker=ticker,
                    ref_date=job.ref_date,
                    agent_outputs=by_ticker[ticker],
                    current_weight_pct=_current_weight_pct(ticker, portfolio),
                    portfolio_snapshot=snapshot,
                )
                dec = res.get("decision") or {}
                job.cio[ticker] = _workflow_decision_to_cio(dec)
                # Traditional/Kelly run an internal Bull/Bear autogen debate;
                # surface its transcript so the UI/report shows the debate.
                transcript = str(res.get("transcript") or "").strip()
                if transcript:
                    prob = dec.get("final_score")
                    job.debate[ticker] = {
                        "triggered": True,
                        "verdict": dec.get("verdict"),
                        "winner": (
                            "bull"
                            if isinstance(prob, (int, float)) and prob > 0.5
                            else "bear"
                            if isinstance(prob, (int, float)) and prob < 0.5
                            else "tie"
                        ),
                        "confidence": round(
                            (float(prob) if isinstance(prob, (int, float)) else 0.5)
                            * 100.0,
                            1,
                        ),
                        "summary": transcript[:3000],
                        "judge_rationale": str(dec.get("verdict") or ""),
                    }
                _log(job, f"✅ {wf_name} quyết định {ticker}: {job.cio[ticker]['action']}")
            except Exception as exc:
                _log(job, f"⚠️ {wf_name} lỗi {ticker}: {exc}")
                job.cio[ticker] = {
                    "action": "PASS", "weight_pct": 0.0, "confidence": 0.4,
                    "reasoning": f"{wf_name} workflow lỗi: {exc}", "debate_summary": "",
                }

        # All tickers in parallel (each its own debate + CIO).
        await asyncio.gather(
            *[_run_one(t) for t in job.request.tickers], return_exceptions=True
        )
        return False

    if wf_name == "markowitz":
        from vnstock.workflows.markowitz_frontier import MarkowitzFrontierWorkflow

        wf = MarkowitzFrontierWorkflow()
        try:
            res = await wf.run(
                tickers=job.request.tickers,
                ref_date=job.ref_date,
                agent_outputs_map=by_ticker,
                current_weights={
                    t: _current_weight_pct(t, portfolio) for t in job.request.tickers
                },
                portfolio_snapshot=snapshot,
            )
            dec = res.get("decision") or {}
            basket = dec.get("basket") or []
            reasoning = dec.get("reasoning") or "Tối ưu Markowitz mean-variance."
            sharpe = float((dec.get("optimizer") or {}).get("sharpe_ratio") or 0.0)
            conf = round(max(0.1, min(0.95, 0.5 + sharpe / 4.0)), 2)
            for ticker in job.request.tickers:
                entry = next(
                    (b for b in basket if (b.get("ticker") or "").upper() == ticker),
                    None,
                )
                if entry and float(entry.get("weight_pct") or 0) > 0:
                    job.cio[ticker] = {
                        "action": str(entry.get("action") or "BUY").upper(),
                        "weight_pct": float(entry.get("weight_pct") or 0),
                        "confidence": conf,
                        "reasoning": reasoning,
                        "debate_summary": "",
                    }
                else:
                    job.cio[ticker] = {
                        "action": "PASS", "weight_pct": 0.0, "confidence": conf,
                        "reasoning": "Không nằm trong danh mục tối ưu Markowitz.",
                        "debate_summary": "",
                    }
            _log(job, f"✅ Markowitz: {len(basket)} mã trong rổ tối ưu (Sharpe={sharpe:.2f})")
        except Exception as exc:
            _log(job, f"⚠️ Markowitz lỗi: {exc}")
            for ticker in job.request.tickers:
                job.cio[ticker] = {
                    "action": "PASS", "weight_pct": 0.0, "confidence": 0.4,
                    "reasoning": f"Markowitz lỗi: {exc}", "debate_summary": "",
                }
        return False

    # cognitive → debate, then let Phase B CIO consume it
    try:
        from cognitive_trading.config import CognitiveConfig
        from cognitive_trading.decision.debate_engine import DebateEngine
        from cognitive_trading.governance.schemas import AnalysisCard
    except Exception as exc:
        _log(job, f"⚠️ Không load được DebateEngine: {exc} (chạy CIO thuần)")
        return True

    try:
        DebateEngine(config=CognitiveConfig())  # smoke-test init
    except Exception as exc:
        _log(job, f"⚠️ Init DebateEngine lỗi: {exc} (chạy CIO thuần)")
        return True

    job.debate = {}

    async def _debate_one(ticker: str) -> None:
        cards = []
        for agent_name in AGENT_NAMES:
            slot = job.agents[(ticker, agent_name)]
            if slot.status != "completed" or not slot.output:
                continue
            impact = _extract_predicted_impact_pct(slot.output) or 0.0
            action_str = slot.action or (
                "BUY" if impact > 0 else "SELL" if impact < 0 else "PASS"
            )
            try:
                cards.append(
                    AnalysisCard(
                        agent_name=agent_name,
                        ticker=ticker,
                        ref_date=job.ref_date,
                        action=action_str,
                        confidence_raw=max(
                            0.0, min(100.0, float(slot.confidence or 0.5) * 100.0)
                        ),
                        upside_pct=max(impact, 0.0),
                        downside_pct=max(-impact, 0.0),
                        reasoning=(slot.output or "")[:2000]
                        or f"{agent_name} output rỗng",
                    )
                )
            except Exception as exc:
                _log(job, f"⚠️ Card {ticker}/{agent_name} lỗi: {exc}")
        if len(cards) < 2:
            _log(job, f"⚠️ {ticker}: <2 card hợp lệ, bỏ qua debate")
            return
        try:
            # New engine per ticker — autogen GroupChat keeps state, not safe
            # to share across parallel debates.
            dr = await DebateEngine(config=CognitiveConfig()).debate(
                ticker=ticker,
                ref_date=job.ref_date,
                cards=cards,
                portfolio_snapshot=snapshot,
            )
            job.debate[ticker] = {
                "triggered": bool(dr.triggered),
                "verdict": dr.verdict,
                "winner": dr.winner,
                "confidence": float(dr.confidence),
                "summary": dr.summary,
                "judge_rationale": dr.judge_rationale,
            }
            _log(
                job,
                f"⚔️ Debate {ticker}: triggered={dr.triggered} "
                f"winner={dr.winner} verdict={dr.verdict} conf={dr.confidence:.0f}",
            )
        except Exception as exc:
            _log(job, f"⚠️ Debate {ticker} lỗi: {exc}")

    # All tickers debate in parallel.
    await asyncio.gather(
        *[_debate_one(t) for t in job.request.tickers], return_exceptions=True
    )
    return True


async def _run_cio_into_job(
    *,
    job: _Job,
    ticker: str,
    slots: List[_AgentSlot],
    portfolio: Dict[str, Any],
    call_llm,
    model_id: str,
) -> None:
    """Synthesize 5 agent outputs into action/weight/confidence/reasoning."""

    pos_lookup = {p["ticker"]: p for p in (portfolio.get("positions") or [])}
    holding = pos_lookup.get(ticker)
    holding_text = (
        f"Đang nắm: {holding['quantity']} cp @ giá TB {holding['avg_price']:,.0f} VND."
        if holding
        else "Hiện chưa có vị thế."
    )

    agent_section = "\n\n".join(
        f"### {s.agent.upper()} ({'❌ ' + (s.error or '') if s.status == 'error' else 'OK'})\n"
        f"action: {s.action or 'N/A'} | confidence: {s.confidence if s.confidence is not None else 'N/A'}\n\n"
        f"{(s.output or '').strip()[:2500]}"
        for s in slots
    )

    workflow_hint = {
        "traditional": "Bạn theo trường phái Traditional Scoring (alpha + RSI + P/E weighted).",
        "kelly": "Bạn theo trường phái Kelly Criterion: tối ưu kích thước vị thế dựa trên xác suất thắng và payoff.",
        "markowitz": "Bạn theo trường phái Markowitz Mean-Variance: cân nhắc tương quan và rủi ro toàn danh mục.",
        "cognitive": "Bạn là CIO của hệ Cognitive Swarm: dung hoà debate Bull/Bear, ưu tiên evidence-based reasoning.",
    }[job.workflow]

    system_prompt = (
        "Bạn là CIO (Chief Investment Officer) của một hệ multi-agent đầu tư chứng khoán Việt Nam. "
        f"{workflow_hint} "
        "Tổng hợp 5 báo cáo agent dưới đây để ra quyết định cuối cùng cho 1 mã. "
        "TRẢ DUY NHẤT MỘT JSON OBJECT (không markdown, không văn bản kèm) với schema:\n"
        '{"action": "BUY"|"BUY_MORE"|"SELL"|"TRIMMING"|"PASS"|"HOLD",'
        ' "weight_pct": 0-15 (số % NAV mục tiêu, đặt 0 nếu PASS/HOLD),'
        ' "confidence": 0-1,'
        ' "reasoning": "<3-6 câu tiếng Việt giải thích quyết định>",'
        ' "debate_summary": "<2-4 câu tóm tắt Bull vs Bear>"}\n'
        "Nguyên tắc: nếu các agent xung đột → confidence thấp, ưu tiên PASS. "
        "Nếu đã nắm vị thế và tín hiệu tiêu cực mạnh → SELL hoặc TRIMMING. "
        "Tuyệt đối không đề xuất weight_pct vượt 15%."
    )

    debate_block = ""
    dbt = job.debate.get(ticker) if job.debate else None
    if dbt:
        debate_block = (
            "\n\n=== KẾT QUẢ TRANH BIỆN BULL/BEAR (Debate Engine) ===\n"
            f"Triggered: {dbt.get('triggered')} | Winner: {dbt.get('winner')} | "
            f"Verdict: {dbt.get('verdict')} | Confidence: {dbt.get('confidence')}\n"
            f"Tóm tắt: {dbt.get('summary') or 'N/A'}\n"
            f"Lập luận trọng tài: {dbt.get('judge_rationale') or 'N/A'}\n"
            "=== END DEBATE ===\n"
            "Hãy coi kết quả debate là tín hiệu quan trọng: nếu debate winner=bear/verdict=sell "
            "→ nghiêng PASS/SELL; nếu bull thắng rõ với confidence cao → có thể BUY."
        )

    user_prompt = (
        f"Ticker: {ticker}\nNgày phân tích: {job.ref_date}\nWorkflow: {job.workflow}\n"
        f"Trạng thái danh mục với mã này: {holding_text}\n\n"
        f"=== AGENT OUTPUTS ===\n{agent_section}\n=== END AGENT OUTPUTS ==="
        f"{debate_block}"
    )

    fallback = {
        "action": "PASS",
        "weight_pct": 0.0,
        "confidence": 0.5,
        "reasoning": "CIO không có đủ dữ liệu hoặc gọi LLM thất bại — giữ nguyên trạng.",
        "debate_summary": "",
    }

    try:
        raw = await call_llm(system_prompt, user_prompt, model=model_id, temperature=0.2)
    except Exception as exc:  # noqa: BLE001
        fallback["reasoning"] = f"CIO LLM lỗi: {exc}. Mặc định PASS."
        job.cio[ticker] = fallback
        return

    job.cio[ticker] = _safe_parse_cio(raw, fallback)


def _safe_parse_cio(raw: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not raw:
        return fallback
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if not obj_match:
        return fallback
    try:
        obj = json.loads(obj_match.group(0))
    except Exception:
        return fallback
    action = str(obj.get("action", fallback["action"])).upper()
    if action not in {"BUY", "BUY_MORE", "SELL", "TRIMMING", "PASS", "HOLD"}:
        action = "PASS"
    try:
        weight = float(obj.get("weight_pct", fallback["weight_pct"]))
    except (TypeError, ValueError):
        weight = 0.0
    weight = max(0.0, min(15.0, weight))
    if action in {"PASS", "HOLD"}:
        weight = 0.0
    try:
        conf = float(obj.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        conf = fallback["confidence"]
    if conf > 1:
        conf = conf / 100.0
    conf = max(0.0, min(1.0, conf))
    reasoning = str(obj.get("reasoning") or fallback["reasoning"]).strip()
    debate = str(obj.get("debate_summary") or "").strip()
    return {
        "action": action,
        "weight_pct": round(weight, 2),
        "confidence": round(conf, 3),
        "reasoning": reasoning,
        "debate_summary": debate,
    }


async def _build_report(
    *,
    request: AnalysisRequest,
    workflow: str,
    ref_date: str,
    slots: Dict[Tuple[str, str], _AgentSlot],
    cio_results: Dict[str, Dict[str, Any]],
    portfolio: Dict[str, Any],
    call_llm,
    model_id: str,
    debate: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    workflow_label = WORKFLOW_LABELS[workflow]
    debate = debate or {}
    sections = []
    for ticker in request.tickers:
        agent_dump = "\n\n".join(
            f"#### {a.upper()}\n{(slots[(ticker, a)].output or '').strip()[:1800]}"
            for a in AGENT_NAMES
        )
        cio = cio_results.get(ticker, {})
        dbt = debate.get(ticker)
        debate_txt = ""
        if dbt:
            debate_txt = (
                f"\nDEBATE: winner={dbt.get('winner')} verdict={dbt.get('verdict')} "
                f"conf={dbt.get('confidence')} | {dbt.get('summary') or ''}"
            )
        sections.append(
            f"### {ticker}\nCIO action={cio.get('action')} weight={cio.get('weight_pct')}% conf={cio.get('confidence')}\n"
            f"Reasoning: {cio.get('reasoning')}{debate_txt}\n\n"
            f"{agent_dump}"
        )
    payload = "\n\n---\n\n".join(sections)
    portfolio_summary = _portfolio_summary_text(portfolio)

    system_prompt = (
        "BẠN LÀ CHUYÊN GIA PHÂN TÍCH TÀI CHÍNH CỦA HỆ THỐNG MULTI-AGENT HỖ TRỢ "
        "PHÂN TÍCH VÀ ĐẦU TƯ CHỨNG KHOÁN. Hãy tổng hợp kết quả phân tích từ 5 agent "
        "(macro, technical, quant, news, financial) và quyết định CIO để viết báo cáo "
        "Markdown tiếng Việt theo đúng cấu trúc dưới đây. Không bịa số liệu, chỉ rút trích từ dữ liệu cung cấp.\n"
        "QUAN TRỌNG: Người dùng đã có một DANH MỤC THỰC TẾ (tiền mặt + cổ phiếu đang nắm). "
        "Báo cáo PHẢI thể hiện rõ bạn biết danh mục này:\n"
        "- Với mã ĐANG NẮM: nêu số lượng, giá vốn, giá hiện tại, lãi/lỗ (%), và khuyến nghị "
        "GIỮ / MUA THÊM / CHỐT LỜI / CẮT LỖ phù hợp với vị thế + tín hiệu agent.\n"
        "- Với mã CHƯA NẮM: cân nhắc có nên mở vị thế mới không, và quy mô bao nhiêu so với "
        "tiền mặt khả dụng (không đề xuất vượt quá tiền mặt).\n"
        "- Đánh giá mức độ phân bổ/tập trung của danh mục và rủi ro tương ứng."
    )

    structure = (
        f"# 📊 Báo cáo phân tích ngày {ref_date}\n"
        f"## Mã: {', '.join(request.tickers)} | Workflow: {workflow_label}\n\n"
        "## 1. Tổng quan thị trường\n"
        "## 2. Phân tích kỹ thuật & định lượng\n"
        "## 3. Phân tích cơ bản\n"
        "## 4. Tin tức & Sentiment\n"
        "## 5. Đánh giá danh mục hiện tại\n"
        "(Bảng/đoạn: từng mã đang nắm — số lượng, giá vốn, giá hiện tại, lãi/lỗ %, "
        "nhận định nên giữ/mua thêm/chốt lời/cắt lỗ. Tổng quan tiền mặt & mức tập trung.)\n"
        "## 6. Quyết định đầu tư\n"
        "(Quyết định CIO/workflow cho từng mã, gắn với vị thế hiện có.)\n"
        "## 7. Khuyến nghị hành động\n"
        "(Danh sách lệnh cụ thể: MUA/BÁN/GIỮ mã nào, khối lượng gợi ý, dùng bao nhiêu "
        "tiền mặt, ưu tiên theo độ tin cậy. Phải nhất quán với danh mục đang có.)\n"
        f"\n---\n*Báo cáo được tạo bởi hệ thống Multi-Agent AI | {workflow_label} workflow*"
    )

    user_prompt = (
        f"Hãy viết báo cáo theo đúng skeleton sau (giữ nguyên tiêu đề, điền nội dung cô đọng, có dẫn chứng):\n\n"
        f"{structure}\n\n"
        f"=== DANH MỤC THỰC TẾ CỦA NGƯỜI DÙNG (đã định giá theo giá mới nhất) ===\n"
        f"{portfolio_summary}\n\n"
        f"=== KẾT QUẢ PHÂN TÍCH PER TICKER ===\n{payload}"
    )

    return await call_llm(system_prompt, user_prompt, model=model_id, temperature=0.3)


def _portfolio_summary_text(portfolio: Dict[str, Any]) -> str:
    cash = float(portfolio.get("cash") or 0.0)
    positions = portfolio.get("positions") or []
    if not positions:
        return (
            f"Tiền mặt khả dụng: {cash:,.0f} VND. Chưa nắm cổ phiếu nào "
            "(toàn bộ là tiền mặt)."
        )

    price_map: Dict[str, float] = {}
    try:
        price_map = market_service.get_latest_prices([p["ticker"] for p in positions])
    except Exception:
        price_map = {}

    lines = [f"Tiền mặt khả dụng: {cash:,.0f} VND.", "Cổ phiếu đang nắm giữ:"]
    stock_value = 0.0
    invested_total = 0.0
    for p in positions:
        tk = p["ticker"]
        qty = int(p["quantity"])
        avg = float(p["avg_price"])
        cur = float(price_map.get(tk, 0.0) or 0.0)
        mv = cur * qty
        invested = avg * qty
        pnl = mv - invested
        pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0
        stock_value += mv
        invested_total += invested
        cur_txt = f"{cur:,.0f}" if cur > 0 else "N/A"
        lines.append(
            f"- {tk}: {qty} cp | giá vốn {avg:,.0f} | giá hiện tại {cur_txt} VND "
            f"| giá trị {mv:,.0f} VND | lãi/lỗ {pnl:+,.0f} VND ({pnl_pct:+.2f}%)"
        )
    total_nav = cash + stock_value
    total_pnl = stock_value - invested_total
    lines.append(
        f"Tổng quan: NAV ≈ {total_nav:,.0f} VND "
        f"(tiền mặt {cash:,.0f} + cổ phiếu {stock_value:,.0f}); "
        f"tổng lãi/lỗ tạm tính {total_pnl:+,.0f} VND. "
        f"Tỷ trọng tiền mặt ≈ {((cash / total_nav * 100.0) if total_nav else 0):.1f}% NAV."
    )
    return "\n".join(lines)


def _fallback_report(
    *,
    workflow: str,
    ref_date: str,
    tickers: List[str],
    cio_results: Dict[str, Dict[str, Any]],
    error: str,
) -> str:
    body = [
        f"# 📊 Báo cáo phân tích ngày {ref_date}",
        f"## Mã: {', '.join(tickers)} | Workflow: {workflow}",
        "",
        f"> ⚠️ LLM tổng hợp lỗi: {error}. Hiển thị bản tóm tắt từ CIO.",
        "",
        "## 5. Quyết định đầu tư",
    ]
    for t in tickers:
        c = cio_results.get(t, {})
        body.append(
            f"- **{t}** → `{c.get('action')}` weight={c.get('weight_pct')}% "
            f"conf={c.get('confidence')}\n  > {c.get('reasoning')}"
        )
    body.append("")
    body.append(f"---\n*Báo cáo được tạo bởi hệ thống Multi-Agent AI | {workflow} workflow*")
    return "\n".join(body)


def _make_analysis_id(ref_date: str, tickers: List[str], workflow: str) -> str:
    ts = datetime.now().strftime("%H%M%S")
    return f"{ref_date}_{'-'.join(tickers)}_{workflow}_{ts}"


def _serialize_history(
    *,
    analysis_id: str,
    request: AnalysisRequest,
    workflow: str,
    ref_date: str,
    slots: Dict[Tuple[str, str], _AgentSlot],
    cio_results: Dict[str, Dict[str, Any]],
    report_md: str,
    debate: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    agents_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for ticker in request.tickers:
        agents_by_ticker[ticker] = []
        for agent_name in AGENT_NAMES:
            s = slots.get((ticker, agent_name))
            if not s:
                continue
            agents_by_ticker[ticker].append(
                {
                    "agent": s.agent,
                    "ticker": s.ticker,
                    "status": s.status,
                    "output": s.output,
                    "confidence": s.confidence,
                    "action": s.action,
                    "error": s.error,
                }
            )

    summary_parts = []
    for t in request.tickers:
        c = cio_results.get(t, {})
        confidence = c.get("confidence")
        conf_text = f"{round((confidence or 0) * 100)}%" if confidence is not None else "?"
        summary_parts.append(f"{c.get('action', '?')} {t} (conf {conf_text})")
    summary = "; ".join(summary_parts)

    return {
        "id": analysis_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ref_date": ref_date,
        "tickers": request.tickers,
        "workflow": workflow,
        "summary": summary,
        "agents": agents_by_ticker,
        "cio": cio_results,
        "debate": debate or {},
        "report": report_md,
    }
