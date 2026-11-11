"""
**목표 없는 자율 탐색** 결과의 비교와 추천 (Phase 6-BB).

왜 따로 있는가
--------------
:mod:`agent.result_ranking` (6-AK) 은 **목표 카드에 처음 도달한 시점**의
후보들을 견준다. 그 비교축은 두 개 — 남은 패와 일반 소환권 — 이고, 목표
카드가 필드에 있다는 것이 **이미 전제**이므로 필드를 세지 않는다.

🔴 **그 두 축만으로 자율 탐색을 견주면 "아무것도 하지 않은 쪽" 이 언제나
이긴다.** 목표가 없으면 "패를 가장 많이 남긴 결과" 가 곧 "일반 소환만 하고
멈춘 결과" 이기 때문이다. 그래서 이 모듈은 **필드에 남은 것**을 축으로
더한다.

🔴 **그래도 점수 하나로 합치지 않는다.** :mod:`agent.result_ranking` 의
규율 그대로다 — 축마다 센 값과 **그 값이 증명하지 않는 것**을 함께 적고,
비지배(파레토) 후보를 **공동 추천**으로 내놓는다.

🔴 **카드 이름도 링크 수치도 보지 않는다.** 이 모듈에 카드 ID 리터럴이
없고, "이 카드가 있으면 좋다" 는 표도 없다 — 센 것은 장수와 엔진이 적어 둔
기록뿐이다.

🔴 **미구현 효과를 점수로 바꾸지 않는다.** 뒷면으로 세트된 카드는 **세트된
장수**로만 세고 "확정 방해 1회" 로 적지 않는다. 묘지·제외 자원도 장수이지,
"후속 확보" 가 아니다.

경계 (ADR-007)
--------------
``engine`` 과 ``agent`` 만 import 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.vocabulary import Zone

from agent.bounded_search import FLOW_ACTION_KINDS, RerunState
from agent.result_ranking import Criterion, Exclusion

__all__ = [
    "CRITERIA_OPEN",
    "OpenCandidate",
    "OpenMeasures",
    "OpenRanking",
    "POLICY_NAME",
    "POLICY_SCOPE_NOTE",
    "POLICY_VERSION",
    "UNJUDGED_OPEN",
    "measure_open",
    "rank_open",
    "select_top",
]

POLICY_NAME: str = "open-development"
POLICY_VERSION: str = "v1"

POLICY_SCOPE_NOTE: str = (
    "목표 카드를 지정하지 않은 자율 탐색에서 **예산 안에 모은 후보**끼리의"
    " 비교입니다 — 🔴 전역 최적 전개도, 실전 최강도, 승률 평가도 아닙니다."
)

#: 🔴 **이 평가가 판정하지 않는 것.** 보고가 수치만 적고 빠뜨리면 읽는
#: 사람이 "필드가 많으니 강하다" 로 읽는다.
UNJUDGED_OPEN: "tuple[str, ...]" = (
    "필드에 남은 몬스터가 **무엇을 할 수 있는지** 세지 않았습니다 — 장수만"
    " 셉니다.",
    "뒷면으로 세트한 카드는 **세트된 장수**일 뿐이고, 그 카드가 이 엔진에서"
    " 실제로 발동 후보가 되는지도 보지 않았습니다 — 🔴 '확정 방해' 로"
    " 세지 않습니다.",
    "묘지·제외에 쌓인 장수는 **자원이 거기 있다**는 사실이고, 다음 턴에"
    " 쓸 수 있다는 증명이 아닙니다.",
    "상대 방해가 없다는 전제이고, 상대 턴의 일은 판정하지 않습니다.",
    "금지·제한(금제) 적법성은 **전혀 보지 않습니다** — 엔진의 행동 적법성"
    " 판정과 다른 일입니다.",
)

CRITERIA_OPEN: "tuple[Criterion, ...]" = (
    Criterion(
        key="field_monsters",
        label_ko="필드에 남은 앞면 몬스터",
        reads_ko="검증된 상태의 자기 몬스터 존·엑스트라 몬스터 존의 앞면"
                 " 카드 수.",
        limit_ko="🔴 **장수뿐입니다.** 그 몬스터가 무엇을 할 수 있는지,"
                 " 공격력이 얼마인지, 상대 턴에 쓸 효과가 있는지 세지"
                 " 않았습니다.",
        role_ko="비교 축 (전개 산출물)",
    ),
    Criterion(
        key="hand_left",
        label_ko="남은 패 장수",
        reads_ko="검증된 상태의 자기 패 장수.",
        limit_ko="🔴 패를 **더 남겼다**는 뜻이고, 그 패의 활용도가 더 높다는"
                 " 증명이 아닙니다.",
        role_ko="비교 축 (보존)",
    ),
    Criterion(
        key="normal_summon_right",
        label_ko="일반 소환권",
        reads_ko="엔진이 기록한 이 턴의 일반 소환권 사용 여부.",
        limit_ko="🔴 쓰지 않았다는 것은 **이 턴에 아직 쓰지 않았다**는 뜻이고,"
                 " 지금 합법적으로 일반 소환할 수 있다는 증명이 아닙니다.",
        role_ko="비교 축 (보존)",
    ),
    Criterion(
        key="spend_actions",
        label_ko="비흐름 행동 수",
        reads_ko="경로에서 패스·페이즈 전환을 뺀 행동 수.",
        limit_ko="🔴 **비교 축이 아닙니다** — 같은 축 값끼리 늘어설 때 더 짧은"
                 " 쪽을 먼저 보여 주는 데만 씁니다. 적다고 더 좋은 전개라는"
                 " 뜻이 아닙니다.",
        role_ko="표시 순서",
    ),
    Criterion(
        key="set_cards",
        label_ko="세트한 카드",
        reads_ko="자기 마법·함정 존의 뒷면 카드 수.",
        limit_ko="🔴 **방해 수단으로 세지 않습니다.** 세트된 장수일 뿐이고,"
                 " 그 카드가 이 엔진에서 발동 후보가 되는지도 보지"
                 " 않았습니다.",
        role_ko="참고 (축 아님)",
    ),
    Criterion(
        key="grave_banish",
        label_ko="묘지·제외 장수",
        reads_ko="자기 묘지와 제외 존의 카드 수.",
        limit_ko="🔴 **후속 수단으로 세지 않습니다** — 거기 있다는 사실일"
                 " 뿐입니다.",
        role_ko="참고 (축 아님)",
    ),
    Criterion(
        key="summon_limits",
        label_ko="걸려 있는 특수 소환 제한",
        reads_ko="엔진의 ``summon_limits`` 표에 이 턴·이 자리로 남아 있는 것.",
        limit_ko="🔴 표가 비어 있다고 '제한 없음' 이 아닙니다 — 이 실행이 그"
                 " 표를 들고 있지 않을 수도 있습니다.",
        role_ko="참고 (축 아님)",
    ),
)

@dataclass(frozen=True, slots=True)
class OpenMeasures:
    """후보 하나의 **센 값들.** 🔴 점수가 아니다."""

    field_monsters: int
    hand_left: int
    normal_summon_used: bool
    spend_actions: int
    flow_actions: int
    set_cards: int
    grave_cards: int
    banished_cards: int
    extra_left: int
    deck_left: int
    limits: "tuple[tuple[str, int], ...]" = ()

    @property
    def summon_right_kept(self) -> bool:
        return not self.normal_summon_used

    @property
    def axes(self) -> "tuple[int, int, int]":
        """🔴 **비교에 쓰는 세 축만** — 나머지는 참고다."""
        return (self.field_monsters, self.hand_left,
                int(self.summon_right_kept))

    def describe_ko(self) -> str:
        used = "사용" if self.normal_summon_used else "미사용"
        line = (f"필드 몬스터 {self.field_monsters} · 패 {self.hand_left} ·"
                f" 일반 소환권 {used} · 비흐름 행동 {self.spend_actions}"
                f" (흐름 {self.flow_actions})")
        line += (f" · 세트 {self.set_cards} · 묘지 {self.grave_cards} ·"
                 f" 제외 {self.banished_cards} · 엑스트라 {self.extra_left} ·"
                 f" 덱 {self.deck_left}")
        if self.limits:
            line += (" · 특수 소환 제한 "
                     + ", ".join(f"{attr}(출처 {src})"
                                 for attr, src in self.limits))
        return line


@dataclass(frozen=True, slots=True)
class OpenCandidate:
    """결과 하나의 평가 칸. 🔴 원래 결과 번호를 들고 있는다."""

    index: int
    verified: bool
    rerun_state: str
    measures: "OpenMeasures | None" = None
    exclusion: Exclusion = Exclusion.NONE
    unmeasurable_reason: str = ""
    nondominated: bool = False
    dominated_by: "tuple[int, ...]" = ()
    order: int = 0

    @property
    def eligible(self) -> bool:
        return self.exclusion is Exclusion.NONE

    @property
    def recommended(self) -> bool:
        return self.eligible and self.nondominated


@dataclass(frozen=True, slots=True)
class OpenRanking:
    """한 자율 탐색 실행의 **추천 전부**."""

    policy: str = POLICY_NAME
    version: str = POLICY_VERSION
    criteria: "tuple[Criterion, ...]" = CRITERIA_OPEN
    unjudged: "tuple[str, ...]" = UNJUDGED_OPEN
    candidates: "tuple[OpenCandidate, ...]" = ()
    note: str = ""

    @property
    def policy_label(self) -> str:
        return f"{self.policy} {self.version}"

    @property
    def eligible_candidates(self) -> "tuple[OpenCandidate, ...]":
        return tuple(one for one in self.candidates if one.eligible)

    @property
    def excluded(self) -> "tuple[OpenCandidate, ...]":
        return tuple(one for one in self.candidates if not one.eligible)

    @property
    def recommended(self) -> "tuple[OpenCandidate, ...]":
        """비지배 후보들 — 표시 순서대로. 🔴 여럿이면 **공동 추천**이다."""
        return tuple(sorted(
            (one for one in self.candidates if one.recommended),
            key=lambda one: (one.order, one.index),
        ))

    @property
    def has_recommendation(self) -> bool:
        return bool(self.recommended)

    def candidate(self, index: int) -> "OpenCandidate | None":
        for one in self.candidates:
            if one.index == index:
                return one
        return None

    def reason_ko(self, index: int) -> str:
        """그 후보가 **왜 추천인가 / 왜 빠졌는가.**"""
        one = self.candidate(index)
        if one is None:
            return f"결과 {index} 를 찾지 못했습니다."
        if one.rerun_state == RerunState.NOT_SELECTED.value:
            #: 🔴 **평가가 보지도 않은 후보를 실패로 적지 않는다.**
            return ("평가 상위에 들지 못해 재생하지 않았습니다 — 🔴 재생"
                    " 실패가 아니고, 경로는 그대로 남아 있습니다.")
        if one.exclusion is Exclusion.NOT_VERIFIED:
            return (f"재생 검증을 통과하지 못해 비교에서 뺐습니다"
                    f" (재생 상태 {one.rerun_state}). 🔴 경로 자체는"
                    f" 그대로 남아 있습니다.")
        if one.exclusion is Exclusion.UNMEASURABLE:
            return f"평가에 필요한 값을 읽지 못했습니다 — {one.unmeasurable_reason}"
        if one.measures is None:
            return "센 값이 없습니다."
        if one.nondominated:
            return ("세 축(필드 몬스터 · 남은 패 · 일반 소환권) 가운데"
                    " 어느 후보에게도 모두 뒤지지 않습니다 — "
                    + one.measures.describe_ko())
        beaten = ", ".join(f"결과 {other}" for other in one.dominated_by)
        return (f"{beaten} 가 세 축 모두에서 뒤지지 않고 적어도 하나에서"
                f" 앞섭니다 — " + one.measures.describe_ko())


# ======================================================================
# 세기
# ======================================================================
def _zone_size(resources, zone) -> "int | None":
    try:
        return int(resources.size(resources.seat, zone))
    except Exception:  # pragma: no cover - 방어용
        return None


def _face_down_spells(resources) -> "int | None":
    summary = resources.zone(resources.seat, Zone.SZONE)
    if summary is None:
        return None
    return sum(1 for slot in summary.cards if not slot.face_up)


def measure_open(path, resources) -> "tuple[OpenMeasures | None, str]":
    """
    후보 하나를 센다 — ``(OpenMeasures | None, 못 센 이유)``.

    🔴 **하나라도 읽을 수 없으면 평가 불가다.** 유리한 기본값으로 메우지
    않는다.
    """
    if resources is None:
        return None, "검증된 상태의 자원 요약이 없습니다."
    try:
        #: ``own_field`` 는 이미 **몬스터 존 + 엑스트라 몬스터 존**만
        #: 담는다 (``agent.bounded_search.FIELD_ZONES``) — 여기서 존을 다시
        #: 거르지 않는다.
        field = sum(1 for slot in resources.own_field if slot.face_up)
    except Exception:  # pragma: no cover - 방어용
        return None, "자기 필드를 읽을 수 없습니다."
    hand = _zone_size(resources, Zone.HAND)
    if hand is None:
        return None, "자기 패 장수를 읽을 수 없습니다."
    used = getattr(resources, "normal_summon_used", None)
    if not isinstance(used, bool):
        return None, "일반 소환권 사용 기록을 읽을 수 없습니다."
    if path is None:
        return None, "경로를 읽을 수 없습니다."
    try:
        kinds = [str(step.kind) for step in path]
    except Exception:  # pragma: no cover - 방어용
        return None, "경로의 걸음 종류를 읽을 수 없습니다."
    flow = sum(1 for kind in kinds if kind in FLOW_ACTION_KINDS)
    sets = _face_down_spells(resources)
    return OpenMeasures(
        field_monsters=field,
        hand_left=hand,
        normal_summon_used=used,
        spend_actions=len(kinds) - flow,
        flow_actions=flow,
        set_cards=0 if sets is None else sets,
        grave_cards=_zone_size(resources, Zone.GRAVE) or 0,
        banished_cards=_zone_size(resources, Zone.REMOVED) or 0,
        extra_left=_zone_size(resources, Zone.EXTRA) or 0,
        deck_left=_zone_size(resources, Zone.DECK) or 0,
        limits=tuple(getattr(resources, "own_limits", ())),
    ), ""


def _dominates(better: OpenMeasures, worse: OpenMeasures) -> bool:
    """
    세 축에서 앞의 것이 뒤의 것을 지배하는가.

    🔴 **세 축뿐이다** — 필드에 남은 앞면 몬스터 · 남은 패 · 일반 소환권.
    모두 뒤지지 않고 최소 하나가 앞서면 지배한다. 🔴 지배당한 후보가
    **실제로 더 좋을 수 있다** (이 기준이 보지 못하는 것이
    :data:`UNJUDGED_OPEN` 에 적혀 있다).
    """
    mine, theirs = better.axes, worse.axes
    if any(a < b for a, b in zip(mine, theirs)):
        return False
    return any(a > b for a, b in zip(mine, theirs))


def _display_key(measures: OpenMeasures) -> tuple:
    """표시 순서 — 축을 크게, 그다음 **짧은 경로**를 먼저."""
    return (-measures.field_monsters, -measures.hand_left,
            -int(measures.summon_right_kept), measures.spend_actions)


def select_top(pool, count: int) -> "frozenset[int]":
    """
    모아 둔 후보 풀에서 **재생할 자리 번호**를 고른다 (Phase 6-BB).

    ``pool`` 은 ``(경로, 자원 요약, 사유)`` 의 차례열이다 —
    :meth:`agent.bounded_search.BoundedSearch.run_many` 의 ``rerun_select``
    가 그대로 넘겨 준다.

    🔴 **고르지 않은 후보를 버리지 않는다.** 재생만 하지 않을 뿐이고, 경로는
    결과에 그대로 남는다 (``RerunState.NOT_SELECTED``).
    """
    rows = []
    for slot, item in enumerate(pool):
        path, resources = item[0], item[1]
        measures, _why = measure_open(path, resources)
        if measures is None:
            continue
        rows.append((slot, measures))
    if not rows:
        return frozenset(range(min(len(pool), max(1, int(count)))))
    #: 🔴 **비지배 후보를 먼저** 넣고, 모자라면 표시 순서로 채운다.
    best = [slot for slot, mine in rows
            if not any(_dominates(other, mine)
                       for slot2, other in rows if slot2 != slot)]
    ordered = [slot for slot, _m in sorted(
        rows, key=lambda row: (_display_key(row[1]), row[0]))]
    chosen: list[int] = []
    for slot in ordered:
        if slot in best and slot not in chosen:
            chosen.append(slot)
        if len(chosen) >= count:
            break
    for slot in ordered:
        if len(chosen) >= count:
            break
        if slot not in chosen:
            chosen.append(slot)
    return frozenset(chosen)


def rank_open(outcome) -> "OpenRanking | None":
    """
    자율 탐색의 **검증된 결과**를 견주고 추천 후보를 고른다.

    🔴 **받은 것을 바꾸지 않는다.** 값만 읽고 새 :class:`OpenRanking` 을
    만든다. 🔴 **검증된 결과만 추천 대상**이고, 나머지는 원래 사유와 함께
    남는다.
    """
    if outcome is None:
        return None
    results = tuple(getattr(outcome, "results", ()) or ())
    rows: list[OpenCandidate] = []
    measured: dict[int, OpenMeasures] = {}
    for result in results:
        state = getattr(result.rerun_state, "value", str(result.rerun_state))
        if not result.verified:
            #: 🔴 **순위 밖이라 재생하지 않은 것**과 **재생이 실패한 것**을
            #: 가른다 (Phase 6-BB) — 섞으면 "검증을 통과하지 못했다" 로
            #: 읽혀서, 평가가 보지도 않은 후보가 실패한 것처럼 보인다.
            rows.append(OpenCandidate(
                index=result.index, verified=False, rerun_state=state,
                exclusion=(
                    Exclusion.UNMEASURABLE
                    if result.rerun_state is RerunState.NOT_SELECTED
                    else Exclusion.NOT_VERIFIED
                ),
                unmeasurable_reason=(
                    "평가 상위에 들지 못해 재생하지 않았습니다 — 🔴 재생"
                    " 실패가 아니고, 경로는 그대로 남아 있습니다."
                    if result.rerun_state is RerunState.NOT_SELECTED else ""
                ),
            ))
            continue
        measures, why = measure_open(result.path, result.resources)
        if measures is None:
            rows.append(OpenCandidate(
                index=result.index, verified=True, rerun_state=state,
                exclusion=Exclusion.UNMEASURABLE, unmeasurable_reason=why,
            ))
            continue
        measured[result.index] = measures
        rows.append(OpenCandidate(index=result.index, verified=True,
                                  rerun_state=state, measures=measures))

    final: list[OpenCandidate] = []
    for one in rows:
        if one.index not in measured:
            final.append(one)
            continue
        mine = measured[one.index]
        beaten_by = tuple(sorted(
            other for other, theirs in measured.items()
            if other != one.index and _dominates(theirs, mine)
        ))
        final.append(OpenCandidate(
            index=one.index, verified=True, rerun_state=one.rerun_state,
            measures=mine, nondominated=not beaten_by,
            dominated_by=beaten_by,
        ))

    order = sorted(
        (one for one in final if one.measures is not None),
        key=lambda one: (_display_key(one.measures), one.index),
    )
    places = {one.index: place for place, one in enumerate(order, start=1)}
    final = [
        OpenCandidate(
            index=one.index, verified=one.verified,
            rerun_state=one.rerun_state, measures=one.measures,
            exclusion=one.exclusion,
            unmeasurable_reason=one.unmeasurable_reason,
            nondominated=one.nondominated, dominated_by=one.dominated_by,
            order=places.get(one.index, 0),
        )
        for one in final
    ]
    note = ""
    if not measured:
        note = ("검증된 결과가 없어 비교하지 않았습니다 — 🔴 경로는 그대로"
                " 남아 있습니다.")
    elif len(measured) == 1:
        note = "검증된 결과가 하나뿐이라 비교할 상대가 없습니다."
    return OpenRanking(candidates=tuple(final), note=note)
