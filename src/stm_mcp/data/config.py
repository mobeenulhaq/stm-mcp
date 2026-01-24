from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GTFSRTConfig(BaseSettings):
    """Configuration for GTFS-RT and i3 API access.

    Automatically loads from environment variables and .env file.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str | None = Field(default=None, alias="STM_API_KEY")
    cache_ttl_seconds: int = Field(default=30, alias="STM_CACHE_TTL")
    trip_updates_url: str = "https://api.stm.info/pub/od/gtfs-rt/ic/v2/tripUpdates"
    vehicle_positions_url: str = "https://api.stm.info/pub/od/gtfs-rt/ic/v2/vehiclePositions"

    # i3 API (service status and alerts)
    i3_etatservice_url: str = "https://api.stm.info/pub/od/i3/v2/messages/etatservice"
    i3_cache_ttl_seconds: int = Field(default=15, alias="STM_I3_CACHE_TTL")


@lru_cache
def get_gtfsrt_config() -> GTFSRTConfig:
    """Get GTFS-RT configuration (cached singleton).

    Returns:
        GTFSRTConfig with values from .env file or environment variables.
    """
    return GTFSRTConfig()
