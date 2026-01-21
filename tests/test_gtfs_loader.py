import zipfile
from pathlib import Path

import aiosqlite
import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader, get_table_counts


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

    # stops.txt
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,wheelchair_boarding\n"
        "BERRI,BERRI,Berri-UQAM,45.515,-73.561,,1,,1\n"
        "BERRI-1,51234,Berri-UQAM - Green Line,45.515,-73.561,,0,BERRI,1\n"
        "51001,51001,Sherbrooke / Saint-Denis,45.518,-73.568,,0,,1\n"
    )

    # calendar.txt
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20241231\n"
        "WEEKEND,0,0,0,0,0,1,1,20240101,20241231\n"
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
        "STM,http://www.stm.info,fr,20240101,20241231,2024.1\n"
    )

    return gtfs_dir


@pytest.fixture
def sample_gtfs_zip(sample_gtfs_dir: Path, tmp_path: Path) -> Path:
    """Create a sample GTFS ZIP file from the directory."""
    zip_path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file_path in sample_gtfs_dir.iterdir():
            zf.write(file_path, file_path.name)
    return zip_path


class TestGTFSLoader:
    """Tests for GTFSLoader."""

    async def test_ingest_from_directory(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test ingesting GTFS data from a directory."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)

        row_counts = await loader.ingest(sample_gtfs_dir)

        assert db_path.exists()
        assert row_counts["agency"] == 1
        assert row_counts["routes"] == 2
        assert row_counts["stops"] == 3
        assert row_counts["calendar"] == 2
        assert row_counts["calendar_dates"] == 2
        assert row_counts["trips"] == 2
        assert row_counts["stop_times"] == 3
        assert row_counts["feed_info"] == 1

    async def test_ingest_from_zip(self, sample_gtfs_zip: Path, tmp_path: Path) -> None:
        """Test ingesting GTFS data from a ZIP file."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)

        row_counts = await loader.ingest(sample_gtfs_zip)

        assert db_path.exists()
        assert row_counts["routes"] == 2
        assert row_counts["stops"] == 3
        assert row_counts["stop_times"] == 3

    async def test_atomic_swap_creates_new_db(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that ingestion creates the database atomically."""
        db_path = tmp_path / "test.db"
        temp_path = db_path.with_suffix(".tmp.db")

        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        # Final DB should exist, temp should not
        assert db_path.exists()
        assert not temp_path.exists()

    async def test_atomic_swap_replaces_existing(
        self, sample_gtfs_dir: Path, tmp_path: Path
    ) -> None:
        """Test that ingestion replaces an existing database."""
        db_path = tmp_path / "test.db"

        # Create initial database
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        # Ingest again - should replace
        await loader.ingest(sample_gtfs_dir)

        assert db_path.exists()
        counts = await get_table_counts(db_path)
        assert counts["routes"] == 2

    async def test_rollback_on_failure(self, tmp_path: Path) -> None:
        """Test that temp DB is cleaned up on failure."""
        db_path = tmp_path / "test.db"
        temp_path = db_path.with_suffix(".tmp.db")
        nonexistent_path = tmp_path / "nonexistent"

        loader = GTFSLoader(db_path)

        with pytest.raises(FileNotFoundError):
            await loader.ingest(nonexistent_path)

        # Neither DB should exist after failure
        assert not db_path.exists()
        assert not temp_path.exists()

    async def test_creates_parent_directories(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that parent directories are created if needed."""
        db_path = tmp_path / "subdir" / "nested" / "test.db"

        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        assert db_path.exists()


class TestSchemaAndIndexes:
    """Tests for database schema and indexes."""

    async def test_schema_has_all_tables(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that all expected tables are created."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] async for row in cursor]
            await cursor.close()

        expected_tables = [
            "agency",
            "calendar",
            "calendar_dates",
            "feed_info",
            "routes",
            "stop_times",
            "stops",
            "trips",
        ]
        assert tables == expected_tables

    async def test_indexes_created(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that expected indexes are created."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
            indexes = [row[0] async for row in cursor]
            await cursor.close()

        expected_indexes = [
            "idx_routes_type",
            "idx_stops_location_type",
            "idx_stops_name",
            "idx_stops_parent",
            "idx_stop_times_stop",
            "idx_stop_times_stop_arrival",
            "idx_trips_route",
            "idx_trips_service",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"


class TestDataIntegrity:
    """Tests for data integrity after ingestion."""

    async def test_route_data_correct(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that route data is correctly loaded."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM routes WHERE route_id = '1'") as cursor:
                route = await cursor.fetchone()

        assert route is not None
        assert route["route_short_name"] == "Green"
        assert route["route_type"] == 1
        assert route["route_color"] == "008E4F"

    async def test_stop_times_data_correct(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that stop_times data is correctly loaded."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM stop_times WHERE trip_id = 'TRIP1' ORDER BY stop_sequence"
            ) as cursor:
                stop_times = [row async for row in cursor]

        assert len(stop_times) == 2
        assert stop_times[0]["arrival_time"] == "08:00:00"
        assert stop_times[0]["stop_id"] == "BERRI-1"
        assert stop_times[1]["arrival_time"] == "08:05:00"
        assert stop_times[1]["stop_id"] == "51001"

    async def test_null_values_handled(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that empty CSV values become NULL in database."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trips WHERE trip_id = 'TRIP1'") as cursor:
                trip = await cursor.fetchone()

        # note_fr and note_en should be NULL (empty in CSV)
        assert trip["note_fr"] is None
        assert trip["note_en"] is None


class TestGetTableCounts:
    """Tests for the get_table_counts utility function."""

    async def test_returns_all_counts(self, sample_gtfs_dir: Path, tmp_path: Path) -> None:
        """Test that get_table_counts returns counts for all tables."""
        db_path = tmp_path / "test.db"
        loader = GTFSLoader(db_path)
        await loader.ingest(sample_gtfs_dir)

        counts = await get_table_counts(db_path)

        assert counts["agency"] == 1
        assert counts["routes"] == 2
        assert counts["stops"] == 3
        assert counts["calendar"] == 2
        assert counts["calendar_dates"] == 2
        assert counts["trips"] == 2
        assert counts["stop_times"] == 3
        assert counts["feed_info"] == 1
