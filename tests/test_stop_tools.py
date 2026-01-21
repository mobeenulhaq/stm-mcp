"""Tests for stop search tools."""

from pathlib import Path

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.services.stop_service import (
    get_stop_by_id,
    haversine_distance,
    search_stops,
)


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

    # routes.txt
    (gtfs_dir / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_url,route_color,route_text_color\n"
        "1,STM,Green,Ligne verte,1,http://stm.info/green,008E4F,FFFFFF\n"
        "24,STM,24,Sherbrooke,3,http://stm.info/24,000000,FFFFFF\n"
    )

    # stops.txt - various stops for testing
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,BERRI,Berri-UQAM,45.515,-73.561,,1,,1\n"
        "BERRI-1,51234,Berri-UQAM - Green Line,45.515,-73.561,,0,BERRI,1\n"
        "51001,51001,Sherbrooke / Saint-Denis,45.518,-73.568,,0,,1\n"
        "51002,51002,Sherbrooke / Berri,45.517,-73.563,,0,,1\n"
        "52001,52001,Mont-Royal / Saint-Denis,45.524,-73.582,,0,,1\n"
        "MCGILL,MCGILL,McGill,45.503,-73.572,,1,,1\n"
    )

    # calendar.txt
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20261231\n"
        "WEEKEND,0,0,0,0,0,1,1,20240101,20261231\n"
    )

    # calendar_dates.txt
    (gtfs_dir / "calendar_dates.txt").write_text(
        "service_id,date,exception_type\nWEEKDAY,20240101,2\nWEEKEND,20240101,1\n"
    )

    # trips.txt
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        "TRIP1,1,WEEKDAY,Angrignon,0,SHAPE1,1,,\n"
        "TRIP2,24,WEEKDAY,Sherbrooke / Cavendish,0,SHAPE2,1,,\n"
    )

    # stop_times.txt
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "TRIP1,08:00:00,08:00:00,BERRI-1,1,0\n"
        "TRIP1,08:05:00,08:05:00,51001,2,0\n"
        "TRIP2,09:00:00,09:00:00,51001,1,0\n"
    )

    # feed_info.txt
    (gtfs_dir / "feed_info.txt").write_text(
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
        "STM,http://www.stm.info,fr,20240101,20261231,2024.1\n"
    )

    return gtfs_dir


@pytest.fixture
async def db_path(sample_gtfs_dir: Path, tmp_path: Path) -> Path:
    """Create a test database from sample GTFS data."""
    db_file = tmp_path / "test.db"
    loader = GTFSLoader(db_file)
    await loader.ingest(sample_gtfs_dir)
    return db_file


class TestHaversineDistance:
    """Tests for haversine distance calculation."""

    def test_same_point(self) -> None:
        """Test distance between same point is zero."""
        distance = haversine_distance(45.5, -73.5, 45.5, -73.5)
        assert distance == 0.0

    def test_known_distance(self) -> None:
        """Test a known distance between two Montreal points."""
        # Berri-UQAM to McGill is approximately 1.3-1.5 km
        distance = haversine_distance(45.515, -73.561, 45.503, -73.572)
        assert 1200 < distance < 1600  # Approximately 1.4 km

    def test_symmetric(self) -> None:
        """Test that distance is symmetric."""
        d1 = haversine_distance(45.515, -73.561, 45.503, -73.572)
        d2 = haversine_distance(45.503, -73.572, 45.515, -73.561)
        assert abs(d1 - d2) < 0.001


class TestSearchStopsByText:
    """Tests for text-based stop search."""

    async def test_search_by_name(self, db_path: Path) -> None:
        """Test searching stops by name."""
        response = await search_stops(query="Berri", db_path=db_path)

        assert response.count >= 2
        for stop in response.stops:
            assert "Berri" in stop.stop_name or "BERRI" in stop.stop_name.upper()

    async def test_search_case_insensitive(self, db_path: Path) -> None:
        """Test that search is case-insensitive."""
        response1 = await search_stops(query="berri", db_path=db_path)
        response2 = await search_stops(query="BERRI", db_path=db_path)

        assert response1.count == response2.count

    async def test_search_partial_match(self, db_path: Path) -> None:
        """Test partial name matching."""
        response = await search_stops(query="Sherbrooke", db_path=db_path)

        assert response.count >= 2
        for stop in response.stops:
            assert "Sherbrooke" in stop.stop_name

    async def test_search_no_results(self, db_path: Path) -> None:
        """Test search with no results."""
        response = await search_stops(query="NONEXISTENT", db_path=db_path)

        assert response.count == 0
        assert len(response.stops) == 0

    async def test_search_with_limit(self, db_path: Path) -> None:
        """Test that limit is respected."""
        response = await search_stops(query="S", limit=2, db_path=db_path)

        assert response.count <= 2


class TestSearchStopsByCode:
    """Tests for stop code search."""

    async def test_search_by_exact_code(self, db_path: Path) -> None:
        """Test searching by exact stop code."""
        response = await search_stops(stop_code="51001", db_path=db_path)

        assert response.count == 1
        assert response.stops[0].stop_code == "51001"
        assert response.stops[0].stop_name == "Sherbrooke / Saint-Denis"

    async def test_search_code_not_found(self, db_path: Path) -> None:
        """Test searching for non-existent stop code."""
        response = await search_stops(stop_code="99999", db_path=db_path)

        assert response.count == 0


class TestSearchStopsByLocation:
    """Tests for geographic stop search."""

    async def test_search_by_location(self, db_path: Path) -> None:
        """Test searching stops near a location."""
        # Search near Berri-UQAM
        response = await search_stops(
            lat=45.515,
            lon=-73.561,
            radius_meters=1000,
            db_path=db_path,
        )

        assert response.count > 0
        # Results should be sorted by distance
        for i in range(len(response.stops) - 1):
            if response.stops[i].distance_meters and response.stops[i + 1].distance_meters:
                assert response.stops[i].distance_meters <= response.stops[i + 1].distance_meters

    async def test_search_includes_distance(self, db_path: Path) -> None:
        """Test that geo search results include distance."""
        response = await search_stops(
            lat=45.515,
            lon=-73.561,
            radius_meters=500,
            db_path=db_path,
        )

        for stop in response.stops:
            assert stop.distance_meters is not None
            assert stop.distance_meters >= 0

    async def test_search_respects_radius(self, db_path: Path) -> None:
        """Test that results are within radius."""
        response = await search_stops(
            lat=45.515,
            lon=-73.561,
            radius_meters=100,
            db_path=db_path,
        )

        for stop in response.stops:
            assert stop.distance_meters is not None
            assert stop.distance_meters <= 100

    async def test_search_small_radius_fewer_results(self, db_path: Path) -> None:
        """Test that smaller radius returns fewer results."""
        response_large = await search_stops(
            lat=45.515,
            lon=-73.561,
            radius_meters=2000,
            db_path=db_path,
        )
        response_small = await search_stops(
            lat=45.515,
            lon=-73.561,
            radius_meters=100,
            db_path=db_path,
        )

        assert response_small.count <= response_large.count


class TestGetStopById:
    """Tests for getting a single stop by ID."""

    async def test_get_existing_stop(self, db_path: Path) -> None:
        """Test getting an existing stop."""
        stop = await get_stop_by_id("51001", db_path=db_path)

        assert stop is not None
        assert stop.stop_id == "51001"
        assert stop.stop_name == "Sherbrooke / Saint-Denis"

    async def test_get_nonexistent_stop(self, db_path: Path) -> None:
        """Test getting a non-existent stop returns None."""
        stop = await get_stop_by_id("NONEXISTENT", db_path=db_path)

        assert stop is None


class TestSearchStopsValidation:
    """Tests for input validation."""

    async def test_no_params_raises_error(self, db_path: Path) -> None:
        """Test that search without parameters raises ValueError."""
        with pytest.raises(ValueError, match="At least one search parameter required"):
            await search_stops(db_path=db_path)

    async def test_geo_search_priority(self, db_path: Path) -> None:
        """Test that geo search takes priority when multiple params provided."""
        # Provide both query and location - location should be used
        response = await search_stops(
            query="McGill",  # This would match only McGill
            lat=45.515,  # But this is at Berri
            lon=-73.561,
            radius_meters=500,
            db_path=db_path,
        )

        # Results should be near Berri, not specifically McGill
        # All results should have distance_meters (geo search characteristic)
        for stop in response.stops:
            assert stop.distance_meters is not None
