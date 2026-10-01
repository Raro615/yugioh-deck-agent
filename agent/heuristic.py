"""
Rule-Based Duel AI — **처음으로 실제로 판단하는 정책** (Phase 3-B).

    GameStateView + LegalActions
            ↓
      Consideration 들이 후보마다 점수를 낸다
            ↓
      가장 높은 후보 하나
            ↓
        PlayerAction

Phase 3-A 가 만든 것은 자리였다. 거기 앉는 첫 번째가 이것이다.

규칙은 **고르기만 한다. 만들지 않는다**
---------------------------------------
:meth:`RuleBasedPolicy.decide` 는 ``legal.allowed`` 의 원소를 그대로
돌려준다. 이 파일에는 ``PlayerAction`` 을 만드는 자리가 **없다** —
있으면 정책이 "허가받지 않은 수" 를 떠올릴 수 있고, 그때 거절은
:class:`~agent.runner.DuelRunner` 의 몫으로 미뤄진다. 떠올릴 수 없게
만드는 것이 거절하는 것보다 낫다.

점수는 **지어낸 숫자가 아니다**
-------------------------------
가중치를 아무 값이나 쓰면 "왜 100 인가" 에 답할 수 없고, 낮은 순위의
규칙이 높은 순위의 규칙을 뒤집는 일이 조용히 생긴다. 그래서 세 상수는
**실제 카드 14,127 장을 세어서** 정했다 (§ :data:`ATK_WEIGHT`).

    실측: 서로 다른 ATK 값 82 개, **최소 간격 10**. ATK · DEF 최대 5000.

그래서 ``ATK_WEIGHT = 1000`` 이면 ATK 한 칸(10)의 값이 10,000 이고,
DEF 가 아무리 커도 5,000 이다 — **수비력이 공격력 한 칸을 넘을 수
없다.** 이 부등식은 시험이 지킨다.

모르는 것을 숫자로 바꾸지 않는다
--------------------------------
공격력이 ``?`` 인 몬스터가 56 장 있다. 그것을 0 으로 읽으면 가장 약한
카드가 되고, 9999 로 읽으면 가장 강한 카드가 된다 — 둘 다 거짓이다.
그래서 :class:`HigherAttackFirst` 는 **판단을 포기한다** (``None``).
포기는 0 점이 아니다. 0 점은 "재어 봤더니 그렇다" 이고 포기는 "재지
못했다" 이며, 어느 규칙이 포기했는지는 :class:`Judgement` 에 남는다.
``UNKNOWN`` 을 허가로 바꾸지 않는 엔진의 규칙과 같은 자리다.

여기서 하지 않는 것 (Phase 3-B §2)
----------------------------------
탐색 · 시뮬레이션 · 학습 · 신경망 · MCTS · self-play 가 없다. 판을
**복제하지 않고** ``apply`` 를 **불러 보지 않는다** — 한 수도 내다보지
않고 지금 보이는 것만으로 고른다. 이 파일이 ``Duel`` 도 ``GameState``
도 ``random`` 도 들이지 않는 것을 시험이 AST 로 지킨다.

그래서 이것은 **baseline 이다.** 더 나은 AI 가 생겼을 때 "무엇보다
나은가" 에 답할 대상이지, 잘 두는 AI 가 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import LegalActions
from engine.game_state_view import CardDefinitionView, GameStateView


class HeuristicError(RuntimeError):
    """규칙 기반 정책을 잘못 조립했을 때."""


# ======================================================================
# 가중치 — 실측에서 나온 값이다
# ======================================================================

#: 실측된 **공격력 한 칸**. 실제 카드 14,127 장에서 서로 다른 ATK 값은
#: 82 개이고 그 사이의 최소 간격이 이것이다. 수비력 쪽도 같다.
#:
#: 이 값이 중요한 이유는 하나다 — 공격력이 **한 칸** 다른 두 카드를
#: 수비력이 뒤집을 수 없어야 한다. 시험이 실제 카드에서 다시 재서 지킨다.
MIN_STAT_GAP: int = 10

#: 공격력 1 점의 값. ``MIN_STAT_GAP`` 만큼 센 카드는 10,000 점어치이고,
#: 수비력이 낼 수 있는 최대(5,000)보다 크다 — 그래서 수비력은 공격력을
#: 뒤집지 못한다.
ATK_WEIGHT: int = 1_000

#: 수비력 1 점의 값. 공격력이 **같을 때만** 갈라야 하므로 1 이다.
DEF_WEIGHT: int = 1

#: 실측된 공격력 · 수비력의 최댓값 (``?`` 는 제외). 가중치 설계의 상한이다.
MAX_PRINTED_ATK: int = 5_000
MAX_PRINTED_DEFENSE: int = 5_000

#: 판에 무언가를 두는 행위의 값. ``ATK`` · ``DEF`` 가 낼 수 있는 최대
#: 합(5,005,000)보다 커야 한다 — **아무리 약한 몬스터라도 소환하는 것이
#: 턴을 넘기는 것보다 앞선다.** 이 부등식은 시험이 지킨다.
BOARD_PRESENCE: int = 10_000_000


# ======================================================================
# 하나의 고려 — "이 후보를 어떻게 보는가"
# ======================================================================


@dataclass(frozen=True, slots=True)
class Appraisal:
    """
    한 규칙이 한 후보에게 준 **점수와 그 이유**.

    ``reason`` 이 비면 만들지 않는다. 이유 없는 점수는 나중에 왜 그렇게
    두었는지 되짚을 수 없고, 되짚을 수 없는 판단은 고칠 수도 없다.
    """

    score: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.score, int) or isinstance(self.score, bool):
            raise HeuristicError(f"점수는 정수입니다: {self.score!r}")
        if not self.reason.strip():
            raise HeuristicError("점수에는 이유가 있어야 합니다.")


@runtime_checkable
class Consideration(Protocol):
    """
    후보 하나를 보고 점수를 내는 **명시적인 규칙**.

    판단할 수 없으면 ``None`` 을 돌려준다 — 0 점이 아니다.
    """

    name: str
    basis: str
    """**왜 이 규칙이 정당한가.** 룰북의 문장이거나 실측이다."""

    def appraise(
        self, view: GameStateView, action: PlayerAction
    ) -> "Appraisal | None":
        ...  # pragma: no cover - 프로토콜


def _definition(
    view: GameStateView, action: PlayerAction
) -> "CardDefinitionView | None":
    """
    행위가 가리키는 카드의 정의. **관측을 통해서만** 본다.

    저장소를 들지 않는다 — 들면 상대의 뒷면 카드도 조회할 수 있게 되고,
    ``GameStateView`` 가 숨긴 것이 뒷문으로 새어 나온다.
    """
    if action.source is None:
        return None
    card = view.find(action.source)
    return card.definition if card is not None else None


class SummonBeforeEndingThePhase:
    """
    **소환할 수 있으면 턴을 넘기기보다 소환한다.**

    근거는 룰북이 정한 소환권의 생김새다 — 일반 소환은 **턴에 한 번**
    이고, 쓰지 않은 소환권은 턴이 끝나면 **사라진다.** 즉 턴을 넘기는
    것은 소환권을 버리는 것이다.

    "어느 몬스터인가" 는 여기서 보지 않는다. 그것은 다음 규칙의 일이다.
    """

    __slots__ = ("name", "basis")

    #: 이 규칙이 값을 주는 행위들. **``legal_actions`` 에 실제로 나타나는
    #: 것만** 적는다 — 나타나지 않는 행위에 점수를 매기면 시험할 수 없는
    #: 코드가 되고, 그것은 규칙이 아니라 희망이다 (측정: Phase 3-B §4).
    BOARD_KINDS = frozenset({PlayerActionKind.NORMAL_SUMMON})

    def __init__(self) -> None:
        self.name = "summon-before-ending"
        self.basis = "룰북: 일반 소환은 턴에 한 번이고 쓰지 않으면 사라진다"

    def appraise(
        self, view: GameStateView, action: PlayerAction
    ) -> "Appraisal | None":
        if action.kind not in self.BOARD_KINDS:
            return None
        return Appraisal(
            BOARD_PRESENCE, f"{action.kind.value}: 소환권을 버리지 않는다"
        )


class HigherAttackFirst:
    """
    **공격력이 높은 쪽을 먼저 소환한다.**

    근거는 룰북의 전투 규칙이다 — 공격력이 높은 몬스터가 낮은 몬스터를
    파괴한다. 그래서 같은 소환권이면 더 센 쪽을 쓰는 것이 낫다.

    공격력이 ``?`` 면 **판단하지 않는다.** 실측 56 장이 그렇고, 그것을
    0 이나 큰 수로 읽으면 둘 다 거짓이 된다.
    """

    __slots__ = ("name", "basis")

    def __init__(self) -> None:
        self.name = "higher-attack-first"
        self.basis = "룰북: 전투에서 공격력이 높은 쪽이 낮은 쪽을 파괴한다"

    def appraise(
        self, view: GameStateView, action: PlayerAction
    ) -> "Appraisal | None":
        definition = _definition(view, action)
        if definition is None or not definition.is_monster:
            return None
        if definition.atk_is_question:
            # **여기가 핵심이다.** 모르는 공격력을 숫자로 바꾸지 않는다.
            return None
        if not definition.has_atk:
            return None
        return Appraisal(
            definition.atk * ATK_WEIGHT, f"공격력 {definition.atk}"
        )


class HigherDefenceBreaksTheTie:
    """
    **공격력이 같으면 수비력이 높은 쪽.**

    근거는 룰북의 전투 규칙 나머지 절반이다 — 수비 표시 몬스터는 수비력
    으로 싸운다. 가중치가 :data:`DEF_WEIGHT` 인 이유는 이것이 **갈림용**
    이기 때문이다: 수비력이 공격력 한 칸을 뒤집으면 규칙의 순위가 뒤집힌다.
    """

    __slots__ = ("name", "basis")

    def __init__(self) -> None:
        self.name = "higher-defence-breaks-tie"
        self.basis = "룰북: 수비 표시 몬스터는 수비력으로 싸운다"

    def appraise(
        self, view: GameStateView, action: PlayerAction
    ) -> "Appraisal | None":
        definition = _definition(view, action)
        if definition is None or not definition.is_monster:
            return None
        if definition.defense_is_question or not definition.has_defense:
            return None
        return Appraisal(
            definition.defense * DEF_WEIGHT, f"수비력 {definition.defense}"
        )


class EndThePhaseAsLastResort:
    """
    **할 일이 없으면 턴을 넘긴다.** 0 점이다.

    이 규칙이 있는 이유는 점수를 주기 위해서가 아니라, 턴을 넘기는 것이
    **아무 규칙도 보지 않은 행위로 남지 않게** 하기 위해서다. 0 점은
    "재어 봤더니 0" 이고, 규칙이 아무것도 말하지 않은 것과 다르다.
    """

    __slots__ = ("name", "basis")

    LAST_RESORT_KINDS = frozenset(
        {PlayerActionKind.END_PHASE, PlayerActionKind.PASS}
    )

    def __init__(self) -> None:
        self.name = "end-phase-as-last-resort"
        self.basis = "다른 규칙이 값을 주지 못한 경우에만 남는 선택이다"

    def appraise(
        self, view: GameStateView, action: PlayerAction
    ) -> "Appraisal | None":
        if action.kind not in self.LAST_RESORT_KINDS:
            return None
        return Appraisal(0, f"{action.kind.value}: 더 할 것이 없다")


#: 기본 규칙 묶음. **순서가 뜻을 갖지 않는다** — 점수는 더해지고, 순위는
#: 가중치가 정한다. 순서에 뜻을 두면 가중치와 순서 둘 중 무엇이 이기는지
#: 읽는 사람이 알 수 없게 된다.
DEFAULT_CONSIDERATIONS: "tuple[Consideration, ...]" = (
    SummonBeforeEndingThePhase(),
    HigherAttackFirst(),
    HigherDefenceBreaksTheTie(),
    EndThePhaseAsLastResort(),
)


# ======================================================================
# 판단의 기록
# ======================================================================


@dataclass(frozen=True, slots=True)
class Evaluation:
    """후보 하나에 대한 **모든 규칙의 말**과 그 합."""

    action: PlayerAction
    total: int
    appraisals: tuple[tuple[str, Appraisal], ...] = ()
    abstained: tuple[str, ...] = ()
    """**판단하지 않은** 규칙들. 0 점을 준 규칙과 섞지 않는다."""

    @property
    def judged(self) -> bool:
        """규칙 하나라도 값을 주었는가."""
        return bool(self.appraisals)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        bits = ", ".join(f"{n}={a.score}" for n, a in self.appraisals) or "없음"
        held = f" · 보류 {len(self.abstained)}" if self.abstained else ""
        return f"{self.action} → {self.total} ({bits}){held}"


@dataclass(frozen=True, slots=True)
class Judgement:
    """
    **왜 그 수를 골랐는가.** 한 결정 지점의 기록 전체.

    고른 것만 남기지 않는다 — 고르지 않은 후보의 점수가 없으면 "왜 저것이
    아니었는가" 에 답할 수 없다.
    """

    seat: int
    evaluations: tuple[Evaluation, ...]
    chosen: "PlayerAction | None"
    reason: str

    @property
    def nothing_was_judged(self) -> bool:
        """어떤 규칙도 어떤 후보에게도 값을 주지 못했는가."""
        return bool(self.evaluations) and not any(
            e.judged for e in self.evaluations
        )

    def of(self, action: PlayerAction) -> "Evaluation | None":
        for evaluation in self.evaluations:
            if evaluation.action == action:
                return evaluation
        return None

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [f"P{self.seat}: {self.reason}"]
        for evaluation in sorted(
            self.evaluations, key=lambda e: -e.total
        ):
            mark = "→" if evaluation.action == self.chosen else " "
            lines.append(f" {mark} {evaluation.describe_ko()}")
        return "\n".join(lines)


# ======================================================================
# 정책
# ======================================================================


@dataclass
class RuleBasedPolicy:
    """
    **명시적인 규칙으로 고르는 정책.** 난수도 탐색도 없다.

    같은 관측과 같은 후보 목록이면 **언제나 같은 수**를 고른다. 점수가
    같으면 :meth:`~engine.action.PlayerAction.canonical_state` 가 작은
    쪽을 고른다 — 목록의 순서에 기대지 않는다. 목록 순서는 엔진이 패를
    어떻게 훑는지에 달린 구현 세부이고, 그것이 바뀌면 AI 의 수가 바뀌는
    것은 설명할 수 없는 일이다.
    """

    considerations: "tuple[Consideration, ...]" = DEFAULT_CONSIDERATIONS
    name: str = "rule-based"
    judgements: list[Judgement] = field(default_factory=list)
    """지나온 결정의 기록. **AI 를 읽을 수 있게 하는 것**이 목적이다."""

    def __post_init__(self) -> None:
        self.considerations = tuple(self.considerations)
        if not self.considerations:
            raise HeuristicError(
                "규칙이 없는 규칙 기반 정책은 규칙 기반이 아닙니다."
            )
        seen: set[str] = set()
        for consideration in self.considerations:
            # ``runtime_checkable`` 은 **있는지**만 본다 (``hasattr``).
            # 이름과 근거가 문자열인지는 따로 묻는다.
            for attribute in ("name", "basis"):
                if not isinstance(getattr(consideration, attribute, None), str):
                    raise HeuristicError(
                        f"{type(consideration).__name__}: {attribute} 가 없습니다."
                    )
            if not isinstance(consideration, Consideration):
                raise HeuristicError(
                    f"{type(consideration).__name__}: 규칙의 모양이 아닙니다 "
                    "— name · basis · appraise 가 필요합니다."
                )
            if not consideration.basis.strip():
                raise HeuristicError(
                    f"{consideration.name}: 근거 없는 규칙은 두지 않습니다."
                )
            if consideration.name in seen:
                raise HeuristicError(f"규칙 이름이 겹칩니다: {consideration.name}")
            seen.add(consideration.name)

    # ------------------------------------------------------------------
    def evaluate(
        self, view: GameStateView, legal: LegalActions
    ) -> tuple[Evaluation, ...]:
        """후보마다 모든 규칙을 물어본다. **판을 바꾸지 않는다.**"""
        evaluations: list[Evaluation] = []
        for action in legal.allowed:
            scored: list[tuple[str, Appraisal]] = []
            held: list[str] = []
            for consideration in self.considerations:
                appraisal = consideration.appraise(view, action)
                if appraisal is None:
                    held.append(consideration.name)
                    continue
                scored.append((consideration.name, appraisal))
            evaluations.append(
                Evaluation(
                    action=action,
                    total=sum(a.score for _, a in scored),
                    appraisals=tuple(scored),
                    abstained=tuple(held),
                )
            )
        return tuple(evaluations)

    def decide(
        self, view: GameStateView, legal: LegalActions
    ) -> "PlayerAction | None":
        if not legal.allowed:
            self.judgements.append(
                Judgement(legal.seat, (), None, "고를 것이 없습니다.")
            )
            return None

        evaluations = self.evaluate(view, legal)
        best = min(
            evaluations,
            key=lambda e: (-e.total, e.action.canonical_state()),
        )
        if best.judged:
            reason = "; ".join(a.reason for _, a in best.appraisals)
        else:
            # 어떤 규칙도 이 후보를 보지 못했다. 고르기는 하지만 **아는
            # 척하지 않는다** — 기록에 그렇게 남는다.
            reason = "아무 규칙도 판단하지 않았습니다 — 규칙이 모자랍니다."
        self.judgements.append(
            Judgement(legal.seat, evaluations, best.action, reason)
        )
        return best.action

    # ------------------------------------------------------------------
    @property
    def last_judgement(self) -> "Judgement | None":
        return self.judgements[-1] if self.judgements else None

    def firing_counts(self) -> dict[str, int]:
        """
        규칙별로 **몇 번 값을 주었는가.**

        한 번도 값을 주지 못한 규칙은 **시험할 수 없는 규칙**이고, 그런
        것은 두지 않는다. 이 셈이 그것을 드러낸다.
        """
        counts = {c.name: 0 for c in self.considerations}
        for judgement in self.judgements:
            for evaluation in judgement.evaluations:
                for name, _ in evaluation.appraisals:
                    counts[name] += 1
        return counts

    def abstention_counts(self) -> dict[str, int]:
        """규칙별로 **몇 번 판단을 포기했는가.**"""
        counts = {c.name: 0 for c in self.considerations}
        for judgement in self.judgements:
            for evaluation in judgement.evaluations:
                for name in evaluation.abstained:
                    counts[name] += 1
        return counts

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<{self.name} 규칙 {len(self.considerations)}개 판단 {len(self.judgements)}회>"


def rule_based_policy(
    *, name: str = "rule-based", considerations=None
) -> RuleBasedPolicy:
    """기본 규칙 묶음으로 정책 하나."""
    return RuleBasedPolicy(
        considerations=DEFAULT_CONSIDERATIONS
        if considerations is None
        else considerations,
        name=name,
    )


__all__ = [
    "HeuristicError",
    "Appraisal",
    "Consideration",
    "Evaluation",
    "Judgement",
    "RuleBasedPolicy",
    "rule_based_policy",
    "DEFAULT_CONSIDERATIONS",
    "SummonBeforeEndingThePhase",
    "HigherAttackFirst",
    "HigherDefenceBreaksTheTie",
    "EndThePhaseAsLastResort",
    "MIN_STAT_GAP",
    "ATK_WEIGHT",
    "DEF_WEIGHT",
    "BOARD_PRESENCE",
    "MAX_PRINTED_ATK",
    "MAX_PRINTED_DEFENSE",
]
