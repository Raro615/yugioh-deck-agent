"""
링크 소환의 **판정** — 이 소재로 이 링크 몬스터를 소환할 수 있는가.

    PlayerAction(LINK_SUMMON, source=링크 몬스터, materials=(…))
        ↓  assess_link_materials(view, actor, source, materials)   ← 이 파일
    LinkMaterialAssessment         적법 / 불법 / 판정할 수 없음
        ↓  ActionValidator          (_LinkMaterialsLegal 이 그대로 읽는다)
        ↓  Duel._link_summon_actions (같은 함수로 후보를 만든다)
    LegalActions

왜 :mod:`engine.link_summon` 과 **다른 파일**인가
--------------------------------------------------
:mod:`engine.summon_rules` 가 일반 소환에서 한 것과 **같은 가름**이다 —
판정은 관측만 읽고, 절차는 판을 바꾼다. 그리고 그 가름은 취향이 아니라
**import 고리**가 요구한다.

    engine.action_validation  (판정이 필요하다)
        ↓
    engine.link_summon        (절차) → engine.summon → engine.effect.delta
        ↓                                                    ↓
    engine.effect.__init__ → engine.effect.executor → engine.special_summon
        ↓
    engine.summon  🔴 부분 초기화된 모듈

실측으로 밟았다 (``tests/engine/test_action_validation.py`` 단독 실행)::

    ImportError: cannot import name 'SPECIAL_SUMMON_PROCEDURE' from
    partially initialized module 'engine.special_summon'

그래서 **판정은 효과 계층을 아예 모른다.** 이 파일의 import 는
``engine.archetype`` · ``engine.ids`` · ``engine.vocabulary`` 뿐이고,
``SummonProcedure`` 도 ``StateDelta`` 도 여기 없다.

공식 규칙이 **세 조건을 따로** 적는다
--------------------------------------
``rules`` 계층의 ``sd-rulebook-en-v10`` 가 그대로 적는다 (RULE-MONSTER-005,
printed page 15) — *"Remember that when you Link Summon, you need to meet
3 goals"*:

1. *"The amount of materials you use matches the Link Rating (Link Monsters
   count as 1 OR their own Link Rating)."*  → :attr:`LinkMaterialRule.link_rating`
2. *"The number of materials you use meets the number specified in the
   materials line or 'recipe'."*  → :attr:`LinkMaterialRule.count`
3. *"The materials match any other requirements in the materials line (such
   as only Effect Monsters, or only a specific Type of monster)."*
   → :attr:`LinkMaterialRule.each` · :attr:`LinkMaterialRule.includes`

🔴 **1 과 2 는 다른 수를 센다.** 1 은 **기여의 합**이고 2 는 **고른 카드
장수**다. 같은 룰북이 예까지 적는다 (RULE-SUMMON-002, printed page 14) —
*"if you want to Summon a Link 3 monster that requires 2 or more materials
in its 'recipe', you can either use 3 monsters (each counts as 1 material)
or else a Link 2 Link Monster (counts as 1 or 2 materials) and a second
monster (counts as 1 material)."* 거기서 고른 카드는 **2장**이고 기여의
합은 **3**이다.

🔴 **Phase 6-AG 가 이 혼용을 고쳤다.** 6-AF 는 기여의 합을
:attr:`LinkMaterialRule.count` 와 **직접 비교**했고, 그래서 두 가지가
동시에 틀렸다 — 기르수(기여 1) + 갈라테아(LINK-2) 로 다른 갈라테아를
소환하려 하면 "소재가 3장" 이라며 거절했고 (각 1로 셀 수 있으므로 합법
이다), 갈라테아 **한 장**이 다른 갈라테아의 「효과 몬스터 2장」 을
만족한다고 판정했다 (고른 카드가 1장이므로 2 를 어긴다). 실측은 보고서
``docs/orcust-girsu-token-line.md`` 의 후속 보완 절에 있다.

무엇을 지원하는가 · 무엇을 지원하지 않는가
------------------------------------------
:func:`assess_link_materials` 의 설명과 아래 "지원하지 않는 것들의 이름"
절이 그 범위를 적는다. 요점 하나만 여기 적어 둔다 — **장수와 링크 수치만
맞으면 통과시키지 않는다.** 통과하는 것은 :data:`LINK_MATERIAL_RULES` 에
손으로 적힌 링크 몬스터뿐이다 (ADR-006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.archetype import matches_setcode
from engine.ids import InstanceId
from engine.summon_restriction import (
    SUMMON_PROHIBITION_RULE_MISSING,
    SUMMON_RESTRICTION_BLIND_SPOTS,
    ProhibitionScope,
    assess_special_summon_permission,
)
from engine.vocabulary import Position, Zone


# ======================================================================
# 절차의 값들
# ======================================================================

#: 출발 자리. 링크 몬스터는 엑스트라 덱에서만 나온다 (공식 규칙).
#:
#: 묘지 · 제외에서 되살아나는 링크 몬스터도 있지만 그것은 **특수 소환**이고
#: 링크 소환이 아니다 (「링크 소환한 이 카드가」 와 가르는 바로 그 구분이다).
LINK_SUMMON_FROM_ZONES: frozenset[Zone] = frozenset({Zone.EXTRA})

#: 놓이는 자리. 모델상 자리당 한 칸이다 (``engine.vocabulary.ZONE_CAPACITY``).
LINK_SUMMON_TO_ZONE: Zone = Zone.EMZONE

#: 놓이는 표시 형식. 링크 몬스터는 **수비 표시가 없다** (공식 규칙) — 그래서
#: 이 값은 다른 절차들과 달리 "고르는 계층이 없어서" 고정한 것이 아니라
#: **규칙이 하나로 정한** 것이다.
LINK_SUMMON_POSITION: Position = Position.FACEUP_ATTACK

#: 소재가 있을 수 있는 자리 — 자신 **필드의** 몬스터다.
LINK_MATERIAL_ZONES: frozenset[Zone] = frozenset({Zone.MZONE, Zone.EMZONE})

#: 소재가 가는 자리. 공식 절차 — 링크 소재는 묘지로 보내진다.
LINK_MATERIAL_DESTINATION: Zone = Zone.GRAVE

# ======================================================================
# 지원하지 않는 것들의 **이름**
# ======================================================================

#: 링크 몬스터를 소재로 쓰면 **1 또는** 그 링크 수치로 센다 (공식 규칙 —
#: RULE-SUMMON-002: *"you can count it as either 1 monster, or as a number
#: of monsters equal to its Link Rating"*).
#:
#: 🔴 **Phase 6-AF 가 이것을 옮겼고 6-AG 가 "또는" 을 고쳤다.** 6-AD 까지
#: 이 이름은 "아직 못 옮겼다" 는 뜻이었고 링크 몬스터가 소재로 들어오면
#: 판정이 ``UNDETERMINED`` 였다. 6-AF 는 **링크 수치로만** 셌고 (고르는
#: 쪽이 1 을 택할 수 있다는 것을 빠뜨렸다), 지금은
#: :func:`material_contribution_options` 가 **고를 수 있는 값들**을 돌려주고
#: :func:`reachable_material_counts` 가 그 조합을 센다.
#:
#: 이름을 **지우지 않는 이유**: 기여를 세게 되었어도
#: :data:`LINK_MATERIAL_RULES` 의 머리말이 적는 한계는 그대로다 — 소재
#: **장수가 범위**인 링크 몬스터 (``Link.AddProcedure`` 의 ``max`` 가
#: ``nil`` 이 아닌 카드) 는 여전히 등록할 수 없다. 이 이름이 그 사실을
#: 들고 있다.
LINK_MATERIAL_AS_LINK_RULE: str = (
    "link-material-link-rating (링크 몬스터를 소재로 쓰면 1 또는 링크 "
    "수치로 센다)"
)

#: 링크 몬스터의 **링크 수치를 읽을 수 없다.**
LINK_RATING_UNREADABLE_RULE: str = (
    "link-material-link-rating-unreadable (소재로 쓴 링크 몬스터의 링크 "
    "수치를 카드 데이터에서 읽을 수 없다)"
)

#: 엑스트라 몬스터 존이 찼을 때, 링크 몬스터가 **가리키는** 메인 몬스터 존.
LINK_PLACEMENT_LINKED_RULE: str = (
    "link-placement-linked-zone (링크 몬스터가 가리키는 메인 몬스터 존)"
)

#: 「이 카드는 링크 소재로 할 수 없다」 류의 제약.
LINK_MATERIAL_BAN_RULE: str = (
    "link-material-restriction (「링크 소재로 할 수 없다」 — 지속 효과 계층)"
)

#: 소재 조건이 :data:`LINK_MATERIAL_RULES` 에 적히지 않았다.
LINK_MATERIAL_RULE_MISSING: str = (
    "link-material-requirement (이 링크 몬스터의 소재 조건을 아직 읽지 않았다)"
)

#: 🔴 **언제나 못 보는 것.** 판정을 바꾸지 않는다 (모듈 머리말).
#:
#: 🔴 **특수 소환 금지는 여기 없다** (Phase 6-AD). 6-AC 까지 이 목록이
#: 그 범위를 덮고 있었고, 그래서 금지가 걸린 판에서도 링크 소환이
#: 수락되었다 — 못 본 것으로 적어 두고 **실행은 허가하는** 모양이었다.
#: 지금은 :func:`~engine.summon_restriction.assess_special_summon_permission`
#: 이 실제로 판정하고, 그 함수가 못 보는 범위만 아래에 더해진다.
LINK_BLIND_SPOTS: tuple[str, ...] = (
    f"{LINK_MATERIAL_BAN_RULE} 를 확인하지 않았습니다 — 그 제약을 적는 "
    "자리가 판에 없습니다.",
) + SUMMON_RESTRICTION_BLIND_SPOTS


# ======================================================================
# 소재 조건 — **손으로 적은** 지식
# ======================================================================


@dataclass(frozen=True, slots=True)
class MaterialRequirement:
    """
    소재 한 장이 만족해야 하는 것. **확인한 것만 적는다.**

    ``Condition`` 을 쓰지 않는 이유가 있다. 효과의 조건은
    ``SetCondition`` 으로 적히고 ``ConditionEvaluator`` 가 판을 보며 평가하는데,
    링크 소재 조건은 공식 스크립트에서 **다른 자리**에 적힌다 —
    ``Link.AddProcedure(c, filter, min, max, matcheck)`` 의 ``filter`` 와
    ``matcheck`` 다. 둘을 같은 어휘로 적으면 "효과의 발동 조건" 과 "소환
    절차의 소재 조건" 이 한 표를 쓰게 되고, 그 표는 둘 중 하나에게 거짓말을
    한다.

    세 값을 돌려준다 — 정의를 못 읽으면 ``None`` 이고 **거짓이 아니다.**
    """

    effect_monster: bool = False
    """``aux.FilterBoolFunctionEx(Card.IsType, TYPE_EFFECT)`` — 효과 몬스터."""
    setcodes: tuple[int, ...] = ()
    """``Card.IsSetCard(...)`` — 이 카드군 중 **하나라도** 맞아야 한다."""

    def holds(self, definition) -> "bool | None":
        """
        그 카드가 이 요구를 만족하는가. 정의를 못 읽으면 ``None``.

        ``None`` 과 ``False`` 를 합치지 않는다 — 「가려진 카드라 모른다」 와
        「조건에 맞지 않는다」 는 다른 사실이고, 앞의 것은 판이 바뀌면
        풀린다.
        """
        if definition is None:
            return None
        if not definition.is_monster:
            return False
        if self.effect_monster and "EFFECT" not in definition.type_names:
            return False
        if self.setcodes and not any(
            matches_setcode(definition.setcodes, code) for code in self.setcodes
        ):
            return False
        return True

    def canonical_state(self) -> tuple:
        return ("material_requirement", self.effect_monster, self.setcodes)

    def describe_ko(self) -> str:
        noun = "효과 몬스터" if self.effect_monster else "몬스터"
        if not self.setcodes:
            return noun
        codes = " / ".join(f"0x{code:x}" for code in self.setcodes)
        return f"카드군 {codes} 의 {noun}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class LinkMaterialRule:
    """
    링크 몬스터 한 장의 소재 조건. **근거를 함께 들고 다닌다.**

    :class:`~engine.effect.library.LibraryEntry` 와 같은 규율이다 — 근거
    없이 적힌 조건은 검증된 규칙이 아니라 추측이다.
    """

    card_id: int
    link_rating: int
    """
    **기여의 합이 정확히 맞춰야 하는 수** — 공식 3 조건의 첫째 (모듈
    머리말 · RULE-MONSTER-005). 카드 데이터의 링크 수치와 같아야 하고,
    등록과 데이터가 어긋나면 실측으로 잡힌다.

    🔴 **:attr:`count` 와 다른 수를 센다.** 이쪽은 ``1`` 또는 소재로 쓴
    링크 몬스터의 링크 수치를 **더한 값**이고, 저쪽은 **고른 카드 장수**다.
    두 수가 같은 카드가 많아서 (갈라테아는 둘 다 2) 한 칸으로 합치고 싶어
    지지만, 합치면 「Link 3 이고 소재 2장」 류가 표현 불가능해지고 무엇보다
    **링크 몬스터를 소재로 쓴 순간 두 수가 갈라진다** (Phase 6-AG 가 고친
    결함이 정확히 그것이다).
    """
    count: int
    """
    **고른 카드가 정확히 몇 장이어야 하는가** — 공식 3 조건의 둘째
    (*"The number of materials you use meets the number specified in the
    materials line or 'recipe'"*). ``Link.AddProcedure`` 의 ``min`` ·
    ``max`` 가 둘 다 이 수인 카드만 등록한다.

    ``2+`` 류는 아직 적을 수 없다 (아래 :data:`LINK_MATERIAL_RULES` 설명).

    🔴 **기여의 합이 아니다.** :attr:`link_rating` 를 보라.
    """
    each: MaterialRequirement
    includes: "MaterialRequirement | None" = None
    """소재 중 **적어도 하나**가 만족해야 하는 것 (``matcheck``)."""
    text_ko: str = ""
    """
    공식 **한국어 카드 텍스트**의 소재 조건 한 줄. 거절 문장에 그대로 쓴다.

    🔴 **판정에 쓰이지 않는다.** 판정은 :attr:`each` · :attr:`includes` ·
    :attr:`count` 가 하고, 이 칸은 사람이 읽는 줄이다 — 카드군을
    ``0x11b`` 로 적으면 ``/combo`` 를 읽는 사람이 무슨 조건인지 알 수 없고,
    엔진은 ``core`` 를 import 하지 않으므로 (ADR-007) 카드군의 이름을
    조회할 수 없다. 그래서 **등록할 때 함께 적는다.**
    """
    lua_file: str = ""
    lua_excerpt: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.card_id}")
        if self.count < 1:
            raise ValueError(f"소재는 최소 한 장입니다: {self.count}")
        if self.link_rating < 1:
            raise ValueError(f"링크 수치는 1 이상입니다: {self.link_rating}")
        #: 🔴 **달성할 수 없는 등록을 막는다** (Phase 6-AG). 소재 한 장의
        #: 최소 기여가 1 이므로 (:func:`material_contribution_options`),
        #: ``count`` 장으로 만들 수 있는 기여의 합은 **최소 ``count``** 다.
        #: ``link_rating`` 이 그보다 작으면 어떤 조합도 첫째 조건을 만족할
        #: 수 없고, 그 등록은 **조용히 아무것도 소환하지 못하는** 줄이 된다.
        if self.link_rating < self.count:
            raise ValueError(
                f"{self.card_id}: 링크 수치 {self.link_rating} 가 소재 "
                f"장수 {self.count} 보다 작습니다 — 소재 한 장은 최소 1 로 "
                "세므로 어떤 조합도 기여의 합을 맞출 수 없습니다."
            )
        if not self.lua_file or not self.lua_excerpt:
            raise ValueError(
                f"{self.card_id}: 소재 조건을 어느 스크립트에서 읽었는지 "
                "적어야 합니다 — 근거 없는 조건은 추측입니다."
            )

    def canonical_state(self) -> tuple:
        return (
            self.card_id,
            self.link_rating,
            self.count,
            self.each.canonical_state(),
            self.includes.canonical_state() if self.includes else None,
        )

    def describe_ko(self) -> str:
        if self.text_ko:
            return self.text_ko
        line = f"{self.each.describe_ko()} {self.count}장"
        if self.includes is not None:
            line += f" (그중 하나는 {self.includes.describe_ko()})"
        return line

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


#: 소재 조건을 **읽은** 링크 몬스터들. 여기 없는 카드는 ``UNKNOWN`` 이다.
#:
#: :data:`~engine.effect.library.EFFECT_LIBRARY` 와 같은 규칙으로 산다 —
#: 손으로 등록하고, 등록되지 않은 것은 모른다 (ADR-006).
#:
#: 🔴 **``2+`` 류를 적을 수 없다.** ``Link.AddProcedure`` 의 ``max`` 가
#: ``nil`` 이 아닌 카드는 소재 장수가 범위이고, 그때는 "어느 장수로 소환할
#: 것인가" 를 고르는 계층이 필요하다 (후보가 조합으로 불어난다). 지금
#: :attr:`LinkMaterialRule.count` 가 **정확한 한 수**인 것은 그 계층이 없다는
#: 사실이고, 범위를 가진 카드는 등록하지 않는다 — 등록하면 그 카드의 다른
#: 장수 조합이 조용히 불법이 된다.
LINK_MATERIAL_RULES: tuple[LinkMaterialRule, ...] = (
    #: 오르페골 갈라테아 — 「효과 몬스터 2장 (「오르페골」 몬스터를 포함)」.
    #:
    #: ``Link.AddProcedure(c, aux.FilterBoolFunctionEx(Card.IsType,
    #: TYPE_EFFECT), 2, nil, s.matcheck)`` 에서 ``filter`` 와 장수를,
    #: ``s.matcheck`` 의 ``g:IsExists(Card.IsSetCard, 1, nil, SET_ORCUST,
    #: lc, sumtype, tp)`` 에서 「포함」 을 옮겼다.
    #:
    #: ``max`` 가 ``nil`` 이므로 **정확히 2장**이다 — 범위가 아니다.
    #:
    #: 🔴 ``matcheck`` 의 ``lc, sumtype, tp`` 인자는 옮기지 못했다. 그것은
    #: 「소환하는 카드 자신의 효과로 카드군이 더해질 수 있는가」 를 묻는
    #: 자리이고 (지속 효과 계층 — STRUCTURAL-76), 이 판정은 **카드 데이터의
    #: 카드군만** 본다. 방향이 안전하다: 효과로 더해진 카드군이 있으면
    #: 합법인 조합이 불법으로 보일 뿐이고 (거짓 음성), 그 반대는 만들 수
    #: 없다.
    LinkMaterialRule(
        card_id=30741503,
        link_rating=2,
        count=2,
        each=MaterialRequirement(effect_monster=True),
        includes=MaterialRequirement(setcodes=(0x11B,)),
        text_ko="효과 몬스터 2장 (「오르페골」 몬스터를 포함)",
        lua_file="c30741503.lua",
        lua_excerpt=(
            "Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsType,"
            "TYPE_EFFECT),2,nil,s.matcheck); "
            "function s.matcheck(g,lc,sumtype,tp) return "
            "g:IsExists(Card.IsSetCard,1,nil,SET_ORCUST,lc,sumtype,tp) end"
        ),
        note=(
            "공식 텍스트: 「효과 몬스터 2장 (「오르페골」 몬스터를 포함)」. "
            "SET_ORCUST = 0x11b (갈라테아 자신의 setcode 와 같은 값이고, "
            "data/cards.cdb 의 30741503 setcode=0x11b 로 대조했다)."
        ),
    ),
    #: 오르페골 갈라테아i — 「「오르페골」 몬스터 또는 「성유물」 몬스터 1장」
    #: (Phase 6-AF).
    #:
    #: ``Link.AddProcedure(c, aux.FilterBoolFunctionEx(Card.IsSetCard,
    #: {SET_ORCUST,SET_WORLD_LEGACY}), 1, 1)`` 에서 **정확히 1장**과 두
    #: 카드군을 옮겼다 (``min`` 과 ``max`` 가 둘 다 1 이므로 범위가 아니다).
    #:
    #: 🔴 **효과 몬스터를 요구하지 않는다.** 필터가 ``Card.IsSetCard`` 하나
    #: 이고 ``Card.IsType(TYPE_EFFECT)`` 가 없다 — 갈라테아와 **다른 조건**
    #: 이고, 그 차이가 성유물 토큰(통상 몬스터)을 이 카드의 소재로는 쓸 수
    #: 있고 갈라테아의 소재로는 쓸 수 없게 만든다.
    #:
    #: ``SET_ORCUST`` = ``0x11b`` · ``SET_WORLD_LEGACY`` = ``0xfe`` (상수
    #: 파일에서 읽었고, 성유물 토큰 46647145 의 setcode 254 = 0xfe 와
    #: 대조했다).
    LinkMaterialRule(
        card_id=48835607,
        link_rating=1,
        count=1,
        each=MaterialRequirement(setcodes=(0x11B, 0xFE)),
        text_ko="「오르페골」 몬스터 또는 「성유물」 몬스터 1장",
        lua_file="c48835607.lua",
        lua_excerpt=(
            "Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsSetCard,"
            "{SET_ORCUST,SET_WORLD_LEGACY}),1,1)"
        ),
        note=(
            "공식 텍스트: 「「오르페골」 몬스터 또는 「성유물」 몬스터 "
            "1장」. 효과 몬스터 조건이 **없다** — 필터에 "
            "Card.IsType(TYPE_EFFECT) 가 들어 있지 않다. "
            "data/cards.cdb 의 48835607 은 setcode=0x11b · 링크 수치 1 이다. "
            "같은 스크립트의 e1 (링크 소환 성공 시 그 턴 이 카드의 링크 "
            "소환을 막는 EFFECT_CANNOT_SPECIAL_SUMMON 등록) 은 "
            "LINK_SUMMON_ONCE_PER_TURN 가 따로 들고 있다."
        ),
    ),
)

@dataclass(frozen=True, slots=True)
class LinkSummonTurnLimit:
    """
    「이 카드를 1턴에 1번만 링크 소환할 수 있다」 류의 제약 (Phase 6-AF).

    공식 스크립트가 이것을 **소재 조건이 아니라 지속 효과**로 적는다 —
    링크 소환에 성공하면 그때 ``EFFECT_CANNOT_SPECIAL_SUMMON`` 을 **플레이어
    에게** 걸고 엔드 페이즈에 지운다. 그래서 :class:`LinkMaterialRule` 과
    **다른 표**에 적는다: 저쪽은 "무엇을 소재로 쓸 수 있는가" 이고 이쪽은
    "몇 번 소환할 수 있는가" 다.

    세는 자리는 :class:`~engine.state.summon_usage.SummonUsageRegistry` 이고
    (판에 있다), 판정하는 자리는 :func:`assess_link_materials` 다 —
    **지식 · 상태 · 판정**이 각자 다른 자리에 있다
    (``EffectDefinition.use_limit`` 과 같은 규율).
    """

    card_id: int
    times: int
    """그 턴에 **몇 번까지** 링크 소환할 수 있는가."""
    scope: ProhibitionScope
    """``SetTargetRange`` 를 옮긴 값 — 누구에게 걸리는가."""
    text_ko: str
    lua_file: str
    lua_excerpt: str
    note: str

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.card_id}")
        if self.times < 1:
            raise ValueError(f"횟수는 1 이상입니다: {self.times}")
        for required in ("text_ko", "lua_file", "lua_excerpt", "note"):
            if not getattr(self, required).strip():
                raise ValueError(
                    f"{self.card_id}: {required} 를 비워 둘 수 없습니다 — "
                    "근거 없는 제약은 추측입니다."
                )

    def canonical_state(self) -> tuple:
        return (self.card_id, self.times, self.scope.value)


#: 턴당 링크 소환 횟수를 **읽은** 링크 몬스터들. 여기 없는 카드는 제약이
#: 적히지 않았다 (ADR-006 — "제약이 없다" 가 아니라 "읽지 않았다").
LINK_SUMMON_ONCE_PER_TURN: tuple[LinkSummonTurnLimit, ...] = (
    LinkSummonTurnLimit(
        card_id=48835607,
        times=1,
        #: ``SetTargetRange(1,0)`` — **그 카드의 컨트롤러에게만** 걸린다.
        scope=ProhibitionScope.CONTROLLER,
        text_ko=(
            "오르페골 갈라테아i: 「"
            "「오르페골 갈라테아i」는 1턴에 1번밖에 링크 소환할 수 없다」"
        ),
        lua_file="c48835607.lua",
        lua_excerpt=(
            "function s.regop(e,tp,...) local e1=Effect.CreateEffect("
            "e:GetHandler()); e1:SetType(EFFECT_TYPE_FIELD); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET); "
            "e1:SetTargetRange(1,0); e1:SetTarget(function(e,c,sump,sumtype) "
            "return c:IsCode(id) and sumtype&SUMMON_TYPE_LINK=="
            "SUMMON_TYPE_LINK end); e1:SetReset(RESET_PHASE|PHASE_END); "
            "Duel.RegisterEffect(e1,tp) end"
        ),
        note=(
            "링크 소환에 성공했을 때 (EVENT_SPSUMMON_SUCCESS + "
            "IsLinkSummoned) 등록되는 지속 효과이고, 대상이 "
            "c:IsCode(id) and sumtype&SUMMON_TYPE_LINK 이므로 **그 카드명의 "
            "링크 소환만** 막는다 (다른 특수 소환은 막지 않는다). "
            "SetReset(RESET_PHASE|PHASE_END) 이 '그 턴' 이고, "
            "SetTargetRange(1,0) 이 '자신' 이다 — 상대의 링크 소환은 "
            "막지 않으므로 scope 가 CONTROLLER 다. "
            "이 저장소는 그것을 '이 턴에 그 카드명을 링크 소환한 횟수' 로 "
            "세고 (GameState.summon_uses), 카드가 필드를 떠난 뒤에도 그 "
            "기록이 남는다 — 공식 효과도 카드가 사라져도 턴 끝까지 "
            "남는다 (Duel.RegisterEffect 는 플레이어에게 건다)."
        ),
    ),
)

_TURN_LIMIT_BY_CARD: dict[int, LinkSummonTurnLimit] = {
    rule.card_id: rule for rule in LINK_SUMMON_ONCE_PER_TURN
}
if len(_TURN_LIMIT_BY_CARD) != len(LINK_SUMMON_ONCE_PER_TURN):  # pragma: no cover
    raise ValueError("한 카드의 턴당 링크 소환 제한을 두 줄로 적었습니다.")


def turn_limit_for(card_id: "int | None") -> "LinkSummonTurnLimit | None":
    """그 링크 몬스터의 턴당 소환 제한. **적히지 않았으면 ``None``.**"""
    if card_id is None:
        return None
    return _TURN_LIMIT_BY_CARD.get(card_id)


_RULES_BY_CARD: dict[int, LinkMaterialRule] = {
    rule.card_id: rule for rule in LINK_MATERIAL_RULES
}
assert len(_RULES_BY_CARD) == len(LINK_MATERIAL_RULES), (
    "같은 카드의 소재 조건이 두 번 적혀 있습니다 — 어느 쪽이 이기는지 말할 "
    "수 없습니다."
)


def material_contribution_options(definition) -> "frozenset[int] | None":
    """
    그 소재가 **몇 으로 세어질 수 있는가** — 고를 수 있는 값들 (Phase 6-AG).

    공식 규칙 (RULE-SUMMON-002) — *"Normally, 1 monster equals 1 Link
    Material. But when you use a Link Monster as material for another Link
    Summon, you can count it as either 1 monster, or as a number of
    monsters equal to its Link Rating."*

    - 링크 몬스터가 아니면 ``{1}`` — 고를 것이 없다.
    - 링크 몬스터면 ``{1, 링크 수치}`` — **고르는 쪽이 정한다.**
      링크 1 이면 두 값이 같으므로 ``{1}`` 하나다.

    🔴 **사이의 값은 없다.** 링크 3 을 소재로 쓰면 1 또는 3 이고 **2 가
    아니다** — 룰북이 "either 1 monster, or ... equal to its Link Rating"
    이라고 적는다. 그래서 돌려주는 것이 범위가 아니라 **집합**이다.

    읽을 수 없으면 ``None`` 이다 — ``{1}`` 도 ``frozenset()`` 도 아니다.
    모르는 수를 ``{1}`` 로 접으면 링크 몬스터가 조용히 1 로만 세어지고,
    빈 집합으로 접으면 "어떤 조합도 없다" 는 **확정 거절**이 된다. 둘 다
    모름을 답으로 바꾼다 (ADR-006).
    """
    if definition is None:
        return None
    if not definition.is_link:
        return frozenset({1})
    rating = definition.link_rating
    if not isinstance(rating, int) or rating < 1:
        return None
    return frozenset({1, rating})


def material_contribution(definition) -> "int | None":
    """
    그 소재가 **최대로** 몇 으로 세어질 수 있는가.

    :func:`material_contribution_options` 의 가장 큰 값이다 — 링크 몬스터면
    자신의 링크 수치, 그 밖이면 1.

    🔴 **판정은 이 함수를 쓰지 않는다** (Phase 6-AG). 판정은 고를 수 있는
    값 **전부**가 필요하고 (``1`` 을 택하는 길이 합법일 수 있다), 그것은
    :func:`material_contribution_options` 가 돌려준다. 이 함수는 **한 장이
    얼마까지 셀 수 있는가**를 묻는 자리에만 쓴다 — 6-AF 가 이 값을 그대로
    판정에 썼고 그래서 "1 로 세는 길" 을 잃었다.

    읽을 수 없으면 ``None`` 이다.
    """
    options = material_contribution_options(definition)
    if options is None:
        return None
    return max(options)


def reachable_material_counts(
    choices: "tuple[frozenset[int], ...]"
) -> frozenset[int]:
    """
    고른 소재들로 만들 수 있는 **기여 합 전부** (Phase 6-AG).

    각 소재가 자기 집합에서 하나를 고르므로, 합의 집합은 선택들의 곱이다.
    소재는 자신 필드의 몬스터이고 (``LINK_MATERIAL_ZONES`` — 최대 6장),
    집합의 크기는 최대 2 이므로 결과는 최대 64가지다.

    🔴 **"도달 가능한가" 를 세는 것이 아니라 "무엇에 도달하는가" 를
    센다.** 거절 문장이 **어디까지 갈 수 있었는지**를 적어야 하고, 참 /
    거짓 하나로는 그것을 적을 수 없다.

    빈 입력은 ``{0}`` 이다 — 아무것도 고르지 않으면 합이 0 이다.
    """
    sums = {0}
    for options in choices:
        sums = {total + share for total in sums for share in options}
    return frozenset(sums)


def material_rule_for(card_id: "int | None") -> "LinkMaterialRule | None":
    """그 링크 몬스터의 소재 조건. **적히지 않았으면 ``None``** 이다."""
    if card_id is None:
        return None
    return _RULES_BY_CARD.get(card_id)


# ======================================================================
# 판정 — 한 곳에서만 한다
# ======================================================================


class LinkMaterialEligibility(str, Enum):
    """
    소재가 적법한가. **셋을 한 불리언으로 합치지 않는다**
    (:class:`~engine.summon_rules.SummonEligibility` 와 같은 모양).
    """

    LEGAL = "legal"
    """확인했고 적법하다."""
    ILLEGAL = "illegal"
    """확인했고 **규칙이 막는다.**"""
    UNDETERMINED = "undetermined"
    """판정할 근거가 없다. **거절이 아니다.**"""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class LinkMaterialAssessment:
    """
    소재 판정 하나와 **그 근거.**

    ``unchecked`` 가 따로 있는 이유는 모듈 머리말에 있다 — 판정을 바꾸지
    않는 관찰과 판정을 막는 모름은 다른 사실이다.
    """

    eligibility: LinkMaterialEligibility
    reason: str
    missing_rule: "str | None" = None
    rule: "LinkMaterialRule | None" = None
    unchecked: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            self.eligibility is not LinkMaterialEligibility.UNDETERMINED
            and self.missing_rule is not None
        ):
            raise ValueError(
                "없는 규칙 이름은 UNDETERMINED 에만 붙습니다: "
                f"{self.eligibility} / {self.missing_rule}"
            )

    @property
    def permits_procedure(self) -> bool:
        return self.eligibility is LinkMaterialEligibility.LEGAL

    @property
    def is_refusal(self) -> bool:
        return self.eligibility is LinkMaterialEligibility.ILLEGAL

    def describe_ko(self) -> str:
        return f"{self.eligibility.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def _legal(rule: LinkMaterialRule) -> LinkMaterialAssessment:
    return LinkMaterialAssessment(
        LinkMaterialEligibility.LEGAL,
        f"{rule.card_id} 의 소재 조건을 만족합니다 ({rule.describe_ko()}).",
        rule=rule,
        unchecked=LINK_BLIND_SPOTS,
    )


def _illegal(reason: str, rule=None) -> LinkMaterialAssessment:
    return LinkMaterialAssessment(
        LinkMaterialEligibility.ILLEGAL, reason, rule=rule
    )


def _undetermined(reason: str, missing: str, rule=None) -> LinkMaterialAssessment:
    return LinkMaterialAssessment(
        LinkMaterialEligibility.UNDETERMINED, reason, missing, rule=rule
    )


def assess_link_materials(
    view, actor: int, source: "InstanceId | None", materials: tuple[InstanceId, ...]
) -> LinkMaterialAssessment:
    """
    이 소재로 그 링크 몬스터를 링크 소환할 수 있는가.

    **관측만 읽는다** — 판을 바꾸지 않고, ``GameState`` 를 받지 않는다.
    검증기와 후보 생성기가 **이 함수 하나**를 부른다.

    순서가 뜻을 가진다. 먼저 ``source`` 가 무엇인지 확인하고 (링크 몬스터인가 ·
    엑스트라 덱에 있는가), 그 다음 소재 조건을 찾고, 마지막에 고른 소재를
    하나하나 본다. 반대로 하면 "소재가 틀렸다" 가 "애초에 링크 몬스터가
    아니다" 를 가린다.

    **공식 3 조건을 셋으로 나눠 본다** (Phase 6-AG · 모듈 머리말):

    1. **고른 카드 장수** (``len(materials) == rule.count``) — 관측을 읽지
       않으므로 가장 먼저 본다.
    2. **카드별 조건** (``rule.each`` · ``rule.includes``) — 그 고리가
       보이지 않는 소재와 못 읽는 정의를 정확한 문장으로 거른다.
    3. **기여의 합** (``rule.link_rating`` 에 닿는 조합이 있는가) — 2 를
       지난 뒤이므로 정의가 전부 읽히고, 남은 모름은 **링크 수치를 못
       읽는 경우 하나**다.

    🔴 **1 과 3 을 한 수로 합치지 않는다.** 6-AF 가 합쳤고 그래서 둘 다
    틀렸다 (모듈 머리말의 실측).

    🔴 **특수 소환 금지를 함께 본다** (Phase 6-AD). 링크 소환은 규칙상
    특수 소환이므로 (공식 룰북) 판에 걸린 특수 소환 금지가 이 행동도
    막는다. 6-AC 까지 이 함수는 그것을 보지 않았고, 그래서 파슬 다이너
    파키세팔로가 필드에 **그대로 남아 있는** 판에서 링크 소환이
    ``accepted=True`` · ``code=OK`` 로 수락되었다 (실측 — 그쪽 모듈 머리말).

    그 판정이 **두 자리로 갈려 들어간다.**

    1. **확인된 금지**는 소재를 보기 전에 막는다 (``ILLEGAL``). 규칙이 답한
       것이 소재 조건의 모름보다 먼저다 (보완8 이 세운 구분).
    2. **판정할 수 없는 금지**는 **마지막에** 본다 (``UNDETERMINED``).
       소재가 확실히 틀린 행동은 판을 못 읽는 것과 무관하게 틀렸으므로,
       모름이 확정 거부를 가리지 않게 한다.
    """
    permission = assess_special_summon_permission(view, actor)
    if source is None:
        return _illegal("소환할 링크 몬스터가 지목되지 않았습니다.")

    card = view.find(source)
    if card is None:
        return _undetermined(
            f"{source} 가 관측에 보이지 않습니다.",
            LINK_MATERIAL_RULE_MISSING,
        )
    definition = card.definition
    if definition is None:
        return _undetermined(
            f"{source} 의 카드 정의를 읽을 수 없어 링크 몬스터인지 알 수 "
            "없습니다.",
            LINK_MATERIAL_RULE_MISSING,
        )
    if not definition.is_link:
        return _illegal(
            f"{source} 는 링크 몬스터가 아닙니다 — 링크 소환할 수 없습니다."
        )
    if card.zone not in LINK_SUMMON_FROM_ZONES:
        allowed = " · ".join(sorted(z.value for z in LINK_SUMMON_FROM_ZONES))
        return _illegal(
            f"{source} 가 {allowed} 에 없습니다 (현재 {card.zone.value}) — "
            "링크 소환은 엑스트라 덱에서 꺼내는 것입니다."
        )
    if card.controller != actor:
        return _illegal(
            f"{source} 는 P{card.controller} 의 카드입니다 "
            f"(P{actor} 가 소환하려 했습니다)."
        )

    #: 🔴 **확인된 특수 소환 금지가 소재보다 먼저다** (Phase 6-AD).
    if permission.forbidden:
        return _illegal(
            f"링크 소환은 특수 소환입니다 — {permission.reason}"
        )

    rule = material_rule_for(definition.card_id)
    if rule is None:
        return _undetermined(
            f"{definition.card_id} 의 소재 조건을 이 저장소가 아직 읽지 "
            "않았습니다. 장수와 링크 수치만 맞춰 통과시키지 않습니다.",
            LINK_MATERIAL_RULE_MISSING,
        )

    #: 🔴 **턴당 링크 소환 제한을 소재보다 먼저 본다** (Phase 6-AF).
    #: 규칙이 답한 것이 소재 조건의 모름보다 먼저다 (확인된 특수 소환 금지와
    #: 같은 자리이고 같은 이유다).
    limit = turn_limit_for(definition.card_id)
    if limit is not None and limit.scope.covers(actor, actor):
        done = view.summons_of(actor, definition.card_id, LINK_SUMMON_KIND)
        if done >= limit.times:
            return _illegal(
                f"P{actor} 는 이 턴에 {definition.card_id} 를 이미 "
                f"{done}번 링크 소환했습니다 (1턴 {limit.times}번) — "
                f"{limit.text_ko}"
            )

    #: 🔴 **같은 카드를 두 번 셀 수 없다** (Phase 6-AG). 소재는 필드를
    #: 떠나므로 한 장이 두 자리를 채울 수 없다.
    #: :class:`~engine.action.PlayerAction` 이 이미 막지만
    #: (``MalformedAction``), 이 함수를 **직접** 부르는 길에는 그 관문이
    #: 없었다 — 그래서 판정 자신이 막는다. 세 계층이 같은 기준을 쓰게
    #: 하는 것이 이 Phase 가 고친 것의 절반이다.
    if len(set(materials)) != len(materials):
        return _illegal(
            "같은 몬스터를 소재로 두 번 고를 수 없습니다 — 소재는 필드를 "
            f"떠납니다: {materials}",
            rule,
        )

    #: 🔴 **공식 3 조건의 둘째 — 고른 카드 장수** (모듈 머리말).
    #: *"The number of materials you use meets the number specified in the
    #: materials line or 'recipe'."* 이 검사는 **관측을 읽지 않는다** —
    #: ``len(materials)`` 하나로 답이 나오므로, 판을 못 읽는 모름이 이
    #: 사실을 가릴 수 없다. 그래서 가장 먼저 둔다.
    #:
    #: 🔴 6-AF 는 이 자리에 **기여의 합**을 놓았다. 그래서 링크 몬스터 한
    #: 장이 「효과 몬스터 2장」 을 만족한다고 판정했다 — 고른 카드가
    #: 1장인데 둘째 조건을 세지 않았기 때문이다.
    if len(materials) != rule.count:
        return _illegal(
            f"소재로 고른 몬스터가 {len(materials)}장입니다 — "
            f"{rule.card_id} 는 {rule.describe_ko()} 입니다 "
            f"(정확히 {rule.count}장).",
            rule,
        )

    #: 자신 필드의 앞면 몬스터인가 · 정의를 읽을 수 있는가.
    for instance in materials:
        held = view.find(instance)
        if held is None:
            return _undetermined(
                f"소재로 고른 {instance} 가 관측에 보이지 않습니다.",
                LINK_MATERIAL_RULE_MISSING,
                rule,
            )
        if held.controller != actor:
            return _illegal(
                f"{instance} 는 P{held.controller} 의 몬스터입니다 — 링크 "
                "소재는 **자신이** 컨트롤하는 몬스터입니다.",
                rule,
            )
        if held.zone not in LINK_MATERIAL_ZONES:
            allowed = " · ".join(sorted(z.value for z in LINK_MATERIAL_ZONES))
            return _illegal(
                f"{instance} 가 {allowed} 에 없습니다 (현재 "
                f"{held.zone.value}) — 링크 소재는 필드의 몬스터입니다.",
                rule,
            )
        if not held.face_up:
            return _illegal(
                f"{instance} 가 뒷면입니다 — 뒷면 몬스터는 링크 소재로 할 "
                "수 없습니다.",
                rule,
            )
        material_definition = held.definition
        if material_definition is None:
            return _undetermined(
                f"{instance} 의 카드 정의를 읽을 수 없어 소재 조건을 볼 수 "
                "없습니다.",
                LINK_MATERIAL_RULE_MISSING,
                rule,
            )
        #: 🔴 **링크 몬스터도 소재가 된다** (Phase 6-AF). 6-AD 까지 이
        #: 자리가 ``UNDETERMINED`` 였고, 그 이유는 "링크 수치로 세는
        #: 규칙을 옮기지 못했다" 였다 — 지금은 **아래에서**
        #: :func:`material_contribution_options` 와
        #: :func:`reachable_material_counts` 가 센다 (이 고리는 카드별
        #: 조건만 본다 — 공식 3 조건의 셋째다).
        holds = rule.each.holds(material_definition)
        if holds is None:
            return _undetermined(
                f"{instance} 가 소재 조건을 만족하는지 읽을 수 없습니다.",
                LINK_MATERIAL_RULE_MISSING,
                rule,
            )
        if not holds:
            return _illegal(
                f"{instance} 는 {rule.each.describe_ko()}가 아닙니다.",
                rule,
            )

    #: 「…를 포함」 — 소재 중 **적어도 하나**.
    if rule.includes is not None:
        answers = [
            rule.includes.holds(
                found.definition if (found := view.find(i)) is not None else None
            )
            for i in materials
        ]
        if not any(answer is True for answer in answers):
            if any(answer is None for answer in answers):
                return _undetermined(
                    f"소재 중에 {rule.includes.describe_ko()}가 있는지 읽을 수 "
                    "없습니다.",
                    LINK_MATERIAL_RULE_MISSING,
                    rule,
                )
            return _illegal(
                f"소재 중에 {rule.includes.describe_ko()}가 없습니다 — "
                f"{rule.card_id} 는 {rule.describe_ko()} 입니다.",
                rule,
            )

    #: 🔴 **공식 3 조건의 첫째 — 기여의 합** (모듈 머리말).
    #: *"The amount of materials you use matches the Link Rating (Link
    #: Monsters count as 1 OR their own Link Rating)."*
    #:
    #: 소재마다 **고를 수 있는 값들**을 모아 (``1`` 또는 그 링크 수치),
    #: 그 조합으로 :attr:`LinkMaterialRule.link_rating` 에 **정확히**
    #: 닿는 길이 있는지 본다. 하나라도 있으면 그 길을 고른 것이 합법이다 —
    #: 고르는 계층이 없어도 **존재**는 판정할 수 있고, 어느 길을 고를지는
    #: 판정이 정할 일이 아니다.
    #:
    #: 🔴 **이 자리가 둘째 조건 뒤에 온다.** 여기서는 정의를 전부 읽은
    #: 뒤이므로 (위 고리가 못 읽는 소재를 이미 걸렀다) ``None`` 은 **링크
    #: 수치를 못 읽는 경우 하나**로 좁혀진다 — 그래서 모름의 이름이
    #: 정확해진다 (:data:`LINK_RATING_UNREADABLE_RULE`).
    choices: list[frozenset[int]] = []
    for instance in materials:
        held = view.find(instance)
        options = material_contribution_options(
            None if held is None else held.definition
        )
        if options is None:
            return _undetermined(
                f"{instance} 의 링크 수치를 읽을 수 없어 기여를 셀 수 "
                "없습니다.",
                LINK_RATING_UNREADABLE_RULE,
                rule,
            )
        choices.append(options)
    reachable = reachable_material_counts(tuple(choices))
    if rule.link_rating not in reachable:
        #: 🔴 **어디까지 갈 수 있었는지 적는다.** "합이 안 맞는다" 만
        #: 적으면 읽는 쪽이 한 장을 바꿔야 하는지 장수를 바꿔야 하는지
        #: 알 수 없다. 장수 조건은 **이미 통과**했으므로 (둘째 조건) 남은
        #: 길은 소재를 바꾸는 것뿐이다.
        able = " · ".join(str(value) for value in sorted(reachable))
        return _illegal(
            f"고른 소재 {len(materials)}장으로 만들 수 있는 기여의 합은 "
            f"{able} 이고 {rule.card_id} 의 링크 수치 {rule.link_rating} "
            "에 닿지 않습니다 — 링크 몬스터는 1 또는 자신의 링크 수치로 "
            "세고 그 사이의 값은 없습니다.",
            rule,
        )

    placement = assess_link_placement(view, actor, materials)
    if placement is not None:
        return placement

    #: 🔴 **마지막 자리** (Phase 6-AD). 소재와 배치가 전부 맞은 뒤에만
    #: "막는지 모른다" 를 돌려준다 — 그 전에 돌려주면 소재가 확실히 틀린
    #: 행동이 모름으로 가려진다.
    if not permission.allowed:
        return _undetermined(
            f"링크 소환은 특수 소환입니다 — {permission.reason}",
            permission.missing_rule or SUMMON_PROHIBITION_RULE_MISSING,
            rule,
        )

    return _legal(rule)


def assess_link_placement(
    view, actor: int, materials: tuple[InstanceId, ...]
) -> "LinkMaterialAssessment | None":
    """
    놓을 자리가 있는가. **있으면 ``None``** 이다 (거절할 것이 없다).

    🔴 **소재가 떠난 뒤의 판을 본다.** 소재는 소환보다 먼저 필드를 떠나므로
    (모듈 머리말), 소재가 차지한 칸은 **빈 칸으로 세어야** 한다. 떠나기 전의
    판으로 세면 소재가 엑스트라 몬스터 존에 있는 경우가 "자리가 없다" 로
    읽힌다.

    자리가 없을 때 **두 갈래로 갈린다.**

    - 자신 필드에 링크 몬스터가 **없다** → 가리키는 칸도 없으므로 규칙상
      놓을 자리가 없다 (``ILLEGAL``).
    - 링크 몬스터가 **있다** → 그 마커가 가리키는 메인 몬스터 존에 놓을 수
      있을지 모른다. 마커의 칸 기하를 옮기지 않았으므로 ``UNDETERMINED``
      이고 :data:`LINK_PLACEMENT_LINKED_RULE` 이 그 이름이다.

    합치면 **규칙이 막은 것이 엔진 미지원으로** 집계된다 (Phase 6-AB 보완6).
    """
    mine = view.player(actor)
    leaving = set(materials)
    target = mine.zone(LINK_SUMMON_TO_ZONE)
    staying = [
        card
        for card in target.occupied()
        if card.instance_id not in leaving
    ]
    #: 칸 수는 ``capacity`` 가 말한다. ``len(ZoneView)`` 는 **장수**이므로
    #: 그것과 비교하면 "찬 칸 수 < 찬 칸 수" 가 되어 언제나 거짓이 된다.
    capacity = target.capacity
    if capacity is None or len(staying) < capacity:
        return None

    linked = [
        card
        for zone in sorted(LINK_MATERIAL_ZONES, key=lambda z: z.value)
        for card in mine.zone(zone).occupied()
        if card.instance_id not in leaving
        and card.definition is not None
        and card.definition.is_link
    ]
    if not linked:
        return _illegal(
            f"{LINK_SUMMON_TO_ZONE.value} 에 빈 칸이 없고, 자신 필드에 "
            "링크 몬스터가 없습니다 — 가리키는 메인 몬스터 존도 없으므로 "
            "놓을 자리가 없습니다."
        )
    return _undetermined(
        f"{LINK_SUMMON_TO_ZONE.value} 가 찼습니다. 자신 필드의 링크 몬스터가 "
        "가리키는 메인 몬스터 존에 놓을 수 있을지는 마커의 칸 기하를 아직 "
        "옮기지 못해 판정할 수 없습니다.",
        LINK_PLACEMENT_LINKED_RULE,
    )




#: 링크 소환의 **소환법 이름** — ``SummonUsageRegistry`` 의 열쇠에 쓴다.
#:
#: 🔴 :class:`~engine.effect.delta.SummonKind` 의 값을 그대로 쓴다. 이 모듈은
#: 효과 계층을 import 하지 않으므로 (머리말의 import 고리) 그 열거형을
#: 가져올 수 없고, 문자열을 **여기 하나에** 적어 두 곳이 갈라지지 않게 한다.
#: 같은 값인지는 시험이 센다.
LINK_SUMMON_KIND: str = "link"


__all__ = [
    "LINK_BLIND_SPOTS",
    "LINK_RATING_UNREADABLE_RULE",
    "LINK_SUMMON_KIND",
    "LINK_SUMMON_ONCE_PER_TURN",
    "LINK_MATERIAL_AS_LINK_RULE",
    "LINK_MATERIAL_BAN_RULE",
    "LINK_MATERIAL_DESTINATION",
    "LINK_MATERIAL_RULES",
    "LINK_MATERIAL_RULE_MISSING",
    "LINK_MATERIAL_ZONES",
    "LINK_PLACEMENT_LINKED_RULE",
    "LINK_SUMMON_FROM_ZONES",
    "LINK_SUMMON_POSITION",
    "LINK_SUMMON_TO_ZONE",
    "LinkMaterialAssessment",
    "LinkMaterialEligibility",
    "LinkMaterialRule",
    "LinkSummonTurnLimit",
    "MaterialRequirement",
    "assess_link_materials",
    "assess_link_placement",
    "material_contribution",
    "material_contribution_options",
    "material_rule_for",
    "reachable_material_counts",
    "turn_limit_for",
]
