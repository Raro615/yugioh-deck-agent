"""
Phase 6-BK — 「성유물－『성관』」 을 **언제 패에서 낼 수 있는가**.

이 파일이 지키는 것
-------------------
A. :mod:`engine.link_zone` 이 **정렬 하나를 고르지 않는다** — 가능한 정렬
   전부를 보고 ``TRUE`` / ``FALSE`` / ``UNKNOWN`` 을 가른다.
B. 기준 전개의 **네 시점**에서 그 답이 실제로 무엇인가 (실측).
C. 성관이 필드에 선 판에서 **엔진의 링크 소재 판정**이 무엇을 허락하는가 —
   성관이 여는 후속이 무엇인지는 이 저장소의 판정이 답해야 한다.
D. 🔴 **아직 등재되지 않은 것** — 성관의 소환 **절차**다. 그 사실을 수로
   못박아 두어, 등재되는 날 이 시험이 먼저 깨지게 한다.

🔴 **정렬을 시험이 고르지 않는다.** C 묶음은 두 정렬을 **모두** 돌려
같은 전개가 나오는 것을 센다 — 그래야 :data:`~engine.link_zone.
MODELLED_ALIGNMENT` 가 결과를 바꾸지 않는다는 말이 측정이 된다.
"""

from pathlib import Path

import pytest

from engine.effect.ruling import ConditionResult
from engine.vocabulary import Phase, Position, Zone

GIRSU = 69811710
CYMBAL_SKELETON = 21441617
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
CROWN = 27918365

CARDS_CDB = Path(__file__).resolve().parent.parent / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="cards.cdb 없음"
)


def _view(state):
    from engine.game_state_view import GameStateView

    return GameStateView.from_state(state, viewer=0)


def _blank(repository):
    from engine.state.game_state import GameState

    state = GameState.create(
        repository, decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=0, seed=1, shuffle=False,
    )
    state.turn.turn_number = 1
    state.turn.set_phase(Phase.MAIN1)
    return state


def _place(state, card_id, zone, index, position):
    inst = state.create_instance(card_id, owner=0, zone=Zone.EXTRA)
    state.move(inst, zone, to_player=0, index=index, position=position)
    return inst


# ======================================================================
# A. 계층이 정렬을 고르지 않는다
# ======================================================================


def test_a01_the_alignments_are_two_and_neither_is_a_rule():
    """🔴 가능한 정렬이 **둘**이고, 어느 쪽도 룰북에서 읽은 것이 아니다."""
    from engine.link_zone import (
        EMZ_ALIGNMENTS, MODELLED_ALIGNMENT, POINTED_ZONE_SOURCE_GAP,
    )

    #: 🔴 수가 움직이면 이 Phase 를 다시 읽는다 — 룰북 §17 이 "둘 중
    #: 하나를 고를 수 있다" 고 적으므로 **둘이라는 사실만** 읽었다.
    assert len(EMZ_ALIGNMENTS) == 2
    assert MODELLED_ALIGNMENT in EMZ_ALIGNMENTS
    #: 🔴 **출처가 없다는 사실을 글자로 들고 있다.** 이 문장이 사라지면
    #: 누군가 정렬을 규칙으로 승격시킨 것이다.
    assert "출처" in POINTED_ZONE_SOURCE_GAP or "없습니다" in POINTED_ZONE_SOURCE_GAP
    assert "aux.GetMMZonesPointedTo" in POINTED_ZONE_SOURCE_GAP


@requires_official_db
@pytest.mark.real_card
def test_a02_no_link_monster_is_a_definite_no(repository):
    """🔴 링크 몬스터가 없으면 **정렬을 몰라도** 답이 난다 — ``FALSE``."""
    from engine.link_zone import pointed_zone_verdict

    state = _blank(repository)
    _place(state, GIRSU, Zone.MZONE, 0, Position.FACEUP_ATTACK)
    got = pointed_zone_verdict(_view(state), 0)
    assert got.answer is ConditionResult.FALSE, got.describe_ko()
    assert got.slots == ()
    #: 🔴 근거를 정렬마다 들고 있다 — 둘 다 빈 목록이어야 한다.
    assert [slots for _n, slots in got.per_alignment] == [(), ()]


@requires_official_db
@pytest.mark.real_card
def test_a03_a_full_board_is_a_definite_no(repository):
    """가리켜지는 칸이 있어도 **빈 칸이 아니면** 놓을 수 없다."""
    from engine.link_zone import pointed_zone_verdict

    state = _blank(repository)
    _place(state, GALATEA, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    for index in range(5):
        _place(state, GIRSU, Zone.MZONE, index, Position.FACEUP_ATTACK)
    got = pointed_zone_verdict(_view(state), 0)
    assert got.answer is ConditionResult.FALSE, got.describe_ko()


@requires_official_db
@pytest.mark.real_card
def test_a04_an_alignment_dependent_board_is_unknown_not_permission(repository):
    """
    🔴 **정렬에 따라 갈리면 ``UNKNOWN``** 이고, 그것은 허가가 아니다
    (ADR-006).

    갈라테아i(링크1 · 좌하) 하나에 칸 0 과 칸 1 이 막힌 판이다. EMZ 가
    왼쪽이면 좌하가 칸 0 을 가리켜 막히고, 오른쪽이면 칸 2 를 가리켜 빈다.
    """
    from engine.link_zone import pointed_zone_verdict

    state = _blank(repository)
    _place(state, GALATEA_I, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    _place(state, GIRSU, Zone.MZONE, 0, Position.FACEUP_ATTACK)
    _place(state, GIRSU, Zone.MZONE, 1, Position.FACEUP_ATTACK)
    got = pointed_zone_verdict(_view(state), 0)
    assert got.answer is ConditionResult.UNKNOWN, got.describe_ko()
    #: 한쪽은 비고 한쪽은 막힌다 — 그래서 갈린다.
    kinds = {bool(slots) for _n, slots in got.per_alignment}
    assert kinds == {True, False}, got.describe_ko()


@requires_official_db
@pytest.mark.real_card
def test_a05_a_bottom_left_on_an_empty_row_is_a_definite_yes(repository):
    """
    🔴 **모든 정렬에서 빈 칸이 있으면 ``TRUE``** — 번호는 서로 달라도 된다.

    이 시험이 지키는 사실은 "**존재**가 확정되고 **번호**는 확정되지
    않는다" 다. 그래서 번호가 아니라 ``answer`` 를 센다.
    """
    from engine.link_zone import pointed_zone_verdict

    state = _blank(repository)
    _place(state, GALATEA, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    got = pointed_zone_verdict(_view(state), 0)
    assert got.answer is ConditionResult.TRUE, got.describe_ko()
    #: 🔴 두 정렬이 **서로 다른 번호**를 가리킨다 — 그래서 번호를 요구하면
    #: 이 판도 거절된다. 그 사실을 여기서 못박는다.
    pointed = [slots for _n, slots in got.per_alignment]
    assert all(pointed), pointed
    assert pointed[0] != pointed[1], pointed


@requires_official_db
@pytest.mark.real_card
def test_a06_a_link_monster_in_the_monster_row_points_sideways_only(repository):
    """
    메인 몬스터 존에 선 링크 몬스터는 **아래 계열로 내 칸을 가리키지
    않는다** — 내 몬스터 줄 아래는 필드 밖이다. 갈라테아i(좌하만) 는
    그래서 아무 칸도 가리키지 않는다.
    """
    from engine.link_zone import EMZ_ALIGNMENTS, pointed_zones

    state = _blank(repository)
    _place(state, GALATEA_I, Zone.MZONE, 2, Position.FACEUP_ATTACK)
    for name in EMZ_ALIGNMENTS:
        assert pointed_zones(_view(state), 0, name) == {}, name


# ======================================================================
# B. 기준 전개의 네 시점 (실측)
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_b01_the_four_decision_points_split_two_and_two(repository):
    """
    🔴 **기준 전개에서 성관을 놓을 수 있는 첫 시점은 「갈라테아 링크 소환
    직후」** 다 (실측).

    =====================================  ========
    시점                                     답
    =====================================  ========
    성관을 가져온 직후 (갈라테아i 링크1)       UNKNOWN
    **갈라테아 링크 소환 직후**               **TRUE**
    갈라테아i 소생 직후                       UNKNOWN
    롱기르수 링크 소환 직후                   **TRUE**
    =====================================  ========
    """
    from engine.link_zone import pointed_zone_verdict
    from tests.test_galatea_effect_extension import (
        _advance_to_open, _is, _setup, _take,
    )

    duel = _setup(repository, prefer=(CROWN, CYMBAL_SKELETON)).duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(GIRSU, 2)), "기르수 ③")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87, "갈라테아i")
    _take(duel, _is("activate_effect", effect=(CYMBAL_SKELETON, 0)), "스켈레촌 ①")
    _take(duel, _is("activate_effect", effect=(GALATEA_I, 2)), "갈라테아i ②")

    #: 성관이 실제로 패에 들어왔다 — 그 전제가 깨지면 아래는 뜻이 없다.
    hand = [c.card_id for c in duel.state.zone(0, Zone.HAND).cards()]
    assert CROWN in hand, hand

    first = pointed_zone_verdict(_view(duel.state), 0)
    assert first.answer is ConditionResult.UNKNOWN, first.describe_ko()

    _take(duel, lambda k: k[0] == "link_summon" and k[2] in (83, 84), "갈라테아")
    second = pointed_zone_verdict(_view(duel.state), 0)
    assert second.answer is ConditionResult.TRUE, second.describe_ko()

    _take(duel, _is("activate_effect", effect=(GALATEA_I, 4)), "갈라테아i ③")
    third = pointed_zone_verdict(_view(duel.state), 0)
    assert third.answer is ConditionResult.UNKNOWN, third.describe_ko()

    legal = _advance_to_open(duel)
    assert any(a.canonical_state()[0] == "link_summon"
               and a.canonical_state()[2] == 91 for a in legal.allowed)
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 91, "롱기르수")
    fourth = pointed_zone_verdict(_view(duel.state), 0)
    assert fourth.answer is ConditionResult.TRUE, fourth.describe_ko()


# ======================================================================
# C. 성관이 여는 후속 — 엔진의 링크 소재 판정이 답한다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
@pytest.mark.parametrize("alignment", ["EMZ 왼쪽", "EMZ 오른쪽"])
def test_c01_longirsu_accepts_galatea_and_the_crown(repository, alignment):
    """
    🔴 **성관이 여는 후속은 롱기르수다** — 갈라테아(링크2, 기여 2) + 성관
    (기여 1) 로 기여 합 3 · 고른 카드 2장이고, 「오르페골」 은 갈라테아가
    댄다. 🔴 **두 정렬 모두** 돌려 같은 답이 나오는 것을 센다.
    """
    from engine.link_rules import assess_link_materials
    from engine.link_zone import EMZ_ALIGNMENTS, pointed_zones

    state = _blank(repository)
    galatea = _place(state, GALATEA, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    #: 성관을 **그 정렬이 가리키는 빈 칸**에 놓는다 — 자리를 임의로 고르지
    #: 않는다. 가리키는 칸이 비어 있다는 것은 A 묶음이 센다.
    slot = min(pointed_zones(_view(state), 0, alignment))
    assert slot in set(state.zone(0, Zone.MZONE).free_slots())
    crown = state.create_instance(CROWN, owner=0, zone=Zone.HAND)
    state.move(crown, Zone.MZONE, to_player=0, index=slot,
               position=Position.FACEUP_DEFENSE)
    longirsu = state.create_instance(LONGIRSU, owner=0, zone=Zone.EXTRA)

    got = assess_link_materials(
        _view(state), 0, longirsu.instance_id,
        (galatea.instance_id, crown.instance_id),
    )
    assert got.permits_procedure, f"{alignment}: {got.reason}"
    assert EMZ_ALIGNMENTS[alignment] in (1, 3)


@requires_official_db
@pytest.mark.real_card
def test_c02_the_crown_alone_cannot_make_longirsu(repository):
    """대조 — 성관 한 장은 장수 조건에 못 미친다 (조용히 통과하지 않는다)."""
    from engine.link_rules import assess_link_materials

    state = _blank(repository)
    crown = state.create_instance(CROWN, owner=0, zone=Zone.HAND)
    state.move(crown, Zone.MZONE, to_player=0, index=0,
               position=Position.FACEUP_DEFENSE)
    longirsu = state.create_instance(LONGIRSU, owner=0, zone=Zone.EXTRA)
    got = assess_link_materials(
        _view(state), 0, longirsu.instance_id, (crown.instance_id,)
    )
    assert not got.permits_procedure
    assert "1장" in got.reason, got.reason


@requires_official_db
@pytest.mark.real_card
def test_c03_the_crown_is_a_defense_position_summon(repository):
    """
    공식 텍스트와 Lua 가 **수비 표시**로 못박는다 —
    ``e1:SetTargetRange(POS_FACEUP_DEFENSE,0)``. 그 사실을 카드 텍스트에서
    확인한다 (등재되지 않은 것을 등재된 것처럼 적지 않는다).
    """
    card = repository.get(CROWN)
    assert card is not None
    text = (card.desc_en or card.desc or "")
    assert "Defense Position" in text, text[:200]
    assert "a Link Monster points to" in text, text[:200]
    assert "once per turn" in text, text[:200]


# ======================================================================
# D. 등재된 것과 **아직 등재되지 않은 것** (Phase 6-BN 에서 갈라졌다)
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_d01_the_crown_has_a_registered_summon_procedure_now(repository):
    """
    🔴 **성관의 소환 절차가 Phase 6-BN 에서 등재되었다.**

    6-BK 의 이 시험은 반대를 적고 있었다 ("등재되지 않았다"). 등재되는 날
    먼저 깨지라고 적어 둔 시험이고, 그날이 와서 **뜻을 뒤집어 다시
    적는다** — 느슨하게 푸는 것이 아니라 새 사실을 못박는다.

    갈라진 것이 무엇인지 수로 적는다.

    1. **소환 절차는 등재되었다** — :data:`~engine.hand_summon.
       HAND_SUMMON_RULES` 에 한 장. 그래서 검증기의 마지막 요구가 더는
       언제나 ``UnimplementedRule`` 이 아니다.
    2. **효과는 여전히 하나도 등재되지 않았다** — ``EFFECT_LIBRARY`` 에
       성관의 ②(무효) · ③(서치)가 없다. 소환 절차는 효과가 아니므로
       (``EFFECT_SPSUMMON_PROC``) 둘이 따로 움직인다.
    3. **놓을 칸은 이제 선택이다** — 행위가 ``ZONE`` 대상으로 칸을 들고
       가고 (``PlayerAction.special_summon`` 의 ``slot``), 절차가 그 칸에만
       놓는다 (``SummonProcedure.plan_for`` 의 ``slot``).
    """
    from engine.action_validation import SPECIAL_SUMMON_CONDITION_RULE
    from engine.effect.library import EFFECT_LIBRARY
    from engine.hand_summon import HAND_SUMMON_RULES, hand_summon_rule_for
    from engine.vocabulary import Position

    #: 🔴 **한 장이다.** 수가 움직이면 어느 카드가 들어왔는지 적어야 한다.
    assert len(HAND_SUMMON_RULES) == 1
    rule = hand_summon_rule_for(CROWN)
    assert rule is not None
    assert rule.from_zone is Zone.HAND
    #: 🔴 공통 특수 소환의 고정값(앞면 공격)이 **아니다** — 카드가 형식을
    #: 정한다 (``SetTargetRange(POS_FACEUP_DEFENSE,0)``).
    assert rule.position is Position.FACEUP_DEFENSE
    assert rule.requires_link_pointed_zone is True
    assert rule.limit_count == 1

    #: 효과는 그대로 0건이다 (②·③ 는 이번 범위가 아니다).
    assert [e for e in EFFECT_LIBRARY if e.card_id == CROWN] == []
    #: 없는 규칙의 **이름은 그대로다** — 등재되지 않은 카드가 그 이름으로
    #: 막힌다 (``_HandSummonLegal.missing_rules``).
    assert "카드마다 다르다" in SPECIAL_SUMMON_CONDITION_RULE


@requires_official_db
@pytest.mark.real_card
def test_d02_the_engine_now_offers_the_crown_at_the_galatea_board(repository):
    """
    실측 — 갈라테아가 선 **그 시점**에 성관이 **후보로 오른다**.

    🔴 **6-BK 의 이 시험은 두 번 틀렸다.**

    1. 뜻이 뒤집혔다 (6-BN 에서 등재되었으므로 후보가 난다).
    2. 그리고 **옛 단정은 비어 있었다** — ``canonical_state()[2]`` 는
       ``int`` 이고 ``crown_ids`` 는 ``InstanceId`` 들이라, ``in`` 이
       **언제나 거짓**이었다. 등재되기 전에도 그 줄은 아무것도 재지
       않았다. 그래서 여기서는 ``action.source`` 를 그대로 본다.
    """
    from tests.test_galatea_effect_extension import _is, _setup, _take

    duel = _setup(repository, prefer=(CROWN, CYMBAL_SKELETON)).duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(GIRSU, 2)), "기르수 ③")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87, "갈라테아i")
    _take(duel, _is("activate_effect", effect=(CYMBAL_SKELETON, 0)), "스켈레촌 ①")
    _take(duel, _is("activate_effect", effect=(GALATEA_I, 2)), "갈라테아i ②")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] in (83, 84), "갈라테아")

    crown_ids = {
        card.instance_id
        for card in duel.state.player(0).hand
        if card.card_id == CROWN
    }
    assert crown_ids, "성관이 패에 없다 — 이 시험의 전제가 깨졌다"

    legal = duel.legal_actions(0)
    offered = [
        action for action in legal.allowed
        if action.source in crown_ids
    ]
    #: 🔴 **한 건이다** — 가리켜지는 빈 칸이 한 칸이므로 (실측: 왼쪽
    #: 정렬에서 ``(0,)``). 칸이 늘면 후보도 늘고, 그때 이 수가 깨진다.
    assert len(offered) == 1, [str(a) for a in offered]
    action = offered[0]
    assert action.kind.value == "special_summon"
    #: 🔴 **행위가 칸을 들고 간다.** 이것이 없으면 실행기가 칸을 다시
    #: 고르고, 허가가 난 칸과 놓인 칸이 갈린다.
    assert len(action.targets) == 1
    assert action.targets[0].kind.value == "zone"
    assert action.targets[0].index == 0
    #: 막힌 것이 없으므로 보류에 특수 소환 줄이 없다.
    assert not [
        w for w in legal.withheld if w.kind.value == "special_summon"
    ]
