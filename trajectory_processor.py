"""轨迹预处理模块。"""

from __future__ import annotations

from typing import Dict, List, Sequence

from data_loader import VisitRecord


def _collapse_consecutive_duplicates(poi_sequence: Sequence[str]) -> List[str]:
    """Remove only adjacent duplicate POIs while preserving route order."""
    collapsed: List[str] = []
    previous_poi: str | None = None
    for poi_id in poi_sequence:
        if poi_id == previous_poi:
            continue
        collapsed.append(poi_id)
        previous_poi = poi_id
    return collapsed


def build_ordered_sequences(
    trajectory_dict: Dict[str, Sequence[VisitRecord]],
    *,
    collapse_consecutive_duplicates: bool = False,
) -> Dict[str, List[str]]:
    """将每条轨迹按visit_order排序后，转换为POI序列。"""
    ordered_sequences: Dict[str, List[str]] = {}
    for trajectory_id, records in trajectory_dict.items():
        sorted_records = sorted(records, key=lambda x: x["visit_order"])
        poi_sequence = [record["poi_id"] for record in sorted_records]
        if collapse_consecutive_duplicates:
            poi_sequence = _collapse_consecutive_duplicates(poi_sequence)
        ordered_sequences[trajectory_id] = poi_sequence
    return ordered_sequences
