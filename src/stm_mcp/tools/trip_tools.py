from stm_mcp.models.responses import PlanTripResponse
from stm_mcp.server import mcp
from stm_mcp.services.trip_planner import plan_trip as _plan_trip


@mcp.tool()
async def plan_trip(
    origin: str,
    destination: str,
    departure_time: str | None = None,
    limit: int = 3,
) -> PlanTripResponse:
    """Plan a transit trip between two STM stops.

    Finds itineraries using bus and metro routes. Currently supports direct
    routes only (no transfers).

    Args:
        origin: Origin stop - stop code, ID, or fuzzy name
                (e.g., "51001", "Berri-UQAM", "sherbrooke at saint-denis")
        destination: Destination stop - same format as origin
        departure_time: Departure time in HH:MM:SS format (default: now)
        limit: Maximum itineraries to return (1-5, default: 3)

    Returns:
        PlanTripResponse with itineraries sorted by departure time.
    """
    # Clamp limit
    if limit < 1:
        limit = 1
    elif limit > 5:
        limit = 5

    return await _plan_trip(
        origin=origin,
        destination=destination,
        departure_time=departure_time,
        limit=limit,
    )
