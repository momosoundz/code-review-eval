# code-review-eval

A small AI code reviewer and the evaluation harness that decides whether a new version of it may ship.

The reviewer takes a diff and writes structured findings to a file. The harness runs it over a labeled dataset, matches findings to known defects, reports precision and recall with intervals, compares two reviewer versions case by case, and returns `PASS`, `FAIL` or `INCONCLUSIVE`. `EVAL.md` holds what was measured and where not to trust it.

## Setup

```bash
uv sync                      # Python 3.13, pinned dependencies
cp .env.example .env         # add ANTHROPIC_API_KEY (reviewer and judge calls)
make check                   # lint, types, tests
```

## Review a diff

```bash
make review DIFF=change.patch
make review REPO=. BASE=main HEAD=my-branch
```

Both write `findings.json`:

```json
{
  "findings": [
    {
      "file": "app/orders.py",
      "line": 41,
      "severity": "high",
      "category": "null_or_missing_value",
      "description": "The query no longer filters by tenant_id.",
      "rationale": "Any tenant can fetch another tenant's order by id.",
      "confidence": 0.9
    }
  ],
  "no_output": false,
  "error": null,
  "dropped": [],
  "usage": {"input_tokens": 812, "output_tokens": 96, "cache_read_input_tokens": 0},
  "elapsed_ms": 2140,
  "model": "claude-haiku-5-5",
  "prompt_id": "3f1c0a9b2e4d"
}
```

`line` is the post-change line number. `no_output: true` means the model refused or returned invalid JSON; the harness scores that as a miss, never as a clean review. A finding that cites a file or line outside the diff is dropped and its reason listed under `dropped`; the rest of the review stands. Exit code is 0 for a valid review, 2 for no usable output, 1 for a diff over the size cap.

The reviewer is one call to the Anthropic Messages API with a JSON schema enforced through structured outputs, no tools, no agent loop. The prompt is `reviewer/prompt.md`; `prompt_id` is a hash of prompt, schema and context mode, so two runs with the same id used the same reviewer. The default model is `claude-haiku-5-5` at effort `low`. One review of a 100-line diff costs well under a cent.

## Run the eval

```bash
make eval RUN=baseline K=5                 # K reviewer calls per case, raw responses stored, scored
make score RUN=baseline                    # re-scores from the committed files; never calls the API
make compare A=baseline-n49 B=exp2a-title-verified-n49
make report RUN=exp2a-title-verified-n49 BASELINE=baseline-n49   # markdown tables
```

A different model, effort or context mode is a different reviewer version:

```bash
uv run python -m eval.harness.collect --run exp2a --k 5 --split release \
    --model claude-haiku-5-5 --context-mode hunk_plus_title_verified
uv run python -m eval.harness.score --run exp2a --online   # judge calls for new pairs only
```

Cost, at the current price table: one Haiku run over the 49 release cases at K=5 is about 0.13 USD, one Sonnet run about 1.4 USD, and each new (finding, gold) pair the Opus judge has not seen costs about 0.006 USD; rescoring a committed run costs nothing. Expect `make eval` with a new reviewer version to spend under 1 USD with Haiku.

`python -m eval.harness.compare` exits 0 on `PASS`, 1 on `FAIL`, 2 on `INCONCLUSIVE`, so it can gate a pipeline; call the module directly for that, because `make` reports any failing recipe as 2. Runs with different gold hashes refuse to compare.

## What is where

| | |
|---|---|
| `EVAL.md` | what was measured, the results, and where not to trust them |
| `AGENTS.md` | conventions and invariants for anyone changing the code |
| `reviewer/` | the reviewer: prompt, schema, one API call, context modes |
| `eval/harness/` | collect, match, judge, score, compare, report, calibrate |
| `eval/dataset/` | the cases, `PROTOCOL.md` (how gold was built, labeled, adjudicated), `taxonomy.md` |
| `eval/labels/` | the human passes, adjudications, pair labels, and `errata.md` with every label change |
| `eval_runs/` | one directory per run with manifest, per-case scores and summary; raw responses under `responses/` |
| `scripts/` | the terminal tools the human uses: `review_cases.py`, `adjudicate.py`, `label_pairs.py` |

## Human in the loop

Three tools, all append-only, all resumable:

```bash
uv run python scripts/review_cases.py --pass 1 --split release   # blind pass over the gold
uv run python scripts/adjudicate.py --runs baseline-n49,exp2c-sonnet-n49   # alarms on clean cases
uv run python scripts/label_pairs.py                               # pairs that calibrate the judge
uv run python -m eval.harness.calibrate --runs baseline-n49,exp2a-title-verified-n49
```
