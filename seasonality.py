"""Seasonality profiling helpers for recommendation-side personalization."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, Sequence

from data_loader import VisitRecord
from utils import unique_preserve_order

SUPPORTED_SEASONS: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
DEFAULT_SUITABLE_SEASON = "all"
SEASON_MONTHS: dict[str, set[int]] = {
    "spring": {3, 4, 5},
    "summer": {6, 7, 8},
    "autumn": {9, 10, 11},
    "winter": {12, 1, 2},
}
SEASON_RING_INDEX = {
    season: index for index, season in enumerate(SUPPORTED_SEASONS)
}


def normalize_requested_season(value: str | None) -> str | None:
    """Normalize a user-provided season string."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized not in SUPPORTED_SEASONS:
        raise ValueError(f"Unsupported season: {value}")
    return normalized


def normalize_suitable_season_tokens(candidates: Iterable[str]) -> tuple[str, ...]:
    """Normalize suitable season tokens into a compact tuple form."""
    tokens = tuple(
        unique_preserve_order(
            token.strip().lower()
            for token in candidates
            if token and token.strip()
        )
    )
    normalized_tokens = tuple(
        token
        for token in tokens
        if token == DEFAULT_SUITABLE_SEASON or token in SUPPORTED_SEASONS
    )
    if not normalized_tokens:
        return (DEFAULT_SUITABLE_SEASON,)
    if DEFAULT_SUITABLE_SEASON in normalized_tokens:
        return (DEFAULT_SUITABLE_SEASON,)
    if len(normalized_tokens) >= len(SUPPORTED_SEASONS):
        return (DEFAULT_SUITABLE_SEASON,)
    return normalized_tokens


def format_suitable_season_text(tokens: Sequence[str]) -> str:
    """Convert season tokens into the persisted CSV string form."""
    normalized_tokens = normalize_suitable_season_tokens(tokens)
    if normalized_tokens == (DEFAULT_SUITABLE_SEASON,):
        return DEFAULT_SUITABLE_SEASON
    return ",".join(normalized_tokens)


def _parse_timestamp(timestamp_text: str | None) -> datetime | None:
    if timestamp_text is None:
        return None
    text = str(timestamp_text).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def infer_season_from_timestamp_text(timestamp_text: str | None) -> str | None:
    """Infer season from an ISO-like timestamp string."""
    timestamp = _parse_timestamp(timestamp_text)
    if timestamp is None:
        return None
    month = int(timestamp.month)
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return None


def build_trajectory_season_lookup(
    trajectory_dict: Mapping[str, Sequence[VisitRecord]],
) -> Dict[str, str]:
    """Infer one season label for each trajectory from its earliest valid timestamp."""
    season_lookup: Dict[str, str] = {}
    for trajectory_id, records in trajectory_dict.items():
        ordered = sorted(records, key=lambda item: item["visit_order"])
        season: str | None = None
        for record in ordered:
            season = infer_season_from_timestamp_text(record.get("timestamp"))
            if season is not None:
                break
        if season is not None:
            season_lookup[str(trajectory_id)] = season
    return season_lookup


def infer_suitable_seasons_from_counts(
    season_counts: Mapping[str, int],
    *,
    min_share_threshold: float,
) -> tuple[str, ...]:
    """Convert season counts into route-side suitable seasons."""
    cleaned_counts = Counter(
        season
        for season, count in season_counts.items()
        if season in SUPPORTED_SEASONS and count > 0
    )
    if not cleaned_counts:
        return (DEFAULT_SUITABLE_SEASON,)

    total = sum(cleaned_counts.values())
    shares = {season: cleaned_counts[season] / total for season in cleaned_counts}
    selected = [
        season
        for season in SUPPORTED_SEASONS
        if shares.get(season, 0.0) >= min_share_threshold
    ]
    if not selected:
        selected = [cleaned_counts.most_common(1)[0][0]]
    return normalize_suitable_season_tokens(selected)


def build_poi_suitable_season_lookup(
    trajectory_dict: Mapping[str, Sequence[VisitRecord]],
    *,
    min_share_threshold: float,
) -> Dict[str, tuple[str, ...]]:
    """Infer suitable seasons for each POI from historical visit timestamps."""
    season_counts_by_poi: dict[str, Counter[str]] = defaultdict(Counter)
    for records in trajectory_dict.values():
        for record in records:
            season = infer_season_from_timestamp_text(record.get("timestamp"))
            if season is None:
                continue
            season_counts_by_poi[str(record["poi_id"])][season] += 1

    return {
        poi_id: infer_suitable_seasons_from_counts(
            season_counts,
            min_share_threshold=min_share_threshold,
        )
        for poi_id, season_counts in season_counts_by_poi.items()
    }


def attach_poi_suitable_seasons(
    poi_dict: Dict[str, dict],
    suitable_season_lookup: Mapping[str, Sequence[str]],
    *,
    overwrite_existing: bool = True,
) -> None:
    """Attach suitable seasons to each POI record in-place."""
    for poi_id, poi_info in poi_dict.items():
        if not overwrite_existing and (
            "suitable_season" in poi_info or "suitable_seasons" in poi_info
        ):
            continue

        normalized_tokens = normalize_suitable_season_tokens(
            suitable_season_lookup.get(
                poi_id,
                (DEFAULT_SUITABLE_SEASON,),
            )
        )
        poi_info["suitable_seasons"] = normalized_tokens
        poi_info["suitable_season"] = format_suitable_season_text(normalized_tokens)


def extract_suitable_seasons(poi_info: Mapping[str, object]) -> tuple[str, ...]:
    """Read suitable season tokens from a POI record."""
    raw_value = poi_info.get("suitable_seasons")
    if isinstance(raw_value, str):
        candidates: Iterable[str] = raw_value.split(",")
    elif raw_value is None:
        fallback = poi_info.get("suitable_season")
        if isinstance(fallback, str):
            candidates = fallback.split(",")
        else:
            candidates = ()
    else:
        candidates = [str(item) for item in raw_value]
    return normalize_suitable_season_tokens(candidates)


def compute_dominant_supporting_season(
    supporting_trajectory_ids: Iterable[str],
    trajectory_season_lookup: Mapping[str, str],
    requested_season: str | None = None,
) -> str | None:
    """Return the dominant season among a route's supporting trajectories."""
    normalized_requested = normalize_requested_season(requested_season)
    season_counter = Counter(
        trajectory_season_lookup[str(trajectory_id)]
        for trajectory_id in supporting_trajectory_ids
        if str(trajectory_id) in trajectory_season_lookup
    )
    if not season_counter:
        return None

    top_count = max(season_counter.values())
    tied_top_seasons = [
        season
        for season in SUPPORTED_SEASONS
        if season_counter.get(season, 0) == top_count
    ]
    if normalized_requested in tied_top_seasons:
        return normalized_requested
    return tied_top_seasons[0] if tied_top_seasons else None


def compute_route_season_fit(
    poi_ids: Sequence[str],
    poi_dict: Mapping[str, Mapping[str, object]],
    requested_season: str | None,
    *,
    dominant_supporting_season: str | None,
) -> tuple[float, int, int]:
    """Compute season fit as the ratio of POIs suitable for the requested season."""
    normalized_season = normalize_requested_season(requested_season)
    if normalized_season is None:
        return 1.0, 0, 0

    unique_pois = unique_preserve_order(str(poi_id) for poi_id in poi_ids)
    if not unique_pois:
        return 1.0, 0, 0

    suitable_seasons = [
        extract_suitable_seasons(poi_dict.get(poi_id, {}))
        for poi_id in unique_pois
    ]
    if all(tokens == (DEFAULT_SUITABLE_SEASON,) for tokens in suitable_seasons):
        matched = len(unique_pois) if dominant_supporting_season == normalized_season else 0
        score = 1.0 if matched else 0.0
        return score, matched, len(unique_pois)

    matched = sum(
        1
        for tokens in suitable_seasons
        if DEFAULT_SUITABLE_SEASON in tokens or normalized_season in tokens
    )
    total = len(unique_pois)
    return matched / max(total, 1), matched, total


def season_ring_distance(left: str | None, right: str | None) -> int:
    """Compute circular distance on the season ring."""
    normalized_left = normalize_requested_season(left)
    normalized_right = normalize_requested_season(right)
    if normalized_left is None or normalized_right is None:
        return len(SUPPORTED_SEASONS)

    left_index = SEASON_RING_INDEX[normalized_left]
    right_index = SEASON_RING_INDEX[normalized_right]
    delta = abs(left_index - right_index)
    return min(delta, len(SUPPORTED_SEASONS) - delta)


def resolve_poi_display_season(
    suitable_seasons: Sequence[str],
    requested_season: str | None,
    route_dominant_season: str | None,
) -> tuple[str | None, str]:
    """Choose the season label to display for a POI in the current request."""
    normalized_tokens = normalize_suitable_season_tokens(suitable_seasons)
    normalized_request = normalize_requested_season(requested_season)
    normalized_route_dominant = normalize_requested_season(route_dominant_season)

    if normalized_request is None:
        return None, "no_requested_season"
    if DEFAULT_SUITABLE_SEASON in normalized_tokens:
        return normalized_request, "all_season_match"
    if normalized_request in normalized_tokens:
        return normalized_request, "exact_request_match"

    candidate_seasons = [
        season for season in normalized_tokens if season in SUPPORTED_SEASONS
    ]
    if not candidate_seasons:
        return None, "no_suitable_season"

    if normalized_route_dominant is not None:
        display_season = min(
            candidate_seasons,
            key=lambda season: (
                season_ring_distance(season, normalized_route_dominant),
                candidate_seasons.index(season),
            ),
        )
        return display_season, "closest_to_route_dominant_season"

    display_season = min(
        candidate_seasons,
        key=lambda season: (
            season_ring_distance(season, normalized_request),
            candidate_seasons.index(season),
        ),
    )
    return display_season, "fallback_to_requested_season_distance"


def build_route_poi_season_details(
    poi_ids: Sequence[str],
    poi_dict: Mapping[str, Mapping[str, object]],
    *,
    requested_season: str | None,
    route_dominant_season: str | None,
) -> list[dict[str, Any]]:
    """Build per-POI season display details for recommendation outputs."""
    unique_poi_ids = unique_preserve_order(str(poi_id) for poi_id in poi_ids)
    details: list[dict[str, Any]] = []

    for poi_id in unique_poi_ids:
        poi_info = poi_dict.get(poi_id, {})
        suitable_tokens = extract_suitable_seasons(poi_info)
        display_season, display_reason = resolve_poi_display_season(
            suitable_tokens,
            requested_season=requested_season,
            route_dominant_season=route_dominant_season,
        )
        details.append(
            {
                "poi_id": poi_id,
                "poi_name": str(poi_info.get("poi_name", poi_id)),
                "category": str(poi_info.get("category", "unknown")),
                "suitable_seasons": list(suitable_tokens),
                "display_season": display_season,
                "display_season_reason": display_reason,
            }
        )

    return details
