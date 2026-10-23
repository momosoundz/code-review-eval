"""Match reviewer findings to gold defects: a location gate, a binary judge, one-to-one pairing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from eval.harness.config import FP_SEVERITIES, LINE_TOLERANCE
from eval.harness.dataset import GoldFinding
from reviewer.config import NON_GATED_CATEGORIES

Judge = Callable[[dict[str, Any], GoldFinding], str]
Pair = tuple[int, str, int]


@dataclass
class MatchOutcome:
    """Counts for one review of one case, plus the pairs behind them."""

    matched: dict[str, int] = field(default_factory=dict)
    tp: int = 0
    fp: int = 0
    fn: int = 0
    noise: int = 0
    duplicates: int = 0
    unknown_pairs: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class _Pairing:
    matched: dict[str, int] = field(default_factory=dict)
    duplicates: set[int] = field(default_factory=set)
    unknown: dict[int, list[str]] = field(default_factory=dict)


def _distance(line: int, spans: tuple[tuple[int, int], ...]) -> int:
    return min(max(start - line, 0, line - end) for start, end in spans)


def eligible_pairs(
    findings: list[dict[str, Any]], golds: list[GoldFinding], tolerance: int = LINE_TOLERANCE
) -> list[Pair]:
    """``(finding_index, gold_id, distance)`` for each finding within ``tolerance`` of a gold.

    Sorted by distance, then gold id, then finding index, so pairing is deterministic.
    """
    pairs: list[Pair] = []
    for index, finding in enumerate(findings):
        for gold in golds:
            distances = [
                _distance(int(finding["line"]), spans)
                for file, spans in gold.locations
                if finding["file"] == file
            ]
            if distances and min(distances) <= tolerance:
                pairs.append((index, gold.gold_id, min(distances)))
    return sorted(pairs, key=lambda p: (p[2], p[1], p[0]))


def _counts_as_fp(finding: dict[str, Any]) -> bool:
    return finding["severity"] in FP_SEVERITIES and finding["category"] not in NON_GATED_CATEGORIES


def _pair(
    findings: list[dict[str, Any]], golds: list[GoldFinding], judge: Judge, tol: int
) -> _Pairing:
    """Greedy one-to-one pairing. The judge decides matches and duplicates alike."""
    state = _Pairing()
    by_id = {g.gold_id: g for g in golds}
    for index, gold_id, _ in eligible_pairs(findings, golds, tol):
        if index in state.matched.values() or index in state.duplicates:
            continue
        verdict = judge(findings[index], by_id[gold_id])
        if verdict == "unknown":
            state.unknown.setdefault(index, []).append(gold_id)
        elif verdict == "match" and gold_id in state.matched:
            state.duplicates.add(index)
        elif verdict == "match":
            state.matched[gold_id] = index
    return state


def match_case(
    findings: list[dict[str, Any]],
    golds: list[GoldFinding],
    judge: Judge,
    tolerance: int = LINE_TOLERANCE,
) -> MatchOutcome:
    """Pair findings with golds and count TP, FP, FN, noise and duplicates.

    A finding earns at most one TP and a gold is matched at most once. A second finding the
    judge also matches to an already matched gold is a duplicate (noise). An unmatched finding
    is an FP when its severity is in ``FP_SEVERITIES`` and its category is gated, otherwise
    noise. A finding whose only verdicts were ``unknown`` is neither TP nor FP; it is listed in
    ``unknown_pairs`` for human review.
    """
    state = _pair(findings, golds, judge, tolerance)
    outcome = MatchOutcome(matched=state.matched)
    for index, finding in enumerate(findings):
        if index in state.matched.values():
            continue
        if index in state.duplicates:
            outcome.duplicates += 1
            outcome.noise += 1
        elif index in state.unknown:
            outcome.unknown_pairs += [(index, g) for g in state.unknown[index]]
        elif _counts_as_fp(finding):
            outcome.fp += 1
        else:
            outcome.noise += 1
    outcome.tp = len(state.matched)
    outcome.fn = len(golds) - outcome.tp
    return outcome
