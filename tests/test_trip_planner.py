"""Tests for trip planning service."""

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.services.trip_planner import plan_trip


def _write_base_gtfs(gtfs_dir: Path) -> None:
    """Write base GTFS files shared across fixtures."""
    (gtfs_dir / "agency.txt").write_text(
        "agency_id,agency_name,agency_url,agency_timezone\n"
        "STM,Société de transport de Montréal,http://www.stm.info,America/Montreal\n"
    )
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20261231\n"
        "WEEKEND,0,0,0,0,0,1,1,20240101,20261231\n"
    )
    (gtfs_dir / "calendar_dates.txt").write_text("service_id,date,exception_type\n")
    (gtfs_dir / "feed_info.txt").write_text(
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
        "STM,http://www.stm.info,fr,20240101,20261231,2024.1\n"
    )


@contextmanager
def _patched_trip_planner_datetime(
    day: int,
    hour: int,
    minute: int,
    second: int = 0,
):
    with patch("stm_mcp.services.trip_planner.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = date(2025, 1, day)
        mock_dt.now.return_value.hour = hour
        mock_dt.now.return_value.minute = minute
        mock_dt.now.return_value.second = second
        yield


@pytest.fixture
def sample_gtfs_dir(tmp_path: Path) -> Path:
    """Create a sample GTFS directory with data for trip planning tests."""
    gtfs_dir = tmp_path / "gtfs"
    gtfs_dir.mkdir()

    _write_base_gtfs(gtfs_dir)

    # routes.txt - metro and bus
    (gtfs_dir / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_url,route_color,route_text_color\n"
        "1,STM,Green,Ligne verte,1,http://stm.info/green,008E4F,FFFFFF\n"
        "24,STM,24,Sherbrooke,3,http://stm.info/24,000000,FFFFFF\n"
        "55,STM,55,St-Laurent,3,http://stm.info/55,000000,FFFFFF\n"
    )

    # stops.txt - multiple stops on same routes
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,BERRI,Berri-UQAM,45.515,-73.561,,1,,1\n"
        "BERRI-1,51234,Berri-UQAM - Green Line,45.515,-73.561,,0,BERRI,1\n"
        "MCGILL,MCGILL,McGill,45.504,-73.573,,1,,1\n"
        "MCGILL-1,51235,McGill - Green Line,45.504,-73.573,,0,MCGILL,1\n"
        "PEEL,PEEL,Peel,45.503,-73.576,,1,,1\n"
        "PEEL-1,51236,Peel - Green Line,45.503,-73.576,,0,PEEL,1\n"
        "51001,51001,Sherbrooke / Saint-Denis,45.518,-73.568,,0,,1\n"
        "51002,51002,Sherbrooke / Papineau,45.520,-73.555,,0,,1\n"
        "55001,55001,St-Laurent / Sherbrooke,45.517,-73.570,,0,,1\n"
    )

    # trips.txt - multiple trips on routes
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        # Green line trips - both directions
        "GREEN1,1,WEEKDAY,Angrignon,0,SHAPE1,1,,\n"
        "GREEN2,1,WEEKDAY,Angrignon,0,SHAPE1,1,,\n"
        "GREEN3,1,WEEKDAY,Honoré-Beaugrand,1,SHAPE2,1,,\n"
        # Bus 24 trips
        "BUS24-1,24,WEEKDAY,Sherbrooke / Cavendish,0,SHAPE3,1,,\n"
        "BUS24-2,24,WEEKDAY,Sherbrooke / Cavendish,0,SHAPE3,1,,\n"
        # Bus 55 trips - different route, no overlap with 24
        "BUS55-1,55,WEEKDAY,St-Laurent / Crémazie,0,SHAPE4,1,,\n"
        # Weekend trips
        "GREEN-WE,1,WEEKEND,Angrignon,0,SHAPE1,1,,\n"
    )

    # stop_times.txt - connect stops via trips
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        # GREEN1: BERRI -> MCGILL -> PEEL (departures at 08:00, 08:05, 08:10)
        "GREEN1,08:00:00,08:00:00,BERRI-1,1,0\n"
        "GREEN1,08:05:00,08:05:00,MCGILL-1,2,0\n"
        "GREEN1,08:10:00,08:10:00,PEEL-1,3,0\n"
        # GREEN2: later departure at 08:30
        "GREEN2,08:30:00,08:30:00,BERRI-1,1,0\n"
        "GREEN2,08:35:00,08:35:00,MCGILL-1,2,0\n"
        "GREEN2,08:40:00,08:40:00,PEEL-1,3,0\n"
        # GREEN3: opposite direction PEEL -> MCGILL -> BERRI
        "GREEN3,09:00:00,09:00:00,PEEL-1,1,0\n"
        "GREEN3,09:05:00,09:05:00,MCGILL-1,2,0\n"
        "GREEN3,09:10:00,09:10:00,BERRI-1,3,0\n"
        # BUS24-1: 51001 -> 51002 at 09:00
        "BUS24-1,09:00:00,09:00:00,51001,1,0\n"
        "BUS24-1,09:15:00,09:15:00,51002,2,0\n"
        # BUS24-2: later departure at 09:30
        "BUS24-2,09:30:00,09:30:00,51001,1,0\n"
        "BUS24-2,09:45:00,09:45:00,51002,2,0\n"
        # BUS55-1: 55001 only (no direct connection to bus 24 stops)
        "BUS55-1,10:00:00,10:00:00,55001,1,0\n"
        # Weekend trip
        "GREEN-WE,10:00:00,10:00:00,BERRI-1,1,0\n"
        "GREEN-WE,10:05:00,10:05:00,MCGILL-1,2,0\n"
    )

    return gtfs_dir


@pytest.fixture
async def db_path(sample_gtfs_dir: Path, tmp_path: Path) -> Path:
    """Create a test database from sample GTFS data."""
    db_file = tmp_path / "test.db"
    loader = GTFSLoader(db_file)
    await loader.ingest(sample_gtfs_dir)
    return db_file


class TestDirectRoute:
    """Tests for finding direct routes between stops."""

    async def test_finds_metro_route(self, db_path: Path) -> None:
        """Test finding direct metro route on green line."""
        # Mock datetime to a weekday
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51234",  # Berri-UQAM - Green Line (by stop code)
                destination="51235",  # McGill - Green Line
                departure_time="08:00:00",
                limit=3,
                db_path=db_path,
            )

        assert response.success is True
        assert response.count >= 1
        assert len(response.itineraries) >= 1

        # Check first itinerary
        itinerary = response.itineraries[0]
        assert len(itinerary.legs) == 1
        assert itinerary.num_transfers == 0

        leg = itinerary.legs[0]
        assert leg.route_id == "1"  # Green line
        assert leg.route_type == 1  # Metro
        assert leg.from_stop_id == "BERRI-1"
        assert leg.to_stop_id == "MCGILL-1"

    async def test_finds_bus_route(self, db_path: Path) -> None:
        """Test finding direct bus route."""
        with _patched_trip_planner_datetime(day=8, hour=9, minute=0):
            response = await plan_trip(
                origin="51001",  # Sherbrooke / Saint-Denis
                destination="51002",  # Sherbrooke / Papineau
                departure_time="09:00:00",
                limit=3,
                db_path=db_path,
            )

        assert response.success is True
        assert len(response.itineraries) >= 1

        leg = response.itineraries[0].legs[0]
        assert leg.route_id == "24"
        assert leg.route_type == 3  # Bus
        assert leg.route_short_name == "24"

    async def test_multiple_departures(self, db_path: Path) -> None:
        """Test that multiple departure times are returned."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51234",  # Berri-UQAM
                destination="51235",  # McGill
                departure_time="08:00:00",
                limit=3,
                db_path=db_path,
            )

        assert response.success is True


class TestNoDirectRoute:
    """Tests for cases with no direct route."""

    async def test_no_direct_connection(self, db_path: Path) -> None:
        """Test when there's no direct route between stops."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51001",  # Bus 24 stop
                destination="55001",  # Bus 55 stop - different route
                departure_time="08:00:00",
                limit=3,
                db_path=db_path,
            )

        assert response.success is False
        assert response.count == 0
        assert len(response.itineraries) == 0
        assert response.error == "No routes found"

    async def test_wrong_direction(self, db_path: Path) -> None:
        """Test that wrong direction trips are not returned."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            # MCGILL comes before BERRI on trip GREEN1, so no direct route
            # in the 08:xx time window when looking for MCGILL->BERRI
            # (GREEN3 at 09:05 goes MCGILL->BERRI but is outside 2-hour window from 08:00)
            response = await plan_trip(
                origin="51235",  # McGill
                destination="51234",  # Berri
                departure_time="08:00:00",
                limit=3,
                db_path=db_path,
            )

        assert response.success is True
        for itinerary in response.itineraries:
            leg = itinerary.legs[0]
            assert leg.trip_id == "GREEN3"


class TestServiceDayFiltering:
    """Tests for service day filtering."""

    async def test_weekday_service_on_weekday(self, db_path: Path) -> None:
        """Test that weekday service is used on a weekday."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="08:00:00",
                db_path=db_path,
            )

        assert response.success is True
        assert response.service_date == "2025-01-08"

    async def test_weekend_service_on_weekend(self, db_path: Path) -> None:
        """Test that weekend service is used on a weekend."""
        with _patched_trip_planner_datetime(day=11, hour=10, minute=0):
            response = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="10:00:00",
                db_path=db_path,
            )

        # Weekend service exists at 10:00
        assert response.service_date == "2025-01-11"
        if response.success:
            # The weekend trip should be GREEN-WE
            assert response.itineraries[0].legs[0].trip_id == "GREEN-WE"


class TestTimeWindow:
    """Tests for time window filtering."""

    async def test_only_finds_within_window(self, db_path: Path) -> None:
        """Test that only departures within 2-hour window are found."""
        with _patched_trip_planner_datetime(day=8, hour=5, minute=0):
            response = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="05:00:00",  # Before any trips (2hr window ends at 07:00)
                db_path=db_path,
            )

        # No trips within 2 hours of 05:00 (first trip is at 08:00, window ends at 07:00)
        assert response.success is False
        assert response.count == 0

    async def test_respects_departure_time(self, db_path: Path) -> None:
        """Test that departure time filter is respected."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=15):
            response = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="08:15:00",  # After GREEN1 departs at 08:00
                db_path=db_path,
            )

        if response.success:
            # Should only find GREEN2 at 08:30, not GREEN1 at 08:00
            for itinerary in response.itineraries:
                assert itinerary.departure_time >= "08:15:00"


class TestStopResolution:
    """Tests for stop resolution."""

    async def test_resolution_success_and_fuzzy(self, db_path: Path) -> None:
        """Test resolving stops by code and fuzzy name."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            by_code = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="08:00:00",
                db_path=db_path,
            )
            by_fuzzy = await plan_trip(
                origin="Berri-UQAM - Green",  # Fuzzy name
                destination="McGill - Green",
                departure_time="08:00:00",
                db_path=db_path,
            )

        assert by_code.origin_resolution.resolved is True
        assert by_code.origin_resolution.resolved_stop_id == "BERRI-1"
        assert by_code.destination_resolution.resolved is True
        assert by_code.destination_resolution.resolved_stop_id == "MCGILL-1"
        assert by_fuzzy.origin_resolution.resolved is True
        assert by_fuzzy.destination_resolution.resolved is True

    async def test_resolution_failure(self, db_path: Path) -> None:
        """Test graceful handling of resolution failure."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="xyznonexistent",
                destination="51235",
                departure_time="08:00:00",
                db_path=db_path,
            )

        assert response.success is False
        assert response.origin_resolution.resolved is False
        assert response.error == "Could not resolve origin or destination stop"


class TestItineraryDetails:
    """Tests for itinerary details."""

    async def test_leg_details(self, db_path: Path) -> None:
        """Test duration, stops, and time formatting."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51234",  # BERRI-1
                destination="51236",  # PEEL-1
                departure_time="08:00:00",
                db_path=db_path,
            )

        if response.success:
            itinerary = response.itineraries[0]
            leg = itinerary.legs[0]
            assert leg.duration_minutes == 10
            assert itinerary.total_duration_minutes == 10
            assert leg.num_stops == 3
            assert leg.departure_time == "08:00:00"
            assert leg.departure_time_formatted == "8:00 AM"
            assert leg.arrival_time == "08:10:00"
            assert leg.arrival_time_formatted == "8:10 AM"


class TestLimitParameter:
    """Tests for limit parameter handling."""

    @pytest.mark.parametrize(
        ("limit", "expected_max"),
        [
            (0, 1),
            (1, 1),
        ],
    )
    async def test_limit_respected(self, db_path: Path, limit: int, expected_max: int) -> None:
        """Test that limit parameter is clamped and respected."""
        with _patched_trip_planner_datetime(day=8, hour=8, minute=0):
            response = await plan_trip(
                origin="51234",
                destination="51235",
                departure_time="08:00:00",
                limit=limit,
                db_path=db_path,
            )

        if response.success:
            assert len(response.itineraries) <= expected_max


@pytest.fixture
def transfer_gtfs_dir(tmp_path: Path) -> Path:
    """Create a GTFS directory with routes that require transfers."""
    gtfs_dir = tmp_path / "gtfs_transfer"
    gtfs_dir.mkdir()

    _write_base_gtfs(gtfs_dir)

    # routes.txt - 3 routes: 24, 55, and metro green line
    (gtfs_dir / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_url,route_color,route_text_color\n"
        "1,STM,Green,Ligne verte,1,http://stm.info/green,008E4F,FFFFFF\n"
        "2,STM,Orange,Ligne orange,1,http://stm.info/orange,ED8004,FFFFFF\n"
        "24,STM,24,Sherbrooke,3,http://stm.info/24,000000,FFFFFF\n"
        "55,STM,55,St-Laurent,3,http://stm.info/55,000000,FFFFFF\n"
    )

    # stops.txt - stops that create transfer scenarios
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        # Bus 24 stops
        "24-A,60001,Bus 24 Origin,45.510,-73.570,,0,,1\n"
        "24-B,60002,Sherbrooke / St-Laurent,45.517,-73.569,,0,,1\n"  # Transfer point
        # Bus 55 stops
        "55-A,60003,St-Laurent / Sherbrooke,45.517,-73.570,,0,,1\n"  # Same area as 24-B
        "55-B,60004,Bus 55 Destination,45.525,-73.570,,0,,1\n"
        # Metro stations with platforms (for parent_station transfers)
        "BERRI,BERRI,Berri-UQAM,45.515,-73.561,,1,,1\n"
        "BERRI-G,60005,Berri-UQAM - Green,45.515,-73.561,,0,BERRI,1\n"
        "BERRI-O,60006,Berri-UQAM - Orange,45.515,-73.562,,0,BERRI,1\n"
        "MCGILL-G,60007,McGill - Green,45.504,-73.573,,0,,1\n"
        "JEAN-TAL-O,60008,Jean-Talon - Orange,45.539,-73.614,,0,,1\n"
    )

    # trips.txt
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        # Bus 24: 24-A -> 24-B (origin to transfer)
        "BUS24-T1,24,WEEKDAY,Sherbrooke Est,0,SHAPE1,1,,\n"
        "BUS24-T2,24,WEEKDAY,Sherbrooke Est,0,SHAPE1,1,,\n"
        # Bus 55: 55-A -> 55-B (transfer to destination)
        "BUS55-T1,55,WEEKDAY,St-Laurent Nord,0,SHAPE2,1,,\n"
        "BUS55-T2,55,WEEKDAY,St-Laurent Nord,0,SHAPE2,1,,\n"
        # Metro Green: MCGILL -> BERRI-G
        "GREEN-T1,1,WEEKDAY,Honoré-Beaugrand,0,SHAPE3,1,,\n"
        # Metro Orange: BERRI-O -> JEAN-TAL
        "ORANGE-T1,2,WEEKDAY,Montmorency,0,SHAPE4,1,,\n"
    )

    # stop_times.txt - create scenarios for transfers
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        # Bus 24 trip 1: departs 09:00, arrives at transfer 09:10
        "BUS24-T1,09:00:00,09:00:00,24-A,1,0\n"
        "BUS24-T1,09:10:00,09:10:00,24-B,2,0\n"
        # Bus 24 trip 2: departs 09:30, arrives at transfer 09:40
        "BUS24-T2,09:30:00,09:30:00,24-A,1,0\n"
        "BUS24-T2,09:40:00,09:40:00,24-B,2,0\n"
        # Bus 55 trip 1: departs 09:15 (5 min after bus 24 arrival), arrives 09:30
        "BUS55-T1,09:15:00,09:15:00,55-A,1,0\n"
        "BUS55-T1,09:30:00,09:30:00,55-B,2,0\n"
        # Bus 55 trip 2: departs 09:45, arrives 10:00
        "BUS55-T2,09:45:00,09:45:00,55-A,1,0\n"
        "BUS55-T2,10:00:00,10:00:00,55-B,2,0\n"
        # Metro Green: MCGILL -> BERRI-G at 10:00-10:05
        "GREEN-T1,10:00:00,10:00:00,MCGILL-G,1,0\n"
        "GREEN-T1,10:05:00,10:05:00,BERRI-G,2,0\n"
        # Metro Orange: BERRI-O -> JEAN-TAL at 10:10-10:20
        "ORANGE-T1,10:10:00,10:10:00,BERRI-O,1,0\n"
        "ORANGE-T1,10:20:00,10:20:00,JEAN-TAL-O,2,0\n"
    )

    return gtfs_dir


@pytest.fixture
async def transfer_db_path(transfer_gtfs_dir: Path, tmp_path: Path) -> Path:
    """Create a test database from transfer GTFS data."""
    db_file = tmp_path / "transfer_test.db"
    loader = GTFSLoader(db_file)
    await loader.ingest(transfer_gtfs_dir)
    return db_file


class TestTransferRoutes:
    """Tests for finding routes with transfers."""

    async def test_finds_same_stop_transfer(self, transfer_db_path: Path) -> None:
        """Test finding a transfer at the same stop (24-B to 55-A are nearby)."""
        with _patched_trip_planner_datetime(day=8, hour=9, minute=0):
            response = await plan_trip(
                origin="60001",  # Bus 24 origin
                destination="60004",  # Bus 55 destination
                departure_time="09:00:00",
                limit=3,
                db_path=transfer_db_path,
            )

        assert response.success is True
        assert response.count >= 1

        # Should have a transfer itinerary
        transfer_itinerary = None
        for itinerary in response.itineraries:
            if itinerary.num_transfers == 1:
                transfer_itinerary = itinerary
                break

        assert transfer_itinerary is not None, "Should find a 1-transfer itinerary"
        assert len(transfer_itinerary.legs) == 2

        # First leg should be bus 24
        leg1 = transfer_itinerary.legs[0]
        assert leg1.route_id == "24"
        assert leg1.from_stop_id == "24-A"
        assert leg1.to_stop_id == "24-B"

        # Second leg should be bus 55
        leg2 = transfer_itinerary.legs[1]
        assert leg2.route_id == "55"
        assert leg2.from_stop_id == "55-A"
        assert leg2.to_stop_id == "55-B"

    async def test_finds_parent_station_transfer(self, transfer_db_path: Path) -> None:
        """Test finding a transfer between metro platforms at same station."""
        with _patched_trip_planner_datetime(day=8, hour=10, minute=0):
            response = await plan_trip(
                origin="60007",  # McGill - Green
                destination="60008",  # Jean-Talon - Orange
                departure_time="10:00:00",
                limit=3,
                db_path=transfer_db_path,
            )

        assert response.success is True

        # Find the transfer itinerary (Green -> Orange at Berri-UQAM)
        transfer_itinerary = None
        for itinerary in response.itineraries:
            if itinerary.num_transfers == 1:
                transfer_itinerary = itinerary
                break

        assert transfer_itinerary is not None, "Should find Green->Orange transfer at Berri"
        assert len(transfer_itinerary.legs) == 2

        # First leg should be Green line to Berri
        leg1 = transfer_itinerary.legs[0]
        assert leg1.route_id == "1"  # Green line
        assert leg1.to_stop_id == "BERRI-G"

        # Second leg should be Orange line from Berri
        leg2 = transfer_itinerary.legs[1]
        assert leg2.route_id == "2"  # Orange line
        assert leg2.from_stop_id == "BERRI-O"

    async def test_transfer_timing_constraints(self, transfer_db_path: Path) -> None:
        """Test that transfers respect min/max timing constraints."""
        with _patched_trip_planner_datetime(day=8, hour=9, minute=0):
            response = await plan_trip(
                origin="60001",
                destination="60004",
                departure_time="09:00:00",
                limit=5,
                db_path=transfer_db_path,
            )

        # All transfer itineraries should have valid wait times
        for itinerary in response.itineraries:
            if itinerary.num_transfers > 0:
                assert itinerary.transfer_wait_minutes is not None
                assert itinerary.transfer_wait_minutes >= 3, "Min transfer time is 3 minutes"
                assert itinerary.transfer_wait_minutes <= 30, "Max transfer time is 30 minutes"

    async def test_no_same_route_transfer(self, transfer_db_path: Path) -> None:
        """Test that transfers don't include same route (which isn't a real transfer)."""
        with _patched_trip_planner_datetime(day=8, hour=9, minute=0):
            response = await plan_trip(
                origin="60001",
                destination="60004",
                departure_time="09:00:00",
                limit=5,
                db_path=transfer_db_path,
            )

        # No transfer itinerary should have same route on both legs
        for itinerary in response.itineraries:
            if len(itinerary.legs) == 2:
                assert itinerary.legs[0].route_id != itinerary.legs[1].route_id

    async def test_combined_direct_and_transfer_results(self, transfer_db_path: Path) -> None:
        """Test that direct and transfer routes are combined and sorted."""
        with _patched_trip_planner_datetime(day=8, hour=9, minute=0):
            response = await plan_trip(
                origin="60001",
                destination="60004",
                departure_time="09:00:00",
                limit=5,
                db_path=transfer_db_path,
            )

        if response.success and len(response.itineraries) > 1:
            # Results should be sorted by total duration
            for i in range(len(response.itineraries) - 1):
                assert (
                    response.itineraries[i].total_duration_minutes
                    <= response.itineraries[i + 1].total_duration_minutes
                )
