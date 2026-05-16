"""Web service layer built on top of the recommendation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from config import DEFAULT_CONFIG, PipelineConfig
from data_loader import load_poi_data, load_trajectory_data
from gba_algorithm import CircularPattern, run_gba
from models import (
    HARD_FILTER_KEYS,
    PERSONALIZATION_MUST_VISIT,
    PERSONALIZATION_SEASON,
    PERSONALIZATION_START_POINT,
    PERSONALIZATION_TIME_BUDGET,
    PERSONALIZATION_TYPE_PREFERENCE,
    PersonalizationSettings,
    SOFT_RANK_KEYS,
    UserRequest,
)
from poi_analysis import compute_poi_popularity
from recommendation import top_k_recommendations
from route_filter import apply_personalized_hard_filters, filter_routes
from route_generator import (
    PersonalizationResult,
    RouteCandidate,
    filter_routes_by_personalization,
    generate_routes_from_patterns,
)
from route_scoring import ScoredRoute, score_routes_for_recommendation
from seasonality import (
    SUPPORTED_SEASONS,
    attach_poi_suitable_seasons,
    build_poi_suitable_season_lookup,
    build_route_poi_season_details,
    build_trajectory_season_lookup,
    normalize_requested_season,
)
from trajectory_processor import build_ordered_sequences
from utils import unique_preserve_order


@dataclass
class SystemState:
    """Preloaded data and mined artifacts kept in memory."""

    poi_dict: Dict[str, dict]
    trajectory_dict: Dict[str, list]
    trajectory_seasons: Dict[str, str]
    sequences: Dict[str, List[str]]
    circular_patterns: List[CircularPattern]
    pair_tpi: Dict[tuple, float]
    graph_node_count: int
    graph_edge_count: int
    poi_popularity: Dict[str, float]


_WEB_REASON_TAG_TRANSLATIONS = {
    "简单闭环路线": "Simple cycle route",
    "高强度闭环模式": "High-strength cycle pattern",
    "稳定闭环模式": "Stable cycle pattern",
    "热门景点覆盖较高": "Strong coverage of popular POIs",
    "类型偏好匹配度高": "Strong category preference match",
    "包含全部必去点": "Includes all required POIs",
    "起点接入便捷": "Convenient start-point access",
    "时间预算适配度高": "Strong time-budget fit",
    "季节适配度高": "Strong season fit",
    "季节适配偏弱": "Weak season fit",
    "节点覆盖更丰富": "Richer POI coverage",
    "类别丰富，体验更均衡": "Balanced route with diverse categories",
    "覆盖多类景点": "Covers multiple attraction categories",
    "闭环模式强": "Strong cycle pattern",
    "满足硬筛选: 时间预算": "Passed hard filter: time budget",
    "满足硬筛选: 必去点": "Passed hard filter: required POIs",
    "满足硬筛选: 起点接近": "Passed hard filter: start-point proximity",
    "满足硬筛选: 季节": "Passed hard filter: season",
    "软排序优先: 时间预算贴合": "Soft-rank priority: time-budget fit",
    "软排序优先: 必去点覆盖较高": "Soft-rank priority: required-POI coverage",
    "软排序优先: 起点接入方便": "Soft-rank priority: convenient start-point access",
    "软排序优先: 类型偏好匹配较好": "Soft-rank priority: category preference match",
    "软排序优先: 季节适配较高": "Soft-rank priority: season fit",
}

_WEB_FALLBACK_TEXT_TRANSLATIONS = {
    "未找到完全包含全部必去点的路线，已按必去点匹配度排序。": (
        "No route includes every required POI. Results were ranked by required-POI match."
    ),
    "指定起点不在高强度闭环中，已按起点距离进行推荐。": (
        "The selected start POI is not part of a high-strength cycle. Results were ranked by start-point distance."
    ),
}


def _translate_reason_tag_for_web(tag: str) -> str:
    translated = _WEB_REASON_TAG_TRANSLATIONS.get(tag)
    if translated is not None:
        return translated
    if tag.startswith("包含 ") and tag.endswith(" 个必去点"):
        count_text = tag.removeprefix("包含 ").removesuffix(" 个必去点")
        return f"Includes {count_text} required POIs"
    if tag.startswith("主导季节: "):
        season_text = tag.removeprefix("主导季节: ")
        return f"Dominant season: {season_text}"
    if tag.startswith("主题集中: 以 ") and tag.endswith(" 为主"):
        category_text = tag.removeprefix("主题集中: 以 ").removesuffix(" 为主")
        return f"Theme focused on {category_text}"
    return tag


def _translate_reason_tags_for_web(tags: List[str]) -> List[str]:
    return [_translate_reason_tag_for_web(tag) for tag in tags]


def _translate_fallback_reason_for_web(text: str | None) -> str | None:
    if not text:
        return text
    translated = text
    for source_text, target_text in _WEB_FALLBACK_TEXT_TRANSLATIONS.items():
        translated = translated.replace(source_text, target_text)
    return translated


class RecommendationService:
    """Service wrapper for the recommendation pipeline."""

    def __init__(self, config: PipelineConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.state: SystemState | None = None
        self._base_dir = Path(__file__).resolve().parent

    def initialize(self) -> None:
        """Load data and precompute the mined patterns."""
        poi_file = self._base_dir / self.config.poi_file
        trajectory_file = self._base_dir / self.config.trajectory_file
        if not poi_file.exists() or not trajectory_file.exists():
            raise ValueError("Data files were not found. Import poi.csv and trajectory.csv first.")

        poi_dict = load_poi_data(poi_file)
        trajectory_dict = load_trajectory_data(trajectory_file)
        trajectory_seasons = build_trajectory_season_lookup(trajectory_dict)
        attach_poi_suitable_seasons(
            poi_dict,
            build_poi_suitable_season_lookup(
                trajectory_dict,
                min_share_threshold=self.config.seasonality_min_share_threshold,
            ),
            overwrite_existing=False,
        )
        sequences = build_ordered_sequences(
            trajectory_dict,
            collapse_consecutive_duplicates=self.config.collapse_consecutive_duplicates,
        )
        circular_patterns, pair_tpi, graph = run_gba(sequences, self.config)
        poi_popularity = compute_poi_popularity(sequences)

        self.state = SystemState(
            poi_dict=poi_dict,
            trajectory_dict=trajectory_dict,
            trajectory_seasons=trajectory_seasons,
            sequences=sequences,
            circular_patterns=circular_patterns,
            pair_tpi=pair_tpi,
            graph_node_count=graph.number_of_nodes(),
            graph_edge_count=graph.number_of_edges(),
            poi_popularity=poi_popularity,
        )

    def import_data_from_csv_bytes(
        self,
        poi_csv_bytes: bytes,
        trajectory_csv_bytes: bytes,
    ) -> Dict[str, Any]:
        """Validate uploaded CSV files, persist them, and rebuild caches."""
        poi_df = pd.read_csv(BytesIO(poi_csv_bytes))
        trajectory_df = pd.read_csv(BytesIO(trajectory_csv_bytes))

        poi_required = {"poi_id", "poi_name", "category", "latitude", "longitude"}
        traj_required = {"user_id", "trajectory_id", "visit_order", "poi_id", "timestamp"}
        missing_poi = sorted(list(poi_required - set(poi_df.columns)))
        missing_traj = sorted(list(traj_required - set(trajectory_df.columns)))
        if missing_poi:
            raise ValueError(f"poi.csv is missing required columns: {', '.join(missing_poi)}")
        if missing_traj:
            raise ValueError(
                f"trajectory.csv is missing required columns: {', '.join(missing_traj)}"
            )

        if "visit_duration_minutes" not in poi_df.columns:
            poi_df["visit_duration_minutes"] = 60.0
        if "opening_hours" not in poi_df.columns:
            poi_df["opening_hours"] = "09:00-18:00"

        poi_file = self._base_dir / self.config.poi_file
        trajectory_file = self._base_dir / self.config.trajectory_file
        poi_file.parent.mkdir(parents=True, exist_ok=True)
        trajectory_file.parent.mkdir(parents=True, exist_ok=True)

        poi_df.to_csv(poi_file, index=False, encoding="utf-8-sig")
        trajectory_df.to_csv(trajectory_file, index=False, encoding="utf-8-sig")

        self.initialize()
        state = self._require_state()
        return {
            "message": "Data import succeeded. The system cache was reloaded.",
            "poi_count": len(state.poi_dict),
            "trajectory_count": len(state.trajectory_dict),
            "pair_pattern_count": len(state.pair_tpi),
            "cycle_pattern_count": len(state.circular_patterns),
        }

    def _require_state(self) -> SystemState:
        if self.state is None:
            raise RuntimeError(
                "The system is not initialized. Import poi.csv and trajectory.csv first."
            )
        return self.state

    def _request_has_value(self, request: UserRequest, key: str) -> bool:
        if key == PERSONALIZATION_TIME_BUDGET:
            return request.time_budget_hours is not None
        if key == PERSONALIZATION_MUST_VISIT:
            return bool(request.must_include_pois)
        if key == PERSONALIZATION_START_POINT:
            return request.start_poi is not None
        if key == PERSONALIZATION_TYPE_PREFERENCE:
            return bool(request.preferred_categories)
        if key == PERSONALIZATION_SEASON:
            return request.requested_season is not None
        return False

    def _build_soft_rank_weights(
        self,
        soft_rank_groups: List[List[str]],
    ) -> dict[str, float]:
        raw_scores: dict[str, float] = {}
        for position, group in enumerate(soft_rank_groups, start=1):
            if not group:
                continue
            raw_score = self.config.soft_rank_position_scores.get(position, 0.0)
            for key in group:
                raw_scores[key] = raw_score

        total = sum(raw_scores.values())
        if total <= 0:
            return {}
        return {key: value / total for key, value in raw_scores.items()}

    def _build_personalization_settings(
        self,
        request: UserRequest,
    ) -> PersonalizationSettings:
        return PersonalizationSettings(
            hard_filter_keys=list(request.hard_filter_keys),
            soft_rank_groups=[list(group) for group in request.soft_rank_groups],
            soft_rank_weights=dict(request.soft_rank_weights),
        )

    def _validate_and_normalize_request(
        self,
        request: UserRequest,
        state: SystemState,
        top_k: int | None,
    ) -> UserRequest:
        preferred_categories = unique_preserve_order(request.preferred_categories)
        must_include_pois = unique_preserve_order(request.must_include_pois)
        available_categories = {
            poi.get("category", "unknown") for poi in state.poi_dict.values()
        }

        invalid_categories = [
            category for category in preferred_categories if category not in available_categories
        ]
        if invalid_categories:
            raise ValueError("Unknown preferred categories: " + ", ".join(invalid_categories))

        if request.start_poi is not None and request.start_poi not in state.poi_dict:
            raise ValueError(f"Start POI does not exist: {request.start_poi}")

        invalid_must_include = [
            poi_id for poi_id in must_include_pois if poi_id not in state.poi_dict
        ]
        if invalid_must_include:
            raise ValueError("Required POIs do not exist: " + ", ".join(invalid_must_include))

        requested_season = normalize_requested_season(request.requested_season)

        if request.time_budget_hours is not None and request.time_budget_hours <= 0:
            raise ValueError("time_budget_hours must be greater than 0")

        if top_k is not None and top_k <= 0:
            raise ValueError("top_k must be greater than 0")

        hard_filter_keys = unique_preserve_order(request.hard_filter_keys)
        invalid_hard_filter_keys = [
            key for key in hard_filter_keys if key not in HARD_FILTER_KEYS
        ]
        if invalid_hard_filter_keys:
            raise ValueError(
                "hard_filter_keys contains invalid conditions: "
                + ", ".join(invalid_hard_filter_keys)
            )

        unavailable_hard_filter_keys = [
            key for key in hard_filter_keys if not self._request_has_value(request, key)
        ]
        if unavailable_hard_filter_keys:
            raise ValueError(
                "hard_filter_keys contains conditions without corresponding input values: "
                + ", ".join(unavailable_hard_filter_keys)
            )

        soft_rank_groups: List[List[str]] = []
        seen_soft_rank_keys: set[str] = set()
        for raw_group in request.soft_rank_groups:
            normalized_group = unique_preserve_order(raw_group)
            if not normalized_group:
                raise ValueError("soft_rank_groups cannot contain empty groups")

            cleaned_group: List[str] = []
            for key in normalized_group:
                if key not in SOFT_RANK_KEYS:
                    raise ValueError(f"soft_rank_groups contains an invalid condition: {key}")
                if key in hard_filter_keys:
                    raise ValueError(
                        f"soft_rank_groups cannot include a condition already used as a hard filter: {key}"
                    )
                if key in seen_soft_rank_keys:
                    raise ValueError(f"soft_rank_groups cannot repeat a condition: {key}")
                if not self._request_has_value(request, key):
                    raise ValueError(
                        f"soft_rank_groups contains a condition without a corresponding input value: {key}"
                    )
                cleaned_group.append(key)
                seen_soft_rank_keys.add(key)

            soft_rank_groups.append(cleaned_group)

        soft_rank_weights = self._build_soft_rank_weights(soft_rank_groups)

        return UserRequest(
            preferred_categories=preferred_categories,
            requested_season=requested_season,
            start_poi=request.start_poi,
            must_include_pois=must_include_pois,
            time_budget_hours=request.time_budget_hours,
            hard_filter_keys=hard_filter_keys,
            soft_rank_groups=soft_rank_groups,
            soft_rank_weights=soft_rank_weights,
        )

    def get_categories(self) -> List[str]:
        state = self._require_state()
        return unique_preserve_order(
            poi.get("category", "unknown") for poi in state.poi_dict.values()
        )

    def get_pois(self) -> List[Dict[str, Any]]:
        state = self._require_state()
        pois: List[Dict[str, Any]] = []
        for poi_id, poi in state.poi_dict.items():
            pois.append(
                {
                    "id": poi_id,
                    "name": poi["poi_name"],
                    "category": poi["category"],
                    "latitude": poi["latitude"],
                    "longitude": poi["longitude"],
                    "visit_duration_minutes": poi.get("visit_duration_minutes", 60.0),
                    "opening_hours": poi.get("opening_hours"),
                    "suitable_season": poi.get("suitable_season", "all"),
                    "suitable_seasons": list(poi.get("suitable_seasons", ("all",))),
                    "popularity": state.poi_popularity.get(poi_id, 0.0),
                }
            )
        return sorted(pois, key=lambda item: item["id"])

    def get_stats(self) -> Dict[str, Any]:
        state = self._require_state()
        top_popular = sorted(
            state.poi_popularity.items(), key=lambda item: item[1], reverse=True
        )[:10]
        available_seasons = [
            season
            for season in SUPPORTED_SEASONS
            if season in set(state.trajectory_seasons.values())
        ] or list(SUPPORTED_SEASONS)
        return {
            "poi_count": len(state.poi_dict),
            "trajectory_count": len(state.trajectory_dict),
            "pair_pattern_count": len(state.pair_tpi),
            "graph_node_count": state.graph_node_count,
            "graph_edge_count": state.graph_edge_count,
            "cycle_pattern_count": len(state.circular_patterns),
            "available_seasons": available_seasons,
            "top_popular_pois": [
                {
                    "poi_id": poi_id,
                    "poi_name": state.poi_dict.get(poi_id, {}).get("poi_name", poi_id),
                    "popularity": score,
                }
                for poi_id, score in top_popular
            ],
        }

    def _personalization_summary_payload(
        self,
        settings: PersonalizationSettings,
    ) -> Dict[str, Any]:
        return {
            "hard_filters": list(settings.hard_filter_keys),
            "soft_rank_groups": [list(group) for group in settings.soft_rank_groups],
            "soft_rank_weights": dict(settings.soft_rank_weights),
        }

    def _build_route_response_item(
        self,
        idx: int,
        scored: ScoredRoute,
        poi_dict: Dict[str, dict],
        settings: PersonalizationSettings,
        requested_season: str | None,
    ) -> Dict[str, Any]:
        route_poi_ids = list(scored.route.poi_route)
        route_poi_names = [
            poi_dict.get(poi_id, {}).get("poi_name", poi_id) for poi_id in route_poi_ids
        ]
        cycle_signature = list(scored.route.canonical_cycle_signature)
        route_poi_details = build_route_poi_season_details(
            route_poi_ids,
            poi_dict,
            requested_season=requested_season,
            route_dominant_season=scored.dominant_supporting_season,
        )
        display_summary = f"Simple cycle route: {' -> '.join(route_poi_names)}"

        personalization_summary = self._personalization_summary_payload(settings)
        return {
            "rank": idx,
            "score": scored.score,
            "base_score": scored.base_score,
            "personal_score": scored.personal_score,
            "hard_filter_passed": True,
            "soft_rank_weights": dict(settings.soft_rank_weights),
            "personalization_summary": personalization_summary,
            "route_poi_ids": route_poi_ids,
            "route_poi_names": route_poi_names,
            "route_poi_details": route_poi_details,
            "route_categories": list(scored.route.categories),
            "path_length": scored.route.path_length,
            "unique_poi_count": scored.route.unique_poi_count,
            "cycle_signature": cycle_signature,
            "is_closed_loop": True,
            "is_simple_cycle": True,
            "display_route_summary": display_summary,
            "pattern_score": scored.cycle_tpi,
            "cycle_support": scored.route.cycle_support,
            "cycle_tpi": scored.cycle_tpi,
            "cycle_strength_global": scored.cycle_strength_global,
            "avg_tpi": scored.route.avg_tpi,
            "avg_pair_tpi": scored.route.avg_pair_tpi,
            "popularity_score": scored.popularity_score,
            "preference_match_score": scored.preference_score,
            "start_fit_score": scored.start_fit_score,
            "time_fit_score": scored.time_fit_score,
            "season_fit_score": scored.season_fit_score,
            "route_length_score": scored.route_length_score,
            "dominant_supporting_season": scored.dominant_supporting_season,
            "season_match_count": scored.route.season_match_count,
            "season_total_count": scored.route.season_total_count,
            "must_visit_fit_score": scored.must_visit_fit_score,
            "category_count": scored.category_count,
            "unique_categories": scored.unique_categories,
            "category_diversity_score": scored.category_diversity_score,
            "dominant_category": scored.dominant_category,
            "dominant_category_ratio": scored.dominant_category_ratio,
            "single_type_penalty": scored.single_type_penalty,
            "travel_cost_km": scored.travel_cost_km,
            "estimated_total_duration_minutes": scored.estimated_total_duration,
            "must_visit_match_count": scored.must_visit_match_count,
            "start_distance_km": scored.route.start_distance_km,
            "reason_tags": _translate_reason_tags_for_web(scored.reason_tags),
            "fallback_reason": _translate_fallback_reason_for_web(scored.fallback_reason),
        }

    def recommend(self, request: UserRequest, top_k: int | None = None) -> Dict[str, Any]:
        """Run the full recommendation pipeline and return serializable data."""
        state = self._require_state()
        request = self._validate_and_normalize_request(request, state, top_k)
        settings = self._build_personalization_settings(request)
        requested_top_k = top_k if top_k is not None else self.config.top_k
        effective_top_k = min(requested_top_k, self.config.top_k)

        routes: List[RouteCandidate] = generate_routes_from_patterns(
            state.circular_patterns,
            state.poi_dict,
            config=self.config,
        )
        personalized: PersonalizationResult = filter_routes_by_personalization(
            routes=routes,
            poi_dict=state.poi_dict,
            trajectory_seasons=state.trajectory_seasons,
            requested_season=request.requested_season,
            start_poi=request.start_poi,
            must_include_pois=request.must_include_pois,
            fallback_limit=max(effective_top_k, 3),
            config=self.config,
        )
        filter_result = filter_routes(
            routes=personalized.routes,
            poi_dict=state.poi_dict,
            config=self.config,
            time_budget_hours=None,
        )
        hard_filter_result = apply_personalized_hard_filters(
            routes=filter_result.routes,
            poi_dict=state.poi_dict,
            config=self.config,
            request=request,
            settings=settings,
        )
        scored_routes = score_routes_for_recommendation(
            routes=hard_filter_result.routes,
            poi_dict=state.poi_dict,
            poi_popularity=state.poi_popularity,
            request=request,
            settings=settings,
            config=self.config,
            fallback_reason=personalized.fallback_reason,
        )
        recommendations = top_k_recommendations(
            scored_routes=scored_routes,
            top_k=effective_top_k,
            start_poi=None,
            must_include_pois=None,
            similarity_threshold=self.config.topk_similarity_threshold,
        )

        personalization_summary = self._personalization_summary_payload(settings)
        return {
            "request": asdict(request),
            "meta": {
                "requested_top_k": requested_top_k,
                "effective_top_k": effective_top_k,
                "initial_candidate_count": len(routes),
                "after_personalization_count": len(personalized.routes),
                "after_filter_count": len(filter_result.routes),
                "after_web_hard_filter_count": len(hard_filter_result.routes),
                "personalization_mode": "hard_filter_plus_soft_rank",
                "personalization_summary": personalization_summary,
                "quality_filter_removed": {
                    "removed_by_time": filter_result.removed_by_time,
                    "removed_by_distance": filter_result.removed_by_distance,
                    "removed_by_cycle_tpi": filter_result.removed_by_cycle_tpi,
                    "removed_by_length": filter_result.removed_by_length,
                },
                "web_hard_filter_removed": {
                    "removed_by_time_budget": hard_filter_result.removed_by_time_budget,
                    "removed_by_must_visit": hard_filter_result.removed_by_must_visit,
                    "removed_by_start_point": hard_filter_result.removed_by_start_point,
                    "removed_by_season": hard_filter_result.removed_by_season,
                },
                "fallback_reason": _translate_fallback_reason_for_web(
                    personalized.fallback_reason
                ),
            },
            "routes": [
                self._build_route_response_item(
                    i,
                    item,
                    state.poi_dict,
                    settings,
                    request.requested_season,
                )
                for i, item in enumerate(recommendations, start=1)
            ],
        }
