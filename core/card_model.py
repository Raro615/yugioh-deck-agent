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
    """
    ``SetType()`` 에서 추출한 ``EFFECT_TYPE_*`` 목록.

    15개 상수는 ``constant.lua`` 에서 **독립 비트**(``0x1`` ~ ``0x4000``)이고
    ``SetType`` 은 그것을 ``+`` 로 묶어 받는다. 그래서 이 값은 **하나의 분류가
    아니라 플래그 집합**이다. 최소 두 축이 섞여 있다 (교체 규칙 기준 전수 측정):

    ======================  =============================================
    적용 범위 축              ``SINGLE`` 14,731 · ``FIELD`` 8,881 ·
                            ``EQUIP`` 639 — 서로 **0회** 공존
    발동 분류 축              ``TRIGGER_O`` 6,087 · ``ACTIVATE`` 4,297 ·
                            ``IGNITION`` 4,137 · ``CONTINUOUS`` 2,456 ·
                            ``TRIGGER_F`` 1,972 · ``QUICK_O`` 1,875 ·
                            ``FLIP`` 189 · ``QUICK_F`` 16
    ======================  =============================================

    ``TARGET`` · ``ACTIONS`` 는 corpus 에 **0블록**이다.

    같은 블록에 ``SetType`` 이 여러 번 걸리면 **더한다.** 단, ``Clone`` 이
    물려준 목록은 그 블록의 **첫 ``SetType`` 이 덮어쓴다** —
    ``sources.lua_loader.parse_lua_source`` 참고.

    .. note::
       🔴 **Phase 3-F-26 이 찾고 3-F-27 이 고친 결함.** 3-F-26 시점에는
       ``Clone`` 이 물려준 목록 위에 자식의 ``SetType`` 이 **더해져서**, 자식이
       분명히 다시 적은 type 위에 부모의 type 이 남았다.

       실제 카드로: ``c324483`` 은 ``e1:SetType(EFFECT_TYPE_IGNITION)`` →
       ``local e2=e1:Clone()`` → ``e2:SetType(EFFECT_TYPE_QUICK_O)`` 인데
       ``e2.effect_types`` 가 ``['IGNITION', 'QUICK_O']`` 였다. 지금은
       ``['QUICK_O']`` 다.

       규모는 **77블록 / 74스크립트**(전체 34,680블록의 0.22%)였고 그중
       **46건이 ``QUICK_O`` 관련**이었다 — ``IGNITION+QUICK_O`` 41 ·
       ``ACTIVATE+QUICK_O`` 5 는 **전부** 이 누적의 산물이었고 지금은 0 이다.
       77건 가운데 **76건이 상호배타 조합**을 만들고 있었다 (적용 범위 25 ·
       발동 분류 51). 그 조합은 한 ``SetType`` 호출 안에서는 **31,933건 중
       0건**이다.

       :attr:`code` 는 같은 위험을 Phase 3-E-18 이 먼저 고쳤다 (그 설명 참고).
       이 칸은 3-F-27 이 고쳤다.

    .. warning::
       🔴 **같은 유형이 형제 칸에 남아 있다** (3-F-27 이 측정하고 범위 밖이라
       고치지 않았다). ``Clone`` 뒤에 자기 설정자를 부르면서 부모 값을 다시
       적지 않은 블록: :attr:`categories` 24 · :attr:`properties` 19 ·
       :attr:`target_ranges` 9 · :attr:`ranges` 12.

       그리고 ``local`` 없이 ``e1=Effect.CreateEffect(c)`` 로 대입하는 자리가
       **217곳 / 195파일** 있고, 파서가 그것을 새 블록으로 보지 않아 **그 뒤
       설정자가 이전 바인딩으로 흘러든다** (``c9839115`` ``e1`` 의 :attr:`code`
       가 그래서 ``EFFECT_UPDATE_ATTACK`` 이다). 이것은 ``Clone`` 과 **다른
       원인**이고 3-F-27 의 수정 범위가 아니다.
    """

    code: str | None = None
    """
    SetCode() 인자. EVENT_* 또는 EFFECT_* 상수 이름.

    ``None`` 은 **두 가지를 뜻한다** (Phase 3-E-17 이 발견하고 3-E-18 이 셌다).

    1. ``SetCode`` 호출이 아예 없었다 — 물어볼 것이 없다 (블록 4,436개)
    2. 호출은 있었는데 인자가 ``EVENT_*`` 도 ``EFFECT_*`` 도 아니어서
       **읽지 못했다** (``SetCode(id)`` · ``SetCode(1082946)`` 등 — 블록 118개 ·
       스크립트 112개)

    둘이 같은 값이 되므로 ``code is None`` 을 "유발 조건이 없다" 로 읽으면
    **118개 블록이 조용히 틀린다.**

    .. warning::
       🔴 **Phase 3-F-25 정정.** 여기에는 *"'없다' 를 말하는 값은 ``None`` 이
       아니라 ``"EVENT_FREE_CHAIN"`` 이다"* 라고 적혀 있었다. **그 문장은
       너무 넓었다.** "없다" 를 적는 방법은 **블록의 종류에 따라 둘**이고,
       어느 쪽인지는 함께 쓰인 ``effect_types`` 가 정한다 (스크립트 단위
       전수 측정):

       ====================  =======  ==========  ===============
       ``effect_types``      블록      FREE_CHAIN  ``code is None``
       ====================  =======  ==========  ===============
       ``ACTIVATE``            4,305   3,642 (85%)        **0**
       ``QUICK_O``             1,875   1,257 (67%)        **0**
       ``IGNITION``            4,180      58 ( 1%)   4,119 (98.5%)
       ``TRIGGER_O``           6,088     **0**             63
       ``TRIGGER_F``           1,972     **0**              8
       ====================  =======  ==========  ===============

       - ``ACTIVATE`` · ``QUICK_O`` 블록은 ``SetCode`` 를 **반드시** 부른다
         (``None`` 이 0건). 그 자리에서 "특정 사건을 요구하지 않는다" 를
         적는 값이 ``EVENT_FREE_CHAIN`` 이다.
       - ``IGNITION`` 블록은 거꾸로 **98.5%가 아예 부르지 않는다.** 같은
         "없다" 를 **생략**으로 적는다. 그래서 ``EVENT_FREE_CHAIN`` 은
         "없다" 의 **유일한 표기가 아니다.**

    공식 규칙과 같다고 읽지 않는다
    ------------------------------
    .. warning::
       🔴 ``EVENT_FREE_CHAIN`` 은 **Lua 내부 태그**이고, 공식 규칙의 개념과
       1:1 로 대응하지 않는다 (Phase 3-F-25 측정).

       - 이 저장소의 공식 자료 — 룰북 원문 · 구조화본
         (``data/rules/``) · 공식 재정 686파일(``data/rulings/``) · 한국어
         공식 DB — 전체에서 "Free Chain" 은 **0회** 나온다.
       - 공식 스펠 스피드와 **1:1 이 아니고, 끝에서 뒤집힌다.**
         ``EFFECT_TYPE_ACTIVATE`` 블록만 보면 필드 마법(공식 스펠 스피드 1,
         어떤 효과에도 대응 **불가**)은 312/312 = **100%** 가
         ``EVENT_FREE_CHAIN`` 인데, 카운터 함정(공식 스펠 스피드 3, 모든
         것에 대응 **가능**)은 210블록 중 **3건(1.4%)** 뿐이다 — 나머지는
         ``EVENT_CHAINING`` 144 등 실제 사건을 적는다. 70배 차이가
         **공식 속도와 반대 방향**으로 난다.
       - ``engine`` 은 이 값을 **읽지 않는다**. 스펠 스피드는
         ``engine/activation_timing.py`` 가 **카드 종류**에서 뽑는다.

    (3-E-17 이 적은 "162장" 은 측정 방법이 틀린 숫자였다 — 3-E-18 이
    ``parse_lua_source`` 결과로 다시 셌다. 또한 ``Clone`` 이 물려준 값이
    읽지 못한 ``SetCode`` 뒤에 **남아 있던** 블록 3개를 3-E-18 이 고쳤다.)
    """

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
    """
    스크립트 전체에서 등장한 EVENT_* 상수.

    **유발 목록이 아니다** (Phase 3-E-17). 이름이 그렇게 읽히지만 실제로는
    파일 하나를 정규식으로 긁은 것이고, 두 가지가 섞여 있다.

    - 어느 효과에 붙었는지 모른다 — 그것은 :attr:`EffectSpec.code` 만 안다
    - ``EVENT_FREE_CHAIN`` 도 들어간다. 그것은 **유발 이벤트가 아니라
      "특정 유발 사건을 요구하지 않는다"** 를 적은 값이다. ``TRIGGER_O`` ·
      ``TRIGGER_F`` 와는 한 번도 같이 쓰이지 않는다 (4,914블록 전수 —
      Phase 3-F-25 가 재확인). 🔴 다만 **함께 쓰이는 종류의 열거가
      3-F-25 전까지 불완전했다**: ``ACTIVATE`` 3,642 · ``QUICK_O`` 1,257 ·
      ``IGNITION`` 58 **그리고** ``FIELD`` 3 · ``CONTINUOUS`` 1 이다
      (뒤의 넷은 ``s.activate`` 안에서 런타임 등록되는 블록 — 유언장
      ``85602018`` 등). 그리고 이 값이 "없다" 의 **유일한 표기가 아니다**
      — :attr:`EffectSpec.code` 설명 참고.

    그래서 이 목록의 길이나 내용으로 "이 카드가 유발 효과를 갖는가" 를 말할 수
    없다.
    """
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
    """표시용 카드 텍스트. 한국어 데이터가 적용되면 한국어, 아니면 공식 DB 원문."""
    desc_en: str = ""
    """공식 DB 의 원문 카드 텍스트. 한국어로 덮어써도 여기에 남는다."""
    strings: list[str] = field(default_factory=list)
    """cdb texts.str1~str16 (효과 선택지 문구 등)"""

    # --- Lua 스크립트 의미 정보 ---
    script: LuaScriptInfo | None = None

    # --- 출처 ---
    sources: set[CardSource] = field(default_factory=set)
    provenance: object | None = None
    """필드별 출처와 상태 (:class:`~core.provenance.CardProvenance`).
    데이터가 덜 모인 카드도 검색에서 빠지지 않으며, 무엇이 없는지만 여기 남는다."""

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

    @property
    def has_printed_effect(self) -> bool:
        """
        공식 카드 종류상 **효과를 가진 카드**인가.

        통상 몬스터와 토큰은 아니다 (통상 펜듈럼 몬스터는 펜듈럼 효과가 있으므로
        예외). 마법·함정은 언제나 효과가 있다.

        ``Lua 가 없다`` 와 ``효과가 없다`` 를 가르는 기준이다. 둘을 섞으면
        듀얼 엔진이 통상 몬스터를 "분석 못 한 카드"로 오해한다.
        """
        if self.type_mask & C.TYPE_TOKEN:
            return False
        if not self.is_monster:
            return True
        if self.type_mask & C.TYPE_NORMAL:
            return bool(self.type_mask & C.TYPE_PENDULUM)
        return True

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
