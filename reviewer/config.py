"""Reviewer settings. Every value here is recorded in the run manifest."""

from pathlib import Path

MODEL = "claude-haiku-5-5"
EFFORT = "low"
MAX_OUTPUT_TOKENS = 8_000
MAX_DIFF_CHARS = 48_000
SEVERITIES = ("high", "medium", "low")
# How the reviewer sees the diff. Changing it is a new reviewer version: it enters prompt_id.
CONTEXT_MODE = "hunk_only"
PROMPT_PATH = Path(__file__).with_name("prompt.md")
SCHEMA_PATH = Path(__file__).with_name("schema.json")

# Defect categories the reviewer labels and the gold set uses. `other` is the escape hatch for a
# defect the taxonomy does not cover yet; `maintainability` never counts as a hit or a false
# positive. Matching a finding to gold does not depend on category.
CATEGORIES = (
    "boundary",
    "null_or_missing_value",
    "wrong_operator",
    "wrong_condition",
    "wrong_variable_or_argument",
    "wrong_literal_or_default",
    "error_handling",
    "resource_lifecycle",
    "concurrency",
    "input_validation",
    "logic_other",
    "other",
)
NON_GATED_CATEGORIES = ("maintainability",)
