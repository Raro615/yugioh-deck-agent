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

Phase 3-C 가 **미래를 보는 정책**을 더했다 (:mod:`agent.search`).

    agent.simulation.Simulator   사본에 진짜 엔진을 적용하고 **관측만** 준다
    agent.evaluation             미래 관측 하나를 LP 단위의 값으로 바꾼다
    agent.search.SearchPolicy    후보마다 해 보고 가장 좋은 미래를 고른다

불변조건은 하나다 — **탐색은 진짜 판을 바꾸지 않는다.** 사본은
``GameState.clone()`` 으로 만든다. ``project()`` 는 난수원을 원본과 함께
쓰므로 **탐색에 쓰지 않는다.**

Phase 3-D 가 **AI 대 AI** 를 붙였다 (:mod:`agent.arena`). 러너를 새로
만들지 않았다 — ``DuelRunner`` 가 이미 정책 둘에게 자리마다 제 관측을
넘긴다. 아레나가 더한 것은 둘이다: 판이 생긴 뒤에 정책을 붙이는
:data:`~agent.arena.PolicyFactory`, 그리고 끝나지 않은 판을 예외가 아니라
:class:`~agent.arena.MatchOutcome` 으로 적는 일.
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
from agent.arena import (
    ArenaError,
    DecisionRecord,
    MatchOutcome,
    MatchResult,
    MatchupSummary,
    PolicyFactory,
    make_first_legal,
    make_random,
    make_rule_based,
    make_search,
    run_match,
    run_series,
    summarize,
)
from agent.evaluation import (
    ATK_IN_LP,
    DECK_CARD_IN_LP,
    HAND_CARD_IN_LP,
    MONSTER_IN_LP,
    OPPONENT_RESOURCE_ZONES,
    SPELL_TRAP_IN_LP,
    EvaluationError,
    Evaluator,
    OpponentResourceDelta,
    OpponentResources,
    StateEvaluator,
    StateValue,
    Terminal,
)
from agent.policy import (
    Decision,
    FirstLegalPolicy,
    Policy,
    PolicyError,
    RandomPolicy,
    ScriptedPolicy,
)
from agent.search import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_SIMULATIONS,
    SUPPORTED_DEPTH,
    SearchCandidate,
    SearchDecision,
    SearchError,
    SearchPolicy,
    search_policy,
)
from agent.simulation import (
    SimulationError,
    SimulationResult,
    SimulationStatus,
    Simulator,
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
    # Phase 3-C — 탐색 / 시뮬레이션 AI
    "Simulator",
    "SimulationResult",
    "SimulationStatus",
    "SimulationError",
    "Terminal",
    "StateValue",
    "Evaluator",
    "StateEvaluator",
    "OpponentResources",
    "OpponentResourceDelta",
    "OPPONENT_RESOURCE_ZONES",
    "EvaluationError",
    "ATK_IN_LP",
    "MONSTER_IN_LP",
    "SPELL_TRAP_IN_LP",
    "DECK_CARD_IN_LP",
    "HAND_CARD_IN_LP",
    "SearchPolicy",
    "search_policy",
    "SearchCandidate",
    "SearchDecision",
    "SearchError",
    "SUPPORTED_DEPTH",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_SIMULATIONS",
    # Phase 3-D — AI 대 AI
    "run_match",
    "run_series",
    "summarize",
    "MatchResult",
    "MatchOutcome",
    "MatchupSummary",
    "DecisionRecord",
    "PolicyFactory",
    "ArenaError",
    "make_search",
    "make_rule_based",
    "make_random",
    "make_first_legal",
]
