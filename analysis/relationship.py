"""
카드 관계 모델.

가장 중요한 구분은 **소속**과 **상호작용**이다.

- 소속(``ARCHETYPE``): 공식 DB 의 ``setcode`` 가 근거다. "이 카드는 오르페골이다."
- 상호작용(그 외): 카드 텍스트나 효과가 근거다. "이 카드는 오르페골을 지명한다",
  "이 카드는 오르페골 몬스터를 묘지에서 특수 소환한다."

카드 텍스트에 이름이 등장한다는 이유로 소속을 판정하지 않는다. 성유물－『성장』은
성유물 카드군이고 오르페골을 지명할 뿐이며, 오르페골 카드가 아니다.

콤보 탐색을 위한 구조
---------------------
이동을 일으키는 관계는 ``from_location`` / ``to_location`` / ``constraint`` 를
가진다. 이것이 "어떤 카드를 어디에서 어디로 옮기는가"라는 상태 전이가 되고,
:meth:`RelationshipBuilder.find_sources` 로 역방향 질의를 할 수 있다
(예: "오르페골 몬스터를 묘지에서 꺼낼 수 있는 카드는?").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from analysis.effect_model import ActionKind, CardAnalysis, CardConstraint


class RelationshipKind(str, Enum):
    """관계의 종류."""

    # --- 소속 ---
    ARCHETYPE = "archetype"
    """공식 setcode 기준 카드군 소속. 유일한 '소속' 관계다."""

    # --- 텍스트 기반 상호작용 ---
    SERIES = "series"
    """카드 텍스트가 그 카드군을 지명한다 (소속이 아니다)."""
    LISTED_NAME = "listed_name"
    """카드 텍스트가 특정 카드를 이름으로 지명한다."""
    REFERENCES = "references"
    """효과 안에서 특정 카드 ID 를 참조한다."""

    # --- 효과 기반 상호작용 ---
    SEARCHES = "searches"
    """덱에서 패로 가져온다."""
    SUMMONS = "summons"
    SENDS_TO_GRAVE = "sends_to_grave"
    DESTROYS = "destroys"
    BANISHES = "banishes"
    BOUNCES = "bounces"
    """필드/묘지에서 패나 덱으로 되돌린다."""
    TARGETS = "targets"
    """규칙상 '대상으로 지정'한다."""


#: 소속으로 취급하는 관계. 나머지는 모두 상호작용이다.
MEMBERSHIP_KINDS = frozenset({RelationshipKind.ARCHETYPE})

#: 효과 액션 -> 관계 종류
_ACTION_TO_KIND: dict[ActionKind, RelationshipKind] = {
    ActionKind.SPECIAL_SUMMON: RelationshipKind.SUMMONS,
    ActionKind.NORMAL_SUMMON: RelationshipKind.SUMMONS,
    ActionKind.TO_GRAVE: RelationshipKind.SENDS_TO_GRAVE,
    ActionKind.DESTROY: RelationshipKind.DESTROYS,
    ActionKind.BANISH: RelationshipKind.BANISHES,
    ActionKind.TO_DECK: RelationshipKind.BOUNCES,
}


@dataclass(slots=True)
class CardRelationship:
    """카드 한 장에서 나가는 관계 하나."""

    source_card_id: int
    kind: RelationshipKind
    target_card_id: int | None = None
    """상대가 특정 카드일 때."""
    target_archetype: str | None = None
    """상대가 카드군일 때."""
    constraint: CardConstraint | None = None
    """상대가 '조건에 맞는 카드'일 때 (증원의 레벨 4 이하 전사족 등)."""
    from_location: str | None = None
    to_location: str | None = None
    effect_index: str | None = None
    evidence: str = ""
    """판정 근거. 소속은 ``setcode:...``, 효과 유래는 ``effect:...`` 로 시작한다."""

    @property
    def is_membership(self) -> bool:
        """'같은 카드군이다'인가, 아니면 '상호작용한다'인가."""
        return self.kind in MEMBERSHIP_KINDS

    def describe_ko(self) -> str:
        who = (
            f"카드 {self.target_card_id}"
            if self.target_card_id is not None
            else (self.target_archetype or "조건에 맞는 카드")
        )
        move = ""
        if self.from_location or self.to_location:
            move = f" ({self.from_location or '?'}→{self.to_location or '?'})"
        return f"{self.kind.value}: {who}{move}"


class RelationshipBuilder:
    """
    카드의 관계를 만든다.

    카드군 소속은 리포지토리의 공식 setcode 에서, 텍스트 지명은 Lua 의
    ``listed_names`` / ``listed_series`` 에서, 나머지는 효과 분석 결과에서 얻는다.
    새 관계 알고리즘을 만들지 않고 이미 있는 데이터를 엮기만 한다.
    """

    def __init__(self, repository, analyzer):
        self.repository = repository
        self.analyzer = analyzer
        self._cache: dict[int, list[CardRelationship]] = {}

    # ------------------------------------------------------------------
    def for_card(self, card_id: int) -> list[CardRelationship]:
        cached = self._cache.get(card_id)
        if cached is not None:
            return cached

        card = self.repository.get(card_id)
        if card is None:
            return []
        analysis = self.analyzer.analyze(card)
        relationships = [
            *self._membership(card_id, analysis),
            *self._text_references(card_id, analysis),
            *self._effect_relationships(card_id, analysis),
        ]
        self._cache[card_id] = relationships
        return relationships

    # ------------------------------------------------------------------
    @staticmethod
    def _membership(card_id: int, analysis: CardAnalysis):
        """공식 setcode 로만 소속을 판정한다."""
        for name in analysis.setcodes:
            yield CardRelationship(
                source_card_id=card_id,
                kind=RelationshipKind.ARCHETYPE,
                target_archetype=name,
                evidence=f"setcode:{name}",
            )

    @staticmethod
    def _text_references(card_id: int, analysis: CardAnalysis):
        """
        카드 텍스트가 지명하는 대상. 지명은 소속이 아니다.

        스크립트가 자기 카드군을 지명하는 일도 흔한데(자신을 참조하는 효과),
        소속 여부와는 별개로 기록한다. 소속은 setcode 만이 근거다.
        """
        for name in analysis.listed_series:
            yield CardRelationship(
                source_card_id=card_id,
                kind=RelationshipKind.SERIES,
                target_archetype=name,
                evidence=f"listed_series:{name}",
            )
        for code in analysis.listed_card_codes:
            if code == card_id:
                continue  # 자기 자신 지명은 관계로 세지 않는다
            yield CardRelationship(
                source_card_id=card_id,
                kind=RelationshipKind.LISTED_NAME,
                target_card_id=code,
                evidence=f"listed_names:{code}",
            )

    def _effect_relationships(self, card_id: int, analysis: CardAnalysis):
        """효과가 실제로 무엇을 하는지에서 관계를 유도한다."""
        for effect in analysis.effects:
            if effect.targets_card and effect.selection:
                yield self._from_selection(
                    card_id, effect, RelationshipKind.TARGETS, None
                )
            for action in effect.actions:
                kind = self._kind_for_action(action)
                if kind is None:
                    continue
                yield self._relationship_for_action(card_id, effect, action, kind)

    @staticmethod
    def _kind_for_action(action) -> RelationshipKind | None:
        if action.kind is ActionKind.TO_HAND:
            # 덱에서 패로 가져오면 서치, 필드/묘지에서면 회수(바운스)다.
            if "DECK" in action.from_locations:
                return RelationshipKind.SEARCHES
            return RelationshipKind.BOUNCES
        return _ACTION_TO_KIND.get(action.kind)

    @staticmethod
    def _relationship_for_action(card_id, effect, action, kind):
        constraint = action.constraint
        archetype = None
        target_card = None
        if constraint is not None:
            if constraint.setcodes:
                archetype = constraint.setcodes[0]
            if len(constraint.card_codes) == 1:
                target_card = constraint.card_codes[0]
        return CardRelationship(
            source_card_id=card_id,
            kind=kind,
            target_card_id=target_card,
            target_archetype=archetype,
            constraint=constraint,
            from_location=action.from_locations[0] if action.from_locations else None,
            to_location=action.to_location,
            effect_index=effect.index,
            evidence=f"effect:{effect.index}:{action.raw}",
        )

    @staticmethod
    def _from_selection(card_id, effect, kind, to_location):
        selection = effect.selection
        constraint = selection.constraint if selection else None
        archetype = (
            constraint.setcodes[0] if constraint and constraint.setcodes else None
        )
        return CardRelationship(
            source_card_id=card_id,
            kind=kind,
            target_archetype=archetype,
            constraint=constraint,
            from_location=selection.locations[0]
            if selection and selection.locations
            else None,
            to_location=to_location,
            effect_index=effect.index,
            evidence=f"effect:{effect.index}:target",
        )

    # ------------------------------------------------------------------
    def find_sources(
        self,
        kind: RelationshipKind,
        archetype: str | None = None,
        from_location: str | None = None,
        to_location: str | None = None,
        cards=None,
    ) -> list[CardRelationship]:
        """
        역방향 질의: 조건에 맞는 관계를 가진 **카드를 찾는다**.

        콤보 탐색의 기본 물음 — "오르페골 몬스터를 묘지에서 특수 소환할 수 있는
        카드는 무엇인가" — 에 답하기 위한 진입점이다.

        Args:
            cards: 검사 대상. 생략하면 카드군 소속 카드로 좁히고,
                그것도 없으면 스크립트가 있는 카드 전체를 본다(느리다).
        """
        if cards is None:
            cards = self._candidates(archetype)

        found: list[CardRelationship] = []
        for card in cards:
            for relation in self.for_card(card.id):
                if relation.kind is not kind:
                    continue
                if archetype and relation.target_archetype != archetype:
                    continue
                if from_location and relation.from_location != from_location:
                    continue
                if to_location and relation.to_location != to_location:
                    continue
                found.append(relation)
        return found

    def _candidates(self, archetype: str | None):
        """
        검사 대상 카드. 카드군이 주어지면 그 카드군과, 그 카드군을 지명하는
        카드만 본다 (전수 검사를 피한다).
        """
        if archetype:
            members = {c.id: c for c in self.repository.by_archetype(archetype)}
            for card in self.repository.by_series(archetype):
                members.setdefault(card.id, card)
            return list(members.values())
        return [c for c in self.repository.all_cards() if c.script]
