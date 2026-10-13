"""
카드 효과의 **사실만** 읽는 자리 (Phase 5-D).

이 모듈은 "이 카드가 좋은가" 를 묻지 않는다. Lua 효과 블록에서 **측정되는
것**만 돌려준다. 역할을 붙이는 일은 :mod:`deck.builder` 가 하고, 그때
여기서 읽은 사실을 근거로 쓴다.

왜 분리하는가 — 섞었을 때 무슨 일이 났는가
-------------------------------------------
Phase 5-C 까지 :mod:`deck.builder` 는 ``card.has_effect_from("HAND")`` 하나로
**역할까지** 정했다. 그 결과 `/deck` 이 아래 8장을 전부 같은 근거
("패에서 발동 (패트랩 계열)") 로 메인 덱에 넣었다 — 실측으로 확인한
이 8장의 실제 효과는 **세 가지로 갈린다**:

====================  =========================================  ==============
카드                  ``LOCATION_HAND`` 을 가진 블록             실제
====================  =========================================  ==============
텐사우전드 드래곤     ``FIELD`` / ``EFFECT_SPSUMMON_PROC``       **특수 소환 절차**
SPYRAL－보텍스        ``FIELD`` / ``EFFECT_SPSUMMON_PROC``       **특수 소환 절차**
펜리르                ``FIELD`` / ``EFFECT_SPSUMMON_PROC``       **특수 소환 절차**
독법사                ``FIELD`` / ``EFFECT_SPSUMMON_PROC``       **특수 소환 절차**
라뷰린스 쿠클락       ``QUICK_O`` / 범주 없음                    발동 가능, 무엇을 하는지 모름
EM 스카이 퓨필        ``QUICK_O`` / ``SPECIAL_SUMMON``           발동 가능, 특수 소환
하나된 마음의 용      ``TRIGGER_O`` / ``EVENT_DRAW``             발동 가능, 드로우에 반응
육화의 하얀 공주      ``QUICK_O`` / ``EVENT_CHAINING`` / ``DISABLE``  **무효화 근거 있음**
====================  =========================================  ==============

🔴 **네 장은 효과를 발동하는 카드가 아니다.** ``EFFECT_SPSUMMON_PROC`` 은
특수 소환 **절차**이고, ``SetRange(LOCATION_HAND)`` 는 "패에 있을 때 그
절차를 쓸 수 있다" 를 뜻한다. 발동이 아니다. 그런데
``has_effect_from("HAND")`` 는 ``SetRange`` 에 ``HAND`` 가 있는지만 보므로
이것도 참이 된다.

실측 (메인 덱 몬스터 7,067장)
------------------------------
=====================================================  =======
기준                                                   장수
=====================================================  =======
``has_effect_from("HAND")`` — Phase 5-C 가 쓴 기준     1,795
``+`` 발동 가능한 효과 종류 (절차·지속 제외)             1,208
``+`` 무효/무력화 범주까지                             **37**
=====================================================  =======

🔴 1,795 대 37 — **48배**다. 587장은 "패에서 발동" 조차 아니었다. 이것이
8장이 한 근거로 묶인 이유이고, 그 근거가 신뢰할 수 없는 이유다.

이 모듈이 **하지 않는 것**
--------------------------
* 🔴 **"상대의" 행동을 방해한다고 말하지 않는다.** ``EVENT_CHAINING`` 은
  "발동에 체인한다" 는 사실이고, **누구의** 발동인지는 Lua 블록에 없다.
  그래서 :func:`chains_on_activation` 의 이름에 "상대" 가 없다.
* 🔴 **덱 적합성을 판정하지 않는다.** "이 카드가 오르페골 덱에 맞는가" 를
  판정할 데이터가 이 저장소에 없다. 그 질문에는 함수가 없다 — 없는 것을
  있는 것처럼 두지 않는다.
* 🔴 **카드 이름을 보지 않는다.** 판정은 전부 Lua 효과 블록에서 나온다.
  특정 카드를 이름으로 넣거나 빼는 목록이 이 파일에 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: 🔴 **발동되는** 효과의 ``EFFECT_TYPE_*`` 종류.
#:
#: ``SINGLE`` 과 ``FIELD`` 가 **없는 것**이 요점이다. 그 둘은 지속 효과와
#: 절차(``EFFECT_SPSUMMON_PROC`` · ``EFFECT_SPSUMMON_CONDITION`` 등)를
#: 적는 자리이고, 발동이 아니다. 8장 중 4장이 이 구분으로 걸러진다.
#:
#: ``SINGLE`` 이 다른 종류와 **함께** 적힌 블록(``['SINGLE','TRIGGER_O']``)은
#: 발동되는 효과다 — 그래서 교집합으로 본다.
ACTIVATABLE_EFFECT_TYPES: frozenset[str] = frozenset({
    "ACTIVATE", "IGNITION", "QUICK_O", "QUICK_F",
    "TRIGGER_O", "TRIGGER_F", "FLIP",
})

#: 무효·무력화를 적는 ``CATEGORY_*``.
#:
#: 이 범주가 있다는 것은 **그 블록이 무효/무력화를 한다**는 Lua 작성자의
#: 표기다. 🔴 그래도 "상대를 막는다" 로 읽지 않는다 — 대상이 누구인지는
#: 범주에 없다.
NEGATION_CATEGORIES: frozenset[str] = frozenset({
    "NEGATE", "DISABLE", "DISABLE_SUMMON",
})

#: "발동에 체인한다" 를 뜻하는 트리거 사건.
CHAIN_RESPONSE_EVENT = "EVENT_CHAINING"


class HandTrapEvidence(str, Enum):
    """
    "패트랩" 이라는 역할이 **효과로 뒷받침되는가**.

    🔴 세 값이 **다른 사실**이다. 합치면 Phase 5-C 의 결함이 돌아온다.
    """

    NEGATION_FROM_HAND = "negation_from_hand"
    """패에서 발동 가능한 블록에 **무효/무력화 범주가 있다.** 가장 강한 근거."""
    ACTIVATABLE_ONLY = "activatable_only"
    """
    패에서 **발동은 가능하지만** 무효/무력화 범주가 없다.

    🔴 패트랩이라고 부를 근거가 **아니다.** 무엇을 하는 효과인지는 이
    저장소가 판정하지 못한다.
    """
    NOT_ACTIVATABLE_FROM_HAND = "not_activatable_from_hand"
    """
    패에서 발동할 수 있는 효과가 **없다.**

    ``LOCATION_HAND`` 을 가진 블록이 있어도 그것이 절차나 지속 효과라면
    여기로 온다 — 8장 중 4장이 이 경우다.
    """

    def describe_ko(self) -> str:
        return {
            HandTrapEvidence.NEGATION_FROM_HAND:
                "패에서 발동 가능한 효과에 무효/무력화 범주가 있습니다",
            HandTrapEvidence.ACTIVATABLE_ONLY:
                "패에서 발동은 가능하지만 무엇을 하는 효과인지는"
                " 판정하지 못했습니다",
            HandTrapEvidence.NOT_ACTIVATABLE_FROM_HAND:
                "패에서 발동할 수 있는 효과가 없습니다",
        }[self]


@dataclass(frozen=True, slots=True)
class HandEffectFacts:
    """
    한 카드의 **패 관련 효과 사실**. 판정이 아니라 측정값이다.

    :attr:`hand_range_blocks` 와 :attr:`activatable_blocks` 를 **둘 다**
    남기는 이유: 두 수가 다를 때 그것이 바로 Phase 5-C 가 틀린 지점이다.
    하나만 남기면 "왜 이 카드가 들어왔는가" 를 다시 물을 수 없다.
    """

    hand_range_blocks: int
    """``SetRange`` 에 ``LOCATION_HAND`` 이 있는 블록 수. **위치 사실뿐이다.**"""
    activatable_blocks: int
    """그중 **발동되는** 효과 종류인 블록 수."""
    negation_blocks: int
    """발동 가능한 블록 중 무효/무력화 범주를 가진 블록 수."""
    chain_response_blocks: int
    """발동 가능한 블록 중 ``EVENT_CHAINING`` 인 블록 수."""
    categories: tuple[str, ...]
    """발동 가능한 블록들의 ``CATEGORY_*`` 합집합 (정렬)."""

    @property
    def evidence(self) -> HandTrapEvidence:
        """🔴 사실에서 **근거 등급만** 정한다. 역할은 정하지 않는다."""
        if self.negation_blocks:
            return HandTrapEvidence.NEGATION_FROM_HAND
        if self.activatable_blocks:
            return HandTrapEvidence.ACTIVATABLE_ONLY
        return HandTrapEvidence.NOT_ACTIVATABLE_FROM_HAND

    @property
    def activatable_from_hand(self) -> bool:
        """패에서 **발동 가능한** 효과가 있는가. 위치만 보는 것과 다르다."""
        return self.activatable_blocks > 0

    def describe_ko(self) -> str:
        bits = [f"패 범위 블록 {self.hand_range_blocks}개",
                f"그중 발동 가능 {self.activatable_blocks}개"]
        if self.negation_blocks:
            bits.append(f"무효/무력화 범주 {self.negation_blocks}개")
        if self.chain_response_blocks:
            bits.append(f"발동에 체인 {self.chain_response_blocks}개")
        return " · ".join(bits)


def hand_effect_facts(card) -> HandEffectFacts:
    """
    카드의 패 관련 효과 사실을 읽는다. **역할을 붙이지 않는다.**

    🔴 ``card.has_effect_from("HAND")`` 를 쓰지 않는다. 그 메서드는
    ``SetRange`` 만 보므로 절차와 발동을 가르지 못한다 — 이 함수가 존재하는
    이유가 그것이다. :mod:`core` 의 공개 API 는 건드리지 않고, 가르는 일을
    여기서 한다.
    """
    hand_blocks = [block for block in card.effects
                   if "HAND" in block.ranges]
    activatable = [
        block for block in hand_blocks
        if ACTIVATABLE_EFFECT_TYPES & set(block.effect_types)
    ]
    categories: set[str] = set()
    for block in activatable:
        categories.update(block.categories)
    return HandEffectFacts(
        hand_range_blocks=len(hand_blocks),
        activatable_blocks=len(activatable),
        negation_blocks=sum(
            1 for block in activatable
            if NEGATION_CATEGORIES & set(block.categories)),
        chain_response_blocks=sum(
            1 for block in activatable
            if block.code == CHAIN_RESPONSE_EVENT),
        categories=tuple(sorted(categories)),
    )


def chains_on_activation(card) -> bool:
    """
    패에서 발동 가능한 효과가 **어떤 발동에 체인하는지**.

    🔴 이름에 "상대" 가 없는 것이 의도다. ``EVENT_CHAINING`` 은 누구의
    발동인지 적지 않으므로, 이 저장소는 "상대를 방해한다" 를 말할 수 없다.
    """
    return hand_effect_facts(card).chain_response_blocks > 0
