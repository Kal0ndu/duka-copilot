"""Rate limit handling for Gemini API with free-tier support.

Gemini free tier limits:
- Per-minute: 60 requests/minute (1 per second)
- Daily: 1500 free requests/day (varies by model)

This module provides intelligent backoff and rate-limit detection.
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta
import os
import re
import time
import logging

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Base rate limit error. retry_after: seconds the server asked us to wait."""

    def __init__(self, message: str = "", retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class PerMinuteRateLimitError(RateLimitError):
    """Per-minute rate limit exceeded (recoverable)."""
    pass


class DailyRateLimitError(RateLimitError):
    """Daily quota exceeded (not recoverable for free tier)."""
    pass


class RateLimiter:
    """Manages rate limits for Gemini API with smart backoff."""
    
    # Gemini free tier limits (flash models allow ~10-15 requests/minute).
    # Override with LLM_RPM in .env for a paid tier.
    PER_MINUTE_LIMIT = int(os.getenv("LLM_RPM", "10"))
    DAILY_LIMIT = 1500  # requests per day (approximate)
    MIN_REQUEST_INTERVAL = 60.0 / PER_MINUTE_LIMIT  # spread calls evenly over the minute
    DEFAULT_RETRY_SECONDS = 30.0
    
    def __init__(self):
        self.last_request_time: Optional[float] = None
        self.request_times: list = []  # Track recent requests for per-minute calculation
        self.daily_request_count = 0
        self.daily_reset_time: Optional[datetime] = None
        self.is_daily_limited = False
        self.daily_limit_until: Optional[datetime] = None
    
    @staticmethod
    def _retry_after(error_str: str) -> Optional[float]:
        """The wait the server suggested, e.g. 'retry_delay { seconds: 32 }'
        or 'Please retry in 31.5s'."""
        m = (re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", error_str)
             or re.search(r"retry in\s*([\d.]+)\s*s", error_str, re.IGNORECASE))
        return float(m.group(1)) if m else None

    def _classify_error(self, error: Exception) -> Tuple[Optional[RateLimitError], str]:
        """Classify an error as a per-minute or daily rate limit.

        Gemini returns 429 / RESOURCE_EXHAUSTED / "quota" for BOTH limits, so
        those words alone don't tell them apart. The quota id does:
        "...PerDay..." means the daily allowance is used up; anything else
        ("...PerMinute...", or no id) is the per-minute limit.

        Returns:
            Tuple of (error_type, message) where error_type is None if not a rate limit error.
        """
        error_msg = str(error)
        error_str = error_msg.lower()
        is_rate_limit = ("429" in error_str or "too many requests" in error_str
                         or "quota" in error_str or "resource exhausted" in error_str
                         or "resource_exhausted" in error_str or "rate limit" in error_str)
        if not is_rate_limit:
            return None, error_msg
        retry_after = self._retry_after(error_msg)
        if "perday" in error_str or "per day" in error_str or "per_day" in error_str or "daily" in error_str:
            return DailyRateLimitError("Daily quota exceeded", retry_after), error_msg
        return PerMinuteRateLimitError("Per-minute rate limit exceeded",
                                       retry_after or self.DEFAULT_RETRY_SECONDS), error_msg

    def classify(self, error: Exception) -> Optional[RateLimitError]:
        """The matching RateLimitError for an exception, or None."""
        return self._classify_error(error)[0]

    def wait_before_request(self, force_check: bool = False) -> None:
        """Sleep if necessary to respect per-minute rate limits.
        
        This implements smart spacing for free-tier free requests.
        For Gemini free tier: ~1 request per second.
        """
        if self.is_daily_limited:
            remaining = (self.daily_limit_until - datetime.now()).total_seconds() if self.daily_limit_until else 3600
            if remaining > 0:
                logger.warning(f"Daily rate limit active for {remaining:.0f} more seconds.")
                raise DailyRateLimitError(f"Daily limit reset in {remaining:.0f}s. Try again later.",
                                          retry_after=remaining)
            else:
                self.is_daily_limited = False
        
        # Clean up old request times (older than 1 minute)
        now = time.monotonic()
        self.request_times = [t for t in self.request_times if now - t < 60.0]
        
        # Check per-minute limit
        if len(self.request_times) >= self.PER_MINUTE_LIMIT:
            # We've made 60 requests in the last minute; wait
            oldest_in_window = self.request_times[0]
            wait_time = 60.0 - (now - oldest_in_window) + 0.1  # Add small buffer
            if wait_time > 0:
                logger.info(f"Per-minute rate limit: sleeping {wait_time:.1f}s")
                time.sleep(wait_time)
                self.request_times = []  # Reset counter after wait
        
        # Enforce minimum interval between requests (free tier: ~1 sec)
        if self.last_request_time is not None:
            elapsed = now - self.last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                sleep_time = self.MIN_REQUEST_INTERVAL - elapsed
                time.sleep(sleep_time)
        
        self.request_times.append(time.monotonic())
        self.last_request_time = time.monotonic()
    
    def handle_rate_limit_error(self, error: Exception) -> Optional[float]:
        """Process a rate limit error and return suggested wait time, or raise if unrecoverable.
        
        Args:
            error: The exception from the LLM call
        
        Returns:
            Wait time in seconds if per-minute limit, or None if daily limit
        
        Raises:
            DailyRateLimitError: If daily quota exceeded
        """
        error_type, error_msg = self._classify_error(error)
        
        if error_type is None:
            return None  # Not a rate limit error
        
        if isinstance(error_type, DailyRateLimitError):
            # Mark as daily limited until the server's suggested time (or 24h)
            self.is_daily_limited = True
            self.daily_limit_until = datetime.now() + timedelta(
                seconds=error_type.retry_after or 24 * 3600)
            logger.error(f"Daily rate limit hit. Will retry at {self.daily_limit_until}")
            raise error_type(error_msg)
        
        if isinstance(error_type, PerMinuteRateLimitError):
            # Per-minute limit: wait what the server asked for (+1s margin)
            wait_time = (error_type.retry_after or self.DEFAULT_RETRY_SECONDS) + 1.0
            logger.warning(f"Per-minute rate limit. Suggesting {wait_time}s wait.")
            return wait_time
        
        return None
    
    def record_success(self) -> None:
        """Record a successful request (for daily quota tracking)."""
        self.daily_request_count += 1
        
        # Reset daily counter at midnight or after 24 hours
        if self.daily_reset_time is None:
            self.daily_reset_time = datetime.now() + timedelta(hours=24)
        elif datetime.now() >= self.daily_reset_time:
            self.daily_request_count = 1
            self.daily_reset_time = datetime.now() + timedelta(hours=24)
    
    def get_status(self) -> dict:
        """Return current rate limit status for monitoring."""
        now = time.monotonic()
        recent_requests = len([t for t in self.request_times if now - t < 60.0])
        
        return {
            "recent_requests_per_minute": recent_requests,
            "daily_request_count": self.daily_request_count,
            "is_daily_limited": self.is_daily_limited,
            "daily_limit_until": self.daily_limit_until.isoformat() if self.daily_limit_until else None,
        }
