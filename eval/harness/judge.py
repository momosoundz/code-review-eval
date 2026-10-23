"""Binary LLM judge: does a finding describe the same defect as a gold label? Verdicts cached."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eval.harness.dataset import GoldFinding
from reviewer import llm

JUDGE_MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "medium"
JUDGE_DIR = Path(__file__).with_name("judge")
PROMPT_PATH = JUDGE_DIR / "prompt.md"
SCHEMA_PATH = JUDGE_DIR / "schema.json"
VERDICTS_DIR = JUDGE_DIR / "verdicts"
VERDICTS = ("match", "no_match", "unknown")


class JudgeUnavailableError(RuntimeError):
    """Offline scoring needed a verdict that was never cached."""


class JudgeResponseError(RuntimeError):
    """The judge returned something that is not a verdict; nothing is cached, rerun later."""


def _create_message(**kwargs: Any) -> Any:
    return llm.client().messages.create(**kwargs)


def judge_prompt_hash() -> str:
    """Hash of the judge prompt and schema; a change invalidates every cached verdict."""
    blob = PROMPT_PATH.read_text() + SCHEMA_PATH.read_text()
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _pair_text(finding: dict[str, Any], gold: GoldFinding) -> str:
    """What the judge sees: the label and the finding's text, never its severity or category."""
    return (
        f"Labeled defect\n"
        f"- root cause: {gold.root_cause}\n"
        f"- failure path: {gold.failure_path}\n\n"
        f"Reviewer finding\n"
        f"- description: {finding['description']}\n"
        f"- rationale: {finding['rationale']}\n"
    )


def pair_key(
    model: str, prompt_hash: str, case_id: str, gold: GoldFinding, finding: dict[str, Any]
) -> str:
    """Short content hash of one (finding, gold) judgment; distinct finding text, distinct key."""
    blob = "\n".join([model, prompt_hash, case_id, gold.gold_id, _pair_text(finding, gold)])
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


class Judge:
    """Match judge with a committed verdict store; ``offline=True`` never calls the API."""

    def __init__(
        self,
        model: str = JUDGE_MODEL,
        effort: str = JUDGE_EFFORT,
        verdicts_dir: Path = VERDICTS_DIR,
        offline: bool = False,
    ) -> None:
        """Bind the judge to a model, an effort level and the directory of cached verdicts."""
        self.model = model
        self.effort = effort
        self.verdicts_dir = verdicts_dir
        self.offline = offline
        self.prompt_hash = judge_prompt_hash()
        self.calls = 0

    def verdict_path(self, case_id: str, gold_id: str, key: str) -> Path:
        """``<judge version>/<case>/<gold>-<key>.json``: readable path, hash for uniqueness."""
        version = f"{self.model}-{self.prompt_hash}"
        return self.verdicts_dir / version / case_id / f"{gold_id}-{key}.json"

    def decide(self, case_id: str, finding: dict[str, Any], gold: GoldFinding) -> str:
        """Return ``match``, ``no_match`` or ``unknown`` for the pair, from cache when possible."""
        key = pair_key(self.model, self.prompt_hash, case_id, gold, finding)
        path = self.verdict_path(case_id, gold.gold_id, key)
        if path.exists():
            record = json.loads(path.read_text())
            if record.get("input") != _pair_text(finding, gold) or record.get("verdict") not in (
                "match",
                "no_match",
            ):
                msg = f"cached verdict at {path} does not match its pair or holds a bad verdict"
                raise JudgeResponseError(msg)
            return str(record["verdict"])
        if self.offline:
            msg = f"no cached verdict for {case_id}/{gold.gold_id} (key {key}); run with an API key"
            raise JudgeUnavailableError(msg)
        record = self._ask(case_id, finding, gold)
        if record["verdict"] != "unknown":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n")
        return str(record["verdict"])

    def _ask(self, case_id: str, finding: dict[str, Any], gold: GoldFinding) -> dict[str, Any]:
        self.calls += 1
        response = _create_message(
            model=self.model,
            max_tokens=2_000,
            system=PROMPT_PATH.read_text(),
            messages=[{"role": "user", "content": _pair_text(finding, gold)}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": json.loads(SCHEMA_PATH.read_text())},
            },
        )
        parsed = _parse(response)
        usage = response.usage
        return {
            "case_id": case_id,
            "gold_id": gold.gold_id,
            "judge_model": self.model,
            "judge_prompt_hash": self.prompt_hash,
            "input": _pair_text(finding, gold),
            "critique": parsed.get("critique", ""),
            "verdict": parsed.get("verdict", "unknown"),
            "usage": {
                "input_tokens": int(usage.input_tokens),
                "output_tokens": int(usage.output_tokens),
            },
        }


def _parse(response: Any) -> dict[str, Any]:
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"judge returned invalid JSON: {text[:200]!r}"
        raise JudgeResponseError(msg) from exc
    if parsed.get("verdict") not in VERDICTS:
        msg = f"judge returned an unknown verdict: {parsed.get('verdict')!r}"
        raise JudgeResponseError(msg)
    return parsed
