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

TIME_WINDOW_HOURS = 2


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
    """Find direct itineraries from origin to destination.

    Args:
        origin: Origin stop query (stop code, ID, or fuzzy name)
        destination: Destination stop query
        departure_time: Departure time in HH:MM:SS format (default: now)
        limit: Maximum itineraries to return (1-5)
        db_path: Optional database path override

    Returns:
        PlanTripResponse with itineraries sorted by departure time
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
    itineraries = await _find_direct_itineraries(
        origin_stop_id=origin_res.resolved_stop_id,
        destination_stop_id=dest_res.resolved_stop_id,
        departure_time=departure_time,
        service_date=service_date,
        limit=limit,
        db_path=db_path,
    )

    return PlanTripResponse(
        origin_resolution=origin_res,
        destination_resolution=dest_res,
        itineraries=itineraries,
        service_date=service_date.isoformat(),
        departure_date=now.date().isoformat(),
        query_time=departure_time,
        count=len(itineraries),
        success=len(itineraries) > 0,
        error=None if itineraries else "No direct routes found",
    )
