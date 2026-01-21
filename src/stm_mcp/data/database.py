"""Database connection helper for GTFS SQLite database."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


def get_db_path() -> Path:
    """Get the database path from environment or default."""
    return Path(os.environ.get("STM_DB_PATH", "data/gtfs.db"))


@asynccontextmanager
async def get_db(db_path: Path | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """Async context manager for DB connections with Row factory.

    Args:
        db_path: Optional path to the database. If not provided, uses STM_DB_PATH
                 environment variable or defaults to 'data/gtfs.db'.

    Yields:
        aiosqlite.Connection configured with Row factory for dict-like access.

    Raises:
        FileNotFoundError: If the database file doesn't exist.
    """
    if db_path is None:
        db_path = get_db_path()

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run 'stm-mcp ingest <gtfs_path>' to create it."
        )

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db
