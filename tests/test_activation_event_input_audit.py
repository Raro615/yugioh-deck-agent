"""
Phase 3-E-30 — 발동 열거의 **사건 입력 계약** 감사.

이번 Phase 는 ``Duel._activation_actions`` 가 사건 없이 후보를 만드는 것이
정상적인 **상태 기반 발동 열거**인지, 아니면 사건 기반 트리거와 잘못 결합되어
있는지를 감사한다. Trigger 시스템의 구현이나 production 연결은 하지 않는다.

측정으로 드러난 사실 넷

1. **production 에 ``activation_actions()`` 라는 공개 함수는 없다.**
   있는 것은 ``Duel._activation_actions`` (private) 뿐이고, 같은 이름의 공개
   함수는 ``tests/test_trigger_connectivity_audit.py`` 의 테스트 도우미다.

2. ``_activation_actions`` 는 **사건을 하나도 읽지 않는다.** AST 로 재면
   ``self.state`` · ``card.card_id`` · ``card.instance_id`` ·
   ``definition.cost`` 뿐이다. ``TimingEvent`` · ``TimingPoint`` ·
   ``TriggerCandidate`` · journal · chain · priority 를 읽지 않는다.
   (타이밍 · 우선권 · 체인은 **관문**(``_activation_gate``)이 본다 — 열거와
   판정이 나뉘어 있다.)

3. 등록된 **실행 가능한 효과 13개는 전부 통상 마법 · 속공 마법 · 함정**이다.
   유발 효과(trigger effect)는 하나도 없다. 그래서 "사건이 없으면 못 세는
   효과" 가 열거 대상에 애초에 들어 있지 않다.

4. 함정은 **후보가 되지 않고**, 그 까닭이 이름 붙은 "없는 규칙" 으로 남는다 —
   ``trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 —
   공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)``.
   즉 사건 의존 효과가 **조용히** 일반 발동으로 섞이는 일이 없다.

이 파일은 production 을 고치지 않고 위 계약을 고정한다.
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    MONSTER_ACTIVATION_MISSING,
    TRAP_TRIGGER_MISSING,
    ActionValidator,
)
from engine.activation_timing import ActivationTiming
from engine.duel import Duel
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1

#: 공식 DB 의 ``type_mask`` 비트. ``core.constants`` 에서 읽는다.
from core.constants import TYPE_QUICKPLAY, TYPE_SPELL, TYPE_TRAP  # noqa: E402

#: 범주마다 한 장. **이 카드들의 규칙을 추측하지 않는다** — 종류는 공식 DB 의
#: ``type_mask`` 로 확인하고(``test_05``), 이름은 공식 DB 의 것을 쓴다.
POT_OF_GREED = 55144522
"""통상 마법. 대상도 비용도 없다."""
MYSTICAL_SPACE_TYPHOON = 5318639
"""속공 마법. 대상이 필요하다."""
FINE = 92595643
"""함정."""


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def function_body(path: str, name: str) -> ast.FunctionDef:
    """docstring 을 뺀 함수 본문 노드. **설명이 아니라 코드를 읽는다.**"""
    tree = ast.parse(source_of(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = [
                stmt
                for stmt in node.body
                if not (
                    isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                )
            ]
            return ast.Module(body=body, type_ignores=[])
    raise AssertionError(f"{path} 에 {name} 이 없습니다")


def names_in(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


# ======================================================================
# 판 — 실제 카드 정의가 붙은 판이어야 관문이 판정할 수 있다
# ======================================================================


def board(repository, card_id, zone=Zone.HAND, *, give_target=False):
    """
    그 카드 한 장을 ``zone`` 에 둔 판. 정의 없이 만들면 모든 판정이
    ``CARD_DEFINITION_UNAVAILABLE`` 로 멈추므로 **리포지토리를 넘긴다.**
    """
    state = GameState.create(
        repository, decks=([card_id] * 6, [POT_OF_GREED] * 6), seed=1
    )
    state.draw(MINE, 2)
    state.draw(THEIRS, 2)
    instance = state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    if zone is not Zone.HAND:
        instance = state.move(
            instance, zone, to_player=MINE, position=Position.FACEDOWN
        )
    if give_target:
        #: 상대 필드에 앞면 마법 한 장 — 대상이 필요한 효과의 대상이 된다.
        theirs = state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.HAND)
        state.move(theirs, Zone.SZONE, to_player=THEIRS, position=Position.FACEUP)
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    return state, instance.instance_id


def duel_of(state) -> Duel:
    return Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=state.turn.turn_player, phase=state.turn.phase
        ),
    )


def activations_for(duel, instance):
    """그 카드를 출처로 하는 **``ACTIVATE_EFFECT``** 후보만."""
    return [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.source == instance and action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


# ======================================================================
# A. 사건 의존성 — 열거는 사건을 읽지 않는다
# ======================================================================

#: 사건 · 트리거 계층의 이름들. 열거 함수가 하나라도 읽으면 결합된 것이다.
EVENT_NAMES = frozenset(
    {
        "TimingEvent",
        "TimingPoint",
        "TriggerCandidate",
        "TriggerSpec",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "TriggerChainIntegrator",
        "EventJournal",
        "JournalEvent",
        "StateDelta",
        "journal",
        "event",
        "events",
        "point",
        "deltas",
    }
)


def test_01_the_public_name_is_a_test_helper_not_production():
    """
    **이름부터 바로잡는다.** production 에 ``activation_actions()`` 는 없다.

    있는 것은 ``Duel._activation_actions`` 뿐이고, 같은 이름의 공개 함수는
    테스트 도우미다. 감사 대상을 잘못 잡으면 결론도 틀린다.
    """
    duel_src = source_of("engine/duel.py")
    assert "def _activation_actions" in duel_src
    #: 공개 함수는 없다 — 들여쓰기 없는 ``def activation_actions`` 가 없다.
    assert "\ndef activation_actions" not in duel_src

    production_public = [
        path
        for path in PROJECT_ROOT.glob("engine/**/*.py")
        if "__pycache__" not in str(path)
        and "\ndef activation_actions" in path.read_text(encoding="utf-8")
    ]
    assert production_public == []

    #: 공개 이름은 테스트 쪽에만 있다.
    helper = source_of("tests/test_trigger_connectivity_audit.py")
    assert "def activation_actions(" in helper


def test_02_the_enumerator_reads_no_event(repository):
    """
    §4 — ``_activation_actions`` 는 사건을 하나도 읽지 않는다.

    **docstring 이 아니라 코드**를 읽는다 (AST). 그리고 "읽지 않는다" 를
    증명하려면 **무엇을 읽는지**도 적어야 한다.
    """
    body = function_body("engine/duel.py", "_activation_actions")
    used = names_in(body)

    leaked = used & EVENT_NAMES
    assert leaked == set(), f"열거가 사건을 읽는다: {sorted(leaked)}"

    #: 실제로 읽는 것 — 판과 등록소와 정의의 비용뿐이다.
    assert {"state", "card_id", "instance_id", "cost"} <= used
    assert "activatable_effects" in used
    assert "target_combinations" in used


def test_03_timing_and_priority_live_in_the_gate_not_the_enumerator():
    """
    §6 — **열거와 판정이 나뉘어 있다.**

    타이밍 · 우선권 · 체인을 열거가 보지 않는 것은 빠뜨린 것이 아니라
    ``_activation_gate`` 가 보기 때문이다. 둘을 따로 재서 그것을 보인다.
    """
    enumerator = names_in(function_body("engine/duel.py", "_activation_actions"))
    gate = names_in(function_body("engine/duel.py", "_activation_gate"))

    #: 열거는 흐름을 보지 않는다.
    assert {"chain", "priority"} & enumerator == set()
    #: 관문은 셋 다 본다.
    assert {"chain", "priority", "ActivationTimingChecker"} <= gate
    assert {"validate", "can_activate"} <= gate


def test_04_activation_timing_declares_a_point_that_nobody_passes():
    """
    **감사 소견 (고치지 않았다).**

    ``ActivationTiming`` 에는 ``point`` 칸이 있고 docstring 이 "``None`` 은
    **모른다** 이지 '시점이 없다' 가 아니다" 라고 적는다. 그런데

    * ``ActivationTimingChecker.check`` 는 ``point`` 를 **읽지 않는다**
      (직렬화에서만 쓴다),
    * 그것을 넘기는 production 호출자도 **없다**.

    즉 사건을 받을 **자리는 이미 선언되어 있고 비어 있다.** 이을 때 이 자리가
    먼저 보이도록 지금 상태를 고정한다.
    """
    fields = {f.name for f in dataclasses.fields(ActivationTiming)}
    assert "point" in fields

    #: ``check`` 본문이 ``point`` 를 읽지 않는다.
    check = names_in(function_body("engine/activation_timing.py", "check"))
    assert "point" not in check

    #: ``point`` 를 읽는 자리는 직렬화뿐이다.
    timing_src = source_of("engine/activation_timing.py")
    reading = [
        line.strip()
        for line in timing_src.splitlines()
        if ".point" in line and not line.strip().startswith("#")
    ]
    assert reading, "측정이 잘못되었다 — point 를 읽는 줄이 있어야 한다"
    for line in reading:
        assert "canonical_state" in line or "data[" in line or "self.point is not None" in line

    #: production 호출자가 ``point`` 를 넘기지 않는다.
    for module in ("engine/duel.py", "engine/response.py"):
        src = source_of(module)
        for chunk in src.split("ActivationTiming(")[1:]:
            head = chunk[: chunk.index(")")] if ")" in chunk else chunk[:200]
            assert "point" not in head, f"{module} 가 point 를 넘긴다: {head}"


# ======================================================================
# B. 효과 범주 — 사건 의존 효과가 열거에 섞이는가
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_05_every_executable_effect_is_a_spell_or_a_trap(repository):
    """
    §5 · §9 — 등록된 실행 가능한 효과의 **카드 범주를 공식 DB 로** 확인한다.

    통상 마법 · 속공 마법 · 함정뿐이고 **유발 효과(몬스터의 트리거)는 하나도
    없다.** 그래서 "사건이 있어야 세는 효과" 가 열거 대상에 들어 있지 않다.
    """
    seen: dict[str, int] = {}
    for entry in EFFECT_LIBRARY:
        if not entry.executable:
            continue
        card = repository.get(entry.definition.effect_ref.card_id)
        assert card is not None, "등록된 효과의 카드가 공식 DB 에 있어야 한다"
        mask = card.type_mask
        #: 마법 또는 함정이다 — 몬스터 효과가 아니다.
        assert mask & (TYPE_SPELL | TYPE_TRAP), f"{card.name} mask=0x{mask:x}"
        if mask & TYPE_TRAP:
            label = "TRAP"
        elif mask & TYPE_QUICKPLAY:
            label = "QUICKPLAY"
        else:
            label = "SPELL"
        seen[label] = seen.get(label, 0) + 1

    #: 측정값 (3-E-30). 숫자가 바뀌면 이 Phase 의 결론을 다시 봐야 한다.
    assert seen == {"SPELL": 6, "QUICKPLAY": 3, "TRAP": 4}, seen


@requires_official_db
@pytest.mark.real_card
def test_06_an_ordinary_spell_becomes_an_activate_effect_candidate(repository):
    """
    §20-5 — 보통의 상태 기반 발동은 기존 ``ACTIVATE_EFFECT`` 로 나온다.

    사건이 없어도 나오는 것이 **맞다** — "지금 이 통상 마법을 발동할 수
    있는가" 는 과거 사건을 묻지 않는다.
    """
    state, instance = board(repository, POT_OF_GREED)
    duel = duel_of(state)

    actions = activations_for(duel, instance)

    assert len(actions) == 1
    assert actions[0].kind is PlayerActionKind.ACTIVATE_EFFECT
    assert actions[0].actor == MINE
    assert actions[0].effect_ref == EffectRef(POT_OF_GREED, 0)
    assert actions[0].targets == ()


@requires_official_db
@pytest.mark.real_card
def test_07_a_trap_never_becomes_an_ordinary_activation_candidate(repository):
    """
    §17 의 핵심 질문 — **사건 의존 효과가 일반 발동으로 섞이는가.**

    함정은 패에 있든 세트되어 있든 ``ACTIVATE_EFFECT`` 후보가 **되지 않는다.**
    그리고 막힌 까닭이 이름 붙은 "없는 규칙" 으로 남는다 — 그 문장이 바로
    "사건(``SetCode(EVENT_*)``) 을 구분할 수 없다" 다.

    **``INVALID`` 가 아니라 ``UNKNOWN`` 인 것이 중요하다** — 실제 규칙은
    함정 발동을 허락하므로, 금지라고 적으면 거짓이 된다.
    """
    for zone in (Zone.HAND, Zone.SZONE):
        state, instance = board(repository, FINE, zone)
        duel = duel_of(state)
        view = GameStateView.from_state(state, viewer=MINE)
        validator = ActionValidator(view)
        action = PlayerAction.activate_effect(
            actor=MINE, source=instance, effect_ref=EffectRef(FINE, 0)
        )

        assert activations_for(duel, instance) == [], f"{zone.value} 에서 후보가 났다"

        verdict = validator.validate(action)
        assert verdict.validity is ActionValidity.UNKNOWN
        assert verdict.validity is not ActionValidity.INVALID
        assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert verdict.missing_rule == TRAP_TRIGGER_MISSING
        #: 그 문장이 **사건**을 가리킨다.
        assert "EVENT_" in verdict.missing_rule
        assert "유발 조건" in verdict.missing_rule


def test_08_the_missing_rules_name_the_event_gap_explicitly():
    """
    저장소가 **스스로** 사건 구분이 없다고 적어 두었다. 두 문장이 서로 다른
    이유를 말하는 것이 핵심이다 (Phase 3-E-16 이 나눴다).
    """
    assert "EVENT_" in TRAP_TRIGGER_MISSING
    assert "유발 조건" in TRAP_TRIGGER_MISSING
    #: 몬스터는 **다른 이유**다 — 효과 분류가 없어 속도조차 정할 수 없다.
    assert MONSTER_ACTIVATION_MISSING != TRAP_TRIGGER_MISSING
    assert "분류" in MONSTER_ACTIVATION_MISSING


@requires_official_db
@pytest.mark.real_card
def test_09_a_targeting_effect_depends_on_the_board_not_on_an_event(repository):
    """
    대상이 필요한 효과는 **판에 대상이 있을 때만** 후보가 된다. 사건이 아니라
    판이 정한다 — 그래서 사건 입력이 없어도 답이 흔들리지 않는다.
    """
    without, instance = board(repository, MYSTICAL_SPACE_TYPHOON)
    with_target, instance2 = board(
        repository, MYSTICAL_SPACE_TYPHOON, give_target=True
    )

    assert activations_for(duel_of(without), instance) == []
    chosen = activations_for(duel_of(with_target), instance2)
    assert len(chosen) == 1
    assert len(chosen[0].targets) == 1


# ======================================================================
# C. 부작용 · 결정론 · 숨은 정보
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_10_enumeration_is_deterministic_and_side_effect_free(repository):
    """
    §15 — 같은 판에서 몇 번 불러도 같은 답이고, 판도 RNG 도 바뀌지 않는다.
    """
    state, _ = board(repository, MYSTICAL_SPACE_TYPHOON, give_target=True)
    duel = duel_of(state)
    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))

    before_hash = state.state_hash()
    before_rng = state.rng.getstate()

    runs = [
        tuple(
            action.canonical_state()
            for action in duel._activation_actions(MINE, validator)
        )
        for _ in range(5)
    ]

    assert len(set(runs)) == 1, "같은 판에서 답이 흔들린다"
    assert runs[0], "후보가 하나도 없으면 이 시험이 흐려진다"
    assert state.state_hash() == before_hash, "열거가 판을 바꿨다"
    assert state.rng.getstate() == before_rng, "열거가 RNG 를 소비했다"


@requires_official_db
@pytest.mark.real_card
def test_11_enumeration_does_not_need_hidden_information(repository):
    """
    §14 — 상대의 뒷면 카드는 **정체를 모르는 채로** 남는다.

    열거는 ``self.state`` 를 읽지만 관문은 ``GameStateView`` 로 판정한다.
    상대의 뒷면 카드는 자리와 쥔 쪽만 보이고 ``card_id`` 는 ``None`` 이다 —
    그래서 열거 결과가 상대의 정체에 의존할 수 없다.
    """
    state, mine = board(repository, POT_OF_GREED)
    hidden = state.create_instance(FINE, owner=THEIRS, zone=Zone.HAND)
    facedown = state.move(
        hidden, Zone.SZONE, to_player=THEIRS, position=Position.FACEDOWN
    )
    view = GameStateView.from_state(state, viewer=MINE)
    seen = view.find(facedown.instance_id)

    assert seen.controller == THEIRS
    assert seen.zone is Zone.SZONE
    assert seen.card_id is None, "상대의 뒷면 정체가 보인다"
    assert seen.definition is None

    #: 내 후보는 그 카드와 무관하게 그대로다.
    duel = duel_of(state)
    assert len(activations_for(duel, mine)) == 1


def test_12_the_enumerator_reads_the_board_the_gate_reads_the_view():
    """
    §14 — 관측 경계가 어디에 있는지 적어 둔다.

    열거는 ``self.state`` (판) 를 읽어 **자리**를 훑고, 판정은
    ``GameStateView`` 만 읽는다 (ADR-007). 열거가 판을 읽는 것은 자기
    자리의 카드를 세기 위해서이고, 상대의 가려진 정보를 쓰지 않는다.
    """
    sources = names_in(function_body("engine/duel.py", "_activation_sources"))
    assert "state" in sources and "player" in sources
    #: 자기 좌석의 패와 마법/함정 존만 본다.
    body = source_of("engine/duel.py").split("def _activation_sources")[1].split(
        "\n    def "
    )[0]
    assert "player.hand" in body and "Zone.SZONE" in body
    assert "1 - seat" not in body, "상대 자리를 훑으면 안 된다"


# ======================================================================
# D. 트리거 파이프라인은 여전히 닿지 않는다
# ======================================================================


def test_13_the_activation_path_never_touches_the_trigger_pipeline():
    """
    §7 · §10 — 발동 경로의 어느 함수도 트리거 계층을 부르지 않는다.

    ``TimingPoint`` 는 ``activation_timing`` 이 **열거형으로만** 쓰므로
    (``ActivationTiming.point`` 의 타입) 파이프라인 호출로 세지 않는다 —
    ``test_04`` 가 그 칸이 비어 있음을 따로 고정한다.
    """
    callers = (
        ("engine/duel.py", "_activation_actions"),
        ("engine/duel.py", "_activation_sources"),
        ("engine/duel.py", "_activation_gate"),
        ("engine/duel.py", "legal_actions"),
    )
    pipeline = {
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "TriggerChainIntegrator",
        "TriggerCandidate",
        "TriggerSpec",
        "TimingEvent",
        "TimingCoordinator",
    }
    for module, name in callers:
        used = names_in(function_body(module, name))
        assert used & pipeline == set(), f"{name} 이 {sorted(used & pipeline)} 을 쓴다"


def test_14_the_dormant_modules_are_still_unreachable_from_the_duel():
    """
    ``engine/duel.py`` 의 import 전이 폐쇄에 트리거 파이프라인을 **만드는**
    모듈이 없다 (3-E-27 ~ 3-E-29 와 같은 측정, HEAD 에서 다시 센다).
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

    for dormant in (
        "engine/trigger_chain.py",
        "engine/trigger_order.py",
        "engine/timing.py",
        "engine/event_pipeline.py",
    ):
        assert dormant not in reached


@requires_official_db
@pytest.mark.real_card
def test_15_the_canonical_legal_action_path_is_unchanged(repository):
    """
    §20-9 — 정론 경로가 그대로다. production 을 고치지 않았으므로 달라질
    이유가 없고, 그것을 동작으로 확인한다.
    """
    state, _ = board(repository, POT_OF_GREED, give_target=True)
    duel = duel_of(state)

    first = duel.legal_actions(MINE)
    second = duel.legal_actions(MINE)

    assert [a.canonical_state() for a in first.allowed] == [
        a.canonical_state() for a in second.allowed
    ]
    assert all(isinstance(a, PlayerAction) for a in first.allowed)
    assert any(a.kind is PlayerActionKind.ACTIVATE_EFFECT for a in first.allowed)
    #: 보류는 ``PlayerAction`` 을 들고 있지 않다 — ``UNKNOWN`` 이 구조적으로
    #: 후보가 될 수 없다.
    for held in first.withheld:
        assert isinstance(held.kind, PlayerActionKind)
        assert not isinstance(held, PlayerAction)
