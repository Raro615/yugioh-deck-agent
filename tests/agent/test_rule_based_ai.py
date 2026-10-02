"""
Phase 3-B — Rule-Based Duel AI.

    GameStateView + LegalActions
            ↓  Consideration 들
      Evaluation / Judgement
            ↓
        PlayerAction

이 파일이 지키는 것
-------------------
**규칙은 고르기만 한다.** 이 모듈에는 ``PlayerAction`` 을 만드는 자리가
없다 — 만들 수 있으면 허가받지 않은 수를 떠올릴 수 있고, 거절을 런너에게
미루게 된다. AST 로 못박는다.

**점수는 지어낸 숫자가 아니다.** 가중치 셋은 실제 카드 14,127 장에서 재서
정했고, 이 파일이 **다시 재서** 확인한다. 수비력이 공격력 한 칸을 뒤집지
못한다는 부등식도 여기서 지킨다.

**모르는 것을 숫자로 바꾸지 않는다.** 공격력이 ``?`` 인 몬스터에게
:class:`HigherAttackFirst` 는 0 점을 주지 않고 **판단을 포기한다.**

**탐색이 아니다.** 판을 복제하지 않고 ``apply`` 를 불러 보지 않는다
(Phase 3-B §2). 이것도 AST 로 못박는다.
"""

import ast
import collections
import pathlib
import re

import pytest

from agent import (
    FirstLegalPolicy,
    RandomPolicy,
    play,
    rule_based_policy,
)
from agent.heuristic import (
    ATK_WEIGHT,
    BOARD_PRESENCE,
    DEF_WEIGHT,
    DEFAULT_CONSIDERATIONS,
    MAX_PRINTED_ATK,
    MAX_PRINTED_DEFENSE,
    MIN_STAT_GAP,
    Appraisal,
    EndThePhaseAsLastResort,
    HeuristicError,
    HigherAttackFirst,
    HigherDefenceBreaksTheTie,
    RuleBasedPolicy,
    SummonBeforeEndingThePhase,
)
from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel, LegalActions
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

pytestmark = requires_official_db

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

# ----------------------------------------------------------------------
# 시험 덱 — **통상 몬스터만** 쓴다
#
# 효과 몬스터는 ``ActionValidator`` 가 ``UNKNOWN`` 을 돌려주므로 (아직
# ``summoning-condition`` 규칙이 없다) 후보에 오르지 않는다. 그래서 규칙이
# 실제로 발화하는 것을 보려면 공격력이 **서로 다른 통상 몬스터**가 필요하다.
# 아래 다섯 장의 능력치는 :func:`test_the_test_deck_is_what_we_think_it_is`
# 가 공식 DB 에서 다시 확인한다 — 적어 둔 숫자를 믿지 않는다.
# ----------------------------------------------------------------------
LUSTER_DRAGON = 11091375  # ATK 1900 / DEF 1600 / 레벨 4
BATTLE_OX = 5053103  # ATK 1700 / DEF 1000 / 레벨 4
KOJIKOCY = 1184620  # ATK 1500 / DEF 1200 / 레벨 4
THE_13TH_GRAVE = 32864  # ATK 1200 / DEF  900 / 레벨 3
WHITE_DUSTON = 3557275  # ATK    0 / DEF 1000 / 레벨 1
POT_OF_GREED = 55144522

#: 공격력이 ``?`` 인 실제 카드 둘. **둘 다 효과 몬스터다** — 실측 56 장이
#: 모두 그렇다. 그래서 듀얼에서는 후보에 오르지 않고, 규칙만 따로 시험한다.
KING_OF_THE_SKULL_SERVANTS = 36021814  # ATK ? / DEF 0
FORTUNE_LADY_LIGHT = 34471458  # ATK ? / DEF ?

TEST_DECK = (
    [LUSTER_DRAGON] * 3
    + [BATTLE_OX] * 3
    + [KOJIKOCY] * 3
    + [THE_13TH_GRAVE] * 3
    + [WHITE_DUSTON] * 3
    + [POT_OF_GREED] * 5
)

EXPECTED_STATS = {
    LUSTER_DRAGON: (1900, 1600, 4),
    BATTLE_OX: (1700, 1000, 4),
    KOJIKOCY: (1500, 1200, 4),
    THE_13TH_GRAVE: (1200, 900, 3),
    WHITE_DUSTON: (0, 1000, 1),
}


def duel_with(repository, *, seed: int = 7, deck=None) -> Duel:
    deck = TEST_DECK if deck is None else deck
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def field_attack(duel: Duel, seat: int) -> int:
    """그 자리의 몬스터 존 공격력 합. ``?`` 는 **더하지 않는다.**"""
    total = 0
    for card in duel.view(seat).me.monster_zone.occupied():
        definition = card.definition
        if definition is None:
            continue
        if definition.has_atk and not definition.atk_is_question:
            total += definition.atk
    return total


def main_phase(duel: Duel) -> None:
    """메인 페이즈 1 까지 턴을 넘긴다 — 후보가 생기는 유일한 자리다."""
    while duel.state.turn.phase is not Phase.MAIN1:
        if duel.advance() is not None:
            continue
        duel.apply(PlayerAction.end_phase(actor=duel.to_act))


# ======================================================================
# 0. 시험 덱이 우리가 생각하는 그 카드들인가
# ======================================================================


@pytest.mark.real_card
def test_the_test_deck_is_what_we_think_it_is(repository):
    """
    **적어 둔 능력치를 믿지 않는다.** 공식 DB 에서 다시 읽는다.

    이 시험이 깨지면 밑에 있는 모든 시험의 전제가 깨진 것이다 — 규칙이
    틀린 것이 아니라 덱이 다른 것이다.
    """
    for card_id, (atk, defense, level) in EXPECTED_STATS.items():
        card = repository.get(card_id)
        assert card is not None, card_id
        assert card.is_monster
        assert not card.is_extra_deck
        assert card.atk == atk, f"{card.name_en}: ATK {card.atk}"
        assert card.defense == defense, f"{card.name_en}: DEF {card.defense}"
        assert card.monster_level == level
        # 효과 몬스터면 ``UNKNOWN`` 때문에 후보에 오르지 않는다.
        assert not card.has_printed_effect, f"{card.name_en} 은 효과 몬스터다"
        assert not card.effects, f"{card.name_en} 에 효과가 붙었다"

    atks = {atk for atk, _, _ in EXPECTED_STATS.values()}
    assert len(atks) == len(EXPECTED_STATS), "공격력이 겹치면 순위를 시험할 수 없다"


@pytest.mark.real_card
def test_every_question_mark_monster_is_an_effect_monster(repository):
    """
    **이것이 ``ATK ?`` 를 듀얼에서 볼 수 없는 이유다.**

    공격력이 ``?`` 인 메인덱 몬스터는 하나도 빠짐없이 효과 몬스터이고,
    효과 몬스터는 ``ActionValidator`` 가 ``UNKNOWN`` 을 돌려주므로 후보에
    오르지 않는다 (``summoning-condition`` 규칙이 아직 없다).

    그래서 :class:`HigherAttackFirst` 의 포기 가지는 듀얼에서 발화하지
    않는다. **그렇다고 지우지 않는다** — 지우면 ``?`` 를 숫자로 읽는
    구조가 된다.
    """
    unknown_atk = [
        card
        for card in repository.all_cards()
        if card.is_monster and card.atk == -2 and not card.is_extra_deck
    ]
    assert unknown_atk, "공격력이 ? 인 몬스터가 없습니다 — 전제가 바뀌었다"
    plain = [card for card in unknown_atk if not card.has_printed_effect]
    assert plain == [], f"효과 없는 ATK ? 몬스터가 생겼다: {[c.name_en for c in plain]}"


# ======================================================================
# A. 경계 — 규칙은 고르기만 한다
# ======================================================================


def _heuristic_tree() -> ast.Module:
    return ast.parse((ROOT / "agent/heuristic.py").read_text())


def test_a_the_rules_never_build_an_action():
    """
    **이것이 이 단계의 핵심 경계다.** ``PlayerAction`` 을 만드는 자리가 없다.

    만들 수 있으면 규칙 기반 AI 가 "허가받지 않은 수" 를 떠올릴 수 있고,
    거절은 런너의 몫으로 미뤄진다. 떠올릴 수 없게 만드는 것이 낫다.
    """
    built = []
    for node in ast.walk(_heuristic_tree()):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "PlayerAction":
            built.append(ast.unparse(node))
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "PlayerAction"
        ):
            built.append(ast.unparse(node))
    assert built == [], f"규칙이 행위를 만들고 있습니다: {built}"


def test_a_the_rules_never_touch_the_board():
    """
    **판을 바꾸거나 복제하는 손잡이를 쓰지 않는다.**

    탐색이 아니라는 것을 이름으로 확인한다 (Phase 3-B §2) — 한 수도
    내다보지 않는다.
    """
    forbidden = {
        "project",
        "clone",
        "apply",
        "advance",
        "draw",
        "move",
        "set_result",
        "state_hash",
        "legal_actions",
    }
    used = {
        node.attr
        for node in ast.walk(_heuristic_tree())
        if isinstance(node, ast.Attribute) and node.attr in forbidden
    }
    assert used == set(), f"판을 만지는 손잡이를 씁니다: {sorted(used)}"


def test_a_the_rules_import_neither_the_duel_nor_a_random_source():
    """
    ``engine.duel`` 에서 가져오는 것은 :class:`LegalActions` 하나다.

    :class:`Duel` 을 가져오면 규칙이 판을 굴릴 수 있고, ``random`` 을
    가져오면 "규칙 기반" 이 아니다. 둘 다 막는다.
    """
    tree = _heuristic_tree()
    modules = set()
    from_duel = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            if node.module == "engine.duel":
                from_duel.update(alias.name for alias in node.names)

    assert from_duel == {"LegalActions"}, from_duel
    banned = {
        "random",
        "secrets",
        "copy",
        "torch",
        "numpy",
        "sklearn",
        "core.card_repository",
        "engine.state.game_state",
    }
    assert modules & banned == set(), f"들이면 안 되는 것을 들였습니다: {modules & banned}"


def test_a_a_consideration_only_ever_sees_a_view_and_one_action():
    """
    규칙 하나가 받는 것은 **관측과 후보 하나**뿐이다.

    후보 목록 전체를 주면 규칙이 "다른 후보를 보고" 점수를 낼 수 있고,
    그러면 점수의 뜻이 후보 구성에 따라 달라진다 — 같은 수가 어떤 때는
    좋고 어떤 때는 나쁜 것이 되어 설명할 수 없다.
    """
    for consideration in DEFAULT_CONSIDERATIONS:
        tree = ast.parse(
            (ROOT / "agent/heuristic.py").read_text()
        )
        break
    appraisals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "appraise"
    ]
    assert len(appraisals) == len(DEFAULT_CONSIDERATIONS) + 1, (
        "프로토콜 하나 + 규칙마다 하나여야 합니다"
    )
    for function in appraisals:
        names = [arg.arg for arg in function.args.args]
        assert names == ["self", "view", "action"], f"{function.name}: {names}"


# ======================================================================
# B. 점수는 지어낸 숫자가 아니다
# ======================================================================


@pytest.mark.real_card
def test_b_the_weights_are_measured_from_the_real_cards(repository):
    """
    **상수 셋을 실제 카드에서 다시 잰다.**

    ``MIN_STAT_GAP`` · ``MAX_PRINTED_ATK`` · ``MAX_PRINTED_DEFENSE`` 는
    지어낸 값이 아니라 실측이다. 카드가 늘어나 실측이 바뀌면 이 시험이
    먼저 깨져야 한다 — 가중치의 부등식이 조용히 무너지는 것보다 낫다.
    """
    monsters = [card for card in repository.all_cards() if card.is_monster]
    atks = sorted({card.atk for card in monsters if card.atk >= 0})
    defences = sorted({card.defense for card in monsters if card.defense >= 0})

    assert max(atks) <= MAX_PRINTED_ATK, max(atks)
    assert max(defences) <= MAX_PRINTED_DEFENSE, max(defences)

    gaps = [b - a for a, b in zip(atks, atks[1:])] + [
        b - a for a, b in zip(defences, defences[1:])
    ]
    assert min(gaps) >= MIN_STAT_GAP, f"능력치 간격이 더 좁아졌습니다: {min(gaps)}"


def test_b_defence_can_never_outrank_one_step_of_attack():
    """
    **수비력은 갈림용이다.** 공격력 한 칸을 뒤집으면 규칙의 순위가 뒤집힌다.
    """
    one_step_of_attack = MIN_STAT_GAP * ATK_WEIGHT
    most_defence_can_say = MAX_PRINTED_DEFENSE * DEF_WEIGHT
    assert most_defence_can_say < one_step_of_attack


def test_b_putting_something_on_the_board_outranks_every_stat():
    """
    **아무리 약한 몬스터라도 소환하는 것이 턴을 넘기는 것보다 앞선다.**

    쓰지 않은 소환권은 턴이 끝나면 사라지므로, 공격력 0 짜리라도 두는
    것이 아무것도 두지 않는 것보다 낫다.
    """
    most_the_stats_can_say = (
        MAX_PRINTED_ATK * ATK_WEIGHT + MAX_PRINTED_DEFENSE * DEF_WEIGHT
    )
    assert BOARD_PRESENCE > most_the_stats_can_say


def test_b_an_appraisal_without_a_reason_is_refused():
    """이유 없는 점수는 되짚을 수 없고, 되짚을 수 없는 판단은 고칠 수 없다."""
    with pytest.raises(HeuristicError):
        Appraisal(10, "")
    with pytest.raises(HeuristicError):
        Appraisal(10, "   ")
    with pytest.raises(HeuristicError):
        Appraisal(1.5, "소수점")  # type: ignore[arg-type]


# ======================================================================
# C. 모르는 것을 숫자로 바꾸지 않는다
# ======================================================================


@pytest.mark.real_card
def test_c_an_unknown_attack_makes_the_rule_abstain_not_score_zero(repository):
    """
    **공격력이 ``?`` 면 판단을 포기한다.** 0 점이 아니다.

    0 으로 읽으면 가장 약한 카드가 되고 큰 수로 읽으면 가장 강한 카드가
    된다 — 둘 다 거짓이다. ``UNKNOWN`` 을 허가로 바꾸지 않는 엔진의
    규칙과 같은 자리다.

    후보 목록은 **손으로 만든다.** 이 카드는 효과 몬스터라서 엔진이
    후보로 내놓지 않기 때문이다 (``summoning-condition`` 미구현). 카드와
    관측은 실제 그대로다.
    """
    deck = [KING_OF_THE_SKULL_SERVANTS] * 10 + [LUSTER_DRAGON] * 10
    duel = duel_with(repository, seed=3, deck=deck)
    main_phase(duel)
    view = duel.view(MINE)

    skull = [
        card
        for card in view.me.hand.occupied()
        if card.card_id == KING_OF_THE_SKULL_SERVANTS
    ]
    if not skull:
        pytest.skip("이 씨앗에서는 해당 카드가 패에 오지 않았습니다")
    definition = skull[0].definition
    assert definition.atk_is_question, "전제: 이 카드의 공격력은 ? 다"

    action = PlayerAction.normal_summon(actor=MINE, source=skull[0].instance_id)
    assert HigherAttackFirst().appraise(view, action) is None

    # 수비력은 ``?`` 가 아니므로 그쪽은 **판단한다** — 포기는 카드마다가
    # 아니라 **값마다**다.
    defence = HigherDefenceBreaksTheTie().appraise(view, action)
    assert defence is not None
    assert defence.score == definition.defense * DEF_WEIGHT


@pytest.mark.real_card
def test_c_the_judgement_records_which_rules_abstained(repository):
    """
    포기한 규칙이 **기록에 남는다.** 0 점과 섞이지 않는다.

    섞이면 "재어 보니 0" 과 "재지 못했다" 를 나중에 구분할 수 없고, 어느
    규칙이 모자란지도 알 수 없다.
    """
    deck = [FORTUNE_LADY_LIGHT] * 20
    duel = duel_with(repository, seed=11, deck=deck)
    main_phase(duel)
    view = duel.view(MINE)
    card = view.me.hand.occupied()[0]
    assert card.definition.atk_is_question
    assert card.definition.defense_is_question

    action = PlayerAction.normal_summon(actor=MINE, source=card.instance_id)
    policy = rule_based_policy()
    chosen = policy.decide(view, LegalActions(MINE, (action,)))

    assert chosen is action
    judgement = policy.last_judgement
    evaluation = judgement.of(action)
    assert "higher-attack-first" in evaluation.abstained
    assert "higher-defence-breaks-tie" in evaluation.abstained
    # 그래도 소환은 한다 — "얼마나 센지 모른다" 가 "두지 말라" 는 아니다.
    assert evaluation.total == BOARD_PRESENCE
    assert evaluation.judged


def test_c_abstaining_everywhere_is_said_out_loud():
    """
    어떤 규칙도 어떤 후보도 보지 못했으면 **아는 척하지 않는다.**

    고르기는 한다 — 고르지 않으면 듀얼이 멈춘다 — 그러나 기록에는
    "규칙이 모자랍니다" 가 남는다.
    """

    class SeesNothing:
        name = "sees-nothing"
        basis = "아무것도 보지 않는다 — 이 시험을 위한 규칙이다"

        def appraise(self, view, action):
            return None

    action = PlayerAction.end_phase(actor=MINE)
    policy = RuleBasedPolicy(considerations=(SeesNothing(),))
    chosen = policy.decide(None, LegalActions(MINE, (action,)))

    assert chosen is action
    judgement = policy.last_judgement
    assert judgement.nothing_was_judged
    assert "규칙이 모자랍니다" in judgement.reason


# ======================================================================
# D. 실제 카드로 판단한다
# ======================================================================


@pytest.mark.real_card
def test_d_the_stronger_monster_is_summoned_first(repository):
    """
    **공격력이 높은 쪽을 고른다.** 실제 카드, 실제 후보 목록에서.
    """
    duel = duel_with(repository, seed=7)
    policy = rule_based_policy()
    play(duel, (policy, FirstLegalPolicy()))

    checked = 0
    for judgement in policy.judgements:
        summons = [
            evaluation
            for evaluation in judgement.evaluations
            if evaluation.action.kind is PlayerActionKind.NORMAL_SUMMON
        ]
        if len(summons) < 2:
            continue
        checked += 1
        chosen = judgement.of(judgement.chosen)
        assert chosen.action.kind is PlayerActionKind.NORMAL_SUMMON
        assert chosen.total == max(evaluation.total for evaluation in summons)
    assert checked, "후보가 둘 이상인 소환 지점이 없었습니다 — 시험이 아무것도 보지 않았다"


@pytest.mark.real_card
def test_d_summoning_always_beats_ending_the_phase(repository):
    """
    소환할 수 있으면 **턴을 넘기지 않는다.** 소환권은 턴이 끝나면 사라진다.
    """
    duel = duel_with(repository, seed=5)
    policy = rule_based_policy()
    play(duel, (policy, FirstLegalPolicy()))

    seen = 0
    for judgement in policy.judgements:
        kinds = {evaluation.action.kind for evaluation in judgement.evaluations}
        if PlayerActionKind.NORMAL_SUMMON not in kinds:
            continue
        seen += 1
        assert judgement.chosen.kind is PlayerActionKind.NORMAL_SUMMON
    assert seen, "소환할 수 있는 지점이 없었습니다"


@pytest.mark.real_card
def test_d_every_declared_rule_actually_fires(repository):
    """
    **한 번도 발화하지 못하는 규칙은 두지 않는다.**

    시험할 수 없는 규칙은 규칙이 아니라 희망이다. 이 시험이 그것을
    드러낸다 — 규칙을 추가했는데 여기가 깨지면, 그 규칙은 지금의 엔진이
    내놓지 않는 후보를 기다리고 있는 것이다.
    """
    duel = duel_with(repository, seed=9)
    policy = rule_based_policy()
    play(duel, (policy, RandomPolicy(seed=4242)))

    fired = policy.firing_counts()
    assert set(fired) == {c.name for c in DEFAULT_CONSIDERATIONS}
    silent = [name for name, count in fired.items() if count == 0]
    assert silent == [], f"한 번도 발화하지 않은 규칙: {silent}"


def test_d_the_last_resort_rule_also_covers_passing():
    """
    ``PASS`` 도 **더 할 것이 없는 선택**이다.

    듀얼에서는 아직 나타나지 않는다 (실측: 우선권이 열리는 자리가 없다).
    그래서 후보 목록을 손으로 만들어 규칙만 확인한다 — 나타나지 않는
    것을 시험하지 않으면, 나타났을 때 조용히 틀린다.
    """
    rule = EndThePhaseAsLastResort()
    for kind, action in (
        (PlayerActionKind.END_PHASE, PlayerAction.end_phase(actor=MINE)),
        (PlayerActionKind.PASS, PlayerAction.passing(actor=MINE)),
    ):
        appraisal = rule.appraise(None, action)
        assert appraisal is not None, kind
        assert appraisal.score == 0

    # 소환은 이 규칙의 일이 아니다.
    summon = PlayerAction.normal_summon(actor=MINE, source=None)
    assert rule.appraise(None, summon) is None


@pytest.mark.real_card
def test_d_pass_never_shows_up_but_attack_now_does(repository):
    """
    **이 순간의 사실이다.** ``PASS`` 는 여전히 후보에 오르지 않는다.

    ``Duel._flow_actions`` 는 우선권이 열려 있을 때만 ``PASS`` 를 넣는데,
    지금도 우선권을 여는 규칙이 없다 (Phase 2-F 미구현).

    **``ATTACK`` 은 이제 오른다** (Phase 3-E-1-B). Phase 3-B 에서 이 시험은
    후보가 ``{NORMAL_SUMMON, END_PHASE}`` 둘뿐이라고 적었고 그때는 사실이었다
    — 전투 실행 계층이 없어서 검증기가 ``UNKNOWN`` 을 돌려주었다. 엔진이
    자란 것이므로 **규칙이 아니라 사실을 고친다.** ``PASS`` 에 대한 주장은
    글자 하나 바뀌지 않았다.

    **``SET_MONSTER`` · ``SET_SPELL_TRAP`` 도 이제 오른다** (Phase 3-E-2).
    같은 이유의 같은 손질이다 — 세트 실행 계층(``engine/set_card.py``)이
    생겨서 검증기가 ``UNKNOWN`` 대신 ``VALID`` 를 돌려준다. 이 시험이 지키는
    것은 "후보가 정확히 세 종류다" 가 아니라 **``PASS`` 가 없다**이고, 그
    주장은 여기서도 글자 하나 바뀌지 않았다.
    """
    duel = duel_with(repository, seed=13)
    policy = rule_based_policy()
    play(duel, (policy, FirstLegalPolicy()))

    kinds = collections.Counter(
        evaluation.action.kind
        for judgement in policy.judgements
        for evaluation in judgement.evaluations
    )
    assert PlayerActionKind.PASS not in kinds, dict(kinds)
    assert set(kinds) == {
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.END_PHASE,
        PlayerActionKind.ATTACK,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
    }, dict(kinds)


# ======================================================================
# E. 같은 상황이면 같은 수
# ======================================================================


@pytest.mark.real_card
def test_e_the_same_board_gives_the_same_move(repository):
    """난수가 없으므로 같은 관측과 같은 후보면 **언제나 같은 수**다."""
    duel = duel_with(repository, seed=7)
    main_phase(duel)
    view = duel.view(MINE)
    legal = duel.legal_actions(MINE)

    first = rule_based_policy().decide(view, legal)
    for _ in range(5):
        assert rule_based_policy().decide(view, legal) == first


@pytest.mark.real_card
def test_e_the_choice_does_not_depend_on_the_order_of_the_list(repository):
    """
    후보 목록의 **순서가 수를 바꾸지 않는다.**

    순서는 엔진이 패를 어떻게 훑는지에 달린 구현 세부다. 그것이 바뀌어서
    AI 의 수가 바뀌면 설명할 수 없다. 그래서 점수가 같을 때의 갈림도
    ``canonical_state`` 로 정한다.
    """
    duel = duel_with(repository, seed=7)
    main_phase(duel)
    view = duel.view(MINE)
    legal = duel.legal_actions(MINE)
    if len(legal.allowed) < 2:
        pytest.skip("후보가 하나뿐인 자리입니다")

    forward = rule_based_policy().decide(view, legal)
    backward = rule_based_policy().decide(
        view, LegalActions(MINE, tuple(reversed(legal.allowed)))
    )
    assert forward == backward


@pytest.mark.real_card
def test_e_two_copies_of_one_card_are_broken_deterministically(repository):
    """
    같은 카드 두 장은 점수가 **완전히 같다.** 그때도 흔들리지 않는다.
    """
    duel = duel_with(repository, seed=4, deck=[LUSTER_DRAGON] * 20)
    main_phase(duel)
    view = duel.view(MINE)
    legal = duel.legal_actions(MINE)
    summons = tuple(
        action
        for action in legal.allowed
        if action.kind is PlayerActionKind.NORMAL_SUMMON
    )
    assert len(summons) >= 2, "같은 카드가 둘 이상 패에 있어야 합니다"

    policy = rule_based_policy()
    chosen = policy.decide(view, LegalActions(MINE, summons))
    totals = {evaluation.total for evaluation in policy.last_judgement.evaluations}
    assert len(totals) == 1, "같은 카드인데 점수가 다릅니다"
    assert chosen.canonical_state() == min(
        action.canonical_state() for action in summons
    )


@pytest.mark.real_card
def test_e_a_whole_duel_runs_without_a_single_refusal(repository):
    """
    규칙 기반 정책으로 듀얼 한 판이 끝까지 간다. **거절이 0 건이다.**

    거절이 있으면 정책이 허가 없는 수를 떠올렸다는 뜻이고, 그것은
    §A 의 경계가 뚫린 것이다.
    """
    duel = duel_with(repository, seed=2)
    transcript = play(duel, (rule_based_policy(), rule_based_policy()))

    assert transcript.finished
    assert transcript.refusals == ()
    assert transcript.result is not None
    # 전투가 들어온 뒤로 듀얼이 **짧아졌다** — 덱아웃(196걸음)이 아니라 LP 0
    # 으로 끝나기 때문이다 (실측 46~126걸음). 지키려던 것은 "한 판이 끝까지
    # 간다" 이고 그 주장은 그대로다.
    assert transcript.steps > 30


# ======================================================================
# F. baseline — 무엇보다 나은가, 그리고 무엇은 아직 재지 못하는가
# ======================================================================

#: 대조 비교에 쓰는 씨앗들. **상대는 고정**하고 내 자리의 정책만 바꾼다 —
#: 그렇게 하지 않으면 양쪽의 패가 달라져서 정책을 비교한 것이 아니게 된다.
COMPARISON_SEEDS = tuple(range(1, 17))


def _field_attack_after(repository, policy_factory, seed: int) -> int:
    duel = duel_with(repository, seed=seed)
    play(duel, (policy_factory(), FirstLegalPolicy()))
    return field_attack(duel, MINE)


@pytest.mark.real_card
def test_f_the_rules_build_a_stronger_board_than_chance(repository):
    """
    **규칙 기반이 무작위보다 낫다** — 지금 잴 수 있는 척도에서.

    척도는 끝났을 때 **내 몬스터 존의 공격력 합**이다. 승률이 아니다
    (다음 시험이 그 이유를 적는다). 상대는 ``FirstLegalPolicy`` 로 고정
    하고 내 자리의 정책만 바꾸므로, 달라지는 것은 정책 하나뿐이다.
    """
    rules = sum(
        _field_attack_after(repository, rule_based_policy, seed)
        for seed in COMPARISON_SEEDS
    )
    chance = sum(
        _field_attack_after(
            repository, lambda s=seed: RandomPolicy(seed=s * 101 + 3), seed
        )
        for seed in COMPARISON_SEEDS
    )
    first = sum(
        _field_attack_after(repository, FirstLegalPolicy, seed)
        for seed in COMPARISON_SEEDS
    )

    assert rules > chance, (rules, chance)
    assert rules > first, (rules, first)


@pytest.mark.real_card
def test_f_the_winner_now_depends_on_the_policy(repository):
    """
    **STRUCTURAL-101 이 풀린 자리다.**

    Phase 3-B 에서 이 시험은 그 반대를 적었다 — "승패는 정책과 무관하다".
    그때는 사실이었다: ``ATTACK`` 이 후보에 오르지 않아 LP 가 8000 에서
    움직이지 않았고, 남은 패배 조건은 덱아웃 하나였으므로 승자는 누가 먼저
    뽑느냐로 정해졌다. 그 시험의 설명에 **"전투가 들어오면 이 시험이 깨진다
    — 그때는 깨지는 것이 옳다"** 고 적어 두었고, Phase 3-E-1-B 가 그
    전투다.

    그래서 주장을 **뒤집는다.** 약화가 아니라 반대 방향의 강화다.

    1. 모든 듀얼이 **LP 0** 으로 끝난다 (덱아웃이 아니다)
    2. LP 가 8000 에서 **움직인다**
    3. 같은 씨앗에서 **정책을 바꾸면 승자가 달라지는** 경우가 있다

    3번은 씨앗 4 에서 실측된다. 다른 씨앗에서 승자가 같은 것은 모순이 아니다
    — 정책이 결과를 **좌우할 수 있다**는 것과 **언제나 좌우한다**는 것은
    다른 주장이고, 여기서 말하는 것은 앞의 것이다.
    """
    winners_by_seed: dict[int, set] = {}
    for seed in (1, 4, 8):
        outcomes = set()
        for factory in (
            rule_based_policy,
            lambda: RandomPolicy(seed=77),
            FirstLegalPolicy,
        ):
            duel = duel_with(repository, seed=seed)
            transcript = play(duel, (factory(), FirstLegalPolicy()))
            outcomes.add(transcript.result.winner)

            assert "라이프 포인트가 0" in transcript.result.reason, seed
            life = (
                duel.state.player(MINE).life_points,
                duel.state.player(THEIRS).life_points,
            )
            assert 0 in life, f"seed={seed}: {life}"
            assert life != (8000, 8000)
        winners_by_seed[seed] = outcomes

    assert len(winners_by_seed[4]) == 2, (
        f"정책에 따라 승자가 갈리는 씨앗이 사라졌습니다: {winners_by_seed}"
    )


@pytest.mark.real_card
def test_f_greedy_is_not_the_best_play(repository):
    """
    **탐욕은 baseline 이지 정답이 아니다.**

    매번 가장 센 몬스터를 고르면 몬스터 존이 찰 때까지의 **순서**가 바뀌고,
    그래서 끝났을 때의 판이 무작위보다 나쁜 씨앗이 존재한다. 한 수도
    내다보지 않는 규칙으로는 이것을 고칠 수 없다 — 다음 단계가 탐색인
    이유가 이것이다.

    깨지면 규칙이 나아진 것이므로 **다시 읽어야 하는 시험**이다.
    """
    worse = [
        seed
        for seed in COMPARISON_SEEDS
        if _field_attack_after(repository, rule_based_policy, seed)
        < _field_attack_after(
            repository, lambda s=seed: RandomPolicy(seed=s * 101 + 3), seed
        )
    ]
    assert worse, "탐욕이 모든 씨앗에서 이겼습니다 — 척도나 규칙을 다시 읽어야 합니다"


# ======================================================================
# G. 잘못 조립한 정책은 만들어지지 않는다
# ======================================================================


def test_g_a_policy_without_rules_is_refused():
    with pytest.raises(HeuristicError, match="규칙 기반이 아닙니다"):
        RuleBasedPolicy(considerations=())


def test_g_a_rule_without_a_basis_is_refused():
    """
    **근거 없는 규칙은 두지 않는다.** 왜 그렇게 두는지 적지 못하면,
    나중에 그것이 틀렸는지도 판단할 수 없다.
    """

    class NoBasis:
        name = "no-basis"
        basis = "  "

        def appraise(self, view, action):
            return None

    with pytest.raises(HeuristicError, match="근거 없는 규칙"):
        RuleBasedPolicy(considerations=(NoBasis(),))


def test_g_two_rules_with_one_name_are_refused():
    """이름이 겹치면 발화 횟수를 셀 수 없고, 셀 수 없으면 죽은 규칙을 못 찾는다."""
    with pytest.raises(HeuristicError, match="겹칩니다"):
        RuleBasedPolicy(
            considerations=(SummonBeforeEndingThePhase(), SummonBeforeEndingThePhase())
        )


def test_g_something_that_is_not_a_rule_is_refused():
    class NotARule:
        name = "not-a-rule"
        basis = "appraise 가 없다"

    with pytest.raises(HeuristicError, match="규칙의 모양이 아닙니다"):
        RuleBasedPolicy(considerations=(NotARule(),))


def test_g_nothing_to_choose_is_recorded_not_guessed():
    """후보가 없으면 ``None`` 이고, 그것도 기록에 남는다."""
    policy = rule_based_policy()
    assert policy.decide(None, LegalActions(MINE, ())) is None
    assert policy.last_judgement.chosen is None
    assert policy.last_judgement.evaluations == ()
    assert not policy.last_judgement.nothing_was_judged


# ======================================================================
# H. Phase 3-B §2 — 넘어가지 않은 선
# ======================================================================

#: §2 가 "절대 다음 단계로 넘어가지 않는다" 로 적은 것들. 이름이 하나도
#: 없어야 한다. Phase 3-A 의 같은 시험이 ``agent/`` 전체를 읽으면서
#: ``evaluate`` 까지 금지했는데, 평가는 §1 이 요구한 일이므로 그 단어는
#: 여기서 빠진다 — 금지되는 것은 **탐색 · 시뮬레이션 · 학습**이다.
#:
#: 검사는 **식별자 단위**다. Phase 3-B 에서는 이것을 부분 문자열로 찾았는데,
#: 그러면 ``ppo`` 가 ``supported`` 안에서 걸린다 — 금지하려던 것은 이름이지
#: 글자 조각이 아니다 (Phase 3-C §16 에서 교정).
FORBIDDEN_IN_THE_AGENT_PACKAGE = (
    "torch",
    "tensorflow",
    "numpy",
    "sklearn",
    "minimax",
    "mcts",
    "montecarlo",
    "monte_carlo",
    "rollout",
    "playout",
    "reward",
    "backprop",
    "gradient",
    "neural",
    "selfplay",
    "self_play",
    "genetic",
    "dqn",
    "ppo",
    "train",
    "fit",
)


def _identifiers_without_prose(path: pathlib.Path) -> "set[str]":
    """
    **설명문과 주석을 떼어 낸 코드의 식별자 집합.**

    설명문에는 "MCTS 가 없다" 처럼 금지된 이름이 **없다고 적기 위해**
    나타난다. 그것까지 금지하면 왜 없는지를 적을 수 없게 된다.

    식별자 단위로 쪼개는 이유: 부분 문자열로 찾으면 ``ppo`` 가
    ``supported`` 안에서 걸린다. 금지하려던 것은 **이름**이다.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", ast.unparse(tree).lower()))


def test_h_the_agent_package_contains_no_search_and_no_learning():
    """
    **§2 의 목록을 이름으로 확인한다.**

    이 단계는 규칙만 쓴다. 탐색이나 학습이 들어오면 그것은 다음 단계이고,
    이 시험이 먼저 깨져서 알려야 한다.

    설명문은 읽지 않는다 — 금지된 이름은 "그것을 쓰지 않는다" 를 적는
    자리에 나타나기 때문이다. 보는 것은 **코드**다.
    """
    sources = {
        path.name: _identifiers_without_prose(path)
        for path in sorted((ROOT / "agent").glob("*.py"))
    }
    found = {
        (name, word)
        for name, identifiers in sources.items()
        for word in FORBIDDEN_IN_THE_AGENT_PACKAGE
        if word in identifiers
    }
    assert found == set(), f"§2 가 금지한 것이 들어왔습니다: {sorted(found)}"


def test_h_the_rule_layer_looks_exactly_one_move_ahead_of_nothing():
    """
    **한 수도 내다보지 않는다.**

    ``evaluate`` 는 후보 목록을 받아 점수만 매긴다 — 그 안에서 판을
    복제하거나 행위를 적용하는 자리가 없다는 것을 §A 가 AST 로 지킨다.
    여기서는 그 함수가 **판을 받지 않는다**는 것을 서명으로 확인한다.
    """
    tree = _heuristic_tree()
    evaluate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate"
    )
    assert [arg.arg for arg in evaluate.args.args] == ["self", "view", "legal"]
