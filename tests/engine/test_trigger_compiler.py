"""
Phase 6-E — 트리거 등록 정보를 시점으로 옮기고, 실제 사건에서 후보를 모은다.

    analysis 가 읽어 둔 등록      ["SINGLE","TRIGGER_O"] · "EVENT_SUMMON_SUCCESS"
          ↓  compile_trigger_spec
    TriggerSpec(MONSTER_SUMMONED, summons={NORMAL})
          ↓  TriggerRegistry.register
    실제 듀얼 → journal → EventPipeline.collect
          ↓
    TriggerCandidate (status=UNKNOWN · RULE_NOT_IMPLEMENTED)

지키는 것 다섯
--------------
1. **옮길 수 있는 사건만 옮긴다.** 엔진이 만들어 내지 못하는 사건에 시점
   이름을 붙이지 않는다.
2. **일반 소환과 특수 소환을 가른다.** 둘은 Lua 에서 다른 사건이고, 합치면
   "일반 소환했을 때" 카드가 특수 소환에도 후보가 된다.
3. 🔴 **후보를 발동 가능으로 승격하지 않는다.** "누구의 사건인가" 를 아직
   판정할 수 없으므로 어떤 후보도 ``ELIGIBLE`` 이 되지 않는다.
4. **실제 사건이 없으면 후보가 없다.**
5. **기존 듀얼 결과와 EventJournal 기록이 바뀌지 않는다.**
"""

import ast
import collections
import pathlib

import pytest

from engine.duel import Duel
from engine.effect.delta import MonsterSummoned, SummonKind, ZoneMoved
from engine.effect.library import definition_registry
from engine.effect.operation import OperationKind
from engine.event_pipeline import EventPipeline
from engine.ids import EffectRef, InstanceId
from engine.trigger import (
    TimingPoint,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerStatus,
    TriggerWording,
    timing_for,
)
from engine.trigger_compiler import (
    EVENT_SUBJECT_RULE,
    EVENT_TIMING,
    TRIGGER_DECLARATION_TYPES,
    TriggerCompilation,
    TriggerCompilationStatus,
    compile_trigger_spec,
)
from engine.validation import ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1

#: 잭나이츠 오르페골 기르수 — ``SINGLE+TRIGGER_O`` 블록 둘이
#: ``EVENT_SUMMON_SUCCESS`` 와 ``EVENT_SPSUMMON_SUCCESS`` 로 갈린다.
GIRSU = 69811710
#: 엘리멘틀 히어로 페더맨 — 레벨 3 통상 몬스터. **실제로 일반 소환된다.**
FEATHERMAN = 21844576
#: 어리석은 매장 — 등재·실행되는 효과. 덱 → 묘지 이동을 만든다.
FOOLISH = 81439173

COMPILED = TriggerCompilationStatus.COMPILED
UNSUPPORTED = TriggerCompilationStatus.EVENT_UNSUPPORTED
UNREAD = TriggerCompilationStatus.EVENT_UNREAD


def compile_of(card_id, ordinal, *, types, code, ranges=()):
    return compile_trigger_spec(
        EffectRef(card_id, ordinal),
        declared_types=types,
        event_code=code,
        ranges=ranges,
    )


def summon_event(kind=SummonKind.NORMAL, instance=1):
    return timing_for(
        MonsterSummoned(
            summon=kind,
            card=InstanceId(instance),
            player=MINE,
            owner=MINE,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.FACEUP_ATTACK,
        )
    )


def move_event(to_zone=Zone.GRAVE, operation=OperationKind.SEND_TO_GRAVE):
    return timing_for(
        ZoneMoved(
            movement=operation,
            card=InstanceId(2),
            source_player=MINE,
            source_zone=Zone.DECK,
            destination_player=MINE,
            destination_zone=to_zone,
        )
    )


# ======================================================================
# A. 등록 정보 추출 — 트리거인가 아닌가
# ======================================================================


def test_a_a_block_without_a_trigger_type_is_not_a_registration():
    """
    🔴 **결과 객체를 만들지 않는다.** "트리거가 아니다" 와 "트리거인데
    옮기지 못했다" 가 같은 값이 되면, 부르는 쪽이 둘을 구분할 수 없다.
    """
    assert compile_of(1, 0, types=["ACTIVATE"], code="EVENT_FREE_CHAIN") is None
    assert compile_of(1, 0, types=["IGNITION"], code=None) is None
    assert compile_of(1, 0, types=["CONTINUOUS", "FIELD"], code=None) is None
    assert compile_of(1, 0, types=[], code="EVENT_SUMMON_SUCCESS") is None


def test_a_both_trigger_flavours_are_registrations():
    assert TRIGGER_DECLARATION_TYPES == frozenset({"TRIGGER_O", "TRIGGER_F"})
    for flavour in sorted(TRIGGER_DECLARATION_TYPES):
        result = compile_of(
            1, 0, types=["SINGLE", flavour], code="EVENT_SUMMON_SUCCESS"
        )
        assert result is not None and result.is_registered


def test_a_the_suffix_is_not_read_as_mandatory_or_optional():
    """
    🔴 ``TRIGGER_O`` → 임의, ``TRIGGER_F`` → 강제 로 옮기지 **않는다.**

    Phase 3-F-26 이 그 뜻풀이를 **근거 없음**으로 기록했다. 이번 Phase 가
    공식 한국어 원문으로 다시 재 봤지만 ``TRIGGER_F`` 의 10%(45장)가
    "발동할 수 있다" 만 갖고 있어 그 판정을 뒤집지 못했다. 그래서 둘 다
    ``UNKNOWN`` 이다 — "확인되지 않았다" 를 뜻하는 값이고 그것이 사실이다.
    """
    optional = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_TO_GRAVE")
    forced = compile_of(1, 0, types=["SINGLE", "TRIGGER_F"], code="EVENT_TO_GRAVE")

    for result in (optional, forced):
        assert result.spec.requirement is TriggerRequirement.UNKNOWN
        assert result.spec.wording is TriggerWording.UNKNOWN

    # 두 선언이 **같은 모양**이다 — 접미사를 읽지 않았다는 증거다.
    assert optional.spec.canonical_state() == forced.spec.canonical_state()


# ======================================================================
# B. 사건 코드 → 시점 — 옮길 수 있는 것만
# ======================================================================


def test_b_the_mapping_is_seven_lines_and_every_point_is_producible():
    """
    옮길 수 있는 코드는 일곱 개뿐이고, 그 시점은 모두 엔진이 실제로 만들어
    내는 것이다 (아래 §F 가 실제 듀얼로 확인한다).
    """
    assert set(EVENT_TIMING) == {
        "EVENT_SUMMON_SUCCESS",
        "EVENT_SPSUMMON_SUCCESS",
        "EVENT_TO_GRAVE",
        "EVENT_TO_HAND",
        "EVENT_TO_DECK",
        "EVENT_REMOVE",
        "EVENT_DRAW",
    }
    assert {timing.point for timing in EVENT_TIMING.values()} == {
        TimingPoint.MONSTER_SUMMONED,
        TimingPoint.CARD_MOVED,
        TimingPoint.CARD_DRAWN,
    }
    # 🔴 지어낸 시점이 없다 — ``UNIMPLEMENTED`` 를 옮길 대상으로 쓰지 않는다.
    assert TimingPoint.UNIMPLEMENTED not in {
        timing.point for timing in EVENT_TIMING.values()
    }


@pytest.mark.parametrize(
    "code",
    [
        "EVENT_PHASE",
        "EVENT_DESTROYED",
        "EVENT_BATTLE_DESTROYED",
        "EVENT_ATTACK_ANNOUNCE",
        "EVENT_LEAVE_FIELD",
        "EVENT_BE_MATERIAL",
        "EVENT_CHAINING",
    ],
)
def test_b_an_event_the_engine_cannot_make_is_refused(code):
    """
    등록은 있지만 엔진이 그 사건을 만들어 내지 못한다. **"트리거가 없다" 가
    아니다** — 그래서 상태를 따로 둔다.
    """
    result = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code=code)

    assert result.status is UNSUPPORTED
    assert result.is_registered is False
    assert result.spec is None
    assert result.event_code == code
    assert code in result.reason


def test_b_event_phase_is_refused_because_the_parser_drops_the_qualifier():
    """
    🔴 가장 많은 미지원 코드(722블록)이고, **가장 솔깃한 함정**이다.

    Phase 3-E-18 이 측정했다 — ``EVENT_PHASE`` 는 단독으로 쓰인 블록이
    **0개**이고 (전부 ``+PHASE_END`` 같은 한정자가 붙는다) 파서는 첫 이름만
    남긴다. 즉 이 값은 "어느 페이즈인지 모른다" 다.
    ``PHASE_CHANGED`` 로 옮기면 엔드 페이즈 카드가 **모든** 페이즈 전환에서
    후보가 된다.
    """
    assert "EVENT_PHASE" not in EVENT_TIMING
    assert TimingPoint.PHASE_CHANGED not in {t.point for t in EVENT_TIMING.values()}


def test_b_an_unread_event_code_is_a_third_answer():
    """
    ``None`` 은 "사건이 없다" 가 아니라 "못 읽었다" 다. **실측 2블록**이고,
    둘 다 Phase 3-E-18 이 ``None`` 으로 되돌린 Clone 사례다
    (요정용 고대 4179255 · EM 스카이 매지션 73734821).
    """
    result = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code=None)

    assert result.status is UNREAD
    assert result.is_registered is False
    assert result.event_code is None
    assert "읽지 못했" in result.reason


def test_b_a_flip_trigger_is_unsupported_not_unread():
    """
    🔴 **조사 중에 내 상태 이름이 틀렸던 것을 잡았다.**

    사건 코드가 ``None`` 인 트리거 블록 71개 중 **69개가 ``FLIP``** 이고,
    그중 57개는 ``SetCode`` 를 **아예 부르지 않는다** — 뒤집혔을 때가
    유발 시점이므로 코드가 없는 것이 **정상**이다 (섀도르 비스트 3717252
    의 ``e1``: ``SetType(SINGLE+FLIP+TRIGGER_O)`` 뒤에 ``SetCode`` 가 없다).

    처음 구현은 그 69개를 "못 읽었다" 로 적었다. 그러면 "파서를 고치면
    풀린다" 로 읽히는데, 실제로는 **뒤집기 계층이 생겨야** 풀린다.
    """
    result = compile_of(1, 0, types=["SINGLE", "FLIP", "TRIGGER_O"], code=None)

    assert result.status is UNSUPPORTED
    assert result.is_registered is False
    assert "FLIP" in result.reason
    # 🔴 ``FLIP`` 과 옮길 수 있는 코드를 **함께** 가진 블록은 0개이므로
    #    이 분기가 멀쩡한 선언을 가로채지 않는다 (§I 가 전수로 센다).
    both = compile_of(
        1, 0, types=["SINGLE", "FLIP", "TRIGGER_O"], code="EVENT_TO_GRAVE"
    )
    assert both.status is COMPILED


def test_b_a_result_cannot_lie_about_what_it_carries():
    spec = TriggerSpec(EffectRef(1, 0), TimingPoint.CARD_DRAWN)
    with pytest.raises(ValueError):
        TriggerCompilation(status=COMPILED, reason="", declared_types=())
    with pytest.raises(ValueError):
        TriggerCompilation(
            status=UNSUPPORTED, reason="", declared_types=(), spec=spec
        )
    with pytest.raises(ValueError):
        TriggerCompilation(
            status=UNREAD, reason="", declared_types=(), event_code="EVENT_TO_GRAVE"
        )


# ======================================================================
# C. 🔴 일반 소환과 특수 소환을 가른다 (거짓 양성 반례)
# ======================================================================


def test_c_the_two_summon_events_compile_to_different_declarations():
    normal = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS")
    special = compile_of(
        1, 1, types=["SINGLE", "TRIGGER_O"], code="EVENT_SPSUMMON_SUCCESS"
    )

    assert normal.spec.point is special.spec.point is TimingPoint.MONSTER_SUMMONED
    assert normal.spec.summons == frozenset({SummonKind.NORMAL})
    assert special.spec.summons == frozenset({SummonKind.SPECIAL})


def test_c_a_normal_summon_declaration_does_not_match_a_special_summon():
    """
    🔴 **이 칸이 없으면 생기는 거짓 양성.** 엔진의
    ``TimingPoint.MONSTER_SUMMONED`` 는 둘을 합친 하나이므로, 구분을 적지
    않으면 "일반 소환했을 때" 카드가 특수 소환에도 후보가 된다.
    """
    normal = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS")
    special = compile_of(
        1, 1, types=["SINGLE", "TRIGGER_O"], code="EVENT_SPSUMMON_SUCCESS"
    )

    assert normal.spec.matches(summon_event(SummonKind.NORMAL)) is True
    assert normal.spec.matches(summon_event(SummonKind.SPECIAL)) is False
    assert special.spec.matches(summon_event(SummonKind.SPECIAL)) is True
    assert special.spec.matches(summon_event(SummonKind.NORMAL)) is False


def test_c_the_summon_filter_belongs_only_to_the_summon_point():
    """소환이 아닌 시점에 소환 필터를 걸 수 없다 — 범주 오류를 막는다."""
    with pytest.raises(TriggerError):
        TriggerSpec(
            EffectRef(1, 0),
            TimingPoint.CARD_MOVED,
            summons=frozenset({SummonKind.NORMAL}),
        )
    with pytest.raises(TypeError):
        TriggerSpec(
            EffectRef(1, 0),
            TimingPoint.MONSTER_SUMMONED,
            summons={SummonKind.NORMAL},  # type: ignore[arg-type]
        )


def test_c_the_summon_kind_travels_with_the_event_not_the_operation():
    """
    ``TimingEvent.summon`` 은 ``operation`` 과 **다른 표**다 —
    ``MonsterSummoned`` 가 효과의 어휘를 쓰지 않기 때문이다.
    """
    event = summon_event(SummonKind.NORMAL)
    assert event.summon is SummonKind.NORMAL
    assert event.operation is None
    assert move_event().summon is None


# ======================================================================
# D. 도착지 사건 — 의미로 좁히지 않는다
# ======================================================================


@pytest.mark.parametrize(
    "code,zone",
    [
        ("EVENT_TO_GRAVE", Zone.GRAVE),
        ("EVENT_TO_HAND", Zone.HAND),
        ("EVENT_TO_DECK", Zone.DECK),
        ("EVENT_REMOVE", Zone.REMOVED),
    ],
)
def test_d_an_arrival_event_filters_only_the_destination(code, zone):
    result = compile_of(1, 0, types=["FIELD", "TRIGGER_O"], code=code)

    assert result.spec.point is TimingPoint.CARD_MOVED
    assert result.spec.to_zones == frozenset({zone})
    # 🔴 **의미로 좁히지 않는다.** Lua 의 ``EVENT_TO_GRAVE`` 는 파괴로 갔든
    # 효과로 보내졌든 묘지에 도착하면 발화한다.
    assert result.spec.operations is None
    assert result.spec.from_zones is None


def test_d_a_grave_declaration_ignores_how_the_card_got_there():
    spec = compile_of(1, 0, types=["FIELD", "TRIGGER_O"], code="EVENT_TO_GRAVE").spec

    for operation in (
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DESTROY,
        OperationKind.DISCARD,
        OperationKind.RELEASE,
    ):
        assert spec.matches(move_event(Zone.GRAVE, operation)) is True
    assert spec.matches(move_event(Zone.HAND, OperationKind.RETURN_TO_HAND)) is False


def test_d_a_draw_is_not_an_arrival_in_the_hand():
    """
    ``EVENT_DRAW`` 와 ``EVENT_TO_HAND`` 가 겹치지 않는다 — ``ZoneMoved`` 가
    ``DRAW`` 를 아예 거부하므로 패 도착 사건에 드로우가 섞이지 않는다.
    """
    draw = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_DRAW").spec
    to_hand = compile_of(1, 1, types=["SINGLE", "TRIGGER_O"], code="EVENT_TO_HAND").spec

    assert draw.point is TimingPoint.CARD_DRAWN
    assert to_hand.point is TimingPoint.CARD_MOVED
    with pytest.raises(ValueError):
        move_event(Zone.HAND, OperationKind.DRAW)


# ======================================================================
# E. 발동 자리 — 일부만 옮기지 않는다
# ======================================================================


def test_e_declared_ranges_become_the_activation_zones():
    result = compile_of(
        1, 0, types=["FIELD", "TRIGGER_O"], code="EVENT_TO_GRAVE", ranges=["MZONE"]
    )
    assert result.spec.activates_from == frozenset({Zone.MZONE})

    both = compile_of(
        1, 0, types=["FIELD", "TRIGGER_O"], code="EVENT_TO_GRAVE",
        ranges=["GRAVE", "HAND"],
    )
    assert both.spec.activates_from == frozenset({Zone.GRAVE, Zone.HAND})


def test_e_no_declared_range_leaves_the_zone_undeclared():
    """
    ``None`` 은 "어디서든" 이 아니라 **"적지 않았다"** 다 —
    ``TriggerSpec.activates_from`` 의 설명이 그렇게 적어 두었고, 그때 관문은
    ``UNKNOWN`` 이 된다.
    """
    result = compile_of(1, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS")
    assert result.spec.activates_from is None


def test_e_one_unmappable_range_drops_them_all():
    """
    🔴 **일부만 옮기면 자리가 실제보다 좁아진다.** 좁은 자리 선언은 그 밖에
    있는 카드를 조용히 후보에서 뺀다. 그래서 하나라도 못 옮기면 전부
    적지 않는다 (관문이 ``UNKNOWN`` 이 되는 쪽이 안전하다).
    """
    result = compile_of(
        1, 0, types=["FIELD", "TRIGGER_O"], code="EVENT_TO_GRAVE",
        ranges=["MZONE", "ONFIELD"],
    )
    assert result.spec.activates_from is None
    assert result.is_registered is True


# ======================================================================
# F. 🔴 실제 사건과 연결 — 끝까지 돌려 본다
# ======================================================================


def registry_from(repository, card_ids):
    """카드 데이터에서 선언을 만들어 레지스트리를 채운다. 손으로 적지 않는다."""
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    registry = TriggerRegistry()
    compiled = []
    for card_id in card_ids:
        card = repository.get(card_id)
        if card is None or card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            result = compile_trigger_spec(
                EffectRef(card_id, ordinal),
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            if result is not None and result.is_registered:
                registry.register(result.spec)
                compiled.append(result)
    return registry, compiled


@pytest.fixture
def summoned(repository):
    """기르수를 필드에 두고 **페더맨을 실제로 일반 소환한** 판."""
    duel = Duel.start(
        repository=repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        seed=5,
    )
    duel.state.create_instance(
        GIRSU, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in duel.legal_actions(MINE) if a.kind.value == "normal_summon"
    )
    step = duel.apply(action)
    assert step.accepted, step.reason
    return duel


@requires_official_db
def test_f_a_real_summon_reaches_the_collector(repository, summoned):
    """
    🔴 **지어낸 사건이 아니다.** 실제 ``Duel.apply`` 가 만든 journal 기록을
    기존 ``EventPipeline`` 에 그대로 넘긴다 — 새 공급 경로를 만들지 않았다.
    """
    registry, _ = registry_from(repository, [GIRSU])
    pipeline = EventPipeline(summoned.view(MINE), registry, definition_registry())

    found = []
    for event in summoned.journal.events:
        for observation in pipeline.collect(event, actor=event.actor):
            found.extend(observation.candidates)

    assert len(found) == 1, [c.effect_ref for c in found]
    [candidate] = found
    assert candidate.effect_ref == EffectRef(GIRSU, 0)
    assert candidate.point is TimingPoint.MONSTER_SUMMONED


@requires_official_db
def test_f_the_special_summon_declaration_does_not_fire_on_a_normal_summon(
    repository, summoned
):
    """
    기르수는 선언이 **둘**이다 (일반 · 특수). 일반 소환 하나로 둘 다 후보가
    되면 거짓 양성이다.
    """
    registry, compiled = registry_from(repository, [GIRSU])
    assert len(compiled) == 2
    assert {tuple(sorted(s.spec.summons))[0] for s in compiled} == {
        SummonKind.NORMAL,
        SummonKind.SPECIAL,
    }

    pipeline = EventPipeline(summoned.view(MINE), registry, definition_registry())
    ordinals = {
        candidate.effect_ref.ordinal
        for event in summoned.journal.events
        for observation in pipeline.collect(event, actor=event.actor)
        for candidate in observation.candidates
    }
    assert ordinals == {0}, ordinals


@requires_official_db
def test_f_no_candidate_is_ever_promoted_to_activatable(repository, summoned):
    """
    🔴 **이 Phase 의 가장 중요한 단정 — 그리고 Phase 6-F 가 더 강하게 만든 것.**

    후보가 나왔다고 발동 가능한 것이 아니다. 실제로 이 판의 소환은
    **페더맨**의 소환이고 후보는 **기르수**의 것이다.

    .. note::
       6-E 에서 이 시험은 ``UNKNOWN`` · ``RULE_NOT_IMPLEMENTED`` 를 단정했다.
       그것이 **그때 알 수 있는 전부**였다 — "이 사건이 이 카드의 사건인가"
       를 묻는 계층이 없었으므로 모른다고 답하는 것이 정직했다.

       6-F 가 그 질문에 답한다 (``TriggerSubject.SELF``). 그래서 같은 판에서
       답이 ``INELIGIBLE`` · ``CANDIDATE_NOT_ELIGIBLE`` 로 **강해졌다** —
       "모른다" 가 아니라 **"주체가 다르다"** 다. 🔴 기존 단정이 틀린 가정을
       갖고 있던 것이 아니라, 모름이 **확정된 거부로 승격**되었다. 이 시험이
       지키려는 불변(``is_candidate is False``) 은 아래에서 그대로 지킨다.
    """
    registry, _ = registry_from(repository, [GIRSU])
    pipeline = EventPipeline(summoned.view(MINE), registry, definition_registry())

    seen = 0
    for event in summoned.journal.events:
        for observation in pipeline.collect(event, actor=event.actor):
            for candidate in observation.candidates:
                seen += 1
                #: 🔴 이 불변은 6-E 와 **한 글자도 다르지 않다.**
                assert candidate.status.is_candidate is False
                #: 그리고 까닭이 정확해졌다.
                assert candidate.status is TriggerStatus.INELIGIBLE
                assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
                #: 사건의 주체(페더맨) 와 후보의 카드(기르수) 가 **둘 다**
                #: 이유에 적힌다 — 어느 쪽이 달랐는지 읽을 수 있어야 한다.
                assert str(observation.event.instance) in candidate.reason
                assert str(candidate.source) in candidate.reason
    assert seen == 1


@requires_official_db
def test_f_the_same_holds_without_a_definition_source(repository, summoned):
    """
    🔴 **이 시험이 실제 거짓 양성을 잡았다.**

    정의 출처를 넘기지 않으면 ``TriggerCollector`` 는 "걸린 조건이 없다" 며
    ``ELIGIBLE`` 을 돌려준다. 6-E 의 처음 구현이 그랬고, 페더맨의 소환에
    기르수가 **발동 가능**으로 나왔다.

    .. note::
       6-E 는 그것을 ``EVENT_SUBJECT_RULE`` **조건**으로 막았고 판정이
       ``UNKNOWN`` 에서 멈췄다. 6-F 는 같은 사실을 **축**으로 옮겼으므로
       (:func:`~engine.trigger.subject_relation`) 조건이 없어도 막히고,
       막히는 이유가 ``INELIGIBLE`` 로 정확해졌다. 🔴 **정의 출처가 있든
       없든 같은 답이라는 이 시험의 요지는 그대로다** — 아래에서 두 경로를
       직접 비교해 그것을 단정한다.
    """
    registry, _ = registry_from(repository, [GIRSU])
    bare = EventPipeline(summoned.view(MINE), registry)  # definitions=None
    held = EventPipeline(summoned.view(MINE), registry, definition_registry())

    def verdicts(pipeline):
        out = []
        for event in summoned.journal.events:
            for observation in pipeline.collect(event, actor=event.actor):
                for candidate in observation.candidates:
                    out.append((candidate.status, candidate.code, candidate.reason))
        return out

    without, with_definitions = verdicts(bare), verdicts(held)
    assert len(without) == 1
    #: 🔴 **두 경로가 글자 하나까지 같다.** 6-E 가 이 자리에서 갈라졌고
    #: 그것이 거짓 양성이었으므로, 같다는 것을 직접 단정한다.
    assert without == with_definitions
    [(status, code, reason)] = without
    assert status is TriggerStatus.INELIGIBLE
    assert code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: ``EVENT_SUBJECT_RULE`` 은 이제 이유에 나오지 않는다 — 모르는 것이
    #: 아니라 **알아서 거부**하기 때문이다. 그 이름이 쓰이는 자리는
    #: 주체를 적지 않은 선언뿐이다 (``test_f_an_unscoped_declaration_...``).
    assert EVENT_SUBJECT_RULE not in reason


@requires_official_db
def test_f_an_unrelated_event_makes_no_candidate(repository):
    """
    시나리오 C — 등록한 사건과 **다른** 사건이 일어나면 후보가 없다.

    드로우만 일어난 판에서는 소환 선언이 아무것도 만들지 않는다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=9
    )
    duel.state.create_instance(
        GIRSU, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    registry, _ = registry_from(repository, [GIRSU])
    pipeline = EventPipeline(duel.view(MINE), registry, definition_registry())

    drawn = [
        observation
        for event in duel.journal.events
        for observation in pipeline.collect(event, actor=event.actor)
    ]
    assert all(observation.candidates == () for observation in drawn), drawn


@requires_official_db
def test_f_a_real_move_to_the_grave_reaches_the_collector(repository):
    """
    시나리오 B — 묘지 도착. 어리석은 매장을 **실제로 해결**해서 만든
    ``ZoneMoved(send_to_grave, DECK→GRAVE)`` 를 쓴다.
    """
    from tests.engine.test_real_card_coverage import bury, foolish_state

    game = foolish_state(repository)
    game.create_instance(
        GIRSU, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    target = game.player(MINE).deck[0].instance_id
    resolution = bury(game, target)

    moved = [
        timing_for(delta)
        for delta in resolution.deltas
        if type(delta).__name__ == "ZoneMoved"
    ]
    assert moved and moved[0].point is TimingPoint.CARD_MOVED
    assert moved[0].to_zone is Zone.GRAVE

    # 묘지 도착을 보는 선언은 그 사건에 반응하고, 소환 선언은 반응하지 않는다.
    grave = compile_of(1, 0, types=["FIELD", "TRIGGER_O"], code="EVENT_TO_GRAVE").spec
    summon = compile_of(
        1, 1, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS"
    ).spec
    assert grave.matches(moved[0]) is True
    assert summon.matches(moved[0]) is False


# ======================================================================
# G. 중복 · 순서 · 복수 효과
# ======================================================================


@requires_official_db
def test_g_each_event_keeps_its_own_candidates(repository, summoned):
    """
    사건별로 따로 남는다 — 합치면 어느 사건에서 나온 후보인지가 사라지고,
    나중에 순서를 정할 근거가 없어진다.
    """
    registry, _ = registry_from(repository, [GIRSU])
    pipeline = EventPipeline(summoned.view(MINE), registry, definition_registry())

    observations = [
        observation
        for event in summoned.journal.events
        for observation in pipeline.collect(event, actor=event.actor)
    ]
    assert len(observations) >= 1
    # 사건 식별자가 서로 다르다 — 같은 사건이 두 번 처리되지 않는다.
    ids = [observation.event_id for observation in observations]
    assert len(ids) == len(set(ids))


def test_g_two_effects_on_one_event_stay_two_declarations():
    """시나리오 F — 한 사건에 여러 효과가 반응하면 각각 따로 식별된다."""
    registry = TriggerRegistry()
    for ordinal in (0, 1):
        result = compile_of(
            7, ordinal, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS"
        )
        registry.register(result.spec)

    watching = registry.watching(summon_event(SummonKind.NORMAL))
    assert len(watching) == 2
    assert {spec.effect_ref.ordinal for spec in watching} == {0, 1}


def test_g_the_same_declaration_cannot_be_registered_twice():
    registry = TriggerRegistry()
    spec = compile_of(
        7, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_SUMMON_SUCCESS"
    ).spec
    registry.register(spec)
    with pytest.raises(TriggerError):
        registry.register(spec)


def test_g_compiling_twice_gives_the_same_declaration():
    first = compile_of(7, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_TO_GRAVE")
    second = compile_of(7, 0, types=["SINGLE", "TRIGGER_O"], code="EVENT_TO_GRAVE")
    assert first.canonical_state() == second.canonical_state()


# ======================================================================
# H. 기존 엔진 호환성
# ======================================================================


@requires_official_db
def test_h_collecting_candidates_does_not_touch_the_board(repository, summoned):
    registry, _ = registry_from(repository, [GIRSU])
    before = summoned.state.state_hash()
    events_before = len(summoned.journal.events)

    pipeline = EventPipeline(summoned.view(MINE), registry, definition_registry())
    for event in summoned.journal.events:
        pipeline.collect(event, actor=event.actor)

    assert summoned.state.state_hash() == before
    assert len(summoned.journal.events) == events_before


def test_h_the_compiler_never_touches_the_duel_or_the_journal():
    """
    🔴 **배선하지 않았다.** ``Duel`` 은 이 컴파일러를 모르고, 기록 계층도
    모른다 — 후보 수집은 실행이 끝난 뒤 **바깥쪽**이 하는 일이다
    (``event_pipeline`` 의 머리말이 적어 둔 그대로).
    """
    duel = pathlib.Path("engine/duel.py").read_text(encoding="utf-8")
    assert "trigger_compiler" not in duel
    assert "trigger" not in duel.lower()

    for name in ("engine/effect/journal.py", "engine/action_execution.py"):
        source = pathlib.Path(name).read_text(encoding="utf-8")
        assert "trigger_compiler" not in source


def test_h_the_compiler_borrows_nothing_from_analysis():
    """ADR-007 — Phase 6-D 와 같은 이유로 문자열과 숫자만 받는다."""
    tree = ast.parse(
        pathlib.Path("engine/trigger_compiler.py").read_text(encoding="utf-8")
    )
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not [m for m in modules if m.startswith(("analysis", "core", "sources"))]


# ======================================================================
# I. 전수 측정 — 더 많이 찾는 것이 목표가 아니다
# ======================================================================


@requires_official_db
def test_i_the_whole_corpus_splits_into_three_measured_groups(repository):
    """
    실측 (``c*.lua`` 12,968개 · 블록 26,352개).

    ::

        트리거가 아닌 블록          18,484
        트리거 등록 블록             7,868
          ↳ 옮겼다 (compiled)       4,173   카드 3,191장
          ↳ 사건 미지원              3,693   카드 3,279장
             (그중 FLIP 69)
          ↳ 사건 코드 미독               2   카드    2장

    🔴 **옮긴 수가 성공 지표가 아니다.** 아래 §J 가 같은 모집단에서
    ``ACTIVATE`` · ``IGNITION`` 이 트리거로 **잘못 분류되지 않았는지**를
    따로 센다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    counts: collections.Counter = collections.Counter()
    cards: dict = collections.defaultdict(set)
    points: collections.Counter = collections.Counter()
    zones = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            result = compile_trigger_spec(
                EffectRef(card.id, ordinal),
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            if result is None:
                counts["not_a_trigger"] += 1
                continue
            counts[result.status.value] += 1
            cards[result.status.value].add(card.id)
            if result.is_registered:
                points[result.spec.point.value] += 1
                if result.spec.activates_from is not None:
                    zones += 1

    assert counts["not_a_trigger"] == 18484
    assert counts["compiled"] == 4173
    assert counts["event_unsupported"] == 3693
    assert counts["event_unread"] == 2
    assert len(cards["compiled"]) == 3191
    assert dict(points) == {
        "monster_summoned": 2889,
        "card_moved": 1257,
        "card_drawn": 27,
    }
    assert zones == 816


# ======================================================================
# J. 🔴 잘못 분류하지 않았는가
# ======================================================================


@requires_official_db
def test_i_no_flip_trigger_ever_compiles(repository):
    """
    ``FLIP`` 트리거 블록 **69개 전부**가 옮겨지지 않는다. 하나라도 옮겨지면
    뒤집기 계층이 없는데 후보가 나온다는 뜻이다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    flips = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            if "FLIP" not in effect.effect_types:
                continue
            result = compile_trigger_spec(
                EffectRef(card.id, ordinal),
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            if result is None:
                continue
            flips += 1
            assert result.is_registered is False, (card.id, ordinal, result)
    assert flips == 69


@requires_official_db
def test_j_no_activate_or_ignition_block_became_a_trigger(repository):
    """
    §11 — 기존 ``IGNITION`` · ``ACTIVATE`` 효과가 트리거로 **바뀌지
    않았는지** 전수로 센다. 하나라도 걸리면 분류가 틀린 것이다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    offenders = []
    for card in repository.all_cards():
        if card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            kinds = set(effect.effect_types)
            if kinds & TRIGGER_DECLARATION_TYPES:
                continue
            result = compile_trigger_spec(
                EffectRef(card.id, ordinal),
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            if result is not None:
                offenders.append((card.id, ordinal, sorted(kinds)))
    assert offenders == [], offenders[:10]


@requires_official_db
def test_j_every_compiled_block_really_declared_a_trigger(repository):
    """반대 방향 — 옮긴 블록은 **전부** 트리거 타입을 실제로 갖고 있다."""
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    checked = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            result = compile_trigger_spec(
                EffectRef(card.id, ordinal),
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            if result is None:
                continue
            checked += 1
            assert TRIGGER_DECLARATION_TYPES & set(result.declared_types), result
    assert checked == 7868


def test_j_the_registry_only_takes_compiled_declarations():
    """
    🔴 옮기지 못한 등록이 레지스트리에 새어 들어가지 않는다.
    ``is_registered`` 가 ``COMPILED`` 에만 참이다.
    """
    for status in TriggerCompilationStatus:
        result = TriggerCompilation(
            status=status,
            reason="",
            declared_types=("SINGLE", "TRIGGER_O"),
            spec=(
                TriggerSpec(EffectRef(1, 0), TimingPoint.CARD_DRAWN)
                if status is COMPILED
                else None
            ),
        )
        assert result.is_registered is (status is COMPILED)
