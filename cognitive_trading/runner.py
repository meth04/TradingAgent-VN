"""Standalone CLI and daily backtest loop for the independent cognitive_trading system."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from vnstock.tools.backtest.trading_calendar import iter_trading_days, previous_trading_day

from pydantic import ValidationError

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.decision.cio_agent import CIOAgent
from cognitive_trading.decision.debate_engine import DebateEngine, DebateResult
from cognitive_trading.decision.debate_trigger import should_trigger_debate
from cognitive_trading.decision.risk_kernel import RiskKernel, infer_sector
from cognitive_trading.governance import (
    ARTIFACT_VERSION,
    AnalysisCard,
    ConfidenceCalibrator,
    NormalizedAgentArtifact,
    SchemaValidator,
    WorkflowArtifactEnvelope,
    WorkflowTickerArtifact,
)
from cognitive_trading.memory import (
    CognitiveDB,
    EpisodicStore,
    PromotionEngine,
    ReflectionAgent,
    StrategyStore,
    init_memory_db,
)
from cognitive_trading.planner import ContextPacker, EventLedgerBuilder, PlannerAgent, PlannerDecision
from cognitive_trading.reporting.daily_reporter import DailyReporter
from cognitive_trading.swarm import (
    FinancialAnalyst,
    MacroAnalyst,
    NewsAnalyst,
    QuantAnalyst,
    TechnicalAnalyst,
)
from vnstock.agents.prompting import Action
from vnstock.core import llm as llm_core
from vnstock.core.llm import LLMError
from vnstock.core.timing import Timer
from vnstock.database.repo import DataRepository
from vnstock.tools.backtest.benchmark import BenchmarkAnalyzer
from vnstock.tools.backtest.portfolio import BUY_FEE_RATE, LOT_SIZE, Portfolio, Position
from vnstock.tools.market_tool import MarketToolkit
from vnstock.tools.quant_tool import QuantToolkit
from vnstock.tools.search_tool import SearchToolkit

try:
    from tracking_news.app.summarizer import close_session as news_close_session
except ImportError:  # pragma: no cover - defensive import guard
    async def news_close_session() -> None:
        return None


@dataclass(frozen=True, slots=True)
class TickerOutcome:
    """Per-ticker artifacts produced before trade execution."""

    ticker: str
    sector: str
    planner_decision: PlannerDecision
    cards: tuple[AnalysisCard, ...]
    debate_result: DebateResult
    intent: Any
    order_ticket: Any


class CognitiveBacktestRunner:
    """Execute the standalone cognitive_trading daily loop and persist frontend-ready outputs."""

    def __init__(self, *, config: CognitiveConfig | None = None) -> None:
        self.config = config or CognitiveConfig()
        self.repo = DataRepository()
        self.quant_toolkit = QuantToolkit()
        self.cognitive_db = CognitiveDB(db_path=self.config.memory_db_path, config=self.config)
        self.ledger_builder = EventLedgerBuilder(
            repo=self.repo,
            search_toolkit=SearchToolkit,
            market_toolkit=MarketToolkit,
            quant_toolkit=self.quant_toolkit,
        )
        self.planner = PlannerAgent()
        self.schema_validator = SchemaValidator(config=self.config)
        self.calibrator = ConfidenceCalibrator(
            db_path=self.config.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )
        self.episodic_store = EpisodicStore(
            db_path=self.config.memory_db_path,
            config=self.config,
            repo=self.repo,
            cognitive_db=self.cognitive_db,
        )
        self.context_packer = ContextPacker(
            search_toolkit=SearchToolkit,
            market_toolkit=MarketToolkit,
            quant_toolkit=self.quant_toolkit,
            episodic_store=self.episodic_store,
        )
        self.debate_engine = DebateEngine(config=self.config)
        self.cio_agent = CIOAgent(
            config=self.config,
            memory_db_path=self.config.memory_db_path,
            cognitive_db=self.cognitive_db,
        )
        self.risk_kernel = RiskKernel(config=self.config, repo=self.repo)
        self.daily_reporter = DailyReporter(config=self.config)
        self.reflection_agent = ReflectionAgent(
            db_path=self.config.memory_db_path,
            config=self.config,
            repo=self.repo,
            episodic_store=self.episodic_store,
            cognitive_db=self.cognitive_db,
        )
        self.promotion_engine = PromotionEngine(
            db_path=self.config.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )
        self.strategy_store = StrategyStore(
            db_path=self.config.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )
        self.analysts = {
            "macro": MacroAnalyst(search_toolkit=SearchToolkit, config=self.config),
            "technical": TechnicalAnalyst(quant_toolkit=self.quant_toolkit, config=self.config),
            "quant": QuantAnalyst(quant_toolkit=self.quant_toolkit, config=self.config),
            "news": NewsAnalyst(search_toolkit=SearchToolkit, config=self.config),
            "financial": FinancialAnalyst(config=self.config),
        }

    async def close(self) -> None:
        """Release shared DB and session resources."""

        try:
            self.reflection_agent.close()
        except Exception:
            pass
        try:
            self.cognitive_db.close()
        except Exception:
            pass
        try:
            self.repo.close()
        except Exception:
            pass
        try:
            self.quant_toolkit.close()
        except Exception:
            pass
        try:
            await llm_core.close_session()
        except Exception:
            pass
        try:
            await news_close_session()
        except Exception:
            pass

    async def run(self, *, tickers: Sequence[str], start: str, end: str) -> list[dict[str, Any]]:
        """Run the cognitive_trading backtest and return the updated equity curve."""

        Timer.reset(prefix="cognitive.")
        self._prepare_output_root()
        init_memory_db(self.config.memory_db_path)

        portfolio = Portfolio.load_state(self.config.state_dir / "portfolio.json")
        equity_curve = self._load_json(self.config.equity_curve_path, default=[])
        if not isinstance(equity_curve, list):
            equity_curve = []

        completed_dates = self._completed_dates()
        effective_start = self._effective_start_date(
            requested_start=start,
            completed_dates=completed_dates,
        )
        if effective_start != start:
            print(
                f"[cognitive.resume] detected incomplete/interrupted tail before {start}; rerunning from {effective_start} first."
            )
        start = effective_start

        portfolio, equity_curve = self._restore_resume_state(
            requested_start=start,
            completed_dates=completed_dates,
            default_portfolio=portfolio,
            default_equity_curve=equity_curve,
        )
        persisted_last_date = str(equity_curve[-1]["date"]) if equity_curve else portfolio.last_date

        benchmark_data = self._load_benchmark_data(start, end)

        requested_tickers = [ticker.upper() for ticker in tickers]
        for trade_date in iter_trading_days(start, end):
            day_timer_snapshot = Timer.snapshot()
            if persisted_last_date and trade_date <= persisted_last_date:
                continue

            portfolio.rollover_day()
            active_tickers = sorted({*requested_tickers, *portfolio.positions.keys()})
            with Timer.track("cognitive.event_ledger"):
                event_ledger = await self.ledger_builder.build(active_tickers, trade_date)
            price_map = self._price_map_from_ledger(event_ledger)
            if not price_map:
                continue

            day_dir = self.config.daily_dir / trade_date
            self._ensure_dir(day_dir)
            self._ensure_dir(day_dir / "analysis")
            self._ensure_dir(day_dir / "trades")
            self._ensure_dir(day_dir / "risk")
            self._ensure_dir(day_dir / "normalized")
            self._persist_run_status(trade_date=trade_date, status="started")

            stop_loss_trades = self._execute_stop_loss_orders(
                portfolio=portfolio,
                price_map=price_map,
                trade_date=trade_date,
            )
            stop_loss_tickers = {
                str(item.get("ticker") or "").upper()
                for item in stop_loss_trades
                if str(item.get("status") or "") == "APPROVED"
            }

            with Timer.track("cognitive.context_packer"):
                self.context_packer.portfolio_context_provider = lambda ticker: self.risk_kernel.enrich_portfolio_snapshot(
                    portfolio=portfolio,
                    ticker=ticker,
                    price_map=price_map,
                )
                contexts = await self.context_packer.pack(event_ledger, trade_date)
                if stop_loss_tickers:
                    contexts = {
                        ticker: context
                        for ticker, context in contexts.items()
                        if ticker.upper() not in stop_loss_tickers
                    }
            with Timer.track("cognitive.collect_outcomes"):
                outcomes = await self._collect_outcomes(
                    trade_date=trade_date,
                    contexts=contexts,
                    portfolio=portfolio,
                    price_map=price_map,
                )

            trade_results: list[dict[str, Any]] = list(stop_loss_trades)
            blocked_orders: list[dict[str, Any]] = []
            approved_stop_loss_count = sum(
                1 for item in stop_loss_trades if str(item.get("status") or "") == "APPROVED"
            )
            for ticker in sorted(stop_loss_tickers):
                blocked_orders.append(
                    {
                        "ticker": ticker,
                        "status": "BLOCKED",
                        "action": Action.BUY.value,
                        "block_reason": "Ticker hit stop-loss earlier in the same session; re-entry deferred until next trading day.",
                    }
                )
            execution_order = self._execution_order(outcomes)
            for outcome in execution_order:
                if approved_stop_loss_count >= 2 and outcome.intent.action in {Action.BUY, Action.BUY_MORE}:
                    trade_result = {
                        "ticker": outcome.ticker,
                        "date": trade_date,
                        "action": outcome.intent.action.value,
                        "price": round(float(price_map.get(outcome.ticker, 0.0) or 0.0), 4) if float(price_map.get(outcome.ticker, 0.0) or 0.0) > 0 else None,
                        "quantity": 0,
                        "total_cost": 0.0,
                        "weight_pct": round(float(outcome.intent.weight_pct), 4),
                        "confidence": round(float(outcome.intent.confidence), 4),
                        "status": "BLOCKED",
                        "reasoning": outcome.intent.reasoning,
                        "playbook_id": outcome.intent.playbook_id,
                        "debate_triggered": bool(outcome.debate_result.triggered),
                        "block_reason": "Multiple stop-losses executed earlier in the same session; new long entries deferred until next trading day.",
                        "planner_classification": outcome.planner_decision.classification,
                        "order_source": "cio",
                    }
                else:
                    trade_result = self._execute_outcome(
                        outcome=outcome,
                        portfolio=portfolio,
                        price_map=price_map,
                        trade_date=trade_date,
                    )
                trade_results.append(trade_result)
                if trade_result.get("status") == "BLOCKED":
                    blocked_orders.append(trade_result)

            risk_report = self.risk_kernel.build_risk_report(
                portfolio=portfolio,
                price_map=price_map,
                blocked_orders=blocked_orders,
            )
            risk_report["stop_loss_orders_executed"] = stop_loss_trades

            nav = float(portfolio.equity(price_map))
            previous_nav = float(equity_curve[-1]["equity"]) if equity_curve else self.config.start_cash_vnd
            daily_return_pct = ((nav - previous_nav) / previous_nav * 100.0) if previous_nav > 0 else 0.0
            portfolio.equity_history.append(nav)
            portfolio.last_date = trade_date
            equity_point = {
                "date": trade_date,
                "equity": round(nav, 4),
                "cash": round(float(portfolio.cash), 4),
                "return_pct": round(((nav - self.config.start_cash_vnd) / self.config.start_cash_vnd) * 100.0, 4),
            }
            equity_curve.append(equity_point)

            analysis_payloads = self._analysis_payloads(outcomes)
            planner_output = {ticker: payload["planner"] for ticker, payload in analysis_payloads.items()}
            day_summary = self._build_day_summary(
                trade_date=trade_date,
                portfolio=portfolio,
                price_map=price_map,
                trade_results=trade_results,
                analysis_payloads=analysis_payloads,
                risk_report=risk_report,
                daily_return_pct=daily_return_pct,
            )

            day_summary["timing"] = Timer.summary_since(day_timer_snapshot, prefix="cognitive.")
            normalized_envelope = self._build_normalized_envelope(
                trade_date=trade_date,
                day_summary=day_summary,
                portfolio=portfolio,
                analysis_payloads=analysis_payloads,
                trade_results=trade_results,
                risk_report=risk_report,
                equity_curve=equity_curve,
            )
            active_playbooks = self.strategy_store.list_active()
            recent_sessions_by_ticker = {
                ticker: (context.get("recent_session_memory", {}) or {}).get("recent_sessions", [])
                for ticker, context in contexts.items()
            }
            normalized_metadata = dict(normalized_envelope.metadata)
            normalized_metadata["memory_context"] = {
                "recent_sessions_by_ticker": recent_sessions_by_ticker,
                "active_playbooks": active_playbooks,
            }
            normalized_envelope.metadata = normalized_metadata
            self._persist_day(
                trade_date=trade_date,
                day_summary=day_summary,
                planner_output=planner_output,
                analysis_payloads=analysis_payloads,
                trade_results=trade_results,
                risk_report=risk_report,
                normalized_envelope=normalized_envelope,
            )
            if str(day_dir).startswith("/tmp/"):
                print(f"[{trade_date}] Đã tự chuyển output cognitive sang đường dẫn ghi được: {day_dir}")
            self._persist_episodic_memory(
                trade_date=trade_date,
                contexts=contexts,
                outcomes=outcomes,
                trade_results=trade_results,
                event_ledger=event_ledger,
            )
            with Timer.track("cognitive.daily_report"):
                daily_report = await self.daily_reporter.generate(
                    trade_date=trade_date,
                    day_summary=day_summary,
                    trade_results=trade_results,
                    analysis_payloads=analysis_payloads,
                    risk_report=risk_report,
                    normalized_envelope=normalized_envelope,
                )
            (day_dir / "daily_report.md").write_text(daily_report, encoding="utf-8")

            final_day_timing = Timer.summary_since(day_timer_snapshot, prefix="cognitive.")
            if final_day_timing:
                print(f"[{trade_date}] Cognitive timing summary: {json.dumps(final_day_timing, ensure_ascii=False)}")

            self._write_json(self.config.equity_curve_path, equity_curve)
            self._persist_portfolio_snapshot(trade_date=trade_date, portfolio=portfolio)
            self._persist_run_status(
                trade_date=trade_date,
                status="completed",
                details={
                    "equity_curve_points": len(equity_curve),
                    "trade_count": len(trade_results),
                },
            )

        if equity_curve:
            last_backtest_date = str(equity_curve[-1]["date"])
            matured_episodes = self.reflection_agent.evaluate(last_backtest_date=last_backtest_date)
            calibration_updates = self.reflection_agent.attribute(episodes=matured_episodes)
            await self.reflection_agent.generate_reflection_summary(
                last_backtest_date=last_backtest_date,
                episodes=matured_episodes,
            )
            for candidate in self.promotion_engine.scan_for_patterns():
                self.promotion_engine.promote(candidate=candidate)
            self.promotion_engine.demote()

            benchmark_metrics = self._calculate_benchmark_metrics(
                equity_curve=equity_curve,
                benchmark_data=benchmark_data,
            )
            self._write_json(
                self.config.output_root / "state" / "benchmark_metrics.json",
                benchmark_metrics,
            )
            self._persist_memory_artifacts(
                last_backtest_date=last_backtest_date,
                calibration_updates=calibration_updates,
            )

        return equity_curve

    async def _collect_outcomes(
        self,
        *,
        trade_date: str,
        contexts: Mapping[str, Mapping[str, Any]],
        portfolio: Portfolio,
        price_map: Mapping[str, float],
    ) -> list[TickerOutcome]:
        tasks = [
            self._analyze_ticker(
                ticker=ticker,
                trade_date=trade_date,
                context=dict(context),
                portfolio=portfolio,
                price_map=price_map,
            )
            for ticker, context in sorted(contexts.items())
        ]
        if not tasks:
            return []
        with Timer.track("cognitive.analyze_ticker_batch"):
            return list(await asyncio.gather(*tasks))

    async def _analyze_ticker(
        self,
        *,
        ticker: str,
        trade_date: str,
        context: dict[str, Any],
        portfolio: Portfolio,
        price_map: Mapping[str, float],
    ) -> TickerOutcome:
        sector = infer_sector(ticker)
        portfolio_snapshot = dict(context.get("portfolio_context") or self.risk_kernel.enrich_portfolio_snapshot(
            portfolio=portfolio,
            ticker=ticker,
            price_map=price_map,
        ))
        context["portfolio_context"] = portfolio_snapshot
        planner_decision = self.planner.classify(ticker=ticker, context=context)

        cards = await asyncio.gather(
            *[
                self._run_analyst(
                    analyst_name=analyst_name,
                    ticker=ticker,
                    trade_date=trade_date,
                    context=context,
                    sector=sector,
                )
                for analyst_name in planner_decision.analysts
            ]
        )
        # Luôn chạy debate để có final_score cho CIO
        with Timer.track("cognitive.debate"):
            debate_result = await self.debate_engine.debate(
                ticker=ticker,
                ref_date=trade_date,
                cards=cards,
                context=context,
                portfolio_snapshot=portfolio_snapshot,
            )
        with Timer.track("cognitive.cio_decision"):
            intent = await self.cio_agent.decide(
                ticker=ticker,
                ref_date=trade_date,
                cards=cards,
                debate_result=debate_result,
                context=context,
                portfolio_snapshot=portfolio_snapshot,
            )
        order_ticket = self.risk_kernel.evaluate_intent(
            intent=intent,
            portfolio=portfolio,
            price_map=price_map,
            sector=sector,
        )
        return TickerOutcome(
            ticker=ticker,
            sector=sector,
            planner_decision=planner_decision,
            cards=tuple(cards),
            debate_result=debate_result,
            intent=intent,
            order_ticket=order_ticket,
        )

    async def _run_analyst(
        self,
        *,
        analyst_name: str,
        ticker: str,
        trade_date: str,
        context: Mapping[str, Any],
        sector: str,
    ) -> AnalysisCard:
        analyst = self.analysts[analyst_name]
        try:
            raw_output = await analyst.analyze(ticker=ticker, ref_date=trade_date, context=context)
            card = await self.schema_validator.validate(
                raw_text=raw_output,
                agent_name=analyst_name,
                ticker=ticker,
                ref_date=trade_date,
            )
            return self.calibrator.apply(card, sector)
        except (LLMError, ValidationError, ValueError, json.JSONDecodeError) as exc:
            return AnalysisCard(
                agent_name=analyst_name,
                ticker=ticker,
                ref_date=trade_date,
                action=Action.PASS,
                confidence_raw=0.0,
                confidence_calibrated=0.0,
                upside_pct=0.0,
                downside_pct=0.0,
                reasoning=f"Phân tích của {analyst_name} tạm thời không khả dụng do lỗi: {exc}",
                evidence_ids=["llm_error"],
                analysis_steps=[f"{type(exc).__name__}: {exc}"],
            )

    def _execute_stop_loss_orders(
        self,
        *,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        trade_date: str,
    ) -> list[dict[str, Any]]:
        trade_results: list[dict[str, Any]] = []
        for order in self.risk_kernel.generate_stop_loss_orders(portfolio=portfolio, price_map=price_map):
            executed, error_message = self._execute_order(portfolio=portfolio, order=order)
            trade_results.append(
                {
                    "ticker": order.ticker,
                    "date": trade_date,
                    "action": order.action.value,
                    "price": order.price,
                    "quantity": order.quantity,
                    "total_cost": order.total_cost,
                    "weight_pct": 0.0,
                    "confidence": 100.0,
                    "status": "APPROVED" if executed else "BLOCKED",
                    "reasoning": "Forced stop-loss order.",
                    "playbook_id": None,
                    "debate_triggered": False,
                    "block_reason": None if executed else error_message,
                    "planner_classification": "risk_stop_loss",
                    "order_source": "stop_loss",
                }
            )
        return trade_results

    def _execute_outcome(
        self,
        *,
        outcome: TickerOutcome,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        trade_date: str,
    ) -> dict[str, Any]:
        price = float(price_map.get(outcome.ticker, 0.0) or 0.0)
        trade_result = {
            "ticker": outcome.ticker,
            "date": trade_date,
            "action": outcome.intent.action.value,
            "price": round(price, 4) if price > 0 else None,
            "quantity": 0,
            "total_cost": 0.0,
            "weight_pct": round(float(outcome.intent.weight_pct), 4),
            "confidence": round(float(outcome.intent.confidence), 4),
            "status": "NO_ACTION",
            "reasoning": outcome.intent.reasoning,
            "playbook_id": outcome.intent.playbook_id,
            "debate_triggered": bool(outcome.debate_result.triggered),
            "block_reason": None,
            "planner_classification": outcome.planner_decision.classification,
            "order_source": "cio",
        }

        if outcome.order_ticket is None:
            return trade_result

        trade_result.update(
            {
                "action": outcome.order_ticket.action.value,
                "quantity": int(outcome.order_ticket.quantity),
                "total_cost": round(float(outcome.order_ticket.total_cost), 4),
                "status": outcome.order_ticket.status,
                "block_reason": outcome.order_ticket.block_reason,
            }
        )
        if outcome.order_ticket.status == "BLOCKED":
            return trade_result

        executed, error_message = self._execute_order(portfolio=portfolio, order=outcome.order_ticket)
        if not executed:
            trade_result["status"] = "BLOCKED"
            trade_result["block_reason"] = error_message
        return trade_result

    @staticmethod
    def _execute_order(*, portfolio: Portfolio, order: Any) -> tuple[bool, str | None]:
        try:
            if order.action in {Action.BUY, Action.BUY_MORE}:
                quantity = int(order.quantity or 0)
                price = float(order.price or 0.0)
                total_cost = float(order.total_cost or 0.0)
                if quantity < LOT_SIZE or price <= 0 or total_cost <= 0:
                    return False, "Approved buy order has invalid quantity/price/total_cost."
                if total_cost - portfolio.cash > 1e-9:
                    return False, "Approved buy order exceeds available cash."
                pos = portfolio.positions.get(order.ticker, Position())
                pos.add_lot(quantity, price)
                portfolio.positions[order.ticker] = pos
                portfolio.cash -= total_cost
                portfolio.trades += 1
                portfolio.buys_per_ticker[order.ticker] = portfolio.buys_per_ticker.get(order.ticker, 0) + 1
                return True, None
            if order.action in {Action.SELL, Action.TRIMMING}:
                portfolio.sell(order.ticker, order.quantity, order.price)
                return True, None
            return False, f"Unsupported executable action: {order.action}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    @staticmethod
    def _execution_order(outcomes: Sequence[TickerOutcome]) -> list[TickerOutcome]:
        priority = {
            Action.SELL: 0,
            Action.TRIMMING: 1,
            Action.BUY_MORE: 2,
            Action.BUY: 3,
            Action.PASS: 4,
        }
        return sorted(
            outcomes,
            key=lambda item: (
                priority.get(item.intent.action, 9),
                -float(item.intent.confidence),
                item.ticker,
            ),
        )

    def _analysis_payloads(self, outcomes: Sequence[TickerOutcome]) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        for outcome in outcomes:
            payloads[outcome.ticker] = {
                "planner": outcome.planner_decision.to_dict(),
                "cards": [card.legacy_payload() for card in outcome.cards],
                "debate": outcome.debate_result.to_dict() if outcome.debate_result.triggered else None,
                "cio_decision": outcome.intent.model_dump(mode="json"),
                "sector": outcome.sector,
            }
        return payloads

    @staticmethod
    def _normalize_agent_artifact(
        *,
        workflow: str,
        ticker: str,
        ref_date: str,
        card: AnalysisCard,
    ) -> NormalizedAgentArtifact:
        return NormalizedAgentArtifact(
            workflow=workflow,
            artifact_origin="native",
            analysis_depth="rich",
            ticker=ticker,
            ref_date=ref_date,
            agent_name=card.agent_name,
            action=card.action,
            confidence_raw=card.confidence_raw,
            confidence_calibrated=card.confidence_calibrated,
            upside_pct=card.upside_pct,
            downside_pct=card.downside_pct,
            reasoning_summary=card.reasoning,
            key_considerations=list(card.evidence_ids),
            evidence_ids=list(card.evidence_ids),
            analysis_steps=list(card.analysis_steps),
            source_agents=[card.agent_name],
            metadata={"native_schema": "AnalysisCard"},
        )

    def _build_normalized_envelope(
        self,
        *,
        trade_date: str,
        day_summary: Mapping[str, Any],
        portfolio: Portfolio,
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        trade_results: Sequence[Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        equity_curve: Sequence[Mapping[str, Any]],
    ) -> WorkflowArtifactEnvelope:
        normalized_analysis: dict[str, WorkflowTickerArtifact] = {}
        for ticker, payload in analysis_payloads.items():
            raw_cards = payload.get("cards") or []
            normalized_cards: list[NormalizedAgentArtifact] = []
            for raw_card in raw_cards:
                if not isinstance(raw_card, Mapping):
                    continue
                try:
                    normalized_cards.append(
                        NormalizedAgentArtifact.model_validate(
                            {
                                "workflow": "cognitive",
                                "artifact_origin": "native",
                                "analysis_depth": "rich",
                                "ticker": ticker,
                                "ref_date": trade_date,
                                "agent_name": raw_card.get("agent_name"),
                                "action": raw_card.get("action"),
                                "confidence_raw": raw_card.get("confidence_raw"),
                                "confidence_calibrated": raw_card.get("confidence_calibrated"),
                                "upside_pct": raw_card.get("upside_pct"),
                                "downside_pct": raw_card.get("downside_pct"),
                                "reasoning_summary": raw_card.get("reasoning"),
                                "key_considerations": raw_card.get("evidence_ids") or [],
                                "evidence_ids": raw_card.get("evidence_ids") or [],
                                "analysis_steps": raw_card.get("analysis_steps") or raw_card.get("_thought_process") or [],
                                "source_agents": [raw_card.get("agent_name")] if raw_card.get("agent_name") else [],
                                "metadata": {"native_schema": "AnalysisCard"},
                            }
                        )
                    )
                except Exception:
                    continue

            trade = next(
                (
                    item for item in trade_results
                    if str(item.get("ticker") or "").upper() == ticker.upper()
                ),
                None,
            )
            normalized_analysis[ticker] = WorkflowTickerArtifact(
                workflow="cognitive",
                artifact_origin="native",
                analysis_depth="rich",
                ticker=ticker,
                ref_date=trade_date,
                planner=dict(payload.get("planner") or {}),
                cards=normalized_cards,
                debate=payload.get("debate"),
                cio_intent=dict(payload.get("cio_decision") or {}),
                risk={
                    "sector": payload.get("sector"),
                    "trade_status": trade.get("status") if isinstance(trade, Mapping) else None,
                    "block_reason": trade.get("block_reason") if isinstance(trade, Mapping) else None,
                },
                trade=dict(trade) if isinstance(trade, Mapping) else None,
                metadata={
                    "source_analysis_dir": f"daily/{trade_date}/analysis/{ticker}",
                    "source_workflow": "cognitive",
                },
            )

        portfolio_state = {
            "cash": float(portfolio.cash),
            "positions": {
                ticker: {
                    "lots": [
                        {"qty": lot.qty, "price": lot.price, "days_held": lot.days_held}
                        for lot in pos.lots
                    ]
                }
                for ticker, pos in portfolio.positions.items()
            },
            "trades": int(portfolio.trades),
            "sells": int(portfolio.sells),
            "wins": int(portfolio.wins),
            "equity_history": list(portfolio.equity_history),
            "last_date": portfolio.last_date,
            "buys_per_ticker": dict(portfolio.buys_per_ticker),
        }
        calibration = list(risk_report.get("calibration_updates") or [])
        return WorkflowArtifactEnvelope(
            workflow="cognitive",
            artifact_origin="native",
            analysis_depth="rich",
            as_of_date=trade_date,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            locale="vi-VN",
            summary=dict(day_summary),
            portfolio_state=portfolio_state,
            ledger=[dict(item) for item in trade_results],
            analysis=normalized_analysis,
            risk_report=dict(risk_report),
            calibration=calibration,
            equity_curve=[dict(point) for point in equity_curve],
            metadata={
                "schema_version": ARTIFACT_VERSION,
                "workflow_family": "cognitive_trading",
            },
        )

    def _persist_episodic_memory(
        self,
        *,
        trade_date: str,
        contexts: Mapping[str, Mapping[str, Any]],
        outcomes: Sequence[TickerOutcome],
        trade_results: Sequence[Mapping[str, Any]],
        event_ledger: Mapping[str, Any],
    ) -> None:
        trade_by_ticker = {
            str(item.get("ticker") or "").upper(): item
            for item in trade_results
            if str(item.get("ticker") or "").upper()
        }
        vn30_close = self._vn30_close_vnd(event_ledger)
        vn30_change_pct = self._vn30_change_pct(event_ledger)
        for outcome in outcomes:
            trade_result = trade_by_ticker.get(outcome.ticker)
            if not trade_result:
                continue
            if str(trade_result.get("status") or "") != "APPROVED":
                continue
            if str(trade_result.get("action") or "") not in {
                Action.BUY.value,
                Action.BUY_MORE.value,
                Action.SELL.value,
                Action.TRIMMING.value,
            }:
                continue

            context = contexts.get(outcome.ticker, {})
            macro_context = context.get("macro_context", {})
            news_context = context.get("news_context", {})
            self.episodic_store.save_episode(
                trade_date=trade_date,
                ticker=outcome.ticker,
                action=str(trade_result.get("action") or outcome.intent.action.value),
                entry_price=float(trade_result.get("price") or 0.0) or None,
                quantity=int(trade_result.get("quantity") or 0) or None,
                vn30_close=vn30_close,
                vn30_change_pct=vn30_change_pct,
                sector=outcome.sector,
                macro_summary=self._context_summary(macro_context),
                news_summary=self._context_summary(news_context),
                agent_cards=outcome.cards,
                debate_summary=outcome.debate_result.summary,
                cio_reasoning=str(outcome.intent.reasoning),
            )

    def _persist_memory_artifacts(
        self,
        *,
        last_backtest_date: str,
        calibration_updates: Sequence[Mapping[str, Any]],
    ) -> None:
        recent_memory: dict[str, list[dict[str, Any]]] = {}
        for ticker in sorted(_vn30_tickers()):
            recent = self.episodic_store.get_recent_session_memory(
                ticker=ticker,
                current_ref_date=last_backtest_date,
                limit=5,
            )
            if recent:
                recent_memory[ticker] = recent

        active_playbooks = self.strategy_store.list_active()
        all_playbooks = self.strategy_store.list_all()
        calibration_summary = self.reflection_agent.calibration_store.get_all_calibrations()
        episodic_summary = [
            {
                "trade_date": item.get("trade_date"),
                "ticker": item.get("ticker"),
                "action": item.get("action"),
                "pnl_t5": item.get("pnl_t5"),
                "alpha_vs_vn30": item.get("alpha_vs_vn30"),
            }
            for ticker in sorted(recent_memory)
            for item in recent_memory[ticker]
        ]

        self._write_json(self.config.state_dir / "recent_analysis_memory.json", recent_memory)
        self._write_json(self.config.state_dir / "strategy_memory_snapshot.json", all_playbooks)
        self._write_json(self.config.state_dir / "calibration_summary.json", calibration_summary)
        self._write_json(self.config.state_dir / "episodic_memory_summary.json", episodic_summary)
        self._write_json(
            self.config.playbooks_dir / "active_summary.json",
            {
                "last_backtest_date": last_backtest_date,
                "active_playbooks": active_playbooks,
                "all_playbooks": all_playbooks,
                "recent_calibration_updates": [dict(item) for item in calibration_updates],
            },
        )

    @staticmethod
    def _context_summary(context: Mapping[str, Any] | None) -> str | None:
        if not isinstance(context, Mapping):
            return None
        summary = context.get("summary")
        if summary:
            return str(summary)
        headlines = []
        for article in context.get("top_articles", []) or []:
            if isinstance(article, Mapping) and article.get("title"):
                headlines.append(str(article["title"]))
        if headlines:
            return " | ".join(headlines)
        return None

    @staticmethod
    def _vn30_close_vnd(event_ledger: Mapping[str, Any]) -> float | None:
        prices = []
        for ticker in _vn30_tickers():
            snapshot = event_ledger.get("tickers", {}).get(ticker)
            if not isinstance(snapshot, Mapping):
                continue
            price = snapshot.get("latest_close_vnd")
            try:
                resolved = float(price)
            except (TypeError, ValueError):
                continue
            if resolved > 0:
                prices.append(resolved)
        if not prices:
            return None
        return round(sum(prices) / len(prices), 4)

    @staticmethod
    def _vn30_change_pct(event_ledger: Mapping[str, Any]) -> float | None:
        changes = []
        for ticker in _vn30_tickers():
            snapshot = event_ledger.get("tickers", {}).get(ticker)
            if not isinstance(snapshot, Mapping):
                continue
            change_pct = snapshot.get("recent_price_change_pct")
            try:
                resolved = float(change_pct)
            except (TypeError, ValueError):
                continue
            changes.append(resolved)
        if not changes:
            return None
        return round(sum(changes) / len(changes), 4)

    def _build_day_summary(
        self,
        *,
        trade_date: str,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        trade_results: Sequence[Mapping[str, Any]],
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        daily_return_pct: float,
    ) -> dict[str, Any]:
        nav = float(portfolio.equity(dict(price_map)))
        approved = [item for item in trade_results if item.get("status") == "APPROVED"]
        buy_count = sum(1 for item in approved if item.get("action") in {Action.BUY.value, Action.BUY_MORE.value})
        sell_count = sum(1 for item in approved if item.get("action") in {Action.SELL.value, Action.TRIMMING.value})
        flagged_tickers = sum(
            1
            for payload in analysis_payloads.values()
            if payload.get("planner", {}).get("classification") == "high_impact"
        )
        debated_tickers = sum(1 for payload in analysis_payloads.values() if payload.get("debate"))
        playbooks_activated = sum(
            1
            for payload in analysis_payloads.values()
            if payload.get("cio_decision", {}).get("playbook_id")
        )
        return {
            "date": trade_date,
            "nav": round(nav, 4),
            "cash": round(float(portfolio.cash), 4),
            "invested": round(nav - float(portfolio.cash), 4),
            "return_pct": round(((nav - self.config.start_cash_vnd) / self.config.start_cash_vnd) * 100.0, 4),
            "daily_return_pct": round(float(daily_return_pct), 4),
            "trade_count": len(approved),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "flagged_tickers": flagged_tickers,
            "debated_tickers": debated_tickers,
            "playbooks_activated": playbooks_activated,
            "sector_exposure": risk_report.get("sector_exposure_pct", {}),
        }

    def _persist_day(
        self,
        *,
        trade_date: str,
        day_summary: Mapping[str, Any],
        planner_output: Mapping[str, Any],
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        trade_results: Sequence[Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        normalized_envelope: WorkflowArtifactEnvelope,
    ) -> None:
        day_dir = self.config.daily_dir / trade_date
        analysis_dir = day_dir / "analysis"
        trades_dir = day_dir / "trades"
        risk_dir = day_dir / "risk"
        normalized_dir = day_dir / "normalized"
        self._ensure_dir(analysis_dir)
        self._ensure_dir(trades_dir)
        self._ensure_dir(risk_dir)
        self._ensure_dir(normalized_dir)

        self._write_json(day_dir / "summary.json", day_summary)
        self._write_json(day_dir / "planner_output.json", planner_output)
        self._write_json(self.config.ledgers_dir / f"{trade_date}.json", list(trade_results))
        self._write_json(risk_dir / "risk_report.json", risk_report)
        self._write_json(normalized_dir / "workflow_artifact.json", normalized_envelope.model_dump(mode="json"))

        for ticker, payload in analysis_payloads.items():
            ticker_analysis_dir = analysis_dir / ticker
            self._ensure_dir(ticker_analysis_dir)
            self._write_json(ticker_analysis_dir / "cards.json", payload.get("cards", []))
            self._write_json(ticker_analysis_dir / "debate.json", payload.get("debate"))
            self._write_json(ticker_analysis_dir / "cio_decision.json", payload.get("cio_decision", {}))

        per_ticker_trade: dict[str, Mapping[str, Any]] = {}
        for trade_result in trade_results:
            ticker = str(trade_result.get("ticker") or "").upper()
            if ticker:
                per_ticker_trade[ticker] = trade_result
        for ticker, trade_result in per_ticker_trade.items():
            self._write_json(trades_dir / f"{ticker}.json", trade_result)

    def _prepare_output_root(self) -> None:
        preferred_paths = (
            self.config.output_root,
            self.config.daily_dir,
            self.config.ledgers_dir,
            self.config.state_dir,
            self.config.memory_dir,
            self.config.playbooks_dir,
            self.config.snapshots_dir,
        )
        try:
            for path in preferred_paths:
                self._ensure_dir(path)
            probe_path = self.config.output_root / ".write_probe"
            probe_path.write_text("ok", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
        except PermissionError:
            fallback_root = Path("/tmp") / f"cognitive-backtest-{os.getpid()}"
            self._rebind_output_paths(fallback_root)
            for path in (
                self.config.output_root,
                self.config.daily_dir,
                self.config.ledgers_dir,
                self.config.state_dir,
                self.config.memory_dir,
                self.config.playbooks_dir,
                self.config.snapshots_dir,
            ):
                self._ensure_dir(path)

    def _rebind_output_paths(self, output_root: Path) -> None:
        object.__setattr__(self.config, "output_root", output_root)
        object.__setattr__(self.config, "daily_dir", output_root / "daily")
        object.__setattr__(self.config, "ledgers_dir", output_root / "ledgers")
        object.__setattr__(self.config, "state_dir", output_root / "state")
        object.__setattr__(self.config, "playbooks_dir", output_root / "playbooks")
        object.__setattr__(self.config, "snapshots_dir", output_root / "state_snapshots")
        object.__setattr__(self.config, "equity_curve_path", output_root / "equity_curve.json")

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        os.makedirs(path, exist_ok=True)

    def _completed_dates(self) -> list[str]:
        completed: list[str] = []
        for day_dir in sorted(self.config.daily_dir.glob("*/run_status.json")):
            payload = self._load_json(day_dir, default={})
            if isinstance(payload, Mapping) and payload.get("status") == "completed":
                completed.append(str(payload.get("trade_date") or day_dir.parent.name))
        return completed

    def _effective_start_date(self, *, requested_start: str, completed_dates: Sequence[str]) -> str:
        requested = date.fromisoformat(requested_start)
        if not completed_dates:
            return requested.isoformat()
        previous = previous_trading_day(requested_start)
        if previous and previous not in completed_dates and self._has_day_artifacts(previous):
            return previous
        return requested.isoformat()

    def _has_day_artifacts(self, trade_date: str) -> bool:
        day_dir = self.config.daily_dir / trade_date
        ledger_path = self.config.ledgers_dir / f"{trade_date}.json"
        return day_dir.exists() or ledger_path.exists()

    def _restore_resume_state(
        self,
        *,
        requested_start: str,
        completed_dates: Sequence[str],
        default_portfolio: Portfolio,
        default_equity_curve: list[dict[str, Any]],
    ) -> tuple[Portfolio, list[dict[str, Any]]]:
        previous = previous_trading_day(requested_start)
        if not previous:
            return default_portfolio, default_equity_curve

        snapshot_path = self.config.snapshots_dir / f"{previous}.json"
        if snapshot_path.exists() and previous in completed_dates:
            return Portfolio.load_state(snapshot_path), self._truncate_equity_curve(default_equity_curve, previous)

        if completed_dates:
            latest_completed = completed_dates[-1]
            if latest_completed < requested_start:
                latest_snapshot_path = self.config.snapshots_dir / f"{latest_completed}.json"
                if latest_snapshot_path.exists():
                    return Portfolio.load_state(latest_snapshot_path), self._truncate_equity_curve(default_equity_curve, latest_completed)

        return default_portfolio, self._truncate_equity_curve(default_equity_curve, previous if previous in completed_dates else None)

    @staticmethod
    def _truncate_equity_curve(equity_curve: list[dict[str, Any]], last_date: str | None) -> list[dict[str, Any]]:
        if not last_date:
            return []
        return [dict(point) for point in equity_curve if str(point.get("date") or "") <= last_date]

    def _persist_run_status(self, *, trade_date: str, status: str, details: Mapping[str, Any] | None = None) -> None:
        day_dir = self.config.daily_dir / trade_date
        payload = {
            "trade_date": trade_date,
            "status": status,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "details": dict(details or {}),
        }
        self._write_json(day_dir / "run_status.json", payload)

    def _persist_portfolio_snapshot(self, *, trade_date: str, portfolio: Portfolio) -> None:
        snapshot_path = self.config.snapshots_dir / f"{trade_date}.json"
        portfolio.save_state(snapshot_path)
        portfolio.save_state(self.config.state_dir / "portfolio.json")
        day_dir = self.config.daily_dir / trade_date
        portfolio.save_state(day_dir / "portfolio_state.json")

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        if path.parent:
            os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _load_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _load_benchmark_data(self, start: str, end: str) -> dict[str, list[float]]:
        """Load VN30 and VNINDEX benchmark prices from vnstock.db."""
        from vnstock.tools.backtest.engine import load_benchmark_data

        benchmark_curves = {}
        for benchmark_name in ("VN30", "VNINDEX"):
            benchmark_df = load_benchmark_data(start, end, benchmark_name)
            if benchmark_df.empty:
                benchmark_curves[benchmark_name] = []
            else:
                benchmark_curves[benchmark_name] = [
                    float(row["close"]) * 1000.0
                    for _, row in benchmark_df.iterrows()
                    if float(row["close"]) > 0.0
                ]
        return benchmark_curves

    def _calculate_benchmark_metrics(
        self,
        *,
        equity_curve: list[dict[str, Any]],
        benchmark_data: dict[str, list[float]],
    ) -> dict[str, dict[str, float]]:
        """Calculate Alpha, Beta, Tracking Error, and IR for VN30 and VNINDEX."""
        if not equity_curve or len(equity_curve) < 2:
            return {}

        strategy_equity = [float(point["equity"]) for point in equity_curve]
        start_capital = self.config.start_cash_vnd

        metrics = {}
        for benchmark_name, benchmark_prices in benchmark_data.items():
            if not benchmark_prices:
                continue

            analyzer = BenchmarkAnalyzer(
                benchmark_name=benchmark_name,
                annual_trading_days=252,
                risk_free_rate=0.025,
            )
            result = analyzer.compare(
                equity_curve=strategy_equity,
                benchmark_prices=benchmark_prices,
                start_capital=start_capital,
            )
            metrics[benchmark_name] = result

        return metrics

    @staticmethod
    def _price_map_from_ledger(event_ledger: Mapping[str, Any]) -> dict[str, float]:
        prices: dict[str, float] = {}
        for ticker, snapshot in event_ledger.get("tickers", {}).items():
            if not isinstance(snapshot, Mapping):
                continue
            price = snapshot.get("latest_close_vnd")
            try:
                resolved = float(price)
            except (TypeError, ValueError):
                continue
            if resolved > 0:
                prices[str(ticker).upper()] = resolved
        return prices


def _vn30_tickers() -> set[str]:
    from vnstock.tools.backtest.engine import VN30_TICKERS

    return {ticker.upper() for ticker in VN30_TICKERS}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone cognitive_trading backtest.")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers or VN30")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    return parser


def _parse_tickers(raw: str) -> list[str]:
    if raw.strip().upper() == "VN30":
        return sorted(_vn30_tickers())
    tickers = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return sorted(dict.fromkeys(tickers))


async def _main(args: argparse.Namespace) -> None:
    runner = CognitiveBacktestRunner()
    try:
        equity_curve = await runner.run(
            tickers=_parse_tickers(args.tickers),
            start=args.start,
            end=args.end,
        )
    finally:
        await runner.close()

    if not equity_curve:
        print("Không có dữ liệu để chạy cognitive_trading trong khoảng ngày đã chọn.")
        return

    latest = equity_curve[-1]
    print(
        "Cognitive trading complete:",
        f"points={len(equity_curve)}",
        f"latest_date={latest.get('date')}",
        f"equity={latest.get('equity')}",
    )


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
