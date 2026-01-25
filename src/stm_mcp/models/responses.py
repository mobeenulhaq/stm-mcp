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


# Metro Status and Service Alerts (i3 API)


class MetroLine(str, Enum):
    """STM metro lines by route_id."""

    GREEN = "1"
    ORANGE = "2"
    YELLOW = "4"
    BLUE = "5"


class MetroStatus(str, Enum):
    """Status of a metro line."""

    NORMAL = "normal"
    DISRUPTED = "disrupted"
    UNKNOWN = "unknown"


class MetroLineStatus(BaseModel):
    """Status of a single metro line."""

    line: MetroLine
    line_name: str = Field(description="Human-readable line name (e.g., 'Green Line')")
    status: MetroStatus
    alerts: list["ServiceAlert"] = Field(
        default_factory=list, description="Alerts affecting this line"
    )


class ServiceAlert(BaseModel):
    """Processed service alert for display."""

    # Bilingual text fields
    header_fr: str | None = None
    header_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None

    # Affected entities
    route_short_name: str | None = Field(
        default=None, description="Route number/short name (e.g., '24', '1')"
    )
    direction_id: str | None = Field(
        default=None, description="Direction identifier (e.g., 'N', 'E')"
    )
    stop_code: str | None = Field(default=None, description="Affected stop code")

    # Time period
    active_start: int | None = Field(
        default=None, description="Unix timestamp when alert became active"
    )
    active_end: int | None = Field(
        default=None, description="Unix timestamp when alert ends (null if ongoing)"
    )

    # Classification
    is_metro: bool = Field(default=False, description="True if this alert is for a metro line")


class GetMetroStatusResponse(BaseModel):
    """Response for get_metro_status tool."""

    lines: list[MetroLineStatus] = Field(description="Status of all 4 metro lines")
    timestamp: int = Field(description="Unix timestamp of the i3 API response")
    all_normal: bool = Field(description="True if all lines have normal service")
    api_available: bool = Field(
        description="Whether the i3 API was reachable (false if API key missing or error)"
    )


class GetServiceAlertsResponse(BaseModel):
    """Response for get_service_alerts tool."""

    alerts: list[ServiceAlert] = Field(description="Filtered service alerts")
    count: int = Field(description="Number of alerts returned")
    total_count: int = Field(description="Total alerts before filtering")
    timestamp: int | None = Field(
        default=None, description="Unix timestamp of the i3 API response"
    )
    api_available: bool = Field(
        description="Whether the i3 API was reachable (false if API key missing or error)"
    )


# Trip Planning Models


class TripLeg(BaseModel):
    """Single leg of a transit trip (one vehicle)."""

    # Route identification
    route_id: str
    route_short_name: str | None = Field(default=None, description="From routes table")
    route_type: int = Field(description="1=metro, 3=bus")
    trip_id: str
    trip_headsign: str | None = None

    # Boarding stop
    from_stop_id: str
    from_stop_name: str
    from_stop_code: str | None = None

    # Alighting stop
    to_stop_id: str
    to_stop_name: str
    to_stop_code: str | None = None

    # Times (GTFS format - can exceed 24:00:00)
    departure_time: str = Field(description="HH:MM:SS format")
    departure_time_formatted: str
    arrival_time: str = Field(description="HH:MM:SS format")
    arrival_time_formatted: str

    # Duration and stops
    duration_minutes: int
    num_stops: int = Field(description="Number of stops traveled (including endpoints)")


class Itinerary(BaseModel):
    """Complete journey from origin to destination."""

    legs: list[TripLeg] = Field(description="Ordered list of trip legs")

    # Overall times
    departure_time: str = Field(description="First leg departure, HH:MM:SS")
    departure_time_formatted: str
    arrival_time: str = Field(description="Last leg arrival, HH:MM:SS")
    arrival_time_formatted: str

    # Summary
    total_duration_minutes: int
    num_transfers: int = Field(description="Number of transfers (legs - 1)")

    # Transfer details (only present for multi-leg itineraries)
    transfer_wait_minutes: int | None = Field(
        default=None, description="Wait time at transfer point"
    )
    transfer_walk_meters: float | None = Field(
        default=None, description="Walking distance if transfer requires walking"
    )


class StopResolutionInfo(BaseModel):
    """How a stop query was resolved."""

    query: str = Field(description="Original user query")
    resolved_stop_id: str | None = None
    resolved_stop_name: str | None = None
    confidence: str | None = Field(default=None, description="exact, high, medium, low")
    resolved: bool
    error: str | None = None


class PlanTripResponse(BaseModel):
    """Response from plan_trip tool."""

    # Resolution status
    origin_resolution: StopResolutionInfo
    destination_resolution: StopResolutionInfo

    # Results
    itineraries: list[Itinerary] = Field(default_factory=list)

    # Time context
    service_date: str = Field(description="GTFS service date YYYY-MM-DD")
    departure_date: str = Field(description="Query date YYYY-MM-DD")
    query_time: str = Field(description="Departure time HH:MM:SS")

    # Status
    count: int
    success: bool
    error: str | None = None
