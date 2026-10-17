"""
Phase 6-D — 카드군 이름을 조건으로 옮기는 컴파일러.

    CardConstraint.setcodes == ["ORCUST"]   ← analysis 가 읽어 둔 **이름**
          ↓  compile_archetype_condition
    IsSetCard((0x11b,))                     ← 엔진이 쓰는 **숫자**
          ↓  CandidateSource(require=…)
    CandidateResolver → eligible / undecided / unchecked

지키는 것 다섯
--------------
1. **옮길 수 있는 것만 옮긴다.** 이름이 상수 표에 없으면 코드를 지어내지
   않는다.
2. **못 옮긴 것을 조용히 버리지 않는다.** 목록에서 빼면 조건이 좁아져
   그 카드군의 카드가 ``FALSE`` 가 된다 — 모르는 것을 거짓으로 접는 일이다.
3. **거짓 양성이 없다.** 다른 카드군의 카드가 참이 되지 않는다.
4. **"요구가 없다" 와 "옮기지 못했다" 가 다른 값이다.**
5. **검색용 ``by_setcode()`` 의 계약을 건드리지 않는다.**
"""

import ast
import pathlib

import pytest

from analysis.effect_model import CardConstraint
from engine.archetype import matches_setcode
from engine.archetype_compiler import (
    UNREAD_PREFIX,
    UNREAD_RULE,
    ArchetypeCompilation,
    compile_archetype_condition,
    unread_archetype_calls,
)
from engine.condition import (
    And,
    ArchetypeUnresolved,
    ConditionContext,
    ConditionResult,
    IsMonster,
    IsSetCard,
    Not,
    Or,
    PlayerRef,
    UnimplementedRule,
)
from engine.cost.choice import CandidateSource, ChoiceSpec
from engine.cost.resolver import CandidateResolver
from engine.game_state_view import GameStateView
from engine.state.game_state import GameState
from engine.vocabulary import EngineVocabulary, default_vocabulary
from engine.vocabulary import Phase, Zone

from sources.script_constants import ScriptConstants
from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
TRUE = ConditionResult.TRUE
FALSE = ConditionResult.FALSE
UNKNOWN = ConditionResult.UNKNOWN

# --- 실제 카드 -------------------------------------------------------
#: 잭나이츠 오르페골 기르수 — 오르페골 **이면서** 잭나이츠다.
GIRSU = 69811710
#: 오르페골 롱기르수 — 오르페골만.
LONGIRSU = 76145142
#: 엘리멘틀 히어로 페더맨 — 다른 카드군 (대조군).
FEATHERMAN = 21844576
#: 용암 마신 라바 골렘 — 카드군이 **없다**.
LAVA_GOLEM = 102380

# --- 실제 카드군 코드 (상수 표에서 읽는다) ---------------------------
SET_ORCUST = 0x11B
SET_MEKK_KNIGHT = 0x10C
SET_WORLD_LEGACY = 0x0FE
SET_HERO = 0x008
SET_ELEMENTAL_HERO = 0x3008

#: 🔴 상수 표에 **없는** 실제 카드군 이름. 이 세 개가 실측값이다.
UNRESOLVABLE = ("CENTURION", "DRAGONTAIL", "DIABELLESTARR")


def constraint(**kwargs) -> CardConstraint:
    return CardConstraint(**kwargs)


def compile_of(c: CardConstraint, **kwargs):
    """호출자가 실제로 쓰는 두 줄을 그대로 쓴다 (모듈 설명의 사용법)."""
    return compile_archetype_condition(
        c.setcodes, unread=unread_archetype_calls(c.raw_predicates), **kwargs
    )


@pytest.fixture(scope="module")
def table() -> EngineVocabulary:
    return default_vocabulary()


@pytest.fixture
def state(repository) -> GameState:
    game = GameState.create(
        repository,
        decks=(
            [GIRSU, LONGIRSU, FEATHERMAN, LAVA_GOLEM] + [FEATHERMAN] * 10,
            [FEATHERMAN] * 10,
        ),
        turn_player=MINE,
        seed=5,
    )
    game.draw(MINE, 4)
    game.draw(THEIRS, 1)
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def in_hand(state: GameState, card_id: int) -> object:
    return next(
        card.instance_id
        for card in state.player(MINE).hand
        if card.card_id == card_id
    )


def ask(view, state, condition, card_id) -> ConditionResult:
    return condition.evaluate(
        view, ConditionContext(player=MINE, source=in_hand(state, card_id))
    )


# ======================================================================
# A. 이름 → 코드 — 상수 표가 유일한 근거다
# ======================================================================


def test_a_the_table_is_the_only_source_of_a_code(table):
    """
    이름을 코드로 바꾸는 근거는 ``archetype_setcode_constants.lua`` 하나다.
    그 표가 ``ScriptConstants`` 에 실리고, ``EngineVocabulary.archetypes``
    가 감싸기만 한다 — 값을 만들지 않는다.

    🔴 **615 → 616** (Phase 6-T 에서 움직였다, 그리고 **이 Phase 의 변경
    때문이 아니다**).

    ``data/constants/archetype_setcode_constants.lua`` 는 상류에서 계속
    갱신되는 파일이고 ``.gitignore`` 대상이다 ("상류에서 계속 갱신되는
    데이터는 커밋하지 않는다"). 6-T 작업을 시작할 때 이 컨테이너의 클론이
    낡아 있어서 ``python -m scripts.fetch_official_db`` 로 다시 받았고,
    그 사이 상류에 카드군 하나가 늘었다 (실측 616).

    🔴 **6-T 는 ``engine/`` 을 한 줄도 바꾸지 않았다** — 바꾼 생산 파일은
    ``deck/`` 와 ``app/`` 뿐이다. 그래서 이 수의 이동은 **데이터 드리프트**
    이고, 이 핀이 그것을 드러내도록 설계되어 있다는 증거다. 늘어난 카드군의
    이름은 가를 수 없다 — 그 파일이 저장소에 없으므로 이전 판과 비교할
    대상이 없다.
    """
    constants = ScriptConstants.load()
    assert len(table.archetypes) == len(constants.setcodes) == 616
    for name in table.archetypes.names():
        assert table.archetypes.value(name) == constants.setcodes[f"SET_{name}"]


def test_a_a_prefixed_or_bare_name_resolves_the_same(table):
    assert table.archetypes.value("ORCUST") == SET_ORCUST
    assert table.archetypes.value("SET_ORCUST") == SET_ORCUST
    assert compile_archetype_condition(["SET_ORCUST"]).resolved == (
        ("ORCUST", SET_ORCUST),
    )


def test_a_the_mapping_is_not_one_to_one_so_the_written_name_is_kept(table):
    """
    🔴 한 코드에 이름이 둘인 묶음이 **실제로 하나 있다** —
    ``SET_POLYMERIZATION`` 과 ``SET_FUSION`` 이 둘 다 ``0x46`` 이다.

    그래서 역조회로 이름을 정규화하면 스크립트가 적은 이름이 **다른 이름으로
    바뀐다.** 컴파일러는 적힌 그대로를 남긴다.
    """
    assert table.archetypes.value("POLYMERIZATION") == table.archetypes.value("FUSION")
    assert compile_archetype_condition(["POLYMERIZATION"]).resolved == (
        ("POLYMERIZATION", 0x46),
    )
    assert compile_archetype_condition(["FUSION"]).resolved == (("FUSION", 0x46),)


def test_a_a_name_outside_the_table_is_never_guessed():
    """
    🔴 **이름이 비슷하다는 이유로 코드를 고르지 않는다.**

    ``SET_CENTURION`` 은 표에 없다. 표에 ``SET_CENTUR`` 로 시작하는 다른
    이름이 있어도 (또는 없어도) 컴파일러는 **아무것도 고르지 않는다.**
    """
    result = compile_archetype_condition(["CENTURION"])
    assert result is not None
    assert result.resolved == ()
    assert result.unresolved == ("CENTURION",)
    assert result.condition == ArchetypeUnresolved("CENTURION")


@pytest.mark.parametrize("name", UNRESOLVABLE)
def test_a_the_three_measured_unresolvable_names_stay_unresolved(name, table):
    """
    실측으로 확인한 미해결 이름 셋. 상수 파일이 그 카드군보다 오래된
    스냅숏이기 때문이고, **데이터를 갱신해야** 풀린다.
    """
    assert table.archetypes.value(name) is None
    result = compile_archetype_condition([name])
    assert result.unresolved == (name,)
    assert result.is_complete is False


# ======================================================================
# B. 세 가지 실패가 서로 다른 값이다
# ======================================================================


def test_b_no_archetype_requirement_returns_none():
    """
    🔴 **결과 객체를 만들지 않는다.** ``Condition | None`` 칸을 하나 더
    만들면 "조건이 없다" 와 "적지 않았다" 가 같은 타입이 된다 (3-E-34).
    """
    assert compile_of(constraint()) is None
    assert compile_of(constraint(races=[1], levels=[4])) is None
    assert compile_archetype_condition([]) is None
    assert compile_archetype_condition([], unread=[]) is None


def test_b_an_unresolved_name_is_data_missing_not_a_missing_rule():
    """
    이름은 읽었는데 코드가 없다 → **데이터**가 없다. 없는 규칙 계층을
    찾아 헤매게 만들지 않는다.
    """
    node = compile_archetype_condition(["CENTURION"]).condition
    assert node.evaluate(None, None) is UNKNOWN
    assert node.missing_rules(None, None) == ()
    [reason] = node.unknown_reasons(None, None)
    assert "SET_CENTURION" in reason


def test_b_an_unread_call_is_a_missing_rule():
    """
    이름을 아예 읽지 못했다 → **코드**가 없다 (Lua 분석이 변수를 못 따라
    간다). 그래서 이쪽은 ``missing_rules`` 에 이름이 올라간다.
    """
    result = compile_of(constraint(raw_predicates=["IsSetCard(setcode)"]))
    assert result.unread == ("IsSetCard(setcode)",)
    assert result.resolved == ()
    assert result.condition == UnimplementedRule(UNREAD_RULE)
    assert result.condition.missing_rules(None, None) == (UNREAD_RULE,)


def test_b_several_unread_calls_raise_one_missing_rule_not_many():
    result = compile_archetype_condition(
        [], unread=["IsSetCard(a)", "IsSetCard(b)", "IsSetCard(c)"]
    )
    assert len(result.unread) == 3
    assert result.condition.missing_rules(None, None) == (UNREAD_RULE,)


def test_b_only_archetype_calls_are_taken_from_the_raw_predicates():
    """``raw_predicates`` 에 다른 술어가 섞여 있어도 머리말로 가린다."""
    assert unread_archetype_calls(
        ["IsSetCard(setcode)", "IsRace(something)", "IsLevel(x)"]
    ) == ("IsSetCard(setcode)",)
    assert UNREAD_PREFIX == "IsSetCard("


def test_b_a_result_with_nothing_in_it_cannot_be_built():
    with pytest.raises(ValueError):
        ArchetypeCompilation(condition=IsSetCard((SET_ORCUST,)))
    with pytest.raises(TypeError):
        ArchetypeCompilation(condition="오르페골", resolved=(("ORCUST", 1),))


# ======================================================================
# B-2. 🔴 **실제 분석기가 그 흔적을 남기는가** — 변이 시험이 찾은 구멍
# ======================================================================
#
# 처음 이 파일의 시험들은 ``raw_predicates`` 를 **손으로 채워** 넣었다.
# 그래서 ``analysis/effect_analyzer.py::_record_unread`` 를 통째로 지워도
# 170개가 **전부 통과했다** (변이 M8). 손으로 만든 입력은 컴파일러를
# 시험하지만 그 입력이 실제로 생기는지는 시험하지 않는다.


@requires_official_db
def test_b2_the_analyzer_leaves_a_trace_when_it_cannot_read_the_argument(repository):
    """
    실제 카드의 실제 스크립트로 확인한다.

    ``c58811192`` (성령수기 키문팔코스) 는 ``IsSetCard(setcode)`` 라고
    적는다 — 인자가 런타임 변수다. 그 흔적이 없으면
    ``setcodes == []`` 이 되어 **"카드군 요구가 없다"** 와 구별되지 않고,
    그 필터를 쓰는 쪽이 **모든 카드를 통과시킨다.**
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analysis = EffectAnalyzer(repository).analyze(repository.get(58811192))
    constraints = [
        effect.selection.constraint
        for effect in analysis.effects
        if effect.selection is not None and effect.selection.constraint is not None
    ]

    traced = [c for c in constraints if unread_archetype_calls(c.raw_predicates)]
    assert traced, "읽지 못한 IsSetCard 의 흔적이 없다"
    for c in traced:
        assert c.setcodes == [], "이름을 읽었다면 흔적을 남길 이유가 없다"
        result = compile_of(c)
        assert result is not None, "흔적이 있는데 '요구 없음' 으로 접혔다"
        assert result.is_complete is False
        assert result.condition.missing_rules(None, None) == (UNREAD_RULE,)

    # 같은 카드의 다른 블록은 이름을 제대로 읽는다 — 흔적이 남지 않는다.
    read = [c for c in constraints if c.setcodes]
    assert read, "이름을 읽은 블록이 하나도 없다"
    for c in read:
        assert unread_archetype_calls(c.raw_predicates) == ()


@requires_official_db
def test_b2_a_variable_named_after_the_script_is_traced_too(repository):
    """``IsSetCard(s.listed_series)`` 도 같은 흔적을 남긴다."""
    from analysis.effect_analyzer import EffectAnalyzer

    analysis = EffectAnalyzer(repository).analyze(repository.get(81878201))
    calls = [
        call
        for effect in analysis.effects
        if effect.selection is not None and effect.selection.constraint is not None
        for call in unread_archetype_calls(effect.selection.constraint.raw_predicates)
    ]
    assert "IsSetCard(s.listed_series)" in calls, calls


@requires_official_db
def test_b2_reading_a_name_never_leaves_a_false_trace(repository):
    """
    🔴 **흔적을 과하게 남기지도 않는다.** 기르수는
    ``IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})`` 로 이름을 둘 다 읽으므로
    ``raw_predicates`` 가 비어 있어야 한다. 비어 있지 않으면 전부 옮긴
    조건이 ``UNKNOWN`` 을 달고 나간다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analysis = EffectAnalyzer(repository).analyze(repository.get(GIRSU))
    [to_grave] = [e for e in analysis.effects if e.raw.index == "e1"]
    source = to_grave.selection.constraint

    assert source.setcodes == ["ORCUST", "WORLD_LEGACY"]
    assert unread_archetype_calls(source.raw_predicates) == ()

    compiled = compile_of(source)
    assert compiled.is_complete is True
    assert compiled.condition == IsSetCard((SET_ORCUST, SET_WORLD_LEGACY))


# ======================================================================
# C. 못 옮긴 이름을 버리지 않는다 (시나리오 F 의 핵심)
# ======================================================================


def test_c_a_partial_list_keeps_the_unresolved_half_as_unknown():
    """
    🔴 **``IsSetCard`` 의 목록은 "하나라도 맞으면" 이다.** 못 바꾼 이름을
    그냥 빼면 조건이 **좁아지고** 센츄리온 카드가 ``FALSE`` 가 된다.
    ``Or`` 로 묶어 3치 논리에 맡긴다.
    """
    result = compile_archetype_condition(["ORCUST", "CENTURION"])

    assert result.resolved == (("ORCUST", SET_ORCUST),)
    assert result.unresolved == ("CENTURION",)
    assert result.is_complete is False
    assert result.condition == Or(
        (IsSetCard((SET_ORCUST,)), ArchetypeUnresolved("CENTURION"))
    )


@requires_official_db
def test_c_the_resolved_half_still_decides_when_it_matches(view, state):
    """해결된 쪽이 맞추면 **확정**이다 — ``Or(TRUE, UNKNOWN) == TRUE``."""
    condition = compile_archetype_condition(["ORCUST", "CENTURION"]).condition

    assert ask(view, state, condition, GIRSU) is TRUE
    assert ask(view, state, condition, LONGIRSU) is TRUE


@requires_official_db
def test_c_a_card_outside_the_resolved_half_becomes_unknown_not_false(view, state):
    """
    🔴 **여기가 이 Phase 의 요점이다.** 페더맨은 오르페골이 아니지만,
    센츄리온인지 **알 수 없다.** 그래서 ``FALSE`` 가 아니라 ``UNKNOWN`` 이다.

    못 바꾼 이름을 버렸다면 이 자리에서 ``FALSE`` 가 나왔을 것이다.
    """
    partial = compile_archetype_condition(["ORCUST", "CENTURION"]).condition
    complete = compile_archetype_condition(["ORCUST"]).condition

    assert ask(view, state, partial, FEATHERMAN) is UNKNOWN
    # 전부 옮긴 조건은 같은 카드를 **확정으로** 거짓이라고 말한다.
    assert ask(view, state, complete, FEATHERMAN) is FALSE


@requires_official_db
def test_c_an_unread_call_makes_every_card_unknown(view, state):
    """인자를 못 읽었으면 어느 카드도 판정할 수 없다."""
    condition = compile_archetype_condition([], unread=["IsSetCard(setcode)"]).condition

    for card_id in (GIRSU, FEATHERMAN, LAVA_GOLEM):
        assert ask(view, state, condition, card_id) is UNKNOWN


# ======================================================================
# D. 실제 카드 시나리오 A~D (일치 · 불일치 · 복합 · 계층)
# ======================================================================


@requires_official_db
def test_d_scenario_a_a_card_in_the_archetype_passes(view, state):
    condition = compile_archetype_condition(["ORCUST"]).condition
    assert ask(view, state, condition, GIRSU) is TRUE
    assert ask(view, state, condition, LONGIRSU) is TRUE


@requires_official_db
def test_d_scenario_b_a_card_of_another_archetype_does_not(view, state):
    """같은 몬스터여도 카드군이 다르면 만족하지 않는다."""
    condition = compile_archetype_condition(["ORCUST"]).condition
    assert ask(view, state, condition, FEATHERMAN) is FALSE
    assert ask(view, state, And((IsMonster(), condition)), FEATHERMAN) is FALSE


@requires_official_db
def test_d_scenario_c_a_card_in_two_archetypes_answers_both(view, state, repository):
    """
    기르수는 오르페골 **이면서** 잭나이츠다. 두 판정이 각각 정확해야 한다.
    """
    assert repository.get(GIRSU).setcodes == [SET_ORCUST, SET_MEKK_KNIGHT]

    orcust = compile_archetype_condition(["ORCUST"]).condition
    mekk = compile_archetype_condition(["MEKK_KNIGHT"]).condition
    legacy = compile_archetype_condition(["WORLD_LEGACY"]).condition

    assert ask(view, state, orcust, GIRSU) is TRUE
    assert ask(view, state, mekk, GIRSU) is TRUE
    assert ask(view, state, legacy, GIRSU) is FALSE
    # 롱기르수는 오르페골만이다 — 둘째 카드군이 참이 되면 거짓 양성이다.
    assert ask(view, state, orcust, LONGIRSU) is TRUE
    assert ask(view, state, mekk, LONGIRSU) is FALSE


@requires_official_db
def test_d_scenario_d_the_hierarchy_comes_through_the_compiler(view, state):
    """
    숫자 코드의 계층(하위 12비트 일치 + 상위 4비트 포함)이 이름 쪽에서도
    그대로 보인다. 페더맨은 ``0x3008`` 하나를 들고 있다.
    """
    hero = compile_archetype_condition(["HERO"])
    elemental = compile_archetype_condition(["ELEMENTAL_HERO"])
    destiny = compile_archetype_condition(["DESTINY_HERO"])

    assert hero.resolved == (("HERO", SET_HERO),)
    assert elemental.resolved == (("ELEMENTAL_HERO", SET_ELEMENTAL_HERO),)

    assert ask(view, state, hero.condition, FEATHERMAN) is TRUE
    assert ask(view, state, elemental.condition, FEATHERMAN) is TRUE
    assert ask(view, state, destiny.condition, FEATHERMAN) is FALSE


@requires_official_db
def test_d_a_card_with_no_archetype_is_false_for_every_resolved_name(view, state):
    for name in ("ORCUST", "HERO", "MEKK_KNIGHT"):
        condition = compile_archetype_condition([name]).condition
        assert ask(view, state, condition, LAVA_GOLEM) is FALSE


# ======================================================================
# E. 거짓 양성 전수 검사 (§8) — 재는 쪽이 중요하다
# ======================================================================


@requires_official_db
def test_e_no_resolved_name_ever_matches_across_a_different_base(repository, table):
    """
    🔴 **차단이 줄어든 것으로 정확성을 주장하지 않는다.** 616개 카드군을
    전부 질의해서, 걸린 카드가 **같은 base 를 공유하지 않는 경우가 하나도
    없음**을 확인한다. 하나라도 있으면 그것이 거짓 양성이다.
    """
    from engine.archetype import SETCODE_BASE_MASK

    cards = list(repository.all_cards())
    offenders = []
    for name in table.archetypes.names():
        query = table.archetypes.value(name)
        for card in cards:
            if not matches_setcode(card.setcodes, query):
                continue
            if not any(
                (code & SETCODE_BASE_MASK) == (query & SETCODE_BASE_MASK)
                for code in card.setcodes
            ):
                offenders.append((name, card.id))
    assert offenders == [], offenders[:10]


@requires_official_db
def test_e_the_exact_match_population_is_always_a_subset(repository, table):
    """
    ``IsSetCard`` 는 정확 일치보다 **좁아지지 않는다.** 좁아지는 카드군이
    하나라도 있으면 기존 검색이 찾던 카드를 효과가 놓친다는 뜻이다.
    """
    cards = list(repository.all_cards())
    for name in table.archetypes.names():
        query = table.archetypes.value(name)
        exact = {c.id for c in cards if query in c.setcodes}
        included = {c.id for c in cards if matches_setcode(c.setcodes, query)}
        assert exact <= included, name


@requires_official_db
def test_e_seventy_eight_archetypes_are_wider_than_an_exact_match(repository, table):
    """
    실측: 616개 중 **78개**가 정확 일치보다 넓고, 그 78개의 합계가
    **1,880 → 3,008장 (+1,128)** 이다. 나머지 537개는 차이가 없다.

    이 수가 :meth:`~core.card_repository.CardRepository.by_setcode` 와
    ``IsSetCard`` 의 **의미 차이**다 (아래 §F 가 그 계약을 고정한다).
    """
    cards = list(repository.all_cards())
    wider, exact_total, included_total = 0, 0, 0
    for name in table.archetypes.names():
        query = table.archetypes.value(name)
        exact = {c.id for c in cards if query in c.setcodes}
        included = {c.id for c in cards if matches_setcode(c.setcodes, query)}
        if included != exact:
            wider += 1
            exact_total += len(exact)
            included_total += len(included)

    assert wider == 78
    assert (exact_total, included_total) == (1880, 3008)


# ======================================================================
# F. 검색용 by_setcode() 의 계약은 그대로다 (§6 · 시나리오 G)
# ======================================================================


@requires_official_db
def test_f_by_setcode_still_means_exact_match(repository):
    """
    🔴 **검색의 의미론을 바꾸지 않았다.** ``by_setcode`` 는 여전히 정확
    일치이고, 그래서 ``SET_HERO`` 로 찾으면 엘리멘틀 히어로가 나오지
    않는다. 효과 조건과 검색은 **다른 질문**이므로 같은 답을 강요하지
    않는다 — 바꾸려면 ``/search`` · ``/deck`` 의 출력이 달라지고, 그것은
    이번 범위가 아니다 (Phase 6-C 보고서 §12).
    """
    exact = {card.id for card in repository.by_setcode(SET_HERO)}
    included = {
        card.id
        for card in repository.all_cards()
        if matches_setcode(card.setcodes, SET_HERO)
    }

    assert len(exact) == 6
    assert len(included) == 159
    assert exact < included


def test_f_the_compiler_does_not_touch_the_repository():
    """컴파일러는 저장소를 보지 않는다 — 이름과 표만 본다."""
    source = pathlib.Path("engine/archetype_compiler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [m for m in imported if m.startswith(("core", "analysis", "sources"))], (
        imported
    )


def test_f_the_engine_still_borrows_exactly_one_symbol_from_analysis():
    """
    🔴 **ADR-007 을 고치지 않았다.** 첫 구현은 이 컴파일러가
    ``CardConstraint`` 를 ``TYPE_CHECKING`` 으로 가져왔고,
    ``test_phase2_contracts.py`` 의 지뢰선이 발화했다. 그것이 옳았으므로
    타입 대신 **문자열과 숫자만** 받도록 바꿨다.
    """
    root = pathlib.Path("engine")
    borrowed = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "analysis"
            ):
                borrowed.update(alias.name for alias in node.names)
    assert borrowed == {"LimitScope"}, borrowed


# ======================================================================
# G. 복합 조건에서 불확실성이 안전하게 전파된다 (시나리오 F)
# ======================================================================


@requires_official_db
def test_g_unknown_does_not_fold_in_and_or_not(view, state):
    partial = compile_archetype_condition(["ORCUST", "CENTURION"]).condition
    context = ConditionContext(player=MINE, source=in_hand(state, FEATHERMAN))

    assert partial.evaluate(view, context) is UNKNOWN
    assert And((IsMonster(), partial)).evaluate(view, context) is UNKNOWN
    assert Not(partial).evaluate(view, context) is UNKNOWN
    # 확정된 거짓과 만나면 거짓이다 — 접는 것이 아니다.
    #
    # 🔴 처음에 이 두 줄을 ``UNKNOWN`` 으로 적었다가 틀렸다. 페더맨은
    # 「성유물」 카드가 **아니라는 것이 확정**이므로 ``And`` 의 한쪽이
    # ``FALSE`` 이고, 그러면 나머지를 몰라도 결과는 ``FALSE`` 다. 바로
    # 위 주석이 그렇게 적혀 있었는데 단정이 반대였다.
    assert And((IsSetCard((SET_WORLD_LEGACY,)), partial)).evaluate(
        view, context
    ) is FALSE
    assert And((Not(IsMonster()), partial)).evaluate(view, context) is FALSE
    # 확정된 참과 만나면 참이다.
    assert Or((IsMonster(), partial)).evaluate(view, context) is TRUE


@requires_official_db
def test_g_the_reason_survives_the_combination(view, state):
    partial = compile_archetype_condition(["ORCUST", "CENTURION"]).condition
    combined = And((IsMonster(), partial))
    context = ConditionContext(player=MINE, source=in_hand(state, FEATHERMAN))

    reasons = combined.unknown_reasons(view, context)
    assert any("SET_CENTURION" in reason for reason in reasons), reasons
    assert combined.missing_rules(view, context) == ()


# ======================================================================
# H. 실제 전달 경로 — 후보를 거르는 자리에서 쓰인다
# ======================================================================


@requires_official_db
def test_h_the_compiled_condition_filters_candidates(view, state):
    """
    🔴 **새 통로를 만들지 않았다.** ``CandidateSource.require`` 가
    ``Condition`` 을 그대로 받으므로, 컴파일 결과를 그 자리에 넣는다.
    """
    compiled = compile_archetype_condition(["ORCUST"])
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=compiled.condition,
        ),
        maximum=2,
    )
    candidates = CandidateResolver(view).resolve(
        choice, ConditionContext(player=MINE)
    )

    found = {state.find_instance(i).card_id for i in candidates.eligible}
    assert found == {GIRSU, LONGIRSU}
    assert candidates.undecided == ()


@requires_official_db
def test_h_a_partial_compilation_puts_the_rest_in_undecided(view, state):
    """
    🔴 **모르는 카드가 조용히 빠지지 않는다.** 못 옮긴 이름이 있으면
    해당하지 않는 카드들이 ``undecided`` 로 남고, 이유도 함께 남는다
    (STRUCTURAL-15 와 같은 규율).
    """
    compiled = compile_archetype_condition(["ORCUST", "CENTURION"])
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=compiled.condition,
        ),
        maximum=4,
    )
    candidates = CandidateResolver(view).resolve(
        choice, ConditionContext(player=MINE)
    )

    eligible = {state.find_instance(i).card_id for i in candidates.eligible}
    undecided = {state.find_instance(i).card_id for i in candidates.undecided}

    assert eligible == {GIRSU, LONGIRSU}
    assert FEATHERMAN in undecided and LAVA_GOLEM in undecided
    assert any("SET_CENTURION" in reason for reason in candidates.reasons)


@requires_official_db
def test_h_compiling_and_evaluating_do_not_touch_the_board(state, view):
    before = state.state_hash()
    compiled = compile_archetype_condition(["ORCUST", "CENTURION"])
    compiled.condition.evaluate(
        view, ConditionContext(player=MINE, source=in_hand(state, GIRSU))
    )
    assert state.state_hash() == before


# ======================================================================
# I. 직렬화와 출처 보존
# ======================================================================


def test_i_the_result_records_which_name_became_which_code():
    result = compile_archetype_condition(["ORCUST", "WORLD_LEGACY"])

    assert result.resolved == (
        ("ORCUST", SET_ORCUST),
        ("WORLD_LEGACY", SET_WORLD_LEGACY),
    )
    assert result.to_dict() == {
        "condition": {
            "kind": "is_set_card",
            "setcodes": ["0x11b", "0xfe"],
        },
        "resolved": [
            {"name": "ORCUST", "setcode": "0x11b"},
            {"name": "WORLD_LEGACY", "setcode": "0xfe"},
        ],
    }


def test_i_an_incomplete_result_says_what_is_missing():
    result = compile_archetype_condition(["ORCUST", "CENTURION"], unread=["IsSetCard(x)"])
    data = result.to_dict()

    assert data["unresolved"] == ["CENTURION"]
    assert data["unread"] == ["IsSetCard(x)"]
    assert "SET_CENTURION→?" in result.describe_ko()
    assert "읽지 못한 호출 1개" in result.describe_ko()


def test_i_the_same_names_compile_to_the_same_representation():
    """
    같은 이름 목록은 언제나 같은 표현이 된다.

    🔴 **순서는 묶음 안에서만 보존된다.** 처음에 "순서가 다르면 다른
    표현" 이라고 단정했다가 틀렸다 — 컴파일러는 해결된 코드를
    ``IsSetCard`` **하나로 모으고** 미해결 이름을 그 뒤에 붙이므로,
    ``["CENTURION", "ORCUST"]`` 와 ``["ORCUST", "CENTURION"]`` 은 같은
    표현이 된다.

    그것이 맞는 동작이다. ``Or`` 는 교환 가능하고, 노드를 이름마다 하나씩
    만들면 ``IsSetCard`` 가 목록을 받는 의미(한 번에 묻는다)가 사라진다.
    보존되는 것은 **묶음 안의 순서**이고, 그것이 스크립트가 적은 순서다.
    """
    first = compile_archetype_condition(["ORCUST", "CENTURION"])
    second = compile_archetype_condition(["ORCUST", "CENTURION"])
    assert first.canonical_state() == second.canonical_state()

    flipped = compile_archetype_condition(["CENTURION", "ORCUST"])
    assert flipped.canonical_state() == first.canonical_state()

    # 해결된 것들끼리는 적힌 순서가 그대로 남는다.
    forward = compile_archetype_condition(["ORCUST", "WORLD_LEGACY"])
    backward = compile_archetype_condition(["WORLD_LEGACY", "ORCUST"])
    assert forward.condition == IsSetCard((SET_ORCUST, SET_WORLD_LEGACY))
    assert backward.condition == IsSetCard((SET_WORLD_LEGACY, SET_ORCUST))
    assert forward.canonical_state() != backward.canonical_state()


def test_i_the_table_can_be_swapped_so_the_three_paths_are_all_reachable():
    """
    상수 표를 바꿔 끼울 수 있다 — 그래서 "표에 없는 이름" 을 실제 데이터에
    의존하지 않고도 만들 수 있다.
    """
    empty = EngineVocabulary(ScriptConstants())
    assert len(empty.archetypes) == 0

    result = compile_archetype_condition(["ORCUST"], vocabulary=empty)
    assert result.unresolved == ("ORCUST",)
    assert result.resolved == ()
