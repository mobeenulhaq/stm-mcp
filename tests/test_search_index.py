"""Tests for search index loading and refresh."""

from pathlib import Path

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.matching.search_index import SearchIndex


@pytest.fixture
def sample_gtfs_dir(tmp_path: Path) -> Path:
    """Create a sample GTFS directory with test data."""
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
        "1,STM,Green,Ligne verte,1,,,\n"
        "24,STM,24,Sherbrooke,3,,,\n"
    )

    # stops.txt
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,51001,Berri-UQAM,45.515,-73.561,,0,,1\n"
        "MCGILL,52001,McGill,45.503,-73.572,,0,,1\n"
        "STATION,,,45.5,-73.5,,1,,\n"
    )

    # calendar.txt
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20261231\n"
    )

    # calendar_dates.txt
    (gtfs_dir / "calendar_dates.txt").write_text("service_id,date,exception_type\n")

    # trips.txt
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        "TRIP1,1,WEEKDAY,Angrignon,0,,,\n"
        "TRIP2,1,WEEKDAY,Honoré-Beaugrand,1,,,\n"
        "TRIP3,24,WEEKDAY,Downtown,0,,,\n"
    )

    # stop_times.txt
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "TRIP1,08:00:00,08:00:00,BERRI,1,0\n"
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
    # Clear any cached index from previous tests
    await SearchIndex.invalidate()
    return db_file


class TestSearchIndexLoading:
    """Tests for index loading."""

    async def test_get_instance_loads_data(self, db_path: Path) -> None:
        """Test that get_instance loads data from database."""
        index = await SearchIndex.get_instance(db_path)

        assert len(index.stops) > 0
        assert len(index.routes) > 0
        assert len(index.headsigns) > 0

    async def test_singleton_pattern(self, db_path: Path) -> None:
        """Test that get_instance returns same instance."""
        index1 = await SearchIndex.get_instance(db_path)
        index2 = await SearchIndex.get_instance(db_path)

        assert index1 is index2

    async def test_excludes_stations(self, db_path: Path) -> None:
        """Test that stations (location_type=1) are excluded from stops."""
        index = await SearchIndex.get_instance(db_path)

        # STATION has location_type=1, should be excluded
        station_ids = [s.stop_id for s in index.stops]
        assert "STATION" not in station_ids


class TestSearchIndexStops:
    """Tests for stop indexing."""

    async def test_stops_by_code_lookup(self, db_path: Path) -> None:
        """Test O(1) lookup by stop code."""
        index = await SearchIndex.get_instance(db_path)

        assert "51001" in index.stops_by_code
        stop = index.stops_by_code["51001"]
        assert stop.stop_name == "Berri-UQAM"

    async def test_stops_by_id_lookup(self, db_path: Path) -> None:
        """Test O(1) lookup by stop ID."""
        index = await SearchIndex.get_instance(db_path)

        assert "BERRI" in index.stops_by_id
        stop = index.stops_by_id["BERRI"]
        assert stop.stop_name == "Berri-UQAM"

    async def test_normalized_name_precomputed(self, db_path: Path) -> None:
        """Test that normalized names are pre-computed."""
        index = await SearchIndex.get_instance(db_path)

        stop = index.stops_by_id["BERRI"]
        assert stop.normalized_name == "berri-uqam"


class TestSearchIndexRoutes:
    """Tests for route indexing."""

    async def test_routes_by_id_lookup(self, db_path: Path) -> None:
        """Test O(1) lookup by route ID."""
        index = await SearchIndex.get_instance(db_path)

        assert "1" in index.routes_by_id
        route = index.routes_by_id["1"]
        assert route.route_short_name == "Green"

    async def test_routes_by_number_lookup(self, db_path: Path) -> None:
        """Test O(1) lookup by route number."""
        index = await SearchIndex.get_instance(db_path)

        assert "24" in index.routes_by_number
        route = index.routes_by_number["24"]
        assert route.route_long_name == "Sherbrooke"

    async def test_route_type_preserved(self, db_path: Path) -> None:
        """Test that route_type is preserved."""
        index = await SearchIndex.get_instance(db_path)

        metro = index.routes_by_id["1"]
        assert metro.route_type == 1  # Metro

        bus = index.routes_by_number["24"]
        assert bus.route_type == 3  # Bus


class TestSearchIndexHeadsigns:
    """Tests for headsign indexing."""

    async def test_headsigns_by_route_lookup(self, db_path: Path) -> None:
        """Test lookup of headsigns by route."""
        index = await SearchIndex.get_instance(db_path)

        assert "1" in index.headsigns_by_route
        headsigns = index.headsigns_by_route["1"]
        assert len(headsigns) >= 2  # Angrignon and Honoré-Beaugrand

    async def test_headsign_direction_id(self, db_path: Path) -> None:
        """Test that direction_id is preserved."""
        index = await SearchIndex.get_instance(db_path)

        headsigns = index.headsigns_by_route["1"]
        direction_ids = {h.direction_id for h in headsigns}
        assert 0 in direction_ids
        assert 1 in direction_ids

    async def test_normalized_headsign_precomputed(self, db_path: Path) -> None:
        """Test that normalized headsigns are pre-computed."""
        index = await SearchIndex.get_instance(db_path)

        headsigns = index.headsigns_by_route["1"]
        angrignon = next(h for h in headsigns if "Angrignon" in h.headsign)
        assert angrignon.normalized_headsign == "angrignon"


class TestSearchIndexInvalidate:
    """Tests for index invalidation."""

    async def test_invalidate_clears_cache(self, db_path: Path) -> None:
        """Test that invalidate clears the cached instance."""
        index1 = await SearchIndex.get_instance(db_path)
        await SearchIndex.invalidate()
        index2 = await SearchIndex.get_instance(db_path)

        # Should be different instances
        assert index1 is not index2

    async def test_reload_returns_fresh_instance(self, db_path: Path) -> None:
        """Test that reload returns a fresh instance."""
        index1 = await SearchIndex.get_instance(db_path)
        index2 = await SearchIndex.reload(db_path)

        assert index1 is not index2


class TestSearchIndexAfterIngestion:
    """Tests for index refresh after GTFS ingestion."""

    async def test_ingest_invalidates_index(
        self, sample_gtfs_dir: Path, tmp_path: Path
    ) -> None:
        """Test that GTFS ingestion invalidates the search index."""
        db_file = tmp_path / "test2.db"
        loader = GTFSLoader(db_file)

        # First ingestion
        await loader.ingest(sample_gtfs_dir)
        await SearchIndex.invalidate()  # Clear from fixture setup
        index1 = await SearchIndex.get_instance(db_file)

        # Modify GTFS data
        stops_file = sample_gtfs_dir / "stops.txt"
        stops_content = stops_file.read_text()
        stops_file.write_text(
            stops_content + "NEW,99999,New Stop,45.5,-73.5,,0,,1\n"
        )

        # Second ingestion should invalidate index
        await loader.ingest(sample_gtfs_dir)
        index2 = await SearchIndex.get_instance(db_file)

        # Should be different instances
        assert index1 is not index2

        # New stop should be in index2
        assert "99999" in index2.stops_by_code
