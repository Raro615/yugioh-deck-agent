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

**"모른다" 와 "세지 않았다" 는 다른 사실이다** (Phase 3-E-6)
-----------------------------------------------------------
``excluded`` 에 두 종류가 들어가고, 섞으면 둘 다 거짓이 된다.

===================  =====================================================
"모른다"              상대의 뒷면 카드 · 공격력이 ``?`` 인 카드. 값을
                      **읽을 수 없다**
"세지 않았다"         내 뒷면 몬스터의 공격력. 정체를 **알지만** 뒷면은
                      공격하지 않으므로 그 공격력이 지금 들어올 피해가
                      아니다 — ``ATK_IN_LP`` 가 1:1 인 근거가 성립하지
                      않는다
===================  =====================================================

STRUCTURAL-115 가 바로 이 자리의 거짓이었다. 예전에는 ``_zone_attack`` 이
내 뒷면 몬스터의 공격력을 **그대로 세면서** "값을 매기지 않았다" 고
보고했고, 그래서 앞면 공격 표시와 뒷면 수비 표시가 같은 점수를 받았다.
지금은 공격력을 세지 않고, 보고도 사실을 말한다.

**자리에 있다는 값은 뒷면도 센다.** ``monsters`` · ``spells`` 는 뒷면
카드도 세는데, 칸을 차지하고 나중에 쓸 수 있는 것이 사실이기 때문이다.
그래서 뒷면 마법 · 함정은 제외 항목이 **없다** — 뺀 것이 없다.

**수비력을 점수화하지 않았다.** 뒷면 수비 표시가 실제로 막아 내는 값
(수비력 · 정보 은닉)을 세는 항은 아직 없고, 그 설계는 별도 Phase 의 일이다.

**"세지 않았다" 는 적어야 사실이 된다** (Phase 3-E-7)
-----------------------------------------------------
``partial`` 은 ``excluded`` 가 비어 있지 않은가 **하나뿐**이다. 그래서
세지 않은 것을 ``excluded`` 에 **적지 않으면** ``partial`` 이 거짓으로
"다 셌다" 고 말한다 — 모르는 값을 0 으로 바꾸는 것과 같은 종류의 거짓이고,
적지 않았으므로 고칠 단서조차 남지 않는다.

STRUCTURAL-130 Audit 에서 **조용히 빠진 자리 다섯**이 나왔다. 묘지만
적혀 있었고 **제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱**은 카드가 있어도
``excluded`` 가 비었다. 지금은 :data:`_UNSCORED_ZONES` 가 다섯을 모두 적는다.
점수는 **하나도 바뀌지 않았다** — 세지 않던 것을 세기 시작한 것이 아니라,
세지 않는다고 말하기 시작한 것이다.

**엑스트라 몬스터 존이 평가에서 사라져 있었다** (STRUCTURAL-132)
---------------------------------------------------------------
같은 Audit 에서 나온 **구현 누락**이다. 엔진은 ``MZONE`` 과 ``EMZONE`` 을
언제나 함께 세는데(``BATTLE_ZONES`` · ``BATTLE_TARGET_ZONES`` ·
``MONSTER_ZONES`` · RULE-BATTLE-013), 평가만 ``MZONE`` 하나를 보고 있었다.

그래서 EMZ 에 선 앞면 공격 표시 몬스터는 **공격 대상으로 제시되면서
점수는 0 이었고**, ``excluded`` 도 비어서 ``partial`` 이 거짓으로 "다 셌다"
고 했다. 관측에는 ``extra_monster_zone`` 으로 분명히 들어와 있었다 — 정보가
평가에서만 사라진 것이므로 가중치 문제가 아니라 **읽는 자리의 누락**이다.
:func:`_field_monster_zones` 가 두 자리를 함께 보게 했고, 가중치는 하나도
새로 만들지 않았다.

**세 이유를 코드가 구분한다** (Phase 3-E-8 · STRUCTURAL-130 해결)
---------------------------------------------------------------
3-E-7 Audit 이 ``excluded`` 안에서 **서로 다른 세 가지**를 찾아냈다. 그런데
``excluded`` 는 문자열 목록이었으므로 셋을 가르는 유일한 수단이 **문구**였고,
``partial`` 은 그 목록이 비었는지만 보았다 — 그래서 실측 **99.6%** 가 참이었다.
언제나 참인 깃발은 아무것도 알려주지 않는다.

지금은 :class:`ExclusionCategory` 가 이유를 든다.

====================  ===========================================  =======
범주                   무슨 뜻인가                                   partial
====================  ===========================================  =======
``DESIGNED_OUT``      값이 보이는데 **항으로 두지 않기로 했다.**      아니다
                      묘지 · 제외 존 · 뒷면 몬스터의 공격력.
                      질문을 하지 않은 것이다
``UNKNOWN``           **다 보이는데 숫자가 나오지 않는다.** 공격력    **그렇다**
                      이 ``?`` 인 카드. 이것만이 평가의 미해결이다
``WITHHELD``          **합법적으로 볼 수 없다.** 상대의 뒷면 정체 ·   아니다
                      상대 패의 내용. 규칙대로 처리한 결과이고,
                      어떤 평가자도 이보다 잘할 수 없다
====================  ===========================================  =======

    ``partial = any(범주 is UNKNOWN)``

**경계가 이유를 가른다.** 상대의 뒷면 몬스터는 공격력이 ``?`` 라서 못 세는 것이
아니라 **정체가 가려져서** 못 센다 → ``WITHHELD``. 공격력이 ``?`` 인 앞면
카드는 다 보이는데도 숫자가 없다 → ``UNKNOWN``. 그래서 ``_zone_attack`` 의
판정 **순서가 규칙이다** — 읽을 수 있는지를 먼저 보고, 그 다음에 숫자가 있는지,
마지막에 앞뒷면을 본다.

**Phase 3-E-6 의 구분은 사라지지 않고 쪼개졌다.** 3-E-6 이 가른 "모른다" 와
"세지 않았다" 중, "모른다" 가 다시 ``WITHHELD``(가려짐) 와
``UNKNOWN``(숫자 없음) 으로 갈렸고, "세지 않았다" 는 ``DESIGNED_OUT`` 이다.
문구는 그대로 두었다 — 바뀐 것은 **기계가 읽을 범주가 생긴 것**이다.

**점수는 한 숫자도 바뀌지 않았다.** 이 변경은 메타데이터의 의미를 가르는
일이고, 가중치도 항도 건드리지 않았다.

여기서 하지 않는 것
-------------------
카드 이름을 보지 않는다 (§25). 상대의 가려진 정보를 추측하지 않는다
(§19). 학습하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from engine.game_state_view import CardView, GameStateView, PlayerView, ZoneView

if TYPE_CHECKING:  # pragma: no cover - 타입 주석 전용
    from collections.abc import Callable


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


class ExclusionCategory(str, Enum):
    """
    합에 넣지 **못한 이유의 종류.** 셋을 섞으면 셋 다 거짓이 된다.

    ``DESIGNED_OUT`` — **평가하지 않기로 했다**
        값을 읽을 수 있고 가려져 있지도 않다. 지금 평가 모델이 그것을 항으로
        두지 않기로 정했을 뿐이다 (묘지 · 제외 존 · 뒷면 몬스터의 공격력).
        평가에 남은 불확실성이 **아니다** — 질문을 하지 않은 것이다.
    ``UNKNOWN`` — **값을 정할 수 없다**
        평가 대상이고 가려져 있지도 않은데 숫자가 나오지 않는다 (공격력이
        ``?`` 인 카드). **관측 경계 밖이어서가 아니라** 값 자체가 지금
        결정되지 않는다. 이것만이 "평가가 아직 못 푼 것" 이다.
    ``WITHHELD`` — **합법적으로 볼 수 없다**
        관측 경계 밖이다 (상대의 뒷면 카드 정체 · 상대 패의 내용). 평가가
        실패한 것이 아니라 **규칙대로 처리한 결과**다 — 어떤 평가자도
        이보다 잘할 수 없다.

    **경계가 이유를 가른다.** 상대의 뒷면 몬스터는 공격력이 ``?`` 라서 못 세는
    것이 아니라 **정체가 가려져서** 못 센다 → ``WITHHELD``. 공격력이 ``?`` 인
    앞면 카드는 다 보이는데도 숫자가 없다 → ``UNKNOWN``.
    """

    DESIGNED_OUT = "designed_out"
    UNKNOWN = "unknown"
    WITHHELD = "withheld"


@dataclass(frozen=True, slots=True)
class Exclusion:
    """
    합에 넣지 못한 것 하나. **이유의 종류와 사람이 읽을 설명을 함께** 든다.

    Phase 3-E-7 까지 이 자리는 그냥 문자열이었고, 그래서 세 범주를 가르는
    유일한 수단이 **문구**였다 — 기계가 읽을 수 없었다 (STRUCTURAL-130).
    """

    category: ExclusionCategory
    note: str

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.note


@dataclass(frozen=True, slots=True)
class StateValue:
    """
    미래 상태 하나의 값. **등급과 휴리스틱을 섞지 않는다.**

    :attr:`excluded` 가 비어 있지 않으면 **합에 넣지 못한 것이 있다** —
    모르는 값을 0 으로 바꾸지 않았다는 기록이다. 이유의 종류는
    :class:`ExclusionCategory` 가 든다.
    """

    terminal: Terminal
    heuristic: int
    terms: tuple[tuple[str, int], ...] = ()
    excluded: tuple[Exclusion, ...] = ()

    @property
    def partial(self) -> bool:
        """
        **아직 못 푼 것이 남았는가** — ``UNKNOWN`` 이 하나라도 있는가다.

        ``bool(self.excluded)`` 가 아니다. 그렇게 두면 "평가하지 않기로 한 것"
        과 "볼 수 없는 것" 까지 들어와 깃발이 **언제나 참**이 되고, 참뿐인
        깃발은 아무것도 알려주지 않는다 (STRUCTURAL-130, 실측 99.6%).

        ``DESIGNED_OUT`` 은 질문을 하지 않은 것이고, ``WITHHELD`` 는 규칙상
        볼 수 없는 것이다 — 둘 다 **평가의 미해결이 아니다.** 남은 하나,
        "볼 수 있는데 숫자가 안 나오는 것" 만이 미해결이다.
        """
        return any(
            item.category is ExclusionCategory.UNKNOWN for item in self.excluded
        )

    @property
    def notes(self) -> tuple[str, ...]:
        """제외 사유의 설명만. 사람에게 보여 줄 때와 문구를 볼 때 쓴다."""
        return tuple(item.note for item in self.excluded)

    def of_category(self, category: ExclusionCategory) -> tuple[Exclusion, ...]:
        """그 범주의 제외 사유만."""
        return tuple(item for item in self.excluded if item.category is category)

    def ordering_key(self) -> tuple[int, int]:
        """
        **등급이 먼저다.** 등급이 다르면 휴리스틱을 보지 않는다.

        큰 쪽이 좋다.
        """
        return (self.terminal.rank, self.heuristic)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        bits = ", ".join(f"{name}={value:+d}" for name, value in self.terms)
        held = ""
        if self.excluded:
            counts = " ".join(
                f"{category.value}={len(self.of_category(category))}"
                for category in ExclusionCategory
                if self.of_category(category)
            )
            held = f" · 제외 {len(self.excluded)}({counts})"
        return f"[{self.terminal.value}] {self.heuristic:+d} ({bits or '없음'}){held}"


@runtime_checkable
class Evaluator(Protocol):
    """관측 하나를 값 하나로 바꾸는 것."""

    name: str

    def evaluate(self, view: GameStateView) -> StateValue:
        ...  # pragma: no cover - 프로토콜


def _is_face_down(card: CardView) -> bool:
    return not card.face_up


@dataclass(frozen=True, slots=True)
class _ZoneAttack:
    """
    한 존의 **공격력 합과, 합에 넣지 못한 마리 수를 이유별로 가른 것.**

    가르는 것이 이 자료형의 전부다. 세 이유가 서로 다른
    :class:`ExclusionCategory` 로 가므로, 한 칸에 몰면 범주가 섞인다.

    ``hidden``
        정의를 **읽을 수 없다** (가려진 상대 카드) → ``WITHHELD``
    ``indeterminate``
        정의는 **읽히는데** 공격력에 숫자가 없다 (``?`` 공격력, 몬스터가 아닌
        카드) → ``UNKNOWN``
    ``not_attacking``
        값을 **알지만** 뒷면은 공격하지 않으므로 세지 않는다 →
        ``DESIGNED_OUT``
    """

    total: int = 0
    hidden: int = 0
    indeterminate: int = 0
    not_attacking: int = 0

    def __add__(self, other: "_ZoneAttack") -> "_ZoneAttack":
        return _ZoneAttack(
            total=self.total + other.total,
            hidden=self.hidden + other.hidden,
            indeterminate=self.indeterminate + other.indeterminate,
            not_attacking=self.not_attacking + other.not_attacking,
        )


def _zone_attack(zone: ZoneView) -> _ZoneAttack:
    """
    그 존의 공격력 합과, **왜 세지 못했는지를 이유별로** 가른 수.

    가르는 것이 이 함수의 핵심이다 (Phase 3-E-6 에서 둘, 3-E-8 에서 셋).

    **순서가 규칙이다.**

    1. 정의를 **읽을 수 있는가** — 못 읽으면 ``hidden``. 관측 경계 밖이고,
       어떤 평가자도 이보다 잘할 수 없다
    2. 읽히는데 **숫자가 있는가** — 없으면 ``indeterminate``. 다 보이는데도
       값이 정해지지 않는다 — 이것만이 "평가가 아직 못 푼 것" 이다
    3. 앞면인가 — 뒷면이면 ``not_attacking``. 값을 알지만 **뒷면은 공격하지
       않으므로** 그 공격력이 지금 들어올 피해가 아니다 (``ATK_IN_LP`` 가
       1:1 인 근거가 성립하지 않는다)

    순서를 바꾸면 범주가 뒤바뀐다. 상대의 뒷면 카드는 1 에서 걸려야 하고,
    내 뒷면 ``?`` 몬스터는 2 에서 걸려야 한다 — 앞면으로 뒤집어도 여전히
    셀 수 없기 때문이다.

    예전에 ``unknown`` 한 칸이 1 과 2 를 함께 담고 있었다. 그래서 "관측 경계
    때문" 과 "값이 없기 때문" 이 같은 사실로 보고되었고, 그것이
    STRUCTURAL-130 이 ``partial`` 을 쓸 수 없게 만든 뿌리다.
    """
    total = hidden = indeterminate = not_attacking = 0
    for card in zone.occupied():
        definition = card.definition
        if definition is None:
            hidden += 1
            continue
        if not definition.is_monster:
            indeterminate += 1
            continue
        if definition.atk_is_question or not definition.has_atk:
            indeterminate += 1
            continue
        if _is_face_down(card):
            not_attacking += 1
            continue
        total += definition.atk
    return _ZoneAttack(
        total=total,
        hidden=hidden,
        indeterminate=indeterminate,
        not_attacking=not_attacking,
    )


def _field_monster_zones(player: PlayerView) -> tuple[ZoneView, ZoneView]:
    """
    **필드에서 몬스터가 서는 자리.** 메인 몬스터 존 하나만 보면 엑스트라
    몬스터 존에 선 몬스터가 평가에서 **통째로 사라진다.**

    엔진은 이미 두 자리를 함께 센다 — ``engine/battle.py`` 의
    ``BATTLE_ZONES``, ``engine/duel.py`` 의 ``BATTLE_TARGET_ZONES``,
    ``engine/action_validation.py`` 의 ``MONSTER_ZONES``, 그리고 같은 파일의
    RULE-BATTLE-013(직접 공격) 판정이 그렇다. 즉 EMZ 의 몬스터는 **공격하고,
    공격 대상이 되고, 직접 공격을 막는다** — ``ATK_IN_LP`` 와
    ``MONSTER_IN_LP`` 의 근거("공격을 한 번 더 할 수 있고 한 번 더 막을 수
    있다")가 글자 그대로 성립한다.

    평가만 ``MZONE`` 하나를 보고 있었던 것이 STRUCTURAL-132 다.
    """
    return (player.monster_zone, player.extra_monster_zone)


def _field_attack(zones: tuple[ZoneView, ...]) -> _ZoneAttack:
    """
    **필드 몬스터 전체**에 대한 ``_zone_attack`` 의 합.

    자리마다 따로 세고 더하기만 한다 — 가르는 규칙은 ``_zone_attack`` 에
    한 번만 적혀 있다.

    자리 목록을 **인수로 받는다.** ``PlayerView.monster_zone`` 같은 접근자는
    매번 존 목록을 훑으므로, 같은 자리를 두 번 꺼내지 않기 위해 호출하는 쪽이
    한 번만 꺼내 넘긴다.
    """
    summed = _ZoneAttack()
    for zone in zones:
        summed += _zone_attack(zone)
    return summed


def _field_monster_count(zones: tuple[ZoneView, ...]) -> int:
    """필드에 선 몬스터 마리 수. **뒷면도 센다** — 자리를 차지하기 때문이다."""
    return sum(zone.size for zone in zones)


#: 평가가 **점수로 세지 않는, 묘지 밖의 자리**와 그 한국어 이름.
#:
#: 세지 않는 것 자체는 설계다 — 제외 존에서 되살릴 수단도, 필드 존 · 펜듈럼
#: 존 · 엑스트라 덱에서 꺼낼 수단도 지금 후보에 오르지 않는다
#: (:data:`GRAVE_IS_COUNTED` 의 근거와 같다).
#:
#: 적어 두는 이유는 다른 데 있다. **세지 않았다고 적지 않으면** ``excluded``
#: 가 비고, 그러면 ``partial`` 이 "다 셌다" 는 **거짓**을 말한다. 예전에는
#: 묘지 하나만 적었고 이 넷은 조용히 빠졌다 (STRUCTURAL-130).
#:
#: 네 자리 모두 **장수는 양쪽에 공개된 사실**이므로, 여기 적는 것은
#: "모른다" 가 아니라 "세지 않았다" 다 — 둘을 섞지 않는다 (Phase 3-E-6).
#:
#: 존을 **문자열 이름이 아니라 접근자로** 적는다. ``getattr(player, "grave")``
#: 로 적으면 "평가가 어느 자리를 읽는가" 를 코드에서 읽을 수 없게 되고,
#: 그것을 고정한 테스트(``test_03_the_evaluator_reads_these...``)가 실제로
#: 깨졌다.
_UNSCORED_ZONES: tuple[tuple[str, "Callable[[PlayerView], ZoneView]"], ...] = (
    ("제외 존", lambda player: player.removed),
    ("필드 존", lambda player: player.field_zone),
    ("펜듈럼 존", lambda player: player.pendulum_zone),
    ("엑스트라 덱", lambda player: player.extra),
)


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
        excluded: list[Exclusion] = []

        def exclude(category: ExclusionCategory, note: str) -> None:
            excluded.append(Exclusion(category=category, note=note))

        terms.append(("lp", me.life_points - opponent.life_points))

        my_monsters = _field_monster_zones(me)
        their_monsters = _field_monster_zones(opponent)
        mine = _field_attack(my_monsters)
        theirs = _field_attack(their_monsters)
        terms.append(("atk", (mine.total - theirs.total) * ATK_IN_LP))

        # **세 이유가 세 범주로 간다** (STRUCTURAL-130, Phase 3-E-8).
        #
        #   가려져서 못 읽는다        WITHHELD      — 경계 밖이다
        #   읽히는데 숫자가 없다      UNKNOWN       — 이것만이 미해결이다
        #   알지만 뒷면이라 안 센다   DESIGNED_OUT  — 질문을 하지 않았다
        #
        # 예전에는 앞의 둘이 한 문구로 합쳐져 있었고, 셋 다 ``partial`` 을
        # 참으로 만들었다.
        if mine.hidden:  # pragma: no cover - 내 카드는 언제나 정의가 읽힌다
            exclude(
                ExclusionCategory.WITHHELD,
                f"내 몬스터 {mine.hidden}마리의 공격력을 모른다 (가려져 있다)",
            )
        if mine.indeterminate:
            exclude(
                ExclusionCategory.UNKNOWN,
                f"내 몬스터 {mine.indeterminate}마리의 공격력을 모른다 "
                "(공격력에 숫자가 없다)",
            )
        if theirs.hidden:
            exclude(
                ExclusionCategory.WITHHELD,
                f"상대 몬스터 {theirs.hidden}마리의 공격력을 모른다 "
                "(가려져 있다)",
            )
        if theirs.indeterminate:
            exclude(
                ExclusionCategory.UNKNOWN,
                f"상대 몬스터 {theirs.indeterminate}마리의 공격력을 모른다 "
                "(공격력에 숫자가 없다)",
            )
        if mine.not_attacking:
            exclude(
                ExclusionCategory.DESIGNED_OUT,
                f"내 뒷면 몬스터 {mine.not_attacking}마리의 공격력은 세지 않았다 "
                "(뒷면은 공격하지 않는다)",
            )
        if theirs.not_attacking:  # pragma: no cover - 뒷면 열람 권한이 있을 때만
            exclude(
                ExclusionCategory.DESIGNED_OUT,
                f"상대 뒷면 몬스터 {theirs.not_attacking}마리의 공격력은 "
                "세지 않았다 (뒷면은 공격하지 않는다)",
            )

        terms.append(
            (
                "monsters",
                (_field_monster_count(my_monsters)
                 - _field_monster_count(their_monsters))
                * MONSTER_IN_LP,
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
            # **장수는 보이고 내용은 보이지 않는다.** 경계 밖이므로 WITHHELD 다
            # — 어떤 평가자도 이보다 잘할 수 없다.
            exclude(
                ExclusionCategory.WITHHELD,
                f"상대 패 {opponent.hand.size}장의 값을 모른다",
            )

        if not GRAVE_IS_COUNTED and (me.grave.size or opponent.grave.size):
            exclude(
                ExclusionCategory.DESIGNED_OUT,
                f"묘지 {me.grave.size}/{opponent.grave.size}장은 값을 매기지 않았다",
            )

        # **세지 않은 것은 세지 않았다고 적는다** (STRUCTURAL-130). 위의
        # 묘지만 적혀 있었고 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱은
        # **조용히** 빠졌다 — 그 자리에 카드가 있어도 ``excluded`` 가 비고
        # ``partial`` 이 거짓으로 "다 셌다" 고 했다. 점수는 바뀌지 않는다.
        for label, zone_of in _UNSCORED_ZONES:
            mine_size, their_size = zone_of(me).size, zone_of(opponent).size
            if mine_size or their_size:
                exclude(
                    ExclusionCategory.DESIGNED_OUT,
                    f"{label} {mine_size}/{their_size}장은 값을 매기지 않았다",
                )

        # **이 자리에 거짓 보고가 있었다** (STRUCTURAL-115, Phase 3-E-6 에서
        # 제거). 예전에는 내 뒷면 카드 수를 세어 "값을 매기지 않았다" 고
        # 적었는데, ``_zone_attack`` 은 그 공격력을 그대로 세고 있었고
        # ``monsters`` · ``spells`` 는 **지금도** 그 카드를 센다. 그래서 그
        # 문장은 어느 쪽으로도 참이 아니었다.
        #
        # 지금은 둘이 각자 사실을 말한다.
        #
        #   공격력을 세지 않은 것   위의 ``my_withheld`` 가 적는다
        #   자리에 있다는 값        ``monsters`` · ``spells`` 가 **센다**
        #                          (뒷면도 자리를 차지하고 나중에 쓸 수 있다)
        #
        # 뒷면 마법 · 함정은 그래서 제외 항목이 **없다** — 뺀 것이 없기
        # 때문이다. 양쪽 모두 ``spell_zone.size`` 로 세므로 대칭이고,
        # 가려진 정체를 읽지도 않는다.

        return StateValue(
            terminal=terminal,
            heuristic=sum(value for _, value in terms),
            terms=tuple(terms),
            excluded=tuple(excluded),
        )


__all__ = [
    "EvaluationError",
    "Terminal",
    "ExclusionCategory",
    "Exclusion",
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
