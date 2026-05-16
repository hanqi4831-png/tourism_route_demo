"""工具函数。"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算两点地理距离（公里）。"""
    radius_km = 6371.0
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    d_lat = lat2_rad - lat1_rad
    d_lon = lon2_rad - lon1_rad
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def min_max_normalize(values: Sequence[float]) -> List[float]:
    """对列表做最小-最大归一化。"""
    if not values:
        return []
    min_v, max_v = min(values), max(values)
    if math.isclose(min_v, max_v):
        return [1.0 for _ in values]
    return [(v - min_v) / (max_v - min_v) for v in values]


def unique_preserve_order(items: Iterable[T]) -> List[T]:
    """去重且保序。"""
    seen: set[T] = set()
    ordered: List[T] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
