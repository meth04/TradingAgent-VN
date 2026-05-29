import re

from tracking_news.app.extract.normalize import normalize_for_matching

VN30_TICKERS: tuple[str, ...] = (
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
)

_TICKER_PATTERN = re.compile(
    rf"(?<![A-Z0-9])({'|'.join(sorted(VN30_TICKERS, key=len, reverse=True))})(?![A-Z0-9])"
)


def extract_vn30_tickers(text: str) -> list[str]:
    normalized = normalize_for_matching(text)
    seen: set[str] = set()
    matches: list[str] = []

    for match in _TICKER_PATTERN.finditer(normalized):
        ticker = match.group(1)
        if ticker not in seen:
            seen.add(ticker)
            matches.append(ticker)

    return matches
