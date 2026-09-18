"""
타이밍과 트리거 — **무슨 일이 일어났고, 그 때문에 무엇이 후보가 되는가**.

    GameState 변화 (StateDelta · JournalEvent)
        ↓  TimingEvent.from_delta / from_journal_event
    TimingEvent            무슨 일이 일어났는가
        ↓  TriggerCollector(view, registry, definitions).collect(event)
    TriggerCollection      후보들 + **확인하지 못한 곳**
        ↓  (다음 단계)
    Action → CostPayment → ChainLink

후보 발견과 체인에 넣기를 분리한다
----------------------------------
:class:`TriggerCandidate` 는 **체인에 들어가지 않는다.** 이 계층이 답하는
것은 "이 사건 때문에 무엇이 후보가 될 수 있는가" 뿐이고, 실제 발동은
Action · 비용 · ``ChainLink`` 를 거쳐야 한다. :class:`TriggerCandidate` 가
``ChainLink`` 를 상속하지도, ``Chain`` 안에 들어가지도 않는다.

ELIGIBLE 이 "발동할 수 있다" 가 아니다
--------------------------------------
:attr:`TriggerStatus.ELIGIBLE` 은 **"타이밍이 맞고 조건이 참이다"** 라는
뜻일 뿐이다. 스펠 스피드 · 타이밍 윈도우 · 놓친 타이밍 · 턴 1회 제약 ·
비용 · 발동 합법성은 하나도 보지 않았다. 그것들이 없는 지금 "발동할 수
있다" 고 말하면 거짓이 된다.

모르는 것을 후보에서 지우지 않는다
----------------------------------
상대의 가려진 카드에도 트리거가 있을 수 있다. 관측에 안 보인다고 "후보가
없다" 고 답하면 ``UNKNOWN`` 을 ``FALSE`` 로 접는 것이다. 그래서
:attr:`TriggerCollection.unchecked` 에 **확인하지 못한 곳**을 남긴다 —
없는 것과 못 본 것을 구분한다.

우선권도 체인도 여기서 건드리지 않는다
--------------------------------------
이 모듈은 ``engine.priority`` 와 ``engine.chain`` 을 **import 하지 않는다.**
트리거가 우선권을 돌리지 않고, 우선권이 후보를 만들지 않는다.

순서는 결정론적이지만 규칙 순서가 아니다
----------------------------------------
후보는 :attr:`TriggerCandidate.identity` 순으로 정렬된다. 등록 순서나 set
순회 순서에 의존하지 않기 위해서다. **이것은 SEGOC 도 발동 순서도 아니다** —
그 규칙은 다음 단계의 몫이고, 지금 정렬은 재현성을 위한 것뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import (
    Condition,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
)
from engine.cost import CostValidator
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionSource,
    EffectImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.delta import (
    CardDrawn,
    CardMovement,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    StateDelta,
    ZoneMoved,
)
from engine.effect.journal import CostPaymentEvent, EffectEvent, JournalEvent
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Zone


class TriggerError(ValueError):
    """트리거 선언의 **모양**이 틀렸다. 규칙 위반이 아니다."""


class TimingPoint(str, Enum):
    """
    게임에서 **무엇이 일어난 시점**인가.

    지금 엔진이 실제로 만들어 낼 수 있는 사건만 있다. **전투 · 데미지 스텝은
    아직 없다** — 그 계층이 아예 없어서 어떤 경로로도 생길 수 없는 이름을
    미리 못박으면, 나중에 실제 모양과 어긋난다. 그것들은 각자의 계층과
    함께 들어온다.

    ``MONSTER_SUMMONED`` 와 ``PHASE_CHANGED`` 는 그 규칙대로 **계층이 생긴
    뒤에** 들어왔다 (Phase 2-I · 2-H). 이제 실제로 그 변화를 만들어 내는
    코드가 있고, :meth:`TimingEvent.from_delta` 가 그것을 옮긴다.
    """

    CARD_MOVED = "card_moved"
    """카드가 존을 옮겼다 (``ZoneMoved``). 무슨 의미로 옮겼는지는 ``operation``."""
    CARD_DRAWN = "card_drawn"
    """카드를 뽑았다 (``CardDrawn``). 존 이동이지만 별개의 사건이다."""
    LIFE_CHANGED = "life_changed"
    """라이프가 바뀌었다 (``LifeChanged``)."""
    EFFECT_RESOLVED = "effect_resolved"
    """효과 하나가 해결을 마쳤다 (``EffectEvent``)."""
    COST_PAID = "cost_paid"
    """비용이 치러졌다 (``CostPaymentEvent``). 효과 해결과 다른 사건이다."""
    MONSTER_SUMMONED = "monster_summoned"
    """
    몬스터가 소환되었다 (``MonsterSummoned``).

    ``CARD_MOVED`` 와 **합치지 않는다.** 카드가 패에서 필드로 움직인 것은
    맞지만, "소환되었을 때" 와 "필드로 보내졌을 때" 는 유희왕에서 전혀
    다른 사건이다. 합치면 트리거 계층이 그 둘을 영영 구분할 수 없다
    (ADR-002 가 파괴와 묘지로 보내기를 가른 것과 같은 이유).

    어떤 소환인지는 ``MonsterSummoned.summon`` 이 말한다. 지금 나올 수 있는
    값은 일반 소환뿐이다.
    """
    PHASE_CHANGED = "phase_changed"
    """
    페이즈가 (때로는 턴까지) 바뀌었다 (``PhaseChanged``).

    **"스탠바이 페이즈에" · "엔드 페이즈에" 같은 타이밍 규칙은 여기 없다.**
    사건이 일어났다는 사실만 옮긴다.
    """
    UNIMPLEMENTED = "unimplemented"
    """
    엔진이 아직 만들어 내지 못하는 시점.

    소환 · 표시 형식 변경 · 전투 · 데미지처럼 계층이 없는 것을 **솔직하게**
    표현한다. 지어낸 시점 이름으로 채우지 않는다.
    """

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class TriggerRequirement(str, Enum):
    """
    발동이 강제인가 임의인가. **판정하지 않고 담기만 한다.**

    실제 유희왕의 강제/임의 판정(놓친 타이밍, "할 수 있다" 의 처리)은
    타이밍 윈도우가 있어야 가능하고, 그것이 없는 지금은 카드가 선언한 값을
    그대로 들고 있을 뿐이다.
    """

    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"
    """어느 쪽인지 확인되지 않았다. 임의로 한쪽으로 정하지 않는다."""


class TriggerWording(str, Enum):
    """
    카드 텍스트가 "…한 **때**" 인지 "…한 **경우**" 인지.

    **어휘만 보존한다.** "WHEN 이므로 반드시 놓친다" · "IF 이므로 반드시
    발동 가능" 같은 규칙은 구현하지 않는다 — 타이밍 윈도우가 없으면 그
    판정을 할 근거가 없다.
    """

    WHEN = "when"
    IF = "if"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return {"when": "~한 때", "if": "~한 경우", "unknown": "미확인"}[self.value]


class TriggerStatus(str, Enum):
    """
    후보의 상태.

    :attr:`UNKNOWN` 을 :attr:`INELIGIBLE` 과 **절대 같게 다루지 않는다** —
    "조건이 거짓이다" 와 "판정할 수 없다" 는 다른 답이다.
    """

    ELIGIBLE = "eligible"
    """
    타이밍이 맞고 조건이 참이다.

    **"발동할 수 있다" 가 아니다.** 스펠 스피드 · 타이밍 윈도우 · 놓친
    타이밍 · 턴 1회 제약 · 비용 · 발동 합법성은 하나도 보지 않았다.
    """
    INELIGIBLE = "ineligible"
    """조건이 **확실히** 거짓이다."""
    UNKNOWN = "unknown"
    """판정할 수 없다. 정보가 없거나 규칙이 아직 없다."""
    FORBIDDEN = "forbidden"
    """
    출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004).

    :attr:`INELIGIBLE` 과 합치지 않는다 — "조건이 거짓" 과 "이 근거로는
    절대 실행하지 않는다" 는 전혀 다른 말이다.
    """

    @property
    def is_candidate(self) -> bool:
        """
        후보로 넘길 만한가. **``ELIGIBLE`` 일 때만 참이다.**

        ``if status is not INELIGIBLE:`` 같은 코드로 ``UNKNOWN`` 이나
        ``FORBIDDEN`` 이 허가로 새어 나가는 것을 막는다.
        """
        return self is TriggerStatus.ELIGIBLE

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


# ======================================================================
# 사건
# ======================================================================


@dataclass(frozen=True, slots=True)
class TimingEvent:
    """
    **무슨 일이 일어났는가.** 불변이고, 기존 기록을 그대로 감싼다.

    :class:`~engine.effect.delta.StateDelta` 를 다시 펼쳐 적지 않는다 —
    Delta 가 이미 "어느 카드가 · 어디에서 · 어디로 · 무슨 의미로" 를 들고
    있으므로, 그것을 그대로 참조하고 필요한 값만 꺼내 본다.
    """

    point: TimingPoint
    delta: StateDelta | None = None
    """이 사건을 만든 상태 변화. 효과 해결처럼 변화가 아닌 사건이면 ``None``."""
    effect_ref: EffectRef | None = None
    """``EFFECT_RESOLVED`` · ``COST_PAID`` 에서 어느 효과였는가."""
    actor: int | None = None
    """이 사건을 일으킨 플레이어. 알 수 없으면 ``None``."""
    note: str = ""
    """``UNIMPLEMENTED`` 에서 무엇을 표현할 수 없었는가."""

    def __post_init__(self) -> None:
        if self.actor is not None and self.actor not in (0, 1):
            raise TriggerError(f"actor 는 0 또는 1 입니다: {self.actor}")
        if self.point is TimingPoint.UNIMPLEMENTED and not self.note:
            raise TriggerError(
                "표현할 수 없는 시점에는 무엇을 표현할 수 없었는지 적어야 합니다."
            )

    # --- 생성 --------------------------------------------------------
    @classmethod
    def from_delta(cls, delta: StateDelta) -> "TimingEvent":
        """상태 변화 하나를 사건으로 본다."""
        if isinstance(delta, ZoneMoved):
            return cls(TimingPoint.CARD_MOVED, delta=delta, actor=delta.to_player)
        if isinstance(delta, CardDrawn):
            return cls(TimingPoint.CARD_DRAWN, delta=delta, actor=delta.player)
        if isinstance(delta, LifeChanged):
            return cls(TimingPoint.LIFE_CHANGED, delta=delta, actor=delta.player)
        if isinstance(delta, MonsterSummoned):
            return cls(
                TimingPoint.MONSTER_SUMMONED, delta=delta, actor=delta.player
            )
        if isinstance(delta, PhaseChanged):
            # **일으킨 사람을 적지 않는다.** 페이즈 전이는 규칙이 하는 일이고,
            # 누가 그것을 선언했는가는 우선권 계층의 질문이다. 턴 플레이어를
            # 적어 넣으면 "그 사람이 한 일" 로 읽히게 된다.
            return cls(TimingPoint.PHASE_CHANGED, delta=delta)
        raise TriggerError(
            f"이 변화를 시점으로 옮길 수 없습니다: {type(delta).__name__}. "
            "지어내지 않고 TimingEvent.unimplemented 를 쓰세요."
        )

    @classmethod
    def from_journal_event(cls, event: JournalEvent) -> "TimingEvent":
        """
        기록된 사건 하나를 시점으로 본다. **그 안의 변화는 포함하지 않는다** —
        변화까지 함께 보려면 :func:`timing_events` 를 쓴다.
        """
        if isinstance(event, EffectEvent):
            return cls(
                TimingPoint.EFFECT_RESOLVED,
                effect_ref=event.effect_ref,
                actor=event.actor,
            )
        if isinstance(event, CostPaymentEvent):
            return cls(
                TimingPoint.COST_PAID,
                effect_ref=event.effect_ref,
                actor=event.actor,
            )
        raise TriggerError(
            f"이 사건을 시점으로 옮길 수 없습니다: {type(event).__name__}."
        )

    @classmethod
    def unimplemented(cls, note: str, actor: int | None = None) -> "TimingEvent":
        """
        엔진이 만들어 내지 못하는 시점. 소환 · 전투 · 데미지가 여기다.

        지어낸 시점 이름 대신 **무엇을 표현할 수 없는지 적는다.**
        """
        return cls(TimingPoint.UNIMPLEMENTED, actor=actor, note=note)

    # --- 조회 --------------------------------------------------------
    @property
    def movement(self) -> CardMovement | None:
        """카드가 움직인 사건이면 그 변화. 아니면 ``None``."""
        return self.delta if isinstance(self.delta, CardMovement) else None

    @property
    def instance(self) -> InstanceId | None:
        """
        이 사건이 건드린 카드. 카드가 없는 사건(라이프 · 페이즈)이면 ``None``.

        **이동한 사건만 보지 않는다.** 소환은 ``CardMovement`` 가 아니지만
        (소환은 효과의 어휘를 쓰지 않는다) 분명히 카드 한 장의 사건이다.
        """
        movement = self.movement
        if movement is not None:
            return movement.instance
        found = getattr(self.delta, "instance", None)
        return found if isinstance(found, InstanceId) else None

    @property
    def operation(self) -> OperationKind | None:
        """**무슨 의미로** 움직였는가. 목적지로는 알 수 없다 (ADR-002)."""
        movement = self.movement
        return movement.operation if movement is not None else None

    @property
    def from_zone(self) -> Zone | None:
        movement = self.movement
        return movement.from_zone if movement is not None else None

    @property
    def to_zone(self) -> Zone | None:
        movement = self.movement
        return movement.to_zone if movement is not None else None

    def canonical_state(self) -> tuple:
        return (
            self.point.value,
            self.delta.canonical_state() if self.delta is not None else None,
            (self.effect_ref.card_id, self.effect_ref.ordinal)
            if self.effect_ref is not None
            else None,
            self.actor,
            self.note,
        )

    def to_dict(self) -> dict:
        data: dict = {"point": self.point.value}
        if self.delta is not None:
            data["delta"] = self.delta.to_dict()
        if self.effect_ref is not None:
            data["effect_ref"] = {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            }
        if self.actor is not None:
            data["actor"] = self.actor
        if self.note:
            data["note"] = self.note
        return data

    def describe_ko(self) -> str:
        if self.delta is not None:
            return f"{self.point.value}: {self.delta.describe_ko()}"
        if self.note:
            return f"{self.point.value}: {self.note}"
        return f"{self.point.value}: {self.effect_ref}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def timing_events(event: JournalEvent) -> tuple[TimingEvent, ...]:
    """
    기록된 사건 하나에서 나오는 시점 전부.

    변화(``deltas``)가 먼저고 사건 자체가 나중이다 — 카드는 해결 **중에**
    움직이고, 해결이 끝난 것은 그 뒤다. 이 순서가 규칙이라고 주장하지는
    않는다. 실제 트리거 순서는 다음 단계의 몫이다.
    """
    found = [TimingEvent.from_delta(delta) for delta in event.deltas]
    found.append(TimingEvent.from_journal_event(event))
    return tuple(found)


# ======================================================================
# 선언
# ======================================================================


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    """
    "이 효과는 이런 일이 일어나면 발동 후보가 된다" 는 **선언**.

    카드 데이터에서 자동 생성하지 않는다 (STRUCTURAL-7 · -21 그대로). 손으로
    등록하고, 등록되지 않은 카드는 후보가 나오지 않는다 — 그것이 지금의
    사실이다.

    ``EffectRef(card_id, ordinal)`` 이 identity 다. ``EffectSpec.index``
    (Lua 변수명 ``"e1"``, 한 카드 안에서 중복 — 실측 4,884장) 를 쓰지 않는다.
    """

    effect_ref: EffectRef
    point: TimingPoint
    requirement: TriggerRequirement = TriggerRequirement.UNKNOWN
    wording: TriggerWording = TriggerWording.UNKNOWN
    operations: frozenset[OperationKind] | None = None
    """``CARD_MOVED`` 에서 어떤 의미의 이동에만 반응하는가. ``None`` 이면 전부."""
    from_zones: frozenset[Zone] | None = None
    to_zones: frozenset[Zone] | None = None
    activates_from: frozenset[Zone] | None = None
    """
    **어느 자리에서 발동할 수 있는가.**

    ``None`` 이면 선언하지 않았다는 뜻이고, 그때
    :class:`TriggerEligibilityJudge` 는 자리 관문을 ``UNKNOWN`` 으로 둔다 —
    적지 않은 것을 "어디서든 발동 가능" 으로 읽지 않는다. 덱 맨 밑의
    몬스터와 필드의 몬스터를 같게 다루면 조용히 틀린다.
    """
    condition: Condition | None = None
    """
    타이밍이 맞은 뒤 추가로 만족해야 할 조건.

    ``None`` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는 뜻**이다. 적지
    않은 조건을 참으로 치지 않기 위해, 정의의 ``activation`` 도 함께 본다
    (:class:`TriggerCollector`).
    """

    def __post_init__(self) -> None:
        for name in ("operations", "from_zones", "to_zones", "activates_from"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, frozenset):
                raise TypeError(
                    f"{name} 는 frozenset 이어야 합니다 — 선언은 불변입니다."
                )
        if self.point is not TimingPoint.CARD_MOVED:
            for name in ("operations", "from_zones", "to_zones"):
                if getattr(self, name) is not None:
                    raise TriggerError(
                        f"{self.point.value} 시점에는 {name} 를 걸 수 없습니다. "
                        "카드 이동이 아닌 사건입니다."
                    )

    @property
    def card_id(self) -> int:
        return self.effect_ref.card_id

    def matches(self, event: TimingEvent) -> bool:
        """
        이 선언이 그 사건에 반응하는가. **선언이 적어 둔 것만 본다** —
        규칙 판단이 아니라 데이터 비교다.
        """
        if event.point is not self.point:
            return False
        if self.operations is not None and event.operation not in self.operations:
            return False
        if self.from_zones is not None and event.from_zone not in self.from_zones:
            return False
        if self.to_zones is not None and event.to_zone not in self.to_zones:
            return False
        return True

    def canonical_state(self) -> tuple:
        return (
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.point.value,
            self.requirement.value,
            self.wording.value,
            _sorted_values(self.operations),
            _sorted_values(self.from_zones),
            _sorted_values(self.to_zones),
            _sorted_values(self.activates_from),
            self.condition.canonical_state() if self.condition is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "point": self.point.value,
            "requirement": self.requirement.value,
            "wording": self.wording.value,
        }
        for name in ("operations", "from_zones", "to_zones", "activates_from"):
            value = getattr(self, name)
            if value is not None:
                data[name] = list(_sorted_values(value))
        if self.condition is not None:
            data["condition"] = self.condition.to_dict()
        return data

    def describe_ko(self) -> str:
        return f"{self.effect_ref} @{self.point.value} ({self.wording})"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TriggerRegistry:
    """
    손으로 등록한 트리거 선언들.

    **자동 생성이 아니다.** 카드 데이터에서 트리거를 뽑아내는 컴파일러는
    아직 없고 (STRUCTURAL-7), 만들 때 ``TEXT_DERIVED`` 경계를 다시 확인해야
    한다. 등록되지 않은 카드는 후보가 나오지 않는 것이 지금의 사실이다.
    """

    __slots__ = ("_specs",)

    def __init__(self, specs: "tuple[TriggerSpec, ...] | None" = None):
        self._specs: list[TriggerSpec] = []
        for spec in specs or ():
            self.register(spec)

    def register(self, spec: TriggerSpec) -> "TriggerRegistry":
        if not isinstance(spec, TriggerSpec):
            raise TypeError(f"TriggerSpec 이 필요합니다: {type(spec).__name__}")
        if spec in self._specs:
            raise TriggerError(f"같은 선언이 이미 등록되어 있습니다: {spec}")
        self._specs.append(spec)
        return self

    def watching(self, event: TimingEvent) -> tuple[TriggerSpec, ...]:
        """
        그 사건에 반응하는 선언들.

        정렬은 :meth:`TriggerSpec.canonical_state` 순이다 — 등록 순서에
        의존하지 않기 위해서고, **규칙상의 순서가 아니다.**
        """
        return tuple(
            sorted(
                (spec for spec in self._specs if spec.matches(event)),
                key=lambda spec: spec.canonical_state(),
            )
        )

    @property
    def specs(self) -> tuple[TriggerSpec, ...]:
        return tuple(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TriggerRegistry n={len(self._specs)}>"


# ======================================================================
# 후보
# ======================================================================


@dataclass(frozen=True, slots=True)
class TriggerCandidate:
    """
    "이 사건을 계기로 이 효과가 발동 후보가 될 수 있다."

    **체인에 들어간 것이 아니다.** ``ChainLink`` 를 상속하지 않고, ``Chain``
    이 이것을 직접 받지도 않는다. 사이에 Action 과 비용 지불이 있다.

    ``CardInstance`` 도 ``GameState`` 도 담지 않는다 — 안정적인 식별자만
    담는다.
    """

    point: TimingPoint
    effect_ref: EffectRef
    source: InstanceId
    """이 트리거를 가진 **카드 인스턴스**. 정의가 아니라 판 위의 그 카드다."""
    controller: int
    """지금 그 카드를 쓰는 쪽. 발동 주체가 될 사람이다."""
    status: TriggerStatus = TriggerStatus.UNKNOWN
    """
    **수집 단계까지 알아낸 것**. 타이밍과 조건만 본 값이다.

    발동 가능성 전체는 :class:`TriggerEligibility` 가 답한다 — 자리 · 실행
    권위 · 비용까지 합친 결과는 이 값과 **다를 수 있다.** 여기만 보고
    "발동할 수 있다" 고 읽지 않는다.
    """
    requirement: TriggerRequirement = TriggerRequirement.UNKNOWN
    wording: TriggerWording = TriggerWording.UNKNOWN
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    notes: tuple[str, ...] = ()
    """왜 판정할 수 없었는가 등, 조건 계층이 남긴 설명."""

    def __post_init__(self) -> None:
        if self.controller not in (0, 1):
            raise TriggerError(f"controller 는 0 또는 1 입니다: {self.controller}")
        if not isinstance(self.notes, tuple):
            raise TypeError("notes 는 tuple 이어야 합니다 — 후보는 불변입니다.")

    @property
    def identity(self) -> tuple:
        """
        후보를 가리키는 **안정적인 식별자.**

        무작위도 주소도 시각도 쓰지 않는다. 같은 판 · 같은 사건이면 같은
        값이고, 정렬 기준으로도 쓴다.
        """
        return (
            self.point.value,
            self.effect_ref.card_id,
            self.effect_ref.ordinal,
            self.source.value,
            self.controller,
        )

    @property
    def key(self) -> str:
        """사람이 읽는 식별자. 로그와 비교용이다."""
        return (
            f"{self.point.value}:{self.effect_ref.card_id}"
            f":{self.effect_ref.ordinal}:#{self.source.value}:P{self.controller}"
        )

    @property
    def is_candidate(self) -> bool:
        """``ELIGIBLE`` 일 때만 참. **발동 가능하다는 뜻이 아니다.**"""
        return self.status.is_candidate

    def canonical_state(self) -> tuple:
        return (
            self.identity,
            self.status.value,
            self.requirement.value,
            self.wording.value,
            self.code.value,
            self.reason,
            self.notes,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "point": self.point.value,
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "source": self.source.value,
            "controller": self.controller,
            "status": self.status.value,
            "requirement": self.requirement.value,
            "wording": self.wording.value,
            "code": self.code.value,
        }
        if self.reason:
            data["reason"] = self.reason
        if self.notes:
            data["notes"] = list(self.notes)
        return data

    def describe_ko(self) -> str:
        return f"{self.key} → {self.status.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TriggerCollection:
    """
    사건 하나에서 모은 후보들과 **확인하지 못한 곳**.

    :attr:`unchecked` 가 있어서 "후보가 없다" 와 "볼 수 없어서 모른다" 가
    구분된다. 가려진 존을 조용히 건너뛰고 빈 목록을 돌려주면 ``UNKNOWN`` 을
    ``FALSE`` 로 접는 것이다.
    """

    event: TimingEvent
    candidates: tuple[TriggerCandidate, ...] = ()
    unchecked: tuple[str, ...] = ()
    """볼 수 없어서 트리거가 있는지 확인하지 못한 곳들."""

    def __post_init__(self) -> None:
        for name in ("candidates", "unchecked"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 결과는 불변입니다.")

    def with_status(self, status: TriggerStatus) -> tuple[TriggerCandidate, ...]:
        return tuple(c for c in self.candidates if c.status is status)

    @property
    def eligible(self) -> tuple[TriggerCandidate, ...]:
        """조건이 참인 후보들. **발동 가능한 것들이 아니다.**"""
        return self.with_status(TriggerStatus.ELIGIBLE)

    @property
    def undecided(self) -> tuple[TriggerCandidate, ...]:
        return self.with_status(TriggerStatus.UNKNOWN)

    @property
    def ineligible(self) -> tuple[TriggerCandidate, ...]:
        return self.with_status(TriggerStatus.INELIGIBLE)

    @property
    def forbidden(self) -> tuple[TriggerCandidate, ...]:
        return self.with_status(TriggerStatus.FORBIDDEN)

    @property
    def fully_checked(self) -> bool:
        """
        **전부 확인했는가.** 거짓이면 이 목록이 완전하다고 말할 수 없다.
        """
        return not self.unchecked

    def __len__(self) -> int:
        return len(self.candidates)

    def __iter__(self):
        return iter(self.candidates)

    def canonical_state(self) -> tuple:
        return (
            self.event.canonical_state(),
            tuple(c.canonical_state() for c in self.candidates),
            self.unchecked,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "event": self.event.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.unchecked:
            data["unchecked"] = list(self.unchecked)
        return data

    def describe_ko(self) -> str:
        missing = f", 확인 못 함 {len(self.unchecked)}곳" if self.unchecked else ""
        return (
            f"{self.event.point.value}: 후보 {len(self.candidates)}개 "
            f"(조건 참 {len(self.eligible)}){missing}"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TriggerCollector:
    """
    사건 하나에 대해 후보를 모은다. **판을 바꾸지 않는다** — 애초에 바꿀 수
    있는 것을 들고 있지 않다 (:class:`~engine.game_state_view.GameStateView`
    는 스냅숏이다).

    조건 판정은 :class:`~engine.condition.ConditionEvaluator` 를 그대로
    쓴다. 새 조건 엔진을 만들지 않는다.
    """

    __slots__ = ("_view", "_registry", "_definitions", "_evaluator")

    def __init__(
        self,
        view: GameStateView,
        registry: TriggerRegistry,
        definitions: EffectDefinitionSource | None = None,
    ):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "TriggerCollector 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 후보 수집이 판을 바꿀 수 있게 됩니다."
            )
        if not isinstance(registry, TriggerRegistry):
            raise TypeError(f"TriggerRegistry 가 필요합니다: {type(registry).__name__}")
        if definitions is not None and not hasattr(definitions, "definition_for"):
            raise TypeError("정의를 찾을 수 있는 것이 필요합니다 (definition_for).")
        self._view = view
        self._registry = registry
        self._definitions = definitions
        self._evaluator = ConditionEvaluator(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def registry(self) -> TriggerRegistry:
        return self._registry

    # ------------------------------------------------------------------
    def collect(self, event: TimingEvent) -> TriggerCollection:
        """
        그 사건 때문에 후보가 되는 것들.

        순서는 :attr:`TriggerCandidate.identity` 순으로 **결정론적**이지만
        **규칙상의 발동 순서가 아니다** (SEGOC 는 다음 단계다).
        """
        if not isinstance(event, TimingEvent):
            raise TypeError(f"TimingEvent 가 필요합니다: {type(event).__name__}")

        specs = self._registry.watching(event)
        candidates: list[TriggerCandidate] = []
        for spec in specs:
            candidates.extend(self._candidates_for(spec, event))
        candidates.sort(key=lambda candidate: candidate.identity)
        return TriggerCollection(
            event=event,
            candidates=tuple(candidates),
            unchecked=self._unchecked() if specs else (),
        )

    def collect_all(self, events) -> tuple[TriggerCollection, ...]:
        """
        사건 여럿을 차례로 본다. **합치지 않는다** — 어느 사건에서 나온
        후보인지가 사라지면 나중에 순서를 정할 근거가 없어진다.
        """
        return tuple(self.collect(event) for event in events)

    # ------------------------------------------------------------------
    def _candidates_for(self, spec: TriggerSpec, event: TimingEvent):
        """선언 하나에 대해, 그 카드가 놓인 자리마다 후보를 만든다."""
        definition = (
            self._definitions.definition_for(spec.effect_ref)
            if self._definitions is not None
            else None
        )
        for card in self._visible_copies(spec.card_id):
            yield self._judge(spec, event, card, definition)

    def _visible_copies(self, card_id: int):
        """
        관측에서 그 카드의 **보이는** 사본들.

        가려진 카드는 ``card_id`` 가 ``None`` 이라 여기 걸리지 않는다. 그
        사실은 :meth:`_unchecked` 가 따로 남긴다 — 조용히 빠뜨리지 않는다.
        """
        for player in self._view.players:
            for zone in player.zones:
                for card in zone.cards:
                    if card is None or card.card_id != card_id:
                        continue
                    if card.instance_id is None:  # pragma: no cover - 방어용
                        continue
                    yield card

    def _unchecked(self) -> tuple[str, ...]:
        """
        **볼 수 없어서 확인하지 못한 곳들.**

        상대의 패 · 덱 · 뒷면 카드에도 트리거가 있을 수 있다. 관측에 없다고
        "후보가 없다" 고 답하면 모르는 것을 거짓으로 접는 것이다.
        """
        missing: list[str] = []
        for player in self._view.players:
            for zone in player.zones:
                if zone.concealed and zone.size:
                    missing.append(
                        f"P{player.player_id} {zone.zone.value} {zone.size}장"
                    )
                    continue
                for card in zone.cards:
                    if card is not None and card.card_id is None:
                        missing.append(
                            f"P{player.player_id} {zone.zone.value} "
                            f"#{card.instance_id.value} 뒷면"
                        )
        return tuple(sorted(missing))

    def _judge(
        self,
        spec: TriggerSpec,
        event: TimingEvent,
        card,
        definition: EffectDefinition | None,
    ) -> TriggerCandidate:
        """이 자리의 이 카드가 후보인가. **관측만 읽는다.**"""
        base = {
            "point": event.point,
            "effect_ref": spec.effect_ref,
            "source": card.instance_id,
            "controller": card.controller,
            "requirement": spec.requirement,
            "wording": spec.wording,
        }

        # 출처 금지가 가장 먼저다 (ADR-004). 조건이 참이어도 실행하지 않는다.
        if definition is not None and definition.provenance.is_forbidden:
            return TriggerCandidate(
                **base,
                status=TriggerStatus.FORBIDDEN,
                code=ValidationCode.RULE_NOT_IMPLEMENTED,
                reason="공식 텍스트에서 유추한 효과는 실행하지 않습니다 (ADR-004).",
            )

        conditions = [
            condition
            for condition in (
                spec.condition,
                definition.activation if definition is not None else None,
            )
            if condition is not None
        ]
        if not conditions:
            missing_definition = self._definitions is not None and definition is None
            if missing_definition:
                return TriggerCandidate(
                    **base,
                    status=TriggerStatus.UNKNOWN,
                    code=ValidationCode.RULE_NOT_IMPLEMENTED,
                    reason=f"{spec.effect_ref} 의 정의가 등록되어 있지 않아 "
                    "조건을 확인할 수 없습니다.",
                    notes=("정의 미등록",),
                )
            return TriggerCandidate(
                **base,
                status=TriggerStatus.ELIGIBLE,
                code=ValidationCode.OK,
                reason="타이밍이 맞고 걸린 조건이 없습니다. 발동 합법성은 "
                "따로 판정해야 합니다.",
            )

        context = ConditionContext(
            player=card.controller,
            source=card.instance_id,
            effect_ref=spec.effect_ref,
        )
        verdicts = [
            self._evaluator.evaluate(condition, context) for condition in conditions
        ]
        combined = ConditionResult.all_of(verdict.result for verdict in verdicts)
        notes = tuple(
            reason for verdict in verdicts for reason in verdict.unknown_reasons
        )
        described = " 그리고 ".join(verdict.description for verdict in verdicts)

        if combined is ConditionResult.TRUE:
            return TriggerCandidate(
                **base,
                status=TriggerStatus.ELIGIBLE,
                code=ValidationCode.OK,
                reason=f"조건이 참입니다: {described}. 발동 합법성은 따로 "
                "판정해야 합니다.",
            )
        if combined is ConditionResult.FALSE:
            return TriggerCandidate(
                **base,
                status=TriggerStatus.INELIGIBLE,
                code=ValidationCode.RULE_NOT_IMPLEMENTED,
                reason=f"조건이 거짓입니다: {described}",
            )
        return TriggerCandidate(
            **base,
            status=TriggerStatus.UNKNOWN,
            code=ValidationCode.INFORMATION_UNAVAILABLE,
            reason=f"조건을 판정할 수 없습니다: {described}",
            notes=notes,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TriggerCollector {self._registry!r}>"


# ======================================================================
# 발동 가능성 — 관문을 **따로** 두고 합친다
# ======================================================================


class EligibilityGate(str, Enum):
    """
    발동 가능성을 가르는 **관문 하나**.

    관문을 이름별로 나눠 두는 이유는 하나다 — 앞으로 규칙이 들어올 때
    기존 판정을 다시 쓰지 않고 **관문만 추가**하면 되게 하려는 것이다.
    하나의 불리언으로 뭉개면 "무엇 때문에 안 되는가" 가 사라진다.
    """

    EVENT_RELATION = "event_relation"
    """이 트리거가 그 사건에 반응하는가 (:meth:`TriggerSpec.matches`)."""
    ACTIVATION_ZONE = "activation_zone"
    """지금 있는 자리에서 발동할 수 있는가."""
    TRIGGER_CONDITION = "trigger_condition"
    """선언된 조건과 정의의 발동 조건이 참인가."""
    EXECUTION_AUTHORITY = "execution_authority"
    """출처와 등록된 구현이 실행을 허용하는가 (ADR-004 · ADR-006)."""
    COST_FEASIBILITY = "cost_feasibility"
    """비용을 **치를 수 있는가.** 치르지는 않는다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: **아직 아무 관문도 보지 않는 규칙들.**
#:
#: 이것이 목록으로 남아 있는 것이 이 단계의 정직한 상태다.
#: :attr:`TriggerEligibility.unchecked_rules` 가 이 목록을 그대로 실어
#: 나르므로, ``ELIGIBLE`` 을 받은 쪽도 "무엇을 아직 안 봤는가" 를 알 수 있다.
UNCHECKED_RULES: tuple[str, ...] = (
    "timing window (놓친 타이밍 · 열린 타이밍)",
    "WHEN/IF 처리 규칙",
    "spell speed",
    "activation limit (턴 1회 · 카드명 제약)",
    "SEGOC 및 동시 트리거 순서",
    "chain 삽입 가능성 및 체인 상한",
)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """
    관문 하나의 판정. :class:`~engine.validation.ValidationResult` 를 그대로
    싣는다 — 새 판정 어휘를 만들지 않는다.
    """

    gate: EligibilityGate
    result: ValidationResult

    @property
    def validity(self) -> ActionValidity:
        return self.result.validity

    @property
    def code(self) -> ValidationCode:
        return self.result.code

    @property
    def passed(self) -> bool:
        """**``VALID`` 일 때만 참.** ``UNKNOWN`` 이 통과로 새지 않는다."""
        return self.result.validity is ActionValidity.VALID

    @property
    def forbids(self) -> bool:
        """출처가 실행을 금지했는가. 판이 바뀌어도 달라지지 않는 거부다."""
        return self.result.code is ValidationCode.EXECUTION_FORBIDDEN

    def canonical_state(self) -> tuple:
        return (self.gate.value, self.result.canonical_state())

    def to_dict(self) -> dict:
        return {"gate": self.gate.value, **self.result.to_dict()}

    def describe_ko(self) -> str:
        return f"{self.gate.value}: {self.result.validity.value} — {self.result.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TriggerEligibility:
    """
    후보 하나의 **발동 가능성 판정**. 관문별 결과를 그대로 들고 있다.

    :attr:`status` 는 :attr:`TriggerCandidate.status` 와 **다를 수 있다.**
    저쪽은 타이밍과 조건까지만 본 값이고, 이쪽은 자리 · 실행 권위 · 비용을
    합친 값이다. 둘을 한 곳에 뭉개지 않는 이유는 "수집 단계에서 알 수 있던
    것" 과 "지금 발동할 수 있는가" 가 다른 질문이기 때문이다.

    ``ELIGIBLE`` 이어도 **완전한 발동 가능성이 아니다.**
    :attr:`unchecked_rules` 에 아직 보지 않은 규칙이 남아 있다.
    """

    candidate: TriggerCandidate
    status: TriggerStatus
    gates: tuple[GateVerdict, ...] = ()
    unchecked_rules: tuple[str, ...] = UNCHECKED_RULES

    def __post_init__(self) -> None:
        for name in ("gates", "unchecked_rules"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 판정은 불변입니다.")
        seen: list[EligibilityGate] = []
        for verdict in self.gates:
            if verdict.gate in seen:
                raise TriggerError(f"관문 {verdict.gate.value} 이 두 번 들어왔습니다.")
            seen.append(verdict.gate)

    # ------------------------------------------------------------------
    @classmethod
    def fold(
        cls, candidate: TriggerCandidate, gates: "tuple[GateVerdict, ...]"
    ) -> "TriggerEligibility":
        """
        관문 결과들을 하나의 상태로 접는다. **순서가 곧 원칙이다.**

        1. 출처 금지가 하나라도 있으면 ``FORBIDDEN`` — 다른 관문이 전부
           통과해도 실행하지 않는다 (ADR-004).
        2. 확실한 거부가 있으면 ``INELIGIBLE``.
        3. 판정 불가가 있으면 ``UNKNOWN`` — **거부보다 약하고 통과보다
           약하다.** 모르는 것을 거짓으로도 참으로도 접지 않는다.
        4. 전부 통과하면 ``ELIGIBLE``.
        """
        if any(verdict.forbids for verdict in gates):
            status = TriggerStatus.FORBIDDEN
        elif any(verdict.validity is ActionValidity.INVALID for verdict in gates):
            status = TriggerStatus.INELIGIBLE
        elif any(verdict.validity is ActionValidity.UNKNOWN for verdict in gates):
            status = TriggerStatus.UNKNOWN
        else:
            status = TriggerStatus.ELIGIBLE
        return cls(candidate=candidate, status=status, gates=gates)

    # ------------------------------------------------------------------
    @property
    def may_activate(self) -> bool:
        """
        ``ELIGIBLE`` 일 때만 참.

        **"규칙상 발동할 수 있다" 는 뜻이 아니다** —
        :attr:`unchecked_rules` 가 비어 있지 않은 동안은 언제나 "지금까지
        본 관문을 전부 통과했다" 까지만 뜻한다.
        """
        return self.status.is_candidate

    @property
    def fully_checked(self) -> bool:
        """
        모든 규칙을 본 판정인가. **지금은 언제나 거짓이다** — 그것이 이
        단계의 사실이고, 참이 되는 날 타이밍 계층이 완성된 것이다.
        """
        return not self.unchecked_rules

    @property
    def blocking(self) -> tuple[GateVerdict, ...]:
        """통과하지 못한 관문들. 순서는 검사 순서 그대로다."""
        return tuple(verdict for verdict in self.gates if not verdict.passed)

    @property
    def requirement(self) -> TriggerRequirement:
        """강제/임의. **판정에 쓰이지 않고 그대로 실려 나간다** (SEGOC 용)."""
        return self.candidate.requirement

    @property
    def wording(self) -> TriggerWording:
        """"때"/"경우". 어휘만 보존한다."""
        return self.candidate.wording

    def gate(self, gate: EligibilityGate) -> GateVerdict | None:
        for verdict in self.gates:
            if verdict.gate is gate:
                return verdict
        return None

    def canonical_state(self) -> tuple:
        return (
            self.candidate.canonical_state(),
            self.status.value,
            tuple(verdict.canonical_state() for verdict in self.gates),
            self.unchecked_rules,
        )

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate.to_dict(),
            "status": self.status.value,
            "gates": [verdict.to_dict() for verdict in self.gates],
            "unchecked_rules": list(self.unchecked_rules),
        }

    def describe_ko(self) -> str:
        blocked = ", ".join(v.gate.value for v in self.blocking) or "없음"
        return (
            f"{self.candidate.key} → {self.status.value} "
            f"(막힌 관문: {blocked}, 미검사 규칙 {len(self.unchecked_rules)}개)"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TriggerEligibilityJudge:
    """
    후보 하나가 지금 발동 가능한가를 **관문별로** 판정한다.

    **판을 바꾸지 않는다.** 관측과 조건 평가기, 그리고 기존 비용 검증기만
    쓴다 — 비용을 *치르지* 않고 *치를 수 있는지*만 본다
    (:class:`~engine.cost.CostValidator`, Phase 2-C).

    체인에 넣지도 않는다. ``Chain.push`` 를 부르지 않고 ``engine.chain`` 을
    import 하지도 않는다.
    """

    __slots__ = ("_view", "_definitions", "_implementations", "_evaluator", "_costs")

    def __init__(
        self,
        view: GameStateView,
        definitions: EffectDefinitionSource | None = None,
        implementations: EffectImplementationLookup | None = None,
    ):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "TriggerEligibilityJudge 는 GameStateView 만 받습니다. "
                "GameState 를 직접 넘기면 판정이 판을 바꿀 수 있게 됩니다."
            )
        if definitions is not None and not hasattr(definitions, "definition_for"):
            raise TypeError("정의를 찾을 수 있는 것이 필요합니다 (definition_for).")
        if implementations is not None and not hasattr(
            implementations, "has_implementation"
        ):
            raise TypeError("구현을 찾을 수 있는 것이 필요합니다 (has_implementation).")
        self._view = view
        self._definitions = definitions
        self._implementations = implementations
        self._evaluator = ConditionEvaluator(view)
        self._costs = CostValidator(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    # ------------------------------------------------------------------
    def judge(
        self, candidate: TriggerCandidate, spec: TriggerSpec, event: TimingEvent
    ) -> TriggerEligibility:
        """
        관문을 순서대로 통과시켜 본다. **하나가 막혀도 나머지를 계속 본다** —
        무엇이 막혔는지 전부 알아야 다음 단계가 판단할 수 있다.
        """
        if candidate.effect_ref != spec.effect_ref:
            raise TriggerError(
                f"후보({candidate.effect_ref})와 선언({spec.effect_ref})이 "
                "다른 효과를 가리킵니다."
            )
        definition = (
            self._definitions.definition_for(spec.effect_ref)
            if self._definitions is not None
            else None
        )
        gates = (
            self._event_relation(spec, event),
            self._activation_zone(candidate, spec),
            self._trigger_condition(candidate, spec, definition),
            self._execution_authority(spec, definition),
            self._cost_feasibility(candidate, definition),
        )
        return TriggerEligibility.fold(candidate, gates)

    def judge_all(
        self, collection: TriggerCollection, registry: TriggerRegistry
    ) -> tuple[TriggerEligibility, ...]:
        """
        수집 결과 전체를 판정한다. 순서는 후보 순서(= ``identity`` 순) 그대로고,
        **규칙상의 발동 순서가 아니다** (SEGOC 는 이 단계에 없다).
        """
        specs = {spec.effect_ref: spec for spec in registry.watching(collection.event)}
        judged: list[TriggerEligibility] = []
        for candidate in collection.candidates:
            spec = specs.get(candidate.effect_ref)
            if spec is None:  # pragma: no cover - 같은 사건이면 일어나지 않는다
                raise TriggerError(
                    f"{candidate.effect_ref} 의 선언을 이 사건에서 찾을 수 "
                    "없습니다. 후보와 등록소가 어긋났습니다."
                )
            judged.append(self.judge(candidate, spec, collection.event))
        return tuple(judged)

    # ------------------------------------------------------------------
    # 관문들
    # ------------------------------------------------------------------
    def _event_relation(self, spec: TriggerSpec, event: TimingEvent) -> GateVerdict:
        """이 사건에 반응하는가. 선언이 적어 둔 것만 본다."""
        if spec.matches(event):
            return _gate(
                EligibilityGate.EVENT_RELATION,
                ActionValidity.VALID,
                ValidationCode.OK,
                f"{event.point.value} 사건에 반응하는 선언입니다.",
            )
        return _gate(
            EligibilityGate.EVENT_RELATION,
            ActionValidity.INVALID,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"이 선언은 {event.point.value} 사건에 반응하지 않습니다.",
        )

    def _activation_zone(
        self, candidate: TriggerCandidate, spec: TriggerSpec
    ) -> GateVerdict:
        """
        지금 있는 자리에서 발동할 수 있는가.

        선언하지 않았으면 ``UNKNOWN`` 이다 — **적지 않은 것을 "어디서든
        발동 가능" 으로 읽지 않는다.**
        """
        if spec.activates_from is None:
            return _gate(
                EligibilityGate.ACTIVATION_ZONE,
                ActionValidity.UNKNOWN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "발동할 수 있는 자리가 선언되지 않았습니다.",
                notes=("activates_from 미선언",),
            )
        card = self._view.find(candidate.source)
        if card is None:
            return _gate(
                EligibilityGate.ACTIVATION_ZONE,
                ActionValidity.UNKNOWN,
                ValidationCode.HIDDEN_CARD,
                f"{candidate.source} 가 관측에 보이지 않아 자리를 확인할 수 "
                "없습니다.",
            )
        if card.zone in spec.activates_from:
            return _gate(
                EligibilityGate.ACTIVATION_ZONE,
                ActionValidity.VALID,
                ValidationCode.OK,
                f"{card.zone.value} 에서 발동할 수 있습니다.",
            )
        return _gate(
            EligibilityGate.ACTIVATION_ZONE,
            ActionValidity.INVALID,
            ValidationCode.SOURCE_WRONG_ZONE,
            f"{card.zone.value} 는 발동할 수 있는 자리가 아닙니다 "
            f"({'/'.join(sorted(z.value for z in spec.activates_from))}).",
        )

    def _trigger_condition(
        self,
        candidate: TriggerCandidate,
        spec: TriggerSpec,
        definition: EffectDefinition | None,
    ) -> GateVerdict:
        """
        선언된 조건과 정의의 발동 조건. 기존 평가기를 그대로 쓴다.

        **조건(trigger condition)과 사건 관계(event relation)를 따로 둔다** —
        "무엇이 일어났을 때" 와 "그때 무엇이 참이어야 하는가" 는 다른
        질문이고, WHEN/IF 규칙이 들어올 때 나뉜 자리가 필요하다.
        """
        conditions = [
            condition
            for condition in (
                spec.condition,
                definition.activation if definition is not None else None,
            )
            if condition is not None
        ]
        if not conditions:
            if self._definitions is not None and definition is None:
                return _gate(
                    EligibilityGate.TRIGGER_CONDITION,
                    ActionValidity.UNKNOWN,
                    ValidationCode.RULE_NOT_IMPLEMENTED,
                    f"{spec.effect_ref} 의 정의가 없어 조건을 확인할 수 없습니다.",
                    notes=("정의 미등록",),
                )
            return _gate(
                EligibilityGate.TRIGGER_CONDITION,
                ActionValidity.VALID,
                ValidationCode.OK,
                "걸린 조건이 없습니다.",
            )
        context = ConditionContext(
            player=candidate.controller,
            source=candidate.source,
            effect_ref=spec.effect_ref,
        )
        verdicts = [
            self._evaluator.evaluate(condition, context) for condition in conditions
        ]
        combined = ConditionResult.all_of(verdict.result for verdict in verdicts)
        described = " 그리고 ".join(verdict.description for verdict in verdicts)
        if combined is ConditionResult.TRUE:
            return _gate(
                EligibilityGate.TRIGGER_CONDITION,
                ActionValidity.VALID,
                ValidationCode.OK,
                f"조건이 참입니다: {described}",
            )
        if combined is ConditionResult.FALSE:
            return _gate(
                EligibilityGate.TRIGGER_CONDITION,
                ActionValidity.INVALID,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"조건이 거짓입니다: {described}",
            )
        return _gate(
            EligibilityGate.TRIGGER_CONDITION,
            ActionValidity.UNKNOWN,
            ValidationCode.INFORMATION_UNAVAILABLE,
            f"조건을 판정할 수 없습니다: {described}",
            notes=tuple(
                reason for verdict in verdicts for reason in verdict.unknown_reasons
            ),
        )

    def _execution_authority(
        self, spec: TriggerSpec, definition: EffectDefinition | None
    ) -> GateVerdict:
        """
        출처와 구현이 실행을 허용하는가. :func:`execution_availability` 를
        그대로 쓴다 — 판정 순서(출처 금지가 가장 먼저)까지 재사용한다.
        """
        if definition is None:
            return _gate(
                EligibilityGate.EXECUTION_AUTHORITY,
                ActionValidity.UNKNOWN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{spec.effect_ref} 의 정의가 없어 실행 권위를 확인할 수 "
                "없습니다.",
                notes=("정의 미등록",),
            )
        availability = execution_availability(definition, self._implementations)
        if availability is ExecutionAvailability.EXECUTABLE:
            return _gate(
                EligibilityGate.EXECUTION_AUTHORITY,
                ActionValidity.VALID,
                ValidationCode.OK,
                "출처가 허용하고 구현이 등록되어 있습니다.",
            )
        if availability is ExecutionAvailability.FORBIDDEN_SOURCE:
            return _gate(
                EligibilityGate.EXECUTION_AUTHORITY,
                ActionValidity.INVALID,
                ValidationCode.EXECUTION_FORBIDDEN,
                "공식 텍스트에서 유추한 효과는 실행하지 않습니다 (ADR-004).",
            )
        return _gate(
            EligibilityGate.EXECUTION_AUTHORITY,
            ActionValidity.UNKNOWN,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"실행할 수 있는지 확인되지 않았습니다: {availability.value}.",
            notes=(availability.value,),
        )

    def _cost_feasibility(
        self, candidate: TriggerCandidate, definition: EffectDefinition | None
    ) -> GateVerdict:
        """
        비용을 **치를 수 있는가.** 치르지 않는다 — 지불은
        :class:`~engine.payment.CostPayer` 의 일이고 이 계층은 그것을
        부르지도, import 하지도 않는다.
        """
        if definition is None:
            return _gate(
                EligibilityGate.COST_FEASIBILITY,
                ActionValidity.UNKNOWN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "정의가 없어 비용을 확인할 수 없습니다.",
                notes=("정의 미등록",),
            )
        if definition.cost.is_free:
            return _gate(
                EligibilityGate.COST_FEASIBILITY,
                ActionValidity.VALID,
                ValidationCode.OK,
                "치를 비용이 없습니다.",
            )
        context = ConditionContext(
            player=candidate.controller,
            source=candidate.source,
            effect_ref=candidate.effect_ref,
        )
        result = self._costs.validate_group(definition.cost, context)
        return GateVerdict(EligibilityGate.COST_FEASIBILITY, result)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TriggerEligibilityJudge {self._view}>"


def _gate(
    gate: EligibilityGate,
    validity: ActionValidity,
    code: ValidationCode,
    reason: str,
    notes: tuple[str, ...] = (),
) -> GateVerdict:
    return GateVerdict(
        gate, ValidationResult(validity, code, reason, notes=notes)
    )


def _sorted_values(values) -> tuple:
    """열거형 묶음을 **정렬된 값 튜플**로. set 순회 순서에 의존하지 않는다."""
    if values is None:
        return ()
    return tuple(sorted(value.value for value in values))


__all__ = [
    "TriggerError",
    "TimingPoint",
    "TriggerRequirement",
    "TriggerWording",
    "TriggerStatus",
    "TimingEvent",
    "timing_events",
    "TriggerSpec",
    "TriggerRegistry",
    "TriggerCandidate",
    "TriggerCollection",
    "TriggerCollector",
    "EligibilityGate",
    "GateVerdict",
    "TriggerEligibility",
    "TriggerEligibilityJudge",
    "UNCHECKED_RULES",
]
