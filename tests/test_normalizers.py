"""Tests for text normalization utilities."""

from stm_mcp.matching.normalizers import (
    extract_route_number,
    get_metro_route_id,
    normalize_text,
    parse_cross_street,
    remove_accents,
    strip_direction_prefix,
)


class TestRemoveAccents:
    """Tests for accent removal."""

    def test_remove_accents_basic(self) -> None:
        """Test basic accent removal."""
        assert remove_accents("Préfontaine") == "Prefontaine"
        assert remove_accents("Côte-des-Neiges") == "Cote-des-Neiges"
        assert remove_accents("Crémazie") == "Cremazie"

    def test_remove_accents_no_change(self) -> None:
        """Test that text without accents is unchanged."""
        assert remove_accents("McGill") == "McGill"
        assert remove_accents("Sherbrooke") == "Sherbrooke"


class TestNormalizeText:
    """Tests for full text normalization."""

    def test_normalize_lowercase(self) -> None:
        """Test conversion to lowercase."""
        result = normalize_text("BERRI-UQAM")
        assert result == "berri-uqam"

    def test_normalize_accents(self) -> None:
        """Test accent removal in normalization."""
        result = normalize_text("Préfontaine")
        assert result == "prefontaine"

    def test_normalize_abbreviation_saint(self) -> None:
        """Test Saint abbreviation expansion."""
        assert normalize_text("St-Michel") == "saint-michel"
        assert normalize_text("St Michel") == "saint michel"

    def test_normalize_combined(self) -> None:
        """Test combined normalizations."""
        result = normalize_text("St-Michel / Boul. Crémazie")
        assert result == "saint-michel / boulevard cremazie"


class TestParseCrossStreet:
    """Tests for cross-street pattern parsing."""

    def test_parse_at_separator(self) -> None:
        """Test 'at' separator."""
        result = parse_cross_street("Sherbrooke at Berri")
        assert result == ("sherbrooke", "berri")

    def test_parse_slash_separator(self) -> None:
        """Test '/' separator."""
        result = parse_cross_street("Sherbrooke / Berri")
        assert result == ("sherbrooke", "berri")

    def test_parse_with_abbreviations(self) -> None:
        """Test cross-street with abbreviations."""
        result = parse_cross_street("St-Denis at Boul. Rosemont")
        assert result == ("saint-denis", "boulevard rosemont")


class TestStripDirectionPrefix:
    """Tests for direction prefix stripping."""

    def test_strip_to_prefix(self) -> None:
        """Test stripping 'to' prefix."""
        assert strip_direction_prefix("to Angrignon") == "Angrignon"

    def test_strip_direction_prefix(self) -> None:
        """Test stripping 'direction' prefix."""
        assert strip_direction_prefix("direction Downtown") == "Downtown"

    def test_strip_preserves_case(self) -> None:
        """Test that case is preserved after prefix removal."""
        assert strip_direction_prefix("TO Angrignon") == "Angrignon"


class TestExtractRouteNumber:
    """Tests for route number extraction."""

    def test_extract_plain_number(self) -> None:
        """Test extracting plain number."""
        assert extract_route_number("24") == "24"
        assert extract_route_number("747") == "747"

    def test_extract_route_prefix(self) -> None:
        """Test extracting with 'route' prefix."""
        assert extract_route_number("route 24") == "24"
        assert extract_route_number("Route 747") == "747"

    def test_extract_hash_prefix(self) -> None:
        """Test extracting with '#' prefix."""
        assert extract_route_number("#24") == "24"

    def test_extract_no_prefix(self) -> None:
        """Test extracting with 'no.' prefix."""
        assert extract_route_number("no. 24") == "24"
        assert extract_route_number("no 80") == "80"

    def test_extract_non_number(self) -> None:
        """Test that non-numbers return None."""
        assert extract_route_number("green line") is None
        assert extract_route_number("sherbrooke") is None


class TestGetMetroRouteId:
    """Tests for metro line alias resolution."""

    def test_green_line_english(self) -> None:
        """Test Green line aliases."""
        assert get_metro_route_id("green") == "1"
        assert get_metro_route_id("green line") == "1"
        assert get_metro_route_id("Green Line") == "1"

    def test_green_line_french(self) -> None:
        """Test Green line French aliases."""
        assert get_metro_route_id("verte") == "1"
        assert get_metro_route_id("ligne verte") == "1"

    def test_non_metro(self) -> None:
        """Test that non-metro queries return None."""
        assert get_metro_route_id("bus 24") is None
        assert get_metro_route_id("sherbrooke") is None
        assert get_metro_route_id("24") is None
