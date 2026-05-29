"""Schema validation and repair loop for converting raw analyst text into AnalysisCard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import ValidationError

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.governance.schemas import AnalysisCard
from vnstock.core.llm import LLMError, call_llm

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"(\{[\s\S]*\})")
_ACTION_LINE_RE = re.compile(r"(?:^|\n)\s*(?:action|hành động|khuyến nghị)\s*[:=]\s*([A-Za-z_À-ỹ]+)", re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"(?:^|\n)\s*(?:confidence_raw|confidence|độ tin cậy)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_UPSIDE_RE = re.compile(r"(?:^|\n)\s*(?:upside_pct|upside|mức tăng kỳ vọng)\s*[:=]\s*(-?[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_DOWNSIDE_RE = re.compile(r"(?:^|\n)\s*(?:downside_pct|downside|mức giảm rủi ro)\s*[:=]\s*(-?[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_EVIDENCE_RE = re.compile(r"(?:^|\n)\s*(?:evidence_ids|evidence|bằng chứng)\s*[:=]\s*(.+)", re.IGNORECASE)


@dataclass(slots=True)
class SchemaValidator:
    """Repair raw analyst output until it becomes a valid AnalysisCard."""

    config: CognitiveConfig = CognitiveConfig()
    max_retries: int = 2
    temperature: float = 0.0

    async def validate(
        self,
        *,
        raw_text: str,
        agent_name: str,
        ticker: str,
        ref_date: str,
    ) -> AnalysisCard:
        """Return a valid AnalysisCard or raise when validation cannot be recovered."""

        errors: list[str] = []
        candidate_text = raw_text.strip()

        for payload in self._deterministic_candidates(
            candidate_text,
            agent_name=agent_name,
            ticker=ticker,
            ref_date=ref_date,
        ):
            try:
                return AnalysisCard.model_validate(payload)
            except (ValidationError, ValueError) as exc:
                errors.append(str(exc))

        for attempt in range(self.max_retries):
            try:
                candidate_text = await self._repair_with_retry(
                    raw_text=candidate_text,
                    agent_name=agent_name,
                    ticker=ticker,
                    ref_date=ref_date,
                    error_message=errors[-1] if errors else "invalid payload",
                )
            except LLMError as exc:
                errors.append(str(exc))
                break

            for payload in self._deterministic_candidates(
                candidate_text,
                agent_name=agent_name,
                ticker=ticker,
                ref_date=ref_date,
            ):
                try:
                    return AnalysisCard.model_validate(payload)
                except (ValidationError, ValueError) as exc:
                    errors.append(str(exc))

        return await self._fallback_extract(
            raw_text=raw_text,
            agent_name=agent_name,
            ticker=ticker,
            ref_date=ref_date,
            errors=errors,
        )

    def _extract_json_payload(self, text: str) -> dict[str, Any]:
        fenced = _JSON_FENCE_RE.search(text)
        if fenced:
            return json.loads(fenced.group(1))

        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        match = _JSON_OBJECT_RE.search(text)
        if not match:
            raise ValueError("No JSON object found in analyst output")
        return json.loads(match.group(1))

    def _deterministic_candidates(
        self,
        text: str,
        *,
        agent_name: str,
        ticker: str,
        ref_date: str,
    ) -> Iterable[dict[str, Any]]:
        seen: set[str] = set()

        def _emit(payload: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
            if not isinstance(payload, dict):
                return []
            normalized = self._normalize_payload(
                payload,
                agent_name=agent_name,
                ticker=ticker,
                ref_date=ref_date,
            )
            key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                return []
            seen.add(key)
            return [normalized]

        try:
            yield from _emit(self._extract_json_payload(text))
        except (json.JSONDecodeError, ValueError):
            pass

        for blob in self._iter_balanced_json_objects(text):
            try:
                yield from _emit(json.loads(blob))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        yield from _emit(self._extract_labeled_payload(text))

    @staticmethod
    def _iter_balanced_json_objects(text: str) -> Iterable[str]:
        start = None
        depth = 0
        in_string = False
        escaped = False
        for idx, ch in enumerate(text):
            if ch == '"' and not escaped:
                in_string = not in_string
            if ch == "\\" and not escaped:
                escaped = True
                continue
            escaped = False
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start : idx + 1]
                    start = None

    def _extract_labeled_payload(self, text: str) -> dict[str, Any] | None:
        action_match = _ACTION_LINE_RE.search(text)
        if not action_match:
            return None

        payload: dict[str, Any] = {
            "action": action_match.group(1).strip().upper(),
            "reasoning": text.strip(),
            "evidence_ids": [],
            "analysis_steps": [],
        }
        if confidence_match := _CONFIDENCE_RE.search(text):
            payload["confidence_raw"] = float(confidence_match.group(1))
        if upside_match := _UPSIDE_RE.search(text):
            payload["upside_pct"] = float(upside_match.group(1))
        if downside_match := _DOWNSIDE_RE.search(text):
            payload["downside_pct"] = float(downside_match.group(1))
        if evidence_match := _EVIDENCE_RE.search(text):
            raw_evidence = evidence_match.group(1).strip()
            payload["evidence_ids"] = [item.strip(" -[]\"") for item in re.split(r"[,;]", raw_evidence) if item.strip()]

        steps = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^(?:\d+[\.)]|-\s+Bước|Bước\s+\d+)", stripped, flags=re.IGNORECASE):
                steps.append(stripped)
        if steps:
            payload["analysis_steps"] = steps[:6]
        return payload

    @staticmethod
    def _normalize_payload(
        payload: dict[str, Any],
        *,
        agent_name: str,
        ticker: str,
        ref_date: str,
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized.setdefault("agent_name", agent_name)
        normalized.setdefault("ticker", ticker)
        normalized.setdefault("ref_date", ref_date)
        normalized.setdefault("action", "PASS")
        normalized.setdefault("confidence_raw", 50)
        normalized.setdefault("confidence_calibrated", None)
        normalized.setdefault("upside_pct", 0)
        normalized.setdefault("downside_pct", 0)
        normalized.setdefault("reasoning", str(payload.get("reasoning") or payload.get("raw_text") or "Không có reasoning chi tiết."))

        evidence_ids = normalized.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        normalized["evidence_ids"] = [str(item) for item in evidence_ids if str(item).strip()]

        analysis_steps = normalized.get("analysis_steps")
        if not isinstance(analysis_steps, list):
            legacy_steps = normalized.get("_thought_process")
            analysis_steps = legacy_steps if isinstance(legacy_steps, list) else []
        normalized["analysis_steps"] = [str(item) for item in analysis_steps if str(item).strip()]
        normalized.pop("_thought_process", None)
        return normalized

    async def _repair_with_retry(
        self,
        *,
        raw_text: str,
        agent_name: str,
        ticker: str,
        ref_date: str,
        error_message: str,
    ) -> str:
        prompt = (
            "Đầu ra analyst trước đó không vượt qua bước kiểm tra AnalysisCard. "
            "Hãy chỉ trả về đúng một JSON object hợp lệ theo mẫu sau:\n"
            "{\n"
            f'  "agent_name": "{agent_name}",\n'
            f'  "ticker": "{ticker}",\n'
            f'  "ref_date": "{ref_date}",\n'
            '  "action": "PASS",\n'
            '  "confidence_raw": 50,\n'
            '  "confidence_calibrated": null,\n'
            '  "upside_pct": 0,\n'
            '  "downside_pct": 0,\n'
            '  "reasoning": "...",\n'
            '  "evidence_ids": ["..."],\n'
            '  "analysis_steps": ["..."]\n'
            "}\n\n"
            f"Lỗi kiểm tra:\n{error_message}\n\n"
            f"Đầu ra gốc:\n{raw_text}"
        )
        try:
            return await call_llm(
                system_prompt=(
                    "Bạn sửa đầu ra analyst thành JSON AnalysisCard hợp lệ. "
                    "Chỉ trả về JSON, không văn xuôi, không markdown fence."
                ),
                user_prompt=prompt,
                model=self.config.validator_model,
                temperature=self.temperature,
                
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            raise LLMError(f"schema validator repair failed: {exc}") from exc

    async def _fallback_extract(
        self,
        *,
        raw_text: str,
        agent_name: str,
        ticker: str,
        ref_date: str,
        errors: list[str],
    ) -> AnalysisCard:
        prompt = (
            "Hãy trích xuất một AnalysisCard hợp lệ từ ghi chú analyst thô. "
            "Nếu thiếu trường, hãy suy luận theo hướng thận trọng mà không dùng thông tin ngoài ghi chú. "
            "Chỉ trả về JSON.\n\n"
            f"agent_name={agent_name}\n"
            f"ticker={ticker}\n"
            f"ref_date={ref_date}\n"
            f"Các lỗi kiểm tra trước đó={json.dumps(errors, ensure_ascii=False)}\n\n"
            f"Ghi chú analyst thô:\n{raw_text}"
        )
        try:
            extracted = await call_llm(
                system_prompt=(
                    "Bạn là bộ trích xuất JSON nghiêm ngặt cho AnalysisCard. "
                    "Hãy trả về đúng một JSON object hợp lệ và không thêm gì khác."
                ),
                user_prompt=prompt,
                model=self.config.validator_model,
                temperature=0.0,
                
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            raise LLMError(f"schema validator fallback failed: {exc}") from exc

        try:
            payload = self._extract_json_payload(extracted)
            payload.setdefault("agent_name", agent_name)
            payload.setdefault("ticker", ticker)
            payload.setdefault("ref_date", ref_date)
            trace = payload.get("analysis_steps")
            if not isinstance(trace, list):
                legacy_trace = payload.get("_thought_process")
                trace = legacy_trace if isinstance(legacy_trace, list) else []
            payload["analysis_steps"] = [*trace, "schema_validator:fallback_extract"]
            return AnalysisCard.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ValueError(f"fallback extractor could not produce a valid AnalysisCard: {exc}") from exc


__all__ = ["SchemaValidator"]
