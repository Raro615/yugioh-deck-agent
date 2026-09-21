"""
Phase 2-X — 묘지로 보내기 · 버리기의 규칙 관문 (rule gate).

Phase 2-W 의 전수 조사가 실제 카드 실행을 막는 가장 큰 구조적 원인 중
하나로 **관문 계층의 부재**를 지목했다. 이 파일은 그 관문 중
``SEND_TO_GRAVE`` · ``DISCARD`` 계열을 다룬다.

    Lua 술어 (Card.IsAbleToGrave · Card.IsDiscardable)
      → CardOperation.gated        효과가 **선언**한다
      → MovementRuling             세 값으로 답한다
      → EffectExecutor 관문         TRUE 일 때만 지나간다
      → GameState → StateDelta → ObservedEvent → TimingEvent

이 파일은 **두 종류의 테스트를 한 파일에 담되 섞지 않는다.**

``@pytest.mark.real_card`` 가 붙은 것만 실제 카드의 의미를 주장한다.
나머지는 synthetic 이고, 관문 **기계장치**의 모양만 시험한다 — 아무 카드의
규칙도 주장하지 않는다 (Phase 2-X §18).

    pytest tests/engine/test_rule_gate_grave_discard.py -m real_card
    pytest tests/engine/test_rule_gate_grave_discard.py -m "not real_card"
"""

import pathlib
import re

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolver
from engine.condition import ConditionResult, IsMonster, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, CostGroup, Selection
from engine.effect.definition import (
    EffectDefinition,
    EffectProvenance,
    ExecutionAvailability,
)
from engine.effect.delta import ZoneMoved
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    FINE,
    FOOLISH_BURIAL,
    SELF_MUMMIFICATION,
    availability,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import (
    DECLARABLE_GATE_KINDS,
    CardOperation,
    OperationKind,
)
from engine.effect.resolution import (
    ResolutionContext,
    ResolutionStatus,
    TargetSelection,
)
from engine.effect.semantics import (
    DECLARED_GATE_RULINGS,
    GATING_RULES,
    LUA_GATE_PREDICATES,
    MISSING_GATE,
    RULE_GATED,
    UNASKED_QUESTIONS,
    DeclaredMovementRuling,
    MovementRuling,
    RuleQuestion,
    UnknownMovementRuling,
    ask_movement,
    declared_gate_question,
)
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import TimingPoint
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone, zone_visibility

from tests.conftest import requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
FEATHERMAN = 21844576
LAB = 999001  # synthetic 정의의 자리. 실제 카드 번호가 아니다.
GRANTED = ValidationResult.valid()


# ======================================================================
# A. 실제 Lua 조사 (§2) — 추측하지 않고 파일을 읽는다
# ======================================================================


def _scripts() -> list[pathlib.Path]:
    return sorted(ROOT.glob("c*.lua"))


def _cards_using(name: str) -> set[str]:
    """그 술어를 쓰는 스크립트 이름들. ``AsCost`` 변종은 **다른 술어**다."""
    pattern = re.compile(rf"\b{name}\b(?!AsCost)")
    return {p.name for p in _scripts() if pattern.search(p.read_text("utf-8", errors="replace"))}


def test_a_the_predicate_names_we_guessed_do_not_exist():
    """
    §2 — "정확한 함수명은 추측하지 말고 실제 repository 의 Lua 를 기준으로
    확인한다."

    그래서 확인했고, **세 개는 존재하지 않았다.** 이름만 그럴듯한 것을
    구현했다면 아무 카드와도 이어지지 않았을 것이다.
    """
    for imagined in ("IsAbleToDiscard", "IsCanBeGrave", "IsCanBeDiscarded"):
        assert _cards_using(imagined) == set(), imagined

    # 실제로 쓰이는 이름은 이 둘이다.
    assert len(_cards_using("IsAbleToGrave")) > 400
    assert len(_cards_using("IsDiscardable")) > 400


def test_a_the_engine_only_names_predicates_that_exist():
    """엔진이 근거로 적은 술어 이름이 **전부 코퍼스에 있다.**"""
    for question, predicate in LUA_GATE_PREDICATES.items():
        bare = predicate.removeprefix("Card.")
        assert _cards_using(bare), (question, predicate)


def test_a_sending_to_grave_and_discarding_are_different_questions():
    """
    §2 — A 와 B 를 하나의 boolean 으로 합치지 않는 근거는 **추론이 아니라
    관측**이다.
    """
    grave = _cards_using("IsAbleToGrave")
    discard = _cards_using("IsDiscardable")

    # 같은 질문이라면 한쪽만 쓰는 카드가 이렇게 많을 수 없다.
    assert len(grave - discard) > 400
    assert len(discard - grave) > 400
    assert len(grave & discard) < 50

    # 결정적인 증거: 한 줄에서 **둘 다** 묻는 카드가 있다.
    both = [
        line.strip()
        for name in sorted(grave & discard)
        for line in (ROOT / name).read_text("utf-8", errors="replace").splitlines()
        if "IsDiscardable" in line and "IsAbleToGrave" in line
    ]
    assert both, "둘을 한 줄에서 함께 묻는 카드를 찾지 못했습니다"
    assert any("IsDiscardable" in line and "IsAbleToGrave" in line for line in both)


def test_a_the_same_operation_is_gated_in_one_card_and_not_in_another():
    """
    **이 테스트가 이번 Phase 의 설계 근거다.**

    육신보살과 어리석은 매장은 둘 다 ``Duel.SendtoGrave`` 를 부른다.
    한쪽은 후보 조건이 ``nil`` 이고 다른 쪽은 ``IsAbleToGrave`` 다.
    그러므로 관문은 **종류(OperationKind)가 아니라 카드가 선언한다.**
    """
    mummify = (ROOT / "c15103313.lua").read_text("utf-8")
    burial = (ROOT / "c81439173.lua").read_text("utf-8")

    assert "Duel.SendtoGrave" in mummify and "Duel.SendtoGrave" in burial
    assert "IsAbleToGrave" not in mummify
    assert "Duel.SelectTarget(tp,nil," in mummify  # 필터가 nil 이다
    assert "IsAbleToGrave" in burial


def test_a_no_reachable_real_card_gets_past_the_grave_gate_today():
    """
    §7 의 정직한 결과. ``IsAbleToGrave`` 를 선언하면서 이 엔진이 닿을 수
    있는 카드(발동형 · 단일 효과 · 비용 없음 · 횟수 제한 없음 · 별도 조건
    없음)는 **전부 덱이나 엑스트라 덱에서 보낸다.**

    덱은 이 엔진의 관측 모델에서 ``HIDDEN`` 이다. 그래서 관문에 닿기
    전에 대상 판정에서 먼저 멈춘다 — 관문이 유일한 막이 아니다.
    """
    assert zone_visibility(Zone.DECK).value == "hidden"
    assert zone_visibility(Zone.EXTRA).value == "owner_only"

    reachable = []
    for path in _scripts():
        text = path.read_text("utf-8", errors="replace")
        if not re.search(r"\bIsAbleToGrave\b(?!AsCost)", text):
            continue
        if "EFFECT_TYPE_ACTIVATE" not in text or "EVENT_FREE_CHAIN" not in text:
            continue
        if len(set(re.findall(r"local (e\d+)=Effect\.CreateEffect", text))) != 1:
            continue
        if any(m in text for m in ("SetCost", "SetCountLimit", "SetCondition")):
            continue
        reachable.append((path.name, set(re.findall(r"LOCATION_[A-Z]+", text))))

    assert reachable, "조사 대상이 비어 있습니다"
    for name, zones in reachable:
        assert zones & {"LOCATION_DECK", "LOCATION_EXTRA"}, name


def test_a_no_reachable_real_card_declares_the_discard_gate():
    """
    §6 의 정직한 결과. ``IsDiscardable`` 을 쓰는 537장은 **전부** 몬스터
    효과이거나, 효과가 여럿이거나, 비용이다. 이 엔진이 닿는 발동형 마법 /
    함정 중에는 **하나도 없다.**

    그래서 DISCARD 관문에는 실제 카드가 붙지 않았다. 없는 것을 있는 척
    만들지 않는다 — 이 테스트가 그 사실을 고정한다.
    """
    reachable = []
    for path in _scripts():
        text = path.read_text("utf-8", errors="replace")
        if not re.search(r"\bIsDiscardable\b", text):
            continue
        if "EFFECT_TYPE_ACTIVATE" not in text or "EVENT_FREE_CHAIN" not in text:
            continue
        if len(set(re.findall(r"local (e\d+)=Effect\.CreateEffect", text))) != 1:
            continue
        if any(m in text for m in ("SetCost", "SetCountLimit", "SetCondition")):
            continue
        reachable.append(path.name)

    assert reachable == []


# ======================================================================
# B. 네 질문을 합치지 않는다 (§2)
# ======================================================================


def test_b_the_four_questions_are_four_values():
    """A · B · C · D 가 각각 이름을 갖는다."""
    assert {q.value for q in RuleQuestion} == {
        "may_be_sent_to_grave",  # A
        "may_be_discarded",  # B
        "may_be_targeted",  # C
        "operation_possible",  # D
    }
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE is not RuleQuestion.MAY_BE_DISCARDED


def test_b_the_ruling_has_a_separate_method_for_each_question():
    """
    하나의 ``may_be_moved(kind, instance)`` 로 합치지 않았다. 합치면
    구현하는 쪽이 "둘 다 같은 답" 을 내놓기 쉬워진다.
    """
    for name in ("may_be_sent_to_grave", "may_be_discarded"):
        assert hasattr(UnknownMovementRuling, name), name
    assert not hasattr(UnknownMovementRuling, "may_be_moved")
    assert isinstance(UnknownMovementRuling(), MovementRuling)


def test_b_one_card_can_be_confirmed_for_one_question_and_unknown_for_the_other():
    """
    **네 집합인 이유다.** "묘지로는 보낼 수 있지만 버릴 수 있는지는
    모른다" 를 적을 수 있어야 한다.
    """
    card = InstanceId(1)
    ruling = DeclaredMovementRuling(sendable=frozenset({card}))

    assert ruling.may_be_sent_to_grave(card) is ConditionResult.TRUE
    assert ruling.may_be_discarded(card) is ConditionResult.UNKNOWN


def test_b_a_card_cannot_be_both_allowed_and_forbidden():
    card = InstanceId(1)
    with pytest.raises(ValueError, match="묘지로 보내기"):
        DeclaredMovementRuling(
            sendable=frozenset({card}), unsendable=frozenset({card})
        )
    with pytest.raises(ValueError, match="버리기"):
        DeclaredMovementRuling(
            discardable=frozenset({card}), undiscardable=frozenset({card})
        )


def test_b_asking_routes_to_the_matching_method():
    """``ask_movement`` 가 두 질문을 섞지 않는 유일한 통로다."""
    card = InstanceId(1)
    ruling = DeclaredMovementRuling(
        sendable=frozenset({card}), undiscardable=frozenset({card})
    )

    assert ask_movement(
        ruling, RuleQuestion.MAY_BE_SENT_TO_GRAVE, card
    ) is ConditionResult.TRUE
    assert ask_movement(
        ruling, RuleQuestion.MAY_BE_DISCARDED, card
    ) is ConditionResult.FALSE
    with pytest.raises(ValueError):
        ask_movement(ruling, RuleQuestion.MAY_BE_TARGETED, card)


def test_b_the_unasked_question_is_written_down_not_left_blank():
    """
    C(대상 지정 가능성)는 아직 아무도 묻지 않는다. **빈 칸으로 두지
    않는다** — 빈 칸은 "없다" 로 읽히고 적어 둔 것은 "아직" 으로 읽힌다.
    """
    assert RuleQuestion.MAY_BE_TARGETED in UNASKED_QUESTIONS
    assert "IsCanBeEffectTarget" in UNASKED_QUESTIONS[RuleQuestion.MAY_BE_TARGETED]
    assert RuleQuestion.MAY_BE_TARGETED not in DECLARED_GATE_RULINGS.values()


def test_b_destruction_is_not_widened_into_this_phase():
    """
    §6 — 파괴는 이번 범위가 아니다. 종류로 거는 관문은 **둘 그대로**이고,
    이동 판정기는 파괴에 답하지 않는다.
    """
    assert RULE_GATED == frozenset(
        {OperationKind.DESTROY, OperationKind.SPECIAL_SUMMON}
    )
    assert OperationKind.DESTROY not in DECLARED_GATE_RULINGS
    assert OperationKind.DESTROY not in DECLARABLE_GATE_KINDS
    assert not hasattr(UnknownMovementRuling, "may_be_destroyed")


# ======================================================================
# C. 선언 — 관문은 카드가 말한다
# ======================================================================


def test_c_an_operation_declares_its_own_gate():
    plain = CardOperation.send_to_grave(PRIMARY_TARGET)
    gated = CardOperation.send_to_grave(PRIMARY_TARGET, gated=True)

    assert plain.gated is False
    assert gated.gated is True
    assert declared_gate_question(plain) is None
    assert declared_gate_question(gated) is RuleQuestion.MAY_BE_SENT_TO_GRAVE
    assert declared_gate_question(
        CardOperation.discard(PRIMARY_TARGET, gated=True)
    ) is RuleQuestion.MAY_BE_DISCARDED


def test_c_not_declaring_is_the_default():
    """
    **적지 않은 것을 "관문이 있다" 로 읽지 않는다.** 기본값이 거짓인 이유는
    실제로 묻지 않는 카드가 있기 때문이다 (육신보살).
    """
    for factory in (
        CardOperation.send_to_grave,
        CardOperation.discard,
        CardOperation.banish,
        CardOperation.destroy,
    ):
        assert factory(PRIMARY_TARGET).gated is False


def test_c_only_the_two_kinds_may_declare_a_gate():
    """파괴 · 특수 소환은 선언과 무관하게 언제나 판정을 받는다."""
    assert DECLARABLE_GATE_KINDS == frozenset(
        {OperationKind.SEND_TO_GRAVE, OperationKind.DISCARD}
    )
    for kind in (
        OperationKind.DESTROY,
        OperationKind.BANISH,
        OperationKind.RELEASE,
        OperationKind.RETURN_TO_HAND,
        OperationKind.RETURN_TO_DECK,
    ):
        with pytest.raises(ValueError, match="선언하는 것이 아닙니다"):
            CardOperation(kind, PRIMARY_TARGET, gated=True)


def test_c_the_declaration_survives_in_the_canonical_form():
    """선언이 정규 표현과 직렬화에 남는다 — 결정론과 재현을 위해서."""
    plain = CardOperation.send_to_grave(PRIMARY_TARGET)
    gated = CardOperation.send_to_grave(PRIMARY_TARGET, gated=True)

    assert plain.canonical_state() != gated.canonical_state()
    assert gated.to_dict()["gated"] is True
    assert "gated" not in plain.to_dict()
    # **의미는 그대로다.** 관문을 선언했다고 다른 종류가 되지 않는다.
    assert plain.kind is gated.kind is OperationKind.SEND_TO_GRAVE
    assert plain.reason_names == gated.reason_names


def test_c_the_gate_tables_cover_both_questions():
    for kind in DECLARABLE_GATE_KINDS:
        assert kind in GATING_RULES
        assert kind in MISSING_GATE
        assert kind in DECLARED_GATE_RULINGS
    assert "IsAbleToGrave" in MISSING_GATE[OperationKind.SEND_TO_GRAVE]
    assert "IsDiscardable" in MISSING_GATE[OperationKind.DISCARD]


# ======================================================================
# synthetic 판 — **아무 카드의 의미도 주장하지 않는다**
# ======================================================================


def new_state(repository) -> GameState:
    """p0 MZONE·GRAVE·HAND 에 페더맨. p1 도 마찬가지 (패는 가려짐)."""
    game = GameState.create(
        repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20)
    )
    game.draw(MINE, 6)
    game.draw(THEIRS, 4)
    for _ in range(2):  # 몬스터 **두 장** — 부분 적용을 시험하려면 필요하다
        game.move(
            game.player(MINE).hand[0], Zone.MZONE, to_player=MINE,
            position=Position.FACEUP_ATTACK,
        )
    game.move(game.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)
    game.move(
        game.player(THEIRS).hand[0], Zone.MZONE, to_player=THEIRS,
        position=Position.FACEUP_ATTACK,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state(repository) -> GameState:
    return new_state(repository)


def my_monster(state: GameState) -> InstanceId:
    return state.player(MINE).monster_zone[0].instance_id


def my_hand(state: GameState) -> InstanceId:
    return state.player(MINE).hand[0].instance_id


def their_hand(state: GameState) -> InstanceId:
    return state.player(THEIRS).hand[0].instance_id


def synthetic(operation, *, zones, ordinal: int = 0) -> EffectDefinition:
    """
    **synthetic 정의.** 출처가 ``hand_written`` 이라고 적혀 있고, 관문
    기계장치의 모양만 시험한다.
    """
    return EffectDefinition(
        effect_ref=EffectRef(LAB, ordinal),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.choosing(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset(zones),
                        owner=PlayerRef.CONTROLLER,
                        require=IsMonster(),
                    )
                )
            )
        ),
        operations=(operation,),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-X 관문 시험"
        ),
    )


def run(state, definition, *chosen, movement=None, journal=None):
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        journal=journal,
        movement=movement,
    )
    return executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref,
            controller=MINE,
            selections=(
                (TargetSelection(PRIMARY_TARGET, Selection(chosen=tuple(chosen))),)
                if chosen
                else ()
            ),
        ),
    )


GRAVE_CASE = ("send_to_grave", Zone.MZONE)
DISCARD_CASE = ("discard", Zone.HAND)


def _case(name, gated: bool):
    if name == "send_to_grave":
        return synthetic(
            CardOperation.send_to_grave(PRIMARY_TARGET, gated=gated),
            zones=(Zone.MZONE,),
            ordinal=0 if gated else 1,
        )
    return synthetic(
        CardOperation.discard(PRIMARY_TARGET, gated=gated),
        zones=(Zone.HAND,),
        ordinal=2 if gated else 3,
    )


def _pick(state, name):
    return my_monster(state) if name == "send_to_grave" else my_hand(state)


def _allow(name, card):
    return (
        DeclaredMovementRuling(sendable=frozenset({card}))
        if name == "send_to_grave"
        else DeclaredMovementRuling(discardable=frozenset({card}))
    )


def _refuse(name, card):
    return (
        DeclaredMovementRuling(unsendable=frozenset({card}))
        if name == "send_to_grave"
        else DeclaredMovementRuling(undiscardable=frozenset({card}))
    )


# ======================================================================
# D. 관문의 세 값 (§4 · §5 · §8) — synthetic
# ======================================================================


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_d_unknown_stops_before_any_mutation(state, name):
    """
    §8-D — 판정기가 없으면 **판을 건드리기 전에** 멈춘다.
    ``UNKNOWN`` 을 허가로 바꾸지 않는다.
    """
    card = _pick(state, name)
    before = state.state_hash()
    journal = EventJournal()

    result = run(state, _case(name, gated=True), card, journal=journal)

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing == MISSING_GATE[OperationKind(name)]
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    assert len(journal) == 0


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_d_a_refusal_is_not_the_same_as_not_knowing(state, name):
    """
    §4 — "명백히 불가능함" 과 "허용되는지 모름" 이 **다른 답**이다.
    합치면 "규칙상 안 된다" 와 "아직 안 옮겼다" 가 한 덩어리가 된다.
    """
    card = _pick(state, name)
    before = state.state_hash()

    refused = run(state, _case(name, gated=True), card, movement=_refuse(name, card))
    unknown = run(state, _case(name, gated=True), card)

    assert refused.status is ResolutionStatus.INVALID_TARGET
    assert refused.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert unknown.status is ResolutionStatus.UNCHECKED_RULES
    assert (refused.status, refused.code) != (unknown.status, unknown.code)
    # 둘 다 판을 건드리지 않는다.
    assert refused.applied == () and unknown.applied == ()
    assert state.state_hash() == before


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_d_a_confirmed_ruling_lets_it_through(state, name):
    """§8-A · §8-E — 허용되면 실제로 옮겨지고 판이 달라진다."""
    card = _pick(state, name)
    before = state.state_hash()

    result = run(state, _case(name, gated=True), card, movement=_allow(name, card))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.applied != ()
    assert result.deltas != ()
    assert state.state_hash() != before
    assert state.locate(card).zone is Zone.GRAVE


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_d_an_undeclared_operation_never_asks(state, name):
    """
    관문을 **선언하지 않은** 같은 종류의 일은 판정기 없이도 지나간다.
    원본 스크립트가 묻지 않기 때문이다 (육신보살 · 벌금).
    """
    card = _pick(state, name)

    result = run(state, _case(name, gated=False), card)

    assert result.status is ResolutionStatus.RESOLVED
    assert state.locate(card).zone is Zone.GRAVE


def test_d_the_two_questions_do_not_answer_for_each_other(state):
    """
    §5 — "DISCARD 는 SEND_TO_GRAVE 와 같다" 고 가정하지 않는다.
    묘지로 보내기를 허가해도 **버리기는 여전히 모른다.**
    """
    monster = my_monster(state)
    hand = my_hand(state)
    ruling = DeclaredMovementRuling(sendable=frozenset({monster, hand}))
    before = state.state_hash()

    sent = run(state, _case("send_to_grave", gated=True), monster, movement=ruling)
    assert sent.status is ResolutionStatus.RESOLVED

    board = state.state_hash()
    discarded = run(state, _case("discard", gated=True), hand, movement=ruling)

    assert discarded.status is ResolutionStatus.UNCHECKED_RULES
    assert state.state_hash() == board
    assert before != board


# ======================================================================
# E. 의미 보존 · Event pipeline (§13 · §14) — synthetic
# ======================================================================


@pytest.mark.parametrize(
    "name,movement_kind",
    [("send_to_grave", OperationKind.SEND_TO_GRAVE), ("discard", OperationKind.DISCARD)],
)
def test_e_the_operation_keeps_its_identity_through_the_gate(
    state, name, movement_kind
):
    """
    §14 — 관문을 공유해도 ``OperationKind`` 의 의미는 유지된다. 목적지가
    둘 다 묘지인데도 ``ZoneMoved.movement`` 가 다르다 (ADR-002).
    """
    card = _pick(state, name)

    result = run(state, _case(name, gated=True), card, movement=_allow(name, card))
    (delta,) = [d for d in result.deltas if isinstance(d, ZoneMoved)]

    assert delta.movement is movement_kind
    assert delta.destination_zone is Zone.GRAVE
    assert result.applied[0].kind is movement_kind
    assert result.applied[0].reason_names == (
        ("EFFECT",) if name == "send_to_grave" else ("DISCARD", "EFFECT")
    )


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_e_a_gated_success_uses_the_existing_event_path(state, name):
    """
    §13 — 새 EventBus 를 만들지 않았다. 기존
    ``StateDelta → EventReader → ObservedEvent → TimingEvent`` 를 지난다.
    """
    card = _pick(state, name)
    journal = EventJournal()

    result = run(
        state,
        _case(name, gated=True),
        card,
        movement=_allow(name, card),
        journal=journal,
    )
    observed = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        result, actor=MINE
    )

    assert [event.timing.point for event in observed] == [TimingPoint.CARD_MOVED]
    assert all(event.event_id for event in observed)
    assert len(journal) == 1


# ======================================================================
# F. 실패 안전성 (§12) — synthetic
# ======================================================================


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
def test_f_every_gate_failure_leaves_everything_alone(state, name):
    """
    §12 — 판정 실패는 **mutation 전에** 일어난다. 판도 · 사건도 · 기록도
    달라지지 않는다.
    """
    card = _pick(state, name)
    cases = {
        "UNCHECKED_RULES": lambda j: run(
            state, _case(name, gated=True), card, journal=j
        ),
        "MISSING_GATE 거절": lambda j: run(
            state, _case(name, gated=True), card,
            movement=_refuse(name, card), journal=j,
        ),
        "가려진 대상": lambda j: run(
            state, _case(name, gated=True), their_hand(state),
            movement=_allow(name, card), journal=j,
        ),
        "안 고름": lambda j: run(
            state, _case(name, gated=True), movement=_allow(name, card), journal=j
        ),
        "없는 카드": lambda j: run(
            state, _case(name, gated=True), InstanceId(9999),
            movement=_allow(name, card), journal=j,
        ),
    }

    answers = {}
    for label, invoke in cases.items():
        journal = EventJournal()
        before = state.state_hash()
        result = invoke(journal)

        assert result.status is not ResolutionStatus.RESOLVED, label
        assert result.applied == (), label
        assert result.deltas == (), label
        assert state.state_hash() == before, label
        assert len(journal) == 0, label
        observed = EventReader(
            GameStateView.from_state(state, viewer=MINE)
        ).read(result, actor=MINE)
        assert observed == (), label
        answers[label] = (result.status, result.code)

    # 다섯 갈래가 한 답으로 뭉개지지 않는다.
    assert len(set(answers.values())) >= 3


@pytest.mark.parametrize(
    "name,zone,operation",
    [
        ("send_to_grave", Zone.MZONE, CardOperation.send_to_grave),
        ("discard", Zone.HAND, CardOperation.discard),
    ],
)
def test_f_the_gate_never_partially_applies(state, name, zone, operation):
    """
    두 장 중 한 장만 판정을 받으면 **한 장도** 옮겨지지 않는다.
    계획이 전부 끝난 뒤에야 적용이 시작된다 (STRUCTURAL-49 그대로).
    """
    cards = [card.instance_id for card in state.player(MINE).zone(zone)[:2]]
    assert len(cards) == 2, zone
    definition = EffectDefinition(
        effect_ref=EffectRef(LAB, 9),
        source_card_id=LAB,
        targets=TargetBinding.single(
            TargetSpec.choosing(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({zone}), owner=PlayerRef.CONTROLLER
                    ),
                    minimum=2,
                    maximum=2,
                )
            )
        ),
        operations=(operation(PRIMARY_TARGET, gated=True),),
        cost=CostGroup(),
        provenance=EffectProvenance.hand_written(
            verified=True, note="Phase 2-X 관문 시험"
        ),
    )
    before = state.state_hash()

    result = run(
        state,
        definition,
        *cards,
        # **한 장만** 확인되었다.
        movement=_allow(name, cards[0]),
    )

    assert result.status is ResolutionStatus.UNCHECKED_RULES
    assert result.applied == ()
    assert result.deltas == ()
    assert state.state_hash() == before
    for card in cards:
        assert state.locate(card).zone is zone


# ======================================================================
# G. 숨은 정보 (§9) — synthetic
# ======================================================================


def test_g_a_hidden_card_is_unknown_not_absent(state):
    """
    §9 — 상대 패의 카드를 고르면 "없다" 가 아니라 "모른다" 다.
    ``viewer`` 는 결정하는 자리(MINE)다.
    """
    hidden = their_hand(state)
    identity = state.find_instance(hidden).card_id

    result = run(
        state,
        _case("discard", gated=True),
        hidden,
        movement=DeclaredMovementRuling(discardable=frozenset({hidden})),
    )

    assert result.status is ResolutionStatus.UNCHECKED_TARGET
    assert result.code is ValidationCode.HIDDEN_CARD
    rendered = repr(result.to_dict()) + (result.reason or "")
    assert str(identity) not in rendered


def test_g_the_gate_is_asked_after_the_target_check_not_before(state):
    """
    순서가 규칙이다. 관문이 먼저 물어지면 **판정기가 상대 패의 카드를 아는
    척**하게 된다 — 가려진 카드에 대해 ``TRUE`` 를 돌려주는 판정기를 줘도
    결과는 ``HIDDEN_CARD`` 여야 한다.
    """
    hidden = their_hand(state)

    result = run(
        state,
        _case("discard", gated=True),
        hidden,
        movement=DeclaredMovementRuling(discardable=frozenset({hidden})),
    )

    assert result.code is ValidationCode.HIDDEN_CARD
    assert result.code is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# H. 결정론 (§10) — synthetic
# ======================================================================


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
@requires_official_db
def test_h_the_gate_is_deterministic(repository, name):
    first, second = new_state(repository), new_state(repository)
    left_card, right_card = _pick(first, name), _pick(second, name)

    left = run(first, _case(name, gated=True), left_card, movement=_allow(name, left_card))
    right = run(
        second, _case(name, gated=True), right_card, movement=_allow(name, right_card)
    )

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


@pytest.mark.parametrize("name", ["send_to_grave", "discard"])
@requires_official_db
def test_h_an_unknown_gate_is_deterministic_too(repository, name):
    first, second = new_state(repository), new_state(repository)

    left = run(first, _case(name, gated=True), _pick(first, name))
    right = run(second, _case(name, gated=True), _pick(second, name))

    assert left.canonical_state() == right.canonical_state()
    assert first.state_hash() == second.state_hash()


def test_h_no_ai_judgement_entered_the_gate():
    """
    §11 — 엔진은 "가능한가" 만 답한다. "무엇을 고를 것인가" 는 AI 의
    영역이고, 관문 코드에 들어오지 않았다.
    """
    import ast

    source = (ROOT / "engine" / "effect" / "semantics.py").read_text("utf-8")
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    for forbidden in ("choose", "select", "score", "policy", "best", "prefer"):
        assert not any(forbidden in name.lower() for name in names), forbidden
    assert "random" not in source


# ======================================================================
# I. 실제 카드 (§8) — 여기서부터만 카드의 의미를 주장한다
# ======================================================================


@pytest.mark.real_card
def test_i_foolish_burial_is_the_first_real_card_that_declares_a_gate():
    """
    어리석은 매장 (81439173) — "①: 덱에서 몬스터 1장을 묘지로 보낸다."

    ``s.tgfilter`` 가 ``c:IsMonster() and c:IsAbleToGrave()`` 다. 앞쪽은
    조건으로, 뒤쪽은 **관문으로** 옮겼다.
    """
    entry = entry_for(EffectRef(FOOLISH_BURIAL, 0))
    assert entry is not None
    assert entry.executable is True
    assert availability(entry.effect_ref) is ExecutionAvailability.EXECUTABLE

    (operation,) = entry.definition.operations
    assert operation.kind is OperationKind.SEND_TO_GRAVE
    assert operation.gated is True
    assert declared_gate_question(operation) is RuleQuestion.MAY_BE_SENT_TO_GRAVE

    # 근거가 원본에 실제로 있다.
    source = (ROOT / entry.lua_file).read_text("utf-8")
    assert "IsAbleToGrave" in source
    assert "Duel.SendtoGrave" in source


@pytest.mark.real_card
def test_i_the_two_earlier_real_cards_declare_no_gate():
    """
    **회귀가 없다는 것이 사실로 고정된다.** 육신보살 · 벌금의 스크립트는
    관문을 묻지 않으므로 ``gated=False`` 이고, 판정기 없이도 그대로
    실행된다.
    """
    for card_id, lua in ((SELF_MUMMIFICATION, "c15103313.lua"), (FINE, "c92595643.lua")):
        entry = entry_for(EffectRef(card_id, 0))
        (operation,) = entry.definition.operations
        assert operation.gated is False, card_id
        source = (ROOT / lua).read_text("utf-8")
        assert "IsAbleToGrave" not in source, card_id
        assert "IsDiscardable" not in source, card_id


@pytest.mark.real_card
@requires_official_db
def test_i_foolish_burial_activates_and_names_the_hidden_deck(repository):
    """
    §7-3 — 여전히 실행되지 않는 이유를 **엔진이 스스로 말한다.**

    관문이 아니라 **덱을 관측할 수 없다는 것**이 먼저 막는다. 순서가
    규칙이다: 대상이 적법한가 → 해도 되는가 → 어디로 가는가.
    """
    game = GameState.create(
        repository, decks=([FOOLISH_BURIAL] + [FEATHERMAN] * 20, [FEATHERMAN] * 20)
    )
    game.draw(MINE, 1)
    game.draw(THEIRS, 3)
    game.move(
        game.player(MINE).hand[0], Zone.SZONE, to_player=MINE,
        position=Position.FACEUP,
    )
    game.turn.set_phase(Phase.MAIN1)
    source = game.player(MINE).spell_zone[0].instance_id
    hidden_card = game.player(MINE).deck[0].instance_id
    before = game.state_hash()

    registry = definition_registry()
    activated = EffectActivator(registry, implementation_registry()).activate(
        game,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(FOOLISH_BURIAL, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(hidden_card)),),
        authorization=GRANTED,
    )

    assert activated.status is ActivationStatus.UNCHECKED_TARGET
    assert activated.code is ValidationCode.HIDDEN_CARD
    assert len(activated.chain) == 0
    assert game.state_hash() == before
    # 정체가 새지 않는다.
    identity = game.find_instance(hidden_card).card_id
    assert str(identity) not in (activated.reason or "")


@pytest.mark.real_card
@requires_official_db
def test_i_the_two_earlier_real_cards_still_resolve(repository):
    """
    §17 — 기존 실제 카드가 그대로 실행된다. 관문을 **종류로** 걸었다면
    여기가 깨졌을 것이다.
    """
    import tests.engine.test_real_card_execution as real

    for card_id, chooser in (
        (SELF_MUMMIFICATION, lambda s: (real.my_monster(s),)),
        (FINE, lambda s: real.my_hand(s, 2)),
    ):
        game = real.new_state(repository)
        activated, resolved = real.activate(game, card_id, *chooser(game))

        assert activated.status is ActivationStatus.ACTIVATED, card_id
        assert resolved.result.status is ResolutionStatus.RESOLVED, card_id
        assert resolved.result.deltas != (), card_id


@pytest.mark.real_card
def test_i_the_default_executor_declares_no_movement_ruling():
    """
    목록에 실렸다는 사실이 이동 판정을 대신하지 못한다
    (파괴의 STRUCTURAL-47 과 같은 자리).
    """
    executor = build_executor()
    assert isinstance(executor.movement, UnknownMovementRuling)
