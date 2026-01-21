"""GTFS data loader for ingesting transit data into SQLite."""

import csv
import logging
import zipfile
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# Schema definitions
SCHEMA_SQL = """
-- agency
CREATE TABLE agency (
    agency_id TEXT PRIMARY KEY,
    agency_name TEXT NOT NULL,
    agency_url TEXT,
    agency_timezone TEXT
);

-- routes
CREATE TABLE routes (
    route_id TEXT PRIMARY KEY,
    agency_id TEXT,
    route_short_name TEXT,
    route_long_name TEXT,
    route_type INTEGER NOT NULL,
    route_url TEXT,
    route_color TEXT,
    route_text_color TEXT
);

-- stops
CREATE TABLE stops (
    stop_id TEXT PRIMARY KEY,
    stop_code TEXT,
    stop_name TEXT NOT NULL,
    stop_lat REAL,
    stop_lon REAL,
    stop_url TEXT,
    location_type INTEGER,
    parent_station TEXT,
    wheelchair_boarding INTEGER
);

-- calendar
CREATE TABLE calendar (
    service_id TEXT PRIMARY KEY,
    monday INTEGER,
    tuesday INTEGER,
    wednesday INTEGER,
    thursday INTEGER,
    friday INTEGER,
    saturday INTEGER,
    sunday INTEGER,
    start_date TEXT,
    end_date TEXT
);

-- calendar_dates
CREATE TABLE calendar_dates (
    service_id TEXT,
    date TEXT,
    exception_type INTEGER,
    PRIMARY KEY (service_id, date)
);

-- trips
CREATE TABLE trips (
    trip_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    trip_headsign TEXT,
    direction_id INTEGER,
    shape_id TEXT,
    wheelchair_accessible INTEGER,
    note_fr TEXT,
    note_en TEXT
);

-- stop_times
CREATE TABLE stop_times (
    trip_id TEXT NOT NULL,
    arrival_time TEXT,
    departure_time TEXT,
    stop_id TEXT NOT NULL,
    stop_sequence INTEGER NOT NULL,
    pickup_type INTEGER,
    PRIMARY KEY (trip_id, stop_sequence)
);

-- feed_info
CREATE TABLE feed_info (
    feed_publisher_name TEXT,
    feed_publisher_url TEXT,
    feed_lang TEXT,
    feed_start_date TEXT,
    feed_end_date TEXT,
    feed_version TEXT
);
"""

INDEX_SQL = """
CREATE INDEX idx_routes_type ON routes(route_type);
CREATE INDEX idx_stops_parent ON stops(parent_station);
CREATE INDEX idx_stops_name ON stops(stop_name);
CREATE INDEX idx_stops_location_type ON stops(location_type);
CREATE INDEX idx_trips_route ON trips(route_id);
CREATE INDEX idx_trips_service ON trips(service_id);
CREATE INDEX idx_stop_times_stop ON stop_times(stop_id);
CREATE INDEX idx_stop_times_stop_arrival ON stop_times(stop_id, arrival_time);
"""

# Table definitions: table_name -> (csv_filename, columns)
TABLE_DEFINITIONS: dict[str, tuple[str, list[str]]] = {
    "agency": (
        "agency.txt",
        ["agency_id", "agency_name", "agency_url", "agency_timezone"],
    ),
    "routes": (
        "routes.txt",
        [
            "route_id",
            "agency_id",
            "route_short_name",
            "route_long_name",
            "route_type",
            "route_url",
            "route_color",
            "route_text_color",
        ],
    ),
    "stops": (
        "stops.txt",
        [
            "stop_id",
            "stop_code",
            "stop_name",
            "stop_lat",
            "stop_lon",
            "stop_url",
            "location_type",
            "parent_station",
            "wheelchair_boarding",
        ],
    ),
    "calendar": (
        "calendar.txt",
        [
            "service_id",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "start_date",
            "end_date",
        ],
    ),
    "calendar_dates": (
        "calendar_dates.txt",
        ["service_id", "date", "exception_type"],
    ),
    "trips": (
        "trips.txt",
        [
            "trip_id",
            "route_id",
            "service_id",
            "trip_headsign",
            "direction_id",
            "shape_id",
            "wheelchair_accessible",
            "note_fr",
            "note_en",
        ],
    ),
    "stop_times": (
        "stop_times.txt",
        [
            "trip_id",
            "arrival_time",
            "departure_time",
            "stop_id",
            "stop_sequence",
            "pickup_type",
        ],
    ),
    "feed_info": (
        "feed_info.txt",
        [
            "feed_publisher_name",
            "feed_publisher_url",
            "feed_lang",
            "feed_start_date",
            "feed_end_date",
            "feed_version",
        ],
    ),
}

# Columns that must be present for a row to be inserted.
REQUIRED_COLUMNS: dict[str, list[str]] = {
    "agency": ["agency_id", "agency_name"],
    "routes": ["route_id", "route_type"],
    "stops": ["stop_id", "stop_name"],
    "calendar": ["service_id"],
    "calendar_dates": ["service_id", "date", "exception_type"],
    "trips": ["trip_id", "route_id", "service_id"],
    "stop_times": ["trip_id", "stop_id", "stop_sequence"],
    "feed_info": [],
}

# Chunk size for bulk inserts
CHUNK_SIZE = 10000


class GTFSLoader:
    """Loader for ingesting GTFS data into SQLite."""

    def __init__(self, db_path: Path):
        """Initialize the loader.

        Args:
            db_path: Path where the SQLite database will be created.
        """
        self.db_path = Path(db_path)

    async def ingest(self, gtfs_path: Path) -> dict[str, int]:
        """Ingest GTFS data from a directory or ZIP file into SQLite.

        Uses atomic swap: loads into temp DB, then replaces the target DB.

        Args:
            gtfs_path: Path to GTFS directory or ZIP file.

        Returns:
            Dictionary with row counts per table.

        Raises:
            FileNotFoundError: If GTFS path doesn't exist.
            ValueError: If required GTFS files are missing.
        """
        gtfs_path = Path(gtfs_path)
        if not gtfs_path.exists():
            raise FileNotFoundError(f"GTFS path not found: {gtfs_path}")

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        temp_db = self.db_path.with_suffix(".tmp.db")

        try:
            # Remove temp db if it exists from a previous failed run
            temp_db.unlink(missing_ok=True)

            async with aiosqlite.connect(temp_db) as db:
                # Performance optimizations for bulk loading
                await db.execute("PRAGMA journal_mode=OFF")
                await db.execute("PRAGMA synchronous=OFF")
                await db.execute("PRAGMA cache_size=10000")

                await self._create_schema(db)
                row_counts = await self._load_all_tables(db, gtfs_path)
                await self._create_indexes(db)
                await self._verify_integrity(db)

            # atomic swap
            if self.db_path.exists():
                self.db_path.unlink()
            temp_db.rename(self.db_path)

            logger.info(f"GTFS ingestion complete: {self.db_path}")
            return row_counts

        except Exception:
            temp_db.unlink(missing_ok=True)
            raise

    async def _create_schema(self, db: aiosqlite.Connection) -> None:
        """Create database schema (tables without indexes)."""
        await db.executescript(SCHEMA_SQL)
        await db.commit()

    async def _create_indexes(self, db: aiosqlite.Connection) -> None:
        """Create indexes after bulk loading."""
        logger.info("Creating indexes...")
        await db.executescript(INDEX_SQL)
        await db.commit()

    async def _load_all_tables(self, db: aiosqlite.Connection, gtfs_path: Path) -> dict[str, int]:
        """Load all GTFS tables from directory or ZIP."""
        row_counts: dict[str, int] = {}

        if gtfs_path.is_file() and gtfs_path.suffix == ".zip":
            with zipfile.ZipFile(gtfs_path, "r") as zf:
                for table_name, (csv_filename, columns) in TABLE_DEFINITIONS.items():
                    if csv_filename in zf.namelist():
                        count = await self._load_table_from_zip(
                            db, table_name, columns, zf, csv_filename
                        )
                        row_counts[table_name] = count
                    else:
                        logger.warning(f"Optional file {csv_filename} not found in ZIP")
                        row_counts[table_name] = 0
        else:
            for table_name, (csv_filename, columns) in TABLE_DEFINITIONS.items():
                csv_path = gtfs_path / csv_filename
                if csv_path.exists():
                    count = await self._load_table(db, table_name, columns, csv_path)
                    row_counts[table_name] = count
                else:
                    logger.warning(f"Optional file {csv_filename} not found")
                    row_counts[table_name] = 0

        return row_counts

    async def _load_table(
        self,
        db: aiosqlite.Connection,
        table_name: str,
        columns: list[str],
        csv_path: Path,
    ) -> int:
        """Load a single CSV file into a table."""
        logger.info(f"Loading {table_name} from {csv_path.name}...")

        placeholders = ",".join(["?"] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"

        total_rows = 0
        skipped_rows = 0
        chunk: list[tuple[Any, ...]] = []
        required = REQUIRED_COLUMNS.get(table_name, [])

        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header_index = self._build_header_index(reader, columns, csv_path.name)
            for row in reader:
                row_dict = self._row_from_index(row, header_index)
                if not self._has_required_values(row_dict, required):
                    skipped_rows += 1
                    continue
                values = tuple(self._convert_value(row_dict.get(col)) for col in columns)
                chunk.append(values)

                if len(chunk) >= CHUNK_SIZE:
                    await db.executemany(insert_sql, chunk)
                    total_rows += len(chunk)
                    chunk = []

            if chunk:
                await db.executemany(insert_sql, chunk)
                total_rows += len(chunk)

        await db.commit()
        logger.info(
            f"  Loaded {total_rows:,} rows into {table_name}"
            + (f" (skipped {skipped_rows:,} invalid)" if skipped_rows else "")
        )
        return total_rows

    async def _load_table_from_zip(
        self,
        db: aiosqlite.Connection,
        table_name: str,
        columns: list[str],
        zf: zipfile.ZipFile,
        csv_filename: str,
    ) -> int:
        """Load a single CSV file from a ZIP into a table."""
        logger.info(f"Loading {table_name} from {csv_filename}...")

        placeholders = ",".join(["?"] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"

        total_rows = 0
        skipped_rows = 0
        chunk: list[tuple[Any, ...]] = []
        required = REQUIRED_COLUMNS.get(table_name, [])

        with zf.open(csv_filename) as f:
            # Wrap binary file in text mode
            import io

            text_file = io.TextIOWrapper(f, encoding="utf-8-sig")
            reader = csv.reader(text_file)
            header_index = self._build_header_index(reader, columns, csv_filename)
            for row in reader:
                row_dict = self._row_from_index(row, header_index)
                if not self._has_required_values(row_dict, required):
                    skipped_rows += 1
                    continue
                values = tuple(self._convert_value(row_dict.get(col)) for col in columns)
                chunk.append(values)

                if len(chunk) >= CHUNK_SIZE:
                    await db.executemany(insert_sql, chunk)
                    total_rows += len(chunk)
                    chunk = []

            if chunk:
                await db.executemany(insert_sql, chunk)
                total_rows += len(chunk)

        await db.commit()
        logger.info(
            f"  Loaded {total_rows:,} rows into {table_name}"
            + (f" (skipped {skipped_rows:,} invalid)" if skipped_rows else "")
        )
        return total_rows

    def _convert_value(self, value: str | None) -> Any:
        """Convert CSV value to appropriate Python type."""
        if value is None or value == "":
            return None
        return value.strip()

    def _has_required_values(self, row: dict[str, str | None], required: list[str]) -> bool:
        """Return True if all required columns have non-empty values."""
        for col in required:
            value = row.get(col)
            if value is None or value.strip() == "":
                return False
        return True

    def _normalize_header(self, name: str, expected: set[str]) -> str:
        """Normalize CSV header field names."""
        cleaned = name.strip()
        if cleaned.startswith("do "):
            candidate = cleaned[3:]
            if candidate in expected:
                return candidate
        for col in expected:
            if cleaned.endswith(col):
                return col
        return cleaned

    def _build_header_index(
        self, reader: csv.reader, columns: list[str], filename: str
    ) -> dict[str, int]:
        """Build header index mapping for a CSV reader."""
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{filename} is empty")
        expected = set(columns)
        normalized = [self._normalize_header(name, expected) for name in header]
        header_index: dict[str, int] = {}
        for idx, name in enumerate(normalized):
            if name in expected and name not in header_index:
                header_index[name] = idx
        missing = [col for col in columns if col not in header_index]
        if missing:
            raise ValueError(f"{filename} missing columns: {', '.join(missing)}")
        return header_index

    def _row_from_index(self, row: list[str], header_index: dict[str, int]) -> dict[str, str]:
        """Map a CSV row list to a dict by header index."""
        row_dict: dict[str, str] = {}
        for col, idx in header_index.items():
            row_dict[col] = row[idx] if idx < len(row) else ""
        return row_dict

    async def _verify_integrity(self, db: aiosqlite.Connection) -> None:
        """Verify database integrity after loading."""
        logger.info("Verifying database integrity...")

        # Check required tables have data
        async with db.execute("SELECT COUNT(*) FROM routes") as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] == 0:
                raise ValueError("No routes loaded - check GTFS data")

        async with db.execute("SELECT COUNT(*) FROM stops") as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] == 0:
                raise ValueError("No stops loaded - check GTFS data")

        async with db.execute("SELECT COUNT(*) FROM trips") as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] == 0:
                raise ValueError("No trips loaded - check GTFS data")

        async with db.execute("SELECT COUNT(*) FROM stop_times") as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] == 0:
                raise ValueError("No stop_times loaded - check GTFS data")

        logger.info("Database integrity verified")


async def get_table_counts(db_path: Path) -> dict[str, int]:
    """Get row counts for all tables in the database.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        Dictionary mapping table names to row counts.
    """
    counts: dict[str, int] = {}
    async with aiosqlite.connect(db_path) as db:
        for table_name in TABLE_DEFINITIONS:
            async with db.execute(f"SELECT COUNT(*) FROM {table_name}") as cursor:
                row = await cursor.fetchone()
                counts[table_name] = row[0] if row else 0
    return counts
