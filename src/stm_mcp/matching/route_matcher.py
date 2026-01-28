from pathlib import Path

from rapidfuzz import fuzz

from stm_mcp.matching.models import (
    MatchConfidence,
    MatchType,
    RouteMatch,
    RouteResolutionResponse,
    confidence_from_score,
)
from stm_mcp.matching.normalizers import (
    extract_route_number,
    get_metro_route_id,
    normalize_text,
)
from stm_mcp.matching.search_index import IndexedRoute, SearchIndex


def _compute_fuzzy_score(query_normalized: str, target_normalized: str) -> float:
    """Compute fuzzy match score for route names."""
    token_score = fuzz.token_set_ratio(query_normalized, target_normalized)
    partial_score = fuzz.partial_ratio(query_normalized, target_normalized)
    return (token_score * 0.7 + partial_score * 0.3)


def _indexed_route_to_match(
    route: IndexedRoute, score: float, match_type: MatchType
) -> RouteMatch:
    """Convert IndexedRoute to RouteMatch with computed confidence."""
    return RouteMatch(
        route_id=route.route_id,
        route_short_name=route.route_short_name,
        route_long_name=route.route_long_name,
        route_type=route.route_type,
        score=score,
        confidence=confidence_from_score(score, match_type),
        match_type=match_type,
    )


async def resolve_route(
    query: str,
    limit: int = 5,
    min_score: float = 60.0,
    db_path: Path | None = None,
) -> RouteResolutionResponse:
    """Resolve a query to matching routes.

    Resolution strategy (priority order):
    1. Exact route number match ("24" -> route 24) -> score=100, confidence=EXACT
    2. Metro line alias ("green line", "ligne verte" -> route 1) -> score=100, confidence=EXACT
    3. Fuzzy name match on route_long_name -> score from rapidfuzz

    Args:
        query: Search query (route number, metro alias, or route name)
        limit: Maximum number of results to return
        min_score: Minimum score threshold (0-100)
        db_path: Optional database path for index loading

    Returns:
        RouteResolutionResponse with matches and resolution status
    """
    query = query.strip()
    if not query:
        return RouteResolutionResponse(
            query=query,
            matches=[],
            best_match=None,
            resolved=False,
        )

    index = await SearchIndex.get_instance(db_path)
    matches: list[RouteMatch] = []
    matched_route_ids: set[str] = set()

    # 1. Exact route number match
    route_number = extract_route_number(query)
    if route_number and route_number in index.routes_by_number:
        route = index.routes_by_number[route_number]
        matches.append(_indexed_route_to_match(route, 100.0, MatchType.NUMBER_EXACT))
        matched_route_ids.add(route.route_id)

    # 2. Metro line alias
    metro_route_id = get_metro_route_id(query)
    if (
        metro_route_id
        and metro_route_id not in matched_route_ids
        and metro_route_id in index.routes_by_id
    ):
        route = index.routes_by_id[metro_route_id]
        matches.append(_indexed_route_to_match(route, 100.0, MatchType.METRO_ALIAS))
        matched_route_ids.add(route.route_id)

    # 3. Fuzzy name matching on route_long_name
    query_normalized = normalize_text(query)
    fuzzy_candidates: list[tuple[IndexedRoute, float]] = []

    for route in index.routes:
        # Skip if already matched
        if route.route_id in matched_route_ids:
            continue

        # Try matching on long name
        best_score = 0.0
        if route.normalized_long_name:
            best_score = max(
                best_score,
                _compute_fuzzy_score(query_normalized, route.normalized_long_name),
            )

        # Also try matching on short name if not just a number
        if route.normalized_short_name and not route.route_short_name.isdigit():
            best_score = max(
                best_score,
                _compute_fuzzy_score(query_normalized, route.normalized_short_name),
            )

        if best_score >= min_score:
            fuzzy_candidates.append((route, best_score))

    # Add fuzzy matches
    for route, score in fuzzy_candidates:
        matches.append(_indexed_route_to_match(route, score, MatchType.FUZZY_NAME))

    # Sort by score descending, then by route_id for stability
    matches.sort(key=lambda m: (-m.score, m.route_id))

    # Apply limit
    matches = matches[:limit]

    # Determine best match and resolved status
    best_match = matches[0] if matches else None
    resolved = (
        best_match is not None
        and best_match.confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH)
    )

    return RouteResolutionResponse(
        query=query,
        matches=matches,
        best_match=best_match,
        resolved=resolved,
    )
