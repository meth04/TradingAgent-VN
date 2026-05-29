from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(str, Enum):
    BUY = "BUY"
    BUY_MORE = "BUY_MORE"
    SELL = "SELL"
    TRIMMING = "TRIMMING"
    PASS = "PASS"


LEGACY_ACTION_ALIASES = {
    "HOLD": Action.PASS,
    "IGNORE": Action.PASS,
    "ADD": Action.BUY_MORE,
}


def normalize_action(value: str | Action | None) -> Optional[Action]:
    """Return normalized Action or None when invalid."""
    if value is None:
        return None
    if isinstance(value, Action):
        return value
    try:
        normalized = value.strip().upper()
    except Exception:  # e.g., non-string with no strip
        return None
    if normalized in Action.__members__:
        return Action[normalized]
    if normalized in LEGACY_ACTION_ALIASES:
        return LEGACY_ACTION_ALIASES[normalized]
    return None


JSON_COT_PREFIX = (
    "\"_thought_process\": [\n"
    "  \"Step 1: ...\",\n"
    "  \"Step 2: ...\",\n"
    "  \"Step 3: ...\"\n"
    "],\n"
)

TEXT_COT_PREFIX = (
    "Hãy bắt đầu trả lời với thẻ <thinking>...</thinking> chứa lập luận từng bước trước khi đưa ra kết luận."
)

BACKTEST_CONTEXT = (
    "ĐÂY LÀ MÔI TRƯỜNG BACKTEST MÔ PHỎNG. Toàn bộ dữ liệu được cung cấp (tin tức, giá cổ phiếu, "
    "báo cáo tài chính, chỉ số kỹ thuật) là DỮ LIỆU THẬT đã xảy ra trong quá khứ, được hệ thống "
    "thu thập từ các nguồn chính thống (CafeF, HOSE, HNX, vnstock API). "
    "TUYỆT ĐỐI KHÔNG được nghi ngờ tính xác thực, KHÔNG được nói dữ liệu là 'giả định', "
    "'tương lai', 'chưa xảy ra', hoặc 'không thể kiểm chứng'. "
    "Hãy coi ref_date là ngày hiện tại và phân tích DỮ LIỆU ĐÃ CUNG CẤP một cách nghiêm túc, "
    "chuyên nghiệp như một chuyên gia tài chính thực thụ. "
    "Tập trung 100% vào phân tích nội dung dữ liệu, KHÔNG bình luận về nguồn gốc hay tính xác thực."
)

TEXT_COT_SUFFIX_WARNING = (
    "Nếu thiếu thẻ <thinking>, phải cảnh báo rằng người dùng không tuân thủ hướng dẫn."
)


def inject_json_cot(schema_body: str) -> str:
    """Prefix JSON schema body with _thought_process requirement."""

    def has_top_level_thought_process(body: str) -> bool:
        depth = 0
        i = 0
        n = len(body)
        while i < n:
            ch = body[i]
            if ch == "\"":
                i += 1
                start = i
                escaped = False
                while i < n:
                    c = body[i]
                    if c == "\\" and not escaped:
                        escaped = True
                        i += 1
                        continue
                    if c == "\"" and not escaped:
                        break
                    escaped = False
                    i += 1
                value = body[start:i]
                if depth == 1 and value in {"_thought_process", "analysis_steps"}:
                    j = i + 1
                    while j < n and body[j].isspace():
                        j += 1
                    if j < n and body[j] == ":":
                        return True
                i += 1
                continue

            if ch == "{":
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
            i += 1
        return False

    if has_top_level_thought_process(schema_body):
        return schema_body

    # Avoid over-stripping; handle leading whitespace and brace with trailing whitespace/newlines
    stripped_body = schema_body.lstrip()

    if stripped_body.startswith("{"):
        stripped_body = stripped_body[1:]
        if stripped_body.startswith("\n"):
            stripped_body = stripped_body[1:]
        else:
            nl_index = stripped_body.find("\n")
            if nl_index != -1 and stripped_body[:nl_index].strip() == "":
                stripped_body = stripped_body[nl_index + 1 :]

    return "{\n" + JSON_COT_PREFIX + stripped_body


@dataclass(frozen=True)
class CoTSnippets:
    json_prefix: str = JSON_COT_PREFIX
    text_prefix: str = TEXT_COT_PREFIX


__all__ = [
    "Action",
    "LEGACY_ACTION_ALIASES",
    "normalize_action",
    "JSON_COT_PREFIX",
    "TEXT_COT_PREFIX",
    "BACKTEST_CONTEXT",
    "inject_json_cot",
    "CoTSnippets",
]
