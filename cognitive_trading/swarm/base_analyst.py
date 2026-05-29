"""Abstract ReAct analyst base class for cognitive_trading intelligence agents."""

from __future__ import annotations

import inspect
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from vnstock.agents.prompting import Action, BACKTEST_CONTEXT
from vnstock.core.llm import LLMError, call_llm

ToolFunction = Callable[[str], Awaitable[Any] | Any]

_ACTION_SET = ", ".join(action.value for action in Action)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Named tool available to a ReAct analyst."""

    name: str
    description: str
    function: ToolFunction


@dataclass(frozen=True, slots=True)
class ReActTurn:
    """Parsed structure of a single ReAct model turn."""

    thought: str | None
    action: str | None
    action_input: str | None
    observations: tuple[str, ...]
    final_answer: str | None
    raw_text: str


class BaseAnalyst(ABC):
    """Shared ReAct loop for all cognitive_trading analyst agents."""

    agent_name: str
    analysis_brief: str

    def __init__(
        self,
        *,
        model: str,
        fallback_models: Sequence[str] | None = None,
        max_steps: int = 3,
        temperature: float = 0.1,
        config: CognitiveConfig | None = None,
    ) -> None:
        self.config = config or CognitiveConfig()
        self.model = model
        self.fallback_models = tuple(fallback_models or ())
        self.max_steps = max_steps
        self.temperature = temperature

    @abstractmethod
    def build_tools(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> Sequence[ToolSpec]:
        """Return the tool definitions available to this analyst."""

    def build_analysis_payload(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return the default payload included in the user prompt."""

        return {
            "ticker": ticker,
            "ref_date": ref_date,
            "context": context,
        }

    async def analyze(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> str:
        """Run the ReAct loop and return the analyst's raw final answer text."""

        tool_specs = list(self.build_tools(ticker=ticker, ref_date=ref_date, context=context))
        tool_map = {tool.name: tool for tool in tool_specs}
        scratchpad = ""
        last_response = ""

        for step in range(1, self.max_steps + 1):
            try:
                response = await call_llm(
                    system_prompt=self._build_system_prompt(tool_specs),
                    user_prompt=self._build_user_prompt(
                        ticker=ticker,
                        ref_date=ref_date,
                        context=context,
                        scratchpad=scratchpad,
                        step=step,
                    ),
                    model=self.model,
                    temperature=self.temperature,
                    
                )
            except LLMError as exc:
                raise LLMError(f"{self.agent_name} analyst failed: {exc}") from exc

            last_response = response.strip()
            parsed = self.parse_react_output(last_response)

            if parsed.final_answer:
                return parsed.final_answer.strip()

            if not parsed.action:
                scratchpad += self._format_trace(
                    parsed=parsed,
                    observation=(
                        "Lỗi định dạng: hãy trả lời bằng Thought + Action + Action Input, "
                        "hoặc Thought + Final Answer."
                    ),
                )
                continue

            observation = await self._invoke_tool(tool_map, parsed.action, parsed.action_input or "")
            scratchpad += self._format_trace(parsed=parsed, observation=observation)

        return await self._request_final_answer(
            ticker=ticker,
            ref_date=ref_date,
            context=context,
            scratchpad=scratchpad,
            last_response=last_response,
        )

    @classmethod
    def parse_react_output(cls, text: str) -> ReActTurn:
        """Parse bilingual ReAct blocks from a model turn."""

        return ReActTurn(
            thought=cls._extract_block(text, ("Thought", "Suy nghĩ", "Suy luận")),
            action=cls._extract_block(text, ("Action", "Hành động")),
            action_input=cls._extract_block(text, ("Action Input", "Đầu vào hành động")),
            observations=tuple(
                match.strip()
                for match in cls._extract_observations(text)
                if match.strip()
            ),
            final_answer=cls._extract_block(text, ("Final Answer", "Kết luận cuối")),
            raw_text=text,
        )

    @staticmethod
    def _extract_block(text: str, labels: str | tuple[str, ...]) -> str | None:
        if isinstance(labels, str):
            labels = (labels,)
        label_group = "|".join(re.escape(label) for label in labels)
        pattern = rf"^(?:{label_group}):\s*(.+?)(?=^[^\n:]+:\s|\Z)"
        match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
        if not match:
            return None
        value = match.group(1).strip()
        return value or None

    @staticmethod
    def _extract_observations(text: str) -> list[str]:
        pattern = r"^(?:Observation|Quan sát):\s*(.+?)(?=^[^\n:]+:\s|\Z)"
        return re.findall(pattern, text, flags=re.MULTILINE | re.DOTALL)

    async def _request_final_answer(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
        scratchpad: str,
        last_response: str,
    ) -> str:
        prompt = (
            self._build_user_prompt(
                ticker=ticker,
                ref_date=ref_date,
                context=context,
                scratchpad=scratchpad,
                step=self.max_steps + 1,
            )
            + "\n\nPhản hồi trước chưa kết thúc bằng Final Answer/Kết luận cuối. "
            + "Hãy trả về đúng định dạng:\nSuy luận: ...\nKết luận cuối: ...\n\n"
            + f"Phản hồi trước đó:\n{last_response}"
        )
        try:
            response = await call_llm(
                system_prompt=self._build_system_prompt(()),
                user_prompt=prompt,
                model=self.model,
                temperature=self.temperature,
                
            )
        except LLMError as exc:
            raise LLMError(f"{self.agent_name} analyst failed: {exc}") from exc

        parsed = self.parse_react_output(response.strip())
        if parsed.final_answer:
            return parsed.final_answer.strip()
        return response.strip()

    async def _invoke_tool(
        self,
        tool_map: Mapping[str, ToolSpec],
        action: str,
        action_input: str,
    ) -> str:
        normalized_action = action.strip()
        tool_spec = tool_map.get(normalized_action)
        if tool_spec is None:
            available = ", ".join(sorted(tool_map))
            return f"Không tìm thấy công cụ '{normalized_action}'. Công cụ khả dụng: {available}."

        try:
            result = tool_spec.function(action_input)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            return f"Công cụ '{normalized_action}' lỗi: {type(exc).__name__}: {exc}"

        if isinstance(result, (dict, list, tuple)):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)

    def _build_system_prompt(self, tool_specs: Sequence[ToolSpec]) -> str:
        tool_lines = "\n".join(
            f"- {tool.name}: {tool.description}" for tool in tool_specs
        ) or "- No external tools available."
        return (
            f"{BACKTEST_CONTEXT}\n\n"
            f"Bạn là analyst {self.agent_name} của cognitive_trading.\n"
            "Bạn phải tuân thủ vòng lặp ReAct nghiêm ngặt và tuyệt đối không dùng thông tin tương lai.\n"
            f"ref_date là ranh giới backtest. Coi ref_date là ngày hiện tại của bạn. "
            "Chỉ dùng bằng chứng có sẵn tại hoặc trước ref_date.\n"
            f"Các hành động cuối hợp lệ: {_ACTION_SET}.\n"
            f"Nhiệm vụ của bạn: {self.analysis_brief}\n\n"
            "Công cụ khả dụng:\n"
            f"{tool_lines}\n\n"
            "Định dạng bắt buộc cho mỗi lượt (ưu tiên tiếng Việt):\n"
            "Suy luận: <lập luận ngắn cho bước tiếp theo, viết bằng tiếng Việt>\n"
            "Hành động: <tên đúng của một công cụ>\n"
            "Đầu vào hành động: <chỉ dẫn thuần văn bản cho công cụ, viết bằng tiếng Việt nếu phù hợp>\n\n"
            "Tương thích ngược: Thought/Action/Action Input vẫn được chấp nhận nếu model dùng format cũ.\n\n"
            "Khi sẵn sàng kết thúc, hãy trả về:\n"
            "Suy luận: <kết luận ngắn bằng tiếng Việt>\n"
            'Kết luận cuối: {"action": "BUY|BUY_MORE|SELL|TRIMMING|PASS", "confidence_raw": 0-100, "upside_pct": số, "downside_pct": số, "reasoning": "...", "evidence_ids": ["..."], "analysis_steps": ["..."]}\n\n'
            "Nếu không chắc, dùng action=PASS và confidence_raw ở mức thận trọng. Không tự tạo Observation. Observation sẽ được chèn sau khi chạy công cụ."
        )

    def _build_user_prompt(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
        scratchpad: str,
        step: int,
    ) -> str:
        payload = self.build_analysis_payload(ticker=ticker, ref_date=ref_date, context=context)
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return (
            f"Ticker: {ticker}\n"
            f"ref_date (ngày hiện tại): {ref_date}\n"
            f"Bước: {step}\n\n"
            "Payload planner/ngữ cảnh:\n"
            f"{payload_json}\n\n"
            "ReAct trace trước đó:\n"
            f"{scratchpad or '(không có)'}"
        )

    @staticmethod
    def _format_trace(*, parsed: ReActTurn, observation: str) -> str:
        parts = []
        if parsed.thought:
            parts.append(f"Thought: {parsed.thought}")
        if parsed.action:
            parts.append(f"Action: {parsed.action}")
        if parsed.action_input:
            parts.append(f"Action Input: {parsed.action_input}")
        parts.append(f"Observation: {observation}")
        return "\n".join(parts) + "\n\n"


__all__ = ["BaseAnalyst", "ReActTurn", "ToolSpec"]
