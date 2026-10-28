"""
Phase 6-AB 보완7 — **이미 확인된 효과 분류를 공통 발동 관문에 전달한다.**

보완6 이 남긴 자리 (BLOCKER-F6-1)
---------------------------------
빠른 효과 기회에서 통상 마법은 ``INVALID`` / ``SPELL_SPEED_TOO_LOW`` 로
막혔는데, **기동 효과는 ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED``** 로 막혔다.
실측 (보완7 §2, 검토 기준 HEAD ``b8a1648``)::

    어니스트 37742478:e[0]
    accepted=False  code=RULE_NOT_IMPLEMENTED
    reason="발동하려는 카드의 스펠 스피드를 판정할 수 없습니다 (몬스터 효과)."
    missing_rule="monster effect classification (기동 · 유발 · 플립 vs 유발즉시)"

차단은 성립했지만 **판정의 뜻이 틀렸다** — ``RULE_NOT_IMPLEMENTED`` 는
*"이 저장소에 그 규칙이 없다"* 이고, 그래서 규칙이 분명히 막은 발동이
**엔진 미지원**으로 집계되었다.

그리고 모른다고 답한 그 분류는 **이미 이 저장소에 있었다** — 어니스트 ①의
정의가 ``activation_kind=IGNITION`` 을 들고 있다 (손으로 적어 검증한 값,
ADR-006). 없던 것은 **그 값이 관문까지 가는 길**이다.

보완7 이 낸 길
--------------
``ActivationTiming`` 이 값 둘을 더 받는다 — ``point`` · ``set_this_turn`` ·
``simultaneous`` · ``stage`` 와 **같은 자리이고 같은 이유**다 (ADR-007).

==========================  ============================================
``activation_kind``          이번에 발동하려는 **효과 하나**의 분류
``responding_kind``          응수하려는 **링크의 효과**의 분류
==========================  ============================================

판정하는 자리는 :data:`~engine.activation_timing.KIND_SPEED` **한 벌**이고
그 표는 룰북의 ``effect_types[*].spell_speed`` 를 옮긴 것이다 (Ignition ·
Trigger · Flip → 1, Quick → 2). 찾는 자리도
:func:`~engine.effect.definition.verified_activation_kind` **한 벌**이다 —
``Duel._effect_kind`` 와 ``ResponseLoop._effect_kind`` 가 둘 다 그것을 부른다.

여기서 **하지 않은** 것
-----------------------
* 카드 단위로 ``QUICK_O`` 를 읽어 분류를 만드는 일. 모듈 설명이 그 방법이
  성립하지 않는다고 측정해 두었다 (856장이 1 계열과 2 계열을 **둘 다**
  가진다). 입력은 손으로 적어 검증한 정의뿐이다.
* 몬스터라는 이유로 1 이나 2 를 일괄 부여하는 일. 분류를 받지 못하면
  ``UNKNOWN`` 그대로다 (``B`` 절).
* 어니스트 카드 ID 전용 분기. 이 파일에 ``37742478`` 이 나오는 것은
  **측정 대상**으로서이고, 엔진에는 그 번호가 없다 (``F`` 절).
* 분류를 안다는 사실을 실행 지원으로 읽는 일. 조건 · 비용 · 대상 · 구현
  등록 · 출처 금지는 그대로 다 본다 (``B`` 절 ``b05``).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.activation_timing import (
    KIND_RULES,
    KIND_SPEED,
    MONSTER_CLASSIFICATION_MISSING,
    ActivationStage,
    SpellSpeed,
)
from engine.duel import Duel, duel_components
from engine.effect.definition import (
    EffectDefinitionRegistry,
    verified_activation_kind,
)
from engine.effect.library import EFFECT_LIBRARY
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import ActivationKind, Phase, Position, Zone
from tests.conftest import requires_official_db
from tests.engine.test_trap_activation_free_chain import (
    GIFT_OF_GREED,
    LUSTER_DRAGON,
    next_turn,
    set_down,
    staged,
)
from tests.engine.window_helpers import pass_fast_window

pytestmark = requires_official_db

P0, P1 = 0, 1

#: 실제 기동 효과 — 어니스트 ①. ``EFFECT_TYPE_IGNITION`` 이고 대상이 없다.
HONEST = 37742478
HONEST_REF = EffectRef(HONEST, 0)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ======================================================================
# 공용 도구
# ======================================================================
def _kinds(duel, seat=P0):
    return sorted({a.kind.value for a in duel.legal_actions(seat).allowed})


def _activations(duel, seat=P0, card_id=None):
    return [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and (card_id is None or a.effect_ref.card_id == card_id)
    ]


def _gate(duel, action, seat=P0):
    """후보를 만든 **그 관문**에 직접 묻는다."""
    offers = duel._trigger_offers(seat)
    return duel._activation_gate(
        action,
        validator=duel.activation_validator(seat, offers),
        selections=action.targets,
    )


def _fingerprint(duel):
    return (
        duel.state.state_hash(),
        duel.state.turn.phase,
        len(duel.chain),
        duel.chain.resolved_count,
        duel.window_floor,
        duel.chain_floor,
        duel.window_passed,
        frozenset(duel.consumed_events),
        duel.priority.window,
        duel.priority.holder.seat,
        duel.priority.consecutive_passes,
        len(duel.journal.events) if duel.journal is not None else 0,
    )


def _honest_board(repository, *, definitions=None, their_hand=0):
    """
    어니스트가 **앞면으로 내 몬스터 존에 있는** 판.

    🔴 초기 판 구성이다 — 실행 중에 상태를 주입하는 것이 아니다. 허가도
    분류도 주입하지 않고, 이 뒤의 모든 변화는 ``Duel.apply`` 가 만든다.
    등재된 기동 효과를 필드에 내놓는 소환 경로는 이 범위가 아니다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P0,
        seed=1,
    )
    card = state.create_instance(HONEST, owner=P0, zone=Zone.MZONE)
    state.move(card, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK)
    for _ in range(2):
        state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.HAND)
    for _ in range(their_hand):
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 5
    state.turn.turn_player = P0
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(definitions=definitions),
    )
    return duel, card.instance_id


def _into_fast_window(duel, seat=P0):
    """**실제 행위로** 빠른 효과 기회에 들어간다 — 몬스터 세트 하나."""
    sets = [
        a
        for a in duel.legal_actions(seat).allowed
        if a.kind is PlayerActionKind.SET_MONSTER
    ]
    assert sets, _kinds(duel, seat)
    step = duel.apply(sets[0])
    assert step.accepted, step.reason
    assert duel.chain.is_empty
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW
    return step


def _registry_with(definition):
    """``EFFECT_LIBRARY`` 의 정의들에서 하나만 **갈아 끼운** 등록부."""
    kept = tuple(
        entry.definition
        for entry in EFFECT_LIBRARY
        if entry.definition.effect_ref != definition.effect_ref
    )
    return EffectDefinitionRegistry(kept + (definition,))


HONEST_DEFINITION = next(
    entry.definition
    for entry in EFFECT_LIBRARY
    if entry.definition.effect_ref == HONEST_REF
)


# ======================================================================
# A. 룰북 대조 — 표를 지어내지 않았다
# ======================================================================
def test_a01_the_kind_speed_table_matches_the_official_rulebook():
    """
    🔴 :data:`KIND_SPEED` 가 **룰북의 수** 그대로다.

    ``engine`` 은 ``rules`` 를 import 하지 않으므로 (런타임이 데이터 파일에
    묶이지 않게) **이 시험이 둘을 대조한다** — ``RESPONSE_TABLE`` ·
    ``SPEED_RULES`` 와 같은 약속이다.
    """
    import json

    document = json.loads(
        (
            PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json"
        ).read_text(encoding="utf-8")
    )
    official = {
        entry["name"]: entry for entry in document["effect_types"]
    }
    names = {
        ActivationKind.IGNITION: "Ignition Effect",
        ActivationKind.TRIGGER: "Trigger Effect",
        ActivationKind.FLIP: "Flip Effect",
        ActivationKind.QUICK: "Quick Effect",
    }

    #: ① 네 분류 전부 표에 있다 — 빠뜨린 멤버가 없다.
    assert set(KIND_SPEED) == set(ActivationKind)
    assert set(KIND_RULES) == set(ActivationKind)

    for kind, name in names.items():
        entry = official[name]
        #: ② 수가 같다.
        assert KIND_SPEED[kind].value == entry["spell_speed"], (kind, name)
        #: ③ 근거 번호가 그 조항의 것이다.
        assert KIND_RULES[kind][0] == entry["rules"][0], (kind, name)
        #: ④ 그리고 그 분류는 **발동하는** 분류다 — 지속 효과를 넣지 않았다.
        assert entry["has_activation"] is True, name

    #: ⑤ 지속 효과(Continuous Effect)는 축에 **없다** — 발동하지 않는다.
    assert official["Continuous Effect"]["has_activation"] is False
    assert "CONTINUOUS" not in {k.value for k in ActivationKind}


def test_a02_the_real_ignition_effect_carries_a_verified_kind(repository):
    """
    🔴 분류의 **출처**다 — 손으로 적어 검증한 정의 하나.

    자동으로 승격한 값이 아니다 (ADR-006). 이 시험은 그 사실을 센다 —
    정의가 ``IGNITION`` 을 들고 있고 출처가 검증된 손 기록이다.
    """
    assert HONEST_DEFINITION.activation_kind is ActivationKind.IGNITION
    assert HONEST_DEFINITION.source_card_id == HONEST
    assert HONEST_DEFINITION.effect_ref.card_id == HONEST
    assert HONEST_DEFINITION.provenance.verified is True
    assert HONEST_DEFINITION.provenance.is_forbidden is False


# ======================================================================
# B. UNKNOWN 경계 — 모르는 것은 그대로 모른다
# ======================================================================
def test_b01_a_missing_definition_stays_unknown(repository):
    """정의가 **없는** 효과는 분류도 없다 — 등록부에 없으면 ``None``."""
    duel, honest = _honest_board(repository)
    absent = EffectRef(LUSTER_DRAGON, 0)
    assert duel._activator.definitions.definition_for(absent) is None
    assert duel._effect_kind(absent, honest) is None


def test_b02_a_definition_without_a_kind_stays_unknown(repository):
    """
    🔴 정의는 있는데 ``activation_kind`` 가 **적히지 않은** 효과.

    그러면 **두 계층이 모두 모른다고** 답하고 둘 다 허가가 아니다 — 실측:

    ==============================  =========================================
    ``ActionValidator``              ``UNKNOWN`` ·
                                     ``monster-activation-timing (기동 · 유발
                                     · 플립 · 유발즉시 분류가 없다)``
    ``ActivationTimingChecker``      ``UNKNOWN`` ·
                                     ``monster effect classification``
    ==============================  =========================================

    🔴 **보완7 이 "모름" 의 범위를 줄이지 않았다.** 바꾼 것은 *아는 것을
    전달하는 길*뿐이고, 적히지 않은 효과는 전과 똑같이 모름이다. 그리고
    규칙 쪽 관문이 **더 앞에서** 막으므로 후보도 되지 않는다.

    🔴 **합성 검증이다** — 실제 어니스트 정의에서 분류 칸만 비운 등록부를
    쓴다. 실제 카드 지원을 주장하지 않는다.
    """
    from engine.action_validation import MONSTER_ACTIVATION_MISSING
    from engine.activation_timing import (
        ActivationTiming,
        ActivationTimingChecker,
    )

    blank = dataclasses.replace(HONEST_DEFINITION, activation_kind=None)
    duel, honest = _honest_board(
        repository, definitions=_registry_with(blank)
    )
    action = PlayerAction.activate_effect(
        actor=P0, source=honest, effect_ref=HONEST_REF
    )

    #: ① 분류를 찾는 길이 ``None`` 을 돌려준다.
    assert duel._effect_kind(HONEST_REF, honest) is None

    #: ② 열린 상태에서도 **후보가 아니다** — 규칙 쪽 관문이 앞에서 막는다.
    assert _activations(duel, P0, HONEST) == []
    verdict = _gate(duel, action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING

    #: ③ 그리고 **모름은 허가가 아니다** — 직접 넣어도 거절이고 불변이다.
    before = _fingerprint(duel)
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert _fingerprint(duel) == before

    #: ④ 타이밍 계층만 따로 물어도 **모름**이다 — 분류를 받지 못했으므로.
    _into_fast_window(duel)
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(
            duel.chain,
            duel.priority,
            stage=duel._activation_stage(),
            activation_kind=None,
        ),
        action,
    )
    assert timed.validity is ActionValidity.UNKNOWN
    assert timed.missing_rule == MONSTER_CLASSIFICATION_MISSING


def test_b03_a_mismatched_source_never_borrows_another_cards_kind(repository):
    """
    🔴 ``source`` 와 ``EffectRef`` 가 어긋나면 **분류를 주지 않는다.**

    검증기가 그 요청을 ``EFFECT_REF_CARD_MISMATCH`` 로 따로 거절하지만,
    분류를 찾는 함수는 **그 거절을 기다리지 않는다** — 순서가 바뀌어도 남의
    분류가 새어 들어오지 않게.
    """
    duel, honest = _honest_board(repository)
    other = [
        c for c in duel.state.player(P0).hand if c and c.card_id == LUSTER_DRAGON
    ][0]

    #: ① 다른 카드의 개체로 어니스트의 효과를 물으면 ``None`` 이다.
    assert duel._effect_kind(HONEST_REF, other.instance_id) is None
    assert (
        verified_activation_kind(
            duel._activator.definitions,
            HONEST_REF,
            source_card_id=LUSTER_DRAGON,
        )
        is None
    )
    #: ② 맞는 카드로 물으면 분류가 나온다 — ①이 "항상 None" 이 아니다.
    assert duel._effect_kind(HONEST_REF, honest) is ActivationKind.IGNITION

    #: ③ 그리고 그 어긋난 요청 자체는 **기존 검증**이 거절한다.
    mismatched = PlayerAction.activate_effect(
        actor=P0, source=other.instance_id, effect_ref=HONEST_REF
    )
    step = duel.apply(mismatched)
    assert step.accepted is False
    assert step.code is ValidationCode.EFFECT_REF_CARD_MISMATCH


def test_b04_two_effects_of_one_card_are_not_confused(repository):
    """
    🔴 **같은 카드의 서로 다른 효과**가 서로의 분류를 받지 않는다.

    이것이 "카드가 아니라 효과" 라는 말의 실제 내용이다 — 모듈 설명이 재어
    둔 856장이 1 계열과 2 계열을 둘 다 가진다.

    🔴 **합성 검증이다** — 같은 카드의 ``e[1]`` 자리에 분류만 다른 정의를
    둔 등록부를 쓴다. 어니스트에게 둘째 효과가 있다고 주장하지 않는다.
    """
    second = dataclasses.replace(
        HONEST_DEFINITION,
        effect_ref=EffectRef(HONEST, 1),
        activation_kind=ActivationKind.QUICK,
    )
    registry = EffectDefinitionRegistry(
        tuple(entry.definition for entry in EFFECT_LIBRARY) + (second,)
    )
    duel, honest = _honest_board(repository, definitions=registry)

    assert duel._effect_kind(HONEST_REF, honest) is ActivationKind.IGNITION
    assert (
        duel._effect_kind(EffectRef(HONEST, 1), honest) is ActivationKind.QUICK
    )
    #: 그리고 그 둘이 **다른 속도**를 받는다.
    assert KIND_SPEED[ActivationKind.IGNITION] is SpellSpeed.NORMAL
    assert KIND_SPEED[ActivationKind.QUICK] is SpellSpeed.FAST


def test_b05_a_known_kind_does_not_make_an_effect_executable(repository):
    """
    🔴 **분류를 안다고 발동이 허가되는 것이 아니다** (사용자 §4 의 금지 첫 줄).

    분류만 ``QUICK`` 으로 바꾼 정의를 두고 재면 **두 계층의 답이 갈린다** —
    실측:

    ==============================  =========================================
    ``ActivationTimingChecker``      ``VALID`` — 스펠 스피드 2 이므로 빠른
                                     효과 기회에서 속도가 막지 않는다
    ``ActionValidator``              ``UNKNOWN`` · ``quick-effect-activation
                                     (룰북이 발동 시점을 적지 않는다 —
                                     RULE-EFFECT-003 의 not_stated)``
    ==============================  =========================================

    즉 **속도 관문을 지나도 발동은 거절된다.** 유발즉시의 발동 시점은
    룰북이 적지 않았고 (``not_stated``), 그 사실을
    :data:`~engine.action_validation.ACTIVATION_KINDS_IN_SCOPE` 가 이미
    들고 있다 — 발동까지 판정하는 분류는 **기동 효과 하나**다.

    🔴 **합성 검증이다.** 어니스트 ①이 유발즉시라고 주장하지 않는다.
    """
    from engine.action_validation import (
        ACTIVATION_KINDS_IN_SCOPE,
        MONSTER_ACTIVATION_MISSING_BY_KIND,
    )
    from engine.activation_timing import (
        ActivationTiming,
        ActivationTimingChecker,
    )

    quick = dataclasses.replace(
        HONEST_DEFINITION, activation_kind=ActivationKind.QUICK
    )
    duel, honest = _honest_board(
        repository, definitions=_registry_with(quick)
    )
    action = PlayerAction.activate_effect(
        actor=P0, source=honest, effect_ref=HONEST_REF
    )
    _into_fast_window(duel)

    #: ① 속도 관문은 통과한다 — 분류가 2 라고 적혀 있으므로.
    timed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(
            duel.chain,
            duel.priority,
            stage=duel._activation_stage(),
            activation_kind=ActivationKind.QUICK,
        ),
        action,
    )
    assert timed.validity is ActionValidity.VALID
    assert "스펠 스피드 2" in timed.reason

    #: ② 🔴 그런데도 **발동은 거절된다** — 공통 관문의 답이다.
    verdict = _gate(duel, action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == (
        MONSTER_ACTIVATION_MISSING_BY_KIND[ActivationKind.QUICK]
    )
    assert _activations(duel, P0, HONEST) == []

    #: ③ 직접 넣어도 거절이고 상태가 불변이다.
    before = _fingerprint(duel)
    step = duel.apply(action)
    assert step.accepted is False
    assert _fingerprint(duel) == before

    #: ④ 그 범위가 코드에 적혀 있다 — 발동까지 판정하는 분류는 하나다.
    assert ACTIVATION_KINDS_IN_SCOPE == frozenset({ActivationKind.IGNITION})


# ======================================================================
# C. 실제 어니스트 — 허용 대조 먼저, 그 다음 금지
# ======================================================================
def test_c01_the_real_ignition_effect_is_blocked_as_a_rule_refusal(repository):
    """
    🔴 **보완7 의 본문.** 열린 상태에서 먼저 허용됨을 확인하고, 같은 초기
    판에서 빠른 효과 기회의 거절이 **규칙 거절**임을 센다.

    ``tests/engine/test_fast_window_legality.py::test_c02`` 가 같은 사실을
    그 파일의 맥락에서 세고, 이쪽은 **이유와 코드와 상태 불변**을 한 자리에
    모은다.
    """
    #: ① 허용 대조 — 열린 상태에서 실제로 발동 · 해결되어 판을 바꾼다.
    duel, honest = _honest_board(repository)
    assert duel._activation_stage() is ActivationStage.OPEN
    action = _activations(duel, P0, HONEST)[0]
    assert _gate(duel, action).validity is ActionValidity.VALID
    hand = len([c for c in duel.state.player(P0).hand if c])
    assert duel.apply(action).accepted is True
    duel.apply(PlayerAction.passing(actor=P1))
    assert "해결" in duel.apply(PlayerAction.passing(actor=P0)).reason
    assert len([c for c in duel.state.player(P0).hand if c]) == hand + 1
    assert [c for c in duel.state.player(P0).monster_zone if c] == []

    #: ② **별도의 같은 초기 판**에서 빠른 효과 기회에 들어간다.
    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]
    _into_fast_window(duel)

    #: ③ 후보에서 빠진다.
    assert _activations(duel, P0, HONEST) == []

    #: ④ 공통 관문이 ``INVALID`` 다 — 모름이 아니다.
    verdict = _gate(duel, action)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert verdict.missing_rule is None

    #: ⑤ 직접 ``apply`` 도 **같은 규칙 거절**이고 상태가 불변이다.
    before = _fingerprint(duel)
    step = duel.apply(action)
    assert (step.accepted, step.code) == (False, ValidationCode.SPELL_SPEED_TOO_LOW)
    assert step.reason == verdict.reason
    assert _fingerprint(duel) == before

    #: ⑥ 양측이 지나가면 다시 발동할 수 있다 — 막은 것이 단계였다.
    pass_fast_window(duel)
    assert duel._activation_stage() is ActivationStage.OPEN
    assert _activations(duel, P0, HONEST)
    assert duel.apply(action).accepted is True


def test_c02_a_real_trap_can_now_respond_to_a_monster_effect(repository):
    """
    🔴 **같은 길이 체인 링크의 속도에도 필요했다** (사용자 §4 의 마지막 줄).

    실측 (보완7 §2, 기준 HEAD)::

        전 턴에 세운 욕망의 선물로 어니스트 ①에 응수
        → accepted=False  code=RULE_NOT_IMPLEMENTED
          "응수할 링크의 스펠 스피드를 판정할 수 없습니다 (몬스터 효과)."

    규칙은 그 응수를 **허락한다** (스펠 스피드 2 → 1). 막은 것은 규칙이
    아니라 분류가 관문까지 가지 못한 것이고, ``responding_kind`` 가 같은
    경로로 그것을 전달한다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * 30, [LUSTER_DRAGON] * 30),
        turn_player=P1,
        seed=1,
    )
    honest = state.create_instance(HONEST, owner=P0, zone=Zone.MZONE)
    state.move(
        honest, Zone.MZONE, to_player=P0, position=Position.FACEUP_ATTACK
    )
    gift = state.create_instance(
        GIFT_OF_GREED, owner=P1, zone=Zone.HAND
    ).instance_id
    for _ in range(2):
        state.create_instance(LUSTER_DRAGON, owner=P0, zone=Zone.HAND)
        state.create_instance(LUSTER_DRAGON, owner=P1, zone=Zone.HAND)
    state.turn.turn_number = 4
    state.turn.turn_player = P1
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P1, phase=Phase.MAIN1),
        **duel_components(),
    )

    #: ① 세우는 것도 **실제 행위**다 — 기록이 남는다.
    set_down(duel, gift, seat=P1)
    next_turn(duel, to_seat=P0)

    #: ② 어니스트 ①을 열린 상태에서 발동한다 (체인 1).
    mine = _activations(duel, P0, HONEST)[0]
    assert duel.apply(mine).accepted is True
    assert len(duel.chain) == 1
    assert duel._activation_stage() is ActivationStage.CHAIN_RESPONSE

    #: ③ 🔴 비턴 플레이어의 함정이 **응수 후보로 나온다.**
    offered = _activations(duel, P1, GIFT_OF_GREED)
    assert offered, duel.legal_actions(P1).withheld
    assert duel._effect_kind(mine.effect_ref, mine.source) is (
        ActivationKind.IGNITION
    )

    #: ④ 정상 경로로 발동되어 체인 2 가 된다.
    assert duel.apply(offered[0]).accepted is True
    assert len(duel.chain) == 2

    #: ⑤ 양측 PASS 로 **두 링크가 역순으로** 해결된다.
    #:
    #: 욕망의 선물은 ``DrawOperation(count=2, who=OPPONENT)`` 이므로 발동한
    #: ``P1`` 의 상대인 ``P0`` 가 2장 뽑고, 그 다음에 풀리는 어니스트 ①이
    #: **자기 자신을 ``P0`` 의 패로** 되돌린다. 그래서 ``P0`` 의 패는
    #: **3장** 늘어난다 — 둘을 따로 센다.
    drawing = len([c for c in duel.state.player(P0).hand if c])
    duel.apply(PlayerAction.passing(actor=P0))
    resolved = duel.apply(PlayerAction.passing(actor=P1))
    assert "해결" in resolved.reason
    assert len([c for c in duel.state.player(P0).hand if c]) == drawing + 3
    #: 어니스트가 패로 돌아왔다 (그 1장의 정체).
    assert HONEST in [
        c.card_id for c in duel.state.player(P0).hand if c
    ]
    assert [c for c in duel.state.player(P0).monster_zone if c] == []
    #: 그리고 나머지 2장은 **덱에서** 왔다 — 함정이 실제로 해결됐다.
    assert duel.chain.is_complete


def test_c03_spell_speed_1_still_cannot_respond_on_a_chain(repository):
    """
    🔴 **응답 단계의 제약은 그대로다** — 분류를 알게 된 것이 응수를
    허락하지 않는다.

    어니스트 ①은 ``IGNITION`` = 스펠 스피드 1 이므로 체인에 응수할 수
    없다 (RULE-CHAIN-004 — *"스펠 스피드 1 은 어떤 효과에도 응수할 수
    없습니다"*). 전에는 그 자리가 ``UNKNOWN`` 이었고 지금은 **규칙
    거절**이다 — 좁아졌을 뿐 넓어지지 않았다.
    """
    from engine.activation_timing import (
        ActivationTiming,
        ActivationTimingChecker,
    )

    duel, honest = _honest_board(repository)
    mine = _activations(duel, P0, HONEST)[0]
    assert duel.apply(mine).accepted is True
    assert len(duel.chain) == 1
    assert duel._activation_stage() is ActivationStage.CHAIN_RESPONSE

    verdict = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(
            duel.chain,
            duel.priority,
            stage=ActivationStage.CHAIN_RESPONSE,
            activation_kind=ActivationKind.IGNITION,
            responding_kind=ActivationKind.IGNITION,
        ),
        mine,
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert "응수할 수 없습니다" in verdict.reason

    #: 🔴 그리고 스펠 스피드 2 는 그 링크에 응수할 수 있다 — 같은 표가
    #: 양쪽을 가른다 (``c02`` 가 실제 카드로 센다).
    allowed = ActivationTimingChecker(duel.view(P0)).check(
        ActivationTiming(
            duel.chain,
            duel.priority,
            stage=ActivationStage.CHAIN_RESPONSE,
            activation_kind=ActivationKind.QUICK,
            responding_kind=ActivationKind.IGNITION,
        ),
        mine,
    )
    assert allowed.validity is ActionValidity.VALID


# ======================================================================
# D. 비턴 플레이어의 실제 빠른 효과 (보완6 BLOCKER-F6-3)
# ======================================================================
def test_d01_the_non_turn_player_activates_a_real_trap_in_the_fast_window(
    repository,
):
    """
    🔴 **상자 C** — 턴 플레이어가 지나간 뒤 **상대**가 실제 함정을 발동한다.

    보완6 은 이 자리를 재지 못하고 BLOCKER-F6-3 으로 남겼다 (그 보고서의
    측정은 전부 턴 플레이어 쪽이었다). 이 시험이 그 공백을 메운다.

    초기 판 구성과 **검증 대상 실행**을 구분한다 — 세우는 것은 전 턴의
    실제 ``SET_SPELL_TRAP`` 행위이고, 턴을 넘기는 것도 실제 진행이다.
    필수 상태 전이를 실행 중에 주입하지 않는다.
    """
    duel, sources, _ = staged(
        repository, mine=[], fodder=3, their_hand=2, turn_player=P1
    )
    gift = duel.state.create_instance(
        GIFT_OF_GREED, owner=P1, zone=Zone.HAND
    ).instance_id

    #: ① 전 턴에 **실제 행위로** 세운다.
    set_down(duel, gift, seat=P1)
    next_turn(duel, to_seat=P0)
    assert duel._activation_stage() is ActivationStage.OPEN

    #: ② 턴 플레이어의 **정상 행동**으로 빈 체인 빠른 효과 기회를 연다.
    _into_fast_window(duel)
    assert duel.chain.is_empty
    assert duel.priority.holder.seat == P0

    #: ③ 턴 플레이어가 지나간다 — 그러면 기회가 상대에게 간다.
    assert _activations(duel, P0) == []
    assert duel.apply(PlayerAction.passing(actor=P0)).accepted is True
    assert duel.priority.holder.seat == P1
    assert duel.chain.is_empty
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW

    #: ④ 🔴 비턴 플레이어에게 **실제 함정 후보**가 나온다.
    offered = _activations(duel, P1, GIFT_OF_GREED)
    assert offered, duel.legal_actions(P1).withheld
    assert _kinds(duel, P1) == ["activate_effect", "pass"]

    #: ⑤ 정상 ``Duel.apply`` 로 발동한다.
    drawing = len([c for c in duel.state.player(P0).hand if c])
    assert duel.apply(offered[0]).accepted is True
    assert len(duel.chain) == 1

    #: ⑥ 응답 · 해결 후 **발동한 쪽의 상대가 2장 뽑는다.**
    #: (``DrawOperation(count=2, who=OPPONENT)`` — 발동한 쪽이 ``P1``
    #: 이므로 ``P0`` 가 뽑는다.)
    duel.apply(PlayerAction.passing(actor=P0))
    resolved = duel.apply(PlayerAction.passing(actor=P1))
    assert "해결" in resolved.reason
    assert len([c for c in duel.state.player(P0).hand if c]) == drawing + 2


def test_d02_the_set_turn_limit_is_not_bypassed(repository):
    """
    🔴 **세트한 턴 제한을 우회하지 않는다** (사용자 §6.D 의 마지막 줄).

    같은 턴에 세운 함정은 그 기회에서도 발동되지 않는다 — 분류 전달이
    그 제약을 건드리지 않았다.
    """
    duel, sources, _ = staged(
        repository, mine=[GIFT_OF_GREED], fodder=3, their_hand=2
    )
    set_down(duel, sources[0])
    #: 턴을 넘기지 **않는다** — 세운 턴 그대로다.
    assert _activations(duel, P0, GIFT_OF_GREED) == []
    action = PlayerAction.activate_effect(
        actor=P0, source=sources[0], effect_ref=EffectRef(GIFT_OF_GREED, 0)
    )
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is ValidationCode.SET_THIS_TURN


# ======================================================================
# E. 사본과 결과 전파
# ======================================================================
def test_e01_a_fork_sees_the_same_kind_and_the_same_verdict(repository):
    """사본의 **효과 분류**와 판정이 원본과 같다."""
    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]
    _into_fast_window(duel)
    fork = Simulator(duel=duel)._fork()

    assert fork._effect_kind(HONEST_REF, honest) == duel._effect_kind(
        HONEST_REF, honest
    )
    assert _kinds(fork, P0) == _kinds(duel, P0)
    mine, theirs = duel.apply(action), fork.apply(action)
    assert (mine.accepted, mine.code) == (theirs.accepted, theirs.code)
    assert mine.reason == theirs.reason


def test_e02_a_forks_refusal_does_not_touch_the_parent(repository):
    """사본이 거절을 받아도 **원본의 판 · 체인 · 기회 상태는 그대로**다."""
    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]
    _into_fast_window(duel)
    before = _fingerprint(duel)

    fork = Simulator(duel=duel)._fork()
    assert fork.apply(action).accepted is False
    pass_fast_window(fork)
    assert fork.apply(action).accepted is True

    assert _fingerprint(duel) == before
    assert duel._activation_stage() is ActivationStage.FAST_WINDOW


def test_e03_a_fork_has_its_own_definition_registry(repository):
    """
    🔴 사본의 **정의 등록부가 격리**된다 — 보완4 의 성과 그대로.

    분류의 출처가 그 등록부이므로, 격리가 깨지면 한쪽의 등록이 다른 쪽의
    **판정**을 바꾼다.
    """
    duel, honest = _honest_board(repository)
    fork = Simulator(duel=duel)._fork()
    assert fork._activator.definitions is not duel._activator.definitions

    extra = dataclasses.replace(
        HONEST_DEFINITION,
        effect_ref=EffectRef(HONEST, 7),
        activation_kind=ActivationKind.QUICK,
    )
    fork._activator.definitions.register(extra)
    assert fork._effect_kind(EffectRef(HONEST, 7), honest) is (
        ActivationKind.QUICK
    )
    #: 🔴 원본은 그것을 모른다.
    assert duel._effect_kind(EffectRef(HONEST, 7), honest) is None


# ======================================================================
# G. 보고 계층 — 같은 판정을 읽는다
# ======================================================================
def test_g01_the_reporting_layer_reads_the_same_verdict(repository):
    """
    🔴 **보고 계층이 같은 코드를 읽는다** (사용자 §4.10 · §5).

    ``deck/opening.py`` 의 ``_gate_code`` 가 ``Duel._activation_gate`` 를
    그대로 부르므로, 후보 생성 · 직접 ``apply`` · 보고가 **한 판정**을
    본다. 전에는 그 자리가 기동 효과에 대해 ``RULE_NOT_IMPLEMENTED`` 를
    적었고, 지금은 ``SPELL_SPEED_TOO_LOW`` 다.
    """
    from deck.opening import _gate_code, unsupported_reasons

    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]

    #: ① 열린 상태에서는 통과 코드다.
    assert _gate_code(duel, action, repository) == "OK"

    #: ② 빠른 효과 기회에서는 **규칙 거절 코드**다.
    _into_fast_window(duel)
    assert _gate_code(duel, action, repository) == "SPELL_SPEED_TOO_LOW"
    assert _gate(duel, action).code.name == "SPELL_SPEED_TOO_LOW"
    assert duel.apply(action).code.name == "SPELL_SPEED_TOO_LOW"

    #: ③ 그리고 그 거절은 **미지원 사유로 집계되지 않는다.**
    reasons = unsupported_reasons(duel.legal_actions(P0))
    assert not any("스펠 스피드" in line for line in reasons), reasons
    assert all(held.missing for held in duel.legal_actions(P0).unsupported())


def test_g02_a_rule_refusal_is_not_counted_as_unsupported(repository):
    """
    🔴 **규칙 거절은 ``missing`` 을 달지 않는다** — 그래서 미지원 집계에
    들어가지 않는다.

    유발 경로의 보류가 그 구분을 직접 적는다 (``Duel._trigger_actions``):
    관문이 ``UNKNOWN`` 이면 ``missing`` 을 채우고, 규칙이 금지하면 비운다.
    """
    duel, honest = _honest_board(repository)
    action = _activations(duel, P0, HONEST)[0]
    _into_fast_window(duel)

    verdict = _gate(duel, action)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.missing_rule is None

    #: 🔴 **보완8 이 이 자리를 고쳤다 — 보류가 남는다.**
    #:
    #: 보완7 은 여기서 ``held == []`` 를 셌고, 그 주석은 *"미지원으로 잘못
    #: 집계가 아니라 집계에 아예 없다"* 였다. 즉 이 시험이 **BLOCKER-F7-1
    #: 을 못 박고 있었다.** 보완8 이 ``_activation_actions`` 가 관문 판정을
    #: 보존하게 했으므로 지금은 한 줄이 남는다.
    #:
    #: 🔴 **느슨하게 한 것이 아니라 더 센다**: 그 줄이 (1) 규칙 거절이고
    #: (2) 코드가 관문의 것과 같고 (3) ``missing`` 이 비어 있어 미지원
    #: 집계에 들어가지 않고 (4) 어느 효과인지가 문장에 남아 있다.
    held = [
        w
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(held) == 1, held
    assert held[0].code is ValidationCode.SPELL_SPEED_TOO_LOW
    assert held[0].is_rule_refusal is True
    assert held[0].missing is None
    assert str(HONEST_REF) in held[0].reason
    #: 그래서 미지원 집계에는 들어가지 않는다 — 규칙이 막은 것이다.
    assert held[0] not in duel.legal_actions(P0).unsupported()


# ======================================================================
# F. 책임 — 분류표도 찾는 길도 한 벌이다
# ======================================================================
def test_f01_only_one_place_maps_a_kind_to_a_spell_speed():
    """
    🔴 **분류 → 스펠 스피드 표가 한 벌이다.**

    production 전체에서 그 대응을 적는 자리가 ``KIND_SPEED`` 하나임을
    센다 — 두 벌이 되면 관문과 보고 계층이 갈린다 (사용자 §4 의 금지).
    """
    offenders = []
    for package in ("engine", "agent", "integration"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(PROJECT_ROOT))
            tree = ast.parse(text)
            for node in ast.walk(tree):
                #: ``ActivationKind.X: SpellSpeed.Y`` 꼴의 사전을 찾는다.
                if not isinstance(node, ast.Dict):
                    continue
                pairs = [
                    (k, v)
                    for k, v in zip(node.keys, node.values)
                    if isinstance(k, ast.Attribute)
                    and isinstance(k.value, ast.Name)
                    and k.value.id == "ActivationKind"
                    and isinstance(v, ast.Attribute)
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "SpellSpeed"
                ]
                if pairs:
                    offenders.append((rel, node.lineno))
    #: 🔴 **정확히 한 자리**다. 비어 있으면 표가 사라진 것이고 (이 시험이
    #: 지키려는 것이 없어진다), 둘 이상이면 갈라진 것이다.
    assert [rel for rel, _ in offenders] == ["engine/activation_timing.py"], (
        offenders
    )


def test_f02_only_one_function_finds_the_kind_from_the_registry():
    """
    🔴 **등록부에서 분류를 찾는 구현이 한 벌이다.**

    각자 ``definition_for`` 를 뒤지면 "카드가 맞는가" 를 한쪽만 확인하는
    일이 생긴다 (``test_b03`` 이 지키는 것이 그것이다).

    경로가 둘인 이유는 **import 경계**다 — :mod:`engine.duel` 은
    ``engine.effect`` 를 읽지 않으므로 (``test_a_the_duel_module_still_
    imports_no_effect_layer``) 다리 쪽
    :func:`~engine.spell_activation.effect_kind_of` 를 지나고, 그 다리는
    저쪽 함수를 **그대로** 부르는 한 줄이다. :class:`ResponseLoop` 은 효과
    계층을 읽으므로 바로 부른다.
    """
    def _calls(rel, name):
        tree = ast.parse(
            (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return {
                    sub.func.id
                    for sub in ast.walk(node)
                    if isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                }
        return None

    #: ① 듀얼은 다리를 지난다.
    duel_calls = _calls("engine/duel.py", "_effect_kind")
    assert duel_calls is not None
    assert "effect_kind_of" in duel_calls, duel_calls
    assert "verified_activation_kind" not in duel_calls

    #: ② 응답 루프는 바로 부른다.
    loop_calls = _calls("engine/response.py", "_effect_kind")
    assert loop_calls is not None
    assert "verified_activation_kind" in loop_calls, loop_calls

    #: ③ 그리고 그 다리는 **그 함수만** 부른다 — 규칙을 더하지 않았다.
    bridge = _calls("engine/spell_activation.py", "effect_kind_of")
    assert bridge == {"verified_activation_kind"}, bridge


def test_f03_the_engine_carries_no_card_specific_branch():
    """
    🔴 **어니스트 카드 ID 전용 분기를 만들지 않았다** (사용자 §4 의 금지).

    🔴 **산문은 세지 않는다.** ``engine/activation_timing.py`` 의 모듈
    설명이 보완6 의 실측을 인용하며 그 번호를 적고 있고, 그것은 분기가
    아니라 **기록**이다. 그래서 문자열 리터럴을 벗긴 뒤 **실행 코드만**
    본다 — 줄 수 핀이 주석과 코드를 구분하지 못한다는
    ``test_trigger_pipeline_dormant_audit`` 의 교훈과 같은 자리다.
    """

    class _StripStrings(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802 - ast 규약
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value=""), node)
            return node

    #: 🔴 **효과 목록은 예외다** — ``engine/effect/library.py`` 는 어느
    #: 카드의 어느 효과를 손으로 적었는지의 **대장**이고 (ADR-006), 카드
    #: 번호가 거기 있는 것이 그 파일의 일이다. 규칙 · 판정 · 흐름 계층에
    #: 번호가 없다는 것이 이 시험의 주장이다.
    ledger = "engine/effect/library.py"
    offenders = []
    for package in ("engine", "agent", "integration"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            rel = str(path.relative_to(PROJECT_ROOT))
            if rel == ledger:
                continue
            tree = _StripStrings().visit(
                ast.parse(path.read_text(encoding="utf-8"))
            )
            if str(HONEST) in ast.unparse(tree):
                offenders.append(rel)
    assert offenders == [], offenders
    #: 그리고 그 대장에는 **있다** — 위 건너뛰기가 "아무도 안 본다" 가
    #: 아님을 센다.
    assert str(HONEST) in (PROJECT_ROOT / ledger).read_text(encoding="utf-8")


def test_f04_the_timing_layer_cannot_read_the_registry_itself():
    """
    🔴 **타이밍 계층은 등록부를 import 하지 않는다** — 값으로 받는다.

    읽게 하면 판정 계층이 등록부에 묶이고, 관측만 받는다는 규율
    (``ActivationTimingChecker`` 가 ``GameStateView`` 만 받는 이유)이
    무너진다.
    """
    text = (PROJECT_ROOT / "engine/activation_timing.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(
        module.startswith("engine.effect") for module in imported
    ), sorted(imported)
    #: 그리고 ``rules`` 도 읽지 않는다 — 표는 손으로 옮기고 시험이 대조한다.
    assert not any(module.startswith("rules") for module in imported)
