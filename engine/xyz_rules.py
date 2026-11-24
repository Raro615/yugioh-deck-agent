"""
엑시즈 소환의 **판정** — 대체 절차 하나를 손으로 읽어 적었다 (Phase 6-BO).

    PlayerAction(XYZ_SUMMON, source=딩기르수, materials=(롱기르수,))
        ↓  assess_xyz_materials          ← 이 파일 (관측만 읽는다)
        ↓  ActionValidator               허가 / 거절 / 모름
        ↓  XyzSummonExecutor             소재를 겹치고 놓는다
    GameState 변경 + MaterialAttached + MonsterSummoned(summon=XYZ)

왜 판정이 실행과 **다른 파일**인가
----------------------------------
:mod:`engine.link_rules` 가 :mod:`engine.link_summon` 과 갈린 것과 같은
이유다. 실행 계층은 ``engine.summon`` · ``engine.effect`` 를 끌고 오고 그
길은 검증기로 되돌아온다 (실측: 그쪽 모듈 머리말). 판정은 그 계층을 아예
모른다 — 받는 것은 :class:`~engine.game_state_view.GameStateView` 하나다
(ADR-007).

무엇을 읽어 적었는가
--------------------
``c93854893.lua`` (시오르페골 딩기르수) 의 ``Xyz.AddProcedure`` 호출
하나다::

    Xyz.AddProcedure(c,nil,8,2,s.ovfilter,aux.Stringid(id,0))
    function s.ovfilter(c,tp,xyzc)
        return c:IsFaceup()
            and c:IsType(TYPE_LINK,xyzc,SUMMON_TYPE_XYZ,tp)
            and c:IsSetCard(SET_ORCUST,xyzc,SUMMON_TYPE_XYZ,tp)
    end

여섯째 인자까지의 뜻을 가른다.

===========================  ===================================================
``nil``                       기본 소재의 추가 필터 — 없다
``8`` · ``2``                 **기본 절차**: 레벨 8 몬스터 2장
``s.ovfilter``                **대체 절차**: 그 필터를 만족하는 카드 **1장**
===========================  ===================================================

🔴 **이 파일이 적은 것은 대체 절차 하나뿐이다.** 기본 절차(레벨 8 몬스터
2장)는 **옮기지 않았다** — 레벨을 세어 겹치는 계층이 없다. 그래서 고른
소재가 대체 절차의 모양이 아니면 이 판정은 ``UNDETERMINED`` 를 돌려주고
(:data:`XYZ_BASE_PROCEDURE_RULE`), **"안 된다" 고 말하지 않는다.**

🔴 **카드 목록이 아니라 조건을 적었다.** ``ovfilter`` 는 카드 ID 를 보지
않고 「앞면 · 링크 몬스터 · 「오르페골」」 세 가지를 본다. 그래서 갈라테아 ·
갈라테아i · 롱기르수 · 엔릴기르수가 **전부 자연히 후보가 된다** — 어느
카드를 쓸지는 이 파일이 정하지 않는다.

여기서 하지 않는 것 (:data:`XYZ_BLIND_SPOTS`)
---------------------------------------------
기본 절차 · 소재를 제거하는 비용(``RemoveOverlayCard``) · 파괴 대체
(``EFFECT_DESTROY_REPLACE``) · 상대의 링크 몬스터를 소재로 쓰는 경우 ·
표시 형식 고르기 · 엑스트라 몬스터 존 밖의 칸.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.archetype import matches_setcode
from engine.archetype_compiler import compile_archetype_condition
from engine.ids import InstanceId
from engine.vocabulary import Position, Zone

#: 출발 자리. 엑시즈 몬스터는 엑스트라 덱에서만 나온다 (공식 규칙).
#:
#: 묘지 · 제외에서 되살아나는 엑시즈 몬스터도 있지만 그것은 **특수 소환**
#: 이고 엑시즈 소환이 아니다 (「엑시즈 소환한 이 카드가」 와 가르는 바로 그
#: 구분이다).
XYZ_SUMMON_FROM_ZONES: frozenset[Zone] = frozenset({Zone.EXTRA})

#: 놓이는 자리. 모델상 자리당 한 칸이다 (``engine.vocabulary.ZONE_CAPACITY``).
#:
#: 🔴 **공식 규칙은 더 넓다.** 엑스트라 덱에서 나오는 몬스터는 엑스트라
#: 몬스터 존 **또는** 자신 링크 몬스터가 가리키는 메인 몬스터 존에 놓을 수
#: 있다. 뒤쪽을 옮기지 않은 이유는 :data:`XYZ_PLACEMENT_RULE` 가 적는다.
XYZ_SUMMON_TO_ZONE: Zone = Zone.EMZONE

#: 놓이는 표시 형식. **고를 수 없다** (STRUCTURAL-61 과 같은 자리).
#:
#: 실제 엑시즈 소환은 앞면 공격 · 앞면 수비를 고를 수 있다. 고르는 계층이
#: 없어서 하나로 고정했을 뿐이고, 이것이 규칙이라고 주장하지 않는다 —
#: 링크 소환의 ``LINK_SUMMON_POSITION`` 과 **다른 종류의 고정**이다 (저쪽은
#: 규칙이 하나로 정했다: 링크 몬스터에는 수비 표시가 없다).
XYZ_SUMMON_POSITION: Position = Position.FACEUP_ATTACK

#: 소재가 있을 수 있는 자리 — 자신 **필드의** 몬스터다.
XYZ_MATERIAL_ZONES: frozenset[Zone] = frozenset({Zone.MZONE, Zone.EMZONE})

#: 소재가 가는 자리. 🔴 **공식 절차 — 엑시즈 소재는 묘지로 가지 않는다.**
#: 그 카드 아래에 겹쳐지고 판에 남는다. 링크 소재와 가르는 바로 그 차이다
#: (:data:`~engine.link_rules.LINK_MATERIAL_DESTINATION` 는 ``GRAVE``).
XYZ_MATERIAL_DESTINATION: Zone = Zone.OVERLAY

#: 소재 조건을 **읽지 않은** 엑시즈 몬스터의 빠진 규칙 이름.
XYZ_RULE_MISSING: str = (
    "xyz-material-requirement (이 엑시즈 몬스터의 소재 조건을 아직 읽지 않았다)"
)

#: 🔴 **기본 절차를 옮기지 않았다.** 「레벨 N 몬스터 2장」 을 세어 겹치는
#: 계층이 없다. 고른 소재가 대체 절차의 모양이 아닐 때 이 이름이 나온다 —
#: 그때의 답은 **"안 된다" 가 아니라 "모른다"** 다 (ADR-006).
XYZ_BASE_PROCEDURE_RULE: str = (
    "xyz-base-procedure (레벨이 맞는 몬스터 여러 장을 겹치는 기본 절차를 "
    "아직 옮기지 않았다)"
)

#: 🔴 **엑스트라 몬스터 존 밖의 칸을 옮기지 않았다.** 공식 규칙은 자신
#: 링크 몬스터가 가리키는 메인 몬스터 존도 허락하고, 그 칸을 세는 계층은
#: 이미 있다 (:mod:`engine.link_zone`). 그런데 대체 절차는 **그 링크
#: 몬스터를 소재로 먹으므로**, 소재가 떠난 뒤에 누가 어느 칸을 가리키는지가
#: 달라진다 — 그 순서를 읽은 근거가 아직 없다.
XYZ_PLACEMENT_RULE: str = (
    "xyz-placement-outside-emz (링크 마커가 가리키는 메인 몬스터 존에 "
    "엑시즈 몬스터를 놓는 길을 아직 옮기지 않았다)"
)

#: 판정을 **바꾸지 않는** 관찰들 — 읽었고 옮기지 않은 것.
#:
#: :class:`XyzMaterialAssessment` 의 ``unchecked`` 로 실려 나간다.
#: 🔴 모름이 아니다: 이것들이 있다고 답이 약해지지 않는다. 답의 **범위**를
#: 적는 자리다 (``engine.hand_summon.UNPORTED`` 와 같은 규율).
XYZ_BLIND_SPOTS: tuple[str, ...] = (
    "기본 절차 (레벨 8 몬스터 2장) — 레벨을 세어 겹치는 계층이 없다.",
    "소재를 제거하는 비용 (RemoveOverlayCard) — 꺼내 쓰는 계층이 없다.",
    "파괴 대체 효과 (EFFECT_DESTROY_REPLACE · c93854893.lua 의 e1) — "
    "지속 효과와 파괴 대체 계층이 없다.",
    "상대의 링크 몬스터를 소재로 쓰는 경우 — ovfilter 는 tp 를 넘기므로 "
    "자신 필드만 본다고 읽었지만, 컨트롤을 넘긴 판으로 확인하지 않았다.",
    "표시 형식 고르기 (앞면 공격 · 앞면 수비) — 고르는 계층이 없다.",
    "소재가 2장 이상인 대체 절차 — 지금 등재된 카드는 1장짜리 하나다.",
)


class XyzMaterialEligibility(str, Enum):
    """판정 셋. 🔴 ``UNDETERMINED`` 은 허가가 **아니다.**"""

    LEGAL = "legal"
    ILLEGAL = "illegal"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True, slots=True)
class XyzAlternativeRule:
    """
    엑시즈 몬스터 한 장의 **대체 소환 절차**. 근거를 함께 들고 다닌다.

    :class:`~engine.link_rules.LinkMaterialRule` 과 같은 규율이다 — 근거
    없이 적힌 조건은 검증된 규칙이 아니라 추측이다.
    """

    card_id: int
    rank: int
    """카드 데이터의 ``level`` 칸 (엑시즈면 랭크). 데이터와 어긋나면 실측으로 잡힌다."""
    material_count: int
    """대체 절차가 요구하는 **고른 카드 장수.** ``ovfilter`` 쪽의 수다."""
    material_must_be_link: bool
    """``ovfilter`` 의 ``IsType(TYPE_LINK, …)``."""
    material_setcode_names: tuple[str, ...]
    """``ovfilter`` 의 ``IsSetCard(…)`` — 이름으로 적고 코드는 표에서 받는다."""
    spsummon_once: bool
    """``c:SetSPSummonOnce(id)`` — 같은 **이름**의 카드를 1턴에 1번만 특수 소환."""
    lua_file: str
    lua_excerpt: str
    note: str

    def describe_ko(self) -> str:
        bits = ["앞면"]
        if self.material_must_be_link:
            bits.append("링크 몬스터")
        if self.material_setcode_names:
            names = " · ".join(
                name[len("SET_"):] if name.upper().startswith("SET_") else name
                for name in self.material_setcode_names
            )
            bits.append(f"「{names}」")
        return (
            f"자신 필드의 {' '.join(bits)} {self.material_count}장을 소재로 "
            f"엑시즈 소환 (랭크 {self.rank})"
            + (" · 같은 이름의 카드는 1턴에 1번만 특수 소환"
               if self.spsummon_once else "")
        )


#: 🔴 **등재된 카드 전부.** 적히지 않은 엑시즈 몬스터는 공통 경로의
#: ``UNDETERMINED`` 에 그대로 막힌다 — 이 표가 범위를 좁게 적는 유일한
#: 자리다 (:data:`~engine.link_rules.LINK_MATERIAL_RULES` 와 같은 자리).
XYZ_ALTERNATIVE_RULES: tuple[XyzAlternativeRule, ...] = (
    XyzAlternativeRule(
        card_id=93854893,
        rank=8,
        material_count=1,
        material_must_be_link=True,
        material_setcode_names=("SET_ORCUST",),
        spsummon_once=True,
        lua_file="c93854893.lua",
        lua_excerpt=(
            "Xyz.AddProcedure(c,nil,8,2,s.ovfilter,aux.Stringid(id,0))  "
            "s.ovfilter = c:IsFaceup() and "
            "c:IsType(TYPE_LINK,xyzc,SUMMON_TYPE_XYZ,tp) and "
            "c:IsSetCard(SET_ORCUST,xyzc,SUMMON_TYPE_XYZ,tp)  "
            "c:SetSPSummonOnce(id)"
        ),
        note=(
            "시오르페골 딩기르수: 공식 텍스트 전문과 c93854893.lua 의"
            " Xyz.AddProcedure 를 읽었다. 「자신 필드의 「오르페골」 링크"
            " 몬스터 1장을 소재로 이 카드를 엑시즈 소환할 수도 있다」 쪽만"
            " 옮겼고, 기본 절차(레벨 8 몬스터 2장)는 옮기지 않았다."
            " 🔴 이 등재가 '이 카드를 전부 구현했다' 는 뜻은 아니다 —"
            " engine.xyz_rules.XYZ_BLIND_SPOTS 가 남은 것을 적는다."
        ),
    ),
)

_BY_CARD: dict[int, XyzAlternativeRule] = {
    rule.card_id: rule for rule in XYZ_ALTERNATIVE_RULES
}
if len(_BY_CARD) != len(XYZ_ALTERNATIVE_RULES):  # pragma: no cover - 방어
    raise ValueError("같은 카드를 두 줄로 적었습니다.")


def _resolve(names: tuple[str, ...]) -> tuple[int, ...]:
    """카드군 **이름**을 상수 표의 코드로. 🔴 못 찾으면 import 가 멈춘다."""
    if not names:
        return ()
    found = compile_archetype_condition(names)
    if found is None or found.unresolved or found.unread:
        raise ValueError(
            f"카드군 이름을 상수 표에서 찾지 못했습니다: {names} — "
            "추측한 코드를 적지 않습니다."
        )
    return tuple(code for _name, code in found.resolved)


#: 등재된 규칙마다 **미리 풀어 둔** 카드군 코드들.
_SETCODES: dict[int, tuple[int, ...]] = {
    rule.card_id: _resolve(rule.material_setcode_names)
    for rule in XYZ_ALTERNATIVE_RULES
}


def alternative_rule_for(card_id: "int | None") -> "XyzAlternativeRule | None":
    """그 카드의 대체 엑시즈 절차. **등재되지 않았으면 ``None``** (ADR-006)."""
    if card_id is None:
        return None
    return _BY_CARD.get(int(card_id))


def material_setcodes(rule: XyzAlternativeRule) -> tuple[int, ...]:
    """그 규칙이 요구하는 카드군 코드들 (import 때 풀어 둔 값)."""
    return _SETCODES[rule.card_id]


@dataclass(frozen=True, slots=True)
class XyzMaterialAssessment:
    """
    소재 판정 하나와 **그 근거.**

    ``unchecked`` 가 따로 있는 이유는 모듈 머리말에 있다 — 판정을 바꾸지
    않는 관찰과 판정을 막는 모름은 다른 사실이다.
    """

    eligibility: XyzMaterialEligibility
    reason: str
    missing_rule: "str | None" = None
    rule: "XyzAlternativeRule | None" = None
    slot: "int | None" = None
    """놓을 칸 (엑스트라 몬스터 존). ``LEGAL`` 일 때만 채워진다."""
    unchecked: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            self.eligibility is not XyzMaterialEligibility.UNDETERMINED
            and self.missing_rule is not None
        ):
            raise ValueError(
                "없는 규칙 이름은 UNDETERMINED 에만 붙습니다: "
                f"{self.eligibility} / {self.missing_rule}"
            )

    @property
    def permits_procedure(self) -> bool:
        return self.eligibility is XyzMaterialEligibility.LEGAL

    @property
    def is_refusal(self) -> bool:
        return self.eligibility is XyzMaterialEligibility.ILLEGAL

    def describe_ko(self) -> str:
        return f"{self.eligibility.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def _legal(rule: XyzAlternativeRule, slot: int) -> XyzMaterialAssessment:
    return XyzMaterialAssessment(
        XyzMaterialEligibility.LEGAL,
        f"{rule.card_id} 의 대체 소재 조건을 만족합니다 "
        f"({rule.describe_ko()}) — 엑스트라 몬스터 존 {slot}번 칸에 놓습니다.",
        rule=rule,
        slot=slot,
        unchecked=XYZ_BLIND_SPOTS,
    )


def _illegal(reason: str, rule=None) -> XyzMaterialAssessment:
    return XyzMaterialAssessment(
        XyzMaterialEligibility.ILLEGAL, reason, rule=rule
    )


def _undetermined(reason: str, missing: str, rule=None) -> XyzMaterialAssessment:
    return XyzMaterialAssessment(
        XyzMaterialEligibility.UNDETERMINED, reason, missing, rule=rule
    )


def assess_xyz_materials(
    view, actor: int, source: "InstanceId | None", materials: tuple[InstanceId, ...]
) -> XyzMaterialAssessment:
    """
    이 소재로 그 엑시즈 몬스터를 엑시즈 소환할 수 있는가.

    **관측만 읽는다** — 판을 바꾸지 않고 ``GameState`` 를 받지 않는다.
    검증기와 후보 생성기가 **이 함수 하나**를 부른다
    (:func:`~engine.link_rules.assess_link_materials` 와 같은 자리).

    순서가 뜻을 가진다.

    1. ``source`` 가 무엇인가 — 엑시즈 몬스터인가 · 엑스트라 덱에 있는가 ·
       내 카드인가. **먼저 본다**: 뒤로 미루면 "소재가 틀렸다" 가 "애초에
       엑시즈 몬스터가 아니다" 를 가린다.
    2. 그 카드의 **대체 절차**가 등재되었는가 (없으면 모름).
    3. 고른 **장수**가 대체 절차의 수인가 (아니면 **모름** — 기본 절차는
       옮기지 않았다).
    4. 고른 소재가 하나하나 조건을 만족하는가.
    5. 이 턴에 **그 이름을 이미 특수 소환했는가** (``SetSPSummonOnce``).
    6. 판에 걸린 **특수 소환 금지**가 막는가.
    7. 소재가 떠난 뒤 **놓을 칸**이 있는가.

    🔴 **7 이 마지막인 것이 뜻을 가진다.** 대체 절차는 엑스트라 몬스터 존의
    링크 몬스터를 소재로 먹으므로, 소재가 떠나면 그 칸이 **빈다.** 그래서
    "지금 비어 있는가" 를 물으면 언제나 거절이 된다 — 물어야 하는 것은
    "소재가 떠난 뒤 비는가" 다.
    """
    if source is None:
        return _illegal("소환할 엑시즈 몬스터가 지목되지 않았습니다.")

    card = view.find(source)
    if card is None:
        return _undetermined(
            f"{source} 가 관측에 보이지 않습니다.", XYZ_RULE_MISSING
        )
    definition = card.definition
    if definition is None:
        return _undetermined(
            f"{source} 의 카드 정의를 읽을 수 없어 엑시즈 몬스터인지 알 수 "
            "없습니다.",
            XYZ_RULE_MISSING,
        )
    if not definition.is_xyz:
        return _illegal(
            f"{source} 는 엑시즈 몬스터가 아닙니다 — 엑시즈 소환할 수 없습니다."
        )
    if card.zone not in XYZ_SUMMON_FROM_ZONES:
        allowed = " · ".join(sorted(z.value for z in XYZ_SUMMON_FROM_ZONES))
        return _illegal(
            f"{source} 가 {allowed} 에 없습니다 (현재 {card.zone.value}) — "
            "엑시즈 소환은 엑스트라 덱에서 꺼내는 것입니다."
        )
    if card.controller != actor:
        return _illegal(
            f"{source} 는 P{card.controller} 의 카드입니다 "
            f"(P{actor} 가 소환하려 했습니다)."
        )

    rule = alternative_rule_for(card.card_id)
    if rule is None:
        return _undetermined(
            f"{card.card_id} 의 엑시즈 소재 조건을 이 저장소가 아직 읽지 "
            "않았습니다.",
            XYZ_RULE_MISSING,
        )

    #: 3. 장수. 🔴 **"안 된다" 가 아니라 "모른다"** 다 — 기본 절차를
    #: 옮기지 않았으므로 그 장수로 가능한지 알 수 없다.
    if len(materials) != rule.material_count:
        return _undetermined(
            f"고른 소재가 {len(materials)}장입니다. 등재된 대체 절차는 "
            f"{rule.material_count}장이고, 기본 절차는 옮기지 않았습니다.",
            XYZ_BASE_PROCEDURE_RULE,
            rule=rule,
        )
    if len(set(materials)) != len(materials):
        return _illegal("같은 카드를 두 번 소재로 골랐습니다.", rule=rule)

    wanted = material_setcodes(rule)
    for instance in materials:
        held = view.find(instance)
        if held is None:
            return _undetermined(
                f"소재로 고른 {instance} 가 관측에 보이지 않습니다.",
                XYZ_RULE_MISSING,
                rule=rule,
            )
        if held.controller != actor:
            return _illegal(
                f"소재 {instance} 는 P{held.controller} 의 카드입니다 — "
                "자신 필드의 몬스터만 소재로 삼습니다.",
                rule=rule,
            )
        if held.zone not in XYZ_MATERIAL_ZONES:
            where = " · ".join(sorted(z.value for z in XYZ_MATERIAL_ZONES))
            return _illegal(
                f"소재 {instance} 가 {where} 에 없습니다 "
                f"(현재 {held.zone.value}).",
                rule=rule,
            )
        if not held.face_up:
            return _illegal(
                f"소재 {instance} 가 앞면이 아닙니다 — "
                "ovfilter 의 IsFaceup() 이 요구합니다.",
                rule=rule,
            )
        held_definition = held.definition
        if held_definition is None:
            return _undetermined(
                f"소재 {instance} 의 카드 정의를 읽을 수 없습니다.",
                XYZ_RULE_MISSING,
                rule=rule,
            )
        if rule.material_must_be_link and not held_definition.is_link:
            return _illegal(
                f"소재 {instance} 는 링크 몬스터가 아닙니다.", rule=rule
            )
        if wanted and not any(
            matches_setcode(held_definition.setcodes, code) for code in wanted
        ):
            names = " · ".join(rule.material_setcode_names)
            return _illegal(
                f"소재 {instance} 가 {names} 에 속하지 않습니다.", rule=rule
            )

    #: 5. 같은 이름을 이 턴에 이미 특수 소환했는가.
    if rule.spsummon_once and _spsummon_once_spent(view, actor, rule):
        return _illegal(
            "이 카드명은 1턴에 1번만 특수 소환할 수 있고 이 턴에 이미 "
            "특수 소환했습니다 (SetSPSummonOnce).",
            rule=rule,
        )

    #: 6. 판에 걸린 특수 소환 금지. 🔴 **판정을 다시 적지 않는다.**
    blocked = _permission_refusal(view, actor, definition)
    if blocked is not None:
        if blocked.forbidden:
            return _illegal(blocked.reason, rule=rule)
        return _undetermined(
            blocked.reason,
            blocked.missing_rule or XYZ_RULE_MISSING,
            rule=rule,
        )

    #: 7. 소재가 떠난 뒤 놓을 칸.
    slot = _free_slot_after(view, actor, materials)
    if slot is None:
        return _undetermined(
            "소재가 떠난 뒤에도 엑스트라 몬스터 존에 빈 칸이 없습니다 — "
            + XYZ_PLACEMENT_RULE,
            XYZ_PLACEMENT_RULE,
            rule=rule,
        )
    return _legal(rule, slot)


def _spsummon_once_spent(view, actor: int, rule: XyzAlternativeRule) -> bool:
    """
    이 턴에 그 **카드명**을 특수 소환했는가. 🔴 **관측만 읽는다.**

    ``GameStateView.summons_by_name`` 은 ``(seat, card_id, 소환법, 횟수)``
    들이다. 🔴 **소환법을 가리지 않고 센다** — ``SetSPSummonOnce`` 는
    「특수 소환」 전체에 걸리는 제한이고, 엑시즈 소환으로 나왔는지 다른
    효과로 나왔는지를 가리지 않는다.

    🔴 **적히지 않은 특수 소환은 보이지 않는다.** 효과 해결 중의 특수 소환은
    사용 기록에 남지 않으므로 (``SummonProcedure.plan_for`` 경로), 그 길로
    나온 같은 이름의 카드를 이 함수는 세지 못한다. 그 사실은
    :data:`XYZ_BLIND_SPOTS` 가 아니라 여기 적는다 — 판정을 바꾸는 모름이기
    때문이다.
    """
    rows = tuple(getattr(view, "summons_by_name", ()) or ())
    for row in rows:
        try:
            seat, card_id, _kind, count = row[0], row[1], row[2], row[3]
        except (TypeError, IndexError):  # pragma: no cover - 방어용
            continue
        if int(seat) != int(actor) or int(card_id) != int(rule.card_id):
            continue
        if int(count) >= 1:
            return True
    return False


def _permission_refusal(view, actor: int, definition):
    """
    판에 걸린 특수 소환 금지가 이 소환을 막는가. **판정하지 않는다** —
    :func:`~engine.summon_restriction.assess_special_summon_permission` 에게
    묻고 그 답을 그대로 돌려준다.
    """
    # 여기서 읽는다 — 두 판정 모듈이 서로를 모듈 최상단에서 읽으면 고리가
    # 생긴다 (``engine.hand_summon._restriction_verdict`` 와 같은 이유).
    from engine.summon_restriction import assess_special_summon_permission

    got = assess_special_summon_permission(view, actor, summoned=definition)
    return None if got.allowed else got


def _free_slot_after(
    view, actor: int, materials: tuple[InstanceId, ...]
) -> "int | None":
    """
    소재가 떠난 뒤 **엑스트라 몬스터 존에 남는 가장 작은 빈 칸.**

    🔴 소재가 차지하고 있던 칸을 **빈 칸으로 센다.** 대체 절차는 그
    칸의 링크 몬스터를 먹으므로, 세지 않으면 이 절차가 영영 막힌다.
    """
    chosen = set(materials)
    box = view.players[actor].zone(XYZ_SUMMON_TO_ZONE)
    if box is None:
        return None
    for index, held in enumerate(box.cards):
        if held is None or held.instance_id in chosen:
            return index
    return None


__all__ = [
    "XYZ_ALTERNATIVE_RULES",
    "XYZ_BASE_PROCEDURE_RULE",
    "XYZ_BLIND_SPOTS",
    "XYZ_MATERIAL_DESTINATION",
    "XYZ_MATERIAL_ZONES",
    "XYZ_PLACEMENT_RULE",
    "XYZ_RULE_MISSING",
    "XYZ_SUMMON_FROM_ZONES",
    "XYZ_SUMMON_POSITION",
    "XYZ_SUMMON_TO_ZONE",
    "XyzAlternativeRule",
    "XyzMaterialAssessment",
    "XyzMaterialEligibility",
    "alternative_rule_for",
    "assess_xyz_materials",
    "material_setcodes",
]
