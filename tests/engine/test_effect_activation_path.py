"""
Phase 3-E-3 Implementation — **첫 번째 실제 Effect Action Path**.

    legal_actions
      → ACTIVATE_EFFECT candidate
      → validation
      → Duel.apply
      → NormalSpellPlacement.place      패 → 마법&함정 존 (앞면)
      → EffectActivator.activate        비용 · ChainLink
      → ChainResolver.resolve_top       효과 해결
      → EffectExecutor                  실제 state mutation
      → NormalSpellPlacement.retire     → 묘지
      → Search simulation

이 파일이 지키는 것
-------------------
**지원하지 않는 효과를 ``UNKNOWN`` → ``VALID`` 로 승격하지 않았다.** 범위는
**패의 통상 마법 하나**이고, 그 밖의 모든 카드는 ``UNKNOWN`` 으로 남는다.
``_COMPLETE_RULES`` 에 ``ACTIVATE_EFFECT`` 를 올렸지만 아무것도 넓어지지
않았다는 것을 §B·§D 가 센다.

**``ACTIVATE_CARD`` 는 손대지 않았다.** 발동 계층이 그 ActionKind 를 받지
않으므로 (모양 검사에서 거절) 후보도 실행 경로도 없다. 둘을 하나로 합치지
않았다.

**발동은 ``ActionHandler`` 가 아니다** (STRUCTURAL-55). 발동의 결과물은
``StateDelta`` 만이 아니라 ``Chain`` 이기도 하므로 거기 끼울 수 없고,
``Duel._apply_activation`` 이 ``_apply_board`` 와 **나란히** 따로 있다.

**규칙을 지어내지 않았다.** 순서와 범위가 전부 공식 조항에서 온다 —
RULE-SPELLTRAP-001 · 002 · 004~011, RULE-CHAIN-004 · 009, RULE-TURN-004.
"""

import pathlib
import re

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    ActionValidator,
    ActionValidity,
    ValidationCode,
)
from engine.chain import Chain
from engine.duel import Duel
from engine.effect.delta import CardDrawn
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.spell_activation import (
    ACTIVATION_POSITION,
    ACTIVATION_ZONE,
    AFTER_RESOLUTION_ZONE,
    NormalSpellPlacement,
    SpellPlaced,
    SpellRetired,
    activatable_effects,
)
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: 욕망의 항아리 — 비용 없음 · 대상 없음 · 조작 하나(드로우 2) · 통상 마법.
#: 등록된 16개 중 **가장 단순한** 효과이고, 그래서 이 Phase 의 기준 카드다.
POT_OF_GREED = 55144522
#: 싸이크론 — **속공** 마법. 발동 타이밍이 다르므로 범위 밖 (RULE-SPELLTRAP-007).
MYSTICAL_SPACE_TYPHOON = 5318639
#: 욕망의 선물 — **함정**. 세트가 앞서야 하므로 범위 밖 (RULE-SPELLTRAP-009).
THE_GIFT_OF_GREED = 5915629
#: 블랙홀 — 통상 마법인데 ``executable=False`` 다. 구현이 없으면 후보가 아니다.
DARK_HOLE = 53129443
#: 어리석은 매장 — 통상 마법이지만 **대상**이 있다. 이번 범위 밖.
FOOLISH_BURIAL = 81439173
LUSTER_DRAGON = 11091375

POT_REF = EffectRef(POT_OF_GREED, 0)


# ======================================================================
# 판 만들기 — 전부 실제 엔진으로
# ======================================================================


def staged(repository, *, hand=(POT_OF_GREED,), phase: Phase = Phase.MAIN1):
    """패를 지정한 메인 페이즈의 듀얼 하나. 배치는 ``create_instance`` 다."""
    deck = [LUSTER_DRAGON] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    sources = [
        state.create_instance(card_id, owner=MINE, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    state.turn.set_phase(phase)
    from engine.priority import PriorityState

    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=phase),
    )
    return duel, sources


def real_duel(repository, *, seed: int = 7):
    """**실제로 굴린** 듀얼을 메인 페이즈까지 가져온다."""
    deck = [POT_OF_GREED] * 20 + [LUSTER_DRAGON] * 20
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
    for _ in range(40):
        if duel.state.turn.phase is Phase.MAIN1:
            break
        if duel.advance() is not None:
            continue
        ending = [
            a
            for a in duel.legal_actions().allowed
            if a.kind is PlayerActionKind.END_PHASE
        ]
        if not ending:
            break
        duel.apply(ending[0])
    assert duel.state.turn.phase is Phase.MAIN1
    return duel


def activations(duel: Duel, seat: "int | None" = None):
    seat = duel.to_act if seat is None else seat
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


def board(duel: Duel) -> tuple:
    """§17 L 이 요구하는 mutation surface 전부."""
    return (
        duel.state.state_hash(),
        duel.state.randomness.draws if duel.state.seed is not None else None,
        duel.state.turn.turn_number,
        duel.state.turn.phase,
        duel.step,
        duel.priority,
        duel.result,
        duel.chain.canonical_state(),
        duel.state.rule_uses.canonical_state(),
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


# ======================================================================
# 0. 전제 — 카드와 공식 조항
# ======================================================================


@pytest.mark.real_card
def test_00_the_cards_are_what_we_think_they_are(repository):
    """적어 둔 것을 믿지 않는다. 공식 DB 에서 다시 읽는다."""
    pot = repository.get(POT_OF_GREED)
    assert pot.is_spell and not pot.is_trap
    assert pot.type_names == ["SPELL"], pot.type_names  # 통상 마법 (하위 종류 없음)

    quick = repository.get(MYSTICAL_SPACE_TYPHOON)
    assert "QUICKPLAY" in quick.type_names
    assert repository.get(THE_GIFT_OF_GREED).is_trap
    assert repository.get(DARK_HOLE).type_names == ["SPELL"]


def test_00b_every_rule_id_the_activation_path_cites_really_exists():
    """
    **추측한 규칙이 하나도 없다.** 인용한 조항이 ``rules`` 계층에 실제로 있다.

    두 파일에서 조항 번호를 **소스에서 직접 읽어** 확인한다.
    """
    from rules.rule_repository import RuleRepository

    rules = RuleRepository.load()
    cited: set[str] = set()
    for name in ("engine/spell_activation.py", "engine/action_validation.py"):
        cited |= set(
            re.findall(r"RULE-[A-Z]+-\d{3}", (ROOT / name).read_text())
        )

    assert "RULE-SPELLTRAP-001" in cited
    assert "RULE-SPELLTRAP-002" in cited
    assert "RULE-CHAIN-004" in cited
    for rule_id in sorted(cited):
        section = rules.get(rule_id)
        assert section is not None, f"{rule_id} 가 룰 계층에 없습니다"
        assert section.text, rule_id


def test_00c_the_official_text_says_what_the_placement_layer_does():
    """
    **이 Phase 의 배치 순서가 원문에서 나온다.**

    ``NormalSpellPlacement`` 가 존재하는 이유 전부가 RULE-SPELLTRAP-002 의
    한 문장이다. 그 문장이 룰 계층에 실제로 있는지 본다 — 없으면 이 설계의
    근거가 "모델의 기억" 이 되고, 그것은 근거가 아니다.
    """
    from rules.rule_repository import RuleRepository

    rules = RuleRepository.load()

    def text(rule_id: str) -> str:
        """
        원문을 **고치지 않고** 읽는 쪽에서 합자만 편다.

        공식 룰북 PDF 에서 온 원문에는 ``ﬁ`` (U+FB01) 합자가 들어 있다
        (``ﬁeld``). 이 저장소는 원문을 **그대로** 보존하므로 (전각 공백
        훼손 사고 이후의 규칙) 비교하는 쪽에서 편다. 이 시험을 처음 쓸 때
        평범한 ``field`` 로 적었는데, 그것이 원문이 아니라 **기억에서 나온
        인용**이었다.
        """
        raw = " ".join(rules.get(rule_id).text.split())
        return raw.replace("\ufb01", "fi").replace("\ufb02", "fl")

    normal = text("RULE-SPELLTRAP-002")
    assert "announce its activation to your opponent" in normal
    assert "placing it face-up on the field" in normal
    assert "After resolving the effect, send the card to the Graveyard" in normal

    assert "only during your Main Phase" in text("RULE-SPELLTRAP-001")
    assert (
        "cannot be activated in response to any other effects"
        in text("RULE-CHAIN-004")
    )


# ======================================================================
# A. Action 조립 (§17 A)
# ======================================================================


@pytest.mark.real_card
def test_01_the_two_activate_kinds_build_different_actions(repository):
    """
    ``ACTIVATE_CARD`` 와 ``ACTIVATE_EFFECT`` 를 **하나로 합치지 않았다**.
    """
    duel, (pot,) = staged(repository)

    as_effect = PlayerAction.activate_effect(
        actor=MINE, source=pot, effect_ref=POT_REF
    )
    as_card = PlayerAction.activate_card(actor=MINE, source=pot)

    assert as_effect.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert as_card.kind is PlayerActionKind.ACTIVATE_CARD
    assert as_effect != as_card
    assert as_effect.canonical_state() != as_card.canonical_state()
    assert as_effect.effect_ref == POT_REF
    assert as_card.effect_ref is None


# ======================================================================
# B. 후보 생성 (§17 B · §5 · §6)
# ======================================================================


@pytest.mark.real_card
def test_02_a_real_duel_produces_an_activation_candidate(repository):
    """**실제로 굴린 듀얼**에서 후보가 나온다. 만든 판이 아니다."""
    duel = real_duel(repository)
    found = activations(duel)
    assert found

    seat = duel.to_act
    pots = {
        c.instance_id
        for c in duel.state.player(seat).hand
        if c.card_id == POT_OF_GREED
    }
    assert {a.source for a in found} == pots
    assert all(a.effect_ref == POT_REF for a in found)
    # 턴을 넘기는 선택도 함께 있다 — 발동이 강제가 아니다.
    assert any(
        a.kind is PlayerActionKind.END_PHASE
        for a in duel.legal_actions(seat).allowed
    )


@pytest.mark.real_card
def test_03_each_copy_in_hand_is_its_own_candidate(repository):
    """
    같은 이름 세 장은 **서로 다른 후보**다. 카드 이름으로 식별하면 하나로
    뭉치고, 그러면 "어느 장을 발동했는지" 를 말할 수 없다.
    """
    duel, sources = staged(repository, hand=(POT_OF_GREED,) * 3)
    found = activations(duel, MINE)

    assert len(found) == 3
    assert {a.source for a in found} == set(sources)
    assert len({a.canonical_state() for a in found}) == 3


@pytest.mark.real_card
def test_04_an_unregistered_card_in_the_library_is_not_a_candidate(repository):
    """
    **§18-5 · §18-1 — 구현이 없으면 후보가 아니다** (ADR-006).

    블랙홀은 통상 마법이고 ``EFFECT_LIBRARY`` 에 **실려 있다.** 그런데
    ``executable=False`` 다 (파괴 판정 계층과 "필드의 몬스터 전부" 를 옮길 수
    없어서 일부러 그렇게 뒀다). 그래서 후보가 되지 않는다.

    "목록에 있다" ≠ "발동할 수 있다".
    """
    assert activatable_effects(DARK_HOLE) == ()

    duel, _ = staged(repository, hand=(DARK_HOLE,))
    assert activations(duel, MINE) == []
    # 세트는 된다 — 그 카드로 할 수 있는 다른 일이 사라진 것이 아니다.
    assert any(
        a.kind is PlayerActionKind.SET_SPELL_TRAP
        for a in duel.legal_actions(MINE).allowed
    )


@pytest.mark.real_card
def test_05_a_card_with_no_definition_at_all_is_not_a_candidate(repository):
    """
    목록에 **없는** 카드는 후보가 되지 않는다. 통상 몬스터로 확인한다.
    """
    assert activatable_effects(LUSTER_DRAGON) == ()
    duel, _ = staged(repository, hand=(LUSTER_DRAGON,))
    assert activations(duel, MINE) == []


@pytest.mark.real_card
@pytest.mark.parametrize(
    "card_id,why",
    [
        (MYSTICAL_SPACE_TYPHOON, "속공 마법 — RULE-SPELLTRAP-007"),
        (THE_GIFT_OF_GREED, "함정 — RULE-SPELLTRAP-009"),
        (FOOLISH_BURIAL, "대상이 **덱**에 있다 — 정책이 볼 수 없는 자리"),
    ],
)
def test_06_out_of_scope_cards_are_not_candidates(repository, card_id, why):
    """
    **§18-2 · §18-4 — 범위 밖은 후보가 아니다.**

    셋 다 ``executable=True`` 인데도 후보가 아니다. 이유가 서로 다르고, 그
    차이를 다음 시험들이 각각 적는다.

    **어리석은 매장의 이유가 Phase 3-E-4 에서 달라졌다.** 그때는 "대상을
    건넬 길이 없다" (STRUCTURAL-121) 였고, 이제 길은 있다. 그런데도 후보가
    아닌 이유는 그 대상이 **덱**에 있기 때문이다 — ``PlayerAction`` 은
    정책에게 가는 데이터이므로 거기에 덱의 카드를 적으면 후보 목록을 읽는
    것만으로 덱 내용이 새어 나간다 (STRUCTURAL-125,
    ``test_18b`` 가 이 사실을 따로 적는다).
    """
    assert activatable_effects(card_id), "executable 이 아니면 이 시험이 흐려진다"
    duel, _ = staged(repository, hand=(card_id,))
    assert activations(duel, MINE) == [], why


@pytest.mark.real_card
@pytest.mark.parametrize("phase", [Phase.DRAW, Phase.STANDBY, Phase.BATTLE, Phase.END])
def test_07_no_candidate_outside_the_main_phase(repository, phase):
    """
    **§17 C** — 통상 마법은 자기 메인 페이즈의 행위다 (RULE-SPELLTRAP-001).
    """
    duel, _ = staged(repository, phase=phase)
    assert activations(duel, MINE) == []


@pytest.mark.real_card
def test_08_no_candidate_for_the_player_whose_turn_it_is_not(repository):
    """자기 턴이 아니면 후보가 아니다 (RULE-CHAIN-009)."""
    duel, (pot,) = staged(repository)
    duel.state.turn.turn_player = THEIRS
    assert activations(duel, MINE) == []


@pytest.mark.real_card
def test_09_no_candidate_when_there_is_nowhere_to_put_the_card(repository):
    """
    마법 & 함정 존이 꽉 차면 후보가 아니다 — 발동은 **놓는** 행위이기
    때문이다 (RULE-SPELLTRAP-002: "placing it face-up on the field").
    """
    duel, (pot,) = staged(repository)
    for _ in range(5):
        filler = duel.state.create_instance(
            THE_GIFT_OF_GREED, owner=MINE, zone=Zone.HAND
        )
        duel.state.move(
            filler, Zone.SZONE, to_player=MINE, position=Position.FACEDOWN
        )
    assert len(duel.state.player(MINE).spell_zone) == 5

    assert activations(duel, MINE) == []
    result = ActionValidator(duel.view(MINE)).validate(
        PlayerAction.activate_effect(actor=MINE, source=pot, effect_ref=POT_REF)
    )
    assert result.code is ValidationCode.ZONE_FULL


@pytest.mark.real_card
def test_10_no_candidate_when_the_activation_condition_is_false(repository):
    """
    **발동 조건이 거짓이면 후보가 아니다.**

    욕망의 항아리의 조건은 ``ZoneCountAtLeast(CONTROLLER, DECK, 2)`` 이고,
    그것은 ``c55144522.lua`` 의 ``Duel.IsPlayerCanDraw(tp,2)`` 에서 옮긴
    것이다. 덱을 1장으로 만들면 후보가 사라진다 — 검증기가 아니라
    **발동 계층**이 거른 것이다 (검증기는 덱 장수를 요구로 갖지 않는다).
    """
    duel, (pot,) = staged(repository)
    deck = duel.state.player(MINE).deck
    while len(deck) > 1:
        duel.state.move(deck.cards()[0], Zone.REMOVED, to_player=MINE)
    assert len(duel.state.player(MINE).deck) == 1

    assert activations(duel, MINE) == []
    # 검증기 혼자서는 통과시킨다 — 두 관문이 따로라는 증거다.
    assert (
        ActionValidator(duel.view(MINE))
        .validate(
            PlayerAction.activate_effect(actor=MINE, source=pot, effect_ref=POT_REF)
        )
        .validity
        is ActionValidity.VALID
    )


@pytest.mark.real_card
def test_11_no_candidate_while_a_chain_is_already_building(repository):
    """
    **RULE-CHAIN-004** — 스펠 스피드 1 은 다른 효과에 응답할 수 없다.

    체인은 ``GameState`` 밖에 살고 검증기는 관측만 읽으므로 (ADR-007), 이
    요구는 체인을 들고 있는 ``Duel`` 이 본다. 검증기 혼자서는 통과시킨다.
    """
    from engine.chain import ChainLink

    duel, (pot,) = staged(repository)
    assert activations(duel, MINE)

    duel.chain = Chain().push(
        ChainLink(sequence=0, actor=THEIRS, effect_ref=POT_REF)
    )
    assert not duel.chain.is_empty
    assert activations(duel, MINE) == []

    assert (
        ActionValidator(duel.view(MINE))
        .validate(
            PlayerAction.activate_effect(actor=MINE, source=pot, effect_ref=POT_REF)
        )
        .validity
        is ActionValidity.VALID
    )


# ======================================================================
# C~H. 실행 — 발동 · 체인 · 해결 · state mutation (§17 E~I)
# ======================================================================


@pytest.mark.real_card
def test_12_the_whole_path_runs_through_duel_apply(repository):
    """
    **§17 E·F·G·H·I 를 한 자리에서 센다.** 이 Phase 의 한 줄이다.

        발동 → 배치 → ChainLink → 해결 → 드로우 2 → 묘지

    숫자로 확인한다. 패는 **1장 줄고 2장 늘어** 결과적으로 +1 이다.
    """
    duel, (pot,) = staged(repository)
    player = duel.state.player(MINE)
    deck_before, hand_before = len(player.deck), len(player.hand)
    assert hand_before == 1 and deck_before == 20

    action = activations(duel, MINE)[0]
    step = duel.apply(action)

    assert step.accepted, step.reason
    assert step.code is ValidationCode.OK
    assert "체인1" in step.reason

    # 드로우 2 가 실제로 일어났다.
    assert len(player.deck) == deck_before - 2 == 18
    assert len(player.hand) == hand_before - 1 + 2 == 2
    # 발동한 카드는 묘지에 있다 (RULE-SPELLTRAP-002).
    assert [c.instance_id for c in player.grave] == [pot]
    assert len(player.spell_zone) == 0
    # 체인은 비워졌다 — 다음 발동이 체인 1 부터 시작한다.
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_13_the_card_passes_through_the_field_face_up(repository):
    """
    **발동은 놓는 행위다** (RULE-SPELLTRAP-002).

    해결이 끝나면 묘지에 있으므로 중간 상태를 ``Duel.apply`` 밖에서는 볼 수
    없다. 그래서 배치 계층을 **직접** 불러 그 한 걸음을 확인한다.
    """
    duel, (pot,) = staged(repository)
    placement = NormalSpellPlacement()

    placed = placement.place(duel.state, pot, MINE)
    assert isinstance(placed, SpellPlaced)
    card = duel.state.find_instance(pot)
    assert card.zone is ACTIVATION_ZONE is Zone.SZONE
    assert card.position is ACTIVATION_POSITION is Position.FACEUP
    assert card.is_faceup
    assert len(duel.state.player(MINE).hand) == 0

    retired = placement.retire(duel.state, placed)
    assert isinstance(retired, SpellRetired)
    assert duel.state.find_instance(pot).zone is AFTER_RESOLUTION_ZONE is Zone.GRAVE


def test_14_the_placement_deltas_claim_nothing_they_did_not_do():
    """
    배치 델타가 **주장하지 않는 것.** 이 이동은 규칙이고 효과가 아니다.

    ``reason_names`` 에 ``EFFECT`` 를 적으면 트리거 계층이 "효과로 묘지에
    갔다" 로 읽고, "효과로 묘지로 보내졌을 때" 를 조건으로 하는 카드가 잘못
    반응한다 (``CardSet`` 이 비워 둔 것과 같은 자리).
    """
    from engine.effect.delta import CardMovement
    from engine.effect.operation import OperationKind
    from engine.ids import InstanceId

    placed = SpellPlaced(
        card=InstanceId(3),
        player=MINE,
        owner=MINE,
        source_player=MINE,
        source_zone=Zone.HAND,
        destination_zone=Zone.SZONE,
        position=Position.FACEUP,
    )
    assert isinstance(placed, CardMovement)
    assert placed.kind == "spell_placed"
    assert placed.operation is OperationKind.MOVE
    assert placed.reason_names == ()
    assert placed.to_dict()["by_effect"] is False
    assert "해결 전" in placed.describe_ko()

    retired = SpellRetired(
        card=InstanceId(3),
        player=MINE,
        owner=MINE,
        source_player=MINE,
        source_zone=Zone.SZONE,
        destination_zone=Zone.GRAVE,
    )
    assert retired.reason_names == ()
    assert "효과가 아니라 규칙" in retired.describe_ko()


@pytest.mark.real_card
def test_15_the_resolution_leaves_draw_deltas_marked_as_effect(repository):
    """
    **효과로 뽑은 것은 효과로 적힌다** — 배치와 구분된다.

    같은 발동 안에서 배치는 ``reason_names == ()`` 이고 드로우는
    ``EFFECT`` 를 달고 있다. 둘이 다른 사건이라는 것이 기록에 남는다.
    """
    from engine.activation import EffectActivator
    from engine.chain import ChainResolver
    from engine.effect.library import (
        build_executor,
        definition_registry,
        implementation_registry,
    )
    from engine.validation import ValidationResult

    duel, (pot,) = staged(repository)
    definitions = definition_registry()
    activator = EffectActivator(definitions, implementation_registry())
    action = PlayerAction.activate_effect(
        actor=MINE, source=pot, effect_ref=POT_REF
    )
    granted = ValidationResult.valid("test")

    activated = activator.activate(duel.state, Chain(), action, authorization=granted)
    assert activated.activated
    assert len(activated.chain) == 1
    assert activated.link.effect_ref == POT_REF
    assert activated.deltas == (), "비용이 없으므로 발동만으로는 판이 안 바뀐다"

    resolved = ChainResolver(build_executor(), definitions).resolve_top(
        duel.state, activated.chain
    )
    drawn = [d for d in resolved.deltas if isinstance(d, CardDrawn)]
    assert len(drawn) == 2
    for delta in drawn:
        assert "EFFECT" in delta.reason_names
        assert "DRAW" in delta.reason_names


@pytest.mark.real_card
def test_16_two_activations_in_one_turn_both_work(repository):
    """
    **턴 1회 제약을 넣지 않았다** — RULE-TURN-004 가 "activate ... as many
    times as you want during this phase" 라고 적는다.

    없는 규칙을 지어내지 않았다는 증거이고, 동시에 체인이 매번 비워져
    다음 발동이 체인 1 부터 시작한다는 증거다.
    """
    duel, sources = staged(repository, hand=(POT_OF_GREED, POT_OF_GREED))
    player = duel.state.player(MINE)

    first = activations(duel, MINE)[0]
    assert duel.apply(first).accepted
    assert duel.chain.is_empty

    remaining = activations(duel, MINE)
    assert len(remaining) == 1
    assert duel.apply(remaining[0]).accepted

    assert len(player.deck) == 16
    assert len(player.grave) == 2
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_17_activation_is_not_an_action_handler(repository):
    """
    **STRUCTURAL-55 를 깨지 않았다.** ``ActionExecutor`` 에 발동이 없다.

    발동의 결과물은 ``StateDelta`` 만이 아니라 ``Chain`` 이기도 하므로
    ``ActionHandler`` 에 끼울 수 없다. 끼우면 체인을 어딘가 숨겨 두고
    주고받아야 하고, 숨긴 통로는 통로가 아니다.
    """
    executor = duel_executor()
    assert executor.handler_for(PlayerActionKind.ACTIVATE_EFFECT) is None
    assert executor.handler_for(PlayerActionKind.ACTIVATE_CARD) is None

    source = (ROOT / "engine/duel.py").read_text()
    assert "def _apply_activation" in source
    assert "def _apply_board" in source


# ======================================================================
# I. ACTIVATE_CARD 는 그대로다 (§3 · §18)
# ======================================================================


@pytest.mark.real_card
def test_18_activate_card_has_no_path_at_all(repository):
    """
    **§18-4 — 지원하지 않는 것을 승격하지 않았다.**

    ``ACTIVATE_CARD`` 는 후보도 없고, 검증기가 허가하지 않고,
    ``Duel.apply`` 가 거절하고, 판이 바뀌지 않는다.
    """
    duel, (pot,) = staged(repository)
    action = PlayerAction.activate_card(actor=MINE, source=pot)
    before = board(duel)

    assert not [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    verdict = ActionValidator(duel.view(MINE)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert not verdict.permits_execution

    step = duel.apply(action)
    assert not step.accepted
    assert board(duel) == before


# ======================================================================
# J~N. 탐색 · 안전 (§17 J~N · §13 · §14 · §15)
# ======================================================================


@pytest.mark.real_card
def test_19_the_simulator_runs_the_activation_without_touching_the_duel(repository):
    """
    **§17 J·K·L** — 사본에서는 일어나고 원본은 그대로다.
    """
    from agent.simulation import SimulationStatus, Simulator

    duel = real_duel(repository)
    seat = duel.to_act
    action = activations(duel)[0]
    simulator = Simulator(duel)
    before = board(duel)

    result = simulator.simulate(action, viewer=seat)
    assert result.status is SimulationStatus.SUPPORTED, result.reason
    assert isinstance(result.future, GameStateView)

    # 사본에서는 실제로 일어났다.
    assert result.future.me.deck.size == duel.state.player(seat).deck.__len__() - 2
    assert result.future.me.grave.size == len(duel.state.player(seat).grave) + 1

    # 원본은 **한 글자도** 바뀌지 않았다 — 체인도 뽑기 수도 그대로다.
    assert board(duel) == before
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_20_many_simulations_do_not_drift_the_duel(repository):
    """
    **§17 M — 사본의 독립.** 몇 번 해 봐도 원본이 흔들리지 않는다.

    ``Chain`` 은 불변이므로 사본과 공유해도 안전하다 — 링크를 쌓으면 새
    ``Chain`` 이 나오고 그것을 받는 ``Duel`` 만 달라진다. 이 시험이 그것을
    지킨다.
    """
    from agent.simulation import Simulator

    duel = real_duel(repository)
    seat = duel.to_act
    simulator = Simulator(duel)
    before = board(duel)

    for _ in range(5):
        for action in duel.legal_actions(seat).allowed:
            simulator.simulate(action, viewer=seat)

    assert board(duel) == before


@pytest.mark.real_card
def test_21_the_simulation_matches_what_really_happens(repository):
    """해 본 것과 실제로 한 것이 **같다.** 다르면 탐색은 헛것을 본다."""
    from agent.simulation import Simulator

    duel = real_duel(repository)
    seat = duel.to_act
    action = activations(duel)[0]

    simulated = Simulator(duel).simulate(action, viewer=seat).future
    assert duel.apply(action).accepted
    assert simulated.canonical_state() == duel.view(seat).canonical_state()


@pytest.mark.real_card
def test_22_the_game_rng_advances_only_in_the_real_duel(repository):
    """
    **§17 N — RNG 격리.** 사본에서 뽑은 것이 원본의 뽑기 수에 남지 않는다.

    ``state.clone()`` 이 난수원까지 복제하므로 ``project()`` 와 다르다 —
    탐색이 반드시 ``clone`` 을 써야 하는 이유다.
    """
    from agent.simulation import Simulator

    duel = real_duel(repository)
    seat = duel.to_act
    draws_before = duel.state.randomness.draws

    simulator = Simulator(duel)
    for _ in range(3):
        simulator.simulate(activations(duel)[0], viewer=seat)
    assert duel.state.randomness.draws == draws_before

    assert duel.apply(activations(duel)[0]).accepted
    # 드로우는 섞기가 아니다 — 이 효과는 난수를 쓰지 않는다.
    assert duel.state.randomness.draws == draws_before


@pytest.mark.real_card
def test_23_the_opponent_does_not_learn_what_was_drawn(repository):
    """
    **§13 · §17 O — 관측 경계.**

    발동한 카드는 상대에게 **보인다** (앞면으로 필드에 놓았으므로 —
    RULE-SPELLTRAP-002). 그 효과로 뽑은 카드는 **보이지 않는다.**
    장수는 공개이고 정체는 비공개다.
    """
    duel, (pot,) = staged(repository)
    assert duel.apply(activations(duel, MINE)[0]).accepted

    theirs = duel.view(THEIRS)
    assert theirs.opponent.hand.size == 2  # 장수는 공개
    assert theirs.opponent.hand.concealed  # 내용은 비공개
    assert theirs.opponent.hand.cards == ()

    # 묘지로 간 발동 카드는 양쪽에 보인다.
    assert [c.card_id for c in theirs.opponent.grave.occupied()] == [POT_OF_GREED]
    assert [c.card_id for c in duel.view(MINE).me.grave.occupied()] == [POT_OF_GREED]


@pytest.mark.real_card
def test_24_no_policy_ever_receives_a_raw_game_state(repository):
    """
    발동이 들어와도 Phase 3-A 의 경계가 그대로다 — 정책은 관측과 목록만 본다.
    """
    duel = real_duel(repository)
    seat = duel.to_act
    seen = []

    class Spy:
        name = "spy"

        def decide(self, view, legal):
            seen.append((view, legal))
            return legal.allowed[0]

    Spy().decide(duel.view(seat), duel.legal_actions(seat))
    view, legal = seen[0]
    assert isinstance(view, GameStateView)
    assert not hasattr(view, "apply")
    assert not hasattr(view, "randomness")
    assert all(isinstance(a, PlayerAction) for a in legal.allowed)


@pytest.mark.real_card
def test_25_the_search_policy_needs_no_activation_branch(repository):
    """
    **§15 — 탐색에 발동 전용 분기를 넣지 않았다.**

    후보 목록이 넓어진 것만으로 저절로 들어오고, 시뮬레이션되고, 점수를
    받는다. ``agent/`` 어디에도 발동의 이름이 없다는 것을 AST 토큰으로
    지킨다 (Phase 3-E-2 가 세트에 쓴 것과 같은 자리).
    """
    import re as _re

    forbidden = (
        "ACTIVATE_CARD",
        "ACTIVATE_EFFECT",
        "activate_card",
        "activate_effect",
        "EffectRef",
        "effect_ref",
        "SpellPlaced",
    )
    for path in sorted((ROOT / "agent").glob("*.py")):
        tokens = set(_re.findall(r"[A-Za-z_][A-Za-z_0-9]*", path.read_text()))
        hits = {t for t in tokens for name in forbidden if name in t}
        assert not hits, (path.name, hits)


@pytest.mark.real_card
def test_26_the_evaluator_scores_the_activation_without_being_told_about_it(
    repository,
):
    """
    **§16 — 평가가 저절로 반영된다.** 평가 함수를 고치지 않았다.

    욕망의 항아리를 발동한 미래는 덱이 2장 줄고 패가 1장 늘어난 판이고,
    평가가 그것을 **그대로** 센다. 발동이라서 점수를 준 것이 아니다.
    """
    from agent.evaluation import DECK_CARD_IN_LP, HAND_CARD_IN_LP, StateEvaluator
    from agent.simulation import Simulator

    duel = real_duel(repository)
    seat = duel.to_act
    evaluator, simulator = StateEvaluator(), Simulator(duel)

    now = evaluator.evaluate(duel.view(seat))
    after = evaluator.evaluate(
        simulator.simulate(activations(duel)[0], viewer=seat).future
    )

    # 덱 −2 · 패 +1 이 그대로 숫자로 나온다.
    assert dict(after.terms)["deck"] - dict(now.terms)["deck"] == -2 * DECK_CARD_IN_LP
    assert dict(after.terms)["hand"] - dict(now.terms)["hand"] == 1 * HAND_CARD_IN_LP
    assert after.heuristic - now.heuristic == -2 * DECK_CARD_IN_LP + HAND_CARD_IN_LP


@pytest.mark.real_card
def test_27_search_declines_the_activation_and_we_say_why(repository):
    """
    **고르지 않는다는 사실을 숨기지 않는다.**

    탐색은 발동을 후보로 받고 시뮬레이션하고 점수까지 매기지만 **고르지
    않는다.** 평가에서 손해이기 때문이다 — Phase 3-C 가 실측으로 정한
    가중치가 덱 한 장(300)을 패 한 장(200)보다 높게 보므로, 2장을 뽑는 것은

        덱 −600 + 패 +400 − (발동한 카드가 패를 떠남) 200 = **−400**

    이다. 턴을 넘기는 것보다 400 낮다.

    **가중치를 고쳐서 고르게 만들지 않았다** (§16). 그렇게 하면 "AI 가
    발동을 쓴다" 가 측정이 아니라 주문이 된다. 덱아웃이 패배 조건이라는
    Phase 3-C 의 근거는 그대로 옳고, 모자란 것은 "뽑은 카드로 무엇을 할 수
    있는가" 를 담는 계층이다 — 그것은 Depth-1 로 볼 수 없다.
    """
    from agent import search_policy
    from agent.simulation import SimulationStatus

    duel = real_duel(repository)
    seat = duel.to_act
    policy = search_policy(duel)
    chosen = policy.decide(duel.view(seat), duel.legal_actions(seat))

    assert chosen.kind is not PlayerActionKind.ACTIVATE_EFFECT
    candidates = {c.action.kind: c for c in policy.last_decision.candidates}
    assert PlayerActionKind.ACTIVATE_EFFECT in candidates

    offered = candidates[PlayerActionKind.ACTIVATE_EFFECT]
    assert offered.status is SimulationStatus.SUPPORTED
    assert offered.value is not None, "해 보고 점수를 냈다"
    ending = candidates[PlayerActionKind.END_PHASE]
    assert offered.value.heuristic == ending.value.heuristic - 400


@pytest.mark.real_card
def test_28_the_rule_based_policy_selects_it_without_any_rule_valuing_it(repository):
    """
    **왜 규칙 기반이 발동을 고르는가** — 측정한 그대로 적는다.

    규칙 기반에는 발동을 보는 규칙이 **하나도 없다.** 그래서 모든 발동
    후보가 0 점으로 ``END_PHASE`` 와 동점이 되고, 동점은
    ``canonical_state()`` 가 가르는데 ``"activate_effect" < "end_phase"`` 다.
    그래서 **알파벳 순서 때문에** 발동이 이긴다.

    이것을 "규칙 기반 AI 가 발동을 활용한다" 로 적지 않는다. Phase 3-E-2 에서
    세트가 같은 자리에서 **졌던** 것과 같은 메커니즘이고 (``"end_phase" <
    "set_spell_trap"``), 방향만 반대다.
    """
    from agent import rule_based_policy

    duel = real_duel(repository)
    seat = duel.to_act
    policy = rule_based_policy()
    evaluations = {
        e.action.kind: e
        for e in policy.evaluate(duel.view(seat), duel.legal_actions(seat))
    }

    activation = evaluations[PlayerActionKind.ACTIVATE_EFFECT]
    assert activation.total == 0
    assert activation.appraisals == ()
    assert len(activation.abstained) == len(policy.considerations)
    assert evaluations[PlayerActionKind.END_PHASE].total == 0
    assert "activate_effect" < "end_phase"


# ======================================================================
# P. 회귀 — 기존 행동 공간이 그대로다 (§17 P · §19)
# ======================================================================


@pytest.mark.real_card
def test_29_every_matchup_still_finishes(repository):
    """
    행동 공간이 또 넓어졌는데도 **모든 판이 끝난다** — 거절도 예외도 상한도
    없다. 발동이 끝나지 않는 듀얼을 만들지 않았다는 증거다.
    """
    from agent.arena import (
        make_first_legal,
        make_random,
        make_rule_based,
        make_search,
        run_series,
        summarize,
    )

    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 8
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
def test_30_the_older_action_kinds_still_appear(repository):
    """
    **§19 — ATTACK · SET · NORMAL_SUMMON 이 사라지지 않았다.**

    발동을 더하면서 기존 후보를 밀어내지 않았다는 것을 실제 듀얼에서 센다.
    """
    import collections

    from agent.arena import make_random

    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 8
    kinds: collections.Counter = collections.Counter()
    for seed in (1, 2, 3, 4):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        policies = [make_random(seed=seed * 7 + i)(duel, i) for i in (MINE, THEIRS)]
        for _ in range(4000):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            seat = duel.to_act
            legal = duel.legal_actions(seat)
            if not legal.allowed:
                break
            for action in legal.allowed:
                kinds[action.kind] += 1
            duel.apply(policies[seat].decide(duel.view(seat), legal))

    for kind in (
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.ATTACK,
        PlayerActionKind.END_PHASE,
        PlayerActionKind.ACTIVATE_EFFECT,
    ):
        assert kinds[kind] > 0, (kind, dict(kinds))
    assert kinds[PlayerActionKind.ACTIVATE_CARD] == 0
    assert kinds[PlayerActionKind.CHANGE_POSITION] == 0
