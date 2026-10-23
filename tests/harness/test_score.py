import json
from pathlib import Path

import pytest

from eval.harness.collect import response_path, reviewer_version
from eval.harness.dataset import GoldFinding, load_dataset
from eval.harness.score import score_run, summarize, write_outputs
from tests.conftest import gold, meta, write_case

MODEL = "claude-haiku-5-5"


def finding(line: int = 41, severity: str = "high", category: str = "input_validation") -> dict:
    return {
        "file": "app/orders.py",
        "line": line,
        "severity": severity,
        "category": category,
        "description": "tenant filter missing",
        "rationale": "r",
        "confidence": 0.9,
    }


def write_response(
    runs: Path, case_id: str, k: int, findings: list[dict], no_output: bool = False
) -> None:
    path = response_path(runs, MODEL, reviewer_version("hunk_only", "low"), case_id, k)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "findings": findings,
        "no_output": no_output,
        "error": None,
        "dropped": [],
        "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0},
        "elapsed_ms": 900,
        "model": MODEL,
        "prompt_id": "p",
    }
    path.write_text(json.dumps({"result": result, "raw": {}}))


def write_manifest(runs: Path, run: str, case_ids: list[str], k: int) -> None:
    (runs / run).mkdir(parents=True, exist_ok=True)
    (runs / run / "manifest.json").write_text(
        json.dumps(
            {
                "run": run,
                "model": MODEL,
                "prompt_id": "p",
                "reviewer_version": reviewer_version("hunk_only", "low"),
                "k": k,
                "case_ids": case_ids,
                "gold_hash": "x",
                "effort": "low",
                "context_mode": "hunk_only",
            }
        )
    )


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path]:
    cases = tmp_path / "cases"
    write_case(cases, "crv-0001", {"expected_findings": []}, meta(source="clean", family_id="f1"))
    write_case(
        cases,
        "crv-0002",
        {"expected_findings": [gold(gold_id="crv-0002-g1")]},
        meta(family_id="f1"),
    )
    write_case(
        cases,
        "crv-0003",
        {"expected_findings": [gold(gold_id="crv-0003-g1", severity="medium")]},
        meta(family_id="f2", source="real_reversed"),
    )
    runs = tmp_path / "runs"
    write_response(runs, "crv-0001", 1, [])
    write_response(runs, "crv-0001", 2, [finding(severity="medium")])
    write_response(runs, "crv-0002", 1, [finding()])
    write_response(runs, "crv-0002", 2, [], no_output=True)
    write_response(runs, "crv-0003", 1, [finding(line=41, severity="low")])
    write_response(runs, "crv-0003", 2, [finding(line=41, severity="medium")])
    write_manifest(runs, "baseline", ["crv-0001", "crv-0002", "crv-0003"], k=2)
    return cases, runs


def always(case_id: str, f: dict, g: GoldFinding) -> str:
    return "match"


def test_rows_per_case_and_run(world: tuple[Path, Path]) -> None:
    cases, runs = world
    rows = score_run("baseline", load_dataset(cases), always, runs_dir=runs)
    assert len(rows) == 6
    by = {(r["case_id"], r["k"]): r for r in rows}
    assert by[("crv-0002", 1)]["tp"] == 1 and by[("crv-0002", 1)]["recall_high"] == 1.0
    assert by[("crv-0002", 2)]["no_output"] is True
    assert by[("crv-0002", 2)]["fn"] == 1 and by[("crv-0002", 2)]["recall_high"] == 0.0
    assert by[("crv-0001", 2)]["fp"] == 1 and by[("crv-0001", 2)]["clean_alarm"] == 1
    assert by[("crv-0001", 1)]["clean_alarm"] == 0
    assert by[("crv-0003", 1)]["recall_high"] is None


def test_summary_metrics(world: tuple[Path, Path]) -> None:
    cases, runs = world
    rows = score_run("baseline", load_dataset(cases), always, runs_dir=runs)
    summary = summarize(rows, load_dataset(cases), k=2)
    assert summary["recall_high"]["mean"] == 0.5
    assert summary["recall_high"]["all_k"] == 0.0
    assert summary["recall_high"]["n_cases"] == 1
    assert summary["clean_fp_rate"]["mean"] == 0.5
    assert summary["clean_fp_rate"]["n_cases"] == 1
    assert summary["precision_medium_plus"]["tp"] == 2
    assert summary["precision_medium_plus"]["fp"] == 1
    assert summary["no_output_rate"] == pytest.approx(1 / 6, abs=1e-4)
    assert summary["by_source"]["real_reversed"]["recall_all"]["mean"] == 1.0
    assert "wilson_case_runs" in summary["clean_fp_rate"]


def test_score_writes_files(world: tuple[Path, Path]) -> None:
    cases, runs = world
    rows = score_run("baseline", load_dataset(cases), always, runs_dir=runs)
    write_outputs("baseline", rows, summarize(rows, load_dataset(cases), k=2), runs_dir=runs)
    assert (runs / "baseline" / "scored.jsonl").exists()
    assert (
        json.loads((runs / "baseline" / "summary.json").read_text())["recall_high"]["mean"] == 0.5
    )


def test_missing_response_is_an_error(world: tuple[Path, Path]) -> None:
    cases, runs = world
    write_manifest(runs, "partial", ["crv-0001", "crv-0002", "crv-0003"], k=3)
    with pytest.raises(FileNotFoundError, match="crv-0001"):
        score_run("partial", load_dataset(cases), always, runs_dir=runs)
