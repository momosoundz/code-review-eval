import json
from pathlib import Path
from typing import Any

import pytest

from eval.harness import judge as judge_mod
from eval.harness.dataset import GoldFinding
from eval.harness.judge import Judge, JudgeResponseError, JudgeUnavailableError, pair_key

GOLD = GoldFinding(
    "crv-0002-g1",
    (("src/rag.py", ((55, 55),)),),
    "null_or_missing_value",
    "medium",
    "max() without default",
    "empty retrieval crashes",
    False,
)
FINDING = {
    "file": "src/rag.py",
    "line": 55,
    "severity": "high",
    "category": "boundary",
    "description": "max over empty list raises",
    "rationale": "r",
    "confidence": 0.8,
}


class FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeResponse:
    def __init__(self, verdict: str) -> None:
        self.content = [FakeBlock(json.dumps({"critique": "same mechanism", "verdict": verdict}))]
        self.stop_reason = "end_turn"
        self.usage = type("U", (), {"input_tokens": 300, "output_tokens": 40})()


def test_pair_key_depends_on_text_not_metadata() -> None:
    k1 = pair_key("claude-opus-5-5", "ph", "crv-0002", GOLD, FINDING)
    k2 = pair_key("claude-opus-5-5", "ph", "crv-0002", GOLD, {**FINDING, "severity": "low"})
    k3 = pair_key("claude-opus-5-5", "ph", "crv-0002", GOLD, {**FINDING, "description": "other"})
    assert k1 == k2 and k1 != k3


def test_judge_calls_model_once_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> FakeResponse:
        calls.append(kwargs)
        return FakeResponse("match")

    monkeypatch.setattr(judge_mod, "_create_message", fake)
    j = Judge(verdicts_dir=tmp_path)
    assert j.decide("crv-0002", FINDING, GOLD) == "match"
    assert j.decide("crv-0002", FINDING, GOLD) == "match"
    assert len(calls) == 1
    assert "severity" not in calls[0]["messages"][0]["content"]
    assert "boundary" not in calls[0]["messages"][0]["content"]
    written = list(tmp_path.rglob("*.json"))
    assert len(written) == 1
    assert written[0].parent.name == "crv-0002" and written[0].name.startswith("crv-0002-g1-")


def test_offline_mode_raises_when_verdict_missing(tmp_path: Path) -> None:
    j = Judge(verdicts_dir=tmp_path, offline=True)
    with pytest.raises(JudgeUnavailableError, match="no cached verdict"):
        j.decide("crv-0002", FINDING, GOLD)


def test_offline_mode_reads_cached_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge_mod, "_create_message", lambda **kw: FakeResponse("no_match"))
    Judge(verdicts_dir=tmp_path).decide("crv-0002", FINDING, GOLD)
    assert (
        Judge(verdicts_dir=tmp_path, offline=True).decide("crv-0002", FINDING, GOLD) == "no_match"
    )


def test_invalid_response_raises_and_caches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = FakeResponse("match")
    bad.content = [FakeBlock("not json")]
    monkeypatch.setattr(judge_mod, "_create_message", lambda **kw: bad)
    with pytest.raises(JudgeResponseError, match="invalid JSON"):
        Judge(verdicts_dir=tmp_path).decide("crv-0002", FINDING, GOLD)
    assert list(tmp_path.rglob("*.json")) == []


def test_unknown_verdict_is_returned_but_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judge_mod, "_create_message", lambda **kw: FakeResponse("unknown"))
    assert Judge(verdicts_dir=tmp_path).decide("crv-0002", FINDING, GOLD) == "unknown"
    assert list(tmp_path.rglob("*.json")) == []
