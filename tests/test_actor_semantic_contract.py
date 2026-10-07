"""
Phase 3-F-11 — 두 ``actor`` 의 **semantic contract 를 고정한다.**

Phase 3-F-9 · 3-F-10 이 **측정**했고, 이 파일은 그 결과를 **계약으로
못박는다.** 계약이 적힌 자리는 production docstring 이고, 이 파일은 그
문장들이 거기 있는지와 실제 동작이 그 문장대로인지를 함께 본다.

세 문장
-------
1. **행위의 주체가 필요하면 ``EventContext.actor`` 를 쓴다.**
2. **변화의 귀속 대상(affected)이 필요하면 ``TimingEvent.actor`` 를 쓴다.**
3. **두 actor 를 같은 뜻으로 취급하지 않는다.** 특히 둘을 비교해서 "누가
   행동했는가" 를 **추론하지 않는다.**

이 Phase 가 production 에서 바꾼 것
-----------------------------------
docstring **둘뿐**이다 (``test_11`` 이 구조가 그대로임을 확인한다).

* ``TimingEvent.actor`` — "이 사건을 일으킨 플레이어" 라는 **거짓 문장**을
  고쳤다. 그 값은 행위자가 아니다.
* ``EventContext.actor`` — **선언**이라는 사실과 ``None`` 이 되는 **두
  까닭**을 보탰다.

``ObservedEvent.actor`` 는 **고치지 않았다** — 그 자리는 원래부터 두 질문을
구분해 두고 있었다 (``test_03``, §5 의 A).
"""

import hashlib
import inspect
import pathlib

import pytest

from engine.action import PlayerAction
from engine.condition import ConditionContext, PlayerRef
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    SummonKind,
    ZoneMoved,
    ZoneShuffled,
)
from engine.effect.operation import OperationKind
from engine.effect.resolution import EffectResult
from engine.event_pipeline import EventContext, EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.summon import duel_executor
from engine.trigger import TimingEvent, TimingPoint, timing_for
from engine.turn_progression import ProgressionResult
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
POT_OF_GREED = 55144522
I = InstanceId


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def field_doc(relative: str, class_name: str, attribute: str) -> str:
    """dataclass 필드 선언 **바로 뒤**의 문자열 리터럴."""
    import ast

    text = source_of(relative)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            body = node.body
            for index, statement in enumerate(body):
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id == attribute
                ):
                    following = body[index + 1] if index + 1 < len(body) else None
                    if (
                        isinstance(following, ast.Expr)
                        and isinstance(following.value, ast.Constant)
                        and isinstance(following.value.value, str)
                    ):
                        return following.value.value
                    return ""
    raise AssertionError(f"{class_name}.{attribute} 를 찾지 못했습니다")


# ======================================================================
# 판
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def summon_by(repository, actor: int):
    duel = live_duel(repository)
    state = duel.state.clone()
    source = list(state.player(actor).hand)[0].instance_id
    action = PlayerAction.special_summon(actor=actor, source=source)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid("감사가 직접 허가")
    )
    return state, execution, action


def battle_by(repository, attacker: int):
    duel = live_duel(repository)
    state = duel.state.clone()
    monster = list(state.player(attacker).hand)[0]
    state.move(monster, Zone.MZONE, to_player=attacker, position=Position.FACEUP_ATTACK)
    state.turn.turn_player = attacker
    state.turn.set_phase(Phase.BATTLE)
    action = PlayerAction.attack_directly(actor=attacker, source=monster.instance_id)
    victim_before = state.player(1 - attacker).life_points
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    return state, execution, action, victim_before


def observed_of(state, execution, *, viewer: int = MINE):
    view = GameStateView.from_state(state, viewer=viewer)
    return EventReader(view).read(execution)


# ======================================================================
# A. 계약이 적혀 있는가 (§3 · §4 · §5)
# ======================================================================


def test_01_the_timing_actor_contract_is_written_and_forbids_the_agent_claim():
    """
    §3 — ``TimingEvent.actor`` 의 계약: **변화가 귀속되는 플레이어.**

    금지 표현("사건을 일으킨 플레이어")이 사라졌는지, 그리고 사건군별로
    어디서 오는지가 적혀 있는지 본다.
    """
    doc = field_doc("engine/trigger.py", "TimingEvent", "actor")

    assert "귀속" in doc
    assert "행위의 주체가 아니다" in doc
    #: 금지된 단정이 없다.
    assert "이 사건을 일으킨 플레이어" not in doc
    assert "일으킨" not in doc

    #: 사건군별 출처가 적혀 있다 — 뜻이 하나가 아니라는 것이 보여야 한다.
    for mentioned in (
        "MonsterSummoned",
        "CardDrawn",
        "LifeChanged",
        "ZoneMoved",
        "PhaseChanged",
        "delta.player",
        "delta.to_player",
    ):
        assert mentioned in doc, mentioned
    #: 전투 반례가 **문장으로** 들어 있다.
    assert "P0" in doc and "P1" in doc
    #: 그리고 어느 쪽을 써야 하는지 가리킨다.
    assert "EventContext" in doc


def test_02_the_context_actor_contract_is_written_with_both_none_reasons():
    """
    §4 — ``EventContext.actor`` 의 계약: **행위의 주체**이고 **선언**이다.

    ``None`` 이 되는 까닭이 **둘**이라는 것과, delta 와 맞춰 보지 않는다는
    것이 적혀 있어야 한다.
    """
    doc = field_doc("engine/event_pipeline.py", "EventContext", "actor")

    assert "행위의 주체" in doc
    assert "부르는 쪽이 선언" in doc
    #: `None` 의 두 까닭.
    assert "규칙이 스스로 한 일" in doc
    assert "EffectResult" in doc and "ProgressionResult" in doc
    #: 검증되지 않는다는 사실.
    assert "맞춰 보지 않는다" in doc
    assert "책임" in doc
    #: 그리고 다른 actor 와 **같은 뜻이 아니라고** 못박는다.
    assert "TimingEvent" in doc
    assert "같은 뜻이 아니다" in doc
    #: 혼동할 표현을 쓰지 않는다.
    assert "affected" not in doc


def test_03_the_observed_actor_already_distinguished_the_two_questions():
    """
    §5 — ``ObservedEvent.actor`` 는 **고치지 않았다.** 답은 A 다.

    그 자리의 docstring 이 **원래부터** 두 질문을 구분해 두었다. 3-F-10 이
    그 문장을 읽지 않고 "구분이 어디에도 없다" 고 적었던 것이 이 Phase 에서
    바로잡힌 부분이다.
    """
    doc = inspect.getdoc(inspect.getattr_static(ObservedEvent, "actor").fget)
    assert doc
    #: 두 질문을 **나란히 놓고** 다르다고 말한다.
    assert "누가 이 행위를 했는가" in doc
    assert "이 사건이 누구의 것인가" in doc
    assert "다른 질문이다" in doc
    #: 그리고 문맥으로 **떨어지지 않는다**고 적어 두었다 — 즉 이 값은
    #: 사건 쪽이다.
    assert "떨어지지 않는다" in doc

    #: 실제로도 사건 쪽을 돌려준다.
    event = ObservedEvent(
        EventContext(1, MINE, Phase.MAIN1, actor=THEIRS),
        TimingEvent(TimingPoint.LIFE_CHANGED, actor=MINE),
    )
    assert event.actor == MINE                 # timing 쪽
    assert event.context.actor == THEIRS       # 행위자


# ======================================================================
# B. 네 사례를 계약으로 고정 (§6)
# ======================================================================


@pytest.mark.parametrize(
    "actor_seat",
    [MINE, THEIRS],
    ids=["내가 소환", "상대가 소환"],
)
def test_04_a_summon_pins_both_actors_to_the_summoner(repository, actor_seat):
    """§6 1·2 — 소환에서는 두 actor 가 **같은 사람**이다."""
    state, execution, action = summon_by(repository, actor_seat)
    events = observed_of(state, execution)
    assert len(events) == 1
    event = events[0]

    assert event.point is TimingPoint.MONSTER_SUMMONED
    #: 각자의 계약으로 따로 확인한다 — 둘을 **서로** 비교하지 않는다 (§9).
    assert event.context.actor == action.actor               # 행위의 주체
    assert event.actor == event.delta.player                 # 변화의 귀속
    assert event.delta.player == actor_seat


@pytest.mark.parametrize(
    "attacker",
    [MINE, THEIRS],
    ids=["내가 상대를 공격", "상대가 나를 공격"],
)
def test_05_a_battle_pins_the_two_actors_to_different_players(repository, attacker):
    """
    §6 3·4 — 전투에서는 두 actor 가 **다른 사람**이다.

    ``context.actor`` 는 공격한 쪽, ``timing.actor`` 는 피해를 받은 쪽이다.
    """
    victim = 1 - attacker
    state, execution, action, victim_before = battle_by(repository, attacker)
    life = [e for e in observed_of(state, execution) if e.point is TimingPoint.LIFE_CHANGED]
    assert len(life) == 1
    event = life[0]

    #: 각자의 계약.
    assert event.context.actor == action.actor == attacker   # 행위의 주체
    assert event.actor == victim                             # 변화의 귀속
    assert event.delta.player == victim
    #: 피해가 실제로 그 쪽에 들어갔다.
    assert state.player(victim).life_points < victim_before
    #: 그리고 둘이 다르다 — 그것이 **정상**이다.
    assert event.actor != event.context.actor


def test_06_the_relation_uses_the_context_actor(repository):
    """
    §6 의 핵심 — "상대가 나를 공격했다" 를 판정하는 기준은
    ``EventContext.actor`` 다.

    같은 사건을 두 기준으로 판정해 **답이 갈리는 것**을 고정한다.
    """
    def relation(actor, controller) -> str:
        if actor is None:
            return "UNKNOWN"
        if actor == controller:
            return "SELF"
        if actor == PlayerRef.OPPONENT.resolve(ConditionContext(player=controller)):
            return "OPPONENT"
        raise AssertionError("2인 게임에서는 닿지 않는다")

    state, execution, _, _ = battle_by(repository, THEIRS)
    event = [
        e for e in observed_of(state, execution) if e.point is TimingPoint.LIFE_CHANGED
    ][0]

    #: 내 쪽 효과가 반응한다고 가정하면 (controller = MINE)
    assert relation(event.context.actor, MINE) == "OPPONENT"   # 계약대로 — 맞다
    assert relation(event.actor, MINE) == "SELF"               # 다른 질문의 답
    #: 그러므로 관계 판정은 **context 쪽**을 읽어야 한다.
    assert relation(event.context.actor, MINE) != relation(event.actor, MINE)


def test_07_the_two_actors_must_not_be_compared_to_infer_the_agent():
    """
    §6 마지막 줄 — **두 actor 를 비교해서 "누가 행동했는가" 를 추론하지
    않는다.**

    비교는 "다른 질문의 답이 다르다" 만 알려 준다. 어느 쪽이 행위자인지는
    **계약이 정하는 것**이고 값의 대소나 일치가 정하는 것이 아니다.
    """
    #: 소환처럼 둘이 같은 경우 — 비교해도 행위자를 **가려낼 수 없다.**
    same = ObservedEvent(
        EventContext(1, MINE, Phase.MAIN1, actor=MINE),
        TimingEvent(TimingPoint.MONSTER_SUMMONED, actor=MINE),
    )
    #: 전투처럼 다른 경우.
    different = ObservedEvent(
        EventContext(1, THEIRS, Phase.BATTLE, actor=THEIRS),
        TimingEvent(TimingPoint.LIFE_CHANGED, actor=MINE),
    )
    #: 행위자는 **언제나 context 쪽**이다 — 같든 다르든.
    assert same.context.actor == MINE
    assert different.context.actor == THEIRS
    #: 일치 여부가 행위자를 정하지 않는다.
    assert (same.actor == same.context.actor) is True
    assert (different.actor == different.context.actor) is False
    #: 그런데 두 경우 모두 행위자를 읽는 방법은 **하나**다.
    for event in (same, different):
        assert event.context.actor is not None


# ======================================================================
# C. None 이 되는 길 (§12 9)
# ======================================================================


def test_08_the_timing_actor_is_none_only_where_the_delta_has_no_player():
    """§12 9 — 사건 쪽 ``None``: delta 에 사람 칸이 없거나 옮길 이름이 없다."""
    phase = timing_for(
        PhaseChanged(
            from_turn=1,
            from_player=MINE,
            from_phase=Phase.MAIN1,
            to_turn=1,
            to_player=MINE,
            to_phase=Phase.END,
        )
    )
    assert phase.point is TimingPoint.PHASE_CHANGED and phase.actor is None

    shuffled = timing_for(ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0))
    assert shuffled.point is TimingPoint.UNIMPLEMENTED and shuffled.actor is None

    #: 값이 있는 쪽은 delta 의 사람 칸과 **언제나 같다.**
    for delta, expected in (
        (CardDrawn(player=THEIRS, card=I(2)), THEIRS),
        (LifeChanged(player=MINE, before=8000, after=6000), MINE),
    ):
        assert timing_for(delta).actor == expected


def test_09_the_context_actor_is_none_for_two_different_reasons(repository):
    """
    §12 9 — 문맥 쪽 ``None``: **규칙이 한 일**이거나 **선언되지 않은 것**이다.

    두 까닭을 구분하는 것이 계약의 일부다.
    """
    #: ① 행위를 들고 있지 않은 결과 — 선언이 없으면 `None`.
    assert "action" not in EffectResult.__dataclass_fields__
    assert "action" not in ProgressionResult.__dataclass_fields__

    duel = live_duel(repository)
    view = GameStateView.from_state(duel.state, viewer=MINE)
    bare = EventReader(view).read_deltas(
        (LifeChanged(player=MINE, before=8000, after=6000),)
    )
    assert bare[0].context.actor is None
    assert bare[0].actor == MINE          # 사건 쪽은 값이 있다

    #: ② 부르는 쪽이 말해 주면 채워진다.
    told = EventReader(view).read_deltas(
        (LifeChanged(player=MINE, before=8000, after=6000),), actor=THEIRS
    )
    assert told[0].context.actor == THEIRS
    assert told[0].actor == MINE          # 사건 쪽은 그대로다

    #: `__str__` 가 `None` 을 **"규칙"** 으로 읽는다 — 그 어휘가 계약의 증거다.
    assert "규칙" in str(EventContext(1, MINE, Phase.MAIN1))


def test_10_a_zone_move_keeps_source_and_destination_separate():
    """
    §12 6 — ``ZoneMoved`` 주의점: 사건 쪽 ``actor`` 는 **도착지 주인**이다.

    출발지와 도착지가 **둘 다 읽히므로**, 필요하면 delta 를 직접 보면 된다 —
    사건의 ``actor`` 를 "옮긴 사람" 으로 읽지 않는다.
    """
    delta = ZoneMoved(
        movement=OperationKind.MOVE,
        card=I(9),
        source_player=MINE,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.MZONE,
    )
    event = timing_for(delta)
    assert event.actor == delta.destination_player == THEIRS
    assert delta.source_player == MINE
    #: 둘이 다르다는 사실이 delta 에 남아 있다.
    assert delta.source_player != delta.destination_player
    #: 계약 문서가 이 경우를 가리킨다.
    assert "delta.to_player" in field_doc("engine/trigger.py", "TimingEvent", "actor")


# ======================================================================
# D. 이 Phase 가 바꾸지 않은 것 (§7 · §10 · §11 · §13 · §14)
# ======================================================================


def test_11_only_docstrings_changed():
    """
    §13 — 구조는 **그대로**다. 필드 · 멤버 · 서명을 못박는다.
    """
    assert list(TimingEvent.__dataclass_fields__) == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    assert list(EventContext.__dataclass_fields__) == [
        "turn_number",
        "turn_player",
        "phase",
        "actor",
        "sequence",
    ]
    assert list(ObservedEvent.__dataclass_fields__) == ["context", "timing"]
    assert len(list(TimingPoint)) == 8
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}
    assert len(ZoneMoved.__dataclass_fields__) == 6

    #: §10 — 새 field 를 더하지 않았다.
    for forbidden in ("cause_player", "affected_player", "actor_player", "action_player"):
        for klass in (TimingEvent, EventContext, LifeChanged, ZoneMoved, MonsterSummoned):
            assert forbidden not in klass.__dataclass_fields__, (forbidden, klass)

    #: §11 — 이름을 바꾸지 않았다.
    assert "actor" in TimingEvent.__dataclass_fields__
    assert "actor" in EventContext.__dataclass_fields__
    assert isinstance(inspect.getattr_static(ObservedEvent, "actor"), property)
    assert {ref.value for ref in PlayerRef} == {"controller", "opponent"}

    #: 서명도 그대로다.
    assert [
        name for name in inspect.signature(EventReader.read).parameters if name != "self"
    ] == ["result", "actor"]
    assert [
        name
        for name in inspect.signature(TimingEvent.from_delta).parameters
        if name != "cls"
    ] == ["delta"]


def test_12_no_production_consumer_was_added():
    """
    §7 — consumer 를 더하지 않았다. **아직 아무도 읽지 않는다.**

    그래서 이 계약은 "지금 틀린 것을 고친다" 가 아니라 "앞으로 틀리지 않게
    적어 둔다" 다.
    """
    readers = []
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative in ("engine/event_pipeline.py", "engine/trigger.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("event.actor", "timing.actor", "context.actor"):
            if needle in text:
                readers.append((relative, needle))
    assert readers == [], readers

    #: dormant 파이프라인도 연결하지 않았다.
    duel_source = source_of("engine/duel.py")
    for absent in (
        "TriggerRegistry",
        "TriggerCollector",
        "engine.timing",
        "engine.event_pipeline",
    ):
        assert absent not in duel_source, absent

    #: `_event_relation` 은 여전히 actor 를 읽지 않는다.
    import ast

    text = source_of("engine/trigger.py")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == "_event_relation":
            body = [
                s
                for s in node.body
                if not (
                    isinstance(s, ast.Expr)
                    and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str)
                )
            ]
            code = "\n".join(ast.unparse(s) for s in body)
            assert "actor" not in code
            break
    else:  # pragma: no cover - 함수가 사라지면 알아야 한다
        raise AssertionError("_event_relation 을 찾지 못했습니다")


def test_13_the_board_and_the_rng_are_untouched(repository):
    """§14 — state_hash · RNG 불변."""
    state, execution, _, _ = battle_by(repository, THEIRS)
    before_hash, before_rng = state.state_hash(), repr(state.rng)
    for _ in range(3):
        observed_of(state, execution)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    #: hidden information 경계도 그대로다.
    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_14_the_search_ranking_is_untouched(repository):
    """§14 — AI · Search 불변. docstring 변경이 순위를 움직이지 않는다."""
    from agent.runner import DuelRunner
    from agent.search import search_policy

    deck = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [5915629] * 4
    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == (
        "30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175"
    )
