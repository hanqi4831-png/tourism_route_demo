"""样例数据生成模块。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def _build_poi_dataframe() -> pd.DataFrame:
    categories = ["culture", "food", "nature", "shopping", "museum"]
    duration_by_category = {
        "culture": (60, 90),
        "food": (30, 60),
        "nature": (45, 75),
        "shopping": (40, 70),
        "museum": (60, 90),
    }
    base_lat, base_lon = 37.46, 121.44
    rng = np.random.default_rng(seed=20260314)
    rows = []
    for i in range(1, 21):
        poi_id = f"P{i:02d}"
        category = categories[(i - 1) % len(categories)]
        low, high = duration_by_category[category]
        visit_duration = float(rng.integers(low, high + 1))
        rows.append(
            {
                "poi_id": poi_id,
                "poi_name": f"POI_{i:02d}",
                "category": category,
                "latitude": base_lat + (i % 5) * 0.02,
                "longitude": base_lon + (i // 5) * 0.02,
                "visit_duration_minutes": visit_duration,
                "opening_hours": "09:00-18:00",
            }
        )
    return pd.DataFrame(rows)


def _pick_route_template(rng: np.random.Generator) -> List[str]:
    templates = [
        ["P01", "P06", "P11", "P01"],
        ["P02", "P07", "P12", "P02"],
        ["P03", "P08", "P13", "P03"],
        ["P04", "P09", "P14", "P04"],
        ["P05", "P10", "P15", "P05"],
        ["P16", "P17", "P18", "P16"],
        ["P19", "P20", "P01", "P19"],
    ]
    base = templates[int(rng.integers(0, len(templates)))].copy()
    if rng.random() < 0.35:
        insert = f"P{int(rng.integers(1, 21)):02d}"
        base.insert(-1, insert)
    return base


def generate_sample_data(poi_file: str | Path, trajectory_file: str | Path) -> None:
    """生成20个POI和100条轨迹样例数据。"""
    poi_path = Path(poi_file)
    traj_path = Path(trajectory_file)
    poi_path.parent.mkdir(parents=True, exist_ok=True)
    traj_path.parent.mkdir(parents=True, exist_ok=True)

    poi_df = _build_poi_dataframe()
    poi_df.to_csv(poi_path, index=False)

    rng = np.random.default_rng(seed=20260314)
    start_time = datetime(2026, 3, 14, 8, 0, 0)
    trajectory_rows = []
    for i in range(1, 101):
        trajectory_id = f"T{i:03d}"
        user_id = f"U{int(rng.integers(1, 31)):03d}"
        route = _pick_route_template(rng)
        for order, poi_id in enumerate(route, start=1):
            timestamp = start_time + timedelta(minutes=10 * i + order * 15)
            trajectory_rows.append(
                {
                    "user_id": user_id,
                    "trajectory_id": trajectory_id,
                    "visit_order": order,
                    "poi_id": poi_id,
                    "timestamp": timestamp.isoformat(),
                }
            )
    pd.DataFrame(trajectory_rows).to_csv(traj_path, index=False)
