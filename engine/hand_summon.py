"""
**패에서 자신을 특수 소환하는 카드별 절차** — 지금은 성유물－『성관』 하나.

    PlayerAction(SPECIAL_SUMMON, source=성관, targets=(ZONE 칸,))
        ↓  assess_hand_summon(view, actor, source, slot)      ← 이 파일
    HandSummonAssessment            적법 / 불법 / 판정할 수 없음
        ↓  ActionValidator           (``_hand_summon_legal`` 이 그대로 읽는다)
        ↓  Duel._hand_summon_actions (같은 함수로 후보를 만든다)
    LegalActions

왜 :mod:`engine.special_summon` 과 **다른 파일**인가
----------------------------------------------------
:mod:`engine.link_rules` 가 링크 소환에서 한 것과 **같은 가름**이다 — 판정은
관측만 읽고, 절차는 판을 바꾼다. 그리고 :mod:`engine.special_summon` 은
**카드를 모르는 공통 경로**다: 거기 카드별 조건을 넣으면 "특수 소환" 하나가
카드 지식을 갖게 되고, 그 다음 카드마다 그 파일이 자란다.

🔴 **공통 경로의 불변식을 깨뜨리지 않는다.**
:func:`~engine.action_validation._special_summon` 의 마지막 요구는 **등재되지
않은 카드에 대해 여전히 ``UNKNOWN``** 이다. 이 파일에 적힌 카드만 그 자리를
실제 판정으로 바꾼다 — ``LINK_SUMMON`` 이
:data:`~engine.link_rules.LINK_MATERIAL_RULES` 로 범위를 좁히는 것과 **같은
구조**다.

성관의 공식 텍스트와 스크립트
-----------------------------
*"You can Special Summon this card (from your hand) in Defense Position to your
zone a Link Monster points to. You can only Special Summon "World Legacy -
"World Crown"" once per turn this way."*

``c27918365.lua`` 의 ``e1`` 이 그 절차다::

    local e1=Effect.CreateEffect(c)
    e1:SetType(EFFECT_TYPE_FIELD)
    e1:SetProperty(EFFECT_FLAG_UNCOPYABLE+EFFECT_FLAG_SPSUM_PARAM)
    e1:SetCode(EFFECT_SPSUMMON_PROC)          -- 🔴 **소환 절차**다
    e1:SetRange(LOCATION_HAND)
    e1:SetTargetRange(POS_FACEUP_DEFENSE,0)   -- 🔴 앞면 **수비** 표시만
    e1:SetCountLimit(1,id,EFFECT_COUNT_CODE_OATH)
    e1:SetValue(function(e,c) return 0,aux.GetMMZonesPointedTo(c:GetControler()) end)

여기서 읽어 옮긴 것 네 가지:

1. ``EFFECT_SPSUMMON_PROC`` — **체인을 만들지 않는다.** 소환 절차는 발동이
   아니므로 체인 링크가 생기지 않고, 상대의 응답 기회도 그 때문에 열리지
   않는다. 그래서 이 파일은 :mod:`engine.chain` 을 import 하지 않는다.
2. ``SetRange(LOCATION_HAND)`` — 패에서만.
3. ``SetTargetRange(POS_FACEUP_DEFENSE,0)`` — 앞면 수비 표시. 🔴 고를 수
   **없다** (공통 경로의 ``SPECIAL_SUMMON_POSITION`` 과 다른 값이고, 그래서
   카드별 절차가 필요하다).
4. ``SetCountLimit(1,id,...)`` — ``id`` 하나이므로 **카드명당 1턴 1번**
   (:class:`~engine.use_limit.LimitScope` 의 ``PER_CARD_NAME``). ``OATH`` 는
   "선언했으면 못 되돌린다" 는 뜻이고 이 저장소에 그 계층이 없다 —
   :data:`UNPORTED` 에 적어 둔다.

놓을 칸은 :mod:`engine.link_zone` 이 답한다
-------------------------------------------
``aux.GetMMZonesPointedTo`` 의 **정의는 vendoring 되어 있지 않다** (호출
자리만 있다). 그래서 6-BK 가 :mod:`engine.link_zone` 을 세워 **가능한 EMZ
정렬 전부**를 보고 답하게 했다. 이 파일은 그 판정을 그대로 쓴다:

* 모든 정렬에서 그 칸이 가리켜지고 비어 있으면 → 적법
* 어느 정렬에서도 아니면 → 불법
* 갈리면 → **판정할 수 없음** (``UNKNOWN`` 은 허가가 아니다 · ADR-006)

🔴 **행동이 칸을 들고 간다.** ``PlayerAction.targets`` 에 ``ZONE`` 대상으로
칸 번호를 싣는다 — 그래야 후보 생성 · 판정 · 절차 · 리플레이가 **같은 칸**을
가리킨다 (사용자 요구). 공통 경로는 칸을 고르지 않고 ``free[0]`` 을 쓰므로
(STRUCTURAL-41) 그 자리로는 이 요구를 지킬 수 없다.

여기서 하지 않는 것 (:data:`UNPORTED`)
--------------------------------------
``EFFECT_COUNT_CODE_OATH`` 의 되돌릴 수 없음, ``EFFECT_FLAG_SPSUM_PARAM`` 이
넘기는 소환 파라미터의 나머지, 상대의 링크 몬스터가 내 칸을 가리키는 경우,
``EFFECT_BECOME_LINKED_ZONE`` 처럼 마커 없이 가리키게 만드는 효과, 성관의
②(효과 무효) · ③(「성유물」 서치).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.effect.ruling import ConditionResult
from engine.link_zone import (
    MODELLED_ALIGNMENT,
    POINTED_ZONE_SOURCE_GAP,
    pointed_zone_verdict,
    pointed_zones,
)
from engine.use_limit import LimitScope
from engine.vocabulary import Position, Zone

__all__ = [
    "HAND_SUMMON_RULES",
    "HAND_SUMMON_USE_KIND",
    "WORLD_CROWN",
    "HandSummonEligibility",
    "HandSummonAssessment",
    "HandSummonRule",
    "UNPORTED",
    "assess_hand_summon",
    "hand_summon_rule_for",
    "hand_summon_slots",
]

WORLD_CROWN = 27918365

#: 🔴 **옮기지 않은 것**을 글자로 들고 있다. 등재했다는 말이 "전부
#: 구현했다" 로 읽히지 않게 하는 자리다 (ADR-006).
UNPORTED: tuple[str, ...] = (
    "EFFECT_COUNT_CODE_OATH — 선언한 뒤 되돌릴 수 없다는 성질을 읽는 계층이"
    " 없습니다 (이 저장소는 선언을 취소하지 않으므로 지금은 차이가 드러나지"
    " 않습니다).",
    "EFFECT_FLAG_SPSUM_PARAM 이 넘기는 소환 파라미터 가운데 표시 형식과"
    " 칸 말고는 옮기지 않았습니다.",
    "상대의 링크 몬스터가 내 칸을 가리키는 경우를 세지 않습니다"
    " (engine.link_zone 의 범위 밖).",
    "EFFECT_BECOME_LINKED_ZONE 처럼 마커 없이 가리키게 만드는 효과를 읽지"
    " 않습니다.",
    "성관의 ②(엑스트라 덱 몬스터의 효과 무효) 와 ③(「성유물」 마법·함정"
    " 서치) 는 등재되지 않았습니다.",
)


class HandSummonEligibility(str, Enum):
    """판정 셋. 🔴 ``UNKNOWN`` 은 허가가 **아니다.**"""

    LEGAL = "legal"
    ILLEGAL = "illegal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HandSummonRule:
    """
    카드 한 장의 **패 특수 소환 절차**. 🔴 손으로 읽어 적은 값이다.
    """

    card_id: int
    from_zone: Zone
    position: Position
    limit_scope: LimitScope
    limit_count: int
    lua_file: str
    lua_excerpt: str
    note: str
    requires_link_pointed_zone: bool = True
    """🔴 놓을 칸이 **링크 마커가 가리키는 메인 몬스터 존**이어야 하는가."""

    def describe_ko(self) -> str:
        return (
            f"{self.card_id}: {self.from_zone.value} 에서 "
            f"{self.position.value} 로, "
            + ("링크 마커가 가리키는 빈 메인 몬스터 존에 "
               if self.requires_link_pointed_zone else "")
            + f"{self.limit_count}턴 1번 ({self.limit_scope.value})"
        )


#: 🔴 **등재된 카드 전부.** 적히지 않은 카드는 공통 경로의 ``UNKNOWN`` 에
#: 그대로 막힌다 — 이 표가 범위를 좁게 적는 유일한 자리다.
HAND_SUMMON_RULES: tuple[HandSummonRule, ...] = (
    HandSummonRule(
        card_id=WORLD_CROWN,
        from_zone=Zone.HAND,
        position=Position.FACEUP_DEFENSE,
        #: ``SetCountLimit(1,id,…)`` — ``id`` 하나다 → 카드명당.
        limit_scope=LimitScope.PER_CARD_NAME,
        limit_count=1,
        lua_file="c27918365.lua",
        lua_excerpt=(
            "e1:SetCode(EFFECT_SPSUMMON_PROC)  "
            "e1:SetRange(LOCATION_HAND)  "
            "e1:SetTargetRange(POS_FACEUP_DEFENSE,0)  "
            "e1:SetCountLimit(1,id,EFFECT_COUNT_CODE_OATH)  "
            "e1:SetValue(function(e,c) return 0,"
            "aux.GetMMZonesPointedTo(c:GetControler()) end)"
        ),
        note=(
            "성유물－『성관』: 공식 텍스트 전문과 c27918365.lua 의 e1 을 읽었다."
            " 체인을 만들지 않는 **소환 절차**이고 (EFFECT_SPSUMMON_PROC),"
            " 패에서 앞면 **수비** 표시로만 나오며, 놓을 칸은 자신 필드의 링크"
            " 몬스터가 가리키는 **메인 몬스터 존**이다. 🔴 턴 제한은"
            " 카드명당 1번이다. 🔴 이 등재가 '이 카드를 전부 구현했다' 는 뜻은"
            " 아니다 — engine.hand_summon.UNPORTED 가 남은 것을 적는다."
        ),
    ),
)

_BY_CARD: dict[int, HandSummonRule] = {
    rule.card_id: rule for rule in HAND_SUMMON_RULES
}


def hand_summon_rule_for(card_id: "int | None") -> "HandSummonRule | None":
    """그 카드의 절차. **등재되지 않았으면 ``None``** (ADR-006)."""
    if card_id is None:
        return None
    return _BY_CARD.get(int(card_id))


@dataclass(frozen=True, slots=True)
class HandSummonAssessment:
    """
    "이 카드를 이 칸에 패에서 특수 소환할 수 있는가" 의 답.

    🔴 :attr:`eligibility` 가 ``LEGAL`` 일 때만 허가가 난다.
    :attr:`unchecked` 는 **확인하지 못한 것**이고, 그것이 있다고 답이
    약해지지는 않는다 — 답의 범위를 적는 자리다.
    """

    eligibility: HandSummonEligibility
    reason: str
    rule: "HandSummonRule | None" = None
    slot: "int | None" = None
    unchecked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def permits_procedure(self) -> bool:
        return self.eligibility is HandSummonEligibility.LEGAL

    def describe_ko(self) -> str:
        return f"{self.eligibility.value}: {self.reason}"


def hand_summon_slots(view, actor: int, card_id: int) -> tuple[int, ...]:
    """
    그 카드를 놓을 수 있는 **칸 번호들** (후보 생성이 쓴다).

    🔴 **판정은 하지 않는다** — 칸마다 :func:`assess_hand_summon` 에게
    다시 물어야 한다. 이 함수는 "물어볼 값어치가 있는 칸" 만 좁힌다.

    🔴 모델링된 정렬 아래의 칸을 돌려준다. 그 정렬이 전개를 바꾸지 않는지는
    :mod:`engine.link_zone` 의 시험이 두 정렬을 모두 돌려 센다.
    """
    rule = hand_summon_rule_for(card_id)
    if rule is None or not rule.requires_link_pointed_zone:
        return ()
    verdict = pointed_zone_verdict(view, actor)
    if verdict.answer is not ConditionResult.TRUE:
        #: 🔴 갈리거나 없으면 **칸을 내놓지 않는다** — 후보를 만들어 두고
        #: 판정에서 막는 것보다, 물어볼 칸이 없다는 사실이 정확하다.
        return ()
    return verdict.slots


def assess_hand_summon(view, actor: int, source, slot: "int | None") -> HandSummonAssessment:
    """
    **한 칸에 대한** 판정. 후보 생성기와 검증기가 **같은 이 함수**를 부른다.

    보는 것 (순서가 뜻을 가진다):

    1. 그 카드에 등재된 절차가 있는가 — 없으면 ``UNKNOWN`` (ADR-006).
    2. 내 카드이고 그 절차가 적은 자리(패)에 있는가.
    3. 판에 걸린 **특수 소환 제한**이 이 카드를 막는가.
    4. 이번 턴에 **카드명당 제한**을 이미 썼는가.
    5. 그 칸이 **링크 마커가 가리키는 빈 칸**인가.
    """
    card = view.find(source) if source is not None else None
    if card is None:
        return HandSummonAssessment(
            HandSummonEligibility.UNKNOWN,
            "그 카드를 관측에서 찾지 못했습니다.",
        )
    definition = card.definition
    card_id = card.card_id if card.card_id is not None else None
    rule = hand_summon_rule_for(card_id)
    if rule is None:
        return HandSummonAssessment(
            HandSummonEligibility.UNKNOWN,
            "이 카드의 패 특수 소환 절차가 등재되지 않았습니다 — "
            "engine.hand_summon.HAND_SUMMON_RULES 에 적힌 카드만 판정합니다.",
        )
    if card.controller != actor:
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            f"P{actor} 의 카드가 아닙니다.", rule=rule,
        )
    if card.zone is not rule.from_zone:
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            f"{rule.from_zone.value} 에 없습니다 (현재 {card.zone.value}).",
            rule=rule,
        )

    #: 3. 판에 걸린 특수 소환 제한. 🔴 **판정을 여기서 다시 적지 않는다** —
    #: :func:`~engine.summon_restriction.assess_special_summon_permission`
    #: 하나가 답한다 (아래 ``_restriction_verdict``).
    blocked = _restriction_verdict(view, actor, definition)
    if blocked is not None:
        if blocked.forbidden:
            return HandSummonAssessment(
                HandSummonEligibility.ILLEGAL, blocked.reason, rule=rule,
            )
        #: 🔴 **모름은 허가가 아니다** (ADR-006). 제한을 지나는지 모르면
        #: 후보가 되지 않는다.
        return HandSummonAssessment(
            HandSummonEligibility.UNKNOWN, blocked.reason, rule=rule,
            unchecked=UNPORTED,
        )

    #: 4. 카드명당 턴 제한.
    if _limit_spent(view, actor, rule):
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            f"이 방법으로는 1턴에 {rule.limit_count}번뿐이고 "
            "(같은 이름의 카드 전체 기준) 이 턴에 이미 썼습니다.",
            rule=rule,
        )

    #: 5. 놓을 칸.
    if not rule.requires_link_pointed_zone:
        return HandSummonAssessment(
            HandSummonEligibility.LEGAL,
            "등재된 절차의 조건을 만족합니다.", rule=rule, slot=slot,
            unchecked=UNPORTED,
        )
    if slot is None:
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            "놓을 칸이 지목되지 않았습니다 — 이 카드는 링크 마커가 가리키는 "
            "칸에만 나오므로 칸을 함께 지목해야 합니다.",
            rule=rule,
        )
    verdict = pointed_zone_verdict(view, actor)
    if verdict.answer is ConditionResult.FALSE:
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            "링크 몬스터가 가리키는 빈 메인 몬스터 존이 없습니다.",
            rule=rule, slot=slot,
        )
    if verdict.answer is ConditionResult.UNKNOWN:
        return HandSummonAssessment(
            HandSummonEligibility.UNKNOWN,
            "놓을 수 있는지가 엑스트라 몬스터 존의 열에 따라 갈립니다 — "
            + POINTED_ZONE_SOURCE_GAP,
            rule=rule, slot=slot,
        )
    #: 🔴 **그 칸이** 가리켜지는 빈 칸인가 — 존재만으로 허가하지 않는다.
    if int(slot) not in set(verdict.slots):
        pointed = pointed_zones(view, actor, MODELLED_ALIGNMENT)
        why = (
            "그 칸은 링크 마커가 가리키지 않습니다"
            if int(slot) not in pointed else "그 칸이 비어 있지 않습니다"
        )
        return HandSummonAssessment(
            HandSummonEligibility.ILLEGAL,
            f"{why} (가리켜지는 빈 칸: "
            f"{sorted(verdict.slots)}).",
            rule=rule, slot=slot,
        )
    return HandSummonAssessment(
        HandSummonEligibility.LEGAL,
        f"링크 마커가 가리키는 빈 칸 {slot} 에 "
        f"{rule.position.value} 로 놓습니다.",
        rule=rule, slot=int(slot), unchecked=UNPORTED,
    )


def _restriction_verdict(view, actor: int, definition):
    """
    판에 걸린 특수 소환 제한이 이 카드를 막는가. **판정하지 않는다** —
    :func:`~engine.summon_restriction.assess_special_summon_permission`
    에게 묻고 그 답을 그대로 돌려준다.

    돌려주는 것은 세 갈래다.

    - 막지 않는다 → ``None``
    - 확인된 금지 → ``forbidden`` 인 판정
    - 제한은 있는데 속성을 읽지 못했다 → ``UNDETERMINED`` 인 판정

    🔴 **여기서 제한을 다시 읽지 않는다.** 6-BN 의 첫 판에서는 이 함수가
    ``view.summon_limits`` 의 줄을 ``row[0]`` 으로 직접 읽었는데, 관측이
    싣는 것은 :class:`~engine.state.summon_limit.AttributeOnlyLimit`
    **객체**이고 ``slots`` 가 걸린 dataclass 는 번호로 읽히지 않는다 —
    그래서 모든 제한이 조용히 건너뛰어졌다. 규칙을 두 곳에 적으면 둘이
    갈린다는 말이 **측정으로 확인된** 자리다.
    """
    # 여기서 읽는다 — 두 판정 모듈이 서로를 모듈 최상단에서 읽으면 고리가
    # 생긴다 (``_LinkMaterialsLegal`` 의 설명과 같은 이유).
    from engine.summon_restriction import assess_special_summon_permission

    got = assess_special_summon_permission(view, actor, summoned=definition)
    if got.allowed:
        return None
    return got


def _limit_spent(view, actor: int, rule: HandSummonRule) -> bool:
    """
    카드명당 턴 제한을 이미 썼는가. 🔴 **관측에 적힌 것만 읽는다.**

    ``GameStateView.summons_by_name`` 은 ``(seat, card_id, kind, count)`` 들
    이고, 이 절차가 적는 ``kind`` 는 :data:`HAND_SUMMON_USE_KIND` 다.
    """
    rows = tuple(getattr(view, "summons_by_name", ()) or ())
    for row in rows:
        try:
            seat, card_id, kind, count = row[0], row[1], row[2], row[3]
        except (TypeError, IndexError):  # pragma: no cover - 방어용
            continue
        if int(seat) != int(actor) or int(card_id) != int(rule.card_id):
            continue
        if str(kind) != HAND_SUMMON_USE_KIND:
            continue
        if int(count) >= int(rule.limit_count):
            return True
    return False


#: 이 절차가 사용 기록에 적는 이름. 🔴 **링크 소환 기록과 섞이지 않는다** —
#: 같은 카드가 두 방법으로 나오는 일이 있고, 제한은 방법마다 따로다.
HAND_SUMMON_USE_KIND: str = "hand-spsummon"
