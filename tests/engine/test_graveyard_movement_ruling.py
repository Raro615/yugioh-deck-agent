"""
Phase 6-X — **묘지 이동을 언제 허가하는가.**

6-W 가 "해결이 ``UNCHECKED_RULES`` 에서 멈춘다" 를 고정했고, 원인은
``MAY_BE_SENT_TO_GRAVE`` 에 답하는 지식이 **룰북 한 줄**(통상 몬스터)뿐이라는
것이었다. 6-X 는 그 자리에 **카드 자신의 텍스트에서 읽는 유도** 하나를
더한다.

무엇을 근거로 허가하는가
------------------------
룰북의 ``Send to the Graveyard`` 항목이 텍스트 모양과 묘지행을 **직접**
묶는다:

    "Destroying a card, discarding, and Tributing a monster are all actions
     that send a card to the Graveyard, and will normally activate **"When
     this card is sent to the Graveyard…"** Trigger Effects."

그러므로 그런 유발을 **인쇄한** 카드는 묘지로 보내지는 카드다.

🔴 **쓰지 않은 추론** — "제약 상수가 없으니 보낼 수 있다". 그 문장을
licensing 하는 줄이 룰북에 없다 (6-W §3.5 가 전수 확인: ``unless`` ·
``restriction`` 둘 다 부재). 그래서 증거가 없는 카드는 **그대로
``UNKNOWN``** 이고, 이 파일의 절반이 그것을 잰다.

이 파일의 묶음
--------------
``A`` 유도의 범위 (질문 하나 · 세 값) · ``B`` 금지 상수의 **실제 범위**
(6-W 의 분류 오류 정정) · ``C`` §5 의 거짓 허가 10사례 · ``D`` 실제 Duel
해결 (기르수) · ``E`` 공통성 (어리석은 매장) · ``F`` 유도가 넓히지 않은 것.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from engine.action import PlayerAction
from engine.activation import EffectActivator
from engine.chain import Chain, ChainResolver
from engine.condition import ConditionContext, ConditionResult
from engine.cost import Selection
from engine.effect.journal import EventJournal
from engine.effect.library import (
    OPERATION_RULINGS,
    build_executor,
    definition_registry,
    implementation_registry,
)
from engine.effect.ruling import (
    DERIVED_FACTS,
    SEND_TO_GRAVE_RULE,
    BoardRuling,
    RuleBasis,
    RuleQuestion,
    derived_fact,
    self_grave_text_fact,
)
from engine.effect.target import PRIMARY_TARGET, TargetSelection
from engine.effect.targeting import TargetResolver
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import EffectRef
from engine.state.game_state import GameState
from engine.validation import ValidationResult
from engine.vocabulary import Position, Zone

from core.card_model import SELF_GRAVE_TRIGGER_EVENT, SELF_GRAVE_TRIGGER_SCOPE
from deck.opening import build_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db
from tests.engine.window_helpers import pass_fast_window

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MINE, THEIRS = 0, 1
GRANTED = ValidationResult.valid()

#: 성유물－『성장』 — 「이 카드가 묘지로 보내졌을 경우」. **증거가 있다.**
GROWTH = 93920420
#: 오르페골 코어 — 스크립트를 끝까지 읽었고 그런 자리가 없다 (``False``).
NO_EVIDENCE = 55051920
#: 텐사우전드 드래곤 — 증거 없는 **효과 몬스터** (어리석은 매장의 후보가 된다).
NO_EVIDENCE_MONSTER = 10000
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터. 스크립트가 **없다** (``None``).
FEATHERMAN = 21844576
#: 차원요새 병기 — ``EFFECT_CANNOT_TO_GRAVE`` 를 **필드 효과**로 등록한다.
#: 🔴 자기 제한이 아니라 **덱의 카드**를 막는다 (6-W 가 잘못 분류했다).
FORTRESS = 1596508
#: 매크로 코스모스 — 묘지 **대신 제외**로 보낸다 (대체 효과).
MACRO = 30241314
#: F.A. 윕크로서 — ``EFFECT_CANNOT_TO_GRAVE_AS_COST``. **비용 한정**이다.
COST_ONLY = 49655592
#: 기르수 — 유발로 덱에서 고른다.
GIRSU = 69811710
#: 어리석은 매장 — **카드 발동**으로 덱에서 고른다. 같은 공통 규칙이다.
BURIAL = 81439173

ORCUST_NAMES = ("SET_ORCUST", "SET_WORLD_LEGACY")


# ======================================================================
# 공용 도구
# ======================================================================
def _ask(
    repository,
    target_card: int,
    *,
    on_field: int | None = None,
    question: RuleQuestion = RuleQuestion.MAY_BE_SENT_TO_GRAVE,
):
    """패의 ``target_card`` 에 대해 묻는다. ``on_field`` 가 있으면 앞면으로 깐다."""
    deck = [target_card] + ([on_field] if on_field else []) + [FEATHERMAN] * 20
    game = GameState.create(repository, decks=(deck, [FEATHERMAN] * 20), seed=7)
    game.draw(MINE, 2 if on_field else 1)
    target = game.player(MINE).hand[0].instance_id
    if on_field:
        game.move(
            game.player(MINE).hand[1].instance_id,
            Zone.MZONE,
            to_player=MINE,
            position=Position.FACEUP_ATTACK,
        )
    board = BoardRuling(GameStateView.from_state(game, viewer=MINE), OPERATION_RULINGS)
    return board.explain(question, target)


def _evidence(repository, card_id) -> "bool | None":
    return repository.get(card_id).self_grave_text_evidence


def _resolve_deck_choice(game, source, card_id, effect_ref, chosen_filter):
    """
    덱에서 고르는 효과를 **프로덕션 경로**로 발동하고 해결한다.

    🔴 **임의의 첫 카드를 고르지 않는다** — 부르는 쪽이 ``chosen_filter`` 로
    어느 카드인지 **명시**한다 (§6 의 요구다).
    """
    definition = definition_registry().definition_for(effect_ref)
    spec = definition.targets[0].spec
    granted = GameStateView.from_state(
        game, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(player=MINE, source=source, effect_ref=effect_ref),
    )
    chosen = next(
        i for i in found.eligible if chosen_filter(game.find_instance(i).card_id)
    )
    registry = definition_registry()
    activated = EffectActivator(registry, implementation_registry()).activate(
        game,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=effect_ref
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
        authorization=GRANTED,
    )
    journal = EventJournal()
    resolved = ChainResolver(
        build_executor(journal, rulings=OPERATION_RULINGS), registry
    ).resolve_top(game, activated.chain)
    return found, chosen, activated, resolved, journal, granted


# ======================================================================
# A. 유도의 범위 — 질문 하나, 값 셋
# ======================================================================


def test_a01_the_derivation_is_bound_to_exactly_one_question():
    """
    🔴 **범위가 이 설계의 핵심이다.**

    묘지로 보내질 수 있다는 것은 패로 되돌려질 수 있다거나 제외될 수
    있다는 뜻이 **아니다.** :func:`normal_monster_facts` 는 다섯 질문을
    한꺼번에 답하는데 (근거가 "효과가 없다" 여서 다섯에 모두 걸린다),
    이쪽 근거는 묘지에 대한 것뿐이므로 **한 질문에만** 걸린다.
    """
    assert set(DERIVED_FACTS) == {RuleQuestion.MAY_BE_SENT_TO_GRAVE}
    assert DERIVED_FACTS[RuleQuestion.MAY_BE_SENT_TO_GRAVE] is self_grave_text_fact


@requires_official_db
def test_a02_the_signal_has_three_different_answers(repository):
    """
    ``None`` · ``()`` · 비어 있지 않음이 **서로 다른 말**이다 (6-U 와 같은 규약).

    합치면 스크립트가 없는 카드가 "증거 없음" 으로, 증거 없음이 "허가" 로
    흘러간다. 이 Phase 에서는 그 방향이 **거짓 허가**가 되므로 특히 중요하다.
    """
    #: 스크립트가 없다 — 읽지 못했다.
    assert _evidence(repository, FEATHERMAN) is None
    #: 끝까지 읽었고 그런 자리가 없다.
    assert _evidence(repository, NO_EVIDENCE) is False
    assert _evidence(repository, FORTRESS) is False
    #: 찾았다.
    assert _evidence(repository, GROWTH) is True
    #: 🔴 ``False`` 와 ``None`` 이 **다른 값**이다 — ``if not`` 으로 합칠 수
    #: 없다는 것이 이 규약의 요점이다.
    assert _evidence(repository, NO_EVIDENCE) is not None


@requires_official_db
def test_a03_only_a_nonempty_signal_becomes_a_fact(repository):
    """``None`` 과 ``False`` 는 **둘 다** 사실이 되지 않는다."""
    for card_id in (FEATHERMAN, NO_EVIDENCE, FORTRESS):
        view = CardDefinitionView.of(repository.get(card_id))
        assert self_grave_text_fact(view) is None, card_id

    view = CardDefinitionView.of(repository.get(GROWTH))
    fact = self_grave_text_fact(view)
    assert fact is not None
    assert fact.answer is ConditionResult.TRUE
    #: 근거는 **그 카드의 텍스트**다 — 룰북 유도가 아니다.
    assert fact.basis is RuleBasis.CARD_TEXT
    #: 그리고 왜 그것이 근거인지 룰북 문장을 함께 적는다.
    assert SEND_TO_GRAVE_RULE in fact.note


@requires_official_db
def test_a04_the_scope_constant_is_load_bearing(repository):
    """
    🔴 **범위를 보지 않으면 거짓 허가가 된다.**

    ``EVENT_TO_GRAVE`` 를 ``FIELD`` 범위로 등록한 카드는 *남이* 묘지로 갈
    때 반응한다 — 자기 묘지행의 증거가 아니다. 그런 카드가 실제로 있고,
    범위를 뺀 집계와 넣은 집계의 **차이로** 그것을 센다.
    """
    event_only, with_scope = set(), set()
    for card in repository.all_cards():
        if card.script is None:
            continue
        for spec in card.script.effects:
            if spec.code != SELF_GRAVE_TRIGGER_EVENT:
                continue
            event_only.add(card.id)
            if SELF_GRAVE_TRIGGER_SCOPE in set(spec.effect_types):
                with_scope.add(card.id)

    #: 범위를 빼면 더 많이 잡힌다 — 그 차이가 거짓 허가가 될 카드들이다.
    assert with_scope < event_only, (len(with_scope), len(event_only))
    assert len(event_only - with_scope) > 0

    #: 그리고 실제로 유도되는 집합은 좁은 쪽과 **정확히** 같다.
    derived = {
        card.id
        for card in repository.all_cards()
        if card.self_grave_text_evidence is True
    }
    assert derived == with_scope, len(derived ^ with_scope)


# ======================================================================
# B. 🔴 금지 상수의 **실제 범위** — 6-W 의 분류를 정정한다
# ======================================================================


@requires_official_db
def test_b01_no_card_in_the_corpus_forbids_its_own_grave_movement(repository):
    """
    🔴 **6-W 가 틀린 자리.** 6-W 보고서 §3.1 은 차원요새 병기를
    "B — 묘지 이동 불가" 로 적었다. Lua 를 읽으면 그렇지 않다.

    ``EFFECT_CANNOT_TO_GRAVE`` 를 쓰는 세 장 **전부** 같은 모양이다:

    - ``EFFECT_TYPE_FIELD`` — 필드 효과다 (자기 한 장이 아니다)
    - ``SetTargetRange(LOCATION_DECK,LOCATION_DECK)`` — **덱의 카드**를 막는다

    그래서 코퍼스에 "자기가 묘지로 못 간다" 를 선언한 카드는 **0장**이고,
    §5 의 B(명시적 금지)는 **토큰**뿐이다 (룰북이 답한다).
    """
    users = sorted(
        card.id
        for card in repository.all_cards()
        if card.script is not None
        and "EFFECT_CANNOT_TO_GRAVE" in (card.script.effect_codes or ())
    )
    assert len(users) == 3, users

    for card_id in users:
        lua = (ROOT / f"c{card_id}.lua").read_text("utf-8")
        block = lua[: lua.index("EFFECT_CANNOT_TO_GRAVE")]
        after = lua[lua.index("EFFECT_CANNOT_TO_GRAVE") :]
        #: 필드 효과로 등록한다.
        assert "EFFECT_TYPE_FIELD" in block, card_id
        #: 대상 범위가 **덱**이다.
        assert "SetTargetRange(LOCATION_DECK,LOCATION_DECK)" in after, card_id

    #: 🔴 그래서 그 세 장 **자신**은 묘지행 증거도 금지도 없다 — ``UNKNOWN``.
    for card_id in users:
        assert _evidence(repository, card_id) is False, card_id


@requires_official_db
def test_b02_cost_only_prohibition_is_a_different_question(repository):
    """
    ``EFFECT_CANNOT_TO_GRAVE_AS_COST`` 는 **비용 한정**이다 (§5-8 대 §5-9).

    그 카드는 ``EFFECT_CANNOT_TO_GRAVE`` 를 갖지 않으므로 "효과로는 보낼 수
    있다" 와 모순되지 않는다. 질문 어휘도 둘을 가른다.
    """
    codes = set(repository.get(COST_ONLY).script.effect_codes or ())
    assert "EFFECT_CANNOT_TO_GRAVE_AS_COST" in codes
    assert "EFFECT_CANNOT_TO_GRAVE" not in codes
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE is not RuleQuestion.MAY_BE_DISCARDED


@requires_official_db
def test_b03_the_field_prohibition_is_observed_as_board_interference(repository):
    """
    🔴 **그 세 장이 실제로 막는 자리는 판이다.**

    자기 제한이 아니므로 목표 카드의 사실로는 잡히지 않는다. 대신 그 카드가
    **필드에 깔리면** 훑기가 멈춘다 — 증거가 있는 카드조차 ``UNKNOWN`` 이
    된다. 그것이 §4 의 "기본 규칙에서 허용되는 행동이라도 현재 적용 중인
    제한을 무시하지 않는다" 다.
    """
    clean = _ask(repository, GROWTH)
    assert clean.answer is ConditionResult.TRUE

    blocked = _ask(repository, GROWTH, on_field=FORTRESS)
    assert blocked.answer is ConditionResult.UNKNOWN
    assert str(FORTRESS) in blocked.reason
    assert "막는지 알 수 없습니다" in blocked.reason


# ======================================================================
# C. §5 의 거짓 허가 10사례
# ======================================================================


@requires_official_db
def test_c01_an_ordinary_deck_monster_moves_by_effect(repository):
    """
    §5-1 — 일반적인 덱 몬스터가 효과로 묘지로 간다 (증거가 있을 때).

    🔴 **Phase 6-AC 가 근거의 출처를 바꿨다.** 6-X 부터 이 답은 규칙서에서
    **파생된** 사실이었고 (``self_grave_text_fact``), 6-AC 가 성유물－
    『성장』 을 ``OPERATION_RULINGS`` 에 **등재**했으므로 등재가 먼저 답한다.
    답(``TRUE``)은 같고 **왜 그런지를 적는 자리**가 바뀌었다 — 그 차이를
    지우지 않으려고 사유도 등재된 문장으로 다시 고정한다.
    """
    verdict = _ask(repository, GROWTH)
    assert verdict.answer is ConditionResult.TRUE
    #: 등재된 사유 — 공식 텍스트를 읽었다는 것과, ① 이 그 상황을 스스로
    #: 전제한다는 것을 함께 적는다.
    assert "공식 텍스트 전문을 읽었고" in verdict.reason, verdict.reason
    assert "그 상황을 스스로 전제한다" in verdict.reason, verdict.reason


@requires_official_db
def test_c02_the_only_explicit_prohibition_is_the_token_rule(repository):
    """
    §5-2 — **명시적으로 금지된 카드.** 코퍼스에서 그것은 토큰뿐이다
    (``test_b01``). 룰북이 직접 답하고, 유도는 그것을 덮지 못한다.
    """
    from engine.effect.ruling import TOKEN_FORBIDDEN, token_facts

    facts = token_facts(12345, "테스트 토큰")
    fact = facts.answer_for(RuleQuestion.MAY_BE_SENT_TO_GRAVE)
    assert fact is not None and fact.answer is ConditionResult.FALSE
    assert fact.basis is RuleBasis.RULEBOOK
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE in TOKEN_FORBIDDEN

    #: 🔴 그리고 코퍼스의 토큰 가운데 묘지행 증거를 가진 카드는 **0장**이다 —
    #: 있었다면 유도와 룰북이 충돌했을 것이다.
    conflicting = [
        card.id
        for card in repository.all_cards()
        if "TOKEN" in set(card.type_names) and card.self_grave_text_evidence
    ]
    assert conflicting == [], conflicting


@requires_official_db
def test_c03_a_continuous_prohibition_on_the_board_stops_the_answer(repository):
    """§5-3 — 지속 효과가 적용 중이면 허가하지 않는다 (``test_b03`` 과 짝)."""
    assert _ask(repository, GROWTH, on_field=FORTRESS).answer is (
        ConditionResult.UNKNOWN
    )


@requires_official_db
def test_c04_a_redirect_on_the_board_stops_the_answer(repository):
    """
    §5-4 — 묘지 **대신 제외**되는 대체 효과. 결과 영역이 달라지므로
    ``TRUE`` 를 줄 수 없고, 이 계층은 그 대체를 실행하지도 못한다.

    🔴 **이동 불가와 대체 이동을 가른다** — 둘 다 ``UNKNOWN`` 이지만 이유가
    다르고, 상수가 다르다 (``test_b01`` 대 아래).
    """
    codes = set(repository.get(MACRO).script.effect_codes or ())
    assert "EFFECT_TO_GRAVE_REDIRECT" in codes
    assert "EFFECT_CANNOT_TO_GRAVE" not in codes
    #: 대체 도착지가 원본에 적혀 있다.
    assert "LOCATION_REMOVED" in (ROOT / f"c{MACRO}.lua").read_text("utf-8")

    blocked = _ask(repository, GROWTH, on_field=MACRO)
    assert blocked.answer is ConditionResult.UNKNOWN
    assert str(MACRO) in blocked.reason


@requires_official_db
def test_c05_a_card_outside_the_restriction_scope_is_not_punished(repository):
    """
    §5-5 — **제한 효과의 적용 대상이 아닌 카드.**

    차원요새 병기 자신은 그 상수를 가지고 있지만 자기 묘지행이 금지된 것이
    아니다. 그래서 답은 ``FALSE`` 가 아니라 ``UNKNOWN`` 이다 — 거짓 금지도
    만들지 않는다.
    """
    verdict = _ask(repository, FORTRESS)
    assert verdict.answer is ConditionResult.UNKNOWN
    assert verdict.answer is not ConditionResult.FALSE


@requires_official_db
def test_c06_a_card_with_no_definition_is_unknown(repository):
    """§5-6 — 카드 정의가 없으면 어떤 카드인지부터 알 수 없다."""
    game = GameState.create(repository, decks=([GROWTH] * 10, [FEATHERMAN] * 10))
    game.draw(MINE, 1)
    instance = game.player(MINE).hand[0].instance_id
    #: 상대 관점에서는 내 패가 가려져 있다.
    board = BoardRuling(
        GameStateView.from_state(game, viewer=THEIRS), OPERATION_RULINGS
    )
    verdict = board.explain(RuleQuestion.MAY_BE_SENT_TO_GRAVE, instance)
    assert verdict.answer is ConditionResult.UNKNOWN
    assert "보이지 않아" in verdict.reason


@requires_official_db
def test_c07_a_missing_script_never_becomes_a_permission(repository):
    """
    §5-7 — **Lua 가 없으면 허가하지 않는다.**

    스크립트 없는 카드가 코퍼스에 실제로 있고 (통상 몬스터 다수), 그 카드의
    신호는 ``None`` 이다. 유도는 거기서 침묵한다. 페더맨이 ``TRUE`` 를 받는
    것은 **룰북**이 답하기 때문이고 유도 때문이 아니다.
    """
    scriptless = [
        card.id
        for card in repository.all_cards()
        if card.self_grave_text_evidence is None
    ]
    assert len(scriptless) > 0
    for card_id in scriptless[:50]:
        view = CardDefinitionView.of(repository.get(card_id))
        assert self_grave_text_fact(view) is None, card_id

    #: 페더맨의 ``TRUE`` 는 유도가 아니다 — 근거가 룰북이다.
    verdict = _ask(repository, FEATHERMAN)
    assert verdict.answer is ConditionResult.TRUE
    assert "통상 몬스터" in verdict.reason
    assert SEND_TO_GRAVE_RULE not in verdict.reason


@requires_official_db
def test_c08_cost_and_effect_stay_separate_in_the_definition(repository):
    """§5-8 · §5-9 — 기르수와 어리석은 매장의 조작은 **효과**다. 비용이 없다."""
    for card_id in (GIRSU, BURIAL):
        definition = definition_registry().definition_for(EffectRef(card_id, 0))
        assert definition.cost.costs == (), card_id
        (operation,) = definition.operations
        assert operation.kind.name == "SEND_TO_GRAVE", card_id
        #: 🔴 ``gated`` 라서 판정을 거친다 — 그것이 이 Phase 가 연 관문이다.
        assert operation.gated is True, card_id


@requires_official_db
def test_c09_an_empty_deck_offers_nothing_and_invents_nothing(repository):
    """§5-10 — 덱에 적법한 카드가 없으면 후보가 0건이고 카드를 만들지 않는다."""
    game = GameState.create(
        repository, decks=([BURIAL] + [NO_EVIDENCE] * 39, [FEATHERMAN] * 20), seed=3
    )
    game.draw(MINE, 1)
    source = game.player(MINE).hand[0].instance_id
    definition = definition_registry().definition_for(EffectRef(BURIAL, 0))
    spec = definition.targets[0].spec
    granted = GameStateView.from_state(
        game, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(
            player=MINE, source=source, effect_ref=definition.effect_ref
        ),
    )
    #: 오르페골 코어는 몬스터가 아니다 — 어리석은 매장의 후보가 아니다.
    assert found.eligible == ()
    assert len(game.player(MINE).zone(Zone.DECK)) == 39


# ======================================================================
# D. 🔴 실제 Duel — 기르수가 끝까지 해결된다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_d01_girsu_resolves_and_the_card_moves(repository):
    """
    🔴 **수준 3.** 일반 소환 → 유발 발동 → 체인 해결 → 덱에서 묘지로.

    프로덕션 경로만 쓴다. 등록소 사본도, 임시 사실도 없다.
    """
    from tests.engine.test_deck_to_grave_blocker import (
        _girsu_board,
        _orcust_pool,
        _summon_girsu,
    )

    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    #: 앞쪽 넷은 패로 뽑힌다 — 증거 카드를 덱에 남기려면 그 뒤에 둔다.
    setup = _girsu_board(
        repository, deck_pool=others[:4] + [GROWTH] + others[4:]
    )
    duel = setup.duel
    source = _summon_girsu(duel)

    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))
    grave_before = len(duel.state.player(MINE).zone(Zone.GRAVE))

    found, chosen, activated, resolved, journal, granted = _resolve_deck_choice(
        duel.state, source, GIRSU, EffectRef(GIRSU, 0), lambda cid: cid == GROWTH
    )

    #: 후보 가운데 증거를 가진 카드는 **정확히 하나**다 — 나머지는 ``UNKNOWN``.
    board = BoardRuling(granted, OPERATION_RULINGS)
    answers = [
        board.explain(RuleQuestion.MAY_BE_SENT_TO_GRAVE, i).answer
        for i in found.eligible
    ]
    assert answers.count(ConditionResult.TRUE) == 1, answers.count(
        ConditionResult.TRUE
    )
    assert answers.count(ConditionResult.UNKNOWN) == len(answers) - 1

    assert activated.status.value == "activated"
    assert resolved.result.status.name == "RESOLVED", resolved.result.reason

    #: 🔴 판이 움직였다.
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before - 1
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before + 1
    moved = duel.state.find_instance(chosen)
    assert moved.zone is Zone.GRAVE
    #: **그 인스턴스**가 갔다 — 같은 이름의 다른 장이 아니다.
    assert moved.card_id == GROWTH


@pytest.mark.real_card
@requires_official_db
def test_d02_the_journal_records_the_move_and_the_shuffle(repository):
    """
    §11-10 — ``EventJournal`` 이 이동과 **셔플**을 함께 적는다.

    셔플은 룰북이 요구한다 — *"You must shuffle your Deck after any time you
    search it."* 덱을 들여다본 효과가 그것을 적지 않으면 기록이 규칙과
    어긋난다.
    """
    from tests.engine.test_deck_to_grave_blocker import (
        _girsu_board,
        _orcust_pool,
        _summon_girsu,
    )

    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    setup = _girsu_board(
        repository, deck_pool=others[:4] + [GROWTH] + others[4:]
    )
    duel = setup.duel
    source = _summon_girsu(duel)
    _, chosen, _, resolved, journal, _ = _resolve_deck_choice(
        duel.state, source, GIRSU, EffectRef(GIRSU, 0), lambda cid: cid == GROWTH
    )
    assert resolved.result.status.name == "RESOLVED"

    entries = [str(e) for e in journal]
    assert entries, "해결했는데 기록이 비었다"
    joined = " ".join(entries)
    assert "send_to_grave" in joined, entries
    assert "DECK" in joined and "GRAVE" in joined, entries
    assert "섞었다" in joined, entries
    #: 효과의 출처가 기록에 남는다.
    assert f"{GIRSU}" in joined, entries


@pytest.mark.real_card
@requires_official_db
def test_d03_the_duel_keeps_going_after_the_resolution(repository):
    """§6-9 — 해결 뒤에도 ``legal_actions`` 가 나온다. 판이 멈추지 않는다."""
    from tests.engine.test_deck_to_grave_blocker import (
        _girsu_board,
        _orcust_pool,
        _summon_girsu,
    )

    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    setup = _girsu_board(
        repository, deck_pool=others[:4] + [GROWTH] + others[4:]
    )
    duel = setup.duel
    source = _summon_girsu(duel)
    _, _, _, resolved, _, _ = _resolve_deck_choice(
        duel.state, source, GIRSU, EffectRef(GIRSU, 0), lambda cid: cid == GROWTH
    )
    assert resolved.result.status.name == "RESOLVED"

    #: 🔴 **빠른 효과 기회를 먼저 지난다** (보완5). 해결 뒤에도 양측이
    #: 지나가야 판이 열린다 (공식 Fast Effect Timing — box B · C). 보완5
    #: 전까지 이 줄은 해결 직후에 ``end_phase`` 가 올라 있을 것을 요구했다.
    pass_fast_window(duel)
    offered = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "end_phase" in offered, offered
    #: 일반 소환권은 이미 썼다 — 판 상태가 유지된다.
    assert "normal_summon" not in offered, offered


@pytest.mark.real_card
@requires_official_db
def test_d04_choosing_a_card_without_evidence_still_stops(repository):
    """
    🔴 **유도가 통째로 허가가 되지 않았다는 증거.**

    같은 효과 · 같은 판에서 **증거 없는 후보**를 고르면 발동은 되고 해결은
    ``UNCHECKED_RULES`` 에서 멈추며 **아무것도 움직이지 않는다.**
    """
    from tests.engine.test_deck_to_grave_blocker import (
        _girsu_board,
        _orcust_pool,
        _summon_girsu,
    )

    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    setup = _girsu_board(
        repository, deck_pool=others[:4] + [GROWTH] + others[4:]
    )
    duel = setup.duel
    source = _summon_girsu(duel)
    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))

    _, chosen, activated, resolved, journal, _ = _resolve_deck_choice(
        duel.state,
        source,
        GIRSU,
        EffectRef(GIRSU, 0),
        lambda cid: repository.get(cid).self_grave_text_evidence is not True,
    )
    assert activated.status.value == "activated"
    assert resolved.result.status.name == "UNCHECKED_RULES"
    assert "IsAbleToGrave" in resolved.result.reason
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before
    assert duel.state.find_instance(chosen).zone is Zone.DECK
    assert list(journal) == []


# ======================================================================
# E. 공통성 — 어리석은 매장이 같은 규칙으로 해결된다 (§7)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_e01_foolish_burial_resolves_by_the_same_rule(repository):
    """
    🔴 **기르수 전용이 아니다.** 어리석은 매장은 **카드 발동**이고
    (``activation_kind`` 이 ``None``) 기르수는 유발인데, 둘이 **같은 관문**을
    지나 같은 결과에 이른다.
    """
    game = GameState.create(
        repository,
        decks=([BURIAL] + [GROWTH] * 3 + [NO_EVIDENCE_MONSTER] * 36,
               [FEATHERMAN] * 20),
        seed=11,
    )
    game.draw(MINE, 1)
    source = game.player(MINE).hand[0].instance_id
    assert game.find_instance(source).card_id == BURIAL

    #: 발동 분류가 기르수와 **다르다** — 그래서 공통성의 증거가 된다.
    assert definition_registry().definition_for(
        EffectRef(BURIAL, 0)
    ).activation_kind is None
    assert definition_registry().definition_for(
        EffectRef(GIRSU, 0)
    ).activation_kind is not None

    deck_before = len(game.player(MINE).zone(Zone.DECK))
    _, chosen, activated, resolved, journal, _ = _resolve_deck_choice(
        game, source, BURIAL, EffectRef(BURIAL, 0), lambda cid: cid == GROWTH
    )
    assert activated.status.value == "activated"
    assert resolved.result.status.name == "RESOLVED", resolved.result.reason
    assert len(game.player(MINE).zone(Zone.DECK)) == deck_before - 1
    assert game.find_instance(chosen).zone is Zone.GRAVE
    assert any("send_to_grave" in str(e) for e in journal)


@pytest.mark.real_card
@requires_official_db
def test_e02_foolish_burial_also_stops_without_evidence(repository):
    """같은 카드가 증거 없는 몬스터를 고르면 멈춘다 — 규칙이 카드에 묶이지 않았다."""
    game = GameState.create(
        repository,
        decks=([BURIAL] + [NO_EVIDENCE_MONSTER] * 39, [FEATHERMAN] * 20),
        seed=11,
    )
    game.draw(MINE, 1)
    source = game.player(MINE).hand[0].instance_id
    deck_before = len(game.player(MINE).zone(Zone.DECK))
    _, chosen, activated, resolved, journal, _ = _resolve_deck_choice(
        game,
        source,
        BURIAL,
        EffectRef(BURIAL, 0),
        lambda cid: cid == NO_EVIDENCE_MONSTER,
    )
    assert activated.status.value == "activated"
    assert resolved.result.status.name == "UNCHECKED_RULES"
    assert len(game.player(MINE).zone(Zone.DECK)) == deck_before
    assert game.find_instance(chosen).zone is Zone.DECK
    assert list(journal) == []


# ======================================================================
# F. 유도가 **넓히지 않은** 것
# ======================================================================


@requires_official_db
def test_f01_the_other_four_questions_stay_unknown(repository):
    """
    🔴 **다섯 질문 공유 경계를 넘지 않았다** (6-W §4.1 이 경고한 것).

    같은 카드에 대해 묘지만 ``TRUE`` 이고 나머지 넷은 ``UNKNOWN`` 이다.
    """
    assert _ask(repository, GROWTH).answer is ConditionResult.TRUE
    for question in (
        RuleQuestion.MAY_BE_BANISHED,
        RuleQuestion.MAY_BE_RETURNED_TO_HAND,
        RuleQuestion.MAY_BE_RETURNED_TO_DECK,
        RuleQuestion.MAY_BE_DISCARDED,
    ):
        verdict = _ask(repository, GROWTH, question=question)
        assert verdict.answer is ConditionResult.UNKNOWN, (question, verdict)


def test_f02_the_derivation_never_answers_false():
    """
    유도는 **허가만** 한다. 금지는 등록소와 룰북의 몫이다.

    근거가 "그 카드 자신이 묘지로 가는 상황을 적었다" 이므로, 그것이 없다는
    사실에서 "갈 수 없다" 가 나오지 않는다 — 그 방향이 거짓 금지다.
    """
    source = (ROOT / "engine" / "effect" / "ruling.py").read_text("utf-8")
    body = source[source.index("def self_grave_text_fact") :]
    body = body[: body.index("\nDERIVED_FACTS")]
    assert "ConditionResult.TRUE" in body
    assert "ConditionResult.FALSE" not in body


@requires_official_db
def test_f03_the_registry_and_the_rulebook_still_come_first(repository):
    """
    순서가 **등록소 → 룰북 → 유도**다. 룰북이 그것을 요구한다 —
    *"If there is a discrepancy between the basic rules and a card's
    effect, the card effect takes precedence."*

    페더맨이 증거다: 등록소에 줄이 있고, 그 답의 근거가 룰북이며, 유도는
    불리지도 않는다 (신호가 ``None``).
    """
    assert FEATHERMAN in OPERATION_RULINGS
    declared = OPERATION_RULINGS.facts_for(FEATHERMAN).answer_for(
        RuleQuestion.MAY_BE_SENT_TO_GRAVE
    )
    assert declared is not None and declared.basis is RuleBasis.RULEBOOK
    assert _evidence(repository, FEATHERMAN) is None
    verdict = _ask(repository, FEATHERMAN)
    assert verdict.reason == declared.note


def test_f04_production_gained_no_card_id_branch():
    """
    🔴 **카드 ID · 카드명 기반 분기를 더하지 않았다** (§3).

    판정 계층이 보는 것은 상수 이름 둘과 관측에 실린 신호뿐이다.
    """
    source = (ROOT / "engine" / "effect" / "ruling.py").read_text("utf-8")
    for card_id in (GIRSU, GROWTH, FORTRESS, MACRO, BURIAL, NO_EVIDENCE):
        assert str(card_id) not in source, card_id
    #: 카드군 이름도 없다.
    for name in ("기르수", "오르페골", "성유물", "Girsu", "Orcust"):
        assert name not in source, name


# ======================================================================
# G. 🔴 새로 허가한 991장 전수 역검증 (6-U 와 같은 방식)
# ======================================================================
#: 룰북 ``Send to the Graveyard`` 가 이름을 댄 **행동**들과, 코퍼스가 더
#: 보여준 둘. 어구는 공식 텍스트를 읽기 위한 것이고 **판정의 입력이 아니다**
#: — 프로덕션은 스크립트 신호만 본다. 이 표는 그 신호가 가리킨 카드들이
#: 정말로 묘지에 가는 카드인지 **사람이 되짚는** 용도다.
GRAVE_GOING_PHRASES: tuple[tuple[str, str, str], ...] = (
    ("묘지로 보내짐", r"묘지(로|에)\s*(직접\s*)?보내", r"sent to the (Graveyard|GY)"),
    ("버려짐", r"묘지(로|에)\s*버려|버려졌|버려진", r"discarded"),
    ("파괴", r"파괴되", r"destroyed"),
    ("릴리스", r"릴리스", r"Tribut"),
    ("엑시즈 소재 제거", r"소재.{0,12}제거|제거되었을", r"detach"),
    ("필드에서 벗어남", r"필드에서\s*벗어", r"leaves the field"),
)


@requires_official_db
def test_g01_the_newly_permitted_population_is_measured(repository):
    """새로 허가된 카드 수를 고정한다. 숫자가 움직이면 여기서 드러난다."""
    newly = [c for c in repository.all_cards() if c.self_grave_text_evidence is True]
    assert len(newly) == 991, len(newly)
    assert sum(1 for c in newly if not c.is_extra_deck) == 818
    assert sum(1 for c in newly if c.is_extra_deck) == 173


@requires_official_db
def test_g02_every_newly_permitted_card_is_corroborated_by_its_text(repository):
    """
    🔴 **거짓 허가 0건** — 991장 전부가 공식 텍스트로 되짚어진다.

    6-U 가 4,028장에 한 것과 같은 역검증이다. 각 카드의 텍스트에 룰북이
    묘지행으로 규정한 행동 가운데 하나가 적혀 있다.
    """
    newly = [c for c in repository.all_cards() if c.self_grave_text_evidence is True]
    counts = {label: 0 for label, _, _ in GRAVE_GOING_PHRASES}
    unexplained = []
    for card in newly:
        ko, en = card.desc or "", card.desc_en or ""
        for label, ko_pattern, en_pattern in GRAVE_GOING_PHRASES:
            if re.search(ko_pattern, ko) or re.search(en_pattern, en):
                counts[label] += 1
                break
        else:
            unexplained.append((card.id, card.name))

    #: 🔴 설명되지 않는 카드가 **하나도 없다**.
    assert unexplained == [], unexplained
    #: 대부분이 직접 어구다 — 분포도 함께 고정한다.
    assert counts["묘지로 보내짐"] == 953, counts
    assert counts["버려짐"] == 33, counts
    assert counts["파괴"] == 3, counts
    assert counts["엑시즈 소재 제거"] == 2, counts
    assert sum(counts.values()) == len(newly)


@requires_official_db
def test_g03_no_prohibited_card_slipped_into_the_permission(repository):
    """🔴 **반대 방향** — 자기 묘지행을 금지하는 상수를 가진 카드가 섞이지 않았다."""
    newly = [c for c in repository.all_cards() if c.self_grave_text_evidence is True]
    for code in ("EFFECT_CANNOT_TO_GRAVE", "EFFECT_CANNOT_TO_GRAVE_AS_COST"):
        bad = [c.id for c in newly if code in (c.script.effect_codes or ())]
        assert bad == [], (code, bad)
    #: 토큰도 섞이지 않았다 — 룰북이 토큰에 ``FALSE`` 를 준다.
    assert [c.id for c in newly if "TOKEN" in set(c.type_names)] == []


@requires_official_db
def test_g04_a_redirect_carrier_may_still_go_to_the_grave_itself(repository):
    """
    🔴 **범위를 가른 자리.** 허가된 991장 가운데 둘이
    ``EFFECT_TO_GRAVE_REDIRECT`` 를 가진다. 그것은 모순이 아니다 — 그 상수가
    ``EFFECT_TYPE_FIELD`` + ``SetRange(LOCATION_MZONE)`` 이므로 **그 카드가
    필드에 있을 때 남을** 제외로 보내는 효과이고, 자기 묘지행을 막는 것이
    아니다.

    그리고 그 카드가 필드에 깔리면 훑기가 멈춘다 (``test_c04`` 와 같은
    경로) — 대체 효과를 무시하지 않는다는 뜻이다.
    """
    newly = [c for c in repository.all_cards() if c.self_grave_text_evidence is True]
    carriers = sorted(
        c.id
        for c in newly
        if "EFFECT_TO_GRAVE_REDIRECT" in (c.script.effect_codes or ())
    )
    assert carriers == [46502744, 79606837], carriers
    for card_id in carriers:
        lua = (ROOT / f"c{card_id}.lua").read_text("utf-8")
        head = lua[: lua.index("EFFECT_TO_GRAVE_REDIRECT")]
        #: 필드 효과다 — 자기 한 장에 걸린 것이 아니다.
        assert "EFFECT_TYPE_FIELD" in head, card_id
        #: 대체 도착지가 제외다.
        assert "LOCATION_REMOVED" in lua, card_id

    #: 🔴 대체 효과를 가진 카드는 **등록소에 없다** — 그래서 판에 깔리면
    #: ``restricts_others`` 기본값(참)이 살아 훑기가 멈춘다.
    redirecting = [
        c.id
        for c in repository.all_cards()
        if c.script is not None
        and (
            "EFFECT_TO_GRAVE_REDIRECT" in (c.script.effect_codes or ())
            or "EFFECT_TO_GRAVE_REDIRECT_CB" in (c.script.effect_codes or ())
        )
    ]
    assert len(redirecting) == 47, len(redirecting)
    assert [cid for cid in redirecting if cid in OPERATION_RULINGS] == []


@requires_official_db
def test_g05_the_verdict_distribution_changed_only_one_way(repository):
    """
    🔴 **답이 뒤집힌 카드가 0장이다.**

    유도는 ``UNKNOWN`` 이던 자리만 채운다. 이미 ``TRUE`` 나 ``FALSE`` 였던
    카드의 답을 바꾸지 않는다 — 그것이 "등록소와 룰북이 먼저" 의 결과다.
    """
    from engine.effect.ruling import rulebook_facts

    question = RuleQuestion.MAY_BE_SENT_TO_GRAVE
    flipped, newly_true, already = [], 0, 0
    for card in repository.all_cards():
        view = CardDefinitionView.of(card)
        prior = None
        declared = OPERATION_RULINGS.facts_for(card.id)
        if declared is not None:
            prior = declared.answer_for(question)
        if prior is None:
            book = rulebook_facts(view)
            if book is not None:
                prior = book.answer_for(question)
        derived = self_grave_text_fact(view)
        if prior is not None:
            already += 1
            if derived is not None and derived.answer is not prior.answer:
                flipped.append(card.id)
        elif derived is not None:
            newly_true += 1

    assert flipped == [], flipped
    #: 🔴 991 → 990 · 684 → 685 (Phase 6-AC). 한 장이 **파생에서 등재로**
    #: 옮겨 갔다 — 성유물－『성장』 이다. 합(1,675)은 그대로이고, 뒤집힌
    #: 카드는 여전히 **0장**이다: 등재가 파생과 **같은 답**을 적었다는 뜻이고
    #: 그것이 이 시험이 지키는 사실이다.
    assert newly_true == 990, newly_true
    assert already == 685, already
    assert newly_true + already == 1675
