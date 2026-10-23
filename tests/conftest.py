"""Shared test helpers: a sample diff and builders for dataset cases."""

import json
from pathlib import Path

SAMPLE_DIFF = """\
diff --git a/app/orders.py b/app/orders.py
index 1111111..2222222 100644
--- a/app/orders.py
+++ b/app/orders.py
@@ -40,5 +40,6 @@ def get_order(order_id: int, tenant_id: int) -> Order:
     session = get_session()
-    order = session.query(Order).filter_by(id=order_id, tenant_id=tenant_id).one()
+    order = session.query(Order).filter_by(id=order_id).one()
+    log.debug("order %s", order_id)
     if order is None:
         raise NotFound(order_id)
     return order
diff --git a/app/util.py b/app/util.py
new file mode 100644
--- /dev/null
+++ b/app/util.py
@@ -0,0 +1,2 @@
+def clamp(x: int, lo: int, hi: int) -> int:
+    return max(lo, min(x, hi))
"""

CASE_DIFF = SAMPLE_DIFF.split("diff --git a/app/util.py", maxsplit=1)[0]


def write_case(root: Path, case_id: str, expected: dict, meta: dict, diff: str = CASE_DIFF) -> Path:
    """Create a case directory with diff, expected and meta files."""
    case_dir = root / case_id
    case_dir.mkdir(parents=True)
    (case_dir / "diff.patch").write_text(diff)
    (case_dir / "expected.json").write_text(json.dumps(expected))
    (case_dir / "meta.json").write_text(json.dumps(meta))
    return case_dir


def gold(**overrides: object) -> dict:
    """A valid gold finding on the sample diff, with overrides."""
    base = {
        "gold_id": "crv-0001-g1",
        "file": "app/orders.py",
        "spans": [[41, 41]],
        "category": "null_or_missing_value",
        "severity": "high",
        "root_cause": "the lookup no longer filters by tenant_id",
        "failure_path": "tenant A asks for an order owned by tenant B and gets it",
        "needs_context_beyond_diff": False,
    }
    base.update(overrides)
    return base


def meta(**overrides: object) -> dict:
    """A valid meta record, with overrides."""
    base = {
        "family_id": "fam-001",
        "split": "dev",
        "source": "seeded",
        "provenance": {"repo": "example", "base_sha": "abc"},
        "status": "active",
    }
    base.update(overrides)
    return base
