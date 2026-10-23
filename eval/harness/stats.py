"""The statistics the eval reports: Wilson intervals, a paired bootstrap by family, a verdict."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

from eval.harness.config import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, GATE_MAX_DROP, MIN_SLICE_SIZE

Z95 = 1.959964


@dataclass(frozen=True)
class CaseScore:
    """One case's value of a metric (already averaged over its K runs) and its family."""

    case_id: str
    family_id: str
    value: float


@dataclass(frozen=True)
class PairedCI:
    """Observed paired delta (b minus a) and its bootstrap percentile interval."""

    delta: float
    low: float
    high: float
    families: int
    resamples: int


class Verdict(Enum):
    """Release decision for a candidate against a baseline."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a proportion; ``(0, 1)`` when ``n`` is zero."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _by_family(scores: list[CaseScore]) -> dict[str, list[CaseScore]]:
    families: dict[str, list[CaseScore]] = {}
    for score in scores:
        families.setdefault(score.family_id, []).append(score)
    return families


def paired_bootstrap(
    a: list[CaseScore],
    b: list[CaseScore],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> PairedCI:
    """Percentile bootstrap of ``mean(b) - mean(a)``, resampling families with replacement.

    Both lists must cover the same case ids. A family is resampled whole, so a clean/seeded
    pair stays together and the interval does not pretend the two are independent.
    """
    ids_a, ids_b = [s.case_id for s in a], [s.case_id for s in b]
    if (
        not a
        or len(set(ids_a)) != len(ids_a)
        or set(ids_a) != set(ids_b)
        or len(ids_b) != len(ids_a)
    ):
        msg = "paired bootstrap needs the same cases, once each, in both runs"
        raise ValueError(msg)
    b_values = {s.case_id: s.value for s in b}
    families = list(_by_family(a).values())
    deltas = [b_values[s.case_id] - s.value for s in a]
    observed = sum(deltas) / len(deltas)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        total = 0.0
        count = 0
        for _ in families:
            family = families[rng.randrange(len(families))]
            for s in family:
                total += b_values[s.case_id] - s.value
                count += 1
        draws.append(total / count)
    draws.sort()
    low = draws[round(0.025 * (resamples - 1))]
    high = draws[round(0.975 * (resamples - 1))]
    return PairedCI(round(observed, 4), round(low, 4), round(high, 4), len(families), resamples)


def verdict(
    delta_low: float,
    floors_ok: bool,
    floors_broken: bool,
    families: int,
    max_drop: float = GATE_MAX_DROP,
) -> Verdict:
    """PASS, FAIL or INCONCLUSIVE from the gate interval, the floor checks and the sample size.

    ``floors_broken`` means a floor is below its threshold with its interval excluding the
    baseline value; ``floors_ok`` means every floor holds with its interval. Fewer than
    ``MIN_SLICE_SIZE`` families can never PASS: the bootstrap has nothing to resample.
    """
    if floors_broken:
        return Verdict.FAIL
    if families >= MIN_SLICE_SIZE and delta_low >= -max_drop and floors_ok:
        return Verdict.PASS
    return Verdict.INCONCLUSIVE
