"""Real-time service for fetching GTFS-RT data with caching.

Provides cached access to real-time trip updates and vehicle positions.
All errors are caught and logged - functions return None on failure.
"""

import logging

from stm_mcp.data.cache import FeedCache
from stm_mcp.data.config import GTFSRTConfig, get_gtfsrt_config
from stm_mcp.data.gtfsrt_client import GTFSRTClient
from stm_mcp.models.realtime import TripUpdatesData, VehiclePositionsData

logger = logging.getLogger(__name__)

# Module-level caches (lazy-initialized)
_trip_updates_cache: FeedCache[TripUpdatesData] | None = None
_vehicle_positions_cache: FeedCache[VehiclePositionsData] | None = None
_config: GTFSRTConfig | None = None


def _get_config() -> GTFSRTConfig:
    """Get or create the GTFS-RT config singleton."""
    global _config
    if _config is None:
        _config = get_gtfsrt_config()
    return _config


def _get_trip_updates_cache() -> FeedCache[TripUpdatesData]:
    """Get or create the trip updates cache singleton."""
    global _trip_updates_cache
    if _trip_updates_cache is None:
        config = _get_config()
        _trip_updates_cache = FeedCache[TripUpdatesData](ttl=config.cache_ttl_seconds)
    return _trip_updates_cache


def _get_vehicle_positions_cache() -> FeedCache[VehiclePositionsData]:
    """Get or create the vehicle positions cache singleton."""
    global _vehicle_positions_cache
    if _vehicle_positions_cache is None:
        config = _get_config()
        _vehicle_positions_cache = FeedCache[VehiclePositionsData](ttl=config.cache_ttl_seconds)
    return _vehicle_positions_cache


def is_realtime_available() -> bool:
    """Check if real-time data is available (API key configured).

    Returns:
        True if STM_API_KEY environment variable is set.
    """
    config = _get_config()
    return config.api_key is not None


async def get_trip_updates(force_refresh: bool = False) -> TripUpdatesData | None:
    """Fetch trip updates with caching.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        TripUpdatesData if successful, None if unavailable or error.
    """
    config = _get_config()
    if config.api_key is None:
        logger.debug("No API key configured, cannot fetch trip updates")
        return None

    cache = _get_trip_updates_cache()

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached = cache.get()
        if cached is not None:
            return cached

    # Acquire lock to prevent concurrent fetches
    async with cache.lock:
        # Double-check cache after acquiring lock
        if not force_refresh:
            cached = cache.get()
            if cached is not None:
                return cached

        # Fetch fresh data
        try:
            async with GTFSRTClient(config) as client:
                data = await client.fetch_trip_updates()
                cache.set(data)
                logger.debug(f"Fetched {len(data.trip_updates)} trip updates")
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch trip updates: {e}")
            return None


async def get_vehicle_positions(force_refresh: bool = False) -> VehiclePositionsData | None:
    """Fetch vehicle positions with caching.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        VehiclePositionsData if successful, None if unavailable or error.
    """
    config = _get_config()
    if config.api_key is None:
        logger.debug("No API key configured, cannot fetch vehicle positions")
        return None

    cache = _get_vehicle_positions_cache()

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached = cache.get()
        if cached is not None:
            return cached

    # Acquire lock to prevent concurrent fetches
    async with cache.lock:
        # Double-check cache after acquiring lock
        if not force_refresh:
            cached = cache.get()
            if cached is not None:
                return cached

        # Fetch fresh data
        try:
            async with GTFSRTClient(config) as client:
                data = await client.fetch_vehicle_positions()
                cache.set(data)
                logger.debug(f"Fetched {len(data.vehicles)} vehicle positions")
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch vehicle positions: {e}")
            return None


def clear_caches() -> None:
    """Clear all real-time data caches.

    Useful for testing or forcing fresh data on next request.
    """
    global _trip_updates_cache, _vehicle_positions_cache, _config
    if _trip_updates_cache:
        _trip_updates_cache.clear()
    if _vehicle_positions_cache:
        _vehicle_positions_cache.clear()


def reset_service() -> None:
    """Reset the service state completely.

    Clears caches and resets config. Useful for testing.
    """
    global _trip_updates_cache, _vehicle_positions_cache, _config
    _trip_updates_cache = None
    _vehicle_positions_cache = None
    _config = None
    # Clear the lru_cache on get_gtfsrt_config so it re-reads .env/environment
    # (hasattr check handles case where function is mocked in tests)
    if hasattr(get_gtfsrt_config, "cache_clear"):
        get_gtfsrt_config.cache_clear()
