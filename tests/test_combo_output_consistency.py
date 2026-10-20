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
    🔴 **두 절이 다른 입력을 본다는 것을 적는다.**

    정적 계획은 자연어 ``deck:`` 초안을 받지 않으면 "패가 덱에서 나올 수
    있는지 확인하지 않았다" 고 적는다. 그 문장은 **플래너에 대해 참**이다 —
    고친 것은 같은 응답에서 ``recipe:`` 가 그것을 이미 검사했다는 사실을
    적지 않은 것이다.

    🔴 **플래너의 판정을 바꾸지 않았다.** 그 문장은 그대로 있고, 옆에
    누가 무엇을 검사했는지가 붙는다.
    """
    blob = _blob(repository, HAND_OK)
    #: 플래너의 문장은 **그대로 있다**.
    assert "덱에서 나올 수 있는지" in blob
    #: 🔴 그리고 그 옆에 실제 판정이 어디서 났는지 적힌다.
    assert "이미 검사했습니다" in blob
    assert "`recipe:`" in blob
    assert "두 절이 다른" in blob


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
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)
    assert run.stopped_reason
    assert "end_phase" in run.stopped_reason
    assert "현재 지원 범위" in run.stopped_reason
    assert "전개가 끝났다는 뜻이 아니고" in run.stopped_reason
    assert "엔진이 막았다는 뜻도 아닙니다" in run.stopped_reason


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
    """
    setup = _opened(repository, [69811710, 703897, 2930675, 12989604, 93920420])
    run = execute_opening(setup, repository)

    assert run.executed == 5, run.executed
    assert run.resolved == 5, run.resolved
    #: 🔴 **둘이 다르다** — 그것이 이 시험의 전부다.
    assert run.effects_resolved == 1, run.effects_resolved
    #: 그 하나가 유발 발동이다 — 기록이 말한다.
    effect_steps = [s for s in run.steps if s.effect_events]
    assert len(effect_steps) == 1
    assert effect_steps[0].kind == "activate_effect"
    assert effect_steps[0].effect_events == ("69811710:e[0]",)


@pytest.mark.real_card
@requires_official_db
def test_08_the_output_says_what_resolved_means(repository):
    """출력이 그 구분을 **글자로** 적는다 — 읽는 쪽이 세어 보지 않아도 된다."""
    blob = _blob(repository, HAND_OK)
    assert "막히지 않고 끝난 걸음" in blob
    assert "효과를 그만큼 해결했다는 뜻이 **아닙니다**" in blob
    assert "효과가 실제로 해결된 걸음** 1걸음" in blob
    #: 한 줄 요약도 같은 수를 쓴다 — 두 수가 갈라지지 않는다.
    assert "효과 해결 1걸음" in blob


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
