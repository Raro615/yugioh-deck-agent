"""
조건 평가의 결과 — 세 가지다.

``TRUE`` / ``FALSE`` / ``UNKNOWN``.

**``UNKNOWN`` 은 세 번째 값이지 "거짓의 일종"이 아니다.** 정보가 가려져
있거나 판정할 규칙이 아직 없다는 뜻이고, 편의상 참이나 거짓으로 접으면
그 순간 엔진이 모르는 것을 아는 척하게 된다.

파이썬 진리값을 막는다
----------------------
``if result:`` 한 줄이면 삼치 논리가 무너진다. 특히 :class:`str` 을 섞은
enum 이었다면 ``bool(UNKNOWN)`` 이 빈 문자열이 아니라서 **참**이 되고,
"모른다" 가 조용히 "그렇다" 로 바뀐다.

그래서 :meth:`ConditionResult.__bool__` 은 값을 돌려주지 않고 **예외를
던진다.** 판정은 언제나 명시적으로 한다::

    if result is ConditionResult.TRUE:      # 좋다
    if result.is_true:                      # 좋다
    if result:                              # TypeError
    if result or fallback:                  # TypeError

삼치 논리
---------
설계 문서 §8 의 표를 그대로 구현한다. 핵심은 **단락(short-circuit)이
``UNKNOWN`` 을 구제한다**는 점이다.

- ``FALSE AND UNKNOWN`` 은 ``FALSE`` — 하나가 확실히 거짓이면 나머지를
  몰라도 전체가 거짓이다.
- ``TRUE OR UNKNOWN`` 은 ``TRUE`` — 하나가 확실히 참이면 마찬가지다.

이것이 없으면 조건 하나만 미해석이어도 트리 전체가 ``UNKNOWN`` 이 된다.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class ConditionResult(Enum):
    """조건 하나의 판정 결과."""

    TRUE = "true"
    """현재 정보만으로 참이라고 확정할 수 있다."""
    FALSE = "false"
    """현재 정보만으로 거짓이라고 확정할 수 있다."""
    UNKNOWN = "unknown"
    """
    판정할 수 없다. **거짓이 아니다.**

    두 가지 원인이 있고 둘 다 정당하다.

    1. 정보가 가려져 있다 (상대 패 · 덱 · 뒷면 카드).
    2. 판정할 규칙이 아직 구현되지 않았다.
    """

    # ------------------------------------------------------------------
    # 파이썬 진리값 금지
    # ------------------------------------------------------------------
    def __bool__(self) -> bool:
        raise TypeError(
            f"ConditionResult.{self.name} 을 참/거짓으로 쓸 수 없습니다. "
            "UNKNOWN 이 조용히 참이 되는 것을 막기 위해서입니다. "
            "`result is ConditionResult.TRUE` 또는 `result.is_true` 로 "
            "명시적으로 비교하세요."
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def is_true(self) -> bool:
        return self is ConditionResult.TRUE

    @property
    def is_false(self) -> bool:
        return self is ConditionResult.FALSE

    @property
    def is_unknown(self) -> bool:
        return self is ConditionResult.UNKNOWN

    @property
    def is_known(self) -> bool:
        """참이든 거짓이든 **확정되었는가.**"""
        return self is not ConditionResult.UNKNOWN

    # ------------------------------------------------------------------
    # 삼치 논리 — 파이썬 ``and`` / ``or`` / ``not`` 을 쓰지 않는다
    # ------------------------------------------------------------------
    def logical_and(self, other: "ConditionResult") -> "ConditionResult":
        """
        ==========  ==========  ==========
        좌           우           결과
        ==========  ==========  ==========
        TRUE        TRUE        TRUE
        TRUE        FALSE       FALSE
        TRUE        UNKNOWN     UNKNOWN
        FALSE       무엇이든     **FALSE**
        UNKNOWN     UNKNOWN     UNKNOWN
        ==========  ==========  ==========
        """
        if self is ConditionResult.FALSE or other is ConditionResult.FALSE:
            return ConditionResult.FALSE
        if self is ConditionResult.UNKNOWN or other is ConditionResult.UNKNOWN:
            return ConditionResult.UNKNOWN
        return ConditionResult.TRUE

    def logical_or(self, other: "ConditionResult") -> "ConditionResult":
        """
        ==========  ==========  ==========
        좌           우           결과
        ==========  ==========  ==========
        TRUE        무엇이든     **TRUE**
        FALSE       FALSE       FALSE
        FALSE       UNKNOWN     UNKNOWN
        UNKNOWN     UNKNOWN     UNKNOWN
        ==========  ==========  ==========
        """
        if self is ConditionResult.TRUE or other is ConditionResult.TRUE:
            return ConditionResult.TRUE
        if self is ConditionResult.UNKNOWN or other is ConditionResult.UNKNOWN:
            return ConditionResult.UNKNOWN
        return ConditionResult.FALSE

    def logical_not(self) -> "ConditionResult":
        """``TRUE ↔ FALSE``. ``UNKNOWN`` 은 부정해도 ``UNKNOWN`` 이다."""
        if self is ConditionResult.TRUE:
            return ConditionResult.FALSE
        if self is ConditionResult.FALSE:
            return ConditionResult.TRUE
        return ConditionResult.UNKNOWN

    # ------------------------------------------------------------------
    # 여러 개 접기
    # ------------------------------------------------------------------
    @staticmethod
    def all_of(results: Iterable["ConditionResult"]) -> "ConditionResult":
        """
        전부 참인가. **빈 묶음은 ``TRUE``** 다 (조건이 없으면 막을 것이 없다).

        ``FALSE`` 를 만나면 곧바로 멈춘다 — 뒤에 ``UNKNOWN`` 이 있어도
        전체는 이미 거짓이다.
        """
        verdict = ConditionResult.TRUE
        for result in results:
            verdict = verdict.logical_and(result)
            if verdict is ConditionResult.FALSE:
                return ConditionResult.FALSE
        return verdict

    @staticmethod
    def any_of(results: Iterable["ConditionResult"]) -> "ConditionResult":
        """
        하나라도 참인가. **빈 묶음은 ``FALSE``** 다 (참인 선택지가 없다).

        ``TRUE`` 를 만나면 곧바로 멈춘다.
        """
        verdict = ConditionResult.FALSE
        for result in results:
            verdict = verdict.logical_or(result)
            if verdict is ConditionResult.TRUE:
                return ConditionResult.TRUE
        return verdict

    @staticmethod
    def from_bool(value: bool) -> "ConditionResult":
        """
        확정된 파이썬 불리언을 결과로 바꾼다.

        **판단이 끝난 값에만 쓴다.** "모르겠으니 일단 ``False``" 를
        여기에 넣으면 정보 부족이 거짓으로 둔갑한다.
        """
        return ConditionResult.TRUE if value else ConditionResult.FALSE

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"ConditionResult.{self.name}"
