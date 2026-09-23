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
from engine.effect.target import SelectionCount, TargetRef
from engine.vocabulary import Zone


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
    SPECIAL_SUMMON = "special_summon"
    """
    몬스터를 **특수 소환한다** (Phase 2-U).

    ``MOVE`` 로 필드에 놓는 것과 **다르다.** 카드가 몬스터 존에 들어가는 것은
    같지만, 소환은 칸 · 표시 형식 · 소환 조건을 요구하고 "특수 소환되었을
    때" 트리거를 낳는다. 목적지만 같은 것을 같은 일로 적으면 그 구분이
    영영 사라진다 (ADR-002 가 파괴와 묘지로 보내기를 가른 것과 같은 이유).

    ``PlayerActionKind.SPECIAL_SUMMON`` 과도 **다른 어휘**다. 저쪽은 고르는
    주체가 고르는 행위이고, 이쪽은 효과 해결 중에 수행되는 일이다
    (ADR-001). 둘이 같은 절차(:class:`~engine.summon.SummonProcedure`)를
    쓰지만 같은 enum 은 아니다.
    """
    DRAW = "draw"
    CHANGE_LIFE = "change_life"
    SHUFFLE = "shuffle"
    """
    한 존의 카드 순서를 **무작위로 다시 늘어놓는다** (Phase 2-Z).

    카드가 존을 옮기지 않으므로 이동이 아니다. ``MOVE`` 와도 다르다 —
    저쪽은 목적지가 있고 이쪽은 없다. 룰북이 "shuffle it and put it back
    in this space" 라고 말하는 그 동작이다.

    **결과 순서를 변화에 적지 않는다.** 섞은 뒤의 덱 순서는 아무도 모르는
    것이 규칙이고, 적어 두면 그것을 읽는 쪽이 알게 된다.
    """
    MOVE = "move"
    """
    카드를 다른 존으로 옮긴다. **게임 의미가 없는 저수준 조작이다.**

    파괴도 · 묘지로 보내기도 · 버리기도 · 릴리스도 · 제외도 · 되돌리기도
    **아니다.** 그래서 :data:`REASON_NAMES` 에서 아무 ``REASON_*`` 도
    주장하지 않는다 — 이유를 말할 수 없는 이동이라는 뜻이다.

    실제 카드의 효과는 이것을 쓰지 않는다 (:class:`
    ~engine.effect.library.LibraryEntry` 가 거부한다). 이것은 의미 계층이
    아직 없는 일을 정직하게 옮기기 위한 원시 조작이고, 앞으로 생길
    파괴 · 보내기 계층이 **공유할 바닥**이다.
    """
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
    # 효과로 특수 소환되었다는 사실을 **기존 이유 모델로** 적는다
    # (Phase 2-U §4). ``SpecialSummonReason`` 같은 새 체계를 만들지 않는다.
    OperationKind.SPECIAL_SUMMON: ("SPSUMMON", "EFFECT"),
    OperationKind.DRAW: ("DRAW", "EFFECT"),
    OperationKind.CHANGE_LIFE: ("EFFECT",),
    # 섞기는 카드에 **아무 일도 하지 않는다.** 이유를 주장하지 않는 것이
    # 사실이다 — ``MOVE`` 가 비어 있는 것과 같은 자리.
    OperationKind.SHUFFLE: (),
    # **비어 있는 것이 사실이다.** 이유를 말할 수 없는 이동이므로
    # ``REASON_EFFECT`` 조차 주장하지 않는다. 여기에 이유를 적는 순간
    # 트리거 계층이 이것을 "효과로 묘지에 갔다" 로 읽게 된다.
    OperationKind.MOVE: (),
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

#: **의미를 주장하는** 카드 조작. ``MOVE`` 는 여기 없다 — 목적지만 말하고
#: 무슨 일인지는 말하지 않기 때문이다 (ADR-002).
SEMANTIC_CARD_KINDS: frozenset[OperationKind] = CARD_OPERATION_KINDS

#: **카드의 스크립트가 스스로 선언하는** 관문이 있는 일들 (Phase 2-X).
#:
#: 파괴와 특수 소환의 관문은 *언제나* 적용된다 — 어떤 파괴든 내성에 막힐 수
#: 있고, 어떤 특수 소환이든 소환 조건을 받는다. 그래서 그 둘은
#: ``semantics.RULE_GATED`` 에서 **종류로** 막는다.
#:
#: 묘지로 보내기와 버리기는 다르다. 공식 스크립트가 후보 조건에
#: ``Card.IsAbleToGrave`` · ``Card.IsDiscardable`` 을 **적을 때도 있고 적지
#: 않을 때도 있다** (실측: 12,702개 중 각각 544장 · 537장이 적는다). 적지
#: 않은 카드는 EDOPro 자신도 묻지 않고 보낸다 — 육신보살(15103313)의
#: ``Duel.SelectTarget(tp,nil,...)`` 이 그렇다.
#:
#: 그러므로 이 둘의 관문은 **종류가 아니라 효과가 선언한다.** 선언은
#: :attr:`CardOperation.gated` 한 칸이고, 그 값은 원본 스크립트를 읽어서
#: 정한다 — 추측하지 않는다.
DECLARABLE_GATE_KINDS: frozenset[OperationKind] = frozenset(
    {OperationKind.SEND_TO_GRAVE, OperationKind.DISCARD}
)


#: :class:`MoveOperation` 이 갈 수 있는 곳.
#:
#: 전부 **칸이 없는 순서 존**이다 — 넣을 자리를 고를 필요가 없으므로 계획을
#: 통과한 이동이 적용 중에 거부되지 않는다. 필드는 여기 없다: 칸 선택과
#: 표시 형식은 소환 절차의 일이다.
MOVABLE_DESTINATIONS: frozenset[Zone] = frozenset(
    {Zone.GRAVE, Zone.REMOVED, Zone.HAND, Zone.DECK}
)

#: 섞을 수 있는 존 (Phase 2-Z).
#:
#: 덱과 엑스트라 덱뿐이다. 칸 방식 존은 "몇 번째" 가 칸 번호라서 순서를
#: 바꾸는 것이 카드를 옮기는 일이고, 묘지는 룰북이 **순서를 바꾸지 말라고
#: 말한다** ("The order of the cards in the Graveyard should not be
#: changed."). 패를 섞는 규칙은 따로 있지만 (``Duel.ShuffleHand``) 이번
#: 단계에서 옮기지 않았다 — 없는 것을 있는 척 넣지 않는다.
SHUFFLEABLE_ZONES: frozenset[Zone] = frozenset({Zone.DECK, Zone.EXTRA})


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
    gated: bool = False
    """
    이 일이 **규칙 관문을 받아야 하는가** (Phase 2-X).

    카드의 공식 스크립트가 후보 조건에 ``Card.IsAbleToGrave`` 또는
    ``Card.IsDiscardable`` 을 적었으면 참이다. 적지 않았으면 거짓이고,
    거짓이 기본값이다 — **적지 않은 것을 "관문이 있다" 로 읽지 않는다.**

    :data:`DECLARABLE_GATE_KINDS` 의 일에만 붙일 수 있다. 파괴와 특수
    소환은 선언과 무관하게 언제나 관문을 받으므로 여기 오지 않는다.
    """

    def __post_init__(self) -> None:
        if self.operation not in CARD_OPERATION_KINDS:
            raise ValueError(
                f"{self.operation.value} 는 카드를 다루는 일이 아닙니다."
            )
        if self.gated and self.operation not in DECLARABLE_GATE_KINDS:
            raise ValueError(
                f"{self.operation.value} 의 관문은 효과가 선언하는 것이 "
                "아닙니다. 파괴 · 특수 소환은 언제나 판정을 받고 "
                "(semantics.RULE_GATED), 나머지는 아직 관문이 없습니다 "
                "(STRUCTURAL-48)."
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
    def send_to_grave(
        cls, target_ref: TargetRef, *, gated: bool = False
    ) -> "CardOperation":
        """
        묘지로 보낸다. **파괴가 아니다** — 파괴 내성이 막지 못한다.

        ``gated`` 는 원본 스크립트가 ``Card.IsAbleToGrave`` 를 적었는지에서
        온다. 기본값이 거짓인 이유는 적지 않은 카드가 실제로 있기
        때문이다 (육신보살 15103313).
        """
        return cls(OperationKind.SEND_TO_GRAVE, target_ref, gated=gated)

    @classmethod
    def banish(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.BANISH, target_ref)

    @classmethod
    def release(cls, target_ref: TargetRef) -> "CardOperation":
        return cls(OperationKind.RELEASE, target_ref)

    @classmethod
    def discard(
        cls, target_ref: TargetRef, *, gated: bool = False
    ) -> "CardOperation":
        """
        버린다. ``gated`` 는 원본이 ``Card.IsDiscardable`` 을 적었는지다 —
        ``Card.IsAbleToGrave`` 와 **다른 술어이고 다른 질문**이다
        (c26400609.lua 가 한 줄에서 둘을 함께 묻는다).
        """
        return cls(OperationKind.DISCARD, target_ref, gated=gated)

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
            self.gated,
        )

    def to_dict(self) -> dict:
        data = {
            "kind": "card_operation",
            "operation": self.operation.value,
            "reasons": list(self.reason_names),
            "target_ref": self.target_ref.name,
        }
        if self.gated:
            data["gated"] = True
        return data

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
        gate = " (규칙 판정을 받는다)" if self.gated else ""
        return f"{self.target_ref} 을 {korean}{gate}"


@dataclass(frozen=True, slots=True)
class DrawOperation(Operation):
    """카드를 뽑는다. 뽑지 않는다 — 뽑는다는 **의미**를 담을 뿐이다."""

    count: "int | SelectionCount" = 1
    """
    몇 장 뽑는가. 숫자를 그대로 적으면 고정 수로 읽는다.

    :class:`~engine.effect.target.SelectionCount` 를 적으면 **판에서
    계산되거나 플레이어가 선언한 수**로 뽑는다 (Phase 2-AC · 2-AD).
    실제 카드가 그렇게 한다 — ``local ct=Duel.SendtoDeck(...)`` 뒤의
    ``Duel.Draw(p,ct,...)`` 가 corpus 에 33곳 있다.
    """
    who: PlayerRef = PlayerRef.CONTROLLER

    def __post_init__(self) -> None:
        if not isinstance(self.count, SelectionCount):
            if self.count <= 0:
                raise ValueError(f"드로우 매수는 양수여야 합니다: {self.count}")
            object.__setattr__(self, "count", SelectionCount.fixed(self.count))

    @property
    def kind(self) -> OperationKind:
        return OperationKind.DRAW

    def canonical_state(self) -> tuple:
        return (
            "draw",
            self.count.canonical_state(),
            self.who.value,
            self.reason_names,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "draw",
            "count": self.count.to_dict(),
            "who": self.who.value,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        return f"{self.who} 가 {self.count.describe_ko()} 드로우"


@dataclass(frozen=True, slots=True)
class ShuffleOperation(Operation):
    """
    한 존을 섞는다. **섞지 않는다** — 섞겠다는 의미를 담을 뿐이다.

    대상이 없다. 카드 한 장을 가리키는 일이 아니라 존 전체의 순서를
    다루는 일이므로 ``target_ref`` 칸 자체를 두지 않는다
    (:class:`DrawOperation` 과 같은 이유).
    """

    zone: Zone
    who: PlayerRef = PlayerRef.CONTROLLER

    def __post_init__(self) -> None:
        if self.zone not in SHUFFLEABLE_ZONES:
            raise ValueError(
                f"{self.zone.value} 는 섞을 수 있는 존이 아닙니다. 칸 방식 존은 "
                "순서를 바꾸는 것이 곧 카드를 옮기는 일이라 섞기로 표현할 수 "
                "없고, 순서가 규칙인 존(묘지)도 섞지 않습니다."
            )

    @property
    def kind(self) -> OperationKind:
        return OperationKind.SHUFFLE

    def canonical_state(self) -> tuple:
        return ("shuffle", self.zone.value, self.who.value, self.reason_names)

    def to_dict(self) -> dict:
        return {
            "kind": "shuffle",
            "zone": self.zone.value,
            "who": self.who.value,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        return f"{self.who} 의 {self.zone.value} 를 섞는다"


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
class MoveOperation(Operation):
    """
    카드를 **지정한 존으로** 옮긴다. 그 이상은 말하지 않는다.

    ``CardOperation`` 과 무엇이 다른가
    ----------------------------------
    ============================  =========================================
    ``CardOperation``              **무슨 일인가**를 말한다. 목적지는 그
                                   의미가 정한다 (파괴 → 묘지)
    ``MoveOperation``              **어디로 가는가**만 말한다. 무슨 일인지는
                                   말하지 않는다
    ============================  =========================================

    그래서 이것으로 "파괴한다" 를 흉내 낼 수 없다. 흉내 내면
    :attr:`reason_names` 가 비어 있으므로 트리거 계층이 **아무 사건도 보지
    못한다** — 조용히 틀리는 대신 눈에 보이게 비어 있다.

    갈 수 있는 곳
    -------------
    :data:`MOVABLE_DESTINATIONS` 뿐이다. 필드(``MZONE`` · ``SZONE`` …)로는
    옮기지 않는다 — 칸 선택과 표시 형식이 필요하고, 그것은 소환 절차의
    일이다 (Phase 2-I).
    """

    destination: "Zone"
    target_ref: TargetRef
    to_owner: bool = True
    """
    주인 쪽으로 보내는가. 거짓이면 컨트롤러 쪽이다.

    기본값이 주인인 이유는 갈 수 있는 곳이 전부 소유권 기반 존이기
    때문이다 (묘지 · 제외 · 패 · 덱).
    """

    def __post_init__(self) -> None:
        if not isinstance(self.target_ref, TargetRef):
            raise TypeError(
                "MoveOperation 에는 TargetRef 가 필요합니다. 어느 카드인지 "
                f"말하지 않는 이동은 일이 아닙니다: {self.target_ref!r}"
            )
        if self.destination not in MOVABLE_DESTINATIONS:
            raise ValueError(
                f"{self.destination} 로는 옮길 수 없습니다. 갈 수 있는 곳: "
                + ", ".join(sorted(z.value for z in MOVABLE_DESTINATIONS))
                + " (필드로 보내는 것은 소환 절차의 일입니다)"
            )

    @property
    def kind(self) -> OperationKind:
        return OperationKind.MOVE

    @property
    def target_refs(self) -> tuple[TargetRef, ...]:
        return (self.target_ref,)

    def canonical_state(self) -> tuple:
        return (
            "move",
            self.destination.value,
            self.target_ref.name,
            self.to_owner,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "move",
            "destination": self.destination.value,
            "target_ref": self.target_ref.name,
            "to_owner": self.to_owner,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        whose = "주인" if self.to_owner else "컨트롤러"
        return (
            f"{self.target_ref} 을 {whose} 의 {self.destination.value} 로 "
            "이동 (의미 없음)"
        )


@dataclass(frozen=True, slots=True)
class SpecialSummonOperation(Operation):
    """
    대상으로 고른 몬스터를 **특수 소환한다.**

    ``CardOperation`` 이 아닌 이유
    ------------------------------
    ``CardOperation`` 의 일들은 목적지가 **의미가 정하는 한 자리**이고
    (파괴 → 묘지), 실행기가 ``DESTINATION`` 표를 보고 그대로 옮긴다. 소환은
    그 모양이 아니다 — 칸 번호와 표시 형식이 필요하고, 남기는 변화도
    ``ZoneMoved`` 가 아니라 :class:`~engine.effect.delta.MonsterSummoned` 다.

    그 표에 끼워 넣으면 "몬스터 존으로 옮겼다" 와 "특수 소환되었다" 가 같은
    기록이 되고, "특수 소환되었을 때" 트리거를 영영 구분할 수 없다.

    **어떤 특수 소환법인가는 말하지 않는다.** 융합 · 싱크로 · 엑시즈 · 링크는
    재료를 고르는 절차가 각자 있고, 그 절차가 생길 때 이름을 갖는다
    (STRUCTURAL-62).

    고르는 일은 여기서 하지 않는다
    ------------------------------
    ``target_ref`` 는 **이름**이고, 실제로 어느 카드가 골라졌는지는
    :class:`~engine.effect.resolution.ResolutionContext` 에 있다. 실행기가
    임의로 고르지 않는다 (Phase 2-U §6).
    """

    target_ref: TargetRef

    def __post_init__(self) -> None:
        if not isinstance(self.target_ref, TargetRef):
            raise TypeError(
                "SpecialSummonOperation 에는 TargetRef 가 필요합니다. 어느 "
                f"카드인지 말하지 않는 소환은 일이 아닙니다: {self.target_ref!r}"
            )

    @property
    def kind(self) -> OperationKind:
        return OperationKind.SPECIAL_SUMMON

    @property
    def target_refs(self) -> tuple[TargetRef, ...]:
        return (self.target_ref,)

    def canonical_state(self) -> tuple:
        return ("special_summon", self.target_ref.name)

    def to_dict(self) -> dict:
        return {
            "kind": "special_summon",
            "target_ref": self.target_ref.name,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        return f"{self.target_ref} 를 특수 소환"


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
    "SEMANTIC_CARD_KINDS",
    "DECLARABLE_GATE_KINDS",
    "SHUFFLEABLE_ZONES",
    "ShuffleOperation",
    "MOVABLE_DESTINATIONS",
    "Operation",
    "CardOperation",
    "DrawOperation",
    "LifeChangeOperation",
    "MoveOperation",
    "SpecialSummonOperation",
    "UnimplementedOperation",
]
