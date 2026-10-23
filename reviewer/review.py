"""Review a diff with one model call and write structured findings to a file."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reviewer import llm
from reviewer.config import (
    CONTEXT_MODE,
    EFFORT,
    MAX_OUTPUT_TOKENS,
    MODEL,
    PROMPT_PATH,
    SCHEMA_PATH,
    SEVERITIES,
)
from reviewer.diffs import DiffTooLargeError, NumberedDiff, number_diff

THINKING_BLOCKS = ("thinking", "redacted_thinking")


class InvalidFindingsError(ValueError):
    """The model returned findings that violate the output contract."""


@dataclass(frozen=True)
class ReviewResult:
    """What one review produced, including the failure mode when it produced nothing."""

    findings: list[dict[str, Any]]
    no_output: bool
    error: str | None
    dropped: list[str]
    usage: dict[str, int]
    elapsed_ms: int
    model: str
    prompt_id: str


def load_prompt() -> str:
    """Return the reviewer prompt text."""
    return PROMPT_PATH.read_text()


def load_schema() -> dict[str, Any]:
    """Return the JSON schema the model output must satisfy."""
    return json.loads(SCHEMA_PATH.read_text())


def prompt_id(context_mode: str = CONTEXT_MODE) -> str:
    """Hash of prompt, schema and context mode: one id per reviewer version."""
    blob = load_prompt() + json.dumps(load_schema(), sort_keys=True) + context_mode
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _create_message(**kwargs: Any) -> Any:
    return llm.client().messages.create(**kwargs)


def _normalize_path(path: str) -> str:
    cleaned = path.strip()
    for prefix in ("./", "b/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned


def _check_finding(raw: dict[str, Any], numbered: NumberedDiff) -> dict[str, Any]:
    for key in ("file", "line", "severity", "category", "description", "rationale", "confidence"):
        if key not in raw:
            msg = f"finding lacks {key!r}"
            raise InvalidFindingsError(msg)
    path = _normalize_path(str(raw["file"]))
    if path not in numbered.valid_lines:
        msg = f"finding cites {path!r}, which is not in the diff"
        raise InvalidFindingsError(msg)
    line = int(raw["line"])
    if line not in numbered.valid_lines[path]:
        msg = f"finding cites {path}:{line}, which is outside the diff hunks"
        raise InvalidFindingsError(msg)
    if raw["severity"] not in SEVERITIES:
        msg = f"unknown severity {raw['severity']!r}"
        raise InvalidFindingsError(msg)
    confidence = float(raw["confidence"])
    if not 0.0 <= confidence <= 1.0:
        msg = f"confidence {confidence} is outside [0, 1]"
        raise InvalidFindingsError(msg)
    return {**raw, "file": path, "line": line, "confidence": confidence}


def normalize_findings(
    payload: dict[str, Any], numbered: NumberedDiff
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate each finding against the diff; return the valid ones and why the rest were dropped.

    Raises:
        InvalidFindingsError: When the payload has no ``findings`` list at all.
    """
    findings = payload.get("findings")
    if not isinstance(findings, list):
        msg = "payload has no 'findings' list"
        raise InvalidFindingsError(msg)
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for raw in findings:
        try:
            kept.append(_check_finding(raw, numbered))
        except (InvalidFindingsError, TypeError, ValueError) as exc:
            dropped.append(str(exc))
    return kept, dropped


def _parse_payload(response: Any) -> dict[str, Any]:
    if response.stop_reason == "refusal":
        msg = "model refused the request"
        raise InvalidFindingsError(msg)
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
    if text is None:
        msg = "response has no text block"
        raise InvalidFindingsError(msg)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"response is not valid JSON: {exc}"
        raise InvalidFindingsError(msg) from exc


def _auditable_envelope(response: Any) -> dict[str, Any]:
    """The API response minus thinking blocks: their text is empty and the signature is opaque."""
    raw = json.loads(json.dumps(response.model_dump(), default=str))
    raw["content"] = [
        block for block in raw.get("content", []) if block.get("type") not in THINKING_BLOCKS
    ]
    return raw


def _usage(response: Any) -> dict[str, int]:
    usage = response.usage
    return {
        "input_tokens": int(usage.input_tokens),
        "output_tokens": int(usage.output_tokens),
        "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }


def review_diff(
    diff_text: str, model: str = MODEL, effort: str = EFFORT, context_mode: str = CONTEXT_MODE
) -> tuple[ReviewResult, dict[str, Any]]:
    """Review ``diff_text`` with one model call; return the result and the raw API envelope.

    A refusal or invalid JSON yields ``no_output=True`` with an empty findings list, so the
    caller scores it as a miss instead of a clean review. A finding that cites a file or line
    outside the diff is dropped and recorded in ``dropped``; the rest of the review stands.
    """
    numbered = number_diff(diff_text)
    version = prompt_id(context_mode)
    started = time.monotonic()
    response = _create_message(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=load_prompt(),
        messages=[{"role": "user", "content": numbered.text}],
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": load_schema()},
        },
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    raw = _auditable_envelope(response)
    usage = _usage(response)
    try:
        findings, dropped = normalize_findings(_parse_payload(response), numbered)
        result = ReviewResult(findings, False, None, dropped, usage, elapsed_ms, model, version)
    except InvalidFindingsError as exc:
        result = ReviewResult([], True, str(exc), [], usage, elapsed_ms, model, version)
    return result, raw


def run_review(
    diff_text: str,
    out_path: Path,
    raw_out: Path | None = None,
    model: str = MODEL,
    effort: str = EFFORT,
) -> ReviewResult:
    """Review ``diff_text``, write ``out_path`` and, when given, the raw envelope to ``raw_out``."""
    result, raw = review_diff(diff_text, model, effort)
    if raw_out is not None:
        raw_out.write_text(json.dumps(raw, indent=2))
    out_path.write_text(json.dumps(asdict(result), indent=2) + "\n")
    return result


def git_diff(repo: Path, base: str, head: str) -> str:
    """Return ``git diff base...head`` for ``repo``."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "diff", f"{base}...{head}", "--", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review a diff and write JSON findings.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", type=Path, help="path to a unified diff")
    source.add_argument("--repo", type=Path, help="repository to diff (needs --base and --head)")
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--out", type=Path, default=Path("findings.json"))
    parser.add_argument("--raw-out", type=Path, default=None)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default=EFFORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit 0 on a valid review, 2 when the model produced no usable output."""
    args = _parse_args(argv)
    diff_text = args.diff.read_text() if args.diff else git_diff(args.repo, args.base, args.head)
    try:
        result = run_review(diff_text, args.out, args.raw_out, args.model, args.effort)
    except DiffTooLargeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.no_output:
        print(f"no usable output: {result.error}", file=sys.stderr)
        return 2
    print(f"{len(result.findings)} finding(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
