"""Parse a unified diff and number the post-change lines the reviewer may cite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from unidiff import PatchSet

from reviewer.config import MAX_DIFF_CHARS


class DiffTooLargeError(ValueError):
    """The diff is bigger than the reviewer accepts; we refuse rather than truncate."""


@dataclass(frozen=True)
class NumberedDiff:
    """A diff rendered with post-change line numbers and the set of citable lines per file."""

    text: str
    valid_lines: dict[str, set[int]] = field(default_factory=dict)
    changed_lines: dict[str, set[int]] = field(default_factory=dict)


def _render_hunk_line(line: object) -> str:
    target = getattr(line, "target_line_no", None)
    marker = getattr(line, "line_type", " ")
    value = str(getattr(line, "value", "")).rstrip("\n")
    number = f"{target:>5}" if target is not None else "     "
    return f"{number} {marker}{value}"


def number_diff(diff_text: str, max_chars: int = MAX_DIFF_CHARS) -> NumberedDiff:
    """Render a unified diff with post-change line numbers in a left gutter.

    Args:
        diff_text: Raw unified diff.
        max_chars: Size cap; larger diffs raise instead of being truncated.

    Returns:
        The numbered rendering and, per post-change path, the lines that appear in a hunk
        and the subset that is a change: added lines and the context line right after a
        deleted block.

    Raises:
        DiffTooLargeError: When the diff exceeds ``max_chars``.
        ValueError: When the diff contains no hunks.
    """
    if len(diff_text) > max_chars:
        msg = f"diff has {len(diff_text)} chars and exceeds the {max_chars} char cap"
        raise DiffTooLargeError(msg)
    patch = PatchSet(diff_text)
    rendered: list[str] = []
    valid: dict[str, set[int]] = {}
    changed: dict[str, set[int]] = {}
    for patched_file in patch:
        path = _post_change_path(patched_file)
        if path is None or patched_file.is_binary_file:
            continue
        rendered.append(f"### {path}")
        lines = valid.setdefault(path, set())
        touched = changed.setdefault(path, set())
        for hunk in patched_file:
            rendered.append(
                f"@@ -{hunk.source_start},{hunk.source_length} "
                f"+{hunk.target_start},{hunk.target_length} @@"
            )
            rendered.extend(_render_hunk(hunk, lines, touched))
    if not valid:
        msg = "diff contains no hunks to review"
        raise ValueError(msg)
    return NumberedDiff(text="\n".join(rendered) + "\n", valid_lines=valid, changed_lines=changed)


def _render_hunk(hunk: Any, lines: set[int], touched: set[int]) -> list[str]:
    """Render one hunk; record its post-change lines and the subset that is a change."""
    rendered: list[str] = []
    after_removal = False
    last_target: int | None = None
    for line in hunk:
        rendered.append(_render_hunk_line(line))
        if line.target_line_no is not None:
            lines.add(line.target_line_no)
            last_target = line.target_line_no
            if line.is_added or after_removal:
                touched.add(line.target_line_no)
        after_removal = line.is_removed
    if after_removal and last_target is not None:
        touched.add(last_target)
    return rendered


def _post_change_path(patched_file: object) -> str | None:
    if getattr(patched_file, "is_removed_file", False):
        return None
    raw = str(getattr(patched_file, "target_file", ""))
    if raw.startswith("b/"):
        raw = raw[2:]
    return raw or None
