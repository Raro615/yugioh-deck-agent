"""
Phase 6-AG (A) — **링크 소재의 장수와 기여의 합은 다른 수다.**

공식 규칙이 세 조건을 따로 적는다 (``rules`` 계층의
``sd-rulebook-en-v10``, RULE-MONSTER-005 / printed page 15) —
*"Remember that when you Link Summon, you need to meet 3 goals"*:

1. *"The amount of materials you use matches the Link Rating (Link
   Monsters count as 1 OR their own Link Rating)."*
2. *"The number of materials you use meets the number specified in the
   materials line or 'recipe'."*
3. *"The materials match any other requirements in the materials line."*

6-AF 는 1 과 2 를 **한 수로 비교했다**. 그래서 두 가지가 동시에 틀렸다:

- 기르수(기여 1) + 갈라테아(LINK-2) 로 **다른 갈라테아**를 소환하려 하면
  "소재가 3장" 이라며 거절했다 — 각 1 로 셀 수 있으므로 합법이다.
- 갈라테아 **한 장**이 다른 갈라테아의 「효과 몬스터 2장」 을 만족한다고
  판정했다 — 고른 카드가 1장이므로 둘째 조건을 어긴다.

이 파일의 **두 절을 구분해서 읽어야 한다.**

- **A 절 — 실제 카드 통합.** 실제 카드 데이터로 판을 만들고, 판정 ·
  후보 생성 · 실제 실행 **세 계층**이 같은 답을 내는지 본다.
- **B 절 — 합성 규칙 단위.** 등록된 두 카드는 ``count`` 와
  ``link_rating`` 이 **같다** (갈라테아 2·2, 갈라테아i 1·1). 소재 한 장의
  최소 기여가 1 이므로, 그 두 카드로는 **첫째 조건이 깨지는 판을 만들 수
  없다** (``count`` 장을 고르면 합이 최소 ``count`` = ``link_rating`` 이고
  그 값은 언제나 도달 가능하다). 그래서 "장수는 맞지만 기여의 합이 닿지
  않는다" 와 "중간값이 필요한 조합" 은 **실제 카드로 구성할 수 없고**,
  ``link_rating > count`` 인 **합성 규칙**으로만 잴 수 있다. B 절이 그
  시험들이고, production 등록표(:data:`LINK_MATERIAL_RULES`)는 건드리지
  않는다.
"""

import pytest

from engine.action import MalformedAction, PlayerAction, PlayerActionKind
from engine.duel import Duel, duel_components
from engine.link_rules import (
    LINK_MATERIAL_RULES,
    LINK_SUMMON_KIND,
    LinkMaterialEligibility,
    LinkMaterialRule,
    MaterialRequirement,
    assess_link_materials,
    material_contribution,
    material_contribution_options,
    material_rule_for,
    reachable_material_counts,
)
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

pytestmark = requires_official_db

GIRSU = 69811710
GALATEA = 30741503
GALATEA_I = 48835607
#: 오르페골 롱기르수 — **LINK-3 효과 몬스터이고 「오르페골」** 이다
#: (``test_b01`` 이 카드 데이터로 확인한다). 소재 조건은 등록하지 않았지만
#: (``2+`` 류) **소재로 쓰는 쪽**은 등록과 무관하다.
LONGIRSU = 76145142
FEATHERMAN = 21844576
P0, P1 = 0, 1


# ======================================================================
# 공용 — 시작 상태만 만든다
# ======================================================================
def _board(repository, *, mine=(), emzone=(), extra=(), turn_number=3):
    """
    **시작 상태**를 만든다. 이 뒤의 변화는 전부 엔진이 만든다.

    🔴 ``mine`` 은 메인 몬스터 존, ``emzone`` 은 엑스트라 몬스터 존이다.
    돌려주는 ``field`` 의 순서는 **``mine`` 다음 ``emzone``** 이고, 그것은
    후보 생성이 쓰는 순서(자리 이름 순 — ``emzone`` 이 먼저)와 **다르다**.
    그래서 소재를 고를 때는 :func:`_pick_link` 가 후보에서 찾는다.
    """
    state = GameState.create(
        repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )
    field = []
    for index, card_id in enumerate(mine):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    for index, card_id in enumerate(emzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.EMZONE)
        state.move(
            instance,
            Zone.EMZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    state.turn.turn_number = turn_number
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    return duel, field, extra_ids


def _offered(duel, source, materials):
    """**엔진이 낸 후보** 중 그 링크 소환. 없으면 ``None``."""
    duel.advance()
    want = set(materials)
    for action in duel.legal_actions(P0).allowed:
        if (
            action.kind is PlayerActionKind.LINK_SUMMON
            and action.source == source
            and set(action.materials) == want
        ):
            return action
    return None


def _pick_link(duel, source, materials):
    """
    후보에서 골라 **실제로 적용한다**.

    🔴 소재의 **순서**는 엔진이 정한다 — 손으로 만든 순서가 다르면
    ``Duel.apply`` 가 "허가된 행위가 아니다" 로 거절한다. 그 거절은 규칙의
    답이 아니라 "내가 낸 후보만 실행한다" 는 ``Duel`` 의 설계이므로,
    시험은 후보에서 찾아 넘긴다.
    """
    action = _offered(duel, source, materials)
    assert action is not None, f"후보에 없습니다: {source} ← {materials}"
    return duel.apply(action)


def _snapshot(duel):
    """판 · 소환 기록을 함께 뜬다 — 거절이 아무것도 바꾸지 않았는지 잰다."""
    state = duel.state
    turn = state.turn.turn_number
    return (
        state.state_hash(),
        tuple(
            state.summon_uses.count(turn, P0, card_id, LINK_SUMMON_KIND)
            for card_id in (GALATEA, GALATEA_I, LONGIRSU)
        ),
        tuple(
            tuple(card.card_id for card in state.zone(seat, zone))
            for seat in (P0, P1)
            for zone in (Zone.MZONE, Zone.EMZONE, Zone.GRAVE)
        ),
    )


# ======================================================================
# A. 실제 카드 통합 — 판정 · 후보 생성 · 실제 실행이 같은 답을 낸다
# ======================================================================


@pytest.mark.real_card
def test_a01_a_link_two_material_counted_as_one_summons_another_galatea(
    repository,
):
    """
    🔴 **기르수 + 갈라테아(LINK-2) → 다른 갈라테아** (재현 사례 1).

    - 고른 카드 **2장** = 갈라테아의 ``count`` → 둘째 조건 ✔
    - 기여는 ``1 + {1, 2}`` 이므로 합이 ``{2, 3}`` 이고 **2 에 닿는다**
      → 첫째 조건 ✔ (갈라테아를 **1 로 센다**)
    - 둘 다 효과 몬스터이고 둘 다 「오르페골」 → 셋째 조건 ✔

    6-AF 는 기여를 **링크 수치로만** 세어 ``1 + 2 = 3`` 을 ``count`` 2 와
    비교했고, 그래서 "소재가 3장입니다" 로 거절했다 — 후보 생성도 **0건**
    이었다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[GALATEA]
    )
    girsu, galatea_on_field = field
    materials = (girsu, galatea_on_field)

    #: 1. 판정 — 합법이다.
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason

    #: 2. 후보 생성 — 같은 조합이 실제로 **오른다** (6-AF 에서는 0건).
    action = _offered(duel, extra[0], materials)
    assert action is not None, [
        (w.code.value, w.reason)
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.LINK_SUMMON
    ]

    #: 3. 검증기 — 후보 생성이 쓰는 **그 검증기**가 같은 답을 낸다.
    validator = duel.activation_validator(P0)
    assert validator.validate(action).validity is ActionValidity.VALID

    #: 4. 실제 실행 — 소재는 묘지로, 갈라테아는 엑스트라 몬스터 존으로.
    step = duel.apply(action)
    assert step.accepted is True, step.reason
    assert [c.card_id for c in duel.state.zone(P0, Zone.EMZONE)] == [GALATEA]
    assert [c.card_id for c in duel.state.zone(P0, Zone.MZONE)] == []
    assert sorted(c.card_id for c in duel.state.zone(P0, Zone.GRAVE)) == sorted(
        [GALATEA, GIRSU]
    )


@pytest.mark.real_card
def test_a02_one_galatea_alone_never_satisfies_two_effect_monsters(repository):
    """
    🔴 **갈라테아 한 장으로는 다른 갈라테아를 소환할 수 없다** (재현 사례 2).

    기여만 보면 ``{1, 2}`` 이고 2 에 닿는다 — 첫째 조건은 만족한다. 그런데
    **둘째 조건**이 「효과 몬스터 2장」 이고 고른 카드는 1장이므로 규칙이
    막는다.

    🔴 6-AF 는 이것을 ``LEGAL`` 로 판정했다. ``Duel.apply`` 는 **다른
    검사**(후보에 그 조합이 없다)로 거절했으므로 한 장 소환이 실제로
    적용된 적은 없지만, **판정 계층과 실행 계층의 답이 달랐다** — 이
    시험이 그 불일치를 막는다.
    """
    #: 다른 몬스터가 **필드에 있어도** 소재로 고르지 않으면 거절이다.
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[GALATEA]
    )
    girsu, galatea_on_field = field
    before = _snapshot(duel)

    alone = assess_link_materials(
        duel.view(P0), P0, extra[0], (galatea_on_field,)
    )
    assert alone.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "1장" in alone.reason and "2장" in alone.reason
    assert alone.missing_rule is None, "장수 위반은 모름이 아니다"

    #: 후보 생성도 그 한 장 조합을 **만들지 않는다** (장수가 2이므로).
    assert _offered(duel, extra[0], (galatea_on_field,)) is None

    #: 실행 경로도 거절하고 **판은 그대로다**.
    step = duel.apply(
        PlayerAction.link_summon(P0, extra[0], (galatea_on_field,))
    )
    assert step.accepted is False
    assert _snapshot(duel) == before

    #: 같은 판에서 **두 장**을 고르면 합법이다 — 거절의 이유가 장수였다는
    #: 것을 이 대조가 못 박는다.
    two = assess_link_materials(
        duel.view(P0), P0, extra[0], (girsu, galatea_on_field)
    )
    assert two.eligibility is LinkMaterialEligibility.LEGAL

    #: 필드에 **그 한 장만** 있는 판도 같은 답이다.
    lonely, lonely_field, lonely_extra = _board(
        repository, emzone=(GALATEA,), extra=[GALATEA]
    )
    only = assess_link_materials(
        lonely.view(P0), P0, lonely_extra[0], (lonely_field[0],)
    )
    assert only.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "1장" in only.reason


@pytest.mark.real_card
def test_a03_a_link_three_material_counted_as_one_is_legal(repository):
    """
    🔴 **롱기르수(LINK-3) + 기르수 → 갈라테아** — "1 로 세는 길" 이 실제
    카드로 열린다.

    고른 카드 2장 ✔ · 기여 ``{1, 3} + {1}`` → 합 ``{2, 4}`` 이고 2 에
    닿는다 ✔ · 둘 다 효과 몬스터이고 「오르페골」 ✔.

    6-AF 는 ``3 + 1 = 4`` 를 ``count`` 2 와 비교해 "소재가 4장" 으로
    거절했다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(LONGIRSU,), extra=[GALATEA]
    )
    materials = (field[0], field[1])
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason

    step = _pick_link(duel, extra[0], materials)
    assert step.accepted is True, step.reason
    assert [c.card_id for c in duel.state.zone(P0, Zone.EMZONE)] == [GALATEA]
    assert sorted(c.card_id for c in duel.state.zone(P0, Zone.GRAVE)) == sorted(
        [LONGIRSU, GIRSU]
    )


@pytest.mark.real_card
def test_a04_a_single_link_three_is_refused_by_the_card_count(repository):
    """
    🔴 **롱기르수 한 장으로는 갈라테아를 소환할 수 없다.**

    기여를 3 으로 세면 첫째 조건은 넘지만 고른 카드가 1장이므로 **둘째
    조건**이 막는다. 거절 문장이 **장수**를 말해야 한다 — 6-AF 는 "소재가
    3장입니다" 라고 적었고, 그것은 기여를 장수로 읽은 문장이다.
    """
    duel, field, extra = _board(
        repository, emzone=(LONGIRSU,), extra=[GALATEA]
    )
    before = _snapshot(duel)
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], (field[0],))
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "1장" in verdict.reason, verdict.reason
    assert "3장" not in verdict.reason, (
        "기여 3 을 장수로 적으면 6-AF 의 혼용이 문장에 남는다: "
        + verdict.reason
    )
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_a05_the_same_monster_cannot_be_counted_twice(repository):
    """
    🔴 **같은 몬스터를 소재로 두 번 셀 수 없다** — 소재는 필드를 떠난다.

    :class:`~engine.action.PlayerAction` 이 이미 막지만, 판정 함수를
    **직접** 부르는 길에는 그 관문이 없었다 — 6-AF 에서
    ``(기르수, 기르수)`` 는 고른 카드 2장 · 기여 2 로 **``LEGAL``** 이었다.
    """
    duel, field, extra = _board(repository, mine=(GIRSU,), extra=[GALATEA])
    duplicate = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[0])
    )
    assert duplicate.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "두 번" in duplicate.reason

    #: 행동 자료형도 같은 답이다 — 두 관문이 어긋나지 않는다.
    with pytest.raises(MalformedAction):
        PlayerAction.link_summon(P0, extra[0], (field[0], field[0]))


@pytest.mark.real_card
def test_a06_a_refusal_changes_nothing_at_all(repository):
    """
    🔴 **거절은 아무것도 바꾸지 않는다** — 소재 이동 · 소환 기록 · 턴당
    사용 제한 전부 그대로다.

    장수 위반 · 중복 · 소재 조건 위반을 한 판에서 차례로 거절시키고,
    :func:`_snapshot` (판 해시 + 링크 소환 횟수 + 각 자리의 카드)이 **한
    번도 움직이지 않는지** 본다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[GALATEA, GALATEA_I]
    )
    girsu, galatea_on_field = field
    before = _snapshot(duel)

    refusals = [
        #: 장수 — 1장 (갈라테아는 2장)
        assess_link_materials(duel.view(P0), P0, extra[0], (girsu,)),
        #: 장수 — 2장 (갈라테아i 는 1장)
        assess_link_materials(
            duel.view(P0), P0, extra[1], (girsu, galatea_on_field)
        ),
        #: 중복
        assess_link_materials(duel.view(P0), P0, extra[0], (girsu, girsu)),
    ]
    for verdict in refusals:
        assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL

    duel.advance()
    for materials in ((girsu,), (girsu, galatea_on_field)):
        step = duel.apply(PlayerAction.link_summon(P0, extra[0], materials))
        assert step.accepted is False
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_a07_the_registered_rules_still_match_the_card_data(repository):
    """
    🔴 **등록한 두 수가 카드 데이터와 어긋나지 않는다.**

    ``count`` 는 ``Link.AddProcedure`` 의 장수이고 ``link_rating`` 은 카드
    데이터의 링크 수치다. 두 수가 **같은 카드만** 등록되어 있는 것이 지금의
    사실이고 (B 절의 머리말이 그 결과를 적는다), 그 사실이 바뀌면 이 시험이
    먼저 깨진다.
    """
    assert [rule.card_id for rule in LINK_MATERIAL_RULES] == [
        GALATEA,
        GALATEA_I,
    ]
    for rule in LINK_MATERIAL_RULES:
        definition = repository.get(rule.card_id)
        assert definition.is_link is True
        assert definition.link_rating == rule.link_rating, rule.card_id
        #: 🔴 지금은 둘이 같다. **같아야 한다는 규칙은 아니다** — 공식
        #: 규칙은 두 수를 따로 세고, 이 단언은 "지금 등록된 것이 전부
        #: 그렇다" 는 **관찰**이다 (B 절이 다른 경우를 합성으로 잰다).
        assert rule.link_rating == rule.count, rule.card_id


# ======================================================================
# B. 합성 규칙 단위 — ``link_rating > count`` 는 실제 카드로 만들 수 없다
# ======================================================================


@pytest.mark.real_card
def test_b01_the_contribution_options_come_from_the_card_data(repository):
    """
    🔴 **기여는 집합이고, 사이의 값은 없다.**

    - 일반 · 효과 몬스터 → ``{1}``
    - LINK-1 → ``{1}`` (두 값이 같다)
    - LINK-2 → ``{1, 2}`` · LINK-3 → ``{1, 3}`` — **2 는 없다**
    - 읽을 수 없으면 ``None`` — ``{1}`` 로 접지 않는다
    """
    assert material_contribution_options(repository.get(GIRSU)) == frozenset(
        {1}
    )
    assert material_contribution_options(
        repository.get(GALATEA_I)
    ) == frozenset({1})
    assert material_contribution_options(repository.get(GALATEA)) == frozenset(
        {1, 2}
    )
    assert material_contribution_options(
        repository.get(LONGIRSU)
    ) == frozenset({1, 3})
    assert material_contribution_options(None) is None

    #: 롱기르수를 소재로 쓰는 쪽은 **등록과 무관하다** — 소재 조건이
    #: 등록되지 않은 카드도 소재로는 쓸 수 있다.
    assert material_rule_for(LONGIRSU) is None
    longirsu = repository.get(LONGIRSU)
    assert "EFFECT" in longirsu.type_names
    assert 0x11B in longirsu.setcodes

    #: :func:`material_contribution` 은 **최대 기여**다 — 판정이 쓰지 않는다.
    assert material_contribution(repository.get(GIRSU)) == 1
    assert material_contribution(repository.get(GALATEA)) == 2
    assert material_contribution(repository.get(LONGIRSU)) == 3
    assert material_contribution(None) is None


def test_b02_the_reachable_sums_are_a_product_of_choices():
    """
    🔴 **합의 집합은 선택들의 곱이다** — 순수 함수로 잰다.

    ``{1} + {1,2}`` → ``{2, 3}`` 이고, ``{1} + {1,3}`` → ``{2, 4}`` 다.
    **``{1}+{1,3}`` 에 3 이 없다** — 그것이 "중간값을 허용하지 않는다" 의
    전부다.
    """
    one, link2, link3 = frozenset({1}), frozenset({1, 2}), frozenset({1, 3})

    assert reachable_material_counts(()) == frozenset({0})
    assert reachable_material_counts((one,)) == frozenset({1})
    assert reachable_material_counts((link2,)) == frozenset({1, 2})
    assert reachable_material_counts((one, link2)) == frozenset({2, 3})
    assert reachable_material_counts((one, link3)) == frozenset({2, 4})
    assert 3 not in reachable_material_counts((one, link3))
    #: ``{1,2} + {1,3}`` → ``1+1 · 1+3 · 2+1 · 2+3`` = ``{2, 3, 4, 5}``.
    assert reachable_material_counts((link2, link3)) == frozenset({2, 3, 4, 5})
    assert reachable_material_counts((one, one, one)) == frozenset({3})


def _synthetic_rule(*, count: int, link_rating: int) -> LinkMaterialRule:
    """
    **합성 규칙** — 실제 카드로는 만들 수 없는 짝 (``link_rating > count``).

    🔴 :data:`LINK_MATERIAL_RULES` 에 **넣지 않는다.** production 등록표는
    그대로이고, 이 값은 아래 시험들이 ``monkeypatch`` 로 **그 시험 동안만**
    끼운다. ``lua_file`` · ``lua_excerpt`` 는 자료형이 요구하므로 채우지만
    **합성이라고 적는다** — 근거 없는 조건을 실제 등록처럼 보이게 하지
    않는다.
    """
    return LinkMaterialRule(
        card_id=GALATEA,
        link_rating=link_rating,
        count=count,
        each=MaterialRequirement(effect_monster=True),
        includes=MaterialRequirement(setcodes=(0x11B,)),
        text_ko=f"[합성] 효과 몬스터 {count}장 (「오르페골」 몬스터를 포함)",
        lua_file="[합성 — 실제 스크립트가 아니다]",
        lua_excerpt=(
            "[합성] Link.AddProcedure(c,...,"
            f"{count},{count}) / link_rating={link_rating}"
        ),
        note=(
            "Phase 6-AG 의 단위 시험 전용. 등록된 실제 카드는 count 와 "
            "link_rating 이 같아서 첫째 조건이 깨지는 판을 만들 수 없다."
        ),
    )


@pytest.mark.real_card
def test_b03_the_right_card_count_with_an_unreachable_sum_is_refused(
    repository, monkeypatch
):
    """
    🔴 **장수는 맞지만 기여의 합이 목표에 닿지 않으면 거절한다**
    (필수 회귀 사례 3) — **합성 규칙**이다 (B 절 머리말).

    ``count=2 · link_rating=3`` 인 규칙에 **일반 효과 몬스터 둘**을 주면
    합이 ``{2}`` 뿐이고 3 에 닿지 않는다.
    """
    import engine.link_rules as link_rules

    synthetic = _synthetic_rule(count=2, link_rating=3)
    monkeypatch.setitem(link_rules._RULES_BY_CARD, GALATEA, synthetic)
    assert material_rule_for(GALATEA) is synthetic

    duel, field, extra = _board(
        repository, mine=(GIRSU, GIRSU), extra=[GALATEA]
    )
    before = _snapshot(duel)
    verdict = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[1])
    )
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "기여" in verdict.reason and "3" in verdict.reason
    assert verdict.missing_rule is None, "도달 불가는 모름이 아니다"
    #: 🔴 **장수 때문이 아니다** — 장수는 통과했다는 것을 문장이 말해야 한다.
    assert "2장입니다" not in verdict.reason, verdict.reason

    #: 같은 규칙에서 **LINK-2 를 2 로 세면** 3 에 닿는다 → 합법이다.
    legal_duel, legal_field, legal_extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[GALATEA]
    )
    reachable = assess_link_materials(
        legal_duel.view(P0),
        P0,
        legal_extra[0],
        (legal_field[0], legal_field[1]),
    )
    assert reachable.eligibility is LinkMaterialEligibility.LEGAL

    #: 실행 경로도 거절하고 판은 그대로다.
    duel.advance()
    step = duel.apply(
        PlayerAction.link_summon(P0, extra[0], (field[0], field[1]))
    )
    assert step.accepted is False
    assert step.code is ValidationCode.LINK_MATERIAL_INVALID
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_b04_an_in_between_link_value_is_never_allowed(
    repository, monkeypatch
):
    """
    🔴 **링크 수치 사이의 임의 중간값을 쓰지 않는다** (필수 회귀 사례 4) —
    **합성 규칙**이다.

    ``count=2 · link_rating=3`` 에 **일반 효과 몬스터 + LINK-3** 을 주면
    합이 ``{2, 4}`` 다. 3 을 만들려면 LINK-3 을 **2 로** 세야 하는데 공식
    규칙은 "1 또는 자신의 링크 수치" 만 허용한다.
    """
    import engine.link_rules as link_rules

    monkeypatch.setitem(
        link_rules._RULES_BY_CARD, GALATEA, _synthetic_rule(count=2, link_rating=3)
    )
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(LONGIRSU,), extra=[GALATEA]
    )
    verdict = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[1])
    )
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "2 · 4" in verdict.reason, verdict.reason
    assert "사이의 값은 없습니다" in verdict.reason

    #: 🔴 **같은 소재로 목표가 4 라면 합법이다** — 거절의 이유가 "소재가
    #: 나쁘다" 가 아니라 "3 에 닿을 수 없다" 였음을 못 박는다.
    monkeypatch.setitem(
        link_rules._RULES_BY_CARD, GALATEA, _synthetic_rule(count=2, link_rating=4)
    )
    four = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[1])
    )
    assert four.eligibility is LinkMaterialEligibility.LEGAL, four.reason


def test_b05_a_rule_whose_rating_is_below_its_count_cannot_be_registered():
    """
    🔴 **달성할 수 없는 등록을 자료형이 막는다.**

    소재 한 장의 최소 기여가 1 이므로 ``count`` 장으로 만들 수 있는 합은
    최소 ``count`` 다. ``link_rating < count`` 인 줄은 **어떤 조합도 소환할
    수 없는** 줄이고, 그것이 조용히 등록되면 "그 카드는 소환할 수 없다" 가
    규칙이 아니라 오타로 들어온다.
    """
    with pytest.raises(ValueError, match="보다 작습니다"):
        _synthetic_rule(count=3, link_rating=2)

    #: 같은 수와 더 큰 수는 등록된다.
    assert _synthetic_rule(count=2, link_rating=2).link_rating == 2
    assert _synthetic_rule(count=2, link_rating=3).link_rating == 3


@pytest.mark.real_card
def test_b06_an_unreadable_link_rating_stays_unknown(repository, monkeypatch):
    """
    🔴 **링크 수치를 못 읽으면 ``UNDETERMINED``** — 거절도 허가도 아니다.

    기여를 셀 수 없으면 첫째 조건을 판정할 수 없다. 그때 ``{1}`` 로 접으면
    (링크 몬스터를 조용히 1 로 세는 것) 합법이 되고, 빈 집합으로 접으면
    확정 거절이 된다 — 둘 다 모름을 답으로 바꾼다 (ADR-006).

    🔴 **둘째 · 셋째 조건은 먼저 통과했다.** 그래서 이 모름이 장수 위반을
    가리지 않는다.
    """
    from engine.link_rules import LINK_RATING_UNREADABLE_RULE

    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[GALATEA]
    )

    #: 소재로 쓴 갈라테아의 링크 수치만 읽지 못하게 한다.
    real = material_contribution_options

    def blind(definition):
        if definition is not None and getattr(definition, "is_link", False):
            return None
        return real(definition)

    monkeypatch.setattr(
        "engine.link_rules.material_contribution_options", blind
    )
    verdict = assess_link_materials(
        duel.view(P0), P0, extra[0], (field[0], field[1])
    )
    assert verdict.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert verdict.missing_rule == LINK_RATING_UNREADABLE_RULE

    #: 같은 모름에서도 **장수 위반은 확정 거절로 남는다.**
    short = assess_link_materials(duel.view(P0), P0, extra[0], (field[1],))
    assert short.eligibility is LinkMaterialEligibility.ILLEGAL
