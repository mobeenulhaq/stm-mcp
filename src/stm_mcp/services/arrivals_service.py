"""Arrivals service for merging static GTFS schedule with real-time predictions.

Implements "static-first" with "graceful degradation":
- All tools work without real-time data; RT overlays predictions
- RT failures fall back to static with source: "static"
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from stm_mcp.models.realtime import (
    OccupancyStatus,
    StopTimeUpdate,
    TripUpdatesData,
    VehiclePosition,
    VehiclePositionsData,
)
from stm_mcp.models.responses import (
    Arrival,
    ArrivalSource,
    GetNextArrivalsResponse,
    ScheduledArrival,
)
from stm_mcp.services.realtime_service import (
    get_trip_updates,
    get_vehicle_positions,
    is_realtime_available,
)
from stm_mcp.services.schedule_service import (
    calculate_minutes_until,
    format_gtfs_time,
    get_scheduled_arrivals,
    gtfs_time_to_seconds,
)

logger = logging.getLogger(__name__)


def apply_delay_to_time(scheduled_time: str, delay_seconds: int) -> str:
    """Apply delay to a GTFS time string.

    Args:
        scheduled_time: Scheduled time in HH:MM:SS format.
        delay_seconds: Delay in seconds (positive=late, negative=early).

    Returns:
        New time string in HH:MM:SS format.
    """
    scheduled_seconds = gtfs_time_to_seconds(scheduled_time)
    predicted_seconds = scheduled_seconds + delay_seconds

    # Convert back to HH:MM:SS (can exceed 24:00)
    hours = predicted_seconds // 3600
    remaining = predicted_seconds % 3600
    minutes = remaining // 60
    seconds = remaining % 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_trip_update_index(
    trip_updates: TripUpdatesData,
    stop_id: str,
) -> dict[str, tuple[StopTimeUpdate, int | None]]:
    """Build index of trip updates for a specific stop.

    Args:
        trip_updates: Trip updates data from RT feed.
        stop_id: Stop ID to filter for.

    Returns:
        Dict mapping trip_id -> (StopTimeUpdate for this stop, feed timestamp).
    """
    index: dict[str, tuple[StopTimeUpdate, int | None]] = {}

    for trip_update in trip_updates.trip_updates:
        trip_id = trip_update.trip.trip_id
        if trip_id is None:
            continue

        # Find stop_time_update for this stop
        for stu in trip_update.stop_time_update:
            if stu.stop_id == stop_id:
                index[trip_id] = (stu, trip_update.timestamp)
                break  # Only one update per stop per trip

    return index


def build_vehicle_position_index(
    vehicle_positions: VehiclePositionsData,
) -> dict[str, VehiclePosition]:
    """Build index of vehicle positions by trip_id.

    Args:
        vehicle_positions: Vehicle positions data from RT feed.

    Returns:
        Dict mapping trip_id -> VehiclePosition.
    """
    index: dict[str, VehiclePosition] = {}

    for vehicle in vehicle_positions.vehicles:
        if vehicle.trip and vehicle.trip.trip_id:
            index[vehicle.trip.trip_id] = vehicle

    return index


def merge_arrival_with_realtime(
    scheduled: ScheduledArrival,
    stop_time_update: StopTimeUpdate | None,
    vehicle_position: VehiclePosition | None,
    query_time: str,
    rt_timestamp: int | None,
) -> Arrival:
    """Merge a scheduled arrival with real-time data.

    Only uses delay from StopTimeEvent (simpler, avoids timezone issues).
    Skips RT prediction if only absolute time present (no delay).

    Args:
        scheduled: Scheduled arrival from static GTFS.
        stop_time_update: Real-time stop time update (if available).
        vehicle_position: Real-time vehicle position (if available).
        query_time: Query time in HH:MM:SS format for minutes_until calculation.
        rt_timestamp: RT feed timestamp for staleness detection.

    Returns:
        Merged Arrival object.
    """
    # Start with static data
    predicted_arrival_time: str | None = None
    predicted_arrival_formatted: str | None = None
    delay_seconds: int | None = None
    source = ArrivalSource.STATIC
    timestamp = rt_timestamp

    # Apply delay from stop_time_update if available
    if stop_time_update and stop_time_update.arrival:
        arrival_event = stop_time_update.arrival
        # Only use delay if present (skip if only absolute time)
        if arrival_event.delay is not None:
            delay_seconds = arrival_event.delay
            predicted_arrival_time = apply_delay_to_time(scheduled.arrival_time, delay_seconds)
            predicted_arrival_formatted = format_gtfs_time(predicted_arrival_time)
            source = ArrivalSource.REALTIME

    # Get occupancy from vehicle position
    occupancy_status: OccupancyStatus | None = None
    if vehicle_position:
        occupancy_status = vehicle_position.occupancy_status
        if occupancy_status is not None:
            source = ArrivalSource.REALTIME
            # Use vehicle timestamp if no trip update timestamp
            if timestamp is None and vehicle_position.timestamp:
                timestamp = vehicle_position.timestamp

    # Calculate minutes_until using effective time (predicted if available)
    effective_time = predicted_arrival_time or scheduled.arrival_time
    minutes_until = calculate_minutes_until(effective_time, query_time)

    return Arrival(
        trip_id=scheduled.trip_id,
        route_id=scheduled.route_id,
        route_short_name=scheduled.route_short_name,
        route_type=scheduled.route_type,
        trip_headsign=scheduled.trip_headsign,
        scheduled_arrival_time=scheduled.arrival_time,
        scheduled_arrival_formatted=scheduled.arrival_time_formatted,
        predicted_arrival_time=predicted_arrival_time,
        predicted_arrival_formatted=predicted_arrival_formatted,
        delay_seconds=delay_seconds,
        minutes_until=minutes_until,
        occupancy_status=occupancy_status,
        source=source,
        rt_timestamp=timestamp,
    )


async def get_next_arrivals(
    stop_id: str,
    route_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
    include_realtime: bool = True,
) -> GetNextArrivalsResponse:
    """Get upcoming arrivals at a stop with real-time predictions.

    Implements "static-first" with "graceful degradation":
    - Always returns static schedule data
    - Overlays RT predictions when available
    - Falls back to static-only on RT failure

    Args:
        stop_id: The stop ID to get arrivals for.
        route_id: Optional route ID to filter by.
        start_time: Start of time window in HH:MM:SS format (default: now).
        end_time: End of time window in HH:MM:SS format (default: 28:00:00).
        limit: Maximum number of arrivals to return.
        db_path: Optional database path override.
        include_realtime: Whether to fetch RT data (default: True).

    Returns:
        GetNextArrivalsResponse with merged arrivals.

    Raises:
        ValueError: If stop_id is not found.
    """
    # Step 1: Get scheduled arrivals (static data)
    scheduled_response = await get_scheduled_arrivals(
        stop_id=stop_id,
        route_id=route_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        db_path=db_path,
    )

    # If no scheduled arrivals, return empty response
    if not scheduled_response.arrivals:
        return GetNextArrivalsResponse(
            stop=scheduled_response.stop,
            arrivals=[],
            service_date=scheduled_response.service_date,
            query_time=scheduled_response.query_time,
            count=0,
            realtime_available=False,
        )

    # Step 2: Check if RT should be fetched
    should_fetch_rt = (
        include_realtime
        and is_realtime_available()
        # At least one bus in results (route_type=3)
        and any(a.route_type == 3 for a in scheduled_response.arrivals)
    )

    trip_updates: TripUpdatesData | None = None
    vehicle_positions: VehiclePositionsData | None = None

    if should_fetch_rt:
        # Step 3: Fetch RT data in parallel
        trip_updates, vehicle_positions = await asyncio.gather(
            get_trip_updates(),
            get_vehicle_positions(),
        )

    # Step 4: Build indexes
    trip_update_index: dict[str, tuple[StopTimeUpdate, int | None]] = {}
    vehicle_position_index: dict[str, VehiclePosition] = {}

    if trip_updates:
        trip_update_index = build_trip_update_index(trip_updates, stop_id)

    if vehicle_positions:
        vehicle_position_index = build_vehicle_position_index(vehicle_positions)

    # Step 5: Merge each arrival with RT data
    arrivals: list[Arrival] = []
    static_count = 0
    realtime_count = 0

    for scheduled in scheduled_response.arrivals:
        stop_time_update: StopTimeUpdate | None = None
        vehicle_position: VehiclePosition | None = None
        rt_timestamp: int | None = None

        # Only look up RT for buses (route_type=3), metro has no RT
        if scheduled.route_type == 3:
            if scheduled.trip_id in trip_update_index:
                stop_time_update, rt_timestamp = trip_update_index[scheduled.trip_id]
            if scheduled.trip_id in vehicle_position_index:
                vehicle_position = vehicle_position_index[scheduled.trip_id]

        arrival = merge_arrival_with_realtime(
            scheduled=scheduled,
            stop_time_update=stop_time_update,
            vehicle_position=vehicle_position,
            query_time=scheduled_response.query_time,
            rt_timestamp=rt_timestamp,
        )
        arrivals.append(arrival)

        if arrival.source == ArrivalSource.REALTIME:
            realtime_count += 1
        else:
            static_count += 1

    # Step 6: Re-sort arrivals by effective time (predicted if available, else scheduled)
    def sort_key(a: Arrival) -> int:
        effective_time = a.predicted_arrival_time or a.scheduled_arrival_time
        return gtfs_time_to_seconds(effective_time)

    arrivals.sort(key=sort_key)

    # Step 7: Determine RT status
    realtime_available = trip_updates is not None
    realtime_updated_at: str | None = None

    if trip_updates:
        # Convert feed timestamp to ISO format
        feed_timestamp = trip_updates.header.timestamp
        realtime_updated_at = datetime.fromtimestamp(feed_timestamp, tz=UTC).isoformat()

    return GetNextArrivalsResponse(
        stop=scheduled_response.stop,
        arrivals=arrivals,
        service_date=scheduled_response.service_date,
        query_time=scheduled_response.query_time,
        count=len(arrivals),
        realtime_available=realtime_available,
        realtime_updated_at=realtime_updated_at,
        static_only_count=static_count,
        realtime_count=realtime_count,
    )
