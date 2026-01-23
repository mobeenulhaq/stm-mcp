from datetime import UTC, datetime

import httpx
from google.transit import gtfs_realtime_pb2

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.models.realtime import (
    FeedHeader,
    OccupancyStatus,
    Position,
    StopTimeEvent,
    StopTimeUpdate,
    TripDescriptor,
    TripUpdate,
    TripUpdatesData,
    VehicleDescriptor,
    VehiclePosition,
    VehiclePositionsData,
)


class GTFSRTClient:
    """Async HTTP client for fetching GTFS-RT feeds from STM API.

    Usage:
        async with GTFSRTClient(config) as client:
            trip_updates = await client.fetch_trip_updates()
    """

    def __init__(self, config: GTFSRTConfig):
        """Initialize the client.

        Args:
            config: GTFS-RT configuration with API key and URLs.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GTFSRTClient":
        """Enter async context - create HTTP client."""
        headers = {}
        if self._config.api_key:
            headers["apikey"] = self._config.api_key
        self._client = httpx.AsyncClient(headers=headers, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context - close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_trip_updates(self) -> TripUpdatesData:
        """Fetch and parse the trip updates feed.

        Returns:
            TripUpdatesData with parsed trip updates.

        Raises:
            RuntimeError: If client not initialized.
            httpx.HTTPError: If the HTTP request fails.
        """
        if not self._client:
            raise RuntimeError("Client not initialized - use 'async with'")

        response = await self._client.get(self._config.trip_updates_url)
        response.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        return self._parse_trip_updates(feed)

    async def fetch_vehicle_positions(self) -> VehiclePositionsData:
        """Fetch and parse the vehicle positions feed.

        Returns:
            VehiclePositionsData with parsed vehicle positions.

        Raises:
            RuntimeError: If client not initialized.
            httpx.HTTPError: If the HTTP request fails.
        """
        if not self._client:
            raise RuntimeError("Client not initialized - use 'async with'")

        response = await self._client.get(self._config.vehicle_positions_url)
        response.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        return self._parse_vehicle_positions(feed)

    def _parse_trip_updates(self, feed: gtfs_realtime_pb2.FeedMessage) -> TripUpdatesData:
        """Parse protobuf feed message into TripUpdatesData model."""
        header = FeedHeader(
            gtfs_realtime_version=feed.header.gtfs_realtime_version,
            timestamp=feed.header.timestamp,
        )

        trip_updates: list[TripUpdate] = []
        for entity in feed.entity:
            if entity.HasField("trip_update"):
                tu = entity.trip_update
                trip_updates.append(self._parse_trip_update(tu))

        return TripUpdatesData(
            header=header,
            trip_updates=trip_updates,
            fetched_at=datetime.now(UTC),
        )

    def _parse_trip_update(self, tu: gtfs_realtime_pb2.TripUpdate) -> TripUpdate:
        """Parse a single trip update entity."""
        trip = self._parse_trip_descriptor(tu.trip)

        stop_time_updates: list[StopTimeUpdate] = []
        for stu in tu.stop_time_update:
            stop_time_updates.append(self._parse_stop_time_update(stu))

        return TripUpdate(
            trip=trip,
            stop_time_update=stop_time_updates,
            timestamp=tu.timestamp if tu.timestamp else None,
        )

    def _parse_stop_time_update(self, stu: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate) -> StopTimeUpdate:
        """Parse a single stop time update."""
        arrival = None
        if stu.HasField("arrival"):
            arrival = StopTimeEvent(
                delay=stu.arrival.delay if stu.arrival.delay else None,
                time=stu.arrival.time if stu.arrival.time else None,
            )

        departure = None
        if stu.HasField("departure"):
            departure = StopTimeEvent(
                delay=stu.departure.delay if stu.departure.delay else None,
                time=stu.departure.time if stu.departure.time else None,
            )

        return StopTimeUpdate(
            stop_sequence=stu.stop_sequence if stu.stop_sequence else None,
            stop_id=stu.stop_id if stu.stop_id else None,
            arrival=arrival,
            departure=departure,
        )

    def _parse_vehicle_positions(self, feed: gtfs_realtime_pb2.FeedMessage) -> VehiclePositionsData:
        """Parse protobuf feed message into VehiclePositionsData model."""
        header = FeedHeader(
            gtfs_realtime_version=feed.header.gtfs_realtime_version,
            timestamp=feed.header.timestamp,
        )

        vehicles: list[VehiclePosition] = []
        for entity in feed.entity:
            if entity.HasField("vehicle"):
                vp = entity.vehicle
                vehicles.append(self._parse_vehicle_position(vp))

        return VehiclePositionsData(
            header=header,
            vehicles=vehicles,
            fetched_at=datetime.now(UTC),
        )

    def _parse_vehicle_position(self, vp: gtfs_realtime_pb2.VehiclePosition) -> VehiclePosition:
        """Parse a single vehicle position entity."""
        trip = None
        if vp.HasField("trip"):
            trip = self._parse_trip_descriptor(vp.trip)

        vehicle = None
        if vp.HasField("vehicle"):
            vehicle = VehicleDescriptor(
                id=vp.vehicle.id if vp.vehicle.id else None,
                label=vp.vehicle.label if vp.vehicle.label else None,
            )

        position = None
        if vp.HasField("position"):
            position = Position(
                latitude=vp.position.latitude,
                longitude=vp.position.longitude,
                bearing=vp.position.bearing if vp.position.bearing else None,
                speed=vp.position.speed if vp.position.speed else None,
            )

        # parse occupancy status (GTFS-RT enum -> our enum)
        occupancy_status = None
        if vp.HasField("occupancy_status"):
            occupancy_name = gtfs_realtime_pb2.VehiclePosition.OccupancyStatus.Name(
                vp.occupancy_status
            )
            try:
                occupancy_status = OccupancyStatus(occupancy_name)
            except ValueError:
                pass  # unknown occupancy status, leave as None

        return VehiclePosition(
            trip=trip,
            vehicle=vehicle,
            position=position,
            current_stop_sequence=vp.current_stop_sequence if vp.current_stop_sequence else None,
            stop_id=vp.stop_id if vp.stop_id else None,
            occupancy_status=occupancy_status,
            timestamp=vp.timestamp if vp.timestamp else None,
        )

    def _parse_trip_descriptor(self, td: gtfs_realtime_pb2.TripDescriptor) -> TripDescriptor:
        """Parse a trip descriptor."""
        return TripDescriptor(
            trip_id=td.trip_id if td.trip_id else None,
            route_id=td.route_id if td.route_id else None,
            direction_id=td.direction_id if td.HasField("direction_id") else None,
            start_time=td.start_time if td.start_time else None,
            start_date=td.start_date if td.start_date else None,
        )
