"""The two ways a reviewer prompt reaches a model: the Anthropic Messages API, or `codex exec`.

The reviewer builds one system prompt, one user message and one JSON schema; a backend turns
them into a ``Completion``. Which backend runs is decided by the model id: ``codex-<model>``
goes through the Codex CLI on the user's subscription, anything else through the Anthropic
client in ``reviewer.llm``. Nothing above this module knows which one answered.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reviewer import llm
from reviewer.config import MAX_OUTPUT_TOKENS

CODEX_PREFIX = "codex-"
CODEX_TIMEOUT_S = 600
THINKING_BLOCKS = ("thinking", "redacted_thinking")
AUDIT_EVENTS = ("thread.started", "turn.completed", "turn.failed", "error")
TOOL_ITEMS = ("command_execution", "file_change", "web_search", "mcp_tool_call")


class BackendUnavailableError(RuntimeError):
    """The backend did not answer at all (CLI failure, timeout, auth); nothing should be cached."""


@dataclass(frozen=True)
class Completion:
    """What a backend returns: the model's text (``None`` when there was none), and the rest."""

    text: str | None
    refused: bool
    usage: dict[str, int]
    raw: dict[str, Any]


def is_codex(model: str) -> bool:
    """True when ``model`` names a Codex CLI model (``codex-gpt-6.1-sol``)."""
    return model.startswith(CODEX_PREFIX)


def complete(model: str, effort: str, system: str, user: str, schema: dict[str, Any]) -> Completion:
    """Run the prompt on the backend that ``model`` selects."""
    if is_codex(model):
        return _complete_codex(model.removeprefix(CODEX_PREFIX), effort, system, user, schema)
    return _complete_anthropic(model, effort, system, user, schema)


def _create_message(**kwargs: Any) -> Any:
    return llm.client().messages.create(**kwargs)


def _complete_anthropic(
    model: str, effort: str, system: str, user: str, schema: dict[str, Any]
) -> Completion:
    response = _create_message(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
    usage = response.usage
    raw = json.loads(json.dumps(response.model_dump(), default=str))
    raw["content"] = [
        block for block in raw.get("content", []) if block.get("type") not in THINKING_BLOCKS
    ]
    return Completion(
        text=text,
        refused=response.stop_reason == "refusal",
        usage={
            "input_tokens": int(usage.input_tokens),
            "output_tokens": int(usage.output_tokens),
            "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        },
        raw=raw,
    )


def _run_codex(args: list[str], prompt: str, cwd: Path) -> tuple[int, str, str | None]:
    """Run ``codex exec`` headless; return its exit code, JSONL events and final message text.

    Raises:
        BackendUnavailableError: When the CLI does not finish within ``CODEX_TIMEOUT_S``.
    """
    last = cwd / "last-message.json"
    try:
        completed = subprocess.run(
            ["codex", "exec", *args, "--output-last-message", str(last), "--json", prompt],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"codex exec did not finish within {CODEX_TIMEOUT_S}s"
        raise BackendUnavailableError(msg) from exc
    text = last.read_text() if last.exists() else None
    return completed.returncode, completed.stdout, text


def _complete_codex(
    model: str, effort: str, system: str, user: str, schema: dict[str, Any]
) -> Completion:
    """One ``codex exec`` call with the schema enforced, in a read-only sandbox.

    Codex prepends its own agent instructions, so the reviewer's system prompt travels at the
    top of the user prompt. The sandbox blocks writes and the working directory is empty; the
    CLI can still run read-only shell commands, so every tool item it reports is kept in the
    raw envelope for audit. A CLI failure (non-zero exit, ``error`` or ``turn.failed`` event,
    timeout) raises ``BackendUnavailableError`` so the caller does not cache it as a review.
    """
    with tempfile.TemporaryDirectory(prefix="codex-review-") as tmp:
        cwd = Path(tmp)
        schema_path = cwd / "schema.json"
        schema_path.write_text(json.dumps(schema))
        args = [
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--output-schema",
            str(schema_path),
        ]
        returncode, events_text, text = _run_codex(args, f"{system}\n\n{user}", cwd)
    events = _parse_events(events_text)
    failed = [e for e in events if e.get("type") in ("error", "turn.failed")]
    if returncode != 0 or failed:
        msg = f"codex exec failed (exit {returncode}): {failed[:1] or 'no error event'}"
        raise BackendUnavailableError(msg)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    for event in events:
        if event.get("type") == "turn.completed":
            u = event.get("usage", {})
            usage = {
                "input_tokens": int(u.get("input_tokens", 0)),
                "output_tokens": int(u.get("output_tokens", 0)),
                "cache_read_input_tokens": int(u.get("cached_input_tokens", 0)),
            }
    kept = [e for e in events if e.get("type") in AUDIT_EVENTS or _is_tool_item(e)]
    return Completion(text=text, refused=False, usage=usage, raw={"codex_events": kept})


def _parse_events(text: str) -> list[dict[str, Any]]:
    """JSONL events from stdout; lines that are not JSON objects are skipped."""
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _is_tool_item(event: dict[str, Any]) -> bool:
    item = event.get("item")
    return isinstance(item, dict) and item.get("type") in TOOL_ITEMS
