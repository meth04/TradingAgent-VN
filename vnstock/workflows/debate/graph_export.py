from __future__ import annotations

import json
import os
from typing import Dict, List, Set

from vnstock.workflows.debate.argumentation import ArgumentationFramework


def export_debate_graph(
    framework: ArgumentationFramework,
    extension: Set[str],
    ticker: str,
    ref_date: str,
) -> Dict:
    args: List[Dict] = []
    for eid, ev in framework.evidences.items():
        status = "accepted" if eid in extension else "defeated"
        args.append(
            {
                "id": eid,
                "agent": ev.source_agent,
                "claim": ev.claim,
                "direction": ev.direction,
                "weight": ev.weight,
                "status": status,
            }
        )

    attacks: List[Dict] = []
    for atk in framework.attacks:
        attacks.append(
            {
                "from": atk.attacker_id,
                "to": atk.target_id,
                "strength": atk.strength,
                "reason": atk.reason,
            }
        )

    net_score = framework.get_net_score(extension)
    verdict = framework.classify_verdict(net_score)

    return {
        "framework": "Dung_1995_AAF",
        "ticker": ticker,
        "ref_date": ref_date,
        "arguments": args,
        "attacks": attacks,
        "grounded_extension": list(extension),
        "net_score": net_score,
        "verdict": verdict,
    }


def save_debate_graph(graph: Dict, output_dir: str, ticker: str, workflow: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{ticker}_{workflow}_debate.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    return path
