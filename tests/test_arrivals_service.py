"""Tests for arrivals service (Phase 4: Static + RT Merge)."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.models.realtime import (
    FeedHeader,
    OccupancyStatus,
    Position,
    StopTimeEvent,
    StopTimeUpdate,
    TripDescriptor,
    TripUpdate,
    TripUpdatesData,
    VehicleDescriptor,
    VehiclePosition,
    VehiclePositionsData,
)
from stm_mcp.models.responses import ArrivalSource, ScheduledArrival
from stm_mcp.services import arrivals_service, realtime_service
from stm_mcp.services.arrivals_service import (
    apply_delay_to_time,
    build_trip_update_index,
    build_vehicle_position_index,
    get_next_arrivals,
    merge_arrival_with_realtime,
)

# ============================================================================
# Unit Tests for Helper Functions
# ============================================================================


class TestApplyDelayToTime:
    """Tests for apply_delay_to_time function."""

    def test_positive_delay(self) -> None:
        """Test adding positive delay (late)."""
        result = apply_delay_to_time("08:30:00", 120)  # 2 minutes late
        assert result == "08:32:00"

    def test_negative_delay(self) -> None:
        """Test adding negative delay (early)."""
        result = apply_delay_to_time("08:30:00", -120)  # 2 minutes early
        assert result == "08:28:00"

    def test_gtfs_time_exceeding_24(self) -> None:
        """Test with GTFS times exceeding 24:00."""
        result = apply_delay_to_time("25:30:00", 300)  # 5 minutes late
        assert result == "25:35:00"


class TestBuildTripUpdateIndex:
    """Tests for build_trip_update_index function."""

    def _create_trip_updates(self, updates: list[tuple[str, str, int | None]]) -> TripUpdatesData:
        """Create TripUpdatesData from list of (trip_id, stop_id, delay)."""
        trip_updates = []
        for trip_id, stop_id, delay in updates:
            stu = StopTimeUpdate(
                stop_id=stop_id,
                arrival=StopTimeEvent(delay=delay) if delay is not None else None,
            )
            trip_updates.append(
                TripUpdate(
                    trip=TripDescriptor(trip_id=trip_id),
                    stop_time_update=[stu],
                    timestamp=1234567890,
                )
            )
        return TripUpdatesData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            trip_updates=trip_updates,
            fetched_at=datetime.now(UTC),
        )

    def test_matching_stop(self) -> None:
        """Test that matching stop is indexed."""
        data = self._create_trip_updates([("TRIP1", "STOP1", 60)])
        index = build_trip_update_index(data, "STOP1")

        assert "TRIP1" in index
        stu, timestamp = index["TRIP1"]
        assert stu.stop_id == "STOP1"
        assert stu.arrival.delay == 60
        assert timestamp == 1234567890

    def test_non_matching_stop(self) -> None:
        """Test that non-matching stop is not indexed."""
        data = self._create_trip_updates([("TRIP1", "STOP1", 60)])
        index = build_trip_update_index(data, "STOP2")

        assert len(index) == 0

    def test_trip_without_trip_id(self) -> None:
        """Test that trips without trip_id are skipped."""
        data = TripUpdatesData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            trip_updates=[
                TripUpdate(
                    trip=TripDescriptor(trip_id=None),  # No trip_id
                    stop_time_update=[StopTimeUpdate(stop_id="STOP1")],
                )
            ],
            fetched_at=datetime.now(UTC),
        )
        index = build_trip_update_index(data, "STOP1")

        assert len(index) == 0


class TestBuildVehiclePositionIndex:
    """Tests for build_vehicle_position_index function."""

    def _create_vehicle_positions(
        self, positions: list[tuple[str | None, OccupancyStatus | None]]
    ) -> VehiclePositionsData:
        """Create VehiclePositionsData from list of (trip_id, occupancy)."""
        vehicles = []
        for trip_id, occupancy in positions:
            trip = TripDescriptor(trip_id=trip_id) if trip_id else None
            vehicles.append(
                VehiclePosition(
                    trip=trip,
                    vehicle=VehicleDescriptor(id="V1"),
                    position=Position(latitude=45.5, longitude=-73.5),
                    occupancy_status=occupancy,
                )
            )
        return VehiclePositionsData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            vehicles=vehicles,
            fetched_at=datetime.now(UTC),
        )

    def test_keyed_by_trip_id(self) -> None:
        """Test that index is keyed by trip_id."""
        data = self._create_vehicle_positions(
            [
                ("TRIP1", OccupancyStatus.MANY_SEATS_AVAILABLE),
            ]
        )
        index = build_vehicle_position_index(data)

        assert "TRIP1" in index
        assert index["TRIP1"].occupancy_status == OccupancyStatus.MANY_SEATS_AVAILABLE

    def test_vehicle_without_trip(self) -> None:
        """Test that vehicles without trip info are skipped."""
        data = self._create_vehicle_positions(
            [
                (None, OccupancyStatus.MANY_SEATS_AVAILABLE),
            ]
        )
        index = build_vehicle_position_index(data)

        assert len(index) == 0


class TestMergeArrivalWithRealtime:
    """Tests for merge_arrival_with_realtime function."""

    def _create_scheduled_arrival(
        self, trip_id: str = "TRIP1", route_type: int = 3
    ) -> ScheduledArrival:
        """Create a test ScheduledArrival."""
        return ScheduledArrival(
            trip_id=trip_id,
            route_id="24",
            route_short_name="24",
            route_type=route_type,
            trip_headsign="Sherbrooke / Cavendish",
            arrival_time="08:30:00",
            arrival_time_formatted="8:30 AM",
            minutes_until=15,
        )

    def test_static_only(self) -> None:
        """Test merge with no RT data (static only)."""
        scheduled = self._create_scheduled_arrival()

        arrival = merge_arrival_with_realtime(
            scheduled=scheduled,
            stop_time_update=None,
            vehicle_position=None,
            query_time="08:15:00",
            rt_timestamp=None,
        )

        assert arrival.source == ArrivalSource.STATIC
        assert arrival.scheduled_arrival_time == "08:30:00"
        assert arrival.predicted_arrival_time is None
        assert arrival.delay_seconds is None
        assert arrival.occupancy_status is None
        assert arrival.minutes_until == 15

    def test_with_delay(self) -> None:
        """Test merge with delay from trip update."""
        scheduled = self._create_scheduled_arrival()
        stu = StopTimeUpdate(
            stop_id="STOP1",
            arrival=StopTimeEvent(delay=120),  # 2 minutes late
        )

        arrival = merge_arrival_with_realtime(
            scheduled=scheduled,
            stop_time_update=stu,
            vehicle_position=None,
            query_time="08:15:00",
            rt_timestamp=1234567890,
        )

        assert arrival.source == ArrivalSource.REALTIME
        assert arrival.scheduled_arrival_time == "08:30:00"
        assert arrival.predicted_arrival_time == "08:32:00"
        assert arrival.predicted_arrival_formatted == "8:32 AM"
        assert arrival.delay_seconds == 120
        # minutes_until should be recalculated with predicted time
        # 08:32:00 - 08:15:00 = 17 minutes
        assert arrival.minutes_until == 17

    def test_with_occupancy_only(self) -> None:
        """Test merge with occupancy but no delay."""
        scheduled = self._create_scheduled_arrival()
        vehicle = VehiclePosition(
            trip=TripDescriptor(trip_id="TRIP1"),
            occupancy_status=OccupancyStatus.FEW_SEATS_AVAILABLE,
            timestamp=1234567890,
        )

        arrival = merge_arrival_with_realtime(
            scheduled=scheduled,
            stop_time_update=None,
            vehicle_position=vehicle,
            query_time="08:15:00",
            rt_timestamp=None,
        )

        assert arrival.source == ArrivalSource.REALTIME
        assert arrival.occupancy_status == OccupancyStatus.FEW_SEATS_AVAILABLE
        assert arrival.predicted_arrival_time is None
        assert arrival.delay_seconds is None
        assert arrival.rt_timestamp == 1234567890

    def test_skips_absolute_time_only(self) -> None:
        """Test that RT is skipped when only absolute time present (no delay)."""
        scheduled = self._create_scheduled_arrival()
        stu = StopTimeUpdate(
            stop_id="STOP1",
            arrival=StopTimeEvent(time=1234567890, delay=None),  # Only absolute time
        )

        arrival = merge_arrival_with_realtime(
            scheduled=scheduled,
            stop_time_update=stu,
            vehicle_position=None,
            query_time="08:15:00",
            rt_timestamp=1234567890,
        )

        # Should stay static since no delay field
        assert arrival.source == ArrivalSource.STATIC
        assert arrival.predicted_arrival_time is None
        assert arrival.delay_seconds is None


# ============================================================================
# Integration Tests (with mocked RT data)
# ============================================================================


@pytest.fixture
def sample_gtfs_dir(tmp_path: Path) -> Path:
    """Create a sample GTFS directory with minimal valid data."""
    gtfs_dir = tmp_path / "gtfs"
    gtfs_dir.mkdir()

    # agency.txt
    (gtfs_dir / "agency.txt").write_text(
        "agency_id,agency_name,agency_url,agency_timezone\n"
        "STM,Société de transport de Montréal,http://www.stm.info,America/Montreal\n"
    )

    # routes.txt - include both metro (1) and bus (3)
    (gtfs_dir / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_url,route_color,route_text_color\n"
        "1,STM,Green,Ligne verte,1,http://stm.info/green,008E4F,FFFFFF\n"
        "24,STM,24,Sherbrooke,3,http://stm.info/24,000000,FFFFFF\n"
    )

    # stops.txt
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "51001,51001,Sherbrooke / Saint-Denis,45.518,-73.568,,0,,1\n"
        "BERRI-1,51234,Berri-UQAM - Green Line,45.515,-73.561,,0,,1\n"
    )

    # calendar.txt
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20271231\n"
        "WEEKEND,0,0,0,0,0,1,1,20240101,20271231\n"
        "DAILY,1,1,1,1,1,1,1,20240101,20271231\n"
    )

    # calendar_dates.txt
    (gtfs_dir / "calendar_dates.txt").write_text("service_id,date,exception_type\n")

    # trips.txt
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        "METRO1,1,DAILY,Angrignon,0,SHAPE1,1,,\n"
        "BUS1,24,DAILY,Sherbrooke / Cavendish,0,SHAPE2,1,,\n"
        "BUS2,24,DAILY,Sherbrooke / Cavendish,0,SHAPE2,1,,\n"
    )

    # stop_times.txt
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "METRO1,08:00:00,08:00:00,51001,1,0\n"
        "BUS1,08:10:00,08:10:00,51001,1,0\n"
        "BUS2,08:20:00,08:20:00,51001,1,0\n"
    )

    # feed_info.txt
    (gtfs_dir / "feed_info.txt").write_text(
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
        "STM,http://www.stm.info,fr,20240101,20271231,2024.1\n"
    )

    return gtfs_dir


@pytest.fixture
async def db_path(sample_gtfs_dir: Path, tmp_path: Path) -> Path:
    """Create a test database from sample GTFS data."""
    db_file = tmp_path / "test.db"
    loader = GTFSLoader(db_file)
    await loader.ingest(sample_gtfs_dir)
    return db_file


@pytest.fixture(autouse=True)
def reset_realtime_service():
    """Reset the realtime service state before and after each test."""
    realtime_service.reset_service()
    yield
    realtime_service.reset_service()


def _config_without_api_key() -> GTFSRTConfig:
    """Create a config without an API key."""
    return GTFSRTConfig(STM_API_KEY=None)


def _config_with_api_key() -> GTFSRTConfig:
    """Create a config with an API key."""
    return GTFSRTConfig(STM_API_KEY="test_key")


class TestGetNextArrivalsIntegration:
    """Integration tests for get_next_arrivals."""

    @pytest.mark.asyncio
    async def test_returns_static_when_rt_unavailable(self, db_path: Path) -> None:
        """Test that static data is returned when RT is unavailable."""
        realtime_service._config = _config_without_api_key()

        response = await get_next_arrivals(
            stop_id="51001",
            start_time="08:00:00",
            end_time="09:00:00",
            db_path=db_path,
        )

        assert response.realtime_available is False
        assert response.realtime_count == 0
        assert response.static_only_count == response.count

        # All arrivals should be static
        for arrival in response.arrivals:
            assert arrival.source == ArrivalSource.STATIC

    @pytest.mark.asyncio
    async def test_merges_rt_data_when_available(self, db_path: Path) -> None:
        """Test that RT data is merged when available."""
        realtime_service._config = _config_with_api_key()

        # Create mock RT data
        trip_updates = TripUpdatesData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            trip_updates=[
                TripUpdate(
                    trip=TripDescriptor(trip_id="BUS1"),
                    stop_time_update=[
                        StopTimeUpdate(
                            stop_id="51001",
                            arrival=StopTimeEvent(delay=120),
                        )
                    ],
                    timestamp=1234567890,
                )
            ],
            fetched_at=datetime.now(UTC),
        )

        vehicle_positions = VehiclePositionsData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            vehicles=[
                VehiclePosition(
                    trip=TripDescriptor(trip_id="BUS1"),
                    occupancy_status=OccupancyStatus.MANY_SEATS_AVAILABLE,
                )
            ],
            fetched_at=datetime.now(UTC),
        )

        with (
            patch.object(
                arrivals_service, "get_trip_updates", new=AsyncMock(return_value=trip_updates)
            ),
            patch.object(
                arrivals_service,
                "get_vehicle_positions",
                new=AsyncMock(return_value=vehicle_positions),
            ),
        ):
            response = await get_next_arrivals(
                stop_id="51001",
                start_time="08:00:00",
                end_time="09:00:00",
                db_path=db_path,
            )

        assert response.realtime_available is True
        assert response.realtime_count >= 1

        # Find the BUS1 arrival
        bus1_arrival = next((a for a in response.arrivals if a.trip_id == "BUS1"), None)
        assert bus1_arrival is not None
        assert bus1_arrival.source == ArrivalSource.REALTIME
        assert bus1_arrival.delay_seconds == 120
        assert bus1_arrival.occupancy_status == OccupancyStatus.MANY_SEATS_AVAILABLE

    @pytest.mark.asyncio
    async def test_metro_arrivals_always_static(self, db_path: Path) -> None:
        """Test that metro arrivals are always static (no RT lookup)."""
        realtime_service._config = _config_with_api_key()

        # Create mock RT data with metro trip
        trip_updates = TripUpdatesData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            trip_updates=[
                TripUpdate(
                    trip=TripDescriptor(trip_id="METRO1"),
                    stop_time_update=[
                        StopTimeUpdate(
                            stop_id="51001",
                            arrival=StopTimeEvent(delay=60),
                        )
                    ],
                )
            ],
            fetched_at=datetime.now(UTC),
        )

        with (
            patch.object(
                arrivals_service, "get_trip_updates", new=AsyncMock(return_value=trip_updates)
            ),
            patch.object(
                arrivals_service, "get_vehicle_positions", new=AsyncMock(return_value=None)
            ),
        ):
            response = await get_next_arrivals(
                stop_id="51001",
                start_time="08:00:00",
                end_time="09:00:00",
                db_path=db_path,
            )

        # Find the METRO1 arrival
        metro_arrival = next((a for a in response.arrivals if a.trip_id == "METRO1"), None)
        assert metro_arrival is not None
        # Metro should be static even though RT data exists for it
        assert metro_arrival.source == ArrivalSource.STATIC
        assert metro_arrival.delay_seconds is None

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_sorting_by_seconds(self, db_path: Path) -> None:
        """Test that arrivals are sorted numerically by seconds, not lexicographically."""
        realtime_service._config = _config_with_api_key()

        # Create RT data that reorders arrivals by delay
        # BUS1 at 08:10 with +15 min delay = 08:25
        # BUS2 at 08:20 with no delay = 08:20
        # So BUS2 should come before BUS1 after sorting
        trip_updates = TripUpdatesData(
            header=FeedHeader(gtfs_realtime_version="2.0", timestamp=1234567890),
            trip_updates=[
                TripUpdate(
                    trip=TripDescriptor(trip_id="BUS1"),
                    stop_time_update=[
                        StopTimeUpdate(
                            stop_id="51001",
                            arrival=StopTimeEvent(delay=900),  # 15 minutes late
                        )
                    ],
                )
            ],
            fetched_at=datetime.now(UTC),
        )

        with (
            patch.object(
                arrivals_service, "get_trip_updates", new=AsyncMock(return_value=trip_updates)
            ),
            patch.object(
                arrivals_service, "get_vehicle_positions", new=AsyncMock(return_value=None)
            ),
        ):
            response = await get_next_arrivals(
                stop_id="51001",
                start_time="08:00:00",
                end_time="09:00:00",
                db_path=db_path,
            )

        # Get bus arrivals only
        bus_arrivals = [a for a in response.arrivals if a.route_type == 3]
        assert len(bus_arrivals) == 2

        # BUS2 (08:20, no delay) should come before BUS1 (08:10 + 15 min = 08:25)
        assert bus_arrivals[0].trip_id == "BUS2"
        assert bus_arrivals[1].trip_id == "BUS1"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_include_realtime_false(self, db_path: Path) -> None:
        """Test that include_realtime=False skips RT fetch."""
        realtime_service._config = _config_with_api_key()

        # This should not be called
        get_trip_updates_mock = AsyncMock()
        get_vehicle_positions_mock = AsyncMock()

        with (
            patch.object(arrivals_service, "get_trip_updates", get_trip_updates_mock),
            patch.object(arrivals_service, "get_vehicle_positions", get_vehicle_positions_mock),
        ):
            response = await get_next_arrivals(
                stop_id="51001",
                start_time="08:00:00",
                end_time="09:00:00",
                db_path=db_path,
                include_realtime=False,
            )

        # RT functions should not have been called
        get_trip_updates_mock.assert_not_called()
        get_vehicle_positions_mock.assert_not_called()

        assert response.realtime_available is False
        assert response.realtime_count == 0
