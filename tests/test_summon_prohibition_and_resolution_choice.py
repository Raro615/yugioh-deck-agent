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


# ======================================================================
# J. 문제 ② — 『성장』 ② 의 선택은 **해결 중에** 일어난다
#
# 🔴 **무엇을 재지 못했는지 먼저 적는다** (6-AD §5 의 B · C · D · E).
#
# §5 는 "발동과 해결 사이에 패가 바뀌면 그때의 패에서 고른다" 와 "해결
# 시점에 금지가 걸리면 허가되지 않는다" 를 **체인 도중의 실제 상태 변화**로
# 재라고 요구한다. 이 저장소에는 그 변화를 만들 수 있는 등재 효과가 없다 —
# 체인에 응답으로 올릴 수 있는 것은 등재된 유발 둘뿐이고 (기르수 ① ·
# 『성장』 ②), 둘 다 패를 줄이거나 지속 효과를 세우지 않는다. 등재된 마법
# 열여섯은 ``activate_card`` 의 적법성을 판정할 계층이 없어 후보가 되지
# 않는다 (실측: 보류 사유 ``activation-timing (Phase 2-C/2-F)``).
#
# 그래서 **체인 도중에 상태를 바꾸는 사례는 재지 못했다.** 대신 같은 성질을
# 갈라서 잰다:
#
# 1. 발동 시점에 **아무 카드도 묶이지 않는다** (J01) — 묶인 것이 없으면
#    "그때의 패에 고정" 이 구조적으로 불가능하다.
# 2. 선택은 **해결 시점의 후보 목록**에서 나오고 (J02 · J03), 패가 다르면
#    고른 카드도 다르다 (J04).
# 3. 후보가 없으면 **발동 자체가 거절된다** (J05) — 공식 스크립트의
#    ``s.sptg1`` 과 같은 자리다.
# 4. 금지된 판은 **양쪽 끝에서** 막힌다 (J06) — 발동 조건이 거짓이고, 해결
#    시점 후보 판정도 거짓이다. 두 답은 **같은 함수**에서 나오므로 갈릴 수
#    없다.
#
# 🔴 이 네 가지가 "체인 도중에 패가 바뀌어도 맞다" 를 **증명하지 않는다.**
# 증명하려면 그 변화를 만드는 효과가 등재되어야 한다 — 그것은 이번 범위가
# 아니다 (§보고의 남은 한계에 적는다).
# ======================================================================
WORLD_ARTIFACT_SWORD = 40441990
"""「성유물－『성건』」 — 패의 **두 번째** 「성유물」 몬스터. 🔴 실제 카드."""

CLIMAX = 703897
KEY = 2930675
AWAKENING = 12989604
CORE = 55051920


def _wand_line(resolution_card_ids=(WAND,)):
    """
    『성장』 ② 까지만 가는 **세 단계 경로** (링크 소환을 넣지 않는다).

    🔴 **셋째 단계는 "해결 중에 『성장』 을 고른다" 까지가 단계다** (6-AD §6).
    발동이 수락됐다는 사실만으로 세면, 해결이 특수 소환을 만들지 못한 판도
    "3/3 완료" 로 적힌다 — 실측으로 그 일이 일어났고 (``test_j04``) 그래서
    기본값에 그 선언을 넣는다.

    왜 네 단계 경로를 쓰지 않는가 — 링크 소환이 특수 소환된 『성장』 을
    소재로 **묘지로 보내므로**, 그 뒤에는 "무엇이 특수 소환되었는가" 를
    필드에서 읽을 수 없다. 이 묶음이 보려는 것은 그 한 장이다.
    """
    from deck.combo_policy import ComboLine, PlannedAction

    return ComboLine(
        name="orcust-girsu-wand-only",
        title_ko="기르수 → 『성장』 묘지행 → 패에서 「성유물」 몬스터 특수 소환",
        steps=(
            PlannedAction(kind="normal_summon", card_id=GIRSU),
            PlannedAction(
                kind="activate_effect", card_id=GIRSU, effect_ref=(GIRSU, 0)
            ),
            PlannedAction(
                kind="activate_effect",
                card_id=WAND,
                effect_ref=(WAND, 1),
                resolution_card_ids=tuple(resolution_card_ids),
            ),
        ),
        basis=(
            "ORCUST_GIRSU_LINE 의 앞 세 단계와 **같은 근거**이고 (그쪽 basis), "
            "링크 소환 한 단계만 뺐다 — 특수 소환된 카드를 필드에서 읽기 "
            "위한 시험용 경로다."
        ),
    )


def _run_wand(repository, hand, *, preferred=(), line=None):
    """
    발표한 레시피와 **지정한 패**로 세 단계를 돌린다.

    ``/combo`` 와 같은 배선을 쓴다 — ``app.main.opening_wiring`` 하나가
    유발과 해결 시점 선택을 꽂는다. ``preferred`` 를 주면 그 목록으로
    :class:`~agent.choice.PreferredCardChoice` 가 만들어진다 (경로가
    ``resolution_card_ids`` 로 적는 것과 같은 자리).

    🔴 **패는 시작 상태다.** 돌리는 중에 패를 건드리지 않는다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_VERIFICATION_RECIPE
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    assert draft is not None
    plan = line if line is not None else _wand_line()

    class _Wanted:
        """``opening_wiring`` 이 읽는 칸 하나만 가진 값."""

        resolution_preferences = tuple(preferred)

    chooser, triggers = opening_wiring(
        repository, _Wanted() if preferred else None
    )
    setup = build_opening(
        repository, draft, list(hand), chooser=chooser, triggers=triggers
    )
    assert setup.can_run, setup.blockers
    run = execute_opening(setup, repository, choose=plan.policy())
    return setup, run, chooser, plan


def _wand_step(run):
    """실행 기록에서 『성장』 ② 의 걸음. 없으면 ``None``."""
    return next(
        (
            step
            for step in run.steps
            if step.accepted and step.effect_ref == f"{WAND}:e[1]"
        ),
        None,
    )


def _wand_record(chooser):
    """해결 시점 선택 기록에서 『성장』 ② 의 것. 없으면 ``None``."""
    return next(
        (
            record
            for record in chooser.records
            if (record.effect_ref.card_id, record.effect_ref.ordinal)
            == (WAND, 1)
        ),
        None,
    )


@pytest.mark.real_card
def test_j01_the_activation_pins_no_card_from_the_hand(repository):
    """
    §5-A — **발동 시점에 패의 어느 한 장도 묶이지 않는다.**

    🔴 **이것이 ② 의 핵심이다.** 묶인 것이 없으면 "발동할 때의 패에 고정"
    이 **구조적으로** 불가능하다 — 뒤에서 아무리 패가 바뀌어도 되돌릴 것이
    없다.

    네 가지를 함께 본다 (전부 정의와 다리 계층의 사실이고 판을 읽지 않는다).
    """
    from engine.effect.library import definition_registry
    from engine.ids import EffectRef
    from engine.target_bridge import (
        chosen_bindings,
        decided_at_resolution,
        required_target_count,
        target_combinations,
    )

    definition = definition_registry().definition_for(EffectRef(WAND, 1))
    assert definition is not None
    binding = definition.targets[0]

    #: ① 정의가 **선언한다** — 짐작이 아니다.
    assert binding.spec.chosen_at_resolution is True
    #: ② 다리 계층이 그 선언을 읽는다.
    assert decided_at_resolution(binding.spec) is True
    #: ③ 그래서 발동 시점에 **고를 자리가 없다.**
    assert chosen_bindings(definition) == ()
    assert required_target_count(definition) == 0
    #: ④ 후보 행위에 실리는 조합은 **빈 것 하나**다 — 패의 장수와 무관하다.
    #:
    #: 🔴 패에 『성장』 을 **두 장** 두고 센다. 발동 시점에 고르는 효과라면
    #: 조합이 둘이 되고, 그러면 후보 행위마다 한 장이 묶인다.
    duel, _mine, _theirs, _extra, hand = _board(
        repository, [GIRSU], hand=(WAND, WAND)
    )
    assert len(hand) == 2
    combinations = target_combinations(
        duel.state, P0, definition, hand[0]
    )
    assert combinations == [()]


@pytest.mark.real_card
def test_j02_the_choice_happens_while_resolving_and_matches_the_summon(
    repository,
):
    """
    §5-F — **고른 기록과 실제로 특수 소환된 카드가 같다.**

    그리고 그 선택이 **해결 중에** 일어났다는 증거를 함께 본다 — 발동 기록의
    ``targets`` 는 비어 있고, 고른 것은 해결 시점 선택 기록에만 있다.
    """
    setup, run, chooser, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, WAND], preferred=(WAND,)
    )
    from deck.combo_policy import line_progress

    assert line_progress(run, plan).completed, run.stopped_reason
    step = _wand_step(run)
    assert step is not None

    #: ① 발동 기록에는 대상이 없다 — **정상**이다.
    assert step.targets == ()
    #: ② 해결 중에 한 장을 골랐다.
    record = _wand_record(chooser)
    assert record is not None
    assert len(record.chosen) == 1
    #: ③ 고른 것은 **엔진이 허용한 후보 중 하나**다.
    assert record.chosen[0] in {c.instance for c in record.offer.permitted}
    #: ④ 그 개체가 지금 자신 몬스터 존에 있다 — 기록과 판이 일치한다.
    state = setup.duel.state
    on_field = [card for card in state.zone(P0, Zone.MZONE)]
    assert record.chosen[0] in {card.instance_id for card in on_field}
    summoned = next(
        card for card in on_field if card.instance_id == record.chosen[0]
    )
    assert summoned.card_id == WAND
    #: ⑤ 걸음 기록도 **같은 카드**를 적는다.
    assert step.resolution_choices == (WAND,)


@pytest.mark.real_card
def test_j03_two_candidates_in_hand_and_exactly_one_is_summoned(repository):
    """
    §5-C 의 앞쪽 — **후보가 둘이면 그중 하나만** 특수 소환된다.

    같은 이름 두 장을 패에 두면, 해결 시점 후보가 둘이고 그중 **고른
    개체만** 필드에 온다. 나머지는 패에 남는다 — 효과가 「1장」 이라고
    적혀 있다 (``minimum=maximum=1``).
    """
    setup, run, chooser, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, WAND, WAND], preferred=(WAND,)
    )
    from deck.combo_policy import line_progress

    assert line_progress(run, plan).completed, run.stopped_reason
    record = _wand_record(chooser)
    assert record is not None
    #: ① 허용 후보가 둘이었다.
    assert len(record.offer.permitted) == 2
    assert record.offer.minimum == 1 and record.offer.maximum == 1
    #: ② 한 장만 골랐고 한 장만 필드에 왔다.
    assert len(record.chosen) == 1
    state = setup.duel.state
    assert [c.card_id for c in state.zone(P0, Zone.MZONE)].count(WAND) == 1
    #: ③ 다른 한 장은 **패에 그대로** 있다.
    assert [c.card_id for c in state.zone(P0, Zone.HAND)].count(WAND) == 1


@pytest.mark.real_card
def test_j04_an_unconfirmed_eligibility_is_not_approved_as_a_success(
    repository,
):
    """
    §2 — **아직 확인하지 못한 발동 자격을 허가하지 않는다.**

    패에 『성장』 이 **없고** 「성유물－『성건』」(40441990) 만 있는 판이다.
    『성건』 은 「성유물」 몬스터이므로 조건 필터는 통과하는데, 그 카드에는
    "지금 특수 소환할 수 있는가" 가 **등재되지 않았다** — 그래서 ``UNKNOWN``
    이다.

    🔴 **이것을 "『성건』 은 규칙상 소환 불가능하다" 로 읽지 마라.** 실제
    규칙에서는 소환할 수 있다. 문제는 **엔진이 그것을 확인하지 못했다**는
    것이고, 확인하지 못한 자격을 발동 허가로 바꾸면 안 된다 (ADR-006).

    🔴 **6-AD 는 이 자리를 수락했다.** ``s.sptg1`` 의
    ``IsExistingMatchingCard`` 를 조건 필터만으로 세었기 때문이다 — 그
    필터(``s.spfilter1``)에는 ``IsCanBeSpecialSummoned`` 가 **함께** 들어
    있다. 그래서 발동이 수락되고 해결 시점에 멈췄다.
    """
    setup, run, chooser, plan = _run_wand(
        repository,
        [GIRSU, CLIMAX, KEY, AWAKENING, WORLD_ARTIFACT_SWORD],
        preferred=(WAND,),
    )
    from deck.combo_policy import line_progress
    from engine.effect.semantics import GATED_CANDIDATE_RULE_MISSING
    from engine.ids import EffectRef
    from engine.validation import ValidationResult

    #: ① 해결 시점 선택을 **아예 묻지 않았다** — 발동이 서지 않았으므로.
    assert _wand_record(chooser) is None
    #: ② 특수 소환도 없다. 필드에는 기르수뿐이다.
    state = setup.duel.state
    assert [c.card_id for c in state.zone(P0, Zone.MZONE)] == [GIRSU]
    assert WORLD_ARTIFACT_SWORD in [
        c.card_id for c in state.zone(P0, Zone.HAND)
    ]
    #: ③ 경로는 둘째 단계까지만 갔다.
    progress = line_progress(run, plan)
    assert progress.completed is False
    assert progress.done == 2
    assert progress.blocked_at is plan.steps[2]

    #: ④ **거절이 모름이다** — 확정 금지가 아니다. 그리고 **무엇이 없어서**
    #: 모르는지 이름이 붙는다 (보완8 의 계약).
    buried = next(
        card for card in state.zone(P0, Zone.GRAVE) if card.card_id == WAND
    )
    before = state.state_hash()
    result = setup.duel._activator.can_activate(
        state,
        setup.duel.chain,
        PlayerAction.activate_effect(
            actor=P0, source=buried.instance_id, effect_ref=EffectRef(WAND, 1)
        ),
        authorization=ValidationResult.valid("시험이 첫 관문을 대신한다"),
    )
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert CODE_VALIDITY[result.code] is ActionValidity.UNKNOWN
    assert result.missing_rule == GATED_CANDIDATE_RULE_MISSING
    assert str(WORLD_ARTIFACT_SWORD) in result.reason
    #: ⑤ 묻는 것만으로 판도 사용 기록도 체인도 바뀌지 않는다.
    assert state.state_hash() == before
    assert len(setup.duel.chain.links) == 0
    #: ⑥ 전개 기록에도 **미지원 사유**로 남는다 — 조용히 사라지지 않는다.
    assert any(
        GATED_CANDIDATE_RULE_MISSING in line for line in run.unsupported
    ), run.unsupported


@pytest.mark.real_card
def test_j04a_a_legal_candidate_is_not_covered_by_an_unknown_one(repository):
    """
    §2 — **확정 가능한 한 장이 있으면 모름이 그것을 덮지 않는다.**

    패에 『성장』(등재됨 · 확정 가능) 과 『성건』(미등재 · 모름) 을 함께
    둔다. 최소 장수는 1이므로 **확정 한 장이면 발동 자격이 충족된다** —
    옆에 모르는 후보가 있다는 이유로 모름이 되면, 실제로 할 수 있는 발동이
    막힌다.

    그리고 해결 시점 선택은 **허가된 후보 안에서만** 일어난다: 『성건』 은
    후보 목록에 남지만 ``permitted`` 가 아니다 (왜 못 고르는지가 정책에게도
    보여야 한다 — ``ChoiceCandidate`` 의 설명).
    """
    setup, run, chooser, plan = _run_wand(
        repository,
        [GIRSU, CLIMAX, KEY, WORLD_ARTIFACT_SWORD, WAND],
        preferred=(WAND,),
    )
    from deck.combo_policy import line_progress

    #: ① 발동 자격이 충족되고 경로가 끝까지 간다.
    assert line_progress(run, plan).completed, run.stopped_reason
    record = _wand_record(chooser)
    assert record is not None
    #: ② 후보 목록에는 둘이 있고, 허가된 것은 『성장』 하나다.
    offered = {c.card_id for c in record.offer.candidates}
    assert offered == {WAND, WORLD_ARTIFACT_SWORD}
    assert [c.card_id for c in record.offer.permitted] == [WAND]
    #: ③ 소환된 것은 『성장』 이고 『성건』 은 패에 남는다.
    state = setup.duel.state
    assert sorted(c.card_id for c in state.zone(P0, Zone.MZONE)) == sorted(
        [GIRSU, WAND]
    )
    assert WORLD_ARTIFACT_SWORD in [
        c.card_id for c in state.zone(P0, Zone.HAND)
    ]


@pytest.mark.real_card
def test_j04b_the_candidate_list_is_counted_from_the_hand_at_resolution(
    repository,
):
    """
    §5-B 의 재는 쪽 — **후보 목록은 그 자리의 패에서 세어진다.**

    같은 발동 · 같은 선호로 두 번 돌린다. 패에 『성장』 이 한 장이면 후보가
    하나, 두 장이면 둘이다. 발동 시점에 고정된 목록이라면 두 판의 선택이
    같은 모양이어야 한다.

    🔴 **패는 시작 상태로 바꾼다** (§5 가 허용한 자리). 체인 도중에 패를
    바꾸는 사례는 이 묶음 머리말에 적은 대로 재지 못했다.
    """
    _one_setup, one_run, one, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, WAND], preferred=(WAND,)
    )
    _two_setup, two_run, two, _plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, WAND, WAND], preferred=(WAND,)
    )
    from deck.combo_policy import line_progress

    assert line_progress(one_run, plan).completed, one_run.stopped_reason
    assert line_progress(two_run, plan).completed, two_run.stopped_reason

    first = _wand_record(one)
    second = _wand_record(two)
    assert first is not None and second is not None
    #: ① 후보 수가 **패를 따른다.**
    assert len(first.offer.permitted) == 1
    assert len(second.offer.permitted) == 2
    #: ② 두 판 모두 **그 판의 후보 안에서** 골랐다.
    assert first.chosen[0] in {c.instance for c in first.offer.permitted}
    assert second.chosen[0] in {c.instance for c in second.offer.permitted}
    #: ③ 발동 기록은 두 판 모두 비어 있다 — 고정된 것이 없다.
    assert _wand_step(one_run).targets == ()
    assert _wand_step(two_run).targets == ()


@pytest.mark.real_card
def test_j05_no_candidate_in_hand_refuses_the_activation(repository):
    """
    §5-D · §3 — **후보가 없으면 발동 자체가 거절된다.**

    ``s.sptg1`` 은 빈 칸과 **후보의 존재**를 함께 본다
    (``Duel.IsExistingMatchingCard``). 6-AC 는 그 둘째를 옮기지 않았고,
    그래서 패에 「성유물」 몬스터가 한 장도 없어도 발동이 수락됐다.

    🔴 **거절은 ``INVALID`` 다** — 후보를 **전부 보고** 모자란 것이므로
    모름이 아니다 (자기 패는 가려진 자리가 아니다).
    """
    from engine.ids import EffectRef
    from engine.validation import ValidationResult

    setup, run, _chooser, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, CORE]
    )
    from deck.combo_policy import line_progress

    progress = line_progress(run, plan)
    #: ① 경로가 셋째 단계에서 멈췄다.
    assert progress.done == 2
    assert progress.blocked_at is plan.steps[2]
    #: ② 특수 소환은 일어나지 않았다 — 필드에는 기르수뿐이다.
    state = setup.duel.state
    assert [c.card_id for c in state.zone(P0, Zone.MZONE)] == [GIRSU]
    #: ③ 묘지의 『성장』 에게 직접 물어도 **같은 답**이다.
    buried = next(
        card for card in state.zone(P0, Zone.GRAVE) if card.card_id == WAND
    )
    before = state.state_hash()
    result = setup.duel._activator.can_activate(
        state,
        setup.duel.chain,
        PlayerAction.activate_effect(
            actor=P0, source=buried.instance_id, effect_ref=EffectRef(WAND, 1)
        ),
        authorization=ValidationResult.valid("시험이 첫 관문을 대신한다"),
    )
    assert result.code is ValidationCode.NO_CANDIDATES
    assert CODE_VALIDITY[result.code] is ActionValidity.INVALID
    assert "후보" in result.reason
    #: ④ 묻는 것만으로 판이 바뀌지 않는다.
    assert state.state_hash() == before


@pytest.mark.real_card
def test_j06_a_forbidden_board_blocks_both_ends(repository):
    """
    §5-E — **금지된 판은 발동 쪽과 해결 쪽 양쪽에서 막힌다.**

    🔴 **체인 도중에 금지가 새로 생기는 사례는 재지 못했다** (이 묶음 머리말).
    대신 두 끝을 각각 재고, 둘이 **같은 함수**를 부른다는 사실을 함께 고정
    한다 — 그러면 두 답이 갈릴 수 없다.
    """
    from engine.condition import ConditionContext, ConditionEvaluator, ConditionResult
    from engine.effect.library import OPERATION_RULINGS, definition_registry
    from engine.effect.ruling import BoardRuling
    from engine.effect.semantics import RuleQuestion
    from engine.ids import EffectRef

    duel, _mine, _theirs, _extra, hand = _board(
        repository, [GIRSU, PACHY], hand=(WAND,)
    )
    view = GameStateView.from_state(duel.state, viewer=P0)

    #: ① **발동 쪽** — 발동 조건이 거짓이다 (모름이 아니다).
    definition = definition_registry().definition_for(EffectRef(WAND, 1))
    assert definition is not None
    verdict = ConditionEvaluator(view).evaluate(
        definition.activation, ConditionContext(player=P0)
    )
    assert verdict.result is ConditionResult.FALSE

    #: ② **해결 쪽** — 패의 그 한 장을 특수 소환할 수 있는지가 거짓이다.
    ruling = BoardRuling(view, OPERATION_RULINGS)
    told = ruling.explain_special_summon(hand[0])
    assert told.answer is ConditionResult.FALSE
    assert str(PACHY) in told.reason

    #: ③ **묻는 자리가 하나다** — 질문으로 물어도 같은 답이 나온다.
    assert (
        ruling.explain(RuleQuestion.MAY_BE_SPECIAL_SUMMONED, hand[0]).answer
        is ConditionResult.FALSE
    )
    assert (
        ruling.may(RuleQuestion.MAY_BE_SPECIAL_SUMMONED, hand[0])
        is ConditionResult.FALSE
    )

    #: ④ 파키세팔로를 빼면 둘 다 풀린다 — 대조군.
    clear, _m, _t, _e, clear_hand = _board(
        repository, [GIRSU], hand=(WAND,)
    )
    clear_view = GameStateView.from_state(clear.state, viewer=P0)
    assert (
        ConditionEvaluator(clear_view)
        .evaluate(definition.activation, ConditionContext(player=P0))
        .result
        is ConditionResult.TRUE
    )
    assert (
        BoardRuling(clear_view, OPERATION_RULINGS)
        .explain_special_summon(clear_hand[0])
        .answer
        is ConditionResult.TRUE
    )


@pytest.mark.real_card
def test_j07_the_preference_never_leaks_between_an_original_and_a_fork(
    repository,
):
    """
    §5-G · §4 — **원본과 사본 사이에 선택 상태도 기록도 새지 않는다.**

    두 자리를 함께 본다 — 기록을 들고 있는 조립 층
    (:class:`~integration.autonomy.PolicyChooser`) 과 선호를 들고 있는
    정책 (:class:`~agent.choice.PreferredCardChoice`).
    """
    from agent.choice import FirstPermittedChoice, PreferredCardChoice

    _setup, run, chooser, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, WAND], preferred=(WAND,)
    )
    from deck.combo_policy import line_progress

    assert line_progress(run, plan).completed, run.stopped_reason
    asked = len(chooser.records)
    assert asked >= 2

    #: ① 사본의 기록은 **비어** 있다 — 원본의 선택이 섞이지 않는다.
    forked = chooser.forked()
    assert forked is not None
    assert forked.records == ()
    #: ② 사본을 만든 것만으로 원본의 기록이 변하지 않는다.
    assert len(chooser.records) == asked
    #: ③ 사본의 정책은 **다른 객체**이고 선호는 같다.
    assert isinstance(chooser.selector, PreferredCardChoice)
    assert isinstance(forked.selector, PreferredCardChoice)
    assert forked.selector is not chooser.selector
    assert forked.selector.preferred == chooser.selector.preferred
    assert forked.selector.then is not None

    #: ④ 뒤에 둘 정책이 사본에서 쓸 수 없으면 **만들 때** 막는다.
    class _NoFork:
        name = "no-fork"

        def accept_offer(self, offer):  # pragma: no cover - 모양만
            return True

        def choose_cards(self, offer):  # pragma: no cover - 모양만
            return ()

    from agent.choice import ChoiceError

    with pytest.raises(ChoiceError):
        PreferredCardChoice((WAND,), _NoFork())
    #: 제대로 된 것은 만들어진다 — 위가 "전부 막는다" 로 통과하지 않게.
    assert PreferredCardChoice((WAND,), FirstPermittedChoice()) is not None


@pytest.mark.real_card
def test_j08_the_policy_chooses_only_inside_the_offer_it_was_given(repository):
    """
    §4 — **정책은 엔진이 낸 후보 안에서만 고른다.**

    🔴 **실제로 기록된 제안**에 물어본다 — 제안을 지어내면 "엔진이 낸 것
    안에서만 고른다" 를 재는 것이 아니라 테스트가 만든 모양을 재는 것이 된다.
    """
    from agent.choice import FirstPermittedChoice, PreferredCardChoice

    _setup, run, chooser, plan = _run_wand(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, WAND], preferred=(WAND,)
    )
    from deck.combo_policy import line_progress

    assert line_progress(run, plan).completed, run.stopped_reason
    record = _wand_record(chooser)
    assert record is not None
    permitted = {c.instance for c in record.offer.permitted}

    #: ① 선호가 후보에 있으면 그것을 집는다.
    wants_wand = PreferredCardChoice((WAND,), FirstPermittedChoice())
    picked = wants_wand.choose_cards(record.offer)
    assert len(picked) == record.offer.minimum
    assert set(picked) <= permitted

    #: ② 후보에 없는 카드를 선호해도 **끌어오지 않는다** — 뒤의 정책이 답한다.
    wants_absent = PreferredCardChoice((PACHY,), FirstPermittedChoice())
    fallen_back = wants_absent.choose_cards(record.offer)
    assert set(fallen_back) <= permitted
    assert fallen_back == FirstPermittedChoice().choose_cards(record.offer)
    #: ③ 선호한 카드가 그 목록에 **없었다는 사실**을 함께 적는다.
    assert PACHY not in {c.card_id for c in record.offer.candidates}

    #: ④ 묻는 것만으로 정책이 앞으로 밀리지 않는다 — 두 번 물으면 같은 답.
    assert wants_wand.choose_cards(record.offer) == picked
