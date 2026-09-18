"""
CostPayer — 비용이 **실제로 판을 바꾸는 유일한 문**.

    CostGroup + PaymentContext + GameState
        ↓  CostPayer.pay()
    GameState 변경  +  CostPaymentResult(payments, deltas)
        ↓
    EventJournal (COST_PAYMENT)

세 결과를 구분한다
------------------
=========================  ==========================================
``ValidationResult``        치를 수 **있는가**
``CostPaymentResult``       실제로 **치렀는가**
``EffectResult``            효과를 실제로 **해결했는가**
=========================  ==========================================

셋을 합치지 않는다. 합치면 "낼 수 있다" 가 "냈다" 로 읽히는 길이 생긴다.

비용과 효과는 다른 사건이다
---------------------------
"이 카드를 **버리고** 발동한다" 의 버리기는 **비용**이고, 해결 중의
"카드 1장을 묘지로 보낸다" 는 **효과**다. 둘 다 카드가 묘지로 가지만 서로
다른 사건이고, 그 구분은 :class:`~engine.effect.journal.EventKind` 와
``CostSemantics`` / ``OperationKind`` 가 지킨다.

왜 ``engine/cost/`` 안이 아닌가
-------------------------------
지불은 **변경**이고, 변경을 적으려면 ``engine.effect.delta`` 와
``engine.effect.journal`` 이 필요하다. 그런데 ``engine.effect`` 는
``engine.cost`` 를 이미 읽는다 (``TargetSpec`` 이 ``ChoiceSpec`` 을 쓴다).
지불을 ``engine/cost/`` 안에 넣으면 두 패키지가 서로를 읽게 되므로, 둘
**위에** 둔다. ``engine/validation.py`` 를 따로 뺀 것과 같은 이유다.

먼저 다 따져보고, 그 다음에 낸다
--------------------------------
:meth:`CostPayer.pay` 는 두 단계다.

1. **preflight** — 지원 여부 · 치를 수 있는가 · 고른 것이 맞는가 · 고른
   카드가 실제로 그 자리에 있는가를 **묶음 전체에 대해** 확인한다. 판을
   읽기만 한다.
2. **지불** — 확정된 것을 순서대로 수행한다.

``CostGroup`` 은 AND 관계다. 앞의 비용을 내고 뒤에서 막히면 낸 것이 그냥
사라진다. 그래서 하나라도 걸리면 **아무것도 내지 않는다.**

되돌리기는 없다 (ADR-008). 그래서 되돌릴 일이 생기지 않도록 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import ConditionContext
from engine.cost import (
    CardCost,
    Cost,
    CostGroup,
    CostPayment,
    CostSemantics,
    CostValidator,
    LifeCost,
    Selection,
    SelectionValidator,
    UnimplementedCost,
)
from engine.effect.delta import LifeChanged, StateDelta, ZoneMoved
from engine.effect.executor import DESTINATION, destination_player
from engine.effect.journal import CostPaymentEvent, EventJournal
from engine.effect.operation import OperationKind
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Zone

#: 비용 의미 → 그 지불이 판에 남기는 **일**.
#:
#: 이 표가 있어서 비용으로 버린 카드와 효과로 묘지에 보낸 카드가 기록에서
#: 갈린다. 목적지는 둘 다 묘지다 (ADR-002).
COST_OPERATION: dict[CostSemantics, OperationKind] = {
    CostSemantics.DISCARD: OperationKind.DISCARD,
    CostSemantics.RELEASE: OperationKind.RELEASE,
}

#: 이번 단계가 실제로 치를 수 있는 비용.
#:
#: 나머지는 **지어내지 않고** ``UNSUPPORTED_COST`` 로 돌려준다.
SUPPORTED_COSTS: frozenset[CostSemantics] = frozenset(COST_OPERATION) | {
    CostSemantics.PAY_LIFE
}

#: 지원하지 않는 비용과, 무엇이 없어서 못 하는가.
UNSUPPORTED_REASON: dict[CostSemantics, str] = {
    CostSemantics.BANISH: "비용으로서의 제외 (Phase 2-F~)",
    CostSemantics.SEND_TO_GRAVE: "비용으로서의 묘지送り — 덱에서 보내는 경우 포함",
    CostSemantics.DETACH: "엑시즈 소재 모델 (Phase 3~)",
    CostSemantics.UNKNOWN: "표현되지 않은 비용",
}


class PaymentError(RuntimeError):
    """지불 중에 판이 예상과 다르게 움직였다. 계속 가지 않고 멈춘다."""


class PaymentStatus(str, Enum):
    """
    지불 시도의 결과.

    **``PAID`` 하나만 판을 바꾼다.** 나머지는 전부 "아무것도 내지 않았다" 를
    뜻하고, 이유만 다르다.
    """

    PAID = "paid"
    """치렀다. 빈 묶음이면 낼 것이 없어 치른 것으로 본다 — 변화는 없다."""
    CANNOT_PAY = "cannot_pay"
    """
    **확실히** 치를 수 없다. 라이프가 모자라거나 후보가 없다. 판은 그대로다.
    """
    UNKNOWN = "unknown"
    """
    치를 수 있는지 **판정할 수 없다.** 판은 그대로다.

    ``CANNOT_PAY`` 와 합치지 않는다 — "못 낸다" 와 "모르겠다" 는 다른
    답이고, 모르는 것을 "일단 지불" 로 바꾸면 프로젝트 전체의 원칙이 깨진다.
    """
    INVALID_SELECTION = "invalid_selection"
    """고른 것이 요구와 맞지 않는다. 판은 그대로다."""
    UNSUPPORTED_COST = "unsupported_cost"
    """이 지불기가 다룰 수 없는 비용이다. 판은 그대로다."""
    EXECUTION_ERROR = "execution_error"
    """
    지불 중에 예상 못 한 오류가 났다.

    **이때만 판이 반쯤 바뀌어 있을 수 있다.** preflight 가 모든 것을
    확인하므로 일어나서는 안 되는 경우이고, 일어났다면 결함이다.
    """


@dataclass(frozen=True, slots=True)
class CostSelection:
    """
    **몇 번째 비용**에 무엇을 골랐는가.

    ``CostGroup.costs`` 안의 자리 번호로 잇는다. 고를 것이 있는 비용만
    순서대로 세는 방식을 쓰지 않는다 — 그러면 중간에 비용 하나가 끼거나
    빠질 때 조용히 다른 비용에 붙는다. 대상 계층이 ``TargetRef`` 라는
    이름으로 잇는 것과 같은 이유다.
    """

    index: int
    selection: Selection

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"비용 자리 번호는 0 이상입니다: {self.index}")

    def canonical_state(self) -> tuple:
        return (self.index, self.selection.canonical_state())

    def to_dict(self) -> dict:
        return {"index": self.index, "selection": self.selection.to_dict()}


@dataclass(frozen=True, slots=True)
class PaymentContext:
    """
    비용 하나를 치를 때의 문맥. **불변**이고 값 타입만 담는다.

    ``CardInstance`` 나 ``GameState`` 를 담지 않는다 — 담으면 문맥이 특정
    판에 묶이고 직렬화도 replay 도 불가능해진다
    (``ResolutionContext`` 와 같은 태도다).
    """

    payer: int
    """비용을 치르는 플레이어. 관측의 시점(viewer)도 이 사람이다."""
    selections: tuple[CostSelection, ...] = ()
    effect_ref: EffectRef | None = None
    """어느 효과의 비용인가. 아직 잇지 않았으면 ``None`` (ActionExecutor 는 다음 단계)."""
    source: InstanceId | None = None

    def __post_init__(self) -> None:
        if self.payer not in (0, 1):
            raise ValueError(f"payer 는 0 또는 1 입니다: {self.payer}")
        if not isinstance(self.selections, tuple):
            raise TypeError("selections 는 tuple 이어야 합니다 — 문맥은 불변입니다.")
        seen: set[int] = set()
        for chosen in self.selections:
            if chosen.index in seen:
                raise ValueError(f"{chosen.index}번 비용에 선택이 두 번 들어왔습니다.")
            seen.add(chosen.index)

    def selection_for(self, index: int) -> Selection | None:
        """
        그 비용에 고른 것. **아직 고르지 않았으면 ``None``.**

        빈 :class:`~engine.cost.Selection` 과 ``None`` 은 다르다 — 전자는
        "고른 결과가 없음", 후자는 "아직 고르지 않음" 이다.
        """
        for chosen in self.selections:
            if chosen.index == index:
                return chosen.selection
        return None

    def condition_context(self) -> ConditionContext:
        """비용 검증 계층으로 넘길 문맥."""
        return ConditionContext(
            player=self.payer, source=self.source, effect_ref=self.effect_ref
        )

    def canonical_state(self) -> tuple:
        return (
            self.payer,
            tuple(s.canonical_state() for s in self.selections),
            (self.effect_ref.card_id, self.effect_ref.ordinal)
            if self.effect_ref is not None
            else None,
            self.source.value if self.source is not None else None,
        )


@dataclass(frozen=True, slots=True)
class CostPaymentResult:
    """
    지불 시도의 결과. **불변**이다.

    :attr:`paid` 는 "치렀는가", :attr:`changed_state` 는 "판이 달라졌는가"
    다. 빈 묶음은 치렀지만 달라지지 않는다.
    """

    status: PaymentStatus
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    missing: str | None = None
    """무엇이 없어서 치르지 못했는가."""
    payments: tuple[CostPayment, ...] = ()
    """실제로 낸 것들. 비용 순서대로다. 실패하면 비어 있다."""
    deltas: tuple[StateDelta, ...] = ()
    """그 지불로 판이 어떻게 달라졌는가. 실패하면 비어 있다."""
    notes: tuple[str, ...] = ()
    """왜 판정할 수 없었는가 등, 검증 계층이 남긴 설명."""

    def __post_init__(self) -> None:
        if self.status is not PaymentStatus.PAID and (self.deltas or self.payments):
            raise ValueError(
                f"{self.status.value} 인데 지불 기록이 있습니다. 치르지 못한 "
                "시도는 판을 바꾸지 않습니다."
            )

    @property
    def paid(self) -> bool:
        return self.status is PaymentStatus.PAID

    @property
    def changed_state(self) -> bool:
        return bool(self.deltas)

    def __bool__(self) -> bool:
        raise TypeError(
            "CostPaymentResult 를 참/거짓으로 쓸 수 없습니다. 치르지 못한 "
            "것이 조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`result.paid` 로 비교하세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.code.value,
            self.reason,
            self.missing,
            tuple(p.canonical_state() for p in self.payments),
            tuple(d.canonical_state() for d in self.deltas),
            self.notes,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.missing is not None:
            data["missing"] = self.missing
        if self.payments:
            data["payments"] = [p.to_dict() for p in self.payments]
        if self.deltas:
            data["deltas"] = [d.to_dict() for d in self.deltas]
        if self.notes:
            data["notes"] = list(self.notes)
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.status.value}[{self.code.value}]: {self.reason}"


@dataclass(frozen=True, slots=True)
class _CardStep:
    """preflight 가 확정한 카드 비용 하나. 카드마다 목적지의 주인까지 정해 둔다."""

    semantics: CostSemantics
    instances: tuple[InstanceId, ...]
    owners: tuple[int, ...]
    player: int


@dataclass(frozen=True, slots=True)
class _LifeStep:
    """preflight 가 확정한 라이프 지불 하나."""

    amount: int
    player: int


class CostPayer:
    """
    비용을 실제로 치른다. **비용이 판을 바꾸는 공식 진입점이다.**

    ``Cost`` · ``ChoiceSpec`` · ``Selection`` 은 어느 것도 판을 바꾸지
    않는다. 바꾸는 것은 이 클래스뿐이다.
    """

    __slots__ = ("_journal",)

    def __init__(self, journal: EventJournal | None = None):
        # 기록은 **선택**이다. 없으면 아무것도 적지 않고, 있어도 판정은
        # 달라지지 않는다 — 기록이 판정에 끼어들면 기록이 아니다.
        self._journal = journal

    @property
    def journal(self) -> EventJournal | None:
        return self._journal

    # ==================================================================
    # 진입점
    # ==================================================================
    def pay(
        self, state: GameState, group: CostGroup, context: PaymentContext
    ) -> CostPaymentResult:
        """
        묶음 전체를 치른다.

        ``state`` 는 **바뀔 수 있다.** 다만 :attr:`PaymentStatus.PAID` 를
        돌려줄 때만 그렇다 — 그 밖의 모든 결과에서는 한 글자도 바뀌지 않는다
        (:attr:`PaymentStatus.EXECUTION_ERROR` 제외, 설명 참고).
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "CostPayer 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 지불할 수 없습니다."
            )
        if group.is_free:
            return CostPaymentResult(
                PaymentStatus.PAID, ValidationCode.OK, "치를 비용이 없습니다."
            )

        plan = self._preflight(state, group, context)
        if isinstance(plan, CostPaymentResult):
            return plan  # preflight 실패 — 판은 그대로다

        payments: list[CostPayment] = []
        deltas: list[StateDelta] = []
        try:
            for step in plan:
                receipt, changes = self._apply(state, step)
                payments.append(receipt)
                deltas.extend(changes)
        except Exception as error:  # pragma: no cover - 일어나서는 안 된다
            # 반쪽짜리 기록은 없는 것보다 나쁘다 — 그것을 근거로 되감으면
            # 틀린 판이 된다.
            return CostPaymentResult(
                PaymentStatus.EXECUTION_ERROR,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"지불 중 오류가 났습니다: {error}. 판이 반쯤 바뀌어 있을 수 "
                "있습니다.",
            )

        result = CostPaymentResult(
            PaymentStatus.PAID,
            ValidationCode.OK,
            f"비용 {len(payments)}건을 치렀습니다.",
            payments=tuple(payments),
            deltas=tuple(deltas),
        )
        if self._journal is not None and result.deltas:
            self._journal.record_payment(
                actor=context.payer,
                payments=result.payments,
                deltas=result.deltas,
                effect_ref=context.effect_ref,
                source=context.source,
            )
        return result

    # ==================================================================
    # 1단계 — preflight. 판을 읽기만 한다.
    # ==================================================================
    def _preflight(
        self, state: GameState, group: CostGroup, context: PaymentContext
    ) -> "list[_CardStep | _LifeStep] | CostPaymentResult":
        """
        **묶음 전체**를 먼저 확인한다. 하나라도 걸리면 아무것도 내지 않는다.

        관측으로 검증한다 — 상대의 가려진 카드를 비용으로 고르면 "안 된다"
        가 아니라 **"모르겠다"** 가 나오고, 어느 쪽이든 지불은 하지 않는다.
        """
        view = GameStateView.from_state(state, viewer=context.payer)
        condition_context = context.condition_context()
        validator = CostValidator(view)
        selections = SelectionValidator(view)

        steps: "list[_CardStep | _LifeStep]" = []
        for index, cost in enumerate(group.costs):
            unsupported = self._check_supported(cost)
            if unsupported is not None:
                return unsupported

            verdict = validator.validate(cost, condition_context)
            if verdict.validity is ActionValidity.INVALID:
                return CostPaymentResult(
                    PaymentStatus.CANNOT_PAY, verdict.code, verdict.reason
                )
            if verdict.validity is ActionValidity.UNKNOWN:
                return CostPaymentResult(
                    PaymentStatus.UNKNOWN,
                    verdict.code,
                    verdict.reason,
                    missing=verdict.missing_rule,
                    notes=verdict.notes,
                )

            if isinstance(cost, LifeCost):
                steps.append(
                    _LifeStep(
                        amount=cost.amount,
                        player=cost.who.resolve(condition_context),
                    )
                )
                continue

            assert isinstance(cost, CardCost)  # 지원 검사가 나머지를 걸렀다
            step = self._plan_card_cost(
                state, cost, index, context, condition_context, selections
            )
            if isinstance(step, CostPaymentResult):
                return step
            steps.append(step)
        return steps

    def _check_supported(self, cost: Cost) -> CostPaymentResult | None:
        """이 지불기가 다룰 수 있는 비용인가. 아니면 **지어내지 않는다.**"""
        if isinstance(cost, UnimplementedCost):
            return CostPaymentResult(
                PaymentStatus.UNSUPPORTED_COST,
                ValidationCode.COST_NOT_IMPLEMENTED,
                f"이 비용을 표현할 수 없습니다: {cost.rule}",
                missing=cost.rule,
            )
        if not isinstance(cost, (CardCost, LifeCost)):
            return CostPaymentResult(
                PaymentStatus.UNSUPPORTED_COST,
                ValidationCode.COST_NOT_IMPLEMENTED,
                f"알 수 없는 비용 종류입니다: {type(cost).__name__}",
            )
        if cost.semantics in SUPPORTED_COSTS:
            return None
        return CostPaymentResult(
            PaymentStatus.UNSUPPORTED_COST,
            ValidationCode.COST_NOT_IMPLEMENTED,
            f"이 지불기는 {cost.semantics.value} 를 치르지 못합니다.",
            missing=UNSUPPORTED_REASON.get(
                cost.semantics, f"{cost.semantics.value} 지불"
            ),
        )

    def _plan_card_cost(
        self,
        state: GameState,
        cost: CardCost,
        index: int,
        context: PaymentContext,
        condition_context: ConditionContext,
        selections: SelectionValidator,
    ) -> "_CardStep | CostPaymentResult":
        """고른 카드를 실제 카드로 풀고, 카드마다 목적지의 주인을 정한다."""
        spec = cost.choice_spec()
        selection = context.selection_for(index)
        if selection is None:
            return CostPaymentResult(
                PaymentStatus.INVALID_SELECTION,
                ValidationCode.TOO_FEW_SELECTED,
                f"{index}번 비용({cost.describe_ko()})에 고른 카드가 없습니다.",
            )

        verdict = selections.validate(spec, selection, condition_context)
        if verdict.validity is ActionValidity.INVALID:
            return CostPaymentResult(
                PaymentStatus.INVALID_SELECTION, verdict.code, verdict.reason
            )
        if verdict.validity is ActionValidity.UNKNOWN:
            return CostPaymentResult(
                PaymentStatus.UNKNOWN,
                verdict.code,
                verdict.reason,
                missing=verdict.missing_rule,
                notes=verdict.notes,
            )

        operation = COST_OPERATION[cost.semantics]
        instances: list[InstanceId] = []
        owners: list[int] = []
        for instance in selection.chosen:
            card = state.find_instance(instance)
            if card is None:  # pragma: no cover - 관측 검증이 먼저 막는다
                return CostPaymentResult(
                    PaymentStatus.INVALID_SELECTION,
                    ValidationCode.CANDIDATE_NOT_FOUND,
                    f"{instance} 가 이 듀얼에 없습니다.",
                )
            if card.zone not in cost.zones:
                # 관측과 판이 어긋난 경우. 조용히 옮기지 않는다 — 패에서
                # 버려야 할 카드를 필드에서 "버렸다" 고 기록하면 트리거
                # 계층이 틀린 사건을 보게 된다.
                return CostPaymentResult(
                    PaymentStatus.INVALID_SELECTION,
                    ValidationCode.SOURCE_WRONG_ZONE,
                    f"{instance} 가 {card.zone.value} 에 있어 "
                    f"{cost.describe_ko()} 의 비용이 될 수 없습니다.",
                )
            instances.append(instance)
            # 주인 결정은 **바꾸기 전에** 끝낸다. 효과 실행기와 같은 표를
            # 쓰므로 비용과 효과가 목적지에서 갈리지 않는다.
            owners.append(destination_player(operation, card))

        return _CardStep(
            semantics=cost.semantics,
            instances=tuple(instances),
            owners=tuple(owners),
            player=cost.who.resolve(condition_context),
        )

    # ==================================================================
    # 2단계 — 지불. 기존 primitive 만 부른다.
    # ==================================================================
    def _apply(
        self, state: GameState, step: "_CardStep | _LifeStep"
    ) -> "tuple[CostPayment, tuple[StateDelta, ...]]":
        if isinstance(step, _LifeStep):
            player = state.player(step.player)
            before = player.life_points
            after = player.change_life(-step.amount)
            if after != before - step.amount:  # pragma: no cover - preflight 가 막는다
                raise PaymentError(
                    f"라이프 {step.amount} 를 지불하려 했는데 "
                    f"{before} → {after} 로 바뀌었습니다."
                )
            receipt = CostPayment(
                CostSemantics.PAY_LIFE, amount=step.amount, player=step.player
            )
            return receipt, (
                LifeChanged(player=step.player, before=before, after=after),
            )

        operation = COST_OPERATION[step.semantics]
        destination: Zone = DESTINATION[operation]
        changes: list[StateDelta] = []
        for instance, to_player in zip(step.instances, step.owners):
            card = state.find_instance(instance)
            assert card is not None  # preflight 가 확인했다
            from_player, from_zone = card.controller, card.zone
            # 계획 단계가 정한 **주인**에게 명시적으로 보낸다.
            state.move(card, destination, to_player=to_player)
            if card.zone is not destination or card.controller != to_player:
                raise PaymentError(
                    f"{instance} 를 P{to_player} 의 {destination.value} 로 "
                    f"보냈는데 {card.zone.value}/P{card.controller} 에 있습니다."
                )
            changes.append(
                ZoneMoved(
                    movement=operation,
                    card=instance,
                    source_player=from_player,
                    source_zone=from_zone,
                    destination_player=to_player,
                    destination_zone=destination,
                )
            )
        receipt = CostPayment(
            step.semantics, instances=step.instances, player=step.player
        )
        return receipt, tuple(changes)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        journal = "없음" if self._journal is None else f"{len(self._journal)}건"
        return f"<CostPayer journal={journal}>"


__all__ = [
    "CostPayer",
    "CostPaymentResult",
    "PaymentContext",
    "CostSelection",
    "PaymentStatus",
    "PaymentError",
    "COST_OPERATION",
    "SUPPORTED_COSTS",
    "UNSUPPORTED_REASON",
]
