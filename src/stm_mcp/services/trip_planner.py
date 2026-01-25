from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stm_mcp.data.database import get_db
from stm_mcp.matching.stop_matcher import resolve_stop
from stm_mcp.models.responses import (
    Itinerary,
    PlanTripResponse,
    StopResolutionInfo,
    TripLeg,
)
from stm_mcp.services.schedule_service import (
    format_gtfs_time,
    get_active_service_ids,
    gtfs_time_to_seconds,
    time_to_gtfs_format,
)
from stm_mcp.services.stop_service import haversine_distance

# Time window constants
TIME_WINDOW_HOURS = 2

# Transfer timing constraints
MIN_TRANSFER_TIME_MINUTES = 3
MAX_TRANSFER_TIME_MINUTES = 30
MAX_WALKING_DISTANCE_METERS = 400


@dataclass
class OutboundSegment:
    """A trip segment from origin to a potential transfer stop."""

    trip_id: str
    route_id: str
    route_short_name: str | None
    route_type: int
    trip_headsign: str | None
    origin_departure: str  # GTFS time at origin
    origin_seq: int
    xfer_stop_id: str  # Transfer stop ID
    xfer_arrival: str  # GTFS time at transfer stop
    xfer_seq: int


@dataclass
class InboundSegment:
    """A trip segment from a potential transfer stop to destination."""

    trip_id: str
    route_id: str
    route_short_name: str | None
    route_type: int
    trip_headsign: str | None
    xfer_stop_id: str  # Transfer stop ID
    xfer_departure: str  # GTFS time at transfer stop
    xfer_seq: int
    dest_arrival: str  # GTFS time at destination
    dest_seq: int


@dataclass
class TransferPoint:
    """A valid transfer between outbound and inbound segments."""

    outbound: OutboundSegment
    inbound: InboundSegment
    wait_minutes: int  # Time waiting at transfer stop
    walk_meters: float  # Walking distance (0 if same stop)
    walk_minutes: int  # Time spent walking (0 if same stop)


async def _resolve_stop_for_planning(
    query: str,
    db_path: Path | None = None,
) -> StopResolutionInfo:
    """Resolve a stop query and return StopResolutionInfo."""
    try:
        result = await resolve_stop(query=query, limit=1, db_path=db_path)

        if result.best_match:
            return StopResolutionInfo(
                query=query,
                resolved_stop_id=result.best_match.stop_id,
                resolved_stop_name=result.best_match.stop_name,
                confidence=result.best_match.confidence.value,
                resolved=result.resolved,
                error=None,
            )
        else:
            return StopResolutionInfo(
                query=query,
                resolved_stop_id=None,
                resolved_stop_name=None,
                confidence=None,
                resolved=False,
                error="No matching stop found",
            )
    except Exception as e:
        return StopResolutionInfo(
            query=query,
            resolved_stop_id=None,
            resolved_stop_name=None,
            confidence=None,
            resolved=False,
            error=str(e),
        )


async def _get_stop_info(db, stop_id: str) -> dict:
    """Get stop name and code from database."""
    sql = "SELECT stop_name, stop_code FROM stops WHERE stop_id = ?"
    async with db.execute(sql, (stop_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            return {"name": row["stop_name"], "code": row["stop_code"]}
        return {"name": stop_id, "code": None}


async def _get_stop_location(db, stop_id: str) -> dict | None:
    """Get stop location and parent station from database."""
    sql = "SELECT stop_lat, stop_lon, parent_station FROM stops WHERE stop_id = ?"
    async with db.execute(sql, (stop_id,)) as cursor:
        row = await cursor.fetchone()
        if row and row["stop_lat"] is not None:
            return {
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
                "parent_station": row["parent_station"],
            }
        return None


async def _get_outbound_segments(
    db,
    origin_stop_id: str,
    departure_time: str,
    end_time: str,
    active_services: list[str],
) -> list[OutboundSegment]:
    """Find all trips from origin with downstream stops for potential transfers.

    Returns all outbound segments that could be first legs of transfer itineraries.
    """
    placeholders = ",".join(["?" for _ in active_services])
    params: list = [origin_stop_id]
    params.extend(active_services)
    params.extend([departure_time, end_time])

    sql = f"""
        WITH origin_trips AS (
            SELECT st.trip_id, st.departure_time AS origin_dep, st.stop_sequence AS origin_seq,
                   t.route_id, t.trip_headsign
            FROM stop_times st
            JOIN trips t ON st.trip_id = t.trip_id
            WHERE st.stop_id = ?
              AND t.service_id IN ({placeholders})
              AND st.departure_time >= ?
              AND st.departure_time <= ?
        )
        SELECT ot.trip_id, ot.origin_dep, ot.origin_seq, ot.route_id, ot.trip_headsign,
               st.stop_id AS xfer_stop, st.arrival_time AS xfer_arrival, st.stop_sequence AS xfer_seq,
               r.route_short_name, r.route_type
        FROM origin_trips ot
        JOIN stop_times st ON ot.trip_id = st.trip_id AND st.stop_sequence > ot.origin_seq
        JOIN routes r ON ot.route_id = r.route_id
        ORDER BY ot.origin_dep, st.stop_sequence
    """

    segments = []
    async with db.execute(sql, params) as cursor:
        async for row in cursor:
            segments.append(
                OutboundSegment(
                    trip_id=row["trip_id"],
                    route_id=row["route_id"],
                    route_short_name=row["route_short_name"],
                    route_type=int(row["route_type"]),
                    trip_headsign=row["trip_headsign"],
                    origin_departure=row["origin_dep"],
                    origin_seq=row["origin_seq"],
                    xfer_stop_id=row["xfer_stop"],
                    xfer_arrival=row["xfer_arrival"],
                    xfer_seq=row["xfer_seq"],
                )
            )
    return segments


async def _get_inbound_segments(
    db,
    destination_stop_id: str,
    active_services: list[str],
    latest_transfer_departure: str,
) -> list[InboundSegment]:
    """Find all trips to destination with upstream stops for potential transfers.

    Returns all inbound segments that could be second legs of transfer itineraries.
    """
    placeholders = ",".join(["?" for _ in active_services])
    params: list = [destination_stop_id]
    params.extend(active_services)
    params.append(latest_transfer_departure)

    sql = f"""
        WITH dest_trips AS (
            SELECT st.trip_id, st.arrival_time AS dest_arr, st.stop_sequence AS dest_seq,
                   t.route_id, t.trip_headsign
            FROM stop_times st
            JOIN trips t ON st.trip_id = t.trip_id
            WHERE st.stop_id = ?
              AND t.service_id IN ({placeholders})
        )
        SELECT dt.trip_id, dt.dest_arr, dt.dest_seq, dt.route_id, dt.trip_headsign,
               st.stop_id AS xfer_stop, st.departure_time AS xfer_dep, st.stop_sequence AS xfer_seq,
               r.route_short_name, r.route_type
        FROM dest_trips dt
        JOIN stop_times st ON dt.trip_id = st.trip_id AND st.stop_sequence < dt.dest_seq
        JOIN routes r ON dt.route_id = r.route_id
        WHERE st.departure_time <= ?
        ORDER BY dt.dest_arr, st.stop_sequence DESC
    """

    segments = []
    async with db.execute(sql, params) as cursor:
        async for row in cursor:
            segments.append(
                InboundSegment(
                    trip_id=row["trip_id"],
                    route_id=row["route_id"],
                    route_short_name=row["route_short_name"],
                    route_type=int(row["route_type"]),
                    trip_headsign=row["trip_headsign"],
                    xfer_stop_id=row["xfer_stop"],
                    xfer_departure=row["xfer_dep"],
                    xfer_seq=row["xfer_seq"],
                    dest_arrival=row["dest_arr"],
                    dest_seq=row["dest_seq"],
                )
            )
    return segments


async def _find_transfer_points(
    db,
    outbound_segments: list[OutboundSegment],
    inbound_segments: list[InboundSegment],
) -> list[TransferPoint]:
    """Find valid transfer points between outbound and inbound segments.

    Strategies (in order of preference):
    1. Same-stop: Stops appearing in both outbound and inbound results
    2. Same-station: Metro platforms sharing parent_station (add 2-min buffer)
    3. Proximity: Nearby stops within MAX_WALKING_DISTANCE_METERS
    """
    transfer_points: list[TransferPoint] = []

    # Build lookup structures
    # Group inbound segments by transfer stop for fast lookup
    inbound_by_stop: dict[str, list[InboundSegment]] = {}
    for seg in inbound_segments:
        if seg.xfer_stop_id not in inbound_by_stop:
            inbound_by_stop[seg.xfer_stop_id] = []
        inbound_by_stop[seg.xfer_stop_id].append(seg)

    # Cache for stop locations (for proximity matching)
    stop_locations: dict[str, dict | None] = {}

    async def get_location(stop_id: str) -> dict | None:
        if stop_id not in stop_locations:
            stop_locations[stop_id] = await _get_stop_location(db, stop_id)
        return stop_locations[stop_id]

    # Get all unique outbound transfer stops
    outbound_stops = {seg.xfer_stop_id for seg in outbound_segments}
    inbound_stops = set(inbound_by_stop.keys())

    # Strategy 1: Same-stop transfers
    common_stops = outbound_stops & inbound_stops

    for out_seg in outbound_segments:
        if out_seg.xfer_stop_id not in common_stops:
            continue

        arrival_seconds = gtfs_time_to_seconds(out_seg.xfer_arrival)

        for in_seg in inbound_by_stop.get(out_seg.xfer_stop_id, []):
            # Skip transfers to same route (not a real transfer)
            if out_seg.route_id == in_seg.route_id:
                continue

            departure_seconds = gtfs_time_to_seconds(in_seg.xfer_departure)
            wait_minutes = (departure_seconds - arrival_seconds) // 60

            # Check timing constraints
            if MIN_TRANSFER_TIME_MINUTES <= wait_minutes <= MAX_TRANSFER_TIME_MINUTES:
                transfer_points.append(
                    TransferPoint(
                        outbound=out_seg,
                        inbound=in_seg,
                        wait_minutes=wait_minutes,
                        walk_meters=0.0,
                        walk_minutes=0,
                    )
                )

    # Strategy 2: Same-station (parent_station) transfers for metro
    # Collect parent stations for outbound stops
    outbound_parent_stations: dict[str, list[str]] = {}  # parent -> list of stop_ids
    for stop_id in outbound_stops:
        loc = await get_location(stop_id)
        if loc and loc["parent_station"]:
            parent = loc["parent_station"]
            if parent not in outbound_parent_stations:
                outbound_parent_stations[parent] = []
            outbound_parent_stations[parent].append(stop_id)

    # Find inbound stops sharing parent stations
    # Track which stops actually matched to exclude from proximity checks
    parent_station_matched_outbound: set[str] = set()
    parent_station_matched_inbound: set[str] = set()

    for in_stop_id in inbound_stops:
        if in_stop_id in common_stops:
            continue  # Already handled in same-stop

        loc = await get_location(in_stop_id)
        if not loc or not loc["parent_station"]:
            continue

        parent = loc["parent_station"]
        if parent not in outbound_parent_stations:
            continue

        # This inbound stop shares a parent station with some outbound stops
        for out_stop_id in outbound_parent_stations[parent]:
            for out_seg in outbound_segments:
                if out_seg.xfer_stop_id != out_stop_id:
                    continue

                arrival_seconds = gtfs_time_to_seconds(out_seg.xfer_arrival)
                # Add 2-minute buffer for walking between platforms
                effective_arrival_seconds = arrival_seconds + 2 * 60

                for in_seg in inbound_by_stop.get(in_stop_id, []):
                    if out_seg.route_id == in_seg.route_id:
                        continue

                    departure_seconds = gtfs_time_to_seconds(in_seg.xfer_departure)
                    effective_wait = (departure_seconds - effective_arrival_seconds) // 60

                    if MIN_TRANSFER_TIME_MINUTES <= effective_wait <= MAX_TRANSFER_TIME_MINUTES:
                        transfer_points.append(
                            TransferPoint(
                                outbound=out_seg,
                                inbound=in_seg,
                                wait_minutes=effective_wait,
                                walk_meters=0.0,  # Same station, negligible distance
                                walk_minutes=2,
                            )
                        )
                        # Track that these stops matched via parent-station
                        parent_station_matched_outbound.add(out_stop_id)
                        parent_station_matched_inbound.add(in_stop_id)

    # Strategy 3: Proximity transfers (walking between nearby stops)
    # Only check stops not already matched via same-stop or parent-station
    unmatched_outbound = outbound_stops - common_stops - parent_station_matched_outbound
    unmatched_inbound = inbound_stops - common_stops - parent_station_matched_inbound

    # Check remaining pairs for proximity
    for out_stop_id in unmatched_outbound:
        out_loc = await get_location(out_stop_id)
        if not out_loc:
            continue

        for in_stop_id in unmatched_inbound:
            in_loc = await get_location(in_stop_id)
            if not in_loc:
                continue

            distance = haversine_distance(
                out_loc["lat"], out_loc["lon"], in_loc["lat"], in_loc["lon"]
            )

            if distance > MAX_WALKING_DISTANCE_METERS:
                continue

            # Walking time: ~80m/min + 1 min buffer
            walk_minutes = int(distance / 80) + 1

            for out_seg in outbound_segments:
                if out_seg.xfer_stop_id != out_stop_id:
                    continue

                arrival_seconds = gtfs_time_to_seconds(out_seg.xfer_arrival)
                effective_arrival_seconds = arrival_seconds + walk_minutes * 60

                for in_seg in inbound_by_stop.get(in_stop_id, []):
                    if out_seg.route_id == in_seg.route_id:
                        continue

                    departure_seconds = gtfs_time_to_seconds(in_seg.xfer_departure)
                    effective_wait = (departure_seconds - effective_arrival_seconds) // 60

                    if MIN_TRANSFER_TIME_MINUTES <= effective_wait <= MAX_TRANSFER_TIME_MINUTES:
                        transfer_points.append(
                            TransferPoint(
                                outbound=out_seg,
                                inbound=in_seg,
                                wait_minutes=effective_wait,
                                walk_meters=distance,
                                walk_minutes=walk_minutes,
                            )
                        )

    return transfer_points


async def _build_transfer_itinerary(
    db,
    transfer: TransferPoint,
    origin_stop_id: str,
    destination_stop_id: str,
) -> Itinerary:
    """Build a 2-leg itinerary from a transfer point."""
    # Get stop info for all stops
    origin_info = await _get_stop_info(db, origin_stop_id)
    xfer_out_info = await _get_stop_info(db, transfer.outbound.xfer_stop_id)
    xfer_in_info = await _get_stop_info(db, transfer.inbound.xfer_stop_id)
    dest_info = await _get_stop_info(db, destination_stop_id)

    # Build first leg (origin -> transfer)
    leg1_duration = (
        gtfs_time_to_seconds(transfer.outbound.xfer_arrival)
        - gtfs_time_to_seconds(transfer.outbound.origin_departure)
    ) // 60

    leg1 = TripLeg(
        route_id=transfer.outbound.route_id,
        route_short_name=transfer.outbound.route_short_name,
        route_type=transfer.outbound.route_type,
        trip_id=transfer.outbound.trip_id,
        trip_headsign=transfer.outbound.trip_headsign,
        from_stop_id=origin_stop_id,
        from_stop_name=origin_info["name"],
        from_stop_code=origin_info["code"],
        to_stop_id=transfer.outbound.xfer_stop_id,
        to_stop_name=xfer_out_info["name"],
        to_stop_code=xfer_out_info["code"],
        departure_time=transfer.outbound.origin_departure,
        departure_time_formatted=format_gtfs_time(transfer.outbound.origin_departure),
        arrival_time=transfer.outbound.xfer_arrival,
        arrival_time_formatted=format_gtfs_time(transfer.outbound.xfer_arrival),
        duration_minutes=leg1_duration,
        num_stops=transfer.outbound.xfer_seq - transfer.outbound.origin_seq + 1,
    )

    # Build second leg (transfer -> destination)
    leg2_duration = (
        gtfs_time_to_seconds(transfer.inbound.dest_arrival)
        - gtfs_time_to_seconds(transfer.inbound.xfer_departure)
    ) // 60

    leg2 = TripLeg(
        route_id=transfer.inbound.route_id,
        route_short_name=transfer.inbound.route_short_name,
        route_type=transfer.inbound.route_type,
        trip_id=transfer.inbound.trip_id,
        trip_headsign=transfer.inbound.trip_headsign,
        from_stop_id=transfer.inbound.xfer_stop_id,
        from_stop_name=xfer_in_info["name"],
        from_stop_code=xfer_in_info["code"],
        to_stop_id=destination_stop_id,
        to_stop_name=dest_info["name"],
        to_stop_code=dest_info["code"],
        departure_time=transfer.inbound.xfer_departure,
        departure_time_formatted=format_gtfs_time(transfer.inbound.xfer_departure),
        arrival_time=transfer.inbound.dest_arrival,
        arrival_time_formatted=format_gtfs_time(transfer.inbound.dest_arrival),
        duration_minutes=leg2_duration,
        num_stops=transfer.inbound.dest_seq - transfer.inbound.xfer_seq + 1,
    )

    # Calculate total duration (includes wait and walk time)
    total_duration = (
        gtfs_time_to_seconds(transfer.inbound.dest_arrival)
        - gtfs_time_to_seconds(transfer.outbound.origin_departure)
    ) // 60

    return Itinerary(
        legs=[leg1, leg2],
        departure_time=transfer.outbound.origin_departure,
        departure_time_formatted=format_gtfs_time(transfer.outbound.origin_departure),
        arrival_time=transfer.inbound.dest_arrival,
        arrival_time_formatted=format_gtfs_time(transfer.inbound.dest_arrival),
        total_duration_minutes=total_duration,
        num_transfers=1,
        transfer_wait_minutes=transfer.wait_minutes,
        transfer_walk_meters=transfer.walk_meters if transfer.walk_meters > 0 else None,
    )


async def _find_transfer_itineraries(
    origin_stop_id: str,
    destination_stop_id: str,
    departure_time: str,
    service_date,
    limit: int,
    db_path: Path | None,
) -> list[Itinerary]:
    """Find itineraries with one transfer between origin and destination."""
    departure_seconds = gtfs_time_to_seconds(departure_time)
    end_seconds = departure_seconds + (TIME_WINDOW_HOURS * 3600)
    end_time = f"{end_seconds // 3600:02d}:{(end_seconds % 3600) // 60:02d}:00"

    async with get_db(db_path) as db:
        # Get active services
        active_services = await get_active_service_ids(db, service_date)
        if not active_services:
            return []

        # Step 1: Get outbound segments from origin
        outbound_segments = await _get_outbound_segments(
            db, origin_stop_id, departure_time, end_time, active_services
        )
        if not outbound_segments:
            return []

        # Step 2: Calculate latest possible transfer departure
        # Based on max outbound arrival + MAX_TRANSFER_TIME
        max_outbound_arrival = max(
            gtfs_time_to_seconds(seg.xfer_arrival) for seg in outbound_segments
        )
        latest_transfer_seconds = max_outbound_arrival + (MAX_TRANSFER_TIME_MINUTES * 60)
        latest_transfer_time = (
            f"{latest_transfer_seconds // 3600:02d}:"
            f"{(latest_transfer_seconds % 3600) // 60:02d}:00"
        )

        # Step 3: Get inbound segments to destination
        inbound_segments = await _get_inbound_segments(
            db, destination_stop_id, active_services, latest_transfer_time
        )
        if not inbound_segments:
            return []

        # Step 4: Find valid transfer points
        transfer_points = await _find_transfer_points(db, outbound_segments, inbound_segments)
        if not transfer_points:
            return []

        # Step 5: Build itineraries from transfer points
        # Sort by total travel time and pick best ones
        transfer_points.sort(
            key=lambda t: (
                gtfs_time_to_seconds(t.inbound.dest_arrival)
                - gtfs_time_to_seconds(t.outbound.origin_departure)
            )
        )

        # Deduplicate by (departure_time, route1, route2) to show variety
        itineraries: list[Itinerary] = []
        seen: set[tuple] = set()

        for transfer in transfer_points:
            key = (
                transfer.outbound.origin_departure,
                transfer.outbound.route_id,
                transfer.inbound.route_id,
            )
            if key in seen:
                continue
            seen.add(key)

            itinerary = await _build_transfer_itinerary(
                db, transfer, origin_stop_id, destination_stop_id
            )
            itineraries.append(itinerary)

            if len(itineraries) >= limit:
                break

    return itineraries


async def _find_direct_itineraries(
    origin_stop_id: str,
    destination_stop_id: str,
    departure_time: str,
    service_date,
    limit: int,
    db_path: Path | None,
) -> list[Itinerary]:
    """Find trips that go directly from origin to destination."""
    departure_seconds = gtfs_time_to_seconds(departure_time)
    end_seconds = departure_seconds + (TIME_WINDOW_HOURS * 3600)
    end_time = f"{end_seconds // 3600:02d}:{(end_seconds % 3600) // 60:02d}:00"

    async with get_db(db_path) as db:
        # Get active services
        active_services = await get_active_service_ids(db, service_date)
        if not active_services:
            return []

        # Get stop info for response
        origin_info = await _get_stop_info(db, origin_stop_id)
        dest_info = await _get_stop_info(db, destination_stop_id)

        # Find trips that visit both origin and destination in order
        placeholders = ",".join(["?" for _ in active_services])
        params: list = [origin_stop_id, destination_stop_id]
        params.extend(active_services)
        params.extend([departure_time, end_time])

        sql = f"""
            SELECT
                o.trip_id,
                o.departure_time as origin_departure,
                o.stop_sequence as origin_seq,
                d.arrival_time as dest_arrival,
                d.stop_sequence as dest_seq,
                t.route_id,
                t.trip_headsign,
                r.route_short_name,
                r.route_type
            FROM stop_times o
            JOIN stop_times d ON o.trip_id = d.trip_id
            JOIN trips t ON o.trip_id = t.trip_id
            JOIN routes r ON t.route_id = r.route_id
            WHERE o.stop_id = ?
              AND d.stop_id = ?
              AND t.service_id IN ({placeholders})
              AND o.departure_time >= ?
              AND o.departure_time <= ?
              AND d.stop_sequence > o.stop_sequence
            ORDER BY o.departure_time
            LIMIT ?
        """
        params.append(limit * 2)  # Fetch extra for filtering

        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    # Build itineraries
    itineraries = []
    seen_routes: set[tuple] = set()  # Dedupe by route to show variety

    for row in rows:
        route_key = (row["route_id"], row["origin_departure"])
        if route_key in seen_routes:
            continue
        seen_routes.add(route_key)

        origin_dep = row["origin_departure"]
        dest_arr = row["dest_arrival"]
        duration = (gtfs_time_to_seconds(dest_arr) - gtfs_time_to_seconds(origin_dep)) // 60
        num_stops = row["dest_seq"] - row["origin_seq"] + 1

        leg = TripLeg(
            route_id=row["route_id"],
            route_short_name=row["route_short_name"],
            route_type=int(row["route_type"]),
            trip_id=row["trip_id"],
            trip_headsign=row["trip_headsign"],
            from_stop_id=origin_stop_id,
            from_stop_name=origin_info["name"],
            from_stop_code=origin_info["code"],
            to_stop_id=destination_stop_id,
            to_stop_name=dest_info["name"],
            to_stop_code=dest_info["code"],
            departure_time=origin_dep,
            departure_time_formatted=format_gtfs_time(origin_dep),
            arrival_time=dest_arr,
            arrival_time_formatted=format_gtfs_time(dest_arr),
            duration_minutes=duration,
            num_stops=num_stops,
        )

        itinerary = Itinerary(
            legs=[leg],
            departure_time=origin_dep,
            departure_time_formatted=format_gtfs_time(origin_dep),
            arrival_time=dest_arr,
            arrival_time_formatted=format_gtfs_time(dest_arr),
            total_duration_minutes=duration,
            num_transfers=0,
        )

        itineraries.append(itinerary)
        if len(itineraries) >= limit:
            break

    return itineraries


async def plan_trip(
    origin: str,
    destination: str,
    departure_time: str | None = None,
    limit: int = 3,
    db_path: Path | None = None,
) -> PlanTripResponse:
    """Find itineraries from origin to destination (direct and 1-transfer).

    Args:
        origin: Origin stop query (stop code, ID, or fuzzy name)
        destination: Destination stop query
        departure_time: Departure time in HH:MM:SS format (default: now)
        limit: Maximum itineraries to return (1-5)
        db_path: Optional database path override

    Returns:
        PlanTripResponse with itineraries sorted by total duration
    """
    now = datetime.now()
    service_date = now.date()

    if departure_time is None:
        departure_time = time_to_gtfs_format(now)

    # Resolve origin and destination stops
    origin_res = await _resolve_stop_for_planning(origin, db_path)
    dest_res = await _resolve_stop_for_planning(destination, db_path)

    if not origin_res.resolved or not dest_res.resolved:
        return PlanTripResponse(
            origin_resolution=origin_res,
            destination_resolution=dest_res,
            itineraries=[],
            service_date=service_date.isoformat(),
            departure_date=now.date().isoformat(),
            query_time=departure_time,
            count=0,
            success=False,
            error="Could not resolve origin or destination stop",
        )

    # Find direct itineraries
    direct_itineraries = await _find_direct_itineraries(
        origin_stop_id=origin_res.resolved_stop_id,
        destination_stop_id=dest_res.resolved_stop_id,
        departure_time=departure_time,
        service_date=service_date,
        limit=limit,
        db_path=db_path,
    )

    # Find transfer itineraries
    transfer_itineraries = await _find_transfer_itineraries(
        origin_stop_id=origin_res.resolved_stop_id,
        destination_stop_id=dest_res.resolved_stop_id,
        departure_time=departure_time,
        service_date=service_date,
        limit=limit,
        db_path=db_path,
    )

    # Combine and sort by total duration
    all_itineraries = direct_itineraries + transfer_itineraries
    all_itineraries.sort(key=lambda it: it.total_duration_minutes)

    # Limit results
    itineraries = all_itineraries[:limit]

    return PlanTripResponse(
        origin_resolution=origin_res,
        destination_resolution=dest_res,
        itineraries=itineraries,
        service_date=service_date.isoformat(),
        departure_date=now.date().isoformat(),
        query_time=departure_time,
        count=len(itineraries),
        success=len(itineraries) > 0,
        error=None if itineraries else "No routes found",
    )
