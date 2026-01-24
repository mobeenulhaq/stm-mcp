"""Service for fetching i3 API alerts and metro status with caching.

Provides cached access to service alerts and metro status.
All errors are caught and logged - functions return api_available=False on failure.
"""

import logging

from stm_mcp.data.cache import FeedCache
from stm_mcp.data.config import GTFSRTConfig, get_gtfsrt_config
from stm_mcp.data.i3_client import I3Client
from stm_mcp.models.alerts import Alert, I3Response, Language
from stm_mcp.models.responses import (
    GetMetroStatusResponse,
    GetServiceAlertsResponse,
    MetroLine,
    MetroLineStatus,
    MetroStatus,
    ServiceAlert,
)

logger = logging.getLogger(__name__)

# Metro line route IDs
METRO_ROUTE_IDS = {"1", "2", "4", "5"}

# Human-readable names for metro lines
METRO_LINE_NAMES = {
    MetroLine.GREEN: "Green Line / Ligne verte",
    MetroLine.ORANGE: "Orange Line / Ligne orange",
    MetroLine.YELLOW: "Yellow Line / Ligne jaune",
    MetroLine.BLUE: "Blue Line / Ligne bleue",
}

# Module-level cache (lazy-initialized)
_i3_cache: FeedCache[I3Response] | None = None
_config: GTFSRTConfig | None = None


def _get_config() -> GTFSRTConfig:
    """Get or create the config singleton."""
    global _config
    if _config is None:
        _config = get_gtfsrt_config()
    return _config


def _get_i3_cache() -> FeedCache[I3Response]:
    """Get or create the i3 cache singleton."""
    global _i3_cache
    if _i3_cache is None:
        config = _get_config()
        _i3_cache = FeedCache[I3Response](ttl=config.i3_cache_ttl_seconds)
    return _i3_cache


async def _fetch_i3_data(force_refresh: bool = False) -> I3Response | None:
    """Fetch i3 data with caching and double-check locking.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        I3Response if successful, None if unavailable or error.
    """
    config = _get_config()
    if config.api_key is None:
        logger.debug("No API key configured, cannot fetch i3 data")
        return None

    cache = _get_i3_cache()

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached = cache.get()
        if cached is not None:
            return cached

    # Acquire lock to prevent concurrent fetches
    async with cache.lock:
        # Double-check cache after acquiring lock
        if not force_refresh:
            cached = cache.get()
            if cached is not None:
                return cached

        # Fetch fresh data
        try:
            async with I3Client(config) as client:
                data = await client.fetch_service_status()
                cache.set(data)
                logger.debug(f"Fetched {len(data.alerts)} alerts from i3 API")
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch i3 data: {e}")
            return None


def _extract_text(texts: list, language: Language) -> str | None:
    """Extract text for the given language from a list of LocalizedText."""
    for text_obj in texts:
        if text_obj.language == language:
            return text_obj.text
    return None


def _alert_to_service_alert(alert: Alert) -> ServiceAlert:
    """Convert raw i3 Alert to ServiceAlert response model."""
    # Extract bilingual texts
    header_fr = _extract_text(alert.header_texts, Language.FR)
    header_en = _extract_text(alert.header_texts, Language.EN)
    description_fr = _extract_text(alert.description_texts, Language.FR)
    description_en = _extract_text(alert.description_texts, Language.EN)

    # Extract entity info (combine from all informed_entities)
    route_short_name: str | None = None
    direction_id: str | None = None
    stop_code: str | None = None

    for entity in alert.informed_entities:
        if entity.route_short_name:
            route_short_name = entity.route_short_name
        if entity.direction_id:
            direction_id = entity.direction_id
        if entity.stop_code:
            stop_code = entity.stop_code

    # Determine if this is a metro alert
    is_metro = route_short_name in METRO_ROUTE_IDS if route_short_name else False

    # Extract time period
    active_start = alert.active_periods.start if alert.active_periods else None
    active_end = alert.active_periods.end if alert.active_periods else None

    return ServiceAlert(
        header_fr=header_fr,
        header_en=header_en,
        description_fr=description_fr,
        description_en=description_en,
        route_short_name=route_short_name,
        direction_id=direction_id,
        stop_code=stop_code,
        active_start=active_start,
        active_end=active_end,
        is_metro=is_metro,
    )


def _is_normal_service_alert(alert: Alert) -> bool:
    """Check if alert indicates normal metro service."""
    for text_obj in alert.description_texts:
        if "Service normal du métro" in text_obj.text:
            return True
        if "Normal métro service" in text_obj.text:
            return True
    return False


def _determine_metro_status(alerts: list[ServiceAlert], raw_alerts: list[Alert]) -> MetroStatus:
    """Determine metro line status from alerts.

    Rules:
    - If any raw alert contains "Service normal du métro" → NORMAL
    - If any alerts exist for the line → DISRUPTED
    - If no alerts for line → UNKNOWN
    """
    if not alerts:
        return MetroStatus.UNKNOWN

    # Check if any of the corresponding raw alerts indicate normal service
    for raw_alert in raw_alerts:
        if _is_normal_service_alert(raw_alert):
            return MetroStatus.NORMAL

    # Any other alerts mean disrupted
    return MetroStatus.DISRUPTED


async def get_metro_status(force_refresh: bool = False) -> GetMetroStatusResponse:
    """Get status of all 4 metro lines.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        GetMetroStatusResponse with status of all metro lines.
    """
    data = await _fetch_i3_data(force_refresh)

    if data is None:
        # API unavailable - return unknown status for all lines
        lines = [
            MetroLineStatus(
                line=line,
                line_name=METRO_LINE_NAMES[line],
                status=MetroStatus.UNKNOWN,
                alerts=[],
            )
            for line in MetroLine
        ]
        return GetMetroStatusResponse(
            lines=lines,
            timestamp=0,
            all_normal=False,
            api_available=False,
        )

    # Group alerts by metro line
    alerts_by_line: dict[MetroLine, list[tuple[ServiceAlert, Alert]]] = {
        line: [] for line in MetroLine
    }

    for alert in data.alerts:
        # Find route_short_name from informed_entities
        route_short_name = None
        for entity in alert.informed_entities:
            if entity.route_short_name:
                route_short_name = entity.route_short_name
                break

        if route_short_name in METRO_ROUTE_IDS:
            line = MetroLine(route_short_name)
            service_alert = _alert_to_service_alert(alert)
            alerts_by_line[line].append((service_alert, alert))

    # Build line statuses
    lines = []
    all_normal = True

    for line in MetroLine:
        line_alerts = alerts_by_line[line]
        service_alerts = [sa for sa, _ in line_alerts]
        raw_alerts = [ra for _, ra in line_alerts]

        status = _determine_metro_status(service_alerts, raw_alerts)
        if status != MetroStatus.NORMAL:
            all_normal = False

        # Filter out "normal service" alerts from the response (they're not useful to show)
        display_alerts = [sa for sa, ra in line_alerts if not _is_normal_service_alert(ra)]

        lines.append(
            MetroLineStatus(
                line=line,
                line_name=METRO_LINE_NAMES[line],
                status=status,
                alerts=display_alerts,
            )
        )

    return GetMetroStatusResponse(
        lines=lines,
        timestamp=data.header.timestamp,
        all_normal=all_normal,
        api_available=True,
    )


async def get_service_alerts(
    route: str | None = None,
    stop_code: str | None = None,
    include_metro: bool = True,
    limit: int = 50,
    force_refresh: bool = False,
) -> GetServiceAlertsResponse:
    """Get filtered service alerts.

    Args:
        route: Filter by route short name (e.g., "24", "1").
        stop_code: Filter by stop code.
        include_metro: If False, exclude metro alerts.
        limit: Maximum number of alerts to return (1-100).
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        GetServiceAlertsResponse with filtered alerts.
    """
    data = await _fetch_i3_data(force_refresh)

    if data is None:
        return GetServiceAlertsResponse(
            alerts=[],
            count=0,
            total_count=0,
            timestamp=None,
            api_available=False,
        )

    # Convert all alerts
    all_alerts = [_alert_to_service_alert(alert) for alert in data.alerts]
    total_count = len(all_alerts)

    # Filter alerts
    filtered = all_alerts

    if not include_metro:
        filtered = [a for a in filtered if not a.is_metro]

    if route:
        filtered = [a for a in filtered if a.route_short_name == route]

    if stop_code:
        filtered = [a for a in filtered if a.stop_code == stop_code]

    # Apply limit
    limited = filtered[:limit]

    return GetServiceAlertsResponse(
        alerts=limited,
        count=len(limited),
        total_count=total_count,
        timestamp=data.header.timestamp,
        api_available=True,
    )


def clear_cache() -> None:
    """Clear the i3 cache.

    Useful for testing or forcing fresh data on next request.
    """
    global _i3_cache
    if _i3_cache:
        _i3_cache.clear()


def reset_service() -> None:
    """Reset the service state completely.

    Clears cache and resets config. Useful for testing.
    """
    global _i3_cache, _config
    _i3_cache = None
    _config = None
    # Clear the lru_cache on get_gtfsrt_config so it re-reads .env/environment
    if hasattr(get_gtfsrt_config, "cache_clear"):
        get_gtfsrt_config.cache_clear()
