from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite

from stm_mcp.data.database import get_db
from stm_mcp.models.responses import (
    GetScheduledArrivalsResponse,
    ScheduledArrival,
    StopInfo,
)

# GTFS weekday column names indexed by weekday (0=Monday, 6=Sunday)
WEEKDAY_COLUMNS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def parse_gtfs_time(time_str: str) -> tuple[int, int, int]:
    """Parse a GTFS time string into hours, minutes, seconds.

    GTFS times can exceed 24:00:00 for trips that extend past midnight.
    For example, "25:30:00" means 1:30 AM the next day.

    Args:
        time_str: Time string in HH:MM:SS format (hours can exceed 24).

    Returns:
        Tuple of (hours, minutes, seconds).

    Raises:
        ValueError: If the time string is invalid.
    """
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid GTFS time format: {time_str}")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
    except ValueError as e:
        raise ValueError(f"Invalid GTFS time format: {time_str}") from e

    return hours, minutes, seconds


def gtfs_time_to_seconds(time_str: str) -> int:
    """Convert a GTFS time string to seconds since midnight.

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        Total seconds since midnight (can exceed 86400 for next-day times).
    """
    hours, minutes, seconds = parse_gtfs_time(time_str)
    return hours * 3600 + minutes * 60 + seconds


def format_gtfs_time(time_str: str) -> str:
    """Format a GTFS time string for human display.

    Converts 24-hour format to 12-hour with AM/PM.
    Times >= 24:00 are shown with "(+1)" suffix to indicate next day.

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        Human-readable time like "8:30 AM" or "1:30 AM (+1)".
    """
    hours, minutes, _ = parse_gtfs_time(time_str)

    next_day = ""
    if hours >= 24:
        hours -= 24
        next_day = " (+1)"

    period = "AM"
    display_hour = hours
    if hours == 0:
        display_hour = 12
    elif hours == 12:
        period = "PM"
    elif hours > 12:
        display_hour = hours - 12
        period = "PM"

    return f"{display_hour}:{minutes:02d} {period}{next_day}"


def time_to_gtfs_format(dt: datetime) -> str:
    """Convert a datetime to GTFS time format.

    Args:
        dt: Datetime object.

    Returns:
        Time string in HH:MM:SS format.
    """
    return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def date_to_gtfs_format(d: date) -> str:
    """Convert a date to GTFS date format (YYYYMMDD).

    Args:
        d: Date object.

    Returns:
        Date string in YYYYMMDD format.
    """
    return d.strftime("%Y%m%d")


def calculate_minutes_until(arrival_time: str, query_time: str) -> int:
    """Calculate minutes from query time to arrival time.

    Args:
        arrival_time: GTFS arrival time string.
        query_time: Query time string in HH:MM:SS format.

    Returns:
        Minutes until arrival (can be negative if arrival is before query).
    """
    arrival_seconds = gtfs_time_to_seconds(arrival_time)
    query_seconds = gtfs_time_to_seconds(query_time)
    diff_seconds = arrival_seconds - query_seconds
    return diff_seconds // 60


# Late night service threshold: times before this hour are considered part of
# the previous day's GTFS service (e.g., 1:30 AM is 25:30:00 on yesterday's service)
LATE_NIGHT_THRESHOLD_HOUR = 4


def get_gtfs_service_context(dt: datetime) -> tuple[date, str, bool]:
    """Determine the GTFS service date and time for a given datetime.

    GTFS uses extended times (25:00:00 = 1 AM, 26:00:00 = 2 AM, etc.) for
    service that runs past midnight. A trip starting Monday evening and
    ending at 2 AM Tuesday has times like 25:00:00-26:00:00 on Monday's
    service date.

    This function handles the "late night" period (midnight to ~4 AM) by:
    - Using the previous calendar day as the service date
    - Converting the time to extended GTFS format (add 24 hours)

    Args:
        dt: The datetime to convert.

    Returns:
        Tuple of (service_date, gtfs_time_str, is_late_night) where:
        - service_date: The GTFS service date (may be previous day)
        - gtfs_time_str: Time in HH:MM:SS format (may be 24+ hours)
        - is_late_night: True if we're in late-night mode (midnight to 4 AM)

    Examples:
        - 10:30 PM Monday -> (Monday, "22:30:00", False)
        - 1:30 AM Tuesday -> (Monday, "25:30:00", True)
        - 5:00 AM Tuesday -> (Tuesday, "05:00:00", False)
    """
    is_late_night = dt.hour < LATE_NIGHT_THRESHOLD_HOUR

    if is_late_night:
        # Late night: use previous day's service with extended time
        service_date = dt.date() - timedelta(days=1)
        extended_hour = dt.hour + 24
        gtfs_time = f"{extended_hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    else:
        # Normal daytime: use current date with normal time
        service_date = dt.date()
        gtfs_time = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"

    return service_date, gtfs_time, is_late_night


def safe_parse_gtfs_time(time_str: str) -> tuple[int, int, int] | None:
    """Safely parse a GTFS time string, returning None on failure.

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        Tuple of (hours, minutes, seconds) or None if parsing fails.
    """
    try:
        return parse_gtfs_time(time_str)
    except ValueError:
        return None


def is_time_in_late_night_range(time_str: str) -> bool:
    """Check if a time string falls in the late-night range (00:00-03:59).

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        True if the time is in the 00:00-03:59 range.
    """
    parsed = safe_parse_gtfs_time(time_str)
    if parsed is None:
        return False
    hours, _, _ = parsed
    return hours < LATE_NIGHT_THRESHOLD_HOUR


def is_extended_time(time_str: str) -> bool:
    """Check if a time string is in GTFS extended format (>= 24:00:00).

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        True if the time is >= 24:00:00.
    """
    parsed = safe_parse_gtfs_time(time_str)
    if parsed is None:
        return False
    hours, _, _ = parsed
    return hours >= 24


def convert_to_extended_time(time_str: str) -> str:
    """Convert a time in 00:00-23:59 range to extended format by adding 24 hours.

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        Time with 24 hours added. Returns as-is if already extended or invalid.

    Examples:
        - "02:10:00" -> "26:10:00"
        - "05:00:00" -> "29:00:00"
        - "25:30:00" -> "25:30:00" (already extended)
    """
    parsed = safe_parse_gtfs_time(time_str)
    if parsed is None:
        return time_str

    hours, minutes, seconds = parsed
    if hours < 24:
        hours += 24
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return time_str


def safe_gtfs_time_to_seconds(time_str: str) -> int | None:
    """Safely convert a GTFS time string to seconds, returning None on failure.

    Args:
        time_str: Time string in HH:MM:SS format.

    Returns:
        Total seconds since midnight, or None if parsing fails.
    """
    parsed = safe_parse_gtfs_time(time_str)
    if parsed is None:
        return None
    hours, minutes, seconds = parsed
    return hours * 3600 + minutes * 60 + seconds


async def get_active_service_ids(
    db: aiosqlite.Connection,
    query_date: date,
) -> set[str]:
    """Get service IDs active on a given date.

    Implements the GTFS service day algorithm:
    1. Find services from calendar where date is within [start_date, end_date]
       AND the weekday flag is 1
    2. Apply calendar_dates exceptions (exception_type=1 adds, 2 removes)

    Args:
        db: Database connection.
        query_date: Date to check for active services.

    Returns:
        Set of active service IDs.
    """
    date_str = date_to_gtfs_format(query_date)
    weekday_col = WEEKDAY_COLUMNS[query_date.weekday()]

    # Step 1: Get base services from calendar
    sql = f"""
        SELECT service_id
        FROM calendar
        WHERE ? BETWEEN start_date AND end_date
          AND {weekday_col} = 1
    """
    async with db.execute(sql, (date_str,)) as cursor:
        rows = await cursor.fetchall()
    base_services = {row["service_id"] for row in rows}

    # Step 2: Apply calendar_dates exceptions
    sql = """
        SELECT service_id, exception_type
        FROM calendar_dates
        WHERE date = ?
    """
    async with db.execute(sql, (date_str,)) as cursor:
        exceptions = await cursor.fetchall()

    for row in exceptions:
        service_id = row["service_id"]
        exception_type = int(row["exception_type"])

        if exception_type == 2:  # Service removed
            base_services.discard(service_id)
        elif exception_type == 1:  # Service added
            base_services.add(service_id)

    return base_services


async def get_scheduled_arrivals(
    stop_id: str,
    route_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
) -> GetScheduledArrivalsResponse:
    """Get scheduled arrivals at a stop.

    Args:
        stop_id: The stop ID to get arrivals for.
        route_id: Optional route ID to filter by.
        start_time: Start of time window in HH:MM:SS format (default: now).
        end_time: End of time window in HH:MM:SS format (default: 28:00:00).
        limit: Maximum number of arrivals to return.
        db_path: Optional database path override.

    Returns:
        GetScheduledArrivalsResponse with arrivals and stop info.

    Raises:
        ValueError: If stop_id is not found.
    """
    now = datetime.now()

    # STEP 1: Determine service_date and start_time together

    # We track `use_extended_times` to know if we're querying previous day's
    # service with times in 24:xx-27:xx format.

    # Rules:
    # 1. Extended start_time (25:xx) → user explicitly wants previous day's service
    # 2. Late-night start_time (00:00-03:59) + currently late-night → previous day
    # 3. Late-night start_time (00:00-03:59) + NOT currently late-night → today
    # 4. Normal start_time (04:00-23:59) → today's service
    # 5. No start_time → use "now" with late-night logic

    use_extended_times = False

    if start_time is not None:
        if is_extended_time(start_time):
            # User explicitly provided extended time (25:xx) → previous day's service
            service_date = now.date() - timedelta(days=1)
            use_extended_times = True
        elif is_time_in_late_night_range(start_time):
            # start_time is in 00:00-03:59 range
            _, _, currently_late_night = get_gtfs_service_context(now)
            if currently_late_night:
                # We're at 1 AM querying for 2 AM → previous day's service
                service_date = now.date() - timedelta(days=1)
                start_time = convert_to_extended_time(start_time)
                use_extended_times = True
            else:
                # We're at 10 AM querying for 2 AM → assume today's service
                service_date = now.date()
        else:
            # start_time is 04:00-23:59 → today's service
            service_date = now.date()
    else:
        # No start_time provided, use "now" with late-night logic
        service_date, start_time, use_extended_times = get_gtfs_service_context(now)

    # STEP 2: Handle end_time
    # If we're using extended times, end_time should also be extended when needed.

    if end_time is None:
        # Default to 4 hours past midnight to catch late-night service
        end_time = "28:00:00"
    elif use_extended_times and is_time_in_late_night_range(end_time):
        # end_time is 00:00-03:59 and we're in extended mode → convert it
        end_time = convert_to_extended_time(end_time)

    # STEP 3: Sanity check - fix inverted time ranges (ONLY in extended mode)
    # When in extended mode (querying previous day's service), if start > end
    # and end is not already extended, extend it.
    # Example: start=25:06:00, end=05:00:00 → end should become 29:00:00

    # We ONLY do this in extended mode. In normal mode, inverted ranges like
    # start=14:00, end=08:00 are likely user errors and should return empty
    # results rather than silently expanding to an 18-hour window.

    if use_extended_times:
        start_seconds = safe_gtfs_time_to_seconds(start_time)
        end_seconds = safe_gtfs_time_to_seconds(end_time)

        if (
            start_seconds is not None
            and end_seconds is not None
            and start_seconds > end_seconds
            and not is_extended_time(end_time)
        ):
            end_time = convert_to_extended_time(end_time)

    async with get_db(db_path) as db:
        # Get stop info
        sql = "SELECT stop_id, stop_name, stop_code FROM stops WHERE stop_id = ?"
        async with db.execute(sql, (stop_id,)) as cursor:
            stop_row = await cursor.fetchone()

        if stop_row is None:
            raise ValueError(f"Stop not found: {stop_id}")

        stop_info = StopInfo(
            stop_id=stop_row["stop_id"],
            stop_name=stop_row["stop_name"],
            stop_code=stop_row["stop_code"],
        )

        # Get active service IDs
        active_services = await get_active_service_ids(db, service_date)

        if not active_services:
            # No active services - return empty result
            return GetScheduledArrivalsResponse(
                stop=stop_info,
                arrivals=[],
                service_date=service_date.isoformat(),
                query_time=start_time,
                count=0,
            )

        # Build query for arrivals
        placeholders = ",".join(["?" for _ in active_services])
        params: list[str | int] = [stop_id]
        params.extend(active_services)
        params.extend([start_time, end_time])

        sql = f"""
            SELECT st.trip_id, st.arrival_time, t.route_id, t.trip_headsign,
                   r.route_short_name, r.route_type
            FROM stop_times st
            JOIN trips t ON st.trip_id = t.trip_id
            JOIN routes r ON t.route_id = r.route_id
            WHERE st.stop_id = ?
              AND t.service_id IN ({placeholders})
              AND st.arrival_time >= ?
              AND st.arrival_time <= ?
        """

        # Add route filter if specified
        if route_id is not None:
            sql += " AND t.route_id = ?"
            params.append(route_id)

        sql += " ORDER BY st.arrival_time LIMIT ?"
        params.append(limit)

        async with db.execute(sql, params) as cursor:
            arrival_rows = await cursor.fetchall()

        # Build arrival objects
        arrivals: list[ScheduledArrival] = []
        for row in arrival_rows:
            arrival_time = row["arrival_time"]
            arrivals.append(
                ScheduledArrival(
                    trip_id=row["trip_id"],
                    route_id=row["route_id"],
                    route_short_name=row["route_short_name"],
                    route_type=int(row["route_type"]),
                    trip_headsign=row["trip_headsign"],
                    arrival_time=arrival_time,
                    arrival_time_formatted=format_gtfs_time(arrival_time),
                    minutes_until=calculate_minutes_until(arrival_time, start_time),
                )
            )

        return GetScheduledArrivalsResponse(
            stop=stop_info,
            arrivals=arrivals,
            service_date=service_date.isoformat(),
            query_time=start_time,
            count=len(arrivals),
        )
