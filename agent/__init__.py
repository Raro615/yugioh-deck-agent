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

Phase 3-B 가 그 자리에 **처음으로 판단하는 정책**을 앉혔다
(:mod:`agent.heuristic`). 명시적인 규칙만 쓴다 — 탐색도 학습도 없고,
판을 복제해 보지도 않는다. 모르는 값(``ATK ?``)은 **숫자로 바꾸지 않고
판단을 포기한다.**
"""

from agent.heuristic import (
    MIN_STAT_GAP,
    ATK_WEIGHT,
    BOARD_PRESENCE,
    DEF_WEIGHT,
    DEFAULT_CONSIDERATIONS,
    Appraisal,
    Consideration,
    EndThePhaseAsLastResort,
    Evaluation,
    HeuristicError,
    HigherAttackFirst,
    HigherDefenceBreaksTheTie,
    Judgement,
    RuleBasedPolicy,
    SummonBeforeEndingThePhase,
    rule_based_policy,
)
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
    # Phase 3-B — 규칙 기반 AI
    "RuleBasedPolicy",
    "rule_based_policy",
    "HeuristicError",
    "Appraisal",
    "Consideration",
    "Evaluation",
    "Judgement",
    "DEFAULT_CONSIDERATIONS",
    "SummonBeforeEndingThePhase",
    "HigherAttackFirst",
    "HigherDefenceBreaksTheTie",
    "EndThePhaseAsLastResort",
    "MIN_STAT_GAP",
    "ATK_WEIGHT",
    "DEF_WEIGHT",
    "BOARD_PRESENCE",
]
