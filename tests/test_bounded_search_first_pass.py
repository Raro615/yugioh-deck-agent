"""
Phase 6-AH — **제한된 전개 탐색 첫 구현.**

무엇을 재는가
-------------
이 파일이 지키려는 사실은 하나다 — **적어 둔 카드 순서를 호출하지 않고,
엔진이 허가한 행동과 해결 중 선택을 펼쳐 목표에 닿는 경로를 찾고, 그
경로를 새 초기 상태에서 다시 밟아 같은 판에 닿는다.**

🔴 **더 센 전개를 만들었다는 시험이 아니다.** 평가 함수가 없고, 찾은 경로가
``deck.combo_policy`` 의 적어 둔 경로와 같을 필요도 없다.

절의 구분 (§7)
--------------
======  =====================================================================
``A``   **실제 카드** — 두 검증용 입력에서 목표에 닿는다
``B``   **해결 중 선택 분기** — ``B-1`` 은 실제 카드, ``B-2`` 는 **재정 한
        건만 합성**한 격리 사례다 (아래 🔴 를 보라)
``C``   분기 안전성 — 원본 불변 · 형제 오염 없음 · 부분 적용 없음
``D``   종료와 정직한 결과 — 예산 · 미발견 · 미지원 보존 · 이 턴 안
``E``   재생과 회귀 — 재생 성공 · 어긋나면 실패로 적는다 · 기존 출력 유지
======  =====================================================================

🔴 **``B-2`` 가 무엇을 합성하는가.** 카드도 효과도 체인도 목표도 전부
실제다. 합성한 것은 **확인된 재정 한 건**뿐이다 —
``OPERATION_RULINGS`` 에 「오르페골 클리막스」(703897) 의
``MAY_BE_SENT_TO_GRAVE`` 를 ``TRUE`` 로 끼운다.

그렇게 하는 이유는 **실측한 사실** 때문이다: 이 저장소의 카드 14,759장
전수에서 「오르페골」 · 「성유물」 setcode 를 갖고 **자기 묘지행을 전제한
텍스트 증거**(``self_grave_text_evidence``)가 있는 카드는 **93920420
하나뿐**이다 (``test_b03`` 이 그 수를 센다). 그래서 기르수 ① 의 **허용**
후보는 실제 카드로는 언제나 **같은 카드의 사본들**이고, 선택이 목표 도달을
가르는 판을 실제 카드만으로는 만들 수 없다.

🔴 **그래서 ``B-2`` 를 ``A`` 의 근거로 쓰지 않는다.** 실제 카드 전개가
성공한다는 주장은 ``A`` 가 혼자 들고 있고, ``B-2`` 가 보이는 것은 **선택
분기 기계가 실제로 다른 미래를 연다**는 사실뿐이다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.bounded_search import (
    CHOICE_BRANCHING_UNAVAILABLE,
    BoundedSearch,
    BoundedSearchError,
    FieldGoal,
    NO_INTERFERENCE,
    OUT_OF_TURN_SCOPE,
    PathStep,
    SearchBudget,
    Termination,
    node_key,
    own_field,
    rerun_path,
    search_for_card,
    selection_options,
)
from agent.choice import ChoiceAsk, FirstPermittedChoice, ScriptedChoice
from agent.simulation import Simulator
from engine.action import PlayerActionKind
from engine.condition import ConditionResult
from engine.duel import Duel, TurnStep, duel_components
from engine.effect.journal import EventJournal
from engine.effect.library import OPERATION_RULINGS
from engine.effect.ruling import CardRuleFacts, RuleBasis, RuleFact
from engine.effect.semantics import RuleQuestion
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone
from integration.autonomy import PolicyChooser, TriggerSource
from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GIRSU = 69811710
GROWTH = 93920420
CLIMAX = 703897
GALATEA = 30741503
GALATEA_I = 48835607
POT_OF_GREED = 55144522
P0, P1 = 0, 1


# ======================================================================
# 입력 — 실제 카드
# ======================================================================
def _setup_for(repository, line):
    """그 검증용 입력으로 선공 메인1 판 하나. ``build_opening`` 그대로다."""
    from app.main import opening_wiring
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(line.recipe_ydk, repository)
    assert parsed.draft is not None
    chooser, triggers = opening_wiring(repository, None)
    setup = build_opening(
        repository, parsed.draft, list(line.hand),
        chooser=chooser, triggers=triggers,
    )
    assert setup.can_run, setup.blockers
    return setup


@pytest.fixture(scope="module")
def growth_input(repository):
    from deck.combo_policy import ORCUST_GIRSU_LINE

    return ORCUST_GIRSU_LINE


@pytest.fixture(scope="module")
def token_input(repository):
    from deck.combo_policy import ORCUST_GIRSU_TOKEN_LINE

    return ORCUST_GIRSU_TOKEN_LINE


@pytest.fixture(scope="module")
def growth_run(repository, growth_input):
    """
    기존 『성장』 경로에 쓰던 **그 입력**에서 한 번 탐색하고 재생한다.

    모듈 범위로 둔 이유는 하나 — 같은 탐색을 시험마다 다시 돌리면 묶음이
    몇 분씩 늘어난다. 🔴 **결과를 공유하지만 판을 공유하지 않는다**:
    재생은 ``bounded_search_opening`` 이 **새로 만든** 초기 상태에서 한다.
    """
    from app.main import bounded_search_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(growth_input.recipe_ydk, repository)
    return bounded_search_opening(
        repository, parsed.draft, list(growth_input.hand), card_id=GALATEA
    )


@pytest.fixture(scope="module")
def token_run(repository, token_input):
    """패에 『성장』 이 **없는** 입력에서 한 번."""
    from app.main import bounded_search_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(token_input.recipe_ydk, repository)
    return bounded_search_opening(
        repository, parsed.draft, list(token_input.hand),
        card_id=GALATEA,
        budget=SearchBudget(max_depth=8, max_nodes=400),
    )


# ======================================================================
# 판을 손으로 적는 입력 — **실제 카드만** 쓴다
# ======================================================================
def _choice_board(repository, *, deck_head=(CLIMAX, GROWTH)):
    """
    기르수 ① 의 **해결 중 선택이 갈림길이 되는** 시작 상태 (실제 카드).

    ===========================  =======================================
    자신 패                      기르수 · 『성장』
    자신 덱 맨 위                ``deck_head`` 순서 그대로
    자신 엑스트라                갈라테아
    상대 몬스터 존               기르수 5장 — **빈 칸이 없다**
    ===========================  =======================================

    🔴 **상대 몬스터 존을 채우는 것이 요점이다.** 비어 있으면 기르수 ③
    (서로의 필드에 토큰 1장씩) 이 발동할 수 있고, 그러면 ① 의 선택과
    무관한 둘째 경로가 열려 **선택이 갈림길이 아니게 된다.** 채우면 ③ 의
    발동 조건이 거짓이 되고 (실측: *"상대 MZONE 에 빈 칸"* 이 거짓),
    남는 길은 ① → 『성장』 ② → 링크뿐이다.

    🔴 **채우는 카드도 등재된 것만 쓴다.** 모르는 앞면 카드가 하나라도
    있으면 ``BoardRuling._interference`` 가 판 전체의 답을 ``UNKNOWN``
    으로 만들고, 그러면 『성장』 ② 의 발동 조건이 *"판정할 수 없습니다"*
    가 되어 이 파일이 재려는 축이 그 모름에 묻힌다 (실측: 통상 몬스터로
    채웠을 때 ② 가 후보에 오르지 않았다).

    🔴 **시작 상태만 손으로 적는다.** 첫 행동 이후의 변화는 전부
    ``Duel.apply`` 가 만든다.
    """
    state = GameState.create(
        repository,
        decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=P0,
        seed=0,
        shuffle=False,
    )
    #: 뒤에서부터 맨 앞에 끼우면 ``deck_head`` 의 순서가 그대로 남는다.
    for card_id in reversed(deck_head):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.DECK)
        state.player(P0).deck.remove(instance)
        state.player(P0).deck.insert(0, instance)
    for card_id in (GIRSU, GROWTH):
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    state.create_instance(GALATEA, owner=P0, zone=Zone.EXTRA)
    for index in range(5):
        instance = state.create_instance(GIRSU, owner=P1, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P1,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
    state.turn.turn_number = 1
    state.turn.set_phase(Phase.MAIN1)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        step=TurnStep.OPEN,
        first_player=P0,
        **duel_components(
            journal=EventJournal(),
            chooser=PolicyChooser(FirstPermittedChoice()),
        ),
        triggers=TriggerSource(repository),
    )


#: 🔴 **합성한 것은 이 재정 한 건뿐이다** (파일 머리말의 🔴 를 보라).
_SYNTHETIC_RULING = CardRuleFacts(
    card_id=CLIMAX,
    answers={
        RuleQuestion.MAY_BE_SENT_TO_GRAVE: RuleFact(
            ConditionResult.TRUE,
            RuleBasis.CARD_TEXT,
            "[합성 — 실제 재정이 아니다] Phase 6-AH 의 시험이 "
            "**허용 후보를 두 장으로 만들기 위해** 끼운 사실이다. "
            "production 의 OPERATION_RULINGS 는 바뀌지 않는다 "
            "(monkeypatch 가 되돌린다).",
        ),
    },
)


@pytest.fixture
def two_permitted(monkeypatch):
    """
    기르수 ① 의 **허용 후보를 두 장으로** 만든다 — 격리된 합성 재정 하나.

    🔴 **production 을 바꾸지 않는다.** ``monkeypatch`` 가 끝에 되돌리고,
    ``test_b04`` 가 되돌아왔는지 센다.
    """
    kept = dict(OPERATION_RULINGS._facts)
    monkeypatch.setattr(
        OPERATION_RULINGS, "_facts", {**kept, CLIMAX: _SYNTHETIC_RULING}
    )
    return kept


# ======================================================================
# A. §7-A — 실제 카드로 목표에 닿는다
# ======================================================================
def test_a01_the_growth_input_reaches_galatea(growth_run):
    """🟢 기존 『성장』 경로의 입력에서 **탐색이** 목표를 찾는다."""
    setup, outcome, replayed = growth_run
    assert outcome is not None
    assert outcome.termination is Termination.GOAL_REACHED, outcome.describe_ko()
    assert outcome.reached
    assert outcome.action_count >= 1
    #: 실제 판에서 센다 — 갈라테아는 링크 몬스터이므로 EMZONE 이다.
    assert (Zone.EMZONE.value, GALATEA, True) in outcome.final_field
    assert "판이 정리되었습니다" in outcome.goal_reason
    #: 🔴 적어 둔 경로와 **같을 필요가 없다.** 비교하지 않는다.
    assert replayed is not None and replayed.ok, replayed


def test_a02_the_token_input_reaches_galatea(token_run, token_input):
    """
    🟢 패에 『성장』 이 **없는** 입력에서도 찾는다.

    그 입력이 요점이다 — 기존 『성장』 경로의 두 번째 소재(패의 93920420)가
    없으므로, 탐색은 **다른 수단**으로 소재를 만들어야 한다.
    """
    assert GROWTH not in token_input.hand
    setup, outcome, replayed = token_run
    assert outcome is not None
    assert outcome.termination is Termination.GOAL_REACHED, outcome.describe_ko()
    assert (Zone.EMZONE.value, GALATEA, True) in outcome.final_field
    assert replayed is not None and replayed.ok, replayed


def test_a03_the_search_module_never_calls_a_written_line():
    """
    🔴 **고정 정책을 호출하지 않았다** — 코드 구조로 센다.

    세 가지를 확인한다.

    1. 탐색 모듈에 적어 둔 경로의 이름이 **글자로도 없다.**
    2. ``agent/`` 전체가 ``deck`` 도 ``integration`` 도 import 하지 않는다
       (ADR-007 의 경계 그대로).
    3. 탐색 모듈에 **카드 ID 리터럴이 없다** — 목표는 밖에서 받는다.
    """
    source = (PROJECT_ROOT / "agent" / "bounded_search.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    #: 🔴 **코드만 센다.** 설명문에는 "무엇을 하지 않는가" 를 적으므로 그
    #: 이름이 나온다 — 그것을 호출로 읽으면 감사가 거짓이 된다 (이 저장소의
    #: 다른 감사들이 ``code_only`` 를 쓰는 것과 같은 이유다).
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            used.add(node.module)
            used |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            used |= {alias.name for alias in node.names}
    for absent in (
        "ORCUST_GIRSU_LINE",
        "ORCUST_GIRSU_TOKEN_LINE",
        "ComboLine",
        "VerificationLinePolicy",
        "deck.combo_policy",
        "PlannedAction",
        "line_named",
        "line_progress",
    ):
        assert absent not in used, absent

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in {"__future__", "engine", "agent",
                                                 "time", "dataclasses", "enum",
                                                 "itertools"}, node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in {"time", "dataclasses",
                                                    "enum", "itertools"}, alias.name

    #: 🔴 **카드 ID 가 없다.** 다섯 자리 이상의 정수 리터럴을 전수로 센다 —
    #: 이 모듈의 상수는 전부 작은 예산 값이다.
    big = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and node.value >= 10_000
    ]
    assert big == [], big

    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        found = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(found):
            if isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                roots |= {alias.name.split(".")[0] for alias in node.names}
        assert "deck" not in roots, path.name
        assert "integration" not in roots, path.name
        assert "core" not in roots, path.name


def test_a04_the_goal_is_judged_on_the_real_state(repository):
    """
    🟢 목표는 **실제 ``GameState``** 에서 센다 — 기록이나 걸음 수가 아니다.

    그리고 **판이 정리되지 않은 자리는 목표가 아니다**: 체인이 올라간
    자리에서 판정하면 ``present`` 가 참이어도 ``reached`` 는 거짓이다.
    """
    goal = FieldGoal(card_id=GIRSU, seat=P0)
    duel = _choice_board(repository)
    first = goal.judge(duel)
    assert first.present is False and first.reached is False

    #: 기르수를 **실제 일반 소환으로** 올린다.
    summons = [
        action for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.NORMAL_SUMMON
    ]
    assert duel.apply(summons[0]).accepted
    on_field = goal.judge(duel)
    assert on_field.present is True
    #: 🔴 소환 직후는 **유발 처리 기회**가 열려 있다 — 정리된 자리가 아니다.
    assert on_field.settled is False, on_field.reason
    assert on_field.reached is False
    assert (Zone.MZONE.value, GIRSU, True) in own_field(duel, P0)


# ======================================================================
# B. §7-B — 해결 중 선택 분기
# ======================================================================
def test_b01_the_real_card_run_branches_on_a_resolution_choice(token_run):
    """
    🟢 **실제 카드** 실행이 해결 중 선택을 적고, 분기를 만들었다.

    🔴 **그 자리의 허용 후보만 적는다** — 적힌 후보가 둘 이상이면 그것은
    엔진이 그 자리에서 낸 목록이고, 탐색은 그 안에서만 다른 답을 해 본다.
    """
    _setup, outcome, _replay = token_run
    asks = [ask for step in outcome.path for ask in step.choices]
    assert asks, outcome.describe_ko()
    assert outcome.choice_branches > 0
    many = [ask for ask in asks if ask.options >= 2]
    assert many, [ask.describe_ko() for ask in asks]
    for ask in asks:
        assert ask.minimum <= len(ask.chosen) <= ask.maximum
        offered = {instance for instance, _card in ask.offered}
        assert set(ask.chosen) <= offered, ask.describe_ko()
        assert ask.plan_missing is False


def test_b02_only_the_choice_branch_reaches_the_goal(repository, two_permitted):
    """
    🔴 **선택이 목표 도달을 가른다** — ``first-permitted`` 는 놓치고 탐색은 찾는다.

    같은 시작 상태 · 같은 예산 · 다른 선택 분기 상한 하나만 바꾼다.

    ========================  ==================================================
    ``max_choice_branches=0``  허용 후보의 **앞쪽**(클리막스)을 보내고 끝난다 —
                               『성장』 ② 가 유발되지 않으므로 둘째 소재가 없다
    ``max_choice_branches=4``  같은 자리에서 **93920420** 을 보내는 분기를 해
                               보고 목표에 닿는다
    ========================  ==================================================
    """
    duel = _choice_board(repository)
    #: 덱 맨 위가 클리막스다 — ``first-permitted`` 가 집는 쪽이다.
    assert [card.card_id for card in duel.state.player(P0).deck.cards()[:2]] == [
        CLIMAX, GROWTH
    ]

    blind = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=6, max_nodes=120, max_choice_branches=0),
    ).run(_choice_board(repository))
    assert blind.reached is False
    assert blind.choice_branches == 0
    assert blind.choice_plans == 0
    #: 🔴 **"범위를 다 펼쳤다" 가 아니다** (6-AH 보완 B 가 정정한 자리).
    #: 보완 전에는 이 줄이 ``EXHAUSTED`` 였는데, 그것은 **틀린 말**이었다 —
    #: 선택 분기 상한이 0 이라 기르수 ① 의 대안을 **하나도 확인하지 않은**
    #: 채 끝났기 때문이다. 지금은 그 생략이 기록되고, 종료 사유도 예산
    #: 초과로 나온다.
    assert blind.termination is Termination.BUDGET_EXCEEDED, blind.describe_ko()
    assert "max_choice_branches=0" in blind.budget_hit
    assert blind.skipped_choices
    assert blind.choice_offers_truncated == 1
    assert any(
        "확인하지 않은 대안이 남았습니다" in line for line in blind.out_of_scope
    )
    #: 🔴 어느 자리인지 적혀 있고, 그 자리의 후보 수도 적혀 있다.
    assert any(
        "69811710:e[0]" in line and "후보 2장" in line
        for line in blind.out_of_scope
    )

    found = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=6, max_nodes=120, max_choice_branches=4),
    ).run(_choice_board(repository))
    assert found.termination is Termination.GOAL_REACHED, found.describe_ko()
    assert found.choice_branches >= 1
    assert (Zone.EMZONE.value, GALATEA, True) in found.final_field

    #: 🔴 **고른 것이 앞쪽이 아니다.** 그것이 "first-permitted 가 놓친다" 의 뜻이다.
    decisive = [
        ask for step in found.path for ask in step.choices
        if ask.options >= 2
    ]
    assert decisive, found.describe_ko()
    assert decisive[0].chosen_card_ids == (GROWTH,)
    assert decisive[0].planned is True
    assert decisive[0].offered[0][1] == CLIMAX

    #: 🔴 **상한 4 로는 대안을 다 확인했다** — 생략이 없다.
    assert found.choice_offers_truncated == 0
    assert found.skipped_choices is False
    assert not any(
        "확인하지 않은 대안이 남았습니다" in line for line in found.out_of_scope
    )
    assert found.choice_plans >= 1

    #: 그리고 재생된다.
    again = rerun_path(_choice_board(repository), found)
    assert again.ok, again.describe_ko()
    assert again.matches_search


def test_b03_no_real_card_pair_can_make_that_choice_matter(repository):
    """
    🔴 **``B-2`` 가 왜 합성 재정을 쓰는가** — 실측으로 적는다.

    기르수 ① 의 허용 후보가 되려면 ``MAY_BE_SENT_TO_GRAVE`` 가 ``TRUE``
    여야 하고, 그 답은 (1) 손으로 등록한 재정이나 (2) **자기 묘지행을 전제한
    텍스트 증거**에서만 나온다 (ADR-006). 「오르페골」 · 「성유물」 setcode
    를 가진 카드 중 그 둘 중 하나를 만족하는 것은 **93920420 하나뿐**이다.

    그래서 실제 카드만으로는 **허용 후보가 서로 다른 두 카드**인 판을 만들
    수 없고, 선택이 목표를 가르는 실제 카드 사례도 만들 수 없다.
    """
    duel = _choice_board(repository, deck_head=(CLIMAX, GROWTH))
    summons = [
        action for action in duel.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.NORMAL_SUMMON
    ]
    scripted = ScriptedChoice((), FirstPermittedChoice())
    fork = Simulator(duel).fork(selector=scripted)
    assert fork.apply(summons[0]).accepted
    from agent.bounded_search import _settle

    _settle(fork, P0)
    firing = [
        action for action in fork.legal_actions(P0).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert firing
    second = ScriptedChoice((), FirstPermittedChoice())
    deeper = Simulator(fork).fork(selector=second)
    assert deeper.apply(firing[0]).accepted
    _settle(deeper, P0)
    asks = second.log
    assert len(asks) == 1, [ask.describe_ko() for ask in asks]
    #: 🔴 **허용 후보가 한 장이다** — 합성 재정 없이는 분기가 생기지 않는다.
    assert asks[0].options == 1, asks[0].describe_ko()
    assert asks[0].offered[0][1] == GROWTH

    #: 그리고 production 의 등록소에 클리막스가 **없다.**
    assert OPERATION_RULINGS.facts_for(CLIMAX) is None


def test_b04_production_rulings_came_back(repository):
    """🔴 ``B-2`` 의 합성 재정이 **되돌아왔다** — production 은 그대로다."""
    assert OPERATION_RULINGS.facts_for(CLIMAX) is None
    assert OPERATION_RULINGS.facts_for(GROWTH) is not None


def test_b06_a_chooser_that_cannot_fork_is_reported(repository, monkeypatch):
    """
    🔴 **사본이 선택 정책을 받지 못하면 그 사실을 적는다.**

    받지 못하면 해결 중 선택이 사본 안에서 거절되고, 그 결과는 "목표에
    닿지 못했다" 로 보인다 — 그 둘을 섞으면 **배선 문제가 규칙상 불가능으로
    읽힌다.** 그래서 범위 밖 목록에 남긴다.
    """
    from integration.autonomy import PolicyChooser

    duel = _choice_board(repository)

    def _no_selector(self, selector=None):
        #: 사본용 정책을 받을 수 없는 고르는 사람을 흉내 낸다.
        if selector is not None:
            raise TypeError("이 고르는 사람은 사본용 정책을 받지 않습니다")
        return PolicyChooser(self.selector, self.definitions)

    monkeypatch.setattr(PolicyChooser, "forked", _no_selector)
    outcome = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=3, max_nodes=30, max_choice_branches=2),
    ).run(duel)
    assert CHOICE_BRANCHING_UNAVAILABLE in outcome.out_of_scope
    assert "규칙상 불가능" in CHOICE_BRANCHING_UNAVAILABLE
    #: 그리고 원본은 그대로다.
    assert own_field(duel, P0) == ()


def test_b05_selection_options_respects_the_counts():
    """
    🟢 분기 후보는 **엔진이 말한 장수 범위** 안의 조합뿐이고 순서가 같다.

    🔴 후보 밖을 만들지 않는다 — 재료가 ``offered`` 의 번호뿐이다.
    """
    ask = ChoiceAsk(
        index=0, label="합성", minimum=1, maximum=2,
        offered=((7, 111), (3, 222), (5, 333)),
        chosen=(3,), chosen_card_ids=(222,),
    )
    options, truncated = selection_options(ask, limit=99)
    assert truncated is False
    assert options == (
        (3,), (5,), (7,),
        (3, 5), (3, 7), (5, 7),
    )
    #: 같은 물음이면 같은 목록이다 (집합의 반복 순서에 기대지 않는다).
    assert selection_options(ask, limit=99)[0] == options
    #: 상한에 걸리면 **잘린 사실을 돌려준다.**
    short, cut = selection_options(ask, limit=2)
    assert cut is True and short == ((3,), (5,))
    #: 장수가 정확히 하나면 조합도 그만큼이다.
    one = ChoiceAsk(index=0, label="합성", minimum=1, maximum=1,
                    offered=((9, 1), (8, 2)), chosen=(8,))
    assert selection_options(one, limit=9)[0] == ((8,), (9,))


# ======================================================================
# C. §7-C — 분기 안전성
# ======================================================================
def test_c01_the_original_board_never_moves(growth_run):
    """
    🟢 **원본 상태 불변.** 탐색이 끝난 뒤 받은 듀얼이 그대로다.

    🔴 그리고 **원본의 고르는 사람에게 묻지 않았다** — 사본의 물음이
    실제 듀얼의 기록에 섞이면 그 기록은 더 이상 증거가 아니다.
    """
    setup, outcome, _replay = growth_run
    duel = setup.duel
    #: 탐색은 사본에만 적용하므로 원본에는 아무 카드도 움직이지 않았다.
    assert own_field(duel, P0) == ()
    assert duel.state.turn.turn_number == 1
    assert len(duel.state.player(P0).hand.cards()) == len(setup.hand)
    assert setup.chooser is not None
    assert setup.chooser.records == ()
    #: 🔴 ``BoundedSearch.run`` 이 해시와 난수 좌표를 직접 확인하고,
    #: 어긋나면 던진다 — 여기서 그 계약을 한 번 더 센다.
    assert outcome.final_state_hash != duel.state.state_hash()


def test_c02_sibling_branches_do_not_contaminate_each_other(repository):
    """
    🟢 **형제 분기가 섞이지 않는다** — 카드 · 토큰 · 사용 제한 전부.

    같은 부모에서 두 사본을 만들어 **다른 수**를 둔다. 둘의 판이 서로
    다르고, 부모는 그대로다.
    """
    duel = _choice_board(repository)
    before = duel.state.state_hash()
    parent = Simulator(duel)
    legal = duel.legal_actions(P0)
    kinds = {action.kind for action in legal.allowed}
    assert PlayerActionKind.NORMAL_SUMMON in kinds
    assert PlayerActionKind.SET_MONSTER in kinds

    results = {}
    for kind in (PlayerActionKind.NORMAL_SUMMON, PlayerActionKind.SET_MONSTER):
        action = next(a for a in legal.allowed if a.kind is kind)
        fork = parent.fork(selector=ScriptedChoice((), FirstPermittedChoice()))
        assert fork.apply(action).accepted
        results[kind] = (
            fork.state.state_hash(),
            own_field(fork, P0),
            fork.state.summon_uses.canonical_state(),
        )

    #: 두 분기의 판이 다르다 (앞면 소환과 뒷면 세트).
    assert results[PlayerActionKind.NORMAL_SUMMON] != results[
        PlayerActionKind.SET_MONSTER
    ]
    assert results[PlayerActionKind.NORMAL_SUMMON][1] == (
        (Zone.MZONE.value, GIRSU, True),
    )
    assert results[PlayerActionKind.SET_MONSTER][1] == (
        (Zone.MZONE.value, GIRSU, False),
    )
    #: 부모는 한 칸도 움직이지 않았다.
    assert duel.state.state_hash() == before
    assert own_field(duel, P0) == ()


def test_c03_a_refused_branch_applies_nothing(repository):
    """
    🟢 **실패한 분기의 부분 적용이 없다.**

    기르수 ③ 은 이 판에서 거절된다 (상대 몬스터 존이 꽉 찼다). 그 거절이
    부모에도 사본에도 아무것도 남기지 않는다.
    """
    duel = _choice_board(repository)
    summons = next(
        a for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert duel.apply(summons).accepted
    from agent.bounded_search import _settle

    _settle(duel, P0)
    held = [
        action for action in duel.legal_actions(P0).withheld
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert held, duel.legal_actions(P0).withheld
    assert any("상대 MZONE 에 빈 칸" in (item.reason or "") for item in held)

    before = duel.state.state_hash()
    search = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=2, max_nodes=20, max_choice_branches=0),
    )
    outcome = search.run(duel)
    assert outcome.reached is False
    assert duel.state.state_hash() == before


def test_c04_dedup_never_merges_two_different_futures(repository):
    """
    🟢 **중복 제거 기준이 안전한 쪽으로 기운다.**

    - 체인이 진행 중이면 **열쇠가 없다** (``None``) — 합치지 않는다.
    - 사용 제한이 다른 두 자리는 **다른 열쇠**다 (``state_hash`` 가 센다).
    - 허용 후보가 다른 두 자리도 다른 열쇠다.
    """
    duel = _choice_board(repository)
    first = node_key(duel, duel.legal_actions(P0))
    assert first is not None

    summons = next(
        a for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    )
    parent = Simulator(duel)
    fork = parent.fork(selector=ScriptedChoice((), FirstPermittedChoice()))
    assert fork.apply(summons).accepted
    #: 일반 소환권을 썼고 유발 기회가 열렸다 — 둘 다 다른 자리를 만든다.
    second = node_key(fork, fork.legal_actions(fork.to_act))
    assert second is not None and second != first

    #: 체인이 올라간 자리에는 열쇠가 없다.
    from agent.bounded_search import _settle

    _settle(fork, P0)
    firing = [
        a for a in fork.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert firing
    chained = Simulator(fork).fork(
        selector=ScriptedChoice((), FirstPermittedChoice())
    )
    assert chained.apply(firing[0]).accepted
    assert not chained.chain.is_empty
    assert node_key(chained, chained.legal_actions(chained.to_act)) is None


# ======================================================================
# D. §7-D — 종료와 정직한 결과
# ======================================================================
def test_d01_the_depth_budget_is_reported(repository):
    """🟢 깊이 예산에 걸리면 **예산 초과**이고, 그 칸의 이름을 적는다."""
    outcome = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=1, max_nodes=40, max_choice_branches=0),
    ).run(_choice_board(repository))
    assert outcome.termination is Termination.BUDGET_EXCEEDED
    assert any("max_depth=1" in line for line in outcome.budget_hit)
    assert outcome.reached is False
    #: 🔴 **"불가능" 이라고 적지 않는다.**
    assert "불가능" not in outcome.goal_reason


def test_d02_the_node_budget_is_reported(repository):
    """🟢 노드 예산에 걸려도 같다 — 종료 사유와 걸린 칸을 따로 적는다."""
    outcome = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=6, max_nodes=2, max_choice_branches=0),
    ).run(_choice_board(repository))
    assert outcome.termination is Termination.BUDGET_EXCEEDED
    assert any("max_nodes=2" in line for line in outcome.budget_hit)
    assert outcome.nodes_expanded <= 3


def test_d03_not_found_is_not_an_error_and_keeps_the_unsupported(repository):
    """
    🟢 **미발견 · 예산 초과 · 오류를 가른다.**

    필드에 올라올 수 없는 카드(마법)를 목표로 두면, 예산이 남은 채로
    범위를 다 펼치고 :attr:`Termination.EXHAUSTED` 가 된다. 그리고 그 자리의
    **미지원 사유는 그대로 남는다** — 종료 사유와 다른 칸이다.
    """
    outcome = BoundedSearch(
        goal=FieldGoal(card_id=POT_OF_GREED, seat=P0),
        budget=SearchBudget(max_depth=6, max_nodes=200, max_choice_branches=0),
    ).run(_choice_board(repository))
    assert outcome.termination is Termination.EXHAUSTED, outcome.describe_ko()
    #: 🔴 **예산에 걸린 칸이 하나도 없다.** 걸렸다면 그것은 소진이 아니라
    #: 예산 초과이고, 종료 사유가 그렇게 바뀐다 (``test_d01``).
    assert outcome.budget_hit == (), outcome.describe_ko()
    assert outcome.errors == ()
    assert outcome.unsupported, outcome.describe_ko()
    assert any("rule" in line or "판정" in line or "아직" in line
               for line in outcome.unsupported)


def test_d04_the_search_stays_inside_this_turn(growth_run, repository):
    """
    🟢 **이 턴을 벗어나지 않는다.** ``end_phase`` 를 전개하지 않고 그 사실을 적는다.

    🔴 턴을 넘기는 유일한 수가 ``end_phase`` 이므로, 그것을 고르지 않는 것이
    구조적인 보장이다.
    """
    _setup, outcome, _replay = growth_run
    assert OUT_OF_TURN_SCOPE in outcome.out_of_scope
    assert all(step.kind != "end_phase" for step in outcome.path)

    #: 재생한 판의 턴 번호가 그대로다.
    duel = _choice_board(repository)
    started = duel.state.turn.turn_number
    found = BoundedSearch(
        goal=FieldGoal(card_id=GALATEA, seat=P0),
        budget=SearchBudget(max_depth=4, max_nodes=60, max_choice_branches=0),
    ).run(duel)
    #: 🔴 **턴이 넘어가지 않았다.** 목표를 찾았는지와 무관한 사실이다 —
    #: 합성 재정이 없으면 이 판에서도 허용 후보가 『성장』 하나뿐이라
    #: ``first-permitted`` 만으로 목표에 닿는다 (``test_b03`` 의 실측).
    assert duel.state.turn.turn_number == started
    assert OUT_OF_TURN_SCOPE in found.out_of_scope
    assert all(step.kind != "end_phase" for step in found.path)


def test_d05_the_goal_node_has_passed_the_required_steps(growth_run):
    """
    🟢 **목표에 일찍 닿아도 남은 필수 처리를 생략하지 않는다.**

    마지막 걸음이 지나간 필수 걸음이 기록에 남아 있고, 그 걸음에 상대의
    무방해 패스가 포함된다 — 우선권을 손으로 돌리지 않았다는 증거다.
    """
    _setup, outcome, _replay = growth_run
    last = outcome.path[-1]
    assert last.forced, last.describe_ko()
    everything = [note for step in outcome.path for note in step.forced]
    assert any(NO_INTERFERENCE in note for note in everything)
    assert any("판이 다시 열렸습니다" in note for note in everything)
    assert "판이 정리되었습니다" in outcome.goal_reason


def test_d06_the_budget_refuses_nonsense():
    """🟢 예산 칸을 잘못 적으면 **거절한다** — 조용히 고쳐 쓰지 않는다."""
    for bad in (
        {"max_depth": 0},
        {"max_nodes": -1},
        {"max_seconds": 0},
        {"max_choice_branches": -1},
        {"max_depth": True},
    ):
        with pytest.raises(BoundedSearchError):
            SearchBudget(**bad)
    with pytest.raises(BoundedSearchError):
        FieldGoal(card_id="30741503")
    with pytest.raises(BoundedSearchError):
        FieldGoal(card_id=GALATEA, seat=2)
    with pytest.raises(BoundedSearchError):
        BoundedSearch(goal=FieldGoal(GALATEA)).run("듀얼이 아니다")


# ======================================================================
# E. §7-E — 재생과 회귀
# ======================================================================
def test_e01_the_found_path_replays_on_a_fresh_board(growth_run, token_run):
    """
    🟢 **새 초기 상태에서 다시 밟아 같은 판에 닿는다.**

    🔴 탐색이 만든 최종 상태를 그대로 내보내는 것이 아니다 —
    ``bounded_search_opening`` 이 ``build_opening`` 을 **다시** 불러 만든
    듀얼에서 재생한다.
    """
    for _setup, outcome, replayed in (growth_run, token_run):
        assert replayed is not None
        assert replayed.ok, replayed.describe_ko()
        assert replayed.goal_reached
        assert replayed.matches_search
        assert replayed.steps == outcome.action_count
        assert replayed.final_state_hash == outcome.final_state_hash
        assert replayed.final_field == outcome.final_field


def test_e02_a_tampered_choice_fails_the_replay(repository, growth_run):
    """
    🔴 **기록된 선택이 그 자리의 허용 후보가 아니면 재생 실패다.**

    성공으로 바꾸지 않고 원인을 적는다.
    """
    _setup, outcome, _replay = growth_run
    with_choice = [
        index for index, step in enumerate(outcome.path) if step.choices
    ]
    assert with_choice
    spot = with_choice[0]
    broken = list(outcome.path)
    bad_ask = ChoiceAsk(
        index=0,
        label=broken[spot].choices[0].label,
        minimum=1,
        maximum=1,
        offered=broken[spot].choices[0].offered,
        chosen=(999_999,),
        chosen_card_ids=(0,),
    )
    broken[spot] = PathStep(
        order=broken[spot].order,
        kind=broken[spot].kind,
        action_key=broken[spot].action_key,
        choices=(bad_ask,),
        forced=broken[spot].forced,
        reason=broken[spot].reason,
    )
    import dataclasses

    tampered = dataclasses.replace(outcome, path=tuple(broken))

    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    chooser, triggers = opening_wiring(repository, None)
    fresh = build_opening(
        repository, parsed.draft, list(ORCUST_GIRSU_LINE.hand),
        chooser=chooser, triggers=triggers,
    )
    result = rerun_path(fresh.duel, tampered)
    assert result.ok is False
    assert result.goal_reached is False
    assert "허용 후보에 없었습니다" in result.reason


def test_e03_a_tampered_action_fails_the_replay(repository, growth_run):
    """🔴 **기록된 행동이 허용 후보가 아니면** 재생 실패다."""
    import dataclasses

    _setup, outcome, _replay = growth_run
    broken = list(outcome.path)
    broken[0] = PathStep(
        order=1,
        kind=broken[0].kind,
        action_key=("normal_summon", 0, 999_999, (), None, None, ()),
    )
    tampered = dataclasses.replace(outcome, path=tuple(broken))

    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    chooser, triggers = opening_wiring(repository, None)
    fresh = build_opening(
        repository, parsed.draft, list(ORCUST_GIRSU_LINE.hand),
        chooser=chooser, triggers=triggers,
    )
    result = rerun_path(fresh.duel, tampered)
    assert result.ok is False
    assert "허용 후보에" in result.reason
    assert result.steps == 0


def test_e04_an_empty_path_is_not_a_replay(growth_run):
    """🔴 경로가 없으면 재생도 없다 — 성공으로 적지 않는다."""
    import dataclasses

    _setup, outcome, _replay = growth_run
    empty = dataclasses.replace(outcome, path=())
    result = rerun_path(_setup.duel, empty)
    assert result.ok is False
    assert "재생할 경로가 없습니다" in result.reason


def test_e05_the_summary_says_the_five_things(growth_run):
    """
    🟢 요약이 **§6 의 다섯 가지**를 적는다.

    실행 방식(제한 탐색) · 목표 도달 여부 · 행동 수와 노드 수 · 예산 종료
    여부 · 전체 규칙 지원을 뜻하지 않는다는 설명.
    """
    from deck.report import render_bounded_search, render_bounded_search_brief

    _setup, outcome, replayed = growth_run
    brief = render_bounded_search_brief(outcome, replayed)
    assert "제한 전개 탐색" in brief
    assert "✔ 도달" in brief
    assert f"행동 {outcome.action_count}걸음" in brief
    assert f"펼친 노드 {outcome.nodes_expanded}개" in brief
    assert "예산" in brief
    assert "전체 규칙 지원을 뜻하지 않습니다" in brief
    assert "최선 전개도 승률 평가도 아닙니다" in brief
    assert "경로 재생" in brief

    detail = render_bounded_search(outcome, replayed, _setup)
    assert "전체 기록" in detail
    assert outcome.final_state_hash in detail
    #: 🔴 **입력 조건을 함께 적는다** (§5) — 알 수 없는 것을 지우지 않는다.
    assert "입력 조건" in detail
    for card_id in _setup.hand:
        assert f"[{card_id}]" in detail
    assert "알 수 없음" in detail
    assert any(
        "남은 덱의 순서는 입력에 없습니다" in note for note in _setup.unknowns
    )
    for step in outcome.path:
        assert str(step.action_key) in detail
    #: 🔴 상세에는 **그 자리의 허용 후보**가 그대로 적힌다.
    for step in outcome.path:
        for ask in step.choices:
            assert "그 자리의 허용 후보" in detail


def test_e06_the_search_mode_is_opt_in(repository):
    """
    🟢 **주지 않으면 돌리지 않는다** — 기존 ``/combo`` 동작이 그대로다.

    그리고 모르는 목표 이름은 **비슷한 것으로 고쳐 주지 않는다.**
    """
    import inspect

    from app.discord_bot import SearchService, _run_bounded_search, combo_messages
    from app.main import DeckAgent, SEARCH_GOALS, search_goal_card_id

    #: 기존 이름의 서명은 바뀌지 않았다 (6-AC 가 고정한 목록 그대로).
    assert list(inspect.signature(combo_messages).parameters) == [
        "agent", "hand_text", "board_text", "deck_text", "recipe_text",
        "line_text",
    ]
    #: 🔴 **Phase 6-AI 가 ``results_text`` 를 그 뒤에 더했다** (모을 서로
    #: 다른 결과 수). 이 시험이 틀린 가정을 갖고 있었던 것이 아니다 —
    #: 그때는 ``search_text`` 가 마지막이었다. 6-AI 도 **맨 뒤의 선택
    #: 인자**로 더했으므로 기존 호출은 그대로 돈다
    #: (``test_bounded_search_multi_results.py::test_e11`` · ``test_e12``).
    #: 🔴 **Phase 6-AL 이 ``followups_text`` 를 그 뒤에 더했다** — 목표 도달
    #: **뒤**에 더 탐색할 비흐름 행동 수다. 셋 다 **맨 뒤의 선택 인자**이고
    #: 기본값이 빈 문자열이므로, 주지 않으면 앞 단계와 한 글자도 다르지
    #: 않다. 이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 6-AH 에서는
    #: ``search_text`` 가 마지막이었고 6-AI 에서는 ``results_text`` 였다.
    assert list(inspect.signature(SearchService.combo_response).parameters)[-3:] == [
        "search_text", "results_text", "followups_text",
    ]
    for name in ("search_text", "results_text", "followups_text"):
        assert inspect.signature(
            SearchService.combo_response).parameters[name].default == ""

    agent = DeckAgent(repository)
    assert _run_bounded_search(agent, "", [], "") is None
    assert _run_bounded_search(agent, "", [], "   ") is None

    unknown = _run_bounded_search(agent, "", [], "없는목표")
    assert unknown is not None and unknown.ran is False
    assert any("없습니다" in line for line in unknown.brief)
    assert any("비슷한 목표를 골라 주지 않습니다" in line for line in unknown.brief)

    #: 레시피가 없으면 돌리지 않고 그 사실을 적는다.
    no_recipe = _run_bounded_search(agent, "", [GIRSU], "galatea")
    assert no_recipe is not None and no_recipe.ran is False
    assert any("레시피" in line for line in no_recipe.brief)

    assert search_goal_card_id("galatea") == GALATEA
    assert search_goal_card_id("GALATEA") == GALATEA
    assert search_goal_card_id("gala") is None
    assert SEARCH_GOALS["galatea"] == GALATEA


def test_e07_the_written_lines_still_run(repository, growth_input):
    """
    🟢 **기존 검증용 전개 정책이 그대로 돈다** (회귀).

    탐색을 더하면서 ``execute_opening`` 의 기존 경로를 건드리지 않았다 —
    적어 둔 경로가 끝까지 실행되고 갈라테아가 필드에 남는다.
    """
    from deck.combo_policy import line_progress
    from deck.opening import execute_opening

    setup = _setup_for(repository, growth_input)
    from app.main import opening_wiring

    chooser, triggers = opening_wiring(repository, growth_input)
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(growth_input.recipe_ydk, repository)
    with_line = build_opening(
        repository, parsed.draft, list(growth_input.hand),
        chooser=chooser, triggers=triggers,
    )
    run = execute_opening(
        with_line, repository, choose=growth_input.policy()
    )
    progress = line_progress(run, growth_input)
    assert progress.completed, progress.describe_ko()
    assert (Zone.EMZONE.value, GALATEA, True) in own_field(with_line.duel, P0)
    #: 그리고 그 실행은 탐색과 **다른 함수**다 — 하나가 다른 하나를 부르지 않는다.
    assert setup.duel is not with_line.duel


def test_e08_search_for_card_is_the_short_way(repository):
    """🟢 짧은 진입점도 같은 결과를 준다 — 기본 예산으로 한 번."""
    outcome = search_for_card(
        _choice_board(repository),
        GIRSU,
        budget=SearchBudget(max_depth=2, max_nodes=10, max_choice_branches=0),
    )
    assert outcome.goal == FieldGoal(card_id=GIRSU, seat=P0)
    assert outcome.termination is Termination.GOAL_REACHED
    assert (Zone.MZONE.value, GIRSU, True) in outcome.final_field
