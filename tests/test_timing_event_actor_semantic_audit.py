"""
Phase 3-F-9 — ``TimingEvent.actor`` 의 **의미 계약** 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
``TimingEvent.actor`` 라는 **하나의 필드**가 사건 종류별로 같은 의미를
갖는가.

측정 결과: **갖지 않는다.**

=====================  ==============================  =================
``MonsterSummoned``     ``delta.player``                **행위자** ○
``CardDrawn``           ``delta.player``                **행위자** ○
``LifeChanged``         ``delta.player``                **당한 쪽** ✗
``ZoneMoved``           ``delta.to_player``             **도착지 주인** ✗
``PhaseChanged``        (적지 않는다)                    ``None``
나머지 7개 delta         (옮길 이름이 없다)               ``None``
=====================  ==============================  =================

가장 강한 반례 (``test_12`` · ``test_13``)
-----------------------------------------
실제 듀얼에서 **P1 이 P0 을 직접 공격**해 P0 의 LP 가 8000 → 6100 이 됐다.
그 전투가 남긴 사건은 하나이고 ``actor`` 가 **0** 이다 — **맞은 쪽**이다.
공격한 P1 은 **어떤 delta 에도 남지 않는다.**

그러므로 상위 계층이 ``event.actor`` 를 "누가 했는가" 로 읽고
``PlayerRef`` 로 해석하면, **"상대가 나를 공격했다" 가 "내가 했다"(SELF) 로
읽힌다.**

🟡 그런데 행위자는 **버려지지 않았다** (``test_13``)
---------------------------------------------------
``EventReader.read`` 가 ``result.action.actor`` 를 ``EventContext.actor`` 에
싣는다. 같은 사건에서 ``ObservedEvent.actor`` 는 **0**(맞은 쪽),
``ObservedEvent.context.actor`` 는 **1**(공격자)다. **두 actor 가 서로 다른
답을 들고 나란히 있다.**

이 파일은 production 을 **한 줄도** 바꾸지 않는다 (``test_22``).
"""

import ast
import hashlib
import importlib
import inspect
import pathlib
import pkgutil

import pytest

from engine.action import PlayerAction
from engine.battle import BattleDestruction, BattleOutcome
from engine.condition import ConditionContext, PlayerRef
from engine.duel import Duel
from engine.effect.delta import (
    CardDrawn,
    CardMovement,
    LifeChanged,
    MonsterSummoned,
    PhaseChanged,
    StateDelta,
    SummonKind,
    ZoneMoved,
    ZoneShuffled,
)
from engine.effect.journal import CostPaymentEvent, EffectEvent, JournalEvent
from engine.effect.operation import OperationKind
from engine.event_pipeline import EventContext, EventReader, ObservedEvent
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.set_card import CardSet
from engine.spell_activation import (
    SpellPlaced,
    SpellRestored,
    SpellRetired,
    SpellRevealed,
)
from engine.summon import duel_executor
from engine.trigger import TimingEvent, TimingPoint, timing_for
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
LUSTER_DRAGON = 11091375  # 통상 몬스터 · ATK 1900


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def method_body(relative: str, class_name: str, method: str) -> str:
    """docstring 을 떼고 **코드만**. 설명이 코드처럼 걸리지 않게 한다."""
    text = source_of(relative)
    for node in ast.walk(ast.parse(text)):
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


# ======================================================================
# 모든 delta 를 한 자리에서 만든다 — 사건군마다 actor 를 재려면 전수가 필요하다
# ======================================================================

I = InstanceId


def every_concrete_delta() -> "dict[str, StateDelta]":
    """
    **실제로 존재하는** 구상 delta 전부. 열두 개다 (``test_03`` 가 수를 센다).

    ``engine`` 전체를 import 해야 하위 클래스가 다 드러난다 — 일부만
    import 한 상태로 세면 ``BattleDestruction`` 처럼 **빠진다**
    (이 파일을 쓰면서 실제로 한 번 빠뜨렸다).
    """
    return {
        "MonsterSummoned": MonsterSummoned(
            summon=SummonKind.SPECIAL,
            card=I(1),
            player=MINE,
            owner=MINE,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.FACEUP_ATTACK,
        ),
        "CardDrawn": CardDrawn(player=THEIRS, card=I(2)),
        "LifeChanged": LifeChanged(player=MINE, before=8000, after=6000),
        "ZoneMoved": ZoneMoved(
            movement=OperationKind.DESTROY,
            card=I(3),
            source_player=THEIRS,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.GRAVE,
        ),
        "PhaseChanged": PhaseChanged(
            from_turn=1,
            from_player=MINE,
            from_phase=Phase.MAIN1,
            to_turn=1,
            to_player=MINE,
            to_phase=Phase.END,
        ),
        "ZoneShuffled": ZoneShuffled(player=MINE, zone=Zone.DECK, size=10, draw=0),
        "BattleDestruction": BattleDestruction(
            card=I(4), owner=THEIRS, source_zone=Zone.MZONE
        ),
        "CardSet": CardSet(
            card=I(5),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.HAND,
            destination_zone=Zone.MZONE,
            destination_index=0,
            position=Position.FACEDOWN_DEFENSE,
        ),
        "SpellPlaced": SpellPlaced(
            card=I(6),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.HAND,
            destination_zone=Zone.SZONE,
            position=Position.FACEUP_ATTACK,
        ),
        "SpellRevealed": SpellRevealed(
            card=I(7),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.SZONE,
            destination_zone=Zone.SZONE,
            position=Position.FACEUP_ATTACK,
        ),
        "SpellRetired": SpellRetired(
            card=I(8),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.SZONE,
            destination_zone=Zone.GRAVE,
            position=Position.FACEUP_ATTACK,
        ),
        "SpellRestored": SpellRestored(
            card=I(9),
            player=MINE,
            owner=MINE,
            source_player=MINE,
            source_zone=Zone.SZONE,
            destination_zone=Zone.SZONE,
            position=Position.FACEDOWN_DEFENSE,
        ),
    }


def moved(operation: OperationKind, *, owner: int, to_zone: Zone) -> ZoneMoved:
    """그 의미로 ``owner`` 의 카드가 자기 자리로 간 이동."""
    return ZoneMoved(
        movement=operation,
        card=I(30),
        source_player=owner,
        source_zone=Zone.MZONE,
        destination_player=owner,
        destination_zone=to_zone,
    )


def battle_board(repository):
    """P1 에게만 몬스터가 있는 판 — P1 의 **직접 공격**이 가능해진다."""
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=3
    )
    while duel.advance() is not None:
        pass
    state = duel.state.clone()
    monster = list(state.player(THEIRS).hand)[0]
    state.move(monster, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK)
    state.turn.turn_player = THEIRS
    state.turn.set_phase(Phase.BATTLE)
    return state, monster.instance_id


# ======================================================================
# A. §2 — TimingEvent 정의와 actor 생성 경로
# ======================================================================


def test_01_the_actor_field_definition():
    """§2 — 타입 · Optional · 정규 표현 · 직렬화 · 검증."""
    assert list(TimingEvent.__dataclass_fields__) == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    #: Optional 이고 기본값이 `None` 이다.
    assert TimingEvent.__dataclass_fields__["actor"].default is None
    assert "int | None" in str(TimingEvent.__dataclass_fields__["actor"].type)

    #: 0/1 또는 `None` 만 된다.
    assert TimingEvent(TimingPoint.LIFE_CHANGED, actor=MINE).actor == MINE
    assert TimingEvent(TimingPoint.LIFE_CHANGED).actor is None
    with pytest.raises(Exception):
        TimingEvent(TimingPoint.LIFE_CHANGED, actor=2)

    #: 정규 표현과 직렬화에 **들어간다.**
    event = TimingEvent(TimingPoint.LIFE_CHANGED, actor=THEIRS)
    assert THEIRS in event.canonical_state()
    assert event.to_dict()["actor"] == THEIRS
    #: `None` 이면 직렬화에서 **빠진다** (적지 않은 것을 0 으로 적지 않는다).
    assert "actor" not in TimingEvent(TimingPoint.LIFE_CHANGED).to_dict()


def test_02_every_actor_creation_path():
    """
    §2 — ``actor`` 가 **어디서** 들어가는가. 경로는 셋뿐이다.

    1. ``from_delta`` — delta 의 사람 칸에서
    2. ``from_journal_event`` — 기록된 사건의 ``actor`` 에서
    3. ``unimplemented`` — 기본 ``None``
    """
    body = method_body("engine/trigger.py", "TimingEvent", "from_delta")
    #: **두 가지 다른 칸**에서 가져온다 — 이것이 이 Phase 의 발견이다.
    assert "actor=delta.player" in body
    assert "actor=delta.to_player" in body
    #: 페이즈는 **일부러 적지 않는다.**
    assert "TimingPoint.PHASE_CHANGED, delta=delta)" in body

    journal = method_body("engine/trigger.py", "TimingEvent", "from_journal_event")
    assert "actor=event.actor" in journal

    #: 기록된 사건 쪽 `actor` 는 **효과를 발동한 사람**이다 (행위자).
    assert "actor" in EffectEvent.__dataclass_fields__
    assert "actor" in CostPaymentEvent.__dataclass_fields__

    #: `unimplemented` 는 기본이 `None`.
    assert TimingEvent.unimplemented("표현 못 함").actor is None
    assert (
        "actor" in inspect.signature(TimingEvent.unimplemented).parameters
    )


def test_03_the_real_delta_vocabulary_is_twelve_classes_not_thirteen_names():
    """
    §3 — **사건 종류를 세기 전에 실제로 있는 클래스를 센다.**

    흔히 드는 이름 가운데 **여섯은 클래스가 아니다** —
    ``CardDestroyed`` · ``CardAddedToHand`` · ``CardDiscarded`` ·
    ``CardBanished`` · ``CardReturned`` 는 전부 ``ZoneMoved`` 의 다른
    ``OperationKind`` 이고, ``TurnChanged`` 는 ``PhaseChanged`` 안에 있다.

    그래서 actor 규칙은 **13가지가 아니라 6가지**다 (ZoneMoved 한 규칙이
    파괴·추방·버리기·되돌리기를 다 덮는다).
    """
    import engine

    for module in pkgutil.walk_packages(engine.__path__, "engine."):
        try:
            importlib.import_module(module.name)
        except Exception:  # pragma: no cover - 선택적 의존성
            pass

    concrete: set[str] = set()

    def walk(klass):
        for child in klass.__subclasses__():
            concrete.add(child.__name__)
            walk(child)

    walk(StateDelta)
    #: 추상 둘을 빼면 구상이 열둘이다.
    abstract = {"CardMovement", "_SpellMovement"}
    assert abstract <= concrete
    assert len(concrete - abstract) == 12, sorted(concrete - abstract)
    assert set(every_concrete_delta()) == concrete - abstract

    #: 클래스가 **없는** 이름들.
    for absent in (
        "CardDestroyed",
        "CardAddedToHand",
        "CardDiscarded",
        "CardBanished",
        "CardReturned",
        "TurnChanged",
    ):
        assert absent not in concrete, absent

    #: 턴 변화는 `PhaseChanged` 가 들고 있다.
    assert {"from_turn", "to_turn"} <= set(PhaseChanged.__dataclass_fields__)


# ======================================================================
# B. §3 — 사건군별 actor 의 실제 의미
# ======================================================================


def test_04_monster_summoned_actor_is_the_agent():
    """§5 — 소환한 사람이다. **행위자가 맞다.**"""
    for player in (MINE, THEIRS):
        delta = MonsterSummoned(
            summon=SummonKind.SPECIAL,
            card=I(1),
            player=player,
            owner=player,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.FACEUP_ATTACK,
        )
        event = timing_for(delta)
        assert event.point is TimingPoint.MONSTER_SUMMONED
        assert event.actor == player == delta.player
    #: `owner` 와 `player` 가 다를 수 있고, actor 는 **소환한 쪽**을 고른다.
    borrowed = MonsterSummoned(
        summon=SummonKind.SPECIAL,
        card=I(1),
        player=MINE,
        owner=THEIRS,
        from_zone=Zone.GRAVE,
        to_zone=Zone.MZONE,
        to_index=0,
        position=Position.FACEUP_ATTACK,
    )
    assert timing_for(borrowed).actor == MINE
    assert borrowed.owner == THEIRS
    assert borrowed.changed_side is True


def test_05_card_drawn_actor_is_the_agent():
    """
    §8 — 뽑은 사람이다. **행위자가 맞다.**

    그리고 "덱에서 카드가 이동했다" 와 **같은 사건으로 취급되지 않는다** —
    별개 시점이고, `ZoneMoved` 로 적는 것이 금지되어 있다.
    """
    assert timing_for(CardDrawn(player=MINE, card=I(2))).actor == MINE
    assert timing_for(CardDrawn(player=THEIRS, card=I(2))).actor == THEIRS
    assert timing_for(CardDrawn(player=MINE, card=I(2))).point is TimingPoint.CARD_DRAWN

    #: 드로우를 `ZoneMoved` 로 적는 것은 **거절된다** — 한 사실을 두 모양으로
    #: 적으면 세는 쪽이 두 번 센다.
    with pytest.raises(ValueError):
        ZoneMoved(
            movement=OperationKind.DRAW,
            card=I(2),
            source_player=MINE,
            source_zone=Zone.DECK,
            destination_player=MINE,
            destination_zone=Zone.HAND,
        )


def test_06_life_changed_actor_is_the_victim_not_the_cause():
    """
    🔴 §7 — **당한 쪽**이다. 원인은 어디에도 없다.

    "LP 를 감소시킨 원인" 과 "LP 가 변경된 플레이어" 를 가른다 —
    현재 구조는 **뒤의 것만** 들고 있다.
    """
    hurt = LifeChanged(player=MINE, before=8000, after=6000)
    event = timing_for(hurt)
    assert event.actor == MINE
    assert hurt.before > hurt.after          # 내가 피해를 입었다
    #: 그런데 `actor` 가 **나**다 — 깎은 쪽이 아니다.
    assert event.actor == hurt.player

    #: 원인을 담을 칸이 **없다.**
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}
    assert not {
        name for name in LifeChanged.__dataclass_fields__ if "actor" in name or "cause" in name
    }

    #: 회복도 같은 모양이다 — 방향만 다르고 `actor` 는 늘 당사자다.
    healed = LifeChanged(player=MINE, before=6000, after=7000)
    assert timing_for(healed).actor == MINE
    assert healed.after > healed.before


def test_07_zone_moved_actor_is_the_destination_owner():
    """
    🔴 §6 — **도착지 주인**이다. 이동을 일으킨 사람이 아니다.

    컨트롤이 넘어가는 이동에서 출발지와 도착지가 **다른 사람**이고,
    ``actor`` 는 도착지를 고른다.
    """
    handed_over = ZoneMoved(
        movement=OperationKind.MOVE,
        card=I(9),
        source_player=MINE,
        source_zone=Zone.MZONE,
        destination_player=THEIRS,
        destination_zone=Zone.MZONE,
    )
    event = timing_for(handed_over)
    assert event.actor == THEIRS
    assert handed_over.source_player == MINE
    #: "내가 내 카드를 상대에게 넘겼다" 인데 actor 는 **상대**다.
    assert event.actor != handed_over.source_player
    assert event.actor == handed_over.destination_player

    #: 다섯 가지를 구분해야 하는데 사건이 들고 있는 것은 넷이고,
    #: "이동을 발생시킨 플레이어" 가 **그 넷에 없다.**
    assert set(ZoneMoved.__dataclass_fields__) == {
        "movement",
        "card",
        "source_player",
        "source_zone",
        "destination_player",
        "destination_zone",
    }
    #: 접근자로는 출발·도착을 **읽을 수 있다** — 잃은 것은 행위자뿐이다.
    assert event.from_zone is Zone.MZONE and event.to_zone is Zone.MZONE
    assert event.operation is OperationKind.MOVE


def test_08_destroy_discard_banish_and_return_share_one_actor_rule():
    """
    §3 · §7 — 네 "사건" 이 전부 ``ZoneMoved`` 이므로 **규칙이 하나**다.

    의미(`operation`)는 구분되는데 ``actor`` 는 넷 다 도착지 주인이다.
    """
    cases = {
        OperationKind.DESTROY: Zone.GRAVE,
        OperationKind.SEND_TO_GRAVE: Zone.GRAVE,
        OperationKind.DISCARD: Zone.GRAVE,
        OperationKind.BANISH: Zone.REMOVED,
        OperationKind.RETURN_TO_HAND: Zone.HAND,
        OperationKind.RETURN_TO_DECK: Zone.DECK,
    }
    for operation, to_zone in cases.items():
        for owner in (MINE, THEIRS):
            event = timing_for(moved(operation, owner=owner, to_zone=to_zone))
            assert event.point is TimingPoint.CARD_MOVED
            assert event.actor == owner
            #: 의미는 구분된다.
            assert event.operation is operation
    #: 여섯 의미가 **한 시점**으로 들어온다.
    points = {
        timing_for(moved(op, owner=MINE, to_zone=z)).point for op, z in cases.items()
    }
    assert points == {TimingPoint.CARD_MOVED}


def test_09_battle_destruction_has_no_point_and_no_actor():
    """
    🔴 §7 C — **전투 파괴는 사건 이름조차 없다.**

    ``BattleDestruction`` 은 ``CardMovement`` 인데 ``ZoneMoved`` 가 아니므로
    ``from_delta`` 가 옮기지 못하고 ``UNIMPLEMENTED`` 로 남는다. 그러면
    ``actor`` 는 ``None`` 이다.
    """
    delta = BattleDestruction(card=I(4), owner=THEIRS, source_zone=Zone.MZONE)
    assert isinstance(delta, CardMovement)
    assert not isinstance(delta, ZoneMoved)

    event = timing_for(delta)
    assert event.point is TimingPoint.UNIMPLEMENTED
    assert event.actor is None
    assert event.note  # 무엇을 옮길 수 없었는지 적어 둔다

    #: delta 자신은 **주인**을 안다 — 그런데 사건으로 옮길 때 버려진다.
    assert delta.owner == THEIRS
    #: 그리고 "누가 파괴했는가" 는 delta 에도 없다.
    assert set(BattleDestruction.__dataclass_fields__) == {
        "card",
        "owner",
        "source_zone",
        "destination_zone",
    }


def test_10_set_and_spell_movements_are_nameless_too():
    """§3 · §10 — 세트 · 마법 배치/공개/퇴장/복귀 다섯도 ``UNIMPLEMENTED`` 다."""
    deltas = every_concrete_delta()
    for name in ("CardSet", "SpellPlaced", "SpellRevealed", "SpellRetired", "SpellRestored"):
        delta = deltas[name]
        event = timing_for(delta)
        assert event.point is TimingPoint.UNIMPLEMENTED, name
        assert event.actor is None, name
        #: 그런데 delta 는 `player` · `owner` · `source_player` 를 **갖고 있다.**
        assert {"player", "owner", "source_player"} <= set(
            type(delta).__dataclass_fields__
        ), name
        assert delta.player == MINE


def test_11_only_five_of_twelve_deltas_get_a_name():
    """§3 — 열둘 가운데 **다섯**만 시점 이름을 받는다."""
    named: dict[str, int | None] = {}
    nameless: dict[str, int | None] = {}
    for name, delta in every_concrete_delta().items():
        event = timing_for(delta)
        target = nameless if event.point is TimingPoint.UNIMPLEMENTED else named
        target[name] = event.actor

    assert set(named) == {
        "MonsterSummoned",
        "CardDrawn",
        "LifeChanged",
        "ZoneMoved",
        "PhaseChanged",
    }
    assert len(nameless) == 7
    #: 이름 없는 일곱은 **전부** actor 가 `None` 이다.
    assert set(nameless.values()) == {None}
    #: 이름이 붙은 다섯 중 `PhaseChanged` 만 `None` 이다.
    assert named["PhaseChanged"] is None
    assert all(named[k] is not None for k in named if k != "PhaseChanged")


# ======================================================================
# C. §4 · §13 — 실제 듀얼로 반례를 만든다
# ======================================================================


def test_12_a_real_direct_attack_records_the_victim_not_the_attacker(repository):
    """
    🔴 §13 1 — **가장 강한 반례.** 실제 듀얼에서 측정한다.

    P1 이 P0 을 직접 공격한다. P0 의 LP 가 줄고, 남는 사건의 ``actor`` 는
    **P0** 이다. 공격한 P1 은 어떤 delta 에도 없다.
    """
    state, attacker = battle_board(repository)
    action = PlayerAction.attack_directly(actor=THEIRS, source=attacker)
    before = state.player(MINE).life_points

    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )

    assert execution.status.value == "executed"
    assert state.player(MINE).life_points < before      # 내가 피해를 입었다

    life = [d for d in execution.deltas if isinstance(d, LifeChanged)]
    assert len(life) == 1
    event = timing_for(life[0])

    #: 공격 선언자는 P1 인데
    assert action.actor == THEIRS
    #: 사건의 actor 는 **P0** 이다.
    assert event.actor == MINE
    assert event.actor != action.actor

    #: 공격자가 **어떤 delta 의 사람 칸에도 없다.**
    assert not [
        delta
        for delta in execution.deltas
        if getattr(delta, "player", None) == THEIRS
        or getattr(delta, "owner", None) == THEIRS
        and isinstance(delta, LifeChanged)
    ]

    #: 그래서 `actor` 를 `PlayerRef` 로 읽으면 **SELF** 가 된다 —
    #: "상대가 나를 공격했다" 가 "내가 했다" 로 읽힌다.
    assert event.actor == MINE  # == 후보가 내 것일 때의 controller
    mistaken = "SELF" if event.actor == MINE else "OPPONENT"
    assert mistaken == "SELF"


def test_13_two_actors_disagree_on_the_same_event(repository):
    """
    🟡 **행위자는 버려지지 않았다.** 다른 칸에 있다.

    ``EventReader.read`` 가 ``result.action.actor`` 를
    ``EventContext.actor`` 에 싣는다. 같은 사건에서 두 ``actor`` 가 **다른
    답**을 들고 나란히 있다.
    """
    state, attacker = battle_board(repository)
    action = PlayerAction.attack_directly(actor=THEIRS, source=attacker)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    view = GameStateView.from_state(state, viewer=MINE)

    #: `actor` 를 넘기지 않으면 **행위에서** 가져온다.
    observed = EventReader(view).read(execution)
    life = [o for o in observed if o.point is TimingPoint.LIFE_CHANGED]
    assert len(life) == 1
    event = life[0]

    assert isinstance(event, ObservedEvent)
    assert event.actor == MINE                 # timing.actor — 맞은 쪽
    assert event.context.actor == THEIRS       # EventContext.actor — 공격자
    assert event.actor != event.context.actor

    #: 그 경로가 코드에 적혀 있다.
    reader = method_body("engine/event_pipeline.py", "EventReader", "read")
    assert "action" in reader and "actor" in reader
    #: `ObservedEvent.actor` 는 `timing` 쪽을 돌려준다.
    observed_actor = method_body("engine/event_pipeline.py", "ObservedEvent", "actor")
    assert "self.timing.actor" in observed_actor
    #: `EventContext` 에 자기 `actor` 칸이 있다.
    assert "actor" in EventContext.__dataclass_fields__


def test_14_an_opponent_draw_is_safe_to_read_as_a_relation():
    """§13 2 — 드로우는 **안전하다.** `actor` 가 행위자다."""
    theirs = timing_for(CardDrawn(player=THEIRS, card=I(2)))
    mine = timing_for(CardDrawn(player=MINE, card=I(3)))
    for event, expected in ((mine, "SELF"), (theirs, "OPPONENT")):
        relation = (
            "SELF"
            if event.actor == MINE
            else "OPPONENT"
            if event.actor
            == PlayerRef.OPPONENT.resolve(ConditionContext(player=MINE))
            else "UNKNOWN"
        )
        assert relation == expected


def test_15_an_opponent_destroying_my_card_is_not_distinguishable():
    """
    🔴 §13 3 · §7 A·B — "**누가** 파괴했는가" 를 구분할 수 없다.

    내 효과로 내 카드가 파괴된 경우와 상대 효과로 내 카드가 파괴된 경우가
    **같은 사건**이 된다. 둘 다 `actor` 가 **카드 주인**이다.
    """
    #: 내 카드가 내 묘지로 — 누가 파괴했든 같은 모양이다.
    by_me = moved(OperationKind.DESTROY, owner=MINE, to_zone=Zone.GRAVE)
    by_them = moved(OperationKind.DESTROY, owner=MINE, to_zone=Zone.GRAVE)
    assert by_me.canonical_state() == by_them.canonical_state()
    assert timing_for(by_me).actor == timing_for(by_them).actor == MINE

    #: 즉 "destroyed card controller" 와 "destroyer actor" 가 **같은 칸**을
    #: 쓰고 있고, 앞의 것만 사실이다.
    assert timing_for(by_me).actor == by_me.destination_player
    #: 파괴자를 적을 칸이 어디에도 없다.
    assert not {
        name
        for name in ZoneMoved.__dataclass_fields__
        if "actor" in name or "cause" in name or "by" in name
    }


def test_16_a_card_moving_to_the_opponent_field_reads_as_the_opponent_acting():
    """
    🔴 §13 4 — "상대 필드로 카드가 이동했다" 와 "상대가 이동시켰다" 가
    **구분되지 않는다.**

    내가 내 카드를 상대에게 넘겼는데 `actor` 가 상대다.
    """
    event = timing_for(
        ZoneMoved(
            movement=OperationKind.MOVE,
            card=I(9),
            source_player=MINE,
            source_zone=Zone.MZONE,
            destination_player=THEIRS,
            destination_zone=Zone.MZONE,
        )
    )
    #: 관계로 읽으면 OPPONENT 가 된다 —
    assert event.actor == THEIRS
    #: 그런데 실제로 움직인 쪽은 나다.
    assert event.delta.source_player == MINE
    #: 사건은 출발지를 **들고 있다** — 그러므로 이것은 정보 부재가 아니라
    #: **어느 칸을 actor 로 골랐는가**의 문제다.
    assert event.from_zone is Zone.MZONE
    assert event.delta.destination_player == THEIRS


def test_17_an_absent_actor_is_not_an_opponent():
    """§4 · §13 — ``actor is None`` 을 "상대가 아니다" 로 읽지 않는다."""
    for name in ("PhaseChanged", "ZoneShuffled", "BattleDestruction", "CardSet"):
        event = timing_for(every_concrete_delta()[name])
        assert event.actor is None, name
        #: `!=` 는 양쪽 모두 참이 된다 — "모른다" 이지 "상대" 가 아니다.
        assert event.actor != MINE and event.actor != THEIRS
        #: 안전한 모양은 존재를 먼저 묻는 것이다.
        assert (event.actor is not None and event.actor != MINE) is False


def test_18_self_and_opponent_safety_per_event_family():
    """
    §9 — 사건군마다 ``event.actor`` 를 ``PlayerRef`` 로 읽어도 **안전한가.**

    =====================  ========  ===================================
    ``MonsterSummoned``     안전       행위자다
    ``CardDrawn``           안전       행위자다
    ``LifeChanged``         **위험**   당한 쪽이다 — 뜻이 뒤집힌다
    ``ZoneMoved``           **위험**   도착지 주인이다
    ``PhaseChanged``        해당 없음   ``None``
    이름 없는 일곱            해당 없음   ``None``
    =====================  ========  ===================================
    """
    safe = {"MonsterSummoned", "CardDrawn"}
    unsafe = {"LifeChanged", "ZoneMoved"}
    absent = {
        "PhaseChanged",
        "ZoneShuffled",
        "BattleDestruction",
        "CardSet",
        "SpellPlaced",
        "SpellRevealed",
        "SpellRetired",
        "SpellRestored",
    }
    assert safe | unsafe | absent == set(every_concrete_delta())
    assert len(safe) == 2 and len(unsafe) == 2 and len(absent) == 8

    for name in safe:
        delta = every_concrete_delta()[name]
        assert timing_for(delta).actor == delta.player
    #: 위험한 둘은 `player` 가 **행위자가 아니다.**
    life = every_concrete_delta()["LifeChanged"]
    assert timing_for(life).actor == life.player   # 당사자
    move = every_concrete_delta()["ZoneMoved"]
    assert timing_for(move).actor == move.destination_player  # 도착지
    for name in absent:
        assert timing_for(every_concrete_delta()[name]).actor is None


# ======================================================================
# D. §12 — 실제 consumer
# ======================================================================


def test_19_the_actor_consumers_do_not_branch_on_event_type():
    """
    §12 — ``actor`` 를 읽는 자리들이 **사건 종류를 구분하지 않는다.**

    그래서 뜻이 섞인 값이 그대로 흘러간다. dormant 라는 이유로 빼지 않는다.
    """
    #: `TimingEvent.actor` 를 읽는 production 자리.
    readers = sorted(
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if "event.actor" in path.read_text(encoding="utf-8")
        or "timing.actor" in path.read_text(encoding="utf-8")
    )
    assert "engine/trigger.py" in readers          # from_journal_event
    assert "engine/event_pipeline.py" in readers   # ObservedEvent.actor

    #: 둘 다 **그대로 옮기기만** 한다 — 사건 종류를 보고 뜻을 고르지 않는다.
    observed_actor = method_body("engine/event_pipeline.py", "ObservedEvent", "actor")
    assert observed_actor.strip() == "return self.timing.actor"
    assert "point" not in observed_actor
    assert "isinstance" not in observed_actor

    #: `EventContext` 는 자기 `actor` 를 행위에서 받아 **그대로** 싣는다.
    context_of = method_body("engine/event_pipeline.py", "EventContext", "of")
    assert "actor=actor" in context_of
    assert "point" not in context_of

    #: live 경로(`duel.py`)는 이 값을 **아예 읽지 않는다** — 그래서 지금
    #: 당장 틀린 판정이 production 에 나오지는 않는다.
    duel_source = source_of("engine/duel.py")
    assert "event.actor" not in duel_source
    assert "timing.actor" not in duel_source


def test_20_reading_the_actor_touches_no_hidden_information(repository):
    """§14 — 행위자·당사자 모두 공개 정보이고 관측 경계를 넓히지 않는다."""
    state, attacker = battle_board(repository)
    action = PlayerAction.attack_directly(actor=THEIRS, source=attacker)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )
    view = GameStateView.from_state(state, viewer=MINE)
    observed = EventReader(view).read(execution)

    assert observed
    for event in observed:
        assert event.actor in (None, MINE, THEIRS)
        assert event.context.actor in (None, MINE, THEIRS)

    #: 상대의 패 · 덱은 그대로 가려져 있다.
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_21_the_state_and_the_rng_do_not_move(repository):
    """§15 — 사건을 읽는 일이 판도 난수도 바꾸지 않는다."""
    state, attacker = battle_board(repository)
    action = PlayerAction.attack_directly(actor=THEIRS, source=attacker)
    execution = duel_executor().execute(
        state, action, authorization=ValidationResult.valid()
    )

    before_hash, before_rng = state.state_hash(), repr(state.rng)
    view = GameStateView.from_state(state, viewer=MINE)
    for _ in range(3):
        EventReader(view).read(execution)
        for delta in execution.deltas:
            timing_for(delta)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng


def test_22_this_phase_changed_nothing(repository):
    """§15 · §16 — 구조 불변 · 순위 digest 불변."""
    assert list(TimingEvent.__dataclass_fields__) == [
        "point",
        "delta",
        "effect_ref",
        "actor",
        "note",
    ]
    assert set(LifeChanged.__dataclass_fields__) == {"player", "before", "after"}
    assert len(ZoneMoved.__dataclass_fields__) == 6
    assert len(list(TimingPoint)) == 8

    duel_source = source_of("engine/duel.py")
    for absent in ("TriggerRegistry", "engine.timing", "engine.event_pipeline"):
        assert absent not in duel_source, absent

    from agent.runner import DuelRunner
    from agent.search import search_policy

    deck = [LUSTER_DRAGON] * 12 + [55144522] * 4 + [5915629] * 4
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
