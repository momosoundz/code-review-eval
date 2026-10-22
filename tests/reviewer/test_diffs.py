import pytest

from reviewer.diffs import DiffTooLargeError, NumberedDiff, number_diff

SAMPLE = """\
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


def test_numbers_post_change_lines() -> None:
    numbered = number_diff(SAMPLE)
    text = numbered.text
    assert "app/orders.py" in text
    assert "   41 +    order = session.query(Order).filter_by(id=order_id).one()" in text
    assert "   42 +    log.debug" in text
    assert "   43      if order is None:" in text


def test_removed_lines_have_no_number() -> None:
    numbered = number_diff(SAMPLE)
    removed = "      -    order = session.query(Order).filter_by(id=order_id, tenant_id"
    assert removed in numbered.text


def test_valid_lines_per_file() -> None:
    numbered = number_diff(SAMPLE)
    assert numbered.valid_lines["app/orders.py"] == {40, 41, 42, 43, 44, 45}
    assert numbered.valid_lines["app/util.py"] == {1, 2}


def test_new_file_path_is_post_change_path() -> None:
    numbered = number_diff(SAMPLE)
    assert set(numbered.valid_lines) == {"app/orders.py", "app/util.py"}


def test_rejects_oversized_diff() -> None:
    big = SAMPLE + "+" + ("x" * 60_000) + "\n"
    with pytest.raises(DiffTooLargeError, match="exceeds"):
        number_diff(big, max_chars=48_000)


def test_empty_diff_is_an_error() -> None:
    with pytest.raises(ValueError, match="no hunks"):
        number_diff("")


def test_numbered_diff_is_frozen() -> None:
    numbered = number_diff(SAMPLE)
    assert isinstance(numbered, NumberedDiff)
    with pytest.raises(AttributeError):
        numbered.text = "x"  # ty: ignore[invalid-assignment]
