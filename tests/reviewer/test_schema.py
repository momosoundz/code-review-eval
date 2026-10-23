import json

from eval.harness.config import ROOT
from reviewer.config import CATEGORIES, NON_GATED_CATEGORIES, PROMPT_PATH, SCHEMA_PATH, SEVERITIES

TAXONOMY_PATH = ROOT / "eval" / "dataset" / "taxonomy.md"


def test_schema_enums_match_config() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    finding = schema["properties"]["findings"]["items"]["properties"]
    assert tuple(finding["category"]["enum"]) == CATEGORIES + NON_GATED_CATEGORIES
    assert tuple(finding["severity"]["enum"]) == SEVERITIES


def test_prompt_and_taxonomy_list_every_category() -> None:
    prompt = PROMPT_PATH.read_text()
    taxonomy = TAXONOMY_PATH.read_text()
    for category in CATEGORIES + NON_GATED_CATEGORIES:
        assert category in prompt
        assert f"| `{category}` |" in taxonomy
