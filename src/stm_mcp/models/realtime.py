"""Pydantic models for GTFS-RT data.

These models represent the subset of GTFS-RT fields we actually use.
Full GTFS-RT spec has many more fields, but we only model what we need.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class OccupancyStatus(str, Enum):
    """Vehicle occupancy level (GTFS-RT standard enum).

    STM maps their 1-4 levels as:
      1 (Nearly empty) -> MANY_SEATS_AVAILABLE
      2 (Some seats)   -> FEW_SEATS_AVAILABLE
      3 (Standing)     -> STANDING_ROOM_ONLY
      4 (Nearly full)  -> FULL
    """

    EMPTY = "EMPTY"
    MANY_SEATS_AVAILABLE = "MANY_SEATS_AVAILABLE"
    FEW_SEATS_AVAILABLE = "FEW_SEATS_AVAILABLE"
    STANDING_ROOM_ONLY = "STANDING_ROOM_ONLY"
    CRUSHED_STANDING_ROOM_ONLY = "CRUSHED_STANDING_ROOM_ONLY"
    FULL = "FULL"
    NOT_ACCEPTING_PASSENGERS = "NOT_ACCEPTING_PASSENGERS"


class StopTimeEvent(BaseModel):
    """Predicted arrival or departure time at a stop."""

    delay: int | None = None  # seconds late (positive) or early (negative)
    time: int | None = None  # predicted unix timestamp


class StopTimeUpdate(BaseModel):
    """Update for a single stop in a trip."""

    stop_sequence: int | None = None
    stop_id: str | None = None
    arrival: StopTimeEvent | None = None
    departure: StopTimeEvent | None = None


class TripDescriptor(BaseModel):
    """Identifies a trip for real-time updates."""

    trip_id: str | None = None
    route_id: str | None = None
    direction_id: int | None = None
    start_time: str | None = None  # HH:MM:SS
    start_date: str | None = None  # YYYYMMDD


class TripUpdate(BaseModel):
    """Real-time update for a single trip."""

    trip: TripDescriptor
    stop_time_update: list[StopTimeUpdate] = []
    timestamp: int | None = None


class Position(BaseModel):
    """Geographic position of a vehicle."""

    latitude: float
    longitude: float
    bearing: float | None = None
    speed: float | None = None  # meters/second


class VehicleDescriptor(BaseModel):
    """Identifies a vehicle."""

    id: str | None = None
    label: str | None = None


class VehiclePosition(BaseModel):
    """Real-time position of a transit vehicle."""

    trip: TripDescriptor | None = None
    vehicle: VehicleDescriptor | None = None
    position: Position | None = None
    current_stop_sequence: int | None = None
    stop_id: str | None = None
    occupancy_status: OccupancyStatus | None = None
    timestamp: int | None = None


class FeedHeader(BaseModel):
    """Header information from GTFS-RT feed."""

    gtfs_realtime_version: str
    timestamp: int


class TripUpdatesData(BaseModel):
    """Complete trip updates feed data."""

    header: FeedHeader
    trip_updates: list[TripUpdate] = []
    fetched_at: datetime


class VehiclePositionsData(BaseModel):
    """Complete vehicle positions feed data."""

    header: FeedHeader
    vehicles: list[VehiclePosition] = []
    fetched_at: datetime
