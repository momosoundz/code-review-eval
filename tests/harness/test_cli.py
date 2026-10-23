import json
from pathlib import Path

import pytest

from eval.harness import compare, dataset, score
from reviewer import review
from tests.conftest import SAMPLE_DIFF, gold, meta, write_case
from tests.harness.test_compare import big_rows, write_run


def test_compare_cli_exit_codes(tmp_path: Path) -> None:
    write_run(tmp_path, "a", big_rows())
    write_run(tmp_path, "b", big_rows())
    write_run(tmp_path, "c", big_rows(flip={f"c{i}" for i in range(12)}))
    flags = ["--runs-dir", str(tmp_path)]
    assert compare.main(["--a", "a", "--b", "b", *flags]) == 0
    assert compare.main(["--a", "a", "--b", "c", *flags]) in (1, 2)
    assert compare.main(["--a", "a", "--b", "missing", *flags]) == 3


def test_score_cli_refuses_to_judge_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cases = tmp_path / "cases"
    write_case(cases, "crv-0001", {"expected_findings": [gold()]}, meta())
    digest = dataset.gold_hash(dataset.load_dataset(cases))
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "manifest.json").write_text(
        json.dumps(
            {
                "run": "r",
                "model": "claude-haiku-5-5",
                "prompt_id": "p",
                "k": 1,
                "reviewer_version": "p-low",
                "case_ids": ["crv-0001"],
                "gold_hash": digest,
            }
        )
    )
    resp = tmp_path / "responses" / "claude-haiku-5-5" / "p-low" / "crv-0001" / "crv-0001-k1.json"
    resp.parent.mkdir(parents=True)
    finding = {
        "file": "app/orders.py",
        "line": 41,
        "severity": "high",
        "category": "other",
        "description": "d",
        "rationale": "r",
        "confidence": 0.9,
    }
    result = {
        "findings": [finding],
        "no_output": False,
        "error": None,
        "dropped": [],
        "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0},
        "elapsed_ms": 1,
        "model": "claude-haiku-5-5",
        "prompt_id": "p",
    }
    resp.write_text(json.dumps({"result": result, "raw": {}}))
    flags = ["--runs-dir", str(tmp_path), "--cases-dir", str(cases)]
    assert score.main(["--run", "r", *flags]) == 3
    assert "no cached verdict" in capsys.readouterr().err
    assert not (tmp_path / "r" / "summary.json").exists()


def test_review_cli_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        input_tokens = 1
        output_tokens = 0

    class Refusal:
        def __init__(self) -> None:
            self.content: list = []
            self.stop_reason = "refusal"
            self.usage = Usage()

        def model_dump(self) -> dict:
            return {"content": []}

    monkeypatch.setattr(review, "_create_message", lambda **kw: Refusal())
    patch = tmp_path / "d.patch"
    patch.write_text(SAMPLE_DIFF)
    assert review.main(["--diff", str(patch), "--out", str(tmp_path / "f.json")]) == 2
    patch.write_text(SAMPLE_DIFF + "+" + "x" * 60_000 + "\n")
    assert review.main(["--diff", str(patch), "--out", str(tmp_path / "f.json")]) == 1


def test_dataset_validate_cli(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    write_case(cases, "crv-0001", {"expected_findings": [gold(file="nope.py")]}, meta())
    assert dataset.main(["validate", "--cases-dir", str(cases)]) == 1
    assert dataset.main(["other"]) == 2
