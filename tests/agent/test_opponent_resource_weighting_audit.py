r"""
Phase 3-F-3 — 상대 자원 **가중치 결정 가능성** 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다.

Phase 3-F-2 가 feature 를 만들었고, 이 Phase 는 그것에 weight 를 붙여 Search 가
소비하게 할지 결정한다. 조사 결과 **지금은 붙일 수 없다** — 붙여도 순위가 바뀌지
않고, 바뀌지 않는 까닭이 가중치가 아니라 **행동 공간**에 있다.

구조적 사슬 (전부 실측)
-----------------------
1. 등재 효과 16개 중 **상대에게 카드를 주는 것은 하나**다 — ``5915629``
   (욕망의 선물, ``DrawOperation(who=opponent, count=2)``).
2. 그 카드는 **함정**이다.
3. 함정은 live 발동 관문의 **범위 밖**이다 — ``trap-activation-timing``
   (공식 스크립트의 ``SetCode(EVENT_*)`` 가 ``EffectDefinition`` 에 없어서
   유발 함정과 유발 조건 없는 함정을 구분할 수 없다, Phase 3-E-44).
4. 그래서 **상대에게 자원을 주는 행동은 후보가 될 수 없다.**
5. 그래서 한 결정 안에서 상대 자원 결과가 **언제나 같다** (실측 273/273 ·
   510/510).
6. 그래서 어떤 weight 도 그 결정에서 **상수 오프셋**이고, 순위를 바꾸지 못한다.

이 파일이 지키는 것
-------------------
위 1–6 을 숫자로 고정한다 (``test_01``–``test_08``). 그리고 §3 이 요구한
double-counting 추적 결과 (``test_09``–``test_11``) 와, weight 를 붙였다면
어떻게 되었을지의 **산술** (``test_12``–``test_13``) 을 적는다.

**가중치를 붙이지 않았다.** 점수 · 항 · Search 가 그대로다
(``test_14``–``test_16``).
"""

import dataclasses
import pathlib

import pytest

from agent.evaluation import (
    DECK_CARD_IN_LP,
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    OpponentResourceDelta,
    OpponentResources,
    StateEvaluator,
    StateValue,
    Terminal,
)
from agent.search import SearchCandidate
from engine.action import PlayerAction
from engine.action_validation import TRAP_TRIGGER_MISSING, ActionValidator
from engine.duel import Duel
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: 상대에게 카드를 주는 **유일한** 등재 효과. 이름을 production 에 넣지 않는다 —
#: 이 파일은 시험이고, 그 사실을 **고정**하기 위해 passcode 를 쓴다.
GIFT_OF_GREED = 5915629
POT_OF_GREED = 55144522
LUSTER_DRAGON = 11091375


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


@pytest.fixture
def evaluator() -> StateEvaluator:
    return StateEvaluator()


def start(repository) -> GameState:
    deck = [LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    state.draw(MINE, 5)
    state.draw(THEIRS, 5)
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    return state


def view_of(state: GameState, viewer: int = MINE) -> GameStateView:
    return GameStateView.from_state(state, viewer=viewer)


def terms_of(evaluator, state: GameState) -> dict:
    return dict(evaluator.evaluate(view_of(state)).terms)


# ======================================================================
# A. 왜 weight 가 아무 일도 하지 못하는가 — 구조적 사슬
# ======================================================================


def test_01_exactly_one_registered_effect_gives_the_opponent_cards():
    """
    **등재 효과 16개 중 상대에게 카드를 주는 것은 하나다.**

    ``DrawOperation`` 의 ``who`` 가 상대를 가리키는 효과를 센다 — 카드 이름이
    아니라 **연산**으로 찾는다.
    """
    giving = []
    for entry in EFFECT_LIBRARY:
        for operation in entry.definition.operations:
            who = getattr(operation, "who", None)
            if type(operation).__name__ != "DrawOperation":
                continue
            if getattr(who, "value", str(who)) == "opponent":
                giving.append(entry.definition.effect_ref.card_id)

    assert len(EFFECT_LIBRARY) == 16
    assert giving == [GIFT_OF_GREED]


@pytest.mark.real_card
def test_02_that_one_effect_is_a_trap(repository):
    """그 하나가 **함정**이다 — 공식 DB 가 말한다. 추측하지 않는다."""
    card = repository.get(GIFT_OF_GREED)
    assert "TRAP" in set(card.type_names)
    #: 비교군 — 욕망의 항아리는 마법이고, 그래서 후보가 된다 (``test_04``).
    assert "SPELL" in set(repository.get(POT_OF_GREED).type_names)


@pytest.mark.real_card
def test_03_a_trap_is_out_of_the_live_activation_gate(repository):
    """
    **함정은 live 관문의 범위 밖이다.** 손에 쥐고 있어도 관문이
    ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED`` 를 낸다.

    "규칙이 금지한다" 가 아니라 **"우리가 모른다"** 다 — 엔진이 유발 함정과
    유발 조건 없는 함정을 구분할 수 없기 때문이다 (Phase 3-E-44).
    """
    assert "trap-activation-timing" in TRAP_TRIGGER_MISSING
    assert "SetCode(EVENT_*)" in TRAP_TRIGGER_MISSING

    state = start(repository)
    gift = state.create_instance(GIFT_OF_GREED, owner=MINE, zone=Zone.HAND)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=state.turn.phase),
    )
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=gift.instance_id,
        effect_ref=EffectRef(GIFT_OF_GREED, 0),
    )
    validator = ActionValidator(duel.view(MINE))
    gate = duel._activation_gate(action, validator=validator, selections=())

    from engine.validation import ActionValidity, ValidationCode

    assert gate.validity is ActionValidity.UNKNOWN
    assert gate.code is ValidationCode.RULE_NOT_IMPLEMENTED


@pytest.mark.real_card
def test_04_so_it_never_enters_the_candidate_list(repository):
    """
    **그래서 후보가 되지 않는다.** 같은 판에서 욕망의 항아리(마법)는 후보가
    되고 욕망의 선물(함정)은 되지 않는다 — 둘 다 손에 있다.
    """
    state = start(repository)
    state.create_instance(GIFT_OF_GREED, owner=MINE, zone=Zone.HAND)
    state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=state.turn.phase),
    )
    refs = {
        action.effect_ref
        for action in duel.legal_actions(MINE).allowed
        if action.effect_ref is not None
    }
    assert EffectRef(POT_OF_GREED, 0) in refs
    assert EffectRef(GIFT_OF_GREED, 0) not in refs


@pytest.mark.real_card
def test_05_no_candidate_in_a_real_board_changes_the_opponent_hand(repository):
    """
    **한 결정 안의 모든 후보가 상대 패를 같은 수로 남긴다.**

    그래서 상대 자원에 어떤 값을 붙여도 그 결정의 후보들에 **같은 양**이
    더해진다 — 순위가 움직일 수 없다 (``test_06`` 이 그 산술을 고정한다).
    """
    from agent.simulation import SimulationStatus, Simulator

    state = start(repository)
    state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=state.turn.phase),
    )
    view = duel.view(MINE)
    simulator = Simulator(duel)

    outcomes = set()
    scored = 0
    for action in duel.legal_actions(MINE).allowed:
        result = simulator.simulate(action, viewer=MINE)
        if result.status is not SimulationStatus.SUPPORTED:
            continue
        scored += 1
        delta = OpponentResourceDelta.between(view, result.future)
        outcomes.add((delta.drawn_from_deck, delta.after.hand))

    assert scored >= 2, "후보가 둘 이상이어야 비교가 뜻을 갖는다"
    assert outcomes == {(0, 5)}, outcomes


def test_06_a_constant_offset_cannot_change_the_candidate_order():
    """
    **상수 오프셋은 순위를 바꾸지 못한다.** ``ordering_key`` 가
    ``(0, -terminal, -heuristic, canonical)`` 이므로 모든 후보의
    ``heuristic`` 에 같은 값을 더하면 순서가 그대로다.

    ``test_05`` 가 "한 결정 안에서 상대 자원이 같다" 를 보였으므로, 상대 자원
    weight 는 **정확히 이 상수 오프셋**이다.
    """
    action = PlayerAction.end_phase(actor=MINE)

    def order(offset: int) -> list[int]:
        candidates = [
            (
                SearchCandidate(
                    action=action,
                    status=None,
                    value=StateValue(
                        terminal=Terminal.ONGOING, heuristic=base + offset
                    ),
                ),
                index,
            )
            for index, base in enumerate((100, 300, 200))
        ]
        return [
            index
            for _, index in sorted(
                candidates, key=lambda pair: pair[0].value.ordering_key(), reverse=True
            )
        ]

    assert order(0) == order(-900) == order(+5000) == [1, 2, 0]


@pytest.mark.real_card
def test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources(repository):
    """
    **실제 듀얼을 돌려 확인한다.** 결정마다 후보들의 상대 자원 결과를 모아
    보면 **언제나 한 가지**다.

    .. note::
       **이 테스트는 원래 문자열 하나만 단정했다** — 아무것도 재지 않는
       장식이었다. 실제 듀얼을 돌려 결정마다 세는 쪽으로 고쳤다.

    보고서의 큰 실측(16판 273결정 · 욕망의 선물 덱 12판 510결정, 둘 다 변동
    **0**) 과 같은 방법이고, 여기서는 회귀로 쓸 수 있게 짧게 돌린다.
    """
    from agent import rule_based_policy
    from agent.runner import DuelRunner
    from agent.search import search_policy
    from agent.simulation import SimulationStatus

    seen: list[int] = []

    class Probe:
        def __init__(self, duel):
            self.inner = search_policy(duel)
            self.name = "probe"

        def decide(self, view, legal):
            if len(legal.allowed) >= 2:
                outcomes = set()
                for action in legal.allowed:
                    result = self.inner.simulator.simulate(action, viewer=legal.seat)
                    if result.status is not SimulationStatus.SUPPORTED:
                        continue
                    delta = OpponentResourceDelta.between(view, result.future)
                    outcomes.add((delta.drawn_from_deck, delta.after.hand))
                if len(outcomes) >= 1:
                    seen.append(len(outcomes))
            return self.inner.decide(view, legal)

    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GIFT_OF_GREED] * 4
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=3)
    DuelRunner(duel, (Probe(duel), rule_based_policy())).run()

    assert seen, "비교할 결정이 하나도 없었다면 이 테스트는 아무것도 재지 않는다"
    #: **모든 결정에서 상대 자원 결과가 한 가지**였다.
    assert set(seen) == {1}, seen


def test_08_the_blocker_is_the_activation_layer_not_the_weight():
    """
    **막고 있는 것이 가중치가 아니다.** 상대 자원을 주는 행동이 후보가 되려면
    함정의 유발 조건을 구분할 수 있어야 하고, 그것은 ``EffectDefinition`` 에
    ``SetCode(EVENT_*)`` 가 들어오는 일이다 — 이 Phase 의 범위 밖이다 (§15 가
    ``LegalActions`` · 발동 경로 수정을 금지한다).
    """
    #: 그 사실이 production 에 **이름 붙은 "없는 규칙"** 으로 남아 있다.
    #: 상수는 여러 줄로 이어 붙여져 있으므로 **조각으로** 확인한다 (통째로
    #: 찾으면 줄바꿈 때문에 걸리지 않는다 — 처음에 그렇게 적어 실패했다).
    validation = source_of("engine/action_validation.py")
    assert "TRAP_TRIGGER_MISSING" in validation
    assert "trap-activation-timing" in validation
    assert "SetCode(EVENT_*)" in validation
    #: 그리고 그 상수가 실제로 함정 발동을 범위 밖으로 보내는 자리에 쓰인다.
    assert "TRAP_TRIGGER_MISSING),)" in validation.replace("\n", "").replace(" ", "")


# ======================================================================
# B. §3 double-counting 추적
# ======================================================================


@pytest.mark.real_card
def test_09_an_opponent_draw_already_moves_the_deck_term(repository, evaluator):
    """
    **§3 의 핵심.** 상대가 1장 뽑으면 기존 ``deck`` 항이 **이미 +300 움직인다** —
    그리고 그 방향이 "나에게 좋다" 다.

    상대 패가 늘어난 것을 세는 항은 **하나도 없다.** 그래서 새 항을 더해도
    "상대 패 +1" 을 두 번 세는 일은 **없고**, 대신 기존 ``deck`` 항과
    **같은 사건의 다른 결과**를 각자 세게 된다.

    한 장당 합계는 ``+300 − W`` 다.
    """
    state = start(repository)
    before = terms_of(evaluator, state)
    before_resources = OpponentResources.of(view_of(state))

    state.draw(THEIRS, 1)
    after = terms_of(evaluator, state)
    after_resources = OpponentResources.of(view_of(state))

    #: 움직인 항은 ``deck`` **하나**다.
    moved = {name: after[name] - before[name] for name in before}
    assert moved == {
        "lp": 0,
        "atk": 0,
        "monsters": 0,
        "spells": 0,
        "deck": DECK_CARD_IN_LP,
        "hand": 0,
    }
    #: 상대 패는 분명히 늘었는데 **어느 항도 그것을 세지 않았다.**
    assert after_resources.hand - before_resources.hand == 1
    assert moved["hand"] == 0  # ``hand`` 항은 내 패만 센다


@pytest.mark.real_card
def test_10_an_opponent_monster_death_is_already_fully_scored(repository, evaluator):
    """
    **진짜 double-counting 위험은 여기다.**

    내 공격으로 상대 몬스터가 죽으면 ``atk`` 와 ``monsters`` 가 **이미** 센다
    (+1900 · +500). 그러니 "상대 묘지가 늘었다" 를 벌점/가점으로 더하면
    **같은 사건을 두 번** 세게 된다.

    ``OpponentResources.total`` 은 이 사건에서 **변하지 않는다** (몬스터 →
    묘지로 자리만 옮겼다) — 그래서 ``total`` 을 쓰는 항이라면 안전하지만,
    ``grave`` 하나만 보는 항이라면 중복이다.
    """
    state = start(repository)
    monster = next(
        card for card in state.player(THEIRS).hand if card.card_id == LUSTER_DRAGON
    )
    state.move(
        monster, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK
    )
    before = terms_of(evaluator, state)
    before_resources = OpponentResources.of(view_of(state))

    dead = next(card for card in state.player(THEIRS).monster_zone if card is not None)
    state.move(dead, Zone.GRAVE, to_player=THEIRS)
    after = terms_of(evaluator, state)
    after_resources = OpponentResources.of(view_of(state))

    #: 기존 두 항이 이미 전부 세었다.
    #:
    #: .. note::
    #:    **상수와만 견주면 아무것도 재지 않는다** (3-F-3 의 고의 위반 6 이
    #:    찾아냈다). ``MONSTER_IN_LP`` 를 0 으로 바꾸면 ``0 == 0`` 이 되어
    #:    통과했다. 그래서 **실제 숫자**도 함께 못박는다.
    assert MONSTER_IN_LP == 500
    assert after["monsters"] - before["monsters"] == MONSTER_IN_LP == 500
    assert after["atk"] - before["atk"] == 1900
    assert sum(after.values()) - sum(before.values()) == 2400

    #: 그런데 상대의 **총 장수는 그대로**다 — 자리만 옮겼다.
    assert before_resources.total == after_resources.total
    #: ``grave`` 만 보면 +1 이고, 그것이 중복의 모양이다.
    assert after_resources.grave - before_resources.grave == 1
    assert after_resources.monsters - before_resources.monsters == -1


@pytest.mark.real_card
def test_11_drawn_from_deck_does_not_fire_on_a_monster_death(repository):
    """
    ``drawn_from_deck`` 은 그 사건에 **반응하지 않는다** — 그래서 그 feature 를
    쓰는 한 ``test_10`` 의 중복은 생기지 않는다. 중복 위험은 ``grave`` 나
    ``total`` 을 직접 항으로 쓸 때 생긴다.
    """
    state = start(repository)
    monster = next(
        card for card in state.player(THEIRS).hand if card.card_id == LUSTER_DRAGON
    )
    state.move(
        monster, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK
    )
    before = view_of(state)
    dead = next(card for card in state.player(THEIRS).monster_zone if card is not None)
    state.move(dead, Zone.GRAVE, to_player=THEIRS)

    delta = OpponentResourceDelta.between(before, view_of(state))
    assert delta.drawn_from_deck == 0
    assert delta.gave_resource is False
    #: 다만 **모른다고 적는다** — 묘지가 늘어난 까닭을 장수로는 정할 수 없다.
    assert delta.fully_explained is False


# ======================================================================
# C. §9 benchmark — weight 를 붙였다면 어떻게 되었을까 (산술만)
# ======================================================================


@pytest.mark.real_card
def test_12_the_benchmark_gap_is_exactly_the_deck_term(repository, evaluator):
    """
    **§9 benchmark.** A(전개3 + 자원3) 와 B(전개3 + 자원0) 의 점수 차가
    **정확히 ``3 × DECK_CARD_IN_LP``** 다 — 전부 ``deck`` 항에서 온다.

    내 전개 쪽 항은 한 칸도 다르지 않다.
    """
    def staged(summons: int, given: int):
        state = start(repository)
        before = view_of(state)
        for _ in range(summons):
            card = next(
                c for c in state.player(MINE).hand if c.card_id == LUSTER_DRAGON
            )
            state.move(
                card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK
            )
        if given:
            state.draw(THEIRS, given)
        after = view_of(state)
        return (
            evaluator.evaluate(after),
            OpponentResourceDelta.between(before, after),
        )

    a_value, a_delta = staged(3, 3)
    b_value, b_delta = staged(3, 0)

    #: 내 쪽은 같다.
    for name in ("lp", "atk", "monsters", "spells", "hand"):
        assert dict(a_value.terms)[name] == dict(b_value.terms)[name], name

    gap = a_value.heuristic - b_value.heuristic
    assert gap == 3 * DECK_CARD_IN_LP == 900
    assert (a_delta.drawn_from_deck, b_delta.drawn_from_deck) == (3, 0)


def test_13_the_only_derivable_weight_makes_a_draw_neutral():
    """
    **유도되는 값은 하나뿐이고, 그 값은 "중립" 을 뜻한다.**

    한 장당 합계가 ``+300 − W`` 이므로:

    ====================  =========================================
    ``W < 300``            상대가 뽑아도 **여전히 나에게 이득**으로 읽힌다
    ``W = 300``            **중립** — 뽑기 자체가 점수를 움직이지 않는다
    ``W > 300``            "상대에게 주는 것은 나쁘다" 를 **단정**한다
    ====================  =========================================

    ``W = 300`` 은 ``DECK_CARD_IN_LP`` 그 자체이므로 **고르지 않고 유도된다.**
    그리고 §9 가 금지한 "무조건 나쁜 행동" 규칙을 만들지 않는 유일한 값이다.

    그래도 **붙이지 않았다** — 붙여도 순위가 바뀌지 않고 (``test_05`` ·
    ``test_06``), 그러면 그 값이 맞는지 **확인할 방법이 없다.**
    """
    gap, drawn = 900, 3
    neutral = gap // drawn
    assert neutral == DECK_CARD_IN_LP == 300
    assert gap - drawn * neutral == 0

    #: ``HAND_CARD_IN_LP`` 를 쓰면 중립이 되지 않는다 — 대칭은 근거가 아니다.
    assert HAND_CARD_IN_LP == 200
    assert gap - drawn * HAND_CARD_IN_LP == 300  # 여전히 이득으로 읽힌다

    #: 그리고 기존 설계가 상대 패에 값을 매기지 않기로 **적어 두었다.**
    assert "상대 패는" in source_of("agent/evaluation.py")
    assert "그 값을 매기려면 내용을 알아야 한다" in source_of("agent/evaluation.py")


# ======================================================================
# D. 아무것도 붙이지 않았다
# ======================================================================


def test_14_no_weight_was_added_and_the_terms_are_unchanged():
    """**가중치를 붙이지 않았다.** 다섯 상수와 항 여섯이 그대로다."""
    assert (DECK_CARD_IN_LP, HAND_CARD_IN_LP, MONSTER_IN_LP) == (300, 200, 500)

    evaluation = source_of("agent/evaluation.py")
    for absent in (
        "OPPONENT_RESOURCE_IN_LP",
        "OPPONENT_DRAW_IN_LP",
        "opponent_resource_penalty",
        "drawn_from_deck *",
    ):
        assert absent not in evaluation, absent


@pytest.mark.real_card
def test_15_the_score_types_and_the_search_path_are_untouched(repository, evaluator):
    """
    **점수 자료형과 Search 가 그대로다.** 네 칸 · 항 여섯 · 비교 하나.
    """
    assert len(dataclasses.fields(StateValue)) == 4
    assert len(dataclasses.fields(SearchCandidate)) == 4

    terms = terms_of(evaluator, start(repository))
    assert tuple(terms) == ("lp", "atk", "monsters", "spells", "deck", "hand")

    search = source_of("agent/search.py")
    for absent in ("OpponentResource", "opponent_resource", "drawn_from_deck"):
        assert absent not in search, absent
    assert "terminal, heuristic = self.value.ordering_key()" in search


@pytest.mark.real_card
def test_16_the_feature_is_still_pure_and_hidden_information_is_still_held(
    repository, evaluator
):
    """
    **3-F-2 의 경계가 그대로다.** 판을 바꾸지 않고 난수를 쓰지 않으며, 상대 덱
    구성이 점수에 닿지 않는다.
    """
    state = start(repository)
    before_hash, before_rng = state.state_hash(), state.rng.getstate()
    view = view_of(state)
    first = (evaluator.evaluate(view), OpponentResources.of(view))
    for _ in range(30):
        assert (evaluator.evaluate(view), OpponentResources.of(view)) == first
    assert state.state_hash() == before_hash
    assert state.rng.getstate() == before_rng

    #: clone 도 같다.
    cloned = view_of(state.clone())
    assert OpponentResources.of(cloned) == first[1]
    assert evaluator.evaluate(cloned) == first[0]

    #: 상대 덱 구성이 달라도 장수가 같으면 점수가 같다.
    other = GameState.create(
        repository,
        decks=(
            [LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5,
            [5053103] * 20 + [POT_OF_GREED] * 5,
        ),
        seed=1,
    )
    other.draw(MINE, 5)
    other.draw(THEIRS, 5)
    other.turn.turn_number = 2
    other.turn.turn_player = MINE
    other.turn.set_phase(Phase.MAIN1)
    assert evaluator.evaluate(view_of(other)).heuristic == first[0].heuristic
