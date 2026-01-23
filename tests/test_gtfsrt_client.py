"""Tests for the GTFS-RT client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.transit import gtfs_realtime_pb2

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.data.gtfsrt_client import GTFSRTClient


def create_trip_updates_feed() -> bytes:
    """Create a minimal trip updates protobuf feed for testing."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1700000000

    entity = feed.entity.add()
    entity.id = "trip_update_1"

    tu = entity.trip_update
    tu.trip.trip_id = "trip_123"
    tu.trip.route_id = "route_456"
    tu.timestamp = 1700000000

    stu = tu.stop_time_update.add()
    stu.stop_sequence = 5
    stu.stop_id = "stop_789"
    stu.arrival.delay = 120  # 2 minutes late
    stu.arrival.time = 1700000120

    return feed.SerializeToString()


def create_vehicle_positions_feed() -> bytes:
    """Create a minimal vehicle positions protobuf feed for testing."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1700000000

    entity = feed.entity.add()
    entity.id = "vehicle_1"

    vp = entity.vehicle
    vp.trip.trip_id = "trip_123"
    vp.trip.route_id = "route_456"
    vp.vehicle.id = "bus_001"
    vp.vehicle.label = "Bus 001"
    vp.position.latitude = 45.5017
    vp.position.longitude = -73.5673
    vp.position.bearing = 90.0
    vp.timestamp = 1700000000
    vp.stop_id = "stop_789"
    vp.current_stop_sequence = 5

    return feed.SerializeToString()


@pytest.fixture
def config() -> GTFSRTConfig:
    """Create a test config."""
    return GTFSRTConfig(
        api_key="test_api_key",
        cache_ttl_seconds=30,
        trip_updates_url="https://example.com/trip_updates",
        vehicle_positions_url="https://example.com/vehicle_positions",
    )


@pytest.mark.asyncio
async def test_parse_trip_updates(config: GTFSRTConfig):
    """Test parsing trip updates from protobuf."""
    feed_bytes = create_trip_updates_feed()

    # Mock the HTTP response (raise_for_status is sync, not async)
    mock_response = MagicMock()
    mock_response.content = feed_bytes

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        async with GTFSRTClient(config) as client:
            data = await client.fetch_trip_updates()

    assert data.header.gtfs_realtime_version == "2.0"
    assert data.header.timestamp == 1700000000
    assert len(data.trip_updates) == 1

    tu = data.trip_updates[0]
    assert tu.trip.trip_id == "trip_123"
    assert tu.trip.route_id == "route_456"
    assert tu.timestamp == 1700000000
    assert len(tu.stop_time_update) == 1

    stu = tu.stop_time_update[0]
    assert stu.stop_sequence == 5
    assert stu.stop_id == "stop_789"
    assert stu.arrival.delay == 120
    assert stu.arrival.time == 1700000120


@pytest.mark.asyncio
async def test_parse_vehicle_positions(config: GTFSRTConfig):
    """Test parsing vehicle positions from protobuf."""
    feed_bytes = create_vehicle_positions_feed()

    # Mock the HTTP response (raise_for_status is sync, not async)
    mock_response = MagicMock()
    mock_response.content = feed_bytes

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        async with GTFSRTClient(config) as client:
            data = await client.fetch_vehicle_positions()

    assert data.header.gtfs_realtime_version == "2.0"
    assert data.header.timestamp == 1700000000
    assert len(data.vehicles) == 1

    vp = data.vehicles[0]
    assert vp.trip.trip_id == "trip_123"
    assert vp.trip.route_id == "route_456"
    assert vp.vehicle.id == "bus_001"
    assert vp.vehicle.label == "Bus 001"
    # Use pytest.approx for float comparisons (protobuf uses float32)
    assert vp.position.latitude == pytest.approx(45.5017, rel=1e-5)
    assert vp.position.longitude == pytest.approx(-73.5673, rel=1e-5)
    assert vp.position.bearing == pytest.approx(90.0)
    assert vp.timestamp == 1700000000
    assert vp.stop_id == "stop_789"
    assert vp.current_stop_sequence == 5
