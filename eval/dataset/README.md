# Dataset

One directory per case under `cases/`. A case is a diff the reviewer sees and the defects we know are in it.

```
cases/crv-0006/
  diff.patch      what the reviewer receives, nothing else
  expected.json   gold findings (empty list for a clean diff) and optional decoys
  meta.json       family, split, source, provenance, status
```

## expected.json

| field | meaning |
|---|---|
| `case_id` | matches the directory name; monotonic, never reused |
| `expected_findings[]` | one entry per defect |
| `.gold_id` | `<case_id>-gN` |
| `.file` | post-change path as it appears in the diff |
| `.spans` | one or more `[start, end]` post-change line ranges where the defect lives |
| `.also[]` | optional extra locations (`{file, spans}`) where the same defect manifests, such as a call site in another file; a finding anchored there counts |
| `.category` | one of the categories in `taxonomy.md` |
| `.severity` | `high`, `medium` or `low`; `high` is the gate slice |
| `.root_cause` | one sentence the judge compares a finding against |
| `.failure_path` | trigger, mechanism and observable impact |
| `.needs_context_beyond_diff` | true when the evidence lives outside the diff; such cases are reported separately |
| `decoys[]` | correct-looking spans that are fine, with the reason; informational |

## meta.json

| field | values |
|---|---|
| `family_id` | cases built from the same base diff share one; the bootstrap resamples by family |
| `split` | `dev` (prompt iteration) or `release` (frozen, headline numbers) |
| `source` | `seeded`, `real_reversed`, `clean`, `discovered` |
| `provenance` | repo, commit, paths, and what was changed to build the case |
| `status` | `active` or `deprecated`; deprecated needs `deprecated_reason` and is never deleted |

## How cases are built

**Clean.** The production-code hunks of a merged commit from one of the author's repositories, taken as they were merged. The reviewer should find nothing of severity medium or high.

**Seeded.** The same clean diff with one defect written in by hand: one changed token or line, no comment that gives it away, drawn from the taxonomy. The pair shares a `family_id`, so the clean and seeded versions give a false-positive measurement on identical context.

**Real reversed.** A merged bug-fix commit replayed backwards, so the diff introduces the defect the fix removed. The fix's commit message and the project notes supply the failure path. Only the production hunks are included; tests that would reveal the answer are not.

**Discovered.** A finding the reviewer made that no gold covered and that a human confirmed as a real defect. It is added to gold under this source and both compared runs are rescored.

## Known biases

- Seeded defects are a single edit each. They are easier to spot than defects buried in a feature-sized change. The per-source slice in the report keeps the two apart.
- Clean means reviewed by one person against the stated scope, not proven bug-free. A confirmed finding on a clean case reclassifies it in a new dataset version.
- All cases are Python and come from a few repositories by the same author. Numbers generalize to that distribution, not to code review in general.
- Commits from public repositories may be in the model's training data. Seeded variants differ from any committed code; reversed fixes are reported as their own slice.

`gold_hash` hashes the scoring fields (ids, diffs, spans, categories, severities, root causes, splits, status). Any change to them is a new dataset version and makes earlier runs incomparable; notes and decoys do not enter the hash.
