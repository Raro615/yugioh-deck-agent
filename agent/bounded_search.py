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

import dataclasses
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

#: 기본은 **결과 하나**다 — 기존 단일 결과 모드와 한 글자도 다르지 않다
#: (Phase 6-AI). 복수 결과는 명시적으로 골라야 켜진다.
DEFAULT_MAX_RESULTS: int = 1
#: 복수 모드를 고를 때의 권장 기본값.
MULTI_DEFAULT_MAX_RESULTS: int = 3
#: 🔴 **옵션으로 노출할 수 있는 작고 명확한 상한.** 결과 하나마다 재생을
#: 한 번 더 돌리므로 (§5) 비용이 결과 수에 비례한다.
RESULTS_CAP: int = 5
#: 재생 전부에 쓸 수 있는 시간의 상한 — **탐색 예산과 따로** 둔다.
DEFAULT_MAX_RERUN_SECONDS: float = 180.0

#: 기본은 **목표에 처음 도달하면 그 분기를 더 펼치지 않는다** (Phase 6-AI
#: 그대로). 0 이면 그 모드이고, 후속 전개 탐색은 **명시적으로 골라야**
#: 켜진다 (Phase 6-AL).
DEFAULT_MAX_FOLLOWUP_ACTIONS: int = 0
#: 후속 모드를 고를 때의 권장 기본값 — **작고 명시적인 상한**이다.
FOLLOWUP_DEFAULT_ACTIONS: int = 2
#: 🔴 **옵션으로 노출할 수 있는 상한.** 기준점마다 분기가 늘어나므로 비용이
#: 빠르게 커진다 — 크게 열어 두면 예산이 한 기준점에서 소진된다.
FOLLOWUP_CAP: int = 3
#: 후속 모드에서 **기준점(최초 도달)** 을 몇 개까지 보관할지의 기본값.
#: 🔴 후속 후보의 상한(:attr:`SearchBudget.max_results`)과 **역할이 다르다**.
DEFAULT_MAX_BASELINES: int = 1

#: 필수 걸음(패스 · 드로우)을 지나가는 반복의 안전장치. 무한 반복을 막는
#: 것뿐이고, 여기 걸리면 그 사실을 노드에 적는다.
SETTLE_GUARD: int = 24

#: **흐름 행동** — 전개 비용으로 세지 않는다 (Phase 6-AK 가 평가에서, 6-AL
#: 이 후속 상한에서 같은 집합을 쓴다). 🔴 패스는 무엇을 쓰는 수가 아니라
#: 우선권을 넘기는 수이고, 페이즈를 넘기는 수도 그렇다. 비용으로 세면
#: "패스를 한 번 더 한 경로" 가 더 비싼 전개로 읽힌다.
#:
#: 🔴 **반복 방지와는 별개다** — 흐름 행동도 노드를 만들고 중복 제거
#: (:func:`node_key`)와 필수 처리 상한(:data:`SETTLE_GUARD`)을 그대로 지난다.
FLOW_ACTION_KINDS: frozenset = frozenset({
    "pass", "end_phase", "change_phase",
})

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
    max_results: int = DEFAULT_MAX_RESULTS
    """
    모을 **서로 다른 성공 결과**의 상한 (Phase 6-AI).

    🔴 **1 이면 기존 단일 결과 모드다** — 첫 성공에서 멈추고 돌려주는 값도
    :class:`SearchOutcome` 그대로다. 2 이상이면 복수 결과 모드이고
    :meth:`BoundedSearch.run_many` 로 들어간다.

    🔴 **중복 결과는 이 수를 늘리지 않는다.** 같은 최종 결과에 다른 행동
    순서로 닿으면 대표 하나로 합치고 (:func:`outcome_key`), 그 사실을
    :attr:`PathResult.duplicates` 로 센다.
    """
    max_rerun_seconds: float = DEFAULT_MAX_RERUN_SECONDS
    max_followup_actions: int = DEFAULT_MAX_FOLLOWUP_ACTIONS
    """
    목표에 처음 도달한 뒤 **추가로 탐색할 비흐름 행동 수**의 상한
    (Phase 6-AL).

    🔴 **0 이 기본이고, 그때는 6-AI 와 한 글자도 다르지 않다** — 목표에 닿은
    분기를 더 펼치지 않는다. 1 이상이면 후속 모드다.

    🔴 **흐름 행동(패스 · 페이즈 전환)은 이 수에 넣지 않는다** — 패스는
    무엇을 쓰는 수가 아니라 우선권을 넘기는 수다. 그래도 반복 방지
    (:func:`node_key` 중복 제거)와 필수 처리 상한(:data:`SETTLE_GUARD`)은
    그대로 돈다.

    🔴 **깊이 상한을 대신하지 않는다** — :attr:`max_depth` 는 그대로
    적용되므로, 기준점이 깊으면 남은 깊이만큼만 더 간다.
    """
    max_baselines: int = DEFAULT_MAX_BASELINES
    """
    후속 모드에서 보관할 **기준점(최초 목표 도달)** 의 수 (Phase 6-AL).

    🔴 **후속 후보의 상한과 역할이 다르다.** :attr:`max_results` 는 **제시할
    후속 후보**의 상한이고, 이 칸은 **어디에서 출발할지**의 상한이다. 둘을
    한 칸에 담으면 "기준점을 모으는 순간 결과 상한에 걸려 후속 행동을 전혀
    탐색하지 않는" 구조가 된다.

    🔴 첫 도달 모드(``max_followup_actions == 0``)에서는 쓰지 않는다 — 그때
    기준점이 곧 결과다.
    """
    """
    재생 **전부**에 쓸 수 있는 시간. 🔴 탐색 예산과 **따로** 둔다 — 그래야
    보고가 탐색 소요와 재생 소요를 가를 수 있고, 결과 수를 늘렸을 때
    전체 요청 시간이 무제한으로 늘지 않는다.
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
        for name, value in (
            ("max_seconds", self.max_seconds),
            ("max_rerun_seconds", self.max_rerun_seconds),
        ):
            if not isinstance(value, (int, float)) or value <= 0:
                raise BoundedSearchError(f"{name} 는 0 보다 큰 수입니다: {value!r}")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or not 1 <= self.max_results <= RESULTS_CAP
        ):
            raise BoundedSearchError(
                f"max_results 는 1 이상 {RESULTS_CAP} 이하의 정수입니다 "
                f"(1 이면 단일 결과 모드): {self.max_results!r}"
            )
        if (
            isinstance(self.max_followup_actions, bool)
            or not isinstance(self.max_followup_actions, int)
            or not 0 <= self.max_followup_actions <= FOLLOWUP_CAP
        ):
            raise BoundedSearchError(
                f"max_followup_actions 는 0 이상 {FOLLOWUP_CAP} 이하의 "
                f"정수입니다 (0 이면 첫 도달 모드): "
                f"{self.max_followup_actions!r}"
            )
        if (
            isinstance(self.max_baselines, bool)
            or not isinstance(self.max_baselines, int)
            or not 1 <= self.max_baselines <= RESULTS_CAP
        ):
            raise BoundedSearchError(
                f"max_baselines 는 1 이상 {RESULTS_CAP} 이하의 정수입니다: "
                f"{self.max_baselines!r}"
            )

    @property
    def many(self) -> bool:
        """복수 결과 모드인가."""
        return self.max_results > 1

    @property
    def continues(self) -> bool:
        """
        **후속 전개 탐색 모드인가** (Phase 6-AL).

        🔴 거짓이면 목표에 처음 도달한 분기를 더 펼치지 않는다 — 기존 동작
        그대로다.
        """
        return self.max_followup_actions > 0

    def describe_ko(self) -> str:
        return (
            f"깊이 {self.max_depth} · 노드 {self.max_nodes} · "
            f"{self.max_seconds:g}초 · 선택 분기 {self.max_choice_branches}"
            + (f" · 결과 {self.max_results}개" if self.many else "")
            + (f" · 재생 {self.max_rerun_seconds:g}초" if self.many else "")
            + (f" · 후속 행동 {self.max_followup_actions}회"
               f" · 기준점 {self.max_baselines}개" if self.continues else "")
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


class ResultRole(str, Enum):
    """
    결과 하나가 **무엇인가** (Phase 6-AL).

    🔴 **기준점과 후속 후보를 가른다.** 섞으면 "목표에 처음 도달한 자리" 와
    "거기서 더 간 자리" 가 한 줄로 보여서, 비교의 기준이 사라진다.
    """

    FIRST_ARRIVAL = "first_arrival"
    """**최초 목표 도달 기준점** — 체인과 필수 처리가 정리된 결정 지점."""
    CONTINUED = "continued"
    """기준점에서 **후속 행동을 실제로 수행한** 후보."""


class ContinuationStop(str, Enum):
    """
    후속 후보가 **왜 거기서 멈췄는가** (Phase 6-AL §4).

    🔴 **"더 할 수 있는 것이 없다" 로 뭉개지 않는다.** 상한에 걸린 것과,
    합법 후보가 없는 것과, 지원하지 않아 후보가 되지 못한 수가 남은 것은
    서로 다른 사실이다.
    """

    OPEN = "open"
    """더 갈 수 있는 자리다 — 🔴 이 후보는 **전개 완료가 아니다.**"""
    ACTION_CAP = "action_cap"
    """``max_followup_actions`` 에 닿았다."""
    DEPTH_CAP = "depth_cap"
    """``max_depth`` 에 닿았다 — 🔴 후속 상한과 다른 상한이다."""
    NO_LEGAL = "no_legal"
    """이 턴 범위에서 엔진이 허가한 수가 없다(``end_phase`` 는 범위 밖)."""
    UNSUPPORTED_LEFT = "unsupported_left"
    """
    허가된 수가 없지만 **지원하지 않아 후보가 되지 못한 수가 남아 있다.**
    🔴 그래서 "규칙상 더 할 수 없다" 고 단정하지 않는다.
    """
    BUDGET = "budget"
    """전체 예산(시간 · 노드 · 결과 수)이 끊어서 끝까지 보지 못했다."""


@dataclass(frozen=True, slots=True)
class FoundMeta:
    """
    모은 결과 하나의 **후속 전개 이력** (Phase 6-AL).

    🔴 **최초 도달 기록은 사라지지 않는다.** 후속 전개 중 목표 카드를
    소재나 비용으로 써도 :attr:`reached_at` 은 남고, 최종 상태에 목표가
    남아 있는지는 :attr:`goal_kept` 이 따로 말한다 — 둘을 한 칸에 담으면
    "목표를 거친 경로" 가 "목표가 있는 집" 으로 읽힌다.
    """

    role: ResultRole = ResultRole.FIRST_ARRIVAL
    reached_at: int = 0
    """목표에 **처음** 도달한 걸음의 순서(1부터). 0 이면 알 수 없다."""
    followup_actions: int = 0
    """기준점 뒤에 실제로 수행한 **비흐름 행동**의 수."""
    followup_flow: int = 0
    """기준점 뒤의 **흐름 행동** 수 — 🔴 후속 상한에 세지 않은 것."""
    goal_kept: bool = True
    """**최종 상태에도** 목표 카드가 앞면으로 남아 있는가."""
    stop: ContinuationStop = ContinuationStop.OPEN
    stop_note: str = ""
    merged_arrivals: "tuple[int, ...]" = ()
    """
    같은 최종 상태로 합쳐진 다른 경로들의 **최초 도달 걸음**들 (§4).

    🔴 **대표를 고르면서 다른 도달 이력을 지우지 않는다.** 대표는
    :func:`representative_order` 가 고르고(기존 기준 그대로), 합쳐진 쪽의
    도달 위치는 여기 남는다.
    """

    @property
    def continued(self) -> bool:
        return self.role is ResultRole.CONTINUED


class RerunState(str, Enum):
    """
    결과 하나의 **재생 상태** (Phase 6-AJ).

    🔴 **여섯 가지를 한 칸으로 뭉치지 않는다.** 섞으면 "검증되지 않았다"
    하나로 읽혀서, 왜 검증되지 않았는지(시간이 없었나 · 예외가 났나 ·
    판이 달랐나 · 아예 끄고 돌렸나)를 되돌릴 수 없다.
    """

    VERIFIED = "verified"
    """재생이 같은 판에 닿고 자원 요약까지 같았다."""
    MISMATCHED = "mismatched"
    """재생이 돌았지만 행동 · 선택 · 최종 상태 · 자원 요약이 어긋났다."""
    ERRORED = "errored"
    """재생 도중 **일반 실행 예외**가 났다 (:attr:`RerunResult.error_type`)."""
    TIMED_OUT = "timed_out"
    """재생을 **시작했는데** 공유 마감 시각을 넘겼다."""
    NOT_STARTED = "not_started"
    """시간이 남지 않아 **시작조차 하지 않았다.** 🔴 위와 다른 사실이다."""
    DISABLED = "disabled"
    """``rerun=False`` 로 재생을 **명시적으로 끄고** 돌렸다."""

    @property
    def ran(self) -> bool:
        """재생을 **시작했는가.**"""
        return self in (
            RerunState.VERIFIED, RerunState.MISMATCHED,
            RerunState.ERRORED, RerunState.TIMED_OUT,
        )


@dataclass(slots=True)
class RerunDeadline:
    """
    복수 결과 재생이 **함께 쓰는 마감 시각** (Phase 6-AJ §A).

    🔴 **결과마다 예산을 새로 시작하지 않는다.** 하나를 만들어 모든 결과가
    돌려 쓰므로, 앞의 결과가 쓴 시간이 뒤의 결과에서 되살아나지 않는다.

    🔴 **단조 시계를 쓴다** (:func:`time.monotonic`). 벽시계는 뒤로 갈 수
    있어서 마감 판정이 뒤집힐 수 있다. ``clock`` 은 시험이 **제어 가능한
    단조 시계**를 꽂는 자리다 — 실제 ``sleep`` 이나 기계 성능에 기대지
    않고 경계를 재기 위한 것이고, 기본값은 그대로 :func:`time.monotonic` 이다.

    🔴 **협력적 시간 제한이다.** 안전한 경계에서만 멈춘다 — 돌고 있는 엔진
    호출 하나를 **강제로 끊지 않는다** (그러려면 프로세스나 스레드 구조가
    필요하고, 이번 범위가 아니다). 그래서 단일 호출이 오래 걸리면 마감
    시각을 **넘겨서** 돌아올 수 있다. 그때 "지정한 초 안에 끝났다" 고
    말하지 않고, 돌아온 즉시 초과를 보고 성공 처리를 막는다.

    🔴 **마감과 정확히 같은 순간은 만료로 본다** (``spent >= limit``).
    경계를 한쪽으로 고정해 두어야 "같을 때는 어느 쪽" 이 구현마다
    달라지지 않는다 (``test_bounded_search_rerun_limits.py::test_a08``).
    """

    limit: float
    clock: "object" = time.monotonic
    started: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(
            self.limit, (int, float)
        ):
            raise BoundedSearchError(
                f"재생 마감은 수여야 합니다: {self.limit!r}"
            )
        if self.limit <= 0:
            raise BoundedSearchError(
                f"재생 마감은 0 보다 커야 합니다: {self.limit}"
            )
        if not callable(self.clock):
            raise BoundedSearchError(
                f"시계는 부를 수 있어야 합니다: {type(self.clock).__name__}"
            )
        self.started = float(self.clock())

    @property
    def spent(self) -> float:
        """시작한 뒤 흐른 시간."""
        return float(self.clock()) - self.started

    @property
    def remaining(self) -> float:
        return self.limit - self.spent

    def expired(self) -> bool:
        """🔴 마감과 **같을 때도** 만료다."""
        return self.spent >= self.limit

    def describe_ko(self) -> str:
        return f"재생 마감 {self.limit:g}초 (쓴 시간 {self.spent:.2f}초)"


def _timed_out(stage: str, deadline: "RerunDeadline", steps: int = 0,
               ) -> "RerunResult":
    """마감을 넘긴 재생을 **실패로** 적는다 (성공으로 바꾸지 않는다)."""
    return RerunResult(
        ok=False,
        reason=(
            f"재생이 공유 마감을 넘겼습니다 ({stage}) — "
            f"{deadline.describe_ko()}. 🔴 이 결과는 검증된 비교에 쓰지 "
            "않습니다. (협력적 제한이므로 돌고 있던 엔진 호출 하나는 끊지 "
            "않았습니다 — 그 호출이 돌아온 자리에서 초과를 보았습니다.)"
        ),
        steps=steps,
        timed_out=True,
        stage=stage,
    )


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
    resources: "ResourceSummary | None" = None
    """
    재생이 닿은 판의 **자원 요약** (Phase 6-AI). 재생이 걸음을 하나라도
    밟았으면 채워진다 — 복수 결과 모드가 "탐색이 적어 둔 요약과 재생된
    상태가 같은가" 를 재는 자리다.
    """
    timed_out: bool = False
    """
    **공유 재생 마감을 넘겨** 멈췄는가 (Phase 6-AJ §A).

    🔴 **검증 불일치와 다른 사실이다.** 불일치는 "다시 밟았더니 달랐다"
    이고, 이것은 "끝까지 보지 못했다" 다. 둘을 한 칸에 담으면 시간이 없어
    못 본 것이 "재현되지 않는 경로" 로 읽힌다.
    """
    error_type: str = ""
    """
    재생을 멈춘 **일반 실행 예외**의 형 이름 (Phase 6-AJ §B). 비어 있으면
    예외가 아니라 판정으로 멈춘 것이다.
    """
    stage: str = ""
    """실패가 난 **단계** — 진단용 (``행동 3`` · ``최종 검증`` 등)."""
    first_arrival_at: int = 0
    """
    재생 중 **최초 목표 도달을 확인한** 걸음 (Phase 6-AL). 0 이면 확인할
    지점을 받지 않았다(첫 도달 모드).
    """
    first_arrival_confirmed: bool = False
    """
    기록된 그 걸음에서 **목표에 실제로 닿았는가.**

    🔴 **후속 경로의 성공 조건은 이것이다.** 최종 상태에 목표가 없다는
    이유만으로 실패시키지 않고, 그렇다고 이 확인을 생략하고 성공시키지도
    않는다.
    """
    goal_kept: bool = False
    """**최종 상태에도** 목표가 앞면으로 남아 있는가 (재생이 실제로 센 값)."""

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        mark = "성공" if self.ok else "🔴 실패"
        return (
            f"재생 {mark} — 걸음 {self.steps} · 목표 {self.goal_reached}"
            f" · 탐색 결과와 일치 {self.matches_search}\n  {self.reason}"
        )


@dataclass(frozen=True, slots=True)
class PathResult:
    """
    서로 다른 성공 결과 **하나** (Phase 6-AI).

    🔴 **살아 있는 판을 들고 있지 않다.** :attr:`resources` 가 그 자리에서
    뜬 값이고, 그 뒤의 탐색이 무엇을 하든 변하지 않는다.
    """

    index: int
    path: "tuple[PathStep, ...]"
    resources: ResourceSummary
    goal_reason: str
    duplicates: int = 0
    """같은 결과에 닿은 **다른 경로**의 수. 🔴 결과 수를 늘리지 않는다."""
    rerun: "RerunResult | None" = None
    resources_match: bool = False
    """재생된 상태의 자원 요약이 탐색이 적어 둔 것과 **같은가.**"""
    rerun_disabled: bool = False
    """
    재생을 **명시적으로 끄고** 돌렸는가 (``rerun=False``, Phase 6-AJ §C).

    🔴 **시간이 없어 시작하지 못한 것과 다르다.** 둘 다 재생이 없지만,
    앞은 사용자가 끈 것이고 뒤는 예산이 끊은 것이다.
    """
    meta: FoundMeta = field(default_factory=FoundMeta)
    """후속 전개 이력 (Phase 6-AL). 첫 도달 모드에서는 기본값 그대로다."""

    @property
    def role(self) -> ResultRole:
        return self.meta.role

    @property
    def is_baseline(self) -> bool:
        """**최초 목표 도달 기준점**인가."""
        return self.meta.role is ResultRole.FIRST_ARRIVAL

    @property
    def goal_kept(self) -> bool:
        """
        **최종 상태에도** 목표 카드가 남아 있는가.

        🔴 재생을 돌렸으면 **재생이 센 값**을 쓴다 — 탐색이 적어 둔 것과
        다르면 그쪽이 검증된 사실이다.
        """
        if self.rerun is not None and self.rerun.steps:
            return self.rerun.goal_kept
        return self.meta.goal_kept

    @property
    def action_count(self) -> int:
        return len(self.path)

    @property
    def choice_count(self) -> int:
        return sum(len(step.choices) for step in self.path)

    @property
    def rerun_state(self) -> RerunState:
        """
        이 결과의 **재생 상태** (Phase 6-AJ §C).

        🔴 **담아 둔 값에서 끌어낸다** — 상태를 따로 적어 두면 두 곳이
        어긋날 수 있다.
        """
        if self.rerun is None:
            return (
                RerunState.DISABLED if self.rerun_disabled
                else RerunState.NOT_STARTED
            )
        if self.rerun.timed_out:
            return RerunState.TIMED_OUT
        if self.rerun.error_type:
            return RerunState.ERRORED
        if self.rerun.ok and self.resources_match:
            return RerunState.VERIFIED
        return RerunState.MISMATCHED

    @property
    def verified(self) -> bool:
        """
        **검증된 결과인가** — 재생이 성공하고 자원 요약까지 같은가.

        🔴 재생하지 않았거나 실패한 결과는 **검증된 비교에 섞지 않는다.**
        시간 초과와 예외도 마찬가지다 (:class:`RerunState`).
        """
        return self.rerun_state is RerunState.VERIFIED

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [
            f"[결과 {self.index}] 행동 {self.action_count}걸음 · 해결 중 선택 "
            f"{self.choice_count}회 · 같은 결과에 닿은 다른 경로 "
            f"{self.duplicates}개 · 검증 "
            f"{'✔' if self.verified else '🔴 아님'}"
        ]
        for step in self.path:
            lines.append("  " + step.describe_ko().replace("\n", "\n  "))
        lines.append("  " + self.resources.describe_ko().replace("\n", "\n  "))
        if self.rerun is not None:
            lines.append("  " + self.rerun.describe_ko().replace("\n", "\n  "))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ResultTally:
    """
    모은 결과의 **상태별 집계** (Phase 6-AJ §C).

    🔴 **수가 맞아떨어져야 한다** — :attr:`total` 이 모은 결과 수와 같다
    (``test_c01``). 하나라도 어느 칸에도 들어가지 않으면 "검증되지 않은
    결과가 조용히 사라진" 것이다.
    """

    verified: int = 0
    mismatched: int = 0
    errored: int = 0
    timed_out: int = 0
    not_started: int = 0
    disabled: int = 0

    @property
    def total(self) -> int:
        return (self.verified + self.mismatched + self.errored
                + self.timed_out + self.not_started + self.disabled)

    @property
    def ran(self) -> int:
        """재생을 **시작한** 결과 수."""
        return self.verified + self.mismatched + self.errored + self.timed_out

    @property
    def incomplete(self) -> int:
        """재생을 **마치지 못한** 결과 수 (시간 초과 · 미시작 · 끔)."""
        return self.timed_out + self.not_started + self.disabled

    def describe_ko(self) -> str:
        return (
            f"검증 {self.verified} · 불일치 {self.mismatched} · 예외"
            f" {self.errored} · 시간 초과 {self.timed_out} · 미시작"
            f" {self.not_started} · 재생 끔 {self.disabled}"
        )


@dataclass(frozen=True, slots=True)
class MultiSearchOutcome:
    """
    복수 결과 모드의 결과 **전부** (Phase 6-AI).

    🔴 **"찾은 결과가 있다" 와 "탐색을 끝까지 했다" 를 가른다.**
    :attr:`reached` 가 앞의 것을 말하고 :attr:`search_exhausted` 가 뒤의 것을
    말한다. 둘을 한 칸에 담으면 "셋을 찾았으니 다 봤다" 로 읽힌다.
    :attr:`termination` 은 **고리가 왜 멈췄는가**이고, 복수 결과 모드에서는
    결과를 찾았더라도 ``exhausted`` 나 ``budget_exceeded`` 로 남는다 —
    목표에 닿은 분기를 더 펼치지 않고 고리를 계속 돌리기 때문이다.

    🔴 **돌려준 결과가 가능한 모든 전개가 아니다.** 예산 · 지원 범위 ·
    선택 생략이 모두 남은 길을 가린다.
    """

    goal: FieldGoal
    budget: SearchBudget
    termination: Termination
    results: "tuple[PathResult, ...]" = ()
    search_exhausted: bool = False
    """지정된 범위를 **끝까지** 펼쳤는가 (예산에 걸리지 않고 스택이 비었는가)."""
    budget_hit: tuple[str, ...] = ()
    """
    **탐색** 쪽에서 걸린 예산 칸만 (Phase 6-AJ §A-9).

    🔴 **재생 쪽 칸을 여기 담지 않는다** — 담으면 "재생 시간이 끝났다" 가
    "탐색 범위를 끝까지 펼치지 못했다" 로 읽힌다. 재생 쪽은
    :attr:`rerun_budget_hit` 이고, 두 사유는 섞지 않는다.
    """
    rerun_budget_hit: tuple[str, ...] = ()
    """**재생** 쪽에서 걸린 예산 칸만 (:class:`RerunDeadline`)."""
    duplicate_results: int = 0
    """같은 결과에 닿아 **대표로 합친** 경로의 총수."""
    nodes_expanded: int = 0
    deepest: int = 0
    choice_branches: int = 0
    choice_plans: int = 0
    choice_offers_truncated: int = 0
    deduped: int = 0
    revisited: int = 0
    stale: int = 0
    search_seconds: float = 0.0
    rerun_seconds: float = 0.0
    """🔴 **탐색 소요와 따로** 적는다 — 둘을 합치면 어디에 시간이 갔는지 모른다."""
    unsupported: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    opponent_declined: tuple[str, ...] = ()
    opponent_blocked: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    rerun_notes: tuple[str, ...] = ()
    """재생을 **돌리지 못한** 결과와 그 이유 (재생 시간 상한 등)."""
    followup_notes: tuple[str, ...] = ()
    """
    후속 전개에서 **멈춘 자리와 이유** (Phase 6-AL). 🔴 "더 할 수 있는 것이
    없다" 로 뭉개지 않는다.
    """

    @property
    def found(self) -> int:
        return len(self.results)

    @property
    def verified_results(self) -> "tuple[PathResult, ...]":
        """🔴 **검증된 것만.** 비교표는 이것으로 만든다."""
        return tuple(result for result in self.results if result.verified)

    @property
    def failed_results(self) -> "tuple[PathResult, ...]":
        """재생을 돌렸는데 실패한 것 — 숨기지 않는다."""
        return tuple(
            result for result in self.results
            if result.rerun is not None and not result.verified
        )

    @property
    def unverified_results(self) -> "tuple[PathResult, ...]":
        """재생을 **시작하지 못한** 것 (시간 부족 · 재생 끔)."""
        return tuple(result for result in self.results if result.rerun is None)

    def results_in(self, *states: RerunState) -> "tuple[PathResult, ...]":
        """그 상태인 결과들만 (Phase 6-AJ §C)."""
        return tuple(
            result for result in self.results if result.rerun_state in states
        )

    @property
    def mismatched_results(self) -> "tuple[PathResult, ...]":
        """재생이 돌았지만 **어긋난** 것."""
        return self.results_in(RerunState.MISMATCHED)

    @property
    def errored_results(self) -> "tuple[PathResult, ...]":
        """**일반 실행 예외**로 멈춘 것 — 🔴 시간 초과와 다른 이유다."""
        return self.results_in(RerunState.ERRORED)

    @property
    def timed_out_results(self) -> "tuple[PathResult, ...]":
        """재생을 **시작했는데** 공유 마감을 넘긴 것."""
        return self.results_in(RerunState.TIMED_OUT)

    @property
    def not_started_results(self) -> "tuple[PathResult, ...]":
        """시간이 남지 않아 **시작조차 못 한** 것."""
        return self.results_in(RerunState.NOT_STARTED)

    @property
    def disabled_results(self) -> "tuple[PathResult, ...]":
        """``rerun=False`` 로 **끄고** 돌린 것."""
        return self.results_in(RerunState.DISABLED)

    @property
    def continues(self) -> bool:
        """**후속 전개 탐색 모드**로 돌았는가 (Phase 6-AL)."""
        return self.budget.continues

    @property
    def baselines(self) -> "tuple[PathResult, ...]":
        """**최초 목표 도달 기준점**들."""
        return tuple(one for one in self.results if one.is_baseline)

    @property
    def continued_results(self) -> "tuple[PathResult, ...]":
        """기준점에서 **후속 행동을 실제로 수행한** 후보들."""
        return tuple(one for one in self.results if not one.is_baseline)

    @property
    def verified_continued(self) -> "tuple[PathResult, ...]":
        """🔴 **재생 검증된 후속 후보만.**"""
        return tuple(one for one in self.continued_results if one.verified)

    @property
    def reached_first_goal(self) -> bool:
        """
        **최초 목표 도달이 있었는가.**

        🔴 후속 후보를 하나도 찾지 못해도 이 사실은 사라지지 않는다 (§4).
        """
        return bool(self.results)

    @property
    def tally(self) -> ResultTally:
        """
        상태별 집계 (Phase 6-AJ §C).

        🔴 **경로를 찾았다는 사실과 재생 검증을 마쳤다는 사실을 가른다** —
        :attr:`found` 는 앞의 것이고 이 집계가 뒤의 것이다. 재생이 실패해도
        :attr:`found` 는 줄지 않는다.
        """
        counts = {state: 0 for state in RerunState}
        for result in self.results:
            counts[result.rerun_state] += 1
        return ResultTally(
            verified=counts[RerunState.VERIFIED],
            mismatched=counts[RerunState.MISMATCHED],
            errored=counts[RerunState.ERRORED],
            timed_out=counts[RerunState.TIMED_OUT],
            not_started=counts[RerunState.NOT_STARTED],
            disabled=counts[RerunState.DISABLED],
        )

    @property
    def reached(self) -> bool:
        return bool(self.results)

    @property
    def hit_result_cap(self) -> bool:
        """결과 수 상한에 닿아 멈췄는가."""
        return any("max_results=" in line for line in self.budget_hit)

    @property
    def skipped_choices(self) -> bool:
        return self.choice_offers_truncated > 0

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [
            f"제한 탐색 (복수 결과) — 목표: {self.goal.describe_ko()}",
            f"  종료(탐색): {self.termination.value}"
            + (f" ({' · '.join(self.budget_hit)})" if self.budget_hit else ""),
            "  종료(재생): "
            + (" · ".join(self.rerun_budget_hit) or "예산에 걸리지 않음"),
            f"  범위를 끝까지 펼쳤는가: {self.search_exhausted}",
            f"  찾은 결과 {self.found}개 ({self.tally.describe_ko()}) ·"
            f" 대표로 합친 경로 {self.duplicate_results}개",
            f"  예산: {self.budget.describe_ko()}",
            f"  펼친 노드 {self.nodes_expanded} · 최대 깊이 {self.deepest}"
            f" · 탐색 {self.search_seconds:.2f}초 · 재생"
            f" {self.rerun_seconds:.2f}초",
        ]
        for result in self.results:
            lines.append(result.describe_ko())
        for label, notes in (
            ("범위 밖", self.out_of_scope),
            ("미지원", self.unsupported),
            ("상대 정책", self.opponent_declined),
            ("상대 자리에서 멈춤", self.opponent_blocked),
            ("재생 메모", self.rerun_notes),
            ("후속 전개 메모", self.followup_notes),
            ("🔴 오류", self.errors),
        ):
            for note in notes:
                lines.append(f"  {label}: {note}")
        return "\n".join(lines)


# ======================================================================
# 자원 요약 — **값으로** 떠 둔다 (Phase 6-AI)
# ======================================================================
#: 자기 자리에서 **내용까지** 적는 존.
OWN_DETAIL_ZONES: tuple[Zone, ...] = (
    Zone.HAND, Zone.MZONE, Zone.EMZONE, Zone.SZONE,
    Zone.FZONE, Zone.PZONE, Zone.GRAVE, Zone.REMOVED,
)
#: 자기 자리에서 **장수만** 적는 존. 🔴 덱의 순서는 입력에 없고
#: (``build_opening`` 의 설명) 엑스트라 덱의 내용은 레시피가 말한다 —
#: 둘 다 "이 전개가 남긴 것" 이 아니라 입력이므로 장수만 적는다.
OWN_COUNT_ZONES: tuple[Zone, ...] = (Zone.DECK, Zone.EXTRA)
#: 상대 자리에서 **내용까지** 적는 존 — 공개된 자리뿐이다.
THEIR_DETAIL_ZONES: tuple[Zone, ...] = (
    Zone.MZONE, Zone.EMZONE, Zone.SZONE,
    Zone.FZONE, Zone.PZONE, Zone.GRAVE, Zone.REMOVED,
)
#: 상대 자리에서 **장수만** 적는 존. 🔴 **가려진 정보를 지어내지 않는다.**
THEIR_COUNT_ZONES: tuple[Zone, ...] = (Zone.HAND, Zone.DECK, Zone.EXTRA)

#: 상대 필드의 **뒷면** 카드를 적을 때 쓰는 자리 표시.
CONCEALED_CARD: None = None


@dataclass(frozen=True, slots=True)
class CardSlot:
    """
    한 칸에 있는 카드 하나. **값뿐이다.**

    🔴 :attr:`card_id` 가 ``None`` 이면 **그 자리가 가려져 있다** — 상대
    필드의 뒷면 카드다. 없는 것이 아니라 **모르는 것**이고, 그 구분을
    없애면 보고가 상대의 정체를 아는 척하게 된다.

    🔴 **개체를 합치지 않는다.** 같은 이름의 두 장, 토큰, 앞뒷면, 표시
    형식이 모두 따로 남는다 — 그 차이가 전개의 차이다.
    """

    instance: int
    card_id: "int | None"
    face_up: bool
    position: str
    sequence: int = 0

    @property
    def concealed(self) -> bool:
        return self.card_id is CONCEALED_CARD

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        what = "가려짐" if self.concealed else f"[{self.card_id}]"
        return f"#{self.instance} {what} {self.position}"


@dataclass(frozen=True, slots=True)
class ZoneSummary:
    """존 하나의 요약. :attr:`counted_only` 면 :attr:`cards` 가 비어 있다."""

    seat: int
    zone: str
    size: int
    cards: "tuple[CardSlot, ...]" = ()
    counted_only: bool = False

    @property
    def card_ids(self) -> "tuple[int | None, ...]":
        return tuple(card.card_id for card in self.cards)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        if self.counted_only:
            return f"P{self.seat} {self.zone} {self.size}장 (장수만)"
        inside = " · ".join(card.describe_ko() for card in self.cards) or "없음"
        return f"P{self.seat} {self.zone} {self.size}장: {inside}"


@dataclass(frozen=True, slots=True)
class UseRecord:
    """
    엔진에 **기록된** 사용 제한 하나.

    🔴 **"쓰지 않았다" 를 "쓸 수 있다" 로 읽지 않는다.** 이 기록은 무엇이
    이미 쓰였는지만 말한다 — 지금 발동할 수 있는지도, 다음 턴에 쓸 수
    있는지도 말하지 않는다 (그 판정은 ``legal_actions`` 의 일이다).
    """

    kind: str
    """``effect`` · ``card`` · ``card_name`` · ``summon`` · ``rule``."""
    label: str
    count: int
    seat: "int | None" = None

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return f"{self.kind} {self.label} ×{self.count}"


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    """
    한 성공 결과의 **실제 남은 자원** — 값으로만 이루어져 있다.

    🔴 **살아 있는 ``Duel`` 을 들고 있지 않다.** 들고 있으면 그 뒤의 탐색이
    그 판을 더 밟았을 때 요약이 조용히 달라진다. :func:`summarize_resources`
    가 **그 자리에서** 값을 뜨고, 이 객체는 그 뒤로 변하지 않는다 (frozen).

    🔴 **평가하지 않는다.** 점수도 총점도 없고, 어느 쪽이 나은지도 적지
    않는다 — 어떤 자원이 어디에 남았는지만 적는다.
    """

    seat: int
    turn_number: int
    phase: str
    state_hash: str
    zones: "tuple[ZoneSummary, ...]"
    uses: "tuple[UseRecord, ...]"
    normal_summon_used: bool
    """그 자리의 **일반 소환권**을 이 턴에 썼는가 (세트와 함께 쓰는 권리다)."""

    def zone(self, seat: int, zone) -> "ZoneSummary | None":
        wanted = zone.value if hasattr(zone, "value") else str(zone)
        for summary in self.zones:
            if summary.seat == seat and summary.zone == wanted:
                return summary
        return None

    def size(self, seat: int, zone) -> int:
        found = self.zone(seat, zone)
        return 0 if found is None else found.size

    def card_ids(self, seat: int, zone) -> "tuple[int | None, ...]":
        found = self.zone(seat, zone)
        return () if found is None else found.card_ids

    @property
    def own_field(self) -> "tuple[CardSlot, ...]":
        """자신의 몬스터 존 + 엑스트라 몬스터 존."""
        out: list[CardSlot] = []
        for zone in FIELD_ZONES:
            found = self.zone(self.seat, zone)
            if found is not None:
                out.extend(found.cards)
        return tuple(out)

    @property
    def own_field_rows(self) -> "tuple[tuple[str, int, bool], ...]":
        """
        :func:`own_field` 와 **같은 모양** — ``(존, 카드 ID, 앞면인가)``.

        재생이 돌려주는 ``RerunResult.final_field`` 와 바로 견주려고 둔다.
        """
        rows: list[tuple[str, int, bool]] = []
        for zone in FIELD_ZONES:
            found = self.zone(self.seat, zone)
            if found is None:
                continue
            for card in found.cards:
                rows.append((found.zone, card.card_id, card.face_up))
        return tuple(rows)

    @property
    def their_field(self) -> "tuple[CardSlot, ...]":
        out: list[CardSlot] = []
        for zone in (Zone.MZONE, Zone.EMZONE, Zone.SZONE):
            found = self.zone(1 - self.seat, zone)
            if found is not None:
                out.extend(found.cards)
        return tuple(out)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        lines = [
            f"P{self.seat} T{self.turn_number} {self.phase} "
            f"해시 {self.state_hash[:12]}… "
            f"일반 소환권 {'씀' if self.normal_summon_used else '안 씀'}"
        ]
        lines.extend(f"  {summary.describe_ko()}" for summary in self.zones)
        if self.uses:
            lines.append("  사용 제한: " + " · ".join(
                record.describe_ko() for record in self.uses
            ))
        return "\n".join(lines)


def _slots_of(container, *, concealed: bool) -> "tuple[CardSlot, ...]":
    """그 존의 카드들을 값으로. ``concealed`` 면 뒷면의 정체를 적지 않는다."""
    out: list[CardSlot] = []
    for card in container.cards():
        face_up = bool(card.is_faceup)
        out.append(
            CardSlot(
                instance=card.instance_id.value,
                card_id=(
                    card.card_id if face_up or not concealed else CONCEALED_CARD
                ),
                face_up=face_up,
                position=card.position.value,
                sequence=card.sequence,
            )
        )
    return tuple(out)


def _use_records(state, turn_number: int) -> "tuple[UseRecord, ...]":
    """
    엔진이 **기록한** 사용 제한 전부 — 효과 · 카드 · 카드명 · 소환 · 규칙.

    🔴 **세는 것을 지어내지 않는다.** 등록부가 들고 있는 항목만 옮긴다.
    """
    from engine.state.rule_usage import RuleActionKind

    records: list[UseRecord] = []
    uses = state.uses
    for (player, card_id, ordinal), count in sorted(uses.per_effect.items()):
        records.append(UseRecord(
            kind="effect", label=f"{card_id}:e[{ordinal}]", count=count,
            seat=player,
        ))
    for (player, instance), count in sorted(uses.per_card.items()):
        records.append(UseRecord(
            kind="card", label=f"#{instance}", count=count, seat=player,
        ))
    for (player, card_id), count in sorted(uses.per_card_name.items()):
        records.append(UseRecord(
            kind="card_name", label=f"[{card_id}]", count=count, seat=player,
        ))
    for player, card_id, summon, count in state.summon_uses.entries(turn_number):
        records.append(UseRecord(
            kind="summon", label=f"[{card_id}] {summon}", count=count,
            seat=player,
        ))
    for player in (0, 1):
        for action in RuleActionKind:
            if action is RuleActionKind.NORMAL_SUMMON:
                count = state.rule_uses.count(turn_number, player, action)
                if count:
                    records.append(UseRecord(
                        kind="rule", label=action.value, count=count,
                        seat=player,
                    ))
    return tuple(records)


def summarize_resources(duel: Duel, seat: int) -> ResourceSummary:
    """
    그 판의 자원을 **값으로** 뜬다 (Phase 6-AI §3).

    🔴 **가려진 정보를 지어내지 않는다.** 상대의 패 · 덱 · 엑스트라 덱은
    **장수만** 적고, 상대 필드의 뒷면 카드는 정체를 적지 않는다
    (:data:`CONCEALED_CARD`). 입력에 없는 것을 평가하지 않는다는 규율이
    요약에도 그대로 적용된다.

    🔴 **그 자리에서 뜬다.** 돌려주는 것은 불변 값이므로, 이 뒤에 그 판을
    더 밟아도 요약은 변하지 않는다.
    """
    from engine.state.rule_usage import RuleActionKind

    state = duel.state
    turn_number = state.turn.turn_number
    zones: list[ZoneSummary] = []
    for player in state.players:
        mine = player.player_id == seat
        detail = OWN_DETAIL_ZONES if mine else THEIR_DETAIL_ZONES
        counted = OWN_COUNT_ZONES if mine else THEIR_COUNT_ZONES
        for zone, container in sorted(
            player.zones.items(), key=lambda item: item[0].value
        ):
            if zone in detail:
                zones.append(ZoneSummary(
                    seat=player.player_id,
                    zone=zone.value,
                    size=len(container),
                    cards=_slots_of(container, concealed=not mine),
                ))
            else:
                #: 🔴 **분류하지 않은 존도 빠뜨리지 않는다** — 장수만 적는다.
                #: ``counted`` 에 적어 둔 존이 그 길로 오고, 거기에 없는
                #: 존(앞으로 생기는 존)도 **조용히 사라지지 않는다**.
                assert zone in counted or zone not in detail
                zones.append(ZoneSummary(
                    seat=player.player_id,
                    zone=zone.value,
                    size=len(container),
                    counted_only=True,
                ))
    return ResourceSummary(
        seat=seat,
        turn_number=turn_number,
        phase=state.turn.phase.value,
        state_hash=state.state_hash(),
        zones=tuple(zones),
        uses=_use_records(state, turn_number),
        normal_summon_used=state.rule_uses.used(
            turn_number, seat, RuleActionKind.NORMAL_SUMMON
        ),
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


def outcome_key(duel: Duel, legal, seat: int) -> tuple:
    """
    두 **성공 결과**를 같은 것으로 볼 수 있는가 (Phase 6-AI §2).

    🔴 **:func:`node_key` 와 목적이 다르다.** 그쪽은 *탐색 도중에* 같은
    자리를 두 번 펼치지 않으려는 것이고 (그래서 체인 중에는 ``None`` 을
    돌려주어 **합치지 않는다**), 이쪽은 *사용자에게 보여 줄* 서로 다른
    결과를 세는 것이다. 그래서 계약이 다르다 —

    =====================  ===============================================
    ``node_key``           체인 중이면 ``None`` (병합 불가). 깊이는 값으로
                           따로 들고 있는다 (:func:`admit`)
    ``outcome_key``        **언제나 열쇠를 돌려준다.** 목표는 *정리된*
                           자리에서만 성립하므로 (``_is_settled``) 체인
                           중인 성공 결과가 없다
    =====================  ===============================================

    무엇이 들어가는가 — ``GameState.canonical_state`` 가 §2 가 요구한 것을
    이미 함께 센다: **양쪽 플레이어의 카드 위치와 상태** (패 · 덱 ·
    엑스트라 · 묘지 · 제외 · 필드 배치 · 표시 형식 · 토큰) · **사용한
    효과·소환 제한** (``uses`` · ``rule_uses`` · ``summon_uses``) · **턴**.
    그 위에 흐름 위의 자리와 **허용 후보 집합**을 더한다 — 후자가 "후속
    행동을 바꿀 수 있는 엔진 상태" 를 그 자리에서 보이는 만큼 담는다
    (지나간 사건 중 아직 쓸 수 있는 유발이 그 목록에 오른다).

    🔴 **카드 장수나 카드명 목록만 같다는 이유로 합치지 않는다.** 열쇠의
    바탕이 ``state_hash`` 이므로 개체 위치 · 표시 형식 · 사용 제한이 모두
    들어간다 — **필드가 같아도 사용 제한이 다르면 다른 결과**다.

    🔴 **안전하게 같다고 말할 수 없으면 별개로 둔다.** 이 열쇠는 보수적인
    쪽으로 기운다 (합치기보다 가른다). 그래서 **중복이 일부 남을 수 있고**,
    개체 ID 를 지우는 공격적인 정규화는 이번에 넣지 않았다 — 그 한계는
    보고서 §2 에 적었다.
    """
    settled, why = _is_settled(duel, seat, legal)
    if not settled:
        raise BoundedSearchError(
            f"정리되지 않은 자리를 성공 결과로 셀 수 없습니다: {why}"
        )
    return (
        duel.state.state_hash(),
        duel.to_act,
        duel.step.value,
        duel.priority.window.value,
        frozenset(repr(action.canonical_state()) for action in legal.allowed),
    )


def representative_order(path: "tuple[PathStep, ...]") -> tuple:
    """
    같은 결과에 닿은 경로들 중 **대표를 고르는 결정론적 기준** (§2).

    1. **행동 수가 적은 것** 먼저.
    2. 동률이면 **행동 열쇠의 글자 순서**.
    3. 그래도 동률이면 **해결 중 선택의 글자 순서**.

    🔴 **"발견한 경로 중 대표" 다.** 전체 최단 경로를 보장하지 않는다 —
    탐색이 그 결과에 닿는 모든 경로를 보았다는 주장이 아니다.

    🔴 **점수가 아니다.** 행동 수가 적다고 더 강한 전개가 아니고, 이 순서를
    전개의 강약으로 읽어서는 안 된다. 같은 결과 안에서 **어느 기록을
    보여 줄지** 고르는 데만 쓴다.
    """
    return (
        len(path),
        tuple(repr(step.action_key) for step in path),
        tuple(
            repr(ask.chosen) for step in path for ask in step.choices
        ),
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
    timed_out: bool = False
    """
    **공유 재생 마감을 넘겨** 필수 걸음 도중에 멈췄는가 (Phase 6-AJ §A).

    🔴 :attr:`blocked` 와 다른 사실이다 — 막힌 것이 아니라 **시간이 끝난**
    것이다. 섞으면 "후보가 없어 멈췄다" 로 읽힌다.
    """


def _settle(duel: Duel, seat: int, *,
            deadline: "RerunDeadline | None" = None) -> _Settled:
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

    ``deadline`` 을 주면 **고리의 첫머리**에서 마감을 본다 (Phase 6-AJ §A).
    🔴 **안전한 경계다** — 엔진에 들어간 ``apply`` 하나를 중간에서 끊지
    않고, 다음 필수 걸음을 **시작하지 않는 것**으로 멈춘다. 주지 않으면
    기본 동작은 6-AI 와 한 글자도 다르지 않다.
    """
    forced: list[str] = []
    declined: list[str] = []
    blocked: list[str] = []
    met: list[tuple[int, object]] = []
    ran_out = False
    for _ in range(SETTLE_GUARD):
        #: 🔴 **필수 처리 반복의 안전한 경계** — 다음 필수 걸음을 시작하기
        #: 전에 마감을 본다. 돌고 있는 ``apply`` 를 끊지는 않는다.
        if deadline is not None and deadline.expired():
            ran_out = True
            break
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
        timed_out=ran_out,
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
    reached_at: int = 0
    """목표에 **처음** 도달한 걸음(1부터). 0 이면 아직 닿지 않았다 (6-AL)."""
    followups: int = 0
    """기준점 뒤에 수행한 **비흐름 행동** 수 (6-AL)."""


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
    results: list = field(default_factory=list)
    """
    모은 **서로 다른 성공 결과**들 — ``(경로, 자원 요약, 판정 이유)`` (6-AI).

    🔴 **판을 들고 있지 않다.** 요약을 그 자리에서 값으로 뜨므로, 뒤의
    탐색이 무엇을 하든 이 목록은 변하지 않는다.
    """
    result_keys: dict = field(default_factory=dict)
    """:func:`outcome_key` → :attr:`results` 의 자리. 중복을 합치는 열쇠다."""
    duplicate_results: int = 0
    """같은 결과에 닿아 **대표로 합친** 경로 수. 🔴 결과 수를 늘리지 않는다."""
    result_dups: dict = field(default_factory=dict)
    """:attr:`results` 의 자리 → 그 결과에 닿은 **다른 경로**의 수."""
    result_meta: dict = field(default_factory=dict)
    """
    :attr:`results` 의 자리 → :class:`FoundMeta` (Phase 6-AL).

    🔴 **결과 목록의 모양을 바꾸지 않고** 후속 이력을 따로 든다 — 기존
    재생 고리와 시험이 쓰는 ``(경로, 요약, 이유)`` 모양이 그대로 남는다.
    """
    followup_notes: list = field(default_factory=list)
    """
    후속 전개에서 **멈춘 자리와 이유** (Phase 6-AL). 🔴 "더 할 수 있는 것이
    없다" 로 뭉개지 않는다.
    """
    rerun_notes: list = field(default_factory=list)
    """재생을 **돌리지 못한** 결과와 그 이유. 🔴 실패를 숨기지 않는다."""
    rerun_budget_hit: list = field(default_factory=list)
    """
    **재생** 쪽에서 걸린 예산 칸 (6-AI).

    🔴 **탐색 예산과 한 통에 담지 않는다.** 담으면 재생 시간 상한에 걸린
    것이 "탐색을 끝까지 펼치지 못했다" 로 읽힌다 — 그 둘은 다른 사실이다.
    보고에는 두 묶음을 합쳐 적고, "범위를 끝까지 펼쳤는가" 는 탐색 쪽만
    본다 (:meth:`BoundedSearch._many_outcome`).
    """
    stack_emptied: bool = False
    """
    고리가 **스택이 비어서** 끝났는가 (6-AI).

    🔴 **"찾은 결과가 있다" 와 다른 사실이다.** 이것이 거짓이면 예산이나
    결과 상한이 고리를 끊은 것이고, 그때 돌려준 결과는 **가능한 모든
    전개가 아니다.**
    """
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

    def count_of(self, role) -> int:
        """그 역할의 결과가 몇 개인가 (Phase 6-AL)."""
        return sum(
            1 for meta in self.result_meta.values() if meta.role is role
        )

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

        #: 🔴 **사본이 선택 정책을 받는지 먼저 확인한다** (:meth:`_probe_chooser`).
        self._probe_chooser(duel, ledger)

        root = _Node(Simulator(duel), (), 0)
        termination, found = self._drive(root, ledger, started)

        #: 🔴 **종료 사유는 고리가 확정한다** (:meth:`_classify`).

        #: 🔴 **진짜 판이 그대로인지 확인한다** (:meth:`_assert_untouched`).
        self._assert_untouched(duel, root_hash, root_draws)

        if found is not None:
            path, final, verdict = found
            return self._outcome(
                termination, ledger, path, final, verdict, started
            )
        return self._outcome(
            termination, ledger, (), duel, self.goal.judge(duel), started
        )

    # ------------------------------------------------------------------
    def run_many(
        self,
        duel: Duel,
        *,
        rerun_from: "Duel | None" = None,
        rerun: bool = True,
        deadline: "RerunDeadline | None" = None,
    ) -> MultiSearchOutcome:
        """
        목표에 닿는 **서로 다른 결과 여럿**을 예산 안에서 모은다 (6-AI §1).

        🔴 **복수 결과 수집을 위한 별도 탐색기를 복사해 만들지 않았다.**
        펼치는 고리는 :meth:`_drive` **하나**이고, 단일 결과 모드와 같은
        :meth:`_open` · :func:`admit` · :func:`superseded` ·
        :meth:`_attempts` · :meth:`_apply_once` 를 지난다. 이 메서드가
        더하는 것은 셋뿐이다 — (1) 목표에 닿은 자리를 값으로 모아 두고
        (:meth:`_collect`) **그 분기를 더 펼치지 않는 것**, (2) 결과 수
        상한, (3) 탐색이 **끝난 뒤** 모은 결과를 재생하는 것
        (:meth:`rerun_results`).

        🔴 **목표를 달성한 분기는 더 펼치지 않는다.** 그래서 "같은 경로에서
        목표 달성 뒤 세트만 더 한 결과" 가 별개의 전개로 늘지 않는다.

        🔴 **"찾은 결과가 있음" 과 "탐색을 끝까지 수행함" 을 가른다.**
        앞의 것은 :attr:`MultiSearchOutcome.reached`, 뒤의 것은
        :attr:`MultiSearchOutcome.search_exhausted` 다. 결과 수 상한에
        걸렸으면 종료 사유에 ``max_results=`` 가 남는다.

        🔴 **돌려준 결과가 가능한 모든 전개라는 말이 아니다.** 깊이 · 노드 ·
        시간 · 선택 분기 · 결과 수 상한이 모두 남은 길을 가리고, 미지원
        후보와 확인하지 못한 선택 대안도 그렇다.

        🔴 **예산이 끝나도 찾은 결과는 보존한다** — 상한에 걸려 멈춘
        탐색도 그때까지 모은 결과를 그대로 돌려준다.

        ``rerun_from`` 은 재생을 돌릴 **새 초기 상태**다 (§5). 같은 입력으로
        다시 만든 듀얼을 넘기는 자리이고, 주지 않으면 받은 ``duel`` 에서
        사본을 떠서 돈다 — 탐색은 원본을 밟지 않으므로 (:meth:`_assert_untouched`)
        그것도 초기 상태이지만, **입력에서 다시 조립한 판**이 더 센 검증이다.

        ``rerun=False`` 면 재생을 돌리지 않고 그 사실을 적는다 — 🔴 그때
        결과는 하나도 :attr:`PathResult.verified` 가 아니고, 상태는
        :attr:`RerunState.DISABLED` 다 (시간이 없어 못 한 것과 가른다).

        ``deadline`` 은 Phase 6-AJ 가 더한 자리다 — 주지 않으면 예산에서
        **공유 마감** 하나를 만들어 모든 결과가 돌려 쓴다.
        """
        if not isinstance(duel, Duel):
            raise BoundedSearchError(f"Duel 이 필요합니다: {type(duel).__name__}")
        if rerun_from is not None and not isinstance(rerun_from, Duel):
            raise BoundedSearchError(
                f"재생할 Duel 이 필요합니다: {type(rerun_from).__name__}"
            )
        if not self.budget.many:
            raise BoundedSearchError(
                "복수 결과 모드는 max_results 가 2 이상일 때만 돕니다 "
                f"(지금 {self.budget.max_results}) — 단일 결과는 run() 입니다."
            )
        started = time.monotonic()
        ledger = _Ledger()
        root_hash = duel.state.state_hash()
        root_draws = duel.state.randomness.draws

        verdict = self.goal.judge(duel)
        if verdict.reached:
            #: 🔴 **뿌리가 이미 목표다** — 밟을 걸음이 없으므로 재생할 경로도
            #: 없다. 그 사실을 적고 **결과 없이** 돌려준다. 걸음 0개를
            #: "서로 다른 전개 한 가지" 로 세지 않는다.
            ledger.note(
                ledger.out_of_scope,
                f"받은 판이 이미 목표를 만족합니다 ({verdict.reason}) — "
                "전개 경로가 없습니다.",
            )
            return self._many_outcome(
                Termination.GOAL_REACHED, ledger, 0.0, 0.0
            )

        #: 🔴 **사본이 선택 정책을 받는지 먼저 확인한다** (:meth:`_probe_chooser`).
        self._probe_chooser(duel, ledger)

        root = _Node(Simulator(duel), (), 0)
        termination, _found = self._drive(root, ledger, started)
        search_seconds = time.monotonic() - started

        #: 🔴 **진짜 판이 그대로인지 확인한다** (:meth:`_assert_untouched`).
        self._assert_untouched(duel, root_hash, root_draws)

        rerun_started = time.monotonic()
        if not rerun:
            ledger.note(
                ledger.rerun_notes,
                "재생을 돌리지 않았습니다 (rerun=False) — 🔴 어떤 결과도 "
                "검증되지 않았습니다.",
            )
            results = tuple(
                PathResult(
                    index=slot + 1,
                    path=path,
                    resources=summary,
                    goal_reason=reason,
                    duplicates=ledger.result_dups.get(slot, 0),
                    #: 🔴 **끈 것과 시간이 없어 못 한 것을 가른다** (§C).
                    rerun_disabled=True,
                    meta=ledger.result_meta.get(slot, FoundMeta()),
                )
                for slot, (path, summary, reason) in enumerate(ledger.results)
            )
        else:
            results = self.rerun_results(
                duel if rerun_from is None else rerun_from, ledger,
                deadline=deadline,
            )
        rerun_seconds = time.monotonic() - rerun_started
        #: 🔴 **탐색 소요와 재생 소요를 따로 적는다** — 합치면 어디에 시간이
        #: 갔는지 알 수 없다 (§5).
        return self._many_outcome(
            termination, ledger, search_seconds, rerun_seconds, results
        )

    # ------------------------------------------------------------------
    def rerun_results(
        self, duel: Duel, ledger: _Ledger, *,
        deadline: "RerunDeadline | None" = None,
    ) -> "tuple[PathResult, ...]":
        """
        모은 결과를 **새 초기 상태에서 하나씩 다시 밟는다** (6-AI §5).

        🔴 **탐색이 끝난 뒤에 돈다.** :meth:`_collect` 가 더 짧은 경로를
        보면 대표를 교체하므로, 중간에 재생하면 교체된 대표가 검증되지 않은
        채 보고된다. 이 자리에서 돌면 **사용자에게 제시하는 최종 대표**가
        검증된 것이 된다.

        🔴 **받은 ``duel`` 은 탐색에 쓴 것과 같은 입력이다.**
        :func:`rerun_steps` 가 거기서 :class:`Simulator` 사본을 새로 떠서
        걸음을 밟으므로, 원본은 그대로 남는다 (:meth:`_assert_untouched` 가
        탐색 직후 이미 확인했다).

        🔴 **모든 결과가 마감 하나를 돌려 쓴다** (Phase 6-AJ §A,
        :class:`RerunDeadline`). :attr:`SearchBudget.max_rerun_seconds` 는
        **재생 전체**의 상한이고, 결과마다 새로 시작하지 않는다. 마감은
        결과를 시작하기 전뿐 아니라 :func:`rerun_steps` 안의 행동 전후 ·
        필수 걸음 경계 · 최종 검증 뒤에서도 본다.

        🔴 **시작하지 못한 결과와 도중에 넘긴 결과를 가른다** —
        :attr:`RerunState.NOT_STARTED` 와 :attr:`RerunState.TIMED_OUT` 이고,
        둘 다 검증으로 세지 않는다. 그때까지 **시간 안에 검증된 결과와
        탐색이 찾은 경로는 그대로 보존한다.**

        🔴 **하나가 실패해도 다른 결과를 버리지 않는다** (§B). 일반 실행
        예외도 그 결과의 실패로만 적히고 (:meth:`_rerun_one`), 남은 예산이
        있으면 다음 결과를 **새 초기 상태에서** 계속 검증한다.

        ``deadline`` 은 시험이 **제어 가능한 단조 시계**를 꽂는 자리다 —
        주지 않으면 예산에서 만들어 쓴다.
        """
        if deadline is None:
            #: 🔴 **하나를 만들어 모든 결과가 돌려 쓴다** — 결과마다 예산을
            #: 새로 시작하면 "전체 N초" 가 "결과마다 N초" 가 된다.
            deadline = RerunDeadline(self.budget.max_rerun_seconds)
        elif not isinstance(deadline, RerunDeadline):
            raise BoundedSearchError(
                f"RerunDeadline 이 필요합니다: {type(deadline).__name__}"
            )
        out: list[PathResult] = []
        for slot, (path, summary, reason) in enumerate(ledger.results):
            index = slot + 1
            dups = ledger.result_dups.get(slot, 0)
            meta = ledger.result_meta.get(slot, FoundMeta())
            if deadline.expired():
                #: 🔴 **시작조차 하지 않았다** — 재생 도중 넘긴 것과 다른
                #: 사실이므로 ``rerun=None`` 으로 남긴다 (§C).
                self._note_rerun_budget(ledger, index, deadline)
                out.append(PathResult(
                    index=index,
                    path=path,
                    resources=summary,
                    goal_reason=reason,
                    duplicates=dups,
                    meta=meta,
                ))
                continue
            rerun, matched = self._rerun_one(
                duel, path, summary, index, ledger, deadline, meta
            )
            out.append(PathResult(
                index=index,
                path=path,
                resources=summary,
                goal_reason=reason,
                duplicates=dups,
                rerun=rerun,
                resources_match=matched,
                meta=meta,
            ))
        return tuple(out)

    # ------------------------------------------------------------------
    def _note_rerun_budget(
        self, ledger: _Ledger, index: int, deadline: "RerunDeadline"
    ) -> None:
        """재생 예산이 끊었다는 사실을 **재생 쪽 칸에** 적는다."""
        ledger.note(
            ledger.rerun_budget_hit,
            f"max_rerun_seconds={self.budget.max_rerun_seconds:g}",
        )
        ledger.note(
            ledger.rerun_notes,
            f"[결과 {index}] 재생을 **시작하지 못했습니다** — 공유 "
            f"{deadline.describe_ko()} 를 이미 넘겼습니다. 🔴 이 결과는 "
            "검증된 비교에 쓰지 않습니다 (경로 자체는 그대로 남습니다).",
        )

    # ------------------------------------------------------------------
    def _rerun_one(
        self,
        duel: Duel,
        path: "tuple[PathStep, ...]",
        summary: "ResourceSummary",
        index: int,
        ledger: _Ledger,
        deadline: "RerunDeadline",
        meta: "FoundMeta | None" = None,
    ) -> "tuple[RerunResult, bool]":
        """
        결과 **하나**를 재생하고 자원 요약까지 견준다 (Phase 6-AJ §B).

        🔴 **예외 경계는 결과 하나다.** 재생 · 최종 검증 · 자원 요약 비교가
        모두 이 안에서 돌고, 여기서 난 예외는 **그 결과의 실패**로 적힌다 —
        다음 결과는 **새 초기 상태**에서 계속 검증된다.

        🔴 **``BaseException`` 을 잡지 않는다.** ``except Exception`` 이므로
        :class:`KeyboardInterrupt` · :class:`SystemExit` ·
        :class:`GeneratorExit` · :class:`asyncio.CancelledError` 는 (셋
        모두 ``BaseException`` 의 직계다) **그대로 올라간다**. 종료와 취소
        신호를 결과 실패로 삼키면 멈추라는 말이 사라진다.

        🔴 **예외를 조용히 삼키지 않는다.** 형 이름과 단계를
        :attr:`RerunResult.error_type` · :attr:`RerunResult.stage` 에 적고
        :attr:`_Ledger.rerun_notes` 에도 남긴다. 성공 기본값으로 바꾸지
        않으며, "탐색이 아무것도 못 찾았다" · UNKNOWN · 정상 무효과 해결로
        바꾸지도 않는다.

        🔴 **실패한 재생의 중간 상태를 다음 결과에 물려주지 않는다.**
        :func:`rerun_steps` 가 받은 ``duel`` 에서 :class:`Simulator` 사본을
        새로 뜨고 원본은 밟지 않으므로, 다음 결과도 같은 초기 상태에서
        시작한다 (``test_b05`` 가 해시로 센다).
        """
        meta = FoundMeta() if meta is None else meta
        #: 🔴 **후속 후보만 최초 도달 지점을 따로 확인한다** (6-AL §2).
        #: 기준점은 최초 도달이 곧 최종 상태이므로 기존 검증과 같고, 그래서
        #: 첫 도달 모드의 동작은 한 글자도 달라지지 않는다.
        arrival = meta.reached_at if meta.continued else 0
        try:
            rerun = rerun_steps(
                duel,
                path,
                self.goal,
                expect_field=summary.own_field_rows,
                expect_hash=summary.state_hash,
                reached_at=arrival,
                deadline=deadline,
            )
            #: 🔴 **자원 요약까지 견준다.** 목표와 해시가 같아도 요약이
            #: 다르면 그 비교는 재생으로 뒷받침되지 않는다. 이 비교도 같은
            #: 경계 안에서 돈다 (§B-1).
            matched = rerun.ok and rerun.resources == summary
        except BoundedSearchError as error:
            #: 🔴 **재생 오류를 "탐색이 아무것도 못 찾았다" 로 바꾸지
            #: 않는다.** 그 결과에만 실패로 적는다.
            rerun = RerunResult(
                ok=False,
                reason=f"재생이 예외로 멈췄습니다: "
                       f"{type(error).__name__}: {error}",
                error_type=type(error).__name__,
                stage="재생 호출",
            )
            matched = False
        except Exception as error:  # noqa: BLE001 - 결과별 경계 (§B)
            rerun = RerunResult(
                ok=False,
                reason=f"재생이 일반 실행 예외로 멈췄습니다: "
                       f"{type(error).__name__}: {error}",
                error_type=type(error).__name__,
                stage="재생 호출",
            )
            matched = False
        #: 🔴 **재생이 돌아온 자리에서 다시 본다** (§A-5, 협력적 제한의
        #: 핵심). 재생 안에서 **하나의 긴 호출**이 마감을 넘겨 버리면 안에서는
        #: 끊을 수 없다 — 그 호출이 반환한 **즉시** 초과를 보고 **성공 처리를
        #: 막는다.** 이 자리가 없으면 "예산 1초인데 10초를 쓰고 검증 성공" 이
        #: 된다 (기준 코드의 재현이 그랬다).
        #:
        #: 🔴 **성공만 막는다.** 어긋남(불일치)과 예외는 우리가 **실제로 본**
        #: 사실이므로 시간 초과로 덮어쓰지 않는다 — 덮으면 "재현되지 않는
        #: 경로" 가 "시간이 없었다" 로 바뀐다.
        if rerun.ok and not rerun.timed_out and deadline.expired():
            rerun = dataclasses.replace(
                rerun,
                ok=False,
                timed_out=True,
                stage=rerun.stage or "재생 호출 뒤",
                reason=(
                    "재생은 끝났지만 돌아온 자리에서 공유 마감을 이미 "
                    f"넘겼습니다 ({deadline.describe_ko()}) — 🔴 검증 성공으로 "
                    "세지 않습니다. (협력적 제한이므로 돌고 있던 호출 하나는 "
                    "끊지 않았습니다.) 먼저 적힌 판정: " + rerun.reason
                ),
            )
            matched = False
        if rerun.error_type:
            ledger.note(
                ledger.rerun_notes,
                f"[결과 {index}] 🔴 재생이 예외로 멈췄습니다 "
                f"({rerun.error_type}, 단계 {rerun.stage or '알 수 없음'}) — "
                "이 결과만 실패로 적었고 다음 결과는 새 초기 상태에서 "
                "계속 검증했습니다.",
            )
        elif rerun.timed_out:
            self._note_rerun_timeout(ledger, index, rerun, deadline)
        elif rerun.ok and not matched:
            ledger.note(
                ledger.rerun_notes,
                f"[결과 {index}] 재생이 같은 판에 닿았지만 자원 요약이 "
                "탐색이 적어 둔 것과 다릅니다 — 검증된 비교에 쓰지 "
                "않습니다.",
            )
        return rerun, matched

    # ------------------------------------------------------------------
    def _note_rerun_timeout(
        self, ledger: _Ledger, index: int, rerun: "RerunResult",
        deadline: "RerunDeadline",
    ) -> None:
        """재생 **도중** 마감을 넘긴 결과를 적는다 — 미시작과 가른다."""
        ledger.note(
            ledger.rerun_budget_hit,
            f"max_rerun_seconds={self.budget.max_rerun_seconds:g}",
        )
        ledger.note(
            ledger.rerun_notes,
            f"[결과 {index}] ⚠️ 재생을 **시작했지만** 공유 마감을 넘겨 "
            f"{rerun.stage or '중간'} 에서 멈췄습니다 (걸음 {rerun.steps}개까지). "
            "🔴 검증 성공으로 세지 않습니다.",
        )

    # ------------------------------------------------------------------
    def _probe_chooser(self, duel: Duel, ledger: _Ledger) -> None:
        """
        사본이 **선택 정책을 받는지** 먼저 확인한다.

        받지 못하면 해결 중 선택이 사본 안에서 거절되고, 그 결과는 "목표에
        닿지 못했다" 로 보인다 — 그 둘을 섞지 않으려고 **사실을 적는다**
        (:data:`CHOICE_BRANCHING_UNAVAILABLE`, §4.4).
        """
        if self.budget.max_choice_branches and _chooser_of(duel) is not None:
            probe = Simulator(duel).fork(
                selector=ScriptedChoice((), FirstPermittedChoice(), name="probe")
            )
            if _chooser_of(probe) is None:
                ledger.note(ledger.out_of_scope, CHOICE_BRANCHING_UNAVAILABLE)

    @staticmethod
    def _assert_untouched(duel: Duel, root_hash: str, root_draws: int) -> None:
        """
        **진짜 판이 그대로인지** 확인한다.

        🔴 탐색이 원본을 밀면 그 결과는 분석이 아니라 사고다. 해시와 난수원
        소비량을 둘 다 본다 — 해시만 보면 ``project()`` 처럼 난수원을
        공유하는 사본이 조용히 지나간다.
        """
        if duel.state.state_hash() != root_hash:
            raise BoundedSearchError(
                "탐색이 원본 판을 바꿨습니다 — 사본에만 적용해야 합니다."
            )
        if duel.state.randomness.draws != root_draws:
            raise BoundedSearchError(
                "탐색이 원본의 난수원을 밀었습니다 — 사본에만 적용해야 합니다."
            )

    # ------------------------------------------------------------------
    def _many_outcome(
        self,
        termination: Termination,
        ledger: _Ledger,
        search_seconds: float,
        rerun_seconds: float,
        results: "tuple[PathResult, ...]" = (),
    ) -> MultiSearchOutcome:
        """
        복수 결과 모드의 결과를 **값으로** 묶는다.

        🔴 **"범위를 끝까지 펼쳤다" 는 네 가지가 모두 참일 때만이다** —
        스택이 비어서 끝났고, **탐색** 예산에 걸린 칸이 없고, 오류가 없고,
        **확인하지 못한 선택 대안도 없다.** 넷 중 하나라도 어긋나면 그
        탐색은 소진된 것이 아니다.

        🔴 **재생 쪽 예산은 이 판정에 넣지 않는다.** 재생 시간 상한에 걸린
        것은 "탐색을 끝까지 펼치지 못했다" 와 다른 사실이다 — Phase 6-AJ
        부터는 **칸도 따로 둔다**: 탐색 쪽은
        :attr:`MultiSearchOutcome.budget_hit`, 재생 쪽은
        :attr:`MultiSearchOutcome.rerun_budget_hit` 이고 섞지 않는다 (§A-9).
        """
        exhausted = (
            ledger.stack_emptied
            and not ledger.budget_hit
            and not ledger.errors
            and ledger.choice_offers_truncated == 0
        )
        return MultiSearchOutcome(
            goal=self.goal,
            budget=self.budget,
            termination=termination,
            results=tuple(results),
            search_exhausted=exhausted,
            #: 🔴 **두 사유를 섞지 않는다** (§A-9).
            budget_hit=tuple(ledger.budget_hit),
            rerun_budget_hit=tuple(ledger.rerun_budget_hit),
            duplicate_results=ledger.duplicate_results,
            nodes_expanded=ledger.nodes,
            deepest=ledger.deepest,
            choice_branches=ledger.choice_branches,
            choice_plans=ledger.choice_plans,
            choice_offers_truncated=ledger.choice_offers_truncated,
            deduped=ledger.deduped,
            revisited=ledger.revisited,
            stale=ledger.stale,
            search_seconds=search_seconds,
            rerun_seconds=rerun_seconds,
            unsupported=tuple(ledger.unsupported),
            out_of_scope=tuple(ledger.out_of_scope),
            opponent_declined=tuple(ledger.declined),
            opponent_blocked=tuple(ledger.blocked),
            errors=tuple(ledger.errors),
            rerun_notes=tuple(ledger.rerun_notes),
            followup_notes=tuple(ledger.followup_notes),
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
            if self.budget.many and self._results_full(ledger):
                #: 🔴 **결과 상한에 닿았다.** 그 사실을 종료 사유에 남긴다
                #: (:meth:`_open` 이 이미 적었다) — "다 찾았다" 가 아니다.
                break
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
        else:
            #: 🔴 스택이 **비어서** 끝났다 — 지정된 범위를 끝까지 펼쳤다.
            ledger.stack_emptied = True
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

    def _results_full(self, ledger: _Ledger) -> bool:
        """
        **제시할 결과**가 상한에 닿았는가 (Phase 6-AL §3).

        🔴 **기준점 보관과 후속 후보 보관의 역할이 다르다.** 후속 모드에서
        :attr:`SearchBudget.max_results` 는 **후속 후보**의 상한이고,
        기준점은 :attr:`SearchBudget.max_baselines` 가 따로 센다 — 한 칸에
        담으면 "기준점을 모으는 순간 결과 상한에 걸려 후속 행동을 전혀
        탐색하지 않는" 구조가 된다.
        """
        if not self.budget.continues:
            return len(ledger.results) >= self.budget.max_results
        return (ledger.count_of(ResultRole.CONTINUED)
                >= self.budget.max_results)

    def _followups_left(self, node: _Node) -> int:
        """그 노드에서 더 할 수 있는 **비흐름 후속 행동** 수."""
        return self.budget.max_followup_actions - node.followups

    def _dedup_key(self, duel: Duel, legal, *, reached_at: int,
                   followups: int):
        """
        중복 제거용 열쇠 (Phase 6-AL §3).

        🔴 **후속 모드에서는 목표 도달 이력과 남은 후속 예산을 함께 넣는다.**
        넣지 않으면 "같은 상태에 도착했다" 는 이유로 **더 많은 탐색 기회를
        가진 경로를 버린다** — 목표 전에 들른 상태와 목표 뒤에 들른 상태는
        할 수 있는 일이 다르고, 남은 후속 예산이 더 많은 쪽에서만 닿는
        결과가 있다.

        🔴 **그 대가로 중복 제거가 약해진다** — 같은 판이 남은 예산마다 다른
        노드가 된다. 그 한계를 보고서에 적는다.

        🔴 첫 도달 모드에서는 :func:`node_key` 그대로다 (한 글자도 다르지
        않다).
        """
        base = node_key(duel, legal)
        if base is None or not self.budget.continues:
            return base
        return base + (
            reached_at > 0,
            max(0, self.budget.max_followup_actions - followups),
        )

    def _key_of(self, node: _Node):
        """그 노드의 상태 열쇠. 후보 목록을 **다시 세지 않는다.**"""
        duel = node.sim.duel
        legal = (
            node.legal if node.legal is not None
            else duel.legal_actions(duel.to_act)
        )
        node.legal = legal
        return self._dedup_key(
            duel, legal,
            reached_at=node.reached_at, followups=node.followups,
        )

    # ------------------------------------------------------------------
    def _open(self, node: _Node, ledger: _Ledger, stack: list, started: float):
        """노드 하나를 펼친다. 목표를 찾으면 ``(경로, 판, 판정)``."""
        duel = node.sim.duel
        if duel.is_over:
            return None
        if node.depth >= self.budget.max_depth:
            ledger.note(ledger.budget_hit, f"max_depth={self.budget.max_depth}")
            if node.reached_at:
                #: 🔴 **후속 상한이 아니라 깊이 상한이 끊었다** — 두 상한을
                #: 섞으면 "후속을 다 봤다" 로 읽힌다 (§3).
                ledger.note(
                    ledger.followup_notes,
                    f"기준점(걸음 {node.reached_at}) 뒤에서 깊이 상한"
                    f" max_depth={self.budget.max_depth} 에 걸려 더 펼치지"
                    " 않았습니다 — 후속 행동 상한과 다른 상한입니다.",
                )
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
        #: 🔴 **상한은 새 비흐름 행동만 막는다** (Phase 6-AM §1).
        #:
        #: 6-AL 은 상한에 닿으면 이 자리에서 ``return None`` 했다. 그러면
        #: 마지막 허용 비흐름 행동 뒤에 **아직 처리할 유발 기회**가 남아
        #: 있을 때, 비용으로 세지 않는 **패스까지 막혀** 정리된 후속 후보가
        #: 누락됐다 — 실제로 필요한 비흐름 행동은 1회인데 상한 2를 줘야
        #: 결과가 나왔다.
        #:
        #: 🔴 **흐름 처리는 계속한다.** 그래도 ``end_phase`` 는 아래 고리가
        #: 그대로 건너뛰므로 **같은 턴 메인 페이즈 범위는 그대로**이고,
        #: 깊이 · 노드 · 시간 · 중복 제거 · 필수 처리 상한도 그대로 돈다.
        flow_only = bool(node.reached_at) and self._followups_left(node) <= 0
        if flow_only:
            ledger.note(
                ledger.budget_hit,
                f"max_followup_actions={self.budget.max_followup_actions}",
            )
            in_scope_flow = [
                action for action in legal.allowed
                if action.kind is not PlayerActionKind.END_PHASE
                and action.kind.value in FLOW_ACTION_KINDS
            ]
            settled_here, why_here = _is_settled(duel, self.goal.seat, legal)
            if not in_scope_flow:
                #: 🔴 **왜 멈추는지 적는다** (§1-H) — 정리되지 않은 채
                #: 멈췄는지, 이미 정리된 자리였는지를 가른다.
                ledger.note(
                    ledger.followup_notes,
                    f"기준점(걸음 {node.reached_at}) 뒤에서 비흐름 행동"
                    f" {node.followups}회로 상한"
                    f" max_followup_actions={self.budget.max_followup_actions}"
                    " 에 닿았고, 이번 범위에서 할 수 있는 흐름 처리(패스)가"
                    " 없어 여기서 멈췄습니다"
                    + ("." if settled_here
                       else f" — 🔴 아직 정리되지 않았습니다 ({why_here})."),
                )
                return None
            ledger.note(
                ledger.followup_notes,
                f"기준점(걸음 {node.reached_at}) 뒤에서 비흐름 행동"
                f" {node.followups}회로 상한"
                f" max_followup_actions={self.budget.max_followup_actions}"
                " 에 닿아 **새 비흐름 행동은 더하지 않고**, 엔진이 허가한"
                " 흐름 처리(패스)만 이어 갑니다 — 흐름 행동은 후속 행동"
                " 수에 세지 않습니다.",
            )

        ordered = sorted(legal.allowed, key=_order_key)
        children: list[_Node] = []
        for action in ordered:
            if action.kind is PlayerActionKind.END_PHASE:
                ledger.note(ledger.out_of_scope, OUT_OF_TURN_SCOPE)
                continue
            if flow_only and action.kind.value not in FLOW_ACTION_KINDS:
                #: 🔴 **새 비흐름 행동을 차단한다** (§1-A). 상한을 넘는
                #: 행동은 **적용하지도 않는다** — 노드를 만들지 않는다.
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
                child_depth = node.depth + 1
                flow = action.kind.value in FLOW_ACTION_KINDS

                if node.reached_at == 0 and verdict.reached:
                    #: ---------------- 최초 목표 도달 ----------------
                    if not self.budget.many:
                        #: 🔴 **단일 결과 모드는 한 글자도 달라지지 않는다.**
                        return path, child_duel, verdict
                    if not self.budget.continues:
                        #: 🔴 **첫 도달 모드 — 이 분기는 더 펼치지 않는다**
                        #: (6-AI §1). 비교하는 것은 "목표에 **처음** 도달하고
                        #: 처리가 정리된 상태" 이므로, 그 뒤에 세트만 더 한
                        #: 결과를 별개의 전개로 늘리지 않는다.
                        self._collect(ledger, path, child_duel, child_legal,
                                      verdict,
                                      FoundMeta(reached_at=child_depth,
                                                goal_kept=verdict.present))
                        if self._results_full(ledger):
                            ledger.note(
                                ledger.budget_hit,
                                f"max_results={self.budget.max_results}",
                            )
                            return None
                        continue
                    #: 🔴 **후속 모드 — 기준점으로 모으고 계속 펼친다** (6-AL).
                    if ledger.count_of(ResultRole.FIRST_ARRIVAL) >= \
                            self.budget.max_baselines:
                        ledger.note(
                            ledger.budget_hit,
                            f"max_baselines={self.budget.max_baselines}",
                        )
                        ledger.note(
                            ledger.followup_notes,
                            f"기준점 상한 max_baselines="
                            f"{self.budget.max_baselines} 에 닿아 걸음"
                            f" {child_depth} 의 최초 도달을 더 보관하지"
                            " 않았습니다 — 🔴 다른 기준점이 없다는 뜻이"
                            " 아닙니다.",
                        )
                        continue
                    self._collect(
                        ledger, path, child_duel, child_legal, verdict,
                        FoundMeta(reached_at=child_depth,
                                  goal_kept=verdict.present,
                                  stop=self._stop_of(child_legal, 0,
                                                     child_depth)),
                    )
                    if self.budget.dedup:
                        admitted = admit(
                            ledger.seen,
                            self._dedup_key(child_duel, child_legal,
                                            reached_at=child_depth,
                                            followups=0),
                            child_depth,
                        )
                        if admitted is Admission.DUPLICATE:
                            ledger.deduped += 1
                            continue
                        if admitted is Admission.SHALLOWER:
                            ledger.revisited += 1
                    children.append(_Node(
                        Simulator(child_duel), path, child_depth, child_legal,
                        reached_at=child_depth, followups=0,
                    ))
                    continue

                if node.reached_at:
                    #: ---------------- 기준점 뒤 ----------------
                    child_followups = node.followups + (0 if flow else 1)
                    settled, why = _is_settled(
                        child_duel, self.goal.seat, child_legal
                    )
                    if settled and child_followups >= 1:
                        #: 🔴 **정리된 결정 지점에서만 수집한다** (§4) — 중간
                        #: 상태를 결과로 내놓지 않는다. 흐름 행동만 한 자리는
                        #: 수집하지 않고(판이 그대로다) 계속 펼친다.
                        self._collect(
                            ledger, path, child_duel, child_legal, verdict,
                            FoundMeta(
                                role=ResultRole.CONTINUED,
                                reached_at=node.reached_at,
                                followup_actions=child_followups,
                                followup_flow=(
                                    len(path) - node.reached_at
                                    - child_followups
                                ),
                                goal_kept=verdict.present,
                                stop=self._stop_of(
                                    child_legal, child_followups, child_depth
                                ),
                            ),
                        )
                        if self._results_full(ledger):
                            ledger.note(
                                ledger.budget_hit,
                                f"max_results={self.budget.max_results}",
                            )
                            return None
                    elif not settled:
                        ledger.note(
                            ledger.followup_notes,
                            f"걸음 {child_depth} 뒤가 정리되지 않아 후속"
                            f" 후보로 세지 않았습니다 ({why}) — 계속"
                            " 펼칩니다.",
                        )
                    if child_followups >= self.budget.max_followup_actions:
                        #: 🔴 **상한에 닿았다는 사실만 적는다** (Phase 6-AM
                        #: §1). 6-AL 은 여기서 ``continue`` 해서 자식을 아예
                        #: 쌓지 않았고, 그래서 그 자리에 남은 **흐름 처리
                        #: (패스)** 가 영원히 실행되지 않았다. 지금은 쌓고,
                        #: 그 노드를 열 때 :meth:`_open` 의 ``flow_only``
                        #: 가 **새 비흐름 행동만** 막는다.
                        #:
                        #: 🔴 두 검사 자리를 **함께** 고쳤다 — 한쪽만 고치면
                        #: 다른 쪽이 같은 누락을 만든다.
                        ledger.note(
                            ledger.budget_hit,
                            "max_followup_actions="
                            f"{self.budget.max_followup_actions}",
                        )
                    if self.budget.dedup:
                        admitted = admit(
                            ledger.seen,
                            self._dedup_key(child_duel, child_legal,
                                            reached_at=node.reached_at,
                                            followups=child_followups),
                            child_depth,
                        )
                        if admitted is Admission.DUPLICATE:
                            ledger.deduped += 1
                            continue
                        if admitted is Admission.SHALLOWER:
                            ledger.revisited += 1
                    children.append(_Node(
                        Simulator(child_duel), path, child_depth, child_legal,
                        reached_at=node.reached_at,
                        followups=child_followups,
                    ))
                    continue

                #: ---------------- 목표 전 (기존 그대로) ----------------
                if self.budget.dedup:
                    verdict_on_key = admit(
                        ledger.seen,
                        self._dedup_key(child_duel, child_legal,
                                        reached_at=0, followups=0),
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

    def _stop_of(self, legal, followups: int, depth: int) -> ContinuationStop:
        """
        이 자리에서 **왜 멈추는가** (Phase 6-AL §4).

        🔴 **"더 할 수 있는 것이 없다" 로 단정하지 않는다.** 허가된 수가
        없어도 지원하지 않아 후보가 되지 못한 수가 남아 있으면
        :attr:`ContinuationStop.UNSUPPORTED_LEFT` 다.
        """
        if not self.budget.continues:
            return ContinuationStop.OPEN
        playable = [
            action for action in legal.allowed
            if action.kind is not PlayerActionKind.END_PHASE
        ]
        if not playable:
            held = list(legal.unsupported())
            return (ContinuationStop.UNSUPPORTED_LEFT if held
                    else ContinuationStop.NO_LEGAL)
        if followups >= self.budget.max_followup_actions:
            return ContinuationStop.ACTION_CAP
        if depth >= self.budget.max_depth:
            return ContinuationStop.DEPTH_CAP
        return ContinuationStop.OPEN

    def _collect(self, ledger: _Ledger, path, duel, legal, verdict,
                 meta: "FoundMeta | None" = None) -> None:
        """
        성공 결과 하나를 **값으로** 모은다 (6-AI §1 · §2).

        🔴 **같은 결과면 대표 하나로 합친다** (:func:`outcome_key`), 그리고
        합친 사실을 :attr:`_Ledger.duplicate_results` 로 센다 — 중복을
        발견했다는 이유로 "서로 다른 결과" 수가 늘지 않는다.

        🔴 **요약을 그 자리에서 뜬다** (:func:`summarize_resources`). 판을
        들고 있으면 뒤의 탐색이 그 판을 더 밟았을 때 요약이 조용히 달라진다.
        """
        meta = FoundMeta() if meta is None else meta
        #: 🔴 **역할을 열쇠에 넣는다** (Phase 6-AL §4). 넣지 않으면 흐름
        #: 행동만 한 후속 후보가 기준점과 같은 판에 닿아 **기준점을 덮어쓸**
        #: 수 있다 — 둘은 다른 사실이다.
        key = (meta.role.value, outcome_key(duel, legal, self.goal.seat))
        summary = summarize_resources(duel, self.goal.seat)
        where = ledger.result_keys.get(key)
        if where is None:
            ledger.result_keys[key] = len(ledger.results)
            ledger.result_meta[len(ledger.results)] = meta
            ledger.results.append((tuple(path), summary, verdict.reason))
            return
        ledger.duplicate_results += 1
        ledger.result_dups[where] = ledger.result_dups.get(where, 0) + 1
        kept_path, _kept_summary, _kept_reason = ledger.results[where]
        kept_meta = ledger.result_meta.get(where, FoundMeta())
        #: 🔴 **합쳐진 쪽의 최초 도달 이력을 지우지 않는다** (§4). 대표는
        #: :func:`representative_order` 가 고르고(기존 기준 그대로), 도달
        #: 위치가 다르면 그 사실이 ``merged_arrivals`` 에 남는다.
        takes_over = representative_order(path) < representative_order(
            kept_path
        )
        #: 🔴 **대표의 자기 도달 걸음은 ``merged_arrivals`` 에 넣지 않는다** —
        #: 거기 들어가는 것은 **합쳐져 사라진 경로**의 도달 걸음이다. 섞으면
        #: "이 결과는 두 자리에서 도달했다" 로 읽힌다.
        leader, displaced = (
            (meta, kept_meta) if takes_over else (kept_meta, meta)
        )
        arrivals = set(kept_meta.merged_arrivals)
        if displaced.reached_at and displaced.reached_at != leader.reached_at:
            arrivals.add(displaced.reached_at)
        arrivals.discard(leader.reached_at)
        if takes_over:
            #: 🔴 **대표가 바뀐다.** 그래서 재생은 탐색이 **끝난 뒤**에
            #: 돌린다 — 중간에 돌리면 교체된 대표가 검증되지 않는다
            #: (:meth:`rerun_results`).
            ledger.results[where] = (tuple(path), summary, verdict.reason)
        ledger.result_meta[where] = dataclasses.replace(
            leader, merged_arrivals=tuple(sorted(arrivals)),
        )

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
    duel: Duel, outcome: SearchOutcome, *, goal: "FieldGoal | None" = None,
    deadline: "RerunDeadline | None" = None,
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

    ``deadline`` 은 Phase 6-AJ 가 더한 **선택 인자**다 — 주지 않으면 기존
    호출 방식과 기본 동작이 그대로다 (단일 경로 재생에는 시간 제한이
    없었고, 지금도 기본은 없다).
    """
    if not isinstance(duel, Duel):
        raise BoundedSearchError(f"Duel 이 필요합니다: {type(duel).__name__}")
    if not isinstance(outcome, SearchOutcome):
        raise BoundedSearchError(
            f"SearchOutcome 이 필요합니다: {type(outcome).__name__}"
        )
    return rerun_steps(
        duel,
        outcome.path,
        outcome.goal if goal is None else goal,
        expect_field=outcome.final_field,
        expect_hash=outcome.final_state_hash,
        deadline=deadline,
    )


def rerun_steps(
    duel: Duel,
    path: "tuple[PathStep, ...]",
    target: FieldGoal,
    *,
    expect_field: "tuple[tuple[str, int, bool], ...]" = (),
    expect_hash: str = "",
    reached_at: int = 0,
    deadline: "RerunDeadline | None" = None,
) -> RerunResult:
    """
    기록된 걸음들을 **새 초기 상태에서** 다시 밟는다 (§5).

    🔴 :func:`rerun_path` 와 **같은 코드**다 — 그쪽이 ``SearchOutcome`` 을
    받는 얇은 겉면이고, 복수 결과 모드는 :class:`PathResult` 의 경로를
    들고 이쪽으로 들어온다 (6-AI). 재생 로직을 두 벌로 갈라 두지 않는다.

    ``expect_field`` · ``expect_hash`` 를 주면 그 둘과 **같은가**까지 본다.
    주지 않으면 목표 도달 여부만 본다.

    ``reached_at`` 을 주면 (Phase 6-AL) **그 걸음에서 목표에 닿았는지 다시
    확인**하고, 최종 상태에 목표가 남아 있는지는 따로 적는다
    (:attr:`RerunResult.goal_kept`). 🔴 **후속 경로의 성공 조건은 "그 걸음에서
    목표에 닿았고 최종 판이 기록과 같다" 이다** — 최종 상태에 목표가 없다는
    이유만으로 실패시키지 않고, 그렇다고 최초 도달 확인을 생략하고
    성공시키지도 않는다. 0 이면 기존 그대로 **최종 상태의 목표**를 본다.

    ``deadline`` 을 주면 **네 자리에서 마감을 본다** (Phase 6-AJ §A) —
    경로를 시작하기 전, 각 행동 **전후**(필수 걸음 처리 포함,
    :func:`_settle`), 그리고 **최종 검증과 자원 요약을 마친 뒤**. 🔴 마지막
    행동이나 최종 검증에서 시간을 넘긴 경우도 놓치지 않는다 — 넘겼으면
    :attr:`RerunResult.timed_out` 이 참이고 :attr:`RerunResult.ok` 는
    거짓이다. 주지 않으면 기본 동작이 6-AI 와 같다.
    """
    if not isinstance(duel, Duel):
        raise BoundedSearchError(f"Duel 이 필요합니다: {type(duel).__name__}")
    if not isinstance(target, FieldGoal):
        raise BoundedSearchError(f"FieldGoal 이 필요합니다: {type(target).__name__}")
    if not path:
        return RerunResult(
            ok=False,
            reason="재생할 경로가 없습니다 — 탐색이 목표에 닿지 않았습니다.",
        )
    if isinstance(reached_at, bool) or not isinstance(reached_at, int) \
            or reached_at < 0 or reached_at > len(path):
        raise BoundedSearchError(
            f"최초 도달 걸음은 0 이상 {len(path)} 이하의 정수입니다: "
            f"{reached_at!r}"
        )
    arrival_confirmed = False
    arrival_reason = ""
    #: 🔴 **경로를 시작하기 전에 본다** — 이미 마감이면 걸음을 하나도 밟지
    #: 않는다 (``test_a01``).
    if deadline is not None and deadline.expired():
        return _timed_out("경로 시작 전", deadline)

    sim = Simulator(duel)
    done = 0
    for recorded in path:
        #: 🔴 **각 행동 앞에서 본다** — 시간이 끝났으면 다음 행동을
        #: 시작하지 않는다 (``test_a02``).
        if deadline is not None and deadline.expired():
            return _timed_out(f"행동 {recorded.order} 앞", deadline, done)
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
        except Exception as error:  # noqa: BLE001 - 걸음 하나의 경계
            #: 🔴 **실행 예외를 예외로 적는다** (Phase 6-AJ 후속). 6-AH 가
            #: 둔 이 분기는 ``reason`` 만 적었고, 6-AJ 가 더한
            #: :attr:`RerunResult.error_type` · :attr:`RerunResult.stage` 를
            #: 채우지 않았다 — 그래서 바깥
            #: :meth:`BoundedSearch._rerun_one` 이 이 결과를
            #: :attr:`RerunState.ERRORED` 가 아니라
            #: :attr:`RerunState.MISMATCHED` 로 읽었고, 집계와 보고가 **실행
            #: 예외를 재생 불일치로** 표시했다.
            #:
            #: 🔴 ``reason`` 과 ``steps`` 의 뜻은 그대로다 — 몇 번째 행동에서
            #: 무엇이 터졌는지, 그때까지 몇 걸음을 밟았는지.
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 행동에서 예외가 났습니다: "
                       f"{type(error).__name__}: {error}",
                steps=done,
                error_type=type(error).__name__,
                stage=f"행동 {recorded.order} 실행",
            )
        if not step.accepted:
            return RerunResult(
                ok=False,
                reason=f"{recorded.order}번째 행동이 거절되었습니다: "
                       f"{step.reason}",
                steps=done,
            )
        settled = _settle(fork, target.seat, deadline=deadline)
        if settled.timed_out:
            #: 🔴 **필수 걸음 도중에 시간이 끝났다** — 안전한 경계에서
            #: 멈췄고, 이 결과는 검증으로 세지 않는다 (``test_a03``).
            return _timed_out(f"행동 {recorded.order} 의 필수 걸음",
                              deadline, done)
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
        if reached_at and done == reached_at:
            #: 🔴 **최초 도달을 그 자리에서 다시 확인한다** (6-AL §2).
            #: 생략하고 최종 판만 보면 "목표를 거쳤다" 가 검증되지 않는다.
            arrival = target.judge(sim.duel)
            arrival_confirmed = arrival.reached
            arrival_reason = arrival.reason
            if not arrival_confirmed:
                return RerunResult(
                    ok=False,
                    reason=f"{reached_at}번째 걸음에서 목표에 닿지 "
                           f"않았습니다 (기록은 거기서 최초 도달이라고 "
                           f"적혀 있습니다): {arrival.reason}",
                    steps=done,
                    stage=f"최초 도달 확인 (걸음 {reached_at})",
                    first_arrival_at=reached_at,
                )
        #: 🔴 **각 행동 뒤에서도 본다** — 마지막 행동에서 시간을 넘긴
        #: 경우를 놓치지 않는다 (``test_a04``).
        if deadline is not None and deadline.expired():
            return _timed_out(f"행동 {recorded.order} 뒤", deadline, done)

    verdict = target.judge(sim.duel)
    field_now = own_field(sim.duel, target.seat)
    hash_now = sim.duel.state.state_hash()
    #: 🔴 **비교할 것을 주지 않았으면 "같다" 고 말하지 않는다.**
    compared = bool(expect_hash) or bool(expect_field)
    same = (
        field_now == expect_field and hash_now == expect_hash
        if compared else False
    )
    if reached_at:
        #: 🔴 **후속 경로** — 성공 조건은 "그 걸음에서 목표에 닿았고 최종
        #: 판이 기록과 같다" 다. 최종 상태의 목표 유지 여부는 **따로** 적는다.
        if compared and not same:
            reason = (
                f"최초 도달(걸음 {reached_at})은 확인했지만 최종 판이 탐색 "
                f"결과와 다릅니다 — 해시 {expect_hash[:12]}… → "
                f"{hash_now[:12]}…"
            )
        else:
            kept = "남아 있습니다" if verdict.present else "남아 있지 않습니다"
            reason = (
                f"걸음 {done}개를 새 초기 상태에서 다시 밟았습니다. 걸음 "
                f"{reached_at}에서 목표에 닿은 것을 확인했고({arrival_reason})"
                f", 최종 상태에 목표 카드는 {kept}"
                + ("" if compared else " (비교할 최종 판을 주지 않았습니다)")
                + "."
            )
        summary = summarize_resources(sim.duel, target.seat)
        if deadline is not None and deadline.expired():
            late = _timed_out("최종 검증 · 자원 요약 뒤", deadline, done)
            return dataclasses.replace(
                late,
                goal_reached=arrival_confirmed,
                final_field=field_now,
                final_state_hash=hash_now,
                matches_search=same,
                resources=summary,
                first_arrival_at=reached_at,
                first_arrival_confirmed=arrival_confirmed,
                goal_kept=verdict.present,
            )
        return RerunResult(
            ok=arrival_confirmed and (same or not compared),
            reason=reason,
            steps=done,
            goal_reached=arrival_confirmed,
            final_field=field_now,
            final_state_hash=hash_now,
            matches_search=same,
            resources=summary,
            first_arrival_at=reached_at,
            first_arrival_confirmed=arrival_confirmed,
            goal_kept=verdict.present,
        )
    if not verdict.reached:
        reason = f"재생이 목표에 닿지 않았습니다: {verdict.reason}"
    elif compared and not same:
        reason = (
            "재생이 목표에는 닿았지만 최종 판이 탐색 결과와 다릅니다 — "
            f"해시 {expect_hash[:12]}… → {hash_now[:12]}…"
        )
    elif not compared:
        reason = (
            f"걸음 {done}개를 새 초기 상태에서 다시 밟아 목표에 닿았습니다 "
            "(비교할 최종 판을 주지 않았습니다)."
        )
    else:
        reason = (
            f"걸음 {done}개를 새 초기 상태에서 다시 밟아 같은 최종 판에 "
            "닿았습니다."
        )
    summary = summarize_resources(sim.duel, target.seat)
    #: 🔴 **최종 검증과 자원 요약을 마친 뒤에도 본다** (``test_a05``). 여기서
    #: 넘겼으면 판정이 맞았더라도 성공으로 적지 않는다 — 협력적 제한이므로
    #: 마지막 호출을 끊지는 못하지만, 돌아온 자리에서 초과를 본다.
    if deadline is not None and deadline.expired():
        late = _timed_out("최종 검증 · 자원 요약 뒤", deadline, done)
        return dataclasses.replace(
            late,
            goal_reached=verdict.reached,
            final_field=field_now,
            final_state_hash=hash_now,
            matches_search=same,
            resources=summary,
            first_arrival_confirmed=verdict.reached,
            goal_kept=verdict.present,
        )
    return RerunResult(
        ok=verdict.reached and (same or not compared),
        reason=reason,
        steps=done,
        goal_reached=verdict.reached,
        final_field=field_now,
        final_state_hash=hash_now,
        matches_search=same,
        resources=summary,
        #: 첫 도달 모드에서는 **최종 상태의 목표**가 곧 도달 확인이다.
        first_arrival_confirmed=verdict.reached,
        goal_kept=verdict.present,
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


def search_many_for_card(
    duel: Duel,
    card_id: int,
    *,
    seat: int = 0,
    budget: "SearchBudget | None" = None,
) -> MultiSearchOutcome:
    """
    그 카드를 자신 필드에 올리는 **서로 다른 결과 여럿**을 모은다 (6-AI).

    🔴 :func:`search_for_card` 와 **같은 탐색기**다 — 예산의
    ``max_results`` 만 다르다.
    """
    return BoundedSearch(
        goal=FieldGoal(card_id=card_id, seat=seat),
        budget=(
            SearchBudget(max_results=MULTI_DEFAULT_MAX_RESULTS)
            if budget is None else budget
        ),
    ).run_many(duel)


__all__ = [
    "Admission",
    "BoundedSearch",
    "BoundedSearchError",
    "CHOICE_BRANCHING_UNAVAILABLE",
    "CONCEALED_CARD",
    "CardSlot",
    "ContinuationStop",
    "DEFAULT_MAX_BASELINES",
    "DEFAULT_MAX_CHOICE_BRANCHES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_FOLLOWUP_ACTIONS",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_RERUN_SECONDS",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_MAX_SECONDS",
    "FIELD_ZONES",
    "FLOW_ACTION_KINDS",
    "FOLLOWUP_CAP",
    "FOLLOWUP_DEFAULT_ACTIONS",
    "FieldGoal",
    "FoundMeta",
    "GoalVerdict",
    "MULTI_DEFAULT_MAX_RESULTS",
    "MultiSearchOutcome",
    "NO_INTERFERENCE",
    "OUT_OF_TURN_SCOPE",
    "PathResult",
    "PathStep",
    "RESULTS_CAP",
    "RerunDeadline",
    "RerunResult",
    "RerunState",
    "ResourceSummary",
    "ResultRole",
    "ResultTally",
    "SETTLE_GUARD",
    "SearchBudget",
    "SearchOutcome",
    "Termination",
    "UseRecord",
    "ZoneSummary",
    "admit",
    "alternative_options",
    "iter_selections",
    "node_key",
    "outcome_key",
    "own_field",
    "representative_order",
    "rerun_path",
    "rerun_steps",
    "search_for_card",
    "search_many_for_card",
    "selection_options",
    "summarize_resources",
    "superseded",
]
