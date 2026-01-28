from enum import Enum

from pydantic import BaseModel, Field


class MatchConfidence(str, Enum):
    """Confidence level for a match.

    - EXACT: score=100 AND exact match type (code, ID, number, metro alias)
    - HIGH: score >= 85 (fuzzy matches only)
    - MEDIUM: score >= 70
    - LOW: score >= 60
    """

    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MatchType(str, Enum):
    """Type of match found."""

    # Exact matches (result in EXACT confidence)
    CODE_EXACT = "code_exact"  # Stop code match
    ID_EXACT = "id_exact"  # Stop/route ID match
    NUMBER_EXACT = "number_exact"  # Route number match
    METRO_ALIAS = "metro_alias"  # Metro line alias match

    # Other matches (result in HIGH/MEDIUM/LOW confidence based on score)
    CROSS_STREET = "cross_street"  # Cross-street pattern match
    FUZZY_NAME = "fuzzy_name"  # Fuzzy name match


def confidence_from_score(score: float, match_type: MatchType) -> MatchConfidence:
    """Determine confidence level from score and match type.

    Exact match types always return EXACT confidence.
    Fuzzy matches use score thresholds.
    """
    # Exact match types -> EXACT confidence
    if match_type in (
        MatchType.CODE_EXACT,
        MatchType.ID_EXACT,
        MatchType.NUMBER_EXACT,
        MatchType.METRO_ALIAS,
    ):
        return MatchConfidence.EXACT

    # Score-based confidence for fuzzy matches
    if score >= 85:
        return MatchConfidence.HIGH
    if score >= 70:
        return MatchConfidence.MEDIUM
    return MatchConfidence.LOW


class StopMatch(BaseModel):
    """A matched stop with confidence information."""

    stop_id: str
    stop_code: str | None = None
    stop_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None
    score: float = Field(description="Match score (0-100)")
    confidence: MatchConfidence = Field(description="Confidence level of the match")
    match_type: MatchType = Field(description="Type of match")


class StopResolutionResponse(BaseModel):
    """Response from resolve_stop tool."""

    query: str = Field(description="Original query string")
    matches: list[StopMatch] = Field(description="Matched stops, ordered by score")
    best_match: StopMatch | None = Field(
        default=None, description="Best match (always set to top match when matches exist)"
    )
    resolved: bool = Field(
        description="True if best_match has EXACT or HIGH confidence (safe to auto-use)"
    )


class RouteMatch(BaseModel):
    """A matched route with confidence information."""

    route_id: str
    route_short_name: str | None = Field(default=None, description="Route number or short name")
    route_long_name: str | None = Field(default=None, description="Full route name")
    route_type: int = Field(description="1=metro, 3=bus")
    score: float = Field(description="Match score (0-100)")
    confidence: MatchConfidence = Field(description="Confidence level of the match")
    match_type: MatchType = Field(description="Type of match")


class RouteResolutionResponse(BaseModel):
    """Response from resolve_route tool."""

    query: str = Field(description="Original query string")
    matches: list[RouteMatch] = Field(description="Matched routes, ordered by score")
    best_match: RouteMatch | None = Field(
        default=None, description="Best match (always set to top match when matches exist)"
    )
    resolved: bool = Field(
        description="True if best_match has EXACT or HIGH confidence (safe to auto-use)"
    )


class DirectionMatch(BaseModel):
    """A matched direction/headsign with confidence information."""

    route_id: str
    direction_id: int = Field(description="Direction ID (0 or 1)")
    headsign: str = Field(description="Trip headsign (destination)")
    score: float = Field(description="Match score (0-100)")
    confidence: MatchConfidence = Field(description="Confidence level of the match")
    match_type: MatchType = Field(description="Type of match")


class DirectionResolutionResponse(BaseModel):
    """Response from resolve_direction tool."""

    query: str = Field(description="Original query string")
    route_id: str = Field(description="Route ID used for matching")
    direction_id_filter: int | None = Field(
        default=None, description="Direction ID filter if provided"
    )
    matches: list[DirectionMatch] = Field(description="Matched directions, ordered by score")
    best_match: DirectionMatch | None = Field(
        default=None, description="Best match (always set to top match when matches exist)"
    )
    resolved: bool = Field(
        description="True if best_match has EXACT or HIGH confidence (safe to auto-use)"
    )
