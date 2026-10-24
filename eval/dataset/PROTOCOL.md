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

## Freezing

Gold is written and validated before the baseline runs on the release split. Every scoring field enters `gold_hash`; a later correction goes through `eval/labels/errata.md`, bumps the hash, and requires rescoring every compared run.
