"""
Phase 2-O — 대상 지정 효과의 end-to-end 통합.

    정의(라이브러리)  →  후보 수집  →  선택 제공  →  대상 검증
        →  파괴 판정  →  실행  →  Delta  →  Event  →  Journal

**실제 카드 하나**로 끝까지 간다. 싸이크론(5318639) 이다 —
``c5318639.lua`` 가 대상 지정(``EFFECT_FLAG_CARD_TARGET``)과
파괴(``Duel.Destroy``)를 둘 다 분명하게 적어 두었고, 이 엔진이 이미 가진
계층만으로 옮길 수 있는 가장 단순한 대상 효과이기 때문이다.

새로 만든 계층이 없다
---------------------
Phase 2-N 의 :class:`~engine.effect.targeting.TargetResolver` 와 Phase 2-M 의
:class:`~engine.effect.semantics.DestructionRuling` 을 **그대로** 쓴다.
이 파일이 증명하려는 것은 새 기능이 아니라 **이어 붙였을 때도 아무 구분도
무너지지 않는다**는 것이다.

두 경로를 **끝까지 나눠서** 본다
--------------------------------
=========================  ================================================
**실제 카드** (싸이크론)    대상은 통과하고 **파괴 판정에서 멈춘다**
                           (``UNCHECKED_RULES``, 판은 그대로)
**synthetic**              판정을 **명시적으로 받아** 끝까지 간다
                           (묘지 · Delta · Event)
=========================  ================================================

이 둘을 나누지 않으면 두 가지 사실이 한 덩어리가 된다 — "실제 카드의 파괴
규칙을 이 엔진이 모른다" 와 "대상 효과 실행 기반이 작동하지 않는다" 는 다른
문제이고, 앞의 것만 참이다.

실제 카드에는 ``DeclaredDestructionRuling`` 을 **주지 않는다.** 주는 순간
"상대의 저 블랙홀은 파괴될 수 있다" 를 이 저장소가 주장하게 되고, 그것은
공식 근거 없이 실제 카드의 재정을 지어내는 일이다. 판정을 선언해도 되는 곳은
**아무 카드의 의미도 주장하지 않는 synthetic 정의**뿐이다.

AI 는 없다
----------
무엇을 고를지는 테스트가 값으로 준다 (``selected_target = ...``). 엔진은
"이 대상이 적법한가" 만 답한다.
"""

import ast
import pathlib

import pytest

from engine.condition import ConditionResult, IsMonster, IsSpellTrap
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectProvenance,
    EffectSource,
    ExecutionAvailability,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    MYSTICAL_SPACE_TYPHOON,
    LibraryEntry,
    availability,
    build_executor,
    definition_registry,
    entry_for,
)
from engine.effect.operation import CardOperation, OperationKind
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import (
    DeclaredDestructionRuling,
    UnknownDestructionRuling,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    TargetBinding,
    TargetRequirement,
    TargetSpec,
)
from engine.effect.targeting import TargetLegality, TargetResolver
from engine.event_pipeline import EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingEvent, TimingPoint
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

MST = MYSTICAL_SPACE_TYPHOON  # 싸이크론 — 이번 단계의 실제 카드
DARK_HOLE = 53129443  # 블랙홀 — 필드 위의 다른 마법 카드
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 통상 몬스터

SYNTHETIC = 2511  # 라뷰린스 쿠클락 — synthetic 정의의 **껍데기**일 뿐이다

MST_EFFECT = EffectRef(MST, 0)
SYNTHETIC_EFFECT = EffectRef(SYNTHETIC, 0)
PRIMARY = PRIMARY_TARGET


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE)
        SZONE: **싸이크론 (앞면, 발동한 카드)**
        MZONE: 페더맨 (앞면)
        HAND:  싸이크론 1장 · 페더맨 1장
    p1(THEIRS)
        SZONE: 블랙홀 (앞면) · 블랙홀 (**뒷면**)
        MZONE: 페더맨 (앞면)
    """
    game = GameState.create(
        repository,
        decks=(
            [MST] * 2 + [FEATHERMAN] * 10,
            [DARK_HOLE] * 2 + [FEATHERMAN] * 10,
        ),
    )
    game.draw(MINE, 4)  # 싸이크론 · 싸이크론 · 페더맨 · 페더맨
    game.draw(THEIRS, 3)  # 블랙홀 · 블랙홀 · 페더맨

    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.move(
        game.player(MINE).hand[-1], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEUP,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEDOWN,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def the_typhoon(state: GameState) -> InstanceId:
    """필드에 있는 싸이크론 — **발동한 카드 자신**이다."""
    for card in state.player(MINE).spell_zone:
        if card.card_id == MST:
            return card.instance_id
    raise AssertionError("싸이크론이 필드에 없습니다.")


def their_faceup_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


def their_facedown_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[1].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def my_hand_typhoon(state: GameState) -> InstanceId:
    for card in state.player(MINE).hand:
        if card.card_id == MST:
            return card.instance_id
    raise AssertionError("패에 싸이크론이 없습니다.")


def definition() -> EffectDefinition:
    """라이브러리가 들고 있는 **그** 정의. 테스트가 따로 만들지 않는다."""
    return definition_registry().definition_for(MST_EFFECT)


def confirmed(*instances: InstanceId) -> DeclaredDestructionRuling:
    """
    **테스트가 명시적으로 선언한** 파괴 판정 (Phase 2-M 과 같은 도구).

    내성 계층을 대신하지 않는다 — 적히지 않은 카드는 여전히 ``UNKNOWN``
    이고, 그래서 파괴되지 않는다.

    **실제 카드에는 쓰지 않는다.** 실제 카드에 이것을 주면 저장소가 그
    카드의 재정을 공식 근거 없이 주장하게 된다. 쓰는 곳은 아무 카드의
    의미도 주장하지 않는 :func:`synthetic_destroy` 뿐이다.
    """
    return DeclaredDestructionRuling(destructible=frozenset(instances))


def synthetic_destroy() -> EffectDefinition:
    """
    **synthetic 정의**다. "필드의 몬스터 1장을 대상으로 파괴한다" 라는
    모양만 만든다 — 출처가 ``hand_written`` 이라고 적혀 있고, 어떤 실제
    카드의 의미도 주장하지 않는다.

    여기 있는 이유는 하나다. 실제 카드로는 파괴 판정에서 멈추므로,
    **판정을 받았을 때 끝까지 가는지**를 시험할 길이 없다.
    """
    return EffectDefinition(
        effect_ref=SYNTHETIC_EFFECT,
        source_card_id=SYNTHETIC,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}),
                        owner=None,
                        require=IsMonster(),
                    ),
                    minimum=1,
                    maximum=1,
                )
            )
        ),
        operations=(CardOperation.destroy(PRIMARY),),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-O 성공 경로 시험용 synthetic 정의"
        ),
    )


def run_synthetic(
    state: GameState,
    target: InstanceId,
    *,
    destruction=None,
    journal: EventJournal | None = None,
):
    """
    synthetic 정의를 실행한다. 판정기를 주지 않으면 ``UNKNOWN`` 그대로다 —
    synthetic 이라고 해서 판정을 건너뛰지 않는다.
    """
    definition = synthetic_destroy()
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((SYNTHETIC_EFFECT,)),
        journal=journal,
        destruction=destruction,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=SYNTHETIC_EFFECT,
            controller=MINE,
            selections=(TargetSelection(PRIMARY, Selection.of(target)),),
        ),
    )


def context(state: GameState, target: InstanceId | None = None) -> ResolutionContext:
    """
    해결 문맥. ``source`` 는 **발동한 싸이크론 자신**이다 —
    ``exclude_source`` 가 그것을 보고 자기 자신을 후보에서 뺀다.
    """
    selections = (
        (TargetSelection(PRIMARY, Selection.of(target)),) if target is not None else ()
    )
    return ResolutionContext(
        effect_ref=MST_EFFECT,
        controller=MINE,
        source=the_typhoon(state),
        selections=selections,
    )


def run(
    state: GameState,
    target: InstanceId | None,
    *,
    destruction=None,
    journal: EventJournal | None = None,
):
    executor = build_executor(journal=journal, destruction=destruction)
    return executor.execute(state, definition(), context(state, target))


def resolver(state: GameState, viewer: int = MINE) -> TargetResolver:
    return TargetResolver(GameStateView.from_state(state, viewer=viewer))


# ======================================================================
# A. 실제 카드의 정의 — 스크립트가 말한 것만 적혀 있는가
# ======================================================================


def test_the_typhoon_is_in_the_library_with_its_script():
    entry = entry_for(MST_EFFECT)

    assert entry is not None
    assert entry.card_id == 5318639
    assert entry.lua_file == "c5318639.lua"
    assert entry.executable is True
    assert entry.definition.provenance.source is EffectSource.OFFICIAL_LUA
    assert entry.definition.provenance.verified is True


def test_the_script_line_that_decided_the_meaning_is_recorded():
    """근거 없이 적힌 정의는 검증된 의미가 아니라 추측이다."""
    excerpt = entry_for(MST_EFFECT).lua_excerpt

    assert "Duel.SelectTarget" in excerpt
    assert "Duel.Destroy" in excerpt
    assert "IsSpellTrap" in excerpt


def test_the_typhoon_targets_rather_than_merely_choosing():
    """
    ``EFFECT_FLAG_CARD_TARGET`` 은 **대상 지정**이다. 고르기로 적으면
    무효화·회피 규칙을 영영 붙일 수 없다.
    """
    spec = definition().target_spec(PRIMARY)

    assert spec.requirement is TargetRequirement.TARGETING
    assert spec.is_targeting is True


def test_the_definition_says_exactly_what_the_script_said():
    spec = definition().target_spec(PRIMARY)
    choice = spec.choice

    assert (choice.minimum, choice.maximum) == (1, 1)  # SelectTarget(...,1,1,...)
    assert choice.source.owner is None  # LOCATION_ONFIELD 양쪽
    assert choice.source.require == IsSpellTrap()  # s.filter
    assert choice.source.exclude_source is True  # chkc~=e:GetHandler()
    assert choice.source.zones == frozenset(
        {Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.PZONE}
    )


def test_the_only_thing_it_does_is_destroy():
    operations = definition().operations

    assert len(operations) == 1
    assert operations[0].kind is OperationKind.DESTROY
    assert operations[0].target_ref == PRIMARY


def test_no_activation_condition_was_invented():
    """
    스크립트의 ``chk==0`` 은 "대상이 있는가" 이고, 그것은 대상 계층이
    :meth:`TargetResolver.availability` 로 답한다. 발동 조건 칸에 옮겨
    적으면 같은 사실이 두 곳에 갈라져 적힌다.
    """
    assert definition().activation is None


# ======================================================================
# B. 후보 수집 — 스크립트의 필터가 실제로 걸러지는가
# ======================================================================


@requires_official_db
def test_the_faceup_spell_on_the_other_side_is_a_candidate(state):
    found = resolver(state).candidates(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert their_faceup_spell(state) in found.eligible


@requires_official_db
def test_monsters_are_not_candidates(state):
    """``s.filter = c:IsSpellTrap()`` — 몬스터는 걸러진다."""
    found = resolver(state).candidates(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert my_monster(state) not in found.eligible
    assert their_monster(state) not in found.eligible


@requires_official_db
def test_the_typhoon_is_not_a_candidate_for_itself(state):
    """
    ``chkc~=e:GetHandler()`` — 싸이크론도 필드의 마법 카드지만 자기
    자신은 대상이 아니다.
    """
    found = resolver(state).candidates(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert the_typhoon(state) not in found.eligible
    assert the_typhoon(state) not in found.undecided


@requires_official_db
def test_a_spell_in_the_hand_is_not_a_candidate(state):
    """``LOCATION_ONFIELD`` — 패의 싸이크론은 필드에 있지 않다."""
    found = resolver(state).candidates(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert my_hand_typhoon(state) not in found.eligible
    assert my_hand_typhoon(state) not in found.undecided


@requires_official_db
def test_the_facedown_card_is_undecided_not_eligible(state):
    """
    상대의 세트 카드가 마법인지 함정인지 **모른다.** 모르는 것을 확실한
    후보에 넣지 않는다.
    """
    found = resolver(state).candidates(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert their_facedown_spell(state) in found.undecided
    assert their_facedown_spell(state) not in found.eligible


@requires_official_db
def test_there_is_something_to_target(state):
    verdict = resolver(state).availability(
        definition().target_spec(PRIMARY), context(state).condition_context()
    )

    assert verdict.legality is TargetLegality.LEGAL
    assert verdict.permits_selection is True


# ======================================================================
# C. 실제 카드 — 대상은 통과하고, 파괴 판정에서 멈춘다
# ======================================================================


@requires_official_db
def test_the_real_typhoon_stops_at_the_destruction_ruling(state):
    """
    **이것이 지금 이 엔진의 정직한 상태다.**

    대상 계층은 끝까지 통과한다 — 후보도 찾고, 고른 것이 적법하다고
    판정한다. 그런데 "그 카드를 파괴해도 되는가" 를 답할 계층이 없으므로
    ``UNCHECKED_RULES`` 로 멈추고 **판은 한 글자도 바뀌지 않는다.**

    실제 카드에 판정을 선언해 주지 않는 이유는 §8 이다 — 그것은 공식 근거
    없이 재정을 지어내는 일이다.
    """
    card_effect = definition()
    spec = card_effect.target_spec(PRIMARY)
    selected_target = their_faceup_spell(state)

    # 1. 대상 계층은 통과한다.
    found = resolver(state).candidates(spec, context(state).condition_context())
    assert selected_target in found.eligible
    checked = resolver(state).validate(
        spec, Selection.of(selected_target), context(state).condition_context(), PRIMARY
    )
    assert checked.legality is TargetLegality.LEGAL

    # 2. 그런데 실행은 파괴 판정에서 멈춘다.
    before = state.state_hash()
    result = run(state, selected_target)  # 판정기를 주지 않는다 (§1)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.applied == ()
    assert result.deltas == ()
    assert state.locate(selected_target).zone is Zone.SZONE
    assert state.state_hash() == before


@requires_official_db
def test_the_typhoon_says_which_rules_it_could_not_check(state):
    """
    멈춘 이유가 "대상이 틀렸다" 가 아니라 **"파괴 규칙을 모른다"** 임이
    적혀 있어야 한다. 둘을 구분할 수 없으면 무엇을 고쳐야 하는지 알 수 없다.
    """
    result = run(state, their_faceup_spell(state))

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert any("내성" in rule for rule in result.unchecked_rules)
    assert any("대체" in rule for rule in result.unchecked_rules)
    assert result.missing


@requires_official_db
def test_nothing_in_the_repository_declares_the_typhoons_targets_destructible(state):
    """
    §8 — 실제 카드의 파괴 판정을 저장소가 주장하지 않는다. 기본 실행기의
    판정기는 어떤 카드에 대해서도 ``UNKNOWN`` 이다.
    """
    ruling = build_executor().destruction

    assert isinstance(ruling, UnknownDestructionRuling)
    for instance in (
        their_faceup_spell(state),
        their_facedown_spell(state),
        the_typhoon(state),
    ):
        assert ruling.may_be_destroyed(instance) is ConditionResult.UNKNOWN


@requires_official_db
def test_the_facedown_card_is_visible_as_a_seat_but_not_as_an_identity(state):
    view = GameStateView.from_state(state, viewer=MINE)
    card = view.find(their_facedown_spell(state))

    assert card is not None  # 자리는 보인다
    assert card.card_id is None  # 정체는 가려져 있다


# ======================================================================
# D. synthetic — 판정을 받으면 끝까지 간다
# ======================================================================


@requires_official_db
def test_a_confirmed_destruction_runs_the_whole_way_through(state):
    """
    §3 — TargetSpec → 후보 → 선택 → 최종 검증 → DESTROY → 판정 → 이동 →
    Delta → EventReader → ObservedEvent → TimingEvent 를 **실제로** 지난다.
    """
    definition_under_test = synthetic_destroy()
    spec = definition_under_test.target_spec(PRIMARY)
    probe = ResolutionContext(
        effect_ref=SYNTHETIC_EFFECT, controller=MINE
    ).condition_context()

    # 1. 후보를 센다.
    found = resolver(state).candidates(spec, probe)
    # 2. **고르는 것은 엔진이 아니다.**
    selected_target = their_monster(state)
    assert selected_target in found.eligible
    # 3. 고른 것이 적법한가.
    checked = resolver(state).validate(
        spec, Selection.of(selected_target), probe, PRIMARY
    )
    assert checked.legality is TargetLegality.LEGAL

    journal = EventJournal()
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    before = state.state_hash()

    # 4. 판정을 **명시적으로** 주고 실행한다.
    result = run_synthetic(
        state, selected_target, destruction=confirmed(selected_target), journal=journal
    )

    # 5. 판이 바뀌었다.
    assert result.status is ResolutionStatus.RESOLVED
    assert result.code is ValidationCode.OK
    assert state.locate(selected_target).zone is Zone.GRAVE
    assert len(state.player(THEIRS).monster_zone) == 0
    assert state.state_hash() != before
    # 6. **파괴로** 기록되었다.
    assert len(result.applied) == 1
    assert result.applied[0].kind is OperationKind.DESTROY
    assert len(result.deltas) == 1
    assert result.deltas[0].operation is OperationKind.DESTROY
    assert "DESTROY" in result.deltas[0].reason_names
    # 7. 2-J 통로를 그대로 지난다.
    observed = reader.read(result, actor=MINE)
    assert len(observed) == 1
    assert observed[0].is_observable
    assert observed[0].timing.point is TimingPoint.CARD_MOVED
    assert observed[0].timing.operation is OperationKind.DESTROY
    assert (observed[0].timing.from_zone, observed[0].timing.to_zone) == (
        Zone.MZONE,
        Zone.GRAVE,
    )
    # 8. 역사에 남았다.
    assert len(journal) == 1
    assert list(journal)[0].effect_ref == SYNTHETIC_EFFECT
    assert list(journal)[0].applied[0].kind is OperationKind.DESTROY


@requires_official_db
def test_the_destroyed_card_is_the_same_card_afterwards(state):
    """``CardInstance`` 는 자리를 옮겨도 같은 카드다. 새로 만들지 않는다."""
    selected_target = their_monster(state)
    before = state.find_instance(selected_target)
    card_id_before, owner_before = before.card_id, before.owner

    run_synthetic(state, selected_target, destruction=confirmed(selected_target))

    after = state.find_instance(selected_target)
    assert after is not None
    assert after.instance_id == selected_target
    assert after.card_id == card_id_before


@requires_official_db
def test_owner_and_controller_survive_the_destruction(state):
    """
    파괴는 카드를 **옮길** 뿐 주인을 바꾸지 않는다 (ADR: Owner ≠ Controller).
    """
    selected_target = their_monster(state)
    before = state.find_instance(selected_target)
    owner_before, controller_before = before.owner, before.controller

    run_synthetic(state, selected_target, destruction=confirmed(selected_target))

    after = state.find_instance(selected_target)
    assert (after.owner, after.controller) == (owner_before, controller_before)
    assert after.owner == THEIRS


@requires_official_db
def test_the_delta_says_where_the_card_came_from_and_went(state):
    selected_target = their_monster(state)

    result = run_synthetic(
        state, selected_target, destruction=confirmed(selected_target)
    )
    delta = result.deltas[0]

    assert delta.instance == selected_target
    assert (delta.from_zone, delta.to_zone) == (Zone.MZONE, Zone.GRAVE)


@requires_official_db
def test_the_timing_event_carries_the_meaning_not_just_the_move(state):
    """
    ``SEND_TO_GRAVE`` 였다면 목적지가 같아도 다른 사건이다 (ADR-002).
    """
    selected_target = their_monster(state)

    result = run_synthetic(
        state, selected_target, destruction=confirmed(selected_target)
    )
    timing = TimingEvent.from_delta(result.deltas[0])

    assert timing.point is TimingPoint.CARD_MOVED
    assert timing.operation is OperationKind.DESTROY
    assert "DESTROY" in timing.delta.reason_names


@requires_official_db
def test_no_new_event_bus_was_built(state):
    """§5 — 기존 파이프라인을 그대로 쓴다."""
    selected_target = their_monster(state)
    result = run_synthetic(
        state, selected_target, destruction=confirmed(selected_target)
    )

    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    observed = reader.read(result, actor=MINE)

    assert isinstance(observed[0], ObservedEvent)
    assert observed[0].event_id  # 내용에서 나온 안정적인 식별자


@requires_official_db
def test_a_synthetic_effect_without_a_ruling_still_stops(state):
    """
    **synthetic 이라고 판정을 건너뛰지 않는다.** 건너뛰면 이 테스트 묶음이
    "판정이 있어야 파괴된다" 를 증명하지 못한다.
    """
    selected_target = their_monster(state)
    before = state.state_hash()

    result = run_synthetic(state, selected_target)  # destruction 없음

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_synthetic_card_declared_indestructible_is_not_destroyed(state):
    """판정이 ``FALSE`` 면 **틀린 대상**이지 "모름" 이 아니다."""
    selected_target = their_monster(state)
    before = state.state_hash()

    result = run_synthetic(
        state,
        selected_target,
        destruction=DeclaredDestructionRuling(protected=frozenset({selected_target})),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


@requires_official_db
def test_a_ruling_for_another_card_does_not_carry_over(state):
    """
    한 장을 확인했다고 다른 장이 확인된 것이 아니다. 적히지 않은 카드는
    ``UNKNOWN`` 이고, 그래서 파괴되지 않는다.
    """
    selected_target = their_monster(state)
    before = state.state_hash()

    result = run_synthetic(state, selected_target, destruction=confirmed(my_monster(state)))

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert state.state_hash() == before


# ======================================================================
# E. 대상이 틀렸을 때 — 판을 건드리지 않는다 (실제 카드)
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "pick, expected_status",
    [
        ("monster", ResolutionStatus.INVALID_TARGET),
        ("self", ResolutionStatus.INVALID_TARGET),
        ("hand", ResolutionStatus.INVALID_TARGET),
        ("facedown", ResolutionStatus.UNCHECKED_TARGET),
    ],
)
def test_an_illegal_or_unknown_target_changes_nothing(state, pick, expected_status):
    picks = {
        "monster": their_monster,
        "self": the_typhoon,
        "hand": my_hand_typhoon,
        "facedown": their_facedown_spell,
    }
    selected_target = picks[pick](state)
    before = state.state_hash()

    result = run(state, selected_target)

    assert result.status is expected_status
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_facedown_target_is_unknown_not_illegal(state):
    """
    **모르는 것과 틀린 것을 합치지 않는다.** 뒤집히면 답이 달라질 수 있다.
    """
    result = run(state, their_facedown_spell(state))

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.INFORMATION_UNAVAILABLE


@requires_official_db
def test_the_target_check_comes_before_the_destruction_gate(state):
    """
    틀린 대상은 파괴 판정까지 가지도 않는다. 두 실패를 섞으면 어느 쪽이
    막았는지 알 수 없다.
    """
    result = run(state, their_monster(state))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.status is not ResolutionStatus.UNCHECKED_RULES


@requires_official_db
def test_choosing_nothing_is_not_the_same_as_having_no_target(state):
    before = state.state_hash()

    result = run(state, None)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_FEW_SELECTED
    assert state.state_hash() == before


@requires_official_db
def test_two_targets_are_refused(state):
    """``SelectTarget(...,1,1,...)`` — 정확히 1장이다."""
    executor = build_executor()
    picked = Selection.of(their_faceup_spell(state), their_facedown_spell(state))
    before = state.state_hash()

    result = executor.execute(
        state,
        definition(),
        ResolutionContext(
            effect_ref=MST_EFFECT,
            controller=MINE,
            source=the_typhoon(state),
            selections=(TargetSelection(PRIMARY, picked),),
        ),
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.TOO_MANY_SELECTED
    assert state.state_hash() == before


@requires_official_db
def test_a_target_that_left_the_field_is_caught_at_execution_time(state):
    """
    §7 — 고른 뒤에 판이 바뀌었다면 **실행 직전에** 다시 본다.

    이것은 ``IsRelateToEffect`` 가 아니다 (STRUCTURAL-50). 같은 자리로
    돌아온 카드를 구분하지 못한다는 사실은 그대로 남는다.
    """
    selected_target = their_faceup_spell(state)
    state.move(state.find_instance(selected_target), Zone.GRAVE, to_player=THEIRS)
    before = state.state_hash()

    result = run(state, selected_target)

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert state.state_hash() == before


@requires_official_db
def test_a_stale_target_stops_a_confirmed_synthetic_destruction_too(state):
    """
    판정을 받았어도 **대상이 이미 필드를 떠났으면** 실행하지 않는다.
    판정은 "파괴해도 되는가" 이지 "아직 거기 있는가" 가 아니다.
    """
    selected_target = their_monster(state)
    state.move(state.find_instance(selected_target), Zone.GRAVE, to_player=THEIRS)
    before = state.state_hash()

    result = run_synthetic(
        state, selected_target, destruction=confirmed(selected_target)
    )

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.deltas == ()
    assert state.state_hash() == before


@requires_official_db
def test_a_target_that_never_existed_is_unknown(state):
    """관측에 없는 카드는 "없다" 가 아니라 **"모른다"** 다."""
    before = state.state_hash()

    result = run(state, InstanceId(9999))

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    assert state.state_hash() == before


# ======================================================================
# F. 실행 권위 — 대상이 맞아도 출처가 금지하면 실행되지 않는다
# ======================================================================


@requires_official_db
def test_a_text_derived_copy_of_the_same_effect_never_runs(state):
    """
    ADR-004 — 같은 대상, 같은 일, **다른 출처**. 출처 검사가 먼저다.
    """
    forged = EffectDefinition(
        effect_ref=MST_EFFECT,
        source_card_id=MST,
        targets=definition().targets,
        operations=definition().operations,
        provenance=EffectProvenance.text_derived("텍스트에서 유추했다고 치자"),
    )
    executor = EffectExecutor(lookup=EffectImplementationRegistry((MST_EFFECT,)))
    before = state.state_hash()

    result = executor.execute(
        state, forged, context(state, their_faceup_spell(state))
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert state.state_hash() == before


@requires_official_db
def test_a_text_derived_effect_is_refused_even_with_a_confirmed_ruling(state):
    """
    파괴 판정을 받아도 **출처가 먼저다.** 판정이 권위를 대신하지 못한다.
    """
    selected_target = their_monster(state)
    forged = EffectDefinition(
        effect_ref=SYNTHETIC_EFFECT,
        source_card_id=SYNTHETIC,
        targets=synthetic_destroy().targets,
        operations=synthetic_destroy().operations,
        provenance=EffectProvenance.text_derived(),
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((SYNTHETIC_EFFECT,)),
        destruction=confirmed(selected_target),
    )
    before = state.state_hash()

    result = executor.execute(
        state,
        forged,
        ResolutionContext(
            effect_ref=SYNTHETIC_EFFECT,
            controller=MINE,
            selections=(TargetSelection(PRIMARY, Selection.of(selected_target)),),
        ),
    )

    assert result.status is ResolutionStatus.FORBIDDEN
    assert state.state_hash() == before


def test_a_text_derived_targeted_entry_cannot_be_registered():
    with pytest.raises(EffectDefinitionError):
        LibraryEntry(
            definition=EffectDefinition(
                effect_ref=MST_EFFECT,
                source_card_id=MST,
                targets=definition().targets,
                operations=definition().operations,
                provenance=EffectProvenance.text_derived(),
            ),
            lua_file="c5318639.lua",
            lua_excerpt="(없음)",
            executable=True,
        )


@requires_official_db
def test_an_unregistered_effect_does_not_run_even_with_a_perfect_target(state):
    """ADR-006 — 의미가 검증되어도 구현이 등록되어 있지 않으면 실행 안 함."""
    executor = EffectExecutor()
    before = state.state_hash()

    result = executor.execute(
        state, definition(), context(state, their_faceup_spell(state))
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


@requires_official_db
def test_an_unregistered_synthetic_effect_does_not_run_either(state):
    """판정을 줘도 등록되지 않은 구현은 실행되지 않는다."""
    selected_target = their_monster(state)
    executor = EffectExecutor(destruction=confirmed(selected_target))
    before = state.state_hash()

    result = executor.execute(
        state,
        synthetic_destroy(),
        ResolutionContext(
            effect_ref=SYNTHETIC_EFFECT,
            controller=MINE,
            selections=(TargetSelection(PRIMARY, Selection.of(selected_target)),),
        ),
    )

    assert result.status is ResolutionStatus.NOT_IMPLEMENTED
    assert state.state_hash() == before


# ======================================================================
# G. 가려진 정보
# ======================================================================


@requires_official_db
def test_the_opponents_view_does_not_leak_the_facedown_identity(state):
    verdict = resolver(state).validate(
        definition().target_spec(PRIMARY),
        Selection.of(their_facedown_spell(state)),
        context(state).condition_context(),
        PRIMARY,
    )

    assert verdict.legality is TargetLegality.UNKNOWN
    assert str(DARK_HOLE) not in str(verdict.to_dict())


@requires_official_db
def test_the_failure_message_names_no_hidden_card(state):
    result = run(state, their_facedown_spell(state))

    assert str(DARK_HOLE) not in result.reason


@requires_official_db
def test_the_owner_of_the_facedown_card_sees_it_as_a_real_candidate(state):
    """
    같은 판이라도 **누가 보는가**에 따라 답이 다르다. 그것은 버그가 아니라
    정보 경계다.
    """
    theirs = TargetResolver(GameStateView.from_state(state, viewer=THEIRS))
    found = theirs.candidates(
        definition().target_spec(PRIMARY),
        ResolutionContext(
            effect_ref=MST_EFFECT, controller=THEIRS, source=the_typhoon(state)
        ).condition_context(),
    )

    assert their_facedown_spell(state) in found.eligible


# ======================================================================
# H. 결정론 · 계층 경계
# ======================================================================


@requires_official_db
def test_the_same_board_gives_the_same_candidates(repository):
    first, second = new_state(repository), new_state(repository)
    spec = definition().target_spec(PRIMARY)

    left = TargetResolver(GameStateView.from_state(first, viewer=MINE)).candidates(
        spec, context(first).condition_context()
    )
    right = TargetResolver(GameStateView.from_state(second, viewer=MINE)).candidates(
        spec, context(second).condition_context()
    )

    assert left.canonical_state() == right.canonical_state()


@requires_official_db
def test_a_clone_refuses_the_typhoon_the_same_way(state):
    copy = state.clone()

    here = run(state, their_faceup_spell(state))
    there = run(copy, their_faceup_spell(copy))

    assert here.status is there.status is ResolutionStatus.UNCHECKED_RULES
    assert state.state_hash() == copy.state_hash()


@requires_official_db
def test_a_clone_destroys_the_same_way(state):
    """성공 경로도 복제본에서 같은 답이 나온다."""
    copy = state.clone()
    target_here, target_there = their_monster(state), their_monster(copy)

    here = run_synthetic(state, target_here, destruction=confirmed(target_here))
    there = run_synthetic(copy, target_there, destruction=confirmed(target_there))

    assert here.status is there.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == copy.state_hash()


@requires_official_db
def test_the_same_destruction_twice_gives_the_same_board(repository):
    """두 판을 따로 세워 같은 일을 시키면 같은 답과 같은 판이 나온다."""
    answers = set()
    for _ in range(3):
        board = new_state(repository)
        target = their_monster(board)
        result = run_synthetic(board, target, destruction=confirmed(target))
        answers.add((result.status, result.code, board.state_hash()))

    assert len(answers) == 1


@requires_official_db
def test_resolving_targets_never_touches_the_board(state):
    before = state.state_hash()
    spec = definition().target_spec(PRIMARY)

    for _ in range(3):
        resolver(state).candidates(spec, context(state).condition_context())
        resolver(state).availability(spec, context(state).condition_context())
        resolver(state).validate(
            spec,
            Selection.of(their_faceup_spell(state)),
            context(state).condition_context(),
            PRIMARY,
        )

    assert state.state_hash() == before


def test_the_library_does_not_pick_targets_for_anyone():
    """
    §4 — 무엇을 고를지는 라이브러리의 질문이 아니다. 정의는 "무엇을
    대상으로 하는가" 만 말한다.
    """
    source = pathlib.Path("engine/effect/library.py").read_text("utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }

    for forbidden in ("choose", "select", "pick", "score", "best_target"):
        assert not any(forbidden in name for name in defined)
    assert "InstanceId" not in source  # 정의에 실제 카드를 박지 않는다


def test_no_second_target_system_was_built():
    """§3 — Phase 2-N 계층을 그대로 쓴다."""
    tree = ast.parse(pathlib.Path("engine/effect/library.py").read_text("utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert defined == {"LibraryEntry"}


def test_the_library_never_reaches_into_the_board():
    """정의는 판을 모른다. 알면 정의가 한 판에 묶인다."""
    tree = ast.parse(pathlib.Path("engine/effect/library.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(module.startswith("engine.state") for module in imported)
    assert "engine.game_state_view" not in imported
    assert "engine.chain" not in imported


def test_no_declared_destruction_ruling_lives_in_the_engine():
    """
    §2 · §8 — 확인된 파괴 판정은 **테스트가 주는 값**이다. 엔진 어디에도
    "이 카드는 파괴될 수 있다" 고 선언된 목록이 없다.
    """
    for path in pathlib.Path("engine").rglob("*.py"):
        source = path.read_text("utf-8")
        if path.name == "semantics.py":
            continue  # 타입이 정의된 곳
        tree = ast.parse(source)
        used = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert "DeclaredDestructionRuling" not in used, path


def test_the_spell_trap_condition_asks_the_question_the_script_asked():
    """
    ``IsSpellTrap`` 을 ``NotMonster`` 로 바꿔 적지 않았다. 필드 위에서는
    값이 같지만 **같은 질문이 아니다**.
    """
    assert IsSpellTrap().to_dict() == {"kind": "is_spell_trap"}
    assert IsSpellTrap().canonical_state() == ("is_spell_trap", None)
