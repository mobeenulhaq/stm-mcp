"""Tests for fuzzy route matching."""

from pathlib import Path

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.matching import SearchIndex
from stm_mcp.matching.models import MatchConfidence, MatchType
from stm_mcp.matching.route_matcher import resolve_route


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

    # routes.txt - metro lines and bus routes
    (gtfs_dir / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_url,route_color,route_text_color\n"
        "1,STM,Green,Ligne verte,1,,,\n"
        "2,STM,Orange,Ligne orange,1,,,\n"
        "4,STM,Yellow,Ligne jaune,1,,,\n"
        "5,STM,Blue,Ligne bleue,1,,,\n"
        "24,STM,24,Sherbrooke,3,,,\n"
        "80,STM,80,Avenue du Parc,3,,,\n"
        "747,STM,747,YUL Aéroport Montréal-Trudeau / Centre-Ville,3,,,\n"
    )

    # stops.txt
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,51001,Berri-UQAM,45.515,-73.561,,0,,1\n"
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
        "TRIP2,24,WEEKDAY,Sherbrooke / Cavendish,0,,,\n"
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


class TestResolveRouteNumber:
    """Tests for route number matching."""

    async def test_exact_route_number(self, db_path: Path) -> None:
        """Test exact route number matching."""
        response = await resolve_route("24", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.route_short_name == "24"
        assert response.best_match.score == 100.0
        assert response.best_match.confidence == MatchConfidence.EXACT
        assert response.best_match.match_type == MatchType.NUMBER_EXACT

    async def test_route_number_with_prefix(self, db_path: Path) -> None:
        """Test route number with 'route' prefix."""
        response = await resolve_route("route 24", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.route_short_name == "24"
        assert response.best_match.match_type == MatchType.NUMBER_EXACT


class TestResolveRouteMetroAlias:
    """Tests for metro line alias matching."""

    async def test_green_line_english(self, db_path: Path) -> None:
        """Test Green line English alias."""
        response = await resolve_route("green line", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.route_id == "1"
        assert response.best_match.confidence == MatchConfidence.EXACT
        assert response.best_match.match_type == MatchType.METRO_ALIAS

    async def test_green_line_french(self, db_path: Path) -> None:
        """Test Green line French alias."""
        response = await resolve_route("ligne verte", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.route_id == "1"


class TestResolveRouteFuzzy:
    """Tests for fuzzy route name matching."""

    async def test_fuzzy_match_route_name(self, db_path: Path) -> None:
        """Test fuzzy matching on route long name."""
        response = await resolve_route("Sherbrooke", db_path=db_path)

        assert len(response.matches) > 0
        # Should find route 24 (Sherbrooke)
        match_names = [m.route_long_name for m in response.matches if m.route_long_name]
        assert any("Sherbrooke" in name for name in match_names)

    async def test_fuzzy_match_aeroport(self, db_path: Path) -> None:
        """Test fuzzy matching airport route."""
        response = await resolve_route("aeroport", db_path=db_path)

        # Should find route 747 (Aéroport)
        assert len(response.matches) > 0
        assert any(m.route_short_name == "747" for m in response.matches)


class TestResolveRouteOptions:
    """Tests for resolve_route options."""

    async def test_empty_query(self, db_path: Path) -> None:
        """Test that empty query returns empty results."""
        response = await resolve_route("", db_path=db_path)

        assert response.resolved is False
        assert response.best_match is None
        assert len(response.matches) == 0


class TestResolveRouteResolution:
    """Tests for resolution status."""

    async def test_route_type_preserved(self, db_path: Path) -> None:
        """Test that route_type is correctly preserved."""
        # Metro
        metro_response = await resolve_route("green line", db_path=db_path)
        assert metro_response.best_match is not None
        assert metro_response.best_match.route_type == 1  # Metro

        # Bus
        bus_response = await resolve_route("24", db_path=db_path)
        assert bus_response.best_match is not None
        assert bus_response.best_match.route_type == 3  # Bus
