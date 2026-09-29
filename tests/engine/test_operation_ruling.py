"""
Phase 2-AK — 조작 판정 계층 (ADR-006).

    "이 Operation 을 지금 이 상황에서 수행할 수 있는가?"

2-AJ 가 확정한 다음 병목이 이것이었다. 결과/조건/값 계층은 실제 카드의
의미를 적을 수 있는데, 정작 **조작 자체**가 판정기가 없어 일어나지 않았다.

무엇이 없었는가
---------------
관문의 **구조**는 2-M · 2-X 에 이미 있었다. 없던 것은 **지식**이다.

    DestructionRuling / MovementRuling / SummonRuling   프로토콜 ✔
    Unknown*Ruling                                      기본값   ✔
    Declared*Ruling                                     손 선언  ✔ (InstanceId)
    ──────────────────────────────────────────────────────────────
    카드 단위의, 출처가 있는, 다시 쓸 수 있는 지식              ✘

``Declared*Ruling`` 은 **판 번호**를 키로 삼는다. 시험 대역으로는 맞지만
지식이 아니다 — 같은 카드를 다음 듀얼에서 다시 확인해야 한다.

TRUE 는 공짜가 아니다
---------------------
"이 카드 텍스트에 막는 말이 없다" 만으로 ``TRUE`` 를 내면 판에 깔린 다른
카드가 막고 있을 때 틀린다. :class:`BoardRuling` 은 둘을 다 본다.
"""

import json
import pathlib
import re

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainResolutionStatus, ChainResolver
from engine.condition import ConditionResult
from engine.cost import Selection
from engine.effect.delta import ZoneMoved
from engine.effect.journal import EventJournal
from engine.effect.library import (
    COMPULSORY_EVACUATION_DEVICE,
    DISAPPEAR,
    FEATHERMAN,
    OPERATION_RULINGS,
    POT_OF_GREED,
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
from engine.effect.resolution import ResolutionStatus, TargetSelection
from engine.effect.ruling import (
    NORMAL_MONSTER_RULE,
    TOKEN_FORBIDDEN,
    TOKEN_RULE,
    UNSCANNED_ZONES,
    BoardRuling,
    CardRuleFacts,
    OperationRuling,
    OperationRulingRegistry,
    RuleBasis,
    RuleFact,
    RulingError,
    normal_monster_facts,
    token_facts,
)
from engine.effect.semantics import (
    DECLARED_GATE_RULINGS,
    LUA_GATE_PREDICATES,
    QUESTION_VERBS,
    RuleQuestion,
    UnknownMovementRuling,
    ask_movement,
)
from engine.effect.target import PRIMARY_TARGET
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode, ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1
GRANTED = ValidationResult.valid()

#: 2-AK 가 더한 세 질문.
NEW_QUESTIONS = (
    RuleQuestion.MAY_BE_RETURNED_TO_HAND,
    RuleQuestion.MAY_BE_BANISHED,
    RuleQuestion.MAY_BE_RETURNED_TO_DECK,
)


# ======================================================================
# 판 만들기
# ======================================================================


def evacuation_state(repository, *, seed=5) -> GameState:
    """
    자신 마법·함정존에 강제 탈출 장치(앞면), 양쪽 몬스터존에 페더맨.

    판에 있는 카드가 **전부 등록되어 있다** — 그렇지 않으면 훑기가
    ``UNKNOWN`` 에서 멈춘다. 그것이 이 계층의 기본값이다.
    """
    game = GameState.create(
        repository,
        decks=(
            [COMPULSORY_EVACUATION_DEVICE] + [FEATHERMAN] * 20,
            [FEATHERMAN] * 20,
        ),
        seed=seed,
    )
    game.draw(MINE, 2)
    game.draw(THEIRS, 1)
    game.move(
        game.player(MINE).hand[0].instance_id,
        Zone.SZONE,
        to_player=MINE,
        position=Position.FACEUP,
    )
    for player in (MINE, THEIRS):
        game.move(
            game.player(player).hand[0].instance_id,
            Zone.MZONE,
            to_player=player,
            position=Position.FACEUP_ATTACK,
        )
    game.turn.set_phase(Phase.MAIN1)
    return game


def board_ruling(state: GameState, registry=OPERATION_RULINGS) -> BoardRuling:
    return BoardRuling(GameStateView.from_state(state, viewer=MINE), registry)


def evacuate(state: GameState, target: InstanceId, *, movement=None, journal=None):
    """**기존 경로를 그대로 지난다.** 발동 → 체인 → 해결."""
    registry = definition_registry()
    activator = EffectActivator(registry, implementation_registry())
    source = state.player(MINE).spell_zone[0].instance_id
    activated = activator.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE,
            source=source,
            effect_ref=EffectRef(COMPULSORY_EVACUATION_DEVICE, 0),
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(target)),),
        authorization=GRANTED,
    )
    if activated.status is not ActivationStatus.ACTIVATED:
        return activated, None
    resolver = ChainResolver(build_executor(journal, movement=movement), registry)
    return activated, resolver.resolve_top(state, activated.chain)


@pytest.fixture
def state(repository) -> GameState:
    return evacuation_state(repository)


# ======================================================================
# A. 질문이 셋 늘어난 근거 (corpus)
# ======================================================================


def scan(pattern: str) -> int:
    rx = re.compile(pattern)
    return sum(
        1
        for path in ROOT.glob("c*.lua")
        if rx.search(path.read_text(errors="replace"))
    )


def test_a_the_new_questions_are_asked_by_real_cards():
    """
    이름을 지어내지 않았다. 셋 다 공식 스크립트의 술어다.

    ::

        IsAbleToHand     2,516장
        IsAbleToRemove     775장
        IsAbleToDeck       572장
    """
    counts = {
        RuleQuestion.MAY_BE_RETURNED_TO_HAND: scan(r"\bIsAbleToHand\b"),
        RuleQuestion.MAY_BE_BANISHED: scan(r"\bIsAbleToRemove\b"),
        RuleQuestion.MAY_BE_RETURNED_TO_DECK: scan(r"\bIsAbleToDeck\b"),
    }

    assert counts[RuleQuestion.MAY_BE_RETURNED_TO_HAND] == 2516
    assert counts[RuleQuestion.MAY_BE_BANISHED] == 775
    assert counts[RuleQuestion.MAY_BE_RETURNED_TO_DECK] == 572

    for question in NEW_QUESTIONS:
        assert question in LUA_GATE_PREDICATES
        assert question in QUESTION_VERBS


def test_a_the_gate_is_card_declared_because_the_corpus_is_split():
    """
    **셋 다 100% 도 0% 도 아니다.** 그래서 종류가 아니라 카드가 선언한다 —
    2-X 가 묘지로 보내기 · 버리기에서 내린 것과 **같은 결론**이다.

    ::

        Duel.SendtoHand  2,587장 중 IsAbleToHand   2,437  (94%)
        Duel.Remove      1,396장 중 IsAbleToRemove   711  (50%)
        Duel.SendtoDeck    825장 중 IsAbleToDeck     557  (67%)
    """
    measured = {}
    for call, predicate in (
        ("SendtoHand", "IsAbleToHand"),
        ("Remove", "IsAbleToRemove"),
        ("SendtoDeck", "IsAbleToDeck"),
    ):
        does = declares = 0
        for path in ROOT.glob("c*.lua"):
            text = path.read_text(errors="replace")
            if f"Duel.{call}(" not in text:
                continue
            does += 1
            if re.search(rf"\b{predicate}\b", text):
                declares += 1
        measured[call] = (does, declares)

    assert measured == {
        "SendtoHand": (2587, 2437),
        "Remove": (1396, 711),
        "SendtoDeck": (825, 557),
    }
    for does, declares in measured.values():
        assert 0 < declares < does  # 전부도 아니고 하나도 아님이 아니다

    for kind in (
        OperationKind.RETURN_TO_HAND,
        OperationKind.BANISH,
        OperationKind.RETURN_TO_DECK,
    ):
        assert kind in DECLARABLE_GATE_KINDS
        assert kind in DECLARED_GATE_RULINGS


def test_a_release_was_not_opened_although_it_is_also_split():
    """
    ``Duel.Release`` 693장 중 ``IsReleasable`` 을 적는 것은 73장(10%)뿐이다.
    같은 모양이지만 **열지 않았다** — 이번에 필요한 카드가 없고, 필요 없는
    것을 미리 열면 그것이 옳은지 아무도 확인하지 않는다.
    """
    assert OperationKind.RELEASE not in DECLARABLE_GATE_KINDS
    assert OperationKind.RELEASE not in DECLARED_GATE_RULINGS

    with pytest.raises(ValueError, match="선언하는 것이 아닙니다"):
        CardOperation(OperationKind.RELEASE, PRIMARY_TARGET, gated=True)


# ======================================================================
# B. 사실은 사실만 담는다
# ======================================================================


def test_b_a_fact_cannot_be_unknown():
    """
    **"모른다" 는 사실이 아니다.** 표에 줄이 없는 것이 "모른다" 이고,
    담을 수 있게 하면 "확인해 보니 모르겠더라" 와 "안 봤다" 가 같은 모양이
    된다.
    """
    with pytest.raises(RulingError, match="참이거나 거짓"):
        RuleFact(ConditionResult.UNKNOWN, RuleBasis.RULEBOOK, "…")


def test_b_a_fact_must_say_where_it_came_from():
    with pytest.raises(RulingError, match="무엇을 읽고"):
        RuleFact(ConditionResult.TRUE, RuleBasis.CARD_TEXT, "   ")


def test_b_claiming_a_card_blocks_nothing_needs_evidence():
    """
    ``restricts_others=False`` 는 **주장**이다. 근거 없이 못 적는다.
    기본값이 참인 것도 같은 이유다 — 확인하지 않은 카드는 막을 수 있다고
    본다.
    """
    assert CardRuleFacts(card_id=1).restricts_others is True

    with pytest.raises(RulingError, match="무엇을 읽고"):
        CardRuleFacts(card_id=1, restricts_others=False)

    ok = CardRuleFacts(
        card_id=1,
        restricts_others=False,
        restriction_basis=RuleBasis.CARD_TEXT,
        restriction_note="텍스트 전문을 읽었다",
    )
    assert ok.restricts_others is False


def test_b_an_unchecked_question_is_none_not_false():
    facts = CardRuleFacts(
        card_id=1,
        answers={
            RuleQuestion.MAY_BE_RETURNED_TO_HAND: RuleFact(
                ConditionResult.TRUE, RuleBasis.CARD_TEXT, "읽었다"
            )
        },
    )

    assert facts.answer_for(RuleQuestion.MAY_BE_RETURNED_TO_HAND) is not None
    assert facts.answer_for(RuleQuestion.MAY_BE_BANISHED) is None


def test_b_one_card_is_written_in_one_place():
    registry = OperationRulingRegistry((CardRuleFacts(card_id=1),))

    with pytest.raises(RulingError, match="이미 등록"):
        registry.register(CardRuleFacts(card_id=1))


def test_b_an_unregistered_card_is_simply_unknown():
    """ADR-006 의 기본값이 이 계층에서 갖는 모양."""
    registry = OperationRulingRegistry()

    assert registry.facts_for(FEATHERMAN) is None
    assert len(registry) == 0


# ======================================================================
# C. 룰북이 직접 답하는 것
# ======================================================================


def rulebook_text() -> str:
    data = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text()
    )

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, str):
            yield node

    return "\n".join(walk(data))


def test_c_both_rulebook_quotes_are_really_in_the_rulebook():
    """
    **인용을 지어내지 않았다.** 두 문장 다 저장소의 공식 룰북에 있다.

    PDF 에서 뽑은 원문은 줄바꿈과 **합자**(``ﬁ`` U+FB01, ``ﬂ`` U+FB02)를
    그대로 갖고 있다 — "the ﬁeld" · "ﬂip". 글자가 다른 것이 아니라 활자가
    다른 것이므로, 비교 전에 그것만 편다. 단어는 하나도 바꾸지 않는다.
    """
    text = " ".join(rulebook_text().replace("ﬁ", "fi").replace("ﬂ", "fl").split())

    assert " ".join(NORMAL_MONSTER_RULE.split()) in text
    assert " ".join(TOKEN_RULE.split()) in text


def test_c_a_normal_monster_is_answered_by_one_rulebook_line():
    """
    "Yellow Normal Monster Cards do not have effects" — 효과가 없으므로
    (1) 스스로를 지키지 않고 (2) 남을 막지 않는다. 추측이 아니라 귀결이다.
    """
    facts = normal_monster_facts(FEATHERMAN, "페더맨")

    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.RULEBOOK
    for question in NEW_QUESTIONS:
        fact = facts.answer_for(question)
        assert fact.answer is ConditionResult.TRUE
        assert fact.basis is RuleBasis.RULEBOOK


def test_c_a_normal_monster_says_nothing_about_being_destroyed():
    """
    **파괴와 특수 소환은 적지 않았다.** "내성이 없다" 와 "지금 파괴해도
    된다" 는 다른 문장이고, 뒤의 것은 대체 효과 · 동시 파괴 처리까지
    봐야 한다. 소생 제한은 아예 카드가 아니라 **이력**에 달려 있다.
    """
    facts = normal_monster_facts(FEATHERMAN)

    assert set(facts.answers) == {
        RuleQuestion.MAY_BE_RETURNED_TO_HAND,
        RuleQuestion.MAY_BE_BANISHED,
        RuleQuestion.MAY_BE_RETURNED_TO_DECK,
        RuleQuestion.MAY_BE_SENT_TO_GRAVE,
        RuleQuestion.MAY_BE_DISCARDED,
    }


def test_c_a_token_is_refused_exactly_where_the_rulebook_names_it():
    """
    "cannot be sent anywhere other than the field, such as the hand or
    Graveyard" — 룰북이 이름을 댄 자리만 적는다.

    **제외는 적지 않았다.** 룰북이 대지 않았고, 대지 않은 것을 채워 넣으면
    그것이 옳은지 아무도 확인하지 않는다.
    """
    facts = token_facts(999, "토큰")

    for question in TOKEN_FORBIDDEN:
        assert facts.answer_for(question).answer is ConditionResult.FALSE
    assert facts.answer_for(RuleQuestion.MAY_BE_BANISHED) is None


# ======================================================================
# D. 판을 보고 답을 합성한다
# ======================================================================


def test_d_the_ruling_refuses_a_mutable_state(state):
    """관측 경계를 우회할 수 없다 — ``GameState`` 를 아예 받지 않는다."""
    with pytest.raises(TypeError, match="GameStateView"):
        BoardRuling(state, OPERATION_RULINGS)


def test_d_an_invisible_card_is_unknown(state):
    ruling = board_ruling(state)

    verdict = ruling.explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, InstanceId(9999)
    )

    assert verdict.answer is ConditionResult.UNKNOWN
    assert "보이지 않아" in verdict.reason


def test_d_an_unregistered_card_is_unknown(state):
    target = state.player(THEIRS).monster_zone[0].instance_id
    ruling = board_ruling(state, OperationRulingRegistry())

    verdict = ruling.explain(RuleQuestion.MAY_BE_RETURNED_TO_HAND, target)

    assert verdict.answer is ConditionResult.UNKNOWN
    assert "확인된 것이 없습니다" in verdict.reason


def test_d_a_registered_card_with_an_unchecked_question_is_unknown(state):
    """
    등록은 됐지만 **그 질문은 확인하지 않았다.** 등록을 허가로 읽지 않는다.
    """
    target = state.player(MINE).spell_zone[0].instance_id  # 강제 탈출 장치 자신
    ruling = board_ruling(state)

    verdict = ruling.explain(RuleQuestion.MAY_BE_RETURNED_TO_HAND, target)

    assert verdict.answer is ConditionResult.UNKNOWN
    assert "확인되지 않았습니다" in verdict.reason


def test_d_a_clean_board_gives_a_true_with_its_reason(state):
    target = state.player(THEIRS).monster_zone[0].instance_id
    ruling = board_ruling(state)

    verdict = ruling.explain(RuleQuestion.MAY_BE_RETURNED_TO_HAND, target)

    assert verdict.answer is ConditionResult.TRUE
    assert "통상 몬스터" in verdict.reason


def test_d_one_unknown_card_on_the_board_is_enough_to_stop_it(repository):
    """
    **"아무도 안 막는다" 는 판 전체를 다 읽었을 때만 할 수 있는 말이다.**

    페더맨 한 장을 등록에서 빼면, 그 카드와 무관한 질문의 답까지
    ``UNKNOWN`` 이 된다. 지나치게 조심스러운 것이 아니라 **정확한** 것이다 —
    모르는 카드가 막고 있을 수 있다.
    """
    state = evacuation_state(repository)
    target = state.player(THEIRS).monster_zone[0].instance_id
    partial = OperationRulingRegistry(
        (
            CardRuleFacts(
                card_id=COMPULSORY_EVACUATION_DEVICE,
                restricts_others=False,
                restriction_basis=RuleBasis.CARD_TEXT,
                restriction_note="읽었다",
            ),
            # 대상 자신에 대한 답은 있다. 판의 다른 페더맨이 문제다.
            normal_monster_facts(FEATHERMAN),
        )
    )
    assert board_ruling(state, partial).may(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target
    ) is ConditionResult.TRUE

    unknown_card = OperationRulingRegistry(
        (
            CardRuleFacts(
                card_id=COMPULSORY_EVACUATION_DEVICE,
                answers={
                    RuleQuestion.MAY_BE_RETURNED_TO_HAND: RuleFact(
                        ConditionResult.TRUE, RuleBasis.CARD_TEXT, "읽었다"
                    )
                },
                restricts_others=False,
                restriction_basis=RuleBasis.CARD_TEXT,
                restriction_note="읽었다",
            ),
        )
    )
    verdict = board_ruling(state, unknown_card).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND,
        state.player(MINE).spell_zone[0].instance_id,
    )
    assert verdict.answer is ConditionResult.UNKNOWN
    assert "확인된 것이 없어" in verdict.reason


def test_d_a_card_that_can_block_makes_the_answer_unknown(repository):
    """
    지속 효과를 **해석하지 않는다.** 막을 수 있는 카드가 깔려 있으면 그냥
    ``UNKNOWN`` 이다 — 무엇을 어떻게 막는지 읽는 계층이 없다
    (STRUCTURAL-76).
    """
    state = evacuation_state(repository)
    target = state.player(THEIRS).monster_zone[0].instance_id
    registry = OperationRulingRegistry(
        (
            normal_monster_facts(FEATHERMAN),
            CardRuleFacts(card_id=COMPULSORY_EVACUATION_DEVICE),  # 기본값 = 막을 수 있다
        )
    )

    verdict = board_ruling(state, registry).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target
    )

    assert verdict.answer is ConditionResult.UNKNOWN
    assert "막을 수 있습니다" in verdict.reason


def test_d_a_false_needs_no_board_scan(repository):
    """
    **막는 것은 혼자서도 막는다.** 토큰이 패로 못 간다는 사실은 판에 무엇이
    깔려 있든 그대로이므로, 훑기를 하지 않는다.
    """
    state = evacuation_state(repository)
    target = state.player(THEIRS).monster_zone[0].instance_id
    registry = OperationRulingRegistry(
        (token_facts(FEATHERMAN, "토큰인 척"),)  # 판의 다른 카드는 등록되지 않았다
    )

    verdict = board_ruling(state, registry).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target
    )

    assert verdict.answer is ConditionResult.FALSE
    assert "토큰" in verdict.reason


def test_d_a_set_card_does_not_stop_the_scan(repository):
    """
    세트된 카드는 **발동 · 반전 전까지 효과를 적용하지 않는다** (룰북).
    그래서 정체를 몰라도 훑기를 막지 않는다.
    """
    state = evacuation_state(repository)
    state.draw(THEIRS, 1)
    state.move(
        state.player(THEIRS).hand[0].instance_id,
        Zone.SZONE,
        to_player=THEIRS,
        position=Position.FACEDOWN,
    )
    assert state.player(THEIRS).spell_zone[0].is_faceup is False
    target = state.player(THEIRS).monster_zone[0].instance_id

    assert board_ruling(state).may(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target
    ) is ConditionResult.TRUE
    assert "뒷면 카드" in UNSCANNED_ZONES


def test_d_what_is_not_scanned_is_written_down(state):
    """
    **빈 칸으로 두지 않는다.** 패를 훑지 않는다는 것은 한계이고, 한계를
    값으로 들고 있어야 문서만 남고 코드가 잊는 일이 없다.
    """
    limits = board_ruling(state).scope_limits()

    assert any("패" in line for line in limits)
    assert any("STRUCTURAL-98" in line for line in limits)


def test_d_destruction_and_summoning_are_still_unknown(state):
    """
    **이 계층은 파괴와 특수 소환에 답하지 않는다.** 답하는 척하면 내성을
    가진 카드가 실제로 파괴된다.
    """
    target = state.player(THEIRS).monster_zone[0].instance_id
    ruling = board_ruling(state)

    assert ruling.may_be_destroyed(target) is ConditionResult.UNKNOWN
    assert ruling.may_be_special_summoned(target) is ConditionResult.UNKNOWN


def test_d_the_old_protocols_go_through_the_same_door(state):
    """
    ``may_be_sent_to_grave`` 와 ``may`` 가 **같은 자리**로 들어간다.
    두 벌로 갈리면 2-AJ 가 사건 계층에서 겪은 일이 여기서 되풀이된다.
    """
    target = state.player(THEIRS).monster_zone[0].instance_id
    ruling = board_ruling(state)

    assert ruling.may_be_sent_to_grave(target) is ruling.may(
        RuleQuestion.MAY_BE_SENT_TO_GRAVE, target
    )
    assert ruling.may_be_discarded(target) is ruling.may(
        RuleQuestion.MAY_BE_DISCARDED, target
    )
    assert isinstance(ruling, OperationRuling)


def test_d_an_old_ruling_says_unknown_to_a_new_question():
    """
    옛 판정기는 2-AK 의 질문을 **모른다.** 그것이 사실이므로 ``UNKNOWN``
    이고, 예외가 아니다 — 모르는 것과 잘못 부른 것을 같은 모양으로 만들지
    않는다.
    """
    old = UnknownMovementRuling()

    for question in NEW_QUESTIONS:
        assert ask_movement(old, question, InstanceId(1)) is ConditionResult.UNKNOWN
    with pytest.raises(ValueError):
        ask_movement(old, RuleQuestion.MAY_BE_TARGETED, InstanceId(1))


# ======================================================================
# E. 실제 카드 — 강제 탈출 장치 (94192409)
# ======================================================================


@pytest.mark.real_card
def test_e_without_a_ruling_the_gate_stops_it_and_the_board_is_untouched(state):
    """
    **``UNKNOWN`` 은 허가가 아니다.** 판정기를 주지 않으면 관문에서 멈추고,
    멈출 때 판은 한 글자도 바뀌지 않는다.
    """
    target = state.player(THEIRS).monster_zone[0].instance_id
    before = state.state_hash()

    activated, resolved = evacuate(state, target)

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is not ChainResolutionStatus.RESOLVED
    assert resolved.result.status is ResolutionStatus.UNCHECKED_RULES
    assert "패로 되돌릴 수 있는지 판정할 수 없습니다" in resolved.result.reason
    assert "IsAbleToHand" in resolved.result.missing
    assert state.state_hash() == before


@pytest.mark.real_card
def test_e_with_a_ruling_the_monster_really_goes_back_to_the_hand(state):
    """
    **2-W 부터 네 단계 동안 멈춰 있던 카드가 돈다.**

        c94192409.lua
          Duel.SelectTarget(tp, Card.IsAbleToHand, …, LOCATION_MZONE, 1,1)
          Duel.SendtoHand(tc, nil, REASON_EFFECT)
    """
    target = state.player(THEIRS).monster_zone[0].instance_id
    hand_before = len(state.player(THEIRS).hand)
    journal = EventJournal()

    activated, resolved = evacuate(
        state, target, movement=board_ruling(state), journal=journal
    )

    assert activated.status is ActivationStatus.ACTIVATED
    assert resolved.status is ChainResolutionStatus.RESOLVED

    moved = [d for d in resolved.deltas if isinstance(d, ZoneMoved)]
    assert len(moved) == 1
    assert moved[0].card == target
    assert moved[0].destination_zone is Zone.HAND
    assert moved[0].movement is OperationKind.RETURN_TO_HAND

    assert len(state.player(THEIRS).monster_zone) == 0
    assert len(state.player(THEIRS).hand) == hand_before + 1
    assert len(journal.events) == 1


@pytest.mark.real_card
def test_e_my_own_monster_is_a_legal_target_too(state):
    """``LOCATION_MZONE, LOCATION_MZONE`` — 양쪽이다. 주인을 가리지 않는다."""
    target = state.player(MINE).monster_zone[0].instance_id

    _, resolved = evacuate(state, target, movement=board_ruling(state))

    assert resolved.status is ChainResolutionStatus.RESOLVED
    assert len(state.player(MINE).monster_zone) == 0


@pytest.mark.real_card
def test_e_a_refusal_stops_the_whole_effect(repository):
    """
    판정이 ``FALSE`` 면 **거절**이지 ``UNKNOWN`` 이 아니다. 둘 다 판을
    건드리지 않지만 이유가 다르고, 이유가 다르면 고칠 것도 다르다.
    """
    state = evacuation_state(repository)
    target = state.player(THEIRS).monster_zone[0].instance_id
    before = state.state_hash()
    registry = OperationRulingRegistry(
        (
            token_facts(FEATHERMAN, "토큰인 척"),
            CardRuleFacts(
                card_id=COMPULSORY_EVACUATION_DEVICE,
                restricts_others=False,
                restriction_basis=RuleBasis.CARD_TEXT,
                restriction_note="읽었다",
            ),
        )
    )

    _, resolved = evacuate(
        state, target, movement=board_ruling(state, registry)
    )

    assert resolved.result.status is ResolutionStatus.INVALID_TARGET
    assert resolved.result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert "패로 되돌릴 수 없다고 판정되었습니다" in resolved.result.reason
    assert state.state_hash() == before


@pytest.mark.real_card
def test_e_the_entry_records_the_gate_it_moved(state):
    definition = entry_for(EffectRef(COMPULSORY_EVACUATION_DEVICE, 0)).definition

    (operation,) = definition.operations
    assert operation.kind is OperationKind.RETURN_TO_HAND
    assert operation.gated is True
    assert "IsAbleToHand 는 관문으로 옮겼다" in definition.provenance.note


@pytest.mark.real_card
def test_e_disappear_is_still_declined_but_for_a_different_reason():
    """
    **이유가 바뀐 것을 기록한다.** 2-W 의 이유(``IsAbleToRemove`` 를 판정할
    계층이 없다)는 이제 참이 아니다. 다시 읽어 보니 둘이 남아 있었다.

    1. ``aux.SpElimFilter`` — EDOPro 보조 함수, 내용 미확인.
    2. 공식 텍스트는 "상대의 **묘지의** 카드", 스크립트는
       ``LOCATION_MZONE|LOCATION_GRAVE``. 어느 쪽이 맞는지 공식 재정으로
       확인하지 않았다 (2-AJ 가 STRUCTURAL-96 을 닫은 방법이 그것이었다).
    """
    entry = entry_for(EffectRef(DISAPPEAR, 0))

    assert entry.executable is False
    assert "aux.SpElimFilter" in entry.note
    assert "다르다" in entry.note

    lua = (ROOT / "c24623598.lua").read_text(errors="replace")
    assert "LOCATION_MZONE|LOCATION_GRAVE" in lua


# ======================================================================
# F. 불변 (결정론 · 복제 · 관측)
# ======================================================================


@pytest.mark.real_card
def test_f_the_same_seed_gives_the_same_result(repository):
    first = evacuation_state(repository, seed=8)
    second = evacuation_state(repository, seed=8)
    assert first.state_hash() == second.state_hash()

    for game in (first, second):
        evacuate(
            game,
            game.player(THEIRS).monster_zone[0].instance_id,
            movement=board_ruling(game),
        )

    assert first.state_hash() == second.state_hash()


@pytest.mark.real_card
def test_f_a_clone_does_not_share_the_outcome(repository):
    original = evacuation_state(repository)
    before = original.state_hash()
    copy = original.clone()

    evacuate(
        copy,
        copy.player(THEIRS).monster_zone[0].instance_id,
        movement=board_ruling(copy),
    )

    assert original.state_hash() == before
    assert copy.state_hash() != before


def test_f_the_ruling_never_changes_the_board(state):
    """판정은 **읽기만** 한다. 스냅숏만 들고 있으므로 바꿀 것이 없다."""
    before = state.state_hash()
    ruling = board_ruling(state)

    for question in RuleQuestion:
        if question in (
            RuleQuestion.MAY_BE_TARGETED,
            RuleQuestion.OPERATION_POSSIBLE,
        ):
            continue
        for player in (MINE, THEIRS):
            for card in state.player(player).monster_zone:
                ruling.may(question, card.instance_id)

    assert state.state_hash() == before


def test_f_the_registry_covers_every_registered_real_card():
    """
    **판에 나올 수 있는 카드는 전부 등록되어 있다.** 하나라도 빠지면 그
    카드가 깔린 판의 답이 통째로 ``UNKNOWN`` 이 된다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    registered = set(OPERATION_RULINGS.card_ids)
    assert {entry.card_id for entry in EFFECT_LIBRARY} <= registered
    assert FEATHERMAN in registered
    assert len(OPERATION_RULINGS) == 17


def test_f_no_spell_or_trap_claims_to_be_returnable(repository):
    """
    목록의 마법 · 함정에는 **자기 자신에 대한 답이 하나도 없다.** 확인한
    것은 "다른 카드를 막지 않는다" 하나뿐이고, 확인하지 않은 것을 적지
    않는다.
    """
    facts = OPERATION_RULINGS.facts_for(POT_OF_GREED)

    assert facts is not None
    assert facts.answers == {}
    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.CARD_TEXT
