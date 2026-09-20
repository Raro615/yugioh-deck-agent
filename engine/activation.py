"""
효과 **발동** — "이 효과를 지금 체인에 올릴 수 있는가".

    PlayerAction(ACTIVATE_EFFECT)
        ↓  EffectActivator.can_activate()   판을 읽기만 한다
    ValidationResult                        VALID · INVALID · UNKNOWN
        ↓  EffectActivator.activate()
    비용 지불 (CostPayer, Phase 2-E)         **여기서만 판이 바뀐다**
        ↓
    ChainLink → Chain.push()                Phase 2-F-2
        ↓  ............................    (다른 시점, 다른 호출)
    ChainResolver.resolve_top()
        ↓
    EffectExecutor.execute()                Phase 2-D-2 · 2-K~2-P

발동 ≠ 해결
-----------
**이 모듈은 :class:`~engine.effect.executor.EffectExecutor` 를 부르지
않는다.** 부르지 않는다는 것이 이 단계의 전부다 — 발동이 곧 해결이면 체인이
존재할 이유가 없고, 체인에 응답해서 끼어드는 효과를 영영 표현할 수 없다.

발동이 하는 일은 넷뿐이다.

1. 발동할 수 있는지 판정한다 (읽기만 한다).
2. 비용을 치른다 (:class:`~engine.payment.CostPayer`).
3. :class:`~engine.chain.ChainLink` 를 만든다.
4. 체인에 쌓는다.

카드가 묘지로 가지도, 몬스터가 파괴되지도, 라이프가 변하지도 않는다.
그것은 전부 해결의 일이다.

ActionExecutor 에 등록하지 않는다
---------------------------------
:class:`~engine.action_execution.ActionHandler` 는 ``apply(state, action)``
이 **``StateDelta`` 만** 돌려주는 모양이다. 그런데 발동의 결과물은 판의
모양이 아니라 **흐름의 위치**(``Chain`` · ``PriorityState``)이고, 그것은
``GameState`` 밖에 산다 (``EventJournal`` 과 같은 이유).

그래서 발동을 ``ActionHandler`` 로 끼워 넣으면 체인을 어딘가 숨겨 두고
주고받아야 한다. 숨긴 통로는 통로가 아니다 — 그래서 발동은 자기 진입점을
갖는다. ``ActionExecutor`` 는 이 모듈을 모르고, 이 모듈도 그쪽을 부르지
않는다 (STRUCTURAL-55).

허가는 밖에서 온다
------------------
"지금 이 행위를 해도 되는가" (페이즈 · 턴 플레이어 · 우선권 · 스펠 스피드)
는 :class:`~engine.action_validation.ActionValidator` 의 질문이고, 그쪽은
오늘 ``ACTIVATE_EFFECT`` 에 **``UNKNOWN`` 을 돌려준다** — 발동 타이밍 계층이
아직 없기 때문이다.

그래서 허가를 주지 않고 부르면 :attr:`ActivationStatus.UNAUTHORIZED` 다.
**``UNKNOWN`` 을 허가로 바꾸지 않는다.** 그것을 우회하려고 이 모듈이 자체
타이밍 규칙을 지어내지도 않는다 — 부르는 쪽이 ``authorization`` 으로
명시적인 ``VALID`` 를 건네야 하고, 그 판단의 책임은 건넨 쪽에 있다
(``ActionExecutor.execute(authorization=...)`` 과 같은 자리다).

여기서 하지 않는 것
-------------------
SEGOC · 스펠 스피드 · 체인 중 발동 · 강제 트리거 · 타이밍 놓침 · 대체 발동 ·
AI. 무엇을 **발동해야 하는가**는 이 계층의 질문이 아니다 — 엔진은 "발동할 수
있는가" 만 답한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.chain import Chain, ChainError, ChainLink
from engine.condition import ConditionContext, ConditionEvaluator, ConditionResult
from engine.cost import CostPayment
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionSource,
    EffectImplementationLookup,
    EmptyImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.delta import StateDelta
from engine.effect.target import TargetSelection
from engine.effect.targeting import TargetLegality, TargetResolver
from engine.game_state_view import GameStateView
from engine.payment import (
    CostPayer,
    CostPaymentResult,
    CostSelection,
    PaymentContext,
    PaymentStatus,
)
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.validation import ValidationCode, ValidationResult


class ActivationStatus(str, Enum):
    """
    발동 시도의 결과.

    **``ACTIVATED`` 하나만 체인을 늘린다.** 나머지는 전부 "체인에 아무것도
    올라가지 않았다" 를 뜻하고, 이유만 다르다.

    왜 기존 열거형을 쓰지 않는가
    ----------------------------
    =================================  =====================================
    :class:`~engine.effect.resolution.  **해결**의 결과다. 발동에 쓰면 이
    ResolutionStatus`                   단계의 전부인 구분이 무너진다
    :class:`~engine.action_execution.   판을 바꾸는 행위의 결과다. "비용을
    ActionStatus`                       못 냈다" 와 "대상이 틀렸다" 를
                                        구분할 칸이 없다
    =================================  =====================================

    ``code`` 는 기존 :class:`~engine.validation.ValidationCode` 를 그대로
    쓴다 — 새 코드 어휘를 만들지 않는다.
    """

    ACTIVATED = "activated"
    """발동했다. 체인에 링크가 하나 올라갔다."""
    UNAUTHORIZED = "unauthorized"
    """
    **지금 이 행위를 해도 되는지 허가가 나지 않았다.** 체인은 그대로다.

    오늘 ``ActionValidator`` 는 ``ACTIVATE_EFFECT`` 에 ``UNKNOWN`` 을
    돌려주므로, 허가를 밖에서 받지 않으면 언제나 여기로 온다. 그것이
    발동 타이밍 계층이 없다는 **사실**이고, 우회하지 않는다.
    """
    INVALID_ACTION = "invalid_action"
    """행위의 **모양**이 발동이 아니다 (종류 · ``effect_ref`` · ``source``)."""
    INVALID_CONTEXT = "invalid_context"
    """행위가 가리키는 효과와 정의가 서로 다르다."""
    FORBIDDEN = "forbidden"
    """출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004)."""
    UNVERIFIED = "unverified"
    """의미가 공식 근거에서 확인되지 않았다."""
    NOT_IMPLEMENTED = "not_implemented"
    """정의가 없거나, 실행 구현이 등록되어 있지 않다 (ADR-006)."""
    CONDITION_FALSE = "condition_false"
    """발동 조건이 **거짓**이다."""
    CONDITION_UNKNOWN = "condition_unknown"
    """발동 조건을 **판정할 수 없다.** 거짓과 합치지 않는다."""
    INVALID_TARGET = "invalid_target"
    """고른 대상이 규칙에 맞지 않거나, 아직 고르지 않았다."""
    UNCHECKED_TARGET = "unchecked_target"
    """고른 대상이 적법한지 **판정할 수 없다** (가려진 정보)."""
    COST_UNPAYABLE = "cost_unpayable"
    """비용을 **확실히** 치를 수 없다. 판은 그대로다."""
    COST_UNKNOWN = "cost_unknown"
    """
    비용을 치를 수 있는지 **판정할 수 없다.** 판은 그대로다.

    ``COST_UNPAYABLE`` 과 합치지 않는다 — "못 낸다" 와 "모르겠다" 는 다른
    답이고, 모르는 것을 "일단 지불" 로 바꾸면 원칙이 깨진다.
    """
    COST_ERROR = "cost_error"
    """
    지불 중에 예상 못 한 오류가 났다.

    **이때만 판이 반쯤 바뀌어 있을 수 있다.** ``CostPayer`` 의 preflight 가
    모든 것을 확인하므로 일어나서는 안 되는 경우이고, 일어났다면 결함이다.
    되돌리기는 ADR-008 이 미뤄 두었다.
    """
    CHAIN_REFUSED = "chain_refused"
    """
    체인이 이 링크를 받지 못한다 (예: 이미 해결이 시작된 체인).

    **비용을 치르기 전에** 확인한다 — 치른 뒤에 거절당하면 되돌릴 방법이
    없기 때문이다.
    """

    @property
    def activated(self) -> bool:
        return self is ActivationStatus.ACTIVATED

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class ActivationError(RuntimeError):
    """발동 중에 판이 예상과 다르게 움직였다. 계속 가지 않고 멈춘다."""


@dataclass(frozen=True, slots=True)
class ActivationResult:
    """
    발동 시도의 결과. **불변**이다.

    :attr:`chain` 은 **시도 뒤의 체인**이다. 실패하면 들어온 체인 그대로가
    돌아온다 — ``None`` 을 돌려주면 부르는 쪽이 "체인이 없다" 와 "체인이
    그대로다" 를 구분하지 못한다.

    :attr:`deltas` 는 **비용 지불이 만든 변화뿐**이다. 발동은 효과를
    적용하지 않으므로 효과의 변화는 여기 없다 — 그것은 해결의 결과
    (:class:`~engine.chain.ChainResolution`)에 있다.
    """

    status: ActivationStatus
    action: PlayerAction
    chain: Chain
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    link: ChainLink | None = None
    authorization: ValidationResult | None = None
    payment: CostPaymentResult | None = None
    deltas: tuple[StateDelta, ...] = ()
    """**비용**이 만든 변화. 효과의 변화가 아니다."""
    missing: str | None = None
    """무엇이 없어서 발동하지 못했는가."""
    unchecked: tuple[str, ...] = ()
    """무엇을 들여다보지 못했는가 (가려진 존 등)."""

    def __post_init__(self) -> None:
        if not isinstance(self.chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(self.chain).__name__}")
        if not isinstance(self.deltas, tuple):
            raise TypeError("deltas 는 tuple 이어야 합니다 — 결과는 불변입니다.")
        if self.status is ActivationStatus.ACTIVATED:
            if self.link is None:
                raise ActivationError(
                    "발동했다면서 링크가 없습니다. 체인에 무엇이 올라갔는지 "
                    "말할 수 없는 성공은 성공이 아닙니다."
                )
        elif self.link is not None:
            raise ActivationError(
                f"{self.status.value} 인데 링크가 있습니다. 발동하지 못한 "
                "시도는 체인을 늘리지 않습니다."
            )
        if self.status is not ActivationStatus.ACTIVATED and self.deltas:
            raise ActivationError(
                f"{self.status.value} 인데 변화 기록이 있습니다. 비용은 "
                "발동이 확정된 뒤에만 치릅니다."
            )

    # --- 조회 --------------------------------------------------------
    @property
    def activated(self) -> bool:
        return self.status is ActivationStatus.ACTIVATED

    @property
    def paid_anything(self) -> bool:
        """비용이 실제로 판을 바꿨는가. 발동 성공과 다른 질문이다."""
        return bool(self.deltas)

    @property
    def payments(self) -> tuple[CostPayment, ...]:
        return self.payment.payments if self.payment is not None else ()

    def __bool__(self) -> bool:
        raise TypeError(
            "ActivationResult 를 참/거짓으로 쓸 수 없습니다. 발동하지 못한 "
            "것이 조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`result.activated` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.action.canonical_state(),
            self.chain.canonical_state(),
            self.code.value,
            self.reason,
            self.link.canonical_state() if self.link is not None else None,
            self.authorization.canonical_state()
            if self.authorization is not None
            else None,
            self.payment.canonical_state() if self.payment is not None else None,
            tuple(delta.canonical_state() for delta in self.deltas),
            self.missing,
            self.unchecked,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "action": self.action.to_dict(),
            "chain": self.chain.to_dict(),
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.link is not None:
            data["link"] = self.link.to_dict()
        if self.authorization is not None:
            data["authorization"] = self.authorization.to_dict()
        if self.payment is not None:
            data["payment"] = self.payment.to_dict()
        if self.deltas:
            data["cost_deltas"] = [delta.to_dict() for delta in self.deltas]
        if self.missing is not None:
            data["missing"] = self.missing
        if self.unchecked:
            data["unchecked"] = list(self.unchecked)
        return data

    def describe_ko(self) -> str:
        return f"{self.status.value}[{self.code.value}]: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


#: 발동 판정이 **아직 답할 수 없는** 것들. ``missing`` 에 그대로 실린다.
MISSING_ACTIVATION_RULES: dict[ActivationStatus, str] = {
    ActivationStatus.UNAUTHORIZED: "activation-timing (스펠 스피드 · 체인 중 발동 · 우선권)",
}


class EffectActivator:
    """
    ``ACTIVATE_EFFECT`` 를 **체인 링크 하나**로 바꾼다.

    **효과를 적용하지 않는다.** 이 클래스는
    :class:`~engine.effect.executor.EffectExecutor` 를 가져오지도 않는다 —
    가져오는 순간 발동과 해결이 같은 자리에서 일어날 수 있게 된다.

    정의는 :class:`~engine.effect.definition.EffectDefinitionSource` 에서
    찾고, 실행 구현이 등록되어 있는지는 ``lookup`` 에 묻는다. 둘 다 없으면
    아무 효과도 발동되지 않는다 — 그것이 기본 상태다 (ADR-006).
    """

    __slots__ = ("_definitions", "_lookup", "_payer")

    def __init__(
        self,
        definitions: EffectDefinitionSource,
        lookup: EffectImplementationLookup | None = None,
        payer: CostPayer | None = None,
    ):
        self._definitions = definitions
        self._lookup = lookup if lookup is not None else EmptyImplementationLookup()
        # 비용 지불기는 **기존 것을 그대로 쓴다** (Phase 2-E). 여기서 비용을
        # 다시 구현하면 두 경로가 갈린다.
        self._payer = payer if payer is not None else CostPayer()

    @property
    def definitions(self) -> EffectDefinitionSource:
        return self._definitions

    @property
    def lookup(self) -> EffectImplementationLookup:
        return self._lookup

    @property
    def payer(self) -> CostPayer:
        return self._payer

    # ==================================================================
    # 읽기만 하는 질문
    # ==================================================================
    def can_activate(
        self,
        state: GameState,
        chain: Chain,
        action: PlayerAction,
        selections: tuple[TargetSelection, ...] = (),
        cost_selections: tuple[CostSelection, ...] = (),
        authorization: ValidationResult | None = None,
    ) -> ValidationResult:
        """
        지금 이 효과를 발동할 수 있는가. **판을 바꾸지 않는다.**

        :class:`~engine.validation.ValidationResult` 를 그대로 돌려준다 —
        "할 수 있는가" 의 어휘는 이미 있고, 발동만을 위한 세 번째 어휘를
        만들 이유가 없다.

        비용은 **치르지 않는다.** 치를 수 있는지까지는 여기서 답하지
        못한다 — ``CostPayer`` 의 preflight 가 비공개이고, 그것을 밖에서
        흉내 내면 두 벌이 갈린다. 그래서 이 판정이 ``VALID`` 라도
        :meth:`activate` 가 비용에서 멈출 수 있고, 그때도 링크는 생기지
        않는다 (STRUCTURAL-56).
        """
        blocked = self._check(state, chain, action, selections, authorization)
        if blocked is None:
            return ValidationResult.valid(
                f"{action.effect_ref} 를 발동할 수 있습니다 (비용 판정 제외)."
            )
        if blocked.status in _UNKNOWN_STATUSES:
            return ValidationResult.unknown(
                blocked.code,
                blocked.reason,
                missing_rule=blocked.missing,
                notes=blocked.unchecked,
            )
        return ValidationResult.invalid(blocked.code, blocked.reason)

    # ==================================================================
    # 진입점 — 여기서만 판이 바뀐다 (비용에 한해)
    # ==================================================================
    def activate(
        self,
        state: GameState,
        chain: Chain,
        action: PlayerAction,
        selections: tuple[TargetSelection, ...] = (),
        cost_selections: tuple[CostSelection, ...] = (),
        authorization: ValidationResult | None = None,
    ) -> ActivationResult:
        """
        효과를 발동해 체인에 올린다.

        순서가 규칙이다. **판을 읽기만 하는 검사를 전부 끝낸 뒤에야** 비용을
        치른다 — 치른 뒤에 거절당하면 되돌릴 방법이 없기 때문이다
        (ADR-008 이 rollback 을 미뤄 두었다). 체인이 링크를 받을 수 있는지도
        지불 **전에** 본다.

        우선권은 **여기서 건드리지 않는다.** 누가 언제 우선권을 옮겨야
        하는지가 아직 정해지지 않았으므로 (STRUCTURAL-34), 몰래 옮기는
        대신 :meth:`advance_priority` 를 부르는 쪽이 고른다.
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "EffectActivator 는 GameState 를 받습니다. 관측"
                "(GameStateView)은 읽기 전용이라 비용을 치를 수 없습니다."
            )
        if not isinstance(chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(chain).__name__}")

        blocked = self._check(state, chain, action, selections, authorization)
        if blocked is not None:
            return blocked

        definition = self._definitions.definition_for(action.effect_ref)
        assert definition is not None  # _check 가 확인했다

        # --- 여기서부터 판이 바뀔 수 있다 ------------------------------
        payment = self._payer.pay(
            state,
            definition.cost,
            PaymentContext(
                payer=action.actor,
                selections=tuple(cost_selections),
                effect_ref=action.effect_ref,
                source=action.source,
            ),
        )
        if not payment.paid:
            return self._fail(
                _COST_STATUS[payment.status],
                action,
                chain,
                payment.code,
                f"비용을 치르지 못했습니다: {payment.reason}",
                missing=payment.missing,
                unchecked=payment.notes,
                authorization=self._verdict(state, action, authorization),
                payment=payment,
            )

        link = ChainLink(
            sequence=len(chain),
            actor=action.actor,
            effect_ref=action.effect_ref,
            source=action.source,
            selections=tuple(selections),
            payments=payment.payments,
        )
        return ActivationResult(
            ActivationStatus.ACTIVATED,
            action,
            chain.push(link),
            ValidationCode.OK,
            f"{action.effect_ref} 를 체인 {link.chain_number} 로 발동했습니다.",
            link=link,
            authorization=self._verdict(state, action, authorization),
            payment=payment,
            deltas=payment.deltas,
        )

    # ------------------------------------------------------------------
    def advance_priority(self, priority: PriorityState) -> PriorityState:
        """
        발동이 성공했을 때의 우선권. **기존 전이를 그대로 부른다.**

        새 우선권 시스템을 만들지 않는다 (§10). 누가 언제 이것을 불러야
        하는지는 여전히 정해지지 않았다 (STRUCTURAL-34) — 그래서
        :meth:`activate` 가 몰래 부르지 않고, 부르는 쪽이 고른다.
        """
        return priority.acted()

    # ==================================================================
    # 판정 — 전부 판을 읽기만 한다
    # ==================================================================
    def _check(
        self,
        state: GameState,
        chain: Chain,
        action: PlayerAction,
        selections: tuple[TargetSelection, ...],
        authorization: ValidationResult | None,
    ) -> ActivationResult | None:
        """막는 것이 있으면 그 결과, 없으면 ``None``."""
        shape = self._check_shape(action, chain)
        if shape is not None:
            return shape

        verdict = self._verdict(state, action, authorization)
        if not verdict.permits_execution:
            return self._fail(
                ActivationStatus.UNAUTHORIZED,
                action,
                chain,
                verdict.code,
                f"지금 이 발동이 허가되지 않았습니다: {verdict.reason}",
                missing=verdict.missing_rule
                or MISSING_ACTIVATION_RULES[ActivationStatus.UNAUTHORIZED],
                authorization=verdict,
            )

        definition = self._definitions.definition_for(action.effect_ref)
        if definition is None:
            return self._fail(
                ActivationStatus.NOT_IMPLEMENTED,
                action,
                chain,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{action.effect_ref} 의 정의가 없습니다.",
                missing="effect definition",
                authorization=verdict,
            )
        if definition.effect_ref != action.effect_ref:
            return self._fail(
                ActivationStatus.INVALID_CONTEXT,
                action,
                chain,
                ValidationCode.EFFECT_REF_CARD_MISMATCH,
                f"정의가 가리키는 효과({definition.effect_ref})가 행위"
                f"({action.effect_ref})와 다릅니다.",
                authorization=verdict,
            )

        authority = self._check_authority(definition, action, chain, verdict)
        if authority is not None:
            return authority

        condition = self._check_condition(state, definition, action, chain, verdict)
        if condition is not None:
            return condition

        return self._check_targets(state, definition, action, chain, selections, verdict)

    def _check_shape(
        self, action: PlayerAction, chain: Chain
    ) -> ActivationResult | None:
        """
        행위가 **발동의 모양**인가. 규칙 판정이 아니다.

        체인이 링크를 받을 수 있는지도 여기서 본다 — 비용을 치르기 **전에**
        알아야 하기 때문이다.
        """
        if not isinstance(action, PlayerAction):
            raise TypeError(f"PlayerAction 이 필요합니다: {type(action).__name__}")
        if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
            return self._fail(
                ActivationStatus.INVALID_ACTION,
                action,
                chain,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{action.kind.value} 는 효과 발동이 아닙니다.",
            )
        if action.effect_ref is None:
            return self._fail(
                ActivationStatus.INVALID_ACTION,
                action,
                chain,
                ValidationCode.EFFECT_REF_REQUIRED,
                "발동할 효과를 가리키지 않았습니다.",
            )
        if action.source is None:
            return self._fail(
                ActivationStatus.INVALID_ACTION,
                action,
                chain,
                ValidationCode.SOURCE_REQUIRED,
                "발동한 카드를 가리키지 않았습니다.",
            )
        try:
            chain.push(
                ChainLink(
                    sequence=len(chain), actor=action.actor,
                    effect_ref=action.effect_ref,
                )
            )
        except ChainError as error:
            # **비용을 치르기 전에** 안다. 치른 뒤에 알면 되돌릴 수 없다.
            return self._fail(
                ActivationStatus.CHAIN_REFUSED,
                action,
                chain,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"체인이 이 링크를 받지 못합니다: {error}",
            )
        return None

    def _verdict(
        self,
        state: GameState,
        action: PlayerAction,
        authorization: ValidationResult | None,
    ) -> ValidationResult:
        """
        허가. 주지 않으면 검증기에게 묻는다 — 여기서 규칙을 만들지 않는다.

        관측은 **행위자의 시점**으로 만든다
        (``ActionExecutor.authorize`` 와 같은 이유).
        """
        if authorization is not None:
            if not isinstance(authorization, ValidationResult):
                raise TypeError(
                    f"ValidationResult 가 필요합니다: {type(authorization).__name__}"
                )
            return authorization
        view = GameStateView.from_state(state, viewer=action.actor)
        return ActionValidator(view).validate(action)

    def _check_authority(
        self,
        definition: EffectDefinition,
        action: PlayerAction,
        chain: Chain,
        verdict: ValidationResult,
    ) -> ActivationResult | None:
        """
        **출처 금지가 가장 먼저**다 — 구현이 등록되어 있어도
        ``TEXT_DERIVED`` 는 발동하지 않는다 (ADR-004).

        해결기가 거절할 효과를 체인에 올리지 않는다. 올리면 "발동은 됐는데
        해결은 안 되는" 링크가 쌓이고, 그것은 규칙이 아니라 결함이다.
        """
        availability = execution_availability(definition, self._lookup)
        if availability is ExecutionAvailability.EXECUTABLE:
            return None
        status, reason, missing = _AVAILABILITY_REFUSAL[availability]
        return self._fail(
            status,
            action,
            chain,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            reason,
            missing=missing,
            authorization=verdict,
        )

    def _check_condition(
        self,
        state: GameState,
        definition: EffectDefinition,
        action: PlayerAction,
        chain: Chain,
        verdict: ValidationResult,
    ) -> ActivationResult | None:
        """
        발동 조건. ``TRUE`` 일 때만 통과한다.

        ``None`` 은 **"조건이 없다" 가 아니라 "적지 않았다"** 이므로 넘어간다
        — 실행기와 같은 태도이고, 여기서 다르게 읽으면 같은 정의가 두 곳에서
        다른 뜻이 된다.
        """
        if definition.activation is None:
            return None
        view = GameStateView.from_state(state, viewer=action.actor)
        evaluated = ConditionEvaluator(view).evaluate(
            definition.activation, self._condition_context(action, ())
        )
        if evaluated.result is ConditionResult.TRUE:
            return None
        if evaluated.result is ConditionResult.FALSE:
            return self._fail(
                ActivationStatus.CONDITION_FALSE,
                action,
                chain,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"발동 조건이 거짓입니다: {evaluated.description}",
                authorization=verdict,
            )
        return self._fail(
            ActivationStatus.CONDITION_UNKNOWN,
            action,
            chain,
            ValidationCode.INFORMATION_UNAVAILABLE,
            f"발동 조건을 판정할 수 없습니다: {evaluated.description}",
            missing="; ".join(evaluated.unknown_reasons) or None,
            unchecked=evaluated.unknown_reasons,
            authorization=verdict,
        )

    def _check_targets(
        self,
        state: GameState,
        definition: EffectDefinition,
        action: PlayerAction,
        chain: Chain,
        selections: tuple[TargetSelection, ...],
        verdict: ValidationResult,
    ) -> ActivationResult | None:
        """
        고른 대상이 규칙에 맞는가. 판정은 Phase 2-N 의
        :class:`~engine.effect.targeting.TargetResolver` 하나가 한다 — 여기서
        자리와 주인을 다시 따지면 두 벌이 갈린다.

        **발동 시점의 대상을 따로 붙들어 두지 못한다.** 링크가 고른 결과를
        들고 가지만, "그때 적법했다" 는 사실은 어디에도 남지 않는다
        (STRUCTURAL-51 · 53).
        """
        if not definition.targets:
            if selections:
                return self._fail(
                    ActivationStatus.INVALID_TARGET,
                    action,
                    chain,
                    ValidationCode.TARGET_COUNT_MISMATCH,
                    "대상을 요구하지 않는 효과에 고른 카드가 들어왔습니다.",
                    authorization=verdict,
                )
            return None

        chosen = {selection.ref: selection.selection for selection in selections}
        resolver = TargetResolver(
            GameStateView.from_state(state, viewer=action.actor)
        )
        context = self._condition_context(
            action, tuple(i for s in selections for i in s.selection.chosen)
        )
        for binding in definition.targets:
            checked = resolver.validate(
                binding.spec, chosen.get(binding.ref), context, binding.ref
            )
            if checked.permits_selection:
                continue
            status = (
                ActivationStatus.INVALID_TARGET
                if checked.legality is TargetLegality.ILLEGAL
                else ActivationStatus.UNCHECKED_TARGET
            )
            return self._fail(
                status,
                action,
                chain,
                checked.code,
                f"{binding.ref} 의 대상이 발동에 쓸 수 없습니다: {checked.reason}",
                missing="; ".join(checked.unchecked) or None,
                unchecked=checked.unchecked,
                authorization=verdict,
            )
        return None

    # ------------------------------------------------------------------
    def _condition_context(self, action: PlayerAction, targets) -> ConditionContext:
        return ConditionContext(
            player=action.actor,
            source=action.source,
            effect_ref=action.effect_ref,
            targets=tuple(targets),
        )

    def _fail(
        self,
        status: ActivationStatus,
        action: PlayerAction,
        chain: Chain,
        code: ValidationCode,
        reason: str,
        missing: str | None = None,
        unchecked: tuple[str, ...] = (),
        authorization: ValidationResult | None = None,
        payment: CostPaymentResult | None = None,
    ) -> ActivationResult:
        """실패 결과 하나. **체인은 들어온 그대로 돌려준다.**"""
        return ActivationResult(
            status,
            action,
            chain,
            code,
            reason,
            authorization=authorization,
            payment=payment,
            missing=missing,
            unchecked=tuple(unchecked),
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EffectActivator lookup={self._lookup!r}>"


#: 실행 가능성이 거절로 바뀔 때의 (상태, 설명, 없는 것).
_AVAILABILITY_REFUSAL: dict[ExecutionAvailability, tuple[ActivationStatus, str, str]] = {
    ExecutionAvailability.FORBIDDEN_SOURCE: (
        ActivationStatus.FORBIDDEN,
        "공식 텍스트에서 유추한 효과는 발동하지 않습니다 (ADR-004).",
        "executable implementation from official script",
    ),
    ExecutionAvailability.UNVERIFIED: (
        ActivationStatus.UNVERIFIED,
        "의미가 공식 근거에서 확인되지 않았습니다.",
        "verified semantics",
    ),
    ExecutionAvailability.NO_IMPLEMENTATION: (
        ActivationStatus.NOT_IMPLEMENTED,
        "실행 구현이 등록되어 있지 않습니다. 해결할 수 없는 효과를 체인에 "
        "올리지 않습니다 (ADR-006).",
        "registered effect implementation",
    ),
}

#: 지불 실패가 발동 실패로 바뀔 때의 상태. **"못 낸다" 와 "모르겠다" 를 나눈다.**
_COST_STATUS: dict[PaymentStatus, ActivationStatus] = {
    PaymentStatus.CANNOT_PAY: ActivationStatus.COST_UNPAYABLE,
    PaymentStatus.INVALID_SELECTION: ActivationStatus.COST_UNPAYABLE,
    PaymentStatus.UNSUPPORTED_COST: ActivationStatus.COST_UNKNOWN,
    PaymentStatus.UNKNOWN: ActivationStatus.COST_UNKNOWN,
    PaymentStatus.EXECUTION_ERROR: ActivationStatus.COST_ERROR,
}

#: **모른다**는 뜻의 상태들. ``can_activate`` 가 ``UNKNOWN`` 으로 옮긴다.
_UNKNOWN_STATUSES: frozenset[ActivationStatus] = frozenset(
    {
        ActivationStatus.UNAUTHORIZED,
        ActivationStatus.UNVERIFIED,
        ActivationStatus.NOT_IMPLEMENTED,
        ActivationStatus.CONDITION_UNKNOWN,
        ActivationStatus.UNCHECKED_TARGET,
        ActivationStatus.COST_UNKNOWN,
    }
)


__all__ = [
    "ActivationStatus",
    "ActivationError",
    "ActivationResult",
    "EffectActivator",
    "MISSING_ACTIVATION_RULES",
]
