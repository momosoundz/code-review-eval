"""Calibrate the match judge against human pair labels: TPR, TNR, kappa, corrected recall."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.harness.config import ROOT, RUNS_DIR
from eval.harness.judge import JUDGE_MODEL, VERDICTS_DIR, judge_prompt_hash
from eval.harness.stats import wilson

LABELS_PATH = ROOT / "eval" / "labels" / "pair-labels.jsonl"


def load_labels(path: Path, version: str) -> list[dict[str, Any]]:
    """Human labels for one judge version, one per pair; a later label supersedes an earlier one.

    Lines that are not valid JSON (a truncated write) are skipped.
    """
    by_pair: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("judge_version") == version:
            by_pair[record["pair_id"]] = record
    return list(by_pair.values())


def load_verdicts(verdicts_dir: Path, version: str) -> dict[str, str]:
    """``pair_id -> verdict`` for every cached verdict under ``version``."""
    out = {}
    for path in (verdicts_dir / version).glob("*/*.json"):
        out[path.stem] = json.loads(path.read_text())["verdict"]
    return out


def confusion(labels: list[dict[str, Any]], verdicts: dict[str, str]) -> dict[str, int]:
    """Counts of (human, judge) outcomes over the labeled pairs that have a verdict."""
    counts = {"tp": 0, "fn": 0, "tn": 0, "fp": 0}
    for row in labels:
        verdict = verdicts.get(row["pair_id"])
        if verdict not in ("match", "no_match"):
            continue
        human_same = row["label"] == "same"
        judge_same = verdict == "match"
        if human_same and judge_same:
            counts["tp"] += 1
        elif human_same:
            counts["fn"] += 1
        elif judge_same:
            counts["fp"] += 1
        else:
            counts["tn"] += 1
    return counts


def stratum_weights(labels: list[dict[str, Any]], verdicts: dict[str, str]) -> dict[str, float]:
    """Store count over labeled count, per judge verdict; 1.0 for a stratum with no labels."""
    store = {"match": 0, "no_match": 0}
    for v in verdicts.values():
        if v in store:
            store[v] += 1
    labeled = {"match": 0, "no_match": 0}
    for row in labels:
        v = verdicts.get(row["pair_id"])
        if v in labeled:
            labeled[v] += 1
    return {k: (store[k] / labeled[k] if labeled[k] else 1.0) for k in store}


def rates(counts: dict[str, int], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Judge error rates from a sample stratified by the judge's own verdict.

    The labeled pairs were sampled by verdict (every ``no_match``, a few ``match`` per gold),
    so the columns of the confusion matrix are complete within each stratum but the strata are
    not in their store proportions. Precision-side rates condition on the verdict and are
    unbiased as sampled: ``ppv`` is the share of judge matches that the human confirms, ``npv``
    the share of judge rejections the human confirms, both with Wilson intervals. ``tpr`` and
    ``tnr`` condition on the human label and need the store proportions back: each stratum is
    reweighted by ``weights`` (store count over labeled count); they are point estimates only.
    ``kappa_sample`` is Cohen's kappa on the labeled pairs as they are; ``kappa`` on the
    reweighted matrix.
    """
    tp, fn, tn, fp = counts["tp"], counts["fn"], counts["tn"], counts["fp"]
    w_match = (weights or {}).get("match", 1.0)
    w_no = (weights or {}).get("no_match", 1.0)
    wtp, wfp, wfn, wtn = tp * w_match, fp * w_match, fn * w_no, tn * w_no
    n = tp + fn + tn + fp
    return {
        "n": n,
        "ppv": tp / (tp + fp) if tp + fp else None,
        "ppv_wilson": list(wilson(tp, tp + fp)) if tp + fp else None,
        "npv": tn / (tn + fn) if tn + fn else None,
        "npv_wilson": list(wilson(tn, tn + fn)) if tn + fn else None,
        "tpr": wtp / (wtp + wfn) if wtp + wfn else None,
        "tnr": wtn / (wtn + wfp) if wtn + wfp else None,
        "weights": {"match": w_match, "no_match": w_no},
        "kappa_sample": _kappa(tp, fp, fn, tn),
        "kappa": _kappa(wtp, wfp, wfn, wtn),
    }


def _kappa(tp: float, fp: float, fn: float, tn: float) -> float | None:
    """Cohen's kappa for a 2x2 matrix; ``None`` when empty or when chance agreement is total."""
    n = tp + fp + fn + tn
    if not n:
        return None
    observed = (tp + tn) / n
    expected = ((tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)) / (n * n)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def corrected_rate(observed: float, tpr: float, tnr: float) -> float | None:
    """Rogan-Gladen correction of an observed positive rate for an imperfect classifier.

    ``observed = tpr * p + (1 - tnr) * (1 - p)`` solved for ``p``, clipped to [0, 1]. Returns
    ``None`` when the judge is no better than chance (``tpr + tnr <= 1``). Applied to the gate
    recall as an approximation: a case outcome is one judged pair when the case has one gated
    gold, which holds for all but three release cases.
    """
    denominator = tpr + tnr - 1
    if denominator <= 0:
        return None
    return min(1.0, max(0.0, (observed - (1 - tnr)) / denominator))


def corrected_runs(runs: list[str], runs_dir: Path, tpr: float, tnr: float) -> list[dict]:
    """Observed and corrected gate recall for each run's summary."""
    out = []
    for run in runs:
        summary = json.loads((runs_dir / run / "summary.json").read_text())
        observed = summary["recall_medium_plus"]["mean"]
        out.append(
            {"run": run, "observed": observed, "corrected": corrected_rate(observed, tpr, tnr)}
        )
    return out


def render(report: dict[str, Any]) -> str:
    """Markdown for EVAL.md."""
    r = report["rates"]
    c = report["confusion"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{100 * x:.0f}%"

    def ci(pair: list[float] | None) -> str:
        return "" if not pair else f" [{100 * pair[0]:.0f}, {100 * pair[1]:.0f}]"

    lines = [
        f"Judge `{report['judge_version']}` against {r['n']} rater-labeled pairs "
        f"({report['unsure']} unsure excluded).",
        "",
        "| | judge: match | judge: no_match |",
        "|---|---|---|",
        f"| rater: same | {c['tp']} | {c['fn']} |",
        f"| rater: different | {c['fp']} | {c['tn']} |",
        "",
        f"Of the judge's matches, {pct(r['ppv'])}{ci(r['ppv_wilson'])} are confirmed by the "
        f"rater; of its rejections, {pct(r['npv'])}{ci(r['npv_wilson'])}. Reweighted to the "
        f"store ({r['weights']['match']:.1f}x match, {r['weights']['no_match']:.1f}x no_match): "
        f"TPR {pct(r['tpr'])}, TNR {pct(r['tnr'])}. Kappa on the sample "
        f"{'n/a' if r['kappa_sample'] is None else format(r['kappa_sample'], '.2f')}, "
        f"reweighted {'n/a' if r['kappa'] is None else format(r['kappa'], '.2f')}.",
    ]
    if report["runs"]:
        lines += ["", "| run | observed gate recall | corrected |", "|---|---|---|"]
        for row in report["runs"]:
            lines.append(f"| {row['run']} | {pct(row['observed'])} | {pct(row['corrected'])} |")
    return "\n".join(lines) + "\n"


def calibrate(
    labels_path: Path, verdicts_dir: Path, version: str, runs: list[str], runs_dir: Path
) -> dict[str, Any]:
    """Confusion matrix, rates and corrected recall for the given runs."""
    all_rows = load_labels(labels_path, version)
    labels = [r for r in all_rows if r["label"] in ("same", "different")]
    verdicts = load_verdicts(verdicts_dir, version)
    counts = confusion(labels, verdicts)
    r = rates(counts, stratum_weights(labels, verdicts))
    corrected = []
    if runs and r["tpr"] is not None and r["tnr"] is not None:
        corrected = corrected_runs(runs, runs_dir, r["tpr"], r["tnr"])
    return {
        "judge_version": version,
        "confusion": counts,
        "rates": r,
        "unsure": len(all_rows) - len(labels),
        "runs": corrected,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ``[--runs a,b] [--labels PATH]``; prints markdown and writes calibration.json."""
    parser = argparse.ArgumentParser(description="Calibrate the judge against human labels.")
    parser.add_argument("--runs", default="", help="comma-separated runs for corrected recall")
    parser.add_argument("--labels", type=Path, default=LABELS_PATH)
    parser.add_argument("--verdicts-dir", type=Path, default=VERDICTS_DIR)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    version = f"{JUDGE_MODEL}-{judge_prompt_hash()}"
    runs = [r for r in args.runs.split(",") if r]
    try:
        report = calibrate(args.labels, args.verdicts_dir, version, runs, args.runs_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    (args.labels.parent / "calibration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
