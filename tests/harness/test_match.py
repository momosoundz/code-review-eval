from eval.harness.dataset import GoldFinding
from eval.harness.match import MatchOutcome, eligible_pairs, match_case

GOLD = GoldFinding(
    "g1",
    (("app/orders.py", ((41, 41),)),),
    "input_validation",
    "high",
    "lookup drops the tenant filter",
    "tenant A reads tenant B's order",
    False,
)
GOLD2 = GoldFinding(
    "g2",
    (("app/orders.py", ((60, 62),)),),
    "error_handling",
    "medium",
    "exception swallowed",
    "a failing write returns success",
    False,
)


def finding(
    file: str = "app/orders.py",
    line: int = 41,
    severity: str = "high",
    category: str = "input_validation",
    description: str = "tenant filter missing",
) -> dict:
    return {
        "file": file,
        "line": line,
        "severity": severity,
        "category": category,
        "description": description,
        "rationale": "r",
        "confidence": 0.9,
    }


def always_match(f: dict, g: GoldFinding) -> str:
    return "match"


def never_match(f: dict, g: GoldFinding) -> str:
    return "no_match"


def test_eligible_within_tolerance() -> None:
    assert eligible_pairs([finding(line=44)], [GOLD], tolerance=3) == [(0, "g1", 3)]
    assert eligible_pairs([finding(line=45)], [GOLD], tolerance=3) == []
    assert eligible_pairs([finding(line=38)], [GOLD], tolerance=3) == [(0, "g1", 3)]


def test_eligible_requires_same_file() -> None:
    assert eligible_pairs([finding(file="app/other.py")], [GOLD], tolerance=3) == []


def test_eligible_uses_span_edges() -> None:
    assert eligible_pairs([finding(line=59)], [GOLD2], tolerance=0) == []
    assert eligible_pairs([finding(line=61)], [GOLD2], tolerance=0) == [(0, "g2", 0)]
    assert eligible_pairs([finding(line=63)], [GOLD2], tolerance=1) == [(0, "g2", 1)]


def test_exact_match_is_tp() -> None:
    out = match_case([finding()], [GOLD], always_match, tolerance=3)
    assert isinstance(out, MatchOutcome)
    assert out.matched == {"g1": 0}
    assert out.tp == 1 and out.fp == 0 and out.fn == 0 and out.noise == 0


def test_judge_rejection_is_fp() -> None:
    out = match_case([finding(description="SQL injection")], [GOLD], never_match, tolerance=3)
    assert out.tp == 0 and out.fp == 1 and out.fn == 1


def test_low_severity_unmatched_is_noise_not_fp() -> None:
    out = match_case([finding(line=41, severity="low")], [GOLD], never_match, tolerance=3)
    assert out.fp == 0 and out.noise == 1 and out.fn == 1


def test_maintainability_is_noise_even_when_high() -> None:
    out = match_case([finding(category="maintainability", severity="high")], [GOLD], never_match, 3)
    assert out.fp == 0 and out.noise == 1


def test_duplicate_on_matched_gold_is_noise() -> None:
    out = match_case([finding(line=41), finding(line=42)], [GOLD], always_match, tolerance=3)
    assert out.tp == 1 and out.fp == 0 and out.noise == 1 and out.duplicates == 1


def test_one_finding_matches_at_most_one_gold() -> None:
    close = GoldFinding(
        "g3", (("app/orders.py", ((42, 42),)),), "boundary", "high", "x", "y", False
    )
    out = match_case([finding(line=41)], [GOLD, close], always_match, tolerance=3)
    assert out.tp == 1 and out.fn == 1


def test_closest_gold_wins_then_gold_id() -> None:
    far = GoldFinding("g0", (("app/orders.py", ((44, 44),)),), "boundary", "high", "x", "y", False)
    out = match_case([finding(line=41)], [far, GOLD], always_match, tolerance=3)
    assert out.matched == {"g1": 0}


def test_empty_review_on_buggy_case() -> None:
    out = match_case([], [GOLD], always_match, tolerance=3)
    assert out.tp == 0 and out.fn == 1 and out.fp == 0


def test_empty_review_on_clean_case() -> None:
    out = match_case([], [], always_match, tolerance=3)
    assert out.tp == out.fp == out.fn == out.noise == 0


def test_finding_on_clean_case_is_fp() -> None:
    out = match_case([finding()], [], always_match, tolerance=3)
    assert out.fp == 1 and out.tp == 0


def test_judge_only_called_for_eligible_pairs() -> None:
    calls: list[str] = []

    def spy(f: dict, g: GoldFinding) -> str:
        calls.append(g.gold_id)
        return "no_match"

    match_case([finding(line=41), finding(line=90)], [GOLD], spy, tolerance=3)
    assert calls == ["g1"]


def test_unknown_verdict_is_neither_tp_nor_fp_and_is_flagged() -> None:
    out = match_case([finding()], [GOLD], lambda f, g: "unknown", tolerance=3)
    assert out.tp == 0 and out.fp == 0 and out.fn == 1
    assert out.unknown_pairs == [(0, "g1")]


def test_unmatched_high_finding_near_matched_gold_is_fp_not_duplicate() -> None:
    def judge(f: dict, g: GoldFinding) -> str:
        return "match" if f["description"] == "tenant filter missing" else "no_match"

    out = match_case(
        [finding(line=41), finding(line=43, description="SQL injection")],
        [GOLD],
        judge,
        tolerance=3,
    )
    assert out.tp == 1 and out.fp == 1 and out.duplicates == 0


def test_unknown_then_match_on_other_gold_is_not_flagged() -> None:
    other = GoldFinding(
        "g9", (("app/orders.py", ((43, 43),)),), "boundary", "high", "x", "y", False
    )

    def judge(f: dict, g: GoldFinding) -> str:
        return "unknown" if g.gold_id == "g1" else "match"

    out = match_case([finding(line=42)], [GOLD, other], judge, tolerance=3)
    assert out.matched == {"g9": 0} and out.unknown_pairs == []


def test_gold_with_a_second_location_in_another_file() -> None:
    gold = GoldFinding(
        "g1",
        (("src/rag.py", ((55, 55),)), ("src/agents.py", ((94, 94),))),
        "null_or_missing_value",
        "medium",
        "max without default",
        "crash",
        False,
    )
    assert eligible_pairs([finding(file="src/agents.py", line=95)], [gold], tolerance=3) == [
        (0, "g1", 1)
    ]
    assert eligible_pairs([finding(file="src/other.py", line=55)], [gold], tolerance=3) == []
