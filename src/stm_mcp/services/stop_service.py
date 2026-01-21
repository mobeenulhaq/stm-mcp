"""Stop search service for querying GTFS stops."""

import math
from pathlib import Path

import aiosqlite

from stm_mcp.data.database import get_db
from stm_mcp.models.responses import SearchStopsResponse, StopResult

# Earth's radius in meters for haversine calculation
EARTH_RADIUS_METERS = 6_371_000


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in meters.

    Args:
        lat1, lon1: First point coordinates in degrees.
        lat2, lon2: Second point coordinates in degrees.

    Returns:
        Distance in meters.
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_METERS * c


def _row_to_stop_result(row: aiosqlite.Row, distance: float | None = None) -> StopResult:
    """Convert a database row to a StopResult."""
    return StopResult(
        stop_id=row["stop_id"],
        stop_code=row["stop_code"],
        stop_name=row["stop_name"],
        stop_lat=float(row["stop_lat"]) if row["stop_lat"] is not None else None,
        stop_lon=float(row["stop_lon"]) if row["stop_lon"] is not None else None,
        location_type=int(row["location_type"]) if row["location_type"] is not None else None,
        parent_station=row["parent_station"],
        wheelchair_boarding=(
            int(row["wheelchair_boarding"]) if row["wheelchair_boarding"] is not None else None
        ),
        distance_meters=distance,
    )


async def search_stops_by_text(
    db: aiosqlite.Connection,
    query: str,
    limit: int = 20,
) -> SearchStopsResponse:
    """Search stops by name using LIKE matching.

    Args:
        db: Database connection.
        query: Text to search for in stop names.
        limit: Maximum number of results.

    Returns:
        SearchStopsResponse with matching stops.
    """
    # Use % wildcards for partial matching
    search_pattern = f"%{query}%"

    sql = """
        SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon,
               location_type, parent_station, wheelchair_boarding
        FROM stops
        WHERE stop_name LIKE ?
        ORDER BY stop_name
        LIMIT ?
    """

    async with db.execute(sql, (search_pattern, limit)) as cursor:
        rows = await cursor.fetchall()

    stops = [_row_to_stop_result(row) for row in rows]
    return SearchStopsResponse(stops=stops, count=len(stops))


async def search_stops_by_code(
    db: aiosqlite.Connection,
    stop_code: str,
) -> SearchStopsResponse:
    """Search stops by exact stop code match.

    Args:
        db: Database connection.
        stop_code: Exact stop code to match.

    Returns:
        SearchStopsResponse with matching stops.
    """
    sql = """
        SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon,
               location_type, parent_station, wheelchair_boarding
        FROM stops
        WHERE stop_code = ?
    """

    async with db.execute(sql, (stop_code,)) as cursor:
        rows = await cursor.fetchall()

    stops = [_row_to_stop_result(row) for row in rows]
    return SearchStopsResponse(stops=stops, count=len(stops))


async def search_stops_by_location(
    db: aiosqlite.Connection,
    lat: float,
    lon: float,
    radius_meters: int = 500,
    limit: int = 20,
) -> SearchStopsResponse:
    """Search stops near a geographic location.

    Uses a bounding box filter for efficient SQL query, then calculates
    exact haversine distance for final filtering and sorting.

    Args:
        db: Database connection.
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        radius_meters: Search radius in meters.
        limit: Maximum number of results.

    Returns:
        SearchStopsResponse with stops sorted by distance.
    """
    # Calculate approximate bounding box
    # 1 degree of latitude ~= 111,000 meters
    # 1 degree of longitude varies with latitude
    lat_delta = radius_meters / 111_000
    lon_delta = radius_meters / (111_000 * math.cos(math.radians(lat)))

    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lon = lon - lon_delta
    max_lon = lon + lon_delta

    # Query with bounding box filter
    sql = """
        SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon,
               location_type, parent_station, wheelchair_boarding
        FROM stops
        WHERE stop_lat BETWEEN ? AND ?
          AND stop_lon BETWEEN ? AND ?
          AND stop_lat IS NOT NULL
          AND stop_lon IS NOT NULL
    """

    async with db.execute(sql, (min_lat, max_lat, min_lon, max_lon)) as cursor:
        rows = await cursor.fetchall()

    # Calculate exact distances and filter
    stops_with_distance: list[tuple[aiosqlite.Row, float]] = []
    for row in rows:
        distance = haversine_distance(lat, lon, row["stop_lat"], row["stop_lon"])
        if distance <= radius_meters:
            stops_with_distance.append((row, distance))

    # Sort by distance and limit
    stops_with_distance.sort(key=lambda x: x[1])
    stops_with_distance = stops_with_distance[:limit]

    stops = [_row_to_stop_result(row, round(distance, 1)) for row, distance in stops_with_distance]
    return SearchStopsResponse(stops=stops, count=len(stops))


async def search_stops(
    query: str | None = None,
    stop_code: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_meters: int = 500,
    limit: int = 20,
    db_path: Path | None = None,
) -> SearchStopsResponse:
    """Search for stops using various criteria.

    Supports three search modes:
    1. Text search: Search by stop name (query parameter)
    2. Stop code: Exact match on stop_code field
    3. Geo search: Find stops near a location (lat/lon)

    If multiple criteria are provided, geo search takes priority,
    then stop_code, then text search.

    Args:
        query: Text to search for in stop names.
        stop_code: Exact stop code to match.
        lat: Latitude for geo search.
        lon: Longitude for geo search.
        radius_meters: Search radius for geo search (default 500m).
        limit: Maximum number of results (default 20).
        db_path: Optional database path override.

    Returns:
        SearchStopsResponse with matching stops.

    Raises:
        ValueError: If no search criteria provided.
    """
    async with get_db(db_path) as db:
        # Geo search takes priority
        if lat is not None and lon is not None:
            return await search_stops_by_location(db, lat, lon, radius_meters, limit)

        # Then stop code
        if stop_code is not None:
            return await search_stops_by_code(db, stop_code)

        # Then text search
        if query is not None:
            return await search_stops_by_text(db, query, limit)

        raise ValueError("At least one search parameter required: query, stop_code, or lat/lon")


async def get_stop_by_id(
    stop_id: str,
    db_path: Path | None = None,
) -> StopResult | None:
    """Get a single stop by its ID.

    Args:
        stop_id: The stop ID to look up.
        db_path: Optional database path override.

    Returns:
        StopResult if found, None otherwise.
    """
    async with get_db(db_path) as db:
        sql = """
            SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon,
                   location_type, parent_station, wheelchair_boarding
            FROM stops
            WHERE stop_id = ?
        """
        async with db.execute(sql, (stop_id,)) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return _row_to_stop_result(row)
