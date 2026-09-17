"""
카드 검색 / 필터 엔진.

:class:`SearchFilters` 는 구조화된 검색 조건을 담는다.
한국어 자연어 질의는 :mod:`core.query_parser` 가 이 구조로 바꿔준 뒤 여기로 넘긴다.

조건 결합 규칙:
- 같은 항목 안의 여러 값은 OR (예: 종족 [기계, 전사] -> 기계족 또는 전사족)
- 서로 다른 항목끼리는 AND (예: 종족 + 속성 -> 둘 다 만족)

효과 관련 조건은 Lua 스크립트에서 추출한 의미 정보를 사용하므로,
카드 텍스트의 글자 일치에 의존하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from core import constants as C
from core.card_model import Card
from core.card_repository import CardRepository, normalize_name


@dataclass(slots=True)
class EffectLocationFilter:
    """'특정 위치에서 특정 일을 하는 효과' 조건."""

    location: str
    """LOCATION_* 접두사를 뺀 이름. 예: 'HAND', 'GRAVE'"""
    category: str | None = None
    """CATEGORY_* 접두사를 뺀 이름. 예: 'SPECIAL_SUMMON'. None 이면 위치만 본다."""

    def matches(self, card: Card) -> bool:
        return card.has_effect_from(self.location, self.category)


@dataclass(slots=True)
class SearchFilters:
    """구조화된 검색 조건."""

    # --- 이름 / 텍스트 ---
    name: str | None = None
    name_exact: bool = False
    text_keywords: list[str] = field(default_factory=list)
    """공식 카드 텍스트 부분 일치 (원문 기준)."""

    # --- 분류 ---
    races: list[int] = field(default_factory=list)
    attributes: list[int] = field(default_factory=list)
    required_types: int = 0
    """반드시 포함해야 하는 TYPE_* 비트 (AND)."""
    excluded_types: int = 0
    """포함되면 안 되는 TYPE_* 비트."""

    # --- 수치 ---
    levels: list[int] = field(default_factory=list)
    """**실제 레벨**. 엑시즈(랭크)와 링크(링크 수)는 레벨이 없으므로 제외된다.
    여러 값은 OR."""
    level_min: int | None = None
    level_max: int | None = None
    ranks: list[int] = field(default_factory=list)
    """엑시즈 몬스터의 랭크. 여러 값은 OR."""
    link_ratings: list[int] = field(default_factory=list)
    """링크 몬스터의 링크 수. 여러 값은 OR."""
    atk_min: int | None = None
    atk_max: int | None = None
    def_min: int | None = None
    def_max: int | None = None

    # --- 효과 의미 (Lua 기반) ---
    effect_categories: list[str] = field(default_factory=list)
    """CATEGORY_* (접두사 제외). 예: ['SPECIAL_SUMMON', 'DRAW']"""
    effect_locations: list[EffectLocationFilter] = field(default_factory=list)
    effect_codes: list[str] = field(default_factory=list)
    """EFFECT_*/EVENT_* 전체 이름. 예: ['EFFECT_SPSUMMON_PROC']"""
    self_special_summon_from_hand: bool = False
    """패에서 스스로 특수 소환하는 절차(EFFECT_SPSUMMON_PROC)를 가진 카드만."""
    special_summon_from_hand: bool = False
    """패에서의 특수 소환에 관여하는 카드. 자체 특수 소환 절차 또는
    패에서 발동하는 특수 소환 효과 중 하나라도 있으면 일치한다."""
    support_races: list[int] = field(default_factory=list)
    """'마법사족에 좋은 카드' 같은 서포트 질의용.
    해당 종족이거나, 공식 카드 텍스트 원문이 그 종족을 언급하면 일치한다."""

    # --- 덱 구성 ---
    archetype: str | None = None
    main_deck_only: bool = False
    extra_deck_only: bool = False
    related_to: int | None = None
    """이 카드 ID 와 관계(지명/피지명/같은 카드군)가 있는 카드만."""

    # --- 출력 제어 ---
    ot: int | None = None
    include_alternates: bool = False
    limit: int | None = None
    sort_by: str = "relevance"
    """relevance | name | level | atk | id"""

    def is_empty(self) -> bool:
        """아무 조건도 없는지."""
        return not any(
            (
                self.name,
                self.text_keywords,
                self.races,
                self.attributes,
                self.required_types,
                self.excluded_types,
                self.levels,
                self.level_min is not None,
                self.level_max is not None,
                self.ranks,
                self.link_ratings,
                self.atk_min is not None,
                self.atk_max is not None,
                self.def_min is not None,
                self.def_max is not None,
                self.effect_categories,
                self.effect_locations,
                self.effect_codes,
                self.self_special_summon_from_hand,
                self.special_summon_from_hand,
                self.support_races,
                self.archetype,
                self.main_deck_only,
                self.extra_deck_only,
                self.related_to is not None,
                self.ot is not None,
            )
        )

    def describe_ko(self) -> str:
        """어떤 조건으로 검색했는지 한국어로 설명한다 (파싱 결과 확인용)."""
        parts: list[str] = []
        if self.name:
            parts.append(f"이름 {'정확히 ' if self.name_exact else ''}'{self.name}'")
        for bit in self.races:
            parts.append(f"{C.RACE_KO.get(bit, '?')}족")
        for bit in self.attributes:
            parts.append(f"{C.ATTRIBUTE_KO.get(bit, '?')}속성")
        if self.levels:
            parts.append("레벨 " + "/".join(str(v) for v in sorted(self.levels)))
        if self.level_min is not None or self.level_max is not None:
            lo = self.level_min if self.level_min is not None else ""
            hi = self.level_max if self.level_max is not None else ""
            parts.append(f"레벨 {lo}~{hi}")
        if self.ranks:
            parts.append("랭크 " + "/".join(str(v) for v in sorted(self.ranks)))
        if self.link_ratings:
            parts.append("링크 " + "/".join(str(v) for v in sorted(self.link_ratings)))
        if self.required_types:
            parts.extend(
                ko for bit, ko in C.TYPE_KO.items() if self.required_types & bit
            )
        if self.atk_min is not None:
            parts.append(f"공격력 {self.atk_min} 이상")
        if self.atk_max is not None:
            parts.append(f"공격력 {self.atk_max} 이하")
        if self.def_min is not None:
            parts.append(f"수비력 {self.def_min} 이상")
        if self.def_max is not None:
            parts.append(f"수비력 {self.def_max} 이하")
        for cat in self.effect_categories:
            parts.append(f"효과:{cat}")
        for loc in self.effect_locations:
            label = f"{loc.location}에서 발동"
            if loc.category:
                label += f"({loc.category})"
            parts.append(label)
        if self.self_special_summon_from_hand:
            parts.append("패에서 자체 특수 소환")
        if self.special_summon_from_hand:
            parts.append("패에서 특수 소환")
        for bit in self.support_races:
            parts.append(f"{C.RACE_KO.get(bit, '?')}족 서포트")
        if self.archetype:
            parts.append(f"카드군 {self.archetype}")
        if self.main_deck_only:
            parts.append("메인 덱")
        if self.extra_deck_only:
            parts.append("엑스트라 덱")
        for kw in self.text_keywords:
            parts.append(f"텍스트 '{kw}'")
        return ", ".join(parts) if parts else "(조건 없음)"


@dataclass(slots=True)
class SearchResult:
    cards: list[Card]
    total: int
    """limit 적용 전 전체 건수."""
    filters: SearchFilters

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)


class CardSearchEngine:
    """:class:`SearchFilters` 를 실제 카드 집합에 적용한다."""

    def __init__(self, repository: CardRepository):
        self.repository = repository

    # ------------------------------------------------------------------
    def search(self, filters: SearchFilters) -> SearchResult:
        candidates = self._candidates(filters)
        matched = [c for c in candidates if self._matches(c, filters)]

        if not filters.include_alternates:
            matched = self.repository.deduplicate(matched)

        matched = self._sort(matched, filters)
        total = len(matched)
        if filters.limit is not None:
            matched = matched[: filters.limit]
        return SearchResult(cards=matched, total=total, filters=filters)

    # ------------------------------------------------------------------
    def _candidates(self, filters: SearchFilters) -> Iterable[Card]:
        """
        인덱스를 이용해 전수 검사 대상을 줄인다.
        가장 선택도가 높은 인덱스 하나만 쓰고 나머지는 술어로 거른다.
        """
        if filters.related_to is not None:
            return self.repository.related_cards(filters.related_to)
        if filters.archetype:
            return self.repository.by_archetype(filters.archetype)
        if filters.name and filters.name_exact:
            return self.repository.find_by_exact_name(filters.name)
        if len(filters.races) == 1:
            return self.repository.by_race(filters.races[0])
        if len(filters.attributes) == 1:
            return self.repository.by_attribute(filters.attributes[0])
        if len(filters.levels) == 1:
            return self.repository.by_level(filters.levels[0])
        if len(filters.ranks) == 1:
            return self.repository.by_rank(filters.ranks[0])
        if len(filters.link_ratings) == 1:
            return self.repository.by_link_rating(filters.link_ratings[0])
        return self.repository.all_cards(include_alternates=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _matches(card: Card, f: SearchFilters) -> bool:
        # --- 카드 종류 ---
        if f.required_types and (card.type_mask & f.required_types) != f.required_types:
            return False
        if f.excluded_types and (card.type_mask & f.excluded_types):
            return False
        if f.main_deck_only and card.is_extra_deck:
            return False
        if f.extra_deck_only and not card.is_extra_deck:
            return False

        # --- 분류 ---
        if f.races and not any(card.race_mask & bit for bit in f.races):
            return False
        if f.attributes and not any(card.attribute_mask & bit for bit in f.attributes):
            return False

        # --- 수치 ---
        # 레벨 / 랭크 / 링크는 cards.cdb 의 같은 컬럼에 저장되지만 서로 다른
        # 개념이다. 엑시즈에는 레벨이 없고(랭크), 링크에도 레벨이 없다(링크 수).
        # 그래서 원시값(card.level)이 아니라 종류별 속성으로 비교한다.
        if f.levels or f.level_min is not None or f.level_max is not None:
            level = card.monster_level  # 엑시즈/링크/비몬스터는 None
            if level is None:
                return False
            if f.levels and level not in f.levels:
                return False
            if f.level_min is not None and level < f.level_min:
                return False
            if f.level_max is not None and level > f.level_max:
                return False
        if f.ranks:
            if card.rank is None or card.rank not in f.ranks:
                return False
        if f.link_ratings:
            if card.link_rating is None or card.link_rating not in f.link_ratings:
                return False
        if f.atk_min is not None and (card.atk < 0 or card.atk < f.atk_min):
            return False
        if f.atk_max is not None and (card.atk < 0 or card.atk > f.atk_max):
            return False
        if f.def_min is not None and (card.defense < 0 or card.defense < f.def_min):
            return False
        if f.def_max is not None and (card.defense < 0 or card.defense > f.def_max):
            return False

        # --- 이름 / 텍스트 ---
        if f.name:
            key = normalize_name(f.name)
            names = [
                normalize_name(n)
                for n in (card.name, card.name_en, card.name_ja, card.name_ko)
                if n
            ]
            if f.name_exact:
                if key not in names:
                    return False
            elif not any(key in n for n in names):
                return False
        for keyword in f.text_keywords:
            # 한국어 텍스트와 원문을 모두 대상으로 한다.
            haystack = (
                f"{card.desc} {card.desc_en} {' '.join(card.strings)}".casefold()
            )
            if keyword.casefold() not in haystack:
                return False

        # --- 효과 의미 ---
        for category in f.effect_categories:
            if not card.has_effect_category(category):
                return False
        for location_filter in f.effect_locations:
            if not location_filter.matches(card):
                return False
        for code in f.effect_codes:
            if not card.has_effect_code(code):
                return False
        if f.self_special_summon_from_hand and not card.can_self_special_summon_from_hand:
            return False
        if f.special_summon_from_hand and not (
            card.can_self_special_summon_from_hand
            or card.has_effect_from("HAND", "SPECIAL_SUMMON")
        ):
            return False
        if f.support_races and not any(
            CardSearchEngine._supports_race(card, bit) for bit in f.support_races
        ):
            return False

        # --- 발매 구분 ---
        if f.ot is not None and not (card.ot & f.ot):
            return False

        return True

    @staticmethod
    def _supports_race(card: Card, race_bit: int) -> bool:
        """
        해당 종족이거나, 카드 텍스트가 그 종족을 언급하는지.

        한국어 데이터가 적용되면 ``desc`` 가 한국어로 바뀌므로 두 언어를 모두 본다.
        한국어 텍스트는 "마법사족", 영어 원문은 "Spellcaster" 로 표기한다.
        """
        if card.race_mask & race_bit:
            return True
        korean = C.RACE_KO.get(race_bit)
        if korean and card.desc and f"{korean}족" in card.desc:
            return True
        english = C.RACE_TEXT_EN.get(race_bit, ())
        for text in (card.desc_en, card.desc):
            if text and any(term in text for term in english):
                return True
        return False

    # ------------------------------------------------------------------
    def _sort(self, cards: list[Card], f: SearchFilters) -> list[Card]:
        if f.sort_by == "name":
            return sorted(cards, key=lambda c: c.display_name())
        if f.sort_by == "level":
            return sorted(cards, key=lambda c: (-c.level, c.display_name()))
        if f.sort_by == "atk":
            return sorted(cards, key=lambda c: (-(c.atk if c.atk >= 0 else -1), c.display_name()))
        if f.sort_by == "id":
            return sorted(cards, key=lambda c: c.id)
        return sorted(cards, key=lambda c: (-self._relevance(c, f), c.display_name()))

    @staticmethod
    def _relevance(card: Card, f: SearchFilters) -> int:
        """
        간단한 관련도 점수.
        이름이 정확히 일치할수록, 그리고 요청한 효과를 많이 가질수록 높다.
        """
        score = 0
        if f.name:
            key = normalize_name(f.name)
            for name in (card.name, card.name_ko, card.name_en, card.name_ja):
                if not name:
                    continue
                normalized = normalize_name(name)
                if normalized == key:
                    score += 100
                    break
                if normalized.startswith(key):
                    score += 50
                    break
        for category in f.effect_categories:
            score += sum(1 for e in card.effects if e.has_category(category))
        for location_filter in f.effect_locations:
            score += sum(
                1 for e in card.effects if e.usable_from(location_filter.location)
            )
        # 효과 정보가 있는 카드를 조금 더 위로 (스크립트 없는 카드는 판단 근거가 적다)
        if card.script is not None:
            score += 1
        return score

    # ------------------------------------------------------------------
    def group_by_archetype(self, cards: Iterable[Card]) -> dict[str, list[Card]]:
        """검색 결과를 카드군별로 묶는다 (덱 구성 검토용)."""
        groups: dict[str, list[Card]] = {}
        for card in cards:
            names = self.repository.archetype_name(card) or ["(카드군 없음)"]
            for name in names:
                groups.setdefault(name, []).append(card)
        return groups
