from stm_mcp.models.responses import GetMetroStatusResponse, GetServiceAlertsResponse
from stm_mcp.app import mcp
from stm_mcp.services.alerts_service import (
    get_metro_status as _get_metro_status,
)
from stm_mcp.services.alerts_service import (
    get_service_alerts as _get_service_alerts,
)


@mcp.tool()
async def get_metro_status() -> GetMetroStatusResponse:
    """Get the current service status of all STM metro lines.

    Returns the status (normal, disrupted, or unknown) for all 4 metro lines
    (Green, Orange, Yellow, Blue) along with any active alerts affecting each line.

    When api_available is False, the status will be 'unknown' for all lines.
    This happens when the API key is not configured or the API is unreachable.

    Returns:
        GetMetroStatusResponse with status of all metro lines.
    """
    return await _get_metro_status()


@mcp.tool()
async def get_service_alerts(
    route: str | None = None,
    stop_code: str | None = None,
    include_metro: bool = True,
    limit: int = 50,
) -> GetServiceAlertsResponse:
    """Get service alerts for STM transit routes and stops.

    Returns active service alerts that can be filtered by route, stop, or type.
    Alerts include information about service disruptions, stop relocations,
    and other important notices in both French and English.

    Args:
        route: Filter by STM route number/short name (e.g., "24" for bus 24,
               "1" for Green Line metro). Returns only alerts for this route.
        stop_code: Filter by stop code (e.g., "51001"). Returns only alerts
                   affecting this specific stop.
        include_metro: If False, excludes metro alerts. Default True.
        limit: Maximum number of alerts to return (1-100, default: 50).

    Returns:
        GetServiceAlertsResponse with filtered alerts.
    """
    # Validate and clamp limit to 1-100
    limit = max(1, min(100, limit))

    return await _get_service_alerts(
        route=route,
        stop_code=stop_code,
        include_metro=include_metro,
        limit=limit,
    )
