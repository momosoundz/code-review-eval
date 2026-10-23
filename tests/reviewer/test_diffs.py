import pytest

from reviewer.diffs import DiffTooLargeError, NumberedDiff, number_diff
from tests.conftest import SAMPLE_DIFF as SAMPLE


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
