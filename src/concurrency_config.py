"""Unified concurrency configuration for LLM rate limiting and throttling.

This module provides a single source of truth for all concurrency-related
configuration, making it easier to reason about limits and avoid deadlocks.

Concurrency Hierarchy:
1. Provider-level limits (hard limits from API): GEMINI_MAX_CONCURRENCY
2. Global LLM limits (soft limits for fairness): GLOBAL_LLM_MAX_CONCURRENCY
3. Pipeline-level limits (workload-specific): BATCH_MAX_CONCURRENCY, RENDER_MAX_CONCURRENCY
4. Adaptive limits (optional): ADAPTIVE_CONCURRENCY_*

Effective limits are calculated as min(provider, global) for LLM calls.
"""

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConcurrencyConfig:
    """Unified concurrency configuration with clear hierarchy."""
    
    # Provider-level limits (hard limits from API)
    gemini_max_concurrency: int = 6
    gemini_rate_limit_rpm: int = 14
    
    # Global LLM limits (soft limits for fairness)
    global_llm_max_concurrency: int = 8
    
    # Pipeline-level limits (workload-specific)
    batch_max_concurrency: int = 4
    batch_high_throughput_workers: int = 8
    render_max_concurrency: int = 6
    
    # Rate limiting
    llm_max_retries: int = 5
    
    # Circuit breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0
    
    # Adaptive concurrency (optional)
    adaptive_concurrency_enabled: bool = False
    adaptive_concurrency_initial: int = 6
    adaptive_concurrency_min: int = 2
    adaptive_concurrency_max: int = 12
    adaptive_concurrency_target_latency: float = 1.0
    
    def __post_init__(self):
        """Calculate effective limits after initialization."""
        # Effective LLM concurrency is min(provider, global)
        self.effective_llm_concurrency = min(
            self.gemini_max_concurrency,
            self.global_llm_max_concurrency
        )
        
        # Effective batch concurrency
        self.effective_batch_concurrency = min(
            self.batch_max_concurrency,
            self.batch_high_throughput_workers
        )
    
    @classmethod
    def from_env(cls) -> "ConcurrencyConfig":
        """Create configuration from environment variables."""
        return cls(
            # Provider-level
            gemini_max_concurrency=int(os.environ.get("GEMINI_MAX_CONCURRENCY", "6")),
            gemini_rate_limit_rpm=int(os.environ.get("GEMINI_RATE_LIMIT_RPM", "14")),
            
            # Global LLM
            global_llm_max_concurrency=int(os.environ.get("GLOBAL_LLM_MAX_CONCURRENCY", "8")),
            
            # Pipeline-level
            batch_max_concurrency=int(os.environ.get("BATCH_MAX_CONCURRENCY", "4")),
            batch_high_throughput_workers=int(os.environ.get("BATCH_HIGH_THROUGHPUT_WORKERS", "8")),
            render_max_concurrency=int(os.environ.get("RENDER_MAX_CONCURRENCY", "6")),
            
            # Rate limiting
            llm_max_retries=int(os.environ.get("LLM_MAX_RETRIES", "5")),
            
            # Circuit breaker
            circuit_breaker_failure_threshold=int(os.environ.get("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            circuit_breaker_recovery_timeout=float(os.environ.get("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "60")),
            
            # Adaptive concurrency
            adaptive_concurrency_enabled=os.environ.get("ADAPTIVE_CONCURRENCY_ENABLED", "false").lower() in ("1", "true", "yes"),
            adaptive_concurrency_initial=int(os.environ.get("ADAPTIVE_CONCURRENCY_INITIAL", "6")),
            adaptive_concurrency_min=int(os.environ.get("ADAPTIVE_CONCURRENCY_MIN", "2")),
            adaptive_concurrency_max=int(os.environ.get("ADAPTIVE_CONCURRENCY_MAX", "12")),
            adaptive_concurrency_target_latency=float(os.environ.get("ADAPTIVE_CONCURRENCY_TARGET_LATENCY", "1.0")),
        )
    
    def log_config(self) -> None:
        """Log the current configuration."""
        logger.info("=" * 70)
        logger.info("CONCURRENCY CONFIGURATION")
        logger.info("=" * 70)
        logger.info("Provider Limits:")
        logger.info("  Gemini max concurrency: %d", self.gemini_max_concurrency)
        logger.info("  Gemini rate limit RPM: %d", self.gemini_rate_limit_rpm)
        logger.info("")
        logger.info("Global Limits:")
        logger.info("  Global LLM max concurrency: %d", self.global_llm_max_concurrency)
        logger.info("  Effective LLM concurrency: %d (min of provider, global)", self.effective_llm_concurrency)
        logger.info("")
        logger.info("Pipeline Limits:")
        logger.info("  Batch max concurrency: %d", self.batch_max_concurrency)
        logger.info("  Batch high throughput workers: %d", self.batch_high_throughput_workers)
        logger.info("  Effective batch concurrency: %d", self.effective_batch_concurrency)
        logger.info("  Render max concurrency: %d", self.render_max_concurrency)
        logger.info("")
        logger.info("Rate Limiting:")
        logger.info("  LLM max retries: %d", self.llm_max_retries)
        logger.info("")
        logger.info("Circuit Breaker:")
        logger.info("  Failure threshold: %d", self.circuit_breaker_failure_threshold)
        logger.info("  Recovery timeout: %.0fs", self.circuit_breaker_recovery_timeout)
        logger.info("")
        logger.info("Adaptive Concurrency:")
        logger.info("  Enabled: %s", self.adaptive_concurrency_enabled)
        if self.adaptive_concurrency_enabled:
            logger.info("  Initial: %d", self.adaptive_concurrency_initial)
            logger.info("  Min: %d", self.adaptive_concurrency_min)
            logger.info("  Max: %d", self.adaptive_concurrency_max)
            logger.info("  Target latency: %.1fs", self.adaptive_concurrency_target_latency)
        logger.info("=" * 70)
    
    def get_effective_limits(self) -> dict:
        """Return a dictionary of effective limits for monitoring."""
        return {
            "effective_llm_concurrency": self.effective_llm_concurrency,
            "effective_batch_concurrency": self.effective_batch_concurrency,
            "gemini_rate_limit_rpm": self.gemini_rate_limit_rpm,
            "global_llm_max_concurrency": self.global_llm_max_concurrency,
            "render_max_concurrency": self.render_max_concurrency,
        }


# Global configuration instance
_config: ConcurrencyConfig | None = None


def get_concurrency_config() -> ConcurrencyConfig:
    """Get or create the global concurrency configuration."""
    global _config
    if _config is None:
        _config = ConcurrencyConfig.from_env()
        _config.log_config()
    return _config


def reload_concurrency_config() -> ConcurrencyConfig:
    """Reload configuration from environment variables."""
    global _config
    _config = ConcurrencyConfig.from_env()
    _config.log_config()
    return _config
