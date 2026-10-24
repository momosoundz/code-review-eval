"""Terminal tool for the human review of gold labels, in two phases per case.

Phase 1 is blind: the reviewer sees exactly what the model sees (the numbered diff) and writes
down any suspected defect. Phase 2 reveals the gold and asks the checklist. Every answer is
appended to ``eval/labels/review-<pass>.jsonl`` so a run can be resumed and audited.

Usage:
    uv run python scripts/review_cases.py --pass 1 [--split dev] [--only crv-0003,crv-0004]
    A pass label such as ``1b`` writes to its own file; use it to re-validate cases whose gold
    changed after a pass, without touching the original pass file.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from eval.harness.config import ROOT
from eval.harness.dataset import Case, load_dataset
from reviewer.diffs import number_diff

LABELS_DIR = ROOT / "eval" / "labels"
CHECKLIST = (
    ("real", "Is the gold defect a real defect (not a style preference)?"),
    ("diff_only", "Can it be inferred from the diff alone, without repo knowledge?"),
    ("location", "Do file and spans point at the defective lines?"),
    ("description", "Do root_cause and failure_path describe this defect, not another?"),
    ("no_telltale", "Is there no comment, name or scaffolding that gives the bug away?"),
    ("severity", "Is the severity consistent with the anchors in taxonomy.md?"),
)
CLEAN_CHECKLIST = (
    (
        "clean",
        "After reading it, do you believe this diff has no defect of severity medium or high?",
    ),
)


def ask(prompt: str, choices: str) -> str:
    """Read one key from ``choices`` (lowercase); repeat until valid."""
    while True:
        answer = input(f"{prompt} [{choices}] ").strip().lower()
        if len(answer) == 1 and answer in choices:
            return answer
        print(f"  answer one of: {', '.join(choices)}")


def show_blind(case: Case, index: int, total: int) -> None:
    """Print only what the reviewer model receives."""
    print("\n" + "=" * 100)
    print(f"case {index}/{total}  id={case.case_id}  (gold hidden)")
    print("=" * 100)
    print(number_diff(case.diff).text)


def phase_blind() -> dict[str, object]:
    """Ask the reviewer what they suspect before seeing the gold."""
    suspects = ask("Do you see a defect of severity medium or high?", "yn")
    note = ""
    if suspects == "y":
        note = input("  where and what (file:line, one line): ").strip()
    return {"blind_suspects_defect": suspects == "y", "blind_note": note}


def show_gold(case: Case) -> None:
    """Reveal the labels."""
    print("-" * 100)
    print(f"source={case.source}  family={case.family_id}  split={case.split}")
    if case.is_clean:
        print("GOLD: clean, no expected findings")
        return
    for g in case.expected_findings:
        where = "; ".join(f"{f} lines {[list(sp) for sp in spans]}" for f, spans in g.locations)
        print(f"GOLD {g.gold_id}: {where}  {g.category}/{g.severity}")
        print(textwrap.indent(textwrap.fill("root_cause: " + g.root_cause, 96), "  "))
        print(textwrap.indent(textwrap.fill("failure_path: " + g.failure_path, 96), "  "))


def phase_checklist(case: Case) -> dict[str, object]:
    """Run the checklist and collect the verdict."""
    items = CLEAN_CHECKLIST if case.is_clean else CHECKLIST
    answers = {key: ask(question, "ynu") for key, question in items}
    verdict = ask("Verdict: (k)eep, (f)ix label, (d)rop case", "kfd")
    comment = input("  comment (optional): ").strip()
    return {"checklist": answers, "verdict": verdict, "comment": comment}


def already_done(path: Path) -> set[str]:
    """Case ids already recorded in ``path``, so a review can be resumed."""
    if not path.exists():
        return set()
    return {json.loads(line)["case_id"] for line in path.read_text().splitlines() if line}


def main(argv: list[str] | None = None) -> int:
    """Walk the cases in a seeded random order and append one JSON line per reviewed case."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass", dest="pass_no", required=True, help="1, 2, or a label like 1b")
    parser.add_argument("--split", default=None)
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument("--reviewer", default="miguel")
    args = parser.parse_args(argv)

    cases = [c for c in load_dataset() if c.active and (not args.split or c.split == args.split)]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.case_id in wanted]
    random.Random(f"{args.pass_no}-{len(cases)}").shuffle(cases)
    out = LABELS_DIR / f"review-pass{args.pass_no}.jsonl"
    done = already_done(out)
    todo = [c for c in cases if c.case_id not in done]
    print(f"{len(todo)} case(s) to review, {len(done)} already in {out.name}")

    for index, case in enumerate(todo, 1):
        show_blind(case, index, len(todo))
        record: dict[str, object] = {
            "case_id": case.case_id,
            "pass": args.pass_no,
            "reviewer": args.reviewer,
            "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "diff_sha256": case.diff_sha256,
        }
        record.update(phase_blind())
        show_gold(case)
        record.update(phase_checklist(case))
        with out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        if index < len(todo) and ask("Next case?", "yq") == "q":
            break
    print(f"\nsaved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
