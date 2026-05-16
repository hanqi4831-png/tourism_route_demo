"""Shared data models used by the Web and legacy CLI layers."""

from __future__ import annotations

from dataclasses import dataclass, field

PERSONALIZATION_TIME_BUDGET = "time_budget"
PERSONALIZATION_MUST_VISIT = "must_visit"
PERSONALIZATION_START_POINT = "start_point"
PERSONALIZATION_TYPE_PREFERENCE = "type_preference"
PERSONALIZATION_SEASON = "season"

HARD_FILTER_KEYS = (
    PERSONALIZATION_TIME_BUDGET,
    PERSONALIZATION_MUST_VISIT,
    PERSONALIZATION_START_POINT,
    PERSONALIZATION_SEASON,
)

SOFT_RANK_KEYS = (
    PERSONALIZATION_TIME_BUDGET,
    PERSONALIZATION_MUST_VISIT,
    PERSONALIZATION_START_POINT,
    PERSONALIZATION_TYPE_PREFERENCE,
    PERSONALIZATION_SEASON,
)

PERSONALIZATION_LABELS = {
    PERSONALIZATION_TIME_BUDGET: "时间预算",
    PERSONALIZATION_MUST_VISIT: "必去点",
    PERSONALIZATION_START_POINT: "起点",
    PERSONALIZATION_TYPE_PREFERENCE: "类型偏好",
    PERSONALIZATION_SEASON: "季节",
}

# Backward-compatible aliases kept for the legacy CLI helpers.
CLI_PERSONALIZATION_TIME_BUDGET = PERSONALIZATION_TIME_BUDGET
CLI_PERSONALIZATION_MUST_VISIT = PERSONALIZATION_MUST_VISIT
CLI_PERSONALIZATION_START_POINT = PERSONALIZATION_START_POINT
CLI_PERSONALIZATION_TYPE_PREFERENCE = PERSONALIZATION_TYPE_PREFERENCE
CLI_PERSONALIZATION_SEASON = PERSONALIZATION_SEASON
CLI_HARD_FILTER_KEYS = HARD_FILTER_KEYS
CLI_SOFT_RANK_KEYS = SOFT_RANK_KEYS
CLI_PERSONALIZATION_LABELS = PERSONALIZATION_LABELS


@dataclass(frozen=True)
class UserRequest:
    """Normalized user request shared by CLI and Web."""

    preferred_categories: list[str] = field(default_factory=list)
    requested_season: str | None = None
    start_poi: str | None = None
    must_include_pois: list[str] = field(default_factory=list)
    time_budget_hours: float | None = None
    hard_filter_keys: list[str] = field(default_factory=list)
    soft_rank_groups: list[list[str]] = field(default_factory=list)
    soft_rank_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonalizationSettings:
    """Shared personalization settings for CLI and Web."""

    hard_filter_keys: list[str] = field(default_factory=list)
    soft_rank_groups: list[list[str]] = field(default_factory=list)
    soft_rank_weights: dict[str, float] = field(default_factory=dict)


CLIPersonalizationSettings = PersonalizationSettings


@dataclass(frozen=True)
class RecommendationMeta:
    """Extra recommendation details kept for display and export."""

    estimated_total_duration: float
    reason_tags: list[str]
    fallback_reason: str | None
    must_visit_match_count: int
    start_fit_score: float
    time_fit_score: float
    season_fit_score: float
    category_count: int
    unique_categories: list[str]
    category_diversity_score: float
    dominant_category: str | None
    dominant_category_ratio: float
    single_type_penalty: float
