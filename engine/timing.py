"""
타이밍 창과 우선권 — **지금 어떤 판단 창이 열려 있는가**.

    사건 (TimingEvent)
        ↓  TimingCoordinator.open_window(event, priority, chain)
    TimingWindow          이 시점의 문맥 (사건 · 턴 · 우선권 · 체인)
        ↓  collect_triggers  →  order_triggers  →  build_trigger_plan
        ↓  prepare_chain     →  check_priority
    TimingOutcome         무엇이 검토되었고 무엇이 체인에 들어갈 준비가 되었는가

여기서 게임을 진행시키지 않는다
-------------------------------
체인을 해결하지 않고, 효과를 실행하지 않고, 페이즈를 넘기지 않고,
우선권을 **돌리지도 않는다.** 이 계층이 답하는 것은 딱 하나다 —
"이 사건 뒤에 무엇을 검토해야 하고, 그 결과가 어떤 상태인가".

우선권을 **갱신하지 않고 확인만 한다**
--------------------------------------
:attr:`TimingOutcome.priority` 는 **들어온 것 그대로**다. "체인에 링크가
추가되었으니 턴 플레이어에게 우선권이 간다" 는 **규칙**이고, 그 규칙은 아직
없다. 지금 만들면 틀린 채로 굳는다.

대신 :class:`~engine.priority.PriorityResolver` 로 **확인**한다 — 지금 차례인
사람이 정말 행동할 수 있는 상태인가, 우선권 상태가 판과 어긋나지 않았는가.
그리고 정할 수 없는 것은 :data:`WINDOW_UNRESOLVED_RULES` 에 남긴다.

책임을 섞지 않는다
------------------
=============================  ==========================================
``PriorityResolver``            누가 우선권을 가지는가
``TriggerCollector`` 외          어떤 트리거가 후보이고 발동 가능한가
``TriggerChainIntegrator``      그 후보를 체인에 넣을 준비가 되었는가
``Chain``                       지금 어떤 링크가 쌓여 있는가
``TimingWindow``                이 사건 뒤에 어떤 판단 창이 열렸는가
=============================  ==========================================

어느 하나가 다른 역할을 대신하지 않는다. :class:`TimingCoordinator` 는
**부르기만** 하고 판정을 다시 만들지 않는다.

판을 바꾸지 않는다
------------------
``GameState`` 를 받지 않는다. ``Chain`` 도 ``PriorityState`` 도 불변이므로
결과는 전부 **새 값**이고, 들어온 것은 그대로 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.chain import Chain
from engine.effect.definition import (
    EffectDefinitionSource,
    EffectImplementationLookup,
)
from engine.game_state_view import GameStateView
from engine.priority import PriorityResolver, PriorityState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCollection,
    TriggerCollector,
    TriggerError,
    TriggerRegistry,
)
from engine.trigger_chain import TriggerChainIntegrator, TriggerChainPlan
from engine.trigger_order import TriggerOrdering
from engine.validation import ActionValidity, ValidationResult
from engine.vocabulary import Phase

#: 이 계층이 **아직 정할 수 없는** 규칙들.
#:
#: 숨기지 않고 목록으로 남긴다. :attr:`TimingOutcome.unresolved_rules` 가
#: 앞 계층의 미정 규칙과 함께 이것을 실어 나르므로, 결과를 받는 쪽도
#: "무엇이 아직 안 정해졌나" 를 안다.
WINDOW_UNRESOLVED_RULES: tuple[str, ...] = (
    "체인에 링크가 추가된 뒤 우선권이 누구에게 가는가",
    "이 시점에 응답 창이 열리는가, 열린다면 어떤 종류인가",
    "놓친 타이밍 (missed timing)",
    "동시에 일어난 여러 사건을 하나의 창으로 묶는 규칙",
    "체인이 끝난 뒤 우선권이 어디로 돌아가는가",
)


@dataclass(frozen=True, slots=True)
class TimingWindow:
    """
    사건 하나 뒤에 열린 **판단 창**. 불변 스냅숏이다.

    ``GameState`` 를 담지 않는다 — 담으면 창이 특정 판에 묶이고 직렬화도
    replay 도 불가능해진다. 판에서 가져오는 것은 관측으로 읽은 값
    (:attr:`viewer` · :attr:`turn_player` · :attr:`phase`) 뿐이다.

    **트리거 수집 결과를 담지 않는다.** 창을 여는 것과 그 창에서 무엇을
    검토하는가는 다른 일이고, 수집 결과는 :class:`TimingOutcome` 에 있다.
    """

    event: TimingEvent
    viewer: int
    """이 창을 만든 관측의 시점. 보이는 것이 다르면 검토 결과도 다르다."""
    turn_player: int
    phase: Phase
    priority: PriorityState
    chain: Chain
    """**이 시점의 체인.** 새 창을 연다고 비우지 않는다."""

    def __post_init__(self) -> None:
        for name in ("viewer", "turn_player"):
            if getattr(self, name) not in (0, 1):
                raise TriggerError(f"{name} 는 0 또는 1 입니다: {getattr(self, name)}")
        if not isinstance(self.chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(self.chain).__name__}")
        if not isinstance(self.priority, PriorityState):
            raise TypeError(
                f"PriorityState 가 필요합니다: {type(self.priority).__name__}"
            )

    @property
    def point(self) -> TimingPoint:
        return self.event.point

    @property
    def opponent(self) -> int:
        return 1 - self.turn_player

    @property
    def chain_is_open(self) -> bool:
        """이미 쌓인 링크가 있는가. **해결 여부와 다른 질문이다.**"""
        return not self.chain.is_empty

    def canonical_state(self) -> tuple:
        return (
            self.event.canonical_state(),
            self.viewer,
            self.turn_player,
            self.phase.value,
            self.priority.canonical_state(),
            self.chain.canonical_state(),
        )

    def to_dict(self) -> dict:
        return {
            "event": self.event.to_dict(),
            "viewer": self.viewer,
            "turn_player": self.turn_player,
            "phase": self.phase.value,
            "priority": self.priority.to_dict(),
            "chain": self.chain.to_dict(),
        }

    def describe_ko(self) -> str:
        return (
            f"[{self.point.value}] T{self.turn_player} {self.phase.value} "
            f"| {self.priority.describe_ko()} | {self.chain.describe_ko()}"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TimingOutcome:
    """
    창 하나를 끝까지 검토한 결과. 불변이다.

    앞 계층의 결과를 **그대로** 들고 있다 — 다시 계산하지 않았다는 것이
    구조로 보이게 하기 위해서다.

    :attr:`priority` 는 :attr:`window` 의 것과 **같다.** 이 계층은 우선권을
    돌리지 않는다 (모듈 설명 참고).
    """

    window: TimingWindow
    collection: TriggerCollection
    ordering: TriggerOrdering
    plan: TriggerChainPlan
    chain: Chain
    """계획대로 링크를 쌓은 **새 체인**. 들어온 체인은 그대로 남는다."""
    priority_check: ValidationResult
    unresolved_rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.unresolved_rules, tuple):
            raise TypeError("unresolved_rules 는 tuple 이어야 합니다.")
        if self.priority is not self.window.priority:
            raise TriggerError(
                "우선권이 바뀌었습니다. 이 계층은 우선권을 갱신하지 않습니다 "
                "— 누구에게 넘어가는가는 아직 규칙이 없습니다."
            )

    # ------------------------------------------------------------------
    @property
    def event(self) -> TimingEvent:
        return self.window.event

    @property
    def point(self) -> TimingPoint:
        return self.window.point

    @property
    def priority(self) -> PriorityState:
        """**들어온 그대로.** 갱신하지 않는다."""
        return self.window.priority

    @property
    def inserted_links(self) -> tuple:
        """이번 창에서 새로 쌓인 링크들."""
        return self.plan.links

    @property
    def chain_changed(self) -> bool:
        return self.chain != self.window.chain

    @property
    def priority_is_actionable(self) -> bool:
        """
        지금 차례인 사람이 행동할 수 있는 상태인가.

        **``VALID`` 일 때만 참이다** — ``UNKNOWN`` 이 허가로 새지 않는다.
        그리고 이것은 "무엇을 할 수 있다" 가 아니라 "차례가 열려 있다" 다.
        """
        return self.priority_check.validity is ActionValidity.VALID

    @property
    def needs_decision(self) -> bool:
        """
        누군가 더 결정해야 하는가.

        판정 불가 후보가 남았거나, 정보가 없어 막힌 후보가 있거나, 순서와
        우선권 규칙이 아직 정해지지 않았다면 참이다. **여기서 정하지
        않는다** — 다음 계층의 몫이다.
        """
        return self.plan.needs_decision or bool(self.unresolved_rules)

    def canonical_state(self) -> tuple:
        return (
            self.window.canonical_state(),
            self.collection.canonical_state(),
            self.ordering.canonical_state(),
            self.plan.canonical_state(),
            self.chain.canonical_state(),
            self.priority_check.canonical_state(),
            self.unresolved_rules,
        )

    def to_dict(self) -> dict:
        return {
            "window": self.window.to_dict(),
            "collection": self.collection.to_dict(),
            "ordering": self.ordering.to_dict(),
            "plan": self.plan.to_dict(),
            "chain": self.chain.to_dict(),
            "priority": self.priority.to_dict(),
            "priority_check": self.priority_check.to_dict(),
            "unresolved_rules": list(self.unresolved_rules),
            "needs_decision": self.needs_decision,
        }

    def describe_ko(self) -> str:
        return (
            f"{self.window.describe_ko()} → 후보 {len(self.collection)} · "
            f"삽입 {len(self.inserted_links)} · 미정 규칙 "
            f"{len(self.unresolved_rules)}개"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TimingCoordinator:
    """
    사건 하나를 **끝까지 검토**하되, 아무것도 진행시키지 않는다.

    판정을 다시 만들지 않는다 — 앞 계층
    (:class:`~engine.trigger_chain.TriggerChainIntegrator` 와 그것이 부르는
    수집 · 적격성 · 정리) 을 부르기만 한다.

    ``GameState`` 를 받지 않으므로 판을 바꿀 수단이 없다.
    """

    __slots__ = ("_view", "_registry", "_definitions", "_integrator")

    def __init__(
        self,
        view: GameStateView,
        registry: TriggerRegistry,
        definitions: EffectDefinitionSource | None = None,
        implementations: EffectImplementationLookup | None = None,
    ):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "TimingCoordinator 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 검토가 판을 바꿀 수 있게 됩니다."
            )
        self._view = view
        self._registry = registry
        self._definitions = definitions
        # 통합기가 수집 · 적격성 · 정리를 이미 엮어 놓았다. 다시 엮지 않는다.
        self._integrator = TriggerChainIntegrator(
            view, registry, definitions, implementations
        )

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def integrator(self) -> TriggerChainIntegrator:
        return self._integrator

    # ------------------------------------------------------------------
    # 단계들 — 각각 따로 부를 수 있다
    # ------------------------------------------------------------------
    def open_window(
        self, event: TimingEvent, priority: PriorityState, chain: Chain
    ) -> TimingWindow:
        """
        사건 하나에 대한 판단 창을 연다. **여기까지만 한다** — 무엇을
        검토할지는 다음 단계다.

        ``chain`` 을 **그대로** 담는다. 새 창을 연다고 기존 체인을 비우지
        않는다.
        """
        if not isinstance(event, TimingEvent):
            raise TypeError(f"TimingEvent 가 필요합니다: {type(event).__name__}")
        return TimingWindow(
            event=event,
            viewer=self._view.viewer,
            turn_player=self._view.turn_player,
            phase=self._view.phase,
            priority=priority,
            chain=chain,
        )

    def collect_triggers(self, window: TimingWindow) -> TriggerCollection:
        """
        후보를 모은다. 기존 수집기를 그대로 쓴다.

        ``unchecked`` (볼 수 없어서 확인하지 못한 곳)가 여기서 사라지지
        않는다 — 그것이 "후보가 없다" 와 "못 봤다" 를 가르는 정보다.
        """
        self._check_window(window)
        return TriggerCollector(
            self._view, self._registry, self._definitions
        ).collect(window.event)

    def order_triggers(self, window: TimingWindow) -> TriggerOrdering:
        """수집 → 적격성 → 정리. 기존 통합기가 하던 그대로다."""
        self._check_window(window)
        return self._integrator.collect_and_order(window.event)

    def build_trigger_plan(
        self, window: TimingWindow, ordering: TriggerOrdering
    ) -> TriggerChainPlan:
        """무엇이 체인에 들어갈 수 있는지 계획한다. **넣지는 않는다.**"""
        self._check_window(window)
        return self._integrator.plan(window.chain, ordering)

    def prepare_chain(self, window: TimingWindow, plan: TriggerChainPlan) -> Chain:
        """
        계획대로 링크를 쌓은 **새 체인**을 돌려준다.

        해결하지 않는다 — 그 사이에 우선권과 응답 기회가 있고, 그것은 이
        계층이 정하지 않는다.
        """
        self._check_window(window)
        return self._integrator.extend(window.chain, plan)

    def check_priority(self, window: TimingWindow) -> ValidationResult:
        """
        지금 차례인 사람이 행동할 수 있는 상태인가. **확인만 한다.**

        우선권을 돌리지 않는다. 쥔 사람이 없으면 턴 플레이어를 기준으로
        물어 "열린 창이 없다" 는 답을 받는다 — 그것도 사실이다.

        우선권 상태가 지금 판과 어긋나면 :class:`PriorityResolver` 가
        ``UNKNOWN`` 을 돌려준다. 어느 쪽이 낡았는지 모르는 채로 "안 된다" 고
        단정하지 않는다.
        """
        self._check_window(window)
        seat = window.priority.holder.seat
        return PriorityResolver(self._view, window.priority).may_act(
            seat if seat is not None else window.turn_player
        )

    # ------------------------------------------------------------------
    def review(
        self, event: TimingEvent, priority: PriorityState, chain: Chain
    ) -> TimingOutcome:
        """
        단계들을 순서대로 이어 붙인다. **각 단계는 따로도 부를 수 있다** —
        이 메서드는 하나의 큰 함수가 아니라 조립일 뿐이다.

        아무것도 실행하지 않고 아무것도 진행시키지 않는다.
        """
        window = self.open_window(event, priority, chain)
        collection = self.collect_triggers(window)
        ordering = self.order_triggers(window)
        plan = self.build_trigger_plan(window, ordering)
        prepared = self.prepare_chain(window, plan)
        verdict = self.check_priority(window)
        return TimingOutcome(
            window=window,
            collection=collection,
            ordering=ordering,
            plan=plan,
            chain=prepared,
            priority_check=verdict,
            unresolved_rules=WINDOW_UNRESOLVED_RULES + plan.unresolved_rules,
        )

    # ------------------------------------------------------------------
    def _check_window(self, window: TimingWindow) -> None:
        """
        이 창이 **이 관측에서** 열린 것인가.

        다른 시점에서 연 창을 다른 관측으로 검토하면 보이는 것이 달라져
        결과가 조용히 어긋난다.
        """
        if not isinstance(window, TimingWindow):
            raise TypeError(f"TimingWindow 가 필요합니다: {type(window).__name__}")
        if window.viewer != self._view.viewer:
            raise TriggerError(
                f"P{window.viewer} 의 관측에서 연 창을 P{self._view.viewer} 의 "
                "관측으로 검토할 수 없습니다."
            )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TimingCoordinator p{self._view.viewer}>"


__all__ = [
    "WINDOW_UNRESOLVED_RULES",
    "TimingWindow",
    "TimingOutcome",
    "TimingCoordinator",
]
