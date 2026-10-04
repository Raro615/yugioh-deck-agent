"""
Phase 3-E-29 — ``TriggerCandidate`` → ``PlayerAction`` **변환 계약 감사**.

이번 Phase 의 목적은 변환을 구현하는 것이 아니라, 그 변환 계약이 지금
production architecture 에 **실제로 필요한지** 감사하는 것이다. 그래서 이
파일은 변환기를 만들지 않고 **지금의 계약을 측정해서 고정**한다.

측정으로 드러난 핵심 사실 셋

1. production 은 이미 ``ACTIVATE_EFFECT`` 를 만든다 — 그런데 입력이
   ``TriggerCandidate`` 가 아니라 **판 + 효과 등록소**다
   (``Duel._activation_actions``: ``_activation_sources`` →
   ``activatable_effects`` → ``target_combinations``).
   즉 "트리거를 Action 으로 바꾸는 자리" 가 비어 있는 것이 아니라,
   **Action 을 만드는 자리가 사건을 보지 않는다.**

2. ``TriggerCandidate`` 는 ``PlayerAction.activate_effect`` 가 요구하는 것 중
   ``actor`` · ``source`` · ``effect_ref`` **셋을 이미 전부** 들고 있다.
   빠진 것은 ``targets`` 하나이고, 그것은 후보가 아니라 **판에서 세는 값**
   이다 (production 도 그렇게 한다).

3. **두 모듈이 서로 다른 파이프라인을 선언한다.**
   ``engine/trigger.py`` 는 "실제 발동은 Action · 비용 · ``ChainLink`` 를
   거쳐야 한다" 고 적고, ``engine/trigger_chain.py`` 는 후보에서
   ``ChainLink`` 로 **바로** 간다. 대상도 비용도 없는 효과에서는 실제로
   ``PlayerAction`` 없이 링크가 만들어진다.

셋 다 **잠든 계층에서만** 일어나므로 production 결함이 아니다. 이 파일은
고치지 않고 **지금 동작을 그대로 고정**한다 — 이을 때 이 자리가 먼저 보이도록.
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.chain import Chain, ChainLink
from engine.condition import Always, IsMonster
from engine.cost import CandidateSource, ChoiceSpec, CostGroup
from engine.effect import (
    PRIMARY_TARGET,
    CardDrawn,
    CardOperation,
    DrawOperation,
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectImplementationRegistry,
    EffectProvenance,
    TargetBinding,
    TargetSpec,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.trigger import (
    TimingEvent,
    TimingPoint,
    TriggerCandidate,
    TriggerCollector,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
)
from engine.trigger_chain import ChainInsertion, TriggerChainIntegrator
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1
WATCHER = 1000
"""트리거를 등록할 카드. 이 카드의 **의미를 주장하지 않는다** — 껍데기다."""
PLAIN = 1001
WATCHED = EffectRef(WATCHER, 0)

#: 트리거 계층을 이루는 모듈들. production 도달성을 이 집합으로 센다.
TRIGGER_MODULES = (
    "engine/trigger.py",
    "engine/trigger_chain.py",
    "engine/trigger_order.py",
    "engine/timing.py",
    "engine/event_pipeline.py",
)

#: 트리거 계층의 이름들. ``TimingPoint`` 는 **일부러 뺀다** —
#: ``activation_timing`` 이 열거형으로만 쓰고 있고, 그것은 파이프라인을
#: 부르는 것이 아니다 (Phase 3-E-27 · 3-E-28 에서 측정).
TRIGGER_NAMES = frozenset(
    {
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "TriggerChainIntegrator",
        "TriggerCandidate",
        "TriggerEligibility",
        "TriggerOrderer",
        "TriggerOrdering",
        "TriggerSpec",
        "TriggerRegistry",
        "TimingEvent",
        "TimingCoordinator",
        "EventPipeline",
    }
)


# ======================================================================
# 판 · 도구
# ======================================================================


def new_state() -> "tuple[GameState, InstanceId]":
    game = GameState.create(
        decks=(
            [WATCHER, WATCHER, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN],
            [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN],
        ),
    )
    game.draw(MINE, 3)
    game.draw(THEIRS, 3)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    facedown = game.move(
        game.player(THEIRS).hand[0], Zone.SZONE, position=Position.FACEDOWN
    )
    game.turn.set_phase(Phase.MAIN1)
    return game, facedown.instance_id


@pytest.fixture
def board():
    return new_state()


def spec(*, zones=frozenset({Zone.MZONE})) -> TriggerSpec:
    return TriggerSpec(WATCHED, TimingPoint.CARD_DRAWN, activates_from=zones)


def drawn() -> TimingEvent:
    return TimingEvent.from_delta(CardDrawn(MINE, InstanceId(2)))


def free_definition() -> EffectDefinition:
    """대상도 비용도 없는 정의. 패를 1장 뽑는 모양만 갖는다."""
    return EffectDefinition(
        effect_ref=WATCHED,
        source_card_id=WATCHER,
        operations=(DrawOperation(1),),
        activation=Always(),
        cost=CostGroup(),
        provenance=EffectProvenance.official_lua(),
    )


def targeting_definition() -> EffectDefinition:
    """필드의 몬스터 1장을 **대상으로** 하는 모양. 실제 카드가 아니다."""
    return EffectDefinition(
        effect_ref=WATCHED,
        source_card_id=WATCHER,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=frozenset({Zone.MZONE}), owner=None, require=IsMonster()
                    )
                )
            )
        ),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        activation=Always(),
        cost=CostGroup(),
        provenance=EffectProvenance.official_lua(),
    )


def planned(view, definition):
    integrator = TriggerChainIntegrator(
        view,
        TriggerRegistry((spec(),)),
        EffectDefinitionRegistry((definition,)),
        EffectImplementationRegistry((WATCHED,)),
    )
    return integrator.plan(Chain(), integrator.collect_and_order(drawn())), integrator


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def engine_and_agent_modules():
    for path in sorted(PROJECT_ROOT.glob("engine/**/*.py")):
        if "__pycache__" not in str(path):
            yield path
    for path in sorted((PROJECT_ROOT / "agent").glob("*.py")):
        if "__pycache__" not in str(path):
            yield path


# ======================================================================
# A. production 도달성 — 변환기가 존재하지 않음을 **증명**한다
# ======================================================================


def test_01_no_production_function_turns_a_candidate_into_an_action():
    """
    §11 — **``TriggerCandidate`` 를 받아 ``PlayerAction`` 을 돌려주는
    production 함수는 하나도 없다.**

    이름이 아니라 **함수 서명**을 AST 로 읽는다. 후보/적격성을 인자로 받는
    함수를 전부 모으고, 그중 ``PlayerAction`` 을 돌려주는 것이 있는지 본다.
    """
    consumers: list[tuple[str, int, str, str]] = []
    for path in engine_and_agent_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            annotations = [
                ast.unparse(arg.annotation)
                for arg in node.args.args + node.args.kwonlyargs
                if arg.annotation is not None
            ]
            if not any(
                "TriggerCandidate" in a or "TriggerEligibility" in a
                for a in annotations
            ):
                continue
            returns = ast.unparse(node.returns) if node.returns else ""
            consumers.append(
                (str(path.relative_to(PROJECT_ROOT)), node.lineno, node.name, returns)
            )

    assert consumers, "후보를 받는 함수가 하나도 없으면 측정이 잘못된 것이다"
    #: 후보를 소비하는 자리는 **전부 트리거 계층 안**이다.
    for module, _, name, _ in consumers:
        assert module in TRIGGER_MODULES, f"트리거 계층 밖에서 소비한다: {module}:{name}"
    #: 그리고 **어느 것도** PlayerAction 을 돌려주지 않는다.
    for module, line, name, returns in consumers:
        assert "PlayerAction" not in returns, f"{module}:{line} {name} -> {returns}"


def test_02_only_the_duel_builds_player_actions_in_production():
    """
    production 에서 ``PlayerAction`` 을 만드는 모듈은 **``engine/duel.py``
    하나**다. 변환기를 넣는다면 그 단일 출처와 어떻게 공존할지가 질문이 된다.
    """
    builders: dict[str, list[str]] = {}
    for path in engine_and_agent_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if func.startswith("PlayerAction."):
                    builders.setdefault(
                        str(path.relative_to(PROJECT_ROOT)), []
                    ).append(func)

    assert set(builders) == {"engine/duel.py"}, builders
    #: 효과 발동 후보는 ``activate_effect`` 로 만든다.
    assert "PlayerAction.activate_effect" in builders["engine/duel.py"]


def test_03_the_canonical_path_does_not_reach_the_trigger_pipeline():
    """
    §11 — 정론 경로의 모듈들과 ``agent/`` 전부가 트리거 계층 이름을
    **하나도 쓰지 않는다.**

    ``TimingPoint`` 는 집합에서 뺐다 — ``activation_timing`` 이 열거형으로만
    쓰고 파이프라인을 부르지 않는다 (3-E-27 · 3-E-28 에서 측정).
    """
    watched = (
        "engine/duel.py",
        "engine/activation.py",
        "engine/action_validation.py",
        "engine/action_execution.py",
        "engine/response.py",
        "engine/target_bridge.py",
        "engine/spell_activation.py",
        "agent/search.py",
        "agent/simulation.py",
        "agent/evaluation.py",
        "agent/policy.py",
        "agent/runner.py",
    )
    for module in watched:
        tree = ast.parse(source_of(module))
        used = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in TRIGGER_NAMES
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in TRIGGER_NAMES
        }
        assert used == set(), f"{module} 가 트리거 계층을 쓴다: {sorted(used)}"


# ======================================================================
# B. 정보 대응 — 무엇이 있고 무엇이 없는가
# ======================================================================


def test_04_the_candidate_already_carries_the_three_identity_fields(board):
    """
    ``PlayerAction.activate_effect`` 가 요구하는 것 중 ``actor`` · ``source`` ·
    ``effect_ref`` **셋은 후보가 이미 들고 있다.**

    `actor` ← `controller` 는 Phase 3-E-28 이 "같은 값" 임을 증명했다. 여기서는
    **그 셋만으로 Action 을 만들 수 있다**는 것을 보인다 (변환기를 만드는 것이
    아니라, 테스트 안에서 한 번 만들어 대응을 확인한다).
    """
    state, _ = board
    view = GameStateView.from_state(state, viewer=MINE)
    candidate = TriggerCollector(view, TriggerRegistry((spec(),))).collect(
        drawn()
    ).candidates[0]

    action = PlayerAction.activate_effect(
        actor=candidate.controller,
        source=candidate.source,
        effect_ref=candidate.effect_ref,
    )

    assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert action.actor == candidate.controller
    assert action.source == candidate.source
    assert action.effect_ref == candidate.effect_ref
    #: 빠진 것은 ``targets`` 하나다 — 그리고 그것은 후보에 없다.
    assert action.targets == ()
    assert not hasattr(candidate, "targets")


def test_05_the_fields_the_candidate_lacks_belong_to_other_layers(board):
    """
    후보에 없는 것이 **빠진 것이 아니라 다른 계층의 것**임을 확인한다.

    * ``targets``    → 판에서 센다 (``target_combinations``)
    * ``selections`` → ``ChainLink`` 가 받는다
    * ``payments``   → 비용 지불이 만든다
    * ``phase``      → ``ACTIVATE_EFFECT`` 에 쓰이지 않는다
    """
    import dataclasses

    candidate_fields = {f.name for f in dataclasses.fields(TriggerCandidate)}
    action_fields = {f.name for f in dataclasses.fields(PlayerAction)}
    link_fields = {f.name for f in dataclasses.fields(ChainLink)}

    #: 겹치는 것 — 이름은 다르지만 대응되는 셋 + 공통 이름.
    assert {"source", "effect_ref"} <= candidate_fields & action_fields
    assert "controller" in candidate_fields and "actor" in action_fields
    #: 후보에 **없는** 것들.
    assert {"targets", "phase", "kind"} & candidate_fields == set()
    assert {"selections", "payments"} & candidate_fields == set()
    #: 선택과 영수증은 ``ChainLink`` 의 칸이다 — Action 의 칸이 아니다.
    assert {"selections", "payments"} <= link_fields
    assert {"selections", "payments"} & action_fields == set()
    #: 후보만 가진 것들 — 전부 **적격성 · 순서** 정보다.
    assert {"point", "requirement", "wording", "status"} <= candidate_fields
    assert {"point", "requirement", "wording", "status"} & action_fields == set()


def test_06_production_derives_targets_from_the_board_not_from_a_candidate():
    """
    production 이 ``targets`` 를 어디서 얻는가 — **판에서 센다.**

    ``Duel._activation_actions`` 의 입력은 ``_activation_sources`` (판) 와
    ``activatable_effects`` (등록소) 이고, 대상은 ``target_combinations`` 가
    센다. 사건도 후보도 입력이 아니다. 그래서 "변환기가 없다" 는 것이
    **빈칸이 아니라 다른 설계**다.
    """
    body = source_of("engine/duel.py").split("def _activation_actions")[1].split(
        "\n    def "
    )[0]
    for supplier in (
        "self._activation_sources(seat)",
        "activatable_effects(card.card_id)",
        "target_combinations(",
        "PlayerAction.activate_effect(",
    ):
        assert supplier in body, f"{supplier} 가 사라졌다"
    #: 사건을 입력으로 받지 않는다.
    assert "TimingEvent" not in body
    assert "TriggerCandidate" not in body


# ======================================================================
# C. 두 모듈이 선언한 파이프라인이 다르다 — 감사 소견
# ======================================================================


def test_07_the_two_modules_declare_different_pipelines():
    """
    **감사 소견 (고치지 않았다).**

    ``engine/trigger.py`` 는 "실제 발동은 **Action** · 비용 · ``ChainLink`` 를
    거쳐야 한다" 고 적는다. ``engine/trigger_chain.py`` 는 후보에서
    ``ChainLink`` 로 **바로** 가는 그림을 적고 ``Action`` 을 언급하지 않는다.

    두 선언이 다르다는 사실을 문서가 아니라 **원본에서** 고정한다.
    """
    trigger_doc = " ".join(source_of("engine/trigger.py").split('"""')[1].split())
    chain_doc = " ".join(source_of("engine/trigger_chain.py").split('"""')[1].split())

    #: 1. trigger.py 는 Action 을 거쳐야 한다고 적는다.
    assert "Action → CostPayment → ChainLink" in trigger_doc
    assert "Action · 비용 · ``ChainLink`` 를 거쳐야 한다" in trigger_doc

    #: 2. trigger_chain.py 의 그림에는 Action 이 없다.
    assert "TriggerChainIntegrator.plan(chain, ordering)" in chain_doc
    assert "Action" not in chain_doc

    #: 3. 그런데 후보가 갖고 있지 않은 것은 **선택과 영수증**이라고 적는다 —
    #:    "Action 이 없다" 가 아니다. 즉 두 모듈이 Action 의 자리를 다르게 본다.
    assert "무엇을 대상으로 골랐는가" in chain_doc
    assert "비용으로 무엇을 냈는가" in chain_doc


def test_08_a_free_effect_reaches_a_chain_link_without_any_player_action(board):
    """
    **감사 소견 (고치지 않았다).** 위 차이가 말뿐이 아님을 실행으로 보인다.

    대상도 비용도 없는 효과는 ``TriggerChainIntegrator`` 에서
    ``INSERTABLE`` 이 되고, ``extend()`` 가 실제로 체인에 넣는다 —
    ``PlayerAction`` 도 ``EffectActivator`` 도 거치지 않는다.

    **production 에서는 닿지 않는다** (``test_01``~``test_03``). 지금 동작을
    그대로 고정해 둔다.
    """
    state, _ = board
    view = GameStateView.from_state(state, viewer=MINE)

    plan, integrator = planned(view, free_definition())

    assert plan.insertable, "대상·비용이 없으면 넣을 수 있다고 판정한다"
    for entry in plan.insertable:
        link = entry.link
        assert isinstance(link, ChainLink)
        #: 후보의 세 값이 그대로 링크의 세 칸이 된다.
        assert link.actor == entry.candidate.controller
        assert link.effect_ref == entry.candidate.effect_ref
        assert link.source == entry.candidate.source
        #: 선택과 영수증은 비어 있다 — 필요 없는 효과이므로 **거짓이 아니다.**
        assert link.selections == ()
        assert link.payments == ()

    extended = integrator.extend(Chain(), plan)
    assert len(extended) == len(plan.insertable)
    assert all(isinstance(link, ChainLink) for link in extended)


def test_09_an_effect_needing_a_target_is_refused_not_filled_in(board):
    """
    **빈칸을 채워 넣지 않는다.** 대상이 필요한 효과는 거부된다 —
    ``_missing_execution_inputs`` 가 그 자리를 지킨다.

    ``test_08`` 과 짝이다: "링크가 만들어지는 경우" 와 "만들어지지 않는
    경우" 를 **둘 다** 고정해야 경계가 보인다.
    """
    state, _ = board
    view = GameStateView.from_state(state, viewer=MINE)
    definition = targeting_definition()
    assert definition.requires_target

    plan, _ = planned(view, definition)

    assert plan.insertable == ()
    refused = [
        entry
        for entry in plan.entries + plan.skipped
        if entry.code is ValidationCode.TOO_FEW_SELECTED
    ]
    assert refused, "대상 미정으로 거부된 항목이 있어야 한다"
    for entry in refused:
        assert entry.insertion is ChainInsertion.NOT_INSERTABLE
        assert entry.link is None
        assert any("대상 선택" in note for note in entry.notes)
        assert "가짜로 채워 넣지 않습니다" in entry.reason


# ======================================================================
# D. ActionKind · 강제/임의 · 사건 문맥
# ======================================================================


def test_10_the_existing_action_kinds_already_cover_the_optional_choice():
    """
    §7 — **새 ``ActionKind`` 불필요.**

    임의 발동은 ``ACTIVATE_EFFECT`` 와 ``PASS`` 로 이미 표현된다. 강제
    진행은 ``PlayerAction`` 이 아니라 흐름 계층의 것이다 —
    ``legal_actions`` 가 드로우에 대해 그렇게 적는다.
    """
    kinds = {kind.name for kind in PlayerActionKind}
    assert {"ACTIVATE_EFFECT", "PASS"} <= kinds
    #: 측정값 11개. 늘어나면 이 Phase 의 결론을 다시 봐야 한다.
    assert len(kinds) == 11
    #: 시스템 전용 종류를 만들지 않았다.
    assert not {k for k in kinds if "SYSTEM" in k or "TRIGGER" in k}

    #: 강제는 행위 목록에 넣지 않고 ``advance`` 가 한다 — 저장소의 선언이다.
    body = source_of("engine/duel.py").split("def legal_actions")[1].split(
        "\n    def "
    )[0]
    normalized = " ".join(body.split())
    assert "선택이 아니라 규칙" in normalized
    assert "행위 목록에 넣지 않고" in normalized


def test_11_mandatory_and_optional_already_live_on_the_candidate(board):
    """
    강제/임의는 ``TriggerRequirement`` 가 들고 있다 — ``PlayerAction`` 에
    그것을 옮길 이유가 없다. Action 은 **플레이어의 의도**이고, 강제인지
    임의인지는 규칙의 성질이다.
    """
    assert {r.name for r in TriggerRequirement} >= {"MANDATORY", "OPTIONAL", "UNKNOWN"}

    state, _ = board
    view = GameStateView.from_state(state, viewer=MINE)
    mandatory = TriggerSpec(
        WATCHED,
        TimingPoint.CARD_DRAWN,
        requirement=TriggerRequirement.MANDATORY,
        activates_from=frozenset({Zone.MZONE}),
    )
    candidate = TriggerCollector(view, TriggerRegistry((mandatory,))).collect(
        drawn()
    ).candidates[0]

    assert candidate.requirement is TriggerRequirement.MANDATORY
    #: 같은 후보로 만든 Action 에는 그 구분이 **없다** — 있어야 할 이유도 없다.
    action = PlayerAction.activate_effect(
        actor=candidate.controller,
        source=candidate.source,
        effect_ref=candidate.effect_ref,
    )
    assert not hasattr(action, "requirement")
    assert not hasattr(action, "mandatory")


def test_12_event_identity_is_needed_for_eligibility_not_for_the_action(board):
    """
    §10 — 사건 문맥은 **적격성과 순서**의 것이고 Action 의 것이 아니다.

    ``TimingPoint`` 는 후보에 있고, 적격성 관문(``_event_relation``)과
    정렬(``TriggerOrderer``)이 그것을 쓴다. ``PlayerAction`` 에는 사건 칸이
    없고, **없는 것이 맞다** — Action 은 과거의 사건이 아니라 지금의 의도다.
    """
    import dataclasses

    action_fields = {f.name for f in dataclasses.fields(PlayerAction)}
    assert "point" not in action_fields
    assert not {f for f in action_fields if "event" in f or "timing" in f}

    #: 적격성 쪽은 사건을 **반드시** 본다.
    gate = source_of("engine/trigger.py").split("def _event_relation")[1].split(
        "\n    def "
    )[0]
    assert "spec.matches(event)" in gate

    #: 정렬 쪽도 사건을 들고 다닌다.
    assert "event: TimingEvent" in source_of("engine/trigger_order.py")

    #: 그리고 같은 사건에서 나온 후보는 그 시점을 싣는다.
    state, _ = board
    view = GameStateView.from_state(state, viewer=MINE)
    candidate = TriggerCollector(view, TriggerRegistry((spec(),))).collect(
        drawn()
    ).candidates[0]
    assert candidate.point is TimingPoint.CARD_DRAWN


# ======================================================================
# E. 숨은 정보 · 정론 경로 불변
# ======================================================================


def test_13_a_candidate_carries_nothing_the_viewer_may_not_see(board):
    """
    §9 — 후보에 숨은 정보가 없다. 그래서 **가상의 변환기도
    ``GameStateView`` 를 넓힐 필요가 없다.**

    후보의 칸을 하나씩 본다: ``source`` · ``controller`` 는 뒷면 카드도 공개
    정보이고, 나머지는 판정 결과다. ``card_id`` · 정의 · 상대의 패는 **칸
    자체가 없다.**
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(TriggerCandidate)}
    for forbidden in ("card_id", "definition", "card", "hand", "deck", "owner"):
        assert forbidden not in fields, f"후보가 {forbidden} 을 들고 있다"

    state, facedown = board
    view = GameStateView.from_state(state, viewer=MINE)
    #: 상대의 뒷면 카드까지 포함하는 넓은 선언으로 모아 본다.
    wide = TriggerSpec(
        WATCHED,
        TimingPoint.CARD_DRAWN,
        activates_from=frozenset({Zone.MZONE, Zone.SZONE, Zone.HAND}),
    )
    collection = TriggerCollector(view, TriggerRegistry((wide,))).collect(drawn())

    #: 보는 쪽이 못 보는 곳은 후보가 아니라 ``unchecked`` 로 남는다 —
    #: **"무엇이 있는가" 가 아니라 "어디를 못 봤는가" 다.**
    assert collection.unchecked
    for note in collection.unchecked:
        assert str(PLAIN) not in note and str(WATCHER) not in note

    #: 상대의 뒷면 카드는 후보에 나타나지 않는다 (관측에 정체가 없다).
    assert facedown not in {candidate.source for candidate in collection}
    for candidate in collection:
        card = view.find(candidate.source)
        assert card is not None, "관측에 없는 카드가 후보가 되면 안 된다"
        spoken = candidate.reason + " " + " ".join(candidate.notes)
        assert str(PLAIN) not in spoken


def test_14_the_canonical_legal_action_path_is_unchanged(board):
    """
    §15 — 정론 경로가 그대로임을 **동작으로** 확인한다.

    이 Phase 는 production 을 고치지 않았으므로 ``legal_actions`` 의 결과가
    달라질 이유가 없다. 같은 판에서 두 번 물어 같은 답이 나오고, 후보가
    전부 ``PlayerAction`` 이며, ``UNKNOWN`` 이 허가로 새지 않는다.
    """
    from engine.duel import Duel
    from engine.priority import PriorityState

    state, _ = board
    duel = Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=state.turn.turn_player, phase=state.turn.phase
        ),
    )
    first = duel.legal_actions(MINE)
    second = duel.legal_actions(MINE)

    assert [a.canonical_state() for a in first.allowed] == [
        a.canonical_state() for a in second.allowed
    ]
    assert all(isinstance(a, PlayerAction) for a in first.allowed)

    #: 보류된 것은 **``PlayerAction`` 을 들고 있지 않다** — ``kind`` 와 이유만
    #: 싣는다. 그래서 ``UNKNOWN`` 이 구조적으로 후보가 될 수 없다.
    import dataclasses
    from engine.duel import WithheldAction

    held_fields = {f.name for f in dataclasses.fields(WithheldAction)}
    assert held_fields == {"kind", "reason", "missing"}
    assert "action" not in held_fields
    for held in first.withheld:
        assert isinstance(held.kind, PlayerActionKind)
        assert not isinstance(held, PlayerAction)


def test_15_no_second_execution_path_was_created():
    """
    이 Phase 가 **아무 production 파일도 바꾸지 않았음**을 구조로 확인한다.

    ``ChainLink`` 를 만드는 production 자리가 셋 그대로다 — 발동기 둘
    (``activation.py``) · 체인 자신 (``chain.py``) · 잠든 트리거 통합
    (``trigger_chain.py``). 네 번째가 생기면 그것이 두 번째 실행 경로다.
    """
    sites: dict[str, int] = {}
    for path in engine_and_agent_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "ChainLink"
        )
        if count:
            sites[str(path.relative_to(PROJECT_ROOT))] = count

    assert sites == {
        "engine/activation.py": 2,
        "engine/chain.py": 1,
        "engine/trigger_chain.py": 1,
    }, sites
