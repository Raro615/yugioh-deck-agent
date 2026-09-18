"""
상태 변화를 **관찰 가능한 사건**으로 옮기는 자리.

    GameState mutation            ← 실행기가 이미 끝냈다
        ↓  StateDelta             무엇이 달라졌는가
        ↓  EventReader            ← 이 파일
    ObservedEvent                 언제 · 누가 · 무슨 사건이었는가
        ↓  TriggerCollector       (Phase 2-F-3-A, 그대로 쓴다)
    TriggerCollection             이 사건을 계기로 후보가 되는 것들

Delta 와 사건은 다르다
----------------------
``StateDelta`` 는 **판이 어떻게 달라졌는가**이고, 사건은 **그 변화가 게임
규칙상 관찰 가능한 일이 되었는가**이다. 둘을 한 객체로 만들면 "아직 아무도
보지 않은 변화" 와 "관찰된 사건" 이 구분되지 않는다.

그래서 :class:`ObservedEvent` 는 Delta 를 **다시 적지 않고** 감싼다 —
:class:`~engine.trigger.TimingEvent` 가 이미 Delta 를 들고 있으므로, 여기서
더하는 것은 **언제 일어났는가**(:class:`EventContext`) 하나뿐이다.

무엇을 하지 않는가
------------------
- 체인을 만들지 않는다.
- 효과를 실행하지 않는다.
- 판을 바꾸지 않는다 — :class:`~engine.game_state_view.GameStateView` 만
  들고 있어서 **바꿀 수 있는 것을 애초에 갖고 있지 않다.**
- 새 수집기 · 새 조건 엔진 · 새 정렬기를 만들지 않는다. Phase 2-F-3-A~D 와
  2-F-4 의 것을 그대로 부른다.
- EventBus 도, 구독 · 발행 프레임워크도 만들지 않는다. 부르는 쪽이 읽고
  넘기는 것이 전부다.

누가 부르는가
-------------
실행기(``ActionExecutor`` · ``TurnProgressor``)는 이 파일을 **모른다.**
상태를 바꾸는 일과 사건을 관찰하는 일이 한 함수에 있으면, 관찰을 끄거나
관찰자를 바꿀 방법이 없어진다. 실행이 끝난 뒤 그 결과를 여기에 넘기는 것은
바깥쪽의 일이다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from engine.effect.delta import StateDelta
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollection,
    TriggerCollector,
    TriggerError,
    TriggerRegistry,
)
from engine.vocabulary import Phase


class EventPipelineError(RuntimeError):
    """사건으로 옮길 수 없는 것을 받았다."""


@dataclass(frozen=True, slots=True)
class EventContext:
    """
    사건이 **언제 · 누구의 행위로** 일어났는가.

    전부 값 타입이다 — ``GameState`` 도 ``CardInstance`` 도 들고 있지 않다.
    나중에 이 사건을 다시 읽을 때 판이 이미 달라져 있어도 문맥은 그대로여야
    하기 때문이다.
    """

    turn_number: int
    turn_player: int
    phase: Phase
    actor: int | None = None
    """이 변화를 일으킨 행위의 주체. 규칙이 스스로 한 일이면 ``None``."""
    sequence: int = 0
    """한 번의 변화 묶음 안에서 **몇 번째**인가. 순서가 곧 사실이다."""

    def __post_init__(self) -> None:
        if self.turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {self.turn_number}")
        if self.turn_player not in (0, 1):
            raise ValueError(f"턴 플레이어는 0 또는 1 입니다: {self.turn_player}")
        if self.actor is not None and self.actor not in (0, 1):
            raise ValueError(f"actor 는 0 또는 1 입니다: {self.actor}")
        if self.sequence < 0:
            raise ValueError(f"순번은 음수일 수 없습니다: {self.sequence}")
        if not isinstance(self.phase, Phase):
            raise TypeError(f"Phase 가 필요합니다: {type(self.phase).__name__}")

    @classmethod
    def of(
        cls,
        view: GameStateView,
        actor: int | None = None,
        sequence: int = 0,
    ) -> "EventContext":
        """관측에서 문맥을 뽑는다. **관측을 바꾸지 않는다.**"""
        return cls(
            turn_number=view.turn_number,
            turn_player=view.turn_player,
            phase=view.phase,
            actor=actor,
            sequence=sequence,
        )

    def at(self, sequence: int) -> "EventContext":
        """같은 문맥의 다음 순번. 불변이므로 새로 만든다."""
        return EventContext(
            self.turn_number, self.turn_player, self.phase, self.actor, sequence
        )

    def canonical_state(self) -> tuple:
        return (
            self.turn_number,
            self.turn_player,
            self.phase.value,
            self.actor,
            self.sequence,
        )

    def to_dict(self) -> dict:
        return {
            "turn": self.turn_number,
            "turn_player": self.turn_player,
            "phase": self.phase.value,
            "actor": self.actor,
            "sequence": self.sequence,
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        who = "규칙" if self.actor is None else f"P{self.actor}"
        return f"T{self.turn_number} {self.phase.value} #{self.sequence} ({who})"


@dataclass(frozen=True, slots=True)
class ObservedEvent:
    """
    관찰된 사건 하나. **불변**이고 값 타입만 담는다.

    :attr:`event_id` 는 내용에서 나온다 — 무작위도, 시각도, 객체 주소도
    쓰지 않는다. 같은 판에서 같은 행위를 하면 같은 값이다.
    """

    context: EventContext
    timing: TimingEvent

    def __post_init__(self) -> None:
        if not isinstance(self.timing, TimingEvent):
            raise TypeError(f"TimingEvent 가 필요합니다: {type(self.timing).__name__}")

    # --- 조회 --------------------------------------------------------
    @property
    def point(self) -> TimingPoint:
        return self.timing.point

    @property
    def delta(self) -> StateDelta | None:
        return self.timing.delta

    @property
    def instance(self) -> InstanceId | None:
        """이 사건이 건드린 카드. 없으면 ``None``."""
        return self.timing.instance

    @property
    def actor(self) -> int | None:
        """
        사건 자체가 밝히는 주체. 없으면 문맥의 행위자로 **떨어지지 않는다** —
        "누가 이 행위를 했는가" 와 "이 사건이 누구의 것인가" 는 다른 질문이다.
        """
        return self.timing.actor

    @property
    def is_observable(self) -> bool:
        """
        트리거가 볼 수 있는 사건인가.

        거짓이면 **변화는 일어났지만 옮길 이름이 없다**는 뜻이다. "사건이
        없었다" 가 아니다 — :attr:`TimingEvent.note` 가 무엇을 옮기지
        못했는지 말한다.
        """
        return self.timing.point is not TimingPoint.UNIMPLEMENTED

    @property
    def event_id(self) -> str:
        """
        이 사건의 **안정적인 식별자.**

        한 번의 변화 묶음 안에서 사건을 구분하고, 같은 입력이면 같은 값이다.
        **듀얼 전체에 걸친 유일성은 보장하지 않는다** — 같은 턴 · 같은
        페이즈에 내용이 똑같은 변화가 두 번 일어나면 같은 값이 나온다. 전역
        번호가 필요해지면 ``EventJournal`` 의 ``sequence`` 가 그 자리다.
        """
        payload = json.dumps(
            self.canonical_state(),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"T{self.context.turn_number}:{self.point.value}:{digest}"

    def canonical_state(self) -> tuple:
        return (self.context.canonical_state(), self.timing.canonical_state())

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "context": self.context.to_dict(),
            "timing": self.timing.to_dict(),
        }

    def describe_ko(self) -> str:
        return f"{self.context} {self.timing.describe_ko()}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class EventObservation:
    """
    사건 하나와, 그 사건에서 모은 후보들.

    **하나의 사건에 여러 후보가 붙을 수 있다.** 그 관계를 잃지 않으려고
    후보 목록을 따로 펼치지 않고 :class:`~engine.trigger.TriggerCollection`
    을 그대로 안고 있는다 — 수집기가 이미 "어느 사건에서 나왔는가" 를 담아
    돌려준다.
    """

    event: ObservedEvent
    collection: TriggerCollection

    def __post_init__(self) -> None:
        if self.collection.event is not self.event.timing:
            raise EventPipelineError(
                "다른 사건에서 모은 후보를 붙일 수 없습니다. 어느 사건에서 "
                "나왔는지가 사라지면 순서를 정할 근거가 없어집니다."
            )

    @property
    def event_id(self) -> str:
        return self.event.event_id

    @property
    def candidates(self) -> tuple[TriggerCandidate, ...]:
        """**발동 가능한 것들이 아니다.** 적격성은 다음 계층이 답한다."""
        return self.collection.candidates

    @property
    def unchecked(self) -> tuple[str, ...]:
        """볼 수 없어서 확인하지 못한 곳들. 비어 있지 않으면 목록이 완전하지 않다."""
        return self.collection.unchecked

    @property
    def fully_checked(self) -> bool:
        return self.collection.fully_checked

    def canonical_state(self) -> tuple:
        return (self.event.canonical_state(), self.collection.canonical_state())

    def to_dict(self) -> dict:
        return {"event": self.event.to_dict(), "collection": self.collection.to_dict()}

    def describe_ko(self) -> str:
        return f"{self.event.describe_ko()} → 후보 {len(self.candidates)}개"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class EventReader:
    """
    변화 묶음을 사건들로 옮긴다. **판을 바꾸지 않는다.**

    관측만 들고 있어서 바꿀 수 있는 것이 애초에 없다 —
    :class:`~engine.trigger.TriggerCollector` 가 ``GameStateView`` 만 받는
    것과 같은 이유다.
    """

    __slots__ = ("_view",)

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "EventReader 는 GameStateView 만 받습니다. GameState 를 넘기면 "
                "사건을 읽는 일이 판을 바꿀 수 있게 됩니다."
            )
        self._view = view

    @property
    def view(self) -> GameStateView:
        return self._view

    # ------------------------------------------------------------------
    def read(self, result, actor: int | None = None) -> tuple[ObservedEvent, ...]:
        """
        실행 결과 하나를 사건들로 옮긴다.

        ``result`` 는 **변화를 들고 있는 것**이면 무엇이든 된다
        (``ActionExecution`` · ``ProgressionResult`` · ``EffectResult``).
        특정 실행기를 가져오지 않는 이유가 그것이다 — 이 파일이 실행기를
        알면 실행기가 사건을 만들어야 한다는 뜻이 되고, 그러면 상태 변경과
        사건 관찰이 다시 붙는다.
        """
        deltas = getattr(result, "deltas", None)
        if deltas is None:
            raise TypeError(
                f"변화(deltas)를 들고 있는 결과가 필요합니다: "
                f"{type(result).__name__}"
            )
        if actor is None:
            actor = getattr(getattr(result, "action", None), "actor", None)
        return self.read_deltas(deltas, actor=actor)

    def read_deltas(
        self, deltas, actor: int | None = None
    ) -> tuple[ObservedEvent, ...]:
        """
        변화들을 **순서 그대로** 사건으로 옮긴다.

        옮길 이름이 없는 변화는 **버리지 않는다.**
        :meth:`~engine.trigger.TimingEvent.unimplemented` 로 남겨서, "사건이
        없었다" 와 "옮길 이름이 없었다" 가 구분되게 한다.
        """
        base = EventContext.of(self._view, actor=actor)
        found: list[ObservedEvent] = []
        for index, delta in enumerate(deltas):
            if not isinstance(delta, StateDelta):
                raise TypeError(
                    f"StateDelta 가 필요합니다: {type(delta).__name__}"
                )
            found.append(ObservedEvent(base.at(index), self._timing_for(delta)))
        return tuple(found)

    # ------------------------------------------------------------------
    def _timing_for(self, delta: StateDelta) -> TimingEvent:
        """
        변화 하나를 시점으로. 옮길 수 없으면 **솔직하게** 적는다.

        :meth:`TimingEvent.from_delta` 는 모르는 변화를 만나면 예외를 던진다
        (지어내지 않겠다는 뜻이다). 파이프라인은 거기서 멈추는 대신 그
        사실을 사건으로 남긴다 — 새 Delta 가 생겼을 때 실행이 죽는 것보다,
        "이것을 아직 못 옮긴다" 가 눈에 보이는 쪽이 낫다.
        """
        try:
            return TimingEvent.from_delta(delta)
        except TriggerError:
            return TimingEvent.unimplemented(
                f"{type(delta).__name__} 를 옮길 시점 이름이 아직 없습니다: "
                f"{delta.describe_ko()}"
            )


class EventPipeline:
    """
    사건을 읽고 **기존 수집기**에게 넘긴다.

        pipeline = EventPipeline(view, registry, definitions)
        for observation in pipeline.collect(execution):
            observation.candidates      # 이 사건에서 나온 후보들

    여기서 끝난다. 적격성(2-F-3-B) · 정렬(2-F-3-C) · 체인 삽입(2-F-3-D) ·
    우선권(2-F-1)은 각자의 계층이 하고, 이 파일은 그것들을 부르지 않는다.
    """

    __slots__ = ("_reader", "_collector")

    def __init__(
        self,
        view: GameStateView,
        registry: TriggerRegistry,
        definitions=None,
    ):
        self._reader = EventReader(view)
        self._collector = TriggerCollector(view, registry, definitions)

    @property
    def view(self) -> GameStateView:
        return self._reader.view

    @property
    def reader(self) -> EventReader:
        return self._reader

    @property
    def collector(self) -> TriggerCollector:
        return self._collector

    # ------------------------------------------------------------------
    def observe(self, result, actor: int | None = None) -> tuple[ObservedEvent, ...]:
        """변화를 사건으로만 옮긴다. 후보는 모으지 않는다."""
        return self._reader.read(result, actor=actor)

    def collect(self, result, actor: int | None = None) -> tuple[EventObservation, ...]:
        """사건마다 후보를 모은다. **사건별로 따로 남긴다** — 합치지 않는다."""
        return self.collect_events(self.observe(result, actor=actor))

    def collect_events(self, events) -> tuple[EventObservation, ...]:
        """이미 읽어 둔 사건들에서 후보를 모은다."""
        return tuple(
            EventObservation(event, self._collector.collect(event.timing))
            for event in events
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EventPipeline viewer=P{self.view.viewer}>"


__all__ = [
    "EventPipelineError",
    "EventContext",
    "ObservedEvent",
    "EventObservation",
    "EventReader",
    "EventPipeline",
]
