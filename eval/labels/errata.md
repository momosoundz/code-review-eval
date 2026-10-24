# Gold errata

Label changes made after a human review pass, with the reason. The review files are never edited.

| date | case | change | reason |
|---|---|---|---|
| 2026-10-23 | crv-0004 | severity medium -> low; failure_path rewritten to state the observable outcome (abstention message instead of a retry) | pass-1 review: the diff shows a skipped retry, not a wrong answer; impact is limited |
| 2026-10-23 | crv-0002 | added `also` location src/agents.py:94 (the call site) | dev K=3 run: the reviewer located the defect at the call site once; both places are legitimate anchors |
| 2026-10-23 | crv-0020 | re-seeded: __aexit__ forwards None instead of the exception; category error_handling, severity high, span 226 | pass-1: previous seed was an annotation mismatch, not a behavioral defect, and not resource_lifecycle |
| 2026-10-23 | crv-0042 | the raise OSError -> warnings.warn edit is now a changed line (304) instead of a context line | pass-1: the gold defect was not visible as a change |
| 2026-10-23 | crv-0046 | diff widened to 14 context lines so `UNSET = object()` is visible; failure_path narrowed to the pickle round trip | pass-1: not inferable without the member value; Enum already returns self from copy and deepcopy |
| 2026-10-23 | crv-0048 | dropped the versionchanged docstring hunk; added g2 (lost validation in _interpret_color, low) | pass-1: the docstring stated the defect verbatim; second unlabeled defect in the diff |
| 2026-10-23 | crv-0045 | dropped the docstring hunk mentioning cycle detection | pass-1: giveaway in a deleted line |
| 2026-10-23 | crv-0043 | removed the added comments and type-ignore markers naming falsy waits; failure_path gives a concrete falsy strategy and the lost-backoff impact; spans shifted to 421-424 and 155-160 | pass-1: telltale text; severity needed justification |
| 2026-10-23 | crv-0049 | added context-only hunks with the runtime_checkable SupportsRead Protocol and its import | pass-1: isinstance vs hasattr difference not inferable without the definition |
| 2026-10-23 | crv-0050 | added a context-only hunk with get_encoding_from_headers; failure_path names the AttributeError on .strip | pass-1: impact not derivable without the consumer |
| 2026-10-23 | crv-0012 | severity -> high | pass-1 + new taxonomy rule: silent wrong result on the main path of a public API |
| 2026-10-23 | crv-0016 | severity -> high | pass-1 + new taxonomy rule: silent wrong retry decision; failure_path rewritten around (A & B) | C |
| 2026-10-23 | crv-0022 | severity -> medium, category -> wrong_condition | pass-1 + new taxonomy rule: wrong decision that surfaces as a propagated exception; category wrong_condition |
| 2026-10-23 | crv-0030 | severity -> medium | pass-1 + new taxonomy rule: main path broken but the failure is visible to the caller |
| 2026-10-23 | crv-0044 | failure_path cites tenacity #696 as evidence that patching the module global is established usage | pass-1: severity depended on that evidence |
| 2026-10-23 | crv-0003 | deprecated | pass-1: same resulting code as crv-0009, which carries a medium gold |
| 2026-10-23 | crv-0020 | failure_path tightened: exception propagates unrecorded, no retry | pass 1b |
| 2026-10-23 | crv-0046 | failure_path: unpickling raises ValueError (no 'new object' outcome) | pass 1b |
| 2026-10-23 | crv-0048 | g2 failure_path: fg=True is accepted (index 1), fg=300 is the invalid escape | pass 1b |
| 2026-10-23 | crv-0049 | failure_path states the Python 3.12+ condition | pass 1b |
| 2026-10-23 | crv-0013 | added discovered gold: shared statistics dict across concurrent calls (concurrency, medium); source clean -> discovered | baseline flagged it 5/5; verified against upstream source |
| 2026-10-23 | crv-0014 | added discovered gold: shared statistics dict across concurrent calls (concurrency, medium) | baseline flagged it 5/5; verified against upstream source |
| 2026-10-23 | crv-0050 | also location at the consumer line utils.py:544 (context-only hunk) | baseline anchored the correct finding on the consumer 3/5 times |
| 2026-10-24 | crv-0055 | deprecated | pass 1c: labeler could not confirm clean; the change relies on urllib3 >= 2.7 behavior while the commit keeps urllib3>=1.26,<3, so the diff is not a clean control (release clean cases 20 -> 19) |
| 2026-10-24 | crv-0052 | source clean -> discovered; g1 medium (self.initial removed without alias, line 275), g2 low (default 1 as sentinel, lines 262/267; two adjudicated claims with one root cause merged into one gold) | adjudication under rules v1, eval/labels/adjudications.jsonl |
| 2026-10-24 | crv-0057 | source clean -> discovered; g1 medium (__context__ taken as the retry cause, line 193), g2 low (`from None` clears the cause chain, line 195) | adjudication under rules v1; all five arms had alarmed on the case |
