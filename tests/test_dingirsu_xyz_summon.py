"""
Phase 6-BO — 「시오르페골 딩기르수」 를 **엑시즈 소환**하고, 소환 성공 시
효과로 **제외된 기계족을 소재로 붙인다.**

이 파일이 지키는 것
-------------------
A. 등재된 값이 ``c93854893.lua`` 에서 읽은 것과 같은가 (랭크 · 소재 장수 ·
   소재 조건 · 1턴 1번 특수 소환), 그리고 **못 옮긴 것이 적혀 있는가.**
B. 소재 판정(:func:`~engine.xyz_rules.assess_xyz_materials`)의 갈래 전부 —
   엑시즈 몬스터가 아님 · 엑스트라 덱에 없음 · 남의 카드 · 등재되지 않은
   카드 · 장수가 다름 · 링크가 아님 · 세트가 다름 · 뒷면 · 1턴 1번 ·
   놓을 칸. 🔴 **"모름" 과 "안 됨" 을 가른다** (ADR-006).
C. 검증기가 그 판정을 **그대로** 쓴다.
D. 절차가 소재를 **숙주 아래(``OVERLAY``)** 로 옮기고 숙주를 엑스트라
   몬스터 존에 앞면 공격 표시로 놓는다. 두 이동이 **각각** 기록된다.
E. 딩기르수 ② — 제외된 기계족 1장을 소재로. 제외 구역이 비어 있으면
   **제시되지 않고**, 여럿이면 **고를 수 있어야** 한다.
F. 후보 요약이 **누구 아래 무엇이 있는지** 들고 있다
   (:attr:`~agent.bounded_search.CardSlot.materials`).
G. 기본 예산의 자율 탐색이 ① 엑시즈 소환 · ② 롱기르수 위 · ③ 스켈레촌
   부착까지 **스스로** 찾는다.

🔴 **수순을 정답으로 주지 않는다.** G 묶음은 행동을 하나도 지정하지 않고
돌아온 후보들 **안에** 그 전개가 있는지만 센다. B · D · E 묶음은 작은 판을
직접 세우지만, 그 판이 "이렇게 전개해야 한다" 는 주장은 아니다.
"""

from pathlib import Path

import pytest

from engine.vocabulary import Phase, Position, Zone

GIRSU = 69811710
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
CYMBAL_SKELETON = 21441617
DINGIRSU = 93854893

#: 🔴 **「오르페골」 이 아닌 링크 몬스터** (Vorticular Drumgon) — 세트
#: 조건이 갈리는 자리를 재려고 쓴다. 이 덱의 카드가 아니고, 전개의 정답을
#: 주장하지 않는다 (``tests/test_world_crown_hand_summon.py`` 와 같은 이유).
OTHER_LINK = 739444

#: 🔴 **등재되지 않은 엑시즈 몬스터** (Number 39: Utopia) — 대체 절차가
#: 적히지 않은 카드가 **모름**으로 막히는지 재는 자리다.
OTHER_XYZ = 84013237

CARDS_CDB = Path(__file__).resolve().parent.parent / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="cards.cdb 없음"
)


# ======================================================================
# 판 만들기 — 작게 유지한다
# ======================================================================
def _view(state, viewer=0):
    from engine.game_state_view import GameStateView

    return GameStateView.from_state(state, viewer=viewer)


def _blank(repository):
    from engine.state.game_state import GameState

    state = GameState.create(
        repository, decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=0, seed=1, shuffle=False,
    )
    state.turn.turn_number = 1
    state.turn.set_phase(Phase.MAIN1)
    return state


def _extra(state, card_id, owner=0):
    """
    엑스트라 덱에 한 장. 🔴 엑시즈 소환의 **출발 자리**다.

    🔴 **개체 번호를 돌려준다** — ``create_instance`` 가 돌려주는 것은
    ``CardInstance`` 이고, 그것을 그대로 행동에 넣으면 판정이 "관측에
    보이지 않습니다" 로 답한다 (실측으로 겪었다).
    """
    return state.create_instance(
        card_id, owner=owner, zone=Zone.EXTRA
    ).instance_id


def _place(state, card_id, zone, index, position=Position.FACEUP_ATTACK,
           owner=0):
    inst = state.create_instance(card_id, owner=owner, zone=Zone.EXTRA)
    state.move(inst, zone, to_player=owner, index=index, position=position)
    return inst.instance_id


def _banish(state, card_id, owner=0):
    inst = state.create_instance(card_id, owner=owner, zone=Zone.EXTRA)
    state.move(inst, Zone.REMOVED, to_player=owner,
               position=Position.FACEUP_ATTACK)
    return inst.instance_id


def _board(repository, *, material=GALATEA, index=0):
    """소재가 엑스트라 몬스터 존에 서 있고 딩기르수가 엑스트라 덱에 있다."""
    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, material, Zone.EMZONE, index)
    return state, host, mat


def _duel(state):
    from engine.duel import Duel
    from engine.priority import PriorityState

    return Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=state.turn.turn_player, phase=state.turn.phase
        ),
    )


def _assess(state, host, materials, actor=0):
    from engine.xyz_rules import assess_xyz_materials

    return assess_xyz_materials(_view(state), actor, host, tuple(materials))


# ======================================================================
# A. 등재된 값이 Lua 에서 읽은 것과 같다
# ======================================================================
def test_a01_the_rule_matches_the_card_script():
    """🔴 등재된 값마다 **어디서 읽었는지**가 함께 적혀 있다."""
    from engine.xyz_rules import XYZ_ALTERNATIVE_RULES, alternative_rule_for

    #: 🔴 **한 장이다.** 늘어나는 날 어느 카드가 들어왔는지 적어야 한다.
    assert len(XYZ_ALTERNATIVE_RULES) == 1
    rule = alternative_rule_for(DINGIRSU)
    assert rule is not None
    assert rule.rank == 8
    assert rule.material_count == 1
    assert rule.material_must_be_link is True
    assert rule.material_setcode_names == ("SET_ORCUST",)
    assert rule.spsummon_once is True
    #: 🔴 근거가 글자로 남아 있다 — 사라지면 누군가 손으로 고친 것이다.
    assert rule.lua_file == "c93854893.lua"
    assert "Xyz.AddProcedure" in rule.lua_excerpt
    assert "s.ovfilter" in rule.lua_excerpt
    assert "SetSPSummonOnce" in rule.lua_excerpt


def test_a02_the_base_procedure_is_not_ported():
    """
    🔴 **기본 절차(레벨 8 몬스터 2장)를 옮기지 않았다.**

    옮기지 않은 것을 적어 두지 않으면 "엑시즈 소환을 구현했다" 는 주장이
    된다. 그 자리가 비는 날 이 시험이 먼저 깨진다.
    """
    from engine.xyz_rules import XYZ_BASE_PROCEDURE_RULE, XYZ_BLIND_SPOTS

    assert XYZ_BASE_PROCEDURE_RULE
    assert len(XYZ_BLIND_SPOTS) >= 5


def test_a03_an_unregistered_xyz_has_no_rule():
    """등재되지 않은 카드는 **없는 것처럼** 동작한다 (ADR-006)."""
    from engine.xyz_rules import alternative_rule_for

    assert alternative_rule_for(OTHER_XYZ) is None
    assert alternative_rule_for(None) is None


def test_a04_the_material_destination_is_not_a_player_zone():
    """🔴 소재는 **숙주가 들고 있다** — 소유자의 존이 아니다."""
    from engine.state.player import PLAYER_ZONES
    from engine.xyz_rules import XYZ_MATERIAL_DESTINATION, XYZ_SUMMON_TO_ZONE

    assert XYZ_MATERIAL_DESTINATION is Zone.OVERLAY
    assert XYZ_MATERIAL_DESTINATION not in PLAYER_ZONES
    assert XYZ_SUMMON_TO_ZONE is Zone.EMZONE


# ======================================================================
# B. 소재 판정의 갈래 — 모름은 허가가 아니다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_b01_a_faceup_orcust_link_is_legal(repository):
    """기준 판 — 앞면 「오르페골」 링크 몬스터 1장이면 ``LEGAL``."""
    from engine.xyz_rules import XyzMaterialEligibility

    state, host, mat = _board(repository)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.LEGAL, got.reason
    assert got.permits_procedure is True
    #: 🔴 **소재가 떠난 뒤의 칸**이다 — 지금 그 칸에는 소재가 있다.
    assert got.slot == 0
    assert got.missing_rule is None


@requires_official_db
@pytest.mark.real_card
def test_b02_longirsu_is_also_a_material(repository):
    """
    🔴 **카드 이름을 고정하지 않았다.** 롱기르수도 같은 조건을 만족하므로
    같은 판정이 나온다 — 갈라테아만 통하는 길이 아니다.
    """
    from engine.xyz_rules import XyzMaterialEligibility

    state, host, mat = _board(repository, material=LONGIRSU)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.LEGAL, got.reason


@requires_official_db
@pytest.mark.real_card
def test_b03_a_non_link_monster_is_refused(repository):
    """링크 몬스터가 아니면 거절 — ``ovfilter`` 의 ``IsType(TYPE_LINK)``."""
    from engine.xyz_rules import XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, GIRSU, Zone.MZONE, 0)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "링크" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b04_a_link_outside_the_archetype_is_refused(repository):
    """「오르페골」 이 아니면 거절 — ``IsSetCard(SET_ORCUST)``."""
    from engine.xyz_rules import XyzMaterialEligibility

    state, host, mat = _board(repository, material=OTHER_LINK)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "ORCUST" in got.reason or "오르페골" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b05_a_facedown_material_is_refused(repository):
    """뒷면이면 거절 — ``IsFaceup()``."""
    from engine.xyz_rules import XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, GALATEA, Zone.MZONE, 0,
                 position=Position.FACEDOWN_DEFENSE)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "앞면" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b06_two_materials_are_unknown_not_illegal(repository):
    """
    🔴 **두 장은 "안 된다" 가 아니라 "모른다" 다.** 기본 절차(레벨 8 두
    장) 를 옮기지 않았으므로, 그 장수로 가능한지 이 저장소는 모른다.
    """
    from engine.xyz_rules import (
        XYZ_BASE_PROCEDURE_RULE, XyzMaterialEligibility,
    )

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    #: 🔴 **엑스트라 몬스터 존은 이 저장소에서 한 칸이다** (실측) — 두
    #: 장을 세우려면 한 장은 메인 몬스터 존에 둔다.
    one = _place(state, GALATEA, Zone.EMZONE, 0)
    two = _place(state, LONGIRSU, Zone.MZONE, 0)
    got = _assess(state, host, [one, two])
    assert got.eligibility is XyzMaterialEligibility.UNDETERMINED
    assert got.missing_rule == XYZ_BASE_PROCEDURE_RULE
    assert got.permits_procedure is False


@requires_official_db
@pytest.mark.real_card
def test_b07_an_unregistered_xyz_is_unknown(repository):
    """등재되지 않은 엑시즈 몬스터는 **모름**으로 막힌다."""
    from engine.xyz_rules import XYZ_RULE_MISSING, XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, OTHER_XYZ)
    mat = _place(state, GALATEA, Zone.EMZONE, 0)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.UNDETERMINED
    assert got.missing_rule == XYZ_RULE_MISSING


@requires_official_db
@pytest.mark.real_card
def test_b08_a_non_xyz_source_is_refused(repository):
    """엑시즈 몬스터가 아니면 **그 사실이 먼저** 보고된다."""
    from engine.xyz_rules import XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, LONGIRSU)
    mat = _place(state, GALATEA, Zone.EMZONE, 0)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "엑시즈 몬스터가 아닙니다" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b09_a_host_already_on_the_field_is_refused(repository):
    """엑스트라 덱에 없으면 거절 — 엑시즈 소환은 거기서 꺼내는 것이다."""
    from engine.xyz_rules import XyzMaterialEligibility

    state = _blank(repository)
    host = _place(state, DINGIRSU, Zone.MZONE, 0)
    mat = _place(state, GALATEA, Zone.EMZONE, 0)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "EXTRA" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b10_an_opponent_material_is_refused(repository):
    """상대 필드의 몬스터는 소재가 되지 않는다."""
    from engine.xyz_rules import XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, GALATEA, Zone.EMZONE, 0, owner=1)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL


@requires_official_db
@pytest.mark.real_card
def test_b11_the_same_name_cannot_be_special_summoned_twice(repository):
    """
    ``c:SetSPSummonOnce(id)`` — 이 턴에 그 **이름**을 이미 특수 소환했으면
    거절한다. 🔴 **소환법을 가리지 않는다**: 링크 소환으로 적어 두어도
    막힌다.
    """
    from engine.effect.delta import SummonKind
    from engine.xyz_rules import XyzMaterialEligibility

    state, host, mat = _board(repository)
    state.summon_uses.record(
        state.turn.turn_number, 0, DINGIRSU, SummonKind.LINK.value
    )
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.ILLEGAL
    assert "1턴에 1번" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b12_a_full_extra_monster_zone_blocks_the_summon(repository):
    """
    소재가 떠난 뒤에도 빈 칸이 없으면 **놓을 수 없다.**

    🔴 소재가 서 있던 칸은 **빈 칸으로 센다** — 그러지 않으면 이 절차가
    영영 막힌다. 여기서는 소재를 메인 몬스터 존에 두고 두 EMZ 칸을 모두
    채워, "소재가 떠나도 비지 않는" 판을 만든다.
    """
    from engine.xyz_rules import XYZ_PLACEMENT_RULE, XyzMaterialEligibility

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, GALATEA, Zone.MZONE, 0)
    #: 🔴 소재가 아닌 카드가 그 칸을 차지한다 — 소재가 떠나도 비지 않는다.
    _place(state, LONGIRSU, Zone.EMZONE, 0)
    got = _assess(state, host, [mat])
    assert got.eligibility is XyzMaterialEligibility.UNDETERMINED
    assert got.missing_rule == XYZ_PLACEMENT_RULE


# ======================================================================
# C. 검증기가 그 판정을 그대로 쓴다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_c01_a_legal_xyz_summon_validates(repository):
    from engine.action import PlayerAction
    from engine.action_validation import ActionValidator
    from engine.validation import ActionValidity

    state, host, mat = _board(repository)
    action = PlayerAction.xyz_summon(0, host, (mat,))
    got = ActionValidator(_view(state)).validate(action)
    assert got.validity is ActionValidity.VALID, got.reason


@requires_official_db
@pytest.mark.real_card
def test_c02_an_illegal_material_is_invalid(repository):
    from engine.action import PlayerAction
    from engine.action_validation import ActionValidator
    from engine.validation import ActionValidity, ValidationCode

    state = _blank(repository)
    host = _extra(state, DINGIRSU)
    mat = _place(state, GIRSU, Zone.MZONE, 0)
    action = PlayerAction.xyz_summon(0, host, (mat,))
    got = ActionValidator(_view(state)).validate(action)
    assert got.validity is ActionValidity.INVALID, got.reason
    assert got.code is ValidationCode.XYZ_MATERIAL_INVALID


@requires_official_db
@pytest.mark.real_card
def test_c03_an_unregistered_card_stays_unknown(repository):
    """🔴 **모름은 허가가 아니다** (ADR-006) — 그리고 거절도 아니다."""
    from engine.action import PlayerAction
    from engine.action_validation import ActionValidator
    from engine.validation import ActionValidity, ValidationCode

    state = _blank(repository)
    host = _extra(state, OTHER_XYZ)
    mat = _place(state, GALATEA, Zone.EMZONE, 0)
    action = PlayerAction.xyz_summon(0, host, (mat,))
    got = ActionValidator(_view(state)).validate(action)
    assert got.validity is ActionValidity.UNKNOWN, got.reason
    assert got.code is ValidationCode.RULE_NOT_IMPLEMENTED


@requires_official_db
@pytest.mark.real_card
def test_c04_the_candidate_generator_offers_the_summon(repository):
    """후보 생성이 그 자리에서 **엑시즈 소환**을 내준다."""
    from engine.action import PlayerActionKind

    state, host, mat = _board(repository)
    duel = _duel(state)
    legal = duel.legal_actions(0)
    found = [a for a in legal.allowed
             if a.kind is PlayerActionKind.XYZ_SUMMON]
    assert found, [w.reason for w in legal.withheld]
    assert all(a.source == host for a in found)
    assert all(tuple(a.materials) == (mat,) for a in found)


@requires_official_db
@pytest.mark.real_card
def test_c05_an_unread_extra_deck_xyz_is_withheld_not_hidden(repository):
    """
    🔴 등재되지 않은 엑시즈 몬스터는 **보류로 남는다** — 조용히 사라지지
    않는다.
    """
    from engine.action import PlayerActionKind

    state = _blank(repository)
    _extra(state, OTHER_XYZ)
    _place(state, GALATEA, Zone.EMZONE, 0)
    duel = _duel(state)
    legal = duel.legal_actions(0)
    assert not [a for a in legal.allowed
                if a.kind is PlayerActionKind.XYZ_SUMMON]
    held = [w for w in legal.withheld
            if w.kind is PlayerActionKind.XYZ_SUMMON]
    assert held, "보류 줄이 없다 — 후보가 말없이 사라졌다"


# ======================================================================
# D. 절차 — 소재는 숙주 아래로 간다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_d01_the_material_moves_under_the_host(repository):
    from engine.action import PlayerActionKind

    state, host, mat = _board(repository)
    duel = _duel(state)
    legal = duel.legal_actions(0)
    action = next(a for a in legal.allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    step = duel.apply(action)
    assert step.accepted, step.reason

    placed = duel.state.find_instance(host)
    assert placed.zone is Zone.EMZONE
    assert placed.is_faceup
    assert placed.position is Position.FACEUP_ATTACK
    #: 🔴 **숙주가 들고 있다.**
    assert list(placed.materials) == [mat]
    moved = duel.state.find_instance(mat)
    assert moved.zone is Zone.OVERLAY


@requires_official_db
@pytest.mark.real_card
def test_d02_each_material_move_is_recorded_on_its_own(repository):
    """
    🔴 **두 사실을 한 기록에 담지 않는다** (ADR-002) — 소환과 소재 이동은
    서로 다른 사건이다.
    """
    from engine.action import PlayerActionKind
    from engine.effect.delta import MATERIAL_BY_XYZ_SUMMON
    from engine.xyz_summon import XyzSummonExecutor

    state, host, mat = _board(repository)
    duel = _duel(state)
    legal = duel.legal_actions(0)
    action = next(a for a in legal.allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    #: 🔴 **실행기에게 직접 묻는다** — ``DuelStep`` 은 델타를 들고 있지
    #: 않다 (무엇이 적용되었는지는 기록이 말한다).
    deltas = XyzSummonExecutor().apply(duel.state, action)
    kinds = [d.kind for d in deltas]
    assert "material_attached" in kinds
    attached = [d for d in deltas if d.kind == "material_attached"]
    assert len(attached) == 1
    assert attached[0].host == host
    assert attached[0].card == mat
    assert attached[0].basis == MATERIAL_BY_XYZ_SUMMON
    #: 🔴 **소환과 소재 이동이 각각이다** — 한 기록에 담지 않는다.
    assert len(kinds) > len(attached)


@requires_official_db
@pytest.mark.real_card
def test_d03_the_summon_is_counted_by_name(repository):
    """같은 이름을 두 번 엑시즈 소환할 수 없다 — 기록이 남는다."""
    from engine.action import PlayerActionKind

    state, host, mat = _board(repository)
    _place(state, LONGIRSU, Zone.MZONE, 0)
    duel = _duel(state)
    action = next(a for a in duel.legal_actions(0).allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    assert duel.apply(action).accepted
    rows = duel.state.summon_uses.entries(duel.state.turn.turn_number)
    assert any(row[1] == DINGIRSU for row in rows), rows
    #: 🔴 두 번째 딩기르수가 엑스트라 덱에 있어도 후보가 되지 않는다.
    _extra(duel.state, DINGIRSU)
    again = [a for a in duel.legal_actions(0).allowed
             if a.kind is PlayerActionKind.XYZ_SUMMON]
    assert not again


# ======================================================================
# F. 후보 요약이 소재를 들고 있다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_f01_the_resource_summary_carries_the_materials(repository):
    """
    🔴 **누구 아래 무엇이 있는가** 를 요약이 말할 수 있어야 한다.
    ``OVERLAY`` 존의 납작한 목록만으로는 엑시즈 몬스터가 둘일 때 가를 수
    없다 (Phase 6-BO §4 에서 실제로 막혔다).
    """
    from agent.bounded_search import summarize_resources
    from engine.action import PlayerActionKind

    state, host, mat = _board(repository)
    duel = _duel(state)
    action = next(a for a in duel.legal_actions(0).allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    assert duel.apply(action).accepted

    summary = summarize_resources(duel, 0)
    box = summary.zone(0, Zone.EMZONE)
    assert box is not None
    hosts = [c for c in box.cards if c is not None and c.card_id == DINGIRSU]
    assert len(hosts) == 1
    assert hosts[0].materials == (mat.value,)
    #: 🔴 ``OVERLAY`` 쪽에도 같은 카드가 있다 — 두 칸이 어긋나지 않는다.
    overlay = summary.zone(0, Zone.OVERLAY)
    assert overlay is not None
    assert [c.instance for c in overlay.cards] == [mat.value]


# ======================================================================
# E. 딩기르수 ② — 제외된 기계족 1장을 소재로
# ======================================================================
def test_e01_the_registered_entry_matches_the_script():
    """
    🔴 **등재된 갈래 하나와 그 모양.** 「하나를 고르고 발동한다」 의 두
    갈래 가운데 뒤쪽만 등재했고, 그 사실이 **근거와 함께** 적혀 있다.
    """
    from engine.effect.library import EFFECT_LIBRARY, entry_for
    from engine.effect.operation import OperationKind
    from engine.ids import EffectRef
    from engine.use_limit import LimitScope
    from engine.vocabulary import ActivationKind

    entry = entry_for(EffectRef(DINGIRSU, 1))
    assert entry is not None
    #: 🔴 **이 카드의 항목은 하나다.** 둘이 되는 날, 같은 ordinal 에 정의
    #: 둘을 둘 수 없다는 제약이 깨졌는지 먼저 확인해야 한다.
    mine = [e for e in EFFECT_LIBRARY
            if e.definition.effect_ref.card_id == DINGIRSU]
    assert len(mine) == 1

    definition = entry.definition
    assert definition.activation_kind is ActivationKind.TRIGGER
    assert definition.use_limit.scope is LimitScope.PER_CARD_NAME
    assert [op.kind for op in definition.operations] == [
        OperationKind.ATTACH_AS_MATERIAL
    ]
    assert entry.lua_file == "c93854893.lua"
    assert "EVENT_SPSUMMON_SUCCESS" in entry.lua_excerpt
    assert "Duel.Overlay" in entry.lua_excerpt
    #: 🔴 **못 옮긴 것이 근거에 적혀 있다** — 앞쪽 갈래와
    #: ``IsCanBeXyzMaterial``.
    note = definition.provenance.note
    assert "IsCanBeXyzMaterial" in note
    assert "앞쪽 갈래" in note


def test_e02_the_choice_is_made_while_resolving_and_picks_one_card():
    """
    🔴 **세 가지를 가른다** — 발동할지 / 효과 안에서 무엇을 할지 / 해결
    중에 어느 카드를 고를지.

    카드 텍스트에 「대상으로 하고」 가 **없고** 공식 스크립트도 ``effop``
    에서 고르므로, 이 저장소도 **해결 중에** 고른다. 장수는 정확히 1장이고
    자리는 **자신의 제외 구역**이다.
    """
    from engine.effect.library import entry_for
    from engine.ids import EffectRef
    from engine.vocabulary import Zone as Z

    definition = entry_for(EffectRef(DINGIRSU, 1)).definition
    #: ``TargetBinding.single`` 은 **튜플**을 돌려준다 — 하나짜리다.
    assert len(definition.targets) == 1
    spec = definition.targets[0].spec
    assert spec.chosen_at_resolution is True
    assert spec.is_targeting is False
    choice = spec.choice
    assert choice.minimum == 1 and choice.maximum == 1
    assert choice.source.zones == frozenset({Z.REMOVED})


def test_e03_the_activation_condition_reads_the_removed_zone():
    """
    🔴 **발동 조건을 장수로만 옮겼다.** "앞면 기계족이 제외되어 있는가" 는
    장수로 답할 수 없고, 그래서 이 조건은 **필요조건**이다 — 제외 구역이
    비어 있으면 제시되지 않고 (실측: §4 의 짧은 전개에서 0건), 비어 있지
    않아도 기계족이 없을 수 있다.
    """
    from engine.condition.model import ZoneCountAtLeast
    from engine.effect.library import entry_for
    from engine.condition.model import PlayerRef
    from engine.ids import EffectRef
    from engine.vocabulary import Zone as Z

    activation = entry_for(EffectRef(DINGIRSU, 1)).definition.activation
    assert isinstance(activation, ZoneCountAtLeast)
    assert activation.who is PlayerRef.CONTROLLER
    assert activation.zone is Z.REMOVED
    assert activation.count == 1
    #: 🔴 **자신을 빼지 않는다** — 세는 자리가 제외 구역이고 딩기르수는
    #: 필드에 있으므로 그 예외를 켤 이유가 없다.
    assert activation.excluding_source is False


def test_e04_the_rule_question_is_registered_for_the_machines():
    """
    부착은 **규칙으로 막히는 조작**이고, 그 물음에 답이 등재되어 있어야
    한다 — 등재되지 않은 카드가 판에 있으면 모든 물음이 ``UNKNOWN`` 이 된다.
    """
    from engine.effect.library import OPERATION_RULINGS
    from engine.effect.operation import OperationKind
    from engine.effect.semantics import RULE_GATED_QUESTIONS, RuleQuestion

    assert (RULE_GATED_QUESTIONS[OperationKind.ATTACH_AS_MATERIAL]
            is RuleQuestion.MAY_BE_XYZ_MATERIAL)
    for card_id in (CYMBAL_SKELETON, GIRSU):
        facts = OPERATION_RULINGS.facts_for(card_id)
        assert facts is not None, card_id
        assert facts.answers.get(RuleQuestion.MAY_BE_XYZ_MATERIAL) is not None
    #: 🔴 **딩기르수 자신도 등재되어 있다** — 앞면으로 판에 서 있는 카드에
    #: 대해 아는 것이 없으면 그 카드가 **자기 효과를 막는다** (실측).
    assert OPERATION_RULINGS.facts_for(DINGIRSU) is not None


# ======================================================================
# H. 기준 덱 · 기준 패의 **실제 판**에서 끝까지
# ======================================================================
def _reference_longirsu_board(repository):
    """
    🔴 **허용 후보에서만 밟는다.** 롱기르수가 서 있고 스켈레촌이 제외되어
    있는 판을 기준 덱 · 기준 패에서 만든다 — 여기까지는 6-BJ · 6-BN 이
    이미 재현한 전개이고, 이 Phase 가 보려는 것은 **그 다음**이다.
    """
    from tests.test_galatea_effect_extension import _is, _setup, _take

    setup = _setup(repository, prefer=(27918365, CYMBAL_SKELETON))
    duel = setup.duel
    assert setup.can_run, setup.refusal
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(GIRSU, 2)), "기르수 ③")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87, "갈라테아i")
    _take(duel, _is("activate_effect", effect=(CYMBAL_SKELETON, 0)),
          "스켈레촌 ①")
    _take(duel, _is("activate_effect", effect=(GALATEA_I, 2)), "갈라테아i ②")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] in (83, 84),
          "갈라테아")
    _take(duel, _is("activate_effect", effect=(GALATEA_I, 4)),
          "갈라테아i ③ (묘지 소생)")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 91, "롱기르수")
    return duel


def _names(duel, zone, seat=0):
    return [c.name for c in duel.state.zone(seat, zone) if c is not None]


@requires_official_db
@pytest.mark.real_card
def test_h01_the_real_board_offers_the_xyz_summon_over_longirsu(repository):
    """① 롱기르수가 선 **실제 판**에서 딩기르수 소환이 허용 후보로 나온다."""
    from engine.action import PlayerActionKind

    duel = _reference_longirsu_board(repository)
    assert LONGIRSU in [c.card_id for c in duel.state.zone(0, Zone.EMZONE)
                        if c is not None]
    legal = duel.legal_actions(0)
    found = [a for a in legal.allowed
             if a.kind is PlayerActionKind.XYZ_SUMMON]
    assert found, [(w.code.value, w.reason) for w in legal.withheld
                   if w.kind is PlayerActionKind.XYZ_SUMMON]
    #: 🔴 **소재가 롱기르수다** — 카드 이름을 고정해 고른 것이 아니라,
    #: 그 판에서 조건을 만족하는 카드가 그것뿐이다.
    for action in found:
        mats = [duel.state.find_instance(m).card_id for m in action.materials]
        assert mats == [LONGIRSU]


@requires_official_db
@pytest.mark.real_card
def test_h02_the_summon_offers_the_choice_trigger(repository):
    """
    ② 소환이 성공하면 **그 자리에서** 딩기르수의 선택 유발 효과가 제시된다.

    🔴 **상대 필드가 비어 있지 않다** — 기르수 ③ 이 놓은 성유물 토큰이
    있으므로 공식 규칙으로는 앞쪽 갈래(상대 필드의 카드 1장을 묘지로)도
    발동할 수 있다. 등재하지 않은 것이 "불가능" 이 아니라는 사실을 이
    시험이 **판으로** 적는다.
    """
    from engine.action import PlayerActionKind

    duel = _reference_longirsu_board(repository)
    action = next(a for a in duel.legal_actions(0).allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    assert duel.apply(action).accepted

    opponent = _names(duel, Zone.MZONE, seat=1)
    assert opponent, "상대 필드가 비었다 — 앞쪽 갈래의 전제가 깨졌다"

    offers = [a for a in duel.legal_actions(0).allowed
              if a.kind is PlayerActionKind.ACTIVATE_EFFECT
              and duel.state.find_instance(a.source).card_id == DINGIRSU]
    assert len(offers) == 1, [a.effect_ref for a in offers]
    assert offers[0].effect_ref.ordinal == 1
    #: 🔴 **발동 시점에는 대상을 들고 있지 않다** (해결 중에 고른다).
    assert not offers[0].targets


@requires_official_db
@pytest.mark.real_card
def test_h03_resolving_moves_one_banished_machine_under_the_host(repository):
    """
    ③ 해결이 **제외된 기계족 1장**을 그 딩기르수 아래로 옮긴다.

    🔴 **두 이동이 따로다** — 롱기르수는 소환 절차로 소재가 되었고,
    스켈레촌은 효과로 붙었다. 🔴 **고르는 수가 남아 있다**: 제외 구역에
    기계족이 둘 있고 한 장만 간다.
    """
    from deck.opening import _settle_chain
    from engine.action import PlayerActionKind

    duel = _reference_longirsu_board(repository)
    before = _names(duel, Zone.REMOVED)
    machines = [c for c in duel.state.zone(0, Zone.REMOVED)
                if c is not None and c.definition is not None
                and c.definition.race_name == "MACHINE"]
    assert len(machines) >= 2, before

    action = next(a for a in duel.legal_actions(0).allowed
                  if a.kind is PlayerActionKind.XYZ_SUMMON)
    assert duel.apply(action).accepted
    offer = next(a for a in duel.legal_actions(0).allowed
                 if a.kind is PlayerActionKind.ACTIVATE_EFFECT
                 and duel.state.find_instance(a.source).card_id == DINGIRSU)
    assert duel.apply(offer).accepted
    if duel.priority.is_open:
        _settle_chain(duel, lambda legal, seat=None: ())

    host = next(c for c in duel.state.zone(0, Zone.EMZONE) if c is not None)
    assert host.card_id == DINGIRSU
    under = [duel.state.find_instance(m).card_id for m in host.materials]
    #: 🔴 소환 절차의 소재가 **먼저**, 효과로 붙인 것이 **뒤**다.
    assert under == [LONGIRSU, CYMBAL_SKELETON]
    after = _names(duel, Zone.REMOVED)
    assert len(after) == len(before) - 1
    assert "오르페골 스켈레촌" not in after
