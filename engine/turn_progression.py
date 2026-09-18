"""
TurnProgressor — **게임의 시간이 앞으로 가는 유일한 문**.

    GameState (지금 몇 턴 · 누구 · 어느 페이즈)
        ↓  TurnProgressor.plan(state)      다음 자리는 어디인가
    TransitionPlan          허가 · 전이 · 아직 보지 않은 규칙
        ↓  TurnProgressor.advance(state)   실제로 옮긴다
    GameState 변경  +  PhaseChanged

무엇을 판정하는가 — **순서만 본다**
------------------------------------
:meth:`TurnProgressor.plan` 의 ``VALID`` 는 "이 엔진이 아는 **진행 순서**와
맞는다" 는 뜻이다. **"지금 이 페이즈에 들어가도 된다" 는 규칙 전체의 허가가
아니다.** 그 둘을 한 단어로 부르면, 아직 없는 규칙들이 조용히 통과한다.

아직 보지 않는 규칙은 :data:`UNRESOLVED_PROGRESSION_RULES` 에 그대로 적어
둔다 — 선공 첫 턴의 배틀 페이즈 · 체인이 남아 있을 때의 페이즈 종료 ·
페이즈를 건너뛰는 효과 따위다. 적어 두는 것과 구현한 것은 다르고, 여기서는
적어 두기만 한다.

턴 플레이어 ≠ 우선권
--------------------
**이 모듈은 :class:`~engine.priority.PriorityState` 를 읽지도 쓰지도
않는다.** 턴 플레이어가 P0 에서 P1 로 넘어간다고 해서 우선권이 그대로
따라가지 않는다 — 우선권은 페이즈 안에서도 여러 번 옮겨 다니고, 전이 직후
누구에게 열리는가는 아직 규칙이 없다. 전이가 우선권을 다시 열어야 한다는
사실만 :attr:`PhaseTransition.requires_priority_update` 로 남기고, 값은
정하지 않는다.

트리거도 만들지 않는다
----------------------
페이즈가 바뀌는 것은 분명히 사건이지만, 여기서
:class:`~engine.trigger.TimingEvent` 나 ``TriggerCandidate`` 를 만들지
않는다. 이 모듈이 후보를 만들기 시작하면 수집 · 적격성 · 정렬이 두 경로로
갈린다. 남기는 것은 :class:`~engine.effect.delta.PhaseChanged` 하나이고,
그것을 사건으로 읽을지는 부르는 쪽이 정한다.

낮은 API 와 규칙의 분리
-----------------------
:class:`~engine.state.turn.TurnState` 의 ``advance_phase()`` ·
``begin_next_turn()`` 은 **규칙이 아니라 값 바꾸기**다 (Phase 1). 이 모듈은
그 둘을 그대로 쓰고, 언제 어느 쪽을 부르는지만 정한다. 새 mutation API 를
만들지 않았다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.effect.delta import PhaseChanged, StateDelta
from engine.state.game_state import GameState
from engine.state.turn import TurnState
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import TURN_PHASE_ORDER, Phase

#: 진행 순서를 보는 것만으로는 **판정할 수 없는** 규칙들.
#:
#: ``plan()`` 이 ``VALID`` 를 주더라도 이 목록은 그대로 남아 있다 — 순서가
#: 맞다는 것과 규칙 전체가 허락한다는 것은 다른 말이기 때문이다.
UNRESOLVED_PROGRESSION_RULES: tuple[str, ...] = (
    "선공 첫 턴에 배틀 페이즈를 실행할 수 없다는 규칙",
    "배틀 페이즈가 없었으면 메인 페이즈 2 도 없다는 규칙",
    "체인이 남아 있거나 해결 중일 때 페이즈를 끝낼 수 있는가",
    "우선권을 쥔 쪽이 페이즈 종료를 선언했는가",
    "페이즈를 건너뛰거나 추가하는 카드 효과 (스킵 · 추가 배틀 페이즈)",
    "전이 직후 우선권이 누구에게 열리는가",
    "배틀 스텝 · 데미지 스텝 안의 진행",
)

#: 턴이 넘어갈 때 **언젠가 초기화되어야 하는** 것들. 지금은 하나도 하지
#: 않는다.
#:
#: 무엇이 언제 지워지는가는 규칙이고, 규칙 없이 지우면 "지웠다는 사실" 이
#: 판에 남아 되돌릴 수 없다. 그래서 목록만 남긴다 —
#: :class:`~engine.state.use_registry.UseRegistry` 가 리셋 시점을 정하지
#: 않은 것과 같은 이유다.
TURN_BOUNDARY_RESETS: tuple[str, ...] = (
    "UseRegistry — PER_CARD · PER_CARD_NAME · PER_EFFECT 의 '1턴에 1번'",
    "일반 소환권 (아직 모델이 없다)",
    "이 턴에 공격했는가 · 표시 형식을 바꿨는가 (아직 모델이 없다)",
    "이 턴에만 적용되는 지속 효과 (AppliedEffect, Phase 8)",
    "TurnState.step — 페이즈 안의 진행 단계",
)


class TurnProgressionError(RuntimeError):
    """계획과 실제 결과가 어긋났다. 일어나서는 안 되는 일이다."""


class TransitionKind(str, Enum):
    """전이의 종류. **턴이 넘어갔는가**가 유일한 갈림이다."""

    PHASE_ADVANCE = "phase_advance"
    """같은 턴 안에서 다음 페이즈로."""
    TURN_CHANGE = "turn_change"
    """엔드 페이즈에서 **다음 턴의** 첫 페이즈로. 턴 번호와 턴 플레이어가 바뀐다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class ProgressionStatus(str, Enum):
    """전이 시도의 결과."""

    ADVANCED = "advanced"
    """옮겼다. 판이 바뀌었다."""
    INVALID_TRANSITION = "invalid_transition"
    """규칙이 **안 된다고** 말했다."""
    UNKNOWN_TRANSITION = "unknown_transition"
    """규칙이 **모른다고** 말했다. ``INVALID`` 와 합치지 않는다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class TurnPosition:
    """게임 시간의 한 자리 — 몇 턴 · 누구 · 어느 페이즈. **불변**이다."""

    turn_number: int
    turn_player: int
    phase: Phase

    def __post_init__(self) -> None:
        if self.turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {self.turn_number}")
        if self.turn_player not in (0, 1):
            raise ValueError(f"턴 플레이어는 0 또는 1 입니다: {self.turn_player}")
        if not isinstance(self.phase, Phase):
            raise TypeError(f"Phase 가 필요합니다: {type(self.phase).__name__}")

    @classmethod
    def of(cls, turn: TurnState) -> "TurnPosition":
        return cls(turn.turn_number, turn.turn_player, turn.phase)

    @classmethod
    def from_state(cls, state: GameState) -> "TurnPosition":
        return cls.of(state.turn)

    @property
    def in_turn_order(self) -> bool:
        """이 페이즈가 턴 진행 순서 위에 있는가. 배틀 스텝 · 데미지 스텝은 아니다."""
        return self.phase in TURN_PHASE_ORDER

    def canonical_state(self) -> tuple:
        return (self.turn_number, self.turn_player, self.phase.value)

    def __str__(self) -> str:
        return f"T{self.turn_number} P{self.turn_player} {self.phase.value}"


@dataclass(frozen=True, slots=True)
class PhaseTransition:
    """
    **어디에서 어디로** 옮기는가. 계획이자 기록이고, 스스로 판을 바꾸지
    않는다.

    턴이 넘어가는 전이는 모양이 정해져 있다 — 턴 번호가 하나 늘고, 턴
    플레이어가 바뀌고, 다음 턴의 첫 페이즈로 간다. :meth:`__post_init__`
    이 그 모양을 강제하므로 "턴은 늘었는데 플레이어는 그대로" 같은 전이는
    **만들어지지 않는다.**
    """

    kind: TransitionKind
    before: TurnPosition
    after: TurnPosition

    def __post_init__(self) -> None:
        if self.kind is TransitionKind.PHASE_ADVANCE:
            if self.after.turn_number != self.before.turn_number:
                raise ValueError(
                    "같은 턴 안의 전이인데 턴 번호가 달라집니다: "
                    f"{self.before} → {self.after}"
                )
            if self.after.turn_player != self.before.turn_player:
                raise ValueError(
                    "같은 턴 안의 전이인데 턴 플레이어가 달라집니다: "
                    f"{self.before} → {self.after}"
                )
            if self.after.phase is self.before.phase:
                raise ValueError(
                    f"달라지는 것이 없는 전이입니다: {self.before.phase.value}"
                )
        else:
            if self.after.turn_number != self.before.turn_number + 1:
                raise ValueError(
                    "턴 넘김은 턴 번호를 하나만 늘립니다: "
                    f"{self.before.turn_number} → {self.after.turn_number}"
                )
            if self.after.turn_player != 1 - self.before.turn_player:
                raise ValueError(
                    "턴이 넘어가면 턴 플레이어가 바뀝니다: "
                    f"P{self.before.turn_player} → P{self.after.turn_player}"
                )
            if self.after.phase is not TURN_PHASE_ORDER[0]:
                raise ValueError(
                    "다음 턴은 첫 페이즈에서 시작합니다: "
                    f"{self.after.phase.value} ≠ {TURN_PHASE_ORDER[0].value}"
                )

    @property
    def changes_turn(self) -> bool:
        return self.kind is TransitionKind.TURN_CHANGE

    @property
    def requires_priority_update(self) -> bool:
        """
        전이 뒤에 우선권을 **다시 정해야 하는가.** 언제나 참이다.

        **누구에게 가는지는 여기서 말하지 않는다** — 그것은 우선권 계층의
        규칙이고, 이 모듈은 :class:`~engine.priority.PriorityState` 를 건드리지
        않는다.
        """
        return True

    def to_delta(self) -> PhaseChanged:
        """이 전이를 :class:`~engine.effect.delta.PhaseChanged` 로 적는다."""
        return PhaseChanged(
            from_turn=self.before.turn_number,
            from_player=self.before.turn_player,
            from_phase=self.before.phase,
            to_turn=self.after.turn_number,
            to_player=self.after.turn_player,
            to_phase=self.after.phase,
        )

    def canonical_state(self) -> tuple:
        return (
            self.kind.value,
            self.before.canonical_state(),
            self.after.canonical_state(),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "before": {
                "turn": self.before.turn_number,
                "player": self.before.turn_player,
                "phase": self.before.phase.value,
            },
            "after": {
                "turn": self.after.turn_number,
                "player": self.after.turn_player,
                "phase": self.after.phase.value,
            },
            "changes_turn": self.changes_turn,
        }

    def describe_ko(self) -> str:
        return f"{self.before} → {self.after}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """
    "옮겨도 되는가" 의 답. **아직 아무것도 옮기지 않았다.**

    :attr:`transition` 은 허가가 났을 때만 들어 있다 — 거절된 계획이 전이를
    들고 있으면 그것을 꺼내 쓰는 코드가 반드시 생긴다.
    """

    verdict: ValidationResult
    transition: PhaseTransition | None = None
    unresolved_rules: tuple[str, ...] = UNRESOLVED_PROGRESSION_RULES

    def __post_init__(self) -> None:
        if self.verdict.permits_execution and self.transition is None:
            raise ValueError("허가가 났는데 옮길 자리가 없습니다.")
        if not self.verdict.permits_execution and self.transition is not None:
            raise ValueError(
                f"{self.verdict.validity.value} 인데 전이를 들고 있습니다. "
                "허가되지 않은 전이는 값으로도 남기지 않습니다."
            )

    @property
    def permits_transition(self) -> bool:
        """
        옮겨도 되는가. **``VALID`` 일 때만 참이다.**

        이 참은 "진행 순서와 맞다" 는 뜻이고,
        :data:`UNRESOLVED_PROGRESSION_RULES` 는 여전히 보지 않았다.
        """
        return self.verdict.permits_execution

    def __bool__(self) -> bool:
        raise TypeError(
            "TransitionPlan 을 참/거짓으로 쓸 수 없습니다. UNKNOWN 이 조용히 "
            "허가가 되는 것을 막기 위해서입니다. `plan.permits_transition` 을 "
            "보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.verdict.canonical_state(),
            self.transition.canonical_state() if self.transition else None,
            self.unresolved_rules,
        )

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.to_dict(),
            "transition": self.transition.to_dict() if self.transition else None,
            "unresolved_rules": list(self.unresolved_rules),
        }

    def describe_ko(self) -> str:
        head = self.transition.describe_ko() if self.transition else "전이 없음"
        return f"{head} [{self.verdict}]"


@dataclass(frozen=True, slots=True)
class ProgressionResult:
    """
    실제로 옮긴 결과. **불변**이다.

    :attr:`deltas` 는 :attr:`ProgressionStatus.ADVANCED` 일 때만 들어 있다 —
    옮기지 않은 시도는 판을 바꾸지 않는다 (Phase 2-G 의
    :class:`~engine.action_execution.ActionExecution` 과 같은 규율).
    """

    status: ProgressionStatus
    plan: TransitionPlan
    deltas: tuple[StateDelta, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.deltas, tuple):
            raise TypeError("deltas 는 tuple 이어야 합니다 — 결과는 불변입니다.")
        if self.status is not ProgressionStatus.ADVANCED and self.deltas:
            raise ValueError(
                f"{self.status.value} 인데 변화 기록이 있습니다. 옮기지 않은 "
                "시도는 판을 바꾸지 않습니다."
            )

    @property
    def advanced(self) -> bool:
        return self.status is ProgressionStatus.ADVANCED

    @property
    def verdict(self) -> ValidationResult:
        return self.plan.verdict

    @property
    def transition(self) -> PhaseTransition | None:
        return self.plan.transition

    @property
    def unresolved_rules(self) -> tuple[str, ...]:
        return self.plan.unresolved_rules

    def __bool__(self) -> bool:
        raise TypeError(
            "ProgressionResult 를 참/거짓으로 쓸 수 없습니다. 옮기지 못한 "
            "이유가 '안 된다' 인지 '모른다' 인지 사라집니다. "
            "`result.advanced` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.plan.canonical_state(),
            tuple(delta.canonical_state() for delta in self.deltas),
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "plan": self.plan.to_dict(),
            "deltas": [delta.to_dict() for delta in self.deltas],
        }

    def describe_ko(self) -> str:
        return f"{self.status.value}: {self.plan.describe_ko()}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TurnProgressor:
    """
    턴과 페이즈를 앞으로 옮긴다. **상태를 갖지 않는다** — 같은 판에
    같은 요청을 주면 언제나 같은 답이다.

        progressor = TurnProgressor()
        plan = progressor.plan(state)          # 옮겨도 되는가
        result = progressor.advance(state)     # 옮긴다

    ``to_phase`` 를 주면 "그 페이즈로 가겠다" 는 요청이 된다. 지금 갈 수
    있는 곳은 **바로 다음 자리 하나**뿐이고, 더 앞의 페이즈로 건너뛰는 것은
    거절이 아니라 ``UNKNOWN`` 이다 — 실제 규칙에서는 메인 페이즈 1 에서
    엔드 페이즈로 바로 갈 수 있지만, 그때 배틀 페이즈가 없었다는 사실이
    무엇을 바꾸는지를 이 엔진은 아직 모른다.
    """

    __slots__ = ()

    # ==================================================================
    # 계산 — 아무것도 판정하지 않는다
    # ==================================================================
    def next_position(self, position: TurnPosition) -> TurnPosition | None:
        """
        진행 순서상 **바로 다음 자리.** 순서 위에 없는 페이즈면 ``None``.

        엔드 페이즈의 다음은 *다음 턴의* 첫 페이즈다 — 이 한 줄이
        :meth:`~engine.state.turn.TurnState.advance_phase` 가 하지 않는 일의
        전부다.
        """
        if position.phase not in TURN_PHASE_ORDER:
            return None
        index = TURN_PHASE_ORDER.index(position.phase)
        if index + 1 < len(TURN_PHASE_ORDER):
            return TurnPosition(
                position.turn_number,
                position.turn_player,
                TURN_PHASE_ORDER[index + 1],
            )
        return TurnPosition(
            position.turn_number + 1,
            1 - position.turn_player,
            TURN_PHASE_ORDER[0],
        )

    def next_transition(self, position: TurnPosition) -> PhaseTransition | None:
        """다음 자리로 가는 전이. 순서 위에 없는 페이즈면 ``None``."""
        after = self.next_position(position)
        if after is None:
            return None
        kind = (
            TransitionKind.TURN_CHANGE
            if after.turn_number != position.turn_number
            else TransitionKind.PHASE_ADVANCE
        )
        return PhaseTransition(kind, position, after)

    # ==================================================================
    # 판정 — 아무것도 바꾸지 않는다
    # ==================================================================
    def plan(
        self, state: GameState, to_phase: Phase | None = None
    ) -> TransitionPlan:
        """
        옮겨도 되는지 본다. **판을 바꾸지 않는다.**

        ``VALID`` 는 "진행 순서와 맞다" 는 뜻이지 규칙 전체의 허가가 아니다
        (모듈 설명 참고).
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "TurnProgressor 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 옮길 수 없습니다."
            )
        if to_phase is not None and not isinstance(to_phase, Phase):
            raise TypeError(f"Phase 가 필요합니다: {type(to_phase).__name__}")

        if state.result is not None:
            return TransitionPlan(
                ValidationResult.invalid(
                    ValidationCode.DUEL_ALREADY_OVER,
                    "이미 끝난 듀얼에서는 시간이 가지 않습니다.",
                )
            )

        position = TurnPosition.from_state(state)
        transition = self.next_transition(position)
        if transition is None:
            return TransitionPlan(
                ValidationResult.unknown(
                    ValidationCode.RULE_NOT_IMPLEMENTED,
                    f"{position.phase.value} 는 턴 진행 순서 위에 없는 "
                    "페이즈입니다. 다음 자리를 계산할 수 없습니다.",
                    missing_rule="배틀 스텝 · 데미지 스텝 안의 진행",
                )
            )

        if to_phase is not None:
            refusal = self._check_requested_phase(position, transition, to_phase)
            if refusal is not None:
                return TransitionPlan(refusal)

        return TransitionPlan(
            ValidationResult.valid(
                f"진행 순서상 다음 자리는 {transition.after} 입니다. "
                "순서가 맞다는 뜻이며, 아직 보지 않은 규칙이 남아 있습니다."
            ),
            transition,
        )

    # ==================================================================
    # 적용 — 여기서만 판이 바뀐다
    # ==================================================================
    def advance(
        self, state: GameState, to_phase: Phase | None = None
    ) -> ProgressionResult:
        """
        실제로 옮긴다. 허가가 나지 않으면 **한 글자도 바꾸지 않는다.**
        """
        plan = self.plan(state, to_phase)
        if not plan.permits_transition:
            status = (
                ProgressionStatus.INVALID_TRANSITION
                if plan.verdict.validity is ActionValidity.INVALID
                else ProgressionStatus.UNKNOWN_TRANSITION
            )
            return ProgressionResult(status, plan)

        transition = plan.transition
        assert transition is not None  # TransitionPlan 이 이미 강제한다
        self._apply(state, transition)
        return ProgressionResult(
            ProgressionStatus.ADVANCED, plan, (transition.to_delta(),)
        )

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _check_requested_phase(
        self,
        position: TurnPosition,
        transition: PhaseTransition,
        to_phase: Phase,
    ) -> ValidationResult | None:
        """요청한 페이즈가 갈 수 있는 자리인가. 갈 수 있으면 ``None``."""
        if to_phase is position.phase:
            return ValidationResult.invalid(
                ValidationCode.PHASE_UNCHANGED,
                f"이미 {to_phase.value} 페이즈입니다.",
            )
        if to_phase is transition.after.phase:
            return None

        if to_phase not in TURN_PHASE_ORDER:
            return ValidationResult.invalid(
                ValidationCode.WRONG_PHASE,
                f"{to_phase.value} 는 턴 진행 순서 위에 없는 페이즈입니다. "
                "페이즈 전이로 갈 수 있는 자리가 아닙니다.",
            )
        here = TURN_PHASE_ORDER.index(position.phase)
        there = TURN_PHASE_ORDER.index(to_phase)
        if there < here:
            return ValidationResult.invalid(
                ValidationCode.WRONG_PHASE,
                f"{to_phase.value} 는 이미 지나온 페이즈입니다. 시간은 "
                "되감기지 않습니다.",
            )
        return ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"{position.phase.value} 에서 {to_phase.value} 로 건너뛰는 것은 "
            "실제 규칙에서는 가능하지만, 건너뛴 페이즈가 없었다는 사실이 "
            "무엇을 바꾸는지 이 엔진은 아직 모릅니다.",
            missing_rule="페이즈 건너뛰기 (메인1 → 엔드 등)",
        )

    def _apply(self, state: GameState, transition: PhaseTransition) -> None:
        """
        :class:`~engine.state.turn.TurnState` 의 Phase 1 API 로만 옮긴다.

        옮긴 뒤 **계획한 자리에 있는지 확인한다** — 어긋나면 기록을 남기지
        않고 예외를 던진다. 틀린 기록은 없는 것보다 나쁘다.
        """
        if transition.changes_turn:
            state.turn.begin_next_turn()
        else:
            state.turn.advance_phase()

        landed = TurnPosition.from_state(state)
        if landed.canonical_state() != transition.after.canonical_state():
            raise TurnProgressionError(
                f"계획한 자리는 {transition.after} 인데 {landed} 에 있습니다."
            )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<TurnProgressor>"


@dataclass(frozen=True, slots=True)
class PhaseTransitionHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 얇은 껍데기.

    **규칙을 하나도 갖지 않는다.** 전부 :class:`TurnProgressor` 에게 넘기고,
    받은 전이를 그대로 돌려준다. 이것이 Phase 2-G 가 말한 "``ActionExecutor``
    가 턴 진행의 세부 규칙을 직접 구현해서는 안 된다" 를 지키는 방식이다.

    **기본 등록은 하지 않는다.** ``ActionValidator`` 는 ``CHANGE_PHASE`` 에
    아직 ``VALID`` 를 주지 않으므로 (우선권 · 체인 · 페이즈 진입 규칙이
    없다), 등록해도 오늘은 실행되지 않는다. 규칙 계층이 생겼을 때
    ``executor.register(PlayerActionKind.CHANGE_PHASE, PhaseTransitionHandler())``
    한 줄이면 붙는다.

    ``END_PHASE`` 는 **맡지 않는다.** "엔드 페이즈로 간다" 인지 "턴을
    끝낸다" 인지가 정해져 있지 않고, 둘 중 하나를 골라 두면 그 추측이 규칙이
    된다.
    """

    progressor: TurnProgressor = field(default_factory=TurnProgressor)

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        if action.kind is not PlayerActionKind.CHANGE_PHASE:
            raise TurnProgressionError(
                f"{action.kind.value} 는 이 핸들러가 맡는 행위가 아닙니다. "
                "change_phase 만 맡습니다."
            )
        result = self.progressor.advance(state, action.phase)
        if not result.advanced:
            raise TurnProgressionError(
                "허가는 났는데 진행 순서가 거절했습니다: "
                f"{result.plan.describe_ko()}"
            )
        return result.deltas


__all__ = [
    "UNRESOLVED_PROGRESSION_RULES",
    "TURN_BOUNDARY_RESETS",
    "TurnProgressionError",
    "TransitionKind",
    "ProgressionStatus",
    "TurnPosition",
    "PhaseTransition",
    "TransitionPlan",
    "ProgressionResult",
    "TurnProgressor",
    "PhaseTransitionHandler",
]
