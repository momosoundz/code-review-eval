"""Parse a unified diff and number the post-change lines the reviewer may cite."""

from __future__ import annotations

from dataclasses import dataclass, field

from unidiff import PatchSet

from reviewer.config import MAX_DIFF_CHARS


class DiffTooLargeError(ValueError):
    """The diff is bigger than the reviewer accepts; we refuse rather than truncate."""


@dataclass(frozen=True)
class NumberedDiff:
    """A diff rendered with post-change line numbers and the set of citable lines per file."""

    text: str
    valid_lines: dict[str, set[int]] = field(default_factory=dict)


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
        The numbered rendering and, per post-change path, the lines that appear in a hunk.

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
    for patched_file in patch:
        path = _post_change_path(patched_file)
        if path is None or patched_file.is_binary_file:
            continue
        rendered.append(f"### {path}")
        lines = valid.setdefault(path, set())
        for hunk in patched_file:
            rendered.append(
                f"@@ -{hunk.source_start},{hunk.source_length} "
                f"+{hunk.target_start},{hunk.target_length} @@"
            )
            for line in hunk:
                rendered.append(_render_hunk_line(line))
                if line.target_line_no is not None:
                    lines.add(line.target_line_no)
    if not valid:
        msg = "diff contains no hunks to review"
        raise ValueError(msg)
    return NumberedDiff(text="\n".join(rendered) + "\n", valid_lines=valid)


def _post_change_path(patched_file: object) -> str | None:
    if getattr(patched_file, "is_removed_file", False):
        return None
    raw = str(getattr(patched_file, "target_file", ""))
    if raw.startswith("b/"):
        raw = raw[2:]
    return raw or None
