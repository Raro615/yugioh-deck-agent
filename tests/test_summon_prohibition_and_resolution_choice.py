"""
Phase 6-AD — **6-AC 의 전개 경로에서 확인된 규칙 오류 둘.**

6-AC 는 네 단계를 실제로 실행했고 그 사실은 그대로다
(``tests/test_orcust_girsu_line.py`` 가 계속 센다). 그런데 통과한 시험들이
아래 두 가지를 재지 못했다.

======  ====================================================================
문제 ①  **특수 소환 금지가 걸린 판에서 링크 소환이 수락되었다.** 소재 조건과
        놓을 자리만 보았고, 링크 소환이 규칙상 특수 소환이라는 사실을 쓰지
        않았다.
문제 ②  **『성장』 ② 의 패 선택을 발동 시점에 고정했다.** 공식 스크립트는
        ``s.sptg1`` 에서 **후보의 존재만** 확인하고 ``s.spop1`` 의
        ``Duel.SelectMatchingCard`` 로 **해결 중에** 고른다.
======  ====================================================================

실제와 합성
-----------
====================================================  ==================
``42009836`` 파슬 다이너 파키세팔로                      🔴 실제 카드
``69811710`` · ``93920420`` · ``30741503``             🔴 실제 카드
``21441617`` 오르페골 스켈레촌 (금지 신호 · 표에 없음)     🔴 실제 카드
초기 판 구성 (필드 · 패 · 엑스트라 덱에 카드 놓기)        **테스트의 구성**
====================================================  ==================

🔴 **초기 판 구성 뒤의 변화는 전부 엔진이 만든다.** 체인 도중의 상태 변화도
``Duel.apply`` 로 만든다 — 그 자리를 ``state.move`` 로 흉내 내면 "해결 시점에
다시 본다" 를 재는 것이 아니라 테스트가 답을 적어 주는 것이 된다.
"""

from __future__ import annotations

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel, duel_components
from engine.game_state_view import GameStateView
from engine.link_rules import LinkMaterialEligibility, assess_link_materials
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.summon_restriction import (
    SPECIAL_SUMMON_PROHIBITIONS,
    SUMMON_PROHIBITION_RULE_MISSING,
    ProhibitionScope,
    SpecialSummonPermission,
    assess_special_summon_permission,
    prohibition_for,
)
from engine.validation import CODE_VALIDITY, ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

GIRSU = 69811710
WAND = 93920420
GALATEA = 30741503
PACHY = 42009836
SKELETON = 21441617
FEATHERMAN = 21844576
P0, P1 = 0, 1

pytestmark = requires_official_db


# ======================================================================
# 공용 — **시작 상태**만 만든다
# ======================================================================
def _board(
    repository,
    mine,
    *,
    theirs=(),
    extra=(GALATEA,),
    mine_position=Position.FACEUP_ATTACK,
    theirs_position=Position.FACEUP_ATTACK,
    hand=(),
):
    """
    양쪽 필드 · 자신의 패 · 자신의 엑스트라 덱을 시작 상태로 놓는다.

    🔴 ``tests/test_orcust_girsu_line.py`` 의 ``_link_board`` 는 자신 필드만
    놓는다. 이 파일은 **상대 필드와 뒷면**도 필요하므로 (금지의 범위가
    ``SetTargetRange`` 로 적히고, 뒷면은 지속 효과를 적용하지 않는다) 여기서
    따로 만든다 — 저쪽 함수를 넓히면 6-AC 의 시험들이 쓰는 모양이 바뀐다.
    """
    state = GameState.create(
        repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )
    mine_ids = []
    for index, card_id in enumerate(mine):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance, Zone.MZONE, to_player=P0, index=index, position=mine_position
        )
        mine_ids.append(instance.instance_id)
    theirs_ids = []
    for index, card_id in enumerate(theirs):
        instance = state.create_instance(card_id, owner=P1, zone=Zone.MZONE)
        state.move(
            instance, Zone.MZONE, to_player=P1, index=index, position=theirs_position
        )
        theirs_ids.append(instance.instance_id)
    hand_ids = []
    for card_id in hand:
        instance = state.create_instance(card_id, owner=P0, zone=Zone.HAND)
        state.move(instance, Zone.HAND, to_player=P0)
        hand_ids.append(instance.instance_id)
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    state.turn.turn_number = 3
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    return duel, mine_ids, theirs_ids, extra_ids, hand_ids


def _link_attempt(duel, extra_ids, mine_ids):
    """
    같은 링크 소환을 **후보 생성과 직접 실행 양쪽으로** 물어본다.

    돌려주는 것: (후보 수, 보류 목록, 적용 결과, 상태가 그대로인가).
    """
    legal = duel.legal_actions(P0)
    candidates = [
        action
        for action in legal.allowed
        if action.kind is PlayerActionKind.LINK_SUMMON
    ]
    withheld = [
        reason
        for reason in legal.withheld
        if reason.kind is PlayerActionKind.LINK_SUMMON
    ]
    action = PlayerAction.link_summon(
        actor=P0, source=extra_ids[0], materials=(mine_ids[0], mine_ids[1])
    )
    before = duel.state.state_hash()
    applied = duel.apply(action)
    return candidates, withheld, applied, duel.state.state_hash() == before


# ======================================================================
# H. 문제 ① — 특수 소환 금지가 링크 소환을 막는다
# ======================================================================
@pytest.mark.real_card
def test_h01_the_reported_board_now_refuses_the_link_summon(repository):
    """
    🔴 **검토자가 실측한 재현 그대로.** 자신 필드에 기르수 · 『성장』 ·
    파키세팔로, 자신 엑스트라 덱에 갈라테아.

    6-AC 에서는 후보가 **올라오고** ``accepted=True`` · ``code=OK`` 였다.
    파키세팔로는 소재로 사라지지도 않았고 필드에 그대로 남았다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND, PACHY]
    )
    candidates, withheld, applied, unchanged = _link_attempt(duel, extra, mine)

    #: ① 후보가 하나도 올라오지 않는다.
    assert candidates == []
    #: ② 직접 적용도 거절된다 — **후보 제외와 같은 답**이다.
    assert applied.accepted is False
    assert applied.code is ValidationCode.SPECIAL_SUMMON_FORBIDDEN
    #: ③ 거절의 이유가 **금지**를 가리킨다. 소재 탓이 아니다.
    assert "특수 소환이 금지" in applied.reason
    assert str(PACHY) in applied.reason
    #: ④ 판이 한 글자도 바뀌지 않았다 — 소재 이동 · 소환 · 사건 · 사용 기록.
    assert unchanged is True
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.EMZONE) if c] == []
    assert sorted(
        c.card_id for c in duel.state.player(P0).zone(Zone.MZONE) if c
    ) == sorted([GIRSU, WAND, PACHY])
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.GRAVE) if c] == []
    assert len(duel.state.uses) == 0
    assert duel.journal is not None and len(duel.journal) == 0
    #: ⑤ 보류에도 **같은 코드**로 적힌다 (보고가 "소재가 틀렸다" 고 하지 않는다).
    assert {reason.code for reason in withheld} == {
        ValidationCode.SPECIAL_SUMMON_FORBIDDEN
    }


@pytest.mark.real_card
def test_h02_without_the_prohibition_the_link_summon_still_runs(repository):
    """
    🔴 **대조군.** 같은 판에서 파키세팔로만 빼면 링크 소환이 그대로 된다.

    이것이 없으면 위 시험은 "링크 소환을 전부 막았다" 로도 통과한다.
    """
    duel, mine, _theirs, extra, _hand = _board(repository, [GIRSU, WAND])
    candidates, _withheld, applied, unchanged = _link_attempt(duel, extra, mine)

    assert len(candidates) == 1
    assert applied.accepted is True
    assert applied.code is ValidationCode.OK
    assert unchanged is False
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.EMZONE) if c] == [
        GALATEA
    ]


@pytest.mark.real_card
def test_h03_the_opponents_pachycephalo_blocks_it_too(repository):
    """
    🔴 **범위가 「서로」 다.** ``SetTargetRange(1,1)`` 를 옮긴 값이고, 공식
    텍스트가 *"Neither player can Special Summon monsters."* 다.

    상대 필드의 카드를 보지 않으면 이 금지가 자기 필드에만 걸린다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND], theirs=(PACHY,)
    )
    candidates, _withheld, applied, unchanged = _link_attempt(duel, extra, mine)

    assert candidates == []
    assert applied.accepted is False
    assert applied.code is ValidationCode.SPECIAL_SUMMON_FORBIDDEN
    assert unchanged is True
    #: 표가 「서로」 라고 적었고, 그 값이 판정에 쓰인다.
    assert prohibition_for(PACHY).scope is ProhibitionScope.BOTH


@pytest.mark.real_card
def test_h04_a_face_down_pachycephalo_does_not_block(repository):
    """
    🔴 **뒷면 카드는 지속 효과를 적용하지 않는다** (룰북). 그래서 뒷면
    파키세팔로는 막지 않는다.

    이 구분이 없으면 판정이 "그 카드가 어딘가 있다" 로 막게 되고, 그것은
    규칙이 아니다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository,
        [GIRSU, WAND],
        theirs=(PACHY,),
        theirs_position=Position.FACEDOWN_DEFENSE,
    )
    candidates, _withheld, applied, _unchanged = _link_attempt(duel, extra, mine)

    assert len(candidates) == 1
    assert applied.accepted is True
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.EMZONE) if c] == [
        GALATEA
    ]


@pytest.mark.real_card
def test_h05_a_signal_without_a_read_scope_is_unknown_not_allowed(repository):
    """
    🔴 **확인된 금지와 판정할 수 없는 금지를 가른다** (ADR-006).

    오르페골 스켈레촌(21441617)의 스크립트에 ``EFFECT_CANNOT_SPECIAL_SUMMON``
    이 있다 — 「그 턴 어둠 속성 이외를 특수 소환할 수 없다」 쪽이다. 그것이
    **지금 누구에게 걸리는지**는 이 저장소가 읽지 않았으므로 모름이다.

    모름은 허가가 아니다. 그리고 **확정 거부도 아니다** — 코드가 갈린다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND, SKELETON]
    )
    candidates, withheld, applied, unchanged = _link_attempt(duel, extra, mine)

    assert candidates == []
    assert applied.accepted is False
    #: 🔴 ``SPECIAL_SUMMON_FORBIDDEN`` 이 **아니다** — 모름 쪽 코드다.
    assert applied.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: ``DuelStep`` 은 **코드만** 들고 판정을 파생한다 (보완8 ·
    #: ``test_duelstep_withheld_validation_audit``). 그래서 여기서도
    #: ``CODE_VALIDITY`` 로 묻는다 — 걸음에 두 벌로 적지 않는다.
    assert CODE_VALIDITY[applied.code] is ActionValidity.UNKNOWN
    #: 🔴 걸음은 **빠진 규칙 이름을 들고 다니지 않는다** (보완8 이 그
    #: 사실을 고정한다 — 걸음은 코드만 든다). 그 이름은 보류 쪽에 있다.
    assert {reason.missing for reason in withheld} == {
        SUMMON_PROHIBITION_RULE_MISSING
    }
    assert unchanged is True
    assert {reason.code for reason in withheld} == {
        ValidationCode.RULE_NOT_IMPLEMENTED
    }


@pytest.mark.real_card
def test_h06_an_unreadable_face_up_card_is_also_unknown(repository):
    """
    🔴 **정체를 알 수 없는 앞면 카드도 모름이다.** "미확인은 안전" 을 쓰지
    않는다.

    상대 필드에 **스크립트가 없는** 카드를 놓는다 (엘리멘틀 히어로
    페더맨 — ``special_summon_restriction_signals`` 가 ``None`` 이다).
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND], theirs=(FEATHERMAN,)
    )
    view = GameStateView.from_state(duel.state, viewer=P0)
    found = view.find(
        next(
            card.instance_id
            for card in duel.state.player(P1).zone(Zone.MZONE)
            if card is not None
        )
    )
    assert found is not None
    assert found.definition.special_summon_restriction_signals is None

    candidates, _withheld, applied, unchanged = _link_attempt(duel, extra, mine)
    assert candidates == []
    assert applied.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert unchanged is True


@pytest.mark.real_card
def test_h07_a_confirmed_prohibition_beats_an_unread_material_rule(repository):
    """
    🔴 **규칙이 답한 것이 모름보다 먼저다** (보완8 이 세운 구분).

    소재 조건을 **읽지 않은** 링크 몬스터(갈라테아i)를 금지된 판에서
    물어보면, 보고는 "소재 조건을 아직 읽지 않았다"(모름)가 아니라
    **"특수 소환이 금지되어 있다"**(확정 거부)를 적어야 한다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND, PACHY], extra=(48835607,)
    )
    action = PlayerAction.link_summon(
        actor=P0, source=extra[0], materials=(mine[0], mine[1])
    )
    applied = duel.apply(action)
    assert applied.code is ValidationCode.SPECIAL_SUMMON_FORBIDDEN


@pytest.mark.real_card
def test_h08_an_unread_prohibition_does_not_hide_an_illegal_material(repository):
    """
    🔴 **반대 방향.** 모름이 확정 위반을 가리지 않는다.

    금지를 판정할 수 없는 판(스켈레촌)에서 **통상 몬스터**를 소재로 고르면,
    보고는 모름이 아니라 소재 위반을 적어야 한다 — 소재가 확실히 틀린
    행동은 판을 못 읽는 것과 무관하게 틀렸다.
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [FEATHERMAN, SKELETON, GIRSU]
    )
    action = PlayerAction.link_summon(
        actor=P0, source=extra[0], materials=(mine[0], mine[2])
    )
    applied = duel.apply(action)
    assert applied.code is ValidationCode.LINK_MATERIAL_INVALID
    assert CODE_VALIDITY[applied.code] is ActionValidity.INVALID


@pytest.mark.real_card
def test_h09_the_judgment_itself_cannot_return_legal_on_a_forbidden_board(
    repository,
):
    """
    🔴 **판정 함수를 직접 불러도 허가가 나지 않는다.**

    검증기의 요구 하나만 고치면 그 요구를 거치지 않는 호출자가 생길 수
    있다 — 그래서 :func:`~engine.link_rules.assess_link_materials` 자신도
    **같은 함수**로 금지를 본다 (관문이 둘이다).
    """
    duel, mine, _theirs, extra, _hand = _board(
        repository, [GIRSU, WAND, PACHY]
    )
    view = GameStateView.from_state(duel.state, viewer=P0)
    assessment = assess_link_materials(view, P0, extra[0], (mine[0], mine[1]))
    assert assessment.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "특수 소환" in assessment.reason


def test_h10_the_prohibition_table_carries_its_evidence():
    """
    🔴 **근거 없이 적힌 금지는 검증된 규칙이 아니다.**

    표의 두 줄이 양방향이라는 것도 함께 센다 — 신호를 적었지만 이 엔진에서
    걸릴 수 없는 카드가 있고 (『성장』 의 ③), 그 사실을 적지 않으면 그 카드가
    필드에 있는 모든 판이 모름이 된다.
    """
    assert {rule.card_id for rule in SPECIAL_SUMMON_PROHIBITIONS} == {PACHY, WAND}
    for rule in SPECIAL_SUMMON_PROHIBITIONS:
        assert rule.lua_file.startswith("c") and rule.lua_file.endswith(".lua")
        assert rule.lua_excerpt.strip()
        assert rule.note.strip()
        assert rule.text_ko.strip()
    assert prohibition_for(PACHY).prohibits is True
    assert prohibition_for(WAND).prohibits is False
    #: 막지 않는다고 적은 줄에는 범위가 없다 — 둘을 함께 적으면 모순이다.
    assert prohibition_for(WAND).scope is None


@pytest.mark.real_card
def test_h11_the_registered_path_board_is_judged_allowed(repository):
    """
    🔴 **정상 경로의 판은 ``ALLOWED`` 다** — 모름이 아니다.

    기르수와 『성장』 둘 다 필드에 있는 상태가 경로의 4 단계 직전이고, 그
    판에서 판정이 모름이면 경로가 막힌다. 『성장』 은 금지 신호를 **적고
    있으므로** (③ 의 해결이 만드는 효과), 표의 "막지 않는다" 줄이 없으면
    여기서 모름이 된다.
    """
    duel, _mine, _theirs, _extra, _hand = _board(repository, [GIRSU, WAND])
    view = GameStateView.from_state(duel.state, viewer=P0)
    found = assess_special_summon_permission(view, P0)
    assert found.permission is SpecialSummonPermission.ALLOWED
    assert found.missing_rule is None
