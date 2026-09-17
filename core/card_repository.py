"""
카드 리포지토리.

공식 데이터베이스(수치 메타데이터 + 카드 텍스트)와 Lua 스크립트(효과 의미 정보)를
카드 ID 기준으로 합쳐 하나의 :class:`~core.card_model.Card` 집합으로 만든다.
검색 계층이 쓰는 인덱스도 여기서 구축한다.

두 소스의 ID 는 실측 기준 12,702 개 중 12,696 개가 일치하므로 ID 조인이 안전하다.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from core import constants as C
from core.card_model import Card, CardSource, LuaScriptInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT_DIR = PROJECT_ROOT
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

_RE_NORMALIZE = re.compile(r"[\s\-·・:：,，.。'\"()\[\]{}!?/\\]+")


def normalize_name(name: str) -> str:
    """
    이름 비교용 정규화.

    대소문자, 공백, 문장부호, 전각/반각 차이를 무시한다.
    한국어/일본어/영어 카드명 모두 같은 규칙을 적용한다.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).casefold()
    return _RE_NORMALIZE.sub("", text)


# 관계의 종류. 검색 결과가 '왜' 관련되었는지 구분하기 위해 쓴다.
RELATION_ARCHETYPE = "archetype"
"""공식 DB 의 setcode 로 같은 카드군에 속한다."""
RELATION_LISTED_NAME = "listed_name"
"""기준 카드의 텍스트가 이 카드를 이름으로 지명한다."""
RELATION_REFERENCED_BY = "referenced_by"
"""이 카드의 텍스트가 기준 카드를 이름으로 지명한다."""
RELATION_SERIES = "series"
"""이 카드의 스크립트가 그 카드군을 지명한다(카드군 서포트)."""


@dataclass(slots=True)
class CardRelation:
    """관련 카드 한 장과, 어떤 근거로 연결되었는지."""

    card: Card
    relation_types: list[str] = field(default_factory=list)

    def add(self, relation_type: str) -> None:
        if relation_type not in self.relation_types:
            self.relation_types.append(relation_type)


@dataclass(slots=True)
class ArchetypeMatch:
    """이름이 카드군으로 해석되었을 때의 결과."""

    term: str
    names: list[str] = field(default_factory=list)
    """확인된 카드군 상수 이름 (SET_ 접두사 제외). 예: ['ORCUST']"""
    setcodes: list[int] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    """카드군 소속 카드 (공식 setcode 기준)."""


@dataclass(slots=True)
class RelationMatch:
    """이름이 관계 검색으로 해석되었을 때의 결과."""

    term: str
    seeds: list[Card] = field(default_factory=list)
    """기준이 된 카드들 (이름이 그 말과 맞는 카드)."""
    archetype: ArchetypeMatch | None = None
    relations: list[CardRelation] = field(default_factory=list)

    @property
    def cards(self) -> list[Card]:
        return [r.card for r in self.relations]

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for relation in self.relations:
            for relation_type in relation.relation_types:
                counts[relation_type] = counts.get(relation_type, 0) + 1
        return counts


@dataclass(slots=True)
class ExactNameMatch:
    """
    질의 전체가 실제 카드명과 정확히 일치했을 때의 결과.

    '몇 종의 카드인가'와 '그 카드에 판본이 몇 개인가'는 다른 값이다.
    같은 카드의 다른 일러스트/에라타는 각각 패스코드를 갖지만 카드로는 1종이다.
    """

    query: str
    cards: list[Card] = field(default_factory=list)
    """중복 제거된 카드 목록 (종)."""
    printings: dict[int, list[int]] = field(default_factory=dict)
    """카드 ID -> 그 카드의 모든 패스코드 (판본)."""

    @property
    def card_count(self) -> int:
        """정확히 일치한 카드 종 수."""
        return len(self.cards)

    @property
    def printing_count(self) -> int:
        """그 카드들의 판본 총 개수."""
        return sum(len(v) for v in self.printings.values())


class CardRepository:
    """카드 적재/보관/조회 계층."""

    def __init__(self, cards: dict[int, Card], constants=None):
        from sources.script_constants import ScriptConstants

        self._cards: dict[int, Card] = cards
        self.constants = constants if constants is not None else ScriptConstants()
        self._by_normalized_name: dict[str, list[int]] = defaultdict(list)
        self._by_race: dict[int, list[int]] = defaultdict(list)
        self._by_attribute: dict[int, list[int]] = defaultdict(list)
        self._by_level: dict[int, list[int]] = defaultdict(list)
        self._by_rank: dict[int, list[int]] = defaultdict(list)
        self._by_link_rating: dict[int, list[int]] = defaultdict(list)
        self._by_setcode: dict[int, list[int]] = defaultdict(list)
        self._by_series: dict[str, list[int]] = defaultdict(list)
        self._referenced_by: dict[int, list[int]] = defaultdict(list)
        self._build_indexes()

    # ------------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------------
    @classmethod
    def build(
        cls,
        db_path: str | os.PathLike[str] | None = None,
        script_dir: str | os.PathLike[str] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        constant_dir: str | os.PathLike[str] | None = None,
        use_cache: bool = True,
        korean_source=None,
        use_korean: bool = True,
    ) -> CardRepository:
        """
        공식 DB 와 Lua 스크립트를 읽어 리포지토리를 만든다.

        Args:
            db_path: ``cards.cdb`` 경로. 생략하면 자동 탐색한다.
            script_dir: ``c*.lua`` 가 있는 디렉터리. 기본값은 저장소 루트.
            cache_dir: Lua 파싱 캐시 위치.
            constant_dir: CARD_*/SET_* 상수 파일 디렉터리.
            use_cache: Lua 파싱 결과 캐시 사용 여부.
            korean_source: 한국어 카드명/텍스트 오버레이 소스.
                생략하면 ``use_korean`` 에 따라 자동으로 찾는다.
            use_korean: 참이면 한국어 데이터를 자동 탐색해 적용한다.
                진입점에 따라 표시 언어가 달라지지 않도록 기본값은 참이다.
        """
        from sources.korean_names import KoreanTextSource
        from sources.lua_loader import LuaScriptSource
        from sources.official_db import OfficialDatabaseSource
        from sources.script_constants import ScriptConstants

        official = OfficialDatabaseSource(db_path)
        cards = official.load()

        lua = LuaScriptSource(script_dir or DEFAULT_SCRIPT_DIR)
        if use_cache:
            cache_path = Path(cache_dir or DEFAULT_CACHE_DIR) / "lua_scripts.json"
            scripts = lua.load_cached(cache_path)
        else:
            scripts = lua.load()

        cls._attach_scripts(cards, scripts)

        constants = ScriptConstants.load(constant_dir)
        cls._resolve_script_constants(cards, constants)

        if korean_source is None and use_korean:
            korean_source = KoreanTextSource.autoload()
        if korean_source:
            korean_source.apply(cards)

        cls._record_provenance(cards)
        return cls(cards, constants=constants)

    @staticmethod
    def _record_provenance(cards: dict[int, Card]) -> None:
        """
        카드마다 어떤 소스가 무엇을 채웠는지 기록한다.

        카드 전체에 점수 하나를 매기지 않고 필드별로 남긴다. Lua 가 없는
        신규 카드도 여기서 '효과 분석 없음' 으로 표시될 뿐, 카드로서는
        온전히 등록된다.
        """
        from core.provenance import (
            AnalysisStatus,
            CardProvenance,
            FieldStatus,
            SourceKind,
        )

        for card in cards.values():
            record = CardProvenance(card_id=card.id)
            availability = record.availability

            if CardSource.OFFICIAL_DB in card.sources:
                availability.cdb_available = True
                record.record("basic_info", SourceKind.OFFICIAL_DB)
                record.record("card_name", SourceKind.OFFICIAL_DB)
            if card.desc_en:
                availability.official_text_available = True
                record.record("effect_text", SourceKind.OFFICIAL_TEXT)
            if card.name_ko:
                availability.korean_available = True
                record.record("card_name", SourceKind.KOREAN_DB)
                record.record("effect_text", SourceKind.KOREAN_DB)
            if card.script is not None:
                availability.lua_available = True
                availability.effect_analysis_available = True
                record.record("effect_analysis", SourceKind.LUA)
                record.analysis_status = AnalysisStatus.LUA_VERIFIED
            elif card.desc:
                # Lua 가 없으면 텍스트에서 유추할 수 있을 뿐이다.
                # 실제 게임 처리와 어긋날 수 있으므로 상태를 달리 표시한다.
                availability.text_analysis_available = True
                record.record(
                    "effect_analysis",
                    SourceKind.OFFICIAL_TEXT,
                    status=FieldStatus.SUPPLEMENTARY,
                    detail="Lua 없음 — 텍스트 유래",
                )
                record.analysis_status = AnalysisStatus.TEXT_DERIVED
            else:
                record.analysis_status = AnalysisStatus.UNAVAILABLE

            card.provenance = record

    @staticmethod
    def _resolve_script_constants(cards: dict[int, Card], constants) -> None:
        """
        스크립트가 명명 상수로 참조한 카드를 실제 ID 로 바꾼다.

        ``s.listed_names={CARD_DARK_MAGICIAN}`` -> ``[46986414]``
        상수 파일이 없으면 아무것도 하지 않는다(기능 저하만 발생).
        """
        if not constants:
            return
        for card in cards.values():
            info = card.script
            if info is None or not info.listed_name_constants:
                continue
            for token in info.listed_name_constants:
                resolved = constants.card_id(token)
                if resolved is not None and resolved not in info.listed_names:
                    info.listed_names.append(resolved)

    @staticmethod
    def _attach_scripts(
        cards: dict[int, Card], scripts: dict[int, LuaScriptInfo]
    ) -> None:
        """
        Lua 스크립트를 카드에 붙인다.

        - 공식 DB 에 있는 카드: 스크립트를 그대로 연결하고 일본어명을 채운다.
        - 공식 DB 에 없는 스크립트: 스크립트만 가진 Card 를 새로 만든다
          (미발매/비공식 카드. 수치 메타데이터는 없다).
        """
        for card_id, info in scripts.items():
            card = cards.get(card_id)
            if card is None:
                card = Card(
                    id=card_id,
                    name=info.name_en or info.name_ja or f"#{card_id}",
                    sources=set(),
                )
                cards[card_id] = card
            card.script = info
            card.name_ja = info.name_ja
            if not card.name_en:
                card.name_en = info.name_en
            if not card.name:
                card.name = info.name_en or info.name_ja or f"#{card_id}"
            card.sources.add(CardSource.LUA_SCRIPT)

        # alias 판본(다른 일러스트/에라타)은 자체 스크립트가 없는 경우가 많다.
        # 원본 카드의 스크립트를 물려받게 해 검색 결과가 어긋나지 않도록 한다.
        for card in cards.values():
            if card.script is None and card.alias:
                origin = cards.get(card.alias)
                if origin is not None and origin.script is not None:
                    card.script = origin.script

    # ------------------------------------------------------------------
    # 인덱스
    # ------------------------------------------------------------------
    def _build_indexes(self) -> None:
        for card in self._cards.values():
            for name in filter(None, (card.name, card.name_en, card.name_ja, card.name_ko)):
                key = normalize_name(name)
                if key and card.id not in self._by_normalized_name[key]:
                    self._by_normalized_name[key].append(card.id)

            for bit in C.RACE_NAMES:
                if card.race_mask & bit:
                    self._by_race[bit].append(card.id)
            for bit in C.ATTRIBUTE_NAMES:
                if card.attribute_mask & bit:
                    self._by_attribute[bit].append(card.id)
            # 레벨 / 랭크 / 링크는 각각 다른 인덱스에 넣는다.
            # cards.cdb 는 세 값을 한 컬럼에 담지만 의미가 다르기 때문이다.
            if card.monster_level is not None:
                self._by_level[card.monster_level].append(card.id)
            if card.rank is not None:
                self._by_rank[card.rank].append(card.id)
            if card.link_rating is not None:
                self._by_link_rating[card.link_rating].append(card.id)
            for setcode in card.setcodes:
                self._by_setcode[setcode].append(card.id)
            if card.script:
                for series in card.script.listed_series:
                    self._by_series[series].append(card.id)
                for ref in card.script.listed_names:
                    if ref != card.id:
                        self._referenced_by[ref].append(card.id)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._cards)

    def __iter__(self) -> Iterator[Card]:
        return iter(self._cards.values())

    def get(self, card_id: int) -> Card | None:
        return self._cards.get(card_id)

    def all_cards(self, include_alternates: bool = False) -> list[Card]:
        """
        전체 카드 목록.

        ``include_alternates`` 가 거짓이면 alias 판본(다른 일러스트/에라타)을
        제외해 같은 카드가 여러 번 나오지 않게 한다.
        """
        if include_alternates:
            return list(self._cards.values())
        return [c for c in self._cards.values() if not c.is_alternate_art]

    def canonical(self, card: Card) -> Card:
        """alias 판본이면 원본 카드를 돌려준다."""
        if card.alias:
            origin = self._cards.get(card.alias)
            if origin is not None:
                return origin
        return card

    def deduplicate(self, cards: Iterable[Card]) -> list[Card]:
        """결과 목록에서 같은 카드의 다른 판본을 하나로 합친다."""
        seen: set[int] = set()
        out: list[Card] = []
        for card in cards:
            origin = self.canonical(card)
            if origin.id in seen:
                continue
            seen.add(origin.id)
            out.append(origin)
        return out

    # --- 이름 ---
    def find_by_exact_name(self, name: str) -> list[Card]:
        ids = self._by_normalized_name.get(normalize_name(name), [])
        return [self._cards[i] for i in ids]

    def resolve_exact_name(self, query: str) -> ExactNameMatch | None:
        """
        입력 문자열 전체가 실제 카드명과 정확히 일치하는지 검사한다.

        한국어 / 공식 DB 원문 / 일본어 이름을 모두 대조하며, 공백과 문장부호
        차이는 무시한다. 일치하지 않으면 ``None`` 을 돌려주고, 호출자는
        평소의 자연어 파싱 경로로 넘어간다.
        """
        records = self.find_by_exact_name(query)
        if not records:
            return None

        printings: dict[int, list[int]] = {}
        for record in records:
            origin = self.canonical(record)
            printings.setdefault(origin.id, []).append(record.id)
        for passcodes in printings.values():
            passcodes.sort()

        cards = [self._cards[cid] for cid in printings]
        return ExactNameMatch(query=query, cards=cards, printings=printings)

    def find_by_name_substring(self, fragment: str) -> list[Card]:
        """부분 일치 이름 검색 (한/일/영 모두 대상)."""
        key = normalize_name(fragment)
        if not key:
            return []
        out: list[Card] = []
        for card in self._cards.values():
            for name in (card.name, card.name_en, card.name_ja, card.name_ko):
                if name and key in normalize_name(name):
                    out.append(card)
                    break
        return out

    # --- 분류 ---
    def by_race(self, race_bit: int) -> list[Card]:
        return [self._cards[i] for i in self._by_race.get(race_bit, [])]

    def by_attribute(self, attribute_bit: int) -> list[Card]:
        return [self._cards[i] for i in self._by_attribute.get(attribute_bit, [])]

    def by_level(self, level: int) -> list[Card]:
        """실제 레벨이 그 값인 몬스터. 엑시즈/링크는 포함되지 않는다."""
        return [self._cards[i] for i in self._by_level.get(level, [])]

    def by_rank(self, rank: int) -> list[Card]:
        """랭크가 그 값인 엑시즈 몬스터."""
        return [self._cards[i] for i in self._by_rank.get(rank, [])]

    def by_link_rating(self, rating: int) -> list[Card]:
        """링크 수가 그 값인 링크 몬스터."""
        return [self._cards[i] for i in self._by_link_rating.get(rating, [])]

    def by_series(self, series: str) -> list[Card]:
        return [self._cards[i] for i in self._by_series.get(series.upper(), [])]

    def by_setcode(self, setcode: int) -> list[Card]:
        return [self._cards[i] for i in self._by_setcode.get(setcode, [])]

    def by_archetype(self, name: str) -> list[Card]:
        """
        카드군 소속 카드를 찾는다.

        두 근거를 합친다.
        1. 공식 DB 의 ``setcode`` (카드명에 카드군이 포함된 정식 소속)
        2. Lua 의 ``s.listed_series`` (카드 텍스트가 그 카드군을 지명)

        ``SET_LABRYNTH`` 든 ``LABRYNTH`` 든 같은 결과를 준다.
        """
        key = name.upper().removeprefix("SET_")
        found: dict[int, Card] = {}
        code = self.constants.setcode(key)
        if code is not None:
            for card in self.by_setcode(code):
                found[card.id] = card
        for card in self.by_series(key):
            found.setdefault(card.id, card)
        return self.deduplicate(found.values())

    def archetype_name(self, card: Card) -> list[str]:
        """카드가 소속된 카드군의 상수 이름 목록."""
        names: list[str] = []
        for code in card.setcodes:
            label = self.constants.setcode_name(code)
            if label:
                names.append(label.removeprefix("SET_"))
        return names

    # --- 카드군 / 관계 해석 -------------------------------------------
    def _seed_cards(self, term: str) -> list[Card]:
        """이름이 그 말과 맞는 카드들. 정확 일치가 있으면 그것만 쓴다."""
        exact = self.find_by_exact_name(term)
        if exact:
            return self.deduplicate(exact)
        return self.deduplicate(self.find_by_name_substring(term))

    def _dominant_setcodes(
        self, seeds: list[Card], ratio: float = 0.5
    ) -> list[int]:
        """
        씨앗 카드 다수가 공유하는 setcode 만 남긴다.

        오르페골 카드 18장 중 18장이 SET_ORCUST 를 갖지만, 2장은 기교(MEKK_KNIGHT)
        도, 1장은 나이트메어도 겸한다. 교차 소속까지 카드군으로 인정하면
        관련 없는 카드군 전체가 결과에 딸려 들어온다.
        """
        if not seeds:
            return []
        counts: dict[int, int] = {}
        for card in seeds:
            for setcode in card.setcodes:
                counts[setcode] = counts.get(setcode, 0) + 1
        threshold = max(1, int(len(seeds) * ratio))
        return sorted(
            (code for code, n in counts.items() if n >= threshold),
            key=lambda code: -counts[code],
        )

    def resolve_archetype(self, term: str) -> ArchetypeMatch | None:
        """
        입력한 말이 카드군을 가리키는지 판단한다.

        게임 용어("마법", "카운터 함정")는 이름이 겹치는 카드가 많아도 공통
        setcode 가 없으므로 ``None`` 이 되고, 호출자는 평소 경로로 넘어간다.
        """
        if len(term.strip()) < 2:
            return None
        seeds = self._seed_cards(term)
        setcodes = self._dominant_setcodes(seeds)
        if not setcodes:
            return None

        cards: dict[int, Card] = {}
        for setcode in setcodes:
            for card in self.by_setcode(setcode):
                cards[card.id] = card
        names = [
            (self.constants.setcode_name(code) or hex(code)).removeprefix("SET_")
            for code in setcodes
        ]
        return ArchetypeMatch(
            term=term,
            names=names,
            setcodes=setcodes,
            cards=self.deduplicate(cards.values()),
        )

    def relations_for_term(self, term: str) -> RelationMatch | None:
        """
        이름 또는 카드군 이름으로 관련 카드를 모으고, 관계 종류를 함께 기록한다.

        기존 :meth:`related_cards` 는 카드 ID 하나를 기준으로 하지만, 자연어
        질의는 "오르페골" 처럼 카드군 이름으로 들어오므로 이름에서 시작한다.
        """
        seeds = self._seed_cards(term)
        if not seeds:
            return None

        found: dict[int, CardRelation] = {}

        def add(card: Card, relation_type: str) -> None:
            origin = self.canonical(card)
            relation = found.get(origin.id)
            if relation is None:
                relation = CardRelation(card=origin)
                found[origin.id] = relation
            relation.add(relation_type)

        # 1. 공식 카드군 소속
        archetype = self.resolve_archetype(term)
        if archetype:
            for card in archetype.cards:
                add(card, RELATION_ARCHETYPE)

        # 2. 카드 텍스트가 서로를 지명하는 관계
        for seed in seeds:
            for other in self.references_of(seed.id):
                add(other, RELATION_LISTED_NAME)
            for other in self.referenced_by(seed.id):
                add(other, RELATION_REFERENCED_BY)

        # 3. 그 카드군을 지명하는 카드 (카드군 서포트)
        # 확인된 카드군만 쓴다. 씨앗 카드가 지명하는 다른 카드군까지 넣으면
        # 방향이 뒤섞인다 — 오르페골 카드가 성유물을 지명한다는 사실은
        # "성유물 카드가 오르페골과 관련된다"는 뜻이 아니다.
        for name in archetype.names if archetype else []:
            for card in self.by_series(name):
                add(card, RELATION_SERIES)

        if not found:
            return None
        relations = sorted(
            found.values(),
            key=lambda rel: (-len(rel.relation_types), rel.card.display_name()),
        )
        return RelationMatch(
            term=term, seeds=seeds, archetype=archetype, relations=relations
        )

    # --- 관계 ---
    def referenced_by(self, card_id: int) -> list[Card]:
        """이 카드를 카드 텍스트에서 지명하는 카드들 (콤보 후보)."""
        return [self._cards[i] for i in self._referenced_by.get(card_id, [])]

    def references_of(self, card_id: int) -> list[Card]:
        """이 카드가 지명하는 카드들."""
        card = self._cards.get(card_id)
        if card is None or card.script is None:
            return []
        return [
            self._cards[ref]
            for ref in card.script.listed_names
            if ref != card_id and ref in self._cards
        ]

    def related_cards(self, card_id: int) -> list[Card]:
        """양방향 관계(지명 + 피지명 + 같은 카드군)를 합친 관련 카드 목록."""
        card = self._cards.get(card_id)
        if card is None:
            return []
        related: dict[int, Card] = {}
        for other in self.references_of(card_id) + self.referenced_by(card_id):
            related[other.id] = other
        if card.script:
            for series in card.script.listed_series:
                for other in self.by_series(series):
                    if other.id != card_id:
                        related[other.id] = other
        return self.deduplicate(related.values())

    # --- 통계 ---
    def stats(self) -> dict[str, int]:
        cards = self.all_cards()
        return {
            "total": len(self._cards),
            "canonical": len(cards),
            "alternate_art": len(self._cards) - len(cards),
            "with_script": sum(1 for c in self._cards.values() if c.script),
            "with_official_data": sum(
                1 for c in self._cards.values() if CardSource.OFFICIAL_DB in c.sources
            ),
            "monsters": sum(1 for c in cards if c.is_monster),
            "spells": sum(1 for c in cards if c.is_spell),
            "traps": sum(1 for c in cards if c.is_trap),
        }
