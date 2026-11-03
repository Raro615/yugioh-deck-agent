"""
Phase 6-AG (B) — **기르수 ③ 을 실제 체인으로 통과시킨다.**

6-AF 의 ``test_f01`` · ``test_f02`` 는 **단위 검증**이다. 둘은
``state.create_instance`` · ``state.move`` 로 해결 직전 판을 만들고
``executor.execute`` 를 직접 부른다 — 그래서 "해결 함수가 무엇을 다시
보는가" 는 재지만 **발동 수락 → 체인 등록 → 역순 해결 → 우선권 복귀**는
재지 못한다. 그 둘을 지우지 않는다 (해결 함수의 계약을 재는 자리로 쓸모가
있다). 이 파일이 **그 위에** 통합 검증을 더한다.

한 실행 안에서 아래 순서를 만든다.

1. 기르수 ③ 을 발동한다 — **체인 링크 1** (실제 카드 · 실제 관문).
2. 함정 한 장이 **체인 링크 2** 로 쌓인다 (실제 발동 경로 · 스펠 스피드 2).
3. 링크 2 가 **먼저** 해결되어 판을 바꾼다.
4. 기르수 ③ 이 **바뀐 판에서** 해결된다.

왜 링크 2 가 **함정**인가 — 다른 길이 막혀 있다
-------------------------------------------------
기동 효과(기르수 ③)는 **판이 열린 상태**에서만 발동된다. 그 위에 무엇을
쌓으려면 스펠 스피드 2 가 필요하고, 이 저장소가 실제로 그것을 허가하는
자리는 **함정**이다 (Phase 6-Q — ``classify_spell_speed`` 가 카드 종류에서
속도를 읽는다).

🔴 **유발즉시(``ActivationKind.QUICK``)로는 만들 수 없다.** 분류를
``QUICK`` 으로 적어도 공용 관문이 ``UNKNOWN`` 을 돌려준다 — 룰북이
유발즉시의 발동 시점을 적지 않았기 때문이다 (``not_stated``,
``ACTIVATION_KINDS_IN_SCOPE`` · ADR-006). 실측은
``tests/engine/test_known_effect_kind_legality.py::test_b05`` 에 있다.
**미지원을 허가로 바꾸지 않는다.**

🔴 **스펠 스피드 1 유발로도 만들 수 없다.** 지나간 사건에 걸린 스펠 스피드
1 은 체인 응답 단계에서 ``stage_forbids_action`` 으로 막힌다 (실측). 같은
사건에서 **동시에** 유발되는 둘은 함께 체인을 만들 수 있지만
(``tests/test_chain_state_change_between_links.py`` 가 그 길을 쓴다),
기르수 ③ 은 사건이 아니라 **기동**이므로 그 길에 들어가지 않는다.

무엇이 실제이고 무엇이 합성인가
--------------------------------
=========================================  =======================
기르수 ③ · 성유물 토큰 · 함정 카드            🔴 **실제 카드**
발동 관문 · 스펠 스피드 · 체인 · 역순 해결      🔴 **실제 공용 경로**
우선권 · 응답 창 · 해결 시점 선택              🔴 **실제 공용 경로**
함정이 **하는 일**(특수 소환 한 장)            **합성** (아래)
=========================================  =======================

🔴 **합성인 것을 정확히 적는다.** 등재된 함정 다섯 장 중 어느 것도 몬스터를
특수 소환하지 않는다. 그래서 「욕망의 선물」 의 **그 주소에** 조작만 바꾼
정의를 넣은 **격리 등록부**를 만들어 그 판에만 꽂는다 — production
:data:`~engine.effect.library.EFFECT_LIBRARY` 는 한 줄도 바뀌지 않고
``test_n02`` 가 그것을 센다. 카드 종류(함정)는 **그대로**이므로 스펠
스피드와 발동 경로는 실제 규칙이 답한다.

🔴 **첫 행동 뒤에는 판을 손으로 바꾸지 않는다.** 시작 상태만 구성한다
(기르수는 필드에, 함정은 **뒷면으로 세워 둔 채**, 턴 번호는 5 — 그래서
「세트한 턴」 제약이 걸리지 않는다). 그 뒤의 모든 변화는 ``Duel.apply`` 가
만들고, 판정 함수를 monkeypatch 하지 않으며 해결 결과를 주입하지 않는다.

왜 한쪽은 **상대** 필드를 채우는가
------------------------------------
기르수 ③ 의 두 조건이 다르다 (``test_n01`` 이 고정한다).

* 발동 조건: ``아님(자신 MZONE 에 이 카드 말고 1장 이상)`` **그리고** 양쪽
  MZONE 에 빈 칸 **그리고** 금지 둘
* 해결 시점 조건(``s.tkop``): 양쪽 MZONE 에 빈 칸 **그리고** 금지 둘 —
  「자신 필드에 다른 몬스터가 없다」 가 **없다**

그래서 "해결 시점에 빈 칸이 사라진다" 를 만들려면 **자신 필드는 쓸 수
없다**: 발동이 서려면 자신 필드에 기르수 하나뿐이어야 하고, 그러면 남은
칸이 넷이라 링크 2 한 번으로 채울 수 없다. 상대 필드는 미리 넷을 놓아도
발동 조건이 서므로 (빈 칸 하나) **한 번의 특수 소환으로 마지막 칸이
찬다.** 그 함정은 상대가 들고 있어야 한다 — 특수 소환은 **해결하는 쪽의**
필드에 놓이기 때문이다 (``_plan_summon_operation`` 이
``context.controller`` 를 넘긴다).
"""

from __future__ import annotations

import pytest

from agent.choice import FirstPermittedChoice, PreferredCardChoice
from engine.action import PlayerAction, PlayerActionKind
from engine.condition import IsMonster, PlayerRef
from engine.cost import CandidateSource, ChoiceSpec
from engine.duel import Duel, TurnStep, duel_components
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.journal import EffectEvent, EventJournal
from engine.effect.library import EFFECT_LIBRARY, definition_registry, entry_for
from engine.effect.operation import SpecialSummonOperation
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.use_limit import LimitScope, effect_key
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone
from integration.autonomy import PolicyChooser
from tests.conftest import requires_official_db

pytestmark = requires_official_db

GIRSU = 69811710
TOKEN = 46647145
#: 「성유물－『성장』」 — 패에서 특수 소환할 수 있는 몬스터
#: (``tests/test_chain_state_change_between_links.py::test_m05`` 가 쓰는
#: 그 카드). 여기서는 **링크 2 가 소환하는 한 장**으로만 쓴다.
WAND = 93920420
#: 「욕망의 선물」 — 등재된 **일반 함정**. 여기서는 그 **주소**를 빌린다
#: (조작을 합성으로 바꾼다 — 파일 머리말).
TRAP = 5915629
P0, P1 = 0, 1

#: 기르수 ③ — 토큰 둘을 만드는 기동 효과. ordinal 은 추측이 아니다
#: (``tests/test_girsu_token_line.py::test_a01`` 이 파싱 결과와 대조한다).
TOKEN_EFFECT = EffectRef(GIRSU, 2)
TRAP_REF = EffectRef(TRAP, 0)

_SYNTHETIC = (
    "🔴 **합성 — 「욕망의 선물」 의 실제 효과가 아니다.** 이 정의는 "
    "tests/test_girsu_token_chain_integration.py 가 '기르수 ③ 의 발동과 "
    "해결 사이에 판이 변한다' 를 재기 위해 그 주소에 넣은 것이고, 지원되는 "
    "조작만 쓴다. 프로덕션 EFFECT_LIBRARY 에 들어가지 않는다."
)

#: 해결하는 쪽 패의 몬스터 한 장을 **그쪽 필드에** 특수 소환한다.
SYNTHETIC_TRAP = EffectDefinition(
    effect_ref=TRAP_REF,
    source_card_id=TRAP,
    targets=TargetBinding.single(
        TargetSpec.choosing(
            ChoiceSpec(
                source=CandidateSource(
                    zones=frozenset({Zone.HAND}),
                    owner=PlayerRef.CONTROLLER,
                    require=IsMonster(),
                ),
                minimum=1,
                maximum=1,
            ),
            chosen_at_resolution=True,
        )
    ),
    operations=(SpecialSummonOperation(PRIMARY_TARGET),),
    activation=None,
    #: 등재된 함정 다섯 장과 **같은 값**이다 — 사건을 기다리지 않는다.
    activation_waits_for_event=False,
    provenance=EffectProvenance.hand_written(verified=True, note=_SYNTHETIC),
)


# ======================================================================
# 공용 — **시작 상태**만 만든다
# ======================================================================
def _isolated_registry() -> EffectDefinitionRegistry:
    """
    그 한 주소만 **갈아 끼운** 등록부.

    🔴 production 목록에서 :data:`TRAP_REF` 의 정의를 빼고 합성 정의를
    넣는다 — 둘을 함께 넣으면 ``EffectDefinitionRegistry`` 가 거절하고
    (같은 주소 두 줄), 어느 쪽이 이기는지 말할 수 없게 된다.
    """
    kept = tuple(
        definition
        for definition in definition_registry().definitions()
        if definition.effect_ref != TRAP_REF
    )
    return EffectDefinitionRegistry(kept + (SYNTHETIC_TRAP,))


def _board(
    repository,
    *,
    mine=(GIRSU,),
    hand=(),
    their_mzone=(),
    their_hand=(),
    trap_seat=P0,
):
    """
    한 실행의 시작 상태. 돌리는 중에는 ``Duel.apply`` 만 판을 바꾼다.

    🔴 **함정은 뒷면으로 세워 둔 채 시작한다.** 실제 ``SET_SPELL_TRAP``
    행위로 세우면 그 턴의 세트 기록이 남아 「세트한 턴에는 발동할 수 없다」
    가 걸리고, 그것을 풀려고 턴을 손으로 넘기면 **첫 행동 뒤에 판을 손으로
    바꾸는** 것이 된다. 그래서 "지난 턴에 세워 두었다" 를 시작 상태로
    적는다 (턴 5).

    🔴 필드에 놓는 카드는 **등재된 것만** 쓴다 — 모르는 앞면 카드가 하나
    있으면 ``BoardRuling._interference`` 가 판 전체의 답을 ``UNKNOWN`` 으로
    만들고, 그러면 이 파일이 재려는 축이 그 모름에 묻힌다.
    """
    state = GameState.create(
        repository,
        decks=([GIRSU] * 20, [GIRSU] * 20),
        turn_player=P0,
        seed=0,
        shuffle=False,
    )
    field = []
    for index, card_id in enumerate(mine):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    hand_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    their_field = []
    for index, card_id in enumerate(their_mzone):
        instance = state.create_instance(card_id, owner=P1, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P1,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        their_field.append(instance.instance_id)
    their_hand_ids = [
        state.create_instance(card_id, owner=P1, zone=Zone.HAND).instance_id
        for card_id in their_hand
    ]
    trap = state.create_instance(TRAP, owner=trap_seat, zone=Zone.SZONE)
    state.move(
        trap,
        Zone.SZONE,
        to_player=trap_seat,
        index=0,
        position=Position.FACEDOWN_DEFENSE,
    )
    state.turn.turn_number = 5
    state.turn.set_phase(Phase.MAIN1)

    definitions = _isolated_registry()
    implementations = EffectImplementationRegistry()
    for entry in EFFECT_LIBRARY:
        if entry.executable:
            implementations.register(entry.effect_ref)
    implementations.register(TRAP_REF)

    journal = EventJournal()
    chooser = PolicyChooser(
        PreferredCardChoice((WAND,), FirstPermittedChoice()), definitions
    )
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        step=TurnStep.OPEN,
        first_player=P0,
        **duel_components(
            journal=journal,
            chooser=chooser,
            definitions=definitions,
            implementations=implementations,
        ),
    )
    return duel, chooser, journal, field, hand_ids, their_field, their_hand_ids


def _activations(duel, seat, ref):
    return [
        action
        for action in duel.legal_actions(seat).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == ref
    ]


def _activate(duel, seat, ref):
    """그 효과의 **후보를 찾아** 적용한다. 행동을 만들지 않는다."""
    duel.advance()
    found = _activations(duel, seat, ref)
    assert found, (
        f"P{seat} 의 후보에 {ref} 가 없다",
        [
            (a.kind.value, str(a.effect_ref))
            for a in duel.legal_actions(seat).allowed
        ],
        [
            (w.kind.value, w.code.value, w.reason[:140])
            for w in duel.legal_actions(seat).withheld
        ],
    )
    return duel.apply(found[0])


def _chain_in(duel, ref, *, limit=6):
    """
    **응답 창을 지나가며** 그 효과가 후보로 오를 때 발동한다.

    🔴 창을 억지로 열지 않는다 — 우선권이 도는 순서를 그대로 따르고,
    후보에 오르지 않으면 패스한다. 상대가 먼저 받는 창도 그대로 지난다.
    """
    for _ in range(limit):
        duel.advance()
        if not duel.priority.is_open:
            break
        seat = duel.priority.holder.seat
        found = _activations(duel, seat, ref)
        if found:
            return duel.apply(found[0])
        passing = [
            action
            for action in duel.legal_actions(seat).allowed
            if action.kind is PlayerActionKind.PASS
        ]
        if not passing:
            break
        duel.apply(passing[0])
    raise AssertionError(f"{ref} 가 응답 창에서 후보로 오르지 않았다")


def _settle(duel, limit=12):
    """양측이 지나가며 체인을 푼다. 패스도 ``legal_actions`` 를 지난다."""
    steps = []
    for _ in range(limit):
        duel.advance()
        if not duel.priority.is_open:
            break
        seat = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=seat)
        assert passing in duel.legal_actions(seat).allowed
        steps.append(duel.apply(passing))
    return steps


def _links(duel):
    return [str(link.effect_ref) for link in duel.chain.links]


def _tokens(duel, seat):
    return [c for c in duel.state.zone(seat, Zone.MZONE) if c.card_id == TOKEN]


def _mzone(duel, seat):
    return [(c.card_id, c.instance_id) for c in duel.state.zone(seat, Zone.MZONE)]


def _resolved_refs(journal):
    """해결된 효과들을 **기록된 순서대로** — 역순 해결을 재는 자리."""
    return [
        str(event.effect_ref)
        for event in journal
        if isinstance(event, EffectEvent)
    ]


def _said(steps, ref):
    """``_settle`` 의 걸음 중 **그 링크의 해결을 보고한 것**."""
    return next((s for s in steps if str(ref) in s.reason), None)


# ======================================================================
# N. 이 파일이 서는 전제
# ======================================================================


@pytest.mark.real_card
def test_n01_the_activation_only_clause_is_not_in_the_resolution_condition():
    """
    🔴 **발동 전용 절이 해결 시점 조건에 없다** — 파일 머리말의 전제.

    이것이 거짓이 되면 아래 두 통합 시험이 재려는 것이 사라지므로 전제를
    **먼저** 고정한다.
    """
    definition = entry_for(TOKEN_EFFECT).definition
    activation = str(definition.activation)
    resolution = str(definition.resolution_condition)

    assert "아님(자신 MZONE 에 이 카드 말고 1장 이상)" in activation
    assert "아님(자신 MZONE 에 이 카드 말고 1장 이상)" not in resolution
    #: 양쪽 빈 칸은 **둘 다** 본다 — 그래서 사례 2 가 성립한다.
    for condition in (activation, resolution):
        assert "자신 MZONE 에 빈 칸" in condition
        assert "상대 MZONE 에 빈 칸" in condition


def test_n02_the_synthetic_trap_never_reaches_production():
    """
    🔴 **격리 등록부는 production 을 건드리지 않는다.**

    같은 주소를 두 번 등록할 수 없으므로 (``EffectDefinitionRegistry``)
    합성 정의는 **갈아 끼운** 것이고, 그 갈아 끼움이 이 시험 파일 안에서만
    산다는 것을 production 목록으로 확인한다.
    """
    assert entry_for(TRAP_REF).definition is not SYNTHETIC_TRAP
    assert SYNTHETIC_TRAP not in [entry.definition for entry in EFFECT_LIBRARY]
    #: production 의 「욕망의 선물」 은 여전히 **드로우**다.
    real = entry_for(TRAP_REF).definition
    assert [op.kind.value for op in real.operations] == ["draw"]

    isolated = _isolated_registry()
    assert isolated.definition_for(TRAP_REF) is SYNTHETIC_TRAP
    #: 다른 주소는 그대로다 — 기르수 ③ 은 production 정의로 돈다.
    assert isolated.definition_for(TOKEN_EFFECT) is (
        entry_for(TOKEN_EFFECT).definition
    )


# ======================================================================
# O. 통합 ① — 체인 링크 2 가 자신 필드에 몬스터를 만든다
# ======================================================================


@pytest.mark.real_card
def test_o01_a_monster_appearing_during_the_chain_does_not_fizzle_the_tokens(
    repository,
):
    """
    🔴 **발동 때 자신 필드에 다른 몬스터가 없었고 해결 때는 있다 → 토큰은
    그대로 만들어진다** (B 필수 사례 1).

    발동 전용 절(「자신 필드에 이 카드 말고 몬스터가 없다」)을 해결 시점에
    **다시 보지 않는다.** 나머지 해결 조건(양쪽 빈 칸 · 금지 둘)이 참이므로
    양쪽에 토큰이 하나씩 생긴다.

    🔴 ``test_f01`` 과 다른 것: 저쪽은 ``state.move`` 로 몬스터를 놓고
    ``executor.execute`` 를 직접 불렀고, 이쪽은 **체인 링크 2 가 실제로
    특수 소환해서** 그 판을 만든다.
    """
    duel, chooser, journal, field, hand, _tf, _th = _board(
        repository, mine=(GIRSU,), hand=(WAND,), trap_seat=P0
    )
    #: 발동 직전 — 자신 필드는 기르수 **하나**뿐이고 토큰이 없다.
    assert [card_id for card_id, _ in _mzone(duel, P0)] == [GIRSU]
    assert _tokens(duel, P0) == [] and _tokens(duel, P1) == []

    #: ① 체인 링크 1 — 기르수 ③ 이 **수락**된다.
    first = _activate(duel, P0, TOKEN_EFFECT)
    assert first.accepted is True, first.reason
    assert duel.chain.is_empty is False
    assert _links(duel) == [str(TOKEN_EFFECT)]

    #: ② 체인 링크 2 — 함정이 **그 위에** 쌓인다 (스펠 스피드 2).
    second = _chain_in(duel, TRAP_REF)
    assert second.accepted is True, second.reason
    assert _links(duel) == [str(TOKEN_EFFECT), str(TRAP_REF)]

    steps = _settle(duel)

    #: ③ 🔴 **역순 해결**이다 — 링크 2 가 먼저 기록된다.
    assert _resolved_refs(journal) == [str(TRAP_REF), str(TOKEN_EFFECT)]

    #: ④ 링크 2 가 실제로 자신 필드에 몬스터를 만들었다 (고른 것도 기록된다).
    summoned = next(
        (r for r in chooser.records if r.effect_ref == TRAP_REF), None
    )
    assert summoned is not None and summoned.chosen
    assert summoned.chosen[0] in hand
    assert (WAND, summoned.chosen[0]) in _mzone(duel, P0)

    #: ⑤ 🔴 **양쪽에 토큰이 하나씩** — 한쪽만 생기는 부분 적용이 없다.
    assert len(_tokens(duel, P0)) == 1
    assert len(_tokens(duel, P1)) == 1

    #: ⑥ 자신 필드는 기르수 + 소환된 『성장』 + 토큰 = 세 장이고 개체가
    #:    겹치지 않는다 (덮어쓰기도 초과 배치도 없다).
    mine = _mzone(duel, P0)
    assert sorted(card_id for card_id, _ in mine) == sorted(
        [GIRSU, WAND, TOKEN]
    )
    assert len({instance for _c, instance in mine}) == 3

    #: ⑦ 🔴 **정상 해결**이고 불발 문장이 붙지 않는다.
    said = _said(steps, TOKEN_EFFECT)
    assert said is not None
    assert said.code is ValidationCode.OK, said.reason
    assert "해결하지 못했습니다" not in said.reason
    assert "일을 하지 않았습니다" not in said.reason

    #: ⑧ 효과 사용 제한이 **한 번** 기록되었다.
    assert (
        duel.state.uses.count(LimitScope.PER_EFFECT, effect_key(P0, TOKEN_EFFECT))
        == 1
    )

    #: ⑨ 체인이 비고 우선권이 돌아왔다 (판이 다시 열렸다).
    assert duel.chain.is_empty
    assert duel.priority.is_open is False
    assert steps[-1].code is ValidationCode.OK
    assert "판이 다시 열렸습니다" in steps[-1].reason


# ======================================================================
# P. 통합 ② — 체인 링크 2 가 마지막 빈 칸을 채운다
# ======================================================================


@pytest.mark.real_card
def test_p01_the_last_free_zone_filled_during_the_chain_is_a_normal_no_op(
    repository,
):
    """
    🔴 **해결 시점에 상대의 마지막 칸이 차면 양쪽 모두 토큰을 만들지
    않는다 — 정상 불발이다** (B 필수 사례 2).

    발동 시점에는 양쪽에 놓을 자리가 있었다 (상대 넷 + 빈 칸 하나). 체인
    링크 2 가 **상대의** 마지막 칸을 채우고, 기르수 ③ 의 해결 시점
    재검사(``s.tkop``)가 거짓이 되어 **아무 일도 하지 않고** 끝난다.

    🔴 **미지원도 오류도 아니다.** ``UNKNOWN`` 으로 바뀌지 않고, 모자란
    규칙 이름이 붙지 않으며, **한쪽에만** 토큰이 생기지도 않는다 — 자신
    쪽에는 빈 칸이 있었는데도 그렇다.
    """
    duel, chooser, journal, field, _hand, their_field, their_hand = _board(
        repository,
        mine=(GIRSU,),
        their_mzone=(GIRSU,) * 4,
        their_hand=(WAND,),
        trap_seat=P1,
    )
    #: 발동 직전 — 상대 필드는 넷이고 **빈 칸이 하나** 남았다.
    assert len(_mzone(duel, P1)) == 4
    assert [card_id for card_id, _ in _mzone(duel, P0)] == [GIRSU]

    #: ① 체인 링크 1 — 빈 칸이 있으므로 발동이 **선다**.
    first = _activate(duel, P0, TOKEN_EFFECT)
    assert first.accepted is True, first.reason
    assert _links(duel) == [str(TOKEN_EFFECT)]

    #: ② 체인 링크 2 — **상대가** 자기 필드의 마지막 칸을 채운다.
    second = _chain_in(duel, TRAP_REF)
    assert second.accepted is True, second.reason
    assert _links(duel) == [str(TOKEN_EFFECT), str(TRAP_REF)]

    steps = _settle(duel)

    #: ③ 🔴 **링크 2 가 먼저 해결되어** 상대 필드를 다 채웠다.
    #:
    #: 🔴 기르수 ③ 은 기록에 **없다** — ``EffectEvent`` 는 "해결되어 판이
    #: 달라진 사건" 이고 (``engine/effect/journal.py``), 불발은 판을 바꾸지
    #: 않았으므로 남길 사건이 없다. 그것이 ``test_p02`` 의 대조군과 갈리는
    #: 자리다 (저쪽은 둘 다 기록된다).
    assert _resolved_refs(journal) == [str(TRAP_REF)]
    assert len(_mzone(duel, P1)) == 5
    filled = next(
        (r for r in chooser.records if r.effect_ref == TRAP_REF), None
    )
    assert filled is not None and filled.chosen
    assert filled.chosen[0] in their_hand

    #: ④ 🔴 **양쪽 모두 토큰이 없다** — 부분 적용이 없다.
    assert _tokens(duel, P0) == []
    assert _tokens(duel, P1) == []
    assert [card_id for card_id, _ in _mzone(duel, P0)] == [GIRSU]
    assert field[0] in [instance for _c, instance in _mzone(duel, P0)]

    #: ⑤ 🔴 **정상 불발**이다 — 코드는 ``OK``, 모자란 규칙이 없고, 사유가
    #:    어느 칸이 막았는지 적는다.
    said = _said(steps, TOKEN_EFFECT)
    assert said is not None
    assert said.code is ValidationCode.OK, said.reason
    assert "일을 하지 않았습니다" in said.reason
    assert "상대 MZONE 에 빈 칸이 없습니다 (5/5)" in said.reason
    assert "해결하지 못했습니다" not in said.reason
    #: 🔴 **모름으로 바뀌지 않았다.** 코드가 ``RULE_NOT_IMPLEMENTED`` 가
    #: 아니고 사유에 "판정할 수 없" 이 없다 — 그리고 사유가 **공식 스크립트
    #: 의 그 줄**을 근거로 든다 (``s.tkop`` 의 재검사). 즉 "아직 구현하지
    #: 않아서 안 된 것" 이 아니라 **규칙이 그렇게 끝낸 것**이다.
    assert said.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert "판정할 수 없" not in said.reason
    assert "s.tkop" in said.reason, said.reason

    #: ⑥ 효과 사용 제한은 **발동했으므로** 기록된다 — 불발이어도 쓴 것이다.
    assert (
        duel.state.uses.count(LimitScope.PER_EFFECT, effect_key(P0, TOKEN_EFFECT))
        == 1
    )

    #: ⑦ 체인이 비고 판이 다시 열렸다.
    assert duel.chain.is_empty
    assert duel.priority.is_open is False
    assert "판이 다시 열렸습니다" in steps[-1].reason


@pytest.mark.real_card
def test_p02_the_same_board_without_the_chain_link_makes_both_tokens(
    repository,
):
    """
    🔴 **대조군** — 링크 2 가 없으면 **같은 시작 판**에서 토큰이 생긴다.

    이것이 없으면 ``test_p01`` 의 불발이 "그 판에서는 애초에 안 되는
    것이었다" 와 구분되지 않는다. 상대 필드가 넷인 채로 기르수 ③ 만
    해결시키면 양쪽에 토큰이 하나씩 생기고, 상대 필드는 다섯이 된다.
    """
    duel, _chooser, journal, _field, _hand, _their_field, _their_hand = _board(
        repository,
        mine=(GIRSU,),
        their_mzone=(GIRSU,) * 4,
        their_hand=(WAND,),
        trap_seat=P1,
    )
    assert _activate(duel, P0, TOKEN_EFFECT).accepted is True
    steps = _settle(duel)

    assert _resolved_refs(journal) == [str(TOKEN_EFFECT)]
    assert len(_tokens(duel, P0)) == 1  # 🔴 불발과 달리 기록이 남는다
    assert len(_tokens(duel, P1)) == 1
    assert len(_mzone(duel, P1)) == 5
    said = _said(steps, TOKEN_EFFECT)
    assert said is not None and said.code is ValidationCode.OK
    assert "일을 하지 않았습니다" not in said.reason
