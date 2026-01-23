"""Fuzzy matching for stops, routes, and directions."""

from stm_mcp.matching.direction_matcher import resolve_direction
from stm_mcp.matching.models import (
    DirectionMatch,
    DirectionResolutionResponse,
    MatchConfidence,
    MatchType,
    RouteMatch,
    RouteResolutionResponse,
    StopMatch,
    StopResolutionResponse,
)
from stm_mcp.matching.normalizers import (
    extract_route_number,
    get_metro_route_id,
    normalize_text,
    parse_cross_street,
    remove_accents,
    strip_direction_prefix,
)
from stm_mcp.matching.route_matcher import resolve_route
from stm_mcp.matching.search_index import SearchIndex
from stm_mcp.matching.stop_matcher import resolve_stop

__all__ = [
    # Matchers
    "resolve_stop",
    "resolve_route",
    "resolve_direction",
    # Index
    "SearchIndex",
    # Models
    "MatchConfidence",
    "MatchType",
    "StopMatch",
    "StopResolutionResponse",
    "RouteMatch",
    "RouteResolutionResponse",
    "DirectionMatch",
    "DirectionResolutionResponse",
    # Normalizers
    "normalize_text",
    "remove_accents",
    "parse_cross_street",
    "strip_direction_prefix",
    "extract_route_number",
    "get_metro_route_id",
]
