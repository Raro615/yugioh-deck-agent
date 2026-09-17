"""
턴과 페이즈의 **상태**.

실제 유희왕 페이즈 규칙 (언제 넘어가는가, 우선권이 누구에게 있는가, 어떤
페이즈에 무엇을 할 수 있는가) 은 구현하지 않는다. 그것은 Phase 4 의
타이밍 계층이다.

여기서 허용하는 것은 "지금이 몇 턴 누구의 어느 페이즈인가" 를 표현하고,
그 값을 안전하게 바꾸는 것까지다. 페이즈 이름은
:class:`~engine.vocabulary.Phase` 를 쓰므로 ``PHASE_*`` 어휘와 어긋날 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.vocabulary import TURN_PHASE_ORDER, Phase


@dataclass(slots=True)
class TurnState:
    """턴 번호 · 턴 플레이어 · 페이즈 · 스텝."""

    turn_number: int = 1
    turn_player: int = 0
    phase: Phase = Phase.DRAW
    step: int = 0
    """페이즈 안의 진행 단계. 배틀 스텝 등에서 쓰게 된다 (Phase 1 은 0 고정)."""

    def __post_init__(self) -> None:
        if self.turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {self.turn_number}")
        if self.turn_player not in (0, 1):
            raise ValueError(f"턴 플레이어는 0 또는 1 입니다: {self.turn_player}")
        if self.step < 0:
            raise ValueError(f"스텝은 음수일 수 없습니다: {self.step}")

    @property
    def non_turn_player(self) -> int:
        return 1 - self.turn_player

    # ------------------------------------------------------------------
    # 상태 변경 (규칙 아님)
    # ------------------------------------------------------------------
    def set_phase(self, phase: Phase, step: int = 0) -> None:
        """
        페이즈를 지정한 값으로 바꾼다. **넘어가도 되는지는 판정하지 않는다.**
        """
        if step < 0:
            raise ValueError(f"스텝은 음수일 수 없습니다: {step}")
        self.phase = phase
        self.step = step

    def advance_phase(self) -> Phase:
        """
        :data:`~engine.vocabulary.TURN_PHASE_ORDER` 에서 다음 페이즈로 옮긴다.
        엔드 페이즈에서는 더 가지 않는다 (턴 넘김은 :meth:`begin_next_turn`).

        배틀 페이즈 내부 스텝은 이 순서에 들어 있지 않다.
        """
        try:
            index = TURN_PHASE_ORDER.index(self.phase)
        except ValueError:
            raise ValueError(
                f"{self.phase.value} 는 턴 진행 순서에 없는 페이즈입니다. "
                "set_phase 로 직접 지정하세요."
            ) from None
        if index + 1 < len(TURN_PHASE_ORDER):
            self.set_phase(TURN_PHASE_ORDER[index + 1])
        return self.phase

    def begin_next_turn(self) -> "TurnState":
        """턴을 넘긴다. 플레이어별 초기화는 :class:`~engine.state.player.PlayerState`
        쪽 ``reset_for_turn()`` 이 따로 한다."""
        self.turn_number += 1
        self.turn_player = self.non_turn_player
        self.set_phase(TURN_PHASE_ORDER[0])
        return self

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "TurnState":
        return TurnState(
            turn_number=self.turn_number,
            turn_player=self.turn_player,
            phase=self.phase,
            step=self.step,
        )

    def canonical_state(self) -> tuple:
        return (self.turn_number, self.turn_player, self.phase.value, self.step)

    def __str__(self) -> str:
        return f"T{self.turn_number} P{self.turn_player} {self.phase.value}"
