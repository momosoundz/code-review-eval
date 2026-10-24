# EVAL.md

The default reviewer is Haiku 5.5 with the commit title and an instruction to verify the code against it (`hunk_plus_title_verified`). It finds the same share of medium-or-high defects as the plain-diff baseline (72% against 71%), with higher precision (97% against 90%) and the same false-alarm rate on clean diffs (1 of 22). Sonnet 5.5 finds more (83%) but alarms on 5 of 22 clean diffs and costs 12 times more; the eval cannot show it is better, and can almost show it is noisier. Sending the title without the verify instruction lost recall on a named case and was rejected.

## What was measured

A reviewer is one Messages API call with structured outputs: a numbered diff in, a JSON list of findings out, each with file, post-change line, severity, category, description, rationale and confidence. Every reviewer version is a `prompt_id` (hash of prompt, schema, context mode and template) plus a model and an effort. Each version was run K=5 times over every case; the raw responses are committed under `eval_runs/responses/` and never rewritten. `make score` rebuilds each run's `scored.jsonl` and `summary.json` from those responses, the current gold and the cached judge verdicts, without an API key, byte for byte; `compare` and `report` derive the rest from those files.

**Dataset** (`eval/dataset/`, protocol in `PROTOCOL.md`): 49 active release cases from tenacity, click and requests, all Python, 1 or 2 production files each. 16 carry one defect seeded by an agent that never saw the reviewer; 8 are merged bug fixes replayed backwards with telltale text removed; 3 were clean commits in which a reviewer alarm was adjudicated as a real defect ("discovered"); 22 are merged commits with no known defect, the clean controls. A clean diff and its seeded variant share a family, and the statistics resample families, never cases. 9 dev cases from a private repo were used for development and never for the numbers below. Gold hash of the release set as recorded in every run manifest: `8da70ac14b15`.

**Matching** (`eval/harness/match.py`): a finding is eligible for a gold defect when it cites the same file within 3 lines of a gold span (or an `also` location, such as the call site). Eligible pairs go to a binary judge, Opus 5.5, which sees the gold's root cause and failure path and the finding's description and rationale, never its severity, category or model, and answers `match`, `no_match` or `unknown`. One finding matches at most one gold; a second match on the same gold is a duplicate; a finding that matches nothing is a false positive when its severity is medium or high and its category is not `maintainability`; a finding whose only verdicts were `unknown` is listed for review and counts as neither. Category never decides a match. Verdicts are cached and committed; `unknown` is never cached.

**Gate** (`eval/harness/config.py`): the gate metric is `recall_medium_plus`, the share of cases whose medium-or-high gold defects were all matched, averaged over the K runs. Low-severity defects have their own recall and never count as a miss. A candidate is compared with the baseline case by case: the delta's 95% interval comes from a paired bootstrap over families (10,000 resamples, seed fixed). **PASS** when the lower bound is at or above −10 points, both floors hold, and there are at least 20 families with gated defects, 20 clean controls, and 20 medium-or-high findings in the baseline to anchor the precision floor. **FAIL** when the whole interval sits below −10 or a floor is broken. Everything else is **INCONCLUSIVE**. The floors are precision at severity medium or high, and the share of clean cases that alarm in any of the K runs; a floor holds when the candidate is no worse than the far bound of the baseline's Wilson interval (precision at or above its lower bound, alarms at or below its upper bound) and is broken only when the two intervals do not overlap. `recall_high` is reported but does not gate: only 7 cases carry a high-severity defect.

## Results

Five arms on the final set, K=5, 23 cases with medium-or-high gold in 22 families, 22 clean controls. Recall is the mean over K; the "all K" column is the share of cases hit in every run.

| | baseline Haiku, diff only | exp1: + commit title | exp2a: + title, verify it | exp2c: Sonnet, diff only | exp2d: Sonnet + title, verify |
|---|---|---|---|---|---|
| recall, medium-or-high (gate) | 71% | 66% | 72% | 83% | 79% |
| same, all K runs | 52% | 52% | 61% | 83% | 74% |
| recall, high only (7 cases) | 94% | 80% | 83% | 100% | 100% |
| recall, low only (7 cases) | 54% | 57% | 49% | 71% | 94% |
| seeded defects, all defects (16) | 84% | 79% | 83% | 91% | 96% |
| reversed fixes, all defects (8) | 57% | 55% | 55% | 75% | 75% |
| precision at medium or high | 90% (94/104) | 97% (88/91) | 97% (96/99) | 83% (125/151) | 82% (126/154) |
| clean controls alarming, any run (22) | 1 | 1 | 1 | 5 | 5 |
| findings per diff | 0.52 | 0.48 | 0.49 | 0.68 | 0.72 |
| cost of one run (USD) | 0.12 | 0.13 | 0.13 | 1.41 | 1.46 |
| delta on the gate, 95% CI | | −5 [−15, +3] | +1 [−7, +8] | +11 [−4, +28] | +8 [−4, +21] |
| verdict | | INCONCLUSIVE | **PASS** | INCONCLUSIVE | INCONCLUSIVE |

**exp1, title only.** Precision rises to 97% and recall drops 5 points. The loss is one case: crv-0016 goes from 4 of 5 to 0 of 5. The title says "flatten chained `|` and `&`", and the misplaced operator reads as part of the announced refactor. Also lost: crv-0018, crv-0024, crv-0049, crv-0057. Rejected.

**exp2a, title plus a verify instruction.** The instruction to check the implementation against the title, operator by operator, recovers crv-0016 to 1 of 5 and keeps the precision. Recall equals the baseline, the all-K share rises from 52% to 61%, false alarms stay at 1 of 22. Lost: crv-0016 (0.8 → 0.2), crv-0024 (1.0 → 0.8), crv-0057 (0.4 → 0.2). Gained: crv-0026, crv-0042, crv-0046, crv-0052. PASS: not worse than the baseline by more than 10 points, floors inside the interval. Chosen as the default.

**exp2c and exp2d, Sonnet.** Sonnet hits two reversed fixes Haiku misses or barely sees (crv-0043, the falsy wait strategy, 0 of 5 on the baseline; crv-0049, the Protocol check, 1 of 5) and is stable (83% of cases in all five runs). It loses crv-0046 (pickle of a sentinel) 5 of 5 and crv-0057. Its gate interval clears −10, so recall is not what stops it: precision (82.8%) sits below the baseline's lower bound (83.2%) and 5 of 22 clean controls alarm (22.7%), above the baseline's upper bound (21.8%). Neither floor is broken (the intervals overlap), so INCONCLUSIVE, not FAIL. The verify instruction does not transfer: exp2d has lower recall (79%), less stability (74% all-K) and the same five alarming controls. On this set Sonnet finds more and filters worse; neither difference is established by the intervals, and which one ships depends on who pays for the alarms.

**What the clean controls taught.** Two of the alarms Sonnet raised 5 of 5 on "clean" commits were real defects (crv-0052: an attribute removed without an alias; crv-0057: the implicit `__context__` taken as the retry's cause). They were adjudicated under rules frozen before the round (`PROTOCOL.md`, "Adjudicating alarms on clean cases"), moved to gold, and every arm was rescored under the same hash. Sonnet's precision rose from 74% to 83% without touching Sonnet; its verdict moved from FAIL to INCONCLUSIVE. Six other alarms could not be decided from the diff; the missing definitions were added as context-only hunks and the cases recollected: three stopped alarming in every arm, two were then closed as false positives, one (crv-0025) stays unresolved and is declared.

## Judge calibration

The match judge was calibrated on 102 of the 652 cached pairs: every pair the judge rejected (30) and two of its matches per gold defect (72), drawn with a fixed seed, shown without the verdict. Because the sample is stratified by the judge's own verdict, the rates that condition on the verdict are read directly with Wilson intervals: the share of judge matches the human confirms (PPV) and the share of judge rejections the human confirms (NPV). TPR and TNR, which condition on the human label, are recovered by reweighting each stratum to its count in the store and are point estimates only. The gate recall of each arm is then corrected for the judge's error (Rogan-Gladen), an approximation: it treats a case outcome as one judged pair, which holds for all but three cases, and ignores that a case with several eligible findings gives the judge several chances to match. `python -m eval.harness.calibrate --runs ...` writes `eval/labels/calibration.json` and the table below.

**Who labeled.** The human read and decided 25 of the 102 pairs; a Codex session (GPT-6 Sol), shown the same two texts and the same question, decided the other 77 after the human saw it agree on all 25. The records do not mark which were the human's. The numbers below therefore compare the Opus judge with a rater from a different model family, anchored by 25 human checks, not with 102 human labels.

Result (`eval/labels/calibration.json`, 102 pairs, 0 unsure):

| | judge: match | judge: no_match |
|---|---|---|
| rater: same | 71 | 1 |
| rater: different | 1 | 29 |

Of the judge's matches, 99% [93, 100] are confirmed by the rater; of its rejections, 97% [83, 99]. Kappa 0.95 on the sample, 0.85 on the matrix reweighted to the store. The two disagreements are both arguable: on crv-0049 the judge rejected a finding that named the removed `hasattr` fallback but blamed a different mechanism (the rater read it as the same defect); on crv-0057 the judge accepted a finding that objects to re-raising the cause by design, while the gold is about an unrelated `__context__` being taken as the cause (the rater read it as different).

Reweighted to the store, TPR is 100% and TNR 77%; the single judge match the rater rejected weighs 8.6 rejections, so TNR rests on one pair and is a fragile point estimate. Correcting the gate recall with those rates moves every arm down by 5 to 10 points (baseline 71% → 63%, exp2a 72% → 64%, exp2c 83% → 78%) and leaves their order unchanged. Read the corrected column as a sensitivity bound, not as the measurement: with 72 of 72 confirmed matches but one, the judge's matches are what the recall counts, and the recall above stands.

| run | observed gate recall | corrected |
|---|---|---|
| baseline | 71% | 63% |
| exp1 | 66% | 56% |
| exp2a | 72% | 64% |
| exp2c | 83% | 78% |
| exp2d | 79% | 73% |

## Where not to trust this

- **Power.** With 23 gated cases the gate intervals are 15 to 30 points wide (exp2c: [−4, +28]). A difference of +10 cannot be separated from zero with this sample; more gated cases, not a lower threshold, is the fix.
- **Seeded defects are not real defects.** 16 of 27 gold defects were planted by an agent; they are easier than the 8 reversed fixes (84% against 57% recall on the baseline). The reversed-fix slice is reported separately and is the one to watch.
- **The judge is from the same family as the reviewers.** Opus judging Haiku and Sonnet findings may share blind spots. The judge never sees the model or the severity, verdicts are cached and auditable, and the calibration above bounds the error; it does not remove it.
- **The calibration sample is stratified by the judge's verdict.** A labeler who sees more than two pairs for one gold defect can infer that the extra ones were judge rejections; the display hides the verdict, the sampling does not fully.
- **One labeler, with model assistance.** All gold labels and adjudications are one person's, who read each diff with two independent model sessions as additional readers (disclosed in `PROTOCOL.md`). Pass 1b on the same cases measures the labeler's consistency with themselves, not agreement between labelers. The judge calibration goes further: 77 of its 102 pair labels were decided by a GPT model after the human checked 25, so it is a cross-family model agreement anchored by a human sample.
- **Gold is never complete.** Three "clean" commits turned out to carry defects when a reviewer insisted. The discovered lane and the adjudication rules exist because this will happen again. crv-0025 keeps one unresolved claim.
- **The title is untrusted input and is not hardened.** The title templates pass the commit title to the model verbatim. An instruction planted in a title could steer the review. Hardening (delimiting the title, telling the model not to follow it) is a new context mode to be measured, not a patch to the measured ones.
- **Clean controls are human-verifiable commits**, selected mechanically from small production commits, not a sample of real pull requests. Real diffs are larger and the alarm rate on them is unknown.
