"""Combine two collected runs into a third, synthetic run under a deterministic policy.

No model call is made. For each case and each run index k, the findings of run A and run B
are merged by file and line proximity: ``union`` keeps everything once (A's wording and
severity win on a shared anchor, so the order of the two runs matters), ``agreement`` keeps
only what both reviewers flagged near the same line. The merged model id has no price entry:
the merged run is scored and compared, never collected. The merged responses are written to the
response store like any other reviewer version, so ``score`` and ``compare`` apply unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from eval.harness.collect import response_path
from eval.harness.config import LINE_TOLERANCE, RUNS_DIR
from reviewer.config import SEVERITIES

POLICIES = ("union", "agreement")


def _near(a: dict[str, Any], b: dict[str, Any], tolerance: int) -> bool:
    return a["file"] == b["file"] and abs(int(a["line"]) - int(b["line"])) <= tolerance


def _rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def merge_findings(
    a: list[dict[str, Any]], b: list[dict[str, Any]], policy: str, tolerance: int = LINE_TOLERANCE
) -> list[dict[str, Any]]:
    """Merge two finding lists.

    ``union``: every finding of A, plus each finding of B that is not within ``tolerance``
    lines of a finding already kept. ``agreement``: each finding of A that has a finding of B
    within ``tolerance`` lines in the same file, with the lower of the two severities.
    """
    if policy == "union":
        kept = [dict(f) for f in a]
        for fb in b:
            if not any(_near(fb, fa, tolerance) for fa in kept):
                kept.append(fb)
        return kept
    if policy == "agreement":
        kept = []
        for fa in a:
            partners = [fb for fb in b if _near(fa, fb, tolerance)]
            if partners:
                lowest = max([*partners, fa], key=lambda f: _rank(f["severity"]))
                kept.append({**fa, "severity": lowest["severity"]})
        return kept
    msg = f"unknown policy {policy!r}; use one of {POLICIES}"
    raise ValueError(msg)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def merged_version(manifest_a: dict[str, Any], manifest_b: dict[str, Any], policy: str) -> str:
    """Directory name of the merged reviewer version: policy plus a hash of both versions."""
    blob = "+".join([policy, manifest_a["reviewer_version"], manifest_b["reviewer_version"]])
    return f"{policy}-{hashlib.sha256(blob.encode()).hexdigest()[:12]}"


def _merge_one(ra: dict[str, Any], rb: dict[str, Any], policy: str, tol: int) -> dict[str, Any]:
    no_output = (
        (ra["no_output"] and rb["no_output"])
        if policy == "union"
        else (ra["no_output"] or rb["no_output"])
    )
    findings = [] if no_output else merge_findings(ra["findings"], rb["findings"], policy, tol)
    return {
        "findings": findings,
        "no_output": no_output,
        "error": None if not no_output else f"{policy}: {ra['error']} / {rb['error']}",
        "dropped": [],
        "usage": {
            k: int(ra["usage"].get(k, 0)) + int(rb["usage"].get(k, 0))
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")
        },
        "elapsed_ms": max(ra["elapsed_ms"], rb["elapsed_ms"]),
        "model": f"{ra['model']}+{rb['model']}",
        "prompt_id": f"{policy}:{ra['prompt_id']}+{rb['prompt_id']}",
        "context_used": ra.get("context_used"),
        "input_sha256": ra.get("input_sha256"),
    }


def merge_runs(
    run_a: str, run_b: str, policy: str, out_run: str, runs_dir: Path = RUNS_DIR
) -> dict[str, Any]:
    """Write the merged responses and ``runs_dir/<out_run>/manifest.json``; return the manifest.

    Both runs must cover the same cases with the same K under the same gold hash.
    """
    ma, mb = _read(runs_dir / run_a / "manifest.json"), _read(runs_dir / run_b / "manifest.json")
    for key in ("case_ids", "k", "gold_hash"):
        if ma[key] != mb[key]:
            msg = f"runs differ in {key}; they cannot be merged"
            raise ValueError(msg)
    model = f"{ma['model']}+{mb['model']}"
    version = merged_version(ma, mb, policy)
    no_output = 0
    for case_id in ma["case_ids"]:
        for k in range(1, ma["k"] + 1):
            ra = _read(response_path(runs_dir, ma["model"], ma["reviewer_version"], case_id, k))
            rb = _read(response_path(runs_dir, mb["model"], mb["reviewer_version"], case_id, k))
            merged = _merge_one(ra["result"], rb["result"], policy, LINE_TOLERANCE)
            no_output += int(merged["no_output"])
            out = response_path(runs_dir, model, version, case_id, k)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps({"result": merged, "raw": {"merged_from": [run_a, run_b]}}, indent=2)
                + "\n"
            )
    cost = round(ma.get("cost_usd", 0.0) + mb.get("cost_usd", 0.0), 4)
    manifest = {
        **{k: ma[k] for k in ("k", "split", "case_ids", "gold_hash", "git_sha", "context_mode")},
        "run": out_run,
        "model": model,
        "effort": f"{ma['effort']}+{mb['effort']}",
        "prompt_id": f"{policy}:{ma['prompt_id']}+{mb['prompt_id']}",
        "reviewer_version": version,
        "merge": {"policy": policy, "runs": [run_a, run_b], "line_tolerance": LINE_TOLERANCE},
        "cases_without_title": ma.get("cases_without_title", []),
        "calls_made": 0,
        "cache_hits": len(ma["case_ids"]) * ma["k"],
        "no_output": no_output,
        "cost_usd": cost,
        "cost_usd_this_invocation": 0.0,
    }
    (runs_dir / out_run).mkdir(parents=True, exist_ok=True)
    (runs_dir / out_run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--a RUN --b RUN --policy union|agreement --out RUN``."""
    parser = argparse.ArgumentParser(description="Merge two runs under a policy.")
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--policy", required=True, choices=POLICIES)
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    try:
        manifest = merge_runs(args.a, args.b, args.policy, args.out, args.runs_dir)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"{args.out}: {len(manifest['case_ids'])} cases x K={manifest['k']}, {args.policy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
