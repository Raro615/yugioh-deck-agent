"""
Phase 6-AD 후속 ③ — **발동과 해결 사이에 상태가 변하는 한 실행.**

6-AD 는 이 검증을 **하지 못했다**고 적었다 (보고서 §13.4 의 B · C · E).
그때의 근거는 "체인에 응답으로 올릴 수 있는 등재 효과가 둘뿐이고 둘 다 패를
줄이지 않는다" 였고, 그래서 초기 상태가 다른 **두 판**을 비교하는 시험으로
대신했다. 그것은 "그때의 패에서 고른다" 를 재지 못한다.

이 파일은 **한 실행 안에서** 아래 순서를 만든다.

1. 『성장』 ② 의 발동이 적법하게 수락된다 (체인 링크 1).
2. **다른 효과가 체인 링크 2 로 쌓여 먼저 해결되고** 패 또는 필드를 바꾼다.
3. 『성장』 ② 가 **바뀐 상태를 다시 읽고** 해결된다.

무엇이 실제이고 무엇이 합성인가
--------------------------------
=========================================  =======================
기르수 ① · 『성장』 ② · 파키세팔로            🔴 **실제 카드 등재**
사건 (일반 소환 성공 · 묘지 도착)             🔴 **실제 기록**
발동 관문 셋 · 체인 · 해결 · 선택 · 실행      🔴 **실제 공용 경로**
링크 2 효과의 **유발 선언**                   **합성** (아래)
링크 2 효과의 **정의**(조작 · 후보 조건)       **합성** (아래)
=========================================  =======================

🔴 **합성인 것을 정확히 적는다.** 이 저장소의 어느 실제 카드도 "다른 카드가
묘지로 갔을 때" 를 선언하지 않는다 (실측: 이 판의 관측에서 컴파일된 유발
선언은 넷이고 전부 **자기 자신**의 사건이다). 그래서 링크 2 의 **선언**을
시험이 만든다 — :class:`_ChainResponse` 가 ``Duel.triggers`` 자리에
제안을 내놓고, 그 뒤는 듀얼이 전부 판정한다:

* ``_opportunity_is_open`` (지나간 시점 · 이미 쓴 기회)
* ``_trigger_actions`` (강제 · 임의 · 창 · 타이밍 · 정의 등재)
* ``_activation_gate`` (``ActionValidator`` · ``ActivationTimingChecker`` ·
  ``EffectActivator``)
* ``ChainResolver`` → ``EffectExecutor`` → 해결 시점 선택 → ``BoardRuling``
  관문 → 실제 이동

🔴 **허가를 주입하지 않는다.** 제안은 "발동할 수 있는 기회가 열렸다" 는
**입력**이고 (``Duel`` 은 카드 선언을 읽지 못하므로 조립 층이 값으로 넘긴다 —
ADR-007), 적법성은 위 네 계층이 답한다. 실제로 그 계층들이 합성 제안을
거절하는 것도 측정했다: ``EffectRef(…, 90)`` 은
``effect_ref_out_of_range`` 로 막혔다.

🔴 **판정 함수를 monkeypatch 하지 않고, 실행 중에 ``state.move`` 로 판을
바꾸지 않는다.** 시작 상태만 구성한다.

🔴 **합성 정의는 프로덕션 목록에 넣지 않는다.** 격리된 등록부를 만들어 그
판에만 꽂는다 (``duel_components(definitions=…, implementations=…)``) —
``tests/engine/test_followup_trigger_integration.py`` 가 세운 방식과 같다.
``EffectRef`` 의 ordinal 은 **주소**일 뿐이고, 그 블록의 실제 효과를
구현했다는 주장이 아니다 (프로덕션이 등재한 것은 ordinal 1 하나다).
"""

from __future__ import annotations

import pytest

from agent.choice import FirstPermittedChoice, PreferredCardChoice
from engine.action import PlayerAction, PlayerActionKind
from engine.archetype_compiler import compile_archetype_condition
from engine.condition import And, IsMonster, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec
from engine.duel import Duel, TurnStep, duel_components
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.library import EFFECT_LIBRARY, definition_registry
from engine.effect.operation import CardOperation, DrawOperation
from engine.effect.operation import SpecialSummonOperation
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.trigger import TriggerRequirement, TriggerWording, timing_events
from engine.validation import CODE_VALIDITY, ActionValidity, ValidationCode
from engine.vocabulary import ActivationKind, Phase, Position, Zone
from integration.autonomy import PolicyChooser, TriggerOffer, trigger_offers
from tests.conftest import requires_official_db

GIRSU = 69811710
WAND = 93920420
PACHY = 42009836
P0, P1 = 0, 1

pytestmark = requires_official_db

#: 🔴 **합성 효과의 주소.** 프로덕션은 ``EffectRef(WAND, 1)`` 하나만
#: 등재한다 — 아래 셋은 **비어 있는 ordinal** 이고, 그 블록의 실제 효과를
#: 구현한 것이 아니다 (파일 머리말).
SEND_REF = EffectRef(WAND, 4)
DRAW_REF = EffectRef(WAND, 3)
SUMMON_REF = EffectRef(WAND, 2)

_SYNTHETIC = (
    "🔴 **합성 — 실제 카드 구현이 아니다.** 이 정의는 "
    "tests/test_chain_state_change_between_links.py 가 '발동과 해결 사이에 "
    "상태가 변한다' 를 재기 위해 만든 것이고, 지원되는 조작만 쓴다. "
    "프로덕션 EFFECT_LIBRARY 에 들어가지 않는다."
)


def _hand_world_legacy_monster() -> ChoiceSpec:
    """자신 패의 **「성유물」 몬스터** 한 장 — 『성장』 ② 와 같은 후보 조건."""
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=And(
                (
                    IsMonster(),
                    compile_archetype_condition(("SET_WORLD_LEGACY",)).condition,
                )
            ),
        ),
        minimum=1,
        maximum=1,
    )


def _hand_monster() -> ChoiceSpec:
    """자신 패의 **몬스터** 한 장 (카드군을 묻지 않는다)."""
    return ChoiceSpec(
        source=CandidateSource(
            zones=frozenset({Zone.HAND}),
            owner=PlayerRef.CONTROLLER,
            require=IsMonster(),
        ),
        minimum=1,
        maximum=1,
    )


def _synthetic(ref, operations, choice=None) -> EffectDefinition:
    """합성 정의 하나. 선택은 **해결 시점**에 한다 (『성장』 ② 와 같다)."""
    return EffectDefinition(
        effect_ref=ref,
        source_card_id=ref.card_id,
        targets=(
            ()
            if choice is None
            else TargetBinding.single(
                TargetSpec.choosing(choice, chosen_at_resolution=True)
            )
        ),
        operations=operations,
        activation=None,
        activation_kind=ActivationKind.TRIGGER,
        provenance=EffectProvenance.hand_written(verified=True, note=_SYNTHETIC),
    )


#: 패의 「성유물」 몬스터 한 장을 묘지로 보낸다 (후보를 **없앤다**).
SEND_DEFINITION = _synthetic(
    SEND_REF,
    (CardOperation.send_to_grave(PRIMARY_TARGET, gated=True),),
    _hand_world_legacy_monster(),
)
#: 한 장 드로우한다 (후보를 **늘릴 수 있다**). 선택이 없다.
DRAW_DEFINITION = _synthetic(
    DRAW_REF, (DrawOperation(count=1, who=PlayerRef.CONTROLLER),)
)
#: 패의 몬스터 한 장을 특수 소환한다 (**칸을 채우고**, 금지를 **세운다**).
SUMMON_DEFINITION = _synthetic(
    SUMMON_REF, (SpecialSummonOperation(PRIMARY_TARGET),), _hand_monster()
)

SYNTHETIC_DEFINITIONS = (SEND_DEFINITION, DRAW_DEFINITION, SUMMON_DEFINITION)


class _ChainResponse:
    """
    ``Duel.triggers`` 자리에 꽂는 것 — **합성 선언 + 실제 사건.**

    🔴 **제안만 만든다.** 적법성은 듀얼의 네 계층이 답한다 (파일 머리말).
    사건은 **기록에서 그대로 펼친** 것이고 (``timing_events``) 지어내지
    않는다 — 그래서 ``consumed_events`` · ``timing_floor`` ·
    ``chain_floor`` · 타이밍 판정이 전부 실제 값으로 돈다.

    🔴 **상태를 들고 있지 않다** — :attr:`source` 는 시험이 "그 합성 효과를
    어느 개체가 들고 있는가" 를 적어 주는 칸이고, 그것이 없으면 제안을
    내놓지 않는다.
    """

    def __init__(self, repository, ref):
        self.repository = repository
        self.ref = ref
        self.source = None

    def offers(self, duel, seat):
        real = trigger_offers(duel, self.repository, seat)
        if seat != P0 or duel.journal is None or self.source is None:
            return real
        extra = []
        seen = set()
        for recorded in duel.journal:
            for event in timing_events(recorded):
                if event.point.value != "card_moved" or event in seen:
                    continue
                seen.add(event)
                extra.append(
                    TriggerOffer(
                        event=event,
                        effect_ref=self.ref,
                        source=self.source,
                        controller=P0,
                        requirement=TriggerRequirement.OPTIONAL,
                        reason="합성 선언 (시험 전용)",
                        wording=TriggerWording.IF,
                        event_sequence=recorded.sequence,
                    )
                )
        return (*real, *extra)


# ======================================================================
# 공용 — **시작 상태**만 만든다
# ======================================================================
def _board(
    repository,
    ref,
    *,
    hand,
    field=(GIRSU,),
    deck=(WAND,) + (GIRSU,) * 20,
    preferred=(),
):
    """
    한 실행의 시작 상태. 돌리는 중에는 ``Duel.apply`` 만 판을 바꾼다.

    ``field`` 에 놓는 카드는 **등재된 것만** 쓴다 — 모르는 앞면 카드가 하나
    있으면 ``BoardRuling._interference`` 가 판 전체의 답을 ``UNKNOWN`` 으로
    만들고, 그러면 이 파일이 재려는 축이 그 모름에 묻힌다.
    """
    state = GameState.create(
        repository,
        decks=(list(deck), [GIRSU] * 20),
        turn_player=P0,
        seed=0,
        shuffle=False,
    )
    field_ids = []
    for index, card_id in enumerate(field):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field_ids.append(instance.instance_id)
    hand_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    state.turn.turn_number = 3
    state.turn.set_phase(Phase.MAIN1)

    definitions = EffectDefinitionRegistry(
        (*definition_registry().definitions(), *SYNTHETIC_DEFINITIONS)
    )
    implementations = EffectImplementationRegistry()
    for entry in EFFECT_LIBRARY:
        if entry.executable:
            implementations.register(entry.effect_ref)
    for synthetic in SYNTHETIC_DEFINITIONS:
        implementations.register(synthetic.effect_ref)

    selector = FirstPermittedChoice()
    if preferred:
        selector = PreferredCardChoice(tuple(preferred), selector)
    chooser = PolicyChooser(selector, definitions)
    triggers = _ChainResponse(repository, ref)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        step=TurnStep.OPEN,
        first_player=P0,
        **duel_components(
            journal=EventJournal(),
            chooser=chooser,
            definitions=definitions,
            implementations=implementations,
        ),
        triggers=triggers,
    )
    return duel, chooser, triggers, hand_ids, field_ids


def _allowed(duel):
    duel.advance()
    return duel.legal_actions(duel.to_act)


def _activate(duel, ref):
    """그 효과의 **후보를 찾아** 적용한다. 행동을 만들지 않는다."""
    legal = _allowed(duel)
    found = [
        action
        for action in legal.allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == ref
    ]
    assert found, (
        ref,
        [(a.kind.value, str(a.effect_ref)) for a in legal.allowed],
        [(w.kind.value, w.code.value, w.reason[:120]) for w in legal.withheld],
    )
    return duel.apply(found[0])


def _settle(duel, limit=8):
    """양측이 지나가며 체인을 푼다. 패스도 ``legal_actions`` 를 지난다."""
    steps = []
    for _ in range(limit):
        if not duel.priority.is_open:
            break
        seat = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=seat)
        assert passing in duel.legal_actions(seat).allowed
        steps.append(duel.apply(passing))
    return steps


def _open_the_window(repository, ref, **board):
    """
    기르수 일반 소환 → 기르수 ① 해결 → **『성장』 ② 의 창**까지 간다.

    여기까지는 전부 **실제 카드**다. 합성 선언은 그 다음 걸음에서만 쓰인다.
    """
    duel, chooser, triggers, hand, field = _board(repository, ref, **board)
    girsu = next(
        i
        for i in hand
        if duel.state.find_instance(i).card_id == GIRSU
    )
    legal = _allowed(duel)
    summon = [
        a
        for a in legal.allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON and a.source == girsu
    ]
    assert summon, [(a.kind.value) for a in legal.allowed]
    assert duel.apply(summon[0]).accepted is True
    assert _activate(duel, EffectRef(GIRSU, 0)).accepted is True
    _settle(duel)
    assert duel.chain.is_empty
    #: 기르수 ① 이 덱에서 보낸 『성장』 — 합성 효과를 **그 개체가** 들고 있다.
    buried = next(
        card
        for card in duel.state.zone(P0, Zone.GRAVE)
        if card.card_id == WAND
    )
    triggers.source = buried.instance_id
    return duel, chooser, triggers, hand, field, buried.instance_id


def _hand_ids(duel, card_id=WAND):
    return [
        card.instance_id
        for card in duel.state.zone(P0, Zone.HAND)
        if card.card_id == card_id
    ]


def _mzone(duel):
    return [(c.card_id, c.instance_id) for c in duel.state.zone(P0, Zone.MZONE)]


def _record(chooser, ref):
    return next(
        (r for r in chooser.records if r.effect_ref == ref), None
    )


# ======================================================================
# M. 한 실행 안에서 상태가 변한다
# ======================================================================
@pytest.mark.real_card
def test_m00_the_two_links_really_stack_and_resolve_in_reverse(repository):
    """
    🔴 **먼저 배선을 고정한다** — 아래 시험들이 재는 순서가 실제로 일어난다.

    ① 『성장』 ② 가 링크 1 로 수락되고, ② 합성 효과가 링크 2 로 쌓이고,
    ③ 링크 2 가 **먼저** 해결된다 (룰북의 역순 해결).
    """
    duel, chooser, _t, hand, _f, _b = _open_the_window(
        repository, SEND_REF, hand=(GIRSU, WAND, WAND), preferred=(WAND,)
    )
    assert len(_hand_ids(duel)) == 2

    first = _activate(duel, EffectRef(WAND, 1))
    assert first.accepted is True
    assert len(duel.chain.links) == 1
    second = _activate(duel, SEND_REF)
    assert second.accepted is True
    assert len(duel.chain.links) == 2

    _settle(duel)
    assert duel.chain.is_empty
    #: 🔴 **합성이 먼저 물었다** — 기록의 순서가 해결 순서다.
    asked = [r.effect_ref for r in chooser.records]
    assert asked.index(SEND_REF) < asked.index(EffectRef(WAND, 1))


@pytest.mark.real_card
def test_m01_a_candidate_that_left_the_hand_is_not_summoned(repository):
    """
    §4-A — **발동 때 있던 개체가 해결 전에 패를 떠나고 다른 후보가 남는다.**

    → 남은 후보를 고르고 **떠난 개체를 소환하지 않는다.**
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository, SEND_REF, hand=(GIRSU, WAND, WAND), preferred=(WAND,)
    )
    at_activation = set(_hand_ids(duel))
    assert len(at_activation) == 2

    assert _activate(duel, EffectRef(WAND, 1)).accepted is True
    assert _activate(duel, SEND_REF).accepted is True
    _settle(duel)

    sent = _record(chooser, SEND_REF)
    summoned = _record(chooser, EffectRef(WAND, 1))
    assert sent is not None and summoned is not None
    #: ① 합성 효과는 발동 시점의 두 후보 중 하나를 보냈다.
    assert len(sent.chosen) == 1
    assert sent.chosen[0] in at_activation
    #: ② 『성장』 ② 는 **남은 하나**를 골랐다 — 떠난 개체가 아니다.
    assert len(summoned.chosen) == 1
    assert summoned.chosen[0] != sent.chosen[0]
    assert summoned.chosen[0] in at_activation
    #: ③ 해결 시점의 후보 목록이 **한 장**으로 줄어 있었다.
    assert len(summoned.offer.candidates) == 1
    assert summoned.offer.candidates[0].instance == summoned.chosen[0]
    #: ④ 판이 그대로 말한다 — 보낸 것은 묘지, 고른 것은 몬스터 존.
    assert (WAND, summoned.chosen[0]) in _mzone(duel)
    assert sent.chosen[0] in [
        c.instance_id for c in duel.state.zone(P0, Zone.GRAVE)
    ]


@pytest.mark.real_card
def test_m02_a_candidate_that_entered_the_hand_is_offered(repository):
    """
    §4-B — **발동 뒤 합법 후보가 패에 새로 들어오면 해결 시 후보에 든다.**

    합성 효과는 한 장 드로우한다 (선택이 없는 조작이다). 덱 맨 위를 『성장』
    으로 두었으므로 그 드로우가 **새 후보**를 만든다.
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository,
        DRAW_REF,
        hand=(GIRSU, WAND),
        #: 🔴 **덱을 전부 『성장』 으로 둔다.** 어느 쪽이 맨 위인지에 기대지
        #: 않으려는 것이다 — 뽑힌 한 장이 후보인 것이 이 시험의 전제다.
        deck=(WAND,) * 10,
        preferred=(WAND,),
    )
    at_activation = set(_hand_ids(duel))
    assert len(at_activation) == 1

    assert _activate(duel, EffectRef(WAND, 1)).accepted is True
    assert _activate(duel, DRAW_REF).accepted is True
    _settle(duel)

    summoned = _record(chooser, EffectRef(WAND, 1))
    assert summoned is not None
    offered = {c.instance for c in summoned.offer.candidates}
    #: ① 발동 시점에는 한 장이었는데 해결 시점에는 둘이다.
    assert len(offered) == 2
    #: ② 늘어난 하나는 **발동 뒤에 들어온** 개체다.
    fresh = offered - at_activation
    assert len(fresh) == 1
    #: ③ 그 개체도 **허가된** 후보다 — 목록에만 올린 것이 아니다.
    assert fresh <= {c.instance for c in summoned.offer.permitted}
    #: ④ 소환된 것은 그 둘 중 하나다.
    assert summoned.chosen[0] in offered


@pytest.mark.real_card
def test_m03_no_candidate_left_means_no_wrong_summon(repository):
    """
    §4-C — **해결 전에 후보가 전부 사라진다.**

    → 잘못된 소환이 일어나지 않고 결과가 정확히 기록된다.

    🔴 **규칙과 엔진의 차이를 적는다.** 공식 ``s.spop1`` 은
    ``if #g>0 then SpecialSummon`` 이므로 후보가 없으면 **효과가 해결되고
    아무 일도 일어나지 않는다.** 이 엔진은 선택의 최소 장수를 못 채운 것으로
    보아 **거절**을 적는다 (``too_few_selected``). 둘은 "잘못된 소환이 없다"
    에서 같고, "해결로 적는가 거절로 적는가" 에서 다르다 — 그 차이를
    숨기지 않고 여기서 고정한다 (보고서 §14.4 의 남은 한계).
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository, SEND_REF, hand=(GIRSU, WAND), preferred=(WAND,)
    )
    only = _hand_ids(duel)
    assert len(only) == 1

    assert _activate(duel, EffectRef(WAND, 1)).accepted is True
    assert _activate(duel, SEND_REF).accepted is True
    steps = _settle(duel)

    #: ① 후보가 하나도 남지 않았다.
    assert _hand_ids(duel) == []
    #: ② 특수 소환이 없다 — 필드에는 기르수 둘뿐이다 (시작 필드 하나 +
    #: 일반 소환 하나).
    assert [card_id for card_id, _ in _mzone(duel)] == [GIRSU, GIRSU]
    #: ③ 고르지 않았다는 사실이 기록에 남는다.
    summoned = _record(chooser, EffectRef(WAND, 1))
    assert summoned is not None
    assert summoned.chosen == ()
    assert summoned.offer.candidates == ()
    #: ④ 엔진이 **이유를 적고** 끝났다 — 조용히 성공으로 넘어가지 않았다.
    reasons = [s.reason for s in steps]
    assert any("해결하지 못했습니다" in r for r in reasons), reasons
    assert any("최소 1장" in r for r in reasons), reasons


@pytest.mark.real_card
def test_m04_a_full_zone_before_activation_is_an_activation_refusal(
    repository,
):
    """
    §4-D 의 **발동 전 검사 쪽** — 칸이 아예 없으면 발동이 서지 않는다.

    🔴 **두 자리를 가른다.** 이 시험은 *발동 전에* 칸이 없는 판이고, 그때는
    발동 조건(``ZoneHasFreeSlot``)이 **거짓**이므로 후보가 오르지 않는다.
    *체인 도중에* 칸이 차는 쪽이 §4-D 가 요구한 사례이고, 그것은 아래
    :func:`test_m05` 가 잰다.
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository,
        SUMMON_REF,
        hand=(GIRSU, WAND, WAND),
        field=(GIRSU, GIRSU, GIRSU, GIRSU),
        preferred=(WAND,),
    )
    #: 시작 필드 넷 + 일반 소환 하나 = **다섯 칸이 전부 찼다.** 아래 단언이
    #: 그 전제를 고정한다.
    assert len(_mzone(duel)) == 5
    legal = _allowed(duel)
    wand_actions = [
        a
        for a in legal.allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == EffectRef(WAND, 1)
    ]
    #: 🔴 칸이 없으면 **발동 조건이 거짓**이고, 그것이 규칙이다 — 이 자리는
    #: §4-D 가 아니라 발동 전 검사다 (아래 ``test_m05`` 가 §4-D 를 잰다).
    assert wand_actions == []


@pytest.mark.real_card
def test_m05_the_zone_filled_during_the_chain_is_not_overwritten(repository):
    """
    §4-D — **체인 도중에** 마지막 칸이 찬다.

    필드에 셋을 놓고 기르수를 일반 소환하면 넷이 차고 **한 칸이 남는다.**
    『성장』 ② 의 발동 조건은 그 한 칸으로 참이 되고, 합성 효과가 링크 2 로
    그 칸을 채운다.
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository,
        SUMMON_REF,
        hand=(GIRSU, WAND, WAND),
        field=(GIRSU, GIRSU, GIRSU),
        preferred=(WAND,),
    )
    assert len(_mzone(duel)) == 4

    assert _activate(duel, EffectRef(WAND, 1)).accepted is True
    assert _activate(duel, SUMMON_REF).accepted is True
    steps = _settle(duel)

    filled = _record(chooser, SUMMON_REF)
    assert filled is not None and filled.chosen
    #: ① 합성 효과가 마지막 칸을 채웠다 — 다섯 칸이 전부 찼다.
    assert len(_mzone(duel)) == 5
    #: ② 개체가 겹치지 않는다 — **덮어쓰기가 없다.**
    summoned_ids = [instance for _c, instance in _mzone(duel)]
    assert len(set(summoned_ids)) == 5
    #: ③ 『성장』 ② 는 고르는 자리에 닿지 못했다 — 해결 시점에 **빈 칸이
    #: 없다**는 것이 발동 조건의 재검사에서 걸린다.
    assert _record(chooser, EffectRef(WAND, 1)) is None
    reasons = [s.reason for s in steps]
    assert any(
        "93920420:e[1]" in r and "해결하지 못했습니다" in r for r in reasons
    ), reasons
    assert any("빈 칸" in r for r in reasons), reasons
    #: ④ 남은 『성장』 은 패에 그대로 있다 — 허위 성공이 없다.
    assert len(_hand_ids(duel)) == 1


@pytest.mark.real_card
def test_m06_a_prohibition_raised_during_the_chain_blocks_the_summon(
    repository,
):
    """
    §4-E — **해결 전에 파키세팔로의 금지가 적용된다.**

    → 『성장』 의 소환도 **공유 금지 판정**으로 막힌다.

    합성 효과가 패의 파키세팔로를 특수 소환한다 (그 카드 자신의 소환
    가능성은 ``OPERATION_RULINGS`` 에 근거와 함께 등재되어 있다). 그것이
    몬스터 존에 서면 ② 의 「서로 몬스터를 특수 소환할 수 없다」 가 걸린다.
    """
    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository, SUMMON_REF, hand=(GIRSU, WAND, PACHY), preferred=(PACHY,)
    )
    assert _activate(duel, EffectRef(WAND, 1)).accepted is True
    assert _activate(duel, SUMMON_REF).accepted is True
    steps = _settle(duel)

    raised = _record(chooser, SUMMON_REF)
    assert raised is not None and raised.chosen
    #: ① 파키세팔로가 앞면으로 몬스터 존에 섰다.
    assert PACHY in [card_id for card_id, _ in _mzone(duel)]
    #: ② **해결 시점에 다시 본다.** 금지가 걸린 뒤라 발동 조건이 거짓이고,
    #: 그 판정은 6-AD 가 더한 ``SpecialSummonPermitted`` — **링크 소환
    #: 거절과 같은 함수**다. 그래서 고르는 자리에 닿지도 못한다.
    assert _record(chooser, EffectRef(WAND, 1)) is None
    reasons = [s.reason for s in steps]
    assert any(
        "93920420:e[1]" in r and "해결하지 못했습니다" in r for r in reasons
    ), reasons
    assert any("특수 소환이 금지되지 않았다" in r for r in reasons), reasons
    #: ③ 소환되지 않았다 — 『성장』 은 패에 남는다.
    assert len(_hand_ids(duel)) == 1
    assert WAND not in [card_id for card_id, _ in _mzone(duel)]
    #: ④ 그리고 그 거절은 **확정 거부**다 (모름이 아니다) — 코드가 말한다.
    assert any(
        s.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE for s in steps
    ), [s.code.value for s in steps]
    assert all(
        CODE_VALIDITY[s.code] is not ActionValidity.UNKNOWN for s in steps
    )


@pytest.mark.real_card
def test_m07_the_change_happens_in_one_copy_only(repository):
    """
    §4-F — **한쪽에서만 상태 변화가 일어나고 다른 쪽이 오염되지 않는다.**

    창까지 간 판을 사본으로 갈라, **사본에서만** 두 링크를 쌓고 푼다.
    원본의 판 · 선택 기록 · 사용 횟수가 그대로여야 한다.
    """
    from agent.simulation import Simulator

    duel, chooser, _t, _h, _f, _b = _open_the_window(
        repository, SEND_REF, hand=(GIRSU, WAND, WAND), preferred=(WAND,)
    )
    before_hash = duel.state.state_hash()
    before_hand = sorted(i.value for i in _hand_ids(duel))
    before_records = len(chooser.records)
    before_uses = len(duel.state.uses)

    copy = Simulator(duel=duel)._fork()
    #: 사본도 **같은 후보**를 본다 — 배선 때문에 달라지지 않는다.
    assert [
        a.canonical_state() for a in duel.legal_actions(P0).allowed
    ] == [a.canonical_state() for a in copy.legal_actions(P0).allowed]

    assert _activate(copy, EffectRef(WAND, 1)).accepted is True
    assert _activate(copy, SEND_REF).accepted is True
    _settle(copy)

    #: ① 사본에서는 상태가 바뀌었다.
    assert len(_hand_ids(copy)) == 0
    assert WAND in [card_id for card_id, _ in _mzone(copy)]
    #: ② 원본은 한 글자도 바뀌지 않았다.
    assert duel.state.state_hash() == before_hash
    assert sorted(i.value for i in _hand_ids(duel)) == before_hand
    assert len(duel.state.uses) == before_uses
    assert [card_id for card_id, _ in _mzone(duel)] == [GIRSU, GIRSU]
    #: ③ 선택 기록도 새지 않는다 — 사본의 선택이 원본 목록에 없다.
    assert len(chooser.records) == before_records
