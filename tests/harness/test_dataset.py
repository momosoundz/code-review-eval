import json
from pathlib import Path

import pytest

from eval.harness.dataset import (
    Case,
    DatasetError,
    gold_hash,
    load_case,
    load_dataset,
    validate_dataset,
)

DIFF = """\
diff --git a/app/orders.py b/app/orders.py
--- a/app/orders.py
+++ b/app/orders.py
@@ -40,5 +40,6 @@ def get_order(order_id: int, tenant_id: int) -> Order:
     session = get_session()
-    order = session.query(Order).filter_by(id=order_id, tenant_id=tenant_id).one()
+    order = session.query(Order).filter_by(id=order_id).one()
+    log.debug("order %s", order_id)
     if order is None:
         raise NotFound(order_id)
     return order
"""


def write_case(root: Path, case_id: str, expected: dict, meta: dict, diff: str = DIFF) -> Path:
    case_dir = root / case_id
    case_dir.mkdir(parents=True)
    (case_dir / "diff.patch").write_text(diff)
    (case_dir / "expected.json").write_text(json.dumps(expected))
    (case_dir / "meta.json").write_text(json.dumps(meta))
    return case_dir


def gold(**overrides: object) -> dict:
    base = {
        "gold_id": "crv-0001-g1",
        "file": "app/orders.py",
        "spans": [[41, 41]],
        "category": "null_or_missing_value",
        "severity": "high",
        "root_cause": "the lookup no longer filters by tenant_id",
        "failure_path": "tenant A asks for an order owned by tenant B and gets it",
        "needs_context_beyond_diff": False,
    }
    base.update(overrides)
    return base


def meta(**overrides: object) -> dict:
    base = {
        "family_id": "fam-001",
        "split": "dev",
        "source": "seeded",
        "provenance": {"repo": "example", "base_sha": "abc"},
        "status": "active",
    }
    base.update(overrides)
    return base


def test_loads_a_valid_case(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0001", {"expected_findings": [gold()]}, meta())
    case = load_case(tmp_path / "crv-0001")
    assert isinstance(case, Case)
    assert case.case_id == "crv-0001"
    assert case.expected_findings[0].spans == ((41, 41),)
    assert case.diff_sha256


def test_clean_case_has_no_findings(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0002", {"expected_findings": []}, meta(source="clean"))
    case = load_case(tmp_path / "crv-0002")
    assert case.expected_findings == ()
    assert case.is_clean


def test_rejects_span_outside_diff(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0003", {"expected_findings": [gold(spans=[[90, 91]])]}, meta())
    with pytest.raises(DatasetError, match="outside the diff"):
        load_case(tmp_path / "crv-0003")


def test_rejects_unknown_file(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0004", {"expected_findings": [gold(file="x.py")]}, meta())
    with pytest.raises(DatasetError, match="not in the diff"):
        load_case(tmp_path / "crv-0004")


def test_rejects_bad_category(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0005", {"expected_findings": [gold(category="weird")]}, meta())
    with pytest.raises(DatasetError, match="category"):
        load_case(tmp_path / "crv-0005")


def test_rejects_bad_split(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0006", {"expected_findings": []}, meta(split="test"))
    with pytest.raises(DatasetError, match="split"):
        load_case(tmp_path / "crv-0006")


def test_rejects_clean_source_with_findings(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0007", {"expected_findings": [gold()]}, meta(source="clean"))
    with pytest.raises(DatasetError, match="clean"):
        load_case(tmp_path / "crv-0007")


def test_rejects_duplicate_gold_ids(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0008", {"expected_findings": [gold(), gold()]}, meta())
    with pytest.raises(DatasetError, match="duplicate gold_id"):
        load_case(tmp_path / "crv-0008")


def test_deprecated_case_is_loaded_but_inactive(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0009",
        {"expected_findings": []},
        meta(source="clean", status="deprecated", deprecated_reason="diff had a real bug"),
    )
    cases = load_dataset(tmp_path)
    assert [c.case_id for c in cases] == ["crv-0009"]
    assert not cases[0].active


def test_deprecated_without_reason_fails(tmp_path: Path) -> None:
    write_case(
        tmp_path, "crv-0010", {"expected_findings": []}, meta(source="clean", status="deprecated")
    )
    with pytest.raises(DatasetError, match="deprecated_reason"):
        load_case(tmp_path / "crv-0010")


def test_gold_hash_ignores_notes_but_not_spans(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0011", {"expected_findings": [gold()]}, meta())
    first = gold_hash(load_dataset(tmp_path))
    (tmp_path / "crv-0011" / "expected.json").write_text(
        json.dumps({"expected_findings": [gold()], "notes": "reviewed twice"})
    )
    assert gold_hash(load_dataset(tmp_path)) == first
    (tmp_path / "crv-0011" / "expected.json").write_text(
        json.dumps({"expected_findings": [gold(spans=[[42, 42]])]})
    )
    assert gold_hash(load_dataset(tmp_path)) != first


def test_validate_reports_every_problem(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0012", {"expected_findings": [gold(file="x.py")]}, meta())
    write_case(tmp_path, "crv-0013", {"expected_findings": []}, meta(source="clean"))
    problems = validate_dataset(tmp_path)
    assert len(problems) == 1
    assert "crv-0012" in problems[0]


def test_case_id_must_match_directory(tmp_path: Path) -> None:
    write_case(
        tmp_path, "crv-0014", {"expected_findings": [], "case_id": "crv-9999"}, meta(source="clean")
    )
    with pytest.raises(DatasetError, match="case_id"):
        load_case(tmp_path / "crv-0014")
