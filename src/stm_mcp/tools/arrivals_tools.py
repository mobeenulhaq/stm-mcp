from stm_mcp.models.responses import GetNextArrivalsResponse
from stm_mcp.app import mcp
from stm_mcp.services.arrivals_service import (
    get_next_arrivals as _get_next_arrivals,
)


@mcp.tool()
async def get_next_arrivals(
    stop_id: str,
    route_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
) -> GetNextArrivalsResponse:
    """Get upcoming arrivals at an STM transit stop with real-time predictions.

    Returns arrivals combining static GTFS schedule with real-time predictions
    when available. Real-time data includes delay predictions and vehicle
    occupancy levels.

    For buses: Real-time predictions and occupancy are overlaid on the schedule.
    For metro: Only scheduled times are shown (metro uses a separate status API).

    Args:
        stop_id: The stop ID to get arrivals for (e.g., "51001").
        route_id: Optional route ID to filter by (e.g., "24").
        start_time: Start of time window in HH:MM:SS format (default: now).
        end_time: End of time window in HH:MM:SS format (default: 28:00:00).
        limit: Maximum number of arrivals to return (1-100, default: 20).

    Returns:
        GetNextArrivalsResponse with arrivals and RT status.
    """
    # Validate and clamp limit to 1-100
    limit = max(1, min(100, limit))

    return await _get_next_arrivals(
        stop_id=stop_id,
        route_id=route_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
