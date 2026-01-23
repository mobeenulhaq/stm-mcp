"""Tests for the TTL-based cache."""

import time

from stm_mcp.data.cache import FeedCache


def test_cache_ttl_expiration():
    """Cache should return None after TTL expires."""
    # Use a very short TTL for testing
    cache: FeedCache[str] = FeedCache(ttl=0.1)

    # Set a value
    cache.set("test_value")

    # Should be available immediately
    assert cache.get() == "test_value"

    # Wait for TTL to expire
    time.sleep(0.15)

    # Should now return None
    assert cache.get() is None


def test_cache_returns_value_before_expiration():
    """Cache should return value before TTL expires."""
    cache: FeedCache[str] = FeedCache(ttl=10.0)

    cache.set("test_value")
    assert cache.get() == "test_value"


def test_cache_clear():
    """Cache clear should remove the value."""
    cache: FeedCache[str] = FeedCache(ttl=10.0)

    cache.set("test_value")
    assert cache.get() == "test_value"

    cache.clear()
    assert cache.get() is None


def test_cache_overwrite():
    """Setting a new value should overwrite the old one."""
    cache: FeedCache[str] = FeedCache(ttl=10.0)

    cache.set("first")
    assert cache.get() == "first"

    cache.set("second")
    assert cache.get() == "second"
