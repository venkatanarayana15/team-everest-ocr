import logging
import os
import random
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter (per-provider).

    Tracks timestamps of recent calls. Blocks if RPM would be exceeded.
    """

    def __init__(self, rpm: int | None = None):
        self.rpm = rpm or int(os.environ.get("LLM_RATE_LIMIT_RPM", "30"))
        self._timestamps: list[float] = []

    def wait(self) -> None:
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.rpm:
            sleep_for = self._timestamps[0] + 60 - now
            if sleep_for > 0:
                logger.debug("Rate limit: sleeping %.1fs", sleep_for)
                time.sleep(sleep_for)
        self._timestamps.append(time.time())


def is_rate_limited(e: Exception) -> bool:
    """Detect 429 / rate-limit across OpenAI, Gemini, DeepSeek, OpenRouter."""
    msg = str(e).lower()
    if hasattr(e, "status_code") and e.status_code == 429:
        return True
    if hasattr(e, "code") and e.code == 429:  # gemini
        return True
    if "429" in msg or "too many requests" in msg:
        return True
    if "rate_limit" in msg or "rate limit" in msg:
        return True
    return False


def call_with_retry(fn, max_retries: int | None = None, rl: RateLimiter | None = None):
    """Call *fn*. On 429: wait (2^attempt + jitter) and retry.

    Re-raises on the last failed attempt or on non-429 errors.
    """
    if rl:
        rl.wait()

    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))

    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if not is_rate_limited(e):
                raise
            if attempt == max_retries - 1:
                raise
            wait = (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "429 rate limited (attempt %d/%d). Waiting %.1fs...",
                attempt + 1,
                max_retries,
                wait,
            )
            time.sleep(wait)
    return None  # unreachable
