"""
Phase 6-B — ``Duel`` 과 ``EventJournal`` 의 연결.

    Duel.start(...)                  journal 하나를 만들어 네 자리에 나눠 준다
      ↓
    ActionExecutor      → record_action   (일반 소환 · 세트 · 공격)
    NormalSpellPlacement→ record_action   (발동 선언 배치 · 해결 뒤 묘지)
    CostPayer           → record_payment  (치른 비용)
    EffectExecutor      → record          (적용된 효과)

이 파일이 고정하는 것
---------------------
1. **적용된 변화만** 적힌다. 거절된 행위는 기록을 남기지 않는다.
2. **기록을 켜도 판이 달라지지 않는다** — 같은 입력이면 같은 최종 상태다.
3. **듀얼마다 기록이 따로다.** 탐색 사본은 **아예 적지 않는다.**
4. 같은 변화가 **두 번 적히지 않는다.**
5. 번호(``sequence``)가 identity 이고, 순서가 재현된다.

🔴 **이 파일은 트리거 실행을 주장하지 않는다.** journal 을 이은 것은
관찰이고, 유발 효과 발동 · 체인 응답 자동화 · 우선권 자동 전환은 **여전히
없다**. ``test_j`` 가 그 사실을 고정한다.
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.effect.journal import (
    ActionEvent,
    CostPaymentEvent,
    EffectEvent,
    EventJournal,
    EventKind,
    JournalError,
)
from engine.spell_activation import duel_components
from engine.validation import ValidationCode
from engine.vocabulary import Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
FEATHERMAN = 21844576       # 통상 몬스터 — 일반 소환이 허가된다
POT_OF_GREED = 55144522     # 엔진에 실행 구현이 등재된 마법


def small_duel(repository, *, seed: int = 5, size: int = 12, **kwargs) -> Duel:
    """``test_duel_loop`` 과 같은 모양의 작은 덱."""
    deck = [FEATHERMAN] * (size - 2) + [POT_OF_GREED] * 2
    return Duel.start(
        repository, decks=(list(deck), list(deck)), seed=seed, **kwargs
    )


def _first(duel: Duel, kind: PlayerActionKind):
    """지금 허가된 행위 중 그 종류의 첫 번째. 없으면 ``None``."""
    return next((a for a in duel.legal_actions(duel.to_act) if a.kind is kind), None)


def _walk_to(duel: Duel, kind: PlayerActionKind, *, limit: int = 120):
    """
    그 종류의 행위가 허가될 때까지 **아주 단순하게** 둔다.

    고를 것이 없으면 ``advance()``, 있으면 첫 번째를 고른다 — 정책이 아니다.
    """
    for _ in range(limit):
        if duel.is_over:
            return None
        if duel.advance() is not None:
            continue
        found = _first(duel, kind)
        if found is not None:
            return found
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            return None
        duel.apply(legal.allowed[0])
    return None


def _resolve_chain(duel: Duel, *, limit: int = 4) -> None:
    """양쪽이 패스해 체인을 푼다. 패스가 없으면 멈춘다."""
    for _ in range(limit):
        if duel.is_over:
            return
        passing = _first(duel, PlayerActionKind.PASS)
        if passing is None:
            return
        duel.apply(passing)


# ===========================================================================
# A. 연결과 하위 호환
# ===========================================================================
def test_a_start_creates_one_journal_shared_by_every_writer(repository):
    r"""🔴 §8-1 — ``start()`` 가 journal 하나를 만들고 **네 자리가 공유**한다.

    따로 만들면 journal 이 넷이 되고, 그러면 "무엇이 먼저 일어났는가" 를
    알 수 없다. 공유는 :func:`~engine.spell_activation.duel_components` 가
    보장한다.
    """
    duel = small_duel(repository)

    assert isinstance(duel.journal, EventJournal)
    assert len(duel.journal) == 0, "시작은 비어 있다 — 아직 아무 행위도 없다"

    #: 🔴 **같은 객체**여야 한다. 같은 내용이 아니라 같은 객체다.
    assert duel._executor.journal is duel.journal
    assert duel._placement.journal is duel.journal
    assert duel._activator.payer.journal is duel.journal
    assert duel._resolver.executor.journal is duel.journal


def test_a_a_caller_that_passes_no_journal_still_works(repository):
    r"""🔴 §8-2 — journal 없이 만든 기존 호출이 **그대로** 돈다.

    ``Duel(state=…, priority=…)`` 는 Phase 2-AO 부터 쓰던 모양이고, 그
    호출에 journal 이 없다. 기본값이 ``None`` 이면 **적지 않고**, 적지
    않는 것이 예전 동작이다.
    """
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Phase

    deck = [FEATHERMAN] * 10
    state = GameState.create(
        repository, decks=(list(deck), list(deck)), turn_player=0, seed=1
    )
    state.turn.set_phase(Phase.MAIN1)
    bare = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=0, phase=Phase.MAIN1),
    )

    assert bare.journal is None, "주지 않았으면 없다 — 몰래 만들지 않는다"
    assert bare._executor.journal is None
    assert bare._placement.journal is None

    #: 그래도 행위는 그대로 적용된다
    state.draw(0, 1)
    summon = _first(bare, PlayerActionKind.NORMAL_SUMMON)
    assert summon is not None, "통상 몬스터는 일반 소환이 허가된다"
    step = bare.apply(summon)
    assert step.accepted is True
    assert step.code is ValidationCode.OK


def test_a_the_duel_module_still_imports_no_effect_layer():
    r"""🔴 §3-1 — :mod:`engine.duel` 이 ``engine.effect`` 를 import 하지 않는다.

    ``test_e_the_duel_makes_no_rules_of_its_own`` 이 이미 고정하는 불변식인데,
    journal 을 잇는 가장 쉬운 방법이 **그것을 깨는 것**이었다. 그래서 여기서
    한 번 더 못박는다 — journal 객체를 만드는 일은
    :func:`~engine.spell_activation.duel_components` 가 하고, 듀얼은 값으로만
    들고 있는다.
    """
    tree = ast.parse((ROOT / "engine/duel.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("engine.effect") for name in modules), modules
    #: 그리고 journal 에 직접 적지 않는다 — 적는 것은 네 writer 의 일이다
    source = (ROOT / "engine/duel.py").read_text(encoding="utf-8")
    for writing in ("record_action(", "record_payment(", ".record("):
        assert writing not in source, writing


# ===========================================================================
# B. 실제 카드 시나리오
# ===========================================================================
@pytest.mark.real_card
def test_b_a_non_chain_action_is_recorded_with_its_real_movement(repository):
    r"""🟢 §7 시나리오 1 — 일반 소환이 **적용된 이동과 함께** 적힌다."""
    duel = small_duel(repository)
    summon = _walk_to(duel, PlayerActionKind.NORMAL_SUMMON)
    assert summon is not None

    seat = duel.to_act
    player = duel.state.player(seat)
    before_hand = len(player.hand)
    before_mzone = sum(1 for c in player.zone(Zone.MZONE) if c is not None)

    step = duel.apply(summon)

    assert step.accepted is True
    #: 판이 실제로 달라졌다
    assert len(player.hand) == before_hand - 1
    assert sum(1 for c in player.zone(Zone.MZONE) if c is not None) == before_mzone + 1

    #: 그 변화가 **하나의 사건**으로 적혔다
    assert len(duel.journal) == 1
    event = duel.journal[0]
    assert isinstance(event, ActionEvent)
    assert event.kind is EventKind.ACTION
    assert event.sequence == 0
    assert event.action_kind == "normal_summon"
    assert event.actor == seat
    assert event.source == summon.source
    assert event.changed_state is True
    assert event.deltas, "적용된 변화가 함께 들어 있다"
    #: 🔴 기록된 카드가 **실제로 움직인 카드**다
    assert summon.source in event.instances


@pytest.mark.real_card
def test_b_an_effect_resolution_is_recorded_after_the_state_changed(repository):
    r"""🟢 §7 시나리오 2 — 이미 실행되는 효과(욕망의 항아리)가 적힌다.

    🔴 **새 카드 효과를 만들지 않았다.** ``EFFECT_LIBRARY`` 에 이미 등재된
    카드를 쓴다.

    그리고 **마법 한 장의 전 여정**이 순서대로 적힌다:
    발동 선언 배치(action) → 효과 해결(effect) → 묘지로(action).
    """
    duel = small_duel(repository)
    activate = _walk_to(duel, PlayerActionKind.ACTIVATE_EFFECT)
    assert activate is not None, "욕망의 항아리는 발동이 허가된다"

    seat = duel.to_act
    player = duel.state.player(seat)
    deck_before = len(player.deck)

    duel.apply(activate)
    #: 🔴 발동만으로는 **효과 기록이 없다** — 발동 ≠ 해결
    assert all(e.kind is not EventKind.EFFECT for e in duel.journal), [
        e.describe_ko() for e in duel.journal
    ]
    placed = [e for e in duel.journal if e.kind is EventKind.ACTION]
    assert len(placed) == 1, "발동 선언으로 카드가 필드에 놓인 사실 하나"

    _resolve_chain(duel)

    #: 해결로 덱이 2장 줄었다 (드로우 2)
    assert len(player.deck) == deck_before - 2

    kinds = [e.kind for e in duel.journal]
    assert kinds == [EventKind.ACTION, EventKind.EFFECT, EventKind.ACTION], kinds

    effect = duel.journal[1]
    assert isinstance(effect, EffectEvent)
    assert effect.effect_ref.card_id == POT_OF_GREED
    assert effect.actor == seat
    assert len(effect.deltas) == 2, "드로우 2장이 변화 둘로 적힌다"

    #: 번호가 0,1,2 로 이어진다 — identity 는 sequence 다
    assert [e.sequence for e in duel.journal] == [0, 1, 2]


@pytest.mark.real_card
def test_b_a_refused_action_leaves_no_event(repository):
    r"""🔴 §7 시나리오 3 · §8-6 — 거절된 행위는 **성공 사건을 남기지 않는다.**

    두 가지 거절을 본다: ① 허가가 나지 않은 행위 ② 소환권을 이미 쓴 뒤의
    두 번째 소환. 둘 다 판을 바꾸지 않고 기록도 남기지 않는다.
    """
    duel = small_duel(repository)
    summon = _walk_to(duel, PlayerActionKind.NORMAL_SUMMON)
    assert summon is not None
    duel.apply(summon)
    assert len(duel.journal) == 1

    seat = duel.to_act
    before_hash = duel.state.state_hash()
    before_events = len(duel.journal)

    #: ① 허가되지 않은 종류 — 특수 소환은 언제나 UNKNOWN 이다
    hand = list(duel.state.player(seat).hand)
    assert hand, "패가 비면 이 시나리오를 볼 수 없다"
    illegal = PlayerAction.special_summon(actor=seat, source=hand[0].instance_id)
    step = duel.apply(illegal)
    assert step.accepted is False
    assert step.code is not ValidationCode.OK

    #: ② 소환권을 이미 썼으므로 두 번째 일반 소환도 거절된다
    again = PlayerAction.normal_summon(actor=seat, source=hand[0].instance_id)
    second = duel.apply(again)
    assert second.accepted is False

    #: 🔴 판도 기록도 그대로다
    assert duel.state.state_hash() == before_hash
    assert len(duel.journal) == before_events


# ===========================================================================
# C. 격리 · 중복 · 동일성
# ===========================================================================
@pytest.mark.real_card
def test_c_two_duels_keep_their_records_apart(repository):
    r"""🔴 §7 시나리오 4 · §8-8 — 듀얼마다 기록이 **따로**다."""
    left = small_duel(repository, seed=5)
    right = small_duel(repository, seed=5)

    assert left.journal is not right.journal

    summon = _walk_to(left, PlayerActionKind.NORMAL_SUMMON)
    assert summon is not None
    left.apply(summon)

    assert len(left.journal) == 1
    assert len(right.journal) == 0, "다른 듀얼의 기록이 섞이지 않는다"

    #: 같은 seed · 같은 입력이면 **같은 기록**이 나온다 (재현)
    mirror = _walk_to(right, PlayerActionKind.NORMAL_SUMMON)
    assert mirror is not None
    right.apply(mirror)
    assert left.journal.canonical_state() == right.journal.canonical_state()
    assert left.journal.journal_hash() == right.journal.journal_hash()


@pytest.mark.real_card
def test_c_a_search_fork_records_nothing_in_the_real_journal(repository):
    r"""🔴 §5-C-4 — 탐색 **사본**이 진짜 기록을 더럽히지 않는다.

    ``agent.simulation.DuelSimulator._fork`` 는 판만 복제하고 나머지를
    공유했다. journal 이 붙은 뒤로는 그대로 두면 **사본에서 돌린 전개가
    진짜 듀얼의 기록에 남는다** — 사본은 버려지는데 기록은 남으므로 그
    기록은 실제 판과 모순된다.

    그래서 사본은 **자기 기록**을 받는다.

    🔴 **Phase 6-AB 가 그 "자기 기록" 의 모양을 고쳤다.** 6-B 는 사본에
    ``journal=False`` 로 **기록하지 않는 한 벌**을 주었다. 그런데 6-Z 부터
    유발 후보가 기록된 사건에서 나오므로, 기록이 없는 사본은 **과거를 잃고**
    원본과 다른 후보를 냈다 (실측: 원본 5 · 사본 4). 지금은 부모의 사건을
    씨앗으로 받은 **새 ``EventJournal``** 이다.

    🔴 **이 시험이 재려는 것은 그대로다** — 아래 "진짜 기록은 한 줄도 늘지
    않았다" 가 그것이고, 그 단정은 손대지 않았다. ``fork.journal is None`` 은
    그것의 **대리 지표**였으므로, 대리 지표 대신 **섞이지 않음을 직접** 센다.
    """
    from agent.simulation import Simulator

    duel = small_duel(repository)
    activate = _walk_to(duel, PlayerActionKind.ACTIVATE_EFFECT)
    assert activate is not None
    before = len(duel.journal)

    #: 🔴 **프로덕션 경로를 쓴다.** 처음에는 여기서 사본을 테스트가 직접
    #: ``dataclasses.replace(..., **duel_components(journal=False))`` 로
    #: 만들었는데, 그러면 내 헬퍼를 시험하는 것이고 ``Simulator._fork`` 를
    #: 시험하는 것이 아니다 — 돌연변이 검사에서 ``_fork`` 의 격리를 지워도
    #: 13개가 모두 통과해서 그 사실이 드러났다.
    simulator = Simulator(duel=duel)
    fork = simulator._fork()

    #: 🔴 **다른 객체이고, 부모의 사건을 그대로 받았다** (6-AB).
    assert fork.journal is not None, "사본도 역사를 들고 있다"
    assert fork.journal is not duel.journal, "같은 객체면 사본의 전개가 섞인다"
    assert tuple(fork.journal) == tuple(duel.journal)
    assert fork.state is not duel.state, "판은 복제됐다"
    #: 규칙은 공유하지 않고 **같은 모양**으로 다시 만든다 — 사본이 진짜와
    #: 같은 규칙으로 돌아야 한다
    assert fork._executor.supported == duel._executor.supported

    #: 사본에서 끝까지 돌린다 — 발동하고 해결까지
    fork.apply(activate)
    _resolve_chain(fork)

    #: 🔴 진짜 기록은 한 줄도 늘지 않았다
    assert len(duel.journal) == before
    #: 🔴 **그런데 사본은 적었다** — 격리가 "아무도 적지 않는다" 로 이루어진
    #: 것이 아님을 센다. 이것이 빠지면 ``_fork`` 가 다시 기록을 떼어 내도
    #: 위 단정이 통과한다 (6-AB).
    assert len(fork.journal) > before
    #: 그리고 진짜 판도 그대로다
    assert fork.state.state_hash() != duel.state.state_hash()


@pytest.mark.real_card
def test_c_the_same_change_is_never_recorded_twice(repository):
    r"""🔴 §8-7 — 같은 변화가 **두 번** 적히지 않는다.

    위험한 자리가 둘이었다. ① 실행기와 해결기가 같은 효과를 각각 적는 것
    ② 체인 링크별 해결과 체인 전체 해결이 겹치는 것.

    🔴 **카드 ID 로 중복을 걸러내지 않는다** (그러면 같은 카드를 두 번
    발동한 정당한 기록이 사라진다). 기존 식별자 —
    ``(sequence, canonical_state)`` — 로 본다.
    """
    duel = small_duel(repository)
    activate = _walk_to(duel, PlayerActionKind.ACTIVATE_EFFECT)
    assert activate is not None
    duel.apply(activate)
    _resolve_chain(duel)

    #: 효과 해결은 **한 번만** 적혔다
    effects = duel.journal.of_kind(EventKind.EFFECT)
    assert len(effects) == 1, [e.describe_ko() for e in effects]

    #: 번호가 0..n-1 로 빈틈없이 이어진다 — 빠지거나 겹치면 깨진다
    assert [e.sequence for e in duel.journal] == list(range(len(duel.journal)))

    #: 같은 변화를 두 사건이 나눠 갖지 않는다
    seen: list[tuple] = []
    for event in duel.journal:
        for delta in event.deltas:
            key = delta.canonical_state()
            assert key not in seen, f"같은 변화가 두 번 적혔다: {delta.describe_ko()}"
            seen.append(key)


@pytest.mark.real_card
def test_c_recording_does_not_change_the_final_state(repository):
    r"""🔴 §5-D · §8-9 — 기록을 켜도 **최종 판이 같다.**

    기록이 행동을 바꾸면 기록이 아니다. 같은 seed · 같은 선택 순서로 두 판을
    돌려 ``state_hash()`` 를 비교한다.
    """
    def play(duel: Duel, limit: int = 300) -> str:
        for _ in range(limit):
            if duel.is_over:
                break
            if duel.advance() is not None:
                continue
            legal = duel.legal_actions(duel.to_act)
            if not legal.allowed:
                break
            duel.apply(legal.allowed[0])
        return duel.state.state_hash()

    recorded = small_duel(repository, seed=9)
    assert recorded.journal is not None

    #: 🔴 ``journal=False`` 가 "끄겠다" 다 — ``None`` (안 줬다) 과 다르다
    silent = small_duel(repository, seed=9, journal=False)
    assert silent.journal is None

    assert play(recorded) == play(silent)
    assert recorded.result == silent.result
    #: 🔴 그런데 기록 쪽만 역사를 들고 있다 — 그것이 이 단계가 더한 전부다
    assert len(recorded.journal) > 0


# ===========================================================================
# D. journal 계약 자체
# ===========================================================================
def test_c_an_executed_action_with_no_change_is_not_recorded(repository):
    r"""🔴 §5-B — **상태 변경 없는 실행 결과**를 사건으로 적지 않는다.

    ``ActionExecution`` 은 "실행됐지만 판이 안 바뀐" 경우를 허용한다
    (``changed_state`` 가 그 질문이다). 그때 사건을 적으면 기록에 빈 줄이
    생기고, 읽는 쪽은 "무슨 일이 있었는데 변화가 없었다" 로 읽는다 —
    역사가 아니라 잡음이다.

    🔴 이 테스트가 처음에는 없었다. 돌연변이로 ``executed.deltas`` 가드를
    지웠더니 13개가 모두 통과해서 드러났다.
    """
    from engine.action_execution import ActionExecutor, ActionStatus
    from engine.action_validation import ValidationResult
    from engine.state.game_state import GameState

    class _NoChangeHandler:
        """판을 바꾸지 않는 수행기. **변화를 지어내지 않는다.**"""

        def apply(self, state, action):
            return ()

    journal = EventJournal()
    executor = ActionExecutor(journal=journal)
    executor.register(PlayerActionKind.PASS, _NoChangeHandler())

    deck = [FEATHERMAN] * 8
    state = GameState.create(
        repository, decks=(list(deck), list(deck)), turn_player=0, seed=1
    )
    result = executor.execute(
        state,
        PlayerAction.passing(actor=0),
        authorization=ValidationResult.valid(),
    )

    assert result.status is ActionStatus.EXECUTED
    assert result.changed_state is False
    #: 🔴 실행은 됐는데 적힌 것이 없다
    assert len(journal) == 0, [e.describe_ko() for e in journal]


def test_d_the_action_event_keeps_its_own_vocabulary():
    r"""🔴 §5-B — ``ActionEvent`` 가 **효과도 비용도 아닌** 제3의 원인이다.

    :class:`EffectEvent` 에 밀어 넣으면 ``effect_ref`` 가 거짓이 되고,
    유발 효과가 "효과에 의해" 와 "소환에 의해" 를 가릴 수 없게 된다.
    """
    journal = EventJournal()
    event = journal.record_action("normal_summon", 0)

    assert isinstance(event, ActionEvent)
    assert event.kind is EventKind.ACTION
    assert not hasattr(event, "effect_ref"), "없는 것을 빈 값으로 채우지 않는다"
    assert event.changed_state is False, "변화가 없으면 바꾼 것이 없다"

    #: 세 종류가 끝까지 갈린다
    assert {k.value for k in EventKind} == {"effect", "cost_payment", "action"}

    #: 왕복한다 — 재현의 입력이 되려면 직렬화가 되어야 한다
    data = event.to_dict()
    assert data["kind"] == "action"
    assert data["action_kind"] == "normal_summon"

    #: 번호가 어긋나면 **거부한다** — 조용히 다시 매기지 않는다
    with pytest.raises(JournalError):
        journal.append(ActionEvent(sequence=99, action_kind="x", actor=0))

    #: 빈 종류 이름을 받지 않는다
    with pytest.raises(ValueError):
        ActionEvent(sequence=0, action_kind="", actor=0)


def test_d_a_recorded_action_is_not_a_timing_point_of_its_own():
    r"""🔴 §6 — 행위 기록을 **트리거 시점으로 지어내지 않는다.**

    ``timing_events`` 가 ``ActionEvent`` 를 만나면 ``TriggerError`` 로
    통째로 실패하거나, 없는 시점 이름을 붙이거나, 둘 중 하나였다. 둘 다
    틀렸으므로 **옮길 이름이 없다는 사실**을 적는다.

    🔴 이 테스트는 트리거 실행을 주장하지 않는다 — 기록이 트리거 계층을
    **깨뜨리지 않는다**는 것만 본다.
    """
    from engine.trigger import TimingEvent, TimingPoint

    event = ActionEvent(sequence=0, action_kind="normal_summon", actor=0)
    timing = TimingEvent.from_journal_event(event)

    assert timing.point is TimingPoint.UNIMPLEMENTED
    assert "normal_summon" in (timing.note or "")
    assert timing.actor == 0

    #: 효과 · 비용은 예전처럼 제 시점으로 간다
    from engine.ids import EffectRef

    resolved = TimingEvent.from_journal_event(
        EffectEvent(sequence=0, effect_ref=EffectRef(1, 0), actor=0)
    )
    assert resolved.point is TimingPoint.EFFECT_RESOLVED
    paid = TimingEvent.from_journal_event(CostPaymentEvent(sequence=0, actor=0))
    assert paid.point is TimingPoint.COST_PAID


@pytest.mark.real_card
def test_j_wiring_the_journal_did_not_turn_on_any_trigger(repository):
    r"""🔴 §6 — journal 연결을 **트리거 실행과 혼동하지 않는다.**

    기록이 이어졌어도 유발 효과는 여전히 발동되지 않는다. 이유는 그대로다 —
    등재된 효과 정의가 전부 ``EFFECT_TYPE_ACTIVATE`` 모양이고, ``Duel`` 은
    트리거 계층을 부르지 않는다.

    이 사실을 적어 두는 이유: 다음 단계가 "이미 되는 줄 알고" 시작하는 것을
    막는다.
    """
    duel = small_duel(repository)
    summon = _walk_to(duel, PlayerActionKind.NORMAL_SUMMON)
    assert summon is not None
    duel.apply(summon)

    #: 소환은 적혔다
    assert len(duel.journal) == 1
    #: 🔴 그런데 체인은 비어 있고, 소환으로 발동된 효과가 없다
    assert len(duel.chain.links) == 0
    assert duel.journal.of_kind(EventKind.EFFECT) == ()

    #: 그리고 듀얼은 트리거 계층을 import 조차 하지 않는다
    tree = ast.parse((ROOT / "engine/duel.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for layer in ("engine.trigger", "engine.trigger_order",
                  "engine.trigger_chain", "engine.timing",
                  "engine.event_pipeline"):
        assert layer not in modules, layer
