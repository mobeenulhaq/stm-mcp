from pathlib import Path

from rapidfuzz import fuzz

from stm_mcp.matching.models import (
    MatchConfidence,
    MatchType,
    StopMatch,
    StopResolutionResponse,
    confidence_from_score,
)
from stm_mcp.matching.normalizers import (
    get_meaningful_tokens,
    normalize_text,
    parse_cross_street,
)
from stm_mcp.matching.search_index import IndexedStation, IndexedStop, SearchIndex

# Fixed score for cross-street matches (prevents them from outscoring exact matches)
CROSS_STREET_SCORE = 85.0
CROSS_STREET_PARTIAL_SCORE = 70.0
STATION_MATCH_THRESHOLD = 90.0

# Implicit cross-street boost when query tokens match both sides of "X / Y" or "X - Y"
IMPLICIT_CROSS_STREET_BOOST = 12.0

# Cross-street separator pattern for stop names
STOP_NAME_SEPARATORS = (" / ", " - ")

# Bonus for stops that are children of a matched station
# Applied when query matches a station name and stop is a platform of that station
STATION_CHILD_BONUS = 10.0


def _compute_fuzzy_score(
    query_normalized: str,
    target_normalized: str,
    query_tokens: set[str] | None = None,
    target_tokens: set[str] | None = None,
) -> float:
    """Compute fuzzy match score using combination of algorithms.

    Uses token_set_ratio (handles word order) combined with partial_ratio
    (handles substrings), blended with token coverage to penalize
    overly-specific matches.

    Args:
        query_normalized: Normalized query string
        target_normalized: Normalized stop name
        query_tokens: Pre-computed meaningful tokens from query (optional)
        target_tokens: Pre-computed meaningful tokens from target (optional)

    Returns:
        Score in 0-100 range
    """
    # Base fuzzy scores
    token_score = fuzz.token_set_ratio(query_normalized, target_normalized)
    partial_score = fuzz.partial_ratio(query_normalized, target_normalized)
    base_score = token_score * 0.7 + partial_score * 0.3

    # Token coverage adjustment
    if query_tokens is None:
        query_tokens = get_meaningful_tokens(query_normalized)
    if target_tokens is None:
        target_tokens = get_meaningful_tokens(target_normalized)

    if query_tokens and target_tokens:
        overlap = query_tokens & target_tokens
        # Query coverage: what fraction of query tokens are found in target?
        # High = target contains all the user's search terms
        query_coverage = len(overlap) / len(query_tokens)
        # Target coverage: what fraction of target tokens match query?
        # Penalizes overly-specific long names
        target_coverage = len(overlap) / len(target_tokens)
        # Combined: weight query coverage more (finding all search terms is important)
        coverage_score = query_coverage * 0.7 + target_coverage * 0.3

        # For single-token queries (e.g., "montroyal", "pieix"), token coverage
        # often fails because the concatenated query doesn't match split tokens.
        # Use partial_ratio directly as it handles substrings well.
        if len(query_tokens) == 1:
            if partial_score >= 75:
                # Good partial match = query overlaps well with target
                # Use partial_score directly, lightly blended with token score
                score = partial_score * 0.85 + token_score * 0.15
            elif base_score >= 60:
                # Decent match, reduce coverage penalty
                score = base_score * 0.85 + (coverage_score * 100) * 0.15
            else:
                score = base_score * 0.70 + (coverage_score * 100) * 0.30
        else:
            # Normal blend: 70% base fuzzy, 30% coverage
            score = base_score * 0.70 + (coverage_score * 100) * 0.30

        # Bonus for full query coverage (all user's search terms found)
        # Scales with query length: more specific queries get bigger bonus
        if query_coverage == 1.0 and len(query_tokens) >= 2:
            score += min(10.0, len(query_tokens) * 4.0)
    else:
        score = base_score

    return min(100.0, score)


def _implicit_cross_street_boost(
    query_tokens: set[str], stop_normalized: str
) -> float:
    """Detect implicit cross-street match and return score boost.

    When a stop name has "X / Y" or "X - Y" format and the query contains
    tokens from both sides, boost the score significantly.

    Example: query "rachel lafontaine" matching "du Parc-La Fontaine / Rachel"
    """
    for sep in STOP_NAME_SEPARATORS:
        if sep in stop_normalized:
            parts = stop_normalized.split(sep, 1)
            if len(parts) == 2:
                left_tokens = get_meaningful_tokens(parts[0])
                right_tokens = get_meaningful_tokens(parts[1])
                # Check if query has tokens from both sides
                hits_left = bool(query_tokens & left_tokens)
                hits_right = bool(query_tokens & right_tokens)
                if hits_left and hits_right:
                    return IMPLICIT_CROSS_STREET_BOOST
    return 0.0


def _find_best_station_match(
    query_normalized: str, stations: list[IndexedStation]
) -> tuple[str, float] | None:
    """Find the best station match for a query.

    Returns (station_stop_id, score) if a station meets threshold, otherwise None.
    """
    best_score = 0.0
    best_station_id: str | None = None

    # Strip "station" from query since users often omit it
    query_clean = query_normalized.replace("station ", "").replace(" station", "")

    for station in stations:
        # Strip "station" from station name for fair comparison
        station_clean = station.normalized_name.replace("station ", "").replace(" station", "")
        score = fuzz.token_set_ratio(query_clean, station_clean)
        if score > best_score:
            best_score = score
            best_station_id = station.stop_id

    if best_station_id and best_score >= STATION_MATCH_THRESHOLD:
        return best_station_id, best_score
    return None


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
    query_tokens = get_meaningful_tokens(query)

    station_preference_parent: str | None = None
    if (
        not cross_streets
        and not any(char.isdigit() for char in query)
        and query_normalized != "station"
    ):
        station_match = _find_best_station_match(query_normalized, index.stations)
        if station_match:
            station_preference_parent = station_match[0]
    fuzzy_candidates: list[tuple[IndexedStop, float]] = []

    for stop in index.stops:
        # Skip if already matched exactly
        if any(m.stop_id == stop.stop_id for m in matches):
            continue

        # Compute base fuzzy score with token coverage
        target_tokens = get_meaningful_tokens(stop.stop_name)
        score = _compute_fuzzy_score(
            query_normalized,
            stop.normalized_name,
            query_tokens=query_tokens,
            target_tokens=target_tokens,
        )

        # Apply implicit cross-street boost if query matches both sides of "X / Y"
        if query_tokens:
            score += _implicit_cross_street_boost(query_tokens, stop.normalized_name)

        # Apply station child bonus if this stop is a platform of the matched station
        if station_preference_parent and stop.parent_station == station_preference_parent:
            score += STATION_CHILD_BONUS

        score = min(100.0, score)  # Cap at 100

        if score >= min_score:
            fuzzy_candidates.append((stop, score))

    # Add fuzzy matches
    for stop, score in fuzzy_candidates:
        matches.append(_indexed_stop_to_match(stop, score, MatchType.FUZZY_NAME))

    # Sort by score descending, prefer child platforms of matched station, then by stop_id
    def station_priority(match: StopMatch) -> int:
        if station_preference_parent:
            stop = index.stops_by_id.get(match.stop_id)
            if stop and stop.parent_station == station_preference_parent:
                return 1
        return 0

    matches.sort(key=lambda m: (-m.score, -station_priority(m), m.stop_id))

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
