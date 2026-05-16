"""Shared configuration for the mining and recommendation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoreWeights:
    """Weights used by the generic route scoring path."""

    cycle_strength: float = 0.25
    popularity_score: float = 0.10
    preference_match_score: float = 0.15
    time_fit_score: float = 0.15
    start_fit_score: float = 0.10
    must_visit_fit_score: float = 0.10
    category_diversity_score: float = 0.10
    travel_cost_penalty: float = 0.10
    single_type_penalty: float = 0.05


@dataclass(frozen=True)
class PipelineConfig:
    """Unified configuration shared by CLI, Web, and mining code."""

    poi_file: str = "data/poi.csv"
    trajectory_file: str = "data/trajectory.csv"

    min_prev: float = 0.04
    max_cycle_length: int = 20
    min_gba_unique_pois: int = 2
    collapse_consecutive_duplicates: bool = True

    seasonality_min_share_threshold: float = 0.20

    top_k: int = 10
    average_speed_kmh: float = 20.0
    max_route_distance_km: float = 1000.0
    hard_time_overrun_ratio: float = 1.5
    soft_time_overrun_ratio: float = 1.2

    min_cycle_support: int = 1
    min_route_pois: int = 2
    max_route_pois: int = 40
    preferred_route_poi_count: int = 4
    topk_similarity_threshold: float = 0.30
    route_length_reward_weight: float = 0.12
    hard_start_distance_threshold_km: float = 3.0

    soft_rank_position_scores: dict[int, float] = field(
        default_factory=lambda: {
            1: 1.0,
            2: 0.7,
            3: 0.4,
            4: 0.2,
        }
    )
    base_score_weight: float = 0.4
    personal_score_weight: float = 0.6

    no_preference_weights: ScoreWeights = field(
        default_factory=lambda: ScoreWeights(
            preference_match_score=0.05,
            category_diversity_score=0.20,
            single_type_penalty=0.08,
        )
    )
    single_preference_weights: ScoreWeights = field(
        default_factory=lambda: ScoreWeights(
            preference_match_score=0.22,
            category_diversity_score=0.03,
            single_type_penalty=0.02,
        )
    )
    multi_preference_weights: ScoreWeights = field(
        default_factory=lambda: ScoreWeights(
            preference_match_score=0.18,
            category_diversity_score=0.10,
            single_type_penalty=0.05,
        )
    )
    dominant_high_threshold: float = 0.80
    dominant_mid_threshold: float = 0.60

    @property
    def cli_base_score_weight(self) -> float:
        """Backward-compatible alias for legacy CLI naming."""
        return self.base_score_weight

    @property
    def cli_personal_score_weight(self) -> float:
        """Backward-compatible alias for legacy CLI naming."""
        return self.personal_score_weight


DEFAULT_CONFIG = PipelineConfig()
