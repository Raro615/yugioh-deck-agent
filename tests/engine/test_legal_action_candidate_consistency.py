"""
Phase 6-S — 후보 생성 · 합법성 판정 · 실제 실행의 정합성.

🔴 먼저 §2 의 전제를 **정정한다**
---------------------------------
지시문 §2 가 이렇게 적었다.

    "``Duel._activation_actions`` 가 발동 후보를 생성하는 과정에서
     ``legal_actions`` 의 공용 계약과 **별도로 동작하는 경로**가 존재한다."

**그런 경로는 없다.** AST 로 세면 ``_activation_actions`` 의 생산 호출은
**정확히 두 곳**이고 **둘 다 ``legal_actions`` 안**이다 (``A`` 절). 그것은
별도 경로가 아니라 ``legal_actions`` 의 **사설 보조 함수**다.

그리고 후보 생성과 실제 실행은 **같은 관문 함수**를 부른다 —
``Duel._activation_gate`` 의 생산 호출도 정확히 두 곳이고, 하나는
``_activation_actions`` (후보 생성), 하나는 ``_apply_activation`` (실행)
이다 (``B`` 절). 둘이 각자 관문을 세우고 있었던 것이 STRUCTURAL-134 였고,
그것은 Phase 3-E-13 에서 이미 합쳐졌다.

관문은 셋이고, 셋이 **서로 다른 것을 본다**
-------------------------------------------
========================================  ==================================
1 ``ActionValidator``                      규칙 쪽. ``GameStateView`` **만**
                                           읽는다 (ADR-007)
2 ``ActivationTimingChecker``              스펠 스피드 · 세트한 턴. 체인과
                                           ``rule_uses`` 는 관측에 **없다**
3 ``EffectActivator.can_activate``         조건 · 비용 · 대상 — "우리가 할
                                           수 있는가" (ADR-006)
========================================  ==================================

🔴 **그래서 ``ActionValidator`` 하나가 VALID 라고 해서 후보가 되지 않는
것이 정상이다.** 이 파일의 첫 측정이 바로 그것을 잘못 비교해서 "거짓 음성
4건" 을 보고했고, 관문 셋으로 다시 재면 **0건**이다 (``D`` 절이 그 정정을
재어서 남긴다).

🔴 유일하게 남은 후보는 **룰북이 금지한다**
-------------------------------------------
"상대 턴 · 창 닫힘" 에서 세트된 일반 함정은 관문 셋을 **전부 통과**하고
실행 구현도 있는데 후보로 나오지 않는다. 이것이 거짓 음성처럼 보였다.
**아니다** — 룰북 ``TURN PLAYER'S PRIORITY`` 가 이렇게 적는다.

    "As long as the turn player has Priority, **the opponent cannot
     activate cards or effects**, except for effects that activate
     automatically, like Trigger or Flip effects."

엔진의 ``PriorityState.idle(turn_player=X)`` 가 바로 그 자리다 — X 가
우선권을 쥐고 있고 아직 넘기지 않았다. Phase 6-Q 의
``test_f04_the_response_window_decides_who_may_activate`` 가 이것을 이미
못 박았고, 그 판단이 **옳았다** (``D`` 절이 룰북 줄과 대조한다).

🔴 **그러면 무엇이 빠져 있는가** — 같은 룰북 줄의 뒷부분이다.

    "After a card's activation, **and at the end of each phase or step**,
     Priority passes to the opponent."

엔진은 **앞쪽만** 구현했다 (발동 뒤에 창이 열린다). **페이즈 · 스텝의
끝에서 우선권이 넘어가는 절반이 없다.** 그것이 실제 듀얼 루프에서 상대 턴
함정이 닿지 않는 이유이고, ``I`` 절이 재어서 남긴다 (고치지 않는다 —
우선권 모델 확장이고 §16 의 범위 밖이다).

이 Phase 가 고친 것 — ``_flow_actions`` 의 **묶인 조건 하나**
-------------------------------------------------------------
"패스할 수 없다" 의 이유가 둘인데 ``elif seat != self.turn_player`` 하나에
묶여 있었다. 그래서 두 가지가 틀렸다 (``F`` 절이 넷을 전수로 센다).

① 창이 **열려 있는데** 상대가 쥔 자리에서 "우선권이 열려 있지 않습니다" —
  **거짓 문장**
② 창이 열려 있고 상대가 쥐었는데 이쪽이 **턴 플레이어이면** 어느 분기도
  밟지 않아 **후보 0 · 보류 0** — **침묵**

후보 목록은 **한 건도 변하지 않았다** (``allowed`` 는 그대로다). 바뀐 것은
``withheld`` 가 사실을 말하게 된 것뿐이다.
"""

import ast
import collections
import inspect
import json
import pathlib
import textwrap

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTarget
from engine.action_validation import ActionValidator
from engine.activation_timing import ActivationTiming, ActivationTimingChecker
from engine.duel import Duel, LegalActions, WithheldAction, duel_components
from engine.effect.journal import EventJournal
from engine.effect.library import EFFECT_LIBRARY, definition_registry
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.spell_activation import activatable_effects
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.target_bridge import TargetBridgeError, selections_for, target_combinations
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
P0, P1 = 0, 1

POT = 55144522       # 욕망의 항아리 — 통상 마법
GIFT = 5915629       # 욕망의 선물 — 일반 함정
FINE = 92595643      # 벌금 — 일반 함정 · 패 2장 (6-P)
FORCEOUT = 94192409  # 강제 탈출 장치 — 일반 함정 (6-O)
LOST = 24623598      # 로스트 — executable=False
PRIMER = 69091732    # 의적의 입문서 — 상대 패 5장 이상
HONEST = 37742478    # 어니스트 — 기동 효과 (6-L)
RELOAD = 22589918    # 리로드 — 속공 마법
LUSTER = 11091375    # 통상 몬스터

DEFS = definition_registry()
EXECUTOR_KINDS = frozenset(duel_executor().supported)
FLOW_KINDS = frozenset({PlayerActionKind.PASS, PlayerActionKind.END_PHASE})
SWEPT_ZONES = (Zone.HAND, Zone.MZONE, Zone.SZONE, Zone.GRAVE, Zone.DECK, Zone.REMOVED)


# ======================================================================
# 판 만들기 · 측정 도구
# ======================================================================


def board(
    repository,
    *,
    my_deck=30,
    their_deck=30,
    my_hand=(),
    their_hand=(),
    my_mzone=(),
    their_mzone=(),
    my_hand_fodder=0,
    their_hand_fodder=0,
    turn_player=P0,
    phase=Phase.MAIN1,
    journal=None,
):
    state = GameState.create(
        repository,
        decks=([LUSTER] * my_deck, [LUSTER] * their_deck),
        turn_player=turn_player,
        seed=1,
    )
    hands = {P0: [], P1: []}
    for seat, cards in ((P0, my_hand), (P1, their_hand)):
        for card_id in cards:
            hands[seat].append(
                state.create_instance(
                    card_id, owner=seat, zone=Zone.HAND
                ).instance_id
            )
    for seat, count in ((P0, my_hand_fodder), (P1, their_hand_fodder)):
        for _ in range(count):
            state.create_instance(LUSTER, owner=seat, zone=Zone.HAND)
    placed = {P0: [], P1: []}
    for seat, layout in ((P0, my_mzone), (P1, their_mzone)):
        for card_id in layout:
            card = state.create_instance(card_id, owner=seat, zone=Zone.HAND)
            state.move(
                card, Zone.MZONE, to_player=seat, position=Position.FACEUP_ATTACK
            )
            placed[seat].append(card.instance_id)
    state.turn.turn_number = 5
    state.turn.turn_player = turn_player
    state.turn.set_phase(phase)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=turn_player, phase=phase),
        **duel_components(journal=journal),
    )
    return duel, hands, placed


def set_down(duel, instance, seat=P0):
    step = duel.apply(PlayerAction.set_spell_trap(actor=seat, source=instance))
    assert step.accepted, step.reason
    return step


def next_turn(duel, to_seat, phase=Phase.MAIN1):
    duel.state.turn.turn_number += 1
    duel.state.turn.turn_player = to_seat
    duel.state.turn.set_phase(phase)
    duel.priority = PriorityState.idle(turn_player=to_seat, phase=phase)


def activation(seat, instance, card_id, targets=()):
    return PlayerAction.activate_effect(
        actor=seat,
        source=instance,
        effect_ref=EffectRef(card_id, 0),
        targets=targets,
    )


def all_effect_refs(card_id):
    """🔴 ``activatable_effects`` 가 아니라 **등재된 전부**."""
    return tuple(
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if entry.definition.effect_ref.card_id == card_id
    )


def conceivable(duel, seat):
    """이 자리에서 **적어 볼 수 있는 모든** 행위 — 흐름 둘까지."""
    out = []
    state = duel.state
    victims = [
        card.instance_id
        for card in state.player(1 - seat).zone(Zone.MZONE)
        if card
    ]
    for zone in SWEPT_ZONES:
        for card in state.player(seat).zone(zone):
            if card is None:
                continue
            iid = card.instance_id
            out.append(PlayerAction.normal_summon(actor=seat, source=iid))
            out.append(PlayerAction.special_summon(actor=seat, source=iid))
            out.append(PlayerAction.set_monster(actor=seat, source=iid))
            out.append(PlayerAction.set_spell_trap(actor=seat, source=iid))
            out.append(PlayerAction.activate_card(actor=seat, source=iid))
            out.append(PlayerAction.change_position(actor=seat, source=iid))
            out.append(PlayerAction.attack_directly(actor=seat, source=iid))
            for victim in victims:
                out.append(
                    PlayerAction.attack(
                        actor=seat,
                        source=iid,
                        target=ActionTarget.instance(victim),
                    )
                )
            for ref in all_effect_refs(card.card_id):
                definition = DEFS.definition_for(ref)
                if definition is None:  # pragma: no cover - 등록소가 보증한다
                    continue
                for targets in target_combinations(state, seat, definition, iid):
                    out.append(
                        PlayerAction.activate_effect(
                            actor=seat, source=iid, effect_ref=ref, targets=targets
                        )
                    )
    out.append(PlayerAction.passing(actor=seat))
    out.append(PlayerAction.end_phase(actor=seat))
    return out


def execution_ready(action):
    """
    §5-C ``EXECUTION_READY`` — **실행 구현이 있는가.** 합법성과 다른 질문이다.
    """
    kind = action.kind
    if kind in FLOW_KINDS:
        return True, "Duel 이 직접 처리한다"
    if kind is PlayerActionKind.ACTIVATE_EFFECT:
        if action.effect_ref is None:  # pragma: no cover - 생성자가 막는다
            return False, "effect_ref 가 없다"
        definition = DEFS.definition_for(action.effect_ref)
        if definition is None:
            return False, "정의가 등재되지 않았다"
        if not definition.operations:
            return False, "옮긴 조작이 없다 (executable=False)"
        try:
            selections_for(definition, action)
        except TargetBridgeError as error:
            return False, f"선택 절차 미지원: {error}"
        return True, f"조작 {len(definition.operations)}개"
    if kind in EXECUTOR_KINDS:
        return True, "실행기에 등록되어 있다"
    return False, "실행기에 등록되지 않았다"


def may_act(duel, seat):
    """
    🔴 **네 번째 판정자 — 이 자리가 지금 **행위를 고를 수 있는가**.

    관문 셋은 "이 발동이 적법한가" 에 답하고, 이것은 그 앞의 질문
    ("이 사람이 지금 무엇이든 고를 수 있는가") 에 답한다. 룰북이 그것을
    따로 적는다 (``TURN PLAYER'S PRIORITY``)::

        As long as the turn player has Priority, the opponent cannot
        activate cards or effects …

    ``legal_actions`` 의 분기 조건이 바로 이 판정이다. 여기서 **베끼지
    않고** 그 조건이 참이 되는 두 자리를 그대로 적는다 —
    ``test_d05`` 가 이 함수와 ``legal_actions`` 의 실제 동작을 대조한다.
    """
    if duel.priority.is_open:
        return duel.priority.holds(seat)
    return seat == duel.turn_player


def gate_of(duel, action, validator):
    """
    **어느 관문이 막았는가.** 셋을 하나씩 물어본다.

    🔴 ``_activation_gate`` 를 베끼지 않는다 — 셋을 따로 물어야 "어느 관문"
    을 말할 수 있고, 합친 답은 ``test_b02`` 가 그 함수로 직접 대조한다.
    """
    first = validator.validate(action)
    if first.validity is not ActionValidity.VALID:
        return "1 ActionValidator", first
    timed = ActivationTimingChecker(validator.view).check(
        ActivationTiming(
            duel.chain, duel.priority, set_this_turn=duel._set_this_turn(action)
        ),
        action,
    )
    if timed.validity is not ActionValidity.VALID:
        return "2 ActivationTimingChecker", timed
    definition = DEFS.definition_for(action.effect_ref)
    third = duel._activator.can_activate(
        duel.state,
        duel.chain,
        action,
        selections=selections_for(definition, action),
        authorization=first,
    )
    if third.validity is not ActionValidity.VALID:
        return "3 can_activate", third
    return "통과", third


def audit(duel, seat):
    """
    한 상태를 **전수로** 센다. 돌려주는 것은 §8 의 네 수와 §10 의 증거다.
    """
    before = (duel.state.state_hash(), duel.state.randomness.draws)
    legal = duel.legal_actions(seat)
    for _ in range(3):  # §10-9 몇 번 만들어도 판이 바뀌지 않는다
        duel.legal_actions(seat)
    after = (duel.state.state_hash(), duel.state.randomness.draws)

    allowed = list(legal.allowed)
    validator = ActionValidator(duel.view(seat), definitions=DEFS)
    allowed_set = set(allowed)

    false_positive = []
    for action in allowed:
        if action.kind in FLOW_KINDS:
            continue  # 흐름은 검증기가 아니라 흐름 계층이 답한다
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
            gate, verdict = gate_of(duel, action, validator)
            if gate != "통과":
                false_positive.append((action, f"{gate} {verdict.code.name}"))
            continue
        verdict = validator.validate(action)
        if verdict.validity is not ActionValidity.VALID:
            false_positive.append((action, verdict.code.name))

    not_ready = [
        (action, why)
        for action in allowed
        for ok, why in [execution_ready(action)]
        if not ok
    ]

    false_negative = []
    blocked = collections.Counter()
    acting = may_act(duel, seat)
    for action in conceivable(duel, seat):
        if action in allowed_set or action.kind in FLOW_KINDS:
            continue
        if not acting:
            #: 🔴 **네 번째 판정자가 먼저 막는다** — 관문을 묻기도 전이다.
            #: 룰북 §82 가 금지하는 자리이므로 거짓 음성이 아니다
            #: (``test_d03`` 가 원문과 대조한다). 발동만 센다 — 다른
            #: 종류까지 넣으면 수가 열거 크기에 묻힌다.
            if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
                blocked["0 우선권 (룰북 TURN PLAYER'S PRIORITY)"] += 1
            continue
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
            gate, _ = gate_of(duel, action, validator)
            if gate != "통과":
                blocked[gate] += 1
                continue
            ok, _ = execution_ready(action)
            if ok:
                false_negative.append(action)
            else:
                blocked["구현 없음 (ADR-006)"] += 1
            continue
        if validator.validate(action).validity is ActionValidity.VALID:
            ok, _ = execution_ready(action)
            if ok:
                false_negative.append(action)
            else:
                blocked["구현 없음 (ADR-006)"] += 1

    return dict(
        legal=legal,
        allowed=allowed,
        false_positive=false_positive,
        false_negative=false_negative,
        not_ready=not_ready,
        blocked=blocked,
        duplicates=len(allowed) - len(allowed_set),
        mutated=before != after,
        silent=not allowed and not legal.withheld and not duel.is_over,
    )


def chain_board(repository, *, depth, my_deck=5):
    """
    🔴 **깊이마다 판을 새로 만든다.**

    같은 ``Duel`` 을 여러 자리에서 재사용하면 뒤에 적용한 걸음이 앞 자리의
    측정을 덮는다 — 처음 적을 때 그렇게 썼고, ``test_f03`` 가 그것을 잡았다.
    ``Duel`` 은 가변이므로 "그 시점" 을 들고 있으려면 그 시점까지만 민 판이
    따로 있어야 한다.

    ``depth=0`` 체인 없음 · ``1`` 체인 1 뒤 · ``2`` 체인 2 뒤.
    """
    duel, hands, _ = board(
        repository,
        my_deck=my_deck,
        my_hand=(POT,),
        their_hand=(GIFT,),
        turn_player=P1,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    if depth >= 1:
        step = duel.apply(activation(P0, pot, POT))
        assert step.accepted, step.reason
    if depth >= 2:
        picks = [
            a
            for a in duel.legal_actions(P1).allowed
            if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        ]
        assert len(picks) == 1, duel.legal_actions(P1).allowed
        step = duel.apply(picks[0])
        assert step.accepted, step.reason
    return duel, pot, gift


def all_states(repository):
    """§7 의 A~G — 실제 엔진으로 만든 상태 스물."""
    out = []

    # A 일반적인 메인 페이즈
    duel, hands, _ = board(repository, my_hand=(LUSTER, LUSTER, POT, GIFT))
    out.append(("A1 메인1 · 소환권 미사용", duel, P0))
    for label, seat in (("A2 소환권 사용 뒤", P0), ("A3 상대 자리 (내 턴)", P1)):
        fresh, fresh_hands, _ = board(
            repository, my_hand=(LUSTER, LUSTER, POT, GIFT)
        )
        step = fresh.apply(
            PlayerAction.normal_summon(actor=P0, source=fresh_hands[P0][0])
        )
        assert step.accepted, step.reason
        out.append((label, fresh, seat))

    # B 마법 카드 발동
    duel, _, _ = board(repository, my_hand=(POT,))
    out.append(("B1 통상 마법 발동 가능", duel, P0))
    duel, _, _ = board(repository, my_hand=(POT,), my_deck=1)
    out.append(("B2 덱 1장 — 카드 조건 거짓", duel, P0))
    duel, _, _ = board(repository, my_hand=(POT,), phase=Phase.BATTLE)
    out.append(("B3 배틀 페이즈", duel, P0))

    # C 세트된 함정
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    set_down(duel, hands[P0][0])
    out.append(("C1 세트한 턴", duel, P0))
    duel_c2, hands_c2, _ = board(repository, my_hand=(GIFT,))
    set_down(duel_c2, hands_c2[P0][0])
    next_turn(duel_c2, P1)
    out.append(("C2 상대 턴 · 내 세트 함정", duel_c2, P0))
    duel_c3, hands_c3, _ = board(repository, my_hand=(GIFT,))
    set_down(duel_c3, hands_c3[P0][0])
    next_turn(duel_c3, P1)
    next_turn(duel_c3, P0)
    out.append(("C3 다음 내 턴", duel_c3, P0))

    # D 상대 턴 체인 — 🔴 자리마다 판을 **새로** 만든다 (``chain_board``)
    out.append(("D1 체인 1 뒤 · 응답권자 P1", chain_board(repository, depth=1)[0], P1))
    out.append(("D2 체인 1 뒤 · 창을 쥐지 않은 P0", chain_board(repository, depth=1)[0], P0))
    out.append(("D3 체인 2 뒤 · 응답권자 P0", chain_board(repository, depth=2)[0], P0))
    out.append(("D4 체인 2 뒤 · 창을 쥐지 않은 P1", chain_board(repository, depth=2)[0], P1))

    # E 몬스터 효과
    duel, _, placed = board(repository, my_mzone=(HONEST,))
    out.append(("E1 어니스트 MZONE", duel, P0))
    duel, _, _ = board(repository, my_hand=(HONEST,))
    out.append(("E2 어니스트 패 (잘못된 위치)", duel, P0))

    # F 복수 대상 효과
    for fodder, label in ((3, "F1 벌금 · 후보 3장"), (1, "F2 벌금 · 후보 1장")):
        duel, hands, _ = board(repository, my_hand=(FINE,), my_hand_fodder=fodder)
        set_down(duel, hands[P0][0])
        next_turn(duel, P1)
        next_turn(duel, P0)
        out.append((label, duel, P0))

    # G 미지원 행동
    duel, hands, _ = board(repository, my_hand=(LOST,), their_hand_fodder=6)
    set_down(duel, hands[P0][0])
    next_turn(duel, P1)
    next_turn(duel, P0)
    out.append(("G1 로스트 (executable=False)", duel, P0))
    duel, hands, _ = board(repository, my_hand=(PRIMER,), their_hand_fodder=2)
    set_down(duel, hands[P0][0])
    next_turn(duel, P1)
    next_turn(duel, P0)
    out.append(("G2 입문서 · 상대 패 2장", duel, P0))
    duel, hands, _ = board(
        repository, my_hand=(FORCEOUT,), their_mzone=(LUSTER,)
    )
    set_down(duel, hands[P0][0])
    next_turn(duel, P1)
    next_turn(duel, P0)
    out.append(("G3 강제 탈출 장치 (6-O)", duel, P0))
    return out


def method_tree(func):
    return ast.parse(textwrap.dedent(inspect.getsource(func)))


def production_source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def call_sites(name):
    """생산 코드에서 ``name`` 을 부르는 자리 — ``(파일, 함수)``."""
    out = []
    for root in ("engine", "agent", "app", "core", "analysis", "rules",
                 "rulings", "sources", "scripts"):
        for path in sorted((ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            stack = []

            class Visitor(ast.NodeVisitor):
                def visit_FunctionDef(self, node):  # noqa: N802
                    stack.append(node.name)
                    self.generic_visit(node)
                    stack.pop()

                visit_AsyncFunctionDef = visit_FunctionDef

                def visit_Call(self, node):  # noqa: N802
                    func = node.func
                    called = (
                        func.attr
                        if isinstance(func, ast.Attribute)
                        else getattr(func, "id", None)
                    )
                    if called == name:
                        out.append(
                            (
                                str(path.relative_to(ROOT)),
                                stack[-1] if stack else "<module>",
                            )
                        )
                    self.generic_visit(node)

            Visitor().visit(tree)
    return out


# ======================================================================
# A. §2 정정 — ``_activation_actions`` 는 사설 보조 함수다
# ======================================================================


@pytest.mark.real_card
def test_a01_activation_actions_is_called_only_inside_legal_actions():
    """
    🔴 **§2 의 전제를 정정한다.** 별도 경로가 아니다.

    생산 호출이 **두 곳**이고 둘 다 ``legal_actions`` 안이다. 두 번 부르는
    이유는 자리가 둘이기 때문이다 — 창이 열린 자리와 턴 플레이어의 자리.
    """
    sites = call_sites("_activation_actions")
    assert sites == [
        ("engine/duel.py", "legal_actions"),
        ("engine/duel.py", "legal_actions"),
    ], sites


@pytest.mark.real_card
def test_a02_activation_actions_is_not_public():
    """**이름이 사설이다** — 밑줄로 시작하고 ``__all__`` 에 없다."""
    from engine import duel as duel_module

    assert "_activation_actions" not in duel_module.__all__
    assert "_activation_gate" not in duel_module.__all__
    assert "legal_actions" not in duel_module.__all__  # 메서드다
    assert "Duel" in duel_module.__all__


@pytest.mark.real_card
def test_a03_legal_actions_is_the_only_public_candidate_source():
    """
    **외부가 읽는 후보 목록은 하나다.** 호출자 다섯 곳 전부 ``legal_actions``
    을 부른다 — ``_activation_actions`` 를 직접 부르는 외부 호출자가 없다.
    """
    sites = call_sites("legal_actions")
    assert ("engine/duel.py", "apply") in sites
    assert ("agent/runner.py", "step") in sites
    simulation = [s for s in sites if s[0] == "agent/simulation.py"]
    assert len(simulation) == 3, simulation
    #: 🔴 ``agent`` · ``app`` 어디에도 사설 보조 함수를 부르는 자리가 없다.
    for path, _ in call_sites("_activation_actions"):
        assert path == "engine/duel.py", path


# ======================================================================
# B. 관문 셋 — 후보 생성과 실행이 **같은 함수**를 부른다
# ======================================================================


@pytest.mark.real_card
def test_b01_the_gate_is_shared_by_generation_and_execution():
    """
    🔴 **STRUCTURAL-134 의 해소가 코드에 남아 있다** (Phase 3-E-13).

    ``_activation_gate`` 의 생산 호출이 **셋**이고, 둘은 후보 생성
    (``_activation_actions`` · ``_trigger_actions``) 하나는 실행
    (``_apply_activation``) 이다.

    🔴 **Phase 6-Z 가 셋째를 더했다.** 유발 후보는 사건에서 나오므로 판에서
    후보를 만드는 ``_activation_actions`` 와 **출처가 다르다** — 그래서 함수를
    갈랐다. 그러나 관문은 **하나**다: 새 함수가 제 관문을 세우면 그 순간
    STRUCTURAL-134 가 되돌아온다 (목록을 만든 자리와 적용하는 자리가 서로 다른
    판을 읽는 어긋남).
    """
    sites = sorted(call_sites("_activation_gate"))
    assert sites == [
        ("engine/duel.py", "_activation_actions"),
        ("engine/duel.py", "_apply_activation"),
        ("engine/duel.py", "_trigger_actions"),
    ], sites


@pytest.mark.real_card
def test_b02_the_gate_asks_three_layers_in_order(repository):
    """
    **관문 셋이 코드에 그대로 있다** — 그리고 순서가 의미를 갖는다.

    1 번이 거절하면 2·3 을 묻지 않는다. 합치면 구현이 없는 카드가 **규칙
    위반**으로 읽히고 그것은 거짓이다 (ADR-006).
    """
    tree = method_tree(Duel._activation_gate)
    names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attrs = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    ]
    assert "ActivationTimingChecker" in names
    assert "ActivationTiming" in names
    assert "validate" in attrs
    assert "can_activate" in attrs

    #: 합친 답이 하나씩 물은 답과 **같다**.
    duel, hands, _ = board(repository, my_hand=(POT,))
    action = activation(P0, hands[P0][0], POT)
    validator = ActionValidator(duel.view(P0), definitions=DEFS)
    gate, _ = gate_of(duel, action, validator)
    assert gate == "통과"
    definition = DEFS.definition_for(action.effect_ref)
    combined = duel._activation_gate(
        action,
        validator=validator,
        selections=selections_for(definition, action),
    )
    assert combined.validity is ActionValidity.VALID


@pytest.mark.real_card
def test_b03_each_gate_blocks_something_different(repository):
    """
    🔴 **셋이 서로 다른 것을 막는다** — 실측으로 세 자리를 전부 밟는다.

    ====================================  ==============================
    1 ``ActionValidator``                  배틀 페이즈의 통상 마법
    2 ``ActivationTimingChecker``          세트한 턴의 함정
    3 ``can_activate``                     카드 조건이 거짓인 효과
    ====================================  ==============================
    """
    # 1 — 배틀 페이즈
    duel, hands, _ = board(repository, my_hand=(POT,), phase=Phase.BATTLE)
    action = activation(P0, hands[P0][0], POT)
    gate, verdict = gate_of(
        duel, action, ActionValidator(duel.view(P0), definitions=DEFS)
    )
    assert gate == "1 ActionValidator", (gate, verdict.reason)

    # 2 — 세트한 턴
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    trap = hands[P0][0]
    set_down(duel, trap)
    gate, verdict = gate_of(
        duel,
        activation(P0, trap, GIFT),
        ActionValidator(duel.view(P0), definitions=DEFS),
    )
    assert gate == "2 ActivationTimingChecker", (gate, verdict.reason)

    # 3 — 카드 조건이 거짓
    duel, hands, _ = board(repository, my_hand=(POT,), my_deck=1)
    gate, verdict = gate_of(
        duel,
        activation(P0, hands[P0][0], POT),
        ActionValidator(duel.view(P0), definitions=DEFS),
    )
    assert gate == "3 can_activate", (gate, verdict.reason)


# ======================================================================
# C. §8 거짓 양성 — **0건**
# ======================================================================


@pytest.mark.real_card
def test_c01_no_candidate_is_refused_by_the_gates(repository):
    """
    🔴 **§8 — 후보로 나온 것은 관문 셋을 전부 통과한다.** 스물 자리 전수.

    발동은 관문 셋으로, 판 행동은 검증기로 다시 묻는다. 흐름 둘은 흐름
    계층의 몫이므로 검증기와 비교하지 않는다 (``F`` 절이 따로 센다).
    """
    total = 0
    offenders = []
    for name, duel, seat in all_states(repository):
        result = audit(duel, seat)
        total += len(result["allowed"])
        for action, why in result["false_positive"]:
            offenders.append((name, action.kind.name, why))
    assert total > 30, total
    assert offenders == [], offenders


@pytest.mark.real_card
def test_c02_every_candidate_has_an_execution_implementation(repository):
    """
    **§3-10 — 실행 구현이 없는 행동을 후보로 내지 않는다.**

    ``activatable_effects`` 가 ``executable`` 만 돌려주므로 (ADR-006) 발동
    후보에는 구현이 있고, 나머지는 실행기 등록을 본다.
    """
    offenders = []
    for name, duel, seat in all_states(repository):
        for action, why in audit(duel, seat)["not_ready"]:
            offenders.append((name, action.kind.name, why))
    assert offenders == [], offenders


@pytest.mark.real_card
def test_c03_an_unexecutable_effect_is_dropped_by_registration_not_by_rules(
    repository,
):
    """
    🔴 **ADR-006 — "구현이 없다" 와 "규칙이 금지한다" 를 가른다.**

    로스트는 ``executable=False`` 다. ``activatable_effects`` 가 아예
    돌려주지 않으므로 후보가 되지 않는다 — 그런데 그것을 ``INVALID`` 로
    적지 않는다.
    """
    assert activatable_effects(LOST) == ()
    assert all_effect_refs(LOST) == (EffectRef(LOST, 0),)
    definition = DEFS.definition_for(EffectRef(LOST, 0))
    assert definition is not None
    assert definition.operations == ()

    duel, hands, _ = board(repository, my_hand=(LOST,), their_hand_fodder=6)
    lost = hands[P0][0]
    set_down(duel, lost)
    next_turn(duel, P1)
    next_turn(duel, P0)
    offered = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert offered == []
    ok, why = execution_ready(activation(P0, lost, LOST))
    assert ok is False
    assert "executable=False" in why


# ======================================================================
# D. §8 거짓 음성 — **0건**, 그리고 🔴 룰북이 금지한 하나
# ======================================================================


@pytest.mark.real_card
def test_d01_no_legal_and_executable_action_is_missing(repository):
    """
    🔴 **§8 — 고를 수 있는 자리에서, 관문 셋을 통과하고 실행 구현이 있는
    행동은 후보에 있다.** 스물 자리 전수에서 **0건**이다.

    .. note::
       🔴 **측정이 두 번 틀렸고, 둘 다 "판정자를 덜 센 것" 이었다.**

       ① 처음에는 ``ActionValidator`` **하나**와 비교해 "4건" 이 나왔다.
          검증기는 ``GameStateView`` 만 읽으므로 세트한 턴 (``rule_uses``)
          도 체인도 볼 수 없고, 혼자서는 발동 가능성을 판정할 수 없다.
          관문 셋으로 다시 재면 그 넷은 관문 2·3 이 막은 것이다
          (``test_d02``).
       ② 그래도 **1건**이 남았다. 관문 셋 앞에 **네 번째 판정자**가 있다 —
          "이 자리가 지금 무엇이든 고를 수 있는가" (:func:`may_act`). 그
          하나는 상대 턴의 세트된 함정이고, 룰북 ``TURN PLAYER'S
          PRIORITY`` 가 **금지한다** (``test_d03`` 가 원문과 대조한다).

       그래서 이 시험은 ``may_act`` 가 참인 자리만 센다. 거짓인 자리는
       ``test_d03`` · ``test_i01`` 이 룰북 근거와 함께 따로 든다.
    """
    offenders = []
    for name, duel, seat in all_states(repository):
        for action in audit(duel, seat)["false_negative"]:
            offenders.append(
                (name, action.kind.name, action.source, str(action.effect_ref))
            )
    assert offenders == [], offenders


@pytest.mark.real_card
def test_d02_the_first_measurement_mistook_three_gates_for_one(repository):
    """
    🔴 **정정을 재어서 남긴다.** 검증기 하나로는 판정할 수 없다.

    세 자리에서 ``ActionValidator`` 는 ``VALID`` 인데 후보가 아니고, 막은
    것은 **다른 관문**이다.
    """
    cases = []

    # 세트한 턴의 함정 — 검증기는 VALID, 관문 2 가 막는다
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    trap = hands[P0][0]
    set_down(duel, trap)
    cases.append((duel, activation(P0, trap, GIFT), "2 ActivationTimingChecker"))

    # 카드 조건이 거짓 — 검증기는 VALID, 관문 3 이 막는다
    duel, hands, _ = board(repository, my_hand=(POT,), my_deck=1)
    cases.append((duel, activation(P0, hands[P0][0], POT), "3 can_activate"))

    # 상대 패가 모자란 입문서 — 같은 결
    duel, hands, _ = board(repository, my_hand=(PRIMER,), their_hand_fodder=2)
    primer = hands[P0][0]
    set_down(duel, primer)
    next_turn(duel, P1)
    next_turn(duel, P0)
    cases.append((duel, activation(P0, primer, PRIMER), "3 can_activate"))

    for duel, action, expected in cases:
        validator = ActionValidator(duel.view(P0), definitions=DEFS)
        #: 🔴 관문 1 **하나만** 보면 통과한다.
        assert validator.validate(action).validity is ActionValidity.VALID
        #: 그런데 셋을 보면 막힌다 — 그래서 후보가 아닌 것이 **옳다**.
        gate, _ = gate_of(duel, action, validator)
        assert gate == expected, (gate, expected)
        assert action not in duel.legal_actions(P0).allowed


@pytest.mark.real_card
def test_d03_the_rulebook_forbids_the_off_turn_activation(repository):
    """
    🔴 **유일하게 남은 후보는 룰북이 금지한다** — 거짓 음성이 아니다.

    "상대 턴 · 창 닫힘" 에서 세트된 일반 함정은 관문 셋을 **전부 통과**하고
    실행 구현도 있다. 그런데 후보가 아니다. 룰북이 그 이유를 적는다.

        *"As long as the turn player has Priority, the opponent cannot
        activate cards or effects, except for effects that activate
        automatically, like Trigger or Flip effects."*

    ``engine`` 은 ``rules`` 를 import 하지 않으므로 (ADR-007) **이 시험이
    룰북 원문과 대조한다** — 스펠 스피드 표와 같은 약속이다.

    Phase 6-Q 의 ``test_f04`` 가 이 사실을 이미 못 박았고, 그 판단이
    **옳았다.** 6-S 는 그것을 되돌리지 않는다.
    """
    document = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    priority = [
        section
        for section in document["sections"]
        if (section.get("title") or "").upper().startswith("TURN PLAYER")
    ]
    assert len(priority) == 1, [s.get("title") for s in priority]
    text = priority[0]["text"]
    assert "the opponent cannot activate cards" in text, text[:200]
    assert "Pass Priority to the opponent" in text, text[:200]

    #: 그리고 엔진이 **그 규칙대로** 행동한다.
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    trap = hands[P0][0]
    set_down(duel, trap)
    next_turn(duel, P1)
    assert not duel.priority.is_open
    assert duel.turn_player == P1

    action = activation(P0, trap, GIFT)
    validator = ActionValidator(duel.view(P0), definitions=DEFS)
    #: 관문 셋이 전부 통과하고 실행 구현도 있다.
    assert gate_of(duel, action, validator)[0] == "통과"
    assert execution_ready(action)[0] is True
    #: 🔴 그래도 후보가 아니다 — 막는 것은 **우선권**이다.
    assert action not in duel.legal_actions(P0).allowed
    assert duel.legal_actions(P0).allowed == ()
    #: 그리고 그 이유가 ``withheld`` 에 적혀 있다.
    reasons = [w.reason for w in duel.legal_actions(P0).withheld]
    assert any("우선권" in reason for reason in reasons), reasons


@pytest.mark.real_card
def test_d05_the_fourth_decider_matches_legal_actions(repository):
    """
    🔴 **네 번째 판정자를 ``legal_actions`` 의 실제 동작과 대조한다.**

    :func:`may_act` 가 거짓인 자리는 ``allowed`` 가 **비어 있고**, 참인
    자리는 적어도 하나를 받는다 — 흐름 하나라도. 스물 자리 전수.

    이것이 §18-4 의 책임 구분이다. 관문 셋은 "이 발동이 적법한가" 에
    답하고, 네 번째는 그 **앞**의 질문에 답한다.
    """
    checked = {"고를 수 있다": 0, "고를 수 없다": 0}
    for name, duel, seat in all_states(repository):
        legal = duel.legal_actions(seat)
        if may_act(duel, seat):
            assert legal.allowed, (name, legal.withheld)
            checked["고를 수 있다"] += 1
        else:
            assert legal.allowed == (), (name, legal.allowed)
            #: 🔴 그리고 **이유가 적혀 있다** — 6-S 가 고친 자리다.
            assert legal.withheld, name
            checked["고를 수 없다"] += 1
    assert checked["고를 수 있다"] > 10, checked
    assert checked["고를 수 없다"] >= 4, checked


@pytest.mark.real_card
def test_d04_a_spell_speed_one_activation_is_refused_off_turn(repository):
    """
    **반대쪽도 재어 둔다** — 상대 턴에 새면 안 되는 것들.

    통상 마법 (패 · 세트) 과 기동 효과는 관문 **1** 이 ``NOT_TURN_PLAYER``
    로 막는다. 그래서 우선권 모델이 넓어지는 날에도 이것들은 새지 않는다.
    """
    cases = []
    duel, hands, _ = board(repository, my_hand=(POT,))
    cases.append(("패의 통상 마법", duel, hands[P0][0], POT))
    duel, hands, _ = board(repository, my_hand=(POT,))
    set_down(duel, hands[P0][0])
    cases.append(("세트된 통상 마법", duel, hands[P0][0], POT))
    duel, _, placed = board(repository, my_mzone=(HONEST,))
    cases.append(("MZONE 의 기동 효과", duel, placed[P0][0], HONEST))

    for label, duel, source, card_id in cases:
        next_turn(duel, P1)
        action = activation(P0, source, card_id)
        validator = ActionValidator(duel.view(P0), definitions=DEFS)
        gate, verdict = gate_of(duel, action, validator)
        assert gate == "1 ActionValidator", (label, gate)
        assert verdict.code is ValidationCode.NOT_TURN_PLAYER, (label, verdict)
        assert verdict.validity is ActionValidity.INVALID, label


# ======================================================================
# E. §10 ``legal_actions`` 의 안전성 — 열 가지
# ======================================================================


@pytest.mark.real_card
def test_e01_candidates_reference_only_cards_on_the_board(repository):
    """§10-1 · §10-2 — 실제 인스턴스를 가리킨다."""
    for name, duel, seat in all_states(repository):
        for action in duel.legal_actions(seat).allowed:
            if action.source is None:
                assert action.kind in FLOW_KINDS, (name, action.kind)
                continue
            instance = duel.state.find_instance(action.source)
            assert instance is not None, (name, action)
            #: §10-5 올바른 플레이어의 행동만 만든다.
            assert action.actor == seat, (name, action)


@pytest.mark.real_card
def test_e02_an_activation_candidate_carries_the_right_effect_ref(repository):
    """§10-3 — 그 카드의 **그 효과**를 가리킨다."""
    seen = 0
    for name, duel, seat in all_states(repository):
        for action in duel.legal_actions(seat).allowed:
            if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
                continue
            seen += 1
            instance = duel.state.find_instance(action.source)
            assert action.effect_ref is not None, name
            assert action.effect_ref.card_id == instance.card_id, (name, action)
            assert action.effect_ref in activatable_effects(instance.card_id)
    assert seen > 5, seen


@pytest.mark.real_card
def test_e03_a_targeting_candidate_carries_a_complete_selection(repository):
    """§10-4 — 선택 정보가 보존된다. 모자라면 후보가 아니다."""
    seen = 0
    for name, duel, seat in all_states(repository):
        for action in duel.legal_actions(seat).allowed:
            if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
                continue
            definition = DEFS.definition_for(action.effect_ref)
            #: 🔴 예외가 나면 선택이 불완전하다는 뜻이다.
            selections_for(definition, action)
            for target in action.targets:
                assert duel.state.find_instance(target.instance_id) is not None
            seen += 1
    assert seen > 5, seen


@pytest.mark.real_card
def test_e04_generating_candidates_never_changes_the_board(repository):
    """§10-9 — 후보를 몇 번 만들어도 판이 바뀌지 않는다. 뽑지도 않는다."""
    for name, duel, seat in all_states(repository):
        assert audit(duel, seat)["mutated"] is False, name


@pytest.mark.real_card
def test_e05_no_candidate_is_produced_twice(repository):
    """§10-10 — 같은 후보가 두 번 나오지 않는다."""
    for name, duel, seat in all_states(repository):
        assert audit(duel, seat)["duplicates"] == 0, name


@pytest.mark.real_card
def test_e06_candidate_generation_executes_nothing(repository):
    """
    §10 마지막 줄 — **후보 생성은 실행하지 않는다.**

    기록이 그 증거다. 후보를 스무 번 만들어도 ``EventJournal`` 이 자라지
    않는다.
    """
    journal = EventJournal()
    duel, hands, _ = board(
        repository, my_hand=(LUSTER, POT, GIFT), journal=journal
    )
    before = len(list(journal))
    for _ in range(20):
        duel.legal_actions(P0)
        duel.legal_actions(P1)
    assert len(list(journal)) == before


@pytest.mark.real_card
def test_e07_the_hidden_hand_of_the_opponent_never_becomes_a_candidate(
    repository,
):
    """§10-8 — 비공개 정보로 후보를 만들지 않는다."""
    duel, hands, _ = board(
        repository, my_hand=(POT,), their_hand=(POT, GIFT), their_hand_fodder=3
    )
    mine = duel.legal_actions(P0)
    their_cards = {
        card.instance_id for card in duel.state.player(P1).zone(Zone.HAND)
    }
    for action in mine.allowed:
        assert action.source not in their_cards, action
        for target in action.targets:
            assert target.instance_id not in their_cards, action


@pytest.mark.real_card
def test_e08_a_closed_duel_offers_nothing(repository):
    """끝난 듀얼은 후보도 보류도 내지 않는다 — 침묵이 **옳은** 유일한 자리."""
    duel, _, _ = board(repository, my_hand=(POT,))
    duel.state.set_result(winner=P1, reason="시험")
    legal = duel.legal_actions(P0)
    assert legal.allowed == ()
    assert legal.withheld == ()
    assert duel.is_over


# ======================================================================
# F. 🔴 이 Phase 가 고친 자리 — 침묵과 거짓 문장
# ======================================================================


def flow_positions(repository):
    """
    창 × 쥔 쪽의 **네 자리**를 실제 엔진으로 만든다.

    ``(이름, duel, seat, 창이 열렸는가, 이 자리가 쥐었는가)``
    """
    out = []
    duel, _, _ = board(repository, my_hand=(POT,))
    out.append(("① 창 닫힘 · 턴 플레이어", duel, P0, False, False))
    out.append(("② 창 닫힘 · 비턴 플레이어", duel, P1, False, False))

    #: 🔴 자리마다 판을 **새로** 만든다 — ``Duel`` 은 가변이다.
    out.append(("③ 창 열림 · 쥔 쪽 (비턴)", chain_board(repository, depth=1)[0], P1, True, True))
    out.append(("④ 창 열림 · 안 쥔 쪽 (턴)", chain_board(repository, depth=1)[0], P0, True, False))
    out.append(("⑤ 창 열림 · 쥔 쪽 (턴)", chain_board(repository, depth=2)[0], P0, True, True))
    out.append(("⑥ 창 열림 · 안 쥔 쪽 (비턴)", chain_board(repository, depth=2)[0], P1, True, False))
    return out


@pytest.mark.real_card
def test_f01_nobody_is_left_in_silence(repository):
    """
    🔴 **고친 것 ② — 침묵이 사라졌다.**

    예전에는 ④ (창이 열려 있고 상대가 쥐었는데 이쪽이 턴 플레이어) 에서
    ``allowed`` 도 ``withheld`` 도 비어 있었다. 읽는 쪽은 "할 것이 없다" 와
    "상대를 기다린다" 와 "듀얼이 끝났다" 를 **가를 수 없었다.**
    """
    for name, duel, seat, _, _ in flow_positions(repository):
        legal = duel.legal_actions(seat)
        assert legal.allowed or legal.withheld, name


@pytest.mark.real_card
def test_f02_the_withheld_reason_is_true_in_every_position(repository):
    """
    🔴 **고친 것 ① — 거짓 문장이 사라졌다.**

    예전에는 창이 **열려 있는데도** "우선권이 열려 있지 않습니다" 라고
    적었다 (⑥). 지금은 두 이유가 갈라져 있고 둘 다 사실이다.
    """
    seen = {"열려 있지 않습니다": 0, "지금은": 0}
    for name, duel, seat, is_open, holds in flow_positions(repository):
        legal = duel.legal_actions(seat)
        passes = [
            w for w in legal.withheld if w.kind is PlayerActionKind.PASS
        ]
        if holds:
            assert passes == [], name
            assert any(
                a.kind is PlayerActionKind.PASS for a in legal.allowed
            ), name
            continue
        if not is_open and seat == duel.turn_player:
            continue  # 턴 플레이어는 창이 닫혀 있어도 보류를 받지 않는다
        assert len(passes) == 1, (name, legal.withheld)
        held = passes[0]
        if is_open:
            #: 🔴 "열려 있지 않다" 고 적지 **않는다** — 열려 있다.
            assert "열려 있지 않습니다" not in held.reason, name
            assert "지금은" in held.reason, (name, held.reason)
            assert f"P{duel.priority.holder.seat}" in held.reason, name
            #: 빠진 규칙이 **아니다** — 순서다.
            assert held.missing is None, (name, held.missing)
            seen["지금은"] += 1
        else:
            assert "우선권이 열려 있지 않습니다." == held.reason, name
            assert held.missing is not None, name
            seen["열려 있지 않습니다"] += 1
    assert seen["지금은"] == 2, seen
    assert seen["열려 있지 않습니다"] == 1, seen


@pytest.mark.real_card
def test_f03_the_candidate_list_did_not_change(repository):
    """
    🔴 **이 수정은 ``allowed`` 를 한 건도 바꾸지 않았다.**

    고친 것은 ``withheld`` 가 사실을 말하게 된 것뿐이다 — 새 후보를 열지도
    닫지도 않았다. 네 자리의 ``allowed`` 를 수로 못 박는다.
    """
    expected = {
        "① 창 닫힘 · 턴 플레이어": {"SET_SPELL_TRAP", "ACTIVATE_EFFECT", "END_PHASE"},
        "② 창 닫힘 · 비턴 플레이어": set(),
        "③ 창 열림 · 쥔 쪽 (비턴)": {"ACTIVATE_EFFECT", "PASS"},
        "④ 창 열림 · 안 쥔 쪽 (턴)": set(),
        "⑤ 창 열림 · 쥔 쪽 (턴)": {"PASS"},
        "⑥ 창 열림 · 안 쥔 쪽 (비턴)": set(),
    }
    for name, duel, seat, _, _ in flow_positions(repository):
        kinds = {a.kind.name for a in duel.legal_actions(seat).allowed}
        assert kinds == expected[name], (name, kinds)


@pytest.mark.real_card
def test_f04_the_flow_layer_answers_pass_and_end_phase_not_the_validator(
    repository,
):
    """
    **왜 흐름 둘을 검증기와 비교하지 않는가** — 검증기가 답하지 않는다.

    ``ActionValidator`` 는 ``GameStateView`` 만 읽고, 우선권과 진행은 판
    **밖**에 산다 (ADR-007). 그래서 그 둘에는 ``UNKNOWN`` 이 온다. 그것이
    거짓 양성이 아니라 **책임 구분**이다.
    """
    duel, _, _ = board(repository, my_hand=(POT,))
    validator = ActionValidator(duel.view(P0), definitions=DEFS)
    for build in (PlayerAction.passing, PlayerAction.end_phase):
        verdict = validator.validate(build(actor=P0))
        assert verdict.validity is ActionValidity.UNKNOWN, build
        assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: 그런데 ``END_PHASE`` 는 후보로 나온다 — 흐름 계층이 허가했다.
    assert PlayerActionKind.END_PHASE in {
        a.kind for a in duel.legal_actions(P0).allowed
    }
    #: 그 허가의 출처가 ``_flow_actions`` 이다.
    tree = method_tree(Duel._flow_actions)
    names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "TurnProgressor" in names
    assert "ActionValidator" not in names


# ======================================================================
# G. §11 수직 실행 경로 — 후보에서 상태 변경까지
# ======================================================================


@pytest.mark.real_card
def test_g01_a_candidate_goes_all_the_way_to_a_state_change(repository):
    """
    🔴 **§11 · §19 수준 3 — 여섯 단계를 한 자리에서 전부 센다.**

    ``DISCOVERED`` → ``VALIDATED`` → ``EXECUTION_READY`` → ``ACCEPTED``
    → ``RESOLVED`` → ``STATE_VERIFIED``. 새 enum 을 만들지 않고 기존
    자리로 센다 (§5).
    """
    journal = EventJournal()
    duel, hands, _ = board(repository, my_hand=(POT,), journal=journal)
    deck_before = len(duel.state.player(P0).zone(Zone.DECK))

    # ① DISCOVERED — 생산 후보 목록에서 가져온다 (손으로 만들지 않는다)
    legal = duel.legal_actions(P0)
    picks = [
        a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(picks) == 1, [a.kind.name for a in legal.allowed]
    action = picks[0]

    # ② VALIDATED — 관문 셋
    validator = ActionValidator(duel.view(P0), definitions=DEFS)
    assert gate_of(duel, action, validator)[0] == "통과"

    # ③ EXECUTION_READY
    assert execution_ready(action)[0] is True

    # ④ ACCEPTED — 체인 등록. **아직 해결이 아니다**
    step = duel.apply(action)
    assert (step.accepted, step.code) == (True, ValidationCode.OK)
    assert len(duel.chain.links) == 1
    assert duel.chain.resolved_count == 0
    assert [e for e in journal if e.kind.name == "EFFECT"] == []
    assert len(duel.state.player(P0).zone(Zone.DECK)) == deck_before

    # ⑤ RESOLVED — 양쪽 패스
    last = None
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        passing = [
            a
            for a in duel.legal_actions().allowed
            if a.kind is PlayerActionKind.PASS
        ]
        assert passing, duel.legal_actions().allowed
        last = duel.apply(passing[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert "해결했습니다" in last.reason
    assert duel.chain.is_empty  # Phase 6-R

    # ⑥ STATE_VERIFIED — 판과 기록이 둘 다 말한다
    assert len(duel.state.player(P0).zone(Zone.DECK)) == deck_before - 2
    assert len(duel.state.player(P0).zone(Zone.HAND)) == 2
    effects = [e for e in journal if e.kind.name == "EFFECT"]
    assert [str(e.effect_ref) for e in effects] == [f"{POT}:e[0]"]
    assert effects[0].applied and effects[0].deltas


@pytest.mark.real_card
def test_g02_apply_refuses_anything_not_in_the_candidate_list(repository):
    """
    **§11 — 거절되면 잘못된 상태 변경이 없다.**

    ``apply`` 의 첫 관문이 ``action not in legal.allowed`` 다. 관문 2·3 이
    막은 발동을 직접 넣어도 판이 움직이지 않는다.
    """
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    trap = hands[P0][0]
    set_down(duel, trap)
    before = (duel.state.state_hash(), len(duel.chain.links))

    step = duel.apply(activation(P0, trap, GIFT))  # 세트한 턴이다

    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "허가된 행위가 아닙니다" in step.reason
    assert (duel.state.state_hash(), len(duel.chain.links)) == before


@pytest.mark.real_card
def test_g03_every_candidate_in_every_state_is_accepted_by_apply(repository):
    """
    🔴 **§8 의 가장 강한 검사 — 후보 전부를 사본에서 실제로 적용한다.**

    스물 자리의 후보를 하나씩 ``clone`` 한 판에서 ``apply`` 한다. 하나라도
    거절되면 후보 목록이 거짓말을 한 것이다.
    """
    tried = 0
    refused = []
    for name, duel, seat in all_states(repository):
        for action in duel.legal_actions(seat).allowed:
            fork = Duel(
                state=duel.state.clone(),
                priority=duel.priority,
                step=duel.step,
                first_player=duel.first_player,
                chain=duel.chain,
                pending_spells=duel.pending_spells,
                **duel_components(journal=False),
            )
            step = fork.apply(action)
            tried += 1
            if not step.accepted:
                refused.append((name, action.kind.name, step.code.name, step.reason))
    assert tried > 30, tried
    assert refused == [], refused


# ======================================================================
# H. §13 기존 실제 효과 실행 회귀
# ======================================================================


def resolve(duel, action):
    """후보 하나를 끝까지 — 발동, 패스, 해결. 해결의 걸음을 돌려준다."""
    step = duel.apply(action)
    assert step.accepted, step.reason
    last = step
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        passing = [
            a
            for a in duel.legal_actions().allowed
            if a.kind is PlayerActionKind.PASS
        ]
        if not passing:
            break
        last = duel.apply(passing[0])
    return last


def offered(duel, seat, card_id):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref.card_id == card_id
    ]


@pytest.mark.real_card
def test_h01_the_honest_effect_still_runs(repository):
    """§13-A — 어니스트 (6-L)."""
    journal = EventJournal()
    duel, _, placed = board(repository, my_mzone=(HONEST,), journal=journal)
    picks = offered(duel, P0, HONEST)
    assert len(picks) == 1
    last = resolve(duel, picks[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert [c.card_id for c in duel.state.player(P0).zone(Zone.HAND)] == [HONEST]
    assert [c for c in duel.state.player(P0).zone(Zone.MZONE) if c] == []
    assert [str(e.effect_ref) for e in journal if e.kind.name == "EFFECT"] == [
        f"{HONEST}:e[0]"
    ]


@pytest.mark.real_card
def test_h02_the_phase_6o_return_to_hand_still_runs(repository):
    """§13-B — 강제 탈출 장치의 ``MZONE → HAND`` (6-O)."""
    journal = EventJournal()
    duel, hands, placed = board(
        repository, my_hand=(FORCEOUT,), their_mzone=(LUSTER,), journal=journal
    )
    set_down(duel, hands[P0][0])
    next_turn(duel, P1)
    next_turn(duel, P0)
    picks = offered(duel, P0, FORCEOUT)
    assert len(picks) == 1, picks
    victim = placed[P1][0]
    assert [t.instance_id for t in picks[0].targets] == [victim]
    their_hand = len(duel.state.player(P1).zone(Zone.HAND))
    last = resolve(duel, picks[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert len(duel.state.player(P1).zone(Zone.HAND)) == their_hand + 1
    assert [c for c in duel.state.player(P1).zone(Zone.MZONE) if c] == []


@pytest.mark.real_card
def test_h03_the_phase_6p_multi_target_still_runs(repository):
    """§13-C — 벌금의 패 2장 (6-P). 조합 셋이 **각각 다른 후보**다."""
    journal = EventJournal()
    duel, hands, _ = board(
        repository, my_hand=(FINE,), my_hand_fodder=3, journal=journal
    )
    set_down(duel, hands[P0][0])
    next_turn(duel, P1)
    next_turn(duel, P0)
    picks = offered(duel, P0, FINE)
    assert len(picks) == 3, picks
    assert {len(p.targets) for p in picks} == {2}
    assert len({tuple(t.instance_id for t in p.targets) for p in picks}) == 3
    hand_before = len(duel.state.player(P0).zone(Zone.HAND))
    last = resolve(duel, picks[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert len(duel.state.player(P0).zone(Zone.HAND)) == hand_before - 2


@pytest.mark.real_card
def test_h04_the_phase_6q_trap_still_runs(repository):
    """§13-D — 세트된 일반 함정의 후보 · 발동 · 해결 (6-Q)."""
    journal = EventJournal()
    duel, hands, _ = board(repository, my_hand=(GIFT,), journal=journal)
    trap = hands[P0][0]
    set_down(duel, trap)
    assert offered(duel, P0, GIFT) == [], "세트한 턴에는 후보가 아니다"
    next_turn(duel, P1)
    next_turn(duel, P0)
    picks = offered(duel, P0, GIFT)
    assert len(picks) == 1
    their_hand = len(duel.state.player(P1).zone(Zone.HAND))
    last = resolve(duel, picks[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    assert len(duel.state.player(P1).zone(Zone.HAND)) == their_hand + 2


@pytest.mark.real_card
def test_h05_the_phase_6q_chain_two_response_still_runs(repository):
    """§13-D — 상대 턴 체인 2 와 역순 해결 (6-Q · 6-R)."""
    journal = EventJournal()
    duel, hands, _ = board(
        repository,
        my_deck=5,
        my_hand=(POT,),
        their_hand=(GIFT,),
        turn_player=P1,
        journal=journal,
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    first = duel.apply(activation(P0, pot, POT))
    assert (first.accepted, first.code) == (True, ValidationCode.OK)

    #: 🔴 체인 2 는 **상대의 후보 목록에서** 가져온다.
    picks = offered(duel, P1, GIFT)
    assert len(picks) == 1, duel.legal_actions(P1).allowed
    second = duel.apply(picks[0])
    assert (second.accepted, second.code) == (True, ValidationCode.OK)
    assert len(duel.chain.links) == 2

    last = None
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        passing = [
            a
            for a in duel.legal_actions().allowed
            if a.kind is PlayerActionKind.PASS
        ]
        assert passing, duel.legal_actions().allowed
        last = duel.apply(passing[0])
    assert (last.accepted, last.code) == (True, ValidationCode.OK)
    #: 역순 — 체인 2 가 먼저다.
    assert [str(e.effect_ref) for e in journal if e.kind.name == "EFFECT"] == [
        f"{GIFT}:e[0]",
        f"{POT}:e[0]",
    ]
    #: Phase 6-R — 체인이 비워진다.
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_h06_the_phase_6r_chain_teardown_still_holds(repository):
    """§13-E — 불발된 체인도 비워지고 패스가 수락된다 (6-R)."""
    duel, hands, _ = board(
        repository, my_deck=3, my_hand=(POT,), their_hand=(GIFT,), turn_player=P1
    )
    pot, gift = hands[P0][0], hands[P1][0]
    set_down(duel, gift, seat=P1)
    next_turn(duel, P0)
    duel.apply(activation(P0, pot, POT))
    duel.apply(offered(duel, P1, GIFT)[0])

    last = None
    guard = 0
    while duel.priority.is_open and guard < 8:
        guard += 1
        passing = [
            a
            for a in duel.legal_actions().allowed
            if a.kind is PlayerActionKind.PASS
        ]
        assert passing
        last = duel.apply(passing[0])

    assert last.accepted is True
    assert last.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert "해결하지 못했습니다" in last.reason
    assert duel.chain.is_empty


@pytest.mark.real_card
def test_h07_the_runner_still_drives_duels_without_refusals(repository):
    """§13-E · §18-14 — ``DuelRunner`` 가 후보 목록으로 듀얼을 끝까지 돈다."""
    from agent.runner import DuelRunner
    from agent.search import search_policy

    deck = [LUSTER] * 12 + [POT] * 4 + [GIFT] * 4
    total = refused = 0
    for seed in (501, 502, 503):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        runner = DuelRunner(
            duel=duel, policies=(search_policy(duel), search_policy(duel))
        )
        transcript = runner.run()
        total += len(transcript.entries)
        refused += sum(1 for e in transcript.entries if not e.accepted)
    assert total > 0
    assert refused == 0


# ======================================================================
# I. §16 · §18-17 — 남은 BLOCKER 를 **재어서 남긴다**
# ======================================================================


@pytest.mark.real_card
def test_i01_the_engine_only_opens_half_of_the_priority_rule(repository):
    """
    🔴 **BLOCKER — 룰북의 우선권 이양이 절반만 구현되어 있다.**

    룰북 ``TURN PLAYER'S PRIORITY`` 의 마지막 줄이 둘을 적는다.

        *"After a card's activation, **and at the end of each phase or
        step**, Priority passes to the opponent."*

    엔진은 **앞쪽만** 한다 — 발동 뒤에 ``ResponseWindow`` 가 열린다.
    페이즈 · 스텝의 끝에서 우선권이 넘어가는 자리가 **없다.**

    그래서 상대 턴에 세트된 함정은 "상대가 무언가 발동해 주지 않으면"
    닿지 않는다. 6-Q 가 연 길의 절반이 실제 듀얼 루프에서 막혀 있다.

    🔴 **6-S 는 이것을 고치지 않는다** — 우선권 모델 확장이고 §16 이 범위
    밖으로 두었다. **재어서 남긴다.**
    """
    document = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    text = next(
        section["text"]
        for section in document["sections"]
        if (section.get("title") or "").upper().startswith("TURN PLAYER")
    )
    assert "at the end of each phase or step" in text, text[:200]

    #: ① 발동 뒤에는 창이 열린다 — 구현된 절반.
    duel, hands, _ = board(repository, my_hand=(POT,))
    duel.apply(activation(P0, hands[P0][0], POT))
    assert duel.priority.is_open

    #: ② 🔴 페이즈를 넘길 때는 열리지 않는다 — 빠진 절반.
    duel, hands, _ = board(repository, my_hand=(GIFT,))
    trap = hands[P0][0]
    set_down(duel, trap)
    next_turn(duel, P1)
    #: 상대가 페이즈를 끝내도 이쪽에 창이 오지 않는다.
    ending = [
        a
        for a in duel.legal_actions(P1).allowed
        if a.kind is PlayerActionKind.END_PHASE
    ]
    assert ending, duel.legal_actions(P1).allowed
    step = duel.apply(ending[0])
    assert step.accepted, step.reason
    assert duel.priority.is_open is False, "창이 열렸다면 이 BLOCKER 는 풀렸다"
    assert offered(duel, P0, GIFT) == [], "후보가 생겼다면 이 BLOCKER 는 풀렸다"


@pytest.mark.real_card
def test_i02_a_gate_blocked_activation_leaves_no_withheld_reason(repository):
    """
    🔴 **BLOCKER (Phase 6-R 이 기록, 6-S 가 수를 센다) — 조용한 보류.**

    ``_activation_actions`` 가 관문에서 걸린 후보를 **이유 없이 버린다.**
    그래서 "발동할 것이 없다" 와 "발동이 지금 규칙상 안 된다" 를 읽는 쪽이
    가를 수 없다.

    스물 자리 중 **고를 수 있는 자리**에서 관문이 막은 발동이 **아홉 건**
    이고 (관문 1 이 다섯 · 관문 2 가 하나 · 관문 3 이 셋), 그 중
    ``withheld`` 에 ``ACTIVATE_EFFECT`` 로 남은 것은 **0건**이다.

    🔴 고를 수 **없는** 자리에서 네 번째 판정자가 막은 발동은 따로 센다 —
    그쪽은 룰북이 금지하는 것이고 (§82), 이유가 ``withheld`` 의 ``PASS``
    항목에 적혀 있다 (6-S 가 고친 자리).

    🔴 고치지 않는다 — ``withheld`` 에 후보마다 항목을 넣는 일은
    ``legal_actions`` 의 공유 계약을 늘린다 (목록 크기가 바뀐다). §16 이
    직접 차단이 아닌 한 수정하지 않는다고 적었고, 이번 결함은 그것 없이도
    전부 측정할 수 있었다.
    """
    blocked = collections.Counter()
    reported = 0
    for name, duel, seat in all_states(repository):
        result = audit(duel, seat)
        blocked.update(result["blocked"])
        reported += sum(
            1
            for w in result["legal"].withheld
            if w.kind is PlayerActionKind.ACTIVATE_EFFECT
        )
    gate_blocked = sum(
        n for gate, n in blocked.items() if gate.startswith(("1 ", "2 ", "3 "))
    )
    assert gate_blocked == 9, dict(blocked)
    #: 🔴 그리고 네 번째 판정자가 막은 것은 **따로** 센다 (룰북 §82).
    assert blocked["0 우선권 (룰북 TURN PLAYER'S PRIORITY)"] > 0, dict(blocked)
    assert reported == 0, "이유가 적히기 시작했다면 이 BLOCKER 는 풀렸다"
    #: 그리고 세 관문이 **전부** 쓰인다 — 한 관문만 막는 것이 아니다.
    assert blocked["1 ActionValidator"] == 5, dict(blocked)
    assert blocked["2 ActivationTimingChecker"] == 1, dict(blocked)
    assert blocked["3 can_activate"] == 3, dict(blocked)


@pytest.mark.real_card
def test_i03_the_withheld_sites_are_now_four(repository):
    """
    **보류 자리가 셋에서 넷이 되었다** — 그리고 넷째는 ``missing`` 이 없다.

    ``tests/test_duelstep_withheld_validation_audit.py::test_09`` 가 이
    경계의 계약이 느슨하다고 적었다 ("세 자리가 같은 칸에 다른 종류의 값을
    넣는다"). 6-S 의 넷째 자리는 그 칸을 **비운다** — 빠진 규칙이 아니라
    순서이므로 넣을 값이 없다. 없는 것을 빈 값으로 채우지 않는다.
    """
    source = production_source("engine/duel.py")
    assert source.count("WithheldAction(") == 4, source.count("WithheldAction(")
    tree = method_tree(Duel._flow_actions)
    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "WithheldAction"
    ]
    assert len(constructions) == 3, len(constructions)
    with_missing = [
        node
        for node in constructions
        if any(kw.arg == "missing" for kw in node.keywords)
    ]
    assert len(with_missing) == 2, len(with_missing)
