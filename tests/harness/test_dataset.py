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
from tests.conftest import gold, meta, write_case


def test_loads_a_valid_case(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0001", {"expected_findings": [gold(gold_id="crv-0001-g1")]}, meta())
    case = load_case(tmp_path / "crv-0001")
    assert isinstance(case, Case)
    assert case.case_id == "crv-0001"
    assert case.expected_findings[0].spans == ((41, 41),)
    assert case.expected_findings[0].locations == (("app/orders.py", ((41, 41),)),)
    assert case.diff_sha256


def test_clean_case_has_no_findings(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0002", {"expected_findings": []}, meta(source="clean"))
    case = load_case(tmp_path / "crv-0002")
    assert case.expected_findings == ()
    assert case.is_clean


def test_rejects_span_outside_diff(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0003",
        {"expected_findings": [gold(gold_id="crv-0003-g1", spans=[[90, 91]])]},
        meta(),
    )
    with pytest.raises(DatasetError, match="outside the diff"):
        load_case(tmp_path / "crv-0003")


def test_rejects_unknown_file(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0004",
        {"expected_findings": [gold(gold_id="crv-0004-g1", file="x.py")]},
        meta(),
    )
    with pytest.raises(DatasetError, match="not in the diff"):
        load_case(tmp_path / "crv-0004")


def test_rejects_bad_category(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0005",
        {"expected_findings": [gold(gold_id="crv-0005-g1", category="weird")]},
        meta(),
    )
    with pytest.raises(DatasetError, match="category"):
        load_case(tmp_path / "crv-0005")


def test_rejects_bad_split(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0006", {"expected_findings": []}, meta(split="test"))
    with pytest.raises(DatasetError, match="split"):
        load_case(tmp_path / "crv-0006")


def test_rejects_clean_source_with_findings(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0007",
        {"expected_findings": [gold(gold_id="crv-0007-g1")]},
        meta(source="clean"),
    )
    with pytest.raises(DatasetError, match="clean"):
        load_case(tmp_path / "crv-0007")


def test_rejects_duplicate_gold_ids(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0008",
        {"expected_findings": [gold(gold_id="crv-0008-g1"), gold(gold_id="crv-0008-g1")]},
        meta(),
    )
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
    write_case(tmp_path, "crv-0011", {"expected_findings": [gold(gold_id="crv-0011-g1")]}, meta())
    first = gold_hash(load_dataset(tmp_path))
    (tmp_path / "crv-0011" / "expected.json").write_text(
        json.dumps({"expected_findings": [gold(gold_id="crv-0011-g1")], "notes": "reviewed twice"})
    )
    assert gold_hash(load_dataset(tmp_path)) == first
    (tmp_path / "crv-0011" / "expected.json").write_text(
        json.dumps({"expected_findings": [gold(gold_id="crv-0011-g1", spans=[[42, 42]])]})
    )
    assert gold_hash(load_dataset(tmp_path)) != first


def test_validate_reports_every_problem(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        "crv-0012",
        {"expected_findings": [gold(gold_id="crv-0012-g1", file="x.py")]},
        meta(),
    )
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


def test_also_locations_are_validated_and_hashed(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    extra = tmp_path / "extra"
    write_case(plain, "crv-0020", {"expected_findings": [gold(gold_id="crv-0020-g1")]}, meta())
    with_also = gold(gold_id="crv-0020-g1", also=[{"file": "app/orders.py", "spans": [[42, 42]]}])
    write_case(extra, "crv-0020", {"expected_findings": [with_also]}, meta())
    case = load_case(extra / "crv-0020")
    assert len(case.expected_findings[0].locations) == 2
    assert gold_hash([case]) != gold_hash([load_case(plain / "crv-0020")])


def test_also_rejects_bad_shapes(tmp_path: Path) -> None:
    bad_span = gold(gold_id="crv-0021-g1", also=[{"file": "app/orders.py", "spans": [[900, 900]]}])
    write_case(tmp_path, "crv-0021", {"expected_findings": [bad_span]}, meta())
    with pytest.raises(DatasetError, match="outside the diff"):
        load_case(tmp_path / "crv-0021")
    dup = gold(gold_id="crv-0022-g1", also=[{"file": "app/orders.py", "spans": [[41, 41]]}])
    write_case(tmp_path, "crv-0022", {"expected_findings": [dup]}, meta())
    with pytest.raises(DatasetError, match="repeats"):
        load_case(tmp_path / "crv-0022")
    not_list = gold(gold_id="crv-0023-g1", also={"file": "x"})
    write_case(tmp_path, "crv-0023", {"expected_findings": [not_list]}, meta())
    with pytest.raises(DatasetError, match="must be a list"):
        load_case(tmp_path / "crv-0023")


def test_ids_are_validated(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0030", {"expected_findings": [gold(gold_id="../../x")]}, meta())
    with pytest.raises(DatasetError, match="gold_id"):
        load_case(tmp_path / "crv-0030")
    write_case(tmp_path, "crv-0031", {"expected_findings": [gold(gold_id="crv-0099-g1")]}, meta())
    with pytest.raises(DatasetError, match="another case"):
        load_case(tmp_path / "crv-0031")
    write_case(tmp_path, "weird", {"expected_findings": []}, meta(source="clean"))
    with pytest.raises(DatasetError, match="crv-NNNN"):
        load_case(tmp_path / "weird")


def test_span_must_touch_a_changed_line(tmp_path: Path) -> None:
    ctx_only = gold(gold_id="crv-0040-g1", spans=[[45, 45]])
    write_case(tmp_path, "crv-0040", {"expected_findings": [ctx_only]}, meta())
    with pytest.raises(DatasetError, match="touches no changed line"):
        load_case(tmp_path / "crv-0040")
    removal_only = """\
diff --git a/app/orders.py b/app/orders.py
--- a/app/orders.py
+++ b/app/orders.py
@@ -40,4 +40,3 @@ def get_order(order_id: int, tenant_id: int) -> Order:
     session = get_session()
-    check_tenant(order_id, tenant_id)
     order = session.query(Order).filter_by(id=order_id).one()
     return order
"""
    after_removal = gold(gold_id="crv-0041-g1", spans=[[41, 41]])
    write_case(
        tmp_path, "crv-0041", {"expected_findings": [after_removal]}, meta(), diff=removal_only
    )
    assert load_case(tmp_path / "crv-0041").expected_findings[0].spans == ((41, 41),)


def test_missing_expected_findings_key_is_not_a_clean_case(tmp_path: Path) -> None:
    write_case(tmp_path, "crv-0001", {}, meta(source="clean"))
    with pytest.raises(DatasetError, match="expected_findings"):
        load_case(tmp_path / "crv-0001")
