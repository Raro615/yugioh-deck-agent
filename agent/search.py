"""
SearchPolicy — **처음으로 미래를 보고 고르는 정책** (Phase 3-C).

    Observation + LegalActions
            ↓  후보마다
        Simulator.simulate(후보)      ← 사본에 진짜 엔진을 적용
            ↓
        GameStateView(viewer)
            ↓
        StateEvaluator
            ↓
        StateValue
            ↓  비교
        PlayerAction

Phase 3-B 와 무엇이 다른가
--------------------------
``RuleBasedPolicy`` 는 **행위 자체**를 보고 점수를 냈다 — "공격력 1900 인
카드를 소환하는 수" 에 1,901,600 점. 이 정책은 행위를 보지 않는다. 그 수를
**실제로 두어 본 뒤의 판**을 본다.

    RuleBased:  Action        → Score
    Search:     Action → 미래 State → Score

그래서 평가 함수가 행위의 종류를 몰라도 된다. "소환이 턴 넘기기보다
낫다" 를 규칙으로 적지 않아도, 소환한 판과 넘긴 판을 재어 보면 전자가
높게 나온다.

가장 중요한 불변조건
--------------------
**SEARCH MUST NEVER CHANGE THE REAL GAME.** 그 보장은 이 파일이 아니라
:class:`~agent.simulation.Simulator` 가 들고 있다 — 이 정책은 사본을 만들
수단도, 진짜 판을 만질 수단도 갖고 있지 않다.

후보를 만들어 내지 않는다
-------------------------
탐색하는 것은 ``legal.allowed`` 의 원소뿐이다 (§16). 지금 엔진이 내놓지
않는 ``ATTACK`` 을 탐색이 상상해서 넣는 일은 **구조적으로 일어날 수
없다** — 이 파일에 ``PlayerAction`` 을 만드는 자리가 없고, 시뮬레이터도
후보 목록에 없는 수를 받으면
:attr:`~agent.simulation.SimulationStatus.NOT_A_CANDIDATE` 로 되돌린다.

모르는 것을 최악으로 바꾸지 않는다
----------------------------------
시뮬레이션이 ``UNKNOWN`` 으로 끝난 후보는 **점수가 없다.** 0 점도, 최저
점수도 아니다 (§17 · §28). 점수가 있는 후보들 뒤에 놓이지만, 그것은
"나쁘다" 가 아니라 **"비교할 수 없다"** 는 뜻이고 흔적에 그렇게 남는다.
점수가 있는 후보가 하나도 없으면 고르기는 하되 아는 척하지 않는다.

깊이
----
이 Phase 가 공식 지원하는 깊이는 **1 뿐이다** (§5 · §9). 2 이상을 넣으면
거부한다 — 돌아가지 않는 설정을 받아 두는 것은 "지원한다" 는 거짓말이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel, LegalActions
from engine.game_state_view import GameStateView
from engine.vocabulary import Phase

from agent.evaluation import Evaluator, StateEvaluator, StateValue, Terminal
from agent.simulation import SimulationStatus, Simulator


class SearchError(RuntimeError):
    """탐색 정책을 잘못 조립하거나 잘못 썼을 때."""


#: 이 Phase 가 공식 지원하는 유일한 깊이 (§9 · §35).
SUPPORTED_DEPTH: int = 1

#: 한 결정에서 해 볼 후보의 상한. 실측 최대 후보 수는 11 이었다
#: (Phase 3-A, 실제 카드) — 16 은 지금의 행동 공간을 모두 덮는다.
#: 상한을 넘겨 못 해 본 후보는 **후보에서 빠지지 않는다.** 점수 없이
#: 흔적에 남고, 고를 수는 있다 (§36 · §37).
DEFAULT_MAX_CANDIDATES: int = 16

#: 한 결정에서 돌릴 시뮬레이션의 상한. 깊이가 1 이면 후보 수와 같다.
DEFAULT_MAX_SIMULATIONS: int = 16

#: 예산 때문에 해 보지 못했다는 기록.
SKIPPED_BY_BUDGET: str = "예산 상한에 걸려 해 보지 못했습니다"


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """
    후보 하나에 대한 기록. **판도 관측도 들고 있지 않다.**

    흔적은 오래 살기 때문에 관측을 담으면 가려진 정보가 그만큼 오래
    남는다. 그래서 남기는 것은 행위 · 상태 · 점수 · 이유뿐이다 (§31).
    """

    action: PlayerAction
    status: "SimulationStatus | None"
    value: "StateValue | None" = None
    reason: str = ""

    @property
    def comparable(self) -> bool:
        """점수가 있어 다른 후보와 **견줄 수 있는가.**"""
        return self.value is not None

    def ordering_key(self) -> tuple:
        """
        **작은 쪽이 좋다.** 네 단계로 결정론적으로 줄 세운다 (§30).

        1. 점수가 있는 후보가 먼저 (``UNKNOWN`` 은 나쁜 것이 아니라
           견줄 수 없는 것이므로 뒤로 간다)
        2. 끝난 판의 등급이 높은 쪽 (승리는 어떤 휴리스틱보다 앞선다)
        3. 휴리스틱이 높은 쪽
        4. ``canonical_state`` 가 작은 쪽 — 목록의 순서나 파이썬의 반복
           순서에 **기대지 않는다**
        """
        if self.value is None:
            return (1, 0, 0, self.action.canonical_state())
        terminal, heuristic = self.value.ordering_key()
        return (0, -terminal, -heuristic, self.action.canonical_state())

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        if self.value is None:
            label = self.status.value if self.status is not None else "미실행"
            return f"{self.action} → {label} (점수 없음: {self.reason})"
        return f"{self.action} → {self.value.describe_ko()}"


@dataclass(frozen=True, slots=True)
class SearchDecision:
    """
    한 결정 지점의 흔적. 개발자가 **AI 가 무엇을 내다봤는지** 읽는 자리다.

    ``state_hash`` 는 되돌려 읽을 수 없는 요약이므로 남겨도 가려진 정보가
    새지 않는다. 판 전체는 남기지 않는다 (§31).
    """

    seat: int
    state_hash: str
    turn_number: int
    phase: Phase
    candidates: tuple[SearchCandidate, ...]
    chosen: "PlayerAction | None"
    reason: str
    simulations: int = 0
    skipped: int = 0
    """예산 때문에 해 보지 못한 후보 수. 0 이 아니면 보고에 적는다 (§37)."""

    @property
    def comparable_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.comparable)

    @property
    def nothing_was_comparable(self) -> bool:
        """점수가 있는 후보가 **하나도 없었는가.**"""
        return bool(self.candidates) and self.comparable_count == 0

    def of(self, action: PlayerAction) -> "SearchCandidate | None":
        for candidate in self.candidates:
            if candidate.action == action:
                return candidate
        return None

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [
            f"P{self.seat} T{self.turn_number} {self.phase.value} "
            f"state_hash={self.state_hash[:12]}… 시뮬레이션 {self.simulations}회",
            f"  이유: {self.reason}",
        ]
        for candidate in sorted(self.candidates, key=lambda c: c.ordering_key()):
            mark = "→" if candidate.action == self.chosen else " "
            lines.append(f" {mark} {candidate.describe_ko()}")
        return "\n".join(lines)


@dataclass
class SearchPolicy:
    """
    후보를 **해 보고** 고르는 정책.

    :attr:`simulator` 없이도 만들 수 있지만 고르지는 못한다 — 붙지 않은
    정책이 조용히 다른 방법으로 고르면, 탐색했다고 믿는 결정이 실은 탐색이
    아니게 된다. 그래서 :meth:`decide` 에서 거부한다.

    듀얼마다 :meth:`attach` 로 새 시뮬레이터를 붙인다. 그때 흔적을
    **지운다** — 정책 객체를 다시 써도 지난 듀얼이 남지 않아야 한다 (§40).
    """

    simulator: "Simulator | None" = None
    evaluator: Evaluator = field(default_factory=StateEvaluator)
    depth: int = SUPPORTED_DEPTH
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_simulations: int = DEFAULT_MAX_SIMULATIONS
    name: str = "search"
    decisions: list[SearchDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.depth != SUPPORTED_DEPTH:
            raise SearchError(
                f"이 Phase 가 지원하는 깊이는 {SUPPORTED_DEPTH} 뿐입니다: "
                f"depth={self.depth}"
            )
        for name, value in (
            ("max_candidates", self.max_candidates),
            ("max_simulations", self.max_simulations),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SearchError(f"{name} 는 1 이상의 정수입니다: {value!r}")
        if not isinstance(self.evaluator, Evaluator):
            raise SearchError(
                f"평가자에 evaluate 가 없습니다: {type(self.evaluator).__name__}"
            )
        if self.simulator is not None and not isinstance(self.simulator, Simulator):
            raise SearchError(
                f"Simulator 가 필요합니다: {type(self.simulator).__name__}"
            )

    # ------------------------------------------------------------------
    def attach(self, simulator: Simulator) -> "SearchPolicy":
        """새 듀얼에 붙인다. **지난 듀얼의 흔적을 지운다** (§40)."""
        if not isinstance(simulator, Simulator):
            raise SearchError(
                f"Simulator 가 필요합니다: {type(simulator).__name__}"
            )
        self.simulator = simulator
        self.decisions = []
        return self

    # ------------------------------------------------------------------
    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        if self.simulator is None:
            raise SearchError(
                "시뮬레이터가 붙지 않은 탐색 정책입니다 — attach(Simulator) 가 "
                "먼저입니다. 붙지 않은 채로 다른 방법으로 고르지 않습니다."
            )
        if not legal.allowed:
            self.decisions.append(
                SearchDecision(
                    seat=legal.seat,
                    state_hash=self.simulator.state_hash(),
                    turn_number=self.simulator.turn_number,
                    phase=self.simulator.phase,
                    candidates=(),
                    chosen=None,
                    reason="고를 것이 없습니다.",
                )
            )
            return None

        candidates, simulations, skipped = self._look_ahead(view, legal)
        best = min(candidates, key=lambda candidate: candidate.ordering_key())

        if best.comparable:
            reason = f"내다본 결과가 가장 좋습니다: {best.value.describe_ko()}"
        else:
            # 점수가 있는 후보가 하나도 없다. 고르기는 하지만 **내다봤다고
            # 말하지 않는다.**
            reason = (
                "견줄 수 있는 후보가 없었습니다 — 내다보지 못한 채 "
                "결정론적 순서로 골랐습니다."
            )

        self.decisions.append(
            SearchDecision(
                seat=legal.seat,
                state_hash=self.simulator.state_hash(),
                turn_number=self.simulator.turn_number,
                phase=self.simulator.phase,
                candidates=candidates,
                chosen=best.action,
                reason=reason,
                simulations=simulations,
                skipped=skipped,
            )
        )
        return best.action

    def _look_ahead(
        self, view: GameStateView, legal: LegalActions
    ) -> tuple[tuple[SearchCandidate, ...], int, int]:
        """
        후보마다 한 수를 해 보고 그 미래를 잰다. **깊이 1 이다.**

        예산을 고르는 순서는 ``canonical_state`` 다 — 목록의 순서에 따라
        누가 평가받는지 달라지면, 같은 판에서 다른 수가 나올 수 있다.
        """
        ordered = sorted(legal.allowed, key=lambda action: action.canonical_state())
        budget = min(self.max_candidates, self.max_simulations)

        candidates: list[SearchCandidate] = []
        simulations = 0
        skipped = 0
        for action in ordered:
            if simulations >= budget:
                # **후보에서 빼지 않는다.** 점수만 없다 (§36).
                skipped += 1
                candidates.append(
                    SearchCandidate(
                        action=action, status=None, reason=SKIPPED_BY_BUDGET
                    )
                )
                continue

            result = self.simulator.simulate(action, viewer=legal.seat)
            simulations += 1

            if result.status is not SimulationStatus.SUPPORTED:
                candidates.append(
                    SearchCandidate(
                        action=action,
                        status=result.status,
                        reason=result.reason,
                    )
                )
                continue

            candidates.append(
                SearchCandidate(
                    action=action,
                    status=result.status,
                    value=self.evaluator.evaluate(result.future),
                    reason=result.reason,
                )
            )
        return tuple(candidates), simulations, skipped

    # ------------------------------------------------------------------
    @property
    def last_decision(self) -> "SearchDecision | None":
        return self.decisions[-1] if self.decisions else None

    def simulation_count(self) -> int:
        """지금까지 돌린 시뮬레이션 총합."""
        return sum(decision.simulations for decision in self.decisions)

    def skipped_count(self) -> int:
        """예산 때문에 해 보지 못한 후보 총합. 0 이 아니면 보고에 적는다."""
        return sum(decision.skipped for decision in self.decisions)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<{self.name} depth={self.depth} 결정 {len(self.decisions)}회 "
            f"시뮬레이션 {self.simulation_count()}회>"
        )


def search_policy(
    duel: Duel,
    *,
    evaluator: "Evaluator | None" = None,
    depth: int = SUPPORTED_DEPTH,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_simulations: int = DEFAULT_MAX_SIMULATIONS,
    name: str = "search",
) -> SearchPolicy:
    """그 듀얼에 붙은 탐색 정책 하나."""
    return SearchPolicy(
        simulator=Simulator(duel),
        evaluator=StateEvaluator() if evaluator is None else evaluator,
        depth=depth,
        max_candidates=max_candidates,
        max_simulations=max_simulations,
        name=name,
    )


__all__ = [
    "SearchError",
    "SearchCandidate",
    "SearchDecision",
    "SearchPolicy",
    "search_policy",
    "SUPPORTED_DEPTH",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_SIMULATIONS",
    "SKIPPED_BY_BUDGET",
]
