import sqlite3
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Text,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

from config import paths

paths.data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = paths.vnstock_db_path
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DB_URL, 
    connect_args={"check_same_thread": False, "timeout": 30} if "sqlite" in DB_URL else {},
    poolclass=NullPool if "sqlite" in DB_URL else None,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- 1. BẢNG DANH MỤC MÃ (Symbols) ---
class Symbol(Base):
    __tablename__ = "symbols"
    ticker = Column(String(10), primary_key=True)
    company_name = Column(String(255))
    exchange = Column(String(10))  # HOSE, HNX
    industry = Column(String(100))
    icb_name2 = Column(String(100))
    icb_name3 = Column(String(100))
    icb_name4 = Column(String(100))
    charter_capital = Column(BigInteger)
    outstanding_shares = Column(BigInteger)


# --- 2. BẢNG DỮ LIỆU LỊCH SỬ NGÀY (OHLCV) ---
class MarketDataDaily(Base):
    __tablename__ = "market_data_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), index=True)
    date = Column(DateTime, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    buy_foreign = Column(BigInteger, default=0)
    sell_foreign = Column(BigInteger, default=0)


class FinancialRatio(Base):
    __tablename__ = "financial_ratios"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), index=True, nullable=False)
    quarter = Column(String(10), index=True, nullable=False)
    trailing_eps = Column(Float)
    book_value_per_share = Column(Float)
    pe = Column(Float)
    pb = Column(Float)
    beta = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    debt_equity = Column(Float)
    net_revenue = Column(Float)
    net_profit = Column(Float)
    revenue_yoy = Column(Float)
    net_profit_yoy = Column(Float)
    updated_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "quarter", name="uq_financial_ratios_ticker_quarter"),
    )


# --- 3. BẢNG DỮ LIỆU PHÚT (Realtime Snapshot) ---
class MarketDataIntraday(Base):
    __tablename__ = "market_data_intraday"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    price = Column(Float)
    volume = Column(BigInteger)
    change_percent = Column(Float)  # % Tăng giảm so với tham chiếu


# --- 4. BẢNG LỊCH SỬ KHUYẾN NGHỊ (Agent Logs) ---
class AgentLog(Base):
    __tablename__ = "agent_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now)
    ticker = Column(String(10), index=True)
    action = Column(String(50))  # MUA / BÁN / QUAN SÁT
    confidence = Column(String(50))  # Tỷ trọng khuyến nghị
    reason = Column(Text)  # Lý do cốt lõi
    full_report_path = Column(String(255))  # Đường dẫn file báo cáo chi tiết (nếu cần)


# --- 5. BẢNG DAILY SENTIMENT ---
class DailySentiment(Base):
    __tablename__ = "daily_sentiment"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, index=True, nullable=False)
    ticker = Column(String(10), index=True, nullable=False)
    daily_score = Column(Float)
    confidence = Column(Float)
    impact_summary = Column(Text)

    __table_args__ = (UniqueConstraint("date", "ticker", name="uq_daily_sentiment"),)


class BacktestMetric(Base):
    __tablename__ = "backtest_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(50), nullable=False)
    ticker = Column(String(10), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    account_value = Column(Float)
    return_pct = Column(Float)
    total_pnl = Column(Float)
    win_rate = Column(Float)
    sharpe = Column(Float)
    trades = Column(Integer)


def _ensure_symbol_columns() -> None:
    if "sqlite" not in DB_URL:
        return

    with sqlite3.connect(DB_PATH) as connection:
        existing = {
            row[1]
            for row in connection.execute("PRAGMA table_info(symbols)").fetchall()
        }
        required_columns = {
            "icb_name2": "TEXT",
            "icb_name3": "TEXT",
            "icb_name4": "TEXT",
            "charter_capital": "BIGINT",
            "outstanding_shares": "BIGINT",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing:
                continue
            connection.execute(
                f"ALTER TABLE symbols ADD COLUMN {column_name} {column_type}"
            )
        connection.commit()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    _ensure_symbol_columns()
    print(f"Successfully initialized DB at {DB_PATH}")
