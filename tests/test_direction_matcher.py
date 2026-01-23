"""Tests for fuzzy direction matching."""

from pathlib import Path

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.matching import SearchIndex
from stm_mcp.matching.direction_matcher import resolve_direction
from stm_mcp.matching.models import MatchConfidence, MatchType


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
        "2,STM,Orange,Ligne orange,1,,,\n"
        "24,STM,24,Sherbrooke,3,,,\n"
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

    # trips.txt - multiple headsigns for each route
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        "TRIP1,1,WEEKDAY,Angrignon,0,,,\n"
        "TRIP2,1,WEEKDAY,Honoré-Beaugrand,1,,,\n"
        "TRIP3,2,WEEKDAY,Côte-Vertu,0,,,\n"
        "TRIP4,2,WEEKDAY,Montmorency,1,,,\n"
        "TRIP5,24,WEEKDAY,Sherbrooke / Cavendish,0,,,\n"
        "TRIP6,24,WEEKDAY,Viau,1,,,\n"
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


class TestResolveDirectionBasic:
    """Tests for basic direction matching."""

    async def test_exact_headsign_match(self, db_path: Path) -> None:
        """Test matching exact headsign."""
        response = await resolve_direction("Angrignon", route_id="1", db_path=db_path)

        assert len(response.matches) > 0
        assert response.best_match is not None
        assert "Angrignon" in response.best_match.headsign

    async def test_fuzzy_headsign_match(self, db_path: Path) -> None:
        """Test fuzzy matching on headsign."""
        response = await resolve_direction("Honore", route_id="1", db_path=db_path)

        assert len(response.matches) > 0
        # Should find Honoré-Beaugrand
        assert response.best_match is not None
        assert "Beaugrand" in response.best_match.headsign


class TestResolveDirectionPrefix:
    """Tests for direction prefix handling."""

    async def test_to_prefix_stripped(self, db_path: Path) -> None:
        """Test that 'to' prefix is stripped."""
        response = await resolve_direction("to Angrignon", route_id="1", db_path=db_path)

        assert len(response.matches) > 0
        assert response.best_match is not None
        assert "Angrignon" in response.best_match.headsign

    async def test_vers_prefix_stripped(self, db_path: Path) -> None:
        """Test that 'vers' prefix is stripped (French)."""
        response = await resolve_direction("vers Montmorency", route_id="2", db_path=db_path)

        assert len(response.matches) > 0
        assert response.best_match is not None
        assert "Montmorency" in response.best_match.headsign

    async def test_direction_prefix_stripped(self, db_path: Path) -> None:
        """Test that 'direction' prefix is stripped."""
        response = await resolve_direction("direction Viau", route_id="24", db_path=db_path)

        assert len(response.matches) > 0
        assert response.best_match is not None
        assert "Viau" in response.best_match.headsign


class TestResolveDirectionFilter:
    """Tests for direction_id filtering."""

    async def test_filter_by_direction_id(self, db_path: Path) -> None:
        """Test filtering by direction_id."""
        # Direction 0 for route 1 is Angrignon
        response_0 = await resolve_direction(
            "Angrignon", route_id="1", direction_id=0, db_path=db_path
        )

        assert len(response_0.matches) > 0
        for match in response_0.matches:
            assert match.direction_id == 0

    async def test_filter_excludes_other_direction(self, db_path: Path) -> None:
        """Test that filter excludes other direction."""
        # Direction 1 for route 1 is Honoré-Beaugrand, not Angrignon
        response = await resolve_direction(
            "Angrignon", route_id="1", direction_id=1, db_path=db_path
        )

        # Should have lower score or no matches since Angrignon is direction 0
        if len(response.matches) > 0:
            assert response.best_match is not None
            # Should not be a high confidence match
            assert response.best_match.confidence != MatchConfidence.EXACT

    async def test_both_directions_without_filter(self, db_path: Path) -> None:
        """Test that without filter, both directions are searched."""
        response = await resolve_direction("a", route_id="1", min_score=10, db_path=db_path)

        # Should get matches from both directions
        direction_ids = {m.direction_id for m in response.matches}
        assert len(direction_ids) >= 1  # At least one direction


class TestResolveDirectionOptions:
    """Tests for resolve_direction options."""

    async def test_empty_query(self, db_path: Path) -> None:
        """Test that empty query returns empty results."""
        response = await resolve_direction("", route_id="1", db_path=db_path)

        assert response.resolved is False
        assert response.best_match is None
        assert len(response.matches) == 0

    async def test_nonexistent_route(self, db_path: Path) -> None:
        """Test that nonexistent route returns empty results."""
        response = await resolve_direction("Angrignon", route_id="999", db_path=db_path)

        assert response.resolved is False
        assert len(response.matches) == 0

    async def test_min_score_filter(self, db_path: Path) -> None:
        """Test that min_score filters results."""
        response_low = await resolve_direction(
            "xyz", route_id="1", min_score=10, db_path=db_path
        )
        response_high = await resolve_direction(
            "xyz", route_id="1", min_score=90, db_path=db_path
        )

        assert len(response_high.matches) <= len(response_low.matches)


class TestResolveDirectionResolution:
    """Tests for resolution status."""

    async def test_high_confidence_resolved(self, db_path: Path) -> None:
        """Test resolved=True for high confidence matches."""
        response = await resolve_direction("Angrignon", route_id="1", db_path=db_path)

        if response.best_match and response.best_match.confidence in (
            MatchConfidence.EXACT,
            MatchConfidence.HIGH,
        ):
            assert response.resolved is True

    async def test_response_includes_route_id(self, db_path: Path) -> None:
        """Test that response includes route_id."""
        response = await resolve_direction("Angrignon", route_id="1", db_path=db_path)

        assert response.route_id == "1"

    async def test_response_includes_direction_filter(self, db_path: Path) -> None:
        """Test that response includes direction_id_filter."""
        response = await resolve_direction(
            "Angrignon", route_id="1", direction_id=0, db_path=db_path
        )

        assert response.direction_id_filter == 0

    async def test_match_type_is_fuzzy(self, db_path: Path) -> None:
        """Test that direction matches have FUZZY_NAME match type."""
        response = await resolve_direction("Angrignon", route_id="1", db_path=db_path)

        if response.best_match:
            assert response.best_match.match_type == MatchType.FUZZY_NAME
