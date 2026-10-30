"""
ActionExecutor — **PlayerAction 이 판을 바꾸는 유일한 문**.

    GameStateView            보이는 것
        ↓
    PlayerAction             무엇을 하고 싶은가
        ↓  ActionValidator   지금 해도 되는가
        ↓  ActionExecutor    허가된 행위를 실제로 적용한다
    GameState 변경  +  ActionExecution(deltas)

지금 실행되는 Action 이 **하나도 없다**
----------------------------------------
이것이 이 단계의 가장 중요한 사실이다. :class:`
~engine.action_validation.ActionValidator` 는 **어떤 Action 에도 ``VALID``
를 주지 않는다** — 소환 절차 · 타이밍 · 체인이 없어서 마지막 한 걸음을
확인할 수 없기 때문이고, 그것은 그 모듈이 스스로 적어 둔 사실이다.

그래서 이 실행기는 오늘 아무것도 실행하지 않는다. **그것이 결함이 아니라
정직한 상태다.** ``UNKNOWN`` 을 허가로 바꿔서 실행되게 만드는 순간, 이
프로젝트가 처음부터 지켜 온 "모르는 것을 참으로 접지 않는다" 가 무너진다.

규칙 계층이 생겨 ``VALID`` 가 나오기 시작하면, **이 파일을 고치지 않고도**
그 Action 이 실행된다.

구현은 등록해야 한다
--------------------
:class:`ActionHandler` 를 등록하지 않으면 그 종류는 실행되지 않는다.
:class:`~engine.effect.definition.EffectImplementationLookup` 이 "검증된
의미 ≠ 실행 가능" 을 지키는 방식(ADR-006) 그대로다. 허가가 났다고 자동으로
실행되지 않는다 — 그 종류를 실제로 수행할 코드가 있어야 한다.

이 실행기가 하지 않는 것
------------------------
소환 절차 · 전투 · 데미지 · 턴 진행 · 카드 효과 해결 · 비용 지불 ·
트리거 수집 · 체인 삽입 · 체인 해결 · 우선권 진행 · AI 판단. 각각은 자기
계층의 일이고, 여기서 흉내 내면 두 경로가 갈린다.

앞으로 붙을 자리
----------------
``SummonExecutor`` · ``BattleExecutor`` · ``EffectExecutor`` 는 각각
:class:`ActionHandler` 로 **등록**된다. 이 파일이 비대해지지 않는 이유가
그것이다 — 종류가 늘어도 여기에는 표 한 줄만 는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.effect.delta import StateDelta
from engine.effect.journal import EventJournal
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode, ValidationResult

#: 종류별로 **무엇이 없어서** 아직 실행하지 못하는가.
#:
#: 비어 있는 자리가 아니라 **남은 일의 목록**이다. 여기 적힌 계층이 생기고
#: 그 종류의 :class:`ActionHandler` 가 등록되면 실행된다.
UNSUPPORTED_REASON: dict[PlayerActionKind, str] = {
    PlayerActionKind.NORMAL_SUMMON: "일반 소환 절차 (제물 · 1턴 1회 · 칸)",
    PlayerActionKind.SPECIAL_SUMMON: (
        "특수 소환 절차 — 카드마다 다른 소환 조건 · 재료 고르기 · 표시 형식"
    ),
    PlayerActionKind.LINK_SUMMON: (
        "링크 소환 절차 — 소재 조건 · 소재 보내기 · 엑스트라 몬스터 존 배치"
    ),
    PlayerActionKind.SET_MONSTER: "세트 절차 (일반 소환권을 함께 쓴다)",
    PlayerActionKind.SET_SPELL_TRAP: "마법 · 함정 세트 절차",
    PlayerActionKind.ACTIVATE_CARD: "발동 절차 — 비용 · 대상 · 체인 삽입이 앞선다",
    PlayerActionKind.ACTIVATE_EFFECT: "발동 절차 — 비용 · 대상 · 체인 삽입이 앞선다",
    PlayerActionKind.CHANGE_POSITION: "표시 형식 변경 규칙 (1턴 1회 · 소환 턴 제약)",
    PlayerActionKind.ATTACK: "전투 (공격 선언 · 데미지 스텝)",
    PlayerActionKind.CHANGE_PHASE: "턴 진행 (페이즈 전이 규칙)",
    PlayerActionKind.END_PHASE: "턴 진행 (페이즈 전이 규칙)",
    PlayerActionKind.PASS: (
        "우선권 계층의 일 — 패스는 GameState 가 아니라 PriorityState 를 "
        "움직인다 (PriorityState.passed)"
    ),
}


class ActionExecutionError(RuntimeError):
    """실행 중에 판이 예상과 다르게 움직였다. 계속 가지 않고 멈춘다."""


class ActionStatus(str, Enum):
    """
    실행 시도의 결과.

    **``EXECUTED`` 하나만 판을 바꾼다.** 나머지는 전부 "아무 일도 일어나지
    않았다" 를 뜻하고, 이유만 다르다.
    """

    EXECUTED = "executed"
    """허가가 났고 구현이 있어 실제로 적용했다."""
    INVALID_ACTION = "invalid_action"
    """검증이 **확실히** 거부했다. 판은 그대로다."""
    UNKNOWN_ACTION = "unknown_action"
    """
    할 수 있는지 **판정할 수 없다.** 판은 그대로다.

    ``INVALID_ACTION`` 과 합치지 않는다 — "안 된다" 와 "모르겠다" 는 다른
    답이다. **오늘 모든 Action 이 여기로 온다** (모듈 설명 참고).
    """
    UNSUPPORTED_ACTION = "unsupported_action"
    """
    허가는 났지만 이 종류를 수행할 구현이 등록되어 있지 않다.

    ``UNKNOWN_ACTION`` 과 다르다 — 이쪽은 "해도 된다는 것은 알지만 할 줄
    모른다" 이다.
    """
    EXECUTION_ERROR = "execution_error"
    """
    적용 중에 예상 못 한 오류가 났다.

    **이때만 판이 반쯤 바뀌어 있을 수 있다.** 되돌리기는 ADR-008 이 미뤄
    두었으므로, 구현은 스스로 계획-후-적용으로 그 위험을 없애야 한다.
    """


@runtime_checkable
class ActionHandler(Protocol):
    """
    한 종류의 Action 을 **실제로 수행하는 것.**

    ``SummonExecutor`` · ``BattleExecutor`` 같은 하위 실행기가 이 모양으로
    등록된다. 허가 판정은 하지 않는다 — 이미 끝난 뒤에 불린다.

    돌려주는 것은 **무엇이 달라졌는가**(:class:`
    ~engine.effect.delta.StateDelta`)다. 기존 기록 구조를 그대로 쓰므로 새
    이벤트 모델을 만들 필요가 없다.
    """

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        ...  # pragma: no cover - 프로토콜


@dataclass(frozen=True, slots=True)
class ActionExecution:
    """
    실행 시도의 결과. **불변**이다.

    :attr:`authorization` 은 이 시도를 허가했거나 거절한 판정 그대로다 —
    "왜 실행되지 않았는가" 를 밖에서 그대로 읽을 수 있다.
    """

    status: ActionStatus
    action: PlayerAction
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    authorization: ValidationResult | None = None
    deltas: tuple[StateDelta, ...] = ()
    missing: str | None = None
    """무엇이 없어서 실행하지 못했는가."""

    def __post_init__(self) -> None:
        if not isinstance(self.deltas, tuple):
            raise TypeError("deltas 는 tuple 이어야 합니다 — 결과는 불변입니다.")
        if self.status is not ActionStatus.EXECUTED and self.deltas:
            raise ValueError(
                f"{self.status.value} 인데 변화 기록이 있습니다. 실행되지 "
                "않은 행위는 판을 바꾸지 않습니다."
            )

    @property
    def executed(self) -> bool:
        return self.status is ActionStatus.EXECUTED

    @property
    def changed_state(self) -> bool:
        """판이 실제로 달라졌는가. 변화가 없는 실행도 있을 수 있다."""
        return bool(self.deltas)

    def __bool__(self) -> bool:
        raise TypeError(
            "ActionExecution 을 참/거짓으로 쓸 수 없습니다. 실행되지 않은 "
            "것이 조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`result.executed` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.action.canonical_state(),
            self.code.value,
            self.reason,
            self.authorization.canonical_state()
            if self.authorization is not None
            else None,
            tuple(delta.canonical_state() for delta in self.deltas),
            self.missing,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "action": self.action.to_dict(),
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.authorization is not None:
            data["authorization"] = self.authorization.to_dict()
        if self.deltas:
            data["deltas"] = [delta.to_dict() for delta in self.deltas]
        if self.missing is not None:
            data["missing"] = self.missing
        return data

    def describe_ko(self) -> str:
        return f"{self.action.kind.value} → {self.status.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class ActionExecutor:
    """
    허가된 :class:`~engine.action.PlayerAction` 을 실제로 적용한다.
    **PlayerAction 이 판을 바꾸는 공식 진입점이다.**

    구현을 등록하지 않으면 아무것도 실행하지 않는다 — 그것이 기본 상태다.
    """

    __slots__ = ("_handlers", "_journal")

    def __init__(
        self,
        handlers: "dict[PlayerActionKind, ActionHandler] | None" = None,
        journal: "EventJournal | None" = None,
    ):
        """
        ``journal`` 을 주면 **실제로 적용된** 행위를 적는다 (Phase 6-B).

        🔴 **기본값은 ``None`` 이고 그때는 아무것도 적지 않는다.** 기록이
        켜지는 것으로 행동이 달라지면 기록이 아니다 — 기존 호출은 한 글자도
        고치지 않고 예전과 같이 돈다.

        :class:`~engine.effect.executor.EffectExecutor` 와
        :class:`~engine.payment.CostPayer` 가 같은 모양으로 journal 을 받는다.
        세 자리가 **판을 바꾸는 세 원인**이고, 기록도 그 세 자리에서 한다 —
        한 곳에 모아 두면 "무엇이 이 변화를 일으켰는가" 가 사라진다.
        """
        self._handlers: dict[PlayerActionKind, ActionHandler] = {}
        self._journal = journal
        for kind, handler in (handlers or {}).items():
            self.register(kind, handler)

    @property
    def journal(self) -> "EventJournal | None":
        """적고 있는 기록. 없으면 ``None`` — 그 사실이 곧 "적지 않는다" 다."""
        return self._journal

    # ------------------------------------------------------------------
    def register(
        self, kind: PlayerActionKind, handler: ActionHandler
    ) -> "ActionExecutor":
        """
        한 종류의 수행기를 등록한다. **손으로 한다** — 어떤 종류도 자동으로
        실행 가능해지지 않는다 (ADR-006 과 같은 태도).
        """
        if not isinstance(kind, PlayerActionKind):
            raise TypeError(f"PlayerActionKind 가 필요합니다: {kind!r}")
        if not hasattr(handler, "apply"):
            raise TypeError("ActionHandler 는 apply(state, action) 가 필요합니다.")
        if kind in self._handlers:
            raise ValueError(f"{kind.value} 의 수행기가 이미 등록되어 있습니다.")
        self._handlers[kind] = handler
        return self

    def handler_for(self, kind: PlayerActionKind) -> ActionHandler | None:
        return self._handlers.get(kind)

    @property
    def supported(self) -> frozenset[PlayerActionKind]:
        """
        지금 실행할 수 있는 종류. **기본값은 빈 집합이다** — 그것이 지금
        엔진의 사실이다.
        """
        return frozenset(self._handlers)

    # ==================================================================
    # 진입점
    # ==================================================================
    def execute(
        self,
        state: GameState,
        action: PlayerAction,
        authorization: ValidationResult | None = None,
    ) -> ActionExecution:
        """
        행위를 적용한다.

        ``state`` 는 **바뀔 수 있다.** 다만 :attr:`ActionStatus.EXECUTED` 를
        돌려줄 때만 그렇다.

        ``authorization`` 은 **규칙 계층이 내준 허가**다. 주지 않으면
        :class:`~engine.action_validation.ActionValidator` 로 직접 물어보는데,
        그것은 오늘 어떤 Action 에도 ``VALID`` 를 주지 않는다. 주더라도
        ``VALID`` 가 아니면 거부한다 — ``UNKNOWN`` 을 허가로 받지 않는다.
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "ActionExecutor 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 적용할 수 없습니다."
            )
        if not isinstance(action, PlayerAction):
            raise TypeError(f"PlayerAction 이 필요합니다: {type(action).__name__}")

        verdict = (
            authorization
            if authorization is not None
            else self.authorize(state, action)
        )
        refusal = self._check_authorization(action, verdict)
        if refusal is not None:
            return refusal

        handler = self._handlers.get(action.kind)
        if handler is None:
            return ActionExecution(
                ActionStatus.UNSUPPORTED_ACTION,
                action,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{action.kind.value} 를 수행할 구현이 등록되어 있지 않습니다.",
                authorization=verdict,
                missing=UNSUPPORTED_REASON.get(
                    action.kind, f"{action.kind.value} 실행"
                ),
            )

        try:
            deltas = tuple(handler.apply(state, action))
        except Exception as error:  # pragma: no cover - 일어나서는 안 된다
            # 반쪽짜리 기록은 없는 것보다 나쁘다 — 돌려주지 않는다.
            return ActionExecution(
                ActionStatus.EXECUTION_ERROR,
                action,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"적용 중 오류가 났습니다: {error}. 판이 반쯤 바뀌어 있을 수 "
                "있습니다.",
                authorization=verdict,
            )

        executed = ActionExecution(
            ActionStatus.EXECUTED,
            action,
            ValidationCode.OK,
            f"{action.kind.value} 를 적용했습니다 ({len(deltas)}건).",
            authorization=verdict,
            deltas=deltas,
        )
        if self._journal is not None and executed.deltas:
            # 🔴 **여기가 기록 시점이다** — 판이 이미 바뀐 뒤, 그리고 그
            # 변화가 ``EXECUTED`` 라는 사실과 함께 묶인 뒤다.
            #
            # ``ActionExecution.__post_init__`` 이 "EXECUTED 가 아니면
            # deltas 가 없다" 를 **생성 시점에 거부**하므로, 이 줄에 닿은
            # deltas 는 정의상 적용이 끝난 변화다. 계획을 완료로 오인할
            # 자리가 구조적으로 없다 (§5-B).
            #
            # 예외 경로(``EXECUTION_ERROR``)는 위에서 이미 돌아갔고 변화를
            # 돌려주지 않는다 — 반쪽짜리 기록을 남기지 않는다.
            self._journal.record_action(
                action_kind=action.kind.value,
                actor=action.actor,
                deltas=executed.deltas,
                source=action.source,
            )
        return executed

    # ------------------------------------------------------------------
    def authorize(self, state: GameState, action: PlayerAction) -> ValidationResult:
        """
        지금 이 행위를 해도 되는가. **검증기에게 그대로 묻는다** — 여기서
        규칙을 다시 만들지 않는다.

        관측은 **행위자의 시점**으로 만든다. 상대의 패를 들여다보고 판정하면
        검증을 반복하는 것만으로 손패를 탐지할 수 있다.
        """
        view = GameStateView.from_state(state, viewer=action.actor)
        return ActionValidator(view).validate(action)

    def _check_authorization(
        self, action: PlayerAction, verdict: ValidationResult
    ) -> ActionExecution | None:
        """
        허가가 났는가. **``VALID`` 일 때만 통과한다.**

        ``permits_execution`` 을 쓴다 — ``if validity is not INVALID:`` 로
        쓰면 ``UNKNOWN`` 이 허가로 새어 나간다.
        """
        if not isinstance(verdict, ValidationResult):
            raise TypeError(
                f"ValidationResult 가 필요합니다: {type(verdict).__name__}"
            )
        if verdict.permits_execution:
            return None
        status = (
            ActionStatus.INVALID_ACTION
            if verdict.validity is ActionValidity.INVALID
            else ActionStatus.UNKNOWN_ACTION
        )
        return ActionExecution(
            status,
            action,
            verdict.code,
            verdict.reason,
            authorization=verdict,
            missing=verdict.missing_rule,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        kinds = ", ".join(sorted(k.value for k in self._handlers)) or "없음"
        return f"<ActionExecutor 등록={kinds}>"


__all__ = [
    "ActionStatus",
    "ActionHandler",
    "ActionExecution",
    "ActionExecutionError",
    "ActionExecutor",
    "UNSUPPORTED_REASON",
]
