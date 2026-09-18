"""
Phase 2-F-3-C — 체인에 넣기 전의 정리와 순서.

    TriggerEligibility 여럿 → TriggerOrderer.order() → TriggerOrdering

세 가지를 본다.

1. **무엇이 순서화 대상인가** — ``ELIGIBLE`` 만. ``UNKNOWN`` 은 제외가
   아니라 **따로 보존**한다.
2. **순서가 결정론적이면서 규칙을 사칭하지 않는가** — 입력 순서가 달라도
   같은 결과지만, ``is_rule_ordered`` 는 거짓이다.
3. **체인에 넣지 않고 판을 건드리지 않는가.**
"""

import ast
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from engine.chain import Chain
from engine.condition import Always, ConditionResult, UnimplementedRule
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
    EventJournal,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityHolder, PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollector,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
)
from engine.trigger_order import (
    UNRESOLVED_ORDER_RULES,
    OrderingBasis,
    PlayerRole,
    TriggerGroup,
    TriggerOrdering,
    TriggerOrderer,
)
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
ALPHA, BETA = 1000, 1001
"""서로 다른 두 카드. 둘 다 Lua 에서는 ``e1`` 을 쓸 수 있다."""


# ======================================================================
# 판 · 준비
# ======================================================================


def new_state(turn_player: int = MINE) -> GameState:
    """양쪽 필드에 몬스터 1장씩. 턴 플레이어는 인자로 고른다."""
    game = GameState.create(
        decks=([ALPHA, BETA, ALPHA], [BETA, ALPHA, BETA]), turn_player=turn_player
    )
    game.draw(MINE, 2)
    game.draw(THEIRS, 2)
    for player in (MINE, THEIRS):
        game.move(
            game.player(player).hand[0],
            Zone.MZONE,
            position=Position.FACEUP_ATTACK,
        )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def drawn_event() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(4)))


def candidate(
    card_id: int = ALPHA,
    ordinal: int = 0,
    source: int = 0,
    controller: int = MINE,
    requirement: TriggerRequirement = TriggerRequirement.UNKNOWN,
    point: TimingPoint = TimingPoint.CARD_DRAWN,
) -> TriggerCandidate:
    return TriggerCandidate(
        point=point,
        effect_ref=EffectRef(card_id, ordinal),
        source=InstanceId(source),
        controller=controller,
        status=TriggerStatus.ELIGIBLE,
        requirement=requirement,
    )


def eligibility(
    status: TriggerStatus = TriggerStatus.ELIGIBLE, **kwargs
) -> TriggerEligibility:
    """관문을 거치지 않고 판정 결과만 만든다 — 정리 계층만 시험한다."""
    return TriggerEligibility(candidate(**kwargs), status, gates=())


# ======================================================================
# A~D. 무엇이 순서화 대상인가
# ======================================================================


def test_only_eligible_candidates_are_ordered(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(TriggerStatus.ELIGIBLE, card_id=ALPHA),
            eligibility(TriggerStatus.INELIGIBLE, card_id=BETA),
            eligibility(TriggerStatus.FORBIDDEN, card_id=ALPHA, ordinal=1),
            eligibility(TriggerStatus.UNKNOWN, card_id=BETA, ordinal=1),
        ),
    )

    assert len(ordering) == 1
    assert ordering.canonical_sequence[0].candidate.effect_ref == EffectRef(ALPHA, 0)


def test_ineligible_is_excluded_not_ordered(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(), (eligibility(TriggerStatus.INELIGIBLE),)
    )

    assert ordering.groups == ()
    assert ordering.is_empty is True
    assert len(ordering.excluded) == 1
    assert ordering.excluded[0].status is TriggerStatus.INELIGIBLE


def test_forbidden_is_excluded_not_ordered(view):
    """``TEXT_DERIVED`` 가 정리 계층을 통해 실행 경로로 새지 않는다."""
    ordering = TriggerOrderer(view).order(
        drawn_event(), (eligibility(TriggerStatus.FORBIDDEN),)
    )

    assert ordering.groups == ()
    assert len(ordering.excluded) == 1
    assert ordering.excluded[0].status is TriggerStatus.FORBIDDEN
    assert ordering.canonical_sequence == ()


def test_unknown_is_kept_apart_from_both(view):
    """
    **가장 중요한 구분이다.** 모르는 것을 자동으로 올리지도, "확실히 안
    된다" 와 같은 통에 담지도 않는다.
    """
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(TriggerStatus.UNKNOWN, card_id=ALPHA),
            eligibility(TriggerStatus.INELIGIBLE, card_id=BETA),
        ),
    )

    assert len(ordering.unordered) == 1
    assert ordering.unordered[0].status is TriggerStatus.UNKNOWN
    # 제외 통에 섞이지 않았다.
    assert all(e.status is not TriggerStatus.UNKNOWN for e in ordering.excluded)
    # 승격되지도 않았다.
    assert ordering.canonical_sequence == ()


def test_every_judged_candidate_lands_in_exactly_one_bucket(view):
    judged = tuple(
        eligibility(status, card_id=ALPHA, ordinal=index)
        for index, status in enumerate(
            (
                TriggerStatus.ELIGIBLE,
                TriggerStatus.INELIGIBLE,
                TriggerStatus.UNKNOWN,
                TriggerStatus.FORBIDDEN,
            )
        )
    )

    ordering = TriggerOrderer(view).order(drawn_event(), judged)

    landed = (
        ordering.canonical_sequence + ordering.unordered + ordering.excluded
    )
    assert len(landed) == len(judged)
    assert {e.candidate.identity for e in landed} == {
        e.candidate.identity for e in judged
    }


# ======================================================================
# E. 강제 / 임의
# ======================================================================


def test_mandatory_optional_and_undetermined_stay_in_separate_buckets(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(requirement=TriggerRequirement.MANDATORY, ordinal=0),
            eligibility(requirement=TriggerRequirement.OPTIONAL, ordinal=1),
            eligibility(requirement=TriggerRequirement.UNKNOWN, ordinal=2),
        ),
    )

    group = ordering.group_for(MINE)
    assert [e.candidate.effect_ref.ordinal for e in group.mandatory] == [0]
    assert [e.candidate.effect_ref.ordinal for e in group.optional] == [1]
    assert [e.candidate.effect_ref.ordinal for e in group.undetermined] == [2]
    assert group.size == 3


def test_the_requirement_is_not_collapsed_into_a_boolean():
    """세 갈래가 유지되어야 SEGOC 가 나중에 쓸 수 있다."""
    assert set(TriggerRequirement) == {
        TriggerRequirement.MANDATORY,
        TriggerRequirement.OPTIONAL,
        TriggerRequirement.UNKNOWN,
    }
    group = TriggerGroup(MINE, PlayerRole.TURN_PLAYER)
    for name in ("mandatory", "optional", "undetermined"):
        assert isinstance(getattr(group, name), tuple)


def test_mandatory_is_not_claimed_to_come_before_optional(view):
    """
    ``canonical_sequence`` 가 강제 → 임의 순으로 잇지만, 그것이 **규칙이라고
    주장하지 않는다.** 미정 규칙 목록에 그대로 남아 있다.
    """
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(requirement=TriggerRequirement.OPTIONAL, ordinal=1),
            eligibility(requirement=TriggerRequirement.MANDATORY, ordinal=0),
        ),
    )

    assert ordering.is_rule_ordered is False
    assert any("강제" in rule and "임의" in rule for rule in ordering.unresolved_rules)


# ======================================================================
# F. 컨트롤러와 턴 플레이어
# ======================================================================


def test_controller_and_turn_player_are_different_questions():
    """
    트리거를 가진 사람과 턴인 사람은 다르다. 묶음은 컨트롤러로 나뉘고,
    턴 여부는 ``role`` 이 따로 말한다.
    """
    board = new_state(turn_player=THEIRS)
    view = GameStateView.from_state(board, viewer=MINE)

    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(controller=MINE, source=0, card_id=ALPHA),
            eligibility(controller=THEIRS, source=1, card_id=BETA),
        ),
    )

    assert ordering.turn_player == THEIRS
    assert ordering.group_for(MINE).role is PlayerRole.NON_TURN_PLAYER
    assert ordering.group_for(THEIRS).role is PlayerRole.TURN_PLAYER
    assert ordering.turn_player_group.controller == THEIRS


def test_the_group_order_is_seat_order_not_rule_order():
    """
    **턴 플레이어 묶음을 앞에 놓지 않는다.** 그것이 SEGOC 규칙이고, 여기서
    못박으면 틀린 채로 굳는다. 자리 번호 순으로 내고 ``role`` 로 알려준다.
    """
    board = new_state(turn_player=THEIRS)
    view = GameStateView.from_state(board, viewer=MINE)

    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(controller=THEIRS, source=1, card_id=BETA),
            eligibility(controller=MINE, source=0, card_id=ALPHA),
        ),
    )

    assert [group.controller for group in ordering.groups] == [MINE, THEIRS]
    assert ordering.groups[0].role is PlayerRole.NON_TURN_PLAYER
    assert any("턴 플레이어" in rule for rule in ordering.unresolved_rules)


def test_a_group_refuses_a_trigger_that_is_not_its_own():
    with pytest.raises(TriggerError):
        TriggerGroup(
            MINE,
            PlayerRole.TURN_PLAYER,
            mandatory=(eligibility(controller=THEIRS),),
        )


def test_ordering_never_reads_or_changes_priority(view):
    """우선권은 "누구 차례인가" 이고 턴은 "누구 턴인가" 다. 섞지 않는다."""
    priority = PriorityState.opened(ResponseWindow.RESPONSE, THEIRS)
    before = priority.canonical_state()

    ordering = TriggerOrderer(view).order(drawn_event(), (eligibility(),))

    assert priority.canonical_state() == before
    assert not hasattr(ordering, "holder")
    assert not hasattr(ordering, "priority")
    assert PlayerRole.TURN_PLAYER.value not in {h.value for h in PriorityHolder}

    tree = ast.parse(pathlib.Path("engine/trigger_order.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("engine.priority") for name in modules)


# ======================================================================
# G, M. identity
# ======================================================================


def test_identity_survives_the_ordering(view):
    original = candidate(card_id=ALPHA, ordinal=2, source=7, controller=MINE)
    ordering = TriggerOrderer(view).order(
        drawn_event(), (TriggerEligibility(original, TriggerStatus.ELIGIBLE),)
    )

    kept = ordering.canonical_sequence[0].candidate
    assert kept.identity == original.identity
    assert kept.effect_ref == EffectRef(ALPHA, 2)
    assert kept.source == InstanceId(7)
    assert kept.controller == MINE
    assert ordering.identities == (original.identity,)


def test_two_cards_sharing_a_lua_variable_name_never_collide(view):
    """
    ``EffectSpec.index`` 는 Lua 변수명(``"e1"``)이고 **서로 다른 카드가 같은
    이름을 쓴다** (실측 4,884장에서 중복). identity 가 ``EffectRef`` 이므로
    두 카드의 0번 효과는 섞이지 않는다.
    """
    first = eligibility(card_id=ALPHA, ordinal=0, source=0)
    second = eligibility(card_id=BETA, ordinal=0, source=1)

    ordering = TriggerOrderer(view).order(drawn_event(), (first, second))

    assert len(ordering) == 2
    identities = ordering.identities
    assert len(set(identities)) == 2
    assert {i[1] for i in identities} == {ALPHA, BETA}  # card_id 로 갈린다
    assert {i[2] for i in identities} == {0}  # ordinal 은 같다
    text = json.dumps(ordering.to_dict(), ensure_ascii=False)
    assert "e1" not in text


def test_the_same_card_in_two_places_is_two_candidates(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(card_id=ALPHA, ordinal=0, source=0),
            eligibility(card_id=ALPHA, ordinal=0, source=3),
        ),
    )

    assert len(ordering) == 2
    assert len(set(ordering.identities)) == 2


# ======================================================================
# H~I. 결정론
# ======================================================================


def test_the_input_order_does_not_change_the_result(view):
    judged = [
        eligibility(card_id=BETA, ordinal=1, source=3, requirement=TriggerRequirement.OPTIONAL),
        eligibility(card_id=ALPHA, ordinal=0, source=0, requirement=TriggerRequirement.MANDATORY),
        eligibility(card_id=ALPHA, ordinal=2, source=1, controller=THEIRS),
        eligibility(card_id=BETA, ordinal=0, source=2, requirement=TriggerRequirement.MANDATORY),
    ]
    orderer = TriggerOrderer(view)

    forward = orderer.order(drawn_event(), tuple(judged))
    backward = orderer.order(drawn_event(), tuple(reversed(judged)))
    shuffled = orderer.order(drawn_event(), tuple(judged[2:] + judged[:2]))

    assert forward.canonical_state() == backward.canonical_state()
    assert forward.canonical_state() == shuffled.canonical_state()
    assert forward.identities == backward.identities


def test_each_bucket_is_sorted_by_identity(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(card_id=BETA, ordinal=0, source=2, requirement=TriggerRequirement.MANDATORY),
            eligibility(card_id=ALPHA, ordinal=1, source=0, requirement=TriggerRequirement.MANDATORY),
            eligibility(card_id=ALPHA, ordinal=0, source=1, requirement=TriggerRequirement.MANDATORY),
        ),
    )

    identities = [e.candidate.identity for e in ordering.group_for(MINE).mandatory]
    assert identities == sorted(identities)


def test_the_same_input_gives_the_same_result():
    results = []
    for _ in range(2):
        board = new_state()
        view = GameStateView.from_state(board, viewer=MINE)
        results.append(
            TriggerOrderer(view)
            .order(
                drawn_event(),
                (
                    eligibility(card_id=ALPHA, requirement=TriggerRequirement.MANDATORY),
                    eligibility(card_id=BETA, ordinal=1, source=1, controller=THEIRS),
                ),
            )
            .canonical_state()
        )

    assert results[0] == results[1]


def test_the_result_serializes_to_plain_data(view):
    ordering = TriggerOrderer(view).order(
        drawn_event(),
        (
            eligibility(requirement=TriggerRequirement.MANDATORY),
            eligibility(TriggerStatus.UNKNOWN, card_id=BETA, ordinal=1, source=1),
        ),
    )

    data = ordering.to_dict()
    text = json.dumps(data, ensure_ascii=False)

    assert "0x" not in text and "object at" not in text
    assert data["basis"] == "canonical"
    assert data["is_rule_ordered"] is False
    assert data["unresolved_rules"]
    assert data["groups"][0]["role"] in ("turn_player", "non_turn_player")
    assert len(data["unordered"]) == 1


def test_the_serialization_does_not_depend_on_the_hash_seed():
    snippet = textwrap.dedent(
        """
        import json
        from engine.effect import CardDrawn
        from engine.game_state_view import GameStateView
        from engine.ids import EffectRef, InstanceId
        from engine.state.game_state import GameState
        from engine.trigger import (
            TimingEvent, TimingPoint, TriggerCandidate, TriggerEligibility,
            TriggerRequirement, TriggerStatus,
        )
        from engine.trigger_order import TriggerOrderer
        from engine.vocabulary import Position, Zone

        game = GameState.create(decks=([1000, 1001, 1000], [1001, 1000, 1001]))
        game.draw(0, 2)
        game.draw(1, 2)
        for player in (0, 1):
            game.move(game.player(player).hand[0], Zone.MZONE,
                      position=Position.FACEUP_ATTACK)
        view = GameStateView.from_state(game, viewer=0)

        judged = tuple(
            TriggerEligibility(
                TriggerCandidate(
                    TimingPoint.CARD_DRAWN, EffectRef(card, ordinal),
                    InstanceId(source), controller,
                    status=TriggerStatus.ELIGIBLE, requirement=requirement,
                ),
                TriggerStatus.ELIGIBLE,
            )
            for card, ordinal, source, controller, requirement in (
                (1001, 1, 3, 1, TriggerRequirement.OPTIONAL),
                (1000, 0, 0, 0, TriggerRequirement.MANDATORY),
                (1000, 2, 1, 1, TriggerRequirement.UNKNOWN),
                (1001, 0, 2, 0, TriggerRequirement.MANDATORY),
            )
        )
        ordering = TriggerOrderer(view).order(
            TimingEvent.from_delta(CardDrawn(0, InstanceId(4))), judged
        )
        print(json.dumps([ordering.canonical_state(), ordering.to_dict()],
                         ensure_ascii=False, sort_keys=True))
        """
    )
    outputs = []
    for seed in ("0", "1", "77777"):
        finished = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONHASHSEED=seed),
            cwd=os.getcwd(),
        )
        assert finished.returncode == 0, finished.stderr
        outputs.append(finished.stdout)
    assert len(set(outputs)) == 1


# ======================================================================
# SEGOC 경계
# ======================================================================


def test_the_ordering_never_claims_to_be_the_rule_order(view):
    ordering = TriggerOrderer(view).order(drawn_event(), (eligibility(),))

    assert ordering.basis is OrderingBasis.CANONICAL
    assert ordering.basis.is_rule_order is False
    assert ordering.is_rule_ordered is False
    assert ordering.unresolved_rules == UNRESOLVED_ORDER_RULES
    assert any("SEGOC" in rule for rule in ordering.unresolved_rules)
    assert len(UNRESOLVED_ORDER_RULES) >= 5


def test_no_segoc_machinery_was_smuggled_in():
    import engine.trigger_order as module

    source = pathlib.Path("engine/trigger_order.py").read_text(encoding="utf-8")
    for forbidden in (
        "sort_by_segoc",
        "apply_segoc",
        "SpellSpeed",
        "resolve_order",
        "place_on_chain",
    ):
        assert not hasattr(module, forbidden), forbidden
    assert "missed" not in source.lower()


# ======================================================================
# J~K, N. Mutation safety · 체인 경계
# ======================================================================


def test_ordering_never_touches_the_board_or_the_history(state):
    view = GameStateView.from_state(state, viewer=MINE)
    journal = EventJournal()
    chain = Chain().activate(MINE, EffectRef(ALPHA, 0))

    before = (
        state.state_hash(),
        journal.journal_hash(),
        chain.canonical_state(),
        [(c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()],
    )

    orderer = TriggerOrderer(view)
    for status in TriggerStatus:
        orderer.order(drawn_event(), (eligibility(status),))
    orderer.order(
        drawn_event(),
        tuple(
            eligibility(card_id=card, ordinal=i, source=i, controller=i % 2)
            for i, card in enumerate((ALPHA, BETA, ALPHA, BETA))
        ),
    )

    assert state.state_hash() == before[0]
    assert journal.journal_hash() == before[1]
    assert chain.canonical_state() == before[2]
    assert [
        (c.instance_id, c.zone, c.controller, c.owner) for c in state.all_instances()
    ] == before[3]
    assert len(journal) == 0 and chain.resolved_count == 0


def test_the_ordering_layer_cannot_reach_the_chain(view):
    """
    ``Chain.push`` 도 ``Chain.activate`` 도 부르지 않고 import 하지도 않는다.
    """
    ordering = TriggerOrderer(view).order(drawn_event(), (eligibility(),))

    with pytest.raises(TypeError):
        Chain().push(ordering)
    with pytest.raises(TypeError):
        Chain().push(ordering.canonical_sequence[0])
    with pytest.raises(TypeError):
        Chain().push(ordering.canonical_sequence[0].candidate)

    tree = ast.parse(pathlib.Path("engine/trigger_order.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for forbidden in ("engine.chain", "engine.priority", "engine.payment", "analysis"):
        assert not any(name.startswith(forbidden) for name in modules), forbidden


def test_the_orderer_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        TriggerOrderer(state)


def test_the_result_is_immutable(view):
    ordering = TriggerOrderer(view).order(drawn_event(), (eligibility(),))

    for name, value in [("groups", ()), ("turn_player", THEIRS)]:
        with pytest.raises(Exception):
            setattr(ordering, name, value)
    assert isinstance(ordering.groups, tuple)
    assert isinstance(ordering.canonical_sequence, tuple)
    assert isinstance(ordering.unresolved_rules, tuple)
    with pytest.raises(Exception):
        ordering.groups[0].controller = THEIRS


def test_a_judgment_from_another_event_is_refused(view):
    other = eligibility(point=TimingPoint.CARD_MOVED)
    with pytest.raises(TriggerError):
        TriggerOrderer(view).order(drawn_event(), (other,))


def test_only_eligibility_results_can_be_ordered(view):
    with pytest.raises(TypeError):
        TriggerOrderer(view).order(drawn_event(), (candidate(),))
    with pytest.raises(TypeError):
        TriggerOrderer(view).order("not an event", ())


def test_a_cloned_board_is_unaffected(state):
    copy = state.clone()
    TriggerOrderer(GameStateView.from_state(copy, viewer=MINE)).order(
        drawn_event(), (eligibility(),)
    )

    assert copy.state_hash() == state.state_hash()
    copy.player(MINE).change_life(-100)
    assert copy.state_hash() != state.state_hash()


# ======================================================================
# L. 실제 계층과 이어붙이기
# ======================================================================


def test_the_real_collection_and_judgment_feed_the_ordering(state):
    """
    **세 계층이 실제로 이어지는지** 확인한다. 손으로 만든 판정이 아니라
    수집(F-3-A) → 판정(F-3-B) → 정리(F-3-C) 를 그대로 흘린다.
    """
    view = GameStateView.from_state(state, viewer=MINE)
    before = state.state_hash()

    held = EffectDefinition(
        effect_ref=EffectRef(ALPHA, 0),
        source_card_id=ALPHA,
        operations=(DrawOperation(1),),
        activation=Always(),
        provenance=EffectProvenance.official_lua(),
    )
    blocked = EffectDefinition(
        effect_ref=EffectRef(BETA, 0),
        source_card_id=BETA,
        operations=(DrawOperation(1),),
        activation=Always(ConditionResult.FALSE),
        provenance=EffectProvenance.official_lua(),
    )
    unsure = EffectDefinition(
        effect_ref=EffectRef(ALPHA, 1),
        source_card_id=ALPHA,
        operations=(DrawOperation(1),),
        activation=UnimplementedRule("아직 없는 규칙"),
        provenance=EffectProvenance.official_lua(),
    )
    definitions = EffectDefinitionRegistry((held, blocked, unsure))
    implementations = EffectImplementationRegistry(
        [held.effect_ref, blocked.effect_ref, unsure.effect_ref]
    )
    registry = TriggerRegistry(
        (
            TriggerSpec(
                EffectRef(ALPHA, 0),
                TimingPoint.CARD_DRAWN,
                requirement=TriggerRequirement.MANDATORY,
                activates_from=frozenset({Zone.MZONE}),
            ),
            TriggerSpec(
                EffectRef(BETA, 0),
                TimingPoint.CARD_DRAWN,
                requirement=TriggerRequirement.OPTIONAL,
                activates_from=frozenset({Zone.MZONE, Zone.HAND}),
            ),
            TriggerSpec(
                EffectRef(ALPHA, 1),
                TimingPoint.CARD_DRAWN,
                activates_from=frozenset({Zone.MZONE}),
            ),
        )
    )

    event = drawn_event()
    collection = TriggerCollector(view, registry, definitions).collect(event)
    judged = TriggerEligibilityJudge(view, definitions, implementations).judge_all(
        collection, registry
    )
    ordering = TriggerOrderer(view).order(event, judged)

    # 조건이 참인 것만 묶음에 들어갔다.
    assert all(
        e.status is TriggerStatus.ELIGIBLE for e in ordering.canonical_sequence
    )
    # 조건이 거짓인 것은 제외, 판정 불가는 따로 보존.
    assert any(e.status is TriggerStatus.INELIGIBLE for e in ordering.excluded)
    assert any(e.status is TriggerStatus.UNKNOWN for e in ordering.unordered)
    # 강제/임의 정보가 끝까지 살아 있다.
    group = ordering.group_for(MINE)
    assert group is not None
    assert any(
        e.candidate.effect_ref == EffectRef(ALPHA, 0) for e in group.mandatory
    )
    # 판은 그대로다.
    assert state.state_hash() == before
    assert ordering.is_rule_ordered is False
