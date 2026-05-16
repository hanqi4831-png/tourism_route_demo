"""Mining helpers for 2-size directed patterns used by GBA."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Sequence, Set, Tuple

PairPattern = Tuple[str, str]


@dataclass(frozen=True)
class PairStat:
    """Statistics kept for a prevalent 2-size directed pattern."""

    pair: PairPattern
    occ_support: int
    traj_support: int
    pair_tpi: float


def mine_linear_pairs_with_trajectory_ids(
    sequences: Dict[str, Sequence[str]],
) -> Tuple[Counter[PairPattern], Dict[PairPattern, Set[str]]]:
    """
    Count adjacent directed pairs and record which trajectories contain them.

    ``occ_support`` counts every adjacent occurrence, while ``traj_support``
    counts distinct supporting trajectories.
    """
    pair_counter: Counter[PairPattern] = Counter()
    pair_trajectory_ids: DefaultDict[PairPattern, Set[str]] = defaultdict(set)

    for trajectory_id, poi_list in sequences.items():
        if len(poi_list) < 2:
            continue

        for i in range(len(poi_list) - 1):
            pair = (poi_list[i], poi_list[i + 1])
            pair_counter[pair] += 1
            pair_trajectory_ids[pair].add(trajectory_id)

    return pair_counter, dict(pair_trajectory_ids)


def compute_feature_trajectory_counts(
    sequences: Dict[str, Sequence[str]],
) -> Dict[str, int]:
    """Count how many distinct trajectories visit each POI."""
    feature_counts: DefaultDict[str, int] = defaultdict(int)

    for poi_list in sequences.values():
        for poi in set(poi_list):
            feature_counts[poi] += 1

    return dict(feature_counts)


def compute_pair_tpi_map(
    pair_trajectory_ids: Dict[PairPattern, Set[str]],
    feature_trajectory_counts: Dict[str, int],
) -> Dict[PairPattern, float]:
    """Compute the paper-style TPI for every mined 2-size directed pattern."""
    pair_tpi_map: Dict[PairPattern, float] = {}

    for pair in pair_trajectory_ids:
        pair_tpi_map[pair] = compute_pair_tpi(
            pair=pair,
            pair_trajectory_ids=pair_trajectory_ids,
            feature_trajectory_counts=feature_trajectory_counts,
        )

    return pair_tpi_map


def compute_pair_tpi(
    pair: PairPattern,
    pair_trajectory_ids: Dict[PairPattern, Set[str]],
    feature_trajectory_counts: Dict[str, int],
) -> float:
    """
    Compute TPI for a single 2-size directed pattern.

    pair_tpi(u, v) = min(
        traj_support(u, v) / traj_count(u),
        traj_support(u, v) / traj_count(v),
    )
    """
    u, v = pair
    traj_support = len(pair_trajectory_ids.get(pair, set()))
    u_count = feature_trajectory_counts.get(u, 0)
    v_count = feature_trajectory_counts.get(v, 0)

    if u_count <= 0 or v_count <= 0:
        return 0.0

    return min(traj_support / u_count, traj_support / v_count)


def get_prevalent_pairs(
    pair_counter: Counter[PairPattern],
    pair_trajectory_ids: Dict[PairPattern, Set[str]],
    pair_tpi_map: Dict[PairPattern, float],
    min_prev: float,
) -> List[PairStat]:
    """
    Select PLCP2 patterns using the paper's prevalence threshold only.

    The original GBA flow keeps a 2-size pattern when its TPI is at least
    ``min_prev``. ``occ_support`` is preserved for reporting, but it is not
    used as an extra mining threshold.
    """
    prevalent: List[PairStat] = []

    for pair, occ_support in pair_counter.items():
        pair_tpi = pair_tpi_map.get(pair, 0.0)
        if pair_tpi < min_prev:
            continue

        prevalent.append(
            PairStat(
                pair=pair,
                occ_support=occ_support,
                traj_support=len(pair_trajectory_ids.get(pair, set())),
                pair_tpi=pair_tpi,
            )
        )

    prevalent.sort(
        key=lambda item: (-item.pair_tpi, -item.traj_support, -item.occ_support, item.pair)
    )
    return prevalent


def average_pair_tpi_for_cycle(
    cycle: Sequence[str], pair_tpi_map: Dict[PairPattern, float]
) -> float:
    """Compute the average pair TPI across the directed edges of a cycle."""
    if len(cycle) < 2:
        return 0.0

    tpi_values: List[float] = []
    for i in range(len(cycle) - 1):
        tpi_values.append(pair_tpi_map.get((cycle[i], cycle[i + 1]), 0.0))

    return sum(tpi_values) / max(len(tpi_values), 1)
