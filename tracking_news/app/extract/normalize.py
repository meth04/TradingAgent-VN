import html
import re
import unicodedata

_INLINE_WHITESPACE_RE = re.compile(r"[\t\r\f\v ]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ").replace("\u200b", " ").replace("\ufeff", " ")

    lines: list[str] = []
    for line in text.splitlines():
        cleaned = _INLINE_WHITESPACE_RE.sub(" ", line).strip()
        if cleaned:
            lines.append(cleaned)

    return _BLANK_LINE_RE.sub("\n\n", "\n".join(lines)).strip()


def strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_for_matching(text: str) -> str:
    return strip_accents(normalize_text(text)).upper()
