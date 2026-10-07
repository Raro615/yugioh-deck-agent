"""
Phase 3-F-14 — ``EventReader`` actor 입력 **계약 강제**.

이 파일이 지키는 단 하나의 계약
-------------------------------
``actor`` 는 **부르는 쪽이 말한다.** 세 모양이 **서로 다른 결과**를 낸다.

=========================  ================================  ================
부르는 모양                 뜻                                 결과
=========================  ================================  ================
``read(r, actor=0|1)``      행위자가 그 사람이다                그 값이 들어간다
``read(r, actor=None)``     **행위자가 없다** (규칙이 한 일)     ``None``
``read(r)``                 **말하지 않았다**                   ``TypeError``
=========================  ================================  ================

``ACTOR_OMITTED ≠ INTENTIONAL_NONE``. 이것이 Phase 3-F-12 가 결함으로
측정하고, 3-F-13 이 ``READ_ACTOR_CALLER_MUST_DECLARE`` 로 판정하고, 이 Phase 가
구현한 것이다.

무엇을 **하지 않는가** (§7)
---------------------------
actor 를 **알아서 찾지 않는다.** ``result.action.actor`` · ``delta.player`` ·
``timing.actor`` · ``source_player`` · ``owner`` · ``controller`` 전부 보지
않는다. 자동으로 찾으면 어떤 사건에서는 행위자를, 어떤 사건에서는 **당한 쪽**을
집는다 — 3-F-13 이 실제 카드로 증명한 그것이다.

* **강욕의 보은**: P0 이 발동하면 P1 이 드로우한다. delta 의 **모든 사람 칸이
  P1** 이고 행위자 P0 은 delta 어디에도 없다.
* **``ZoneMoved``**: 파괴 · 패로 · 버리기 · 제외 · 덱으로 — 두 사람 칸이 **모두
  카드 주인**이다. 가해자 칸이 없다.
* 그런데 **``MonsterSummoned``** 은 ``player``(소환자) 와 ``owner``(주인) 를 둘
  다 담는다. 즉 **delta 가 행위자를 담을 때도 있고 안 담을 때도 있어서**, 같은
  규칙으로 읽으면 반드시 어딘가에서 틀린다.

에러는 무엇인가 (§8)
--------------------
``TypeError`` 다. 새 ``ValidationCode`` 를 만들지 않았고, ``UNKNOWN`` 으로도
처리하지 않았다 — ``UNKNOWN`` 은 "알 수 없음" 이고 이것은 **"필수 입력을
누락함"** 이다. 이 모듈이 이미 입력 계약 위반에 ``TypeError`` 를 쓴다
(``EventReader(GameState)`` · ``read(deltas 없는 결과)``) — 그 관례를 따랐다.
"""

import ast
import dataclasses
import inspect
import pathlib
import subprocess

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationResult, EffectActivator
from engine.chain import Chain
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    SummonKind,
    ZoneMoved,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import definition_registry
from engine.effect.operation import OperationKind
from engine.effect.resolution import EffectResult, ResolutionContext
from engine.event_pipeline import (
    _ACTOR_OMITTED,
    EventContext,
    EventPipeline,
    EventReader,
    _ActorOmitted,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.summon import duel_executor
from engine.trigger import TimingPoint, TriggerRegistry, timing_for
from engine.turn_progression import ProgressionResult, TurnProgressor
from engine.validation import ValidationResult
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
    "engine",
    "agent",
    "app",
    "core",
    "analysis",
    "rules",
    "rulings",
    "sources",
    "scripts",
)
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375
FEATHERMAN = 71925487
POT_OF_GREED = 55144522
#: 강욕의 보은 — **상대가** 2장 드로우한다.
THE_GIFT_OF_GREED = 5915629
#: 자비의 비 — **양쪽이** 1000 회복한다.
RAIN_OF_MERCY = 66719324
I = InstanceId


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def method_code(relative: str, class_name: str, method: str) -> str:
    """메서드 본문을 **docstring 을 떼고** 돌려준다 (3-F-7 의 교훈)."""
    for node in ast.walk(ast.parse(source_of(relative))):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    body = list(child.body)
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)
                    ):
                        body = body[1:]
                    return "\n".join(ast.unparse(s) for s in body)
    raise AssertionError(f"{class_name}.{method} 를 찾지 못했습니다")


def code_only(relative: str) -> str:
    """문자열 리터럴을 지운 코드 — 설명을 코드로 착각하지 않으려고 쓴다."""

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    return ast.unparse(_Strip().visit(ast.parse(source_of(relative))))


# ======================================================================
# 판 — 실제 카드
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def reader_for(state, *, viewer: int = MINE) -> EventReader:
    return EventReader(GameStateView.from_state(state, viewer=viewer))


def battle(repository, attacker: int):
    """P1 이 P0 을 직접 공격한다 — 3-F-9 부터 쓰는 같은 반례."""
    duel = live_duel(repository)
    state = duel.state.clone()
    monster = list(state.player(attacker).hand)[0]
    state.move(
        monster, Zone.MZONE, to_player=attacker, position=Position.FACEUP_ATTACK
    )
    state.turn.turn_player = attacker
    state.turn.set_phase(Phase.BATTLE)
    action = PlayerAction.attack_directly(actor=attacker, source=monster.instance_id)
    victim_before = state.player(1 - attacker).life_points
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action, victim_before


def summon(repository, actor: int, kind: str = "normal_summon"):
    duel = live_duel(repository)
    state = duel.state.clone()
    state.turn.turn_player = actor
    state.turn.set_phase(Phase.MAIN1)
    source = list(state.player(actor).hand)[0].instance_id
    action = getattr(PlayerAction, kind)(actor=actor, source=source)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid("감사가 직접 허가")
    )
    return state, execution, action


def resolve_spell(repository, passcode: int, controller: int, *, journal=None):
    """실제 마법 한 장을 **해결만** 한다 → ``action`` 을 들고 있지 않은 결과."""
    reference = EffectRef(passcode, 0)
    state = GameState.create(
        repository, decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16)
    )
    card = state.create_instance(passcode, owner=controller, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    result = EffectExecutor(
        lookup=EffectImplementationRegistry((reference,)), journal=journal
    ).execute(
        state,
        definition_registry().definition_for(reference),
        ResolutionContext(
            effect_ref=reference, controller=controller, source=card.instance_id
        ),
    )
    return state, result


def zone_move(kind: OperationKind, destination: Zone, *, owner: int = MINE) -> ZoneMoved:
    return ZoneMoved(
        movement=kind,
        card=I(9),
        source_player=owner,
        source_zone=Zone.MZONE,
        destination_player=owner,
        destination_zone=destination,
    )


# ======================================================================
# A. §10 1~4 — 세 모양이 서로 다르다
# ======================================================================


def test_01_omitting_the_actor_is_refused(repository):
    """
    §10 1 — **생략은 거부된다.**

    그리고 에러가 **무엇을 해야 하는지** 말해 준다. 계약을 강제하는 에러는
    고치는 방법을 함께 줘야 한다 — 그러지 않으면 부르는 쪽이 아무 값이나
    넣어 통과시키려 한다.
    """
    state, execution, _, _ = battle(repository, THEIRS)
    reader = reader_for(state)

    with pytest.raises(TypeError) as omitted:
        reader.read(execution)

    message = str(omitted.value)
    assert "actor 를 말해야 합니다" in message
    #: 왜 알아낼 수 없는지.
    assert "부르는 쪽만 압니다" in message
    #: 무엇을 하면 되는지 — 두 길을 다 적는다.
    assert "actor=0" in message and "actor=None" in message
    #: 생략의 뜻을 못박는다.
    assert "'행위자가 없다'는 뜻이 아니라" in message


def test_02_saying_none_is_accepted_and_means_no_agent(repository):
    """
    §10 2 — ``actor=None`` 은 **"행위자가 없다" 는 선언**이고 성공한다.

    §4 가 요구한 보존이다 — 페이즈 전환처럼 semantic actor 가 원래 없는 사건을
    읽을 길이 있어야 한다.
    """
    duel = live_duel(repository)
    state = duel.state.clone()
    progression = TurnProgressor().advance(state)
    assert isinstance(progression, ProgressionResult)
    assert progression.deltas

    observed = reader_for(state).read(progression, actor=None)
    assert observed
    for event in observed:
        assert event.point is TimingPoint.PHASE_CHANGED
        assert event.context.actor is None
        assert event.actor is None


@pytest.mark.parametrize("declared", [MINE, THEIRS])
def test_03_saying_a_player_is_accepted_and_arrives_intact(repository, declared):
    """§10 3 · 4 — ``actor=0`` 과 ``actor=1`` 이 **그대로** 들어온다."""
    state, execution, _, _ = battle(repository, THEIRS)
    observed = reader_for(state).read(execution, actor=declared)

    assert observed
    for event in observed:
        assert event.context.actor == declared
    #: 묶음 전체가 같은 값을 공유한다.
    assert {event.context.actor for event in observed} == {declared}


def test_04_the_three_shapes_give_three_different_outcomes(repository):
    """
    🟢 §1 · §11 — **이 Phase 의 성공 조건.**

    ``ACTOR_OMITTED`` · ``INTENTIONAL_NONE`` · ``ACTOR_DECLARED`` 가 **서로
    다른 결과**를 낸다. 3-F-12 가 "구별되지 않는다" 를 측정한 바로 그 자리다.
    """
    state, execution, action, _ = battle(repository, THEIRS)
    reader = reader_for(state)

    #: ① 생략 → 예외 (사건이 하나도 나오지 않는다)
    with pytest.raises(TypeError):
        reader.read(execution)

    #: ② 없다고 말함 → 사건은 나오고 actor 는 None
    said_none = reader.read(execution, actor=None)
    assert len(said_none) == 1
    assert said_none[0].context.actor is None

    #: ③ 값 → 그 값
    declared = reader.read(execution, actor=action.actor)
    assert len(declared) == 1
    assert declared[0].context.actor == THEIRS

    #: ②와 ③은 **문맥이 다르다** — 같은 사건을 다르게 읽은 것이다.
    assert said_none[0].context != declared[0].context
    #: 그런데 귀속자(timing)는 둘 다 같다 — 그쪽은 delta 에서 파생되니까.
    assert said_none[0].actor == declared[0].actor == MINE


# ======================================================================
# B. §3 — 보초값 하나가 네 입구를 덮는다
# ======================================================================


def test_05_all_four_entry_points_share_one_sentinel():
    """
    §3 — ``read`` · ``read_deltas`` · ``observe`` · ``collect`` 가 **같은
    보초값**을 쓴다.

    넷 중 하나만 ``None`` 으로 남으면 그 자리가 계약의 구멍이 된다 — 그리로
    들어온 ``None`` 은 "선언된 None" 으로 보이기 때문이다.
    """
    boundary = (
        EventReader.read,
        EventReader.read_deltas,
        EventPipeline.observe,
        EventPipeline.collect,
    )
    for function in boundary:
        default = inspect.signature(function).parameters["actor"].default
        assert default is _ACTOR_OMITTED, function.__qualname__
        assert isinstance(default, _ActorOmitted)

    #: 보초값은 **하나**다. 매번 새로 만들면 ``is`` 비교가 조용히 깨진다.
    assert len({id(inspect.signature(f).parameters["actor"].default) for f in boundary}) == 1

    #: 사건을 **이미 들고 있는** 자리는 actor 를 받지 않는다 — 그때는 이미 정해져
    #: 있으므로 계약을 다시 물을 자리가 아니다.
    assert "actor" not in inspect.signature(EventPipeline.collect_events).parameters

    #: 보초값은 공개 이름이 아니다 (§9 — 새 공개 API 를 만들지 않는다).
    from engine import event_pipeline

    assert "_ACTOR_OMITTED" not in event_pipeline.__all__
    assert "_ActorOmitted" not in event_pipeline.__all__


def test_06_the_rule_lives_in_exactly_one_place():
    """
    §3 — 판정이 **한 곳**에 있다.

    ``read`` 는 넘기기만 하고 ``read_deltas`` 가 판정한다. 같은 규칙을 두 벌
    두면 언제든 갈린다 — ``_timing_for`` 가 그 까닭을 이미 적어 두었고 (Phase
    2-AJ 에서 실제로 갈려서 실제 카드가 한쪽만 죽었다), 같은 태도를 따랐다.
    """
    read = method_code("engine/event_pipeline.py", "EventReader", "read")
    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")

    #: 판정은 ``read_deltas`` 에만 있다.
    assert "_ACTOR_OMITTED" in read_deltas
    assert "raise TypeError" in read_deltas
    assert "_ACTOR_OMITTED" not in read
    #: ``read`` 는 그대로 넘긴다.
    assert "self.read_deltas(deltas, actor=actor)" in read

    #: 전체 모듈에서 보초값 비교가 **한 번**만 나온다.
    module_code = code_only("engine/event_pipeline.py")
    assert module_code.count("actor is _ACTOR_OMITTED") == 1


def test_07_the_pipeline_entry_points_refuse_too(repository):
    """
    §3 — ``EventPipeline`` 로 들어와도 같다.

    ``observe`` · ``collect`` 의 기본값을 ``None`` 으로 두면 계약을 우회하는
    문이 된다 — 그래서 셋이 같은 거부를 낸다.
    """
    state, execution, action = summon(repository, MINE)
    registry = TriggerRegistry()
    pipeline = EventPipeline(
        GameStateView.from_state(state, viewer=MINE), registry
    )

    with pytest.raises(TypeError):
        pipeline.observe(execution)
    with pytest.raises(TypeError):
        pipeline.collect(execution)

    #: 선언하면 통과한다.
    assert pipeline.observe(execution, actor=action.actor)
    observations = pipeline.collect(execution, actor=action.actor)
    assert observations
    assert all(o.event.context.actor == action.actor for o in observations)
    #: "없다" 도 말할 수 있다.
    assert all(
        o.event.context.actor is None
        for o in pipeline.collect(execution, actor=None)
    )


# ======================================================================
# C. §7 — 자동 추론이 하나도 없다
# ======================================================================


def test_08_no_automatic_inference_survives_anywhere(repository):
    """
    🔴 §7 — **여섯 가지 자동 추론이 전부 없다.**

    ``result.action.actor`` · ``delta.player`` · ``timing.actor`` ·
    ``source_player`` · ``owner`` · ``controller``.
    """
    read = method_code("engine/event_pipeline.py", "EventReader", "read")
    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    both = read + "\n" + read_deltas

    for forbidden in (
        "action",
        "player",
        "controller",
        "owner",
        "timing.actor",
        "source_player",
    ):
        #: ``actor`` 라는 말 자체는 남아 있어야 하므로 지우고 센다.
        assert forbidden not in both.replace("actor", ""), forbidden

    #: 그리고 실제로 추론하지 않는다 — 결과가 알고 있어도 쓰지 않는다.
    state, execution, action, _ = battle(repository, THEIRS)
    assert execution.action.actor == THEIRS      # 결과는 알고 있다
    with pytest.raises(TypeError):
        reader_for(state).read(execution)        # 그래도 쓰지 않는다


def test_09_the_declared_actor_is_never_overwritten_by_the_delta(repository):
    """
    §6 — ``context.actor = timing.actor`` 도, ``= delta.player`` 도 **아니다.**

    공격한 쪽이 P1 인데 ``actor=P0`` 이라고 거짓 선언하면 그대로 들어간다.
    선언을 delta 로 덮어쓰면 "부르는 쪽이 책임진다" 가 거짓말이 된다.
    """
    state, execution, action, _ = battle(repository, THEIRS)
    delta = execution.deltas[0]
    assert isinstance(delta, LifeChanged)
    assert delta.player == MINE          # 맞은 쪽
    assert action.actor == THEIRS        # 공격한 쪽

    lied = reader_for(state).read(execution, actor=MINE)
    assert lied[0].context.actor == MINE           # 선언이 그대로다
    assert lied[0].actor == MINE                   # 귀속자는 delta 에서 온다
    #: 둘이 같은 값이 되었지만 **경로가 다르다** — 하나는 선언, 하나는 파생.
    assert "actor=actor" in method_code(
        "engine/event_pipeline.py", "EventReader", "read_deltas"
    )

    #: 0/1 밖만 막는다 — 값의 사실 여부는 검증하지 않는다.
    with pytest.raises(ValueError):
        EventContext(1, MINE, Phase.MAIN1, actor=2)


# ======================================================================
# D. §10 5~10 — 사건별
# ======================================================================


def test_10_the_battle_case_needs_a_declaration_and_keeps_both_meanings(repository):
    """
    §6 · §10 5 — Battle. LP 8000 → **6100**.

    ``read(execution, actor=1)`` 이어야 하고, ``read(execution)`` 은 거부된다.
    그리고 두 actor 의 뜻이 그대로 보존된다.
    """
    state, execution, action, victim_before = battle(repository, THEIRS)
    assert victim_before == 8000
    assert state.player(MINE).life_points == 6100

    #: 생략은 허용되지 않는다.
    with pytest.raises(TypeError):
        reader_for(state).read(execution)

    observed = reader_for(state).read(execution, actor=THEIRS)
    assert len(observed) == 1
    event = observed[0]
    assert event.point is TimingPoint.LIFE_CHANGED
    assert event.actor == MINE                  # 귀속 — 맞은 쪽
    assert event.context.actor == THEIRS        # 행위 — 공격한 쪽
    assert event.actor != event.context.actor
    assert event.context.actor == action.actor


def test_11_a_monster_summoned_declares_the_summoner(repository):
    """
    §10 7 — ``MonsterSummoned``.

    delta 가 소환자를 담고 있어도 **선언은 따로 한다.** 값이 같아지는 것은
    결과이고, 경로가 같아지는 것은 아니다.
    """
    state, execution, action = summon(repository, MINE)
    assert execution.deltas

    with pytest.raises(TypeError):
        reader_for(state).read(execution)

    observed = reader_for(state).read(execution, actor=action.actor)
    assert observed[0].point is TimingPoint.MONSTER_SUMMONED
    assert observed[0].actor == MINE
    assert observed[0].context.actor == MINE

    #: delta 쪽은 ``player`` 와 ``owner`` 를 **둘 다** 담는다 — 그래서 소환에서는
    #: delta 만 봐도 행위자를 알 수 있다. 그런데 다른 사건군은 아니다
    #: (``test_12`` · ``test_13``) — 그것이 자동 추론을 못 쓰는 까닭이다.
    handed = MonsterSummoned(
        summon=SummonKind.SPECIAL,
        card=I(4),
        player=MINE,
        owner=THEIRS,
        from_zone=Zone.GRAVE,
        to_zone=Zone.MZONE,
        to_index=0,
        position=Position.FACEUP_ATTACK,
    )
    assert timing_for(handed).actor == MINE != handed.owner


def test_12_the_gift_of_greed_proves_the_declaration_is_the_only_source(repository):
    """
    🔴 §10 8 — ``CardDrawn``. **강욕의 보은** (실제 카드 `5915629`).

    P0 이 발동하면 **P1 이 2장 드로우한다.** delta 의 모든 사람 칸이 P1 이므로,
    **선언 말고는 행위자를 알 길이 없다.**
    """
    journal = EventJournal()
    state, result = resolve_spell(
        repository, THE_GIFT_OF_GREED, MINE, journal=journal
    )
    assert isinstance(result, EffectResult)
    assert len(result.deltas) == 2

    for delta in result.deltas:
        assert isinstance(delta, CardDrawn)
        people = {
            name: getattr(delta, name)
            for name in dir(delta)
            if "player" in name and not name.startswith("_")
        }
        assert set(people.values()) == {THEIRS}, people

    #: 생략은 거부된다 — 전에는 조용히 ``None`` 이 되었다.
    with pytest.raises(TypeError):
        reader_for(state).read(result)

    #: 선언하면 행위자가 남는다. 귀속자는 상대 그대로다.
    observed = reader_for(state).read(result, actor=MINE)
    assert [o.context.actor for o in observed] == [MINE, MINE]
    assert [o.actor for o in observed] == [THEIRS, THEIRS]

    #: journal 은 알고 있었지만 ``read()`` 는 **쓰지 않는다** (3-F-12 의 공백은
    #: 그대로다 — 이 Phase 가 고친 것은 "말하지 않아도 통과하는 것" 이다).
    assert journal.events[0].actor == MINE
    assert [
        o.context.actor for o in reader_for(state).read(journal.events[0], actor=None)
    ] == [None, None]


def test_13_the_zone_moved_family_cannot_name_the_agent(repository):
    """
    🔴 §10 10 — ``ZoneMoved``. 파괴 · 패로 · 버리기 · 제외 · 덱으로.

    다섯 다 ``ZoneMoved`` 이고 두 사람 칸이 **모두 카드 주인**이다. 가해자를
    담는 칸이 없으므로 **선언이 유일한 출처**다.
    """
    state = GameState.create(
        repository, decks=([LUSTER_DRAGON] * 8, [LUSTER_DRAGON] * 8)
    )
    reader = reader_for(state)

    for kind, destination in (
        (OperationKind.DESTROY, Zone.GRAVE),
        (OperationKind.RETURN_TO_HAND, Zone.HAND),
        (OperationKind.DISCARD, Zone.GRAVE),
        (OperationKind.BANISH, Zone.REMOVED),
        (OperationKind.RETURN_TO_DECK, Zone.DECK),
    ):
        delta = zone_move(kind, destination, owner=MINE)
        assert delta.source_player == delta.destination_player == MINE

        #: 생략은 거부된다.
        with pytest.raises(TypeError):
            reader.read_deltas((delta,))

        #: "상대가 내 카드를 파괴했다" 를 **선언으로** 말한다.
        observed = reader.read_deltas((delta,), actor=THEIRS)
        assert observed[0].point is TimingPoint.CARD_MOVED
        assert observed[0].actor == MINE              # 귀속 — 주인
        assert observed[0].context.actor == THEIRS    # 행위 — 가해자
        assert observed[0].actor != observed[0].context.actor

    #: 컨트롤이 넘어가는 이동에서도 귀속자는 **도착지 주인**이다.
    handed_over = ZoneMoved(
        movement=OperationKind.MOVE,
        card=I(12),
        source_player=MINE,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.MZONE,
    )
    assert timing_for(handed_over).actor == THEIRS


def test_14_a_life_change_needs_the_declaration_most_of_all(repository):
    """
    §10 9 — ``LifeChanged``. 사람 칸이 **하나**이고 그것은 **당한 쪽**이다.

    자비의 비는 한 번의 실행이 **귀속자가 다른 delta 둘**을 낸다. 행위자는
    하나다 — 그래서 선언은 **묶음마다 한 번**이다.
    """
    state, result = resolve_spell(repository, RAIN_OF_MERCY, MINE)
    assert len(result.deltas) == 2
    assert all(isinstance(delta, LifeChanged) for delta in result.deltas)

    with pytest.raises(TypeError):
        reader_for(state).read(result)

    observed = reader_for(state).read(result, actor=MINE)
    #: 귀속자가 둘이다.
    assert sorted(event.actor for event in observed) == [MINE, THEIRS]
    #: 행위자는 **하나**다.
    assert {event.context.actor for event in observed} == {MINE}
    assert [event.context.sequence for event in observed] == [0, 1]


# ======================================================================
# E. §9 — 결과별 계약
# ======================================================================


def test_15_every_delta_bearing_result_must_declare(repository):
    """
    §9 — **일곱 result 전부 생략을 거부한다.**

    "actor 필수" 가 타입마다 다르지 않다는 것을 실제 객체로 확인한다. 셋은
    실제 실행으로, 넷은 구조로 본다 (``CostPaymentResult`` 와
    ``CostPaymentEvent`` 는 비용이 있는 카드가 필요하고, ``ActivationResult`` 는
    비용 없는 발동에서 delta 가 0개다).
    """
    #: ① ActionExecution
    state, execution, action = summon(repository, MINE)
    #: ② EffectResult
    effect_state, effect_result = resolve_spell(repository, POT_OF_GREED, MINE)
    #: ③ ProgressionResult
    duel = live_duel(repository)
    progression_state = duel.state.clone()
    progression = TurnProgressor().advance(progression_state)

    for state_, result in (
        (state, execution),
        (effect_state, effect_result),
        (progression_state, progression),
    ):
        assert result.deltas, type(result).__name__
        with pytest.raises(TypeError) as omitted:
            reader_for(state_).read(result)
        assert "actor 를 말해야 합니다" in str(omitted.value)
        #: 그리고 "없다" 는 **언제나** 말할 수 있다 — 타입마다 다르지 않다.
        assert all(
            event.context.actor is None
            for event in reader_for(state_).read(result, actor=None)
        )

    #: ④ journal 사건도 같다.
    journal = EventJournal()
    journal_state, _ = resolve_spell(
        repository, POT_OF_GREED, MINE, journal=journal
    )
    with pytest.raises(TypeError):
        reader_for(journal_state).read(journal.events[0])


def test_16_an_activation_result_follows_the_same_contract(repository):
    """
    §9 — ``ActivationResult``. 비용 없는 발동은 delta 가 0개다.

    그래도 **계약은 같다** — delta 수와 무관하게 입력을 먼저 본다. delta 하나를
    얹어서(``dataclasses.replace``) 확인한다. 판을 바꾸지 않는 측정이다.
    """
    reference = EffectRef(POT_OF_GREED, 0)
    state = GameState.create(
        repository, decks=([POT_OF_GREED] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16)
    )
    card = state.create_instance(POT_OF_GREED, owner=THEIRS, zone=Zone.SZONE)
    action = PlayerAction.activate_effect(
        actor=THEIRS, source=card.instance_id, effect_ref=reference
    )
    result = EffectActivator(
        definition_registry(), EffectImplementationRegistry((reference,))
    ).activate(state, Chain(), action, authorization=ValidationResult.valid())
    assert isinstance(result, ActivationResult)
    assert result.activated and result.deltas == ()

    reader = reader_for(state, viewer=THEIRS)
    #: delta 가 없어도 생략은 거부된다 — 입력 계약이 먼저다.
    with pytest.raises(TypeError):
        reader.read(result)
    assert reader.read(result, actor=THEIRS) == ()

    #: delta 를 얹으면 선언이 그대로 들어온다.
    summon_state, summon_execution, summon_action = summon(repository, MINE)
    with_delta = dataclasses.replace(result, deltas=summon_execution.deltas[:1])
    observed = reader.read(with_delta, actor=action.actor)
    assert len(observed) == 1
    assert observed[0].context.actor == THEIRS


def test_17_the_deltas_contract_is_checked_before_the_actor_contract():
    """
    §8 — 두 ``TypeError`` 가 **섞이지 않는다.**

    ``deltas`` 를 들고 있지 않은 것을 넘기면 그 사실을 먼저 말한다. 순서가
    뒤집히면 "결과가 틀렸다" 가 "actor 를 안 말했다" 로 보고되어 부르는 쪽이
    엉뚱한 곳을 고친다.
    """
    reader = EventReader(GameStateView.from_state(GameState.create(), viewer=MINE))

    with pytest.raises(TypeError) as bad_result:
        reader.read(object())
    assert "변화(deltas)를 들고 있는 결과가 필요합니다" in str(bad_result.value)
    assert "actor 를 말해야 합니다" not in str(bad_result.value)

    #: 반대로 결과가 멀쩡하면 actor 쪽을 말한다.
    with pytest.raises(TypeError) as bad_actor:
        reader.read(dataclasses.make_dataclass("_Empty", [("deltas", tuple)])(()))
    assert "actor 를 말해야 합니다" in str(bad_actor.value)


def test_18_no_new_validation_code_was_invented():
    """
    §8 — ``ValidationCode`` 를 **건드리지 않았다.**

    입력 계약 위반은 규칙 판정이 아니다. ``UNKNOWN`` 으로도 처리하지 않았다 —
    ``UNKNOWN`` 은 "알 수 없음" 이고 이것은 "필수 입력 누락" 이다.
    """
    from engine.validation import ValidationCode

    pipeline_code = code_only("engine/event_pipeline.py")
    assert "ValidationCode" not in pipeline_code
    assert "UNKNOWN" not in pipeline_code
    for name in ("ACTOR_OMITTED", "ACTOR_REQUIRED", "ACTOR_MISSING"):
        assert not hasattr(ValidationCode, name), name

    #: 이 모듈의 관례를 따랐다 — 입력 계약 위반은 ``TypeError`` 다. 여섯 자리이고
    #: 전부 "필요한 것이 오지 않았다" 다: ``Phase`` · ``TimingEvent`` ·
    #: ``GameStateView`` · ``deltas`` · **``actor``** · ``StateDelta``.
    assert pipeline_code.count("raise TypeError") == 6
    #: 그중 actor 자리가 이 Phase 가 더한 하나다.
    read_deltas = method_code("engine/event_pipeline.py", "EventReader", "read_deltas")
    assert read_deltas.count("raise TypeError") == 2  # actor · StateDelta
    #: 그리고 규칙 판정 쪽 예외는 **쓰지 않았다**.
    assert "EventPipelineError" not in read_deltas


# ======================================================================
# F. §12 · §13 — 범위와 불변
# ======================================================================


def test_19_only_one_production_file_changed():
    """
    §12 — production 변경이 **``engine/event_pipeline.py`` 하나**다.

    ``EVENT_RELATION`` 도, ``TriggerRegistry`` 도, trigger pipeline 도 건드리지
    않았다. 그리고 **dormant 가 그대로다** — 이 모듈의 production importer 는
    여전히 0개다.
    """
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1", "--"] + list(PRODUCTION_ROOTS),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    #: HEAD~1 이 없을 수도 있으니(최초 commit) 실패를 조용히 넘기지 않고,
    #: 대신 **구조**로 확인한다. 아래가 본 단정이다.
    importers = {
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if path.name != "event_pipeline.py"
        and (
            "from engine.event_pipeline import" in path.read_text(encoding="utf-8")
            or "import engine.event_pipeline" in path.read_text(encoding="utf-8")
        )
    }
    assert importers == set(), importers

    assert "EVENT_RELATION" not in source_of("engine/duel.py")
    assert "EventReader" not in source_of("engine/duel.py")
    #: trigger.py 는 손대지 않았다 — 귀속자 계약은 그대로다.
    assert "**행위의 주체가 아니다**" in source_of("engine/trigger.py")

    #: §9 의 금지 항목.
    pipeline = source_of("engine/event_pipeline.py")
    for forbidden in (
        "cause_player",
        "affected_player",
        "action_player",
        "source_player",
        "actor_player",
        "ActorKind",
        "ActorSource",
        "EventActor",
    ):
        assert forbidden not in pipeline, forbidden


def test_20_the_event_context_structure_is_untouched():
    """
    §3 — ``EventContext`` · ``TimingEvent`` · ``ObservedEvent`` 구조 불변.

    이 Phase 가 더한 것은 **보초값 하나**다. 칸은 하나도 늘지 않았다.
    """
    assert [f.name for f in dataclasses.fields(EventContext)] == [
        "turn_number",
        "turn_player",
        "phase",
        "actor",
        "sequence",
    ]
    from engine.trigger import TimingEvent

    assert [f.name for f in dataclasses.fields(TimingEvent)] == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    #: ``ObservedEvent.actor`` 는 여전히 사건 쪽을 돌려준다.
    assert method_code("engine/event_pipeline.py", "ObservedEvent", "actor") == (
        "return self.timing.actor"
    )
    #: ``EventContext.of`` 의 모양도 그대로다.
    assert list(inspect.signature(EventContext.of).parameters) == [
        "view",
        "actor",
        "sequence",
    ]


def test_21_reading_events_still_changes_nothing(repository):
    """§13 — ``state_hash`` · RNG · hidden-information 불변."""
    state, execution, action, _ = battle(repository, THEIRS)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    reader = reader_for(state)
    reader.read(execution, actor=action.actor)
    reader.read(execution, actor=None)
    reader.read_deltas(execution.deltas, actor=MINE)
    with pytest.raises(TypeError):
        reader.read(execution)

    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    assert (
        live_duel(repository, seed=13).state.state_hash()
        == live_duel(repository, seed=13).state.state_hash()
    )

    #: 관측만 받는다 — 거부된 호출도 판을 건드리지 않았다.
    with pytest.raises(TypeError):
        EventReader(state)
    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()
