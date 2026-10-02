"""
Phase 3-E-4 — Target Selection Bridge.

    PlayerAction(targets=(ActionTarget.instance(#41),))
      → selections_for(definition, action)
      → (TargetSelection(@primary, Selection((#41,))),)
      → EffectActivator.activate(selections=...)
      → ChainLink(selections=...)
      → ChainResolver → EffectExecutor
      → GameState 변경

이 파일이 지키는 것
-------------------
**다리 하나다.** 후보 세기(``TargetResolver.candidates``) · 적법성 판정
(``TargetResolver.validate``) · 효과 실행(``EffectExecutor``)은 **전부 이미
있던 것**이고, 없던 것은 ``ActionTarget`` ↔ ``TargetSelection`` 환전뿐이다.

**대상 하나하나가 다른 후보다.** 같은 이름 두 장은 ``instance_id`` 로
구분되고, 한쪽을 고른 결과와 다른 쪽을 고른 결과가 다르다.

**고르는 사람이 없는 대상은 짝에서 빠진다.** ``at_random`` 은 발동 시점에
정하지 않고 해결 중에 Game RNG 가 정한다 (§18). "무작위로 1장" 과
"플레이어가 1장" 을 같은 자리에 놓지 않는다.

**가려진 자리의 카드는 가리키지 않는다.** ``PlayerAction`` 은 정책에게 가는
데이터이므로, 거기에 덱의 카드를 적으면 후보 목록을 읽는 것만으로 덱 내용이
새어 나간다 (STRUCTURAL-125).
"""

import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget, ActionTargetKind
from engine.action_validation import ActionValidator, ActionValidity, ValidationCode
from engine.chain import Chain
from engine.cost import Selection
from engine.duel import Duel
from engine.effect.library import definition_registry, implementation_registry
from engine.effect.target import TargetRef, TargetSelection
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.target_bridge import (
    TargetBridgeError,
    chosen_bindings,
    required_target_count,
    selections_for,
    target_combinations,
    targets_from,
)
from engine.validation import ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: 무정한 말살 — 통상 마법. **한 카드 안에 두 종류의 대상이 나란히 있다.**
#:   @primary  자신 필드의 몬스터 1장 — 플레이어가 고른다 (TargetSpec.targeting)
#:   @random   상대 패에서 1장       — 아무도 고르지 않는다 (TargetSpec.at_random)
#: 그래서 이 Phase 의 기준 카드다 — §13 의 "필드의 몬스터 1장을 대상으로
#: 한다" 수준이면서 §18 의 구분까지 한 장으로 증명한다.
RUTHLESS_DENIAL = 73148972
#: 어리석은 매장 — 대상이 **덱**에 있다. 정책이 볼 수 없는 자리다.
FOOLISH_BURIAL = 81439173
#: 욕망의 항아리 — 대상이 없다. Phase 3-E-3 의 기준 카드.
POT_OF_GREED = 55144522
#: 싸이크론 — 대상이 있지만 **속공** 마법이라 후보 생성 범위 밖. 다리 자체는
#: 통과하므로 "가려진 정체" 시험에 쓴다.
MYSTICAL_SPACE_TYPHOON = 5318639

LUSTER_DRAGON = 11091375  # ATK 1900
BATTLE_OX = 5053103  # ATK 1700
TRAP_HOLE = 4206964

RUTHLESS_REF = EffectRef(RUTHLESS_DENIAL, 0)
POT_REF = EffectRef(POT_OF_GREED, 0)

DEFINITIONS = definition_registry()


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def staged(
    repository,
    *,
    hand=(RUTHLESS_DENIAL,),
    mine=(LUSTER_DRAGON, BATTLE_OX),
    theirs=(),
    opponent_hand: int = 2,
    phase: Phase = Phase.MAIN1,
):
    """
    메인 페이즈의 판 하나. 배치는 ``create_instance`` + ``GameState.move`` 다.

    ``mine`` · ``theirs`` 는 몬스터 존에 앞면 공격 표시로 놓는다.
    """
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 20, [POT_OF_GREED] * 20), seed=1
    )
    sources = [
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    placed = {MINE: [], THEIRS: []}
    for seat, layout in ((MINE, mine), (THEIRS, theirs)):
        for card_id in layout:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
            )
            placed[seat].append(card.instance_id)
    if opponent_hand:
        state.draw(THEIRS, opponent_hand)
    state.turn.set_phase(phase)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=phase),
    )
    return duel, sources, placed


def activations(duel: Duel, seat: int = MINE):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


def board(duel: Duel) -> tuple:
    """바뀔 수 있는 자리 전부."""
    return (
        duel.state.state_hash(),
        duel.state.randomness.draws if duel.state.seed is not None else None,
        duel.state.randomness.selections
        if hasattr(duel.state.randomness, "selections")
        else None,
        duel.chain.canonical_state(),
        duel.priority,
        duel.result,
        tuple(
            (
                duel.state.player(seat).life_points,
                tuple(
                    tuple(c.instance_id.value for c in duel.state.player(seat).zone(z))
                    for z in (
                        Zone.DECK, Zone.HAND, Zone.MZONE,
                        Zone.SZONE, Zone.GRAVE, Zone.REMOVED,
                    )
                ),
            )
            for seat in (MINE, THEIRS)
        ),
    )


def granted() -> ValidationResult:
    return ValidationResult.valid("test: 바깥에서 준 허가")


def can_activate(duel: Duel, action: PlayerAction, definition):
    return duel._activator.can_activate(
        duel.state,
        duel.chain,
        action,
        selections=selections_for(definition, action),
        authorization=granted(),
    )


# ======================================================================
# 0. 전제 — 카드와 근거
# ======================================================================


@pytest.mark.real_card
def test_00_the_test_card_is_what_we_think_it_is(repository):
    """적어 둔 것을 믿지 않는다. 공식 DB 와 라이브러리에서 다시 읽는다."""
    card = repository.get(RUTHLESS_DENIAL)
    assert card is not None
    assert card.type_names == ["SPELL"], card.type_names  # 통상 마법

    definition = DEFINITIONS.definition_for(RUTHLESS_REF)
    assert definition is not None
    assert definition.cost.costs == (), "비용이 있으면 이 Phase 의 범위 밖이다"
    assert len(definition.targets) == 2

    from engine.effect.library import entry_for

    entry = entry_for(RUTHLESS_REF)
    assert entry.executable
    assert entry.lua_file == "c73148972.lua"
    # 근거가 함께 실려 있다 — 정의가 추측이 아니라는 증거.
    assert "SelectTarget" in entry.lua_excerpt
    assert "RandomSelect" in entry.lua_excerpt


def test_00b_the_two_target_kinds_are_not_the_same_thing():
    """
    **§18 — "무작위로 1장" 과 "플레이어가 1장" 을 같은 자리에 놓지 않는다.**

    같은 카드 안에 둘이 나란히 있고, 다리는 **앞의 것만** 짝짓는다.
    """
    definition = DEFINITIONS.definition_for(RUTHLESS_REF)
    names = [binding.ref.name for binding in definition.targets]
    assert names == ["primary", "random"]

    chosen = chosen_bindings(definition)
    assert [b.ref.name for b in chosen] == ["primary"]
    assert required_target_count(definition) == 1

    primary, random_binding = definition.targets
    assert not primary.spec.is_random
    assert random_binding.spec.is_random


# ======================================================================
# A. 환전 — ActionTarget ↔ TargetSelection (§3 · §7 · §8)
# ======================================================================


def test_01_the_bridge_converts_order_into_names():
    """
    환전은 **순서 → 이름**이다. ``PlayerAction`` 에는 이름이 없고 순서만 있다.
    """
    definition = DEFINITIONS.definition_for(RUTHLESS_REF)
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=InstanceId(1),
        effect_ref=RUTHLESS_REF,
        targets=targets_from((InstanceId(41),)),
    )

    selections = selections_for(definition, action)
    assert len(selections) == 1
    assert isinstance(selections[0], TargetSelection)
    assert selections[0].ref == TargetRef("primary")
    assert selections[0].selection == Selection((InstanceId(41),))
    # ``@random`` 에는 아무것도 넣지 않는다.
    assert [s.ref.name for s in selections] == ["primary"]


def test_02_an_effect_with_no_target_gets_an_empty_tuple():
    definition = DEFINITIONS.definition_for(POT_REF)
    action = PlayerAction.activate_effect(
        actor=MINE, source=InstanceId(1), effect_ref=POT_REF
    )
    assert chosen_bindings(definition) == ()
    assert required_target_count(definition) == 0
    assert selections_for(definition, action) == ()


def test_03_the_bridge_preserves_instance_identity_and_order():
    """
    **§7 · §9** — ``instance_id`` 를 그대로 보존하고 순서를 잃지 않는다.

    ``set`` 으로 만들면 "어느 순서로 골랐는가" 가 사라진다.
    """
    ids = (InstanceId(7), InstanceId(3), InstanceId(9))
    targets = targets_from(ids)
    assert [t.kind for t in targets] == [ActionTargetKind.INSTANCE] * 3
    assert tuple(t.instance_id for t in targets) == ids, "순서가 바뀌었다"
    assert isinstance(targets, tuple), "불변이어야 한다"


def test_04_the_bridge_refuses_a_shape_it_cannot_convert():
    """
    **모양이 맞지 않으면 거절한다.** 적법성 판정이 아니다 — 적법성은 받는
    쪽(``TargetResolver``)이 다시 본다.
    """
    ruthless = DEFINITIONS.definition_for(RUTHLESS_REF)
    pot = DEFINITIONS.definition_for(POT_REF)

    # 대상이 필요한데 없다
    with pytest.raises(TargetBridgeError, match="1장이 필요한데 0개"):
        selections_for(
            ruthless,
            PlayerAction.activate_effect(
                actor=MINE, source=InstanceId(1), effect_ref=RUTHLESS_REF
            ),
        )
    # 너무 많다
    with pytest.raises(TargetBridgeError, match="1장이 필요한데 2개"):
        selections_for(
            ruthless,
            PlayerAction.activate_effect(
                actor=MINE,
                source=InstanceId(1),
                effect_ref=RUTHLESS_REF,
                targets=targets_from((InstanceId(1), InstanceId(2))),
            ),
        )
    # 대상이 없는 효과에 대상
    with pytest.raises(TargetBridgeError, match="고를 대상이 없는데"):
        selections_for(
            pot,
            PlayerAction.activate_effect(
                actor=MINE,
                source=InstanceId(1),
                effect_ref=POT_REF,
                targets=targets_from((InstanceId(1),)),
            ),
        )
    # 카드가 아닌 대상 (존 · 플레이어)
    with pytest.raises(TargetBridgeError, match="카드\\(instance\\)여야"):
        selections_for(
            ruthless,
            PlayerAction.activate_effect(
                actor=MINE,
                source=InstanceId(1),
                effect_ref=RUTHLESS_REF,
                targets=(ActionTarget.player_target(THEIRS),),
            ),
        )


def test_05_the_bridge_does_not_count_candidates_itself():
    """
    **후보를 세는 코드를 새로 쓰지 않았다.** 다리가 ``TargetResolver`` 를
    부른다 — 세는 로직이 두 벌이 되면 둘이 갈라진다.
    """
    import ast

    source = (ROOT / "engine/target_bridge.py").read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "candidates" in called, "TargetResolver.candidates 를 쓰지 않는다"
    assert "TargetResolver" in source

    # **설명문을 걷어내고** 본다 — "여기서 하지 않는 것" 목록에 적어 둔 이름이
    # 금지어 검사에 걸리면 거짓 경보가 난다 (Phase 3-E-1 의 test_08c 와 같은
    # 손질이다). 처음에 그렇게 썼고, 그것이 잘못된 가정이었다.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    code = ast.unparse(tree)
    for forbidden in ("TargetEngine", "TargetGraph", "TargetSearchEngine"):
        assert forbidden not in code


# ======================================================================
# B. 후보 생성 — 대상마다 다른 후보 (§5 · §7 · §17)
# ======================================================================


@pytest.mark.real_card
def test_06_each_eligible_target_is_its_own_candidate(repository):
    """
    **대상 하나하나가 다른 후보다.** 내 필드에 몬스터 2장이면 후보가 2개다.
    """
    duel, _, placed = staged(repository)
    found = activations(duel)

    assert len(found) == 2
    assert {a.instance_targets()[0] for a in found} == set(placed[MINE])
    assert len({a.canonical_state() for a in found}) == 2


@pytest.mark.real_card
def test_07_same_name_copies_are_told_apart_by_instance_id(repository):
    """
    **§7 · §15-7 — 같은 이름 세 장을 이름으로 식별하지 않는다.**

    세 후보가 모두 다르고, 고른 하나만 묘지로 간다.
    """
    duel, _, placed = staged(
        repository, mine=(LUSTER_DRAGON, LUSTER_DRAGON, LUSTER_DRAGON)
    )
    found = activations(duel)
    assert len(found) == 3
    assert len({a.instance_targets()[0] for a in found}) == 3

    target = found[1].instance_targets()[0]
    assert duel.apply(found[1]).accepted
    assert settle_chain(duel).accepted

    survivors = [c.instance_id for c in duel.state.player(MINE).monster_zone]
    assert target not in survivors
    assert len(survivors) == 2
    assert target in [c.instance_id for c in duel.state.player(MINE).grave]


@pytest.mark.real_card
def test_08_no_candidate_when_there_is_nothing_eligible(repository):
    """
    대상이 될 것이 없으면 후보가 없다 — 발동 조건이 그것을 본다
    (``ZoneCountAtLeast(CONTROLLER, MZONE, 1)``).
    """
    duel, _, _ = staged(repository, mine=())
    assert activations(duel) == []


@pytest.mark.real_card
def test_09_only_the_controllers_own_monsters_are_candidates(repository):
    """
    후보 조건이 ``owner=CONTROLLER`` 다 (``LOCATION_MZONE, 0`` — 자신 쪽만).
    상대 몬스터는 후보에 오르지 않는다.
    """
    duel, _, placed = staged(
        repository, mine=(LUSTER_DRAGON,), theirs=(BATTLE_OX, LUSTER_DRAGON)
    )
    found = activations(duel)
    assert len(found) == 1
    assert found[0].instance_targets()[0] == placed[MINE][0]
    for instance in placed[THEIRS]:
        assert instance not in {a.instance_targets()[0] for a in found}


@pytest.mark.real_card
def test_10_the_candidate_order_follows_the_observation(repository):
    """
    **§9 · §17 — 순서를 잃지 않는다.** 그리고 **아무 순서나가 아니다.**

    처음에는 "같은 판이면 같은 순서" 만 확인했는데, 그것으로는 모자랐다 —
    후보를 ``sorted(set(...), reverse)`` 로 뒤집어도 그 시험은 통과한다
    (고의 위반으로 확인했다). 안정적이기만 하면 ``set`` 을 거쳐 순서를 잃은
    것과 구별되지 않는다.

    그래서 **관측의 순서**에 못박는다. ``CandidateResolver`` 가 존을 훑는
    순서가 곧 몬스터 존의 자리 순서이고, 후보도 그 순서로 나와야 한다.
    """
    duel, _, placed = staged(
        repository, mine=(LUSTER_DRAGON, BATTLE_OX, LUSTER_DRAGON)
    )

    on_field = [c.instance_id for c in duel.state.player(MINE).monster_zone]
    chosen = [a.instance_targets()[0] for a in activations(duel)]
    assert chosen == on_field, (chosen, on_field)

    # 그리고 되풀이해도 같다.
    for _ in range(3):
        again, _, _ = staged(
            repository, mine=(LUSTER_DRAGON, BATTLE_OX, LUSTER_DRAGON)
        )
        assert [a.instance_targets()[0] for a in activations(again)] == chosen


@pytest.mark.real_card
def test_11_no_duplicate_candidates(repository):
    """**§17 — 같은 Action + 같은 대상의 중복 후보를 만들지 않는다.**"""
    duel, _, _ = staged(
        repository, hand=(RUTHLESS_DENIAL, RUTHLESS_DENIAL), mine=(LUSTER_DRAGON,)
    )
    found = activations(duel)
    states = [a.canonical_state() for a in found]
    assert len(states) == len(set(states))
    # 패에 2장 × 대상 1장 = 4개가 아니라 2개다.
    assert len(found) == 2


# ======================================================================
# C. 실행 — 전체 경로 (§14 · §25)
# ======================================================================


@pytest.mark.real_card
def test_12_the_whole_target_path_runs_through_duel_apply(repository):
    """
    **§14 · §25 를 한 자리에서 센다.** 이 Phase 의 한 줄이다.

        PlayerAction(targets=…) → TargetSelection → activation → Chain
        → resolution → EffectOperation(targets=…) → state change

    무정한 말살: 고른 내 몬스터가 묘지로, 상대 패에서 무작위로 1장이 묘지로.
    """
    duel, (spell,), placed = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
    chosen = activations(duel)[0]
    target = chosen.instance_targets()[0]

    mine_before = len(duel.state.player(MINE).monster_zone)
    opp_hand_before = len(duel.state.player(THEIRS).hand)

    activation = duel.apply(chosen)
    assert activation.accepted, activation.reason
    # 발동과 해결 사이에 상대의 응답 기회가 들어간다 (Phase 3-E-11 ·
    # RULE-CHAIN-001). 결과 숫자는 아래에서 그대로 확인한다.
    step = settle_chain(duel)
    assert step.accepted, step.reason
    assert "@primary" in step.reason
    assert str(target.value) in step.reason

    # ① 고른 대상이 묘지로 갔다.
    assert len(duel.state.player(MINE).monster_zone) == mine_before - 1
    assert target in [c.instance_id for c in duel.state.player(MINE).grave]
    # ② 발동한 마법도 묘지로 갔다 (RULE-SPELLTRAP-002).
    assert spell in [c.instance_id for c in duel.state.player(MINE).grave]
    # ③ 상대 패에서 무작위로 1장이 묘지로 갔다 (@random).
    assert len(duel.state.player(THEIRS).hand) == opp_hand_before - 1
    assert len(duel.state.player(THEIRS).grave) == 1
    # ④ 체인은 비워졌다.
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_13_choosing_a_different_target_gives_a_different_board(repository):
    """
    **대상이 결과를 바꾼다.** 두 후보가 서로 다른 미래를 만든다 — 그래야
    대상 선택이 의미를 갖는다.
    """
    outcomes = {}
    for index in (0, 1):
        duel, _, _ = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
        chosen = activations(duel)[index]
        target = chosen.instance_targets()[0]
        assert duel.apply(chosen).accepted
        assert settle_chain(duel).accepted
        survivor = [c.card_id for c in duel.state.player(MINE).monster_zone]
        outcomes[target] = survivor

    assert len(outcomes) == 2
    assert list(outcomes.values())[0] != list(outcomes.values())[1]


@pytest.mark.real_card
def test_14_the_chain_link_carries_the_selection(repository):
    """
    **대상이 ChainLink 에 보존된다** — 기존 ``Chain`` 구조를 그대로 쓴다.

    보존되지 않으면 해결 시점에 무엇을 골랐는지 알 수 없다.
    """
    duel, (spell,), placed = staged(repository, mine=(LUSTER_DRAGON,))
    chosen = activations(duel)[0]
    definition = DEFINITIONS.definition_for(RUTHLESS_REF)

    activated = duel._activator.activate(
        duel.state,
        Chain(),
        chosen,
        selections=selections_for(definition, chosen),
        authorization=granted(),
    )
    assert activated.activated
    link = activated.link
    assert len(link.selections) == 1
    assert link.selections[0].ref == TargetRef("primary")
    assert link.selections[0].selection.chosen == (placed[MINE][0],)


@pytest.mark.real_card
def test_15_the_effect_deltas_name_the_chosen_card(repository):
    """
    기록에 **고른 카드가** 남는다. 무작위로 간 카드와 구분된다.
    """
    duel, _, placed = staged(repository, mine=(LUSTER_DRAGON,))
    chosen = activations(duel)[0]
    definition = DEFINITIONS.definition_for(RUTHLESS_REF)

    activated = duel._activator.activate(
        duel.state,
        Chain(),
        chosen,
        selections=selections_for(definition, chosen),
        authorization=granted(),
    )
    resolved = duel._resolver.resolve_top(duel.state, activated.chain)
    assert resolved.resolved, resolved.reason

    moved = {d.instance: d for d in resolved.deltas}
    assert placed[MINE][0] in moved, "고른 카드가 기록에 없다"
    chosen_delta = moved[placed[MINE][0]]
    assert chosen_delta.from_zone is Zone.MZONE
    assert chosen_delta.to_zone is Zone.GRAVE
    assert "EFFECT" in chosen_delta.reason_names

    # @random 쪽은 상대 패에서 왔다.
    random_deltas = [
        d for d in resolved.deltas if d.from_zone is Zone.HAND
    ]
    assert len(random_deltas) == 1
    assert random_deltas[0].from_player == THEIRS


# ======================================================================
# D. Negative cases (§15)
# ======================================================================


@pytest.mark.real_card
def test_16_a_nonexistent_instance_is_unknown_not_invalid(repository):
    """
    **§15-1 에서 이 저장소는 ``UNKNOWN`` 을 고른다** — 그 이유를 적는다.

    "그런 카드가 없다" 와 "그 카드를 볼 수 없다" 는 관측에서 **구별되지
    않는다.** 구별해서 ``INVALID`` 를 돌려주면, 검증을 반복하는 것만으로
    상대 패에 어떤 카드가 있는지 탐지할 수 있다 (ADR-007 이 막는 바로 그
    경로다).

    그래서 ``HIDDEN_CARD`` / ``UNKNOWN`` 으로 남긴다. 어느 쪽이든 **허가가
    아니므로** 후보가 되지 않고 ``apply`` 도 거절한다 — 안전성은 같고,
    정보가 새지 않는 쪽을 고른 것이다.
    """
    duel, (spell,), _ = staged(repository, mine=(LUSTER_DRAGON,))
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=spell,
        effect_ref=RUTHLESS_REF,
        targets=targets_from((InstanceId(9999),)),
    )

    verdict = ActionValidator(duel.view(MINE)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD
    assert not verdict.permits_execution

    before = board(duel)
    assert not duel.apply(action).accepted
    assert board(duel) == before


@pytest.mark.real_card
def test_17_a_target_in_the_wrong_zone_is_invalid(repository):
    """
    **§15-2** — 자리가 틀린 카드는 ``INVALID`` 다. 자리는 **공개**이므로
    확실히 판정할 수 있고, 그때는 ``UNKNOWN`` 으로 미루지 않는다.
    """
    duel, (spell,), placed = staged(repository, mine=(LUSTER_DRAGON,))
    in_hand = duel.state.player(MINE).hand.cards()[0].instance_id

    action = PlayerAction.activate_effect(
        actor=MINE,
        source=spell,
        effect_ref=RUTHLESS_REF,
        targets=targets_from((in_hand,)),
    )
    verdict = can_activate(duel, action, DEFINITIONS.definition_for(RUTHLESS_REF))
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    before = board(duel)
    assert not duel.apply(action).accepted
    assert board(duel) == before


@pytest.mark.real_card
def test_18_a_target_that_fails_the_condition_is_invalid(repository):
    """
    **§15-3** — 조건을 만족하지 않는 카드는 ``INVALID`` 다.

    무정한 말살의 후보 조건은 ``owner=CONTROLLER`` 다. 상대 몬스터는 자리도
    주인도 **보이므로** 확실히 아니다.
    """
    duel, (spell,), placed = staged(
        repository, mine=(LUSTER_DRAGON,), theirs=(BATTLE_OX,)
    )
    action = PlayerAction.activate_effect(
        actor=MINE,
        source=spell,
        effect_ref=RUTHLESS_REF,
        targets=targets_from((placed[THEIRS][0],)),
    )
    verdict = can_activate(duel, action, DEFINITIONS.definition_for(RUTHLESS_REF))
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert not duel.apply(action).accepted


@pytest.mark.real_card
def test_18b_a_target_only_the_effect_may_see_is_not_a_candidate(repository):
    """
    **STRUCTURAL-125 — ``looked_at`` 권한이 AI 에게 새지 않는다.**

    어리석은 매장은 **덱**의 몬스터를 고른다. 규칙이 그 효과에게 덱을 열어
    주므로 (``looked_at``) 후보를 셀 수는 있다. 그런데 ``PlayerAction`` 은
    ``legal_actions`` 가 정책에게 **그대로 건네는 데이터**다 — 거기에 덱의
    카드를 적으면 후보 목록을 읽는 것만으로 덱 내용이 새어 나간다.

    그래서 다리가 **평소 관측으로 한 번 더 좁힌다.** 효과에게 준 권한은
    해결 중에만 유효하다.

    Phase 3-E-3 은 이 카드가 후보가 아닌 이유를 "대상을 건넬 길이 없다"
    (STRUCTURAL-121) 로 적었다. 길은 생겼고, 이제 이유가 **관측 경계**다.
    """
    duel, (spell,), _ = staged(repository, hand=(FOOLISH_BURIAL,), mine=())
    definition = DEFINITIONS.definition_for(EffectRef(FOOLISH_BURIAL, 0))

    # 규칙은 이 효과에게 덱을 열어 준다.
    binding = chosen_bindings(definition)[0]
    assert binding.spec.looked_at_zones() == frozenset({Zone.DECK})

    # 그런데도 후보 조합이 없다 — 평소 관측에 보이지 않기 때문이다.
    assert target_combinations(duel.state, MINE, definition, spell) == []
    assert activations(duel) == []

    # 덱의 카드를 손으로 적어 넣으면 검증기가 막는다 (이중 방어).
    deck_card = duel.state.player(MINE).deck.cards()[0].instance_id
    assert duel.view(MINE).find(deck_card) is None
    forced = PlayerAction.activate_effect(
        actor=MINE,
        source=spell,
        effect_ref=EffectRef(FOOLISH_BURIAL, 0),
        targets=targets_from((deck_card,)),
    )
    verdict = ActionValidator(duel.view(MINE)).validate(forced)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD


@pytest.mark.real_card
def test_19_a_face_down_target_is_unknown_not_invalid(repository):
    """
    **§15-4 · §6 — 가려진 정체는 ``UNKNOWN`` 이다.**

    싸이크론의 후보 조건은 "마법 · 함정인가" 이고, 뒷면 카드에는 그것을
    판정할 수 없다. 그래서 ``undecided`` 로 남아 **후보가 되지 않고**, 손으로
    적어 넣어도 ``UNKNOWN`` 이다 — 결코 ``VALID`` 가 아니다.

    같은 카드가 **앞면**이면 통과한다. 그래서 거절의 이유가 "싸이크론이 안
    된다" 가 아니라 **"보이지 않는다"** 임이 확인된다.
    """
    definition = DEFINITIONS.definition_for(EffectRef(MYSTICAL_SPACE_TYPHOON, 0))

    def attempt(position: Position):
        duel, (spell,), _ = staged(
            repository, hand=(MYSTICAL_SPACE_TYPHOON,), mine=()
        )
        victim = duel.state.create_instance(
            TRAP_HOLE, owner=THEIRS, zone=Zone.HAND
        )
        duel.state.move(
            victim, Zone.SZONE, to_player=THEIRS, position=position
        )
        action = PlayerAction.activate_effect(
            actor=MINE,
            source=spell,
            effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0),
            targets=targets_from((victim.instance_id,)),
        )
        combos = target_combinations(duel.state, MINE, definition, spell)
        return combos, can_activate(duel, action, definition)

    hidden_combos, hidden = attempt(Position.FACEDOWN)
    assert hidden_combos == [], "뒷면 카드가 후보에 올랐다"
    assert hidden.validity is ActionValidity.UNKNOWN
    assert hidden.code is ValidationCode.INFORMATION_UNAVAILABLE

    visible_combos, visible = attempt(Position.FACEUP)
    assert len(visible_combos) == 1
    assert visible.validity is ActionValidity.VALID


@pytest.mark.real_card
def test_20_a_missing_or_extra_target_never_touches_the_board(repository):
    """
    **§15-5 · §15-6** — 개수가 틀린 Action 은 판을 한 글자도 바꾸지 않는다.

    환전이 **배치보다 앞**이기 때문이다 — 카드를 필드에 놓기 전에 거절한다.
    """
    duel, (spell,), placed = staged(repository, mine=(LUSTER_DRAGON,))
    before = board(duel)

    for targets, label in (
        ((), "대상 없음"),
        (targets_from((placed[MINE][0], placed[MINE][0])), "대상 2개"),
    ):
        action = PlayerAction.activate_effect(
            actor=MINE, source=spell, effect_ref=RUTHLESS_REF, targets=targets
        )
        step = duel.apply(action)
        assert not step.accepted, label
        assert board(duel) == before, label
        # 마법이 필드에 남아 있지 않다.
        assert len(duel.state.player(MINE).spell_zone) == 0, label

        # **실행 경로를 직접 두드린다.** ``apply`` 는 후보 재확인에서 먼저
        # 막으므로 (test_21) 위 세 줄만으로는 ``_apply_activation`` 안의
        # **순서**가 확인되지 않는다. 환전이 배치보다 뒤로 가면 거절될
        # Action 이 카드를 필드에 올려놓고 멈춘다 — 고의 위반으로 확인한
        # 구멍이고, 이 줄이 그것을 막는다.
        direct = duel._apply_activation(action)
        assert not direct.accepted, label
        assert direct.code is ValidationCode.TARGET_COUNT_MISMATCH, label
        assert board(duel) == before, label
        assert len(duel.state.player(MINE).spell_zone) == 0, label
        assert spell in [c.instance_id for c in duel.state.player(MINE).hand], label


@pytest.mark.real_card
def test_21_a_target_on_an_effect_that_wants_none_is_refused(repository):
    """
    **§15-6** — 대상이 없는 효과에 대상을 넣으면 거절된다.

    **어느 관문이 막는지가 중요하다.** ``Duel.apply`` 는 후보 목록을 **다시**
    보고 거기 없으면 거절하므로 (``RULE_NOT_IMPLEMENTED``), 모양이 틀린
    Action 은 다리에 닿기도 전에 막힌다. 다리의 모양 검사는 **두 번째 방어**
    이고, 거기까지 가는 길을 따로 확인한다.

    이 시험을 처음 쓸 때 ``apply`` 가 ``TARGET_COUNT_MISMATCH`` 를 돌려줄
    것으로 적었는데, 그것이 잘못된 가정이었다 — 후보 재확인이 더 앞이다.
    """
    duel, (spell, pot), placed = staged(
        repository, hand=(RUTHLESS_DENIAL, POT_OF_GREED), mine=(LUSTER_DRAGON,)
    )
    before = board(duel)

    action = PlayerAction.activate_effect(
        actor=MINE,
        source=pot,
        effect_ref=POT_REF,
        targets=targets_from((placed[MINE][0],)),
    )
    # 후보가 아니다 — 대상 없는 효과의 후보는 대상도 없이 만들어진다.
    assert action not in duel.legal_actions(MINE).allowed
    step = duel.apply(action)
    assert not step.accepted
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert board(duel) == before

    # 두 번째 방어: 다리에 직접 주면 모양으로 거절한다.
    with pytest.raises(TargetBridgeError, match="고를 대상이 없는데"):
        selections_for(DEFINITIONS.definition_for(POT_REF), action)


# ======================================================================
# E. Search · 안전 (§16 · §19 · §20)
# ======================================================================


@pytest.mark.real_card
def test_22_the_simulator_runs_a_targeted_activation(repository):
    """
    **§16 · §19** — 사본에서는 일어나고 원본은 그대로다.
    """
    from agent.simulation import SimulationStatus, Simulator

    duel, _, placed = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
    chosen = activations(duel)[0]
    target = chosen.instance_targets()[0]
    simulator = Simulator(duel)
    before = board(duel)

    result = simulator.simulate(chosen, viewer=MINE)
    assert result.status is SimulationStatus.SUPPORTED, result.reason
    assert isinstance(result.future, GameStateView)
    # 사본에서는 고른 카드가 사라졌다.
    assert target not in [
        c.instance_id for c in result.future.me.monster_zone.occupied()
    ]
    # 원본은 한 글자도 바뀌지 않았다.
    assert board(duel) == before
    assert target in [c.instance_id for c in duel.state.player(MINE).monster_zone]


@pytest.mark.real_card
def test_23_different_targets_give_different_futures(repository):
    """
    탐색이 대상을 **구별할 수 있다.** 미래가 같으면 고를 이유가 없다.
    """
    from agent.simulation import Simulator

    duel, _, _ = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
    simulator = Simulator(duel)
    futures = {
        action.instance_targets()[0]: simulator.simulate(
            action, viewer=MINE
        ).future
        for action in activations(duel)
    }
    assert len(futures) == 2
    survivors = {
        tuple(c.card_id for c in future.me.monster_zone.occupied())
        for future in futures.values()
    }
    assert len(survivors) == 2, "대상이 달라도 미래가 같다"


@pytest.mark.real_card
def test_24_many_simulations_do_not_drift_the_duel(repository):
    """**§19 — 사본의 독립.** 몇 번 해 봐도 원본이 흔들리지 않는다."""
    from agent.simulation import Simulator

    duel, _, _ = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
    simulator = Simulator(duel)
    before = board(duel)

    for _ in range(5):
        for action in duel.legal_actions(MINE).allowed:
            simulator.simulate(action, viewer=MINE)

    assert board(duel) == before


@pytest.mark.real_card
def test_25_the_random_half_uses_the_game_rng_only(repository):
    """
    **§18 · §20 — 무작위 쪽은 Game RNG 를 쓴다.** Policy RNG 가 아니다.

    같은 씨앗이면 같은 카드가 간다. 그리고 사본에서 쓴 난수가 원본에
    남지 않는다.
    """
    taken = []
    for _ in range(3):
        duel, _, _ = staged(repository, mine=(LUSTER_DRAGON,))
        assert duel.apply(activations(duel)[0]).accepted
        taken.append(
            tuple(c.instance_id.value for c in duel.state.player(THEIRS).grave)
        )
    assert taken[0] == taken[1] == taken[2], taken

    # 사본에서 해 봐도 원본의 난수 상태가 움직이지 않는다.
    from agent.simulation import Simulator

    duel, _, _ = staged(repository, mine=(LUSTER_DRAGON,))
    before = board(duel)
    simulator = Simulator(duel)
    for _ in range(3):
        simulator.simulate(activations(duel)[0], viewer=MINE)
    assert board(duel) == before


@pytest.mark.real_card
def test_26_the_opponent_cannot_read_the_discard_through_the_action(repository):
    """
    **§6 · §19 — 후보 목록이 가려진 정보를 흘리지 않는다.**

    무정한 말살의 ``@random`` 은 상대 패에서 뽑는다. 그 카드가 **후보에
    적혀 있지 않다** — 적혀 있으면 상대 패를 읽는 길이 된다.
    """
    duel, _, _ = staged(repository, mine=(LUSTER_DRAGON,))
    opponent_hand = {
        c.instance_id for c in duel.state.player(THEIRS).hand
    }
    assert opponent_hand, "상대 패가 비면 이 시험이 말하는 것이 없다"

    for action in activations(duel):
        named = set(action.instance_targets())
        assert not (named & opponent_hand), named
        # 후보는 오직 내 필드의 카드만 가리킨다.
        assert named <= {
            c.instance_id for c in duel.state.player(MINE).monster_zone
        }

    # 정책이 받는 관측에서도 상대 패는 가려져 있다.
    view = duel.view(MINE)
    assert view.opponent.hand.concealed
    assert view.opponent.hand.cards == ()


@pytest.mark.real_card
def test_27_the_search_policy_needs_no_target_branch(repository):
    """
    **§16 — 탐색에 대상 전용 분기를 넣지 않았다.**

    Action 자체가 대상을 들고 있으므로 ``SearchPolicy`` 는 평소대로 후보를
    받아 시뮬레이션하고 점수를 낸다. ``agent/`` 어디에도 대상의 이름이
    없다는 것을 토큰으로 지킨다.
    """
    import re

    forbidden = (
        "TargetSelection",
        "TargetRef",
        "target_combinations",
        "selections_for",
        "ActionTarget",
        "choose_target",
    )
    for path in sorted((ROOT / "agent").glob("*.py")):
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", path.read_text()))
        hits = {t for t in tokens for name in forbidden if name in t}
        assert not hits, (path.name, hits)


@pytest.mark.real_card
def test_28_the_search_policy_picks_a_target_through_evaluation(repository):
    """
    **§16 — 탐색이 대상을 평가로 고른다.** 하드코딩이 아니다.

    무정한 말살은 내 몬스터를 묘지로 보내므로 평가에서는 **손해**다. 그래서
    탐색은 발동하지 않는다. 그런데도 두 대상 중 **덜 손해인 쪽**에 더 높은
    점수를 매긴다 — 공격력이 낮은 몬스터를 보내는 쪽이다. 그것이 평가가
    대상을 구별한다는 증거다.
    """
    from agent import search_policy
    from agent.evaluation import StateEvaluator
    from agent.simulation import SimulationStatus, Simulator

    duel, _, placed = staged(repository, mine=(LUSTER_DRAGON, BATTLE_OX))
    evaluator, simulator = StateEvaluator(), Simulator(duel)

    scored = {}
    for action in activations(duel):
        result = simulator.simulate(action, viewer=MINE)
        assert result.status is SimulationStatus.SUPPORTED
        scored[action.instance_targets()[0]] = evaluator.evaluate(
            result.future
        ).heuristic
    assert len(scored) == 2
    assert len(set(scored.values())) == 2, "대상이 달라도 점수가 같다"

    # 공격력이 낮은 쪽(BATTLE_OX 1700)을 보내는 미래가 더 높다.
    by_card = {
        duel.state.find_instance(instance).card_id: score
        for instance, score in scored.items()
    }
    assert by_card[BATTLE_OX] > by_card[LUSTER_DRAGON]

    policy = search_policy(duel)
    chosen = policy.decide(duel.view(MINE), duel.legal_actions(MINE))
    kinds = {c.action.kind for c in policy.last_decision.candidates}
    assert PlayerActionKind.ACTIVATE_EFFECT in kinds
    # 자기 몬스터를 버리는 것은 손해이므로 고르지 않는다 — 평가의 결과다.
    assert chosen.kind is not PlayerActionKind.ACTIVATE_EFFECT


# ======================================================================
# F. 회귀 (§21)
# ======================================================================


@pytest.mark.real_card
def test_29_every_matchup_still_finishes_with_targets_in_play(repository):
    """
    대상이 있는 효과가 행동 공간에 들어와도 **모든 판이 끝난다.**
    """
    from agent.arena import (
        make_first_legal,
        make_random,
        make_rule_based,
        make_search,
        run_series,
        summarize,
    )

    deck = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [RUTHLESS_DENIAL] * 4
    for label, factories in (
        ("search", (make_search(), make_search())),
        ("rule", (make_rule_based(), make_rule_based())),
        ("random", (make_random(seed=31), make_random(seed=32))),
        ("first", (make_first_legal(), make_first_legal())),
    ):
        summary = summarize(
            run_series(
                repository, decks=(deck, deck), seeds=(1, 2, 3, 4), factories=factories
            )
        )
        assert summary.all_completed, label
        assert summary.refusals == 0, label
        assert summary.errors == 0, label
        assert summary.limits == 0, label


@pytest.mark.real_card
def test_30_a_targeted_activation_really_happens_in_a_played_duel(repository):
    """
    **만든 판이 아니라 굴린 듀얼**에서 대상 발동이 실제로 일어난다.

    정책이 둔 수로 도달한 자리에서 센다 — 후보에 있기만 한 것을 성공으로
    세지 않는다.
    """
    import collections

    from agent.arena import make_random

    deck = [LUSTER_DRAGON] * 10 + [BATTLE_OX] * 6 + [RUTHLESS_DENIAL] * 4
    executed: collections.Counter = collections.Counter()
    with_targets = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        policies = [make_random(seed=seed * 11 + i)(duel, i) for i in (MINE, THEIRS)]
        for _ in range(4000):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            seat = duel.to_act
            legal = duel.legal_actions(seat)
            if not legal.allowed:
                break
            action = policies[seat].decide(duel.view(seat), legal)
            if duel.apply(action).accepted:
                executed[action.kind] += 1
                if (
                    action.kind is PlayerActionKind.ACTIVATE_EFFECT
                    and action.targets
                ):
                    with_targets += 1

    assert executed[PlayerActionKind.ACTIVATE_EFFECT] > 0, dict(executed)
    assert with_targets > 0, "대상이 있는 발동이 한 번도 실행되지 않았다"
    # 기존 행동 종류가 밀려나지 않았다 (§21).
    for kind in (
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.ATTACK,
        PlayerActionKind.END_PHASE,
    ):
        assert executed[kind] > 0, (kind, dict(executed))
