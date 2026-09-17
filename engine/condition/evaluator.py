"""
조건 평가의 진입점.

:class:`ConditionEvaluator` 는 **관측 하나를 쥐고** 조건을 판정한다.
``GameState`` 를 받지 않는 것이 핵심이다 — 받으면 ``move()`` ·
``change_life()`` 가 손에 닿고, 조건이 판을 바꿀 수 있게 된다.

    GameState → GameStateView → ConditionEvaluator → ConditionVerdict

``ConditionVerdict`` 는 판정과 **그 근거**를 함께 낸다. ``UNKNOWN`` 일 때
무엇 때문에 모르는지 말해주지 않으면, 부르는 쪽이 "그냥 안 되나 보다" 하고
거짓처럼 다루게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.condition.context import ConditionContext
from engine.condition.model import Condition
from engine.condition.result import ConditionResult
from engine.game_state_view import GameStateView


@dataclass(frozen=True, slots=True)
class ConditionVerdict:
    """판정 하나와 그 근거."""

    result: ConditionResult
    description: str
    """조건을 한국어로 풀어 쓴 것. 설명 · 디버깅용."""
    unknown_reasons: tuple[str, ...] = ()
    """``UNKNOWN`` 일 때 무엇 때문에 모르는가. 확정된 판정이면 비어 있다."""

    @property
    def is_true(self) -> bool:
        return self.result.is_true

    @property
    def is_false(self) -> bool:
        return self.result.is_false

    @property
    def is_unknown(self) -> bool:
        return self.result.is_unknown

    def __bool__(self) -> bool:
        raise TypeError(
            "ConditionVerdict 를 참/거짓으로 쓸 수 없습니다. "
            "`verdict.result is ConditionResult.TRUE` 로 비교하세요."
        )

    def canonical_state(self) -> tuple:
        return (self.result.value, self.description, self.unknown_reasons)

    def to_dict(self) -> dict:
        return {
            "result": self.result.value,
            "description": self.description,
            "unknown_reasons": list(self.unknown_reasons),
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        if self.unknown_reasons:
            return f"{self.result.value} ({'; '.join(self.unknown_reasons)})"
        return self.result.value


class ConditionEvaluator:
    """
    관측 하나에 대해 조건을 판정한다.

    **상태를 바꾸지 않는다.** 애초에 바꿀 수 있는 것을 들고 있지 않다 —
    :class:`~engine.game_state_view.GameStateView` 는 frozen dataclass 로만
    이루어진 스냅숏이다.

    평가기 자신도 상태를 쌓지 않는다. 같은 관측 · 같은 문맥이면 몇 번을
    물어도 같은 답이 나온다.
    """

    __slots__ = ("_view",)

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "ConditionEvaluator 는 GameStateView 만 받습니다. "
                "GameState 를 직접 넘기면 조건이 판을 바꿀 수 있게 됩니다 "
                "(GameStateView.from_state 로 감싸세요)."
            )
        self._view = view

    @property
    def view(self) -> GameStateView:
        return self._view

    def result(
        self, condition: Condition, context: ConditionContext
    ) -> ConditionResult:
        """판정 값만 필요할 때."""
        return condition.evaluate(self._view, context)

    def evaluate(
        self, condition: Condition, context: ConditionContext
    ) -> ConditionVerdict:
        """
        판정과 근거를 함께 낸다.

        ``UNKNOWN`` 일 때만 이유를 모은다 — 확정된 판정에는 모을 것이 없고,
        모으는 순회를 건너뛸 수 있다.
        """
        result = condition.evaluate(self._view, context)
        reasons = (
            condition.unknown_reasons(self._view, context)
            if result is ConditionResult.UNKNOWN
            else ()
        )
        return ConditionVerdict(
            result=result,
            description=condition.describe_ko(),
            unknown_reasons=reasons,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ConditionEvaluator {self._view}>"
