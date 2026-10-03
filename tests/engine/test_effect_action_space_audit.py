"""
Phase 3-E-3 — Effect Action Space (Audit 기록 + 구현 뒤의 사실).

이 파일은 Audit 이 조사한 **같은 자리들**을 계속 지킨다. Audit 시점에는
"여기가 끊어져 있다" 를 적었고, Implementation 이 그중 **일부**를 이었다.
그래서 주장이 바뀐 시험마다 **무엇을 적고 있었고 왜 바뀌었는지**를 docstring
에 남긴다 — 기록을 지우지 않고 갱신한다.

끊어져 있던 둘 중 **하나만** 이어졌다
-------------------------------------
``ACTIVATE_EFFECT``  이어졌다. 후보 → 검증 → Duel.apply → 발동 → 체인 →
                     해결 → 실제 state mutation 까지 간다.
``ACTIVATE_CARD``    **그대로다.** 발동 계층이 받지 않으므로 (모양 검사에서
                     거절) 후보도 실행 경로도 없다. Audit 의 주장이 그대로
                     살아 있다.

지금의 경로
-----------
                             ACTIVATE_EFFECT      ACTIVATE_CARD
    legal_actions            후보가 나온다        0건
    validation               통상 마법만 VALID    영원히 UNKNOWN
    Duel.apply               실행된다             거절
    EffectActivator          받는다               모양 검사에서 거절
    Chain                    링크가 쌓인다        —
    ChainResolver            해결된다             —
    EffectExecutor           판이 바뀐다          —

**``ActionExecutor`` 에는 여전히 발동 수행기가 등록되어 있지 않다.** 발동의
결과물은 ``StateDelta`` 만이 아니라 ``Chain`` 이기도 하므로 거기 끼울 수
없고, 그것이 의도였다 (STRUCTURAL-55). :meth:`Duel._apply_activation` 이
``_apply_board`` 와 **나란히** 따로 있다.

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
#: 욕망의 선물 — **함정**이다. 세트가 앞서야 하므로 (RULE-SPELLTRAP-009)
#: 이번 범위 밖이고, 그 사실을 ``test_05b`` 가 적는다.
THE_GIFT_OF_GREED = 5915629


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


def test_02_the_validator_now_tells_the_two_apart():
    """
    **STRUCTURAL-119 가 풀린 자리다.**

    Audit 에서 이 시험은 그 반대를 적었다 — "검증기는 둘을 구분하지 않는다,
    같은 요구 하나를 쓴다". 그때는 사실이었고 결함도 아니었다: 발동 타이밍
    계층이 없어 구분할 근거가 없었기 때문이다. 그 설명에 **"다음 Phase 가
    구분하면 이 시험이 깨진다"** 고 적어 두었고, 이 Phase 가 그 Phase 다.

    ``ACTIVATE_CARD`` 는 ``_activate`` 를 **그대로** 쓴다 — 요구 하나(컨트롤러)
    뿐이고, 발동 계층이 애초에 받지 않으므로 더 볼 것이 없다.
    """
    from engine.action_validation import (
        _REQUIREMENT_BUILDERS,
        _activate,
        _activate_effect,
    )

    assert _REQUIREMENT_BUILDERS[PlayerActionKind.ACTIVATE_CARD] is _activate
    assert _REQUIREMENT_BUILDERS[PlayerActionKind.ACTIVATE_EFFECT] is _activate_effect
    assert _activate is not _activate_effect


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


def test_04_only_activate_effect_can_ever_be_valid():
    """
    **한쪽만 올랐다.** Audit 에서는 둘 다 ``_MISSING_RULE`` 에 있었다.

    ``ACTIVATE_EFFECT`` 를 ``_COMPLETE_RULES`` 에 올린 것이 "모든 발동이
    허가된다" 가 **아니라는 것**은 ``_activate_effect`` 의 마지막 요구가
    지킨다 — 범위 밖은 전부 ``UNKNOWN`` 이다 (``test_05b``).

    ``ACTIVATE_CARD`` 는 그대로다. 발동 계층이 받지 않으므로 올릴 근거가
    없다.
    """
    assert PlayerActionKind.ACTIVATE_CARD in _MISSING_RULE
    assert PlayerActionKind.ACTIVATE_CARD not in _COMPLETE_RULES

    assert PlayerActionKind.ACTIVATE_EFFECT not in _MISSING_RULE
    assert PlayerActionKind.ACTIVATE_EFFECT in _COMPLETE_RULES


@pytest.mark.real_card
def test_05_a_normal_spell_is_now_authorized_but_card_activation_is_not(repository):
    """
    같은 카드 · 같은 판에서 **두 ActionKind 의 답이 갈린다.**

    Audit 에서는 둘 다 ``UNKNOWN`` 이었다. 이제 ``ACTIVATE_EFFECT`` 는
    통상 마법이므로 허가가 나고, ``ACTIVATE_CARD`` 는 그대로 ``UNKNOWN`` 이다
    — 발동 계층이 그 ActionKind 를 받지 않으므로 허가를 낼 근거가 없다.
    """
    state, source = hand_with(repository, POT_OF_GREED)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    as_effect = validator.validate(
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(POT_OF_GREED, 0)
        )
    )
    assert as_effect.validity is ActionValidity.VALID
    assert as_effect.permits_execution

    as_card = validator.validate(
        PlayerAction.activate_card(actor=MINE, source=source)
    )
    assert as_card.validity is ActionValidity.UNKNOWN
    assert as_card.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "activation-timing" in as_card.missing_rule
    assert not as_card.permits_execution


@pytest.mark.real_card
@pytest.mark.parametrize(
    "card_id,expected",
    [
        (THE_GIFT_OF_GREED, "non-spell-activation-timing"),
    ],
)
def test_05b_everything_outside_the_scope_stays_unknown(
    repository, card_id, expected
):
    """
    **``_COMPLETE_RULES`` 에 올렸지만 아무것도 넓히지 않았다.**

    함정은 공식 조항이 다른 타이밍을 적으므로 (RULE-SPELLTRAP-009 — 세트가
    앞서야 하고 세트한 턴에는 못 쓴다) ``UNKNOWN`` 으로 남는다.

    **``INVALID`` 가 아니다.** 실제 규칙에서는 발동할 수 있고, 없는 것은 그
    타이밍을 볼 계층뿐이다. ``INVALID`` 로 적으면 "규칙이 금지한다" 는 거짓을
    말하게 된다.

    **속공 마법이 이 목록에서 빠졌다** (Phase 3-E-12). 아래 ``test_05b2`` 로
    옮겼다 — 패에 있는 속공 마법의 발동 타이밍은 ``RULE-SPELLTRAP-007`` 이
    한 문장으로 적으므로 더 이상 "모른다" 가 아니다.
    """
    state, source = hand_with(repository, card_id)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    result = validator.validate(
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(card_id, 0)
        )
    )
    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert expected in result.missing_rule
    assert not result.permits_execution


@pytest.mark.real_card
def test_05b2_a_quick_play_spell_in_hand_is_now_in_scope(repository):
    """
    **패에 있는 속공 마법이 범위 안으로 들어왔다** (Phase 3-E-12).

    Phase 3-E-3 에서는 ``UNKNOWN`` 이었고, 그때는 그것이 옳았다 — 속공 마법의
    타이밍을 볼 계층이 없었다. 지금은 **있다.** 공식 조항이 둘로 갈린다.

        ``RULE-SPELLTRAP-007`` — "These are special Spell Cards that can be
        activated during **any Phase of your turn**, not just your Main Phase.
        You can **also** activate them during your opponent's turn **if you Set
        the card face-down first**, but then you cannot activate the card in
        the same turn you Set it."

    첫 문장은 **세트를 요구하지 않는다** — 그래서 "패에 있는 속공 마법을 자기
    턴에" 는 세트한 턴을 세지 않아도 판정할 수 있다. 두 번째 문장은 세트와
    "세트한 턴" 추적을 요구하므로 **여전히 ``UNKNOWN``** 이다
    (``test_05b3``).

    그리고 메인 페이즈 제약이 **걸리지 않는다** — "not just your Main Phase".
    """
    from engine.vocabulary import Phase

    for phase in (Phase.MAIN1, Phase.BATTLE, Phase.MAIN2, Phase.END):
        state, source = hand_with(repository, MYSTICAL_SPACE_TYPHOON)
        state.turn.set_phase(phase)
        validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))
        result = validator.validate(
            PlayerAction.activate_effect(
                actor=MINE,
                source=source,
                effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0),
            )
        )
        assert result.validity is ActionValidity.VALID, (phase, result.reason)


@pytest.mark.real_card
def test_05b3_a_set_quick_play_spell_is_still_unknown(repository):
    """
    **세트된 속공 마법은 여전히 ``UNKNOWN``** 이다 (Phase 3-E-12).

    ``RULE-SPELLTRAP-007`` 의 두 번째 문장이 "you cannot activate the card in
    the same turn you Set it" 를 요구하는데, **세트한 턴을 세는 자리가 엔진에
    없다** (``engine/activation_timing.py`` 의 ``UNRESOLVED_TIMING_RULES`` 가
    "세트한 턴의 함정 발동 제약" 을 보지 않는다고 적어 두었다).

    세지 못하는 제약을 통과시키면 "세트한 턴에 발동할 수 있다" 는 거짓이
    된다. 그래서 ``UNKNOWN`` 이고, **``INVALID`` 도 아니다.**
    """
    from engine.vocabulary import Position, Zone

    state, source = hand_with(repository, MYSTICAL_SPACE_TYPHOON)
    card = state.find_instance(source)
    state.move(card, Zone.SZONE, to_player=MINE, position=Position.FACEDOWN)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    result = validator.validate(
        PlayerAction.activate_effect(
            actor=MINE,
            source=source,
            effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0),
        )
    )
    assert result.validity is ActionValidity.UNKNOWN, result.reason
    assert "set-card-activation-timing" in (result.missing_rule or "")
    assert not result.permits_execution


@pytest.mark.real_card
def test_05c_an_on_field_activation_is_unknown_not_invalid(repository):
    """
    필드에서의 발동은 **``UNKNOWN``** 이다 — 이 구분이 가장 중요하다.

    구현 중에 한 번 틀렸던 자리다. "패에 있는가" 를 ``INVALID``
    (``SOURCE_WRONG_ZONE``) 요구로 두었더니, 필드의 몬스터가 자기 효과를
    발동하는 것이 **규칙 위반**으로 읽혔다. 실제 규칙에서는 적법하고 (기동
    효과) 없는 것은 그 타이밍 계층뿐이다. 그래서 자리 검사를 범위 조건 안으로
    옮겼다.

    ``tests/engine/test_action_legality.py`` 의
    ``test_an_effect_ordinal_beyond_the_card_is_invalid`` 가 이 실수를 잡았다.

    **예로 든 카드를 바꿨다** (Phase 3-E-14)
    ----------------------------------------
    처음에는 **뒷면으로 세트한** 통상 마법을 예로 들었다. 그 가정이 틀렸다 —
    공식 룰북에 그 자리를 **직접 판정하는 조항이 있다.**

        RULE-SPELLTRAP-012 — "Spell Cards can be activated during the Main
        Phases **even in the same turn that you Set them** (except for
        Quick-Play Spell Cards). Setting them does not allow you to use them
        on your opponent's turn; they still can only be activated during your
        Main Phase."

    즉 "세트한 통상 마법의 발동" 은 모르는 것이 아니라 **아는 것**이고, 지금은
    ``VALID`` 가 나온다. ``UNKNOWN`` 으로 남겨 두면 "모른다" 는 거짓이 된다.

    **주장은 그대로다.** 필드에서의 발동을 ``INVALID`` 로 적지 않는다는 것이고,
    그것을 보이려면 조항이 아직 답하지 않은 자리를 예로 들어야 한다 — 마법 &
    함정 존의 **앞면** 마법이 그렇다. 몬스터의 기동 효과도 같은 자리지만 그쪽은
    "통상 마법이 아니다" 라는 **다른** 이유로 걸리므로 (``
    non-spell-activation-timing``) 이 시험이 읽는 문자열이 달라진다.
    """
    state, source = hand_with(repository, POT_OF_GREED)
    state.move(
        state.find_instance(source),
        Zone.SZONE,
        to_player=MINE,
        position=Position.FACEUP,
    )
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    result = validator.validate(
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(POT_OF_GREED, 0)
        )
    )
    assert result.validity is ActionValidity.UNKNOWN, result
    assert "on-field-activation-timing" in result.missing_rule


# ======================================================================
# 3. legal_actions — 후보가 **0건**이다 (§5)
# ======================================================================


@pytest.mark.real_card
def test_06_a_real_duel_now_offers_one_candidate_per_hand_copy(repository):
    """
    **실제로 굴린 듀얼**에서 센다. Audit 에서는 0건이었다.

    패의 욕망의 항아리 **장수만큼** 후보가 나온다 — 같은 이름 여러 장이
    하나로 뭉치지 않는다. ``ACTIVATE_CARD`` 는 여전히 0건이다.
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
    assert kinds.count(PlayerActionKind.ACTIVATE_EFFECT) == len(pots)

    # instance 마다 하나씩이고, 전부 패의 그 카드들이다.
    sources = {
        a.source
        for a in legal.allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    }
    assert sources == set(pots)
    # 세트도 그대로 된다 — 같은 카드로 할 수 있는 다른 일이 사라지지 않았다.
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
def test_07b_candidate_generation_is_now_wired_too(repository):
    """
    **STRUCTURAL-117 이 풀린 자리다.**

    Audit 에서 이 시험은 "후보를 만드는 코드와 적법성 판정이 서로 다른
    구멍이다" 를 적었고, 고의 위반으로 그것을 증명했다 — ``ACTIVATE_CARD`` 를
    ``_COMPLETE_RULES`` 에 올려 검증기가 ``VALID`` 를 내게 만든 뒤에도 후보는
    0건이었다. 둘을 **모두** 이어야 했고, 그래서 이 Phase 가 둘을 모두 이었다.

    ``Duel._activation_actions`` 가 그 자리다. 패 순회에 억지로 끼우지 않고
    **따로** 둔 이유: 소환·세트는 ``source`` 하나로 후보가 정해지지만 발동은
    ``(source, effect_ref)`` 짝이고, 카드 한 장이 효과를 여러 개 가질 수 있다.
    """
    source = (ROOT / "engine/duel.py").read_text()

    # 후보를 만드는 자리가 실제로 있다.
    assert "def _activation_actions" in source
    assert "PlayerAction.activate_effect" in source
    assert "self._activation_actions(seat, validator)" in source

    # 소환·세트의 순회는 **건드리지 않았다** — 거기에 발동을 끼워 넣지 않았다.
    hand_loop = source.split("for card in self.state.player(seat).hand:")[1]
    builders = hand_loop.split("):")[0]
    assert "PlayerAction.normal_summon" in builders
    assert "PlayerAction.set_monster" in builders
    assert "PlayerAction.set_spell_trap" in builders
    assert "activate" not in builders, builders


# ======================================================================
# 4. Duel.apply — 거절하고 **아무것도 바꾸지 않는다** (§4)
# ======================================================================


@pytest.mark.real_card
def test_08_duel_apply_still_refuses_activate_card_and_changes_nothing(repository):
    """
    **``ACTIVATE_CARD`` 쪽 주장은 글자 하나 바뀌지 않았다.**

    Audit 에서는 둘 다 거절됐다. 이제 ``ACTIVATE_EFFECT`` 는 실행되지만
    (``test_11b``), ``ACTIVATE_CARD`` 는 그대로 거절되고 판은 한 글자도
    바뀌지 않는다.
    """
    duel = main_phase_duel(repository)
    seat = duel.to_act
    pot = next(
        c.instance_id
        for c in duel.state.player(seat).hand
        if c.card_id == POT_OF_GREED
    )
    before = board(duel)

    step = duel.apply(PlayerAction.activate_card(actor=seat, source=pot))
    assert not step.accepted
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert board(duel) == before


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


def test_10_the_duel_now_holds_a_chain():
    """
    **``Duel`` 이 체인을 들게 됐다.**

    Audit 에서 이 시험은 그 반대를 적었다. ``Duel`` 의 모듈 설명이 처음부터
    "체인이 어디까지 쌓였는지 ... 그 자리가 여태 없었다. 이 클래스가 그
    자리다" 라고 썼는데 실제로 받은 칸은 ``priority`` 하나였고, 이 Phase 가
    설명대로 칸을 채웠다.

    **``Chain`` 은 ``state_hash()`` 에 들어가지 않는다** — 체인은 판의 모양이
    아니라 흐름의 위치다. 그 불변식은 그대로다.
    """
    fields = set(Duel.__dataclass_fields__)
    assert "priority" in fields
    assert "chain" in fields

    # 발동기·해결기는 **발동 계층**에서 가져온다. duel.py 가
    # engine.effect 를 직접 읽지 않는 것은 test_duel_loop 가 지킨다.
    source = (ROOT / "engine/duel.py").read_text()
    assert "duel_activator" in source
    assert "duel_resolver" in source
    assert "from engine.spell_activation import" in source


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
def test_16_the_simulator_runs_the_activation_and_still_refuses_the_card(repository):
    """
    Audit 에서는 둘 다 ``NOT_A_CANDIDATE`` 였다. 이제 갈린다.

    ``ACTIVATE_EFFECT`` 는 ``SUPPORTED`` 이고 미래가 돌아온다.
    ``ACTIVATE_CARD`` 는 그대로 ``NOT_A_CANDIDATE`` 다 — ``UNKNOWN`` 과
    구분되는 것이 여전히 중요하다: ``UNKNOWN`` 은 "해 봤는데 엔진이 모른다"
    이고 ``NOT_A_CANDIDATE`` 는 "애초에 고를 수 없다" 다.
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

    refused = simulator.simulate(
        PlayerAction.activate_card(actor=seat, source=pot), viewer=seat
    )
    assert refused.status is SimulationStatus.NOT_A_CANDIDATE
    assert refused.future is None

    supported = simulator.simulate(
        PlayerAction.activate_effect(
            actor=seat, source=pot, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
        viewer=seat,
    )
    assert supported.status is SimulationStatus.SUPPORTED, supported.reason
    assert supported.future is not None


@pytest.mark.real_card
def test_17_the_search_policy_now_sees_the_activation(repository):
    """
    탐색의 후보 목록에 발동이 **들어온다.** Audit 에서는 0건이었다.

    ``SearchPolicy`` 에 발동을 위한 분기를 **넣지 않았다** — 후보 목록이
    넓어진 것만으로 저절로 들어온다. 그것이 Phase 3-A 가 만든 경계가
    아직 성립한다는 뜻이다.
    """
    from agent import search_policy

    duel = main_phase_duel(repository)
    seat = duel.to_act
    policy = search_policy(duel)
    policy.decide(duel.view(seat), duel.legal_actions(seat))

    kinds = {c.action.kind for c in policy.last_decision.candidates}
    assert PlayerActionKind.ACTIVATE_CARD not in kinds
    assert PlayerActionKind.ACTIVATE_EFFECT in kinds


# ======================================================================
# 9. 우선권 · 응답 (§10)
# ======================================================================


def test_18_the_duel_now_opens_the_response_loop_after_an_activation():
    """
    **STRUCTURAL-34 의 절반이 풀린 자리다** (Phase 3-E-11).

    Phase 3-E-3 에서 이 시험은 그 반대를 적었다 — "``Duel`` 은
    ``ResponseLoop`` 를 모른다" 고. 그때는 **여는 규칙이 없었기 때문**이고,
    없는 규칙을 지어내지 않은 것이 옳았다.

    **왜 기존 전제가 바뀌었는가.** 규칙이 없는 것이 아니라 **찾지 않았던**
    것이다. 공식 룰북 ``RULE-CHAIN-001`` 이 한 문장으로 적는다 —

        "If a card's effect is activated, the opponent is **always** given a
         chance to respond with a card effect of their own, creating a Chain."

    그래서 지금은 ``Duel._apply_activation`` 이 링크를 쌓은 뒤 **상대에게**
    기회를 연다. ``ResponseLoop.opened`` 의 설명("부르는 쪽이 값으로 연다")은
    그대로이고, 그 **부르는 쪽이 생겼다.**

    아직 열지 않는 자리는 그대로다 — 페이즈 전환(RULE-CHAIN-009)과 체인 해결
    뒤(``AFTER_CHAIN_RULE``). 그래서 STRUCTURAL-34 전체가 풀린 것이 아니다.
    """
    from engine.response import ResponseLoop

    assert hasattr(ResponseLoop, "opened")
    assert hasattr(ResponseLoop, "act")
    assert hasattr(ResponseLoop, "resolve")

    source = (ROOT / "engine/duel.py").read_text()
    assert "ResponseLoop.opened(" in source
    assert "RULE-CHAIN-001" in source
    # 나머지 절반은 여전히 열지 않는다 — 기회를 여는 자리가 **하나뿐**이다.
    assert source.count("ResponseLoop.opened(") == 1
    assert "PHASE_CHANGE" not in source
    assert "give_to" not in source, "체인 해결 뒤 우선권은 아직 정하지 않았다"


def test_19_the_timing_layer_lists_what_it_does_not_check():
    """
    타이밍 계층이 **무엇을 보지 않았는지** 적어 둔다. 지어내지 않은 증거다.
    """
    from engine.activation_timing import UNRESOLVED_TIMING_RULES

    assert len(UNRESOLVED_TIMING_RULES) == 6
    joined = " ".join(UNRESOLVED_TIMING_RULES)
    for unchecked in ("페이즈별 발동 제약", "턴 1회", "타이밍 놓침", "데미지 스텝"):
        assert unchecked in joined
