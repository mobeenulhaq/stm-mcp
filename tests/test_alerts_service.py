"""Tests for the alerts service."""

from unittest.mock import AsyncMock, patch

import pytest

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.models.alerts import (
    ActivePeriod,
    Alert,
    I3Header,
    I3Response,
    InformedEntity,
    Language,
    LocalizedText,
)
from stm_mcp.models.responses import MetroStatus
from stm_mcp.services import alerts_service


@pytest.fixture(autouse=True)
def reset_service():
    """Reset the service state before and after each test."""
    alerts_service.reset_service()
    yield
    alerts_service.reset_service()


def _config_without_api_key() -> GTFSRTConfig:
    """Create a config without an API key."""
    return GTFSRTConfig(STM_API_KEY=None)


def _config_with_api_key() -> GTFSRTConfig:
    """Create a config with an API key."""
    return GTFSRTConfig(STM_API_KEY="test_key")


def _create_metro_normal_alert(route_id: str) -> Alert:
    """Create a 'Service normal du métro' alert for a metro line."""
    return Alert(
        active_periods=ActivePeriod(start=1700000000),
        informed_entities=[InformedEntity(route_short_name=route_id)],
        header_texts=[
            LocalizedText(language=Language.FR, text="Votre ligne"),
            LocalizedText(language=Language.EN, text="Your line"),
        ],
        description_texts=[
            LocalizedText(language=Language.FR, text="Service normal du métro"),
            LocalizedText(language=Language.EN, text="Normal métro service"),
        ],
    )


def _create_metro_disruption_alert(route_id: str) -> Alert:
    """Create a disruption alert for a metro line."""
    return Alert(
        active_periods=ActivePeriod(start=1700000000),
        informed_entities=[InformedEntity(route_short_name=route_id)],
        header_texts=[
            LocalizedText(language=Language.FR, text="Votre ligne"),
            LocalizedText(language=Language.EN, text="Your line"),
        ],
        description_texts=[
            LocalizedText(language=Language.FR, text="Service interrompu"),
            LocalizedText(language=Language.EN, text="Service interrupted"),
        ],
    )


def _create_bus_alert(route_id: str, stop_code: str | None = None) -> Alert:
    """Create an alert for a bus route."""
    entities = [InformedEntity(route_short_name=route_id)]
    if stop_code:
        entities.append(InformedEntity(stop_code=stop_code))

    return Alert(
        active_periods=ActivePeriod(start=1700000000),
        informed_entities=entities,
        header_texts=[
            LocalizedText(language=Language.FR, text="Votre arrêt"),
            LocalizedText(language=Language.EN, text="Your stop"),
        ],
        description_texts=[
            LocalizedText(language=Language.FR, text="Arrêt déplacé"),
            LocalizedText(language=Language.EN, text="Stop relocated"),
        ],
    )


# =============================================================================
# Graceful degradation tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_metro_status_without_api_key():
    """get_metro_status returns api_available=False without API key."""
    alerts_service._config = _config_without_api_key()

    result = await alerts_service.get_metro_status()

    assert result.api_available is False
    assert result.all_normal is False
    assert len(result.lines) == 4
    for line in result.lines:
        assert line.status == MetroStatus.UNKNOWN


@pytest.mark.asyncio
async def test_get_service_alerts_without_api_key():
    """get_service_alerts returns api_available=False without API key."""
    alerts_service._config = _config_without_api_key()

    result = await alerts_service.get_service_alerts()

    assert result.api_available is False
    assert result.count == 0
    assert result.total_count == 0


# =============================================================================
# Metro status logic tests
# =============================================================================


@pytest.mark.asyncio
async def test_metro_status_normal_service():
    """Metro line with 'Service normal du métro' alert should be NORMAL."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[_create_metro_normal_alert("1")],  # Green line
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_metro_status()

    assert result.api_available is True
    green_line = next(line for line in result.lines if line.line.value == "1")
    assert green_line.status == MetroStatus.NORMAL
    # Normal service alerts should be filtered out of the display
    assert len(green_line.alerts) == 0


@pytest.mark.asyncio
async def test_metro_status_disrupted():
    """Metro line with disruption alert should be DISRUPTED."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[_create_metro_disruption_alert("2")],  # Orange line
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_metro_status()

    assert result.api_available is True
    orange_line = next(line for line in result.lines if line.line.value == "2")
    assert orange_line.status == MetroStatus.DISRUPTED
    assert len(orange_line.alerts) == 1
    assert result.all_normal is False


@pytest.mark.asyncio
async def test_metro_status_unknown_no_alerts():
    """Metro line with no alerts should be UNKNOWN."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[],  # No alerts at all
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_metro_status()

    assert result.api_available is True
    for line in result.lines:
        assert line.status == MetroStatus.UNKNOWN


@pytest.mark.asyncio
async def test_metro_status_all_normal():
    """all_normal should be True when all lines have normal service."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[
            _create_metro_normal_alert("1"),  # Green
            _create_metro_normal_alert("2"),  # Orange
            _create_metro_normal_alert("4"),  # Yellow
            _create_metro_normal_alert("5"),  # Blue
        ],
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_metro_status()

    assert result.all_normal is True


# =============================================================================
# Alert filtering tests
# =============================================================================


@pytest.mark.asyncio
async def test_filter_alerts_by_route():
    """get_service_alerts should filter by route."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[
            _create_bus_alert("24"),
            _create_bus_alert("55"),
            _create_bus_alert("24"),  # Another alert for route 24
        ],
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_service_alerts(route="24")

    assert result.count == 2
    assert result.total_count == 3
    for alert in result.alerts:
        assert alert.route_short_name == "24"


@pytest.mark.asyncio
async def test_filter_alerts_by_stop_code():
    """get_service_alerts should filter by stop_code."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[
            _create_bus_alert("24", stop_code="51001"),
            _create_bus_alert("24", stop_code="51002"),
            _create_bus_alert("55", stop_code="51001"),
        ],
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_service_alerts(stop_code="51001")

    assert result.count == 2
    for alert in result.alerts:
        assert alert.stop_code == "51001"


@pytest.mark.asyncio
async def test_filter_exclude_metro():
    """get_service_alerts with include_metro=False should exclude metro alerts."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[
            _create_bus_alert("24"),
            _create_metro_normal_alert("1"),
            _create_metro_disruption_alert("2"),
        ],
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_service_alerts(include_metro=False)

    assert result.count == 1
    assert result.alerts[0].route_short_name == "24"
    assert result.alerts[0].is_metro is False


@pytest.mark.asyncio
async def test_filter_alerts_limit():
    """get_service_alerts should respect the limit parameter."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[_create_bus_alert(str(i)) for i in range(10, 20)],  # 10 alerts
    )

    with patch.object(alerts_service, "_fetch_i3_data", new=AsyncMock(return_value=i3_response)):
        result = await alerts_service.get_service_alerts(limit=3)

    assert result.count == 3
    assert result.total_count == 10


# =============================================================================
# Cache tests
# =============================================================================


@pytest.mark.asyncio
async def test_cache_is_used():
    """Second call should use cached data."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[_create_bus_alert("24")],
    )

    fetch_mock = AsyncMock(return_value=i3_response)

    with patch.object(alerts_service, "I3Client") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.fetch_service_status = fetch_mock
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client_class.return_value = mock_client

        # First call - should fetch
        await alerts_service.get_service_alerts()
        # Second call - should use cache
        await alerts_service.get_service_alerts()

    # Should only have fetched once
    assert fetch_mock.call_count == 1


@pytest.mark.asyncio
async def test_clear_cache():
    """clear_cache should invalidate the cache."""
    alerts_service._config = _config_with_api_key()

    i3_response = I3Response(
        header=I3Header(timestamp=1700000000),
        alerts=[],
    )

    fetch_mock = AsyncMock(return_value=i3_response)

    with patch.object(alerts_service, "I3Client") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.fetch_service_status = fetch_mock
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client_class.return_value = mock_client

        # First call
        await alerts_service.get_service_alerts()
        # Clear cache
        alerts_service.clear_cache()
        # Second call - should fetch again
        await alerts_service.get_service_alerts()

    assert fetch_mock.call_count == 2
