"""
Phase 6-AA — **/combo 응답이 자기와 모순되지 않는가.**

사용자가 Discord 에서 돌려 보고 넷을 찾았다 (그 실험이 이 파일의 출처다).

    ①  입력을 **거절했는데** 아래 정적 계획이 기르수 소환 · 효과를 나열하고
        "확정" · "엔진이 허가함" 으로 적었다
    ②  ``recipe:`` 로 패 일치를 **검사했는데** 정적 계획이 "덱 초안을 주지
        않아 그 검증을 하지 않았다" 고 적었다
    ③  ``['end_phase']`` 만 남았을 때 "전개가 끝났다" 고 **단정**했다
    ④  "해결 5걸음" 이 **효과를 5번 해결했다**로 읽혔다

🔴 **엔진 판정을 바꾸지 않았다.** 넷 다 표시의 결함이고, 고친 것은 표시다.
②가 특히 그렇다 — 플래너의 판정("나는 그 검사를 하지 않았다")은 **참이고**,
고친 것은 같은 응답 안에서 누가 무엇을 검사했는지를 적지 않은 것이다.

🔴 **토큰 없는 응답 생성 검사다.** 이 파일은 ``combo_messages`` 가 돌려주는
문자열을 센다 — Discord 에 접속하지 않고, 접속했다고 적지도 않는다.
"""

from __future__ import annotations

import pytest

import app.discord_bot as bot
from deck.opening import build_opening, execute_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db

#: 사용자가 실제로 보낸 레시피 그대로.
RECIPE = (
    "69811710 x3, 703897 x3, 2930675 x3, 12989604 x3, 93920420 x3, "
    "21441617 x3, 4055337 x3, 57835716 x3, 94046012 x3, 26845680 x3, "
    "29666221 x3, 47171541 x3, 55051920 x3, 90351981 x1"
)
#: 실험 1 — 정상 입력.
HAND_OK = "69811710, 703897, 2930675, 12989604, 93920420"
#: 실험 3 — 패의 매수가 덱 보유 매수를 넘는다.
HAND_OVER = "69811710, 69811710, 69811710, 69811710, 93920420"


class _Agent:
    def __init__(self, repository):
        self.repository = repository


def _blob(repository, hand: str) -> str:
    """**기본 응답**(Discord 메시지)만 이어 붙인다. 첨부는 들어오지 않는다."""
    return "\n".join(bot.combo_messages(_Agent(repository), hand,
                                        recipe_text=RECIPE))


def _detail(repository, hand: str) -> str:
    """
    **상세 기록 첨부**의 본문 (Phase 6-AE).

    🔴 요약과 첨부를 **따로** 본다 — 이어 붙여 하나로 읽으면 "요약에서
    빠졌다" 와 "어디에도 없다" 를 가를 수 없다. 이 파일이 재려는 것이
    바로 그 구분이다.
    """
    response = bot.combo_response(_Agent(repository), hand,
                                  recipe_text=RECIPE)
    assert response.attachments, "상세 기록 첨부가 없습니다"
    return "\n".join(item.text for item in response.attachments)


def _opened(repository, hand: "list[int]"):
    """
    ``/combo`` 가 쓰는 것과 **같은 배선**으로 선공 판을 만든다.

    🔴 ``opening_wiring`` 을 쓰지 않으면 유발이 ``legal_actions`` 에 오르지
    않아 걸음이 4 가 되고, 그러면 이 파일이 재려는 숫자가 사용자가 본 것과
    달라진다 (6-AA 가 한 번 그렇게 틀렸다).
    """
    from app.main import opening_wiring

    chooser, triggers = opening_wiring(repository)
    draft = parse_recipe(RECIPE, repository).draft
    return build_opening(
        repository, draft, hand, chooser=chooser, triggers=triggers
    )


# ======================================================================
# ① 거절한 입력에 전개를 추천하지 않는다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_01_a_refused_input_gets_no_static_plan(repository):
    """
    🔴 **거절한 입력에 대해 "이렇게 전개하면 된다" 를 보여 주지 않는다.**

    보여 주면 사용자는 자기 입력이 통과한 것으로 읽는다 — 사용자가 실제로
    그렇게 읽었고, 그것이 실험 ③ 의 보고였다.
    """
    blob = _blob(repository, HAND_OVER)

    #: ① 거절 사실과 **그 이유**는 그대로 적는다.
    assert "실행하지 않았습니다" in blob
    assert "패 4장 > 덱 3장" in blob

    #: ② 🔴 **정적 계획 절이 아예 없다.**
    assert "정적 계획" not in blob
    assert "실행하지 않은 정적 계획" not in blob
    #: ③ 🔴 그래서 "확정" · "엔진이 허가함" 도 없다.
    for forbidden in ("확정", "엔진이 허가"):
        assert forbidden not in blob, forbidden

    #: ④ 왜 내지 않았는지 적는다 — 조용히 빼지 않는다.
    assert "정적 전개 추천은 내지 않았습니다" in blob
    assert "입력이 규칙 검증을 통과하지 못했습니다" in blob


@pytest.mark.real_card
@requires_official_db
def test_02_a_valid_input_still_gets_the_static_plan(repository):
    """
    🔴 **정상 입력에서는 그대로 보여 준다** — 기능을 없앤 것이 아니다.
    """
    blob = _blob(repository, HAND_OK)
    #: 🔴 **Phase 6-AE** — 실제 실행이 있으면 정적 계획은 **첨부**로 간다.
    #: 요약에는 "첨부에 있다 · 엔진으로 돌린 것이 아니다 · 위 실행의 다음
    #: 행동도 아니다" 가 한 줄로 남는다 (6-AE §3).
    assert "**[정적 계획은 첨부에 있습니다]**" in blob
    assert "엔진으로 돌린 것이 **아니고**" in blob
    assert "위 실행의 다음 행동도 아닙니다" in blob
    #: 🔴 **기능을 없앤 것이 아니다** — 첨부에 전부 있다.
    detail = _detail(repository, HAND_OK)
    assert "[아래는 실행하지 않은 정적 계획입니다]" in detail
    assert "정적 계획의 판정" in detail
    assert "**엔진으로 돌린 것이 아닙니다.**" in detail
    #: 🔴 그리고 그 절이 실행 기록 **뒤에** 있고 머리말로 갈라져 있다.
    assert detail.index("[실제 엔진 실행]") < detail.index(
        "[아래는 실행하지 않은 정적 계획입니다]")


def test_03_the_runner_reports_whether_the_input_was_refused():
    """
    거절 여부를 **실행 절이 직접 말한다** — 부르는 쪽이 다시 판정하지 않는다.

    두 번 판정하면 두 답이 갈라질 수 있고, 그것이 이 저장소가 반복해서
    고쳐 온 모양이다 (STRUCTURAL-134).
    """
    import inspect

    #: 🔴 **Phase 6-AE 가 이름과 반환형을 바꿨다** — 줄 목록 두 개가 아니라
    #: :class:`~app.discord_bot.OpeningReport` 하나를 돌려준다 (요약 · 상세 ·
    #: 거절 여부 · 실행 여부). 재는 계약은 그대로다: **실행 절이 거절
    #: 여부를 직접 말하고, 부르는 쪽은 다시 판정하지 않는다.**
    signature = inspect.signature(bot._run_opening)
    #: ``from __future__ import annotations`` 때문에 주석은 **문자열**이다.
    assert signature.return_annotation == "OpeningReport"
    assert "refused" in bot.OpeningReport.__dataclass_fields__
    source = inspect.getsource(bot.combo_response)
    #: 🔴 **Phase 6-BC 가 호출을 한 겹 감쌌다** — ``search:auto`` 면 기준점
    #: 실행을 **돌리지 않는다** (자율 탐색이 주 실행이다). 재는 계약은
    #: 그대로다: 실행 절이 거절 여부를 직접 말하고, 부르는 쪽은 다시
    #: 판정하지 않는다.
    assert "executed = (None if autonomous" in source
    assert "else _run_opening(" in source
    #: 🔴 거절 여부는 **보고에서 읽는다** — 다시 계산하지 않는다.
    #: ``gate`` 는 "거절을 말하는 보고" 이고, 자율 탐색이면 탐색 절의
    #: 보고가 그 자리에 온다 (기준점 실행이 없으므로).
    assert "gate.refused" in source
    assert "gate = searched if autonomous else executed" in source
    #: 🔴 부르는 쪽이 ``setup`` 을 다시 만들어 판정하지 않는다.
    assert "build_opening" not in source
    #: 🔴 **엔진을 한 번만 돌린다** — 요약과 첨부가 같은 기록에서 나온다.
    assert source.count("_run_opening(") == 1
    assert "execute_opening" not in source


# ======================================================================
# ② 레시피 검사와 정적 계획의 안내가 충돌하지 않는다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_04_the_recipe_check_and_the_planner_note_do_not_contradict(repository):
    """
    🔴 **같은 검사를 두 번 다르게 말하지 않는다** (Phase 6-AB 보완8 이 정정).

    6-AA 는 플래너의 *"덱 초안을 주지 않아 검증하지 않았습니다"* 를 **그대로
    보여 주고** 그 아래에 해명 두 줄을 붙였다. 그 해명은 참이지만 사용자가
    읽는 것은 **상충하는 검사 결과 두 개와 변명**이었고, 사용자가 실제로
    그렇게 보고했다.

    플래너가 별도 입력을 받지 않았다는 것은 **내부 사정**이고 그 자체가 검사
    결과로 전달될 일이 아니다. 그래서 ``recipe:`` 가 이미 답한 항목은 그
    목록에서 **빼고**, 실제 결과를 **한 번** 적는다.

    🔴 **플래너의 판정을 바꾸지 않았다** — ``plan.manual_checks`` 는 그대로고
    (``test_05`` 가 그 검사가 실제로 일어남을 센다), 바뀐 것은 사용자에게
    보여 줄 때 어느 줄이 이미 답을 받았는지 가리는 일뿐이다.
    """
    blob = _blob(repository, HAND_OK)
    #: 🔴 **플래너의 "확인하지 않았다" 문장이 사용자에게 가지 않는다.**
    assert "덱에서 나올 수 있는가" not in blob
    assert "검증하지 않았습니다" not in blob
    #: 🔴 대신 실제 결과가 **한 번** 적힌다.
    assert "이미 검사했습니다" in blob
    assert "`recipe:`" in blob
    assert blob.count("이미 검사했습니다") == 1
    #: 🔴 그리고 그 판정이 이 응답의 판정이라고 말한다 — 변명이 아니라 결과다.
    assert "이 응답의 판정입니다" in blob


@pytest.mark.real_card
@requires_official_db
def test_05_the_recipe_really_did_check_the_hand(repository):
    """
    위의 안내가 **참이어야** 한다 — 레시피 경로가 그 검사를 실제로 한다.

    실험 ③ 이 그 증거다: 같은 검사가 매수 초과를 잡았다.
    """
    draft = parse_recipe(RECIPE, repository).draft
    over = build_opening(repository, draft, [69811710] * 4 + [93920420])
    assert over.duel is None
    rules = " ".join(f"{f.rule}: {f.detail}" for f in over.violations)
    assert "패의 매수가 덱 보유 매수 이내인가" in rules
    assert "패 4장 > 덱 3장" in rules


# ======================================================================
# ③ 멈춘 이유를 단정하지 않는다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_06_the_stop_reason_is_scoped_to_what_this_repo_supports(repository):
    """
    🔴 ``['end_phase']`` 만 남은 것은 **이 범위에서** 고를 것이 없다는 뜻이다.

    "전개가 끝났다" 는 이 저장소가 모든 전개 수단을 안다고 가정한다 —
    실행 구현이 등재된 효과는 15개이고 유발은 하나다.

    🔴 **Phase 6-AB 최종 보완이 이 자리를 더 좁혔다** (④). 6-AA 의 한정은
    **참이지만 불충분했다** — 같은 자리의 보류를 보지 않았다. 실측: 사용자가
    보낸 이 패의 전개는 `['end_phase']` 만 남은 자리에서 멈췄고 **같은
    자리에 미지원 보류가 1건** 있었다 (``activate_card`` 의 남은 적법성을
    판정할 규칙 계층이 없다). 즉 "이 범위에서 고를 것이 없다" 는
    *"지원하지 않아 **후보가 되지 못한 것이 있다**"* 를 말하지 않았고,
    읽는 쪽은 그것을 정상 전개 종료로 읽을 수 있었다.

    그래서 기대 문장이 바뀐다 — ``"현재 지원 범위"`` 한정은 **미지원
    보류가 없는** 자리의 문장이 되었고 (``stopped_kind == "flow_only"``),
    이 패는 ``"unsupported"`` 였다.

    🔴 **Phase 6-AC 가 그 자리를 ``"flow_only"`` 로 되돌렸다 — 지원이
    늘어서다.** 6-AB 때 멈춘 자리에 남아 있던 미지원 보류는
    ``activate_card`` 하나였고, 6-AC 가 그것을 고친 것은 **아니다.** 바뀐
    것은 **그 자리에 도달하는 경로**다: 성유물－『성장』 ② 이 등재되어
    전개가 한 걸음 더 나아가고 (5 → 6걸음, 효과 해결 1 → 2), 마지막 자리는
    세트를 모두 끝낸 뒤라 패에 발동 후보가 남지 않는다. 그래서 **그 자리의**
    보류가 0건이 되었고, 도중에 지나온 미지원은 그대로 1건이다.

    🔴 **Phase 6-AO 가 그 자리를 다시 ``"unsupported"`` 로 옮겼다 — 지원이
    또 늘어서다.** 이번에도 ``activate_card`` 를 고친 것이 아니고, 바뀐 것은
    **이 패의 기본(자율) 전개가 지나는 길**이다. 실측으로 적는다.

    ===  ====================================================  ===========
    6-AC                                                       6-AO
    ===  ====================================================  ===========
    2    기르수 ① — 덱의 **『성장』**(93920420) 을 묘지로         덱의 **디베르**(57835716) 를 묘지로
    3    묘지의 『성장』 ② — 패의 『성장』 을 특수 소환            기르수 ③ — 성유물 토큰 2장
    4~6  세트 3장                                               세트 3장
    ===  ====================================================  ===========

    🔴 **왜 2 단계의 대상이 바뀌었나.** 기르수 ① 의 해결 중 선택은
    ``opening_wiring`` 의 기준점 ``FirstPermittedChoice`` 가 집는다 —
    **허용된 후보의 앞쪽**이다. 6-AC 때 그 허용 후보는 『성장』 **한
    장뿐**이었다 (디베르를 묘지로 보낼 수 있는지가 등재되지 않아
    ``UNKNOWN`` 이었고, ADR-006 으로 후보가 되지 못했다). 6-AO 가 디베르의
    ``MAY_BE_SENT_TO_GRAVE`` 를 손으로 읽어 등재하자 허용 후보가 둘이 되었고,
    **패스코드가 더 작은 디베르**(57835716 < 93920420)가 앞이다.

    🔴 **이전 기대값이 틀렸던 것이 아니다** — 그때 이 패의 기본 전개는 정말
    그 길이었고 그 자리의 보류는 정말 0건이었다. 바뀐 것은 저장소가 아는
    것이고, ``FirstPermittedChoice`` 는 **전략이 아니라 기준점**이므로
    (``app/main.py::opening_wiring``) 무엇이 앞인지는 보장한 적이 없다.
    『성장』 경로를 **보장**받는 자리는 ``--line orcust-girsu`` 이고
    ``tests/test_orcust_girsu_line.py`` 가 그것을 잰다.

    🔴 **그래서 멈춘 자리의 보류가 0 → 2건이 되었다.** 하나는 6-AB 부터
    있던 ``activate_card`` 이고, 새로 붙은 하나는 **이번에 등재한 디베르
    ①**(``57835716:e[0]``)이다 — 묘지에 디베르가 있으므로 발동 자리에
    오르지만, 그 자리의 판에서는 **해결 중에 고를 후보가 있다고 확인하지
    못한다** (기르수 ③ 이 만든 성유물 토큰 ``46647145`` 가 특수 소환을
    막는지 읽은 것이 없어 ``UNKNOWN`` 이고, 덱 후보 「오르페골
    트로이메어」``4055337`` 도 특수 소환 가능 여부를 읽은 것이 없다).
    🔴 **그것을 OK 로 바꾸지 않았다** — ``UNKNOWN`` 은 보류로 남고, 그
    보류가 이 자리의 분류를 ``"unsupported"`` 로 만든다.

    재는 요구는 그대로다 — "끝났다고 단정하지 않는다" · "막혔다고 적지
    않는다" · "도중에 지나온 미지원을 적는다". 셋 다 아래에서 센다.
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)
    assert run.stopped_reason
    assert "end_phase" in run.stopped_reason
    #: 🔴 한 낱말로 갈린다 — 네 가지가 같은 문장으로 나오지 않는다.
    assert run.stopped_kind == "unsupported", (
        run.stopped_kind, run.stopped_reason
    )
    #: 🔴 **멈춘 자리에도 보류가 있고 전개 전체를 검증한 것도 아니다** —
    #: 보완8 이 가른 두 질문이고, 이 패는 이제 둘 다 참인 자리다.
    assert run.unsupported
    assert run.fully_supported is False
    #: 🔴 **끝났다고 단정하지 않는다** — 그 요구는 그대로다.
    assert "전개가 끝난 것이 아니라" in run.stopped_reason
    #: 🔴 **막혔다고 적지도 않는다** — "모른다" 라고 적는다.
    assert "엔진이 그 수단을 모르는 자리" in run.stopped_reason
    #: 🔴 그리고 **지원하지 않아 후보가 되지 못한 것**을 적는다 — 몇 건인지와
    #: **무엇인지**를 함께 적는다.
    assert "지원하지 않아 후보가 되지" in run.stopped_reason
    #: 🔴 **Phase 6-AP 에서 그 보류가 둘에서 하나로 줄었다.** 6-AO 때 둘
    #: 중 하나는 디베르 ①(``57835716:e[0]``) 이었고, 그 보류 사유는
    #: "기르수 ③ 이 만든 성유물 토큰(46647145)에 대해 확인된 것이 없어
    #: 막는지 알 수 없다" 였다 — 디스코드 실행에서 사용자가 본 것이
    #: 그것이다. 6-AP 가 룰북의 토큰 한 줄을 판정 계층에 **연결**하자 그
    #: 보류가 사라지고 **디베르 ① 이 실제로 발동된다** (아래 ``test_07``
    #: 이 걸음 수로 센다). **이전 기대값이 틀렸던 것이 아니라** 그때는
    #: 정말 보류가 둘이었다.
    assert "1건" in run.stopped_reason
    #: 🔴 **남은 하나가 무엇인지 글자로 남는다** — 6-AB 부터 있던
    #: ``activate_card`` 이고, 이 Phase 가 고친 것이 아니다.
    assert "activate_card" in run.stopped_reason
    #: 🔴 **토큰 때문에 생기던 보류는 없다.**
    assert "57835716:e[0]" not in run.stopped_reason
    assert "46647145" not in run.stopped_reason


# ======================================================================
# ④ "해결 N걸음" 의 뜻을 가른다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_07_resolved_steps_and_resolved_effects_are_different_numbers(repository):
    """
    🔴 **``resolved`` 는 효과를 해결한 걸음 수가 아니다.**

    체인을 만들지 않는 소환 · 세트도 "막히지 않았다" 이므로 들어온다.
    사용자의 전개에서 ``resolved`` 는 5 였고 **효과 해결은 1** 이었다.

    🔴 **Phase 6-AC 에서 수가 둘 다 늘었다** (6 · 2). 성유물－『성장』 ② 이
    등재되어 기르수 ① 뒤에 한 걸음이 더 붙었고, 그 걸음도 효과 해결이다.
    **재는 것은 수가 아니라 두 수가 다르다는 사실**이고 그것은 그대로다.

    🔴 **Phase 6-AO 에서 수는 그대로지만 둘째 효과가 바뀌었다** — 실측:
    ``executed`` 6 · ``resolved`` 6 · ``effects_resolved`` 2 는 같고, 둘째
    효과 해결이 ``93920420:e[1]`` 에서 ``69811710:e[2]`` (기르수 ③) 로
    바뀌었다. 이유는 ``test_06`` 의 표에 적었다 — 기르수 ① 의 기준점 선택이
    디베르를 집게 되어 『성장』 이 묘지에 가지 않는다. **이전 기대값이
    틀렸던 것이 아니라** 그때 기본 전개가 지난 길이 그랬다.

    🔴 **Phase 6-AP 에서 둘 다 늘었다** — 실측: ``executed`` 7 ·
    ``resolved`` 7 · ``effects_resolved`` **3**. 늘어난 걸음이 **디베르
    ①**(``57835716:e[0]``) 이고, 6-AO 때 그 걸음은 기르수 ③ 이 만든 토큰
    때문에 보류되어 있었다 (``test_06`` 의 설명). 🔴 **재는 것은 수가
    아니라 두 수가 다르다는 사실**이고 그것은 그대로다.

    🔴 **Phase 6-AQ 에서 둘 다 다시 줄었다 — 실측: ``executed`` 6 ·
    ``resolved`` 6 · ``effects_resolved`` 2.** 이번에도 **이 패의 기본(자율)
    전개가 지나는 길**이 바뀐 것이고, 이전 기대값이 틀렸던 것이 아니다.

    원인은 ``test_06`` 이 적어 둔 그 자리와 **같다**. 기르수 ① 의 해결 중
    선택은 기준점 ``FirstPermittedChoice`` 가 집고, 그것은 **허용된 후보의
    앞쪽**(패스코드가 작은 쪽)이다. 6-AQ 가 스켈레촌 ① 을 등재하면서 그
    카드의 ``MAY_BE_SENT_TO_GRAVE`` 를 공식 텍스트 전문을 읽어 적었으므로
    허용 후보가 하나 늘었고, **21441617 < 57835716** 이다. 그래서 기르수 ①
    이 디베르 대신 **스켈레촌**을 묘지로 보낸다.

    그 다음이 갈린다 — 디베르 ① 은 「덱에서」 특수 소환하므로 묘지에 혼자
    있어도 발동할 수 있지만, 스켈레촌 ① 은 「자신 묘지의 "오르페골"
    몬스터」 를 **대상으로 지정**해야 하고 그 자리의 묘지에는 **스켈레촌
    자신뿐**이다 (「"오르페골 스켈레촌" 이외의」 로 자기 사본은 빠진다).
    그래서 그 걸음이 후보가 되지 않는다.

    🔴 **이전 수치와 같게 만들려고 합법 후보를 제거하지 않았다.**
    ``FirstPermittedChoice`` 는 **전략이 아니라 기준점**이고, 보장받는
    경로는 ``--line`` 쪽이다 (``orcust-skeleton-longirsu`` 가 그 경로를
    끝까지 돈다 — ``tests/test_skeleton_revival_and_longirsu.py::test_g01``).
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)

    assert run.executed == 6, run.executed
    assert run.resolved == 6, run.resolved
    #: 🔴 **둘이 다르다** — 그것이 이 시험의 전부다.
    assert run.effects_resolved == 2, run.effects_resolved
    #: 그 둘이 어느 효과인지 기록이 말한다.
    effect_steps = [s for s in run.steps if s.effect_events]
    assert [s.kind for s in effect_steps] == [
        "activate_effect",
        "activate_effect",
    ]
    assert [s.effect_events for s in effect_steps] == [
        ("69811710:e[0]",),
        ("69811710:e[2]",),
    ]
    #: 🔴 **묘지에 간 것이 스켈레촌이다** — 위 설명의 근거를 수로 고정한다.
    from engine.vocabulary import Zone

    assert [
        card.card_id for card in setup.duel.state.zone(0, Zone.GRAVE)
    ] == [21441617]


@pytest.mark.real_card
@requires_official_db
def test_08_the_output_says_what_resolved_means(repository):
    """
    출력이 그 구분을 **글자로** 적는다 — 읽는 쪽이 세어 보지 않아도 된다.

    🔴 **Phase 6-AE 가 두 자리를 가른다.** "막히지 않고 끝난 걸음" 과 그
    경고는 **상세 기록**에 있고 (그 수를 쓰는 사람이 보는 자리), 기본
    응답에는 **조작이 실제로 수행된 걸음**만 적는다 — 요약에 세 수를 함께
    올리면 읽는 쪽이 어느 것이 "소환이 몇 번 일어났나" 인지 알 수 없다.
    """
    blob = _blob(repository, HAND_OK)
    detail = _detail(repository, HAND_OK)
    #: ① 🔴 **상세 기록이 세 수를 전부 들고 있다** — 하나도 사라지지 않았다.
    assert "막히지 않고 끝난 걸음" in detail
    assert "효과를 그만큼 해결했다는 뜻이 **아닙니다**" in detail
    #: 🔴 Phase 6-AP 에서 2 → **3걸음** (``test_07`` 의 설명 — 토큰
    #: 때문에 보류되던 디베르 ① 이 실제로 발동된다).
    #: 🔴 Phase 6-AQ 에서 3 → **2걸음** — 기본 전개가 지나는 길이 다시
    #: 바뀌었다 (``test_07`` 의 설명). 이전 수가 틀렸던 것이 아니다.
    assert "효과의 조작이 실제로 수행된 걸음** 2걸음" in detail
    #: ② 🔴 **정정 (Phase 6-AR).** 기본 응답이 한눈 요약으로 줄면서 걸음
    #: 수 자체가 상세 기록으로 내려갔다 — **세 수가 하나도 사라지지 않았고**
    #: (위 ①), 요약은 "무엇을 했는가" 를 한 줄로 적는다. 여기서 재던 사실은
    #: *요약이 세 수를 섞어 올리지 않는다* 였고, 그것은 그대로다.
    assert "**효과의 조작 수행 2걸음**" not in blob
    assert "막히지 않고 끝난 걸음" not in blob
    assert "전개:" in blob
    #: Phase 6-AC 에서 1 → 2 (위 ``test_07`` 의 설명).
    #: ③ 🔴 **Phase 6-AD 후속2 의 낱말이 두 자리에 그대로 있다.** "해결된
    #: 걸음" 은 규칙상 **해결됐지만 아무 일도 하지 않은 걸음**까지 포함하는
    #: 말이고 (공식 ``s.spop1`` 의 조기 종료), 그러면 그 수가 "소환이 N번
    #: 일어났다" 로 읽힌다 (보고서 §15.3).
    assert "효과의 조작이 실제로 수행된 걸음** 2걸음" in detail
    #: ④ 🔴 **이 전개에는 조작 없는 걸음이 없으므로 그 줄이 어디에도 없다.**
    for text in (blob, detail):
        assert "해결됐지만 조작이 없었던 걸음" not in text
        assert "해결됐지만 조작 없음" not in text


def test_09_the_run_cannot_count_chains_from_the_steps():
    """
    🔴 **6-AA 가 한 번 틀렸다 — 그 자리를 주석으로 남겼다.**

    ``ExecutedStep.chain_links_after`` 는 **걸음이 끝난 뒤 남은** 링크 수이고
    체인이 풀리면 0 이다. 그 수로 "발동이 몇 번 있었는가" 를 세면 유발을
    발동하고 해결한 전개에서 **0** 이 나온다 (실측). 그래서 세지 않는다.
    """
    import inspect

    from deck.opening import OpeningRun

    assert not hasattr(OpeningRun, "chains_built")
    source = inspect.getsource(OpeningRun)
    assert "걸음이 끝난 뒤 남은" in source
    assert "effects_resolved" in source
