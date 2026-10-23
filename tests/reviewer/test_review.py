import json
from pathlib import Path
from typing import Any

import pytest

from reviewer import review
from reviewer.review import InvalidFindingsError, normalize_findings, prompt_id, run_review
from tests.conftest import SAMPLE_DIFF as SAMPLE


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
        content = [{"type": "thinking", "thinking": "", "signature": "opaque"}]
        content += [{"type": "text", "text": b.text} for b in self.content]
        return {
            "id": self.id,
            "stop_reason": self.stop_reason,
            "model": self.model,
            "content": content,
        }


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
    findings, dropped = normalize_findings(good_payload(), numbered)
    assert findings[0]["file"] == "app/orders.py" and dropped == []


def test_drops_finding_on_unknown_file_and_keeps_the_rest() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    bad = {**payload["findings"][0], "file": "app/other.py"}
    payload["findings"].append(bad)
    findings, dropped = normalize_findings(payload, numbered)
    assert len(findings) == 1 and len(dropped) == 1 and "not in the diff" in dropped[0]


def test_drops_line_outside_hunks() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    payload["findings"][0]["line"] = 400
    findings, dropped = normalize_findings(payload, numbered)
    assert findings == [] and "outside" in dropped[0]


def test_drops_bad_severity() -> None:
    numbered = review.number_diff(SAMPLE)
    payload = good_payload()
    payload["findings"][0]["severity"] = "critical"
    _, dropped = normalize_findings(payload, numbered)
    assert "severity" in dropped[0]


def test_payload_without_findings_list_is_invalid() -> None:
    numbered = review.number_diff(SAMPLE)
    with pytest.raises(InvalidFindingsError, match="findings"):
        normalize_findings({"items": []}, numbered)


def test_empty_findings_is_valid() -> None:
    numbered = review.number_diff(SAMPLE)
    assert normalize_findings({"findings": []}, numbered) == ([], [])


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
    assert calls[0]["model"] == review.MODEL
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


def test_raw_envelope_drops_thinking_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review, "_create_message", lambda **kw: FakeResponse(good_payload()))
    raw_out = tmp_path / "raw.json"
    run_review(SAMPLE, out_path=tmp_path / "f.json", raw_out=raw_out)
    raw = json.loads(raw_out.read_text())
    assert [b["type"] for b in raw["content"]] == ["text"]


def test_normalize_keeps_dotfile_directories() -> None:
    assert review._normalize_path("./.github/ci.yml") == ".github/ci.yml"
    assert review._normalize_path("b/.env.example") == ".env.example"
    assert review._normalize_path("app/orders.py") == "app/orders.py"
