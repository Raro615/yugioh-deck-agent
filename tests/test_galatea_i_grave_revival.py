"""
Phase 6-BJ — **오르페골 갈라테아i ③ (묘지 소생) 을 실제 엔진으로 해결한다.**

이 파일이 지키는 것
-------------------
1. **효과가 등재되어 있고 모양이 스크립트와 같다** — 묘지에서 발동하고,
   비용은 묘지의 「오르페골」 1장 제외이고, 자기 자신은 비용이 될 수 없고,
   턴 제한은 ``{id,1}`` (그 카드명의 **이 효과** 기준) 이다.
2. **비용의 제외와 소생이 다른 사건이다** — 기록이 둘로 남는다.
3. **세 결과가 서로 다르다** — 처음부터 발동할 수 없다 / 적법하게 비용을
   낸 뒤 해결에서 소생하지 못했다 / 소생했다.
4. **소생 제한을 이력으로 넘는다** — 이 듀얼에서 정규 링크 소환을 거친
   기록이 있을 때만이고, 없으면 여전히 ``UNKNOWN`` 이다 (ADR-006).
5. **② 와 ③ 의 턴 제한이 섞이지 않는다** — 같은 턴에 ② 를 쓴 갈라테아i 가
   링크 소재가 되어 묘지로 가도 ③ 은 그대로 쓸 수 있다.
6. **바벨은 필드에서만 막는다** — 패에 가져온 바벨은 조건을 건드리지
   않는다.
7. **후속 링크가 엔진의 판정으로 열린다** — 소생한 갈라테아i 와 필드의
   갈라테아로 롱기르수가 **허용 후보**가 된다.

🔴 **고정 수순을 정답으로 넣지 않는다.** 구동기는 **그 자리의 허용 후보
에서** 행동을 찾고, 없으면 멈춘다. 특정 카드 번호에 가산점을 주거나 비용
카드를 고정하지 않는다 — 비용으로 무엇이 올라오는지도 엔진에게 묻는다.
"""

import pytest

from tests.conftest import requires_official_db

pytestmark = [requires_official_db, pytest.mark.real_card]

GIRSU = 69811710
CYMBAL_SKELETON = 21441617
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
BABEL = 90351981
ASH_BLOSSOM = 14558127

#: ``script.effects`` 의 서수 — ``e3`` 이 2번, ``e4`` 가 4번이다
#: (등록 순서: e1 · e2 · e3 · e3a · e4 · e4a).
GALATEA_I_TO_HAND = (GALATEA_I, 2)
GALATEA_I_REVIVE = (GALATEA_I, 4)


# ======================================================================
# 구동기
# ======================================================================
def _entry():
    from engine.effect.library import EFFECT_LIBRARY

    found = [
        one for one in EFFECT_LIBRARY
        if (one.definition.effect_ref.card_id,
            one.definition.effect_ref.ordinal) == GALATEA_I_REVIVE
    ]
    assert len(found) == 1, "갈라테아i e[4] 가 한 번 등재되어 있어야 합니다."
    return found[0]


def _to_galatea(repository):
    """
    사용자가 디스코드에서 본 판을 **허용 후보만으로** 만든다.

    기르수 일반 소환 → ① 스켈레촌을 묘지로 → ② 토큰 두 장 → 기르수로
    갈라테아i 링크 → 스켈레촌 ① 로 기르수 소생 → 갈라테아i + 기르수로
    갈라테아 링크. 그러면 묘지에 갈라테아i 와 기르수가 있다.
    """
    from tests.test_galatea_effect_extension import _is, _setup, _take

    duel = _setup(repository, prefer=(CYMBAL_SKELETON,)).duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(GIRSU, 2)), "기르수 ② 토큰")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87,
          "갈라테아i 링크 소환")
    _take(duel, _is("activate_effect", effect=(CYMBAL_SKELETON, 0)),
          "스켈레촌 ①")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] in (83, 84),
          "갈라테아 링크 소환")
    return duel


def _card_of(duel, instance):
    """
    개체 번호(정규 표현의 **정수**) 가 어느 카드인가.

    🔴 ``canonical_state`` 는 ``InstanceId`` 가 아니라 그 값을 싣는다 —
    그래서 객체끼리 견주면 언제나 어긋난다.
    """
    want = int(getattr(instance, "value", instance))
    for player in duel.state.players:
        for box in player.zones.values():
            for card in box.cards():
                if card.instance_id.value == want:
                    return card.card_id
    return None


def _revive_actions(duel):
    from tests.test_galatea_effect_extension import _advance_to_open

    legal = _advance_to_open(duel)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    return legal, hits


def _synthetic(repository, *, history: bool, free_slots: int = 5,
               babel_zone=None, in_grave=(GIRSU,)):
    """
    묘지의 갈라테아i 하나로 **판정만** 보는 합성 판.

    🔴 합성한 것은 **판**이고 카드 재정이 아니다 — ``OPERATION_RULINGS`` 도
    ``EFFECT_LIBRARY`` 도 손대지 않는다.
    """
    from agent.choice import FirstPermittedChoice
    from engine.duel import Duel, TurnStep, duel_components
    from engine.effect.journal import EventJournal
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Phase, Position, Zone
    from integration.autonomy import PolicyChooser, TriggerSource

    state = GameState.create(
        repository,
        decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=0,
        seed=1,
        shuffle=False,
    )
    galatea_i = state.create_instance(GALATEA_I, owner=0, zone=Zone.GRAVE)
    for card_id in in_grave:
        state.create_instance(card_id, owner=0, zone=Zone.GRAVE)
    for index in range(5 - free_slots):
        blocker = state.create_instance(GIRSU, owner=0, zone=Zone.MZONE)
        state.move(blocker, Zone.MZONE, to_player=0, index=index,
                   position=Position.FACEUP_ATTACK)
    if babel_zone is not None:
        babel = state.create_instance(BABEL, owner=0, zone=babel_zone)
        if babel_zone is Zone.FZONE:
            state.move(babel, Zone.FZONE, to_player=0, index=0,
                       position=Position.FACEUP)
    if history:
        state.summon_history.record(galatea_i.instance_id, "link")
    state.turn.turn_number = 1
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=0, phase=Phase.MAIN1),
        step=TurnStep.OPEN,
        first_player=0,
        **duel_components(journal=EventJournal(),
                          chooser=PolicyChooser(FirstPermittedChoice())),
        triggers=TriggerSource(repository),
    )
    return duel, galatea_i.instance_id


# ======================================================================
# 1. 등재된 모양이 스크립트와 같다
# ======================================================================
def test_a01_the_revive_effect_is_registered_from_the_grave():
    """``e4:SetRange(LOCATION_GRAVE)`` — 묘지 **하나**다."""
    from engine.vocabulary import ActivationKind, Zone

    definition = _entry().definition
    assert definition.activation_zones == frozenset({Zone.GRAVE})
    assert definition.activation_kind is ActivationKind.IGNITION
    #: ② 는 몬스터 존에서 발동한다 — 두 효과의 자리가 섞이지 않는다.
    assert definition.activation_zones != frozenset({Zone.MZONE, Zone.EMZONE})


def test_a02_the_cost_banishes_one_orcust_card_from_the_grave_not_itself():
    """
    ``s.spcostfilter`` — 「오르페골」 **카드**이고, 「**다른**」 이다.

    🔴 ``IsMonster()`` 를 적지 않았다는 것도 함께 지킨다 — 스크립트에
    없으므로 묘지의 바벨 · 클리막스도 비용이 된다.
    """
    from engine.cost import CostSemantics
    from engine.vocabulary import Zone

    costs = _entry().definition.cost.costs
    assert len(costs) == 1
    cost = costs[0]
    assert cost.semantics is CostSemantics.BANISH
    assert cost.zones == frozenset({Zone.GRAVE})
    assert cost.count == 1 and cost.upper_bound == 1
    assert cost.exclude_source is True
    assert cost.require is not None
    assert "IsMonster" not in repr(cost.require)


def test_a03_the_turn_limit_is_per_effect_not_per_card_name():
    """``SetCountLimit(1,{id,1})`` 과 ``SetCountLimit(1,id)`` 를 가른다."""
    from engine.effect.library import EFFECT_LIBRARY
    from engine.ids import EffectRef, InstanceId
    from engine.use_limit import LimitScope

    revive = _entry().definition
    assert revive.use_limit is not None
    assert revive.use_limit.scope is LimitScope.PER_EFFECT

    to_hand = next(
        one.definition for one in EFFECT_LIBRARY
        if (one.definition.effect_ref.card_id,
            one.definition.effect_ref.ordinal) == GALATEA_I_TO_HAND
    )
    assert to_hand.use_limit.scope is LimitScope.PER_CARD_NAME

    #: 🔴 **열쇠가 서로 다르다** — 같으면 ② 를 쓴 뒤 ③ 이 막힌다.
    instance = InstanceId(1)
    revive_key = revive.use_limit.key_for(
        0, EffectRef(GALATEA_I, 4), instance
    )
    to_hand_key = to_hand.use_limit.key_for(
        0, EffectRef(GALATEA_I, 2), instance
    )
    assert revive_key != to_hand_key


def test_a04_the_operation_summons_the_card_itself():
    """``s.spop`` 의 ``c`` 는 ``e:GetHandler()`` — 자기 참조다."""
    from engine.effect.operation import OperationKind
    from engine.effect.target import SELF_TARGET

    operations = _entry().definition.operations
    assert len(operations) == 1
    assert operations[0].kind is OperationKind.SPECIAL_SUMMON
    assert operations[0].target_ref == SELF_TARGET
    #: 대상 지정이 아니다 — ``targets`` 가 비어 있다.
    assert not _entry().definition.requires_target


def test_a05_the_resolution_condition_is_declared_empty():
    """
    ``s.spop`` 은 조건을 다시 보지 않는다 — ``None`` 과 **다른 값**이다.

    🔴 ``None`` 이면 실행기가 발동 조건 전체를 다시 보고, 그러면 "적법하게
    비용을 낸 뒤 자리가 사라졌다" 가 조건 거짓으로 적힌다.
    """
    definition = _entry().definition
    assert definition.resolution_condition is not None
    assert definition.resolution_condition.canonical_state() == (
        ("and", ())
    )


def test_a06_the_provenance_records_the_text_script_conflict():
    """
    🔴 **출처가 어긋나는 것을 덮어쓰지 않고 적는다.**

    스크립트는 ``LOCATION_MZONE|LOCATION_GRAVE`` 를 훑지만 공식 텍스트는
    양쪽 언어가 묘지만 적는다. 좁은 쪽을 골랐다는 사실이 근거에 있어야
    한다.
    """
    basis = _entry().definition.provenance.note
    assert "LOCATION_MZONE" in basis
    assert "묘지만" in basis
    assert "EnableReviveLimit" in basis
    #: 옮기지 못한 것이 적혀 있다.
    for missing in ("e4a", "IsAbleToRemoveAsCost", "SpElimFilter"):
        assert missing in basis


def test_a07_the_card_declares_it_may_be_special_summoned():
    """
    ``s.sptg`` 의 ``c:IsCanBeSpecialSummoned`` 가 묻는 질문 하나.

    🔴 그 답이 **소생 제한을 판정한 것은 아니다** — 근거가 그렇게 적어야
    한다.
    """
    from engine.condition import ConditionResult
    from engine.effect.library import OPERATION_RULINGS
    from engine.effect.ruling import RuleQuestion

    facts = OPERATION_RULINGS.facts_for(GALATEA_I)
    assert facts is not None
    answer = facts.answers[RuleQuestion.MAY_BE_SPECIAL_SUMMONED]
    assert answer.answer is ConditionResult.TRUE
    assert "소생 제한을 판정한 것은 아니다" in answer.note
    assert "summon_history" in answer.note


def test_a08_the_library_note_no_longer_says_e4_is_unregistered():
    """🔴 거짓이 된 설명을 그대로 두지 않는다 (6-BI 가 같은 일을 했다)."""
    from engine.effect.library import OPERATION_RULINGS

    note = OPERATION_RULINGS.facts_for(GALATEA_I).restriction_note
    assert "Phase 6-BJ 가 e4 를 등재했다" in note
    assert "e3a · e4a" in note


# ======================================================================
# 2. 사용자가 본 판에서 후보가 오른다
# ======================================================================
def test_b01_the_revive_is_a_candidate_on_the_board_the_user_saw(repository):
    """
    🔴 **이것이 6-BJ §1 의 질문이다.** 6-BI 까지 이 자리에는 후보가 없었다
    (등재되지 않았으므로 보류 목록에도 나타나지 않았다).
    """
    duel = _to_galatea(repository)
    legal, hits = _revive_actions(duel)
    assert hits, (
        "갈라테아i ③ 이 허용 후보에 없습니다: "
        + "; ".join(str(a.canonical_state()) for a in legal.allowed)
        + " / 보류: "
        + "; ".join(f"{w.kind.value}: {w.reason}" for w in legal.withheld)
    )


def test_b02_the_only_cost_candidate_is_the_other_orcust_in_the_grave(
    repository,
):
    """
    🔴 **자기 자신이 비용 후보가 아니다.** 그 판의 묘지에는 갈라테아i 와
    기르수뿐이므로, 비용 후보가 기르수 하나여야 한다 — 「다른」 이 지켜
    지면 후보가 하나, 지켜지지 않으면 둘이다.

    🔴 **어느 카드를 골라야 한다고 적지 않는다** — 엔진이 낸 후보를 읽고
    그 안에 자신이 없음을 본다.
    """
    duel = _to_galatea(repository)
    _, hits = _revive_actions(duel)
    paid = set()
    for action in hits:
        for instance in action.cost_cards:
            found = duel.state.find_instance(instance)
            paid.add(found.card_id)
    assert GALATEA_I not in paid
    assert paid == {GIRSU}


def test_b03_the_cost_banish_and_the_summon_are_separate_events(repository):
    """🔴 **두 사건이다.** 하나로 적으면 둘을 영영 가를 수 없다."""
    from engine.vocabulary import Zone
    from tests.test_galatea_effect_extension import _is, _take

    duel = _to_galatea(repository)
    before = len(duel.journal.events)
    _take(duel, _is("activate_effect", effect=GALATEA_I_REVIVE), "③ 소생")
    fresh = duel.journal.events[before:]
    assert len(fresh) == 2, [one.describe_ko() for one in fresh]
    assert "제외" in fresh[0].describe_ko()
    assert "소환" in fresh[1].describe_ko()

    mzone = [c.card_id for c in duel.state.zone(0, Zone.MZONE).cards()]
    removed = [c.card_id for c in duel.state.zone(0, Zone.REMOVED).cards()]
    assert GALATEA_I in mzone
    assert GIRSU in removed


def test_b04_the_follow_up_link_is_offered_by_the_engines_own_rules(
    repository,
):
    """
    소생한 갈라테아i (링크 1) 와 필드의 갈라테아 (링크 2) 로 롱기르수
    (링크 3) 가 **허용 후보**가 되는가.

    🔴 **가설을 판정으로 바꾸지 않는다** — 소재 조건은
    :mod:`engine.link_rules` 가 보고, 이 시험은 그 답을 읽는다.
    """
    from tests.test_galatea_effect_extension import (
        _advance_to_open, _is, _take,
    )

    duel = _to_galatea(repository)
    _take(duel, _is("activate_effect", effect=GALATEA_I_REVIVE), "③ 소생")
    legal = _advance_to_open(duel)
    links = []
    for action in legal.allowed:
        key = action.canonical_state()
        if key[0] != "link_summon" or key[2] is None:
            continue
        if _card_of(duel, key[2]) == LONGIRSU:
            links.append((action, key))
    assert links, (
        "롱기르수가 허용 후보에 없습니다: "
        + "; ".join(str(a.canonical_state()) for a in legal.allowed)
    )
    materials = set()
    for _, key in links:
        for instance in key[6]:
            materials.add(_card_of(duel, instance))
    assert materials == {GALATEA, GALATEA_I}


def test_b05_using_the_search_effect_does_not_spend_the_revive(repository):
    """
    🔴 **이번 요청의 핵심 하나.** 같은 턴에 ② 를 쓴 갈라테아i 가 링크
    소재가 되어 묘지로 간 뒤에도 ③ 을 쓸 수 있어야 한다.
    """
    from tests.test_galatea_effect_extension import _is, _setup, _take

    duel = _setup(repository, prefer=(CYMBAL_SKELETON,)).duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(GIRSU, 2)), "기르수 ② 토큰")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87, "갈라테아i 링크")
    #: **먼저 ② 를 쓴다** — 카드명 기준 1턴 1번을 소모한다.
    _take(duel, _is("activate_effect", effect=GALATEA_I_TO_HAND), "② 서치")
    _take(duel, _is("activate_effect", effect=(CYMBAL_SKELETON, 0)), "스켈레촌 ①")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] in (83, 84),
          "갈라테아 링크")

    legal, hits = _revive_actions(duel)
    assert hits, (
        "② 를 쓴 갈라테아i 의 ③ 이 막혔습니다: "
        + "; ".join(f"{w.kind.value}: {w.reason}" for w in legal.withheld)
    )


def test_b06_the_revive_can_only_be_used_once_per_turn(repository):
    """``SetCountLimit(1,{id,1})`` — 두 번째는 없다."""
    from tests.test_galatea_effect_extension import _is, _take

    duel = _to_galatea(repository)
    _take(duel, _is("activate_effect", effect=GALATEA_I_REVIVE), "③ 소생")
    #: 소생한 갈라테아i 는 이제 몬스터 존에 있으므로 발동 자리부터 틀리고,
    #: 그 사실이 보류 이유에 적힌다 — 턴 제한과 **다른 이유**다.
    _, hits = _revive_actions(duel)
    assert not hits


# ======================================================================
# 3. 세 결과가 서로 다르다
# ======================================================================
def test_c01_no_free_monster_zone_means_it_cannot_be_activated_at_all(
    repository,
):
    """
    ``Duel.GetMZoneCount(tp,c)>0`` — 빈 칸이 없으면 **발동 자체가 없다.**

    🔴 그때 비용이 치러지지 않는 것도 함께 지킨다.
    """
    from engine.vocabulary import Zone

    duel, _ = _synthetic(repository, history=True, free_slots=0)
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert not hits
    said = [w.reason for w in legal.withheld if str(GALATEA_I) in w.reason]
    assert any("발동 조건이 거짓" in one and "빈 칸" in one for one in said), said
    #: 비용은 치러지지 않았다 — 제외 구역이 비어 있다.
    assert not list(duel.state.zone(0, Zone.REMOVED).cards())
    assert not duel.journal.events


def test_c02_without_a_summon_record_the_cost_is_paid_and_the_revive_fails(
    repository,
):
    """
    🔴 **적법하게 비용을 낸 뒤 해결에서 소생하지 못하는 결과**가 따로
    있어야 한다 — 그리고 그 이유가 소생 제한이라고 말해야 한다.

    이것은 **공식보다 좁다**: 공식은 ``s.sptg`` 가 발동 시점에
    ``IsCanBeSpecialSummoned`` 를 묻기 때문에 애초에 발동할 수 없다. 이
    저장소는 그 답이 ``UNKNOWN`` 이고 (``ADR-006``) 모름을 거절로도
    허가로도 바꾸지 않으므로, 발동은 되고 해결이 멈춘다.
    """
    from deck.opening import _settle_chain
    from engine.validation import ValidationCode
    from engine.vocabulary import Zone

    duel, _ = _synthetic(repository, history=False)
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert hits
    assert duel.apply(hits[0]).accepted
    settled, resolved = _settle_chain(duel, lambda legal, seat=None: ())
    assert resolved is False
    assert settled.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "정규 소환" in settled.reason
    assert "소환된 기록이 없습니다" in settled.reason
    #: 비용은 치러졌고 (ADR-008 — 되돌리지 않는다) 소생은 없다.
    assert [c.card_id for c in duel.state.zone(0, Zone.REMOVED).cards()] == [
        GIRSU
    ]
    assert GALATEA_I in [
        c.card_id for c in duel.state.zone(0, Zone.GRAVE).cards()
    ]
    assert not list(duel.state.zone(0, Zone.MZONE).cards())


def test_c03_with_a_link_summon_record_the_revive_resolves(repository):
    """같은 판 · 같은 비용인데 **이력 하나**로 결과가 갈린다."""
    from deck.opening import _settle_chain
    from engine.validation import ValidationCode
    from engine.vocabulary import Zone

    duel, _ = _synthetic(repository, history=True)
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert hits
    assert duel.apply(hits[0]).accepted
    settled, resolved = _settle_chain(duel, lambda legal, seat=None: ())
    assert resolved is True
    assert settled.code is ValidationCode.OK
    assert [c.card_id for c in duel.state.zone(0, Zone.MZONE).cards()] == [
        GALATEA_I
    ]


def test_c04_an_effect_special_summon_does_not_count_as_a_procedure(
    repository,
):
    """
    🔴 **다른 카드의 효과로 특수 소환된 것은 「정규 소환」 이 아니다.**

    ``PROCEDURE_SUMMON_KINDS`` 에 :attr:`SummonKind.SPECIAL` 이 없다는
    사실을 판에서 확인한다 — 이력이 ``special`` 하나면 여전히 막힌다.
    """
    from deck.opening import _settle_chain
    from engine.validation import ValidationCode

    duel, instance = _synthetic(repository, history=False)
    duel.state.summon_history.record(instance, "special")
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert hits
    assert duel.apply(hits[0]).accepted
    settled, resolved = _settle_chain(duel, lambda legal, seat=None: ())
    assert resolved is False
    assert settled.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "그 카드의 절차가 아닙니다" in settled.reason


def test_c05_no_other_orcust_in_the_grave_means_no_candidate(repository):
    """비용 후보가 없으면 발동 후보도 없다 — 자기 자신은 세지 않는다."""
    duel, _ = _synthetic(repository, history=True, in_grave=(ASH_BLOSSOM,))
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert not hits


# ======================================================================
# 4. 바벨 — 필드와 패를 가른다
# ======================================================================
def test_d01_babel_face_up_in_the_field_zone_blocks_the_revive(repository):
    """``aux.NOT(s.babelcon)`` — 이 저장소가 읽을 수 있는 범위다."""
    from engine.vocabulary import Zone

    duel, _ = _synthetic(repository, history=True, babel_zone=Zone.FZONE)
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert not hits
    said = [w.reason for w in legal.withheld if str(GALATEA_I) in w.reason]
    assert any(str(BABEL) in one for one in said), said


def test_d02_babel_in_hand_does_not_block_the_revive(repository):
    """
    🔴 **② 가 패에 가져온 바벨은 적용 중이 아니다.** 적용은 필드 존에
    앞면으로 놓인 뒤 시작하고, 구현된 타이밍 범위가 정확히 그 한 줄이다.
    """
    from engine.vocabulary import Zone

    duel, _ = _synthetic(repository, history=True, babel_zone=Zone.HAND)
    legal = duel.legal_actions(0)
    hits = [
        action for action in legal.allowed
        if action.canonical_state()[0] == "activate_effect"
        and action.canonical_state()[4] == GALATEA_I_REVIVE
    ]
    assert hits


# ======================================================================
# 5. 소환 이력 — 적는 자리와 복제
# ======================================================================
def test_e01_the_registry_records_only_after_the_landing_is_verified(
    repository,
):
    """
    🔴 **틀린 기록은 없는 것보다 나쁘다.** 놓을 칸이 없어 절차가 멈추면
    이력도 남지 않아야 한다.
    """
    from engine.action import PlayerAction, PlayerActionKind
    from engine.special_summon import SpecialSummonError, SpecialSummonExecutor
    from engine.vocabulary import Position, Zone
    from engine.state.game_state import GameState

    state = GameState.create(
        repository,
        decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=0,
        seed=1,
        shuffle=False,
    )
    for index in range(5):
        blocker = state.create_instance(GIRSU, owner=0, zone=Zone.MZONE)
        state.move(blocker, Zone.MZONE, to_player=0, index=index,
                   position=Position.FACEUP_ATTACK)
    waiting = state.create_instance(GIRSU, owner=0, zone=Zone.GRAVE)
    action = PlayerAction(
        kind=PlayerActionKind.SPECIAL_SUMMON,
        actor=0,
        source=waiting.instance_id,
    )
    with pytest.raises(SpecialSummonError):
        SpecialSummonExecutor().apply(state, action)
    assert state.summon_history.kinds(waiting.instance_id) == ()


def test_e02_the_registry_is_copied_with_the_state(repository):
    """🔴 복제가 따라가지 않으면 탐색의 가지에서 소생이 사라진다."""
    from engine.state.game_state import GameState
    from engine.vocabulary import Zone

    state = GameState.create(
        repository,
        decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=0,
        seed=1,
        shuffle=False,
    )
    instance = state.create_instance(GALATEA_I, owner=0, zone=Zone.GRAVE)
    state.summon_history.record(instance.instance_id, "link")
    for copy in (state.clone(), state.project()):
        assert copy.summon_history.kinds(instance.instance_id) == ("link",)
        copy.summon_history.record(instance.instance_id, "special")
        assert state.summon_history.kinds(instance.instance_id) == ("link",)


def test_e03_a_real_link_summon_writes_the_record(repository):
    """기르수로 갈라테아i 를 링크 소환하면 그 사실이 적힌다."""
    from tests.test_galatea_effect_extension import _is, _setup, _take

    duel = _setup(repository, prefer=(CYMBAL_SKELETON,)).duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 87, "갈라테아i 링크")
    from engine.ids import InstanceId

    assert duel.state.summon_history.kinds(InstanceId(87)) == ("link",)
    #: 일반 소환도 적힌다 — 다만 소생 제한의 "거쳤다" 에는 쓰이지 않는다.
    assert duel.state.summon_history.kinds(InstanceId(75)) == ("normal",)


def test_e04_the_procedure_table_excludes_plain_special_summons():
    """🔴 두 표가 **다른 질문**이다 (``SPECIAL_SUMMON_KINDS`` 와 가른다)."""
    from engine.effect.delta import (
        PROCEDURE_SUMMON_KINDS,
        SPECIAL_SUMMON_KINDS,
        SummonKind,
    )

    assert SummonKind.LINK in PROCEDURE_SUMMON_KINDS
    assert SummonKind.SPECIAL not in PROCEDURE_SUMMON_KINDS
    assert SummonKind.NORMAL not in PROCEDURE_SUMMON_KINDS
    assert SummonKind.SPECIAL in SPECIAL_SUMMON_KINDS
