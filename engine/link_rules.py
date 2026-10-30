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

#: 링크 몬스터를 소재로 쓰면 그 링크 수치만큼 센다 (공식 규칙).
LINK_MATERIAL_AS_LINK_RULE: str = (
    "link-material-link-rating (링크 몬스터를 소재로 쓰면 링크 수치만큼 센다)"
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
LINK_BLIND_SPOTS: tuple[str, ...] = (
    f"{LINK_MATERIAL_BAN_RULE} 를 확인하지 않았습니다 — 그 제약을 적는 "
    "자리가 판에 없습니다.",
)


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
    """카드 데이터의 링크 수치. 등록과 데이터가 어긋나면 실측으로 잡힌다."""
    count: int
    """**정확히** 이 장수다. ``2+`` 류는 아직 적을 수 없다 (아래 설명)."""
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
)

_RULES_BY_CARD: dict[int, LinkMaterialRule] = {
    rule.card_id: rule for rule in LINK_MATERIAL_RULES
}
assert len(_RULES_BY_CARD) == len(LINK_MATERIAL_RULES), (
    "같은 카드의 소재 조건이 두 번 적혀 있습니다 — 어느 쪽이 이기는지 말할 "
    "수 없습니다."
)


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
    """
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

    rule = material_rule_for(definition.card_id)
    if rule is None:
        return _undetermined(
            f"{definition.card_id} 의 소재 조건을 이 저장소가 아직 읽지 "
            "않았습니다. 장수와 링크 수치만 맞춰 통과시키지 않습니다.",
            LINK_MATERIAL_RULE_MISSING,
        )

    if len(materials) != rule.count:
        return _illegal(
            f"소재가 {len(materials)}장입니다 — {rule.card_id} 는 "
            f"{rule.describe_ko()} 입니다.",
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
        #: 🔴 **링크 몬스터를 소재로 쓰는 것은 아직 옮기지 못했다** — 그때
        #: 링크 수치만큼 세므로 장수 계산이 달라진다 (모듈 머리말).
        if material_definition.is_link:
            return _undetermined(
                f"{instance} 가 링크 몬스터입니다 — 그때 소재 장수를 링크 "
                "수치로 세는 규칙을 아직 옮기지 못했습니다.",
                LINK_MATERIAL_AS_LINK_RULE,
                rule,
            )
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

    placement = assess_link_placement(view, actor, materials)
    if placement is not None:
        return placement

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




__all__ = [
    "LINK_BLIND_SPOTS",
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
    "MaterialRequirement",
    "assess_link_materials",
    "assess_link_placement",
    "material_rule_for",
]
