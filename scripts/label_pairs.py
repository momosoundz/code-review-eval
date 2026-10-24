"""Terminal tool for the human labels that calibrate the match judge.

Every cached judge verdict is one (finding, gold) pair. The tool samples pairs from the verdict
store, shows the human exactly what the judge saw (the labeled defect and the finding's text,
never the judge's verdict, the model, or the run), and asks one question: do they describe the
same defect? Every answer is appended to ``eval/labels/pair-labels.jsonl``; nothing is edited.

Sampling: every ``no_match`` verdict, plus ``--per-gold`` ``match`` verdicts per gold defect,
drawn with a fixed seed. The store is dominated by matches because the location gate runs
first, so an even sample would barely test the judge's rejections.

Usage:
    uv run python scripts/label_pairs.py [--per-gold 2] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eval.harness.config import ROOT
from eval.harness.dataset import load_dataset
from eval.harness.judge import JUDGE_MODEL, VERDICTS_DIR, judge_prompt_hash
from reviewer.diffs import number_diff

OUT_PATH = ROOT / "eval" / "labels" / "pair-labels.jsonl"
LABELS = {"s": "same", "d": "different", "u": "unsure"}


@dataclass(frozen=True)
class Pair:
    """One cached judge verdict, identified by its file."""

    case_id: str
    gold_id: str
    key: str
    input: str
    verdict: str

    @property
    def pair_id(self) -> str:
        """``<gold>-<key>``, the verdict file's stem."""
        return f"{self.gold_id}-{self.key}"


def load_pairs(verdicts_dir: Path, version: str) -> list[Pair]:
    """Every verdict cached under ``version``, sorted by file path."""
    pairs = []
    for path in sorted((verdicts_dir / version).glob("*/*.json")):
        record = json.loads(path.read_text())
        key = path.stem.removeprefix(record["gold_id"] + "-")
        pairs.append(
            Pair(record["case_id"], record["gold_id"], key, record["input"], record["verdict"])
        )
    return pairs


def sample_pairs(pairs: list[Pair], per_gold: int, seed: int) -> list[Pair]:
    """All ``no_match`` pairs plus ``per_gold`` ``match`` pairs per gold, shuffled with ``seed``."""
    rng = random.Random(seed)
    chosen = [p for p in pairs if p.verdict == "no_match"]
    by_gold: dict[str, list[Pair]] = {}
    for p in pairs:
        if p.verdict == "match":
            by_gold.setdefault(p.gold_id, []).append(p)
    for gold_id in sorted(by_gold):
        matches = by_gold[gold_id]
        chosen += rng.sample(matches, min(per_gold, len(matches)))
    rng.shuffle(chosen)
    return chosen


def already_done(path: Path) -> set[tuple[str, str]]:
    """``(pair_id, judge_version)`` already labeled, so a session can resume.

    A truncated last line (the process died mid-write) is skipped, not fatal.
    """
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        done.add((record["pair_id"], record["judge_version"]))
    return done


def ask(prompt: str, choices: str) -> str:
    """Read one key from ``choices``; repeat until valid."""
    while True:
        answer = input(f"{prompt} [{choices}] ").strip().lower()
        if len(answer) == 1 and answer in choices:
            return answer
        print(f"  answer one of: {', '.join(choices)}")


def main(argv: list[str] | None = None) -> int:
    """Walk the sampled pairs and append one JSON line per label."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-gold", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--labeler", default="miguel")
    parser.add_argument("--verdicts-dir", type=Path, default=VERDICTS_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    version = f"{JUDGE_MODEL}-{judge_prompt_hash()}"
    sampled = sample_pairs(load_pairs(args.verdicts_dir, version), args.per_gold, args.seed)
    done = already_done(args.out)
    todo = [p for p in sampled if (p.pair_id, version) not in done]
    diffs = {c.case_id: c.diff for c in load_dataset()}
    print(f"{len(todo)} pair(s) to label, {len(done)} already in {args.out.name}")
    for index, pair in enumerate(todo, 1):
        print("\n" + "=" * 100)
        print(f"pair {index}/{len(todo)}  case {pair.case_id}  (judge verdict hidden)")
        print("=" * 100)
        print(textwrap.indent(pair.input, "  "))
        answer = ask("Same defect? (s)ame, (d)ifferent, (u)nsure, (v)iew the diff", "sduv")
        if answer == "v":
            print(number_diff(diffs[pair.case_id]).text)
            answer = ask("Same defect? (s)ame, (d)ifferent, (u)nsure", "sdu")
        record = {
            "pair_id": pair.pair_id,
            "case_id": pair.case_id,
            "gold_id": pair.gold_id,
            "judge_version": version,
            "label": LABELS[answer],
            "comment": input("  comment (optional): ").strip(),
            "labeler": args.labeler,
            "labeled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with args.out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        if index < len(todo) and ask("Next pair?", "yq") == "q":
            break
    print(f"\nsaved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
