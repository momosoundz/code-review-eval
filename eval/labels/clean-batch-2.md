# Clean controls, batch 2 (pre-registered 2026-10-24)

Rules: `eval/dataset/PROTOCOL.md`, "Adding clean controls (batch 2)". Candidate listing produced before any reviewer ran on these commits. Eligibility was computed mechanically over `git log --no-merges --since=2024-06-01` of the local clones (tenacity 32ac68f, click 2247b35, requests 611c6162); two refinements were added to the eligibility rule after the first mechanical listing and before any labeling: commits whose title or sole file says no runtime behavior changes (version bumps, typing, docs, lint, dead code) are excluded. Allocation: the first two eligible per repository in log order; the sixth candidate is the spare.

## Candidates (git log order, two per repository)

| # | repo | commit | file | lines | title |
|---|---|---|---|---|---|
| 1 | tenacity | c650fb4 | tenacity/wait.py | 4 | Fix exponential wait threshold underflow (#656) |
| 2 | tenacity | e5179bd | tenacity/__init__.py | 8 | fix: reraise underlying exception when TryAgain wraps a cause (#640) |
| 3 | click | 1f9cd54 | src/click/_termui_impl.py | 5 | Close the pager temp file before unlinking it |
| 4 | click | bec5928 | src/click/decorators.py | 36 | Fix `package_name` resolution when top-level module differs from distribution name |
| 5 | requests | 6404f345 | src/requests/models.py | 6 | Fix `prepare_body` stream detection for `__getattr__`-based file wrappers (#7433) |
| 6 | requests | a4f9a599 | src/requests/utils.py | 6 | Port bpo-39057 to Requests (#7427) |

## Excluded after passing the size filter

| repo | commit | reason | title |
|---|---|---|---|
| tenacity | d6690dc | title says no runtime behavior change (version, typing, docs, dead code) | refactor: declare BaseAction's REPR_FIELDS and NAME as ClassVar (#680) |
| tenacity | 7c3c45c | title says no runtime behavior change (version, typing, docs, dead code) | fix: annotate wait_base.__radd__ as taking the int seed from sum() (#677) |
| tenacity | a2af454 | title says no runtime behavior change (version, typing, docs, dead code) | Fix static typing of @retry decorated instance methods (fixes #532) (#668) |
| tenacity | ae2d75e | title says no runtime behavior change (version, typing, docs, dead code) | refactor: enable PGH, PYI ruff rules and rename TCH to TC (#619) |
| tenacity | 6be363b | title says no runtime behavior change (version, typing, docs, dead code) | docs: fix typos in docstrings (#590) |
| tenacity | fea6430 | title says no runtime behavior change (version, typing, docs, dead code) | refactor: replace deprecated typing.Pattern with re.Pattern (#589) |
| tenacity | 7efa2fe | title says no runtime behavior change (version, typing, docs, dead code) | fix: use typing.Self on Python 3.11+ instead of typing_extensions (#576) |
| tenacity | 1b2b4ef | title says no runtime behavior change (version, typing, docs, dead code) | fix: resolve tornado mypy errors instead of suppressing them (#568) |
| tenacity | d4e868d | title says no runtime behavior change (version, typing, docs, dead code) | Fix `retry()` annotations with async `sleep=` function (#555) |
| tenacity | 3bf33b4 | title says no runtime behavior change (version, typing, docs, dead code) | chore: drop Python 3.9 support (EOL) (#552) |
| tenacity | 21ae7d0 | title says no runtime behavior change (version, typing, docs, dead code) | docs: fix syntax error in wait_chain docstring example (#548) |
| tenacity | eed7d78 | title says no runtime behavior change (version, typing, docs, dead code) | Support Python 3.14 (#528) |
| click | 94f17e2 | title says no runtime behavior change (version, typing, docs, dead code) | Remove unused bindings and constants from `_winconsole` |
| click | ce57b87 | title says no runtime behavior change (version, typing, docs, dead code) | Add FAQ entry about `edit()` returning immediately |
| click | 1ac08db | lint-only change | Fix ruff E501 line-too-long in PowerShell template |
| click | aef225d | title says no runtime behavior change (version, typing, docs, dead code) | Add type annotations for instance attributes in `formatting` |
| click | ea76281 | title says no runtime behavior change (version, typing, docs, dead code) | Add type annotations for instance attributes in `shell_completion` |
| click | 0baa8db | only comments or docstrings change | Document ctx.params bypass with test and doc |
| click | fc41aa1 | title says no runtime behavior change (version, typing, docs, dead code) | Apply class-body annotations to `KeepOpenFile` for consistency |
| click | 279ce7b | title says no runtime behavior change (version, typing, docs, dead code) | Add type annotations for instance attributes in `utils` |
| click | 27de74a | title says no runtime behavior change (version, typing, docs, dead code) | Shorten the docstring annotations for confirm and prompt |
| click | ce7b47d | only comments or docstrings change | Update comments on UNSET handling during parse_args |
| click | b9abeaa | only comments or docstrings change | Hint at the concepts carried by default |
| click | 96e4c75 | only comments or docstrings change | Add explanation for the casting |
| click | 7f4fa21 | only comments or docstrings change | Lint |
| click | b39590f | only comments or docstrings change | Make the source selection logic clearer |
| click | 3155dca | title says no runtime behavior change (version, typing, docs, dead code) | fix(typing): Using correct typing for `param_hint` |
| requests | 6e83187b | title says no runtime behavior change (version, typing, docs, dead code) | v2.34.2 |
| requests | b7b549b5 | title says no runtime behavior change (version, typing, docs, dead code) | v2.34.1 |
| requests | 5691f596 | typing or version module, no runtime behavior | Update JsonType containers to read-based collections (#7436) |
| requests | f7822f7c | title says no runtime behavior change (version, typing, docs, dead code) | v2.34.0.dev1 |
| requests | 111d2b77 | title says no runtime behavior change (version, typing, docs, dead code) | v2.33.1 |
| requests | 5e7cb71c | title says no runtime behavior change (version, typing, docs, dead code) | Bump version to dev for test publish |
| requests | b25c87d7 | title says no runtime behavior change (version, typing, docs, dead code) | v2.32.5 |
| requests | 821770e8 | title says no runtime behavior change (version, typing, docs, dead code) | Bump version and add release notes for v2.32.4 |

Eligible but after the allocation cut: 89 commits (listed in `git log` order in the clones).
