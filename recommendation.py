"""Top-K recommendation selection."""

from __future__ import annotations

from typing import Iterable, List, Sequence

from route_scoring import ScoredRoute


def _route_overlap_ratio(route_a: ScoredRoute, route_b: ScoredRoute) -> float:
    set_a = set(route_a.route.poi_route[:-1])
    set_b = set(route_b.route.poi_route[:-1])
    union = set_a.union(set_b)
    if not union:
        return 0.0
    return len(set_a.intersection(set_b)) / len(union)


def _sort_pool(
    routes: Iterable[ScoredRoute],
    start_poi: str | None,
) -> List[ScoredRoute]:
    if start_poi:
        return sorted(
            routes,
            key=lambda item: (
                item.route.start_distance_km
                if item.route.start_distance_km is not None
                else float("inf"),
                -item.score,
                -item.route.unique_poi_count,
                item.route.poi_route,
            ),
        )
    return sorted(
        routes,
        key=lambda item: (
            -item.score,
            -item.route.unique_poi_count,
            item.route.poi_route,
        ),
    )


def _select_diverse(
    *,
    pool: Sequence[ScoredRoute],
    selected: List[ScoredRoute],
    used_signatures: set[tuple[str, ...]],
    similarity_threshold: float,
    top_k: int,
    allow_overlap: bool,
) -> None:
    for candidate in pool:
        signature = candidate.route.canonical_cycle_signature
        if signature in used_signatures:
            continue

        if not allow_overlap:
            too_similar = any(
                _route_overlap_ratio(candidate, chosen) > similarity_threshold
                for chosen in selected
            )
            if too_similar:
                continue

        selected.append(candidate)
        used_signatures.add(signature)
        if len(selected) >= top_k:
            return


def _final_sort_key(item: ScoredRoute, start_poi: str | None) -> tuple:
    if start_poi:
        return (
            item.route.start_distance_km
            if item.route.start_distance_km is not None
            else float("inf"),
            -item.score,
            -item.route.unique_poi_count,
            item.route.poi_route,
        )
    return (
        -item.score,
        -item.route.unique_poi_count,
        item.route.poi_route,
    )


def top_k_recommendations(
    scored_routes: List[ScoredRoute],
    top_k: int,
    start_poi: str | None = None,
    must_include_pois: Sequence[str] | None = None,
    similarity_threshold: float = 0.80,
) -> List[ScoredRoute]:
    """Return the final Top-K recommendations with cycle-level dedup."""
    if top_k <= 0 or not scored_routes:
        return []

    pool = list(scored_routes)
    must_set = set(must_include_pois or [])
    if must_set:
        full_matches = [
            item for item in pool if item.route.must_include_match_count >= len(must_set)
        ]
        if full_matches:
            pool = full_matches
        else:
            max_match = max(item.route.must_include_match_count for item in pool)
            pool = [item for item in pool if item.route.must_include_match_count == max_match]

    if start_poi:
        contains_start = [item for item in pool if start_poi in set(item.route.poi_route[:-1])]
        if contains_start:
            pool = contains_start

    if not pool:
        return []

    sorted_pool = _sort_pool(pool, start_poi=start_poi)
    selected: List[ScoredRoute] = []
    used_signatures: set[tuple[str, ...]] = set()

    _select_diverse(
        pool=sorted_pool,
        selected=selected,
        used_signatures=used_signatures,
        similarity_threshold=similarity_threshold,
        top_k=top_k,
        allow_overlap=False,
    )
    if len(selected) < top_k:
        _select_diverse(
            pool=sorted_pool,
            selected=selected,
            used_signatures=used_signatures,
            similarity_threshold=similarity_threshold,
            top_k=top_k,
            allow_overlap=True,
        )

    selected.sort(key=lambda item: _final_sort_key(item, start_poi))
    return selected
