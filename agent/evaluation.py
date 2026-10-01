"""
Evaluation — **미래 상태 하나가 나에게 얼마나 좋은가** (Phase 3-C).

    Simulation State  →  GameStateView(viewer)  →  StateValue

평가가 받는 것은 **관측뿐이다.** 시뮬레이션의 ``GameState`` 는 여기 오지
않는다 — 오면 상대 패와 덱이 그대로 보이고, 그 순간 평가 함수가 실제
대전에서 알 수 없는 사실로 점수를 낸다 (§18).

끝난 판은 숫자가 아니라 등급이다
---------------------------------
승리를 "매우 큰 수" 로 적는 흔한 방식을 쓰지 않는다. 그 수는 휴리스틱
항이 자라면 **조용히 추월당하고**, 그때 AI 는 이기는 수를 버린다. 그래서
:class:`Terminal` 을 **등급**으로 두고, 비교는 ``(등급, 휴리스틱)`` 순서로
한다 — 등급이 다르면 휴리스틱을 아예 보지 않으므로 추월이 불가능하다.

    WIN  >  ONGOING  >  DRAW  >  LOSS

``DRAW`` 가 ``ONGOING`` 보다 아래인 이유: **진행 중인 판은 아직 이길 수
있고, 무승부는 더 이상 이길 수 없다.**

모든 항은 LP 로 환산한다
------------------------
가중치를 임의의 점수로 두면 "왜 100 인가" 에 답할 수 없다. 그래서 단위를
**LP** 하나로 통일하고, 각 항은 "이것을 얻기 위해 LP 를 얼마까지 내줄
것인가" 로 적는다. 공격력은 환산이 필요 없다 — **공격력은 그대로 LP 로
들어오는 피해**이므로 1:1 이다 (:data:`ATK_IN_LP`).

덱 장수가 자원 중 가장 무거운 이유
----------------------------------
Phase 3-B 측정에서 **지금 도달 가능한 패배 조건은 덱아웃 하나**였다
(공격이 후보에 없어 LP 가 움직이지 않는다). 룰북도 "A player with no
cards left in their Deck and unable to draw loses the Duel" 이라고 적는다.
그래서 덱에 남은 한 장은 **패의 한 장보다 무겁다** — 패의 자원이면서
동시에 패배로부터의 거리다.

그 결과 드로우는 점수를 **떨어뜨린다**(덱 300 → 패 200). 어색해 보이지만
사실이고, 드로우는 고르는 일이 아니므로 판단을 비틀지도 않는다.

모르는 것을 0 으로 바꾸지 않는다
--------------------------------
공격력이 ``?`` 인 몬스터, 상대의 뒷면 카드처럼 **값을 모르는 것은 합에서
빼고** :attr:`StateValue.excluded` 에 적는다. 0 으로 넣으면 "약하다" 는
거짓이 되고, 큰 수로 넣으면 "강하다" 는 거짓이 된다 (§20 · §28).
빠진 것이 있는 평가는 :attr:`StateValue.partial` 이 참이다.

여기서 하지 않는 것
-------------------
카드 이름을 보지 않는다 (§25). 상대의 가려진 정보를 추측하지 않는다
(§19). 학습하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from engine.game_state_view import CardView, GameStateView, ZoneView


class EvaluationError(RuntimeError):
    """평가를 잘못 요청했을 때."""


class Terminal(str, Enum):
    """
    이 판이 **끝났는가, 끝났다면 나에게 어떻게 끝났는가.**

    숫자가 아니라 등급이다. 등급이 다르면 휴리스틱은 보지 않는다.
    """

    WIN = "win"
    ONGOING = "ongoing"
    DRAW = "draw"
    LOSS = "loss"

    @property
    def rank(self) -> int:
        return _TERMINAL_RANK[self]

    @classmethod
    def of(cls, view: GameStateView) -> "Terminal":
        """
        관측에서 읽는다. ``winner`` 는 **공개된 사실**이다.

        ``is_over`` 인데 ``winner`` 가 없으면 무승부다. 지금 엔진에는 그런
        결과를 만드는 자리가 없지만(측정: 0회), 없는 경우를 조용히
        승리나 패배로 바꾸지 않는다.
        """
        if not view.is_over:
            return cls.ONGOING
        if view.winner is None:
            return cls.DRAW
        return cls.WIN if view.winner == view.viewer else cls.LOSS


_TERMINAL_RANK: "dict[Terminal, int]" = {
    Terminal.WIN: 2,
    Terminal.ONGOING: 1,
    Terminal.DRAW: 0,
    Terminal.LOSS: -1,
}


# ======================================================================
# 가중치 — 단위는 전부 LP 다
# ======================================================================

#: 공격력 1 점의 값. **환산하지 않는다** — 공격력은 그대로 LP 로 들어오는
#: 피해이므로 1:1 이다. 전투가 구현되면 이 등식이 문자 그대로 참이 된다.
ATK_IN_LP: int = 1

#: 필드에 선 몬스터 한 마리의 값(공격력과 **별도**). 공격력이 같아도 몬스터가
#: 하나 더 있는 쪽이 낫다 — 공격을 한 번 더 할 수 있고 한 번 더 막을 수 있다.
MONSTER_IN_LP: int = 500

#: 필드에 놓인 마법 · 함정 한 장의 값. 몬스터보다 낮게 둔 이유는 지금
#: 엔진에서 **발동이 후보에 오르지 않기** 때문이다 (Phase 3-B 측정: 0회) —
#: 놓여 있다는 사실 자체의 값만 센다.
SPELL_TRAP_IN_LP: int = 300

#: 덱에 남은 한 장의 값. **자원 중 가장 무겁다** — 지금 도달 가능한 패배
#: 조건이 덱아웃 하나이므로, 덱의 한 장은 패배로부터의 거리 1 이다.
DECK_CARD_IN_LP: int = 300

#: 내 패의 한 장. 아직 쓸 수 없는 자원이므로 덱보다 가볍다. **상대 패는
#: 세지 않는다** — 장수는 보이지만 그 값을 매기려면 내용을 알아야 한다.
HAND_CARD_IN_LP: int = 200

#: 묘지 · 제외 존의 한 장. 공개 정보지만 지금 엔진에서 되살릴 수단이
#: 후보에 오르지 않으므로 **값을 0 으로 두지 않고 세지 않는다** — 세지
#: 않은 것은 :attr:`StateValue.excluded` 에 적는다.
GRAVE_IS_COUNTED: bool = False


@dataclass(frozen=True, slots=True)
class StateValue:
    """
    미래 상태 하나의 값. **등급과 휴리스틱을 섞지 않는다.**

    :attr:`excluded` 가 비어 있지 않으면 **합에 넣지 못한 것이 있다** —
    모르는 값을 0 으로 바꾸지 않았다는 기록이다.
    """

    terminal: Terminal
    heuristic: int
    terms: tuple[tuple[str, int], ...] = ()
    excluded: tuple[str, ...] = ()

    @property
    def partial(self) -> bool:
        """합에 넣지 못한 것이 있는가."""
        return bool(self.excluded)

    def ordering_key(self) -> tuple[int, int]:
        """
        **등급이 먼저다.** 등급이 다르면 휴리스틱을 보지 않는다.

        큰 쪽이 좋다.
        """
        return (self.terminal.rank, self.heuristic)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        bits = ", ".join(f"{name}={value:+d}" for name, value in self.terms)
        held = f" · 제외 {len(self.excluded)}" if self.excluded else ""
        return f"[{self.terminal.value}] {self.heuristic:+d} ({bits or '없음'}){held}"


@runtime_checkable
class Evaluator(Protocol):
    """관측 하나를 값 하나로 바꾸는 것."""

    name: str

    def evaluate(self, view: GameStateView) -> StateValue:
        ...  # pragma: no cover - 프로토콜


def _zone_attack(zone: ZoneView) -> tuple[int, int]:
    """
    그 존의 **공격력 합과 셀 수 없었던 마리 수.**

    셀 수 없는 경우가 셋이다 — 정의가 없는 카드(가려진 상대 카드), 공격력이
    ``?`` 인 카드, 공격력 칸이 없는 카드. 셋 다 0 으로 바꾸지 않는다.
    """
    total = 0
    unknown = 0
    for card in zone.occupied():
        definition = card.definition
        if definition is None or not definition.is_monster:
            unknown += 1
            continue
        if definition.atk_is_question or not definition.has_atk:
            unknown += 1
            continue
        total += definition.atk
    return total, unknown


def _is_face_down(card: CardView) -> bool:
    return not card.face_up


@dataclass(frozen=True, slots=True)
class StateEvaluator:
    """
    기본 평가자. **단위는 LP 하나**이고 모든 항이 LP 로 환산된다.

    관점은 언제나 ``view.viewer`` 다 (§23). P0 가 평가할 때와 P1 이 평가할
    때 **같은 평가자가** 각자의 관점으로 작동한다 — 자리를 인수로 받지
    않고 관측이 이미 누구의 것인지 알고 있기 때문이다.
    """

    name: str = "state-evaluator"

    def evaluate(self, view: GameStateView) -> StateValue:
        if not isinstance(view, GameStateView):
            raise EvaluationError(
                f"관측이 필요합니다 (GameStateView): {type(view).__name__}"
            )

        terminal = Terminal.of(view)
        if terminal is not Terminal.ONGOING:
            # 끝난 판에서는 휴리스틱을 재지 않는다. 등급이 이미 모든 것을
            # 말하고, 끝난 판의 자원은 아무 의미가 없다.
            return StateValue(terminal=terminal, heuristic=0)

        me, opponent = view.me, view.opponent
        terms: list[tuple[str, int]] = []
        excluded: list[str] = []

        terms.append(("lp", me.life_points - opponent.life_points))

        my_attack, my_unknown = _zone_attack(me.monster_zone)
        their_attack, their_unknown = _zone_attack(opponent.monster_zone)
        terms.append(("atk", (my_attack - their_attack) * ATK_IN_LP))
        if my_unknown:
            excluded.append(f"내 몬스터 {my_unknown}마리의 공격력을 모른다")
        if their_unknown:
            excluded.append(f"상대 몬스터 {their_unknown}마리의 공격력을 모른다")

        terms.append(
            (
                "monsters",
                (me.monster_zone.size - opponent.monster_zone.size) * MONSTER_IN_LP,
            )
        )
        terms.append(
            (
                "spells",
                (me.spell_zone.size - opponent.spell_zone.size) * SPELL_TRAP_IN_LP,
            )
        )
        terms.append(
            ("deck", (me.deck.size - opponent.deck.size) * DECK_CARD_IN_LP)
        )

        # **내 패만 센다.** 상대 패는 장수가 보이지만 값을 매기려면 내용을
        # 알아야 하고, 내용은 보이지 않는다 (§26).
        terms.append(("hand", me.hand.size * HAND_CARD_IN_LP))
        if opponent.hand.size:
            excluded.append(f"상대 패 {opponent.hand.size}장의 값을 모른다")

        if not GRAVE_IS_COUNTED and (me.grave.size or opponent.grave.size):
            excluded.append(
                f"묘지 {me.grave.size}/{opponent.grave.size}장은 값을 매기지 않았다"
            )

        # 내 뒷면 카드는 **정체는 보이지만** 상대에게는 안 보인다. 값에
        # 넣지 않는 쪽을 고른 이유는, 넣으면 같은 판이 보는 자리에 따라
        # 다른 점수가 되어 §23 의 일관된 관점이 깨지기 때문이다.
        face_down = sum(
            1
            for zone in (me.monster_zone, me.spell_zone)
            for card in zone.occupied()
            if _is_face_down(card)
        )
        if face_down:
            excluded.append(f"내 뒷면 카드 {face_down}장은 값을 매기지 않았다")

        return StateValue(
            terminal=terminal,
            heuristic=sum(value for _, value in terms),
            terms=tuple(terms),
            excluded=tuple(excluded),
        )


__all__ = [
    "EvaluationError",
    "Terminal",
    "StateValue",
    "Evaluator",
    "StateEvaluator",
    "ATK_IN_LP",
    "MONSTER_IN_LP",
    "SPELL_TRAP_IN_LP",
    "DECK_CARD_IN_LP",
    "HAND_CARD_IN_LP",
    "GRAVE_IS_COUNTED",
]
