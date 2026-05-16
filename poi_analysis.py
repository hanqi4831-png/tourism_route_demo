"""POI分析模块。"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Sequence


def compute_poi_popularity(sequences: Dict[str, Sequence[str]]) -> Dict[str, float]:
    """
    计算POI热度：
    popularity(poi) = visit_count / total_visits
    """
    counter: Counter[str] = Counter()
    total_visits = 0
    for poi_list in sequences.values():
        counter.update(poi_list)
        total_visits += len(poi_list)
    if total_visits == 0:
        return {}
    return {poi_id: cnt / total_visits for poi_id, cnt in counter.items()}
