"""
Phase 6-W — **덱에서 고른 카드를 묘지로 보내는 경로가 어디서 멈추는가.**

6-V 가 기르수(69811710)의 일반 소환 · 유발 후보 생성 · 발동까지 열었고,
해결이 ``UNCHECKED_RULES`` 에서 멈췄다. 6-W 는 그 자리를 **조사하고 고정**
한다 — 프로덕션은 한 줄도 바꾸지 않는다.

왜 고치지 않았는가
------------------
🔴 **룰북에 근거가 없다.** 6-U 가 소환 제약을 열 때 쓴 문장은

    "All Normal Monsters, and most Effect Monsters (**unless they have a
     specific restriction**), can be Summoned in this way" (RULE-SUMMON-009)

이고, 그 문장이 "제약이 없으면 된다" 를 **직접 licensing** 했다. 묘지에는
그런 문장이 없다 — 룰북의 ``Send to the Graveyard`` 항목은 **보내는 방법**을
열거하고 예외는 제외 카드에 관한 것이다 (``test_c01``). 구조화 자료의 묘지
항목도 ``movement`` 에 "효과로 덱에서 보내진다" 를 적지 않는다
(``test_c02``).

그래서 "제약 상수가 없다 → 보낼 수 있다" 는 **근거 없는 허용**이고, 이
Phase 는 그것을 하지 않았다.

이 파일이 하는 일
-----------------
``A``–``E`` 는 **되는 것**을 잰다 (후보 생성 · 카드군 판정 · 인스턴스 구분 ·
거짓 양성 0건). ``F``–``G`` 는 **안 되는 것**을 잰다 (판정이 A/B/C 를
구분하지 못한다 · 해결이 멈춘다 · 판이 변하지 않는다). ``H`` 는 그 벽이
기르수만의 것이 아님을 잰다.

🔴 **안 되는 것을 적는 묶음이 이 파일의 절반이다.** 고정해 두지 않으면 다음
Phase 가 같은 자리를 다시 찾아야 한다.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.archetype import matches_setcode
from engine.archetype_compiler import compile_archetype_condition
from engine.chain import Chain, ChainResolver
from engine.condition import ConditionContext, ConditionResult
from engine.cost import Selection
from engine.effect.journal import EventJournal
from engine.effect.library import (
    OPERATION_RULINGS,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import OperationKind
from engine.effect.ruling import (
    BoardRuling,
    CardRuleFacts,
    OperationRulingRegistry,
    RuleBasis,
    RuleFact,
    RuleQuestion,
    rulebook_facts,
)
from engine.effect.target import PRIMARY_TARGET, TargetSelection, TargetRequirement
from engine.effect.targeting import TargetResolver
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import EffectRef
from engine.state.game_state import GameState
from engine.validation import ValidationResult
from engine.vocabulary import Zone

from deck.opening import build_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MINE = 0
GRANTED = ValidationResult.valid()

#: 이 Phase 의 대상.
GIRSU = 69811710
#: 어리석은 매장 — **같은 모양의 다른 카드** (덱에서 고르고 묘지로 보낸다).
FOOLISH_BURIAL = 81439173
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터. 룰북이 답하는 **유일한** 쪽.
FEATHERMAN = 21844576

#: 기르수 ``s.tgfilter`` 가 묻는 카드군 이름. 숫자를 적지 않는다.
ORCUST_NAMES = ("SET_ORCUST", "SET_WORLD_LEGACY")

# ── 묘지 이동을 말하는 카드들 (실측으로 고른 대표) ──────────────────
#: 차원요새 병기 — ``EFFECT_CANNOT_TO_GRAVE``. §5 의 **B(불가)** 후보.
CANNOT_TO_GRAVE = 1596508
#: F.A. 윕크로서 — ``EFFECT_CANNOT_TO_GRAVE_AS_COST``. 🔴 **비용 한정**이고
#: 효과로 보내는 것과 **다른 질문**이다 (§3 의 구분을 카드가 증명한다).
CANNOT_AS_COST = 49655592
#: 매크로 코스모스 — ``EFFECT_TO_GRAVE_REDIRECT``. 묘지 **대신** 제외로.
REDIRECT_FIELD = 30241314
#: 보옥수 사파이어 페가수스 — ``EFFECT_TO_GRAVE_REDIRECT_CB`` (대체 콜백).
REDIRECT_CALLBACK = 7093411
#: 성유물－『성장』 — 자기 텍스트가 「이 카드가 묘지로 보내졌을 경우」 다.
#: 기르수 후보 중 **유일하게** 자기 묘지행 유발을 등록한 카드다.
SELF_GRAVE_TRIGGER = 93920420


# ======================================================================
# 공용 도구
# ======================================================================
def _archetype_codes() -> tuple[int, ...]:
    compiled = compile_archetype_condition(ORCUST_NAMES)
    assert compiled is not None and compiled.unresolved == ()
    return tuple(code for _, code in compiled.resolved)


def _orcust_pool(repository) -> list[int]:
    codes = _archetype_codes()
    return sorted(
        card.id
        for card in repository.all_cards()
        if not card.is_extra_deck
        and card.id != GIRSU
        and any(matches_setcode(card.setcodes, code) for code in codes)
    )


def _girsu_board(repository, *, deck_pool=None, extra_hand=(), girsu_copies=1):
    """기르수가 패에 있는 선공 판. 무작위 셔플에 기대지 않는다."""
    pool = list(deck_pool) if deck_pool is not None else _orcust_pool(repository)
    lines = [f"{GIRSU} x{girsu_copies}"] + [
        f"{cid} x1" for cid in pool[: 40 - girsu_copies]
    ]
    hand = [GIRSU, *list(extra_hand)]
    hand += [cid for cid in pool if cid not in hand][: max(0, 5 - len(hand))]
    setup = build_opening(repository, parse_recipe("\n".join(lines), repository).draft, hand[:5])
    assert setup.duel is not None, setup.blockers
    return setup


def _summon_girsu(duel):
    actions = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
        and duel.state.find_instance(a.source).card_id == GIRSU
    ]
    assert actions, "기르수가 일반 소환 후보에 없다 (6-U 가 열어 둔 경로다)"
    step = duel.apply(actions[0])
    assert step.accepted is True, step.reason
    return next(
        c.instance_id for c in duel.state.player(MINE).monster_zone if c is not None
    )


def _girsu_candidates(duel, source):
    """
    기르수 효과의 **적법 후보**. 규칙이 선언한 ``looked_at`` 을 열고 센다.

    룰북이 그것을 licensing 한다 — *"If a card effect requires you to ...
    look through it"*. 평소 관측으로는 덱이 보이지 않는다 (``test_f02``).
    """
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))
    spec = definition.targets[0].spec
    granted = GameStateView.from_state(
        duel.state, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(player=MINE, source=source, effect_ref=definition.effect_ref),
    )
    return definition, spec, granted, found


def _facts_for(repository, card_id):
    """그 카드에 대해 판정 계층이 들고 있는 사실. 없으면 ``None``."""
    declared = OPERATION_RULINGS.facts_for(card_id)
    if declared is not None:
        return declared
    return rulebook_facts(CardDefinitionView.of(repository.get(card_id)))


def _grave_codes(repository, card_id) -> set[str]:
    card = repository.get(card_id)
    if card is None or card.script is None:
        return set()
    return {code for code in (card.script.effect_codes or ()) if "GRAVE" in code}


def _has_self_grave_trigger(repository, card_id) -> bool:
    """스크립트가 ``EVENT_TO_GRAVE`` 를 **자기**(``SINGLE``) 로 등록했는가."""
    card = repository.get(card_id)
    if card is None or card.script is None:
        return False
    return any(
        spec.code == "EVENT_TO_GRAVE" and "SINGLE" in set(spec.effect_types)
        for spec in card.script.effects
    )


# ======================================================================
# A. 선택 조건 — 카드군 판정은 기존 계층이 한다
# ======================================================================


@requires_official_db
def test_a01_the_choice_is_a_resolution_time_choice_not_a_target(repository):
    """
    🔴 **이 Phase 의 중심 구분** (§4 가 경고한 것).

    기르수의 선택은 **해결 중 고르기**이고 발동 시 대상 지정이 아니다.
    Lua 가 그 둘을 다른 자리에 적는다:

    ====================  ==========================================
    대상 지정              ``EFFECT_FLAG_CARD_TARGET`` + ``SelectTarget``
                          — ``SetTarget`` 안에서
    해결 중 고르기         플래그 없음 + ``SelectMatchingCard``
                          — ``SetOperation`` 안에서
    ====================  ==========================================

    엔진의 어휘가 그 구분을 **이미 들고 있다** (``TargetRequirement``).
    """
    lua = (ROOT / f"c{GIRSU}.lua").read_text("utf-8")
    #: 대상 지정의 표지가 **없다**.
    assert "EFFECT_FLAG_CARD_TARGET" not in lua
    assert "SelectTarget" not in lua
    #: 고르기는 **해결 동작**(``s.tgop``) 안에 있다.
    operation = lua[lua.index("function s.tgop") :]
    assert "Duel.SelectMatchingCard" in operation

    #: 그래서 정의도 ``CHOOSING`` 이다 — ``TARGETING`` 이 아니다.
    spec = entry_for(EffectRef(GIRSU, 0)).definition.targets[0].spec
    assert spec.requirement is TargetRequirement.CHOOSING
    assert spec.is_targeting is False

    #: 대조군 — 무정한 말살은 **진짜 대상 지정**이다.
    ruthless = (ROOT / "c73148972.lua").read_text("utf-8")
    assert "EFFECT_FLAG_CARD_TARGET" in ruthless
    assert "Duel.SelectTarget" in ruthless


@requires_official_db
def test_a02_the_archetype_codes_come_from_the_constant_table(repository):
    """카드군 판정은 **기존 setcode 계층**이 한다 (§3). 숫자를 적지 않았다."""
    spec = entry_for(EffectRef(GIRSU, 0)).definition.targets[0].spec
    assert spec.choice.source.require.setcodes == _archetype_codes()
    #: 표가 무엇을 돌려줬는지도 적어 둔다 — 적어 둔 숫자를 믿지 않는다.
    assert _archetype_codes() == (0x11B, 0xFE)


@requires_official_db
def test_a03_the_candidate_source_is_the_controllers_deck_only(repository):
    """``LOCATION_DECK, 0`` — 자신 덱만이다. 상대 덱은 후보가 아니다."""
    source = entry_for(EffectRef(GIRSU, 0)).definition.targets[0].spec.choice.source
    assert source.zones == frozenset({Zone.DECK})
    assert source.owner.value == "controller"


# ======================================================================
# B. 후보 생성 — 되는 것 (§7-2 · §7-3 · §7-4 · §7-6)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_b01_orcust_and_world_legacy_cards_are_both_candidates(repository):
    """
    §7-2 · §7-3 — **두 카드군이 모두 후보가 된다.**

    묶음 하나로 묻는 조건이므로 (``IsSetCard`` 가 목록 중 하나라도 맞으면
    참) 한쪽만 걸리면 그 조건이 잘못 옮겨진 것이다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    _, spec, _, found = _girsu_candidates(duel, source)

    codes = spec.choice.source.require.setcodes
    orcust, legacy = [], []
    for instance in found.eligible:
        card = repository.get(duel.state.find_instance(instance).card_id)
        if matches_setcode(card.setcodes, codes[0]):
            orcust.append(card.id)
        if matches_setcode(card.setcodes, codes[1]):
            legacy.append(card.id)
    assert orcust, "「오르페골」 후보가 하나도 없다"
    assert legacy, "「성유물」 후보가 하나도 없다"


@pytest.mark.real_card
@requires_official_db
def test_b02_no_candidate_is_outside_the_archetype_or_the_deck(repository):
    """
    §7-4 · §6 — **거짓 양성 0건.**

    후보 전부가 그 카드군이고, 전부 자신 덱에 있다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    _, spec, _, found = _girsu_candidates(duel, source)
    codes = spec.choice.source.require.setcodes

    deck = duel.state.player(MINE).zone(Zone.DECK)
    assert len(found.eligible) == len(deck), "이 판의 덱은 전부 후보여야 한다"
    for instance in found.eligible:
        held = duel.state.find_instance(instance)
        assert held.zone is Zone.DECK, (instance, held.zone)
        card = repository.get(held.card_id)
        assert any(matches_setcode(card.setcodes, code) for code in codes), card.id


@pytest.mark.real_card
@requires_official_db
def test_b03_a_deck_without_the_archetype_offers_nothing(repository):
    """
    §7-5 — **덱에 해당 카드가 없으면 후보가 0장이다.** 지어내지 않는다.

    🔴 그런데 발동 조건은 여전히 참이다 — ``s.tgtg`` 의 **덱 장수 부분만**
    옮겼기 때문이다. 그 간격을 숨기지 않고 여기 적는다.
    """
    plain = [
        card.id
        for card in repository.all_cards()
        if not card.is_extra_deck and card.is_monster and "NORMAL" in card.type_names
    ][:39]
    assert len(plain) >= 39
    setup = _girsu_board(repository, deck_pool=plain, girsu_copies=1)
    duel = setup.duel
    source = _summon_girsu(duel)
    definition, _, _, found = _girsu_candidates(duel, source)

    assert found.eligible == (), [
        duel.state.find_instance(i).card_id for i in found.eligible
    ]
    #: 발동 조건은 참이다 (덱 장수만 본다).
    assert definition.activation.evaluate(
        duel.view(MINE), ConditionContext(player=MINE, source=source)
    ).is_true


@pytest.mark.real_card
@requires_official_db
def test_b04_identical_cards_are_separate_instances(repository):
    """
    §7-6 · §7-13 — **같은 카드가 여러 장이면 서로 다른 후보**다.

    묶는 것이 ``InstanceId`` 이므로 같은 이름 3장은 **세 후보**이고, 그
    구분이 없으면 "어느 한 장을 보냈다" 를 말할 수 없다.
    """
    others = [cid for cid in _orcust_pool(repository) if cid != SELF_GRAVE_TRIGGER]
    #: 🔴 앞쪽 넷은 **패로 뽑힌다** — 세 장을 덱에 남기려면 그 뒤에 둔다.
    pool = others[:4] + [SELF_GRAVE_TRIGGER] * 3 + others[4:]
    setup = _girsu_board(repository, deck_pool=pool)
    assert SELF_GRAVE_TRIGGER not in [
        c.card_id for c in setup.duel.state.player(MINE).hand
    ]
    duel = setup.duel
    source = _summon_girsu(duel)
    _, _, _, found = _girsu_candidates(duel, source)

    same = [
        i
        for i in found.eligible
        if duel.state.find_instance(i).card_id == SELF_GRAVE_TRIGGER
    ]
    assert len(same) >= 2, same
    #: 🔴 서로 다른 인스턴스다 — 중복이 아니다.
    assert len(set(same)) == len(same)


# ======================================================================
# C. 🔴 룰북에 근거가 없다 — 고치지 않은 이유
# ======================================================================


def test_c01_the_rulebook_does_not_license_a_general_send_to_grave():
    """
    🔴 **이 Phase 가 유도를 더하지 않은 이유.**

    룰북의 ``Send to the Graveyard`` 항목은 **보내는 방법**을 열거하고,
    예외는 **제외 카드**에 관한 것이다. "제약이 없으면 보낼 수 있다" 를
    말하지 않는다.

    6-U 가 쓴 문장과 **직접 대비**된다 — 그쪽은 ``unless they have a
    specific restriction`` 을 명시적으로 적었다.
    """
    document = json.loads(
        (ROOT / "data/rules/documents/sd-rulebook-en-v10.json").read_text("utf-8")
    )
    sections = [
        s for s in document["sections"] if s.get("title") == "Send to the Graveyard"
    ]
    assert len(sections) == 1, [s.get("title") for s in sections]
    text = sections[0]["text"]

    #: 있는 것 — 보내는 방법과 유발 효과.
    assert "can be sent to the Graveyard in various ways" in text
    assert "When this card is sent to the" in text
    #: 🔴 **없는 것** — "제약이 없으면" 류의 허가 문장.
    assert "unless" not in text.lower()
    assert "restriction" not in text.lower()
    #: 예외는 제외 카드에 관한 것이다.
    assert "banished" in text.lower()

    #: 대조군 — 소환 쪽에는 그 문장이 **있다** (6-U 가 그것을 썼다).
    structured = json.loads(
        (ROOT / "data/rules/structured/sd-rulebook-en-v10.json").read_text("utf-8")
    )
    normal = next(
        s for s in structured["summons"] if s["summon_type"] == "Normal Summon"
    )
    assert any(
        "unless they have a specific restriction" in r for r in normal["restrictions"]
    )


def test_c02_the_structured_graveyard_zone_omits_deck_to_grave():
    """
    구조화 자료의 묘지 항목도 licensing 하지 않는다 — ``movement`` 가
    적는 것은 **파괴**와 **사용된 마법·함정**뿐이다.
    """
    structured = json.loads(
        (ROOT / "data/rules/structured/sd-rulebook-en-v10.json").read_text("utf-8")
    )
    grave = next(z for z in structured["zones"] if z["engine_zone"] == "GRAVE")
    movement = grave["movement"]
    assert movement == [
        "Monster Cards sent here when destroyed",
        "Spell & Trap Cards sent here when used",
    ], movement
    #: 🔴 "효과로 덱에서 보내진다" 가 없다.
    assert not [m for m in movement if "Deck" in m]


# ======================================================================
# D. 제약 상수 — 데이터는 전부 추출되어 있다 (§5 의 재료)
# ======================================================================


@requires_official_db
def test_d01_the_grave_constants_are_extracted_exactly(repository):
    """
    🔴 **분석기가 정확하다.** 단어 경계로 세면 스크립트와 완전히 일치한다.

    처음 측정이 부분 문자열로 틀렸고 (``EFFECT_TO_GRAVE_REDIRECT`` 가
    ``..._CB`` 안에 들어 있다), 그 과정에서 네 번째 상수를 찾았다 —
    ``EFFECT_CANNOT_TO_GRAVE_AS_COST``. 적어 둔 숫자를 믿지 않는다.
    """
    expected = {
        "EFFECT_CANNOT_TO_GRAVE": 3,
        "EFFECT_CANNOT_TO_GRAVE_AS_COST": 1,
        "EFFECT_TO_GRAVE_REDIRECT": 31,
        "EFFECT_TO_GRAVE_REDIRECT_CB": 16,
    }
    for code, count in expected.items():
        from_analysis = {
            card.id
            for card in repository.all_cards()
            if card.script is not None and code in (card.script.effect_codes or ())
        }
        pattern = re.compile(r"\b" + code + r"\b")
        from_source = set()
        for path in ROOT.glob("c*.lua"):
            if pattern.search(path.read_text("utf-8", errors="replace")):
                match = re.fullmatch(r"c(\d+)\.lua", path.name)
                if match:
                    from_source.add(int(match.group(1)))
        assert len(from_analysis) == count, (code, len(from_analysis))
        assert from_analysis == from_source, (code, from_analysis ^ from_source)


@requires_official_db
def test_d02_cost_and_effect_are_different_questions(repository):
    """
    §3 · §7-9 — **비용으로 보내기와 효과로 보내기는 다른 질문**이고,
    코퍼스가 그것을 카드 하나로 증명한다.

    F.A. 윕크로서는 ``EFFECT_CANNOT_TO_GRAVE_AS_COST`` 를 등록한다 —
    **비용 한정**이다. 그 카드는 ``EFFECT_CANNOT_TO_GRAVE`` 를 갖지 않으므로
    "효과로는 보낼 수 있다" 와 모순되지 않는다.

    룰북도 그 둘을 가른다: *"A card that is returned from the field to the
    hand or Deck, or, that is sent to the Graveyard **as a cost** or
    Tribute, is NOT considered 'destroyed.'"*
    """
    codes = _grave_codes(repository, CANNOT_AS_COST)
    assert "EFFECT_CANNOT_TO_GRAVE_AS_COST" in codes
    assert "EFFECT_CANNOT_TO_GRAVE" not in codes

    #: 질문 어휘도 둘을 가른다 — 같은 칸에 넣지 않았다.
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE is not RuleQuestion.MAY_BE_DISCARDED

    #: 기르수의 조작은 **효과**다 — 비용이 아니다.
    definition = entry_for(EffectRef(GIRSU, 0)).definition
    assert definition.cost.costs == ()
    (operation,) = definition.operations
    assert operation.kind is OperationKind.SEND_TO_GRAVE


@requires_official_db
def test_d03_redirect_is_not_the_same_as_forbidden(repository):
    """
    §5 · §7-10 — **이동 불가와 대체 이동을 가른다.**

    매크로 코스모스는 묘지행을 **금지**하지 않는다. 묘지 **대신 제외**로
    보낸다 (``SetValue(LOCATION_REMOVED)``). 보옥수는 대체 **콜백**이다.

    🔴 그 둘은 ``EFFECT_CANNOT_TO_GRAVE`` 와 **다른 상수**이고, 섞으면
    "못 간다" 와 "다른 데로 간다" 가 한 칸에 들어간다.
    """
    assert _grave_codes(repository, REDIRECT_FIELD) == {"EFFECT_TO_GRAVE_REDIRECT"}
    assert _grave_codes(repository, REDIRECT_CALLBACK) == {
        "EFFECT_TO_GRAVE_REDIRECT_CB"
    }
    assert _grave_codes(repository, CANNOT_TO_GRAVE) == {"EFFECT_CANNOT_TO_GRAVE"}

    #: 매크로 코스모스의 대체 도착지가 원본에 적혀 있다.
    lua = (ROOT / f"c{REDIRECT_FIELD}.lua").read_text("utf-8")
    assert "EFFECT_TO_GRAVE_REDIRECT" in lua
    assert "LOCATION_REMOVED" in lua


@requires_official_db
def test_d04_leave_field_redirect_does_not_reach_a_deck_card(repository):
    """
    🔴 **범위를 가른다.** ``EFFECT_LEAVE_FIELD_REDIRECT`` 는 255장이 쓰는
    큰 상수인데, 그것이 말하는 것은 **필드를 떠날 때**다.

    기르수가 보내는 카드는 **덱**에 있으므로 그 상수는 해당하지 않는다.
    범위를 가르지 않으면 "255장이 막는다" 는 거짓 보고가 된다.
    """
    users = {
        card.id
        for card in repository.all_cards()
        if card.script is not None
        and "EFFECT_LEAVE_FIELD_REDIRECT" in (card.script.effect_codes or ())
    }
    assert len(users) == 255, len(users)
    #: 이름이 말하는 자리가 필드다 — 덱이 아니다.
    assert "LEAVE_FIELD" in "EFFECT_LEAVE_FIELD_REDIRECT"


# ======================================================================
# E. 자기 묘지행 유발 — 다음 Phase 의 재료 (쓰지는 않았다)
# ======================================================================


@requires_official_db
def test_e01_the_self_grave_trigger_population_is_measured(repository):
    """
    🔴 **다음 Phase 가 쓸 증거를 재서 남긴다.** 이 Phase 는 쓰지 않았다.

    카드 자신의 스크립트가 ``EVENT_TO_GRAVE`` 를 ``SINGLE``(자기)로 등록
    하면, 그 카드는 묘지로 보내질 수 있다는 **긍정적 증거**다 — 룰북이 그
    텍스트 모양을 묘지행에 직접 묶는다 (``test_c01`` 의 두 번째 단언).

    전 코퍼스에서 그런 카드와 ``EFFECT_CANNOT_TO_GRAVE`` 가 **겹치지
    않는다** — 모순 0건이고, 그것이 이 증거의 일관성이다.
    """
    main_deck = [
        card
        for card in repository.all_cards()
        if not card.is_extra_deck and card.script is not None
    ]
    with_trigger = [c for c in main_deck if _has_self_grave_trigger(repository, c.id)]
    assert len(with_trigger) == 818, len(with_trigger)

    #: 🔴 모순 0건.
    conflicting = [
        c.id
        for c in with_trigger
        if "EFFECT_CANNOT_TO_GRAVE" in (c.script.effect_codes or ())
    ]
    assert conflicting == [], conflicting


@pytest.mark.real_card
@requires_official_db
def test_e02_exactly_one_girsu_candidate_carries_that_evidence(repository):
    """
    기르수 후보 중 자기 묘지행 유발을 가진 카드가 **정확히 하나**다 —
    성유물－『성장』. 공식 텍스트가 「이 카드가 묘지로 보내졌을 경우」 다.
    """
    pool = _orcust_pool(repository)
    carriers = [cid for cid in pool if _has_self_grave_trigger(repository, cid)]
    assert carriers == [SELF_GRAVE_TRIGGER], carriers
    assert "묘지로 보내졌을 경우" in repository.get(SELF_GRAVE_TRIGGER).desc


# ======================================================================
# F. 🔴 여기서 멈춘다 — 판정이 A/B/C 를 구분하지 못한다
# ======================================================================


@requires_official_db
def test_f01_the_gate_now_tells_evidence_from_no_evidence(repository):
    """
    🔴 **Phase 6-X 가 이 자리를 고쳤다.** 6-W 가 재던 것은 "셋 다 같은
    답이고 이유문까지 같다" 였고, 그 이름은
    ``test_f01_the_gate_cannot_tell_the_three_situations_apart`` 였다.

    무엇이 바뀌었는가
    -----------------
    카드 **자신의 텍스트**가 자기 묘지행을 적었으면 ``TRUE`` 가 된다
    (:func:`~engine.effect.ruling.self_grave_trigger_fact`). 그래서 증거가
    있는 카드와 없는 카드가 **갈린다.**

    🔴 **6-W 의 분류 하나가 틀렸다** (6-X 가 Lua 를 읽고 정정했다).
    차원요새 병기를 "B — 자기가 묘지에 못 간다" 로 적었는데, 그 카드의
    ``EFFECT_CANNOT_TO_GRAVE`` 는 ``EFFECT_TYPE_FIELD`` +
    ``SetTargetRange(LOCATION_DECK,LOCATION_DECK)`` 다 — **남의 덱 카드**가
    묘지로 가는 것을 막는 지속 효과이고, 자기 제한이 아니다. 그래서 그
    카드 자신의 묘지행은 지금도 ``UNKNOWN`` 이 맞다 (``test_graveyard_movement_ruling.py`` 의
    ``test_b03`` 이 그 상수의 실제 범위를 고정한다).
    """
    cases = {
        "A 증거 있다": SELF_GRAVE_TRIGGER,
        "증거 없다 (오르페골 코어)": 55051920,
        "증거 없다 (차원요새 병기 — 자기 제한이 아니다)": CANNOT_TO_GRAVE,
    }
    answers = {}
    for label, card_id in cases.items():
        game = GameState.create(repository, decks=([card_id] * 10, [FEATHERMAN] * 10))
        game.draw(MINE, 1)
        instance = game.player(MINE).hand[0].instance_id
        board = BoardRuling(
            GameStateView.from_state(game, viewer=MINE), OPERATION_RULINGS
        )
        verdict = board.explain(RuleQuestion.MAY_BE_SENT_TO_GRAVE, instance)
        answers[label] = (verdict.answer, verdict.reason)

    #: 🔴 **갈린다** — 이것이 6-W 와 달라진 전부다.
    assert answers["A 증거 있다"][0] is ConditionResult.TRUE, answers
    assert "자기 묘지행 유발을 등록한다" in answers["A 증거 있다"][1]

    #: 증거가 없는 둘은 그대로 ``UNKNOWN`` 이다 — 근거 없는 허가를 주지
    #: 않는다는 것이 이 Phase 가 **지킨** 쪽이다.
    for label in list(cases)[1:]:
        answer, reason = answers[label]
        assert answer is ConditionResult.UNKNOWN, (label, answers[label])
        assert "확인된 것이 없습니다" in reason, (label, reason)

    #: 🔴 대조군 — 통상 몬스터만 답이 난다 (룰북 한 줄).
    game = GameState.create(repository, decks=([FEATHERMAN] * 10, [FEATHERMAN] * 10))
    game.draw(MINE, 1)
    instance = game.player(MINE).hand[0].instance_id
    board = BoardRuling(GameStateView.from_state(game, viewer=MINE), OPERATION_RULINGS)
    assert (
        board.may(RuleQuestion.MAY_BE_SENT_TO_GRAVE, instance) is ConditionResult.TRUE
    )


@requires_official_db
def test_f02_the_registry_and_the_rulebook_derivation_are_the_only_sources(repository):
    """
    **왜** 구분이 없는지 구조로 적는다 — 답이 나오는 자리가 둘뿐이다.

    1. ``OPERATION_RULINGS`` — 손으로 적은 19장
    2. ``rulebook_facts`` — 순수 통상 몬스터만

    기르수 후보 47장 중 어느 쪽에도 걸리는 카드가 **0장**이다.
    """
    pool = _orcust_pool(repository)
    covered = [cid for cid in pool if _facts_for(repository, cid) is not None]
    assert covered == [], covered

    #: 등록소는 19장이고 그 안에 후보가 없다.
    assert len(OPERATION_RULINGS) == 19
    assert not (set(OPERATION_RULINGS.card_ids) & set(pool))


@pytest.mark.real_card
@requires_official_db
def test_f03_every_candidate_answers_unknown_on_the_real_board(repository):
    """
    실제 판에서도 같다 — 적법 후보 **전부**가 ``UNKNOWN`` 이다.

    🔴 이것이 §6 의 "그 카드의 묘지 이동 가능성 확인" 이 실패하는 자리다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    _, _, granted, found = _girsu_candidates(duel, source)
    assert found.eligible, "후보가 없으면 이 시험은 아무것도 재지 않는다"

    board = BoardRuling(granted, OPERATION_RULINGS)
    answers = {
        board.may(RuleQuestion.MAY_BE_SENT_TO_GRAVE, i) for i in found.eligible
    }
    assert answers == {ConditionResult.UNKNOWN}, answers


# ======================================================================
# G. 🔴 해결이 멈추고 판이 변하지 않는다 (§7-1 · §7-11 · §7-12)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_g01_activation_succeeds_and_resolution_stops_at_the_gate(repository):
    """
    §7-1 — **발동은 되고 해결은 안 된다.** 둘을 가른다 (§3).

    고르는 사람이 자기 덱을 보고 한 장을 고르면 발동이 성공하고 체인에
    링크가 하나 쌓인다. 그런데 해결이 ``UNCHECKED_RULES`` 에서 멈춘다.

    🔴 **임의의 첫 카드를 자동으로 고르지 않았다** (§4). 후보 목록을 받아
    시험이 명시적으로 하나를 지정한다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    definition, _, _, found = _girsu_candidates(duel, source)
    chosen = found.eligible[0]
    #: 🔴 **전제를 적어 둔다** (Phase 6-X 가 명시로 바꿨다). 이 판의 후보
    #: 가운데 자기 묘지행 증거를 가진 카드가 **한 장도 없다** — 기본 풀의
    #: 성유물－『성장』은 패로 뽑히거나 40장 절단에서 빠진다. 그래서 아래의
    #: "해결이 멈춘다" 는 6-X 가 유도를 더한 뒤에도 성립하고, 그것이
    #: **근거 없는 허가를 주지 않는다**는 뜻이다 (``test_f01`` 과 짝이다).
    assert all(
        not repository.get(duel.state.find_instance(i).card_id)
        .self_grave_trigger_signals
        for i in found.eligible
    )

    registry = definition_registry()
    activated = EffectActivator(registry, implementation_registry()).activate(
        duel.state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(GIRSU, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
        authorization=GRANTED,
    )
    assert activated.status.value == "activated"
    assert len(activated.chain) == 1

    journal = EventJournal()
    resolved = ChainResolver(
        build_executor(journal, rulings=OPERATION_RULINGS), registry
    ).resolve_top(duel.state, activated.chain)

    assert resolved.result.status.name == "UNCHECKED_RULES"
    assert "IsAbleToGrave" in resolved.result.reason


@pytest.mark.real_card
@requires_official_db
def test_g02_nothing_moves_before_or_after_the_blocked_resolution(repository):
    """
    §7-11 · §7-12 — **체인 해결 이전에도, 막힌 해결 뒤에도 카드가 움직이지
    않는다.** 덱 · 묘지 · 인스턴스 · 기록 네 축을 전부 잰다.

    🔴 **이것을 성공으로 적지 않는다.**
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    definition, _, _, found = _girsu_candidates(duel, source)
    chosen = found.eligible[0]
    #: ``test_g01`` 과 같은 전제 — 이 후보에는 증거가 없다.
    assert not repository.get(
        duel.state.find_instance(chosen).card_id
    ).self_grave_trigger_signals

    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))
    grave_before = len(duel.state.player(MINE).zone(Zone.GRAVE))
    registry = definition_registry()

    activated = EffectActivator(registry, implementation_registry()).activate(
        duel.state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(GIRSU, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
        authorization=GRANTED,
    )
    #: 🔴 **발동만으로는 움직이지 않는다** — 해결이 하는 일이다.
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before
    assert duel.state.find_instance(chosen).zone is Zone.DECK

    journal = EventJournal()
    ChainResolver(
        build_executor(journal, rulings=OPERATION_RULINGS), registry
    ).resolve_top(duel.state, activated.chain)

    #: 막힌 해결 뒤에도 그대로다.
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before
    assert duel.state.find_instance(chosen).zone is Zone.DECK
    #: 기록도 비어 있다 — 멈춘 해결은 사건을 적지 않는다.
    assert list(journal) == []


@pytest.mark.real_card
@requires_official_db
def test_g03_the_duel_loop_still_offers_no_activation(repository):
    """
    §7-13 — ``STRUCTURAL-125`` 는 그대로다. 이 Phase 는 그것도 바꾸지
    않았다.

    🔴 **그리고 그 경계가 옳다** — ``PlayerAction`` 에 덱 인스턴스를 적으면
    정책이 후보 목록을 읽는 것만으로 덱 내용을 알게 된다. 고쳐야 할 것은
    경계가 아니라 **선택을 해결 시점으로 옮기는 것**이다 (``test_a01``).
    """
    from engine.target_bridge import target_combinations

    setup = _girsu_board(repository)
    duel = setup.duel
    source = _summon_girsu(duel)
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))

    assert list(target_combinations(duel.state, MINE, definition, source)) == []
    offered = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "activate_effect" not in offered
    assert "end_phase" in offered

    #: 평소 관측으로는 덱이 보이지 않는다 — 그것이 그 경계의 근거다.
    ordinary = GameStateView.from_state(duel.state, viewer=MINE)
    deck = duel.state.player(MINE).zone(Zone.DECK)
    assert deck, "덱이 비면 이 시험은 아무것도 재지 않는다"
    assert all(ordinary.find(c.instance_id) is None for c in deck)


# ======================================================================
# H. 같은 벽이 기르수만의 것이 아니다 (§7-15)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_h01_foolish_burial_stops_at_the_same_place(repository):
    """
    §7-15 — **같은 구조의 다른 카드가 같은 자리에서 멈춘다.**

    어리석은 매장도 덱에서 고르고 묘지로 보낸다. 관문 선언(``gated``)과
    조작 종류가 기르수와 같고, 멈추는 이유도 같다.

    🔴 즉 이 벽은 **유발 효과 때문도, 기르수 때문도 아니다.** 덱에서 고른
    카드를 묘지로 보내는 **모든** 효과가 여기서 멈춘다.
    """
    girsu = entry_for(EffectRef(GIRSU, 0)).definition
    burial = entry_for(EffectRef(FOOLISH_BURIAL, 0)).definition

    for definition in (girsu, burial):
        (operation,) = definition.operations
        assert operation.kind is OperationKind.SEND_TO_GRAVE
        assert operation.gated is True
        source = definition.targets[0].spec.choice.source
        assert source.zones == frozenset({Zone.DECK})
        assert definition.targets[0].spec.requirement is TargetRequirement.CHOOSING

    #: 다른 점은 **발동 분류 하나**다 — 유발 대 카드 발동.
    assert girsu.activation_kind is not None
    assert burial.activation_kind is None


@requires_official_db
def test_h02_the_production_code_gained_no_card_branch(repository):
    """
    🔴 **이 Phase 는 프로덕션을 한 줄도 바꾸지 않았다.**

    고칠 수 있었지만 룰북 근거가 없어서 하지 않았다 (``test_c01``). 그
    결정의 증거로, 판정 계층에 이 Phase 가 더한 카드 번호가 없음을 센다.
    """
    ruling_source = (ROOT / "engine" / "effect" / "ruling.py").read_text("utf-8")
    for card_id in (GIRSU, SELF_GRAVE_TRIGGER, CANNOT_TO_GRAVE, REDIRECT_FIELD):
        assert str(card_id) not in ruling_source, card_id
    #: 묘지 상수 이름도 판정 계층에 없다 — 유도를 더하지 않았다는 뜻이다.
    assert "EFFECT_CANNOT_TO_GRAVE" not in ruling_source
    assert "EFFECT_TO_GRAVE_REDIRECT" not in ruling_source


# ======================================================================
# I. 🔴 막는 것이 **사실 하나**임을 보인다 (§13.1 의 근거)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_i01_one_registered_fact_lets_the_same_path_resolve(repository):
    """
    🔴 **해결 경로는 이미 완성되어 있다.** 막는 것은 판정 사실 하나다.

    ``OPERATION_RULINGS`` 의 **사본**에 성유물－『성장』의
    ``MAY_BE_SENT_TO_GRAVE`` 를 한 줄 넣고 **같은 프로덕션 해결 경로**를
    돌린다. 그러면 ``UNCHECKED_RULES`` 가 ``RESOLVED`` 가 되고 카드가 실제로
    덱에서 묘지로 간다.

    읽는 법
    -------
    이것이 보이는 것: 조작 · 체인 해결 · ``EventJournal`` 은 준비돼 있다.
    이것이 **보이지 않는** 것: 818장에 대한 **유도의 정당성**. 그 사실을
    여기서는 손으로 넣었다.

    🔴 **그래서 이것은 수준 3 달성이 아니다.** 프로덕션 등록소는 그대로이고
    (``test_i02``), 프로덕션 경로에서 기르수 효과는 여전히 멈춘다
    (``test_g01``). 이 시험은 §13.1 추천의 **근거**를 고정한다.

    .. note::
       🔴 **Phase 6-X 가 그 추천을 실행했다.** 이제 같은 카드가 **등록소
       사본 없이도** 해결된다 — 유도가 그 사실을 카드 자신의 텍스트에서
       읽는다 (``test_graveyard_movement_ruling.py`` 의 ``test_d01``).

       이 시험을 남겨 두는 이유는 **등가성**이다. 손으로 적은 사실과
       유도된 사실이 **같은 결과**에 이른다는 것을 보이므로, 유도가
       등록소를 흉내 낸 것이 아니라 같은 자리에 들어갔다는 증거다.
    """
    others = [cid for cid in _orcust_pool(repository) if cid != SELF_GRAVE_TRIGGER]
    #: 앞쪽 넷은 패로 뽑힌다 — 그 뒤에 두어야 덱에 남는다.
    setup = _girsu_board(repository, deck_pool=others[:4] + [SELF_GRAVE_TRIGGER] + others[4:])
    duel = setup.duel
    source = _summon_girsu(duel)
    _, _, _, found = _girsu_candidates(duel, source)
    chosen = next(
        i
        for i in found.eligible
        if duel.state.find_instance(i).card_id == SELF_GRAVE_TRIGGER
    )

    #: 🔴 **사본**이다. 원본 등록소는 건드리지 않는다.
    derived = OperationRulingRegistry(
        tuple(OPERATION_RULINGS.facts_for(c) for c in OPERATION_RULINGS.card_ids)
    )
    note = (
        "자기 스크립트가 EVENT_TO_GRAVE 를 SINGLE 로 등록한다 — 공식 "
        "텍스트가 「이 카드가 묘지로 보내졌을 경우」다."
    )
    derived.register(
        CardRuleFacts(
            card_id=SELF_GRAVE_TRIGGER,
            answers={
                RuleQuestion.MAY_BE_SENT_TO_GRAVE: RuleFact(
                    ConditionResult.TRUE, RuleBasis.CARD_TEXT, note
                )
            },
            restricts_others=False,
            restriction_basis=RuleBasis.CARD_TEXT,
            restriction_note=note,
        )
    )
    assert len(derived) == len(OPERATION_RULINGS) + 1

    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))
    grave_before = len(duel.state.player(MINE).zone(Zone.GRAVE))
    registry = definition_registry()
    activated = EffectActivator(registry, implementation_registry()).activate(
        duel.state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(GIRSU, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
        authorization=GRANTED,
    )
    assert activated.status.value == "activated"

    journal = EventJournal()
    resolved = ChainResolver(
        build_executor(journal, rulings=derived), registry
    ).resolve_top(duel.state, activated.chain)

    #: 🔴 여기서는 끝까지 간다.
    assert resolved.result.status.name == "RESOLVED", resolved.result.reason
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before - 1
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before + 1
    moved = duel.state.find_instance(chosen)
    #: **그 인스턴스**가 갔다 — 같은 이름의 다른 장이 아니다.
    assert moved.zone is Zone.GRAVE
    assert moved.card_id == SELF_GRAVE_TRIGGER

    #: 기록이 이동과 섞기를 둘 다 적는다.
    entries = [str(e) for e in journal]
    assert entries, "해결했는데 기록이 비었다"
    assert any("send_to_grave" in text for text in entries), entries
    assert any("DECK" in text and "GRAVE" in text for text in entries), entries


@requires_official_db
def test_i02_the_production_registry_is_untouched():
    """
    🔴 ``test_i01`` 이 **원본을 바꾸지 않았다**는 것을 따로 센다.

    사본에 넣은 사실이 프로덕션 등록소로 새면 ``test_f01`` 이 조용히 뜻을
    잃는다 — 그래서 원본의 크기와 내용을 함께 고정한다.
    """
    assert len(OPERATION_RULINGS) == 19
    assert SELF_GRAVE_TRIGGER not in OPERATION_RULINGS
    #: 원본에서 묘지 질문에 답하는 것은 **통상 몬스터 한 장**뿐이다.
    answering = [
        card_id
        for card_id in OPERATION_RULINGS.card_ids
        if OPERATION_RULINGS.facts_for(card_id).answer_for(
            RuleQuestion.MAY_BE_SENT_TO_GRAVE
        )
        is not None
    ]
    assert answering == [FEATHERMAN], answering
