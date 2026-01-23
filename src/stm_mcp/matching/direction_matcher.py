"""Fuzzy direction/headsign matching."""

from pathlib import Path

from rapidfuzz import fuzz

from stm_mcp.matching.models import (
    DirectionMatch,
    DirectionResolutionResponse,
    MatchConfidence,
    MatchType,
    confidence_from_score,
)
from stm_mcp.matching.normalizers import normalize_text, strip_direction_prefix
from stm_mcp.matching.search_index import IndexedHeadsign, SearchIndex


def _compute_fuzzy_score(query_normalized: str, target_normalized: str) -> float:
    """Compute fuzzy match score for headsigns."""
    token_score = fuzz.token_set_ratio(query_normalized, target_normalized)
    partial_score = fuzz.partial_ratio(query_normalized, target_normalized)
    return (token_score * 0.7 + partial_score * 0.3)


def _indexed_headsign_to_match(
    headsign: IndexedHeadsign, score: float, match_type: MatchType
) -> DirectionMatch:
    """Convert IndexedHeadsign to DirectionMatch with computed confidence."""
    return DirectionMatch(
        route_id=headsign.route_id,
        direction_id=headsign.direction_id,
        headsign=headsign.headsign,
        score=score,
        confidence=confidence_from_score(score, match_type),
        match_type=match_type,
    )


async def resolve_direction(
    query: str,
    route_id: str,
    direction_id: int | None = None,
    min_score: float = 60.0,
    db_path: Path | None = None,
) -> DirectionResolutionResponse:
    """Resolve a query to matching directions/headsigns for a route.

    Resolution strategy:
    1. Strip direction prefixes ("to ", "vers ", "direction ")
    2. Fuzzy match on trip_headsign for the given route
    3. Optionally filter by direction_id if provided

    Args:
        query: Search query (headsign or destination name)
        route_id: Route ID to find directions for
        direction_id: Optional direction ID to filter results (0 or 1)
        min_score: Minimum score threshold (0-100)
        db_path: Optional database path for index loading

    Returns:
        DirectionResolutionResponse with matches and resolution status
    """
    query = query.strip()
    if not query:
        return DirectionResolutionResponse(
            query=query,
            route_id=route_id,
            direction_id_filter=direction_id,
            matches=[],
            best_match=None,
            resolved=False,
        )

    index = await SearchIndex.get_instance(db_path)
    matches: list[DirectionMatch] = []

    # Get headsigns for this route
    headsigns = index.headsigns_by_route.get(route_id, [])
    if not headsigns:
        return DirectionResolutionResponse(
            query=query,
            route_id=route_id,
            direction_id_filter=direction_id,
            matches=[],
            best_match=None,
            resolved=False,
        )

    # Normalize query and strip direction prefix
    query_cleaned = strip_direction_prefix(query)
    query_normalized = normalize_text(query_cleaned)

    # Track unique (direction_id, headsign) combinations to avoid duplicates
    seen: set[tuple[int, str]] = set()

    for headsign in headsigns:
        # Apply direction_id filter if provided
        if direction_id is not None and headsign.direction_id != direction_id:
            continue

        # Avoid duplicate headsigns
        key = (headsign.direction_id, headsign.headsign)
        if key in seen:
            continue
        seen.add(key)

        # Compute fuzzy score
        score = _compute_fuzzy_score(query_normalized, headsign.normalized_headsign)

        if score >= min_score:
            matches.append(
                _indexed_headsign_to_match(headsign, score, MatchType.FUZZY_NAME)
            )

    # Sort by score descending, then by direction_id for stability
    matches.sort(key=lambda m: (-m.score, m.direction_id, m.headsign))

    # Determine best match and resolved status
    best_match = matches[0] if matches else None
    resolved = (
        best_match is not None
        and best_match.confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH)
    )

    return DirectionResolutionResponse(
        query=query,
        route_id=route_id,
        direction_id_filter=direction_id,
        matches=matches,
        best_match=best_match,
        resolved=resolved,
    )
