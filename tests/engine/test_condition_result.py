"""
engine/condition/result.py — 삼치 논리.

**``UNKNOWN`` 은 세 번째 값이지 거짓의 일종이 아니다.** 이 파일은 그것이
어떤 경로로도 참/거짓으로 접히지 않는지 확인한다.
"""

import pytest

from engine.condition.result import ConditionResult as R


# ----------------------------------------------------------------------
# A. 세 상태가 서로 구분된다
# ----------------------------------------------------------------------


def test_three_states_are_distinct():
    assert len(set(R)) == 3
    assert R.TRUE is not R.FALSE
    assert R.TRUE is not R.UNKNOWN
    assert R.FALSE is not R.UNKNOWN
    assert R.TRUE != R.UNKNOWN
    assert R.FALSE != R.UNKNOWN


def test_predicates_do_not_confuse_the_states():
    assert (R.TRUE.is_true, R.TRUE.is_false, R.TRUE.is_unknown) == (True, False, False)
    assert (R.FALSE.is_true, R.FALSE.is_false, R.FALSE.is_unknown) == (False, True, False)
    assert (R.UNKNOWN.is_true, R.UNKNOWN.is_false, R.UNKNOWN.is_unknown) == (
        False,
        False,
        True,
    )


def test_is_known_separates_decided_from_undecided():
    assert R.TRUE.is_known is True
    assert R.FALSE.is_known is True
    assert R.UNKNOWN.is_known is False


def test_unknown_is_not_false():
    """가장 흔한 착각. '모른다' 와 '아니다' 는 다른 답이다."""
    assert R.UNKNOWN is not R.FALSE
    assert R.UNKNOWN.is_false is False


# ----------------------------------------------------------------------
# 파이썬 진리값은 아예 막혀 있다
# ----------------------------------------------------------------------


def test_truthiness_raises_for_every_state():
    """
    ``if result:`` 한 줄이면 삼치 논리가 무너진다. ``str`` 을 섞은 enum
    이었다면 ``bool(UNKNOWN)`` 이 **참**이 되어 "모른다" 가 조용히
    "그렇다" 로 바뀐다. 그래서 값을 돌려주지 않고 예외를 던진다.
    """
    for result in R:
        with pytest.raises(TypeError):
            bool(result)
        with pytest.raises(TypeError):
            if result:  # noqa: SIM103
                pass


def test_python_boolean_operators_are_blocked():
    with pytest.raises(TypeError):
        R.UNKNOWN or False
    with pytest.raises(TypeError):
        R.UNKNOWN and True
    with pytest.raises(TypeError):
        not R.UNKNOWN


def test_result_is_not_a_string_enum():
    """
    ``str`` 을 상속했다면 ``bool(UNKNOWN)`` 이 빈 문자열이 아니라서 참이
    되고, ``__bool__`` 을 막아도 다른 경로로 샌다.
    """
    assert not issubclass(R, str)
    assert R.UNKNOWN != "unknown"


# ----------------------------------------------------------------------
# B. 진리표 전체
# ----------------------------------------------------------------------

AND_TABLE = [
    (R.TRUE, R.TRUE, R.TRUE),
    (R.TRUE, R.FALSE, R.FALSE),
    (R.TRUE, R.UNKNOWN, R.UNKNOWN),
    (R.FALSE, R.TRUE, R.FALSE),
    (R.FALSE, R.FALSE, R.FALSE),
    (R.FALSE, R.UNKNOWN, R.FALSE),
    (R.UNKNOWN, R.TRUE, R.UNKNOWN),
    (R.UNKNOWN, R.FALSE, R.FALSE),
    (R.UNKNOWN, R.UNKNOWN, R.UNKNOWN),
]

OR_TABLE = [
    (R.TRUE, R.TRUE, R.TRUE),
    (R.TRUE, R.FALSE, R.TRUE),
    (R.TRUE, R.UNKNOWN, R.TRUE),
    (R.FALSE, R.TRUE, R.TRUE),
    (R.FALSE, R.FALSE, R.FALSE),
    (R.FALSE, R.UNKNOWN, R.UNKNOWN),
    (R.UNKNOWN, R.TRUE, R.TRUE),
    (R.UNKNOWN, R.FALSE, R.UNKNOWN),
    (R.UNKNOWN, R.UNKNOWN, R.UNKNOWN),
]


@pytest.mark.parametrize("left,right,expected", AND_TABLE)
def test_and_truth_table(left, right, expected):
    assert left.logical_and(right) is expected


@pytest.mark.parametrize("left,right,expected", OR_TABLE)
def test_or_truth_table(left, right, expected):
    assert left.logical_or(right) is expected


@pytest.mark.parametrize(
    "value,expected",
    [(R.TRUE, R.FALSE), (R.FALSE, R.TRUE), (R.UNKNOWN, R.UNKNOWN)],
)
def test_not_truth_table(value, expected):
    assert value.logical_not() is expected


def test_and_and_or_are_commutative():
    for left in R:
        for right in R:
            assert left.logical_and(right) is right.logical_and(left)
            assert left.logical_or(right) is right.logical_or(left)


def test_double_negation_returns_the_original():
    for value in R:
        assert value.logical_not().logical_not() is value


# ----------------------------------------------------------------------
# C. 단락 평가 — UNKNOWN 을 구제하는 두 경우
# ----------------------------------------------------------------------


def test_a_certain_false_defeats_unknown_in_and():
    """하나가 확실히 거짓이면 나머지를 몰라도 전체가 거짓이다."""
    assert R.FALSE.logical_and(R.UNKNOWN) is R.FALSE
    assert R.all_of([R.UNKNOWN, R.FALSE, R.UNKNOWN]) is R.FALSE


def test_a_certain_true_defeats_unknown_in_or():
    """
    OR 단락 평가가 없으면 조건 하나만 미해석이어도 트리 전체가
    ``UNKNOWN`` 이 된다.
    """
    assert R.TRUE.logical_or(R.UNKNOWN) is R.TRUE
    assert R.any_of([R.UNKNOWN, R.TRUE, R.UNKNOWN]) is R.TRUE


def test_unknown_survives_when_nothing_decides_it():
    assert R.all_of([R.TRUE, R.UNKNOWN, R.TRUE]) is R.UNKNOWN
    assert R.any_of([R.FALSE, R.UNKNOWN, R.FALSE]) is R.UNKNOWN


def test_short_circuit_stops_consuming_the_iterator():
    """단락은 뒤를 **보지 않는다.** 평가 비용과 부작용 양쪽에서 중요하다."""
    seen: list[R] = []

    def watched(values):
        for value in values:
            seen.append(value)
            yield value

    assert R.all_of(watched([R.FALSE, R.TRUE, R.TRUE])) is R.FALSE
    assert seen == [R.FALSE]

    seen.clear()
    assert R.any_of(watched([R.TRUE, R.FALSE, R.FALSE])) is R.TRUE
    assert seen == [R.TRUE]


# ----------------------------------------------------------------------
# 빈 묶음
# ----------------------------------------------------------------------


def test_empty_all_is_true_and_empty_any_is_false():
    """조건이 없으면 막을 것이 없고, 선택지가 없으면 고를 것이 없다."""
    assert R.all_of([]) is R.TRUE
    assert R.any_of([]) is R.FALSE


# ----------------------------------------------------------------------
# from_bool
# ----------------------------------------------------------------------


def test_from_bool_only_produces_decided_values():
    assert R.from_bool(True) is R.TRUE
    assert R.from_bool(False) is R.FALSE
    assert R.from_bool(1 > 0) is R.TRUE


def test_from_bool_never_produces_unknown():
    """
    ``UNKNOWN`` 은 불리언에서 나올 수 없다. 정보 부족을 표현하려면 애초에
    ``UNKNOWN`` 을 돌려줘야지 ``False`` 를 거쳐 오면 안 된다.
    """
    assert R.from_bool(True) is not R.UNKNOWN
    assert R.from_bool(False) is not R.UNKNOWN
