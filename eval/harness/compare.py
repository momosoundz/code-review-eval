"""Compare a candidate run against a baseline, case by case, and emit a verdict."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.harness.config import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    GATE_MAX_DROP,
    GATE_METRIC,
    MIN_SLICE_SIZE,
    RUNS_DIR,
)
from eval.harness.stats import CaseScore, paired_bootstrap, verdict


def _read(runs_dir: Path, run: str, name: str) -> Any:
    path = runs_dir / run / name
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in path.read_text().splitlines() if line]
    return json.loads(path.read_text())


def _case_means(rows: list[dict[str, Any]], key: str) -> list[CaseScore]:
    per: dict[str, list[float]] = {}
    family: dict[str, str] = {}
    for r in rows:
        if r[key] is None:
            continue
        per.setdefault(r["case_id"], []).append(float(r[key]))
        family[r["case_id"]] = r["family_id"]
    return [CaseScore(c, family[c], sum(v) / len(v)) for c, v in sorted(per.items())]


def _moved(a: list[CaseScore], b: list[CaseScore], direction: int) -> list[dict[str, Any]]:
    b_by = {s.case_id: s.value for s in b}
    moved = []
    for s in a:
        delta = b_by[s.case_id] - s.value
        if delta * direction > 0:
            moved.append({"case_id": s.case_id, "baseline": s.value, "candidate": b_by[s.case_id]})
    return moved


def _check_comparable(
    a: dict[str, Any], b: dict[str, Any], sa: dict[str, Any], sb: dict[str, Any]
) -> None:
    """Refuse to compare runs whose gold, judge, k or tolerance differ.

    Reviewer-side settings (prompt, context mode, effort, model) are allowed to differ: they
    are what an experiment changes, and the manifest records them.
    """
    if a["gold_hash"] != b["gold_hash"]:
        msg = f"runs have different gold_hash ({a['gold_hash']} vs {b['gold_hash']}); rescore first"
        raise ValueError(msg)
    for manifest, summary in ((a, sa), (b, sb)):
        if summary.get("gold_hash") != manifest["gold_hash"]:
            msg = (
                f"run {manifest.get('run', '?')} was scored under gold_hash "
                f"{summary.get('gold_hash')} but collected under {manifest['gold_hash']}; "
                "rescore it"
            )
            raise ValueError(msg)
    same_judge = (sa["judge"]["prompt_hash"], sa["judge"]["model"]) == (
        sb["judge"]["prompt_hash"],
        sb["judge"]["model"],
    )
    if not same_judge:
        msg = "runs were scored by different judge versions; rescore both with the same judge"
        raise ValueError(msg)
    for key, va, vb in (
        ("k", a.get("k"), b.get("k")),
        ("line_tolerance", sa.get("line_tolerance"), sb.get("line_tolerance")),
    ):
        if va != vb:
            msg = f"runs differ in {key} ({va} vs {vb}); they are not comparable"
            raise ValueError(msg)


def _floors(sa: dict[str, Any], sb: dict[str, Any]) -> tuple[bool, bool, dict[str, Any]]:
    """Precision and clean-FP floors: hold unless the candidate is worse beyond the baseline CI.

    A floor holds (``ok``) when the candidate's point estimate sits inside the baseline's
    interval, and is broken only when the two intervals do not overlap. The clean-alarm floor
    is judged per case: the rate of clean diffs that alarm in any of the K runs (``any_k``),
    against the Wilson interval over cases, never the per-run mean. With
    few clean cases the intervals are wide, so that floor can rarely be declared broken: it
    fails to hold instead, which makes the verdict INCONCLUSIVE rather than FAIL. A floor can
    only be declared ok with enough data: at least ``MIN_SLICE_SIZE`` clean cases for the
    false-alarm floor and ``MIN_SLICE_SIZE`` medium-or-high findings for precision.
    """
    pa, pb = sa["precision_medium_plus"], sb["precision_medium_plus"]
    ca, cb = sa["clean_fp_rate"], sb["clean_fp_rate"]
    enough_findings = (pa["tp"] + pa["fp"]) >= MIN_SLICE_SIZE
    enough_clean = cb["n_cases"] >= MIN_SLICE_SIZE
    both_precision = pa["value"] is not None and pb["value"] is not None
    both_clean = ca["any_k"] is not None and cb["any_k"] is not None
    precision_ok = enough_findings and both_precision and pb["value"] >= pa["wilson"][0]
    precision_broken = both_precision and pb["wilson"][1] < pa["wilson"][0]
    clean_ok = enough_clean and both_clean and cb["any_k"] <= ca["wilson_cases"][1]
    clean_broken = both_clean and cb["wilson_cases"][0] > ca["wilson_cases"][1]
    detail = {
        "precision": {
            "baseline": pa["value"],
            "candidate": pb["value"],
            "ok": precision_ok,
            "enough_findings": enough_findings,
        },
        "clean_fp_rate": {
            "baseline": ca["any_k"],
            "candidate": cb["any_k"],
            "unit": "share of clean cases alarming in any of K runs",
            "ok": clean_ok,
            "enough_cases": enough_clean,
        },
    }
    return precision_ok and clean_ok, precision_broken or clean_broken, detail


def compare_runs(
    baseline: str,
    candidate: str,
    runs_dir: Path = RUNS_DIR,
    resamples: int = BOOTSTRAP_RESAMPLES,
    max_drop: float = GATE_MAX_DROP,
) -> dict[str, Any]:
    """Paired comparison on the gate metric with floors; writes comparison-vs-<baseline>.json."""
    ma, mb = _read(runs_dir, baseline, "manifest.json"), _read(runs_dir, candidate, "manifest.json")
    sa, sb = _read(runs_dir, baseline, "summary.json"), _read(runs_dir, candidate, "summary.json")
    _check_comparable(ma, mb, sa, sb)
    ra, rb = _read(runs_dir, baseline, "scored.jsonl"), _read(runs_dir, candidate, "scored.jsonl")
    a_high, b_high = _case_means(ra, GATE_METRIC), _case_means(rb, GATE_METRIC)
    ci = paired_bootstrap(a_high, b_high, resamples, BOOTSTRAP_SEED)
    floors_ok, floors_broken, floors = _floors(sa, sb)
    decision = verdict((ci.low, ci.high), floors_ok, floors_broken, ci.families, max_drop)
    a_clean, b_clean = _case_means(ra, "clean_alarm"), _case_means(rb, "clean_alarm")
    out = {
        "baseline": baseline,
        "candidate": candidate,
        "verdict": decision.value,
        "gate": {
            "metric": GATE_METRIC,
            "max_drop": max_drop,
            "min_families": MIN_SLICE_SIZE,
            "rule": (
                "PASS: families >= min_families and ci_low >= -max_drop and floors ok; "
                "FAIL: ci_high < -max_drop or a floor broken; else INCONCLUSIVE"
            ),
        },
        "gate_metric": {
            "delta": ci.delta,
            "ci95": [ci.low, ci.high],
            "families": ci.families,
            "resamples": ci.resamples,
            "n_cases": len(a_high),
        },
        "floors": floors,
        "lost_cases": _moved(a_high, b_high, -1),
        "gained_cases": _moved(a_high, b_high, +1),
        "new_clean_alarms": _moved(a_clean, b_clean, +1),
        "baseline_prompt_id": ma["prompt_id"],
        "candidate_prompt_id": mb["prompt_id"],
    }
    (runs_dir / candidate / f"comparison-vs-{baseline}.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    return out


def _floors_line(floors: dict[str, Any]) -> str:
    """One line per floor: baseline -> candidate and whether the floor holds."""
    pr, cl = floors["precision"], floors["clean_fp_rate"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{100 * x:.0f}%"

    def state(floor: dict[str, Any]) -> str:
        if floor["ok"]:
            return "floor ok"
        enough = floor.get("enough_findings", floor.get("enough_cases", True))
        return "floor not declarable" if not enough else "floor NOT met"

    return (
        f"  precision@>=medium {pct(pr['baseline'])} -> {pct(pr['candidate'])} ({state(pr)}); "
        f"clean cases alarming {pct(cl['baseline'])} -> {pct(cl['candidate'])} ({state(cl)})"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--a BASELINE --b CANDIDATE``. Exit 0 PASS, 1 FAIL, 2 INCONCLUSIVE, 3 error."""
    parser = argparse.ArgumentParser(description="Compare two scored runs.")
    parser.add_argument("--a", required=True, help="baseline run")
    parser.add_argument("--b", required=True, help="candidate run")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    try:
        out = compare_runs(args.a, args.b, runs_dir=args.runs_dir)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    rh = out["gate_metric"]
    print(
        f"{out['verdict']}: {GATE_METRIC} delta {rh['delta']:+.3f} CI95 {rh['ci95']} "
        f"over {rh['n_cases']} cases in {rh['families']} families"
    )
    print(_floors_line(out["floors"]))
    for label in ("lost_cases", "gained_cases", "new_clean_alarms"):
        for item in out[label]:
            print(f"  {label}: {item['case_id']} {item['baseline']} -> {item['candidate']}")
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[out["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
