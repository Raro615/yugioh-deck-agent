"""
ChoicePolicy — **해결 중에 무엇을 고를 것인가** (Phase 6-Y).

    제안: "이것을 지금 써도 된다"         → accept_offer(offer) -> bool
    제안: "이 카드들 중에 고를 수 있다"   → choose_cards(offer) -> (InstanceId, …)

:class:`~agent.policy.Policy` 와 **다른 시점**이다
---------------------------------------------------
``Policy`` 는 *고르는 시점*에 답한다 — "지금 어떤 합법적인 ``PlayerAction``
을 할 것인가". 이쪽은 *해결 시점*에 답한다 — "허용된 후보 중 어느
인스턴스인가". 두 질문의 정보가 다르다:

* 고르는 시점에는 덱이 보이지 않는다 (가려진 존이다).
* 해결 시점에는 규칙이 선언한 ``looked_at`` 이 열려 **그 효과가 볼 수
  있는 것만** 보인다 — 룰북이 그것을 licensing 한다.

그래서 두 시점을 한 프로토콜로 합치지 않는다. 합치면 "덱을 먼저 보고
쓸지 정한다" 가 되고, 그것은 규칙이 허락한 범위가 아니다.

🔴 이 계층은 **제안이 왜 생겼는지 모른다**
--------------------------------------------
제안을 만드는 쪽은 조립 층(``integration``)이고, 그쪽이 사건 · 시점 ·
선언을 읽는다. 이 파일은 그 기계를 **모른다** — 받은 제안의 **모양만**
읽는다 (``offer.permitted`` · ``offer.minimum`` · ``offer.requirement_known``).

그 경계는 이 저장소가 이미 **감사 둘**로 지켜 둔 것이다. ``agent/`` 의 어느
파일도 사건 계층의 어휘도, 규칙이 무엇을 쓰는지를 가리키는 어휘도 **글자로**
쓰지 않는다 — 루트와 엔진의 두 감사가 그 토큰들을 ``agent/`` 전수에서 센다.

🔴 **6-Y 가 그 경계를 두 번 깼다.** 한 번은 사건 쪽 이름으로, 고친 뒤 한
번은 엔진 쪽 이름으로. 그래서 지금 이름은 정책이 **하는 일**만 말한다 —
제안을 받아들이는가. 그 기록은 보고서 부록 A 에 있다.

정책의 말은 허가가 아니다
-------------------------
여기서 고른 것을 그대로 쓰지 않는다. 조립 층이 후보 목록에 있는지 · 장수가
맞는지 · 움직일 수 있다고 판정됐는지 다시 보고, 어긋나면 거절한다. 그 뒤에도
``ChainResolver`` 가 ``TargetResolver`` 와 ``BoardRuling`` 으로 한 번 더 본다.

여기서 하지 않는 것
-------------------
**어느 카드가 좋은지 모른다.** 이 파일의 정책들은 인터페이스가 도는지와
**정책이 달라지면 전개도 달라지는지**를 보이기 위한 기준점이고, 오르페골
전개를 아는 AI 가 아니다. 평가도 탐색도 없다.
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable

from engine.ids import InstanceId


class ChoiceError(RuntimeError):
    """선택 정책을 쓰는 방법이 틀렸을 때."""


@runtime_checkable
class ChoicePolicy(Protocol):
    """해결 시점의 두 질문에 답하는 것."""

    name: str

    def accept_offer(self, offer) -> bool:
        ...  # pragma: no cover - 프로토콜

    def choose_cards(self, offer) -> "tuple[InstanceId, ...]":
        ...  # pragma: no cover - 프로토콜


@runtime_checkable
class ForkablePolicy(Protocol):
    """
    **탐색 사본에서 써도 안전한** 정책 (Phase 6-AB 보완).

    왜 따로 두는가 — 사본은 미래를 재려고 정책에게 묻는다. 정책이 상태를
    들고 있으면 (:class:`RandomChoice` 의 난수원 · 센 횟수) 그 물음이
    **진짜 듀얼의 정책을 앞으로 밀어 버린다.** 실측한 증상: 상태 있는
    정책으로 ``Simulator.simulate`` 를 한 번 돌리자 부모 정책의 호출 수가
    0 → 1 이 됐다. 그러면 같은 자리에서 다시 두었을 때 다른 답이 나온다.

    🔴 **"상태가 없으니 공유해도 된다" 를 사본 쪽에서 추측하지 않는다.**
    모양이 ``accept_offer`` · ``choose_cards`` 둘뿐이면 상태가 있는지 알
    방법이 없다. 그래서 **정책이 직접 말하게** 한다: :meth:`forked` 가
    있으면 사본용 정책을 받아 쓰고, 없으면 사본은 그 정책을 쓰지 않는다.

    무상태 정책은 ``self`` 를 돌려주면 된다 (:class:`FirstPermittedChoice` ·
    :class:`DeclineChoice`). 상태 있는 정책은 사본용 사본을 만들어야 한다
    (:class:`RandomChoice` 가 씨앗을 갈라 쓴다).
    """

    def forked(self) -> "ChoicePolicy":
        ...  # pragma: no cover - 프로토콜


#: 사본용 씨앗을 만들 때 부모의 씨앗에 곱하는 수 (Phase 6-AB 보완).
#:
#: 소수를 쓰는 이유는 하나다 — 부모 씨앗과 뽑은 횟수의 조합이 서로 겹치지
#: 않게 하는 것. 전략적 의미는 없고, 난수의 품질을 주장하지도 않는다.
_FORK_SEED_STRIDE = 1_000_003


def _take(offer, instances) -> "tuple[InstanceId, ...]":
    """
    정확히 ``minimum`` 장만 집는다.

    🔴 **더 집지 않는다.** 최대까지 고를 수 있어도 "많이 고르는 것이 좋다"
    는 전략 주장이고, 이 파일은 그 주장을 하지 않는다.
    """
    return tuple(instances[: offer.minimum])


class FirstPermittedChoice:
    """
    **허용된 후보의 앞쪽**을 집고, 제안은 **언제나 받아들인다.**

    후보 순서는 관측의 순서다 (``CandidateResolver`` 가 존을 훑는 순서),
    그래서 같은 판이면 같은 선택이 나온다.

    🔴 **"언제나 받아들인다" 는 전략이 아니라 기준점이다.** 그것이 강제인지
    임의인지를 가르는 지식이 이 엔진에 없고 (제안의 ``requirement_known``
    이 거짓이다), 이 정책은 그 모름을 **자기 선택으로** 메꾼다 — 규칙이
    강제한다고 주장하지 않는다.
    """

    __slots__ = ("name",)

    def __init__(self, name: str = "first-permitted"):
        self.name = name

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer) -> "tuple[InstanceId, ...]":
        return _take(offer, [c.instance for c in offer.permitted])

    def forked(self) -> "FirstPermittedChoice":
        """
        **자기 자신**이다 — 이 정책은 상태를 들고 있지 않다 (``__slots__``
        가 이름 하나뿐이고, 두 답이 모두 제안만 보고 나온다).

        🔴 그 사실을 **정책이 말한다.** 사본 쪽에서 "무상태인 것 같다" 고
        추측하지 않는다 (:class:`ForkablePolicy` 의 설명).
        """
        return self

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name}>"


class DeclineChoice:
    """
    **아무 제안도 받아들이지 않는다.** 대조군이다.

    쓸모는 하나다 — 그것이 **선택**임을 보이는 것. 이 정책으로 돌린 판에서
    카드가 움직이지 않으면, 움직인 판의 그 이동은 정책의 결정이다.
    """

    __slots__ = ("name",)

    def __init__(self, name: str = "decline"):
        self.name = name

    def accept_offer(self, offer) -> bool:
        return False

    def choose_cards(self, offer) -> "tuple[InstanceId, ...]":
        return ()

    def forked(self) -> "DeclineChoice":
        """**자기 자신**이다 — 상태가 없다 (``FirstPermittedChoice`` 와 같다)."""
        return self

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name}>"


class RandomChoice:
    """
    허용된 후보 중 **무작위로** 집는다. 제 난수원을 쓴다.

    씨앗이 **필수**다 — :class:`~agent.policy.RandomPolicy` 와 같은 이유이고,
    같은 규율이다 (Phase 2-Z). 듀얼의 난수원을 빌려 쓰면 정책이 한 번 더
    생각했다는 이유로 덱 셔플이 달라진다.
    """

    __slots__ = ("name", "_rng", "_draws", "_seed")

    def __init__(self, seed: int, name: str = "random-choice"):
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ChoiceError(f"씨앗은 정수입니다: {seed!r}")
        self.name = name
        self._rng = random.Random(seed)
        self._draws = 0
        #: 🔴 **씨앗을 들고 있는다** (Phase 6-AB 보완). :meth:`forked` 가
        #: 사본용 씨앗을 이것에서 **산술로** 만든다 — 그래야 다른 프로세스
        #: 에서도 같은 값이 나온다 (아래 설명).
        self._seed = seed

    @property
    def seed(self) -> int:
        """이 정책이 받은 씨앗. 재현의 좌표다."""
        return self._seed

    @property
    def draws(self) -> int:
        """몇 번 뽑았는가. 정책이 **생각한 양**이지 듀얼의 좌표가 아니다."""
        return self._draws

    def accept_offer(self, offer) -> bool:
        self._draws += 1
        return bool(self._rng.randrange(2))

    def choose_cards(self, offer) -> "tuple[InstanceId, ...]":
        permitted = [c.instance for c in offer.permitted]
        if not permitted:
            return ()
        self._draws += 1
        order = list(permitted)
        self._rng.shuffle(order)
        return _take(offer, order)

    def forked(self) -> "RandomChoice":
        """
        🔴 **사본용 난수원을 따로 만든다** (Phase 6-AB 보완).

        이 정책은 상태를 들고 있다 — 난수원과 센 횟수. 공유하면 사본이 미래를
        재려고 뽑은 난수가 **진짜 듀얼의 다음 선택을 바꾼다.**

        씨앗은 **받은 씨앗과 지금까지 뽑은 횟수에서 산술로** 만든다. 그래서
        (1) 같은 자리에서 포크하면 같은 사본 정책이 나오고 (재현된다),
        (2) 다른 자리에서 포크하면 다른 사본 정책이 나오고,
        (3) 부모의 ``draws`` 는 **변하지 않는다.**

        🔴 부모의 난수원을 뽑아서 씨앗을 만들지 않는다 — 뽑는 순간 부모가
        앞으로 밀린다. 그것이 고치려는 결함이다.

        🔴 **``hash()`` 를 쓰지 않는다.** 처음에는
        ``hash((self.name, self._draws))`` 로 만들었는데, 파이썬은 문자열
        해시에 **프로세스마다 다른 소금**을 넣는다 (``PYTHONHASHSEED``).
        그러면 같은 자리에서 포크해도 **실행마다 다른 사본**이 나와, 바로
        위에서 약속한 재현이 깨진다. 산술이면 깨지지 않는다.
        """
        return RandomChoice(
            seed=self._seed * _FORK_SEED_STRIDE + self._draws + 1,
            name=f"{self.name}-fork",
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name} draws={self._draws}>"


__all__ = [
    "ChoiceError",
    "ChoicePolicy",
    "ForkablePolicy",
    "FirstPermittedChoice",
    "DeclineChoice",
    "RandomChoice",
]
