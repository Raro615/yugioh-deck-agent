"""
통합 카드 데이터 모델.

공식 카드 데이터베이스(``cards.cdb``)의 수치 메타데이터와
Lua 스크립트에서 추출한 효과 의미 정보를 하나의 :class:`Card` 로 합친다.

두 데이터 소스의 역할 분담:

- 공식 DB : 카드명, 카드 텍스트, 레벨/랭크/링크, 속성, 종족, 공/수, 카드 종류
- Lua     : 효과의 기계적 의미 (발동 위치, 트리거 이벤트, 효과 분류, 소환 절차)

Lua 스크립트에는 레벨/속성/종족/공수/카드 텍스트가 들어 있지 않으므로,
수치 기반 필터는 반드시 공식 DB 쪽 데이터를 필요로 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core import constants as C


class CardSource(str, Enum):
    """카드 레코드가 어느 소스에서 왔는지 표시한다."""

    OFFICIAL_DB = "official_db"
    LUA_SCRIPT = "lua_script"
    KOREAN_OVERLAY = "korean_overlay"


@dataclass(slots=True)
class EffectSpec:
    """
    Lua 스크립트의 단일 효과 블록(``local e1=Effect.CreateEffect(c)`` ...)에서
    추출한 기계적 명세.

    필드는 Lua 원문 상수 이름을 접두사 없이 보관한다.
    예) ``EFFECT_TYPE_TRIGGER_O`` -> ``effect_types=['TRIGGER_O']``
        ``SetRange(LOCATION_HAND)`` -> ``ranges=['HAND']``
        ``SetCategory(CATEGORY_TOHAND)`` -> ``categories=['TOHAND']``
    """

    index: str = ""
    """Lua 변수명 (e1, e2, ...)"""

    effect_types: list[str] = field(default_factory=list)
    """SetType() 에서 추출한 EFFECT_TYPE_* 목록"""

    code: str | None = None
    """SetCode() 인자. EVENT_* 또는 EFFECT_* 상수 이름"""

    ranges: list[str] = field(default_factory=list)
    """SetRange() 의 LOCATION_* 목록 — '이 효과를 어디서 발동/적용할 수 있는가'"""

    target_ranges: list[str] = field(default_factory=list)
    """SetTargetRange() 의 LOCATION_* 목록"""

    categories: list[str] = field(default_factory=list)
    """SetCategory() 의 CATEGORY_* 목록 — '이 효과가 무엇을 하는가'"""

    properties: list[str] = field(default_factory=list)
    """SetProperty() 의 EFFECT_FLAG_* 목록"""

    count_limit: str | None = None
    """SetCountLimit() 원문 인자"""

    cloned_from: str | None = None
    """``e4=e3:Clone()`` 인 경우 원본 변수명"""

    def has_category(self, category: str) -> bool:
        return category.upper() in self.categories

    def usable_from(self, location: str) -> bool:
        """해당 위치에서 발동/적용 가능한 효과인지."""
        return location.upper() in self.ranges


@dataclass(slots=True)
class LuaScriptInfo:
    """Lua 스크립트 파일에서 추출한 정보 전체."""

    card_id: int
    file_name: str
    name_ja: str | None = None
    name_en: str | None = None
    scripted_by: str | None = None
    effects: list[EffectSpec] = field(default_factory=list)
    listed_names: list[int] = field(default_factory=list)
    """s.listed_names — 카드 텍스트가 명시적으로 참조하는 카드 ID"""
    listed_name_constants: list[str] = field(default_factory=list)
    """s.listed_names 에 명명 상수(CARD_*)로 적힌 참조. 리포지토리가 ID 로 해석한다."""
    listed_series: list[str] = field(default_factory=list)
    """s.listed_series — 참조하는 카드군(SET_*)"""
    functions: list[str] = field(default_factory=list)
    trigger_events: list[str] = field(default_factory=list)
    """스크립트 전체에서 등장한 EVENT_* 상수"""
    locations: list[str] = field(default_factory=list)
    """스크립트 전체에서 등장한 LOCATION_* 상수"""
    categories: list[str] = field(default_factory=list)
    """스크립트 전체에서 등장한 CATEGORY_* 상수"""
    effect_codes: list[str] = field(default_factory=list)
    """스크립트 전체에서 등장한 EFFECT_* 상수 (EFFECT_TYPE_/EFFECT_FLAG_ 제외)"""


@dataclass(slots=True)
class Card:
    """검색과 필터가 사용하는 정규화된 카드 레코드."""

    # --- 식별 ---
    id: int
    name: str = ""
    """표시용 카드명. 한국어 데이터가 적용되면 한국어, 아니면 공식 DB 원문."""
    name_en: str | None = None
    name_ja: str | None = None
    name_ko: str | None = None

    # --- 공식 DB 수치 메타데이터 ---
    type_mask: int = 0
    attribute_mask: int = 0
    race_mask: int = 0
    level: int = 0
    """레벨/랭크/링크 값. 종류에 따라 해석이 달라진다."""
    atk: int = C.STAT_NONE
    defense: int = C.STAT_NONE
    pendulum_scale_left: int | None = None
    pendulum_scale_right: int | None = None
    link_marker_mask: int = 0
    setcodes: list[int] = field(default_factory=list)
    category_mask: int = 0
    """공식 DB 의 category 컬럼 (CATEGORY_* 비트마스크)"""
    alias: int = 0
    """0 이 아니면 이 카드는 alias 대상 카드의 다른 일러스트/에라타판이다."""
    ot: int = 0
    desc: str = ""
    """공식 카드 텍스트. 임의 번역하지 않고 원문을 보존한다."""
    strings: list[str] = field(default_factory=list)
    """cdb texts.str1~str16 (효과 선택지 문구 등)"""

    # --- Lua 스크립트 의미 정보 ---
    script: LuaScriptInfo | None = None

    # --- 출처 ---
    sources: set[CardSource] = field(default_factory=set)

    # ------------------------------------------------------------------
    # 카드 종류 판별
    # ------------------------------------------------------------------
    @property
    def is_monster(self) -> bool:
        return bool(self.type_mask & C.TYPE_MONSTER)

    @property
    def is_spell(self) -> bool:
        return bool(self.type_mask & C.TYPE_SPELL)

    @property
    def is_trap(self) -> bool:
        return bool(self.type_mask & C.TYPE_TRAP)

    @property
    def is_xyz(self) -> bool:
        return bool(self.type_mask & C.TYPE_XYZ)

    @property
    def is_link(self) -> bool:
        return bool(self.type_mask & C.TYPE_LINK)

    @property
    def is_pendulum(self) -> bool:
        return bool(self.type_mask & C.TYPE_PENDULUM)

    @property
    def is_extra_deck(self) -> bool:
        return bool(
            self.type_mask
            & (C.TYPE_FUSION | C.TYPE_SYNCHRO | C.TYPE_XYZ | C.TYPE_LINK)
        )

    @property
    def is_alternate_art(self) -> bool:
        """다른 일러스트/에라타 판본인지 (중복 제거 대상)."""
        return self.alias != 0

    # ------------------------------------------------------------------
    # 레벨 / 랭크 / 링크
    # ------------------------------------------------------------------
    @property
    def rank(self) -> int | None:
        """엑시즈 몬스터의 랭크."""
        return self.level if self.is_xyz else None

    @property
    def link_rating(self) -> int | None:
        """링크 몬스터의 링크 마커 수."""
        return self.level if self.is_link else None

    @property
    def monster_level(self) -> int | None:
        """일반적인 '레벨'. 엑시즈/링크는 레벨이 없으므로 None."""
        if not self.is_monster or self.is_xyz or self.is_link:
            return None
        return self.level

    @property
    def link_markers(self) -> list[str]:
        return [
            ko
            for bit, ko in C.LINK_MARKER_KO.items()
            if self.link_marker_mask & bit
        ]

    # ------------------------------------------------------------------
    # 이름 표기
    # ------------------------------------------------------------------
    @property
    def type_names(self) -> list[str]:
        return C.decode_bitmask(self.type_mask, C.TYPE_NAMES)

    @property
    def race_name(self) -> str | None:
        names = C.decode_bitmask(self.race_mask, C.RACE_NAMES)
        return names[0] if names else None

    @property
    def attribute_name(self) -> str | None:
        names = C.decode_bitmask(self.attribute_mask, C.ATTRIBUTE_NAMES)
        return names[0] if names else None

    @property
    def race_ko(self) -> str | None:
        for bit, ko in C.RACE_KO.items():
            if self.race_mask & bit:
                return f"{ko}족"
        return None

    @property
    def attribute_ko(self) -> str | None:
        for bit, ko in C.ATTRIBUTE_KO.items():
            if self.attribute_mask & bit:
                return f"{ko}속성"
        return None

    @property
    def type_ko(self) -> str:
        """카드 종류를 한국어 게임 용어로 표기한다."""
        parts = [ko for bit, ko in C.TYPE_KO.items() if self.type_mask & bit]
        return "/".join(parts) if parts else "?"

    # ------------------------------------------------------------------
    # 효과 의미 질의 (Lua 기반)
    # ------------------------------------------------------------------
    @property
    def effects(self) -> list[EffectSpec]:
        return self.script.effects if self.script else []

    def has_effect_category(self, category: str) -> bool:
        """공식 DB category 비트마스크 또는 Lua CATEGORY_* 중 하나라도 일치."""
        category = category.upper()
        if any(e.has_category(category) for e in self.effects):
            return True
        if self.script and category in self.script.categories:
            return True
        return False

    def has_effect_from(self, location: str, category: str | None = None) -> bool:
        """
        지정한 위치에서 발동/적용 가능한 효과가 있는지.
        ``category`` 를 주면 그 효과가 해당 분류인지까지 확인한다.

        예) ``card.has_effect_from('HAND', 'SPECIAL_SUMMON')``
            -> 패에서 특수 소환을 실행하는 효과를 가진 카드
        """
        location = location.upper()
        for eff in self.effects:
            if not eff.usable_from(location):
                continue
            if category is None or eff.has_category(category.upper()):
                return True
        return False

    def has_effect_code(self, code: str) -> bool:
        """스크립트에 특정 EFFECT_*/EVENT_* 코드가 등장하는지."""
        if not self.script:
            return False
        code = code.upper()
        return (
            code in self.script.effect_codes
            or code in self.script.trigger_events
            or any(e.code == code for e in self.effects)
        )

    @property
    def can_self_special_summon_from_hand(self) -> bool:
        """
        패에서 스스로 특수 소환할 수 있는 카드인지.

        EDOPro 에서 자체 특수 소환 절차는 ``EFFECT_SPSUMMON_PROC`` 효과를
        ``LOCATION_HAND`` 범위로 등록해 구현한다.
        """
        for eff in self.effects:
            if eff.code == "EFFECT_SPSUMMON_PROC" and eff.usable_from("HAND"):
                return True
        return False

    # ------------------------------------------------------------------
    def display_name(self) -> str:
        """표시용 이름. 한국어 > 공식 DB 원문 > 일본어 순."""
        return self.name_ko or self.name or self.name_ja or f"#{self.id}"

    def summary_ko(self) -> str:
        """한 줄 요약 (한국어 게임 용어 기준)."""
        bits: list[str] = [self.display_name()]
        if self.is_monster:
            if self.is_link:
                bits.append(f"링크{self.level}")
            elif self.is_xyz:
                bits.append(f"랭크{self.level}")
            else:
                bits.append(f"레벨{self.level}")
            if self.attribute_ko:
                bits.append(self.attribute_ko)
            if self.race_ko:
                bits.append(self.race_ko)
            atk = "?" if self.atk == C.STAT_UNKNOWN else self.atk
            if self.is_link:
                bits.append(f"{atk}")
            else:
                dfs = "?" if self.defense == C.STAT_UNKNOWN else self.defense
                bits.append(f"{atk}/{dfs}")
        bits.append(self.type_ko)
        return " · ".join(str(b) for b in bits)
