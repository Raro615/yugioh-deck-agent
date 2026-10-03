"""
Phase 3-E-16 — 세트한 함정의 발동 타이밍 감사 (``_OUT_OF_SCOPE_TYPES`` 의 TRAP).

이 Phase 는 **함정을 열지 않았다.** 어디까지 알고 어디부터 모르는지를 재고,
코드에 적혀 있던 **틀린 이유 하나를 고쳤다.**

처음 적혀 있던 이유가 더 이상 참이 아니었다
-------------------------------------------
``_OUT_OF_SCOPE_TYPES`` 의 ``TRAP`` 항목은 이렇게 적혀 있었다.

    "trap-activation-timing (세트가 앞서고 세트한 턴에는 못 쓴다 —
     RULE-SPELLTRAP-009)"

**그 둘은 지금 다 있다.** 세트는 ``SET_SPELL_TRAP`` 이 하고 (Phase 3-E-2),
세트한 턴은 ``GameState.rule_uses`` 가 적고 ``ActivationTimingChecker`` 가
본다 (Phase 3-E-15). 즉 코드가 **스스로에 대해 거짓을 적고 있었다.**

지금 모자란 것은 **하나**다
---------------------------
공식 스크립트는 "이 효과가 언제 발동하는가" 를 ``SetCode(EVENT_*)`` 로 적는다.
등재된 함정 5장은 **전부 ``EVENT_FREE_CHAIN``** (유발 조건 없음) 이고, 그
사실이 ``core`` 계층의 ``Card.script`` 에는 **있다.** 그런데
``EffectDefinition`` 에는 **옮겨지지 않았다.**

그래서 엔진은 "유발 조건 없는 함정" 과 "무언가가 일어났을 때만 발동하는 함정"
을 구분할 수 없다. 구분하지 못하는 채로 종류 전체를 통과시키면 유발 함정이
아무 때나 발동하게 된다. 그래서 막아 두고, 막는 이유를 정확히 적는다 —
``INVALID`` 가 아니라 ``UNKNOWN`` 인 이유도 그것이다.

절대로 혼동하지 않는다
----------------------
    TRAP              ≠  TRIGGER
    EVENT_FREE_CHAIN  ≠  ALWAYS LEGAL
    SET_THIS_TURN     ≠  ACTIVATION_INVALID
    CANDIDATE         ≠  VALIDATION  ≠  EXECUTION
    TURN_PLAYER       ≠  RESPONSE_SEAT
"""

import pathlib

import pytest

from agent.evaluation import StateEvaluator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    _OUT_OF_SCOPE_TYPES,
    TRAP_TRIGGER_MISSING,
    ActionValidator,
)
from engine.activation_timing import (
    ActivationTiming,
    ActivationTimingChecker,
    SpellSpeed,
    classify_spell_speed,
)
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.ids import EffectRef
from engine.priority import PriorityState, ResponseWindow
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.target_bridge import selections_for, target_combinations
from engine.validation import ActionValidity, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

P0, P1 = 0, 1
SET_ACTION = RuleActionKind.SET_SPELL_TRAP

LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522  # 통상 마법 — 상대가 체인 1 을 만드는 데 쓴다

#: 등재된 함정들. 이 목록은 **측정 결과**이고, 바뀌면 이 Phase 를 다시 읽어야
#: 한다 (``test_01`` 이 리포지토리에서 직접 세서 대조한다).
GIFT_OF_GREED = 5915629  # 욕망의 선물 — 상대가 2장 드로우 · 실행 가능
FINE = 92595643  # 벌금 — 자신 패 2장 버리기 · 대상 **2장**
FORCEOUT = 94192409  # 강제 탈출 장치 — 몬스터 1장 패로
LOST = 24623598  # 로스트 — executable=False
PRIMER = 69091732  # 의적의 입문서 — 상대 패 5장 이상일 때

ALL_TRAPS = (GIFT_OF_GREED, FINE, FORCEOUT, LOST, PRIMER)


def duel_at(repository, *, mine=(), theirs=(), their_mzone=(), turn_player=P0, turn=5):
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20),
        turn_player=turn_player,
        seed=1,
    )
    for card_id in mine:
        state.create_instance(card_id, owner=P0, zone=Zone.HAND)
    for card_id in theirs:
        state.create_instance(card_id, owner=P1, zone=Zone.HAND)
    for card_id in their_mzone:
        state.create_instance(
            card_id, owner=P1, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
        )
    state.turn.turn_number = turn
    state.turn.turn_player = turn_player
    state.turn.set_phase(Phase.MAIN1)
    return Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=Phase.MAIN1),
    )


def set_down(duel, seat, card_id):
    card = next(c for c in duel.state.player(seat).hand if c.card_id == card_id)
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=card.instance_id))
    assert step.accepted, step.reason
    return card.instance_id


def made(seat, instance, card_id):
    return PlayerAction.activate_effect(
        actor=seat, source=instance, effect_ref=EffectRef(card_id, 0)
    )


def activations(duel, seat, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def next_own_turn(duel, seat=P0):
    duel.state.turn.turn_number += 2
    duel.state.turn.turn_player = seat
    duel.state.turn.set_phase(Phase.MAIN1)
    duel.priority = PriorityState.idle(turn_player=seat, phase=Phase.MAIN1)


# ======================================================================
# §3 — 등재된 함정 다섯 장의 실제 정의
# ======================================================================


@pytest.mark.real_card
def test_01_every_registered_trap_is_free_chain_in_the_core_layer(repository):
    """
    **§3 · §29-3 · §29-4 — 다섯 장 전부 ``EVENT_FREE_CHAIN`` 이다.**

    그리고 그 사실이 **어느 계층에 있는가**가 이 Phase 의 핵심이다.

    - ``core`` 의 ``Card.script`` — **있다** (공식 Lua 의 ``SetCode``)
    - ``engine`` 의 ``EffectDefinition`` — **없다**

    ``EVENT_FREE_CHAIN`` 을 "언제나 발동 가능" 으로 읽지 않는다. 뜻은 **"유발
    조건이 없다"** 이고, 그래도 세트한 턴 · 스펠 스피드 · 발동 기회(창)는 각각
    따로 걸린다.

    **장수를 여기서 센다.** Phase 3-E-15 보고서는 "함정 4장" 이라고 적었는데
    실제로는 **5장**이고 그중 하나(로스트)가 ``executable=False`` 다. 세는
    기준이 "등재" 와 "실행 가능" 으로 달랐던 것이고, 이 시험이 둘을 따로 센다.
    """
    traps = [
        entry
        for entry in EFFECT_LIBRARY
        if "TRAP" in repository.get(entry.definition.source_card_id).type_names
    ]
    assert {e.definition.source_card_id for e in traps} == set(ALL_TRAPS)
    assert len(traps) == 5
    assert sum(1 for e in traps if e.executable) == 4
    assert [e.executable for e in traps if e.definition.source_card_id == LOST] == [
        False
    ]

    for entry in traps:
        card = repository.get(entry.definition.source_card_id)
        # ① 스펠 스피드는 카드 종류만으로 정해진다 — 함정은 2 다.
        assert classify_spell_speed(card).speed is SpellSpeed.FAST

        # ② 유발 조건 없음이 **core 계층에** 적혀 있다.
        assert card.script.trigger_events == ["EVENT_FREE_CHAIN"], card.name
        assert [s.code for s in card.script.effects] == ["EVENT_FREE_CHAIN"], card.name

    # ③ 그런데 **엔진의 정의에는 그런 자리가 없다.**
    fields = set(EffectDefinition.__dataclass_fields__)
    assert not [
        name for name in fields if "trigger" in name or "event" in name or "timing" in name
    ], fields
    # 그리고 **엔진은 그 데이터를 읽지 않는다.** 상수 이름이 설명 주석에
    # 등장하는 것과, 실행 코드가 ``core`` 의 필드를 읽는 것은 다른 일이다 —
    # 뒤쪽을 잰다.
    # 주석과 설명에 이름이 등장하는 것과 **실행 코드가 그 필드를 읽는 것**은
    # 다른 일이다. 문자열로 재면 설명에 걸린다 (실제로 걸렸다 — ``ids.py`` 가
    # ``card.script.effects`` 를 설명에 적는다). 그래서 **AST** 로 잰다.
    import ast

    for module in pathlib.Path("engine").rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        read = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "trigger_events" not in read, module.name
        assert "trigger_event" not in read, module.name


def test_02_the_reason_that_actually_fires_is_the_true_one():
    """
    **§6 — 막는 이유가 참이어야 하고, 닿는 자리에 있어야 한다.**

    두 가지가 틀려 있었다.

    ① **이유가 거짓이 되었다.** ``_OUT_OF_SCOPE_TYPES`` 의 ``TRAP`` 항목은
       "세트가 앞서고 세트한 턴에는 못 쓴다" 라고 적고 있었다. 세트는 Phase
       3-E-2 가, 세트한 턴은 Phase 3-E-15 가 해결했으므로 둘 다 더 이상 이유가
       아니다.

    ② **그 항목은 닿지 않는 코드였다.** 함정은 ``definition.is_spell`` 이
       거짓이므로 앞선 분기에서 돌아가고, 이름 검사까지 가지 않는다. 즉 틀린
       문장이 **아무 영향도 주지 않는 자리**에 있었고, 그래서 틀린 채로
       남아 있었다. 실제로 나오던 문장은 "함정 · 몬스터 효과의 발동 타이밍"
       하나였고, 그것은 **서로 다른 두 공백을 한 문장에 담고** 있었다.

    그래서 닿지 않는 항목을 지우고, 실제로 걸리는 자리에서 함정과 몬스터를
    나눴다. 이 Phase 가 바꾼 것은 이것뿐이고 **판정 결과는 그대로다**
    (둘 다 ``UNKNOWN``).
    """
    from engine.action_validation import MONSTER_ACTIVATION_MISSING

    # ① 닿지 않던 항목이 사라졌다.
    assert "TRAP" not in dict(_OUT_OF_SCOPE_TYPES)
    assert set(dict(_OUT_OF_SCOPE_TYPES)) == {
        "CONTINUOUS",
        "EQUIP",
        "FIELD",
        "RITUAL",
        "COUNTER",
    }
    # 남은 다섯은 **각자의 이유**를 갖는다 — 한 문장으로 뭉치지 않는다.
    assert len({reason for _, reason in _OUT_OF_SCOPE_TYPES}) == 5

    # ② 이유가 측정된 사실이고, 해결된 것을 들지 않는다.
    assert TRAP_TRIGGER_MISSING.startswith("trap-activation-timing")
    assert "유발 조건" in TRAP_TRIGGER_MISSING
    assert "EffectDefinition" in TRAP_TRIGGER_MISSING
    assert "세트가 앞서고" not in TRAP_TRIGGER_MISSING
    assert "세트한 턴" not in TRAP_TRIGGER_MISSING

    # ③ 함정과 몬스터가 **다른 문장**이다.
    assert TRAP_TRIGGER_MISSING != MONSTER_ACTIVATION_MISSING
    assert "함정" not in MONSTER_ACTIVATION_MISSING


# ======================================================================
# §22 — 세트한 턴 기록은 **읽기만** 한다
# ======================================================================


@pytest.mark.real_card
def test_03_the_set_turn_record_covers_traps_too(repository):
    """
    **§22 · §29-9 — Phase 3-E-15 의 기록을 그대로 읽는다.**

    새 저장소를 만들지 않았다. 기록하는 쪽은 카드 종류를 보지 않으므로 함정도
    같은 표에 적힌다 — 그래서 이 Phase 가 할 일은 **읽기**뿐이다.
    """
    duel = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    turn = duel.state.turn.turn_number
    instance = set_down(duel, P0, GIFT_OF_GREED)

    assert duel.state.rule_uses.used_card(turn, P0, instance, SET_ACTION)
    assert duel._set_this_turn(made(P0, instance, GIFT_OF_GREED)) is True

    next_own_turn(duel)
    assert duel._set_this_turn(made(P0, instance, GIFT_OF_GREED)) is False
    # 지난 턴의 기록은 남아 있다 — 역사다.
    assert duel.state.rule_uses.used_card(turn, P0, instance, SET_ACTION)


# ======================================================================
# §7 · §8 — 세 계층을 따로 센다
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("card_id", [GIFT_OF_GREED, FINE, FORCEOUT, PRIMER])
def test_04_only_the_validator_blocks_a_set_trap(repository, card_id):
    """
    **§7 · §8 — "후보가 없다" 의 이유가 정확히 하나다.**

    세 계층을 따로 재면 막는 곳이 하나로 좁혀진다.

    ========================  =========================================
    Action Space              **통과** — 출발지에 있다 (Phase 3-E-14)
    ``ActivationTimingChecker``  **통과** — 스펠 스피드 2 · 세트한 턴도 안다
    ``ActionValidator``       **막는다** — ``TRAP`` 이 범위 밖이다
    ========================  =========================================

    이것이 "Trap candidate 가 없다" 와 "candidate 는 있지만 validator 가
    거부한다" 를 가르는 자리다. 지금은 **뒤쪽**이고, 그래서 고칠 곳이 어디인지
    분명하다.
    """
    duel = duel_at(repository, mine=(card_id, LUSTER_DRAGON))
    instance = set_down(duel, P0, card_id)
    next_own_turn(duel)
    action = made(P0, instance, card_id)

    # ① Action Space — 출발지에 있다.
    assert instance in {c.instance_id for c in duel._activation_sources(P0)}

    # ② 타이밍 관문 — 통과한다. 세트한 턴도 알고 있다.
    assert duel._set_this_turn(action) is False
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=False), action
    )
    assert timed.validity is ActionValidity.VALID, timed.reason

    # ③ 검증기 — 여기서 막힌다. 그리고 ``INVALID`` 가 아니라 ``UNKNOWN`` 이다.
    verdict = ActionValidator(duel.view(P0)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == TRAP_TRIGGER_MISSING

    # 그래서 후보가 되지 않는다 — 이 Phase 는 그것을 바꾸지 않았다.
    assert activations(duel, P0, card_id) == []


@pytest.mark.real_card
def test_05_a_set_trap_on_the_same_turn_is_blocked_for_two_reasons(repository):
    """
    **§11 — 세트한 턴에는 이유가 **둘**이다. 하나로 뭉치지 않는다.**

    ① 검증기: 유발 조건을 구분할 수 없다 (``UNKNOWN``)
    ② 타이밍: 세트한 턴이다 (``INVALID``, RULE-SPELLTRAP-009)

    ②가 ``INVALID`` 라는 것이 Phase 3-E-15 가 얻은 것이다 — 세트한 턴을
    세므로 "모른다" 가 아니라 "규칙이 금지한다" 를 말할 수 있다. 그래서 함정의
    같은 턴 발동에 **무조건 같은 답을 주지 않는다** (§11).
    """
    duel = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    instance = set_down(duel, P0, GIFT_OF_GREED)
    action = made(P0, instance, GIFT_OF_GREED)

    assert duel._set_this_turn(action) is True
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=True), action
    )
    assert timed.validity is ActionValidity.INVALID
    assert "세트한 턴" in timed.reason

    verdict = ActionValidator(duel.view(P0)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN


# ======================================================================
# §10 · §13 — 상대 턴의 응답 자리
# ======================================================================


@pytest.mark.real_card
def test_06_the_response_seat_is_already_correct_for_a_set_trap(repository):
    """
    **§10 · §13 · §29-8 — 응답 자리는 이미 맞다.**

    ``turn_player`` · ``priority holder`` · ``response seat`` 세 개를 혼동하지
    않았는지 실제 창에서 센다. 상대 턴인데 응답 자리는 나이고, 그래도 턴
    플레이어는 바뀌지 않는다.

    그리고 **그 창 안에서도** 세트 함정은 후보가 아니다 — 자리가 틀려서가
    아니라 검증기가 유발 조건을 모르기 때문이다. 둘을 가르는 것이 이 시험의
    목적이다. "turn_player 가 아니라서 invalid" 라고 적으면 거짓이 된다.
    """
    duel = duel_at(
        repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON), theirs=(POT_OF_GREED,)
    )
    instance = set_down(duel, P0, GIFT_OF_GREED)

    # 상대 턴으로 넘어간다.
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = P1
    duel.priority = PriorityState.idle(turn_player=P1, phase=Phase.MAIN1)

    # 상대가 발동해 창이 열린다 (RULE-CHAIN-001).
    assert duel.apply(activations(duel, P1, POT_OF_GREED)[0]).accepted
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.is_seat(P0), "응답 자리가 내가 아니다"
    assert duel.turn_player == P1, "턴 플레이어가 바뀌었다"
    assert duel.to_act == P0

    action = made(P0, instance, GIFT_OF_GREED)
    # 세트한 턴이 아니다 — 상대 턴은 언제나 다음 턴이다.
    assert duel._set_this_turn(action) is False
    # 스펠 스피드 2 로 스펠 스피드 1 에 응수할 수 있다.
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=False), action
    )
    assert timed.validity is ActionValidity.VALID
    assert "스펠 스피드 2" in timed.reason

    # 그래도 후보가 아니다 — 막는 것은 **검증기 하나**다.
    assert activations(duel, P0, GIFT_OF_GREED) == []
    gate = duel._activation_gate(
        action, validator=ActionValidator(duel.view(P0)), selections=()
    )
    assert gate.validity is ActionValidity.UNKNOWN
    assert [a.kind for a in duel.legal_actions(P0).allowed] == [PlayerActionKind.PASS]


# ======================================================================
# §19 — 실행 경계. **어디까지 되는지 실제로 돌려 본다**
# ======================================================================


def _force_execute(duel, instance, card_id):
    """
    허가를 손으로 넣어 **실행 계층만** 돌린다 (감사용).

    ``legal_actions`` 를 거치지 않으므로 이것은 "이 발동이 적법하다" 는 주장이
    **아니다.** 검증기를 열었다고 가정했을 때 실행이 되는지만 본다.
    """
    definition = duel._activator.definitions.definition_for(EffectRef(card_id, 0))
    combos = list(target_combinations(duel.state, P0, definition, instance))
    action = PlayerAction.activate_effect(
        actor=P0,
        source=instance,
        effect_ref=EffectRef(card_id, 0),
        targets=combos[0] if combos else (),
    )
    permit = ValidationResult.valid("감사용 허가 — 실행 계층만 잰다")
    try:
        selections = selections_for(definition, action)
    except Exception as error:  # noqa: BLE001 - 무엇이 막는지 그대로 적는다
        return {"stage": "target_bridge", "detail": str(error), "combos": len(combos)}
    allowed = duel._activator.can_activate(
        duel.state, duel.chain, action, selections=selections, authorization=permit
    )
    if allowed.validity is not ActionValidity.VALID:
        return {"stage": "can_activate", "detail": allowed.reason, "combos": len(combos)}
    activated = duel._activator.activate(
        duel.state, duel.chain, action, selections=selections, authorization=permit
    )
    placed = duel._place_activated(action)
    duel.chain = activated.chain
    steps = duel._resolver.resolve_all(duel.state, duel.chain)
    duel._placement.retire(duel.state, placed)
    last = steps[-1] if steps else None
    return {
        "stage": "resolved" if last is not None and last.resolved else "resolve",
        "detail": "" if last is None else last.reason,
        "combos": len(combos),
        "zone": duel.state.find_instance(instance).zone,
    }


@pytest.mark.real_card
def test_07_two_traps_already_execute_end_to_end(repository):
    """
    **§19 · §29-17 — 실행이 되는 함정이 이미 있다.**

    검증기만 열려 있다면 **욕망의 선물**과 **의적의 입문서**는 발동 →
    앞면으로 돌리기 → 해결 → 묘지까지 전부 돌아간다. 즉
    ``SET_ACTIVATION_EXECUTION`` (세트된 카드를 앞면으로 돌려 발동하는 경로)은
    함정에도 **이미 있다** — Phase 3-E-14 의 ``reveal`` + ``retire`` 가 그것이다.

    이것을 재어 두는 이유: 실행이 안 된다는 이유로 후보를 만들지 않는 것과,
    실행이 되는데도 후보를 만들지 않는 것은 **다른 사실**이다. 지금은 뒤쪽이다.
    """
    duel = duel_at(
        repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON), their_mzone=(LUSTER_DRAGON,)
    )
    gift = set_down(duel, P0, GIFT_OF_GREED)
    next_own_turn(duel)
    their_hand = len(duel.state.player(P1).zones[Zone.HAND])
    result = _force_execute(duel, gift, GIFT_OF_GREED)
    assert result["stage"] == "resolved", result
    assert result["zone"] is Zone.GRAVE
    assert len(duel.state.player(P1).zones[Zone.HAND]) == their_hand + 2

    duel = duel_at(
        repository,
        mine=(PRIMER, LUSTER_DRAGON),
        theirs=(LUSTER_DRAGON,) * 6,
    )
    primer = set_down(duel, P0, PRIMER)
    next_own_turn(duel)
    result = _force_execute(duel, primer, PRIMER)
    assert result["stage"] == "resolved", result
    assert result["zone"] is Zone.GRAVE
    assert len(duel.state.player(P1).zones[Zone.HAND]) == 5


@pytest.mark.real_card
def test_08_the_two_that_do_not_execute_fail_for_non_trap_reasons(repository):
    """
    **§19 · §29-17 — 남은 둘이 막히는 이유는 함정과 무관하다.**

    ``강제 탈출 장치``
        해결 계층이 ``Card.IsAbleToHand`` 를 옮기지 못했다. 판정할 수 없는
        것을 허가로 바꾸지 않으므로 ``RULE_NOT_IMPLEMENTED`` 로 멈춘다. **조작
        관문의 공백**이고, 마법이 같은 조작을 써도 같다.
    ``벌금``
        ``target_combinations`` 가 **단일 대상만** 열거한다 (``minimum != 1``
        이면 빈 목록). 벌금은 ``minimum=maximum=2`` 이고, 등재된 효과 중
        ``minimum>1`` 인 것은 **이 한 장뿐**이다 — 즉 이 공백은 함정에서
        드러났을 뿐 함정의 것이 아니다 (Phase 3-E-4 의 다리 범위).

    둘을 "함정이라서 안 된다" 로 적으면 고칠 곳을 틀리게 가리킨다. 그래서
    ``SET_CARD_EFFECT_EXECUTION`` 과 ``SET_ACTIVATION_EXECUTION`` 을 나눠
    적는다.
    """
    duel = duel_at(
        repository, mine=(FORCEOUT, LUSTER_DRAGON), their_mzone=(LUSTER_DRAGON,)
    )
    forceout = set_down(duel, P0, FORCEOUT)
    next_own_turn(duel)
    result = _force_execute(duel, forceout, FORCEOUT)
    assert result["combos"] == 1, "대상은 찾았다"
    assert result["stage"] == "resolve", result
    assert "IsAbleToHand" in result["detail"], result["detail"]

    duel = duel_at(repository, mine=(FINE,) + (LUSTER_DRAGON,) * 5)
    fine = set_down(duel, P0, FINE)
    next_own_turn(duel)
    result = _force_execute(duel, fine, FINE)
    assert result["stage"] == "target_bridge", result
    assert result["combos"] == 0, "다리가 여러 장 고르기를 열거하지 못한다"

    # 그리고 그 한계는 **카드 종류와 무관하다** — 다리가 단일 대상만 센다.
    bridge = pathlib.Path("engine/target_bridge.py").read_text(encoding="utf-8")
    assert "choice.minimum != 1 or choice.maximum != 1" in bridge
    multi = [
        entry.definition.source_card_id
        for entry in EFFECT_LIBRARY
        for binding in entry.definition.targets
        if (getattr(binding.spec, "to_dict", dict)().get("choice") or {}).get(
            "minimum", 1
        )
        > 1
    ]
    assert multi == [FINE], multi


# ======================================================================
# §15 · §16 · §17 · §18 — 경계와 불변
# ======================================================================


@pytest.mark.real_card
def test_09_the_opponent_learns_nothing_about_a_set_trap(repository):
    """
    **§15 · §16 · §29-9 — 함정이라는 사실조차 공개하지 않는다.**

    "함정이라서 응답 후보가 될 수 있다" 는 것은 정체를 아는 쪽만 할 수 있는
    말이다. 그래서 상대 관측에는 카드 종류도 정의도 세트한 턴도 없다.
    """
    duel = duel_at(repository, mine=(GIFT_OF_GREED, FORCEOUT, LUSTER_DRAGON))
    set_down(duel, P0, GIFT_OF_GREED)
    set_down(duel, P0, FORCEOUT)

    theirs = duel.view(P1)
    seen = [c for c in theirs.opponent.zone(Zone.SZONE).cards if c is not None]
    assert [(c.card_id, c.name, c.definition) for c in seen] == [
        (None, None, None),
        (None, None, None),
    ]
    assert theirs.opponent.zone(Zone.SZONE).size == 2

    for viewer in (P0, P1):
        payload = duel.view(viewer).to_dict()
        assert not [
            key
            for key in payload
            if "set_turn" in key or "trap" in key.lower() or "activation" in key
        ]


@pytest.mark.real_card
def test_10_this_phase_changed_no_behaviour(repository):
    """
    **§17 · §18 · §29-10~14 — 감사이므로 판이 달라지지 않는다.**

    후보 수 · 점수 · 해시 · 난수 네 개를 함께 센다. 이 Phase 가 고친 것은
    **막는 이유 문자열** 하나이므로 넷 다 그대로여야 한다.
    """
    duel = duel_at(
        repository,
        mine=(GIFT_OF_GREED, POT_OF_GREED, LUSTER_DRAGON),
        their_mzone=(LUSTER_DRAGON,),
    )
    set_down(duel, P0, GIFT_OF_GREED)
    next_own_turn(duel)

    # 함정은 후보가 아니고, 통상 마법은 후보다.
    assert activations(duel, P0, GIFT_OF_GREED) == []
    assert activations(duel, P0, POT_OF_GREED) != []

    before_hash = duel.state.state_hash()
    before_draws = duel.state.randomness.draws
    before_value = StateEvaluator().evaluate(duel.view(P0))

    # 후보를 여러 번 만들어도 판이 바뀌지 않는다 (읽기만 한다).
    for _ in range(3):
        duel.legal_actions(P0)
        duel.legal_actions(P1)

    assert duel.state.state_hash() == before_hash
    assert duel.state.randomness.draws == before_draws
    after_value = StateEvaluator().evaluate(duel.view(P0))
    assert (after_value.heuristic, after_value.terms) == (
        before_value.heuristic,
        before_value.terms,
    )

    # 그리고 평가 · 탐색이 함정을 읽지 않는다.
    # 평가 · 탐색은 이 Phase 가 읽은 것들을 **읽지 않는다.** ("TRAP" 같은
    # 흔한 조각으로 재면 ``SPELL_TRAP_IN_LP`` 같은 무관한 상수에 걸린다 —
    # 실제로 걸렸고, 그래서 읽는 **대상**을 이름으로 짚는다.)
    for path in ("agent/evaluation.py", "agent/search.py", "agent/policy.py"):
        source = pathlib.Path(path).read_text(encoding="utf-8")
        for forbidden in (
            "_OUT_OF_SCOPE_TYPES",
            "TRAP_TRIGGER_MISSING",
            "trigger_event",
            "rule_uses",
            "set_this_turn",
        ):
            assert forbidden not in source, (path, forbidden)


@pytest.mark.real_card
def test_11_clone_keeps_the_set_trap_record_independent(repository):
    """**§29-10 · §29-11 — 복제는 옮기고, 사본의 변경은 번지지 않는다.**"""
    duel = duel_at(repository, mine=(GIFT_OF_GREED, FORCEOUT, LUSTER_DRAGON))
    turn = duel.state.turn.turn_number
    instance = set_down(duel, P0, GIFT_OF_GREED)

    clone = duel.state.clone()
    assert clone.rule_uses.used_card(turn, P0, instance, SET_ACTION)
    assert clone.state_hash() == duel.state.state_hash()

    before = duel.state.state_hash()
    fork = Duel(state=clone, priority=duel.priority)
    set_down(fork, P0, FORCEOUT)
    assert duel.state.state_hash() == before
    assert clone.state_hash() != before


def test_12_no_new_engine_subsystem_was_created():
    """**§21 · §27 — 새 시스템을 만들지 않았다.** 감사의 결과물은 측정과 문장이다."""
    for module in pathlib.Path("engine").rglob("*.py"):
        source = module.read_text(encoding="utf-8")
        for forbidden in (
            "class TrapEngine",
            "class TrapTimingEngine",
            "class TrapResponseEngine",
            "class TriggerGraph",
            "class TimingGraph",
            "class EffectGraph",
            "class RuleGraph",
        ):
            assert forbidden not in source, (module.name, forbidden)

    kinds = {k.value for k in PlayerActionKind}
    for invented in ("activate_trap", "set_trap", "trap_response"):
        assert invented not in kinds


# ======================================================================
# §24 — 의도적 위반
# ======================================================================


@pytest.mark.real_card
def test_13_a_trap_must_not_be_read_as_spell_speed_one(repository):
    """
    **§24-A — 함정을 통상 마법처럼 다루면 깨져야 한다.**

    함정의 스펠 스피드는 **2** 다 (RULE-SPELLTRAP-008). 1 로 읽으면 두 가지가
    동시에 틀린다 — 체인에 응수할 수 없게 되고, 세트한 턴 제약이 걸리지 않게
    된다 (``_set_turn_refusal`` 이 스펠 스피드 1 을 그냥 통과시킨다).

    즉 "함정 = 마법" 이라는 한 번의 착각이 **두 규칙을 동시에** 무너뜨린다.
    """
    for card_id in ALL_TRAPS:
        card = repository.get(card_id)
        speed = classify_spell_speed(card)
        assert speed.speed is SpellSpeed.FAST, card.name
        assert speed.speed is not SpellSpeed.NORMAL

    duel = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    instance = set_down(duel, P0, GIFT_OF_GREED)
    action = made(P0, instance, GIFT_OF_GREED)
    # 세트한 턴 → 스펠 스피드 2 이므로 반드시 막힌다.
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(duel.chain, duel.priority, set_this_turn=True), action
    )
    assert timed.validity is ActionValidity.INVALID


@pytest.mark.real_card
def test_14_ignoring_the_set_turn_must_break_the_two_turn_distinction(repository):
    """
    **§24-B — 세트한 턴을 무시하면 같은 턴과 다음 턴이 구별되지 않는다.**

    두 판은 자리도 표시 형식도 같고 **세트한 턴만** 다르다. 기록을 읽지 않으면
    둘이 같은 답을 내고, 그 순간 RULE-SPELLTRAP-009 가 사라진다.
    """
    same = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    same_instance = set_down(same, P0, GIFT_OF_GREED)

    later = duel_at(repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON))
    later_instance = set_down(later, P0, GIFT_OF_GREED)
    next_own_turn(later)

    for duel, instance in ((same, same_instance), (later, later_instance)):
        [card] = [c for c in duel.state.player(P0).zones[Zone.SZONE] if c is not None]
        assert card.zone is Zone.SZONE
        assert card.position is Position.FACEDOWN

    assert same._set_this_turn(made(P0, same_instance, GIFT_OF_GREED)) is True
    assert later._set_this_turn(made(P0, later_instance, GIFT_OF_GREED)) is False

    checker = ActivationTimingChecker(same.view(P0))
    refused = checker.check(
        ActivationTiming(same.chain, same.priority, set_this_turn=True),
        made(P0, same_instance, GIFT_OF_GREED),
    )
    allowed = ActivationTimingChecker(later.view(P0)).check(
        ActivationTiming(later.chain, later.priority, set_this_turn=False),
        made(P0, later_instance, GIFT_OF_GREED),
    )
    assert (refused.validity, allowed.validity) == (
        ActionValidity.INVALID,
        ActionValidity.VALID,
    )


@pytest.mark.real_card
def test_15_the_response_seat_must_not_be_the_turn_player(repository):
    """
    **§24-C — 응답 자리를 턴 플레이어와 같다고 보면 상대 턴 응답이 사라진다.**

    상대 턴의 응답 창에서 응답 자리는 **내가** 쥔다. 그 둘을 같다고 보면
    ``to_act`` 가 상대가 되고, 세트한 함정이 열리는 날에도 후보를 받을 자리가
    없어진다.

    그래서 창이 열린 자리에서 세 값이 **서로 다른** 것을 고정한다.
    """
    duel = duel_at(
        repository, mine=(GIFT_OF_GREED, LUSTER_DRAGON), theirs=(POT_OF_GREED,)
    )
    set_down(duel, P0, GIFT_OF_GREED)
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = P1
    duel.priority = PriorityState.idle(turn_player=P1, phase=Phase.MAIN1)
    assert duel.apply(activations(duel, P1, POT_OF_GREED)[0]).accepted

    assert duel.turn_player == P1
    assert duel.priority.holder.is_seat(P0)
    assert duel.to_act == P0
    assert duel.to_act != duel.turn_player, "응답 자리와 턴 플레이어가 같아졌다"
    assert duel.priority.turn_player == P1, "우선권이 턴 플레이어를 바꿨다"
