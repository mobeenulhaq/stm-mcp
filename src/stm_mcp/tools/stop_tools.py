"""MCP tools for searching stops."""

from stm_mcp.models.responses import SearchStopsResponse
from stm_mcp.server import mcp
from stm_mcp.services.stop_service import search_stops as _search_stops


@mcp.tool()
async def search_stops(
    query: str | None = None,
    stop_code: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_meters: int = 500,
    limit: int = 20,
) -> SearchStopsResponse:
    """Search for STM transit stops.

    Supports three search modes:
    - Text search: Find stops by name (e.g., "Berri", "McGill")
    - Stop code: Find by exact stop code (e.g., "51001")
    - Geo search: Find stops near coordinates within a radius

    Examples:
        search_stops(query="Berri")  # Find stops with "Berri" in name
        search_stops(stop_code="51001")  # Find stop by code
        search_stops(lat=45.515, lon=-73.561, radius_meters=500)  # Nearby stops

    Args:
        query: Text to search for in stop names (case-insensitive partial match).
        stop_code: Exact stop code to match.
        lat: Latitude for geographic search (requires lon).
        lon: Longitude for geographic search (requires lat).
        radius_meters: Search radius for geo search (default 500m, max recommended 2000m).
        limit: Maximum number of results to return (default 20, max 100).

    Returns:
        SearchStopsResponse with list of matching stops and count.
        For geo search, stops are sorted by distance and include distance_meters.
    """
    # Validate limit
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    # Validate radius
    if radius_meters < 1:
        radius_meters = 1
    elif radius_meters > 10000:
        radius_meters = 10000

    return await _search_stops(
        query=query,
        stop_code=stop_code,
        lat=lat,
        lon=lon,
        radius_meters=radius_meters,
        limit=limit,
    )
