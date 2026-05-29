from __future__ import annotations

import asyncio
import inspect
from typing import Dict, List, Sequence

from autogen_core.models import (
    AssistantMessage,
    CreateResult,
    LLMMessage,
    ModelCapabilities,
    ModelFamily,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
    ChatCompletionClient,
)
from autogen_agentchat.messages import TextMessage
from config import models
from vnstock.agents.prompting import BACKTEST_CONTEXT
from vnstock.workflows.base import AgentOutput
from vnstock.workflows.debate.argumentation import ArgumentationFramework, detect_attacks
from vnstock.workflows.debate.evidence import Evidence, extract_evidence_from_agent_output
from vnstock.workflows.utils import format_facts
from vnstock.core.llm import call_llm


def _render_transcript(messages: Sequence[LLMMessage]) -> str:
    lines: List[str] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            lines.append(f"[system] {msg.content}")
        elif isinstance(msg, UserMessage):
            lines.append(f"[{msg.source}] {msg.content}")
        elif isinstance(msg, AssistantMessage):
            lines.append(f"[{msg.source}] {msg.content}")
    return "\n".join(lines)


class VNStockModelClient(ChatCompletionClient):
    def __init__(
        self,
        model: str | None = None,
        fallback_models: List[str] | None = None,
        temperature: float = 0.2,
    ):
        super().__init__()
        self.model = model or models.t3_debate_model
        self.fallback_models = fallback_models or []
        self.temperature = temperature

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools=(),
        tool_choice="auto",
        json_output=None,
        extra_create_args={},
        cancellation_token=None,
    ) -> CreateResult:
        # Respect configured models for debate
        # Map to system+user prompts concatenated; keep it simple for now
        system_parts: List[str] = []
        user_parts: List[str] = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system_parts.append(m.content)
            elif isinstance(m, UserMessage):
                user_parts.append(str(m.content))
            elif isinstance(m, AssistantMessage):
                user_parts.append(str(m.content))
            elif isinstance(m, TextMessage):
                user_parts.append(str(m.content))
        system_prompt = "\n\n".join(system_parts) if system_parts else "Bạn là trợ lý phân tích tài chính hữu ích và phải trả lời bằng tiếng Việt."
        user_prompt = "\n\n".join(user_parts)
        content = await call_llm(
            system_prompt,
            user_prompt,
            model=self.model,
            temperature=self.temperature,
            
        )
        return CreateResult(
            finish_reason="stop",
            content=content,
            usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
            cached=False,
            logprobs=None,
            thought=None,
        )

    def create_stream(self, *args, **kwargs):  # pragma: no cover - streaming not needed here
        raise NotImplementedError

    async def close(self) -> None:
        return None

    def actual_usage(self) -> RequestUsage:
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def total_usage(self) -> RequestUsage:
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def count_tokens(self, messages: Sequence[LLMMessage], *, tools=()) -> int:
        return 0

    def remaining_tokens(self, messages: Sequence[LLMMessage], *, tools=()) -> int:
        return 0

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(vision=False, function_calling=False, json_output=False)

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            vision=False,
            function_calling=False,
            json_output=False,
            family=ModelFamily.ANY,
            structured_output=False,
            multiple_system_messages=True,
        )


_groupchat_runner = None  # module-level hook for monkeypatching in tests


async def run_autogen_debate(
    *,
    ticker: str,
    ref_date: str,
    agent_outputs: Dict[str, AgentOutput],
    llm_semaphore=None,
    model: str | None = None,
    rounds: int = 1,
    preformatted_facts: str | None = None,
) -> Dict[str, object]:
    debate_model = model or models.t3_debate_model
    rounds = max(1, int(rounds))  # allow 1 round (2 turns) to reduce latency
    facts = preformatted_facts if preformatted_facts is not None else format_facts(agent_outputs)
    debate_prompt = (
        f"{BACKTEST_CONTEXT}\n\n"
        "Hãy suy luận từng bước bằng tiếng Việt. 1) Rà soát các fact Tier-2. 2) Xây dựng lập luận nhất quán cho phe của mình. 3) Phản biện điểm mạnh nhất của đối phương bằng phản chứng. 4) Giữ giọng điệu chuyên nghiệp, tranh biện rõ ràng.\n"
        "Bạn là hội đồng Bull vs Bear. Tranh luận 1 vòng đầy đủ (Bull rồi Bear), ngắn gọn nhưng có lập luận rõ ràng.\n"
        "Đặt toàn bộ lập luận tường minh trong thẻ <thinking>...</thinking> trước khi kết luận để bắt buộc chain-of-thought hiển thị.\n"
        f"Ticker: {ticker}\nNgày phân tích (coi là ngày hiện tại): {ref_date}\n"
        "Bull: luận điểm tích cực, xác suất thắng và upside.\n"
        "Bear: tail risk, downside, phản biện dữ liệu.\n"
        "Kết thúc: mỗi bên chốt xác suất thắng thua và độ tin cậy."
    )

    async def _default_run_groupchat() -> str:
        try:
            from autogen_agentchat.agents import AssistantAgent
            from autogen_agentchat.teams import RoundRobinGroupChat
        except Exception:
            # Fallback: minimal single-shot transcript using default LLM
            system = "Bạn là hội đồng Bull vs Bear, hãy tóm tắt 3 vòng tranh luận hoàn toàn bằng tiếng Việt."
            user = f"{debate_prompt}\nDữ liệu:\n{facts}"
            return await call_llm(
                system,
                user,
                model=debate_model,
            )

        model_client = VNStockModelClient(
            model=debate_model,
            temperature=0.2,
        )
        bull = AssistantAgent(
            name="Bull",
            model_client=model_client,
            system_message=(
                f"{BACKTEST_CONTEXT} "
                "Hãy suy luận từng bước bằng tiếng Việt. 1) Rà soát fact Tier-2. 2) Xây dựng luận điểm bullish với xác suất và upside. 3) Phản biện điểm mạnh nhất của Bear bằng phản chứng. Giữ câu trả lời ngắn gọn."
            ),
        )
        bear = AssistantAgent(
            name="Bear",
            model_client=model_client,
            system_message=(
                f"{BACKTEST_CONTEXT} "
                "Hãy suy luận từng bước bằng tiếng Việt. 1) Rà soát fact Tier-2. 2) Xây dựng luận điểm bearish với tail risk và downside. 3) Phản biện điểm mạnh nhất của Bull bằng phản chứng. Giữ câu trả lời ngắn gọn."
            ),
        )
        task = f"{debate_prompt}\nDữ liệu:\n{facts}"
        groupchat = RoundRobinGroupChat(
            [bull, bear],
            max_turns=rounds * 2,
        )
        result = await groupchat.run(task=task)
        msg_seq = [m for m in getattr(result, "messages", [])]
        return _render_transcript(msg_seq)

    runner = _groupchat_runner or _default_run_groupchat
    try:
        transcript = await runner()
        if inspect.isawaitable(transcript):
            transcript = await transcript
    except Exception as exc:
        transcript = (
            "[DEBATE_FALLBACK] AutoGen debate không hoàn tất, chuyển sang transcript deterministic.\n"
            f"Lý do: {type(exc).__name__}: {exc}\n\n"
            f"Dữ liệu tranh luận:\n{facts}"
        )

    if not transcript or not transcript.strip():
        transcript = (
            "[DEBATE_FALLBACK] Không thu được transcript từ AutoGen, dùng transcript deterministic.\n\n"
            f"Dữ liệu tranh luận:\n{facts}"
        )

    evidence_lists = await asyncio.gather(
        *[extract_evidence_from_agent_output(ao, ref_date) for ao in agent_outputs.values()]
    )
    evidences: List[Evidence] = [ev for sub in evidence_lists for ev in sub]
    attacks = await detect_attacks(evidences)
    framework = ArgumentationFramework(evidences, attacks)
    extension = framework.compute_grounded_extension()
    net_score = framework.get_net_score(extension)
    verdict = framework.classify_verdict(net_score)
    prob_score = max(0.0, min(1.0, 0.5 + net_score / 20.0))

    summary_vi = (
        f"Phe Bull và Bear đã tranh luận trên dữ liệu Tier-2. Kết quả cuối: {verdict}, "
        f"điểm ròng={net_score:.2f}, xác suất chuẩn hóa={round(prob_score, 3):.3f}."
    )
    return {
        "transcript": transcript,
        "summary_vi": summary_vi,
        "net_score": net_score,
        "verdict": verdict,
        "final_score": round(prob_score, 3),
    }
