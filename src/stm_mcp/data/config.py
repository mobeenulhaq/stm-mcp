from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GTFSRTConfig(BaseSettings):
    """Configuration for GTFS-RT API access.

    Automatically loads from environment variables and .env file.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str | None = Field(default=None, alias="STM_API_KEY")
    cache_ttl_seconds: int = Field(default=30, alias="STM_CACHE_TTL")
    trip_updates_url: str = "https://api.stm.info/pub/od/gtfs-rt/ic/v2/tripUpdates"
    vehicle_positions_url: str = "https://api.stm.info/pub/od/gtfs-rt/ic/v2/vehiclePositions"


@lru_cache
def get_gtfsrt_config() -> GTFSRTConfig:
    """Get GTFS-RT configuration (cached singleton).

    Returns:
        GTFSRTConfig with values from .env file or environment variables.
    """
    return GTFSRTConfig()
