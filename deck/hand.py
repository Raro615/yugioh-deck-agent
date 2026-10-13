"""
초기 패를 **받는 자리** (Phase 4-B).

🔴 **이번 단계에서 구현한 것은 "사용자가 지정한 패를 그대로 돌려주는"
경로 하나다.** 덱에서 무작위로 패를 뽑는 기능은 **구현하지 않았다** —
지원하는 것처럼 적지 않는다.

왜 경계를 따로 두는가
---------------------
:class:`~deck.planner.ComboPlanner` 가 패를 **스스로 만들면**, 나중에
무작위 패를 넣을 때 플래너를 고쳐야 한다. 그리고 난수원이 플래너 안에
생기면 "전개 계획을 한 번 더 돌렸다" 는 이유로 패가 달라진다. 그래서
플래너는 패를 **받기만** 한다.

경계는 하나다. 구현체가 하나뿐인 인터페이스를 여러 겹으로 쌓지 않는다.

후속 단계에서 무작위 패를 넣을 자리
-----------------------------------
:class:`HandProvider` 를 만족하는 구현을 **하나 더** 추가하면 된다.
플래너도 모델도 고치지 않는다.

그때 지켜야 할 것: 난수원을 **스스로 들고** 다녀야 한다.
:class:`~engine.randomness.RandomPurpose` 는 ``AI_*`` 를 일부러 넣지
않았고("탐색·정책의 무작위는 규칙의 무작위와 다른 계층이고, 한 열거형에
섞으면 같은 난수원을 쓰게 된다"), :class:`~agent.policy.RandomPolicy` 가
그 결정에 따라 제 ``random.Random`` 을 들고 다닌다. 패 생성도 **같은 쪽**
이다 — 덱 셔플의 난수원을 빌려 쓰면 패를 한 번 더 뽑았다는 이유로 듀얼의
셔플 결과가 달라진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class HandProvider(Protocol):
    """초기 패 하나를 내놓는 것. 카드 ID 목록을 돌려준다."""

    def hand(self) -> list[int]:
        """
        이번 계획에 쓸 초기 패.

        🔴 **장수를 보장하지 않는다.** 몇 장인지는 구현과 입력이 정한다 —
        부르는 쪽이 특정 장수를 가정하면 안 된다 (:mod:`deck.planner` 의
        설명 참고).
        """
        ...


@dataclass(frozen=True, slots=True)
class FixedHand:
    """
    사용자가 지정한 패를 그대로 내놓는다. **이번 단계의 유일한 구현.**

    빈 패도 그대로 돌려준다 — "비었으면 뽑아 준다" 를 여기서 하면 입력과
    생성이 다시 섞인다.
    """

    card_ids: tuple[int, ...] = ()

    def hand(self) -> list[int]:
        return list(self.card_ids)

    def __len__(self) -> int:
        return len(self.card_ids)
