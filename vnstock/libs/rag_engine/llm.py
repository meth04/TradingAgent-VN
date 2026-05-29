import asyncio
import sys

from openai import AsyncOpenAI

from .config import settings


class RateLimiter:
    def __init__(self, max_calls: int, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self.semaphore = asyncio.Semaphore(max_calls)
        self.timestamps: list[float] = []

    async def acquire(self) -> None:
        async with self.semaphore:
            now = asyncio.get_event_loop().time()
            self.timestamps = [t for t in self.timestamps if now - t < self.period]
            if len(self.timestamps) >= self.max_calls:
                sleep_time = self.period - (now - self.timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            self.timestamps.append(asyncio.get_event_loop().time())


limiter = RateLimiter(settings.MAX_RPM)
_client = AsyncOpenAI(
    api_key=settings.API_KEY,
    base_url=settings.BASE_URL,
    timeout=settings.LLM_TIMEOUT_SECONDS,
)


async def openai_complete_if_cache(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, str]] | None = None,
    **kwargs,
) -> str:
    model_name = kwargs.get("model") or kwargs.get("model_name") or settings.LLM_MODEL

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history_messages:
        messages.extend(history_messages)
    messages.append({"role": "user", "content": prompt})

    await limiter.acquire()
    try:
        response = await _client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=kwargs.get("temperature", 0.1),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
    except asyncio.TimeoutError:
        print(
            f"[LLM TIMEOUT] model={model_name} exceeded {settings.LLM_TIMEOUT_SECONDS:.0f}s",
            file=sys.stderr,
        )
        return ""
    except Exception as exc:
        print(f"[LLM ERROR] model={model_name}: {exc}", file=sys.stderr)
        return ""

    content = response.choices[0].message.content
    return content.strip() if isinstance(content, str) else ""
