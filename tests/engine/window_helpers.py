"""
빠른 효과 기회를 **실제 PASS 로** 지나가는 공용 도구 (Phase 6-AB 보완5).

🔴 **왜 이 파일이 생겼나**

보완5 가 공식 Fast Effect Timing 도표의 상자 B · C 를 엔진에 실었다 —
*"Whenever either player performs an action, the game state is no longer
open"* 이고, 다시 열리려면 **턴 플레이어가 지나가고 상대가 되돌려
지나가야** 한다.

그래서 **판을 바꾸는 행동 뒤에는 PASS 둘이 필수 절차로 끼어든다.** 보완5
전의 시험들은 행동 하나 뒤에 곧바로 다음 행동을 넣었고, 그 기대값은
확인된 규칙과 충돌한다 (보완5 §3-3 · §3-5). 그 기대값을 **정정**하면서
같은 세 줄을 스물한 파일에 복사하지 않기 위해 이 자리를 만들었다.

🔴 **이것은 테스트 전용 허가가 아니다.** 하는 일은 ``legal_actions`` 로
PASS 가 올라 있는지 보고 ``Duel.apply`` 로 넣는 것뿐이다 — 손으로
우선권을 돌리거나 상태를 주입하지 않는다. 즉 **사람이 하는 일을 그대로**
한다.

이 파일은 ``test_`` 로 시작하지 않으므로 pytest 가 수집하지 않는다.
"""

from __future__ import annotations

from engine.action import PlayerAction, PlayerActionKind

#: PASS 둘이면 닫힌다 (상자 B → C → A). 여유를 조금 두고 상한을 건다 —
#: 무한 반복으로 시험이 매달리는 쪽이 실패보다 나쁘다.
MAX_PASSES = 6


def pass_fast_window(duel):
    """
    열려 있는 **빠른 효과 기회**를 지나간다. 열려 있지 않으면 아무것도 안 한다.

    체인이 서 있으면 **건드리지 않는다** — 그쪽은 응답 창이고 PASS 의 뜻이
    다르다 (체인을 푼다). 이 함수는 ``chain.is_empty`` 일 때만 지나간다.
    """
    steps = []
    for _ in range(MAX_PASSES):
        if not duel.priority.is_open or not duel.chain.is_empty:
            break
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        if passing not in duel.legal_actions(holder).allowed:
            break
        steps.append(duel.apply(passing))
    return steps


def act(duel, action):
    """
    행동 하나를 넣고 **그 뒤의 빠른 효과 기회까지** 지나간다.

    돌려주는 것은 **그 행동의 걸음**이다 — 뒤따르는 PASS 의 걸음이 아니다.
    그래서 ``step.accepted`` · ``step.reason`` 을 읽는 기존 시험이 재는
    대상을 바꾸지 않는다.
    """
    step = duel.apply(action)
    if step.accepted:
        pass_fast_window(duel)
    return step


def reopen(duel):
    """
    판이 다시 **열린 상태**가 되게 한다. 유발 처리 기회가 남아 있으면
    그것부터 지나간다.

    🔴 유발 기회를 지나가는 PASS 와 빠른 효과 기회를 지나가는 PASS 는
    **다른 것**이지만, 둘 다 "지나간다" 는 점은 같고 둘 다
    ``legal_actions`` 를 지난다. 어느 쪽을 지나갔는지는 돌려주는 걸음들의
    ``reason`` 에 그대로 남는다.
    """
    steps = []
    for _ in range(MAX_PASSES * 2):
        if not duel.chain.is_empty:
            break
        actor = duel._window_actor()
        if actor is None:
            if not duel.priority.is_open:
                break
            actor = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=actor)
        if passing not in duel.legal_actions(actor).allowed:
            break
        steps.append(duel.apply(passing))
    return steps


class Steps(list):
    """
    패스로 지난 걸음들. ``resolution`` 은 **체인을 푼** 걸음이다.

    🔴 **마지막 걸음이 해결 걸음이 아니다** (보완5). 체인이 풀린 뒤에도
    양측이 빠른 효과 기회를 지나가야 판이 열리므로, ``[-1]`` 은 *"양쪽이
    빠른 효과 기회를 지나갔습니다"* 가 된다 — 그것은 **절차를 지났다는
    말이고 링크의 결과가 아니다.** 불발 · 대상 미선택 · 후보 아님이 전부
    그 한 문장으로 덮인다 (실측).

    체인이 서지 않았으면 ``resolution`` 은 ``None`` 이다.
    """

    resolution = None


def settle(duel, *, limit=8):
    """
    창이 닫힐 때까지 **실제 PASS 로** 지난다. 돌려주는 것은 :class:`Steps` 다.

    유발 등재 단계는 건드리지 않는다 — 우선권이 열려 있을 때만 움직인다.
    """
    steps = Steps()
    for _ in range(limit):
        if not duel.priority.is_open:
            break
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        if passing not in duel.legal_actions(holder).allowed:
            break
        had_chain = not duel.chain.is_empty
        steps.append(duel.apply(passing))
        if had_chain and duel.chain.is_empty:
            steps.resolution = steps[-1]
    return steps


def resolve_and_reopen(duel):
    """
    체인을 풀고 그 뒤의 빠른 효과 기회까지 지나간다.

    돌려주는 것은 ``(해결 걸음, 그 뒤의 걸음들)`` 이다 — 해결 걸음을 따로
    주는 이유가 있다. 보완5 전까지 시험들은 "마지막 걸음" 의 ``reason`` 에서
    *"체인1 … 를 해결했습니다"* 를 찾았는데, 지금은 마지막 걸음이 빠른 효과
    기회를 닫는 PASS 다. **마지막이 아니라 해결을 읽어야 한다.**
    """
    resolution = None
    trailing = []
    for _ in range(MAX_PASSES * 2):
        if not duel.priority.is_open:
            break
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        if passing not in duel.legal_actions(holder).allowed:
            break
        had_chain = not duel.chain.is_empty
        step = duel.apply(passing)
        if had_chain and duel.chain.is_empty:
            resolution = step
        elif resolution is not None:
            trailing.append(step)
    return resolution, trailing


__all__ = [
    "MAX_PASSES",
    "PlayerActionKind",
    "Steps",
    "act",
    "pass_fast_window",
    "reopen",
    "resolve_and_reopen",
    "settle",
]
