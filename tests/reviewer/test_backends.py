import json
from pathlib import Path
from typing import Any

import pytest

from reviewer import backends, review
from reviewer.backends import BackendUnavailableError, Completion, complete, is_codex
from tests.reviewer.test_review import SAMPLE, FakeResponse, good_payload


def test_model_prefix_selects_the_codex_backend() -> None:
    assert is_codex("codex-gpt-6.1-sol") and not is_codex("claude-haiku-5-5")


def test_codex_completion_parses_last_message_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], prompt: str, cwd: Path) -> tuple[int, str, str | None]:
        seen["args"] = args
        seen["prompt"] = prompt
        seen["schema"] = json.loads((cwd / "schema.json").read_text())
        events = [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"big": "x" * 10}},
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 1500, "output_tokens": 40, "cached_input_tokens": 200},
            },
        ]
        return 0, "\n".join(json.dumps(e) for e in events) + "\n", json.dumps(good_payload())

    monkeypatch.setattr(backends, "_run_codex", fake_run)
    out = complete("codex-gpt-6.1-sol", "low", "SYSTEM", "USER", {"type": "object"})
    assert json.loads(out.text or "")["findings"][0]["line"] == 41
    assert out.usage == {"input_tokens": 1500, "output_tokens": 40, "cache_read_input_tokens": 200}
    assert out.refused is False
    assert [e["type"] for e in out.raw["codex_events"]] == ["thread.started", "turn.completed"]
    assert seen["prompt"].startswith("SYSTEM\n\nUSER")
    assert seen["schema"] == {"type": "object"}
    assert "--model" in seen["args"] and "gpt-6.1-sol" in seen["args"]
    assert seen["args"][seen["args"].index("--sandbox") + 1] == "read-only"
    assert 'model_reasoning_effort="low"' in seen["args"]
    assert "--skip-git-repo-check" in seen["args"] and "--output-schema" in seen["args"]


def test_codex_failure_raises_instead_of_caching_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "_run_codex", lambda a, p, c: (1, "", None))
    with pytest.raises(BackendUnavailableError, match="exit 1"):
        complete("codex-gpt-6.1-sol", "low", "S", "U", {})
    events = '{"type":"thread.started"}\n{"type":"turn.failed","error":"rate limit"}\n'
    monkeypatch.setattr(backends, "_run_codex", lambda a, p, c: (0, events, None))
    with pytest.raises(BackendUnavailableError, match=r"turn\.failed"):
        complete("codex-gpt-6.1-sol", "low", "S", "U", {})


def test_codex_skips_non_json_lines_and_keeps_tool_items(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = "\n".join(
        [
            "Reading additional input from stdin...",
            '{"type":"thread.started","thread_id":"t"}',
            '{"type":"item.completed","item":{"type":"command_execution","command":"ls"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"..."}}',
            '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}',
            '{"truncated": ',
        ]
    )
    monkeypatch.setattr(backends, "_run_codex", lambda a, p, c: (0, stdout, "{}"))
    out = complete("codex-gpt-6.1-sol", "low", "S", "U", {})
    kinds = [(e["type"], e.get("item", {}).get("type")) for e in out.raw["codex_events"]]
    assert kinds == [
        ("thread.started", None),
        ("item.completed", "command_execution"),
        ("turn.completed", None),
    ]
    assert out.usage == {"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": 0}


def test_codex_events_without_a_completed_turn_report_zero_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backends, "_run_codex", lambda a, p, c: (0, '{"type":"thread.started"}\n', "{}")
    )
    out = complete("codex-gpt-6.1-sol", "low", "S", "U", {})
    assert out.usage == {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}


def test_codex_without_a_final_message_is_no_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "_run_codex", lambda args, prompt, cwd: (0, "", None))
    result, raw = review.review_diff(SAMPLE, model="codex-gpt-6.1-sol")
    assert result.no_output and result.findings == [] and "no text block" in (result.error or "")
    assert raw == {"codex_events": []}


def test_review_diff_routes_codex_models_to_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        backends,
        "_run_codex",
        lambda args, prompt, cwd: (0, calls.append("codex") or "", json.dumps(good_payload())),
    )
    monkeypatch.setattr(
        backends,
        "_create_message",
        lambda **kw: calls.append("anthropic") or FakeResponse(good_payload()),
    )
    review.review_diff(SAMPLE, model="codex-gpt-6.1-sol")
    review.review_diff(SAMPLE, model="claude-haiku-5-5")
    assert calls == ["codex", "anthropic"]


def test_anthropic_completion_drops_thinking_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "_create_message", lambda **kw: FakeResponse(good_payload()))
    out = complete("claude-haiku-5-5", "low", "S", "U", {"type": "object"})
    assert isinstance(out, Completion)
    assert [b["type"] for b in out.raw["content"]] == ["text"]
