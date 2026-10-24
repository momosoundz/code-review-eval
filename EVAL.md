# EVAL.md

The default reviewer is Haiku 5.5 given the diff, the commit title, and an instruction to verify the code against the title. It finds the same share of medium-or-high defects as the plain-diff baseline (72% against 71%), with higher precision (97% against 90%) and the same false-alarm rate on clean diffs (1 of 22). Sonnet 5.5 finds more (83%) but alarms on 5 of 22 clean diffs and costs 12 times more; the eval cannot show it is better and almost shows it is noisier. Sending the title without the verify instruction lost recall on a named case and was rejected.

## What was measured

A reviewer is one Messages API call with structured outputs: a numbered diff in, JSON findings out (file, post-change line, severity, category, description, rationale, confidence). A reviewer version is a `prompt_id` (hash of prompt, schema, context mode and template) plus a model and an effort. Each version ran K=5 times per case; raw responses are committed under `eval_runs/responses/` and never rewritten. `make score` rebuilds every run's `scored.jsonl` and `summary.json` from those responses, the current gold and the cached judge verdicts, without an API key, byte for byte.

**Dataset** (`eval/dataset/`, protocol in `PROTOCOL.md`): 49 release cases from tenacity, click and requests, 1 or 2 production files each. 16 carry one defect seeded by an agent that never saw the reviewer; 8 are merged bug fixes replayed backwards with telltale text removed; 3 were clean commits in which a reviewer alarm was adjudicated as a real defect; 22 are merged commits with no known defect, the clean controls. A clean diff and its seeded variant share a family, and the statistics resample families. 9 dev cases from a private repo were used only for development. Release gold hash: `8da70ac14b15`.

**Matching** (`eval/harness/match.py`): a finding is eligible for a gold defect when it cites the same file within 3 lines of a gold span or an `also` location. Eligible pairs go to a binary judge, Opus 5.5, which sees the gold's root cause and failure path and the finding's description and rationale, never its severity, category or model. One finding matches at most one gold; a second match on the same gold is a duplicate; an unmatched finding is a false positive when its severity is medium or high and its category is not `maintainability`. Category never decides a match. Verdicts are cached and committed.

**Gate** (`eval/harness/config.py`): the metric is `recall_medium_plus`, the share of cases whose medium-or-high gold defects were all matched, averaged over K. Low-severity defects have their own recall and never count as a miss. The delta against the baseline gets a 95% interval from a paired bootstrap over families (10,000 resamples, fixed seed). **PASS**: lower bound at or above −10 points, both floors hold, at least 20 families with gated defects, 20 clean controls and 20 baseline findings. **FAIL**: the whole interval below −10, or a floor broken. Otherwise **INCONCLUSIVE**. The floors are precision at medium or high and the share of clean cases alarming in any of the K runs; a floor holds when the candidate is no worse than the far bound of the baseline's Wilson interval and is broken only when the intervals do not overlap. `recall_high` is reported but does not gate: 7 cases carry a high-severity defect.

## Results

Five arms, K=5, 23 cases with medium-or-high gold in 22 families, 22 clean controls.

| | baseline Haiku, diff only | exp1: + commit title | exp2a: + title, verify it | exp2c: Sonnet, diff only | exp2d: Sonnet + title, verify |
|---|---|---|---|---|---|
| recall, medium-or-high (gate) | 71% | 66% | 72% | 83% | 79% |
| same, all K runs | 52% | 52% | 61% | 83% | 74% |
| recall, high only (7) | 94% | 80% | 83% | 100% | 100% |
| recall, low only (7) | 54% | 57% | 49% | 71% | 94% |
| seeded defects (16) | 84% | 79% | 83% | 91% | 96% |
| reversed fixes (8) | 57% | 55% | 55% | 75% | 75% |
| precision at medium or high | 90% (94/104) | 97% (88/91) | 97% (96/99) | 83% (125/151) | 82% (126/154) |
| clean controls alarming, any run (22) | 1 | 1 | 1 | 5 | 5 |
| findings per diff | 0.52 | 0.48 | 0.49 | 0.68 | 0.72 |
| cost of one run (USD) | 0.12 | 0.13 | 0.13 | 1.41 | 1.46 |
| delta on the gate, 95% CI | | −5 [−15, +3] | +1 [−7, +8] | +11 [−4, +28] | +8 [−4, +21] |
| verdict | | INCONCLUSIVE | **PASS** | INCONCLUSIVE | INCONCLUSIVE |

**exp1, title only.** Precision rises to 97%, recall drops 5 points. The loss is one case: crv-0016 goes from 4 of 5 to 0 of 5 because the title "flatten chained `|` and `&`" makes the misplaced operator read as part of the refactor. Also lost: crv-0018, crv-0024, crv-0049, crv-0057. Rejected.

**exp2a, title plus a verify instruction.** Checking the implementation against the title, operator by operator, recovers crv-0016 to 1 of 5 and keeps the precision. Recall equals the baseline, the all-K share rises from 52% to 61%, false alarms stay at 1 of 22. Lost: crv-0016 (0.8 → 0.2), crv-0024, crv-0057. Gained: crv-0026, crv-0042, crv-0046, crv-0052. PASS; chosen as the default.

**exp2c and exp2d, Sonnet.** Sonnet hits two reversed fixes Haiku misses or barely sees (crv-0043, 0 of 5 on the baseline; crv-0049, 1 of 5) and is stable (83% in all five runs). It loses crv-0046 (pickle of a sentinel) 5 of 5 and crv-0057. Its gate interval clears −10, so recall is not what stops it: precision (82.8%) sits below the baseline's lower bound (83.2%) and 5 of 22 clean controls alarm (22.7%) against the baseline's upper bound (21.8%). Neither floor is broken, so INCONCLUSIVE. The verify instruction does not transfer: exp2d has lower recall (79%), less stability and the same five alarms. On this set Sonnet finds more and filters worse; neither difference is established by the intervals.

**What the clean controls taught.** Two alarms Sonnet raised 5 of 5 on "clean" commits were real defects (crv-0052, an attribute removed without an alias; crv-0057, the implicit `__context__` taken as the retry's cause). They were adjudicated under rules frozen before the round (`PROTOCOL.md`), moved to gold, and every arm was rescored under the same hash: Sonnet's precision rose from 74% to 83% without touching Sonnet, and its verdict from FAIL to INCONCLUSIVE. Six other alarms could not be decided from the diff; the missing definitions were added as context-only hunks and the cases recollected: three stopped alarming in every arm, two were closed as false positives, one (crv-0025) stays unresolved.

## Judge calibration

102 of the 652 cached pairs were labeled without the verdict: every pair the judge rejected (30) and two of its matches per gold defect (72). The human decided 25 and a Codex session (GPT-6 Sol), given the same two texts, decided the other 77 after agreeing on all 25; the records do not mark which were the human's. This is the Opus judge against a rater from another model family, anchored by 25 human checks.

| | judge: match | judge: no_match |
|---|---|---|
| rater: same | 71 | 1 |
| rater: different | 1 | 29 |

Of the judge's matches, 99% [93, 100] are confirmed; of its rejections, 97% [83, 99]. Kappa 0.95 on the sample, 0.85 reweighted to the store. Both disagreements are arguable: crv-0049 (same line, a different mechanism named) and crv-0057 (the finding objects to the design, the gold is about an unrelated context). Reweighted, TPR is 100% and TNR 77%, but TNR rests on one pair that weighs 8.6 rejections. Correcting the gate recall with those rates (Rogan-Gladen, one judged pair per case, an approximation) moves every arm down 5 to 10 points (baseline 63%, exp2a 64%, exp2c 78%) without changing their order; read it as a sensitivity bound. `python -m eval.harness.calibrate` writes `eval/labels/calibration.json`.

## Where not to trust this

- **Power.** With 23 gated cases the gate intervals are 15 to 30 points wide. A +10 cannot be separated from zero; more gated cases, not a lower threshold, is the fix.
- **Seeded defects are easier than real ones**: 84% against 57% recall on the baseline. Watch the reversed-fix row.
- **The judge is from the same family as the reviewers.** It never sees the model or severity, verdicts are auditable, and the calibration bounds the error; it does not remove it.
- **The calibration sample is stratified by the judge's verdict**, and 77 of its 102 labels are a GPT model's. A rater who sees a third pair for one gold can infer it was a rejection.
- **One labeler, with model assistance**, for every gold label and adjudication (two independent model sessions as readers, disclosed in `PROTOCOL.md`). Pass 1b measures self-consistency, not inter-rater agreement.
- **Gold is never complete.** Three "clean" commits carried defects. crv-0025 keeps one unresolved claim.
- **The commit title is untrusted input and is not hardened**: an instruction planted in it could steer the review. Hardening is a new context mode to be measured.
- **Clean controls are human-verifiable small commits**, not a sample of real pull requests; the alarm rate on real diffs is unknown.
