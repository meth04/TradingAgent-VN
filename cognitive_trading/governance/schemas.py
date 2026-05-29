"""Pydantic schemas that normalize cognitive_trading decisions, analyst output, and workflow artifacts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vnstock.agents.prompting import Action, normalize_action

ORDER_ACTIONS = {Action.BUY, Action.BUY_MORE, Action.SELL, Action.TRIMMING}
ARTIFACT_VERSION = "1.0"
ARTIFACT_ORIGINS = {"native", "adapted"}
ANALYSIS_DEPTHS = {"rich", "sparse"}


class CognitiveSchema(BaseModel):
    """Base schema with strict validation for downstream governance steps."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class AnalysisCard(CognitiveSchema):
    """Canonical analyst output before calibration and debate."""

    agent_name: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    ref_date: str
    action: Action
    confidence_raw: float = Field(ge=0.0, le=100.0)
    confidence_calibrated: float | None = Field(default=None, ge=0.0, le=100.0)
    upside_pct: float
    downside_pct: float
    reasoning: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    analysis_steps: list[str] = Field(default_factory=list)

    @field_validator("agent_name")
    @classmethod
    def _normalize_agent_name(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("ref_date")
    @classmethod
    def _validate_ref_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("action", mode="before")
    @classmethod
    def _validate_action(cls, value: str | Action) -> Action:
        normalized = normalize_action(value)
        if normalized is None:
            raise ValueError("action must use the vnstock mandatory action set")
        return normalized

    @model_validator(mode="before")
    @classmethod
    def _normalize_analysis_steps_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        trace = value.get("analysis_steps")
        if trace is None:
            trace = value.get("_thought_process")
        if trace is None:
            trace = []
        value["analysis_steps"] = list(trace) if isinstance(trace, list) else []
        # Remove _thought_process to avoid extra="forbid" rejection
        value.pop("_thought_process", None)
        return value

    @property
    def thought_process(self) -> list[str]:
        """Backward-compatible accessor for older callers/tests."""

        return list(self.analysis_steps)

    def legacy_payload(self) -> dict[str, Any]:
        """Return a backward-compatible serialized shape including _thought_process."""

        payload = self.model_dump()
        payload["_thought_process"] = list(self.analysis_steps)
        return payload


class NormalizedAgentArtifact(CognitiveSchema):
    """Workflow-agnostic, dashboard-friendly per-agent artifact."""

    version: str = Field(default=ARTIFACT_VERSION)
    artifact_origin: Literal["native", "adapted"] = "native"
    analysis_depth: Literal["rich", "sparse"] = "rich"
    workflow: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    ref_date: str
    action: Action | None = None
    confidence_raw: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence_calibrated: float | None = Field(default=None, ge=0.0, le=100.0)
    upside_pct: float | None = None
    downside_pct: float | None = None
    reasoning_summary: str = Field(default="")
    key_considerations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    analysis_steps: list[str] = Field(default_factory=list)
    source_agents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workflow", "agent_name")
    @classmethod
    def _normalize_text_fields(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("ref_date")
    @classmethod
    def _validate_ref_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action_optional(cls, value: str | Action | None) -> Action | None:
        if value is None:
            return None
        normalized = normalize_action(value)
        if normalized is None:
            raise ValueError("action must use the vnstock mandatory action set")
        return normalized

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        trace = value.get("analysis_steps")
        if trace is None:
            trace = value.get("_thought_process")
        if trace is None:
            trace = []
        value["analysis_steps"] = list(trace) if isinstance(trace, list) else []

        reasoning_summary = value.get("reasoning_summary")
        if reasoning_summary in {None, ""}:
            reasoning_summary = value.get("reasoning") or value.get("raw_analysis") or ""
        value["reasoning_summary"] = str(reasoning_summary)

        considerations = value.get("key_considerations")
        if considerations is None:
            considerations = value.get("evidence_ids") or value.get("evidence") or []
        value["key_considerations"] = list(considerations) if isinstance(considerations, list) else []
        return value


class IntentTicket(CognitiveSchema):
    """Position intent produced by the CIO as a percent of NAV."""

    ticker: str = Field(min_length=1)
    action: Action
    weight_pct: float = Field(ge=0.0, le=100.0, description="Target portfolio weight as % NAV")
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str = Field(min_length=1)
    playbook_id: str | None = None

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("action", mode="before")
    @classmethod
    def _validate_action(cls, value: str | Action) -> Action:
        normalized = normalize_action(value)
        if normalized is None:
            raise ValueError("action must use the vnstock mandatory action set")
        return normalized


class OrderTicket(CognitiveSchema):
    """Executable order proposal with explicit VND pricing and totals."""

    ticker: str = Field(min_length=1)
    action: Action
    quantity: int = Field(ge=0)
    price: float = Field(ge=0.0, description="Order price in VND")
    total_cost: float = Field(ge=0.0, description="Total order value in VND")
    status: str = Field(pattern="^(APPROVED|BLOCKED)$")
    block_reason: str | None = None

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("action", mode="before")
    @classmethod
    def _validate_action(cls, value: str | Action) -> Action:
        normalized = normalize_action(value)
        if normalized not in ORDER_ACTIONS:
            raise ValueError("order actions must be BUY, BUY_MORE, SELL, or TRIMMING")
        return normalized

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _validate_block_reason(self) -> "OrderTicket":
        if self.status == "BLOCKED" and not self.block_reason:
            raise ValueError("block_reason is required when status is BLOCKED")
        if self.status == "APPROVED" and self.block_reason:
            raise ValueError("block_reason must be empty when status is APPROVED")
        return self


class WorkflowTickerArtifact(CognitiveSchema):
    """Normalized per-ticker artifact stored for both native and adapted workflows."""

    version: str = Field(default=ARTIFACT_VERSION)
    workflow: str = Field(min_length=1)
    artifact_origin: Literal["native", "adapted"] = "native"
    analysis_depth: Literal["rich", "sparse"] = "rich"
    ticker: str = Field(min_length=1)
    ref_date: str
    planner: dict[str, Any] | None = None
    cards: list[NormalizedAgentArtifact] = Field(default_factory=list)
    debate: dict[str, Any] | None = None
    cio_intent: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    trade: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workflow")
    @classmethod
    def _normalize_workflow(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("ref_date")
    @classmethod
    def _validate_ref_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class WorkflowArtifactEnvelope(CognitiveSchema):
    """Versioned workflow/day envelope for normalized archive persistence."""

    version: str = Field(default=ARTIFACT_VERSION)
    workflow: str = Field(min_length=1)
    artifact_origin: Literal["native", "adapted"] = "native"
    analysis_depth: Literal["rich", "sparse"] = "rich"
    as_of_date: str
    generated_at: str
    locale: str = "vi-VN"
    summary: dict[str, Any] = Field(default_factory=dict)
    portfolio_state: dict[str, Any] = Field(default_factory=dict)
    ledger: list[dict[str, Any]] = Field(default_factory=list)
    analysis: dict[str, WorkflowTickerArtifact] = Field(default_factory=dict)
    risk_report: dict[str, Any] = Field(default_factory=dict)
    calibration: list[dict[str, Any]] = Field(default_factory=list)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workflow")
    @classmethod
    def _normalize_workflow(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("as_of_date")
    @classmethod
    def _validate_as_of_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


__all__ = [
    "ARTIFACT_VERSION",
    "AnalysisCard",
    "IntentTicket",
    "NormalizedAgentArtifact",
    "OrderTicket",
    "WorkflowArtifactEnvelope",
    "WorkflowTickerArtifact",
]
