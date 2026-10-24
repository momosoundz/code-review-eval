"""Score a collected run offline: match every response against gold and aggregate."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval.harness.collect import response_path
from eval.harness.config import (
    GATE_METRIC,
    LINE_TOLERANCE,
    MIN_SLICE_SIZE,
    RUNS_DIR,
)
from eval.harness.dataset import CASES_DIR, Case, GoldFinding, gold_hash, load_dataset
from eval.harness.judge import Judge, JudgeResponseError, JudgeUnavailableError
from eval.harness.match import counts_toward_precision, match_case
from eval.harness.stats import wilson

CaseJudge = Callable[[str, dict[str, Any], GoldFinding], str]


def _load_manifest(run: str, runs_dir: Path) -> dict[str, Any]:
    return json.loads((runs_dir / run / "manifest.json").read_text())


def _load_result(path: Path, case_id: str) -> dict[str, Any]:
    if not path.exists():
        msg = f"missing response for {case_id}: {path}"
        raise FileNotFoundError(msg)
    return json.loads(path.read_text())["result"]


def _row(case: Case, k: int, result: dict[str, Any], judge: CaseJudge, tolerance: int) -> dict:
    findings = [] if result["no_output"] else result["findings"]
    outcome = match_case(
        findings, list(case.expected_findings), lambda f, g: judge(case.case_id, f, g), tolerance
    )
    highs = [g.gold_id for g in case.high_gold]
    gated = [g.gold_id for g in case.gated_gold]
    lows = [g.gold_id for g in case.low_gold]
    recall_gated = None if not gated else float(all(g in outcome.matched for g in gated))
    recall_low = None if not lows else sum(g in outcome.matched for g in lows) / len(lows)
    tp_medium_plus = sum(counts_toward_precision(findings[i]) for i in outcome.matched.values())
    recall_high = None if not highs else float(all(g in outcome.matched for g in highs))
    return {
        "case_id": case.case_id,
        "k": k,
        "family_id": case.family_id,
        "source": case.source,
        "split": case.split,
        "is_clean": case.is_clean,
        "no_output": bool(result["no_output"]),
        "findings": len(findings),
        "tp": outcome.tp,
        "tp_medium_plus": tp_medium_plus,
        "fp": outcome.fp,
        "fn": outcome.fn,
        "noise": outcome.noise,
        "duplicates": outcome.duplicates,
        "matched": outcome.matched,
        "unknown_pairs": outcome.unknown_pairs,
        "recall_all": None
        if not case.expected_findings
        else outcome.tp / len(case.expected_findings),
        "recall_high": recall_high,
        "recall_medium_plus": recall_gated,
        "recall_low": recall_low,
        "clean_alarm": int(case.is_clean and outcome.fp > 0),
        "elapsed_ms": result["elapsed_ms"],
        "output_tokens": result["usage"]["output_tokens"],
        "input_tokens": result["usage"]["input_tokens"],
    }


def score_run(
    run: str,
    cases: list[Case],
    judge: CaseJudge,
    runs_dir: Path = RUNS_DIR,
    tolerance: int = LINE_TOLERANCE,
) -> list[dict[str, Any]]:
    """One row per (case, k) for the cases named in the run manifest."""
    manifest = _load_manifest(run, runs_dir)
    by_id = {c.case_id: c for c in cases}
    rows: list[dict[str, Any]] = []
    for case_id in manifest["case_ids"]:
        case = by_id[case_id]
        for k in range(1, manifest["k"] + 1):
            path = response_path(
                runs_dir, manifest["model"], manifest["reviewer_version"], case_id, k
            )
            rows.append(_row(case, k, _load_result(path, case_id), judge, tolerance))
    return rows


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _per_case(rows: list[dict[str, Any]], key: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in rows:
        if r[key] is not None:
            out.setdefault(r["case_id"], []).append(float(r[key]))
    return out


def _rate(rows: list[dict[str, Any]], key: str, k: int) -> dict[str, Any]:
    """Mean over cases of the per-case mean over K, plus all-K and any-K rates.

    ``wilson_case_runs`` is over the raw (case, run) outcomes and treats runs as independent,
    which overstates certainty: descriptive only. ``wilson_cases`` is over cases, counting a case
    as a success when any of its K runs succeeded; it is the interval the floors use.
    Inference lives in the paired bootstrap.
    """
    per_case = _per_case(rows, key)
    means = [sum(v) / len(v) for v in per_case.values()]
    all_k = [float(all(x == 1.0 for x in v)) for v in per_case.values()]
    any_k = [float(any(x == 1.0 for x in v)) for v in per_case.values()]
    outcomes = [x for v in per_case.values() for x in v]
    return {
        "mean": _mean(means),
        "all_k": _mean(all_k),
        "any_k": _mean(any_k),
        "n_cases": len(means),
        "k": k,
        "wilson_case_runs": [round(x, 4) for x in wilson(round(sum(outcomes)), len(outcomes))],
        "wilson_cases": [round(x, 4) for x in wilson(round(sum(any_k)), len(any_k))],
        "gates": len(means) >= MIN_SLICE_SIZE,
    }


def _precision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Matched findings of severity medium or high over all medium-or-high findings."""
    tp = sum(r["tp_medium_plus"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    return {
        "value": round(tp / (tp + fp), 4) if tp + fp else None,
        "tp": tp,
        "fp": fp,
        "wilson": [round(x, 4) for x in wilson(tp, tp + fp)],
    }


def _slices(rows: list[dict[str, Any]], cases: list[Case], k: int) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for source in sorted({c.source for c in cases}):
        subset = [r for r in rows if r["source"] == source]
        out[source] = {
            "n_cases": len({r["case_id"] for r in subset}),
            "recall_all": _rate(subset, "recall_all", k),
        }
    return out


def summarize(
    rows: list[dict[str, Any]],
    cases: list[Case],
    k: int,
    judge: dict[str, str] | None = None,
    tolerance: int = LINE_TOLERANCE,
) -> dict[str, Any]:
    """Headline metrics: gate, floors, diagnostics, slices, and what scored them."""
    n = len(rows)
    return {
        "n_cases": len({r["case_id"] for r in rows}),
        "k": k,
        "judge": judge or {},
        "line_tolerance": tolerance,
        "gate_metric": GATE_METRIC,
        "recall_medium_plus": _rate(rows, "recall_medium_plus", k),
        "recall_high": _rate(rows, "recall_high", k),
        "recall_all": _rate(rows, "recall_all", k),
        "recall_low": _rate(rows, "recall_low", k),
        "precision_medium_plus": _precision(rows),
        "clean_fp_rate": _rate([r for r in rows if r["is_clean"]], "clean_alarm", k),
        "no_output_rate": round(sum(r["no_output"] for r in rows) / n, 4) if n else None,
        "findings_per_diff": _mean([float(r["findings"]) for r in rows]),
        "noise_per_diff": _mean([float(r["noise"]) for r in rows]),
        "duplicate_rate": round(
            sum(r["duplicates"] for r in rows) / max(1, sum(r["findings"] for r in rows)), 4
        ),
        "unknown_pairs": sum(len(r["unknown_pairs"]) for r in rows),
        "p50_elapsed_ms": sorted(r["elapsed_ms"] for r in rows)[n // 2] if n else None,
        "by_source": _slices(rows, cases, k),
    }


def write_outputs(
    run: str, rows: list[dict[str, Any]], summary: dict[str, Any], runs_dir: Path = RUNS_DIR
) -> None:
    """Write ``scored.jsonl`` and ``summary.json`` next to the run manifest."""
    out = runs_dir / run
    (out / "scored.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--run NAME [--online]``. Offline unless ``--online``: no key is read from the env."""
    parser = argparse.ArgumentParser(description="Score a collected run.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--online", action="store_true", help="allow judge calls for new pairs")
    parser.add_argument("--tolerance", type=int, default=LINE_TOLERANCE)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    args = parser.parse_args(argv)
    judge = Judge(offline=not args.online)
    try:
        cases = load_dataset(args.cases_dir)
        manifest = _load_manifest(args.run, args.runs_dir)
        run_cases = [c for c in cases if c.case_id in manifest["case_ids"]]
        current = gold_hash(run_cases)
        if current != manifest["gold_hash"] or len(run_cases) != len(manifest["case_ids"]):
            msg = (
                f"dataset changed since the run was collected (gold_hash {current} vs "
                f"{manifest['gold_hash']}); collect again or pin the dataset version"
            )
            raise ValueError(msg)
        rows = score_run(args.run, cases, judge.decide, args.runs_dir, args.tolerance)
    except (ValueError, FileNotFoundError, JudgeUnavailableError, JudgeResponseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    summary = summarize(
        rows,
        run_cases,
        manifest["k"],
        judge={"model": judge.model, "prompt_hash": judge.prompt_hash},
        tolerance=args.tolerance,
    )
    summary["gold_hash"] = current
    write_outputs(args.run, rows, summary, args.runs_dir)
    rh = summary["recall_medium_plus"]
    pr, cf = summary["precision_medium_plus"], summary["clean_fp_rate"]
    print(
        f"{summary['n_cases']} cases x K={manifest['k']}: recall_medium_plus {rh['mean']} "
        f"(all K {rh['all_k']}, n={rh['n_cases']}), precision@>=medium {pr['value']} "
        f"({pr['tp']}/{pr['tp'] + pr['fp']}), clean FP rate {cf['mean']} (n={cf['n_cases']}), "
        f"no_output {summary['no_output_rate']}, judge calls {judge.calls}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
