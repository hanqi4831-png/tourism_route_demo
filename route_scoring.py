"""Route scoring logic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from config import PipelineConfig, ScoreWeights
from models import (
    PersonalizationSettings,
    CLI_PERSONALIZATION_MUST_VISIT,
    CLI_PERSONALIZATION_SEASON,
    CLI_PERSONALIZATION_START_POINT,
    CLI_PERSONALIZATION_TIME_BUDGET,
    CLI_PERSONALIZATION_TYPE_PREFERENCE,
    UserRequest,
)
from route_filter import estimate_total_distance_km, estimate_total_duration_minutes
from route_generator import RouteCandidate
from utils import min_max_normalize


@dataclass(frozen=True)
class ScoredRoute:
    """A route together with all derived scoring signals."""

    route: RouteCandidate
    score: float
    cycle_tpi: float
    cycle_strength_global: float
    popularity_score: float
    preference_score: float
    must_visit_fit_score: float
    start_fit_score: float
    time_fit_score: float
    season_fit_score: float
    route_length_score: float
    category_count: int
    unique_categories: List[str]
    category_diversity_score: float
    dominant_category: str | None
    dominant_category_ratio: float
    single_type_penalty: float
    travel_cost_km: float
    estimated_total_duration: float
    reason_tags: List[str]
    fallback_reason: str | None
    must_visit_match_count: int
    dominant_supporting_season: str | None = None
    base_score: float = 0.0
    personal_score: float = 0.0

    @property
    def cycle_strength(self) -> float:
        """Backward-compatible alias."""
        return self.cycle_strength_global


def _compute_route_popularity(
    route_pois: Sequence[str], poi_popularity: Dict[str, float]
) -> float:
    values = [poi_popularity.get(poi_id, 0.0) for poi_id in route_pois]
    if not values:
        return 0.0
    return float(np.mean(values))


def _core_pois(route_pois: Sequence[str]) -> List[str]:
    """Return the cycle core POIs."""
    return list(route_pois[:-1])


def _categories_for_pois(
    poi_ids: Sequence[str], poi_dict: Dict[str, dict]
) -> List[str]:
    """Map a POI sequence to categories."""
    return [poi_dict.get(poi_id, {}).get("category", "unknown") for poi_id in poi_ids]


def _compute_preference_match(
    categories: Sequence[str], preferred_categories: set[str]
) -> float:
    """Score preference match using both coverage and density."""
    if not categories:
        return 0.0
    if not preferred_categories:
        return 0.5

    unique_route_categories = set(categories)
    coverage = len(unique_route_categories.intersection(preferred_categories)) / max(
        len(preferred_categories), 1
    )
    density = sum(1 for category in categories if category in preferred_categories) / max(
        len(categories), 1
    )
    return 0.5 * coverage + 0.5 * density


def _compute_category_profile(
    categories: Sequence[str],
) -> Tuple[int, List[str], float, str | None, float]:
    """Compute route category structure metrics."""
    if not categories:
        return 0, [], 0.0, None, 0.0
    counter = Counter(categories)
    total = len(categories)
    unique_categories = list(counter.keys())
    category_count = len(unique_categories)
    dominant_category, dominant_count = max(counter.items(), key=lambda item: item[1])
    diversity = category_count / max(total, 1)
    dominant_ratio = dominant_count / max(total, 1)
    return category_count, unique_categories, diversity, dominant_category, dominant_ratio


def _compute_single_type_penalty(
    dominant_ratio: float,
    category_count: int,
    preferred_categories: Sequence[str],
    config: PipelineConfig,
) -> float:
    """Penalize overly single-type routes unless the user wants that."""
    if category_count <= 1:
        base_penalty = 1.0
    elif dominant_ratio >= config.dominant_high_threshold:
        base_penalty = 0.7
    elif dominant_ratio >= config.dominant_mid_threshold:
        base_penalty = 0.4
    else:
        base_penalty = 0.1

    if len(preferred_categories) == 1:
        return base_penalty * 0.4
    return base_penalty


def _build_dynamic_weights(
    config: PipelineConfig,
    preferred_categories: Sequence[str],
    has_must_visit: bool,
    has_start_poi: bool,
) -> ScoreWeights:
    """Build weights based on the active personalization inputs."""
    if not preferred_categories:
        weights = config.no_preference_weights
    elif len(preferred_categories) == 1:
        weights = config.single_preference_weights
    else:
        weights = config.multi_preference_weights

    w = ScoreWeights(
        cycle_strength=weights.cycle_strength,
        popularity_score=weights.popularity_score,
        preference_match_score=weights.preference_match_score,
        time_fit_score=weights.time_fit_score,
        start_fit_score=weights.start_fit_score + (0.05 if has_start_poi else 0.0),
        must_visit_fit_score=weights.must_visit_fit_score + (0.05 if has_must_visit else 0.0),
        category_diversity_score=weights.category_diversity_score,
        travel_cost_penalty=weights.travel_cost_penalty,
        single_type_penalty=weights.single_type_penalty,
    )
    positive_sum = (
        w.cycle_strength
        + w.popularity_score
        + w.preference_match_score
        + w.time_fit_score
        + w.start_fit_score
        + w.must_visit_fit_score
        + w.category_diversity_score
    )
    if positive_sum <= 0:
        return w

    norm = 1.0 / positive_sum
    return ScoreWeights(
        cycle_strength=w.cycle_strength * norm,
        popularity_score=w.popularity_score * norm,
        preference_match_score=w.preference_match_score * norm,
        time_fit_score=w.time_fit_score * norm,
        start_fit_score=w.start_fit_score * norm,
        must_visit_fit_score=w.must_visit_fit_score * norm,
        category_diversity_score=w.category_diversity_score * norm,
        travel_cost_penalty=w.travel_cost_penalty,
        single_type_penalty=w.single_type_penalty,
    )


def _compute_time_fit_score(
    estimated_minutes: float,
    time_budget_hours: float | None,
    soft_time_overrun_ratio: float,
    hard_time_overrun_ratio: float,
) -> float:
    """Convert estimated duration into a time-fit score."""
    if time_budget_hours is None:
        return 1.0

    budget_minutes = max(time_budget_hours * 60.0, 1.0)
    ratio = estimated_minutes / budget_minutes
    if 0.8 <= ratio <= 1.0:
        return 1.0
    if 1.0 < ratio <= soft_time_overrun_ratio:
        return 0.7
    if soft_time_overrun_ratio < ratio <= hard_time_overrun_ratio:
        return 0.3
    if ratio > hard_time_overrun_ratio:
        return 0.0
    return max(ratio / 0.8, 0.5)


def _compute_route_length_score(unique_poi_count: int, config: PipelineConfig) -> float:
    """Reward routes with more unique POIs."""
    min_count = max(config.min_route_pois, 0)
    preferred_count = max(config.preferred_route_poi_count, min_count)
    if preferred_count == min_count:
        return 1.0 if unique_poi_count >= preferred_count else 0.0

    raw_score = (unique_poi_count - min_count) / max(preferred_count - min_count, 1)
    return float(min(max(raw_score, 0.0), 1.0))


def _build_reason_tags(
    route: RouteCandidate,
    popularity_score: float,
    preference_score: float,
    time_fit_score: float,
    season_fit_score: float,
    route_length_score: float,
    category_diversity_score: float,
    dominant_category: str | None,
    dominant_category_ratio: float,
) -> List[str]:
    """Generate human-readable reason tags."""
    tags: List[str] = ["简单闭环路线"]

    if route.cycle_tpi >= 0.20:
        tags.append("高强度闭环模式")
    elif route.cycle_tpi >= 0.10:
        tags.append("稳定闭环模式")

    if popularity_score >= 0.06:
        tags.append("热门景点覆盖较高")
    if preference_score >= 0.8:
        tags.append("类型偏好匹配度高")
    if route.must_include_total_count > 0:
        if route.must_include_match_count == route.must_include_total_count:
            tags.append("包含全部必去点")
        else:
            tags.append(
                f"包含 {route.must_include_match_count}/{route.must_include_total_count} 个必去点"
            )
    if route.start_distance_km is not None and route.start_distance_km <= 3:
        tags.append("起点接入便捷")
    if time_fit_score >= 0.9:
        tags.append("时间预算适配度高")
    if route.dominant_supporting_season:
        tags.append(f"主导季节: {route.dominant_supporting_season}")
    if season_fit_score >= 0.8:
        tags.append("季节适配度高")
    elif route.season_total_count > 0 and season_fit_score <= 0.3:
        tags.append("季节适配偏弱")
    if route_length_score >= 0.75:
        tags.append("节点覆盖更丰富")
    if category_diversity_score >= 0.75:
        tags.append("类别丰富，体验更均衡")
    elif category_diversity_score >= 0.5:
        tags.append("覆盖多类景点")
    if dominant_category_ratio >= 0.8 and dominant_category:
        tags.append(f"主题集中: 以 {dominant_category} 为主")

    return tags


def _preference_soft_rank_scores(
    categories: Sequence[str],
    preferred_categories: Sequence[str],
) -> Tuple[float, float, float]:
    """Compute preference coverage, balance, and final score."""
    if not categories or not preferred_categories:
        return 0.0, 0.0, 0.0

    preferred_set = set(preferred_categories)
    coverage = len(set(categories).intersection(preferred_set)) / max(len(preferred_set), 1)
    preferred_poi_count = sum(1 for category in categories if category in preferred_set)
    preferred_ratio = preferred_poi_count / max(len(categories), 1)
    if preferred_ratio < 0.2:
        balance = 0.2
    elif preferred_ratio <= 0.6:
        balance = 1.0
    elif preferred_ratio <= 0.8:
        balance = 0.6
    else:
        balance = 0.2
    return coverage, balance, 0.6 * coverage + 0.4 * balance


def _build_personalized_reason_tags(
    *,
    route: RouteCandidate,
    base_score: float,
    soft_scores: Dict[str, float],
    hard_filter_keys: Sequence[str],
    route_length_score: float,
) -> List[str]:
    """Generate personalized explanation tags."""
    tags: List[str] = ["简单闭环路线"]
    if base_score >= 0.08 or route.cycle_tpi >= 0.10:
        tags.append("闭环模式强")

    for key in hard_filter_keys:
        if key == CLI_PERSONALIZATION_TIME_BUDGET:
            tags.append("满足硬筛选: 时间预算")
        elif key == CLI_PERSONALIZATION_MUST_VISIT:
            tags.append("满足硬筛选: 必去点")
        elif key == CLI_PERSONALIZATION_START_POINT:
            tags.append("满足硬筛选: 起点接近")
        elif key == CLI_PERSONALIZATION_SEASON:
            tags.append("满足硬筛选: 季节")

    if soft_scores.get(CLI_PERSONALIZATION_TIME_BUDGET, 0.0) >= 0.70:
        tags.append("软排序优先: 时间预算贴合")
    if soft_scores.get(CLI_PERSONALIZATION_MUST_VISIT, 0.0) >= 0.70:
        tags.append("软排序优先: 必去点覆盖较高")
    if soft_scores.get(CLI_PERSONALIZATION_START_POINT, 0.0) >= 0.80:
        tags.append("软排序优先: 起点接入方便")
    if soft_scores.get(CLI_PERSONALIZATION_TYPE_PREFERENCE, 0.0) >= 0.70:
        tags.append("软排序优先: 类型偏好匹配较好")
    if soft_scores.get(CLI_PERSONALIZATION_SEASON, 0.0) >= 0.70:
        tags.append("软排序优先: 季节适配较高")
    if route_length_score >= 0.75:
        tags.append("节点覆盖更丰富")

    return tags


def score_routes(
    routes: Iterable[RouteCandidate],
    poi_dict: Dict[str, dict],
    poi_popularity: Dict[str, float],
    preferred_categories: Sequence[str],
    config: PipelineConfig,
    time_budget_hours: float | None,
    start_poi: str | None = None,
    must_include_pois: Sequence[str] | None = None,
    fallback_reason: str | None = None,
) -> List[ScoredRoute]:
    """Score routes with dynamic weights and explanatory metrics."""
    routes_list = list(routes)
    if not routes_list:
        return []

    preferred_set = set(preferred_categories)
    dynamic_weights = _build_dynamic_weights(
        config=config,
        preferred_categories=preferred_categories,
        has_must_visit=bool(must_include_pois),
        has_start_poi=bool(start_poi),
    )
    raw_costs = [
        estimate_total_distance_km(
            route.poi_route,
            poi_dict,
            access_distance_km=route.start_distance_km or 0.0,
        )
        for route in routes_list
    ]
    norm_costs = min_max_normalize(raw_costs)

    scored: List[ScoredRoute] = []
    for idx, route in enumerate(routes_list):
        core_pois = _core_pois(route.poi_route)
        core_categories = _categories_for_pois(core_pois, poi_dict)
        popularity_score = _compute_route_popularity(core_pois, poi_popularity)
        preference_score = _compute_preference_match(core_categories, preferred_set)
        estimated_total_duration = estimate_total_duration_minutes(
            route.poi_route,
            poi_dict,
            config.average_speed_kmh,
            access_distance_km=route.start_distance_km or 0.0,
        )
        (
            category_count,
            unique_categories,
            category_diversity_score,
            dominant_category,
            dominant_category_ratio,
        ) = _compute_category_profile(core_categories)
        single_type_penalty = _compute_single_type_penalty(
            dominant_ratio=dominant_category_ratio,
            category_count=category_count,
            preferred_categories=preferred_categories,
            config=config,
        )
        route_length_score = _compute_route_length_score(route.unique_poi_count, config)
        time_fit_score = _compute_time_fit_score(
            estimated_minutes=estimated_total_duration,
            time_budget_hours=time_budget_hours,
            soft_time_overrun_ratio=config.soft_time_overrun_ratio,
            hard_time_overrun_ratio=config.hard_time_overrun_ratio,
        )
        start_fit_score = route.start_fit_score
        must_visit_fit_score = route.must_visit_fit_score
        season_fit_score = route.season_fit_score
        score = (
            dynamic_weights.cycle_strength * route.cycle_tpi
            + dynamic_weights.popularity_score * popularity_score
            + dynamic_weights.preference_match_score * preference_score
            + dynamic_weights.time_fit_score * time_fit_score
            + dynamic_weights.start_fit_score * start_fit_score
            + dynamic_weights.must_visit_fit_score * must_visit_fit_score
            + dynamic_weights.category_diversity_score * category_diversity_score
            + config.route_length_reward_weight * route_length_score
            - dynamic_weights.travel_cost_penalty * norm_costs[idx]
            - dynamic_weights.single_type_penalty * single_type_penalty
        )
        reason_tags = _build_reason_tags(
            route=route,
            popularity_score=popularity_score,
            preference_score=preference_score,
            time_fit_score=time_fit_score,
            season_fit_score=season_fit_score,
            route_length_score=route_length_score,
            category_diversity_score=category_diversity_score,
            dominant_category=dominant_category,
            dominant_category_ratio=dominant_category_ratio,
        )
        scored.append(
            ScoredRoute(
                route=route,
                score=score,
                cycle_tpi=route.cycle_tpi,
                cycle_strength_global=route.cycle_strength_global,
                popularity_score=popularity_score,
                preference_score=preference_score,
                must_visit_fit_score=must_visit_fit_score,
                start_fit_score=start_fit_score,
                time_fit_score=time_fit_score,
                season_fit_score=season_fit_score,
                route_length_score=route_length_score,
                category_count=category_count,
                unique_categories=unique_categories,
                category_diversity_score=category_diversity_score,
                dominant_category=dominant_category,
                dominant_category_ratio=dominant_category_ratio,
                single_type_penalty=single_type_penalty,
                travel_cost_km=raw_costs[idx],
                estimated_total_duration=estimated_total_duration,
                reason_tags=reason_tags,
                fallback_reason=fallback_reason,
                must_visit_match_count=route.must_include_match_count,
                dominant_supporting_season=route.dominant_supporting_season,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def score_routes_for_recommendation(
    routes: Iterable[RouteCandidate],
    poi_dict: Dict[str, dict],
    poi_popularity: Dict[str, float],
    request: UserRequest,
    settings: PersonalizationSettings,
    config: PipelineConfig,
    fallback_reason: str | None = None,
) -> List[ScoredRoute]:
    """Score routes using base-score plus personalization soft ranking."""
    routes_list = list(routes)
    if not routes_list:
        return []

    scored: List[ScoredRoute] = []
    for route in routes_list:
        core_pois = _core_pois(route.poi_route)
        core_categories = _categories_for_pois(core_pois, poi_dict)
        popularity_score = _compute_route_popularity(core_pois, poi_popularity)
        estimated_total_duration = estimate_total_duration_minutes(
            route.poi_route,
            poi_dict,
            config.average_speed_kmh,
            access_distance_km=route.start_distance_km or 0.0,
        )
        (
            category_count,
            unique_categories,
            category_diversity_score,
            dominant_category,
            dominant_category_ratio,
        ) = _compute_category_profile(core_categories)
        single_type_penalty = _compute_single_type_penalty(
            dominant_ratio=dominant_category_ratio,
            category_count=category_count,
            preferred_categories=request.preferred_categories,
            config=config,
        )
        route_length_score = _compute_route_length_score(route.unique_poi_count, config)

        time_score = 0.0
        if request.time_budget_hours is not None:
            estimated_hours = estimated_total_duration / 60.0
            time_score = max(
                0.0,
                1.0
                - abs(estimated_hours - request.time_budget_hours)
                / max(request.time_budget_hours, 1e-9),
            )

        must_score = route.must_visit_fit_score if request.must_include_pois else 0.0
        start_score = route.start_fit_score if request.start_poi else 0.0
        season_score = route.season_fit_score if request.requested_season else 0.0
        _, _, preference_score = _preference_soft_rank_scores(
            core_categories,
            request.preferred_categories,
        )

        soft_scores: Dict[str, float] = {}
        if CLI_PERSONALIZATION_TIME_BUDGET in settings.soft_rank_weights:
            soft_scores[CLI_PERSONALIZATION_TIME_BUDGET] = time_score
        if CLI_PERSONALIZATION_MUST_VISIT in settings.soft_rank_weights:
            soft_scores[CLI_PERSONALIZATION_MUST_VISIT] = must_score
        if CLI_PERSONALIZATION_START_POINT in settings.soft_rank_weights:
            soft_scores[CLI_PERSONALIZATION_START_POINT] = start_score
        if CLI_PERSONALIZATION_TYPE_PREFERENCE in settings.soft_rank_weights:
            soft_scores[CLI_PERSONALIZATION_TYPE_PREFERENCE] = preference_score
        if CLI_PERSONALIZATION_SEASON in settings.soft_rank_weights:
            soft_scores[CLI_PERSONALIZATION_SEASON] = season_score

        personal_score = sum(
            settings.soft_rank_weights[key] * score
            for key, score in soft_scores.items()
        )
        base_score = 0.5 * route.cycle_tpi + 0.5 * route.cycle_strength_global
        final_score = (
            config.base_score_weight * base_score
            + config.personal_score_weight * personal_score
            + config.route_length_reward_weight * route_length_score
        )
        reason_tags = _build_personalized_reason_tags(
            route=route,
            base_score=base_score,
            soft_scores=soft_scores,
            hard_filter_keys=settings.hard_filter_keys,
            route_length_score=route_length_score,
        )
        scored.append(
            ScoredRoute(
                route=route,
                score=final_score,
                cycle_tpi=route.cycle_tpi,
                cycle_strength_global=route.cycle_strength_global,
                popularity_score=popularity_score,
                preference_score=preference_score,
                must_visit_fit_score=must_score,
                start_fit_score=start_score,
                time_fit_score=time_score,
                season_fit_score=season_score,
                route_length_score=route_length_score,
                category_count=category_count,
                unique_categories=unique_categories,
                category_diversity_score=category_diversity_score,
                dominant_category=dominant_category,
                dominant_category_ratio=dominant_category_ratio,
                single_type_penalty=single_type_penalty,
                travel_cost_km=estimate_total_distance_km(
                    route.poi_route,
                    poi_dict,
                    access_distance_km=route.start_distance_km or 0.0,
                ),
                estimated_total_duration=estimated_total_duration,
                reason_tags=reason_tags,
                fallback_reason=fallback_reason,
                must_visit_match_count=route.must_include_match_count,
                dominant_supporting_season=route.dominant_supporting_season,
                base_score=base_score,
                personal_score=personal_score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


score_routes_for_cli = score_routes_for_recommendation
