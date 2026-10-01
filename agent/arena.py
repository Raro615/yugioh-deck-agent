"""
Arena — **AI 대 AI 한 판을 돌리고 무슨 일이 있었는지 적는다** (Phase 3-D).

    make_search()      ─┐
                        ├→ run_match(seed=…) → MatchResult
    make_rule_based()  ─┘

여기서 하지 않는 일
-------------------
**러너를 새로 만들지 않는다.** :class:`~agent.runner.DuelRunner` 가 이미
정책 둘을 받아 자리마다 제 관측을 넘겨 준다 (Phase 3-A). 이 모듈이 하는
일은 그 위에 둘뿐이다.

1. **정책을 판에 붙인다.** :class:`~agent.search.SearchPolicy` 는 그 듀얼의
   :class:`~agent.simulation.Simulator` 가 필요하므로, 정책을 미리 만들어
   둘 수 없고 **판이 생긴 뒤에** 만들어야 한다. 그것이 :data:`PolicyFactory`
   가 ``(duel, seat)`` 를 받는 이유다.
2. **끝나지 않은 판을 예외가 아니라 결과로 적는다.** 여러 판을 줄줄이 돌릴
   때 한 판이 터지면 나머지를 못 보게 되는데, 터진 것도 측정값이다.

승패로 우열을 말하지 않는다
---------------------------
:class:`MatchResult` 는 승자를 적지만, 지금 행동 공간에서는 **승패가 정책과
무관하다** (Phase 3-B 측정: ``ATTACK`` 이 후보에 없어 LP 가 움직이지 않고
남은 패배 조건은 덱아웃 하나다). 그래서 이 모듈은 승률을 집계하되 그것을
**강함의 척도로 쓰지 않는다** — 세는 것과 결론 내리는 것은 다른 일이다.

시뮬레이션과 실제 판을 섞지 않는다
----------------------------------
:class:`MatchResult` 는 **실제로 둔 수**의 기록이다. 탐색이 내다본 미래는
여기 없다. :class:`DecisionRecord` 가 탐색 쪽에서 가져오는 것은 "후보가
몇 개였고 몇 번 해 봤고 고른 것의 점수가 얼마였나" 뿐이고, 미래 관측은
가져오지 않는다 (§11 · §16).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from engine.action import PlayerAction
from engine.duel import Duel
from engine.state.game_state import DEFAULT_LIFE_POINTS
from engine.vocabulary import Phase

from agent.heuristic import rule_based_policy
from agent.policy import FirstLegalPolicy, Policy, RandomPolicy
from agent.runner import MAX_STEPS, DuelRunner, RunnerError, Transcript
from agent.search import SearchPolicy, search_policy


class ArenaError(RuntimeError):
    """대국을 잘못 차렸을 때."""


#: 판이 생긴 뒤에 그 자리의 정책을 만드는 것. ``(duel, seat) -> Policy``.
#:
#: 정책을 미리 만들어 두지 않는 이유는 :class:`SearchPolicy` 다 — 그 듀얼의
#: 시뮬레이터가 필요하므로 판보다 먼저 존재할 수 없다. 덤으로 **정책 객체가
#: 판마다 새로 생기므로** 지난 판의 상태가 넘어올 길도 없다.
PolicyFactory = Callable[[Duel, int], Policy]


class MatchOutcome(str, Enum):
    """
    한 판이 **어떻게 끝났는가.** 엔진의 승패와 다른 층이다.

    :class:`~engine.state.game_state.DuelResult` 는 규칙이 선언한 승패이고,
    이것은 **대국이 제대로 치러졌는가**다. 둘을 한 칸에 담으면 "안전 상한에
    걸렸다" 가 "졌다" 로 읽힌다 (§15).
    """

    COMPLETED = "completed"
    """엔진이 승패를 선언했다. 정상 종료다."""
    GAME_LIMIT_REACHED = "game_limit_reached"
    """안전 상한에 걸렸다. **승패가 아니다** — 승자는 ``None`` 이다."""
    POLICY_REFUSED = "policy_refused"
    """정책이 규약을 어겼다 (후보 밖의 수 따위). 듀얼의 사실이 아니라 결함이다."""
    ERROR = "error"
    """예외가 났다. 숨기지 않고 이유를 적는다."""

    @property
    def is_clean(self) -> bool:
        return self is MatchOutcome.COMPLETED


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """
    실제 결정 하나의 기록. **양쪽 정책에 똑같이 남는다** (§12).

    앞쪽 여섯 칸은 어느 정책이든 남는다. 뒤쪽 넷은 **탐색 정책일 때만**
    채워지고, 아니면 ``None`` 이다 — 0 으로 채우지 않는다. 0 은 "후보가
    없었다" 라는 사실이고 ``None`` 은 "탐색하지 않았다" 이며, 둘은 다르다.

    판도 관측도 담지 않는다. 상대의 패 · 덱 · 세트 카드가 들어갈 칸이 없다.
    """

    seat: int
    policy: str
    turn_number: int
    phase: "Phase | None"
    legal_count: int
    action: "PlayerAction | None"
    accepted: bool
    candidate_count: "int | None" = None
    simulations: "int | None" = None
    score: "tuple[str, int] | None" = None
    """고른 후보의 ``(등급, 휴리스틱)``. 점수가 없는 후보를 골랐으면 ``None``."""
    search_reason: str = ""

    @property
    def searched(self) -> bool:
        """이 결정이 **내다본** 결정인가."""
        return self.candidate_count is not None

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        what = self.action.kind.value if self.action is not None else "(없음)"
        where = f"T{self.turn_number} {self.phase.value if self.phase else '?'}"
        tail = ""
        if self.searched:
            grade = f"{self.score[0]} {self.score[1]:+d}" if self.score else "점수없음"
            tail = f" · 후보 {self.candidate_count} 시뮬 {self.simulations} → {grade}"
        return f"P{self.seat} {where} {self.policy}: {what} (후보 {self.legal_count}){tail}"


@dataclass(frozen=True, slots=True)
class MatchResult:
    """한 판의 측정값 전부. **실제로 둔 수**만 들어 있다."""

    seed: int
    names: tuple[str, str]
    outcome: MatchOutcome
    winner: "int | None"
    reason: str
    turns: int
    actions: int
    rule_steps: int
    simulations: int
    refusals: int
    life_points: tuple[int, int]
    state_hash: str
    decisions: tuple[DecisionRecord, ...]
    elapsed_ms: float
    decision_ms: tuple[float, ...] = ()
    """결정마다 정책이 쓴 시간. 적용 시간은 들어 있지 않다."""

    @property
    def completed(self) -> bool:
        return self.outcome.is_clean

    @property
    def longest_repeat(self) -> int:
        """
        **같은 자리에서 같은 수를 연달아** 몇 번 두었는가 (진단용).

        ``(자리, 턴, 페이즈, 수)`` 가 똑같이 반복되면 판이 전진하지 않은
        것이다. 이것으로 승패를 만들지 않는다 — 무한 반복을 막는 것은
        러너의 걸음 상한이고, 이 값은 **왜 상한에 걸렸는지** 읽는 데 쓴다
        (§14 · §15).
        """
        longest = run = 0
        previous = None
        for record in self.decisions:
            signature = (
                record.seat,
                record.turn_number,
                record.phase,
                None if record.action is None else record.action.canonical_state(),
            )
            run = run + 1 if signature == previous else 1
            previous = signature
            longest = max(longest, run)
        return longest

    def action_distribution(self, seat: "int | None" = None) -> "dict[str, int]":
        counts: dict[str, int] = {}
        for record in self.decisions:
            if seat is not None and record.seat != seat:
                continue
            if record.action is None:
                continue
            counts[record.action.kind.value] = (
                counts.get(record.action.kind.value, 0) + 1
            )
        return dict(sorted(counts.items()))

    def canonical_state(self) -> tuple:
        """
        **같은 대국인가**를 비교하는 모양. 재현 시험이 이것을 쓴다.

        시간은 넣지 않는다 — 같은 대국을 두 번 돌리면 같은 수가 나오지만
        같은 밀리초가 나오지는 않는다.
        """
        return (
            self.seed,
            self.outcome.value,
            self.winner,
            self.turns,
            self.actions,
            self.rule_steps,
            self.simulations,
            self.refusals,
            self.life_points,
            self.state_hash,
            tuple(
                (
                    record.seat,
                    record.turn_number,
                    record.phase.value if record.phase else None,
                    record.legal_count,
                    None if record.action is None else record.action.canonical_state(),
                    record.accepted,
                    record.candidate_count,
                    record.simulations,
                    record.score,
                )
                for record in self.decisions
            ),
        )

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        winner = "없음" if self.winner is None else f"P{self.winner}"
        return (
            f"seed={self.seed} {self.names[0]} vs {self.names[1]} → "
            f"{self.outcome.value} 승자 {winner} · 턴 {self.turns} · "
            f"수 {self.actions} · 시뮬 {self.simulations} · {self.elapsed_ms:.0f}ms"
        )


# ======================================================================
# 정책 공장 — 판이 생긴 뒤에 붙인다
# ======================================================================


class _Timed:
    """
    정책 하나를 감싸 **고르는 데 걸린 시간만** 잰다.

    고른 것은 **손대지 않고 그대로** 돌려준다. 감싼 것과 감싸지 않은 것이
    같은 대국을 만드는지는 시험이 확인한다.
    """

    __slots__ = ("inner", "name", "elapsed_ms")

    def __init__(self, inner: Policy):
        self.inner = inner
        self.name = getattr(inner, "name", type(inner).__name__)
        self.elapsed_ms: list[float] = []

    def decide(self, view, legal):
        started = time.perf_counter()
        chosen = self.inner.decide(view, legal)
        self.elapsed_ms.append((time.perf_counter() - started) * 1000.0)
        return chosen

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<timed {self.name}>"


def make_search(
    *, depth: int = 1, max_candidates: int = 16, max_simulations: int = 16
) -> PolicyFactory:
    """그 판의 시뮬레이터에 붙은 탐색 정책을 만드는 공장."""

    def build(duel: Duel, seat: int) -> Policy:
        return search_policy(
            duel,
            depth=depth,
            max_candidates=max_candidates,
            max_simulations=max_simulations,
            name=f"search-p{seat}",
        )

    return build


def make_rule_based() -> PolicyFactory:
    def build(duel: Duel, seat: int) -> Policy:
        return rule_based_policy(name=f"rule-based-p{seat}")

    return build


def make_random(seed: int) -> PolicyFactory:
    """
    자리마다 **다른** 씨앗을 쓴다 (``seed + seat``).

    같은 씨앗을 양쪽에 주면 두 정책이 같은 순서로 뽑아서, 서로 독립인
    정책 둘이 아니라 거울 둘이 된다.
    """

    def build(duel: Duel, seat: int) -> Policy:
        return RandomPolicy(seed=seed + seat, name=f"random-p{seat}")

    return build


def make_first_legal() -> PolicyFactory:
    def build(duel: Duel, seat: int) -> Policy:
        return FirstLegalPolicy(name=f"first-legal-p{seat}")

    return build


# ======================================================================
# 한 판
# ======================================================================


def _search_trace(policy) -> "list | None":
    """그 정책이 탐색 정책이면 그 흔적. 아니면 ``None``."""
    inner = getattr(policy, "inner", policy)
    if isinstance(inner, SearchPolicy):
        return inner.decisions
    return None


def _records(
    transcript: Transcript, policies: "tuple[Policy, Policy]"
) -> tuple[DecisionRecord, ...]:
    """
    기록 둘을 **자리별 순서로** 맞춘다.

    러너는 자리 ``s`` 의 걸음마다 ``policies[s].decide`` 를 **정확히 한 번**
    부른다. 그래서 자리 ``s`` 의 ``n`` 번째 걸음은 그 정책의 ``n`` 번째
    결정이다. 이 대응이 깨지면 점수가 다른 수에 붙으므로, 시험이 이것을
    따로 확인한다.
    """
    traces = {seat: _search_trace(policy) for seat, policy in enumerate(policies)}
    seen: dict[int, int] = {0: 0, 1: 0}
    records: list[DecisionRecord] = []
    for entry in transcript.entries:
        index = seen[entry.seat]
        seen[entry.seat] = index + 1
        trace = traces[entry.seat]

        candidate_count = simulations = None
        score = None
        search_reason = ""
        if trace is not None and index < len(trace):
            decision = trace[index]
            candidate_count = len(decision.candidates)
            simulations = decision.simulations
            search_reason = decision.reason
            chosen = (
                decision.of(decision.chosen) if decision.chosen is not None else None
            )
            if chosen is not None and chosen.value is not None:
                score = (chosen.value.terminal.value, chosen.value.heuristic)

        records.append(
            DecisionRecord(
                seat=entry.seat,
                policy=entry.policy,
                turn_number=entry.turn_number,
                phase=entry.phase,
                legal_count=entry.legal_count,
                action=entry.action,
                accepted=entry.accepted,
                candidate_count=candidate_count,
                simulations=simulations,
                score=score,
                search_reason=search_reason,
            )
        )
    return tuple(records)


def run_match(
    repository,
    *,
    decks,
    seed: int,
    factories: "tuple[PolicyFactory, PolicyFactory]",
    first_player: int = 0,
    life_points: int = DEFAULT_LIFE_POINTS,
    max_steps: int = MAX_STEPS,
) -> MatchResult:
    """
    AI 대 AI 한 판. **실제 엔진을 처음부터 끝까지** 쓴다.

    끝나지 않거나 터져도 던지지 않고 :class:`MatchOutcome` 으로 적는다 —
    여러 판을 줄줄이 돌릴 때 한 판이 터져서 나머지를 못 보게 되면, 터진
    것도 측정값이라는 사실을 잃는다.
    """
    if len(factories) != 2:
        raise ArenaError(f"정책 공장은 자리마다 하나씩 둘입니다: {len(factories)}개")

    duel = Duel.start(
        repository,
        decks=(list(decks[0]), list(decks[1])),
        seed=seed,
        first_player=first_player,
        life_points=life_points,
    )
    policies = tuple(
        _Timed(factory(duel, seat)) for seat, factory in enumerate(factories)
    )
    runner = DuelRunner(duel, policies)  # type: ignore[arg-type]

    started = time.perf_counter()
    outcome = MatchOutcome.COMPLETED
    failure = ""
    try:
        transcript = runner.run(max_steps=max_steps)
    except RunnerError as error:
        outcome = MatchOutcome.GAME_LIMIT_REACHED
        failure = str(error)
        transcript = runner.transcript()
    except Exception as error:  # noqa: BLE001 - 숨기지 않고 결과로 적는다
        outcome = MatchOutcome.ERROR
        failure = f"{type(error).__name__}: {error}"
        transcript = runner.transcript()
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if outcome is MatchOutcome.COMPLETED:
        if transcript.refusals:
            outcome = MatchOutcome.POLICY_REFUSED
            failure = transcript.refusals[0].reason
        elif transcript.result is None:
            # 끝나지 않았는데 러너가 조용히 돌아왔다. 승패로 바꾸지 않는다.
            outcome = MatchOutcome.GAME_LIMIT_REACHED
            failure = "러너가 더 나아가지 못했습니다."

    records = _records(transcript, policies)
    simulations = sum(
        record.simulations or 0 for record in records
    )
    return MatchResult(
        seed=seed,
        names=(policies[0].name, policies[1].name),
        outcome=outcome,
        # **승패는 엔진만 선언한다.** 상한에 걸린 판에는 승자가 없다.
        winner=transcript.result.winner if transcript.result is not None else None,
        reason=transcript.result.reason if transcript.result is not None else failure,
        turns=duel.state.turn.turn_number,
        actions=transcript.steps,
        rule_steps=transcript.rule_steps,
        simulations=simulations,
        refusals=len(transcript.refusals),
        life_points=(
            duel.state.player(0).life_points,
            duel.state.player(1).life_points,
        ),
        state_hash=duel.state.state_hash(),
        decisions=records,
        elapsed_ms=elapsed_ms,
        decision_ms=tuple(policies[0].elapsed_ms + policies[1].elapsed_ms),
    )


def run_series(
    repository,
    *,
    decks,
    seeds,
    factories: "tuple[PolicyFactory, PolicyFactory]",
    **kwargs,
) -> tuple[MatchResult, ...]:
    """여러 씨앗으로 같은 조합을 돌린다."""
    return tuple(
        run_match(repository, decks=decks, seed=seed, factories=factories, **kwargs)
        for seed in seeds
    )


# ======================================================================
# 집계 — 세는 것과 결론 내리는 것은 다른 일이다
# ======================================================================


@dataclass(frozen=True, slots=True)
class MatchupSummary:
    """
    한 조합의 집계. **승률이 들어 있지만 그것으로 우열을 말하지 않는다.**

    지금 행동 공간에서는 승패가 정책과 무관하다 (Phase 3-B 측정). 그래서
    :attr:`wins` 는 "이렇게 끝났다" 의 기록이고 강함의 척도가 아니다.
    """

    names: tuple[str, str]
    games: int
    completed: int
    refusals: int
    errors: int
    limits: int
    turns: int
    actions: int
    simulations: int
    wins: tuple[int, int]
    draws: int
    elapsed_ms: float
    decision_ms: tuple[float, ...] = ()
    distribution: "dict[str, int]" = field(default_factory=dict)

    @property
    def all_completed(self) -> bool:
        return self.games > 0 and self.completed == self.games

    @property
    def average_turns(self) -> float:
        return self.turns / self.games if self.games else 0.0

    @property
    def average_simulations(self) -> float:
        return self.simulations / self.games if self.games else 0.0

    @property
    def simulations_per_decision(self) -> float:
        return self.simulations / self.actions if self.actions else 0.0

    @property
    def average_decision_ms(self) -> float:
        return (
            sum(self.decision_ms) / len(self.decision_ms) if self.decision_ms else 0.0
        )

    @property
    def max_decision_ms(self) -> float:
        return max(self.decision_ms) if self.decision_ms else 0.0

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return (
            f"{self.names[0]} vs {self.names[1]}: {self.completed}/{self.games} 완주 · "
            f"거절 {self.refusals} · 예외 {self.errors} · 상한 {self.limits} · "
            f"평균 턴 {self.average_turns:.1f} · 시뮬 {self.simulations} · "
            f"결정 평균 {self.average_decision_ms:.2f}ms"
        )


def summarize(results: "tuple[MatchResult, ...]") -> MatchupSummary:
    if not results:
        raise ArenaError("집계할 판이 없습니다.")

    wins = [0, 0]
    draws = 0
    distribution: dict[str, int] = {}
    for result in results:
        if result.winner is None:
            draws += 1
        else:
            wins[result.winner] += 1
        for kind, count in result.action_distribution().items():
            distribution[kind] = distribution.get(kind, 0) + count

    return MatchupSummary(
        names=results[0].names,
        games=len(results),
        completed=sum(1 for r in results if r.completed),
        refusals=sum(r.refusals for r in results),
        errors=sum(1 for r in results if r.outcome is MatchOutcome.ERROR),
        limits=sum(
            1 for r in results if r.outcome is MatchOutcome.GAME_LIMIT_REACHED
        ),
        turns=sum(r.turns for r in results),
        actions=sum(r.actions for r in results),
        simulations=sum(r.simulations for r in results),
        wins=(wins[0], wins[1]),
        draws=draws,
        elapsed_ms=sum(r.elapsed_ms for r in results),
        decision_ms=tuple(ms for r in results for ms in r.decision_ms),
        distribution=dict(sorted(distribution.items())),
    )


__all__ = [
    "ArenaError",
    "PolicyFactory",
    "MatchOutcome",
    "DecisionRecord",
    "MatchResult",
    "MatchupSummary",
    "run_match",
    "run_series",
    "summarize",
    "make_search",
    "make_rule_based",
    "make_random",
    "make_first_legal",
]
