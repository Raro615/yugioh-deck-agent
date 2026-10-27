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
import types

import pytest

from agent.choice import DeclineChoice, FirstPermittedChoice, RandomChoice
from agent.heuristic import rule_based_policy
from agent.runner import DuelRunner
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
from engine.vocabulary import Phase, Position, Zone

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


class _FixedOffers:
    """
    🔴 **합성 — 주어진 제안 그대로를 내놓는다.**

    판정 함수(``_window_admits``)를 직접 재는 것으로는 ``legal_actions`` 가
    그 판정을 **어떻게 적는지**(보류의 이유와 ``missing``)를 볼 수 없다.
    그래서 제안 하나를 고정해 놓고 그 출력을 본다. 허가 · 비용 · 최종 상태를
    주입하는 것이 아니다 — 내놓는 제안은 실제 ``TriggerSource`` 가 만든
    것이고, 바꾼 것은 사건 번호뿐이다.
    """

    def __init__(self, offers):
        self._offers = tuple(offers)

    def offers(self, duel, seat: int):
        return tuple(o for o in self._offers if o.controller == seat)


def _wired(duel, repository, **replacements):
    """그 판의 유발 원천을 바꿔 끼운 사본."""
    return dataclasses.replace(
        duel, triggers=_Replaced(repository, **replacements)
    )


def _decline_window(duel, *, seat: int = MINE) -> int:
    """
    열린 **임의** 유발 처리 기회를 ``PASS`` 로 지난다 (Phase 6-AB 보완4).

    돌려주는 것은 밟은 걸음 수다. 열린 기회가 없으면 0 이다.

    🔴 **왜 이 도구가 생겼는가.** 보완4 가 공식 Fast Effect Timing 도표를
    근거로 *"유발 기회가 열린 자리에서는 판이 열린 상태에서만 할 수 있는
    행동(통상 소환 · 세트 · 페이즈 이동)을 할 수 없다"* 를 구현했다 —
    *"Many actions can ONLY be performed when the game state is open (when
    you're in box A)."* 그래서 이 파일이 **다른 행동을 끼워 넣어** 창을
    지나던 방식이 성립하지 않고, 지나는 방법은 ``PASS`` 다.

    🔴 **강제 묶음은 지나갈 수 없다** — 그 자리에는 ``PASS`` 가 오르지
    않으므로 0 을 돌려준다. 그것이 ``test_c01`` · ``test_c02`` 가 재는
    구분이다.

    🔴 **창을 옮기지는 않는다.** 포기는 :attr:`Duel.window_passed` 에만
    적히고 :attr:`Duel.window_floor` 는 그대로다 — 창을 옮기는 것은 여전히
    판을 바꾸는 행동이다. 그래서 "창이 옮겨 갔는가" 를 재는 시험은 포기
    **뒤에** 그 행동을 한다.
    """
    steps = 0
    while steps < 4:
        legal = duel.legal_actions(duel.to_act)
        passing = [
            action
            for action in legal.allowed
            if action.kind is PlayerActionKind.PASS
        ]
        if not passing or duel.priority.is_open:
            break
        assert duel.apply(passing[0]).accepted is True
        steps += 1
    return steps


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
def test_b02_an_if_trigger_does_not_miss_timing_but_its_window_still_closes(
    repository,
):
    """
    🔴 **두 사실을 가른다** — 6-AB 보완이 고친 해석이다.

    6-AB 는 이 시험을 ``test_b02_an_if_trigger_survives_an_intervening_action``
    이라 부르고 *"「경우」 이므로 그 사건 뒤에 다른 일이 일어나도 기회가
    남는다"* 를 단정했다. **그 해석이 틀렸다.**

    *"타이밍을 놓치지 않는다"* 는 *"같은 페이즈에서 나중에 마음대로 발동할
    수 있다"* 는 뜻이 **아니다.** 둘은 다른 질문이다:

    ====================================  ==============================
    「경우」 는 타이밍을 놓치는가            **아니다** (``_missed_timing``)
    그 기회가 아직 열려 있는가              그 자리에서 무엇을 했는가에 달렸다
    ====================================  ==============================

    근거는 공식 Fast Effect Timing 도표다 — 유발은 체인을 시작하지 않는 행위
    뒤와 체인 해결 뒤에 확인되고, 그 자리에서 양쪽이 패스하면 판은 **open
    state** 로 돌아간다. 그 확인 자리에서 유발 대신 **다른 일을 골랐다면**
    그 자리의 기회는 지나간 것이다.
    (https://www.yugioh-card.com/en/play/fast-effect-timing/)

    실측한 6-AB 의 증상: 기르수 소환 뒤 일반 행동을 **세 걸음** 하고도 그
    유발이 후보에 남았다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    offers = duel._trigger_offers(MINE)
    assert len(offers) == 1

    #: 🔴 **「경우」 는 타이밍을 놓치지 않는다** — 그 사실은 그대로다.
    assert offers[0].misses_timing is False
    assert duel._missed_timing(offers[0]) is False
    #: 그리고 지금은 발동할 수 있다.
    assert _trigger_action(duel) is not None

    #: 🔴 **먼저 그 기회를 지난다** (보완4). 판이 열린 상태가 아니면
    #: 끼워 넣을 행동 자체가 후보로 오르지 않는다 (``_decline_window``).
    assert _decline_window(duel) >= 1
    assert _trigger_action(duel) is None, "포기한 기회는 다시 오르지 않는다"

    other = _other_action(duel)
    assert other is not None, "끼워 넣을 행동이 없으면 아무것도 재지 않는다"
    assert duel.apply(other).accepted is True
    assert duel.state.turn.phase is Phase.MAIN1

    #: 🔴 **기회는 닫혔다** — 양쪽이 지나갔고 그 뒤 판을 바꾸는 행동이
    #: 새 창을 열었다 (``Duel.window_floor``).
    assert _trigger_action(duel) is None
    assert duel.window_floor > offers[0].event_sequence
    #: 🔴 **그런데 타이밍을 놓친 것이 아니다** — 두 사실이 따로 남아 있다.
    offers_after = duel._trigger_offers(MINE)
    assert len(offers_after) == 1, "제안 자체는 남는다 — 닫힌 것은 창이다"
    assert duel._missed_timing(offers_after[0]) is False
    assert duel._window_admits(offers_after[0], MINE) is False

    #: 🔴 **기회가 끝났다고 적혀 있다** — 빠진 규칙이 아니므로 ``missing`` 은
    #: 없다.
    closed = [
        w
        for w in duel.legal_actions(MINE).withheld
        if "기회는 이미 끝났습니다" in w.reason
    ]
    assert len(closed) == 1
    assert closed[0].missing is None


@requires_official_db
def test_b02b_the_closed_window_does_not_reopen_in_the_same_phase(repository):
    """
    🔴 **종료된 기회는 같은 페이즈에서도 다시 나타나지 않는다.**

    6-AB 까지는 나타났다 (``test_b02`` 의 실측). 걸음을 더 밟아도 닫힌 채로
    있어야 한다 — "한 걸음만 닫힌다" 가 되면 그것도 결함이다.

    🔴 **보완4: 기회를 지나는 방법이 ``PASS`` 가 되었다** (``_decline_window``
    의 설명). 단정은 그대로다 — 닫힌 뒤에는 걸음을 더 밟아도 열리지 않는다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    assert _trigger_action(duel) is not None
    assert _decline_window(duel) >= 1
    assert _trigger_action(duel) is None

    steps = 0
    while steps < 4:
        #: 🔴 페이즈를 넘기지 않는다 — 넘기면 ``timing_floor`` 가 닫으므로
        #: 이 시험이 재려는 것(**같은 페이즈 안에서** 닫힌 채로 있는가)이
        #: 바뀐다.
        other = next(
            (
                a
                for a in duel.legal_actions(MINE).allowed
                if a.kind
                not in (
                    PlayerActionKind.ACTIVATE_EFFECT,
                    PlayerActionKind.PASS,
                    PlayerActionKind.END_PHASE,
                )
            ),
            None,
        )
        if other is None:
            break
        assert duel.apply(other).accepted is True
        steps += 1
        #: 🔴 걸음마다 닫힌 채로 있다.
        assert _trigger_action(duel) is None, steps
    assert steps >= 1, "행동을 한 걸음도 못 했으면 아무것도 재지 않는다"
    assert duel.state.turn.phase is Phase.MAIN1


@requires_official_db
def test_b03_synthetic_the_wording_decides_missed_timing_not_the_window(
    repository,
):
    """
    🔴 **어휘는 "놓쳤는가" 에만 답한다** (합성 · 6-AB 보완이 고친 자리).

    6-AB 의 이 시험은 합성 「때」 유발이 일반 행동 뒤에 **"놓쳤습니다"** 로
    보류되는 것을 쟀다. 지금은 그 자리에서 **포기**가 먼저 적힌다 — 그
    자리가 유발을 받고 다른 것을 골랐으니 그것이 더 앞선 사실이다.

    그래서 재는 것을 옮긴다: 어휘가 가르는 값(:meth:`Duel._missed_timing`)을
    **직접** 센다. 「때」 와 「경우」 의 구분은 그대로 살아 있고, 창이 닫히는
    일과 **섞이지 않는다** — 그 섞임이 6-AB 의 결함이었다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    _summon(setup.duel)

    base = setup.duel._trigger_offers(MINE)
    assert len(base) == 1

    #: 사건이 **마지막일 때** — 어느 어휘든 놓치지 않았다.
    for wording in (TriggerWording.IF, TriggerWording.WHEN):
        duel = _wired(setup.duel, repository, wording=wording)
        offer = duel._trigger_offers(MINE)[0]
        assert duel._missed_timing(offer) is False, wording
        assert duel._window_admits(offer, MINE) is True, wording

    #: 🔴 **포기한 뒤에** 끼워 넣을 행동을 적용한다 (보완4). 판이 열린
    #: 상태가 아니면 그 행동이 후보로 오르지 않는다 (``_decline_window``).
    #: 포기는 ``window_passed`` 에만 적히고, 기록을 늘려 **사건을 마지막이
    #: 아니게** 만드는 것은 판을 바꾸는 그 행동이다.
    assert _decline_window(setup.duel) >= 1
    other = _other_action(setup.duel)
    assert other is not None
    assert setup.duel.apply(other).accepted is True

    #: 🔴 사건이 **마지막이 아닐 때** — 여기서 어휘가 갈린다.
    if_duel = _wired(setup.duel, repository, wording=TriggerWording.IF)
    when_duel = _wired(setup.duel, repository, wording=TriggerWording.WHEN)
    assert if_duel._missed_timing(if_duel._trigger_offers(MINE)[0]) is False
    assert when_duel._missed_timing(when_duel._trigger_offers(MINE)[0]) is True

    #: 🔴 **둘 다 창은 닫혀 있다** — 어휘와 무관하다. 닫은 근거는 둘이고
    #: (포기했고, 그 뒤 판을 바꾸는 행동이 창을 옮겼다) 둘 중 하나로도
    #: 닫힌다 — 어휘 판정은 그것과 **다른 사실**이라는 것이 요점이다.
    for duel in (if_duel, when_duel):
        offer = duel._trigger_offers(MINE)[0]
        assert duel._window_admits(offer, MINE) is False


@requires_official_db
def test_b03b_synthetic_a_mandatory_when_is_not_expired_by_the_wording(
    repository,
):
    """
    🔴 **강제 「때」 를 어휘만으로 만료시키지 않는다** (합성 · BLOCKER 재현).

    6-AB 의 실측 증상: ``MANDATORY`` + ``WHEN`` 이고 사건이 마지막이 아니면
    ``_mandatory_offers`` 가 **0** 을 돌려주었다 — 규칙이 처리를 요구하는
    효과가 **조용히 사라졌다.**

    🔴 **근거의 상태를 정직하게 적는다.** 룰북(``data/rules/``)에 「때 /
    경우」 구분이 없으므로 *"강제는 타이밍을 놓치지 않는다"* 를 **공식
    문서로 확인하지 못했다.** 2차 자료는 그렇게 말하지만 공식 재정이 아니다.
    그래서 이 엔진은 그 조합을 **모름**(``None``)으로 두고, 의무를 지우지도
    발동을 허가하지도 않는다 (:meth:`Duel._missed_timing` 의 설명).
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    #: 🔴 **포기한 뒤에** 끼워 넣는다 (보완4 — ``_decline_window``).
    assert _decline_window(setup.duel) >= 1
    other = _other_action(setup.duel)
    assert other is not None
    assert setup.duel.apply(other).accepted is True

    optional = _wired(setup.duel, repository, wording=TriggerWording.WHEN)
    forced = _wired(
        setup.duel,
        repository,
        wording=TriggerWording.WHEN,
        requirement=TriggerRequirement.MANDATORY,
    )

    #: 🔴 임의 「때」 는 놓쳤다 — 의무가 아니다.
    assert optional._missed_timing(optional._trigger_offers(MINE)[0]) is True
    assert optional._mandatory_offers(MINE) == ()

    #: 🔴 강제 「때」 는 **모른다** — 그래서 의무로 남는다.
    assert forced._missed_timing(forced._trigger_offers(MINE)[0]) is None
    assert len(forced._mandatory_offers(MINE)) == 1


@requires_official_db
def test_b04_synthetic_an_unknown_wording_admits_nothing(repository):
    """
    🔴 **어휘를 모르면 어느 관문도 열지 않는다** (합성 · 리뷰 A).

    6-AB 보완의 ``_window_admits`` 는 마지막 줄이
    ``return self._missed_timing(offer) is not True`` 였다. 그래서
    ``None``(판정 근거 없음)이 **``True``** 가 됐다 — 실측:

    =========================  =======
    ``_missed_timing``           ``None``
    ``_window_admits``           ``True``   🔴
    ``_offer_is_activatable``    ``True``   🔴
    ``event_backed`` 에 포함      **예**     🔴
    ``legal_actions`` 후보        아니오
    =========================  =======

    막는 것은 후보 목록의 보류 **하나뿐**이었고, 내부 관문은 열려 있었다.
    🔴 **다만 직접 ``apply`` 는 그때도 거절됐다** (후보 검사에서) — 그래서
    이것은 **내부 판정 불일치**이고 실행 우회가 재현된 것은 **아니다.**

    지금은 ``None`` 이 그대로 ``None`` 이고, :meth:`Duel._offer_is_activatable`
    이 ``is True`` 만 통과시키므로 넷이 모두 닫힌다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = setup.duel

    base = duel._trigger_offers(MINE)
    assert len(base) == 1, "제안이 없으면 이 시험은 아무것도 재지 않는다"

    #: 🔴 **합성 — 사건 번호를 현재 창 안이면서 마지막이 아닌 자리로 둔다.**
    #: 그 자리가 어휘로 답이 갈리는 **유일한** 자리이고, 실제 실행 경로에서는
    #: 아직 도달하지 않는다 (``test_b04b`` 가 그 사실을 실측으로 잠근다).
    floor = max(duel.timing_floor, duel.window_floor)
    last = len(duel.journal) - 1
    unknown = dataclasses.replace(
        base[0], wording=TriggerWording.UNKNOWN, event_sequence=floor
    )
    assert floor <= unknown.event_sequence, "창 밖이면 어휘가 쓰이지 않는다"

    #: 사건이 **마지막일 때**는 어휘를 몰라도 답이 하나다 — 열린다.
    if unknown.event_sequence == last:
        assert duel._missed_timing(unknown) is False
        assert duel._window_admits(unknown, MINE) is True
        #: 그래서 모름이 답을 가르는 자리를 만들려면 기록이 더 자라야 한다.
        unknown = dataclasses.replace(unknown, event_sequence=floor)

    #: 🔴 기록을 늘려 **마지막이 아니게** 만든다 — 창은 그대로 둔다.
    #:
    #: 🔴 **보완4: 끼워 넣기 전에 기회를 지난다** (판이 열린 상태가 아니면
    #: 그 행동이 후보로 오르지 않는다). 그리고 창을 **되돌린다** —
    #: ``window_floor`` 를 0 으로 두는 것과 같은 이유다: 이 시험이 재려는
    #: 것은 **어휘 판정** 하나이고, 창이 닫혔다는 사실로 가려지면 그 판정에
    #: 도달하지 않는다.
    grown = dataclasses.replace(duel, timing_floor=0, window_floor=0)
    assert _decline_window(grown) >= 1
    other = _other_action(grown)
    assert other is not None
    assert grown.apply(other).accepted is True
    grown = dataclasses.replace(
        grown, window_floor=0, window_passed=frozenset()
    )
    assert len(grown.journal) - 1 > unknown.event_sequence, "기록이 안 자랐다"

    #: 🔴 **넷이 모두 닫힌다.**
    assert grown._missed_timing(unknown) is None
    assert grown._window_admits(unknown, MINE) is None
    assert grown._offer_is_activatable(unknown, MINE) is False
    wired = _wired(grown, repository, wording=TriggerWording.UNKNOWN)
    backed = wired.activation_validator(MINE).event_backed or frozenset()
    assert (unknown.source, unknown.effect_ref) not in backed


@requires_official_db
def test_b04b_a_window_never_holds_more_than_one_event_yet(repository):
    """
    🔴 **실측 — 지금 창에는 사건이 하나뿐이다.** 그래서 어휘 판정이 실제
    실행 경로에서 **답을 가르지 않는다.**

    듀얼 한 판을 끝까지 돌리며 ``legal_actions`` 가 불릴 때마다
    ``(기록의 마지막 번호) − (창의 바닥)`` 을 쟀다. 실측 분포는
    ``{-1, 0}`` 이고 **1 이상이 한 번도 없었다** (호출 142회).

    뜻: 창이 열릴 때마다 그 안의 사건은 **하나**이므로 "사건이 창 안에
    있지만 마지막은 아니다" 라는 자리에 도달하지 않는다. 「때 / 경우」 가
    답을 가르는 자리가 바로 그곳이므로, 어휘 판정은 **지금은 쓰이지 않는다.**

    🔴 **그래서 ``test_b04`` 는 합성이다** — 그 사실을 숨기지 않고, 어휘
    판정을 지운 것도 아니다. 사건을 여럿 낳는 효과나 여러 걸음으로 해결되는
    효과가 들어오면 이 시험이 **먼저 깨지고**, 그때 어휘 판정이 실제로
    쓰이기 시작한다. 보고서 §8 에 BLOCKER 로 적었다.
    """
    import engine.duel as duel_module

    gaps: list[int] = []
    original = duel_module.Duel.legal_actions

    def traced(self, seat=None):
        journal = len(self.journal) if self.journal is not None else 0
        floor = max(self.timing_floor, self.window_floor)
        gaps.append(journal - 1 - floor)
        return original(self, seat)

    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    runner = DuelRunner(
        duel, (rule_based_policy(name="p0"), rule_based_policy(name="p1"))
    )
    duel_module.Duel.legal_actions = traced
    try:
        for _ in range(600):
            runner.step()
            if duel.is_over:
                break
    finally:
        duel_module.Duel.legal_actions = original

    assert duel.is_over, "듀얼이 끝나지 않으면 표본이 한쪽으로 치우친다"
    assert len(gaps) > 50, len(gaps)
    #: 🔴 **창에 사건이 둘 이상 들어간 적이 없다.**
    assert max(gaps) <= 0, (max(gaps), sorted(set(gaps)))


@requires_official_db
def test_b05_synthetic_a_chain_separates_this_window_from_new_events(
    repository,
):
    """
    🔴 **체인이 쌓이는 동안 세 갈래를 가른다** (합성 · 리뷰 C).

    6-AB 보완은 ``chain.is_empty`` **하나**로 판정해서 체인이 쌓이면
    **모든** 유발을 막았다. 그래서 한 사건이 유발 둘을 여는 경우 — 룰북이
    **같은 특수 체인**에 쌓는다고 적는 그 경우 (§*When multiple cards are
    activated simultaneously*) — 첫 발동 뒤 둘째가 후보에서 사라졌다
    (실측: 후보 1건 → 발동 뒤 0건, 보류도 없었다).

    지금은 :attr:`~engine.duel.Duel.chain_floor` 가 **같은 기회의 유발**과
    **체인 도중에 생긴 사건**을 가른다.

    ===================================  ==========================
    ``window_floor <= seq < chain_floor``  같은 기회 → 같은 체인에 쌓는다
    ``seq >= chain_floor``                 체인 도중 → 보존하고 기다린다
    ``seq < window_floor``                 지나간 창 → 끝났다
    ===================================  ==========================

    🔴 **빈 목록으로 통과할 수 없다** — 제안이 실제로 있는지, 체인이 실제로
    쌓였는지 먼저 단정한다 (6-AB 보완의 이 시험은 빈 ``for`` 를 돌았다).
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    base = duel._trigger_offers(MINE)
    assert len(base) == 1

    action = _trigger_action(duel)
    assert action is not None
    assert duel.apply(action).accepted is True
    #: 🔴 체인이 **실제로** 쌓였다.
    assert duel.chain.is_empty is False
    assert len(duel.chain) == 1
    assert duel.chain_floor >= 0

    same_window = dataclasses.replace(
        base[0], event_sequence=duel.chain_floor - 1
    )
    during_chain = dataclasses.replace(
        base[0], event_sequence=duel.chain_floor
    )
    past_window = dataclasses.replace(base[0], event_sequence=-1)

    #: 🔴 같은 기회의 유발 — **쌓을 수 있다.**
    assert duel._window_admits(same_window, MINE) is True
    assert duel._offer_is_activatable(same_window, MINE) is True
    #: 🔴 체인 도중의 사건 — **기다린다.**
    assert duel._window_admits(during_chain, MINE) is False
    #: 🔴 지나간 창 — **끝났다.**
    assert duel._window_admits(past_window, MINE) is False

    #: 그리고 체인 도중의 사건에는 그 이유가 적힌다. 빠진 규칙이 아니라
    #: **순서**이므로 ``missing`` 은 비어 있다.
    #:
    #: 🔴 **아직 쓰지 않은 기회로 물어야 한다.** 방금 발동한 효과의 기회는
    #: ``consumed_events`` 에 들어갔으므로 ``_trigger_offers`` 가 **아예
    #: 내놓지 않는다** — 그 제안으로 물으면 보류가 비어 통과한다 (처음에
    #: 그렇게 썼고 바로 드러났다). 그래서 **다른 효과 번호**로 바꾼다.
    unspent = dataclasses.replace(
        during_chain, effect_ref=EffectRef(GIRSU, 1)
    )
    waiting = dataclasses.replace(duel, triggers=_FixedOffers((unspent,)))
    assert len(waiting._trigger_offers(MINE)) == 1, "제안이 비면 아무것도 재지 않는다"
    deferred = [
        w
        for w in waiting.legal_actions(MINE).withheld
        if "체인이 처리 중입니다" in w.reason
    ]
    assert len(deferred) == 1
    assert deferred[0].missing is None
    assert "기회는 남아" in deferred[0].reason


@requires_official_db
def test_b05b_the_window_moves_to_the_chain_start_when_it_resolves(repository):
    """
    🔴 **체인이 해결되면 창이 그 체인의 시작점으로 옮겨간다** (리뷰 B · C).

    그 한 걸음이 둘을 동시에 만든다:

    · 체인을 **연** 기회의 사건은 **끝난다** — 그 기회에서 쓰지 않은 임의
      유발이 다시 나오지 않는다 (리뷰 B 가 가리킨 결함).
    · 체인 **도중에** 생긴 사건은 **남는다** — 그 체인이 모두 해결된 뒤에
      발동한다 (聖鳥クレイン 재정).

    🔴 실제 카드로 밟는다 — 소환 → 유발 발동 → 체인 해결. 바꿔 끼운 값이
    없다. 두 사건의 판정만 합성 번호로 확인한다 (``test_b04b`` 가 적은
    이유로, 체인 도중에 실제로 유발을 낳는 사건이 아직 없다).
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    base = duel._trigger_offers(MINE)
    assert len(base) == 1
    opened = max(duel.timing_floor, duel.window_floor)

    action = _trigger_action(duel)
    assert action is not None
    assert duel.apply(action).accepted is True
    chain_start = duel.chain_floor
    assert chain_start >= 0

    opener = dataclasses.replace(base[0], event_sequence=chain_start - 1)
    during = dataclasses.replace(base[0], event_sequence=chain_start)
    assert opener.event_sequence >= opened

    _settle(duel)
    #: 🔴 체인이 끝났고 창이 그 시작점으로 옮겨갔다.
    assert duel.chain.is_empty is True
    assert duel.chain_floor == -1
    assert duel.window_floor == chain_start

    #: 🔴 체인을 연 기회는 끝났다.
    assert duel._window_admits(opener, MINE) is False
    #: 🔴 체인 도중의 사건은 살아 있다 — 분실이 아니다.
    assert duel._window_admits(during, MINE) is True


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

    #: 🔴 **막을 행동을 사본에서 꺼낸다** (보완4). 원본에서는 유발 기회가
    #: 열려 있어 그 행동이 후보로 오르지 않고 (판이 열린 상태가 아니다),
    #: 원본에서 기회를 지나면 이 시험이 재려는 **강제 의무**가 사라진다.
    #: 사본은 판을 ``clone()`` 하므로 개체 번호가 같고, 그래서 거기서 꺼낸
    #: 행동을 원본에 그대로 제출할 수 있다.
    probe = Simulator(duel=setup.duel)._fork()
    assert _decline_window(probe) >= 1
    before = _other_action(probe)
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
    #: 🔴 **포기한 뒤에** 끼워 넣는다 (보완4 — ``_decline_window``).
    #: ``_mandatory_offers`` 는 포기를 보지 않으므로 (강제는 포기할 수
    #: 없다) 아래의 의무 단정은 그대로다.
    assert _decline_window(setup.duel) >= 1
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
def test_c06_synthetic_the_duty_seat_goes_first_and_that_is_ordering(
    repository,
):
    """
    🔴 **의무를 든 자리가 먼저 간다** (합성 · 6-AB 보완이 고친 자리).

    6-AB 의 이 시험은 *"차례가 아닌 자리에는 거짓 보류를 달지 않는다"* 를
    쟀다. 그 단정은 **당시의 구조**에 맞았지만 구조 자체가 틀렸다 — 그때는
    상대의 강제 의무를 **아무도 묻지 않았고**, 내 ``END_PHASE`` 가 수락되어
    ``timing_floor`` 가 그 의무를 지웠다 (실측: 상대 의무 1 → 0).

    근거는 룰북 ``TURN PLAYER'S PRIORITY`` 다: *"...except for effects that
    activate automatically, like Trigger or Flip effects."* 유발 효과는 턴
    플레이어 우선권의 **명시된 예외**이므로, 상대가 강제 유발을 들고 있으면
    내 턴이라도 그 처리가 먼저다.

    그래서 지금 재는 것은 둘이다 — :attr:`Duel.to_act` 가 의무를 든 자리를
    가리키는가, 그리고 다른 자리가 막힐 때 그 이유가 **순서**로 적히는가
    (``missing`` 을 비운다 — 빠진 규칙이 아니다).

    🔴 **영구 대기가 아니다.** 막는 조건이 :meth:`Duel._duty_seat` 에 묶여
    있고 그 함수는 **발동할 수 있는** 의무만 가리키므로, 막힌 자리가 생기면
    가리켜진 자리에는 반드시 고를 것이 있다. 아래에서 그것도 센다.
    """

    class _BothSeats:
        """어느 자리로 물어도 턴 플레이어의 제안을 강제로 돌려준다."""

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

    #: 🔴 의무를 든 자리를 가리킨다 — 턴 플레이어가 먼저다 (룰북
    #: §*When multiple cards are activated simultaneously*).
    assert duel._duty_seat() == MINE
    assert duel.to_act == MINE

    #: 🔴 그 자리에는 **고를 것이 있다** — 영구 대기가 아니다.
    mine = duel.legal_actions(MINE)
    assert mine.allowed
    assert all(
        a.kind is PlayerActionKind.ACTIVATE_EFFECT for a in mine.allowed
    )

    #: 🔴 다른 자리는 막히고, 이유는 **순서**다.
    theirs = duel.legal_actions(THEIRS)
    assert theirs.allowed == ()
    ordering = [
        w for w in theirs.withheld if "처리가 먼저입니다" in w.reason
    ]
    assert ordering, [w.reason for w in theirs.withheld]
    assert all(w.missing is None for w in ordering)
    #: 🔴 **거짓 보류가 없다** — 보장할 근거가 없는 것이 아니라 순서다.
    assert _withheld_for(duel, THEIRS, MANDATORY_TRIGGER_UNPLAYABLE) == []


@requires_official_db
def test_c06b_synthetic_the_opponents_duty_blocks_my_phase_change(repository):
    """
    🔴 **상대의 강제 의무를 ``END_PHASE`` 로 지나칠 수 없다** (합성).

    6-AB 의 실측 증상: 상대 의무가 1건 열려 있는데 내 ``END_PHASE`` 가
    **수락되고**, 페이즈가 넘어가면서 ``timing_floor`` 가 그 의무를 **0 으로
    지웠다.** 규칙이 요구한 처리가 조용히 사라진 것이다.

    🔴 **보완4가 이 시험의 합성을 고쳤다.** 전에는 상대의 제안이
    ``controller`` 만 바꾼 것이어서 **카드는 내 것**이었고, 그래서 발동
    관문이 *"자신이 쥐고 있는 카드가 아닙니다"* 로 거절했다 — 그 의무는
    처리할 수 **없는** 의무였다. 보완4 가 ``_window_can_act`` 로 "처리할 수
    있는 의무만 자리를 옮긴다" 를 구현하자 그 사실이 드러났다 (처리할 수
    없는 의무로 막으면 양쪽 모두 고를 것이 없어 듀얼이 멈춘다).

    그래서 이제 **상대 자리에 실제 카드 개체를 놓는다** — 상대의 덱에서
    기르수 한 장을 자기 몬스터 존으로 옮기고, 그 개체를 제안의 ``source``
    로 쓴다. 바꾸는 것은 **보드 배치와 제안의 자리 · 필수 여부**이고,
    허가 · 체인 링크 · 최종 상태는 엔진이 만든다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    theirs = next(
        card
        for card in setup.duel.state.player(THEIRS).zone(Zone.DECK)
        if card is not None and card.card_id == GIRSU
    )
    setup.duel.state.move(
        theirs, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK
    )

    class _TheirDuty:
        """상대 자리에만, **상대의 카드로** 강제 의무를 내놓는다."""

        def __init__(self, repo):
            self._inner = TriggerSource(repo)

        def offers(self, duel, seat: int):
            if seat != THEIRS:
                return ()
            return tuple(
                dataclasses.replace(
                    offer,
                    requirement=TriggerRequirement.MANDATORY,
                    controller=THEIRS,
                    source=theirs.instance_id,
                )
                for offer in self._inner.offers(duel, MINE)
            )

    duel = dataclasses.replace(setup.duel, triggers=_TheirDuty(repository))
    #: 🔴 그 의무는 **처리할 수 있다** — 그러지 않으면 막을 근거가 없다.
    assert duel._window_can_act(THEIRS) is True

    assert len(duel._mandatory_offers(THEIRS)) == 1
    assert duel._mandatory_offers(MINE) == ()
    #: 🔴 상대가 간다 — 내 턴인데도.
    assert duel.to_act == THEIRS
    assert duel.turn_player == MINE

    #: 🔴 내 ``END_PHASE`` 가 거절된다.
    before_phase = duel.state.turn.phase
    step = duel.apply(PlayerAction.end_phase(actor=MINE))
    assert step.accepted is False
    assert duel.state.turn.phase is before_phase
    #: 🔴 그래서 의무가 살아 있다.
    assert len(duel._mandatory_offers(THEIRS)) == 1


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


# ======================================================================
# E. 정책 격리 — 사본이 부모의 정책을 밀지 않는가 (6-AB 보완)
# ======================================================================


class _StatefulNoFork:
    """
    상태를 들고 있으면서 ``forked()`` 를 **주지 않는** 정책.

    6-AB 는 이런 정책을 사본에 **그대로 공유했고**, 그 근거는 "모양이
    ``choose(request)`` 하나뿐이니 기록을 가졌는지 알 방법이 없다" 였다.
    🔴 그 추론이 거꾸로였다 — 알 수 없으면 공유가 아니라 **보류**가 안전한
    쪽이다.
    """

    name = "stateful-no-fork"

    def __init__(self) -> None:
        self.calls = 0

    def accept_offer(self, offer) -> bool:
        self.calls += 1
        return True

    def choose_cards(self, offer):
        self.calls += 1
        return (offer.candidates[0].instance,) if offer.candidates else ()


@requires_official_db
def test_e01_a_fork_does_not_advance_a_stateful_policy(repository):
    """
    🔴 **사본이 부모의 정책 상태를 밀지 않는다** (리뷰 지적 F · 실측).

    6-AB 의 증상: 상태 있는 정책으로 ``Simulator.simulate`` 를 한 번 돌리자
    부모 정책의 호출 수가 **0 → 1** 이 됐다. 사본은 미래를 **재기만** 해야
    하는데 부모를 앞으로 밀었고, 그러면 같은 자리에서 실제로 두었을 때 다른
    답이 나온다.
    """
    selector = _StatefulNoFork()
    setup, chooser = _board(repository, selector=selector)
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None
    assert selector.calls == 0

    result = Simulator(duel).simulate(action, viewer=MINE)
    assert result.status is SimulationStatus.SUPPORTED

    #: 🔴 부모의 정책이 그대로다.
    assert selector.calls == 0
    assert chooser.records == ()


@requires_official_db
def test_e02_a_non_forkable_chooser_is_refused_not_shared(repository):
    """
    🔴 **``forked()`` 를 주지 않는 정책은 사본이 쓰지 않는다** — 그리고 그
    거절이 **결과에 보인다.**

    조용히 공유하면 오염이 보이지 않는다. 거절은 보인다. 그래서 사본은
    고르는 사람 없이 돌고, 아직 정해지지 않은 선택이 거절된다.
    """
    setup, _ = _board(repository, selector=_StatefulNoFork())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None

    assert Simulator(duel)._forked_chooser() is None
    result = Simulator(duel).simulate(action, viewer=MINE)
    #: 🔴 발동은 되고 **해결이 거절된다** — 그 사실이 이유에 적힌다.
    assert result.status is SimulationStatus.SUPPORTED
    assert "아직 고르지 않은" in (result.reason or "")


@requires_official_db
def test_e03_a_forkable_policy_lets_the_fork_resolve(repository):
    """
    🔴 **무상태 정책은 ``forked()`` 로 그 사실을 말하고, 사본은 해결까지 간다.**

    프로덕션 배선이 쓰는 정책이 이쪽이다 (``app.main.opening_wiring`` 의
    :class:`~agent.choice.FirstPermittedChoice`). 그래서 6-AB 가 고친
    "사본이 원본보다 못 해결한다" 는 **그대로 고쳐져 있다.**
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None

    forked = chooser.forked()
    assert forked is not None
    assert forked is not chooser
    assert forked.records == ()

    result = Simulator(duel).simulate(action, viewer=MINE)
    assert result.status is SimulationStatus.SUPPORTED
    assert "해결했습니다" in (result.reason or "")
    #: 🔴 사본이 물었는데도 부모의 기록은 비어 있다.
    assert chooser.records == ()


def test_e04_the_random_policy_forks_without_moving_its_parent():
    """
    🔴 **상태 있는 정책은 사본용 사본을 만든다** — 부모의 난수원을 뽑지 않는다.

    부모의 난수원에서 씨앗을 뽑으면 **뽑는 순간** 부모가 앞으로 밀린다.
    그것이 고치려는 결함이므로, 씨앗은 *지금까지 뽑은 횟수*에서 만든다.
    """
    parent = RandomChoice(seed=11)
    first, second = parent.forked(), parent.forked()

    #: 🔴 부모가 움직이지 않았다.
    assert parent.draws == 0
    #: 다른 객체이고, 같은 자리에서는 같은 사본이 나온다 (재현된다).
    assert first is not second
    assert first.name == second.name

    empty = types.SimpleNamespace(permitted=(), candidates=(), minimum=0)
    first.accept_offer(empty)
    assert first.draws == 1
    #: 🔴 사본이 뽑아도 부모는 그대로다.
    assert parent.draws == 0


@requires_official_db
def test_e05_sibling_forks_do_not_share_declined_opportunities(repository):
    """
    🔴 **창 상태도 형제 분기를 넘지 않는다** (6-AB 추가 보완의 새 칸).

    :attr:`~engine.duel.Duel.window_floor` · :attr:`~engine.duel.Duel.chain_floor`
    는 ``int`` 이므로 ``dataclasses.replace`` 가 값으로 가져간다 —
    ``consumed_events`` 와 같은 규율이다 (6-AA ``test_d04``). 6-AB 보완의
    ``declined_events`` 를 대체한 칸들이 그 규율을 따르는지 센다.
    """
    setup, _ = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    opened = duel.window_floor

    sim = Simulator(duel)
    left, right = sim._fork(), sim._fork()

    #: 🔴 **포기도 창 상태다** (보완4가 더한 ``window_passed``). 한쪽에서
    #: 포기하고 판을 바꾸는 행동까지 밟는다 — 포기는 ``window_passed`` 에,
    #: 그 행동은 ``window_floor`` 에 적히므로 **두 칸을 함께** 센다.
    assert _decline_window(left) >= 1
    other = _other_action(left)
    assert other is not None
    assert left.apply(other).accepted is True

    #: 🔴 한쪽만 창이 옮겨갔다.
    assert left.window_floor > opened
    assert right.window_floor == opened
    assert duel.window_floor == opened
    #: 🔴 포기 기록도 넘지 않았다 — ``frozenset`` 을 갈아 끼우므로.
    assert right.window_passed == frozenset()
    assert duel.window_passed == frozenset()
    #: 🔴 그래서 형제는 아직 발동할 수 있고 부모도 그렇다.
    assert _trigger_action(left) is None
    assert _trigger_action(right) is not None
    assert _trigger_action(duel) is not None


# ======================================================================
# F. 실제 카드 · 정상 경로 — 합성이 아니다
# ======================================================================


@requires_official_db
def test_f01_the_real_card_path_still_resolves_deck_to_grave(repository):
    """
    🔴 **실제 카드 · 정상 경로가 그대로 돈다** — 이번 수정이 깨뜨리지 않았다.

    기르수 소환 → 유발 발동 (``legal_actions`` → ``apply``) → 해결 중
    ``PolicyChooser`` 가 카드를 고름 → 덱에서 묘지로.

    🔴 **합성이 아니다.** 바꿔 끼운 값이 하나도 없고, 행동은 모두
    ``legal_actions`` 을 지난다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    grave_before = len(duel.state.player(MINE).zone(Zone.GRAVE))
    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))

    _summon(duel)
    action = _trigger_action(duel)
    assert action is not None
    assert duel.apply(action).accepted is True
    _settle(duel)

    #: 🔴 **고른 것은 정책이다** — 엔진이 대신 고르지 않았다.
    assert len(chooser.records) == 1
    chosen = chooser.records[0].chosen
    assert len(chosen) == 1

    #: 🔴 그리고 그 카드가 실제로 덱에서 묘지로 갔다.
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before + 1
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before - 1
    grave = duel.state.player(MINE).zone(Zone.GRAVE)
    assert [c.instance_id for c in grave] == list(chosen)


@requires_official_db
def test_f02_the_real_card_opportunity_opens_once_and_closes(repository):
    """
    🔴 **실제 카드로 수명 전체를 밟는다** — 사건 → 기회 → 발동 → 종료 → 진행.

    발동으로 닫는 쪽이다 (포기로 닫는 쪽은 ``test_b02`` · ``test_c05``).
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel

    #: ① 사건 전 — 기회가 없다.
    assert duel._trigger_offers(MINE) == ()

    #: ② 사건 → 기회 개시.
    _summon(duel)
    assert len(duel._trigger_offers(MINE)) == 1
    assert _trigger_action(duel) is not None

    #: ③ 발동.
    action = _trigger_action(duel)
    assert duel.apply(action).accepted is True
    #: 체인 처리 중에는 발동이 열리지 않는다.
    assert duel.chain.is_empty is False
    _settle(duel)

    #: ④ 기회 종료 — 소비로 닫혔고, 체인이 해결돼 창도 옮겨갔다.
    assert len(duel.consumed_events) == 1
    assert duel.chain_floor == -1
    assert duel.window_floor >= 1
    assert _trigger_action(duel) is None

    #: ⑤ 다음 진행 — 흐름이 돌아왔다.
    resumed = duel.legal_actions(MINE)
    assert any(
        a.kind is not PlayerActionKind.ACTIVATE_EFFECT for a in resumed.allowed
    )
