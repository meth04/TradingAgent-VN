import os
import asyncio
import atexit
import random
from typing import Any

import aiohttp
from dotenv import load_dotenv
from config import models

load_dotenv()

API_KEY = os.getenv("CLIPROXY_API_KEY")
BASE_URL = os.getenv("CLIPROXY_BASE_URL", "http://127.0.0.1:8317/v1")
DEFAULT_MODEL = os.getenv("GPT_MODEL", os.getenv("PRIMARY_MODEL", "coder-model"))

if BASE_URL and BASE_URL.endswith("/"):
    BASE_URL = BASE_URL.rstrip("/")

# ---------------------------------------------------------------------------
# Concurrency guard — only limits in-flight requests; NO RPM cap.
# ProxyPal (with 50 accounts) handles rate distribution internally.
# ---------------------------------------------------------------------------

_sem = asyncio.Semaphore(models.llm_concurrency)

_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(
            limit=models.llm_concurrency + 10,
            keepalive_timeout=720,
        )
        timeout = aiohttp.ClientTimeout(total=540, connect=30, sock_read=480)
        _session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


def _cleanup_session_sync() -> None:
    global _session
    if _session and not _session.closed:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(close_session())
        finally:
            loop.close()


atexit.register(_cleanup_session_sync)


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------

_MAX_RETRIES_SAME_MODEL = 2
_INITIAL_BACKOFF_SECONDS = 1.5
_MAX_BACKOFF_SECONDS = 15.0


def _exp_backoff(attempt: int, initial: float = _INITIAL_BACKOFF_SECONDS) -> float:
    """Exponential backoff with jitter: ``initial * 2^attempt + rand``."""
    delay = min(initial * (2 ** attempt), _MAX_BACKOFF_SECONDS)
    return delay + random.uniform(0, 0.5)



class LLMError(Exception):
    """Raised when all LLM attempts fail; callers must handle explicitly."""


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    fallback_models: list[str] | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    """
    * Raises LLMError instead of returning error strings.
    """
    del fallback_models
    url = f"{BASE_URL}/chat/completions"
    models_to_try = [model or DEFAULT_MODEL]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    last_error = "❌ Lỗi kết nối LLM: Unknown error"

    for idx, chosen_model in enumerate(models_to_try):
        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        # Retry loop for the SAME model (handles 429s / 5xx)
        for attempt in range(_MAX_RETRIES_SAME_MODEL):
            try:
                session = await _get_session()
                async with _sem:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status == 429:
                            retry_after = response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait = float(retry_after)
                                except ValueError:
                                    wait = _exp_backoff(attempt)
                            else:
                                wait = _exp_backoff(attempt)
                            print(
                                f"[call_llm] 429 on {chosen_model} "
                                f"(attempt {attempt + 1}/{_MAX_RETRIES_SAME_MODEL}). "
                                f"Waiting {wait:.1f}s …",
                                flush=True,
                            )
                            last_error = f"❌ Rate limited (429) on {chosen_model}"
                            await asyncio.sleep(wait)
                            continue  # retry same model

                        if response.status != 200:
                            text = await response.text()
                            last_error = f"❌ Lỗi API ({response.status}): {text}"
                            if response.status >= 500:
                                await asyncio.sleep(_exp_backoff(attempt, 1.0))
                                continue
                            break  # 4xx (not 429) — skip to next model

                        try:
                            data = await response.json()
                        except Exception as exc:
                            last_error = f"❌ Phản hồi API không đúng định dạng: {exc}"
                            break

                        if data and "choices" in data and len(data["choices"]) > 0:
                            content = data["choices"][0]["message"]["content"]
                            if isinstance(content, str):
                                content = content.strip()
                            else:
                                content = str(content)

                            if content.startswith("❌"):
                                last_error = content
                                if attempt < _MAX_RETRIES_SAME_MODEL - 1:
                                    await asyncio.sleep(_exp_backoff(attempt, 1.0))
                                    continue
                                break
                            return content
                        else:
                            last_error = f"❌ Phản hồi API không đúng định dạng: {data}"
                            break

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = f"❌ Lỗi kết nối LLM: {exc}"
                if attempt < _MAX_RETRIES_SAME_MODEL - 1:
                    await asyncio.sleep(_exp_backoff(attempt, 1.0))
                    continue
            except Exception as exc:
                last_error = f"❌ Lỗi kết nối LLM: {exc}"
                break

    raise LLMError(last_error)
