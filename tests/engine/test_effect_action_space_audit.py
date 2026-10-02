"""
Phase 3-E-3 — Effect Action Space **Audit** (조사 전용).

이 파일은 기능을 넣지 않는다. **지금 사실인 것을 실행 가능한 주장으로
고정한다** — 다음 Phase 가 무엇을 바꾸는지 이 파일이 깨지는 것으로 보인다.

조사한 경로
-----------
    GameStateView
      → legal_actions          ACTIVATE 후보가 나오는가      → 0건
      → validation             VALID 이 나오는가             → 영원히 UNKNOWN
      → Duel.apply             실행되는가                    → 거절
      ────────────────────────────────────────────────────────────
      → EffectActivator        손으로 부르면 되는가          → 된다
      → CostPayer              비용 경로가 있는가            → 있다 (라이브러리에 비용 효과 0건)
      → Chain                  링크가 쌓이는가               → 쌓인다
      → ChainResolver          해결되는가                    → 된다
      → EffectExecutor         판이 바뀌는가                 → 바뀐다

끊어진 곳이 **한 군데**다
-------------------------
발동·체인·해결·효과 실행은 **전부 동작한다.** 동작하지 않는 것은
``PlayerAction`` 에서 거기로 들어가는 길이다. ``Duel`` 은 ``Chain`` 을 들고
있지 않고, ``ActionExecutor`` 에는 발동 수행기가 등록되어 있지 않으며,
``engine/activation.py`` 의 설명이 **그것이 의도였다**고 적고 있다
(STRUCTURAL-55).

이름만 있는 것과 실제로 있는 것
-------------------------------
``ACTIVATE_CARD`` 와 ``ACTIVATE_EFFECT`` 는 둘 다 열거형에 있고 생성자도
있다. 그러나 **발동 계층은 ``ACTIVATE_EFFECT`` 만 받는다** — ``ACTIVATE_CARD``
는 모양 검사에서 거절된다. 둘을 같은 것으로 적지 않는다.
"""

import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionStatus
from engine.action_validation import (
    _COMPLETE_RULES,
    _MISSING_RULE,
    ActionValidator,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolver
from engine.cost import Selection
from engine.duel import Duel
from engine.effect.delta import CardDrawn
from engine.effect.library import (
    EFFECT_LIBRARY,
    build_executor,
    definition_registry,
    implementation_registry,
)
from engine.effect.target import TargetRef, TargetSelection
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: 욕망의 항아리 — 비용 없음 · 대상 없음 · 조작 하나(드로우 2). 이 목록에서
#: **가장 단순한** 효과이고, 그래서 Audit 의 기준 카드다.
POT_OF_GREED = 55144522
#: 싸이크론 — 대상이 있는 효과. 뒷면 대상이 ``UNKNOWN`` 을 만드는 자리.
MYSTICAL_SPACE_TYPHOON = 5318639
TRAP_HOLE = 4206964
LUSTER_DRAGON = 11091375


# ======================================================================
# 판 만들기
# ======================================================================


def hand_with(repository, card_id: int, *, deck_filler: int = LUSTER_DRAGON):
    """패에 그 카드 한 장을 쥔 메인 페이즈의 판."""
    state = GameState.create(
        repository, decks=([card_id, deck_filler] * 10, [deck_filler] * 20), seed=1
    )
    source = state.create_instance(card_id, owner=MINE, zone=Zone.HAND).instance_id
    state.turn.set_phase(Phase.MAIN1)
    return state, source


def main_phase_duel(repository, *, card_id: int = POT_OF_GREED):
    """**실제로 굴린** 듀얼을 메인 페이즈까지 가져온다."""
    deck = [card_id] * 20 + [LUSTER_DRAGON] * 20
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=7)
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


def board(duel: Duel) -> tuple:
    """판이 바뀌었는지 보는 데 쓰는 스냅숏."""
    return (
        duel.state.state_hash(),
        duel.state.randomness.draws if duel.state.seed is not None else None,
        tuple(
            (
                duel.state.player(seat).life_points,
                tuple(
                    len(duel.state.player(seat).zone(z))
                    for z in (Zone.DECK, Zone.HAND, Zone.MZONE, Zone.SZONE, Zone.GRAVE)
                ),
            )
            for seat in (MINE, THEIRS)
        ),
        duel.state.rule_uses.canonical_state(),
    )


# ======================================================================
# 1. 두 ACTIVATE 는 **다른 것**이다 (§2)
# ======================================================================


@pytest.mark.real_card
def test_01_both_activate_kinds_exist_and_are_not_the_same_thing(repository):
    """
    열거형에 둘 다 있고, **뜻이 다르다.** 합쳐서 설명하지 않는다.

    ``ACTIVATE_CARD``   카드 자체의 발동 (마법 · 함정). ``effect_ref`` 는
                        가질 수 **있지만** 필수가 아니다
    ``ACTIVATE_EFFECT`` 카드가 가진 **특정 효과** — ``effect_ref`` 로 지목한다.
                        없으면 모양이 틀린 것이다

    모양 검사가 **생성자가 아니라 검증기에** 있다. ``PlayerAction`` 은
    ``effect_ref=None`` 인 효과 발동도 만들어 주고, ``validate_structure`` 가
    ``EFFECT_REF_REQUIRED`` 로 거절한다. (이 시험을 처음 쓸 때 생성자가
    거절한다고 가정했는데, 그것이 틀렸다 — 거절하는 자리가 한 단계 뒤다.)
    """
    assert PlayerActionKind.ACTIVATE_CARD.value == "activate_card"
    assert PlayerActionKind.ACTIVATE_EFFECT.value == "activate_effect"
    assert PlayerActionKind.ACTIVATE_CARD is not PlayerActionKind.ACTIVATE_EFFECT

    card = PlayerAction.activate_card(actor=MINE, source=None)
    assert card.effect_ref is None, "카드 발동은 효과를 지목하지 않아도 된다"

    state, source = hand_with(repository, POT_OF_GREED)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    # 생성자는 막지 않는다 ...
    shapeless = PlayerAction(
        kind=PlayerActionKind.ACTIVATE_EFFECT,
        actor=MINE,
        source=source,
        effect_ref=None,
    )
    # ... 검증기가 막는다.
    refused = validator.validate_structure(shapeless)
    assert refused.validity is ActionValidity.INVALID
    assert refused.code is ValidationCode.EFFECT_REF_REQUIRED

    # 카드 발동은 같은 자리에서 통과한다 — effect_ref 가 필수가 아니다.
    fine = validator.validate_structure(
        PlayerAction.activate_card(actor=MINE, source=source)
    )
    assert fine.validity is ActionValidity.VALID, fine.reason


def test_02_the_validator_does_not_tell_the_two_apart_yet():
    """
    **검증기는 둘을 구분하지 않는다** — 같은 요구 하나를 쓴다.

    이것이 결함이라는 뜻이 아니다. 발동 타이밍 계층이 없으므로 구분할
    근거가 아직 없고, 없는 것을 지어내지 않은 결과다. 다음 Phase 가
    구분하면 이 시험이 깨진다.
    """
    from engine.action_validation import _REQUIREMENT_BUILDERS, _activate

    assert _REQUIREMENT_BUILDERS[PlayerActionKind.ACTIVATE_CARD] is _activate
    assert _REQUIREMENT_BUILDERS[PlayerActionKind.ACTIVATE_EFFECT] is _activate


def test_03_the_activation_layer_only_accepts_activate_effect(repository):
    """
    **발동 계층은 ``ACTIVATE_EFFECT`` 만 받는다.**

    ``ACTIVATE_CARD`` 는 모양 검사에서 거절된다 — 손으로 불러도 실행 경로가
    **없다.** "열거형에 있다" 가 "실행할 수 있다" 가 아니라는 가장 짧은 증거다.
    """
    state, source = hand_with(repository, POT_OF_GREED)
    activator = EffectActivator(definition_registry(), implementation_registry())
    ref = EffectRef(POT_OF_GREED, 0)
    granted = ValidationResult.valid("audit: 바깥에서 준 허가")

    as_card = PlayerAction.activate_card(actor=MINE, source=source, effect_ref=ref)
    refused = activator.activate(state, Chain(), as_card, authorization=granted)
    assert refused.status is ActivationStatus.INVALID_ACTION
    assert "효과 발동이 아닙니다" in refused.reason
    assert len(refused.chain) == 0

    as_effect = PlayerAction.activate_effect(
        actor=MINE, source=source, effect_ref=ref
    )
    accepted = activator.activate(state, Chain(), as_effect, authorization=granted)
    assert accepted.status is ActivationStatus.ACTIVATED


# ======================================================================
# 2. 검증기는 **영원히** 허가를 내지 않는다 (§7)
# ======================================================================


@pytest.mark.parametrize(
    "kind", [PlayerActionKind.ACTIVATE_CARD, PlayerActionKind.ACTIVATE_EFFECT]
)
def test_04_neither_activate_kind_can_ever_be_valid(kind):
    """
    둘 다 ``_MISSING_RULE`` 에 있고 ``_COMPLETE_RULES`` 에 없다.

    그래서 요구를 전부 통과해도 결과는 ``UNKNOWN`` 이다. **``UNKNOWN`` 은
    허가가 아니므로** 후보가 되지 않는다 — 이것이 ACTIVATE 후보가 0건인
    구조적 이유다.
    """
    assert kind in _MISSING_RULE
    assert kind not in _COMPLETE_RULES


@pytest.mark.real_card
def test_05_a_perfectly_fine_activation_is_still_unknown(repository):
    """
    **확인할 수 있는 것은 전부 통과했는데도** 허가가 아니다.

    자기 패의 카드 · 자기 턴 · 메인 페이즈 · 덱 20장. 그래도 ``UNKNOWN`` 이고,
    ``missing_rule`` 이 무엇이 없는지 말한다.
    """
    state, source = hand_with(repository, POT_OF_GREED)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    for action, expected in (
        (
            PlayerAction.activate_card(actor=MINE, source=source),
            "activation-timing",
        ),
        (
            PlayerAction.activate_effect(
                actor=MINE, source=source, effect_ref=EffectRef(POT_OF_GREED, 0)
            ),
            "activation-condition",
        ),
    ):
        result = validator.validate(action)
        assert result.validity is ActionValidity.UNKNOWN
        assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert expected in result.missing_rule
        assert not result.permits_execution


# ======================================================================
# 3. legal_actions — 후보가 **0건**이다 (§5)
# ======================================================================


@pytest.mark.real_card
def test_06_a_real_duel_offers_zero_activate_candidates(repository):
    """
    **실제로 굴린 듀얼**에서 센다. 패에 욕망의 항아리가 여러 장 있어도 0건이다.
    """
    duel = main_phase_duel(repository)
    seat = duel.to_act
    legal = duel.legal_actions(seat)

    pots = [
        c.instance_id
        for c in duel.state.player(seat).hand
        if c.card_id == POT_OF_GREED
    ]
    assert pots, "패에 욕망의 항아리가 없으면 이 시험이 말하는 것이 없다"

    kinds = [a.kind for a in legal.allowed]
    assert kinds.count(PlayerActionKind.ACTIVATE_CARD) == 0
    assert kinds.count(PlayerActionKind.ACTIVATE_EFFECT) == 0
    # 세트는 된다 — 같은 마법 카드로 할 수 있는 다른 일은 후보에 있다.
    assert PlayerActionKind.SET_SPELL_TRAP in kinds


@pytest.mark.real_card
def test_07_only_activate_card_leaves_a_trace_in_withheld(repository):
    """
    **"왜 못 하는가" 가 절반만 적혀 있다.**

    ``ACTIVATE_CARD`` 는 ``withheld`` 에 이유와 함께 남는다. ``ACTIVATE_EFFECT``
    는 **어디에도 없다** — ``Duel`` 이 그 후보를 만들어 보지조차 않기 때문이다
    (``_withheld_board_actions`` 는 ``activate_card`` 만 만든다).

    빈 목록은 "할 것이 없다" 로 읽히고 적어 둔 것은 "아직" 으로 읽힌다 —
    지금 ``ACTIVATE_EFFECT`` 는 앞쪽으로 읽힌다.
    """
    duel = main_phase_duel(repository)
    legal = duel.legal_actions(duel.to_act)
    held = {w.kind for w in legal.withheld}

    assert PlayerActionKind.ACTIVATE_CARD in held
    assert PlayerActionKind.ACTIVATE_EFFECT not in held

    note = next(
        w for w in legal.withheld if w.kind is PlayerActionKind.ACTIVATE_CARD
    )
    assert "activation-timing" in note.missing


@pytest.mark.real_card
def test_07b_candidate_generation_is_a_separate_gap_from_validation(repository):
    """
    **두 구멍이 따로다.** 이것이 다음 Phase 의 최소 변경량을 정하는 사실이다.

    ``Duel.legal_actions`` 의 패 순회는 **세 가지만** 만들어 본다 —
    ``normal_summon`` · ``set_monster`` · ``set_spell_trap``. 발동은 그 목록에
    없으므로, 검증기가 ``VALID`` 를 돌려주더라도 후보는 여전히 0건이다.

    고의 위반으로 확인했다: ``ACTIVATE_CARD`` 를 ``_COMPLETE_RULES`` 에 올려
    검증기가 ``VALID`` 를 내게 만든 뒤에도 후보 수는 0이었고 ``Duel.apply``
    는 "지금 허가된 행위가 아닙니다" 로 거절했다. 그래서

        "검증기를 고치면 후보가 나온다"

    는 **틀렸다.** 후보를 만드는 코드와 실행 수행기가 따로 필요하다.
    이 시험은 그 순회가 세 가지뿐이라는 것을 소스에서 직접 읽어 고정한다.
    """
    source = (ROOT / "engine/duel.py").read_text()
    hand_loop = source.split("for card in self.state.player(seat).hand:")[1]
    builders = hand_loop.split("):")[0]
    assert "PlayerAction.normal_summon" in builders
    assert "PlayerAction.set_monster" in builders
    assert "PlayerAction.set_spell_trap" in builders
    assert "activate" not in builders, builders

    # allowed 에 발동을 넣는 자리가 **하나도 없다.**
    assert "PlayerAction.activate_effect" not in source


# ======================================================================
# 4. Duel.apply — 거절하고 **아무것도 바꾸지 않는다** (§4)
# ======================================================================


@pytest.mark.real_card
def test_08_duel_apply_refuses_both_and_changes_nothing(repository):
    """
    거절이 **조용하지 않고**, 거절된 발동이 판을 한 글자도 바꾸지 않는다.
    """
    duel = main_phase_duel(repository)
    seat = duel.to_act
    pot = next(
        c.instance_id
        for c in duel.state.player(seat).hand
        if c.card_id == POT_OF_GREED
    )
    before = board(duel)

    for action in (
        PlayerAction.activate_card(actor=seat, source=pot),
        PlayerAction.activate_effect(
            actor=seat, source=pot, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
    ):
        step = duel.apply(action)
        assert not step.accepted, action.kind
        assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert board(duel) == before, action.kind


def test_09_no_activation_handler_is_registered_anywhere():
    """
    ADR-006 — 등록하지 않은 것은 실행되지 않는다. **등록되어 있지 않다.**

    ``engine/activation.py`` 가 그것이 의도라고 적어 두었다 (STRUCTURAL-55):
    ``ActionHandler.apply`` 는 ``StateDelta`` 만 돌려주는데 발동의 결과물은
    ``Chain`` · ``PriorityState`` 이고, 그것은 ``GameState`` 밖에 산다.
    """
    executor = duel_executor()
    assert executor.handler_for(PlayerActionKind.ACTIVATE_CARD) is None
    assert executor.handler_for(PlayerActionKind.ACTIVATE_EFFECT) is None
    assert PlayerActionKind.ACTIVATE_CARD not in executor.supported
    assert PlayerActionKind.ACTIVATE_EFFECT not in executor.supported


def test_10_the_duel_does_not_hold_a_chain():
    """
    **``Duel`` 에 체인이 없다.** 이것이 끊어진 자리의 정확한 위치다.

    ``Duel`` 의 모듈 설명은 "지금 누가 우선권을 쥐었는지 · **체인이 어디까지
    쌓였는지** ... 그 자리가 여태 없었다. 이 클래스가 그 자리다" 라고
    적었지만, 실제로 받은 칸은 ``priority`` 하나다.
    """
    fields = set(Duel.__dataclass_fields__)
    assert "priority" in fields
    assert "chain" not in fields

    source = (ROOT / "engine/duel.py").read_text()
    assert "EffectActivator" not in source
    assert "ChainResolver" not in source


# ======================================================================
# 5. 손으로 부르면 **전부 동작한다** (§11)
# ======================================================================


@pytest.mark.real_card
def test_11_the_whole_path_works_when_called_by_hand(repository):
    """
    **이름만 있는 것이 아니다.** 실제 state mutation 까지 확인한다.

        욕망의 항아리 — 비용 없음 · 대상 없음 · 드로우 2

    발동 → 체인 → 해결 → 효과 → 덱 2장이 패로. 숫자로 확인한다.
    """
    state, source = hand_with(repository, POT_OF_GREED)
    deck_before, hand_before = len(state.player(MINE).deck), len(state.player(MINE).hand)

    definitions = definition_registry()
    activator = EffectActivator(definitions, implementation_registry())
    action = PlayerAction.activate_effect(
        actor=MINE, source=source, effect_ref=EffectRef(POT_OF_GREED, 0)
    )
    granted = ValidationResult.valid("audit: 바깥에서 준 허가")

    # ① 발동 — 체인에 링크가 쌓인다. **판은 아직 그대로다** (비용이 없다).
    activated = activator.activate(state, Chain(), action, authorization=granted)
    assert activated.status is ActivationStatus.ACTIVATED
    assert len(activated.chain) == 1
    assert activated.link.effect_ref == EffectRef(POT_OF_GREED, 0)
    assert activated.link.actor == MINE
    assert activated.deltas == (), "비용이 없으므로 발동만으로는 판이 안 바뀐다"
    assert len(state.player(MINE).deck) == deck_before

    # ② 해결 — 여기서 판이 바뀐다.
    resolved = ChainResolver(build_executor(), definitions).resolve_top(
        state, activated.chain
    )
    assert resolved.status.value == "resolved", resolved.reason
    assert len(state.player(MINE).deck) == deck_before - 2
    assert len(state.player(MINE).hand) == hand_before + 2
    drawn = [d for d in resolved.deltas if isinstance(d, CardDrawn)]
    assert len(drawn) == 2
    assert all("EFFECT" in d.reason_names for d in drawn)


@pytest.mark.real_card
def test_12_six_library_effects_resolve_with_the_default_executor(repository):
    """
    **몇 장이 실제로 끝까지 가는가.** 측정해서 적는다.

    ``build_executor()`` 를 기본값으로 쓰고 대상 선택을 주지 않았을 때
    해결까지 가는 것은 **6개**다. 나머지는 대상을 줘야 하거나
    (``invalid_target``) 판을 갖춰야 한다 (``condition_false``) — 못 하는
    것이 아니라 이 시험이 주지 않은 것이다.
    """
    definitions = definition_registry()
    activator = EffectActivator(definitions, implementation_registry())
    granted = ValidationResult.valid("audit")
    resolved: list[int] = []

    for entry in EFFECT_LIBRARY:
        if not entry.executable:
            continue
        card_id = entry.definition.effect_ref.card_id
        state, source = hand_with(repository, card_id)
        state.draw(MINE, 2)  # 패를 요구하는 효과가 있다
        action = PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(card_id, 0)
        )
        activated = activator.activate(state, Chain(), action, authorization=granted)
        if activated.status is not ActivationStatus.ACTIVATED:
            continue
        outcome = ChainResolver(build_executor(), definitions).resolve_top(
            state, activated.chain
        )
        if outcome.status.value == "resolved":
            resolved.append(card_id)

    assert sorted(resolved) == sorted(
        [55144522, 66719324, 84257639, 5915629, 70368879, 22589918]
    ), resolved


# ======================================================================
# 6. UNKNOWN 은 허가가 아니다 — 발동 계층에서도 (§7 · §13)
# ======================================================================


@pytest.mark.real_card
def test_13_a_face_down_target_makes_the_activation_unknown_not_legal(repository):
    """
    **관측 경계가 발동까지 지켜진다.**

    싸이크론의 후보 조건은 "마법 · 함정인가" 다. 뒷면 카드에는 그것을
    판정할 수 없으므로 ``UNKNOWN(information_unavailable)`` 이고, 발동은
    거절된다 — 체인에 아무것도 올라가지 않는다.

    같은 카드가 **앞면**이면 발동이 통과한다. 그래서 거절의 이유가
    "싸이크론이 안 된다" 가 아니라 **"보이지 않는다"** 임이 확인된다.
    """
    definitions = definition_registry()
    activator = EffectActivator(definitions, implementation_registry())
    granted = ValidationResult.valid("audit")

    def attempt(position: Position):
        state, source = hand_with(repository, MYSTICAL_SPACE_TYPHOON)
        victim = state.create_instance(TRAP_HOLE, owner=THEIRS, zone=Zone.HAND)
        state.move(victim, Zone.SZONE, to_player=THEIRS, position=position)
        action = PlayerAction.activate_effect(
            actor=MINE,
            source=source,
            effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0),
        )
        selections = (
            TargetSelection(TargetRef("primary"), Selection((victim.instance_id,))),
        )
        verdict = activator.can_activate(
            state, Chain(), action, selections=selections, authorization=granted
        )
        result = activator.activate(
            state, Chain(), action, selections=selections, authorization=granted
        )
        return verdict, result

    hidden_verdict, hidden = attempt(Position.FACEDOWN)
    assert hidden_verdict.validity is ActionValidity.UNKNOWN
    assert hidden_verdict.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert hidden.status is ActivationStatus.UNCHECKED_TARGET
    assert len(hidden.chain) == 0, "UNKNOWN 이 체인을 늘렸다"

    visible_verdict, visible = attempt(Position.FACEUP)
    assert visible_verdict.validity is ActionValidity.VALID
    assert visible.status is ActivationStatus.ACTIVATED


@pytest.mark.real_card
def test_14_destruction_still_refuses_to_resolve_without_declared_knowledge(
    repository,
):
    """
    **발동이 되어도 해결이 안 되는 자리가 있다.**

    싸이크론은 앞면 대상으로 발동까지 간다. 그런데 기본 실행기는 파괴를
    판정하지 못하므로 (``UnknownDestructionRuling``) 해결이 멈춘다 —
    "파괴 내성 · 대체 효과를 판정할 수 없다". 판정할 수 없는 것을 허가로
    바꾸지 않는다 (ADR-006 · STRUCTURAL-47).

    ``EFFECT_LIBRARY`` 에 실려 있다는 사실이 파괴 판정을 대신하지 않는다.
    """
    definitions = definition_registry()
    activator = EffectActivator(definitions, implementation_registry())
    state, source = hand_with(repository, MYSTICAL_SPACE_TYPHOON)
    victim = state.create_instance(TRAP_HOLE, owner=THEIRS, zone=Zone.HAND)
    state.move(victim, Zone.SZONE, to_player=THEIRS, position=Position.FACEUP)

    action = PlayerAction.activate_effect(
        actor=MINE, source=source, effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0)
    )
    selections = (
        TargetSelection(TargetRef("primary"), Selection((victim.instance_id,))),
    )
    activated = activator.activate(
        state,
        Chain(),
        action,
        selections=selections,
        authorization=ValidationResult.valid("audit"),
    )
    assert activated.status is ActivationStatus.ACTIVATED

    outcome = ChainResolver(build_executor(), definitions).resolve_top(
        state, activated.chain
    )
    assert outcome.status.value != "resolved"
    assert "판정할 수 없" in outcome.reason
    assert len(state.player(THEIRS).spell_zone) == 1, "판정 못 한 파괴가 일어났다"
    assert len(state.player(THEIRS).grave) == 0


# ======================================================================
# 7. 비용 (§8)
# ======================================================================


def test_15_no_library_effect_has_a_cost_so_the_cost_path_is_untravelled():
    """
    **비용 경로는 있지만 라이브러리에는 비용이 하나도 없다.**

    ``CostPayer`` · ``CostGroup`` · ``PaymentContext`` 가 모두 있고 발동이
    그 순서대로 부른다. 그러나 등록된 16개 효과 전부 ``CostGroup(costs=())``
    이므로, **이 경로를 지나간 실제 카드가 아직 없다.**

    그래서 "비용을 치른 뒤 발동이 실패하면 어떻게 되는가" 는 실제 카드로
    확인할 수 없고, 코드가 선언한 것만 적을 수 있다 — 치를 수 있는 검사를
    전부 끝낸 뒤에 치르고, 치르지 못하면 링크를 만들지 않는다
    (STRUCTURAL-56: ``can_activate`` 가 ``VALID`` 라도 비용에서 멈출 수 있다).
    """
    with_cost = [
        e.definition.effect_ref.card_id
        for e in EFFECT_LIBRARY
        if e.definition.cost.costs
    ]
    assert with_cost == [], with_cost
    assert len(EFFECT_LIBRARY) == 16


# ======================================================================
# 8. Search · Simulation (§12)
# ======================================================================


@pytest.mark.real_card
def test_16_the_simulator_reports_not_a_candidate_not_unknown(repository):
    """
    탐색은 **후보만** 해 본다. 발동은 후보가 아니므로 ``NOT_A_CANDIDATE`` 다.

    ``UNKNOWN`` 과 구분되는 것이 중요하다 — ``UNKNOWN`` 은 "해 봤는데
    엔진이 모른다" 이고 ``NOT_A_CANDIDATE`` 는 "애초에 고를 수 없다" 다.
    """
    from agent.simulation import SimulationStatus, Simulator

    duel = main_phase_duel(repository)
    seat = duel.to_act
    pot = next(
        c.instance_id
        for c in duel.state.player(seat).hand
        if c.card_id == POT_OF_GREED
    )
    simulator = Simulator(duel)

    for action in (
        PlayerAction.activate_card(actor=seat, source=pot),
        PlayerAction.activate_effect(
            actor=seat, source=pot, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
    ):
        result = simulator.simulate(action, viewer=seat)
        assert result.status is SimulationStatus.NOT_A_CANDIDATE, action.kind
        assert result.future is None


@pytest.mark.real_card
def test_17_the_search_policy_never_sees_an_activation(repository):
    """탐색의 후보 목록에 발동이 **하나도** 없다."""
    from agent import search_policy

    duel = main_phase_duel(repository)
    seat = duel.to_act
    policy = search_policy(duel)
    policy.decide(duel.view(seat), duel.legal_actions(seat))

    kinds = {c.action.kind for c in policy.last_decision.candidates}
    assert PlayerActionKind.ACTIVATE_CARD not in kinds
    assert PlayerActionKind.ACTIVATE_EFFECT not in kinds
    assert kinds, "후보가 아예 없으면 이 시험이 말하는 것이 없다"


# ======================================================================
# 9. 우선권 · 응답 (§10)
# ======================================================================


def test_18_the_response_loop_exists_but_nothing_opens_it():
    """
    **응답 루프는 있고, 그것을 여는 규칙은 없다** (STRUCTURAL-34).

    ``ResponseLoop.opened`` 는 "부르는 쪽이 값으로 여는 도구" 라고 스스로
    적는다 — "링크가 쌓였으니 자동으로 열린다" 는 규칙이 없다. 그리고
    ``Duel`` 은 ``ResponseLoop`` 를 모른다.
    """
    from engine.response import ResponseLoop

    assert hasattr(ResponseLoop, "opened")
    assert hasattr(ResponseLoop, "act")
    assert hasattr(ResponseLoop, "resolve")

    source = (ROOT / "engine/duel.py").read_text()
    assert "ResponseLoop" not in source
    assert "ResponseState" not in source


def test_19_the_timing_layer_lists_what_it_does_not_check():
    """
    타이밍 계층이 **무엇을 보지 않았는지** 적어 둔다. 지어내지 않은 증거다.
    """
    from engine.activation_timing import UNRESOLVED_TIMING_RULES

    assert len(UNRESOLVED_TIMING_RULES) == 6
    joined = " ".join(UNRESOLVED_TIMING_RULES)
    for unchecked in ("페이즈별 발동 제약", "턴 1회", "타이밍 놓침", "데미지 스텝"):
        assert unchecked in joined
