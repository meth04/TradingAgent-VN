import hashlib
import re
from collections import Counter

from app.extract.normalize import normalize_for_matching

_TOKEN_RE = re.compile(r"[A-Z0-9]{2,}")
_UINT64_MASK = (1 << 64) - 1
_INT64_SIGN_BIT = 1 << 63


def _to_uint64(value: int) -> int:
    return value & _UINT64_MASK


def _to_int64(value: int) -> int:
    value = _to_uint64(value)
    if value >= _INT64_SIGN_BIT:
        return value - (1 << 64)
    return value


def compute_content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_counts(text: str) -> Counter[str]:
    normalized = normalize_for_matching(text)
    return Counter(_TOKEN_RE.findall(normalized))


def compute_simhash64(text: str) -> int:
    weights = [0] * 64
    for token, count in _token_counts(text).items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big", signed=False)
        for bit in range(64):
            if value & (1 << bit):
                weights[bit] += count
            else:
                weights[bit] -= count

    simhash = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            simhash |= 1 << bit
    return _to_int64(simhash)


def compute_simhash_bucket(simhash64: int, *, prefix_bits: int = 16) -> int:
    return _to_uint64(simhash64) >> (64 - prefix_bits)


def hamming_distance(left: int, right: int) -> int:
    return (_to_uint64(left) ^ _to_uint64(right)).bit_count()
