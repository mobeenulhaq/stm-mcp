from enum import Enum

from pydantic import BaseModel, Field

from stm_mcp.models.realtime import OccupancyStatus


class ArrivalSource(str, Enum):
    """Indicates whether arrival data is from static schedule (GTFS db) or real-time (GTFS RT)."""
    STATIC = "static"
    REALTIME = "realtime"


class StopResult(BaseModel):
    stop_id: str
    stop_code: str | None = None
    stop_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None
    location_type: int | None = Field(
        default=None, description="0=stop/platform, 1=station, 2=entrance/exit"
    )
    parent_station: str | None = None
    wheelchair_boarding: int | None = Field(
        default=None, description="0=no info, 1=accessible, 2=not accessible"
    )
    distance_meters: float | None = Field(
        default=None, description="Distance from search coordinates (geo search only)"
    )


class SearchStopsResponse(BaseModel):
    stops: list[StopResult]
    count: int = Field(description="Number of stops returned")
    total_matches: int | None = Field(
        default=None, description="Total matches before limit applied (if known)"
    )


class ScheduledArrival(BaseModel):
    trip_id: str
    route_id: str
    route_short_name: str | None = Field(default=None, description="Bus number or line name")
    route_type: int = Field(description="1=metro, 3=bus")
    trip_headsign: str | None = Field(default=None, description="Destination displayed on vehicle")
    arrival_time: str = Field(description="Scheduled arrival time in HH:MM:SS format")
    arrival_time_formatted: str = Field(description="Human-readable time (e.g., '1:30 AM (+1)')")
    minutes_until: int | None = Field(
        default=None, description="Minutes until arrival from query time"
    )


class StopInfo(BaseModel):
    stop_id: str
    stop_name: str
    stop_code: str | None = None


class GetScheduledArrivalsResponse(BaseModel):
    stop: StopInfo
    arrivals: list[ScheduledArrival]
    service_date: str = Field(description="Service date in YYYY-MM-DD format")
    query_time: str = Field(description="Query time in HH:MM:SS format")
    count: int = Field(description="Number of arrivals returned")


class Arrival(BaseModel):
    """Arrival with merged static schedule and real-time prediction data."""

    # Trip identification
    trip_id: str
    route_id: str
    route_short_name: str | None = None
    route_type: int = Field(description="1=metro, 3=bus")
    trip_headsign: str | None = None

    # Scheduled time (always present)
    scheduled_arrival_time: str = Field(description="Scheduled arrival in HH:MM:SS format")
    scheduled_arrival_formatted: str = Field(description="Human-readable scheduled time")

    # Predicted time (only when RT available)
    predicted_arrival_time: str | None = Field(
        default=None, description="Predicted arrival in HH:MM:SS format"
    )
    predicted_arrival_formatted: str | None = Field(
        default=None, description="Human-readable predicted time"
    )
    delay_seconds: int | None = Field(
        default=None, description="Delay in seconds (positive=late, negative=early)"
    )

    # Effective minutes until (uses predicted if available)
    minutes_until: int | None = Field(
        default=None, description="Minutes until arrival from query time"
    )

    # Occupancy (buses only, when RT available)
    occupancy_status: OccupancyStatus | None = None

    # Source tracking
    source: ArrivalSource = ArrivalSource.STATIC
    rt_timestamp: int | None = Field(
        default=None, description="RT feed timestamp for staleness detection"
    )


class GetNextArrivalsResponse(BaseModel):
    """Response for get_next_arrivals with merged static and real-time data."""

    stop: StopInfo
    arrivals: list[Arrival]
    service_date: str = Field(description="Service date in YYYY-MM-DD format")
    query_time: str = Field(description="Query time in HH:MM:SS format")
    count: int = Field(description="Number of arrivals returned")

    # RT status
    realtime_available: bool = Field(
        description="Whether real-time data was available for this query"
    )
    realtime_updated_at: str | None = Field(
        default=None, description="ISO timestamp of last RT update"
    )
    static_only_count: int = Field(default=0, description="Number of static-only arrivals")
    realtime_count: int = Field(default=0, description="Number of arrivals with RT data")
