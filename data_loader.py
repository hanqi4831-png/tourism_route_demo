"""Data loading helpers for the route recommendation demo."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, NotRequired, TypedDict

import pandas as pd

SUPPORTED_SEASONS: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
DEFAULT_SUITABLE_SEASON = "all"


class POIInfo(TypedDict):
    poi_id: str
    poi_name: str
    category: str
    latitude: float
    longitude: float
    visit_duration_minutes: float
    opening_hours: str | None
    suitable_season: NotRequired[str]
    suitable_seasons: NotRequired[tuple[str, ...]]


class VisitRecord(TypedDict):
    user_id: str
    trajectory_id: str
    visit_order: int
    poi_id: str
    timestamp: str


def _normalize_suitable_season_value(raw_value: object) -> tuple[str, ...] | None:
    if raw_value is None or pd.isna(raw_value):
        return None

    tokens: list[str] = []
    for part in str(raw_value).split(","):
        token = part.strip().lower()
        if not token:
            continue
        if token == DEFAULT_SUITABLE_SEASON:
            return (DEFAULT_SUITABLE_SEASON,)
        if token in SUPPORTED_SEASONS and token not in tokens:
            tokens.append(token)

    if not tokens:
        return None
    if len(tokens) >= len(SUPPORTED_SEASONS):
        return (DEFAULT_SUITABLE_SEASON,)
    return tuple(tokens)


def load_poi_data(file_path: str | Path) -> Dict[str, POIInfo]:
    """Load POI data and index it by ``poi_id``."""
    df = pd.read_csv(file_path)
    has_suitable_season = "suitable_season" in df.columns
    poi_dict: Dict[str, POIInfo] = {}

    for _, row in df.iterrows():
        poi_id = str(row["poi_id"])
        poi_info: POIInfo = POIInfo(
            poi_id=poi_id,
            poi_name=str(row["poi_name"]),
            category=str(row["category"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            visit_duration_minutes=float(row.get("visit_duration_minutes", 60.0)),
            opening_hours=(
                str(row["opening_hours"])
                if "opening_hours" in df.columns and pd.notna(row["opening_hours"])
                else None
            ),
        )

        if has_suitable_season:
            tokens = _normalize_suitable_season_value(row.get("suitable_season"))
            if tokens is not None:
                poi_info["suitable_seasons"] = tokens
                poi_info["suitable_season"] = (
                    DEFAULT_SUITABLE_SEASON
                    if tokens == (DEFAULT_SUITABLE_SEASON,)
                    else ",".join(tokens)
                )

        poi_dict[poi_id] = poi_info

    return poi_dict


def load_trajectory_data(file_path: str | Path) -> Dict[str, List[VisitRecord]]:
    """Load trajectory data and group visit records by ``trajectory_id``."""
    df = pd.read_csv(file_path)
    grouped: Dict[str, List[VisitRecord]] = {}
    for _, row in df.iterrows():
        trajectory_id = str(row["trajectory_id"])
        record = VisitRecord(
            user_id=str(row["user_id"]),
            trajectory_id=trajectory_id,
            visit_order=int(row["visit_order"]),
            poi_id=str(row["poi_id"]),
            timestamp=str(row["timestamp"]),
        )
        grouped.setdefault(trajectory_id, []).append(record)
    return grouped
