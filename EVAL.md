# EVAL.md

The default reviewer is Haiku 5.5 given the diff, the commit title, and an instruction to verify the code against the title. It finds the same share of medium-or-high defects as the plain-diff baseline (69% against 68%), with higher precision (97% against 90%) and the same false-alarm rate on clean diffs (1 of 20). Sonnet 5.5 finds more (79%) but its precision falls below the floor and it alarms on 4 of 20 clean diffs at 12 times the cost; the eval cannot show it is better. A second reviewer from another family (GPT-6 Sol through the Codex CLI, same prompt) combined with the default by `union` is the only candidate whose gain is demonstrated: +14 points of recall, 95% CI [+5, +25], with precision and false alarms inside the floors. Requiring both reviewers to agree gives 100% precision and zero alarms at the cost of 7 recall points. Sending the title without the verify instruction lost recall on a named case and was rejected.

## What was measured

A reviewer is one model call with a JSON schema: a numbered diff in, findings out (file, post-change line, severity, category, description, rationale, confidence), through the Anthropic API or the Codex CLI. A reviewer version is a `prompt_id` (hash of prompt, schema, context mode and template) plus a model and an effort. Each version ran K=5 times per case; raw responses are committed under `eval_runs/responses/` and never rewritten. `make score` rebuilds every run's scores from those responses, the current gold and the cached judge verdicts, without an API key, byte for byte.

**Dataset** (`eval/dataset/`, protocol in `PROTOCOL.md`): 49 release cases from tenacity, click and requests, 1 or 2 production files each. 16 carry one defect seeded by an agent that never saw the reviewer; 8 are merged bug fixes replayed backwards with telltale text removed; 5 were clean commits in which a reviewer alarm was adjudicated as a real defect; 20 are merged commits with no known defect, the clean controls. A clean diff and its seeded variant share a family, and the statistics resample families. 9 dev cases from a private repo were used only for development. Release gold hash: `217f2ffe1a45`.

**Matching** (`eval/harness/match.py`): a finding is eligible for a gold defect when it cites the same file within 3 lines of a gold span. Eligible pairs go to a binary judge, Opus 5.5, which sees the gold's root cause and failure path and the finding's description and rationale, never its severity, category or model. One finding matches at most one gold; an unmatched finding is a false positive at severity medium or high. Category never decides a match. Verdicts are cached and committed.

**Gate** (`eval/harness/config.py`): the metric is `recall_medium_plus`, the share of cases whose medium-or-high gold defects were all matched, averaged over K. Low-severity defects have their own recall and never count as a miss. The delta against the baseline gets a 95% interval from a paired bootstrap over families (10,000 resamples, fixed seed). **PASS**: lower bound at or above −10 points, both floors hold, at least 20 families with gated defects, 20 clean controls and 20 baseline findings. **FAIL**: the whole interval below −10, or a floor broken. Otherwise **INCONCLUSIVE**. The floors are precision at medium or high and the share of clean cases alarming in any of the K runs; a floor holds when the candidate is no worse than the far bound of the baseline's Wilson interval and is broken only when the intervals do not overlap. `recall_high` is reported but does not gate: 7 cases carry a high-severity defect.

## Results

Eight arms, K=5, 24 cases with medium-or-high gold in 23 families, 20 clean controls. Every arm is scored under the final gold. The runs scored under each earlier gold (before the second clean batch, before and after the first adjudication, before the second) are in the git history, one commit per transition, with the verdicts they produced.

| | baseline Haiku, diff only | exp1: + commit title | exp2a: + title, verify it | exp2c: Sonnet, diff only | exp2d: Sonnet + title, verify |
|---|---|---|---|---|---|
| recall, medium-or-high (gate) | 68% | 63% | 69% | 79% | 76% |
| same, all K runs | 50% | 50% | 58% | 79% | 71% |
| recall, high only (7) | 94% | 80% | 83% | 100% | 100% |
| recall, low only (9) | 48% | 50% | 42% | 62% | 82% |
| seeded (16) / reversed fixes (8) | 84% / 57% | 79% / 55% | 83% / 55% | 91% / 75% | 96% / 75% |
| precision at medium or high | 90% (94/104) | 97% (88/91) | 97% (96/99) | 83% (125/151) | 82% (126/154) |
| clean controls alarming, any run (20) | 1 | 1 | 1 | 4 | 4 |
| findings per diff | 0.52 | 0.48 | 0.49 | 0.68 | 0.72 |
| cost of one run (USD) | 0.12 | 0.13 | 0.13 | 1.41 | 1.46 |
| delta on the gate, 95% CI | | −5 [−14, +3] | +1 [−7, +8] | +11 [−4, +27] | +8 [−4, +20] |
| verdict | | INCONCLUSIVE | **PASS** | INCONCLUSIVE | INCONCLUSIVE |

**exp1, title only.** Precision rises to 97%, recall drops 5 points. The loss is one case: crv-0016 goes from 4 of 5 to 0 of 5 because the title "flatten chained `|` and `&`" makes the misplaced operator read as part of the refactor. Also lost: crv-0018, crv-0024, crv-0049, crv-0057. Rejected.

**exp2a, title plus a verify instruction.** Checking the implementation against the title, operator by operator, recovers crv-0016 to 1 of 5 and keeps the precision. Recall equals the baseline, the all-K share rises from 50% to 58%, false alarms stay at 1 of 20. Lost: crv-0016 (0.8 → 0.2), crv-0024, crv-0057. Gained: crv-0026, crv-0042, crv-0046, crv-0052. PASS; chosen as the default.

**exp2c and exp2d, Sonnet.** Sonnet hits two reversed fixes Haiku misses or barely sees (crv-0043, 0 of 5 on the baseline; crv-0049, 1 of 5) and is stable (79% in all five runs). It loses crv-0046 (pickle of a sentinel) 5 of 5 and crv-0057. Its gate interval clears −10, so recall is not what stops it: precision (82.8%) sits below the baseline's lower bound (83.2%). Four of 20 controls alarm, inside the baseline's upper bound (23.6%). Neither floor is broken, so INCONCLUSIVE. The verify instruction does not transfer: exp2d has lower recall (76%), less stability and the same four alarms.

**exp3, a second reviewer from another family.** The same prompt, schema and context mode sent through `codex exec` (GPT-6 Sol, read-only sandbox, on a subscription), and two deterministic combinations with exp2a (`eval/harness/merge.py`, no model call).

| | exp3: Codex alone | exp3: union (2a + Codex) | exp3: agreement (2a + Codex) |
|---|---|---|---|
| recall, medium-or-high (gate) | 81% | 82% | 61% |
| same, all K runs | 75% | 75% | 50% |
| recall, high only (7) | 100% | 100% | 83% |
| seeded (16) / reversed fixes (8) | 94% / 65% | 91% / 78% | 83% / 32% |
| precision at medium or high | 90% (113/125) | 92% (119/129) | 100% (81/81) |
| clean controls alarming, any run (20) | 1 | 2 | 0 |
| findings per diff | 0.56 | 0.64 | 0.41 |
| cost of one run (USD, Codex on a subscription) | 0 | 0.13 | 0.13 |
| delta on the gate, 95% CI | +12 [−1, +26] | +14 [+5, +25] | −8 [−18, +2] |
| verdict | **PASS** | **PASS** | INCONCLUSIVE |

Codex alone passes with a lower bound just under zero. `union` (either reviewer, once) is the first arm that is better, not only not worse: the delta's whole interval sits above zero, with precision 92% and 2 of 20 alarming controls, both inside the baseline's intervals. The two reviewers miss different things: Codex gets crv-0043 and crv-0049 that Haiku does not, Haiku gets crv-0046 that Codex loses 5 of 5, and the union keeps all three. `agreement` (both must flag the same line) is the other extreme: 100% precision, no alarms, and 7 recall points lost (crv-0016, crv-0024, crv-0046, crv-0050).

**What the clean controls taught.** Four alarms raised 5 of 5 on "clean" commits were real defects: two by Sonnet (crv-0052, crv-0057) and two by Codex (crv-0011, crv-0051; the labeler's own blind notes had flagged both as possible issues). Each was adjudicated under rules frozen before the round (`PROTOCOL.md`), moved to gold, and every arm was rescored under the same hash. The repairs favour the model that insisted: Sonnet's precision rose from 74% to 83%, Codex's from 82% to 90%, without touching either model; this is disclosed because it is the main way the gold can drift toward a strong reviewer. Six other alarms could not be decided from the diff; the missing definitions were added as context-only hunks and the cases recollected: three stopped alarming, two were closed as false positives, one (crv-0025) stays unresolved.

## Judge calibration

102 of the 652 cached pairs were labeled without the verdict: every pair the judge rejected (30) and two of its matches per gold defect (72). The human decided 25 and a Codex session (GPT-6 Sol), given the same two texts, decided the other 77 after agreeing on all 25; the records do not mark which were the human's. This is the Opus judge against a rater from another model family, anchored by 25 human checks.

| | judge: match | judge: no_match |
|---|---|---|
| rater: same | 71 | 1 |
| rater: different | 1 | 29 |

Of the judge's matches, 99% [93, 100] are confirmed; of its rejections, 97% [83, 99]. Kappa 0.95 on the sample, 0.85 reweighted to the store. Both disagreements are arguable: crv-0049 (same line, a different mechanism named) and crv-0057 (the finding objects to the design, the gold is about an unrelated context). Reweighted, TPR is 100% and TNR 77%, but TNR rests on one pair that weighs 8.6 rejections. Correcting the gate recall with those rates (Rogan-Gladen, one judged pair per case, an approximation) moves every arm down 4 to 8 points without changing their order; read it as a sensitivity bound. `python -m eval.harness.calibrate` writes `eval/labels/calibration.json`.

## Where not to trust this

- **Power.** With 24 gated cases the gate intervals are 15 to 30 points wide. A +10 cannot be separated from zero; more gated cases, not a lower threshold, is the fix.
- **Seeded defects are easier than real ones**: 84% against 57% recall on the baseline. Watch the reversed-fix row.
- **The judge is from the same family as the reviewers.** It never sees the model or severity, verdicts are auditable, and the calibration bounds the error; it does not remove it.
- **The calibration sample is stratified by the judge's verdict**, and 77 of its 102 labels are a GPT model's. A rater who sees a third pair for one gold can infer it was a rejection.
- **One labeler, with model assistance**, for every gold label and adjudication (two independent model sessions as readers, disclosed in `PROTOCOL.md`). Pass 1b measures self-consistency, not inter-rater agreement.
- **Gold is never complete, and repairs favour the insistent reviewer.** Five "clean" commits carried defects, each found by a reviewer alarming 5 of 5; every repair raised that reviewer's precision. The rules make it auditable, not neutral. crv-0025 keeps one unresolved claim.
- **The commit title is untrusted input and is not hardened**: an instruction planted in it could steer the review. Hardening is a new context mode to be measured.
- **The Codex arm runs on a subscription, not a priced API.** Its cost is recorded as zero and its latency (p50 13 s against 4 s) is the CLI's; a production deployment would pay per token and should be re-measured. The CLI can run read-only commands inside its sandbox; every tool item it reported is kept in the raw envelope, and none appeared in this run.
- **Clean controls are human-verifiable small commits**, not a sample of real pull requests; the alarm rate on real diffs is unknown.
