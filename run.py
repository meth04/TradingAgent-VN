"""Root CLI for the VNStock AI Hedge Fund workspace.

Examples:
    python run.py crawl-vnstock --tickers FPT
    python run.py crawl-news --news-days 23 --source cafef
    python run.py analyze --ticker FPT --year 2025 --quarter Q4
    python run.py backtest --tickers FPT --start 2026-03-24 --end 2026-03-25 \
        --workflows Traditional,Kelly,Markowitz
    python run.py backtest-cognitive --tickers FPT --start 2026-03-24 --end 2026-03-25
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

# Import torch first on Windows to avoid DLL ordering issues with downstream libs.
try:
    import torch  # noqa: F401
except ImportError:
    pass


ROOT = Path(__file__).resolve().parent
for extra in (ROOT, ROOT / "vnstock", ROOT / "tracking_news"):
    extra_str = str(extra)
    if extra_str not in sys.path:
        sys.path.insert(0, extra_str)


try:
    from config import paths
    from cognitive_trading.runner import CognitiveBacktestRunner
    from vnstock.agents.financial_analysis import (
        FinancialAnalysisError,
        generate_financial_report,
    )
    from vnstock.agents.financial_agent import normalize_financial_quarter
    from vnstock.core import llm as llm_core
    from vnstock.database.models import init_db
    from vnstock.jobs.crawler import MarketCrawler
    from vnstock.libs.rag_engine.ingest import run_ingest
    from vnstock.libs.rag_engine.retrieval import query_func
    from vnstock.tools.backtest.engine import VN30_TICKERS, run_portfolio_backtest, select_workflows
except ImportError as exc:  # pragma: no cover - startup guard
    hint = f"PYTHONPATH={ROOT}:{ROOT / 'vnstock'}:{ROOT / 'cognitive_trading'}"
    print(f"ImportError: {exc}. Try setting {hint}.", file=sys.stderr)
    raise


NEWS_DB_PATH = paths.news_db_path


def _ensure_loop_policy() -> None:
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def parse_tickers(raw: str | None) -> list[str]:
    if not raw or raw.strip().upper() == "VN30":
        return list(VN30_TICKERS)
    items: Iterable[str] = (item.strip().upper() for item in raw.split(","))
    return [item for item in items if item]


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid {label}: {value}. Expected YYYY-MM-DD.") from exc


def _news_window_start(news_days: int, today: date) -> date:
    if news_days <= 0:
        raise ValueError("news_days must be >= 1")
    return today - timedelta(days=news_days - 1)


def _latest_news_date(db_path: Path) -> date | None:
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT MAX(published_date) FROM articles").fetchone()
        if not row or not row[0]:
            return None
        return date.fromisoformat(str(row[0]))
    except Exception:
        return None


def _has_market_data_for_range(ticker: str, start: date, end: date) -> bool:
    from vnstock.database.repo import DataRepository

    repo = DataRepository()
    try:
        df = repo.get_price_history(
            ticker,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        return not df.empty
    finally:
        repo.close()


def _ensure_backtest_market_data(tickers: list[str], start: date, end: date) -> None:
    required = sorted({*tickers, "VN30", "VNINDEX"})
    missing = [ticker for ticker in required if not _has_market_data_for_range(ticker, start, end)]
    if not missing:
        return

    print(
        "Phát hiện thiếu dữ liệu backtest cho: "
        f"{', '.join(missing)}. Đang tự crawl/backfill từ vnstock..."
    )
    init_db()
    crawler = MarketCrawler()
    try:
        crawler.sync_tickers(
            [ticker for ticker in tickers if ticker in missing],
            include_benchmarks=("VN30" in missing or "VNINDEX" in missing),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
    finally:
        crawler.repo.close()

    still_missing = [ticker for ticker in required if not _has_market_data_for_range(ticker, start, end)]
    if still_missing:
        print(
            "Cảnh báo: vẫn thiếu dữ liệu sau khi crawl cho: "
            f"{', '.join(still_missing)}"
        )


async def handle_backtest(args: argparse.Namespace) -> None:
    start_date = _parse_iso_date(args.start, "start")
    end_date = _parse_iso_date(args.end, "end")
    if start_date > end_date:
        print("Invalid date range: start must be <= end")
        sys.exit(2)

    tickers = parse_tickers(args.tickers)
    if not tickers:
        print("No tickers provided; exiting.")
        sys.exit(2)

    workflow_labels = select_workflows(args.workflows)
    if not workflow_labels:
        print("No valid workflow labels selected; exiting.")
        sys.exit(2)

    _ensure_backtest_market_data(tickers, start_date, end_date)

    results = await run_portfolio_backtest(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        tickers=tickers,
        workflows=workflow_labels,
    )
    if not results:
        print("Không có dữ liệu thị trường cho khoảng ngày đã chọn.")
        return

    print("VNStock backtest complete:")
    for result in results:
        metrics = result.metrics(final_prices={})
        benchmark = result.benchmark_metrics or {}
        profit_factor = float(metrics["profit_factor"])
        profit_factor_display = "inf" if math.isinf(profit_factor) else f"{profit_factor:.2f}"
        vn30 = benchmark.get('VN30', {}) if isinstance(benchmark, dict) else {}
        vnindex = benchmark.get('VNINDEX', {}) if isinstance(benchmark, dict) else {}
        print(
            f"- {result.name}: return_pct={float(metrics['return_pct']):.2f}% | "
            f"account_value={float(metrics['account_value']):.0f} | "
            f"total_pnl={float(metrics['total_pnl']):.0f} | trades={int(metrics['trades'])} | "
            f"sharpe={float(metrics['sharpe']):.2f} | sortino={float(metrics['sortino']):.2f} | "
            f"calmar={float(metrics['calmar']):.2f} | mdd={float(metrics['max_drawdown_pct']):.2f}% | "
            f"var95={float(metrics['var_95_pct']):.2f}% | cvar95={float(metrics['cvar_95_pct']):.2f}% | "
            f"profit_factor={profit_factor_display} | win_rate={float(metrics['win_rate']):.2f}% | "
            f"vn30={float(vn30.get('benchmark_return_pct', 0.0)):.2f}% | active30={float(vn30.get('active_return_pct', 0.0)):.2f}% | "
            f"alpha30={float(vn30.get('alpha_annualized_pct', 0.0)):.2f}% | beta30={float(vn30.get('beta', 0.0)):.2f} | ir30={float(vn30.get('information_ratio', 0.0)):.2f} | "
            f"vnindex={float(vnindex.get('benchmark_return_pct', 0.0)):.2f}% | activeindex={float(vnindex.get('active_return_pct', 0.0)):.2f}%"
        )


async def handle_backtest_cognitive(args: argparse.Namespace) -> None:
    start_date = _parse_iso_date(args.start, "start")
    end_date = _parse_iso_date(args.end, "end")
    if start_date > end_date:
        print("Invalid date range: start must be <= end")
        sys.exit(2)

    tickers = parse_tickers(args.tickers)
    if not tickers:
        print("No tickers provided; exiting.")
        sys.exit(2)

    _ensure_backtest_market_data(tickers, start_date, end_date)

    runner = CognitiveBacktestRunner()
    try:
        equity_curve = await runner.run(
            tickers=tickers,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )
    finally:
        await runner.close()

    if not equity_curve:
        print("Không có dữ liệu thị trường cho khoảng ngày đã chọn.")
        return

    latest = equity_curve[-1]
    print(
        "Cognitive backtest complete:",
        f"tickers={','.join(tickers)}",
        f"points={len(equity_curve)}",
        f"latest_date={latest.get('date')}",
        f"equity={latest.get('equity')}",
    )


async def handle_rag_query(args: argparse.Namespace) -> None:
    contexts, answer = await query_func(
        None,
        question=args.query,
        mode=args.mode,
        ticker=args.ticker,
        year=args.year,
        quarter=args.quarter,
    )
    if contexts:
        print(f"Retrieved {len(contexts)} context chunks.")
    print(answer)


async def generate_fundamental_report(ticker: str, year: str, quarter: str) -> Path:
    ticker_upper = ticker.upper()
    quarter_label = normalize_financial_quarter(quarter)
    print("Running financial_analysis agent...")
    artifact = await generate_financial_report(ticker_upper, year, quarter_label)
    return artifact.path


async def handle_analyze(args: argparse.Namespace) -> None:
    try:
        report_path = await generate_fundamental_report(
            ticker=args.ticker.upper(),
            year=str(args.year),
            quarter=args.quarter,
        )
    except FinancialAnalysisError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    print(f"Saved report to {report_path}")


async def handle_rag_index(args: argparse.Namespace) -> None:
    await asyncio.to_thread(run_ingest, args.input, args.pattern)


def handle_rag_dashboard(args: argparse.Namespace) -> None:
    port = int(getattr(args, "port", 8501))
    dashboard_path = ROOT / "vnstock" / "libs" / "rag_engine" / "dashboard.py"
    subprocess.run(
        ["streamlit", "run", str(dashboard_path), "--server.port", str(port)],
        check=True,
    )


def _configure_news_ingest_window(
    news_days: int,
    source: str = "cafef",
    *,
    incremental: bool = False,
) -> tuple[str, str]:
    today = date.today()
    date_to_dt = today
    date_from_dt = _news_window_start(news_days, today)

    if incremental:
        latest_date = _latest_news_date(NEWS_DB_PATH)
        if latest_date:
            date_from_dt = max(date_from_dt, latest_date + timedelta(days=1))
            if date_from_dt > date_to_dt:
                date_from_dt = date_to_dt

    date_from = date_from_dt.isoformat()
    date_to = date_to_dt.isoformat()
    max_pages = max(3, (news_days * 5) + 3)

    os.environ["NEWS_DB_PATH"] = str(NEWS_DB_PATH)
    os.environ["INGEST_DATE_FROM"] = date_from
    os.environ["INGEST_DATE_TO"] = date_to
    os.environ["ENABLED_SOURCES"] = source or "cafef"
    os.environ["MAX_PAGES_PER_SECTION"] = str(max_pages)
    os.environ["MAX_EXTRA_PAGES_PER_SECTION"] = str(max_pages)

    window_mode = "Incremental" if incremental else "Requested"
    print(
        f"{window_mode} news crawl window: {date_from} -> {date_to} | "
        f"source={source} | db={NEWS_DB_PATH}"
    )
    print(f"Ước tính cần crawl tối đa {max_pages} pages/danh mục để bao phủ {news_days} ngày.")
    return date_from, date_to


def handle_crawl_vnstock(args: argparse.Namespace) -> None:
    init_db()
    crawler = MarketCrawler()
    tickers = parse_tickers(args.tickers) if args.tickers else crawler.watchlist
    try:
        results = crawler.sync_tickers(
            tickers,
            replace_existing=bool(getattr(args, "replace_existing", False)),
            max_requests_per_minute=int(getattr(args, "max_requests_per_minute", 20)),
        )
        total_records = sum(results.values())
        action = "thay thế" if getattr(args, "replace_existing", False) else "thêm"
        print(f"Crawl Vnstock xong. Đã {action} {total_records} bản ghi vào {paths.vnstock_db_path}.")
    finally:
        crawler.repo.close()


def handle_crawl_news(args: argparse.Namespace) -> None:
    source = (getattr(args, "source", "cafef") or "cafef").strip().lower()
    date_from, date_to = _configure_news_ingest_window(
        news_days=args.news_days,
        source=source,
        incremental=False,
    )
    print(f"Bắt đầu crawl tin tức từ {date_from} đến {date_to} (Nguồn: {source})...")
    from tracking_news.app.ingest.run_once import main as crawl_main

    crawl_main()


async def handle_sync(args: argparse.Namespace) -> None:
    tickers = parse_tickers(args.tickers)
    if not tickers:
        print("No tickers provided; exiting.")
        sys.exit(2)

    year = str(args.year)
    quarter_label = normalize_financial_quarter(args.quarter)

    init_db()
    crawler = MarketCrawler()
    try:
        price_counts = await asyncio.to_thread(crawler.sync_tickers, tickers)
    finally:
        crawler.repo.close()
    print(f"Price sync complete: {sum(price_counts.values())} new rows into {paths.vnstock_db_path}")

    date_from, date_to = _configure_news_ingest_window(
        news_days=args.news_days,
        source="cafef",
        incremental=True,
    )
    from tracking_news.app.ingest.run_once import main as crawl_main

    await asyncio.to_thread(crawl_main)
    print(f"News sync complete: {date_from} -> {date_to} into {paths.news_db_path}")

    failures: list[str] = []
    for ticker in tickers:
        try:
            report_path = await generate_fundamental_report(ticker, year, quarter_label)
            print(f"Cached fundamentals: {ticker.upper()} -> {report_path}")
        except FinancialAnalysisError as exc:
            print(f"❌ {exc}")
            failures.append(ticker.upper())

    if failures:
        raise SystemExit(1)


async def _close_tracking_news_session() -> None:
    try:
        from tracking_news.app.summarizer import close_session as news_close_session
    except Exception:
        return

    try:
        await news_close_session()
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="VNStock AI Hedge Fund CLI with centralized /data databases."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest = subparsers.add_parser(
        "backtest",
        help="Run the VNStock 3-workflow backtest.",
    )
    backtest.add_argument("--tickers", default="VN30", help="Comma-separated tickers or VN30.")
    backtest.add_argument("--start", required=True, help="Inclusive start date (YYYY-MM-DD).")
    backtest.add_argument("--end", required=True, help="Inclusive end date (YYYY-MM-DD).")
    backtest.add_argument(
        "--workflows",
        default="Traditional,Kelly,Markowitz",
        help="Comma-separated workflow labels (Traditional,Kelly,Markowitz).",
    )

    backtest_cognitive = subparsers.add_parser(
        "backtest-cognitive",
        help="Run the cognitive_trading backtest.",
    )
    backtest_cognitive.add_argument(
        "--tickers",
        default="VN30",
        help="Comma-separated tickers or VN30.",
    )
    backtest_cognitive.add_argument(
        "--start",
        required=True,
        help="Inclusive start date (YYYY-MM-DD).",
    )
    backtest_cognitive.add_argument(
        "--end",
        required=True,
        help="Inclusive end date (YYYY-MM-DD).",
    )

    sync = subparsers.add_parser(
        "sync",
        aliases=["prepare"],
        help="Sync prices, news, and cached financial reports into the shared workspace.",
    )
    sync.add_argument("--tickers", default="VN30", help="Comma-separated tickers or VN30.")
    sync.add_argument("--year", required=True, help="Financial report year, e.g. 2025.")
    sync.add_argument("--quarter", required=True, help="Financial report quarter, e.g. Q4.")
    sync.add_argument(
        "--news-days",
        type=int,
        default=3,
        help="Inclusive news window in calendar days ending today.",
    )

    rag = subparsers.add_parser("rag", help="Ingest or query the financial RAG store.")
    rag_sub = rag.add_subparsers(dest="rag_command", required=True)

    rag_ingest = rag_sub.add_parser("index", help="Ingest OCR text files into the RAG store.")
    rag_ingest.add_argument("--input", required=True, help="File or directory path.")
    rag_ingest.add_argument(
        "--pattern",
        default="*.ocr_text.txt",
        help="Glob pattern used when --input points to a directory.",
    )

    rag_query = rag_sub.add_parser("query", help="Query the financial RAG store.")
    rag_query.add_argument("--query", required=True, help="Question to ask.")
    rag_query.add_argument("--ticker", help="Optional ticker override.")
    rag_query.add_argument("--year", help="Optional year override.")
    rag_query.add_argument("--quarter", help="Optional quarter override, e.g. Q4.")
    rag_query.add_argument(
        "--mode",
        choices=["global", "local", "hybrid"],
        default="hybrid",
        help="Retrieval mode.",
    )

    rag_dashboard = rag_sub.add_parser("dashboard", help="Launch the RAG dashboard.")
    rag_dashboard.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Streamlit server port.",
    )

    analyze = subparsers.add_parser(
        "analyze",
        help="Generate a cached Markdown financial report from OCR/RAG source documents.",
    )
    analyze.add_argument("--ticker", required=True, help="Ticker symbol, e.g. FPT.")
    analyze.add_argument("--year", required=True, help="Financial report year, e.g. 2025.")
    analyze.add_argument("--quarter", required=True, help="Quarter label, e.g. Q1 or Q4.")

    crawl_vnstock = subparsers.add_parser(
        "crawl-vnstock",
        help="Incrementally sync or fully refresh OHLCV data into data/vnstock.db.",
    )
    crawl_vnstock.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers or VN30. Empty uses the built-in watchlist.",
    )
    crawl_vnstock.add_argument(
        "--replace-existing",
        action="store_true",
        help="Fetch full history and replace existing rows for each selected ticker.",
    )
    crawl_vnstock.add_argument(
        "--max-requests-per-minute",
        type=int,
        default=20,
        help="Throttle market data requests to avoid hitting the upstream rate limit.",
    )

    crawl_news = subparsers.add_parser(
        "crawl-news",
        help="Crawl CafeF-style news into data/news.db for an inclusive day window.",
    )
    crawl_news.add_argument(
        "--news-days",
        type=int,
        default=10,
        help="Inclusive news window in calendar days ending today.",
    )
    crawl_news.add_argument(
        "--source",
        default="cafef",
        help="News source to crawl. Default: cafef.",
    )

    return parser


async def _main() -> None:
    _ensure_loop_policy()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "backtest":
            await handle_backtest(args)
        elif args.command == "backtest-cognitive":
            await handle_backtest_cognitive(args)
        elif args.command in {"sync", "prepare"}:
            await handle_sync(args)
        elif args.command == "rag" and args.rag_command == "index":
            await handle_rag_index(args)
        elif args.command == "rag" and args.rag_command == "query":
            await handle_rag_query(args)
        elif args.command == "rag" and args.rag_command == "dashboard":
            handle_rag_dashboard(args)
        elif args.command == "analyze":
            await handle_analyze(args)
        elif args.command == "crawl-vnstock":
            handle_crawl_vnstock(args)
        elif args.command == "crawl-news":
            handle_crawl_news(args)
        else:  # pragma: no cover - argparse should guard this
            parser.error(f"Unsupported command: {args.command}")
    finally:
        try:
            await llm_core.close_session()
        except Exception:
            pass
        await _close_tracking_news_session()


if __name__ == "__main__":
    asyncio.run(_main())
