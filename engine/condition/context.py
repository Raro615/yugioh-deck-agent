"""
조건이 판정되는 **문맥**.

같은 조건이라도 누구의 조건인지, 어느 카드가 물어보는지에 따라 답이 달라진다.
"자신 필드에 몬스터가 있는가" 의 "자신" 은 문맥이 정한다.

담는 것은 전부 Phase 1 · 2-A 가 이미 정의한 **안정적인 식별자**다. 파이썬
객체 참조를 담으면 문맥이 특정 ``GameState`` 에 묶이고, 직렬화도 replay 도
불가능해진다.

지금 담지 않는 것
-----------------
체인 문맥 · 직전 이벤트 · 발동 이유. **아직 그 시스템이 없기 때문이다.**
자리만 만들어 두면 모양을 미리 못박게 되므로, 그런 정보가 필요한 조건은
지금은 ``UNKNOWN`` 을 돌려준다 (``UnimplementedRule``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.ids import EffectRef, InstanceId


class PlayerRef(str, Enum):
    """
    조건이 가리키는 플레이어. **문맥 상대적**이다.

    카드 텍스트의 "자신" / "상대" 에 대응한다. 절대 번호(0/1)를 조건에
    적어 넣으면 같은 조건을 양쪽이 쓸 수 없다.
    """

    CONTROLLER = "controller"
    """이 조건의 주인 (:attr:`ConditionContext.player`)."""
    OPPONENT = "opponent"

    def resolve(self, context: "ConditionContext") -> int:
        return context.player if self is PlayerRef.CONTROLLER else context.opponent

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return "자신" if self is PlayerRef.CONTROLLER else "상대"


@dataclass(frozen=True, slots=True)
class ConditionContext:
    """
    조건 하나를 판정하는 데 필요한 문맥. **불변**이다.

    ``player`` 만 필수다. 나머지는 없을 수 있고, 없는데 필요하면 조건이
    ``UNKNOWN`` 을 돌려준다 — 예외를 던지거나 임의의 값을 고르지 않는다.
    """

    player: int
    """이 조건은 누구의 것인가. ``PlayerRef.CONTROLLER`` 가 가리키는 쪽."""
    source: InstanceId | None = None
    """조건을 묻고 있는 카드. 없을 수 있다."""
    effect_ref: EffectRef | None = None
    """지금 판정 중인 효과. 없을 수 있다."""
    targets: tuple[InstanceId, ...] = ()
    """이미 정해진 대상들. 순서가 의미를 가질 수 있으므로 정렬하지 않는다."""

    def __post_init__(self) -> None:
        if self.player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {self.player}")
        if not isinstance(self.targets, tuple):
            raise TypeError("targets 는 tuple 이어야 합니다 — 문맥은 불변입니다.")

    @property
    def opponent(self) -> int:
        return 1 - self.player

    def canonical_state(self) -> tuple:
        """정수 · 문자열 · ``None`` 만으로 이루어진 정규 표현."""
        return (
            self.player,
            self.source.value if self.source is not None else None,
            (self.effect_ref.card_id, self.effect_ref.ordinal)
            if self.effect_ref is not None
            else None,
            tuple(t.value for t in self.targets),
        )

    def to_dict(self) -> dict:
        data: dict = {"player": self.player}
        if self.source is not None:
            data["source"] = self.source.value
        if self.effect_ref is not None:
            data["effect_ref"] = {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            }
        if self.targets:
            data["targets"] = [t.value for t in self.targets]
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        bits = [f"P{self.player}"]
        if self.source is not None:
            bits.append(str(self.source))
        if self.effect_ref is not None:
            bits.append(str(self.effect_ref))
        return " ".join(bits)
