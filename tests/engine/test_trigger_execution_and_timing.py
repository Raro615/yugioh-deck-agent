"""
Phase 6-AB — **유발 실행 · 타이밍의 네 BLOCKER.**

6-AA 는 강제 · 임의의 근거와 기회의 수명을 세웠지만 넷을 남겼다.

    A. **판정이 후보 생성에만 있었다.** ``UNKNOWN`` 과 지나간 기회는
       ``legal_actions`` 에서만 걸러졌고, 발동 관문 자신은 ``valid/ok`` 를
       돌려주었다 (실측). 막는 것은 ``apply`` 앞의 "후보 목록에 있는가"
       하나뿐이었다 — **목록에 없다는 이유만으로** 안전한 구조다.
    B. **기회가 페이즈 안에서 끝나지 않았다.** 닫는 근거가 페이즈 경계
       하나뿐이어서, 사건 뒤에 다른 일이 일어나도 기회가 남았다. 그때
       6-AA 는 ``BLOCKER-6AA-2`` 로 적고 **근거 없는 일괄 규칙을 만들지
       않았다** ("다음 행동이면 만료").
    C. **강제 보장이 ``END_PHASE`` 한 자리였다.** 일반 행동과 ``PASS`` 로는
       그냥 넘어갔다.
    D. **사본이 역사를 잃었다.** ``_fork`` 가 기록하지 않는 한 벌로 바꿔
       끼우므로 (``journal=False``) 사본의 ``legal_actions`` 가 원본과 다른
       답을 냈다 — 실측 **원본 5 · 사본 4**.

🔴 **B 를 푼 것은 새 규칙이 아니라 찾은 근거다.** 공식 재정이 어휘로 가른다 —
「때」 효과는 그 사건이 *마지막에 일어난 일*이어야 하고, 「경우」 효과는
그렇지 않다. 출처는 ``core.card_model.Card.activation_wording_text`` 의
설명에 적었다. 그래서 6-AA 가 "한계" 로 고정한 기르수의 동작은 **결함이
아니었다**: 기르수의 텍스트는 「경우에 발동」 이고, 규칙이 그 기회를 남긴다.

네 군으로 나눈다.

================  ==================================================
A. 공유 판정        후보 생성과 직접 실행이 같은 판정을 쓰는가
B. 어휘와 수명      「때 / 경우」 가 기회를 언제 닫는가
C. 강제 보장        강제 유발을 무엇으로도 넘길 수 없는가
D. 사본             사본이 원본과 같은 후보를 보고, 새지 않는가
================  ==================================================

🔴 **실제 카드와 합성 구조 시험을 가른다.** 실행 등재된 유발 효과는 기르수
하나이고 (6-Z ``test_c09``) 그것은 **임의 · 「경우」** 다 (실측:
``test_b01``). 그래서 **강제**와 **「때」** 의 처리는 실제 카드로 돌릴 수
없고, 판정값 하나만 바꿔 끼운 합성 제안으로 구조를 센다. 그 시험들은 이름에
``synthetic`` 을 달고, 실제 카드에서 실행됐다고 적지 않는다.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import DeclineChoice, FirstPermittedChoice
from agent.simulation import Simulator, SimulationStatus
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidity
from engine.duel import (
    MANDATORY_TRIGGER_UNPLAYABLE,
    TRIGGER_REQUIREMENT_MISSING,
    TRIGGER_WORDING_MISSING,
    Duel,
)
from engine.ids import EffectRef
from engine.trigger import TriggerRequirement, TriggerWording
from engine.trigger_compiler import TEXT_IF, TEXT_WHEN, wording_from
from engine.vocabulary import Phase

from integration.autonomy import PolicyChooser, TriggerSource
from tests.conftest import requires_official_db
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    MINE,
    THEIRS,
    _board,
    _settle,
    _source,
    _summon,
    _trigger_action,
)


# ======================================================================
# 공용 도구
# ======================================================================
class _Replaced:
    """
    🔴 **합성 — 판정값만 바꿔 끼운다.**

    실제 :class:`~integration.autonomy.TriggerSource` 를 그대로 쓰고,
    돌려받은 제안의 ``requirement`` · ``wording`` 만 갈아 끼운다. 사건 ·
    사건 번호 · 카드 개체 · 효과는 **전부 실제 값**이고, 관문도 엔진의 것
    그대로다.

    허가 · 비용 · 최종 상태를 우회 주입하는 것이 **아니다** — 바꾸는 것은
    6-AA · 6-AB 가 새로 판정하기 시작한 그 두 값뿐이다.
    """

    def __init__(self, repository, **replacements):
        self._inner = TriggerSource(repository)
        self._replacements = replacements

    def offers(self, duel, seat: int):
        return tuple(
            dataclasses.replace(offer, **self._replacements)
            for offer in self._inner.offers(duel, seat)
        )


def _wired(duel, repository, **replacements):
    """그 판의 유발 원천을 바꿔 끼운 사본."""
    return dataclasses.replace(
        duel, triggers=_Replaced(repository, **replacements)
    )


def _other_action(duel, *, seat: int = MINE):
    """유발 발동이 **아닌** 행동 하나. 없으면 ``None``."""
    return next(
        (
            a
            for a in duel.legal_actions(seat).allowed
            if a.kind is not PlayerActionKind.ACTIVATE_EFFECT
            and a.kind is not PlayerActionKind.PASS
        ),
        None,
    )


def _withheld_for(duel, seat: int, missing: str):
    """그 ``missing`` 을 적은 보류들."""
    return [
        w for w in duel.legal_actions(seat).withheld if w.missing == missing
    ]


# ======================================================================
# A. 공유 판정 — 후보 생성과 직접 실행이 같은 판정을 쓰는가
# ======================================================================


@requires_official_db
def test_a01_the_gate_itself_refuses_an_unknown_trigger(repository):
    """
    🔴 **관문 자신이 거절한다** — 후보 목록에 없다는 이유에 기대지 않는다.

    6-AA 의 구조에서는 ``UNKNOWN`` 유발의 발동을 관문에 직접 물으면
    ``valid`` 가 나왔다 (실측). 그래서 ``legal_actions`` 를 지나지 않고
    만든 행동이 관문을 통과했다.

    지금은 **같은 판정이 관문 안에** 있다: ``activation_validator`` 가
    ``_offer_is_activatable`` 로 ``event_backed`` 를 만들고, 그 검증기를
    후보 생성과 ``_apply_activation`` 이 함께 쓴다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    #: 실제 유발 하나가 열려 있다 — 바꿔 끼우기 전에 확인한다.
    assert _trigger_action(setup.duel) is not None

    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.UNKNOWN
    )
    offers = duel._trigger_offers(MINE)
    assert len(offers) == 1, "합성이 제안 자체를 없애면 아무것도 재지 않는다"

    candidate = PlayerAction.activate_effect(
        actor=MINE, source=offers[0].source, effect_ref=offers[0].effect_ref
    )
    #: 🔴 후보 목록에 없고 — 그것은 6-AA 도 했다.
    assert candidate not in duel.legal_actions(MINE).allowed
    #: 🔴 **그리고 관문 자신이 열지 않는다** — 이것이 6-AB 가 더한 것이다.
    validator = duel.activation_validator(MINE)
    assert (validator.event_backed or frozenset()) == frozenset()


@requires_official_db
def test_a02_a_directly_submitted_unknown_trigger_is_refused(repository):
    """
    🔴 **``Duel.apply`` 에 직접 넣어도 거절된다** (BLOCKER-6AB-A).

    ``legal_actions`` 를 거치지 않고 만든 행동이다. 거절 사유가 "모른다"
    (``RULE_NOT_IMPLEMENTED`` 계열) 로 나와야 한다 — "규칙이 금지한다" 와
    **다른 사실**이기 때문이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.UNKNOWN
    )
    offers = duel._trigger_offers(MINE)
    candidate = PlayerAction.activate_effect(
        actor=MINE, source=offers[0].source, effect_ref=offers[0].effect_ref
    )

    step = duel.apply(candidate)
    assert step.accepted is False
    assert step.code is not None


@requires_official_db
def test_a03_a_refused_submission_changes_nothing(repository):
    """
    🔴 **거절된 요청이 판 · 체인 · 우선권 · 소비를 바꾸지 않는다.**

    세 가지를 넣어 본다 — 모름인 유발 · 사건이 없는 효과 번호 · 다른 개체.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.UNKNOWN
    )
    offers = duel._trigger_offers(MINE)
    source = offers[0].source

    before = (
        duel.state.state_hash(),
        len(duel.journal),
        len(duel.chain),
        duel.priority.is_open,
        frozenset(duel.consumed_events),
        duel.timing_floor,
    )

    attempts = [
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=offers[0].effect_ref
        ),
        PlayerAction.activate_effect(
            actor=MINE, source=source, effect_ref=EffectRef(GIRSU, 7)
        ),
        PlayerAction.activate_effect(
            actor=THEIRS, source=source, effect_ref=offers[0].effect_ref
        ),
    ]
    for attempt in attempts:
        assert duel.apply(attempt).accepted is False, attempt

    after = (
        duel.state.state_hash(),
        len(duel.journal),
        len(duel.chain),
        duel.priority.is_open,
        frozenset(duel.consumed_events),
        duel.timing_floor,
    )
    assert after == before


@requires_official_db
def test_a04_an_already_consumed_opportunity_is_refused_twice_over(repository):
    """
    🔴 **쓴 기회는 후보에도 없고 관문도 열지 않는다.**

    같은 사건 · 같은 효과 · 같은 개체를 두 번 발동할 수 없다는 것은 6-Z ·
    6-AA 가 세웠다. 6-AB 가 더한 것은 **관문 쪽**이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    first = _trigger_action(duel)
    assert first is not None
    assert duel.apply(first).accepted is True
    _settle(duel)

    assert _trigger_action(duel) is None
    validator = duel.activation_validator(MINE)
    assert (first.source, first.effect_ref) not in (
        validator.event_backed or frozenset()
    )
    assert duel.apply(first).accepted is False


@requires_official_db
def test_a05_the_candidate_set_and_the_gate_agree_on_every_offer(repository):
    """
    🔴 **두 자리의 답이 같다** — 제안마다 확인한다.

    "후보에 올랐다" ⟺ "관문이 열었다" 를 제안 하나하나에 대해 센다. 한쪽만
    참인 제안이 있으면 그것이 바로 우회 경로다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)

    offers = duel._trigger_offers(MINE)
    assert offers, "제안이 없으면 이 시험은 아무것도 재지 않는다"
    allowed = duel.legal_actions(MINE).allowed
    opened = duel.activation_validator(MINE).event_backed or frozenset()

    for offer in offers:
        in_list = any(
            a.kind is PlayerActionKind.ACTIVATE_EFFECT
            and a.source == offer.source
            and a.effect_ref == offer.effect_ref
            for a in allowed
        )
        at_gate = (offer.source, offer.effect_ref) in opened
        assert in_list == at_gate, (offer.effect_ref, in_list, at_gate)


def test_a06_the_validator_takes_the_judgement_as_a_value():
    """
    🔴 **검증기가 유발 계층을 import 하지 않는다.**

    ``engine.action_validation`` 은 ``event_backed`` 를 **값으로** 받는다 —
    그래야 판정이 한 자리(``Duel.activation_validator``)에만 있고, 검증기가
    자기 나름의 판정을 따로 갖지 않는다.
    """
    source = _source("engine/action_validation.py")
    assert "event_backed" in source
    for banned in ("TriggerRequirement", "TriggerWording", "trigger_offers"):
        assert banned not in source, banned


# ======================================================================
# B. 어휘와 수명 — 「때 / 경우」 가 기회를 언제 닫는가
# ======================================================================


@requires_official_db
def test_b01_the_only_registered_trigger_is_an_optional_if(repository):
    """
    🔴 **실측 — 기르수는 임의 · 「경우」 다.**

    이것이 아래 시험들의 전제다. 그래서 「때」 의 만료는 실제 카드로 밟을 수
    없고 합성으로 센다.
    """
    card = repository.get(GIRSU)
    assert card.activation_permission_text == "optional"
    assert card.activation_wording_text == TEXT_IF
    assert wording_from(TEXT_IF) is TriggerWording.IF
    assert wording_from(TEXT_WHEN) is TriggerWording.WHEN
    assert wording_from(None) is TriggerWording.UNKNOWN


@requires_official_db
def test_b02_an_if_trigger_survives_an_intervening_action(repository):
    """
    🔴 **「경우」 는 타이밍을 놓치지 않는다** — 6-AA ``test_c05`` 를 **설명**한다.

    6-AA 는 같은 동작을 ``BLOCKER-6AA-2`` 로 적었다 ("실제 규칙에서는 그
    시점이 지나면 기회가 사라진다"). 그 읽기가 **틀렸다**: 기르수는 「경우」
    이므로 그 사건 뒤에 다른 일이 일어나도 기회가 **남는 것이 규칙대로**다.

    그래서 이 시험은 6-AA 와 **같은 결과**를 재지만, 한계가 아니라 근거로
    잠근다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    assert len(duel._trigger_offers(MINE)) == 1

    other = _other_action(duel)
    assert other is not None, "끼워 넣을 행동이 없으면 아무것도 재지 않는다"
    assert duel.apply(other).accepted is True
    assert duel.state.turn.phase is Phase.MAIN1

    #: 🔴 **열려 있다 — 규칙이 그렇게 정했다.**
    offers = duel._trigger_offers(MINE)
    assert len(offers) == 1
    assert offers[0].misses_timing is False
    assert _trigger_action(duel) is not None


@requires_official_db
def test_b03_synthetic_a_when_trigger_closes_after_another_action(repository):
    """
    🔴 **「때」 는 그 사건이 마지막일 때만 열린다** (합성).

    어휘만 ``WHEN`` 으로 바꿔 끼운다. 사건 번호는 실제 값이므로, 기록의
    마지막이 아니게 되는 순간 ``misses_timing`` 이 참이 된다.

    🔴 **보류에 ``missing`` 을 적지 않는다** — 빠진 규칙이 없다. 규칙이
    그렇게 정했을 뿐이다 (6-S 의 규율).
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    _summon(setup.duel)
    duel = _wired(setup.duel, repository, wording=TriggerWording.WHEN)

    #: 사건 직후 — 아직 마지막이다.
    assert _trigger_action(duel) is not None
    other = _other_action(duel)
    assert other is not None
    assert duel.apply(other).accepted is True

    #: 🔴 지나갔다.
    assert _trigger_action(duel) is None
    missed = [
        w
        for w in duel.legal_actions(MINE).withheld
        if "놓쳤습니다" in w.reason
    ]
    assert len(missed) == 1
    assert missed[0].missing is None


@requires_official_db
def test_b04_synthetic_an_unknown_wording_is_withheld_with_its_reason(
    repository,
):
    """
    🔴 **어휘를 모르면 허가하지 않고, 무엇을 모르는지 적는다** (합성).

    「때」 였다면 지나갔고 「경우」 였다면 남아 있다 — 둘 중 어느 쪽인지
    모르므로 **기회가 열려 있는지 말할 수 없다.** 모름을 허가로 바꾸지 않고,
    조용히 넘어가지도 않는다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    _summon(setup.duel)
    duel = _wired(setup.duel, repository, wording=TriggerWording.UNKNOWN)

    #: 사건 직후에는 어휘를 몰라도 답이 하나다 — 마지막이므로 둘 다 열린다.
    assert _trigger_action(duel) is not None
    other = _other_action(duel)
    assert other is not None
    assert duel.apply(other).accepted is True

    #: 🔴 이제 어휘가 답을 가른다 — 그래서 보류한다.
    assert _trigger_action(duel) is None
    assert len(_withheld_for(duel, MINE, TRIGGER_WORDING_MISSING)) == 1


@requires_official_db
def test_b05_synthetic_a_when_trigger_is_preserved_while_a_chain_is_open(
    repository,
):
    """
    🔴 **체인 처리 중에 생긴 사건은 만료시키지 않는다** (SEGOC · 합성).

    공식 재정: 체인 처리 중에 시점을 만난 효과는 그 체인이 **완전히 해결된
    뒤**에 발동한다. 그래서 체인이 열려 있는 동안은 "마지막에 일어난 일" 로
    재지 않는다 — 재면 체인 안의 기록이 기회를 먹어 버린다.

    🔴 **순서를 임의로 적법화하지 않는다.** SEGOC 의 순서 결정도 WHEN/IF 의
    완전한 구현도 이 Phase 의 범위가 아니다 (``UNRESOLVED_ORDER_RULES``).
    여기서 재는 것은 **보존**뿐이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(setup.duel, repository, wording=TriggerWording.WHEN)

    action = _trigger_action(duel)
    assert action is not None
    assert duel.apply(action).accepted is True
    #: 체인이 열려 있다 — 응답 창이다.
    assert duel.chain.is_empty is False

    offers = duel._trigger_offers(MINE)
    for offer in offers:
        #: 🔴 체인이 열려 있으므로 "지금" 으로 센다.
        assert duel._timing_is_current(offer) is True


@requires_official_db
def test_b06_asking_repeatedly_leaves_the_opportunity_untouched(repository):
    """
    🔴 **묻는 것만으로 기회 · 사건 · 판 · 바닥이 바뀌지 않는다.**

    6-AA ``test_c03`` 이 센 것을 6-AB 의 새 자리에서 다시 센다 —
    ``_enforce_mandatory`` 와 ``_timing_is_current`` 가 ``legal_actions``
    안에 들어왔으므로 그 둘이 상태를 만들지 않는지 확인해야 한다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)

    def snapshot():
        return (
            duel.state.state_hash(),
            len(duel.journal),
            frozenset(duel.consumed_events),
            duel.timing_floor,
            len(duel._trigger_offers(MINE)),
            tuple(a.kind for a in duel.legal_actions(MINE).allowed),
        )

    first = snapshot()
    for _ in range(5):
        duel.legal_actions(MINE)
        duel.legal_actions(THEIRS)
        duel.activation_validator(MINE)
    assert snapshot() == first


@requires_official_db
def test_b07_a_rejected_illegal_action_spends_no_opportunity(repository):
    """🔴 **거절된 불법 행동이 적법한 기회를 소비하지 않는다** (6-AA 유지)."""
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    assert _trigger_action(duel) is not None

    bogus = PlayerAction.activate_effect(
        actor=MINE,
        source=_trigger_action(duel).source,
        effect_ref=EffectRef(GIRSU, 9),
    )
    assert duel.apply(bogus).accepted is False
    assert len(duel.consumed_events) == 0
    assert _trigger_action(duel) is not None


# ======================================================================
# C. 강제 보장 — 무엇으로도 넘길 수 없는가
# ======================================================================


@requires_official_db
def test_c01_synthetic_a_mandatory_trigger_closes_the_other_actions(repository):
    """
    🔴 **강제 유발이 열려 있으면 다른 길이 닫힌다** (합성 · BLOCKER-6AB-C).

    6-AA 는 ``END_PHASE`` 한 자리만 막았다. 일반 행동(세트 · 소환 · 발동)과
    ``PASS`` 로는 그냥 넘어갔다.

    🔴 **엔진이 대신 발동하지는 않는다** — 후보를 남기고, 그 안의 선택은
    여전히 고르는 쪽의 것이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.MANDATORY
    )

    legal = duel.legal_actions(MINE)
    assert legal.allowed, "허가가 비면 영구 대기다"
    #: 🔴 남은 길은 그 발동뿐이다.
    assert all(
        a.kind is PlayerActionKind.ACTIVATE_EFFECT for a in legal.allowed
    )
    assert all(a.effect_ref.card_id == GIRSU for a in legal.allowed)

    #: 🔴 넘기려 한 길들이 **왜** 막혔는지 적혀 있다.
    reasons = [w.reason for w in legal.withheld if "먼저 처리해야" in w.reason]
    assert reasons


@requires_official_db
def test_c02_synthetic_a_mandatory_trigger_cannot_be_passed_over(repository):
    """
    🔴 **``PASS`` · ``END_PHASE`` · 일반 행동 셋 다 막힌다** (합성).

    6-AA 가 ``END_PHASE`` 하나만 막은 자리다. 세 종류를 각각 ``apply`` 에
    직접 넣어 본다 — ``legal_actions`` 를 거치지 않는 길이다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    before = _other_action(setup.duel)
    assert before is not None, "막을 일반 행동이 없으면 아무것도 재지 않는다"

    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.MANDATORY
    )
    for attempt in (
        PlayerAction.passing(actor=MINE),
        PlayerAction.end_phase(actor=MINE),
        before,
    ):
        assert duel.apply(attempt).accepted is False, attempt


@requires_official_db
def test_c03_synthetic_the_flow_resumes_after_the_duty_is_done(repository):
    """
    🔴 **처리하면 흐름이 돌아온다** — 영구 대기가 아니다 (합성).

    강제 유발을 발동해 해결까지 간 뒤, 다시 일반 행동이 허가되는지 센다.
    해결 중의 카드 선택은 ``PolicyChooser`` 를 지난다 — 엔진이 그 선택을
    대신하지 않는다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.MANDATORY
    )

    duty = duel.legal_actions(MINE).allowed[0]
    assert duty.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert duel.apply(duty).accepted is True
    _settle(duel)

    #: 🔴 해결 중에 **고르는 쪽이** 골랐다.
    assert len(chooser.records) >= 1
    #: 🔴 그리고 흐름이 돌아왔다.
    resumed = duel.legal_actions(MINE)
    assert any(
        a.kind is not PlayerActionKind.ACTIVATE_EFFECT for a in resumed.allowed
    )


@requires_official_db
def test_c04_synthetic_an_unplayable_mandatory_trigger_does_not_deadlock(
    repository,
):
    """
    🔴 **발동할 수 없는 강제 유발이 듀얼을 멈추지 않는다** (합성).

    조건 · 비용 · 구현 중 하나가 막으면 관문이 그 발동을 열지 않는다. 그때
    다른 길까지 닫으면 **고를 것이 없어** 듀얼이 그 자리에서 멈춘다.

    그래서 닫지 않고, 진행의 합법성을 보장하지 못한다는 사실을 보류에
    적는다 — "완료 · 정상 종료" 와 **구별되는 미지원 결과**다.

    합성 방법: **강제이면서 어휘를 모르는** 제안을 만들고 사건이 마지막이
    아니게 한다. 그러면 의무는 남아 있는데 (「경우」 였다면 아직 열려 있다)
    관문은 열지 않는다 (모름을 허가로 바꾸지 않는다) — 조건 · 비용 · 구현이
    막은 것과 **같은 모양**이다.

    🔴 **「때」 로는 이 모양이 안 나온다.** 지나간 「때」 는 더 이상 의무가
    아니다 — 규칙이 이미 "놓쳤다" 고 답했으므로
    :meth:`~engine.duel.Duel._mandatory_offers` 가 그것을 의무로 세지 않는다
    (6-AB). 세어 두면 "규칙이 요구하는데 발동할 수 없다" 는 **거짓 보류**가
    붙는다. 이 시험을 처음 쓸 때 ``WHEN`` 으로 합성했고, 그 과정에서 그
    거짓을 찾아 엔진을 고쳤다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    #: 🔴 좁혀지지 **않은** 판에서 끼워 넣을 행동을 꺼낸다 — 강제를 꽂은 뒤에는
    #: 그 행동이 이미 보류로 밀려 있어 꺼낼 수 없다 (``test_c01``).
    other = _other_action(setup.duel)
    assert other is not None, "끼워 넣을 행동이 없으면 아무것도 재지 않는다"
    assert setup.duel.apply(other).accepted is True

    duel = _wired(
        setup.duel,
        repository,
        requirement=TriggerRequirement.MANDATORY,
        wording=TriggerWording.UNKNOWN,
    )
    #: 의무는 남아 있다 — 어휘를 모르므로 끝났다고 단정하지 않는다.
    assert len(duel._mandatory_offers(MINE)) == 1

    legal = duel.legal_actions(MINE)
    #: 🔴 멈추지 않았다.
    assert legal.allowed
    #: 🔴 그리고 조용히 넘어가지 않았다.
    assert len(_withheld_for(duel, MINE, MANDATORY_TRIGGER_UNPLAYABLE)) == 1


@requires_official_db
def test_c05_synthetic_my_duty_does_not_close_the_other_seat(repository):
    """
    🔴 **자리마다 따로 본다** — 상대의 강제 기회가 내 행동을 막지 않는다.

    막으면 상대가 처리할 수 없는 기회로 내 턴이 멈춘다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired(
        setup.duel, repository, requirement=TriggerRequirement.MANDATORY
    )
    #: 내 자리에는 강제가 있다.
    assert duel._mandatory_offers(MINE)
    #: 🔴 상대 자리에는 없다 — 그래서 상대의 허가는 강제로 좁혀지지 않는다.
    assert duel._mandatory_offers(THEIRS) == ()


@requires_official_db
def test_c06_synthetic_a_duty_outside_my_turn_is_not_a_missing_rule(repository):
    """
    🔴 **지금 고르는 자리가 아니면 "관문이 막았다" 고 적지 않는다** (합성).

    상대가 강제 기회를 들고 있는 동안 ``legal_actions(상대)`` 를 물으면
    허가가 비어 있다. 그 이유는 **순서**다 — 우선권이 그 자리에 없다. 그런데
    6-AB 가 처음 쓴 ``_enforce_mandatory`` 는 거기에
    :data:`~engine.duel.MANDATORY_TRIGGER_UNPLAYABLE` 을 달았고, 그 보류는
    "규칙이 요구하는데 발동 절차를 보장할 근거가 없다" 는 뜻이므로 **거짓**
    이었다 (실측으로 찾았다).

    🔴 지금은 ``missing`` 을 **비우고** 순서라고 적는다 — 6-S 가
    ``_flow_actions`` 에서 세운 기준과 같다. 조용히 넘기지도 않는다: 의무가
    그 자리에 열려 있다는 사실은 적힌다.

    합성 방법: 어느 자리로 물어도 **0번 자리의 제안**을 돌려주는 원천을
    꽂는다. 실제 ``TriggerSource`` 는 ``controller`` 로 걸러 주므로, 자리가
    어긋난 상태를 실제 카드로는 만들 수 없다.
    """

    class _BothSeats:
        def __init__(self, repo):
            self._inner = TriggerSource(repo)

        def offers(self, duel, seat: int):
            return tuple(
                dataclasses.replace(
                    offer, requirement=TriggerRequirement.MANDATORY
                )
                for offer in self._inner.offers(duel, MINE)
            )

    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = dataclasses.replace(setup.duel, triggers=_BothSeats(repository))

    assert duel.to_act == MINE
    assert duel._mandatory_offers(THEIRS), "합성이 어긋난 자리를 못 만들면 빈다"

    theirs = duel.legal_actions(THEIRS)
    assert theirs.allowed == (), "차례가 아니므로 고를 것이 없다"
    #: 🔴 **거짓 보류가 없다.**
    assert _withheld_for(duel, THEIRS, MANDATORY_TRIGGER_UNPLAYABLE) == []
    #: 🔴 **그런데 조용히 넘기지도 않았다.**
    ordering = [
        w
        for w in theirs.withheld
        if "행동을 고르는 자리가 아닙니다" in w.reason
    ]
    assert len(ordering) == 1
    assert ordering[0].missing is None

    #: 🔴 **내 자리는 그대로 좁혀진다** — 순서 판정이 보장을 끄지 않았다.
    mine = duel.legal_actions(MINE)
    assert mine.allowed
    assert all(
        a.kind is PlayerActionKind.ACTIVATE_EFFECT for a in mine.allowed
    )


def test_c07_the_duty_is_enforced_in_one_place():
    """
    🔴 **``END_PHASE`` 전용 블록이 사라졌다** — 한 자리에서 본다.

    6-AA 는 ``_flow_actions`` 안에서 ``END_PHASE`` 만 막았다. 그 자리가 남아
    있으면 같은 규칙이 두 군데 있게 되고, 둘이 갈라지는 날 오류 없이 조용히
    달라진다.
    """
    source = _source("engine/duel.py")
    assert "_enforce_mandatory" in source
    assert source.count("def _enforce_mandatory") == 1
    #: ``legal_actions`` 가 그것을 마지막에 통과한다.
    assert "return self._enforce_mandatory(" in source


# ======================================================================
# D. 사본 — 원본과 같은 후보를 보고, 새지 않는가
# ======================================================================


@requires_official_db
def test_d01_a_fork_sees_the_same_candidates_as_the_original(repository):
    """
    🔴 **사본이 역사를 물려받는다** (BLOCKER-6AB-D).

    6-AA 의 ``_fork`` 는 기록하지 않는 한 벌로 바꿔 끼웠고 (``journal=False``)
    그래서 사본이 **과거 사건을 잃었다**. 유발 후보는 기록된 사건에서 나오므로
    (6-Z) 사본의 ``legal_actions`` 가 원본과 다른 답을 냈다 — 실측 **원본 5 ·
    사본 4**.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    assert _trigger_action(duel) is not None

    fork = Simulator(duel)._fork()
    assert len(fork.journal) == len(duel.journal)
    assert _trigger_action(fork) is not None
    assert tuple(a.kind for a in fork.legal_actions(MINE).allowed) == tuple(
        a.kind for a in duel.legal_actions(MINE).allowed
    )


@requires_official_db
def test_d02_a_fork_keeps_its_own_journal_object(repository):
    """
    🔴 **사본의 기록은 다른 객체다** — 6-B 의 요구를 그대로 지킨다.

    부모의 사건들을 씨앗으로 받은 **새 ``EventJournal``** 이고, 사본의 전개는
    그 새 객체에만 쌓인다. 그래서 버려지는 사본의 역사가 진짜 기록과
    모순되지 않는다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    fork = Simulator(duel)._fork()

    assert fork.journal is not duel.journal
    before = len(duel.journal)
    action = _trigger_action(fork)
    assert action is not None
    assert fork.apply(action).accepted is True
    #: 🔴 **해결까지 간다.** 발동 선언만으로는 기록이 늘지 않는다 (실측 —
    #: 체인에 쌓는 일은 판을 바꾸지 않는다). 판을 바꾸는 것은 해결이다.
    _settle(fork)
    assert len(fork.journal) > before
    #: 🔴 사본의 전개가 부모에 남지 않았다.
    assert len(duel.journal) == before


@requires_official_db
def test_d03_sibling_forks_do_not_see_each_other(repository):
    """🔴 **형제 분기가 섞이지 않는다** — 소비도 기록도."""
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    sim = Simulator(duel)
    left, right = sim._fork(), sim._fork()

    assert left.journal is not right.journal
    action = _trigger_action(left)
    assert action is not None
    assert left.apply(action).accepted is True

    assert len(left.consumed_events) == 1
    assert len(right.consumed_events) == 0
    assert len(duel.consumed_events) == 0
    assert _trigger_action(right) is not None


@requires_official_db
def test_d04_a_trigger_born_inside_the_fork_becomes_a_candidate(repository):
    """
    🔴 **사본 안의 새 행동이 낳은 유발도 후보가 된다.**

    기록을 복사하는 것만으로는 이것이 되지 않는다 — 사본의 ``legal_actions``
    가 **사본의 기록**을 읽어야 한다. 소환 **전**에 포크해서 센다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    fork = Simulator(duel)._fork()

    assert _trigger_action(fork) is None, "소환 전에는 유발이 없다"
    summons = [
        a
        for a in fork.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
    ]
    assert summons, "소환할 것이 없으면 아무것도 재지 않는다"
    assert fork.apply(summons[0]).accepted is True

    #: 🔴 사본 안에서 태어난 유발이다.
    assert _trigger_action(fork) is not None
    #: 🔴 그리고 부모는 그 사건을 모른다.
    assert len(duel.journal) == 0
    assert _trigger_action(duel) is None


@requires_official_db
def test_d05_the_real_simulator_path_resolves_the_trigger(repository):
    """
    🔴 **기록을 복사하는 것으로 끝내지 않고 ``Simulator`` 로 확인한다.**

    사본은 실행기 한 벌을 **새로** 만들므로 (``duel_components``) 해결 시점
    선택을 할 사람도 물려받아야 한다. 물려받지 못한 동안의 실측::

        simulate → SUPPORTED, "아직 고르지 않은 대상이 있습니다: @primary"

    발동은 되는데 **해결이 거절됐다.** 그러면 "해결할 수 있는 효과" 가 원본과
    사본에서 달라지고, 미래의 값이 규칙이 아니라 **배선**을 재게 된다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None

    result = Simulator(duel).simulate(action, viewer=MINE)
    assert result.status is SimulationStatus.SUPPORTED
    assert "아직 고르지 않은" not in (result.reason or "")
    assert "해결했습니다" in (result.reason or "")


@requires_official_db
def test_d06_the_fork_asks_with_the_same_policy_but_its_own_record(repository):
    """
    🔴 **정책은 공유하고 기록은 나눈다.**

    정책을 공유하지 않으면 재는 미래가 실제로 밟을 미래가 아니다. 기록을
    공유하면 :attr:`~integration.autonomy.PolicyChooser.records` 가 "실제
    듀얼에서 **해결 중에** 무엇을 물었는가" 의 증거가 아니게 된다 —
    일어나지 않은 선택이 섞인다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None

    assert len(chooser.records) == 0
    result = Simulator(duel).simulate(action, viewer=MINE)
    assert result.status is SimulationStatus.SUPPORTED
    #: 🔴 사본이 물었지만 진짜 듀얼의 기록은 비어 있다.
    assert len(chooser.records) == 0

    forked = chooser.forked()
    assert forked is not chooser
    assert forked.selector is chooser.selector
    assert forked.records == ()


@requires_official_db
def test_d07_a_simulation_leaves_the_original_untouched(repository):
    """🔴 **시뮬레이션이 판 · 기록 · 소비 · 난수를 바꾸지 않는다.**"""
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None

    sim = Simulator(duel)
    before = (
        duel.state.state_hash(),
        len(duel.journal),
        frozenset(duel.consumed_events),
        duel.timing_floor,
        duel.state.randomness.draws,
    )
    sim.simulate(action, viewer=MINE)
    after = (
        duel.state.state_hash(),
        len(duel.journal),
        frozenset(duel.consumed_events),
        duel.timing_floor,
        duel.state.randomness.draws,
    )
    assert after == before


def test_d08_the_state_hash_is_not_used_to_merge_states():
    """
    🔴 **실측 — ``state_hash`` 로 상태를 합치는 자리가 없다.**

    같은 해시가 같은 발동 가능성을 뜻하지 않으므로 (6-AA ``test_d05``),
    해시로 중복을 지우면 기회가 다른 두 상태가 하나로 합쳐진다. 지금은 그런
    자리가 **없다** — 해시는 흔적 기록에만 쓰인다. 그래서 이 Phase 는
    탐색 쪽에 손대지 않았고, 그 사실을 여기 잠근다.

    이 시험이 깨지는 날은 해시가 판단에 쓰이기 시작한 날이다.
    """
    for path in ("agent/search.py", "agent/simulation.py"):
        source = _source(path)
        for banned in ("state_hash()] =", "seen.add(", "_cache[", "visited"):
            assert banned not in source, (path, banned)
