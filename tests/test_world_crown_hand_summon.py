"""
Phase 6-BN — 「성유물－『성관』」 을 **패에서 특수 소환하는 절차**.

이 파일이 지키는 것
-------------------
A. 등재된 값이 ``c27918365.lua`` 에서 읽은 것과 같은가 (출발 자리 · 표시
   형식 · 턴 제한 · 놓을 칸의 조건).
B. 판정(:func:`~engine.hand_summon.assess_hand_summon`)의 **세 갈래**가
   갈리는 자리 전부 — 등재되지 않은 카드 · 내 카드가 아님 · 패에 없음 ·
   칸 미지목 · 가리켜지지 않는 칸 · 찬 칸 · 턴 제한 · 특수 소환 제한.
C. 검증기가 그 판정을 **그대로** 쓴다 — 등재된 카드만 ``VALID`` 가 되고,
   등재되지 않은 카드는 여전히 ``UNKNOWN`` 이다.
D. 절차가 **지목된 칸에** 앞면 수비 표시로 놓고, 공통 경로는 한 글자도
   바뀌지 않는다.
E. 후보 생성이 **가리켜지는 빈 칸마다 하나씩** 만든다.
F. 🔴 **체인을 만들지 않는다** — ``EFFECT_SPSUMMON_PROC`` 는 소환 절차이고
   효과가 아니다.
G. 성관이 선 뒤의 후속은 **기존 링크 소재 판정**이 답한다 (이 Phase 가
   카드 순서를 정답으로 넣지 않는다).

🔴 **정렬을 시험이 고르지 않는다.** E 묶음은 두 EMZ 정렬을 모두 돌려
칸의 수를 센다 — :data:`~engine.link_zone.MODELLED_ALIGNMENT` 가 후보의
**수**를 바꾸지 않는다는 말이 측정이 되어야 한다.
"""

from pathlib import Path

import pytest

from engine.vocabulary import Phase, Position, Zone

GIRSU = 69811710
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
CYMBAL_SKELETON = 21441617
CROWN = 27918365

#: 🔴 **좌·우 마커를 함께 가진 링크 몬스터** (Vorticular Drumgon).
#:
#: 이 덱의 카드가 아니다. 오르페골 링크 몬스터는 옆 칸을 가리키는 마커가
#: 없어서 (실측: 갈라테아 · 갈라테아i · 롱기르수 모두 메인 몬스터 존에서
#: 가리키는 칸이 0개), **가리켜지는 빈 칸이 둘인 판**을 그 카드들로는 만들
#: 수 없다. 규칙을 재는 자리이므로 덱과 무관한 카드를 쓰고, 이 카드가
#: 전개의 정답이라고 주장하지 않는다.
SIDE_MARKER_LINK = 739444

CARDS_CDB = Path(__file__).resolve().parent.parent / "data" / "cards.cdb"

requires_official_db = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="cards.cdb 없음"
)


# ======================================================================
# 판 만들기 — 작게 유지한다
# ======================================================================


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


def _place(state, card_id, zone, index, position, owner=0):
    inst = state.create_instance(card_id, owner=owner, zone=Zone.EXTRA)
    state.move(inst, zone, to_player=owner, index=index, position=position)
    return inst


def _hand(state, card_id, owner=0):
    return state.create_instance(card_id, owner=owner, zone=Zone.HAND)


def _board(repository):
    """갈라테아가 EMZ 에 서 있고 성관이 패에 있는 **최소 판**."""
    state = _blank(repository)
    _place(state, GALATEA, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    crown = _hand(state, CROWN)
    return state, crown


def _duel(state):
    from engine.duel import Duel
    from engine.priority import PriorityState

    return Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=state.turn.turn_player, phase=state.turn.phase
        ),
    )


# ======================================================================
# A. 등재된 값이 Lua 에서 읽은 것과 같다
# ======================================================================


def test_a01_the_rule_matches_the_card_script():
    """🔴 등재된 값마다 **어디서 읽었는지**가 함께 적혀 있다."""
    from engine.hand_summon import (
        HAND_SUMMON_RULES, UNPORTED, hand_summon_rule_for,
    )
    from engine.use_limit import LimitScope

    #: 🔴 **한 장이다.** 늘어나는 날 어느 카드가 들어왔는지 적어야 한다.
    assert len(HAND_SUMMON_RULES) == 1
    rule = hand_summon_rule_for(CROWN)
    assert rule is not None
    assert rule.from_zone is Zone.HAND
    assert rule.position is Position.FACEUP_DEFENSE
    assert rule.limit_scope is LimitScope.PER_CARD_NAME
    assert rule.limit_count == 1
    assert rule.requires_link_pointed_zone is True
    #: 🔴 근거가 글자로 남아 있다 — 사라지면 누군가 손으로 고친 것이다.
    assert rule.lua_file == "c27918365.lua"
    assert "EFFECT_SPSUMMON_PROC" in rule.lua_excerpt
    assert "POS_FACEUP_DEFENSE" in rule.lua_excerpt
    assert "EFFECT_COUNT_CODE_OATH" in rule.lua_excerpt
    assert "aux.GetMMZonesPointedTo" in rule.lua_excerpt
    #: 🔴 **못 옮긴 것이 적혀 있다.** 비어 있으면 "전부 구현했다" 는
    #: 주장이 되므로, 수가 0 이 되는 날 이 시험이 먼저 깨진다.
    assert len(UNPORTED) >= 5


def test_a02_an_unregistered_card_has_no_rule():
    """등재되지 않은 카드는 **없는 것처럼** 동작한다 (ADR-006)."""
    from engine.hand_summon import hand_summon_rule_for

    assert hand_summon_rule_for(GIRSU) is None
    assert hand_summon_rule_for(None) is None


def test_a03_the_use_kind_is_not_the_link_summon_kind():
    """
    🔴 사용 기록의 이름이 **링크 소환과 섞이지 않는다.**

    같은 카드가 두 방법으로 나올 수 있고, 턴 제한은 방법마다 따로 센다.
    """
    from engine.effect.delta import SummonKind
    from engine.hand_summon import HAND_SUMMON_USE_KIND

    assert HAND_SUMMON_USE_KIND not in {k.value for k in SummonKind}


# ======================================================================
# B. 판정의 갈래 — 모름은 허가가 아니다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_b01_a_pointed_free_zone_is_legal(repository):
    """기준 판 — 가리켜지는 빈 칸을 지목하면 ``LEGAL``."""
    from engine.hand_summon import (
        HandSummonEligibility, assess_hand_summon, hand_summon_slots,
    )

    state, crown = _board(repository)
    slots = hand_summon_slots(_view(state), 0, CROWN)
    assert slots, "가리켜지는 빈 칸이 없다 — 전제가 깨졌다"
    got = assess_hand_summon(_view(state), 0, crown.instance_id, slots[0])
    assert got.eligibility is HandSummonEligibility.LEGAL, got.reason
    assert got.permits_procedure
    assert got.slot == slots[0]
    #: 🔴 **허가가 났어도 못 본 것은 못 본 것이다.**
    assert got.unchecked


@requires_official_db
@pytest.mark.real_card
def test_b02_an_unregistered_card_is_unknown_not_illegal(repository):
    """
    🔴 등재되지 않은 카드는 ``UNKNOWN`` 이다 — **금지가 아니다.**

    "조건을 모른다" 와 "특수 소환할 수 없다" 를 합치면, 구현되지 않은
    카드가 규칙상 불가로 집계된다.
    """
    from engine.hand_summon import HandSummonEligibility, assess_hand_summon

    state, _crown = _board(repository)
    other = _hand(state, GIRSU)
    got = assess_hand_summon(_view(state), 0, other.instance_id, 0)
    assert got.eligibility is HandSummonEligibility.UNKNOWN
    assert got.rule is None
    assert "등재" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b03_a_card_not_in_hand_is_illegal(repository):
    """패에 없으면 이 절차가 아니다 — 확인된 거절."""
    from engine.hand_summon import HandSummonEligibility, assess_hand_summon

    state = _blank(repository)
    _place(state, GALATEA, Zone.EMZONE, 0, Position.FACEUP_ATTACK)
    crown = _place(state, CROWN, Zone.MZONE, 4, Position.FACEUP_DEFENSE)
    got = assess_hand_summon(_view(state), 0, crown.instance_id, 0)
    assert got.eligibility is HandSummonEligibility.ILLEGAL
    assert "HAND" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b04_no_named_slot_is_illegal(repository):
    """
    칸을 지목하지 않으면 거절한다.

    🔴 **칸을 골라 주지 않는다.** 골라 주면 허가가 난 칸과 놓인 칸이
    갈릴 수 있고, 그것이 이 Phase 가 막으려는 일이다.
    """
    from engine.hand_summon import HandSummonEligibility, assess_hand_summon

    state, crown = _board(repository)
    got = assess_hand_summon(_view(state), 0, crown.instance_id, None)
    assert got.eligibility is HandSummonEligibility.ILLEGAL
    assert "칸" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b05_an_unpointed_zone_is_illegal(repository):
    """가리켜지지 **않는** 칸은 비어 있어도 거절한다."""
    from engine.hand_summon import (
        HandSummonEligibility, assess_hand_summon, hand_summon_slots,
    )

    state, crown = _board(repository)
    pointed = set(hand_summon_slots(_view(state), 0, CROWN))
    elsewhere = next(i for i in range(5) if i not in pointed)
    got = assess_hand_summon(_view(state), 0, crown.instance_id, elsewhere)
    assert got.eligibility is HandSummonEligibility.ILLEGAL
    assert "가리키지 않습니다" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b06_an_occupied_board_is_illegal(repository):
    """가리켜지는 칸이 **차 있으면** 놓을 수 없다."""
    from engine.hand_summon import (
        HandSummonEligibility, assess_hand_summon, hand_summon_slots,
    )

    state, crown = _board(repository)
    for index in range(5):
        _place(state, GIRSU, Zone.MZONE, index, Position.FACEUP_ATTACK)
    assert hand_summon_slots(_view(state), 0, CROWN) == ()
    got = assess_hand_summon(_view(state), 0, crown.instance_id, 0)
    assert got.eligibility is HandSummonEligibility.ILLEGAL
    assert "빈 메인 몬스터 존이 없습니다" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b07_the_turn_limit_is_per_card_name(repository):
    """
    🔴 턴 제한은 **카드명**에 걸린다 — 다른 개체도 함께 막힌다.

    ``SetCountLimit(1,id,…)`` 의 ``id`` 는 카드 ID 이므로, 패에 성관이 두
    장 있어도 이 방법으로는 한 번뿐이다.
    """
    from engine.hand_summon import (
        HAND_SUMMON_USE_KIND, HandSummonEligibility, assess_hand_summon,
        hand_summon_slots,
    )

    state, crown = _board(repository)
    second = _hand(state, CROWN)
    assert second.instance_id != crown.instance_id
    slots = hand_summon_slots(_view(state), 0, CROWN)
    #: 한 번 썼다고 적는다 — 소환은 하지 않는다 (판정만 본다).
    state.summon_uses.record(
        state.turn.turn_number, 0, CROWN, HAND_SUMMON_USE_KIND
    )
    for instance in (crown, second):
        got = assess_hand_summon(
            _view(state), 0, instance.instance_id, slots[0]
        )
        assert got.eligibility is HandSummonEligibility.ILLEGAL, got.reason
        assert "이미 썼습니다" in got.reason


@requires_official_db
@pytest.mark.real_card
def test_b08_an_attribute_only_limit_refuses(repository):
    """
    판에 걸린 **특수 소환 제한**을 그대로 반영한다.

    🔴 판정을 여기서 다시 적지 않는다 —
    :func:`~engine.summon_restriction.assess_special_summon_permission`
    하나가 답한다. 6-BN 의 첫 판은 관측의 줄을 번호로 읽어 **제한을 전부
    건너뛰었다**; 이 시험이 그 자리를 지킨다.
    """
    from engine.hand_summon import (
        HandSummonEligibility, assess_hand_summon, hand_summon_slots,
    )
    from engine.state.summon_limit import AttributeOnlyLimit

    state, crown = _board(repository)
    slots = hand_summon_slots(_view(state), 0, CROWN)
    #: 「빛 속성밖에 특수 소환할 수 없다」 — 성관은 빛 속성이 아니다.
    state.summon_limits.record(
        AttributeOnlyLimit(
            turn_number=state.turn.turn_number,
            player=0,
            attribute="LIGHT",
            source_card_id=GIRSU,
            ordinal=0,
            basis="시험용 — 제한이 실제로 읽히는지 재려고 직접 적었다.",
        )
    )
    got = assess_hand_summon(_view(state), 0, crown.instance_id, slots[0])
    assert got.eligibility is HandSummonEligibility.ILLEGAL, got.describe_ko()
    assert "LIGHT" in got.reason


# ======================================================================
# C. 검증기가 그 판정을 그대로 쓴다
# ======================================================================


def test_c01_special_summon_left_the_missing_rule_table():
    """
    🔴 ``SPECIAL_SUMMON`` 이 ``_MISSING_RULE`` 을 떠나고
    ``_COMPLETE_RULES`` 로 갔다 — 두 표가 **겹치지 않는다.**
    """
    from engine.action import PlayerActionKind
    from engine.action_validation import _COMPLETE_RULES, _MISSING_RULE

    assert PlayerActionKind.SPECIAL_SUMMON not in _MISSING_RULE
    assert PlayerActionKind.SPECIAL_SUMMON in _COMPLETE_RULES
    assert not (_COMPLETE_RULES & set(_MISSING_RULE))


@requires_official_db
@pytest.mark.real_card
def test_c02_the_validator_allows_the_registered_card(repository):
    """등재된 카드 · 지목된 칸 → ``VALID``."""
    from engine.action import PlayerAction
    from engine.hand_summon import hand_summon_slots
    from engine.validation import ActionValidity

    state, crown = _board(repository)
    duel = _duel(state)
    slots = hand_summon_slots(_view(state), 0, CROWN)
    action = PlayerAction.special_summon(
        actor=0, source=crown.instance_id, slot=slots[0]
    )
    verdict = duel.activation_validator(0).validate(action)
    assert verdict.validity is ActionValidity.VALID, verdict.reason


@requires_official_db
@pytest.mark.real_card
def test_c03_the_validator_still_answers_unknown_elsewhere(repository):
    """
    🔴 **범위가 넓어지지 않았다.** 등재되지 않은 카드의 특수 소환은
    여전히 ``UNKNOWN`` 이고, 없는 규칙의 이름도 그대로다.
    """
    from engine.action import PlayerAction
    from engine.action_validation import SPECIAL_SUMMON_CONDITION_RULE
    from engine.validation import ActionValidity

    state, _crown = _board(repository)
    other = _hand(state, GIRSU)
    duel = _duel(state)
    for slot in (None, 0):
        action = PlayerAction.special_summon(
            actor=0, source=other.instance_id, slot=slot
        )
        verdict = duel.activation_validator(0).validate(action)
        assert verdict.validity is ActionValidity.UNKNOWN, verdict.reason
        assert verdict.missing_rule == SPECIAL_SUMMON_CONDITION_RULE


@requires_official_db
@pytest.mark.real_card
def test_c04_a_non_zone_target_is_malformed(repository):
    """
    대상 하나가 **칸이 아니면** 거절한다.

    수만 맞추고 종류를 보지 않으면 ``INSTANCE`` 대상 하나가 칸을 지목한
    것으로 읽힌다.
    """
    from engine.action import PlayerAction, PlayerActionKind
    from engine.action_target import ActionTarget
    from engine.validation import ActionValidity, ValidationCode

    state, crown = _board(repository)
    duel = _duel(state)
    action = PlayerAction(
        kind=PlayerActionKind.SPECIAL_SUMMON,
        actor=0,
        source=crown.instance_id,
        targets=(ActionTarget.instance(crown.instance_id),),
    )
    verdict = duel.activation_validator(0).validate(action)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.TARGET_KIND_INVALID


# ======================================================================
# D. 절차 — 지목된 칸에 앞면 수비 표시로
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_d01_it_lands_face_up_defense_in_the_named_slot(repository):
    """실측 — 패에서 **그 칸으로** 옮겨지고 표시 형식이 수비다."""
    from engine.action import PlayerAction
    from engine.hand_summon import HAND_SUMMON_USE_KIND, hand_summon_slots

    state, crown = _board(repository)
    duel = _duel(state)
    slot = hand_summon_slots(_view(state), 0, CROWN)[0]
    step = duel.apply(
        PlayerAction.special_summon(
            actor=0, source=crown.instance_id, slot=slot
        )
    )
    assert step.accepted, step.reason
    landed = state.zone(0, Zone.MZONE).slot(slot)
    assert landed is not None and landed.card_id == CROWN
    assert landed.position is Position.FACEUP_DEFENSE
    assert CROWN not in [card.card_id for card in state.player(0).hand]
    #: 🔴 **이 방법으로 썼다고 적힌다** — 판정이 읽는 이름과 같다.
    assert (0, CROWN, HAND_SUMMON_USE_KIND, 1) in _view(state).summons_by_name


@requires_official_db
@pytest.mark.real_card
def test_d02_the_second_one_is_refused_in_the_same_turn(repository):
    """
    실측 — 한 번 쓴 뒤 같은 턴의 두 번째 성관은 **후보가 되지 않는다.**

    기록을 손으로 적지 않는다 (B07 이 그쪽을 본다) — 실제로 한 장 소환한
    뒤를 본다.
    """
    from engine.action import PlayerAction, PlayerActionKind
    from engine.hand_summon import HandSummonEligibility, assess_hand_summon

    state, crown = _board(repository)
    #: 두 번째 칸을 만들어 둔다 — 칸이 없어서 막히는 것과 턴 제한으로
    #: 막히는 것을 가르기 위해서다. 🔴 엑스트라 몬스터 존은 이 모델에서
    #: 한 칸뿐이므로 (실측: ``EMZONE 의 칸은 0..0``) 두 번째 링크 몬스터를
    #: **메인 몬스터 존**에 세워 옆 칸을 가리키게 한다.
    _place(state, SIDE_MARKER_LINK, Zone.MZONE, 2, Position.FACEUP_ATTACK)
    second = _hand(state, CROWN)
    duel = _duel(state)
    from engine.hand_summon import hand_summon_slots

    slots = hand_summon_slots(_view(state), 0, CROWN)
    assert len(slots) >= 2, slots
    step = duel.apply(
        PlayerAction.special_summon(
            actor=0, source=crown.instance_id, slot=slots[0]
        )
    )
    assert step.accepted, step.reason
    left = [s for s in hand_summon_slots(_view(state), 0, CROWN)]
    assert left, "두 번째 칸이 남아 있어야 이 시험이 턴 제한을 잰다"
    got = assess_hand_summon(_view(state), 0, second.instance_id, left[0])
    assert got.eligibility is HandSummonEligibility.ILLEGAL, got.reason
    assert "이미 썼습니다" in got.reason
    assert not [
        a for a in duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.SPECIAL_SUMMON
    ]


@requires_official_db
@pytest.mark.real_card
def test_d03_an_occupied_named_slot_stops_before_touching_the_board(
    repository
):
    """
    🔴 지목한 칸이 차 있으면 **다른 칸으로 옮겨 놓지 않는다.**

    조용히 옮기면 허가가 난 칸과 놓인 칸이 갈리고, 리플레이가 거짓을
    적는다.
    """
    from engine.action import PlayerAction
    from engine.special_summon import SpecialSummonError, hand_summon_procedure

    state, crown = _board(repository)
    _place(state, GIRSU, Zone.MZONE, 0, Position.FACEUP_ATTACK)
    procedure = hand_summon_procedure(CROWN)
    action = PlayerAction.special_summon(
        actor=0, source=crown.instance_id, slot=0
    )
    with pytest.raises(SpecialSummonError) as caught:
        procedure.plan(state, action, slot=0)
    assert "비어 있지 않습니다" in str(caught.value)
    #: 판은 그대로다 — 성관이 아직 패에 있다.
    assert CROWN in [card.card_id for card in state.player(0).hand]


@requires_official_db
@pytest.mark.real_card
def test_d04_the_generic_special_summon_path_did_not_change(repository):
    """
    🔴 **공통 경로는 한 글자도 바뀌지 않았다.**

    칸을 주지 않으면 가장 작은 빈 칸을 쓰고 (STRUCTURAL-41) 표시 형식은
    앞면 공격이다 (STRUCTURAL-61) — 효과에 의한 특수 소환이 그 길로 간다.
    """
    from engine.special_summon import (
        SPECIAL_SUMMON_POSITION, SPECIAL_SUMMON_PROCEDURE,
    )

    state = _blank(repository)
    _place(state, GIRSU, Zone.MZONE, 0, Position.FACEUP_ATTACK)
    girsu = _hand(state, GIRSU)
    placement = SPECIAL_SUMMON_PROCEDURE.plan_for(state, girsu.instance_id, 0)
    assert placement.slot == 1
    assert placement.position is SPECIAL_SUMMON_POSITION
    assert SPECIAL_SUMMON_POSITION is Position.FACEUP_ATTACK


# ======================================================================
# E. 후보 생성 — 가리켜지는 빈 칸마다 하나
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_e01_one_candidate_per_pointed_free_slot(repository):
    """후보의 수가 **칸의 수**와 같고, 각 후보가 자기 칸을 들고 간다."""
    from engine.action import PlayerActionKind
    from engine.hand_summon import hand_summon_slots

    state, crown = _board(repository)
    _place(state, SIDE_MARKER_LINK, Zone.MZONE, 2, Position.FACEUP_ATTACK)
    duel = _duel(state)
    slots = hand_summon_slots(_view(state), 0, CROWN)
    offered = [
        a for a in duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.SPECIAL_SUMMON
    ]
    assert len(offered) == len(slots) >= 2
    assert sorted(a.targets[0].index for a in offered) == sorted(slots)


@requires_official_db
@pytest.mark.real_card
def test_e02_the_candidate_count_is_the_same_under_both_alignments(
    repository
):
    """
    🔴 **정렬을 시험이 고르지 않는다.** 두 정렬 모두에서 "가리켜지는 빈
    칸" 의 수가 같아야 후보의 수가 정렬에 달려 있지 않다고 말할 수 있다.

    🔴 **칸 번호는 같지 않다** — 그것이 이 저장소가 못 읽은 것이고
    (:data:`~engine.link_zone.POINTED_ZONE_SOURCE_GAP`), 숨기지 않는다.
    """
    from engine.link_zone import EMZ_ALIGNMENTS, pointed_zones

    state, _crown = _board(repository)
    counts = {
        name: len(pointed_zones(_view(state), 0, name))
        for name in EMZ_ALIGNMENTS
    }
    assert len(set(counts.values())) == 1, counts
    numbers = {
        name: pointed_zones(_view(state), 0, name) for name in EMZ_ALIGNMENTS
    }
    #: 실측 — 왼쪽 정렬은 0번, 오른쪽 정렬은 2번을 가리킨다.
    assert len({tuple(v) for v in numbers.values()}) == 2, numbers


@requires_official_db
@pytest.mark.real_card
def test_e03_no_pointed_zone_is_withheld_with_a_reason(repository):
    """
    가리켜지는 빈 칸이 없으면 **보류에 이유가 남는다.**

    🔴 "물어봤고 막혔다" 와 "물어보지도 않았다" 는 다른 사실이다.
    """
    from engine.action import PlayerActionKind

    state = _blank(repository)
    _hand(state, CROWN)
    duel = _duel(state)
    legal = duel.legal_actions(0)
    assert not [
        a for a in legal.allowed
        if a.kind is PlayerActionKind.SPECIAL_SUMMON
    ]
    held = [
        w for w in legal.withheld
        if w.kind is PlayerActionKind.SPECIAL_SUMMON
    ]
    assert len(held) == 1, [w.reason for w in held]
    assert "빈 메인 몬스터 존이 없어" in held[0].reason


@requires_official_db
@pytest.mark.real_card
def test_e04_an_unregistered_hand_card_is_not_withheld_twice(repository):
    """
    🔴 등재되지 않은 패 카드를 **보류에 또 적지 않는다.**

    그 사실은 공통 경로가 이미 ``UNKNOWN`` 으로 적는다 — 여기서 또 적으면
    같은 사유가 두 줄이 된다.
    """
    from engine.action import PlayerActionKind

    state = _blank(repository)
    _hand(state, GIRSU)
    duel = _duel(state)
    held = [
        w for w in duel.legal_actions(0).withheld
        if w.kind is PlayerActionKind.SPECIAL_SUMMON
    ]
    assert held == []


# ======================================================================
# F. 체인을 만들지 않는다
# ======================================================================


def test_f01_the_procedure_layer_knows_nothing_of_chains():
    """
    🔴 ``EFFECT_SPSUMMON_PROC`` 는 **소환 절차**이고 효과가 아니다.

    체인에 올라가지 않고 상대의 응답 창도 열리지 않는다. 그 사실을
    import 로 지킨다 — 글로 적은 약속은 깨져도 조용하다.
    """
    #: 🔴 **import 줄만 본다.** 설명문에는 "체인을 만들지 않는다" 가
    #: 적혀 있고, 글자만 세면 그 설명이 시험을 깨뜨린다.
    root = Path(__file__).resolve().parent.parent / "engine"
    for name in ("hand_summon.py", "special_summon.py"):
        lines = [
            line.strip()
            for line in (root / name).read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not [
            line for line in lines
            if "engine.chain" in line
            or "ChainResolver" in line
            or "TriggerCollector" in line
        ], (name, lines)


# ======================================================================
# G. 후속은 기존 판정이 답한다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_g01_the_follow_up_comes_from_the_existing_material_judgment(
    repository
):
    """
    성관이 선 뒤 **무엇을 링크 소환할 수 있는가**는 기존 소재 판정이
    답한다 (:func:`~engine.link_rules.assess_link_materials`).

    🔴 이 Phase 는 카드 순서도 최종 몬스터도 정답으로 넣지 않는다 — 여기서
    롱기르수를 쓰는 것은 **판정이 그렇다고 답하는지** 재기 위해서다.
    """
    from engine.action import PlayerAction
    from engine.hand_summon import hand_summon_slots
    from engine.link_rules import assess_link_materials

    state, crown = _board(repository)
    longirsu = state.create_instance(LONGIRSU, owner=0, zone=Zone.EXTRA)
    duel = _duel(state)
    slot = hand_summon_slots(_view(state), 0, CROWN)[0]
    assert duel.apply(
        PlayerAction.special_summon(
            actor=0, source=crown.instance_id, slot=slot
        )
    ).accepted

    galatea = next(
        card for card in state.zone(0, Zone.EMZONE) if card is not None
    )
    standing = state.zone(0, Zone.MZONE).slot(slot)
    got = assess_link_materials(
        _view(state), 0, longirsu.instance_id,
        (galatea.instance_id, standing.instance_id),
    )
    assert got.permits_procedure, got.reason
    #: 🔴 **기르수는 소재가 아니다** — 묘지에 있던 기르수가 여기에 끼어
    #: 들지 않는다는 사실이 이 판에서 확인된다 (필드의 두 장뿐이다).
    assert {
        card.card_id for card in state.zone(0, Zone.MZONE) if card is not None
    } == {CROWN}


@requires_official_db
@pytest.mark.real_card
def test_g02_a_token_joins_only_if_the_material_rule_admits_it(repository):
    """
    토큰도 **소재 조건을 만족할 때만** 소재가 된다.

    🔴 토큰을 특별히 넣거나 빼지 않는다 — **같은 판정에게 묻는다.**
    롱기르수는 「오르페골」 몬스터를 포함하는 **효과 몬스터** 2장 이상을
    요구하고, 성유물 토큰은 통상 몬스터 토큰이므로 (``type`` 에
    ``NORMAL|TOKEN``) 그 조건을 지나지 못한다.

    실측한 전개의 판에도 이 토큰이 서 있다 — 그래서 "쓰이지 않았다" 가
    우연이 아니라 **판정의 답**이라는 것을 여기서 확인한다.
    """
    from engine.hand_summon import hand_summon_slots
    from engine.link_rules import assess_link_materials, material_rule_for
    from engine.token import TOKEN_RULES, create_token, plan_token

    rule = material_rule_for(LONGIRSU)
    assert rule is not None
    assert "효과 몬스터" in rule.describe_ko()

    state, crown = _board(repository)
    longirsu = state.create_instance(LONGIRSU, owner=0, zone=Zone.EXTRA)
    galatea = next(
        card for card in state.zone(0, Zone.EMZONE) if card is not None
    )
    #: 성유물 토큰을 실제로 놓는다 (전개에 나오는 그 토큰이다).
    #: 🔴 **가리켜지는 칸을 비워 둔다** (``taken``). 토큰도 가장 작은 빈
    #: 칸을 쓰므로 (STRUCTURAL-41) 비워 두지 않으면 성관이 설 칸을
    #: 토큰이 먹고, 이 시험은 "칸이 없다" 를 재게 된다 (실측으로 잡았다).
    pointed = hand_summon_slots(_view(state), 0, CROWN)
    assert pointed, "가리켜지는 빈 칸이 없다 — 전제가 깨졌다"
    plan = plan_token(
        state, TOKEN_RULES[0], controller=0, summoner=0,
        position=Position.FACEUP_ATTACK,
        taken={0: set(pointed)},
    )
    token, _created, _summoned = create_token(state, plan)

    #: 🔴 **갈라테아 + 토큰은 소재가 되지 않는다** — 장수는 맞는데
    #: 조건이 맞지 않는다.
    with_token = assess_link_materials(
        _view(state), 0, longirsu.instance_id,
        (galatea.instance_id, token.instance_id),
    )
    assert not with_token.permits_procedure, with_token.reason

    #: 같은 판에서 **성관을 세우면** 같은 판정이 허락한다 — 거절이 "토큰이
    #: 미지원" 이어서가 아니라 조건 때문이라는 뜻이다.
    from engine.action import PlayerAction

    slot = hand_summon_slots(_view(state), 0, CROWN)[0]

    assert _duel(state).apply(
        PlayerAction.special_summon(
            actor=0, source=crown.instance_id, slot=slot
        )
    ).accepted
    standing = state.zone(0, Zone.MZONE).slot(slot)
    with_crown = assess_link_materials(
        _view(state), 0, longirsu.instance_id,
        (galatea.instance_id, standing.instance_id),
    )
    assert with_crown.permits_procedure, with_crown.reason
