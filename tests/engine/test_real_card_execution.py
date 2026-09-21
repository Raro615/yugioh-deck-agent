"""
Phase 2-W — 실제 카드 실행 범위 (real card execution coverage).

**이 파일의 모든 테스트는 실제 카드를 실행한다** (``@pytest.mark.real_card``).
synthetic 정의는 한 군데(§K 의 ``TEXT_DERIVED`` 갈래)에서만, 그것도 실제
카드의 정의에 출처만 바꿔 끼우는 방식으로 쓴다 — 아무 카드의 의미도
지어내지 않는다.

    pytest -m real_card        이 파일 (과 다른 실제 카드 테스트)
    pytest -m "not real_card"  synthetic 만

무엇을 보는가
-------------
Phase 2-M ~ 2-V 가 만든 경로가 **실제 카드에서도 같은 경계를 지키는가**.

    Card → EffectRef → activation → selection → ChainLink → resolution
         → Operation → OperationHandler → GameState → StateDelta
         → ObservedEvent → TimingEvent

"많이 실행했는가" 가 아니라 "경계가 그대로인가" 를 본다. 그래서 여기에는
**실행되지 않는 실제 카드**도 들어 있다 — 싸이크론은 파괴 관문에서 멈추고,
강제 탈출 장치 · 로스트 · 죽은 자의 소생 · 블랙홀은 아예 실행되지 않는다.
그것이 지금의 정직한 상태다.
"""

import pathlib

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.cost import Selection
from engine.effect.definition import (
    EffectProvenance,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.delta import CardDrawn, LifeChanged, ZoneMoved
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    COMPULSORY_EVACUATION_DEVICE,
    FOOLISH_BURIAL,
    DARK_HOLE,
    DIAN_KETO,
    DISAPPEAR,
    EFFECT_LIBRARY,
    FINE,
    MONSTER_REBORN,
    MYSTICAL_SPACE_TYPHOON,
    POT_OF_GREED,
    RAIN_OF_MERCY,
    SELF_MUMMIFICATION,
    THE_GIFT_OF_GREED,
    UPSTART_GOBLIN,
    availability,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import OperationKind
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import DeclaredDestructionRuling
from engine.effect.target import PRIMARY_TARGET
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingPoint, TriggerSpec
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = [requires_official_db, pytest.mark.real_card]

MINE, THEIRS = 0, 1
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 판을 채우는 통상 몬스터
GRANTED = ValidationResult.valid()
"""
발동 허가를 **밖에서** 준다.

``ActionValidator`` 는 ``ACTIVATE_EFFECT`` 에 아직 ``UNKNOWN`` 을 돌려준다
(발동 타이밍 계층이 없다). 그것을 여기서 ``VALID`` 로 바꾸는 것이 아니라,
"허가가 이미 났다고 치고 그 다음이 맞는가" 를 보는 것이다 — Phase 2-Q 의
``authorization=`` 이 그 자리다.
"""

#: 이번 단계에서 실행되는 실제 카드들.
NEW_CARDS = (DIAN_KETO, THE_GIFT_OF_GREED, UPSTART_GOBLIN, SELF_MUMMIFICATION, FINE)
#: 앞 단계까지의 실행 가능 카드들.
OLD_CARDS = (POT_OF_GREED, RAIN_OF_MERCY, MYSTICAL_SPACE_TYPHOON)


# ======================================================================
# 판 만들기
# ======================================================================


def new_state(repository) -> GameState:
    """
    p0(MINE) MZONE: 페더맨 / 패: 페더맨 3장 / 덱: 실행 대상 카드들 + 페더맨
    p1(THEIRS) SZONE: 싸이크론의 대상이 될 블랙홀 (앞면)
               MZONE: 페더맨 / 패: 페더맨 3장 (가려짐)

    **마법 / 함정 존은 비워 둔다.** 칸이 5개뿐인데 실행 가능한 실제 카드가
    8장이므로 전부 늘어놓을 수 없다 — 발동하는 카드만 :func:`source_of` 가
    그때 꺼내 놓는다.
    """
    game = GameState.create(
        repository,
        decks=(
            list(OLD_CARDS + NEW_CARDS) + [FEATHERMAN] * 20,
            [DARK_HOLE] + [FEATHERMAN] * 20,
        ),
    )
    game.draw(MINE, 4)  # 페더맨은 덱 뒤쪽에 있으므로 실제 카드가 먼저 온다
    while any(card.card_id != FEATHERMAN for card in game.player(MINE).hand):
        for card in game.player(MINE).hand:
            if card.card_id != FEATHERMAN:
                game.move(card.instance_id, Zone.DECK, to_player=MINE)
                break
        game.draw(MINE, 1)
    game.draw(THEIRS, 5)
    game.move(
        game.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
        position=Position.FACEUP_ATTACK,
    )
    game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, to_player=THEIRS,
        position=Position.FACEUP,
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


def source_of(state: GameState, card_id: int) -> InstanceId:
    """
    발동하는 그 카드 자신. 아직 필드에 없으면 **덱에서 꺼내 앞면으로
    놓는다.**

    카드가 어떻게 필드에 왔는가는 이 단계의 관심이 아니다 (세트 · 발동
    타이밍은 Phase 2-S 와 그 다음의 일이다). 여기서 보는 것은 "발동할 수
    있는 자리에 있는 카드가 해결되면 무엇이 일어나는가" 다.
    """
    for card in state.player(MINE).spell_zone:
        if card.card_id == card_id:
            return card.instance_id
    for card in state.player(MINE).deck:
        if card.card_id == card_id:
            state.move(
                card.instance_id, Zone.SZONE, to_player=MINE,
                position=Position.FACEUP,
            )
            return card.instance_id
    raise AssertionError(f"덱에도 필드에도 {card_id} 가 없습니다.")


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def their_monster(state: GameState) -> InstanceId:
    return state.player(THEIRS).monster_zone[0].instance_id


def their_spell(state: GameState) -> InstanceId:
    return state.player(THEIRS).spell_zone[0].instance_id


def their_hand(state: GameState) -> InstanceId:
    return state.player(THEIRS).hand[0].instance_id


def my_hand(state: GameState, count: int = 1) -> tuple[InstanceId, ...]:
    return tuple(card.instance_id for card in state.player(MINE).hand[:count])


# ======================================================================
# 실제 경로 — 발동 → 체인 → 해결
# ======================================================================


def activate(
    state: GameState,
    card_id: int,
    *chosen: InstanceId,
    journal: EventJournal | None = None,
    destruction=None,
):
    """
    **기존 경로를 우회하지 않는다.** 실행기를 직접 부르지 않는다.

    ``EffectActivator`` (2-Q) → ``Chain`` (2-F-2) → ``ChainResolver`` →
    ``EffectExecutor`` (2-D-2) 를 그대로 지난다.
    """
    registry = definition_registry()
    activator = EffectActivator(registry, implementation_registry())
    effect_ref = EffectRef(card_id, 0)
    selections = (
        (TargetSelection(PRIMARY_TARGET, Selection.of(*chosen)),) if chosen else ()
    )
    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source_of(state, card_id), effect_ref=effect_ref
        ),
        selections,
        authorization=GRANTED,
    )
    if activated.status is not ActivationStatus.ACTIVATED:
        return activated, None
    resolver = ChainResolver(
        build_executor(journal, destruction=destruction), registry
    )
    return activated, resolver.resolve_top(state, activated.chain)


def events_of(state: GameState, result, viewer: int = MINE):
    return EventReader(GameStateView.from_state(state, viewer=viewer)).read(
        result, actor=MINE
    )


def resolve_directly(
    state: GameState,
    card_id: int,
    *chosen: InstanceId,
    provenance: EffectProvenance | None = None,
    effect_ref: EffectRef | None = None,
    registered: bool = True,
):
    """
    실패 갈래를 보기 위해 **해결만** 부른다.

    발동을 건너뛰는 것이 아니라, 발동이 이미 끝난 뒤의 한 걸음을 따로
    보는 것이다. 정의는 언제나 실제 카드의 것이다.
    """
    definition = entry_for(EffectRef(card_id, 0)).definition
    if provenance is not None:
        definition = definition.__class__(
            effect_ref=definition.effect_ref,
            source_card_id=definition.source_card_id,
            targets=definition.targets,
            operations=definition.operations,
            cost=definition.cost,
            activation=definition.activation,
            provenance=provenance,
        )
    executor = EffectExecutor(
        lookup=(
            EffectImplementationRegistry((definition.effect_ref,))
            if registered
            else None
        )
    )
    selections = (
        (TargetSelection(PRIMARY_TARGET, Selection(chosen=tuple(chosen))),)
        if chosen
        else ()
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=effect_ref or definition.effect_ref,
            controller=MINE,
            selections=selections,
        ),
    )


# ======================================================================
# A. 조사 결과 (§1 · §2 · §13)
# ======================================================================


def test_a_the_library_is_exactly_thirteen_real_cards():
    """
    **이것이 전부라는 것이 사실이다.** 14,127장 중 여기 있는 것만
    실행되고, 늘어나면 이 단언이 깨진다 — 그것이 이 테스트의 일이다.
    Phase 2-X 에서 어리석은 매장(81439173)이 더해지며 실제로 깨졌다.
    """
    assert len(EFFECT_LIBRARY) == 13
    assert {entry.card_id for entry in EFFECT_LIBRARY} == {
        POT_OF_GREED, RAIN_OF_MERCY, MYSTICAL_SPACE_TYPHOON,
        DARK_HOLE, MONSTER_REBORN,
        DIAN_KETO, THE_GIFT_OF_GREED, UPSTART_GOBLIN,
        SELF_MUMMIFICATION, FINE,
        COMPULSORY_EVACUATION_DEVICE, DISAPPEAR,
        FOOLISH_BURIAL,  # Phase 2-X — 관문을 선언하는 첫 실제 카드
    }


def test_a_nine_real_effect_refs_are_executable():
    """
    §1 — ``LUA_VERIFIED`` + ``EffectRef`` + 등록된 구현. **이 셋이 다
    맞을 때만** ``EXECUTABLE`` 이다 (ADR-006).

    ``EXECUTABLE`` 은 "실행 권위가 있다" 이지 "해결이 성공한다" 가
    아니다. 아홉 장 중 싸이크론은 파괴 관문에서, 어리석은 매장은 덱을
    관측할 수 없어서 멈춘다 — 둘 다 ``EXECUTABLE`` 이다.
    """
    executable = {
        entry.effect_ref
        for entry in EFFECT_LIBRARY
        if availability(entry.effect_ref) is ExecutionAvailability.EXECUTABLE
    }

    assert executable == {
        EffectRef(cid, 0) for cid in OLD_CARDS + NEW_CARDS + (FOOLISH_BURIAL,)
    }
    assert len(executable) == 9


def test_a_every_declined_card_says_what_is_missing():
    """
    실행하지 않는 실제 카드를 **빼 버리지 않는다.** 빼면 "왜 못 하는가" 가
    사라진다. 넷이 남아 있고 넷 다 이유를 들고 있다.
    """
    declined = {
        entry.card_id: entry.note
        for entry in EFFECT_LIBRARY
        if not entry.executable
    }

    assert set(declined) == {
        DARK_HOLE,  # 파괴 의미 + 존 전체 일괄 처리
        MONSTER_REBORN,  # IsCanBeSpecialSummoned + 표시 형식
        COMPULSORY_EVACUATION_DEVICE,  # IsAbleToHand
        DISAPPEAR,  # IsAbleToRemove
    }
    for card_id, note in declined.items():
        assert note, card_id
        assert availability(EffectRef(card_id, 0)) is (
            ExecutionAvailability.NO_IMPLEMENTATION
        )
    # 막고 있는 것이 **관문 계층**이라는 것을 두 카드가 이름으로 말한다.
    assert "IsAbleToHand" in declined[COMPULSORY_EVACUATION_DEVICE]
    assert "IsAbleToRemove" in declined[DISAPPEAR]
    assert "IsCanBeSpecialSummoned" in declined[MONSTER_REBORN]


def test_a_operation_coverage_by_real_cards():
    """
    §13 — 종류마다 **실제 카드 / synthetic 전용 / 아직 못 함** 을 나눈다.
    B 와 C 를 A 로 억지로 옮기지 않는다.
    """
    by_real = {
        operation.kind
        for entry in EFFECT_LIBRARY
        if entry.executable
        for operation in entry.definition.operations
    }

    # A. 실제 카드가 쓰는 종류
    assert by_real == {
        OperationKind.DRAW,  # 욕망의 항아리 · 욕망의 선물 · 갑부 고블린
        OperationKind.CHANGE_LIFE,  # 은혜의 단비 · 다이안 켓 · 갑부 고블린
        OperationKind.DESTROY,  # 싸이크론 — 관문에서 멈춘다
        OperationKind.SEND_TO_GRAVE,  # 육신보살 (Phase 2-W)
        OperationKind.DISCARD,  # 벌금 (Phase 2-W)
    }
    # B. synthetic 으로만 검증된 종류 (STRUCTURAL-66)
    assert not by_real & {
        OperationKind.BANISH,
        OperationKind.RELEASE,
        OperationKind.RETURN_TO_HAND,
        OperationKind.RETURN_TO_DECK,
        OperationKind.SPECIAL_SUMMON,
    }
    # C. 실제 카드가 될 수 없는 것 · 실행되지 않는 것
    assert OperationKind.MOVE not in by_real  # 설계상 불가
    assert OperationKind.UNKNOWN not in by_real


# ======================================================================
# B. 실제 카드 A — 치료의 신 다이안 켓 (CHANGE_LIFE)
# ======================================================================


def test_b_dian_keto_recovers_exactly_one_thousand(state):
    """
    "①: 자신은 1000 LP 회복한다." — 대상도 비용도 조건도 없는 가장 단순한
    실제 카드다.
    """
    before = (state.player(MINE).life_points, state.player(THEIRS).life_points)

    activated, resolved = activate(state, DIAN_KETO)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert resolved.result.status is ResolutionStatus.RESOLVED
    assert [a.kind for a in resolved.result.applied] == [OperationKind.CHANGE_LIFE]
    assert (state.player(MINE).life_points, state.player(THEIRS).life_points) == (
        before[0] + 1000,
        before[1],  # **상대는 그대로다** — 은혜의 단비와 다른 점이다
    )


def test_b_dian_keto_leaves_one_life_changed_delta(state):
    _, resolved = activate(state, DIAN_KETO)
    (delta,) = resolved.result.deltas

    assert isinstance(delta, LifeChanged)
    assert delta.player == MINE
    assert delta.after - delta.before == 1000

    (event,) = events_of(state, resolved.result)
    assert event.timing.point is TimingPoint.LIFE_CHANGED


# ======================================================================
# C. 실제 카드 B — 욕망의 선물 (DRAW, 상대가 뽑는다)
# ======================================================================


def test_c_the_gift_of_greed_makes_the_opponent_draw(state):
    """
    "상대는 덱에서 카드를 2장 드로우한다."

    욕망의 항아리와 **같은 일을 다른 사람이** 한다. 새 조작을 만들지
    않았다 — ``DrawOperation.who`` 하나로 갈린다.
    """
    mine_before = len(state.player(MINE).hand)
    theirs_before = len(state.player(THEIRS).hand)

    activated, resolved = activate(state, THE_GIFT_OF_GREED)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.result.status is ResolutionStatus.RESOLVED
    assert len(state.player(MINE).hand) == mine_before  # 내 패는 그대로
    assert len(state.player(THEIRS).hand) == theirs_before + 2

    assert all(isinstance(d, CardDrawn) for d in resolved.result.deltas)
    assert {d.player for d in resolved.result.deltas} == {THEIRS}


def test_c_the_gift_of_greed_needs_two_cards_in_the_opponents_deck(repository):
    """
    발동 조건은 **상대** 덱을 본다 (``Duel.IsPlayerCanDraw(1-tp,2)``).
    내 덱이 아무리 두꺼워도 상대 덱이 얇으면 발동하지 않는다.
    """
    state = new_state(repository)
    state.draw(THEIRS, len(state.player(THEIRS).deck) - 1)  # 상대 덱 1장만 남긴다

    activated, resolved = activate(state, THE_GIFT_OF_GREED)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert resolved is None


# ======================================================================
# D. 실제 카드 C — 갑부 고블린 (DRAW + CHANGE_LIFE)
# ======================================================================


def test_d_upstart_goblin_runs_two_different_operations_in_order(state):
    """
    "①: 자신은 덱에서 1장 드로우한다. 그 후, 상대는 1000 LP 회복한다."

    **한 효과가 서로 다른 두 종류의 일을 한다** — 이 목록에서 처음이다.
    순서도 정의가 적은 그대로다.
    """
    hand_before = len(state.player(MINE).hand)
    opponent_before = state.player(THEIRS).life_points

    activated, resolved = activate(state, UPSTART_GOBLIN)

    assert activated.status is ActivationStatus.ACTIVATED
    assert [a.kind for a in resolved.result.applied] == [
        OperationKind.DRAW,
        OperationKind.CHANGE_LIFE,
    ]
    assert len(state.player(MINE).hand) == hand_before + 1
    assert state.player(THEIRS).life_points == opponent_before + 1000


def test_d_upstart_goblin_takes_two_different_handlers(state):
    """
    §5 — 두 일이 **표에서 서로 다른 수행기**로 간다. 같은 실행기 안에서
    갈라지지만 코드가 갈라지지는 않는다 (Phase 2-V).
    """
    from engine.effect.executor import OPERATION_HANDLERS

    _, resolved = activate(state, UPSTART_GOBLIN)
    handlers = {OPERATION_HANDLERS[a.kind].apply for a in resolved.result.applied}

    assert len(handlers) == 2
    assert [type(d).__name__ for d in resolved.result.deltas] == [
        "CardDrawn",
        "LifeChanged",
    ]
    assert [e.timing.point for e in events_of(state, resolved.result)] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.LIFE_CHANGED,
    ]


def test_d_upstart_goblin_does_nothing_at_all_when_the_deck_is_empty(repository):
    """
    덱이 비면 드로우도 회복도 **둘 다** 일어나지 않는다.

    Lua 는 ``if Duel.Draw(...)>0 then ... end`` 로 이어 붙였는데, 이
    실행기는 계획을 전부 마친 뒤에 적용하므로 같은 결과에 다른 경로로
    닿는다 (STRUCTURAL-67). 발동 조건이 먼저 걸린다.
    """
    state = new_state(repository)
    source_of(state, UPSTART_GOBLIN)  # 카드를 내놓는 것은 준비다
    state.draw(MINE, len(state.player(MINE).deck))
    before = state.state_hash()

    activated, resolved = activate(state, UPSTART_GOBLIN)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert resolved is None
    assert state.state_hash() == before


# ======================================================================
# E. 실제 카드 D — 육신보살 (SEND_TO_GRAVE, 대상 지정)
# ======================================================================


def test_e_self_mummification_sends_the_targeted_monster_to_the_graveyard(state):
    """
    "자신 필드 위에 존재하는 몬스터 1장을 선택하고 묘지로 보낸다."

    **파괴가 아니다.** 같은 묘지로 가지만 ``Duel.SendtoGrave`` 이고,
    그래서 ``REASON_NAMES`` 에 ``DESTROY`` 가 없다 (ADR-002).
    """
    target = my_monster(state)

    activated, resolved = activate(state, SELF_MUMMIFICATION, target)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.result.status is ResolutionStatus.RESOLVED
    (applied,) = resolved.result.applied
    assert applied.kind is OperationKind.SEND_TO_GRAVE
    assert applied.reason_names == ("EFFECT",)
    assert "DESTROY" not in applied.reason_names
    assert state.locate(target).zone is Zone.GRAVE


def test_e_self_mummification_needs_no_destruction_ruling(state):
    """
    §7 — 파괴가 아니므로 **파괴 판정을 묻지 않는다.** 싸이크론은 같은
    자리에서 멈추는데 이 카드는 지나간다. 그 차이가 ADR-002 다.
    """
    _, resolved = activate(state, SELF_MUMMIFICATION, my_monster(state))
    assert resolved.result.status is ResolutionStatus.RESOLVED

    _, typhoon = activate(state, MYSTICAL_SPACE_TYPHOON, their_spell(state))
    assert typhoon.result.status is ResolutionStatus.UNCHECKED_RULES


def test_e_self_mummification_cannot_take_the_opponents_monster(state):
    """
    ``Duel.SelectTarget(tp,nil,tp,LOCATION_MZONE,0,...)`` — 뒤의 ``0`` 이
    "상대 쪽은 보지 않는다" 다. 그 자리가 ``owner=CONTROLLER`` 로 왔다.

    **발동 단계에서 막힌다.** 대상 판정은 해결이 아니라 발동의 일이므로
    (Phase 2-Q), 체인에 아무것도 올라가지 않는다. 같은 거절을 해결
    단계에서도 하는지는 §K 가 따로 본다 — 두 관문이 **둘 다** 있어야
    하나가 새어도 판이 상하지 않는다.
    """
    source_of(state, SELF_MUMMIFICATION)
    before = state.state_hash()

    activated, resolved = activate(state, SELF_MUMMIFICATION, their_monster(state))

    assert activated.status is ActivationStatus.INVALID_TARGET
    assert resolved is None
    assert len(activated.chain) == 0
    assert state.state_hash() == before

    # 해결 단계도 같은 답을 낸다 (발동을 건너뛰고 불러도).
    later = resolve_directly(state, SELF_MUMMIFICATION, their_monster(state))
    assert later.status is ResolutionStatus.INVALID_TARGET
    assert later.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


# ======================================================================
# F. 실제 카드 E — 벌금 (DISCARD, 두 장 고르기)
# ======================================================================


def test_f_fine_discards_exactly_two_cards_from_the_hand(state):
    """
    "자신은 패를 2장 버린다."

    **여러 장을 한 번에** 다루는 첫 실제 카드다.
    """
    chosen = my_hand(state, 2)
    hand_before = len(state.player(MINE).hand)
    grave_before = len(state.player(MINE).grave)

    activated, resolved = activate(state, FINE, *chosen)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.result.status is ResolutionStatus.RESOLVED
    (applied,) = resolved.result.applied
    assert applied.kind is OperationKind.DISCARD
    assert applied.instances == chosen
    assert len(state.player(MINE).hand) == hand_before - 2
    assert len(state.player(MINE).grave) == grave_before + 2
    for instance in chosen:
        assert state.locate(instance).zone is Zone.GRAVE


def test_f_fine_is_choosing_not_targeting(state):
    """
    스크립트에 ``EFFECT_FLAG_CARD_TARGET`` 이 없다. 규칙상 "대상으로
    한다" 와 **다른 것**이고, 그 구분이 정의에 남아 있다.
    """
    definition = entry_for(EffectRef(FINE, 0)).definition
    (binding,) = definition.targets

    assert binding.spec.requires_selection is True
    assert binding.spec.requirement.value == "choosing"

    typhoon = entry_for(EffectRef(MYSTICAL_SPACE_TYPHOON, 0)).definition
    (target_binding,) = typhoon.targets
    assert target_binding.spec.requirement.value == "targeting"


def test_f_fine_refuses_one_card(state):
    """
    "2장" 은 최소이자 최대다. 한 장만 골라도 **한 장도 버리지 않는다.**
    """
    source_of(state, FINE)
    before = state.state_hash()

    activated, resolved = activate(state, FINE, *my_hand(state, 1))

    # 장수 판정도 발동의 일이다 (Phase 2-Q · 2-C).
    assert activated.status is ActivationStatus.INVALID_TARGET
    assert resolved is None
    assert len(activated.chain) == 0
    assert state.state_hash() == before

    later = resolve_directly(state, FINE, *my_hand(state, 1))
    assert later.status is not ResolutionStatus.RESOLVED
    assert later.applied == ()
    assert later.deltas == ()
    assert state.state_hash() == before


def test_f_fine_needs_two_cards_in_hand(repository):
    """발동 조건 ``IsExistingMatchingCard(...,LOCATION_HAND,0,2,...)``."""
    state = new_state(repository)
    while len(state.player(MINE).hand) > 1:
        state.move(state.player(MINE).hand[0], Zone.REMOVED, to_player=MINE)

    activated, resolved = activate(state, FINE)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert resolved is None


# ======================================================================
# G. 근거 대조 (§1) — 옮긴 줄이 원본에 실제로 있는가
# ======================================================================


@pytest.mark.parametrize("card_id", OLD_CARDS + NEW_CARDS)
def test_g_every_executable_entry_points_at_a_real_script(card_id):
    """
    근거 없이 적힌 정의는 검증된 의미가 아니라 추측이다. 파일이 실제로
    있고, 인용한 호출 이름이 그 파일 안에 있는지 본다.
    """
    entry = entry_for(EffectRef(card_id, 0))
    path = pathlib.Path(entry.lua_file)

    assert path.is_file(), entry.lua_file
    source = path.read_text("utf-8")
    assert f"c{card_id}.lua" == path.name

    # 인용문의 ``Duel.XXX(`` 호출이 전부 원본에 있다.
    import re

    calls = set(re.findall(r"(Duel\.[A-Za-z]+)\(", entry.lua_excerpt))
    assert calls, entry.lua_excerpt
    for call in calls:
        assert call + "(" in source, (card_id, call)


@pytest.mark.parametrize("card_id", OLD_CARDS + NEW_CARDS)
def test_g_every_executable_entry_is_official_and_verified(card_id):
    """§1 — ``LUA_VERIFIED`` 이고 출처가 실행을 금지하지 않는다."""
    definition = entry_for(EffectRef(card_id, 0)).definition

    assert definition.provenance.verified is True
    assert definition.provenance.is_forbidden is False
    assert definition.provenance.source.value == "official_lua"
    assert definition.is_described is True


@pytest.mark.parametrize("card_id", OLD_CARDS + NEW_CARDS)
def test_g_the_card_exists_in_the_official_database(repository, card_id):
    """
    **카드 텍스트를 추측하지 않는다.** 공식 데이터에 그 번호가 있고
    이름과 텍스트를 들고 있는지 확인한다.
    """
    card = repository.get(card_id)

    assert card is not None, card_id
    assert card.name
    assert card.desc


# ======================================================================
# H. DESTROY (§7) — 실제 카드는 관문에서 멈춘다
# ======================================================================


def test_h_the_typhoon_activates_and_then_stops_at_the_gate(state):
    """
    **발동은 되고 해결은 멈춘다.** 실제 카드의 파괴 재정을 지어내지 않는다
    (Phase 2-O).
    """
    target = their_spell(state)
    source_of(state, MYSTICAL_SPACE_TYPHOON)
    before = state.state_hash()

    activated, resolved = activate(state, MYSTICAL_SPACE_TYPHOON, target)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.result.status is ResolutionStatus.UNCHECKED_RULES
    assert resolved.result.applied == ()
    assert resolved.result.deltas == ()
    assert state.locate(target).zone is Zone.SZONE
    assert state.state_hash() == before


def test_h_the_typhoon_runs_only_when_a_ruling_is_given(state):
    """
    §7 의 두 경우를 **한 자리에서** 가른다.

    1. 파괴 규칙을 모름 → ``UNCHECKED_RULES``, 변화 없음 (위 테스트)
    2. 파괴 규칙을 알고 대상도 적법 → 실제 파괴

    두 번째는 **판정을 테스트가 명시적으로 준다.** 저장소가 실제 카드의
    재정을 들고 있는 것이 아니다 — ``UNKNOWN`` 을 ``TRUE`` 로 바꾸는 것과
    밖에서 답을 받는 것은 다르다.
    """
    target = their_spell(state)

    _, resolved = activate(
        state,
        MYSTICAL_SPACE_TYPHOON,
        target,
        destruction=DeclaredDestructionRuling(destructible=frozenset({target})),
    )

    assert resolved.result.status is ResolutionStatus.RESOLVED
    (applied,) = resolved.result.applied
    assert applied.kind is OperationKind.DESTROY
    assert applied.reason_names == ("DESTROY", "EFFECT")
    assert state.locate(target).zone is Zone.GRAVE


def test_h_the_default_executor_declares_no_ruling():
    """
    목록에 실렸다는 사실이 파괴 판정을 대신하지 못한다
    (Phase 2-M · STRUCTURAL-47).
    """
    from engine.effect.semantics import UnknownDestructionRuling

    executor = build_executor()
    assert isinstance(executor._destruction, UnknownDestructionRuling)


# ======================================================================
# I. MOVE 와 의미 있는 이동 (§8)
# ======================================================================


def test_i_no_real_card_may_ever_be_a_bare_move():
    """
    §8 — ``MOVE`` 는 **설계상** 실제 카드가 될 수 없다.
    ``LibraryEntry`` 가 거부한다 (ADR-002).
    """
    from engine.cost import CandidateSource, ChoiceSpec
    from engine.effect.definition import EffectDefinition, EffectDefinitionError
    from engine.effect.library import LibraryEntry
    from engine.effect.operation import MoveOperation
    from engine.effect.target import TargetBinding, TargetSpec

    # 대상까지 제대로 묶어 둔다 — 그래야 정의가 유효해지고, 거부가
    # "대상을 빠뜨렸다" 가 아니라 **MOVE 라서** 라는 것이 드러난다.
    definition = EffectDefinition(
        effect_ref=EffectRef(DIAN_KETO, 9),
        source_card_id=DIAN_KETO,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(source=CandidateSource(zones=frozenset({Zone.MZONE})))
            )
        ),
        operations=(
            MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY_TARGET),
        ),
        provenance=EffectProvenance.official_lua("시험"),
    )

    with pytest.raises(EffectDefinitionError, match="MOVE"):
        LibraryEntry(
            definition=definition,
            lua_file="c84257639.lua",
            lua_excerpt="Duel.Recover(p,d,REASON_EFFECT)",
            executable=True,
        )


def test_i_send_to_grave_and_discard_stay_different_all_the_way(state):
    """
    §8 — 육신보살과 벌금은 **같은 자리로** 카드를 보내지만 다른 일이다.
    그 구분이 ``StateDelta`` 까지 살아 있다.
    """
    _, mummify = activate(state, SELF_MUMMIFICATION, my_monster(state))
    _, fine = activate(state, FINE, *my_hand(state, 2))

    (moved,) = [d for d in mummify.result.deltas if isinstance(d, ZoneMoved)]
    discarded = [d for d in fine.result.deltas if isinstance(d, ZoneMoved)]

    assert moved.movement is OperationKind.SEND_TO_GRAVE
    assert {d.movement for d in discarded} == {OperationKind.DISCARD}
    assert moved.destination_zone is Zone.GRAVE
    assert {d.destination_zone for d in discarded} == {Zone.GRAVE}
    # 목적지가 같아도 movement 가 다르다. 목적지로는 구분할 수 없다.
    assert moved.movement is not discarded[0].movement


def test_i_a_destroy_trigger_does_not_fire_on_either_of_them(state):
    """
    ADR-002 가 실제로 무엇을 막는가. "파괴되었을 때" 를 기다리는 선언이
    묘지로 보내기와 버리기에 **반응하지 않는다**.
    """
    from engine.trigger import TimingEvent

    watcher = TriggerSpec(
        effect_ref=EffectRef(999999, 0),
        point=TimingPoint.CARD_MOVED,
        operations=frozenset({OperationKind.DESTROY}),
    )

    _, mummify = activate(state, SELF_MUMMIFICATION, my_monster(state))
    _, fine = activate(state, FINE, *my_hand(state, 2))

    for result in (mummify.result, fine.result):
        for delta in result.deltas:
            if isinstance(delta, ZoneMoved):
                assert watcher.matches(TimingEvent.from_delta(delta)) is False


# ======================================================================
# J. SPECIAL_SUMMON (§9)
# ======================================================================


def test_j_no_real_card_special_summons_yet():
    """
    §9 — Phase 2-U 가 경로를 열었지만 **실행 가능한 실제 카드가 없다.**
    죽은 자의 소생의 후보 조건이 ``IsCanBeSpecialSummoned`` 이고 그
    계층이 없다 (STRUCTURAL-64). 추측해서 채우지 않는다.
    """
    summoners = [
        entry
        for entry in EFFECT_LIBRARY
        if entry.executable
        and any(
            operation.kind is OperationKind.SPECIAL_SUMMON
            for operation in entry.definition.operations
        )
    ]

    assert summoners == []
    reborn = entry_for(EffectRef(MONSTER_REBORN, 0))
    assert reborn is not None  # 빼 버리지 않는다
    assert reborn.executable is False
    assert "IsCanBeSpecialSummoned" in reborn.note


def test_j_the_summon_path_still_refuses_without_a_ruling():
    """
    §9 — 경로 자체는 살아 있고, 기본 판정기가 **어떤 특수 소환도
    허가하지 않는다** (Phase 2-U).
    """
    from engine.effect.semantics import UnknownSummonRuling

    executor = build_executor()
    assert isinstance(executor._summoning, UnknownSummonRuling)


# ======================================================================
# K. 실패 행렬 (§10) — 실제 카드로
# ======================================================================


def test_k_every_reachable_failure_leaves_the_board_alone(state):
    """
    §10 의 열둘 중 **실제 카드로 닿을 수 있는 열** 을 한 자리에서 돌린다.
    전부 ``applied == ()`` · ``deltas == ()`` · ``state_hash`` 불변.

    닿을 수 없는 둘은 아래 두 테스트가 **왜 닿을 수 없는지**를 적는다.
    """
    cases = {
        # 1. 부적법한 대상 — 육신보살에 상대 몬스터
        "invalid target": lambda: resolve_directly(
            state, SELF_MUMMIFICATION, their_monster(state)
        ),
        # 2. 가려진 대상 — 벌금에 상대 패
        "hidden target": lambda: resolve_directly(
            state, FINE, their_hand(state), my_hand(state)[0]
        ),
        # 3. 떠난 대상 — 아래 _stale 이 따로 잰다 (준비가 판을 흔든다)
        # 4. 대상을 안 골랐다
        "missing target": lambda: resolve_directly(state, SELF_MUMMIFICATION),
        # 5. 모자라게 골랐다 — 벌금은 2장이다
        "insufficient selection": lambda: resolve_directly(
            state, FINE, *my_hand(state, 1)
        ),
        # 6. 없는 카드
        "missing instance": lambda: resolve_directly(
            state, SELF_MUMMIFICATION, InstanceId(9999)
        ),
        # 7. 규칙 미상 — 싸이크론의 파괴 관문
        "unknown rule": lambda: resolve_directly(
            state, MYSTICAL_SPACE_TYPHOON, their_spell(state)
        ),
        # 8. 출처가 금지 — 실제 카드의 정의에 출처만 바꿔 끼운다
        "text derived": lambda: resolve_directly(
            state,
            DIAN_KETO,
            provenance=EffectProvenance.text_derived("텍스트에서 유추했다고 치면"),
        ),
        # 9. 구현 등록 없음
        "implementation missing": lambda: resolve_directly(
            state, DIAN_KETO, registered=False
        ),
        # 10. 다른 효과의 문맥
        "invalid context": lambda: resolve_directly(
            state, DIAN_KETO, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
    }

    answers = {name: _expect_failure(state, name, case) for name, case in cases.items()}
    answers["stale instance"] = _stale(state)

    assert len(answers) == 10

    # 열 갈래가 **일곱** 답으로 갈린다. 겹치는 세 쌍은 겹치는 것이 맞다:
    #
    # * 없는 카드 ≡ 가려진 대상 — 관측 경계 밖에서는 *없는 것*과 *안 보이는
    #   것*을 구분할 수 없다. 구분하면 숨은 정보가 샌다 (§11).
    # * 안 고름 ≡ 모자라게 고름 — 둘 다 "고른 수가 요구보다 적다" 는 같은
    #   사실이다.
    # * 떠난 대상 ≡ 부적법한 대상 — 자리를 떠난 카드는 더 이상 후보가 아니다.
    #
    # 나머지 넷은 서로 다른 답이어야 한다. 뭉개지면 이 단언이 깨진다.
    assert len(set(answers.values())) == 7
    assert len({status for status, _ in answers.values()}) == 6
    assert answers["missing instance"] == answers["hidden target"]
    assert answers["missing target"] == answers["insufficient selection"]
    assert answers["stale instance"] == answers["invalid target"]


def _expect_failure(state: GameState, name: str, invoke) -> tuple:
    before = state.state_hash()
    result = invoke()
    assert result.status is not ResolutionStatus.RESOLVED, name
    assert result.applied == (), name
    assert result.deltas == (), name
    assert state.state_hash() == before, name
    return result.status, result.code


def _stale(state: GameState) -> tuple:
    """
    고른 뒤 그 몬스터가 자리를 떠났다.

    자리를 옮기는 것은 **이 갈래의 준비**이지 실행기의 일이 아니므로,
    판을 재는 자는 이동을 마친 뒤에 찍는다.
    """
    target = my_monster(state)
    state.move(target, Zone.REMOVED, to_player=MINE)
    return _expect_failure(
        state,
        "stale instance",
        lambda: resolve_directly(state, SELF_MUMMIFICATION, target),
    )


def test_k_unsupported_operation_is_unreachable_from_real_cards():
    """
    §10 의 "unsupported operation" 은 **지금 실제 카드로 닿을 수 없다.**

    옮기지 못한 일이 있는 카드는 ``operations=()`` 로 실리고 실행 구현도
    등록되지 않으므로, 실행기에 닿기 전에 ``NOT_IMPLEMENTED`` 에서 멈춘다.
    ``OperationKind.UNKNOWN`` 을 들고 목록에 실린 실제 카드는 없다.

    없는 것을 있는 척 만들지 않는다 — 이 테스트가 그 사실을 고정한다.
    """
    unknown_ops = [
        entry
        for entry in EFFECT_LIBRARY
        if any(
            operation.kind is OperationKind.UNKNOWN
            for operation in entry.definition.operations
        )
    ]

    assert unknown_ops == []
    for card_id in (DARK_HOLE, MONSTER_REBORN, COMPULSORY_EVACUATION_DEVICE, DISAPPEAR):
        entry = entry_for(EffectRef(card_id, 0))
        assert entry.definition.operations == ()
        assert availability(entry.effect_ref) is (
            ExecutionAvailability.NO_IMPLEMENTATION
        )


def test_k_cost_unavailable_is_unreachable_from_real_cards():
    """
    §10 의 "cost unavailable" 도 **지금 실제 카드로 닿을 수 없다.**

    목록의 실제 카드 중 비용이 있는 것이 하나도 없다. 비용 있는 후보
    (압수 c17375316 의 ``Cost.PayLP(1000)``)는 패 공개(``ConfirmCards``)를
    옮길 수 없어서 목록에 넣지 않았다 (Phase 2-W §1).
    """
    for entry in EFFECT_LIBRARY:
        assert entry.definition.has_cost is False, entry.card_id
        assert entry.definition.cost.is_free is True, entry.card_id


def test_k_an_effect_ref_outside_the_library_has_no_implementation():
    """§10 — invalid EffectRef."""
    assert availability(EffectRef(DIAN_KETO, 7)) is (
        ExecutionAvailability.NO_IMPLEMENTATION
    )
    assert availability(EffectRef(1, 0)) is ExecutionAvailability.NO_IMPLEMENTATION
    assert entry_for(EffectRef(DIAN_KETO, 7)) is None


def test_k_a_declined_real_card_cannot_be_activated(state):
    """
    §10 — implementation missing. 강제 탈출 장치는 **발동 단계에서**
    멈춘다. 체인에 아무것도 올라가지 않는다.
    """
    definition = entry_for(EffectRef(COMPULSORY_EVACUATION_DEVICE, 0)).definition
    assert execution_availability(definition, implementation_registry()) is (
        ExecutionAvailability.NO_IMPLEMENTATION
    )

    activator = EffectActivator(definition_registry(), implementation_registry())
    borrowed = source_of(state, POT_OF_GREED)  # 자리를 내놓는 것은 준비다
    before = state.state_hash()
    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE,
            source=borrowed,  # 자리만 빌린다
            effect_ref=EffectRef(COMPULSORY_EVACUATION_DEVICE, 0),
        ),
        (),
        authorization=GRANTED,
    )

    assert activated.status is not ActivationStatus.ACTIVATED
    assert len(activated.chain) == 0
    assert state.state_hash() == before


# ======================================================================
# L. 숨은 정보 (§11)
# ======================================================================


def test_l_a_refusal_never_names_the_opponents_card(state):
    """
    §11 — 상대 패의 카드를 고르면 거절하되, **무엇이었는지 말하지
    않는다.** ``UNKNOWN`` 과 ``INVALID`` 를 구분한다.
    """
    hidden = their_hand(state)
    identity = state.find_instance(hidden).card_id

    result = resolve_directly(state, FINE, hidden, my_hand(state)[0])

    assert result.status is ResolutionStatus.UNCHECKED_TARGET  # 모른다
    assert result.status is not ResolutionStatus.INVALID_TARGET  # 틀렸다가 아니다
    assert result.code is ValidationCode.HIDDEN_CARD

    rendered = repr(result.to_dict()) + (result.reason or "")
    assert str(identity) not in rendered
    assert str(hidden.value) not in rendered


def test_l_a_visible_card_of_the_opponent_is_invalid_not_unknown(state):
    """
    반대쪽도 본다. 상대의 **앞면** 몬스터는 보이므로 "모른다" 가 아니라
    "후보가 아니다" 다. 둘이 뭉개지면 숨은 정보 판정이 무의미해진다.
    """
    result = resolve_directly(state, SELF_MUMMIFICATION, their_monster(state))

    assert result.status is ResolutionStatus.INVALID_TARGET
    assert result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


def test_l_the_opponents_draw_does_not_reveal_what_was_drawn(state):
    """
    욕망의 선물은 **상대가** 뽑는다. 내 눈으로 본 사건에 그 카드의
    정체가 들어 있으면 안 된다.
    """
    _, resolved = activate(state, THE_GIFT_OF_GREED)
    drawn = {d.card for d in resolved.result.deltas if isinstance(d, CardDrawn)}
    identities = {state.find_instance(i).card_id for i in drawn}

    observed = events_of(state, resolved.result, viewer=MINE)
    rendered = repr([event.to_dict() for event in observed])

    for identity in identities:
        assert str(identity) not in rendered


# ======================================================================
# M. 결정론 (§12)
# ======================================================================


CHOOSERS = {
    DIAN_KETO: lambda s: (),
    THE_GIFT_OF_GREED: lambda s: (),
    UPSTART_GOBLIN: lambda s: (),
    SELF_MUMMIFICATION: lambda s: (my_monster(s),),
    FINE: lambda s: my_hand(s, 2),
    POT_OF_GREED: lambda s: (),
    RAIN_OF_MERCY: lambda s: (),
    MYSTICAL_SPACE_TYPHOON: lambda s: (their_spell(s),),
}


@pytest.mark.parametrize("card_id", OLD_CARDS + NEW_CARDS)
def test_m_the_same_card_on_the_same_board_gives_the_same_answer(
    repository, card_id
):
    """§12 — 같은 판 · 같은 효과 · 같은 선택 → 같은 결과와 같은 판."""
    first, second = new_state(repository), new_state(repository)

    _, left = activate(first, card_id, *CHOOSERS[card_id](first))
    _, right = activate(second, card_id, *CHOOSERS[card_id](second))

    assert left.result.canonical_state() == right.result.canonical_state()
    assert first.state_hash() == second.state_hash()


@pytest.mark.parametrize("card_id", OLD_CARDS + NEW_CARDS)
def test_m_the_event_ids_come_from_the_content(repository, card_id):
    first, second = new_state(repository), new_state(repository)

    _, left = activate(first, card_id, *CHOOSERS[card_id](first))
    _, right = activate(second, card_id, *CHOOSERS[card_id](second))

    assert [e.event_id for e in events_of(first, left.result)] == [
        e.event_id for e in events_of(second, right.result)
    ]


@pytest.mark.parametrize("card_id", NEW_CARDS)
def test_m_running_on_a_clone_leaves_the_original_alone(state, card_id):
    """§12 — 복제본에서 실행해도 원본은 그대로다."""
    clone = state.clone()
    before = state.state_hash()

    _, resolved = activate(clone, card_id, *CHOOSERS[card_id](clone))

    assert resolved.result.status is ResolutionStatus.RESOLVED
    assert state.state_hash() == before
    assert clone.state_hash() != before


@pytest.mark.parametrize("card_id", NEW_CARDS)
def test_m_every_execution_is_journalled_once(state, card_id):
    journal = EventJournal()

    activate(state, card_id, *CHOOSERS[card_id](state), journal=journal)

    assert len(journal) == 1
    recorded = list(journal)[0]
    assert recorded.effect_ref == EffectRef(card_id, 0)
