"""将 CIKM16 Melbourne 数据清洗为本项目可直接使用的 CSV 格式。

输入（默认）:
- data-cikm16/POI-Melb.csv
- data-cikm16/userVisits-Melb-allPOI.csv

输出（默认）:
- data-cikm16/cleaned/poi.csv
- data-cikm16/cleaned/trajectory.csv

用法示例:
    python clean_cikm16_to_demo.py
    python clean_cikm16_to_demo.py --input-dir "data-cikm16" --output-dir "data"
    python clean_cikm16_to_demo.py --min-visits-per-trajectory 3
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd


@dataclass
class CleanConfig:
    input_dir: Path
    output_dir: Path
    min_visits_per_trajectory: int = 2
    dedup_consecutive_same_poi: bool = True
    default_opening_hours: str = "09:00-18:00"


def _normalize_category(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def _estimate_visit_duration_minutes(category: str) -> float:
    """
    按类别给出简易停留时长估计（分钟）。
    仅用于生成 demo 所需字段，不影响原始轨迹顺序。
    """
    cat = category.lower()
    if any(k in cat for k in ["transport", "station", "carpark"]):
        return 25.0
    if any(k in cat for k in ["museum", "gallery", "library", "cultural", "assembly"]):
        return 80.0
    if any(k in cat for k in ["park", "garden", "leisure", "recreation"]):
        return 60.0
    if any(k in cat for k in ["retail", "shopping", "mixed_use"]):
        return 50.0
    if any(k in cat for k in ["worship", "church"]):
        return 45.0
    return 55.0


def clean_poi_table(poi_raw: pd.DataFrame, opening_hours: str) -> pd.DataFrame:
    poi = poi_raw.rename(
        columns={
            "poiID": "raw_poi_id",
            "poiName": "poi_name",
            "theme": "theme",
            "lat": "latitude",
            "long": "longitude",
        }
    ).copy()
    required = {"raw_poi_id", "poi_name", "theme", "latitude", "longitude"}
    missing = required - set(poi.columns)
    if missing:
        raise ValueError(f"POI-Melb.csv 缺少字段: {', '.join(sorted(missing))}")

    poi["poi_id"] = poi["raw_poi_id"].apply(lambda x: f"P{int(x):03d}")
    poi["category"] = poi["theme"].astype(str).apply(_normalize_category)
    poi["visit_duration_minutes"] = poi["category"].apply(_estimate_visit_duration_minutes)
    poi["opening_hours"] = opening_hours

    cleaned = poi[
        [
            "poi_id",
            "poi_name",
            "category",
            "latitude",
            "longitude",
            "visit_duration_minutes",
            "opening_hours",
        ]
    ].drop_duplicates(subset=["poi_id"])
    return cleaned


def clean_trajectory_table(
    visits_raw: pd.DataFrame,
    min_visits_per_trajectory: int,
    dedup_consecutive_same_poi: bool,
) -> pd.DataFrame:
    visits = visits_raw.rename(
        columns={
            "userID": "user_id",
            "dateTaken": "timestamp_unix",
            "poiID": "raw_poi_id",
            "seqID": "seq_id",
        }
    ).copy()
    required = {"user_id", "timestamp_unix", "raw_poi_id", "seq_id"}
    missing = required - set(visits.columns)
    if missing:
        raise ValueError(f"userVisits-Melb-allPOI.csv 缺少字段: {', '.join(sorted(missing))}")

    visits["poi_id"] = visits["raw_poi_id"].apply(lambda x: f"P{int(x):03d}")
    ts_num = pd.to_numeric(visits["timestamp_unix"], errors="coerce")
    # CIKM16 数据中可能混有异常或不同精度时间戳：
    # - <=1e11 视为秒级
    # - >1e11 视为毫秒级
    ts_sec = pd.to_datetime(ts_num.where(ts_num <= 1e11), unit="s", utc=True, errors="coerce")
    ts_ms = pd.to_datetime(ts_num.where(ts_num > 1e11), unit="ms", utc=True, errors="coerce")
    visits["timestamp"] = ts_sec.fillna(ts_ms)
    visits = visits.dropna(subset=["timestamp"])
    visits["trajectory_id"] = visits["seq_id"].apply(lambda x: f"T{int(x):06d}")
    visits = visits.sort_values(["trajectory_id", "timestamp", "poi_id"]).reset_index(drop=True)

    if dedup_consecutive_same_poi:
        visits["prev_poi"] = visits.groupby("trajectory_id")["poi_id"].shift(1)
        visits = visits[visits["poi_id"] != visits["prev_poi"]].drop(columns=["prev_poi"])

    # 过滤过短轨迹，避免过多无效模式
    valid_ids = (
        visits.groupby("trajectory_id")["poi_id"]
        .count()
        .reset_index(name="n")
        .query("n >= @min_visits_per_trajectory")["trajectory_id"]
        .tolist()
    )
    visits = visits[visits["trajectory_id"].isin(valid_ids)].copy()

    visits["visit_order"] = visits.groupby("trajectory_id").cumcount() + 1
    visits["timestamp"] = visits["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    cleaned = visits[
        ["user_id", "trajectory_id", "visit_order", "poi_id", "timestamp"]
    ].reset_index(drop=True)
    return cleaned


def run_cleaning(config: CleanConfig) -> Dict[str, int]:
    poi_path = config.input_dir / "POI-Melb.csv"
    visits_path = config.input_dir / "userVisits-Melb-allPOI.csv"
    if not poi_path.exists() or not visits_path.exists():
        raise FileNotFoundError(
            "未找到输入文件，请确认 data-cikm16 下包含 POI-Melb.csv 与 userVisits-Melb-allPOI.csv"
        )

    poi_raw = pd.read_csv(poi_path, sep=";")
    visits_raw = pd.read_csv(visits_path, sep=";")

    poi_clean = clean_poi_table(poi_raw, opening_hours=config.default_opening_hours)
    traj_clean = clean_trajectory_table(
        visits_raw,
        min_visits_per_trajectory=config.min_visits_per_trajectory,
        dedup_consecutive_same_poi=config.dedup_consecutive_same_poi,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    poi_out = config.output_dir / "poi.csv"
    traj_out = config.output_dir / "trajectory.csv"
    poi_clean.to_csv(poi_out, index=False, encoding="utf-8-sig")
    traj_clean.to_csv(traj_out, index=False, encoding="utf-8-sig")

    return {
        "poi_count": len(poi_clean),
        "trajectory_count": traj_clean["trajectory_id"].nunique(),
        "visit_count": len(traj_clean),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清洗 CIKM16 数据为 demo 可用格式")
    parser.add_argument(
        "--input-dir",
        type=str,
        default="data-cikm16",
        help="原始 CIKM16 数据目录（默认 data-cikm16）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data-cikm16/cleaned",
        help="输出目录（默认 data-cikm16/cleaned）",
    )
    parser.add_argument(
        "--min-visits-per-trajectory",
        type=int,
        default=2,
        help="保留轨迹最小访问点数（默认 2）",
    )
    parser.add_argument(
        "--disable-dedup-consecutive",
        action="store_true",
        help="关闭同轨迹连续重复 POI 去重",
    )
    return parser.parse_args()


def _resolve_path(base_dir: Path, user_path: str) -> Path:
    """将用户路径解析为绝对路径；相对路径按脚本目录解释。"""
    p = Path(user_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    config = CleanConfig(
        input_dir=_resolve_path(base_dir, args.input_dir),
        output_dir=_resolve_path(base_dir, args.output_dir),
        min_visits_per_trajectory=args.min_visits_per_trajectory,
        dedup_consecutive_same_poi=not args.disable_dedup_consecutive,
    )
    stats = run_cleaning(config)
    print("数据清洗完成。")
    print(f"POI 数量: {stats['poi_count']}")
    print(f"轨迹数量: {stats['trajectory_count']}")
    print(f"访问记录数: {stats['visit_count']}")
    print(f"输出文件: {config.output_dir / 'poi.csv'}")
    print(f"输出文件: {config.output_dir / 'trajectory.csv'}")


if __name__ == "__main__":
    main()
