"""
게임 규칙의 무작위 — **재현 가능한** 난수 (Phase 2-Z).

    seed  →  RandomSource  →  RandomOutcome  →  EventJournal
                    ↓
              Operation → StateDelta → ObservedEvent   (기존 통로 그대로)

두 원칙이 이 파일의 전부다.

1. **랜덤이어도 재현 가능해야 한다.**
   같은 seed · 같은 상태 · 같은 순서의 요청이면 언제나 같은 결과다.
   전역 :mod:`random` 을 쓰지 않는다 — 다른 코드가 전역 상태를 건드리면
   재현이 깨진다.

2. **게임의 랜덤과 AI 의 랜덤은 다른 계층이다.**
   여기 있는 것은 *규칙이 요구하는* 무작위뿐이다: 덱 셔플, "무작위로 1장".
   탐색 · 정책 · 시뮬레이션의 무작위는 여기 오지 않는다
   (:class:`RandomPurpose` 가 그 경계를 값으로 들고 있다).

카드를 모른다
-------------
:class:`RandomSource` 는 **카드를 보지 않는다.** 원시 연산이 돌려주는 것은
자리 번호(index)와 순열뿐이고, 그것을 카드에 대응시키는 일은 부르는 쪽이
한다.

그래서 난수원을 통해 숨은 정보가 샐 수 없다 — 애초에 정체를 손에 쥐지
않기 때문이다. 정체가 붙는 것은 :class:`RandomOutcome` 이고, 그것은
**엔진 내부 기록**이지 관측이 아니다.

판의 해시에 들어가지 않는다
---------------------------
난수원의 위치는 **판의 모양이 아니라 흐름의 위치**다. ``chain`` ·
``journal`` · ``priority`` 를 :meth:`~engine.state.game_state.GameState.
state_hash` 에서 뺀 것과 같은 이유로 여기도 뺀다 — 넣으면 "같은 판은
어떤 경로로 왔든 같은 해시" 가 깨진다. 판이 똑같은데 드로우를 몇 번
했느냐로 해시가 달라지면 그것은 판의 해시가 아니다.

대신 :meth:`RandomSource.canonical_state` 가 따로 있다. 재현과 시험이
난수원의 위치를 **값으로** 비교할 수 있어야 하기 때문이고, 그 값은
객체 주소도 ``repr`` 도 아닌 :meth:`random.Random.getstate` 의 내용에서
나온다.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from engine.ids import InstanceId


class RandomError(RuntimeError):
    """무작위를 꺼낼 수 없는 상태에서 꺼내려 했다."""


class RandomPurpose(str, Enum):
    """
    이 무작위는 **무엇의 것인가.**

    ``AI_*`` 를 여기 두지 않는다. 탐색·정책의 무작위는 규칙의 무작위와
    다른 계층이고, 한 열거형에 섞으면 같은 난수원을 쓰게 된다 — 그러면
    AI 가 한 번 더 생각했다는 이유로 듀얼의 결과가 달라진다.
    """

    DECK_SHUFFLE = "deck_shuffle"
    """덱을 섞는다 (룰북: "shuffle it and put it back in this space")."""
    RANDOM_SELECTION = "random_selection"
    """"무작위로 1장 고른다" — 고르는 사람이 없는 선택."""

    def describe_ko(self) -> str:
        return {
            RandomPurpose.DECK_SHUFFLE: "덱 셔플",
            RandomPurpose.RANDOM_SELECTION: "무작위 선택",
        }[self]


@dataclass(frozen=True, slots=True)
class RandomOutcome:
    """
    무작위 하나의 결과. **엔진 내부 기록이지 관측이 아니다.**

    :attr:`draw` 가 재현 좌표다 — "이 듀얼의 seed 로 만든 난수원에서
    ``draw`` 번째로 꺼낸 것" 이라는 뜻이고, 실패한 시나리오를 그 번호로
    정확히 되짚을 수 있다.

    :attr:`candidates` 와 :attr:`selected` 는 :class:`InstanceId` 다 —
    ``card_id`` 를 담지 않는다. 정체는 애초에 여기 오지 않는다.
    """

    purpose: RandomPurpose
    draw: int
    """이 듀얼의 난수원에서 **몇 번째** 꺼낸 것인가 (0 부터)."""
    candidates: tuple[InstanceId, ...]
    """무엇들 중에서 골랐는가. 순서가 결정론의 일부다."""
    selected: tuple[InstanceId, ...]
    """골라진 것 (셔플이면 **새 순서 전체**)."""

    def __post_init__(self) -> None:
        if self.draw < 0:
            raise ValueError(f"draw 는 음수일 수 없습니다: {self.draw}")
        unknown = set(self.selected) - set(self.candidates)
        if unknown:
            raise ValueError(
                "후보에 없던 것이 골라졌습니다: "
                f"{sorted(i.value for i in unknown)}"
            )
        if self.purpose is RandomPurpose.DECK_SHUFFLE and len(
            self.selected
        ) != len(self.candidates):
            raise ValueError(
                "셔플은 카드를 잃거나 만들지 않습니다: "
                f"{len(self.candidates)} → {len(self.selected)}"
            )

    @property
    def size(self) -> int:
        return len(self.candidates)

    def canonical_state(self) -> tuple:
        return (
            self.purpose.value,
            self.draw,
            tuple(i.value for i in self.candidates),
            tuple(i.value for i in self.selected),
        )

    def to_dict(self) -> dict:
        """
        **엔진 내부용이다.** 정체(``InstanceId``)가 그대로 들어 있으므로
        플레이어에게 그대로 건네면 안 된다 — 관측으로 나갈 때는
        :meth:`public_summary` 를 쓴다.
        """
        return {
            "purpose": self.purpose.value,
            "draw": self.draw,
            "candidates": [i.value for i in self.candidates],
            "selected": [i.value for i in self.selected],
        }

    def public_summary(self) -> dict:
        """
        **누구에게 보여도 되는 만큼.** 몇 장 중에 몇 장이 골라졌는가만
        말하고, 무엇이 골라졌는지는 말하지 않는다.

        "상대 패에서 무작위로 1장" 이 실제로 무엇이었는지는 그 카드가
        공개되는 규칙이 따로 있을 때만 알려진다 — 무작위였다는 사실이
        정체를 공개하는 근거가 되지는 않는다.
        """
        return {
            "purpose": self.purpose.value,
            "candidate_count": len(self.candidates),
            "selected_count": len(self.selected),
        }

    def describe_ko(self) -> str:
        return (
            f"{self.purpose.describe_ko()} #{self.draw} "
            f"({len(self.candidates)}장 중 {len(self.selected)}장)"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class RandomSource:
    """
    이 듀얼 전용 난수원. **카드를 보지 않는다.**

    원시 연산(:meth:`next_index` · :meth:`next_permutation`)은 자리 번호만
    다루고, 정체가 붙은 :class:`RandomOutcome` 은 그 위에 얹힌다.

    ``draws`` 는 **꺼낸 횟수**다 — 원시 난수의 소비 횟수가 아니라 요청
    횟수다. 재현할 때 "몇 번째 무작위에서 갈렸는가" 를 세는 좌표이므로
    구현이 바뀌어도 뜻이 흔들리지 않아야 한다.
    """

    __slots__ = ("_rng", "_draws")

    def __init__(self, rng: random.Random, draws: int = 0):
        if not isinstance(rng, random.Random):
            raise TypeError(
                "RandomSource 는 random.Random 을 받습니다. 전역 random 모듈을 "
                "넘기면 다른 코드가 전역 상태를 건드릴 때 재현이 깨집니다."
            )
        if draws < 0:
            raise ValueError(f"draws 는 음수일 수 없습니다: {draws}")
        self._rng = rng
        self._draws = draws

    @classmethod
    def seeded(cls, seed: int) -> "RandomSource":
        """seed 하나에서 만든다. 같은 seed 는 언제나 같은 난수원이다."""
        return cls(random.Random(seed))

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def draws(self) -> int:
        """지금까지 몇 번 꺼냈는가. 다음 결과의 :attr:`RandomOutcome.draw`."""
        return self._draws

    @property
    def raw(self) -> random.Random:
        """
        바탕이 되는 :class:`random.Random`.

        **엔진 코드는 이것을 쓰지 않는다.** 여기서 직접 꺼내면 :attr:`draws`
        가 세지 않아 재현 좌표가 어긋난다. 상태 복제와 시험만 쓴다.
        """
        return self._rng

    # ------------------------------------------------------------------
    # 원시 — 자리 번호만 다룬다
    # ------------------------------------------------------------------
    def next_index(self, size: int) -> int:
        """``0 <= i < size`` 하나. 크기가 0 이면 거부한다."""
        if size <= 0:
            raise RandomError(
                f"고를 것이 없습니다 (size={size}). 빈 후보에서 무작위로 "
                "고를 수 없고, 조용히 아무것도 고르지 않은 척하지도 않습니다."
            )
        self._draws += 1
        return self._rng.randrange(size)

    def next_permutation(self, size: int) -> tuple[int, ...]:
        """
        ``0..size-1`` 의 순열 하나.

        **자리 번호만 섞는다.** 무엇이 그 자리에 있었는지는 모른다.
        """
        if size < 0:
            raise ValueError(f"size 는 음수일 수 없습니다: {size}")
        self._draws += 1
        order = list(range(size))
        self._rng.shuffle(order)
        return tuple(order)

    # ------------------------------------------------------------------
    # 정체가 붙은 결과
    # ------------------------------------------------------------------
    def choose(
        self,
        candidates: Sequence[InstanceId],
        purpose: RandomPurpose = RandomPurpose.RANDOM_SELECTION,
    ) -> RandomOutcome:
        """
        후보 중 하나를 무작위로 고른다.

        **후보의 순서가 결정론의 일부다.** 같은 집합이라도 순서가 다르면
        다른 답이 나오므로, 부르는 쪽이 정해진 순서로 넘겨야 한다
        (:class:`~engine.cost.resolver.CandidateResolver` 가 이미
        ``(컨트롤러, 존 순서, sequence, instance_id)`` 로 정렬해 준다).
        """
        ordered = tuple(candidates)
        draw = self._draws
        index = self.next_index(len(ordered))
        return RandomOutcome(
            purpose=purpose,
            draw=draw,
            candidates=ordered,
            selected=(ordered[index],),
        )

    def choose_many(
        self,
        candidates: Sequence[InstanceId],
        count: int,
        replacement: bool = False,
        purpose: RandomPurpose = RandomPurpose.RANDOM_SELECTION,
    ) -> RandomOutcome:
        """
        후보 중 ``count`` 개를 무작위로 고른다 (Phase 2-AB).

        ``replacement`` 가 거짓이면 같은 카드를 두 번 고르지 않는다 — 한
        장의 카드를 두 번 버릴 수는 없다. 참이면 같은 것이 다시 나올 수
        있다 (주사위처럼 **뽑고 되돌리는** 경우).

        **한 번 부를 때 ``count`` 만큼 꺼낸다.** 재현 좌표(:attr:`draw`)는
        첫 꺼냄의 번호이고, 되짚을 때 그 번호부터 ``count`` 번 꺼내면 같은
        답이 나온다.

        :meth:`choose` 와 같은 일을 하되 수가 늘었을 뿐이다 — 한 장을 고르는
        것은 ``count=1`` 이다.
        """
        ordered = tuple(candidates)
        if count < 0:
            raise ValueError(f"고를 수는 음수일 수 없습니다: {count}")
        if not replacement and count > len(ordered):
            raise RandomError(
                f"{len(ordered)}개 중에서 {count}개를 **겹치지 않게** 고를 수 "
                "없습니다. 없는 것을 있는 척 고르지 않습니다."
            )
        draw = self._draws
        picked: list[InstanceId] = []
        if replacement:
            for _ in range(count):
                picked.append(ordered[self.next_index(len(ordered))])
        else:
            remaining = list(ordered)
            for _ in range(count):
                picked.append(remaining.pop(self.next_index(len(remaining))))
        return RandomOutcome(
            purpose=purpose,
            draw=draw,
            candidates=ordered,
            selected=tuple(picked),
        )

    def shuffle(
        self,
        cards: Sequence[InstanceId],
        purpose: RandomPurpose = RandomPurpose.DECK_SHUFFLE,
    ) -> RandomOutcome:
        """
        카드들의 **새 순서**를 정한다. 판을 바꾸지 않는다 — 순서를
        돌려줄 뿐이고, 적용은 부르는 쪽(실행기)의 일이다.

        카드가 복제되거나 사라지지 않는다는 것은
        :class:`RandomOutcome` 이 생성 시점에 확인한다.
        """
        ordered = tuple(cards)
        draw = self._draws
        order = self.next_permutation(len(ordered))
        return RandomOutcome(
            purpose=purpose,
            draw=draw,
            candidates=ordered,
            selected=tuple(ordered[i] for i in order),
        )

    # ------------------------------------------------------------------
    # 복제 · 정규 표현
    # ------------------------------------------------------------------
    def clone(self) -> "RandomSource":
        """
        상태째 복제한다. **사본에서 꺼내도 원본의 다음 결과는 그대로다.**
        """
        copy = random.Random()
        copy.setstate(self._rng.getstate())
        return RandomSource(copy, draws=self._draws)

    def canonical_state(self) -> tuple:
        """
        난수원의 위치를 **값으로** 나타낸다.

        객체 주소도 ``repr`` 도 쓰지 않는다 —
        :meth:`random.Random.getstate` 의 내용을 결정론적으로 직렬화해
        요약한다. 같은 논리적 위치면 프로세스를 다시 띄워도 같은 값이다.

        .. note::
           이것은 :meth:`~engine.state.game_state.GameState.canonical_state`
           에 **들어가지 않는다.** 난수원의 위치는 판의 모양이 아니다.
        """
        payload = json.dumps(
            self._rng.getstate(),
            separators=(",", ":"),
            default=list,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return (self._draws, digest)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RandomSource)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<RandomSource draws={self._draws}>"


__all__ = [
    "RandomError",
    "RandomPurpose",
    "RandomOutcome",
    "RandomSource",
]
