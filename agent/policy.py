"""
Policy — **AI 가 엔진을 보는 유일한 창** (Phase 3-A).

    GameStateView(viewer)  +  LegalActions
            ↓  Policy.decide(...)
        PlayerAction

정책이 받는 것은 **관측과 후보 목록 둘뿐**이다. :class:`~engine.duel.Duel`
도 :class:`~engine.state.game_state.GameState` 도 받지 않는다 — 받으면
정책이 판을 읽거나 바꿀 수 있고, 그 순간 "AI 가 엔진을 쓴다" 가 "AI 가
엔진이다" 가 된다.

난수원을 섞지 않는다
--------------------
정책의 무작위는 **듀얼의 무작위와 다른 난수원**을 쓴다. 이것은 이번에
정한 것이 아니라 :class:`~engine.randomness.RandomPurpose` 가 이미 적어 둔
결정이다.

    "``AI_*`` 를 여기 두지 않는다. 탐색·정책의 무작위는 규칙의 무작위와
     다른 계층이고, 한 열거형에 섞으면 같은 난수원을 쓰게 된다 — 그러면
     AI 가 한 번 더 생각했다는 이유로 듀얼의 결과가 달라진다."

그래서 :class:`RandomPolicy` 는 제 ``random.Random`` 을 들고 다닌다. 정책이
몇 번을 더 뽑든 덱 셔플은 그대로다.

정책의 말은 허가가 아니다
-------------------------
:meth:`Policy.decide` 가 돌려준 것을 **그대로 적용하지 않는다.**
:class:`~agent.runner.DuelRunner` 가 후보 목록에 있는지 다시 보고, 없으면
거절한다 — 엔진이 ``UNKNOWN`` 을 허가로 바꾸지 않는 것과 같은 자리다.

여기서 하지 않는 것
-------------------
**잘 두는 법을 모른다.** 이 파일에 있는 정책 둘은 인터페이스가 도는지
보이기 위한 **기준점**이지 AI 가 아니다. 평가 함수도, 탐색도, 학습도 없다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import LegalActions
from engine.game_state_view import GameStateView


class PolicyError(RuntimeError):
    """정책이 규약을 어겼을 때."""


@runtime_checkable
class Policy(Protocol):
    """
    **지금 무엇을 할 것인가**에 답하는 것.

    ``legal.allowed`` 가 비어 있으면 ``None`` 을 돌려준다 — 고를 것이
    없는 것과 "아무것도 안 하겠다" 는 다른 사실이고, 후자는
    :attr:`~engine.action.PlayerActionKind.PASS` 라는 **행위**다.
    """

    name: str

    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        ...  # pragma: no cover - 프로토콜


@dataclass(frozen=True, slots=True)
class Decision:
    """정책이 고른 것과 **왜 그것이 받아들여졌는가 / 아닌가.**"""

    seat: int
    policy: str
    action: "PlayerAction | None"
    accepted: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.accepted


# ======================================================================
# 기준점 정책들 — AI 가 아니다
# ======================================================================


class FirstLegalPolicy:
    """
    **언제나 목록의 첫 번째**를 고른다. 가장 단순한 기준점이다.

    쓸모는 하나다 — 인터페이스가 도는지, 그리고 **정책이 달라지면 듀얼도
    달라지는지**를 보이는 것.
    """

    __slots__ = ("name",)

    def __init__(self, name: str = "first-legal"):
        self.name = name

    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        return legal.allowed[0] if legal.allowed else None

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name}>"


class RandomPolicy:
    """
    후보 중 하나를 **무작위로** 고른다. 제 난수원을 쓴다.

    씨앗이 **필수**다. 씨앗 없는 무작위는 재현할 수 없고, 이 저장소는
    그것을 다른 모든 자리에서 이미 거부한다 (Phase 2-Z).
    """

    __slots__ = ("name", "_rng", "_draws")

    def __init__(self, seed: int, name: str = "random"):
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise PolicyError(f"씨앗은 정수입니다: {seed!r}")
        self.name = name
        # **듀얼의 난수원이 아니다.** 엔진의 RandomSource 를 빌려 쓰면
        # 정책이 한 번 더 생각했다는 이유로 덱 셔플이 달라진다.
        self._rng = random.Random(seed)
        self._draws = 0

    @property
    def draws(self) -> int:
        """몇 번 뽑았는가. 정책이 **생각한 양**이지 듀얼의 좌표가 아니다."""
        return self._draws

    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        if not legal.allowed:
            return None
        self._draws += 1
        return legal.allowed[self._rng.randrange(len(legal.allowed))]

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name} draws={self._draws}>"


class ScriptedPolicy:
    """
    미리 정한 순서대로 고른다. **시험과 재현**을 위한 것이다.

    목록이 떨어지면 ``fallback`` 으로 넘어간다 — 떨어졌다고 멈추면 듀얼이
    끝나지 않는다.
    """

    __slots__ = ("name", "_plan", "_at", "_fallback")

    def __init__(
        self,
        plan: "tuple[PlayerActionKind, ...]",
        *,
        fallback: "Policy | None" = None,
        name: str = "scripted",
    ):
        self.name = name
        self._plan = tuple(plan)
        self._at = 0
        self._fallback = fallback if fallback is not None else FirstLegalPolicy()

    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        if not legal.allowed:
            return None
        while self._at < len(self._plan):
            wanted = self._plan[self._at]
            self._at += 1
            for action in legal.allowed:
                if action.kind is wanted:
                    return action
        return self._fallback.decide(view, legal)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name} {self._at}/{len(self._plan)}>"


__all__ = [
    "Policy",
    "PolicyError",
    "Decision",
    "FirstLegalPolicy",
    "RandomPolicy",
    "ScriptedPolicy",
]
