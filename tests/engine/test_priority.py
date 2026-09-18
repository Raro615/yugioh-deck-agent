"""
Phase 2-F-1 — 우선권과 응답 기회.

여기서 답하는 것은 **하나뿐**이다: 지금 누가 다음 선택을 할 차례인가.

그 사람이 **무엇을** 할 수 있는지는 답하지 않는다. 발동 조건 · 스펠 스피드 ·
체인 · 트리거 · 타이밍은 전부 이후 단계다.

세 가지를 본다.

1. 상태가 불변이고 결정론적인가.
2. 전이가 새 상태를 돌려주는가 — 그리고 **아무것도 해결하지 않는가.**
3. 조회가 판을 건드리지 않고, 정보를 새게 하지 않는가.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from engine.condition import PlayerRef
from engine.game_state_view import GameStateView
from engine.priority import (
    PriorityError,
    PriorityHolder,
    PriorityResolver,
    PriorityState,
    ResponseWindow,
)
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

MINE, THEIRS = 0, 1


# ======================================================================
# 판
# ======================================================================


def new_state(turn_player: int = MINE, phase: Phase = Phase.MAIN1) -> GameState:
    game = GameState.create(
        decks=(range(1000, 1030), range(2000, 2030)), turn_player=turn_player
    )
    game.draw(MINE, 5)
    game.draw(THEIRS, 5)
    game.move(game.player(MINE).hand[0], Zone.MZONE, position=Position.FACEUP_ATTACK)
    game.turn.set_phase(phase)
    return game


@pytest.fixture
def state() -> GameState:
    return new_state()


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def opened(
    window: ResponseWindow = ResponseWindow.ACTION,
    holder=MINE,
    turn_player: int = MINE,
    phase: Phase = Phase.MAIN1,
    reason: str = "",
) -> PriorityState:
    return PriorityState.opened(window, holder, turn_player, phase, reason)


# ======================================================================
# 1~2. 불변 · 결정론
# ======================================================================


def test_a_priority_state_is_immutable():
    priority = opened()
    for field, value in [
        ("holder", PriorityHolder.PLAYER_1),
        ("window", ResponseWindow.RESPONSE),
        ("consecutive_passes", 3),
        ("turn_player", 1),
    ]:
        with pytest.raises(Exception):
            setattr(priority, field, value)


def test_states_compare_by_value():
    first = opened(ResponseWindow.RESPONSE, THEIRS, reason="효과 발동")
    same = opened(ResponseWindow.RESPONSE, THEIRS, reason="효과 발동")
    other = opened(ResponseWindow.RESPONSE, MINE, reason="효과 발동")

    assert first == same
    assert first.canonical_state() == same.canonical_state()
    assert first != other
    assert first.canonical_state() != other.canonical_state()


def test_the_canonical_state_is_plain_data():
    priority = opened(ResponseWindow.PHASE_CHANGE, THEIRS, phase=Phase.END)
    canonical = priority.canonical_state()

    assert canonical == ("player_1", "phase_change", 0, 0, "END", "")
    text = json.dumps(canonical)
    assert "0x" not in text and "object at" not in text
    json.dumps(priority.to_dict(), ensure_ascii=False)


def test_the_serialization_does_not_depend_on_the_hash_seed():
    """
    ``PYTHONHASHSEED`` 가 달라도 같은 값이어야 한다. 프로세스를 새로 띄워
    실제로 확인한다 — 같은 프로세스 안에서는 검증되지 않는 성질이다.
    """
    snippet = textwrap.dedent(
        """
        import json
        from engine.priority import PriorityState, ResponseWindow
        from engine.vocabulary import Phase

        priority = PriorityState.opened(
            ResponseWindow.RESPONSE, 1, turn_player=0, phase=Phase.MAIN1,
            reason="응답 기회"
        ).passed()
        print(json.dumps([priority.canonical_state(), priority.to_dict()],
                         ensure_ascii=False, sort_keys=True))
        """
    )
    outputs = []
    for seed in ("0", "1", "12345"):
        environment = dict(os.environ, PYTHONHASHSEED=seed)
        finished = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            env=environment,
            cwd=os.getcwd(),
        )
        assert finished.returncode == 0, finished.stderr
        outputs.append(finished.stdout)
    assert len(set(outputs)) == 1


# ======================================================================
# 3~5. 전이 — 패스와 연속 패스
# ======================================================================


def test_priority_passes_to_the_other_seat():
    first = opened(ResponseWindow.RESPONSE, MINE)

    second = first.passed()

    assert second.holder is PriorityHolder.PLAYER_1
    assert second.consecutive_passes == 1
    assert first.holder is PriorityHolder.PLAYER_0  # 원본은 그대로다
    assert first.consecutive_passes == 0


def test_priority_passes_back():
    priority = opened(ResponseWindow.RESPONSE, THEIRS).passed()

    assert priority.holder is PriorityHolder.PLAYER_0
    assert priority.consecutive_passes == 1


def test_two_passes_in_a_row_are_recorded_but_resolve_nothing():
    """
    **여기서 아무것도 해결하지 않는다.** 체인을 닫지도, 효과를 처리하지도,
    페이즈를 넘기지도 않는다. "둘 다 패스했다" 는 사실만 남는다.
    """
    priority = opened(ResponseWindow.RESPONSE, MINE, reason="효과 발동")

    after = priority.passed().passed()

    assert after.consecutive_passes == 2
    assert after.both_passed is True
    # 기회는 여전히 열려 있다 — 닫을지 말지는 체인 계층이 정한다.
    assert after.window is ResponseWindow.RESPONSE
    assert after.is_open is True
    assert after.holder is PriorityHolder.PLAYER_0
    assert after.reason == "효과 발동"


def test_acting_breaks_the_pass_streak():
    priority = opened(ResponseWindow.RESPONSE, MINE).passed()
    assert priority.consecutive_passes == 1

    after = priority.acted()

    assert after.consecutive_passes == 0
    assert after.both_passed is False
    assert after.holder is priority.holder  # 행동한 사람이 계속 쥐고 있다


def test_granting_priority_is_not_passing():
    """
    넘겨주는 것은 **새 기회를 주는 것**이라 연속 패스가 끊긴다. 패스로
    넘어가는 것과 다르다.
    """
    priority = opened(ResponseWindow.RESPONSE, MINE).passed()
    assert priority.consecutive_passes == 1

    granted = priority.give_to(MINE)

    assert granted.holder is PriorityHolder.PLAYER_0
    assert granted.consecutive_passes == 0


def test_closing_a_window_leaves_nobody_in_turn():
    priority = opened(ResponseWindow.RESPONSE, THEIRS).passed().passed()

    closed = priority.closed("체인 종료")

    assert closed.window is ResponseWindow.NONE
    assert closed.holder is PriorityHolder.NOBODY
    assert closed.consecutive_passes == 0
    assert closed.is_open is False
    assert closed.reason == "체인 종료"
    # 턴 문맥은 남는다.
    assert closed.turn_player == priority.turn_player
    assert closed.phase is priority.phase


def test_passing_never_closes_the_window_on_its_own():
    """
    패스가 기회를 닫는다면 그 판단이 이미 규칙이다. 닫는 것은 호출 쪽의
    결정이어야 한다.
    """
    priority = opened(ResponseWindow.RESPONSE, MINE)
    for _ in range(6):
        priority = priority.passed()
        assert priority.is_open is True
        assert priority.window is ResponseWindow.RESPONSE
    assert priority.consecutive_passes == 6


# ======================================================================
# 6. 잘못된 전이
# ======================================================================


def test_nothing_can_happen_when_no_window_is_open():
    idle = PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1)

    assert idle.is_open is False
    assert idle.holder is PriorityHolder.NOBODY
    for transition in ("passed", "acted"):
        with pytest.raises(PriorityError):
            getattr(idle, transition)()
    with pytest.raises(PriorityError):
        idle.give_to(MINE)


def test_a_state_cannot_claim_a_holder_without_a_window():
    with pytest.raises(PriorityError):
        PriorityState(holder=PriorityHolder.PLAYER_0, window=ResponseWindow.NONE)


def test_a_state_cannot_open_a_window_with_nobody_in_turn():
    with pytest.raises(PriorityError):
        PriorityState(holder=PriorityHolder.NOBODY, window=ResponseWindow.ACTION)


def test_none_is_not_a_window_you_can_open():
    with pytest.raises(PriorityError):
        PriorityState.opened(ResponseWindow.NONE, MINE)


def test_priority_cannot_be_given_to_nobody():
    with pytest.raises(PriorityError):
        opened().give_to(PriorityHolder.NOBODY)


@pytest.mark.parametrize("seat", [-1, 2, 99])
def test_a_seat_that_does_not_exist_is_refused(seat):
    with pytest.raises(ValueError):
        PriorityHolder.of(seat)
    with pytest.raises(ValueError):
        opened().give_to(seat)


def test_a_bad_turn_player_is_refused():
    with pytest.raises(ValueError):
        PriorityState.idle(turn_player=5)


def test_a_negative_pass_count_is_refused():
    with pytest.raises(ValueError):
        PriorityState(
            holder=PriorityHolder.PLAYER_0,
            window=ResponseWindow.ACTION,
            consecutive_passes=-1,
        )


# ======================================================================
# 7. 기회와 턴 문맥의 보존
# ======================================================================


def test_a_transition_keeps_the_window_and_the_turn_context():
    priority = opened(
        ResponseWindow.PHASE_CHANGE, MINE, turn_player=THEIRS, phase=Phase.END,
        reason="엔드 페이즈 진입",
    )

    for after in (priority.passed(), priority.acted(), priority.give_to(THEIRS)):
        assert after.window is ResponseWindow.PHASE_CHANGE
        assert after.turn_player == THEIRS
        assert after.phase is Phase.END
        assert after.reason == "엔드 페이즈 진입"


def test_the_turn_context_can_be_re_synced_without_progressing_anything():
    priority = opened(ResponseWindow.ACTION, MINE, phase=Phase.MAIN1).passed()

    moved = priority.in_phase(Phase.BATTLE, turn_player=THEIRS)

    assert moved.phase is Phase.BATTLE
    assert moved.turn_player == THEIRS
    assert moved.holder is priority.holder
    assert moved.consecutive_passes == priority.consecutive_passes
    assert priority.phase is Phase.MAIN1  # 원본은 그대로


def test_the_holder_is_not_forced_to_be_the_turn_player():
    """
    ``holder == turn_player`` 를 어디에서도 강제하지 않는다. 상대의 응답
    기회가 바로 그 반례다.
    """
    priority = opened(ResponseWindow.RESPONSE, THEIRS, turn_player=MINE)

    assert priority.turn_player == MINE
    assert priority.holder is PriorityHolder.PLAYER_1
    assert priority.holder_is_turn_player is False
    assert opened(ResponseWindow.ACTION, MINE, turn_player=MINE).holder_is_turn_player


def test_nobody_has_no_opposite():
    assert PriorityHolder.NOBODY.opponent is PriorityHolder.NOBODY
    assert PriorityHolder.NOBODY.seat is None
    assert PriorityHolder.NOBODY.holds is False
    assert PriorityHolder.PLAYER_0.opponent is PriorityHolder.PLAYER_1
    assert PriorityHolder.PLAYER_1.opponent is PriorityHolder.PLAYER_0
    assert PriorityHolder.of(1).seat == 1


def test_an_absolute_seat_is_not_a_relative_reference():
    """
    :class:`PlayerRef` 는 문맥 상대적("자신"/"상대")이고
    :class:`PriorityHolder` 는 절대적이다. 우선권에는 기준이 될 문맥이 없다.
    """
    assert not isinstance(PriorityHolder.PLAYER_0, PlayerRef)
    assert {holder.value for holder in PriorityHolder}.isdisjoint(
        {ref.value for ref in PlayerRef}
    )


# ======================================================================
# 8~9. 판을 건드리지 않는다
# ======================================================================


def test_building_and_transitioning_never_touches_the_board(state):
    before = state.state_hash()

    priority = PriorityState.opened(
        ResponseWindow.RESPONSE, THEIRS, state.turn.turn_player, state.turn.phase
    )
    priority.passed().passed().acted().give_to(MINE).closed()

    assert state.state_hash() == before


def test_asking_who_has_priority_never_touches_the_board(state, view):
    before = state.state_hash()
    resolver = PriorityResolver(view, opened())

    resolver.may_act(MINE)
    resolver.may_act(THEIRS)
    resolver.may_respond(MINE)
    _ = resolver.holder, resolver.window, resolver.both_passed

    assert state.state_hash() == before


def test_the_priority_layer_has_no_handle_on_the_board():
    """
    ``PriorityState`` 는 ``GameState`` 를 담지 않는다. 담으면 특정 판에
    묶이고 직렬화도 replay 도 불가능해진다.
    """
    priority = opened()
    assert PriorityState.__slots__ == (
        "holder",
        "window",
        "consecutive_passes",
        "turn_player",
        "phase",
        "reason",
    )
    for held in (priority.holder, priority.window, priority.phase):
        assert not isinstance(held, GameState)
    for forbidden in ("state", "game", "apply", "mutate"):
        assert not hasattr(priority, forbidden), forbidden


def test_the_resolver_refuses_a_raw_game_state(state):
    with pytest.raises(TypeError):
        PriorityResolver(state, opened())
    view = GameStateView.from_state(state, viewer=MINE)
    with pytest.raises(TypeError):
        PriorityResolver(view, "not a priority state")


def test_priority_is_not_part_of_the_board_hash(state):
    """
    우선권은 판의 **모양**이 아니라 흐름의 위치다. ``state_hash()`` 에
    섞으면 "같은 판" 의 뜻이 달라진다 (``EventJournal`` 과 같은 이유).
    """
    twin = new_state()
    assert state.state_hash() == twin.state_hash()

    _ = opened(ResponseWindow.RESPONSE, THEIRS)
    _ = opened(ResponseWindow.ACTION, MINE).passed()

    assert state.state_hash() == twin.state_hash()


def test_cloning_a_board_is_still_independent(state):
    """기존 ``GameState.clone()`` 의 독립성이 그대로인지 확인한다."""
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    copy.move(copy.player(MINE).hand[0], Zone.GRAVE, to_player=MINE)

    assert copy.state_hash() != state.state_hash()
    assert len(state.player(MINE).grave) == 0


# ======================================================================
# 10~11. 조회 판정
# ======================================================================


def test_the_holder_may_act_and_the_other_may_not(view):
    resolver = PriorityResolver(view, opened(ResponseWindow.ACTION, MINE))

    mine = resolver.may_act(MINE)
    theirs = resolver.may_act(THEIRS)

    assert mine.validity is ActionValidity.VALID
    assert mine.permits_execution is True
    assert theirs.validity is ActionValidity.INVALID
    assert theirs.code is ValidationCode.NOT_PRIORITY_HOLDER
    assert theirs.permits_execution is False


def test_nobody_may_act_when_no_window_is_open(view):
    resolver = PriorityResolver(view, PriorityState.idle(MINE, Phase.MAIN1))

    for seat in (MINE, THEIRS):
        verdict = resolver.may_act(seat)
        assert verdict.validity is ActionValidity.INVALID
        assert verdict.code is ValidationCode.NO_RESPONSE_WINDOW


def test_an_action_window_is_not_a_response_window(view):
    resolver = PriorityResolver(view, opened(ResponseWindow.ACTION, MINE))

    assert resolver.may_act(MINE).validity is ActionValidity.VALID
    responded = resolver.may_respond(MINE)
    assert responded.validity is ActionValidity.INVALID
    assert responded.code is ValidationCode.NO_RESPONSE_WINDOW


def test_a_response_window_permits_responding(view):
    resolver = PriorityResolver(view, opened(ResponseWindow.RESPONSE, MINE))
    assert resolver.may_respond(MINE).validity is ActionValidity.VALID
    assert resolver.may_respond(THEIRS).code is ValidationCode.NOT_PRIORITY_HOLDER


def test_having_priority_does_not_claim_a_legal_action_exists(view):
    """
    ``VALID`` 는 **차례가 그 사람의 것**이라는 뜻일 뿐이다. 할 수 있는 행위가
    하나라도 있다는 뜻이 아니다.
    """
    verdict = PriorityResolver(view, opened()).may_act(MINE)
    assert verdict.validity is ActionValidity.VALID
    assert "별개로 판정" in verdict.reason


def test_a_verdict_cannot_be_read_as_a_boolean(view):
    verdict = PriorityResolver(view, opened()).may_act(THEIRS)
    with pytest.raises(TypeError):
        bool(verdict)


@pytest.mark.parametrize("seat", [-1, 2])
def test_asking_about_a_seat_that_does_not_exist_is_refused(view, seat):
    with pytest.raises(ValueError):
        PriorityResolver(view, opened()).may_act(seat)


def test_a_stale_priority_state_answers_unknown_not_invalid(state):
    """
    복사본이 어긋났다는 것은 어느 한쪽이 낡았다는 뜻인데 **어느 쪽인지 알 수
    없다.** 모르는 것을 "안 된다" 로 단정하지 않는다.
    """
    view = GameStateView.from_state(state, viewer=MINE)  # T0 MAIN1

    for stale in (
        opened(ResponseWindow.ACTION, MINE, turn_player=THEIRS, phase=Phase.MAIN1),
        opened(ResponseWindow.ACTION, MINE, turn_player=MINE, phase=Phase.BATTLE),
    ):
        verdict = PriorityResolver(view, stale).may_act(MINE)
        assert verdict.validity is ActionValidity.UNKNOWN
        assert verdict.validity is not ActionValidity.INVALID
        assert verdict.code is ValidationCode.PRIORITY_STATE_STALE
        assert verdict.missing_rule
        assert verdict.notes


def test_a_matching_priority_state_is_not_stale(state):
    view = GameStateView.from_state(state, viewer=MINE)
    fresh = opened(
        ResponseWindow.ACTION, MINE, state.turn.turn_player, state.turn.phase
    )
    assert PriorityResolver(view, fresh).may_act(MINE).validity is ActionValidity.VALID


# ======================================================================
# 12. 정보를 새게 하지 않는다
# ======================================================================


def test_the_priority_layer_carries_no_card_information():
    """
    우선권 상태에는 카드가 **하나도** 들어 있지 않다. 그래서 상대의 패나
    세트 카드가 이 계층을 통해 새어 나갈 길이 없다.

    문자열 검색이 아니라 **모양**으로 확인한다 — ``"player_1"`` 안의 ``1``
    같은 우연한 일치에 속지 않기 위해서다.
    """
    from dataclasses import fields

    from engine.ids import EffectRef, InstanceId

    priority = opened(ResponseWindow.RESPONSE, THEIRS, reason="상대가 응답할 차례")

    # 담고 있는 값에 카드가 없다.
    for field in fields(priority):
        value = getattr(priority, field.name)
        assert not isinstance(value, (InstanceId, EffectRef)), field.name
        assert isinstance(value, (str, int, PriorityHolder, ResponseWindow, Phase))

    # 직렬화 결과의 칸도 정해진 것뿐이다.
    assert set(priority.to_dict()) <= {
        "holder",
        "window",
        "consecutive_passes",
        "turn_player",
        "phase",
        "reason",
    }


def test_both_viewers_see_the_same_priority_verdict(state):
    """
    우선권 판정은 관측자에 따라 달라지지 않는다 — 누구 차례인가는 공개
    정보이기 때문이다. 가려진 정보에 의존한다면 두 답이 갈렸을 것이다.
    """
    priority = opened(ResponseWindow.RESPONSE, THEIRS)
    mine = PriorityResolver(GameStateView.from_state(state, viewer=MINE), priority)
    theirs = PriorityResolver(GameStateView.from_state(state, viewer=THEIRS), priority)

    for seat in (MINE, THEIRS):
        assert (
            mine.may_act(seat).canonical_state()
            == theirs.may_act(seat).canonical_state()
        )


# ======================================================================
# 경계 — 조기에 만들지 않은 것
# ======================================================================


def test_the_priority_layer_knows_nothing_about_chains():
    """
    ``ChainLink`` · ``ChainResolver`` 류를 미리 만들지 않았다. "둘 다
    패스했다" 가 무엇을 뜻하는지도 여기서 정하지 않는다.
    """
    import engine.priority as module

    names = dir(module)
    for forbidden in ("Chain", "ChainLink", "ChainBlock", "Trigger", "SpellSpeed"):
        assert not any(forbidden in name for name in names), forbidden
    assert "chain" not in module.__doc__.lower().replace("체인", "")


def test_the_priority_layer_does_not_import_analysis():
    """``engine`` 은 ``analysis`` 의 실행 어휘를 가져오지 않는다 (Contract H)."""
    source = (
        __import__("pathlib").Path("engine/priority.py").read_text(encoding="utf-8")
    )
    assert "analysis" not in source


def test_the_window_vocabulary_is_exactly_what_this_step_promised():
    assert {window.value for window in ResponseWindow} == {
        "none",
        "action",
        "response",
        "phase_change",
    }
    assert ResponseWindow.NONE.allows_decision is False
    assert all(
        window.allows_decision
        for window in ResponseWindow
        if window is not ResponseWindow.NONE
    )
