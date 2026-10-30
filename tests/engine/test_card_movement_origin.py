"""
Phase 6-M — 카드 이동의 **출발 자리 · 도착 자리 · 카드 종류.**

    CardOperation(RETURN_TO_HAND, origin_zones=FIELD_ZONES)
        ↓  EffectExecutor._plan_card_operation     ← 계획 단계에서만 거절한다
    (ORIGIN_RULES) → (이 효과가 적은 자리) → (도착 자리가 가능한가) → (관문)
        ↓  _apply_card_movement
    GameState 변경 + EventJournal

이 파일이 지키는 것
-------------------
🔴 **"패로 되돌릴 수 있다" 가 "어디서든 패로 간다" 를 뜻하지 않는다.**
6-L 측정에서는 열 자리 전부가 ``RESOLVED`` 였다 — 묘지 · 덱 · 제외 구역 ·
엑스트라 덱에 있는 카드까지 패로 돌아갔다 (§A).

🔴 **전역 표와 이 효과의 제약은 다른 축이다.** ``ORIGIN_RULES`` 는 일의
종류마다 전역이어서 ``RETURN_TO_HAND`` 를 필드로 묶으면 묘지에서 패로
되돌리는 실제 카드들이 전부 틀린다. 그래서 6-M 은 그 표에 줄을 더하지
않고, 조작 하나가 자기 출발 자리를 적게 했다 (§B · §C).

🔴 **엑스트라 덱 몬스터를 메인 덱 카드처럼 옮기지 않는다.** 룰북은 그
카드가 패 · 메인 덱으로 들어오는 길을 말하지 않고, 그러면 어디로 가는지도
말하지 않는다 — 목적지를 지어내지 않고 멈춘다 (§E).

🔴 **일어나지 않은 이동을 성공으로 적지 않는다.** 이미 그 자리에 있는
카드는 옮길 것이 없다 (§F).

🔴 **거절은 계획 단계에서만 한다.** 판이 하나도 바뀌지 않고 journal 도
비어 있다 (§I · ADR-008).
"""

import ast
import pathlib

import pytest

from engine.action import PlayerActionKind
from engine.duel import Duel
from engine.effect.definition import EffectDefinition, EffectProvenance
from engine.effect.executor import (
    DESTINATION,
    DESTINATION_OWNER,
    DestinationOwner,
    EffectExecutor,
    EffectImplementationRegistry,
    destination_player,
    movement_destination,
    movement_player,
)
from engine.effect.journal import EventJournal
from engine.effect.library import (
    EFFECT_LIBRARY,
    HONEST,
    OPERATION_RULINGS,
    definition_registry,
)
from engine.effect.operation import (
    CARD_OPERATION_KINDS,
    MOVABLE_DESTINATIONS,
    CardOperation,
    MoveOperation,
    OperationKind,
)
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.semantics import (
    FIELD_ZONES,
    MAIN_DECK_ONLY_ZONES,
    MISSING_EXTRA_DECK_DESTINATION,
    MISSING_SAME_ZONE_MOVEMENT,
    ORIGIN_RULES,
    origin_rule,
)
from engine.effect.target import SELF_TARGET
from engine.ids import EffectRef
from engine.payment import COST_OPERATION, SUPPORTED_COSTS
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

HONEST_REF = EffectRef(HONEST, 0)
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터. 덱을 이것으로 채운다.
FEATHERMAN = 21844576
#: 궁극의 푸른 눈의 백룡 — **융합 몬스터**이고 효과가 없다.
ULTIMATE_BLUE_EYES = 23995346
#: 오드아이즈 펜듈럼 드래곤 — **펜듈럼**이지만 메인 덱 카드다.
ODD_EYES = 16178681
#: 욕망의 항아리 — 마법 카드.
POT_OF_GREED = 55144522

#: 이 파일이 쓰는 모든 자리. 엔진이 가진 것 전부다.
ALL_ZONES = (
    Zone.MZONE,
    Zone.EMZONE,
    Zone.SZONE,
    Zone.FZONE,
    Zone.PZONE,
    Zone.GRAVE,
    Zone.REMOVED,
    Zone.DECK,
    Zone.EXTRA,
    Zone.HAND,
)


# ======================================================================
# 판 만들기
# ======================================================================


def definition_of(operation, *, card_id=HONEST):
    """그 조작 하나만 하는 자기 참조 정의. **production 을 건드리지 않는다.**"""
    return EffectDefinition(
        effect_ref=EffectRef(card_id, 0),
        source_card_id=card_id,
        operations=(operation,),
        provenance=EffectProvenance.official_lua("Phase 6-M 시험용"),
    )


def run(
    repository,
    definition,
    *,
    card_id=HONEST,
    zone=Zone.MZONE,
    owner=MINE,
    controller=None,
    journal=None,
    extra=(),
):
    """실제 실행기로 돌린다. ``(결과, state, 움직일 카드)``."""
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    for other_id, other_zone in extra:
        state.create_instance(
            other_id, owner=MINE, zone=other_zone, position=Position.FACEUP
        )
    instance = state.create_instance(
        card_id, owner=owner, zone=zone, position=Position.FACEUP
    )
    if controller is not None:
        instance.controller = controller
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        rulings=OPERATION_RULINGS,
        journal=journal,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            source=instance.instance_id,
        ),
    )
    return result, state, instance


def board(repository, *cards, zone=Zone.MZONE, journal=None):
    """앞면으로 놓인 판 + 실제 ``Duel``."""
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    placed = [
        state.create_instance(card_id, owner=MINE, zone=zone,
                              position=Position.FACEUP)
        for card_id in cards
    ]
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    return duel, placed


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


# ======================================================================
# A. 기존 구조 — ORIGIN_RULES 는 무엇을 관리하는가 (§4-A · §16-1)
# ======================================================================


def test_a01_origin_rules_holds_exactly_two_kinds():
    """
    🔴 **§4-A 1 · 2** — ``ORIGIN_RULES`` 에는 **두 줄**뿐이고,
    ``RETURN_TO_HAND`` 는 **그중에 없다.**

    6-M 의 과제 설명은 "``ORIGIN_RULES`` 에 ``RETURN_TO_HAND`` 관련 출발
    영역 제약이 있다" 였다. 🔴 **실제 코드는 반대다** — 제약이 하나도
    없고, 그 **없음**이 결함이었다. 막힌 이동을 푸는 작업이 아니라, 전부
    열려 있던 것을 공식 텍스트가 말한 만큼만 좁히는 작업이다.

    그리고 6-M 은 이 표에 **줄을 더하지 않았다** — ``test_b01`` 이 왜
    더할 수 없는지를 센다.
    """
    assert set(ORIGIN_RULES) == {
        OperationKind.DISCARD,
        OperationKind.DESTROY,
    }
    assert OperationKind.RETURN_TO_HAND not in ORIGIN_RULES
    assert origin_rule(OperationKind.RETURN_TO_HAND) is None

    #: 두 줄이 **"안다" 와 "모른다" 를 나눈다** — 그 구분이 이 표의 설계다.
    assert ORIGIN_RULES[OperationKind.DISCARD].known is True
    assert ORIGIN_RULES[OperationKind.DISCARD].zones == frozenset({Zone.HAND})
    assert ORIGIN_RULES[OperationKind.DESTROY].known is False
    assert ORIGIN_RULES[OperationKind.DESTROY].missing


@pytest.mark.real_card
@pytest.mark.parametrize("zone", ALL_ZONES)
def test_a02_an_operation_that_declares_nothing_still_moves_from_anywhere(
    repository, zone
):
    """
    🔴 **§12-1 · §12-2 — 구현 전 측정을 그대로 남긴다.**

    자리를 **적지 않은** 조작은 어느 자리에서든 지난다. 6-M 이 그것을
    바꾸지 않았다 — 적지 않은 것을 "필드에서만" 으로 읽으면 묘지에서 패로
    되돌리는 실제 카드들이 틀린다.

    유일한 예외가 ``HAND`` 이고, 그것은 자리 규칙이 아니라 **옮길 것이
    없다**는 사실이다 (§F).
    """
    definition = definition_of(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    assert definition.operations[0].origin_zones is None

    result, state, instance = run(repository, definition, zone=zone)
    after = state.find_instance(instance.instance_id)

    if zone is Zone.HAND:
        assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION
        assert after.zone is Zone.HAND
        return
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert after.zone is Zone.HAND


def test_a03_the_global_table_would_be_wrong_for_return_to_hand():
    """
    🔴 **§5 · §9 — 왜 ``ORIGIN_RULES`` 에 줄을 더하지 않았는가.**

    그 표는 **일의 종류마다 전역**이다 (:class:`
    ~engine.effect.semantics.OriginRule` 하나가 ``OperationKind`` 하나에
    붙는다). 그러므로 ``RETURN_TO_HAND`` 에 ``FIELD_ZONES`` 를 적으면
    **모든** 패 되돌림이 필드에서만 일어난다.

    근거는 추측이 아니라 코퍼스 측정이다 — 묘지에서 패로 되돌리는 공식
    스크립트가 실제로 많다 (``test_a04``).
    """
    #: 표의 모양 자체가 "종류 하나에 규칙 하나" 다.
    for kind, rule in ORIGIN_RULES.items():
        assert isinstance(kind, OperationKind)
        assert rule.zones and all(isinstance(z, Zone) for z in rule.zones)

    #: 그래서 조작마다 적는 칸이 **따로** 있어야 한다 (Phase 6-M).
    assert "origin_zones" in CardOperation.__dataclass_fields__
    assert CardOperation.__dataclass_fields__["origin_zones"].default is None


def test_a04_the_corpus_returns_cards_to_hand_from_off_field():
    """
    🔴 **§6 — 필드 밖에서 패로 되돌리는 공식 스크립트를 센다.**

    ``ORIGIN_RULES`` 를 전역으로 좁히면 **이 카드들이 전부 틀린다.** 숫자가
    근거다 — 추측이 아니다.

    표본: 저장소의 ``c*.lua`` 전부. 세는 것은 ``Duel.SendtoHand`` 호출과
    같은 블록에 ``LOCATION_GRAVE`` · ``LOCATION_DECK`` · ``LOCATION_REMOVED``
    가 함께 적힌 파일 수다. **정적 분석이고 실행 수치가 아니다.**
    """
    scripts = sorted(PROJECT_ROOT.glob("c*.lua"))
    assert len(scripts) > 10_000, len(scripts)

    off_field = {"LOCATION_GRAVE": 0, "LOCATION_DECK": 0, "LOCATION_REMOVED": 0}
    sendtohand = 0
    for path in scripts:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Duel.SendtoHand" not in text:
            continue
        sendtohand += 1
        for name in off_field:
            if name in text:
                off_field[name] += 1

    #: 실측 (Phase 6-M). 숫자가 바뀌면 이 결론을 다시 봐야 한다.
    assert sendtohand > 2_000, sendtohand
    for name, count in off_field.items():
        assert count > 100, (name, count)


# ======================================================================
# B. 이 효과가 적은 출발 자리 (§9-C)
# ======================================================================


def test_b01_the_declared_origin_is_a_different_axis_from_the_table():
    """
    **§5 · §9-C** — 두 축이 **따로** 있고, 서로를 대신하지 않는다.

    전역 표는 "이 종류의 일은 여기서만 일어난다" 이고, 조작의 칸은
    "**이 효과**는 여기 있는 카드에 일어난다" 다.
    """
    declared = CardOperation.return_to_hand(
        SELF_TARGET, gated=True, origin_zones=FIELD_ZONES
    )
    assert declared.origin_zones == FIELD_ZONES
    #: 전역 표는 **여전히** 아무 말도 하지 않는다.
    assert origin_rule(declared.kind) is None

    #: 적지 않은 것이 기본값이고, 그것은 "어디서든" 이 아니라 "말하지
    #: 않았다" 다.
    assert CardOperation.return_to_hand(SELF_TARGET).origin_zones is None


def test_b02_an_empty_origin_cannot_be_declared():
    """
    🔴 "아무 자리에서도 일어나지 않는 일" 은 **적을 수 없다.**

    적으면 그 효과는 영영 실행되지 않는데, 그것은 "모른다" 와 다른 말이고
    모른다는 ``None`` 이 이미 뜻한다.
    """
    with pytest.raises(ValueError, match="빈 출발 자리"):
        CardOperation.return_to_hand(SELF_TARGET, origin_zones=frozenset())


def test_b03_the_origin_must_be_zones():
    """자리 이름 문자열을 받지 않는다 — 어휘를 섞지 않는다."""
    with pytest.raises(TypeError, match="frozenset"):
        CardOperation.return_to_hand(SELF_TARGET, origin_zones={Zone.MZONE})
    with pytest.raises(TypeError, match="Zone"):
        CardOperation.return_to_hand(SELF_TARGET, origin_zones=frozenset({"MZONE"}))


def test_b04_the_declaration_is_part_of_the_canonical_state():
    """
    적은 것과 적지 않은 것이 **다른 값**이어야 한다.

    같은 값으로 접히면 두 정의가 같은 것으로 보이고, 재현과 비교가 깨진다.
    """
    bare = CardOperation.return_to_hand(SELF_TARGET, gated=True)
    field = CardOperation.return_to_hand(
        SELF_TARGET, gated=True, origin_zones=FIELD_ZONES
    )
    grave = CardOperation.return_to_hand(
        SELF_TARGET, gated=True, origin_zones=frozenset({Zone.GRAVE})
    )
    states = {bare.canonical_state(), field.canonical_state(), grave.canonical_state()}
    assert len(states) == 3

    assert "origin_zones" not in bare.to_dict()
    assert field.to_dict()["origin_zones"] == sorted(
        z.value for z in FIELD_ZONES
    )
    assert grave.to_dict()["origin_zones"] == ["GRAVE"]


@pytest.mark.real_card
@pytest.mark.parametrize("zone", ALL_ZONES)
def test_b05_the_declared_origin_refuses_every_other_zone(repository, zone):
    """
    🔴 **§10-G** — 적은 자리가 아니면 **확실히 거절한다.**

    ``ORIGIN_RULES`` 의 "모른다" 쪽과 다르다 — 이것은 공식 텍스트가 적은
    것을 옮긴 것이므로 **아는 규칙**이고, ``SOURCE_WRONG_ZONE`` 이다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(
            SELF_TARGET, gated=True, origin_zones=FIELD_ZONES
        )
    )
    result, state, instance = run(repository, definition, zone=zone)
    after = state.find_instance(instance.instance_id)

    if zone in FIELD_ZONES:
        assert result.status is ResolutionStatus.RESOLVED, result.reason
        assert after.zone is Zone.HAND
        return
    assert result.status is ResolutionStatus.INVALID_TARGET, result.reason
    assert result.code is ValidationCode.SOURCE_WRONG_ZONE
    #: 🔴 **"안 된다" 이므로 없는 규칙을 적지 않는다.**
    assert result.missing is None
    #: 판은 그대로다.
    assert after.zone is zone
    assert result.deltas == ()


@pytest.mark.real_card
def test_b06_a_grave_only_effect_works_from_the_grave(repository):
    """
    🔴 **§10-B — 묘지에서 패로 회수하는 효과를 막지 않는다.**

    이것이 전역 표를 쓰지 않은 이유의 반대 방향 증거다. 같은
    ``RETURN_TO_HAND`` 가 **묘지에서만** 일어나는 효과로도 적힌다.

    등재된 카드로 하는 검증이 아니다 — 그런 카드는 아직 등재되어 있지
    않다 (``test_k03``). 축이 그것을 **표현할 수 있는가**를 센다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(
            SELF_TARGET, gated=True, origin_zones=frozenset({Zone.GRAVE})
        )
    )
    result, state, instance = run(repository, definition, zone=Zone.GRAVE)
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(instance.instance_id).zone is Zone.HAND

    #: 그리고 같은 정의가 필드에서는 **거절한다** — 축이 양방향이다.
    refused, state2, inst2 = run(repository, definition, zone=Zone.MZONE)
    assert refused.status is ResolutionStatus.INVALID_TARGET
    assert state2.find_instance(inst2.instance_id).zone is Zone.MZONE


# ======================================================================
# C. 어니스트 ① 이 공식 텍스트에서 자리를 받았다 (§10-A · §10-J)
# ======================================================================


@pytest.mark.real_card
def test_c01_honest_declares_the_field_because_the_text_says_so(repository):
    """
    🔴 **§4 — 근거가 공식 텍스트와 공식 Lua 양쪽에 있다.**

    「**필드의** 앞면 표시의 이 카드를 패로 되돌린다」 — 한국어 원문이
    직접 말한다. Lua 도 ``e1:SetRange(LOCATION_MZONE)`` 과
    ``if c:IsFaceup() and c:IsRelateToEffect(e)`` 로 적는다.
    """
    definition = definition_registry().definition_for(HONEST_REF)
    assert definition is not None
    operation = definition.operations[0]
    assert operation.kind is OperationKind.RETURN_TO_HAND
    assert operation.origin_zones == FIELD_ZONES

    card = repository.get(HONEST)
    assert card is not None
    text = card.desc or ""
    #: 🔴 공식 텍스트를 **번역하지 않았다** — 저장소의 원문을 읽는다.
    assert "필드의 앞면 표시의 이 카드를 패로 되돌린다" in text

    lua = source_of("c37742478.lua")
    assert "e1:SetRange(LOCATION_MZONE)" in lua
    assert "c:IsFaceup()" in lua

    #: 🔴 **옮기지 못한 것이 근거에 그대로 적혀 있다.**
    note = definition.provenance.note
    assert "origin_zones=FIELD_ZONES" in note
    assert "IsRelateToEffect" in note and "IsFaceup" in note


@pytest.mark.real_card
def test_c02_honest_still_resolves_through_the_real_duel(repository):
    """
    🔴 **§10-J · §17 수준 2 회귀** — 6-L 이 확보한 경로가 그대로다.

        legal_actions → apply → 체인 1 → 응답 창 → 해결
          → GameState 변경 → EventJournal
    """
    journal = EventJournal()
    duel, placed = board(repository, HONEST, journal=journal)
    honest = placed[0].instance_id

    candidates = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(candidates) == 1
    assert candidates[0].effect_ref == HONEST_REF
    assert candidates[0].targets == ()

    before = len(duel.state.player(MINE).hand)
    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    #: 발동만으로는 움직이지 않는다.
    assert duel.state.find_instance(honest).zone is Zone.MZONE

    settled = settle_chain(duel)
    assert settled is not None and settled.accepted
    assert duel.state.find_instance(honest).zone is Zone.HAND
    assert len(duel.state.player(MINE).hand) == before + 1

    events = [e for e in journal.events if e.effect_ref == HONEST_REF]
    assert len(events) == 1
    delta = events[0].deltas[0]
    assert delta.instance == honest
    assert delta.source_zone is Zone.MZONE
    assert delta.destination_zone is Zone.HAND
    assert delta.movement is OperationKind.RETURN_TO_HAND


@pytest.mark.real_card
def test_c03_honest_off_the_field_is_refused_not_moved(repository):
    """
    🔴 **§10-G — 6-L 이 남긴 잠재적 오동작이 닫혔다.**

    6-L 보고서 §16-1 이 적었다: "실측: 묘지 · 패 · 마법 & 함정 존에 있는
    카드도 ``RESOLVED`` 로 패에 돌아간다." 지금은 거절된다.
    """
    definition = definition_registry().definition_for(HONEST_REF)
    for zone in (Zone.GRAVE, Zone.REMOVED, Zone.DECK, Zone.HAND, Zone.EXTRA):
        journal = EventJournal()
        result, state, instance = run(
            repository, definition, zone=zone, journal=journal
        )
        assert result.status is ResolutionStatus.INVALID_TARGET, (zone, result.reason)
        assert result.code is ValidationCode.SOURCE_WRONG_ZONE, zone
        assert state.find_instance(instance.instance_id).zone is zone
        assert result.deltas == ()
        #: 🔴 기록도 없다.
        assert journal.events == ()


# ======================================================================
# D. 도착 자리를 정하는 자리는 하나다 (§7 · §9-C)
# ======================================================================


def test_d01_the_destination_table_is_unchanged():
    """6-M 은 ``DESTINATION`` 에 손대지 않았다."""
    assert DESTINATION == {
        OperationKind.DESTROY: Zone.GRAVE,
        OperationKind.SEND_TO_GRAVE: Zone.GRAVE,
        OperationKind.RELEASE: Zone.GRAVE,
        OperationKind.DISCARD: Zone.GRAVE,
        OperationKind.BANISH: Zone.REMOVED,
        OperationKind.RETURN_TO_HAND: Zone.HAND,
        OperationKind.RETURN_TO_DECK: Zone.DECK,
    }
    #: 주인 쪽도 그대로다 — 전부 소유권 기반 존이다.
    assert set(DESTINATION_OWNER.values()) == {DestinationOwner.OWNER}


def test_d02_one_function_decides_the_destination():
    """
    🔴 **§9-C** — 계획 단계와 적용 단계가 **같은 함수**를 본다.

    예전에는 두 자리가 같은 조건식을 따로 들고 있었다. 한쪽만 고치면
    계획이 통과시킨 이동이 다른 자리로 간다.
    """
    for kind in DESTINATION:
        operation = (
            CardOperation(kind, SELF_TARGET)
            if kind in CARD_OPERATION_KINDS
            else None
        )
        if operation is None:
            continue
        assert movement_destination(operation) is DESTINATION[kind]

    move = MoveOperation(Zone.REMOVED, SELF_TARGET)
    assert movement_destination(move) is Zone.REMOVED

    #: AST — 적용 단계가 **표를 직접 보지 않는다.**
    tree = ast.parse(source_of("engine/effect/executor.py"))
    apply_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_card_movement"
    )
    body = ast.unparse(apply_fn)
    assert "movement_destination(operation)" in body
    assert "DESTINATION[" not in body


@pytest.mark.real_card
def test_d03_one_function_decides_the_destination_player(repository):
    """``movement_player`` 도 한 곳이다 — 계획이 정하고 적용이 쓴다."""
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    card = state.create_instance(HONEST, owner=THEIRS, zone=Zone.MZONE,
                                 position=Position.FACEUP)
    card.controller = MINE

    operation = CardOperation.return_to_hand(SELF_TARGET)
    assert movement_player(operation, card) == THEIRS
    assert movement_player(operation, card) == destination_player(
        operation.kind, card
    )

    #: ``MOVE`` 는 조작이 직접 말한다 — 표에 그 줄이 **없다.**
    to_owner = MoveOperation(Zone.HAND, SELF_TARGET, to_owner=True)
    to_controller = MoveOperation(Zone.HAND, SELF_TARGET, to_owner=False)
    assert movement_player(to_owner, card) == THEIRS
    assert movement_player(to_controller, card) == MINE
    with pytest.raises(KeyError):
        destination_player(OperationKind.MOVE, card)


@pytest.mark.real_card
def test_d04_a_card_controlled_by_the_other_player_goes_to_its_owner(repository):
    """
    🔴 **§10-D · §7-F** — 소유자와 컨트롤러가 다르면 **소유자의** 패로 간다.

    ``GameState.move`` 의 기본값은 컨트롤러이므로, 기본값에 기대면 빼앗은
    쪽의 패로 들어간다. 계획 단계가 명시적으로 주인을 정한다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(
            SELF_TARGET, gated=True, origin_zones=FIELD_ZONES
        )
    )
    result, state, instance = run(
        repository, definition, owner=THEIRS, controller=MINE
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    after = state.find_instance(instance.instance_id)
    assert after.zone is Zone.HAND
    assert after.owner == THEIRS
    assert after.controller == THEIRS
    assert len(state.player(THEIRS).hand) == 1
    assert len(state.player(MINE).hand) == 0


# ======================================================================
# E. 엑스트라 덱 몬스터 (§7-C · §10-E)
# ======================================================================


def test_e01_the_main_deck_only_zones_come_from_the_rulebook():
    """
    🔴 **§4 근거** — 룰북의 ``Hand`` · ``Deck`` 칸에 엑스트라 덱 몬스터가
    들어오는 길이 **없다.**

    그리고 룰북은 그런 우회를 말할 때는 **명시한다** — 펜듈럼이 필드에서
    묘지로 갈 때 엑스트라 덱에 놓인다는 문장이 있다. 패 · 덱에 대해서는
    그런 문장이 없으므로, 어디로 가는지를 **모른다**.
    """
    import json

    rulebook = json.loads(
        (PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    zones = {z["engine_zone"]: z for z in rulebook["zones"] if z.get("engine_zone")}

    assert MAIN_DECK_ONLY_ZONES == frozenset({Zone.HAND, Zone.DECK})
    for zone in MAIN_DECK_ONLY_ZONES:
        movement = " ".join(zones[zone.value]["movement"])
        assert "Extra Deck" not in movement, (zone, movement)

    extra = " ".join(zones["EXTRA"]["movement"])
    assert "Extra Deck Monsters may be Summoned to the field from here" in extra
    #: 🔴 펜듈럼 우회는 **적혀 있다** — 그래서 패 쪽의 침묵이 의미를 갖는다.
    assert "Pendulum Monster Cards that would be sent from the field" in extra
    assert "hand" not in extra.lower()


@pytest.mark.real_card
@pytest.mark.parametrize("destination", sorted(MAIN_DECK_ONLY_ZONES, key=str))
def test_e02_an_extra_deck_monster_is_not_sent_to_the_hand_or_deck(
    repository, destination
):
    """
    🔴 **§10-E · §7-C** — 융합 몬스터를 **메인 덱 카드처럼 옮기지 않는다.**

    구현 전 측정: ``RESOLVED`` 로 패에 들어갔다 (패 1장 · 엑스트라 0장).
    지금은 멈추고, 무엇이 없어서 멈췄는지 이름을 남긴다.
    """
    card = repository.get(ULTIMATE_BLUE_EYES)
    assert card is not None and card.is_extra_deck

    operation = (
        CardOperation.return_to_hand(SELF_TARGET, origin_zones=FIELD_ZONES)
        if destination is Zone.HAND
        else CardOperation.return_to_deck(SELF_TARGET)
    )
    definition = definition_of(operation, card_id=ULTIMATE_BLUE_EYES)
    journal = EventJournal()
    result, state, instance = run(
        repository,
        definition,
        card_id=ULTIMATE_BLUE_EYES,
        journal=journal,
    )

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION, result.reason
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == MISSING_EXTRA_DECK_DESTINATION
    #: 🔴 판이 **하나도** 바뀌지 않는다.
    after = state.find_instance(instance.instance_id)
    assert after.zone is Zone.MZONE
    assert len(state.player(MINE).hand) == 0
    assert result.deltas == ()
    assert journal.events == ()


@pytest.mark.real_card
def test_e03_an_extra_deck_monster_still_goes_to_the_grave_and_removed(
    repository,
):
    """
    🔴 **막는 것은 패 · 메인 덱뿐이다.**

    융합 몬스터가 묘지로 가고 제외되는 것은 룰북이 말하는 보통의 일이고,
    6-M 이 그것을 건드리지 않았다. 카드 종류로 **모든** 이동을 막으면
    그것이 새 결함이다.
    """
    for operation, expected in (
        (CardOperation.send_to_grave(SELF_TARGET), Zone.GRAVE),
        (CardOperation.banish(SELF_TARGET), Zone.REMOVED),
    ):
        definition = definition_of(operation, card_id=ULTIMATE_BLUE_EYES)
        result, state, instance = run(
            repository, definition, card_id=ULTIMATE_BLUE_EYES
        )
        assert result.status is ResolutionStatus.RESOLVED, result.reason
        assert state.find_instance(instance.instance_id).zone is expected


@pytest.mark.real_card
def test_e04_a_pendulum_main_deck_monster_is_not_an_extra_deck_card(repository):
    """
    **§7-E** — 펜듈럼 몬스터는 **메인 덱 카드**이므로 패로 돌아간다.

    룰북이 말하는 엑스트라 덱 우회는 "필드에서 **묘지로** 갈 때" 이고, 패로
    되돌리는 경우가 아니다. 그 우회는 6-M 이 옮기지 않았다 (§16).
    """
    card = repository.get(ODD_EYES)
    assert card is not None and card.is_pendulum and not card.is_extra_deck

    definition = definition_of(
        CardOperation.return_to_hand(SELF_TARGET, origin_zones=FIELD_ZONES),
        card_id=ODD_EYES,
    )
    result, state, instance = run(repository, definition, card_id=ODD_EYES)
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(instance.instance_id).zone is Zone.HAND


def test_e05_the_card_type_is_read_from_one_derived_value():
    """
    🔴 **§3-12 — 카드 ID 로 분기하지 않는다.**

    읽는 것은 ``is_extra_deck`` 하나이고 그것은 이미 있는 파생값이다
    (``engine/summon_rules.py`` 가 일반 소환 판정에서 같은 값을 읽는다).
    """
    tree = ast.parse(source_of("engine/effect/executor.py"))
    checker = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_is_extra_deck"
    )
    body = ast.unparse(checker)
    assert "is_extra_deck" in body
    #: 카드 ID 도 이름도 읽지 않는다.
    for forbidden in ("card_id", "name", "type_mask", "type_names"):
        assert forbidden not in body, forbidden

    #: 거절을 판정하는 함수도 그렇다.
    refusal = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_movement_refusal"
    )
    refusal_body = ast.unparse(refusal)
    for forbidden in ("card_id", "type_mask", "type_names"):
        assert forbidden not in refusal_body, forbidden


@pytest.mark.real_card
def test_e06_an_unreadable_definition_is_a_measured_hole_not_a_refusal(repository):
    """
    🔴 **6-M 이 닫지 못한 공백을 숨기지 않고 못박는다** (§16-4).

    카드 정의를 읽을 수 없으면 ``_is_extra_deck`` 가 ``None`` 을 돌려주고,
    그것은 ``False`` 와 **구분된다.** 그런데 거절을 판정하는 쪽은
    ``is True`` 만 막는다 — 즉 **모르는 것이 통과한다.**

    그것이 "모르는 것을 허가로 바꾼다" 임을 안다. 그런데도 그렇게 둔
    이유를 측정으로 적는다.

    1. 저장소가 연결되지 않은 ``GameState`` 는 **시험용 구성**이다.
       production 의 듀얼 조립(``duel_components``)과 ``Duel`` 은 언제나
       저장소를 건넨 ``GameState`` 를 받는다 (``test_e07`` 이 센다).
    2. 그 자리를 막으면 **실제 카드가 아닌 합성 ID** 로 실행기 기계를 재는
       기존 단위 시험 **열한 개**가 "옮길 수 없다" 가 된다 (실측). 그
       시험들의 덱은 ``1000`` · ``1500`` 같은 합성 ID 라서 저장소를 연결해도
       정의를 얻을 수 없다 — 고치려면 그 파일들의 판 구성을 실제 카드로
       바꿔야 하고, 그것은 이 Phase 의 범위를 크게 넘는다 (§3-1 · §14).

    최소 수정안은 §16-4 에 적었다. **이 시험이 그 자리를 가리킨다** — 공백이
    닫히는 날 이 시험이 먼저 깨진다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(SELF_TARGET, origin_zones=FIELD_ZONES)
    )
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    instance = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )
    #: 저장소 연결을 끊는다 — ``CardInstance.definition`` 이 들어 올린다.
    instance._repository = None
    with pytest.raises(RuntimeError):
        instance.definition

    #: 🔴 세 값 중 ``None`` 이다 — ``False`` 와 **구분된다.**
    assert EffectExecutor._is_extra_deck(instance) is None

    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        rulings=OPERATION_RULINGS,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            source=instance.instance_id,
        ),
    )
    #: 🔴 **지금은 통과한다.** 이것이 남은 공백이고, 바람직하다는 뜻이 아니다.
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(instance.instance_id).zone is Zone.HAND


def test_e07_the_production_duel_always_binds_a_repository():
    """
    🔴 **§16-4 의 전제를 센다** — production 경로에서는 정의를 읽을 수 있다.

    그래서 ``test_e06`` 의 공백이 **실제 듀얼에서는 닿지 않는다.** 그 사실이
    공백을 정당화하지는 않지만, 그 크기를 말해 준다.
    """
    #: ``Duel`` 은 ``GameState`` 를 받고, 그 판은 저장소로 만들어진다.
    create = ast.parse(source_of("engine/state/game_state.py"))
    factory = next(
        node
        for node in ast.walk(create)
        if isinstance(node, ast.FunctionDef) and node.name == "create"
    )
    #: 첫 인자가 저장소다 — 넘기지 않는 길이 **시험용**이라는 증거다.
    assert [a.arg for a in factory.args.args][:2] == ["cls", "repository"]

    #: 그리고 실제 듀얼을 만드는 테스트 경로가 그것을 넘긴다.
    duel_src = source_of("engine/duel.py")
    assert "state: GameState" in duel_src


# ======================================================================
# F. 일어나지 않은 이동 (§11-5)
# ======================================================================


@pytest.mark.real_card
def test_f01_a_card_already_in_the_destination_is_not_moved(repository):
    """
    🔴 **§11-5 — 실측으로 찾은 기록 결함.**

    구현 전: ``RESOLVED`` 였고 journal 에 ``#40 P0/HAND → P0/HAND
    (return_to_hand)`` 가 **성공한 이동으로** 적혔다. 적용된 것이 없는데
    기록이 생긴 것이다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    journal = EventJournal()
    result, state, instance = run(
        repository, definition, zone=Zone.HAND, journal=journal
    )

    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION, result.reason
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == MISSING_SAME_ZONE_MOVEMENT
    assert result.deltas == ()
    assert result.applied == ()
    assert journal.events == ()
    assert state.find_instance(instance.instance_id).zone is Zone.HAND


@pytest.mark.real_card
@pytest.mark.parametrize(
    "operation_kind, zone",
    [
        (OperationKind.SEND_TO_GRAVE, Zone.GRAVE),
        (OperationKind.BANISH, Zone.REMOVED),
        (OperationKind.RETURN_TO_DECK, Zone.DECK),
    ],
)
def test_f02_the_same_holds_for_every_movement(repository, operation_kind, zone):
    """같은 불변 조건이 **이동 전부**에 걸린다 — 패 되돌림만의 일이 아니다."""
    definition = definition_of(CardOperation(operation_kind, SELF_TARGET))
    journal = EventJournal()
    result, state, instance = run(
        repository, definition, zone=zone, journal=journal
    )
    assert result.status is ResolutionStatus.UNSUPPORTED_OPERATION, result.reason
    assert result.missing == MISSING_SAME_ZONE_MOVEMENT
    assert journal.events == ()
    assert state.find_instance(instance.instance_id).zone is zone


@pytest.mark.real_card
def test_f03_a_different_player_in_the_same_zone_is_a_real_move(repository):
    """
    🔴 **자리가 같아도 주인이 다르면 일어나는 일이다.**

    "같은 자리" 를 자리 이름만으로 보면 상대 패에 있는 카드를 주인의 패로
    되돌리는 이동이 사라진다. 자리와 주인을 **함께** 본다.

    🔴 관문을 **선언하지 않은** 조작으로 센다. 선언하면 판정 계층이 먼저
    멈추기 때문이고, 그것은 이 시험이 보려는 축이 아니다 — 상대 패의
    카드는 컨트롤러의 관측에서 **가려져** 있어 "패로 되돌릴 수 있는가" 에
    답할 수 없다 (``test_f04`` 가 그 사실을 따로 센다).
    """
    definition = definition_of(CardOperation.return_to_hand(SELF_TARGET))
    #: 소유자는 상대이고 지금은 내가 쥐고 있다 — 소유자의 패로 간다.
    result, state, instance = run(
        repository, definition, zone=Zone.HAND, owner=THEIRS, controller=MINE
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    after = state.find_instance(instance.instance_id)
    assert after.zone is Zone.HAND
    assert after.controller == THEIRS
    assert after.owner == THEIRS


@pytest.mark.real_card
def test_f04_a_hidden_card_cannot_be_judged(repository):
    """
    🔴 **§3-10 — 가려진 카드는 "모른다" 이고, 모르는 것은 허가가 아니다.**

    같은 판에서 관문을 **선언한** 조작은 멈춘다. 상대 패의 카드는
    컨트롤러의 관측에서 정체가 보이지 않으므로 (``GameStateView`` 가
    ``card_id`` 를 내보내지 않는다) 판정 계층이 답할 수 없다.

    6-M 이 이것을 바꾸지 않았다 — 거절의 **이유가 다르다**는 것을 적어
    둔다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(SELF_TARGET, gated=True)
    )
    journal = EventJournal()
    result, state, instance = run(
        repository,
        definition,
        zone=Zone.HAND,
        owner=THEIRS,
        controller=MINE,
        journal=journal,
    )
    assert result.status is ResolutionStatus.UNCHECKED_RULES, result.reason
    assert result.missing
    #: 🔴 6-M 의 두 거절과 **다른 이유**다.
    assert result.missing != MISSING_SAME_ZONE_MOVEMENT
    assert result.missing != MISSING_EXTRA_DECK_DESTINATION
    assert state.find_instance(instance.instance_id).zone is Zone.HAND
    assert journal.events == ()


# ======================================================================
# G. 거절은 계획 단계에서만 (§11-1 · ADR-008)
# ======================================================================


def test_g01_the_refusal_lives_in_the_planning_phase():
    """
    🔴 **ADR-008** — 비용을 치른 뒤 실패하는 구조를 만들지 않는다.

    AST 로 센다: ``_movement_refusal`` 을 부르는 자리가 ``_plan_*`` 안에만
    있고, ``_apply_*`` 안에는 없다.
    """
    tree = ast.parse(source_of("engine/effect/executor.py"))
    callers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if "_movement_refusal" in ast.unparse(node) and not node.name.startswith(
            "_movement_refusal"
        ):
            callers.append(node.name)
    assert callers == ["_plan_card_operation"], callers


def test_g02_the_refusal_reads_no_game_state():
    """
    계획 단계의 거절은 **카드 하나와 조작 하나**만 본다.

    ``GameState`` 를 읽으면 "계획이 읽은 판" 과 "적용이 바꾸는 판" 이
    어긋날 수 있다.
    """
    tree = ast.parse(source_of("engine/effect/executor.py"))
    refusal = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_movement_refusal"
    )
    assert [a.arg for a in refusal.args.args] == [
        "self",
        "operation",
        "card",
        "instance",
    ]
    body = ast.unparse(refusal)
    for forbidden in ("state.", "GameState", ".move(", "find_instance"):
        assert forbidden not in body, forbidden


# ======================================================================
# H. 비용에 의한 이동과 효과 해결에 의한 이동 (§8 · §10-H · §10-I)
# ======================================================================


def test_h01_the_cost_layer_moves_cards_for_two_reasons_only():
    """
    **§8 1 · 3** — 비용이 옮길 수 있는 것은 **버리기와 릴리스**뿐이다.

    둘 다 묘지로 가므로 :data:`MAIN_DECK_ONLY_ZONES` 와 겹치지 않는다 —
    그래서 6-M 의 도착 자리 거절이 비용 경로의 동작을 바꾸지 않는다.
    """
    assert set(COST_OPERATION.values()) == {
        OperationKind.DISCARD,
        OperationKind.RELEASE,
    }
    for kind in COST_OPERATION.values():
        assert DESTINATION[kind] is Zone.GRAVE
        assert DESTINATION[kind] not in MAIN_DECK_ONLY_ZONES
    assert len(SUPPORTED_COSTS) == 3  # 둘 + 라이프 지불


def test_h02_no_registered_effect_has_a_cost_today():
    """
    🔴 **§12 — 비용 이동 경로는 등재된 효과에서 도달하지 않는다.**

    그래서 6-M 은 ``engine/payment.py`` 를 고치지 않았다. 남은 공백은
    보고서 §16 에 적었다 — 숨기지 않고, 지어내지도 않는다.
    """
    with_cost = [
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if entry.definition.cost is not None and entry.definition.cost.costs
    ]
    assert with_cost == [], with_cost


def test_h03_the_executor_never_pays_a_cost():
    """
    🔴 **§8 2 — 해결 단계의 이동을 비용으로 적지 않는다.**

    지불은 ``EffectActivator.activate`` 의 일이고, 실행기는 지불기를 들고
    있지도 않다.
    """
    executor_src = source_of("engine/effect/executor.py")
    for forbidden in ("CostPayer", "_payer", "CostSemantics", "COST_OPERATION"):
        assert forbidden not in executor_src, forbidden

    activation_src = source_of("engine/activation.py")
    assert "self._payer.pay(" in activation_src


@pytest.mark.real_card
def test_h04_an_effect_move_is_recorded_as_the_effect_kind(repository):
    """
    **§10-I · §11-5** — 효과 해결로 일어난 이동은 **그 효과의 종류**로
    적힌다. 비용의 종류로 섞이지 않는다.
    """
    definition = definition_of(
        CardOperation.return_to_hand(
            SELF_TARGET, gated=True, origin_zones=FIELD_ZONES
        )
    )
    journal = EventJournal()
    result, state, instance = run(repository, definition, journal=journal)
    assert result.status is ResolutionStatus.RESOLVED, result.reason

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert delta.movement is OperationKind.RETURN_TO_HAND
    assert delta.movement not in set(COST_OPERATION.values())
    assert delta.source_zone is Zone.MZONE
    assert delta.destination_zone is Zone.HAND
    assert len(journal.events) == 1
    assert journal.events[0].effect_ref == definition.effect_ref


# ======================================================================
# I. 상태와 기록의 일관성 (§11)
# ======================================================================


@pytest.mark.real_card
def test_i01_one_card_moves_and_the_others_do_not(repository):
    """**§10-C · §11-3** — 같은 카드 ID 셋 중 **발동한 쪽만** 움직인다."""
    definition = definition_registry().definition_for(HONEST_REF)
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    placed = [
        state.create_instance(HONEST, owner=MINE, zone=Zone.MZONE,
                              position=Position.FACEUP)
        for _ in range(3)
    ]
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((HONEST_REF,)),
        rulings=OPERATION_RULINGS,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=HONEST_REF, controller=MINE, source=placed[1].instance_id
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    zones = [state.find_instance(p.instance_id).zone for p in placed]
    assert zones == [Zone.MZONE, Zone.HAND, Zone.MZONE]
    assert len(state.player(MINE).hand) == 1


@pytest.mark.real_card
def test_i02_the_zone_counts_stay_consistent(repository):
    """**§11-6** — 이동 뒤 양쪽 존의 장수가 맞는다."""
    definition = definition_registry().definition_for(HONEST_REF)
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    instance = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP
    )
    before_hand = len(state.player(MINE).hand)
    before_field = len(state.player(MINE).zones[Zone.MZONE])

    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((HONEST_REF,)),
        rulings=OPERATION_RULINGS,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=HONEST_REF, controller=MINE, source=instance.instance_id
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert len(state.player(MINE).hand) == before_hand + 1
    assert len(state.player(MINE).zones[Zone.MZONE]) == before_field - 1
    #: 출처 정보가 남는다 (§11-7).
    after = state.find_instance(instance.instance_id)
    assert after.previous.location is Zone.MZONE


@pytest.mark.real_card
def test_i03_a_refused_move_leaves_the_state_hash_untouched(repository):
    """
    🔴 **§11-1** — 거절되면 판이 **비트 단위로** 그대로다.

    "카드 위치가 같다" 보다 센 단언이다 — 다른 칸이 조용히 바뀌는 것까지
    잡는다.
    """
    definition = definition_registry().definition_for(HONEST_REF)
    deck = [FEATHERMAN] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    instance = state.create_instance(
        HONEST, owner=MINE, zone=Zone.GRAVE, position=Position.FACEUP
    )
    before = state.state_hash()

    journal = EventJournal()
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((HONEST_REF,)),
        rulings=OPERATION_RULINGS,
        journal=journal,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=HONEST_REF, controller=MINE, source=instance.instance_id
        ),
    )
    assert result.status is ResolutionStatus.INVALID_TARGET, result.reason
    assert state.state_hash() == before
    assert journal.events == ()


# ======================================================================
# J. 토큰 (§7-D · §10-F)
# ======================================================================


def test_j01_tokens_are_not_in_the_engine_at_all(repository):
    """
    🔴 **§10-F — 토큰은 이 엔진에 들어올 수 없다.** 측정이고 추측이 아니다.

    ``cards.cdb`` 에 241장이 있는데 저장소가 **하나도 싣지 않는다**
    (``OfficialDatabaseSource.iter_cards(include_tokens=False)`` 가 기본값
    이고, production 에서 ``True`` 를 넘기는 자리가 없다).

    그러므로 "토큰이 패에 남지 않게 한다" 는 **지금 고칠 수 있는 결함이
    아니다.** 토큰 인스턴스를 만들 수조차 없다. 데이터 파이프라인을
    바꾸는 일은 이번 범위가 아니므로 (§3-18) 미지원으로 보존하고 센다.
    """
    import sqlite3

    import core.constants as C
    from tests.conftest import CARDS_CDB

    connection = sqlite3.connect(f"file:{CARDS_CDB}?mode=ro", uri=True)
    try:
        (in_db,) = connection.execute(
            "SELECT COUNT(*) FROM datas WHERE type & ? != 0", (C.TYPE_TOKEN,)
        ).fetchone()
    finally:
        connection.close()
    assert in_db > 200, in_db

    loaded = [
        card
        for card in repository.all_cards()
        if card.type_mask & C.TYPE_TOKEN
    ]
    assert loaded == [], len(loaded)

    #: production 에서 토큰을 켜는 자리가 없다.
    source = source_of("sources/official_db.py")
    assert "include_tokens: bool = False" in source
    for module in ("core/card_repository.py", "engine/state/game_state.py"):
        assert "include_tokens=True" not in source_of(module)


# ======================================================================
# K. 금지 사항과 범위 (§3 · §14)
# ======================================================================


def test_k01_no_new_operation_kind_and_no_new_destination():
    """**§3-4 · §9** — 새 이동 시스템을 만들지 않았다."""
    assert [k.value for k in OperationKind] == [
        "destroy",
        "send_to_grave",
        "banish",
        "release",
        "discard",
        "return_to_hand",
        "return_to_deck",
        "special_summon",
        "draw",
        "change_life",
        "shuffle",
        "move",
        "unknown",
    ]
    assert MOVABLE_DESTINATIONS == frozenset(
        {Zone.GRAVE, Zone.REMOVED, Zone.HAND, Zone.DECK}
    )


def test_k02_the_library_grew_no_executable_entry():
    """
    🔴 **§12 — 6-M 은 실행 범위를 넓히지 않았다.** 정확성만 바꿨다.

    등재 17건 · 실행 가능 14건은 6-L 과 같다. 그 사실을 그대로 적는다.

    🔴 **Phase 6-V 가 둘 다 하나씩 늘렸다** (18 · 15). 6-M 이 범위를 넓히지
    않았다는 사실은 그대로이고, 넓힌 것은 6-V 다 — 기르수 ① 하나.
    """
    #: Phase 6-AC 가 성유물－『성장』 ① 을 더했다 (18 → 19).
    assert len(EFFECT_LIBRARY) == 19
    #: Phase 6-AC — 성유물－『성장』 ① 이 실행 가능으로 더해졌다 (15 → 16).
    assert sum(1 for entry in EFFECT_LIBRARY if entry.executable) == 16


def test_k03_only_one_registered_operation_declares_its_origin():
    """
    🔴 **§12-4** — 자리를 적은 등재 조작은 **어니스트 ① 하나**다.

    나머지는 공식 텍스트가 자리를 말하지 않았거나 아직 읽지 않았다.
    적지 않은 것을 적은 것처럼 세지 않는다.
    """
    declared = [
        (entry.definition.effect_ref, operation.kind, operation.origin_zones)
        for entry in EFFECT_LIBRARY
        for operation in entry.definition.operations
        if getattr(operation, "origin_zones", None) is not None
    ]
    assert declared == [
        (HONEST_REF, OperationKind.RETURN_TO_HAND, FIELD_ZONES)
    ], declared


def test_k04_the_pot_of_greed_path_is_untouched(repository):
    """**§3-1** — 기존 ``ACTIVATE`` 효과의 실행이 그대로다."""
    definition = definition_registry().definition_for(EffectRef(POT_OF_GREED, 0))
    assert definition is not None
    assert [op.kind for op in definition.operations] == [OperationKind.DRAW]
    for operation in definition.operations:
        assert getattr(operation, "origin_zones", None) is None
