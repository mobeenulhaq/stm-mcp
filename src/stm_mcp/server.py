import argparse
import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

# Initialize the MCP server
mcp = FastMCP(
    "STM Transit",
    instructions="Montreal STM transit information - schedules, real-time arrivals, and trip planning",
)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: str


@mcp.tool()
def health() -> HealthResponse:
    """Check if the STM MCP server is running and healthy.

    Returns the server status, version, and current timestamp.
    """
    from stm_mcp import __version__

    return HealthResponse(
        status="ok",
        version=__version__,
        timestamp=datetime.now(UTC).isoformat(),
    )


async def run_ingest(gtfs_path: Path, db_path: Path) -> None:
    """Run GTFS ingestion."""
    from stm_mcp.data.gtfs_loader import GTFSLoader

    loader = GTFSLoader(db_path)
    row_counts = await loader.ingest(gtfs_path)

    print("\nIngestion complete. Row counts:")
    for table, count in row_counts.items():
        print(f"  {table}: {count:,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stm-mcp",
        description="STM Transit MCP Server",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ingest command
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest GTFS data into SQLite database",
    )
    ingest_parser.add_argument(
        "gtfs_path",
        type=Path,
        help="Path to GTFS directory or ZIP file",
    )
    ingest_parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("STM_DB_PATH", "data/gtfs.db")),
        help="SQLite database path (default: data/gtfs.db or STM_DB_PATH env var)",
    )
    ingest_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        # Configure logging
        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        asyncio.run(run_ingest(args.gtfs_path, args.db))
    else:
        # Default: run MCP server
        mcp.run()


if __name__ == "__main__":
    main()
