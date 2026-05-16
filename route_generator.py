"""Route generation and personalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from config import DEFAULT_CONFIG, PipelineConfig
from gba_algorithm import CircularPattern
from seasonality import compute_dominant_supporting_season, compute_route_season_fit
from utils import haversine_km


def _canonical_cycle_signature(nodes: Sequence[str]) -> Tuple[str, ...]:
    """Normalize a cycle core up to rotation."""
    core = list(nodes)
    if not core:
        return tuple()
    rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
    return min(rotations)


@dataclass(frozen=True)
class RouteCandidate:
    """A route generated from a mined circular pattern."""

    poi_route: Tuple[str, ...]
    avg_pair_tpi: float
    cycle_support: int
    cycle_tpi: float
    cycle_strength_global: float
    supporting_trajectory_ids: frozenset[str]
    categories: Tuple[str, ...]
    path_length: int
    unique_poi_count: int
    canonical_cycle_signature: Tuple[str, ...]
    start_distance_km: float | None = None
    must_include_match_count: int = 0
    must_include_total_count: int = 0
    start_fit_score: float = 1.0
    must_visit_fit_score: float = 1.0
    dominant_supporting_season: str | None = None
    season_fit_score: float = 1.0
    season_match_count: int = 0
    season_total_count: int = 0

    @property
    def avg_tpi(self) -> float:
        """Backward-compatible alias."""
        return self.avg_pair_tpi

    @property
    def cycle_strength(self) -> float:
        """Backward-compatible alias."""
        return self.cycle_strength_global


@dataclass(frozen=True)
class PersonalizationResult:
    """Routes plus fallback metadata produced by personalization."""

    routes: List[RouteCandidate]
    used_start_fallback: bool
    used_must_include_fallback: bool
    max_matched_must_include: int
    total_requested_must_include: int
    fallback_reason: str | None = None


def _validate_simple_cycle(poi_route: Sequence[str]) -> None:
    if len(poi_route) < 3 or poi_route[0] != poi_route[-1]:
        raise ValueError("route must be a closed cycle")
    core = list(poi_route[:-1])
    if len(core) != len(set(core)):
        raise ValueError("route must be a simple cycle without repeated core POIs")


def _build_route_candidate(
    *,
    poi_route: Sequence[str],
    avg_pair_tpi: float,
    cycle_support: int,
    cycle_tpi: float,
    cycle_strength_global: float,
    supporting_trajectory_ids: frozenset[str],
    categories: Sequence[str],
    start_distance_km: float | None = None,
    must_include_match_count: int = 0,
    must_include_total_count: int = 0,
    start_fit_score: float = 1.0,
    must_visit_fit_score: float = 1.0,
    dominant_supporting_season: str | None = None,
    season_fit_score: float = 1.0,
    season_match_count: int = 0,
    season_total_count: int = 0,
) -> RouteCandidate:
    _validate_simple_cycle(poi_route)
    core = tuple(poi_route[:-1])
    return RouteCandidate(
        poi_route=tuple(poi_route),
        avg_pair_tpi=avg_pair_tpi,
        cycle_support=cycle_support,
        cycle_tpi=cycle_tpi,
        cycle_strength_global=cycle_strength_global,
        supporting_trajectory_ids=supporting_trajectory_ids,
        categories=tuple(categories),
        path_length=len(core),
        unique_poi_count=len(core),
        canonical_cycle_signature=_canonical_cycle_signature(core),
        start_distance_km=start_distance_km,
        must_include_match_count=must_include_match_count,
        must_include_total_count=must_include_total_count,
        start_fit_score=start_fit_score,
        must_visit_fit_score=must_visit_fit_score,
        dominant_supporting_season=dominant_supporting_season,
        season_fit_score=season_fit_score,
        season_match_count=season_match_count,
        season_total_count=season_total_count,
    )


def generate_routes_from_patterns(
    patterns: Iterable[CircularPattern],
    poi_dict: Dict[str, dict],
    config: PipelineConfig = DEFAULT_CONFIG,
) -> List[RouteCandidate]:
    """Convert circular patterns into route candidates."""
    _ = config
    routes: List[RouteCandidate] = []
    for pattern in patterns:
        categories = tuple(
            poi_dict.get(poi_id, {}).get("category", "unknown")
            for poi_id in pattern.cycle[:-1]
        )
        routes.append(
            _build_route_candidate(
                poi_route=pattern.cycle,
                avg_pair_tpi=pattern.avg_pair_tpi,
                cycle_support=pattern.cycle_support,
                cycle_tpi=pattern.cycle_tpi,
                cycle_strength_global=pattern.cycle_strength_global,
                supporting_trajectory_ids=pattern.supporting_trajectory_ids,
                categories=categories,
            )
        )
    return routes


def _rotate_cycle(
    route: Sequence[str], categories: Sequence[str], start_poi: str
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Rotate a closed cycle so it starts from the first matching POI."""
    core = list(route[:-1])
    if start_poi not in core:
        raise ValueError("start_poi not in route")

    idx = core.index(start_poi)
    rotated_core = core[idx:] + core[:idx]

    core_categories = list(categories)
    rotated_categories = core_categories[idx:] + core_categories[:idx]
    return tuple(rotated_core + [start_poi]), tuple(rotated_categories)


def _build_route_with_metrics(
    route: RouteCandidate,
    *,
    poi_route: Tuple[str, ...] | None = None,
    categories: Tuple[str, ...] | None = None,
    start_distance_km: float | None = None,
    must_include_match_count: int | None = None,
    must_include_total_count: int | None = None,
    start_fit_score: float | None = None,
    must_visit_fit_score: float | None = None,
    dominant_supporting_season: str | None = None,
    season_fit_score: float | None = None,
    season_match_count: int | None = None,
    season_total_count: int | None = None,
) -> RouteCandidate:
    """Clone a route candidate with updated personalization metrics."""
    return _build_route_candidate(
        poi_route=poi_route if poi_route is not None else route.poi_route,
        avg_pair_tpi=route.avg_pair_tpi,
        cycle_support=route.cycle_support,
        cycle_tpi=route.cycle_tpi,
        cycle_strength_global=route.cycle_strength_global,
        supporting_trajectory_ids=route.supporting_trajectory_ids,
        categories=categories if categories is not None else route.categories,
        start_distance_km=route.start_distance_km if start_distance_km is None else start_distance_km,
        must_include_match_count=(
            route.must_include_match_count
            if must_include_match_count is None
            else must_include_match_count
        ),
        must_include_total_count=(
            route.must_include_total_count
            if must_include_total_count is None
            else must_include_total_count
        ),
        start_fit_score=route.start_fit_score if start_fit_score is None else start_fit_score,
        must_visit_fit_score=(
            route.must_visit_fit_score if must_visit_fit_score is None else must_visit_fit_score
        ),
        dominant_supporting_season=(
            route.dominant_supporting_season
            if dominant_supporting_season is None
            else dominant_supporting_season
        ),
        season_fit_score=route.season_fit_score if season_fit_score is None else season_fit_score,
        season_match_count=(
            route.season_match_count if season_match_count is None else season_match_count
        ),
        season_total_count=(
            route.season_total_count if season_total_count is None else season_total_count
        ),
    )


def _compute_start_fit_score(distance_km: float | None) -> float:
    """Translate approach distance into a coarse start-fit score."""
    if distance_km is None:
        return 1.0
    if distance_km <= 1:
        return 1.0
    if distance_km <= 3:
        return 0.8
    if distance_km <= 5:
        return 0.5
    return 0.2


def filter_routes_by_personalization(
    routes: Iterable[RouteCandidate],
    poi_dict: Dict[str, dict],
    trajectory_seasons: Dict[str, str] | None = None,
    requested_season: str | None = None,
    start_poi: str | None = None,
    must_include_pois: Sequence[str] | None = None,
    fallback_limit: int = 5,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> PersonalizationResult:
    """
    Annotate routes with personalization metrics.

    This stage intentionally does not truncate the candidate set.
    """
    _ = fallback_limit
    _ = config
    routes_list = list(routes)
    must_include_set = set(must_include_pois or [])
    trajectory_season_lookup = trajectory_seasons or {}

    if not routes_list:
        return PersonalizationResult(
            routes=[],
            used_start_fallback=False,
            used_must_include_fallback=False,
            max_matched_must_include=0,
            total_requested_must_include=len(must_include_set),
            fallback_reason=None,
        )

    contains_start_any = False
    max_matched_count = 0
    result_routes: List[RouteCandidate] = []
    for route in routes_list:
        core = list(route.poi_route[:-1])
        core_set = set(core)
        matched_count = len(core_set.intersection(must_include_set))
        max_matched_count = max(max_matched_count, matched_count)
        dominant_supporting_season = compute_dominant_supporting_season(
            route.supporting_trajectory_ids,
            trajectory_season_lookup,
            requested_season=requested_season,
        )
        season_fit_score, season_match_count, season_total_count = compute_route_season_fit(
            core,
            poi_dict,
            requested_season,
            dominant_supporting_season=dominant_supporting_season,
        )

        start_distance_km: float | None = None
        route_to_add = route
        if start_poi and start_poi in poi_dict:
            if start_poi in core_set:
                contains_start_any = True
                rotated_route, rotated_categories = _rotate_cycle(
                    route.poi_route, route.categories, start_poi
                )
                route_to_add = _build_route_with_metrics(
                    route,
                    poi_route=rotated_route,
                    categories=rotated_categories,
                )
                start_distance_km = 0.0
            else:
                best_start = min(
                    core,
                    key=lambda poi_id: haversine_km(
                        float(poi_dict[start_poi]["latitude"]),
                        float(poi_dict[start_poi]["longitude"]),
                        float(poi_dict[poi_id]["latitude"]),
                        float(poi_dict[poi_id]["longitude"]),
                    ),
                )
                start_distance_km = haversine_km(
                    float(poi_dict[start_poi]["latitude"]),
                    float(poi_dict[start_poi]["longitude"]),
                    float(poi_dict[best_start]["latitude"]),
                    float(poi_dict[best_start]["longitude"]),
                )
                rotated_route, rotated_categories = _rotate_cycle(
                    route.poi_route, route.categories, best_start
                )
                route_to_add = _build_route_with_metrics(
                    route,
                    poi_route=rotated_route,
                    categories=rotated_categories,
                )

        total_must = len(must_include_set)
        must_fit = matched_count / total_must if total_must > 0 else 1.0
        result_routes.append(
            _build_route_with_metrics(
                route_to_add,
                start_distance_km=start_distance_km,
                must_include_match_count=matched_count,
                must_include_total_count=total_must,
                start_fit_score=_compute_start_fit_score(start_distance_km),
                must_visit_fit_score=must_fit,
                dominant_supporting_season=dominant_supporting_season,
                season_fit_score=season_fit_score,
                season_match_count=season_match_count,
                season_total_count=season_total_count,
            )
        )

    used_start_fallback = bool(start_poi and not contains_start_any and start_poi in poi_dict)
    used_must_fallback = bool(must_include_set and max_matched_count < len(must_include_set))

    fallback_msgs: List[str] = []
    if used_must_fallback:
        fallback_msgs.append("未找到完全包含全部必去点的路线，已按必去点匹配度排序。")
    if used_start_fallback:
        fallback_msgs.append("指定起点不在高强度闭环中，已按起点距离进行推荐。")
    fallback_reason = " ".join(fallback_msgs) if fallback_msgs else None

    return PersonalizationResult(
        routes=result_routes,
        used_start_fallback=used_start_fallback,
        used_must_include_fallback=used_must_fallback,
        max_matched_must_include=max_matched_count,
        total_requested_must_include=len(must_include_set),
        fallback_reason=fallback_reason,
    )
