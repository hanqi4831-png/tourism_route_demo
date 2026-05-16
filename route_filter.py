"""Candidate route filtering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from config import PipelineConfig
from models import (
    PERSONALIZATION_MUST_VISIT,
    PERSONALIZATION_SEASON,
    PERSONALIZATION_START_POINT,
    PERSONALIZATION_TIME_BUDGET,
    PersonalizationSettings,
    UserRequest,
)
from route_generator import RouteCandidate
from utils import haversine_km


@dataclass(frozen=True)
class FilterResult:
    """Routes kept after hard filtering plus removal counts."""

    routes: List[RouteCandidate]
    removed_by_time: int
    removed_by_distance: int
    removed_by_cycle_tpi: int
    removed_by_length: int


@dataclass(frozen=True)
class PersonalizedHardFilterResult:
    """Hard-filter result plus removal counts."""

    routes: List[RouteCandidate]
    original_count: int
    removed_by_time_budget: int
    removed_by_must_visit: int
    removed_by_start_point: int
    removed_by_season: int


def estimate_total_distance_km(
    route_pois: Sequence[str],
    poi_dict: Dict[str, dict],
    access_distance_km: float = 0.0,
) -> float:
    """Estimate route distance, optionally including one-way access distance."""
    total = max(access_distance_km, 0.0)
    for i in range(len(route_pois) - 1):
        src = poi_dict[route_pois[i]]
        dst = poi_dict[route_pois[i + 1]]
        total += haversine_km(
            float(src["latitude"]),
            float(src["longitude"]),
            float(dst["latitude"]),
            float(dst["longitude"]),
        )
    return total


def estimate_total_duration_minutes(
    route_pois: Sequence[str],
    poi_dict: Dict[str, dict],
    average_speed_kmh: float,
    access_distance_km: float = 0.0,
) -> float:
    """Estimate route duration as stay time plus travel time."""
    core = route_pois[:-1]
    stay_minutes = sum(
        float(poi_dict[poi_id].get("visit_duration_minutes", 60.0)) for poi_id in core
    )
    total_distance_km = estimate_total_distance_km(
        route_pois,
        poi_dict,
        access_distance_km=access_distance_km,
    )
    speed = max(average_speed_kmh, 0.1)
    travel_minutes = total_distance_km / speed * 60.0
    return stay_minutes + travel_minutes


def filter_routes(
    routes: Iterable[RouteCandidate],
    poi_dict: Dict[str, dict],
    config: PipelineConfig,
    time_budget_hours: float | None,
) -> FilterResult:
    """Remove routes that are clearly infeasible before scoring."""
    kept: List[RouteCandidate] = []
    removed_by_time = 0
    removed_by_distance = 0
    removed_by_cycle_tpi = 0
    removed_by_length = 0
    time_budget_minutes = time_budget_hours * 60.0 if time_budget_hours else None

    for route in routes:
        core_len = route.unique_poi_count
        if core_len < config.min_route_pois or core_len > config.max_route_pois:
            removed_by_length += 1
            continue

        if route.cycle_support < config.min_cycle_support or route.cycle_tpi < config.min_prev:
            removed_by_cycle_tpi += 1
            continue

        access_distance_km = route.start_distance_km or 0.0
        distance_km = estimate_total_distance_km(
            route.poi_route,
            poi_dict,
            access_distance_km=access_distance_km,
        )
        if distance_km > config.max_route_distance_km:
            removed_by_distance += 1
            continue

        if time_budget_minutes is not None:
            est_minutes = estimate_total_duration_minutes(
                route.poi_route,
                poi_dict,
                config.average_speed_kmh,
                access_distance_km=access_distance_km,
            )
            ratio = est_minutes / max(time_budget_minutes, 1.0)
            if ratio > config.hard_time_overrun_ratio:
                removed_by_time += 1
                continue

        kept.append(route)

    return FilterResult(
        routes=kept,
        removed_by_time=removed_by_time,
        removed_by_distance=removed_by_distance,
        removed_by_cycle_tpi=removed_by_cycle_tpi,
        removed_by_length=removed_by_length,
    )


def apply_personalized_hard_filters(
    routes: Iterable[RouteCandidate],
    poi_dict: Dict[str, dict],
    config: PipelineConfig,
    request: UserRequest,
    settings: PersonalizationSettings,
) -> PersonalizedHardFilterResult:
    """Apply personalized hard filters after generic quality filtering."""
    routes_list = list(routes)
    if not routes_list or not settings.hard_filter_keys:
        return PersonalizedHardFilterResult(
            routes=routes_list,
            original_count=len(routes_list),
            removed_by_time_budget=0,
            removed_by_must_visit=0,
            removed_by_start_point=0,
            removed_by_season=0,
        )

    removed_by_time_budget = 0
    removed_by_must_visit = 0
    removed_by_start_point = 0
    removed_by_season = 0
    kept: List[RouteCandidate] = []
    active_keys = [
        key
        for key in (
            PERSONALIZATION_TIME_BUDGET,
            PERSONALIZATION_MUST_VISIT,
            PERSONALIZATION_START_POINT,
            PERSONALIZATION_SEASON,
        )
        if key in settings.hard_filter_keys
    ]

    for route in routes_list:
        failed_key: str | None = None
        for key in active_keys:
            if key == PERSONALIZATION_TIME_BUDGET:
                if request.time_budget_hours is None:
                    continue
                estimated_minutes = estimate_total_duration_minutes(
                    route.poi_route,
                    poi_dict,
                    config.average_speed_kmh,
                    access_distance_km=route.start_distance_km or 0.0,
                )
                if estimated_minutes > request.time_budget_hours * 60.0:
                    failed_key = key
                    break
            elif key == PERSONALIZATION_MUST_VISIT:
                if not request.must_include_pois:
                    continue
                if route.must_include_match_count < route.must_include_total_count:
                    failed_key = key
                    break
            elif key == PERSONALIZATION_START_POINT:
                if request.start_poi is None:
                    continue
                if route.start_distance_km is None:
                    failed_key = key
                    break
                if route.start_distance_km > config.hard_start_distance_threshold_km:
                    failed_key = key
                    break
            elif key == PERSONALIZATION_SEASON:
                if request.requested_season is None:
                    continue
                if route.dominant_supporting_season != request.requested_season:
                    failed_key = key
                    break

        if failed_key is None:
            kept.append(route)
            continue

        if failed_key == PERSONALIZATION_TIME_BUDGET:
            removed_by_time_budget += 1
        elif failed_key == PERSONALIZATION_MUST_VISIT:
            removed_by_must_visit += 1
        elif failed_key == PERSONALIZATION_START_POINT:
            removed_by_start_point += 1
        elif failed_key == PERSONALIZATION_SEASON:
            removed_by_season += 1

    return PersonalizedHardFilterResult(
        routes=kept,
        original_count=len(routes_list),
        removed_by_time_budget=removed_by_time_budget,
        removed_by_must_visit=removed_by_must_visit,
        removed_by_start_point=removed_by_start_point,
        removed_by_season=removed_by_season,
    )


CLIHardFilterResult = PersonalizedHardFilterResult
apply_cli_hard_filters = apply_personalized_hard_filters
