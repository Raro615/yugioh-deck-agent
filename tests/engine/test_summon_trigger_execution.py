"""
Phase 6-V — **소환 성공에서 유발 효과까지의 수직 경로.**

6-U 가 기르수(69811710)의 실제 일반 소환을 열었고, 그 직후 ``entry_for`` 가
``None`` 이어서 유발 효과 후보가 하나도 나지 않았다. 이 Phase 가 그 고리를
잇는다.

    일반 소환 (6-U)
      ↓  MonsterSummoned 델타
      ↓  timing_events → TimingPoint.MONSTER_SUMMONED
      ↓  TriggerRegistry / TriggerSpec        (이미 있었다)
      ↓  EffectDefinition                      ← 6-V 가 등재했다
      ↓  TriggerEligibilityJudge 관문 5개      ← activation_zone 을 6-V 가 열었다
      ↓  TriggerChainIntegrator.plan
      ↓  EffectActivator → Chain
      ↓  ChainResolver                         ← 🔴 여기서 멈춘다 (관문)

🔴 **이 파일은 "되는 것" 과 "안 되는 것" 을 같은 비중으로 적는다.**
수준 3(덱→묘지 이동)은 **달성하지 못했고**, 멈추는 자리를 F 묶음이 테스트로
고정한다. 고정해 두지 않으면 다음 Phase 가 같은 자리를 다시 찾아야 한다.
"""

from __future__ import annotations

import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.archetype import matches_setcode
from engine.chain import Chain, ChainResolver
from engine.condition import ConditionContext
from engine.cost import Selection
from engine.effect.delta import PhaseChanged
from engine.effect.journal import EventJournal
from engine.effect.library import (
    EFFECT_LIBRARY,
    build_executor,
    definition_registry,
    entry_for,
    implementation_registry,
)
from engine.effect.operation import OperationKind
from engine.effect.target import PRIMARY_TARGET, TargetSelection
from engine.effect.targeting import TargetResolver
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.state.use_registry import LimitScope
from engine.target_bridge import target_combinations
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerStatus,
    TriggerSubject,
    timing_events,
)
from engine.trigger_chain import TriggerChainIntegrator
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import ActivationKind, Zone
from integration.trigger_registry import compiled_triggers, registry_for_view

from deck.opening import build_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

MINE = 0

#: 잭나이츠 오르페골 기르수 — 이 Phase 의 대상.
GIRSU = 69811710
#: 레알 제넥스 마그나 — 같은 ``EVENT_SUMMON_SUCCESS`` 모양의 **다른 카드**
#: (공통 구조 확인용, §5-12). 정의는 등재하지 않았다.
MAGNA = 1533292
#: 어니스트 — 6-K/6-L 이 등재한 **기동** 효과. 회귀 대조군.
HONEST = 37742478

#: 기르수 ``s.tgfilter`` 가 묻는 카드군. 🔴 **숫자를 적지 않는다** — 상수
#: 표가 해석한 값을 쓰고, 이 테스트는 그 값이 무엇인지 따로 확인한다.
ORCUST_NAMES = ("SET_ORCUST", "SET_WORLD_LEGACY")

GRANTED = ValidationResult.valid()


# ======================================================================
# 공용 도구
# ======================================================================
def _orcust_pool(repository) -> list[int]:
    """메인덱 「오르페골」/「성유물」 카드 번호들 (기르수 제외)."""
    from engine.archetype_compiler import compile_archetype_condition

    codes = tuple(code for _, code in compile_archetype_condition(ORCUST_NAMES).resolved)
    return sorted(
        card.id
        for card in repository.all_cards()
        if not card.is_extra_deck
        and card.id != GIRSU
        and any(matches_setcode(card.setcodes, code) for code in codes)
    )


def _girsu_board(
    repository,
    *,
    deck_pool: list[int] | None = None,
    hand_extra=(),
    girsu_copies: int = 3,
):
    """
    기르수가 **패에 있는** 선공 판. 6-T 의 설정기를 쓴다.

    무작위 셔플에 기대지 않는다 — 패를 지정하지 않으면 기르수가 패에
    안 들어오는 판이 나오고, 그러면 이 파일이 아무것도 재지 못한다.
    """
    pool = deck_pool if deck_pool is not None else _orcust_pool(repository)
    lines = [f"{GIRSU} x{girsu_copies}"] + [
        f"{cid} x1" for cid in pool[: 40 - girsu_copies]
    ]
    parsed = parse_recipe("\n".join(lines), repository)
    hand = [GIRSU, *list(hand_extra)]
    hand += pool[: max(0, 5 - len(hand))]
    setup = build_opening(repository, parsed.draft, hand[:5])
    assert setup.duel is not None, setup.blockers
    return setup


def _summon_girsu(duel):
    """기르수를 실제로 일반 소환하고 그 인스턴스를 돌려준다."""
    actions = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.NORMAL_SUMMON
        and duel.state.find_instance(a.source).card_id == GIRSU
    ]
    assert actions, "기르수가 일반 소환 후보에 없다 (6-U 가 열어 둔 경로다)"
    step = duel.apply(actions[0])
    assert step.accepted is True, step.reason
    placed = [c for c in duel.state.player(MINE).monster_zone if c is not None]
    assert [c.card_id for c in placed] == [GIRSU]
    return placed[0].instance_id


def _summon_events(duel) -> list[TimingEvent]:
    """기록에서 소환 시점만 골라낸다."""
    return [
        te
        for ev in duel.journal
        for te in timing_events(ev)
        if te.point is TimingPoint.MONSTER_SUMMONED
    ]


def _integrator(duel, repository):
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    return build, TriggerChainIntegrator(
        view, build.registry, definition_registry(), implementation_registry()
    )


# ======================================================================
# A. 등재 — 끊겼던 고리
# ======================================================================


@requires_official_db
def test_a01_girsu_is_now_in_the_library_and_it_is_the_first_trigger(repository):
    """
    🔴 **6-U 가 남긴 `DEFINITION_MISSING` 이 풀렸다.**

    그리고 이것이 이 목록의 **첫 유발 효과**다 — 그 전까지 등재된 17건은
    전부 기동 효과이거나 마법 · 함정의 카드 발동이었다.
    """
    entry = entry_for(EffectRef(GIRSU, 0))
    assert entry is not None
    assert entry.executable is True
    assert entry.definition.activation_kind is ActivationKind.TRIGGER
    assert entry.lua_file == "c69811710.lua"

    others = [
        e
        for e in EFFECT_LIBRARY
        if e.definition.activation_kind is ActivationKind.TRIGGER
    ]
    assert [e.effect_ref for e in others] == [EffectRef(GIRSU, 0)], (
        "유발 효과가 늘어났다면 이 테스트의 '첫 유발 효과' 주장을 고쳐야 한다"
    )


@requires_official_db
def test_a02_entry_for_needs_an_effect_ref_not_a_card_id(repository):
    """
    🔴 **6-U 가 심은 무의미한 단언을 고정해 둔다.**

    6-U 의 보고와 테스트가 ``entry_for(MAGNA) is None`` 으로 "등재가 없다" 를
    주장했는데, ``entry_for`` 는 :class:`EffectRef` 를 받는다 — 정수를 넘기면
    비교가 **언제나 거짓**이라 카드와 무관하게 ``None`` 이 나온다. 결론은
    우연히 맞았지만 그 단언은 아무것도 재지 않았다.

    그래서 여기서 **두 호출이 다른 것**임을 적어 둔다.
    """
    #: 정수는 어떤 카드든 ``None`` 이다 — 등재된 카드조차.
    assert entry_for(HONEST) is None
    assert entry_for(GIRSU) is None
    #: 올바른 호출은 등재를 실제로 구분한다.
    assert entry_for(EffectRef(HONEST, 0)) is not None
    assert entry_for(EffectRef(GIRSU, 0)) is not None
    assert entry_for(EffectRef(MAGNA, 0)) is None


@requires_official_db
def test_a03_the_definition_carries_the_lua_meaning(repository):
    """정의가 원본의 **그 줄**을 담고 있다 — 하는 일 · 후보 · 관문."""
    definition = entry_for(EffectRef(GIRSU, 0)).definition

    (operation,) = definition.operations
    assert operation.kind is OperationKind.SEND_TO_GRAVE
    #: ``c:IsAbleToGrave()`` 는 조건이 아니라 **관문**이다 (2-X 의 가름).
    assert operation.gated is True

    source = definition.targets[0].spec.choice.source
    assert source.zones == frozenset({Zone.DECK})
    #: 자신 덱만이다 (``LOCATION_DECK, 0``).
    assert source.owner.value == "controller"

    lua = (ROOT / "c69811710.lua").read_text("utf-8")
    assert "EVENT_SUMMON_SUCCESS" in lua
    assert "IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})" in lua
    assert "IsAbleToGrave" in lua
    assert "Duel.SendtoGrave" in lua


@requires_official_db
def test_a04_the_archetype_codes_come_from_the_constant_table(repository):
    """
    🔴 **카드군 코드를 손으로 적지 않았다.**

    정의가 들고 있는 코드가 상수 표가 해석한 값과 같다. 숫자를 적었다면
    상수 표가 갱신될 때 조용히 어긋난다.
    """
    from engine.archetype_compiler import compile_archetype_condition

    compiled = compile_archetype_condition(ORCUST_NAMES)
    assert compiled.unresolved == ()
    expected = tuple(code for _, code in compiled.resolved)

    require = entry_for(EffectRef(GIRSU, 0)).definition.targets[0].spec.choice.source.require
    assert require.setcodes == expected
    #: 표가 무엇을 돌려줬는지도 적어 둔다 (적어 둔 숫자를 믿지 않는다).
    assert expected == (0x11B, 0xFE)


# ======================================================================
# B. 소환 성공 사건 (§5-1 · §5-2)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_b01_girsu_is_really_normal_summoned(repository):
    """§5-1 — 실제 일반 소환. 6-U 가 열어 둔 경로를 그대로 쓴다."""
    setup = _girsu_board(repository)
    duel = setup.duel
    before = duel.view(MINE).normal_summons_used[MINE]
    hand_before = len(duel.state.player(MINE).hand)

    instance = _summon_girsu(duel)

    assert duel.view(MINE).normal_summons_used[MINE] == before + 1
    assert len(duel.state.player(MINE).hand) == hand_before - 1
    card = duel.state.find_instance(instance)
    assert card.zone is Zone.MZONE


@pytest.mark.real_card
@requires_official_db
def test_b02_the_summon_emits_one_monster_summoned_event(repository):
    """
    §5-2 — 소환 성공 **사건**이 난다.

    🔴 그 사건이 ``MonsterSummoned`` 델타를 들고 있고, 거기에 **도착지**가
    적혀 있다 — 그것이 뒤에서 발동 자리의 근거가 된다 (D 묶음).
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    instance = _summon_girsu(duel)

    events = _summon_events(duel)
    assert len(events) == 1, [e.point.value for e in events]
    event = events[0]
    assert event.actor == MINE
    assert event.delta.card == instance
    assert event.delta.from_zone is Zone.HAND
    assert event.delta.to_zone is Zone.MZONE
    assert event.delta.summon.value == "normal"


@pytest.mark.real_card
@requires_official_db
def test_b03_the_summon_itself_activates_nothing(repository):
    """
    🔴 **소환은 효과 발동이 아니다** (RULE-CHAIN-011).

    6-U §19 가 세워 둔 구분이고, 유발 효과를 이었다고 흐려지지 않는다 —
    소환 직후 체인은 **비어 있고** 기록에 효과 사건이 없다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    _summon_girsu(duel)

    assert len(duel.chain) == 0
    assert [e for e in setup.journal if e.kind.name == "EFFECT"] == []
    assert [e for e in duel.journal if e.kind.name == "EFFECT"] == []


# ======================================================================
# C. 트리거 등록과 후보 (§5-3 · §5-6)
# ======================================================================


@requires_official_db
def test_c01_the_two_registrations_are_split_by_summon_kind(repository):
    """
    기르수의 두 등록이 **다른 소환**에 반응한다 — 이 구분은 6-E 가 만든
    것이고 6-V 가 쓴다. ``e1`` 이 일반, ``e2`` 가 특수다.
    """
    specs = {
        c.spec.effect_ref.ordinal: c.spec
        for c in compiled_triggers(repository, GIRSU).compilations
        if c.is_registered
    }
    assert sorted(specs) == [0, 1]
    assert {k.value for k in specs[0].summons} == {"normal"}
    assert {k.value for k in specs[1].summons} == {"special"}
    for spec in specs.values():
        assert spec.point is TimingPoint.MONSTER_SUMMONED
        assert spec.subject is TriggerSubject.SELF
        #: 🔴 ``SetRange`` 가 없다 — D 묶음이 그래서 사건을 읽는다.
        assert spec.activates_from is None


@pytest.mark.real_card
@requires_official_db
def test_c02_the_summoned_instance_is_the_only_candidate(repository):
    """
    §5-6 — **중복 등록이 되지 않는다.**

    패에 기르수가 여러 장 있어도 후보는 **소환된 그 한 장**이다. 나머지는
    ``event_relation`` 이 "사건의 주체가 아니다" 로 거른다.
    """
    setup = _girsu_board(repository, hand_extra=[GIRSU, GIRSU])
    duel = setup.duel
    hand_girsu = [c for c in duel.state.player(MINE).hand if c.card_id == GIRSU]
    assert len(hand_girsu) >= 2, "이 테스트는 패에 기르수가 둘 이상이어야 한다"

    instance = _summon_girsu(duel)
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])

    eligible = ordering.canonical_sequence
    assert len(eligible) == 1, [e.candidate.source for e in eligible]
    assert eligible[0].candidate.source == instance
    assert eligible[0].candidate.effect_ref == EffectRef(GIRSU, 0)

    #: 나머지는 **같은 이유로** 걸러진다.
    for other in ordering.excluded:
        assert other.candidate.source != instance
        relation = next(
            g for g in other.gates if g.gate is EligibilityGate.EVENT_RELATION
        )
        assert relation.result.validity is ActionValidity.INVALID


@pytest.mark.real_card
@requires_official_db
def test_c03_the_candidate_carries_the_right_effect_ref(repository):
    """
    §5-3 — **정확한 `EffectRef`**. ``e2`` (특수 소환) 는 후보가 아니다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    _summon_girsu(duel)
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])

    refs = [e.candidate.effect_ref for e in ordering.canonical_sequence]
    assert refs == [EffectRef(GIRSU, 0)]
    assert EffectRef(GIRSU, 1) not in refs


# ======================================================================
# D. 발동 자리 — 이 Phase 가 연 관문
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_d01_all_five_gates_pass_on_the_real_summon(repository):
    """
    🔴 **이 Phase 의 핵심 측정** — 관문 다섯 개가 전부 통과한다.

    6-U 직후에는 ``activation_zone`` 과 ``execution_authority`` 가 둘 다
    ``UNKNOWN`` 이었다. 전자는 이 Phase 가 사건을 읽게 해서, 후자는 정의와
    구현을 등재해서 풀렸다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    _summon_girsu(duel)
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])

    (eligibility,) = ordering.canonical_sequence
    assert eligibility.status is TriggerStatus.ELIGIBLE
    seen = {g.gate: g.result for g in eligibility.gates}
    assert set(seen) == set(EligibilityGate)
    for gate, result in seen.items():
        assert result.validity is ActionValidity.VALID, (gate, result)
        assert result.code is ValidationCode.OK, (gate, result)


@pytest.mark.real_card
@requires_official_db
def test_d02_the_activation_zone_reason_names_the_summon_event(repository):
    """
    🔴 **근거가 추측이 아니라 사건이다.**

    이유문이 소환 사건을 가리킨다 — 나중에 누구든 "왜 MZONE 이라고 했나" 를
    그 사건에서 다시 확인할 수 있어야 한다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    _summon_girsu(duel)
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])

    (eligibility,) = ordering.canonical_sequence
    zone = next(
        g for g in eligibility.gates if g.gate is EligibilityGate.ACTIVATION_ZONE
    )
    assert "MZONE" in zone.result.reason
    assert "소환 사건" in zone.result.reason
    assert "HAND" in zone.result.reason and "MZONE" in zone.result.reason


@requires_official_db
def test_d03_a_non_summon_event_does_not_open_the_zone_gate(repository):
    """
    🔴 **열어 준 것이 소환 계열 하나다.**

    같은 등록에 소환이 **아닌** 사건을 주면 자리 관문이 그대로
    ``UNKNOWN`` 이다. 이 단언이 깨지면 이 Phase 가 SINGLE 트리거 5,204건
    전부에 ``MZONE`` 을 채운 것이 된다.
    """
    from engine.trigger import TriggerEligibilityJudge
    from engine.vocabulary import Phase as GamePhase

    setup = _girsu_board(repository)
    duel = setup.duel
    instance = _summon_girsu(duel)
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    spec = next(
        s for s in build.registry.specs if s.effect_ref == EffectRef(GIRSU, 0)
    )
    judge = TriggerEligibilityJudge(
        view, definition_registry(), implementation_registry()
    )
    phase_event = TimingEvent.from_delta(
        PhaseChanged(
            from_turn=1,
            from_player=MINE,
            from_phase=GamePhase.MAIN1,
            to_turn=1,
            to_player=MINE,
            to_phase=GamePhase.BATTLE,
        )
    )
    verdict = judge._activation_zone(
        _candidate_for(judge, build, instance), spec, phase_event
    )
    assert verdict.result.validity is ActionValidity.UNKNOWN
    assert verdict.result.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "선언되지 않았" in verdict.result.reason


def _candidate_for(judge, build, instance):
    """자리 관문만 따로 묻기 위한 최소 후보."""
    from engine.trigger import TriggerCandidate

    return TriggerCandidate(
        point=TimingPoint.MONSTER_SUMMONED,
        effect_ref=EffectRef(GIRSU, 0),
        source=instance,
        controller=MINE,
    )


@pytest.mark.real_card
@requires_official_db
def test_d04_a_summon_event_about_another_card_does_not_open_the_gate(repository):
    """
    🔴 **사건의 주체가 이 카드여야 한다.**

    다른 카드의 소환 사건으로는 자리가 열리지 않는다 — ``SELF`` 등록에서
    도착지가 "이 카드" 의 것일 때만 성립하는 추론이기 때문이다.
    """
    from engine.trigger import TriggerEligibilityJudge

    setup = _girsu_board(repository, hand_extra=[GIRSU])
    duel = setup.duel
    instance = _summon_girsu(duel)
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    spec = next(
        s for s in build.registry.specs if s.effect_ref == EffectRef(GIRSU, 0)
    )
    event = _summon_events(duel)[0]
    judge = TriggerEligibilityJudge(
        view, definition_registry(), implementation_registry()
    )

    #: 같은 사건, **다른 후보** — 패에 있는 다른 기르수를 가리킨다.
    other = next(
        c.instance_id
        for c in duel.state.player(MINE).hand
        if c.card_id == GIRSU
    )
    assert other != instance
    verdict = judge._activation_zone(
        _candidate_for(judge, build, other), spec, event
    )
    assert verdict.result.validity is ActionValidity.UNKNOWN


# ======================================================================
# E. 후보 집합 — 올바른 카드만 (§5-7 · §5-8)
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_e01_only_orcust_or_world_legacy_cards_are_candidates(repository):
    """
    §5-7 — **거짓 양성 0건.** 적법 후보 전부가 정말 그 카드군이고 덱에 있다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    instance = _summon_girsu(duel)
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))
    spec = definition.targets[0].spec

    granted = GameStateView.from_state(
        duel.state, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    context = ConditionContext(
        player=MINE, source=instance, effect_ref=definition.effect_ref
    )
    found = TargetResolver(granted).candidates(spec, context)

    deck = duel.state.player(MINE).zone(Zone.DECK)
    assert len(found.eligible) == len(deck), "이 판의 덱은 전부 후보여야 한다"

    codes = spec.choice.source.require.setcodes
    for chosen in found.eligible:
        card = duel.state.find_instance(chosen)
        assert card.zone is Zone.DECK
        definition_card = repository.get(card.card_id)
        assert any(
            matches_setcode(definition_card.setcodes, code) for code in codes
        ), (card.card_id, definition_card.name)


@pytest.mark.real_card
@requires_official_db
def test_e02_a_deck_without_a_legal_card_offers_nothing(repository):
    """
    §5-8 — **덱에 적합한 카드가 없으면 거짓 성공을 만들지 않는다.**

    후보가 0장이다. 🔴 그리고 발동 조건은 여전히 참이다 — 덱 장수만 보기
    때문이다. 그 **간격을 숨기지 않고 여기 적는다**: 조건이 참인데 고를
    것이 없는 판이 실제로 존재한다.

    🔴 **처음 이 시험은 틀렸다.** 덱을 통상 몬스터로 채웠는데 후보가 2장
    나왔고, 그 둘은 **덱에 남은 기르수**였다 — 기르수 자신이 「오르페골」
    카드다 (``setcodes`` 에 ``0x11b``). 즉 엔진이 옳았고 전제가 틀렸다.
    그래서 기르수를 **한 장만** 넣어 전부 패로 보낸다.
    """
    plain = [card.id for card in repository.all_cards()
             if not card.is_extra_deck and card.is_monster
             and "NORMAL" in card.type_names][:39]
    assert len(plain) >= 39
    #: 기르수 자신이 오르페골이라는 사실을 먼저 고정한다.
    from engine.archetype_compiler import compile_archetype_condition

    codes = tuple(
        code for _, code in compile_archetype_condition(ORCUST_NAMES).resolved
    )
    assert any(matches_setcode(repository.get(GIRSU).setcodes, c) for c in codes)

    setup = _girsu_board(
        repository, deck_pool=plain, hand_extra=[], girsu_copies=1
    )
    duel = setup.duel
    instance = _summon_girsu(duel)

    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))
    spec = definition.targets[0].spec
    granted = GameStateView.from_state(
        duel.state, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(
            player=MINE, source=instance, effect_ref=definition.effect_ref
        ),
    )
    assert found.eligible == (), [
        duel.state.find_instance(i).card_id for i in found.eligible
    ]

    #: 🔴 발동 조건은 참이다 — 덱 장수 부분만 옮겼기 때문이다.
    view = duel.view(MINE)
    assert definition.activation.evaluate(
        view, ConditionContext(player=MINE, source=instance)
    ).is_true

    #: 그래서 체인에 넣을 준비가 **되지 않는다** (고를 것이 없다).
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])
    plan = integ.plan(Chain(), ordering)
    assert plan.insertable == ()


# ======================================================================
# F. 🔴 여기서 멈춘다 — 수준 3 미달성을 테스트로 고정한다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_f01_the_plan_refuses_to_invent_a_selection(repository):
    """
    🔴 **계획이 가짜 선택을 채워 넣지 않는다.**

    관문 다섯 개가 전부 통과해도 체인 링크가 **되지 않는다** — 무엇을
    고를지 아직 아무도 말하지 않았기 때문이다. 이것이 올바른 동작이고,
    §4 가 금지한 "자동으로 첫 번째 카드를 선택해 성공 처리" 를 엔진이
    구조적으로 막는다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    _summon_girsu(duel)
    _, integ = _integrator(duel, repository)
    ordering = integ.collect_and_order(_summon_events(duel)[0])
    plan = integ.plan(Chain(), ordering)

    assert plan.needs_decision is True
    assert plan.insertable == ()
    (blocked,) = plan.blocked
    assert blocked.code is ValidationCode.TOO_FEW_SELECTED
    assert "가짜로 채워 넣지 않습니다" in blocked.reason
    assert integ.extend(Chain(), plan) == Chain()


@pytest.mark.real_card
@requires_official_db
def test_f02_the_duel_loop_never_offers_a_deck_choosing_effect(repository):
    """
    🔴 **STRUCTURAL-125 — 덱에서 고르는 효과는 ``legal_actions`` 후보가 될
    수 없다.** 이 Phase 가 만든 한계가 아니라 이미 선언된 경계다.

    ``target_bridge.target_combinations`` 가 ``looked_at`` 으로 후보를 센
    **뒤 평소 관측으로 다시 좁힌다** — ``PlayerAction`` 은 정책에게 가는
    데이터이고, 거기에 덱의 인스턴스를 적으면 정책이 후보 목록을 읽는 것만
    으로 덱 내용을 알게 된다.

    그래서 소환 뒤에도 ``activate_effect`` 가 제시되지 않는다. **이것을
    "효과가 없다" 로 읽지 않도록** 같은 자리에서 조합 수가 0 인 것까지
    함께 잰다.
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    instance = _summon_girsu(duel)
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))

    combos = target_combinations(duel.state, MINE, definition, instance)
    assert list(combos) == [], "덱 후보가 Action 에 적히면 숨은 정보가 샌다"

    offered = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "activate_effect" not in offered
    assert "end_phase" in offered


@pytest.mark.real_card
@requires_official_db
def test_f03_resolution_stops_at_the_send_to_grave_gate(repository):
    """
    🔴 **수준 3 미달성 — 첫 번째 실제 BLOCKER 를 고정한다.**

    고르는 사람이 자기 덱을 보고 한 장을 고르면 (룰북: *"If a card effect
    requires you to ... look through it"*) 발동은 **성공한다** — 체인에
    링크가 하나 쌓인다. 그런데 해결이 ``UNCHECKED_RULES`` 에서 멈춘다:
    ``Card.IsAbleToGrave`` 에 답할 수 있는 계층이 없다.

    🔴 **어리석은 매장(81439173)이 오늘 멈추는 그 자리와 같다.** 즉 6-V 가
    만든 한계가 아니라, 유발 효과를 이어 붙이자 **그 앞에 있던 벽이 드러난
    것**이다.

    그래서 덱도 묘지도 변하지 않고 기록도 비어 있다. **이것을 성공으로
    적지 않는다.**
    """
    setup = _girsu_board(repository)
    duel = setup.duel
    instance = _summon_girsu(duel)
    registry = definition_registry()
    definition = registry.definition_for(EffectRef(GIRSU, 0))
    spec = definition.targets[0].spec

    granted = GameStateView.from_state(
        duel.state, viewer=MINE, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(
            player=MINE, source=instance, effect_ref=definition.effect_ref
        ),
    )
    chosen = found.eligible[0]

    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))
    grave_before = len(duel.state.player(MINE).zone(Zone.GRAVE))

    activated = EffectActivator(registry, implementation_registry()).activate(
        duel.state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=instance, effect_ref=EffectRef(GIRSU, 0)
        ),
        (TargetSelection(PRIMARY_TARGET, Selection.of(chosen)),),
        authorization=GRANTED,
    )
    #: 발동은 된다 — 체인에 링크가 하나.
    assert activated.status.value == "activated"
    assert len(activated.chain) == 1

    journal = EventJournal()
    resolved = ChainResolver(build_executor(journal), registry).resolve_top(
        duel.state, activated.chain
    )
    #: 🔴 그리고 **해결이 관문에서 멈춘다.**
    assert resolved.result.status.name == "UNCHECKED_RULES"
    assert "IsAbleToGrave" in resolved.result.reason

    #: 판은 **하나도** 변하지 않았다.
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_before
    assert duel.state.find_instance(chosen).zone is Zone.DECK
    #: §5-11 — 기록도 비어 있다. 멈춘 해결은 사건을 적지 않는다.
    assert list(journal) == []


@requires_official_db
def test_f04_no_orcust_candidate_can_answer_the_grave_gate(repository):
    """
    🔴 **왜 그 관문이 답할 수 없는지 전수로 적는다.**

    관문은 룰북 한 줄에서 **순수 통상 몬스터**에만 답할 수 있다
    (``rulebook_facts``). 기르수의 적법 후보 중 그런 카드는 **0장**이다 —
    효과 몬스터 · 마법 · 함정뿐이다.

    그래서 이것은 "운이 나빴다" 가 아니라 **구조적**이다: 이 카드의 효과는
    조작 판정 계층이 넓어지기 전에는 해결될 수 없다.
    """
    from engine.archetype_compiler import compile_archetype_condition

    codes = tuple(
        code for _, code in compile_archetype_condition(ORCUST_NAMES).resolved
    )
    pool = [
        card
        for card in repository.all_cards()
        if not card.is_extra_deck
        and any(matches_setcode(card.setcodes, code) for code in codes)
    ]
    assert len(pool) >= 40, len(pool)

    plain_normals = [
        card
        for card in pool
        if card.is_monster and "NORMAL" in card.type_names
    ]
    assert plain_normals == [], [c.id for c in plain_normals]


@requires_official_db
def test_f05_the_once_per_turn_limit_is_recorded_as_not_claimed(repository):
    """
    §5-9 — 🔴 **1턴에 1번을 주장하지 않는다.**

    기르수의 Lua 는 ``e1:SetCountLimit(1,id)`` 를 적는다 — ``UseRegistry``
    의 ``PER_CARD_NAME`` 과 같은 축이다. 그런데 그 저장소는 횟수를 **세기만**
    하고 "몇 번까지 허용인가" 는 Phase 4 다.

    그래서 정의가 그 제약을 **들고 있지 않다.** 들고 있는 척하면 "한 번만
    발동된다" 가 거짓으로 적힌다. 대신 여기서 **그 사실을 고정한다.**
    """
    #: 원본에는 분명히 있다.
    lua = (ROOT / "c69811710.lua").read_text("utf-8")
    assert "e1:SetCountLimit(1,id)" in lua
    #: 추출도 되어 있다.
    spec = repository.get(GIRSU).script.effects[0]
    assert spec.count_limit == "1,id"
    #: 🔴 그런데 정의에는 그것을 적을 칸이 없다.
    definition = entry_for(EffectRef(GIRSU, 0)).definition
    assert not hasattr(definition, "count_limit")
    assert not hasattr(definition, "activation_limit")
    #: 세는 축은 이미 있다 — 집행 계층만 없다.
    assert LimitScope.PER_CARD_NAME.value


# ======================================================================
# G. 공통 구조 — 기르수 전용이 아니다 (§5-12)
# ======================================================================


@requires_official_db
def test_g01_the_zone_gate_fix_is_not_about_girsu(repository):
    """
    §5-12 — **다른 카드로도 같은 구조가 성립한다.**

    🔴 **처음 이 시험은 마그나(1533292)를 썼고 틀렸다** — 마그나의 등록은
    ``activates_from={MZONE}`` 이다 (``SetRange`` 를 적는다). 그래서 애초에
    이 Phase 가 연 자리가 아니다.

    같은 모양(``SINGLE`` · ``EVENT_SUMMON_SUCCESS`` · ``SetRange`` 없음)의
    카드를 **코퍼스에서 찾아** 그 등록도 같은 축에 놓이는지 확인한다. 정의는
    등재하지 않았으므로 실행은 안 된다 — 확인하는 것은 **자리 축이 카드별
    분기가 아니라는 것** 하나다.
    """
    #: 마그나는 범위를 적는다 — 반례로 함께 고정한다.
    magna = {
        c.spec.effect_ref.ordinal: c.spec
        for c in compiled_triggers(repository, MAGNA).compilations
        if c.is_registered
    }
    assert magna
    assert magna[min(magna)].activates_from == frozenset({Zone.MZONE})

    #: 같은 모양의 다른 카드들을 데이터에서 고른다.
    same_shape = []
    for card in repository.all_cards():
        script = card.script
        if script is None or card.id == GIRSU:
            continue
        for spec in script.effects:
            types = set(spec.effect_types)
            if (
                "TRIGGER_O" in types
                and "SINGLE" in types
                and spec.code == "EVENT_SUMMON_SUCCESS"
                and not spec.ranges
            ):
                same_shape.append(card.id)
                break
        if len(same_shape) >= 20:
            break
    assert len(same_shape) >= 20, len(same_shape)

    opened = 0
    for card_id in same_shape:
        for compilation in compiled_triggers(repository, card_id).compilations:
            if not compilation.is_registered:
                continue
            spec = compilation.spec
            if spec.point is not TimingPoint.MONSTER_SUMMONED:
                continue
            if spec.subject is TriggerSubject.SELF and spec.activates_from is None:
                opened += 1
    #: 🔴 기르수 **혼자가 아니다** — 같은 근거로 열릴 등록이 여럿이다.
    assert opened >= 20, opened
    #: 그래도 정의가 없으면 실행되지 않는다 (ADR-006).
    assert entry_for(EffectRef(MAGNA, 0)) is None


@requires_official_db
def test_g02_the_production_code_has_no_card_id(repository):
    """
    🔴 **§3 금지 — 기르수 ID 기반 프로덕션 하드코딩이 없다.**

    고친 엔진 파일에 **카드 번호**가 한 개도 없다. 번호가 적히는 자리는
    ``EFFECT_LIBRARY`` 하나이고, 그것이 이 저장소가 정해 둔 자리다.

    🔴 **카드 이름은 검사하지 않는다.** ``engine/trigger.py`` 에는 6-E 가
    적어 둔 측정 설명에 「기르수」 가 이미 한 번 나온다 (이 Phase 전부터
    있었다). 설명에서 실측 사례를 이름으로 부르는 것은 하드코딩이 아니고,
    그것까지 금지하면 근거를 적지 못하게 된다. 금지되는 것은 **분기**다.
    """
    trigger_source = (ROOT / "engine" / "trigger.py").read_text("utf-8")
    assert str(GIRSU) not in trigger_source
    assert "ORCUST" not in trigger_source
    assert "SET_" not in trigger_source
    #: 이 Phase 가 더한 판정 함수에 카드별 분기가 없다.
    head = trigger_source.index("def _zone_from_summon_event")
    body = trigger_source[head : trigger_source.index("def _trigger_condition", head)]
    assert "card_id" not in body
    assert str(GIRSU) not in body
