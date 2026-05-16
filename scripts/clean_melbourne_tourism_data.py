"""Clean Melbourne source data into project-ready CSV files.

The cleaning flow follows `优化.md`:
1. Standardize raw POI and visit tables.
2. Keep only tourism-related POIs defined by fixed local rules.
3. Re-classify kept POIs into a unified category system.
4. Rebuild trajectories by skipping removed POIs and collapsing adjacent duplicates.
5. Estimate POI-level visit durations from visit blocks.
6. Write reports plus publish `poi.csv` and `trajectory.csv` to `data/`.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


CITY_NAME = "Melbourne"
CITY_SLUG = "melbourne_tourism"
CITY_PREFIX = "MELB"
DEFAULT_VISIT_DURATION_MINUTES = 60.0
MIN_VALID_TIMESTAMP = pd.Timestamp("2000-01-01", tz="UTC")
MAX_VALID_TIMESTAMP = pd.Timestamp("2035-01-01", tz="UTC")
REMOVED_BLOCK_SENTINEL = "__REMOVED__"


def normalize_text(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def normalize_name_set(values: set[str]) -> set[str]:
    return {normalize_text(value) for value in values}


def normalize_name_map(values: dict[str, str]) -> dict[str, str]:
    return {normalize_text(key): value for key, value in values.items()}


def parse_numeric_series(values: pd.Series) -> pd.Series:
    cleaned = values.astype(str).str.strip().str.rstrip(",")
    return pd.to_numeric(cleaned, errors="coerce")


EXPLICIT_KEEP_NAMES = normalize_name_set(
    {
        "Melbourne International Karting Complex",
        "Harbour Town",
        "Railway Good Shed No 2",
        "State Library Victoria",
        "NGV International",
        "Shrine of Remembrance",
        "Melbourne Town Hall",
        "Old Treasury Building",
        "Former Royal Mint",
        "Parliament House",
        "Sidney Myer Music Bowl",
        "Melbourne Theatre Company",
        "Elisabeth Murdoch Hall",
        "Melbourne Recital Centre",
        "Conservatory",
        "Queen Victoria Market",
        "Southgate Arts and Leisure Precinct",
        "Melbourne Central",
        "Eureka Tower",
        "QV Village",
        "Waterfront City",
        "Melbourne Cricket Ground (MCG)",
        "AAMI Park",
        "Rod Laver Arena",
        "Melbourne Park",
        "Margaret Court Arena",
        "Hisense Arena",
        "Etihad Stadium",
        "Flemington Racecourse",
        "State Netball Hockey Centre",
        "Carlton Football Club",
        "Visy Park",
        "North Melbourne Recreation Centre (Aquatic)",
        "City Baths",
        "Westpac Centre",
        "Royal Park Golf Course",
        "Melbourne International Shooting Club",
        "North Melbourne Football Club",
        "North Melbourne Recreation Centre (Gymnasium)",
        "Government House",
        "Council House 2 (CH2)",
        "ANZ 'Gothic' Bank",
        "Treasury Reserve",
        "Freshwater Place",
        "DFO South Wharf",
        "Myer",
        "David Jones",
        "Melbourne Exhibition Centre",
        "Melbourne Convention Centre",
        "Central Pier",
        "Dallas Brooks Centre",
    }
)

EXPLICIT_REMOVE_NAMES = normalize_name_set(
    {
        "Bishopscourt",
        "Supreme Court",
        "Victoria Police",
        "Metropolitan Fire Brigade (MFB)",
        "Commonwealth Law Courts",
        "County Court Melbourne",
        "Melbourne Childrens Court",
        "Melbourne Magistrates Court",
        "Australian Red Cross",
        "Australian Broadcasting Corporation (ABC)",
        "SBS (Special Broadcasting Service)",
        "Coronial Services Centre of Victoria",
        "Donor Tissue Bank of Victoria",
        "State Coroners Office",
        "Victorian Insitute of Forensic Medicine",
        "Kraft",
        "Melbourne Wholesale Fish Market",
        "Melbourne Wholesale Fruit, Vegetable & Flower Market",
        "Central City Studios",
        "Channel 7 - Melbourne Broadcast Centre",
        "Mercy Private Hospital",
        "Epworth Freemasons Hospital",
        "Epworth Freemasons Hospital : Medical Centre",
        "Melbourne Private Hospital",
        "Alfred Hospital",
        "Peter Maccallum Cancer Institute",
        "Royal Childrens Hospital",
        "Royal Dental Hospital",
        "Royal Melbourne Hospital",
        "Royal Womens Hospital",
        "The Royal Victorian Eye & Ear Hospital",
        "Carlton Gardens Primary School",
        "Carlton Primary School",
        "Kensington Primary School",
        "North Melbourne Primary School",
        "Melbourne Girls Grammar School",
        "Wesley College",
        "Melbourne Grammar School",
        "University High School",
        "Kangan Batman Tafe",
    }
)

KEEP_SUBTHEMES = {
    "Art Gallery/Museum",
    "Aquarium",
    "Bridge",
    "Casino",
    "Church",
    "Cinema",
    "Department Store",
    "Function/Conference/Exhibition Centre",
    "Gymnasium/Health Club",
    "Indoor Recreation Facility",
    "Informal Outdoor Facility (Park/Garden/Reserve)",
    "Library",
    "Major Sports & Recreation Facility",
    "Marina",
    "Observation Tower/Wheel",
    "Outdoor Recreation Facility (Zoo, Golf Course)",
    "Private Sports Club/Facility",
    "Railway Station",
    "Retail",
    "Synagogue",
    "Tertiary (University)",
    "Theatre Live",
    "Transport Terminal",
    "Visitor Centre",
}

REMOVE_SUBTHEMES = {
    "Cemetery",
    "Current Construction Site",
    "Current Construction Site - Commercial",
    "Dwelling (House)",
    "Film & RV Studio",
    "Fire Station",
    "Further Education",
    "Government Building",
    "Hostel",
    "Industrial (Manufacturing)",
    "Medical Services",
    "Office",
    "Police Station",
    "Primary Schools",
    "Private Hospital",
    "Public Hospital",
    "School - Primary and Secondary Education",
    "Secondary Schools",
    "Store Yard",
    "Vacant Land - Undeveloped Site",
}

KEEP_PUBLIC_BUILDING_NAMES = normalize_name_set(
    {
        "Conservatory",
        "Elisabeth Murdoch Hall",
        "Melbourne Recital Centre",
        "Melbourne Theatre Company",
        "Melbourne Town Hall",
        "Melbourne Visitor Booth",
        "Melbourne Visitor Centre",
        "NGV International",
        "Shrine of Remembrance",
        "Sidney Myer Music Bowl",
        "State Library Victoria",
    }
)

KEEP_MIXED_USE_NAMES = normalize_name_set(
    {
        "ANZ 'Gothic' Bank",
        "Council House 2 (CH2)",
        "DFO South Wharf",
        "Eureka Tower",
        "Freshwater Place",
        "Melbourne Central",
        "QV Village",
        "Southgate Arts and Leisure Precinct",
        "Treasury Reserve",
        "Waterfront City",
    }
)

KEEP_OFFICE_NAMES = normalize_name_set(
    {
        "Former Royal Mint",
        "North Melbourne Football Club",
        "Old Treasury Building",
        "Parliament House",
    }
)

KEEP_CONSTRUCTION_REVIEW_NAMES = normalize_name_set(
    {
        "Harbour Town",
        "Melbourne International Karting Complex",
        "Railway Good Shed No 2",
    }
)

MANUAL_CATEGORY_MAP = normalize_name_map(
    {
        "State Library Victoria": "civic_landmark",
        "The Melbourne Athenaeum Library": "civic_landmark",
        "Melbourne Visitor Booth": "civic_landmark",
        "Melbourne Visitor Centre": "civic_landmark",
        "Federation Square": "civic_landmark",
        "Council House 2 (CH2)": "civic_landmark",
        "Shrine of Remembrance": "historical_building",
        "Melbourne Town Hall": "historical_building",
        "Old Treasury Building": "historical_building",
        "Former Royal Mint": "historical_building",
        "Parliament House": "historical_building",
        "Government House": "historical_building",
        "ANZ 'Gothic' Bank": "historical_building",
        "Treasury Reserve": "historical_building",
        "Cooks' Cottage": "historical_building",
        "Old Melbourne Gaol Crime & Justice Experience": "historical_building",
        "Royal Exhibition Building": "historical_building",
        "Sinclair's Cottage": "historical_building",
        "Polly Woodside": "historical_building",
        "Railway Good Shed No 2": "historical_building",
        "NGV International": "museum_gallery",
        "The Ian Potter Centre: NGV Australia": "museum_gallery",
        "Australian Centre For The Moving Image (ACMI)": "museum_gallery",
        "Australian Centre for Contemporary Art": "museum_gallery",
        "Fire Services Museum Victoria": "museum_gallery",
        "Victoria Police Museum": "museum_gallery",
        "Sidney Myer Music Bowl": "performance_venue",
        "Melbourne Theatre Company": "performance_venue",
        "Elisabeth Murdoch Hall": "performance_venue",
        "Melbourne Recital Centre": "performance_venue",
        "Conservatory": "performance_venue",
        "Victorian Arts Centre": "performance_venue",
        "Hamer Hall": "performance_venue",
        "MTC Theatre": "performance_venue",
        "State Theatre": "performance_venue",
        "FairFax Studio": "performance_venue",
        "Forum Theatre": "performance_venue",
        "Princess Theatre": "performance_venue",
        "Regent Theatre": "performance_venue",
        "Eureka Tower": "observation_landmark",
        "Eureka Skydeck 88": "observation_landmark",
        "Melbourne Star Observation Wheel": "observation_landmark",
        "Queen Victoria Market": "market_shopping",
        "Harbour Town": "market_shopping",
        "DFO South Wharf": "market_shopping",
        "Myer": "market_shopping",
        "David Jones": "market_shopping",
        "Southgate Arts and Leisure Precinct": "commercial_landmark",
        "Melbourne Central": "commercial_landmark",
        "QV Village": "commercial_landmark",
        "Waterfront City": "commercial_landmark",
        "Freshwater Place": "commercial_landmark",
        "AAMI Park": "sport",
        "Carlton Football Club": "sport",
        "City Baths": "sport",
        "Etihad Stadium": "sport",
        "Flemington Racecourse": "sport",
        "Hisense Arena": "sport",
        "Icehouse": "sport",
        "Margaret Court Arena": "sport",
        "Melbourne Cricket Ground (MCG)": "sport",
        "Melbourne International Karting Complex": "sport",
        "Melbourne International Shooting Club": "sport",
        "Melbourne Park": "sport",
        "North Melbourne Football Club": "sport",
        "North Melbourne Recreation Centre (Aquatic)": "sport",
        "North Melbourne Recreation Centre (Gymnasium)": "sport",
        "North Melbourne Recreation Reserve": "sport",
        "Richmond Football Club": "sport",
        "Riverslide Skate Park": "sport",
        "Rod Laver Arena": "sport",
        "Royal Park Golf Course": "sport",
        "State Netball Hockey Centre": "sport",
        "Visy Park": "sport",
        "Westpac Centre": "sport",
        "Melbourne Aquarium": "entertainment",
        "Crown Entertainment Complex": "entertainment",
        "IMAX Melbourne": "entertainment",
        "Melbourne Zoo": "entertainment",
        "Artplay": "entertainment",
        "Melbourne Convention Centre": "convention_exhibition",
        "Melbourne Exhibition Centre": "convention_exhibition",
        "Central Pier": "waterfront",
        "Dallas Brooks Centre": "convention_exhibition",
        "Melbourne Showgrounds": "convention_exhibition",
        "New Quay": "waterfront",
        "New Quay Marina": "waterfront",
        "Webb Bridge": "waterfront",
        "Sandridge Rail Bridge": "waterfront",
        "Port of Melbourne": "transport",
        "Melbourne Central Railway Station": "transport",
    }
)

SUBTHEME_CATEGORY_MAP = {
    "Art Gallery/Museum": "museum_gallery",
    "Aquarium": "entertainment",
    "Bridge": "waterfront",
    "Casino": "entertainment",
    "Church": "religious_heritage",
    "Cinema": "entertainment",
    "Department Store": "market_shopping",
    "Function/Conference/Exhibition Centre": "convention_exhibition",
    "Gymnasium/Health Club": "sport",
    "Indoor Recreation Facility": "leisure_recreation",
    "Informal Outdoor Facility (Park/Garden/Reserve)": "park_garden",
    "Library": "civic_landmark",
    "Major Sports & Recreation Facility": "sport",
    "Marina": "waterfront",
    "Observation Tower/Wheel": "observation_landmark",
    "Outdoor Recreation Facility (Zoo, Golf Course)": "leisure_recreation",
    "Private Sports Club/Facility": "sport",
    "Railway Station": "transport",
    "Retail": "market_shopping",
    "Synagogue": "religious_heritage",
    "Tertiary (University)": "university",
    "Theatre Live": "performance_venue",
    "Transport Terminal": "transport",
    "Visitor Centre": "civic_landmark",
}

NAME_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("railway station", "transport terminal"), "transport"),
    (("visitor centre", "visitor center", "visitor booth"), "civic_landmark"),
    (("cathedral", "church", "synagogue"), "religious_heritage"),
    (("theatre", "music bowl", "recital centre", "playhouse", "arts centre"), "performance_venue"),
    (("museum", "gallery"), "museum_gallery"),
    (("stadium", "arena", "cricket ground", "golf course", "shooting club", "football club"), "sport"),
    (("market",), "market_shopping"),
    (("university",), "university"),
]


@dataclass(frozen=True)
class CleanConfig:
    project_root: Path
    input_dir: Path
    output_dir: Path
    publish_dir: Path
    poi_filename: str = "POI-Melb.csv"
    visits_filename: str = "userVisits-Melb-allPOI.csv"
    default_visit_duration_minutes: float = DEFAULT_VISIT_DURATION_MINUTES

    @property
    def poi_path(self) -> Path:
        return self.input_dir / self.poi_filename

    @property
    def visits_path(self) -> Path:
        return self.input_dir / self.visits_filename


def resolve_path(project_root: Path, user_path: str) -> Path:
    path = Path(user_path)
    if path.is_absolute():
        return path
    return project_root / path


def normalize_poi_ids(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("Int64")
    return numeric.map(lambda value: f"{CITY_PREFIX}_P{int(value):03d}" if pd.notna(value) else pd.NA)


def normalize_trajectory_ids(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("Int64")
    return numeric.map(lambda value: f"{CITY_PREFIX}_T{int(value):06d}" if pd.notna(value) else pd.NA)


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    normalized_columns = []
    for column in df.columns:
        column_name = str(column).strip()
        if column_name == "long,":
            column_name = "long"
        normalized_columns.append(column_name)
    df.columns = normalized_columns
    return df


def clean_poi_table(poi_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    poi = poi_raw.rename(
        columns={
            "poiID": "raw_poi_id",
            "theme": "theme",
            "subTheme": "sub_theme",
            "poiName": "poi_name",
            "lat": "latitude",
            "long": "longitude",
        }
    ).copy()

    required = {"raw_poi_id", "theme", "sub_theme", "poi_name", "latitude", "longitude"}
    missing = required - set(poi.columns)
    if missing:
        raise ValueError(f"POI file is missing required columns: {', '.join(sorted(missing))}")

    poi["raw_poi_id_num"] = parse_numeric_series(poi["raw_poi_id"])
    poi["theme"] = poi["theme"].astype(str).str.strip()
    poi["sub_theme"] = poi["sub_theme"].astype(str).str.strip()
    poi["poi_name"] = poi["poi_name"].astype(str).str.strip()
    poi["latitude"] = parse_numeric_series(poi["latitude"])
    poi["longitude"] = parse_numeric_series(poi["longitude"])
    poi["name_key"] = poi["poi_name"].map(normalize_text)

    invalid_mask = (
        poi["raw_poi_id_num"].isna()
        | poi["poi_name"].eq("")
        | poi["theme"].eq("")
        | poi["sub_theme"].eq("")
        | poi["latitude"].isna()
        | poi["longitude"].isna()
        | (poi["latitude"] < -90)
        | (poi["latitude"] > 90)
        | (poi["longitude"] < -180)
        | (poi["longitude"] > 180)
    )
    invalid_count = int(invalid_mask.sum())
    poi = poi.loc[~invalid_mask].copy()
    poi["poi_id"] = normalize_poi_ids(poi["raw_poi_id_num"])
    poi["opening_hours"] = ""

    if poi["poi_id"].duplicated().any():
        duplicates = poi.loc[poi["poi_id"].duplicated(), "poi_id"].tolist()
        raise ValueError(f"Duplicate standardized POI IDs detected: {duplicates[:5]}")

    poi = poi.sort_values("raw_poi_id_num").reset_index(drop=True)
    return (
        poi[
            [
                "raw_poi_id_num",
                "poi_id",
                "theme",
                "sub_theme",
                "poi_name",
                "name_key",
                "latitude",
                "longitude",
                "opening_hours",
            ]
        ],
        {
            "raw_poi_count": int(len(poi_raw)),
            "invalid_or_incomplete_poi_count": invalid_count,
            "clean_poi_count": int(len(poi)),
        },
    )


def build_keep_remove_rules() -> dict[str, Any]:
    return {
        "explicit_keep_names": EXPLICIT_KEEP_NAMES,
        "explicit_remove_names": EXPLICIT_REMOVE_NAMES,
        "keep_public_building_names": KEEP_PUBLIC_BUILDING_NAMES,
        "keep_mixed_use_names": KEEP_MIXED_USE_NAMES,
        "keep_office_names": KEEP_OFFICE_NAMES,
        "keep_construction_review_names": KEEP_CONSTRUCTION_REVIEW_NAMES,
    }


def decide_poi_retention(row: pd.Series, rules: dict[str, Any]) -> tuple[bool, str]:
    name_key = row["name_key"]
    theme = row["theme"]
    sub_theme = row["sub_theme"]

    if name_key in rules["explicit_keep_names"]:
        return True, "explicit_keep_name"

    if name_key in rules["explicit_remove_names"]:
        return False, "explicit_remove_name"

    if theme == "Health Services":
        return False, "remove_health_services_theme"

    if sub_theme == "Public Buildings":
        if name_key in rules["keep_public_building_names"]:
            return True, "keep_public_building_name"
        return False, "remove_public_building_not_in_keep_list"

    if sub_theme in {"Retail/Office", "Retail/Office/Carpark", "Retail/Office/Residential/Carpark", "Retail/Residential"}:
        if name_key in rules["keep_mixed_use_names"]:
            return True, "keep_manual_mixed_use_name"
        return False, "remove_mixed_use_not_in_keep_list"

    if sub_theme == "Office":
        if name_key in rules["keep_office_names"]:
            return True, "keep_manual_office_name"
        return False, "remove_office_not_in_keep_list"

    if sub_theme in {
        "Current Construction Site",
        "Current Construction Site - Commercial",
        "Dwelling (House)",
        "Hostel",
        "Store Yard",
        "Vacant Land - Undeveloped Site",
    }:
        if name_key in rules["keep_construction_review_names"]:
            return True, "keep_manual_review_name"
        return False, f"remove_subtheme:{sub_theme}"

    if sub_theme in REMOVE_SUBTHEMES:
        return False, f"remove_subtheme:{sub_theme}"

    if sub_theme in KEEP_SUBTHEMES:
        return True, f"keep_subtheme:{sub_theme}"

    if theme in {"Industrial", "Warehouse/Store", "Specialist Residential Accommodation"}:
        return False, f"remove_theme:{theme}"

    return False, "remove_not_in_tourism_scope"


def filter_pois(poi_table: pd.DataFrame, rules: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    decisions = poi_table.apply(lambda row: decide_poi_retention(row, rules), axis=1, result_type="expand")
    decisions.columns = ["is_kept", "retention_reason"]
    annotated = pd.concat([poi_table, decisions], axis=1)

    kept = annotated.loc[annotated["is_kept"]].copy()
    removed = annotated.loc[~annotated["is_kept"]].copy()
    return kept, removed


def classify_poi_category(row: pd.Series) -> tuple[str, str]:
    name_key = row["name_key"]
    poi_name = row["poi_name"]
    sub_theme = row["sub_theme"]

    if name_key in MANUAL_CATEGORY_MAP:
        return MANUAL_CATEGORY_MAP[name_key], "manual_name_mapping"

    name_key_text = normalize_text(poi_name)
    for keywords, category in NAME_KEYWORD_RULES:
        if any(keyword in name_key_text for keyword in keywords):
            return category, "name_keyword_rule"

    if sub_theme in SUBTHEME_CATEGORY_MAP:
        return SUBTHEME_CATEGORY_MAP[sub_theme], "subtheme_rule"

    raise ValueError(
        "Unable to classify kept POI with fixed rules: "
        f"{poi_name} (theme={row['theme']}, subTheme={sub_theme})"
    )


def classify_poi_categories(kept_pois: pd.DataFrame) -> pd.DataFrame:
    categories = kept_pois.apply(lambda row: classify_poi_category(row), axis=1, result_type="expand")
    categories.columns = ["category", "category_source"]
    classified = pd.concat([kept_pois.reset_index(drop=True), categories.reset_index(drop=True)], axis=1)
    return classified


def clean_visit_records(
    visits_raw: pd.DataFrame,
    valid_raw_poi_ids: set[int],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    visits = visits_raw.rename(
        columns={
            "photoID": "photo_id",
            "userID": "user_id",
            "dateTaken": "timestamp_unix",
            "poiID": "raw_poi_id",
            "poiTheme": "poi_theme",
            "poiFreq": "poi_freq",
            "seqID": "raw_trajectory_id",
        }
    ).copy()

    required = {"photo_id", "user_id", "timestamp_unix", "raw_poi_id", "raw_trajectory_id"}
    missing = required - set(visits.columns)
    if missing:
        raise ValueError(f"Visits file is missing required columns: {', '.join(sorted(missing))}")

    visits["source_row"] = range(len(visits))
    visits["user_id"] = visits["user_id"].astype(str).str.strip()
    visits["raw_poi_id_num"] = parse_numeric_series(visits["raw_poi_id"]).astype("Int64")
    visits["raw_trajectory_id_num"] = parse_numeric_series(visits["raw_trajectory_id"]).astype("Int64")
    visits["timestamp_unix_num"] = parse_numeric_series(visits["timestamp_unix"])
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

    unknown_poi_mask = ~visits["raw_poi_id_num"].isin(valid_raw_poi_ids)
    removed_unknown_source_poi_records = int(unknown_poi_mask.sum())
    visits = visits.loc[~unknown_poi_mask].copy()

    visits["trajectory_id"] = normalize_trajectory_ids(visits["raw_trajectory_id_num"])
    visits["full_poi_id"] = normalize_poi_ids(visits["raw_poi_id_num"])
    visits = visits.sort_values(["raw_trajectory_id_num", "timestamp_dt", "source_row"]).reset_index(drop=True)

    users_per_trajectory = visits.groupby("trajectory_id")["user_id"].nunique()
    multi_user_trajectories = users_per_trajectory[users_per_trajectory > 1]
    if not multi_user_trajectories.empty:
        sample = ", ".join(multi_user_trajectories.index[:5])
        raise ValueError(f"Found trajectories assigned to multiple users: {sample}")

    return (
        visits[
            [
                "photo_id",
                "user_id",
                "timestamp_dt",
                "raw_poi_id_num",
                "raw_trajectory_id_num",
                "trajectory_id",
                "full_poi_id",
                "source_row",
            ]
        ],
        {
            "raw_photo_record_count": int(len(visits_raw)),
            "removed_invalid_time_records": removed_invalid_time_records,
            "removed_invalid_identity_records": removed_invalid_identity_records,
            "removed_unknown_source_poi_records": removed_unknown_source_poi_records,
            "clean_photo_record_count": int(len(visits)),
            "clean_trajectory_count": int(visits["trajectory_id"].nunique()),
            "clean_user_count": int(visits["user_id"].nunique()),
        },
    )


def compress_consecutive_values(values: list[str]) -> list[str]:
    compressed: list[str] = []
    for value in values:
        if not compressed or compressed[-1] != value:
            compressed.append(value)
    return compressed


def analyze_skip_blocks(filtered_poi_sequence: list[str | None]) -> tuple[bool, bool, int]:
    blocks: list[str] = []
    for poi_id in filtered_poi_sequence:
        block_value = poi_id if poi_id is not None else REMOVED_BLOCK_SENTINEL
        if not blocks or blocks[-1] != block_value:
            blocks.append(block_value)

    skip_affected = False
    skip_duplicate = False
    skip_duplicate_events = 0
    for index in range(1, len(blocks) - 1):
        if blocks[index] != REMOVED_BLOCK_SENTINEL:
            continue
        left = blocks[index - 1]
        right = blocks[index + 1]
        if left == REMOVED_BLOCK_SENTINEL or right == REMOVED_BLOCK_SENTINEL:
            continue
        skip_affected = True
        if left == right:
            skip_duplicate = True
            skip_duplicate_events += 1

    return skip_affected, skip_duplicate, skip_duplicate_events


def rebuild_trajectories_with_skips(
    clean_visits: pd.DataFrame,
    kept_pois: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    kept_lookup = dict(zip(kept_pois["raw_poi_id_num"], kept_pois["poi_id"]))
    aggregated_rows: list[dict[str, Any]] = []
    trajectory_summaries: list[dict[str, Any]] = []

    retained_photo_record_count = 0
    removed_filtered_out_poi_records = 0
    adjacent_duplicate_merge_count = 0
    skip_duplicate_event_count = 0

    for trajectory_id, group in clean_visits.groupby("trajectory_id", sort=False):
        group = group.sort_values(["timestamp_dt", "source_row"]).copy()
        user_id = str(group["user_id"].iloc[0])
        filtered_poi_ids = [kept_lookup.get(raw_poi_id, None) for raw_poi_id in group["raw_poi_id_num"].tolist()]
        original_visit_count = len(compress_consecutive_values(group["full_poi_id"].astype(str).tolist()))
        skip_affected, skip_duplicate, skip_duplicate_events = analyze_skip_blocks(filtered_poi_ids)
        skip_duplicate_event_count += skip_duplicate_events

        group["poi_id"] = group["raw_poi_id_num"].map(kept_lookup)
        kept_group = group.loc[group["poi_id"].notna()].copy()
        removed_records = int(len(group) - len(kept_group))
        retained_photo_record_count += int(len(kept_group))
        removed_filtered_out_poi_records += removed_records

        final_visit_count = 0
        if not kept_group.empty:
            kept_group["starts_new_visit"] = kept_group["poi_id"].ne(kept_group["poi_id"].shift(1))
            kept_group["visit_block"] = kept_group["starts_new_visit"].cumsum()
            aggregated = (
                kept_group.groupby("visit_block", sort=False)
                .agg(
                    user_id=("user_id", "first"),
                    trajectory_id=("trajectory_id", "first"),
                    poi_id=("poi_id", "first"),
                    arrival_time=("timestamp_dt", "min"),
                    departure_time=("timestamp_dt", "max"),
                    photo_count=("photo_id", "count"),
                )
                .reset_index(drop=True)
            )
            aggregated["visit_order"] = range(1, len(aggregated) + 1)
            aggregated["visit_duration_minutes"] = (
                aggregated["departure_time"] - aggregated["arrival_time"]
            ).dt.total_seconds() / 60.0
            aggregated["timestamp"] = aggregated["arrival_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            final_visit_count = int(len(aggregated))
            adjacent_duplicate_merge_count += int(len(kept_group) - len(aggregated))

            for _, visit_row in aggregated.iterrows():
                aggregated_rows.append(
                    {
                        "user_id": str(visit_row["user_id"]),
                        "trajectory_id": str(visit_row["trajectory_id"]),
                        "visit_order": int(visit_row["visit_order"]),
                        "poi_id": str(visit_row["poi_id"]),
                        "arrival_time": visit_row["arrival_time"],
                        "departure_time": visit_row["departure_time"],
                        "timestamp": str(visit_row["timestamp"]),
                        "visit_duration_minutes": float(visit_row["visit_duration_minutes"]),
                        "photo_count": int(visit_row["photo_count"]),
                    }
                )

        trajectory_summaries.append(
            {
                "trajectory_id": trajectory_id,
                "user_id": user_id,
                "cleaned_photo_count": int(len(group)),
                "original_visit_count": int(original_visit_count),
                "retained_photo_count": int(len(kept_group)),
                "removed_filtered_poi_count": removed_records,
                "final_visit_count": final_visit_count,
                "skip_affected": skip_affected,
                "skip_duplicate": skip_duplicate,
                "skip_duplicate_events": int(skip_duplicate_events),
            }
        )

    aggregated_visits = pd.DataFrame(aggregated_rows)
    trajectory_summary = pd.DataFrame(trajectory_summaries)

    if aggregated_visits.empty:
        raise ValueError("No visit-level trajectories remain after Melbourne POI filtering.")

    return (
        aggregated_visits,
        trajectory_summary,
        {
            "raw_trajectory_count": int(trajectory_summary["trajectory_id"].nunique()),
            "retained_trajectory_count": int((trajectory_summary["final_visit_count"] > 0).sum()),
            "dropped_trajectory_count": int((trajectory_summary["final_visit_count"] == 0).sum()),
            "retained_photo_record_count": int(retained_photo_record_count),
            "removed_filtered_out_poi_records": int(removed_filtered_out_poi_records),
            "final_visit_record_count": int(len(aggregated_visits)),
            "skip_affected_trajectory_count": int(trajectory_summary["skip_affected"].sum()),
            "skip_duplicate_trajectory_count": int(trajectory_summary["skip_duplicate"].sum()),
            "skip_duplicate_event_count": int(skip_duplicate_event_count),
            "adjacent_duplicate_merge_count": int(adjacent_duplicate_merge_count),
        },
    )


def estimate_poi_durations(
    kept_pois: pd.DataFrame,
    aggregated_visits: pd.DataFrame,
    default_duration_minutes: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    positive_visits = aggregated_visits.loc[
        aggregated_visits["visit_duration_minutes"] > 0,
        ["poi_id", "visit_duration_minutes"],
    ].copy()
    poi_duration_medians = positive_visits.groupby("poi_id")["visit_duration_minutes"].median()

    poi_with_durations = kept_pois.copy()
    poi_with_durations["visit_duration_minutes"] = poi_with_durations["poi_id"].map(poi_duration_medians)
    default_mask = poi_with_durations["visit_duration_minutes"].isna()
    poi_with_durations["visit_duration_minutes"] = (
        poi_with_durations["visit_duration_minutes"].fillna(default_duration_minutes).round(2)
    )

    return (
        poi_with_durations,
        {
            "positive_visit_duration_sample_count": int(len(positive_visits)),
            "default_duration_poi_count": int(default_mask.sum()),
            "poi_duration_mean": float(poi_with_durations["visit_duration_minutes"].mean()),
            "poi_duration_median": float(poi_with_durations["visit_duration_minutes"].median()),
        },
    )


def build_output_poi_csv(poi_table: pd.DataFrame) -> pd.DataFrame:
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


def build_output_trajectory_csv(aggregated_visits: pd.DataFrame) -> pd.DataFrame:
    return aggregated_visits[["user_id", "trajectory_id", "visit_order", "poi_id", "timestamp"]].copy()


def validate_outputs(poi_csv: pd.DataFrame, trajectory_csv: pd.DataFrame) -> None:
    if poi_csv["poi_id"].duplicated().any():
        raise ValueError("poi.csv validation failed: poi_id must be unique.")

    if poi_csv["poi_name"].astype(str).str.strip().eq("").any():
        raise ValueError("poi.csv validation failed: poi_name contains empty values.")

    if poi_csv["category"].astype(str).str.strip().eq("").any():
        raise ValueError("poi.csv validation failed: category contains empty values.")

    latitudes = pd.to_numeric(poi_csv["latitude"], errors="coerce")
    longitudes = pd.to_numeric(poi_csv["longitude"], errors="coerce")
    invalid_coordinates = (
        latitudes.isna()
        | longitudes.isna()
        | (latitudes < -90)
        | (latitudes > 90)
        | (longitudes < -180)
        | (longitudes > 180)
    )
    if invalid_coordinates.any():
        raise ValueError("poi.csv validation failed: invalid latitude/longitude values detected.")

    durations = pd.to_numeric(poi_csv["visit_duration_minutes"], errors="coerce")
    if durations.isna().any() or (durations < 0).any():
        raise ValueError("poi.csv validation failed: visit_duration_minutes must be numeric and non-negative.")

    if trajectory_csv["user_id"].astype(str).str.strip().eq("").any():
        raise ValueError("trajectory.csv validation failed: user_id contains empty values.")

    if trajectory_csv["trajectory_id"].astype(str).str.strip().eq("").any():
        raise ValueError("trajectory.csv validation failed: trajectory_id contains empty values.")

    valid_poi_ids = set(poi_csv["poi_id"].tolist())
    if (~trajectory_csv["poi_id"].isin(valid_poi_ids)).any():
        raise ValueError("trajectory.csv validation failed: poi_id contains references not present in poi.csv.")

    timestamps = pd.to_datetime(trajectory_csv["timestamp"], errors="coerce", utc=True)
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
        group_timestamps = pd.to_datetime(group["timestamp"], errors="coerce", utc=True)
        if not group_timestamps.is_monotonic_increasing:
            raise ValueError(
                "trajectory.csv validation failed: timestamps are not non-decreasing "
                f"for trajectory {trajectory_id}."
            )


def summarize_length_distribution(lengths: pd.Series) -> dict[str, Any]:
    if lengths.empty:
        return {
            "length_eq_1": 0,
            "length_eq_2": 0,
            "length_ge_3": 0,
            "mean_length": 0.0,
            "median_length": 0.0,
            "max_length": 0,
        }

    return {
        "length_eq_1": int((lengths == 1).sum()),
        "length_eq_2": int((lengths == 2).sum()),
        "length_ge_3": int((lengths >= 3).sum()),
        "mean_length": float(lengths.mean()),
        "median_length": float(lengths.median()),
        "max_length": int(lengths.max()),
    }


def summarize_length_change(length_change: pd.Series) -> dict[str, int]:
    return {
        "unchanged": int((length_change == 0).sum()),
        "reduced_by_1": int((length_change == -1).sum()),
        "reduced_by_2": int((length_change == -2).sum()),
        "reduced_by_3_or_more": int((length_change <= -3).sum()),
    }


def write_removed_poi_list(output_path: Path, removed_pois: pd.DataFrame) -> None:
    report = removed_pois.rename(
        columns={
            "raw_poi_id_num": "poiID",
            "poi_name": "poiName",
            "theme": "theme",
            "sub_theme": "subTheme",
            "retention_reason": "remove_reason",
        }
    )[
        ["poiID", "poiName", "theme", "subTheme", "remove_reason"]
    ].copy()
    report.to_csv(output_path, index=False, encoding="utf-8")


def write_category_mapping_report(output_path: Path, classified_pois: pd.DataFrame) -> None:
    report = classified_pois.rename(columns={"sub_theme": "subTheme"})[
        ["poi_id", "poi_name", "theme", "subTheme", "category", "category_source"]
    ].copy()
    report = report.rename(columns={"category": "final_category"})
    report.to_csv(output_path, index=False, encoding="utf-8")


def write_trajectory_rebuild_report(
    output_path: Path,
    trajectory_summary: pd.DataFrame,
    rebuild_stats: dict[str, Any],
) -> None:
    retained_summary = trajectory_summary.loc[trajectory_summary["final_visit_count"] > 0].copy()
    final_length_stats = summarize_length_distribution(retained_summary["final_visit_count"])
    original_length_stats = summarize_length_distribution(trajectory_summary["original_visit_count"])
    length_change_stats = summarize_length_change(
        retained_summary["final_visit_count"] - retained_summary["original_visit_count"]
    )

    lines = [
        f"# {CITY_NAME} Trajectory Rebuild Report",
        "",
        "## Rules",
        "",
        "- Raw photo records were sorted by timestamp within each `seqID`.",
        "- Records whose POIs were removed by the tourism keep list were skipped directly.",
        "- Remaining consecutive duplicate POIs were merged into a single visit block.",
        "- Short trajectories were retained; trajectories with only 1 or 2 final visits were not removed.",
        "",
        "## Counts",
        "",
        f"- Raw cleaned trajectory count: {rebuild_stats['raw_trajectory_count']}",
        f"- Retained trajectory count after POI filtering: {rebuild_stats['retained_trajectory_count']}",
        f"- Dropped trajectories whose every POI was removed: {rebuild_stats['dropped_trajectory_count']}",
        f"- Photo-level records after POI filtering: {rebuild_stats['retained_photo_record_count']}",
        f"- Final visit-level records: {rebuild_stats['final_visit_record_count']}",
        f"- Trajectories affected by skip-linking: {rebuild_stats['skip_affected_trajectory_count']}",
        f"- Trajectories with skip-induced adjacent-duplicate compression: {rebuild_stats['skip_duplicate_trajectory_count']}",
        f"- Skip-induced duplicate compression events: {rebuild_stats['skip_duplicate_event_count']}",
        f"- Adjacent duplicate merges after filtering: {rebuild_stats['adjacent_duplicate_merge_count']}",
        "",
        "## Original Visit-Length Distribution",
        "",
        f"- Length = 1: {original_length_stats['length_eq_1']}",
        f"- Length = 2: {original_length_stats['length_eq_2']}",
        f"- Length >= 3: {original_length_stats['length_ge_3']}",
        f"- Mean length: {original_length_stats['mean_length']:.2f}",
        f"- Median length: {original_length_stats['median_length']:.2f}",
        f"- Max length: {original_length_stats['max_length']}",
        "",
        "## Final Visit-Length Distribution",
        "",
        f"- Length = 1: {final_length_stats['length_eq_1']}",
        f"- Length = 2: {final_length_stats['length_eq_2']}",
        f"- Length >= 3: {final_length_stats['length_ge_3']}",
        f"- Mean length: {final_length_stats['mean_length']:.2f}",
        f"- Median length: {final_length_stats['median_length']:.2f}",
        f"- Max length: {final_length_stats['max_length']}",
        "",
        "## Length Change After POI Removal",
        "",
        f"- Unchanged visit counts: {length_change_stats['unchanged']}",
        f"- Reduced by 1 visit: {length_change_stats['reduced_by_1']}",
        f"- Reduced by 2 visits: {length_change_stats['reduced_by_2']}",
        f"- Reduced by 3 or more visits: {length_change_stats['reduced_by_3_or_more']}",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_cleaning_report(
    output_path: Path,
    *,
    config: CleanConfig,
    poi_stats: dict[str, Any],
    visit_stats: dict[str, Any],
    raw_sequence_count: int,
    classified_pois: pd.DataFrame,
    removed_pois: pd.DataFrame,
    trajectory_csv: pd.DataFrame,
    duration_stats: dict[str, Any],
    rebuild_stats: dict[str, Any],
) -> None:
    category_source_counts = classified_pois["category_source"].value_counts().to_dict()
    category_counts = classified_pois["category"].value_counts().sort_index()
    final_length_stats = summarize_length_distribution(
        trajectory_csv.groupby("trajectory_id").size() if not trajectory_csv.empty else pd.Series(dtype=int)
    )

    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(config.project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    lines = [
        f"# {CITY_NAME} Cleaning Report",
        "",
        "## Output Files",
        "",
        f"- `poi.csv`: `{rel(config.output_dir / 'poi.csv')}`",
        f"- `trajectory.csv`: `{rel(config.output_dir / 'trajectory.csv')}`",
        f"- `removed_poi_list.csv`: `{rel(config.output_dir / 'removed_poi_list.csv')}`",
        f"- `category_mapping_report.csv`: `{rel(config.output_dir / 'category_mapping_report.csv')}`",
        f"- `trajectory_rebuild_report.md`: `{rel(config.output_dir / 'trajectory_rebuild_report.md')}`",
        f"- Published `data/poi.csv`: `{rel(config.publish_dir / 'poi.csv')}`",
        f"- Published `data/trajectory.csv`: `{rel(config.publish_dir / 'trajectory.csv')}`",
        "",
        "## Input Statistics",
        "",
        f"- Raw POI count: {poi_stats['raw_poi_count']}",
        f"- POIs removed as invalid/incomplete before rule filtering: {poi_stats['invalid_or_incomplete_poi_count']}",
        f"- Raw photo-level visit record count: {visit_stats['raw_photo_record_count']}",
        f"- Raw sequence count: {raw_sequence_count}",
        f"- Raw user count after basic ID cleaning: {visit_stats['clean_user_count']}",
        "",
        "## Cleaning Statistics",
        "",
        f"- Removed invalid timestamp records: {visit_stats['removed_invalid_time_records']}",
        f"- Removed invalid identity records: {visit_stats['removed_invalid_identity_records']}",
        f"- Removed visits that referenced unknown source POIs: {visit_stats['removed_unknown_source_poi_records']}",
        f"- Photo-level records after basic cleaning: {visit_stats['clean_photo_record_count']}",
        f"- Removed POIs by tourism rules: {len(removed_pois)}",
        f"- Final retained POI count: {len(classified_pois)}",
        f"- Removed photo-level records because POIs were filtered out: {rebuild_stats['removed_filtered_out_poi_records']}",
        f"- Photo-level records after POI filtering: {rebuild_stats['retained_photo_record_count']}",
        f"- Visit-level records after aggregation: {len(trajectory_csv)}",
        f"- Final retained trajectory count: {trajectory_csv['trajectory_id'].nunique()}",
        "",
        "## Final Trajectory Length Distribution",
        "",
        f"- Length = 1 trajectories: {final_length_stats['length_eq_1']}",
        f"- Length = 2 trajectories: {final_length_stats['length_eq_2']}",
        f"- Length >= 3 trajectories: {final_length_stats['length_ge_3']}",
        f"- Mean trajectory length: {final_length_stats['mean_length']:.2f}",
        f"- Median trajectory length: {final_length_stats['median_length']:.2f}",
        f"- Max trajectory length: {final_length_stats['max_length']}",
        "",
        "## Category Strategy",
        "",
        "- Categories were redefined into unified tourism labels instead of reusing the raw `theme/subTheme` values directly.",
        "- Classification priority was: exact-name manual mapping -> name keyword rule -> subtheme rule.",
        "- Fixed local mappings were used at runtime; the script does not depend on live web requests.",
        f"- Manual-name mappings used: {category_source_counts.get('manual_name_mapping', 0)}",
        f"- Name keyword rules used: {category_source_counts.get('name_keyword_rule', 0)}",
        f"- Subtheme rules used: {category_source_counts.get('subtheme_rule', 0)}",
        "",
        "## Final Category Counts",
        "",
    ]

    for category, count in category_counts.items():
        lines.append(f"- {category}: {int(count)}")

    lines.extend(
        [
            "",
            "## Duration Estimation",
            "",
            "- POI-level `visit_duration_minutes` was estimated as the median positive duration of that POI's visit blocks.",
            f"- Positive visit-duration samples used: {duration_stats['positive_visit_duration_sample_count']}",
            f"- POIs using the default duration ({int(config.default_visit_duration_minutes)}): {duration_stats['default_duration_poi_count']}",
            f"- Mean POI visit duration: {duration_stats['poi_duration_mean']:.2f}",
            f"- Median POI visit duration: {duration_stats['poi_duration_median']:.2f}",
            "",
            "## Keep/Remove Notes Required By The Spec",
            "",
            "- Kept all transport POIs (`Railway Station`, `Transport Terminal`) and all `Tertiary (University)` POIs.",
            "- Kept explicit review points including `Harbour Town`, `Railway Good Shed No 2`, `Council House 2 (CH2)`, `ANZ 'Gothic' Bank`, and `Dallas Brooks Centre`.",
            "- Removed non-tourism medical, school, police/fire/forensic/judicial back-office, film/broadcast production, industrial, and wholesale-market sites.",
            "- `Bishopscourt` was removed explicitly.",
            "- `Supreme Court` was removed explicitly.",
            "",
            "## Trajectory Rebuild Notes Required By The Spec",
            "",
            "- If a POI was removed from a trajectory, the script skipped it and connected the previous retained POI directly to the next retained POI in time order.",
            "- After skipping removed POIs, adjacent duplicate POIs were compressed into a single visit block.",
            "- Short trajectories were retained; this cleaning flow does not delete trajectories only because they became short.",
            "",
            "## Validation Summary",
            "",
            "- `poi.csv`: unique `poi_id`, non-empty `poi_name` and `category`, valid coordinates, non-negative `visit_duration_minutes`.",
            "- `trajectory.csv`: all `poi_id` values exist in `poi.csv`, `visit_order` starts from 1 and stays contiguous, timestamps are non-decreasing, and required identifiers are non-empty.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_main_outputs(config: CleanConfig, poi_csv_path: Path, trajectory_csv_path: Path) -> dict[str, Path]:
    config.publish_dir.mkdir(parents=True, exist_ok=True)
    publish_poi_path = config.publish_dir / "poi.csv"
    publish_trajectory_path = config.publish_dir / "trajectory.csv"
    shutil.copy2(poi_csv_path, publish_poi_path)
    shutil.copy2(trajectory_csv_path, publish_trajectory_path)
    return {
        "publish_poi_path": publish_poi_path,
        "publish_trajectory_path": publish_trajectory_path,
    }


def run_cleaning(config: CleanConfig) -> dict[str, Any]:
    for input_path in (config.poi_path, config.visits_path):
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

    poi_raw = load_csv(config.poi_path)
    visits_raw = load_csv(config.visits_path)
    raw_sequence_count = int(pd.to_numeric(visits_raw["seqID"], errors="coerce").nunique())

    poi_table, poi_stats = clean_poi_table(poi_raw)
    keep_remove_rules = build_keep_remove_rules()
    kept_pois, removed_pois = filter_pois(poi_table, keep_remove_rules)
    classified_pois = classify_poi_categories(kept_pois)
    clean_visits, visit_stats = clean_visit_records(
        visits_raw,
        valid_raw_poi_ids=set(poi_table["raw_poi_id_num"].astype(int).tolist()),
    )
    aggregated_visits, trajectory_summary, rebuild_stats = rebuild_trajectories_with_skips(
        clean_visits,
        classified_pois,
    )
    poi_with_durations, duration_stats = estimate_poi_durations(
        classified_pois,
        aggregated_visits,
        default_duration_minutes=config.default_visit_duration_minutes,
    )

    poi_csv = build_output_poi_csv(poi_with_durations)
    trajectory_csv = build_output_trajectory_csv(aggregated_visits)
    validate_outputs(poi_csv, trajectory_csv)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    poi_output_path = config.output_dir / "poi.csv"
    trajectory_output_path = config.output_dir / "trajectory.csv"
    removed_poi_output_path = config.output_dir / "removed_poi_list.csv"
    category_mapping_output_path = config.output_dir / "category_mapping_report.csv"
    trajectory_rebuild_output_path = config.output_dir / "trajectory_rebuild_report.md"
    cleaning_report_output_path = config.output_dir / "cleaning_report.md"

    poi_csv.to_csv(poi_output_path, index=False, encoding="utf-8")
    trajectory_csv.to_csv(trajectory_output_path, index=False, encoding="utf-8")
    write_removed_poi_list(removed_poi_output_path, removed_pois)
    write_category_mapping_report(category_mapping_output_path, poi_with_durations)
    write_trajectory_rebuild_report(trajectory_rebuild_output_path, trajectory_summary, rebuild_stats)

    publish_paths = publish_main_outputs(config, poi_output_path, trajectory_output_path)
    write_cleaning_report(
        cleaning_report_output_path,
        config=config,
        poi_stats=poi_stats,
        visit_stats=visit_stats,
        raw_sequence_count=raw_sequence_count,
        classified_pois=poi_with_durations,
        removed_pois=removed_pois,
        trajectory_csv=trajectory_csv,
        duration_stats=duration_stats,
        rebuild_stats=rebuild_stats,
    )

    return {
        "poi_output_path": poi_output_path,
        "trajectory_output_path": trajectory_output_path,
        "removed_poi_output_path": removed_poi_output_path,
        "category_mapping_output_path": category_mapping_output_path,
        "trajectory_rebuild_output_path": trajectory_rebuild_output_path,
        "cleaning_report_output_path": cleaning_report_output_path,
        "publish_poi_path": publish_paths["publish_poi_path"],
        "publish_trajectory_path": publish_paths["publish_trajectory_path"],
        "poi_count": int(len(poi_csv)),
        "trajectory_count": int(trajectory_csv["trajectory_id"].nunique()),
        "visit_count": int(len(trajectory_csv)),
        "removed_poi_count": int(len(removed_pois)),
        "category_count": int(poi_csv["category"].nunique()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean Melbourne tourism data for the route project.")
    parser.add_argument("--input-dir", type=str, default="data2", help="Directory that contains the Melbourne source CSV files.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=f"data_cleaned/{CITY_SLUG}",
        help="Directory for cleaned outputs and reports.",
    )
    parser.add_argument(
        "--publish-dir",
        type=str,
        default="data",
        help="Directory that should receive the project-ready poi.csv and trajectory.csv files.",
    )
    parser.add_argument("--poi-file", type=str, default="POI-Melb.csv", help="POI source filename.")
    parser.add_argument("--visits-file", type=str, default="userVisits-Melb-allPOI.csv", help="Visit source filename.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    config = CleanConfig(
        project_root=project_root,
        input_dir=resolve_path(project_root, args.input_dir),
        output_dir=resolve_path(project_root, args.output_dir),
        publish_dir=resolve_path(project_root, args.publish_dir),
        poi_filename=args.poi_file,
        visits_filename=args.visits_file,
    )
    stats = run_cleaning(config)
    print(f"{CITY_NAME} data cleaning completed.")
    print(f"POI count: {stats['poi_count']}")
    print(f"Removed POI count: {stats['removed_poi_count']}")
    print(f"Category count: {stats['category_count']}")
    print(f"Trajectory count: {stats['trajectory_count']}")
    print(f"Visit count: {stats['visit_count']}")
    print(f"Cleaned poi.csv: {stats['poi_output_path']}")
    print(f"Cleaned trajectory.csv: {stats['trajectory_output_path']}")
    print(f"Published poi.csv: {stats['publish_poi_path']}")
    print(f"Published trajectory.csv: {stats['publish_trajectory_path']}")


if __name__ == "__main__":
    main()
