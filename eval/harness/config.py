"""Eval harness constants. Every value that shapes a score is copied into the run manifest."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "eval_runs"

# Hard stop for one collect run, in USD, estimated from token usage and the price table below.
BUDGET_USD = 5.0

# USD per million tokens, input and output. Used only for the cost estimate in the manifest.
PRICES_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# Matching: a finding is eligible for a gold defect when it cites the same file and a line within
# this many lines of one of the gold spans. Recorded in the manifest; sensitivity shown at 0/3/10.
LINE_TOLERANCE = 3

# A finding that matches no gold counts as a false positive only at these severities.
FP_SEVERITIES = ("high", "medium")

# Statistics: resamples for the paired bootstrap and the gate margin in recall points.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261022
GATE_MAX_DROP = 0.10
MIN_SLICE_SIZE = 20
