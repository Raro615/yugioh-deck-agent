"""
Phase 3-E-28 — ``_judge`` 와 관문의 **이중 평가 정합성** 감사.

3-E-27 이 다음 후보로 지목한 걱정은 이것이었다.

    ``_judge`` 는 ``ConditionContext`` 를 ``card.controller`` 로 만들고,
    관문 쪽은 ``candidate.controller`` 로 만든다. 같은 뜻인가?

**측정 결과: 같은 뜻이 아니라 같은 값이다.** 이름이 아니라 대입이 그렇게
만든다 — ``TriggerCollector._judge`` 가 ``base["controller"] = card.controller``
로 후보를 만들고, 관문은 그 후보의 값을 그대로 쓴다. 그리고 두 계층은
``TriggerChainIntegrator.collect_and_order`` 에서 **같은 ``GameStateView``
객체**를 받는다.

이 파일은 그 계약을 고정하고, **고정하지 않은 것도 적어 둔다** (§4-C).

세 가지를 섞지 않는다 (저장소가 이미 셋으로 나눠 둔 것이다).

* ``owner``       — 카드의 주인
* ``controller``  — 지금 그 카드를 쥐고 있는 쪽
* ``actor``       — 이 행위를 시도하는 쪽 (``engine/action.py`` · ADR §22)

이 Phase 는 **production code 를 고치지 않았다.** 감사다.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction
from engine.action_validation import ActionValidator
from engine.condition import Always, ConditionResult, UnimplementedRule
from engine.condition.context import ConditionContext, PlayerRef
from engine.condition.model import ControllerIs
from engine.effect import CardDrawn, DrawOperation, EffectDefinition, EffectProvenance
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
)
from engine.trigger_chain import TriggerChainIntegrator
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1
WATCHER = 1000
"""트리거를 등록할 카드. 이 카드의 **의미를 주장하지 않는다** — 껍데기다."""
PLAIN = 1001
WATCHED = EffectRef(WATCHER, 0)


# ======================================================================
# 판 — 양쪽에 ``WATCHER`` 를 하나씩 둔다 (상대가 쥔 트리거가 필요하다)
# ======================================================================


def new_state() -> GameState:
    game = GameState.create(
        decks=(
            [WATCHER, WATCHER, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN],
            [WATCHER, PLAIN, PLAIN, PLAIN, PLAIN],
        ),
    )
    game.draw(MINE, 3)
    game.draw(THEIRS, 3)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.move(game.player(THEIRS).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def spec(condition=None) -> TriggerSpec:
    return TriggerSpec(
        WATCHED,
        TimingPoint.CARD_DRAWN,
        condition=condition,
        activates_from=frozenset({Zone.MZONE}),
    )


def drawn() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(2)))


def judged(view, condition):
    """``_judge`` 의 후보와 관문의 판정을 **둘 다** 돌려준다."""
    declared = spec(condition)
    candidate = TriggerCollector(view, TriggerRegistry((declared,))).collect(
        drawn()
    ).candidates[0]
    eligibility = TriggerEligibilityJudge(view).judge(candidate, declared, drawn())
    return candidate, eligibility


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# ======================================================================
# A. 같은 값인가 — 이름이 아니라 대입을 본다
# ======================================================================


def test_01_the_candidates_controller_is_assigned_from_the_cards_controller(view):
    """
    **이름이 의미를 정하지 않는다.** 그래서 값을 본다.

    ``_judge`` 가 만든 후보마다 ``candidate.controller`` 가 같은 관측에서 읽은
    ``card.controller`` 와 같은지 확인한다 — 양쪽 플레이어의 카드 전부에 대해.
    """
    collection = TriggerCollector(
        view, TriggerRegistry((spec(),))
    ).collect(drawn())

    assert collection.candidates, "후보가 하나도 없다"
    seen = set()
    for candidate in collection:
        card = view.find(candidate.source)
        assert card is not None
        assert candidate.controller == card.controller
        assert candidate.source == card.instance_id
        seen.add(card.controller)
    #: 한쪽만 보고 "같다" 고 결론내지 않는다 — 양쪽이 섞여 있어야 의미가 있다.
    assert seen == {MINE, THEIRS}, f"양쪽 controller 가 섞여 있어야 한다: {seen}"


def test_02_the_assignment_is_visible_in_the_source(view):
    """
    값이 같은 것이 **우연이 아니라 대입** 때문임을 원본에서 확인한다.

    ``_judge`` 의 ``base`` 가 ``card.controller`` 를 그대로 싣고, 관문은 그
    후보의 값을 쓴다. 그래서 둘은 **같은 하나의 사실**이다.
    """
    source = source_of("engine/trigger.py")
    judge_body = source.split("def _judge")[1].split("\n    def ")[0]
    assert '"controller": card.controller' in judge_body
    assert '"source": card.instance_id' in judge_body

    gate_body = source.split("def _trigger_condition")[1].split("\n    def ")[0]
    assert "player=candidate.controller" in gate_body
    assert "source=candidate.source" in gate_body


def test_03_both_layers_receive_the_same_view_object(view, state):
    """
    같은 값이어도 **다른 관측**으로 평가하면 다른 답이 날 수 있다.

    production 배선(``collect_and_order``)은 **세 계층 전부**에 같은
    ``GameStateView`` 객체를 넘긴다 — 수집기 · 판정기 · 정렬기.
    """
    body = source_of("engine/trigger_chain.py").split("def collect_and_order")[1].split(
        "\n    def "
    )[0]
    #: 세 번 — ``TriggerCollector`` · ``TriggerEligibilityJudge`` · ``TriggerOrderer``.
    assert body.count("self._view") == 3, "세 계층이 같은 관측을 받아야 한다"
    for layer in ("TriggerCollector(", "TriggerEligibilityJudge(", "TriggerOrderer("):
        head = body.split(layer)[1][:40]
        assert "self._view" in head, f"{layer} 가 다른 관측을 받는다"

    integrator = TriggerChainIntegrator(view, TriggerRegistry((spec(),)))
    #: 노출된 관측이 우리가 넘긴 그 객체다 (사본이 아니다).
    assert integrator.view is view


# ======================================================================
# B. 같은 조건을 두 번 평가했을 때 — 결과가 같은가
# ======================================================================

#: controller 가 틀리면 **답이 뒤집히는** 조건을 일부러 넣었다.
#: ``ControllerIs`` 가 그렇다 — 주체를 잘못 잡으면 참/거짓이 바뀐다.
DOUBLE_EVALUATION_CASES = (
    ("조건 TRUE", Always(), TriggerStatus.ELIGIBLE, ValidationCode.OK),
    (
        "조건 FALSE",
        Always(ConditionResult.FALSE),
        TriggerStatus.INELIGIBLE,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    ),
    (
        "규칙 미구현",
        UnimplementedRule("체인 위의 카드 수"),
        TriggerStatus.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    ),
    (
        "ControllerIs(자신)",
        ControllerIs(PlayerRef.CONTROLLER),
        TriggerStatus.ELIGIBLE,
        ValidationCode.OK,
    ),
    (
        "ControllerIs(상대)",
        ControllerIs(PlayerRef.OPPONENT),
        TriggerStatus.INELIGIBLE,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    ),
)


@pytest.mark.parametrize(
    "label,condition,expected_status,expected_code", DOUBLE_EVALUATION_CASES
)
def test_04_the_two_layers_agree(view, label, condition, expected_status, expected_code):
    """
    **주체를 잘못 잡으면 답이 뒤집히는 조건**으로 두 계층을 비교한다.

    ``ControllerIs(자신)`` 과 ``ControllerIs(상대)`` 가 핵심이다 — 한쪽이
    다른 주체로 평가하고 있었다면 이 두 줄에서 반대 답이 나온다.
    """
    candidate, eligibility = judged(view, condition)
    gate = eligibility.gate(EligibilityGate.TRIGGER_CONDITION)

    assert candidate.status is expected_status
    assert candidate.code is expected_code
    assert gate.code is expected_code
    #: 판정 어휘가 달라도(후보는 ``TriggerStatus``, 관문은 ``ActionValidity``)
    #: **가리키는 사실은 같다.**
    if expected_status is TriggerStatus.ELIGIBLE:
        assert gate.validity is ActionValidity.VALID
    elif expected_status is TriggerStatus.INELIGIBLE:
        assert gate.validity is ActionValidity.INVALID
    else:
        assert gate.validity is ActionValidity.UNKNOWN


def test_05_the_collector_and_the_judge_answer_different_questions(view):
    """
    **의도된 차이** — 중복 평가가 곧 버그는 아니다.

    수집기는 "타이밍이 맞고 조건이 참인가" 까지만 본다. 판정기는 거기에 자리 ·
    실행 권위 · 비용을 더한다. 그래서 같은 후보가 수집기에서 ``ELIGIBLE``,
    판정기에서 ``UNKNOWN`` 일 수 있고, 그것은 모순이 아니다 —
    ``TriggerCandidate.status`` 의 docstring 이 그렇게 적는다.
    """
    candidate, eligibility = judged(view, Always())

    assert candidate.status is TriggerStatus.ELIGIBLE
    #: 정의를 등록하지 않았으므로 실행 권위를 확인할 수 없다 (ADR-006).
    assert eligibility.status is TriggerStatus.UNKNOWN
    authority = eligibility.gate(EligibilityGate.EXECUTION_AUTHORITY)
    assert authority.validity is ActionValidity.UNKNOWN
    assert authority.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: 조건 관문은 통과했다 — 어긋난 것이 아니라 **다른 질문**이다.
    assert eligibility.gate(EligibilityGate.TRIGGER_CONDITION).validity is (
        ActionValidity.VALID
    )
    doc = " ".join((TriggerCandidate.status.__doc__ or "").split()) or " ".join(
        source_of("engine/trigger.py")
        .split("status: TriggerStatus = TriggerStatus.UNKNOWN")[1]
        .split('"""')[1]
        .split()
    )
    assert "다를 수 있다" in doc


# ======================================================================
# C. edge case — 엔진이 표현할 수 있는 것만 시험한다
# ======================================================================


def test_06_a_card_controlled_by_the_non_turn_player_is_judged_for_its_controller(view):
    """
    **상대가 쥔 카드의 트리거는 상대의 것이다.** (표현 가능)

    같은 사건에 양쪽 카드가 반응할 수 있고, 각자의 ``controller`` 로 평가된다.
    한쪽 주체로 뭉개면 ``ControllerIs(자신)`` 이 한쪽에서 거짓이 된다.
    """
    declared = spec(ControllerIs(PlayerRef.CONTROLLER))
    collection = TriggerCollector(view, TriggerRegistry((declared,))).collect(drawn())

    by_controller = {}
    for candidate in collection:
        eligibility = TriggerEligibilityJudge(view).judge(candidate, declared, drawn())
        by_controller.setdefault(candidate.controller, []).append(
            (candidate, eligibility)
        )

    assert set(by_controller) == {MINE, THEIRS}
    #: **양쪽 다** "자신이 쥐고 있다" 가 참이다 — 각자의 주체로 봤기 때문이다.
    for candidates in by_controller.values():
        for candidate, eligibility in candidates:
            assert candidate.code is ValidationCode.OK
            assert eligibility.gate(EligibilityGate.TRIGGER_CONDITION).code is (
                ValidationCode.OK
            )


def test_07_the_turn_player_is_not_the_subject_of_the_condition(state):
    """
    **턴 플레이어와 조건의 주체는 다르다.** (표현 가능)

    턴을 넘겨도 후보의 ``controller`` 는 바뀌지 않는다 — 조건의 주체는 카드를
    쥔 쪽이고 턴과 무관하다. 그래서 상대 턴의 함정이 표현된다.
    """
    before = GameStateView.from_state(state, viewer=MINE)
    first = {c.source: c.controller for c in TriggerCollector(
        before, TriggerRegistry((spec(),))
    ).collect(drawn())}

    state.turn = state.turn.begin_next_turn()
    assert state.turn.turn_player == THEIRS

    after_view = GameStateView.from_state(state, viewer=MINE)
    after = {c.source: c.controller for c in TriggerCollector(
        after_view, TriggerRegistry((spec(),))
    ).collect(drawn())}

    assert first == after, "턴이 바뀌어도 조건의 주체는 그대로다"


def test_08_a_persistent_control_change_is_not_representable(state):
    """
    **표현 불가를 기록한다 — 없는 기반을 만들지 않는다.**

    ``CardInstance.set_controller`` 는 있지만 저장소 어디서도 부르지 않고,
    ``ZoneContainer`` 가 존을 다시 색인할 때마다
    ``card.controller = self.owner`` 로 덮어쓴다. 그래서 "상대에게 컨트롤을
    빼앗긴 카드" 는 지금 엔진에서 **유지되지 않는다.**

    `candidate.controller != card.controller` 를 production 에서 만들 길이
    없다는 뜻이고, 그것이 §4-C 를 감사 소견으로만 남기는 근거다.
    """
    #: 1. 아무도 부르지 않는다.
    #: ``tests/`` 는 제외한다 — 이 파일 자신이 그 이름을 적고 있다.
    callers = [
        str(path.relative_to(PROJECT_ROOT))
        for path in PROJECT_ROOT.rglob("*.py")
        if "tests" not in path.parts
        and path.name != "card_instance.py"
        and "set_controller" in path.read_text(encoding="utf-8")
    ]
    assert callers == [], f"set_controller 를 부르는 자리가 생겼다: {callers}"

    #: 2. 존 연산이 덮어쓴다 — 실제로 해 본다.
    card = state.player(MINE).monster_zone[0]
    card.set_controller(THEIRS)
    assert card.controller == THEIRS, "직접 바꾸는 것 자체는 된다"
    state.move(
        state.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    assert card.controller == MINE, "존을 다시 색인하면 존 주인으로 돌아간다"


# ======================================================================
# D. 고정하지 않은 것 — 숨기지 않고 적는다
# ======================================================================


def test_09_judge_checks_the_effect_ref_but_not_the_controller(view, state):
    """
    **감사 소견 (고치지 않았다).**

    ``judge()`` 는 후보와 선언이 다른 효과를 가리키면 ``TriggerError`` 를
    던진다. 그런데 후보의 ``controller`` · ``source`` 가 관측과 어긋나는지는
    **확인하지 않는다.**

    손으로 만든 후보로 어긋나게 하면 한 번의 ``judge()`` 안에서 두 관문이
    서로 다른 "누가 쥐고 있는가" 를 쓴다 — 조건 관문은 후보의 값으로, 자리
    관문은 관측의 카드로 본다.

    **production 에서는 닿지 않는다**: ``collect_and_order`` 가 같은 관측에서
    후보를 만들고(``test_01``~``test_03``), 지속적 컨트롤 변경이 표현되지
    않으며(``test_08``), 트리거 계층 자체가 정론 경로에서 잠들어 있다
    (``test_11``). 그래서 지금 동작을 **그대로 고정**해 둔다 — 트리거 계층을
    이을 때 이 자리가 먼저 보이도록.
    """
    mine = state.player(MINE).monster_zone[0].instance_id
    assert view.find(mine).controller == MINE
    declared = spec(ControllerIs(PlayerRef.CONTROLLER))

    #: effect_ref 불일치는 **막는다.**
    with pytest.raises(TriggerError):
        TriggerEligibilityJudge(view).judge(
            TriggerCandidate(
                point=TimingPoint.CARD_DRAWN,
                effect_ref=EffectRef(WATCHER, 7),
                source=mine,
                controller=MINE,
            ),
            declared,
            drawn(),
        )

    #: controller 불일치는 **막지 않는다** — 지금의 사실이다.
    forged = TriggerCandidate(
        point=TimingPoint.CARD_DRAWN,
        effect_ref=WATCHED,
        source=mine,
        controller=THEIRS,  # 관측은 MINE 이라고 말한다
    )
    eligibility = TriggerEligibilityJudge(view).judge(forged, declared, drawn())

    condition = eligibility.gate(EligibilityGate.TRIGGER_CONDITION)
    zone = eligibility.gate(EligibilityGate.ACTIVATION_ZONE)
    #: 조건 관문은 **후보가 준** 주체로 봤다 → "자신이 쥐고 있다" 가 거짓
    assert condition.validity is ActionValidity.INVALID
    assert condition.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: 자리 관문은 **관측의 카드**로 봤다 → 통과
    assert zone.validity is ActionValidity.VALID
    #: 즉 한 판정 안에서 두 관문이 서로 다른 전제를 썼다.
    assert eligibility.status is TriggerStatus.INELIGIBLE


# ======================================================================
# E. production 경로 · 어휘 · 경계
# ======================================================================


def test_10_the_production_path_uses_the_actor_and_requires_it_to_control(state):
    """
    production 쪽은 **세 번째 값**을 쓴다 — ``action.actor`` 다.

    그리고 발동 요구가 ``ControllerIs(PlayerRef.CONTROLLER, action.source)``
    이므로, production 은 **``actor == card.controller`` 를 요구한다.** 그래서
    트리거 계층의 ``card.controller`` 가 나중에 그대로 ``actor`` 가 된다 —
    둘을 잇는 계약이 이미 코드에 있다.
    """
    validator_source = source_of("engine/action_validation.py")
    context_for = validator_source.split("def context_for")[1].split("\n    def ")[0]
    assert "player=action.actor" in context_for
    assert "source=action.source" in context_for

    activation = source_of("engine/activation.py").split("def _condition_context")[1][
        :400
    ]
    assert "player=action.actor" in activation

    #: 발동은 "자기가 쥔 카드인가" 를 묻는다 — 양쪽 발동 종류 모두.
    for fn in ("def _activate(", "def _activate_effect("):
        body = validator_source.split(fn)[1].split("\ndef ")[0]
        assert "ControllerIs(PlayerRef.CONTROLLER, action.source)" in body
        assert "SOURCE_NOT_CONTROLLED" in body

    #: 실제로도 그렇다 — 상대 카드로 발동하려 하면 거부된다.
    #: 그 요구를 **production 의 문맥으로** 직접 평가한다.
    #:
    #: ``validate()`` 를 끝까지 돌리지 않는 이유: 이 판의 카드는 합성 id 라
    #: 정의가 없어서 더 앞선 요구가 ``CARD_DEFINITION_UNAVAILABLE``(UNKNOWN)
    #: 로 멈춘다 — 그것 자체가 "모름을 거부로 바꾸지 않는다" 의 올바른 동작
    #: 이므로, 여기서는 controller 요구만 떼어 본다.
    their_monster = state.player(THEIRS).monster_zone[0]
    assert their_monster.controller == THEIRS
    seen = GameStateView.from_state(state, viewer=MINE)
    validator = ActionValidator(seen)
    requirement = ControllerIs(PlayerRef.CONTROLLER, their_monster.instance_id)

    #: 상대 카드를 내가 발동하려 한다 → actor(MINE) != controller(THEIRS) → 거짓
    mine_acting = validator.context_for(
        PlayerAction.activate_effect(
            actor=MINE, source=their_monster.instance_id, effect_ref=WATCHED
        )
    )
    assert mine_acting.player == MINE
    assert requirement.evaluate(seen, mine_acting) is ConditionResult.FALSE

    #: 쥔 쪽이 발동하면 참이다 — 즉 production 은 actor == controller 를 요구한다.
    owner_acting = validator.context_for(
        PlayerAction.activate_effect(
            actor=THEIRS, source=their_monster.instance_id, effect_ref=WATCHED
        )
    )
    assert owner_acting.player == THEIRS
    assert requirement.evaluate(seen, owner_acting) is ConditionResult.TRUE


def test_11_the_canonical_path_does_not_build_the_trigger_layer():
    """
    ``_judge`` 와 관문이 **둘 다** 정론 경로에서 잠들어 있다.

    ``engine/duel.py`` 의 import 전이 폐쇄에 ``engine.trigger`` 는 들어 있지만
    (``activation_timing`` 이 ``TimingPoint`` 열거형 하나를 쓴다), 두 계층을
    **생성하는** 모듈(``trigger_chain`` · ``timing`` · ``event_pipeline``)은
    들어 있지 않다. 그래서 이번 감사의 어떤 발견도 production blocker 가
    아니다.
    """
    def imported(path: str) -> set[str]:
        tree = ast.parse(source_of(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return {name for name in names if name.startswith("engine")}

    reached: set[str] = set()
    stack = ["engine/duel.py"]
    while stack:
        current = stack.pop()
        if current in reached:
            continue
        reached.add(current)
        for module in imported(current):
            base = module.replace(".", "/")
            for candidate in (base + ".py", base + "/__init__.py"):
                if (PROJECT_ROOT / candidate).exists() and candidate not in reached:
                    stack.append(candidate)

    #: 두 계층을 **만드는** 모듈은 정론 경로에 없다.
    for dormant in (
        "engine/trigger_chain.py",
        "engine/timing.py",
        "engine/event_pipeline.py",
    ):
        assert dormant not in reached
    #: production 검증 경로는 당연히 들어 있다 — 비교 대상이 살아 있음을 확인.
    assert "engine/action_validation.py" in reached
    assert "engine/activation.py" in reached


def test_12_the_repository_keeps_owner_controller_and_actor_apart():
    """
    세 개념이 **이미** 나뉘어 있다. 새 소유권 추상을 만들 이유가 없다.
    """
    #: ``class PlayerActionKind`` 가 먼저 나오므로 정확한 선언으로 자른다.
    action_doc = " ".join(
        source_of("engine/action.py")
        .split("class PlayerAction:")[1]
        .split('"""')[1]
        .split()
    )
    assert "actor" in action_doc and "controller" in action_doc
    assert "owner=0, controller=1, actor=1" in action_doc

    #: 조건 계층의 주체는 **문맥 상대적**이다 — 절대 번호가 아니다.
    context_doc = " ".join(source_of("engine/condition/context.py")
                           .split("class PlayerRef")[1].split('"""')[1].split())
    assert "문맥 상대적" in context_doc
    assert ConditionContext(player=MINE).opponent == THEIRS
    assert PlayerRef.CONTROLLER.resolve(ConditionContext(player=THEIRS)) == THEIRS


def test_13_nothing_about_the_observation_boundary_changed(state):
    """
    이번 Phase 는 관측 경계를 건드리지 않았다. ``controller`` 는 뒷면 카드도
    **공개 정보**이므로, 가려진 것을 추측할 필요가 애초에 없다.
    """
    facedown = state.move(
        state.player(THEIRS).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    seen = GameStateView.from_state(state, viewer=MINE).find(facedown.instance_id)

    #: 자리와 쥔 쪽은 보인다 — 정체는 보이지 않는다.
    assert seen.controller == THEIRS
    assert seen.zone is Zone.SZONE
    assert seen.card_id is None
    assert seen.definition is None
    #: 그래서 ``ControllerIs`` 가 **정체를 몰라도** 판정된다.
    doc = " ".join(source_of("engine/condition/model.py")
                   .split("class ControllerIs")[1].split('"""')[1].split())
    assert "정체를 몰라도" in doc
