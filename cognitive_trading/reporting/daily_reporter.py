"""Daily Markdown report generation for cognitive_trading sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from vnstock.core.llm import LLMError, call_llm


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


def _to_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_vnd_exact(value: Any) -> str | None:
    amount = _to_decimal(value)
    if amount is None:
        return None
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    normalized = format(quantized, "f")
    integer, _, fraction = normalized.partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    if fraction == "00":
        return f"{grouped} VND"
    return f"{grouped},{fraction} VND"


def _format_vnd_millions(value: Any) -> str | None:
    amount = _to_decimal(value)
    if amount is None:
        return None
    millions = (amount / Decimal("1000000")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{format(millions, 'f').replace('.', ',')} triệu VND"


@dataclass(slots=True)
class DailyReporter:
    """Render a daily session report with LLM generation and deterministic fallback."""

    config: CognitiveConfig = CognitiveConfig()
    temperature: float = 0.1

    async def generate(
        self,
        *,
        trade_date: str,
        day_summary: Mapping[str, Any],
        trade_results: Sequence[Mapping[str, Any]],
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        normalized_envelope: Mapping[str, Any] | None = None,
    ) -> str:
        """Return the daily Markdown report for one trading session."""

        prompt_payload = self._prompt_payload(
            trade_date=trade_date,
            day_summary=day_summary,
            trade_results=trade_results,
            analysis_payloads=analysis_payloads,
            risk_report=risk_report,
            normalized_envelope=normalized_envelope,
        )
        if not prompt_payload["top_trades"] and not prompt_payload["debates"] and not prompt_payload["agent_viewpoints"]:
            return self._fallback_report(
                trade_date=trade_date,
                day_summary=day_summary,
                trade_results=trade_results,
                analysis_payloads=analysis_payloads,
                risk_report=risk_report,
                normalized_envelope=normalized_envelope,
            )
        try:
            report = await call_llm(
                system_prompt=(
                    "Bạn là chuyên gia phân tích tài chính đang viết memo học thuật cho khóa luận về multi-agent hỗ trợ phân tích và đầu tư chứng khoán. "
                    "Toàn bộ báo cáo phải bằng tiếng Việt, giọng điệu phân tích, súc tích, nghiêm túc, không phóng đại, không dùng văn phong marketing AI. "
                    "Chỉ sử dụng dữ liệu JSON được cung cấp. Không bịa thêm giao dịch, tranh luận, agent, playbook hay rủi ro không có trong dữ liệu. "
                    "Mọi số tiền phải sao chép nguyên văn từ các trường *_display trong DATA; không tự quy đổi đơn vị, không tự đổi triệu thành tỷ."
                ),
                user_prompt=(
                    "Viết báo cáo Markdown với đúng thứ tự các mục sau:\n"
                    f"# Báo cáo Cognitive Trading ngày {trade_date}\n"
                    "## Bối cảnh thị trường\n"
                    "## Tín hiệu nổi bật\n"
                    "## Quyết định giao dịch\n"
                    "## Trí nhớ 5 phiên gần nhất\n"
                    "## Playbook / chiến thuật đang kích hoạt\n"
                    "## Tranh luận và bất đồng\n"
                    "## Rủi ro và kế hoạch tiếp theo\n\n"
                    "Yêu cầu: \n"
                    "- Giữ cùng format chung như các workflow khác, nhưng giọng văn phải thể hiện rõ bản sắc multi-agent của cognitive.\n"
                    "- Trong phần quyết định giao dịch, phải làm rõ góc nhìn agent, CIO và tác động thực tế lên danh mục.\n"
                    "- Nếu thiếu dữ liệu ở một mục, phải nói rõ điều đó bằng tiếng Việt.\n"
                    "- Không viết như blog marketing; viết như memo phân tích cho giảng viên/hội đồng.\n"
                    "- Khi nhắc đến tiền, chỉ được dùng đúng chuỗi ở các trường *_display trong DATA; không tự thêm 'tỷ', 'triệu' hay viết lại số theo cách khác.\n\n"
                    f"DATA:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)}"
                ),
                model=self.config.report_model,
                temperature=self.temperature,
                
            )
            return _normalize_markdown_report(report)
        except LLMError:
            return self._fallback_report(
                trade_date=trade_date,
                day_summary=day_summary,
                trade_results=trade_results,
                analysis_payloads=analysis_payloads,
                risk_report=risk_report,
                normalized_envelope=normalized_envelope,
            )

    @staticmethod
    def _prompt_payload(
        *,
        trade_date: str,
        day_summary: Mapping[str, Any],
        trade_results: Sequence[Mapping[str, Any]],
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        normalized_envelope: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        debated = []
        calibration_updates = risk_report.get("calibration_updates") or []
        agent_viewpoints = []
        cio_summaries = []
        for ticker, payload in sorted(analysis_payloads.items()):
            for card in payload.get("cards", []) or []:
                if not isinstance(card, Mapping):
                    continue
                agent_viewpoints.append(
                    {
                        "ticker": ticker,
                        "agent_name": card.get("agent_name"),
                        "action": card.get("action"),
                        "confidence": card.get("confidence_calibrated") or card.get("confidence_raw"),
                        "reasoning": card.get("reasoning"),
                        "analysis_steps": card.get("analysis_steps") or card.get("_thought_process") or [],
                        "evidence_ids": card.get("evidence_ids") or [],
                    }
                )
            debate = payload.get("debate")
            if isinstance(debate, Mapping) and debate.get("triggered"):
                debated.append(
                    {
                        "ticker": ticker,
                        "winner": debate.get("winner"),
                        "verdict": debate.get("verdict"),
                        "confidence": debate.get("confidence"),
                        "summary": debate.get("summary"),
                    }
                )
            cio = payload.get("cio_decision")
            if isinstance(cio, Mapping):
                cio_summaries.append(
                    {
                        "ticker": ticker,
                        "action": cio.get("action"),
                        "weight_pct": cio.get("weight_pct"),
                        "reasoning": cio.get("reasoning"),
                        "playbook_id": cio.get("playbook_id"),
                    }
                )

        top_trades = []
        for item in sorted(
            [dict(item) for item in trade_results],
            key=lambda entry: float(entry.get("total_cost") or 0.0),
            reverse=True,
        )[:5]:
            trade_payload = dict(item)
            price_display = _format_vnd_exact(trade_payload.get("price"))
            total_cost_display = _format_vnd_exact(trade_payload.get("total_cost"))
            total_cost_million_display = _format_vnd_millions(trade_payload.get("total_cost"))
            if price_display is not None:
                trade_payload["price_display"] = price_display
            if total_cost_display is not None:
                trade_payload["total_cost_display"] = total_cost_display
            if total_cost_million_display is not None:
                trade_payload["total_cost_million_display"] = total_cost_million_display
            top_trades.append(trade_payload)

        summary_payload = dict(day_summary)
        for field in ("nav", "cash", "invested"):
            exact_display = _format_vnd_exact(summary_payload.get(field))
            million_display = _format_vnd_millions(summary_payload.get(field))
            if exact_display is not None:
                summary_payload[f"{field}_display"] = exact_display
            if million_display is not None:
                summary_payload[f"{field}_million_display"] = million_display
        memory_context = (normalized_envelope or {}).get("metadata", {}).get("memory_context") if isinstance(normalized_envelope, Mapping) else None
        return {
            "trade_date": trade_date,
            "summary": summary_payload,
            "top_trades": top_trades,
            "debates": debated[:5],
            "agent_viewpoints": agent_viewpoints[:20],
            "cio_summaries": cio_summaries[:10],
            "risk_report": dict(risk_report),
            "calibration_updates": list(calibration_updates) if isinstance(calibration_updates, Sequence) else [],
            "memory_context": dict(memory_context or {}),
            "normalized_artifact": dict(normalized_envelope or {}),
        }

    @staticmethod
    def _fallback_report(
        *,
        trade_date: str,
        day_summary: Mapping[str, Any],
        trade_results: Sequence[Mapping[str, Any]],
        analysis_payloads: Mapping[str, Mapping[str, Any]],
        risk_report: Mapping[str, Any],
        normalized_envelope: Mapping[str, Any] | Any | None,
    ) -> str:
        if normalized_envelope is not None and hasattr(normalized_envelope, "model_dump"):
            normalized_envelope = normalized_envelope.model_dump(mode="json")
        nav = float(day_summary.get("nav") or 0.0)
        cash = float(day_summary.get("cash") or 0.0)
        return_pct = float(day_summary.get("return_pct") or 0.0)
        daily_return_pct = float(day_summary.get("daily_return_pct") or 0.0)

        top_trades = sorted(
            [dict(item) for item in trade_results],
            key=lambda item: float(item.get("total_cost") or 0.0),
            reverse=True,
        )[:5]

        agent_lines: list[str] = []
        cio_lines: list[str] = []
        debate_lines: list[str] = []
        confidence_lines: list[str] = []
        for ticker, payload in sorted(analysis_payloads.items()):
            for card in payload.get("cards", []) or []:
                if not isinstance(card, Mapping):
                    continue
                agent_lines.append(
                    "- "
                    f"{ticker} / {card.get('agent_name')}: action={card.get('action')}, "
                    f"confidence={card.get('confidence_calibrated') or card.get('confidence_raw')}, "
                    f"reasoning={card.get('reasoning')}"
                )
                confidence_lines.append(
                    "- "
                    f"{ticker} / {card.get('agent_name')}: confidence={card.get('confidence_calibrated') or card.get('confidence_raw')}"
                )
            cio = payload.get("cio_decision")
            if isinstance(cio, Mapping):
                cio_lines.append(
                    "- "
                    f"{ticker}: action={cio.get('action')}, weight={cio.get('weight_pct')}, "
                    f"reasoning={cio.get('reasoning')}"
                )
            debate = payload.get("debate")
            if isinstance(debate, Mapping) and debate.get("triggered"):
                debate_lines.append(
                    "- "
                    f"{ticker}: winner={debate.get('winner')}, verdict={debate.get('verdict')}, "
                    f"summary={debate.get('summary')}"
                )

        risk_lines: list[str] = []
        for blocked in risk_report.get("blocked_orders", []):
            if isinstance(blocked, Mapping):
                risk_lines.append(
                    "- "
                    f"{blocked.get('ticker')}: {blocked.get('block_reason') or blocked.get('reason') or 'Lệnh bị chặn'}"
                )
        for hit in risk_report.get("stop_loss_hits", []):
            if isinstance(hit, Mapping):
                risk_lines.append(
                    f"- Theo dõi stop-loss {hit.get('ticker')}: loss_pct={hit.get('loss_pct')}"
                )
        if risk_report.get("drawdown_halt"):
            risk_lines.append(
                "- Đang kích hoạt drawdown halt: "
                f"{risk_report.get('drawdown_pct')}% >= giới hạn {risk_report.get('limits', {}).get('max_drawdown_pct')}%."
            )

        trade_lines = []
        for item in top_trades:
            price_display = _format_vnd_exact(item.get("price")) or str(item.get("price"))
            total_cost_display = _format_vnd_exact(item.get("total_cost")) or str(item.get("total_cost"))
            total_cost_million_display = _format_vnd_millions(item.get("total_cost"))
            total_clause = total_cost_display
            if total_cost_million_display:
                total_clause = f"{total_clause} ({total_cost_million_display})"
            trade_lines.append(
                "- "
                f"{item.get('ticker')} {item.get('action')} qty={item.get('quantity')} "
                f"giá={price_display} tổng={total_clause} "
                f"trạng thái={item.get('status')}"
            )

        calibration_lines: list[str] = []
        calibration_updates = risk_report.get("calibration_updates") or []
        for update in calibration_updates:
            if isinstance(update, Mapping):
                calibration_lines.append(
                    "- "
                    f"{update.get('agent_name')} / {update.get('sector')}: "
                    f"win_rate={update.get('win_rate')}, total_calls={update.get('total_calls')}"
                )

        decision_lines = []
        if trade_lines:
            decision_lines.extend(trade_lines)
        if cio_lines:
            decision_lines.extend(cio_lines)
        if confidence_lines:
            decision_lines.extend(confidence_lines[:5])

        memory_context = dict((normalized_envelope or {}).get("metadata", {}).get("memory_context") or {}) if isinstance(normalized_envelope, Mapping) else {}
        recent_memory_lines = []
        for ticker, sessions in sorted((memory_context.get("recent_sessions_by_ticker") or {}).items()):
            if not isinstance(sessions, list) or not sessions:
                continue
            latest = sessions[0]
            recent_memory_lines.append(
                f"- {ticker}: gần nhất {latest.get('trade_date')} action={latest.get('action')} pnl_t5={latest.get('pnl_t5')} alpha={latest.get('alpha_vs_vn30')}"
            )
        playbook_lines = []
        for item in memory_context.get("active_playbooks", []) or []:
            if isinstance(item, Mapping):
                playbook_lines.append(
                    f"- #{item.get('id')}: {item.get('name')} | action={item.get('recommended_action')} | avg_alpha={item.get('avg_alpha')}"
                )
        next_steps = [
            "- Tiếp tục theo dõi các mã đã phát sinh giao dịch hoặc tranh luận trong phiên gần nhất.",
            "- So sánh diễn biến tiếp theo của giá với mức độ tin cậy mà các agent đã đưa ra.",
        ]
        if calibration_lines:
            next_steps.extend(calibration_lines)
        else:
            next_steps.append("- Chưa có cập nhật calibration trong phiên này.")

        return "\n".join(
            [
                f"# Báo cáo Cognitive Trading ngày {trade_date}",
                "",
                "## Bối cảnh thị trường",
                f"- NAV: {_format_vnd_exact(nav) or f'{nav:,.2f} VND'} ({_format_vnd_millions(nav) or 'không rõ'})",
                f"- Tiền mặt: {_format_vnd_exact(cash) or f'{cash:,.2f} VND'} ({_format_vnd_millions(cash) or 'không rõ'})",
                f"- Lợi nhuận lũy kế: {return_pct:.2f}% | Lợi nhuận trong ngày: {daily_return_pct:.2f}%",
                f"- Mã được gắn cờ quan trọng: {int(day_summary.get('flagged_tickers') or 0)} | Mã có tranh luận: {int(day_summary.get('debated_tickers') or 0)}",
                "",
                "## Tín hiệu nổi bật",
                *(agent_lines or ["- Chưa có tín hiệu nổi bật đủ rõ trong payload hiện tại."]),
                "",
                "## Quyết định giao dịch",
                *(decision_lines or ["- Không có quyết định giao dịch đáng chú ý trong phiên."]),
                "",
                "## Trí nhớ 5 phiên gần nhất",
                *(recent_memory_lines or ["- Chưa có trí nhớ 5 phiên gần nhất đủ điều kiện để hiển thị."]),
                "",
                "## Playbook / chiến thuật đang kích hoạt",
                *(playbook_lines or ["- Chưa có playbook active nào được kích hoạt trong phiên này."]),
                "",
                "## Tranh luận và bất đồng",
                *(debate_lines or ["- Không có tranh luận nổi bật hoặc bất đồng đáng kể được kích hoạt trong phiên này."]),
                "",
                "## Rủi ro và kế hoạch tiếp theo",
                *(risk_lines or ["- Không có cảnh báo rủi ro trọng yếu trong phiên."]),
                *next_steps,
            ]
        )


__all__ = ["DailyReporter"]
