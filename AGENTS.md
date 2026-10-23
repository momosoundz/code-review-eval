# Working in this repo

Rules for any agent or person changing this code. Everything is in English: code, comments, gold labels, docs, commit messages.

## Toolchain

`uv` for the environment, `ruff` for lint and format, `ty` for types, `pytest` for tests, `prek` for the pre-commit hook. `make check` runs all four and must be green before anything is staged. Zero warnings: fix them or add an inline ignore with a reason.

Hard limits, enforced by ruff: functions under 100 lines, cyclomatic complexity 8, 5 positional parameters, 100-character lines. Absolute imports only. Google-style docstrings on public functions that do something non-trivial; no comments that restate the code.

## Where things live

| concern | module |
|---|---|
| numbering a diff | `reviewer/diffs.py` |
| the model call and the output contract | `reviewer/review.py`, `reviewer/prompt.md`, `reviewer/schema.json` |
| the Anthropic client | `reviewer/llm.py` (the only module that imports `anthropic`) |
| what the reviewer is: model, effort, size cap, taxonomy | `reviewer/config.py` |
| how it is scored: tolerance, floors, bootstrap, budget | `eval/harness/config.py` |
| dataset contract and validation | `eval/harness/dataset.py`, `eval/dataset/README.md` |
| storing responses | `eval/harness/collect.py` |
| matching a finding to a gold defect | `eval/harness/match.py` |
| the judge and its verdict store | `eval/harness/judge.py`, `eval/harness/judge/` |
| statistics | `eval/harness/stats.py` |
| scoring a run, comparing two runs | `eval/harness/score.py`, `eval/harness/compare.py` |

`eval/` imports from `reviewer/`, never the reverse. A constant goes in a config module when it is recorded in a run manifest or changed between experiments; a constant with one consumer stays in that module. The defect taxonomy has one source, `reviewer/config.py`; `tests/reviewer/test_schema.py` fails if the schema, the prompt or `eval/dataset/taxonomy.md` drift from it.

## Harness invariants

- A model response is written once to `eval_runs/responses/<model>/<prompt_id>-<effort>/<case>/<case>-k<k>.json` and never rewritten. A new prompt, schema, context mode or effort is a new directory.
- A judge verdict is written once to `eval/harness/judge/verdicts/<judge model>-<judge prompt hash>/<case>/<gold>-<hash>.json`. The path says what it judged; the hash keeps distinct findings apart. `unknown` verdicts and malformed responses are never cached.
- `make score` reruns from those files alone, without an API key, and produces byte-identical output. Anything that breaks this is a bug.
- A refusal or invalid JSON is `no_output` and scores as a miss. A single finding outside the diff is dropped and listed, not a reason to void the review.
- Gold cases are never deleted; they are deprecated with a reason. Any change to a scoring field is a new `gold_hash`, and runs with different hashes are not comparable. Label corrections are recorded in `eval/labels/errata.md`; the review files there are never edited.
- Matching does not depend on category. A defect of an unforeseen type is labeled `other` and scored like any other.
- Fewer than 20 families can never produce a `PASS`. Slices under 20 cases are reported with intervals and never gate.

## How a change lands

1. Write the test for the behavior first, then the code. Mock the network boundary only (`_create_message`), never the logic.
2. Run `make check`. Stage. Do not commit.
3. Run an adversarial review of the staged diff (a second model or a fresh agent, with the mandate to break it) and a standards pass against this file. Fix what is real; write down what was rejected and why.
4. The human reviews the staged diff and gives the go. Then commit, one logical change per commit: `type(scope): verb object`, 72 characters, body says why. Never `--no-verify`.
5. Push and PRs only on explicit instruction.

## What not to add

No second provider, framework, abstraction layer, retry loop, cache beyond the response store, or metric until a run shows the number it would change. A feature that nobody measured is not in this repo.
