"""
Phase 6-AK — **검증된 복수 전개 결과의 비교·추천 v1**.

이 파일이 고정하는 사실은 넷이다.

======  ======================================================================
``A``   **평가 정책 v1** — 세 관측값(남은 패 · 일반 소환권 · 비흐름 행동)과
        두 보존 축의 **비지배 후보**. 장단점이 갈리면 둘 다 남고, 동률이면
        공동 후보다. 🔴 임의의 가중치 합계도, 전개 점수도 없다.
``B``   **검증 경계** — ``PathResult.verified`` 인 결과만 추천 대상이다.
        수치가 유리해도 미검증 결과는 추천하지 않고, 원래 사유와 함께
        보존된다. 읽을 수 없는 관측값은 **평가 불가**이고 0 점으로 바꾸지
        않는다.
``C``   **출력** — 기본 응답에 검증 후보 수 · 추천 ID(또는 공동 후보) ·
        이유와 장단점 · 범위 · "최강·승률 평가가 아님" 이 들어가고, 상세에
        후보별 값 · 비지배 선정 이유 · 제외 사유 · **평가하지 못한 차이**가
        들어간다. 🔴 기존 전개 기록 · 자원 비교 · 재생 실패 표시 · 시간 제한
        표시가 그대로다.
``D``   **실제 카드 통합** — 기존 오르페골 입력으로 탐색 → 수집 → 재생 →
        평가 → 출력이 돌고, 실제로 나타난 차이만 보고된다.
======  ======================================================================

🔴 **A · B · C 는 작은 결정적 fixture 로 잰다.** 평가는 값만 읽는 독립
단계이므로(``agent.result_ranking``), 세 관측값을 들고 있는 최소한의 물건으로
경계를 재는 것이 정확하다 — 30초짜리 실제 탐색을 사례마다 반복할 이유가 없다.
🔴 **production 평가 함수와 production 렌더러를 그대로 부른다** — 테스트 안에
평가 알고리즘을 따로 쓰지 않는다. D 절은 실제 카드로 **연결**을 확인한다.

🔴 **이 단계는 강한 집 평가도, 최선 전개 탐색도, 범용 AI 도 아니다.**
자원 보존 중심의 **제한적 휴리스틱**이고, 이 파일은 그 제한이 출력에서
사라지지 않는지도 함께 센다.
"""

from __future__ import annotations

import ast
import dataclasses
import io
from dataclasses import dataclass

import pytest

import agent.result_ranking as ranking_mod
from agent.result_ranking import (
    CRITERIA_V1,
    Candidate,
    Exclusion,
    FLOW_ACTION_KINDS,
    Measures,
    POLICY_NAME,
    POLICY_VERSION,
    Ranking,
    measure_result,
    rank_results,
)

GALATEA = 30741503
P0 = 0


# ======================================================================
# 작은 결정적 fixture — 세 관측값만 들고 있는 최소한의 물건
# ======================================================================
@dataclass(frozen=True, slots=True)
class _Zone:
    seat: int
    zone: str
    size: int


@dataclass(frozen=True, slots=True)
class _Resources:
    """
    ``ResourceSummary`` 가 평가에 내주는 **그 부분만**.

    ``extra_zones`` 는 평가가 **읽지 않는** 자리를 채워 보려고 둔다 (필드 ·
    마·함 존 등) — 그것을 늘려도 추천이 달라지지 않아야 한다 (``test_b05``).
    """

    seat: int
    normal_summon_used: bool
    hand: "int | None" = 0
    extra_zones: "tuple[tuple[str, int], ...]" = ()

    def zone(self, seat, zone):
        name = getattr(zone, "value", str(zone))
        if seat != self.seat:
            return None
        if name == "HAND":
            return (None if self.hand is None
                    else _Zone(seat, name, self.hand))
        for other, size in self.extra_zones:
            if other == name:
                return _Zone(seat, name, size)
        return None


@dataclass(frozen=True, slots=True)
class _Step:
    kind: str


@dataclass(frozen=True, slots=True)
class _Result:
    """``PathResult`` 가 평가에 내주는 **그 부분만**."""

    index: int
    verified: bool
    resources: "object | None"
    path: "tuple[_Step, ...]"
    rerun_state: str = "verified"


@dataclass(frozen=True, slots=True)
class _Outcome:
    results: "tuple[_Result, ...]"


def _one(index, *, hand=3, used=True, steps=("normal_summon",),
         verified=True, state="verified", resources=True, hand_zone=True,
         extra_zones=()):
    res = None
    if resources:
        res = _Resources(
            seat=P0, normal_summon_used=used,
            hand=hand if hand_zone else None,
            extra_zones=tuple(extra_zones),
        )
    return _Result(index=index, verified=verified, resources=res,
                   path=tuple(_Step(kind) for kind in steps),
                   rerun_state=state)


def _ranked(*results):
    return rank_results(_Outcome(tuple(results)))


# ======================================================================
# A. 평가 정책 v1
# ======================================================================
def test_a01_the_policy_records_its_name_version_and_criteria():
    """
    🔴 **정책의 이름 · 판 · 기준을 구조화해서 기록한다** (§3).

    그리고 각 기준은 **무엇을 증명하지 않는지**를 자료형에 들고 있다 —
    보고가 수치만 적고 제한을 빠뜨리면 "패가 많으니 더 좋다" 로 읽힌다.
    """
    result = _ranked(_one(1))
    assert result.policy == POLICY_NAME == "resource-preservation"
    assert result.version == POLICY_VERSION == "v1"
    assert result.policy_label == "resource-preservation v1"
    assert result.criteria == CRITERIA_V1
    assert [one.key for one in CRITERIA_V1] == [
        "hand_left", "normal_summon_right", "spend_actions",
    ]
    for criterion in CRITERIA_V1:
        assert criterion.limit_ko.startswith("🔴"), criterion.key
        assert criterion.reads_ko and criterion.role_ko
    #: 🔴 **표시 순서 기준임을 기준 자체가 말한다.**
    spend = [one for one in CRITERIA_V1 if one.key == "spend_actions"][0]
    assert "표시 순서" in spend.role_ko
    assert "실전적으로 더 좋다는 뜻이" in spend.limit_ko


def test_a02_flow_actions_are_not_counted_as_a_cost():
    """
    🔴 **패스 같은 흐름 행동을 전개 비용으로 세지 않는다** (§3-C).

    세면 "패스를 한 번 더 한 경로" 가 더 비싼 전개로 읽힌다.
    """
    assert "pass" in FLOW_ACTION_KINDS
    measures, why = measure_result(_one(
        1, steps=("normal_summon", "pass", "activate_effect", "end_phase"),
    ))
    assert why == ""
    assert measures.spend_actions == 2
    assert measures.flow_actions == 2
    assert "비용으로 세지 않았습니다" in measures.describe_ko()


def test_a03_a_candidate_better_on_both_axes_wins():
    """🔴 **두 보존 축 모두 우세하면 그 후보만 추천된다** (§3-추천-1)."""
    result = _ranked(
        _one(1, hand=3, used=False, steps=("a", "b", "c")),
        _one(2, hand=2, used=True, steps=("a",)),
    )
    assert result.recommended_ids == (1,)
    assert result.tied is False
    beaten = result.candidate(2)
    assert beaten.nondominated is False
    assert beaten.dominated_by == (1,)
    #: 🔴 **밀렸다는 것이 게임 전체의 우열이 아니라고 말한다.**
    assert "게임 전체에서 더 좋다는 뜻은 아닙니다" in result.reason_ko(2)
    #: 🔴 밀린 후보도 **사라지지 않는다.**
    assert [one.index for one in result.candidates] == [1, 2]


def test_a04_a_trade_off_keeps_both_candidates():
    """
    🔴 **패 보존과 소환권 보존이 상충하면 둘 다 남는다** (§3-추천-1).

    그리고 장단점을 **양쪽 그대로** 적는다 — 어느 쪽이 더 좋은지 고르지
    않는다.
    """
    result = _ranked(
        _one(1, hand=4, used=True, steps=("a", "b")),
        _one(2, hand=2, used=False, steps=("a",)),
    )
    assert set(result.recommended_ids) == {1, 2}
    assert result.tied is True
    assert all(one.nondominated for one in result.eligible_candidates)
    reason = result.reason_ko(1)
    assert "장단점이 갈립니다" in reason
    assert "어느 쪽이 더 좋은지 고르지 않았습니다" in reason
    #: 🔴 비흐름 행동이 적은 쪽을 **먼저 표시**한다 (우열이 아니다).
    assert result.recommended_ids == (2, 1)
    assert [one.order for one in result.recommended] == [1, 2]


def test_a05_equal_axes_differ_only_in_display_order():
    """
    🔴 **보존 축이 같고 행동 수만 다르면 둘 다 남고 순서만 다르다**
    (§3-추천-2).
    """
    result = _ranked(
        _one(1, hand=3, used=True, steps=("a", "b", "c")),
        _one(2, hand=3, used=True, steps=("a",)),
    )
    assert result.recommended_ids == (2, 1)
    assert [one.order for one in result.recommended] == [1, 2]
    assert all(one.dominated_by == () for one in result.eligible_candidates)
    #: 🔴 **"장단점" 이라고 적지 않는다** — 두 보존 축은 같고 다른 것은
    #: **표시 순서 기준**뿐이다. 그렇게 적으면 표시 기준이 전략적 선택처럼
    #: 읽힌다.
    reason = result.reason_ko(1)
    assert "두 보존 축이 같습니다" in reason
    assert "장단점이 갈립니다" not in reason
    assert "표시 순서 기준" in reason


def test_a06_an_all_equal_pair_stays_a_joint_candidate():
    """🔴 **모든 기준이 같으면 공동 후보다** — 억지로 하나로 줄이지 않는다."""
    result = _ranked(
        _one(1, hand=3, used=True, steps=("a", "b")),
        _one(2, hand=3, used=True, steps=("x", "y")),
    )
    assert result.recommended_ids == (1, 2)
    #: 🔴 **같은 표시 자리**다 — 공동 후보라는 뜻이다.
    assert [one.order for one in result.recommended] == [1, 1]
    assert result.tied is True
    assert "모두 같습니다" in result.reason_ko(1)


def test_a07_no_weighted_total_score_exists():
    """
    🔴 **임의의 가중치 합계나 '전개 점수'를 도입하지 않았다** — 코드로 센다.
    """
    source = io.open("agent/result_ranking.py", encoding="utf-8").read()
    for banned in ("score", "weight", "점수", "총점", "순위", "승률"):
        #: 설명문에서 "만들지 않는다" 를 적으므로 **코드만** 센다.
        tree = ast.parse(source)
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        } | {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        assert not [one for one in names if banned in one.lower()], banned
    #: 🔴 ``Measures`` 에 합계 칸이 없다.
    assert [field.name for field in dataclasses.fields(Measures)] == [
        "hand_left", "normal_summon_used", "spend_actions", "flow_actions",
    ]


def test_a08_the_evaluation_never_touches_what_it_reads():
    """
    🔴 **평가 전후로 원본 상태 · 경로 · 재생 결과가 변하지 않는다** (§2).

    받은 것은 전부 frozen 이고, 평가는 새 :class:`Ranking` 만 만든다.
    """
    first = _one(1, hand=3, used=False, steps=("a", "b"))
    second = _one(2, hand=2, used=True, steps=("a",))
    outcome = _Outcome((first, second))
    before = (dataclasses.astuple(first), dataclasses.astuple(second),
              outcome.results)

    result = rank_results(outcome)
    assert result.recommended_ids == (1,)

    assert (dataclasses.astuple(first), dataclasses.astuple(second),
            outcome.results) == before
    #: 🔴 평가 결과도 **값**이다 — 다시 돌려도 같다 (결정적이다).
    again = rank_results(outcome)
    assert again.recommended_ids == result.recommended_ids
    assert [one.order for one in again.candidates] == [
        one.order for one in result.candidates
    ]


# ======================================================================
# B. 검증 경계와 평가 불가
# ======================================================================
def test_b01_an_unverified_result_is_never_recommended():
    """
    🔴 **수치가 유리해도 미검증 결과는 추천하지 않는다** (§2).

    그리고 **원래 사유와 함께** 보존된다 — 재생 상태를 덮어쓰지 않는다.
    """
    result = _ranked(
        _one(1, hand=9, used=False, steps=("a",), verified=False,
             state="mismatched"),
        _one(2, hand=2, used=True, steps=("a", "b")),
    )
    assert result.recommended_ids == (2,)
    excluded = result.excluded
    assert [one.index for one in excluded] == [1]
    assert excluded[0].exclusion is Exclusion.NOT_VERIFIED
    assert excluded[0].rerun_state == "mismatched"
    assert excluded[0].measures is None
    assert "수치가 유리해도" in result.reason_ko(1)
    #: 🔴 경로 자체가 사라지지 않는다 — 모든 결과가 그대로 있다.
    assert [one.index for one in result.candidates] == [1, 2]


@pytest.mark.parametrize("state", [
    "mismatched", "errored", "timed_out", "not_started", "disabled",
])
def test_b02_every_unverified_state_keeps_its_own_reason(state):
    """
    🔴 **불일치 · 실행 예외 · 시간 초과 · 미시작 · 재생 끔**이 각자의 사유로
    남는다 (§2). 평가가 그 다섯을 하나로 뭉개지 않는다.
    """
    result = _ranked(_one(1, verified=False, state=state))
    only = result.candidate(1)
    assert only.eligible is False
    assert only.rerun_state == state
    assert state in result.reason_ko(1)
    assert result.has_recommendation is False
    assert "추천할 검증 결과가 없습니다" in result.note


def test_b03_unreadable_measures_are_never_replaced_with_zero():
    """
    🔴 **평가에 필요한 정보가 없으면 평가 불가다** (§2) — 임의의 0 점이나
    유리한 기본값으로 대체하지 않는다.
    """
    cases = (
        ("자원 요약이 없다", _one(1, resources=False)),
        ("패 장수를 못 읽는다", _one(2, hand_zone=False)),
        ("걸음 종류를 못 읽는다",
         dataclasses.replace(_one(3), path=(_Step(""),))),
    )
    for label, broken in cases:
        result = _ranked(broken)
        only = result.candidate(broken.index)
        assert only.exclusion is Exclusion.UNMEASURABLE, label
        assert only.measures is None, label
        assert only.verified is True, label
        assert only.unmeasurable_reason, label
        assert "0 점이나 유리한 기본값으로 대체하지 않았습니다" in \
            result.reason_ko(broken.index), label
        assert result.has_recommendation is False, label

    #: 🔴 **소환권 기록이 참/거짓이 아니면** 그것도 평가 불가다.
    odd = dataclasses.replace(
        _one(4), resources=_Resources(seat=P0, normal_summon_used=None, hand=3)
    )
    measures, why = measure_result(odd)
    assert measures is None
    assert "일반 소환권" in why


def test_b04_zero_and_one_verified_results_are_named():
    """
    🔴 **검증 결과 0개는 '추천할 검증 결과 없음', 1개는 '유일한 검증 후보'**
    (§2) — 하나뿐일 때 다른 결과보다 우수하다고 말하지 않는다.
    """
    empty = rank_results(_Outcome(()))
    assert empty.candidates == ()
    assert empty.has_recommendation is False
    assert "추천할 검증 결과가 없습니다" in empty.note

    alone = _ranked(_one(1, hand=1, used=True))
    assert alone.recommended_ids == (1,)
    assert alone.only_one_verified is True
    assert "유일한 검증 후보" in alone.note
    assert "다른 결과보다 우수하다는 뜻이 아닙니다" in alone.note
    #: 🔴 공동 후보가 아니다 (하나뿐이다) — 그래도 우월 주장은 없다.
    assert alone.tied is False


def test_b05_a_bigger_field_never_raises_the_recommendation():
    """
    🔴 **필드 카드 수나 세트 카드 수만 늘어도 방해력이 자동으로 오르지
    않는다** (§5).

    평가가 읽는 것은 세 수치뿐이므로, 필드와 세트를 아무리 늘려도 추천이
    바뀌지 않는다 — 그 차이의 유불리는 **이번 기준이 판단하지 못한다.**
    """
    base = _ranked(
        _one(1, hand=3, used=True, steps=("a", "b")),
        _one(2, hand=3, used=True, steps=("a", "b")),
    )
    assert base.recommended_ids == (1, 2)

    #: 결과 2 에 필드 몬스터 다섯 장과 세트 세 장을 붙인다 — 🔴 평가가 읽는
    #: 세 수치가 아니므로 추천이 달라지지 않아야 한다.
    loud = _one(2, hand=3, used=True, steps=("a", "b"),
                extra_zones=(("MZONE", 5), ("SZONE", 3), ("EMZONE", 1)))
    assert loud.resources.zone(P0, "MZONE").size == 5
    after = rank_results(_Outcome((
        _one(1, hand=3, used=True, steps=("a", "b")), loud,
    )))
    assert after.recommended_ids == base.recommended_ids == (1, 2)
    assert [one.order for one in after.recommended] == [1, 1]
    #: 🔴 수치도 그대로다 — 필드가 늘었다고 어떤 값도 오르지 않는다.
    assert after.candidate(2).measures == base.candidate(2).measures
    #: 🔴 그리고 그 차이를 **판단하지 못한다고 이름으로 적어 둔다.**
    joined = " ".join(after.unjudged)
    assert "세트한 카드" in joined
    assert "토큰" in joined
    assert "효과 사용 제한" in joined


# ======================================================================
# C. 출력
# ======================================================================
def test_c01_the_brief_carries_the_five_required_items(capsys):
    """
    🔴 **기본 응답의 다섯 항목** (§4) — 검증 후보 수 · 추천 ID(또는 공동
    후보) · 이유와 장단점 · 범위 · "최강·승률 평가가 아님".
    """
    from deck import report

    result = _ranked(
        _one(1, hand=4, used=True, steps=("a", "b")),
        _one(2, hand=2, used=False, steps=("a",)),
    )
    text = "\n".join(report._ranking_brief(result))

    assert "검증된 후보 2개" in text
    assert "공동 후보: 결과 2 · 결과 1" in text
    assert "장단점이 갈립니다" in text
    assert "탐색에서 발견하고 재생 검증한 후보 사이의 비교" in text
    assert "실전 최강·승률 평가가 아닙니다" in text
    #: 🔴 **언제의 자원인지도 요약에 적는다.**
    assert "처음 도달한 시점" in text
    assert "최종 집의 평가가 아닙니다" in text
    assert f"평가 정책: {result.policy_label}" in text


def test_c02_the_detail_carries_the_values_and_the_limits():
    """
    🔴 **상세 기록의 네 가지** (§4) — 후보별 값 · 비지배 선정 이유 · 제외된
    결과와 사유 · **평가하지 못한 차이**.
    """
    from deck import report

    result = _ranked(
        _one(1, hand=4, used=True, steps=("a", "b")),
        _one(2, hand=2, used=False, steps=("a", "pass")),
        _one(3, hand=9, used=False, steps=("a",), verified=False,
             state="timed_out"),
    )
    text = "\n".join(report._ranking_detail(result))

    assert "정책 이름: resource-preservation" in text
    assert "정책 판: v1" in text
    #: 후보별 값
    assert "남은 패 4장" in text and "남은 패 2장" in text
    assert "비흐름 행동 1회 (흐름 1회는 비용에서 제외)" in text
    #: 비지배 선정 이유
    assert "두 축 모두" in text and "최소 한 축이 더 나은" in text
    assert "안전한 가지치기 근거가" in text
    assert "결과 ID 는 **표시 순서를 가르는 데만**" in text
    #: 제외된 결과와 사유
    assert "추천 대상에서 제외 (1건)" in text
    assert "timed_out" in text
    assert "경로와 자원은 위에 그대로" in text
    #: 평가하지 못한 차이
    assert "유불리를 판단하지 **못한** 차이" in text
    assert "점수로" in text and "바꾸지 않았습니다" in text
    #: 기준마다 제한이 함께 적힌다
    for criterion in CRITERIA_V1:
        assert criterion.limit_ko in text


def test_c03_the_renderers_keep_working_without_a_ranking():
    """
    🔴 **주지 않으면 6-AJ 와 한 글자도 다르지 않다** (§4).

    추천은 **독립 단계**이므로 평가 결과를 주지 않은 호출은 예전 그대로다.
    """
    import inspect

    from deck import report

    assert report._ranking_brief(None) == []
    assert report._ranking_detail(None) == []
    brief = inspect.signature(report.render_multi_search_brief).parameters
    detail = inspect.signature(report.render_multi_search).parameters
    #: 🔴 **맨 뒤의 선택 인자**다 — 기존 호출이 그대로 돈다.
    assert list(brief)[-1] == "ranking" and brief["ranking"].default is None
    assert list(detail)[-1] == "ranking" and detail["ranking"].default is None


def test_c04_the_report_layer_never_imports_agent():
    """
    🔴 **표시 층은 ``agent`` 를 import 하지 않는다** (ADR-007).

    평가는 ``agent.result_ranking`` 이, 표시는 ``deck.report`` 가 하고, 둘을
    잇는 자리는 어댑터 하나(``app.main.rank_search_results``)다.
    """
    tree = ast.parse(io.open("deck/report.py", encoding="utf-8").read())
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        for name in names:
            assert name.split(".")[0] not in {"agent", "integration"}, name

    #: 🔴 평가 모듈도 ``deck`` 과 ``integration`` 을 모른다.
    tree = ast.parse(
        io.open("agent/result_ranking.py", encoding="utf-8").read()
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in {
                "__future__", "engine", "agent", "dataclasses", "enum",
            }, node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in {"dataclasses", "enum"}, \
                    alias.name
    #: 🔴 카드 ID 리터럴이 없다 — 목표도 카드도 밖에서 온다.
    big = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int) and not isinstance(node.value, bool)
        and node.value >= 10_000
    ]
    assert big == [], big


def test_c05_the_adapters_share_one_evaluation_seat():
    """
    🔴 **CLI 와 Discord 가 같은 자리를 쓴다** (§4) — 각자 평가하면 같은
    입력에 다른 추천이 나온다. 그리고 **새 명령도 새 옵션도 만들지 않았다.**
    """
    import inspect

    from app.main import build_parser, rank_search_results

    assert rank_search_results(None) is None

    source = io.open("app/discord_bot.py", encoding="utf-8").read()
    assert "rank_search_results" in source
    assert "result_ranking" not in source, \
        "🔴 어댑터는 agent 를 직접 import 하지 않는다"

    #: 🔴 **추천 때문에 ``/combo`` 의 인자가 늘지 않았다** — 이 시험이 재는
    #: 사실은 그것이다. (Phase 6-AL 이 **다른 기능**으로 ``followups`` 를
    #: 더했으므로, 추천용 인자가 없다는 쪽을 직접 센다.)
    import app.discord_bot as bot

    pytest.importorskip("discord", reason="봇 전용 의존성")
    _client, tree = bot.build_client(dev_guild_id=None, service=object())
    combo = {one.name: one for one in tree.get_commands()}["combo"]
    names = [one.name for one in combo.parameters]
    assert names[:7] == [
        "hand", "board", "deck", "recipe", "line", "search", "results",
    ]
    assert not [one for one in names
                if "rank" in one or "recommend" in one or "추천" in one]
    #: 🔴 CLI 도 그대로다.
    parser = build_parser()
    combo_cli = parser._subparsers._group_actions[0].choices["combo"]
    flags = {
        option
        for action in combo_cli._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    assert "--results" in flags
    assert not {one for one in flags if "rank" in one or "recommend" in one}
    assert "ranking" in inspect.signature(
        __import__("deck.report", fromlist=["report"]).render_multi_search
    ).parameters


# ======================================================================
# D. 실제 카드 통합
# ======================================================================
@pytest.fixture(scope="module")
def repository():
    from core.card_repository import CardRepository

    return CardRepository.build(db_path="data/cards.cdb", script_dir=".")


@pytest.fixture(scope="module")
def real_run(repository):
    """
    기존 오르페골 입력으로 **탐색 → 수집 → 재생 → 평가**까지.

    🔴 적어 둔 경로(``ORCUST_GIRSU_LINE``)를 호출하지 않았다 — 거기서 가져온
    것은 레시피와 시작 패, 즉 **입력**뿐이다.
    """
    from agent.bounded_search import SearchBudget
    from app.main import bounded_search_many_opening, rank_search_results
    from deck.combo_policy import ORCUST_GIRSU_LINE
    from deck.recipe import parse_recipe

    parsed = parse_recipe(ORCUST_GIRSU_LINE.recipe_ydk, repository)
    setup, outcome = bounded_search_many_opening(
        repository, parsed.draft, list(ORCUST_GIRSU_LINE.hand),
        card_id=GALATEA, max_results=3,
        budget=SearchBudget(max_depth=6, max_nodes=400),
    )
    assert outcome is not None
    return setup, outcome, rank_search_results(outcome)


def test_d01_the_real_input_produces_a_recommendation_with_reasons(real_run):
    """
    🔴 **실제 카드에서 추천 후보와 근거가 나온다** (§7).

    그리고 **검증된 결과만** 후보이고, 수치는 실제로 나타난 것이다.
    """
    _setup, outcome, result = real_run
    assert outcome.found >= 2, outcome.describe_ko()
    assert outcome.tally.verified == outcome.found

    assert [one.index for one in result.candidates] == [
        one.index for one in outcome.results
    ]
    assert len(result.verified_candidates) == outcome.found
    assert result.excluded == ()
    assert result.has_recommendation
    for one in result.recommended:
        assert one.measures is not None
        assert one.measures.hand_left >= 0
        reason = result.reason_ko(one.index)
        assert "자원 보존 기준" in reason
        assert f"패 {one.measures.hand_left}장" in reason


def test_d02_the_measures_match_the_verified_resources(real_run):
    """
    🔴 **평가가 읽은 수치가 재생으로 검증된 상태의 것이다** (§2).

    요약을 다시 세지 않고, 그 결과의 ``ResourceSummary`` 와 경로에서 바로
    읽은 값인지 확인한다.
    """
    from engine.vocabulary import Zone

    _setup, outcome, result = real_run
    for path_result in outcome.results:
        candidate = result.candidate(path_result.index)
        assert candidate is not None
        assert candidate.measures is not None
        summary = path_result.resources
        assert candidate.measures.hand_left == summary.size(
            summary.seat, Zone.HAND
        )
        assert candidate.measures.normal_summon_used == \
            summary.normal_summon_used
        spend = sum(
            1 for step in path_result.path
            if step.kind not in FLOW_ACTION_KINDS
        )
        assert candidate.measures.spend_actions == spend


def test_d03_the_order_keeps_every_id_bound_to_its_path(real_run):
    """
    🔴 **정렬 뒤에도 결과 ID 와 상세 경로의 연결이 정확하다** (§4).

    표시 순서는 비흐름 행동 수로 정해지지만, 각 후보가 들고 있는 ID 로
    원래 경로를 되찾을 수 있어야 한다.
    """
    _setup, outcome, result = real_run
    by_index = {one.index: one for one in outcome.results}
    spends = []
    for candidate in result.recommended:
        origin = by_index[candidate.index]
        assert candidate.measures.spend_actions == sum(
            1 for step in origin.path if step.kind not in FLOW_ACTION_KINDS
        )
        spends.append(candidate.measures.spend_actions)
    #: 🔴 **적은 쪽이 먼저**다 (표시 기준이다).
    assert spends == sorted(spends)
    #: 🔴 ID 가 중복되거나 사라지지 않는다.
    assert len({one.index for one in result.candidates}) == outcome.found


def test_d04_the_full_output_keeps_the_old_records(real_run, repository):
    """
    🔴 **기존 전개 기록 · 자원 비교 · 재생 표시 · 시간 제한 표시가 그대로**
    (§4 · §5).

    추천은 그 위에 **붙기만** 한다.
    """
    from deck import report

    setup, outcome, result = real_run
    brief = report.render_multi_search_brief(outcome, repository, result)
    detail = report.render_multi_search(outcome, repository, setup, result)

    #: 추천이 들어왔다.
    assert "추천 — 어느 후보를 먼저 볼까" in brief
    assert "추천 (평가 정책과 후보별 값)" in detail
    #: 🔴 기존 것이 그대로 있다.
    for marker in ("검증된 서로 다른 결과", "결과들의 차이",
                   "탐색 예산에 걸린 칸", "재생 예산에 걸린 칸",
                   "조건: **선공 · 상대 방해 없음**"):
        assert marker in brief, marker
    for marker in ("경로 (행동과 해결 중 선택)", "최종 자원 (실제 GameState)",
                   "재생 (새 초기 상태에서 다시 실행)", "기록된 사용 제한",
                   "결과들의 차이 (검증된 것만)", "재생 메모"):
        assert marker in detail, marker
    #: 🔴 **상대 토큰과 사용 제한의 차이가 보고에서 사라지지 않는다.**
    assert "상대 필드에 남긴 칸" in brief
    assert "기록된 사용 제한" in detail
    #: 🔴 추천 없이 그린 것과 **추천 절만** 다르다.
    plain = report.render_multi_search_brief(outcome, repository)
    assert "추천 — 어느 후보를 먼저 볼까" not in plain
    for line in plain.splitlines():
        if line.strip():
            assert line in brief, line


def test_d05_a_set_only_difference_is_not_called_a_new_strategy(real_run):
    """
    🔴 **세트 여부만 다른 후보를 전략적으로 다른 전개처럼 과장하지 않는다**
    (§5).

    추천 이유에 적히는 것은 세 수치와 그 제한뿐이고, 동률이면 **동률이라고
    말한다.**
    """
    _setup, _outcome, result = real_run
    text = " ".join(
        result.reason_ko(one.index) for one in result.candidates
    ) + " " + " ".join(result.unjudged)
    for banned in ("최강", "승률", "총점", "점수", "전략적으로"):
        assert banned not in text, banned
    if result.tied:
        #: 🔴 **무엇이 갈리는지 셋 중 하나로 정확히 말한다** — 보존 축의
        #: 장단점이 갈리거나, 보존 축은 같고 표시 순서만 다르거나, 세 수치가
        #: 모두 같거나.
        for one in result.recommended:
            reason = result.reason_ko(one.index)
            assert (
                "보존 축의 장단점이 갈립니다" in reason
                or "두 보존 축이 같습니다" in reason
                or "모두 같습니다" in reason
            ), reason
