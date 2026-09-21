"""
Phase 2-K — 카드 효과가 처음으로 판을 바꾼다.

    ChainLink → ChainResolver → EffectExecutor → GameState 변경
              → StateDelta → EventPipeline

Phase 2-D-2 가 실행기를, 2-F-2 가 체인을, 2-J 가 사건 통로를 만들었다.
**그런데 엔진이 들고 있는 효과 정의가 하나도 없었다.** 이번 단계가 채우는
것은 그 목록이고, 이 파일은 그 목록이 실제로 실행되는지를 본다.

네 가지를 본다.

1. **실제로 카드가 움직이는가.** 욕망의 항아리로 덱 2장이 패로 온다.
2. **세 가지 상태가 섞이지 않는가** — ``TEXT_DERIVED`` / 구현 없음 /
   구현 있음.
3. **실패가 판을 건드리지 않는가.**
4. **체인과 실행기의 책임이 섞이지 않는가.**
"""

import ast
import pathlib

import pytest

from engine.chain import Chain, ChainLink, ChainResolutionStatus, ChainResolver
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.delta import CardDrawn
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    DARK_HOLE,
    EFFECT_LIBRARY,
    POT_OF_GREED,
    LibraryEntry,
    availability,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import DrawOperation, OperationKind
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.event_pipeline import EventPipeline, EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingPoint, TriggerRegistry
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

POT_REF = EffectRef(POT_OF_GREED, 0)
DARK_HOLE_REF = EffectRef(DARK_HOLE, 0)
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 덱을 채우는 용도


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository, deck_size: int = 10) -> GameState:
    """p0 의 필드에 앞면으로 놓인 욕망의 항아리 하나. 덱은 페더맨으로 채운다."""
    game = GameState.create(
        repository,
        decks=([POT_OF_GREED] + [FEATHERMAN] * deck_size, [FEATHERMAN] * 5),
    )
    game.draw(MINE, 1)
    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


@pytest.fixture
def journal() -> EventJournal:
    return EventJournal()


def pot_instance(state: GameState) -> InstanceId:
    return state.player(MINE).spell_zone[0].instance_id


def context_for(state: GameState) -> ResolutionContext:
    return ResolutionContext(
        effect_ref=POT_REF, controller=MINE, source=pot_instance(state)
    )


def resolve_through_chain(
    state: GameState, journal: EventJournal | None = None
):
    """ChainLink 하나를 실제로 해결한다. **이번 단계의 핵심 경로다.**"""
    resolver = ChainResolver(build_executor(journal), definition_registry())
    chain = Chain(
        links=(
            ChainLink(
                sequence=0,
                actor=MINE,
                effect_ref=POT_REF,
                source=pot_instance(state),
            ),
        )
    )
    return resolver.resolve_top(state, chain)


# ======================================================================
# A. EffectRef 로 찾기
# ======================================================================


def test_the_library_holds_what_the_engine_can_read():
    assert entry_for(POT_REF) is not None
    assert entry_for(DARK_HOLE_REF) is not None
    assert entry_for(EffectRef(POT_OF_GREED, 1)) is None
    assert entry_for(EffectRef(1, 0)) is None


def test_every_entry_cites_the_script_it_came_from():
    """근거 없이 적힌 정의는 검증된 의미가 아니라 추측이다."""
    for entry in EFFECT_LIBRARY:
        assert entry.lua_file.endswith(".lua")
        assert entry.lua_excerpt
        assert pathlib.Path(entry.lua_file).is_file(), entry.lua_file


def test_the_effect_ref_is_the_identity_not_the_lua_variable_name():
    """
    ``EffectSpec.index`` (Lua 변수명 ``"e1"``) 는 한 카드 안에서 중복된다.
    목록의 열쇠는 ``EffectRef(card_id, ordinal)`` 이다.
    """
    entry = entry_for(POT_REF)

    assert entry.effect_ref == EffectRef(POT_OF_GREED, 0)
    assert entry.definition.ordinal == 0
    assert entry.definition.source_card_id == POT_OF_GREED
    assert not hasattr(entry.definition, "index")


def test_the_two_registries_answer_different_questions():
    """
    정의가 있다고 실행할 수 있는 것이 아니다 (ADR-006).
    """
    definitions = definition_registry()
    implementations = implementation_registry()

    assert POT_REF in definitions
    assert DARK_HOLE_REF in definitions  # 정의는 둘 다 있다
    assert implementations.has_implementation(POT_REF)
    assert not implementations.has_implementation(DARK_HOLE_REF)


def test_a_ref_that_is_not_in_the_library_has_no_implementation():
    assert availability(EffectRef(1, 0)) is ExecutionAvailability.NO_IMPLEMENTATION


# ======================================================================
# B. 실행 권위 — 세 가지 상태
# ======================================================================


def test_lua_verified_with_an_implementation_may_run():
    assert availability(POT_REF) is ExecutionAvailability.EXECUTABLE
    assert availability(POT_REF).permits_execution is True


def test_lua_verified_without_an_implementation_may_not_run():
    """
    의미는 스크립트에서 확인했지만 옮길 방법이 없다. **금지와 다른 상태다.**
    """
    assert availability(DARK_HOLE_REF) is ExecutionAvailability.NO_IMPLEMENTATION
    assert availability(DARK_HOLE_REF).permits_execution is False


def test_text_derived_may_never_run():
    forbidden = EffectDefinition(
        effect_ref=EffectRef(999999, 0),
        source_card_id=999999,
        operations=(DrawOperation(count=1),),
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    lookup = EffectImplementationRegistry((forbidden.effect_ref,))

    # 구현이 등록되어 **있어도** 금지다 (ADR-004).
    assert execution_availability(forbidden, lookup) is (
        ExecutionAvailability.FORBIDDEN_SOURCE
    )


@requires_official_db
def test_a_text_derived_effect_changes_nothing(state):
    forbidden = EffectDefinition(
        effect_ref=EffectRef(999999, 0),
        source_card_id=999999,
        operations=(DrawOperation(count=2),),
        provenance=EffectProvenance.text_derived("텍스트에서 유추"),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((forbidden.effect_ref,))
    )
    before = state.state_hash()

    result = executor.execute(
        state,
        forbidden,
        ResolutionContext(effect_ref=forbidden.effect_ref, controller=MINE),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert result.missing == "executable implementation from official script"
    assert result.deltas == ()
    assert state.state_hash() == before

    # .. note::
    #    ``result.code`` 는 ``RULE_NOT_IMPLEMENTED`` 다. 금지를 가리키는
    #    ``ValidationCode.EXECUTION_FORBIDDEN`` 이 나중에(2-F-1) 생겼는데
    #    실행기(2-D-2)가 아직 그것을 쓰지 않는다. **판정 자체는 정확하다**
    #    (``status`` 가 ``FORBIDDEN``) — 코드만 덜 구체적이다. DETAIL 로
    #    기록하고 여기서 고치지 않는다.
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED


@requires_official_db
def test_an_effect_without_an_implementation_changes_nothing(state):
    """블랙홀은 목록에 있지만 실행되지 않는다."""
    executor = build_executor()
    definition = entry_for(DARK_HOLE_REF).definition
    before = state.state_hash()

    result = executor.execute(
        state,
        definition,
        ResolutionContext(effect_ref=DARK_HOLE_REF, controller=MINE),
    )

    assert result.status is not ResolutionStatus.RESOLVED
    assert result.deltas == ()
    assert state.state_hash() == before


def test_the_library_refuses_to_mark_a_forbidden_source_executable():
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=EffectDefinition(
                effect_ref=EffectRef(999999, 0),
                source_card_id=999999,
                operations=(DrawOperation(count=1),),
                provenance=EffectProvenance.text_derived(),
            ),
            lua_file="",
            lua_excerpt="없음",
            executable=True,
        )


def test_the_library_refuses_to_run_an_effect_with_nothing_written():
    """빈 효과를 실행하면 "아무 일도 없었는데 해결됐다" 가 된다."""
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=EffectDefinition(
                effect_ref=EffectRef(999999, 0),
                source_card_id=999999,
                provenance=EffectProvenance.official_lua(),
            ),
            lua_file="c999999.lua",
            lua_excerpt="없음",
            executable=True,
        )


def test_an_entry_that_does_not_run_must_say_why():
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=entry_for(DARK_HOLE_REF).definition,
            lua_file="c53129443.lua",
            lua_excerpt="Duel.Destroy",
            executable=False,
            note="",
        )


def test_the_dark_hole_entry_says_exactly_what_is_missing():
    entry = entry_for(DARK_HOLE_REF)

    assert entry.executable is False
    assert "STRUCTURAL-10" in entry.note
    assert entry.definition.is_described is False
    assert OperationKind.DESTROY not in {
        op.kind for op in entry.definition.operations
    }


# ======================================================================
# C. 실제 mutation
# ======================================================================


@requires_official_db
def test_pot_of_greed_actually_draws_two_cards(state):
    """**이 프로젝트에서 카드 효과가 처음으로 판을 바꾸는 지점이다.**"""
    hand_before = len(state.player(MINE).hand)
    deck_before = len(state.player(MINE).deck)
    top_two = [card.instance_id for card in state.player(MINE).deck[:2]]

    result = build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand_before + 2
    assert len(state.player(MINE).deck) == deck_before - 2
    assert [c.instance_id for c in state.player(MINE).hand] == top_two


@requires_official_db
def test_the_drawn_cards_keep_their_identity(state):
    """움직이는 것은 ``CardInstance`` 다. 정의가 아니다."""
    drawn = state.player(MINE).deck[0]
    identity = (drawn.instance_id, drawn.card_id, drawn.owner, drawn.controller)

    build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert state.locate(drawn.instance_id).zone is Zone.HAND
    assert (drawn.instance_id, drawn.card_id, drawn.owner, drawn.controller) == (
        identity
    )


@requires_official_db
def test_the_card_definition_is_untouched(state, repository):
    definition = repository.get(POT_OF_GREED)
    before = (definition.name, definition.type_mask, definition.desc)

    build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert (definition.name, definition.type_mask, definition.desc) == before
    assert repository.get(POT_OF_GREED) is definition


@requires_official_db
def test_only_the_controller_draws(state):
    theirs_before = len(state.player(THEIRS).hand)

    build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert len(state.player(THEIRS).hand) == theirs_before


# ======================================================================
# D. 실패 안전성
# ======================================================================


@requires_official_db
def test_a_deck_that_cannot_pay_two_cards_stops_before_the_draw(repository):
    """
    스크립트의 ``Duel.IsPlayerCanDraw(tp,2)`` 중 덱 장수 부분이다. 조건이
    거짓이면 **한 장도 뽑지 않는다.**
    """
    state = new_state(repository, deck_size=1)
    before = state.state_hash()
    hand_before = len(state.player(MINE).hand)

    result = build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert result.status is not ResolutionStatus.RESOLVED
    assert result.deltas == ()
    assert len(state.player(MINE).hand) == hand_before
    assert state.state_hash() == before


@requires_official_db
def test_every_refusal_leaves_the_board_untouched(state):
    """세 가지 실패 경로 전부에서 판이 그대로다."""
    forbidden = EffectDefinition(
        effect_ref=EffectRef(999999, 0),
        source_card_id=999999,
        operations=(DrawOperation(count=1),),
        provenance=EffectProvenance.text_derived(),
    )
    executor = build_executor()
    before = state.state_hash()

    for definition, ref in (
        (forbidden, forbidden.effect_ref),
        (entry_for(DARK_HOLE_REF).definition, DARK_HOLE_REF),
    ):
        result = executor.execute(
            state, definition, ResolutionContext(effect_ref=ref, controller=MINE)
        )
        assert result.status is not ResolutionStatus.RESOLVED
        assert result.deltas == ()

    assert state.state_hash() == before


@requires_official_db
def test_an_unresolved_result_cannot_be_read_as_success(state):
    result = build_executor().execute(
        state,
        entry_for(DARK_HOLE_REF).definition,
        ResolutionContext(effect_ref=DARK_HOLE_REF, controller=MINE),
    )

    with pytest.raises(TypeError):
        bool(result)


# ======================================================================
# E. 변화 기록과 사건 통로
# ======================================================================


@requires_official_db
def test_the_draw_is_recorded_as_two_changes(state):
    result = build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    assert len(result.deltas) == 2
    for delta in result.deltas:
        assert isinstance(delta, CardDrawn)
        assert delta.player == MINE
        assert (delta.from_zone, delta.to_zone) == (Zone.DECK, Zone.HAND)


@requires_official_db
def test_the_changes_reach_the_event_pipeline(state):
    """§8 — 새 EventBus 를 만들지 않고 2-J 의 통로를 그대로 쓴다."""
    result = build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )

    events = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        result, actor=MINE
    )

    assert len(events) == 2
    assert all(e.point is TimingPoint.CARD_DRAWN for e in events)
    assert [e.context.sequence for e in events] == [0, 1]
    assert all(e.context.actor == MINE for e in events)


@requires_official_db
def test_the_pipeline_can_collect_candidates_from_an_effect(state):
    """
    사건 통로가 효과에도 그대로 열려 있다. 등록된 트리거가 없으므로 후보는
    나오지 않는다 — **그것이 지금의 사실이다.**
    """
    result = build_executor().execute(
        state, entry_for(POT_REF).definition, context_for(state)
    )
    pipeline = EventPipeline(
        GameStateView.from_state(state, viewer=MINE), TriggerRegistry()
    )
    after = state.state_hash()

    observations = pipeline.collect(result, actor=MINE)

    assert len(observations) == 2
    assert all(o.candidates == () for o in observations)
    assert state.state_hash() == after  # 관찰이 판을 바꾸지 않는다


@requires_official_db
def test_the_resolution_is_written_to_the_journal(state, journal):
    executor = build_executor(journal)

    executor.execute(state, entry_for(POT_REF).definition, context_for(state))

    assert len(journal) == 1
    event = list(journal)[0]
    assert event.effect_ref == POT_REF
    assert event.actor == MINE
    assert len(event.deltas) == 2


@requires_official_db
def test_a_refused_effect_writes_nothing_to_the_journal(state, journal):
    build_executor(journal).execute(
        state,
        entry_for(DARK_HOLE_REF).definition,
        ResolutionContext(effect_ref=DARK_HOLE_REF, controller=MINE),
    )

    assert len(journal) == 0


# ======================================================================
# F. 결정론
# ======================================================================


@requires_official_db
def test_the_same_board_and_effect_give_the_same_board(repository):
    first, second = new_state(repository), new_state(repository)
    assert first.state_hash() == second.state_hash()

    build_executor().execute(
        first, entry_for(POT_REF).definition, context_for(first)
    )
    build_executor().execute(
        second, entry_for(POT_REF).definition, context_for(second)
    )

    assert first.state_hash() == second.state_hash()


@requires_official_db
def test_a_clone_resolves_on_its_own(state):
    copy = state.clone()
    before = state.state_hash()

    result = build_executor().execute(
        copy, entry_for(POT_REF).definition, context_for(copy)
    )

    assert result.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == before
    assert len(state.player(MINE).hand) == 0
    assert len(copy.player(MINE).hand) == 2


@requires_official_db
def test_the_result_is_the_same_value_every_time(repository):
    first, second = new_state(repository), new_state(repository)

    left = build_executor().execute(
        first, entry_for(POT_REF).definition, context_for(first)
    )
    right = build_executor().execute(
        second, entry_for(POT_REF).definition, context_for(second)
    )

    assert left.canonical_state() == right.canonical_state()


def test_the_library_itself_is_a_stable_value():
    assert [e.canonical_state() for e in EFFECT_LIBRARY] == [
        e.canonical_state() for e in EFFECT_LIBRARY
    ]
    assert len({e.effect_ref for e in EFFECT_LIBRARY}) == len(EFFECT_LIBRARY)


# ======================================================================
# G. 체인과의 경계
# ======================================================================


@requires_official_db
def test_a_chain_link_actually_resolves_into_a_board_change(state):
    """
    **이번 단계가 잇는 경로 전체다.** 링크 하나가 실제로 카드를 움직인다.
    """
    hand_before = len(state.player(MINE).hand)
    before = state.state_hash()

    resolution = resolve_through_chain(state)

    assert resolution.status is ChainResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == hand_before + 2
    assert state.state_hash() != before


@requires_official_db
def test_the_chain_advances_after_the_link_resolves(state):
    resolution = resolve_through_chain(state)

    assert resolution.chain.resolved_count == 1
    assert resolution.chain.is_complete
    assert len(resolution.chain) == 1  # 링크는 사라지지 않는다


@requires_official_db
def test_the_chain_carries_the_result_of_the_effect(state, journal):
    resolution = resolve_through_chain(state, journal)

    assert resolution.result is not None
    assert resolution.result.status is ResolutionStatus.RESOLVED
    assert len(resolution.result.deltas) == 2
    assert len(journal) == 1  # 체인을 거쳐도 같은 기록이 남는다


@requires_official_db
def test_a_link_whose_definition_is_missing_changes_nothing(state):
    resolver = ChainResolver(build_executor(), definition_registry())
    chain = Chain(
        links=(
            ChainLink(
                sequence=0,
                actor=MINE,
                effect_ref=EffectRef(1, 0),
                source=pot_instance(state),
            ),
        )
    )
    before = state.state_hash()

    resolution = resolver.resolve_top(state, chain)

    assert resolution.status is ChainResolutionStatus.INVALID_CHAIN_LINK
    assert resolution.code is ValidationCode.CHAIN_DEFINITION_UNAVAILABLE
    assert state.state_hash() == before


@requires_official_db
def test_a_link_that_cannot_run_leaves_the_chain_where_it_was(state):
    resolver = ChainResolver(build_executor(), definition_registry())
    chain = Chain(
        links=(
            ChainLink(
                sequence=0,
                actor=MINE,
                effect_ref=DARK_HOLE_REF,
                source=pot_instance(state),
            ),
        )
    )
    before = state.state_hash()

    resolution = resolver.resolve_top(state, chain)

    assert resolution.status is not ChainResolutionStatus.RESOLVED
    assert resolution.chain.resolved_count == 0  # 해결한 것으로 치지 않는다
    assert state.state_hash() == before


def test_the_chain_layer_does_not_apply_effects_itself():
    """
    체인은 "무엇을 언제" 만 정한다. 판을 바꾸는 것은 실행기 하나다.
    """
    tree = ast.parse(pathlib.Path("engine/chain.py").read_text("utf-8"))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("move", "draw", "change_life", "create_instance"):
        assert forbidden not in attributes, f"체인이 {forbidden} 를 부릅니다."


def test_the_executor_does_not_know_about_chains():
    """
    실행기가 체인을 알면 "체인을 거친 해결" 과 "직접 해결" 이 달라진다.
    """
    tree = ast.parse(pathlib.Path("engine/effect/executor.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "engine.chain" not in imported
    assert "engine.priority" not in imported
    assert "engine.timing" not in imported


def test_the_library_does_not_reach_up_into_the_chain_layer():
    """아래에서 위를 부르면 방향이 뒤집힌다."""
    tree = ast.parse(pathlib.Path("engine/effect/library.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for forbidden in (
        "engine.chain",
        "engine.trigger",
        "engine.trigger_chain",
        "engine.event_pipeline",
        "engine.action_execution",
        "engine.normal_summon",
    ):
        assert forbidden not in imported


def test_the_library_makes_no_decisions_about_whether_to_use_an_effect():
    """
    "이 효과를 쓸 것인가" 는 AI 의 질문이다. 목록은 "쓰기로 했다면 무엇이
    일어나는가" 만 안다.

    **낱말이 아니라 코드를 본다.** 예전에는 원문에 ``"choose"`` 가 있는지
    보았는데, 그 검사는 ``ChoiceSpec(chooser=...)`` 처럼 **누가 고르는가를
    규칙으로 적은 자리**까지 잡는다 (``chooser`` 안에 ``choose`` 가 있다).
    고르는 주체를 명세에 적는 것은 목록이 고르는 것이 아니라 카드가 그렇게
    적혀 있다는 뜻이므로, 정의하거나 부르는 **함수 이름**만 본다.
    """
    tree = ast.parse(pathlib.Path("engine/effect/library.py").read_text("utf-8"))

    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name):
            names.add(callee.id)
        elif isinstance(callee, ast.Attribute):
            names.add(callee.attr)

    for forbidden in ("choose", "select_best", "evaluate_value", "score", "policy"):
        assert not any(forbidden in name for name in names), forbidden
    # 무작위도 없다 — 목록은 결정론적이다.
    assert "random" not in pathlib.Path("engine/effect/library.py").read_text("utf-8")


@requires_official_db
def test_the_effect_does_not_pay_a_cost_again(state):
    """
    §11 — 비용은 Phase 2-E 의 계층이 이미 치렀다. 실행기가 다시 치르지
    않는다. 욕망의 항아리는 애초에 비용이 없다.
    """
    definition = entry_for(POT_REF).definition

    assert definition.has_cost is False
    assert definition.cost.is_free is True

    source = pathlib.Path("engine/effect/executor.py").read_text("utf-8")
    assert "CostPayer" not in source
