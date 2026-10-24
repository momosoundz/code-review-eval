"""Load and validate the labeled dataset: one directory per case with diff, gold and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.harness.config import GATED_SEVERITIES
from reviewer.config import CATEGORIES, SEVERITIES
from reviewer.diffs import NumberedDiff, number_diff

CASES_DIR = Path(__file__).resolve().parents[1] / "dataset" / "cases"
CASE_ID = re.compile(r"crv-\d{4}")
GOLD_ID = re.compile(r"crv-\d{4}-g\d+")
SPLITS = ("dev", "release")
SOURCES = ("seeded", "real_reversed", "clean", "discovered")
STATUSES = ("active", "deprecated")


class DatasetError(ValueError):
    """A case violates the dataset contract."""


Location = tuple[str, tuple[tuple[int, int], ...]]


@dataclass(frozen=True)
class GoldFinding:
    """One labeled defect: where it is, what it is, and how it fails.

    ``locations`` lists every place a correct finding may anchor, each a file with one or
    more post-change line spans. The first one is where the defect lives; the others are
    places where it manifests, such as a call site in another file.
    """

    gold_id: str
    locations: tuple[Location, ...]
    category: str
    severity: str
    root_cause: str
    failure_path: str
    needs_context_beyond_diff: bool

    @property
    def file(self) -> str:
        """The file of the primary location."""
        return self.locations[0][0]

    @property
    def spans(self) -> tuple[tuple[int, int], ...]:
        """The spans of the primary location."""
        return self.locations[0][1]


@dataclass(frozen=True)
class Case:
    """A diff plus its gold findings and metadata."""

    case_id: str
    diff: str
    diff_sha256: str
    expected_findings: tuple[GoldFinding, ...]
    family_id: str
    split: str
    source: str
    status: str
    commit_title: str | None = None

    @property
    def is_clean(self) -> bool:
        """True when the case carries no gold defect."""
        return not self.expected_findings

    @property
    def active(self) -> bool:
        """True when the case counts toward scores."""
        return self.status == "active"

    @property
    def high_gold(self) -> tuple[GoldFinding, ...]:
        """Gold findings with severity high (diagnostic slice)."""
        return tuple(g for g in self.expected_findings if g.severity == "high")

    @property
    def gated_gold(self) -> tuple[GoldFinding, ...]:
        """Gold findings of severity medium or high: the ones the gate metric counts."""
        return tuple(g for g in self.expected_findings if g.severity in GATED_SEVERITIES)

    @property
    def low_gold(self) -> tuple[GoldFinding, ...]:
        """Gold findings of severity low, reported in their own metric."""
        return tuple(g for g in self.expected_findings if g.severity == "low")


def _require(condition: bool, case_id: str, message: str) -> None:
    if not condition:
        raise DatasetError(f"{case_id}: {message}")


def _parse_location(
    raw: dict[str, Any], gold_id: str, case_id: str, numbered: NumberedDiff, primary: bool = True
) -> Location:
    valid, changed = numbered.valid_lines, numbered.changed_lines
    path = str(raw["file"])
    _require(path in valid, case_id, f"{gold_id} cites {path!r}, not in the diff")
    spans = tuple((int(a), int(b)) for a, b in raw["spans"])
    _require(bool(spans), case_id, f"{gold_id} has no spans for {path}")
    for start, end in spans:
        inside = start <= end and all(n in valid[path] for n in range(start, end + 1))
        _require(inside, case_id, f"{gold_id} span {start}-{end} is outside the diff hunks")
        touches = any(n in changed[path] for n in range(start, end + 1))
        _require(
            touches or not primary, case_id, f"{gold_id} span {start}-{end} touches no changed line"
        )
    return path, spans


def _parse_gold(raw: dict[str, Any], case_id: str, numbered: NumberedDiff) -> GoldFinding:
    gold_id = str(raw["gold_id"])
    _require(bool(GOLD_ID.fullmatch(gold_id)), case_id, f"gold_id {gold_id!r} must be <case_id>-gN")
    _require(
        gold_id.startswith(f"{case_id}-g"), case_id, f"gold_id {gold_id!r} belongs to another case"
    )
    primary = {"file": raw["file"], "spans": raw["spans"]}
    extra = raw.get("also", [])
    _require(isinstance(extra, list), case_id, f"{gold_id} 'also' must be a list of locations")
    locations = (
        _parse_location(primary, gold_id, case_id, numbered),
        *(_parse_location(loc, gold_id, case_id, numbered, primary=False) for loc in extra),
    )
    _require(len(set(locations)) == len(locations), case_id, f"{gold_id} repeats a location")
    _require(raw["category"] in CATEGORIES, case_id, f"{gold_id} has unknown category")
    _require(raw["severity"] in SEVERITIES, case_id, f"{gold_id} has unknown severity")
    return GoldFinding(
        gold_id=gold_id,
        locations=locations,
        category=str(raw["category"]),
        severity=str(raw["severity"]),
        root_cause=str(raw["root_cause"]),
        failure_path=str(raw["failure_path"]),
        needs_context_beyond_diff=bool(raw.get("needs_context_beyond_diff", False)),
    )


def _check_meta(meta: dict[str, Any], case_id: str) -> None:
    _require(meta.get("split") in SPLITS, case_id, f"split must be one of {SPLITS}")
    _require(meta.get("source") in SOURCES, case_id, f"source must be one of {SOURCES}")
    _require(meta.get("status", "active") in STATUSES, case_id, f"status must be one of {STATUSES}")
    if meta.get("status") == "deprecated":
        _require(bool(meta.get("deprecated_reason")), case_id, "deprecated needs deprecated_reason")
    _require(bool(meta.get("family_id")), case_id, "family_id is required")
    provenance = meta.get("provenance", {})
    _require(isinstance(provenance, dict), case_id, "provenance must be an object")
    title = provenance.get("commit_title")
    _require(
        title is None or (isinstance(title, str) and "\n" not in title and title.strip() != ""),
        case_id,
        "commit_title must be a non-empty single line when present",
    )


def load_case(case_dir: Path) -> Case:
    """Load one case directory, validating it against the contract.

    Raises:
        DatasetError: With the case id and the first violated rule.
    """
    case_id = case_dir.name
    _require(bool(CASE_ID.fullmatch(case_id)), case_id, "case directory must be named crv-NNNN")
    diff = (case_dir / "diff.patch").read_text()
    expected = json.loads((case_dir / "expected.json").read_text())
    meta = json.loads((case_dir / "meta.json").read_text())
    declared = expected.get("case_id", case_id)
    _require(declared == case_id, case_id, f"case_id {declared!r} does not match directory")
    _check_meta(meta, case_id)
    try:
        numbered = number_diff(diff)
    except ValueError as exc:
        raise DatasetError(f"{case_id}: {exc}") from exc
    raw_golds = expected.get("expected_findings")
    _require(
        isinstance(raw_golds, list),
        case_id,
        "expected.json needs an explicit expected_findings list ([] for a clean case)",
    )
    golds = tuple(_parse_gold(g, case_id, numbered) for g in raw_golds)
    ids = [g.gold_id for g in golds]
    _require(len(ids) == len(set(ids)), case_id, "duplicate gold_id")
    _require(meta["source"] != "clean" or not golds, case_id, "a clean case cannot have findings")
    return Case(
        case_id=case_id,
        diff=diff,
        diff_sha256=hashlib.sha256(diff.encode()).hexdigest(),
        expected_findings=golds,
        family_id=str(meta["family_id"]),
        split=str(meta["split"]),
        source=str(meta["source"]),
        status=str(meta.get("status", "active")),
        commit_title=meta.get("provenance", {}).get("commit_title"),
    )


def load_dataset(cases_dir: Path = CASES_DIR) -> list[Case]:
    """Load every case directory under ``cases_dir``, sorted by id."""
    return [load_case(d) for d in sorted(cases_dir.iterdir()) if d.is_dir()]


def gold_hash(cases: list[Case]) -> str:
    """Hash of every field that can change a score: ids, diffs, spans, labels, judge inputs."""
    rows = [
        {
            "case_id": c.case_id,
            "diff_sha256": c.diff_sha256,
            "split": c.split,
            "status": c.status,
            "family_id": c.family_id,
            "gold": [
                [
                    g.gold_id,
                    [[f, [list(sp) for sp in spans]] for f, spans in g.locations],
                    g.category,
                    g.severity,
                    g.root_cause,
                    g.failure_path,
                ]
                for g in c.expected_findings
            ],
        }
        for c in cases
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]


def validate_dataset(cases_dir: Path = CASES_DIR) -> list[str]:
    """Return one message per invalid case; an empty list means the dataset is valid."""
    problems: list[str] = []
    for case_dir in sorted(cases_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        try:
            load_case(case_dir)
        except (DatasetError, KeyError, TypeError, json.JSONDecodeError, FileNotFoundError) as exc:
            problems.append(f"{case_dir.name}: {exc}")
    return problems


def _summary(cases: list[Case]) -> str:
    active = [c for c in cases if c.active]
    lines = [f"{len(active)} active cases, gold_hash {gold_hash(cases)}"]
    for split in sorted({c.split for c in active}):
        subset = [c for c in active if c.split == split]
        clean = sum(c.is_clean for c in subset)
        golds = sum(len(c.expected_findings) for c in subset)
        lines.append(f"  {split}: {len(subset)} cases, {clean} clean, {golds} gold findings")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``validate [--cases-dir DIR]``: exit 1 when any case is invalid, 2 on usage errors."""
    parser = argparse.ArgumentParser(description="Validate the dataset.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not args.cases_dir.is_dir():
        print(f"not a directory: {args.cases_dir}", file=sys.stderr)
        return 2
    problems = validate_dataset(args.cases_dir)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(_summary(load_dataset(args.cases_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
