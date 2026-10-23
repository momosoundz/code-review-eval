# Gold errata

Label changes made after a human review pass, with the reason. The review files are never edited.

| date | case | change | reason |
|---|---|---|---|
| 2026-10-23 | crv-0004 | severity medium -> low; failure_path rewritten to state the observable outcome (abstention message instead of a retry) | pass-1 review: the diff shows a skipped retry, not a wrong answer; impact is limited |
| 2026-10-23 | crv-0002 | added `also` location src/agents.py:94 (the call site) | dev K=3 run: the reviewer located the defect at the call site once; both places are legitimate anchors |
