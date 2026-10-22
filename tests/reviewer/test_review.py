import json
from pathlib import Path
from typing import Any

import pytest

from reviewer import review
from reviewer.review import InvalidFindingsError, normalize_findings, prompt_id, run_review
from tests.reviewer.test_diffs import SAMPLE


class FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeUsage:
    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 0


class FakeResponse:
    def __init__(self, payload: Any, stop_reason: str = "end_turn") -> None:
        self.content = [FakeBlock(json.dumps(payload))]
        self.stop_reason = stop_reason
        self.usage = FakeUsage()
        self.model = "claude-haiku-5-5"
        self.id = "msg_test"

    def model_dump(self) -> dict[str, Any]:
        return {"id": self.id, "stop_reason": self.stop_reason, "model": self.model}


def good_payload() -> dict[str, Any]:
    return {
        "findings": [
            {
                "file": "./app/orders.py",
                "line": 41,
                "severity": "high",
                "category": "missing_check",
                "description": "The query no longer filters by tenant_id.",
                "rationale": "Any tenant can fetch another tenant's order by id.",
                "confidence": 0.9,
            }
        ]
    }


def test_normalize_strips_leading_dot_slash() -> None:
    numbered = review.number_diff(SAMPLE)
    findings = normalize_findings(good_payload(), numbered)
    assert findings[0]["file"] == "app/orders.py"


def test_rejects_finding_on_unknown_file() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    payload["findings"][0]["file"] = "app/other.py"
    with pytest.raises(InvalidFindingsError, match="not in the diff"):
        normalize_findings(payload, numbered)


def test_rejects_line_outside_hunks() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    payload["findings"][0]["line"] = 400
    with pytest.raises(InvalidFindingsError, match="outside"):
        normalize_findings(payload, numbered)


def test_rejects_bad_severity() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    payload["findings"][0]["severity"] = "critical"
    with pytest.raises(InvalidFindingsError, match="severity"):
        normalize_findings(payload, numbered)


def test_empty_findings_is_valid() -> None:
    numbered = review.number_diff(SAMPLE)
    assert normalize_findings({"findings": []}, numbered) == []


def test_run_review_writes_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_create(**kwargs: Any) -> FakeResponse:
        calls.append(kwargs)
        return FakeResponse(good_payload())

    monkeypatch.setattr(review, "_create_message", fake_create)
    out = tmp_path / "findings.json"
    result = run_review(SAMPLE, out_path=out, raw_out=tmp_path / "raw.json")
    written = json.loads(out.read_text())
    assert written["findings"][0]["file"] == "app/orders.py"
    assert written["prompt_id"] == prompt_id()
    assert result.no_output is False
    assert calls[0]["model"] == review.DEFAULT_MODEL
    assert "output_config" in calls[0]
    assert "tools" not in calls[0]


def test_run_review_marks_refusal_as_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_create(**kwargs: Any) -> FakeResponse:
        resp = FakeResponse({}, stop_reason="refusal")
        resp.content = []
        return resp

    monkeypatch.setattr(review, "_create_message", fake_create)
    result = run_review(SAMPLE, out_path=tmp_path / "f.json")
    assert result.no_output is True
    assert result.error is not None


def test_run_review_marks_invalid_json_as_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_create(**kwargs: Any) -> FakeResponse:
        resp = FakeResponse({})
        resp.content = [FakeBlock("not json")]
        return resp

    monkeypatch.setattr(review, "_create_message", fake_create)
    result = run_review(SAMPLE, out_path=tmp_path / "f.json")
    assert result.no_output is True


def test_prompt_id_changes_with_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    before = prompt_id()
    monkeypatch.setattr(review, "load_prompt", lambda: "different prompt")
    assert prompt_id() != before
