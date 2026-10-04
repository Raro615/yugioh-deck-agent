"""
Phase 3-E-20 — 트리거 계층이 듀얼 루프에 **연결되어 있는가** (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

한 문장
-------
트리거 계층은 **완성된 상태로 잠들어 있다** — 사건 정보도, 후보 수집기도,
적격성 판정도, 체인 삽입 계획도 다 있는데 **아무도 부르지 않는다.** 그리고
불러야 할 이유도 아직 없다: 등록된 선언이 0개이고, 실행 목록에 실린 효과
16개는 전부 ``EVENT_FREE_CHAIN``(유발이 아니라 "언제든") 이다.

연결이 끊긴 자리는 정확히 **두 곳**이다
---------------------------------------
::

    GameState 변경
      ├ TurnProgressor.advance() → PhaseChanged  ← 만들어진다
      │                               ✗ ①  Duel._apply_end_phase 가 버린다
      ├ EffectExecutor → EffectResult.deltas     ← 만들어진다
      │                               ✗ ②  journal=None · DuelStep 에 칸이 없다
      ↓
    TimingEvent / TriggerCollector / TriggerChainIntegrator / TimingCoordinator
      ← **production 에서 부르는 곳이 없다** (테스트만 부른다)

① 은 "사건을 만들지 않는다" 가 아니다. ``PhaseChanged`` 는 실제로 만들어지고
``from_phase``/``to_phase`` 를 다 갖고 있다. 받는 쪽이 없어서 버려진다.

② 도 같다. ``EffectResult.deltas`` 는 채워지지만 ``EventJournal`` 이 붙어
있지 않고 (``build_executor()`` 의 ``journal`` 기본값이 ``None``),
``DuelStep`` 에도 변화를 내보내는 칸이 없다.

그래서 이것은 **"부분적으로 연결된 모순" 이 아니라 아직 연결되지 않은 경계**다.
구분이 중요하다 — 모순이면 지금 고쳐야 하고, 경계면 소비자가 생길 때 잇는다.
"""

import ast
import collections
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.chain import ChainLink
from engine.duel import Duel, DuelStep
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY, build_executor
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.spell_activation import duel_resolver
from engine.trigger import (
    TimingPoint,
    TriggerCollection,
    TriggerCollector,
    TriggerRegistry,
    TriggerSpec,
)
from engine.turn_progression import ProgressionStatus, TurnProgressor
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 트리거 계층을 이루는 모듈들.
TRIGGER_MODULES = (
    "engine.trigger",
    "engine.trigger_chain",
    "engine.trigger_order",
    "engine.timing",
    "engine.event_pipeline",
)

#: 듀얼 한 판이 실제로 쓰는 모듈 (``engine/duel.py`` 의 import 목록).
PRODUCTION_ROOTS = ("engine", "agent", "app")

FEATHERMAN = 21844576
POT_OF_GREED = 55144522


def production_modules() -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for root in PRODUCTION_ROOTS:
        for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
            name = path.relative_to(PROJECT_ROOT).as_posix()[:-3].replace("/", ".")
            if name.endswith(".__init__"):
                name = name[: -len(".__init__")]
            out[name] = path
    return out


def import_graph() -> dict[str, set[str]]:
    """``{모듈: 그것을 import 하는 production 모듈들}``. **AST 로 본다.**"""
    importers: dict[str, set[str]] = collections.defaultdict(set)
    for name, path in production_modules().items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                importers[node.module].add(name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    importers[alias.name].add(name)
    return importers


def small_duel(repository, *, seed: int = 5) -> Duel:
    """**발동할 수 있는 카드가 반드시 손에 오도록** 절반을 통상 마법으로 채운다."""
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


def activation_actions(duel: Duel, seat: int) -> list[PlayerAction]:
    """고를 수 있는 **발동** 행위들. 종류는 ``ACTIVATE_EFFECT`` 다."""
    return [
        action
        for action in duel.legal_actions(seat)
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


# ======================================================================
# §2 · §4 — 누가 부르는가 (import 그래프)
# ======================================================================


def test_01_the_integration_layer_has_no_production_importer():
    """
    **§4 — ``engine.timing`` 과 ``engine.event_pipeline`` 은 아무도 import 하지
    않는다.** 둘이 트리거 계층의 입구인데, 입구로 들어오는 사람이 없다.
    """
    importers = import_graph()
    assert importers.get("engine.timing", set()) == set()
    assert importers.get("engine.event_pipeline", set()) == set()

    #: 그 아래 두 모듈은 ``engine.timing`` 을 통해서만 닿는다.
    assert importers.get("engine.trigger_chain", set()) == {"engine.timing"}
    assert importers.get("engine.trigger_order", set()) == {
        "engine.timing",
        "engine.trigger_chain",
    }


def test_02_engine_trigger_reaches_production_only_as_a_type():
    """
    **§2 — ``engine.trigger`` 를 import 하는 production 모듈은 넷이고, 그중
    셋은 잠든 계층이다.** 살아 있는 경로는 ``engine.activation_timing`` 하나인데,
    가져가는 것이 ``TimingPoint`` **하나**이고 그것도 판정에 쓰지 않는다
    (``ActivationTiming.point`` 는 ``canonical_state``/``to_dict`` 에만 나온다).
    """
    importers = import_graph()
    assert importers["engine.trigger"] == {
        "engine.activation_timing",
        "engine.event_pipeline",
        "engine.timing",
        "engine.trigger_chain",
        "engine.trigger_order",
    }

    source = (PROJECT_ROOT / "engine/activation_timing.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "engine.trigger"
        for alias in node.names
    }
    assert names == {"TimingPoint"}


def test_03_the_duel_loop_never_mentions_the_trigger_layer():
    """**§4 — ``engine/duel.py`` 에 ``trigger`` 라는 글자가 없다.**"""
    duel_source = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    assert "trigger" not in duel_source.lower()

    tree = ast.parse(duel_source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not [m for m in imported if m in TRIGGER_MODULES], sorted(imported)


def test_04_no_production_module_constructs_the_trigger_structures():
    """
    **§2 — 생성자를 부르는 곳이 production 에 없다. 테스트에만 있다.**

    "존재한다" 와 "불린다" 를 가른다 (§3).
    """
    targets = (
        "TriggerSpec(",
        "TriggerCollector(",
        "TriggerChainIntegrator(",
        "TimingCoordinator(",
        "TriggerRegistry(",
    )
    definition_files = {
        "engine/trigger.py",
        "engine/trigger_chain.py",
        "engine/timing.py",
    }
    callers = {}
    for name, path in production_modules().items():
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel in definition_files:
            continue
        text = path.read_text(encoding="utf-8")
        for target in targets:
            if target in text:
                callers.setdefault(rel, []).append(target)

    #: **생성자를 부르는 production 모듈은 딱 하나다** — 그리고 그 모듈 자신을
    #: import 하는 곳이 없다. 즉 "부르는 코드가 있다" 와 "불린다" 는 다르다.
    assert sorted(callers) == ["engine/event_pipeline.py"], callers
    assert callers["engine/event_pipeline.py"] == ["TriggerCollector("]
    assert import_graph().get("engine.event_pipeline", set()) == set()

    #: 반대로 테스트에서는 실제로 쓰인다 — 계층이 죽은 코드가 아니라 **잠든**
    #: 코드라는 뜻이다.
    test_users = [
        path.name
        for path in sorted((PROJECT_ROOT / "tests").rglob("test_*.py"))
        if any(t in path.read_text(encoding="utf-8") for t in targets)
    ]
    assert len(test_users) >= 8, test_users


# ======================================================================
# §5 — 페이즈 전이 실측
# ======================================================================


@pytest.mark.real_card
def test_05_every_phase_transition_happens_but_emits_nothing_to_the_caller(repository):
    """
    **§5 — 여섯 전이 전부 일어난다. 그리고 전부 사건을 내보내지 않는다.**

    ``DuelStep`` 에는 변화(``StateDelta``)나 사건(``TimingEvent``)을 내보내는
    칸이 아예 없다 — 버리는 것이 아니라 **내보낼 통로가 없다.**
    """
    duel = small_duel(repository)
    assert duel.state.turn.phase is Phase.DRAW

    seen: list[tuple[Phase, Phase]] = []
    for _ in range(6):
        before = duel.state.turn.phase
        step = duel.apply(
            PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player)
        )
        assert step.accepted, step.reason
        seen.append((before, duel.state.turn.phase))
        duel.advance()

    assert seen == [
        (Phase.DRAW, Phase.STANDBY),
        (Phase.STANDBY, Phase.MAIN1),
        (Phase.MAIN1, Phase.BATTLE),
        (Phase.BATTLE, Phase.MAIN2),
        (Phase.MAIN2, Phase.END),
        (Phase.END, Phase.DRAW),
    ]

    fields = set(DuelStep.__dataclass_fields__)
    assert fields == {"action", "accepted", "code", "reason", "result"}
    assert not [f for f in fields if "delta" in f or "event" in f or "trigger" in f]


@pytest.mark.real_card
def test_06_the_phase_changed_delta_is_created_and_then_dropped(repository):
    """
    **§5 — ``PhaseChanged`` 는 만들어진다. 받는 쪽이 없다.**

    ``TurnProgressor.advance`` 는 ``deltas`` 에 ``PhaseChanged`` 하나를 담아
    돌려주고, 그것은 출발 페이즈와 도착 페이즈를 **둘 다** 갖고 있다 (§6 의
    질문 5 에 대한 답: 정보는 있다). 그런데 ``Duel._apply_end_phase`` 는
    ``status`` 와 ``verdict`` 만 읽는다.
    """
    duel = small_duel(repository)
    result = TurnProgressor().advance(duel.state)
    assert result.status is ProgressionStatus.ADVANCED
    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert type(delta).__name__ == "PhaseChanged"
    assert delta.from_phase is Phase.DRAW
    assert delta.to_phase is Phase.STANDBY

    #: 듀얼 쪽 코드가 그 ``deltas`` 를 읽지 않는다는 것을 **코드로** 확인한다.
    source = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    body = source.split("def _apply_end_phase")[1].split("\n    def ")[0]
    assert "TurnProgressor().advance" in body
    assert "deltas" not in body


# ======================================================================
# §4 — 효과 쪽 사건도 같은 자리에서 끊긴다
# ======================================================================


def test_07_the_production_executor_has_no_journal():
    """
    **§4 — ``EventJournal`` 이 붙어 있지 않으므로 ``JournalEvent`` 가 생기지
    않는다.** 그래서 ``TimingEvent.from_journal_event`` 에는 production 입력이
    아예 없다 (``EFFECT_RESOLVED`` · ``COST_PAID`` 시점이 생길 수 없다).
    """
    assert build_executor().journal is None
    resolver = duel_resolver()
    #: 듀얼이 쓰는 해결기도 같은 실행기를 받는다.
    assert getattr(resolver, "_executor", None) is not None
    assert resolver._executor.journal is None


@pytest.mark.real_card
def test_08_effect_deltas_exist_but_do_not_leave_the_duel(repository):
    """
    **§4 — 효과 해결은 ``deltas`` 를 만든다. 듀얼은 그것을 내보내지 않는다.**

    즉 재료(변화)는 production 에 있고, 그것을 사건으로 바꾸는 호출만 없다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    activations = activation_actions(duel, seat)
    assert activations, duel.legal_actions(seat).kinds

    step = duel.apply(activations[0])
    assert step.accepted, step.reason
    #: 발동은 성립했고 체인이 쌓였는데, 그 과정의 변화는 호출자에게 가지 않는다.
    assert not hasattr(step, "deltas")


# ======================================================================
# §6 · §12 — 등록된 것이 무엇인가
# ======================================================================


def test_09_the_definition_layer_has_no_trigger_concept():
    """
    **§6 — 듀얼이 쓰는 ``EffectDefinition`` 에 유발을 적는 칸이 없다.**

    ``TriggerSpec`` 은 **별도 구조**이고 정의와 이어져 있지 않다. 그래서
    "EVENT_PHASE → TriggerSpec" 연결고리는 코드 수준에서 존재하지 않는다
    (§6 의 질문 1 에 대한 답: NO).
    """
    fields = set(EffectDefinition.__dataclass_fields__)
    assert not [
        f for f in fields if "trigger" in f or "event" in f or "speed" in f
    ], sorted(fields)
    assert "activation" in fields  # 조건은 있다 — 유발 사건이 없다


@pytest.mark.real_card
def test_10_every_registered_effect_is_free_chain_not_a_trigger(repository):
    """
    **§12 — 실행 목록에 유발 효과가 하나도 없다.**

    ``EFFECT_LIBRARY`` 의 항목 전부가 ``EVENT_FREE_CHAIN``(통상 마법 · 함정의
    "발동한다") 이다. 그러므로 지금 **막혀 있는 실행 가능한 유발 사례가 없다**
    (§12 의 분류 E 가 0건, 전부 A).
    """
    codes = []
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        spec = ref.resolve(card) if card is not None else None
        codes.append(spec.code if spec is not None else None)

    assert len(EFFECT_LIBRARY) >= 16
    assert set(codes) == {"EVENT_FREE_CHAIN"}, collections.Counter(codes)


# ======================================================================
# §8 · §9 — 체인과 행위의 소유권
# ======================================================================


@pytest.mark.real_card
def test_11_chain_links_are_created_by_activation_from_a_player_action(repository):
    """
    **§8 — production 에서 ``ChainLink`` 를 만드는 것은
    ``EffectActivator.activate`` 다.** 후보 수집도, ``ResponseLoop`` 도,
    ``apply()`` 자신도 아니다. ``Duel`` 은 ``ChainLink`` 를 만들지 않는다.
    """
    duel_source = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    assert "ChainLink(" not in duel_source

    def constructs_chain_link(path: pathlib.Path) -> bool:
        """**호출**만 센다 — 설명 문장의 ``ChainLink(selections=...)`` 는 아니다."""
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ChainLink"
            ):
                return True
        return False

    builders = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in production_modules().values()
        if constructs_chain_link(path)
    )
    #: 세 곳뿐이고, 그중 ``engine/trigger_chain.py`` 는 잠든 계층이다.
    assert builders == [
        "engine/activation.py",
        "engine/chain.py",
        "engine/trigger_chain.py",
    ], builders

    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    activations = activation_actions(duel, seat)
    assert activations, duel.legal_actions(seat).kinds
    chosen = activations[0]
    duel.apply(chosen)
    #: 쌓인 링크의 주인은 **고른 행위**다 — 후보가 아니다.
    assert len(duel.chain) >= 1
    assert duel.chain.links[0].effect_ref == chosen.effect_ref
    assert isinstance(duel.chain.links[0], ChainLink)


def test_12_there_is_no_trigger_action_kind_and_no_trigger_legal_action():
    """
    **§9 — 트리거는 ``PlayerAction`` 이 되지 않는다. 될 자리도 없다.**

    ``PlayerActionKind`` 에 트리거용 종류가 없고, ``legal_actions`` 가 후보를
    만드는 네 자리(패 · 공격 · 발동 · 흐름) 어디에도 트리거가 없다.
    """
    kinds = {kind.value for kind in PlayerActionKind}
    assert not [k for k in kinds if "trigger" in k], kinds

    source = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    body = source.split("def legal_actions")[1].split("\n    def ")[0]
    for helper in ("_activation_actions", "_attack_actions", "_flow_actions"):
        assert helper in body
    assert "trigger" not in body.lower()


# ======================================================================
# §7 · §10 — 우선권과 관측
# ======================================================================


def test_13_the_trigger_layer_does_not_touch_priority_or_response():
    """
    **§7 — 후보 수집 계층은 우선권/응답을 읽지도 쓰지도 않는다.**

    ``engine/trigger.py`` · ``trigger_order.py`` · ``trigger_chain.py`` 는
    ``engine.priority`` 와 ``engine.response`` 를 import 하지 않는다. 우선권을
    보는 것은 **잠든 조율 계층**(``engine/timing.py``) 뿐이다. 따라서 트리거
    계층은 응답 기회를 **열지 않는다** (§7 의 B: 가능성만 서술한다).
    """
    for module in ("engine/trigger.py", "engine/trigger_order.py", "engine/trigger_chain.py"):
        tree = ast.parse((PROJECT_ROOT / module).read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "engine.priority" not in imported, module
        assert "engine.response" not in imported, module

    timing = ast.parse((PROJECT_ROOT / "engine/timing.py").read_text(encoding="utf-8"))
    timing_imports = {
        node.module
        for node in ast.walk(timing)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "engine.priority" in timing_imports


@pytest.mark.real_card
def test_14_candidate_collection_cannot_see_concealed_cards(repository):
    """
    **§10 — 후보 수집은 관측만 본다. 가려진 자리는 "모른다" 로 남긴다.**

    상대 패의 카드에 선언을 걸어도 후보가 나오지 않고, 대신
    ``TriggerCollection.unchecked`` 가 "거기를 보지 못했다" 를 적는다. 그래서
    트리거 후보가 숨은 정보를 새게 하지 않는다 — ``GameStateView`` 를 바꿀
    이유가 없다.
    """
    duel = small_duel(repository)
    view = duel.view(0)
    with pytest.raises(TypeError):
        TriggerCollector(duel.state, TriggerRegistry())  # GameState 는 거부한다

    registry = TriggerRegistry().register(
        TriggerSpec(effect_ref=EffectRef(POT_OF_GREED, 0), point=TimingPoint.CARD_DRAWN)
    )
    collector = TriggerCollector(view, registry)
    from engine.trigger import TimingEvent

    event = TimingEvent.unimplemented("감사용 사건", actor=0)
    collection = collector.collect(event)
    assert isinstance(collection, TriggerCollection)
    assert collection.candidates == ()

    #: 관측에서 상대 패는 가려져 있고, 그 사실이 기록된다.
    from engine.effect.delta import CardDrawn

    drawn = TimingEvent.from_delta(
        CardDrawn(player=0, card=duel.state.player(0).hand[0].instance_id)
    )
    collected = collector.collect(drawn)
    assert any("HAND" in note for note in collected.unchecked), collected.unchecked


def test_15_the_agent_layer_knows_nothing_about_triggers():
    """**§11 — ``agent/`` 에 트리거가 없다. 평가 · 탐색 · 정책 전부.**"""
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in ("Trigger", "trigger", "TimingEvent", "TimingPoint"):
            assert token not in text, (path.name, token)
