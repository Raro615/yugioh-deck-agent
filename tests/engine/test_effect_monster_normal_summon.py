"""
Phase 6-U — 효과 몬스터의 일반 소환 조건 판정.

6-T 가 선공 패로 실제 Duel 을 돌렸을 때 **효과 몬스터는 한 장도 소환되지
않았다.** 룰북이 효과 몬스터에 건 조건은 하나다.

    RULE-SUMMON-009 — "All Normal Monsters, and most Effect Monsters
    (**unless they have a specific restriction**), can be Summoned in this
    way."

그래서 묻는 것도 하나다 — **이 카드에 그 제약이 있는가.** 6-U 전까지
``assess_normal_summon`` 은 그 질문에 답할 데이터가 없다고 보고 효과 몬스터
전부를 ``UNDETERMINED`` 로 내보냈다. 이 파일이 재는 것은 네 가지다.

1. **"제약 없음"과 "정보 없음"이 갈리는가** (§6). 세 답이 서로 다르다 —
   스크립트를 읽고 신호가 없음 · 신호가 있음 · 스크립트가 없음.
2. **갈린 판정이 실제 Duel 을 바꾸는가.** 어니스트가 필드에 나오는가.
3. **바뀌지 않아야 하는 것이 그대로인가** — 통상 · 의식 · 토큰 · 엑스트라
   덱 · 레벨 5 이상 · 소환권 · 빈 칸.
4. **코퍼스 전수에서 거짓 허가가 나지 않는가.** 공식 카드 텍스트로 역검산
   한다 (문구로 **판정**하지 않는다 — 판정을 **검산**한다).

🔴 **일반 소환했다는 것과 그 효과가 발동했다는 것은 다른 사실이다**
(§19). 기르수가 필드에 나온 것으로 그 효과까지 해결됐다고 말하지 않는다.
"""

import re

import pytest

from core.card_model import NORMAL_SUMMON_RESTRICTION_CODES
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.summon_rules import (
    SUMMON_RESTRICTION_RULE,
    SummonEligibility,
    assess_normal_summon,
)
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

MINE, THEIRS = 0, 1

# ----------------------------------------------------------------------
# 실제 카드. **적어 둔 성질을 믿지 않는다** — 각 테스트가 공식 DB 에서
# 다시 확인한 뒤에 판정을 본다.
# ----------------------------------------------------------------------
HONEST = 37742478  # 어니스트 — 레벨 4 효과 몬스터, 제약 신호 없음
GIRSU = 69811710  # 잭나이츠 오르페골 기르수 — 레벨 4 효과 몬스터
KURIBOH = 40640057  # 크리보 — 레벨 1 효과 몬스터
FEATHERMAN = 21844576  # 엘리멘틀 히어로 페더맨 — 레벨 3 **통상** 몬스터
BLUE_EYES = 89631139  # 푸른 눈의 백룡 — 레벨 8 통상 (제물 2장)
BLACK_MAGICIAN = 342673  # 검은 마술사－블랙 매지션 — 레벨 7 **효과** 몬스터
TEN_THOUSAND_DRAGON = 10000  # 텐사우전드 드래곤 — ``TYPE_SPSUMMON``
GHOSTRICK_LANTERN = 54512827  # 고스트릭 랜턴 — ``EFFECT_CANNOT_SUMMON``
MASK_CHAMELEON = 53573406  # 가면레온 — ``EFFECT_CANNOT_SUMMON``
CETUS = 77435268  # 체츠커 — 공식 텍스트에 제약이 있으나 **스크립트가 없다**
RED_EYES_WYVERN = 67300516  # 붉은 눈의 비룡 — 제약이 **판 상태**에 걸린다
CHAOS_SOLDIER = 5405694  # 카오스 솔저 — 의식
ULTIMATE_DRAGON = 23995346  # 궁극의 푸른 눈의 백룡 — 융합 (엑스트라 덱)


# ======================================================================
# 도구
# ======================================================================


def view_of(repository, card_id: int) -> CardDefinitionView:
    card = repository.get(card_id)
    assert card is not None, f"카드 {card_id} 가 저장소에 없습니다"
    return CardDefinitionView.of(card)


def assess(repository, card_id: int):
    return assess_normal_summon(view_of(repository, card_id))


def board(repository, hand: list[int]) -> GameState:
    """패를 **지정해서** 만든다. 셔플로 뽑은 패가 아니다."""
    filler = [FEATHERMAN] * 10
    game = GameState.create(
        repository, decks=(list(hand) + filler, [FEATHERMAN] * 10)
    )
    game.draw(MINE, len(hand))
    game.draw(THEIRS, 1)
    game.turn.set_phase(Phase.MAIN1)
    return game


def in_hand(state: GameState, card_id: int, player: int = MINE) -> InstanceId:
    return next(
        card.instance_id
        for card in state.player(player).hand
        if card.card_id == card_id
    )


def verdict(state: GameState, action: PlayerAction):
    return ActionValidator(
        GameStateView.from_state(state, viewer=action.actor)
    ).validate(action)


def summon(state: GameState, card_id: int, player: int = MINE) -> PlayerAction:
    return PlayerAction.normal_summon(player, in_hand(state, card_id, player))


def monsters(state: GameState, player: int = MINE):
    return [c for c in state.player(player).monster_zone if c is not None]


def signals_of(repository, card_id: int):
    card = repository.get(card_id)
    return card.normal_summon_restriction_signals


# ======================================================================
# A. 세 답이 서로 다르다 (§6)
# ======================================================================


@pytest.mark.real_card
def test_a01_a_script_read_with_no_signal_is_not_the_same_as_no_script(
    repository,
):
    """
    🔴 **이 파일의 뼈대.** ``()`` 와 ``None`` 을 합치면 안 된다.

    - 어니스트: 스크립트를 끝까지 읽었고 네 상수가 **한 건도 없다** → ``()``
    - 체츠커: 이 저장소에 **스크립트 자체가 없다** → ``None``

    둘을 합치면 체츠커가 "제약 없음" 으로 둔갑한다. 그런데 체츠커의 공식
    텍스트는 「자신 필드에 몬스터가 존재할 경우, 이 카드는 일반 소환할 수
    없다」 라고 **직접** 말한다.
    """
    assert signals_of(repository, HONEST) == ()
    assert signals_of(repository, CETUS) is None

    #: 전제를 데이터로 확인한다 — 둘 다 레벨 4 효과 몬스터다.
    for card_id in (HONEST, CETUS):
        definition = view_of(repository, card_id)
        assert definition.is_monster
        assert definition.monster_level == 4
        assert "EFFECT" in definition.type_names
        assert "NORMAL" not in definition.type_names

    #: 체츠커의 공식 텍스트가 실제로 그렇게 말하는지 본다 (번역하지 않는다).
    assert re.search(
        r"(일반|통상)\s*소환할\s*수\s*없", repository.get(CETUS).desc or ""
    ), "전제가 바뀌었다 — 체츠커의 공식 텍스트에 제약 문구가 없습니다"


@pytest.mark.real_card
def test_a02_no_signal_opens_the_procedure(repository):
    """어니스트 · 기르수 · 크리보 — 룰북의 "most" 에 해당한다."""
    for card_id in (HONEST, GIRSU, KURIBOH):
        assessment = assess(repository, card_id)
        assert assessment.eligibility is SummonEligibility.ORDINARY, card_id
        assert assessment.permits_procedure is True
        assert assessment.is_refusal is False
        assert assessment.missing_rule is None
        assert assessment.tributes_required is None
        #: 이유에 **근거가 적혀 있다.** "그냥 효과 몬스터니까" 가 아니다.
        assert "RULE-SUMMON-009" in assessment.reason


@pytest.mark.real_card
def test_a03_a_missing_script_keeps_unknown(repository):
    """
    §6 상황 2 — **정보가 없는 것을 허가로 바꾸지 않는다.**

    체츠커는 규칙상 조건부로 일반 소환할 수 없는 카드다. 그 조건을 읽을
    데이터가 없으므로 ``UNDETERMINED`` 로 남는다. 이것이 맞는 답이다.
    """
    assessment = assess(repository, CETUS)

    assert assessment.eligibility is SummonEligibility.UNDETERMINED
    assert assessment.permits_procedure is False
    assert assessment.is_refusal is False, "모른다는 거절이 아니다"
    assert assessment.missing_rule == SUMMON_RESTRICTION_RULE
    assert "스크립트를 읽을 수 없어" in assessment.reason
    assert "제약이 없다는 뜻이 아닙니다" in assessment.reason


@pytest.mark.real_card
def test_a04_a_restriction_signal_keeps_unknown(repository):
    """
    신호를 찾았다 — 그런데 **누구에게 걸리는지 모른다.**

    고스트릭 랜턴의 ``EFFECT_CANNOT_SUMMON`` 은 자신에게 걸리지만
    (「자신 필드에 "고스트릭" 몬스터가 존재할 경우에만」), 같은 상수를
    **상대에게** 거는 카드도 있다. 이 계층은 그것을 구분하지 못하므로
    둘 다 "모른다" 로 남는다.
    """
    for card_id in (GHOSTRICK_LANTERN, MASK_CHAMELEON):
        signals = signals_of(repository, card_id)
        assert signals == ("EFFECT_CANNOT_SUMMON",), (card_id, signals)

        assessment = assess(repository, card_id)
        assert assessment.eligibility is SummonEligibility.UNDETERMINED
        assert assessment.permits_procedure is False
        assert assessment.is_refusal is False
        assert assessment.missing_rule == SUMMON_RESTRICTION_RULE
        assert "EFFECT_CANNOT_SUMMON" in assessment.reason


@pytest.mark.real_card
def test_a05_the_signal_list_is_what_the_module_says_it_is(repository):
    """
    상수 목록이 **코드에 한 곳**만 있다. 테스트가 제 목록을 따로 들지 않는다.
    """
    assert NORMAL_SUMMON_RESTRICTION_CODES == (
        "EFFECT_CANNOT_SUMMON",
        "EFFECT_CANNOT_SSET",
        "EFFECT_LIMIT_SUMMON_PROC",
        "EFFECT_SUMMON_PROC",
    )
    #: 신호는 **이 목록의 순서대로** 나온다 (출력이 안정적이어야 한다).
    card = repository.get(GHOSTRICK_LANTERN)
    signals = card.normal_summon_restriction_signals
    order = [NORMAL_SUMMON_RESTRICTION_CODES.index(s) for s in signals]
    assert order == sorted(order)


# ======================================================================
# B. 바뀌지 않아야 하는 것들
# ======================================================================


@pytest.mark.real_card
def test_b01_a_normal_monster_is_still_ordinary_without_any_script(repository):
    """
    통상 몬스터는 **종류 비트**로 판정한다 (룰북 "All Normal Monsters").
    스크립트가 없어도 그대로다 — 신호를 보기 **전에** 끝난다.
    """
    assert signals_of(repository, FEATHERMAN) is None

    assessment = assess(repository, FEATHERMAN)
    assert assessment.eligibility is SummonEligibility.ORDINARY
    assert "통상 몬스터" in assessment.reason


@pytest.mark.real_card
def test_b02_type_spsummon_is_still_forbidden(repository):
    """
    「일반 소환할 수 없다」 는 EDOPro 에서 **스크립트가 아니라 종류 비트**다.
    그래서 신호가 ``()`` 여도 ``FORBIDDEN`` 이어야 한다 — 신호를 보는 갈래에
    **도달하지 않는다**.
    """
    assert signals_of(repository, TEN_THOUSAND_DRAGON) == ()

    assessment = assess(repository, TEN_THOUSAND_DRAGON)
    assert assessment.eligibility is SummonEligibility.FORBIDDEN
    assert assessment.is_refusal is True
    assert assessment.permits_procedure is False
    assert "SPSUMMON" in assessment.reason


@pytest.mark.real_card
def test_b03_ritual_and_extra_deck_are_still_forbidden(repository):
    for card_id in (CHAOS_SOLDIER, ULTIMATE_DRAGON):
        assessment = assess(repository, card_id)
        assert assessment.eligibility is SummonEligibility.FORBIDDEN, card_id
        assert assessment.is_refusal is True


@pytest.mark.real_card
def test_b04_level_five_and_up_still_needs_tribute(repository):
    """
    레벨을 **신호보다 먼저** 본다. 뒤바뀌면 레벨 7 효과 몬스터가 제물 없이
    소환된다.
    """
    definition = view_of(repository, BLACK_MAGICIAN)
    assert definition.monster_level == 7
    assert "EFFECT" in definition.type_names
    assert signals_of(repository, BLACK_MAGICIAN) == ()

    assessment = assess(repository, BLACK_MAGICIAN)
    assert assessment.eligibility is SummonEligibility.NEEDS_TRIBUTE
    assert assessment.tributes_required == 2
    assert assessment.missing_rule == "tribute-summon (제물 선택 · 릴리스)"

    #: 통상 몬스터 쪽도 그대로다.
    blue = assess(repository, BLUE_EYES)
    assert blue.eligibility is SummonEligibility.NEEDS_TRIBUTE
    assert blue.tributes_required == 2


def test_b05_a_hand_built_definition_still_withholds():
    """
    🔴 **손으로 만든 관측은 조용히 허가를 얻지 않는다.**

    기본값이 ``None`` 이라서 "적지 않았다" 가 "읽지 않았다" 로 읽힌다.
    """
    definition = CardDefinitionView(
        card_id=1,
        name="손으로 만든 효과 몬스터",
        type_mask=0,
        attribute_mask=0,
        race_mask=0,
        link_marker_mask=0,
        level=4,
        atk=1000,
        defense=1000,
        pendulum_scale_left=None,
        pendulum_scale_right=None,
        is_monster=True,
        is_spell=False,
        is_trap=False,
        is_xyz=False,
        is_link=False,
        is_pendulum=False,
        is_extra_deck=False,
        monster_level=4,
        rank=None,
        link_rating=None,
        attribute_name="DARK",
        race_name="WARRIOR",
        type_names=("MONSTER", "EFFECT"),
        setcodes=(),
    )

    assert definition.normal_summon_restriction_signals is None
    assessment = assess_normal_summon(definition)
    assert assessment.eligibility is SummonEligibility.UNDETERMINED
    assert assessment.missing_rule == SUMMON_RESTRICTION_RULE


def test_b06_no_definition_is_still_undetermined():
    assessment = assess_normal_summon(None)
    assert assessment.eligibility is SummonEligibility.UNDETERMINED
    assert assessment.missing_rule is None, (
        "정의를 못 읽은 것은 소환 제약 규칙이 없는 것과 다른 사실이다"
    )


# ======================================================================
# C. 관측이 그 사실을 실어 보내는가
# ======================================================================


@pytest.mark.real_card
def test_c01_the_view_carries_the_signals_and_round_trips(repository):
    definition = view_of(repository, GHOSTRICK_LANTERN)

    assert definition.normal_summon_restriction_signals == (
        "EFFECT_CANNOT_SUMMON",
    )
    assert definition.to_dict()["normal_summon_restriction_signals"] == [
        "EFFECT_CANNOT_SUMMON"
    ]
    assert definition.normal_summon_restriction_signals in (
        definition.canonical_state()
    )


@pytest.mark.real_card
def test_c02_none_survives_to_dict_as_none_not_as_empty_list(repository):
    """
    🔴 ``None`` 을 ``[]`` 로 적으면 **직렬화에서 정보가 사라진다.**
    """
    definition = view_of(repository, CETUS)

    assert definition.normal_summon_restriction_signals is None
    assert definition.to_dict()["normal_summon_restriction_signals"] is None


@pytest.mark.real_card
def test_c03_two_cards_with_different_signals_differ_canonically(repository):
    """판정이 달라지는 두 카드는 ``canonical_state`` 도 달라야 한다."""
    clean = view_of(repository, HONEST)
    dirty = view_of(repository, GHOSTRICK_LANTERN)
    absent = view_of(repository, CETUS)

    states = {clean.canonical_state(), dirty.canonical_state(), absent.canonical_state()}
    assert len(states) == 3


@pytest.mark.real_card
def test_c04_the_view_does_not_carry_the_whole_script(repository):
    """
    실어 보내는 것은 **네 상수의 등장 여부**뿐이다. 스크립트의 다른
    ``EFFECT_*`` 상수가 관측에 섞여 나오지 않는다.

    🔴 시험할 카드를 **데이터에서 고른다.** 처음 이 시험은 고스트릭 랜턴을
    썼고 틀렸다 — 그 스크립트의 ``EFFECT_*`` 상수는 ``EFFECT_CANNOT_SUMMON``
    **하나뿐**이라, 다른 상수가 새는지를 아예 시험할 수 없었다.
    """
    watched = set(NORMAL_SUMMON_RESTRICTION_CODES)
    rich = [
        card
        for card in repository.all_cards()
        if card.normal_summon_restriction_signals
        and len(set(card.script.effect_codes) - watched) >= 2
    ]
    assert rich, "전제가 바뀌었다 — 신호와 다른 상수를 함께 가진 카드가 없다"

    for card in rich[:50]:
        others = set(card.script.effect_codes) - watched
        signals = CardDefinitionView.of(card).normal_summon_restriction_signals
        assert set(signals) <= watched, (card.id, signals)
        #: 다른 상수는 **한 건도** 실려 나오지 않는다.
        assert set(signals) & others == set(), (card.id, others)


# ======================================================================
# D. 검증기 — 같은 판정이 소환과 세트를 함께 연다
# ======================================================================


@pytest.mark.real_card
def test_d01_the_validator_now_permits_honest(repository):
    state = board(repository, [HONEST, GIRSU, FEATHERMAN])
    result = verdict(state, summon(state, HONEST))

    assert result.validity is ActionValidity.VALID
    assert result.code is ValidationCode.OK
    assert result.permits_execution is True
    assert result.missing_rule is None


@pytest.mark.real_card
def test_d02_the_validator_still_withholds_cetus(repository):
    state = board(repository, [CETUS, FEATHERMAN])
    result = verdict(state, summon(state, CETUS))

    assert result.validity is ActionValidity.UNKNOWN
    assert result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert result.missing_rule == SUMMON_RESTRICTION_RULE
    assert result.permits_execution is False


@pytest.mark.real_card
def test_d03_the_set_path_uses_the_same_assessment(repository):
    """
    세트도 ``_NormalSummonProcedure`` 를 쓴다
    (``engine/action_validation.py`` 의 ``_set_monster``). 그래서 어니스트는
    세트도 열리고, 체츠커는 세트도 막힌다 — **한 판정이 두 경로를 연다.**

    🔴 그래서 ``EFFECT_CANNOT_SSET`` 도 신호 목록에 든다. 세트를 막는 카드를
    이 판정이 통과시키면, 그 카드가 세트 경로로 새어 나간다.
    """
    state = board(repository, [HONEST, CETUS, FEATHERMAN])

    honest_set = PlayerAction.set_monster(MINE, in_hand(state, HONEST))
    assert verdict(state, honest_set).validity is ActionValidity.VALID

    cetus_set = PlayerAction.set_monster(MINE, in_hand(state, CETUS))
    cetus_result = verdict(state, cetus_set)
    assert cetus_result.validity is ActionValidity.UNKNOWN
    assert cetus_result.missing_rule == SUMMON_RESTRICTION_RULE


@pytest.mark.real_card
def test_d04_the_summon_right_still_closes_the_gate(repository):
    """소환권은 소환 절차와 **다른 조건**이다. 열린 절차가 권리를 만들지 않는다."""
    state = board(repository, [HONEST, GIRSU, FEATHERMAN])
    from engine.state.rule_usage import RuleActionKind

    state.rule_uses.record(state.turn.turn_number, MINE, RuleActionKind.NORMAL_SUMMON)
    result = verdict(state, summon(state, HONEST))

    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.NORMAL_SUMMON_ALREADY_USED


@pytest.mark.real_card
def test_d05_a_full_monster_zone_still_refuses(repository):
    state = board(repository, [HONEST, GIRSU, FEATHERMAN])
    #: 다섯 칸을 채운다 — 무엇으로 채웠는지는 중요하지 않다. **패는
    #: 건드리지 않는다** (소환하려던 카드가 사라지면 다른 것을 시험한다).
    for index in range(5):
        state.move(
            state.player(MINE).deck[0], Zone.MZONE, to_player=MINE,
            index=index, position=Position.FACEUP_ATTACK,
        )

    result = verdict(state, summon(state, HONEST))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.ZONE_FULL


@pytest.mark.real_card
def test_d06_the_wrong_phase_still_refuses(repository):
    state = board(repository, [HONEST, FEATHERMAN])
    state.turn.set_phase(Phase.DRAW)

    result = verdict(state, summon(state, HONEST))
    assert result.validity is ActionValidity.INVALID
    assert result.code is ValidationCode.WRONG_PHASE


# ======================================================================
# E. 실제 Duel — 후보에 오르고, 실행되고, 판이 바뀐다
# ======================================================================


def _main_phase_duel(repository, deck: list[int]):
    """
    선공 메인 페이즈 1 까지 **걸어서** 간다 — 페이즈를 손으로 써 넣지
    않는다. ``legal_actions`` 가 내놓는 ``END_PHASE`` 를 실제로 적용한다
    (``deck/opening.py`` 의 ``_walk_to_main1`` 과 같은 방식).
    """
    from engine.duel import Duel

    duel = Duel.start(repository=repository, decks=(deck, deck), seed=11)
    for _ in range(6):
        if duel.state.turn.phase is Phase.MAIN1:
            break
        duel.advance()
        ends = [
            a for a in duel.legal_actions(0).allowed
            if a.kind is PlayerActionKind.END_PHASE
        ]
        assert ends, f"{duel.state.turn.phase} 에서 페이즈를 넘길 수 없습니다"
        step = duel.apply(ends[0])
        assert step.accepted, step.reason
    assert duel.state.turn.phase is Phase.MAIN1, duel.state.turn.phase
    return duel


@pytest.mark.real_card
def test_e01_honest_becomes_a_candidate_and_reaches_the_field(repository):
    """
    **6-T 가 멈춘 자리다.** 후보 → 실행 → 판 변화를 한 번에 본다.
    """
    duel = _main_phase_duel(repository, [HONEST] * 40)
    seat = duel.turn_player

    allowed = duel.legal_actions(seat).allowed
    summons = [a for a in allowed if a.kind.value == "normal_summon"]
    assert summons, "어니스트가 일반 소환 후보에 오르지 않았습니다"

    before_hand = len(duel.state.player(seat).hand)
    assert monsters(duel.state, seat) == []
    assert duel.view(seat).normal_summons_used[seat] == 0

    step = duel.apply(summons[0])

    assert step.accepted is True
    assert step.code is ValidationCode.OK
    placed = monsters(duel.state, seat)
    assert len(placed) == 1
    assert placed[0].card_id == HONEST
    #: RULE-SUMMON-009 — 앞면 공격 표시로 나온다.
    assert placed[0].position is Position.FACEUP_ATTACK
    assert duel.view(seat).normal_summons_used[seat] == 1
    assert len(duel.state.player(seat).hand) == before_hand - 1


@pytest.mark.real_card
def test_e02_the_summon_does_not_activate_the_effect(repository):
    """
    🔴 **§19.** 기르수를 일반 소환했다는 것과 그 효과가 발동했다는 것은
    다른 사실이다. 소환 직후 체인은 **비어 있어야** 한다.
    """
    duel = _main_phase_duel(repository, [GIRSU] * 40)
    seat = duel.turn_player
    summons = [
        a for a in duel.legal_actions(seat).allowed
        if a.kind.value == "normal_summon"
    ]
    assert summons, "기르수가 일반 소환 후보에 오르지 않았습니다"

    step = duel.apply(summons[0])

    assert step.accepted is True
    assert monsters(duel.state, seat)[0].card_id == GIRSU
    assert len(duel.chain) == 0, "소환이 체인을 만들지 않는다 (RULE-CHAIN-011)"
    assert duel.state.pending == []


@pytest.mark.real_card
def test_e03_the_summon_right_is_spent_once(repository):
    """
    소환한 뒤에는 **소환도 세트도** 후보에서 사라진다 (RULE-SUMMON-009 —
    "one of these once per turn").
    """
    duel = _main_phase_duel(repository, [HONEST] * 40)
    seat = duel.turn_player
    summons = [
        a for a in duel.legal_actions(seat).allowed
        if a.kind.value == "normal_summon"
    ]
    duel.apply(summons[0])

    kinds = {a.kind.value for a in duel.legal_actions(seat).allowed}
    assert "normal_summon" not in kinds
    assert "set_monster" not in kinds


@pytest.mark.real_card
def test_e04_cetus_is_dropped_silently_in_a_real_duel(repository):
    """
    스크립트가 없는 카드는 실제 Duel 에서도 후보에 오르지 않는다.

    🔴 **그런데 보류 목록에도 적히지 않는다.** ``_withheld_board_actions``
    는 ``ACTIVATE_CARD`` 만 한 줄 남기고, 소환 · 세트 후보는 조용히
    빠진다 (실측). 이 Phase 가 그것을 고치지 않았으므로 **고쳐진 척하지
    않는다** — 측정한 대로 고정한다.
    """
    duel = _main_phase_duel(repository, [CETUS] * 40)
    seat = duel.turn_player
    legal = duel.legal_actions(seat)

    assert not [a for a in legal.allowed if a.kind.value == "normal_summon"]
    assert not [a for a in legal.allowed if a.kind.value == "set_monster"]

    held_kinds = {w.kind for w in legal.withheld}
    assert PlayerActionKind.NORMAL_SUMMON not in held_kinds, (
        "소환 보류가 보고되기 시작했다면 그것은 **개선**이다 — 이 테스트의"
        " 기대를 바꾸고 보고서에 적어야 한다"
    )

    #: 검증기에 직접 물으면 이유가 나온다 — 사라진 것은 **보고**뿐이다.
    result = verdict(duel.state, summon(duel.state, CETUS, seat))
    assert result.missing_rule == SUMMON_RESTRICTION_RULE


# ======================================================================
# F. 코퍼스 전수 — 거짓 허가가 나지 않는가
# ======================================================================

#: 공식 카드 텍스트가 **자기 자신의** 일반 소환 금지를 말하는 표현.
#:
#: 🔴 **이것으로 판정하지 않는다.** 상수 기반 판정을 **역검산**하는 데만
#: 쓴다. 문구로 판정하면 틀린다 — 같은 문구가 *다른 카드*의 성질을 가리키는
#: 경우(프린시퍼그 · 황금의 사교신)와 플레이어에게 걸리는 경우(붉은 눈의
#: 비룡)가 섞여 있다.
_FORBIDDING_PHRASES = (
    re.compile(r"(일반|통상)\s*소환[^。.\n]{0,12}수\s*없"),
    re.compile(r"[Cc]annot be Normal Summoned"),
)

#: 위 문구가 걸리지만 **자기 자신의 일반 소환 제약이 아닌** 카드들.
#: 전수 측정(Phase 6-U)이 찾아낸 전부다. 하나하나 사유가 있다.
_EXPLAINED_PHRASE_HITS = {
    11496832: "프린시퍼그 — 「자신 필드의 통상 소환할 수 없는 몬스터」. **다른 카드**를 가리킨다",
    78642798: "황금의 사교신 — 「자신 필드의 통상 소환할 수 없는 \"새크리파이스\" 몬스터」. 다른 카드다",
    67300516: "붉은 눈의 비룡 — 「이 카드의 효과를 발동하는 턴에, **자신은** 통상 소환할 수 없다」. 플레이어·턴에 걸리는 판 상태다",
    64892035: "늑장 오크 — 「일반 소환한 턴에는 **공격**할 수 없다」. 소환 제약이 아니다",
    80559548: "SR 셰이부메랑 — 늑장 오크와 같은 공격 제약이다",
}


def _clean_candidates(repository):
    """
    신호가 ``()`` 여서 ``ORDINARY`` 가 **된** 카드들.

    통상 몬스터는 들어오지 않는다 — 그쪽은 종류 비트로 먼저 끝난다.
    """
    out = []
    for card in repository.all_cards():
        if card.normal_summon_restriction_signals != ():
            continue
        if "NORMAL" in card.type_names:
            continue
        assessment = assess_normal_summon(CardDefinitionView.of(card))
        if assessment.eligibility is SummonEligibility.ORDINARY:
            out.append(card)
    return out


@pytest.mark.real_card
def test_f01_the_newly_permitted_cards_are_a_real_and_bounded_set(repository):
    """
    규모를 **재서** 적는다. 수가 움직이면 테스트가 알려준다.
    """
    clean = _clean_candidates(repository)
    assert len(clean) > 3000, f"너무 적다 ({len(clean)}) — 신호 추출이 깨졌나?"
    assert len(clean) < 5000, f"너무 많다 ({len(clean)}) — 종류 판정이 새나?"
    #: 전부 메인덱 · 레벨 4 이하 · 효과 몬스터다.
    for card in clean:
        assert card.is_monster and not card.is_extra_deck, card.id
        assert 1 <= (card.monster_level or 0) <= 4, card.id
        assert "NORMAL" not in card.type_names, card.id


@pytest.mark.real_card
def test_f02_no_newly_permitted_card_forbids_its_own_normal_summon(repository):
    """
    🔴 **거짓 허가 측정 (§9).** 새로 허가한 카드 전부의 **공식 텍스트**를
    훑어, 자기 자신의 일반 소환을 금지한다고 말하는 카드가 남아 있는지 본다.

    걸린 카드는 :data:`_EXPLAINED_PHRASE_HITS` 에 사유가 적힌 것뿐이어야
    한다. 새로운 카드가 걸리면 그것은 **실제 거짓 허가**이거나 설명이
    필요한 새 사례다 — 어느 쪽이든 조용히 지나가면 안 된다.
    """
    unexplained = []
    for card in _clean_candidates(repository):
        text = f"{card.desc or ''}\n{card.desc_en or ''}"
        if any(p.search(text) for p in _FORBIDDING_PHRASES):
            if card.id not in _EXPLAINED_PHRASE_HITS:
                unexplained.append((card.id, card.name_ko or card.name))
    assert unexplained == [], f"설명되지 않은 금지 문구: {unexplained}"


@pytest.mark.real_card
def test_f03_every_explained_hit_is_still_in_the_permitted_set(repository):
    """
    예외 목록이 **낡은 채로 남지 않게** 한다. 거기 적힌 카드가 더 이상
    허가되지 않는다면 그 줄은 지워야 한다.
    """
    permitted = {card.id for card in _clean_candidates(repository)}
    missing = sorted(set(_EXPLAINED_PHRASE_HITS) - permitted)
    assert missing == [], f"예외 목록이 낡았다 — 더 이상 허가되지 않는다: {missing}"


@pytest.mark.real_card
def test_f04_type_spsummon_is_what_actually_folds_the_cannot_be_summoned_cards(
    repository,
):
    """
    **왜 상수 목록에 "일반 소환 불가" 상수가 없는가.** EDOPro 는 그것을
    스크립트로 적지 않는다 — 종류 비트로 적는다. 그래서 코퍼스 전체에
    ``EFFECT_CANNOT_BE_NORMAL_SUMMONED`` 가 **0건**이다.
    """
    appearances = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        if "EFFECT_CANNOT_BE_NORMAL_SUMMONED" in card.script.effect_codes:
            appearances += 1
    assert appearances == 0, (
        "전제가 바뀌었다 — 스크립트가 일반 소환 금지를 직접 적기 시작했다면"
        " 그 상수를 NORMAL_SUMMON_RESTRICTION_CODES 에 더해야 한다"
    )

    #: 대신 종류 비트가 접는다.
    folded = [
        card
        for card in repository.all_cards()
        if card.is_monster
        and not card.is_extra_deck
        and "SPSUMMON" in card.type_names
    ]
    assert len(folded) > 300, f"TYPE_SPSUMMON 메인덱 몬스터가 {len(folded)}장뿐"
    for card in folded[:50]:
        assessment = assess_normal_summon(CardDefinitionView.of(card))
        assert assessment.eligibility is SummonEligibility.FORBIDDEN, card.id


@pytest.mark.real_card
def test_f05_cards_with_signals_all_stay_unknown(repository):
    """신호가 하나라도 있으면 **전부** 모른다로 남는다. 예외를 두지 않는다."""
    checked = 0
    for card in repository.all_cards():
        signals = card.normal_summon_restriction_signals
        if not signals:
            continue
        assessment = assess_normal_summon(CardDefinitionView.of(card))
        assert assessment.permits_procedure is False, (card.id, signals)
        checked += 1
    assert checked > 100, f"신호를 가진 카드가 {checked}장뿐 — 추출이 깨졌나?"


# ======================================================================
# G. 남은 한계 — 이 Phase 가 고치지 않은 것
# ======================================================================


@pytest.mark.real_card
def test_g01_a_board_imposed_summon_lock_is_still_unread(repository):
    """
    🔴 **BLOCKER 를 테스트로 적어 둔다.**

    「레프티레스 서번트」가 필드에 앞면 표시로 있으면 **서로** 몬스터를
    일반 소환할 수 없다. 그 제약은 카드 **정의**가 아니라 **판 상태**에
    있고, ``assess_normal_summon`` 은 판을 보지 않는다 (모듈 설명).

    그래서 ``ORDINARY`` 는 "**카드 자신에게** 제약이 없다" 는 뜻이고
    "지금 소환해도 된다" 는 뜻이 **아니다**. 이 테스트는 그 간격이 아직
    닫히지 않았음을 고정한다 — 닫혔다고 말하지 않기 위해서다.
    """
    lefty = 16008155  # 레프티레스 서번트
    card = repository.get(lefty)
    assert card is not None
    assert re.search(r"일반\s*소환할\s*수\s*없", card.desc or ""), (
        "전제가 바뀌었다 — 이 카드의 공식 텍스트에 제약 문구가 없습니다"
    )

    #: 상대 필드에 몬스터가 있어도 어니스트의 판정은 ORDINARY 그대로다 —
    #: 이 함수는 판을 입력으로 받지 **않는다**.
    state = board(repository, [HONEST, FEATHERMAN])
    state.move(
        state.player(THEIRS).deck[0], Zone.MZONE, to_player=THEIRS,
        index=0, position=Position.FACEUP_ATTACK,
    )
    assert monsters(state, THEIRS), "전제: 상대 필드에 몬스터를 놓았다"
    assert assess(repository, HONEST).permits_procedure is True

    #: 판정이 판을 보지 않는다는 사실 자체를 적는다.
    assert assess_normal_summon(view_of(repository, HONEST)).canonical_state() == (
        assess(repository, HONEST).canonical_state()
    )


@pytest.mark.real_card
def test_g02_an_alternative_summon_procedure_is_still_unread(repository):
    """
    ``EFFECT_SUMMON_PROC`` 은 **대체 일반 소환 절차**다 (「자신 필드의 레벨
    2 이하 몬스터 1장을 릴리스하고 일반 소환할 수 있다」 류). 그 절차를
    이 Phase 가 구현하지 않았으므로, 그 카드는 모른다로 남는다.
    """
    found = [
        card
        for card in repository.all_cards()
        if card.normal_summon_restriction_signals
        and "EFFECT_SUMMON_PROC" in card.normal_summon_restriction_signals
    ]
    assert found, "EFFECT_SUMMON_PROC 을 쓰는 카드가 사라졌다 — 전제가 바뀌었다"
    for card in found:
        assessment = assess_normal_summon(CardDefinitionView.of(card))
        assert assessment.permits_procedure is False, card.id
