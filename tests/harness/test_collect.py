import json
from dataclasses import replace
from pathlib import Path

import pytest

from eval.harness import collect
from eval.harness.collect import (
    BudgetExceededError,
    CollectSettings,
    UnknownModelError,
    collect_run,
    response_path,
    reviewer_version,
)
from eval.harness.dataset import load_dataset
from reviewer.config import CONTEXT_MODE
from reviewer.diffs import number_diff
from reviewer.review import ReviewResult, input_sha256
from tests.conftest import gold, meta, write_case


def fake_result(no_output: bool = False, tokens: int = 1000) -> ReviewResult:
    findings = (
        []
        if no_output
        else [
            {
                "file": "app/orders.py",
                "line": 41,
                "severity": "high",
                "category": "input_validation",
                "description": "d",
                "rationale": "r",
                "confidence": 0.9,
            }
        ]
    )
    usage = {"input_tokens": tokens, "output_tokens": 100, "cache_read_input_tokens": 0}
    return ReviewResult(
        findings,
        no_output,
        "refused" if no_output else None,
        [],
        usage,
        1200,
        "claude-haiku-5-5",
        "p1",
        "hunk_only",
        "",
    )


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    cases = tmp_path / "cases"
    write_case(cases, "crv-0001", {"expected_findings": []}, meta(source="clean", split="dev"))
    write_case(
        cases, "crv-0002", {"expected_findings": [gold(gold_id="crv-0002-g1")]}, meta(split="dev")
    )
    return cases


def test_collect_writes_one_response_per_case_and_run(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str | None]] = []

    def fake_review(
        diff: str, model: str, effort: str, mode: str, title: str | None = None
    ) -> tuple[ReviewResult, dict]:
        calls.append((diff[:10], mode, title))
        return fake_result(), {"id": "msg"}

    monkeypatch.setattr(collect, "review_diff", fake_review)
    runs = tmp_path / "runs"
    manifest = collect_run(
        "baseline", k=2, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    assert len(calls) == 4
    entry = json.loads(
        response_path(
            runs,
            "claude-haiku-5-5",
            reviewer_version(CONTEXT_MODE, "low"),
            "crv-0002",
            1,
        ).read_text()
    )
    assert entry["result"]["findings"][0]["line"] == 41
    assert entry["raw"] == {"id": "msg"}
    assert manifest["k"] == 2
    assert manifest["case_ids"] == ["crv-0001", "crv-0002"]
    assert manifest["calls_made"] == 4
    assert (runs / "baseline" / "manifest.json").exists()


def test_collect_never_overwrites_existing_entries(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(
        collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {"v": 1})
    )
    collect_run(
        "baseline", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    monkeypatch.setattr(
        collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {"v": 2})
    )
    manifest = collect_run(
        "baseline", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    entry = json.loads(
        response_path(
            runs,
            "claude-haiku-5-5",
            reviewer_version(CONTEXT_MODE, "low"),
            "crv-0001",
            1,
        ).read_text()
    )
    assert entry["raw"] == {"v": 1}
    assert manifest["calls_made"] == 0
    assert manifest["cache_hits"] == 2


def test_no_output_is_recorded_not_skipped(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(no_output=True), {})
    )
    runs = tmp_path / "runs"
    manifest = collect_run(
        "baseline", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    entry = json.loads(
        response_path(
            runs,
            "claude-haiku-5-5",
            reviewer_version(CONTEXT_MODE, "low"),
            "crv-0002",
            1,
        ).read_text()
    )
    assert entry["result"]["no_output"] is True
    assert manifest["no_output"] == 2


def test_budget_stops_the_run(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(tokens=10_000_000), {})
    )
    with pytest.raises(BudgetExceededError, match="budget"):
        collect_run(
            "baseline",
            k=3,
            cases=load_dataset(dataset),
            settings=CollectSettings(runs_dir=tmp_path / "runs", budget_usd=0.5),
        )


def test_manifest_records_versions(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    manifest = collect_run(
        "baseline",
        k=1,
        cases=load_dataset(dataset),
        settings=CollectSettings(runs_dir=tmp_path / "runs"),
    )
    for key in (
        "model",
        "effort",
        "prompt_id",
        "context_mode",
        "gold_hash",
        "git_sha",
        "started_at",
        "finished_at",
        "cost_usd",
        "split",
    ):
        assert key in manifest, key


def test_effort_gets_its_own_responses(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    collect_run("low", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs))
    manifest = collect_run(
        "high",
        k=1,
        cases=load_dataset(dataset),
        settings=CollectSettings(runs_dir=runs, effort="high"),
    )
    assert manifest["calls_made"] == 2 and manifest["cache_hits"] == 0


def test_unknown_model_is_refused(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    with pytest.raises(UnknownModelError, match="no price"):
        collect_run(
            "x",
            k=1,
            cases=load_dataset(dataset),
            settings=CollectSettings(runs_dir=tmp_path / "runs", model="claude-typo-9"),
        )


def test_manifest_refuses_a_different_shape(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    collect_run(
        "baseline", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    with pytest.raises(FileExistsError, match="different run"):
        collect_run(
            "baseline", k=2, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
        )


def test_manifest_refuses_a_different_effort_under_the_same_run_name(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    collect_run(
        "baseline", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs)
    )
    with pytest.raises(FileExistsError, match="different run"):
        collect_run(
            "baseline",
            k=1,
            cases=load_dataset(dataset),
            settings=CollectSettings(runs_dir=runs, effort="high"),
        )


def test_budget_counts_cached_spend(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(
        collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(tokens=3_000_000), {})
    )
    settings = CollectSettings(runs_dir=runs, budget_usd=0.5)
    collect_run("a", k=1, cases=load_dataset(dataset)[:1], settings=settings)
    with pytest.raises(BudgetExceededError):
        collect_run("b", k=1, cases=load_dataset(dataset), settings=settings)


def test_context_mode_gets_its_own_responses_and_passes_the_title(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str | None]] = []

    def fake(d: str, m: str, e: str, c: str, t: str | None = None) -> tuple[ReviewResult, dict]:
        seen.append((c, t))
        return fake_result(), {}

    monkeypatch.setattr(collect, "review_diff", fake)
    runs = tmp_path / "runs"
    collect_run("a", k=1, cases=load_dataset(dataset), settings=CollectSettings(runs_dir=runs))
    manifest = collect_run(
        "b",
        k=1,
        cases=load_dataset(dataset),
        settings=CollectSettings(runs_dir=runs, context_mode="hunk_plus_title"),
    )
    assert manifest["calls_made"] == 2 and manifest["context_mode"] == "hunk_plus_title"
    assert seen[-1][0] == "hunk_plus_title"


def test_title_reaches_the_reviewer_and_a_changed_title_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = tmp_path / "cases"
    write_case(
        cases,
        "crv-0002",
        {"expected_findings": [gold(gold_id="crv-0002-g1")]},
        meta(provenance={"repo": "x", "commit": "abc", "commit_title": "Add tenant check"}),
    )
    seen: list[str | None] = []

    def fake(d: str, m: str, e: str, c: str, t: str | None = None) -> tuple[ReviewResult, dict]:
        seen.append(t)

        digest = input_sha256(number_diff(d).text, c, t)
        return replace(fake_result(), input_sha256=digest), {}

    monkeypatch.setattr(collect, "review_diff", fake)
    runs = tmp_path / "runs"
    settings = CollectSettings(runs_dir=runs, context_mode="hunk_plus_title")
    collect_run("a", k=1, cases=load_dataset(cases), settings=settings)
    assert seen == ["Add tenant check"]
    meta_path = cases / "crv-0002" / "meta.json"
    changed = json.loads(meta_path.read_text())
    changed["provenance"]["commit_title"] = "Something else"
    meta_path.write_text(json.dumps(changed))
    with pytest.raises(FileExistsError, match="different input"):
        collect_run("b", k=1, cases=load_dataset(cases), settings=settings)


def test_manifest_lists_cases_without_title_in_title_mode(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "review_diff", lambda d, m, e, c, t=None: (fake_result(), {}))
    manifest = collect_run(
        "t",
        k=1,
        cases=load_dataset(dataset),
        settings=CollectSettings(runs_dir=tmp_path / "runs", context_mode="hunk_plus_title"),
    )
    assert manifest["cases_without_title"] == ["crv-0001", "crv-0002"]
