"""
Phase 6-O — **룰북 한 줄을 그 줄이 덮는 카드 전체에 잇는다.**

    OperationRulingRegistry (손으로 적은 18장)   ← 가장 먼저
        ↓ 없으면
    rulebook_facts(관측된 카드 종류)             ← 룰북 한 줄
        ↓ 둘 다 없으면
    None = 모른다                               ← 메꾸지 않는다

이 파일이 지키는 것
-------------------
🔴 **규칙을 더한 것이 아니라 연결했다.** `NORMAL_MONSTER_RULE` 과
`normal_monster_facts` 는 **이미 있었다.** 그 줄이 덮는 카드가 저장소에
**684장**인데 손으로 적힌 것이 **1장**이었다 (§A).

🔴 **카드 ID 를 보지 않는다.** 보는 것은 관측이 실어 준 카드 **종류**뿐
이고, 그래서 카드별 예외가 아니다 (§E).

🔴 **모르는 것은 그대로 모른다.** 통상 **펜듈럼** 몬스터 · 효과 몬스터 ·
마법 · 함정 · 가려진 카드는 전부 ``None`` 이다 (§B).

🔴 **손으로 적은 것이 룰북 유도를 이긴다.** 더 좁은 근거가 더 넓은 근거를
이긴다 (§C).

🔴 **실행이 실제로 늘었다.** 같은 판에서 어니스트 ① 이 멈추던 것이
해결된다 — 그 전후를 실제 ``Duel`` 과 ``EventJournal`` 로 센다 (§F · §G).
"""

import ast
import pathlib

import pytest

import core.constants as C
from engine.action import PlayerActionKind
from engine.condition import ConditionResult
from engine.duel import Duel
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import (
    HONEST,
    OPERATION_RULINGS,
    definition_registry,
)
from engine.effect.resolution import ResolutionContext, ResolutionStatus
from engine.effect.ruling import (
    NORMAL_MONSTER_RULE,
    NOT_PLAIN_NORMAL,
    BoardRuling,
    CardRuleFacts,
    OperationRulingRegistry,
    RuleBasis,
    RuleFact,
    normal_monster_facts,
    rulebook_facts,
)
from engine.effect.semantics import FIELD_ZONES, RuleQuestion
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.spell_activation import duel_components
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

HONEST_REF = EffectRef(HONEST, 0)
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터이고 **손으로** 등록되어 있다.
FEATHERMAN = 21844576
#: 13번째 매장자 — 통상 몬스터이고 등록되어 **있지 않다.**
UNLISTED_NORMAL = 32864
#: 워터 스피릿 — 통상 · 튜너. 종류 이름이 둘이어도 통상 몬스터다.
UNLISTED_NORMAL_TUNER = 487395
#: 메탈포제 실버드 — 통상 **펜듈럼** 몬스터. 펜듈럼 효과가 있다.
NORMAL_PENDULUM = 7868571
#: 사이버 드래곤 — 효과 몬스터이고 등록되어 있지 않다.
UNLISTED_EFFECT = 70095154
#: 욕망의 항아리 — 마법. 손으로 등록되어 있다.
POT_OF_GREED = 55144522


# ======================================================================
# 판 만들기
# ======================================================================


def new_state(repository) -> GameState:
    return GameState.create(
        repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=1
    )


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def honest_with(repository, *bystanders, zone=Zone.MZONE, owner=THEIRS):
    """어니스트 ① 과 구경꾼 몇 장이 **앞면으로** 놓인 판."""
    state = new_state(repository)
    honest = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    for card_id in bystanders:
        state.create_instance(
            card_id, owner=owner, zone=zone, position=Position.FACEUP_ATTACK
        )
    return state, honest.instance_id


def verdict_and_result(state, honest_instance, rulings=OPERATION_RULINGS):
    """그 판의 이동 판정과 **실제 실행 결과**를 함께."""
    view = GameStateView.from_state(state, viewer=MINE)
    verdict = BoardRuling(view, rulings).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, honest_instance
    )
    definition = definition_registry().definition_for(HONEST_REF)
    journal = EventJournal()
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((HONEST_REF,)),
        rulings=rulings,
        journal=journal,
    )
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=HONEST_REF, controller=MINE, source=honest_instance
        ),
    )
    return verdict, result, journal


def definition_view(repository, card_id: int) -> CardDefinitionView:
    card = repository.get(card_id)
    assert card is not None, card_id
    return CardDefinitionView.of(card)


# ======================================================================
# A. 감사 — 등록소가 무엇을 덮고 무엇을 비워 두는가 (§4-A · §12)
# ======================================================================


def test_a01_the_registry_holds_twenty_one_hand_written_cards():
    """
    **§4-A 1 · 2** — 등록소는 **카드 ID → 확인된 사실**의 표이고, 지금
    **21장**이 손으로 적혀 있다.

    6-O 는 이 표에 줄을 더하지 않았다 (§14 "모든 OPERATION_RULINGS 데이터
    확장" 금지).

    🔴 **Phase 6-V 가 한 줄 더했다 (18 → 19): 기르수.** 등재된 카드는
    판에 깔리고, 모르는 카드가 하나라도 있으면 판 전체의 답이 ``UNKNOWN``
    이 된다 (``BoardRuling._interference``) — 어니스트가 6-K 에서 들어온
    것과 **같은 이유**다. 그 줄의 ``answers`` 는 비어 있다: 묻지 않은 것을
    참으로 채우지 않았다.

    🔴 **Phase 6-AC 가 두 줄 더했다 (19 → 21): 성유물－『성장』 · 오르페골
    갈라테아.** 갈라테아는 기르수와 **같은 이유**로 들어왔다 (링크 소환으로
    필드에 놓이고 그 뒤의 판 훑기에 걸린다, ``answers`` 는 비어 있다).
    『성장』 은 다르다 — 그 카드에는 **두 질문의 답이 적혀 있다**
    (``MAY_BE_SENT_TO_GRAVE`` · ``MAY_BE_SPECIAL_SUMMONED``). 둘 다 공식
    텍스트 전문을 읽은 것이고, 그래서 §14 의 "데이터 확장" 금지를 어긴
    것이 아니라 **이번 경로가 요구한 두 질문만** 읽었다.
    """
    assert len(OPERATION_RULINGS) == 21
    assert len(OPERATION_RULINGS.card_ids) == 21
    assert FEATHERMAN in OPERATION_RULINGS.card_ids
    assert HONEST in OPERATION_RULINGS.card_ids
    assert POT_OF_GREED in OPERATION_RULINGS.card_ids
    #: 🔴 이 셋은 **없다** — 그것이 §A 가 재는 공백이다.
    for absent in (UNLISTED_NORMAL, UNLISTED_NORMAL_TUNER, UNLISTED_EFFECT):
        assert OPERATION_RULINGS.facts_for(absent) is None, absent


@pytest.mark.real_card
def test_a02_the_rulebook_line_covers_684_cards_but_one_was_written(repository):
    """
    🔴 **§12-2 — 구현 전 측정을 그대로 남긴다.**

    룰북 한 줄(`NORMAL_MONSTER_RULE`)이 덮는 카드가 저장소에 **684장**인데
    손으로 적힌 것이 **1장**이었다. 그것이 "규칙 데이터는 존재하지만 실행
    경로와 연결되지 않음" (§5-C) 의 실측값이다.

    표본이 아니라 **전수**다 — ``CardRepository`` 의 14,127장을 다 센다.
    """
    cards = list(repository.all_cards())
    assert len(cards) == 14127, len(cards)

    def plain_normal(card) -> bool:
        if not (card.is_monster and card.type_mask & C.TYPE_NORMAL):
            return False
        if card.is_extra_deck or card.is_pendulum:
            return False
        return True

    plain = [card for card in cards if plain_normal(card)]
    #: 실측 (Phase 6-O). 숫자가 바뀌면 이 Phase 의 결론을 다시 봐야 한다.
    assert len(plain) == 684, len(plain)
    hand_written = [c for c in plain if c.id in OPERATION_RULINGS.card_ids]
    assert [c.id for c in hand_written] == [FEATHERMAN], hand_written

    #: 통상 몬스터 전체는 722장이고, 차이 38장이 **펜듈럼**이다.
    every_normal = [
        c for c in cards if c.is_monster and c.type_mask & C.TYPE_NORMAL
    ]
    assert len(every_normal) == 722, len(every_normal)
    pendulum = [c for c in every_normal if c.is_pendulum]
    assert len(pendulum) == 38, len(pendulum)
    #: 🔴 **엑스트라 덱 통상 몬스터는 0장이다** — 측정이고 가정이 아니다.
    assert [c for c in every_normal if c.is_extra_deck] == []


def test_a03_the_rule_and_its_derivation_already_existed():
    """
    🔴 **§15-9 · §3-4 — 6-O 가 더한 것은 규칙이 아니라 연결이다.**

    룰북 원문과 그 귀결은 **이미 적혀 있었다.** 6-O 는 그 둘을 건드리지
    않았다.
    """
    assert NORMAL_MONSTER_RULE == (
        "Yellow Normal Monster Cards do not have effects, and have a "
        "description of them written here that does not affect the game."
    )
    facts = normal_monster_facts(UNLISTED_NORMAL, "시험용")
    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.RULEBOOK
    assert set(facts.answers) == {
        RuleQuestion.MAY_BE_RETURNED_TO_HAND,
        RuleQuestion.MAY_BE_BANISHED,
        RuleQuestion.MAY_BE_RETURNED_TO_DECK,
        RuleQuestion.MAY_BE_SENT_TO_GRAVE,
        RuleQuestion.MAY_BE_DISCARDED,
    }
    #: 🔴 파괴와 특수 소환은 **여기 없다** — 룰북 한 줄로 나오지 않는다.
    for absent in (
        RuleQuestion.MAY_BE_TARGETED,
        RuleQuestion.OPERATION_POSSIBLE,
    ):
        assert absent not in facts.answers, absent
    for fact in facts.answers.values():
        assert fact.basis is RuleBasis.RULEBOOK
        assert NORMAL_MONSTER_RULE in fact.note


# ======================================================================
# B. 유도가 답하는 것과 **답하지 않는 것** (§9 · §18)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("card_id", [UNLISTED_NORMAL, UNLISTED_NORMAL_TUNER,
                                     FEATHERMAN])
def test_b01_a_plain_normal_monster_is_answered(repository, card_id):
    """통상 몬스터는 룰북 한 줄로 답이 나온다 — 종류 이름이 둘이어도."""
    facts = rulebook_facts(definition_view(repository, card_id))
    assert facts is not None
    assert facts.card_id == card_id
    assert facts.restricts_others is False
    assert facts.restriction_basis is RuleBasis.RULEBOOK
    assert len(facts.answers) == 5
    for fact in facts.answers.values():
        assert fact.answer is ConditionResult.TRUE
        assert fact.basis is RuleBasis.RULEBOOK


@pytest.mark.real_card
@pytest.mark.parametrize(
    "card_id, why",
    [
        (NORMAL_PENDULUM, "통상 펜듈럼 — 펜듈럼 효과가 있다"),
        (UNLISTED_EFFECT, "효과 몬스터 — 룰북 한 줄이 말하지 않는다"),
        (POT_OF_GREED, "마법 — 텍스트를 읽어야 한다"),
        (94192409, "함정 — 텍스트를 읽어야 한다"),
    ],
)
def test_b02_everything_else_stays_unknown(repository, card_id, why):
    """
    🔴 **§3-6 · §18 — 모르는 것은 그대로 모른다.**

    룰북 한 줄이 덮지 않는 카드에 답을 지어내지 않는다.
    """
    assert rulebook_facts(definition_view(repository, card_id)) is None, why


def test_b03_a_concealed_card_is_not_derived():
    """정의가 없으면 ``None`` — 가려진 카드의 종류를 짐작하지 않는다."""
    assert rulebook_facts(None) is None


def fabricated(
    *,
    card_id: int = 999999,
    is_monster: bool = True,
    is_extra_deck: bool = False,
    is_pendulum: bool = False,
    type_names: "tuple[str, ...]" = ("MONSTER", "NORMAL"),
) -> CardDefinitionView:
    """
    🔴 **지어낸 관측.** 저장소에 없는 조합을 재기 위한 것이다 (Phase 6-O).

    이것으로만 잴 수 있는 것이 있다 — 지금 데이터에 **0장**인 조합
    (엑스트라 덱 통상 몬스터 · 몬스터가 아닌 NORMAL)에서도 유도가 멈추는지.
    실제 카드로는 그 가지를 밟을 수 없으므로, 그 가지를 지키는 조건이
    조용히 지워져도 아무 시험이 깨지지 않는다 (mutation R4 · R6 이 그렇게
    살아남았다).
    """
    return CardDefinitionView(
        card_id=card_id,
        name="지어낸 카드",
        type_mask=0,
        attribute_mask=0,
        race_mask=0,
        link_marker_mask=0,
        level=4,
        atk=1000,
        defense=1000,
        pendulum_scale_left=None,
        pendulum_scale_right=None,
        is_monster=is_monster,
        is_spell=False,
        is_trap=False,
        is_xyz=False,
        is_link=False,
        is_pendulum=is_pendulum,
        is_extra_deck=is_extra_deck,
        monster_level=4,
        rank=None,
        link_rating=None,
        attribute_name=None,
        race_name=None,
        type_names=type_names,
        setcodes=(),
    )


def test_b06_a_non_monster_carrying_normal_is_refused():
    """
    🔴 **mutation R4 를 잡는다.**

    ``is_monster`` 를 보지 않게 바꿔도 실제 카드로는 아무 시험이 깨지지
    않았다 — 저장소에 ``NORMAL`` 을 가진 비몬스터가 **0장**이기 때문이다
    (``test_b08``). 그 가지를 **지어낸 관측**으로 직접 잰다.

    룰북의 그 줄은 "Yellow Normal **Monster** Cards" 라고 적는다. 몬스터가
    아니면 그 줄이 말하는 카드가 아니다.
    """
    assert rulebook_facts(fabricated()) is not None, "통상 몬스터는 답한다"
    #: 🔴 몬스터가 아니면 멈춘다.
    assert rulebook_facts(
        fabricated(is_monster=False, type_names=("SPELL", "NORMAL"))
    ) is None


def test_b07_a_fabricated_extra_deck_normal_is_refused():
    """
    🔴 **mutation R6 를 잡는다.**

    엑스트라 덱 통상 몬스터는 지금 저장소에 **0장**이다 (``test_a02``).
    그래서 그 조건을 지워도 실제 카드로는 드러나지 않는다. 지어낸 관측으로
    잰다 — 그 카드가 생기는 날 패 · 메인 덱으로 갈 수 있다는 답을 룰북 한
    줄에서 끌어내면 틀린다 (Phase 6-M §4-2).
    """
    assert rulebook_facts(fabricated(is_extra_deck=True)) is None
    #: 펜듈럼도 같은 자리에서 멈춘다 (실제 카드로도 센다 — ``test_b02``).
    assert rulebook_facts(
        fabricated(is_pendulum=True, type_names=("MONSTER", "NORMAL", "PENDULUM"))
    ) is None
    #: 카드 ID 가 양수가 아니면 멈춘다.
    assert rulebook_facts(fabricated(card_id=0)) is None


@pytest.mark.real_card
def test_b08_no_card_in_the_repository_is_a_non_monster_normal(repository):
    """
    🔴 ``test_b06`` 이 **지어낸 관측**을 쓰는 이유를 수치로 적는다.

    저장소 14,127장 중 ``NORMAL`` 을 가진 비몬스터가 **0장**이다. 그래서
    실제 카드로는 그 가지를 밟을 수 없다 — 그것이 mutation R4 가 살아남은
    이유이고, 테스트의 구멍이 아니라 **데이터의 사실**이다.
    """
    offenders = [
        card.id
        for card in repository.all_cards()
        if "NORMAL" in card.type_names and not card.is_monster
    ]
    assert offenders == [], offenders


def test_b04_the_pendulum_exclusion_cites_this_repositorys_own_model():
    """
    🔴 **§7 — 펜듈럼을 뺀 근거.**

    추측이 아니라 이 저장소가 **이미 적어 둔 사실**이다 —
    ``Card.has_printed_effect`` 가 "통상 펜듈럼 몬스터는 펜듈럼 효과가
    있으므로 예외" 라고 적는다.
    """
    assert NOT_PLAIN_NORMAL == frozenset({"PENDULUM", "TOKEN"})
    model = source_of("core/card_model.py")
    assert "통상 펜듈럼 몬스터는 펜듈럼 효과가 있으므로" in model


@pytest.mark.real_card
def test_b05_a_normal_pendulum_really_has_a_pendulum_effect(repository):
    """
    그 제외가 **실제 카드에서도** 맞는지 센다 — 공식 텍스트를 읽는다.
    """
    card = repository.get(NORMAL_PENDULUM)
    assert card is not None
    assert card.is_pendulum and (card.type_mask & C.TYPE_NORMAL)
    #: 🔴 몬스터로는 통상인데 **효과가 있다고 이 저장소가 말한다.**
    assert card.has_printed_effect is True
    plain = repository.get(UNLISTED_NORMAL)
    assert plain.has_printed_effect is False


# ======================================================================
# C. 손으로 적은 것이 앞선다 (§3-9 · §8)
# ======================================================================


@pytest.mark.real_card
def test_c01_hand_written_facts_beat_the_derivation(repository):
    """
    🔴 **더 좁은 근거가 더 넓은 근거를 이긴다.**

    통상 몬스터 하나를 손으로 **거짓**이라고 적어 두면 룰북 유도가
    그것을 덮지 않는다. 순서가 뒤바뀌면 사람이 공식 재정을 읽고 적은 것이
    사라진다.
    """
    state = new_state(repository)
    target = state.create_instance(
        UNLISTED_NORMAL, owner=MINE, zone=Zone.MZONE,
        position=Position.FACEUP_ATTACK,
    )
    view = GameStateView.from_state(state, viewer=MINE)

    hand_written = OperationRulingRegistry((
        CardRuleFacts(
            card_id=UNLISTED_NORMAL,
            answers={
                RuleQuestion.MAY_BE_RETURNED_TO_HAND: RuleFact(
                    ConditionResult.FALSE,
                    RuleBasis.OFFICIAL_RULING,
                    "시험용: 사람이 읽고 적은 것이 룰북 유도를 이겨야 한다",
                )
            },
            restricts_others=False,
            restriction_basis=RuleBasis.OFFICIAL_RULING,
            restriction_note="시험용",
        ),
    ))
    declared = BoardRuling(view, hand_written).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target.instance_id
    )
    derived = BoardRuling(view, OPERATION_RULINGS).explain(
        RuleQuestion.MAY_BE_RETURNED_TO_HAND, target.instance_id
    )
    assert declared.answer is ConditionResult.FALSE, declared.reason
    assert "시험용" in declared.reason
    #: 같은 판에서 등록소가 비어 있으면 룰북 유도가 답한다.
    assert derived.answer is ConditionResult.TRUE, derived.reason


def test_c02_the_lookup_happens_in_exactly_one_place():
    """
    AST — 사실을 찾는 자리가 **하나**다 (``_facts_of``).

    둘이면 한쪽만 고치는 날이 오고, 그날 두 자리가 다른 답을 낸다 (6-N 이
    같은 함정을 밟았다).
    """
    tree = ast.parse(source_of("engine/effect/ruling.py"))
    board = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "BoardRuling"
    )
    body = ast.unparse(board)
    #: 등록소를 직접 묻는 자리는 ``_facts_of`` 안에만 있다.
    assert body.count("self._registry.facts_for(") == 1, body.count(
        "self._registry.facts_for("
    )
    assert body.count("self._facts_of(") == 2  # explain · _interference
    #: 룰북 유도를 부르는 자리도 하나다.
    assert body.count("rulebook_facts(") == 1


def test_c03_the_derivation_reads_no_card_id():
    """🔴 **§3-10 · §10-I** — 카드 ID 로 분기하지 않는다 (AST)."""
    tree = ast.parse(source_of("engine/effect/ruling.py"))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "rulebook_facts"
    )
    body = ast.unparse(fn)
    #: 보는 것은 **종류**뿐이다.
    for expected in ("is_monster", "type_names", "is_extra_deck"):
        assert expected in body, expected
    #: 카드 ID 와 비교하는 자리가 없다 — 넘겨 주기만 한다.
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and "card_id" in ast.unparse(node):
            #: 유일하게 허용되는 비교는 "양수인가" 다.
            assert "<= 0" in ast.unparse(node), ast.unparse(node)


# ======================================================================
# D. 🔴 실제 실행 — 전후 (§10-I · §12)
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize(
    "bystander", [UNLISTED_NORMAL, UNLISTED_NORMAL_TUNER]
)
def test_d01_a_normal_monster_no_longer_blocks_resolution(
    repository, bystander
):
    """
    🔴 **§17 수준 3 — 실행이 실제로 늘었다.**

    구현 전: 상대 필드에 **앞면 통상 몬스터**가 있으면 어니스트 ① 이
    ``UNKNOWN`` → ``UNCHECKED_RULES`` 로 멈췄고 카드가 ``MZONE`` 에
    남았다 (실측, 표본 5장 전부).

    지금은 ``TRUE`` → ``RESOLVED`` 이고 카드가 ``HAND`` 로 간다.
    """
    state, honest = honest_with(repository, bystander)
    verdict, result, journal = verdict_and_result(state, honest)

    assert verdict.answer is ConditionResult.TRUE, verdict.reason
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert state.find_instance(honest).zone is Zone.HAND
    #: 🔴 기록도 실제 변경과 일치한다 (§12-8).
    assert len(journal.events) == 1
    delta = journal.events[0].deltas[0]
    assert delta.instance == honest
    assert delta.source_zone is Zone.MZONE
    assert delta.destination_zone is Zone.HAND
    #: 구경꾼은 움직이지 않았다.
    others = [
        c for c in state.player(THEIRS).zones[Zone.MZONE]
        if c.card_id == bystander
    ]
    assert len(others) == 1


@pytest.mark.real_card
@pytest.mark.parametrize(
    "bystander, why",
    [
        (UNLISTED_EFFECT, "효과 몬스터 — 막는지 알 수 없다"),
        (NORMAL_PENDULUM, "통상 펜듈럼 — 펜듈럼 효과가 있다"),
    ],
)
def test_d02_everything_else_still_blocks(repository, bystander, why):
    """
    🔴 **§10-B — 규칙 범위를 지나치게 확대하지 않았다.**

    비슷해 보이지만 룰북 한 줄이 덮지 않는 카드는 **여전히 막는다.** 판도
    기록도 그대로다.
    """
    state, honest = honest_with(repository, bystander)
    before = state.state_hash()
    verdict, result, journal = verdict_and_result(state, honest)

    assert verdict.answer is ConditionResult.UNKNOWN, (why, verdict.reason)
    assert str(bystander) in verdict.reason
    assert result.status is ResolutionStatus.UNCHECKED_RULES, why
    assert state.find_instance(honest).zone is Zone.MZONE
    assert result.deltas == ()
    assert journal.events == ()
    assert state.state_hash() == before


@pytest.mark.real_card
def test_d03_one_unlisted_card_among_many_still_blocks(repository):
    """
    🔴 **하나라도 모르면 멈춘다.** 통상 몬스터 셋과 효과 몬스터 하나를
    함께 두면 답은 ``UNKNOWN`` 이다 — "아무도 안 막는다" 는 판 전체를
    읽었을 때만 할 수 있는 말이다.
    """
    state, honest = honest_with(
        repository,
        UNLISTED_NORMAL,
        UNLISTED_NORMAL_TUNER,
        FEATHERMAN,
        UNLISTED_EFFECT,
    )
    verdict, result, _ = verdict_and_result(state, honest)
    assert verdict.answer is ConditionResult.UNKNOWN
    assert str(UNLISTED_EFFECT) in verdict.reason
    assert result.status is ResolutionStatus.UNCHECKED_RULES


@pytest.mark.real_card
@pytest.mark.parametrize("zone", sorted(FIELD_ZONES, key=str))
def test_d04_the_derivation_applies_wherever_the_sweep_looks(repository, zone):
    """
    훑는 자리 **전부**에서 같은 답이 나온다 — 자리마다 다른 규칙이
    생기지 않는다.
    """
    state, honest = honest_with(repository, UNLISTED_NORMAL, zone=zone)
    verdict, result, _ = verdict_and_result(state, honest)
    assert verdict.answer is ConditionResult.TRUE, (zone, verdict.reason)
    assert result.status is ResolutionStatus.RESOLVED, zone


@pytest.mark.real_card
def test_d05_a_normal_monster_in_the_graveyard_is_also_answered(repository):
    """
    🔴 **6-N 이 연 자리와 맞물린다.** 6-N 이 묘지를 훑게 만들었고 (자리를
    먼저 본다), 6-O 가 거기서 만나는 통상 몬스터에 답을 준다.
    """
    state, honest = honest_with(repository, UNLISTED_NORMAL, zone=Zone.GRAVE)
    verdict, result, _ = verdict_and_result(state, honest)
    assert verdict.answer is ConditionResult.TRUE, verdict.reason
    assert result.status is ResolutionStatus.RESOLVED

    #: 대조 — 묘지의 효과 몬스터는 여전히 막는다.
    other, honest2 = honest_with(repository, UNLISTED_EFFECT, zone=Zone.GRAVE)
    verdict2, result2, _ = verdict_and_result(other, honest2)
    assert verdict2.answer is ConditionResult.UNKNOWN
    assert result2.status is ResolutionStatus.UNCHECKED_RULES


# ======================================================================
# E. 실제 Duel 수직 통합 (§8 · §10-I)
# ======================================================================


@pytest.mark.real_card
def test_e01_the_whole_duel_path_runs_with_a_normal_monster_present(
    repository,
):
    """
    🔴 **§17 수준 3** — 실제 ``Duel`` 이 끝까지 간다.

        legal_actions → apply → 체인 1 → 응답 창 → 해결
          → GameState 변경 → EventJournal

    구경꾼이 **상대의 앞면 통상 몬스터**다. 6-O 전에는 이 판에서 해결이
    멈췄다.
    """
    journal = EventJournal()
    state = new_state(repository)
    placed = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.create_instance(
        UNLISTED_NORMAL, owner=THEIRS, zone=Zone.MZONE,
        position=Position.FACEUP_ATTACK,
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    candidates = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(candidates) == 1
    assert candidates[0].effect_ref == HONEST_REF

    before_hand = len(duel.state.player(MINE).hand)
    step = duel.apply(candidates[0])
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    #: 발동만으로는 움직이지 않는다.
    assert duel.state.find_instance(placed.instance_id).zone is Zone.MZONE

    settled = settle_chain(duel)
    assert settled is not None and settled.accepted
    #: 🔴 **해결됐다.**
    assert duel.state.find_instance(placed.instance_id).zone is Zone.HAND
    assert len(duel.state.player(MINE).hand) == before_hand + 1

    events = [e for e in journal.events if e.effect_ref == HONEST_REF]
    assert len(events) == 1
    assert events[0].deltas[0].destination_zone is Zone.HAND


@pytest.mark.real_card
def test_e02_the_duel_still_stops_on_an_effect_monster(repository):
    """
    **§10-D** — 같은 경로에서 효과 몬스터가 있으면 **발동은 되고 해결이
    멈춘다.** 판은 그대로다.
    """
    journal = EventJournal()
    state = new_state(repository)
    placed = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.create_instance(
        UNLISTED_EFFECT, owner=THEIRS, zone=Zone.MZONE,
        position=Position.FACEUP_ATTACK,
    )
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
        **duel_components(journal=journal),
    )
    candidates = [
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(candidates) == 1
    duel.apply(candidates[0])
    settle_chain(duel)

    #: 🔴 카드가 움직이지 않았고 기록도 없다.
    assert duel.state.find_instance(placed.instance_id).zone is Zone.MZONE
    assert [e for e in journal.events if e.effect_ref == HONEST_REF] == []


# ======================================================================
# F. 기존 회귀 (§10-F · §10-G · §10-H)
# ======================================================================


@pytest.mark.real_card
def test_f01_honest_alone_still_resolves(repository):
    """**§10-H** — Phase 6-L 의 경로가 그대로다 (구경꾼 없는 판)."""
    state, honest = honest_with(repository)
    verdict, result, journal = verdict_and_result(state, honest)
    assert verdict.answer is ConditionResult.TRUE
    assert result.status is ResolutionStatus.RESOLVED
    assert state.find_instance(honest).zone is Zone.HAND
    assert len(journal.events) == 1


@pytest.mark.real_card
def test_f02_the_phase_6m_origin_rule_still_holds(repository):
    """**§10-F** — 어니스트 ① 이 필드 밖에서는 여전히 거절된다."""
    from engine.validation import ValidationCode

    definition = definition_registry().definition_for(HONEST_REF)
    assert definition.operations[0].origin_zones == FIELD_ZONES
    for zone in (Zone.GRAVE, Zone.DECK, Zone.HAND):
        state = new_state(repository)
        instance = state.create_instance(
            HONEST, owner=MINE, zone=zone, position=Position.FACEUP_ATTACK
        )
        journal = EventJournal()
        executor = EffectExecutor(
            lookup=EffectImplementationRegistry((HONEST_REF,)),
            rulings=OPERATION_RULINGS,
            journal=journal,
        )
        result = executor.execute(
            state,
            definition,
            ResolutionContext(
                effect_ref=HONEST_REF, controller=MINE,
                source=instance.instance_id,
            ),
        )
        assert result.status is ResolutionStatus.INVALID_TARGET, zone
        assert result.code is ValidationCode.SOURCE_WRONG_ZONE, zone
        assert journal.events == ()


@pytest.mark.real_card
def test_f03_the_phase_6n_face_rule_still_holds(repository):
    """
    **§10-G** — 필드의 **세트** 카드는 여전히 건너뛴다. 6-O 가 그 구분을
    바꾸지 않았다.
    """
    state = new_state(repository)
    honest = state.create_instance(
        HONEST, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    state.create_instance(
        UNLISTED_EFFECT, owner=THEIRS, zone=Zone.MZONE,
        position=Position.FACEDOWN_DEFENSE,
    )
    verdict, result, _ = verdict_and_result(state, honest.instance_id)
    #: 뒷면이므로 효과를 적용하지 않는다 → 막지 않는다.
    assert verdict.answer is ConditionResult.TRUE, verdict.reason
    assert result.status is ResolutionStatus.RESOLVED


@pytest.mark.real_card
def test_f04_the_existing_activate_effects_are_unchanged(repository):
    """**§13-3** — 기존 ``ACTIVATE`` 효과의 실행이 그대로다."""
    from engine.effect.library import EFFECT_LIBRARY
    from engine.effect.operation import OperationKind

    #: 🔴 17 → 18 · 14 → 15 (Phase 6-V). 아래가 재는 것은 **욕망의 항아리의
    #: 실행이 그대로인가** 이고, 그 사실은 변하지 않았다.
    #: Phase 6-AC 가 성유물－『성장』 ① 을 더했다 (18 → 19).
    assert len(EFFECT_LIBRARY) == 19
    #: Phase 6-AC — 성유물－『성장』 ① 이 실행 가능으로 더해졌다 (15 → 16).
    assert sum(1 for e in EFFECT_LIBRARY if e.executable) == 16

    definition = definition_registry().definition_for(
        EffectRef(POT_OF_GREED, 0)
    )
    state = new_state(repository)
    source = state.create_instance(
        POT_OF_GREED, owner=MINE, zone=Zone.SZONE, position=Position.FACEUP
    )
    executor = EffectExecutor(
        lookup=EffectImplementationRegistry((definition.effect_ref,)),
        rulings=OPERATION_RULINGS,
    )
    before = len(state.player(MINE).hand)
    result = executor.execute(
        state,
        definition,
        ResolutionContext(
            effect_ref=definition.effect_ref, controller=MINE,
            source=source.instance_id,
        ),
    )
    assert result.status is ResolutionStatus.RESOLVED, result.reason
    assert [o.kind for o in definition.operations] == [OperationKind.DRAW]
    assert len(state.player(MINE).hand) == before + 2


# ======================================================================
# G. 금지 사항 — 범위를 넘지 않았다 (§3 · §14)
# ======================================================================


def test_g01_no_new_rule_engine_and_no_new_result_type():
    """**§3-4 · §14** — 새 판정 체계를 만들지 않았다."""
    assert [b.value for b in RuleBasis] == [
        "rulebook", "card_text", "official_ruling"
    ]
    assert [r.name for r in ConditionResult] == ["TRUE", "FALSE", "UNKNOWN"]
    #: 🔴 **판정 체계는 그대로이고 질문이 하나 늘었다** (Phase 6-AC).
    #:
    #: 이 단언이 지키는 것은 "새 판정 체계를 만들지 않았다" 이고, 그것은
    #: 위의 두 줄(근거의 종류 · 결과의 세 값)이 잰다. 질문 목록은 **그
    #: 체계 안에서** 늘어나는 것이므로 늘어난 사실을 적는다 —
    #: ``MAY_BE_SPECIAL_SUMMONED`` 가 그것이고, 같은 ``RuleFact`` ·
    #: 같은 ``RuleBasis`` · 같은 세 값을 쓴다.
    assert len(list(RuleQuestion)) == 8
    assert RuleQuestion.MAY_BE_SPECIAL_SUMMONED.value == "may_be_special_summoned"


def test_g02_the_registry_data_was_not_expanded():
    """
    🔴 **§14 — "모든 OPERATION_RULINGS 데이터 확장" 을 하지 않았다.**

    6-O 가 손으로 적은 줄을 늘리지 않았다는 사실은 그대로다 — 그때
    18장이었고 늘어난 것은 **유도**였다.

    🔴 **Phase 6-V 가 한 줄 더했다 (19).** 6-O 의 금지를 어긴 것이 아니라
    6-V 가 새 카드를 등재했기 때문이고, 아래 단언이 지키는 "유도는
    ``ruling.py`` 에 있고 ``library.py`` 는 그것을 쓰지 않는다" 는 그대로다.
    """
    library = source_of("engine/effect/library.py")
    #: Phase 6-AC 가 둘을 더했다 — 성유물－『성장』 · 오르페골 갈라테아 (19 → 21).
    assert len(OPERATION_RULINGS) == 21
    #: 라이브러리 쪽은 6-O 가 건드리지 않았다 — 유도는 ruling.py 에 있다.
    assert "rulebook_facts" not in library


def test_g03_the_change_is_one_file():
    """**§16-8 보고** — 6-O 가 바꾼 production 은 한 파일이다."""
    ruling = source_of("engine/effect/ruling.py")
    assert "def rulebook_facts(" in ruling
    assert "def _facts_of(" in ruling
    for untouched in (
        "engine/effect/library.py",
        "engine/game_state_view.py",
        "engine/effect/executor.py",
        "engine/action_validation.py",
    ):
        assert "rulebook_facts" not in source_of(untouched), untouched
