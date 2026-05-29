import json
import math

from app.extract.normalize import normalize_for_matching

POSITIVE_SIGNALS = {
    "TANG TRAN": 2.2,
    "BUT PHA": 1.8,
    "KY LUC": 1.6,
    "DOT BIEN": 1.5,
    "TANG SOC": 1.9,
    "PHUC HOI MANH": 1.5,
    "KHOI SAC": 1.1,
    "LAP DINH": 1.8,
    "BUNG NO": 1.7,
    "HUONG LOI": 1.0,
}

NEGATIVE_SIGNALS = {
    "LAO DOC": -2.3,
    "BAN THAO": -1.9,
    "THUA LO": -1.6,
    "RUI RO": -1.2,
    "CANH BAO": -1.0,
    "GIAM SAN": -2.1,
    "THAO CHAY": -1.8,
    "MAT THANH KHOAN": -1.5,
    "GAP KHO": -1.0,
    "PHA SAN": -2.0,
}


def _collect_signal_hits(text: str) -> tuple[float, list[dict[str, float | int | str]]]:
    raw_score = 0.0
    hits: list[dict[str, float | int | str]] = []

    for signal_map in (POSITIVE_SIGNALS, NEGATIVE_SIGNALS):
        for term, weight in signal_map.items():
            count = text.count(term)
            if not count:
                continue
            raw_score += weight * count
            hits.append({"term": term, "weight": weight, "count": count})

    return raw_score, hits


def score_fomo(
    title: str, content_text: str, tickers: list[str] | None = None
) -> tuple[float, str]:
    normalized_title = normalize_for_matching(title)
    normalized_body = normalize_for_matching(content_text)

    raw_score, hits = _collect_signal_hits(normalized_body)
    title_bonus, title_hits = _collect_signal_hits(normalized_title)
    weighted_title_bonus = title_bonus * 0.75
    raw_score += weighted_title_bonus

    signal_index = {hit["term"]: hit for hit in hits}
    for hit in title_hits:
        term = str(hit["term"])
        if term in signal_index:
            signal_index[term]["count"] = int(signal_index[term]["count"]) + int(hit["count"])
        else:
            hits.append(hit)
            signal_index[term] = hit

    ticker_count = len(tickers or [])
    ticker_boost = 1.0 + min(0.3, ticker_count * 0.08)
    k = 1.8
    final = math.tanh(raw_score * ticker_boost * k / 4)
    final = max(-1.0, min(1.0, final))
    final = round(final, 4)

    explain = {
        "raw_score": round(raw_score, 4),
        "k": k,
        "final": final,
        "signals": sorted(hits, key=lambda item: abs(float(item["weight"])), reverse=True),
        "ticker_boost": round(ticker_boost, 4),
        "title_bonus": round(weighted_title_bonus, 4),
    }
    return final, json.dumps(explain, ensure_ascii=False, sort_keys=True)
