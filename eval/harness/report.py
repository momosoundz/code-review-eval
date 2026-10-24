"""Render a run summary, and optionally a comparison, as the markdown tables EVAL.md uses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.harness.config import RUNS_DIR


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.0f}%"


def _interval(pair: list[float] | None) -> str:
    return "" if not pair else f" [{100 * pair[0]:.0f}, {100 * pair[1]:.0f}]"


def _rate_row(label: str, rate: dict[str, Any]) -> str:
    gates = "" if rate.get("gates", True) else " (too few to gate)"
    interval = _interval(rate.get("wilson_case_runs")) if rate["n_cases"] else ""
    return (
        f"| {label} | {_pct(rate['mean'])}{interval} | "
        f"{_pct(rate['all_k'])} | {_pct(rate['any_k'])} | {rate['n_cases']}{gates} |"
    )


def summary_table(summary: dict[str, Any]) -> str:
    """Headline metrics of one run as a markdown table."""
    k = summary["k"]
    pr = summary["precision_medium_plus"]
    lines = [
        f"| metric | mean over K={k} [Wilson 95% on case runs, descriptive] | all K | any K "
        "| cases |",
        "|---|---|---|---|---|",
        _rate_row("recall, defects medium or high (gate)", summary["recall_medium_plus"]),
        _rate_row("recall, high only", summary["recall_high"]),
        _rate_row("recall, all defects", summary["recall_all"]),
        _rate_row("recall, low only", summary["recall_low"]),
        _rate_row("clean diffs with a false alarm", summary["clean_fp_rate"]),
        "| precision at severity medium or high | "
        f"{_pct(pr['value'])}{_interval(pr.get('wilson'))} | | | {pr['tp']} TP / {pr['fp']} FP |",
        "",
        f"no_output {_pct(summary['no_output_rate'])}, "
        f"findings per diff {summary['findings_per_diff']}, "
        f"noise per diff {summary['noise_per_diff']}, "
        f"duplicate rate {_pct(summary['duplicate_rate'])}, "
        f"unknown judge pairs {summary['unknown_pairs']}, "
        f"p50 latency {summary['p50_elapsed_ms']} ms.",
    ]
    return "\n".join(lines)


def slices_table(summary: dict[str, Any]) -> str:
    """Recall over all defects by case source."""
    lines = [
        "| source | cases | recall, all defects [Wilson 95% on case runs] | all K |",
        "|---|---|---|---|",
    ]
    for source, data in summary["by_source"].items():
        r = data["recall_all"]
        interval = _interval(r.get("wilson_case_runs")) if r["n_cases"] else ""
        lines.append(
            f"| {source} | {data['n_cases']} | {_pct(r['mean'])}{interval} | {_pct(r['all_k'])} |"
        )
    return "\n".join(lines)


def comparison_table(comparison: dict[str, Any]) -> str:
    """Verdict, paired delta and the named cases that moved."""
    g = comparison["gate_metric"]
    gate = comparison["gate"]
    low, high = (100 * x for x in g["ci95"])
    lines = [
        f"**{comparison['verdict']}** on {gate['metric']}: delta {100 * g['delta']:+.0f} points, "
        f"95% CI [{low:+.0f}, {high:+.0f}] over {g['n_cases']} cases in {g['families']} families "
        f"(gate: lower bound >= {-100 * gate['max_drop']:.0f}, "
        f"at least {gate['min_families']} families).",
    ]
    for label, items in (
        ("Lost", comparison["lost_cases"]),
        ("Gained", comparison["gained_cases"]),
        ("New clean alarms", comparison["new_clean_alarms"]),
    ):
        if items:
            names = ", ".join(
                f"{i['case_id']} ({i['baseline']:.2f} -> {i['candidate']:.2f})" for i in items
            )
            lines.append(f"- {label}: {names}")
        else:
            lines.append(f"- {label}: none")
    return "\n".join(lines)


def render(run: str, runs_dir: Path = RUNS_DIR, baseline: str | None = None) -> str:
    """Markdown for one run, plus its comparison against ``baseline`` when given."""
    summary = json.loads((runs_dir / run / "summary.json").read_text())
    manifest = json.loads((runs_dir / run / "manifest.json").read_text())
    parts = [f"### {run}", "", summary_table(summary), "", slices_table(summary)]
    without_title = manifest.get("cases_without_title", [])
    if without_title:
        parts += [
            "",
            f"{len(without_title)} case(s) have no commit title and were reviewed as "
            f"`hunk_only` under context mode `{manifest['context_mode']}`: "
            + ", ".join(without_title)
            + ".",
        ]
    if baseline:
        comparison = json.loads((runs_dir / run / f"comparison-vs-{baseline}.json").read_text())
        parts += ["", comparison_table(comparison)]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--run NAME [--baseline NAME] [--runs-dir DIR]``; prints markdown."""
    parser = argparse.ArgumentParser(description="Render a run as markdown.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    try:
        print(render(args.run, args.runs_dir, args.baseline))
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: cannot render {args.run}: {exc!r}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
