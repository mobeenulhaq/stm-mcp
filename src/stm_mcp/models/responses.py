from pydantic import BaseModel, Field


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
