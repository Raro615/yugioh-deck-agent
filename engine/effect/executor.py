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

관측과 변경을 섞지 않는다
-------------------------
조건 평가는 :class:`~engine.game_state_view.GameStateView` 로 하고, 변경은
``GameState`` 의 기존 primitive 로만 한다. 관측을 통해 판을 고치지 않는다.

권위는 그대로다
---------------
``TEXT_DERIVED`` 는 구현이 등록되어 있어도 실행하지 않는다. ``LUA_VERIFIED``
라고 해서 자동으로 실행되지도 않는다 — 등록된 구현이 있어야 한다 (ADR-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import ConditionEvaluator, ConditionResult
from engine.effect.definition import (
    EffectDefinition,
    EffectImplementationLookup,
    EmptyImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.operation import (
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    Operation,
    OperationKind,
)
from engine.effect.resolution import (
    AppliedOperation,
    EffectResult,
    ResolutionContext,
    ResolutionStatus,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Zone

#: 카드를 다루는 일이 카드를 **어디로** 보내는가.
#:
#: 목적지가 같다고 해서 같은 일이 아니다 — 파괴 · 묘지로 보내기 · 릴리스 ·
#: 버리기가 전부 묘지로 가지만 서로 다른 사건이고, 그 구분은
#: ``AppliedOperation.kind`` 와 ``reason_names`` 가 지킨다 (ADR-002).
DESTINATION: dict[OperationKind, Zone] = {
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
#: 이미 정해진 사실이다. 실행하지 않는 이유는 목적지가 아니라 **파괴
#: 의미**(내성 · 대체 · 트리거)가 없기 때문이다.
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
    rule = DESTINATION_OWNER[kind]
    return card.owner if rule is DestinationOwner.OWNER else card.controller


#: 이 실행기가 다룰 수 있는 일.
#:
#: ``DESTROY`` 가 **없다.** 유희왕의 "파괴" 는 묘지로 보내는 것과 다르고
#: (파괴 내성 · 파괴 대체 · "파괴되었을 때" 트리거), 그 계층이 아직 없다.
#: 목적지가 묘지라는 이유로 구현했다고 말하지 않는다.
SUPPORTED: frozenset[OperationKind] = frozenset(DESTINATION) | {
    OperationKind.DRAW,
    OperationKind.CHANGE_LIFE,
}

#: 지원하지 않는 일과, 무엇이 없어서 못 하는가.
UNSUPPORTED_REASON: dict[OperationKind, str] = {
    OperationKind.DESTROY: (
        "destruction semantics — 파괴 내성 · 파괴 대체 · 파괴 트리거 (Phase 2-E~)"
    ),
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

    __slots__ = ("_lookup",)

    def __init__(self, lookup: EffectImplementationLookup | None = None):
        self._lookup = lookup if lookup is not None else EmptyImplementationLookup()

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

        try:
            applied = tuple(self._apply(state, step) for step in plan)
        except Exception as error:  # pragma: no cover - 일어나서는 안 된다
            return EffectResult(
                ResolutionStatus.EXECUTION_ERROR,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"적용 중 오류가 났습니다: {error}. 판이 반쯤 바뀌어 있을 수 "
                "있습니다.",
            )

        return EffectResult(
            ResolutionStatus.RESOLVED,
            ValidationCode.OK,
            f"{definition.effect_ref} 를 적용했습니다 ({len(applied)}건).",
            applied=applied,
        )

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
        if isinstance(operation, DrawOperation):
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

        if isinstance(operation, LifeChangeOperation):
            return _Step(
                operation,
                amount=operation.delta,
                player=_resolve_player(operation.who, context),
            )

        if isinstance(operation, CardOperation):
            return self._plan_card_operation(state, definition, context, operation)

        return _fail(
            ResolutionStatus.UNSUPPORTED_OPERATION,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"알 수 없는 일입니다: {type(operation).__name__}",
        )

    def _plan_card_operation(
        self,
        state: GameState,
        definition: EffectDefinition,
        context: ResolutionContext,
        operation: CardOperation,
    ) -> "_Step | EffectResult":
        """
        대상 이름을 실제 카드로 푼다.

        이름이 정의에 없거나, 고르지 않았거나, 판에 없는 카드면 **여기서
        멈춘다.** 적용은 시작도 하지 않는다.
        """
        ref = operation.target_ref
        try:
            definition.target_spec(ref)
        except KeyError:
            return _fail(
                ResolutionStatus.INVALID_CONTEXT,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{operation.kind.value} 가 선언되지 않은 대상 {ref} 를 "
                "가리킵니다.",
            )

        selection = context.selection_for(ref)
        if selection is None:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 에 고른 카드가 없습니다.",
            )

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
            if operation.kind is OperationKind.DISCARD and card.zone is not Zone.HAND:
                # 버리기는 패에서만 일어난다. 필드의 카드를 "버렸다" 고
                # 기록하면 트리거 계층이 틀린 사건을 보게 된다.
                return _fail(
                    ResolutionStatus.INVALID_TARGET,
                    ValidationCode.SOURCE_WRONG_ZONE,
                    f"{instance} 가 패에 없어 버릴 수 없습니다 "
                    f"(현재 {card.zone.value}).",
                )
            instances.append(instance)
            # 주인 결정은 **바꾸기 전에** 끝낸다 (계획 단계).
            owners.append(destination_player(operation.kind, card))

        if not instances:
            return _fail(
                ResolutionStatus.INVALID_TARGET,
                ValidationCode.TOO_FEW_SELECTED,
                f"{ref} 에 고른 카드가 없습니다.",
            )
        return _Step(operation, instances=tuple(instances), owners=tuple(owners))

    # ==================================================================
    # 2단계 — 적용. 기존 primitive 만 부른다.
    # ==================================================================
    def _apply(self, state: GameState, step: _Step) -> AppliedOperation:
        operation = step.operation
        if operation.kind is OperationKind.DRAW:
            assert step.player is not None and step.amount is not None
            drawn = state.draw(step.player, step.amount)
            return AppliedOperation(
                kind=OperationKind.DRAW,
                reason_names=operation.reason_names,
                instances=tuple(card.instance_id for card in drawn),
                amount=step.amount,
                player=step.player,
            )

        if operation.kind is OperationKind.CHANGE_LIFE:
            assert step.player is not None and step.amount is not None
            state.player(step.player).change_life(step.amount)
            return step.record()

        destination = DESTINATION[operation.kind]
        for instance, to_player in zip(step.instances, step.owners):
            card = state.find_instance(instance)
            assert card is not None  # 계획 단계가 확인했다
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
        return step.record()

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EffectExecutor lookup={self._lookup!r}>"


def _fail(
    status: ResolutionStatus,
    code: ValidationCode,
    reason: str,
    missing: str | None = None,
) -> EffectResult:
    return EffectResult(status, code, reason, missing)


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
    "SUPPORTED",
    "UNSUPPORTED_REASON",
]
