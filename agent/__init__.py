"""
agent — **엔진을 쓰는 쪽** (Phase 3).

``engine/`` 은 Phase 2-AO 에서 얼렸다 (ENGINE V1 FREEZE). 이 꾸러미는 그것을
**고치지 않고 쓴다** — 한 줄도 바꾸지 않는다.

    engine.duel.Duel            규칙
        ↓ view(seat) · legal_actions(seat)
    agent.policy.Policy         고르는 쪽
        ↓ PlayerAction
    agent.runner.DuelRunner     전달과 기록

경계가 하나다: **정책은 관측과 후보 목록만 본다.** ``Duel`` 도
``GameState`` 도 정책에게 가지 않는다.
"""

from agent.policy import (
    Decision,
    FirstLegalPolicy,
    Policy,
    PolicyError,
    RandomPolicy,
    ScriptedPolicy,
)
from agent.runner import (
    MAX_STEPS,
    DuelRunner,
    RunnerError,
    Transcript,
    TranscriptEntry,
    play,
)

__all__ = [
    "Policy",
    "PolicyError",
    "Decision",
    "FirstLegalPolicy",
    "RandomPolicy",
    "ScriptedPolicy",
    "DuelRunner",
    "RunnerError",
    "Transcript",
    "TranscriptEntry",
    "MAX_STEPS",
    "play",
]
