# Defect taxonomy

Ten categories a reviewer can plausibly identify from a diff alone. The reviewer may also emit `maintainability`, which never counts as a hit or a false positive.

| category | what it covers | example |
|---|---|---|
| `boundary` | off-by-one, inclusive/exclusive mix-up, empty or single-element edge | `range(len(xs) - 1)` skipping the last item |
| `null_or_missing_value` | None, empty, missing key or default not handled | `max(seq)` without `default` on a possibly empty sequence |
| `wrong_operator_or_operand` | wrong comparison, sign, arithmetic or boolean operator | `delta < max_drop` instead of `delta < -max_drop` |
| `wrong_condition` | inverted, too broad or too narrow guard | a retry that fires for every weak question |
| `wrong_variable_or_argument` | right operation on the wrong value | logging `chunks[0].score` inside a loop over `chunks` |
| `error_handling` | exception swallowed, wrong exception, failure not propagated | `except Exception: return []` with no log |
| `resource_leak` | file, connection, lock or task not released on every path | a session opened and not closed when an error is raised |
| `concurrency` | race, missing await, shared state without protection | checking then acting on a value another task can change |
| `unsafe_input` | untrusted data reaching a query, command, path or template | string-formatting user text into SQL |
| `wrong_literal_or_default` | wrong constant, unit, flag or default value | a threshold set to the wrong scale |

Severity is assigned to the defect, not to the category: `high` for data loss, security boundary bypass, crash on a common path or silent wrong results; `medium` for incorrect behavior under a plausible but less common input; `low` for a limited-impact defect.
