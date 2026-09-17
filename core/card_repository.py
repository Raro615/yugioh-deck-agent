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

        return cls(cards, constants=constants)

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
            if card.is_monster:
                self._by_level[card.level].append(card.id)
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
        return [self._cards[i] for i in self._by_level.get(level, [])]

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
