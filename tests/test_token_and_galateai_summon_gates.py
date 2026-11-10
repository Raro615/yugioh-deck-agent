"""
Phase 6-AP — **필드의 토큰 · 갈라테아i 가 다른 소환 판정을 가리던 자리.**

이 파일이 재는 것
-----------------
디스코드 실행에서 나온 두 ``UNKNOWN`` 과, 토큰의 링크 소재 처리다.

=========================================  ===============================
``MZONE 의 46647145 에 대해 확인된 것이 없어``  A — 성유물 토큰
``EMZONE 의 48835607 에 대해 확인된 것이 없어``  B — 오르페골 갈라테아i
토큰이 링크 소재가 되는가                      C — 이미 구현되어 있었다
=========================================  ===============================

A · B 는 **같은 계층**이다 — :meth:`~engine.effect.ruling.BoardRuling.
_interference` 가 판을 훑다가 **확인된 사실이 없는 앞면 카드**를 만나면 그
자리에서 ``UNKNOWN`` 을 돌려준다 (ADR-006 의 기본값). 고친 것은 판정이
아니라 **그 사실을 어디서 읽는가** 다.

- A: :func:`~engine.effect.ruling.token_facts` 가 6-AF 에 **적혀 있었고
  production 에서 불리지 않았다.** 6-AP 가
  :func:`~engine.effect.ruling.rulebook_facts` 에 연결했다.
- B: 갈라테아i 가 :data:`~engine.effect.library.OPERATION_RULINGS` 에
  **없었다.** 6-AP 가 ``c48835607.lua`` 의 등록 효과 다섯 개를 읽고 한 줄을
  더했다.

🔴 **둘 다 "UNKNOWN 을 OK 로 바꾼 것" 이 아니다.** 실제 금지 · 실제 제한 ·
등록되지 않은 다른 카드는 그대로다 — ``D`` 묶음이 그것을 센다.

실제와 합성
-----------
====================================================  ==================
``46647145`` · ``48835607`` · ``57835716`` 경로 전체    🔴 실제 카드
``42009836`` 파슬 다이너 파키세팔로 (실제 금지)          🔴 실제 카드
``4055337`` 오르페골 트로이메어 (판정 등록 없음)          🔴 실제 카드
초기 판 구성 (필드 · 묘지 · 덱에 카드 놓기)              **테스트의 구성**
====================================================  ==================
"""

from __future__ import annotations

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.condition import ConditionResult
from engine.effect.library import (
    EFFECT_LIBRARY,
    GALATEA,
    GALATEA_I,
    OPERATION_RULINGS,
    entry_for,
)
from engine.effect.ruling import (
    TOKEN_NOT_PLAIN,
    TOKEN_RULE,
    BoardRuling,
    RuleBasis,
    RuleQuestion,
    rulebook_facts,
    token_facts,
)
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.link_rules import LinkMaterialEligibility, assess_link_materials
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db, settle_chain

GIRSU = 69811710
DIBER = 57835716
SKELETON = 21441617
TOKEN = 46647145
FEATHERMAN = 21844576
#: 🔴 **실제로 특수 소환을 금지하는** 카드 — 손으로 읽은 표에
#: ``prohibits=True`` 로 있다.
PACHYCEPHALO = 42009836
#: 🔴 **판정 등록이 없는** 실제 「오르페골」 몬스터 (트로이메어, LINK-2).
#: 🔴 이 자리의 카드는 등록소가 늘 때마다 바뀐다 — 재는 것은 "등록되지 않은
#: 카드는 자동 허가되지 않는다" 이고 특정 카드가 아니다.
UNREGISTERED = 4055337

DIBER_EFFECT = EffectRef(DIBER, 0)
P0, P1 = 0, 1

pytestmark = requires_official_db


# ======================================================================
# 공용 — **시작 상태**만 만든다
# ======================================================================
def _board(
    repository,
    *,
    mine=(),
    theirs=(),
    emzone=(),
    grave=(),
    deck=(),
    extra=(),
    hand=(),
    chooser=None,
):
    """
    **시작 상태**를 만든다. 첫 행동 뒤의 모든 변화는 엔진이 만든다.

    토큰은 ``POS_FACEUP_DEFENSE`` 로 놓는다 — 기르수 ③ 이 실제로 그렇게
    특수 소환한다 (``c69811710.lua`` 의 ``s.tkop``).
    """
    from app.main import opening_wiring

    state = GameState.create(
        repository,
        decks=(list(deck) + [FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )

    def place(card_id, seat, zone, index):
        position = (
            Position.FACEUP_DEFENSE
            if card_id == TOKEN
            else Position.FACEUP_ATTACK
        )
        instance = state.create_instance(card_id, owner=seat, zone=zone)
        state.move(
            instance, zone, to_player=seat, index=index, position=position
        )
        return instance.instance_id

    mine_ids = [place(c, P0, Zone.MZONE, i) for i, c in enumerate(mine)]
    their_ids = [place(c, P1, Zone.MZONE, i) for i, c in enumerate(theirs)]
    em_ids = [place(c, P0, Zone.EMZONE, i) for i, c in enumerate(emzone)]
    grave_ids = []
    for card_id in grave:
        instance = state.create_instance(card_id, owner=P0, zone=Zone.GRAVE)
        state.move(instance, Zone.GRAVE, to_player=P0)
        grave_ids.append(instance.instance_id)
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    for card_id in hand:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    state.turn.turn_number = 3
    state.turn.set_phase(Phase.MAIN1)
    wired, triggers = opening_wiring(repository, None)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        triggers=triggers,
        **duel_components(chooser=chooser if chooser is not None else wired),
    )
    return duel, mine_ids, their_ids, em_ids, grave_ids, extra_ids


def _zone_ids(duel, zone, seat=P0):
    return [card.card_id for card in duel.state.zone(seat, zone)]


def _diber_offer(duel, source):
    duel.advance()
    for action in duel.legal_actions(P0).allowed:
        if (
            action.kind is PlayerActionKind.ACTIVATE_EFFECT
            and action.source == source
            and action.effect_ref == DIBER_EFFECT
        ):
            return action
    return None


def _diber_gate(duel, source):
    action = PlayerAction.activate_effect(
        actor=P0, source=source, effect_ref=DIBER_EFFECT
    )
    return duel._activation_gate(
        action, validator=duel.activation_validator(P0), selections=()
    )


def _deck_candidate_verdict(duel, card_id=SKELETON):
    """해결 중 후보 관문에 **같은 관측으로** 직접 묻는다."""
    state = duel.state
    spec = entry_for(DIBER_EFFECT).definition.targets[0].spec
    granted = GameStateView.from_state(
        state, viewer=P0, looked_at=spec.looked_at_zones()
    )
    candidate = [
        c for c in state.zone(P0, Zone.DECK) if c.card_id == card_id
    ][0]
    return BoardRuling(granted, OPERATION_RULINGS).explain_special_summon(
        candidate.instance_id
    )


def _link_offers(duel, summoned):
    duel.advance()
    return [
        tuple(duel.state.find_instance(m).card_id for m in action.materials)
        for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.LINK_SUMMON
        and duel.state.find_instance(action.source).card_id == summoned
    ]


# ======================================================================
# A. 토큰 — 룰북 한 줄이 production 에 연결되었다
# ======================================================================
def test_a01_the_token_rule_is_now_reachable_from_the_observation(repository):
    """
    🔴 **이 Phase 의 본문 ①.** 관측된 토큰 정의에서
    :func:`rulebook_facts` 가 :func:`token_facts` 의 답을 돌려준다.

    6-AF 가 그 함수를 적어 두고 production 에서 부르지 않았고, 그래서
    필드에 토큰이 있는 판은 **전부** ``UNKNOWN`` 이었다.
    """
    duel, _m, _t, _e, _g, _x = _board(repository, mine=(TOKEN,))
    view = duel.view(P0)
    card = [c for c in view.player(P0).zone(Zone.MZONE).cards if c][0]
    assert card.card_id == TOKEN

    facts = rulebook_facts(card.definition)
    assert facts is not None, "토큰의 룰북 사실이 연결되지 않았습니다"
    assert facts.card_id == TOKEN
    #: 🔴 **"안 막는다" 의 근거가 룰북이다** — 공짜가 아니다.
    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.RULEBOOK
    assert facts.restriction_note.strip()
    #: 🔴 **모든 제약이 없다고 적지 않았다** — 갈 수 없는 자리는 거짓이고,
    #: 제외 · 특수 소환 가능 여부는 **답하지 않았다**.
    assert (
        facts.answer_for(RuleQuestion.MAY_BE_SENT_TO_GRAVE).answer
        is ConditionResult.FALSE
    )
    assert (
        facts.answer_for(RuleQuestion.MAY_BE_RETURNED_TO_HAND).answer
        is ConditionResult.FALSE
    )
    assert facts.answer_for(RuleQuestion.MAY_BE_BANISHED) is None
    assert facts.answer_for(RuleQuestion.MAY_BE_SPECIAL_SUMMONED) is None
    #: 그리고 그 답이 토큰의 줄에서 나왔다는 것이 글자로 남는다.
    assert TOKEN_RULE in facts.answer_for(
        RuleQuestion.MAY_BE_SENT_TO_GRAVE
    ).note


def test_a02_an_effect_token_would_not_be_answered():
    """
    🔴 **"토큰이니까 제약이 없다" 를 쓰지 않았다.** 효과를 가진 토큰은 이
    줄이 답하지 않는다.

    실측: ``data/cards.cdb`` 의 토큰은 241장이고 그중 238장이 정확히
    ``MONSTER|NORMAL|TOKEN`` 이며 (스크립트가 한 장도 없다), 남은 3장은
    ``type`` 이 ``0x4000`` 뿐인 자리표시자다. 그래서 지금 이 갈래에 걸리는
    카드는 **0장**이지만, 생기는 날 조용히 "효과 없음" 으로 읽히면 틀린다.
    """
    assert "EFFECT" in TOKEN_NOT_PLAIN
    assert "PENDULUM" in TOKEN_NOT_PLAIN

    class _View:
        card_id = 999_999
        name = "효과를 가진 토큰"
        is_monster = True
        is_extra_deck = False
        type_names = ("MONSTER", "NORMAL", "TOKEN", "EFFECT")

    assert rulebook_facts(_View()) is None
    #: 효과가 없는 쪽은 답한다 — 갈림이 **종류**에 있다.
    class _Plain(_View):
        type_names = ("MONSTER", "NORMAL", "TOKEN")

    answered = rulebook_facts(_Plain())
    assert answered is not None
    assert answered.restricts_others is False


@pytest.mark.real_card
def test_a03_a_token_on_the_field_no_longer_hides_the_deck_candidate(
    repository,
):
    """
    🔴 **디스코드 증상 A 가 사라졌다.** 필드에 성유물 토큰이 있어도 디베르
    ① 의 덱 후보 판정이 ``TRUE`` 이고, 발동이 후보 목록에 오른다.

    수정 전 실측: 후보 목록에서 빠지고 보류 사유가
    ``gated-candidate-eligibility`` · "MZONE 의 46647145 에 대해 확인된
    것이 없어, 그것이 막는지 알 수 없습니다" 였다.
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository, mine=(GIRSU, TOKEN), grave=(DIBER,), deck=(SKELETON,)
    )
    told = _deck_candidate_verdict(duel)
    assert told.answer is ConditionResult.TRUE, told.reason
    assert str(TOKEN) not in told.reason

    assert _diber_offer(duel, grave[0]) is not None
    #: 🔴 **후보 목록과 관문이 같은 답을 낸다.**
    assert _diber_gate(duel, grave[0]).validity is ActionValidity.VALID


@pytest.mark.real_card
def test_a04_the_opponents_token_is_also_judged(repository):
    """
    🔴 **상대 필드의 토큰도 같은 자리다.** 기르수 ③ 은 **서로의** 필드에
    토큰을 만들고 (``SpecialSummonStep(tk2,0,tp,1-tp,…)``), 판을 훑는 관문은
    양쪽을 본다.
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository, mine=(GIRSU,), theirs=(TOKEN,), grave=(DIBER,), deck=(SKELETON,)
    )
    assert _deck_candidate_verdict(duel).answer is ConditionResult.TRUE
    assert _diber_offer(duel, grave[0]) is not None


# ======================================================================
# B. 갈라테아i — 한 줄을 읽고 등록했다
# ======================================================================
def test_b01_galatea_i_has_a_read_fact_that_claims_only_one_thing():
    """
    🔴 **이 Phase 의 본문 ②.** 갈라테아i 가 등록소에 있고, 그 줄이 주장하는
    것은 **「필드에 있다는 것만으로 남의 조작을 막는가」 하나**다.

    🔴 **그 카드의 효과를 구현했다는 뜻이 아니다** — ``e3``(패에 넣기) ·
    ``e4``(묘지에서 자신을 특수 소환) 는 등재되어 있지 않다.
    """
    facts = OPERATION_RULINGS.facts_for(GALATEA_I)
    assert facts is not None, "갈라테아i 가 등록소에 없습니다"
    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.CARD_TEXT
    note = facts.restriction_note
    #: 다섯 효과를 하나하나 적었다 — "텍스트에 없다" 를 공짜로 쓰지 않았다.
    for needle in (
        "c48835607.lua",
        "EVENT_SPSUMMON_SUCCESS",
        "SUMMON_TYPE_LINK",
        "EFFECT_CANNOT_BE_XYZ_MATERIAL",
        "LINK_SUMMON_ONCE_PER_TURN",
    ):
        assert needle in note, needle
    #: 🔴 **구현했다고 적지 않았다** — 그 낱말이 나오는 자리가 **부정문**
    #: 이어야 한다 (낱말을 금지하면 부정문도 쓸 수 없다).
    for sentence in note.split("."):
        if "전부 구현했다" in sentence:
            assert "아니다" in sentence, sentence
    assert "등재되지 않았고" in note
    #: 🔴 그리고 그것이 사실이다 — 등재표에 그 카드의 효과가 하나도 없다.
    assert GALATEA_I not in {
        entry.definition.effect_ref.card_id for entry in EFFECT_LIBRARY
    }
    #: 질문별 답은 **하나도 적지 않았다** (읽지 않은 것을 적지 않는다).
    assert facts.answers == {}


@pytest.mark.real_card
def test_b02_galatea_i_on_the_field_no_longer_hides_the_deck_candidate(
    repository,
):
    """
    🔴 **디스코드 증상 B 가 사라졌다.** 엑스트라 몬스터 존에 갈라테아i 가
    있어도 디베르 ① 의 덱 후보 판정이 ``TRUE`` 다.

    수정 전 실측: "EMZONE 의 48835607 에 대해 확인된 것이 없어, 그것이
    막는지 알 수 없습니다".
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository,
        mine=(GIRSU,),
        emzone=(GALATEA_I,),
        grave=(DIBER,),
        deck=(SKELETON,),
    )
    told = _deck_candidate_verdict(duel)
    assert told.answer is ConditionResult.TRUE, told.reason
    assert _diber_offer(duel, grave[0]) is not None
    assert _diber_gate(duel, grave[0]).validity is ActionValidity.VALID


@pytest.mark.real_card
def test_b03_both_at_once_are_judged(repository):
    """토큰과 갈라테아i 가 **함께** 있는 판도 같다."""
    duel, _m, _t, _e, grave, _x = _board(
        repository,
        mine=(GIRSU, TOKEN),
        theirs=(TOKEN,),
        emzone=(GALATEA_I,),
        grave=(DIBER,),
        deck=(SKELETON,),
    )
    assert _deck_candidate_verdict(duel).answer is ConditionResult.TRUE
    assert _diber_offer(duel, grave[0]) is not None


# ======================================================================
# C. 토큰의 링크 소재 — **이미 구현되어 있었다.** 실제로 확인한다
# ======================================================================
@pytest.mark.real_card
def test_c01_a_token_is_a_legal_material_where_the_condition_allows_it(
    repository,
):
    """
    🔴 **일괄 허가가 아니다.** 갈라테아i 의 소재 조건이 「「오르페골」 또는
    「성유물」 몬스터 1장」 이고 (``c48835607.lua`` 의
    ``Link.AddProcedure(..., Card.IsSetCard, {SET_ORCUST,SET_WORLD_LEGACY},
    1, 1)``), 성유물 토큰은 setcode ``0xfe`` 이므로 **그 조건으로** 소재가
    된다 — 토큰이라서가 아니다.

    후보 목록과 실행이 같은 답을 낸다.
    """
    duel, mine, _t, _e, _g, extra = _board(
        repository, mine=(TOKEN,), extra=(GALATEA_I,)
    )
    #: ① 판정 함수가 합법이라고 답한다.
    view = GameStateView.from_state(duel.state, viewer=P0)
    verdict = assess_link_materials(view, P0, extra[0], (mine[0],))
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason
    #: ② 후보 목록에 그 조합이 있다.
    assert (TOKEN,) in _link_offers(duel, GALATEA_I)
    #: ③ 실행도 같다.
    step = duel.apply(
        PlayerAction.link_summon(
            actor=P0, source=extra[0], materials=(mine[0],)
        )
    )
    assert step.accepted is True, step.reason
    assert _zone_ids(duel, Zone.EMZONE) == [GALATEA_I]


@pytest.mark.real_card
def test_c02_an_effect_monster_condition_still_refuses_the_token(repository):
    """
    🔴 **효과 몬스터를 요구하는 조건은 토큰을 거절한다.** 갈라테아는
    「효과 몬스터 2장 (「오르페골」 몬스터를 포함)」 이고, 토큰은
    ``TYPE_NORMAL`` 이다.

    후보 목록에 **오르지 않고**, 손으로 만든 행동도 거절되며 판은 그대로다.
    """
    duel, mine, _t, _e, _g, extra = _board(
        repository, mine=(GIRSU, TOKEN), extra=(GALATEA,)
    )
    #: ① 후보 목록에 토큰이 든 조합이 없다.
    offers = _link_offers(duel, GALATEA)
    assert all(TOKEN not in combo for combo in offers), offers
    #: ② 손으로 만들어 넣어도 거절이다.
    before = duel.state.state_hash()
    step = duel.apply(
        PlayerAction.link_summon(
            actor=P0, source=extra[0], materials=tuple(mine)
        )
    )
    assert step.accepted is False
    assert step.code is ValidationCode.LINK_MATERIAL_INVALID
    assert "효과 몬스터가 아닙니다" in step.reason
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_c03_the_opponents_token_is_not_my_material(repository):
    """
    🔴 **상대 필드의 토큰을 별도 허가 없이 쓰지 않는다.** 링크 소재는
    자신이 컨트롤하는 몬스터다.
    """
    duel, mine, theirs, _e, _g, extra = _board(
        repository, mine=(GIRSU,), theirs=(TOKEN,), extra=(GALATEA_I,)
    )
    #: ① 후보 목록에 상대 토큰이 없다 — 내 기르수만 나온다.
    offers = _link_offers(duel, GALATEA_I)
    assert offers == [(GIRSU,)], offers
    #: ② 손으로 만들어 넣으면 거절이고 판은 그대로다.
    before = duel.state.state_hash()
    step = duel.apply(
        PlayerAction.link_summon(
            actor=P0, source=extra[0], materials=(theirs[0],)
        )
    )
    assert step.accepted is False
    assert step.code is ValidationCode.LINK_MATERIAL_INVALID
    assert "P1 의 몬스터" in step.reason
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_c04_a_material_token_vanishes_and_is_not_reusable(repository):
    """
    🔴 **소재로 쓴 토큰은 어디에도 남지 않는다.** 묘지 · 제외 · 패 · 덱 ·
    엑스트라 덱 어디에도 없고, 개체 자체가 판에서 사라진다.

    🔴 **상대 필드의 토큰은 그대로 있다** — 내 소재가 아니었다.
    """
    duel, mine, theirs, _e, _g, extra = _board(
        repository, mine=(TOKEN,), theirs=(TOKEN,), extra=(GALATEA_I,)
    )
    assert duel.apply(
        PlayerAction.link_summon(
            actor=P0, source=extra[0], materials=(mine[0],)
        )
    ).accepted is True

    state = duel.state
    for zone in (
        Zone.MZONE,
        Zone.EMZONE,
        Zone.GRAVE,
        Zone.REMOVED,
        Zone.HAND,
        Zone.DECK,
        Zone.EXTRA,
    ):
        assert TOKEN not in _zone_ids(duel, zone), zone
    #: 🔴 개체가 **판에서** 사라졌다 — 다른 존에 숨어 있지 않다.
    assert state.find_instance(mine[0]) is None
    #: 🔴 상대의 토큰은 건드리지 않았다.
    assert _zone_ids(duel, Zone.MZONE, P1) == [TOKEN]
    assert state.find_instance(theirs[0]) is not None
    #: 기록이 **소멸**이라고 적는다 — 묘지로 보냈다고 적지 않는다.
    said = " ".join(str(event) for event in duel.journal)
    assert "소멸" in said
    assert "어느 존에도 가지 않음" in said
    #: 그리고 그 뒤에 링크 소환이 적힌다.
    assert "link 소환" in said


@pytest.mark.real_card
def test_c05_a_fork_does_not_leak_the_vanished_token(repository):
    """🔴 **사본에서 소재로 쓴 토큰이 원본에 남아 있다** (분기 격리)."""
    from agent.simulation import Simulator

    duel, mine, _t, _e, _g, extra = _board(
        repository, mine=(TOKEN,), extra=(GALATEA_I,)
    )
    before = duel.state.state_hash()
    fork = Simulator(duel=duel)._fork()
    fork_mine = [
        c.instance_id for c in fork.state.zone(P0, Zone.MZONE)
        if c.card_id == TOKEN
    ][0]
    fork_extra = [c.instance_id for c in fork.state.zone(P0, Zone.EXTRA)][0]
    assert fork.apply(
        PlayerAction.link_summon(
            actor=P0, source=fork_extra, materials=(fork_mine,)
        )
    ).accepted is True

    assert [c.card_id for c in fork.state.zone(P0, Zone.EMZONE)] == [GALATEA_I]
    assert fork.state.find_instance(fork_mine) is None
    #: 🔴 **원본은 한 글자도 바뀌지 않았다.**
    assert duel.state.state_hash() == before
    assert _zone_ids(duel, Zone.MZONE) == [TOKEN]
    assert duel.state.find_instance(mine[0]) is not None


# ======================================================================
# D. 넓어지지 않았다 — 실제 금지 · 실제 제한 · 모르는 카드
# ======================================================================
@pytest.mark.real_card
def test_d01_a_real_prohibition_still_refuses(repository):
    """
    🔴 **실제 특수 소환 금지는 그대로 막는다.** 상대 필드의 파키세팔로는
    손으로 읽은 표에 ``prohibits=True`` 로 있다.

    그리고 그 거절은 **모름이 아니라 확정 거부**다.
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository,
        mine=(GIRSU, TOKEN),
        theirs=(PACHYCEPHALO,),
        grave=(DIBER,),
        deck=(SKELETON,),
    )
    assert _diber_offer(duel, grave[0]) is None
    gate = _diber_gate(duel, grave[0])
    assert gate.validity is ActionValidity.INVALID, gate.reason
    told = _deck_candidate_verdict(duel)
    assert told.answer is ConditionResult.FALSE, told.reason
    assert str(PACHYCEPHALO) in told.reason


@pytest.mark.real_card
def test_d02_an_unregistered_card_is_still_unknown(repository):
    """
    🔴 **모르는 카드는 자동 허가되지 않는다.** 등록소에 없는 「오르페골」
    몬스터가 필드에 있으면 그대로 ``UNKNOWN`` 이다 (ADR-006).

    🔴 **토큰과 함께 있어도 그렇다** — 토큰을 읽게 된 것이 다른 카드의
    모름을 덮지 않는다.
    """
    assert UNREGISTERED not in OPERATION_RULINGS.card_ids

    for label, mine in (
        ("미등록만", (GIRSU, UNREGISTERED)),
        ("토큰과 함께", (GIRSU, TOKEN, UNREGISTERED)),
    ):
        duel, _m, _t, _e, grave, _x = _board(
            repository, mine=mine, grave=(DIBER,), deck=(SKELETON,)
        )
        told = _deck_candidate_verdict(duel)
        assert told.answer is ConditionResult.UNKNOWN, (label, told.reason)
        assert str(UNREGISTERED) in told.reason, label
        assert _diber_offer(duel, grave[0]) is None, label
        gate = _diber_gate(duel, grave[0])
        assert gate.validity is ActionValidity.UNKNOWN, (label, gate.reason)


@pytest.mark.real_card
def test_d03_the_dark_limit_still_applies_with_a_token_on_the_field(
    repository,
):
    """
    🔴 **디베르의 어둠 속성 제한은 그대로 걸리고 그대로 막는다** — 토큰을
    읽게 된 것이 그 제한을 풀지 않는다.
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository,
        mine=(GIRSU, TOKEN),
        grave=(DIBER,),
        deck=(SKELETON,),
        hand=(FEATHERMAN, GIRSU),
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)

    state = duel.state
    assert SKELETON in _zone_ids(duel, Zone.MZONE)
    limits = state.summon_limits.active(state.turn.turn_number, P0)
    assert len(limits) == 1
    assert limits[0].attribute == "DARK"

    ruling = BoardRuling(duel.view(P0), OPERATION_RULINGS)
    hand = {c.card_id: c.instance_id for c in state.zone(P0, Zone.HAND)}
    wind = ruling.explain_special_summon(hand[FEATHERMAN])
    assert wind.answer is ConditionResult.FALSE
    assert "DARK" in wind.reason
    dark = ruling.explain_special_summon(hand[GIRSU])
    assert dark.answer is ConditionResult.TRUE, dark.reason


@pytest.mark.real_card
def test_d04_the_no_candidate_restriction_rule_still_holds(repository):
    """
    🔴 **직전 보완이 유지된다** (6-AO 후속). 토큰이 필드에 있고 해결 전에
    유일한 덱 후보가 사라지면, 소환은 없고 **제한은 걸린다.**

    🔴 발동과 해결 사이의 카드 이동은 **시험이 손으로 만든 조작**이다.
    """
    duel, _m, _t, _e, grave, _x = _board(
        repository, mine=(GIRSU, TOKEN), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    state = duel.state
    only = [c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON][0]
    state.move(only, Zone.GRAVE, to_player=P0)   # 🔴 시험용 상태 조작
    settle_chain(duel)

    assert SKELETON not in _zone_ids(duel, Zone.MZONE)
    assert len(state.summon_limits.active(state.turn.turn_number, P0)) == 1
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]


# ======================================================================
# E. 시작 패부터 — 실제 전개와 연결
# ======================================================================
@pytest.mark.real_card
def test_e01_the_written_line_runs_from_the_starting_hand(repository):
    """
    🔴 **준비된 판이 아니다.** 발표한 레시피와 시작 패에서 다섯 걸음이 전부
    실제 엔진 행동으로 수행된다.

        1  기르수 일반 소환
        2  기르수 ① — 덱의 디베르를 묘지로
        3  기르수 ③ — 서로의 필드에 성유물 토큰 1장씩
        4  🔴 **토큰이 남은 채** 디베르 ① — 덱에서 스켈레촌 특수 소환
        5  자신의 토큰을 소재로 갈라테아i 링크 소환

    🔴 **4 단계가 이 Phase 전까지 막혀 있었다** — 3 단계가 만든 토큰이
    디베르의 후보 판정을 ``UNKNOWN`` 으로 만들었다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import (
        ORCUST_TOKEN_DIBER_LINE,
        line_progress,
    )
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    line = ORCUST_TOKEN_DIBER_LINE
    draft = parse_recipe(line.recipe_ydk, repository).draft
    assert draft is not None
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(
        repository, draft, list(line.hand), chooser=chooser, triggers=triggers
    )
    assert setup.can_run, setup.blockers
    run = execute_opening(setup, repository, choose=line.policy())

    progress = line_progress(run, line)
    assert progress.completed, progress.describe_ko()
    assert progress.done == 5
    kinds = [step.kind for step in run.steps if step.accepted]
    assert kinds[:5] == [
        "normal_summon",
        "activate_effect",
        "activate_effect",
        "activate_effect",
        "link_summon",
    ], kinds

    state = setup.duel.state
    #: 최종 판 — 토큰은 **한 장도 남지 않는다** (내 쪽). 상대 토큰은 남는다.
    assert sorted(c.card_id for c in state.zone(P0, Zone.MZONE)) == sorted(
        [GIRSU, SKELETON]
    )
    assert [c.card_id for c in state.zone(P0, Zone.EMZONE)] == [GALATEA_I]
    assert [c.card_id for c in state.zone(P0, Zone.REMOVED)] == [DIBER]
    assert [c.card_id for c in state.zone(P0, Zone.GRAVE)] == []
    assert [c.card_id for c in state.zone(P1, Zone.MZONE)] == [TOKEN]
    #: 제한도 그대로 걸려 있다.
    limits = state.summon_limits.active(state.turn.turn_number, P0)
    assert len(limits) == 1 and limits[0].attribute == "DARK"


@pytest.mark.real_card
def test_e02_the_line_is_registered_separately_from_the_search(repository):
    """
    🔴 **검증용 고정 경로와 일반 탐색을 가른다.** 이 경로는 사람이 적어 둔
    다섯 걸음이고, 탐색기는 이 이름을 모른다.
    """
    import inspect

    from deck.combo_policy import COMBO_LINES, ORCUST_TOKEN_DIBER_LINE
    import agent.bounded_search as bs

    assert COMBO_LINES["orcust-token-diber"] is ORCUST_TOKEN_DIBER_LINE
    assert "검증용" in ORCUST_TOKEN_DIBER_LINE.note
    assert ORCUST_TOKEN_DIBER_LINE.reproduction_ready is True
    #: 🔴 **탐색기에 카드별 정답 수순이 없다.**
    source = inspect.getsource(bs)
    for needle in ("orcust-token-diber", str(DIBER), str(TOKEN), "COMBO_LINES"):
        assert needle not in source, needle
