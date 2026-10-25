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

from reviewer import backends
from reviewer.backends import Completion
from reviewer.config import (
    CONTEXT_MODE,
    CONTEXT_MODES,
    EFFORT,
    MODEL,
    PROMPT_PATH,
    SCHEMA_PATH,
    SEVERITIES,
)
from reviewer.diffs import DiffTooLargeError, NumberedDiff, number_diff


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
    context_used: str
    input_sha256: str


def load_prompt() -> str:
    """Return the reviewer prompt text."""
    return PROMPT_PATH.read_text()


def load_schema() -> dict[str, Any]:
    """Return the JSON schema the model output must satisfy."""
    return json.loads(SCHEMA_PATH.read_text())


def prompt_id(context_mode: str = CONTEXT_MODE) -> str:
    """Hash of prompt, schema, context mode and its message template: one id per reviewer."""
    blob = (
        load_prompt()
        + json.dumps(load_schema(), sort_keys=True)
        + context_mode
        + TEMPLATES[context_mode]
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def input_sha256(numbered_diff: str, context_mode: str, title: str | None) -> str:
    """Hash of everything the model saw for one review: system prompt and user message."""
    blob = load_prompt() + "\n" + user_message(numbered_diff, context_mode, title)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


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
    payload: Any, numbered: NumberedDiff
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate each finding against the diff; return the valid ones and why the rest were dropped.

    Raises:
        InvalidFindingsError: When the payload is not an object with a ``findings`` list.
    """
    if not isinstance(payload, dict):
        msg = f"payload is not a JSON object: {type(payload).__name__}"
        raise InvalidFindingsError(msg)
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


def _parse_payload(completion: Completion) -> Any:
    if completion.refused:
        msg = "model refused the request"
        raise InvalidFindingsError(msg)
    if completion.text is None:
        msg = "response has no text block"
        raise InvalidFindingsError(msg)
    try:
        return json.loads(completion.text)
    except json.JSONDecodeError as exc:
        msg = f"response is not valid JSON: {exc}"
        raise InvalidFindingsError(msg) from exc


TEMPLATES = {
    "hunk_only": "{diff}",
    "hunk_plus_title": (
        "Commit title: {title}\n"
        "A behavior change that the title announces is intended and is not a defect by "
        "itself; judge whether the implementation of that intent is correct.\n\n{diff}"
    ),
    "hunk_plus_title_verified": (
        "Commit title: {title}\n"
        "The title states what the author meant to do. Do not take it as evidence that the "
        "code does it. Check the implementation against the title operator by operator and "
        "branch by branch: a change that the title announces is not a defect, but an "
        "implementation that does something other than what the title says is, even when "
        "it looks like part of the same refactor.\n\n{diff}"
    ),
}


def effective_context(context_mode: str, title: str | None) -> str:
    """The mode actually applied: a title mode without a title degrades to ``hunk_only``."""
    return context_mode if title or context_mode == "hunk_only" else "hunk_only"


def user_message(numbered_diff: str, context_mode: str, title: str | None) -> str:
    """What the model receives, built from the template of the effective context mode."""
    mode = effective_context(context_mode, title)
    return TEMPLATES[mode].format(diff=numbered_diff, title=title or "")


def review_diff(
    diff_text: str,
    model: str = MODEL,
    effort: str = EFFORT,
    context_mode: str = CONTEXT_MODE,
    title: str | None = None,
) -> tuple[ReviewResult, dict[str, Any]]:
    """Review ``diff_text`` with one model call; return the result and the raw API envelope.

    ``model`` picks the backend (``reviewer.backends``): ``codex-<model>`` runs through the
    Codex CLI, any other id through the Anthropic API. A refusal or invalid JSON yields
    ``no_output=True`` with an empty findings list, so the caller scores it as a miss instead
    of a clean review. A finding that cites a file or line outside the diff is dropped and
    recorded in ``dropped``; the rest of the review stands. ``context_mode`` selects what
    accompanies the diff; it is part of ``prompt_id``.
    """
    numbered = number_diff(diff_text)
    version = prompt_id(context_mode)
    used = effective_context(context_mode, title)
    digest = input_sha256(numbered.text, context_mode, title)
    started = time.monotonic()
    completion = backends.complete(
        model,
        effort,
        load_prompt(),
        user_message(numbered.text, context_mode, title),
        load_schema(),
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    raw = completion.raw
    usage = completion.usage
    try:
        findings, dropped = normalize_findings(_parse_payload(completion), numbered)
        result = ReviewResult(
            findings, False, None, dropped, usage, elapsed_ms, model, version, used, digest
        )
    except InvalidFindingsError as exc:
        result = ReviewResult(
            [], True, str(exc), [], usage, elapsed_ms, model, version, used, digest
        )
    return result, raw


@dataclass(frozen=True)
class ReviewOptions:
    """What varies between reviewer versions: model, effort, context mode, and the title."""

    model: str = MODEL
    effort: str = EFFORT
    context_mode: str = CONTEXT_MODE
    title: str | None = None


def run_review(
    diff_text: str,
    out_path: Path,
    raw_out: Path | None = None,
    options: ReviewOptions | None = None,
) -> ReviewResult:
    """Review ``diff_text``, write ``out_path`` and, when given, the raw envelope to ``raw_out``."""
    opts = options or ReviewOptions()
    result, raw = review_diff(diff_text, opts.model, opts.effort, opts.context_mode, opts.title)
    if raw_out is not None:
        raw_out.write_text(json.dumps(raw, indent=2))
    out_path.write_text(json.dumps(asdict(result), indent=2) + "\n")
    return result


def clean_title(title: str | None) -> str | None:
    """One line, whitespace collapsed, capped at 200 characters; None stays None."""
    if title is None:
        return None
    return " ".join(title.split())[:200] or None


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
    parser.add_argument("--context-mode", default=CONTEXT_MODE, choices=CONTEXT_MODES)
    parser.add_argument("--title", default=None, help="commit title, used in hunk_plus_title mode")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit 0 on a valid review, 2 when the model produced no usable output."""
    args = _parse_args(argv)
    diff_text = args.diff.read_text() if args.diff else git_diff(args.repo, args.base, args.head)
    try:
        options = ReviewOptions(args.model, args.effort, args.context_mode, clean_title(args.title))
        result = run_review(diff_text, args.out, args.raw_out, options)
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
