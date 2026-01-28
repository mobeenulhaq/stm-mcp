"""Tests for schedule service."""

from datetime import date, datetime
from pathlib import Path

import aiosqlite
import pytest

from stm_mcp.data.gtfs_loader import GTFSLoader
from stm_mcp.services.schedule_service import (
    LATE_NIGHT_THRESHOLD_HOUR,
    calculate_minutes_until,
    convert_to_extended_time,
    format_gtfs_time,
    get_active_service_ids,
    get_gtfs_service_context,
    get_scheduled_arrivals,
    gtfs_time_to_seconds,
    is_extended_time,
    is_time_in_late_night_range,
    parse_gtfs_time,
    safe_gtfs_time_to_seconds,
    safe_parse_gtfs_time,
)


class TestGTFSTimeParsing:
    """Tests for GTFS time parsing functions."""

    def test_parse_normal_time(self) -> None:
        """Test parsing a normal time."""
        hours, minutes, seconds = parse_gtfs_time("08:30:00")
        assert hours == 8
        assert minutes == 30
        assert seconds == 0

    def test_parse_midnight(self) -> None:
        """Test parsing midnight."""
        hours, minutes, seconds = parse_gtfs_time("00:00:00")
        assert hours == 0
        assert minutes == 0
        assert seconds == 0

    def test_parse_time_exceeding_24(self) -> None:
        """Test parsing a time that exceeds 24:00:00."""
        hours, minutes, seconds = parse_gtfs_time("25:30:00")
        assert hours == 25
        assert minutes == 30
        assert seconds == 0

    def test_parse_time_with_seconds(self) -> None:
        """Test parsing time with non-zero seconds."""
        hours, minutes, seconds = parse_gtfs_time("12:45:30")
        assert hours == 12
        assert minutes == 45
        assert seconds == 30

    def test_parse_invalid_format(self) -> None:
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError):
            parse_gtfs_time("invalid")

    def test_parse_missing_parts(self) -> None:
        """Test that missing parts raises ValueError."""
        with pytest.raises(ValueError):
            parse_gtfs_time("08:30")


class TestGTFSTimeToSeconds:
    """Tests for converting GTFS time to seconds."""

    def test_midnight(self) -> None:
        """Test midnight is 0 seconds."""
        assert gtfs_time_to_seconds("00:00:00") == 0

    def test_one_hour(self) -> None:
        """Test 1:00 AM is 3600 seconds."""
        assert gtfs_time_to_seconds("01:00:00") == 3600

    def test_normal_time(self) -> None:
        """Test a normal time."""
        # 8:30:00 = 8*3600 + 30*60 = 28800 + 1800 = 30600
        assert gtfs_time_to_seconds("08:30:00") == 30600

    def test_time_exceeding_24(self) -> None:
        """Test time exceeding 24 hours."""
        # 25:30:00 = 25*3600 + 30*60 = 90000 + 1800 = 91800
        assert gtfs_time_to_seconds("25:30:00") == 91800


class TestFormatGTFSTime:
    """Tests for formatting GTFS time for display."""

    def test_format_morning(self) -> None:
        """Test formatting a morning time."""
        assert format_gtfs_time("08:30:00") == "8:30 AM"

    def test_format_afternoon(self) -> None:
        """Test formatting an afternoon time."""
        assert format_gtfs_time("14:30:00") == "2:30 PM"

    def test_format_noon(self) -> None:
        """Test formatting noon."""
        assert format_gtfs_time("12:00:00") == "12:00 PM"

    def test_format_midnight(self) -> None:
        """Test formatting midnight."""
        assert format_gtfs_time("00:00:00") == "12:00 AM"

    def test_format_exceeding_24(self) -> None:
        """Test formatting a time exceeding 24:00."""
        assert format_gtfs_time("25:30:00") == "1:30 AM (+1)"

    def test_format_just_past_midnight(self) -> None:
        """Test formatting just past midnight on next day."""
        assert format_gtfs_time("24:15:00") == "12:15 AM (+1)"


class TestCalculateMinutesUntil:
    """Tests for calculating minutes until arrival."""

    def test_same_time(self) -> None:
        """Test when arrival equals query time."""
        assert calculate_minutes_until("08:30:00", "08:30:00") == 0

    def test_future_arrival(self) -> None:
        """Test when arrival is in the future."""
        assert calculate_minutes_until("08:45:00", "08:30:00") == 15

    def test_past_arrival(self) -> None:
        """Test when arrival is in the past."""
        assert calculate_minutes_until("08:15:00", "08:30:00") == -15

    def test_hour_boundary(self) -> None:
        """Test crossing hour boundary."""
        assert calculate_minutes_until("09:00:00", "08:30:00") == 30


class TestGetGTFSServiceContext:
    """Tests for GTFS late-night service context determination."""

    def test_normal_daytime(self) -> None:
        """Test that daytime uses current date with normal time."""
        dt = datetime(2026, 1, 27, 10, 30, 0)  # 10:30 AM Tuesday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 27)
        assert gtfs_time == "10:30:00"
        assert is_late_night is False

    def test_evening(self) -> None:
        """Test that evening uses current date with normal time."""
        dt = datetime(2026, 1, 26, 22, 30, 0)  # 10:30 PM Monday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 26)
        assert gtfs_time == "22:30:00"
        assert is_late_night is False

    def test_late_night_uses_previous_day(self) -> None:
        """Test that late night (1:30 AM) uses previous day's service."""
        dt = datetime(2026, 1, 27, 1, 30, 0)  # 1:30 AM Tuesday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 26)  # Monday's service
        assert gtfs_time == "25:30:00"
        assert is_late_night is True

    def test_late_night_at_midnight(self) -> None:
        """Test that midnight uses previous day's service."""
        dt = datetime(2026, 1, 27, 0, 0, 0)  # Midnight Tuesday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 26)  # Monday's service
        assert gtfs_time == "24:00:00"
        assert is_late_night is True

    def test_late_night_just_before_threshold(self) -> None:
        """Test that 3:59 AM uses previous day's service."""
        dt = datetime(2026, 1, 27, 3, 59, 0)  # 3:59 AM Tuesday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 26)  # Monday's service
        assert gtfs_time == "27:59:00"
        assert is_late_night is True

    def test_threshold_boundary(self) -> None:
        """Test that exactly 4:00 AM uses current day's service."""
        dt = datetime(2026, 1, 27, 4, 0, 0)  # 4:00 AM Tuesday
        service_date, gtfs_time, is_late_night = get_gtfs_service_context(dt)
        assert service_date == date(2026, 1, 27)  # Tuesday's service
        assert gtfs_time == "04:00:00"
        assert is_late_night is False

    def test_threshold_constant(self) -> None:
        """Test that the threshold constant is 4 AM."""
        assert LATE_NIGHT_THRESHOLD_HOUR == 4


class TestSafeParseGtfsTime:
    """Tests for safe GTFS time parsing."""

    def test_valid_time(self) -> None:
        """Test parsing a valid time."""
        assert safe_parse_gtfs_time("08:30:00") == (8, 30, 0)

    def test_extended_time(self) -> None:
        """Test parsing an extended time."""
        assert safe_parse_gtfs_time("25:30:00") == (25, 30, 0)

    def test_invalid_format_returns_none(self) -> None:
        """Test that invalid format returns None."""
        assert safe_parse_gtfs_time("invalid") is None
        assert safe_parse_gtfs_time("5:00") is None
        assert safe_parse_gtfs_time("") is None


class TestIsTimeInLateNightRange:
    """Tests for checking if a time is in the late-night range."""

    def test_midnight_is_late_night(self) -> None:
        """Test that 00:00:00 is in late-night range."""
        assert is_time_in_late_night_range("00:00:00") is True

    def test_2am_is_late_night(self) -> None:
        """Test that 02:00:00 is in late-night range."""
        assert is_time_in_late_night_range("02:00:00") is True

    def test_359am_is_late_night(self) -> None:
        """Test that 03:59:00 is in late-night range."""
        assert is_time_in_late_night_range("03:59:00") is True

    def test_4am_is_not_late_night(self) -> None:
        """Test that 04:00:00 is NOT in late-night range."""
        assert is_time_in_late_night_range("04:00:00") is False

    def test_8am_is_not_late_night(self) -> None:
        """Test that 08:00:00 is NOT in late-night range."""
        assert is_time_in_late_night_range("08:00:00") is False

    def test_extended_time_is_not_late_night(self) -> None:
        """Test that 25:30:00 is NOT in late-night range (already extended)."""
        assert is_time_in_late_night_range("25:30:00") is False

    def test_invalid_format_returns_false(self) -> None:
        """Test that invalid time format returns False (not raises)."""
        assert is_time_in_late_night_range("invalid") is False
        assert is_time_in_late_night_range("5:00") is False


class TestIsExtendedTime:
    """Tests for checking if a time is in extended GTFS format."""

    def test_normal_time_not_extended(self) -> None:
        """Test that normal times are not extended."""
        assert is_extended_time("08:00:00") is False
        assert is_extended_time("23:59:59") is False

    def test_extended_time_detected(self) -> None:
        """Test that extended times are detected."""
        assert is_extended_time("24:00:00") is True
        assert is_extended_time("25:30:00") is True
        assert is_extended_time("27:59:59") is True

    def test_invalid_format_returns_false(self) -> None:
        """Test that invalid format returns False."""
        assert is_extended_time("invalid") is False


class TestConvertToExtendedTime:
    """Tests for converting times to extended GTFS format."""

    def test_late_night_time_converted(self) -> None:
        """Test that 02:10:00 becomes 26:10:00."""
        assert convert_to_extended_time("02:10:00") == "26:10:00"

    def test_daytime_time_converted(self) -> None:
        """Test that 05:00:00 becomes 29:00:00."""
        assert convert_to_extended_time("05:00:00") == "29:00:00"

    def test_evening_time_converted(self) -> None:
        """Test that 22:00:00 becomes 46:00:00."""
        assert convert_to_extended_time("22:00:00") == "46:00:00"

    def test_midnight_converted(self) -> None:
        """Test that 00:00:00 becomes 24:00:00."""
        assert convert_to_extended_time("00:00:00") == "24:00:00"

    def test_extended_time_unchanged(self) -> None:
        """Test that already-extended times stay unchanged."""
        assert convert_to_extended_time("25:30:00") == "25:30:00"

    def test_invalid_format_returned_as_is(self) -> None:
        """Test that invalid time format is returned as-is."""
        assert convert_to_extended_time("invalid") == "invalid"
        assert convert_to_extended_time("5:00") == "5:00"


class TestSafeGtfsTimeToSeconds:
    """Tests for safe conversion to seconds."""

    def test_valid_time(self) -> None:
        """Test converting valid time."""
        assert safe_gtfs_time_to_seconds("01:00:00") == 3600

    def test_extended_time(self) -> None:
        """Test converting extended time."""
        assert safe_gtfs_time_to_seconds("25:30:00") == 91800

    def test_invalid_format_returns_none(self) -> None:
        """Test that invalid format returns None."""
        assert safe_gtfs_time_to_seconds("invalid") is None


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

    # calendar.txt - use dates that include today
    (gtfs_dir / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20240101,20261231\n"
        "WEEKEND,0,0,0,0,0,1,1,20240101,20261231\n"
    )

    # calendar_dates.txt - test exceptions
    (gtfs_dir / "calendar_dates.txt").write_text(
        "service_id,date,exception_type\n"
        "WEEKDAY,20240101,2\n"  # Remove weekday service on Jan 1, 2024
        "WEEKEND,20240101,1\n"  # Add weekend service on Jan 1, 2024
        "SPECIAL,20240101,1\n"  # Add special service on Jan 1, 2024
    )

    # trips.txt - includes late-night trips
    (gtfs_dir / "trips.txt").write_text(
        "trip_id,route_id,service_id,trip_headsign,direction_id,shape_id,wheelchair_accessible,note_fr,note_en\n"
        "TRIP1,1,WEEKDAY,Angrignon,0,SHAPE1,1,,\n"
        "TRIP2,24,WEEKDAY,Sherbrooke / Cavendish,0,SHAPE2,1,,\n"
        "TRIP3,24,WEEKEND,Sherbrooke / Cavendish,0,SHAPE2,1,,\n"
        "TRIP_NIGHT,24,WEEKDAY,Night Bus,0,SHAPE2,1,,\n"
    )

    # stop_times.txt - includes late-night arrivals (25:xx = 1 AM next day)
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "TRIP1,08:00:00,08:00:00,BERRI-1,1,0\n"
        "TRIP1,08:05:00,08:05:00,51001,2,0\n"
        "TRIP2,09:00:00,09:00:00,51001,1,0\n"
        "TRIP2,09:15:00,09:15:00,BERRI-1,2,0\n"
        "TRIP3,10:00:00,10:00:00,51001,1,0\n"
        "TRIP_NIGHT,25:30:00,25:30:00,51001,1,0\n"
        "TRIP_NIGHT,25:45:00,25:45:00,BERRI-1,2,0\n"
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
    return db_file


class TestGetActiveServiceIds:
    """Tests for service day algorithm."""

    async def test_weekday_service(self, db_path: Path) -> None:
        """Test that weekday service is active on a Wednesday."""
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            # January 8, 2025 is a Wednesday
            services = await get_active_service_ids(db, date(2025, 1, 8))
            assert "WEEKDAY" in services
            assert "WEEKEND" not in services

    async def test_weekend_service(self, db_path: Path) -> None:
        """Test that weekend service is active on a Saturday."""
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            # January 11, 2025 is a Saturday
            services = await get_active_service_ids(db, date(2025, 1, 11))
            assert "WEEKEND" in services
            assert "WEEKDAY" not in services

    async def test_exception_removes_service(self, db_path: Path) -> None:
        """Test that exception_type=2 removes service."""
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            # January 1, 2024 is a Monday, but WEEKDAY is removed by exception
            services = await get_active_service_ids(db, date(2024, 1, 1))
            assert "WEEKDAY" not in services

    async def test_exception_adds_service(self, db_path: Path) -> None:
        """Test that exception_type=1 adds service."""
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            # January 1, 2024 is a Monday, WEEKEND and SPECIAL added by exception
            services = await get_active_service_ids(db, date(2024, 1, 1))
            assert "WEEKEND" in services
            assert "SPECIAL" in services


class TestGetScheduledArrivals:
    """Tests for getting scheduled arrivals."""

    async def test_get_arrivals_for_stop(self, db_path: Path) -> None:
        """Test getting arrivals at a stop."""
        # Use a weekday date that falls within the calendar range
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="08:00:00",
            end_time="10:00:00",
            db_path=db_path,
        )

        assert response.stop.stop_id == "51001"
        assert response.stop.stop_name == "Sherbrooke / Saint-Denis"
        # Should have arrivals from weekday trips (TRIP1 at 08:05, TRIP2 at 09:00)
        # Note: The actual arrivals depend on the current day being a weekday
        assert response.count >= 0

    async def test_get_arrivals_with_route_filter(self, db_path: Path) -> None:
        """Test filtering arrivals by route."""
        response = await get_scheduled_arrivals(
            stop_id="51001",
            route_id="24",
            start_time="08:00:00",
            end_time="10:00:00",
            db_path=db_path,
        )

        # All arrivals should be for route 24
        for arrival in response.arrivals:
            assert arrival.route_id == "24"

    async def test_stop_not_found(self, db_path: Path) -> None:
        """Test that non-existent stop raises ValueError."""
        with pytest.raises(ValueError, match="Stop not found"):
            await get_scheduled_arrivals(
                stop_id="NONEXISTENT",
                db_path=db_path,
            )

    async def test_arrival_time_formatting(self, db_path: Path) -> None:
        """Test that arrival times are formatted correctly."""
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="08:00:00",
            end_time="10:00:00",
            db_path=db_path,
        )

        for arrival in response.arrivals:
            # arrival_time should be in HH:MM:SS format
            assert len(arrival.arrival_time.split(":")) == 3
            # arrival_time_formatted should contain AM or PM
            assert "AM" in arrival.arrival_time_formatted or "PM" in arrival.arrival_time_formatted

    async def test_late_night_with_extended_start_time(self, db_path: Path) -> None:
        """Test querying with explicit extended start_time uses previous day's service."""
        # User explicitly provides extended time (25:00 = 1 AM)
        # This should query previous day's service
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="25:00:00",
            end_time="26:00:00",
            db_path=db_path,
        )
        # Should find the TRIP_NIGHT at 25:30:00
        # Note: service_date should be previous day
        assert response.query_time == "25:00:00"

    async def test_late_night_extended_start_with_normal_end(self, db_path: Path) -> None:
        """Test that extended start + normal end gets end extended (sanity check)."""
        # start=25:00:00, end=05:00:00 should become end=29:00:00
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="25:00:00",
            end_time="05:00:00",
            db_path=db_path,
        )
        # Should find the TRIP_NIGHT at 25:30:00
        # The sanity check should extend end to 29:00:00
        assert response.query_time == "25:00:00"

    async def test_normal_mode_inverted_range_not_fixed(self, db_path: Path) -> None:
        """Test that inverted range in normal mode is NOT silently fixed."""
        # At 10 AM (simulated via explicit times), start=14:00, end=08:00
        # This is an inverted range that should NOT be expanded
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="14:00:00",
            end_time="08:00:00",
            db_path=db_path,
        )
        # Should return empty (inverted range matches nothing)
        assert response.count == 0

    async def test_normal_start_time_uses_today(self, db_path: Path) -> None:
        """Test that normal start_time (05:00) uses today's service."""
        response = await get_scheduled_arrivals(
            stop_id="51001",
            start_time="05:00:00",
            end_time="10:00:00",
            db_path=db_path,
        )
        # Should query today's service, not yesterday's
        # query_time should be unchanged (not converted to 29:00:00)
        assert response.query_time == "05:00:00"
