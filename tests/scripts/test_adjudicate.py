import json
from pathlib import Path

from eval.harness.collect import response_path, reviewer_version
from eval.harness.dataset import load_dataset
from scripts.adjudicate import already_done, claim_id, collect_claims, queue, record
from tests.conftest import meta, write_case


def finding(line: int = 41, description: str = "tenant filter missing", **over: object) -> dict:
    base = {
        "file": "app/orders.py",
        "line": line,
        "severity": "high",
        "category": "input_validation",
        "description": description,
        "rationale": "r",
        "confidence": 0.9,
    }
    base.update(over)
    return base


def write_run(runs: Path, run: str, model: str, mode: str, per_k: dict[int, list[dict]]) -> None:
    version = reviewer_version(mode, "low")
    (runs / run).mkdir(parents=True)
    (runs / run / "manifest.json").write_text(
        json.dumps(
            {"model": model, "reviewer_version": version, "k": len(per_k), "case_ids": ["crv-0001"]}
        )
    )
    for k, findings in per_k.items():
        path = response_path(runs, model, version, "crv-0001", k)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"result": {"no_output": False, "findings": findings}}))


def test_claims_are_grouped_by_anchor_across_runs_and_hide_their_origin(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(runs, "a", "claude-haiku-5-5", "hunk_only", {1: [finding()], 2: [finding()]})
    write_run(
        runs,
        "b",
        "claude-sonnet-5-5",
        "hunk_only",
        {1: [finding(description="the tenant filter is gone"), finding(line=42, description="x")]},
    )
    claims = sorted(collect_claims(runs, ["a", "b"], "crv-0001"), key=lambda c: -c.count)
    assert [(c.line, c.count, len(c.variants)) for c in claims] == [(41, 3, 2), (42, 1, 1)]
    assert not any(hasattr(c, "model") or hasattr(c, "severity") for c in claims)


def test_low_severity_and_maintainability_are_not_claims(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(
        runs,
        "a",
        "claude-haiku-5-5",
        "hunk_only",
        {1: [finding(severity="low"), finding(line=42, category="maintainability")]},
    )
    assert collect_claims(runs, ["a"], "crv-0001") == []


def test_claim_id_is_the_anchor() -> None:
    assert claim_id("c", "f.py", 1) == claim_id("c", "f.py", 1)
    assert claim_id("c", "f.py", 1) != claim_id("c", "f.py", 2)


def test_queue_orders_alarmed_clean_cases_by_claim_count(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(runs, "a", "claude-haiku-5-5", "hunk_only", {1: [finding()], 2: [finding()]})
    write_case(tmp_path / "cases", "crv-0001", {"expected_findings": []}, meta(source="clean"))
    write_case(tmp_path / "cases", "crv-0002", {"expected_findings": []}, meta(source="clean"))
    cases = load_dataset(tmp_path / "cases")
    claims = {c.case_id: collect_claims(runs, ["a"], c.case_id) for c in cases}
    assert [c.case_id for c in queue(cases, claims)] == ["crv-0001"]


def test_record_carries_the_audit_fields_and_resume_reads_them(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(runs, "a", "claude-haiku-5-5", "hunk_only", {1: [finding()]})
    write_case(tmp_path / "cases", "crv-0001", {"expected_findings": []}, meta(source="clean"))
    case = load_dataset(tmp_path / "cases")[0]
    claim = collect_claims(runs, ["a"], "crv-0001")[0]
    decision: dict[str, object] = {"blind_assessment": "fine", "verdict": "fp", "reason": "ok"}
    rec = record(claim, case, decision, "m")
    for key in (
        "diff_sha256",
        "claim_id",
        "claim_variants",
        "sources",
        "blind_assessment",
        "verdict",
        "reason",
        "adjudicator",
        "adjudicated_at",
        "rules_version",
    ):
        assert key in rec
    out = tmp_path / "adj.jsonl"
    out.write_text(json.dumps(rec) + "\n")
    assert already_done(out) == {(claim.claim_id, case.diff_sha256)}
    assert (claim.claim_id, "another-diff") not in already_done(out)
