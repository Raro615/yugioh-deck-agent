"""
BoundedSearch — **적어 둔 경로를 따라가지 않고** 목표에 닿는 길을 찾는다
(Phase 6-AH).

    목표: 자신 필드에 그 카드가 앞면으로 있다 (실제 판에서 센다)
        ↓
    Duel.legal_actions        ← 후보는 **엔진이** 만든다
        ↓  후보마다
    Simulator.fork(selector=각본)   ← 사본에 진짜 엔진을 적용
        ↓  해결 중 물음마다
    ScriptedChoice            ← 그 자리의 허용 후보 안에서 다른 답을 해 본다
        ↓
    목표 판정 → 경로 기록 → **새 초기 상태에서 재생**

고정 정책과 무엇이 다른가
-------------------------
``deck.combo_policy`` 의 :class:`~deck.combo_policy.VerificationLinePolicy`
는 **사람이 적어 둔 네 단계**를 순서대로 찾아 고른다. 적혀 있지 않은 판에서는
아무것도 고르지 못한다.

이 모듈에는 그 목록이 없다. 고르는 기준은 두 개뿐이다 —

1. **엔진이 그 자리에서 허가했는가** (``legal.allowed`` 의 원소인가),
2. **그 뒤가 목표인가** (실제 ``GameState`` 에서 센다).

그래서 이 모듈은 ``ORCUST_GIRSU_LINE`` 도 ``ORCUST_GIRSU_TOKEN_LINE`` 도
읽지 않고, "기르수 다음에는 이 효과" 같은 분기도 갖지 않는다. 카드 ID 가
쓰이는 자리는 **목표 지정 하나**다 (:class:`FieldGoal.card_id`).

🔴 이것이 **무엇이 아닌가**
---------------------------
🔴 **최선 전개가 아니다.** 평가 함수가 없다. 찾는 것은 "목표에 닿는 한
경로" 이고, 더 센 전개도 더 나은 집도 주장하지 않는다.

🔴 **승률도 전개 강도도 재지 않는다.** 노드를 고르는 순서는
``canonical_state`` 의 결정론적 순서이고, 그것은 좋음의 척도가 아니라
**재현의 좌표**다.

🔴 **범용 AI 가 아니다.** 지원하는 범위는 선공 · 상대의 능동적 방해가 없는
명시적 분석 조건 · **이 턴 안**이고, 엔진이 지금 지원하는 행동과 효과뿐이다.

🔴 **경로를 못 찾은 것이 "실제 듀얼에서 불가능하다" 를 뜻하지 않는다.**
:class:`Termination` 이 그 둘을 가른다 — 예산 초과 · 이번 범위에서 미발견 ·
실행 오류가 전부 다른 사실이다.

규칙 판정을 다시 만들지 않는다
------------------------------
행동의 적법성은 ``Duel.legal_actions`` · ``Duel.apply`` 가 판정하고, 해결 중
선택의 허용 후보는 그 자리의 ``offer.permitted`` 가 낸다. 이 모듈에는
``PlayerAction`` 을 **만드는 코드가 없고**, 후보 목록 밖을 고르는 길도 없다
(:class:`~agent.choice.ScriptedChoice` 가 거절한다).

상대는 **명시적인 정책**이다
----------------------------
"상대의 방해가 없다" 를 조용히 가정하지 않는다. 상대 자리가 오면
:data:`NO_INTERFERENCE` 가 **패스를 고른다** — 그 자리에 다른 수가 있었다면
:attr:`SearchOutcome.opponent_declined` 에 적는다. 우선권 · 패스 · 유발 처리
기회를 **생략하지 않는다**: 전부 ``legal_actions`` 를 지나 ``apply`` 로
들어간다.

🔴 **상대 자리에 고를 것이 남으면 그 노드에서 멈춘다.** 상대의 선택을
탐색하지 않는 것이 이번 범위이고, 그 사실을
:attr:`SearchOutcome.opponent_blocked` 에 적는다 — 조용히 아무 수나
골라 주지 않는다.

이 턴을 벗어나지 않는다
-----------------------
``end_phase`` 는 **전개하지 않는다** (:data:`OUT_OF_TURN_SCOPE`). 그것이 이
턴을 끝내는 유일한 수이므로, 이 모듈이 그것을 고르지 않는 한 탐색은 구조적
으로 이 턴 안에 머문다. 그 사실을 범위로 적고, 조용히 빼지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel
from engine.vocabulary import Zone

from agent.choice import ChoiceAsk, FirstPermittedChoice, ScriptedChoice
from agent.simulation import Simulator


class BoundedSearchError(RuntimeError):
    """탐색기를 잘못 조립하거나 잘못 썼을 때."""


#: 자신 필드로 세는 존 — 메인 몬스터 존과 엑스트라 몬스터 존은 **다른 존**이다
#: (``Zone.EMZONE`` 의 설명). 링크 몬스터는 후자에 놓이므로 둘을 함께 본다.
FIELD_ZONES: tuple[Zone, ...] = (Zone.MZONE, Zone.EMZONE)

#: 기본 예산. 실측으로 정한 값이다 (보고서 §5) — 두 실제 입력이 이 안에서
#: 목표에 닿는다. **크게 잡아 두면 못 찾았다는 보고가 늦게 나온다.**
DEFAULT_MAX_DEPTH: int = 8
DEFAULT_MAX_NODES: int = 300
DEFAULT_MAX_SECONDS: float = 300.0
#: 한 행동에서 만들 **해결 중 선택 분기**의 상한.
DEFAULT_MAX_CHOICE_BRANCHES: int = 8

#: 필수 걸음(패스 · 드로우)을 지나가는 반복의 안전장치. 무한 반복을 막는
#: 것뿐이고, 여기 걸리면 그 사실을 노드에 적는다.
SETTLE_GUARD: int = 24

#: ``end_phase`` 를 전개하지 않는 이유.
OUT_OF_TURN_SCOPE: str = (
    "end_phase: 이 턴을 벗어나는 수이므로 이번 범위에서 전개하지 않았습니다"
    " — 다음 턴의 자원으로 목표에 닿는 경로는 찾지 않습니다."
)

#: 상대 자리의 정책 이름. **값 하나뿐인 정책**이고, 그래서 이름만으로 충분하다.
NO_INTERFERENCE: str = "no-interference (상대는 언제나 패스한다)"

#: 사본이 해결 중 선택을 받지 못할 때 적는 말.
CHOICE_BRANCHING_UNAVAILABLE: str = (
    "해결 중 선택을 분기하지 못했습니다 — 이 듀얼의 고르는 사람이 사본용"
    " 선택 정책을 받지 않습니다. 그 경로의 선택은 사본 안에서 거절되므로"
    " 목표에 닿지 못한 것이 '규칙상 불가능' 을 뜻하지 않습니다."
)


class Termination(str, Enum):
    """
    탐색이 **어떻게 끝났는가.** 네 가지를 한 칸으로 뭉치지 않는다.

    🔴 :attr:`EXHAUSTED` 는 "이 패로는 불가능하다" 가 아니다 — **지정된
    탐색 범위 안에서** 못 찾았다는 뜻이고, 그 범위는
    :class:`SearchBudget` 과 이 모듈의 지원 범위가 정한다.
    """

    GOAL_REACHED = "goal_reached"
    """목표에 닿는 경로를 찾았다."""
    EXHAUSTED = "exhausted"
    """지정된 범위를 모두 펼쳤고 **그 안에** 목표가 없었다."""
    BUDGET_EXCEEDED = "budget_exceeded"
    """예산에 걸려 멈췄다. 🔴 **못 찾았다는 뜻이 아니다.**"""
    ERROR = "error"
    """실행 중 예외가 났다. 숨기지 않는다."""

    @property
    def found(self) -> bool:
        return self is Termination.GOAL_REACHED


@dataclass(frozen=True, slots=True)
class SearchBudget:
    """
    **어디까지 해 볼 것인가.** 네 칸 모두 보고에 적는다.

    :attr:`max_seconds` 는 **안전장치**다 — 기계가 느리면 먼저 걸린다.
    그래서 같은 입력에서 같은 결과를 요구할 때는 이 칸을 넉넉히 두고
    노드·깊이로 가둔다 (같은 노드·깊이 예산이면 결과가 재현된다).
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_seconds: float = DEFAULT_MAX_SECONDS
    max_choice_branches: int = DEFAULT_MAX_CHOICE_BRANCHES
    dedup: bool = True
    """
    중복 제거를 쓸 것인가 (:func:`node_key` 의 기준으로).

    🔴 **끄면 같은 판을 여러 번 펼친다.** 기준이 안전한지 재는 자리가
    있어야 하므로 칸으로 둔다 — 기본은 켜짐이다.
    """

    def __post_init__(self) -> None:
        for name, value in (
            ("max_depth", self.max_depth),
            ("max_nodes", self.max_nodes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise BoundedSearchError(f"{name} 는 1 이상의 정수입니다: {value!r}")
        if isinstance(self.max_choice_branches, bool) or not isinstance(
            self.max_choice_branches, int
        ) or self.max_choice_branches < 0:
            raise BoundedSearchError(
                "max_choice_branches 는 0 이상의 정수입니다 "
                f"(0 이면 해결 중 선택을 분기하지 않는다): "
                f"{self.max_choice_branches!r}"
            )
        if not isinstance(self.max_seconds, (int, float)) or self.max_seconds <= 0:
            raise BoundedSearchError(
                f"max_seconds 는 0 보다 큰 수입니다: {self.max_seconds!r}"
            )

    def describe_ko(self) -> str:
        return (
            f"깊이 {self.max_depth} · 노드 {self.max_nodes} · "
            f"{self.max_seconds:g}초 · 선택 분기 {self.max_choice_branches}"
            + (" · 중복 제거 켜짐" if self.dedup else " · 중복 제거 꺼짐")
        )


@dataclass(frozen=True, slots=True)
class GoalVerdict:
    """
    목표 판정 하나. **셋을 따로 적는다.**

    :attr:`present` 와 :attr:`settled` 를 가르는 이유 — 체인 도중에 카드가
    필드에 올라와 있는 자리는 목표가 아니다. 그 자리에서 멈추면 남은 필수
    처리가 생략되고, 그 뒤에 카드가 떠날 수도 있다.
    """

    reached: bool
    present: bool
    settled: bool
    reason: str


@dataclass(frozen=True, slots=True)
class FieldGoal:
    """
    **자신 필드에 그 카드가 앞면으로 있고, 판이 정리되었는가.**

    🔴 **실제 ``GameState`` 에서 센다.** 기록이나 걸음 수로 추정하지 않는다.

    🔴 **카드 ID 는 목표 지정에만 쓴다.** 이 값으로 행동을 고르는 분기는
    이 모듈에 없다 — 고르는 기준은 "엔진이 허가했는가" 하나다.
    """

    card_id: int
    seat: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.card_id, bool) or not isinstance(self.card_id, int):
            raise BoundedSearchError(f"카드 ID 는 정수입니다: {self.card_id!r}")
        if self.seat not in (0, 1):
            raise BoundedSearchError(f"자리는 0 또는 1 입니다: {self.seat!r}")

    def describe_ko(self) -> str:
        return (
            f"자신(P{self.seat}) 필드에 [{self.card_id}] 가 앞면으로 있고 "
            "진행 중인 체인과 필수 처리가 정리되었다"
        )

    def judge(self, duel: Duel, legal=None) -> GoalVerdict:
        """
        ``legal`` 을 주면 그 자리의 후보 목록을 **다시 세지 않는다** — 부르는
        쪽이 이미 세어 두었으면 그것을 쓴다 (한 노드에서 두 번 세면 탐색이
        두 배로 느려진다).
        """
        present = any(
            card_id == self.card_id and face_up
            for _zone, card_id, face_up in own_field(duel, self.seat)
        )
        settled, why = _is_settled(duel, self.seat, legal)
        if present and settled:
            reason = f"[{self.card_id}] 가 자신 필드에 있고 판이 정리되었습니다."
        elif present:
            reason = f"[{self.card_id}] 는 있지만 {why}"
        else:
            reason = f"[{self.card_id}] 가 자신 필드에 없습니다."
        return GoalVerdict(
            reached=present and settled,
            present=present,
            settled=settled,
            reason=reason,
        )


def _chooser_of(duel: Duel):
    """
    그 듀얼의 **해결 시점에 고르는 사람**. 없으면 ``None``.

    :meth:`Simulator._forked_chooser` 가 읽는 자리와 **같은 자리**다 —
    사본이 그것을 받았는지 확인하려면 같은 길로 봐야 한다.
    """
    resolver = getattr(duel, "_resolver", None)
    executor = getattr(resolver, "executor", None)
    return getattr(executor, "chooser", None)


def own_field(duel: Duel, seat: int) -> "tuple[tuple[str, int, bool], ...]":
    """
    그 자리의 **필드 몬스터**를 ``(존, 카드 ID, 앞면인가)`` 로.

    🔴 **자기 자리만 센다.** 상대의 필드는 목표 판정에 쓰지 않는다 — 이
    모듈의 목표는 자신 필드의 모양이다.
    """
    rows: list[tuple[str, int, bool]] = []
    for zone in FIELD_ZONES:
        for card in duel.state.player(seat).zone(zone).cards():
            rows.append((zone.value, card.card_id, card.is_faceup))
    return tuple(rows)


def _is_settled(duel: Duel, seat: int, legal=None) -> "tuple[bool, str]":
    """
    **진행 중인 체인과 필수 처리가 정리되었는가.**

    다섯 가지를 함께 본다 — 듀얼이 끝나지 않았는가 · 체인이 비었는가 ·
    응답 창이 닫혔는가 · 지금 고를 사람이 자신인가 · **엔진이 그 자리에서
    ``end_phase`` 를 허가하는가.**

    🔴 **마지막 조건이 필요한 이유 — 실측한 결함이다.** 앞의 넷만 보면
    일반 소환 **직후**가 "정리된 자리" 로 읽혔다: 체인은 비어 있고 응답
    창도 ``none`` 이지만, 그 자리에는 **유발 처리 기회**가 열려 있어
    엔진이 ``end_phase`` 를 *"유발 처리 기회가 열려 있습니다 — 판이 열린
    상태가 아니므로 그 기회를 처리한 뒤에 진행합니다"* 로 보류했다. 그
    자리를 목표로 읽으면 **남은 필수 처리를 생략**하게 된다.

    그래서 "판이 열렸는가" 를 **엔진의 답으로** 묻는다 — 이 계층이 그
    조건을 다시 짜지 않는다.

    🔴 **듀얼이 끝난 자리는 정리된 자리가 아니다.** 그 뒤에 할 수 있는
    것이 없으므로 목표로 읽으면 안 된다.
    """
    if duel.is_over:
        return False, "듀얼이 끝났습니다."
    if not duel.chain.is_empty:
        return False, f"체인이 {len(duel.chain)}링크 진행 중입니다."
    if duel.priority.is_open:
        return False, f"응답 기회가 열려 있습니다 ({duel.priority.window.value})."
    if duel.to_act != seat:
        return False, f"지금 고를 사람이 P{duel.to_act} 입니다."
    here = duel.legal_actions(seat) if legal is None else legal
    if not any(
        action.kind is PlayerActionKind.END_PHASE for action in here.allowed
    ):
        return False, (
            "아직 지나야 하는 처리가 남아 있습니다 — 엔진이 그 자리에서 "
            "end_phase 를 허가하지 않았습니다 (판이 열린 자리가 아닙니다)."
        )
    return True, ""


# ======================================================================
# 기록
# ======================================================================
@dataclass(frozen=True, slots=True)
class PathStep:
    """
    경로의 한 걸음 — **행동 하나와 그 걸음에서 한 해결 중 선택 전부.**

    :attr:`action_key` 는 ``PlayerAction.canonical_state()`` 다. 재생은 이
    값으로 **그 자리의 허용 후보를 다시 찾는다** — 객체를 들고 다니면 새
    초기 상태에서 그것이 허가된 수인지 확인하지 않게 된다.
    """

    order: int
    kind: str
    action_key: tuple
    choices: "tuple[ChoiceAsk, ...]" = ()
    forced: tuple[str, ...] = ()
    """이 걸음 뒤에 지나간 **필수 걸음**들 (패스 · 드로우). 생략하지 않는다."""
    reason: str = ""

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [f"{self.order}. {self.kind} {self.action_key}"]
        if self.reason:
            lines.append(f"   → {self.reason}")
        for ask in self.choices:
            lines.append(f"   선택 {ask.describe_ko()}")
        for note in self.forced:
            lines.append(f"   필수 {note}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """
    탐색 한 번의 결과 **전부**. 성공만이 아니라 **왜 끝났는지**를 들고 있다.

    🔴 **미지원과 종료 사유를 따로 적는다.** 예산이 남았는데 못 찾은 것과,
    그 자리에 지원하지 않아 후보가 되지 못한 수가 있는 것은 다른 사실이다.
    """

    goal: FieldGoal
    termination: Termination
    budget: SearchBudget
    budget_hit: tuple[str, ...] = ()
    path: "tuple[PathStep, ...]" = ()
    nodes_expanded: int = 0
    deepest: int = 0
    choice_branches: int = 0
    """해결 중 선택의 **대기에 넣은 대안 각본** 수 (상한이 세는 것과 같다)."""
    choice_plans: int = 0
    """그중 **실제로 돌린** 대안 각본 수. 🔴 위 수와 섞지 않는다."""
    choice_offers_truncated: int = 0
    """**확인하지 않은 대안이 남은 물음**의 수. 0 이 아니면 선택을 생략했다."""
    deduped: int = 0
    revisited: int = 0
    """같은 상태에 **더 얕게** 다시 닿아 다시 펼친 횟수 (보완 A)."""
    stale: int = 0
    """대기 중에 **더 얕은 길이 생겨** 펼치지 않은 노드 수 (보완 A)."""
    elapsed_seconds: float = 0.0
    unsupported: tuple[str, ...] = ()
    """그 자리에서 **지원하지 않아 후보가 되지 못한** 것들. 종료 사유와 별개다."""
    out_of_scope: tuple[str, ...] = ()
    """이번 범위에서 **일부러 펼치지 않은** 분기 (``end_phase`` · 잘린 선택 분기)."""
    opponent_declined: tuple[str, ...] = ()
    """상대 자리에 다른 수가 있었지만 **무방해 정책이 패스한** 자리들."""
    opponent_blocked: tuple[str, ...] = ()
    """상대 자리에 고를 것이 남아 **더 펼치지 않은** 노드들."""
    errors: tuple[str, ...] = ()
    final_field: "tuple[tuple[str, int, bool], ...]" = ()
    final_state_hash: str = ""
    goal_reason: str = ""

    @property
    def reached(self) -> bool:
        return self.termination.found

    @property
    def action_count(self) -> int:
        return len(self.path)

    @property
    def choice_count(self) -> int:
        return sum(len(step.choices) for step in self.path)

    @property
    def skipped_choices(self) -> bool:
        """
        **확인하지 않은 선택 대안이 남았는가** (보완 B).

        🔴 목표에 닿았어도 참일 수 있다 — 그러면 "이 경로를 찾았다" 는
        맞지만 "선택을 다 봤다" 는 틀리다. 두 사실을 함께 적는다.
        """
        return self.choice_offers_truncated > 0

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [
            f"제한 탐색 — 목표: {self.goal.describe_ko()}",
            f"  종료: {self.termination.value}"
            + (f" ({' · '.join(self.budget_hit)})" if self.budget_hit else ""),
            f"  예산: {self.budget.describe_ko()}",
            f"  펼친 노드 {self.nodes_expanded} · 최대 깊이 {self.deepest}"
            f" · 선택 분기 대기 {self.choice_branches}/실행 {self.choice_plans}"
            f" · 중복 제거 {self.deduped} · 얕게 재방문 {self.revisited}"
            f" · 밀려난 노드 {self.stale}"
            f" · 확인 못 한 선택 물음 {self.choice_offers_truncated}"
            f" · {self.elapsed_seconds:.2f}초",
            f"  목표 판정: {self.goal_reason}",
        ]
        for step in self.path:
            lines.append(step.describe_ko())
        for note in self.out_of_scope:
            lines.append(f"  범위 밖: {note}")
        for note in self.unsupported:
            lines.append(f"  미지원: {note}")
        for note in self.opponent_declined:
            lines.append(f"  상대 정책: {note}")
        for note in self.opponent_blocked:
            lines.append(f"  상대 자리에서 멈춤: {note}")
        for note in self.errors:
            lines.append(f"  🔴 오류: {note}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class RerunResult:
    """
    찾은 경로를 **새 초기 상태에서 다시 실행한** 결과.

    🔴 **재생 실패를 성공으로 바꾸지 않는다.** :attr:`ok` 가 거짓이면
    :attr:`reason` 이 어디서 어긋났는지 말한다.
    """

    ok: bool
    reason: str
    steps: int = 0
    goal_reached: bool = False
    final_field: "tuple[tuple[str, int, bool], ...]" = ()
    final_state_hash: str = ""
    matches_search: bool = False
    """탐색이 남긴 최종 판(해시와 자신 필드)과 **같은가.**"""

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        mark = "성공" if self.ok else "🔴 실패"
        return (
            f"재생 {mark} — 걸음 {self.steps} · 목표 {self.goal_reached}"
            f" · 탐색 결과와 일치 {self.matches_search}\n  {self.reason}"
        )


# ======================================================================
# 중복 제거
# ======================================================================
def node_key(duel: Duel, legal) -> "tuple | None":
    """
    두 노드를 **같은 것으로 볼 수 있는가.** 볼 수 없으면 ``None``.

    들어가는 것
    -----------
    ========================  ==================================================
    ``state.state_hash()``    판의 모양 + **사용 제한** + 턴당 소환 기록 +
                              턴 — ``GameState.canonical_state`` 가 그것들을
                              함께 센다 (Phase 6-AF 가 ``summon_uses`` 를 넣었다)
    ``to_act``                지금 고를 사람
    ``step`` · 응답 창        흐름 위의 자리 — 같은 판이라도 여기가 다르면
                              할 수 있는 일이 다르다
    허용 후보 집합            **엔진이 "지금 무엇을 할 수 있는가" 에 준 답**
    ========================  ==================================================

    🔴 **``state_hash`` 하나로는 모자란다.** 그 값은 체인 · 우선권 · 기록을
    **일부러 빼고** 만든다 (``GameState.canonical_state`` 의 설명) — "같은
    판" 의 뜻을 경로와 무관하게 두려고 그렇게 두었다. 탐색에는 그 빠진 것이
    미래를 바꾸므로, 흐름 위의 자리와 허용 후보를 함께 넣는다.

    🔴 **체인이 진행 중이면 ``None`` 이다.** 체인 도중의 두 자리를 같다고
    볼 안전한 기준이 없으므로 **합치지 않는다** — 중복 제거를 못 하는 것이
    틀린 병합보다 낫다.

    🔴 **기록 전체를 넣지 않는다.** 넣으면 모든 노드가 영원히 달라지고
    중복 제거가 사실상 꺼진다. 대신 **허용 후보 집합**을 넣는다 — 지나간
    사건 중 아직 쓸 수 있는 것이 무엇인지는 그 목록에 이미 나타난다
    (유발 후보가 바로 그렇게 오른다).

    🔴 **미래 동치의 증명이 아니다.** 지금 할 수 있는 일과 사용 제한이 같은
    두 자리를 같다고 보는 **보수적인 기준**이고, 그 한계를 보고서에 적는다.
    """
    if not duel.chain.is_empty:
        return None
    return (
        duel.state.state_hash(),
        duel.to_act,
        duel.step.value,
        duel.priority.window.value,
        frozenset(repr(action.canonical_state()) for action in legal.allowed),
    )


class Admission(str, Enum):
    """
    같은 상태에 다시 닿았을 때 **펼칠 것인가** (Phase 6-AH 보완 A).

    🔴 **깊이 상한이 있으면 "같은 상태" 가 "같은 미래" 가 아니다.** 얕게
    닿은 쪽에는 남은 깊이 예산이 더 많으므로, 그 쪽에서만 닿는 경로가
    있을 수 있다.

    🔴 **최단 경로 탐색이 아니다.** 이 판정이 보장하는 것은 하나뿐이다 —
    **깊이 상한 안의 경로를 "이미 봤다" 는 이유로 잘못 버리지 않는다.**
    더 짧은 경로를 **찾아 준다**는 주장이 아니고, 탐색의 완전성이나
    최적성을 주장하지도 않는다.
    """

    FRESH = "fresh"
    """처음 보는 상태다."""
    SHALLOWER = "shallower"
    """본 상태인데 **더 얕게** 닿았다 — 남은 깊이 예산이 더 많으므로 다시 펼친다."""
    DUPLICATE = "duplicate"
    """
    본 상태이고 **같거나 더 깊게** 닿았다 — 버린다.

    🔴 **왜 안전한가.** 먼저 기록된 깊이 ``d`` 가 이번 깊이 ``d'`` 보다
    작거나 같으면, 남은 예산은 ``max_depth - d >= max_depth - d'`` 다. 즉
    이번 노드에서 예산 안에 닿을 수 있는 것은 그 노드에서도 닿을 수 있다.
    """

    @property
    def opens(self) -> bool:
        """이 판정이 노드를 **펼치게** 하는가."""
        return self is not Admission.DUPLICATE


def admit(seen: dict, key, depth: int) -> Admission:
    """
    그 열쇠를 ``depth`` 에서 받아들일지 정하고, **받으면 기록을 갱신한다.**

    ``key`` 가 ``None`` 이면 (:func:`node_key` 가 안전한 기준을 못 만든
    자리) 언제나 :attr:`Admission.FRESH` 다 — **병합하지 않는다.**
    """
    if key is None:
        return Admission.FRESH
    before = seen.get(key)
    if before is None:
        seen[key] = depth
        return Admission.FRESH
    if depth < before:
        seen[key] = depth
        return Admission.SHALLOWER
    return Admission.DUPLICATE


def superseded(seen: dict, key, depth: int) -> bool:
    """
    대기 중인 노드가 **더 얕은 길에 밀려났는가** (보완 A).

    같은 상태에 더 얕게 닿은 노드가 나중에 생기면, 깊은 쪽을 펼치는 일은
    **그 얕은 쪽이 하는 일의 부분집합**이다 (:attr:`Admission.DUPLICATE`
    의 근거와 같다). 그래서 꺼낼 때 한 번 더 보고 넘긴다 — 같은 기준을
    **넣을 때와 꺼낼 때 모두** 적용해 일관되게 둔다.

    🔴 열쇠가 없으면 밀려날 수 없다 (병합하지 않는 상태다).
    """
    if key is None:
        return False
    before = seen.get(key)
    return before is not None and before < depth


# ======================================================================
# 필수 걸음과 상대 자리
# ======================================================================
@dataclass(frozen=True, slots=True)
class _Settled:
    """필수 걸음을 지난 뒤의 메모들."""

    forced: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    met: tuple[tuple[int, object], ...] = ()


def _settle(duel: Duel, seat: int) -> _Settled:
    """
    **고르는 일이 아닌 걸음들을 지나간다.** 전부 엔진을 지나서.

    두 가지를 지난다 —

    1. **상대 자리** — :data:`NO_INTERFERENCE` 가 패스를 고른다. 다른 수가
       있었으면 적는다. 🔴 패스도 ``legal_actions`` 를 지나 ``apply`` 로
       들어간다 — 손으로 우선권을 돌리지 않는다.
    2. **자기 자리에 패스밖에 없는 걸음** — 고를 것이 하나뿐이면 고르는
       일이 아니다 (``Simulator._settle_forced_passes`` 와 같은 근거).

    🔴 **고를 것이 있으면 즉시 멈춘다.** 그 자리가 진짜 결정 지점이고,
    거기까지가 한 걸음이다.

    🔴 **``Duel.advance()`` 를 부르지 않는다.** 그것을 부르는 production
    자리는 **하나여야 한다** — ``agent/runner.py`` 의 고리뿐이고, 그래야
    ``rule_steps`` 가 생기는 길이 하나로 남는다 (``tests/
    test_duel_advance_rule_step_contract.py::test_22`` 가 그 계약을 센다).

    그리고 이 범위에서는 **부를 일이 없다**: ``advance()`` 가 하는 일은
    드로우 페이즈의 드로우 하나이고, 이 탐색은 ``end_phase`` 를 고르지
    않으므로 (:data:`OUT_OF_TURN_SCOPE`) 턴이 넘어가지 않아
    ``TurnStep.DRAW_PENDING`` 에 닿지 않는다. 🔴 **그래도 조용히 넘기지
    않는다**: 그 자리가 생기면 후보가 비어 멈추고, 그 사실이
    :attr:`_Settled.blocked` 에 남는다. ``Simulator._settle_forced_passes``
    도 같은 이유로 부르지 않는다.
    """
    forced: list[str] = []
    declined: list[str] = []
    blocked: list[str] = []
    met: list[tuple[int, object]] = []
    for _ in range(SETTLE_GUARD):
        if duel.is_over:
            break
        actor = duel.to_act
        legal = duel.legal_actions(actor)
        for held in legal.unsupported():
            met.append((actor, held))
        if not legal.allowed:
            blocked.append(f"P{actor} 의 후보가 없습니다.")
            break
        passes = [
            action for action in legal.allowed
            if action.kind is PlayerActionKind.PASS
        ]
        others = [
            action for action in legal.allowed
            if action.kind is not PlayerActionKind.PASS
        ]
        if actor == seat and others:
            # 진짜 결정 지점이다.
            break
        if not passes:
            blocked.append(
                f"P{actor} 자리에 패스가 없고 고를 것이 "
                f"{len(others)}개 남았습니다."
            )
            break
        if actor != seat and others:
            declined.append(
                f"P{actor} 자리에 패스 말고 {len(others)}개가 있었지만 "
                f"{NO_INTERFERENCE} 가 패스했습니다."
            )
        done = duel.apply(passes[0])
        label = (
            f"P{actor} 패스 ({NO_INTERFERENCE})" if actor != seat
            else f"P{actor} 패스 (고를 것이 그것뿐)"
        )
        forced.append(f"{label}: {done.reason}")
        if not done.accepted:
            blocked.append(f"P{actor} 의 패스가 거절되었습니다: {done.reason}")
            break
    else:
        blocked.append(
            f"필수 걸음이 {SETTLE_GUARD}번 안에 끝나지 않았습니다 — "
            "여기서 멈추고 그 사실을 적습니다."
        )
    return _Settled(
        forced=tuple(forced),
        declined=tuple(declined),
        blocked=tuple(blocked),
        met=tuple(met),
    )


# ======================================================================
# 선택 분기
# ======================================================================
def iter_selections(ask: ChoiceAsk):
    """
    그 물음의 **허용 조합을 차례로 낸다.** 🔴 **지연 생성이다** (generator).

    🔴 **후보 밖을 만들지 않는다.** 재료는 :attr:`ChoiceAsk.offered` 의
    인스턴스뿐이고, 장수는 ``minimum``~``maximum`` 안이다.

    🔴 **순서가 결정론적이다.** 번호로 정렬한 뒤 ``combinations`` 를 쓰므로
    같은 물음이면 같은 순서가 나온다 — 집합의 반복 순서에 기대지 않는다.

    🔴 **두 비용을 가른다** (Phase 6-AH 보완 B). 후보를 **읽는** 비용은
    ``offered`` 의 길이에 비례하고 (정렬 한 번), 조합을 **만드는** 비용은
    꺼내 쓰는 만큼만 든다. 앞의 것은 피할 수 없고 뒤의 것은 피할 수 있다 —
    그 구분이 이 함수가 생성기인 이유다.

    🔴 **빈 선택과 조합 없음을 가른다.** ``minimum == 0`` 이면 빈 짝 ``()``
    을 **허용 조합의 하나로** 낸다 (아무것도 고르지 않는 선택이 적법하다는
    뜻이다). 낼 것이 없으면 아무것도 내지 않는다.
    """
    pool = tuple(sorted(instance for instance, _card in ask.offered))
    lowest = max(0, ask.minimum)
    for size in range(lowest, ask.maximum + 1):
        if size == 0:
            yield ()
            continue
        if size > len(pool):
            return
        yield from combinations(pool, size)


def selection_options(
    ask: ChoiceAsk, limit: int
) -> "tuple[tuple[tuple[int, ...], ...], bool]":
    """
    앞에서 **최대 ``limit`` 개**의 조합과, **더 있는가**.

    🔴 **전부 만든 뒤 자르지 않는다** (Phase 6-AH 보완 B 가 고친 자리).
    보완 전에는 ``combinations`` 의 결과를 모두 목록에 넣고
    ``options[:limit]`` 로 잘랐다. 실측 — 후보 20개에서 정확히 10개를
    고르는 물음에 상한 4를 주면 **반환은 4개인데 내부 생성은 184,756개**
    였다. 반환 개수만 제한하고 **생성 비용은 제한하지 않았다**, 그리고 그
    생성 도중에는 바깥의 시간 예산 검사가 끼어들지도 못했다.

    지금은 생성기에서 **많아도 ``limit + 1`` 개만 꺼낸다** — ``limit`` 개를
    담고, "하나 더 있는가" 를 알려고 한 개를 더 본다. 그 한 개가
    :attr:`truncated` 의 근거다.

    🔴 **대안이 없는 자리를 잘렸다고 적지 않는다.** 생성기가 ``limit`` 개를
    채우기 전에 끝나면 ``truncated`` 는 거짓이다 — ``limit == 0`` 이고 낼
    조합이 하나도 없는 자리도 그렇다.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise BoundedSearchError(f"상한은 0 이상의 정수입니다: {limit!r}")
    taken: list[tuple[int, ...]] = []
    truncated = False
    for option in iter_selections(ask):
        if len(taken) >= limit:
            truncated = True
            break
        taken.append(option)
    return tuple(taken), truncated


def alternative_options(
    ask: ChoiceAsk, realized: "tuple[int, ...]", limit: int
) -> "tuple[tuple[tuple[int, ...], ...], bool]":
    """
    **이미 한 선택을 뺀 대안**을 앞에서 최대 ``limit`` 개, 그리고 더 있는가.

    🔴 **이미 실행한 기본 선택과 새로 해 볼 대안을 가른다** (보완 B).
    ``realized`` 는 그 걸음에서 **실제로 고른 것**이므로 다시 해 볼 필요가
    없다. 그것을 뺀 나머지가 대안이다.

    🔴 **상한이 0 이어도 "대안이 있는가" 는 답한다.** ``limit == 0`` 이면
    담는 것은 없지만, 대안이 하나라도 있으면 ``more`` 가 참이다. 그래야
    "상한 0 이라 아무것도 확인하지 않았다" 를 **기록할 수** 있다 — 보완
    전에는 그 자리에서 분기 처리를 즉시 건너뛰어 생략 사실이 남지 않았다.

    꺼내는 양은 많아도 ``limit + 2`` 개다 (``realized`` 를 만나 건너뛰는
    한 개를 더 본다).
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise BoundedSearchError(f"상한은 0 이상의 정수입니다: {limit!r}")
    picked: list[tuple[int, ...]] = []
    more = False
    for option in iter_selections(ask):
        if option == realized:
            continue
        if len(picked) >= limit:
            more = True
            break
        picked.append(option)
    return tuple(picked), more


# ======================================================================
# 탐색
# ======================================================================
@dataclass(frozen=True, slots=True)
class _Attempt:
    """후보 하나를 한 각본으로 해 본 결과."""

    accepted: bool
    reason: str
    asks: "tuple[ChoiceAsk, ...]" = ()
    duel: "Duel | None" = None
    settled: _Settled = field(default_factory=_Settled)
    error: str = ""


@dataclass(slots=True)
class _Node:
    sim: Simulator
    path: tuple
    depth: int
    legal: object = None


@dataclass(slots=True)
class _Ledger:
    """탐색 한 번이 쌓는 수치와 메모들."""

    nodes: int = 0
    deepest: int = 0
    choice_branches: int = 0
    """**대기에 넣은 대안 각본**의 수 (:class:`SearchBudget.max_choice_branches`)."""
    choice_plans: int = 0
    """**실제로 돌린 대안 각본**의 수. 예산이 끊으면 대기한 것보다 적다."""
    choice_offers_truncated: int = 0
    """**확인하지 못한 대안이 남은 물음**의 수 (Phase 6-AH 보완 B)."""
    deduped: int = 0
    revisited: int = 0
    """같은 상태에 **더 얕게** 다시 닿아 다시 펼친 횟수 (보완 A)."""
    stale: int = 0
    """대기 중에 **더 얕은 길이 생겨** 펼치지 않은 노드 수 (보완 A)."""
    budget_hit: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    out_of_scope: list = field(default_factory=list)
    declined: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    seen: dict = field(default_factory=dict)
    """
    이 탐색이 본 노드 열쇠 → **그 상태에 가장 얕게 닿은 깊이** (보완 A).

    🔴 **방문 여부만으로는 모자란다.** 깊이 우선 탐색이 같은 상태를 **깊은
    경로로 먼저** 보면, 나중에 더 얕은 경로로 닿아도 "이미 봤다" 로 버린다.
    그런데 깊이 상한이 있으면 얕은 쪽에 **남은 깊이 예산이 더 많다** —
    버리면 상한 안의 경로를 놓친다 (격리 그래프 실측: 보고서 §9.1).

    🔴 **깊이를 열쇠에 넣지 않는다.** 넣으면 같은 상태가 깊이마다 다른
    노드가 되어 중복 제거가 사실상 꺼진다. 열쇠는 그대로 두고 **값**으로
    깊이를 들고 있는다.
    """

    def note(self, bucket: list, line: str) -> bool:
        """그 줄을 **새로** 적었는가. 같은 줄은 한 번만 남는다."""
        if line in bucket:
            return False
        bucket.append(line)
        return True


@dataclass
class BoundedSearch:
    """
    목표에 닿는 **한 경로**를 예산 안에서 찾는다.

    펼치는 순서는 ``canonical_state`` 의 결정론적 깊이 우선이다. 깊이
    우선을 쓰는 이유는 하나 — 목표가 몇 걸음 뒤에 있을 때 노드를 적게
    쓴다. **좋은 수를 먼저 본다는 주장이 아니다** (평가가 없다).
    """

    goal: FieldGoal
    budget: SearchBudget = field(default_factory=SearchBudget)

    def __post_init__(self) -> None:
        if not isinstance(self.goal, FieldGoal):
            raise BoundedSearchError(
                f"FieldGoal 이 필요합니다: {type(self.goal).__name__}"
            )
        if not isinstance(self.budget, SearchBudget):
            raise BoundedSearchError(
                f"SearchBudget 이 필요합니다: {type(self.budget).__name__}"
            )

    # ------------------------------------------------------------------
    def run(self, duel: Duel) -> SearchOutcome:
        """
        **진짜 판은 건드리지 않는다.** 모든 적용은 사본에서 일어난다.

        뿌리 노드는 받은 듀얼 그대로이고, 거기에는 아무것도 적용하지
        않는다 — 첫 걸음부터 :meth:`Simulator.fork` 가 만든 사본이다.
        """
        if not isinstance(duel, Duel):
            raise BoundedSearchError(f"Duel 이 필요합니다: {type(duel).__name__}")
        started = time.monotonic()
        ledger = _Ledger()
        root_hash = duel.state.state_hash()
        root_draws = duel.state.randomness.draws

        verdict = self.goal.judge(duel)
        if verdict.reached:
            return self._outcome(
                Termination.GOAL_REACHED, ledger, (), duel, verdict, started
            )

        #: 🔴 **사본이 선택 정책을 받는지 먼저 확인한다.** 받지 못하면 해결
        #: 중 선택이 사본 안에서 거절되고, 그 결과는 "목표에 닿지 못했다" 로
        #: 보인다 — 그 둘을 섞지 않으려고 **사실을 적는다** (§4.4).
        if self.budget.max_choice_branches and _chooser_of(duel) is not None:
            probe = Simulator(duel).fork(
                selector=ScriptedChoice((), FirstPermittedChoice(), name="probe")
            )
            if _chooser_of(probe) is None:
                ledger.note(ledger.out_of_scope, CHOICE_BRANCHING_UNAVAILABLE)

        root = _Node(Simulator(duel), (), 0)
        termination, found = self._drive(root, ledger, started)

        #: 🔴 **종료 사유는 고리가 확정한다** (:meth:`_classify`).

        #: 🔴 **진짜 판이 그대로인지 확인한다.** 탐색이 원본을 밀면 그
        #: 결과는 분석이 아니라 사고다.
        if duel.state.state_hash() != root_hash:
            raise BoundedSearchError(
                "탐색이 원본 판을 바꿨습니다 — 사본에만 적용해야 합니다."
            )
        if duel.state.randomness.draws != root_draws:
            raise BoundedSearchError(
                "탐색이 원본의 난수원을 밀었습니다 — 사본에만 적용해야 합니다."
            )

        if found is not None:
            path, final, verdict = found
            return self._outcome(
                termination, ledger, path, final, verdict, started
            )
        return self._outcome(
            termination, ledger, (), duel, self.goal.judge(duel), started
        )

    # ------------------------------------------------------------------
    def _drive(self, root: _Node, ledger: _Ledger, started: float):
        """
        깊이 우선 고리 하나. 돌려주는 것은 ``(종료 사유, 찾은 것)``.

        🔴 **:meth:`run` 과 가른 이유가 시험이다** (Phase 6-AH 보완 A).
        중복 제거가 깊이를 어떻게 보는지는 **고리 · :meth:`_open` ·
        :func:`admit` · :func:`superseded` 가 함께** 만드는 동작이므로,
        그것을 재려면 그 넷을 **그대로** 돌려야 한다. 격리된 그래프로
        재는 시험이 이 자리에 들어온다 (``tests/
        test_bounded_search_depth_and_choices.py``) — 시험이 제 알고리즘을
        따로 적어 그것만 통과시키는 일을 막는다.

        :meth:`run` 은 그대로 입력을 검사하고 (``Duel`` 인가) 원본이
        그대로인지 확인한다 — 그 둘은 이 고리의 일이 아니다.

        🔴 **뿌리도 같은 원칙을 받는다.** 뿌리의 열쇠를 깊이 0 으로 적어
        두므로, 순환 경로가 뿌리로 돌아오면 그것도 중복이다.
        """
        stack: list[_Node] = [root]
        admit(ledger.seen, self._key_of(root), 0)
        termination = Termination.EXHAUSTED
        found = None

        while stack:
            spent = time.monotonic() - started
            if ledger.nodes >= self.budget.max_nodes:
                ledger.note(ledger.budget_hit, f"max_nodes={self.budget.max_nodes}")
                termination = Termination.BUDGET_EXCEEDED
                break
            if spent >= self.budget.max_seconds:
                ledger.note(
                    ledger.budget_hit, f"max_seconds={self.budget.max_seconds:g}"
                )
                termination = Termination.BUDGET_EXCEEDED
                break
            node = stack.pop()
            #: 🔴 **꺼낼 때 한 번 더 본다** — 이 노드가 대기하는 동안 같은
            #: 상태에 더 얕게 닿았으면 이 노드는 할 일이 없다
            #: (:func:`superseded`).
            if self.budget.dedup and superseded(
                ledger.seen, self._key_of(node), node.depth
            ):
                ledger.stale += 1
                continue
            ledger.deepest = max(ledger.deepest, node.depth)
            found = self._open(node, ledger, stack, started)
            if found is not None:
                termination = Termination.GOAL_REACHED
                break
        return self._classify(termination, found, ledger), found

    @staticmethod
    def _classify(termination, found, ledger: _Ledger) -> Termination:
        """
        고리가 끝난 뒤 **종료 사유를 확정한다.**

        🔴 **오류가 가장 센 사실이다.** 예외가 났는데 "범위를 다 펼쳤다"
        거나 "예산에 걸렸다" 로 적으면 그 예외가 보고에서 사라진다.

        🔴 **예산에 걸린 채로 "범위를 다 펼쳤다" 고 적지 않는다.** 깊이
        상한에 걸려 더 내려가지 못한 가지나, **확인하지 못한 선택 대안**이
        하나라도 있으면 그 탐색은 소진된 것이 아니다 — 못 찾았다는 말과
        범위를 다 봤다는 말은 다른 사실이다 (:class:`Termination`).

        🔴 **이 판정이 고리 안에 있는 이유.** :meth:`run` 에만 두면 고리를
        직접 돌리는 쪽(격리 그래프 시험)이 다른 답을 보게 되고, 그러면 두
        계층의 종료 사유가 어긋난다.
        """
        if found is not None:
            return Termination.GOAL_REACHED
        if ledger.errors:
            return Termination.ERROR
        if termination is Termination.EXHAUSTED and ledger.budget_hit:
            return Termination.BUDGET_EXCEEDED
        return termination

    def _key_of(self, node: _Node):
        """그 노드의 상태 열쇠. 후보 목록을 **다시 세지 않는다.**"""
        duel = node.sim.duel
        legal = (
            node.legal if node.legal is not None
            else duel.legal_actions(duel.to_act)
        )
        node.legal = legal
        return node_key(duel, legal)

    # ------------------------------------------------------------------
    def _open(self, node: _Node, ledger: _Ledger, stack: list, started: float):
        """노드 하나를 펼친다. 목표를 찾으면 ``(경로, 판, 판정)``."""
        duel = node.sim.duel
        if duel.is_over:
            return None
        if node.depth >= self.budget.max_depth:
            ledger.note(ledger.budget_hit, f"max_depth={self.budget.max_depth}")
            return None
        if duel.to_act != self.goal.seat:
            ledger.note(
                ledger.blocked,
                f"P{duel.to_act} 자리에 고를 것이 남아 더 펼치지 않았습니다 — "
                "이번 범위는 상대의 선택을 탐색하지 않습니다.",
            )
            return None

        legal = node.legal if node.legal is not None else duel.legal_actions(duel.to_act)
        for held in legal.unsupported():
            ledger.note(
                ledger.unsupported,
                Simulator._encountered_line(
                    held, seat=duel.to_act, viewer=self.goal.seat
                ),
            )
        ordered = sorted(legal.allowed, key=_order_key)
        children: list[_Node] = []
        for action in ordered:
            if action.kind is PlayerActionKind.END_PHASE:
                ledger.note(ledger.out_of_scope, OUT_OF_TURN_SCOPE)
                continue
            if ledger.nodes >= self.budget.max_nodes:
                ledger.note(ledger.budget_hit, f"max_nodes={self.budget.max_nodes}")
                break
            if time.monotonic() - started >= self.budget.max_seconds:
                ledger.note(
                    ledger.budget_hit, f"max_seconds={self.budget.max_seconds:g}"
                )
                break
            for attempt in self._attempts(node.sim, action, ledger, started):
                if attempt.error:
                    continue
                if not attempt.accepted or attempt.duel is None:
                    continue
                child_duel = attempt.duel
                step = PathStep(
                    order=node.depth + 1,
                    kind=action.kind.value,
                    action_key=action.canonical_state(),
                    choices=attempt.asks,
                    forced=attempt.settled.forced,
                    reason=attempt.reason,
                )
                path = node.path + (step,)
                child_legal = child_duel.legal_actions(child_duel.to_act)
                verdict = self.goal.judge(child_duel, child_legal)
                if verdict.reached:
                    return path, child_duel, verdict
                child_depth = node.depth + 1
                if self.budget.dedup:
                    verdict_on_key = admit(
                        ledger.seen,
                        node_key(child_duel, child_legal),
                        child_depth,
                    )
                    if verdict_on_key is Admission.DUPLICATE:
                        ledger.deduped += 1
                        continue
                    if verdict_on_key is Admission.SHALLOWER:
                        #: 🔴 **다시 펼친다.** 남은 깊이 예산이 더 많으므로
                        #: 이 쪽에서만 닿는 경로가 있을 수 있다.
                        ledger.revisited += 1
                children.append(
                    _Node(Simulator(child_duel), path, child_depth, child_legal)
                )
        #: 깊이 우선 — 앞쪽 후보를 **먼저** 펼치려면 뒤에서부터 쌓는다.
        stack.extend(reversed(children))
        return None

    # ------------------------------------------------------------------
    def _attempts(
        self, parent: Simulator, action: PlayerAction, ledger: _Ledger, started: float
    ) -> "list[_Attempt]":
        """
        같은 행동을 **해결 중 선택만 바꿔** 여러 번 해 본다.

        🔴 **진행 중인 상태를 고치지 않는다.** 각본마다 부모의 판에서
        **처음부터** 다시 하고, 사본은 각본마다 하나다. 같은 효과를 두 번
        적용하는 자리가 없다.

        각본을 늘리는 방법 — 빈 각본으로 한 번 돌리면 그 걸음의 물음
        전부가 기록에 남는다. 그 기록의 **실제 답**을 앞부분으로 고정하고
        한 자리만 다른 답으로 바꾼 각본을 큐에 넣는다. 그러면 같은 미래를
        두 번 계산하지 않는다.
        """
        results: list[_Attempt] = []
        queue: list[tuple] = [()]
        seen_plans: set = {()}
        branches = 0
        while queue:
            if ledger.nodes >= self.budget.max_nodes:
                ledger.note(ledger.budget_hit, f"max_nodes={self.budget.max_nodes}")
                break
            if time.monotonic() - started >= self.budget.max_seconds:
                ledger.note(
                    ledger.budget_hit, f"max_seconds={self.budget.max_seconds:g}"
                )
                break
            plan = queue.pop(0)
            attempt = self._apply_once(parent, action, plan)
            ledger.nodes += 1
            if plan:
                #: 🔴 **실행한 대안 각본의 수**다 — 대기에 넣은 수
                #: (:attr:`_Ledger.choice_branches`) 와 섞지 않는다. 예산이
                #: 고리를 끊으면 대기한 것보다 적다.
                ledger.choice_plans += 1
            if attempt.error:
                ledger.note(ledger.errors, attempt.error)
            for line in attempt.settled.declined:
                ledger.note(ledger.declined, line)
            for line in attempt.settled.blocked:
                ledger.note(ledger.blocked, line)
            for seat, held in attempt.settled.met:
                ledger.note(
                    ledger.unsupported,
                    Simulator._encountered_line(
                        held, seat=seat, viewer=self.goal.seat
                    ),
                )
            results.append(attempt)
            if not attempt.accepted:
                continue
            realized = tuple(ask.chosen for ask in attempt.asks)
            cap = self.budget.max_choice_branches
            #: 🔴 **상한에 걸렸어도 물음마다 한 번은 본다** (보완 B).
            #: 보완 전에는 ``branches >= cap`` 이면 이 고리를 **즉시
            #: 끊었고**, 그래서 상한 0 이거나 앞선 물음이 상한을 다 쓴
            #: 경우에 **대안이 있어도 생략 사실이 남지 않았다.** 지금은
            #: 물음마다 :func:`alternative_options` 를 부르는데, 그 호출은
            #: 상한이 0 이어도 조합을 많아도 두 개만 꺼내므로 (설명 참조)
            #: 비용이 상한과 함께 묶여 있다.
            for index in range(len(plan), len(attempt.asks)):
                ask = attempt.asks[index]
                room = max(0, cap - branches)
                alternatives, more = alternative_options(
                    ask, realized[index], room
                )
                for option in alternatives:
                    plan_next = realized[:index] + (option,)
                    if plan_next in seen_plans:
                        continue
                    seen_plans.add(plan_next)
                    queue.append(plan_next)
                    branches += 1
                    ledger.choice_branches += 1
                if more:
                    #: 🔴 **확인하지 않은 대안이 남았다.** 그 사실을 범위 밖
                    #: 목록과 **예산에 걸린 칸**에 함께 적는다 — 그러면 아무
                    #: 것도 못 찾았을 때 종료 사유가 "범위를 다 펼쳤다" 가
                    #: 되지 않는다 (:class:`Termination` 의 구분).
                    #: 🔴 **물음 하나를 한 번만 센다.** 같은 물음이 여러
                    #: 각본에서 다시 나오므로, 집계를 **새로 적은 줄**에
                    #: 묶어 둔다 — 그러지 않으면 목록은 2줄인데 수치는 3이
                    #: 되어 두 보고가 어긋난다 (실측).
                    if ledger.note(
                        ledger.out_of_scope, _skipped_choices_line(ask, cap)
                    ):
                        ledger.choice_offers_truncated += 1
                    ledger.note(ledger.budget_hit, f"max_choice_branches={cap}")
        return results

    def _apply_once(
        self, parent: Simulator, action: PlayerAction, plan: tuple
    ) -> _Attempt:
        """사본 하나에 그 행동을 적용하고 필수 걸음까지 지난다."""
        scripted = ScriptedChoice(plan, FirstPermittedChoice(), name="bounded-search")
        fork = parent.fork(selector=scripted)
        try:
            step = fork.apply(action)
        except Exception as error:  # noqa: BLE001 - 숨기지 않고 상태로 남긴다
            return _Attempt(
                accepted=False,
                reason=f"{type(error).__name__}: {error}",
                asks=scripted.log,
                error=f"{action.kind.value}: {type(error).__name__}: {error}",
            )
        if not step.accepted:
            return _Attempt(
                accepted=False, reason=step.reason, asks=scripted.log
            )
        settled = _settle(fork, self.goal.seat)
        return _Attempt(
            accepted=True,
            reason=step.reason,
            asks=scripted.log,
            duel=fork,
            settled=settled,
        )

    # ------------------------------------------------------------------
    def _outcome(
        self,
        termination: Termination,
        ledger: _Ledger,
        path: tuple,
        duel: Duel,
        verdict: GoalVerdict,
        started: float,
    ) -> SearchOutcome:
        return SearchOutcome(
            goal=self.goal,
            termination=termination,
            budget=self.budget,
            budget_hit=tuple(ledger.budget_hit),
            path=tuple(path),
            nodes_expanded=ledger.nodes,
            deepest=ledger.deepest,
            choice_branches=ledger.choice_branches,
            choice_plans=ledger.choice_plans,
            choice_offers_truncated=ledger.choice_offers_truncated,
            deduped=ledger.deduped,
            revisited=ledger.revisited,
            stale=ledger.stale,
            elapsed_seconds=time.monotonic() - started,
            unsupported=tuple(ledger.unsupported),
            out_of_scope=tuple(ledger.out_of_scope),
            opponent_declined=tuple(ledger.declined),
            opponent_blocked=tuple(ledger.blocked),
            errors=tuple(ledger.errors),
            final_field=own_field(duel, self.goal.seat),
            final_state_hash=duel.state.state_hash(),
            goal_reason=verdict.reason,
        )


def _skipped_choices_line(ask: ChoiceAsk, cap: int) -> str:
    """
    **확인하지 않은 선택 대안이 남았다**는 한 줄 (Phase 6-AH 보완 B).

    🔴 **상한의 뜻을 문장에 적는다.** 세 수치가 혼용되지 않아야 한다 —
    *만든* 조합 수 · *대기에 넣은* 대안 각본 수 · *실행한* 대안 각본 수.
    상한이 세는 것은 가운데 하나다.
    """
    return (
        f"{ask.label} 의 해결 중 선택: 그 자리의 후보 {ask.options}장에서 "
        "**확인하지 않은 대안이 남았습니다** — 한 행동의 선택 분기 상한 "
        f"{cap}개에 걸렸습니다. 그 상한이 세는 것은 **대기에 넣은 대안 "
        "각본의 수**이고, 만든 조합의 수도 실행한 각본의 수도 아닙니다."
    )


def _order_key(action: PlayerAction) -> tuple:
    """
    후보를 **결정론적으로** 줄 세운다.

    🔴 **좋음의 순서가 아니다.** ``canonical_state`` 를 글자로 비교하는
    이유는 그 안에 ``None`` 과 정수가 섞여 있어 그대로는 비교할 수 없기
    때문이다 (실측: ``('end_phase', 0, None, …)`` 와
    ``('normal_summon', 0, 75, …)`` 를 비교하면 종류가 같을 때 터진다).
    """
    return (action.kind.value, repr(action.canonical_state()))


# ======================================================================
# 재생
# ======================================================================
def rerun_path(
    duel: Duel, outcome: SearchOutcome, *, goal: "FieldGoal | None" = None
) -> RerunResult:
    """
    찾은 경로를 **새 초기 상태에서 다시 실행**한다 (§5).

    🔴 **탐색이 만든 최종 판을 그대로 내보내는 것으로 끝내지 않는다.**
    같은 입력으로 만든 새 듀얼에서 걸음을 다시 밟고, 그 결과를 잰다.

    🔴 **기록된 행동이 지금 허용 후보인지 다시 본다.** ``canonical_state``
    가 같은 후보를 그 자리의 ``legal.allowed`` 에서 찾고, 없으면 **실패**로
    적는다 — 객체를 들고 다니며 억지로 적용하지 않는다.

    🔴 **기록된 선택이 그 자리의 허용 후보인지 다시 본다.**
    :class:`~agent.choice.ScriptedChoice` 가 후보 밖이면 쓰지 않고 그 사실을
    적으므로 (``plan_missing``), 하나라도 있으면 **실패**다.
    """
    if not isinstance(duel, Duel):
        raise BoundedSearchError(f"Duel 이 필요합니다: {type(duel).__name__}")
    if not isinstance(outcome, SearchOutcome):
        raise BoundedSearchError(
            f"SearchOutcome 이 필요합니다: {type(outcome).__name__}"
        )
    target = outcome.goal if goal is None else goal
    if not outcome.path:
        return RerunResult(
            ok=False,
            reason="재생할 경로가 없습니다 — 탐색이 목표에 닿지 않았습니다.",
        )

    sim = Simulator(duel)
    done = 0
    for recorded in outcome.path:
        current = sim.duel
        if current.to_act != target.seat:
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 걸음 앞에서 고를 사람이 "
                       f"P{current.to_act} 입니다 — 기록과 다릅니다.",
                steps=done,
            )
        legal = current.legal_actions(current.to_act)
        matches = [
            action for action in legal.allowed
            if action.canonical_state() == recorded.action_key
        ]
        if not matches:
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 행동이 지금 허용 후보에 "
                       f"없습니다: {recorded.kind} {recorded.action_key}",
                steps=done,
            )
        plan = tuple(ask.chosen for ask in recorded.choices)
        scripted = ScriptedChoice(plan, FirstPermittedChoice(), name="rerun")
        fork = sim.fork(selector=scripted)
        try:
            step = fork.apply(matches[0])
        except Exception as error:  # noqa: BLE001
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 행동에서 예외가 났습니다: "
                       f"{type(error).__name__}: {error}",
                steps=done,
            )
        if not step.accepted:
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 행동이 거절되었습니다: "
                       f"{step.reason}",
                steps=done,
            )
        _settle(fork, target.seat)
        if scripted.plan_was_missed:
            missed = [ask.describe_ko() for ask in scripted.log if ask.plan_missing]
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 걸음에서 기록된 선택이 그 자리의 "
                       f"허용 후보에 없었습니다: {' / '.join(missed)}",
                steps=done,
            )
        done_asks = tuple(ask.chosen for ask in scripted.log)
        if done_asks[: len(plan)] != plan:
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 걸음의 선택이 기록과 다릅니다: "
                       f"{plan} → {done_asks[: len(plan)]}",
                steps=done,
            )
        if len(done_asks) != len(plan):
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 걸음의 물음 수가 기록과 "
                       f"다릅니다: {len(plan)} → {len(done_asks)}",
                steps=done,
            )
        sim = Simulator(fork)
        done += 1

    verdict = target.judge(sim.duel)
    field_now = own_field(sim.duel, target.seat)
    hash_now = sim.duel.state.state_hash()
    same = (
        field_now == outcome.final_field
        and hash_now == outcome.final_state_hash
    )
    if not verdict.reached:
        reason = f"재생이 목표에 닿지 않았습니다: {verdict.reason}"
    elif not same:
        reason = (
            "재생이 목표에는 닿았지만 최종 판이 탐색 결과와 다릅니다 — "
            f"해시 {outcome.final_state_hash[:12]}… → {hash_now[:12]}…"
        )
    else:
        reason = (
            f"걸음 {done}개를 새 초기 상태에서 다시 밟아 같은 최종 판에 "
            "닿았습니다."
        )
    return RerunResult(
        ok=verdict.reached and same,
        reason=reason,
        steps=done,
        goal_reached=verdict.reached,
        final_field=field_now,
        final_state_hash=hash_now,
        matches_search=same,
    )


def search_for_card(
    duel: Duel,
    card_id: int,
    *,
    seat: int = 0,
    budget: "SearchBudget | None" = None,
) -> SearchOutcome:
    """그 카드를 자신 필드에 올리는 경로 하나를 예산 안에서 찾는다."""
    return BoundedSearch(
        goal=FieldGoal(card_id=card_id, seat=seat),
        budget=SearchBudget() if budget is None else budget,
    ).run(duel)


__all__ = [
    "BoundedSearch",
    "BoundedSearchError",
    "CHOICE_BRANCHING_UNAVAILABLE",
    "DEFAULT_MAX_CHOICE_BRANCHES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_SECONDS",
    "FIELD_ZONES",
    "FieldGoal",
    "GoalVerdict",
    "NO_INTERFERENCE",
    "OUT_OF_TURN_SCOPE",
    "PathStep",
    "RerunResult",
    "SETTLE_GUARD",
    "SearchBudget",
    "SearchOutcome",
    "Termination",
    "node_key",
    "own_field",
    "rerun_path",
    "search_for_card",
    "Admission",
    "admit",
    "alternative_options",
    "iter_selections",
    "selection_options",
    "superseded",
]
