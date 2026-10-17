"""
Phase 6-C — 카드군(아키타입) 조건과 특수 소환 몬스터의 소환 조건.

이 Phase 가 고친 **구조적 누락 두 가지**를 지킨다.

1. **카드군을 묻는 조건이 없었다** (STRUCTURAL-77). 자리는 이미 있었다 —
   ``CardDefinitionView.setcodes`` 가 관측에 실려 있었고 (3-E-18 test_11),
   후보를 거르는 ``CardCandidateSource.require`` 는 ``Condition`` 을 그대로
   받는다. 없던 것은 그 ``Condition`` 하나다.
2. **``TYPE_SPSUMMON`` 을 아무도 보지 않았다.** 메인덱 몬스터 344장이
   규칙상 일반 소환이 **확실히 불가능한데** ``NEEDS_TRIBUTE`` 262장 ·
   ``UNDETERMINED`` 82장으로 나갔다.

여기서 하지 않는 것
-------------------
카드군을 묻는 조건이 생겼다는 것은 **그 효과가 실행된다는 뜻이 아니다.**
``EFFECT_LIBRARY`` 등재는 여전히 16장이고, ``analysis`` 가 읽은 카드군
이름(``CardConstraint.setcodes``)을 엔진 조건으로 **자동으로 옮기는 계층은
없다** (아래 §C 가 그 경계를 고정한다).
"""

import ast
import pathlib

import pytest

from engine.action import PlayerAction
from engine.action_validation import ActionValidator
from engine.archetype import (
    SETCODE_BASE_MASK,
    SETCODE_MAX,
    SETCODE_SUBTYPE_MASK,
    matches_setcode,
    validate_setcode,
)
from engine.condition import (
    And,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    IsMonster,
    IsSetCard,
    Not,
    Or,
    PlayerRef,
)
from engine.cost.choice import CandidateSource, ChoiceSpec
from engine.cost.resolver import CandidateResolver
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.summon_rules import (
    NEVER_NORMAL_SUMMONABLE,
    SummonEligibility,
    assess_normal_summon,
)
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1

TRUE = ConditionResult.TRUE
FALSE = ConditionResult.FALSE
UNKNOWN = ConditionResult.UNKNOWN

# --- 실제 카드 -------------------------------------------------------
#: 잭나이츠 오르페골 기르수 — 레벨 4 효과 몬스터. 카드군 둘에 속한다.
GIRSU = 69811710
#: 엘리멘틀 히어로 페더맨 — 레벨 3 **통상** 몬스터, 카드군 ``0x3008``.
FEATHERMAN = 21844576
#: 히어로의 유산 — 마법 카드, 카드군 ``0x008`` (상위 비트가 **없다**).
HERO_LEGACY = 25614410
#: 용암 마신 라바 골렘 — 레벨 8 ``TYPE_SPSUMMON``. 카드군이 **없다**.
LAVA_GOLEM = 102380
#: 푸른 눈의 백룡 — 레벨 8 통상. 제물이 필요한 쪽의 대조군.
BLUE_EYES = 89631139
#: 크리보 — 레벨 1 효과 몬스터. 소환 제약을 못 읽는 쪽의 대조군.
KURIBOH = 40640057

# --- 실제 카드군 코드 -------------------------------------------------
#: ``SET_HERO`` — 큰 묶음.
SET_HERO = 0x008
#: ``SET_ELEMENTAL_HERO`` — ``SET_HERO`` 안의 작은 묶음.
SET_ELEMENTAL_HERO = 0x3008
#: ``SET_DESTINY_HERO`` — 같은 큰 묶음 안의 **다른** 작은 묶음.
SET_DESTINY_HERO = 0xC008
#: ``SET_ORCUST`` · ``SET_MEKK_KNIGHT`` — 기르수가 속한 둘.
SET_ORCUST = 0x11B
SET_MEKK_KNIGHT = 0x10C
#: ``SET_WORLD_LEGACY`` (성유물) — 기르수 ①이 **찾는** 카드군.
#: 기르수 자신은 여기 속하지 않는다 — 찾는 것과 속하는 것은 다른 말이다.
SET_WORLD_LEGACY = 0x0FE
#: ``SET_WORLD_CHALICE`` (성잔) — 기르수가 속하지도 찾지도 않는 카드군.
SET_WORLD_CHALICE = 0x0FD


# ======================================================================
# 판 · 도구
# ======================================================================


@pytest.fixture
def state(repository) -> GameState:
    """
    내 패: 기르수 · 페더맨 · 히어로의 유산 · 라바 골렘 · 푸른 눈 · 크리보.
    상대 마법 / 함정 존에 **뒷면** 카드 한 장 — 정체를 모르는 쪽을 만든다.
    """
    game = GameState.create(
        repository,
        decks=(
            [GIRSU, FEATHERMAN, HERO_LEGACY, LAVA_GOLEM, BLUE_EYES, KURIBOH]
            + [FEATHERMAN] * 8,
            [FEATHERMAN] * 10,
        ),
        turn_player=MINE,
        seed=3,
    )
    game.draw(MINE, 6)
    game.draw(THEIRS, 2)
    game.move(
        game.player(THEIRS).hand[0],
        Zone.SZONE,
        to_player=THEIRS,
        position=Position.FACEDOWN,
    )
    game.turn.set_phase(Phase.MAIN1)
    return game


@pytest.fixture
def view(state) -> GameStateView:
    return GameStateView.from_state(state, viewer=MINE)


def in_hand(state: GameState, card_id: int, player: int = MINE) -> InstanceId:
    return next(
        card.instance_id
        for card in state.player(player).hand
        if card.card_id == card_id
    )


def ask(view, state, condition, card_id, player=MINE) -> ConditionResult:
    """``card_id`` 를 문맥의 ``source`` 로 놓고 조건을 묻는다."""
    context = ConditionContext(
        player=MINE, source=in_hand(state, card_id, player)
    )
    return condition.evaluate(view, context)


# ======================================================================
# A. 표현 — 규칙 자체
# ======================================================================


def test_a_the_base_must_match_and_the_asked_subtype_must_be_contained():
    """
    하위 12비트는 **같아야** 하고 상위 4비트는 **포함**이면 된다.

    근거는 ``engine/archetype.py`` 의 설명에 있다 — 엘리멘틀 히어로 에어맨
    (40044918) 의 공식 원문이 「덱에서 "히어로" 몬스터 1장을 패에 넣는다」
    이고 그 스크립트는 ``IsSetCard(SET_HERO)`` 로 묻는데, 엘리멘틀 히어로
    카드들이 들고 있는 코드는 ``0x3008`` 이다.
    """
    # 작은 묶음의 카드를 큰 묶음으로 물으면 참이다.
    assert matches_setcode([SET_ELEMENTAL_HERO], SET_HERO) is True
    # 그 역은 거짓이다 — 「히어로」 카드가 「엘리멘틀 히어로」는 아니다.
    assert matches_setcode([SET_HERO], SET_ELEMENTAL_HERO) is False
    # 같은 큰 묶음 안의 **다른** 작은 묶음끼리는 서로 아니다.
    assert matches_setcode([SET_ELEMENTAL_HERO], SET_DESTINY_HERO) is False
    assert matches_setcode([SET_DESTINY_HERO], SET_ELEMENTAL_HERO) is False
    # 하위 12비트가 다르면 상위가 같아도 아니다.
    assert matches_setcode([SET_ORCUST], SET_MEKK_KNIGHT) is False


def test_a_a_card_with_no_setcode_is_false_not_unknown():
    """
    코드를 하나도 안 가진 카드는 **어느 카드군에도 속하지 않는다.**

    카드 14,127장 중 6,221장(44.0%)이 그렇다. 그것은 ``cards.cdb`` 가 적어
    둔 사실이므로 "모른다" 가 아니다.
    """
    assert matches_setcode([], SET_ORCUST) is False


def test_a_an_impossible_code_is_refused_rather_than_never_matching():
    """
    코드일 수 없는 값은 거부한다. 조용히 통과시키면 **아무 카드와도 맞지
    않는 조건**이 만들어지고, 그것은 "속하지 않는다" 와 구별되지 않는다.
    """
    for bad in (0, -1, SETCODE_MAX + 1, 0x1000, 0xF000):
        with pytest.raises(ValueError):
            validate_setcode(bad)
    for wrong_type in (True, "0x11b", 0.0, None):
        with pytest.raises(TypeError):
            validate_setcode(wrong_type)

    # 실제 코드는 통과한다.
    for good in (SET_HERO, SET_ELEMENTAL_HERO, SET_ORCUST, SETCODE_MAX):
        assert validate_setcode(good) == good


def test_a_the_two_masks_do_not_overlap_and_cover_sixteen_bits():
    assert SETCODE_BASE_MASK & SETCODE_SUBTYPE_MASK == 0
    assert SETCODE_BASE_MASK | SETCODE_SUBTYPE_MASK == SETCODE_MAX


def test_a_the_condition_needs_at_least_one_code_and_keeps_it_immutable():
    with pytest.raises(ValueError):
        IsSetCard(())
    with pytest.raises(TypeError):
        IsSetCard([SET_ORCUST])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IsSetCard((SET_ORCUST, 0))


# ======================================================================
# B. 직렬화 — 같은 조건이면 같은 표현
# ======================================================================


def test_b_the_serialised_form_is_stable_and_names_the_codes():
    condition = IsSetCard((SET_ORCUST, SET_WORLD_CHALICE))

    assert condition.to_dict() == {
        "kind": "is_set_card",
        "setcodes": ["0x11b", "0xfd"],
    }
    assert condition.canonical_state() == (
        "is_set_card",
        (SET_ORCUST, SET_WORLD_CHALICE),
        None,
    )
    # 같은 조건을 두 번 만들면 같은 표현이다.
    assert (
        IsSetCard((SET_ORCUST,)).canonical_state()
        == IsSetCard((SET_ORCUST,)).canonical_state()
    )
    # 묻는 카드를 지목하면 표현에 들어간다.
    pinned = IsSetCard((SET_ORCUST,), instance=InstanceId(7))
    assert pinned.to_dict()["instance"] == 7
    assert pinned.canonical_state() != IsSetCard((SET_ORCUST,)).canonical_state()


def test_b_two_different_archetypes_do_not_share_a_representation():
    assert (
        IsSetCard((SET_HERO,)).canonical_state()
        != IsSetCard((SET_ELEMENTAL_HERO,)).canonical_state()
    )


def test_b_the_description_is_korean_and_mentions_every_code():
    text = IsSetCard((SET_ORCUST, SET_MEKK_KNIGHT)).describe_ko()

    assert "0x11b" in text and "0x10c" in text
    assert "카드군" in text


# ======================================================================
# C. 파싱 — analysis 는 **이름**, 엔진은 **숫자**
# ======================================================================


def test_c_analysis_already_reads_the_archetype_filter_as_names(repository):
    """
    기르수의 ``s.tgfilter`` 는 ``c:IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})``
    이고, ``analysis`` 가 그것을 **이름**으로 읽어 둔다. 이 Phase 는 그
    파서를 건드리지 않았다 — 읽는 자리는 이미 있었다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analysis = EffectAnalyzer(repository).analyze(repository.get(GIRSU))
    [to_grave] = [
        effect
        for effect in analysis.effects
        if effect.raw.index == "e1"
    ]

    assert to_grave.selection is not None
    assert to_grave.selection.constraint.setcodes == ["ORCUST", "WORLD_LEGACY"]


def test_c_the_compiler_now_turns_an_archetype_name_into_a_condition():
    """
    🔴 **이 시험의 몸이 Phase 6-D 에서 바뀌었다.** 원래 이름은
    ``test_c_nothing_turns_an_archetype_name_into_a_condition`` 이었고,
    세 가지를 고정했다 — 표에는 이름이 있다 · ``EngineVocabulary`` 가
    ``SET_`` 묶음을 내보내지 **않는다** · production 에 ``IsSetCard`` 를
    만드는 자리가 **없다**.

    셋 다 **쓰여진 시점에 맞았다.** Phase 6-C 는 조건만 만들고 그것을
    채우는 코드를 일부러 두지 않았다 (쓰는 자리가 없었으므로). Phase 6-D
    가 그 자리를 만들었으니 두 번째와 세 번째가 뒤집힌다. 첫 번째는
    그대로다.

    바뀐 사실을 그대로 고정한다.
    """
    from engine.archetype_compiler import compile_archetype_condition
    from engine.vocabulary import default_vocabulary
    from sources.script_constants import ScriptConstants

    constants = ScriptConstants.load()
    assert constants.setcode("ORCUST") == SET_ORCUST
    assert constants.setcode("SET_ELEMENTAL_HERO") == SET_ELEMENTAL_HERO

    # ① 이제 ``EngineVocabulary`` 가 카드군 묶음을 내보낸다.
    #: 🔴 **615 → 616** (Phase 6-T). 상류 데이터가 늘었고 이 Phase 의 변경
    #: 때문이 아니다 — 까닭은
    #: ``tests/engine/test_archetype_compiler.py`` 의
    #: ``test_a_the_table_is_the_only_source_of_a_code`` 설명에 적었다.
    vocabulary = default_vocabulary()
    assert "archetypes" in vocabulary.__slots__
    assert len(vocabulary.archetypes) == 616
    assert vocabulary.archetypes.value("ORCUST") == SET_ORCUST
    # 🔴 그 묶음은 여전히 ``others`` 에서 오지 않는다 — 출처가 다르다.
    assert "ORCUST" not in vocabulary.constants.others

    # ② 이제 production 에 조건을 만드는 자리가 **딱 한 곳** 있다.
    builders = []
    for root in ("engine", "agent", "deck", "app"):
        for module in pathlib.Path(root).rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "IsSetCard"
                ):
                    builders.append(module.as_posix())
    assert builders == ["engine/archetype_compiler.py"], builders

    # ③ 그 자리가 실제로 이름을 조건으로 바꾼다.
    compiled = compile_archetype_condition(["ORCUST"])
    assert compiled is not None
    assert compiled.condition == IsSetCard((SET_ORCUST,))
    assert compiled.is_complete is True

    # ④ 🔴 **그래도 이 Phase 가 등재를 늘리지는 않았다.** 옮길 수 있다는
    #    것과 적어 두었다는 것은 다른 말이고, ``EFFECT_LIBRARY`` 는 아직
    #    카드군 조건을 쓰지 않는다.
    #
    #    🔴 수가 16 에서 17 로 **움직였다** (Phase 6-K). 이 테스트가 틀린
    #    가정을 갖고 있었던 것이 아니라, 6-D 시점에 실제로 16건이었다. 늘린
    #    것은 카드군 조건이 아니라 어니스트 ① 이고, 그것도
    #    ``executable=False`` 다 — 아래 단언이 지키는 "카드군 조건이 등재를
    #    늘리지 않았다" 는 여전히 참이다.
    from engine.effect.library import EFFECT_LIBRARY, HONEST

    assert len(EFFECT_LIBRARY) == 17
    assert [
        entry.card_id for entry in EFFECT_LIBRARY
        if entry.definition.targets
        and any(
            "IsSetCard" in binding.describe_ko() for binding in entry.definition.targets
        )
    ] == []
    #: 🔴 Phase 6-L — 어니스트가 **실행 가능**이 되어 이 집합에서 빠졌다.
    #: 6-K 가 그것을 실행 불가로 실은 이유는 "정의가 '이 효과의 카드' 를
    #: 가리킬 이름이 없다" 였고, 6-L 이 그 이름을 만들었다 (``SELF_TARGET``).
    #: 남은 셋은 그대로이고, 이 테스트가 지키는 사실(카드군 조건이 등재를
    #: 늘리지 않았다)도 그대로다.
    assert {entry.card_id for entry in EFFECT_LIBRARY if not entry.executable} == {
        53129443, 83764718, 24623598
    }
    assert HONEST in {entry.card_id for entry in EFFECT_LIBRARY if entry.executable}


# ======================================================================
# D. 판정 — 실제 관측을 읽어 세 답을 낸다 (§8 시나리오 3)
# ======================================================================


def test_d_a_card_in_its_archetype_is_true(view, state):
    assert ask(view, state, IsSetCard((SET_ORCUST,)), GIRSU) is TRUE
    assert ask(view, state, IsSetCard((SET_MEKK_KNIGHT,)), GIRSU) is TRUE


def test_d_a_list_matches_when_any_one_matches(view, state):
    """스크립트의 ``IsSetCard({A, B})`` 그대로 — 하나라도 맞으면 참이다."""
    assert (
        ask(view, state, IsSetCard((SET_WORLD_CHALICE, SET_ORCUST)), GIRSU)
        is TRUE
    )
    assert (
        ask(view, state, IsSetCard((SET_WORLD_CHALICE, SET_HERO)), GIRSU)
        is FALSE
    )


def test_d_a_card_outside_the_archetype_is_false(view, state):
    assert ask(view, state, IsSetCard((SET_WORLD_CHALICE,)), GIRSU) is FALSE
    assert ask(view, state, IsSetCard((SET_ORCUST,)), FEATHERMAN) is FALSE


def test_d_the_hierarchy_holds_on_real_cards(view, state):
    """
    페더맨은 ``0x3008`` 하나를 들고 있고, 히어로의 유산은 ``0x008`` 하나를
    들고 있다. 두 방향이 실제 카드에서 갈린다.
    """
    assert ask(view, state, IsSetCard((SET_HERO,)), FEATHERMAN) is TRUE
    assert ask(view, state, IsSetCard((SET_ELEMENTAL_HERO,)), FEATHERMAN) is TRUE
    assert ask(view, state, IsSetCard((SET_DESTINY_HERO,)), FEATHERMAN) is FALSE

    assert ask(view, state, IsSetCard((SET_HERO,)), HERO_LEGACY) is TRUE
    assert ask(view, state, IsSetCard((SET_ELEMENTAL_HERO,)), HERO_LEGACY) is FALSE


def test_d_a_card_with_no_archetype_is_false_with_no_doubt(view, state):
    """라바 골렘은 코드를 하나도 갖고 있지 않다 — 거짓이고, 이유가 없다."""
    condition = IsSetCard((SET_ORCUST,))
    context = ConditionContext(player=MINE, source=in_hand(state, LAVA_GOLEM))

    assert condition.evaluate(view, context) is FALSE
    assert condition.unknown_reasons(view, context) == ()


def test_d_an_archetype_is_asked_of_a_spell_as_readily_as_a_monster(view, state):
    """
    카드군은 **몬스터만의 성질이 아니다.** 히어로의 유산은 마법 카드이고
    ``0x008`` 을 들고 있다. 그래서 종류 조건과 카드군 조건을 **묶어야**
    "「히어로」 **몬스터**" 가 된다.
    """
    hero = IsSetCard((SET_HERO,))
    monster_hero = And((IsMonster(), hero))

    assert ask(view, state, hero, HERO_LEGACY) is TRUE
    assert ask(view, state, monster_hero, HERO_LEGACY) is FALSE
    assert ask(view, state, monster_hero, FEATHERMAN) is TRUE


# ======================================================================
# E. 모르는 것은 모른다 (§8 시나리오 4)
# ======================================================================


def test_e_a_face_down_card_of_the_opponent_is_unknown(state):
    """
    상대의 뒷면 카드는 정체를 모르므로 카드군도 모른다. **거짓이 아니다.**
    """
    theirs = GameStateView.from_state(state, viewer=MINE)
    [hidden] = [
        card
        for card in theirs.opponent.zone(Zone.SZONE).cards
        if card is not None
    ]
    condition = IsSetCard((SET_HERO,), instance=hidden.instance_id)
    context = ConditionContext(player=MINE)

    assert condition.evaluate(theirs, context) is UNKNOWN
    [reason] = condition.unknown_reasons(theirs, context)
    assert "뒷면" in reason


def test_e_a_card_in_a_concealed_zone_is_unknown(state):
    """상대 패는 통째로 가려져 있다 — 그 안의 카드는 관측에 없다."""
    mine = GameStateView.from_state(state, viewer=MINE)
    their_card = state.player(THEIRS).hand[0].instance_id
    condition = IsSetCard((SET_HERO,), instance=their_card)
    context = ConditionContext(player=MINE)

    assert condition.evaluate(mine, context) is UNKNOWN
    [reason] = condition.unknown_reasons(mine, context)
    assert "보이지 않" in reason


def test_e_without_a_source_the_question_has_no_subject(view):
    condition = IsSetCard((SET_HERO,))
    context = ConditionContext(player=MINE)

    assert condition.evaluate(view, context) is UNKNOWN
    assert condition.unknown_reasons(view, context) == (
        "문맥에 source 가 없어 어느 카드인지 알 수 없음",
    )


def test_e_unknown_does_not_fold_into_true_or_false(view, state):
    """``UNKNOWN`` 이 논리 결합을 통과해도 접히지 않는다."""
    their_card = state.player(THEIRS).hand[0].instance_id
    unknown = IsSetCard((SET_HERO,), instance=their_card)
    context = ConditionContext(player=MINE, source=in_hand(state, FEATHERMAN))

    assert unknown.evaluate(view, context) is UNKNOWN
    assert And((IsSetCard((SET_HERO,)), unknown)).evaluate(view, context) is UNKNOWN
    assert Not(unknown).evaluate(view, context) is UNKNOWN
    # 확정된 거짓과 만나면 결과는 거짓이다 — 그것은 접는 것이 아니다.
    assert (
        And((IsSetCard((SET_WORLD_CHALICE,)), unknown)).evaluate(view, context)
        is FALSE
    )
    assert Or((IsSetCard((SET_HERO,)), unknown)).evaluate(view, context) is TRUE


# ======================================================================
# F. 전달 경로 — 후보를 거르는 자리에서 실제로 쓰인다
# ======================================================================


def test_f_the_candidate_filter_uses_the_condition_as_it_stands(view, state):
    """
    🔴 **새 필터 모델을 만들지 않았다.** ``CandidateSource.require`` 가
    ``Condition`` 을 그대로 받고, ``CandidateResolver`` 가 후보마다 문맥의
    ``source`` 를 그 카드로 바꿔 판정한다. 그 통로에 조건 하나를 넣었다.
    """
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=IsSetCard((SET_HERO,)),
        ),
        maximum=2,
    )
    candidates = CandidateResolver(view).resolve(
        choice, ConditionContext(player=MINE)
    )

    found = {state.find_instance(i).card_id for i in candidates.eligible}
    assert found == {FEATHERMAN, HERO_LEGACY}
    assert candidates.undecided == ()


def test_f_a_concealed_zone_is_recorded_not_silently_empty(view):
    """
    상대 패를 후보로 삼으면 "없다" 가 아니라 "못 봤다" 가 남는다
    (STRUCTURAL-15). 카드군 조건이 그 구분을 망가뜨리지 않는다.
    """
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.OPPONENT,
            require=IsSetCard((SET_HERO,)),
        ),
        chooser=PlayerRef.OPPONENT,
    )
    candidates = CandidateResolver(view).resolve(
        choice, ConditionContext(player=MINE)
    )

    assert candidates.eligible == ()
    assert candidates.unchecked != ()


def test_f_evaluating_the_condition_does_not_touch_the_board(state, view):
    before = state.state_hash()
    evaluator = ConditionEvaluator(view)
    evaluator.evaluate(
        IsSetCard((SET_HERO, SET_ORCUST)),
        ConditionContext(player=MINE, source=in_hand(state, GIRSU)),
    )

    assert state.state_hash() == before


# ======================================================================
# G. 카드 유형 표현 (§8 시나리오 1 · 2) — **이미 있었다**
# ======================================================================


def test_g_the_four_basic_kinds_are_already_distinguished(repository):
    """일반 몬스터 · 효과 몬스터 · 마법 · 함정이 종류 이름으로 갈린다."""

    def names(card_id):
        return set(CardDefinitionView.of(repository.get(card_id)).type_names)

    assert names(FEATHERMAN) == {"MONSTER", "NORMAL"}
    assert names(GIRSU) == {"MONSTER", "EFFECT"}
    assert names(HERO_LEGACY) == {"SPELL"}

    view = CardDefinitionView.of(repository.get(FEATHERMAN))
    assert (view.is_monster, view.is_spell, view.is_trap) == (True, False, False)
    spell = CardDefinitionView.of(repository.get(HERO_LEGACY))
    assert (spell.is_monster, spell.is_spell, spell.is_trap) == (False, True, False)


@pytest.mark.parametrize(
    "combination",
    [
        ("MONSTER", "EFFECT", "SYNCHRO", "PENDULUM"),
        ("MONSTER", "EFFECT", "XYZ", "PENDULUM"),
        ("MONSTER", "EFFECT", "FUSION", "PENDULUM"),
        ("MONSTER", "EFFECT", "TUNER", "SYNCHRO"),
        ("MONSTER", "EFFECT", "SPIRIT"),
        ("MONSTER", "EFFECT", "GEMINI"),
        ("MONSTER", "EFFECT", "UNION"),
        ("MONSTER", "EFFECT", "TOON"),
        ("MONSTER", "EFFECT", "FLIP"),
        ("MONSTER", "RITUAL"),
        ("MONSTER", "EFFECT", "SPSUMMON"),
    ],
)
def test_g_composite_types_survive_the_trip_into_the_engine(
    repository, combination
):
    """
    복합 유형이 **관측까지** 그대로 간다. 비트마스크 한 칸에 담겨 있으므로
    표현 능력에 빈자리가 없다 — 이 Phase 가 여기에는 아무것도 더하지
    않았고, 더할 것이 없다는 사실을 고정한다.
    """
    matching = [
        card
        for card in repository.all_cards()
        if set(combination) <= set(card.type_names)
    ]
    assert matching, combination

    definition = CardDefinitionView.of(matching[0])
    assert set(combination) <= set(definition.type_names)


def test_g_the_engine_never_normal_summons_three_kinds(repository):
    """
    세 종류가 **확실히** 일반 소환되지 않는다. ``SPSUMMON`` 이 이 Phase 에서
    들어왔다.
    """
    assert NEVER_NORMAL_SUMMONABLE == frozenset({"RITUAL", "TOKEN", "SPSUMMON"})


# ======================================================================
# H. 특수 소환 몬스터의 소환 조건 (§8 시나리오 5 의 절반)
# ======================================================================


def test_h_a_special_summon_monster_is_now_refused_not_doubted(repository):
    """
    라바 골렘은 레벨 8 이고 ``TYPE_SPSUMMON`` 이다. **제물을 둘 치러도**
    일반 소환되지 않는다. 그 전에는 ``NEEDS_TRIBUTE`` 로 나가서 "제물만
    있으면 될지도 모른다" 고 말했다.
    """
    assessment = assess_normal_summon(
        CardDefinitionView.of(repository.get(LAVA_GOLEM))
    )

    assert assessment.eligibility is SummonEligibility.FORBIDDEN
    assert assessment.is_refusal is True
    assert assessment.tributes_required is None
    assert "SPSUMMON" in assessment.reason


def test_h_the_validator_refuses_it_outright(state):
    """판정이 검증기까지 **그대로** 간다 — 길을 새로 내지 않았다."""
    action = PlayerAction.normal_summon(MINE, in_hand(state, LAVA_GOLEM))
    result = ActionValidator(GameStateView.from_state(state, viewer=MINE)).validate(
        action
    )

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.CANNOT_NORMAL_SUMMON


def test_h_the_level_is_not_even_consulted(repository):
    """
    레벨을 보기 **전에** 거절한다. 순서가 뒤바뀌면 레벨 5 이상인 262장이
    ``NEEDS_TRIBUTE`` 로 나간다.
    """
    golem = CardDefinitionView.of(repository.get(LAVA_GOLEM))
    assert golem.monster_level == 8
    assert assess_normal_summon(golem).eligibility is SummonEligibility.FORBIDDEN

    # 레벨 8 통상 몬스터는 그대로 "제물이 필요하다" 다.
    blue_eyes = CardDefinitionView.of(repository.get(BLUE_EYES))
    needs = assess_normal_summon(blue_eyes)
    assert needs.eligibility is SummonEligibility.NEEDS_TRIBUTE
    assert needs.tributes_required == 2


def test_h_nothing_became_permitted(repository):
    """
    🔴 **그 변경(Phase 6-C)은 허가를 하나도 늘리지 않았다.** ``ORDINARY``
    는 542장 그대로이고, 움직인 것은 "모른다 · 제물이 필요하다" → "안 된다"
    뿐이었다.

    ::

        ordinary        542 →  542   (그대로)
        forbidden       148 →  492   (+344)
        needs_tribute 2,066 → 1,804  (-262)
        undetermined  4,311 → 4,229  ( -82)

    🔴 **Phase 6-U 가 그 다음 칸을 움직였다** (이 Phase 와 무관한 변경이고,
    이 시험이 세는 것은 코퍼스 분포이므로 숫자가 따라 움직인다). 이번에
    움직인 것은 "모른다" → "된다" 이고, 근거는 카드 **자신의 스크립트에
    소환 제약 상수가 없다는 사실**이다 (``docs/phase6u-effect-monster-
    normal-summon.md``).

    ::

        ordinary        542 → 4,570  (+4,028)
        forbidden       492 →   492   (그대로)
        needs_tribute 1,804 → 1,804  (그대로)
        undetermined  4,229 →   201  (-4,028)

    남은 201장은 **허가하지 않은 것이 옳은** 카드들이다 — 스크립트가 없는
    153장과 제약 상수를 가진 48장.
    """
    import collections

    counts: collections.Counter = collections.Counter()
    for card in repository.all_cards():
        if not card.is_monster or card.is_extra_deck:
            continue
        counts[
            assess_normal_summon(CardDefinitionView.of(card)).eligibility
        ] += 1

    assert sum(counts.values()) == 7067
    assert counts[SummonEligibility.ORDINARY] == 4570
    assert counts[SummonEligibility.FORBIDDEN] == 492
    assert counts[SummonEligibility.NEEDS_TRIBUTE] == 1804
    assert counts[SummonEligibility.UNDETERMINED] == 201


# ======================================================================
# I. 기르수 회귀 (§8 시나리오 5)
# ======================================================================


def test_i_girsu_is_read_as_the_card_it_is(repository):
    definition = CardDefinitionView.of(repository.get(GIRSU))

    assert definition.is_monster is True
    assert definition.is_extra_deck is False
    assert definition.monster_level == 4
    assert set(definition.type_names) == {"MONSTER", "EFFECT"}
    assert definition.setcodes == (SET_ORCUST, SET_MEKK_KNIGHT)


def test_i_girsu_is_permitted_and_the_reason_is_not_the_archetype(repository):
    """
    🔴 **카드군 조건은 기르수의 일반 소환과 아무 상관이 없다** — 그것이
    이 시험의 요지이고, 그 요지는 변하지 않았다.

    바뀐 것은 **다른 Phase 의 사실**이다. 이 시험은 카드군 조건이 생겼을
    때 기르수가 ``UNDETERMINED`` 임을 적었고, 그때는 맞았다. 그러나 적어 둔
    근거("효과 몬스터의 소환 제약을 읽는 계층이 없다")를 **"그러므로 영원히
    모른다"** 로 읽으면 틀린 전제가 된다 — Phase 6-U 가 카드 자신의
    스크립트를 읽어 기르수에 제약 상수가 **한 건도 없음**을 확인했다.

    그래서 지금 확인할 것은 그대로 하나다: 판정의 이유에 **카드군이
    나오지 않는다**. 열린 것도 카드군 때문이 아니다.
    """
    assessment = assess_normal_summon(
        CardDefinitionView.of(repository.get(GIRSU))
    )

    assert assessment.eligibility is SummonEligibility.ORDINARY
    assert assessment.permits_procedure is True
    assert assessment.is_refusal is False
    assert assessment.missing_rule is None
    # 카드군 때문이 아니다 — 이유에 카드군이 나오지 않는다.
    assert "카드군" not in assessment.reason
    assert "setcode" not in assessment.reason
    assert "오르페골" not in assessment.reason
    #: 근거는 룰북이다.
    assert "RULE-SUMMON-009" in assessment.reason


def test_i_the_validator_permits_girsu_and_still_withholds_the_unreadable(
    state, repository
):
    """
    기르수 쪽은 Phase 6-U 에서 허가가 났다 (위 시험의 설명 참고).

    🔴 **보류가 사라진 것이 아니다.** 증거를 만들 수 없는 카드는 그대로
    보류된다 — 그쪽을 함께 재지 않으면 이 시험이 "이제 전부 허가된다" 로
    읽힌다.
    """
    action = PlayerAction.normal_summon(MINE, in_hand(state, GIRSU))
    result = ActionValidator(GameStateView.from_state(state, viewer=MINE)).validate(
        action
    )

    assert result.validity is ActionValidity.VALID
    assert result.code is ValidationCode.OK
    assert result.missing_rule is None
    assert result.permits_execution is True

    #: 체츠커 — 공식 텍스트에 제약이 있는데 이 저장소에 스크립트가 없다.
    cetus = 77435268
    withheld = GameState.create(
        repository, decks=([cetus] + [FEATHERMAN] * 12, [FEATHERMAN] * 10)
    )
    withheld.draw(MINE, 2)
    withheld.draw(THEIRS, 1)
    withheld.turn.set_phase(Phase.MAIN1)
    held = ActionValidator(
        GameStateView.from_state(withheld, viewer=MINE)
    ).validate(PlayerAction.normal_summon(MINE, in_hand(withheld, cetus)))

    assert held.validity is ActionValidity.UNKNOWN
    assert held.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "summoning-condition" in held.missing_rule
    assert held.permits_execution is False


def test_i_what_the_archetype_condition_does_buy_girsu(view, state):
    """
    **달라진 것은 이것 하나다.** 기르수 ①의 「"오르페골" 또는 "성유물"
    카드」 를 고르는 필터를 이제 구조로 **적을 수 있다.** 적는 것과 그
    효과가 실행되는 것은 다른 말이고, 등재는 여전히 없다.
    """
    from engine.effect.library import entry_for

    orcust_or_relic = IsSetCard((SET_ORCUST, SET_WORLD_LEGACY))
    choice = ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=orcust_or_relic,
        )
    )
    candidates = CandidateResolver(view).resolve(
        choice, ConditionContext(player=MINE)
    )

    assert {state.find_instance(i).card_id for i in candidates.eligible} == {GIRSU}
    # 🔴 기르수가 걸린 것은 「오르페골」 쪽이다 — 「성유물」 카드는 아니다.
    assert ask(view, state, IsSetCard((SET_WORLD_LEGACY,)), GIRSU) is FALSE

    # 그런데 기르수의 효과는 등재되어 있지 않다.
    assert entry_for(GIRSU) is None


# ======================================================================
# J. 경계 — 이 Phase 가 하지 않은 것
# ======================================================================


def test_j_no_card_is_named_in_the_new_production_code():
    """
    카드 ID 도 카드 이름도 프로덕션에 들어가지 않았다. 규칙은 데이터
    형식 하나이고, 카드별 예외가 없다.
    """
    source = pathlib.Path("engine/archetype.py").read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # 설명(근거 서술)은 뺀다

    tree = ast.parse(source)
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    ]
    # 🔴 처음 쓴 단정이 **마스크 자신**(0xFFF=4095 · 0xF000=61440)을 잡았다.
    # 세려던 것은 패스코드이므로 마스크 셋을 빼고 센다.
    masks = {SETCODE_BASE_MASK, SETCODE_SUBTYPE_MASK, SETCODE_MAX}
    assert max(numbers) == SETCODE_MAX
    assert set(numbers) - masks <= {0, 1}, set(numbers) - masks
    assert "card_id" not in body


def test_j_the_archetype_rule_lives_in_exactly_one_place():
    """
    판정이 두 곳에 있으면 둘이 갈린다. 마스크를 직접 쓰는 production 파일은
    ``engine/archetype.py`` 하나뿐이다.
    """
    users = []
    for root in ("engine", "agent", "deck", "core", "analysis"):
        for module in pathlib.Path(root).rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            if "0xFFF" in text or "0xF000" in text:
                users.append(module.as_posix())
    assert users == ["engine/archetype.py"], users


def test_j_nothing_can_add_an_archetype_to_a_card_in_play():
    """
    🔴 **이 조건의 ``FALSE`` 가 완전한 답인 이유.**

    다른 카드의 지속 효과가 카드군을 더하는 경우는 판 어디에도 적히지
    않는다 — ``CardInstance`` 에 그런 칸이 없고, 쓰는 자리도 없다. 그래서
    지금 엔진이 만들 수 있는 **모든 판**에서 카드의 카드군은 정의가 말하는
    그대로다.

    이 시험이 깨지는 날(= 칸이 생기는 날) :class:`IsSetCard` 는 그 칸을
    함께 봐야 한다. 그때까지는 정의 하나로 충분하다.
    """
    from engine.state.card_instance import CardInstance

    fields = set(CardInstance.__dataclass_fields__)
    assert not [name for name in fields if "setcode" in name or "archetype" in name]

    for root in ("engine", "agent"):
        for module in pathlib.Path(root).rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            assert "add_setcode" not in text, module.as_posix()
            assert "AddSetcode" not in text, module.as_posix()


def test_j_this_phase_turned_on_no_new_execution():
    """
    등재된 효과는 그대로 16개이고, 전부 ``ACTIVATE`` 모양이다. 카드군
    조건이 생겼다고 유발 효과가 켜지지 않았다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    # 🔴 16 → 17 (Phase 6-K, 어니스트 ①) → 실행 수 13 → **14** (Phase 6-L).
    # 이 테스트가 지키는 것은 "**카드군 조건**이 실행을 켜지 않았다" 이고,
    # 늘어난 하나는 카드군 조건이 아니라 자기 참조(``SELF_TARGET``)에서
    # 왔다. 아래 두 줄이 그것을 이름으로 못박는다.
    assert len(EFFECT_LIBRARY) == 17
    assert len([entry for entry in EFFECT_LIBRARY if entry.executable]) == 14
    #: 🔴 실행되는 효과 중 **카드군 조건을 쓰는 것이 하나도 없다.**
    assert [
        entry.card_id
        for entry in EFFECT_LIBRARY
        if entry.executable
        and any("카드군" in b.describe_ko() for b in entry.definition.targets)
    ] == []
