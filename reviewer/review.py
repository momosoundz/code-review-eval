"""Review a diff with one model call and write structured findings to a file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import anthropic

from reviewer.diffs import DiffTooLargeError, NumberedDiff, number_diff

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"
MAX_TOKENS = 8_000
SEVERITIES = ("high", "medium", "low")
PROMPT_PATH = Path(__file__).with_name("prompt.md")
SCHEMA_PATH = Path(__file__).with_name("schema.json")


class InvalidFindingsError(ValueError):
    """The model returned findings that violate the output contract."""


@dataclass(frozen=True)
class ReviewResult:
    """What one review produced, including the failure mode when it produced nothing."""

    findings: list[dict[str, Any]]
    no_output: bool
    error: str | None
    usage: dict[str, int]
    model: str
    prompt_id: str


def load_prompt() -> str:
    """Return the reviewer prompt text."""
    return PROMPT_PATH.read_text()


def load_schema() -> dict[str, Any]:
    """Return the JSON schema the model output must satisfy."""
    return json.loads(SCHEMA_PATH.read_text())


def prompt_id(context_mode: str = "hunk_only") -> str:
    """Hash of prompt, schema and context mode: one id per reviewer version."""
    blob = load_prompt() + json.dumps(load_schema(), sort_keys=True) + context_mode
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _client() -> anthropic.Anthropic:
    """Build the API client; a user-scoped key needs ``ANTHROPIC_WORKSPACE_ID`` as a header."""
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(default_headers=headers)


def _create_message(**kwargs: Any) -> Any:
    return _client().messages.create(**kwargs)


def _normalize_path(path: str) -> str:
    cleaned = path.strip().lstrip("./")
    return cleaned[2:] if cleaned.startswith("b/") else cleaned


def _check_finding(raw: dict[str, Any], numbered: NumberedDiff) -> dict[str, Any]:
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


def normalize_findings(payload: dict[str, Any], numbered: NumberedDiff) -> list[dict[str, Any]]:
    """Validate the model payload against the diff and normalize paths and numbers.

    Raises:
        InvalidFindingsError: When a finding cites a file or line not in the diff,
            or carries a value outside the contract.
    """
    findings = payload.get("findings")
    if not isinstance(findings, list):
        msg = "payload has no 'findings' list"
        raise InvalidFindingsError(msg)
    return [_check_finding(f, numbered) for f in findings]


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


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }


def run_review(
    diff_text: str,
    out_path: Path,
    raw_out: Path | None = None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> ReviewResult:
    """Review ``diff_text`` with one model call and write ``out_path``.

    A refusal, invalid JSON or a finding outside the diff yields ``no_output=True`` with an
    empty findings list, so the caller can score it as a miss instead of a clean review.
    """
    numbered = number_diff(diff_text)
    version = prompt_id()
    response = _create_message(
        model=model,
        max_tokens=MAX_TOKENS,
        system=load_prompt(),
        messages=[{"role": "user", "content": numbered.text}],
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": load_schema()},
        },
    )
    if raw_out is not None:
        raw_out.write_text(json.dumps(response.model_dump(), indent=2, default=str))
    try:
        findings = normalize_findings(_parse_payload(response), numbered)
        result = ReviewResult(findings, False, None, _usage(response), model, version)
    except InvalidFindingsError as exc:
        result = ReviewResult([], True, str(exc), _usage(response), model, version)
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
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
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
