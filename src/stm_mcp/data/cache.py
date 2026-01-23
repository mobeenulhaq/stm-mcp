"""Simple TTL-based cache for GTFS-RT feeds."""

import asyncio
import time
from typing import Generic, TypeVar

T = TypeVar("T")


class FeedCache(Generic[T]):
    """Single-value TTL cache for one feed.

    Thread-safe cache that stores a single value with time-based expiration.
    Uses an async lock to prevent concurrent fetches.
    """

    def __init__(self, ttl: float = 30.0):
        """Initialize the cache.

        Args:
            ttl: Time-to-live in seconds for cached values.
        """
        self._ttl = ttl
        self._value: T | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    def get(self) -> T | None:
        """Get the cached value if it hasn't expired.

        Returns:
            The cached value if valid, None if expired or not set.
        """
        if self._value is not None and time.monotonic() < self._expires_at:
            return self._value
        return None

    def set(self, value: T) -> None:
        """Set a value in the cache with TTL.

        Args:
            value: The value to cache.
        """
        self._value = value
        self._expires_at = time.monotonic() + self._ttl

    def clear(self) -> None:
        """Clear the cached value."""
        self._value = None
        self._expires_at = 0

    @property
    def lock(self) -> asyncio.Lock:
        """Get the async lock for coordinating fetches."""
        return self._lock
