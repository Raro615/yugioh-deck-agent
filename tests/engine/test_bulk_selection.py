"""
Phase 2-AI — 고르지 않는 선택 ("해당하는 것 전부") 과 첫 실제 카드.

이 단계는 새 계층을 만드는 자리가 아니다. Phase 2-AD ~ 2-AH 가 만든
사슬을 **실제 카드 하나에 처음으로 태우는** 자리다.

    Effect → Operation A → OperationResult A → ResultRef(A)
           → Computed Value → Operation B

리로드(22589918)가 그 사슬을 그대로 탄다.

    @primary  = 패 **전부**                    ← TargetRequirement.ALL (2-AI)
    0번       = return_to_deck(@primary)       → OperationResult(0)
    1번       = shuffle(DECK)
    2번       = draw(ResultRef(0, ATTEMPTED))  ← 앞 결과가 뒤의 수가 된다

왜 ``ALL`` 이 필요했는가
------------------------
2-AH 까지의 요구는 넷이었다.

    ======================  ====================================
    ``NONE``                 대상이 없다
    ``TARGETING``            대상을 지정한다
    ``CHOOSING``             고르지만 대상 지정은 아니다
    ``RANDOM``               아무도 고르지 않는다 (난수가 정한다)
    ======================  ====================================

"전부" 를 ``CHOOSING`` 으로 흉내 내려면 ``minimum``/``maximum`` 을 **지금
후보 수**에 맞춰 두어야 한다. 그러면 명세가 판에 따라 달라지고, 판이 바뀌면
명세가 거짓이 된다. 전부는 수가 아니라 **범위**다 — 그래서 요구를 하나
늘렸고, 늘린 것은 그것뿐이다.

카드 하나를 위해 구조를 바꾼 것이 아니라는 근거는 §A 의 측정이다.
"""

import pathlib
import re
from collections import Counter

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.effect.definition import EffectProvenance, ExecutionAvailability
from engine.effect.delta import CardDrawn, ZoneMoved
from engine.effect.library import (
    EFFECT_LIBRARY,
    RELOAD,
    availability,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import OperationKind
from engine.effect.resolution import TargetSelection
from engine.effect.target import (
    PRIMARY_TARGET,
    AllMatchingSpec,
    CountKind,
    RandomSelectionSpec,
    SelectionCount,
    TargetRequirement,
    TargetSpec,
)
from engine.execution import ResultField
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
FEATHERMAN = 21844576
GRANTED = ValidationResult.valid()

HAND_ALL = AllMatchingSpec(
    source=CandidateSource(zones=frozenset({Zone.HAND}), owner=PlayerRef.CONTROLLER)
)


# ======================================================================
# 판 만들기
# ======================================================================


def reload_state(repository, *, hand: int = 3, deck: int = 20, seed=11) -> GameState:
    """
    자신 마법존에 리로드, 패에 페더맨 ``hand`` 장, 덱에 페더맨 ``deck`` 장.

    리로드 자신은 **패에 없다** — 발동한 카드는 이미 마법존에 있으므로
    ``Duel.GetFieldGroup(p,LOCATION_HAND,0)`` 에 걸리지 않는다.
    """
    game = GameState.create(
        repository,
        decks=([RELOAD] + [FEATHERMAN] * (deck + hand), [FEATHERMAN] * 20),
        seed=seed,
    )
    game.draw(MINE, hand + 1)
    game.move(
        game.player(MINE).hand[0].instance_id,
        Zone.SZONE,
        to_player=MINE,
        position=Position.FACEUP,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return reload_state(repository)


def run_reload(state: GameState, *chosen: InstanceId, journal=None):
    """**기존 경로를 우회하지 않는다.** 발동 → 체인 → 해결을 그대로 지난다."""
    registry = definition_registry()
    activator = EffectActivator(registry, implementation_registry())
    source = state.player(MINE).spell_zone[0].instance_id
    selections = (
        (TargetSelection(PRIMARY_TARGET, Selection.of(*chosen)),) if chosen else ()
    )
    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(RELOAD, 0)
        ),
        selections,
        authorization=GRANTED,
    )
    if activated.status is not ActivationStatus.ACTIVATED:
        return activated, None
    resolver = ChainResolver(build_executor(journal), registry)
    return activated, resolver.resolve_top(state, activated.chain)


# ======================================================================
# A. 조사 — 왜 요구를 하나 늘렸는가 (STRUCTURAL-10)
# ======================================================================


def measure_bulk_corpus() -> tuple[dict[int, dict[str, str]], Counter, set[int]]:
    """
    **고르지 않고 그룹을 통째로 넘기는** 자리를 센다.

    질의는 이것 하나다 — 다시 돌리면 같은 수가 나온다::

        local <g> = Duel.GetFieldGroup(…)      필터 없음 = 존 전체
                  | Duel.GetMatchingGroup(…)   필터 있음 = 해당하는 것 전부
        …
        Duel.{Destroy|SendtoGrave|SendtoDeck|Remove|SendtoHand|Release}(<g>, …)

    ``g:Select(…)`` 를 거친 그룹은 **다른 변수**에 담겨 넘어가므로 여기
    걸리지 않는다. 그것이 ``CHOOSING`` 이고 이 측정의 바깥이다.
    """
    made = re.compile(r"local\s+(\w+)\s*=\s*Duel\.Get(FieldGroup|MatchingGroup)\(")
    calls = ("Destroy", "SendtoGrave", "SendtoDeck", "Remove", "SendtoHand", "Release")

    cards: dict[int, dict[str, str]] = {}
    per_call: Counter = Counter()
    no_filter: set[int] = set()
    for path in ROOT.glob("c*.lua"):
        text = path.read_text(errors="replace")
        groups = {m.group(1): m.group(2) for m in made.finditer(text)}
        if not groups:
            continue
        hits: dict[str, str] = {}
        for call in calls:
            for m in re.finditer(r"Duel\.%s\(\s*(\w+)\s*[,)]" % call, text):
                if m.group(1) in groups:
                    hits[call] = groups[m.group(1)]
                    break
        if hits:
            card_id = int(path.stem[1:])
            cards[card_id] = hits
            for call, origin in hits.items():
                per_call[call] += 1
                if origin == "FieldGroup":
                    # **카드를 센다, 자리를 세지 않는다.** 한 카드가 두
                    # 종류를 쓰면 per_call 에는 둘 다 잡히지만 카드 수는
                    # 하나다.
                    no_filter.add(card_id)
    return cards, per_call, no_filter


def test_a_bulk_is_a_shape_the_corpus_uses_everywhere():
    """
    **카드 하나 때문에 요구를 늘린 것이 아니다.**

    ``Duel.GetFieldGroup`` / ``GetMatchingGroup`` 으로 만든 그룹을 고르지
    않고 통째로 넘기는 카드가 **1,156장**이다. 리로드는 그중 하나다.

    ::

        Destroy      533      SendtoGrave  223      SendtoHand  214
        Remove       181      SendtoDeck   115      Release      91

    그중 **176장**은 필터조차 없다 (``GetFieldGroup`` — "존에 있는 것
    전부"). 리로드의 ``Duel.GetFieldGroup(p,LOCATION_HAND,0)`` 이 그
    모양이다.

    한 장을 위해 구조를 바꾸는 일은 §2 가 금지한다. 이 수가 바뀌지 않는
    한 ``TargetRequirement.ALL`` 은 한 장을 위한 것이 아니다.
    """
    cards, per_call, no_filter = measure_bulk_corpus()

    assert len(cards) == 1156
    assert per_call == Counter(
        {
            "Destroy": 533,
            "SendtoGrave": 223,
            "SendtoHand": 214,
            "Remove": 181,
            "SendtoDeck": 115,
            "Release": 91,
        }
    )
    assert len(no_filter) == 176
    assert RELOAD in no_filter
    assert RELOAD in cards
    assert cards[RELOAD] == {"SendtoDeck": "FieldGroup"}


def test_a_the_corpus_is_not_one_card_type(repository):
    """
    몬스터 · 마법 · 함정이 **다 쓴다.** 어느 한 종류의 버릇이 아니다.
    """
    cards, _, _ = measure_bulk_corpus()

    kinds: Counter = Counter()
    for card_id in cards:
        card = repository.get(card_id)
        assert card is not None, card_id
        kinds[
            "monster" if card.is_monster else "spell" if card.is_spell else "trap"
        ] += 1

    assert kinds == Counter({"monster": 692, "spell": 247, "trap": 217})


# ======================================================================
# B. AllMatchingSpec — 없는 칸이 곧 주장이다
# ======================================================================


def test_b_all_matching_has_no_count():
    """
    **장수 칸을 두지 않았다.** 전부를 "지금 후보 수" 로 적으면 판이 바뀔
    때마다 명세가 달라져야 하고, 그 순간 명세는 판을 설명하는 것이 아니라
    판을 베낀 것이 된다.
    """
    assert not hasattr(HAND_ALL, "count")
    assert HAND_ALL.source.zones == frozenset({Zone.HAND})


def test_b_all_matching_has_nobody_choosing():
    """
    **고르는 사람 칸도 두지 않았다.** ``ChoiceSpec`` 의 ``chooser`` 가 여기
    없는 이유는 "컨트롤러가 고른다" 가 아니라 **고를 일이 없다** 는 것이다.
    """
    assert not hasattr(HAND_ALL, "chooser")


def test_b_nobody_looks_at_the_zone():
    """
    아무도 고르지 않으므로 **아무도 들여다보지 않는다** (2-AA 와 같은 이유).

    리로드가 자신의 패를 되돌리는 일이 패를 공개하지는 않는다.
    """
    assert HAND_ALL.looked_at_zones() == frozenset()
    assert TargetSpec.all_matching(HAND_ALL).looked_at_zones() == frozenset()


def test_b_the_description_says_all_not_a_number():
    assert "전부" in HAND_ALL.describe_ko()
    assert not any(ch.isdigit() for ch in HAND_ALL.describe_ko())


# ======================================================================
# C. TargetSpec — 요구와 명세가 어긋나지 않는다
# ======================================================================


def test_c_all_is_its_own_requirement():
    spec = TargetSpec.all_matching(HAND_ALL)

    assert spec.requirement is TargetRequirement.ALL
    assert spec.is_bulk
    assert not spec.is_random
    assert spec.requires_selection


def test_c_a_bulk_spec_is_never_pending():
    """
    **"아직 안 골랐다" 라는 상태가 없다.** 고를 것이 없기 때문이다.

    ``CHOOSING`` 은 선택이 오기 전까지 ``is_pending`` 이 참이고, ``ALL``
    은 언제나 거짓이다 — ``RANDOM`` 과 같은 이유다.
    """
    bulk = TargetSpec.all_matching(HAND_ALL)
    choosing = TargetSpec.choosing(
        ChoiceSpec(source=HAND_ALL.source, minimum=1, maximum=1)
    )

    assert not bulk.is_pending(None)
    assert not bulk.is_pending(Selection(chosen=()))
    assert choosing.is_pending(None)


def test_c_a_bulk_requirement_demands_a_bulk_spec():
    """요구가 ``ALL`` 인데 ``ChoiceSpec`` 이 붙으면 둘 중 하나가 거짓말이다."""
    with pytest.raises(ValueError, match="AllMatchingSpec"):
        TargetSpec(
            requirement=TargetRequirement.ALL,
            choice=ChoiceSpec(source=HAND_ALL.source, minimum=1, maximum=1),
        )


def test_c_a_bulk_spec_demands_a_bulk_requirement():
    with pytest.raises(ValueError, match="AllMatchingSpec"):
        TargetSpec(requirement=TargetRequirement.CHOOSING, choice=HAND_ALL)


def test_c_bulk_and_random_are_not_the_same_thing():
    """
    둘 다 "아무도 고르지 않는다" 지만 **다른 이유로** 그렇다.

    무작위는 후보 중 **일부**를 난수가 정하고 (그래서 장수가 있다), 전부는
    정할 것이 없다 (그래서 장수가 없다).
    """
    at_random = TargetSpec.at_random(
        RandomSelectionSpec(source=HAND_ALL.source, count=SelectionCount.fixed(1))
    )

    assert at_random.is_random and not at_random.is_bulk
    assert at_random.choice.count.kind is CountKind.FIXED
    assert not hasattr(HAND_ALL, "count")


# ======================================================================
# D. 밖에서 고른 것을 넣을 수 없다 (발동 경계)
# ======================================================================


def test_d_a_chosen_card_is_refused_for_a_bulk_target(state):
    """
    **고른 결과를 받을 곳이 없다.** 받아 주면 "전부" 가 "네가 고른 것"이
    되고, 그것은 이 카드가 적어 둔 일이 아니다.

    한 장만 넣어도 거절이다 — 그 한 장이 마침 패 전부일 때도 마찬가지다.
    """
    one = state.player(MINE).hand[0].instance_id

    activated, resolved = run_reload(state, one)

    assert activated.status is not ActivationStatus.ACTIVATED
    assert resolved is None
    assert activated.code is ValidationCode.TARGET_COUNT_MISMATCH
    assert "전부" in activated.reason


def test_d_the_refusal_leaves_the_board_alone(state):
    before = state.state_hash()

    run_reload(state, state.player(MINE).hand[0].instance_id)

    assert state.state_hash() == before


# ======================================================================
# E. 리로드 — 등재 상태 (§3)
# ======================================================================


def test_e_reload_is_registered_from_its_script():
    entry = entry_for(EffectRef(RELOAD, 0))

    assert entry.card_id == RELOAD
    assert entry.lua_file == "c22589918.lua"
    assert entry.executable
    assert availability(EffectRef(RELOAD, 0)) is ExecutionAvailability.EXECUTABLE
    assert entry.definition.provenance.source is EffectProvenance.official_lua("x").source


def test_e_the_provenance_records_what_was_not_ported():
    """
    **옮기지 못한 것을 적어 둔다.** 적지 않으면 "다 옮겼다" 로 읽힌다.
    """
    note = entry_for(EffectRef(RELOAD, 0)).definition.provenance.note

    for missing in ("IsAbleToDeck", "IsPlayerCanDraw", "BreakEffect"):
        assert missing in note


def test_e_reload_is_the_first_real_card_on_the_chain():
    """
    §3 의 요점. 2-AD ~ 2-AH 의 사슬은 지금까지 synthetic 정의만 태웠다.
    리로드가 **실제 카드로** 그 사슬을 타는 첫 장이다.
    """
    from_result = [
        (entry.card_id, index)
        for entry in EFFECT_LIBRARY
        for index, operation in enumerate(entry.definition.operations)
        if isinstance(getattr(operation, "count", None), SelectionCount)
        and operation.count.kind is CountKind.FROM_RESULT
    ]

    assert from_result == [(RELOAD, 2)]

    bulk = [
        entry.card_id
        for entry in EFFECT_LIBRARY
        for binding in entry.definition.targets
        if binding.spec.is_bulk
    ]
    assert bulk == [RELOAD]


def test_e_the_draw_reads_the_attempted_count_not_the_affected_one():
    """
    스크립트는 ``Duel.Draw(p,#g,…)`` 다 — ``g`` 는 **패 전체 그룹**이므로
    실제로 덱에 들어간 수가 아니라 **넣으려 한 수**다 (2-AF 가 둘을 가른
    이유).

    공식 한국어 텍스트("덱에 넣은 매수만큼")는 ``AFFECTED_COUNT`` 쪽으로
    읽힌다. 이 정의의 출처는 ``official_lua`` 이므로 **스크립트를 따르고**,
    다른 점은 라이브러리 주석에 적어 두었다 — 텍스트를 해석해서 스크립트를
    고치지 않는다.
    """
    draw = entry_for(EffectRef(RELOAD, 0)).definition.operations[2]

    assert draw.kind is OperationKind.DRAW
    assert draw.count.kind is CountKind.FROM_RESULT
    assert draw.count.result.operation_index == 0
    assert draw.count.result.field is ResultField.ATTEMPTED_COUNT


# ======================================================================
# F. 리로드 — 실제 실행 (§5 의 목표 흐름)
# ======================================================================


@pytest.mark.real_card
def test_f_the_whole_hand_goes_back_and_the_same_number_comes_out(state):
    """
    **§5 의 목표 흐름이 실제 카드에서 한 번에 돈다.**

        패 3장 → 0번이 3장을 덱으로 → OperationResult(0).attempted == 3
                → ResultRef(0, ATTEMPTED) → 2번이 3장 드로우

    드로우 수를 정의에 적어 두지 않았다는 점이 요점이다. 3은 **앞 조작이
    낸 수**다.
    """
    hand_before = tuple(card.instance_id for card in state.player(MINE).hand)
    deck_before = len(state.player(MINE).deck)
    assert len(hand_before) == 3

    activated, resolved = run_reload(state)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED

    moved = [d for d in resolved.deltas if isinstance(d, ZoneMoved)]
    drawn = [d for d in resolved.deltas if isinstance(d, CardDrawn)]
    assert len(moved) == 3
    assert {d.card for d in moved} == set(hand_before)
    assert all(d.destination_zone is Zone.DECK for d in moved)
    assert len(drawn) == 3

    # 패는 다시 3장이고, 덱 장수는 되돌린 만큼 늘었다가 뽑은 만큼 줄어
    # 제자리다.
    assert len(state.player(MINE).hand) == 3
    assert len(state.player(MINE).deck) == deck_before


@pytest.mark.real_card
@pytest.mark.parametrize("hand", [1, 2, 5])
def test_f_the_number_drawn_follows_the_hand_not_the_definition(repository, hand):
    """
    같은 정의가 **판마다 다른 수**를 뽑는다. 정의는 그대로다.
    """
    state = reload_state(repository, hand=hand)

    _, resolved = run_reload(state)

    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert len([d for d in resolved.deltas if isinstance(d, CardDrawn)]) == hand
    assert len(state.player(MINE).hand) == hand


@pytest.mark.real_card
def test_f_the_returned_cards_are_not_the_drawn_ones_by_construction(state):
    """
    되돌린 뒤 **섞는다** (1번 조작). 그래서 뽑은 카드가 방금 돌려보낸 그
    카드라는 보장이 없다 — 셔플이 그 사이에 있다는 것이 요점이다.
    """
    entry = entry_for(EffectRef(RELOAD, 0))
    kinds = [operation.kind for operation in entry.definition.operations]

    assert kinds == [
        OperationKind.RETURN_TO_DECK,
        OperationKind.SHUFFLE,
        OperationKind.DRAW,
    ]


@pytest.mark.real_card
def test_f_the_opponent_hand_is_untouched(state):
    """
    ``owner=CONTROLLER`` 다. "전부" 가 판 전체를 뜻하지 않는다.
    """
    theirs = tuple(card.instance_id for card in state.player(THEIRS).hand)

    run_reload(state)

    assert tuple(card.instance_id for card in state.player(THEIRS).hand) == theirs


# ======================================================================
# G. 멈추는 자리 — 0장과 모자란 덱
# ======================================================================


@pytest.mark.real_card
def test_g_an_empty_hand_is_stopped_at_activation(repository):
    """
    ``if #g==0 then return end`` 에 해당하는 자리를 **발동 조건**이 막는다.

    ``ZoneCountAtLeast(CONTROLLER, HAND, 1)`` 이 그것이다. 조작 쪽에서
    "0장이면 실패" 로 만들지 않았다 — 전부가 0장인 것은 실패가 아니라 할
    일이 없는 것이고, 막아야 한다면 그것은 발동 조건이 할 일이다.
    """
    state = reload_state(repository, hand=0)
    assert len(state.player(MINE).hand) == 0

    activated, resolved = run_reload(state)

    assert activated.status is not ActivationStatus.ACTIVATED
    assert resolved is None


@pytest.mark.real_card
def test_g_this_card_can_never_run_the_deck_out(repository):
    """
    **덱이 0장이어도 멈추지 않는다.** 처음에 그 반대를 시험으로 적었다가
    틀렸다는 것을 실행이 알려 주었으므로, 사실 쪽을 남긴다.

    이유가 구조에 있다. 2번 조작이 뽑는 수는 ``ResultRef(0, ATTEMPTED)``
    이고, 0번 조작은 **그 수만큼의 카드를 덱에 넣은** 뒤다. 그래서 뽑기
    직전의 덱은 언제나 그 수 이상이다 — 이 카드에 한해 "덱이 모자라서
    멈춘다" 는 갈래가 없다.

    ``Duel.IsPlayerCanDraw`` 를 옮기지 못했다는 사실은 그대로다. 그것은
    "덱 장수" 가 아니라 "이 플레이어가 드로우할 수 있는가" 이고, 그것을
    막는 다른 카드가 깔려 있는 판은 이 계층으로 아직 만들지 못한다.
    """
    state = reload_state(repository, hand=3, deck=0)
    assert len(state.player(MINE).deck) == 0

    activated, resolved = run_reload(state)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert len([d for d in resolved.deltas if isinstance(d, CardDrawn)]) == 3
    assert len(state.player(MINE).hand) == 3
    assert len(state.player(MINE).deck) == 0


# ======================================================================
# H. 결정론
# ======================================================================


@pytest.mark.real_card
def test_h_the_same_seed_gives_the_same_hand(repository):
    """
    셔플이 끼어 있어도 **같은 씨앗이면 같은 판**이다 (Phase 2-N).
    """
    first = reload_state(repository, seed=4)
    second = reload_state(repository, seed=4)
    assert first.state_hash() == second.state_hash()

    run_reload(first)
    run_reload(second)

    assert first.state_hash() == second.state_hash()
