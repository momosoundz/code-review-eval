import math

import pytest

from eval.harness.stats import (
    CaseScore,
    Verdict,
    paired_bootstrap,
    verdict,
    wilson,
)


def test_wilson_known_values() -> None:
    low, high = wilson(35, 40)
    assert math.isclose(low, 0.738, abs_tol=0.002)
    assert math.isclose(high, 0.945, abs_tol=0.002)
    assert wilson(0, 15) == pytest.approx((0.0, 0.204), abs=0.002)
    assert wilson(0, 0) == (0.0, 1.0)


def scores(values: dict[str, float], family: dict[str, str] | None = None) -> list[CaseScore]:
    return [CaseScore(cid, (family or {}).get(cid, cid), v) for cid, v in values.items()]


def test_paired_bootstrap_zero_delta_when_identical() -> None:
    a = scores({"c1": 1, "c2": 0, "c3": 1, "c4": 1})
    ci = paired_bootstrap(a, a, resamples=500, seed=1)
    assert ci.delta == 0 and ci.low == 0 and ci.high == 0


def test_paired_bootstrap_recovers_known_delta() -> None:
    a = scores({f"c{i}": 1.0 if i < 30 else 0.0 for i in range(40)})
    b = scores({f"c{i}": 1.0 if i < 20 else 0.0 for i in range(40)})
    ci = paired_bootstrap(a, b, resamples=2000, seed=7)
    assert ci.delta == pytest.approx(-0.25)
    assert ci.low < -0.25 < ci.high
    assert ci.low < -0.1


def test_paired_bootstrap_is_seeded() -> None:
    a = scores({f"c{i}": float(i % 2) for i in range(20)})
    b = scores({f"c{i}": float(i % 3 == 0) for i in range(20)})
    assert paired_bootstrap(a, b, 300, 3) == paired_bootstrap(a, b, 300, 3)
    assert paired_bootstrap(a, b, 300, 3) != paired_bootstrap(a, b, 300, 4)


def test_paired_bootstrap_resamples_by_family() -> None:
    fam = {"c1": "f1", "c2": "f1", "c3": "f2", "c4": "f2"}
    a = scores({"c1": 1, "c2": 1, "c3": 0, "c4": 0}, fam)
    b = scores({"c1": 0, "c2": 0, "c3": 0, "c4": 0}, fam)
    ci = paired_bootstrap(a, b, resamples=400, seed=2)
    assert ci.delta == -0.5
    assert ci.families == 2
    assert ci.low <= -0.5 <= ci.high


def test_paired_bootstrap_requires_same_cases() -> None:
    with pytest.raises(ValueError, match="same cases"):
        paired_bootstrap(scores({"c1": 1}), scores({"c2": 1}), 10, 1)


def test_verdict_pass_when_lower_bound_within_margin() -> None:
    v = verdict((-0.05, 0.10), floors_ok=True, floors_broken=False, families=30, max_drop=0.10)
    assert v is Verdict.PASS


def test_verdict_inconclusive_when_ci_crosses_margin() -> None:
    v = verdict((-0.19, 0.02), floors_ok=True, floors_broken=False, families=30, max_drop=0.10)
    assert v is Verdict.INCONCLUSIVE


def test_verdict_fail_when_floor_broken() -> None:
    v = verdict((0.0, 0.1), floors_ok=False, floors_broken=True, families=30, max_drop=0.10)
    assert v is Verdict.FAIL


def test_verdict_inconclusive_when_floor_uncertain() -> None:
    v = verdict((0.0, 0.1), floors_ok=False, floors_broken=False, families=30, max_drop=0.10)
    assert v is Verdict.INCONCLUSIVE


def test_verdict_fails_when_the_whole_interval_is_below_the_margin() -> None:
    v = verdict((-0.40, -0.12), floors_ok=True, floors_broken=False, families=30, max_drop=0.10)
    assert v is Verdict.FAIL


def test_verdict_tiny_sample_still_fails_on_a_conclusive_drop() -> None:
    v = verdict((-0.60, -0.20), floors_ok=True, floors_broken=False, families=2, max_drop=0.10)
    assert v is Verdict.FAIL


def test_verdict_never_passes_on_a_tiny_sample() -> None:
    v = verdict((0.0, 0.1), floors_ok=True, floors_broken=False, families=2, max_drop=0.10)
    assert v is Verdict.INCONCLUSIVE


def test_paired_bootstrap_rejects_duplicates_and_empty() -> None:
    dup = scores({"c1": 1}) + scores({"c1": 0})
    with pytest.raises(ValueError, match="once each"):
        paired_bootstrap(dup, dup, 10, 1)
    with pytest.raises(ValueError, match="same cases"):
        paired_bootstrap([], [], 10, 1)
