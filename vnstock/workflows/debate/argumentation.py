from __future__ import annotations

from typing import Dict, List, Set

from vnstock.workflows.debate.evidence import Attack, Evidence


class ArgumentationFramework:
    """
    Implementation of Dung (1995) Abstract Argumentation Framework.
    Computes the Grounded Extension (least fixpoint of characteristic function).
    """

    def __init__(self, evidences: List[Evidence], attacks: List[Attack]):
        self.evidences: Dict[str, Evidence] = {e.id: e for e in evidences}
        self.attacks: List[Attack] = attacks

    def _attackers_of(self, target_id: str) -> List[Attack]:
        return [atk for atk in self.attacks if atk.target_id == target_id]

    def _attackers_attacked_by(self, attacker_ids: Set[str]) -> Set[str]:
        defended: Set[str] = set()
        for atk in self.attacks:
            if atk.attacker_id in attacker_ids:
                defended.add(atk.target_id)
        return defended

    def compute_grounded_extension(self) -> Set[str]:
        accepted: Set[str] = set()
        remaining = set(self.evidences.keys())

        while True:
            # Unattacked args w.r.t remaining
            unattacked = {
                a_id
                for a_id in remaining
                if not any(atk.attacker_id in remaining for atk in self._attackers_of(a_id))
            }
            if not unattacked:
                break

            accepted |= unattacked
            # Remove attacked by newly accepted
            attacked_by_accepted = {
                atk.target_id for atk in self.attacks if atk.attacker_id in unattacked
            }
            remaining -= unattacked
            remaining -= attacked_by_accepted

        return accepted

    def get_net_score(self, extension: Set[str]) -> float:
        score = 0.0
        for eid in extension:
            e = self.evidences[eid]
            w = e.weight
            if e.direction == "bearish":
                w = -w
            score += w
        return round(score, 2)

    def classify_verdict(self, net_score: float) -> str:
        if net_score > 5:
            return "strong_bullish"
        if net_score > 2:
            return "cautious_bullish"
        if net_score > -2:
            return "neutral"
        if net_score > -5:
            return "cautious_bearish"
        return "strong_bearish"


async def detect_attacks(evidences: List[Evidence]) -> List[Attack]:
    """Deterministically identify attacks between evidence using rule-based heuristics."""

    _ATTACK_CACHE = getattr(detect_attacks, "_cache", {})
    setattr(detect_attacks, "_cache", _ATTACK_CACHE)

    cache_key = tuple(sorted((e.id, e.source_agent, e.direction, e.claim) for e in evidences))
    if cache_key in _ATTACK_CACHE:
        return _ATTACK_CACHE[cache_key]

    attacks: List[Attack] = []
    for ev in evidences:
        if ev.direction != "bearish":
            continue
        if ev.source_agent == "macro":
            for tgt in evidences:
                if tgt.source_agent == "quant" and tgt.direction == "bullish":
                    attacks.append(Attack(ev.id, tgt.id, "Rủi ro vĩ mô phủ nhận luận điểm định lượng tích cực", round(min(ev.weight, tgt.weight) / 10, 2)))
        if ev.source_agent == "news":
            for tgt in evidences:
                if tgt.source_agent == "financial" and tgt.direction == "bullish":
                    attacks.append(Attack(ev.id, tgt.id, "Rủi ro sự kiện làm suy yếu luận điểm cơ bản tích cực", round(min(ev.weight, tgt.weight) / 10, 2)))
        if ev.source_agent == "technical":
            for tgt in evidences:
                if tgt.source_agent == "news" and tgt.direction == "bullish":
                    attacks.append(Attack(ev.id, tgt.id, "Giá và động lượng không xác nhận catalyst tin tức", round(min(ev.weight, tgt.weight) / 10, 2)))

    _ATTACK_CACHE[cache_key] = attacks
    return attacks
