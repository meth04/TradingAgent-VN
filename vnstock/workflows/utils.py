from __future__ import annotations

import json
from typing import Dict

from vnstock.workflows.base import AgentOutput


def format_facts(agent_outputs: Dict[str, AgentOutput]) -> str:
    parts: list[str] = []
    for name in ["macro", "news", "technical", "quant", "financial"]:
        agent_output = agent_outputs.get(name)
        if not agent_output:
            continue
        parts.append(f"### {name}\n{agent_output.raw_analysis.strip()}")
    return "\n\n".join(parts)


def safe_json_extract(text: str) -> tuple[dict | None, str]:
    raw = text.strip()
    try:
        return json.loads(raw), raw
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1]), raw
            except Exception:
                return None, raw
        return None, raw


__all__ = ["format_facts", "safe_json_extract"]
