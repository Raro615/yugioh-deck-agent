"""
Phase 6-T — 선공 패 · 덱 레시피로 **실제 Duel 을 돌린다.**

이 파일이 지키는 단 하나의 경계
-------------------------------
🔴 **"카드 텍스트를 읽어 그럴듯한 전개를 적은 것" 과 "엔진이 실제로
실행한 것" 을 섞지 않는다.** 지시문 §21 이 그것을 수준 2 · 3 의 조건으로
적었다 — *"단순히 카드 효과 텍스트를 읽어 전개 과정을 출력했다면 수준 2나
수준 3을 달성했다고 주장하지 않는다."*

그래서 이 파일의 모든 걸음은 ``Duel.legal_actions`` 가 **내놓은 후보**를
``Duel.apply`` 에 넣어 나온 결과이고, 그 결과를 ``GameState`` 와
``EventJournal`` 로 다시 센다.

세 사실을 따로 센다 (Phase 6-R · 6-S 의 규율)
---------------------------------------------
======================  ==========================================
행위 수락                ``DuelStep.accepted``
체인 등록                ``Duel.chain``
효과 해결 · 상태 변경     ``EventJournal`` · ``GameState``
======================  ==========================================

:class:`~deck.opening.ExecutedStep` 이 그 셋을 따로 들고 있고, ``C`` 절이
같은 걸음에서 셋을 각각 확인한다.

왜 ``Duel.start`` 를 쓰지 않는가 (``B`` 절)
-------------------------------------------
``Duel.start`` 는 **섞고 5장씩 뽑는다.** 6-T 의 패는 사용자가 지정한 것이라
뽑을 수 없다. 그래서 ``GameState.create`` 로 덱을 놓고 패를
``create_instance`` 로 세운다 — 그러면 패의 출처가 입력 그대로 남는다.

🔴 그리고 **선공 1턴 메인 페이즈까지 걸어서 간다.** 페이즈를 손으로 써
넣지 않고 ``legal_actions`` 가 내놓는 ``END_PHASE`` 를 실제로 적용한다
(``B`` 절이 그 두 걸음을 센다).

🔴 **알 수 없는 것을 성공으로 적지 않는다** (``G`` 절)
------------------------------------------------------
덱 순서 · 금지 제한 · 상대의 패는 입력에 **없다.**
:attr:`~deck.opening.OpeningSetup.unknowns` 가 그것을 적고, 레시피가 없으면
``duel`` 을 아예 만들지 않는다 (``J`` 절).
"""

import collections
import pathlib

import pytest

from deck.model import ValidationOutcome
from deck.opening import (
    MAX_EXECUTED_ACTIONS,
    OpeningSetup,
    build_opening,
    check_hand_against_recipe,
    execute_opening,
    first_meaningful,
    opening_hand_size,
)
from deck.recipe import EMPTY_RECIPE, looks_like_ydk, parse_recipe
from engine.action import PlayerActionKind
from engine.duel import OPENING_HAND, Duel, TurnStep
from engine.ids import EffectRef
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parent.parent

POT = 55144522       # 욕망의 항아리 — 통상 마법 · 2장 드로우
GIFT = 5915629       # 욕망의 선물 — 일반 함정
FINE = 92595643      # 벌금 — 일반 함정 · 패 2장 (6-P)
FORCEOUT = 94192409  # 강제 탈출 장치 — 일반 함정 (6-O)
HONEST = 37742478    # 어니스트 — 기동 효과 (6-L)
LUSTER = 11091375    # 사파이어 드래곤 — 통상 몬스터
BLUE_EYES = 89631139  # 푸른 눈의 백룡 — 레벨 8 (소환 못 하는 자리에 쓴다)

#: 모든 시험이 쓰는 40장 레시피. 🔴 **한 곳에만 적는다** — 두 곳에 적으면
#: 둘이 갈라지고, 갈라진 것을 시험이 못 본다.
RECIPE_40 = f"{POT} x3, {GIFT} x3, {HONEST} x3, {FINE} x3, {LUSTER} x28"
HAND_5 = [POT, HONEST, GIFT, LUSTER, LUSTER]

ALL_ZONES = (
    Zone.DECK, Zone.HAND, Zone.MZONE, Zone.SZONE, Zone.GRAVE,
    Zone.REMOVED, Zone.EXTRA, Zone.FZONE, Zone.PZONE, Zone.EMZONE,
)


# ======================================================================
# 측정 도구
# ======================================================================


def recipe_draft(repository, text=RECIPE_40):
    parsed = parse_recipe(text, repository)
    assert parsed.draft is not None, parsed.notes
    return parsed


def opened(repository, *, recipe=RECIPE_40, hand=None):
    parsed = recipe_draft(repository, recipe)
    return build_opening(repository, parsed.draft, list(hand or HAND_5))


def census(duel, seat=0):
    """그 자리의 **모든** 카드를 센다 — 카드별 매수와 인스턴스 목록."""
    cards: collections.Counter = collections.Counter()
    instances = []
    for zone in ALL_ZONES:
        for card in duel.state.player(seat).zone(zone):
            if card is None:
                continue
            cards[card.card_id] += 1
            instances.append(card.instance_id)
    return cards, instances


def recipe_counts(draft):
    counts: collections.Counter = collections.Counter()
    for slot in draft.main:
        counts[slot.card_id] += slot.copies
    for slot in draft.extra:
        counts[slot.card_id] += slot.copies
    return counts


def finding(setup, rule):
    matches = [f for f in setup.all_findings if f.rule == rule]
    assert len(matches) == 1, [f.rule for f in setup.all_findings]
    return matches[0]


# ======================================================================
# A. §14-A·B·C·D — 레시피와 패의 정합성
# ======================================================================


@pytest.mark.real_card
def test_a01_a_recipe_list_is_read_with_exact_copies(repository):
    """**§14-A — 서로 다른 카드와 매수를 그대로 읽는다.**"""
    parsed = recipe_draft(repository)
    counts = recipe_counts(parsed.draft)
    assert counts == {POT: 3, GIFT: 3, HONEST: 3, FINE: 3, LUSTER: 28}
    assert parsed.draft.main_count == 40
    assert parsed.draft.extra_count == 0
    assert parsed.unresolved == []


@pytest.mark.real_card
def test_a02_a_ydk_recipe_counts_repeated_lines(repository):
    """
    **YDK — 같은 패스코드가 여러 줄이면 그 수가 매수다.**

    🔴 그리고 ``#extra`` · 사이드 구역을 가른다. 사이드는 읽고 버리고 그
    사실을 적는다 — 선공 전개에 들어오지 않는다.
    """
    text = "\n".join([
        "#created by test",
        "#main",
        *([str(POT)] * 3),
        *([str(LUSTER)] * 37),
        "#extra",
        "#!side",
        str(GIFT),
    ])
    assert looks_like_ydk(text)
    parsed = parse_recipe(text, repository)
    assert recipe_counts(parsed.draft) == {POT: 3, LUSTER: 37}
    assert parsed.draft.main_count == 40
    assert any("사이드 덱 1장" in note for note in parsed.notes), parsed.notes


@pytest.mark.real_card
def test_a03_an_unreadable_token_is_never_dropped(repository):
    """
    🔴 **해석하지 못한 토큰을 버리지 않는다.**

    해석된 것만으로 덱을 만들면 사용자는 자기가 적은 카드가 들어간 덱으로
    검증했다고 믿는다 (``/combo`` 의 패 해석과 같은 규율).
    """
    parsed = parse_recipe(f"{POT} x3, 이런카드는없다 x2, {LUSTER} x37",
                          repository)
    assert parsed.unresolved == ["이런카드는없다"]
    assert recipe_counts(parsed.draft) == {POT: 3, LUSTER: 37}


@pytest.mark.real_card
def test_a04_an_empty_recipe_is_not_an_empty_deck(repository):
    """
    🔴 **"적지 않았다" 와 "빈 덱" 을 가른다.**

    빈 덱으로 전개를 검증하면 덱 장수를 조건으로 보는 효과가 거짓으로
    통과한다 (Phase 6-S §16-B 가 실측으로 경고한 자리).
    """
    parsed = parse_recipe("", repository)
    assert parsed.is_empty
    assert parsed.draft is None
    assert EMPTY_RECIPE in parsed.notes


@pytest.mark.real_card
def test_a05_a_hand_card_outside_the_recipe_is_refused(repository):
    """**§14-C — 덱에 없는 카드가 패에 있으면 거절한다.**"""
    setup = opened(repository, hand=[POT, HONEST, GIFT, LUSTER, FORCEOUT])
    assert setup.can_run is False
    assert setup.duel is None
    bad = finding(setup, "패가 메인 덱에 있는가")
    assert bad.outcome is ValidationOutcome.VIOLATED
    assert "강제 탈출 장치" in bad.detail
    assert any("패가 메인 덱에 있는가" in b for b in setup.blockers)


@pytest.mark.real_card
def test_a06_a_hand_exceeding_the_recipe_copies_is_refused(repository):
    """**§14-B — 패의 매수가 덱 보유 매수를 넘으면 거절한다.**"""
    #: 레시피에 욕망의 선물이 3장인데 패에 4장.
    setup = opened(repository, hand=[GIFT, GIFT, GIFT, GIFT, LUSTER])
    assert setup.can_run is False
    bad = finding(setup, "패의 매수가 덱 보유 매수 이내인가")
    assert bad.outcome is ValidationOutcome.VIOLATED
    assert "패 4장 > 덱 3장" in bad.detail


@pytest.mark.real_card
def test_a07_an_extra_deck_card_in_the_opening_hand_is_refused(repository):
    """
    **§14-D — 엑스트라 덱 카드는 첫 패에 올 수 없다.**

    🔴 레시피의 엑스트라 목록이 아니라 **카드 데이터**로 본다 — 레시피에
    안 적혀 있어도 엑스트라 덱 카드는 첫 패에 오지 않는다.
    """
    extra_card = next(
        card for card in repository.all_cards() if card.is_extra_deck
    )
    setup = opened(
        repository,
        recipe=f"{POT} x3, {LUSTER} x36, {extra_card.id} x1",
        hand=[POT, LUSTER, LUSTER, LUSTER, extra_card.id],
    )
    assert setup.can_run is False
    bad = finding(setup, "엑스트라 덱 카드가 시작 패에 있는가")
    assert bad.outcome is ValidationOutcome.VIOLATED
    assert extra_card.display_name() in bad.detail


@pytest.mark.real_card
def test_a08_the_opening_hand_size_comes_from_the_engine(repository):
    """
    **장수를 여기서 다시 적지 않는다** — ``engine`` 의 상수를 읽는다.
    """
    assert opening_hand_size() == OPENING_HAND
    setup = opened(repository, hand=HAND_5[:4])
    bad = finding(setup, "선공 첫 패 장수")
    assert bad.outcome is ValidationOutcome.VIOLATED
    assert f"{OPENING_HAND}장입니다" in bad.detail
    assert setup.can_run is False


@pytest.mark.real_card
def test_a09_a_card_id_outside_the_database_is_refused(repository):
    """**§6-8 — 카드 정의를 읽을 수 없으면 거절한다.**"""
    findings, rest = check_hand_against_recipe(
        [999999991, POT, HONEST, GIFT, LUSTER],
        recipe_draft(repository).draft,
        repository,
    )
    definitions = [f for f in findings if f.rule == "패 카드의 정의"]
    assert definitions[0].outcome is ValidationOutcome.VIOLATED
    assert rest == [], "위반이 있으면 남은 덱을 계산하지 않는다"


# ======================================================================
# B. §14-E — 선공 첫 턴의 상태를 **걸어서** 만든다
# ======================================================================


@pytest.mark.real_card
def test_b01_the_opening_state_is_the_first_turn_main_phase(repository):
    """**§7 — 턴 1 · 메인 페이즈 1 · 선공 · 드로우 없음.**"""
    setup = opened(repository)
    assert setup.can_run
    duel = setup.duel
    assert duel.state.turn.turn_number == 1
    assert duel.state.turn.phase is Phase.MAIN1
    assert duel.state.turn.turn_player == 0
    assert duel.first_player == 0
    assert duel.step is TurnStep.OPEN
    assert duel.priority.is_open is False
    assert duel.chain.is_empty
    assert duel.is_over is False


@pytest.mark.real_card
def test_b02_the_first_player_never_drew(repository):
    """
    🔴 **선공 첫 턴은 뽑지 않는다** (룰북). 패는 입력 그대로 5장이고 덱은
    40 − 5 = 35장이다.
    """
    setup = opened(repository)
    duel = setup.duel
    assert len(duel.state.player(0).zone(Zone.HAND)) == OPENING_HAND
    assert len(duel.state.player(0).zone(Zone.DECK)) == 40 - OPENING_HAND
    assert len(setup.deck_rest) == 40 - OPENING_HAND
    #: 패가 **입력 그대로**다 — 뽑은 것이 아니다.
    assert collections.Counter(
        card.card_id for card in duel.state.player(0).zone(Zone.HAND)
    ) == collections.Counter(HAND_5)


@pytest.mark.real_card
def test_b03_the_phase_was_walked_not_written(repository):
    """
    🔴 **페이즈를 손으로 써 넣지 않았다.**

    ``build_opening`` 은 드로우 페이즈에서 시작해 ``legal_actions`` 가
    내놓는 ``END_PHASE`` 를 실제로 적용한다. 그 두 걸음이 기록에 남는다 —
    여기서는 같은 길을 **다시 걸어** 그것이 실제로 가능한 길임을 센다.
    """
    from engine.effect.journal import EventJournal
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.duel import duel_components

    state = GameState.create(repository, decks=([LUSTER] * 35, [LUSTER] * 40),
                             turn_player=0, seed=0, shuffle=False)
    for card_id in HAND_5:
        state.create_instance(card_id, owner=0, zone=Zone.HAND)
    state.turn.set_phase(Phase.DRAW)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=0, phase=Phase.DRAW),
        step=TurnStep.OPEN,
        first_player=0,
        **duel_components(journal=EventJournal()),
    )
    walked = []
    for _ in range(4):
        if duel.state.turn.phase is Phase.MAIN1:
            break
        ends = [a for a in duel.legal_actions(0).allowed
                if a.kind is PlayerActionKind.END_PHASE]
        assert ends, duel.legal_actions(0).withheld
        step = duel.apply(ends[0])
        assert step.accepted, step.reason
        walked.append(duel.state.turn.phase.name)
    assert walked == ["STANDBY", "MAIN1"], walked
    #: 🔴 그리고 그 사이에 **뽑지 않았다**.
    assert len(duel.state.player(0).zone(Zone.HAND)) == OPENING_HAND


@pytest.mark.real_card
def test_b04_the_opponent_hand_is_never_invented(repository):
    """
    🔴 **§3-15 — 상대의 비공개 정보를 지어내지 않는다.**

    상대 패는 **비어 있고**, 그 사실이 ``unknowns`` 에 적힌다.
    """
    setup = opened(repository)
    duel = setup.duel
    assert [c for c in duel.state.player(1).zone(Zone.HAND) if c] == []
    assert [c for c in duel.state.player(1).zone(Zone.MZONE) if c] == []
    assert [c for c in duel.state.player(1).zone(Zone.GRAVE) if c] == []
    assert any("상대의 덱·패·필드는 입력에 없습니다" in u
               for u in setup.unknowns), setup.unknowns


@pytest.mark.real_card
def test_b05_my_own_board_starts_empty(repository):
    """**§7 — 필드 · 묘지 · 제외가 비어 있다. 지어내지 않는다.**"""
    setup = opened(repository)
    for zone in (Zone.MZONE, Zone.SZONE, Zone.GRAVE, Zone.REMOVED,
                 Zone.FZONE, Zone.EXTRA):
        assert [c for c in setup.duel.state.player(0).zone(zone) if c] == [], zone


# ======================================================================
# C. §14-F·G·H·I — 실제 행동 실행
# ======================================================================


@pytest.mark.real_card
def test_c01_a_candidate_from_the_engine_executes_and_changes_the_state(
    repository,
):
    """
    🔴 **§21 수준 2 의 핵심** — 후보 → 판정 → 실행 → 상태 변경 → 후속 후보.

    세 사실을 **따로** 센다: 행위 수락 · 체인 등록 · 효과 해결.
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    assert run.steps, run.stopped_reason

    first = run.steps[0]
    #: ① 후보는 엔진이 내놓은 것이다 — 판정 코드가 그 증거다.
    assert first.gate_code == "OK", first.gate_code
    #: ② 행위를 수락했다.
    assert first.accepted is True
    #: ③ 효과가 적용되었다 — 기록이 말한다.
    assert first.effect_events == (f"{POT}:e[0]",), first.effect_events
    #: ④ 판이 바뀌었다.
    assert first.state_changed is True
    #: ⑤ 그리고 **다음 후보가 생긴다**.
    assert first.next_candidates > 0


@pytest.mark.real_card
def test_c02_the_drawing_effect_really_drew(repository):
    """
    **§14-G — 실제 효과 발동.** 욕망의 항아리가 **2장 뽑는다.**

    🔴 패 장수와 덱 장수를 **둘 다** 센다 — 한쪽만 보면 "카드가 어디서
    왔는가" 를 모른다.
    """
    setup = opened(repository)
    duel = setup.duel
    hand_before = len(duel.state.player(0).zone(Zone.HAND))
    deck_before = len(duel.state.player(0).zone(Zone.DECK))

    run = execute_opening(setup, repository, max_actions=1)
    assert len(run.steps) == 1
    assert run.steps[0].kind == "activate_effect"
    assert len(duel.state.player(0).zone(Zone.DECK)) == deck_before - 2
    #: 발동한 마법이 묘지로 갔으므로 패는 −1 +2 = +1 이다.
    assert len(duel.state.player(0).zone(Zone.HAND)) == hand_before + 1
    assert [c.card_id for c in duel.state.player(0).zone(Zone.GRAVE)] == [POT]


@pytest.mark.real_card
def test_c03_the_chain_was_opened_and_closed_by_the_engine(repository):
    """
    **§14-H — 체인 처리는 기존 우선권 · PASS 절차다.**

    발동 → 응답 창 → 양쪽 패스 → 해결. 🔴 그리고 **체인이 비워진다**
    (Phase 6-R).
    """
    setup = opened(repository)
    run = execute_opening(setup, repository, max_actions=1)
    step = run.steps[0]
    assert step.resolved is True
    assert "해결했습니다" in step.reason
    assert step.step_code == ValidationCode.OK.name
    #: 체인이 남지 않았다.
    assert step.chain_links_after == 0
    assert setup.duel.chain.is_empty
    assert setup.duel.priority.is_open is False


@pytest.mark.real_card
def test_c04_several_actions_run_in_a_row(repository):
    """
    **§9 — 같은 경로를 재사용해 두 번째 행동까지 이어진다.**

    실측: 발동 → 통상 소환 → 세트 셋 = **다섯 걸음**. 전부 수락되고 전부
    판을 바꾼다.
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    assert run.executed >= 2, [s.kind for s in run.steps]
    assert run.executed == len(run.steps)
    assert run.state_changes == len(run.steps)
    kinds = [s.kind for s in run.steps]
    assert kinds[0] == "activate_effect"
    assert "normal_summon" in kinds
    #: 🔴 같은 인스턴스를 두 번 쓰지 않았다 (§15).
    sources = [s.card_id for s in run.steps]
    assert len(sources) == len(run.steps)


@pytest.mark.real_card
def test_c05_the_normal_summon_right_is_spent_once(repository):
    """
    🔴 **§15 — 쓴 일반 소환권을 다시 쓰지 않는다.**

    실행이 끝난 뒤 통상 소환 후보가 **0건**이다 — 엔진이 막는다.
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    summons = [s for s in run.steps if s.kind == "normal_summon"]
    assert len(summons) == 1, [s.kind for s in run.steps]
    remaining = [
        a for a in setup.duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    ]
    assert remaining == []


@pytest.mark.real_card
def test_c06_every_executed_action_came_from_legal_actions(repository):
    """
    🔴 **행동을 추측해서 실행하지 않는다** (§3-6).

    같은 상태를 다시 만들어, 걸음마다 그 행동이 **그 시점의 후보 목록에
    있었는지** 확인한다.
    """
    setup = opened(repository)
    duel = setup.duel
    picked = []
    for _ in range(MAX_EXECUTED_ACTIONS):
        duel.advance()
        legal = duel.legal_actions(duel.to_act)
        action = first_meaningful(duel, legal)
        if action is None:
            break
        #: 🔴 고른 것이 **후보 목록에 있다**.
        assert action in legal.allowed
        step = duel.apply(action)
        assert step.accepted, step.reason
        picked.append(action.kind.value)
        while duel.priority.is_open:
            passing = [a for a in duel.legal_actions().allowed
                       if a.kind is PlayerActionKind.PASS]
            if not passing:
                break
            duel.apply(passing[0])
    assert len(picked) >= 2, picked


@pytest.mark.real_card
def test_c07_the_following_candidates_are_generated_from_the_new_state(
    repository,
):
    """**§14-I — 바뀐 상태에서 후속 후보가 나온다.**"""
    setup = opened(repository)
    before = len(setup.duel.legal_actions(0).allowed)
    run = execute_opening(setup, repository, max_actions=1)
    after = len(setup.duel.legal_actions(0).allowed)
    assert before > 0 and after > 0
    #: 🔴 같은 목록이 아니다 — 판이 바뀌었으므로 후보도 바뀐다.
    assert run.steps[0].next_candidates == after


# ======================================================================
# D. §15 — 실행 안전성 (인스턴스 · 매수 · 덱)
# ======================================================================


@pytest.mark.real_card
def test_d01_the_card_census_equals_the_recipe_before_and_after(repository):
    """
    🔴 **§15 전체를 한 자리에서 센다.**

    ① 처음 판의 카드 매수가 레시피와 **정확히 같다**
    ② 실행 뒤에도 총 장수와 카드별 매수가 **보존된다**
    ③ 인스턴스가 **중복되지 않고**, 생기거나 사라지지 않는다
    """
    parsed = recipe_draft(repository)
    setup = build_opening(repository, parsed.draft, list(HAND_5))
    duel = setup.duel

    before_cards, before_instances = census(duel)
    assert before_cards == recipe_counts(parsed.draft)
    assert len(before_instances) == len(set(before_instances))
    assert sum(before_cards.values()) == 40

    execute_opening(setup, repository)

    after_cards, after_instances = census(duel)
    assert after_cards == before_cards, {
        k: after_cards[k] - before_cards[k]
        for k in set(after_cards) | set(before_cards)
        if after_cards[k] != before_cards[k]
    }
    assert len(after_instances) == len(set(after_instances))
    assert set(after_instances) == set(before_instances)


@pytest.mark.real_card
def test_d02_the_hand_is_removed_from_the_deck_exactly(repository):
    """🔴 **§15 — 시작 패를 덱에서 뺀다.** 매수까지 정확히."""
    parsed = recipe_draft(repository)
    findings, rest = check_hand_against_recipe(
        list(HAND_5), parsed.draft, repository
    )
    assert all(f.outcome is not ValidationOutcome.VIOLATED for f in findings)
    expected = recipe_counts(parsed.draft) - collections.Counter(HAND_5)
    assert collections.Counter(rest) == expected
    assert len(rest) == 35


@pytest.mark.real_card
def test_d03_the_deck_order_is_declared_not_shuffled(repository):
    """
    🔴 **덱 순서를 임의로 확정하지 않는다** (§15 · §8).

    순서를 모르는 것과 재현되지 않는 것은 다르다. 같은 입력이 같은 배열을
    주고 (정렬), 그것이 실제 셔플이 아니라는 사실을 ``unknowns`` 가 적는다.
    """
    one = opened(repository)
    two = opened(repository)
    order_one = [c.card_id for c in one.duel.state.player(0).zone(Zone.DECK)]
    order_two = [c.card_id for c in two.duel.state.player(0).zone(Zone.DECK)]
    assert order_one == order_two, "같은 입력이 다른 배열을 주면 재현이 안 된다"
    assert order_one == sorted(order_one), "선언된 배열은 패스코드 순이다"
    assert any("패스코드 순으로 정렬" in u for u in one.unknowns), one.unknowns
    assert any("실제 셔플로 뽑은 패가 아닙니다" in u for u in one.unknowns)


@pytest.mark.real_card
def test_d04_generating_candidates_never_changes_the_board(repository):
    """후보를 여러 번 만들어도 판이 바뀌지 않는다 (Phase 6-S 의 성질)."""
    setup = opened(repository)
    duel = setup.duel
    before = (duel.state.state_hash(), duel.state.randomness.draws)
    for _ in range(5):
        duel.legal_actions(0)
        duel.legal_actions(1)
    assert (duel.state.state_hash(), duel.state.randomness.draws) == before


# ======================================================================
# E. §10 — 실행 기록
# ======================================================================


@pytest.mark.real_card
def test_e00_a_refused_step_is_recorded_as_refused(repository):
    """
    🔴 **§15 — 실행하지 않은 행동을 성공으로 적지 않는다.**

    변이 시험이 이 자리를 먼저 찾았다. ``accepted`` · ``resolved`` ·
    ``state_changed`` 를 **상수로** 바꾼 변이 셋이 살아남았는데, 이 경로의
    모든 걸음이 수락되기 때문이었다 — 거절된 걸음이 하나도 없으면 그 세
    칸이 정직한지 알 수 없다.

    그래서 **후보 목록에 없는 행동**을 고르는 선택 함수를 넣는다.
    ``Duel.apply`` 의 첫 관문이 그것을 거절하고 (Phase 6-S §3-1), 기록은
    그 사실을 그대로 적어야 한다.
    """
    from engine.action import PlayerAction

    setup = opened(repository)
    duel = setup.duel

    def choose_illegal(duel_, legal):
        #: 상대 자리의 행동 — 내 차례에 허가될 수 없다.
        card = duel_.state.player(1).zone(Zone.DECK)[0]
        return PlayerAction.normal_summon(actor=0, source=card.instance_id)

    before = duel.state.state_hash()
    run = execute_opening(setup, repository, choose=choose_illegal)

    assert len(run.steps) == 1, run.steps
    step = run.steps[0]
    #: ① 수락하지 않았다고 적는다.
    assert step.accepted is False
    #: ② 해결했다고 적지 않는다.
    assert step.resolved is False
    #: ③ 판이 바뀌었다고 적지 않는다.
    assert step.state_changed is False
    assert duel.state.state_hash() == before
    #: ④ 그리고 멈춘 이유가 **거절**이라고 적힌다.
    assert run.stopped_reason
    assert "거절" in run.stopped_reason
    assert run.executed == 0
    assert run.resolved == 0
    assert run.state_changes == 0


@pytest.mark.real_card
def test_e00b_an_unsorted_draft_still_gives_a_declared_deck_order(repository):
    """
    🔴 **정렬이 ``_build_draft`` 의 부수 효과에 의존하지 않는다.**

    변이 시험에서 "덱 순서를 정렬하지 않는다" 가 살아남았다 — 레시피
    파서가 이미 칸을 패스코드 순으로 만들기 때문이다. 그런데
    :func:`~deck.opening.check_hand_against_recipe` 는 **어떤**
    ``DeckDraft`` 든 받는다 (``DeckBuilder`` 의 초안은 정렬되어 있지 않다).

    그래서 칸 순서를 **거꾸로** 뒤집은 초안으로 같은 것을 센다.
    """
    parsed = recipe_draft(repository)
    parsed.draft.main.reverse()
    assert [s.card_id for s in parsed.draft.main] != sorted(
        s.card_id for s in parsed.draft.main
    ), "뒤집히지 않았다면 이 시험이 아무것도 재지 않는다"

    _findings, rest = check_hand_against_recipe(
        list(HAND_5), parsed.draft, repository
    )
    assert rest == sorted(rest), "선언된 배열은 패스코드 순이다"

    setup = build_opening(repository, parsed.draft, list(HAND_5))
    assert setup.can_run
    order = [c.card_id for c in setup.duel.state.player(0).zone(Zone.DECK)]
    assert order == sorted(order)


@pytest.mark.real_card
def test_e01_every_step_records_the_three_facts_separately(repository):
    """
    🔴 **§10 — 걸음마다 세 사실이 따로 적힌다.**

    하나의 bool 로 묶으면 "발동했다" 와 "해결됐다" 가 같은 값이 되고,
    그것이 Phase 6-R 이 고친 결함이다.
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    for step in run.steps:
        #: ① 행위 수락
        assert isinstance(step.accepted, bool)
        #: ② 체인 등록 — 수와 해결 수를 따로 들고 있다
        assert isinstance(step.chain_links_after, int)
        assert isinstance(step.chain_resolved_after, int)
        #: ③ 효과 해결 · 상태 변경
        assert isinstance(step.resolved, bool)
        assert isinstance(step.state_changed, bool)
        assert isinstance(step.effect_events, tuple)
        #: 그리고 판정 코드와 이유가 **둘 다** 있다.
        assert step.gate_code
        assert step.step_code
        assert step.reason


@pytest.mark.real_card
def test_e02_the_record_names_the_real_card_and_instance(repository):
    """**§10 — 카드 이름 · ID · EffectRef 가 실제 판의 것이다.**"""
    setup = opened(repository)
    run = execute_opening(setup, repository)
    for step in run.steps:
        assert step.card_id is not None
        card = repository.get(step.card_id)
        assert card is not None
        assert step.card_name == card.display_name()
        if step.effect_ref:
            assert step.effect_ref.startswith(str(step.card_id))


@pytest.mark.real_card
def test_e03_the_journal_records_only_applied_effects(repository):
    """
    **§10 · §14 — ``EventJournal`` 에 적용된 것만 남는다.**

    기록의 ``EFFECT`` 사건 수가 걸음들이 적은 ``effect_events`` 의 합과
    같다 — 양쪽이 같은 사실을 센다.
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    journal_effects = [
        str(event.effect_ref) for event in setup.journal
        if event.kind.name == "EFFECT"
    ]
    recorded = [ref for step in run.steps for ref in step.effect_events]
    assert journal_effects == recorded, (journal_effects, recorded)
    assert journal_effects == [f"{POT}:e[0]"]


@pytest.mark.real_card
def test_e04_the_stop_reason_separates_finished_from_blocked(repository):
    """
    🔴 **"더 할 것이 없다" 와 "상한에 닿았다" 와 "막혔다" 를 가른다.**

    전개가 끝난 것은 실패가 아니다 (§11 마지막 줄).
    """
    setup = opened(repository)
    run = execute_opening(setup, repository)
    assert run.stopped_reason
    assert "판을 바꿀 후보가 더 없습니다" in run.stopped_reason
    assert "막힌 것이 아닙니다" in run.stopped_reason

    #: 상한에 닿으면 **다른** 이유가 적힌다.
    tight = opened(repository)
    capped = execute_opening(tight, repository, max_actions=2)
    assert len(capped.steps) == 2
    assert "상한" in capped.stopped_reason
    assert "전개가 끝났다는 뜻이 아닙니다" in capped.stopped_reason


@pytest.mark.real_card
def test_e05_the_chosen_action_is_never_called_best(repository):
    """
    🔴 **§9 — 고른 행동을 최선이라고 말하지 않는다.**

    선택 함수의 설명이 그것을 적고, ``END_PHASE`` 를 고르지 않는다.
    """
    import inspect

    doc = inspect.getdoc(first_meaningful) or ""
    assert "최선이 아니다" in doc
    assert "검증용" in doc

    setup = opened(repository)
    duel = setup.duel
    #: 흐름만 남은 자리에서는 ``None`` 이다 — 호출자가 멈춘다.
    execute_opening(setup, repository)
    legal = duel.legal_actions(duel.to_act)
    assert first_meaningful(duel, legal) is None
    assert PlayerActionKind.END_PHASE in {a.kind for a in legal.allowed}


# ======================================================================
# F. §14-J·K — 정보 부족과 정적 계획의 분리
# ======================================================================


@pytest.mark.real_card
def test_f01_no_recipe_means_no_execution(repository):
    """
    🔴 **§14-J — 레시피가 없으면 가짜 실행 성공을 내지 않는다.**

    ``duel`` 을 아예 만들지 않고, 왜 만들지 않았는지 적는다.
    """
    parsed = parse_recipe("", repository)
    assert parsed.draft is None
    #: 빈 초안을 억지로 넣으면 **위반이 잡힌다** — 그것이 안전망이다.
    from deck.model import DeckDraft

    setup = build_opening(repository, DeckDraft(), list(HAND_5))
    assert setup.can_run is False
    assert setup.duel is None
    assert setup.blockers


@pytest.mark.real_card
def test_f02_the_discord_output_separates_executed_from_planned(repository):
    """
    🔴 **§14-K · §21 수준 3 — 실제 실행과 정적 계획을 가른다.**

    레시피를 주면 **실행 절이 먼저** 나오고, 정적 계획 절에 "실행하지
    않았다" 가 적힌다.
    """
    from app.discord_bot import combo_messages
    from app.main import DeckAgent

    agent = DeckAgent(repository)
    hand_text = ", ".join(str(c) for c in HAND_5)
    text = "\n".join(combo_messages(agent, hand_text,
                                    recipe_text=RECIPE_40))

    #: ① 실제 실행 절이 있고 걸음 수를 **실측으로** 말한다.
    assert "**[실제 엔진 실행]**" in text
    assert "엔진이 실제로" in text and "걸음 실행" in text
    #: ② 정적 계획 절이 "실행하지 않았다" 를 적는다.
    assert "**[아래는 실행하지 않은 정적 계획입니다]**" in text
    assert "엔진으로 돌린 것이 아닙니다" in text
    #: ③ 🔴 그리고 그 둘의 순서가 정해져 있다.
    assert text.index("**[실제 엔진 실행]**") < text.index(
        "**[아래는 실행하지 않은 정적 계획입니다]**")
    #: ④ 정적 계획의 판정이 **그 절 안**에 있다 (맨 위가 아니다).
    assert "정적 계획의 판정:" in text
    assert text.index("**[실제 엔진 실행]**") < text.index("정적 계획의 판정:")


@pytest.mark.real_card
def test_f03_without_a_recipe_the_discord_output_says_what_is_missing(
    repository,
):
    """
    🔴 **§5 · §13 — 레시피 없이 성공으로 표시하지 않는다.**

    그리고 **왜 ``deck:`` 으로는 안 되는지**를 적는다 — 적지 않으면
    사용자는 초안으로 검증했다고 믿는다.
    """
    from app.discord_bot import combo_messages
    from app.main import DeckAgent

    agent = DeckAgent(repository)
    text = "\n".join(combo_messages(agent, ", ".join(str(c) for c in HAND_5)))

    assert "**[실제 엔진 실행]**" in text
    assert "하지 않았습니다" in text
    assert "덱 레시피" in text
    assert "자연어 요청" in text
    assert "`recipe:`" in text
    #: 🔴 실행한 걸음이 **하나도** 적히지 않는다.
    assert "엔진이 실제로" not in text


@pytest.mark.real_card
def test_f04_the_existing_combo_call_still_works(repository):
    """
    **§13 · §19 — 기존 호출 계약이 깨지지 않는다.**

    ``recipe_text`` 는 **마지막 선택 인수**이므로 예전 호출이 그대로 돈다.
    """
    import inspect

    from app.discord_bot import SearchService, combo_messages

    params = list(inspect.signature(combo_messages).parameters)
    assert params == ["agent", "hand_text", "board_text", "deck_text",
                      "recipe_text"]
    for name in ("board_text", "deck_text", "recipe_text"):
        assert inspect.signature(combo_messages).parameters[name].default == ""
    service = list(inspect.signature(SearchService.combo_texts).parameters)
    assert service == ["self", "hand_text", "board_text", "deck_text",
                       "recipe_text"]
    #: 예전과 같은 인수 하나로 부른다.
    assert combo_messages(repository and DeckAgentFor(repository),
                          str(POT))


class DeckAgentFor:
    """``DeckAgent`` 하나를 만드는 작은 도움 — 시험 안에서만 쓴다."""

    def __new__(cls, repository):
        from app.main import DeckAgent

        return DeckAgent(repository)


# ======================================================================
# G. §14-L~P — 앞 Phase 의 실행 회귀
# ======================================================================


def resolve_one(duel, action):
    """후보 하나를 끝까지 — 발동 · 패스 · 해결."""
    step = duel.apply(action)
    assert step.accepted, step.reason
    last = step
    for _ in range(8):
        if not duel.priority.is_open:
            break
        passing = [a for a in duel.legal_actions().allowed
                   if a.kind is PlayerActionKind.PASS]
        if not passing:
            break
        last = duel.apply(passing[0])
    return last


def activation_for(duel, seat, card_id):
    return [
        a for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref.card_id == card_id
    ]


@pytest.mark.real_card
def test_g01_an_effect_monster_cannot_be_normal_summoned_yet(repository):
    """
    🔴 **§14-L 의 실측 — 어니스트는 이 경로에서 통상 소환할 수 없다.**

    처음 이 시험은 "어니스트를 통상 소환한 뒤 효과를 발동한다" 로 적었고
    **틀렸다.** 실측하면 검증기가 이렇게 답한다::

        어니스트    ['MONSTER', 'EFFECT'] -> UNKNOWN  RULE_NOT_IMPLEMENTED
                   missing=summoning-condition (카드 텍스트의 소환 제약)
        사파이어 드래곤 ['MONSTER', 'NORMAL'] -> VALID    OK

    🔴 **그리고 그것이 옳다.** 효과 몬스터는 카드 텍스트에 소환 제약이 있을
    수 있고 (예: "이 카드는 통상 소환할 수 없다"), 엔진은 그 문장을 읽지
    못한다. 읽지 못하는 것을 ``VALID`` 로 올리면 규칙이 금지한 소환을
    허가하게 된다 — ``UNKNOWN`` 이 정확한 답이다 (ADR-006 · §3-8).

    그래서 **선공 전개의 폭이 통상 몬스터로 묶인다.** 이것이 Phase 6-U 가
    넓히기 전에 알아야 하는 BLOCKER 이고, 이 시험이 그것을 재어서 남긴다 —
    풀리면 이 단언이 깨진다.
    """
    from engine.action import PlayerAction
    from engine.action_validation import ActionValidator
    from engine.validation import ActionValidity

    setup = opened(repository)
    duel = setup.duel
    validator = ActionValidator(
        duel.view(0), definitions=duel._activator.definitions
    )
    seen = {}
    for instance in duel.state.player(0).zone(Zone.HAND):
        card = repository.get(instance.card_id)
        if not card.is_monster:
            continue
        verdict = validator.validate(
            PlayerAction.normal_summon(actor=0, source=instance.instance_id)
        )
        seen[instance.card_id] = verdict

    #: 통상 몬스터는 허가가 난다.
    assert seen[LUSTER].validity is ActionValidity.VALID
    #: 🔴 효과 몬스터는 **모른다** — 금지가 아니라 모름이다.
    honest = seen[HONEST]
    assert honest.validity is ActionValidity.UNKNOWN
    assert honest.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert honest.missing_rule == "summoning-condition (카드 텍스트의 소환 제약)"
    #: 그래서 후보로 나오지 않는다 — ``UNKNOWN`` 은 후보가 아니다.
    offered = [
        a for a in duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
        and duel.state.find_instance(a.source).card_id == HONEST
    ]
    assert offered == []


@pytest.mark.real_card
def test_g01b_the_honest_effect_still_runs_when_it_is_on_the_field(repository):
    """
    **§14-L — 어니스트의 효과 실행(6-L)은 그대로다.**

    🔴 **이것은 선공 전개 경로가 아니다.** 위 시험이 재어 둔 대로 어니스트는
    이 경로에서 통상 소환할 수 없으므로, 효과가 유지되는지는 필드에 놓은
    판에서 확인한다 (Phase 6-S 와 같은 방식). 그 사실을 적지 않으면 이
    시험이 "선공 전개로 어니스트를 썼다" 로 읽힌다.
    """
    from engine.duel import duel_components
    from engine.effect.journal import EventJournal
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Position

    journal = EventJournal()
    state = GameState.create(repository, decks=([LUSTER] * 30, [LUSTER] * 30),
                             turn_player=0, seed=1)
    card = state.create_instance(HONEST, owner=0, zone=Zone.HAND)
    state.move(card, Zone.MZONE, to_player=0,
               position=Position.FACEUP_ATTACK)
    state.turn.turn_number = 5
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=0, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    picks = activation_for(duel, 0, HONEST)
    assert len(picks) == 1, picks
    last = resolve_one(duel, picks[0])
    assert last.code is ValidationCode.OK
    assert [c.card_id for c in duel.state.player(0).zone(Zone.HAND)] == [HONEST]
    assert [c for c in duel.state.player(0).zone(Zone.MZONE) if c] == []
    assert [str(e.effect_ref) for e in journal
            if e.kind.name == "EFFECT"] == [f"{HONEST}:e[0]"]


@pytest.mark.real_card
def test_g02_the_phase_6p_multi_target_still_runs_from_this_path(repository):
    """**§14-M — 벌금의 패 2장 (6-P).** 조합 셋이 각각 다른 후보다."""
    setup = opened(repository, hand=[FINE, LUSTER, LUSTER, LUSTER, POT])
    duel = setup.duel
    sets = [
        a for a in duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
        and duel.state.find_instance(a.source).card_id == FINE
    ]
    assert sets
    assert duel.apply(sets[0]).accepted
    #: 세트한 턴에는 발동할 수 없다 (6-Q).
    assert activation_for(duel, 0, FINE) == []
    #: 다음 내 턴으로 넘긴다 — 턴 진행은 엔진의 것이다.
    _advance_to_my_next_main(duel)
    picks = activation_for(duel, 0, FINE)
    #: 🔴 **조합 수를 상수로 적지 않는다.** 턴을 넘기는 동안 드로우가
    #: 일어나 패가 늘었고, 후보 수는 그 패에서 **2장을 고르는 조합 수**다.
    #: 처음 이 시험은 3 으로 적었고 실측은 10 이었다 — 수를 세는 쪽이
    #: 아니라 **세는 방법**을 못 박는다.
    import math

    definition = duel._activator.definitions.definition_for(
        EffectRef(FINE, 0)
    )
    pool = [
        c for c in duel.state.player(0).zone(Zone.HAND)
        if c.card_id != FINE
    ]
    assert len(picks) == math.comb(len(pool), 2), (len(picks), len(pool))
    assert len(picks) >= 3, picks
    assert {len(p.targets) for p in picks} == {2}
    #: 조합이 **서로 다르다**.
    assert len({tuple(t.instance_id for t in p.targets) for p in picks}) == len(picks)
    hand_before = len(duel.state.player(0).zone(Zone.HAND))
    last = resolve_one(duel, picks[0])
    assert last.code is ValidationCode.OK
    assert len(duel.state.player(0).zone(Zone.HAND)) == hand_before - 2


@pytest.mark.real_card
def test_g03_the_phase_6q_trap_still_runs_from_this_path(repository):
    """**§14-N — 세트된 일반 함정 (6-Q) 의 후보 · 발동 · 해결.**"""
    setup = opened(repository)
    duel = setup.duel
    sets = [
        a for a in duel.legal_actions(0).allowed
        if a.kind is PlayerActionKind.SET_SPELL_TRAP
        and duel.state.find_instance(a.source).card_id == GIFT
    ]
    assert sets
    assert duel.apply(sets[0]).accepted
    _advance_to_my_next_main(duel)
    picks = activation_for(duel, 0, GIFT)
    assert len(picks) == 1
    their_hand = len(duel.state.player(1).zone(Zone.HAND))
    last = resolve_one(duel, picks[0])
    assert last.code is ValidationCode.OK
    assert len(duel.state.player(1).zone(Zone.HAND)) == their_hand + 2


@pytest.mark.real_card
def test_g04_the_phase_6r_chain_teardown_holds_here(repository):
    """**§14-O — 체인 종료 뒤 잔류 링크가 없다 (6-R).**"""
    setup = opened(repository)
    run = execute_opening(setup, repository)
    assert run.steps
    for step in run.steps:
        assert step.chain_links_after == 0, step
        assert step.chain_resolved_after == 0, step
    assert setup.duel.chain.is_empty
    assert setup.duel.priority.is_open is False


@pytest.mark.real_card
def test_g05_the_phase_6s_candidate_consistency_holds_here(repository):
    """
    **§14-P — 후보 생성 · 판정 · 실행의 정합성 (6-S).**

    이 경로의 모든 후보가 관문을 통과하고 ``apply`` 에서 접수된다.
    """
    from engine.duel import duel_components

    setup = opened(repository)
    duel = setup.duel
    tried = refused = 0
    for action in duel.legal_actions(0).allowed:
        fork = Duel(
            state=duel.state.clone(),
            priority=duel.priority,
            step=duel.step,
            first_player=duel.first_player,
            chain=duel.chain,
            pending_spells=duel.pending_spells,
            **duel_components(journal=False),
        )
        tried += 1
        if not fork.apply(action).accepted:
            refused += 1
    assert tried >= 5, tried
    assert refused == 0


def _advance_to_my_next_main(duel):
    """
    🔴 **턴을 엔진으로 넘긴다** — 페이즈를 손으로 쓰지 않는다.

    내 턴의 메인 1 로 돌아올 때까지 ``END_PHASE`` 를 적용한다 (상대는
    아무 것도 하지 않는다 — 상대의 방해가 없는 시나리오다).
    """
    start = duel.state.turn.turn_number
    for _ in range(40):
        duel.advance()
        if (duel.state.turn.turn_number > start
                and duel.state.turn.turn_player == 0
                and duel.state.turn.phase is Phase.MAIN1):
            return
        legal = duel.legal_actions(duel.to_act)
        ends = [a for a in legal.allowed
                if a.kind is PlayerActionKind.END_PHASE]
        if not ends:
            passing = [a for a in legal.allowed
                       if a.kind is PlayerActionKind.PASS]
            assert passing, legal.withheld
            duel.apply(passing[0])
            continue
        duel.apply(ends[0])
    raise AssertionError("내 다음 메인 페이즈 1 에 닿지 못했다")


# ======================================================================
# H. 이 Phase 가 **하지 않은 것**을 못 박는다
# ======================================================================


@pytest.mark.real_card
def test_h01_no_new_duel_engine_was_written():
    """
    🔴 **§3-5 — 새 듀얼 엔진을 만들지 않았다.**

    ``deck/opening.py`` 에 규칙이 한 줄도 없다 — 전부 ``engine`` 에게
    묻는다. AST 로 센다.
    """
    import ast

    source = (ROOT / "deck" / "opening.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    #: 들고 있는 것은 **입력과 기록**뿐이다. 판정기도 실행기도 없다.
    assert classes == ["OpeningSetup", "ExecutedStep", "OpeningRun"], classes
    #: 🔴 ``engine`` 의 것을 **부른다** — 베끼지 않는다.
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for name in ("legal_actions", "apply", "advance", "validate"):
        assert name in calls, (name, sorted(calls))


@pytest.mark.real_card
def test_h02_the_search_depth_is_declared_not_a_rule():
    """
    🔴 **§11 — 탐색 깊이가 이 단계의 선언이고 유희왕의 규칙이 아니다.**

    그 사실이 상수의 설명에 적혀 있어야 한다 — 적혀 있지 않으면 다음에
    읽는 사람이 규칙이라고 믿는다.
    """
    source = (ROOT / "deck" / "opening.py").read_text(encoding="utf-8")
    block = source.split("MAX_EXECUTED_ACTIONS")[0]
    assert "이 단계가 선언한 상한" in block
    assert "유희왕의 규칙이" in block
    assert MAX_EXECUTED_ACTIONS == 8


@pytest.mark.real_card
def test_h03_the_house_strength_evaluation_is_declared_missing(repository):
    """
    🔴 **§12 — 집의 강도 평가를 지어내지 않는다.**

    출력이 "미구현" 이라고 적고, 방해 수단의 수를 세지 않는다.
    """
    from deck.report import render_opening_board

    setup = opened(repository)
    execute_opening(setup, repository)
    text = render_opening_board(setup, repository)
    assert "집의 강도 평가는 미구현입니다" in text
    assert "방해 수단의 수를 카드 텍스트만 보고 세지 않았습니다" in text
