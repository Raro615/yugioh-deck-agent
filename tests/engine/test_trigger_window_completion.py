"""
Phase 6-AB 최종 보완 — **양측 유발 기회 · 체인 등재 · 미지원 전파.**

6-AB 추가 보완이 남긴 넷을 재는 파일이다.

    ①  ``_window_admits`` 가 체인이 열려 있으면 ``sequence <
       self.chain_floor`` 만 보고 ``_missed_timing`` 을 **건너뛰었다.**
       그래서 판정 불가(``UNKNOWN``) 제안이 *다른 효과가 세운 체인* 덕에
       "그 창의 사건" 으로 읽힐 자리가 있었다
    ②  ``window_floor`` 가 **자리 구분 없는 한 값**이어서, 내 행동 하나가
       상대의 임의 유발 창을 같이 닫았다 (BLOCKER-F2-1)
    ③  "같은 기회의 유발 둘을 한 체인에" 가 ``_window_admits`` 의 ``True``
       확인에서 끝났고, **실제 링크 2개와 역순 해결**을 통과한 적이 없었다
       (BLOCKER-F2-2)
    ④  ``deck/opening.py`` 가 *"남은 후보가 흐름뿐"* 을 **보류를 보지 않고**
       정상 종료 문장으로 적었다. 미지원 사유가 Simulator 와 ``/combo``
       까지 가지 않았다

여섯 군으로 나눈다.

================  ==================================================
A. 등록 자격        체인 유무와 **무관하게** 자격을 먼저 보는가
B. 양측 기회        두 자리의 기회를 각각 보장하고 **종료**하는가
C. 체인 등재        실제 경로로 링크 2개가 쌓이고 역순으로 풀리는가
D. 미지원 전파      실행에 영향을 준 미지원이 밖까지 가는가
E. 사본            새 상태(``window_passed``)가 새지 않는가
F. 보존            실제 카드 경로와 ``/combo`` 가 그대로인가
================  ==================================================

🔴 **C 군은 합성 검증이다.** 이 저장소에 실행 구현이 등재된 유발 효과는
기르수 ① 하나이고 (6-Z ``test_c09``), **카드명별 횟수 제한을 지키면서**
같은 기회에 둘을 올릴 실제 카드 조합이 없다. 그래서 C 군은 기존
``EffectDefinition`` 과 공통 연산(``DrawOperation``) 하나로 만든 최소
합성 효과를 **같은 카드 개체의 둘째 효과 칸**에 붙여 엔진 통합 경로를
센다. 허가 · 체인 링크 · 최종 상태를 주입하지 않는다 — 실제 사건 ·
후보 생성 · 관문 · ``Duel.apply`` · ``ChainResolver`` 를 모두 지난다.
**실제 카드 지원이 완료되었다는 뜻이 아니다.**

🔴 **합성 효과가 기르수 ②의 실제 효과를 주장하지 않는다.** 붙인 조작은
룰북의 드로우 하나이고, 기르수의 둘째 효과와 아무 관계가 없다. 이름에
``synthetic`` 을 달아 둔 시험이 그것이다.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import FirstPermittedChoice
from agent.simulation import SimulationError, SimulationResult, Simulator
from agent.simulation import SimulationStatus
from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.chain import ChainResolver
from engine.condition import PlayerRef, ZoneCountAtLeast
from engine.duel import (
    TRIGGER_IMPLEMENTATION_MISSING,
    TRIGGER_WORDING_MISSING,
    LegalActions,
    WithheldAction,
)
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.journal import EffectEvent
from engine.effect.library import (
    EFFECT_LIBRARY,
    OPERATION_RULINGS,
    LibraryEntry,
    build_executor,
)
from engine.effect.operation import DrawOperation
from engine.ids import EffectRef
from engine.payment import CostPayer
from engine.trigger import TriggerRequirement
from engine.trigger_compiler import TEXT_IF, TEXT_WHEN, wording_from
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import ActivationKind, Zone

from integration.autonomy import PolicyChooser, TriggerSource
from tests.conftest import requires_official_db
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    MINE,
    THEIRS,
    _board,
    _settle,
    _summon,
)

#: 합성 효과가 앉는 칸 — **같은 카드 개체의 둘째 효과**다.
SYNTH_REF = EffectRef(GIRSU, 1)
#: 실제 기르수 ①.
REAL_REF = EffectRef(GIRSU, 0)


# ======================================================================
# 공용 도구
# ======================================================================
#: 🔴 **합성 — 룰북의 드로우 하나.** 기르수 ②의 실제 효과가 아니다.
#:
#: 왜 드로우인가: 대상 선택이 없고 (해결 시점 선택이 끼어들지 않는다) 판의
#: 다른 카드를 보지 않으므로, **역순 해결이 실제로 일어났는지**를 가리는
#: 것이 없다. 묘지로 보내는 효과를 둘 쌓으면 둘째 해결이
#: ``BoardRuling._interference`` 에서 ``UNKNOWN`` 이 된다 — 먼저 풀린 링크가
#: 묘지에 넣은 카드에 대해 "그것이 막는지" 확인된 것이 없기 때문이고
#: (실측), 그것은 엔진의 올바른 보수적 답이므로 우회하지 않는다.
SYNTH_DEFINITION = EffectDefinition(
    effect_ref=SYNTH_REF,
    source_card_id=GIRSU,
    targets=(),
    operations=(DrawOperation(count=1, who=PlayerRef.CONTROLLER),),
    activation=ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.DECK, 1),
    activation_kind=ActivationKind.TRIGGER,
    provenance=EffectProvenance.hand_written(
        verified=True,
        note=(
            "합성 — 같은 기회의 유발 둘을 한 체인에 쌓아 역순으로 해결하는 "
            "경로를 재기 위한 최소 효과다. 조작은 룰북의 드로우 하나이고 "
            "대상 선택이 없다. 🔴 기르수의 둘째 효과가 아니고, 어떤 실제 "
            "카드의 효과도 주장하지 않는다."
        ),
    ),
)

SYNTH_ENTRIES = EFFECT_LIBRARY + (
    LibraryEntry(
        definition=SYNTH_DEFINITION,
        lua_file="(합성)",
        lua_excerpt="(합성 — 드로우 1장. 실제 카드 효과가 아니다)",
        executable=True,
    ),
)
SYNTH_DEFINITIONS = EffectDefinitionRegistry(
    tuple(entry.definition for entry in SYNTH_ENTRIES)
)


class _Pair:
    """
    🔴 **합성 — 같은 실제 사건에서 제안 둘.**

    실제 :class:`~integration.autonomy.TriggerSource` 가 만든 제안을 받아
    **효과 칸만** 바꿔 하나를 더 낸다. 사건 · 사건 번호 · 카드 개체 ·
    자리는 전부 실제 값이고, 관문도 엔진의 것 그대로다.

    ``replacements`` 를 주면 **실제 효과 쪽 제안에만** 적용한다 — 그러면
    "자격 없는 제안 하나와 자격 있는 제안 하나" 가 같은 창에 있는 자리를
    만들 수 있고, 그것이 ①을 재는 자리다.
    """

    def __init__(self, repository, **replacements):
        self._inner = TriggerSource(repository)
        self._replacements = replacements

    def offers(self, duel, seat: int):
        out = []
        for offer in self._inner.offers(duel, seat):
            out.append(dataclasses.replace(offer, effect_ref=SYNTH_REF))
            out.append(
                dataclasses.replace(offer, **self._replacements)
                if self._replacements
                else offer
            )
        return tuple(out)


def _wired_pair(duel, chooser, repository, **replacements):
    """
    합성 효과를 **그 판의 등록부에** 꽂은 사본.

    🔴 프로덕션 등록부를 건드리지 않는다. 꽂는 것은 이 판의 발동기 ·
    해결기 · 유발 원천 세 칸뿐이고, 해결 시점 선택을 옮기는
    :class:`~integration.autonomy.PolicyChooser` 에도 **같은 등록부**를
    준다 — 그러지 않으면 해결 중의 물음이 프로덕션 등록부를 되묻고
    "정의가 없습니다" 로 끝난다 (실측).
    """
    implementations = EffectImplementationRegistry()
    for entry in SYNTH_ENTRIES:
        if entry.executable:
            implementations.register(entry.effect_ref)
    if chooser is not None:
        chooser.definitions = SYNTH_DEFINITIONS
    return dataclasses.replace(
        duel,
        _activator=EffectActivator(
            SYNTH_DEFINITIONS,
            implementations,
            payer=CostPayer(journal=duel.journal),
        ),
        _resolver=ChainResolver(
            build_executor(
                journal=duel.journal,
                entries=SYNTH_ENTRIES,
                rulings=OPERATION_RULINGS,
                chooser=chooser,
            ),
            SYNTH_DEFINITIONS,
        ),
        triggers=_Pair(repository, **replacements),
    )


def _paired_board(repository, **replacements):
    """소환까지 끝나고 제안 둘이 열린 판."""
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = _wired_pair(setup.duel, chooser, repository, **replacements)
    return duel, chooser


def _activations(duel, seat: int = MINE):
    return [
        action
        for action in duel.legal_actions(seat).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


def _offer_for(duel, effect_ref, seat: int = MINE):
    return next(
        offer
        for offer in duel._trigger_offers(seat)
        if offer.effect_ref == effect_ref
    )


def _snapshot(duel, seat: int = MINE):
    player = duel.state.player(seat)
    return (
        len(player.zone(Zone.GRAVE)),
        len(player.zone(Zone.DECK)),
        len(player.zone(Zone.HAND)),
    )


class _TheirOptional:
    """
    🔴 **합성 — 상대 자리에만 임의 유발 제안 하나.**

    바꾸는 것은 제안의 자리(``controller``)와 필수 여부 두 값뿐이다.
    ``_TheirDuty`` (6-AB) 와 같은 방식이고, 다른 것은 **강제가 아니라
    임의**라는 점이다 — ②가 닫아 버린 창이 바로 그것이다.
    """

    def __init__(self, repository):
        self._inner = TriggerSource(repository)

    def offers(self, duel, seat: int):
        if seat != THEIRS:
            return ()
        return tuple(
            dataclasses.replace(
                offer,
                requirement=TriggerRequirement.OPTIONAL,
                controller=THEIRS,
            )
            for offer in self._inner.offers(duel, MINE)
        )


class _BothOptional:
    """🔴 **합성 — 두 자리에 각각 임의 유발 제안 하나.**"""

    def __init__(self, repository):
        self._inner = TriggerSource(repository)

    def offers(self, duel, seat: int):
        return tuple(
            dataclasses.replace(
                offer,
                requirement=TriggerRequirement.OPTIONAL,
                controller=seat,
            )
            for offer in self._inner.offers(duel, MINE)
        )


def _their_board(repository, source_factory):
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    return dataclasses.replace(setup.duel, triggers=source_factory(repository))


# ======================================================================
# A. 등록 자격 — 체인 유무와 무관하게 자격을 먼저 본다
# ======================================================================


@requires_official_db
def test_a01_the_eligibility_is_asked_in_one_place(repository):
    """
    🔴 **자격은 체인 유무와 무관하게 한 자리가 답한다** (①).

    고친 전의 코드는 체인이 열리면 ``return sequence < self.chain_floor``
    로 **끝냈다.** 그 식은 "이 창의 사건인가" 만 묻고 자격을 묻지 않는다 —
    그래서 같은 창의 사건이기만 하면 **어휘를 읽지 못한 제안도** ``True``
    를 받을 수 있었다. 지금은 그 분기가 ``False`` 만 돌려주고 나머지는
    자격 검사로 떨어진다.

    세 띠를 센다. 사건 번호를 **그 창의 마지막 사건이 아닌** 자리에 두어야
    어휘가 답을 가르므로 (마지막 사건이면 「때」도 「경우」도 놓치지
    않는다) 사건 번호와 어휘 두 값만 바꾼 합성 제안을 쓴다 — 실측으로 이
    저장소의 실제 경로에서는 창이 사건 하나만 들고 (``test_b04b``) 그
    자리가 저절로 생기지 않는다.

    ================================  =========  =========  =========
    띠                                  「경우」     「때」      읽지 못함
    ================================  =========  =========  =========
    지나간 창 (``seq < floor``)         ``False``  ``False``  ``False``
    체인 없음 · 마지막이 아닌 사건        ``True``   ``False``  ``None``
    체인 도중의 사건 (``>= floor``)      ``False``  ``False``  ``False``
    ================================  =========  =========  =========

    🔴 **셋째 열이 ①이다** — 어느 띠에서도 허가가 되지 않는다.

    🔴 **셋째 줄의 ``False`` 는 "자격 없음" 이 아니다.** 체인 도중에 생긴
    사건은 그 체인이 전부 풀린 **뒤의** 기회에서 처리한다 (OCG 카드
    데이터베이스 cid=5883 「聖鳥クレイン」 2021-07-01 보충). 그 제안이
    **다음 창에서** 허가되는 것을 ``test_c02`` 가 센다.
    """
    wordings = (
        ("경우", wording_from(TEXT_IF), True),
        ("때", wording_from(TEXT_WHEN), False),
        ("읽지 못함", None, None),
    )
    for label, wording, eligible in wordings:
        duel, _ = _paired_board(repository, wording=wording)
        base = _offer_for(duel, REAL_REF)
        floor = max(duel.timing_floor, duel.window_floor)

        #: ① 지나간 창.
        past = dataclasses.replace(base, event_sequence=floor - 1)
        assert duel._window_admits(past, MINE) is False, label

        #: ② 체인이 없고 그 사건이 마지막이 아니다 — 어휘가 답을 가른다.
        assert duel.chain.is_empty
        not_last = dataclasses.replace(
            base, event_sequence=duel._window_horizon() + 1
        )
        assert duel._window_admits(not_last, MINE) is eligible, label

        #: ③ 체인을 **정상 경로로** 열고, 체인 도중의 사건을 묻는다.
        synthetic = next(
            a for a in _activations(duel) if a.effect_ref == SYNTH_REF
        )
        assert duel.apply(synthetic).accepted is True
        assert len(duel.chain) == 1 and duel.chain_floor >= 0
        during = dataclasses.replace(
            base, event_sequence=duel.chain_floor + 1
        )
        assert duel._window_admits(during, MINE) is False, label

        #: 🔴 **같은 창의 다른 유발은 자격 검사로 떨어진다** — 체인이
        #: 열렸다는 이유로 끝나지 않는다. 실측으로 그 사건은 그 창의
        #: 마지막이므로 세 어휘 모두 자격이 있다.
        same_window = _offer_for(duel, REAL_REF)
        assert same_window.event_sequence < duel.chain_floor
        assert duel._window_admits(same_window, MINE) is True, label


@requires_official_db
def test_a02_an_unknown_offer_never_becomes_permission(repository):
    """
    🔴 **판정 불가 제안이 어떤 띠에서도 허가가 되지 않는다** (①).

    그리고 **두 자리가 같은 답을 한다.** 내부 판정
    (:meth:`~engine.duel.Duel._window_admits`) 과 후보 목록의 보류가
    갈라지면 어느 쪽이 진짜인지 말할 수 없다 — 6-AB 보완이 바로 그 상태
    였다 (내부는 ``True``, 목록은 보류).

    세 자리에서 센다 — 자격 판정 · 후보 목록 · **직접** ``Duel.apply``.
    마지막이 중요하다: 후보 목록에 없다는 이유로 막는 것은 호출 순서에
    의존하는 안전이다 (6-AB A 가 세운 기준).
    """
    duel, _ = _paired_board(repository, wording=None, event_sequence=1)
    unknown = _offer_for(duel, REAL_REF)
    action = PlayerAction.activate_effect(
        actor=MINE, source=unknown.source, effect_ref=REAL_REF
    )

    #: ① 체인이 없을 때 — 자격 판정이 ``None`` 이고 후보가 아니다.
    assert duel._window_admits(unknown, MINE) is None
    assert duel._offer_is_activatable(unknown, MINE) is False
    assert [a.effect_ref for a in _activations(duel)] == [SYNTH_REF]
    assert [
        held
        for held in duel.legal_actions(MINE).withheld
        if held.missing == TRIGGER_WORDING_MISSING
    ]

    #: 🔴 직접 넣어도 거절된다.
    before = duel.state.state_hash()
    assert duel.apply(action).accepted is False
    assert duel.state.state_hash() == before
    assert duel.chain.is_empty

    #: ② **다른 효과로 체인을 연 뒤에도** 허가가 되지 않는다.
    synthetic = next(a for a in _activations(duel) if a.effect_ref == SYNTH_REF)
    assert duel.apply(synthetic).accepted is True
    assert not duel.chain.is_empty

    still = _offer_for(duel, REAL_REF)
    assert duel._window_admits(still, MINE) is not True
    assert duel._offer_is_activatable(still, MINE) is False
    assert [a.effect_ref for a in _activations(duel)] == []

    #: 🔴 그리고 **왜** 오르지 못했는지가 적힌다 — 기회는 보존되지만
    #: 발동은 그 체인 뒤다 (``_trigger_actions`` 와 같은 답).
    held = duel.legal_actions(MINE).withheld
    assert [w for w in held if "체인이 처리 중" in w.reason]

    #: 🔴 직접 넣어도 거절되고 체인 링크가 늘지 않는다.
    links = len(duel.chain)
    state = duel.state.state_hash()
    assert duel.apply(action).accepted is False
    assert len(duel.chain) == links
    assert duel.state.state_hash() == state


@requires_official_db
def test_a03_an_eligible_second_offer_does_not_expire_when_a_chain_opens(
    repository,
):
    """
    🔴 **자격이 있는 둘째 제안은 체인이 열려도 만료되지 않는다** (①).

    ①을 고치는 방향을 거꾸로 틀면 이것이 깨진다 — 자격을 먼저 보되 그
    뒤에 체인 단계를 **잘못** 물으면 같은 기회의 둘째 유발이 "지나간 창"
    으로 읽힌다. 그러면 ③이 영원히 불가능하다.

    그리고 **체인이 풀린 뒤에는** 창이 체인 시작점으로 옮겨 가므로 같은
    제안이 더 이상 허가되지 않는다 — 그것이 기회의 종료다.
    """
    duel, _ = _paired_board(repository)
    first = next(a for a in _activations(duel) if a.effect_ref == SYNTH_REF)
    assert duel.apply(first).accepted is True

    offer = _offer_for(duel, REAL_REF)
    assert duel._window_admits(offer, MINE) is True
    assert duel._offer_is_activatable(offer, MINE) is True

    second = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    assert duel.apply(second).accepted is True
    for step in _settle(duel):
        assert step.accepted is True

    #: 🔴 해결 뒤에는 창이 옮겨 갔다.
    assert duel.chain.is_empty
    assert duel.window_floor >= 0
    #: 🔴 **정정 (Phase 6-AC): 그 **두 제안**이 더 이상 허가되지 않는다.**
    #:
    #: 전에는 ``_activations(duel) == []`` 로 셌고, 그 식이 참이었던 것은
    #: **후속 유발의 실행 구현이 없었기** 때문이다. 6-AC 가 성유물－『성장』
    #: ① 을 등재했으므로, 기르수 ① 의 해결이 만든 **새 사건**(덱 → 묘지)이
    #: 새 제안을 연다 — 그것은 기회의 종료가 깨진 것이 **아니라** 다른
    #: 기회가 열린 것이고, ``test_followup_trigger_integration`` 이 재는
    #: 바로 그 경로다.
    #:
    #: 그래서 재는 것을 **이 기회의 두 제안**으로 좁힌다.
    assert {a.effect_ref for a in _activations(duel)} & {
        SYNTH_REF,
        REAL_REF,
    } == set()


# ======================================================================
# B. 양측 기회 — 두 자리를 각각 보장하고 종료한다
# ======================================================================


@requires_official_db
def test_b01_synthetic_the_opponents_optional_window_blocks_my_turn(
    repository,
):
    """
    🔴 **상대의 임의 유발 기회가 내 통상 행동과 페이즈 이동을 막는다** (②).

    근거는 룰북 ``TURN PLAYER'S PRIORITY`` 다 — *"the opponent cannot
    activate cards or effects, **except for effects that activate
    automatically, like Trigger or Flip effects**."* 유발은 턴 플레이어
    우선권의 **명시된 예외**이므로, 상대가 처리할 기회를 들고 있으면 내
    행동이 그것을 지나칠 수 없다.

    ②의 증상: ``window_floor`` 가 자리 구분 없는 한 값이어서 **내 행동
    하나가 상대의 창을 같이 닫았다.** 강제는 ``_duty_seat`` 가 막고
    있었으므로 (6-AB C) 남아 있던 구멍은 **임의**였다.
    """
    duel = _their_board(repository, _TheirOptional)
    #: 🔴 상대에게 처리할 것이 있고, 내게는 없다.
    assert duel._window_claims(THEIRS)
    assert duel._window_claims(MINE) == ()
    assert duel._window_actor() == THEIRS
    assert duel.to_act == THEIRS
    assert duel.turn_player == MINE

    #: 🔴 내 자리는 막히고, 이유는 **순서**다 — 빠진 규칙이 아니다.
    mine = duel.legal_actions(MINE)
    assert mine.allowed == ()
    ordering = [w for w in mine.withheld if "기회가 아직 열려" in w.reason]
    assert ordering, [w.reason for w in mine.withheld]
    assert all(w.missing is None for w in ordering)
    #: 🔴 **순서로 막은 것은 미지원이 아니다.** 같은 자리에 이 Phase 와
    #: 무관한 미지원 보류가 따로 있을 수 있고 (실측: ``activate_card`` 의
    #: 남은 적법성 계층), 그것과 섞이지 않아야 한다.
    assert not set(ordering) & set(mine.unsupported())

    #: 🔴 ``END_PHASE`` 로 지나칠 수 없다.
    before = duel.state.turn.phase
    step = duel.apply(PlayerAction.end_phase(actor=MINE))
    assert step.accepted is False
    assert duel.state.turn.phase is before
    assert duel._window_claims(THEIRS)


@requires_official_db
def test_b02_synthetic_a_pass_is_a_decline_and_the_turn_comes_back(
    repository,
):
    """
    🔴 **상대가 포기하면 기회가 끝나고 내 차례가 돌아온다** (②).

    ``PASS`` 가 여기서 뜻하는 것은 **이 유발 처리 기회에서 발동하지
    않는다**다. 우선권이 열려 있을 때의 ``PASS`` (체인 응답) 와 **다른
    일**이고, 자리에 따라 갈라진다 — 그 구분을 ``test_b04`` 가 센다.

    그리고 영구 대기가 아님을 센다: 포기 뒤에 내 행동이 실제로 수락된다.
    """
    duel = _their_board(repository, _TheirOptional)
    passing = PlayerAction.passing(actor=THEIRS)
    assert passing in duel.legal_actions(THEIRS).allowed

    step = duel.apply(passing)
    assert step.accepted is True
    assert step.code is ValidationCode.OK
    assert "발동하지 않기로" in step.reason

    #: 🔴 그 자리의 기회가 끝났다.
    assert THEIRS in duel.window_passed
    assert duel._window_claims(THEIRS) == ()
    assert duel._window_actor() is None
    assert duel.to_act == MINE

    #: 🔴 **정정 (보완5).** 보완4 는 여기서 곧바로 ``end_phase`` 를
    #: 요구했고, 그래서 *"포기는 거절이고 차례가 돌아온다"* 가 **판이 열린
    #: 상태로 돌아온다**는 뜻으로 적혀 있었다. 차례는 돌아온다 — 그러나
    #: 돌아온 자리는 **빠른 효과 기회**다 (공식 도표의 상자 B).
    mine = duel.legal_actions(MINE)
    assert mine.allowed
    assert sorted({a.kind.value for a in mine.allowed}) == ["pass"]
    before = duel.state.turn.phase
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is False
    #: 양측이 그 기회를 지나가면 흐름이 돌아온다.
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is True
    assert duel.state.turn.phase is not before


@requires_official_db
def test_b03_synthetic_both_seats_choose_and_the_flow_returns(repository):
    """
    🔴 **두 자리가 각각 고르고 정상 흐름으로 돌아온다** (②).

    두 조합을 센다 — 둘 다 포기, 그리고 턴 플레이어가 발동하고 상대가
    응답을 포기. 어느 쪽이든 끝에서 **통상 진행 후보가 다시 열린다.**
    """
    #: ① 둘 다 포기.
    duel = _their_board(repository, _BothOptional)
    assert duel._window_actor() == MINE  # 턴 플레이어가 먼저다
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert duel._window_actor() == THEIRS
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True
    assert duel.window_passed == frozenset({MINE, THEIRS})
    assert duel._window_actor() is None
    assert duel.to_act == MINE
    assert duel.legal_actions(MINE).allowed

    #: ② 턴 플레이어가 발동한다.
    duel2 = _their_board(repository, _BothOptional)
    mine = _activations(duel2, MINE)
    assert mine, duel2.legal_actions(MINE).withheld
    assert duel2.apply(mine[0]).accepted is True
    assert duel2.priority.is_open
    for step in _settle(duel2):
        assert step.accepted is True
    assert duel2.chain.is_empty
    #: 🔴 체인이 풀린 뒤 창이 옮겨 가고 흐름이 돌아온다.
    assert duel2.window_passed == frozenset()
    assert duel2.legal_actions(duel2.to_act).allowed


@requires_official_db
def test_b04_synthetic_a_pass_means_what_the_step_says_it_means(repository):
    """
    🔴 **``PASS`` 가 단계에 따라 다른 일을 한다** (②).

    세 단계가 있다.

    ====================  =============================================
    우선권이 열려 있다      체인 응답의 포기 — ``priority.passed()``
    우선권이 닫혀 있고      **유발 처리 기회의 포기** — ``window_passed``
    내 창에 처리할 것이
    있다
    둘 다 아니다           통상 우선권 넘김
    ====================  =============================================

    같은 행위가 단계를 보지 않고 한 가지 일만 하면, 유발을 포기한 것이
    체인 응답을 포기한 것으로 적히거나 그 반대가 된다.
    """
    #: ① 우선권이 닫혀 있고 내 창에 처리할 것이 있다 → 유발 포기.
    declining = _their_board(repository, _BothOptional)
    assert declining.priority.is_open is False
    assert declining._window_claims(MINE)
    step = declining.apply(PlayerAction.passing(actor=MINE))
    assert step.accepted is True
    assert MINE in declining.window_passed
    assert "발동하지 않기로" in step.reason

    #: ② 발동으로 우선권이 열린 자리의 ``PASS`` 는 **체인 응답**이다.
    responding = _their_board(repository, _BothOptional)
    mine = _activations(responding, MINE)
    assert mine, responding.legal_actions(MINE).withheld
    assert responding.apply(mine[0]).accepted is True
    assert responding.priority.is_open is True
    holder = responding.priority.holder.seat
    answer = responding.apply(PlayerAction.passing(actor=holder))
    assert answer.accepted is True
    #: 🔴 **다른 일이다** — 유발 포기 기록을 건드리지 않고, 이유도 다르다.
    assert "발동하지 않기로" not in (answer.reason or "")
    assert MINE not in responding.window_passed
    assert THEIRS not in responding.window_passed


@requires_official_db
def test_b05_synthetic_a_duty_outranks_an_optional_window(repository):
    """
    🔴 **강제와 임의가 섞이면 강제가 먼저다** (②).

    룰북 §*When multiple cards are activated simultaneously* 가 특수
    체인을 쌓는 순서를 적는다 — 턴 플레이어의 강제 · 상대의 강제 · 턴
    플레이어의 임의 · 상대의 임의. 이 엔진은 그 네 단계를 **전부** 구현하지
    않는다. 구현한 것은 **강제가 임의보다 먼저**라는 한 단계이고, 그것을
    여기서 센다.

    🔴 **구현하지 않은 것을 적어 둔다** — 강제끼리 · 임의끼리의 자리 순서를
    이 엔진은 ``turn_player`` 먼저로만 처리하고, 그것이 네 단계 전부라고
    주장하지 않는다 (``_duty_seat`` · ``_window_actor`` 의 순회 순서).
    """

    class _MineDutyTheirOptional:
        def __init__(self, repo):
            self._inner = TriggerSource(repo)

        def offers(self, duel, seat: int):
            return tuple(
                dataclasses.replace(
                    offer,
                    requirement=(
                        TriggerRequirement.MANDATORY
                        if seat == MINE
                        else TriggerRequirement.OPTIONAL
                    ),
                    controller=seat,
                )
                for offer in self._inner.offers(duel, MINE)
            )

    duel = _their_board(repository, _MineDutyTheirOptional)
    #: 🔴 강제를 든 자리가 먼저다 — 임의 창이 열려 있어도.
    assert duel._duty_seat() == MINE
    assert duel._window_claims(THEIRS)
    assert duel.to_act == MINE

    #: 🔴 상대는 막히고, 이유는 순서다.
    theirs = duel.legal_actions(THEIRS)
    assert theirs.allowed == ()
    #: 🔴 **이유가 강제 쪽으로 적힌다.** ``_enforce_mandatory`` 가 의무를
    #: **먼저** 보기 때문이다 — 두 사실("강제가 먼저다" · "턴 플레이어의
    #: 기회가 열려 있다") 이 같은 자리를 가리키지만, 막는 근거가 더 강한
    #: 쪽을 적는다 (룰북 §*When multiple cards are activated
    #: simultaneously*). 이 순서를 뒤집으면 강제 의무가 임의 창의 이유로
    #: 가려진다 (``test_c06`` 이 그 문장을 센다).
    ordering = [w for w in theirs.withheld if "처리가 먼저" in w.reason]
    assert ordering, [w.reason for w in theirs.withheld]
    assert all(w.missing is None for w in ordering)


# ======================================================================
# C. 체인 등재 — 실제 경로로 링크 2개가 쌓이고 역순으로 풀린다
# ======================================================================


@requires_official_db
def test_c01_synthetic_two_triggers_of_one_opportunity_share_one_chain(
    repository,
):
    """
    🔴 **같은 기회의 유발 둘이 한 체인에 쌓이고 역순으로 풀린다** (③).

    🔴 **합성 검증이다** (이 파일 머리말). 둘째 효과는 룰북의 드로우 하나를
    같은 카드 개체의 둘째 칸에 붙인 것이고, 실제 카드 지원이 아니다.
    주입하지 않은 것을 적어 둔다 — 허가 · 체인 링크 · 최종 상태 모두
    엔진이 만든다. 이 시험이 지나는 자리:

    1. 실제 사건 (일반 소환) → 제안 2개
    2. ``legal_actions`` 에 후보 2개
    3. ``Duel.apply`` 로 첫째 · 둘째 발동
    4. 같은 체인에 **서로 다른 링크 2개**
    5. 같은 사건의 **중복 발동 차단**
    6. 상대 응답 절차 (우선권이 열린다)
    7. **역순 해결** — 나중에 쌓인 링크가 먼저 풀린다
    8. ``GameState`` 와 ``EventJournal`` 의 결과 일치
    9. 해결 뒤 **정상 진행으로 복귀**
    """
    duel, chooser = _paired_board(repository)
    start = _snapshot(duel)

    #: 1 · 2
    assert len(duel._trigger_offers(MINE)) == 2
    first_set = {a.effect_ref for a in _activations(duel)}
    assert first_set == {SYNTH_REF, REAL_REF}

    #: 3 — 합성(드로우)을 먼저 올린다. 그러면 **실제 기르수 ①이 먼저
    #: 풀린다** (역순이므로) 고, 묘지에 들어간 카드가 둘째 해결을 막지
    #: 않는다 (``SYNTH_DEFINITION`` 의 설명).
    synthetic = next(a for a in _activations(duel) if a.effect_ref == SYNTH_REF)
    assert duel.apply(synthetic).accepted is True
    assert len(duel.chain) == 1

    real = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    assert duel.apply(real).accepted is True

    #: 4
    links = [(link.sequence, link.effect_ref) for link in duel.chain]
    assert links == [(0, SYNTH_REF), (1, REAL_REF)]
    assert len({ref for _seq, ref in links}) == 2

    #: 5 — 같은 사건을 두 번 쓰지 않는다.
    assert _activations(duel) == []
    assert len(duel.consumed_events) == 2
    repeat = duel.apply(real)
    assert repeat.accepted is False
    assert len(duel.chain) == 2

    #: 6
    assert duel.priority.is_open is True
    settled = _settle(duel)
    assert settled and all(step.accepted for step in settled)

    #: 7 — 기록이 역순을 말한다.
    applied = [
        event.effect_ref for event in duel.journal if isinstance(event, EffectEvent)
    ]
    assert applied == [REAL_REF, SYNTH_REF]

    #: 8 — 묘지 +1 (기르수 ①) · 패 +1 · 덱 -2.
    grave, deck, hand = _snapshot(duel)
    assert (grave, deck, hand) == (start[0] + 1, start[1] - 2, start[2] + 1)
    #: 🔴 해결 시점 선택은 **대상이 있는 효과 하나에만** 물었다.
    assert [record.effect_ref for record in chooser.records] == [REAL_REF]

    #: 9
    assert duel.chain.is_empty
    assert duel.legal_actions(duel.to_act).allowed


@requires_official_db
def test_c02_synthetic_an_event_born_during_the_chain_waits_for_a_new_window(
    repository,
):
    """
    🔴 **체인 도중에 생긴 사건은 그 체인이 끝난 뒤의 기회에서 처리한다** (③).

    근거는 공식 재정이다 (OCG 카드 데이터베이스 cid=5883 「聖鳥クレイン」
    2021-07-01 보충) — 체인 처리 중에 조건을 만족한 효과는 **그 체인이
    전부 해결된 뒤에** 발동한다.

    재는 방식: 체인을 쌓은 뒤 ``chain_floor`` 를 경계로 **사건 번호가
    경계 뒤인** 제안이 허가되지 않고, 체인이 풀려 창이 옮겨 간 뒤에는
    같은 제안이 허가되는가. 🔴 체인 중의 사건을 만드는 일은 합성이다 —
    사건 번호 하나만 실제 기록의 뒤쪽 번호로 바꾼다.
    """
    duel, _ = _paired_board(repository)
    #: 🔴 제안은 **소비되기 전에** 꺼내 둔다 — 소비된 사건은 더 이상
    #: 제안으로 나오지 않는다 (``consumed_events``).
    base = _offer_for(duel, REAL_REF)
    synthetic = next(a for a in _activations(duel) if a.effect_ref == SYNTH_REF)
    assert duel.apply(synthetic).accepted is True
    real = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    assert duel.apply(real).accepted is True
    floor = duel.chain_floor
    assert floor >= 0

    later = dataclasses.replace(base, event_sequence=floor + 3)
    #: 🔴 체인이 열려 있는 동안에는 허가되지 않는다.
    assert duel._window_admits(later, MINE) is False

    for step in _settle(duel):
        assert step.accepted is True
    assert duel.chain.is_empty

    #: 🔴 체인이 풀린 뒤에는 그 사건이 새 창에 들어온다.
    assert duel.window_floor == floor
    assert duel._window_admits(later, MINE) is True


@requires_official_db
def test_c03_synthetic_asking_again_or_illegally_changes_nothing(repository):
    """
    🔴 **반복 질의와 불법 제출이 상태를 바꾸지 않는다** (③).

    후보를 세 번 묻고, 자리가 아닌 쪽의 발동을 넣어 본다. 어느 것도
    기회 · 체인 · 판을 움직이지 않아야 한다.
    """
    duel, _ = _paired_board(repository)
    before = (
        duel.state.state_hash(),
        len(duel.chain),
        duel.window_floor,
        duel.chain_floor,
        frozenset(duel.consumed_events),
        duel.window_passed,
    )
    seen = [tuple(sorted(str(a.effect_ref) for a in _activations(duel)))
            for _ in range(3)]
    assert len(set(seen)) == 1

    offer = _offer_for(duel, REAL_REF)
    illegal = PlayerAction.activate_effect(
        actor=THEIRS, source=offer.source, effect_ref=REAL_REF
    )
    assert duel.apply(illegal).accepted is False
    assert (
        duel.state.state_hash(),
        len(duel.chain),
        duel.window_floor,
        duel.chain_floor,
        frozenset(duel.consumed_events),
        duel.window_passed,
    ) == before


@requires_official_db
def test_c04_synthetic_a_consumed_offer_is_refused_on_direct_apply(
    repository,
):
    """
    🔴 **소비된 기회의 직접 ``apply`` 가 거절된다** (③).

    체인이 풀린 뒤에도, 같은 사건 · 같은 효과를 **후보 목록을 지나지
    않고** 넣으면 거절되어야 한다. 막는 것이 "후보 목록에 없다" 하나이면
    그것은 호출 순서에 의존하는 안전이다.
    """
    duel, _ = _paired_board(repository)
    synthetic = next(a for a in _activations(duel) if a.effect_ref == SYNTH_REF)
    duel.apply(synthetic)
    real = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    duel.apply(real)
    for _step in _settle(duel):
        pass

    after = duel.state.state_hash()
    for action in (synthetic, real):
        step = duel.apply(action)
        assert step.accepted is False, action
        assert duel.state.state_hash() == after
    assert duel.chain.is_empty


# ======================================================================
# D. 미지원 전파 — 실행에 영향을 준 미지원이 밖까지 간다
# ======================================================================


def test_d01_only_a_named_missing_rule_counts_as_unsupported():
    """
    🔴 **``missing`` 이 붙은 보류만 미지원이다** (④).

    "규칙이 막았다" 와 "이 저장소에 그 규칙이 없다" 는 다른 사실이다.
    섞으면 읽는 쪽이 규칙의 답을 결함으로 읽거나 그 반대가 된다.
    """
    #: 🔴 **보완8 이 ``code`` 를 더했다** — 전에는 셋째 인자가 ``missing``
    #: 이었고, ``missing`` 이 비었는지로 읽는 쪽이 종류를 짐작했다. 지금은
    #: 코드가 그것을 말하고, 코드와 ``missing`` 의 일치는 자료형이 강제한다
    #: (확정 거부에 "없는 것" 을 붙이면 생성이 거부된다).
    legal = LegalActions(
        seat=MINE,
        allowed=(),
        withheld=(
            WithheldAction(
                PlayerActionKind.END_PHASE,
                "순서가 아닙니다",
                ValidationCode.STAGE_FORBIDS_ACTION,
            ),
            WithheldAction(
                PlayerActionKind.ACTIVATE_EFFECT,
                "규칙이 없습니다",
                ValidationCode.RULE_NOT_IMPLEMENTED,
                missing="rule-x",
            ),
        ),
    )
    assert [held.missing for held in legal.unsupported()] == ["rule-x"]
    assert LegalActions(MINE).unsupported() == ()

    #: 🔴 그리고 그 구분이 **코드에서도** 읽힌다 — 문장을 보지 않는다.
    assert [held.is_rule_refusal for held in legal.withheld] == [True, False]
    assert [held.validity for held in legal.unsupported()] == [
        ActionValidity.UNKNOWN
    ]


def test_d02_a_simulation_result_refuses_an_edge_without_a_future():
    """
    🔴 **없는 미래의 경계를 적지 않는다** (④).

    ``unsupported`` 는 *그 미래의 다음 자리* 에 대한 사실이다. 미래가
    없는 결과에 그것이 채워져 있다면 다른 자리의 보류를 옮겨 적은 것이다.
    """
    action = PlayerAction.end_phase(actor=MINE)
    with pytest.raises(SimulationError):
        SimulationResult(
            action=action,
            status=SimulationStatus.REFUSED,
            viewer=MINE,
            unsupported=("x",),
        )
    #: 🔴 미래가 있는 결과에서는 두 값이 함께 산다.
    ok = SimulationResult(
        action=action, status=SimulationStatus.NOT_A_CANDIDATE, viewer=MINE
    )
    assert ok.unsupported == ()
    assert ok.fully_supported is False


@requires_official_db
def test_d03_the_simulator_carries_the_unsupported_edge_outward(repository):
    """
    🔴 **미지원 사유가 Simulator 밖으로 나온다** (④).

    사본은 버려지므로 그 자리에서 읽지 않으면 사실이 영영 나가지 않는다.
    그리고 :attr:`SimulationResult.fully_supported` 가 "엔진이 이 행동을
    적용했다" 와 "그 뒤를 다 안다" 를 가른다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = setup.duel
    simulator = Simulator(duel=duel)
    legal = duel.legal_actions(duel.to_act)
    results = [
        simulator.simulate(action, viewer=MINE) for action in legal.allowed
    ]
    supported = [r for r in results if r.status is SimulationStatus.SUPPORTED]
    assert supported

    #: 🔴 미지원 경계가 있으면 그 미래는 끝까지 검증된 것이 아니다.
    for result in supported:
        assert result.fully_supported is (not result.unsupported)
        for line in result.unsupported:
            assert "[" in line and "]" in line

    #: 🔴 실측으로 이 판에는 경계가 있다 — ``activate_card`` 의 남은
    #: 적법성을 판정할 규칙 계층이 아직 없다. 그 사실이 전개 결과를
    #: "정상 종료" 로 읽히게 하던 자리다 (④).
    assert any(result.unsupported for result in supported)


@requires_official_db
def test_d04_the_run_separates_flow_only_from_unsupported(repository):
    """
    🔴 **"후보가 흐름뿐" 과 "미지원이 있다" 를 가른다** (④).

    6-AB 추가 보완까지 이 자리는 보류를 보지 않고 한 문장을 적었다.
    실측: 사용자가 본 그 전개는 ``['end_phase']`` 만 남은 자리에서
    멈췄고, **같은 자리에 미지원 보류가 1건 있었다.** 즉 그 문장이 말한
    "정상 전개 종료" 는 측정되지 않은 주장이었다.
    """
    from deck.opening import build_opening, execute_opening, unsupported_reasons
    from deck.recipe import parse_recipe
    from deck.report import render_opening_run
    from app.main import opening_wiring
    from tests.engine.test_trigger_normal_path_integration import (
        GROWTH,
        _orcust_pool,
    )

    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    pool = others[:4] + [GROWTH] + others[4:]
    lines = [f"{GIRSU} x1"] + [f"{cid} x1" for cid in pool[:39]]
    hand = ([GIRSU] + [cid for cid in pool if cid != GIRSU])[:5]
    chooser, triggers = opening_wiring(repository)
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        hand,
        chooser=chooser,
        triggers=triggers,
    )
    run = execute_opening(setup, repository)

    #: 🔴 한 낱말로 가른다.
    assert run.stopped_kind == "unsupported"
    assert run.unsupported
    assert "지원하지 않아 후보가 되지" in (run.stopped_reason or "")
    #: 🔴 걸음마다도 남는다 — 어디서 만났는지가 보인다.
    assert any(step.unsupported for step in run.steps)

    #: 🔴 보고까지 간다.
    text = render_opening_run(run)
    assert "미지원 사유" in text
    for item in run.unsupported:
        assert item in text

    #: 🔴 판정을 새로 하지 않는다 — 엔진의 보류를 옮기기만 한다.
    legal = setup.duel.legal_actions(setup.duel.to_act)
    assert len(unsupported_reasons(legal)) == len(legal.unsupported())


@requires_official_db
def test_d05_the_combo_answer_says_the_run_was_not_fully_supported(
    repository,
):
    """
    🔴 **미지원 사유가 ``/combo`` 응답까지 간다** (④).

    🔴 **토큰 없는 응답 생성 검사다** — ``combo_messages`` 가 돌려주는
    문자열을 센다. Discord 에 접속하지 않고, 접속했다고 적지도 않는다.
    """
    import app.discord_bot as bot
    from tests.test_combo_output_consistency import HAND_OK, RECIPE, _Agent

    blob = "\n".join(
        bot.combo_messages(_Agent(repository), HAND_OK, recipe_text=RECIPE)
    )
    assert "지원하지 않아 후보가 되지 못한 것이" in blob
    assert "미지원 사유" in blob
    #: 🔴 그래서 걸음 수를 "전개를 다 했다" 로 읽을 수 없다고 적는다.
    assert "전개를 다 했다" in blob
    #: 🔴 **정정 (Phase 6-AC).** 이 패의 멈춘 자리는 더 이상 미지원이
    #: 아니다 (``stopped_kind == "flow_only"``) — 전개가 한 걸음 더 나아가
    #: 세트를 모두 끝내고 멈추므로 그 자리에 발동 후보가 남지 않는다.
    #: 그래서 "정상 전개 종료가 아닙니다" 대신 **도중에 지나온 미지원**을
    #: 적는 줄을 센다. 재는 요구(④ — 미지원이 응답까지 간다)는 그대로다.
    assert "전개 도중에 지나온 미지원이 있습니다" in blob
    assert "정상 전개 종료가 아닙니다" not in blob


# ======================================================================
# E. 사본 — 새 상태가 새지 않는다
# ======================================================================


@requires_official_db
def test_e01_a_fork_inherits_the_window_state(repository):
    """
    🔴 **사본이 기회의 수명 상태를 그대로 물려받는다** (⑤).

    ``window_floor`` · ``chain_floor`` · ``window_passed`` 가 사본에서
    달라지면 사본의 후보가 원본과 달라지고, 그러면 미래의 값이 규칙이
    아니라 배선 때문에 달라진다.
    """
    duel = _their_board(repository, _BothOptional)
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    simulator = Simulator(duel=duel)
    fork = simulator._fork()

    assert fork.window_passed == duel.window_passed
    assert fork.window_floor == duel.window_floor
    assert fork.chain_floor == duel.chain_floor
    assert fork.timing_floor == duel.timing_floor
    assert fork._window_actor() == duel._window_actor()
    assert {str(a) for a in fork.legal_actions(THEIRS).allowed} == {
        str(a) for a in duel.legal_actions(THEIRS).allowed
    }


@requires_official_db
def test_e02_a_decline_in_one_fork_does_not_close_another(repository):
    """
    🔴 **한 가지에서 포기한 것이 다른 가지와 원본을 닫지 않는다** (⑤).

    ``window_passed`` 는 ``frozenset`` 을 **갈아 끼워** 기록하므로 사본이
    원본의 집합을 밀어 넣을 수 없다. 그 성질을 값으로 센다.
    """
    duel = _their_board(repository, _BothOptional)
    simulator = Simulator(duel=duel)
    left, right = simulator._fork(), simulator._fork()

    assert left.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert left.window_passed == frozenset({MINE})
    #: 🔴 다른 가지와 원본은 그대로다.
    assert right.window_passed == frozenset()
    assert duel.window_passed == frozenset()
    assert duel._window_actor() == MINE
    assert right._window_actor() == MINE


@requires_official_db
def test_e03_a_fork_keeps_the_window_state_across_an_open_chain(repository):
    """
    🔴 **체인이 열린 자리에서도 사본이 같은 상태를 본다** (⑤).

    실제 카드 경로로 센다 — 발동해서 체인을 열고, 그 자리에서 사본을
    만든다. 세 값과 우선권 상태가 그대로여야 사본이 **같은 응답 절차**를
    본다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = setup.duel
    action = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    assert duel.apply(action).accepted is True
    assert duel.priority.is_open is True

    fork = Simulator(duel=duel)._fork()
    assert fork.chain_floor == duel.chain_floor
    assert fork.window_floor == duel.window_floor
    assert fork.window_passed == duel.window_passed
    assert len(fork.chain) == len(duel.chain)
    assert fork.priority.is_open is True
    assert {str(a) for a in fork.legal_actions(fork.to_act).allowed} == {
        str(a) for a in duel.legal_actions(duel.to_act).allowed
    }

    #: 🔴 사본에서 체인을 풀어도 원본은 그대로다.
    for step in _settle(fork):
        assert step.accepted is True
    assert fork.chain.is_empty
    assert len(duel.chain) == 1
    assert duel.priority.is_open is True


@requires_official_db
def test_e04_synthetic_a_fork_keeps_the_parents_effect_definitions(repository):
    """
    🔴 **사본이 원본의 효과 정의와 실행 계약을 그대로 쓴다** (보완4 ③).

    최종 보완까지 이 시험의 이름은
    ``test_e04_synthetic_a_fork_rebuilds_the_production_registry`` 였고,
    사본이 프로덕션 등록부로 **다시 만들어** 원본에 꽂힌 정의를 잃는 것을
    *"올바른 설계"* 로 적었다 — 사라지는 **방식**(미지원 보류로 적힌다)만
    쟀다.

    🔴 **그 단정이 틀렸다.** 사본이 원본보다 **못 해결하면** 미래의 값이
    규칙이 아니라 **배선** 때문에 달라진다. 그것은 ``_forked_journal`` ·
    ``_forked_chooser`` 가 이미 고친 것과 같은 결의 결함이고 (6-AB ·
    최종 보완), 같은 이유로 고쳐야 했다. 실측::

        원본 후보 ['69811710:e[0]', '69811710:e[1]']
        🔴 사본 후보 ['69811710:e[0]']
        🔴 사본의 정의 등재 = False

    지금은 ``Simulator._forked_definitions`` 가 원본의 정의 · 구현 목록을
    ``duel_components`` 에 넘기고, 그쪽이 **같은 내용의 새 등록부**를
    만든다 — 담긴 ``EffectDefinition`` 은 frozen 이므로 공유해도 안전하고,
    격리해야 하는 것은 ``register()`` 로 바뀌는 **목록**이다.
    """
    duel, _ = _paired_board(repository)
    fork = Simulator(duel=duel)._fork()

    #: 🔴 같은 후보 · 같은 정의.
    assert {a.effect_ref for a in _activations(fork)} == {SYNTH_REF, REAL_REF}
    for ref in (SYNTH_REF, REAL_REF):
        assert fork._activator.definitions.definition_for(ref) is not None
        assert fork._activator.lookup.has_implementation(ref)

    #: 🔴 **그래서 미지원 보류가 없다** — 정의가 없어서 오르지 못한 후보가
    #: 하나도 없다 (이 시험이 전에 세던 것이 바로 그 보류다).
    assert not [
        held
        for held in fork.legal_actions(MINE).withheld
        if held.missing == TRIGGER_IMPLEMENTATION_MISSING
    ]

    #: 🔴 **등록부는 같은 객체가 아니다** — 한 분기의 등록이 다른 분기와
    #: 부모에 보이면 안 된다.
    assert fork._activator.definitions is not duel._activator.definitions
    assert fork._activator.lookup is not duel._activator.lookup
    assert fork._resolver is not duel._resolver


@requires_official_db
def test_e05_synthetic_a_fork_resolves_the_two_link_chain_like_the_original(
    repository,
):
    """
    🔴 **사본이 양쪽 시나리오를 원본과 **같이** 해결한다** (보완4 ③).

    ``test_e04`` 가 "같은 후보" 를 쟀고, 이 시험이 **같은 결과**를 센다 —
    후보만 같고 해결이 다르면 미래의 값이 여전히 배선을 잰다.

    🔴 **원본은 움직이지 않는다** — 사본의 전개가 부모의 기록에 남지 않고
    (``_forked_journal``) 판도 그대로다.
    """
    duel, _ = _paired_board(repository)
    before = _snapshot(duel)
    fork = Simulator(duel=duel)._fork()

    synthetic = next(a for a in _activations(fork) if a.effect_ref == SYNTH_REF)
    assert fork.apply(synthetic).accepted is True
    real = next(a for a in _activations(fork) if a.effect_ref == REAL_REF)
    assert fork.apply(real).accepted is True
    assert [(link.sequence, link.effect_ref) for link in fork.chain] == [
        (0, SYNTH_REF),
        (1, REAL_REF),
    ]
    for step in _settle(fork):
        assert step.accepted is True

    #: 🔴 **역순 해결과 결과가 원본 경로와 같다** (``test_c01`` 의 값).
    applied = [
        event.effect_ref
        for event in fork.journal
        if isinstance(event, EffectEvent)
    ]
    assert applied == [REAL_REF, SYNTH_REF]
    grave, deck, hand = _snapshot(fork)
    assert (grave, deck, hand) == (
        before[0] + 1,
        before[1] - 2,
        before[2] + 1,
    )

    #: 🔴 부모는 그대로다.
    assert duel.chain.is_empty
    assert _snapshot(duel) == before
    assert not [
        event for event in duel.journal if isinstance(event, EffectEvent)
    ]


# ======================================================================
# F. 보존 — 실제 카드 경로와 /combo 가 그대로다
# ======================================================================


@requires_official_db
def test_f01_the_real_card_path_is_unchanged(repository):
    """
    🔴 **실제 카드 하나의 경로가 그대로다** (보존).

    합성 둘째 효과를 꽂지 않은 판에서는 제안이 하나이고, 그 하나가 예전
    그대로 풀린다 — 묘지 +1 · 덱 -1.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = setup.duel
    start = _snapshot(duel)
    assert len(duel._trigger_offers(MINE)) == 1

    action = next(a for a in _activations(duel) if a.effect_ref == REAL_REF)
    assert duel.apply(action).accepted is True
    assert len(duel.chain) == 1
    for step in _settle(duel):
        assert step.accepted is True

    grave, deck, _hand = _snapshot(duel)
    assert (grave, deck) == (start[0] + 1, start[1] - 1)
    assert [record.effect_ref for record in chooser.records] == [REAL_REF]
    assert _activations(duel) == []


@requires_official_db
def test_f02_the_combo_answer_keeps_both_inputs(repository):
    """
    🔴 **``/combo`` 의 두 입력이 그대로 갈린다** (보존).

    정상 입력은 실행되고, 덱 보유 매수를 넘는 패는 거절된다. 이 Phase 가
    더한 줄이 그 구분을 덮지 않아야 한다.

    🔴 **토큰 없는 응답 생성 검사다.**
    """
    import app.discord_bot as bot
    from tests.test_combo_output_consistency import (
        HAND_OK,
        HAND_OVER,
        RECIPE,
        _Agent,
    )

    good = "\n".join(
        bot.combo_messages(_Agent(repository), HAND_OK, recipe_text=RECIPE)
    )
    bad = "\n".join(
        bot.combo_messages(_Agent(repository), HAND_OVER, recipe_text=RECIPE)
    )
    #: Phase 6-AC 에서 5 → 6걸음 · 효과 해결 1 → 2
    #: (``test_combo_output_consistency`` 의 ``test_07`` 이 그 변화를 적는다).
    assert "엔진이 실제로 6걸음 실행" in good
    assert "효과 해결 2걸음" in good
    assert "실행하지 않았습니다" in bad
    assert "엔진이 실제로" not in bad
