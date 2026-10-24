"""Terminal tool to adjudicate reviewer alarms on clean cases, under the rules in PROTOCOL.md.

For each clean release case with at least one medium-or-high finding in any run, the
adjudicator first reads the numbered diff and records a blind assessment. Then every claim
made on that case is shown, shuffled, grouped by the line it anchors on, as text only: no
model name, no run, no severity, no frequency. Each claim gets a verdict ``fp``, ``defect`` or
``unresolved`` and a reason. One JSON line per claim is appended to
``eval/labels/adjudications.jsonl``; nothing is ever edited.

Usage:
    uv run python scripts/adjudicate.py --runs baseline-n44,exp2a-title-verified-n44
    uv run python scripts/adjudicate.py --runs baseline-n44 --only crv-0011
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eval.harness.collect import response_path
from eval.harness.config import GATED_SEVERITIES, ROOT, RUNS_DIR
from eval.harness.dataset import Case, load_dataset
from reviewer.config import NON_GATED_CATEGORIES, SEVERITIES
from reviewer.diffs import number_diff

RULES_VERSION = "adjudication-v1"
OUT_PATH = ROOT / "eval" / "labels" / "adjudications.jsonl"
VERDICTS = {"f": "fp", "d": "defect", "u": "unresolved"}


@dataclass
class Claim:
    """Every finding anchored on one line of one case, with the response files behind them.

    Models word the same claim differently in each run, so claims are grouped by anchor and
    every distinct wording is kept as a variant; the adjudicator reads them together.
    """

    claim_id: str
    case_id: str
    file: str
    line: int
    variants: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        """How many stored responses made this claim; orders the queue, never shown."""
        return len(self.sources)


def claim_id(case_id: str, file: str, line: int) -> str:
    """Stable id of a claim: the case and the anchor line."""
    blob = "\n".join([case_id, file, str(line)])
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def _variant(f: dict) -> str:
    return " ".join(f"{f['description']} Rationale: {f['rationale']}".split())


def _findings(path: Path) -> list[dict]:
    result = json.loads(path.read_text())["result"]
    return [] if result["no_output"] else result["findings"]


def collect_claims(runs_dir: Path, runs: list[str], case_id: str) -> list[Claim]:
    """Distinct medium-or-high claims on ``case_id`` across every response of ``runs``."""
    claims: dict[str, Claim] = {}
    for run in runs:
        manifest = json.loads((runs_dir / run / "manifest.json").read_text())
        if case_id not in manifest["case_ids"]:
            continue
        for k in range(1, manifest["k"] + 1):
            path = response_path(
                runs_dir, manifest["model"], manifest["reviewer_version"], case_id, k
            )
            for f in _findings(path):
                if f["severity"] not in GATED_SEVERITIES or f["category"] in NON_GATED_CATEGORIES:
                    continue
                cid = claim_id(case_id, f["file"], int(f["line"]))
                claim = claims.setdefault(cid, Claim(cid, case_id, f["file"], int(f["line"])))
                if _variant(f) not in claim.variants:
                    claim.variants.append(_variant(f))
                claim.sources.append(str(path.relative_to(runs_dir)))
    return sorted(claims.values(), key=lambda c: c.claim_id)


def queue(cases: list[Case], claims_by_case: dict[str, list[Claim]]) -> list[Case]:
    """Clean cases with at least one claim, most-claimed first, then by id."""
    with_claims = [c for c in cases if c.is_clean and claims_by_case.get(c.case_id)]
    return sorted(
        with_claims,
        key=lambda c: (-sum(cl.count for cl in claims_by_case[c.case_id]), c.case_id),
    )


def already_done(path: Path) -> set[tuple[str, str]]:
    """``(claim_id, diff_sha256)`` pairs already adjudicated, so a session can resume.

    The diff hash is part of the key: a case whose diff was widened with context after an
    ``unresolved`` verdict is adjudicated again on the new diff.
    """
    if not path.exists():
        return set()
    records = [json.loads(line) for line in path.read_text().splitlines() if line]
    return {(r["claim_id"], r["diff_sha256"]) for r in records}


def record(claim: Claim, case: Case, decision: dict[str, object], who: str) -> dict[str, object]:
    """The append-only adjudication record for one claim.

    ``decision`` holds ``blind_assessment``, ``verdict``, ``reason`` and, for a defect, the
    anchor, trigger, impact, severity and evidence.
    """
    return {
        "case_id": case.case_id,
        "diff_sha256": case.diff_sha256,
        "claim_id": claim.claim_id,
        "claim_file": claim.file,
        "claim_line": claim.line,
        "claim_variants": claim.variants,
        "sources": claim.sources,
        **decision,
        "adjudicator": who,
        "adjudicated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rules_version": RULES_VERSION,
    }


def ask(prompt: str, choices: str) -> str:
    """Read one key from ``choices``; repeat until valid."""
    while True:
        answer = input(f"{prompt} [{choices}] ").strip().lower()
        if answer and answer in choices:
            return answer
        print(f"  answer one of: {', '.join(choices)}")


def _ask_detail(verdict: str) -> dict[str, object]:
    detail: dict[str, object] = {"reason": input("  reason (one line): ").strip()}
    if verdict == "defect":
        detail["anchor"] = input("  changed line that anchors the defect (file:line): ").strip()
        detail["trigger"] = input("  concrete trigger: ").strip()
        detail["impact"] = input("  observable impact: ").strip()
        detail["severity"] = ask("  severity", "".join(s[0] for s in SEVERITIES))
        detail["severity"] = next(s for s in SEVERITIES if s[0] == detail["severity"])
        detail["evidence"] = input(
            "  independently checkable evidence (url, test, repro): "
        ).strip()
    return detail


def adjudicate_case(
    case: Case, claims: list[Claim], done: set[tuple[str, str]], who: str, out: Path
) -> None:
    """Blind read, then one verdict per pending claim, each appended as it is given."""
    pending = [c for c in claims if (c.claim_id, case.diff_sha256) not in done]
    if not pending:
        return
    print("\n" + "=" * 100)
    print(f"case {case.case_id}  ({len(pending)} claim(s) to adjudicate; model identity hidden)")
    print("=" * 100)
    print(number_diff(case.diff).text)
    blind = input("Blind assessment: any defect of severity medium or high? (one line): ").strip()
    random.Random(case.case_id).shuffle(pending)
    for index, claim in enumerate(pending, 1):
        print("-" * 100)
        print(f"claim {index}/{len(pending)}  {claim.file}:{claim.line}")
        for variant in claim.variants:
            print(textwrap.indent(textwrap.fill("- " + variant, 96), "  "))
        verdict = VERDICTS[ask("Verdict: (f)alse positive, (d)efect, (u)nresolved", "fdu")]
        decision = {"blind_assessment": blind, "verdict": verdict, **_ask_detail(verdict)}
        with out.open("a") as fh:
            fh.write(json.dumps(record(claim, case, decision, who)) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Walk the queue of alarmed clean cases and append one record per claim."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", required=True, help="comma-separated run names")
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument("--adjudicator", default="miguel")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    runs = args.runs.split(",")
    cases = [c for c in load_dataset() if c.active and c.split == "release" and c.is_clean]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.case_id in wanted]
    claims = {c.case_id: collect_claims(args.runs_dir, runs, c.case_id) for c in cases}
    todo = queue(cases, claims)
    done = already_done(args.out)
    total = sum(
        len([cl for cl in claims[c.case_id] if (cl.claim_id, c.diff_sha256) not in done])
        for c in todo
    )
    print(f"{len(todo)} case(s), {total} claim(s) pending, {len(done)} already in {args.out.name}")
    for index, case in enumerate(todo, 1):
        adjudicate_case(case, claims[case.case_id], done, args.adjudicator, args.out)
        if index < len(todo) and ask("Next case?", "yq") == "q":
            break
    print(f"\nsaved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
