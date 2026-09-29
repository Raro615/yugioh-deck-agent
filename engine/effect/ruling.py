"""
조작 판정 계층 — **"이 조작을 지금 이 상황에서 수행할 수 있는가"** (Phase 2-AK).

    RuleQuestion          무엇을 묻는가        (semantics.py, Phase 2-X · 2-AK)
    CardRuleFacts         그 카드에 대해 사람이 **확인한 것**
    OperationRulingRegistry  확인된 것들의 모음 — 등록되지 않으면 UNKNOWN
    BoardRuling           판을 보고 **답을 합성**한다

ADR-006 이 말하는 자리
----------------------
지금까지 관문은 **구조만** 있었다. :class:`~engine.effect.semantics.
DestructionRuling` · ``MovementRuling`` · ``SummonRuling`` 은 프로토콜과
"아무것도 모른다" 기본값과 시험용 손 선언(``Declared*Ruling``, **판 번호**
단위)만 갖고 있었다. 그래서 등재된 실제 카드 16장 중 4장이 실행되지 않았고,
넷 다 이유가 같았다 — **답할 지식이 없다.**

이 파일은 그 지식을 담는다. 다른 것은 하나도 바꾸지 않는다.

지식은 카드 단위이고, 판정은 상황 단위다
----------------------------------------
둘을 섞지 않는 것이 이 파일의 뼈대다.

======================  ==============================================
:class:`CardRuleFacts`   **카드**에 대한 사실. 듀얼과 무관하다.
:class:`BoardRuling`     **이 판에서** 그 사실이 어떤 답이 되는가.
======================  ==============================================

``Declared*Ruling`` 이 :class:`~engine.ids.InstanceId` 를 키로 삼은 것은
시험 대역으로는 맞지만 **지식이 아니다** — 같은 카드를 다음 듀얼에서 다시
확인해야 한다. 여기서는 ``card_id`` 를 키로 삼고, 출처를 함께 적는다.

TRUE 는 공짜가 아니다
---------------------
"이 카드의 텍스트에 막는 말이 없다" 만으로 ``TRUE`` 를 내면, 판에 깔린 다른
카드가 막고 있을 때 틀린다. 그래서 :class:`BoardRuling` 은 **두 가지를 다**
본다.

1. 그 카드 자신이 무엇을 말하는가 (:class:`CardRuleFacts`).
2. 판에 **막을 수 있는 것**이 있는가 (:data:`INTERFERENCE_ZONES` 훑기).

2번에서 **등록되지 않은 카드를 하나라도 만나면 ``UNKNOWN``** 이다. 모르는
카드가 깔린 판에서 "아무도 안 막는다" 고 말할 수 없기 때문이다. 이것이
ADR-006 의 기본값이 이 계층에서 갖는 모양이다.

여기서 하지 않는 것
-------------------
지속 효과를 **해석하지 않는다.** :attr:`CardRuleFacts.restricts_others` 는
"이 카드가 다른 카드의 조작을 막을 수 있는가" 하나의 참/거짓이고, 무엇을
어떻게 막는지는 적지 않는다. 막을 수 있는 카드가 판에 있으면 그냥
``UNKNOWN`` 이다 — 지속 효과 계층(STRUCTURAL-76)은 여전히 없다.

판을 바꾸지 않는다. :class:`~engine.game_state_view.GameStateView` 만
읽는다 — 관측 경계를 우회하지 않으려고 ``GameState`` 를 아예 받지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable

from engine.condition import ConditionResult
from engine.effect.semantics import RuleQuestion
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.vocabulary import Zone


class RulingError(Exception):
    """판정 지식을 적는 방법이 틀렸을 때."""


# ======================================================================
# 출처
# ======================================================================


class RuleBasis(str, Enum):
    """
    이 사실을 **어디서 읽었는가.** 없는 값이 하나 있다 — "짐작했다".

    적을 수 없으면 적지 않는다. 등록되지 않은 것은 ``UNKNOWN`` 이고,
    그것이 이 계층의 기본값이다.
    """

    RULEBOOK = "rulebook"
    """공식 룰북 (``data/rules/documents/sd-rulebook-en-v10.json``)."""
    CARD_TEXT = "card_text"
    """
    그 카드의 **공식 텍스트 전문**을 읽었다.

    "텍스트에 없으니 그런 효과가 없다" 가 성립하는 이유는 룰북이 카드
    텍스트를 효과의 전부로 규정하기 때문이다. 일부만 읽고 적으면 안 된다.
    """
    OFFICIAL_RULING = "official_ruling"
    """``https://www.db.yugioh-card.com/yugiohdb/`` 의 재정 · 보충."""


# ======================================================================
# 카드 한 장에 대해 확인한 것
# ======================================================================


@dataclass(frozen=True, slots=True)
class RuleFact:
    """
    질문 하나에 대한 **확인된 답.**

    ``UNKNOWN`` 을 담을 수 없다. "모른다" 는 사실이 아니라 **사실이 없는
    것**이고, 그것은 이 표에 줄이 없는 것으로 표현된다. 담을 수 있게 하면
    "확인해서 모르겠더라" 와 "안 봤다" 가 같은 모양이 된다.
    """

    answer: ConditionResult
    basis: RuleBasis
    note: str

    def __post_init__(self) -> None:
        if self.answer not in (ConditionResult.TRUE, ConditionResult.FALSE):
            raise RulingError(
                f"확인된 답은 참이거나 거짓입니다: {self.answer}. 모르는 것은 "
                "표에 적지 않습니다 — 줄이 없는 것이 '모른다' 입니다."
            )
        if not self.note.strip():
            raise RulingError("무엇을 읽고 그렇게 적었는지 남겨야 합니다.")

    def canonical_state(self) -> tuple:
        return (self.answer.value, self.basis.value, self.note)


@dataclass(frozen=True, slots=True)
class CardRuleFacts:
    """
    카드 한 장에 대해 **사람이 확인한 것들.**

    :attr:`answers` 에 없는 질문은 **확인하지 않은** 질문이다. 한 카드에
    대해 "패로 되돌릴 수 있는지는 확인했지만 제외할 수 있는지는 아직" 이
    그대로 적힌다.
    """

    card_id: int
    answers: Mapping[RuleQuestion, RuleFact] = field(default_factory=dict)
    restricts_others: bool = True
    """
    이 카드가 **다른 카드의 조작을 막을 수 있는가.**

    기본값이 참인 것이 핵심이다. 확인하지 않은 카드는 막을 수 있다고
    보는 것이 안전한 쪽이고, 그러면 그 카드가 깔린 판의 답은 ``UNKNOWN``
    이 된다. 거짓으로 적으려면 :attr:`restriction_basis` 를 함께 적어야
    한다 — 공짜로 "안 막는다" 를 주장할 수 없다.
    """
    restriction_basis: "RuleBasis | None" = None
    restriction_note: str = ""

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise RulingError(f"카드 ID 는 양수입니다: {self.card_id}")
        if not self.restricts_others:
            if self.restriction_basis is None or not self.restriction_note.strip():
                raise RulingError(
                    f"{self.card_id}: '다른 카드를 막지 않는다' 는 주장이므로 "
                    "무엇을 읽고 그렇게 말하는지 적어야 합니다."
                )
        object.__setattr__(self, "answers", dict(self.answers))

    def answer_for(self, question: RuleQuestion) -> "RuleFact | None":
        """확인한 답. **확인하지 않았으면 ``None``** (0 도 거짓도 아니다)."""
        return self.answers.get(question)

    def canonical_state(self) -> tuple:
        return (
            self.card_id,
            tuple(
                (question.value, fact.canonical_state())
                for question, fact in sorted(
                    self.answers.items(), key=lambda kv: kv[0].value
                )
            ),
            self.restricts_others,
        )


# ======================================================================
# 룰북이 직접 답하는 것들
# ======================================================================

#: 룰북 원문. 토큰에 대한 **유일한 근거**다.
#:
#:     "Monster Tokens are monsters that appear on the field as the result
#:      of a card's effect. They are not included in the Deck, and cannot be
#:      sent anywhere other than the field, such as the hand or Graveyard.
#:      When a Token is destroyed or returned to the hand or Deck, they are
#:      simply removed from the field instead."
TOKEN_RULE: str = (
    "They are not included in the Deck, and cannot be sent anywhere other "
    "than the field, such as the hand or Graveyard."
)

#: 룰북 원문. 통상 몬스터가 **아무것도 하지 않는다**는 근거다.
#:
#:     "Yellow Normal Monster Cards do not have effects, and have a
#:      description of them written here that does not affect the game."
NORMAL_MONSTER_RULE: str = (
    "Yellow Normal Monster Cards do not have effects, and have a "
    "description of them written here that does not affect the game."
)

#: 토큰이 **갈 수 없는** 자리들. 룰북이 이름을 댄 것과 같은 범위다.
TOKEN_FORBIDDEN: tuple[RuleQuestion, ...] = (
    RuleQuestion.MAY_BE_RETURNED_TO_HAND,
    RuleQuestion.MAY_BE_SENT_TO_GRAVE,
    RuleQuestion.MAY_BE_RETURNED_TO_DECK,
    RuleQuestion.MAY_BE_DISCARDED,
)


def normal_monster_facts(card_id: int, name: str = "") -> CardRuleFacts:
    """
    **통상 몬스터**에 대한 사실. 룰북 한 줄에서 전부 나온다.

    효과가 없으므로 (1) 스스로를 지키지 않고 (2) 남을 막지 않는다. 둘 다
    추측이 아니라 :data:`NORMAL_MONSTER_RULE` 의 직접적인 귀결이다.

    **파괴와 특수 소환은 여기 없다.** 파괴 내성이 없다는 것과 "지금 이
    카드를 파괴해도 된다" 는 다른 문장이고, 후자는 대체 효과 · 동시 파괴
    처리까지 봐야 한다. 특수 소환은 소생 제한이 카드 텍스트가 아니라
    **그 카드가 어떻게 필드를 떠났는가**에 달려 있어 카드 단위로 적을 수
    없다 (STRUCTURAL-64).
    """
    note = f"통상 몬스터이므로 효과가 없다 — 룰북: {NORMAL_MONSTER_RULE}"
    if name:
        note = f"{name}: {note}"
    fact = RuleFact(ConditionResult.TRUE, RuleBasis.RULEBOOK, note)
    return CardRuleFacts(
        card_id=card_id,
        answers={
            RuleQuestion.MAY_BE_RETURNED_TO_HAND: fact,
            RuleQuestion.MAY_BE_BANISHED: fact,
            RuleQuestion.MAY_BE_RETURNED_TO_DECK: fact,
            RuleQuestion.MAY_BE_SENT_TO_GRAVE: fact,
            RuleQuestion.MAY_BE_DISCARDED: fact,
        },
        restricts_others=False,
        restriction_basis=RuleBasis.RULEBOOK,
        restriction_note=note,
    )


def token_facts(card_id: int, name: str = "") -> CardRuleFacts:
    """
    **토큰**에 대한 사실. 갈 수 없는 자리가 룰북에 적혀 있다.

    제외(:attr:`RuleQuestion.MAY_BE_BANISHED`)는 **적지 않는다.** 룰북이
    이름을 대지 않았고, 대지 않은 것을 채워 넣지 않는다.
    """
    note = f"토큰 — 룰북: {TOKEN_RULE}"
    if name:
        note = f"{name}: {note}"
    fact = RuleFact(ConditionResult.FALSE, RuleBasis.RULEBOOK, note)
    return CardRuleFacts(
        card_id=card_id,
        answers={question: fact for question in TOKEN_FORBIDDEN},
        restricts_others=False,
        restriction_basis=RuleBasis.RULEBOOK,
        restriction_note=f"토큰은 필드의 통상 몬스터로 취급된다 — {NORMAL_MONSTER_RULE}",
    )


# ======================================================================
# 모음
# ======================================================================


class OperationRulingRegistry:
    """
    확인된 사실들. **손으로 등록한다** (ADR-006).

    :class:`~engine.effect.definition.EffectImplementationRegistry` ·
    :class:`~engine.trigger.TriggerRegistry` 와 같은 모양이다 — 등록되지
    않은 것은 없는 것이 아니라 **모르는 것**이다.
    """

    __slots__ = ("_facts",)

    def __init__(self, facts: "tuple[CardRuleFacts, ...] | None" = None):
        self._facts: dict[int, CardRuleFacts] = {}
        for entry in facts or ():
            self.register(entry)

    def register(self, entry: CardRuleFacts) -> "OperationRulingRegistry":
        if not isinstance(entry, CardRuleFacts):
            raise TypeError(f"CardRuleFacts 가 필요합니다: {type(entry).__name__}")
        if entry.card_id in self._facts:
            raise RulingError(
                f"{entry.card_id} 는 이미 등록되어 있습니다. 한 카드의 사실은 "
                "한 군데에만 적습니다 — 두 군데면 어느 쪽이 맞는지 알 수 없습니다."
            )
        self._facts[entry.card_id] = entry
        return self

    def facts_for(self, card_id: int) -> "CardRuleFacts | None":
        return self._facts.get(card_id)

    def __contains__(self, card_id: object) -> bool:
        return card_id in self._facts

    def __len__(self) -> int:
        return len(self._facts)

    @property
    def card_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._facts))

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<OperationRulingRegistry {len(self._facts)}장>"


# ======================================================================
# 판을 보고 답을 합성한다
# ======================================================================

#: 막을 수 있는 것을 **찾아보는** 자리들.
#:
#: 필드와 묘지와 제외 구역이다. 셋 다 **누구나 볼 수 있는** 자리이고,
#: 그래서 훑는 것이 관측 경계를 넘지 않는다.
INTERFERENCE_ZONES: frozenset[Zone] = frozenset(
    {
        Zone.MZONE,
        Zone.EMZONE,
        Zone.SZONE,
        Zone.FZONE,
        Zone.PZONE,
        Zone.GRAVE,
        Zone.REMOVED,
    }
)

#: 훑지 **않는** 자리와 그 이유. 빈 칸으로 두지 않고 적어 둔다.
UNSCANNED_ZONES: dict[str, str] = {
    "패": (
        "상대의 패는 보이지 않는다. 패에서 적용되는 지속 효과를 가진 카드가 "
        "있으면 이 계층은 그것을 못 본다 (STRUCTURAL-98)."
    ),
    "덱": "덱의 카드는 효과를 적용하지 않는다.",
    "뒷면 카드": (
        "세트된 카드는 발동 · 반전 전까지 효과를 적용하지 않는다. 그래서 "
        "정체를 몰라도 훑기를 막지 않는다."
    ),
}


@runtime_checkable
class OperationRuling(Protocol):
    """
    질문 하나를 받아 답하는 판정기.

    옛 프로토콜들(``DestructionRuling`` · ``MovementRuling`` ·
    ``SummonRuling``)은 **질문마다 메서드**였다. 질문이 둘일 때는 그것이
    맞았지만 다섯이 되면서 메서드를 셋 더 만드는 대신 질문을 값으로
    받는다 — :class:`~engine.effect.semantics.RuleQuestion` 이 이미 그
    구분을 들고 있으므로, 이름으로 한 번 더 나누면 같은 말을 두 벌 적는
    것이 된다.
    """

    def may(
        self, question: RuleQuestion, instance: InstanceId
    ) -> ConditionResult:
        ...  # pragma: no cover - 프로토콜


@dataclass(frozen=True, slots=True)
class RulingVerdict:
    """답과 **그렇게 답한 이유.** 이유 없는 답을 내놓지 않는다."""

    answer: ConditionResult
    reason: str


class BoardRuling:
    """
    **이 판에서** 그 조작을 할 수 있는가.

    옛 프로토콜 셋을 그대로 만족시키므로 실행기는 바뀌지 않는다
    (``may_be_destroyed`` · ``may_be_sent_to_grave`` · ``may_be_discarded``).
    새 질문은 :meth:`may` 로 온다.

    파괴와 특수 소환에는 **언제나 ``UNKNOWN``** 이다. 이 계층이 그 둘의
    지식을 담지 않기 때문이고, 담지 않은 이유는 :func:`normal_monster_facts`
    의 설명에 적혀 있다.
    """

    __slots__ = ("_view", "_registry")

    def __init__(self, view: GameStateView, registry: OperationRulingRegistry):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "BoardRuling 은 GameStateView 만 받습니다. GameState 를 받으면 "
                "판정이 판을 바꿀 수 있게 되고, 관측 경계도 사라집니다."
            )
        if not isinstance(registry, OperationRulingRegistry):
            raise TypeError(
                f"OperationRulingRegistry 가 필요합니다: {type(registry).__name__}"
            )
        self._view = view
        self._registry = registry

    # ------------------------------------------------------------------
    def explain(
        self, question: RuleQuestion, instance: InstanceId
    ) -> RulingVerdict:
        """답과 이유를 함께. :meth:`may` 는 여기서 답만 꺼낸다."""
        card = self._view.find(instance)
        if card is None or card.card_id is None:
            return RulingVerdict(
                ConditionResult.UNKNOWN,
                f"{instance} 가 보이지 않아 어떤 카드인지 알 수 없습니다.",
            )

        facts = self._registry.facts_for(card.card_id)
        if facts is None:
            return RulingVerdict(
                ConditionResult.UNKNOWN,
                f"{card.card_id} 에 대해 확인된 것이 없습니다.",
            )

        fact = facts.answer_for(question)
        if fact is None:
            return RulingVerdict(
                ConditionResult.UNKNOWN,
                f"{card.card_id} 에 대해 '{question.value}' 는 확인되지 "
                "않았습니다.",
            )
        if fact.answer is ConditionResult.FALSE:
            # **막는 것은 혼자서도 막는다.** 판을 더 볼 필요가 없다.
            return RulingVerdict(ConditionResult.FALSE, fact.note)

        blocker = self._interference(instance)
        if blocker is not None:
            return RulingVerdict(ConditionResult.UNKNOWN, blocker)
        return RulingVerdict(ConditionResult.TRUE, fact.note)

    def may(
        self, question: RuleQuestion, instance: InstanceId
    ) -> ConditionResult:
        return self.explain(question, instance).answer

    # 옛 프로토콜들. **같은 자리로 들어간다** — 두 벌로 갈리지 않게.
    def may_be_sent_to_grave(self, instance: InstanceId) -> ConditionResult:
        return self.may(RuleQuestion.MAY_BE_SENT_TO_GRAVE, instance)

    def may_be_discarded(self, instance: InstanceId) -> ConditionResult:
        return self.may(RuleQuestion.MAY_BE_DISCARDED, instance)

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        """
        **언제나 ``UNKNOWN``.** 파괴 지식은 이 계층에 없다.

        내성 · 대체 효과 · 동시 파괴 처리를 카드 텍스트 한 줄로 환원할 수
        없고, 환원한 척하면 내성을 가진 카드가 실제로 파괴된다.
        """
        return ConditionResult.UNKNOWN

    def may_be_special_summoned(self, instance: InstanceId) -> ConditionResult:
        """**언제나 ``UNKNOWN``.** 소생 제한은 카드가 아니라 **이력**이다."""
        return ConditionResult.UNKNOWN

    # ------------------------------------------------------------------
    def _interference(self, target: InstanceId) -> "str | None":
        """
        판에 **막을 수 있는 것**이 있는가. 없으면 ``None``.

        모르는 카드를 하나라도 만나면 그 자리에서 멈춘다 — "아무도 안
        막는다" 는 판 전체를 다 읽었을 때만 할 수 있는 말이다.
        """
        for player in self._view.players:
            for zone in player.zones:
                if zone.zone not in INTERFERENCE_ZONES:
                    continue
                for card in zone.cards:
                    if card is None or card.instance_id == target:
                        continue
                    if not card.face_up:
                        # 세트된 카드는 효과를 적용하지 않는다 (룰북).
                        continue
                    if card.card_id is None:
                        return (
                            f"{zone.zone.value} 에 정체를 알 수 없는 앞면 "
                            "카드가 있어 막는 것이 있는지 볼 수 없습니다."
                        )
                    facts = self._registry.facts_for(card.card_id)
                    if facts is None:
                        return (
                            f"{zone.zone.value} 의 {card.card_id} 에 대해 "
                            "확인된 것이 없어, 그것이 막는지 알 수 없습니다."
                        )
                    if facts.restricts_others:
                        return (
                            f"{zone.zone.value} 의 {card.card_id} 는 다른 "
                            "카드의 조작을 막을 수 있습니다."
                        )
        return None

    def scope_limits(self) -> tuple[str, ...]:
        """
        **무엇을 보지 않았는가.** 통과한 답에도 이것이 함께 있다.

        지금 이 목록을 결과에 실어 보낼 자리가 없다 (STRUCTURAL-98). 그래서
        여기에서라도 값으로 들고 있는다 — 문서에만 적으면 썩는다.
        """
        return tuple(f"{where}: {why}" for where, why in UNSCANNED_ZONES.items())

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<BoardRuling viewer=P{self._view.viewer} {self._registry!r}>"


__all__ = [
    "RulingError",
    "RuleBasis",
    "RuleFact",
    "CardRuleFacts",
    "TOKEN_RULE",
    "NORMAL_MONSTER_RULE",
    "TOKEN_FORBIDDEN",
    "normal_monster_facts",
    "token_facts",
    "OperationRulingRegistry",
    "INTERFERENCE_ZONES",
    "UNSCANNED_ZONES",
    "OperationRuling",
    "RulingVerdict",
    "BoardRuling",
]
