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
)

_BY_CARD: dict[int, SummonProhibitionRule] = {
    rule.card_id: rule for rule in SPECIAL_SUMMON_PROHIBITIONS
}
if len(_BY_CARD) != len(SPECIAL_SUMMON_PROHIBITIONS):  # pragma: no cover - 방어
    raise ValueError("한 카드의 금지를 두 줄로 적었습니다.")


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


def assess_special_summon_permission(
    view, actor: int
) -> SummonPermissionAssessment:
    """
    P{actor} 가 **지금 특수 소환을 할 수 있는가.** 소환되는 카드와 무관하다.

    **관측만 읽는다.** 판을 바꾸지 않고 ``GameState`` 를 받지 않는다.

    순서가 뜻을 가진다 — **확인된 금지를 먼저** 찾는다. 모름을 먼저 돌려
    주면 금지된 판이 "모른다" 로 집계되고, 그것은 규칙이 막은 것을 엔진
    미지원으로 적는 일이다 (Phase 6-AB 보완6 · 보완8 이 세운 구분).
    """
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
    "SPECIAL_SUMMON_PROHIBITIONS",
    "ProhibitionScope",
    "SpecialSummonPermission",
    "SummonPermissionAssessment",
    "SummonProhibitionRule",
    "assess_special_summon_permission",
    "prohibition_for",
]
