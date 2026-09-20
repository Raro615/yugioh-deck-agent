"""
체인 응답 루프 — **지금 누가 체인에 무엇을 더할 차례인가**.

    Chain [L1]  +  PriorityState(RESPONSE, P1)
        ↓  ResponseLoop.act(state, response, PlayerAction)
        ├ PASS            ──►  우선권만 넘어간다. 판도 체인도 그대로
        └ ACTIVATE_EFFECT ──►  EffectActivator (Phase 2-Q)
                               ──►  Chain [L1, L2], 우선권은 상대에게
        ↓  둘 다 연속 패스
    ResponseLoop.ready_to_resolve()  →  VALID
        ↓  ResponseLoop.resolve(state, response, ChainResolver)
    L2 → L1 (LIFO)

두 값을 **나란히** 들고 있을 뿐이다
-----------------------------------
``Chain`` 과 ``PriorityState`` 는 서로를 모른다 — 우선권은 체인의 모양을
모르고, 체인은 누구 차례인지 모른다 (Phase 2-F-1 · 2-F-2 가 그렇게 나눴다).
:class:`ResponseState` 는 그 둘을 **한 값에 담기만** 한다. 어느 쪽에도
새 칸을 만들지 않고, ``PriorityState.resolve_chain()`` 같은 것도 만들지
않는다.

둘 다 ``GameState`` **밖**에 산다. 체인도 우선권도 판의 모양이 아니라 흐름의
위치이고, ``state_hash()`` 에 섞으면 "같은 판" 의 뜻이 달라진다.

트리거와 응답을 합치지 않는다
-----------------------------
=============================  =============================================
**트리거** (Phase 2-F-3)        하나의 **사건** 때문에 여럿이 동시에 발동
                                후보가 된다. 순서는 턴 플레이어 우선 규칙이
                                정하고, 플레이어가 고르는 것이 아니다
**응답** (여기)                  **이미 쌓인 체인**에 우선권을 쥔 사람이
                                하나를 더 얹는다. 무엇을 얹을지는 그 사람이
                                정하고, 순서는 우선권이 정한다
=============================  =============================================

이 모듈은 ``TriggerCollector`` 도 ``TriggerChainIntegrator`` 도 부르지
않는다. 같은 ``Chain`` 에 링크를 얹는다는 점만 같고, **왜 얹히는가**가 전혀
다르기 때문이다. 하나의 흐름으로 합치면 "동시에 발생한 유발 효과" 와
"체인에 대응해서 발동한 효과" 를 영영 구분할 수 없다.

효과를 실행하지 않는다
----------------------
``EffectExecutor`` 를 가져오지 않는다. 링크를 얹는 것은
:class:`~engine.activation.EffectActivator` (Phase 2-Q)가, 푸는 것은
:class:`~engine.chain.ChainResolver` (Phase 2-F-2)가 한다. 이 모듈은 **누가
언제** 그것을 할 차례인지만 말한다.

여기서 정하지 않는 규칙
-----------------------
- **체인이 끝난 뒤 누구에게 우선권이 가는가.** 그 규칙이 없으므로
  :meth:`ResponseLoop.resolve` 는 기회를 **닫는다** — 지어내지 않는다.
- **누가 응답 기회를 여는가.** :meth:`ResponseLoop.opened` 는 부르는 쪽이
  값으로 여는 도구일 뿐이고, "링크가 쌓였으니 자동으로 열린다" 는 규칙을
  만들지 않았다 (STRUCTURAL-34).
- 스펠 스피드 · 체인 블록 · SEGOC · 데미지 스텝 · 퀵 이펙트 타이밍 전부.
  "이 효과를 이 시점에 발동해도 되는가" 는 여전히 밖에서 오는 허가다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import ActivationResult, ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolution, ChainResolver
from engine.cost import CostPayment
from engine.effect.delta import StateDelta
from engine.effect.target import TargetSelection
from engine.game_state_view import GameStateView
from engine.payment import CostSelection
from engine.priority import (
    PriorityHolder,
    PriorityResolver,
    PriorityState,
    ResponseWindow,
)
from engine.state.game_state import GameState
from engine.validation import ValidationCode, ValidationResult


class ResponseStep(str, Enum):
    """
    **다음에 무엇을 해야 하는가.** 저장하지 않고 체인과 우선권에서 읽는다.

    저장하면 체인·우선권과 어긋날 수 있고, 어긋난 순간 어느 쪽이 맞는지
    알 수 없게 된다.
    """

    NO_CHAIN = "no_chain"
    """쌓인 링크가 없다. 응답할 체인 자체가 없다."""
    AWAIT_RESPONSE = "await_response"
    """아직 누군가 응답할 차례다."""
    RESOLVE = "resolve"
    """양쪽이 연속으로 패스했다. 이제 체인을 푼다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class ResponseOutcome(str, Enum):
    """
    응답 한 번의 결과.

    **``LINK_ADDED`` 하나만 체인을 늘린다.** ``PASSED`` 는 우선권만 옮기고,
    ``REFUSED`` 는 아무것도 옮기지 않는다.
    """

    LINK_ADDED = "link_added"
    """응답으로 링크가 하나 올라갔다."""
    PASSED = "passed"
    """
    패스했다. **효과가 아니다** — 체인도 판도 그대로이고, 우선권만 넘어간다.
    """
    REFUSED = "refused"
    """
    행위가 거절되었다. 체인 · 판 · **우선권까지** 그대로다.

    우선권을 옮기지 않는 이유: 거절은 "아무 일도 일어나지 않았다" 이므로,
    차례를 쥔 사람은 여전히 그 사람이다. 실패를 패스로 바꾸면 되돌릴 수 없는
    차례가 조용히 날아간다.
    """

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class ResponseError(RuntimeError):
    """응답 루프의 **모양**이 틀렸다. 규칙 위반이 아니다."""


@dataclass(frozen=True, slots=True)
class ResponseState:
    """
    루프의 **위치** — 쌓인 체인과 지금 차례인 사람. 불변이다.

    ``GameState`` 를 담지 않는다. 담으면 흐름의 위치가 판의 모양에 묶이고,
    직렬화도 replay 도 불가능해진다.
    """

    chain: Chain
    priority: PriorityState

    def __post_init__(self) -> None:
        if not isinstance(self.chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(self.chain).__name__}")
        if not isinstance(self.priority, PriorityState):
            raise TypeError(
                f"PriorityState 가 필요합니다: {type(self.priority).__name__}"
            )

    # --- 조회 --------------------------------------------------------
    @property
    def holder(self) -> PriorityHolder:
        return self.priority.holder

    @property
    def step(self) -> ResponseStep:
        """
        다음에 무엇을 해야 하는가.

        **순서가 규칙이다.** 체인이 비었으면 패스가 몇 번이든 풀 것이
        없다 — 빈 체인에서의 연속 패스는 다른 뜻이고, 그 뜻은 여기서 정하지
        않는다.
        """
        if self.chain.is_empty or self.chain.is_complete:
            return ResponseStep.NO_CHAIN
        if self.priority.both_passed:
            return ResponseStep.RESOLVE
        return ResponseStep.AWAIT_RESPONSE

    @property
    def is_open(self) -> bool:
        return self.priority.is_open

    @property
    def awaiting_response(self) -> bool:
        return self.step is ResponseStep.AWAIT_RESPONSE

    def with_chain(self, chain: Chain) -> "ResponseState":
        return ResponseState(chain, self.priority)

    def with_priority(self, priority: PriorityState) -> "ResponseState":
        return ResponseState(self.chain, priority)

    def canonical_state(self) -> tuple:
        return (self.chain.canonical_state(), self.priority.canonical_state())

    def to_dict(self) -> dict:
        return {
            "chain": self.chain.to_dict(),
            "priority": self.priority.to_dict(),
            "step": self.step.value,
        }

    def describe_ko(self) -> str:
        return (
            f"체인 {len(self.chain)}개 · {self.priority.describe_ko()} · "
            f"{self.step.value}"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class ResponseResult:
    """
    응답 한 번의 결과. **불변**이다.

    :attr:`state` 는 **시도 뒤의 위치**다. 거절되면 들어온 것 그대로가
    돌아온다 — ``None`` 을 돌려주면 "위치가 없다" 와 "위치가 그대로다" 가
    구분되지 않는다.
    """

    outcome: ResponseOutcome
    action: PlayerAction
    state: ResponseState
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    activation: ActivationResult | None = None
    """``ACTIVATE_EFFECT`` 였다면 Phase 2-Q 가 내놓은 결과 그대로."""
    missing: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ResponseState):
            raise TypeError(
                f"ResponseState 가 필요합니다: {type(self.state).__name__}"
            )
        if self.outcome is ResponseOutcome.LINK_ADDED:
            if self.activation is None or self.activation.link is None:
                raise ResponseError(
                    "링크가 올라갔다면서 발동 결과가 없습니다. 무엇이 "
                    "올라갔는지 말할 수 없는 성공은 성공이 아닙니다."
                )
        elif self.activation is not None and self.activation.activated:
            raise ResponseError(
                f"{self.outcome.value} 인데 발동은 성공했다고 되어 있습니다."
            )

    # --- 조회 --------------------------------------------------------
    @property
    def chain(self) -> Chain:
        return self.state.chain

    @property
    def priority(self) -> PriorityState:
        return self.state.priority

    @property
    def link(self):
        """이번 응답으로 올라간 링크. 없으면 ``None``."""
        return self.activation.link if self.activation is not None else None

    @property
    def added_link(self) -> bool:
        return self.outcome is ResponseOutcome.LINK_ADDED

    @property
    def deltas(self) -> tuple[StateDelta, ...]:
        """**비용**이 만든 변화. 효과의 변화가 아니다 — 아직 해결하지 않았다."""
        return self.activation.deltas if self.activation is not None else ()

    @property
    def payments(self) -> tuple[CostPayment, ...]:
        return self.activation.payments if self.activation is not None else ()

    def __bool__(self) -> bool:
        raise TypeError(
            "ResponseResult 를 참/거짓으로 쓸 수 없습니다. 거절된 응답이 "
            "조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`result.outcome` 을 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.outcome.value,
            self.action.canonical_state(),
            self.state.canonical_state(),
            self.code.value,
            self.reason,
            self.activation.canonical_state() if self.activation is not None else None,
            self.missing,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "outcome": self.outcome.value,
            "action": self.action.to_dict(),
            "state": self.state.to_dict(),
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.activation is not None:
            data["activation"] = self.activation.to_dict()
        if self.missing is not None:
            data["missing"] = self.missing
        return data

    def describe_ko(self) -> str:
        return f"{self.outcome.value}[{self.code.value}]: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class ResponseResolution:
    """
    루프가 체인 해결로 넘어간 결과.

    :attr:`permitted` 가 ``VALID`` 가 아니면 :attr:`steps` 는 비어 있고
    :attr:`state` 는 들어온 그대로다 — **아직 풀 때가 아니라는 뜻**이지
    실패가 아니다.
    """

    permitted: ValidationResult
    state: ResponseState
    steps: tuple[ChainResolution, ...] = ()

    def __post_init__(self) -> None:
        if not self.permitted.permits_execution and self.steps:
            raise ResponseError(
                "해결이 허가되지 않았는데 해결 기록이 있습니다."
            )

    @property
    def started(self) -> bool:
        return bool(self.steps)

    @property
    def fully_resolved(self) -> bool:
        """남은 링크가 없는가. **시작했는가와 다른 질문이다.**"""
        return self.started and self.state.chain.is_complete

    def __bool__(self) -> bool:
        raise TypeError(
            "ResponseResolution 을 참/거짓으로 쓸 수 없습니다. "
            "`result.started` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.permitted.canonical_state(),
            self.state.canonical_state(),
            tuple(step.canonical_state() for step in self.steps),
        )

    def to_dict(self) -> dict:
        return {
            "permitted": self.permitted.to_dict(),
            "state": self.state.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"<ResponseResolution {len(self.steps)}단계>"


#: 이 루프가 **다룰 줄 아는** 행위. 나머지는 거절한다.
RESPONDABLE: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.ACTIVATE_EFFECT, PlayerActionKind.PASS}
)

#: 체인이 끝난 뒤의 우선권 규칙이 없다는 사실. 기회를 닫을 때 남긴다.
AFTER_CHAIN_RULE = "체인 해결 뒤 우선권 규칙 (STRUCTURAL-34)"


class ResponseLoop:
    """
    체인에 대한 응답 한 번을 처리한다.

    **판을 직접 바꾸지 않는다.** 판이 바뀌는 것은
    :class:`~engine.activation.EffectActivator` 가 비용을 치를 때와
    :class:`~engine.chain.ChainResolver` 가 링크를 풀 때뿐이고, 둘 다 이미
    있는 것을 그대로 부른다.
    """

    __slots__ = ("_activator",)

    def __init__(self, activator: EffectActivator):
        if not isinstance(activator, EffectActivator):
            raise TypeError(
                f"EffectActivator 가 필요합니다: {type(activator).__name__}"
            )
        self._activator = activator

    @property
    def activator(self) -> EffectActivator:
        return self._activator

    # ==================================================================
    # 기회를 여는 도구 — 규칙이 아니다
    # ==================================================================
    @staticmethod
    def opened(
        chain: Chain,
        holder: PriorityHolder | int,
        turn_player: int,
        phase,
        reason: str = "체인에 응답",
    ) -> ResponseState:
        """
        응답 기회가 열린 위치를 만든다.

        **"링크가 쌓였으니 자동으로 열린다" 는 규칙을 만들지 않았다** — 누가
        언제 여는지는 아직 정해지지 않았고 (STRUCTURAL-34), 여기서 정하면
        틀린 채로 굳는다. 부르는 쪽이 값으로 연다.
        """
        return ResponseState(
            chain,
            PriorityState.opened(
                ResponseWindow.RESPONSE,
                holder,
                turn_player=turn_player,
                phase=phase,
                reason=reason,
            ),
        )

    # ==================================================================
    # 응답 한 번
    # ==================================================================
    def act(
        self,
        state: GameState,
        response: ResponseState,
        action: PlayerAction,
        selections: tuple[TargetSelection, ...] = (),
        cost_selections: tuple[CostSelection, ...] = (),
        authorization: ValidationResult | None = None,
    ) -> ResponseResult:
        """
        지금 차례인 사람의 행위 하나를 처리한다.

        순서가 규칙이다. **차례인지 먼저 보고**, 그 다음에 무엇을 하려는지
        본다 — 차례가 아닌 사람의 발동이 비용을 치르고 나서 거절되면 되돌릴
        방법이 없다.
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "ResponseLoop 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 비용을 치를 수 없습니다."
            )
        if not isinstance(response, ResponseState):
            raise TypeError(
                f"ResponseState 가 필요합니다: {type(response).__name__}"
            )
        if not isinstance(action, PlayerAction):
            raise TypeError(f"PlayerAction 이 필요합니다: {type(action).__name__}")

        turn = self.may_act(state, response, action.actor)
        if not turn.permits_execution:
            return ResponseResult(
                ResponseOutcome.REFUSED,
                action,
                response,
                turn.code,
                f"지금 이 자리의 차례가 아닙니다: {turn.reason}",
                missing=turn.missing_rule,
            )

        if action.kind not in RESPONDABLE:
            return ResponseResult(
                ResponseOutcome.REFUSED,
                action,
                response,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"응답 루프는 {action.kind.value} 를 다루지 못합니다. "
                "다룰 수 있는 것: "
                + ", ".join(sorted(k.value for k in RESPONDABLE)),
                missing=f"{action.kind.value} 를 체인 응답으로 다루는 규칙",
            )

        if action.kind is PlayerActionKind.PASS:
            return self._pass(action, response)
        return self._activate(
            state, response, action, selections, cost_selections, authorization
        )

    def may_act(
        self, state: GameState, response: ResponseState, seat: int
    ) -> ValidationResult:
        """
        그 자리가 지금 결정할 차례인가. **판을 읽기만 한다.**

        판정은 :class:`~engine.priority.PriorityResolver` 하나가 한다 —
        여기서 우선권 규칙을 다시 만들면 두 벌이 갈린다. 관측은 **그 자리의
        시점**으로 만든다.
        """
        view = GameStateView.from_state(state, viewer=seat)
        return PriorityResolver(view, response.priority).may_act(seat)

    # ------------------------------------------------------------------
    def _pass(
        self, action: PlayerAction, response: ResponseState
    ) -> ResponseResult:
        """
        패스는 **효과가 아니다.** 체인도 판도 그대로이고 우선권만 넘어간다.

        여기서 체인을 해결하지 않는다 — "둘 다 패스했다" 는 사실만 남고,
        그 다음에 무엇을 할지는 부르는 쪽이 :attr:`ResponseState.step` 을
        보고 정한다.
        """
        return ResponseResult(
            ResponseOutcome.PASSED,
            action,
            response.with_priority(response.priority.passed()),
            ValidationCode.OK,
            f"P{action.actor} 가 패스했습니다.",
        )

    def _activate(
        self,
        state: GameState,
        response: ResponseState,
        action: PlayerAction,
        selections: tuple[TargetSelection, ...],
        cost_selections: tuple[CostSelection, ...],
        authorization: ValidationResult | None,
    ) -> ResponseResult:
        """
        Phase 2-Q 의 발동 계층을 **그대로** 부른다. 여기서 발동 규칙을 다시
        만들지 않는다.

        성공하면 우선권이 **상대에게** 간다 — 그것이 응답 루프의 모양이다.
        연속 패스는 끊긴다 (:meth:`~engine.priority.PriorityState.acted`).
        """
        activation = self._activator.activate(
            state,
            response.chain,
            action,
            selections,
            cost_selections,
            authorization,
        )
        if activation.status is not ActivationStatus.ACTIVATED:
            # **우선권도 옮기지 않는다.** 아무 일도 일어나지 않았으므로
            # 차례는 여전히 그 사람의 것이다.
            return ResponseResult(
                ResponseOutcome.REFUSED,
                action,
                response,
                activation.code,
                f"응답 발동이 거절되었습니다: {activation.reason}",
                activation=activation,
                missing=activation.missing,
            )

        moved = response.priority.acted().give_to(response.priority.holder.opponent)
        return ResponseResult(
            ResponseOutcome.LINK_ADDED,
            action,
            ResponseState(activation.chain, moved),
            ValidationCode.OK,
            f"체인 {activation.link.chain_number} 로 응답했습니다.",
            activation=activation,
        )

    # ==================================================================
    # 해결로 넘어가기
    # ==================================================================
    def ready_to_resolve(self, response: ResponseState) -> ValidationResult:
        """
        지금 체인을 풀어도 되는가. **``VALID`` 일 때만 참이다.**

        새 어휘를 만들지 않고 :class:`~engine.validation.ValidationResult` 를
        그대로 돌려준다.
        """
        step = response.step
        if step is ResponseStep.RESOLVE:
            return ValidationResult.valid(
                f"양쪽이 연속으로 패스했습니다 (링크 {response.chain.remaining}개 남음)."
            )
        if step is ResponseStep.NO_CHAIN:
            return ValidationResult.invalid(
                ValidationCode.CHAIN_EMPTY, "풀 링크가 없습니다."
            )
        return ValidationResult.invalid(
            ValidationCode.NO_RESPONSE_WINDOW,
            f"아직 {response.priority.holder} 의 응답 차례입니다 "
            f"(연속 패스 {response.priority.consecutive_passes}회).",
        )

    def resolve(
        self,
        state: GameState,
        response: ResponseState,
        resolver: ChainResolver,
    ) -> ResponseResolution:
        """
        체인을 푼다. **기존 :class:`~engine.chain.ChainResolver` 에 넘긴다** —
        여기서 해결기를 다시 만들지 않는다 (§9).

        허가가 나지 않으면 한 글자도 바꾸지 않는다. 푼 뒤에는 기회를
        **닫는다** — 체인이 끝난 뒤 누구에게 우선권이 가는지가 아직 정해지지
        않았고 (STRUCTURAL-34), 지어내지 않는다.
        """
        if not isinstance(resolver, ChainResolver):
            raise TypeError(
                f"ChainResolver 가 필요합니다: {type(resolver).__name__}"
            )
        permitted = self.ready_to_resolve(response)
        if not permitted.permits_execution:
            return ResponseResolution(permitted, response)

        steps = resolver.resolve_all(state, response.chain)
        return ResponseResolution(
            permitted,
            ResponseState(
                steps[-1].chain,
                response.priority.closed(AFTER_CHAIN_RULE),
            ),
            steps,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ResponseLoop {self._activator!r}>"


__all__ = [
    "ResponseStep",
    "ResponseOutcome",
    "ResponseError",
    "ResponseState",
    "ResponseResult",
    "ResponseResolution",
    "ResponseLoop",
    "RESPONDABLE",
    "AFTER_CHAIN_RULE",
]
