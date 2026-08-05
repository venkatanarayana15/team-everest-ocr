import asyncio
import base64
import functools
import json
import logging
import os
import threading
import time
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional



logger = logging.getLogger(__name__)


def _load_dotenv(path: str = None) -> None:
    if path is None:
        from pathlib import Path
        path = str(Path(__file__).resolve().parent.parent / ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in os.environ:
                    os.environ[k] = v.strip()


_load_dotenv()

# Global semaphore that caps total concurrent LLM calls across ALL pipelines.
# This prevents LLM API overload regardless of how many pipelines are active.
_global_llm_semaphore = asyncio.Semaphore(
    int(os.environ.get("GLOBAL_LLM_MAX_CONCURRENCY", "3"))
)


# ── Structured Metrics (Phase 6) ──────────────────────────────────

@dataclass
class RateLimitMetrics:
    """Track rate limiting metrics for structured logging."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_hits: int = 0
    retries: int = 0
    total_sleep_time: float = 0.0
    tokens_refunded: int = 0
    circuit_breaker_opens: int = 0
    
    def record_request(self, success: bool, rate_limited: bool = False, 
                       sleep_time: float = 0.0, token_refunded: bool = False) -> None:
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        if rate_limited:
            self.rate_limit_hits += 1
        if sleep_time > 0:
            self.retries += 1
            self.total_sleep_time += sleep_time
        if token_refunded:
            self.tokens_refunded += 1
    
    def get_stats(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "success_rate": round(self.successful_requests / max(1, self.total_requests), 3),
            "rate_limit_rate": round(self.rate_limit_hits / max(1, self.total_requests), 3),
            "retry_rate": round(self.retries / max(1, self.total_requests), 3),
            "avg_sleep_time": round(self.total_sleep_time / max(1, self.retries), 2),
            "tokens_refunded": self.tokens_refunded,
            "circuit_breaker_opens": self.circuit_breaker_opens,
        }
    
    def log_summary(self, prefix: str = "") -> None:
        stats = self.get_stats()
        if self.total_requests > 0:
            logger.info(
                "%s[RateLimit Metrics] total=%d success=%.1f%% rate_limited=%.1f%% "
                "retries=%d avg_sleep=%.1fs refunded=%d circuit_opens=%d",
                prefix + " " if prefix else "",
                stats["total_requests"],
                stats["success_rate"] * 100,
                stats["rate_limit_rate"] * 100,
                stats["retries"],
                stats["avg_sleep_time"],
                stats["tokens_refunded"],
                stats["circuit_breaker_opens"],
            )


# Global metrics instance
_rate_limit_metrics = RateLimitMetrics()


def get_rate_limit_metrics() -> RateLimitMetrics:
    """Get the global rate limit metrics instance."""
    return _rate_limit_metrics


def log_rate_limit_metrics(prefix: str = "") -> None:
    """Log current rate limit metrics."""
    _rate_limit_metrics.log_summary(prefix)


# ── Circuit Breaker (Phase 3) ──────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker pattern to prevent infinite retries during sustained failures.
    
    States:
    - closed: Normal operation, requests pass through
    - open: Too many failures, requests are rejected immediately
    - half-open: Testing if service recovered, limited requests pass
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
        self._lock = threading.Lock()
    
    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                if self.state != "open":
                    logger.warning(
                        "Circuit breaker OPEN: %d consecutive failures, "
                        "rejecting requests for %.0fs",
                        self.failure_count, self.recovery_timeout,
                    )
                    _rate_limit_metrics.circuit_breaker_opens += 1
                self.state = "open"
    
    def record_success(self) -> None:
        with self._lock:
            if self.state == "half-open":
                logger.info("Circuit breaker CLOSED: service recovered")
            self.failure_count = 0
            self.state = "closed"
    
    def can_execute(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            elif self.state == "open":
                if self.last_failure_time and \
                   (time.monotonic() - self.last_failure_time) > self.recovery_timeout:
                    logger.info("Circuit breaker HALF-OPEN: testing service recovery")
                    self.state = "half-open"
                    return True
                return False
            else:  # half-open
                return True


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker(
    failure_threshold=int(os.environ.get("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.environ.get("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "60")),
)


# ── Rate Limiter (Phase 1: Token Refund) ──────────────────────────

class RateLimiter:
    """Token-bucket rate limiter with refund capability, shared per provider+model.

    Enforces two budgets for the Gemini quota:
      * ``rpm`` — requests per minute (token-bucket, refills at ``rpm/60``).
      * ``tpm`` — tokens per minute (sliding 60s window fed by the actual
        token usage reported by the API, so TPM is never exceeded).

    A token is consumed only when the caller actually proceeds with the
    request — so long in-flight calls no longer inflate the rate window.

    Concurrency is capped by an internal semaphore sized to ``max_concurrency``.

    Phase 1: refund_token() returns tokens on failed requests.
    Phase 6: block() pauses ALL callers for a global cooldown after a 429
             quota-exhausted error, preventing a thundering herd of retries.
    """

    WINDOW_SEC = 60.0

    def __init__(self, rpm: int, max_concurrency: int, tpm: int = 0):
        self.rpm = max(int(rpm or 0), 1)
        self.max_concurrency = max(int(max_concurrency or 1), 1)
        self.tpm = max(int(tpm or 0), 0)
        self._tokens = float(self.rpm)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._blocked_until = 0.0
        self._token_timestamps: list[tuple[float, float]] = []
        self._window_tokens = 0.0

    def _consume_token(self) -> float:
        """Consume one token; return seconds to sleep before the request."""
        with self._lock:
            now = time.monotonic()
            self._tokens = min(float(self.rpm), self._tokens + (now - self._last_refill) * self.rpm / 60.0)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            return (1.0 - self._tokens) * 60.0 / self.rpm

    def refund_token(self) -> None:
        """Refund a token after a failed request (Phase 1 improvement)."""
        with self._lock:
            self._tokens = min(float(self.rpm), self._tokens + 1.0)
            _rate_limit_metrics.tokens_refunded += 1
            logger.debug("Rate limit: token refunded (%.1f tokens available)", self._tokens)

    def _prune_window(self, now: float) -> None:
        cutoff = now - self.WINDOW_SEC
        while self._token_timestamps and self._token_timestamps[0][0] < cutoff:
            _, n = self._token_timestamps.pop(0)
            self._window_tokens -= n
        if not self._token_timestamps:
            self._window_tokens = 0.0

    def _token_budget_wait(self) -> float:
        """Seconds until the 60s token window has room again (0 if under budget)."""
        if self.tpm <= 0:
            return 0.0
        now = time.monotonic()
        self._prune_window(now)
        if self._window_tokens >= self.tpm and self._token_timestamps:
            oldest = self._token_timestamps[0][0]
            return max(0.0, oldest + self.WINDOW_SEC - now)
        return 0.0

    def record_tokens(self, usage: dict) -> None:
        """Record actual token consumption from a successful API response."""
        total = int(usage.get("total_tokens") or 0)
        if total <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._prune_window(now)
            self._token_timestamps.append((now, float(total)))
            self._window_tokens += float(total)

    def block(self, seconds: float) -> None:
        """Pause ALL callers on this limiter for ``seconds`` (429 quota backoff)."""
        if seconds <= 0:
            return
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)

    def _cooldown(self) -> float:
        """Combined seconds to wait for global block + token budget (>= 0)."""
        with self._lock:
            now = time.monotonic()
            return max(self._blocked_until - now, self._token_budget_wait(), 0.0)

    def wait(self) -> None:
        delay = self._cooldown()
        while delay > 0:
            time.sleep(min(delay, 5.0))
            delay = self._cooldown()
        delay = self._consume_token()
        if delay > 0:
            logger.debug("Rate limit: sleeping %.1fs", delay)
            time.sleep(delay)

    async def wait_async(self, on_wait=None) -> None:
        async with self._semaphore:
            delay = self._cooldown()
            while delay > 0:
                if on_wait:
                    on_wait("quota_backoff", f"Quota window busy — pausing {delay:.0f}s")
                await asyncio.sleep(min(delay, 5.0))
                delay = self._cooldown()
            delay = self._consume_token()
            if delay > 0:
                if on_wait:
                    on_wait("waiting_for_rate_limit", f"Rate limit: waiting {delay:.1f}s...")
                logger.debug("Rate limit: sleeping %.1fs", delay)
                await asyncio.sleep(delay)


# ── Adaptive Concurrency (Phase 5) ────────────────────────────────

class AdaptiveConcurrencyLimiter:
    """Adaptive concurrency limiter that adjusts based on latency (Phase 5).
    
    This is an optional enhancement that can be enabled via
    ADAPTIVE_CONCURRENCY_ENABLED=true.
    """
    
    def __init__(self, initial_concurrency: int = 6, 
                 min_concurrency: int = 2, 
                 max_concurrency: int = 12,
                 target_latency: float = 1.0):
        self.current_concurrency = initial_concurrency
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.target_latency = target_latency
        self.latency_history: list[float] = []
        self._lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(initial_concurrency)
    
    def record_latency(self, latency: float) -> None:
        """Record request latency and adjust concurrency if needed."""
        with self._lock:
            self.latency_history.append(latency)
            # Keep only last 100 measurements
            if len(self.latency_history) > 100:
                self.latency_history.pop(0)
            
            # Adjust concurrency based on average latency
            if len(self.latency_history) >= 10:
                avg_latency = sum(self.latency_history) / len(self.latency_history)
                
                if avg_latency > self.target_latency * 1.5:
                    # High latency, reduce concurrency
                    new_concurrency = max(self.min_concurrency, self.current_concurrency - 1)
                    if new_concurrency != self.current_concurrency:
                        logger.info(
                            "Adaptive concurrency: reducing %d → %d (avg latency %.2fs > target %.2fs)",
                            self.current_concurrency, new_concurrency, avg_latency, self.target_latency
                        )
                        self.current_concurrency = new_concurrency
                        self._semaphore = asyncio.Semaphore(new_concurrency)
                elif avg_latency < self.target_latency * 0.5:
                    # Low latency, increase concurrency
                    new_concurrency = min(self.max_concurrency, self.current_concurrency + 1)
                    if new_concurrency != self.current_concurrency:
                        logger.info(
                            "Adaptive concurrency: increasing %d → %d (avg latency %.2fs < target %.2fs)",
                            self.current_concurrency, new_concurrency, avg_latency, self.target_latency
                        )
                        self.current_concurrency = new_concurrency
                        self._semaphore = asyncio.Semaphore(new_concurrency)
    
    async def acquire(self) -> None:
        """Acquire a concurrency slot."""
        await self._semaphore.acquire()
    
    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()
    
    def get_stats(self) -> dict:
        """Get current adaptive concurrency stats."""
        with self._lock:
            avg_latency = sum(self.latency_history) / len(self.latency_history) if self.latency_history else 0
            return {
                "current_concurrency": self.current_concurrency,
                "min_concurrency": self.min_concurrency,
                "max_concurrency": self.max_concurrency,
                "target_latency": self.target_latency,
                "avg_latency": round(avg_latency, 2),
                "latency_samples": len(self.latency_history),
            }


# Global adaptive concurrency limiter (optional, enabled via env var)
_adaptive_limiter: Optional[AdaptiveConcurrencyLimiter] = None

if os.environ.get("ADAPTIVE_CONCURRENCY_ENABLED", "false").lower() in ("1", "true", "yes"):
    _adaptive_limiter = AdaptiveConcurrencyLimiter(
        initial_concurrency=int(os.environ.get("ADAPTIVE_CONCURRENCY_INITIAL", "6")),
        min_concurrency=int(os.environ.get("ADAPTIVE_CONCURRENCY_MIN", "2")),
        max_concurrency=int(os.environ.get("ADAPTIVE_CONCURRENCY_MAX", "12")),
        target_latency=float(os.environ.get("ADAPTIVE_CONCURRENCY_TARGET_LATENCY", "1.0")),
    )
    logger.info("Adaptive concurrency enabled: %s", _adaptive_limiter.get_stats())


def get_adaptive_limiter() -> Optional[AdaptiveConcurrencyLimiter]:
    """Get the global adaptive concurrency limiter (if enabled)."""
    return _adaptive_limiter


# One limiter per provider+model so separate client instances (single vs
# batch pipelines) share the same budget instead of each getting their own.
_RATE_LIMITERS: dict[str, RateLimiter] = {}
_RATE_LIMITERS_LOCK = threading.Lock()


def _get_rate_limiter(key: str, rpm: int, max_concurrency: int, tpm: int = 0) -> RateLimiter:
    with _RATE_LIMITERS_LOCK:
        lim = _RATE_LIMITERS.get(key)
        if lim is None:
            lim = RateLimiter(rpm, max_concurrency, tpm)
            _RATE_LIMITERS[key] = lim
        return lim


# Provider HTTP clients opened by get_model_client(); closed at shutdown so
# pending aiohttp/grpc sessions don't leak (fixes the "coroutine
# connect_tcp.try_connect was never awaited" warning on exit).
_OPEN_CLIENTS: list = []
_CLIENTS_LOCK = threading.Lock()


def _register_client(client) -> None:
    with _CLIENTS_LOCK:
        _OPEN_CLIENTS.append(client)


async def close_all_clients() -> None:
    """Close every registered provider client. Call once at server shutdown."""
    with _CLIENTS_LOCK:
        clients = list(_OPEN_CLIENTS)
        _OPEN_CLIENTS.clear()
    for c in clients:
        try:
            await c.aclose()
        except Exception:
            logger.debug("Error closing %s client", type(c).__name__, exc_info=True)


def _is_transient(e: Exception) -> bool:
    """Check if an exception is transient (retryable)."""
    msg = str(e).lower()
    error_type = type(e).__name__
    
    # Log the exception details for debugging
    logger.debug("Checking exception: [%s] %s", error_type, str(e)[:200] if str(e) else "(empty)")
    
    # Check for HTTP status codes
    if hasattr(e, "status_code"):
        code = e.status_code
        if code == 429 or (500 <= code < 600):
            logger.debug("Transient: HTTP status %d", code)
            return True
    
    # Check for gRPC-style error codes (Gemini API uses 'code' attribute)
    if hasattr(e, "code"):
        code = e.code
        # Handle both integer and string codes
        try:
            code_int = int(code) if code else 0
            if code_int == 429 or (500 <= code_int < 600):
                logger.debug("Transient: API code %d", code_int)
                return True
        except (ValueError, TypeError):
            # If code is not a number, check string representation
            code_str = str(code).lower()
            if "429" in code_str or "too_many_requests" in code_str or "resource_exhausted" in code_str:
                logger.debug("Transient: API code string %s", code_str)
                return True
    
    # Check for rate limit patterns in message
    if "429" in msg or "too many requests" in msg:
        logger.debug("Transient: rate limit pattern in message")
        return True
    if "rate_limit" in msg or "rate limit" in msg:
        logger.debug("Transient: rate limit pattern in message")
        return True
    
    # Check for timeout/connection errors (built-in Python exceptions)
    if isinstance(e, (TimeoutError, ConnectionError)):
        logger.debug("Transient: timeout/connection error (built-in)")
        return True
    if "timeout" in msg or "connection refused" in msg or "connection reset" in msg:
        logger.debug("Transient: timeout/connection pattern in message")
        return True
    
    # Check for httpx/aiohttp network errors (common with Gemini API)
    # httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, etc.
    httpx_errors = ("ReadError", "ConnectError", "TimeoutException", 
                    "WriteError", "CloseError", "PoolTimeout",
                    "RemoteProtocolError", "LocalProtocolError",
                    "ProxyError", "UnsupportedProtocol",
                    "ProtocolError", "StreamError")
    if error_type in httpx_errors:
        logger.debug("Transient: httpx network error [%s]", error_type)
        return True
    
    # Check for aiohttp errors
    aiohttp_errors = ("ClientError", "ServerError", "ClientConnectorError",
                      "ServerDisconnectedError", "ClientResponseError",
                      "ClientPayloadError", "HttpProcessingError")
    if error_type in aiohttp_errors:
        logger.debug("Transient: aiohttp network error [%s]", error_type)
        return True
    
    # Check for empty message with known network error types
    # (ReadError(''), ConnectError('') with empty message)
    if not msg and error_type in (*httpx_errors, *aiohttp_errors):
        logger.debug("Transient: empty message from known network error type [%s]", error_type)
        return True
    
    # Check for Gemini-specific errors
    if "resource_exhausted" in msg or "quota" in msg:
        logger.debug("Transient: resource exhausted pattern")
        return True
    
    # Check for empty exceptions (might be Gemini library issues)
    if not msg and error_type in ("ClientError", "ServerError", "GoogleAPIError"):
        logger.debug("Transient: empty message from %s", error_type)
        return True
    
    logger.debug("Non-transient exception")
    return False


def _is_quota_exhausted(e: Exception) -> bool:
    """True when the API rejected the call because a quota/TPM window is exhausted.

    429 RESOURCE_EXHAUSTED with "you exceeded your current quota" means the
    per-minute token budget is spent — retrying in 2-8s is futile and only
    makes things worse, so callers should pause ALL requests for a longer,
    coordinated window instead.
    """
    msg = str(e).lower()
    return (
        "resource_exhausted" in msg
        or "quota" in msg
        or "exceeded your current quota" in msg
        or "quota exceeded" in msg
        or "insufficient_quota" in msg
    )


def _retry_wait(attempt: int, e: Exception, rl: RateLimiter | None) -> float:
    """Compute the sleep before the next retry, with 429 quota-aware backoff."""
    retry_after = getattr(e, 'retry_after', None) or getattr(e, 'headers', {}).get('retry-after')
    if _is_quota_exhausted(e):
        try:
            wait = float(retry_after) if retry_after else float(os.environ.get("GEMINI_429_BACKOFF_SEC", "30"))
        except (ValueError, TypeError):
            wait = float(os.environ.get("GEMINI_429_BACKOFF_SEC", "30"))
        wait = max(wait, float(os.environ.get("GEMINI_429_BACKOFF_SEC", "30")))
        if rl:
            rl.block(wait)
        logger.warning("Gemini quota exhausted (429) — pausing all requests for %.1fs", wait)
        return wait
    if retry_after:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass
    return (2 ** attempt) + random.uniform(0, 5)


def call_with_retry(fn, max_retries: int | None = None, rl: RateLimiter | None = None):
    """Synchronous call with retry logic (Phase 2: Retry-After + Phase 3: Circuit Breaker)."""
    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))
    
    # Phase 3: Check circuit breaker
    if not _circuit_breaker.can_execute():
        raise RuntimeError("Circuit breaker OPEN: too many consecutive failures, try again later")
    
    if rl:
        rl.wait()
    
    for attempt in range(max_retries):
        try:
            result = fn()
            _circuit_breaker.record_success()
            return result
        except Exception as e:
            if not _is_transient(e):
                raise
            if attempt == max_retries - 1:
                raise

            wait = _retry_wait(attempt, e, rl)

            # Phase 1: Refund token on failed request
            if rl:
                rl.refund_token()

            # Don't count quota exhaustion as circuit-breaker failures —
            # it's a capacity signal, not a service degradation.
            if not _is_quota_exhausted(e):
                _circuit_breaker.record_failure()
            _rate_limit_metrics.record_request(
                success=False, 
                rate_limited=True, 
                sleep_time=wait,
                token_refunded=True
            )
            
            logger.info(
                "Transient error (%s) attempt %d/%d. Waiting %.1fs...",
                type(e).__name__,
                attempt + 1,
                max_retries,
                wait,
            )
            time.sleep(wait)
    return None


async def call_with_retry_async(fn, max_retries: int | None = None, rl: RateLimiter | None = None, on_wait=None):
    """Async call with retry logic (Phase 2: Retry-After + Phase 3: Circuit Breaker)."""
    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))
    
    # Phase 3: Check circuit breaker
    if not _circuit_breaker.can_execute():
        raise RuntimeError("Circuit breaker OPEN: too many consecutive failures, try again later")
    
    for attempt in range(max_retries):
        try:
            # Wait for the rate-limit token FIRST (outside the global semaphore).
            # Otherwise workers sleeping in wait_async would hold a global
            # concurrency slot while not making a request, starving everyone else.
            if rl:
                await rl.wait_async(on_wait=on_wait)
            if on_wait and _global_llm_semaphore.locked():
                on_wait("waiting_for_semaphore", "Waiting for global LLM semaphore slot...")
            async with _global_llm_semaphore:
                result = await fn()
            _circuit_breaker.record_success()
            _rate_limit_metrics.record_request(success=True)
            return result
        except Exception as e:
            # Log detailed exception info for debugging
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else repr(e)
            logger.debug(
                "Exception caught: [%s] %s (attempt %d/%d)",
                error_type, error_msg[:200], attempt + 1, max_retries
            )
            
            if not _is_transient(e):
                logger.warning("Non-transient error: [%s] %s", error_type, error_msg[:200])
                raise
            if attempt == max_retries - 1:
                logger.warning("Max retries reached, raising: [%s] %s", error_type, error_msg[:200])
                raise

            wait = _retry_wait(attempt, e, rl)

            # Phase 1: Refund token on failed request
            if rl:
                rl.refund_token()

            # Don't count quota exhaustion as circuit-breaker failures —
            # it's a capacity signal, not a service degradation.
            if not _is_quota_exhausted(e):
                _circuit_breaker.record_failure()
            _rate_limit_metrics.record_request(
                success=False, 
                rate_limited=True, 
                sleep_time=wait,
                token_refunded=True
            )
            
            logger.info(
                "Transient error (%s [%s]) attempt %d/%d. Waiting %.1fs...",
                error_type, error_msg[:100], attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)
    return None

TokenUsage = dict


# Global timeout for Gemini API calls (in seconds)
_GEMINI_API_TIMEOUT = int(os.environ.get("GEMINI_API_TIMEOUT", "180"))


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


@functools.lru_cache(maxsize=32)
def _encode_image(path: str, max_dim: int = 2048) -> str:
    import cv2
    img = cv2.imread(path)
    if img is not None:
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        success, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if success:
            return base64.b64encode(buf.tobytes()).decode("utf-8")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class ModelClient(ABC):
    @property
    def needs_images(self) -> bool:
        return True

    @abstractmethod
    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        ...

    async def aclose(self) -> None:
        """Release provider HTTP resources. Override in subclasses."""
        return


# ── Gemini (google.genai) ──────────────────────────────────────────

class GeminiClient(ModelClient):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", base_url: str | None = None):
        from google import genai as _genai
        http_options = {"timeout": 120000}
        if base_url:
            http_options["base_url"] = base_url
        self._client = _genai.Client(api_key=api_key, http_options=http_options)
        self._genai = _genai
        self.model_name = model
        self.provider = "gemini"
        _gemini_conc = int(os.environ.get("GEMINI_MAX_CONCURRENCY", "2"))
        _gemini_rpm = int(os.environ.get("GEMINI_RATE_LIMIT_RPM", "14"))
        _gemini_tpm = int(os.environ.get("GEMINI_RATE_LIMIT_TPM", "250000"))
        self._rl = _get_rate_limiter(f"gemini:{model}", _gemini_rpm, _gemini_conc, _gemini_tpm)

    async def aclose(self) -> None:
        try:
            await self._client.aio.close()
        except Exception:
            pass

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        metadata = getattr(response, "usage_metadata", None)
        if metadata is not None:
            prompt_tokens = getattr(metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(metadata, "response_token_count", 0) or 0
            total_tokens = getattr(metadata, "total_token_count", 0) or 0
            if completion_tokens == 0 and prompt_tokens > 0:
                text = getattr(response, "text", "") or ""
                completion_tokens = max(len(text.split()) * 4 // 3, 1)
                total_tokens = prompt_tokens + completion_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
        return usage

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        from PIL import Image

        if page_images:
            pages = sorted(page_images.keys())
            contents: list = [prompt]
            for p in pages:
                img = Image.open(page_images[p])
                contents.append(img)
            try:
                response = await asyncio.wait_for(
                    call_with_retry_async(
                        lambda: self._client.aio.models.generate_content(
                            model=self.model_name,
                            contents=contents,
                            config=self._genai.types.GenerateContentConfig(
                                response_mime_type="application/json",
                                max_output_tokens=int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
                            ),
                        ),
                        rl=self._rl,
                        on_wait=lambda stage, msg: logger.info("GeminiClient: %s - %s", stage, msg),
                    ),
                    timeout=_GEMINI_API_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error("Gemini API call timed out after %ds for pages %s", _GEMINI_API_TIMEOUT, pages)
                return None, {}
        elif pdf_path:
            logger.debug("Uploading PDF to Gemini...")
            try:
                sample_file = await call_with_retry_async(
                    lambda: self._client.aio.files.upload(
                        file=pdf_path,
                        config={"mime_type": "application/pdf"},
                    ),
                    rl=self._rl,
                    on_wait=lambda stage, msg: logger.info("GeminiClient: %s - %s", stage, msg),
                )
                logger.debug("Uploaded: %s", sample_file.name)
                response = await call_with_retry_async(
                    lambda: self._client.aio.models.generate_content(
                        model=self.model_name,
                        contents=[sample_file, prompt],
                        config=self._genai.types.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
                        ),
                    ),
                    rl=self._rl,
                    on_wait=lambda stage, msg: logger.info("GeminiClient: %s - %s", stage, msg),
                )
            except Exception as e:
                logger.warning("Gemini PDF generation failed (%s)", e)
                return None, {}
        else:
            logger.warning("Gemini extract_structured called with no PDF and no page images")
            return None, {}

        token_usage = self._extract_token_usage(response)
        self._rl.record_tokens(token_usage)
        text = _strip_json_fence(response.text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), token_usage)
            return data, token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, token_usage


# ── Factory ───────────────────────────────────────────────────────

def get_model_client(role: str = "primary") -> ModelClient:
    _load_dotenv()

    prefix = role.upper()
    model_key = f"{prefix}_MODEL"
    api_key_key = f"{prefix}_API_KEY"
    base_url_key = f"{prefix}_BASE_URL"

    model = os.environ.get(model_key, "gemini-2.5-flash")
    api_key = os.environ.get(api_key_key) or os.environ.get("GEMINI_API_KEY")
    base_url = os.environ.get(base_url_key)

    if not api_key:
        raise ValueError(f"{api_key_key} (or GEMINI_API_KEY) not set in .env")

    logger.info("[%s] Using Gemini: %s  base_url=%s", role, model, base_url)
    client = GeminiClient(api_key=api_key, model=model, base_url=base_url)
    _register_client(client)
    return client
