"""MCP tools for fuzzy resolution of stops, routes, and directions."""

from stm_mcp.matching.direction_matcher import resolve_direction as _resolve_direction
from stm_mcp.matching.models import (
    DirectionResolutionResponse,
    RouteResolutionResponse,
    StopResolutionResponse,
)
from stm_mcp.matching.route_matcher import resolve_route as _resolve_route
from stm_mcp.matching.stop_matcher import resolve_stop as _resolve_stop
from stm_mcp.server import mcp


@mcp.tool()
async def resolve_stop(
    query: str,
    limit: int = 5,
    min_score: float = 60.0,
) -> StopResolutionResponse:
    """Resolve a natural language query to matching STM stops using fuzzy matching.

    Handles typos, abbreviations, bilingual names, and cross-street patterns.

    Resolution strategy (priority order):
    1. Exact stop_code match (e.g., "51001") -> confidence=EXACT
    2. Exact stop_id match -> confidence=EXACT
    3. Cross-street pattern (e.g., "Sherbrooke at Berri") -> confidence=HIGH
    4. Fuzzy name matching -> confidence based on score

    Examples:
        resolve_stop("51001")  # Exact code -> resolved=True, confidence=EXACT
        resolve_stop("Bembi")  # Typo for "Berri" -> resolved depends on score
        resolve_stop("St-Michel")  # Expands to "Saint-Michel"
        resolve_stop("Sherbrooke at Berri")  # Cross-street pattern

    Args:
        query: Search query - stop code, name, or cross-street pattern.
        limit: Maximum number of matches to return (default 5, max 20).
        min_score: Minimum match score 0-100 (default 60).

    Returns:
        StopResolutionResponse with:
        - matches: List of matched stops with scores and confidence
        - best_match: Top match (always set when matches exist)
        - resolved: True if best_match has EXACT or HIGH confidence (safe to auto-use)
    """
    if limit < 1:
        limit = 1
    elif limit > 20:
        limit = 20

    if min_score < 0:
        min_score = 0
    elif min_score > 100:
        min_score = 100

    return await _resolve_stop(query=query, limit=limit, min_score=min_score)


@mcp.tool()
async def resolve_route(
    query: str,
    limit: int = 5,
    min_score: float = 60.0,
) -> RouteResolutionResponse:
    """Resolve a natural language query to matching STM routes using fuzzy matching.

    Handles route numbers, metro line aliases, and fuzzy name matching.

    Resolution strategy (priority order):
    1. Exact route number (e.g., "24", "bus 747") -> confidence=EXACT
    2. Metro line alias (e.g., "green line", "ligne verte") -> confidence=EXACT
    3. Fuzzy name matching on route_long_name -> confidence based on score

    Examples:
        resolve_route("24")  # Bus route 24 -> resolved=True, confidence=EXACT
        resolve_route("green line")  # Green metro line -> resolved=True, confidence=EXACT
        resolve_route("ligne verte")  # Same as above (bilingual)
        resolve_route("Papineau")  # Fuzzy match on route names

    Args:
        query: Search query - route number, metro alias, or route name.
        limit: Maximum number of matches to return (default 5, max 20).
        min_score: Minimum match score 0-100 (default 60).

    Returns:
        RouteResolutionResponse with:
        - matches: List of matched routes with scores and confidence
        - best_match: Top match (always set when matches exist)
        - resolved: True if best_match has EXACT or HIGH confidence (safe to auto-use)
    """
    if limit < 1:
        limit = 1
    elif limit > 20:
        limit = 20

    if min_score < 0:
        min_score = 0
    elif min_score > 100:
        min_score = 100

    return await _resolve_route(query=query, limit=limit, min_score=min_score)


@mcp.tool()
async def resolve_direction(
    query: str,
    route_id: str,
    direction_id: int | None = None,
    min_score: float = 60.0,
) -> DirectionResolutionResponse:
    """Resolve a direction/headsign query for a specific STM route.

    Matches user input like "to Angrignon" or "vers Montmorency" to actual
    trip headsigns for the given route.

    Handles direction prefixes ("to ", "vers ", "direction ") and fuzzy matching.

    Examples:
        resolve_direction("Angrignon", route_id="1")  # Green line direction
        resolve_direction("vers Montmorency", route_id="2")  # Orange line
        resolve_direction("downtown", route_id="24", direction_id=0)  # Filter by direction

    Args:
        query: Direction query - headsign or destination name.
        route_id: Route ID to find directions for.
        direction_id: Optional direction filter (0 or 1) to narrow results.
        min_score: Minimum match score 0-100 (default 60).

    Returns:
        DirectionResolutionResponse with:
        - matches: List of matched directions with scores and confidence
        - best_match: Top match (always set when matches exist)
        - resolved: True if best_match has EXACT or HIGH confidence (safe to auto-use)
    """
    if min_score < 0:
        min_score = 0
    elif min_score > 100:
        min_score = 100

    return await _resolve_direction(
        query=query,
        route_id=route_id,
        direction_id=direction_id,
        min_score=min_score,
    )
