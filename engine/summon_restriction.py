"""
특수 소환을 **막는 것이 판에 있는가** (Phase 6-AD).

    PlayerAction(LINK_SUMMON, …)            SpecialSummonOperation
        ↓                                        ↓
    engine.link_rules                        engine.effect.ruling
        ↘                                      ↙
          assess_special_summon_permission(view, actor)   ← 이 파일
                            ↓
              ALLOWED / FORBIDDEN / UNDETERMINED

왜 이 파일이 생겼는가 — **실측한 거짓 허가**
--------------------------------------------
Phase 6-AC 가 링크 소환을 실행하게 만들었고, 그 판정이
:func:`~engine.link_rules.assess_link_materials` 하나였다. 그 함수는 소재
조건과 놓을 자리만 보았으므로, **특수 소환을 막는 카드가 필드에 앞면으로
남아 있는 판에서도 링크 소환이 수락되었다.** 실측 (6-AD 검토):

    자신 필드: 기르수 69811710 · 성장 93920420 · 파키세팔로 42009836
    자신 엑스트라 덱: 갈라테아 30741503

    legal_actions → link_summon 후보가 **올라온다**
    Duel.apply     → accepted=True · code=OK
    결과           → 엑스트라 몬스터 존에 갈라테아, 필드에 파키세팔로 그대로

파키세팔로는 소재로 사라지지도 않았다. ``c42009836.lua`` 의 ``e1`` 이
``EFFECT_TYPE_FIELD`` · ``LOCATION_MZONE`` · ``EFFECT_CANNOT_SPECIAL_SUMMON``
· ``EFFECT_FLAG_PLAYER_TARGET`` · ``SetTargetRange(1,1)`` 이고, 공식 텍스트가
*"Neither player can Special Summon monsters."* 다. **링크 소환은 규칙상
특수 소환이므로** (공식 룰북) 그 금지가 걸린다.

무엇을 아는가 · 무엇을 모르는가
--------------------------------
두 가지를 **다른 축**으로 본다.

1. **그 카드가 특수 소환을 막을 수 있는 상수를 적었는가** — 관측이 신호로
   싣는다 (``CardDefinitionView.special_summon_restriction_signals``). 세
   가지 답이 다르다: ``None`` (스크립트를 못 읽었다) · ``()`` (끝까지
   읽었고 없다) · 비어 있지 않음 (막을 수 있는 것을 찾았다).
2. **그것이 지금 누구에게 걸리는가** — 신호는 말하지 않는다. 그것은 손으로
   읽은 표가 답한다 (:data:`SPECIAL_SUMMON_PROHIBITIONS`).

그래서 판정이 세 갈래다 (ADR-006).

==========================================  =======================
필드의 앞면 카드가 신호를 적지 않았다 (``()``)   그 카드는 막지 않는다
표에 **걸린다**고 적혀 있다                     ``FORBIDDEN`` — 확인된 금지
신호를 적었는데 표에 없다 · 스크립트를 못 읽었다  ``UNDETERMINED`` — 모른다
정체를 알 수 없는 앞면 카드가 있다               ``UNDETERMINED``
==========================================  =======================

🔴 **미확인을 안전으로 접지 않는다.** 그리고 반대로 **모든 앞면 효과
몬스터를 일괄 금지하지도 않는다** — 신호가 ``()`` 인 카드는 스크립트를
끝까지 읽고 그 상수가 없음을 확인한 쪽이고, 그것이 "확인된 안전 범위" 다.

🔴 **import 를 늘리지 않는다.** :mod:`engine.link_rules` 가 효과 계층을
모른다는 약속을 지켜야 하므로 (그쪽 머리말의 import 고리), 이 파일도
``engine.ids`` · ``engine.vocabulary`` 만 읽는다. 등록소도 ``Condition`` 도
여기 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.ids import InstanceId
from engine.vocabulary import Zone


# ======================================================================
# 어디를 보는가 · 무엇을 못 보는가
# ======================================================================

#: 지속 금지가 **적용되는 자리**. 앞면 카드만 본다.
#:
#: ``c42009836.lua`` 의 ``SetRange(LOCATION_MZONE)`` 가 그 자리를 적는다.
#: 마법·함정 존을 함께 보는 이유: 같은 모양의 금지를 **지속 마법·함정**이
#: 적는 경우가 있고 (「우비동」 류), 그때도 신호가 같은 자리에 실린다.
#: 그 카드들을 표에 적지 않았으므로 판정은 ``UNDETERMINED`` 가 되지만,
#: **보지 않는 것과 보고 모르는 것은 다르다.**
SUMMON_RESTRICTION_SCAN_ZONES: frozenset[Zone] = frozenset(
    {Zone.MZONE, Zone.EMZONE, Zone.SZONE}
)

#: 앞뒷면이 뜻을 갖는 자리. 뒷면 카드는 지속 효과를 적용하지 않는다 (룰북).
SUMMON_RESTRICTION_FACE_ZONES: frozenset[Zone] = frozenset(
    {Zone.MZONE, Zone.EMZONE, Zone.SZONE}
)

#: 신호를 적었는데 **언제 · 누구에게** 걸리는지를 표에 적지 않았다.
SUMMON_PROHIBITION_RULE_MISSING: str = (
    "summon-prohibition-scope (특수 소환 금지가 지금 누구에게 걸리는가)"
)

#: 🔴 **이 판정이 보지 않는 범위.** 판정을 바꾸지 않는다 — 적어만 둔다.
#:
#: 이 목록은 "허가해도 된다" 는 뜻이 **아니다.** 필드의 앞면 금지는 위에서
#: 실제로 판정하고, 여기 적힌 것은 **그 밖의** 금지 경로다. 그것들이
#: 지원되지 않는다는 사실을 면책 문구로 쓰지 않으려고 이름으로 남긴다.
SUMMON_RESTRICTION_BLIND_SPOTS: tuple[str, ...] = (
    "필드 밖(패 · 묘지 · 제외 상태)에서 걸리는 특수 소환 금지를 "
    "확인하지 않았습니다 — 그 자리의 지속 효과를 읽는 계층이 없습니다.",
    "지속 효과의 무효화 · 제거를 확인하지 않았습니다 — 금지가 무효화된 "
    "판에서도 이 판정은 금지를 그대로 읽습니다 (그 방향은 거짓 금지이고, "
    "거짓 허가보다 안전한 쪽입니다).",
    "속성 · 종족 · 소환법으로 범위가 좁혀진 금지를 확인하지 않았습니다 — "
    "표에 적은 것은 범위 조건이 없는 금지뿐입니다.",
)


# ======================================================================
# 손으로 읽은 표
# ======================================================================
class ProhibitionScope(str, Enum):
    """그 금지가 **누구에게** 걸리는가. ``SetTargetRange`` 를 옮긴 값이다."""

    BOTH = "both"
    """``SetTargetRange(1,1)`` — 서로의 플레이어."""
    CONTROLLER = "controller"
    """``SetTargetRange(1,0)`` — 그 카드의 컨트롤러."""
    OPPONENT = "opponent"
    """``SetTargetRange(0,1)`` — 상대."""

    def covers(self, actor: int, controller: int) -> bool:
        """P{actor} 가 이 금지에 걸리는가."""
        if self is ProhibitionScope.BOTH:
            return True
        if self is ProhibitionScope.CONTROLLER:
            return actor == controller
        return actor != controller


@dataclass(frozen=True, slots=True)
class SummonProhibitionRule:
    """
    카드 한 장이 **특수 소환을 막는가** — 손으로 읽은 사실.

    :class:`~engine.link_rules.LinkMaterialRule` 과 같은 규율이다: 근거를
    함께 들고 다닌다. 근거 없이 적힌 금지는 검증된 규칙이 아니다.

    :attr:`prohibits` 가 **두 방향 다** 적힌다는 것이 요점이다. 신호를
    적었는데 그 금지가 **이 엔진에서 걸릴 수 없는** 카드도 있고 (성유물－
    『성장』), 그 사실을 적지 않으면 그 카드가 필드에 있는 모든 판이
    ``UNDETERMINED`` 가 된다 — 정상 전개까지 막힌다.
    """

    card_id: int
    prohibits: bool
    text_ko: str
    lua_file: str
    lua_excerpt: str
    note: str
    scope: "ProhibitionScope | None" = None
    zones: frozenset[Zone] = SUMMON_RESTRICTION_SCAN_ZONES

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.card_id}")
        if self.prohibits and self.scope is None:
            raise ValueError(
                f"{self.card_id}: 막는다고 적었으면 **누구에게** 걸리는지도 "
                "적어야 합니다 (SetTargetRange 를 옮깁니다)."
            )
        if not self.prohibits and self.scope is not None:
            raise ValueError(
                f"{self.card_id}: 막지 않는다고 적었는데 범위가 적혀 "
                "있습니다 — 둘 중 하나가 거짓입니다."
            )
        for required in ("text_ko", "lua_file", "lua_excerpt", "note"):
            if not getattr(self, required).strip():
                raise ValueError(
                    f"{self.card_id}: {required} 를 비워 둘 수 없습니다 — "
                    "무엇을 읽고 그렇게 적었는지 남겨야 합니다."
                )

    def applies_to(self, actor: int, controller: int, zone: Zone) -> bool:
        """이 금지가 **지금 이 자리에서** P{actor} 에게 걸리는가."""
        if not self.prohibits or self.scope is None:
            return False
        if zone not in self.zones:
            return False
        return self.scope.covers(actor, controller)

    def canonical_state(self) -> tuple:
        return (
            self.card_id,
            self.prohibits,
            None if self.scope is None else self.scope.value,
            tuple(sorted(z.value for z in self.zones)),
        )


#: 손으로 읽은 금지 표. **이 표에 있는 카드만 확정 판정을 받는다.**
SPECIAL_SUMMON_PROHIBITIONS: tuple[SummonProhibitionRule, ...] = (
    SummonProhibitionRule(
        card_id=42009836,
        prohibits=True,
        scope=ProhibitionScope.BOTH,
        zones=frozenset({Zone.MZONE}),
        text_ko=(
            "파슬 다이너 파키세팔로: 「서로 특수 소환할 수 없다」 "
            "(공식 영문 Neither player can Special Summon monsters.)"
        ),
        lua_file="c42009836.lua",
        lua_excerpt=(
            "e1:SetType(EFFECT_TYPE_FIELD); e1:SetRange(LOCATION_MZONE); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET); "
            "e1:SetTargetRange(1,1); c:RegisterEffect(e1)"
        ),
        note=(
            "카드가 필드에 **앞면으로 있는 동안** 걸리는 지속 효과이고 "
            "(EFFECT_TYPE_FIELD · SetRange(LOCATION_MZONE)), 조건도 범위 "
            "조건도 없다 (SetCondition · SetTarget 가 없다). "
            "SetTargetRange(1,1) 이 '서로' 이고 PLAYER_TARGET 이 '플레이어 "
            "에게 걸린다' 다. 리버스 파괴 효과(e2)는 이 판정과 무관하므로 "
            "옮기지 않았다."
        ),
    ),
    SummonProhibitionRule(
        card_id=93920420,
        prohibits=False,
        text_ko=(
            "성유물－『성장』: ③ 의 발동 후에만 「그 턴 어둠 속성 이외를 "
            "특수 소환할 수 없다」 가 걸린다. 카드가 필드에 있는 것만으로는 "
            "아무것도 막지 않는다."
        ),
        lua_file="c93920420.lua",
        lua_excerpt=(
            "function s.spop2(...): local e1=Effect.CreateEffect(...); "
            "e1:SetType(EFFECT_TYPE_FIELD); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetTarget(s.splimit); Duel.RegisterEffect(e1,tp)"
        ),
        note=(
            "그 금지는 c:RegisterEffect 로 카드에 붙은 지속 효과가 아니라 "
            "**③ 의 해결(s.spop2)이 그때 만들어 등록하는** 효과다. ③ 은 "
            "EFFECT_LIBRARY 에 등재되지 않았으므로 이 엔진에서 발동될 수 "
            "없고 (engine.effect.library 의 _WORLD_WAND_RESTRICTION_GUARD "
            "가 그 사실을 import 시점에 지킨다), 그래서 신호가 있어도 "
            "이 판에서는 걸리지 않는다. ③ 을 등재하면 이 줄이 거짓이 된다."
        ),
    ),
    SummonProhibitionRule(
        card_id=48835607,
        prohibits=False,
        text_ko=(
            "오르페골 갈라테아i: 링크 소환에 성공하면 「그 턴 「오르페골 "
            "갈라테아i」를 링크 소환할 수 없다」 가 걸린다. 그것은 "
            "**카드명과 소환법으로 좁혀진** 제약이고, 특수 소환 전체를 "
            "막지 않는다."
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
            "신호(EFFECT_CANNOT_SPECIAL_SUMMON)는 실제로 있지만 **범위 "
            "조건이 붙어 있다** — SetTarget 이 c:IsCode(id) and "
            "sumtype&SUMMON_TYPE_LINK 이므로 그 카드명의 링크 소환만 막는다. "
            "그러므로 이 카드가 필드에 있다는 사실이 다른 특수 소환을 막지 "
            "않는다 (실측: 6-AF 전까지 이 카드가 엑스트라 몬스터 존에 있는 "
            "판에서 갈라테아의 링크 소환이 summon-prohibition-scope 로 "
            "보류되었다 — 규칙이 막지 않는 것이 엔진 미지원으로 집계됐다). "
            "🔴 좁혀진 그 제약을 **버린 것이 아니다** — "
            "engine.link_rules.LINK_SUMMON_ONCE_PER_TURN 가 같은 근거로 "
            "들고 있고 assess_link_materials 가 판정한다. 이 표에서 "
            "prohibits=False 인 것은 '특수 소환 전체를 막지 않는다' 는 "
            "뜻이고 '아무 제약도 없다' 는 뜻이 아니다. "
            "같은 스크립트의 EFFECT_CANNOT_BE_XYZ_MATERIAL 은 특수 소환 "
            "금지가 아니라 엑시즈 소재 제약이므로 이 판정과 무관하다."
        ),
    ),
    #: 🔴 **오르페골 디베르** (Phase 6-AO). 신호
    #: (``EFFECT_CANNOT_SPECIAL_SUMMON``) 는 실제로 있고, ① 은 **등재되어
    #: 있다** — 성유물－『성장』 ③ 과 다른 점이 그것이다. 그래도 이 표의 답은
    #: ``prohibits=False`` 이고 그 이유가 정확히 적혀야 한다.
    #:
    #: 그 제한은 **카드에 붙은 지속 효과가 아니다.** ``s.spop`` 이 해결 중에
    #: 만들어 플레이어에게 등록하는 효과이고, 그때 디베르는 비용으로
    #: **제외되어 필드에 없다.** 즉 "이 카드가 앞면으로 필드에 있다" 는 이
    #: 표의 질문과 그 제한은 **연결되어 있지 않다.**
    #:
    #: 🔴 **그 제한을 버린 것이 아니다** — Phase 6-AO 가 그것을 적는 계층을
    #: 만들었고 (:mod:`engine.state.summon_limit`),
    #: :func:`assess_special_summon_permission` 이 ``summoned`` 를 받은
    #: 자리에서 판정한다. 이 표에서 ``prohibits=False`` 인 것은 "**필드에
    #: 있다는 사실**이 특수 소환을 막지 않는다" 는 뜻이다.
    SummonProhibitionRule(
        card_id=57835716,
        prohibits=False,
        text_ko=(
            "오르페골 디베르: ① 의 발동 후에만 「턴 종료시까지 어둠 속성 "
            "몬스터밖에 특수 소환할 수 없다」 가 걸린다. 카드가 필드에 "
            "있는 것만으로는 아무것도 막지 않는다 (그 제한은 발동 비용으로 "
            "**제외된 뒤**에 걸린다)."
        ),
        lua_file="c57835716.lua",
        lua_excerpt=(
            "function s.spop(...): local e1=Effect.CreateEffect("
            "e:GetHandler()); e1:SetType(EFFECT_TYPE_FIELD); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_OATH); "
            "e1:SetTargetRange(1,0); e1:SetTarget(s.splimit); "
            "e1:SetReset(RESET_PHASE|PHASE_END); Duel.RegisterEffect(e1,tp)"
        ),
        note=(
            "그 금지는 c:RegisterEffect 로 카드에 붙은 지속 효과가 아니라 "
            "**① 의 해결(s.spop)이 그때 만들어 플레이어에게 등록하는** "
            "효과다. 그리고 그 시점에 이 카드는 비용(Cost.SelfBanish)으로 "
            "제외되어 필드에 없으므로, 이 표가 묻는 '필드의 앞면 카드' 와 "
            "그 제한은 연결되어 있지 않다. "
            "🔴 제한 자체는 Phase 6-AO 가 engine.state.summon_limit 에 적고 "
            "assess_special_summon_permission 이 summoned 를 받은 자리에서 "
            "판정한다 — 갈라테아i 와 같은 규율이다 (prohibits=False 는 "
            "'특수 소환 전체를 막지 않는다' 는 뜻이고 '아무 제약도 없다' 는 "
            "뜻이 아니다)."
        ),
    ),
    #: 🔴 **오르페골 스켈레촌** (Phase 6-AO 이 적고 6-AQ 가 근거를 옮겼다).
    #:
    #: 🔴 **왜 표에 있는가**: 디베르 ① 이 덱에서 특수 소환할 후보이고,
    #: 필드에 나오면 그 뒤의 모든 특수 소환 판정이 이 카드를 만난다. 표에
    #: 없으면 신호 때문에 그 판 전체가 ``UNDETERMINED`` 가 되고, 정상
    #: 전개가 "막는지 모른다" 로 멈춘다.
    #:
    #: 🔴 **6-AO 의 근거는 '① 이 등재되지 않았다' 였고, 6-AQ 가 ① 을
    #: 등재했다.** 그래서 이 줄은 디베르와 **같은 근거**로 다시 적혀 있다 —
    #: 제한은 발동 뒤에 걸리고 그때 이 카드는 비용으로 제외되어 필드에
    #: 없으므로, 이 표가 묻는 '필드의 앞면 카드' 와 연결되어 있지 않다.
    SummonProhibitionRule(
        card_id=21441617,
        prohibits=False,
        text_ko=(
            "오르페골 스켈레촌: ① 의 발동 후에만 「턴 종료시까지 어둠 속성 "
            "몬스터밖에 특수 소환할 수 없다」 가 걸린다. 카드가 필드에 "
            "있는 것만으로는 아무것도 막지 않는다."
        ),
        lua_file="c21441617.lua",
        lua_excerpt=(
            "function s.spop(...): e1:SetType(EFFECT_TYPE_FIELD); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_OATH); "
            "e1:SetTargetRange(1,0); e1:SetTarget(s.splimit); "
            "Duel.RegisterEffect(e1,tp)"
        ),
        note=(
            "디베르와 같은 모양의 제한이고 같은 이유로 필드에 있다는 사실과 "
            "연결되어 있지 않다 — 그 금지는 c:RegisterEffect 로 카드에 붙은 "
            "지속 효과가 아니라 **① 의 해결(s.spop)이 그때 만들어 "
            "플레이어에게 등록하는** 효과이고, 그 시점에 이 카드는 "
            "비용(Cost.SelfBanish)으로 제외되어 필드에 없다. "
            "🔴 제한 자체는 Phase 6-AQ 가 ① 을 등재하면서 "
            "engine.state.summon_limit 에 적고 "
            "assess_special_summon_permission 이 판정한다 (prohibits=False "
            "는 '특수 소환 전체를 막지 않는다' 는 뜻이고 '아무 제약도 없다' "
            "는 뜻이 아니다). "
            "🔴 6-AO 의 이 줄은 '① 이 EFFECT_LIBRARY 에 등재되지 않았다' 를 "
            "근거로 적혀 있었다. **그 근거는 6-AQ 에서 더 이상 참이 "
            "아니고**, 그래서 디베르와 같은 근거로 다시 적었다."
        ),
    ),
    SummonProhibitionRule(
        card_id=94046012,
        prohibits=False,
        text_ko=(
            "오르페골 카노네: ① 의 발동 후에만 「턴 종료시까지 어둠 속성 "
            "몬스터밖에 특수 소환할 수 없다」 가 걸린다. 카드가 필드에 "
            "있는 것만으로는 아무것도 막지 않는다."
        ),
        lua_file="c94046012.lua",
        lua_excerpt=(
            "function s.spop(...): e1:SetType(EFFECT_TYPE_FIELD); "
            "e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_OATH); "
            "e1:SetTargetRange(1,0); e1:SetTarget(s.splimit); "
            "Duel.RegisterEffect(e1,tp)"
        ),
        note=(
            "스켈레촌과 같은 모양의 제한이다. 다만 **근거가 다르다** — 이 "
            "카드의 ① 은 EFFECT_LIBRARY 에 등재되지 않았으므로 이 엔진에서 "
            "발동될 수 없고 (성유물－『성장』 ③ 과 같은 자리), "
            "engine.effect.library 의 _CANNONE_RESTRICTION_GUARD 가 그 "
            "사실을 import 시점에 지킨다. 등재하면 이 줄을 디베르 · "
            "스켈레촌과 같은 근거로 다시 적어야 한다."
        ),
    ),
)

#: 🔴 **"한 번에 2장 이상" 을 막는 금지** (Phase 6-AF) — 위의 표와 **다른
#: 질문**이다.
#:
#: 위의 표는 "특수 소환을 할 수 있는가" 이고 이 표는 "**동시에 여러 장**을
#: 특수 소환할 수 있는가" 다. 둘을 합치면 청안의 정령룡이 필드에 있는 판에서
#: 한 장짜리 특수 소환까지 막히고, 그것은 규칙이 아니다.
#:
#: 🔴 **왜 신호로 찾을 수 없는가.** 이 금지는
#: :data:`~core.card_model.SPECIAL_SUMMON_RESTRICTION_CODES` 의
#: ``EFFECT_CANNOT_SPECIAL_SUMMON`` 으로 적히지 않는다 — 카드가 **자기 ID 를
#: 코드로** 등록하고 (``e1:SetCode(id)``) 다른 스크립트가
#: ``Duel.IsPlayerAffectedByEffect(tp,CARD_BLUEEYES_SPIRIT)`` 로 묻는다.
#: 파싱 캐시는 그 숫자 코드를 **``null`` 로** 적으므로 (실측:
#: ``data/cache/lua_scripts.json`` 의 59822133 e1 → ``"code": null``) 이
#: 금지를 등록하는 카드를 전수 조회할 길이 **없다.** 그래서 손으로 읽은
#: 한 장만 확정 판정을 받고, 전수를 확인하지 못한 사실은 아래
#: :data:`SIMULTANEOUS_SUMMON_BLIND_SPOTS` 에 이름으로 남는다.
SIMULTANEOUS_SUMMON_PROHIBITIONS: tuple[SummonProhibitionRule, ...] = (
    SummonProhibitionRule(
        card_id=59822133,
        prohibits=True,
        scope=ProhibitionScope.BOTH,
        zones=frozenset({Zone.MZONE}),
        text_ko=(
            "청안의 정령룡: 「서로 2장 이상의 몬스터를 동시에 특수 소환할 "
            "수 없다」 (공식 영문 Neither player can Special Summon 2 or "
            "more monsters at the same time. — data/cards.cdb 59822133)"
        ),
        lua_file="c59822133.lua",
        lua_excerpt=(
            "local e1=Effect.CreateEffect(c); "
            "e1:SetType(EFFECT_TYPE_FIELD); e1:SetCode(id); "
            "e1:SetRange(LOCATION_MZONE); "
            "e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET); "
            "e1:SetTargetRange(1,1); c:RegisterEffect(e1)"
        ),
        note=(
            "카드가 필드에 **앞면으로 있는 동안** 걸리는 지속 효과이고 "
            "(EFFECT_TYPE_FIELD · SetRange(LOCATION_MZONE)), 조건도 범위 "
            "조건도 없다. SetTargetRange(1,1) 이 '서로' 다. 코드가 "
            "EFFECT_CANNOT_SPECIAL_SUMMON 이 아니라 **카드 자신의 ID** 이고 "
            "(SetCode(id)), 다른 카드들은 그것을 "
            "Duel.IsPlayerAffectedByEffect(tp,CARD_BLUEEYES_SPIRIT) 로 "
            "묻는다 — 상수 CARD_BLUEEYES_SPIRIT=59822133 은 "
            "data/constants/card_counter_constants.lua 에 있다."
        ),
    ),
)

#: 🔴 **이 판정이 보지 못하는 범위.** 허가로 바꾸지 않는다 — 적어만 둔다.
SIMULTANEOUS_SUMMON_BLIND_SPOTS: tuple[str, ...] = (
    "같은 금지를 등록하는 다른 카드가 있는지 전수로 확인하지 못했습니다 — "
    "파싱 캐시가 SetCode(id) 의 숫자 코드를 null 로 적으므로 "
    "(실측: 59822133 의 e1) 그 카드들을 조회할 수 없습니다.",
) + SUMMON_RESTRICTION_BLIND_SPOTS

#: 전수를 확인하지 못했다는 사실의 **이름**.
SIMULTANEOUS_SUMMON_RULE_MISSING: str = (
    "simultaneous-summon-prohibition-scan (동시 다수 특수 소환 금지를 "
    "등록하는 카드를 전수로 찾을 수 없다)"
)

_BY_CARD_SIMULTANEOUS: dict[int, SummonProhibitionRule] = {
    rule.card_id: rule for rule in SIMULTANEOUS_SUMMON_PROHIBITIONS
}

_BY_CARD: dict[int, SummonProhibitionRule] = {
    rule.card_id: rule for rule in SPECIAL_SUMMON_PROHIBITIONS
}
if len(_BY_CARD) != len(SPECIAL_SUMMON_PROHIBITIONS):  # pragma: no cover - 방어
    raise ValueError("한 카드의 금지를 두 줄로 적었습니다.")


#: 관측이 제한 칸을 싣지 않을 때의 이름 (Phase 6-AO).
SUMMON_LIMIT_VIEW_MISSING: str = (
    "summon-limit-view (관측이 효과가 걸어 둔 특수 소환 제한을 싣지 않는다)"
)

#: 소환하려는 카드의 속성을 읽지 못할 때의 이름 (Phase 6-AO).
SUMMON_LIMIT_ATTRIBUTE_MISSING: str = (
    "summon-limit-attribute (제한이 보는 속성을 읽을 수 없다)"
)


def prohibition_for(card_id: int) -> "SummonProhibitionRule | None":
    """손으로 읽은 금지. **적히지 않았으면 ``None``** (ADR-006)."""
    return _BY_CARD.get(card_id)


# ======================================================================
# 판정
# ======================================================================
class SpecialSummonPermission(str, Enum):
    """특수 소환을 **할 수 있는가** — 세 갈래다."""

    ALLOWED = "allowed"
    """판을 전부 읽었고 막는 것이 없다."""
    FORBIDDEN = "forbidden"
    """**확인된 금지**가 걸린다. 규칙이 막은 것이고 미지원이 아니다."""
    UNDETERMINED = "undetermined"
    """막는지 알 수 없다. 허가가 **아니다**."""


@dataclass(frozen=True, slots=True)
class SummonPermissionAssessment:
    """판정 하나와 그 이유. :class:`SpecialSummonPermission` 이 답이다."""

    permission: SpecialSummonPermission
    reason: str
    missing_rule: "str | None" = None
    blocker: "InstanceId | None" = None
    blocker_card_id: "int | None" = None
    unchecked: tuple[str, ...] = SUMMON_RESTRICTION_BLIND_SPOTS

    @property
    def forbidden(self) -> bool:
        return self.permission is SpecialSummonPermission.FORBIDDEN

    @property
    def allowed(self) -> bool:
        return self.permission is SpecialSummonPermission.ALLOWED

    def canonical_state(self) -> tuple:
        return (
            self.permission.value,
            self.missing_rule,
            None if self.blocker is None else self.blocker.value,
            self.blocker_card_id,
        )


def _limit_refusal(view, actor: int, summoned) -> "SummonPermissionAssessment | None":
    """
    효과가 걸어 둔 **카드별 제한**이 이 소환을 막는가 (Phase 6-AO).

    막지 않으면 ``None`` 이다 — 이 함수는 "허가" 를 돌려주지 않는다. 허가는
    판 전체를 읽은 뒤에만 할 수 있는 말이고, 그 판단은 부르는 쪽의 것이다.

    세 갈래다.

    - 제한이 없다 → ``None``
    - 제한이 있고 그 속성이 **아니다** → ``FORBIDDEN`` (확인된 금지)
    - 제한이 있는데 **속성을 읽을 수 없다** → ``UNDETERMINED``
      (:meth:`AttributeOnlyLimit.permits` 가 ``None``)
    """
    if summoned is None:
        return None
    limits = getattr(view, "special_summon_limits", None)
    if limits is None:
        #: 🔴 이 관측에는 제한 칸이 없다 — 옛 관측 객체이거나 시험용
        #: 대역이다. **없는 것을 허가로도 금지로도 바꾸지 않는다**: 제한을
        #: 볼 수 없다는 사실을 모름으로 적는다.
        return SummonPermissionAssessment(
            SpecialSummonPermission.UNDETERMINED,
            "이 관측은 효과가 걸어 둔 특수 소환 제한을 싣지 않습니다 — "
            "막는지 알 수 없습니다.",
            missing_rule=SUMMON_LIMIT_VIEW_MISSING,
        )
    attribute = getattr(summoned, "attribute_name", None)
    for limit in limits(actor):
        verdict = limit.permits(attribute)
        if verdict is True:
            continue
        if verdict is None:
            return SummonPermissionAssessment(
                SpecialSummonPermission.UNDETERMINED,
                f"{limit.describe_ko()} — 그런데 소환하려는 카드의 속성을 "
                "읽을 수 없어 그 제한을 지나는지 알 수 없습니다.",
                missing_rule=SUMMON_LIMIT_ATTRIBUTE_MISSING,
                blocker_card_id=limit.source_card_id,
            )
        return SummonPermissionAssessment(
            SpecialSummonPermission.FORBIDDEN,
            f"{limit.describe_ko()} — 소환하려는 카드는 "
            f"{attribute} 속성입니다.",
            blocker_card_id=limit.source_card_id,
        )
    return None


def assess_special_summon_permission(
    view, actor: int, *, summoned=None
) -> SummonPermissionAssessment:
    """
    P{actor} 가 **지금 특수 소환을 할 수 있는가.**

    **관측만 읽는다.** 판을 바꾸지 않고 ``GameState`` 를 받지 않는다.

    순서가 뜻을 가진다 — **확인된 금지를 먼저** 찾는다. 모름을 먼저 돌려
    주면 금지된 판이 "모른다" 로 집계되고, 그것은 규칙이 막은 것을 엔진
    미지원으로 적는 일이다 (Phase 6-AB 보완6 · 보완8 이 세운 구분).

    ``summoned`` (Phase 6-AO)
    -------------------------
    **무엇을 소환하려는지 아는 자리**는 그 카드 정의(``CardDefinitionView``)
    를 함께 준다. 그러면 효과가 걸어 둔 **카드별 제한**까지 본다
    (:mod:`engine.state.summon_limit`) — 「어둠 속성밖에 특수 소환할 수
    없다」 처럼 **무엇을 소환하는가에 따라 답이 갈리는** 제한이다.

    🔴 **주지 않으면 그 제한을 보지 않는다.** 판 전체에 걸리는 금지와 달리
    이 제한은 카드를 모르면 답할 수 없고, 모르는 것을 금지로 바꾸면
    **발동 시점에 고를 카드가 정해지지 않은 효과**(성유물－『성장』 ② ·
    디베르 ① 자신)가 전부 막힌다. 그 자리의 질문은 "지금 아무것도 특수
    소환할 수 없는가" 이고, 그것은 이 제한이 답하는 질문이 아니다.

    🔴 **카드를 아는 자리는 전부 주어야 한다.** 주지 않은 경로가 남으면 그
    경로로 제한이 우회된다 — 지금 주는 곳은 둘이다: 링크 소환 판정
    (:func:`~engine.link_rules.assess_link_materials`) 과 효과 해결의 관문
    (:meth:`~engine.effect.ruling.BoardRuling.explain_special_summon`).
    """
    #: 🔴 **카드별 제한이 필드 훑기보다 먼저다.** 이것은 **확인된** 금지이고
    #: (효과가 공개 해결되어 적힌 기록이다), 필드 훑기는 모름을 낼 수 있다 —
    #: 뒤에 두면 확인된 금지가 모름에 가린다 (위 문단의 순서 규율).
    decided = _limit_refusal(view, actor, summoned)
    if decided is not None:
        return decided

    undetermined: "SummonPermissionAssessment | None" = None
    for player in view.players:
        for zone in player.zones:
            if zone.zone not in SUMMON_RESTRICTION_SCAN_ZONES:
                continue
            for card in zone.cards:
                if card is None:
                    continue
                if zone.zone in SUMMON_RESTRICTION_FACE_ZONES and not card.face_up:
                    #: 뒷면 카드는 지속 효과를 적용하지 않는다 (룰북).
                    continue
                found = _look(view, actor, card, zone.zone)
                if found is None:
                    continue
                if found.forbidden:
                    return found
                if undetermined is None:
                    undetermined = found
    if undetermined is not None:
        return undetermined
    return SummonPermissionAssessment(
        SpecialSummonPermission.ALLOWED,
        "필드의 앞면 카드를 전부 읽었고 특수 소환을 막는 것이 없습니다.",
    )


def assess_simultaneous_special_summon_permission(
    view, actor: int, count: int
) -> SummonPermissionAssessment:
    """
    P{actor} 가 **한 번에 ``count`` 장**을 특수 소환할 수 있는가 (Phase 6-AF).

    공식 스크립트의 ``not Duel.IsPlayerAffectedByEffect(tp,
    CARD_BLUEEYES_SPIRIT)`` 를 옮긴 자리다.

    🔴 **``count`` 가 1 이면 묻지 않는다.** 이 금지는 "2장 이상 동시" 에만
    걸리므로, 한 장짜리 특수 소환에 적용하면 규칙에 없는 금지를 만든다.

    🔴 **:func:`assess_special_summon_permission` 과 합치지 않는다** — 다른
    질문이고 (그쪽 표의 설명), 합치면 한 장짜리까지 막힌다.

    세 갈래가 그대로 보존된다. 확인된 금지 → ``FORBIDDEN``, 필드의 앞면
    카드를 전부 읽었고 그 카드가 없다 → ``ALLOWED``, 정체를 알 수 없는
    앞면 카드가 있다 → ``UNDETERMINED``.
    """
    if count < 2:
        return SummonPermissionAssessment(
            SpecialSummonPermission.ALLOWED,
            f"{count}장은 '동시에 2장 이상' 이 아니므로 이 금지가 걸리지 "
            "않습니다.",
            unchecked=(),
        )
    undetermined: "SummonPermissionAssessment | None" = None
    for player in view.players:
        for zone in player.zones:
            if zone.zone not in SUMMON_RESTRICTION_SCAN_ZONES:
                continue
            for card in zone.cards:
                if card is None:
                    continue
                if (
                    zone.zone in SUMMON_RESTRICTION_FACE_ZONES
                    and not card.face_up
                ):
                    continue
                if card.card_id is None:
                    if undetermined is None:
                        undetermined = SummonPermissionAssessment(
                            SpecialSummonPermission.UNDETERMINED,
                            f"{zone.zone.value} 에 정체를 알 수 없는 앞면 "
                            "카드가 있어 동시 다수 특수 소환을 막는 것이 "
                            "있는지 볼 수 없습니다.",
                            SIMULTANEOUS_SUMMON_RULE_MISSING,
                            blocker=card.instance_id,
                            unchecked=SIMULTANEOUS_SUMMON_BLIND_SPOTS,
                        )
                    continue
                rule = _BY_CARD_SIMULTANEOUS.get(card.card_id)
                if rule is not None and rule.applies_to(
                    actor, card.controller, zone.zone
                ):
                    return SummonPermissionAssessment(
                        SpecialSummonPermission.FORBIDDEN,
                        f"{zone.zone.value} 의 {card.card_id} 가 동시에 "
                        f"{count}장을 특수 소환하는 것을 막습니다 — "
                        f"{rule.text_ko}",
                        blocker=card.instance_id,
                        blocker_card_id=card.card_id,
                        unchecked=SIMULTANEOUS_SUMMON_BLIND_SPOTS,
                    )
    if undetermined is not None:
        return undetermined
    return SummonPermissionAssessment(
        SpecialSummonPermission.ALLOWED,
        "필드의 앞면 카드를 전부 읽었고 동시 다수 특수 소환을 막는 카드가 "
        "없습니다.",
        unchecked=SIMULTANEOUS_SUMMON_BLIND_SPOTS,
    )


def _look(view, actor: int, card, zone: Zone) -> "SummonPermissionAssessment | None":
    """카드 한 장이 막는가. **막지 않는 것이 확인되면 ``None``** 이다."""
    if card.card_id is None:
        return SummonPermissionAssessment(
            SpecialSummonPermission.UNDETERMINED,
            f"{zone.value} 에 정체를 알 수 없는 앞면 카드가 있어 특수 소환을 "
            "막는 것이 있는지 볼 수 없습니다.",
            SUMMON_PROHIBITION_RULE_MISSING,
            blocker=card.instance_id,
        )
    rule = prohibition_for(card.card_id)
    if rule is not None and rule.applies_to(actor, card.controller, zone):
        return SummonPermissionAssessment(
            SpecialSummonPermission.FORBIDDEN,
            f"{zone.value} 의 {card.card_id} 가 특수 소환을 막습니다 — "
            f"{rule.text_ko}",
            blocker=card.instance_id,
            blocker_card_id=card.card_id,
        )
    definition = card.definition
    signals = (
        None if definition is None else definition.special_summon_restriction_signals
    )
    if signals is None:
        return SummonPermissionAssessment(
            SpecialSummonPermission.UNDETERMINED,
            f"{zone.value} 의 {card.card_id} 의 스크립트를 읽지 못해 특수 "
            "소환을 막는지 알 수 없습니다.",
            SUMMON_PROHIBITION_RULE_MISSING,
            blocker=card.instance_id,
            blocker_card_id=card.card_id,
        )
    if not signals:
        #: 🔴 **끝까지 읽었고 막는 상수가 없다** — 확인된 안전 범위다.
        return None
    if rule is not None:
        #: 신호는 있지만 손으로 읽은 표가 "이 판에서는 걸리지 않는다" 고
        #: 적었다 (성유물－『성장』 의 ③).
        return None
    return SummonPermissionAssessment(
        SpecialSummonPermission.UNDETERMINED,
        f"{zone.value} 의 {card.card_id} 가 특수 소환을 막을 수 있는 상수를 "
        f"적었지만 ({' · '.join(signals)}) 그것이 지금 누구에게 걸리는지를 "
        "이 저장소가 아직 읽지 않았습니다.",
        SUMMON_PROHIBITION_RULE_MISSING,
        blocker=card.instance_id,
        blocker_card_id=card.card_id,
    )


__all__ = [
    "SUMMON_PROHIBITION_RULE_MISSING",
    "SUMMON_RESTRICTION_BLIND_SPOTS",
    "SUMMON_RESTRICTION_FACE_ZONES",
    "SUMMON_RESTRICTION_SCAN_ZONES",
    "SIMULTANEOUS_SUMMON_BLIND_SPOTS",
    "SIMULTANEOUS_SUMMON_PROHIBITIONS",
    "SIMULTANEOUS_SUMMON_RULE_MISSING",
    "SUMMON_LIMIT_ATTRIBUTE_MISSING",
    "SUMMON_LIMIT_VIEW_MISSING",
    "SPECIAL_SUMMON_PROHIBITIONS",
    "ProhibitionScope",
    "SpecialSummonPermission",
    "SummonPermissionAssessment",
    "SummonProhibitionRule",
    "assess_simultaneous_special_summon_permission",
    "assess_special_summon_permission",
    "prohibition_for",
]
