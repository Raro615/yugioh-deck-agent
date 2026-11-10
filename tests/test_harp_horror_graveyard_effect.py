"""
Phase 6-AO — **오르페골 디베르(57835716) ① 을 전체 경로로 연결한다.**

    합법 행동 후보 생성 → 발동 조건과 비용 검증 → 비용 지불과 체인 처리
    → 해결 중 허용 카드 선택 → 특수 소환 → 사용 제한 · 소환 제한 기록
    → 탐색 → 새 초기 상태에서 전체 경로 재생

효과 계약 — 공식 한국어 텍스트와 Lua
=====================================
``data/cards.cdb`` (57835716)::

    이 카드명의 효과는 1턴에 1번밖에 사용할 수 없다.
    ①: 묘지의 이 카드를 제외하고 발동할 수 있다. 덱에서 "오르페골 디베르"
    이외의 "오르페골" 몬스터 1장을 특수 소환한다. 이 효과의 발동 후,
    턴 종료시까지 자신은 어둠 속성 몬스터밖에 특수 소환할 수 없다.

``c57835716.lua`` 의 ``e1`` 에서 읽은 자리들 (전문은
:data:`~engine.effect.library.EFFECT_LIBRARY` 의 항목 주석에 있다):

=============================  ========================================
**발동 위치**                   ``SetRange(LOCATION_GRAVE)`` — 묘지
**발동 분류**                   ``EFFECT_TYPE_IGNITION`` — 기동
**비용**                        ``Cost.SelfBanish`` — **이 카드 자신**을 제외
**비용 지불 시점**               발동 시점 (``SetCost``)
**발동 조건**                   빈 몬스터 존 · 특수 소환 금지 없음 ·
                               「오르페골 바벨」 이 적용되지 않음
**덱 후보 조건**                 「오르페골」 몬스터 · **디베르 이외** ·
                               지금 특수 소환할 수 있다
**대상 지정**                   **아니다** (``SetOperationInfo`` 가
                               카드를 ``nil`` 로 적는다)
**고르는 시점**                  **해결 중** (``s.spop`` 의
                               ``SelectMatchingCard``)
**소환 자리 · 표시 형식**         자신 몬스터 존 · 앞면 공격
                               (``POS_FACEUP`` → 이 저장소의 고정값)
**같은 이름 사용 제한**           ``SetCountLimit(1,id)`` — 카드명 기준 1턴 1번
**이후의 특수 소환 제한**         어둠 속성만 · **자신에게만** ·
                               **턴 종료까지** · 소환법을 가리지 않음
**무효 · 불발 시의 비용**         되돌아오지 않는다 (비용은 발동 시점에
                               치러졌고 해결기는 그것을 모른다)
=============================  ========================================

이 파일의 일곱 절
=================
=====  ==========================================================
A 절   **계약이 등록표와 같은 모양인가** (판을 만들지 않는 단위 검사)
B 절   **발동의 성공 · 실패 경계** (준비한 작은 상태)
C 절   **비용** — 치를 수 있는가 · 치른 뒤 되돌아오지 않는가
D 절   **해결** — 선택 · 특수 소환 · 사용 제한 · 소환 제한의 기록
E 절   **제한의 적용 범위** — 효과 · 링크 · 토큰 세 경로와 만료
F 절   **시작 패부터의 통합**과 탐색 · 전체 경로 재생
G 절   **격리와 일치** — 원본 불변 · 분기 간 격리 · 후보와 직접 실행
=====  ==========================================================

🔴 **B~E 절의 판은 손으로 구성한 시작 상태다.** 그 상태가 기존 시작 패에서
도달 가능하다고 주장하지 않는다 — 그 질문의 답은 **F 절**이고, 보고서
``docs/orcust-harp-horror-graveyard-extension.md`` §5~§7 이 둘을 갈라 적는다.

🔴 **합성인 것을 정확히 적는다.** E 절의 일부 시험은 「WIND 속성만 허용」 이라는
**손으로 적은 제한 기록**을 쓴다. 실제 카드가 그런 제한을 걸지는 않지만, 등재된
링크 몬스터와 토큰이 **전부 어둠 속성**이므로 (실측) 실제 제한으로는 거절
쪽을 만들 수 없다. 🔴 **거절을 재는 판정 경로는 실제 production 경로 그대로다** —
합성인 것은 기록의 **값** 하나다.
"""

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.condition import ConditionContext, ConditionResult, PlayerRef
from engine.cost import CostGroup, CostSemantics, SelfCardCost
from engine.cost.validation import CostValidator
from engine.duel import Duel
from engine.effect.library import (
    EFFECT_LIBRARY,
    HARP_HORROR,
    OPERATION_RULINGS,
    entry_for,
)
from engine.effect.operation import (
    OperationKind,
    RestrictSpecialSummonOperation,
    SpecialSummonOperation,
)
from engine.effect.ruling import (
    REVIVAL_LIMIT_FREE_ZONES,
    BoardRuling,
    RuleQuestion,
)
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.link_rules import LinkMaterialEligibility, assess_link_materials
from engine.payment import SUPPORTED_COSTS, CostPayer, PaymentContext, PaymentStatus
from engine.priority import PriorityState
from engine.spell_activation import activatable_effects, duel_components
from engine.special_summon import SPECIAL_SUMMON_FROM_ZONES
from engine.state.game_state import GameState
from engine.state.summon_limit import AttributeOnlyLimit, SummonLimitRegistry
from engine.summon_restriction import (
    SpecialSummonPermission,
    assess_special_summon_permission,
    prohibition_for,
)
from engine.use_limit import LimitScope
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

#: 🔴 **오르페골 디베르** — 이 Phase 가 등재한 효과의 주인.
DIBER = 57835716
#: 오르페골 스켈레촌 — 디베르 ① 이 덱에서 특수 소환할 후보. ① 은 미등재.
SKELETON = 21441617
#: 오르페골 카노네 — 같은 자리의 다른 후보.
CANNONE = 94046012
#: 잭나이츠 오르페골 기르수 — 일반 소환되고 ① 로 디베르를 묘지에 둔다.
GIRSU = 69811710
#: 오르페골 갈라테아 — LINK-2. **어둠 속성**이므로 디베르의 제한을 지난다.
GALATEA = 30741503
#: 오르페골 바벨 — 앞면으로 있으면 ① 의 조건(``s.spcon1``) 이 거짓이다.
BABEL = 90351981
#: 엘리멘틀 히어로 페더맨 — **WIND 속성** 통상 몬스터. 「어둠 속성만」
#: 제한의 **거절** 쪽을 실제 카드로 재는 자리다.
FEATHERMAN = 21844576
#: 성유물 토큰 — 기르수 ③ 이 만든다. 어둠 속성이다 (실측).
WORLD_LEGACY_TOKEN = 46647145

P0, P1 = 0, 1
#: 🔴 **손으로 읽은 금지 표에 ``prohibits=True`` 로 있는 실제 카드** —
#: 파슬 다이너 파키세팔로. ``test_h03`` 이 "확정적으로 부적격" 을 만드는
#: 수단으로 쓴다.
PACHYCEPHALO = 42009836
#: 🔴 **「오르페골」 몬스터인데 특수 소환 가능 여부를 읽지 않은 실제 카드** —
#: 오르페골 트로이메어 (LINK-2). ``test_h04`` 가 "모름" 을 만드는 수단으로
#: 쓴다. 🔴 **이 자리의 카드는 등록소가 늘 때마다 바뀐다** — 재는 것은
#: "읽지 않은 후보는 생략의 근거가 되지 못한다" 이고 특정 카드가 아니다.
UNREAD_ORCUST = 4055337

DIBER_EFFECT = EffectRef(DIBER, 0)


# ======================================================================
# 공용 — **시작 상태만** 만든다
# ======================================================================
def _board(
    repository,
    *,
    mine=(),
    emzone=(),
    grave=(),
    deck=(),
    extra=(),
    hand=(),
    turn_number=3,
    chooser=None,
):
    """
    **시작 상태**를 만든다. 첫 행동 뒤의 모든 변화는 엔진이 만든다.

    ``deck`` 의 카드들이 덱 **앞쪽**에 놓이고 그 뒤를 페더맨이 채운다.
    섞지 않으므로 (``shuffle=False``) 같은 입력이 같은 판을 만든다.

    🔴 **유발 배선을 꽂는다** — 꽂지 않으면 사건이 유발 후보를 열지 못하고,
    그러면 "유발이 없다" 와 "배선이 없다" 가 구별되지 않는다.
    """
    from app.main import opening_wiring

    state = GameState.create(
        repository,
        decks=(list(deck) + [FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
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
    for index, card_id in enumerate(emzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.EMZONE)
        state.move(
            instance,
            Zone.EMZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field.append(instance.instance_id)
    grave_ids = []
    for card_id in grave:
        instance = state.create_instance(card_id, owner=P0, zone=Zone.GRAVE)
        state.move(instance, Zone.GRAVE, to_player=P0)
        grave_ids.append(instance.instance_id)
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    hand_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.HAND).instance_id
        for card_id in hand
    ]
    state.turn.turn_number = turn_number
    state.turn.set_phase(Phase.MAIN1)
    wired, triggers = opening_wiring(repository, None)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        triggers=triggers,
        **duel_components(chooser=chooser if chooser is not None else wired),
    )
    return duel, field, grave_ids, extra_ids, hand_ids


def _zone_ids(duel, zone, seat=P0):
    return [card.card_id for card in duel.state.zone(seat, zone)]


def _diber_offer(duel, source):
    """디베르 ① 의 **허가된 후보**. 없으면 ``None``."""
    duel.advance()
    for action in duel.legal_actions(P0).allowed:
        if (
            action.kind is PlayerActionKind.ACTIVATE_EFFECT
            and action.source == source
            and action.effect_ref == DIBER_EFFECT
        ):
            return action
    return None


def _diber_withheld(duel):
    """디베르 ① 이 왜 후보가 되지 못했는가 — ``(코드, 없는 규칙, 문장)``."""
    duel.advance()
    return [
        (w.code.value, w.missing, w.reason)
        for w in duel.legal_actions(P0).withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
        and str(DIBER_EFFECT) in w.reason
    ]


def _limits(duel, seat=P0):
    state = duel.state
    return state.summon_limits.active(state.turn.turn_number, seat)


def _snapshot(duel):
    """판 · 사용 기록 · 제한을 함께 뜬다."""
    state = duel.state
    return (
        state.state_hash(),
        state.summon_limits.canonical_state(),
        tuple(
            tuple(card.card_id for card in state.zone(seat, zone))
            for seat in (P0, P1)
            for zone in (
                Zone.MZONE,
                Zone.EMZONE,
                Zone.GRAVE,
                Zone.REMOVED,
                Zone.HAND,
            )
        ),
    )


class _PickExactly:
    """
    해결 중에 **지정한 카드를 고른다** — 시험용 선택 정책.

    🔴 **엔진의 판정을 우회하지 않는다.** 고른 것이 허용 후보 밖이면
    실행기가 거절한다 (``EffectExecutor`` 의 ③ 단계) — 이 정책은 그 관문을
    **재기 위해** 있다.
    """

    name = "pick-exactly"

    def __init__(self, instances):
        self.instances = tuple(instances)

    def accept_offer(self, offer) -> bool:  # pragma: no cover - 유발용
        return True

    def choose_cards(self, offer):  # pragma: no cover - 유발용
        return self.instances

    def choose(self, request):
        return self.instances

    def forked(self):
        return self


# ======================================================================
# A. 계약이 등록표와 같은 모양인가
# ======================================================================
def test_a01_the_registered_definition_matches_the_contract():
    """
    🔴 **머리말의 계약표를 등록표에서 그대로 확인한다.** 근거 없이 적힌
    정의는 검증된 규칙이 아니므로 ``lua_file`` · ``lua_excerpt`` 도 본다.
    """
    entry = entry_for(DIBER_EFFECT)
    assert entry is not None
    assert entry.executable is True
    definition = entry.definition
    #: 발동 위치 · 분류.
    assert definition.activation_zones == frozenset({Zone.GRAVE})
    assert definition.activation_kind.value == "IGNITION"
    #: 비용 — **자신을 제외**하고, 고를 것이 없다.
    assert len(definition.cost) == 1
    cost = definition.cost.costs[0]
    assert isinstance(cost, SelfCardCost)
    assert cost.semantics is CostSemantics.BANISH
    assert cost.zones == frozenset({Zone.GRAVE})
    assert cost.choice_spec() is None
    #: 하는 일 — 특수 소환 **다음에** 제한을 건다 (``EFFECT_FLAG_OATH``).
    kinds = [operation.kind for operation in definition.operations]
    assert kinds == [
        OperationKind.SPECIAL_SUMMON,
        OperationKind.RESTRICT_SPECIAL_SUMMON,
    ]
    assert isinstance(definition.operations[0], SpecialSummonOperation)
    restrict = definition.operations[1]
    assert isinstance(restrict, RestrictSpecialSummonOperation)
    assert restrict.attribute == "DARK"
    assert restrict.who is PlayerRef.CONTROLLER
    assert "EFFECT_CANNOT_SPECIAL_SUMMON" in restrict.basis
    #: 사용 제한 — 카드명 기준.
    assert definition.use_limit is not None
    assert definition.use_limit.scope is LimitScope.PER_CARD_NAME
    assert definition.use_limit.times == 1
    #: 해결 시점의 재검사와 정상 불발 선언.
    assert definition.resolution_condition is not None
    assert definition.resolution_skip is not None
    assert definition.resolution_skip.when_condition_false is True
    assert definition.resolution_skip.when_no_candidate is True
    #: 근거.
    assert entry.lua_file == "c57835716.lua"
    assert "Cost.SelfBanish" in entry.lua_excerpt
    assert "LOCATION_GRAVE" in entry.lua_excerpt
    assert "not c:IsCode(id)" in entry.lua_excerpt


def test_a02_only_the_ignition_half_is_registered():
    """
    🔴 **``e2`` 는 등재하지 않았다** — 바벨이 적용될 때 쓰이는 유발즉시
    쪽이다. 등재된 것이 하나임을 세어, 다음 사람이 ② 를 등재할 때 이 시험이
    깨지게 한다 (성유물－『성장』 ③ 의 guard 와 같은 규율).
    """
    refs = {entry.effect_ref for entry in EFFECT_LIBRARY if entry.card_id == DIBER}
    assert refs == {DIBER_EFFECT}
    assert tuple(activatable_effects(DIBER)) == (DIBER_EFFECT,)


def test_a03_the_candidate_facts_we_read_are_declared():
    """
    🔴 **덱의 후보가 "지금 특수 소환할 수 있는가" 는 카드별로 묻는다**
    (``s.filter`` 의 ``IsCanBeSpecialSummoned`` → 관문). 읽은 카드만
    답이 있고, 읽지 않은 카드는 ``UNKNOWN`` 이다 (ADR-006).
    """
    for card_id in (DIBER, SKELETON, CANNONE, GIRSU):
        facts = OPERATION_RULINGS.facts_for(card_id)
        assert facts is not None, card_id
        fact = facts.answers.get(RuleQuestion.MAY_BE_SPECIAL_SUMMONED)
        assert fact is not None, card_id
        assert fact.answer is ConditionResult.TRUE
        assert fact.note
        #: 🔴 **필드에 있다는 사실이 남을 막지 않는다** — 막으면 이 카드가
        #: 나온 뒤의 모든 특수 소환 판정이 ``UNKNOWN`` 이 된다.
        assert facts.restricts_others is False
    #: 기르수 ① 이 덱에서 **디베르를 묘지로 보낼 수 있는가** 도 읽었다.
    diber = OPERATION_RULINGS.facts_for(DIBER)
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE in diber.answers


def test_a04_the_three_orcust_monsters_do_not_block_by_standing_there():
    """
    🔴 **신호를 적었는데 표에 없으면 판 전체가 ``UNDETERMINED`` 가 된다.**

    디베르 · 스켈레촌 · 카노네는 ``EFFECT_CANNOT_SPECIAL_SUMMON`` 을 적지만
    (실측: ``special_summon_restriction_signals``), 그것은 **발동한 뒤**에
    플레이어에게 걸리는 제한이고 필드에 있다는 사실과 무관하다. 그래서 금지
    표에 ``prohibits=False`` 로 적혀 있어야 한다.
    """
    for card_id in (DIBER, SKELETON, CANNONE):
        rule = prohibition_for(card_id)
        assert rule is not None, card_id
        assert rule.prohibits is False
        assert rule.scope is None
        assert rule.lua_file
        assert rule.note


def test_a05_the_moved_layers_say_what_they_opened():
    """
    🔴 **이 Phase 가 넓힌 공용 계층 셋을 그대로 센다.** 넓힌 것이 맞는지는
    각 자리의 주석이 근거를 적고, 이 시험은 **그 범위가 의도한 만큼인지**를
    본다 — 더 넓어지면 깨진다.
    """
    #: 비용으로서의 제외가 치를 수 있는 비용이 되었다.
    assert CostSemantics.BANISH in SUPPORTED_COSTS
    #: 덱에서 나오는 특수 소환을 절차가 옮겼다 — **엑스트라 덱은 아니다.**
    assert Zone.DECK in SPECIAL_SUMMON_FROM_ZONES
    assert Zone.EXTRA not in SPECIAL_SUMMON_FROM_ZONES
    #: 덱은 소생 제한을 묻지 않는 자리다 — **엑스트라 덱은 아니다.**
    assert REVIVAL_LIMIT_FREE_ZONES == frozenset({Zone.HAND, Zone.DECK})


# ======================================================================
# B. 발동의 성공 · 실패 경계 (준비한 작은 상태)
# ======================================================================
@pytest.mark.real_card
def test_b01_the_graveyard_ignition_is_offered(repository):
    """
    🔴 **정상 발동** — 묘지에 디베르, 덱에 「오르페골」 몬스터, 빈 몬스터 존.

    세 계층이 같은 답을 내는지 함께 본다: 후보 목록 · 관문 · 직접 실행.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None, _diber_withheld(duel)
    #: 🔴 **후보 생성이 쓰는 그 관문**이 같은 답을 낸다.
    gate = duel._activation_gate(
        action, validator=duel.activation_validator(P0), selections=()
    )
    assert gate.validity is ActionValidity.VALID, gate.reason


@pytest.mark.real_card
def test_b02_the_hand_is_the_wrong_place(repository):
    """
    🔴 **발동 위치가 아니면 확정 거부다** (모름이 아니다). 정의가 발동 자리를
    적어 두었으므로 (``activation_zones``) "그 자리가 아니다" 를 규칙이
    답한다 — 적지 않은 효과는 ``UNKNOWN`` 으로 남는다.
    """
    duel, _f, _g, _e, hand = _board(
        repository, mine=(GIRSU,), deck=(SKELETON,), hand=(DIBER,)
    )
    assert _diber_offer(duel, hand[0]) is None
    held = _diber_withheld(duel)
    assert held, "거절 사유가 적히지 않았습니다"
    assert any(code == ValidationCode.SOURCE_WRONG_ZONE.value for code, _, _ in held)
    assert any("GRAVE" in reason for _, _, reason in held)


@pytest.mark.real_card
def test_b03_a_full_monster_zone_refuses_the_activation(repository):
    """
    🔴 **빈 칸이 없으면 발동 조건이 거짓이다** (``s.sptg`` 의
    ``GetLocationCount``). 미지원이 아니라 **규칙의 거절**이다.
    """
    duel, _f, grave, _e, _h = _board(
        repository,
        mine=(GIRSU, GIRSU, GIRSU, GIRSU, GIRSU),
        grave=(DIBER,),
        deck=(SKELETON,),
    )
    assert _diber_offer(duel, grave[0]) is None
    held = _diber_withheld(duel)
    assert any("MZONE 에 빈 칸" in reason for _, _, reason in held)


@pytest.mark.real_card
def test_b04_no_legal_deck_candidate_refuses_the_activation(repository):
    """
    🔴 **고를 수 있는 후보가 없으면 발동하지 못한다** (``s.sptg`` 의
    ``IsExistingMatchingCard``). 덱에 「오르페골」 몬스터가 **디베르뿐**인
    판으로 잰다 — 그 사본들은 「디베르 이외」 조건에서 빠진다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(DIBER, DIBER)
    )
    assert _diber_offer(duel, grave[0]) is None
    held = _diber_withheld(duel)
    assert any(code == ValidationCode.NO_CANDIDATES.value for code, _, _ in held), held


@pytest.mark.real_card
def test_b05_the_same_name_is_excluded_not_merely_the_same_instance(repository):
    """
    🔴 **「디베르 이외」 는 카드명 조건이다.** 묘지의 디베르 **한 장**만
    빼는 것이 아니라 덱의 사본도 함께 빠진다 — ``instance_id`` 로 한 장만
    빼면 둘째 사본이 조용히 통과한다.

    덱에 디베르 사본 **둘**과 스켈레촌 **하나**를 두고, 실제로 소환되는
    카드가 스켈레촌인지 본다.
    """
    duel, _f, grave, _e, _h = _board(
        repository,
        mine=(GIRSU,),
        grave=(DIBER,),
        deck=(DIBER, DIBER, SKELETON),
        chooser=None,
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None, _diber_withheld(duel)
    assert duel.apply(action).accepted is True
    settle_chain(duel)
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU, SKELETON]
    #: 디베르 사본은 덱에 **그대로** 있다.
    assert _zone_ids(duel, Zone.DECK).count(DIBER) == 2


@pytest.mark.real_card
def test_b06_orcustrated_babel_turns_the_ignition_half_off(repository):
    """
    🔴 **``s.spcon1`` 은 바벨이 적용되지 **않을** 때의 조건이다.** 바벨이
    앞면으로 있으면 공식 카드는 ② (유발즉시) 를 쓰는데, 그 분류는 이
    저장소가 허가하지 않는다 — 그래서 **어느 쪽도 발동되지 않는다.** 그
    사실을 그대로 적는다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    babel = duel.state.create_instance(BABEL, owner=P0, zone=Zone.FZONE)
    duel.state.move(
        babel, Zone.FZONE, to_player=P0, index=0, position=Position.FACEUP
    )
    assert _diber_offer(duel, grave[0]) is None
    held = _diber_withheld(duel)
    assert any(str(BABEL) in reason for _, _, reason in held), held


@pytest.mark.real_card
def test_b07_the_use_limit_is_per_card_name(repository):
    """
    🔴 **다른 개체로 우회할 수 없다.** 묘지에 디베르 두 장을 두고, 한 장이
    발동한 뒤 **다른 개체**가 후보가 되는지 본다 — ``SetCountLimit(1,id)``
    는 카드명 기준이므로 되지 않아야 한다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER, DIBER), deck=(SKELETON, CANNONE)
    )
    first = _diber_offer(duel, grave[0])
    assert first is not None
    assert duel.apply(first).accepted is True
    settle_chain(duel)
    #: 둘째 개체는 여전히 묘지에 있다 — 비용으로 떠난 것은 첫째다.
    assert grave[1] in {card.instance_id for card in duel.state.zone(P0, Zone.GRAVE)}
    assert _diber_offer(duel, grave[1]) is None
    held = _diber_withheld(duel)
    assert any("이미 1번 썼습니다" in reason for _, _, reason in held), held


# ======================================================================
# C. 비용
# ======================================================================
def test_c01_the_self_cost_needs_no_selection():
    """
    🔴 **고를 것이 없는 비용이다.** :meth:`CostGroup.choice_specs` 에서
    빠지므로 고르는 계층을 지나지 않고 치를 수 있다 — 그것이 이 자료형이
    :class:`~engine.cost.CardCost` 와 갈라진 이유다.
    """
    cost = SelfCardCost.banish(frozenset({Zone.GRAVE}))
    assert cost.choice_spec() is None
    assert CostGroup((cost,)).choice_specs() == ()
    assert cost.semantics is CostSemantics.BANISH
    assert "제외" in cost.describe_ko()


@pytest.mark.real_card
def test_c02_the_cost_cannot_be_paid_from_the_wrong_zone(repository):
    """
    🔴 **치를 수 없는 비용은 판정에서 걸리고, 판은 바뀌지 않는다.**

    검증기와 지불기를 **직접** 부른다 — 듀얼 고리를 지나지 않는 길에도
    우회가 없어야 한다.
    """
    duel, field, _g, _e, _h = _board(repository, mine=(DIBER,), deck=(SKELETON,))
    cost = SelfCardCost.banish(frozenset({Zone.GRAVE}))
    context = ConditionContext(player=P0, source=field[0], effect_ref=DIBER_EFFECT)
    verdict = CostValidator(duel.view(P0)).validate(cost, context)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.SOURCE_WRONG_ZONE

    before = _snapshot(duel)
    paid = CostPayer().pay(
        duel.state,
        CostGroup((cost,)),
        PaymentContext(payer=P0, source=field[0], effect_ref=DIBER_EFFECT),
    )
    assert paid.paid is False
    assert paid.status is PaymentStatus.CANNOT_PAY
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_c03_the_cost_is_paid_at_activation_not_at_resolution(repository):
    """
    🔴 **비용과 해결을 한 단계로 뭉개지 않는다.** 발동이 수락된 **직후**
    (체인이 아직 해결되지 않은 시점) 에 디베르가 이미 제외되어 있어야 한다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    #: 아직 해결하지 않았다.
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    #: 그런데 비용은 이미 치러졌다.
    assert _zone_ids(duel, Zone.GRAVE) == []
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]


@pytest.mark.real_card
def test_c04_a_resolution_that_does_nothing_keeps_the_cost(repository):
    """
    🔴 **해결이 불발되어도 비용은 되돌아오지 않는다.**

    🔴 그리고 **제한도 걸리지 않는다** — 공식 스크립트의 ``s.spop`` 이 빈
    칸을 다시 보고 ``return`` 하는 자리가 ``RegisterEffect`` **앞**이다.

    발동과 해결 사이의 상태 변화는 **시험이 손으로 만든다** (몬스터 존을
    채운다) — 그 자리를 실제 카드로 만들 수단이 이 저장소에 없다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True

    state = duel.state
    for index in range(1, 5):
        filler = state.create_instance(FEATHERMAN, owner=P0, zone=Zone.MZONE)
        state.move(
            filler,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
    settle_chain(duel)

    #: 아무것도 소환되지 않았다 (채운 네 장 그대로).
    assert _zone_ids(duel, Zone.MZONE).count(SKELETON) == 0
    #: 비용은 그대로다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    #: 제한은 걸리지 않았다.
    assert _limits(duel) == ()


# ======================================================================
# D. 해결 — 선택 · 특수 소환 · 기록
# ======================================================================
@pytest.mark.real_card
def test_d01_the_resolution_summons_and_records_everything(repository):
    """
    🔴 **해결 한 번의 실제 변화 전부.** 덱에서 고른 몬스터가 자신 몬스터
    존에 앞면 공격 표시로 놓이고, 사용 제한과 특수 소환 제한이 기록된다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON, CANNONE)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)

    state = duel.state
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU, SKELETON]
    summoned = [c for c in state.zone(P0, Zone.MZONE) if c.card_id == SKELETON][0]
    assert summoned.position is Position.FACEUP_ATTACK
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    #: 고르지 않은 후보는 덱에 남는다.
    assert CANNONE in _zone_ids(duel, Zone.DECK)
    #: 사용 제한 — 카드명 기준으로 1번.
    limit = entry_for(DIBER_EFFECT).definition.use_limit
    key = limit.key_for(P0, DIBER_EFFECT, grave[0])
    assert state.uses.count(limit.scope, key) == 1
    #: 특수 소환 제한 — 하나, 어둠 속성, 자신에게.
    active = _limits(duel)
    assert len(active) == 1
    assert active[0].attribute == "DARK"
    assert active[0].player == P0
    assert active[0].source_card_id == DIBER
    assert active[0].basis


@pytest.mark.real_card
def test_d02_the_summon_is_recorded_as_a_summon_event(repository):
    """
    🔴 **옮긴 것이 아니라 소환이다.** 기록에 소환 사건이 남아야 「특수
    소환되었을 경우」 유발이 그것을 볼 수 있다.

    🔴 **그런데 이 판에서 유발은 열리지 않는다** — 기르수 ① 의 특수 소환
    복제본(``e[1]``, ``EVENT_SPSUMMON_SUCCESS``) 은 등재되지 않았고, 등재된
    ``e[0]`` 은 **일반 소환** 사건에만 걸린다. 사건이 없는 것과 등재가 없는
    것은 다른 사실이므로 **둘을 함께** 적는다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, grave=(DIBER,), deck=(GIRSU,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]

    #: 기록이 소환으로 적는다.
    said = " ".join(str(event) for event in duel.journal)
    assert "소환" in said
    assert "special" in said
    #: 그리고 그 사건으로 열린 유발 제안은 **없다** (등재 범위).
    duel.advance()
    offers = [
        offer
        for offer in duel.triggers.offers(duel, P0)
        if offer.effect_ref.card_id == GIRSU
    ]
    assert offers == []
    assert EffectRef(GIRSU, 1) not in {entry.effect_ref for entry in EFFECT_LIBRARY}


@pytest.mark.real_card
def test_d03_a_card_outside_the_offered_candidates_is_refused(repository):
    """
    🔴 **해결 중 선택은 엔진이 만든 허용 후보 안에서만 이루어진다.**

    후보가 아닌 카드(페더맨 — 「오르페골」 이 아니다) 를 고르는 정책을 꽂고,
    실행기가 거절하는지 본다. 🔴 **정책이 판을 바꾸지 못한다**는 것이
    요점이다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    outsider = [
        card for card in duel.state.zone(P0, Zone.DECK) if card.card_id == FEATHERMAN
    ][0]
    duel, _f2, grave2, _e2, _h2 = _board(
        repository,
        mine=(GIRSU,),
        grave=(DIBER,),
        deck=(SKELETON,),
        chooser=_PickExactly((outsider.instance_id,)),
    )
    action = _diber_offer(duel, grave2[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)
    #: 아무것도 소환되지 않았고 제한도 걸리지 않았다.
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    assert _limits(duel) == ()
    #: 비용은 그대로다 — 발동은 성립했다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]


# ======================================================================
# E. 제한의 적용 범위
# ======================================================================
@pytest.mark.real_card
def test_e01_the_dark_limit_refuses_a_non_dark_effect_summon(repository):
    """
    🔴 **실제 제한 · 실제 카드 · 실제 관문.** 디베르 ① 을 해결한 뒤, 효과에
    의한 특수 소환의 공용 관문(:meth:`BoardRuling.explain_special_summon`)
    에 **WIND 속성** 페더맨을 물으면 ``FALSE`` 여야 한다.

    🔴 그리고 **어둠 속성은 그대로 통과한다** — 제한이 전부를 막지 않는다.
    """
    duel, _f, grave, _e, _h = _board(
        repository,
        mine=(GIRSU,),
        grave=(DIBER,),
        deck=(SKELETON,),
        hand=(FEATHERMAN, GIRSU),
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)
    assert len(_limits(duel)) == 1

    ruling = BoardRuling(duel.view(P0), OPERATION_RULINGS)
    hand = {card.card_id: card.instance_id for card in duel.state.zone(P0, Zone.HAND)}
    wind = ruling.explain_special_summon(hand[FEATHERMAN])
    assert wind.answer is ConditionResult.FALSE
    assert "DARK" in wind.reason
    assert str(DIBER) in wind.reason
    dark = ruling.explain_special_summon(hand[GIRSU])
    assert dark.answer is ConditionResult.TRUE, dark.reason


@pytest.mark.real_card
def test_e02_a_dark_link_summon_still_passes_the_limit(repository):
    """
    🔴 **제한이 정상 전개를 막지 않는다.** 디베르 ① 뒤에도 갈라테아(어둠
    속성) 의 링크 소환은 합법이다 — 이것이 F 절 통합 경로의 근거다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,), extra=[GALATEA]
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    duel.apply(action)
    settle_chain(duel)

    extra_id = [c.instance_id for c in duel.state.zone(P0, Zone.EXTRA)][0]
    materials = tuple(c.instance_id for c in duel.state.zone(P0, Zone.MZONE))
    verdict = assess_link_materials(duel.view(P0), P0, extra_id, materials)
    assert verdict.eligibility is LinkMaterialEligibility.LEGAL, verdict.reason


@pytest.mark.real_card
def test_e03_the_limit_also_reaches_the_link_summon_path(repository):
    """
    🔴 **다른 특수 소환 경로로 우회되지 않는다** — 링크 소환도 특수 소환이다.

    🔴 **합성인 것을 적는다**: 등재된 링크 몬스터가 전부 어둠 속성이므로
    (실측) 실제 제한으로는 거절 쪽을 만들 수 없다. 그래서 **제한 기록의 값만**
    「WIND 속성만 허용」 으로 손으로 적고, 판정 경로는 production 그대로
    둔다 — 재는 것은 "링크 소환 판정이 이 표를 본다" 다.
    """
    duel, field, _g, extra, _h = _board(
        repository, mine=(GIRSU, SKELETON), extra=[GALATEA]
    )
    duel.state.summon_limits.record(
        AttributeOnlyLimit(
            turn_number=duel.state.turn.turn_number,
            player=P0,
            attribute="WIND",
            source_card_id=DIBER,
            ordinal=0,
            basis="시험용으로 손으로 적은 제한 — 실제 카드의 값이 아니다",
        )
    )
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], tuple(field))
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "WIND" in verdict.reason
    assert "DARK" in verdict.reason
    #: 후보 생성도 같은 답을 낸다.
    duel.advance()
    offered = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.LINK_SUMMON
    ]
    assert offered == []


@pytest.mark.real_card
def test_e04_the_limit_also_reaches_the_token_path(repository):
    """
    🔴 **토큰도 특수 소환이다.** 토큰의 개체는 해결 전에 없으므로 관문에
    넘길 ``InstanceId`` 가 없고, 대신 **손으로 읽어 대조한 토큰 데이터**의
    속성을 묻는다 (:class:`~engine.token.TokenRule`).

    여기서도 제한 기록의 **값만** 합성이다 (성유물 토큰은 어둠 속성이다 —
    실측).
    """
    duel, _f, _g, _e, _h = _board(repository, mine=(GIRSU,))
    duel.state.summon_limits.record(
        AttributeOnlyLimit(
            turn_number=duel.state.turn.turn_number,
            player=P0,
            attribute="WIND",
            source_card_id=DIBER,
            ordinal=0,
            basis="시험용으로 손으로 적은 제한 — 실제 카드의 값이 아니다",
        )
    )
    duel.advance()
    token_effect = [
        a
        for a in duel.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == EffectRef(GIRSU, 2)
    ]
    assert token_effect, "기르수 ③ 이 후보가 아닙니다"
    assert duel.apply(token_effect[0]).accepted is True
    settle_chain(duel)
    #: 🔴 **토큰이 만들어지지 않았다** — 양쪽 모두.
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    assert _zone_ids(duel, Zone.MZONE, P1) == []
    #: 그리고 그 거절은 **규칙이 막은 것**으로 적힌다.
    said = " ".join(str(event) for event in duel.journal)
    assert WORLD_LEGACY_TOKEN not in [
        card.card_id for card in duel.state.zone(P0, Zone.MZONE)
    ], said


@pytest.mark.real_card
def test_e05_the_limit_applies_only_after_the_resolution(repository):
    """
    🔴 **적용 시점**: 발동만으로는 걸리지 않는다. ``EFFECT_FLAG_OATH`` 가
    "등록 전에 진행 중이던 처리에는 걸리지 않는다" 는 뜻이고, 공식
    스크립트가 소환을 먼저 하고 등록을 나중에 한다 — 이 저장소는 조작의
    **순서**로 그것을 지킨다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    #: 발동 직후 — 아직 없다.
    assert _limits(duel) == ()
    settle_chain(duel)
    #: 해결 뒤 — 걸렸다.
    assert len(_limits(duel)) == 1


@pytest.mark.real_card
def test_e06_the_limit_expires_with_the_turn(repository):
    """
    🔴 **만료**: ``SetReset(RESET_PHASE|PHASE_END)`` 이고 공식 텍스트가
    「턴 종료시까지」 다. 기록의 열쇠에 턴 번호가 들어가므로 **다음 턴에는
    걸리지 않는다** — 지우지 않고도 만료된다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,), turn_number=3
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    duel.apply(action)
    settle_chain(duel)
    state = duel.state
    assert len(state.summon_limits.active(3, P0)) == 1
    #: 다음 턴에는 없다.
    assert state.summon_limits.active(4, P0) == ()
    #: 상대에게는 걸리지 않았다 (``SetTargetRange(1,0)``).
    assert state.summon_limits.active(3, P1) == ()


def test_e07_an_unknown_attribute_is_not_waved_through():
    """
    🔴 **모름을 허가로 접지 않는다.** 소환하려는 카드의 속성을 읽을 수
    없으면 판정은 ``UNDETERMINED`` 이고, 그것은 허가가 **아니다**.
    """
    limit = AttributeOnlyLimit(1, P0, "DARK", DIBER, 0, "시험용")
    assert limit.permits("DARK") is True
    assert limit.permits("WIND") is False
    assert limit.permits(None) is None

    class _View:
        def special_summon_limits(self, player):
            return (limit,) if player == P0 else ()

        players = ()

    class _NoAttribute:
        attribute_name = None

    told = assess_special_summon_permission(_View(), P0, summoned=_NoAttribute())
    assert told.permission is SpecialSummonPermission.UNDETERMINED
    assert told.allowed is False
    assert told.forbidden is False


def test_e08_a_view_without_the_limit_column_is_undetermined():
    """
    🔴 **없는 칸을 허가로 바꾸지 않는다.** 제한을 싣지 않는 관측(옛 객체 ·
    시험용 대역) 에서는 "막는지 알 수 없다" 가 답이다.
    """

    class _Old:
        players = ()

    told = assess_special_summon_permission(
        _Old(), P0, summoned=type("D", (), {"attribute_name": "DARK"})()
    )
    assert told.permission is SpecialSummonPermission.UNDETERMINED
    assert told.missing_rule


def test_e09_the_limit_is_part_of_the_state_hash():
    """
    🔴 **제한이 걸린 판과 걸리지 않은 판은 다른 판이다.** 해시에 들어가지
    않으면 탐색의 중복 제거가 둘을 합치고, 한쪽에서만 합법인 소환이 다른
    쪽의 경로로 보고된다.
    """
    registry = SummonLimitRegistry()
    assert registry.canonical_state() == ()
    registry.record(AttributeOnlyLimit(1, P0, "DARK", DIBER, 0, "시험용"))
    assert registry.canonical_state() == ((1, P0, "DARK", DIBER, 0),)
    #: 같은 제한을 두 번 적어도 하나다 — 「…밖에」 는 누적되지 않는다.
    registry.record(AttributeOnlyLimit(1, P0, "DARK", DIBER, 0, "시험용"))
    assert len(registry) == 1


@pytest.mark.real_card
def test_e10_the_hash_separates_the_limited_board(repository):
    """🔴 같은 존 · 같은 카드인 두 판이 **제한 때문에** 다른 해시를 갖는다."""
    duel, _f, _g, _e, _h = _board(repository, mine=(GIRSU,))
    plain = duel.state.state_hash()
    duel.state.summon_limits.record(
        AttributeOnlyLimit(duel.state.turn.turn_number, P0, "DARK", DIBER, 0, "x")
    )
    assert duel.state.state_hash() != plain


# ======================================================================
# F. 시작 패부터의 통합 · 탐색 · 재생
# ======================================================================
@pytest.mark.real_card
def test_f01_the_written_line_runs_from_the_starting_hand(repository):
    """
    🔴 **시작 패부터 끝까지 엔진이 돌린다** — 적어 둔 경로를 그대로.

    기르수 일반 소환 → ① 로 디베르를 묘지로 → 디베르 ① 로 덱에서 스켈레촌
    특수 소환 → 기르수 + 스켈레촌 으로 갈라테아 링크 소환.

    🔴 **판을 손으로 구성하지 않는다.** 시작 패와 레시피만 주고, 그 뒤의
    모든 변화는 엔진이 만든다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_HARP_HORROR_LINE as line
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe

    parsed = parse_recipe(line.recipe_ydk, repository)
    assert parsed.draft is not None
    chooser, triggers = opening_wiring(repository, line)
    setup = build_opening(
        repository, parsed.draft, list(line.hand), chooser=chooser, triggers=triggers
    )
    assert setup.can_run, setup.blockers
    run = execute_opening(setup, repository, choose=line.policy())

    kinds = [step.kind for step in run.steps]
    assert kinds == [
        "normal_summon",
        "activate_effect",
        "activate_effect",
        "link_summon",
    ], run.stopped_reason
    assert all(step.accepted for step in run.steps)

    state = setup.duel.state
    ids = lambda zone: [c.card_id for c in state.zone(P0, zone)]  # noqa: E731
    assert ids(Zone.EMZONE) == [GALATEA]
    assert ids(Zone.MZONE) == []
    assert ids(Zone.REMOVED) == [DIBER]
    assert sorted(ids(Zone.GRAVE)) == sorted([GIRSU, SKELETON])
    #: 제한이 기록되어 있고, 갈라테아는 그것을 지나 소환되었다.
    active = state.summon_limits.active(state.turn.turn_number, P0)
    assert len(active) == 1
    assert active[0].attribute == "DARK"


@pytest.mark.real_card
def test_f02_the_hand_and_the_recipe_pass_the_existing_checks(repository):
    """
    🔴 **새 시작 패가 그 레시피에서 나올 수 있는가** — 기존 입력 검증을
    그대로 지난다. 🔴 **레시피는 기존 검증용 레시피 그대로다** (디베르가 이미
    x3 들어 있다).

    🔴 **대회 합법 덱이라고 주장하지 않는다** — 금지 · 제한 데이터가 없으므로
    그 검증은 "판정하지 못했다" 로 남는다.
    """
    from deck.combo_policy import (
        ORCUST_HARP_HORROR_HAND,
        ORCUST_HARP_HORROR_LINE,
        ORCUST_VERIFICATION_RECIPE,
    )
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    assert ORCUST_HARP_HORROR_LINE.recipe_ydk == ORCUST_VERIFICATION_RECIPE
    assert ORCUST_HARP_HORROR_LINE.reproduction_ready is True
    parsed = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository)
    assert parsed.draft is not None
    assert parsed.draft.main_count == 40
    assert parsed.draft.extra_count == 6

    copies = {slot.card_id: slot.copies for slot in parsed.draft.main}
    #: 🔴 **디베르가 이미 x3 들어 있다** — 그래서 새 레시피를 만들지 않았다.
    assert copies.get(DIBER) == 3
    #: 디베르 ① 이 덱에서 꺼낼 「오르페골」 몬스터도 들어 있다.
    assert copies.get(SKELETON) == 3
    assert copies.get(CANNONE) == 3
    #: 🔴 **시작 패의 다섯 장이 전부 그 레시피 안에 있고 매수를 넘지 않는다.**
    assert len(ORCUST_HARP_HORROR_HAND) == 5
    for card_id in ORCUST_HARP_HORROR_HAND:
        assert copies.get(card_id, 0) >= ORCUST_HARP_HORROR_HAND.count(card_id)
    #: 🔴 **「성장」 과 「바벨」 은 패에 없다** — 경로가 갈리는 자리다.
    assert 93920420 not in ORCUST_HARP_HORROR_HAND
    assert BABEL not in ORCUST_HARP_HORROR_HAND

    setup = build_opening(repository, parsed.draft, list(ORCUST_HARP_HORROR_HAND))
    assert setup.can_run, setup.blockers
    #: 🔴 **금지 · 제한은 판정하지 못한다** — 그래서 대회 합법이라고 적지
    #: 않는다. 그 사실이 입력 검증의 "알 수 없는 것" 에 남아 있어야 한다.
    unknowns = " ".join(getattr(setup, "unknowns", ()) or ())
    assert "금지" in unknowns or "리미트" in unknowns, unknowns


@pytest.mark.real_card
def test_f03_the_general_search_finds_it_and_the_rerun_verifies(repository):
    """
    🔴 **탐색기에 수순을 적지 않았다.** 목표 판정은 ``FieldGoal`` 하나이고
    후보는 엔진이 허가한 것뿐이다 — 그래서 이 시험이 재는 것은 "등재가 탐색
    경로까지 닿았는가" 다.

    🔴 **직접 제출한 경로(``test_f01``) 와 다른 질문이다.** 저쪽은 적어 둔
    순서를 그대로 밟고, 이쪽은 **엔진이 스스로 찾는다.**

    재생은 같은 입력에서 **다시 조립한** 초기 상태에서 돈다.
    """
    from agent.bounded_search import (
        BoundedSearch,
        FieldGoal,
        SearchBudget,
        rerun_steps,
    )
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_HARP_HORROR_LINE as line
    from deck.opening import build_opening
    from deck.recipe import parse_recipe

    def _fresh():
        parsed = parse_recipe(line.recipe_ydk, repository)
        chooser, triggers = opening_wiring(repository, None)
        setup = build_opening(
            repository,
            parsed.draft,
            list(line.hand),
            chooser=chooser,
            triggers=triggers,
        )
        assert setup.can_run, setup.blockers
        return setup.duel

    duel = _fresh()
    before = duel.state.state_hash()
    search = BoundedSearch(
        goal=FieldGoal(GALATEA, P0),
        budget=SearchBudget(max_depth=6, max_nodes=60),
    )
    outcome = search.run(duel)
    assert outcome.reached is True, outcome.goal_reason
    #: 🔴 탐색은 원본을 밟지 않는다.
    assert duel.state.state_hash() == before
    #: 경로에 링크 소환이 들어 있다.
    assert any(step.kind == PlayerActionKind.LINK_SUMMON.value for step in outcome.path)

    #: 🔴 **경로에 묘지에서 자신을 제외하는 등재 효과가 들어 있다.**
    #:
    #: 🔴 **Phase 6-AQ 에서 이 단언이 좁아졌다.** 6-AO 때 이 자리는
    #: ``assert DIBER in chosen`` 이었고 **그때 사실이었다** — 그 시점에
    #: 묘지에서 발동하는 등재 효과가 디베르 ① 하나뿐이었으므로, 목표에
    #: 닿는 경로도 그것을 쓰는 것뿐이었다.
    #:
    #: 6-AQ 가 스켈레촌 ①(``21441617:e[0]``) 을 등재하자 탐색기가 **더
    #: 먼저 닿는 다른 경로**를 찾는다 (실측): 기르수 일반 소환 → 기르수 ①
    #: 로 **스켈레촌**을 묘지로 → 기르수 ③ 토큰 → 갈라테아i 링크 →
    #: 스켈레촌 ① 로 묘지의 기르수 소생 → 갈라테아 링크. 기르수 ① 의
    #: 기준점(``FirstPermittedChoice``)이 집는 것은 패스코드가 더 작은
    #: 21441617 이고, 6-AO 시점에는 그 분기가 목표에 닿지 못해 탐색이
    #: 디베르 분기까지 갔던 것이다.
    #:
    #: 🔴 **탐색기에 수순을 적지 않았으므로 그것을 고정하지 않는다.** 재는
    #: 것은 "등재가 탐색 경로까지 닿았는가" 이고, 둘 중 어느 쪽이 먼저
    #: 닿는지는 예산 · 기준점이 정한다.
    grave_effects = {
        tuple(step.action_key[4])
        for step in outcome.path
        if step.kind == PlayerActionKind.ACTIVATE_EFFECT.value
        and step.action_key[4] is not None
    }
    assert grave_effects & {(DIBER, 0), (SKELETON, 0)}, outcome.describe_ko()
    #: 🔴 그리고 **지금 실제로 집히는 것**은 스켈레촌 ① 이다 (6-AQ 실측).
    assert (SKELETON, 0) in grave_effects, outcome.describe_ko()

    rerun = rerun_steps(
        _fresh(),
        outcome.path,
        FieldGoal(GALATEA, P0),
        expect_field=outcome.final_field,
        expect_hash=outcome.final_state_hash,
    )
    assert rerun.ok is True, rerun.describe_ko()
    assert rerun.goal_reached is True
    assert rerun.matches_search is True


# ======================================================================
# G. 격리와 일치
# ======================================================================
@pytest.mark.real_card
def test_g01_a_fork_pays_the_cost_without_touching_the_original(repository):
    """
    🔴 **한 분기가 치른 비용이 다른 분기를 오염시키지 않는다.** 탐색이 밟는
    길이 이것이므로, 여기서 새는 것이 있으면 탐색이 진짜 판을 바꾼다.
    """
    from agent.simulation import Simulator

    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    duel.advance()
    before = _snapshot(duel)

    fork = Simulator(duel).fork()
    fork.advance()
    action = next(
        a
        for a in fork.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == DIBER_EFFECT
    )
    assert fork.apply(action).accepted is True
    settle_chain(fork)

    #: 사본에서는 전부 일어났다.
    assert [c.card_id for c in fork.state.zone(P0, Zone.REMOVED)] == [DIBER]
    assert len(fork.state.summon_limits.active(fork.state.turn.turn_number, P0)) == 1
    #: 🔴 원본은 한 칸도 바뀌지 않았다 — 제한도 없다.
    assert _snapshot(duel) == before
    assert _limits(duel) == ()


@pytest.mark.real_card
def test_g02_two_forks_do_not_share_the_limit(repository):
    """
    🔴 **분기 간 격리.** 한 분기가 걸어 둔 제한이 다른 분기에 보이면, 그
    분기에서는 발동하지도 않은 효과의 제약이 소환을 막는다.
    """
    from agent.simulation import Simulator

    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    duel.advance()
    left = Simulator(duel).fork()
    right = Simulator(duel).fork()
    left.advance()
    action = next(
        a
        for a in left.legal_actions(P0).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
        and a.effect_ref == DIBER_EFFECT
    )
    left.apply(action)
    settle_chain(left)

    turn = duel.state.turn.turn_number
    assert len(left.state.summon_limits.active(turn, P0)) == 1
    assert right.state.summon_limits.active(turn, P0) == ()
    assert duel.state.summon_limits.active(turn, P0) == ()


@pytest.mark.real_card
def test_g03_a_hand_built_action_gets_the_same_checks(repository):
    """
    🔴 **후보 목록을 지나지 않은 길에 우회가 없다.** 손으로 조립한
    ``PlayerAction`` 을 ``apply`` 에 넣고, 거절이 판을 바꾸지 않는지 본다.

    여기서는 **발동 자리가 틀린** 행동을 넣는다 (패의 디베르).
    """
    duel, _f, _g, _e, hand = _board(
        repository, mine=(GIRSU,), deck=(SKELETON,), hand=(DIBER,)
    )
    duel.advance()
    before = _snapshot(duel)
    action = PlayerAction.activate_effect(
        actor=P0, source=hand[0], effect_ref=DIBER_EFFECT
    )
    step = duel.apply(action)
    assert step.accepted is False
    assert step.code is ValidationCode.SOURCE_WRONG_ZONE
    assert _snapshot(duel) == before


@pytest.mark.real_card
def test_g04_the_gate_and_the_candidate_list_agree(repository):
    """
    🔴 **후보 생성과 관문이 같은 답을 낸다.** 같은 판에서 디베르 ① 이 후보로
    오르는지와 관문이 허가하는지를 **네 판**에서 나란히 본다 — 갈리면 "목록에
    없으니 안전하다" 가 거짓이 된다.
    """
    boards = (
        ("정상", dict(mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,))),
        ("후보 없음", dict(mine=(GIRSU,), grave=(DIBER,), deck=(DIBER,))),
        (
            "빈 칸 없음",
            dict(
                mine=(GIRSU, GIRSU, GIRSU, GIRSU, GIRSU),
                grave=(DIBER,),
                deck=(SKELETON,),
            ),
        ),
        ("덱에 오르페골 없음", dict(mine=(GIRSU,), grave=(DIBER,), deck=())),
    )
    for label, setup in boards:
        duel, _f, grave, _e, _h = _board(repository, **setup)
        offered = _diber_offer(duel, grave[0]) is not None
        action = PlayerAction.activate_effect(
            actor=P0, source=grave[0], effect_ref=DIBER_EFFECT
        )
        gate = duel._activation_gate(
            action, validator=duel.activation_validator(P0), selections=()
        )
        permitted = gate.validity is ActionValidity.VALID
        assert offered == permitted, f"{label}: 목록 {offered} · 관문 {permitted}"
        #: 그리고 거절된 판에서는 ``apply`` 도 거절한다.
        if not permitted:
            before = _snapshot(duel)
            assert duel.apply(action).accepted is False
            assert _snapshot(duel) == before


# ======================================================================
# H. 후보 0장과 빈 칸 없음을 **가른다** (Phase 6-AO 후속)
# ======================================================================
#: 🔴 **이 절의 판은 전부 "준비된 판" 이다.** 발동과 해결 사이의 카드 이동 ·
#: 카드 놓기는 **시험이 손으로 만든 조작**이고, 그 자리를 실제 등재된 상대
#: 카드로 만들 수단이 이 저장소에 없다 (상대 방해는 범위 밖이다). 각
#: 시험이 그 사실을 자기 docstring 에 적는다.
#:
#: 재는 것은 ``c57835716.lua`` 의 ``s.spop`` 제어 흐름 **한 가지**다::
#:
#:     if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end   -- (A)
#:     local g=Duel.SelectMatchingCard(...)
#:     if #g>0 then Duel.SpecialSummon(g,...) end                        -- (B)
#:     local e1=...; Duel.RegisterEffect(e1,tp)                          -- (B 밖)
#:
#: (A) 는 ``RegisterEffect`` **앞**이라 효과 전체가 끝나고, (B) 는 소환만
#: 건너뛴다. 6-AO 는 둘을 같은 처리로 묶어 (B) 에서도 제한이 빠졌다.


@pytest.mark.real_card
def test_h01_the_only_deck_candidate_vanishing_still_registers_the_limit(
    repository,
):
    """
    🔴 **이 보완의 본문** (요구 ③). 해결 전에 **유일한 덱 후보가 사라지면**
    소환만 하지 않고 **어둠 속성 제한은 걸린다.**

    6-AO 의 실측 (결함)::

        MZONE    [69811710]        ← 소환 없음 (맞다)
        REMOVED  [57835716]        ← 비용 유지 (맞다)
        limits   ()                ← 🔴 **제한 누락 — 이것이 결함이었다**

    🔴 **발동과 해결 사이의 카드 이동은 시험이 손으로 만든 조작이다** —
    덱의 스켈레촌을 묘지로 옮긴다. 실제 등재된 상대 카드로 이 상황을
    만들었다고 주장하지 않는다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    #: 비용은 **발동 시점**에 이미 치러졌다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]

    state = duel.state
    #: 🔴 **시험용 상태 조작** — 유일한 합법 후보를 덱에서 빼낸다.
    only = [c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON][0]
    state.move(only, Zone.GRAVE, to_player=P0)
    assert [
        c.card_id
        for c in state.zone(P0, Zone.DECK)
        if c.card_id in (SKELETON, CANNONE, GIRSU)
    ] == []

    settle_chain(duel)

    #: ① 소환은 없다 — 몬스터 존은 그대로다.
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    #: ② 빈 칸은 여전히 있었다 (요구 ③ — (A) 갈래가 아니다).
    assert len(state.zone(P0, Zone.MZONE)) == 1
    #: ③ 🔴 **제한은 걸렸다.**
    active = _limits(duel)
    assert len(active) == 1, active
    assert active[0].attribute == "DARK"
    assert active[0].player == P0
    assert active[0].source_card_id == DIBER
    #: ④ 비용은 되돌아오지 않는다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    #: ⑤ 사용 기록도 그대로다 — 이 턴에 다시 쓸 수 없다.
    limit = entry_for(DIBER_EFFECT).definition.use_limit
    key = limit.key_for(P0, DIBER_EFFECT, grave[0])
    assert state.uses.count(limit.scope, key) == 1
    #: ⑥ 🔴 **허위 소환 기록이 없다** — 기록과 실제 변화가 일치한다.
    #: 조작 기록을 **종류로** 센다 (문장으로 세면 제한 설명의 "특수 소환"
    #: 이라는 낱말에 걸린다 — 실측).
    kinds = [
        record.kind.name
        for event in duel.journal
        for record in getattr(event, "applied", ())
    ]
    assert "SPECIAL_SUMMON" not in kinds, kinds
    assert "RESTRICT_SPECIAL_SUMMON" in kinds, kinds
    #: 그리고 기록이 건드린 카드에 스켈레촌이 없다.
    touched = {
        instance for event in duel.journal for instance in event.instances
    }
    assert only.instance_id not in touched, touched


@pytest.mark.real_card
def test_h02_a_full_monster_zone_at_resolution_still_registers_nothing(
    repository,
):
    """
    🔴 **(A) 갈래는 달라지지 않았다** (요구 ②). 해결 시 몬스터 존이 가득
    차면 **소환도 제한도** 없다 — ``return`` 이 ``RegisterEffect`` 앞이다.

    ``test_c04`` 와 **같은 사실**을 재지만, 이쪽은 ``test_h01`` 과 나란히
    두어 두 갈래가 **서로 다른 답**임을 한자리에서 보인다.

    🔴 발동 뒤 몬스터 존을 채우는 것은 **시험이 손으로 만든 조작**이다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True

    state = duel.state
    for index in range(1, 5):
        filler = state.create_instance(FEATHERMAN, owner=P0, zone=Zone.MZONE)
        state.move(
            filler,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
    settle_chain(duel)

    assert _zone_ids(duel, Zone.MZONE).count(SKELETON) == 0
    #: 🔴 **제한이 없다** — ``test_h01`` 과 갈리는 자리다.
    assert _limits(duel) == ()
    #: 비용과 사용 기록은 유지된다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    limit = entry_for(DIBER_EFFECT).definition.use_limit
    key = limit.key_for(P0, DIBER_EFFECT, grave[0])
    assert state.uses.count(limit.scope, key) == 1
    #: 덱의 스켈레촌은 그대로 남아 있다 — 고르지도 않았다.
    assert SKELETON in _zone_ids(duel, Zone.DECK)


@pytest.mark.real_card
def test_h03_a_candidate_that_became_ineligible_also_registers_the_limit(
    repository,
):
    """
    🔴 **후보가 남아 있는데 확정적으로 부적격이 된 경우** (요구 ④).

    후보를 없애지 않고 **엔진이 확정 거부로 답하는 기존 수단**으로 만든다 —
    상대 필드의 「파슬 다이너 파키세팔로」(42009836) 다. 그 카드는 손으로
    읽은 금지 표에 ``prohibits=True`` 로 있고
    (:data:`~engine.summon_restriction.SPECIAL_SUMMON_PROHIBITIONS`),
    해결 중 후보 관문(``may_be_special_summoned``)이 **모든 후보에 대해
    ``FALSE``** 를 답한다. 공식 ``s.filter`` 의
    ``IsCanBeSpecialSummoned`` 가 하는 일이 바로 그것이다.

    🔴 **발동 뒤에 놓는다** — 디베르 ① 의 발동 조건에
    ``SpecialSummonPermitted`` 가 있어서 그 카드가 먼저 있으면 발동 자체가
    거절된다 (``test_b03`` 과 같은 자리). 그래서 이 상태 변화도 **시험이
    손으로 만든 조작**이다.

    🔴 **모름이 아니다.** 후보는 덱에 그대로 있고, 판정은 ``FALSE`` 이며,
    그래서 "합법 후보 0장" 이다 — 그때도 제한은 걸린다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON, CANNONE)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True

    state = duel.state
    #: 🔴 **시험용 상태 조작** — 상대 필드에 파키세팔로를 놓는다.
    pachy = state.create_instance(PACHYCEPHALO, owner=P1, zone=Zone.MZONE)
    state.move(
        pachy,
        Zone.MZONE,
        to_player=P1,
        index=0,
        position=Position.FACEUP_ATTACK,
    )
    settle_chain(duel)

    #: ① 후보는 **덱에 그대로 있다** — 사라져서가 아니라 부적격이다.
    assert SKELETON in _zone_ids(duel, Zone.DECK)
    assert CANNONE in _zone_ids(duel, Zone.DECK)
    #: ② 소환은 없다.
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    #: ③ 🔴 **제한은 걸렸다.**
    assert len(_limits(duel)) == 1
    assert _limits(duel)[0].attribute == "DARK"
    #: ④ 비용과 사용 기록은 유지된다.
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    limit = entry_for(DIBER_EFFECT).definition.use_limit
    key = limit.key_for(P0, DIBER_EFFECT, grave[0])
    assert state.uses.count(limit.scope, key) == 1
    #: ⑤ 그 판정이 **확정 거부**였다는 것을 같은 관문에 직접 물어 확인한다.
    #: 🔴 해결기가 쓰는 것과 **같은 관측**을 만든다 — 덱은 가린 자리이므로
    #: 효과가 선언한 ``looked_at`` 을 열지 않으면 관문의 답이 "보이지
    #: 않는다" 가 된다 (실측).
    spec = entry_for(DIBER_EFFECT).definition.targets[0].spec
    granted = GameStateView.from_state(
        state, viewer=P0, looked_at=spec.looked_at_zones()
    )
    ruling = BoardRuling(granted, OPERATION_RULINGS)
    candidate = [
        c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON
    ][0]
    told = ruling.explain_special_summon(candidate.instance_id)
    assert told.answer is ConditionResult.FALSE, told.reason
    assert str(PACHYCEPHALO) in told.reason


@pytest.mark.real_card
def test_h04_an_undetermined_candidate_is_not_absorbed_as_an_empty_pool(
    repository,
):
    """
    🔴 **모름을 "후보 0장" 으로 접지 않는다** (요구 ⑤).

    해결 전에 합법 후보를 빼고, 그 자리에 **특수 소환 가능 여부를 읽지
    않은** 「오르페골」 몬스터만 남긴다 — 「오르페골 트로이메어」(4055337)
    는 :data:`~engine.effect.library.OPERATION_RULINGS` 에 없다.

    그때 답은 ``UNCHECKED_RULES`` 이고 **제한도 걸리지 않는다** — 생략의
    근거가 "전부 확인했고 0장이다" 인데 그 전제가 거짓이기 때문이다.

    🔴 발동과 해결 사이의 카드 이동은 **시험이 손으로 만든 조작**이다.
    """
    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON, UNREAD_ORCUST)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True

    state = duel.state
    #: 🔴 **시험용 상태 조작** — 읽은 후보만 빼낸다. 읽지 않은 후보는 남는다.
    only = [c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON][0]
    state.move(only, Zone.GRAVE, to_player=P0)
    assert UNREAD_ORCUST in _zone_ids(duel, Zone.DECK)

    before = _snapshot(duel)
    settle_chain(duel)

    #: ① 소환도 제한도 없다 — **모름은 생략이 아니다.**
    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    assert _limits(duel) == ()
    #: ② 비용과 사용 기록은 유지된다 (발동은 성립했다).
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    limit = entry_for(DIBER_EFFECT).definition.use_limit
    key = limit.key_for(P0, DIBER_EFFECT, grave[0])
    assert state.uses.count(limit.scope, key) == 1
    #: ③ 🔴 **판은 그 밖에서 한 글자도 바뀌지 않았다** (섞기만 뺀다 —
    #: 덱을 들여다보지도 못했다).
    assert _snapshot(duel) == before
    #: ④ 그 카드가 **정말 읽지 않은 카드**임을 등록소에 직접 묻는다.
    assert UNREAD_ORCUST not in OPERATION_RULINGS.card_ids


@pytest.mark.real_card
def test_h05_a_policy_pick_outside_the_pool_is_still_refused(repository):
    """
    🔴 **후보 밖 선택도 이 보완에 흡수되지 않는다** (요구 ⑤).

    합법 후보가 있는데 정책이 후보 밖 카드를 고르면 그대로 거절이고, 제한도
    걸리지 않는다 — ``test_d03`` 과 같은 사실을 **이 보완 뒤에** 다시 잰다
    (그 자리가 "후보 0장" 쪽으로 새지 않는지가 요점이다).
    """
    probe, _f0, _g0, _e0, _h0 = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    outsider = [
        c for c in probe.state.zone(P0, Zone.DECK) if c.card_id == FEATHERMAN
    ][0]
    duel, _f, grave, _e, _h = _board(
        repository,
        mine=(GIRSU,),
        grave=(DIBER,),
        deck=(SKELETON,),
        chooser=_PickExactly((outsider.instance_id,)),
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    settle_chain(duel)

    assert _zone_ids(duel, Zone.MZONE) == [GIRSU]
    assert _limits(duel) == ()
    assert _zone_ids(duel, Zone.REMOVED) == [DIBER]
    #: 합법 후보는 덱에 그대로 있다 — "0장이어서" 가 아니다.
    assert SKELETON in _zone_ids(duel, Zone.DECK)


@pytest.mark.real_card
def test_h06_the_limit_from_an_empty_pool_binds_the_later_summons(repository):
    """
    🔴 **소환 없이 걸린 제한도 실제 후속 판정에 작용한다** (요구 ⑥).

    ``test_h01`` 의 자리에서 공용 관문에 물으면 어둠 아닌 카드는 ``FALSE``,
    어둠은 ``TRUE`` 이고, 상대에게는 걸리지 않고 다음 턴에는 만료된다.
    """
    duel, _f, grave, _e, _h = _board(
        repository,
        mine=(GIRSU,),
        grave=(DIBER,),
        deck=(SKELETON,),
        hand=(FEATHERMAN, GIRSU),
        turn_number=3,
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True
    state = duel.state
    only = [c for c in state.zone(P0, Zone.DECK) if c.card_id == SKELETON][0]
    state.move(only, Zone.GRAVE, to_player=P0)   # 🔴 시험용 상태 조작
    settle_chain(duel)
    assert len(_limits(duel)) == 1

    ruling = BoardRuling(duel.view(P0), OPERATION_RULINGS)
    hand = {c.card_id: c.instance_id for c in state.zone(P0, Zone.HAND)}
    wind = ruling.explain_special_summon(hand[FEATHERMAN])
    assert wind.answer is ConditionResult.FALSE
    assert "DARK" in wind.reason
    assert str(DIBER) in wind.reason
    dark = ruling.explain_special_summon(hand[GIRSU])
    assert dark.answer is ConditionResult.TRUE, dark.reason
    #: 자신에게만 · 이 턴만.
    assert state.summon_limits.active(3, P1) == ()
    assert state.summon_limits.active(4, P0) == ()


@pytest.mark.real_card
def test_h07_two_forks_do_not_share_the_limit_from_an_empty_pool(repository):
    """
    🔴 **분기 격리** (요구 ⑥). ``test_h01`` 의 해결을 사본에서만 수행하면
    제한은 **그 사본에만** 생긴다.
    """
    from agent.simulation import Simulator

    duel, _f, grave, _e, _h = _board(
        repository, mine=(GIRSU,), grave=(DIBER,), deck=(SKELETON,)
    )
    action = _diber_offer(duel, grave[0])
    assert action is not None
    assert duel.apply(action).accepted is True

    fork = Simulator(duel=duel)._fork()
    other = Simulator(duel=duel)._fork()
    only = [
        c for c in fork.state.zone(P0, Zone.DECK) if c.card_id == SKELETON
    ][0]
    fork.state.move(only, Zone.GRAVE, to_player=P0)   # 🔴 시험용 상태 조작
    settle_chain(fork)

    assert len(fork.state.summon_limits.active(3, P0)) == 1
    #: 🔴 **원본과 다른 사본에는 없다.**
    assert duel.state.summon_limits.active(3, P0) == ()
    assert other.state.summon_limits.active(3, P0) == ()
    #: 해시도 갈린다.
    assert fork.state.state_hash() != other.state.state_hash()


def test_h08_the_scope_is_declared_not_assumed():
    """
    🔴 **일괄 완화가 아니다.** 생략의 범위는 **선언**이고, 선언하지 않은
    효과는 예전 뜻 그대로다.

    실측으로 센다 — 등재된 모든 효과의 ``no_candidate_scope`` 를 본다.
    """
    from engine.effect.definition import NoCandidateScope, ResolutionSkip

    #: 기본값이 **전체 생략**이다 — 적지 않으면 6-AO 까지와 같다.
    assert ResolutionSkip(
        when_no_candidate=True, basis="시험용"
    ).no_candidate_scope is NoCandidateScope.WHOLE_EFFECT

    #: 범위만 적고 조건을 적지 않으면 **만들어지지 않는다.**
    with pytest.raises(ValueError):
        ResolutionSkip(
            when_condition_false=True,
            no_candidate_scope=NoCandidateScope.TARGET_OPERATIONS,
            basis="시험용",
        )

    #: 🔴 **범위를 선언한 효과가 디베르 ① 하나뿐이다.**
    narrowed = {
        str(entry.definition.effect_ref): entry.definition.resolution_skip
        for entry in EFFECT_LIBRARY
        if entry.definition.resolution_skip is not None
        and entry.definition.resolution_skip.no_candidate_scope
        is NoCandidateScope.TARGET_OPERATIONS
    }
    assert list(narrowed) == [str(DIBER_EFFECT)], narrowed
    #: 그리고 그 선언의 근거가 ``if #g>0`` 밖의 ``RegisterEffect`` 를 가리킨다.
    basis = narrowed[str(DIBER_EFFECT)].basis
    assert "RegisterEffect" in basis
    assert "if #g>0" in basis

    #: 🔴 **다른 선언들은 전부 전체 생략이다** — 성유물－『성장』 ② ·
    #: 기르수 ③ 의 뜻이 한 글자도 달라지지 않았다.
    #:
    #: 🔴 **Phase 6-AQ 에서 선언 하나가 늘었다** (스켈레촌 ① ·
    #: ``21441617:e[0]``). 그쪽은 ``when_no_candidate`` 를 **적지 않고**
    #: ``when_target_unusable`` 만 적으므로 "후보가 없을 때의 범위" 는
    #: 기본값 그대로다. 🔴 **이전 수가 틀렸던 것이 아니다**: 6-AO 후속
    #: 시점에 ``resolution_skip`` 을 적은 효과가 셋뿐이었다.
    others = {
        str(entry.definition.effect_ref)
        for entry in EFFECT_LIBRARY
        if entry.definition.resolution_skip is not None
        and str(entry.definition.effect_ref) != str(DIBER_EFFECT)
    }
    assert others == {
        "69811710:e[2]",
        "93920420:e[1]",
        "21441617:e[0]",
    }, others
    for entry in EFFECT_LIBRARY:
        skip = entry.definition.resolution_skip
        if skip is None or str(entry.definition.effect_ref) == str(DIBER_EFFECT):
            continue
        assert skip.no_candidate_scope is NoCandidateScope.WHOLE_EFFECT

    #: 🔴 **``resolution_skip`` 을 적은 효과 전부의 census** (6-AQ 에서 넷).
    declared = {
        str(entry.definition.effect_ref): (
            entry.definition.resolution_skip.when_condition_false,
            entry.definition.resolution_skip.when_no_candidate,
            entry.definition.resolution_skip.no_candidate_scope.value,
            entry.definition.resolution_skip.when_target_unusable,
        )
        for entry in EFFECT_LIBRARY
        if entry.definition.resolution_skip is not None
    }
    assert declared == {
        "93920420:e[1]": (True, True, "whole_effect", False),
        "69811710:e[2]": (True, False, "whole_effect", False),
        str(DIBER_EFFECT): (True, True, "target_operations", False),
        #: 🔴 스켈레촌 ① 은 **대상 생략 하나만** 적는다 — 그 ``s.spop`` 에
        #: 조건 재검사도 (``GetLocationCount`` 가 없다) 고르기도 없다.
        "21441617:e[0]": (False, False, "whole_effect", True),
    }, declared


def test_h09_the_executor_names_no_card(repository):
    """
    🔴 **해결기에 디베르 카드 ID 가 없다.** 범위는 정의가 말하고, 어느 일이
    그 대상을 쓰는지는 ``Operation.target_refs`` 가 답한다.
    """
    import pathlib

    source = pathlib.Path("engine/effect/executor.py").read_text(encoding="utf-8")
    assert str(DIBER) not in source
    assert "57835716" not in source
    #: 그리고 건너뛸 일을 고르는 기준이 **선언된 대상 이름**이다.
    assert "operation.target_refs" in source
    assert "NoCandidateScope.TARGET_OPERATIONS" in source

    #: 실측 — 디베르 ① 의 두 조작 중 대상을 쓰는 것은 소환 하나다.
    operations = entry_for(DIBER_EFFECT).definition.operations
    using = [op.kind.name for op in operations if op.target_refs]
    assert using == ["SPECIAL_SUMMON"], using
    free = [op.kind.name for op in operations if not op.target_refs]
    assert free == ["RESTRICT_SPECIAL_SUMMON"], free
