"""
비용 — "효과를 진행하려면 무엇을 내놓아야 하는가".

**치르지 않는다.** 여기 있는 것은 청구서이지 영수증이 아니다.

    ReleaseCost(...)          "몬스터 1장을 릴리스해야 한다"
    ≠ Zone.move(card, GRAVE)  "몬스터를 묘지로 보냈다"

analysis 의 비용 모델과 무엇이 다른가
--------------------------------------
``analysis.effect_model`` 에 이미 ``CostKind`` 19종과 ``EffectCost`` 가 있다.
그것은 **Lua 비용 함수를 읽은 기록**이다 — 가변 dataclass 이고 ``raw`` 에
원문을 들고 있으며, 지금 판에서 치를 수 있는지 판정하지 못한다.

여기의 비용은 **실행 전 검증용**이다. 불변이고, 원문이 없고, 관측을 받아
"지금 이것을 치를 수 있는가" 에 답한다. ``analysis`` 에서 아무것도 가져오지
않는다 — ``CostKind`` 라는 이름이 겹치는 것을 피하려고 열거형 대신 **클래스를
나눴다.** 조건 계층이 ``BoolOp.LEAF`` 를 쓰지 않고 ``And`` / ``Or`` / 술어를
따로 둔 것과 같은 이유다.

의미를 합치지 않는다
--------------------
릴리스 · 패 버리기 · 제외 · 묘지로 보내기는 **서로 다른 사건**이다. 결과적으로
같은 존에 가더라도 그렇다. :class:`CostSemantics` 가 그 구분을 담는다.

**파괴는 비용이 될 수 없다.** 유희왕에서 카드를 파괴하는 것은 효과의 결과이지
발동 비용이 아니고 (``analysis.CostKind`` 에도 없다), 여기에 넣으면
ADR-002 의 ``Destroy ≠ Send to Graveyard`` 가 비용 쪽에서 무너진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import Condition, ConditionContext, PlayerRef
from engine.cost.choice import CandidateSource, ChoiceSpec
from engine.vocabulary import Zone

#: 필드 위의 몬스터가 있는 곳.
FIELD_MONSTER_ZONES: frozenset[Zone] = frozenset({Zone.MZONE, Zone.EMZONE})


class CostSemantics(str, Enum):
    """
    비용으로 **무엇을 하는가.**

    목적지가 같아도 사건이 다르다. 릴리스된 몬스터와 묘지로 보내진 몬스터는
    둘 다 묘지에 있지만, "릴리스되었을 때" 트리거는 후자로 발동하지 않는다.

    ``DESTROY`` 가 **없다.** 파괴는 효과의 결과이지 비용이 아니다 (ADR-002).
    """

    RELEASE = "release"
    """릴리스(제물). 묘지로 가지만 파괴도 '묘지로 보내기'도 아니다."""
    DISCARD = "discard"
    """패에서 버린다."""
    BANISH = "banish"
    SEND_TO_GRAVE = "send_to_grave"
    """묘지로 보낸다. **릴리스가 아니다.**"""
    DETACH = "detach"
    """엑시즈 소재를 뗀다."""
    PAY_LIFE = "pay_life"
    UNKNOWN = "unknown"
    """비용이 있다는 것만 알고 내용은 모른다."""


@dataclass(frozen=True, slots=True)
class Cost:
    """
    비용 하나. **불변**이고, 관측을 받아 치를 수 있는지 말할 수 있을 뿐이다.

    실제 지불은 여기서 하지 않는다 — 어느 Phase 에서도 이 객체가 판을
    바꾸지 않는다.
    """

    @property
    def semantics(self) -> CostSemantics:
        raise NotImplementedError  # pragma: no cover - 추상

    def choice_spec(self) -> ChoiceSpec | None:
        """
        이 비용이 요구하는 **선택**. 고를 것이 없으면 ``None``.

        라이프 지불처럼 고를 것이 없는 비용은 ``None`` 이고, 그때는
        :class:`~engine.cost.validation.CostValidator` 가 다른 방법으로
        판정한다.
        """
        raise NotImplementedError  # pragma: no cover - 추상

    def canonical_state(self) -> tuple:
        raise NotImplementedError  # pragma: no cover - 추상

    def to_dict(self) -> dict:
        raise NotImplementedError  # pragma: no cover - 추상

    def describe_ko(self) -> str:
        raise NotImplementedError  # pragma: no cover - 추상

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class CardCost(Cost):
    """
    카드를 내놓는 비용. 어디에서 몇 장을, 어떤 조건으로 고르는가.

    :meth:`release` · :meth:`discard` · :meth:`banish` · :meth:`send_to_grave`
    로 만든다. 직접 만들 때는 :attr:`kind` 를 반드시 준다.
    """

    kind: CostSemantics
    zones: frozenset[Zone]
    count: int = 1
    maximum: int | None = None
    """``None`` 이면 :attr:`count` 와 같다 (정확히 그 수)."""
    who: PlayerRef = PlayerRef.CONTROLLER
    require: Condition | None = None
    """후보가 추가로 만족해야 하는 조건. 예: 어둠 속성 · 레벨 4 이상."""

    def __post_init__(self) -> None:
        if self.kind is CostSemantics.PAY_LIFE:
            raise ValueError("라이프 지불은 LifeCost 로 표현하세요.")
        if not isinstance(self.zones, frozenset):
            raise TypeError("zones 는 frozenset 이어야 합니다 — 비용은 불변입니다.")
        if not self.zones:
            raise ValueError("비용에는 카드를 고를 존이 최소 하나 필요합니다.")
        if self.count < 0:
            raise ValueError(f"장수는 음수일 수 없습니다: {self.count}")
        if self.maximum is not None and self.maximum < self.count:
            raise ValueError(
                f"최대({self.maximum})가 최소({self.count})보다 작습니다."
            )

    @property
    def semantics(self) -> CostSemantics:
        return self.kind

    @property
    def upper_bound(self) -> int:
        return self.maximum if self.maximum is not None else self.count

    def choice_spec(self) -> ChoiceSpec:
        return ChoiceSpec(
            chooser=self.who,
            source=CandidateSource(owner=self.who, zones=self.zones, require=self.require),
            minimum=self.count,
            maximum=self.upper_bound,
        )

    # --- 생성자 -------------------------------------------------------
    @classmethod
    def release(
        cls,
        count: int = 1,
        *,
        who: PlayerRef = PlayerRef.CONTROLLER,
        require: Condition | None = None,
        maximum: int | None = None,
    ) -> "CardCost":
        """필드의 몬스터를 릴리스한다. **파괴도 묘지로 보내기도 아니다.**"""
        return cls(
            kind=CostSemantics.RELEASE,
            zones=FIELD_MONSTER_ZONES,
            count=count,
            maximum=maximum,
            who=who,
            require=require,
        )

    @classmethod
    def discard(
        cls,
        count: int = 1,
        *,
        who: PlayerRef = PlayerRef.CONTROLLER,
        require: Condition | None = None,
        maximum: int | None = None,
    ) -> "CardCost":
        return cls(
            kind=CostSemantics.DISCARD,
            zones=frozenset({Zone.HAND}),
            count=count,
            maximum=maximum,
            who=who,
            require=require,
        )

    @classmethod
    def banish(
        cls,
        zones: frozenset[Zone],
        count: int = 1,
        *,
        who: PlayerRef = PlayerRef.CONTROLLER,
        require: Condition | None = None,
        maximum: int | None = None,
    ) -> "CardCost":
        return cls(
            kind=CostSemantics.BANISH,
            zones=zones,
            count=count,
            maximum=maximum,
            who=who,
            require=require,
        )

    @classmethod
    def send_to_grave(
        cls,
        zones: frozenset[Zone],
        count: int = 1,
        *,
        who: PlayerRef = PlayerRef.CONTROLLER,
        require: Condition | None = None,
        maximum: int | None = None,
    ) -> "CardCost":
        """묘지로 보낸다. 릴리스와 **다른 사건**이다."""
        return cls(
            kind=CostSemantics.SEND_TO_GRAVE,
            zones=zones,
            count=count,
            maximum=maximum,
            who=who,
            require=require,
        )

    # --- 직렬화 -------------------------------------------------------
    def canonical_state(self) -> tuple:
        return (
            "card_cost",
            self.kind.value,
            tuple(sorted(z.value for z in self.zones)),
            self.count,
            self.maximum,
            self.who.value,
            self.require.canonical_state() if self.require is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "card_cost",
            "semantics": self.kind.value,
            "zones": sorted(z.value for z in self.zones),
            "count": self.count,
            "who": self.who.value,
        }
        if self.maximum is not None:
            data["maximum"] = self.maximum
        if self.require is not None:
            data["require"] = self.require.to_dict()
        return data

    def describe_ko(self) -> str:
        korean = {
            CostSemantics.RELEASE: "릴리스",
            CostSemantics.DISCARD: "패에서 버림",
            CostSemantics.BANISH: "제외",
            CostSemantics.SEND_TO_GRAVE: "묘지로 보냄",
            CostSemantics.DETACH: "소재 제거",
        }[self.kind]
        amount = (
            f"{self.count}장"
            if self.maximum is None or self.maximum == self.count
            else f"{self.count}~{self.maximum}장"
        )
        what = f" ({self.require.describe_ko()})" if self.require is not None else ""
        return f"{self.who} {'/'.join(sorted(z.value for z in self.zones))} 에서 {amount}{what} {korean}"


@dataclass(frozen=True, slots=True)
class LifeCost(Cost):
    """
    라이프를 지불한다. **실제로 깎지 않는다** — 낼 수 있는지만 본다.

    "지불할 수 있는가" 의 정확한 규칙(0 이 되어도 되는가 등)은 규칙 계층의
    문제다. 여기서는 **남은 라이프가 그 값 이상인가**만 본다.
    """

    amount: int
    who: PlayerRef = PlayerRef.CONTROLLER

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"지불할 라이프는 양수여야 합니다: {self.amount}")

    @property
    def semantics(self) -> CostSemantics:
        return CostSemantics.PAY_LIFE

    def choice_spec(self) -> None:
        """고를 것이 없다."""
        return None

    def canonical_state(self) -> tuple:
        return ("life_cost", self.amount, self.who.value)

    def to_dict(self) -> dict:
        return {"kind": "life_cost", "amount": self.amount, "who": self.who.value}

    def describe_ko(self) -> str:
        return f"{self.who} 라이프 {self.amount} 지불"


@dataclass(frozen=True, slots=True)
class UnimplementedCost(Cost):
    """
    **아직 표현할 수 없는 비용.** 판정은 언제나 ``UNKNOWN`` 이다.

    엑시즈 소재 제거 · 카운터 제거 · 카드별 예외처럼 지금 모델이 담지 못하는
    것을 솔직하게 표현한다. 지어낸 비용으로 채우지 않는다.
    """

    rule: str
    kind: CostSemantics = CostSemantics.UNKNOWN

    @property
    def semantics(self) -> CostSemantics:
        return self.kind

    def choice_spec(self) -> None:
        return None

    def canonical_state(self) -> tuple:
        return ("unimplemented_cost", self.rule, self.kind.value)

    def to_dict(self) -> dict:
        return {
            "kind": "unimplemented_cost",
            "rule": self.rule,
            "semantics": self.kind.value,
        }

    def describe_ko(self) -> str:
        return f"표현 불가 비용({self.rule})"


@dataclass(frozen=True, slots=True)
class CostGroup:
    """
    함께 치러야 하는 비용들. **AND 관계**다.

    "라이프 1000 지불 **그리고** 몬스터 1장 릴리스" 를 표현한다.

    "둘 중 하나를 고른다" 는 **표현하지 않는다.** 선택지 있는 비용은 어느
    쪽을 고르느냐가 이후 처리까지 갈라지므로, 그 갈래를 담을 구조가 생긴
    뒤에 (Phase 2-D 이후) 다룬다. 지금 흉내 내면 모양을 미리 못박는다.
    """

    costs: tuple[Cost, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.costs, tuple):
            raise TypeError("costs 는 tuple 이어야 합니다 — 비용은 불변입니다.")

    @property
    def is_free(self) -> bool:
        """치를 것이 없는가. 빈 묶음은 언제나 치를 수 있다."""
        return not self.costs

    def choice_specs(self) -> tuple[ChoiceSpec, ...]:
        """고를 것이 있는 비용들의 선택 명세. 순서는 비용 순서 그대로다."""
        return tuple(
            spec for cost in self.costs if (spec := cost.choice_spec()) is not None
        )

    def canonical_state(self) -> tuple:
        return ("cost_group", tuple(c.canonical_state() for c in self.costs))

    def to_dict(self) -> dict:
        return {"kind": "cost_group", "costs": [c.to_dict() for c in self.costs]}

    def describe_ko(self) -> str:
        if not self.costs:
            return "(비용 없음)"
        return " 그리고 ".join(c.describe_ko() for c in self.costs)

    def __len__(self) -> int:
        return len(self.costs)

    def __iter__(self):
        return iter(self.costs)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


__all__ = [
    "CostSemantics",
    "Cost",
    "CardCost",
    "LifeCost",
    "UnimplementedCost",
    "CostGroup",
    "FIELD_MONSTER_ZONES",
]
