"""
검증된 복수 전개 결과의 **비교와 추천 v1** (Phase 6-AK).

이 모듈이 하는 일은 하나다 — 탐색과 재생 검증이 **이미 끝난** 결과들을
읽고, 이름과 판이 붙은 기준으로 **무엇을 먼저 검토할지** 고른다.

🔴 **실전 승률도, 최강 전개도, 상대 방해 대응력도 계산하지 않는다.** 이번
평가는 :data:`POLICY_NAME` 이 말하는 **자원 보존 중심의 제한적 휴리스틱**이고,
그 두 축이 게임 전체에서의 우월성을 뜻하지 않는다.

🔴 **독립 단계다.** 받은 결과 · 경로 · 재생 결과를 **하나도 바꾸지 않고**
값만 읽는다 (전부 frozen 이다). 평가 때문에 수집한 경로가 사라지지 않는다 —
제외된 결과도 **원래 사유와 함께** 그대로 들고 있는다
(:attr:`Ranking.candidates`).

🔴 **임의의 가중치 합계를 만들지 않는다.** "전개 점수 87점" 같은 수는 없고,
세 수치(:class:`Measures`)와 그 수치가 **증명하지 않는 것**
(:class:`Criterion.limit_ko`)을 함께 적는다.

🔴 **목표 카드에 처음 도달한 시점의 비교다.** 탐색은 목표에 닿은 분기를 더
펼치지 않으므로(6-AI §1.2), 여기 있는 자원은 "전개를 끝까지 수행한 최종 집"
이 아니다. :data:`FIRST_ARRIVAL_NOTE` 가 그 사실을 적는다.

경계 (ADR-007)
--------------
``engine`` 과 ``agent`` 만 import 한다. 카드 ID 리터럴도, 적어 둔 전개
경로의 이름도 없다 — 받은 결과만 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.vocabulary import Zone

__all__ = [
    "CRITERIA_V1",
    "Candidate",
    "Criterion",
    "Exclusion",
    "FIRST_ARRIVAL_NOTE",
    "FLOW_ACTION_KINDS",
    "Measures",
    "POLICY_NAME",
    "POLICY_SCOPE_NOTE",
    "POLICY_VERSION",
    "Ranking",
    "UNMEASURABLE",
    "measure_result",
    "rank_results",
]

#: 평가 정책의 **이름과 판**. 🔴 바뀌면 보고에 그대로 드러난다.
POLICY_NAME: str = "resource-preservation"
POLICY_VERSION: str = "v1"

#: 🔴 **이 평가의 범위**를 한 줄로.
POLICY_SCOPE_NOTE: str = (
    "탐색에서 발견하고 재생 검증한 후보 사이의 비교입니다 — 자원 보존 중심의"
    " 제한적 휴리스틱이고, 🔴 실전 최강·승률 평가가 아닙니다."
)

#: 🔴 **언제의 자원인가.**
FIRST_ARRIVAL_NOTE: str = (
    "목표 카드에 **처음 도달한 시점**의 후보 비교입니다 — 탐색이 목표에 닿은"
    " 분기를 더 펼치지 않으므로, 전개를 끝까지 수행한 최종 집의 평가가"
    " 아닙니다."
)

#: **흐름 행동** — 전개 비용으로 세지 않는다. 🔴 패스는 무엇을 쓰는 수가
#: 아니라 우선권을 넘기는 수이고, 페이즈를 넘기는 수도 그렇다. 이것을 비용으로
#: 세면 "패스를 한 번 더 한 경로" 가 더 비싼 전개로 읽힌다.
FLOW_ACTION_KINDS: frozenset = frozenset({
    "pass", "end_phase", "change_phase",
})

#: 평가할 수 없다는 표시. 🔴 **0 점이나 유리한 기본값으로 바꾸지 않는다.**
UNMEASURABLE: None = None


@dataclass(frozen=True, slots=True)
class Criterion:
    """
    기준 **하나** — 이름 · 무엇을 읽는가 · 🔴 **무엇을 증명하지 않는가.**

    해석 제한을 자료형에 넣어 둔 이유는 하나다: 보고가 수치만 적고 제한을
    빠뜨리면, 읽는 사람이 "패가 많으니 더 좋다" 로 읽는다.
    """

    key: str
    label_ko: str
    reads_ko: str
    """이 기준이 **실제로 읽는 관측값**."""
    limit_ko: str
    """🔴 이 수치가 **증명하지 않는 것**."""
    role_ko: str
    """추천에서 이 기준이 하는 일 (보존 축인가, 표시 순서인가)."""


#: 🔴 **기준 v1 전부.** 카드별 실전 강도를 지어내지 않는다.
CRITERIA_V1: "tuple[Criterion, ...]" = (
    Criterion(
        key="hand_left",
        label_ko="남은 패 장수",
        reads_ko="재생으로 검증된 상태의 자기 패 장수.",
        limit_ko="🔴 패를 **더 남겼다**는 뜻이고, 그 패의 활용도가 더 높다는"
                 " 증명이 아닙니다. 무엇을 할 수 있는 패인지 세지 않았습니다.",
        role_ko="보존 축 (비지배 후보를 구하는 두 축의 하나)",
    ),
    Criterion(
        key="normal_summon_right",
        label_ko="일반 소환권",
        reads_ko="엔진이 기록한 이 턴의 일반 소환권 사용 여부.",
        limit_ko="🔴 쓰지 않았다는 것은 **이 턴에 아직 쓰지 않았다**는 뜻이고,"
                 " 지금 합법적으로 일반 소환할 수 있다는 증명이 아닙니다"
                 " (발동·소환 가능 판정은 ``legal_actions`` 의 일입니다).",
        role_ko="보존 축 (비지배 후보를 구하는 두 축의 하나)",
    ),
    Criterion(
        key="spend_actions",
        label_ko="비흐름 행동 수",
        reads_ko="경로의 걸음 중 흐름 행동(패스·페이즈 전환)이 아닌 것의 수.",
        limit_ko="🔴 적다는 것이 패 트랩에 강하거나 실전적으로 더 좋다는 뜻이"
                 " 아닙니다. **짧은 경로를 먼저 검토하게 하는 표시 기준**일"
                 " 뿐입니다.",
        role_ko="표시 순서 (우열 근거가 아니다)",
    ),
)

#: 🔴 **이번 기준이 유불유를 판단하지 못하는 차이들.** 보고가 이것을
#: "평가했다" 로 읽히지 않게 이름으로 적어 둔다.
UNJUDGED_DIFFERENCES: "tuple[str, ...]" = (
    "상대에게 남긴 카드와 토큰 (몇 칸을 줬는지는 기존 비교가 보여 주지만,"
    " 그것이 유리한지 불리한지는 이번 기준이 판단하지 못합니다)",
    "이미 쓴 효과 사용 제한 (무엇을 더 못 쓰게 됐는지의 가치)",
    "자신 필드 · 묘지 · 제외 · 엑스트라 덱의 **구성** 차이",
    "세트한 카드가 무엇인지, 그것이 막는 것",
    "공격력 · 링크 수치 등 수치 자체",
    "다음 턴의 후속 전개와 상대의 방해 수",
)


class Exclusion(str, Enum):
    """추천 대상에서 **빠진 이유.** 🔴 원래 사유를 덮어쓰지 않는다."""

    NONE = "none"
    """빠지지 않았다 (추천 대상)."""
    NOT_VERIFIED = "not_verified"
    """재생 검증을 통과하지 못했다 — 원래 재생 상태가 이유를 말한다."""
    UNMEASURABLE = "unmeasurable"
    """평가에 필요한 관측값을 읽을 수 없다. 🔴 0 점으로 대체하지 않는다."""


@dataclass(frozen=True, slots=True)
class Measures:
    """
    후보 하나의 **관측값 셋.** 🔴 점수가 아니다 — 센 것 그대로다.
    """

    hand_left: int
    normal_summon_used: bool
    spend_actions: int
    flow_actions: int
    """참고용 — 🔴 **비용으로 세지 않은** 흐름 행동의 수."""

    @property
    def summon_right_kept(self) -> bool:
        """일반 소환권을 **이 턴에 아직 쓰지 않았는가.**"""
        return not self.normal_summon_used

    def describe_ko(self) -> str:
        used = "사용했습니다" if self.normal_summon_used else "쓰지 않았습니다"
        return (f"패 {self.hand_left}장을 남겼고 일반 소환권을 {used}."
                f" 비흐름 행동은 {self.spend_actions}회입니다"
                f" (흐름 행동 {self.flow_actions}회는 비용으로 세지"
                f" 않았습니다).")


@dataclass(frozen=True, slots=True)
class Candidate:
    """
    결과 하나의 **평가 칸.** 🔴 원래 결과 ID 를 들고 있으므로, 표시 순서를
    바꿔도 경로·자원·재생 결과와의 연결이 끊기지 않는다.
    """

    index: int
    """원래 결과 ID (``PathResult.index``). 🔴 정렬 뒤에도 이것이 기준이다."""
    verified: bool
    rerun_state: str
    """원래 재생 상태의 값 문자열 — 제외 사유를 덮어쓰지 않으려고 들고 있는다."""
    measures: "Measures | None" = None
    exclusion: Exclusion = Exclusion.NONE
    unmeasurable_reason: str = ""
    nondominated: bool = False
    dominated_by: "tuple[int, ...]" = ()
    order: int = 0
    """표시 순서 (1부터). 🔴 **같은 값이면 공동 후보**다."""

    @property
    def eligible(self) -> bool:
        """추천 대상인가 — 검증됐고 평가할 수 있는가."""
        return self.exclusion is Exclusion.NONE

    @property
    def recommended(self) -> bool:
        return self.eligible and self.nondominated


@dataclass(frozen=True, slots=True)
class Ranking:
    """
    한 실행의 **추천 결과 전부** (Phase 6-AK).

    🔴 **같은 실행에서 수집된 결과끼리만** 비교한다 — 이 객체는 하나의
    ``MultiSearchOutcome`` 에서만 만들어진다.
    """

    policy: str = POLICY_NAME
    version: str = POLICY_VERSION
    criteria: "tuple[Criterion, ...]" = CRITERIA_V1
    unjudged: "tuple[str, ...]" = UNJUDGED_DIFFERENCES
    candidates: "tuple[Candidate, ...]" = ()
    """🔴 **모든 결과** — 제외된 것까지, 원래 결과 ID 순서로."""
    note: str = ""
    """검증 결과가 없거나 하나뿐일 때의 안내."""

    @property
    def policy_label(self) -> str:
        return f"{self.policy} {self.version}"

    @property
    def verified_candidates(self) -> "tuple[Candidate, ...]":
        return tuple(one for one in self.candidates if one.verified)

    @property
    def eligible_candidates(self) -> "tuple[Candidate, ...]":
        return tuple(one for one in self.candidates if one.eligible)

    @property
    def excluded(self) -> "tuple[Candidate, ...]":
        """🔴 추천에서 빠진 것들 — **사유와 함께** 보존된다."""
        return tuple(one for one in self.candidates if not one.eligible)

    @property
    def recommended(self) -> "tuple[Candidate, ...]":
        """
        **추천 후보** — 두 보존 축에서 비지배인 것들, 표시 순서대로.

        🔴 여럿이면 **공동 후보**다. 억지로 하나로 줄이지 않는다.
        """
        picked = [one for one in self.candidates if one.recommended]
        picked.sort(key=lambda one: (one.order, one.index))
        return tuple(picked)

    @property
    def recommended_ids(self) -> "tuple[int, ...]":
        return tuple(one.index for one in self.recommended)

    @property
    def has_recommendation(self) -> bool:
        return bool(self.recommended)

    @property
    def tied(self) -> bool:
        """추천 후보가 **둘 이상**인가 (장단점이 갈리거나 동률인가)."""
        return len(self.recommended) > 1

    @property
    def only_one_verified(self) -> bool:
        return len(self.verified_candidates) == 1

    def candidate(self, index: int) -> "Candidate | None":
        for one in self.candidates:
            if one.index == index:
                return one
        return None

    def reason_ko(self, index: int) -> str:
        """그 후보가 **왜** 추천(또는 제외)됐는지, 수치와 함께."""
        one = self.candidate(index)
        if one is None:
            return f"[결과 {index}] 를 찾지 못했습니다."
        if one.exclusion is Exclusion.NOT_VERIFIED:
            return (f"추천 대상이 아닙니다 — 재생 검증을 통과하지 못했습니다"
                    f" (재생 상태 {one.rerun_state}). 🔴 수치가 유리해도"
                    f" 추천하지 않습니다.")
        if one.exclusion is Exclusion.UNMEASURABLE:
            return (f"평가하지 못했습니다 — {one.unmeasurable_reason}"
                    " 🔴 0 점이나 유리한 기본값으로 대체하지 않았습니다.")
        head = (
            f"이번 자원 보존 기준({self.policy_label})의 추천 후보입니다."
            if one.nondominated else
            "이번 두 보존 축에서 다른 후보에 밀렸습니다 — 밀린 상대: "
            + " · ".join(f"결과 {i}" for i in one.dominated_by)
            + " (두 축 모두 나쁘지 않고 최소 한 축이 더 낫습니다). 🔴 그"
              "쪽이 게임 전체에서 더 좋다는 뜻은 아닙니다."
        )
        tail = ""
        if one.nondominated and self.tied:
            others = [
                other for other in self.recommended if other.index != index
            ]
            if others:
                bits = [
                    f"결과 {other.index}: "
                    + _trade_off_ko(one.measures, other.measures)
                    for other in others
                ]
                #: 🔴 **무엇이 갈리는지 정직하게 적는다.** 두 보존 축이 같고
                #: 비흐름 행동만 다르면 그것은 **표시 순서**의 차이이고
                #: "장단점" 이 아니다 — 그렇게 적으면 표시 기준이 전략적
                #: 선택처럼 읽힌다.
                axes_differ = any(
                    _axes_differ(one.measures, other.measures)
                    for other in others
                )
                lead = (
                    " 다른 추천 후보와 **보존 축의 장단점이 갈립니다**: "
                    if axes_differ else
                    " 다른 추천 후보와 **두 보존 축이 같습니다**: "
                )
                tail = (lead + " / ".join(bits)
                        + " — 🔴 어느 쪽이 더 좋은지 고르지 않았습니다.")
        return f"{head} {one.measures.describe_ko()}{tail}"


def _axes_differ(mine: Measures, other: Measures) -> bool:
    """**두 보존 축**에서 다른가 (비흐름 행동은 보존 축이 아니다)."""
    return (mine.hand_left != other.hand_left
            or mine.summon_right_kept != other.summon_right_kept)


def _trade_off_ko(mine: Measures, other: Measures) -> str:
    """두 후보의 **차이**를 양쪽 그대로. 🔴 승자를 고르지 않는다."""
    bits: list[str] = []
    if other.hand_left != mine.hand_left:
        more = "많습니다" if other.hand_left > mine.hand_left else "적습니다"
        bits.append(f"패가 {other.hand_left}장으로 {more}")
    if other.summon_right_kept != mine.summon_right_kept:
        bits.append("일반 소환권을 "
                    + ("쓰지 않았습니다" if other.summon_right_kept
                       else "사용했습니다"))
    if other.spend_actions != mine.spend_actions:
        bits.append(f"비흐름 행동이 {other.spend_actions}회입니다")
    if not bits:
        return "이 세 수치가 **모두 같습니다** (동률 공동 후보입니다)"
    text = " · ".join(bits)
    if not _axes_differ(mine, other):
        #: 🔴 **표시 순서의 차이임을 그 자리에서 말한다.**
        text += " (🔴 비흐름 행동은 **표시 순서 기준**일 뿐이고 보존 축이"
        text += " 아닙니다 — 두 보존 축은 같습니다)"
    return text


def _hand_left(resources) -> "int | None":
    """패 장수 — 🔴 **읽을 수 없으면 ``None``.** 0 으로 바꾸지 않는다."""
    zone = getattr(resources, "zone", None)
    if zone is None:
        return None
    found = zone(getattr(resources, "seat", 0), Zone.HAND)
    if found is None:
        return None
    size = getattr(found, "size", None)
    if isinstance(size, bool) or not isinstance(size, int):
        return None
    return size


def _spend_and_flow(path) -> "tuple[int, int] | None":
    """
    (비흐름 행동 수, 흐름 행동 수). 🔴 걸음의 종류를 읽을 수 없으면 ``None``.
    """
    if path is None:
        return None
    spend = 0
    flow = 0
    for step in path:
        kind = getattr(step, "kind", None)
        if not isinstance(kind, str) or not kind:
            return None
        if kind in FLOW_ACTION_KINDS:
            flow += 1
        else:
            spend += 1
    return spend, flow


def measure_result(result) -> "tuple[Measures | None, str]":
    """
    결과 하나의 관측값을 센다 — ``(Measures | None, 못 센 이유)``.

    🔴 **하나라도 읽을 수 없으면 평가 불가다.** 임의의 0 점이나 유리한
    기본값으로 대체하지 않는다.
    """
    resources = getattr(result, "resources", None)
    if resources is None:
        return None, "검증된 상태의 자원 요약이 없습니다."
    hand = _hand_left(resources)
    if hand is None:
        return None, "자기 패 장수를 읽을 수 없습니다."
    used = getattr(resources, "normal_summon_used", None)
    if not isinstance(used, bool):
        return None, "일반 소환권 사용 기록을 읽을 수 없습니다."
    counted = _spend_and_flow(getattr(result, "path", None))
    if counted is None:
        return None, "경로의 걸음 종류를 읽을 수 없습니다."
    spend, flow = counted
    return Measures(hand_left=hand, normal_summon_used=used,
                    spend_actions=spend, flow_actions=flow), ""


def _dominates(better: Measures, worse: Measures) -> bool:
    """
    두 **보존 축**에서 앞의 것이 뒤의 것을 지배하는가.

    🔴 **두 축만 본다** — 남은 패와 일반 소환권. 두 축 모두 나쁘지 않고
    최소 한 축이 더 나으면 지배한다. 🔴 이것을 게임 전체에서의 우월성이나
    안전한 가지치기 근거로 읽지 말 것: 지배당한 후보가 **필드 구성이나
    세트한 카드 때문에 실제로 더 좋을 수 있다** (이번 기준이 그것을 보지
    못한다).
    """
    kept = int(better.summon_right_kept) >= int(worse.summon_right_kept)
    held = better.hand_left >= worse.hand_left
    if not (kept and held):
        return False
    return (better.hand_left > worse.hand_left
            or int(better.summon_right_kept) > int(worse.summon_right_kept))


def rank_results(outcome) -> Ranking:
    """
    한 실행의 검증된 결과들을 비교하고 **추천 후보**를 고른다 (6-AK).

    🔴 **받은 것을 바꾸지 않는다.** 값만 읽고 새 :class:`Ranking` 을 만든다.

    🔴 **검증된 결과만 추천 대상이다** (``PathResult.verified``). 불일치 ·
    실행 예외 · 시간 초과 · 미시작 · 재생 끔 결과는 **원래 사유와 함께**
    남지만 순위에 들어가지 않는다.
    """
    rows: list[Candidate] = []
    for result in getattr(outcome, "results", ()) or ():
        index = getattr(result, "index", len(rows) + 1)
        state = getattr(result, "rerun_state", None)
        state_value = str(getattr(state, "value", state or "unknown"))
        if not getattr(result, "verified", False):
            rows.append(Candidate(
                index=index, verified=False, rerun_state=state_value,
                exclusion=Exclusion.NOT_VERIFIED,
            ))
            continue
        measures, why = measure_result(result)
        if measures is None:
            rows.append(Candidate(
                index=index, verified=True, rerun_state=state_value,
                exclusion=Exclusion.UNMEASURABLE, unmeasurable_reason=why,
            ))
            continue
        rows.append(Candidate(
            index=index, verified=True, rerun_state=state_value,
            measures=measures,
        ))

    eligible = [one for one in rows if one.eligible]
    #: 🔴 **비지배 후보**를 구한다 — 두 보존 축만으로.
    decided: list[Candidate] = []
    for one in rows:
        if not one.eligible:
            decided.append(one)
            continue
        beaten_by = tuple(sorted(
            other.index for other in eligible
            if other.index != one.index
            and _dominates(other.measures, one.measures)
        ))
        decided.append(_replace(
            one, nondominated=not beaten_by, dominated_by=beaten_by,
        ))

    #: 🔴 **표시 순서만** 정한다 — 비흐름 행동이 적은 쪽을 먼저 보게 하고,
    #: 같으면 공동 후보로 같은 자리에 둔다. 결과 ID 는 **표시 순서를 가르는**
    #: 데만 쓰고 우열 근거로 쓰지 않는다.
    picked = sorted(
        (one for one in decided if one.recommended),
        key=lambda one: (one.measures.spend_actions, one.index),
    )
    order_of: dict = {}
    seen: list = []
    for one in picked:
        spend = one.measures.spend_actions
        if spend not in seen:
            seen.append(spend)
        order_of[one.index] = seen.index(spend) + 1
    decided = [
        _replace(one, order=order_of.get(one.index, 0)) for one in decided
    ]

    verified = [one for one in decided if one.verified]
    if not verified:
        note = ("🔴 **추천할 검증 결과가 없습니다** — 재생으로 뒷받침된 결과가"
                " 없습니다. 아래 제외 사유를 보십시오.")
    elif len(verified) == 1:
        note = ("**유일한 검증 후보**입니다 — 🔴 다른 결과보다 우수하다는"
                " 뜻이 아닙니다 (비교할 검증 후보가 없습니다).")
    else:
        note = ""
    return Ranking(candidates=tuple(decided), note=note)


def _replace(one: Candidate, **changes) -> Candidate:
    """``dataclasses.replace`` 와 같은 일 — frozen 이므로 새로 만든다."""
    values = {
        "index": one.index,
        "verified": one.verified,
        "rerun_state": one.rerun_state,
        "measures": one.measures,
        "exclusion": one.exclusion,
        "unmeasurable_reason": one.unmeasurable_reason,
        "nondominated": one.nondominated,
        "dominated_by": one.dominated_by,
        "order": one.order,
    }
    values.update(changes)
    return Candidate(**values)
