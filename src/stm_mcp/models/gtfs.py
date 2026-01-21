"""Pydantic models for GTFS entities."""

from pydantic import BaseModel


class Agency(BaseModel):
    """GTFS agency entity."""

    agency_id: str
    agency_name: str
    agency_url: str | None = None
    agency_timezone: str | None = None


class Route(BaseModel):
    """GTFS route entity."""

    route_id: str
    agency_id: str | None = None
    route_short_name: str | None = None
    route_long_name: str | None = None
    route_type: int  # 1=metro, 3=bus
    route_url: str | None = None
    route_color: str | None = None
    route_text_color: str | None = None


class Stop(BaseModel):
    """GTFS stop entity."""

    stop_id: str
    stop_code: str | None = None
    stop_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None
    stop_url: str | None = None
    location_type: int | None = None  # 0=stop, 1=station, 2=entrance
    parent_station: str | None = None
    wheelchair_boarding: int | None = None


class Calendar(BaseModel):
    """GTFS calendar entity for service patterns."""

    service_id: str
    monday: int
    tuesday: int
    wednesday: int
    thursday: int
    friday: int
    saturday: int
    sunday: int
    start_date: str  # YYYYMMDD
    end_date: str  # YYYYMMDD


class CalendarDate(BaseModel):
    """GTFS calendar_dates entity for service exceptions."""

    service_id: str
    date: str  # YYYYMMDD
    exception_type: int  # 1=added, 2=removed


class Trip(BaseModel):
    """GTFS trip entity."""

    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: str | None = None
    direction_id: int | None = None
    shape_id: str | None = None
    wheelchair_accessible: int | None = None
    note_fr: str | None = None
    note_en: str | None = None


class StopTime(BaseModel):
    """GTFS stop_times entity."""

    trip_id: str
    arrival_time: str | None = None  # HH:MM:SS (can exceed 24:00:00)
    departure_time: str | None = None
    stop_id: str
    stop_sequence: int
    pickup_type: int | None = None


class FeedInfo(BaseModel):
    """GTFS feed_info entity."""

    feed_publisher_name: str | None = None
    feed_publisher_url: str | None = None
    feed_lang: str | None = None
    feed_start_date: str | None = None
    feed_end_date: str | None = None
    feed_version: str | None = None
