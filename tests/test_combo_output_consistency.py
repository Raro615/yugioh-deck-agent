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
    return "\n".join(bot.combo_messages(_Agent(repository), hand, recipe_text=RECIPE))


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
    assert "아래는 실행하지 않은 정적 계획입니다" in blob
    assert "정적 계획의 판정" in blob
    assert "엔진으로 돌린 것이 아닙니다" in blob


def test_03_the_runner_reports_whether_the_input_was_refused():
    """
    거절 여부를 **실행 절이 직접 말한다** — 부르는 쪽이 다시 판정하지 않는다.

    두 번 판정하면 두 답이 갈라질 수 있고, 그것이 이 저장소가 반복해서
    고쳐 온 모양이다 (STRUCTURAL-134).
    """
    import inspect

    signature = inspect.signature(bot._executed_lines)
    assert "tuple" in str(signature.return_annotation)
    source = inspect.getsource(bot.combo_messages)
    assert "executed_lines, input_refused = _executed_lines(" in source
    #: 🔴 부르는 쪽이 ``setup`` 을 다시 만들어 판정하지 않는다.
    assert "build_opening" not in source


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

    재는 요구는 그대로다 — "끝났다고 단정하지 않는다" · "막혔다고 적지
    않는다" · "도중에 지나온 미지원을 적는다". 셋 다 아래에서 센다.
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)
    assert run.stopped_reason
    assert "end_phase" in run.stopped_reason
    #: 🔴 한 낱말로 갈린다 — 네 가지가 같은 문장으로 나오지 않는다.
    assert run.stopped_kind == "flow_only", (
        run.stopped_kind, run.stopped_reason
    )
    #: 🔴 **멈춘 자리는 깨끗한데 전개 전체를 검증한 것은 아니다** — 보완8 이
    #: 가른 두 질문이고, 이 패가 그 자리다.
    assert run.unsupported
    assert run.fully_supported is False
    #: 🔴 **끝났다고 단정하지 않는다** — 그 요구는 그대로다.
    assert "실제로 이 패의 전개가 끝났다는 뜻이 아니고" in run.stopped_reason
    #: 🔴 **막혔다고 적지도 않는다** — 그 요구도 그대로다.
    assert "엔진이 막았다는 뜻도 아닙니다" in run.stopped_reason
    #: 🔴 그리고 **지원하지 않아 후보가 되지 못한 것**을 적는다 (6-AB 최종 ·
    #: 보완8 이 시점을 "앞선 자리" 로 분명히 했다).
    assert "지원하지 않아 후보가 되지" in run.stopped_reason
    assert "앞선 자리" in run.stopped_reason


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
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)

    assert run.executed == 6, run.executed
    assert run.resolved == 6, run.resolved
    #: 🔴 **둘이 다르다** — 그것이 이 시험의 전부다.
    assert run.effects_resolved == 2, run.effects_resolved
    #: 그 둘이 유발 발동이다 — 기록이 말한다.
    effect_steps = [s for s in run.steps if s.effect_events]
    assert [s.kind for s in effect_steps] == [
        "activate_effect",
        "activate_effect",
    ]
    assert [s.effect_events for s in effect_steps] == [
        ("69811710:e[0]",),
        ("93920420:e[1]",),
    ]


@pytest.mark.real_card
@requires_official_db
def test_08_the_output_says_what_resolved_means(repository):
    """출력이 그 구분을 **글자로** 적는다 — 읽는 쪽이 세어 보지 않아도 된다."""
    blob = _blob(repository, HAND_OK)
    assert "막히지 않고 끝난 걸음" in blob
    assert "효과를 그만큼 해결했다는 뜻이 **아닙니다**" in blob
    #: Phase 6-AC 에서 1 → 2 (위 ``test_07`` 의 설명).
    assert "효과가 실제로 해결된 걸음** 2걸음" in blob
    #: 한 줄 요약도 같은 수를 쓴다 — 두 수가 갈라지지 않는다.
    assert "효과 해결 2걸음" in blob


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
