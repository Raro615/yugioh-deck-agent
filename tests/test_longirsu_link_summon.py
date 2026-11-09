"""
Phase 6-AN — **오르페골 롱기르수(76145142) 의 링크 소환을 지원한다.**

무엇이 막혀 있었나
==================
:data:`~engine.link_rules.LINK_MATERIAL_RULES` 의 ``count`` 는 6-AM 까지
**정확히 그 장수**였다 (한 수). 그래서 소재 줄이 ``2+`` 인 카드, 즉 "2장
**이상**" 인 카드를 **적을 자리가 없었다** — 적으면 3장 조합이 거절되고,
3 으로 적으면 2장 조합이 거절된다. 롱기르수가 바로 그 모양이다.

6-AN 이 더한 것은 :attr:`~engine.link_rules.LinkMaterialRule.count_max`
하나이고, ``None`` 이면 이전과 **한 글자도 다르지 않다** (D 절이 센다).

소재 조건표 — 근거와 구조
=========================
근거는 **공식 스크립트 한 줄**이다 (``c76145142.lua``)::

    Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsType,TYPE_EFFECT),
                      2,nil,s.matcheck)
    function s.matcheck(g,lc,sumtype,tp)
        return g:IsExists(Card.IsSetCard,1,nil,SET_ORCUST,lc,sumtype,tp)
    end

``Link.AddProcedure(c, filter, min, max, matcheck)`` 의 자리를 그대로 읽으면
넷이 나오고, **그 넷을 섞지 않는다** (공식 룰북이 세 조건을 따로 적는 것과
같은 구분 — ``test_link_material_count_and_rating`` 머리말):

======================  =========================  =========================
읽은 것                  Lua 의 자리                 이 저장소의 자리
======================  =========================  =========================
**고른 카드의 장수**      ``min=2`` · ``max=nil``    ``count=2``
                                                   ``count_max=3``
**기여의 합**            카드 데이터의 링크 수치 3     ``link_rating=3``
**소재 각각의 조건**      ``Card.IsType(TYPE_EFFECT)``  ``each=``
                                                   ``MaterialRequirement(``
                                                   ``effect_monster=True)``
**소재 집합의 조건**      ``s.matcheck`` 의           ``includes=``
                        ``IsSetCard(SET_ORCUST)``  ``MaterialRequirement(``
                                                   ``setcodes=(0x11B,))``
======================  =========================  =========================

🔴 **``max=nil`` 을 무한으로 읽지 않았다.** 소재 한 장의 최소 기여가 1
이므로 (링크 몬스터도 1 로 **셀 수 있다**), 합이 정확히 3 이어야 하는 소환에
4장을 쓰면 합이 4 이상이 되어 닿을 수 없다. 그래서 상한은 **링크 수치 3**
이고, 그 추론은 :meth:`LinkMaterialRule.__post_init__` 이 ``count_max <=
link_rating`` 으로 고정한다 — 규칙에서 나온 수이고 카드별 예외가 아니다.

🔴 **옮기지 못한 인자를 적는다.** ``s.matcheck(g,lc,sumtype,tp)`` 의 뒤
세 인자(소환될 카드 · 소환법 · 플레이어)를 ``Card.IsSetCard`` 에 넘기는 것은
「그 소환에서만 카드군을 얻는」 효과를 보는 자리인데, 이 저장소는 그 축을
옮기지 않았다. 그래서 그런 효과가 깔린 판에서 **더 적게 허가한다** — 거짓
허가가 아니라 거짓 거절이다.

🔴 **소환을 지원한 것과 카드를 지원한 것은 다르다.** 이 Phase 가 지원한
것은 **링크 소환 절차 하나**다. 롱기르수의 ①(파괴 내성) · ②③(묘지의 기계족
2장을 덱으로) 는 **옮기지 않았다** — ``LINK_MATERIAL_RULES`` 는 소재 조건의
등록표이고 효과 등록표가 아니다 (``test_a15`` 가 그 사실을 센다).

이 파일의 네 절
===============
=====  ==========================================================
A 절   **소재 조건의 성공·실패 경계.** 위 표의 네 줄을 각각 깬다
B 절   **준비한 작은 상태에서의 소환 실행.** 🔴 **이 판이 기존 시작 패에서
       도달 가능하다는 주장이 아니다** — 손으로 구성한 시작 상태다
C 절   **탐색·재생 통합.** 준비한 상태에서 탐색기가 찾고, **다시 조립한**
       초기 상태에서 재생이 검증한다
D 절   **보존과 미지원 유지.** 갈라테아 · 갈라테아i 의 판정이 그대로이고,
       등록하지 않은 링크 몬스터가 이번 변경으로 열리지 않는다
=====  ==========================================================

실제 시작 패(``ORCUST_VERIFICATION_HAND``) 에서의 탐색 결과는 이 파일이
아니라 **보고서** ``docs/orcust-longirsu-link-summon.md`` §5 에 있다 — 그
측정은 수 분이 걸리므로 단위 시험에 넣지 않았다.
"""

from itertools import combinations

import pytest

from engine.action import MalformedAction, PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.link_rules import (
    LINK_MATERIAL_RULES,
    LINK_PLACEMENT_LINKED_RULE,
    LINK_SUMMON_KIND,
    LINK_MATERIAL_RULE_MISSING,
    LinkMaterialEligibility,
    assess_link_materials,
    material_contribution_options,
    material_rule_for,
)
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.validation import ActionValidity
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

pytestmark = requires_official_db

#: 🔴 **오르페골 롱기르수** — 이 Phase 가 등록한 카드. LINK-3 효과 몬스터.
LONGIRSU = 76145142
#: 오르페골 갈라테아 — LINK-2. 기여를 **1 또는 2** 로 고를 수 있다.
GALATEA = 30741503
#: 오르페골 갈라테아i — LINK-1.
GALATEA_I = 48835607
#: 잭나이츠 오르페골 기르수 — 레벨 4 **효과** 몬스터이고 「오르페골」 이다
#: (setcode ``0x11b`` · ``0x10c``). ``includes`` 를 채우는 자리.
GIRSU = 69811710
#: 🔴 잭나이츠 오르페골 엔릴기르수 — LINK-4 이고 **소재 조건이 등록되지
#: 않았다.** 같은 레시피의 엑스트라 덱에 있으므로, "이번 변경으로 다른 링크
#: 몬스터가 자동으로 열리지 않는다" 를 재는 자리로 쓴다.
ENLILGIRSU = 74820316
#: 성유물－『성장』 — **효과** 몬스터이지만 setcode 가 ``0xfe`` 하나이므로
#: **「오르페골」 이 아니다.** ``each`` 는 지나고 ``includes`` 만 깨는 자리.
GROWTH = 93920420
#: 성유물－『성관』 — 패에서 스스로 특수 소환할 수 있는 「성유물」 몬스터.
#: 『성장』 ② 의 후보가 되는 자리(B 절의 유발 검사)에 쓴다.
CROWN = 27918365
#: 엘리멘틀 히어로 페더맨 — **통상** 몬스터 (``MONSTER,NORMAL``). ``each``
#: 를 깨는 자리이고, 덱을 채우는 데도 쓴다.
FEATHERMAN = 21844576
#: 성유물 토큰 — ``MONSTER,NORMAL,TOKEN``. 토큰도 **통상** 몬스터이므로
#: ``each`` 를 깬다 (그리고 소재로 떠나면 묘지에 가지 않는다).
TOKEN = 46647145
#: 「오르페골」 의 공식 setcode — ``data/constants/archetype_setcode_constants
#: .lua:395`` 의 ``SET_ORCUST``.
SET_ORCUST = 0x11B

P0, P1 = 0, 1


# ======================================================================
# 공용 — **시작 상태만** 만든다
# ======================================================================
def _board(repository, *, mine=(), emzone=(), extra=(), hand=(), turn_number=3):
    """
    **시작 상태**를 만든다. 첫 행동 뒤의 모든 변화는 엔진이 만든다.

    🔴 **유발 배선을 꽂는다** (``opening_wiring``). 꽂지 않으면 사건이
    유발 후보를 열지 못하므로 (``Duel.triggers`` 가 ``None``), "소재가 묘지로
    가서 생긴 유발" 을 **없는 것으로 읽게 된다** — 실제로 측정하다가 밟은
    자리다 (``test_b04`` 의 주석).

    돌려주는 ``field`` 의 순서는 ``mine`` 다음 ``emzone`` 이고, 후보 생성이
    쓰는 순서(자리 이름 순)와 **다르다**. 그래서 소재는 :func:`_offered` 가
    후보에서 찾는다.
    """
    from app.main import opening_wiring

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
    for card_id in hand:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    state.turn.turn_number = turn_number
    state.turn.set_phase(Phase.MAIN1)
    chooser, triggers = opening_wiring(repository, None)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        triggers=triggers,
        **duel_components(chooser=chooser),
    )
    return duel, field, extra_ids


def _assess(duel, source, materials):
    """**관측만 읽는 공용 판정** 하나. 판을 바꾸지 않는다."""
    return assess_link_materials(duel.view(P0), P0, source, tuple(materials))


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


def _link_candidates(duel, source):
    """그 ``source`` 로 오른 링크 소환 후보의 **소재 집합들**."""
    duel.advance()
    return {
        frozenset(action.materials)
        for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.LINK_SUMMON and action.source == source
    }


def _withheld_links(duel):
    """보류된 링크 소환의 ``(코드, 없는 규칙)`` 들."""
    duel.advance()
    return {
        (w.code.value, w.missing)
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.LINK_SUMMON
    }


def _zone_ids(duel, zone, seat=P0):
    return [card.card_id for card in duel.state.zone(seat, zone)]


def _summons(duel, card_id, seat=P0):
    state = duel.state
    return state.summon_uses.count(
        state.turn.turn_number, seat, card_id, LINK_SUMMON_KIND
    )


def _snapshot(duel):
    """판 · 소환 기록을 함께 뜬다 — 거절이 아무것도 바꾸지 않았는지 잰다."""
    state = duel.state
    turn = state.turn.turn_number
    return (
        state.state_hash(),
        tuple(
            state.summon_uses.count(turn, P0, card_id, LINK_SUMMON_KIND)
            for card_id in (GALATEA, GALATEA_I, LONGIRSU, ENLILGIRSU)
        ),
        tuple(
            tuple(card.card_id for card in state.zone(seat, zone))
            for seat in (P0, P1)
            for zone in (Zone.MZONE, Zone.EMZONE, Zone.GRAVE, Zone.EXTRA)
        ),
    )


# ======================================================================
# A. 소재 조건의 성공·실패 경계
# ======================================================================
@pytest.mark.real_card
def test_a01_two_materials_reach_three_by_counting_galatea_as_its_rating(
    repository,
):
    """
    🔴 **최소 장수(2장) 로 소환한다** — 머리말 표의 첫 줄 **성공** 쪽.

    - 고른 카드 **2장** → ``2 <= 2 <= 3`` ✔
    - 기여는 ``1 + {1, 2}`` 이므로 합이 ``{2, 3}`` 이고 **3 에 닿는다** ✔
      (갈라테아를 **자신의 링크 수치 2 로** 센 길이다)
    - 둘 다 효과 몬스터 ✔ · 둘 다 「오르페골」 → ``includes`` ✔

    세 계층(판정 · 후보 생성 · 검증기)이 **같은 답**을 내는지 함께 본다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    materials = tuple(field)

    verdict = _assess(duel, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason

    action = _offered(duel, extra[0], materials)
    assert action is not None, _withheld_links(duel)

    validator = duel.activation_validator(P0)
    assert validator.validate(action).validity is ActionValidity.VALID


@pytest.mark.real_card
def test_a02_three_materials_reach_three_with_one_each(repository):
    """
    🔴 **최대 장수(3장) 로 소환한다** — 같은 줄의 다른 끝.

    기여가 ``1 + 1 + 1 = 3`` 이고, 「오르페골」 은 기르수 하나로 충분하다
    (``includes`` 는 **적어도 하나**다). 『성장』 두 장은 효과 몬스터이므로
    ``each`` 를 지나고 ``includes`` 는 채우지 못한다 — 그것이 정확히
    「…를 포함하는」 의 뜻이다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason
    assert _offered(duel, extra[0], field) is not None


@pytest.mark.real_card
def test_a03_the_same_link_monster_may_also_be_counted_as_one(repository):
    """
    🔴 **링크 몬스터를 1 로 세는 길도 열려 있다** (공식 조건 1 의 괄호).

    ``test_a01`` 과 **같은 갈라테아**를 쓰면서 3장을 고르면 ``1 + 1 +
    {1, 2}`` 이므로 합이 ``{3, 4}`` 이고, 3 에 닿는 길은 갈라테아를 **1 로**
    센 쪽이다. 즉 한 장이 두 값 중 하나를 고를 수 있다는 규칙이 두 조합을
    **모두** 합법으로 만든다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    #: 소재가 될 갈라테아의 기여 선택이 정말 두 값인지 먼저 본다.
    held = duel.view(P0).find(field[2])
    assert material_contribution_options(held.definition) == frozenset({1, 2})

    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason
    assert _offered(duel, extra[0], field) is not None


@pytest.mark.real_card
def test_a04_one_material_is_refused_for_the_count_even_when_the_sum_reaches(
    repository,
):
    """
    🔴 **「합이 닿는다」 가 「장수가 맞다」 를 대신하지 못한다.**

    필드의 **다른 롱기르수**(LINK-3) 한 장이면 기여를 ``{1, 3}`` 에서 고를 수
    있으므로 **합은 3 에 닿는다**. 그래도 고른 카드가 1장이므로 거절이고,
    거절의 이유는 **장수**다 — 두 조건을 한 수로 합치면 이 판이 통과한다
    (6-AF 가 실제로 그렇게 통과시켰다).
    """
    duel, field, extra = _board(
        repository, emzone=(LONGIRSU,), extra=[LONGIRSU]
    )
    held = duel.view(P0).find(field[0])
    assert material_contribution_options(held.definition) == frozenset({1, 3})

    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "1장입니다" in verdict.reason
    assert "2장 이상 3장 이하" in verdict.reason
    assert _offered(duel, extra[0], field) is None


@pytest.mark.real_card
def test_a05_four_materials_exceed_the_upper_bound(repository):
    """
    🔴 **상한도 경계다.** ``max=nil`` 을 무한으로 읽었다면 4장이 통과했을
    것이다 — 그러면 기여의 합이 최소 4 가 되어 링크 수치 3 에 **절대** 닿지
    않는 조합을 "장수는 맞다" 로 적는 셈이다 (거절 사유가 틀린다).
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH, GROWTH, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "4장입니다" in verdict.reason
    assert "2장 이상 3장 이하" in verdict.reason


@pytest.mark.real_card
def test_a06_right_count_but_the_sum_cannot_reach_three(repository):
    """
    🔴 **장수는 맞지만 기여의 합이 닿지 않는다** (머리말 표 둘째 줄).

    기르수 + 『성장』 은 둘 다 기여가 ``{1}`` 뿐이므로 합이 **2 하나**다.
    장수 조건(2장) 은 지났고 ``each`` · ``includes`` 도 지났는데 합에서
    막히므로, 읽는 쪽이 **소재를 바꿔야 한다**는 것을 알 수 있어야 한다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "기여의 합은 2" in verdict.reason
    assert "링크 수치 3" in verdict.reason


@pytest.mark.real_card
def test_a07_a_link_four_material_overshoots_and_there_is_no_value_between(
    repository,
):
    """
    🔴 **중간값이 없다.** 기르수 + 엔릴기르수(LINK-4) 는 합이 ``{2, 5}`` 다 —
    3 은 그 사이에 있지만 **고를 수 없는 값**이다. 링크 몬스터를 "1 이상
    자신의 링크 수치 이하" 로 세는 규칙이 아니기 때문이다.

    🔴 엔릴기르수는 **소재로는 쓸 수 있다** — 소재 조건이 등록되지 않은 것은
    「자신을 소환하는 절차」 이고, 소재로 쓰이는 쪽은 그것과 무관하다
    (``test_d03`` 이 그 반대쪽을 센다).
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(ENLILGIRSU,), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "기여의 합은 2 · 5" in verdict.reason


@pytest.mark.real_card
def test_a08_a_normal_monster_breaks_the_per_material_condition(repository):
    """
    🔴 **소재 각각의 조건** (머리말 표 셋째 줄) — 페더맨은 ``MONSTER,NORMAL``
    이므로 효과 몬스터가 아니다.

    장수(3장) 와 합(1+1+1=3) 과 ``includes``(기르수) 는 **모두 맞다.** 그래서
    이 거절은 **카드별 조건 하나**의 것이고, 판정이 그 카드를 지목한다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, FEATHERMAN, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert str(field[1]) in verdict.reason
    assert "효과 몬스터가 아닙니다" in verdict.reason
    assert _offered(duel, extra[0], field) is None


@pytest.mark.real_card
def test_a09_a_token_breaks_the_same_condition(repository):
    """
    🔴 **토큰도 통상 몬스터다** (``MONSTER,NORMAL,TOKEN``) — 같은 조건에서
    같은 이유로 막힌다. 토큰을 "몬스터이므로 통과" 로 두면 이 자리가 열린다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, TOKEN, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert str(field[1]) in verdict.reason
    assert "효과 몬스터가 아닙니다" in verdict.reason


@pytest.mark.real_card
def test_a10_effect_monsters_without_an_orcust_break_the_group_condition(
    repository,
):
    """
    🔴 **소재 집합의 조건** (머리말 표 넷째 줄). 『성장』 세 장은 전부 효과
    몬스터이고 합도 3 이지만 setcode 가 ``0xfe`` 뿐이므로 「오르페골」 이
    **하나도 없다** — ``s.matcheck`` 가 거짓인 판이다.
    """
    duel, field, extra = _board(
        repository, mine=(GROWTH, GROWTH, GROWTH), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "없습니다" in verdict.reason
    assert hex(SET_ORCUST).lower() in verdict.reason.lower()


@pytest.mark.real_card
def test_a11_an_orcust_link_monster_also_satisfies_the_group_condition(
    repository,
):
    """
    🔴 **「오르페골」 을 채우는 것이 메인 덱 몬스터여야 할 이유는 없다.**
    갈라테아도 setcode ``0x11b`` 이므로 ``includes`` 를 채운다 — 조건은
    카드군만 보고 자리를 보지 않는다.

    그리고 이 판은 ``each`` 도 지난다 (『성장』 과 갈라테아 둘 다 효과
    몬스터), 합은 ``1 + {1, 2}`` 에서 3 에 닿는다.
    """
    duel, field, extra = _board(
        repository, mine=(GROWTH,), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason
    assert _offered(duel, extra[0], field) is not None


@pytest.mark.real_card
def test_a12_the_same_instance_cannot_be_chosen_twice(repository):
    """
    🔴 **두 자리에서 막는다.** 소재는 필드를 떠나므로 한 장이 두 자리를 채울
    수 없다 — :class:`PlayerAction` 이 조립에서 막고, 판정을 **직접** 부르는
    길에서는 판정 자신이 막는다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), extra=[LONGIRSU]
    )
    with pytest.raises(MalformedAction):
        PlayerAction.link_summon(
            actor=P0, source=extra[0], materials=(field[0], field[0])
        )

    verdict = _assess(duel, extra[0], (field[0], field[0]))
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "두 번 고를 수 없습니다" in verdict.reason


@pytest.mark.real_card
def test_a13_a_staying_link_monster_in_the_extra_zone_is_undetermined(
    repository,
):
    """
    🔴 **배치는 소재가 떠난 뒤의 판으로 센다.** 여기서는 갈라테아가 **소재가
    아니므로** 엑스트라 몬스터 존(칸 1개) 에 그대로 남는다. 그 경우 링크
    마커가 가리키는 메인 몬스터 존에 놓을 수 있는지는 **칸 기하를 옮기지
    못해 판정할 수 없다** — 모름이고, 모름의 이름을 적는다.

    🔴 **모름을 거절로도 허가로도 바꾸지 않는다** (ADR-006).

    🔴 **그런데 이 판에서 거절 사유 목록은 비어 있다** — 그것이 틀린 것이
    아니다. 후보 생성은 "허가된 조합이 하나라도 있으면 거절 사유를 적지
    않는다" (``Duel._link_summon_actions``), 그리고 여기에는 **허가된 조합이
    있다**: 같은 갈라테아를 **소재로 넣으면** 그 칸이 비므로 배치가 풀린다.
    즉 막힌 것은 "이 조합" 하나이고 "이 카드의 소환" 이 아니다. 두 사실을
    함께 재야 어느 쪽이 막혔는지 읽을 수 있다.
    """
    duel, field, extra = _board(
        repository,
        mine=(GIRSU, GROWTH, GROWTH),
        emzone=(GALATEA,),
        extra=[LONGIRSU],
    )
    materials = tuple(field[:3])
    verdict = _assess(duel, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert verdict.missing_rule == LINK_PLACEMENT_LINKED_RULE
    assert _offered(duel, extra[0], materials) is None

    #: 🔴 **칸을 비우는 조합은 허가된다** — 그래서 위 모름은 조합의 것이다.
    candidates = _link_candidates(duel, extra[0])
    assert candidates, "칸을 비우는 조합도 없으면 위 모름을 조합의 것이라 "\
        "말할 수 없습니다"
    assert all(field[3] in picked for picked in candidates)


@pytest.mark.real_card
def test_a14_candidate_generation_and_the_shared_assessment_agree(repository):
    """
    🔴 **후보 생성과 직접 판정이 같은 집합을 낸다.** 후보 생성이 장수의
    범위를 돌므로 (``rule.counts()``), 그 고리가 빠뜨리거나 더 내놓는 조합이
    있으면 "목록에 없으니 안전하다" 가 거짓이 된다.

    세 몬스터로 만들 수 있는 **모든 부분집합**(1~3장) 을 직접 판정에 물어
    합법인 것만 모으고, 엔진이 낸 후보와 **집합으로** 비교한다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    expected = set()
    for size in range(1, len(field) + 1):
        for picked in combinations(field, size):
            if (
                _assess(duel, extra[0], picked).eligibility
                is LinkMaterialEligibility.LEGAL
            ):
                expected.add(frozenset(picked))

    #: 🔴 **빈 집합이면 이 시험은 아무것도 재지 않는다** — 실제로 합법인
    #: 조합이 있어야 "같다" 가 뜻을 가진다.
    assert expected, "합법 조합이 없으면 일치를 잴 수 없습니다"
    assert _link_candidates(duel, extra[0]) == expected


@pytest.mark.real_card
def test_a15_the_registered_rule_matches_the_lua_we_read(repository):
    """
    🔴 **조건표가 근거와 같은 모양인가.** 머리말의 네 줄을 등록표에서 그대로
    확인하고, **근거를 적지 않은 등록을 허용하지 않는다**.

    🔴 그리고 **효과를 등록한 것이 아님**을 센다 — 이 자료형에는 효과를 적는
    칸이 없다. "소환을 지원했다" 와 "카드를 지원했다" 가 구별되는 근거다.
    """
    rule = material_rule_for(LONGIRSU)
    assert rule is not None
    #: 장수 — 두 수이고 섞이지 않는다.
    assert (rule.count, rule.count_max, rule.max_count) == (2, 3, 3)
    assert rule.counts() == (2, 3)
    assert rule.exact_count is False
    assert rule.accepts_count(2) and rule.accepts_count(3)
    assert not rule.accepts_count(1) and not rule.accepts_count(4)
    #: 기여의 합 — 장수와 **다른 수**다.
    assert rule.link_rating == 3
    #: 소재 각각의 조건 · 소재 집합의 조건.
    assert rule.each.effect_monster is True
    assert rule.includes is not None
    assert rule.includes.setcodes == (SET_ORCUST,)
    #: 근거.
    assert rule.lua_file == "c76145142.lua"
    assert "Link.AddProcedure" in rule.lua_excerpt
    assert "matcheck" in rule.lua_excerpt
    #: 🔴 효과를 적는 칸이 없다.
    assert not hasattr(rule, "effects")
    #: 카드 데이터와 링크 수치가 같은가 — 손으로 적은 수가 데이터와 갈라지면
    #: 합 조건 전체가 틀린다.
    assert repository.get(LONGIRSU).link_rating == rule.link_rating


# ======================================================================
# B. 준비한 작은 상태에서의 소환 실행
#
# 🔴 **이 절의 판이 기존 시작 패에서 도달 가능하다는 주장이 아니다.**
# 손으로 구성한 시작 상태이고, 실제 시작 패에서의 결과는 보고서 §5 다.
# ======================================================================
@pytest.mark.real_card
def test_b01_two_material_summon_moves_everything_it_should(repository):
    """
    🔴 **소재 2장 소환의 실제 변화 전부.** 소재는 묘지로, 롱기르수는 엑스트라
    덱에서 나와 엑스트라 몬스터 존에 앞면 공격 표시로, 그리고 이 턴에 그
    카드명을 링크 소환했다는 기록이 남는다.

    갈라테아가 **소재이므로** 엑스트라 몬스터 존(칸 1개) 이 비고, 그 칸에
    롱기르수가 들어간다 — 배치를 소재가 떠나기 **전**의 판으로 셌다면 이
    소환이 "자리가 없다" 로 막혔을 것이다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    action = _offered(duel, extra[0], tuple(field))
    assert action is not None

    step = duel.apply(action)
    assert step.accepted is True, step.reason

    assert _zone_ids(duel, Zone.EMZONE) == [LONGIRSU]
    assert _zone_ids(duel, Zone.MZONE) == []
    assert sorted(_zone_ids(duel, Zone.GRAVE)) == sorted([GIRSU, GALATEA])
    assert _zone_ids(duel, Zone.EXTRA) == []
    assert _summons(duel, LONGIRSU) == 1
    summoned = duel.state.zone(P0, Zone.EMZONE)[0]
    assert summoned.position is Position.FACEUP_ATTACK


@pytest.mark.real_card
def test_b02_three_material_summon_moves_all_three(repository):
    """
    🔴 **장수가 범위인 카드의 다른 끝도 실제로 실행된다.** 소재 세 장이 모두
    묘지로 가고, 남은 엑스트라 덱 카드(엔릴기르수) 는 **그대로 있다** —
    소환한 것만 나온다.
    """
    duel, field, extra = _board(
        repository,
        mine=(GIRSU, GROWTH, GROWTH),
        extra=[LONGIRSU, ENLILGIRSU],
    )
    action = _offered(duel, extra[0], tuple(field))
    assert action is not None
    assert duel.apply(action).accepted is True

    assert _zone_ids(duel, Zone.EMZONE) == [LONGIRSU]
    assert _zone_ids(duel, Zone.MZONE) == []
    assert sorted(_zone_ids(duel, Zone.GRAVE)) == sorted([GIRSU, GROWTH, GROWTH])
    assert _zone_ids(duel, Zone.EXTRA) == [ENLILGIRSU]
    assert _summons(duel, LONGIRSU) == 1
    assert _summons(duel, ENLILGIRSU) == 0


@pytest.mark.real_card
def test_b03_a_material_sent_to_the_graveyard_opens_its_own_trigger(repository):
    """
    🔴 **소재가 묘지로 간 사건이 유발 기회를 연다** — 그리고 그것이 **정상
    경로**로 처리된다.

    성유물－『성장』 ② 는 ``EVENT_TO_GRAVE`` 의 임의 유발이다. 링크 소재로
    묘지에 간 두 장이 **각각** 기회를 열고, 그 제안들은 관문 다섯을 모두
    지난다 (``event_relation`` · ``activation_zone`` · ``trigger_condition``
    · ``execution_authority`` · ``cost_feasibility``).

    🔴 **그 뒤에 막히는 것은 롱기르수와 무관한 자리다.** 패의 『성관』 을
    지금 특수 소환할 수 있는지(``may_be_special_summoned``) 는 이 엔진이
    답하지 못하는 질문이고 (소환 이력을 적는 자리가 없다 — 6-AD), 그래서
    발동 후보로는 오르지 않고 **보류에 그 이유가 적힌다.** 그 둘을 섞지
    않는다: 사건과 기회는 **열렸고**, 막힌 것은 **다른 미지원**이다.

    🔴 그리고 **흐름이 그 기회를 건너뛰지 않는다** — 유발 처리 기회가 열려
    있는 동안 페이즈를 넘기는 수가 보류된다.
    """
    duel, field, extra = _board(
        repository,
        mine=(GIRSU, GROWTH, GROWTH),
        extra=[LONGIRSU],
        hand=(CROWN,),
    )
    action = _offered(duel, extra[0], tuple(field))
    assert action is not None
    assert duel.apply(action).accepted is True
    duel.advance()

    offers = duel.triggers.offers(duel, P0)
    growth_offers = [
        offer for offer in offers if offer.effect_ref.card_id == GROWTH
    ]
    #: 🔴 묘지로 간 『성장』 **두 장이 각각** 기회를 연다 — 한 장의 기회가
    #: 다른 장의 것을 닫지 않는다.
    assert len(growth_offers) == 2
    assert {offer.source for offer in growth_offers} == {field[1], field[2]}
    for offer in growth_offers:
        assert offer.is_optional is True
        assert "activation_zone=valid" in offer.reason
        assert "trigger_condition=valid" in offer.reason
        #: 사건은 **소재가 묘지로 간 그 이동**이다.
        assert offer.event.delta.destination_zone is Zone.GRAVE
        assert offer.event.delta.card in (field[1], field[2])

    legal = duel.legal_actions(P0)
    activations = [
        w
        for w in legal.withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert activations, "기회가 열렸는데 보류 사유가 없습니다"
    assert any("may_be_special_summoned" in w.reason for w in activations)
    #: 🔴 막힌 이유가 **링크 소재 조건이 아니다.**
    assert not any(
        w.missing == LINK_MATERIAL_RULE_MISSING for w in activations
    )
    #: 흐름이 그 기회를 지나가 버리지 않는다.
    assert any(
        w.kind is PlayerActionKind.END_PHASE for w in legal.withheld
    )


@pytest.mark.real_card
def test_b04_a_refusal_changes_nothing(repository):
    """
    🔴 **거절은 판을 건드리지 않는다.** 소재 조건이 깨진 조합을 손으로 조립해
    ``apply`` 에 넣고, 판 · 소환 기록 · 모든 존이 그대로인지 본다.

    🔴 손으로 만든 행동도 **같은 검사**를 받는다 — 후보 목록을 지나지 않은
    길에 우회가 없어야 한다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), extra=[LONGIRSU]
    )
    duel.advance()
    before = _snapshot(duel)

    action = PlayerAction.link_summon(
        actor=P0, source=extra[0], materials=tuple(field)
    )
    step = duel.apply(action)
    assert step.accepted is False
    assert _snapshot(duel) == before
    assert _summons(duel, LONGIRSU) == 0


@pytest.mark.real_card
def test_b05_a_fork_summons_without_touching_the_original(repository):
    """
    🔴 **사본에서 소환해도 원본은 그대로다.** 탐색이 밟는 길이 이것이므로
    (``Simulator.fork``), 여기서 새는 것이 있으면 탐색이 진짜 판을 바꾼다.
    """
    from agent.simulation import Simulator

    duel, field, extra = _board(
        repository, mine=(GIRSU,), emzone=(GALATEA,), extra=[LONGIRSU]
    )
    duel.advance()
    before = _snapshot(duel)

    fork = Simulator(duel).fork()
    fork.advance()
    action = next(
        a
        for a in fork.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.LINK_SUMMON
    )
    assert fork.apply(action).accepted is True

    assert [c.card_id for c in fork.state.zone(P0, Zone.EMZONE)] == [LONGIRSU]
    assert _snapshot(duel) == before
    assert _zone_ids(duel, Zone.EXTRA) == [LONGIRSU]


# ======================================================================
# C. 탐색 · 재생 통합 (준비한 상태에서)
# ======================================================================
@pytest.mark.real_card
def test_c01_the_search_finds_the_summon_and_the_rerun_verifies_it(repository):
    """
    🔴 **탐색이 찾고, 다시 조립한 초기 상태에서 재생이 검증한다.**

    탐색기 안에는 "롱기르수면 이렇게" 같은 분기가 없다 — 목표 판정은
    ``FieldGoal`` 하나이고, 후보는 엔진이 허가한 것뿐이다. 그래서 이 시험이
    재는 것은 **등록이 탐색 경로까지 닿았는가**다.

    재생은 ``_board`` 를 **다시 불러** 만든 판에서 돈다 (같은 입력 · 같은
    씨앗) — 탐색이 쓴 판을 재활용하지 않는다.
    """
    from agent.bounded_search import (
        BoundedSearch,
        FieldGoal,
        SearchBudget,
        rerun_steps,
    )

    setup = dict(mine=(GIRSU,), emzone=(GALATEA,), extra=[LONGIRSU])
    duel, _field, _extra = _board(repository, **setup)
    before = duel.state.state_hash()

    search = BoundedSearch(
        goal=FieldGoal(LONGIRSU, P0),
        budget=SearchBudget(max_depth=4, max_nodes=30),
    )
    outcome = search.run(duel)
    assert outcome.reached is True, outcome.goal_reason
    #: 경로에 **링크 소환이 들어 있다** (패스만으로 닿은 것이 아니다).
    assert any(
        step.kind == PlayerActionKind.LINK_SUMMON.value for step in outcome.path
    )
    #: 🔴 탐색은 원본을 밟지 않는다.
    assert duel.state.state_hash() == before

    fresh, _f, _e = _board(repository, **setup)
    rerun = rerun_steps(
        fresh,
        outcome.path,
        FieldGoal(LONGIRSU, P0),
        expect_field=outcome.final_field,
        expect_hash=outcome.final_state_hash,
    )
    assert rerun.ok is True, rerun.describe_ko()
    assert rerun.goal_reached is True
    assert rerun.matches_search is True
    assert rerun.steps == len(outcome.path)
    #: 🔴 재생도 **사본에서** 돈다 — 넘긴 초기 상태는 그대로다.
    assert [c.card_id for c in fresh.state.zone(P0, Zone.EMZONE)] == [GALATEA]
    assert [c.card_id for c in fresh.state.zone(P0, Zone.EXTRA)] == [LONGIRSU]
    #: 그리고 재생이 센 최종 자신 필드에 롱기르수가 **있다**.
    assert any(
        card_id == LONGIRSU and face_up
        for _zone, card_id, face_up in rerun.final_field
    )


def test_c02_the_cli_goal_table_names_this_card_without_a_new_command():
    """
    🔴 **기존 흐름을 재사용한다.** ``--search`` / ``search:`` 가 읽는 목표
    이름표에 한 줄이 늘었을 뿐이고, 새 인자도 새 명령도 없다.

    🔴 **이름표의 ID 가 등록표의 카드와 같은가** — 두 자리가 갈라지면
    사용자가 고른 목표와 엔진이 허가하는 소환이 다른 카드가 된다.
    """
    from app.main import SEARCH_GOALS, search_goal_card_id

    assert search_goal_card_id("longirsu") == LONGIRSU
    assert search_goal_card_id("LONGIRSU") == LONGIRSU
    #: 모르는 이름은 **추측하지 않는다** (기존 규율).
    assert search_goal_card_id("longirs") is None
    assert search_goal_card_id("") is None
    #: 이름표의 모든 목표가 **실제 카드 ID** 이고, 그중 롱기르수는 등록표에
    #: 있다.
    assert SEARCH_GOALS["galatea"] == GALATEA
    assert material_rule_for(SEARCH_GOALS["longirsu"]) is not None


# ======================================================================
# D. 보존과 미지원 유지
# ======================================================================
@pytest.mark.real_card
def test_d01_galatea_and_galatea_i_are_unchanged(repository):
    """
    🔴 **이전 등록은 한 글자도 바뀌지 않았다.** ``count_max`` 의 기본값이
    ``None`` 이므로 두 카드는 여전히 **정확히 그 장수**다.
    """
    for card_id, count in ((GALATEA, 2), (GALATEA_I, 1)):
        rule = material_rule_for(card_id)
        assert rule is not None
        assert rule.count == count
        assert rule.count_max is None
        assert rule.max_count == count
        assert rule.exact_count is True
        assert rule.counts() == (count,)
        assert "정확히" in rule.count_ko()

    #: 그리고 실제 판에서 갈라테아가 **그대로 소환된다** (2장 · 합 2).
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH), extra=[GALATEA]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason
    assert _offered(duel, extra[0], field) is not None


@pytest.mark.real_card
def test_d02_galateas_count_did_not_become_a_range(repository):
    """
    🔴 **범위가 번지지 않았다.** 롱기르수에 범위를 더한 변경이 갈라테아의
    장수까지 느슨하게 만들었다면 이 세 장 조합이 통과한다 — 통과하면 안
    된다. 거절 문장이 "정확히 2장" 이라고 적는 것까지 본다.
    """
    duel, field, extra = _board(
        repository, mine=(GIRSU, GROWTH, GROWTH), extra=[GALATEA]
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "3장입니다" in verdict.reason
    assert "정확히 2장" in verdict.reason
    assert _offered(duel, extra[0], field) is None


@pytest.mark.real_card
def test_d03_an_unregistered_link_monster_is_still_undetermined(repository):
    """
    🔴 **다른 링크 몬스터가 이번 변경으로 열리지 않는다** (ADR-006).

    엔릴기르수(LINK-4) 는 **같은 레시피 · 같은 카드군 · 같은 엑스트라 덱**에
    있고, 이 판은 효과 몬스터 4장에 「오르페골」 도 있다. 즉 "카드군과 장수가
    맞으면 통과" 같은 우회가 있었다면 **바로 여기서 통과한다.** 답은 모름이고,
    모름의 이름은 "소재 조건을 아직 읽지 않았다" 다.
    """
    duel, field, extra = _board(
        repository,
        mine=(GIRSU, GROWTH, GROWTH, GROWTH),
        extra=[ENLILGIRSU],
    )
    verdict = _assess(duel, extra[0], field)
    assert verdict.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert verdict.missing_rule == LINK_MATERIAL_RULE_MISSING
    assert _link_candidates(duel, extra[0]) == set()
    assert ("rule_not_implemented", LINK_MATERIAL_RULE_MISSING) in _withheld_links(
        duel
    )


def test_d04_the_registry_holds_one_range_and_the_bounds_are_sound():
    """
    🔴 **등록표 전수.** 이번에 범위가 생긴 카드는 **하나**이고, 모든 등록이
    ``1 <= count <= max_count <= link_rating`` 을 지킨다 — 소재 한 장의 최소
    기여가 1 이므로 ``link_rating`` 보다 많은 장수는 합에 **절대** 닿지
    않는다.

    🔴 그리고 **모든 등록이 근거를 들고 있다** — 근거 없는 등록이 생기면
    "읽었다" 와 "그럴 것이다" 가 섞인다.
    """
    ranged = [rule for rule in LINK_MATERIAL_RULES if not rule.exact_count]
    assert [rule.card_id for rule in ranged] == [LONGIRSU]

    for rule in LINK_MATERIAL_RULES:
        assert 1 <= rule.count <= rule.max_count <= rule.link_rating, rule
        assert rule.counts()[0] == rule.count
        assert rule.counts()[-1] == rule.max_count
        assert rule.lua_file
        assert rule.lua_excerpt
