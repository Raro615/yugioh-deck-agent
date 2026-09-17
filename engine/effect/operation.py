"""
Operation — "효과가 해결되면 판에 **어떤 의미의 변화**가 생기는가".

**아무것도 바꾸지 않는다.** Operation 을 만드는 것은 청구서를 쓰는 일이지
돈을 내는 일이 아니다. 실제 존 이동은 Phase 2-D-2 의 실행기가 한다.

PlayerAction 과 다르다
----------------------
``DestroyOperation`` 에 대응하는 ``PlayerActionKind.DESTROY`` 를 **만들지
않는다** (ADR-001 · ADR-002). 흐름은 한 방향이다.

    PlayerAction.ACTIVATE_EFFECT   플레이어가 고른 것
        ↓
    EffectDefinition
        ↓
    Operation.DESTROY              효과가 하는 것

목적지로 의미를 구분하지 않는다
-------------------------------
파괴 · 묘지로 보내기 · 릴리스는 **전부 묘지로 간다.** 목적지로는 절대
구분할 수 없다. 구분은 ``REASON_*`` 비트 하나다 (ADR-002).

===================  ==========================  ====================
Operation            reason                      뜻
===================  ==========================  ====================
``DESTROY``          ``DESTROY | EFFECT``        파괴된다
``SEND_TO_GRAVE``    ``EFFECT``                  묘지로 보내진다
``RELEASE``          ``RELEASE``                 릴리스된다
===================  ==========================  ====================

세 줄이 전부 묘지로 끝나지만 서로 다른 사건이다. "파괴되었을 때" 트리거는
가운데와 아래로 발동하지 않고, 파괴 내성은 가운데를 막지 못한다.

무엇을 대상으로 하는가
----------------------
카드를 다루는 일은 **이름으로** 대상을 가리킨다
(:class:`~engine.effect.target.TargetRef`). 규칙 자체는 정의가 들고 있고,
실제로 골라진 카드는 해결 문맥에 있다.

    EffectDefinition.targets      @primary -> "상대 몬스터 1장을 대상으로"
    CardOperation.destroy(@primary)         "그것을 파괴한다"
    ResolutionContext.selections  @primary -> #7

``InstanceId`` 를 일에 박아 넣지 않는다. 박으면 그 정의는 한 판에서 한 번밖에
쓸 수 없다.

대상이 없는 일과 대상을 빠뜨린 일은 다르다
------------------------------------------
:class:`DrawOperation` 에는 ``target_ref`` **칸 자체가 없다** — 드로우에는
대상이 없기 때문이고, 없는 것을 ``None`` 으로 표현하면 "빠뜨렸다" 와
구분되지 않는다. 반대로 :class:`CardOperation` 은 ``target_ref`` 가 **반드시**
있어야 한다.

수치가 아니라 이름을 담는다
---------------------------
``REASON_*`` 의 **숫자를 여기에 적지 않는다.** ``engine/vocabulary.py`` 의
원칙 그대로 이름만 들고 있고, 값은 필요할 때 ``constant.lua`` 에서 읽는다
(:meth:`Operation.reason_mask`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import PlayerRef
from engine.effect.target import TargetRef


class OperationKind(str, Enum):
    """
    효과가 하는 일.

    ``analysis.effect_model.ActionKind`` 와 **다른 어휘**다. 그쪽은 Lua 를
    읽은 기록의 분류이고 (``ACTION_DESTINATION`` 이 파괴와 묘지送り를 같은
    ``"GRAVE"`` 로 합친다), 이쪽은 실행 의미다. 그래서 가져오지 않는다.
    """

    DESTROY = "destroy"
    """파괴한다. **묘지로 보내는 것이 아니다.**"""
    SEND_TO_GRAVE = "send_to_grave"
    """묘지로 보낸다. **파괴가 아니다.**"""
    BANISH = "banish"
    RELEASE = "release"
    """릴리스한다. 파괴도 묘지로 보내기도 아니다."""
    DISCARD = "discard"
    RETURN_TO_HAND = "return_to_hand"
    RETURN_TO_DECK = "return_to_deck"
    DRAW = "draw"
    CHANGE_LIFE = "change_life"
    UNKNOWN = "unknown"
    """무엇을 하는지 구조화하지 못했다."""


#: 종류별 ``REASON_*`` 이름. **값이 아니라 이름이다.**
#:
#: 전투 · 비용으로 인한 경우는 여기 없다 — 그것은 효과가 아니라 다른 경로이고,
#: 그 경로가 생길 때 (Phase 2-D-2 이후) 함께 정한다.
REASON_NAMES: dict[OperationKind, tuple[str, ...]] = {
    OperationKind.DESTROY: ("DESTROY", "EFFECT"),
    OperationKind.SEND_TO_GRAVE: ("EFFECT",),
    OperationKind.BANISH: ("EFFECT",),
    OperationKind.RELEASE: ("RELEASE",),
    OperationKind.DISCARD: ("DISCARD", "EFFECT"),
    OperationKind.RETURN_TO_HAND: ("RETURN", "EFFECT"),
    OperationKind.RETURN_TO_DECK: ("RETURN", "EFFECT"),
    OperationKind.DRAW: ("DRAW", "EFFECT"),
    OperationKind.CHANGE_LIFE: ("EFFECT",),
    OperationKind.UNKNOWN: (),
}

#: 카드를 대상으로 하는 종류. 나머지는 수치를 다룬다.
CARD_OPERATION_KINDS: frozenset[OperationKind] = frozenset(
    {
        OperationKind.DESTROY,
        OperationKind.SEND_TO_GRAVE,
        OperationKind.BANISH,
        OperationKind.RELEASE,
        OperationKind.DISCARD,
        OperationKind.RETURN_TO_HAND,
        OperationKind.RETURN_TO_DECK,
    }
)


@dataclass(frozen=True, slots=True)
class Operation:
    """
    효과가 하는 일 하나. **불변**이고, 만들어도 아무 일도 일어나지 않는다.
    """

    @property
    def kind(self) -> OperationKind:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def reason_names(self) -> tuple[str, ...]:
        """이 일이 **왜** 일어나는가. ``REASON_*`` 상수 이름들."""
        return REASON_NAMES[self.kind]

    @property
    def target_refs(self) -> tuple["TargetRef", ...]:
        """
        이 일이 쓰는 대상 이름들. **대상이 없는 일은 빈 튜플이다.**

        비어 있다는 것은 "대상을 빠뜨렸다" 가 아니라 "대상이 필요 없다" 는
        뜻이다. 빠뜨린 경우는 애초에 만들어지지 않는다 —
        :class:`CardOperation` 이 ``target_ref`` 를 필수로 받기 때문이다.
        """
        return ()

    def reason_mask(self, vocabulary=None) -> int:
        """
        ``reason_names`` 를 실제 비트마스크로 바꾼다.

        값은 ``constant.lua`` 에서 읽는다 — 여기에 숫자를 적어 두지 않는다.
        읽을 수 없는 이름은 **조용히 0 으로 만들지 않고** 거부한다.
        """
        if vocabulary is None:
            from engine.vocabulary import default_vocabulary

            vocabulary = default_vocabulary()
        mask = 0
        for name in self.reason_names:
            value = vocabulary.reasons.value(name)
            if value is None:
                raise KeyError(f"REASON_{name} 을 상수에서 찾을 수 없습니다.")
            mask |= value
        return mask

    def canonical_state(self) -> tuple:
        raise NotImplementedError  # pragma: no cover - 추상

    def to_dict(self) -> dict:
        raise NotImplementedError  # pragma: no cover - 추상

    def describe_ko(self) -> str:
        raise NotImplementedError  # pragma: no cover - 추상

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class CardOperation(Operation):
    """
    카드에 무언가 하는 일. 대상을 **이름으로** 가리킨다.

    :meth:`destroy` · :meth:`send_to_grave` · :meth:`banish` 등으로 만든다.
    같은 대상이라도 :attr:`operation` 이 다르면 **다른 사건**이다.

    ``target_ref`` 는 반드시 있어야 한다. 카드를 다루는 일인데 어느 카드인지
    말하지 않으면 그것은 일이 아니다.
    """

    operation: OperationKind
    target_ref: TargetRef

    def __post_init__(self) -> None:
        if self.operation not in CARD_OPERATION_KINDS:
            raise ValueError(
                f"{self.operation.value} 는 카드를 다루는 일이 아닙니다."
            )
        if not isinstance(self.target_ref, TargetRef):
            raise TypeError(
                f"{self.operation.value} 에는 TargetRef 가 필요합니다. "
                "정의가 선언한 대상의 이름을 주세요 (예: PRIMARY_TARGET). "
                f"들어온 것: {self.target_ref!r}"
            )

    @property
    def kind(self) -> OperationKind:
        return self.operation

    @property
    def target_refs(self) -> tuple[TargetRef, ...]:
        return (self.target_ref,)

    @classmethod
    def destroy(cls, target_ref: TargetRef) -> "CardOperation":
        """파괴한다. 결과적으로 묘지에 가더라도 **묘지로 보내는 것이 아니다.**"""
        return cls(OperationKind.DESTROY, target_ref)

    @classmethod
    def send_to_grave(cls, target_ref: TargetRef) -> "CardOperation":
        """묘지로 보낸다. **파괴가 아니다** — 파괴 내성이 막지 못한다."""
        return cls(OperationKind.SEND_TO_GRAVE, target_ref)

    @classmethod
    def banish(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.BANISH, target_ref)

    @classmethod
    def release(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.RELEASE, target_ref)

    @classmethod
    def discard(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.DISCARD, target_ref)

    @classmethod
    def return_to_hand(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.RETURN_TO_HAND, target_ref)

    @classmethod
    def return_to_deck(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.RETURN_TO_DECK, target_ref)

    def canonical_state(self) -> tuple:
        return (
            "card_operation",
            self.operation.value,
            self.reason_names,
            self.target_ref.name,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "card_operation",
            "operation": self.operation.value,
            "reasons": list(self.reason_names),
            "target_ref": self.target_ref.name,
        }

    def describe_ko(self) -> str:
        korean = {
            OperationKind.DESTROY: "파괴",
            OperationKind.SEND_TO_GRAVE: "묘지로 보냄",
            OperationKind.BANISH: "제외",
            OperationKind.RELEASE: "릴리스",
            OperationKind.DISCARD: "버림",
            OperationKind.RETURN_TO_HAND: "패로 되돌림",
            OperationKind.RETURN_TO_DECK: "덱으로 되돌림",
        }[self.operation]
        return f"{self.target_ref} 을 {korean}"


@dataclass(frozen=True, slots=True)
class DrawOperation(Operation):
    """카드를 뽑는다. 뽑지 않는다 — 뽑는다는 **의미**를 담을 뿐이다."""

    count: int = 1
    who: PlayerRef = PlayerRef.CONTROLLER

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError(f"드로우 매수는 양수여야 합니다: {self.count}")

    @property
    def kind(self) -> OperationKind:
        return OperationKind.DRAW

    def canonical_state(self) -> tuple:
        return ("draw", self.count, self.who.value, self.reason_names)

    def to_dict(self) -> dict:
        return {
            "kind": "draw",
            "count": self.count,
            "who": self.who.value,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        return f"{self.who} 가 {self.count}장 드로우"


@dataclass(frozen=True, slots=True)
class LifeChangeOperation(Operation):
    """
    라이프를 바꾼다. **바꾸지 않는다.**

    ``delta`` 가 음수면 줄어들고 양수면 늘어난다.

    .. note::
       "효과 데미지" 와 "효과로 라이프가 줄어든다" 는 유희왕 규칙상 다르다
       (전자만 데미지 무효·반사의 대상이다). 그 구분을 담으려면 데미지
       처리 계층이 있어야 하고, 지금은 없다. 지어내지 않고 남겨 둔다.
    """

    delta: int
    who: PlayerRef = PlayerRef.CONTROLLER

    def __post_init__(self) -> None:
        if self.delta == 0:
            raise ValueError("변화량이 0 인 라이프 조작은 의미가 없습니다.")

    @property
    def kind(self) -> OperationKind:
        return OperationKind.CHANGE_LIFE

    @property
    def is_loss(self) -> bool:
        return self.delta < 0

    def canonical_state(self) -> tuple:
        return ("change_life", self.delta, self.who.value, self.reason_names)

    def to_dict(self) -> dict:
        return {
            "kind": "change_life",
            "delta": self.delta,
            "who": self.who.value,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        verb = "감소" if self.is_loss else "회복"
        return f"{self.who} 라이프 {abs(self.delta)} {verb}"


@dataclass(frozen=True, slots=True)
class UnimplementedOperation(Operation):
    """
    **아직 표현할 수 없는 일.**

    소환 · 표시 형식 변경 · 수치 변경 · 무효화처럼 지금 어휘가 담지 못하는
    것을 솔직하게 표현한다. 지어낸 Operation 으로 채우지 않는다.
    """

    rule: str

    @property
    def kind(self) -> OperationKind:
        return OperationKind.UNKNOWN

    def canonical_state(self) -> tuple:
        return ("unimplemented_operation", self.rule)

    def to_dict(self) -> dict:
        return {"kind": "unimplemented_operation", "rule": self.rule}

    def describe_ko(self) -> str:
        return f"표현 불가({self.rule})"


__all__ = [
    "OperationKind",
    "REASON_NAMES",
    "CARD_OPERATION_KINDS",
    "Operation",
    "CardOperation",
    "DrawOperation",
    "LifeChangeOperation",
    "UnimplementedOperation",
]
