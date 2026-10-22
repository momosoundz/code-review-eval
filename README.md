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
  "usage": {"input_tokens": 812, "output_tokens": 96, "cache_read_input_tokens": 0},
  "model": "claude-haiku-5-5",
  "prompt_id": "3f1c0a9b2e4d"
}
```

`line` is the post-change line number. `no_output: true` means the model refused, returned invalid JSON or cited a line outside the diff; the harness scores that as a miss, never as a clean review. Exit code is 0 for a valid review, 2 for no usable output, 1 for a diff over the size cap.

The reviewer is one call to the Anthropic Messages API with a JSON schema enforced through structured outputs, no tools, no agent loop. The prompt is `reviewer/prompt.md`; `prompt_id` is a hash of prompt, schema and context mode, so two runs with the same id used the same reviewer. The default model is `claude-haiku-5-5` at effort `low`. One review of a 100-line diff costs well under a cent.

## Run the eval

```bash
make eval RUN=baseline K=5    # calls the model K times per case, caches raw outputs, scores
make score RUN=baseline       # re-scores from the committed caches; no API key needed
make compare A=baseline B=exp1
```

See `EVAL.md` for the dataset, the matching rule, the gate and the results.
