r"""
Phase 3-F-1 — Evaluation Core 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다.

이 Phase 는 "AI 가 상태를 평가하는 Evaluation Core 를 만든다" 였는데, 조사해
보니 **그것이 이미 있다** — :mod:`agent.evaluation` (Phase 3-C, 661줄). 그래서
새 클래스를 만들지 않았다. 만들면 그것이 바로 중복 abstraction 이다.

이 파일은 **새 것을 더하지 않고** 다음 넷을 고정한다.

1. Phase 가 요구한 feature A–G 중 **무엇이 있고 무엇이 없는가**, 그리고 없는
   것의 **까닭이 가중치가 아니라 architecture** 라는 사실.
2. **§6 의 질문에 대한 답** — Evaluation Core 는 "내 필드가 강해졌다" 와
   "상대에게 자원을 제공했다" 를 **구분하지 못한다.** 추측이 아니라 실측이다
   (``test_08``–``test_10``).
3. **§7 의 확장성** — ``Evaluator.evaluate`` 에 context 인수가 **없다.**
   Opponent Model 을 붙이려면 Protocol 을 바꿔야 한다.
4. 이름이 비슷한 **두 abstraction 이 다른 것**이라는 사실 —
   ``agent.heuristic.Evaluation`` 은 **행동**을 채점하고
   ``agent.evaluation.StateValue`` 는 **상태**를 채점한다.

이미 있는 것은 다시 적지 않는다. 순수성 · 관측 경계 · 제외 범주 ·
등급 우선순위는 ``test_evaluation_alignment_audit.py`` ·
``test_exclusion_categories.py`` · ``test_evaluation_excluded_audit.py``
(합 1,830줄) 가 이미 지킨다.
"""

import ast
import dataclasses
import inspect
import pathlib

import pytest

from agent.evaluation import (
    ATK_IN_LP,
    DECK_CARD_IN_LP,
    GRAVE_IS_COUNTED,
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    SPELL_TRAP_IN_LP,
    Evaluator,
    ExclusionCategory,
    StateEvaluator,
    StateValue,
    Terminal,
)
from agent.search import SearchPolicy, search_policy
from engine.action_validation import TRAP_TRIGGER_MISSING
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: Phase 3-A / 3-B / 3-C 가 쓴 **같은 카드 풀**에서 둘만 쓴다.
LUSTER_DRAGON = 11091375  # ATK 1900
BATTLE_OX = 5053103  # ATK 1700
POT_OF_GREED = 55144522

#: 평가가 내는 항의 **이름 전부.** 늘거나 줄면 feature 집합이 바뀐 것이다.
TERM_NAMES = ("lp", "atk", "monsters", "spells", "deck", "hand")


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


@pytest.fixture
def evaluator() -> StateEvaluator:
    return StateEvaluator()


def staged(repository, *, my_monsters: int, their_hand_gain: int) -> GameState:
    """
    증식의 G **모양**의 판을 손으로 만든다 — 그 카드를 쓰지 않는다.

    ``my_monsters`` 만큼 내 필드에 몬스터를 세우고 (= 전개),
    ``their_hand_gain`` 만큼 상대가 덱에서 패로 가져간다 (= 자원 제공).

    두 축을 **따로** 움직일 수 있어야 평가가 둘을 구분하는지 잴 수 있다.
    """
    deck = [LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    state.draw(MINE, 5)
    state.draw(THEIRS, 5)
    for _ in range(my_monsters):
        card = next(c for c in state.player(MINE).hand if c.card_id == LUSTER_DRAGON)
        state.move(card, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK)
    if their_hand_gain:
        state.draw(THEIRS, their_hand_gain)
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    return state


def value_of(evaluator, state: GameState, viewer: int = MINE) -> StateValue:
    return evaluator.evaluate(GameStateView.from_state(state, viewer=viewer))


def terms_of(evaluator, state: GameState, viewer: int = MINE) -> dict:
    return dict(value_of(evaluator, state, viewer).terms)


# ======================================================================
# A. 이미 있는 것 — 새로 만들지 않았다
# ======================================================================


def test_01_an_evaluation_core_already_exists_so_none_was_created():
    """
    **이 Phase 는 새 Evaluation 클래스를 만들지 않았다.**

    ``agent/evaluation.py`` 가 이미 ``GameStateView → StateValue`` 를 한다.
    Phase 가 목표로 적은 구조가 그대로 있다.

        GameStateView → Evaluation Features → Evaluation Score → Search
    """
    module = PROJECT_ROOT / "agent" / "evaluation.py"
    assert module.is_file()

    tree = ast.parse(source_of("agent/evaluation.py"))
    classes = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    #: 네 조각이 Phase 가 요구한 네 개념에 그대로 대응한다.
    assert "Terminal" in classes  # Game Outcome
    assert "StateValue" in classes  # Feature Value + Score
    assert "Evaluator" in classes  # 교체 지점
    assert "StateEvaluator" in classes  # 기본 구현

    #: 그리고 이 Phase 가 **새 평가자를 더하지 않았다.**
    assert {name for name in classes if name.endswith("Evaluator")} == {
        "Evaluator",
        "StateEvaluator",
    }


def test_02_the_two_similarly_named_abstractions_are_different_things():
    """
    ``agent.heuristic.Evaluation`` 과 ``agent.evaluation.StateValue`` 는
    **이름만 닮았고 다른 것을 센다.**

    ========================================  ===========================
    ``agent.heuristic.Evaluation``             **행동** 하나의 점수
                                               (``action`` 필드를 든다)
    ``agent.evaluation.StateValue``             **상태** 하나의 값
                                               (``terminal`` 등급을 든다)
    ========================================  ===========================

    그래서 둘을 합치면 안 된다 — 합치면 "이 수가 좋다" 와 "이 판이 좋다" 가
    한 숫자가 된다.
    """
    from agent.heuristic import Evaluation as ActionEvaluation

    action_fields = {f.name for f in dataclasses.fields(ActionEvaluation)}
    state_fields = {f.name for f in dataclasses.fields(StateValue)}

    assert "action" in action_fields
    assert "action" not in state_fields
    assert "terminal" in state_fields
    assert "terminal" not in action_fields
    assert action_fields.isdisjoint(state_fields - {"total"})


def test_03_the_rule_based_policy_does_not_touch_the_evaluation_core():
    """
    ``RuleBasedPolicy`` 는 ``agent.evaluation`` 을 **import 하지 않는다.**
    그래서 이 Phase 가 Evaluation Core 를 건드려도 규칙 기반 정책은 영향을
    받지 않는다 — 두 정책이 **다른 양을 센다** (3-C 의 ``test_20``).
    """
    imports = set()
    for node in ast.walk(ast.parse(source_of("agent/heuristic.py"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    assert "agent.evaluation" not in imports
    assert "StateEvaluator" not in source_of("agent/heuristic.py")


# ======================================================================
# B. feature 집합 — 무엇이 있고 무엇이 없는가
# ======================================================================


@pytest.mark.real_card
def test_04_the_feature_set_is_exactly_these_six(repository, evaluator):
    """
    **항은 여섯이고 이름이 고정이다.** 늘거나 줄면 feature 집합이 바뀐 것이다.

    Phase 가 요구한 범주와의 대응:

    ===========================  =========================================
    A Game Outcome                ``terminal`` (항이 아니라 **등급**이다)
    B Board State                 ``atk`` · ``monsters`` · ``spells``
    C Resource                    ``deck`` · ``hand``
    F Life Point                  ``lp``
    G Information                 ``excluded`` 의 세 범주
    D Interaction                 **없다** (``test_06``)
    E Follow-up                   **없다** (``test_05``)
    ===========================  =========================================
    """
    state = staged(repository, my_monsters=1, their_hand_gain=0)
    value = value_of(evaluator, state)
    assert tuple(name for name, _ in value.terms) == TERM_NAMES

    #: 합은 항의 합이다 — 숨은 항이 없다.
    assert value.heuristic == sum(amount for _, amount in value.terms)

    #: 등급은 항이 아니다. 섞지 않는다.
    assert "terminal" not in dict(value.terms)
    assert value.ordering_key() == (value.terminal.rank, value.heuristic)


def test_05_follow_up_is_deferred_because_the_input_cannot_answer_it():
    """
    **E (Follow-up) 은 가중치 문제가 아니라 입력 문제다.**

    평가가 받는 것은 ``GameStateView`` 뿐이고, 거기에는
    ``legal_actions`` · ``chain`` · ``priority`` 가 **없다.** 체인과 우선권은
    ``GameState`` 밖에 살기 때문이다 (ADR-007).

    그래서 "다음에 무엇을 할 수 있는가" 는 이 입력으로 **계산할 수 없다.**
    억지로 세려면 평가가 ``Duel`` 을 받아야 하고, 그러면 §4 의 순수 읽기
    구조가 깨진다. DEFERRED 로 적고 지어내지 않는다.
    """
    surface = {name for name in dir(GameStateView) if not name.startswith("_")}
    for missing in ("legal_actions", "chain", "priority"):
        assert missing not in surface

    #: 그 셋을 들고 있는 것은 ``Duel`` 이고, 평가자는 그것을 받지 않는다.
    signature = inspect.signature(StateEvaluator.evaluate)
    assert list(signature.parameters) == ["self", "view"]
    assert signature.parameters["view"].annotation in (GameStateView, "GameStateView")


def test_06_interaction_is_deferred_because_the_engine_cannot_tell_it():
    """
    **D (Interaction) 도 입력 문제다.**

    "상대 턴에 개입할 수 있는 수단이 몇 개인가" 를 세려면 세트된 카드가
    **유발 조건이 있는 함정인지** 알아야 한다. 엔진은 그것을 구분하지 못한다 —
    공식 스크립트의 ``SetCode(EVENT_*)`` 가 ``EffectDefinition`` 에 옮겨지지
    않았고, 그 사실이 이름 붙은 "없는 규칙" 으로 남아 있다.

    그래서 지금 셀 수 있는 것은 **마법 · 함정 존의 장수**뿐이고, 그것이
    ``spells`` 항이다. 장수와 interaction capability 를 혼동하지 않는다.
    """
    assert "trap-activation-timing" in TRAP_TRIGGER_MISSING
    assert "SetCode(EVENT_*)" in TRAP_TRIGGER_MISSING

    #: ``spells`` 는 **놓여 있다는 사실**의 값이고 발동 가능성이 아니다 —
    #: 그 까닭이 가중치 주석에 적혀 있다.
    weights = source_of("agent/evaluation.py")
    assert "발동이 후보에 오르지 않기" in weights
    assert "놓여 있다는 사실 자체의 값만 센다" in weights


def test_07_the_documented_weights_are_the_only_weights():
    """
    **가중치는 다섯이고 단위가 전부 LP 다.** 이 Phase 는 하나도 바꾸지 않았고
    새로 만들지도 않았다 (§5: 가중치 최적화 금지).
    """
    assert (ATK_IN_LP, MONSTER_IN_LP, SPELL_TRAP_IN_LP) == (1, 500, 300)
    assert (DECK_CARD_IN_LP, HAND_CARD_IN_LP) == (300, 200)
    assert GRAVE_IS_COUNTED is False

    #: 덱이 패보다 무겁다 — 그 까닭이 "덱아웃이 지금 유일한 패배 조건" 이다.
    assert DECK_CARD_IN_LP > HAND_CARD_IN_LP
    assert "덱아웃" in source_of("agent/evaluation.py")


# ======================================================================
# C. §6 의 답 — 두 사실을 구분하지 못한다
# ======================================================================


@pytest.mark.real_card
def test_08_every_term_but_hand_is_a_difference_so_sides_collapse(
    repository, evaluator
):
    """
    **왜 구분하지 못하는가 — 항이 전부 차(me − opponent)다.**

    ``hand`` 하나만 내 쪽을 센다. 나머지 다섯은 차이므로 "내가 좋아졌다" 와
    "상대가 나빠졌다" 가 **한 숫자에 합쳐진다.**
    """
    base = staged(repository, my_monsters=0, their_hand_gain=0)
    #: 양쪽이 대칭이면 차는 전부 0 이고, 내 쪽만 세는 항만 남는다.
    terms = terms_of(evaluator, base)
    assert terms["lp"] == 0
    assert terms["atk"] == 0
    assert terms["monsters"] == 0
    assert terms["spells"] == 0
    assert terms["deck"] == 0
    assert terms["hand"] == 5 * HAND_CARD_IN_LP

    #: 두 자리에서 본 값의 차 항은 **부호만 뒤집힌다** — 차라는 증거다.
    mine = terms_of(evaluator, base, MINE)
    theirs = terms_of(evaluator, base, THEIRS)
    for name in ("lp", "atk", "monsters", "spells", "deck"):
        assert mine[name] == -theirs[name], name
    #: ``hand`` 는 뒤집히지 않는다 — 양쪽이 각자 자기 패만 센다.
    assert mine["hand"] == theirs["hand"] == 5 * HAND_CARD_IN_LP


@pytest.mark.real_card
def test_09_giving_the_opponent_cards_raises_my_score(repository, evaluator):
    """
    **§6 의 답 — 구분하지 못한다. 그리고 부호가 거꾸로다.**

    내 판을 **한 칸도 바꾸지 않고** 상대에게 3장을 주면 점수가 **올라간다.**

    까닭은 ``deck`` 항이 ``(내 덱 − 상대 덱) × 300`` 이기 때문이다. 상대가
    뽑으면 상대 덱이 줄고, 그러면 차가 커진다. 그리고 상대 패가 늘어난 것을
    세는 항은 **하나도 없다** — ``WITHHELD`` 메모만 장수를 적고 값은 0 이다.

    이것은 가중치를 조절해서 고칠 수 있는 문제가 **아니다.** "상대에게 자원을
    제공했다" 에 대응하는 항이 애초에 없고, 움직이는 유일한 항이 **반대
    방향으로** 움직인다.
    """
    quiet = staged(repository, my_monsters=0, their_hand_gain=0)
    gave = staged(repository, my_monsters=0, their_hand_gain=3)

    quiet_value, gave_value = value_of(evaluator, quiet), value_of(evaluator, gave)

    #: 내 쪽은 한 칸도 다르지 않다.
    for name in ("lp", "atk", "monsters", "spells", "hand"):
        assert dict(quiet_value.terms)[name] == dict(gave_value.terms)[name], name

    #: 그런데 점수가 **올라간다.**
    assert gave_value.heuristic > quiet_value.heuristic
    assert gave_value.heuristic - quiet_value.heuristic == 3 * DECK_CARD_IN_LP

    #: 올라간 것은 ``deck`` 항 하나다.
    assert dict(gave_value.terms)["deck"] == 3 * DECK_CARD_IN_LP
    assert dict(quiet_value.terms)["deck"] == 0

    #: 상대 패가 5 → 8 로 늘었다는 사실은 **값 없이** 메모로만 남는다.
    held = [
        note
        for note in (
            item.note for item in gave_value.of_category(ExclusionCategory.WITHHELD)
        )
        if "상대 패" in note
    ]
    assert held == ["상대 패 8장의 값을 모른다"]
    #: 그리고 그것은 미해결로 세지도 않는다 — 규칙상 볼 수 없는 것이다.
    assert gave_value.partial is False


@pytest.mark.real_card
def test_10_the_maxx_c_shaped_states_are_ordered_by_board_alone(
    repository, evaluator
):
    """
    **§6 의 세 상태 A · B · C.** 전개가 커질수록 점수가 커진다 — 그런데 그
    증가분에 "상대에게 준 자원" 이 **빠져 있지 않고 더해져 있다.**

    같은 전개(3회)를 상대에게 **주고** 한 경우가 **주지 않고** 한 경우보다
    높다. 즉 평가만 보고 고르면 **자원을 주는 쪽을 고른다.**

    증식의 G 라는 카드도 그 효과도 여기 없다. 모양만 손으로 만들었고, 실제
    대응은 Search 가 엔진 결과를 비교할 일이다.
    """
    a = value_of(evaluator, staged(repository, my_monsters=1, their_hand_gain=1))
    b = value_of(evaluator, staged(repository, my_monsters=3, their_hand_gain=3))
    c = value_of(evaluator, staged(repository, my_monsters=5, their_hand_gain=5))
    b_quiet = value_of(evaluator, staged(repository, my_monsters=3, their_hand_gain=0))

    #: 전개가 커질수록 점수가 커진다 — 여기까지는 바라는 대로다.
    assert a.heuristic < b.heuristic < c.heuristic

    #: 그런데 **같은 전개**인데 자원을 준 쪽이 더 높다.
    assert b.heuristic > b_quiet.heuristic
    assert b.heuristic - b_quiet.heuristic == 3 * DECK_CARD_IN_LP

    #: 내 필드 쪽 항은 둘이 같다 — 차이는 전부 ``deck`` 에서 왔다.
    for name in ("atk", "monsters", "spells", "hand", "lp"):
        assert dict(b.terms)[name] == dict(b_quiet.terms)[name], name


# ======================================================================
# D. §7 확장성 — Opponent Model 을 붙일 자리가 아직 없다
# ======================================================================


def test_11_the_evaluator_protocol_takes_no_context():
    """
    **Opponent Model 을 받을 자리가 지금은 없다.**

    ``Evaluator.evaluate(view) -> StateValue`` 가 전부다. 나중에 상대 덱 믿음
    같은 문맥을 넘기려면 **Protocol 을 바꿔야 하고**, Search 가 그 Protocol 로
    런타임 검사를 하므로 (``isinstance(self.evaluator, Evaluator)``) 그 변경은
    Search 까지 닿는다.

    이번 Phase 는 그것을 바꾸지 않는다 — 사실만 적어 둔다.
    """
    signature = inspect.signature(Evaluator.evaluate)
    assert list(signature.parameters) == ["self", "view"]
    for forbidden in ("context", "belief", "opponent_model", "deck"):
        assert forbidden not in signature.parameters

    #: Search 가 Protocol 로 **실제로** 검사한다 — 그래서 서명 변경이 Search 에
    #: 닿는다. 소스에 그 문자열이 있는지만 보면 ``if False and ...`` 같은 변경을
    #: 놓친다 (3-F-1 의 고의 위반 7 이 실제로 그랬다). 그래서 **거부하는지**를
    #: 본다.
    class _NotAnEvaluator:
        name = "broken"

    from agent.search import SearchError
    from agent.simulation import Simulator

    with pytest.raises(SearchError, match="evaluate"):
        SearchPolicy(
            simulator=Simulator.__new__(Simulator),
            evaluator=_NotAnEvaluator(),
        )


def test_12_no_opponent_deck_or_card_name_enters_the_evaluation():
    """
    **상대 덱도 카드 이름도 보지 않는다** (§7 · §25).

    평가 모듈 전체에 카드 이름 · passcode · 덱 이름이 하나도 없다.
    """
    tree = ast.parse(source_of("agent/evaluation.py"))
    #: 숫자 리터럴은 가중치뿐이어야 한다 — passcode(8자리) 가 없다.
    numbers = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    assert not any(value > 10_000 for value in numbers), sorted(numbers)

    #: **카드의 정체를 읽는 접근자를 쓰지 않는다.** 읽는 것은 ``definition``
    #: 을 거친 ``atk`` 계열뿐이고, 그것은 앞면 카드의 공개 정보다.
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in (
        "name",  # 카드 이름
        "card_id",  # passcode
        "definition_for",  # 정의 조회기
        "repository",
        "setcode",
        "text",
        "state",  # GameState 직접 접근
        "clone",
        "randomness",
        "rng",
    ):
        assert forbidden not in attributes, forbidden

    #: 읽는 정의 항목은 **공격력 관련 셋**뿐이다.
    assert {"atk", "has_atk", "atk_is_question"} <= attributes
    assert "definition" in attributes


# ======================================================================
# E. Search 와의 관계 — 이미 연결되어 있다
# ======================================================================


@pytest.mark.real_card
def test_13_search_already_consumes_the_evaluation_core(repository):
    """
    **§8 의 답: 연결할 것이 없다 — 이미 연결되어 있다.**

    ``SearchPolicy.evaluator`` 가 ``Evaluator`` 를 들고 기본값이
    ``StateEvaluator`` 다. 그래서 Phase 가 말한 (A) 는 Phase 3-C 에서 이미
    이루어졌다.
    """
    fields = {f.name: f for f in dataclasses.fields(SearchPolicy)}
    assert "evaluator" in fields
    assert fields["evaluator"].default_factory is StateEvaluator

    duel = Duel.start(
        repository,
        decks=([LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5,) * 2,
        seed=7,
    )
    policy = search_policy(duel)
    assert isinstance(policy.evaluator, StateEvaluator)
    assert policy.evaluator.name == "state-evaluator"


@pytest.mark.real_card
def test_14_a_replacement_evaluator_is_accepted_without_touching_search(
    repository,
):
    """
    **교체 지점이 열려 있다.** 다른 평가자를 주입할 수 있고, Search 코드를
    고치지 않는다 — 그래서 미래의 Evaluation 변경이 Search 를 건드리지 않는다.
    """

    class _Flat:
        name = "flat"

        def evaluate(self, view: GameStateView) -> StateValue:
            return StateValue(terminal=Terminal.of(view), heuristic=0)

    duel = Duel.start(
        repository,
        decks=([LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5,) * 2,
        seed=7,
    )
    policy = search_policy(duel, evaluator=_Flat())
    assert policy.evaluator.name == "flat"
    assert isinstance(policy.evaluator, Evaluator)

    #: 비교는 ``ordering_key`` 하나로만 한다 — 평가자가 바뀌어도 Search 의
    #: 비교 방법은 바뀌지 않는다.
    assert "ordering_key()" in source_of("agent/search.py")


@pytest.mark.real_card
def test_15_this_phase_changed_no_production_behaviour(repository, evaluator):
    """
    **이 Phase 는 점수를 한 숫자도 바꾸지 않았다.**

    가중치 다섯 · 항 이름 여섯 · 등급 넷이 그대로이므로, 같은 판에서 같은
    점수가 나온다. 그래서 Search 의 결정도 바뀌지 않는다.
    """
    state = staged(repository, my_monsters=2, their_hand_gain=0)
    value = value_of(evaluator, state)

    #: 손으로 센 값과 맞춰 본다 — 공식 DB 의 ATK 1900 짜리 둘.
    assert dict(value.terms) == {
        "lp": 0,
        "atk": 2 * 1900 * ATK_IN_LP,
        "monsters": 2 * MONSTER_IN_LP,
        "spells": 0,
        "deck": 0,
        "hand": 3 * HAND_CARD_IN_LP,
    }
    assert value.heuristic == 3800 + 1000 + 600
    assert value.terminal is Terminal.ONGOING

    #: 평가가 판을 읽기만 한다 — 30번 불러도 판과 난수원이 그대로다.
    before, rng = state.state_hash(), state.rng.getstate()
    for _ in range(30):
        assert value_of(evaluator, state) == value
    assert state.state_hash() == before
    assert state.rng.getstate() == rng


@pytest.mark.real_card
def test_16_an_ended_duel_reports_a_grade_and_no_features(repository, evaluator):
    """
    **끝난 판은 항을 내지 않는다** — 등급이 모든 것을 말한다.

    그리고 등급 순서가 ``WIN > ONGOING > DRAW > LOSS`` 다. 진행 중인 판이
    무승부보다 높은 것이 핵심이다 — 아직 이길 수 있기 때문이다.
    """
    ongoing = value_of(evaluator, staged(repository, my_monsters=0, their_hand_gain=0))

    won = staged(repository, my_monsters=0, their_hand_gain=0)
    won.set_result(winner=MINE, reason="테스트가 끝을 적었다")
    drawn = staged(repository, my_monsters=0, their_hand_gain=0)
    drawn.set_result(winner=None, reason="테스트가 끝을 적었다")

    win_value = value_of(evaluator, won, MINE)
    loss_value = value_of(evaluator, won, THEIRS)
    draw_value = value_of(evaluator, drawn, MINE)

    for value, expected in (
        (win_value, Terminal.WIN),
        (loss_value, Terminal.LOSS),
        (draw_value, Terminal.DRAW),
    ):
        assert value.terminal is expected
        assert value.terms == ()
        assert value.heuristic == 0
        assert value.excluded == ()

    #: 등급 순서. ``ONGOING`` 이 ``DRAW`` 를 이긴다.
    assert win_value.ordering_key() > ongoing.ordering_key()
    assert ongoing.ordering_key() > draw_value.ordering_key()
    assert draw_value.ordering_key() > loss_value.ordering_key()


@pytest.mark.real_card
def test_17_the_same_counts_with_a_different_opponent_deck_score_the_same(
    repository, evaluator
):
    """
    **상대 덱 구성이 평가에 새지 않는다.** 장수가 같으면 점수가 같다.

    이것이 §7 의 "상대 덱을 몰래 알지 않는다" 를 지키는 자리다.
    """
    luster = [LUSTER_DRAGON] * 20 + [POT_OF_GREED] * 5
    ox = [BATTLE_OX] * 20 + [POT_OF_GREED] * 5

    def board(their_deck):
        state = GameState.create(
            repository, decks=(list(luster), list(their_deck)), seed=1
        )
        state.draw(MINE, 5)
        state.draw(THEIRS, 5)
        state.turn.turn_number = 2
        state.turn.turn_player = MINE
        state.turn.set_phase(Phase.MAIN1)
        return state

    same = value_of(evaluator, board(luster))
    other = value_of(evaluator, board(ox))

    assert same.heuristic == other.heuristic
    assert dict(same.terms) == dict(other.terms)
