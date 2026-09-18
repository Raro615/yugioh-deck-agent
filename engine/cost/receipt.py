"""
CostPayment — **실제로 무엇을 지불했는가** (영수증).

    Cost          무엇을 내놓아야 하는가        청구서
    CostPayment   실제로 무엇을 내놓았는가      영수증

청구서는 :mod:`engine.cost.model` 에 있고, 영수증은 여기 있다. 둘을 한
타입으로 합치면 "내야 한다" 와 "냈다" 가 구분되지 않는다.

영수증도 판을 바꾸지 않는다
---------------------------
:class:`CostPayment` 에 ``apply`` 도 ``undo`` 도 없다. 지불은
:class:`~engine.payment.CostPayer` 가 하고, 이것은 그 결과를 적을 뿐이다.
:class:`~engine.effect.delta.StateDelta` 와 같은 태도다.

StateDelta 와 무엇이 다른가
---------------------------
=====================  ==========================================
``CostPayment``         **어떤 비용**을 치렀는가
``StateDelta``          그 결과 **판이 어떻게 달라졌는가**
=====================  ==========================================

"패에서 2장을 버렸다" 는 영수증 하나 · 변화 둘이다. ``AppliedOperation``
과 ``StateDelta`` 의 관계와 같다.

의미를 목적지로 뭉개지 않는다
-----------------------------
버리기와 릴리스는 둘 다 묘지로 가지만 서로 다른 사건이다. 영수증은
:class:`~engine.cost.model.CostSemantics` 를 그대로 들고 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.cost.model import CostSemantics
from engine.ids import InstanceId


@dataclass(frozen=True, slots=True)
class CostPayment:
    """
    치른 비용 하나의 기록. **불변**이고 값 타입만 담는다.

    ``amount`` 는 **요청한 값**이다. 라이프가 모자라 실제로 덜 깎였다면 그
    사실은 :class:`~engine.effect.delta.LifeChanged` 의 ``before`` /
    ``after`` 에 남는다 — 다만 지불은 애초에 모자라면 시작하지 않으므로
    (``CostValidator`` 가 먼저 막는다) 지금은 둘이 같다.
    """

    semantics: CostSemantics
    instances: tuple[InstanceId, ...] = ()
    """내놓은 카드들. 라이프 지불이면 비어 있다."""
    amount: int | None = None
    """지불한 라이프. 카드 비용이면 ``None``."""
    player: int | None = None
    """누가 치렀는가."""

    def __post_init__(self) -> None:
        if not isinstance(self.instances, tuple):
            raise TypeError("instances 는 tuple 이어야 합니다 — 영수증은 불변입니다.")
        if self.player is not None and self.player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {self.player}")
        if self.semantics is CostSemantics.PAY_LIFE:
            if self.amount is None or self.amount <= 0:
                raise ValueError("라이프 지불에는 양수 금액이 필요합니다.")
            if self.instances:
                raise ValueError("라이프 지불에 카드가 딸려 있습니다.")
        elif self.amount is not None:
            raise ValueError(
                f"{self.semantics.value} 는 카드 비용인데 금액이 붙어 있습니다."
            )

    def canonical_state(self) -> tuple:
        return (
            self.semantics.value,
            tuple(i.value for i in self.instances),
            self.amount,
            self.player,
        )

    def to_dict(self) -> dict:
        data: dict = {"semantics": self.semantics.value}
        if self.instances:
            data["instances"] = [i.value for i in self.instances]
        if self.amount is not None:
            data["amount"] = self.amount
        if self.player is not None:
            data["player"] = self.player
        return data

    def describe_ko(self) -> str:
        korean = {
            CostSemantics.RELEASE: "릴리스",
            CostSemantics.DISCARD: "패에서 버림",
            CostSemantics.BANISH: "제외",
            CostSemantics.SEND_TO_GRAVE: "묘지로 보냄",
            CostSemantics.DETACH: "소재 제거",
            CostSemantics.PAY_LIFE: "라이프 지불",
            CostSemantics.UNKNOWN: "알 수 없는 비용",
        }[self.semantics]
        if self.semantics is CostSemantics.PAY_LIFE:
            return f"P{self.player} {korean} {self.amount}"
        cards = ", ".join(str(i) for i in self.instances)
        return f"P{self.player} {cards} {korean}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


__all__ = ["CostPayment"]
