import random
import time
from collections.abc import Callable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import CRAWL_RATE_LIMIT_SECONDS, CRAWL_TIMEOUT_SECONDS, CRAWL_USER_AGENT


def build_client(*, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": CRAWL_USER_AGENT},
        timeout=CRAWL_TIMEOUT_SECONDS,
        transport=transport,
    )


def _apply_rate_limit(rate_limit_seconds: float) -> None:
    delay = max(0.0, rate_limit_seconds + random.uniform(0.0, 0.25))
    if delay:
        time.sleep(delay)


def _fetch_html_once(client: httpx.Client, url: str, *, rate_limit_seconds: float) -> str:
    _apply_rate_limit(rate_limit_seconds)
    response = client.get(url)
    response.raise_for_status()
    return response.text


def _build_fetcher(rate_limit_seconds: float) -> Callable[[httpx.Client, str], str]:
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    )
    def _fetch(client: httpx.Client, url: str) -> str:
        return _fetch_html_once(client, url, rate_limit_seconds=rate_limit_seconds)

    return _fetch


def fetch_html(
    url: str, *, client: httpx.Client | None = None, rate_limit_seconds: float | None = None
) -> str:
    fetcher = _build_fetcher(
        CRAWL_RATE_LIMIT_SECONDS if rate_limit_seconds is None else rate_limit_seconds
    )
    if client is not None:
        return fetcher(client, url)

    with build_client() as owned_client:
        return fetcher(owned_client, url)
