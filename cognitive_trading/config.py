from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import models as shared_models
from config import paths as shared_paths
from config import risk_limits as shared_risk_limits
from config import trading as shared_trading


@dataclass(frozen=True)
class CognitiveConfig:
    """Standalone config derived from the shared project defaults."""

    start_cash_vnd: float = shared_trading.portfolio_cash
    lot_size: int = shared_trading.lot_size
    settlement_lag_days: int = shared_trading.settlement_lag_days
    buy_fee_rate: float = shared_trading.buy_fee_rate
    sell_fee_rate: float = shared_trading.sell_fee_rate

    planner_model: str = shared_models.t3_argument_model

    macro_analyst_model: str = shared_models.t2_macro_model
    news_analyst_model: str = shared_models.t2_news_model
    financial_analyst_model: str = shared_models.t2_financial_model
    technical_analyst_model: str = shared_models.t2_technical_model
    quant_analyst_model: str = shared_models.t2_quant_model

    validator_model: str = shared_models.t3_argument_model
    debate_model: str = shared_models.t3_debate_model
    cio_model: str = shared_models.t4_cio_model
    reflection_model: str = shared_models.t3_argument_model
    report_model: str = shared_models.daily_report_model

    llm_concurrency: int = shared_models.llm_concurrency

    max_position_pct: float = shared_risk_limits.max_position_pct
    min_cash_reserve_pct: float = shared_risk_limits.min_cash_reserve_pct
    stop_loss_pct: float = shared_risk_limits.stop_loss_pct
    max_drawdown_pct: float = shared_risk_limits.max_drawdown_pct

    output_root: Path = field(
        default_factory=lambda: shared_paths.backtest_results_dir / "cognitive"
    )
    memory_db_path: Path = field(default_factory=lambda: shared_paths.cognitive_db_path)
    daily_dir: Path = field(init=False)
    ledgers_dir: Path = field(init=False)
    state_dir: Path = field(init=False)
    memory_dir: Path = field(init=False)
    playbooks_dir: Path = field(init=False)
    snapshots_dir: Path = field(init=False)
    equity_curve_path: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "daily_dir", self.output_root / "daily")
        object.__setattr__(self, "ledgers_dir", self.output_root / "ledgers")
        object.__setattr__(self, "state_dir", self.output_root / "state")
        object.__setattr__(self, "memory_dir", self.memory_db_path.parent)
        object.__setattr__(self, "playbooks_dir", self.output_root / "playbooks")
        object.__setattr__(self, "snapshots_dir", self.output_root / "state_snapshots")
        object.__setattr__(self, "equity_curve_path", self.output_root / "equity_curve.json")


cognitive = CognitiveConfig()

__all__ = ["CognitiveConfig", "cognitive"]
