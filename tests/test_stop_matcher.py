"""Tests for fuzzy stop matching."""

from pathlib import Path

import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.matching import SearchIndex
from stm_mcp.matching.models import MatchConfidence, MatchType
from stm_mcp.matching.stop_matcher import resolve_stop


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

    # stops.txt - various stops for testing fuzzy matching
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,51001,Berri-UQAM,45.515,-73.561,,0,,1\n"
        "SAINT-MICHEL,52001,Saint-Michel,45.559,-73.600,,0,,1\n"
        "SHERBROOKE-BERRI,53001,Sherbrooke / Berri,45.517,-73.563,,0,,1\n"
        "SHERBROOKE-DENIS,54001,Sherbrooke / Saint-Denis,45.518,-73.568,,0,,1\n"
        "MCGILL,55001,McGill,45.503,-73.572,,0,,1\n"
        "PREFONTAINE,56001,Préfontaine,45.540,-73.550,,0,,1\n"
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


class TestResolveStopExact:
    """Tests for exact stop matching."""

    async def test_exact_stop_code_match(self, db_path: Path) -> None:
        """Test exact stop code matching."""
        response = await resolve_stop("51001", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.stop_code == "51001"
        assert response.best_match.score == 100.0
        assert response.best_match.confidence == MatchConfidence.EXACT
        assert response.best_match.match_type == MatchType.CODE_EXACT

    async def test_exact_stop_id_match(self, db_path: Path) -> None:
        """Test exact stop ID matching."""
        response = await resolve_stop("BERRI", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.stop_id == "BERRI"
        assert response.best_match.score == 100.0
        assert response.best_match.confidence == MatchConfidence.EXACT
        assert response.best_match.match_type == MatchType.ID_EXACT


class TestResolveStopFuzzy:
    """Tests for fuzzy stop matching."""

    async def test_fuzzy_match_typo(self, db_path: Path) -> None:
        """Test fuzzy matching handles typos."""
        response = await resolve_stop("Beri-UQAM", db_path=db_path)

        assert len(response.matches) > 0
        # Should find Berri-UQAM as a match
        match_names = [m.stop_name for m in response.matches]
        assert any("Berri" in name for name in match_names)

    async def test_fuzzy_match_abbreviation(self, db_path: Path) -> None:
        """Test fuzzy matching expands abbreviations."""
        response = await resolve_stop("St-Michel", db_path=db_path)

        assert len(response.matches) > 0
        # Should find Saint-Michel
        assert response.best_match is not None
        assert "Michel" in response.best_match.stop_name

    async def test_fuzzy_match_accents(self, db_path: Path) -> None:
        """Test fuzzy matching handles accents."""
        response = await resolve_stop("Prefontaine", db_path=db_path)

        assert len(response.matches) > 0
        # Should find Préfontaine
        assert response.best_match is not None
        assert "fontaine" in response.best_match.stop_name.lower()


class TestResolveStopCrossStreet:
    """Tests for cross-street pattern matching."""

    async def test_cross_street_match(self, db_path: Path) -> None:
        """Test cross-street pattern matching."""
        response = await resolve_stop("Sherbrooke at Berri", db_path=db_path)

        assert len(response.matches) > 0
        # Should find Sherbrooke / Berri with high confidence
        cross_matches = [
            m for m in response.matches if m.match_type == MatchType.CROSS_STREET
        ]
        assert len(cross_matches) > 0

    async def test_cross_street_both_streets(self, db_path: Path) -> None:
        """Test that cross-street matches both streets."""
        response = await resolve_stop("Sherbrooke / Saint-Denis", db_path=db_path)

        assert response.best_match is not None
        # Should match Sherbrooke / Saint-Denis stop
        assert "Sherbrooke" in response.best_match.stop_name
        assert "Denis" in response.best_match.stop_name


class TestResolveStopOptions:
    """Tests for resolve_stop options."""

    async def test_limit_option(self, db_path: Path) -> None:
        """Test that limit is respected."""
        response = await resolve_stop("S", limit=2, db_path=db_path)

        assert len(response.matches) <= 2

    async def test_min_score_option(self, db_path: Path) -> None:
        """Test that min_score filters results."""
        response_low = await resolve_stop("xyz", min_score=10, db_path=db_path)
        response_high = await resolve_stop("xyz", min_score=90, db_path=db_path)

        assert len(response_high.matches) <= len(response_low.matches)

    async def test_empty_query(self, db_path: Path) -> None:
        """Test that empty query returns empty results."""
        response = await resolve_stop("", db_path=db_path)

        assert response.resolved is False
        assert response.best_match is None
        assert len(response.matches) == 0

    async def test_whitespace_query(self, db_path: Path) -> None:
        """Test that whitespace-only query returns empty results."""
        response = await resolve_stop("   ", db_path=db_path)

        assert response.resolved is False
        assert len(response.matches) == 0


class TestResolveStopResolution:
    """Tests for resolution status."""

    async def test_resolved_true_for_exact(self, db_path: Path) -> None:
        """Test resolved=True for exact matches."""
        response = await resolve_stop("51001", db_path=db_path)

        assert response.resolved is True
        assert response.best_match is not None
        assert response.best_match.confidence == MatchConfidence.EXACT

    async def test_best_match_always_set(self, db_path: Path) -> None:
        """Test that best_match is always set when matches exist."""
        response = await resolve_stop("Sherbrooke", db_path=db_path)

        assert len(response.matches) > 0
        assert response.best_match is not None
        assert response.best_match == response.matches[0]

    async def test_matches_sorted_by_score(self, db_path: Path) -> None:
        """Test that matches are sorted by score descending."""
        response = await resolve_stop("Sherbrooke", db_path=db_path)

        for i in range(len(response.matches) - 1):
            assert response.matches[i].score >= response.matches[i + 1].score
