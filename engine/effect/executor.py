"""
EffectExecutor — 효과가 **실제로 판을 바꾸는 유일한 문**.

    EffectDefinition + ResolutionContext + GameState
        ↓  EffectExecutor.execute()
    GameState 변경  +  EffectResult

Operation 이 스스로 판을 바꾸지 않는다
--------------------------------------
``operation.execute(state)`` 를 만들지 않았다. 일은 **무엇을 한다는 의미**일
뿐이고, 그 의미를 상태 조작으로 옮기는 것은 실행기 하나의 책임이다. 흩어
놓으면 나중에 ``StateDelta`` · ``EventJournal`` 을 끼워 넣을 자리가 없다.

먼저 다 따져보고, 그 다음에 바꾼다
----------------------------------
실행은 두 단계다.

1. **계획** — 권위 · 조건 · 문맥 · 대상 · 지원 여부를 전부 확인하고,
   실제로 할 일을 카드 단위까지 확정한다. 여기서 판을 **읽기만** 한다.
2. **적용** — 확정된 일을 순서대로 수행한다.

계획이 실패하면 적용은 시작도 하지 않으므로 **판이 반쯤 바뀌는 일이 없다.**
지원하는 일들의 목적지(묘지 · 제외 · 패 · 덱)는 전부 칸 수 제한이 없는 존
이라서, 계획을 통과한 이동이 적용 중에 거부될 여지도 없다.

그래도 예상 못 한 오류가 나면 :attr:`ResolutionStatus.EXECUTION_ERROR` 를
돌려주는데, **그때는 판이 반쯤 바뀌어 있을 수 있다.** 일어나서는 안 되는
경우이고, 일어났다면 결함이다. 원자적 되돌리기는 ``StateDelta`` 가 들어오는
Phase 2-E 의 몫이다 (ADR-008).

무엇이 달라졌는지 적어 둔다
---------------------------
판을 바꾼 뒤에는 그 변화를 :class:`~engine.effect.delta.StateDelta` 로
남기고, :class:`~engine.effect.journal.EventJournal` 을 받았으면 거기에도
적는다. 기록은 판을 바꾸지 않는다 — 방향은 실행 → 기록 한 쪽뿐이다.

되돌리기는 여전히 없다 (ADR-008). Delta 는 *기록*이지 *계획*이 아니다.


관측과 변경을 섞지 않는다
-------------------------
조건 평가는 :class:`~engine.game_state_view.GameStateView` 로 하고, 변경은
``GameState`` 의 기존 primitive 로만 한다. 관측을 통해 판을 고치지 않는다.

권위는 그대로다
---------------
``TEXT_DERIVED`` 는 구현이 등록되어 있어도 실행하지 않는다. ``LUA_VERIFIED``
라고 해서 자동으로 실행되지도 않는다 — 등록된 구현이 있어야 한다 (ADR-006).

할 줄 아는 것 ≠ 해도 되는 것
----------------------------
구현이 등록되어 있어도, 그 일의 **규칙**을 판정할 수 없으면 수행하지
않는다. 파괴가 그렇다 — 내성과 대체 효과를 답할
:class:`~engine.effect.semantics.DestructionRuling` 이 없으면
:attr:`~engine.effect.resolution.ResolutionStatus.UNCHECKED_RULES` 로 멈추고
판은 한 글자도 바뀌지 않는다. **``UNKNOWN`` 은 허가가 아니다.**
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from engine.condition import (
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    PlayerRef,
)
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.cost.resolver import CandidateResolver
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    StateDelta,
    ZoneMoved,
    ZoneShuffled,
)
from engine.effect.definition import (
    EffectDefinition,
    EffectImplementationLookup,
    EmptyImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.operation import (
    ShuffleOperation,
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    MoveOperation,
    Operation,
    OperationKind,
    SpecialSummonOperation,
)
from engine.effect.journal import EventJournal
from engine.randomness import RandomError, RandomOutcome, RandomPurpose
from engine.effect.targeting import TargetLegality, TargetResolver
from engine.effect.semantics import (
    MISSING_GATE,
    DestructionRuling,
    MovementRuling,
    SummonRuling,
    UnknownDestructionRuling,
    UnknownMovementRuling,
    UnknownSummonRuling,
    ask_movement,
    collect_unchecked,
    declared_gate_question,
    gating_rules,
    is_rule_gated,
    origin_rule,
    unchecked_rules,
)
from engine.effect.resolution import (
    AppliedOperation,
    EffectResult,
    ResolutionContext,
    ResolutionStatus,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.special_summon import SPECIAL_SUMMON_PROCEDURE
from engine.state.game_state import GameState
from engine.summon import SummonError, SummonPlacement
from engine.validation import ValidationCode
from engine.vocabulary import Zone

#: 카드를 다루는 일이 카드를 **어디로** 보내는가.
#:
#: 목적지가 같다고 해서 같은 일이 아니다 — 파괴 · 묘지로 보내기 · 릴리스 ·
#: 버리기가 전부 묘지로 가지만 서로 다른 사건이고, 그 구분은
#: ``AppliedOperation.kind`` 와 ``reason_names`` 가 지킨다 (ADR-002).
DESTINATION: dict[OperationKind, Zone] = {
    OperationKind.DESTROY: Zone.GRAVE,
    OperationKind.SEND_TO_GRAVE: Zone.GRAVE,
    OperationKind.RELEASE: Zone.GRAVE,
    OperationKind.DISCARD: Zone.GRAVE,
    OperationKind.BANISH: Zone.REMOVED,
    OperationKind.RETURN_TO_HAND: Zone.HAND,
    OperationKind.RETURN_TO_DECK: Zone.DECK,
}


class DestinationOwner(str, Enum):
    """
    옮겨진 카드가 **누구의** 존으로 가는가.

    존은 플레이어마다 따로 있으므로, 목적지를 정할 때 존 종류만으로는
    부족하다. 누구의 묘지인지까지 정해야 한다.
    """

    OWNER = "owner"
    """카드의 **주인** 쪽. 소유권 기반 존(묘지 · 제외 · 패 · 덱)이 전부 이쪽이다."""
    CONTROLLER = "controller"
    """카드를 **지금 쓰는 쪽**. 필드(MZONE · SZONE …)가 이쪽이다."""


#: 일마다 목적지의 주인을 어떻게 정하는가. **명시적으로** 적는다.
#:
#: 지금은 전부 :attr:`DestinationOwner.OWNER` 인데, 그것은 우연이 아니라
#: 지원하는 일들이 모두 소유권 기반 존으로 보내기 때문이다. 소환 · 세트
#: 처럼 **필드로** 보내는 일이 들어오면 그것은 ``CONTROLLER`` 이고, 그때
#: 이 표에 줄이 늘어난다. 한 줄로 ``card.owner`` 를 쓰고 있으면 그 날
#: 조용히 틀린다.
#:
#: ``DESTROY`` 도 적어 둔다 — 파괴된 카드가 주인의 묘지로 간다는 것은
#: 이미 정해진 사실이다. 파괴가 멈추는 이유는 목적지가 아니라 **파괴해도
#: 되는지를 판정할 수 없기** 때문이다 (:class:`
#: ~engine.effect.semantics.DestructionRuling`).
DESTINATION_OWNER: dict[OperationKind, DestinationOwner] = {
    OperationKind.DESTROY: DestinationOwner.OWNER,
    OperationKind.SEND_TO_GRAVE: DestinationOwner.OWNER,
    OperationKind.RELEASE: DestinationOwner.OWNER,
    OperationKind.DISCARD: DestinationOwner.OWNER,
    OperationKind.BANISH: DestinationOwner.OWNER,
    OperationKind.RETURN_TO_HAND: DestinationOwner.OWNER,
    OperationKind.RETURN_TO_DECK: DestinationOwner.OWNER,
}


def destination_player(kind: OperationKind, card) -> int:
    """
    이 카드가 **누구의** 존으로 가는가. 표를 따른다.

    ``GameState.move`` 의 ``to_player`` 기본값은 **컨트롤러**다. 그 기본값에
    기대면 컨트롤을 빼앗긴 카드가 빼앗은 쪽의 묘지로 간다. 그래서 실행기는
    기본값을 쓰지 않고 언제나 여기서 정한 값을 넘긴다.
    """
    if kind is OperationKind.MOVE:
        raise KeyError(
            "MOVE 의 목적지 주인은 표가 아니라 MoveOperation.to_owner 가 "
            "정합니다. 의미가 없는 이동이라 '이 일은 주인에게 간다' 는 "
            "규칙 자체가 없기 때문입니다."
        )
    rule = DESTINATION_OWNER[kind]
    return card.owner if rule is DestinationOwner.OWNER else card.controller


#: 이 실행기가 **할 줄 아는** 일.
#:
#: ``DESTROY`` 가 여기 있는 것은 "파괴 규칙을 전부 옮겼다" 는 뜻이 아니라
#: **"파괴를 어떻게 수행하는지는 안다"** 는 뜻이다. 해도 되는지는 다른
#: 질문이고, 그것은 :class:`~engine.effect.semantics.DestructionRuling` 이
#: 답한다 — 답을 못 받으면 수행하지 않는다
#: (:attr:`~engine.effect.resolution.ResolutionStatus.UNCHECKED_RULES`).
#:
#: 할 줄 아는 것과 해도 되는 것을 한 집합에 넣지 않는다. 넣으면 "지원한다"
#: 가 곧 "허가한다" 가 된다.
#: 이 실행기가 **할 줄 아는** 일. :data:`OPERATION_HANDLERS` 에서 세운다 —
#: 목록을 따로 적어 두면 표와 어긋나는 날이 온다 (Phase 2-V).
#:
#: 모듈 끝에서 정의된다. 표가 클래스 뒤에 와야 하기 때문이다.
SUPPORTED: frozenset[OperationKind]

#: 지원하지 않는 일과, 무엇이 없어서 못 하는가.
UNSUPPORTED_REASON: dict[OperationKind, str] = {
    OperationKind.UNKNOWN: "표현되지 않은 일",
}


class EffectExecutionError(RuntimeError):
    """
    적용 중에 판이 예상과 다르게 움직였다.

    :attr:`ResolutionStatus.EXECUTION_ERROR` 로 올라간다. 일어나서는 안
    되는 경우이고, 일어났다면 결함이다.
    """


@dataclass(frozen=True, slots=True)
class _Step:
    """계획 단계에서 확정한 **할 일 하나.** 적용 단계가 그대로 수행한다."""

    operation: Operation
    instances: tuple[InstanceId, ...] = ()
    owners: tuple[int, ...] = ()
    """``instances`` 와 짝을 이루는 **목적지의 주인.** 계획 단계에서 정한다."""
    amount: int | None = None
    player: int | None = None
    placements: tuple[SummonPlacement, ...] = ()
    """소환이 확정한 배치들. 소환이 아닌 일에는 비어 있다 (Phase 2-U)."""
    outcome: "RandomOutcome | None" = None
    """
    무작위가 **계획 단계에서 이미 결정된** 결과 (Phase 2-Z).

    적용 단계에서 난수를 꺼내지 않는 것이 핵심이다 — 계획이 끝난 뒤에
    무작위가 일어나면 "계획을 전부 확인한 뒤에 적용한다" 가 깨지고,
    실패했을 때 난수원만 소비된 채로 남는다.
    """

    def __post_init__(self) -> None:
        if len(self.owners) != len(self.instances):
            raise ValueError(
                "카드마다 목적지의 주인이 정해져 있어야 합니다: "
                f"{len(self.instances)}장, 주인 {len(self.owners)}개"
            )

    def record(self) -> AppliedOperation:
        return AppliedOperation(
            kind=self.operation.kind,
            reason_names=self.operation.reason_names,
            instances=self.instances,
            amount=self.amount,
            player=self.player,
        )


class EffectImplementationRegistry:
    """
    어떤 효과에 실행 구현이 있다고 **선언된** 목록.

    ADR-006 을 지키기 위한 최소 구조다. 등록은 손으로 한다 — 카드 데이터가
    ``LUA_VERIFIED`` 라는 것만으로 자동 등록되지 않는다. 그것이 "검증된
    의미" 와 "실행 가능" 을 나누는 지점이다.

    ``analysis`` 에서 자동으로 채우는 컴파일러는 아직 없다. 만들 때
    ``TEXT_DERIVED`` 경계를 다시 확인해야 한다.
    """

    __slots__ = ("_refs",)

    def __init__(self, refs=()):
        self._refs: set[EffectRef] = set(refs)

    def register(self, effect_ref: EffectRef) -> "EffectImplementationRegistry":
        self._refs.add(effect_ref)
        return self

    def has_implementation(self, effect_ref: EffectRef) -> bool:
        return effect_ref in self._refs

    def __len__(self) -> int:
        return len(self._refs)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EffectImplementationRegistry n={len(self._refs)}>"


class EffectExecutor:
    """
    효과를 실제로 적용한다. **효과가 판을 바꾸는 공식 진입점이다.**

    ``lookup`` 을 주지 않으면 아무 구현도 등록되어 있지 않은 것으로 본다 —
    그것이 기본 상태이고, 그 상태에서는 어떤 효과도 실행되지 않는다.
    """

    __slots__ = ("_lookup", "_journal", "_destruction", "_summoning", "_movement")

    def __init__(
        self,
        lookup: EffectImplementationLookup | None = None,
        journal: EventJournal | None = None,
        destruction: DestructionRuling | None = None,
        summoning: SummonRuling | None = None,
        movement: MovementRuling | None = None,
    ):
        self._lookup = lookup if lookup is not None else EmptyImplementationLookup()
        # 기록은 **선택**이다. 없으면 아무것도 적지 않고, 있어도 실행
        # 결과는 달라지지 않는다 — 기록이 판정에 끼어들면 기록이 아니다.
        self._journal = journal
        # 파괴 판정은 **선택이 아니다.** 주지 않으면 아무것도 판정하지 못하는
        # 판정기가 들어가고, 그러면 어떤 파괴도 일어나지 않는다.
        # ``EmptyImplementationLookup`` 과 같은 자리다 (ADR-006).
        self._destruction = (
            destruction if destruction is not None else UnknownDestructionRuling()
        )
        # 소환 판정도 **선택이 아니다.** 주지 않으면 어떤 특수 소환도
        # 일어나지 않는다 — "이 카드를 특수 소환할 수 있는가" 는 카드마다
        # 다르고 그것을 읽는 계층이 없다 (Phase 2-U).
        self._summoning = (
            summoning if summoning is not None else UnknownSummonRuling()
        )
        # 이동 판정도 **선택이 아니다** (Phase 2-X). 주지 않으면 관문을
        # **선언한** 이동은 하나도 일어나지 않는다. 선언하지 않은 이동은
        # 영향을 받지 않는다 — 그 카드의 스크립트가 묻지 않기 때문이다.
        self._movement = (
            movement if movement is not None else UnknownMovementRuling()
        )

    @property
    def journal(self) -> EventJournal | None:
        return self._journal

    @property
    def destruction(self) -> DestructionRuling:
        return self._destruction

    @property
    def summoning(self) -> SummonRuling:
        return self._summoning

    @property
    def movement(self) -> MovementRuling:
        return self._movement

    # ==================================================================
    # 진입점
    # ==================================================================
    def execute(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
    ) -> EffectResult:
        """
        효과를 적용한다.

        ``state`` 는 **바뀔 수 있다.** 다만 :attr:`ResolutionStatus.RESOLVED`
        를 돌려줄 때만 그렇다 — 그 밖의 모든 결과에서는 한 글자도 바뀌지
        않는다 (:attr:`ResolutionStatus.EXECUTION_ERROR` 제외, 설명 참고).
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "EffectExecutor 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 적용할 수 없습니다."
            )

        plan = self._plan(state, definition, context)
        if isinstance(plan, EffectResult):
            return plan  # 계획 실패 — 판은 그대로다

        applied: list[AppliedOperation] = []
        deltas: list[StateDelta] = []
        try:
            for step in plan:
                record, changes = self._apply(state, step)
                applied.append(record)
                deltas.extend(changes)
        except Exception as error:  # pragma: no cover - 일어나서는 안 된다
            # 여기서는 변화 기록을 돌려주지 않는다. 판이 반쯤 바뀌어 있을 수
            # 있고, 반쪽짜리 기록은 없는 것보다 나쁘다 — 그것을 근거로
            # 되감으면 틀린 판이 된다.
            return EffectResult(
                ResolutionStatus.EXECUTION_ERROR,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"적용 중 오류가 났습니다: {error}. 판이 반쯤 바뀌어 있을 수 "
                "있습니다.",
            )

        result = EffectResult(
            ResolutionStatus.RESOLVED,
            ValidationCode.OK,
            f"{definition.effect_ref} 를 적용했습니다 ({len(applied)}건).",
            applied=tuple(applied),
            deltas=tuple(deltas),
            # 의미를 주장한 일들이 **보지 않은 규칙**을 그대로 들고 나간다.
            # 성공했다고 규칙을 전부 본 것이 아니다 (Phase 2-M).
            unchecked_rules=collect_unchecked(record.kind for record in applied),
        )
        if self._journal is not None and result.deltas:
            # 판을 바꾼 해결만 적는다. 바꾼 것이 없으면 역사도 없다.
            self._journal.record(
                effect_ref=definition.effect_ref,
                actor=context.controller,
                applied=result.applied,
                deltas=result.deltas,
                source=context.source,
            )
        return result

    # ==================================================================
    # 1단계 — 계획. 판을 읽기만 한다.
    # ==================================================================
    def _plan(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
    ) -> "list[_Step] | EffectResult":
        """
        할 일을 카드 단위까지 확정한다. 하나라도 걸리면 :class:`EffectResult`
        를 돌려주고, 그때 판은 아직 손대지 않은 상태다.
        """
        if context.effect_ref != definition.effect_ref:
            return _fail(
                ResolutionStatus.INVALID_CONTEXT,
                ValidationCode.EFFECT_REF_CARD_MISMATCH,
                f"문맥이 가리키는 효과({context.effect_ref})가 정의"
                f"({definition.effect_ref})와 다릅니다.",
            )

        authority = self._check_authority(definition)
        if authority is not None:
            return authority

        unsupported = self._check_supported(definition)
        if unsupported is not None:
            return unsupported

        condition = self._check_condition(state, definition, context)
        if condition is not None:
            return condition

        pending = context.pending_targets(definition)
        if pending:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                "아직 고르지 않은 대상이 있습니다: "
                + ", ".join(str(ref) for ref in pending),
            )

        steps: list[_Step] = []
        for operation in definition.operations:
            step = self._plan_operation(state, definition, context, operation)
            if isinstance(step, EffectResult):
                return step
            steps.append(step)
        return steps

    def _check_authority(self, definition: EffectDefinition) -> EffectResult | None:
        """
        실행 권위. **출처 금지가 가장 먼저**다 — 구현이 등록되어 있어도
        ``TEXT_DERIVED`` 는 실행하지 않는다 (ADR-004).
        """
        availability = execution_availability(definition, self._lookup)
        if availability is ExecutionAvailability.EXECUTABLE:
            return None
        if availability is ExecutionAvailability.FORBIDDEN_SOURCE:
            return _fail(
                ResolutionStatus.FORBIDDEN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "공식 텍스트에서 유추한 효과는 실행하지 않습니다 (ADR-004).",
                missing="executable implementation from official script",
            )
        if availability is ExecutionAvailability.UNVERIFIED:
            return _fail(
                ResolutionStatus.UNKNOWN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "의미가 공식 근거에서 확인되지 않았습니다.",
                missing="verified semantics",
            )
        return _fail(
            ResolutionStatus.NOT_IMPLEMENTED,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"{definition.effect_ref} 의 실행 구현이 등록되어 있지 않습니다. "
            "검증된 의미만으로는 실행하지 않습니다 (ADR-006).",
            missing="registered effect implementation",
        )

    def _check_supported(self, definition: EffectDefinition) -> EffectResult | None:
        """이 실행기가 다룰 수 있는 일들인가."""
        for operation in definition.operations:
            if operation.kind in SUPPORTED:
                continue
            missing = UNSUPPORTED_REASON.get(
                operation.kind, f"{operation.kind.value} 실행"
            )
            return _fail(
                ResolutionStatus.UNSUPPORTED_OPERATION,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"이 실행기는 {operation.kind.value} 를 다루지 못합니다.",
                missing=missing,
            )
        return None

    def _check_condition(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
    ) -> EffectResult | None:
        """
        발동 조건. ``TRUE`` 일 때만 통과한다.

        ``UNKNOWN`` 을 ``TRUE`` 로 접지 않는다 — 모르는 것을 실행으로 바꾸면
        프로젝트 전체의 원칙이 깨진다.
        """
        if definition.activation is None:
            return None
        view = GameStateView.from_state(state, viewer=context.controller)
        verdict = ConditionEvaluator(view).evaluate(
            definition.activation, context.condition_context()
        )
        if verdict.result is ConditionResult.TRUE:
            return None
        if verdict.result is ConditionResult.FALSE:
            return _fail(
                ResolutionStatus.CONDITION_FALSE,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"발동 조건이 거짓입니다: {verdict.description}",
            )
        return _fail(
            ResolutionStatus.CONDITION_UNKNOWN,
            ValidationCode.INFORMATION_UNAVAILABLE,
            f"발동 조건을 판정할 수 없습니다: {verdict.description}",
            missing="; ".join(verdict.unknown_reasons) or None,
        )

    def _plan_operation(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: Operation,
    ) -> "_Step | EffectResult":
        """
        일 하나를 **표에 따라** 계획기에게 넘긴다.

        ``isinstance`` 사슬을 두지 않는다 — 계획과 적용이 서로 다른 것으로
        갈라지면 (한쪽은 클래스, 한쪽은 ``kind``) 새 일을 더할 때 한 곳만
        고쳐도 조용히 지나간다. 표 하나가 두 쪽을 함께 들고 있다
        (Phase 2-V).
        """
        handler = OPERATION_HANDLERS.get(operation.kind)
        if handler is None:
            return _fail(
                ResolutionStatus.UNSUPPORTED_OPERATION,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"이 실행기는 {operation.kind.value} 를 다루지 못합니다 "
                f"({type(operation).__name__}).",
                missing=UNSUPPORTED_REASON.get(
                    operation.kind, f"{operation.kind.value} 실행"
                ),
            )
        return handler.plan(self, state, definition, context, operation)

    # ------------------------------------------------------------------
    # 종류별 계획기 — 표가 부른다
    # ------------------------------------------------------------------
    def _plan_draw(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: DrawOperation,
    ) -> "_Step | EffectResult":
        """
        표는 ``kind`` 로 찾지만 여기서는 :class:`DrawOperation` 의 값을
        읽는다. 그래도 되는 이유는 **조작 스스로가 자기 종류를 제한하기**
        때문이다 — :class:`CardOperation` 은 ``DRAW`` 로 만들어지지 않는다
        (생성 시점에 ``ValueError``). 종류가 곧 부류다.
        """
        if operation.count <= 0:
            # :class:`DrawOperation` 이 생성 시점에 막지만, 그 방어를
            # 우회해서 들어온 값도 조용히 통과시키지 않는다.
            return _fail(
                ResolutionStatus.INVALID_OPERATION,
                ValidationCode.INVALID_AMOUNT,
                f"{operation.count}장 드로우는 의미가 없습니다.",
            )
        player = _resolve_player(operation.who, context)
        available = len(state.player(player).deck)
        if available < operation.count:
            # **뽑기 전에** 센다. 덱이 모자랄 때의 규칙(덱 데스)이 아직
            # 없으므로, 있는 만큼만 뽑아 놓고 성공처럼 끝내지 않는다.
            # ``GameState.draw`` 는 있는 만큼만 옮기고 멈추는 primitive
            # 라서, 그대로 부르면 "3장 드로우" 가 조용히 1장이 된다.
            return _fail(
                ResolutionStatus.INSUFFICIENT_CARDS,
                ValidationCode.INSUFFICIENT_DECK,
                f"덱이 {available}장뿐이라 {operation.count}장을 뽑을 수 "
                "없습니다. 한 장도 뽑지 않습니다.",
                missing="deck-out rule (Phase 2-G)",
            )
        return _Step(operation, amount=operation.count, player=player)

    def _plan_life_change(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: LifeChangeOperation,
    ) -> "_Step | EffectResult":
        return _Step(
            operation,
            amount=operation.delta,
            player=_resolve_player(operation.who, context),
        )

    def _plan_shuffle(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: ShuffleOperation,
    ) -> "_Step | EffectResult":
        """
        섞을 순서를 **계획 단계에서** 정한다 (Phase 2-Z).

        적용 단계에서 난수를 꺼내지 않는 것이 핵심이다. 꺼내면 뒤의 일이
        막혔을 때 난수원만 소비된 채로 남고, 같은 입력을 다시 돌려도 같은
        결과가 나오지 않는다.

        난수원이 없으면 **거절한다.** 조용히 전역 난수로 넘어가면 재현할
        수 없는 판이 만들어진다.
        """
        player = _resolve_player(operation.who, context)
        container = state.player(player).zone(operation.zone)
        cards = tuple(card.instance_id for card in container)
        try:
            outcome = state.randomness.shuffle(cards, RandomPurpose.DECK_SHUFFLE)
        except (RuntimeError, RandomError) as error:
            return _fail(
                ResolutionStatus.UNSUPPORTED_OPERATION,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"섞을 수 없습니다: {error}",
                missing="seeded randomness (GameState.create(seed=...))",
            )
        return _Step(operation, player=player, amount=len(cards), outcome=outcome)

    def _plan_card_operation(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: "CardOperation | MoveOperation",
    ) -> "_Step | EffectResult":
        """
        대상 이름을 실제 카드로 푼다.

        이름이 정의에 없거나, 고르지 않았거나, 판에 없는 카드면 **여기서
        멈춘다.** 적용은 시작도 하지 않는다.
        """
        ref = operation.target_ref
        try:
            spec = definition.target_spec(ref)
        except KeyError:
            return _fail(
                ResolutionStatus.INVALID_CONTEXT,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{operation.kind.value} 가 선언되지 않은 대상 {ref} 를 "
                "가리킵니다.",
            )

        resolved = self._resolve_selection(state, definition, context, operation)
        if isinstance(resolved, EffectResult):
            return resolved
        _, selection = resolved

        if spec is not None and spec.is_random:
            # **다시 판정하지 않는다** (Phase 2-AB). 무작위 선택은 바로 앞
            # 단계에서 후보를 **권위 있게** 세면서 자리 · 주인 · 조건을 이미
            # 확인했다. 여기서 컨트롤러의 관측으로 다시 보면 상대 패의
            # 카드가 "안 보인다" 는 이유로 거절된다 — 아무도 고르지 않은
            # 선택에 고르는 사람의 시야를 요구하는 셈이다.
            pass
        else:
            # **고른 것이 규칙에 맞는지 먼저 본다** (Phase 2-N). 여기가
            # 없으면 자리도 주인도 조건도 맞지 않는 카드가 그대로 실행된다.
            legal = self._check_target(state, spec, selection, context, ref)
            if legal is not None:
                return legal

        instances: list[InstanceId] = []
        owners: list[int] = []
        for instance in selection.chosen:
            card = state.find_instance(instance)
            if card is None:
                return _fail(
                    ResolutionStatus.INVALID_TARGET,
                    ValidationCode.CANDIDATE_NOT_FOUND,
                    f"{instance} 가 이 듀얼에 없습니다.",
                )
            rule = origin_rule(operation.kind)
            if rule is not None and not rule.allows(card.zone):
                # 출발 자리가 어긋났다. **"안 된다" 와 "모른다" 를 나눈다** —
                # 버리기가 패 밖에서 일어나지 않는다는 것은 규칙이고,
                # 필드 밖 파괴는 이 엔진이 아직 안 옮긴 것이다.
                if rule.known:
                    return _fail(
                        ResolutionStatus.INVALID_TARGET,
                        ValidationCode.SOURCE_WRONG_ZONE,
                        f"{instance} 가 패에 없어 버릴 수 없습니다 "
                        f"(현재 {card.zone.value}). {rule.detail}.",
                    )
                return _fail(
                    ResolutionStatus.UNSUPPORTED_OPERATION,
                    ValidationCode.RULE_NOT_IMPLEMENTED,
                    f"{instance} 는 {card.zone.value} 에 있습니다. "
                    f"{rule.detail}.",
                    missing=rule.missing,
                )
            gate = self._check_rule_gate(operation, instance)
            if gate is not None:
                return gate

            instances.append(instance)
            # 주인 결정은 **바꾸기 전에** 끝낸다 (계획 단계).
            if isinstance(operation, MoveOperation):
                # 의미가 없는 이동이므로 표를 볼 수 없다. 조작이 직접 말한다.
                owners.append(card.owner if operation.to_owner else card.controller)
            else:
                owners.append(destination_player(operation.kind, card))

        if not instances:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 에 고른 카드가 없습니다.",
            )
        return _Step(operation, instances=tuple(instances), owners=tuple(owners))

    def _plan_summon_operation(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: SpecialSummonOperation,
    ) -> "_Step | EffectResult":
        """
        고른 몬스터를 어디에 놓을지 **Phase 2-T 의 절차에게 묻는다.**

        자리 찾기 · 빈 칸 찾기는 여기서 다시 하지 않는다 — 플레이어가
        선언한 특수 소환과 **같은 코드**를 쓴다
        (:data:`~engine.special_summon.SPECIAL_SUMMON_PROCEDURE`).

        순서가 규칙이다. 대상이 적법한가(Phase 2-N) → 특수 소환해도
        되는가(관문) → 어디에 놓을 수 있는가. **판에 손대기 전에** 전부
        끝낸다.
        """
        selected = self._resolve_selection(state, definition, context, operation)
        if isinstance(selected, EffectResult):
            return selected
        ref, selection = selected

        legal = self._check_target(state, definition.target_spec(ref), selection, context, ref)
        if legal is not None:
            return legal

        placements: list[SummonPlacement] = []
        for instance in selection.chosen:
            gate = self._check_rule_gate(operation, instance)
            if gate is not None:
                return gate
            try:
                placements.append(
                    SPECIAL_SUMMON_PROCEDURE.plan_for(
                        state, instance, context.controller
                    )
                )
            except SummonError as error:
                # 지시를 수행할 수 없다. **적법성 위반이 아니다** — 자리가
                # 어긋났거나 놓을 칸이 없다는 뜻이고, 판은 그대로다.
                return _fail(
                    ResolutionStatus.INVALID_TARGET,
                    ValidationCode.CANDIDATE_NOT_ELIGIBLE,
                    f"{instance} 를 특수 소환할 수 없습니다: {error}",
                )

        if not placements:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 에 고른 카드가 없습니다.",
            )
        return _Step(
            operation,
            instances=tuple(p.card for p in placements),
            owners=tuple(p.owner for p in placements),
            placements=tuple(placements),
        )

    def _resolve_selection(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: Operation,
    ):
        """
        일이 가리키는 이름과 이번에 골라진 것. 실패하면 :class:`EffectResult`.

        ``_plan_card_operation`` 과 같은 검사를 두 번 적지 않으려고 뽑아냈다.

        **무작위 선택이면 밖에서 받지 않는다** (Phase 2-AB). 고르는 사람이
        없으므로 받을 곳이 없고, 난수원이 정한다.
        """
        ref = operation.target_refs[0]
        try:
            spec = definition.target_spec(ref)
        except KeyError:
            return _fail(
                ResolutionStatus.INVALID_CONTEXT,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{operation.kind.value} 가 선언되지 않은 대상 {ref} 를 "
                "가리킵니다.",
            )
        if spec is not None and spec.is_random:
            return self._roll_selection(state, spec, context, ref)
        selection = context.selection_for(ref)
        if selection is None:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 에 고른 카드가 없습니다.",
            )
        return ref, selection

    def _roll_selection(
        self,
        state: GameState,
        spec,
        context: ResolutionContext,
        ref,
    ):
        """
        후보를 세고, 그중 하나를 **난수원이** 고른다 (Phase 2-AB).

        두 일을 섞지 않는다.

        1. :class:`~engine.cost.resolver.CandidateResolver` 가 후보를 센다.
        2. :class:`~engine.randomness.RandomSource` 가 **자리 번호**를 고른다.

        난수원은 판을 뒤지지 않고 카드를 보지도 않는다 — 몇 개 중 몇
        번째인지만 답한다.

        **아무도 고르지 않으므로 아무도 볼 필요가 없다.** 그래서 후보는
        각 자리의 **주인 시점**으로 센다 (상대 패의 카드는 상대가 안다).
        그렇게 만든 관측은 후보를 세는 데만 쓰이고 밖으로 나가지 않는다 —
        선택되었다는 사실이 카드를 공개하지는 않는다 (Phase 2-AA).

        난수는 **계획 단계의 마지막**에 꺼낸다. 후보가 없거나 모르면 꺼내기
        전에 멈추므로, 실패한 요청이 난수원만 소비하는 일이 없다.
        """
        candidates = self._authoritative_candidates(state, spec, context)
        if isinstance(candidates, EffectResult):
            return candidates

        count = spec.choice.count
        try:
            outcome = state.randomness.choose_many(
                candidates, count, replacement=spec.choice.replacement
            )
        except RandomError as error:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 를 무작위로 고를 수 없습니다: {error}",
            )
        except RuntimeError as error:  # seed 없이 만들어진 판
            return _fail(
                ResolutionStatus.UNSUPPORTED_OPERATION,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{ref} 를 무작위로 고를 수 없습니다: {error}",
                missing="seeded randomness (GameState.create(seed=...))",
            )
        return ref, Selection(chosen=outcome.selected)

    def _authoritative_candidates(self, state: GameState, spec, context):
        """
        무작위 선택의 후보를 **자리마다 그 주인의 눈으로** 센다.

        자리마다 따로 세는 이유가 있다. 한 사람의 관측으로는 상대의 패를
        볼 수 없고, 그렇다고 "못 봤으니 후보가 없다" 로 접으면 모르는 것을
        거짓으로 만든다 (STRUCTURAL-15). 무작위 선택에는 고르는 사람이
        없으므로, 각 자리를 **그 자리의 주인이 아는 만큼** 세는 것이 맞다.

        그래도 **아직 모르는 것은 모른다.** 뒷면 카드의 정의를 읽지 못해
        조건을 판정할 수 없으면 ``undecided`` 로 남고, 그때는 고르지
        않는다 — 후보가 몇 개인지 모르는 채로 무작위를 돌리면 확률이
        틀린다.
        """
        source = spec.choice.source
        owners = (
            (source.owner.resolve(context.condition_context()),)
            if source.owner is not None
            else (0, 1)
        )

        eligible: list[InstanceId] = []
        undecided: list[InstanceId] = []
        reasons: list[str] = []
        unchecked: list[str] = []
        for owner in owners:
            # 그 자리의 주인 시점. 자기 패는 자기가 안다. 덱처럼 주인도
            # 못 보는 자리는 ``looked_at`` 으로 연다 — 자기 자리에만
            # 적용되므로 남의 것은 열리지 않는다 (Phase 2-Y).
            view = GameStateView.from_state(
                state, viewer=owner, looked_at=frozenset(source.zones)
            )
            narrowed = ChoiceSpec(
                source=CandidateSource(
                    zones=source.zones,
                    owner=PlayerRef.CONTROLLER,
                    require=source.require,
                    exclude_source=source.exclude_source,
                ),
                minimum=spec.choice.minimum,
                maximum=spec.choice.maximum,
            )
            found = CandidateResolver(view).resolve(
                narrowed,
                ConditionContext(player=owner, source=context.source),
            )
            eligible.extend(found.eligible)
            undecided.extend(found.undecided)
            reasons.extend(found.reasons)
            unchecked.extend(found.unchecked)

        if undecided or unchecked:
            return _fail(
                ResolutionStatus.UNCHECKED_TARGET,
                ValidationCode.INFORMATION_UNAVAILABLE,
                "후보를 다 세지 못했습니다: "
                + "; ".join(reasons + unchecked),
                missing="; ".join(unchecked) or None,
            )
        return tuple(eligible)

    def _check_target(
        self,
        state: GameState,
        spec,
        selection,
        context: ResolutionContext,
        ref,
    ) -> "EffectResult | None":
        """
        고른 대상이 규칙에 맞는가. 맞으면 ``None``.

        판정은 :class:`~engine.effect.targeting.TargetResolver` 하나가 한다 —
        실행기가 자리와 주인을 다시 따지면 두 벌이 갈린다.

        **``UNKNOWN`` 을 ``INVALID`` 로 접지 않는다.** 가려진 정보 때문에
        판정할 수 없는 것과 규칙상 틀린 것은 다른 사실이고, 어느 쪽이든
        판은 건드리지 않는다.
        """
        # 이 규칙이 **스스로 적어 둔** 자리만 들여다본다 (Phase 2-Y).
        # 규칙이 자기 덱에서 고르라고 했으면 컨트롤러는 자기 덱을 본다 —
        # 룰북이 그렇게 말한다. 남의 자리는 어떤 경우에도 열리지 않는다.
        view = GameStateView.from_state(
            state,
            viewer=context.controller,
            looked_at=spec.looked_at_zones() if spec is not None else None,
        )
        verdict = TargetResolver(view).validate(
            spec, selection, context.condition_context(), ref
        )
        if verdict.permits_selection:
            return None
        if verdict.legality is TargetLegality.ILLEGAL:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                verdict.code,
                f"{ref} 의 대상이 적법하지 않습니다: {verdict.reason}",
            )
        return _fail(
            ResolutionStatus.UNCHECKED_TARGET,
            verdict.code,
            f"{ref} 의 대상이 적법한지 판정할 수 없습니다: {verdict.reason}",
            missing="; ".join(verdict.unchecked) or None,
        )

    def _check_rule_gate(
        self, operation: Operation, instance: InstanceId
    ) -> "EffectResult | None":
        """
        **판정을 받아야만 실행되는 일**의 관문. 통과하면 ``None``.

        ``UNKNOWN`` 을 허가로 바꾸지 않는다 — 내성을 판정할 수 없는데
        파괴하면 내성을 가진 카드가 실제로 파괴된다. 적어 두는 것만으로는
        그것을 막지 못한다 (Phase 2-M 의 STRUCTURAL-47).

        판정을 못 받으면 **판에 손대기 전에** 멈춘다. 이 효과 전체가
        멈추고, 한 장만 파괴되는 부분 적용은 일어나지 않는다 — "내성을 가진
        한 장만 남고 나머지는 파괴된다" 는 규칙을 아직 옮기지 못했으므로,
        안전한 쪽으로 통째로 멈춘다 (STRUCTURAL-49).
        """
        kind = operation.kind
        question = declared_gate_question(operation)

        if is_rule_gated(kind):
            # 종류만으로 언제나 물어지는 관문 (파괴 · 특수 소환).
            if kind is OperationKind.SPECIAL_SUMMON:
                verdict = self._summoning.may_be_special_summoned(instance)
                refusal = f"{instance} 는 특수 소환할 수 없다고 판정되었습니다."
                unknown = f"{instance} 를 특수 소환해도 되는지 판정할 수 없습니다"
            else:
                verdict = self._destruction.may_be_destroyed(instance)
                refusal = f"{instance} 는 파괴되지 않는다고 판정되었습니다."
                unknown = f"{instance} 를 파괴해도 되는지 판정할 수 없습니다"
        elif question is not None:
            # **카드가 선언한** 관문 (Phase 2-X). 선언하지 않은 같은 종류의
            # 일은 여기 오지 않는다 — 원본 스크립트가 묻지 않기 때문이다.
            verdict = ask_movement(self._movement, question, instance)
            word = "묘지로 보낼" if kind is OperationKind.SEND_TO_GRAVE else "버릴"
            refusal = f"{instance} 는 {word} 수 없다고 판정되었습니다."
            unknown = f"{instance} 를 {word} 수 있는지 판정할 수 없습니다"
        else:
            return None

        if verdict is ConditionResult.TRUE:
            return None
        if verdict is ConditionResult.FALSE:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.CANDIDATE_NOT_ELIGIBLE,
                refusal,
            )
        return _fail(
            ResolutionStatus.UNCHECKED_RULES,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            unknown
            + ": "
            + " · ".join(gating_rules(kind))
            + ". 판정할 수 없는 것을 허가로 바꾸지 않습니다.",
            missing=MISSING_GATE[kind],
            unchecked=unchecked_rules(kind),
        )

    # ==================================================================
    # 2단계 — 적용. 기존 primitive 만 부른다.
    # ==================================================================
    def _apply(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        """
        일 하나를 **표에 따라** 수행기에게 넘긴다.

        계획과 **같은 표**를 쓴다 — 두 dispatch 가 서로 다른 것으로 갈라지면
        (계획은 클래스로, 적용은 ``kind`` 로) 새 일을 더할 때 한 곳만 고쳐도
        조용히 지나간다 (Phase 2-V).
        """
        handler = OPERATION_HANDLERS.get(step.operation.kind)
        if handler is None:  # pragma: no cover - 계획 단계가 막는다
            raise EffectExecutionError(
                f"{step.operation.kind.value} 를 수행할 수 없는데 계획이 "
                "통과했습니다."
            )
        return handler.apply(self, state, step)

    # ------------------------------------------------------------------
    # 종류별 수행기 — 표가 부른다. **기존 primitive 만 부른다.**
    # ------------------------------------------------------------------
    def _apply_draw(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        assert step.player is not None and step.amount is not None
        drawn = state.draw(step.player, step.amount)
        if len(drawn) != step.amount:  # pragma: no cover - 계획이 막는다
            raise EffectExecutionError(
                f"{step.amount}장을 뽑기로 했는데 {len(drawn)}장만 옮겨졌습니다."
            )
        record = AppliedOperation(
            kind=OperationKind.DRAW,
            reason_names=step.operation.reason_names,
            instances=tuple(card.instance_id for card in drawn),
            amount=step.amount,
            player=step.player,
        )
        changes = tuple(
            CardDrawn(player=step.player, card=card.instance_id) for card in drawn
        )
        return record, changes

    def _apply_life_change(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        assert step.player is not None and step.amount is not None
        player = state.player(step.player)
        before = player.life_points
        after = player.change_life(step.amount)
        if after == before:
            # 실제로 달라진 것이 없으면 변화도 없다 (0 에서 더 깎는 경우).
            return step.record(), ()
        return step.record(), (
            LifeChanged(player=step.player, before=before, after=after),
        )

    def _apply_special_summon(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        # 놓는 일은 **Phase 2-T 의 절차**가 한다. 여기서 ``state.move`` 를
        # 직접 부르면 칸과 표시 형식이 두 곳에서 정해진다.
        changes = []
        for placement in step.placements:
            SPECIAL_SUMMON_PROCEDURE.place(state, placement)
            changes.append(placement.to_delta(SPECIAL_SUMMON_PROCEDURE.summon))
        return step.record(), tuple(changes)

    def _apply_shuffle(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        """
        계획이 정한 순서를 **그대로 적용한다.** 여기서 난수를 꺼내지 않는다.
        """
        operation = step.operation
        outcome = step.outcome
        assert outcome is not None and step.player is not None  # 계획이 정했다
        container = state.player(step.player).zone(operation.zone)

        current = [card.instance_id for card in container]
        if current != list(outcome.candidates):
            # pragma: no cover - 계획과 적용 사이에 판이 바뀌면 안 된다
            raise EffectExecutionError(
                "섞기를 계획한 뒤 존의 내용이 달라졌습니다. 계획과 적용 "
                "사이에 판이 바뀌면 재현이 깨집니다."
            )
        place = {instance: index for index, instance in enumerate(current)}
        container.reorder(tuple(place[i] for i in outcome.selected))

        changed = ZoneShuffled(
            player=step.player,
            zone=operation.zone,
            size=outcome.size,
            draw=outcome.draw,
        )
        return step.record(), (changed,)

    def _apply_card_movement(
        self, state: GameState, step: _Step
    ) -> "tuple[AppliedOperation, tuple[StateDelta, ...]]":
        operation = step.operation
        # ``MOVE`` 는 목적지를 **조작이 들고 있다.** 나머지는 의미가 목적지를
        # 정한다 (파괴 → 묘지). 그 차이가 이 한 줄이다.
        destination = (
            operation.destination
            if isinstance(operation, MoveOperation)
            else DESTINATION[operation.kind]
        )
        changes = []
        for instance, to_player in zip(step.instances, step.owners):
            card = state.find_instance(instance)
            assert card is not None  # 계획 단계가 확인했다
            # 출발지는 **옮기기 전에** 읽어야 한다.
            from_player, from_zone = card.controller, card.zone
            # 계획 단계가 정한 주인에게 **명시적으로** 보낸다.
            # ``GameState.move`` 의 기본값(컨트롤러)에 절대 기대지 않는다 —
            # 기대면 컨트롤을 빼앗긴 카드가 빼앗은 쪽의 묘지로 간다.
            state.move(card, destination, to_player=to_player)
            if card.zone is not destination or card.controller != to_player:
                # 존과 인스턴스가 서로 다른 말을 하는 상태로 계속 가지 않는다.
                raise EffectExecutionError(
                    f"{instance} 를 P{to_player} 의 {destination.value} 로 "
                    f"보냈는데 {card.zone.value}/P{card.controller} 에 있습니다."
                )
            changes.append(
                ZoneMoved(
                    movement=operation.kind,
                    card=instance,
                    source_player=from_player,
                    source_zone=from_zone,
                    destination_player=to_player,
                    destination_zone=destination,
                )
            )
        return step.record(), tuple(changes)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        journal = "없음" if self._journal is None else f"{len(self._journal)}건"
        return f"<EffectExecutor lookup={self._lookup!r} journal={journal}>"


@dataclass(frozen=True, slots=True)
class OperationHandler:
    """
    한 종류의 일을 **계획하고 수행하는 한 쌍.**

    둘을 한 값에 묶는 이유는 하나다 — 따로 두면 계획만 더하고 수행을
    빠뜨릴 수 있고, 그 실수는 실행 중에야 드러난다. 여기에 줄을 더하는 것이
    "이 일을 할 줄 안다" 는 **유일한** 선언이다 (:data:`SUPPORTED` 도 이
    표에서 세운다).
    """

    plan: Callable[
        [
            "EffectExecutor",
            GameState,
            EffectDefinition,
            ResolutionContext,
            Operation,
        ],
        "_Step | EffectResult",
    ]
    apply: Callable[
        ["EffectExecutor", GameState, "_Step"],
        "tuple[AppliedOperation, tuple[StateDelta, ...]]",
    ]
    note: str = ""
    """이 일이 어떤 계층을 쓰는가. 사람이 읽는 설명이다."""


#: 종류 → (계획기, 수행기). **이 실행기가 아는 것의 전부다.**
#:
#: 거대한 ``if/elif`` 하나로 모든 일을 처리하지 않는다 (Phase 2-V §3).
#: 더 중요한 것은 **dispatch 가 하나**라는 점이다 — 예전에는 계획이
#: ``isinstance`` 로, 적용이 ``kind`` 로 갈라져 있어서 새 일을 더할 때 한
#: 곳만 고쳐도 조용히 지나갔다.
OPERATION_HANDLERS: dict[OperationKind, OperationHandler] = {
    OperationKind.DRAW: OperationHandler(
        EffectExecutor._plan_draw,
        EffectExecutor._apply_draw,
        "GameState.draw",
    ),
    OperationKind.CHANGE_LIFE: OperationHandler(
        EffectExecutor._plan_life_change,
        EffectExecutor._apply_life_change,
        "PlayerState.change_life",
    ),
    OperationKind.SPECIAL_SUMMON: OperationHandler(
        EffectExecutor._plan_summon_operation,
        EffectExecutor._apply_special_summon,
        "SummonProcedure (Phase 2-T)",
    ),
    OperationKind.SHUFFLE: OperationHandler(
        EffectExecutor._plan_shuffle,
        EffectExecutor._apply_shuffle,
        "RandomSource.shuffle + ZoneContainer.reorder (Phase 2-Z)",
    ),
    OperationKind.MOVE: OperationHandler(
        EffectExecutor._plan_card_operation,
        EffectExecutor._apply_card_movement,
        "GameState.move — 의미 없는 이동 (Phase 2-L)",
    ),
    **{
        kind: OperationHandler(
            EffectExecutor._plan_card_operation,
            EffectExecutor._apply_card_movement,
            f"GameState.move → {zone.value} (의미: {kind.value})",
        )
        for kind, zone in DESTINATION.items()
    },
}

SUPPORTED = frozenset(OPERATION_HANDLERS)


def _fail(
    status: ResolutionStatus,
    code: ValidationCode,
    reason: str,
    missing: str | None = None,
    unchecked: tuple[str, ...] = (),
) -> EffectResult:
    return EffectResult(status, code, reason, missing, unchecked_rules=unchecked)


def _resolve_player(who, context: ResolutionContext) -> int:
    """``PlayerRef`` 를 이번 해결의 실제 플레이어 번호로 바꾼다."""
    return who.resolve(context.condition_context())


__all__ = [
    "EffectExecutor",
    "EffectExecutionError",
    "EffectImplementationRegistry",
    "DestinationOwner",
    "DESTINATION",
    "DESTINATION_OWNER",
    "destination_player",
    "OperationHandler",
    "OPERATION_HANDLERS",
    "SUPPORTED",
    "UNSUPPORTED_REASON",
]
