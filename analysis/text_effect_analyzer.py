"""
공식 카드 텍스트 기반 효과 분석.

Lua 스크립트가 아직 없는 신규 카드도 최소한의 효과 정보를 갖게 한다.
다만 **Lua 분석과 같게 취급하지 않는다.** 여기서 나온 결과는 모두
:attr:`~core.provenance.AnalysisStatus.TEXT_DERIVED` 로 표시되며,
실제 게임 처리와 어긋날 수 있다.

읽는 것은 카드 텍스트에 분명히 적힌 동작 낱말뿐이다. 발동 조건의 논리 구조,
비용, 대상 지정 같은 것은 텍스트만으로 안전하게 구조화할 수 없으므로
시도하지 않는다. 그런 항목은 Lua 가 생길 때까지 비어 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from analysis.effect_model import ACTION_DESTINATION, ActionKind
from core import constants as C

#: 카드 텍스트의 동작 표현 -> 액션. 한국어 공식 표기와 영어 원문을 함께 본다.
#: 한 낱말이 곧 한 동작인 경우만 싣는다. 애매한 표현은 넣지 않는다.
_TEXT_ACTIONS: dict[ActionKind, tuple[str, ...]] = {
    ActionKind.SPECIAL_SUMMON: ("특수 소환", "특수소환", "Special Summon"),
    ActionKind.NORMAL_SUMMON: ("일반 소환", "Normal Summon"),
    ActionKind.DRAW: ("드로우", "draw"),
    ActionKind.DESTROY: ("파괴", "destroy"),
    ActionKind.BANISH: ("제외", "banish"),
    ActionKind.TO_HAND: ("패에 넣", "add it to", "add 1", "to your hand"),
    ActionKind.TO_GRAVE: ("묘지로 보", "send it to the GY", "send 1"),
    ActionKind.TO_DECK: ("덱으로 되돌", "return it to the Deck"),
    ActionKind.DISCARD: ("버리고", "버린다", "discard"),
    ActionKind.RELEASE: ("릴리스", "Tribute"),
    ActionKind.NEGATE: ("무효", "negate"),
    ActionKind.DAMAGE: ("데미지를 준다", "damage"),
    ActionKind.RECOVER: ("라이프 포인트를 회복", "gain", "회복한다"),
    ActionKind.TOKEN: ("토큰", "Token"),
    ActionKind.EQUIP: ("장착", "equip"),
}

#: 텍스트에서 읽을 수 있는 발동 위치 표현.
_TEXT_LOCATIONS: dict[str, tuple[str, ...]] = {
    "HAND": ("패에서", "패의", "from your hand"),
    "GRAVE": ("묘지에서", "묘지의", "from your GY", "from the GY"),
    "DECK": ("덱에서", "덱의", "from your Deck"),
    "REMOVED": ("제외된", "banished"),
    "MZONE": ("필드의", "필드에서", "on the field"),
}

_RE_ONCE_PER_TURN = re.compile(r"1턴에\s*1번|Once per turn", re.I)


@dataclass(slots=True)
class TextDerivedEffect:
    """
    카드 텍스트에서 읽어낸 효과 윤곽.

    :class:`~analysis.effect_model.EffectAnalysis` 와 이름을 겹치지 않게 둔다.
    구조가 다르고 신뢰도도 다르기 때문이다.
    """

    actions: list[ActionKind] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    once_per_turn: bool = False
    source_text: str = ""

    def describe_ko(self) -> str:
        parts: list[str] = []
        if self.locations:
            parts.append("/".join(self.locations) + "에서")
        parts.extend(
            f"{a.value}→{ACTION_DESTINATION.get(a) or '?'}" for a in self.actions
        )
        if self.once_per_turn:
            parts.append("1턴 1회")
        return " · ".join(parts) if parts else "(텍스트에서 읽은 것 없음)"


@dataclass(slots=True)
class TextAnalysis:
    """카드 한 장의 텍스트 유래 분석."""

    card_id: int
    effect: TextDerivedEffect | None = None
    has_text: bool = False
    skipped_reason: str | None = None
    """분석을 시도하지 않은 이유. 예: 효과가 없는 일반 몬스터."""

    @property
    def is_empty(self) -> bool:
        return self.effect is None or not self.effect.actions


class TextEffectAnalyzer:
    """
    공식 텍스트에서 효과 윤곽을 읽는다.

    Lua 분석기와 별개 클래스로 둔다. 결과를 섞어 쓰지 못하게 하려는 것이다.
    """

    @staticmethod
    def _is_flavor_text_only(card) -> bool:
        """효과 텍스트가 아니라 설정 문구만 가진 카드인가."""
        if not card.type_mask & C.TYPE_MONSTER:
            return False
        has_effect_type = bool(
            card.type_mask
            & (
                C.TYPE_EFFECT
                | C.TYPE_FLIP
                | C.TYPE_SPIRIT
                | C.TYPE_UNION
                | C.TYPE_GEMINI
                | C.TYPE_TOON
                | C.TYPE_PENDULUM
                | C.TYPE_LINK
            )
        )
        return bool(card.type_mask & C.TYPE_NORMAL) and not has_effect_type

    def analyze(self, card) -> TextAnalysis:
        if card is None:
            return TextAnalysis(card_id=0)
        text = " ".join(t for t in (card.desc, card.desc_en) if t).strip()
        analysis = TextAnalysis(card_id=card.id, has_text=bool(text))
        if not text:
            return analysis

        # 효과가 없는 몬스터의 카드 텍스트는 설정 문구다. 거기 나오는
        # "파괴력" 같은 낱말을 효과로 읽으면 없는 효과를 만들어낸다.
        if self._is_flavor_text_only(card):
            analysis.skipped_reason = "효과가 없는 몬스터 (설정 문구)"
            return analysis

        actions: list[ActionKind] = []
        for kind, needles in _TEXT_ACTIONS.items():
            if any(needle.lower() in text.lower() for needle in needles):
                actions.append(kind)

        locations: list[str] = []
        for location, needles in _TEXT_LOCATIONS.items():
            if any(needle.lower() in text.lower() for needle in needles):
                locations.append(location)

        analysis.effect = TextDerivedEffect(
            actions=actions,
            locations=locations,
            once_per_turn=bool(_RE_ONCE_PER_TURN.search(text)),
            source_text=text[:400],
        )
        return analysis
