import json
from pathlib import Path

from eval.harness.report import comparison_table, render, slices_table, summary_table


def rate(mean: float, n: int) -> dict:
    return {
        "mean": mean,
        "all_k": mean,
        "any_k": mean,
        "n_cases": n,
        "k": 3,
        "wilson_case_runs": [max(0.0, mean - 0.1), min(1.0, mean + 0.1)],
        "gates": n >= 20,
    }


def summary() -> dict:
    return {
        "k": 3,
        "n_cases": 40,
        "recall_medium_plus": rate(0.8, 20),
        "recall_high": rate(0.6, 5),
        "recall_all": rate(0.75, 24),
        "recall_low": rate(0.5, 4),
        "clean_fp_rate": rate(0.1, 16),
        "precision_medium_plus": {"value": 0.9, "tp": 27, "fp": 3, "wilson": [0.74, 0.97]},
        "no_output_rate": 0.0,
        "findings_per_diff": 1.1,
        "noise_per_diff": 0.2,
        "duplicate_rate": 0.05,
        "unknown_pairs": 1,
        "p50_elapsed_ms": 2100,
        "by_source": {"seeded": {"n_cases": 16, "recall_all": rate(0.8, 16)}},
    }


def test_summary_table_mentions_gate_and_small_slices() -> None:
    text = summary_table(summary())
    assert "recall, defects medium or high (gate) | 80% [70, 90]" in text
    assert "recall, high only | 60% [50, 70] | 60% | 60% | 5 (too few to gate)" in text
    assert "27 TP / 3 FP" in text


def test_comparison_table_names_lost_cases() -> None:
    comparison = {
        "verdict": "INCONCLUSIVE",
        "gate": {"metric": "recall_medium_plus", "max_drop": 0.1, "min_families": 20},
        "gate_metric": {"delta": -0.05, "ci95": [-0.2, 0.1], "n_cases": 20, "families": 20},
        "lost_cases": [{"case_id": "crv-0012", "baseline": 1.0, "candidate": 0.33}],
        "gained_cases": [],
        "new_clean_alarms": [],
    }
    text = comparison_table(comparison)
    assert (
        "**INCONCLUSIVE**" in text and "crv-0012 (1.00 -> 0.33)" in text and "Gained: none" in text
    )


def test_render_reads_files(tmp_path: Path) -> None:
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "summary.json").write_text(json.dumps(summary()))
    (tmp_path / "r" / "manifest.json").write_text(
        json.dumps({"context_mode": "hunk_only", "cases_without_title": []})
    )
    text = render("r", tmp_path)
    assert text.startswith("### r") and "| seeded | 16 | 80% [70, 90] | 80% |" in text
    assert "no commit title" not in text


def test_render_names_the_cases_reviewed_without_a_title(tmp_path: Path) -> None:
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "summary.json").write_text(json.dumps(summary()))
    (tmp_path / "r" / "manifest.json").write_text(
        json.dumps({"context_mode": "hunk_plus_title", "cases_without_title": ["crv-0040"]})
    )
    text = render("r", tmp_path)
    assert "1 case(s) have no commit title" in text and "crv-0040" in text


def test_slices_table_keeps_the_interval_of_small_slices() -> None:
    text = slices_table(summary())
    assert "| seeded | 16 | 80% [70, 90] | 80% |" in text
