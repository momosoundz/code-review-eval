# Defect taxonomy

Twelve categories for the defect mechanism, one escape hatch, and one non-gated label. The list lives in `reviewer/config.py`; the reviewer schema and the dataset validator both read it. A finding matches a gold defect by location and root cause, never by category, so a defect of an unforeseen type is still scored.

| category | what it covers | example |
|---|---|---|
| `boundary` | off-by-one, inclusive/exclusive mix-up, thresholds, empty or single-element edge | `range(len(xs) - 1)` skipping the last item |
| `null_or_missing_value` | None, empty, missing key or default not handled | `max(seq)` without `default` on a possibly empty sequence |
| `wrong_operator` | wrong comparison, sign, arithmetic or boolean operator | `delta < max_drop` instead of `delta < -max_drop` |
| `wrong_condition` | inverted, too broad or too narrow predicate or branch | a retry that fires for every weak question |
| `wrong_variable_or_argument` | right operation on the wrong value or argument | logging `chunks[0].score` inside a loop over `chunks` |
| `wrong_literal_or_default` | wrong constant, unit, flag or default value | a URL with the wrong path segment |
| `error_handling` | exception swallowed, wrong exception, failure not propagated | `except Exception: return []` with no log |
| `resource_lifecycle` | file, connection, lock or task not released, closed early, or used after close | a session opened and not closed when an error is raised |
| `concurrency` | race, missing await, shared state without protection | checking then acting on a value another task can change |
| `input_validation` | untrusted data crossing a trust boundary unchecked: query, command, path, template, tenant scope | string-formatting user text into SQL; a lookup that drops the tenant filter |
| `logic_other` | algorithm, state machine, ordering or missing behavior that fits no label above | two steps executed in the wrong order |
| `other` | the taxonomy does not cover it yet; the root cause says what it is | consolidated into a new category once three cases share it |
| `maintainability` | structure or readability, severity `low`, never a hit nor a false positive | a 90-line function |

Severity is assigned to the defect, not to the category: `high` for data loss, security boundary bypass, crash on a common path or silent wrong results; `medium` for incorrect behavior under a plausible but less common input; `low` for a limited-impact defect.

Why this shape: the closest published taxonomy is ByteDance's BitsAI-CR defect dimension (null, boundary, conditions, arguments, business logic, resource leaks, exceptions, concurrency). ManySStuBs4J's fix templates (operator, operand, literal, condition, argument) cover the single-edit defects we seed. Security is an impact, not a mechanism: a missing tenant check is `input_validation` with impact noted in `failure_path`, the way CR-Bench keeps root cause and impact on separate axes. The taxonomy is versioned through `gold_hash`; changing a label is a new dataset version.
