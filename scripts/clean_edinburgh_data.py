"""Clean Edinburgh source data into the route system's target CSV format."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


MIN_VALID_TIMESTAMP = pd.Timestamp("2000-01-01", tz="UTC")
MAX_VALID_TIMESTAMP = pd.Timestamp("2035-01-01", tz="UTC")
DEFAULT_VISIT_DURATION_MINUTES = 60.0
EXPECTED_COST_COLUMNS = {"from", "to", "cost", "profit", "category"}


@dataclass(frozen=True)
class CleanConfig:
    project_root: Path
    input_dir: Path
    output_dir: Path
    poi_filename: str = "POI-Edin.csv"
    visits_filename: str = "userVisits-Edin.csv"
    cost_filename: str = "costProfCat-EdinPOI-all.csv"
    default_visit_duration_minutes: float = DEFAULT_VISIT_DURATION_MINUTES

    @property
    def poi_path(self) -> Path:
        return self.input_dir / self.poi_filename

    @property
    def visits_path(self) -> Path:
        return self.input_dir / self.visits_filename

    @property
    def cost_path(self) -> Path:
        return self.input_dir / self.cost_filename


def load_poi_file(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def load_visits_file(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def load_cost_profit_file(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def normalize_poi_ids(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("Int64")
    return numeric.map(lambda value: f"EDIN_P{int(value)}" if pd.notna(value) else pd.NA)


def normalize_trajectory_ids(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("Int64")
    return numeric.map(lambda value: f"EDIN_T{int(value)}" if pd.notna(value) else pd.NA)


def clean_poi_table(poi_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    longitude_column = "long" if "long" in poi_raw.columns else "lon" if "lon" in poi_raw.columns else None
    if longitude_column is None:
        raise ValueError("POI file is missing the longitude column: expected 'long' or 'lon'.")

    poi = poi_raw.rename(
        columns={
            "poiID": "raw_poi_id",
            "poiName": "poi_name",
            "theme": "category",
            "lat": "latitude",
            longitude_column: "longitude",
        }
    ).copy()

    required = {"raw_poi_id", "poi_name", "category", "latitude", "longitude"}
    missing = required - set(poi.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"POI file is missing required columns: {missing_text}")

    poi["raw_poi_id_num"] = pd.to_numeric(poi["raw_poi_id"], errors="coerce")
    poi["poi_name"] = poi["poi_name"].astype(str).str.strip()
    poi["category"] = poi["category"].astype(str).str.strip()
    poi["latitude"] = pd.to_numeric(poi["latitude"], errors="coerce")
    poi["longitude"] = pd.to_numeric(poi["longitude"], errors="coerce")

    invalid_coord_mask = (
        poi["raw_poi_id_num"].isna()
        | poi["latitude"].isna()
        | poi["longitude"].isna()
        | (poi["latitude"] < -90)
        | (poi["latitude"] > 90)
        | (poi["longitude"] < -180)
        | (poi["longitude"] > 180)
    )
    invalid_coord_count = int(invalid_coord_mask.sum())

    poi = poi.loc[~invalid_coord_mask].copy()
    poi["poi_id"] = normalize_poi_ids(poi["raw_poi_id_num"])
    poi["opening_hours"] = ""

    if poi["poi_id"].duplicated().any():
        duplicated = poi.loc[poi["poi_id"].duplicated(), "poi_id"].tolist()
        raise ValueError(f"Duplicate POI IDs found after normalization: {duplicated[:5]}")

    empty_name_count = int(poi["poi_name"].eq("").sum())
    empty_category_count = int(poi["category"].eq("").sum())
    if empty_name_count or empty_category_count:
        raise ValueError(
            "POI file contains empty required text fields after cleaning: "
            f"empty poi_name={empty_name_count}, empty category={empty_category_count}"
        )

    poi = poi.sort_values("raw_poi_id_num").reset_index(drop=True)
    return (
        poi[
            [
                "raw_poi_id_num",
                "poi_id",
                "poi_name",
                "category",
                "latitude",
                "longitude",
                "opening_hours",
            ]
        ],
        {
            "invalid_coordinate_poi_count": invalid_coord_count,
            "retained_poi_count": int(len(poi)),
        },
    )


def clean_visit_records(
    visits_raw: pd.DataFrame,
    valid_poi_ids: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    visits = visits_raw.rename(
        columns={
            "photoID": "photo_id",
            "userID": "user_id",
            "dateTaken": "timestamp_unix",
            "poiID": "raw_poi_id",
            "seqID": "raw_trajectory_id",
        }
    ).copy()

    required = {"photo_id", "user_id", "timestamp_unix", "raw_poi_id", "raw_trajectory_id"}
    missing = required - set(visits.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Visits file is missing required columns: {missing_text}")

    visits["source_row"] = range(len(visits))
    visits["user_id"] = visits["user_id"].astype(str).str.strip()
    visits["timestamp_unix_num"] = pd.to_numeric(visits["timestamp_unix"], errors="coerce")
    visits["raw_poi_id_num"] = pd.to_numeric(visits["raw_poi_id"], errors="coerce")
    visits["raw_trajectory_id_num"] = pd.to_numeric(visits["raw_trajectory_id"], errors="coerce")
    visits["timestamp_dt"] = pd.to_datetime(visits["timestamp_unix_num"], unit="s", utc=True, errors="coerce")

    invalid_time_mask = (
        visits["timestamp_dt"].isna()
        | (visits["timestamp_dt"] < MIN_VALID_TIMESTAMP)
        | (visits["timestamp_dt"] > MAX_VALID_TIMESTAMP)
    )
    removed_invalid_time_records = int(invalid_time_mask.sum())
    visits = visits.loc[~invalid_time_mask].copy()

    invalid_identity_mask = (
        visits["user_id"].eq("")
        | visits["raw_poi_id_num"].isna()
        | visits["raw_trajectory_id_num"].isna()
    )
    removed_invalid_identity_records = int(invalid_identity_mask.sum())
    visits = visits.loc[~invalid_identity_mask].copy()

    visits["poi_id"] = normalize_poi_ids(visits["raw_poi_id_num"])
    visits["trajectory_id"] = normalize_trajectory_ids(visits["raw_trajectory_id_num"])

    unmapped_poi_mask = ~visits["poi_id"].isin(valid_poi_ids)
    removed_unmapped_poi_records = int(unmapped_poi_mask.sum())
    visits = visits.loc[~unmapped_poi_mask].copy()

    visits = visits.sort_values(["raw_trajectory_id_num", "timestamp_dt", "source_row"]).reset_index(drop=True)

    users_per_trajectory = visits.groupby("trajectory_id")["user_id"].nunique()
    multi_user_trajectories = users_per_trajectory[users_per_trajectory > 1]
    if not multi_user_trajectories.empty:
        sample = ", ".join(multi_user_trajectories.index[:5])
        raise ValueError(f"Found trajectories with multiple users assigned: {sample}")

    return (
        visits[
            [
                "photo_id",
                "user_id",
                "timestamp_dt",
                "raw_poi_id_num",
                "raw_trajectory_id_num",
                "trajectory_id",
                "poi_id",
                "source_row",
            ]
        ],
        {
            "removed_invalid_time_records": removed_invalid_time_records,
            "removed_invalid_identity_records": removed_invalid_identity_records,
            "removed_unmapped_poi_records": removed_unmapped_poi_records,
            "clean_photo_record_count": int(len(visits)),
            "clean_sequence_count": int(visits["trajectory_id"].nunique()),
        },
    )


def aggregate_consecutive_same_poi(visits: pd.DataFrame) -> pd.DataFrame:
    if visits.empty:
        raise ValueError("No visit records remain after cleaning.")

    previous_poi = visits.groupby("trajectory_id")["poi_id"].shift(1)
    visits = visits.copy()
    visits["starts_new_visit"] = visits["poi_id"].ne(previous_poi)
    visits["visit_block"] = visits.groupby("trajectory_id")["starts_new_visit"].cumsum()

    aggregated = (
        visits.groupby(["trajectory_id", "visit_block"], sort=False)
        .agg(
            user_id=("user_id", "first"),
            poi_id=("poi_id", "first"),
            arrival_time=("timestamp_dt", "min"),
            departure_time=("timestamp_dt", "max"),
        )
        .reset_index()
    )
    aggregated["visit_duration_minutes"] = (
        aggregated["departure_time"] - aggregated["arrival_time"]
    ).dt.total_seconds() / 60.0
    aggregated["visit_order"] = aggregated.groupby("trajectory_id").cumcount() + 1
    aggregated["timestamp"] = aggregated["arrival_time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return aggregated


def estimate_poi_visit_duration(
    poi_table: pd.DataFrame,
    aggregated_visits: pd.DataFrame,
    default_duration_minutes: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    positive_visits = aggregated_visits.loc[
        aggregated_visits["visit_duration_minutes"] > 0,
        ["poi_id", "visit_duration_minutes"],
    ].copy()
    poi_duration_median = positive_visits.groupby("poi_id")["visit_duration_minutes"].median()

    poi_with_duration = poi_table.copy()
    poi_with_duration["visit_duration_minutes"] = poi_with_duration["poi_id"].map(poi_duration_median)
    used_default_duration_mask = poi_with_duration["visit_duration_minutes"].isna()
    poi_with_duration["visit_duration_minutes"] = (
        poi_with_duration["visit_duration_minutes"]
        .fillna(default_duration_minutes)
        .round(2)
    )

    return (
        poi_with_duration,
        {
            "positive_visit_duration_sample_count": int(len(positive_visits)),
            "default_duration_poi_count": int(used_default_duration_mask.sum()),
            "poi_duration_mean": float(poi_with_duration["visit_duration_minutes"].mean()),
            "poi_duration_median": float(poi_with_duration["visit_duration_minutes"].median()),
        },
    )


def build_poi_csv(poi_table: pd.DataFrame) -> pd.DataFrame:
    return poi_table[
        [
            "poi_id",
            "poi_name",
            "category",
            "latitude",
            "longitude",
            "visit_duration_minutes",
            "opening_hours",
        ]
    ].copy()


def build_trajectory_csv(aggregated_visits: pd.DataFrame) -> pd.DataFrame:
    return aggregated_visits[
        ["user_id", "trajectory_id", "visit_order", "poi_id", "timestamp"]
    ].copy()


def validate_outputs(poi_csv: pd.DataFrame, trajectory_csv: pd.DataFrame) -> None:
    if poi_csv["poi_id"].duplicated().any():
        raise ValueError("poi.csv validation failed: poi_id must be unique.")

    if poi_csv["poi_name"].astype(str).str.strip().eq("").any():
        raise ValueError("poi.csv validation failed: poi_name contains empty values.")

    if poi_csv["category"].astype(str).str.strip().eq("").any():
        raise ValueError("poi.csv validation failed: category contains empty values.")

    lat = pd.to_numeric(poi_csv["latitude"], errors="coerce")
    lon = pd.to_numeric(poi_csv["longitude"], errors="coerce")
    invalid_coords = lat.isna() | lon.isna() | (lat < -90) | (lat > 90) | (lon < -180) | (lon > 180)
    if invalid_coords.any():
        raise ValueError("poi.csv validation failed: invalid latitude/longitude values detected.")

    durations = pd.to_numeric(poi_csv["visit_duration_minutes"], errors="coerce")
    if durations.isna().any() or (durations < 0).any():
        raise ValueError("poi.csv validation failed: visit_duration_minutes must be numeric and non-negative.")

    if trajectory_csv["user_id"].astype(str).str.strip().eq("").any():
        raise ValueError("trajectory.csv validation failed: user_id contains empty values.")

    if trajectory_csv["trajectory_id"].astype(str).str.strip().eq("").any():
        raise ValueError("trajectory.csv validation failed: trajectory_id contains empty values.")

    valid_poi_ids = set(poi_csv["poi_id"].tolist())
    invalid_poi_refs = ~trajectory_csv["poi_id"].isin(valid_poi_ids)
    if invalid_poi_refs.any():
        raise ValueError("trajectory.csv validation failed: poi_id contains references not present in poi.csv.")

    timestamps = pd.to_datetime(trajectory_csv["timestamp"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("trajectory.csv validation failed: timestamp contains invalid ISO 8601 values.")

    for trajectory_id, group in trajectory_csv.groupby("trajectory_id", sort=False):
        expected_order = list(range(1, len(group) + 1))
        actual_order = group["visit_order"].tolist()
        if actual_order != expected_order:
            raise ValueError(
                "trajectory.csv validation failed: visit_order is not contiguous "
                f"for trajectory {trajectory_id}."
            )
        group_timestamps = pd.to_datetime(group["timestamp"], errors="coerce")
        if not group_timestamps.is_monotonic_increasing:
            raise ValueError(
                "trajectory.csv validation failed: timestamps are not non-decreasing "
                f"for trajectory {trajectory_id}."
            )


def summarize_trajectory_lengths(trajectory_csv: pd.DataFrame) -> dict[str, Any]:
    lengths = trajectory_csv.groupby("trajectory_id").size()
    return {
        "length_eq_1": int((lengths == 1).sum()),
        "length_eq_2": int((lengths == 2).sum()),
        "length_ge_3": int((lengths >= 3).sum()),
        "mean_length": float(lengths.mean()),
        "median_length": float(lengths.median()),
        "max_length": int(lengths.max()),
    }


def write_cleaning_report(
    output_path: Path,
    *,
    config: CleanConfig,
    poi_raw: pd.DataFrame,
    visits_raw: pd.DataFrame,
    cost_raw: pd.DataFrame,
    poi_csv: pd.DataFrame,
    trajectory_csv: pd.DataFrame,
    poi_stats: dict[str, Any],
    visit_stats: dict[str, Any],
    duration_stats: dict[str, Any],
    trajectory_length_stats: dict[str, Any],
    cost_file_copied: bool,
) -> None:
    def display_path(path: Path) -> str:
        try:
            return str(path.relative_to(config.project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    lines = [
        "# Edinburgh Cleaning Report",
        "",
        "## Output Files",
        "",
        f"- `poi.csv`: `{display_path(config.output_dir / 'poi.csv')}`",
        f"- `trajectory.csv`: `{display_path(config.output_dir / 'trajectory.csv')}`",
        f"- `cleaning_report.md`: `{display_path(output_path)}`",
        f"- `costProfCat-EdinPOI-all.csv` copied: `{'yes' if cost_file_copied else 'no'}`",
        "",
        "## Input Statistics",
        "",
        f"- Raw POI count: {len(poi_raw)}",
        f"- Raw photo-level visit record count: {len(visits_raw)}",
        f"- Raw sequence count: {visits_raw['seqID'].nunique()}",
        "",
        "## Cleaning Statistics",
        "",
        f"- Removed invalid timestamp records: {visit_stats['removed_invalid_time_records']}",
        f"- Removed records with invalid user/POI/sequence IDs: {visit_stats['removed_invalid_identity_records']}",
        f"- Removed records with unmapped POIs: {visit_stats['removed_unmapped_poi_records']}",
        f"- Removed invalid-coordinate POIs: {poi_stats['invalid_coordinate_poi_count']}",
        f"- Photo-level records before aggregation: {visit_stats['clean_photo_record_count']}",
        f"- Visit-level records after aggregation: {len(trajectory_csv)}",
        f"- Trajectory count after aggregation: {trajectory_csv['trajectory_id'].nunique()}",
        f"- Final retained trajectory count: {trajectory_csv['trajectory_id'].nunique()}",
        f"- Final retained POI count: {len(poi_csv)}",
        "",
        "## Trajectory Length Distribution",
        "",
        f"- Length = 1 trajectories: {trajectory_length_stats['length_eq_1']}",
        f"- Length = 2 trajectories: {trajectory_length_stats['length_eq_2']}",
        f"- Length >= 3 trajectories: {trajectory_length_stats['length_ge_3']}",
        f"- Mean trajectory length: {trajectory_length_stats['mean_length']:.2f}",
        f"- Median trajectory length: {trajectory_length_stats['median_length']:.2f}",
        f"- Max trajectory length: {trajectory_length_stats['max_length']}",
        "",
        "## visit_duration_minutes Statistics",
        "",
        f"- Mean POI visit duration: {duration_stats['poi_duration_mean']:.2f}",
        f"- Median POI visit duration: {duration_stats['poi_duration_median']:.2f}",
        f"- POIs using the default duration ({int(config.default_visit_duration_minutes)}): {duration_stats['default_duration_poi_count']}",
        f"- Positive visit-duration samples used: {duration_stats['positive_visit_duration_sample_count']}",
        "",
        "## Missing-Field Notes",
        "",
        "- The source data does not include `visit_duration_minutes` directly.",
        "- The source data does not include `opening_hours`.",
        "- The source data provides only `theme`, without finer-grained subcategories.",
        "- The source visit log is photo-level data and was collapsed into visit-level sequences by merging only adjacent duplicate POIs.",
        "- Short trajectories were retained; no trajectories were removed only because of length.",
        "",
        "## Cost-Profit File Notes",
        "",
        f"- Source file: `{display_path(config.cost_path)}`",
        f"- Columns: {', '.join(cost_raw.columns.astype(str).tolist())}",
        f"- Row count: {len(cost_raw)}",
        f"- Required columns present: {'yes' if EXPECTED_COST_COLUMNS.issubset(set(cost_raw.columns)) else 'no'}",
        "- The cost-profit file was not merged into `poi.csv` or `trajectory.csv` during the main cleaning flow.",
        "- It can be used later for route scoring, cost estimation, or profit modeling extensions.",
        "",
        "## Validation Summary",
        "",
        "- `poi.csv`: unique `poi_id`, non-empty `poi_name` and `category`, valid coordinates, non-negative `visit_duration_minutes`.",
        "- `trajectory.csv`: all `poi_id` values exist in `poi.csv`, `visit_order` starts from 1 and is contiguous inside each trajectory, timestamps are non-decreasing, and required identifiers are non-empty.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def maybe_copy_cost_file(config: CleanConfig, cost_raw: pd.DataFrame) -> bool:
    if not EXPECTED_COST_COLUMNS.issubset(set(cost_raw.columns)):
        return False
    shutil.copy2(config.cost_path, config.output_dir / config.cost_filename)
    return True


def run_cleaning(config: CleanConfig) -> dict[str, Any]:
    for input_path in (config.poi_path, config.visits_path, config.cost_path):
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

    poi_raw = load_poi_file(config.poi_path)
    visits_raw = load_visits_file(config.visits_path)
    cost_raw = load_cost_profit_file(config.cost_path)

    poi_table, poi_stats = clean_poi_table(poi_raw)
    valid_poi_ids = set(poi_table["poi_id"].tolist())
    cleaned_visits, visit_stats = clean_visit_records(visits_raw, valid_poi_ids=valid_poi_ids)
    aggregated_visits = aggregate_consecutive_same_poi(cleaned_visits)
    poi_with_duration, duration_stats = estimate_poi_visit_duration(
        poi_table,
        aggregated_visits,
        default_duration_minutes=config.default_visit_duration_minutes,
    )

    poi_csv = build_poi_csv(poi_with_duration)
    trajectory_csv = build_trajectory_csv(aggregated_visits)
    validate_outputs(poi_csv, trajectory_csv)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    poi_output_path = config.output_dir / "poi.csv"
    trajectory_output_path = config.output_dir / "trajectory.csv"
    report_output_path = config.output_dir / "cleaning_report.md"

    poi_csv.to_csv(poi_output_path, index=False, encoding="utf-8")
    trajectory_csv.to_csv(trajectory_output_path, index=False, encoding="utf-8")
    cost_file_copied = maybe_copy_cost_file(config, cost_raw)
    trajectory_length_stats = summarize_trajectory_lengths(trajectory_csv)
    write_cleaning_report(
        report_output_path,
        config=config,
        poi_raw=poi_raw,
        visits_raw=visits_raw,
        cost_raw=cost_raw,
        poi_csv=poi_csv,
        trajectory_csv=trajectory_csv,
        poi_stats=poi_stats,
        visit_stats=visit_stats,
        duration_stats=duration_stats,
        trajectory_length_stats=trajectory_length_stats,
        cost_file_copied=cost_file_copied,
    )

    return {
        "poi_output_path": poi_output_path,
        "trajectory_output_path": trajectory_output_path,
        "report_output_path": report_output_path,
        "poi_count": int(len(poi_csv)),
        "trajectory_count": int(trajectory_csv["trajectory_id"].nunique()),
        "visit_count": int(len(trajectory_csv)),
        "trajectory_length_stats": trajectory_length_stats,
        "duration_stats": duration_stats,
        "visit_stats": visit_stats,
        "poi_stats": poi_stats,
        "cost_file_copied": cost_file_copied,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean Edinburgh tourism data for the route system.")
    parser.add_argument(
        "--input-dir",
        type=str,
        default="data2",
        help="Input directory that contains the Edinburgh source CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data_cleaned/edinburgh",
        help="Output directory for the cleaned CSV files and report.",
    )
    parser.add_argument(
        "--poi-file",
        type=str,
        default="POI-Edin.csv",
        help="POI source filename inside the input directory.",
    )
    parser.add_argument(
        "--visits-file",
        type=str,
        default="userVisits-Edin.csv",
        help="Visit source filename inside the input directory.",
    )
    parser.add_argument(
        "--cost-file",
        type=str,
        default="costProfCat-EdinPOI-all.csv",
        help="Cost-profit source filename inside the input directory.",
    )
    return parser.parse_args()


def resolve_path(project_root: Path, user_path: str) -> Path:
    path = Path(user_path)
    if path.is_absolute():
        return path
    return project_root / path


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    config = CleanConfig(
        project_root=project_root,
        input_dir=resolve_path(project_root, args.input_dir),
        output_dir=resolve_path(project_root, args.output_dir),
        poi_filename=args.poi_file,
        visits_filename=args.visits_file,
        cost_filename=args.cost_file,
    )
    stats = run_cleaning(config)
    print("Edinburgh data cleaning completed.")
    print(f"POI count: {stats['poi_count']}")
    print(f"Trajectory count: {stats['trajectory_count']}")
    print(f"Visit count: {stats['visit_count']}")
    print(f"poi.csv: {stats['poi_output_path']}")
    print(f"trajectory.csv: {stats['trajectory_output_path']}")
    print(f"cleaning_report.md: {stats['report_output_path']}")


if __name__ == "__main__":
    main()
