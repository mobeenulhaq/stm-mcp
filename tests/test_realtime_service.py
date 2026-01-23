"""Tests for the real-time service."""

import pytest

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.services import realtime_service


@pytest.fixture(autouse=True)
def reset_service():
    """Reset the service state before and after each test."""
    realtime_service.reset_service()
    yield
    realtime_service.reset_service()


def _config_without_api_key() -> GTFSRTConfig:
    """Create a config without an API key.

    Note: Must use alias name (STM_API_KEY) to override .env file values.
    """
    return GTFSRTConfig(STM_API_KEY=None)


def _config_with_api_key() -> GTFSRTConfig:
    """Create a config with an API key."""
    return GTFSRTConfig(STM_API_KEY="test_key")


@pytest.mark.asyncio
async def test_get_trip_updates_returns_none_without_api_key():
    """get_trip_updates should return None when no API key is configured."""
    realtime_service._config = _config_without_api_key()
    result = await realtime_service.get_trip_updates()
    assert result is None


def test_is_realtime_available_without_api_key():
    """is_realtime_available should return False without API key."""
    realtime_service._config = _config_without_api_key()
    assert realtime_service.is_realtime_available() is False
