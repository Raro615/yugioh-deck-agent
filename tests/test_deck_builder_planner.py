r"""
Phase 4-B — 덱 구성과 전개 계획.

실제 카드 데이터와 실제 룰북 데이터로 검증한다. **가짜 카드 효과로 정상
동작을 증명하지 않는다** — 카드를 직접 만드는 곳은 "저장소에 없는 ID"
처리를 보는 자리뿐이고, 그때도 효과를 지어내지 않는다.

🔴 이 파일이 못 박는 계약:

1. **초기 패의 장수를 강제하지 않는다.** 0장·1장·7장·9장 모두 받는다.
   룰북 데이터의 패 상한 6 은 ``zones[Hand]`` 가 "엔드 페이즈 종료 시점의
   상한" 이라고 적어 둔 값이고 그 외 시점의 상한은 룰북에 없다.
2. **패 입력과 패 생성이 분리되어 있다.** 플래너에 난수원이 없다.
3. **무작위 패 생성은 구현되어 있지 않다** — 그 사실이 출력에 드러난다.
4. **검증 불가를 통과로 바꾸지 않는다.** 금지·제한과 동일명 매수는
   데이터가 없어 검증 불가이고, 그것이 '위반 0건' 에 섞이지 않는다.
5. **UNKNOWN 을 성공으로 바꾸지 않는다.**
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

import deck.planner as planner_module
from core.card_model import Card
from deck.builder import DeckBuilder
from deck.hand import FixedHand, HandProvider
from deck.model import (
    CardRole,
    DeckDraft,
    DeckSlot,
    StepBasis,
    StepStatus,
    ValidationOutcome,
)
from deck.planner import ComboPlanner, engine_executable_card_ids
from deck.report import render_plan, render_validation
from deck.request import DeckGoal, parse_deck_request
from deck.validator import DeckValidator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"
RULEBOOK = (PROJECT_ROOT / "data" / "rules" / "structured"
            / "sd-rulebook-en-v10.json")

requires_cards_cdb = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="data/cards.cdb 가 없습니다.")
requires_rulebook = pytest.mark.skipif(
    not RULEBOOK.is_file(), reason="룰북 구조화 데이터가 없습니다.")

#: 실측으로 고른 표본 (Phase 4-B 작업 중 확인)
POT_OF_GREED = 55144522       # 엔진에 실행 구현이 등록된 마법
NO_SCRIPT_TRAP = 212652       # Lua 스크립트가 없는 함정


# ===========================================================================
# A. 요청 구조화
# ===========================================================================
def test_01_request_parser_reads_themes_and_goals():
    r"""🟢 §1 — 테마와 목표를 뽑는다."""
    request = parse_deck_request(
        "오르페골 + K9으로 덱을 짜 줘. 초동 안정성을 우선하고,"
        " 패트랩도 충분히 넣어 줘.")
    assert "오르페골" in request.themes
    assert "K9" in request.themes
    assert DeckGoal.OPENING_STABILITY in request.goals
    assert DeckGoal.HAND_TRAP_WEIGHT in request.goals


def test_02_request_parser_does_not_invent_a_default_goal():
    r"""🔴 §1 — 목표를 못 찾으면 **비워 둔다.** 기본 목표를 끼우지 않는다."""
    request = parse_deck_request("오르페골 덱")
    assert request.goals == []
    assert "지정되지 않았습니다" in request.describe_ko()


def test_03_empty_request_is_reported_not_guessed():
    r"""🟢 §1 — 빈 요청은 빈 것으로 돌려준다."""
    request = parse_deck_request("")
    assert request.themes == [] and request.goals == []
    assert request.is_empty


# ===========================================================================
# B. 덱 구성 — 실제 카드 데이터
# ===========================================================================
@requires_cards_cdb
def test_04_known_theme_builds_a_deck_with_recorded_reasons(repository):
    r"""🟢 §4 — 실제 카드군으로 덱이 만들어지고 **모든 칸에 근거가 있다.**"""
    request = parse_deck_request("오르페골 덱, 초동 안정성 우선")
    draft = DeckBuilder(repository).build(request)

    assert draft.resolved_themes, draft.notes
    assert draft.main, "메인 덱이 비어 있다"
    for slot in draft.all_slots():
        assert slot.copies >= 1
        assert slot.reason.strip(), slot
        assert isinstance(slot.role, CardRole)


@requires_cards_cdb
def test_05_candidate_selection_is_separate_from_the_final_deck(repository):
    r"""🔴 §4 — 후보 선정과 최종 구성이 **다른 단계**다.

    후보는 카드군 소속 전부이고, 최종 덱은 그보다 적거나 같다. 두 수가
    언제나 같다면 선정 단계가 결정 단계를 그냥 통과시킨 것이다.
    """
    builder = DeckBuilder(repository)
    request = parse_deck_request("오르페골 덱")
    groups = builder.candidates(request)
    assert groups and groups[0].resolved
    theme_cards = len(groups[0].cards)

    draft = builder.build(request)
    theme_slots = [s for s in draft.all_slots() if s.theme]
    assert len(theme_slots) <= theme_cards


@requires_cards_cdb
def test_06_unresolved_theme_is_reported_not_dropped(repository):
    r"""🔴 §7 — 검색 결과가 없는 테마를 **조용히 버리지 않는다.**"""
    request = parse_deck_request("존재하지않는테마이름입니다 덱")
    draft = DeckBuilder(repository).build(request)
    assert draft.unresolved_themes, draft.notes
    assert any("해석하지" in note for note in draft.notes)


@requires_cards_cdb
def test_07_excluded_card_name_is_not_in_the_deck(repository):
    r"""🟢 §4 — 사용자가 제외한 카드는 들어가지 않는다."""
    request = parse_deck_request("오르페골 덱")
    draft = DeckBuilder(repository).build(request)
    victim = draft.main[0].name
    request2 = parse_deck_request(f"오르페골 덱, {victim} 제외")
    assert victim in request2.excluded_names
    #: 🔴 테마가 살아 있어야 한다. 처음에는 이 단정이 없어서, 제외 때문에
    #: 테마까지 사라져 덱이 **비었는데도** 테스트가 통과했다 — 빈 덱에는
    #: 제외한 카드도 없으니까. 엉뚱한 이유로 통과하는 테스트였다.
    assert request2.themes == request.themes, request2.themes
    draft2 = DeckBuilder(repository).build(request2)
    assert draft2.resolved_themes, draft2.notes
    assert draft2.main, "제외 때문에 덱이 비면 안 된다"
    assert victim not in [s.name for s in draft2.all_slots()]


@requires_cards_cdb
def test_08_goal_changes_the_copy_counts(repository):
    r"""🟢 §4 — 목표가 매수에 실제로 반영된다."""
    plain = DeckBuilder(repository).build(parse_deck_request("오르페골 덱"))
    weighted = DeckBuilder(repository).build(
        parse_deck_request("오르페골 덱, 패트랩 비중 우선"))
    traps_plain = [s.copies for s in plain.main
                   if s.role is CardRole.HAND_TRAP]
    traps_weighted = [s.copies for s in weighted.main
                      if s.role is CardRole.HAND_TRAP]
    if traps_plain and traps_weighted:
        assert max(traps_weighted) >= max(traps_plain)


# ===========================================================================
# C. 덱 검증 — 룰북 데이터에서 읽은 규칙만
# ===========================================================================
@requires_rulebook
def test_09_main_deck_size_rule_comes_from_the_rulebook_data():
    r"""🔴 §4 — 40~60 을 **데이터에서 읽는다.** 코드에 박은 수가 아니다."""
    source = inspect.getsource(DeckValidator._check_main_size)
    assert '"40 to 60" in notes' in source
    #: 룰북에 그 문장이 실제로 있다
    assert "40 to 60" in RULEBOOK.read_text(encoding="utf-8")


@requires_rulebook
def test_10_deck_too_small_is_a_violation():
    r"""🟢 §7 — 덱 규격 위반을 잡는다."""
    draft = DeckDraft(main=[DeckSlot(1, "a", 1, CardRole.THEME_CORE, "x")])
    validation = DeckValidator().validate(draft)
    sizes = [f for f in validation.findings if f.rule == "메인 덱 장수"]
    assert sizes and sizes[0].outcome is ValidationOutcome.VIOLATED
    assert validation.has_violation


@requires_rulebook
def test_11_copy_limit_and_banlist_are_unverifiable_not_passed():
    r"""🔴 §4 / §7 — 데이터가 없는 제약을 **통과로 처리하지 않는다.**"""
    draft = DeckDraft(main=[DeckSlot(1, "a", 99, CardRole.THEME_CORE, "x")])
    validation = DeckValidator().validate(draft)
    by_rule = {f.rule: f for f in validation.findings}

    assert (by_rule["동일명 카드 매수 상한"].outcome
            is ValidationOutcome.UNVERIFIABLE)
    assert (by_rule["금지·제한 (리미트 레귤레이션)"].outcome
            is ValidationOutcome.UNVERIFIABLE)
    #: 99장을 넣어도 '위반' 으로 적지 않는다 — 근거가 없으니까
    assert by_rule["동일명 카드 매수 상한"].outcome is not (
        ValidationOutcome.VIOLATED)
    #: 그리고 검증 불가가 '위반 0건' 뒤에 숨지 않는다
    text = render_validation(validation)
    assert "검증 불가" in text
    assert "통과가 아닙니다" in text


@requires_rulebook
def test_12_extra_deck_capacity_comes_from_the_rulebook_zone():
    r"""🟢 §4 — 엑스트라 덱 상한도 데이터에서 읽는다."""
    extra = [DeckSlot(i, f"c{i}", 1, CardRole.EXTRA_DECK, "x")
             for i in range(20)]
    validation = DeckValidator().validate(DeckDraft(extra=extra))
    found = [f for f in validation.findings if f.rule == "엑스트라 덱 장수"]
    assert found and found[0].outcome is ValidationOutcome.VIOLATED
    assert "15" in found[0].detail


@requires_rulebook
def test_13_missing_rulebook_makes_size_checks_unverifiable(tmp_path):
    r"""🔴 §4 — 규칙 데이터가 없으면 **검증 불가**다. 기본값으로 때우지 않는다."""
    validator = DeckValidator(rulebook_path=tmp_path / "nope.json")
    validation = validator.validate(DeckDraft())
    by_rule = {f.rule: f for f in validation.findings}
    assert (by_rule["메인 덱 장수"].outcome
            is ValidationOutcome.UNVERIFIABLE)
    assert (by_rule["엑스트라 덱 장수"].outcome
            is ValidationOutcome.UNVERIFIABLE)


# ===========================================================================
# D. 전개 계획 — 초기 패는 입력이 정한다
# ===========================================================================
@requires_cards_cdb
@pytest.mark.parametrize("size", [0, 1, 2, 7, 9])
def test_14_planner_accepts_any_hand_size(repository, size):
    r"""🔴 §5 — **장수를 강제하지 않는다.**

    룰북 데이터의 패 상한 6 은 ``zones[Hand]`` 가 "엔드 페이즈 종료
    시점의 상한" 이라고 적은 값이고, 같은 자리에 "그 외 시점의 상한은
    룰북에 없다" 고 적혀 있다. 그래서 7장·9장도 거부하지 않는다.
    """
    hand = [POT_OF_GREED] * size
    plan = ComboPlanner(repository).plan(FixedHand(tuple(hand)))
    assert len(plan.hand) == size
    if size == 0:
        assert plan.stopped_reason and "비어 있습니다" in plan.stopped_reason
    else:
        assert plan.steps


@requires_rulebook
def test_15_the_rulebook_says_hand_limit_is_end_phase_only():
    r"""🔴 §5 — 위 테스트의 근거를 **데이터에서 확인한다.**"""
    import json

    data = json.loads(RULEBOOK.read_text(encoding="utf-8"))
    hand = next(z for z in data["zones"] if z.get("name") == "Hand")
    assert hand.get("capacity") == 6
    assert "엔드 페이즈" in (hand.get("notes") or "")
    assert "그 외 시점의 상한은 룰북에 없다" in (hand.get("notes") or "")


@requires_cards_cdb
def test_16_engine_registered_card_is_confirmed(repository):
    r"""🟢 §5 — 엔진에 실행 구현이 있는 카드는 **확정**이다."""
    assert POT_OF_GREED in engine_executable_card_ids()
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    step = plan.steps[0]
    assert step.status is StepStatus.CONFIRMED
    assert step.basis is StepBasis.ENGINE_EXECUTABLE


@requires_cards_cdb
def test_17_card_without_a_script_stays_unknown(repository):
    r"""🔴 §5 — 근거가 없으면 **UNKNOWN 이고, 성공이 아니다.**"""
    card = repository.get(NO_SCRIPT_TRAP)
    assert card is not None and card.script is None
    plan = ComboPlanner(repository).plan(FixedHand((NO_SCRIPT_TRAP,)))
    step = plan.steps[0]
    assert step.status is StepStatus.UNKNOWN
    assert step.basis in (StepBasis.PRINTED_TYPE_ONLY, StepBasis.NONE)
    assert plan.confirmed_steps == []
    assert any(step.card_name in check for check in plan.manual_checks)


@requires_cards_cdb
def test_18_summon_right_makes_the_second_monster_conditional(repository):
    r"""🟢 §5 — 두 번째 일반 소환은 **조건부**다. 소환권이 하나이기 때문이다."""
    request = parse_deck_request("오르페골 덱")
    draft = DeckBuilder(repository).build(request)
    monsters = [s.card_id for s in draft.main
                if repository.get(s.card_id).is_monster][:2]
    if len(monsters) < 2:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    plan = ComboPlanner(repository).plan(FixedHand(tuple(monsters)))
    summons = [s for s in plan.steps if "일반 소환" in s.action]
    assert summons[0].status is StepStatus.CONFIRMED
    assert summons[1].status is StepStatus.CONDITIONAL
    assert any("소환권" in r for r in summons[1].requires)


@requires_cards_cdb
def test_19_unsupported_summon_methods_are_listed_not_planned(repository):
    r"""🔴 §5 — 미지원 절차를 **지원하는 것처럼 계획하지 않는다.**"""
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    joined = " ".join(plan.unsupported)
    for word in ("특수 소환", "융합", "싱크로", "엑시즈", "링크"):
        assert word in joined, word
    #: 계획된 걸음에는 특수 소환이 없다
    assert not [s for s in plan.steps if "특수 소환" in s.action
                and s.status is StepStatus.CONFIRMED]


@requires_cards_cdb
def test_20_unknown_card_id_is_not_silently_skipped(repository):
    r"""🟢 §5 — 저장소에 없는 ID 는 **미확인 걸음으로 남는다.**"""
    plan = ComboPlanner(repository).plan(FixedHand((999999999,)))
    assert len(plan.steps) == 1
    assert plan.steps[0].status is StepStatus.UNKNOWN
    assert any("999999999" in c for c in plan.manual_checks)


@requires_cards_cdb
def test_21_partially_grounded_plan_reports_where_it_stopped(repository):
    r"""🔴 §5 — 일부 걸음만 근거가 있으면 **중단 사유를 적는다.**"""
    plan = ComboPlanner(repository).plan(
        FixedHand((POT_OF_GREED, NO_SCRIPT_TRAP)))
    statuses = {s.status for s in plan.steps}
    assert StepStatus.CONFIRMED in statuses
    assert StepStatus.UNKNOWN in statuses
    assert plan.stopped_reason, "중단 사유가 비어 있다"


@requires_cards_cdb
def test_22_board_defaults_to_empty_and_is_not_invented(repository):
    r"""🟢 §5 — 초기 상태를 주지 않으면 **비운다.** 채우지 않는다."""
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    assert plan.board == []
    plan2 = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)),
                                          board=[NO_SCRIPT_TRAP])
    assert plan2.board == [NO_SCRIPT_TRAP]


@requires_cards_cdb
def test_23_hand_against_deck_is_unverified_when_no_deck_is_given(repository):
    r"""🔴 §5 — 덱을 주지 않으면 그 검증을 **하지 않았다고 적는다.**"""
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    assert any("검증하지 않았습니다" in c for c in plan.manual_checks)


@requires_cards_cdb
def test_24_hand_not_in_deck_is_flagged(repository):
    r"""🟢 §5 — 덱을 주면 패가 덱과 맞는지 본다."""
    draft = DeckDraft(main=[DeckSlot(POT_OF_GREED, "욕망의 항아리", 1,
                                     CardRole.THEME_CORE, "x")])
    plan = ComboPlanner(repository).plan(
        FixedHand((POT_OF_GREED, POT_OF_GREED)), draft=draft)
    assert any("2장" in c and "1장" in c for c in plan.manual_checks)


# ===========================================================================
# E. 패 입력과 패 생성의 분리 (§3 · §9-8)
# ===========================================================================
def test_25_fixed_hand_satisfies_the_provider_boundary():
    r"""🟢 §3 — 이번 단계의 유일한 구현이 경계를 만족한다."""
    provider = FixedHand((1, 2, 3))
    assert isinstance(provider, HandProvider)
    assert provider.hand() == [1, 2, 3]
    assert FixedHand(()).hand() == []


def test_26_planner_holds_no_random_source_and_no_hand_generation():
    r"""🔴 §3 / §9-8 — 플래너 안에 **난수원도 패 생성도 없다.**

    후속 단계에서 무작위 패를 넣을 때 플래너를 고치지 않아야 하고, 난수원이
    플래너에 생기면 "한 번 더 계획했다" 는 이유로 패가 달라진다.
    """
    source = inspect.getsource(planner_module)
    tree = ast.parse(source)
    imported = {n.names[0].name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module}
    assert "random" not in imported, imported

    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)}
    for forbidden in ("shuffle", "sample", "choice", "randint", "random"):
        assert forbidden not in called, forbidden


def test_27_random_hand_generation_is_not_implemented():
    r"""🔴 §5 / §9-8 — **구현하지 않은 것을 지원하는 것처럼 적지 않는다.**

    `deck.hand` 에 구현체는 하나뿐이고, 그 사실이 문서와 출력에 드러난다.
    """
    import deck.hand as hand_module

    #: 🔴 Protocol(경계 선언)은 구현체가 아니다. 처음에 둘을 같이 세어
    #: 틀렸다 — 세어야 하는 것은 **구체 구현**이고, 그것이 하나뿐이라는
    #: 사실이 "무작위 패는 아직 없다" 를 뜻한다.
    concrete = [obj for name, obj in vars(hand_module).items()
                if isinstance(obj, type) and not name.startswith("_")
                and obj.__module__ == hand_module.__name__
                and not getattr(obj, "_is_protocol", False)]
    assert [c.__name__ for c in concrete] == ["FixedHand"], concrete
    assert "HandProvider" in vars(hand_module), "경계 선언이 있어야 한다"
    assert "구현하지 않았다" in (hand_module.__doc__ or "")


@requires_cards_cdb
def test_28_plan_output_states_that_random_hands_are_unimplemented(repository):
    r"""🔴 §9-8 — 사용자가 보는 출력에 그 사실이 적힌다."""
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    text = render_plan(plan)
    assert "무작위 패 생성은 구현되어 있지 않습니다" in text


# ===========================================================================
# F. 과대 진술 방지
# ===========================================================================
@requires_cards_cdb
def test_29_plan_never_claims_the_line_is_legal(repository):
    r"""🔴 §5 — "검증됐다" 고 주장하지 않는다."""
    plan = ComboPlanner(repository).plan(FixedHand((POT_OF_GREED,)))
    text = render_plan(plan)
    assert "검증되지 않았습니다" in text
    for claim in ("합법임을 확인", "검증 완료", "성공했습니다",
                  "시뮬레이터에서 실행했습니다"):
        assert claim not in text, claim


def test_30_action_basis_is_not_confused_with_effect_implementation():
    r"""🔴 두 근거를 **분리해 둔다.**

    일반 소환이 되는 몬스터를 두고 "효과 실행 구현이 있다" 고 적으면 과대
    진술이다. 작업 중 실제로 그렇게 적고 있었고, 그래서 근거 값을 둘로
    갈랐다.
    """
    assert StepBasis.ENGINE_ACTION is not StepBasis.ENGINE_EXECUTABLE
    assert "허가" in StepBasis.ENGINE_ACTION.describe_ko()
    assert "실행 구현" in StepBasis.ENGINE_EXECUTABLE.describe_ko()

    source = inspect.getsource(planner_module)
    summon = source.split("일반 소환합니다")[1][:400]
    assert "ENGINE_ACTION" in summon


def test_31_engine_v1_is_only_read_never_modified():
    r"""🔴 §8 — 이 꾸러미는 엔진을 **읽기만** 한다."""
    for path in sorted((PROJECT_ROOT / "deck").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            #: 엔진 객체의 속성에 대입하지 않는다
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        assert not isinstance(target.value, ast.Name) or (
                            target.value.id not in {"engine", "duel", "state"}
                        ), (path, ast.unparse(node))


def test_32_this_file_respects_the_repository_tripwires():
    r"""🔴 저장소의 지뢰선을 **스스로** 확인한다."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert re.search(r"[0-9a-f]{64}", text) is None
    for match in re.findall(r"pytest\.skip\(([^)]*)\)", text):
        assert "commit 이 아직 없다" in match, match


# ===========================================================================
# F. Phase 5-D — 보강 카드 오분류 수정
#
# `/deck request:"오르페골 덱 짜줘"` 가 아래 8장을 **전부 같은 근거**
# ("패에서 발동 (패트랩 계열)") 로 메인 덱에 넣은 것이 이 절의 출발점이다.
# 🔴 이 8장은 **이름으로 걸러내지 않는다** — 하드코딩 제외 목록을 만들면
# 같은 결함이 다른 카드에서 그대로 재발한다. 여기서 확인하는 것은 **효과
# 데이터가 이 8장을 서로 다르게 판정하는가** 다.
# ===========================================================================
#: 실제 보고된 8장. 🔴 **제외 목록이 아니다** — 판정이 갈리는지 보는 표본이다.
MISCLASSIFIED_SAMPLE: tuple[tuple[int, str], ...] = (
    (2511, "라뷰린스 쿠클락"),
    (10000, "텐사우전드 드래곤"),
    (35699, "SPYRAL－보텍스"),
    (122520, "EM 스카이 퓨필"),
    (132308, "육화의 하얀 공주"),
    (218704, "펜리르"),
    (263926, "독법사"),
    (291414, "하나된 마음의 용"),
)


@requires_cards_cdb
def test_33_hand_range_alone_is_not_an_activatable_effect(repository):
    r"""🔴 §A — ``LOCATION_HAND`` 은 **발동 가능**과 같지 않다.

    이것이 오분류의 뿌리다. ``card.has_effect_from("HAND")`` 는
    ``SetRange`` 에 ``HAND`` 이 있는지만 보므로 **특수 소환 절차**
    (``EFFECT_SPSUMMON_PROC``, ``EFFECT_TYPE_FIELD``) 에도 참이 된다.
    절차는 발동이 아니다.
    """
    from deck.evidence import hand_effect_facts

    loc_only = activatable = 0
    for card in repository.all_cards():
        if card.is_extra_deck or not card.is_monster:
            continue
        if card.has_effect_from("HAND"):
            loc_only += 1
        if hand_effect_facts(card).activatable_from_hand:
            activatable += 1

    #: 🔴 두 수가 같다면 가르는 일이 일어나지 않은 것이다
    assert activatable < loc_only, (activatable, loc_only)
    #: 실측: 1,795 대 1,208 — 587장이 발동 가능한 효과가 아니었다
    assert loc_only - activatable > 400, (loc_only, activatable)


@requires_cards_cdb
def test_34_the_eight_reported_cards_do_not_share_one_verdict(repository):
    r"""🔴 §C-2 — 보고된 8장이 **한 역할로 묶이지 않는다.**

    묶였던 것이 결함이었다. 지금은 효과 데이터만으로 **세 등급**으로
    갈린다 — 이름을 보지 않는다.
    """
    from deck.evidence import HandTrapEvidence, hand_effect_facts

    verdicts: dict[int, HandTrapEvidence] = {}
    for card_id, expected_name in MISCLASSIFIED_SAMPLE:
        card = repository.get(card_id)
        assert card is not None, card_id
        #: 표본이 바뀌지 않았는지 확인한다 (ID 가 다른 카드를 가리키면
        #: 이 테스트는 다른 것을 재고 있다)
        assert card.display_name() == expected_name, card.display_name()
        verdicts[card_id] = hand_effect_facts(card).evidence

    #: 🔴 전부 같은 판정이면 결함이 돌아온 것이다
    assert len(set(verdicts.values())) == 3, verdicts

    #: 네 장은 패에서 **발동할 수 있는 효과가 없다** (특수 소환 절차)
    not_activatable = {cid for cid, v in verdicts.items()
                       if v is HandTrapEvidence.NOT_ACTIVATABLE_FROM_HAND}
    assert not_activatable == {10000, 35699, 218704, 263926}, not_activatable

    #: 세 장은 발동은 가능하지만 **무엇을 하는지 판정하지 못한다**
    activatable_only = {cid for cid, v in verdicts.items()
                        if v is HandTrapEvidence.ACTIVATABLE_ONLY}
    assert activatable_only == {2511, 122520, 291414}, activatable_only

    #: 한 장만 무효/무력화 근거가 있다
    negation = {cid for cid, v in verdicts.items()
                if v is HandTrapEvidence.NEGATION_FROM_HAND}
    assert negation == {132308}, negation


@requires_cards_cdb
def test_35_the_role_follows_the_evidence_not_the_location(repository):
    r"""🔴 §C-1 · §C-3 — 역할이 **근거 등급을 따라간다.**

    패에서 발동 가능하다는 사실만으로 :attr:`CardRole.HAND_TRAP` 이 되지
    않는다. 그 사실은 :attr:`CardRole.HAND_ACTIVATABLE` 이고, 역할의
    출처도 따로 적힌다.
    """
    from deck.builder import ThemeCandidates
    from deck.evidence import HandTrapEvidence, hand_effect_facts
    from deck.model import RoleEvidence

    group = ThemeCandidates(term="테스트", resolved_names=["TESTSET"])
    builder = DeckBuilder(repository)

    expected = {
        HandTrapEvidence.NEGATION_FROM_HAND:
            (CardRole.HAND_TRAP, RoleEvidence.LUA_EFFECT_CATEGORY),
        HandTrapEvidence.ACTIVATABLE_ONLY:
            (CardRole.HAND_ACTIVATABLE, RoleEvidence.LUA_EFFECT_BLOCK),
    }

    checked = set()
    for card_id, _name in MISCLASSIFIED_SAMPLE:
        card = repository.get(card_id)
        role, reason, evidence = builder._classify(card, group)
        facts = hand_effect_facts(card)

        if card.can_self_special_summon_from_hand:
            #: 특수 소환 절차는 **그 역할**로 간다 — 패트랩이 아니다
            assert role is CardRole.SELF_SPECIAL_SUMMON, (card_id, role)
            assert evidence is RoleEvidence.LUA_EFFECT_BLOCK
            checked.add("self_sp")
            continue

        if facts.evidence in expected:
            want_role, want_evidence = expected[facts.evidence]
            assert role is want_role, (card_id, role, facts.evidence)
            assert evidence is want_evidence, (card_id, evidence)
            checked.add(facts.evidence.value)

        #: 🔴 근거가 약한 카드를 패트랩이라고 적지 않는다
        if role is not CardRole.HAND_TRAP:
            assert "패트랩" not in reason or "근거는 아닙니다" in reason, reason

    #: 표본이 세 경로를 모두 밟았다 — 하나라도 빠지면 반쪽만 본 것이다
    assert checked == {"self_sp", "activatable_only",
                       "negation_from_hand"}, checked


@requires_cards_cdb
def test_36_a_shortfall_alone_does_not_pick_any_card(repository):
    r"""🔴 §B-1 — **장수 부족은 카드 선정의 근거가 아니다.**

    장수가 부족하다는 사실은 '몇 장' 만 알려 주고 '어떤 카드' 인지는
    알려 주지 않는다. 목표가 없으면 보강하지 않고, 부족하다는 사실과
    그 이유를 적는다.
    """
    draft = DeckBuilder(repository).build(parse_deck_request("오르페골 덱"))

    #: 테마 카드만 들어 있다 — 테마 밖 카드가 하나도 없다
    assert draft.main, draft.notes
    assert all(slot.theme for slot in draft.main), [
        slot.name for slot in draft.main if not slot.theme]
    assert draft.main_count < 40, draft.main_count

    #: 그 사실을 적는다
    assert any("보강하지 않았습니다" in note for note in draft.notes), draft.notes
    assert any("판정할 데이터가 없" in note for note in draft.notes), draft.notes

    #: 🔴 그리고 검증이 장수 위반을 **숨기지 않는다**
    validation = DeckValidator().validate(draft)
    sizes = [f for f in validation.findings if f.rule == "메인 덱 장수"]
    assert len(sizes) == 1
    assert sizes[0].outcome is ValidationOutcome.VIOLATED, sizes[0]


@requires_cards_cdb
def test_37_filling_requires_both_a_goal_and_measured_evidence(repository):
    r"""🟢 §B — 보강은 **요청된 목표 + 측정된 근거** 둘이 있을 때만 한다."""
    from deck.evidence import HandTrapEvidence, hand_effect_facts
    from deck.model import RoleEvidence

    draft = DeckBuilder(repository).build(
        parse_deck_request("오르페골 덱, 패트랩 비중 우선"))
    filled = [slot for slot in draft.main if slot.theme is None]
    assert filled, draft.notes

    for slot in filled:
        card = repository.get(slot.card_id)
        #: 🔴 넣은 카드마다 **무효/무력화 범주가 실제로 있다**
        facts = hand_effect_facts(card)
        assert facts.evidence is HandTrapEvidence.NEGATION_FROM_HAND, slot
        assert facts.negation_blocks >= 1, slot
        assert slot.role is CardRole.HAND_TRAP, slot
        assert slot.evidence is RoleEvidence.LUA_EFFECT_CATEGORY, slot

    #: 🔴 보고된 8장 중 **근거가 없는 7장은 들어오지 않는다**
    present = {slot.card_id for slot in draft.main}
    for card_id, name in MISCLASSIFIED_SAMPLE:
        if card_id == 132308:      # 무효 근거가 있는 한 장
            continue
        assert card_id not in present, (card_id, name)

    #: 순서가 임의라는 사실을 적는다 — 추천이라고 적지 않는다
    assert any("임의" in note for note in draft.notes), draft.notes


@requires_cards_cdb
def test_38_no_filler_claims_to_fit_the_theme(repository):
    r"""🔴 §C-4 — 테마 적합성을 **주장하지 않는다.**

    이 저장소에는 "이 카드가 오르페골 덱에 맞는가" 를 판정할 데이터가
    없다. 그래서 보강 카드의 근거에 테마 이름이 들어가지 않고, 맞는지
    판정하지 않았다는 사실이 적힌다.
    """
    draft = DeckBuilder(repository).build(
        parse_deck_request("오르페골 덱, 패트랩 비중 우선"))
    filled = [slot for slot in draft.main if slot.theme is None]
    assert filled

    for slot in filled:
        assert slot.theme is None, slot
        assert "오르페골" not in slot.reason, slot.reason
        assert "ORCUST" not in slot.reason, slot.reason
        assert "판정하지 않았습니다" in slot.reason, slot.reason
        #: 추천·시너지·강함을 주장하는 말이 없다
        for claim in ("추천", "시너지", "강력", "최적", "좋은", "필수"):
            assert claim not in slot.reason, (claim, slot.reason)


def test_39_the_evidence_layer_holds_no_card_name_list():
    r"""🔴 §4 — 효과 판정이 **카드 이름이나 ID 목록에 기대지 않는다.**

    8장을 하드코딩으로 빼면 같은 결함이 다른 카드에서 그대로 재발한다.
    그래서 :mod:`deck.evidence` 에는 카드 이름도, 카드 ID 리터럴도 없다.
    """
    import deck.evidence as evidence_module

    source = Path(evidence_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    #: 실행되는 코드에 **카드 ID 가 없다.** 🔴 "정수 리터럴이 하나도
    #: 없다" 로 적었더니 ``> 0`` 과 ``sum(1 for …)`` 의 0·1 이 걸렸다 —
    #: 그것은 블록 **개수**이고 카드 ID 가 아니다. 이 저장소의 카드 ID 는
    #: 네 자리 이상이므로(표본 최솟값 2,511) 9 를 넘는 리터럴만 본다.
    numbers = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
        and not isinstance(node.value, bool) and node.value > 9
    ]
    assert numbers == [], numbers

    #: 카드 이름을 쓰는 비교가 없다
    for forbidden in ("display_name", "name_ko", "name_en", ".name"):
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                    "display_name", "name_ko", "name_en", "name"):
                raise AssertionError(f"이름을 읽는다: {node.attr}")
        assert forbidden not in _code_only(source), forbidden


def _code_only(source: str) -> str:
    """docstring 과 주석을 지운 본문. 표에 적힌 카드 이름을 세지 않는다."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.unparse(tree)


@requires_cards_cdb
def test_40_the_negation_pool_is_far_smaller_than_the_old_one(repository):
    r"""🟢 §B — 좁힌 기준의 **크기를 기록한다.**

    1,795장이 37장이 됐다. 이 수가 다시 커지면 기준이 느슨해진 것이다.
    """
    from deck.evidence import HandTrapEvidence, hand_effect_facts

    old_pool = negation_pool = 0
    for card in repository.all_cards():
        if card.is_extra_deck or not card.is_monster:
            continue
        if card.has_effect_from("HAND"):
            old_pool += 1
        if (hand_effect_facts(card).evidence
                is HandTrapEvidence.NEGATION_FROM_HAND):
            negation_pool += 1

    assert negation_pool >= 1, negation_pool
    #: 실측 1,795 대 37 — 48배. 10배 안으로 좁혀지면 기준이 풀린 것이다
    assert negation_pool * 10 < old_pool, (negation_pool, old_pool)


@requires_cards_cdb
def test_41_the_repository_cannot_say_whose_activation_is_chained(repository):
    r"""🔴 §A — "**상대의** 행동을 방해한다" 를 이 저장소는 말할 수 없다.

    ``EVENT_CHAINING`` 은 "발동에 체인한다" 는 사실이고 **누구의** 발동
    인지는 Lua 블록에 없다. 그래서 그 말을 쓰는 함수도, 그 말을 적는
    근거 문장도 없다.
    """
    import deck.evidence as evidence_module

    source = Path(evidence_module.__file__).read_text(encoding="utf-8")
    code = _code_only(source)
    #: 코드에 "상대" 가 없다 (docstring 에서는 왜 없는지 설명한다)
    assert "상대" not in code, code

    #: 그래도 사실 자체는 읽는다 — 읽지 않는 것과 다르다
    from deck.evidence import chains_on_activation, hand_effect_facts

    card = repository.get(132308)        # 육화의 하얀 공주
    assert chains_on_activation(card) is True
    assert hand_effect_facts(card).chain_response_blocks == 1

    #: 보강 근거 문장에도 "상대" 가 없다
    draft = DeckBuilder(repository).build(
        parse_deck_request("오르페골 덱, 패트랩 비중 우선"))
    for slot in draft.all_slots():
        assert "상대" not in slot.reason, slot.reason


@requires_cards_cdb
def test_42_role_and_evidence_are_separate_fields(repository):
    r"""🔴 §A — 역할과 **그 근거**가 서로 다른 칸이다.

    합쳐 두면 "근거 없이 붙은 역할" 과 "측정으로 붙은 역할" 이 구별되지
    않는다. 그것이 Phase 5-C 결함의 형태였다.
    """
    from deck.model import RoleEvidence

    #: 기본값은 "근거 없음" 이다 — 조용히 그럴듯한 값이 붙지 않는다
    bare = DeckSlot(card_id=1, name="x", copies=1,
                    role=CardRole.THEME_CORE, reason="r")
    assert bare.evidence is RoleEvidence.NONE

    draft = DeckBuilder(repository).build(
        parse_deck_request("오르페골 덱, 패트랩 비중 우선"))
    #: 실제 덱의 모든 칸에 근거가 적혀 있다
    for slot in draft.all_slots():
        assert isinstance(slot.evidence, RoleEvidence), slot
        assert slot.evidence is not RoleEvidence.NONE, slot

    #: 같은 역할이 서로 다른 근거로 붙을 수 있다 — 그래서 따로 적는다
    pairs = {(slot.role, slot.evidence) for slot in draft.all_slots()}
    roles = {role for role, _ in pairs}
    assert len(pairs) > len(roles) or len(roles) > 1, pairs


def test_43_the_role_label_no_longer_claims_hand_trap_for_a_location():
    r"""🔴 §B-3 — 역할 **이름**이 측정한 것만 말한다.

    ``"패에서 발동 (패트랩 계열)"`` 은 위치 사실에 역할 이름을 붙인
    표기였다. 지금은 무엇을 측정했는지만 적는다.
    """
    labels = {role: role.describe_ko() for role in CardRole}
    assert "패트랩 계열" not in " ".join(labels.values()), labels
    assert labels[CardRole.HAND_TRAP] == "패에서 발동 · 무효/무력화 범주 확인"
    assert labels[CardRole.HAND_ACTIVATABLE] == (
        "패에서 발동 가능 (효과 내용 미판정)")
    #: 두 역할이 다른 값이다 — 합치면 결함이 돌아온다
    assert CardRole.HAND_TRAP is not CardRole.HAND_ACTIVATABLE
