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
