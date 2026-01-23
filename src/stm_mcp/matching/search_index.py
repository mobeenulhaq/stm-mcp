"""Pre-computed in-memory search index for fuzzy matching."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from stm_mcp.data.database import get_db_path
from stm_mcp.matching.normalizers import normalize_text

logger = logging.getLogger(__name__)


@dataclass
class IndexedStop:
    """Stop data with pre-computed normalized text."""

    stop_id: str
    stop_code: str | None
    stop_name: str
    stop_lat: float | None
    stop_lon: float | None
    normalized_name: str  # Pre-computed for fuzzy matching


@dataclass
class IndexedRoute:
    """Route data with pre-computed normalized text."""

    route_id: str
    route_short_name: str | None
    route_long_name: str | None
    route_type: int
    normalized_short_name: str | None
    normalized_long_name: str | None


@dataclass
class IndexedHeadsign:
    """Headsign data for direction matching."""

    route_id: str
    direction_id: int
    headsign: str
    normalized_headsign: str


class SearchIndex:
    """Lazy-loaded singleton index for fuzzy matching.

    Pre-computes normalized text for all stops, routes, and headsigns
    to enable fast fuzzy matching without repeated database queries.

    Usage:
        index = await SearchIndex.get_instance()
        # Use index.stops, index.routes, index.headsigns

    After GTFS ingestion:
        await SearchIndex.invalidate()  # Clear cached instance
    """

    _instance: "SearchIndex | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize empty index. Use get_instance() instead."""
        # Stops
        self.stops: list[IndexedStop] = []
        self.stops_by_code: dict[str, IndexedStop] = {}  # stop_code -> stop
        self.stops_by_id: dict[str, IndexedStop] = {}  # stop_id -> stop

        # Routes
        self.routes: list[IndexedRoute] = []
        self.routes_by_id: dict[str, IndexedRoute] = {}  # route_id -> route
        self.routes_by_number: dict[str, IndexedRoute] = {}  # route_short_name -> route

        # Headsigns (grouped by route)
        self.headsigns: list[IndexedHeadsign] = []
        self.headsigns_by_route: dict[str, list[IndexedHeadsign]] = {}  # route_id -> headsigns

    @classmethod
    async def get_instance(cls, db_path: Path | None = None) -> "SearchIndex":
        """Get or create the singleton index instance.

        Args:
            db_path: Optional database path. Uses default if not provided.

        Returns:
            The loaded SearchIndex singleton.
        """
        async with cls._lock:
            if cls._instance is None:
                cls._instance = SearchIndex()
                await cls._instance._load(db_path)
            return cls._instance

    @classmethod
    async def invalidate(cls) -> None:
        """Invalidate the cached index. Call after GTFS ingestion."""
        async with cls._lock:
            cls._instance = None
            logger.info("SearchIndex invalidated")

    @classmethod
    async def reload(cls, db_path: Path | None = None) -> "SearchIndex":
        """Force reload the index from database."""
        await cls.invalidate()
        return await cls.get_instance(db_path)

    async def _load(self, db_path: Path | None = None) -> None:
        """Load all data from database and build indexes."""
        if db_path is None:
            db_path = get_db_path()

        logger.info(f"Loading SearchIndex from {db_path}...")

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await self._load_stops(db)
            await self._load_routes(db)
            await self._load_headsigns(db)

        logger.info(
            f"SearchIndex loaded: {len(self.stops)} stops, "
            f"{len(self.routes)} routes, {len(self.headsigns)} headsigns"
        )

    async def _load_stops(self, db: aiosqlite.Connection) -> None:
        """Load stops into index."""
        query = """
            SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon
            FROM stops
            WHERE location_type IS NULL OR location_type = 0
        """
        async with db.execute(query) as cursor:
            async for row in cursor:
                stop = IndexedStop(
                    stop_id=row["stop_id"],
                    stop_code=row["stop_code"],
                    stop_name=row["stop_name"],
                    stop_lat=float(row["stop_lat"]) if row["stop_lat"] else None,
                    stop_lon=float(row["stop_lon"]) if row["stop_lon"] else None,
                    normalized_name=normalize_text(row["stop_name"]),
                )
                self.stops.append(stop)
                self.stops_by_id[stop.stop_id] = stop
                if stop.stop_code:
                    self.stops_by_code[stop.stop_code] = stop

    async def _load_routes(self, db: aiosqlite.Connection) -> None:
        """Load routes into index."""
        query = """
            SELECT route_id, route_short_name, route_long_name, route_type
            FROM routes
        """
        async with db.execute(query) as cursor:
            async for row in cursor:
                route = IndexedRoute(
                    route_id=row["route_id"],
                    route_short_name=row["route_short_name"],
                    route_long_name=row["route_long_name"],
                    route_type=int(row["route_type"]),
                    normalized_short_name=(
                        normalize_text(row["route_short_name"]) if row["route_short_name"] else None
                    ),
                    normalized_long_name=(
                        normalize_text(row["route_long_name"]) if row["route_long_name"] else None
                    ),
                )
                self.routes.append(route)
                self.routes_by_id[route.route_id] = route
                if route.route_short_name:
                    self.routes_by_number[route.route_short_name] = route

    async def _load_headsigns(self, db: aiosqlite.Connection) -> None:
        """Load unique headsigns into index."""
        query = """
            SELECT DISTINCT route_id, direction_id, trip_headsign
            FROM trips
            WHERE trip_headsign IS NOT NULL AND trip_headsign != ''
        """
        async with db.execute(query) as cursor:
            async for row in cursor:
                headsign = IndexedHeadsign(
                    route_id=row["route_id"],
                    direction_id=int(row["direction_id"]) if row["direction_id"] is not None else 0,
                    headsign=row["trip_headsign"],
                    normalized_headsign=normalize_text(row["trip_headsign"]),
                )
                self.headsigns.append(headsign)

                if headsign.route_id not in self.headsigns_by_route:
                    self.headsigns_by_route[headsign.route_id] = []
                self.headsigns_by_route[headsign.route_id].append(headsign)
