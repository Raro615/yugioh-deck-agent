"""
Phase 6-AE — **``/combo`` 의 기본 요약과 상세 첨부.**

무엇이 틀렸었는가
-----------------
사용자가 아래 조건으로 실행했고, 실행은 **정상**이었다 (지정 경로 4/4 ·
실행 5걸음 · 효과의 조작 수행 2걸음 · 갈라테아 링크 소환 성공)::

    hand:   69811710,703897,2930675,12989604,93920420
    line:   orcust-girsu
    recipe: ORCUST_VERIFICATION_RECIPE

그런데 **출력**이 네 가지로 읽을 수 없었다 (실측).

====================================  ==================================
같은 미지원 사유가 걸음마다 반복됐다     2건이 **6번씩**
경로 완료와 지원 범위 미완료가 섞였다    ✅ 와 🔴 가 같은 묶음에
실제 실행 뒤에 정적 계획이 길게 붙었다   응답의 절반
마지막에 누락 안내가 붙었다             *"길이 제한으로 10줄을 보내지
                                      못했습니다"* (4메시지 7,749자)
====================================  ==================================

이 파일이 고정하는 것
---------------------
🔴 **엔진을 건드리지 않았다.** 이 묶음은 **출력만** 잰다 — 같은 입력의
실행 결과가 그대로인지는 ``test_combo_output_consistency`` ·
``test_orcust_girsu_line`` 이 재고, 여기서는 **렌더링이 판을 바꾸지
않는다**는 것까지 본다 (``test_e01``).

🔴 **합성 기록과 실제 실행을 가른다.** ``test_a*`` · ``test_g*`` ·
``test_h*`` 는 실제 카드로 ``/combo`` 를 돌리고, ``test_c*`` ~ ``test_f*`` ·
``test_i*`` · ``test_j*`` 는 **손으로 만든 기록**을 요약 함수에 넣는다 —
그쪽은 "렌더러가 이 입력에 이렇게 답한다" 는 단위 시험이고 "실제 듀얼에서
그 일이 일어났다" 는 뜻이 아니다.
"""

from __future__ import annotations

import pytest

import app.discord_bot as bot
from deck.combo_policy import ORCUST_VERIFICATION_RECIPE, line_named
from deck.opening import ExecutedStep, OpeningRun, OpeningSetup
from deck.report import render_opening_brief
from tests.conftest import requires_official_db

GIRSU = 69811710
WAND = 93920420
GALATEA = 30741503
HAND_OK = "69811710,703897,2930675,12989604,93920420"
#: 패의 매수가 덱 보유 매수를 넘는다 — 입력 검증이 거절한다.
HAND_OVER = "69811710,69811710,69811710,69811710,93920420"
LINE = "orcust-girsu"


class _Agent:
    def __init__(self, repository):
        self.repository = repository


def _response(repository, hand: str = HAND_OK, *, recipe: str | None = None,
              line: str = LINE) -> bot.ComboResponse:
    return bot.combo_response(
        _Agent(repository), hand,
        recipe_text=ORCUST_VERIFICATION_RECIPE if recipe is None else recipe,
        line_text=line,
    )


def _summary(response: bot.ComboResponse) -> str:
    return "\n".join(response.messages)


def _detail(response: bot.ComboResponse) -> str:
    return "\n".join(item.text for item in response.attachments)


# ======================================================================
# 합성 기록 — 🔴 **듀얼을 돌리지 않는다**
# ======================================================================
class _FakeZone(list):
    pass


class _FakeCard:
    def __init__(self, card_id: int):
        self.card_id = card_id


class _FakePlayer:
    def __init__(self, zones):
        self._zones = zones

    def zone(self, zone):
        return self._zones.get(zone, [])


class _FakeState:
    def __init__(self, zones):
        self._player = _FakePlayer(zones)
        self.reads = 0

    def player(self, index: int):
        self.reads += 1
        return self._player


class _FakeDuel:
    def __init__(self, zones):
        self.state = _FakeState(zones)


def _setup(zones=None, *, blockers=(), unverifiable=()) -> OpeningSetup:
    """
    요약 함수가 읽는 칸만 가진 **합성 입력**.

    🔴 ``duel`` 이 ``None`` 이면 ``can_run`` 이 거짓이므로, 실행한 경우를
    재려면 가짜 판을 하나 둔다 — 그 판은 **읽기만** 당한다.
    """
    from engine.vocabulary import Zone

    made = OpeningSetup()
    made.duel = None if zones is None else _FakeDuel(
        {getattr(Zone, name): [_FakeCard(c) for c in ids]
         for name, ids in zones.items()}
    )
    made.blockers = list(blockers)
    made.findings = list(unverifiable)
    return made


def _step(order: int, kind: str, **over) -> ExecutedStep:
    """합성 걸음 하나. **기본값은 성공한 걸음**이다."""
    spec = dict(
        order=order, actor=0, kind=kind, card_id=None, card_name="",
        effect_ref=None, targets=(), gate_code="OK", accepted=True,
        step_code="OK", reason="(합성 기록)", chain_links_after=0,
        chain_resolved_after=0, resolved=True, state_changed=True,
        effect_events=(), next_candidates=0,
    )
    spec.update(over)
    return ExecutedStep(**spec)


def _run(steps, **over) -> OpeningRun:
    made = OpeningRun(setup=OpeningSetup())
    made.steps = list(steps)
    for key, value in over.items():
        setattr(made, key, value)
    return made


# ======================================================================
# A · B. 정상 경로 — 실제 카드
# ======================================================================
@pytest.mark.real_card
@requires_official_db
def test_a01_the_normal_run_fits_in_the_default_answer(repository):
    """
    **A** — 정상 4/4 실행의 기본 응답이 **전송 제한 안에** 들어간다.

    🔴 **그리고 누락 안내가 없다** — 이것이 사용자가 보고한 증상이다.
    """
    response = _response(repository)
    assert response.messages
    for text in response.messages:
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT, len(text)
    #: 🔴 메시지 수를 늘려 해결하지 않았다.
    assert len(response.messages) <= bot.COMBO_MESSAGE_LIMIT
    summary = _summary(response)
    assert "보내지 못했습니다" not in summary
    assert bot.TRUNCATION_NOTICE.strip() not in summary


@pytest.mark.real_card
@requires_official_db
def test_a02_the_default_answer_keeps_the_five_sections(repository):
    """**A** — 요약이 §2 의 다섯 절을 전부 들고 있다."""
    summary = _summary(_response(repository))
    #: ① 실행 결과 요약
    assert f"검증용 전개 경로 `{LINE}`" in summary
    assert "경로를 끝까지 실행했습니다 (4/4단계)" in summary
    assert "실행 5걸음" in summary
    assert "**효과의 조작 수행 2걸음**" in summary
    #: 🔴 "지정 경로이고 자율 탐색이 아니다" 는 **한 번만** 적는다.
    assert summary.count("최선 전개 탐색도") == 1
    #: ② 실제 실행한 주요 행동 — 한국어 카드명으로
    assert "일반 소환 — 잭나이츠 오르페골 기르수" in summary
    assert "링크 소환 — 오르페골 갈라테아" in summary
    assert "소재: 잭나이츠 오르페골 기르수 · 성유물－『성장』" in summary
    assert "해결 중 선택: 성유물－『성장』" in summary
    #: ③ 최종 상태 — 두 몬스터 존을 가르고 이름을 적는다
    assert "몬스터 존: 없음" in summary
    assert "엑스트라 몬스터 존: 오르페골 갈라테아" in summary
    assert "마법·함정 존: 없음" in summary
    assert "패 3장: 오르페골 클리막스" in summary
    assert "묘지 3장:" in summary
    assert "남은 덱 34장 · 엑스트라 덱 5장" in summary
    #: ④ 멈춘 이유 — 원문이 아니라 뜻
    assert "지정 경로를 완료했습니다" in summary
    assert "이후 행동은 이 검증 경로에 지정되지 않았습니다" in summary
    assert "not_chosen" not in summary
    #: ⑤ 검증의 한계 — 짧지만 "검증 불가" 를 지우지 않는다
    assert "검증 불가 2건" in summary
    assert "문제 없음이 아닙니다" in summary


@pytest.mark.real_card
@requires_official_db
def test_b01_route_completion_and_unsupported_scope_stay_separate(repository):
    """
    **B** — 경로는 완료했고 **다른 행동에 미지원이 있었다.** 둘을 섞지 않는다.

    🔴 **미지원 경고가 있다는 이유로 실행한 경로를 실패처럼 적지 않는다.**
    """
    summary = _summary(_response(repository))
    assert "✅" in summary and "경로를 끝까지 실행했습니다" in summary
    assert "엔진이 지원하지 않아 후보가 되지 못한 것이 2건" in summary
    #: 🔴 **두 문장이 따로 있다** — 경로 완료는 "이 패의 전개를 다 했다" 가
    #: 아니고, 미지원은 "규칙이 막았다" 가 아니다.
    assert "이 패로 가능한 전개를 다 보았다는 뜻이 아닙니다" in summary
    assert "이 패의 전개를 다 했다**로 읽을 수 없습니다" in summary
    #: 🔴 경로 완료 줄에 실패 표시가 붙지 않는다.
    completion = next(l for l in summary.splitlines()
                      if "경로를 끝까지 실행했습니다" in l)
    assert "🔴" not in completion


@pytest.mark.real_card
@requires_official_db
def test_b02_each_unsupported_reason_appears_once(repository):
    """
    **B · I** — 같은 미지원 사유가 **한 번씩만** 나온다 (사용자 증상 ①).

    실측 (6-AD): 같은 두 사유가 응답 안에 **6번씩** 있었다.
    """
    summary = _summary(_response(repository))
    for needle in ("link-material-requirement", "activation-timing"):
        assert summary.count(needle) == 1, (needle, summary.count(needle))
    #: 🔴 **합치면서 구분을 잃지 않았다** — 행동 종류와 빠진 규칙의 이름이
    #: 둘 다 남아 있고, 그래서 두 줄이 서로 다른 줄이다.
    assert "link_summon [link-material-requirement" in summary
    assert "activate_card [activation-timing" in summary
    #: 🔴 "어디서 만났는가" 를 적는다 — 자리와 도중을 섞지 않는다.
    assert "걸음이 끝난 자리" in summary


@pytest.mark.real_card
@requires_official_db
def test_b03_the_static_plan_is_not_appended_after_a_real_run(repository):
    """
    **B** — 실제 실행 뒤에 정적 계획을 **길게 붙이지 않는다** (사용자 증상 ③).

    🔴 그러나 **없애지도 않는다** — 첨부에 전부 있고, 요약은 그것이 실행이
    아니라는 사실을 한 줄로 적는다.
    """
    response = _response(repository)
    summary, detail = _summary(response), _detail(response)
    assert "**[정적 계획은 첨부에 있습니다]**" in summary
    assert "위 실행의 다음 행동도 아닙니다" in summary
    #: 요약에는 걸음별 상세가 없다.
    assert "상태: 돌려볼 수 있음 (정적 확인)" not in summary
    #: 첨부에는 있고, 실행 기록과 **머리말로 갈라져** 있다.
    assert "상태: 돌려볼 수 있음 (정적 확인)" in detail
    assert detail.index("[실제 엔진 실행]") < detail.index(
        "[아래는 실행하지 않은 정적 계획입니다]")


@pytest.mark.real_card
@requires_official_db
def test_b04_the_detail_attachment_keeps_the_whole_record(repository):
    """**B** — 첨부가 **원래의 기록**을 하나도 잃지 않았다."""
    response = _response(repository)
    detail = _detail(response)
    assert len(response.attachments) == 1
    assert response.attachments[0].filename == bot.COMBO_DETAIL_FILENAME
    for needle in (
        "선공 상태 구성",                    # 입력과 초기 상태
        "검증 통과 10건",
        "금지·제한 (리미트 레귤레이션)",      # 모든 검증 한계
        "🔴 실제 엔진 실행 (검증된 걸음)",     # 걸음별 기록
        "판정 OK · 수락 예 · 결과 OK",
        "해결 중 선택 1장:",
        "소재 2장:",
        "적용된 효과 기록:",
        "막히지 않고 끝난 걸음",
        "효과의 조작이 실제로 수행된 걸음",
        "이 전개 중에 만난 **미지원 사유**",
        "현재까지의 결과 (실제 GameState)",
        "[아래는 실행하지 않은 정적 계획입니다]",
    ):
        assert needle in detail, needle
    #: 🔴 첨부는 UTF-8 바이트로 나간다 (파일명에 사용자 입력이 없다).
    assert response.attachments[0].data.decode("utf-8") == detail


# ======================================================================
# C ~ F. 네 결과 — 🔴 **합성 기록**으로 렌더러를 잰다
# ======================================================================
def test_c01_an_incomplete_route_is_not_written_as_completed():
    """
    **C** — 경로 미완료 + ``not_chosen`` 을 **완료처럼 적지 않는다**.
    """
    line = line_named(LINE)
    progress = type("P", (), {"completed": False, "done": 2, "line": line,
                              "describe_ko": lambda self: "🔴 경로가 2/4단계에서 멈췄습니다"})()
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU]}),
        _run([_step(1, "normal_summon", card_id=GIRSU, card_name="기르수")],
             stopped_kind="not_chosen",
             stopped_candidates=("end_phase", "pass")),
        line=line, progress=progress,
    )
    assert "경로가 2/4단계에서 멈췄습니다" in said
    assert "지정 경로를 완료했습니다" not in said
    assert "✅ **지정 경로를 완료" not in said
    assert "남은 후보: 턴 종료 · 우선권 넘김" in said


def test_d01_a_normal_no_op_is_shown_as_such():
    """
    **D** — 정상 불발: 해결됐으나 조작 없음. 🔴 **전개 목표 달성이 아니다.**
    """
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU]}),
        _run([
            _step(1, "activate_effect", card_id=WAND, card_name="『성장』",
                  effect_ref=f"{WAND}:e[1]", state_changed=False,
                  resolved_without_operation=True,
                  reason="해결되었지만 일을 하지 않았습니다 — 빈 칸이 없습니다"),
        ], stopped_kind="flow_only"),
    )
    assert "🔴 해결됐지만 조작 없음" in said
    assert "미지원도 오류도 아닙니다" in said
    #: 🔴 **이유를 생략하지 않는다.**
    assert "빈 칸이 없습니다" in said
    #: 🔴 성공(조작 수행)으로 적지 않는다.
    assert "조작 수행" not in said.replace("조작 수행 0걸음", "")
    assert "**효과의 조작 수행 0걸음**" in said


def test_e01_an_unknown_resolution_is_not_a_normal_no_op():
    """
    **E** — ``UNKNOWN`` 으로 해결 미확정. 🔴 정상 불발로 **위장하지 않는다**.
    """
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU]}),
        _run([
            _step(1, "activate_effect", card_id=WAND, card_name="『성장』",
                  effect_ref=f"{WAND}:e[1]", accepted=True, resolved=False,
                  state_changed=False, step_code="RULE_NOT_IMPLEMENTED",
                  reason="후보를 지금 쓸 수 있는지 판정하지 못했습니다"),
        ], stopped_kind="flow_only"),
    )
    assert "🔴 해결 미확정 (모름)" in said
    assert "해결됐지만 조작 없음" not in said
    assert "판정하지 못했습니다" in said


def test_f01_a_refused_choice_stays_a_refusal():
    """**F** — 잘못된 선택 · 확정 거부를 **거절로** 적는다."""
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU]}),
        _run([
            _step(1, "activate_effect", card_id=WAND, card_name="『성장』",
                  effect_ref=f"{WAND}:e[1]", accepted=True, resolved=False,
                  state_changed=False, step_code="CANDIDATE_NOT_ELIGIBLE",
                  reason="후보가 아닌 카드가 들어왔습니다"),
        ], stopped_kind="rejected"),
    )
    assert "🔴 거절" in said
    assert "해결됐지만 조작 없음" not in said
    assert "해결 미확정" not in said
    assert "후보가 아닌 카드가 들어왔습니다" in said


def test_f02_the_four_outcomes_come_from_the_record_not_the_sentence():
    """
    🔴 **문장을 다시 파싱해 추측하지 않는다** (6-AE §5).

    네 결과는 :meth:`~deck.opening.ExecutedStep.outcome` 이 **이미 기록된
    칸들**에서 낸다 — 같은 ``reason`` 문장이라도 칸이 다르면 답이 다르다.
    """
    same_reason = "같은 문장"
    operated = _step(1, "activate_effect", effect_ref="1:e[0]",
                     effect_events=("1:e[0]",), reason=same_reason)
    idle = _step(1, "activate_effect", effect_ref="1:e[0]",
                 resolved_without_operation=True, state_changed=False,
                 reason=same_reason)
    unknown = _step(1, "activate_effect", effect_ref="1:e[0]", resolved=False,
                    step_code="RULE_NOT_IMPLEMENTED", reason=same_reason)
    refused = _step(1, "activate_effect", effect_ref="1:e[0]", resolved=False,
                    step_code="CANDIDATE_NOT_ELIGIBLE", reason=same_reason)
    assert [s.outcome for s in (operated, idle, unknown, refused)] == [
        "operated", "idle", "unknown", "refused",
    ]
    #: 🔴 효과를 발동하지 않은 걸음은 넷 중 어느 것도 아니다.
    assert _step(1, "normal_summon").outcome == "flow"


# ======================================================================
# G · H. 실제 실행이 없는 경우
# ======================================================================
@pytest.mark.real_card
@requires_official_db
def test_g01_no_recipe_says_so_first_and_calls_the_plan_a_reference(
    repository,
):
    """
    **G** — 레시피가 없어 실행하지 않았다. 🔴 그 사실이 **먼저**다.

    그리고 정적 계획은 **"실행하지 않은 참고 계획"** 이다 — 실행 걸음 수나
    성공 표시를 만들지 않는다.
    """
    response = _response(repository, recipe="", line="")
    summary = _summary(response)
    assert "🔴 **하지 않았습니다** — 실제 덱 레시피가 없습니다." in summary
    assert "**[실행하지 않은 참고 계획]**" in summary
    assert "아래 걸음 수는 실행 걸음이 **아닙니다.**" in summary
    #: 🔴 실행한 것처럼 적지 않는다.
    assert "엔진이 실제로" not in summary
    assert "전개 실행 요약" not in summary
    assert summary.index("하지 않았습니다") < summary.index(
        "[실행하지 않은 참고 계획]")
    #: 🔴 **이때는 계획을 줄이지 않는다** — 그것이 응답의 내용 전부다.
    assert "상태: " in summary


@pytest.mark.real_card
@requires_official_db
def test_h01_a_refused_input_is_not_the_same_as_a_missing_recipe(repository):
    """
    **H** — 레시피 · 패 검증 실패는 "레시피 미제공" 과 **다르게** 적는다.
    """
    response = _response(repository, hand=HAND_OVER)
    summary = _summary(response)
    #: 🔴 거절이고, 그 이유가 적힌다.
    assert "실행하지 않았습니다" in summary
    assert "패 4장 > 덱 3장" in summary
    #: 🔴 "레시피가 없다" 와 섞지 않는다.
    assert "실제 덱 레시피가 없습니다" not in summary
    #: 🔴 거절한 입력에는 참고 계획조차 내지 않는다 (6-AA 의 계약).
    assert "정적 전개 추천은 내지 않았습니다" in summary
    assert "[실행하지 않은 참고 계획]" not in summary
    #: 🔴 걸음 수도 성공 표시도 만들지 않는다.
    assert "실행 5걸음" not in summary
    #: 🔴 그래도 전체 검증 결과는 첨부에 남는다.
    assert "선공 상태 구성" in _detail(response)


# ======================================================================
# I · J. 긴 기록 · 비공개 정보
# ======================================================================
def test_i01_a_long_record_is_summarised_without_hiding_the_rest():
    """
    **I** — 긴 기록과 많은 미지원 사유에서도 동작한다.

    🔴 **버린 사실을 숨기지 않는다** — 몇 줄을 뺐는지 적고 상세 기록을
    가리킨다.
    """
    steps = [
        _step(index, "activate_effect", card_id=index,
              card_name="아주 긴 카드 이름을 가진 몬스터" * 2,
              effect_ref=f"{index}:e[0]", effect_events=(f"{index}:e[0]",))
        for index in range(1, 41)
    ]
    reasons = [f"activate_card [rule-{index}]: 사유 {index}"
               for index in range(1, 21)]
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU], "HAND": list(range(1, 31))}),
        _run(steps, stopped_kind="flow_only", unsupported=reasons),
    )
    #: ① 걸음 요약이 상한에서 멈추고 **뺀 줄 수를 적는다.**
    assert "걸음 요약" in said and "상세 기록**에 있습니다" in said
    assert "버리지 않았습니다" in said
    #: ② 미지원 사유도 같다.
    assert f"미지원으로" not in said  # (문구 혼동 방지)
    assert "사유 1" in said
    assert "남은 14건은 **상세 기록**에 있습니다" in said
    #: ③ 긴 구역의 이름도 상한까지만 적고 수를 적는다.
    assert "이름 전체는 상세 기록" in said


def test_j01_the_opponents_hidden_reason_is_not_newly_exposed():
    """
    **J** — 상대 자리의 사유에 **비공개 정보가 새로 들어가지 않는다.**

    🔴 요약은 ``run.unsupported`` 의 문장을 **그대로** 옮긴다 — 보완8
    마무리가 그 문장에서 ``reason`` 을 뺀 이유(뒷면 카드의 ``EffectRef`` 가
    그 카드의 정체다)가 그대로 유지된다. 이 묶음은 요약이 **무엇도 더하지
    않는다**는 것을 고정한다.
    """
    elsewhere = ("activate_effect [trap-activation-event]: P1 의 기회에서"
                 " 만났고 어느 카드인지는 전개 보고의 관측 밖입니다.")
    said = render_opening_brief(
        _setup({"MZONE": [GIRSU]}),
        _run([_step(1, "normal_summon", card_id=GIRSU, card_name="기르수",
                    unsupported_during=(elsewhere,))],
             stopped_kind="flow_only", unsupported=[elsewhere]),
    )
    assert elsewhere in said
    assert "어느 카드인지는 전개 보고의 관측 밖입니다" in said
    #: 🔴 요약이 카드 번호나 효과 참조를 **새로** 붙이지 않았다.
    body = said[said.index("지원 범위"):]
    assert "e[" not in body
    assert "[1" not in body.replace("[trap-activation-event]", "")
    #: 🔴 "자동 처리 도중" 으로 적는다 — 그 자리의 사실이 아니다.
    assert "자동 처리 도중 1걸음" in said


def test_j02_rendering_does_not_touch_the_state():
    """
    🔴 **실행 결과를 렌더링해도 판이 바뀌지 않는다** (6-AE §5).

    가짜 판은 ``player(...)`` 를 **읽기만** 당한다 — 쓰는 메서드가 없으므로
    쓰려 했다면 ``AttributeError`` 로 깨진다. 읽은 횟수가 0이 아닌 것이
    "정말 그 판을 보았다" 는 증거다.
    """
    setup = _setup({"MZONE": [GIRSU], "EMZONE": [GALATEA]})
    render_opening_brief(setup, _run([_step(1, "normal_summon")]))
    assert setup.duel.state.reads > 0


# ======================================================================
# 길이 제한과 전달
# ======================================================================
def test_k01_the_attachment_is_split_not_truncated():
    """
    **첨부가 상한을 넘으면 나눈다** — 버리지 않는다 (6-AE §4).
    """
    text = "\n".join(f"줄 {index}" for index in range(1, 2001))
    parts = bot.combo_attachments(text, limit=4096)
    assert len(parts) > 1
    for part in parts:
        assert part.size <= 4096, part.size
    #: 🔴 한 줄도 사라지지 않았다.
    rebuilt = "\n".join(part.text for part in parts)
    assert rebuilt.splitlines() == text.splitlines()
    #: 🔴 파일명이 갈라지고, 사용자 입력이 들어가지 않는다.
    assert [part.filename for part in parts[:2]] == [
        "combo-detail-1.txt", "combo-detail-2.txt",
    ]


def test_k02_one_file_keeps_the_plain_name():
    """상한 안에 들어가면 **나누지 않는다** — 이름도 그대로다."""
    parts = bot.combo_attachments("짧은 기록")
    assert [p.filename for p in parts] == [bot.COMBO_DETAIL_FILENAME]
    assert parts[0].text == "짧은 기록"


def test_k03_a_line_longer_than_the_limit_is_split_by_characters():
    """한 줄이 상한을 넘어도 **버리지 않는다.**"""
    parts = bot.combo_attachments("가" * 500, limit=256)
    assert len(parts) > 1
    assert "".join(p.text for p in parts).replace("\n", "") == "가" * 500
    for part in parts:
        assert part.size <= 256, part.size


def test_k04_too_many_parts_say_how_much_did_not_fit():
    """
    첨부 수 상한을 넘으면 **몇 줄을 담지 못했는지 적는다** — 조용히 끊지
    않는다. 🔴 실측 범위(상세 15KB)에서는 일어나지 않는다.
    """
    text = "\n".join(f"줄 {index}" for index in range(1, 400))
    parts = bot.combo_attachments(text, limit=256, count_limit=2)
    assert len(parts) == 2
    assert "담지 못했습니다" in parts[-1].text
    assert "CLI" in parts[-1].text


def test_k05_the_overflow_notice_points_at_the_attachment():
    """
    🔴 **잘림 안내가 "어디서 전체를 볼 수 있는가" 를 가리킨다** (6-AE §4).

    그리고 **몇 줄이 빠졌는지도 그대로 적는다** — 가리킬 곳이 있다는 사실이
    누락을 지우지 않는다.
    """
    pages = bot.paginate([f"줄 {i}" * 30 for i in range(200)],
                         max_messages=2,
                         overflow_notice="첨부를 보세요.")
    assert len(pages) == 2
    assert "줄을 보내지 못했습니다" in pages[-1]
    assert "첨부를 보세요." in pages[-1]


# ======================================================================
# CLI — 🔴 **공용 보고 함수를 고쳐서 CLI 내용이 사라지지 않았다**
# ======================================================================
def test_l01_the_cli_still_prints_the_whole_record():
    """
    🔴 **CLI 는 전체 기록을 그대로 본다** (6-AE §4 의 마지막 줄).

    요약은 **더한 것**이고 바꿔 끼운 것이 아니다 — ``app/main.py`` 가 부르는
    세 함수가 그대로이고, 요약 함수를 부르지 않는다. AST 로 센다 (문장이
    아니라 호출을 본다).
    """
    import ast
    import pathlib

    source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    called = {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"render_opening_setup", "render_opening_run",
            "render_opening_board"} <= called
    #: 🔴 CLI 가 요약으로 **갈아타지 않았다** — 전체를 본다.
    assert "render_opening_brief" not in called
    #: 🔴 그리고 CLI 는 discord 를 **import 하지 않는다** (기존 경계).
    #: 낱말로 세면 주석의 ``tests/test_discord_bot.py`` 인용에 걸린다 —
    #: 그래서 import 문만 본다.
    assert "import discord" not in source


def test_l02_the_shared_renderers_were_not_narrowed():
    """
    🔴 **기존 세 함수의 출력에서 아무 줄도 빼지 않았다.**

    6-AE 가 더한 것은 :func:`~deck.report.render_opening_brief` 하나이고,
    세 함수는 이름도 서명도 그대로다 — 그래서 CLI · 첨부 · 기존 시험이
    같은 것을 본다.
    """
    import inspect

    from deck import report

    for name in ("render_opening_setup", "render_opening_run",
                 "render_opening_board"):
        assert hasattr(report, name), name
    assert list(inspect.signature(report.render_opening_setup)
                .parameters) == ["setup"]
    assert list(inspect.signature(report.render_opening_run)
                .parameters) == ["run"]
    assert list(inspect.signature(report.render_opening_board)
                .parameters) == ["setup", "repository"]
    #: 🔴 ``deck`` 계층은 discord 를 **import 하지 않는다** (6-AE §4).
    assert "import discord" not in inspect.getsource(report)


def test_l03_the_engine_layers_do_not_import_discord():
    """🔴 **Discord SDK 의존성이 엔진 · deck 계층에 들어가지 않았다.**"""
    import pathlib

    for folder in ("engine", "deck"):
        for path in pathlib.Path(folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "import discord" not in text, path
