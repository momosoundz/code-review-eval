"""Load and validate the labeled dataset: one directory per case with diff, gold and metadata."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reviewer.diffs import number_diff

CASES_DIR = Path(__file__).resolve().parents[1] / "dataset" / "cases"
SPLITS = ("dev", "release")
SOURCES = ("seeded", "real_reversed", "clean", "discovered")
STATUSES = ("active", "deprecated")
SEVERITIES = ("high", "medium", "low")
CATEGORIES = (
    "boundary",
    "null_or_missing_value",
    "wrong_operator_or_operand",
    "wrong_condition",
    "wrong_variable_or_argument",
    "error_handling",
    "resource_leak",
    "concurrency",
    "unsafe_input",
    "wrong_literal_or_default",
)


class DatasetError(ValueError):
    """A case violates the dataset contract."""


@dataclass(frozen=True)
class GoldFinding:
    """One labeled defect: where it is, what it is, and how it fails."""

    gold_id: str
    file: str
    spans: tuple[tuple[int, int], ...]
    category: str
    severity: str
    root_cause: str
    failure_path: str
    needs_context_beyond_diff: bool


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
    decoys: tuple[dict[str, Any], ...] = ()

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
        """Gold findings with severity high; the gate metric is computed over these."""
        return tuple(g for g in self.expected_findings if g.severity == "high")


def _require(condition: bool, case_id: str, message: str) -> None:
    if not condition:
        raise DatasetError(f"{case_id}: {message}")


def _parse_gold(raw: dict[str, Any], case_id: str, valid: dict[str, set[int]]) -> GoldFinding:
    gold_id = str(raw["gold_id"])
    path = str(raw["file"])
    _require(path in valid, case_id, f"{gold_id} cites {path!r}, not in the diff")
    spans = tuple((int(a), int(b)) for a, b in raw["spans"])
    _require(bool(spans), case_id, f"{gold_id} has no spans")
    for start, end in spans:
        inside = start <= end and all(n in valid[path] for n in range(start, end + 1))
        _require(inside, case_id, f"{gold_id} span {start}-{end} is outside the diff hunks")
    _require(raw["category"] in CATEGORIES, case_id, f"{gold_id} has unknown category")
    _require(raw["severity"] in SEVERITIES, case_id, f"{gold_id} has unknown severity")
    return GoldFinding(
        gold_id=gold_id,
        file=path,
        spans=spans,
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


def load_case(case_dir: Path) -> Case:
    """Load one case directory, validating it against the contract.

    Raises:
        DatasetError: With the case id and the first violated rule.
    """
    case_id = case_dir.name
    diff = (case_dir / "diff.patch").read_text()
    expected = json.loads((case_dir / "expected.json").read_text())
    meta = json.loads((case_dir / "meta.json").read_text())
    declared = expected.get("case_id", case_id)
    _require(declared == case_id, case_id, f"case_id {declared!r} does not match directory")
    _check_meta(meta, case_id)
    try:
        valid = number_diff(diff).valid_lines
    except ValueError as exc:
        raise DatasetError(f"{case_id}: {exc}") from exc
    golds = tuple(_parse_gold(g, case_id, valid) for g in expected.get("expected_findings", []))
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
        decoys=tuple(expected.get("decoys", [])),
    )


def load_dataset(cases_dir: Path = CASES_DIR) -> list[Case]:
    """Load every case directory under ``cases_dir``, sorted by id."""
    return [load_case(d) for d in sorted(cases_dir.iterdir()) if d.is_dir()]


def gold_hash(cases: list[Case]) -> str:
    """Hash of the scoring fields of every case: ids, diffs, spans, severities, splits, status."""
    rows = [
        {
            "case_id": c.case_id,
            "diff_sha256": c.diff_sha256,
            "split": c.split,
            "status": c.status,
            "family_id": c.family_id,
            "gold": [
                [g.gold_id, g.file, list(g.spans), g.category, g.severity, g.root_cause]
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
        except (DatasetError, KeyError, json.JSONDecodeError, FileNotFoundError) as exc:
            problems.append(f"{case_dir.name}: {exc}")
    return problems


def _summary(cases: list[Case]) -> str:
    active = [c for c in cases if c.active]
    by = lambda key: sorted({getattr(c, key) for c in active})  # noqa: E731
    lines = [f"{len(active)} active cases, gold_hash {gold_hash(cases)}"]
    for split in by("split"):
        subset = [c for c in active if c.split == split]
        clean = sum(c.is_clean for c in subset)
        golds = sum(len(c.expected_findings) for c in subset)
        lines.append(f"  {split}: {len(subset)} cases, {clean} clean, {golds} gold findings")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``validate`` exits non-zero when any case is invalid and prints a summary otherwise."""
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] != ["validate"]:
        print("usage: python -m eval.harness.dataset validate", file=sys.stderr)
        return 2
    problems = validate_dataset()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(_summary(load_dataset()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
