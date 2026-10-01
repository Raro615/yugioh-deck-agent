"""
Simulation — **후보 하나를 실제 엔진으로 해 보는 자리** (Phase 3-C).

    Original Duel
         │  clone()
         ├──→ Fork A ──apply(A)──→ GameStateView(viewer)
         ├──→ Fork B ──apply(B)──→ GameStateView(viewer)
         └──→ Fork C ──apply(C)──→ GameStateView(viewer)

가장 중요한 불변조건
--------------------
**SEARCH MUST NEVER CHANGE THE REAL GAME.**

그래서 되감지 않는다. 원본에 적용한 뒤 되돌리는 방식은 "되돌리기가 완전
한가" 를 영원히 증명해야 하는 빚을 지는데, :meth:`GameState.clone` 은 그
빚이 없다 — 원본을 **건드리지 않으므로** 되돌릴 것이 없다 (§10).

난수원을 함께 쓰지 않는다
-------------------------
``GameState`` 에는 복제가 둘 있고, 하나는 **써서는 안 된다.**

``project()``   난수원을 원본과 **함께 쓴다.** 효과 해결의 계획 단계를
                위한 것이고(Phase 2-AH), 탐색에 쓰면 시뮬레이션이 꺼낸
                난수가 진짜 판의 좌표를 밀어 버린다 — 같은 seed 로 다시
                돌렸을 때 다른 판이 된다.
``clone()``     난수원을 **꺼낸 횟수까지 복제한다.** 탐색이 쓸 것은 이쪽이다.

측정으로 확인했다: 사본에서 셔플하면 사본의 ``draws`` 만 올라가고 원본은
그대로다. ``project()`` 로 같은 일을 하면 **원본의 ``draws`` 가 올라간다.**

가짜 실행기를 만들지 않는다
---------------------------
``fake_apply`` · ``simple_apply`` · ``estimated_apply`` 를 두지 않는다
(§15). 사본에 적용하는 것은 진짜 :meth:`Duel.apply` 이고, 그래서
시뮬레이션이 본 미래는 **그 수를 진짜로 두었을 때의 미래와 같다.** 다르면
AI 는 있지도 않은 미래를 보고 판단한다.

내다본 결과로 넘기는 것은 **관측뿐이다**
----------------------------------------
:class:`SimulationResult` 는 사본의 ``GameState`` 를 들고 있지 않다.
들고 있으면 탐색 정책이 그것을 통해 상대 패를 읽을 수 있고, 그러면
"시뮬레이션을 갖고 있다" 는 이유로 관측 경계가 사라진다 (§18). 사본은
관측을 뜬 뒤 버려진다.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum

from engine.action import PlayerAction
from engine.duel import Duel, DuelStep, LegalActions
from engine.game_state_view import GameStateView
from engine.validation import ValidationCode


class SimulationError(RuntimeError):
    """시뮬레이터를 잘못 쓸 때."""


class SimulationStatus(str, Enum):
    """
    후보 하나를 해 본 결과가 **어떻게 끝났는가.**

    실패를 한 칸으로 뭉치지 않는다 (§17). "허가된 후보가 아니다" 와
    "규칙이 아직 없다" 와 "예외가 났다" 는 전부 다른 사실이고, 어느 것도
    **자동으로 최악의 점수가 되지 않는다.**
    """

    SUPPORTED = "supported"
    """엔진이 적용했다. 미래 상태를 볼 수 있다."""
    NOT_A_CANDIDATE = "not_a_candidate"
    """지금 허가된 후보가 아니다. 탐색이 만들어 낸 수라는 뜻이다 (§16 · §47)."""
    UNKNOWN = "unknown"
    """규칙이 아직 없다. **모른다는 것이지 나쁘다는 것이 아니다** (§17 · §28)."""
    REFUSED = "refused"
    """엔진이 규칙에 따라 거절했다."""
    ERROR = "error"
    """실행 중 예외가 났다. 숨기지 않는다."""

    @property
    def gives_a_future(self) -> bool:
        """미래 상태를 볼 수 있는가."""
        return self is SimulationStatus.SUPPORTED


#: 엔진이 "아직 규칙이 없다" 고 말하는 코드들. 이것을 거절과 섞지 않는다.
_UNKNOWN_CODES: frozenset[ValidationCode] = frozenset(
    {
        ValidationCode.RULE_NOT_IMPLEMENTED,
        ValidationCode.COST_NOT_IMPLEMENTED,
        ValidationCode.INFORMATION_UNAVAILABLE,
        ValidationCode.CARD_DEFINITION_UNAVAILABLE,
        ValidationCode.EFFECT_LIST_UNRELIABLE,
    }
)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """
    후보 하나를 해 본 결과. **사본의 판을 들고 있지 않다.**

    :attr:`future` 는 그 수를 둔 **뒤의 관측**이고, 보는 사람은
    :attr:`viewer` 다. 성공하지 못했으면 ``None`` 이다 — 없는 미래를
    꾸며 내지 않는다.
    """

    action: PlayerAction
    status: SimulationStatus
    viewer: int
    reason: str = ""
    code: "ValidationCode | None" = None
    future: "GameStateView | None" = None

    def __post_init__(self) -> None:
        if self.status.gives_a_future and self.future is None:
            raise SimulationError(
                "적용에 성공했는데 미래 관측이 없습니다 — 둘은 함께 옵니다."
            )
        if not self.status.gives_a_future and self.future is not None:
            raise SimulationError(
                f"{self.status.value} 인데 미래 관측이 있습니다 — "
                "실패한 시뮬레이션의 미래를 꾸며 내지 않습니다."
            )

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return f"{self.action} → {self.status.value}" + (
            f" ({self.reason})" if self.reason else ""
        )


@dataclass
class Simulator:
    """
    듀얼 하나에 묶여, **후보를 해 보고 관측만 돌려주는** 좁은 창.

    탐색 정책이 :class:`Duel` 을 직접 들지 않는 이유가 이 클래스다. 정책이
    듀얼을 들면 ``apply`` 로 진짜 판을 바꿀 수 있고, ``state`` 로 상대 패를
    읽을 수 있다. 이 창은 둘 다 **줄 수 없는 모양**이다 —
    :meth:`simulate` 가 돌려주는 것은 관측과 상태 하나뿐이다.

    :attr:`simulations` 는 몇 번 해 봤는지의 셈이다. 판단에 쓰지 않는다.
    """

    duel: Duel
    simulations: int = 0
    _forks: int = 0

    # ------------------------------------------------------------------
    # 읽기 — 진짜 판을 바꾸지 않는 것들만
    # ------------------------------------------------------------------
    def legal_actions(self, seat: int) -> LegalActions:
        return self.duel.legal_actions(seat)

    def view(self, seat: int) -> GameStateView:
        return self.duel.view(seat)

    def state_hash(self) -> str:
        """
        지금 판의 지문. **되돌려 읽을 수 없는 요약**이므로 흔적에 남겨도
        가려진 정보가 새지 않는다 (§31).
        """
        return self.duel.state.state_hash()

    def random_draws(self) -> int:
        """
        진짜 판의 난수원이 **몇 번 꺼냈는가.** 재현의 좌표다.

        탐색이 끝난 뒤 이 값이 그대로여야 한다 (§13 · §14).
        """
        return self.duel.state.randomness.draws

    @property
    def turn_number(self) -> int:
        return self.duel.state.turn.turn_number

    @property
    def phase(self):
        return self.duel.state.turn.phase

    # ------------------------------------------------------------------
    # 포크
    # ------------------------------------------------------------------
    def _fork(self) -> Duel:
        """
        **판만 복제하고 나머지는 그대로 쓴다.**

        ``priority`` 는 frozen 이라 공유해도 바뀌지 않는다. ``_executor``
        는 수행기 등록부일 뿐 듀얼마다 달라지는 상태를 들지 않으므로
        공유하는 것이 오히려 옳다 — 그래야 사본이 **진짜와 같은 규칙**으로
        돈다 (§15).
        """
        self._forks += 1
        return dataclasses.replace(self.duel, state=self.duel.state.clone())

    def simulate(self, action: PlayerAction, *, viewer: int) -> SimulationResult:
        """
        후보 하나를 사본에서 해 본다. **진짜 판은 건드리지 않는다.**

        ``viewer`` 는 미래를 **누구의 눈으로 볼 것인가**다. 두는 사람과
        보는 사람이 다를 수 있으므로 따로 받는다.
        """
        if not isinstance(action, PlayerAction):
            raise SimulationError(
                f"PlayerAction 이 필요합니다: {type(action).__name__}"
            )
        if viewer not in (0, 1):
            raise SimulationError(f"보는 자리는 0 또는 1 입니다: {viewer}")

        self.simulations += 1

        # **후보 목록에 있는지 먼저 본다.** 엔진의 ``apply`` 도 다시 보지만,
        # 거기서는 "허가된 후보가 아니다" 가 "규칙이 없다" 와 같은 코드로
        # 나와서 둘을 가를 수 없다 (§16 · §47).
        legal = self.duel.legal_actions(action.actor)
        if action not in legal.allowed:
            return SimulationResult(
                action=action,
                status=SimulationStatus.NOT_A_CANDIDATE,
                viewer=viewer,
                reason="지금 허가된 후보가 아닙니다 — 탐색은 후보만 해 봅니다.",
            )

        fork = self._fork()
        try:
            step: DuelStep = fork.apply(action)
        except Exception as error:  # noqa: BLE001 - 숨기지 않고 상태로 남긴다
            return SimulationResult(
                action=action,
                status=SimulationStatus.ERROR,
                viewer=viewer,
                reason=f"{type(error).__name__}: {error}",
            )

        if step.accepted:
            return SimulationResult(
                action=action,
                status=SimulationStatus.SUPPORTED,
                viewer=viewer,
                reason=step.reason,
                code=step.code,
                # 사본은 여기서 버려진다. 넘어가는 것은 관측뿐이다.
                future=fork.view(viewer),
            )

        status = (
            SimulationStatus.UNKNOWN
            if step.code in _UNKNOWN_CODES
            else SimulationStatus.REFUSED
        )
        return SimulationResult(
            action=action,
            status=status,
            viewer=viewer,
            reason=step.reason,
            code=step.code,
        )

    def fork_after(self, action: PlayerAction) -> "Simulator | None":
        """
        그 수를 둔 **사본에 묶인 새 시뮬레이터**. 깊이를 늘릴 자리다.

        Phase 3-C 의 :class:`~agent.search.SearchPolicy` 는 ``depth=1`` 만
        지원하므로 **이것을 부르지 않는다.** 그래도 두는 이유는 깊이를
        늘리는 일이 "구조를 새로 만드는 일" 이 아님을 보이기 위해서다 —
        depth-2 는 이 메서드를 한 번 더 부르는 것이고, 그때도 정책에게
        가는 것은 여전히 관측뿐이다.

        적용에 실패하면 ``None`` 이다. 실패한 미래를 이어 가지 않는다.
        """
        fork = self._fork()
        try:
            step = fork.apply(action)
        except Exception:  # noqa: BLE001
            return None
        if not step.accepted:
            return None
        return Simulator(duel=fork)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<Simulator 시뮬레이션 {self.simulations}회 포크 {self._forks}회>"


__all__ = [
    "SimulationError",
    "SimulationStatus",
    "SimulationResult",
    "Simulator",
]
