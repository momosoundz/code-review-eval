# Labeling protocol

How the release set was built and validated, so a reader can judge the gold before trusting the numbers.

## Roles

- **Base selection** (agent, Claude): merged commits from tenacity, click and requests, 1 or 2 production files, 15 to 85 diff lines, no test or doc hunks. Chosen by size and domain variety, before any reviewer ran on them.
- **Seeding** (agent, Codex, fresh session per repository): writes one defect into each clean diff. It receives the clean patch, the assigned category, `taxonomy.md`, the gold schema and the rules below. It does not see the reviewer prompt, any reviewer output, or the other repositories' cases.
- **Reversed fixes** (agent, Claude): a merged bug fix replayed backwards; the gold is written from the fix's own commit message and tests, before any reviewer runs on the case.
- **Validation** (human, Miguel): every release case, two passes with `scripts/review_cases.py`. Pass 1 is blind: the diff only, then the gold and the checklist. Pass 2 is the same at least two weeks later, reshuffled, without the first answers in view. Reported as intra-rater stability, never as inter-rater agreement.

## Seeding rules

1. One defect per diff, in the assigned category. The category list is balanced across the set before seeding starts.
2. The defect must be inferable from the diff alone: trigger, mechanism and observable impact must be visible in the hunks, not in repository knowledge.
3. No comment, name, TODO or scaffolding that points at the defect. The edit should read like a plausible mistake in that commit.
4. One or a few lines changed. The rest of the diff is the merged original; it stays intact and serves as healthy context.
5. `root_cause` names the faulty operation; `failure_path` gives a concrete trigger and what the user or operator observes. Neither reuses phrases from the reviewer prompt.
6. Severity follows the anchors in `taxonomy.md`; it is assigned to the defect, not to the category.
7. A seed is never kept or dropped because of whether any reviewer caught it.
8. **Telltale** means any text in the diff that names the defect or its fix: a planted comment, but also a docstring, a changelog note or a comment carried over from the real history. Reversed fixes have such text removed from the deleted side, and from the added side when the pre-fix code carried it.
9. The primary gold location must touch a changed line: a `+` line, the context line right after a deleted block, or the last line of a hunk that ends in a deletion. `also` locations may sit on context. A defect that only exists in untouched context is not a defect of this change.
10. When the gold depends on a definition or a consumer that the change does not touch, that code is added as a context-only hunk, so the defect can be derived from the diff alone. The provenance note says so.
11. In a title context mode, a case without a commit title is reviewed as `hunk_only`; the manifest lists those cases and the report says so. Reversed fixes carry no title by construction.

## What the first pass changed

Pass 1 on the release set returned six `f` verdicts and no `d`. They produced: one re-seed (crv-0020), one diff whose gold edit had been placed on a context line (crv-0042), three cases that needed a definition or consumer as context (crv-0046, crv-0049, crv-0050), two reversed fixes whose docstrings gave the defect away (crv-0045, crv-0048), four severity or category corrections under the new rules, and one dev case deprecated because its code equals a buggy state labeled elsewhere (crv-0003). Every change is in `eval/labels/errata.md`.

## Adjudicating alarms on clean cases (rules v1, frozen 2026-10-24)

A clean case is a merged commit with no known defect. When a reviewer arm alarms on one, the alarm is a false positive until a human says otherwise, and the human may say otherwise: crv-0013 and crv-0014 were clean until a 5-of-5 alarm turned out to be a real defect. Because a strong model that insists gets more chances to move the gold, the adjudication follows these rules, written before any verdict of this round was recorded. Every record cites the rule version.

1. **Every claim is adjudicated, not only the loud ones.** The queue holds the union of distinct findings of severity medium or high from every arm on every clean case of the release split, singletons included. Frequency and model identity are hidden; frequency only orders the queue.
2. **Blind first.** The adjudicator reads the numbered diff and records their own assessment before any claim is shown. Then the claims appear, shuffled and deduplicated, as text only.
3. **Three verdicts per claim:** `fp`, `defect`, `unresolved`. Doubt is never forced into `fp`. A `defect` needs a changed-line anchor, a concrete trigger, the mechanism, the observable impact and a severity justified by `taxonomy.md`; it must be inferable from the diff (rule 2 of seeding) and is checked against upstream evidence when it exists. An `fp` names the premise that fails.
4. **A `defect` becomes gold through errata**, with the case source moved to `discovered`, a new `gold_hash`, and every arm rescored under the same hash from the stored responses. Original and corrected results are both published and each transition is explained.
5. **One rater.** Adjudication by the same person who labeled the gold is a limitation stated in EVAL.md, not an agreement measure. A second pass by that person is intra-rater stability.
6. **The record is per claim and append-only:** case id and diff hash, claim id (hash of the claim text), the claim text, the response files it came from, the blind assessment, verdict, reason, adjudicator, timestamp, rule version. A later decision supersedes by appending, never by editing.
7. **The decision rule does not move after the results.** `MIN_SLICE_SIZE` stays at 20; reaching the clean floor is done by adding verified controls, never by lowering the threshold. A sensitivity analysis at another threshold is reported as exploratory and never gates.

## Adding clean controls (batch 2, pre-registered 2026-10-24)

The clean floor needs 20 declarable controls and the set has 19 after crv-0055. The second batch of controls is selected under rules fixed before any reviewer runs on them; `eval/labels/clean-batch-2.md` lists every candidate and every exclusion with its reason.

1. Eligibility: a merged, non-merge commit from tenacity, click or requests since 2024-06; one production file touched; 4 to 40 changed lines; not used by any existing case as commit or `fix_commit`; the diff reads as a complete change without the test file.
2. Allocation: two commits per repository, taken in `git log` order from the eligible list, so the agent's taste does not pick the easy ones. Six candidates for a batch of five, the sixth is the spare.
3. Comments carried by the merged commit stay: a clean control is the commit as merged.
4. The human labels the candidates blind with `scripts/review_cases.py --pass 1d` before any reviewer runs. `k` enters the set, `u` and `f` are excluded with the note recorded; no candidate is replaced after reviewer results exist.
5. The result is described as "human-verifiable clean commits", not as a sample of production changes.
6. Outcome: pass 1d (2026-10-24) confirmed all six candidates (`eval/labels/review-pass1d.jsonl`); the spare stays in the set, so the release split has 25 clean controls.

## How the human labels

**Pair labels for the judge calibration (2026-10-24):** of the 102 pairs in `eval/labels/pair-labels.jsonl`, the human read and decided 25; a Codex session (GPT-6 Sol), given the same two texts and the same question and nothing else, decided the remaining 77 after the human saw it agree with him on every one of the 25. The records do not mark which 25 were the human's. The calibration therefore measures the Opus judge against a rater from a different model family, anchored by 25 human checks, not against 102 human labels.

The human adjudicator works with two independent model sessions (one Codex, one Claude) that are not connected to this repository or its runs. Each session receives the same material the human sees, scores it on its own, then the two are made to argue their disagreements; the human reads both and decides. The label is the human's; the sessions are a second and third reading, not raters. This is disclosed because one of the sessions shares a model family with the match judge, and because it means the "single rater" is a human with model assistance, not an unaided human.

## Freezing

Gold is written and validated before the baseline runs on the release split. Every scoring field enters `gold_hash`; a later correction goes through `eval/labels/errata.md`, bumps the hash, and requires rescoring every compared run.
