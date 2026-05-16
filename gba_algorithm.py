"""Core implementation of the graph-based algorithm (GBA)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Sequence, Set, Tuple

import networkx as nx

from config import PipelineConfig
from graph_builder import build_directed_graph
from pattern_mining import (
    PairPattern,
    average_pair_tpi_for_cycle,
    compute_feature_trajectory_counts,
    compute_pair_tpi_map,
    get_prevalent_pairs,
    mine_linear_pairs_with_trajectory_ids,
)


@dataclass(frozen=True)
class CircularPattern:
    """A prevalent circular pattern mined by GBA."""

    cycle: Tuple[str, ...]
    avg_pair_tpi: float
    length: int
    path_length: int
    unique_poi_count: int
    cycle_support: int
    supporting_trajectory_ids: frozenset[str]
    cycle_tpi: float
    cycle_strength_global: float


def _canonical_cycle_signature(cycle: Sequence[str]) -> Tuple[str, ...]:
    """Normalize a closed directed cycle up to rotation only."""
    core = list(cycle[:-1])
    if not core:
        return tuple()
    rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
    return min(rotations)


def _sorted_nodes_by_degree(subgraph: nx.DiGraph) -> List[str]:
    """Sort SCC nodes by descending degree, matching the paper's node order."""
    return sorted(
        subgraph.nodes(),
        key=lambda node: (
            -subgraph.degree(node),
            -subgraph.out_degree(node),
            -subgraph.in_degree(node),
            node,
        ),
    )


def _sorted_successors(subgraph: nx.DiGraph, node: str) -> List[str]:
    """Use a deterministic successor order during DFS."""
    return sorted(
        subgraph.successors(node),
        key=lambda neighbor: (
            -subgraph.degree(neighbor),
            -subgraph.out_degree(neighbor),
            -subgraph.in_degree(neighbor),
            neighbor,
        ),
    )


def _is_simple_cycle(cycle: Sequence[str], min_unique_pois: int) -> bool:
    """Return whether the cycle is a valid simple cycle."""
    if len(cycle) < 3 or cycle[0] != cycle[-1]:
        return False
    core = list(cycle[:-1])
    return len(core) >= min_unique_pois and len(core) == len(set(core))


def _find_cycles_in_scc(
    subgraph: nx.DiGraph,
    pair_trajectory_ids: Dict[PairPattern, Set[str]],
    max_cycle_length: int,
    min_unique_pois: int,
) -> List[Tuple[str, ...]]:
    """Find simple candidate cycles inside one SCC."""
    working_graph = subgraph.copy()
    ordered_nodes = _sorted_nodes_by_degree(working_graph)
    cycles: List[Tuple[str, ...]] = []
    seen_signatures: Set[Tuple[str, ...]] = set()

    def dfs(
        start: str,
        current: str,
        path: List[str],
        visited: Set[str],
        supporting_ids: Set[str] | None,
    ) -> None:
        path_length = len(path)
        for neighbor in _sorted_successors(working_graph, current):
            if path_length >= max_cycle_length and neighbor != start:
                continue

            edge_supporting_ids = pair_trajectory_ids.get((current, neighbor), set())
            next_supporting_ids = (
                set(edge_supporting_ids)
                if supporting_ids is None
                else supporting_ids.intersection(edge_supporting_ids)
            )
            if not next_supporting_ids:
                continue

            if neighbor == start:
                found_cycle = tuple(path + [start])
                if not _is_simple_cycle(found_cycle, min_unique_pois):
                    continue
                signature = _canonical_cycle_signature(found_cycle)
                if signature and signature not in seen_signatures:
                    assert found_cycle[0] == found_cycle[-1]
                    assert len(found_cycle[:-1]) == len(set(found_cycle[:-1]))
                    assert len(found_cycle[:-1]) >= min_unique_pois
                    seen_signatures.add(signature)
                    cycles.append(found_cycle)
                continue

            if path_length >= max_cycle_length or neighbor in visited:
                continue

            visited.add(neighbor)
            path.append(neighbor)
            dfs(
                start=start,
                current=neighbor,
                path=path,
                visited=visited,
                supporting_ids=next_supporting_ids,
            )
            path.pop()
            visited.remove(neighbor)

    for start in ordered_nodes:
        if not working_graph.has_node(start):
            continue

        dfs(
            start=start,
            current=start,
            path=[start],
            visited={start},
            supporting_ids=None,
        )
        working_graph.remove_node(start)

    return cycles


def run_gba(
    sequences: Dict[str, Sequence[str]],
    config: PipelineConfig,
) -> Tuple[List[CircularPattern], Dict[PairPattern, float], nx.DiGraph]:
    """Run the full GBA mining flow."""
    pair_counter, pair_trajectory_ids = mine_linear_pairs_with_trajectory_ids(sequences)
    feature_trajectory_counts = compute_feature_trajectory_counts(sequences)
    pair_tpi_map = compute_pair_tpi_map(pair_trajectory_ids, feature_trajectory_counts)
    prevalent_pairs = get_prevalent_pairs(
        pair_counter=pair_counter,
        pair_trajectory_ids=pair_trajectory_ids,
        pair_tpi_map=pair_tpi_map,
        min_prev=config.min_prev,
    )
    graph = build_directed_graph(prevalent_pairs)

    all_cycles: List[Tuple[str, ...]] = []
    max_cycle_length = max(config.max_cycle_length, 2)
    min_unique_pois = max(config.min_gba_unique_pois, 1)
    for scc_nodes in nx.strongly_connected_components(graph):
        if len(scc_nodes) < 2:
            continue

        scc_subgraph = graph.subgraph(scc_nodes).copy()
        all_cycles.extend(
            _find_cycles_in_scc(
                subgraph=scc_subgraph,
                pair_trajectory_ids=pair_trajectory_ids,
                max_cycle_length=max_cycle_length,
                min_unique_pois=min_unique_pois,
            )
        )

    total_trajectory_count = max(len(sequences), 1)
    circular_patterns: List[CircularPattern] = []
    removed_by_unique_poi_count = 0
    for cycle in all_cycles:
        if not _is_simple_cycle(cycle, min_unique_pois):
            removed_by_unique_poi_count += 1
            continue

        edge_support_sets: List[Set[str]] = []
        for i in range(len(cycle) - 1):
            edge_support_sets.append(pair_trajectory_ids.get((cycle[i], cycle[i + 1]), set()))

        supporting_ids = set.intersection(*edge_support_sets) if edge_support_sets else set()
        cycle_support = len(supporting_ids)
        if cycle_support <= 0:
            continue

        core_nodes = list(cycle[:-1])
        unique_poi_count = len(core_nodes)
        denominators = [feature_trajectory_counts.get(node, 0) for node in core_nodes]
        if any(count <= 0 for count in denominators):
            continue

        cycle_tpi = min(cycle_support / count for count in denominators)
        if cycle_tpi < config.min_prev:
            continue

        path_length = len(cycle) - 1
        circular_patterns.append(
            CircularPattern(
                cycle=cycle,
                avg_pair_tpi=average_pair_tpi_for_cycle(cycle, pair_tpi_map),
                length=path_length,
                path_length=path_length,
                unique_poi_count=unique_poi_count,
                cycle_support=cycle_support,
                supporting_trajectory_ids=frozenset(supporting_ids),
                cycle_tpi=cycle_tpi,
                cycle_strength_global=cycle_support / total_trajectory_count,
            )
        )

    candidate_path_counter = Counter(len(cycle) - 1 for cycle in all_cycles)
    kept_path_counter = Counter(pattern.path_length for pattern in circular_patterns)
    kept_unique_counter = Counter(pattern.unique_poi_count for pattern in circular_patterns)
    print(
        "[DEBUG][GBA] "
        f"candidate_simple_cycles={len(all_cycles)}, "
        f"kept_simple_cycles={len(circular_patterns)}, "
        f"removed_by_min_unique_poi_count={removed_by_unique_poi_count}, "
        f"candidate_path_length_distribution={dict(sorted(candidate_path_counter.items()))}, "
        f"kept_path_length_distribution={dict(sorted(kept_path_counter.items()))}, "
        f"kept_unique_poi_count_distribution={dict(sorted(kept_unique_counter.items()))}"
    )

    circular_patterns.sort(
        key=lambda item: (
            -item.cycle_tpi,
            -item.cycle_support,
            -item.unique_poi_count,
            -item.path_length,
            item.cycle,
        )
    )
    return circular_patterns, pair_tpi_map, graph
