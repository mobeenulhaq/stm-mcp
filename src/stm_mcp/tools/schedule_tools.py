from stm_mcp.models.responses import GetScheduledArrivalsResponse
from stm_mcp.server import mcp
from stm_mcp.services.schedule_service import (
    get_scheduled_arrivals as _get_scheduled_arrivals,
)


@mcp.tool()
async def get_scheduled_arrivals(
    stop_id: str,
    route_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
) -> GetScheduledArrivalsResponse:
    """Get scheduled arrivals at an STM transit stop.

    Returns upcoming arrivals based on the static GTFS schedule. This does not
    include real-time predictions. Use this to see what buses/metros are
    scheduled to arrive at a stop.

    The schedule is filtered by today's active service (weekday/weekend/holiday).

    Examples:
        get_scheduled_arrivals(stop_id="51001")  # All arrivals at stop
        get_scheduled_arrivals(stop_id="51001", route_id="24")  # Just route 24
        get_scheduled_arrivals(stop_id="51001", start_time="08:00:00", end_time="09:00:00")

    Args:
        stop_id: The stop ID to get arrivals for (required).
                 Use search_stops() to find stop IDs.
        route_id: Optional route ID to filter arrivals by a specific bus/metro line.
        start_time: Start of time window in HH:MM:SS format.
                    Defaults to the current time.
        end_time: End of time window in HH:MM:SS format.
                  Defaults to 28:00:00 (4 AM next day) to include late-night service.
                  Note: GTFS times can exceed 24:00:00 for trips past midnight.
        limit: Maximum number of arrivals to return (default 20, max 100).

    Returns:
        GetScheduledArrivalsResponse containing:
        - stop: Basic stop information
        - arrivals: List of scheduled arrivals with route info, times, and minutes until
        - service_date: The service date used for schedule lookup
        - query_time: The start time used for the query
        - count: Number of arrivals returned
    """
    # Validate limit
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    return await _get_scheduled_arrivals(
        stop_id=stop_id,
        route_id=route_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
