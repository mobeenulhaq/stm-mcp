"""Tests for the i3 API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.data.i3_client import I3Client


def create_i3_response() -> dict:
    """Create a sample i3 API response for testing."""
    return {
        "header": {"timestamp": 1700000000},
        "alerts": [
            {
                "active_periods": {"start": 1700000000, "end": None},
                "cause": None,
                "effect": None,
                "informed_entities": [
                    {"route_short_name": "24"},
                    {"direction_id": "N"},
                    {"stop_code": "51001"},
                ],
                "header_texts": [
                    {"language": "fr", "text": "Votre arrêt"},
                    {"language": "en", "text": "Your stop"},
                ],
                "description_texts": [
                    {"language": "fr", "text": "Arrêt déplacé"},
                    {"language": "en", "text": "Stop relocated"},
                ],
            },
            {
                "active_periods": {"start": 1700000000, "end": None},
                "cause": None,
                "effect": None,
                "informed_entities": [{"route_short_name": "1"}],
                "header_texts": [
                    {"language": "fr", "text": "Votre ligne"},
                    {"language": "en", "text": "Your line"},
                ],
                "description_texts": [
                    {"language": "fr", "text": "Service normal du métro"},
                    {"language": "en", "text": "Normal métro service"},
                ],
            },
        ],
    }


@pytest.fixture
def config() -> GTFSRTConfig:
    """Create a test config."""
    return GTFSRTConfig(
        STM_API_KEY="test_api_key",
        i3_etatservice_url="https://example.com/etatservice",
    )


@pytest.mark.asyncio
async def test_fetch_service_status_parses_json(config: GTFSRTConfig):
    """Test parsing service status from JSON."""
    response_data = create_i3_response()

    mock_response = MagicMock()
    mock_response.json.return_value = response_data

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        async with I3Client(config) as client:
            data = await client.fetch_service_status()

    assert data.header.timestamp == 1700000000
    assert len(data.alerts) == 2

    # First alert - bus route
    alert1 = data.alerts[0]
    assert len(alert1.informed_entities) == 3
    assert alert1.informed_entities[0].route_short_name == "24"
    assert alert1.informed_entities[1].direction_id == "N"
    assert alert1.informed_entities[2].stop_code == "51001"
    assert len(alert1.header_texts) == 2
    assert alert1.header_texts[0].language.value == "fr"
    assert alert1.header_texts[0].text == "Votre arrêt"

    # Second alert - metro
    alert2 = data.alerts[1]
    assert alert2.informed_entities[0].route_short_name == "1"
    assert alert2.description_texts[0].text == "Service normal du métro"


@pytest.mark.asyncio
async def test_client_requires_async_context():
    """Test that client methods fail without async context."""
    config = GTFSRTConfig(STM_API_KEY="test_key")
    client = I3Client(config)

    with pytest.raises(RuntimeError, match="Client not initialized"):
        await client.fetch_service_status()


@pytest.mark.asyncio
async def test_client_sets_apikey_header(config: GTFSRTConfig):
    """Test that the client sets the apikey header."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"header": {"timestamp": 0}, "alerts": []}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        async with I3Client(config) as client:
            await client.fetch_service_status()

        # Check that AsyncClient was created with apikey header
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args.kwargs
        assert call_kwargs["headers"]["apikey"] == "test_api_key"


@pytest.mark.asyncio
async def test_client_handles_extra_fields():
    """Test that extra fields in the response are ignored."""
    config = GTFSRTConfig(STM_API_KEY="test_key")
    response_data = {
        "header": {"timestamp": 1700000000, "extra_field": "ignored"},
        "alerts": [
            {
                "active_periods": {"start": 1700000000},
                "informed_entities": [],
                "header_texts": [],
                "description_texts": [],
                "unknown_field": "should be ignored",
            }
        ],
        "another_extra": "also ignored",
    }

    mock_response = MagicMock()
    mock_response.json.return_value = response_data

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        async with I3Client(config) as client:
            data = await client.fetch_service_status()

    # Should parse without errors despite extra fields
    assert data.header.timestamp == 1700000000
    assert len(data.alerts) == 1
