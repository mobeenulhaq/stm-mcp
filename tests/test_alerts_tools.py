"""Tests for the alerts MCP tools."""

from unittest.mock import AsyncMock, patch

import pytest

from stm_mcp.models.responses import (
    GetMetroStatusResponse,
    GetServiceAlertsResponse,
    MetroLine,
    MetroLineStatus,
    MetroStatus,
    ServiceAlert,
)
from stm_mcp.tools.alerts_tools import get_metro_status, get_service_alerts


def _create_mock_metro_status_response() -> GetMetroStatusResponse:
    """Create a mock metro status response."""
    return GetMetroStatusResponse(
        lines=[
            MetroLineStatus(
                line=MetroLine.GREEN,
                line_name="Green Line / Ligne verte",
                status=MetroStatus.NORMAL,
                alerts=[],
            ),
            MetroLineStatus(
                line=MetroLine.ORANGE,
                line_name="Orange Line / Ligne orange",
                status=MetroStatus.DISRUPTED,
                alerts=[
                    ServiceAlert(
                        header_fr="Votre ligne",
                        header_en="Your line",
                        description_fr="Service interrompu",
                        description_en="Service interrupted",
                        route_short_name="2",
                        is_metro=True,
                    )
                ],
            ),
            MetroLineStatus(
                line=MetroLine.YELLOW,
                line_name="Yellow Line / Ligne jaune",
                status=MetroStatus.NORMAL,
                alerts=[],
            ),
            MetroLineStatus(
                line=MetroLine.BLUE,
                line_name="Blue Line / Ligne bleue",
                status=MetroStatus.UNKNOWN,
                alerts=[],
            ),
        ],
        timestamp=1700000000,
        all_normal=False,
        api_available=True,
    )


def _create_mock_alerts_response(count: int = 5) -> GetServiceAlertsResponse:
    """Create a mock service alerts response."""
    alerts = [
        ServiceAlert(
            header_fr=f"Alerte {i}",
            header_en=f"Alert {i}",
            description_fr=f"Description {i}",
            description_en=f"Description {i}",
            route_short_name=str(20 + i),
            is_metro=False,
        )
        for i in range(count)
    ]
    return GetServiceAlertsResponse(
        alerts=alerts,
        count=count,
        total_count=count,
        timestamp=1700000000,
        api_available=True,
    )


@pytest.mark.asyncio
async def test_get_metro_status_returns_response():
    """get_metro_status should return the service response."""
    mock_response = _create_mock_metro_status_response()

    with patch(
        "stm_mcp.tools.alerts_tools._get_metro_status",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await get_metro_status()

    assert result.api_available is True
    assert len(result.lines) == 4
    assert result.all_normal is False


@pytest.mark.asyncio
async def test_get_service_alerts_returns_response():
    """get_service_alerts should return the service response."""
    mock_response = _create_mock_alerts_response(5)

    with patch(
        "stm_mcp.tools.alerts_tools._get_service_alerts",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await get_service_alerts()

    assert result.api_available is True
    assert result.count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (0, 1),
        (500, 100),
    ],
)
async def test_get_service_alerts_clamps_limit(limit: int, expected: int):
    """get_service_alerts should clamp limit to 1-100."""
    mock_response = _create_mock_alerts_response(1)

    with patch(
        "stm_mcp.tools.alerts_tools._get_service_alerts",
        new=AsyncMock(return_value=mock_response),
    ) as mock_service:
        await get_service_alerts(limit=limit)

    mock_service.assert_called_once()
    call_kwargs = mock_service.call_args.kwargs
    assert call_kwargs["limit"] == expected


@pytest.mark.asyncio
async def test_get_service_alerts_passes_filters():
    """get_service_alerts should pass filters to the service."""
    mock_response = _create_mock_alerts_response(1)

    with patch(
        "stm_mcp.tools.alerts_tools._get_service_alerts",
        new=AsyncMock(return_value=mock_response),
    ) as mock_service:
        await get_service_alerts(route="24", stop_code="51001", include_metro=False)

    mock_service.assert_called_once()
    call_kwargs = mock_service.call_args.kwargs
    assert call_kwargs["route"] == "24"
    assert call_kwargs["stop_code"] == "51001"
    assert call_kwargs["include_metro"] is False
