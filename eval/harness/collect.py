"""Call the reviewer K times per case and store every raw response. Never overwrites."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.harness.config import BUDGET_USD, PRICES_PER_MTOK, RUNS_DIR
from eval.harness.dataset import Case, gold_hash, load_dataset
from reviewer.config import CONTEXT_MODE, CONTEXT_MODES, EFFORT, MODEL
from reviewer.diffs import number_diff
from reviewer.review import ReviewResult, input_sha256, prompt_id, review_diff


class BudgetExceededError(RuntimeError):
    """The estimated spend of this run crossed the configured cap."""


class UnknownModelError(ValueError):
    """The model has no entry in the price table, so the budget cap cannot be enforced."""


@dataclass(frozen=True)
class CollectSettings:
    """Knobs of a collect run; defaults come from the reviewer and harness config."""

    model: str = MODEL
    effort: str = EFFORT
    context_mode: str = CONTEXT_MODE
    budget_usd: float = BUDGET_USD
    runs_dir: Path = RUNS_DIR


def response_path(runs_dir: Path, model: str, version: str, case_id: str, k: int) -> Path:
    """Where the raw response of run ``k`` for ``case_id`` under this reviewer version lives."""
    return runs_dir / "responses" / model / version / case_id / f"{case_id}-k{k}.json"


def estimate_cost(model: str, usage: dict[str, int]) -> float:
    """USD estimate from the price table.

    Raises:
        UnknownModelError: For a model without a price; the budget cap cannot work without one.
    """
    if model not in PRICES_PER_MTOK:
        msg = f"no price for model {model!r} in PRICES_PER_MTOK; add it before collecting"
        raise UnknownModelError(msg)
    price_in, price_out = PRICES_PER_MTOK[model]
    return (usage["input_tokens"] * price_in + usage["output_tokens"] * price_out) / 1_000_000


def reviewer_version(context_mode: str, effort: str) -> str:
    """Directory name for one reviewer configuration: prompt+schema hash and effort."""
    return f"{prompt_id(context_mode)}-{effort}"


def _cached_cost(path: Path, model: str) -> float:
    return estimate_cost(model, json.loads(path.read_text())["result"]["usage"])


def _check_cached_input(path: Path, case: Case, settings: CollectSettings) -> None:
    """A stored response must come from the same input we would send now, or it is stale."""
    stored = json.loads(path.read_text())["result"].get("input_sha256")
    expected = input_sha256(number_diff(case.diff).text, settings.context_mode, case.commit_title)
    if stored and stored != expected:
        msg = (
            f"{path} was produced from a different input (title or diff changed); "
            "move it aside or use a new case id"
        )
        raise FileExistsError(msg)


def _write_manifest(out: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest, refusing to replace one that describes a different run shape."""
    if out.exists():
        previous = json.loads(out.read_text())
        keys = ("k", "case_ids", "prompt_id", "reviewer_version", "model")
        same = all(previous.get(k) == manifest[k] for k in keys)
        if not same:
            msg = (
                f"{out} already describes a different run (k, cases or reviewer); pick a new --run"
            )
            raise FileExistsError(msg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")


def git_sha() -> str:
    """Short sha of the working tree, or ``unknown`` outside a repository."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return out.stdout.strip()


def _collect_one(path: Path, case: Case, settings: CollectSettings) -> ReviewResult:
    result, raw = review_diff(
        case.diff, settings.model, settings.effort, settings.context_mode, case.commit_title
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"result": asdict(result), "raw": raw}, indent=2) + "\n")
    return result


def collect_run(
    run: str, k: int, cases: list[Case], settings: CollectSettings | None = None
) -> dict[str, Any]:
    """Store ``k`` responses per case and write ``runs_dir/<run>/manifest.json``.

    Existing responses are reused, never rewritten. A ``no_output`` result is cached like
    any other so scoring sees it. Raises ``BudgetExceededError`` when the estimated spend of
    this invocation passes ``budget_usd``; what was collected so far stays on disk.
    """
    settings = settings or CollectSettings()
    model, effort, budget_usd = settings.model, settings.effort, settings.budget_usd
    version = reviewer_version(settings.context_mode, effort)
    started = datetime.now(UTC)
    without_title = [c.case_id for c in cases if not c.commit_title]
    calls = hits = no_output = 0
    cost = spent_now = 0.0
    for case in cases:
        for i in range(1, k + 1):
            path = response_path(settings.runs_dir, model, version, case.case_id, i)
            if path.exists():
                _check_cached_input(path, case, settings)
                hits += 1
                cost += _cached_cost(path, model)
                continue
            result = _collect_one(path, case, settings)
            calls += 1
            no_output += int(result.no_output)
            spent_now += estimate_cost(model, result.usage)
            cost += estimate_cost(model, result.usage)
            if cost > budget_usd:
                msg = (
                    f"run {run} passed the {budget_usd:.2f} USD budget "
                    f"({cost:.2f} USD across all responses of this reviewer version)"
                )
                raise BudgetExceededError(msg)
    manifest = {
        "run": run,
        "model": model,
        "effort": effort,
        "prompt_id": prompt_id(settings.context_mode),
        "reviewer_version": version,
        "context_mode": settings.context_mode,
        "cases_without_title": without_title if settings.context_mode != "hunk_only" else [],
        "k": k,
        "split": sorted({c.split for c in cases}),
        "case_ids": [c.case_id for c in cases],
        "gold_hash": gold_hash(cases),
        "git_sha": git_sha(),
        "calls_made": calls,
        "cache_hits": hits,
        "no_output": no_output,
        "cost_usd": round(cost, 4),
        "cost_usd_this_invocation": round(spent_now, 4),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_manifest(settings.runs_dir / run / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--run NAME --k N [--split dev|release]``."""
    parser = argparse.ArgumentParser(description="Collect K reviewer responses per case.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--split", default="release")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default=EFFORT)
    parser.add_argument("--context-mode", default=CONTEXT_MODE, choices=CONTEXT_MODES)
    args = parser.parse_args(argv)
    cases = [c for c in load_dataset() if c.active and c.split == args.split]
    if not cases:
        print(f"no active cases in split {args.split!r}", file=sys.stderr)
        return 1
    try:
        settings = CollectSettings(
            model=args.model, effort=args.effort, context_mode=args.context_mode
        )
        manifest = collect_run(args.run, args.k, cases, settings)
    except (BudgetExceededError, FileExistsError, UnknownModelError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 3
    print(
        f"{manifest['calls_made']} call(s), {manifest['cache_hits']} cached, "
        f"{manifest['no_output']} no_output, est. {manifest['cost_usd']:.3f} USD"
    )
    if manifest["cases_without_title"]:
        print(
            f"warning: {len(manifest['cases_without_title'])} case(s) have no commit title and "
            "were reviewed as hunk_only",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
