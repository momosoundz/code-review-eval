import json
from pathlib import Path

import pytest

from eval.harness.calibrate import (
    calibrate,
    confusion,
    corrected_rate,
    load_labels,
    rates,
    render,
    stratum_weights,
)


def labels(rows: list[tuple[str, str]]) -> list[dict]:
    return [{"pair_id": pid, "label": label} for pid, label in rows]


def test_confusion_counts_each_quadrant_and_skips_missing_verdicts() -> None:
    verdicts = {"a": "match", "b": "match", "c": "no_match", "d": "no_match"}
    counts = confusion(
        labels(
            [("a", "same"), ("b", "different"), ("c", "same"), ("d", "different"), ("e", "same")]
        ),
        verdicts,
    )
    assert counts == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}


def test_rates_and_kappa_without_weights() -> None:
    r = rates({"tp": 45, "fn": 5, "tn": 40, "fp": 10})
    assert r["tpr"] == 0.9 and r["tnr"] == 0.8 and r["n"] == 100
    assert r["ppv"] == pytest.approx(45 / 55) and r["npv"] == pytest.approx(40 / 45)
    assert r["ppv_wilson"][0] < r["ppv"] < r["ppv_wilson"][1]
    assert r["kappa"] == pytest.approx(0.7, abs=1e-9)
    assert r["kappa_sample"] == pytest.approx(0.7, abs=1e-9)


def test_reweighting_changes_kappa_but_not_kappa_sample() -> None:
    counts = {"tp": 71, "fp": 1, "fn": 1, "tn": 29}
    plain = rates(counts)
    weighted = rates(counts, {"match": 8.6, "no_match": 1.0})
    assert plain["kappa"] == pytest.approx(plain["kappa_sample"])
    assert weighted["kappa_sample"] == pytest.approx(plain["kappa_sample"])
    assert weighted["kappa"] < weighted["kappa_sample"]


def test_rates_reweight_the_judge_strata_to_the_store() -> None:
    """Every no_match labeled, one in ten matches labeled: TPR must weigh matches 10x."""
    counts = {"tp": 9, "fp": 1, "fn": 5, "tn": 25}
    unweighted = rates(counts)
    weighted = rates(counts, {"match": 10.0, "no_match": 1.0})
    assert unweighted["tpr"] == pytest.approx(9 / 14)
    assert weighted["tpr"] == pytest.approx(90 / 95)
    assert weighted["tnr"] == pytest.approx(25 / 35)
    assert weighted["ppv"] == unweighted["ppv"] == 0.9


def test_stratum_weights_are_store_over_labeled() -> None:
    verdicts = {f"m{i}": "match" for i in range(10)} | {"n0": "no_match", "n1": "no_match"}
    labels = [
        {"pair_id": "m0", "label": "same"},
        {"pair_id": "m1", "label": "same"},
        {"pair_id": "n0", "label": "different"},
        {"pair_id": "n1", "label": "same"},
    ]
    assert stratum_weights(labels, verdicts) == {"match": 5.0, "no_match": 1.0}
    assert stratum_weights([], verdicts) == {"match": 1.0, "no_match": 1.0}


def test_rates_with_no_negatives_leave_tnr_undefined() -> None:
    r = rates({"tp": 10, "fn": 0, "tn": 0, "fp": 0})
    assert r["tpr"] == 1.0 and r["tnr"] is None and r["npv"] is None


def test_corrected_rate_inverts_the_misclassification() -> None:
    observed = 0.9 * 0.7 + 0.2 * 0.3
    assert corrected_rate(observed, 0.9, 0.8) == pytest.approx(0.7)
    assert corrected_rate(0.5, 0.5, 0.5) is None
    assert corrected_rate(0.05, 0.9, 0.8) == 0.0


def test_calibrate_reads_files_and_corrects_runs(tmp_path: Path) -> None:
    version = "judge-v"
    store = tmp_path / "verdicts" / version / "crv-0001"
    store.mkdir(parents=True)
    for pid, verdict in (("g1-aaa", "match"), ("g1-bbb", "no_match"), ("g1-ccc", "match")):
        (store / f"{pid}.json").write_text(json.dumps({"verdict": verdict}))
    labels_path = tmp_path / "pair-labels.jsonl"
    labels_path.write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {"pair_id": "g1-aaa", "judge_version": version, "label": "same"},
                {"pair_id": "g1-bbb", "judge_version": version, "label": "different"},
                {"pair_id": "g1-ccc", "judge_version": version, "label": "unsure"},
            ]
        )
    )
    (tmp_path / "runs" / "r").mkdir(parents=True)
    (tmp_path / "runs" / "r" / "summary.json").write_text(
        json.dumps({"recall_medium_plus": {"mean": 0.8}})
    )
    report = calibrate(labels_path, tmp_path / "verdicts", version, ["r"], tmp_path / "runs")
    assert report["confusion"] == {"tp": 1, "fn": 0, "tn": 1, "fp": 0}
    assert report["unsure"] == 1
    assert report["runs"] == [{"run": "r", "observed": 0.8, "corrected": 0.8}]
    text = render(report)
    assert "| rater: same | 1 | 0 |" in text and "| r | 80% | 80% |" in text


def test_load_labels_filters_the_judge_version_and_keeps_the_last_label(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"pair_id": "a", "judge_version": "v1", "label": "same"}),
                json.dumps({"pair_id": "a", "judge_version": "v1", "label": "different"}),
                json.dumps({"pair_id": "b", "judge_version": "v0", "label": "same"}),
                '{"pair_id": "c", "judge_ver',
            ]
        )
    )
    rows = load_labels(path, "v1")
    assert [(r["pair_id"], r["label"]) for r in rows] == [("a", "different")]
