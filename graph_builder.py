"""有向图构建模块。"""

from __future__ import annotations

from typing import Iterable

import networkx as nx

from pattern_mining import PairStat


def build_directed_graph(prevalent_pairs: Iterable[PairStat]) -> nx.DiGraph:
    """根据PLCP2构建有向图。"""
    graph = nx.DiGraph()
    for stat in prevalent_pairs:
        src, dst = stat.pair
        graph.add_edge(
            src,
            dst,
            occ_support=stat.occ_support,
            traj_support=stat.traj_support,
            pair_tpi=stat.pair_tpi,
        )
    return graph
