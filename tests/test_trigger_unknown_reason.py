"""
Phase 3-E-27 — 트리거 계층의 ``UNKNOWN`` **까닭** 분리.

``UNKNOWN`` 이 한 칸이면 "코드가 생겨야 풀리는 것" 과 "판이 바뀌면 풀리는 것"
을 구분할 수 없다. 3-E-26 이 발동/해결 계층에서 가른 것을 트리거 계층의 네
자리에 같은 방법으로 적용했고, 이 파일이 그것을 지킨다.

고친 자리 — 전부 **이미 있는** 어휘와 **이미 있는** API 만 썼다.

1. ``TriggerCollector._judge`` 조건 ``UNKNOWN``
   → ``condition.missing_rules(view, context)`` 로 가른다
2. ``TriggerEligibilityJudge._trigger_condition`` 조건 ``UNKNOWN``
   → 같은 방법 + ``ValidationResult.missing_rule`` 에 규칙 이름을 싣는다
3. ``TriggerChainIntegrator._undecided``
   → 조건을 다시 평가하지 않는 계층이므로 **막힌 ``UNKNOWN`` 관문**이 적어 둔
   코드를 올린다
4. ``TriggerChainIntegrator._refused``
   → 확실한 거부였는데 ``RULE_NOT_IMPLEMENTED`` 를 적고 있었다 (3-E-26 이
   ``trigger.py`` 에서 고친 것과 **같은 결함**이 여기 남아 있었다).
   **``INVALID`` 관문**이 적어 둔 코드를 올린다.

**판정은 한 칸도 움직이지 않았다.** ``UNKNOWN`` 안에서 이유만 갈랐고,
거부는 거부 그대로다.
"""

import pytest

from engine.chain import Chain
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.condition.model import And, ConditionContext
from engine.cost import CostGroup
from engine.effect import (
    CardDrawn,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.trigger_chain import ChainInsertion, TriggerChainIntegrator
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1
WATCHER = 1000
"""트리거를 등록할 카드. 이 카드의 **의미를 주장하지 않는다** — 껍데기다."""
PLAIN = 1001
WATCHED = EffectRef(WATCHER, 0)

MISSING = "체인 위의 카드 수"
"""아직 없는 규칙 계층의 이름. 실제 로드맵의 문구를 쓰지 않는다."""


# ======================================================================
# 판 — 셔플하지 않는다
# ======================================================================


def new_state() -> "tuple[GameState, InstanceId]":
    """
    p0: 앞면 몬스터 1장 + 패. p1: **뒷면 세트 카드 1장** + 패.

    뒷면 카드가 이 파일의 핵심이다 — 정체를 볼 수 없는 사실이 필요하다.
    """
    game = GameState.create(
        decks=(
            [WATCHER, WATCHER, PLAIN, PLAIN, PLAIN, PLAIN],
            [PLAIN, PLAIN, PLAIN, PLAIN],
        ),
    )
    game.draw(MINE, 3)
    game.draw(THEIRS, 2)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    facedown = game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    game.turn.set_phase(Phase.MAIN1)
    return game, facedown.instance_id


@pytest.fixture
def board():
    return new_state()


def seen_by(state: GameState, viewer: int = MINE) -> GameStateView:
    return GameStateView.from_state(state, viewer=viewer)


def spec(condition=None, *, zones=frozenset({Zone.MZONE})) -> TriggerSpec:
    return TriggerSpec(
        WATCHED, TimingPoint.CARD_DRAWN, condition=condition, activates_from=zones
    )


def definition(activation=None) -> EffectDefinition:
    return EffectDefinition(
        effect_ref=WATCHED,
        source_card_id=WATCHER,
        operations=(DrawOperation(1),),
        activation=activation,
        cost=CostGroup(),
        provenance=EffectProvenance.official_lua(),
    )


def drawn() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(2)))


def collected(view, condition):
    """site 1 — 후보 하나."""
    collection = TriggerCollector(view, TriggerRegistry((spec(condition),))).collect(
        drawn()
    )
    return collection.candidates[0]


def condition_gate(view, condition):
    """site 2 — 조건 관문 하나."""
    declared = spec(condition)
    candidate = TriggerCollector(view, TriggerRegistry((declared,))).collect(
        drawn()
    ).candidates[0]
    eligibility = TriggerEligibilityJudge(view).judge(candidate, declared, drawn())
    return eligibility, eligibility.gate(EligibilityGate.TRIGGER_CONDITION)


def planned(view, condition):
    """site 3·4 — 삽입 계획 하나."""
    integrator = TriggerChainIntegrator(
        view,
        TriggerRegistry((spec(),)),
        EffectDefinitionRegistry((definition(activation=condition),)),
        EffectImplementationRegistry((WATCHED,)),
    )
    return integrator.plan(Chain(), integrator.collect_and_order(drawn()))


# ======================================================================
# A. 정보가 없어서 모른다 → INFORMATION_UNAVAILABLE
# ======================================================================


def test_01_a_hidden_identity_is_missing_information_not_a_missing_rule(board):
    """
    상대의 뒷면 카드가 **무엇인가**는 볼 수 없다. 규칙은 있다 — 정보가 없다.

    이 까닭은 **판이 바뀌면 풀린다** (카드가 앞면이 되면 답이 나온다). 그래서
    ``RULE_NOT_IMPLEMENTED`` 가 아니다.
    """
    state, facedown = board
    view = seen_by(state)

    candidate = collected(view, IsMonster(facedown))

    assert candidate.status is TriggerStatus.UNKNOWN
    assert candidate.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert candidate.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert candidate.is_candidate is False


def test_02_an_unobservable_card_is_also_missing_information(board):
    """관측 밖의 카드도 정보 쪽이다 — 빠진 규칙이 없다."""
    state, _ = board

    candidate = collected(seen_by(state), IsMonster(InstanceId(9999)))

    assert candidate.status is TriggerStatus.UNKNOWN
    assert candidate.code is ValidationCode.INFORMATION_UNAVAILABLE


# ======================================================================
# B. 규칙이 없어서 모른다 → RULE_NOT_IMPLEMENTED
# ======================================================================


def test_03_a_missing_rule_is_reported_as_a_missing_rule(board):
    """
    ``UnimplementedRule`` 은 **코드가 생겨야** 풀린다. 판을 아무리 바꿔도 답이
    나오지 않으므로 정보 부족과 같은 칸에 두면 안 된다.
    """
    state, _ = board

    candidate = collected(seen_by(state), UnimplementedRule(MISSING))

    assert candidate.status is TriggerStatus.UNKNOWN
    assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert candidate.code is not ValidationCode.INFORMATION_UNAVAILABLE
    #: 규칙 이름은 ``notes`` 가 조건 계층의 말 그대로 전한다.
    assert any(MISSING in note for note in candidate.notes)


def test_04_the_gate_also_carries_the_rule_name(board):
    """
    관문은 :class:`~engine.validation.ValidationResult` 를 그대로 싣는다 —
    그래서 ``missing_rule`` 까지 남는다. **새 필드를 만들지 않았다.**
    """
    state, facedown = board
    view = seen_by(state)

    _, missing_rule_gate = condition_gate(view, UnimplementedRule(MISSING))
    _, hidden_gate = condition_gate(view, IsMonster(facedown))

    assert missing_rule_gate.validity is ActionValidity.UNKNOWN
    assert missing_rule_gate.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert missing_rule_gate.result.missing_rule == MISSING

    assert hidden_gate.validity is ActionValidity.UNKNOWN
    assert hidden_gate.code is ValidationCode.INFORMATION_UNAVAILABLE
    #: 정보가 없어서 모르는 쪽은 **빠진 규칙이 없다.** 빈 칸을 지어내지 않는다.
    assert hidden_gate.result.missing_rule is None


# ======================================================================
# C · E. 거짓은 거짓이고, 조건 없음은 모름이 아니다
# ======================================================================


def test_05_a_known_false_condition_never_becomes_unknown(board):
    """
    조건을 **끝까지 보고** 거짓을 받았다. 트리거 계층이 조심스럽다는 이유로
    모름으로 올리지 않는다.
    """
    state, _ = board
    view = seen_by(state)

    candidate = collected(view, Always(ConditionResult.FALSE))
    eligibility, gate = condition_gate(view, Always(ConditionResult.FALSE))

    assert candidate.status is TriggerStatus.INELIGIBLE
    assert candidate.status is not TriggerStatus.UNKNOWN
    assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert eligibility.status is TriggerStatus.INELIGIBLE
    assert gate.validity is ActionValidity.INVALID
    assert gate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE


def test_06_no_condition_is_not_unknown(board):
    """
    조건 metadata 가 **없다**는 것만으로 모름이 되지 않는다
    (``all_of([]) is TRUE`` — 조건이 없으면 막을 것이 없다).
    """
    state, _ = board
    view = seen_by(state)

    candidate = collected(view, None)
    _, gate = condition_gate(view, None)

    assert candidate.status is TriggerStatus.ELIGIBLE
    assert candidate.code is ValidationCode.OK
    assert gate.validity is ActionValidity.VALID
    assert gate.code is ValidationCode.OK


# ======================================================================
# D. 둘 다 빠졌을 때 — 우선순위를 **새로 정하지 않았다**
# ======================================================================


def test_07_a_missing_rule_wins_over_missing_information_in_either_order(board):
    """
    규칙도 없고 정보도 없을 때 어느 쪽을 말하는가.

    **저장소가 이미 정해 둔 답을 따른다.** ``ActionValidator._check_requirements``
    는 빠진 규칙이 하나라도 있으면 ``RULE_NOT_IMPLEMENTED`` 를 쓰고,
    ``And.missing_rules`` 는 자식 순서와 무관하게 규칙을 모은다. 즉 순서를
    바꿔도 같은 답이 나와야 한다 — 그것이 우선순위를 **지어내지 않았다**는
    증거다.
    """
    state, facedown = board
    view = seen_by(state)
    rule_first = And((UnimplementedRule(MISSING), IsMonster(facedown)))
    hidden_first = And((IsMonster(facedown), UnimplementedRule(MISSING)))

    a = collected(view, rule_first)
    b = collected(view, hidden_first)

    assert a.status is b.status is TriggerStatus.UNKNOWN
    assert a.code is b.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: 두 까닭이 **둘 다** 남는다 — 하나를 지우지 않는다.
    assert any(MISSING in note for note in a.notes)
    assert any("뒷면" in note for note in a.notes)


# ======================================================================
# F. 체인 삽입 계층 — 다시 평가하지 않고 관문의 까닭을 올린다
# ======================================================================


def test_08_the_chain_layer_reports_the_blocking_gates_reason(board):
    """
    ``TriggerChainIntegrator`` 는 조건을 다시 평가하지 않는다. 그래서
    ``missing_rules`` 를 부를 수 없고, **관문이 적어 둔 코드**를 올린다.
    """
    state, facedown = board
    view = seen_by(state)

    by_rule = planned(view, UnimplementedRule(MISSING))
    by_hidden = planned(view, IsMonster(facedown))

    assert by_rule.unresolved and by_hidden.unresolved
    for entry in by_rule.unresolved:
        assert entry.insertion is ChainInsertion.UNKNOWN
        assert entry.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert any(MISSING in note for note in entry.notes)
    for entry in by_hidden.unresolved:
        assert entry.insertion is ChainInsertion.UNKNOWN
        assert entry.code is ValidationCode.INFORMATION_UNAVAILABLE


def test_09_a_refusal_in_the_chain_layer_is_not_called_unimplemented(board):
    """
    **3-E-27 에서 새로 찾은 결함.** ``_refused`` 는 확실한 거부에
    ``RULE_NOT_IMPLEMENTED`` 를 적고 있었다 — 3-E-26 이 ``trigger.py`` 에서
    고친 것과 같은 결함이 이 파일에 남아 있었다 (3-E-26 의 측정이
    ``ChainInsertion.NOT_INSERTABLE`` 을 보지 않아서 놓쳤다).

    거부를 일으킨 **``INVALID`` 관문**의 코드를 올린다. 패의 사본은 자리에서
    막히므로 ``SOURCE_WRONG_ZONE`` 이고, 조건이 거짓이면
    ``CANDIDATE_NOT_ELIGIBLE`` 이다. 어느 쪽도 "엔진이 못 한다" 가 아니다.
    """
    state, _ = board
    view = seen_by(state)

    plan = planned(view, Always(ConditionResult.FALSE))

    assert plan.skipped
    for entry in plan.skipped:
        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.code is not ValidationCode.RULE_NOT_IMPLEMENTED
        assert entry.code in (
            ValidationCode.CANDIDATE_NOT_ELIGIBLE,
            ValidationCode.SOURCE_WRONG_ZONE,
        )


def test_10_a_definite_refusal_is_not_relabelled_by_an_unknown_gate(board):
    """
    같은 후보에 ``INVALID`` 관문과 ``UNKNOWN`` 관문이 **함께** 있을 때.

    패의 사본은 자리 관문에서 확실히 막히는데 조건 관문은 판정 불가다.
    판정은 ``INELIGIBLE`` 이므로 (``fold`` 가 ``INVALID`` 를 먼저 접는다)
    이유도 거부 쪽에서 와야 한다 — 모름이 거부의 이름을 가져가지 않는다.
    """
    state, _ = board
    view = seen_by(state)

    plan = planned(view, UnimplementedRule(MISSING))

    assert plan.skipped, "자리에서 막힌 사본이 있어야 한다"
    for entry in plan.skipped:
        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.code is ValidationCode.SOURCE_WRONG_ZONE
        assert entry.code is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_10b_an_earlier_unknown_gate_does_not_name_the_refusal(board):
    """
    **거부의 이름은 거부를 일으킨 관문에서만 온다** — 순서가 아니라 판정으로
    고른다.

    이 판은 그 둘이 갈리는 유일한 모양이다: ``activates_from`` 을 적지 않아
    자리 관문이 ``UNKNOWN`` (``RULE_NOT_IMPLEMENTED``) 이고, 조건 관문이
    ``INVALID`` (``CANDIDATE_NOT_ELIGIBLE``) 다. ``blocking`` 은 검사 순서를
    보존하므로 **모름이 먼저 온다.** "처음 막힌 관문" 으로 고르면 확실한
    거부가 "엔진이 못 한다" 로 다시 라벨링된다.

    (``test_10`` 만으로는 이 차이가 드러나지 않는다 — 거기서는 ``INVALID``
    관문이 마침 먼저 와서 두 방식이 같은 답을 낸다.)
    """
    state, _ = board
    view = seen_by(state)
    undeclared = TriggerSpec(WATCHED, TimingPoint.CARD_DRAWN, activates_from=None)
    integrator = TriggerChainIntegrator(
        view,
        TriggerRegistry((undeclared,)),
        EffectDefinitionRegistry((definition(activation=Always(ConditionResult.FALSE)),)),
        EffectImplementationRegistry((WATCHED,)),
    )
    plan = integrator.plan(Chain(), integrator.collect_and_order(drawn()))

    assert plan.skipped
    for entry in plan.skipped:
        gates = {v.gate: v for v in entry.eligibility.blocking}
        #: 모름이 거부보다 **먼저** 막혀 있다는 전제를 테스트가 직접 확인한다.
        order = [v.gate for v in entry.eligibility.blocking]
        assert order.index(EligibilityGate.ACTIVATION_ZONE) < order.index(
            EligibilityGate.TRIGGER_CONDITION
        )
        assert gates[EligibilityGate.ACTIVATION_ZONE].validity is ActionValidity.UNKNOWN
        assert gates[EligibilityGate.TRIGGER_CONDITION].validity is ActionValidity.INVALID

        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
        assert entry.code is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# G. 관측 경계 · 어휘
# ======================================================================


def test_11_the_split_reads_nothing_the_viewer_may_not_see(board):
    """
    **가려진 정보를 지어내지 않는다.**

    측정한 경계: 상대의 뒷면 세트 카드는 보는 쪽에게 ``card_id`` 조차 ``None``
    이고, 주인 쪽에서는 보인다. 까닭을 가르는 코드는 ``missing_rules(view,
    context)`` 로 **평가가 받은 것과 같은 관측**만 받으므로 이 경계를 넘지
    않는다.

    세 가지를 확인한다.

    1. 경계가 살아 있다 (보는 쪽은 ``card_id`` 를 못 본다).
    2. 가려진 정체가 ``reason`` · ``notes`` 로 **새지 않는다.**
    3. 가려진 사실에서 **규칙 이름을 지어내지 않는다** — 정보 쪽 ``UNKNOWN``
       의 ``missing_rules`` 는 빈 튜플이고 ``missing_rule`` 은 ``None`` 이다.
    """
    state, facedown = board
    condition = IsMonster(facedown)
    opponent = seen_by(state, viewer=MINE)
    owner = seen_by(state, viewer=THEIRS)

    # 1. 관측 경계
    assert opponent.find(facedown).card_id is None, "보는 쪽은 정체를 못 본다"
    assert owner.find(facedown).card_id == PLAIN, "주인은 자기 세트를 본다"

    candidate = collected(opponent, condition)
    _, gate = condition_gate(opponent, condition)

    assert candidate.status is TriggerStatus.UNKNOWN
    assert candidate.code is ValidationCode.INFORMATION_UNAVAILABLE

    # 2. 누출 없음
    spoken = candidate.reason + " " + " ".join(candidate.notes) + " " + gate.result.reason
    assert str(PLAIN) not in spoken

    # 3. 가려진 사실을 규칙 미구현으로 바꾸지 않는다
    context = ConditionContext(
        player=MINE,
        source=state.player(MINE).monster_zone[0].instance_id,
        effect_ref=WATCHED,
    )
    assert condition.missing_rules(opponent, context) == ()
    assert gate.result.missing_rule is None


def test_12_no_new_vocabulary_was_added():
    """
    §7 — 새 ``ValidationCode`` · 새 status 를 만들지 않았다. 측정값 48개 그대로.
    """
    assert len(list(ValidationCode)) == 48
    assert len(list(ActionValidity)) == 3
    assert len(list(TriggerStatus)) == 4
    assert len(list(ChainInsertion)) == 3
