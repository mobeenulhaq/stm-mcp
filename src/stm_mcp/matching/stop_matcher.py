"""Fuzzy stop matching."""

from pathlib import Path

from rapidfuzz import fuzz

from stm_mcp.matching.models import (
    MatchConfidence,
    MatchType,
    StopMatch,
    StopResolutionResponse,
    confidence_from_score,
)
from stm_mcp.matching.normalizers import normalize_text, parse_cross_street
from stm_mcp.matching.search_index import IndexedStop, SearchIndex

# Fixed score for cross-street matches (prevents them from outscoring exact matches)
CROSS_STREET_SCORE = 85.0
CROSS_STREET_PARTIAL_SCORE = 70.0


def _compute_fuzzy_score(query_normalized: str, target_normalized: str) -> float:
    """Compute fuzzy match score using combination of algorithms.

    Uses token_set_ratio (handles word order) combined with partial_ratio
    (handles substrings) for best results with transit stop names.
    """
    token_score = fuzz.token_set_ratio(query_normalized, target_normalized)
    partial_score = fuzz.partial_ratio(query_normalized, target_normalized)
    # Weight token_set more heavily as it handles variations better
    return (token_score * 0.7 + partial_score * 0.3)


def _match_cross_street(
    streets: tuple[str, str], stops: list[IndexedStop]
) -> list[tuple[IndexedStop, float]]:
    """Find stops matching a cross-street pattern.

    Returns list of (stop, score) tuples for stops containing both streets.
    """
    street1, street2 = streets
    matches: list[tuple[IndexedStop, float]] = []

    for stop in stops:
        name = stop.normalized_name
        has_street1 = street1 in name
        has_street2 = street2 in name

        if has_street1 and has_street2:
            # Both streets found -> fixed high score
            matches.append((stop, CROSS_STREET_SCORE))
        elif has_street1 or has_street2:
            # Only one street found -> partial match
            matches.append((stop, CROSS_STREET_PARTIAL_SCORE))

    return matches


def _indexed_stop_to_match(
    stop: IndexedStop, score: float, match_type: MatchType
) -> StopMatch:
    """Convert IndexedStop to StopMatch with computed confidence."""
    return StopMatch(
        stop_id=stop.stop_id,
        stop_code=stop.stop_code,
        stop_name=stop.stop_name,
        stop_lat=stop.stop_lat,
        stop_lon=stop.stop_lon,
        score=score,
        confidence=confidence_from_score(score, match_type),
        match_type=match_type,
    )


async def resolve_stop(
    query: str,
    limit: int = 5,
    min_score: float = 60.0,
    db_path: Path | None = None,
) -> StopResolutionResponse:
    """Resolve a query to matching stops.

    Resolution strategy (priority order):
    1. Exact stop_code match -> score=100, confidence=EXACT
    2. Exact stop_id match -> score=100, confidence=EXACT
    3. Cross-street pattern matching -> fixed score=85, confidence=HIGH
    4. Fuzzy name matching -> score from rapidfuzz

    Args:
        query: Search query (stop code, name, or cross-street pattern)
        limit: Maximum number of results to return
        min_score: Minimum score threshold (0-100)
        db_path: Optional database path for index loading

    Returns:
        StopResolutionResponse with matches and resolution status
    """
    query = query.strip()
    if not query:
        return StopResolutionResponse(
            query=query,
            matches=[],
            best_match=None,
            resolved=False,
        )

    index = await SearchIndex.get_instance(db_path)
    matches: list[StopMatch] = []

    # 1. Exact stop_code match
    if query in index.stops_by_code:
        stop = index.stops_by_code[query]
        matches.append(_indexed_stop_to_match(stop, 100.0, MatchType.CODE_EXACT))

    # 2. Exact stop_id match (if not already matched by code)
    if not matches and query in index.stops_by_id:
        stop = index.stops_by_id[query]
        matches.append(_indexed_stop_to_match(stop, 100.0, MatchType.ID_EXACT))

    # 3. Cross-street pattern matching
    cross_streets = parse_cross_street(query)
    if cross_streets:
        cross_matches = _match_cross_street(cross_streets, index.stops)
        for stop, score in cross_matches:
            if score >= min_score:
                matches.append(_indexed_stop_to_match(stop, score, MatchType.CROSS_STREET))

    # 4. Fuzzy name matching
    query_normalized = normalize_text(query)
    fuzzy_candidates: list[tuple[IndexedStop, float]] = []

    for stop in index.stops:
        # Skip if already matched exactly
        if any(m.stop_id == stop.stop_id for m in matches):
            continue

        score = _compute_fuzzy_score(query_normalized, stop.normalized_name)
        if score >= min_score:
            fuzzy_candidates.append((stop, score))

    # Add fuzzy matches
    for stop, score in fuzzy_candidates:
        matches.append(_indexed_stop_to_match(stop, score, MatchType.FUZZY_NAME))

    # Sort by score descending, then by stop_id for stability
    matches.sort(key=lambda m: (-m.score, m.stop_id))

    # Apply limit
    matches = matches[:limit]

    # Determine best match and resolved status
    best_match = matches[0] if matches else None
    resolved = (
        best_match is not None
        and best_match.confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH)
    )

    return StopResolutionResponse(
        query=query,
        matches=matches,
        best_match=best_match,
        resolved=resolved,
    )
