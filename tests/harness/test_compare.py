import json
from pathlib import Path

import pytest

from eval.harness.compare import compare_runs

ROW_KEYS = ("tp", "tp_medium_plus", "fp", "fn", "noise", "duplicates", "findings", "no_output")


def row(
    case_id: str,
    k: int,
    family: str,
    recall_high: float | None,
    *,
    fp: int = 0,
    is_clean: bool = False,
    tp: int = 0,
) -> dict:
    base: dict[str, object] = dict.fromkeys(ROW_KEYS, 0)
    base.update(
        {
            "case_id": case_id,
            "k": k,
            "family_id": family,
            "source": "seeded",
            "is_clean": is_clean,
            "recall_high": recall_high,
            "recall_all": recall_high,
            "clean_alarm": int(is_clean and fp > 0),
            "tp": tp,
            "tp_medium_plus": tp,
            "fp": fp,
            "elapsed_ms": 1000,
            "matched": {},
            "unknown_pairs": [],
        }
    )
    return base


def write_run(
    runs: Path, name: str, rows: list[dict], gold_hash: str = "g", judge: str = "j"
) -> None:
    (runs / name).mkdir(parents=True)
    (runs / name / "scored.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (runs / name / "summary.json").write_text(
        json.dumps(
            {
                "k": 2,
                "n_cases": 40,
                "judge": {"model": "m", "prompt_hash": judge},
                "line_tolerance": 3,
                "precision_medium_plus": {"value": 0.9, "tp": 27, "fp": 3, "wilson": [0.74, 0.97]},
                "clean_fp_rate": {"mean": 0.05, "n_cases": 20, "wilson_case_runs": [0.01, 0.17]},
                "recall_high": {"mean": 0.75, "n_cases": 20},
            }
        )
    )
    (runs / name / "manifest.json").write_text(
        json.dumps({"gold_hash": gold_hash, "prompt_id": name, "k": 2, "context_mode": "hunk_only"})
    )


def big_rows(flip: set[str] | None = None, alarm: set[str] | None = None) -> list[dict]:
    """40 cases in 40 families: 20 with a high gold (c0..c19), 20 clean (d0..d19)."""
    rows = []
    for k in (1, 2):
        for i in range(20):
            cid = f"c{i}"
            hit = 0.0 if cid in (flip or set()) else 1.0
            rows.append(row(cid, k, f"f{i}", hit, tp=int(hit)))
        for i in range(20):
            cid = f"d{i}"
            fp = 1 if cid in (alarm or set()) else 0
            rows.append(row(cid, k, f"g{i}", None, fp=fp, is_clean=True))
    return rows


def baseline_rows() -> list[dict]:
    rows = []
    for k in (1, 2):
        rows += [
            row("c1", k, "f1", 1.0, tp=1),
            row("c2", k, "f2", 1.0, tp=1),
            row("c3", k, "f3", 0.0),
            row("c4", k, "f4", None, is_clean=True),
        ]
    return rows


def test_identical_runs_pass(tmp_path: Path) -> None:
    write_run(tmp_path, "a", big_rows())
    write_run(tmp_path, "b", big_rows())
    out = compare_runs("a", "b", runs_dir=tmp_path, resamples=300)
    assert out["verdict"] == "PASS"


def test_tiny_sample_is_inconclusive_even_when_identical(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows())
    write_run(tmp_path, "b", baseline_rows())
    out = compare_runs("a", "b", runs_dir=tmp_path, resamples=300)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["recall_high"]["delta"] == 0.0
    assert out["lost_cases"] == [] and out["gained_cases"] == []


def test_lost_case_is_named(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows())
    cand = baseline_rows()
    for r in cand:
        if r["case_id"] == "c1":
            r["recall_high"] = 0.0
            r["tp"] = 0
    write_run(tmp_path, "b", cand)
    out = compare_runs("a", "b", runs_dir=tmp_path, resamples=300)
    assert out["lost_cases"] == [{"case_id": "c1", "baseline": 1.0, "candidate": 0.0}]
    assert out["recall_high"]["delta"] < 0
    assert out["verdict"] in ("INCONCLUSIVE", "FAIL")


def test_gained_case_is_named(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows())
    cand = baseline_rows()
    for r in cand:
        if r["case_id"] == "c3":
            r["recall_high"] = 1.0
    write_run(tmp_path, "b", cand)
    out = compare_runs("a", "b", runs_dir=tmp_path, resamples=300)
    assert out["gained_cases"][0]["case_id"] == "c3"


def test_new_false_positive_is_named(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows())
    cand = baseline_rows()
    cand[3]["fp"] = 1
    cand[3]["clean_alarm"] = 1
    write_run(tmp_path, "b", cand)
    out = compare_runs("a", "b", runs_dir=tmp_path, resamples=300)
    assert out["new_clean_alarms"] == [{"case_id": "c4", "baseline": 0.0, "candidate": 0.5}]


def test_refuses_different_gold_or_judge(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows(), gold_hash="g1")
    write_run(tmp_path, "b", baseline_rows(), gold_hash="g2")
    with pytest.raises(ValueError, match="gold_hash"):
        compare_runs("a", "b", runs_dir=tmp_path, resamples=10)
    write_run(tmp_path, "c", baseline_rows(), gold_hash="g1", judge="other")
    with pytest.raises(ValueError, match="judge"):
        compare_runs("a", "c", runs_dir=tmp_path, resamples=10)
    write_run(tmp_path, "d", baseline_rows(), gold_hash="g1")
    manifest = json.loads((tmp_path / "d" / "manifest.json").read_text())
    manifest["k"] = 5
    (tmp_path / "d" / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differ in k"):
        compare_runs("a", "d", runs_dir=tmp_path, resamples=10)


def test_writes_comparison_json(tmp_path: Path) -> None:
    write_run(tmp_path, "a", baseline_rows())
    write_run(tmp_path, "b", baseline_rows())
    compare_runs("a", "b", runs_dir=tmp_path, resamples=100)
    out = json.loads((tmp_path / "b" / "comparison-vs-a.json").read_text())
    assert out["baseline"] == "a" and out["candidate"] == "b"
