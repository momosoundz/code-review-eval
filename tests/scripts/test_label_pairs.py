import json
from pathlib import Path

import pytest

from scripts.label_pairs import already_done, ask, load_pairs, sample_pairs


def write_store(root: Path, version: str, rows: list[tuple[str, str, str, str]]) -> Path:
    for case_id, gold_id, key, verdict in rows:
        d = root / version / case_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{gold_id}-{key}.json").write_text(
            json.dumps({"case_id": case_id, "gold_id": gold_id, "input": "txt", "verdict": verdict})
        )
    return root


def test_sample_keeps_every_no_match_and_caps_matches_per_gold(tmp_path: Path) -> None:
    rows = [("crv-0001", "crv-0001-g1", f"k{i}", "match") for i in range(5)]
    rows += [
        ("crv-0001", "crv-0001-g1", "n1", "no_match"),
        ("crv-0002", "crv-0002-g1", "n2", "no_match"),
    ]
    rows += [("crv-0002", "crv-0002-g1", "m1", "match")]
    pairs = load_pairs(write_store(tmp_path, "v", rows), "v")
    sample = sample_pairs(pairs, per_gold=2, seed=1)
    ids = {p.pair_id for p in sample}
    assert {"crv-0001-g1-n1", "crv-0002-g1-n2", "crv-0002-g1-m1"} <= ids
    assert sum(p.gold_id == "crv-0001-g1" and p.verdict == "match" for p in sample) == 2
    assert [p.pair_id for p in sample] == [p.pair_id for p in sample_pairs(pairs, 2, 1)]


def test_pair_id_matches_the_verdict_file_stem(tmp_path: Path) -> None:
    pairs = load_pairs(
        write_store(tmp_path, "v", [("crv-0001", "crv-0001-g1", "abc", "match")]), "v"
    )
    assert pairs[0].pair_id == "crv-0001-g1-abc" and pairs[0].key == "abc"


def test_already_done_is_keyed_by_judge_version_and_skips_a_truncated_line(tmp_path: Path) -> None:
    out = tmp_path / "labels.jsonl"
    out.write_text(
        json.dumps({"pair_id": "crv-0001-g1-abc", "judge_version": "v1", "label": "same"})
        + "\n"
        + '{"pair_id": "crv-0001-g1-def", "judge_ver'
    )
    assert already_done(out) == {("crv-0001-g1-abc", "v1")}
    assert ("crv-0001-g1-abc", "v2") not in already_done(out)


def test_ask_rejects_multi_character_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["sd", "", "x", "d"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert ask("?", "sdu") == "d"
