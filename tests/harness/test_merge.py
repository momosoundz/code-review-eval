import json
from pathlib import Path

import pytest

from eval.harness.collect import response_path
from eval.harness.merge import merge_findings, merge_runs


def f(line: int, severity: str = "high", file: str = "a.py", desc: str = "d") -> dict:
    return {
        "file": file,
        "line": line,
        "severity": severity,
        "category": "boundary",
        "description": desc,
        "rationale": "r",
        "confidence": 0.9,
    }


def test_union_keeps_everything_once() -> None:
    merged = merge_findings([f(10), f(50)], [f(12, desc="dup"), f(90), f(30, file="b.py")], "union")
    assert [(m["file"], m["line"]) for m in merged] == [
        ("a.py", 10),
        ("a.py", 50),
        ("a.py", 90),
        ("b.py", 30),
    ]


def test_agreement_keeps_shared_anchors_with_the_lower_severity() -> None:
    merged = merge_findings([f(10, "high"), f(50, "medium")], [f(12, "low"), f(200)], "agreement")
    assert merged == [{**f(10, "high"), "severity": "low"}]


def test_union_does_not_alias_the_input_and_respects_the_tolerance_boundary() -> None:
    a = [f(10)]
    merged = merge_findings(a, [f(13), f(14)], "union", tolerance=3)
    assert [m["line"] for m in merged] == [10, 14]
    assert len(a) == 1 and merged[0] is not a[0]


def test_agreement_needs_the_same_file() -> None:
    assert merge_findings([f(10)], [f(10, file="b.py")], "agreement") == []


def test_unknown_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="policy"):
        merge_findings([], [], "vote")


def write_run(
    runs: Path,
    name: str,
    model: str,
    version: str,
    per_case: dict[str, list[list[dict]]],
    *,
    no_output: frozenset[str] = frozenset(),
) -> None:
    (runs / name).mkdir(parents=True)
    (runs / name / "manifest.json").write_text(
        json.dumps(
            {
                "run": name,
                "model": model,
                "effort": "low",
                "prompt_id": version[:12],
                "reviewer_version": version,
                "context_mode": "hunk_only",
                "k": 2,
                "split": ["release"],
                "case_ids": sorted(per_case),
                "gold_hash": "g",
                "git_sha": "s",
                "cost_usd": 0.5,
            }
        )
    )
    for case_id, runs_k in per_case.items():
        for k, findings in enumerate(runs_k, 1):
            path = response_path(runs, model, version, case_id, k)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "result": {
                            "findings": findings,
                            "no_output": f"{case_id}-k{k}" in no_output,
                            "error": None,
                            "dropped": [],
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 1,
                                "cache_read_input_tokens": 0,
                            },
                            "elapsed_ms": 5,
                            "model": model,
                            "prompt_id": version[:12],
                            "context_used": "hunk_only",
                            "input_sha256": "abc",
                        },
                        "raw": {},
                    }
                )
            )


def test_merge_runs_writes_a_scorable_run(tmp_path: Path) -> None:
    write_run(tmp_path, "a", "m1", "v1-low", {"crv-0001": [[f(10)], [f(10)]]})
    write_run(
        tmp_path,
        "b",
        "m2",
        "v2-low",
        {"crv-0001": [[f(11)], []]},
        no_output=frozenset({"crv-0001-k2"}),
    )
    manifest = merge_runs("a", "b", "agreement", "ab-agree", tmp_path)
    assert manifest["model"] == "m1+m2" and manifest["merge"]["policy"] == "agreement"
    k1 = json.loads(
        response_path(tmp_path, "m1+m2", manifest["reviewer_version"], "crv-0001", 1).read_text()
    )["result"]
    k2 = json.loads(
        response_path(tmp_path, "m1+m2", manifest["reviewer_version"], "crv-0001", 2).read_text()
    )["result"]
    assert [x["line"] for x in k1["findings"]] == [10] and k1["usage"]["input_tokens"] == 20
    assert k2["no_output"] is True and k2["findings"] == []
    assert manifest["no_output"] == 1
    union = merge_runs("a", "b", "union", "ab-union", tmp_path)
    k2u = json.loads(
        response_path(tmp_path, "m1+m2", union["reviewer_version"], "crv-0001", 2).read_text()
    )["result"]
    assert k2u["no_output"] is False and [x["line"] for x in k2u["findings"]] == [10]


def test_merge_refuses_runs_with_different_cases(tmp_path: Path) -> None:
    write_run(tmp_path, "a", "m1", "v1-low", {"crv-0001": [[], []]})
    write_run(tmp_path, "b", "m2", "v2-low", {"crv-0002": [[], []]})
    with pytest.raises(ValueError, match="case_ids"):
        merge_runs("a", "b", "union", "x", tmp_path)
