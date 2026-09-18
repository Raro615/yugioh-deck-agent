"""
우선권과 응답 기회 — **지금 누가 다음 선택을 할 차례인가**.

    PriorityState(holder, window, consecutive_passes, turn_player, phase)
        ↓  PriorityResolver(view, priority)
    "이 플레이어가 지금 결정할 차례인가"   ValidationResult

이것은 규칙이 아니라 **자리표**다
----------------------------------
여기서 답하는 것은 딱 하나, "차례가 누구인가" 이다. 그 사람이 **무엇을**
할 수 있는지는 답하지 않는다. 발동 조건 · 스펠 스피드 · 체인 · 트리거 ·
타이밍은 전부 이후 단계이고, 지금 흉내 내면 모양을 미리 못박게 된다.

옛 유희왕의 "우선권" 규칙이 아니다
----------------------------------
2010년 이전 OCG 의 "선공 우선권" 재정을 구현하는 것이 아니다. 여기서
우선권은 **엔진 내부의 추상화**다 — 게임 흐름에서 다음 합법적 선택의
기회를 누가 쥐고 있는가.

그래서 네 가지를 **따로** 둔다.

=====================  ================================================
``turn_player``         누구의 턴인가          ``TurnState``
``phase``               어느 페이즈인가        ``TurnState``
``holder``              누구의 차례인가        여기
``window``              어떤 종류의 기회인가   여기
=====================  ================================================

``holder == turn_player`` 를 어디에서도 강제하지 않는다. 상대의 응답 기회가
바로 그 반례다.

상대 참조와 절대 자리를 섞지 않는다
-----------------------------------
:class:`~engine.condition.PlayerRef` 는 **문맥 상대적**이다 ("자신" /
"상대"). 우선권에는 문맥이 없다 — 누구의 관점도 아니고, 그냥 0번이거나
1번이다. 그래서 절대 자리를 가리키는 :class:`PriorityHolder` 를 따로 둔다.
``PlayerRef.CONTROLLER`` 를 우선권 보유자로 쓰면 "무엇의 컨트롤러인가" 라는
답 없는 질문이 생긴다.

판을 바꾸지 않는다
------------------
:class:`PriorityState` 는 불변이고 ``GameState`` 안에 살지 않는다. 모든
전이는 **새 상태를 돌려준다** — ``state.passed()`` 는 자기를 고치지 않는다.
:class:`PriorityResolver` 는 관측만 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.game_state_view import GameStateView
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase


class PriorityError(ValueError):
    """
    있을 수 없는 전이를 요청했다.

    "지금 이 플레이어가 행동할 수 있는가" 는 판정이므로
    :class:`~engine.validation.ValidationResult` 로 답하지만, "아무도 차례가
    아닌데 패스한다" 는 판정이 아니라 **호출 쪽의 결함**이다. 조용히
    넘어가지 않는다.
    """


class PriorityHolder(str, Enum):
    """
    우선권을 쥔 **절대 자리**.

    ``PlayerRef`` 와 다르다 — 그쪽은 문맥 상대적("자신"/"상대")이고 이쪽은
    절대적이다. 우선권에는 기준이 될 문맥이 없다.

    :attr:`NOBODY` 가 있는 이유: "아무도 결정할 차례가 아니다" 는 "0번의
    차례다" 와 **다른 사실**이다. ``int | None`` 로 두면 ``None`` 이
    "아무도" 인지 "아직 안 정했다" 인지 구분되지 않는다.
    """

    PLAYER_0 = "player_0"
    PLAYER_1 = "player_1"
    NOBODY = "nobody"
    """아무에게도 차례가 없다. 열린 기회가 없을 때다."""

    @classmethod
    def of(cls, seat: int) -> "PriorityHolder":
        """자리 번호(0/1)를 보유자로 바꾼다."""
        if seat == 0:
            return cls.PLAYER_0
        if seat == 1:
            return cls.PLAYER_1
        raise ValueError(f"자리는 0 또는 1 입니다: {seat}")

    @property
    def holds(self) -> bool:
        """누군가 쥐고 있는가."""
        return self is not PriorityHolder.NOBODY

    @property
    def seat(self) -> int | None:
        """자리 번호. **아무도 아니면 ``None``.**"""
        if self is PriorityHolder.PLAYER_0:
            return 0
        if self is PriorityHolder.PLAYER_1:
            return 1
        return None

    @property
    def opponent(self) -> "PriorityHolder":
        """
        맞은편 자리. :attr:`NOBODY` 의 맞은편은 여전히 :attr:`NOBODY` 다 —
        아무도 아닌 것의 상대는 없다.
        """
        if self is PriorityHolder.PLAYER_0:
            return PriorityHolder.PLAYER_1
        if self is PriorityHolder.PLAYER_1:
            return PriorityHolder.PLAYER_0
        return PriorityHolder.NOBODY

    def is_seat(self, seat: int) -> bool:
        return self.seat == seat

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return {"player_0": "P0", "player_1": "P1", "nobody": "없음"}[self.value]


class ResponseWindow(str, Enum):
    """
    **어떤 종류의 결정 기회인가.**

    카드가 발동될 수 있는지, 스펠 스피드가 맞는지는 여기서 말하지 않는다.
    그것은 발동 합법성이고 이후 단계다. 이 열거형은 문맥일 뿐이다.
    """

    NONE = "none"
    """열린 기회가 없다. 아무도 결정할 차례가 아니다."""
    ACTION = "action"
    """턴 플레이어가 자기 턴의 행동을 고르는 기회."""
    RESPONSE = "response"
    """방금 일어난 일에 응답하는 기회."""
    PHASE_CHANGE = "phase_change"
    """페이즈를 넘기기 전의 기회."""

    @property
    def allows_decision(self) -> bool:
        """이 기회에서 누군가 결정할 수 있는가. :attr:`NONE` 만 거짓이다."""
        return self is not ResponseWindow.NONE

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class PriorityState:
    """
    지금 누가 어떤 기회를 쥐고 있는가. **불변**이고 값 타입만 담는다.

    ``GameState`` 를 담지 않는다 — 담으면 특정 판에 묶이고 직렬화도 replay
    도 불가능해진다. :attr:`turn_player` 와 :attr:`phase` 는 **복사본**이라
    판과 어긋날 수 있고, 그것을 :class:`PriorityResolver` 가 감지한다.

    ``GameState`` 안에 살지도 않는다. 우선권은 판의 **모양**이 아니라 흐름의
    위치이고, ``state_hash()`` 에 섞으면 "같은 판" 의 뜻이 달라진다
    (``EventJournal`` 을 밖에 둔 것과 같은 이유다).
    """

    holder: PriorityHolder = PriorityHolder.NOBODY
    window: ResponseWindow = ResponseWindow.NONE
    consecutive_passes: int = 0
    """**연속으로** 패스한 횟수. 누가 무엇을 하면 0 으로 돌아간다."""
    turn_player: int = 0
    phase: Phase = Phase.DRAW
    reason: str = ""
    """이 기회가 왜 열렸는가. 사람이 읽는 설명일 뿐 판정에 쓰지 않는다."""

    def __post_init__(self) -> None:
        if self.turn_player not in (0, 1):
            raise ValueError(f"턴 플레이어는 0 또는 1 입니다: {self.turn_player}")
        if self.consecutive_passes < 0:
            raise ValueError(
                f"패스 횟수는 음수일 수 없습니다: {self.consecutive_passes}"
            )
        if self.window is ResponseWindow.NONE and self.holder.holds:
            raise PriorityError(
                "열린 기회가 없는데 우선권을 쥔 사람이 있습니다. "
                "기회를 닫으려면 closed() 를 쓰세요."
            )
        if self.window.allows_decision and not self.holder.holds:
            raise PriorityError(
                f"{self.window.value} 기회가 열려 있는데 차례인 사람이 "
                "없습니다."
            )

    # ------------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------------
    @classmethod
    def idle(cls, turn_player: int = 0, phase: Phase = Phase.DRAW) -> "PriorityState":
        """아무 기회도 열려 있지 않은 상태. 듀얼의 출발점이다."""
        return cls(turn_player=turn_player, phase=phase)

    @classmethod
    def opened(
        cls,
        window: ResponseWindow,
        holder: PriorityHolder | int,
        turn_player: int = 0,
        phase: Phase = Phase.DRAW,
        reason: str = "",
    ) -> "PriorityState":
        """기회를 연다. 새로 연 기회의 연속 패스는 언제나 0 이다."""
        if window is ResponseWindow.NONE:
            raise PriorityError("NONE 은 기회가 아닙니다. idle() 또는 closed() 를 쓰세요.")
        return cls(
            holder=_as_holder(holder),
            window=window,
            consecutive_passes=0,
            turn_player=turn_player,
            phase=phase,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # 전이 — 전부 **새 상태**를 돌려준다
    # ------------------------------------------------------------------
    def give_to(self, holder: PriorityHolder | int) -> "PriorityState":
        """
        우선권을 지정한 사람에게 넘긴다.

        패스가 아니라 **새 기회를 주는 것**이므로 연속 패스는 0 으로
        돌아간다. 패스로 넘어가는 것은 :meth:`passed` 다.
        """
        if not self.window.allows_decision:
            raise PriorityError(
                "열린 기회가 없어 우선권을 넘길 수 없습니다. "
                "먼저 opened() 로 기회를 여세요."
            )
        given = _as_holder(holder)
        if not given.holds:
            raise PriorityError("아무에게도 넘길 수 없습니다. closed() 를 쓰세요.")
        return PriorityState(
            holder=given,
            window=self.window,
            consecutive_passes=0,
            turn_player=self.turn_player,
            phase=self.phase,
            reason=self.reason,
        )

    def passed(self) -> "PriorityState":
        """
        지금 차례인 사람이 패스한다. 우선권이 맞은편으로 가고 연속 패스가
        하나 늘어난다.

        **여기서 아무것도 해결하지 않는다.** 체인을 닫지도, 효과를
        처리하지도, 페이즈를 넘기지도 않는다. "둘 다 패스했다" 는 사실만
        :attr:`consecutive_passes` 에 남고, 그 다음에 무엇을 할지는 체인
        계층(Phase 2-F-2)이 정한다.

        기회(:attr:`window`)는 **그대로 유지된다.** 패스가 기회를 닫는다면
        그 판단이 이미 규칙이기 때문이다.
        """
        if not self.window.allows_decision:
            raise PriorityError("열린 기회가 없는데 패스할 수 없습니다.")
        return PriorityState(
            holder=self.holder.opponent,
            window=self.window,
            consecutive_passes=self.consecutive_passes + 1,
            turn_player=self.turn_player,
            phase=self.phase,
            reason=self.reason,
        )

    def acted(self) -> "PriorityState":
        """
        지금 차례인 사람이 **무언가 했다.** 연속 패스가 끊긴다.

        무엇을 했는지는 담지 않는다 — 그것은 Action 과 Journal 의 몫이다.
        여기서는 "패스가 아니었다" 는 사실만 반영한다.
        """
        if not self.window.allows_decision:
            raise PriorityError("열린 기회가 없는데 행동할 수 없습니다.")
        return PriorityState(
            holder=self.holder,
            window=self.window,
            consecutive_passes=0,
            turn_player=self.turn_player,
            phase=self.phase,
            reason=self.reason,
        )

    def closed(self, reason: str = "") -> "PriorityState":
        """
        기회를 닫는다. 아무도 차례가 아닌 상태로 돌아간다.

        **누가 닫을지는 여기서 정하지 않는다.** 이 메서드를 부르는 것은
        호출 쪽의 결정이고, 패스가 자동으로 부르지 않는다.
        """
        return PriorityState(
            holder=PriorityHolder.NOBODY,
            window=ResponseWindow.NONE,
            consecutive_passes=0,
            turn_player=self.turn_player,
            phase=self.phase,
            reason=reason,
        )

    def in_phase(self, phase: Phase, turn_player: int | None = None) -> "PriorityState":
        """
        턴 문맥만 갈아 끼운 사본. 페이즈 진행 자체는 하지 않는다 — 판이
        움직였을 때 우선권 상태를 따라 맞추는 용도다.
        """
        return PriorityState(
            holder=self.holder,
            window=self.window,
            consecutive_passes=self.consecutive_passes,
            turn_player=self.turn_player if turn_player is None else turn_player,
            phase=phase,
            reason=self.reason,
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self.window.allows_decision

    @property
    def both_passed(self) -> bool:
        """
        양쪽이 **연속으로** 패스했는가.

        이것이 무엇을 뜻하는지는 여기서 정하지 않는다. 체인이 있으면 체인이
        끝난다는 뜻이고, 없으면 다른 뜻이다. 사실만 말한다.
        """
        return self.consecutive_passes >= 2

    @property
    def holder_is_turn_player(self) -> bool:
        """
        차례인 사람이 턴 플레이어인가. **강제하지 않는 관계**를 묻는 것뿐이다.
        """
        return self.holder.is_seat(self.turn_player)

    def holds(self, seat: int) -> bool:
        """그 자리가 지금 차례인가. 판정이 아니라 단순 비교다."""
        return self.holder.is_seat(seat)

    # ------------------------------------------------------------------
    # 결정론적 표현
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        """
        같은 상태면 언제나 같은 값. 정수 · 문자열로만 이루어지므로
        ``PYTHONHASHSEED`` 에도, dict/set 순회 순서에도 영향받지 않는다.
        """
        return (
            self.holder.value,
            self.window.value,
            self.consecutive_passes,
            self.turn_player,
            self.phase.value,
            self.reason,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "holder": self.holder.value,
            "window": self.window.value,
            "consecutive_passes": self.consecutive_passes,
            "turn_player": self.turn_player,
            "phase": self.phase.value,
        }
        if self.reason:
            data["reason"] = self.reason
        return data

    def describe_ko(self) -> str:
        if not self.is_open:
            return f"기회 없음 (T{self.turn_player} {self.phase.value})"
        passes = f" 연속패스{self.consecutive_passes}" if self.consecutive_passes else ""
        return f"{self.holder} 차례 [{self.window.value}]{passes}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class PriorityResolver:
    """
    "지금 이 플레이어가 결정할 차례인가" 에 답한다. **판을 읽지도 바꾸지도
    않는다** — 관측(:class:`~engine.game_state_view.GameStateView`)과 우선권
    상태만 본다.

    .. warning::
       :meth:`may_act` 가 ``VALID`` 라는 것은 **차례가 그 사람의 것**이라는
       뜻일 뿐, 할 수 있는 행위가 하나라도 있다는 뜻이 아니다. 행위 하나가
       합법인지는 :class:`~engine.action_validation.ActionValidator` 가
       따로 답하고, 그쪽은 이번 단계에서 바꾸지 않았다.
    """

    __slots__ = ("_view", "_priority")

    def __init__(self, view: GameStateView, priority: PriorityState):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "PriorityResolver 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 조회가 판을 바꿀 수 있게 됩니다."
            )
        if not isinstance(priority, PriorityState):
            raise TypeError(
                f"PriorityState 가 필요합니다: {type(priority).__name__}"
            )
        self._view = view
        self._priority = priority

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def priority(self) -> PriorityState:
        return self._priority

    @property
    def holder(self) -> PriorityHolder:
        return self._priority.holder

    @property
    def window(self) -> ResponseWindow:
        return self._priority.window

    @property
    def both_passed(self) -> bool:
        return self._priority.both_passed

    # ------------------------------------------------------------------
    def may_act(self, seat: int) -> ValidationResult:
        """
        그 자리가 지금 결정할 차례인가.

        - 우선권 상태가 지금 판과 어긋나면 ``UNKNOWN`` — 어느 쪽이 낡았는지
          모르는 채로 "안 된다" 고 단정하지 않는다.
        - 열린 기회가 없으면 ``INVALID``.
        - 기회는 있는데 다른 사람 차례면 ``INVALID``.
        - 그 사람 차례면 ``VALID``.
        """
        if seat not in (0, 1):
            raise ValueError(f"자리는 0 또는 1 입니다: {seat}")

        stale = self._staleness()
        if stale is not None:
            return stale

        if not self._priority.is_open:
            return ValidationResult(
                ActionValidity.INVALID,
                ValidationCode.NO_RESPONSE_WINDOW,
                "지금은 아무도 결정할 차례가 아닙니다.",
            )
        if not self._priority.holds(seat):
            return ValidationResult(
                ActionValidity.INVALID,
                ValidationCode.NOT_PRIORITY_HOLDER,
                f"지금은 {self._priority.holder} 차례입니다 (P{seat} 아님).",
            )
        return ValidationResult(
            ActionValidity.VALID,
            ValidationCode.OK,
            f"P{seat} 가 {self._priority.window.value} 기회를 쥐고 있습니다. "
            "무엇을 할 수 있는지는 별개로 판정해야 합니다.",
        )

    def may_respond(self, seat: int) -> ValidationResult:
        """
        그 자리가 **응답**할 차례인가.

        :attr:`ResponseWindow.RESPONSE` 가 아닌 기회는 ``INVALID`` 다 —
        자기 턴의 행동 기회와 응답 기회는 다른 것이다.
        """
        verdict = self.may_act(seat)
        if verdict.validity is not ActionValidity.VALID:
            return verdict
        if self._priority.window is not ResponseWindow.RESPONSE:
            return ValidationResult(
                ActionValidity.INVALID,
                ValidationCode.NO_RESPONSE_WINDOW,
                f"지금은 {self._priority.window.value} 기회이지 응답 기회가 "
                "아닙니다.",
            )
        return verdict

    def _staleness(self) -> ValidationResult | None:
        """
        우선권 상태가 지금 판과 같은 턴 · 같은 페이즈를 말하고 있는가.

        복사본이 어긋났다는 것은 어느 한쪽이 낡았다는 뜻인데, **어느 쪽인지
        알 수 없다.** 그래서 ``UNKNOWN`` 이다.
        """
        mismatches: list[str] = []
        if self._priority.turn_player != self._view.turn_player:
            mismatches.append(
                f"턴 플레이어: 우선권 P{self._priority.turn_player} vs "
                f"관측 P{self._view.turn_player}"
            )
        if self._priority.phase is not self._view.phase:
            mismatches.append(
                f"페이즈: 우선권 {self._priority.phase.value} vs "
                f"관측 {self._view.phase.value}"
            )
        if not mismatches:
            return None
        return ValidationResult(
            ActionValidity.UNKNOWN,
            ValidationCode.PRIORITY_STATE_STALE,
            "우선권 상태가 지금 판과 맞지 않습니다: " + ", ".join(mismatches),
            missing_rule="priority state synchronisation (Phase 2-F-2~)",
            notes=tuple(mismatches),
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<PriorityResolver {self._priority.describe_ko()}>"


def _as_holder(holder: PriorityHolder | int) -> PriorityHolder:
    """자리 번호도 보유자도 받는다. 둘을 섞어 쓰는 것을 막지 않는다."""
    if isinstance(holder, PriorityHolder):
        return holder
    return PriorityHolder.of(holder)


__all__ = [
    "PriorityHolder",
    "ResponseWindow",
    "PriorityState",
    "PriorityResolver",
    "PriorityError",
]
