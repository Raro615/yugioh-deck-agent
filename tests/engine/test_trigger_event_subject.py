"""
Phase 6-F — **이 사건이 이 카드의 사건인가.**

Phase 6-E 는 사건의 *종류*와 등록을 맞췄다. 그래서 "몬스터가 일반 소환되었을
때" 까지는 옳았지만 "**이** 카드가 일반 소환되었을 때" 를 가릴 수 없었고,
그 모름을 ``UnimplementedRule`` 조건으로 실어 보냈다. 6-F 가 그 질문에
답한다::

    사건          MonsterSummoned(card=#41)        → TimingEvent.instance = #41
    후보          TriggerCandidate(source=#40)     → 판 위의 그 카드
    선언          TriggerSpec(subject=SELF)        → 자기 사건에만 반응
          ↓  subject_relation
    #41 ≠ #40  →  INVALID / CANDIDATE_NOT_ELIGIBLE   (확정된 거부)
    #41 = #41  →  VALID   / OK
    subject=None →  UNKNOWN / RULE_NOT_IMPLEMENTED    (적지 않았다)

지키는 것 여섯
--------------
1. **같은 카드 ID 의 서로 다른 인스턴스를 구분한다.** 사본 A 가 소환되면
   사본 B 는 후보가 아니다.
2. **적지 않은 것을 통과로 읽지 않는다.** ``subject=None`` 은 ``ANY`` 가
   아니다.
3. 🔴 **수집기와 판정기가 같은 답을 낸다.** ``TriggerEligibility.fold`` 는
   후보의 ``status`` 를 보지 않으므로, 한쪽만 고치면 다시 승격된다.
4. **확정된 거부가 모름보다 앞이다.** ``fold`` 의 순서와 같다.
5. **주체를 통과해도 발동 가능이 아니다.** 자리 · 실행 권위 · 비용이 남는다.
6. **기존 듀얼 결과와 EventJournal 기록이 바뀌지 않는다.**

🔴 이 파일이 **실제 `Duel.apply`** 로 만들지 못하는 것 하나
----------------------------------------------------------
"그 카드 **자신**이 소환되는" 사건은 실제 행동으로 만들 수 없다. 엔진의
``assess_normal_summon`` 이 **효과 몬스터에 ``UNDETERMINED``** 를 돌려주고
(카드 자신의 제약을 아직 못 읽는다) 그래서 ``legal_actions`` 가 일반 소환을
제시하지 않는데, ``SINGLE`` 트리거를 가진 카드는 **전부 효과 몬스터**다
(통상 몬스터에는 효과가 없다). 특수 소환 경로도 마찬가지로 제시되지 않는다.

그래서 **거짓 양성 방향**(다른 카드의 소환)은 실제 ``Duel.apply`` 사건으로
확인하고 (``test_b_*``), **참 방향**(자기 소환)은 실제 ``GameState`` 의
실제 인스턴스로 delta 를 만들어 확인한다 (``test_a_*``). 지어낸 것은
**그 delta 를 만든 행동 하나**뿐이고, 인스턴스 · 관측 · 수집기 · 판정기는
전부 실제다. 이 차단 요인은 보고서 §14 에 적었다.
"""

import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from engine.duel import Duel
from engine.effect.delta import CardDrawn, LifeChanged, MonsterSummoned, SummonKind
from engine.effect.library import definition_registry
from engine.event_pipeline import EventPipeline
from engine.ids import EffectRef, InstanceId
from engine.trigger import (
    SUBJECT_AWARE_POINTS,
    SUBJECT_MISSING_RULE,
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
    TriggerSubject,
    subject_relation,
)
from engine.trigger_compiler import (
    ANY_SCOPE_DECLARATION,
    EVENT_SUBJECT_RULE,
    EVENT_TIMING,
    SELF_SCOPE_DECLARATION,
    compile_trigger_spec,
)
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: 포키 드라코 — 효과 블록이 **하나**뿐이고 그 하나가
#: ``SINGLE+TRIGGER_O`` · ``EVENT_SUMMON_SUCCESS`` 다. 공식 원문도 「이 카드가
#: 일반 소환에 성공했을 때」 이므로 **원문과 등록이 1:1 로 귀속된다** —
#: 블록이 여럿인 카드로는 "어느 문장이 이 블록인가" 를 말할 수 없다.
SELF_SUMMON_CARD = 8175346

#: 엘리멘틀 히어로 페더맨 — **통상** 몬스터라서 엔진이 실제로 일반 소환할 수
#: 있고 (``assess_normal_summon`` 이 ``VALID``), 트리거는 하나도 없다.
FEATHERMAN = 21844576

#: 잭나이츠 오르페골 기르수 — 6-E 가 거짓 양성을 재현한 카드.
GIRSU = 69811710


# ======================================================================
# 도움 함수 — 전부 **실제** 컴파일러를 지난다
# ======================================================================


def registry_from(repository, card_ids):
    """카드 데이터 → 실제 컴파일러 → 등록소. 손으로 선언을 적지 않는다."""
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


def summon_event(instance: InstanceId, kind: SummonKind = SummonKind.NORMAL):
    """
    실제 인스턴스를 주체로 하는 소환 사건.

    ``TimingEvent.from_delta`` 를 그대로 쓴다 — 시점을 손으로 적지 않는다.
    """
    return TimingEvent.from_delta(
        MonsterSummoned(
            summon=kind,
            card=instance,
            player=MINE,
            owner=MINE,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.ATTACK,
        )
    )


@pytest.fixture
def two_copies(repository):
    """
    같은 카드 **2장**을 필드에 둔 실제 판 (시나리오 C).

    덱에도 같은 카드가 있으므로 패에도 사본이 생긴다 — 수집기는 **보이는
    사본마다** 후보를 만들므로 그것까지 포함해 구분해야 한다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([SELF_SUMMON_CARD] * 20, [SELF_SUMMON_CARD] * 20),
        seed=11,
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    first = duel.state.create_instance(
        SELF_SUMMON_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    second = duel.state.create_instance(
        SELF_SUMMON_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    return duel, first.instance_id, second.instance_id


@pytest.fixture
def featherman_summoned(repository):
    """
    기르수를 필드에 두고 **페더맨을 실제로 일반 소환한** 판 (6-E 의 픽스처).

    사건은 전부 실제 ``Duel.apply`` 가 만든 journal 기록에서 나온다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
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


def both_layers(view, registry, event, definitions=None):
    """
    🔴 **수집기와 판정기를 같은 사건에 둘 다 돌린다.**

    ``TriggerEligibility.fold`` 는 관문만 보고 후보의 ``status`` 를 보지
    않으므로, 한쪽만 확인하면 다른 쪽이 조용히 승격시키는 것을 못 본다.
    """
    collector = TriggerCollector(view, registry, definitions)
    judge = TriggerEligibilityJudge(view, definitions)
    out = []
    for candidate in collector.collect(event).candidates:
        spec = next(
            s for s in registry.watching(event) if s.effect_ref == candidate.effect_ref
        )
        out.append((candidate, judge.judge(candidate, spec, event)))
    return out


# ======================================================================
# A. 축의 모양 — 세 상태가 뭉개지지 않는가
# ======================================================================


def test_01_the_axis_has_three_states_not_two():
    """
    ``SELF`` · ``ANY`` · ``None``. 🔴 ``None`` 은 ``ANY`` 가 **아니다.**

    그렇게 읽는 것이 Phase 6-E 가 재현해서 잡은 거짓 양성이다.

    🔴 **Phase 6-H 에서 축이 한 값 늘었다** (``OTHER`` — "이 카드 이외의
    사건에만"). 이 테스트가 틀린 전제를 갖고 있었던 것이 아니라, 6-F 시점에
    실제로 값이 둘이었다. 아래 목록만 고치고 나머지 단정은 **하나도 약화하지
    않았다** — 이 테스트가 지키는 것은 값의 개수가 아니라 *"적지 않은 것을
    통과로 읽지 않는다"* 이고 그것은 그대로다. ``OTHER`` 의 비대칭은
    ``test_trigger_event_subject_condition.py`` 가 전수로 고정한다.
    """
    assert [m.value for m in TriggerSubject] == ["self", "other", "any"]

    base = dict(point=TimingPoint.MONSTER_SUMMONED)
    event = summon_event(InstanceId(7))
    here, elsewhere = InstanceId(7), InstanceId(9)

    unscoped = TriggerSpec(EffectRef(1, 0), **base)
    assert unscoped.subject is None
    verdict = subject_relation(unscoped, event, here)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == SUBJECT_MISSING_RULE

    anyone = TriggerSpec(EffectRef(1, 0), subject=TriggerSubject.ANY, **base)
    assert subject_relation(anyone, event, elsewhere).permits_execution is True

    mine = TriggerSpec(EffectRef(1, 0), subject=TriggerSubject.SELF, **base)
    assert subject_relation(mine, event, here).permits_execution is True
    refusal = subject_relation(mine, event, elsewhere)
    assert refusal.validity is ActionValidity.INVALID
    assert refusal.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    #: 🔴 **확정된 거부는 미구현이 아니다.** 양쪽이 ``InstanceId`` 를 들고
    #: 있으므로 데이터 비교로 답이 확정된다.
    assert refusal.missing_rule is None


def test_02_a_missing_value_is_unknown_for_a_different_reason_than_a_missing_rule():
    """
    🔴 **두 ``UNKNOWN`` 을 가른다** (3-E-27 의 규율).

    ``subject`` 를 적지 않은 것은 **규칙이 없어서**이고 (코드가 생겨야 풀린다),
    사건이 카드를 가리키지 않는 것은 **정보가 없어서**다 (판이 바뀌면 풀린다).
    """
    mine = TriggerSpec(
        EffectRef(1, 0), TimingPoint.CARD_DRAWN, subject=TriggerSubject.SELF
    )

    #: 라이프 사건은 카드 한 장을 가리키지 않는다.
    bloodless = TimingEvent.from_delta(LifeChanged(player=MINE, before=8000, after=7000))
    assert bloodless.instance is None
    no_value = subject_relation(mine, bloodless, InstanceId(3))
    assert no_value.validity is ActionValidity.UNKNOWN
    assert no_value.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert no_value.missing_rule is None

    #: 후보 쪽 인스턴스를 모르는 경우도 같은 갈래다.
    drawn = TimingEvent.from_delta(CardDrawn(player=MINE, card=InstanceId(3)))
    assert subject_relation(mine, drawn, None).code is (
        ValidationCode.INFORMATION_UNAVAILABLE
    )

    #: 반면 적지 않은 선언은 규칙 쪽이다.
    unscoped = TriggerSpec(EffectRef(1, 0), TimingPoint.CARD_DRAWN)
    assert subject_relation(unscoped, drawn, InstanceId(3)).code is (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )


def test_03_the_axis_is_refused_where_the_event_names_no_card():
    """
    주체를 걸 수 있는 시점은 **사건이 카드 한 장을 가리키는** 것들뿐이다.

    영원히 ``UNKNOWN`` 인 선언을 만들 수 있게 두면 "모른다" 가 쌓인다 —
    ``summons`` 를 ``MONSTER_SUMMONED`` 에만 허용한 것과 같은 이유다.
    """
    assert SUBJECT_AWARE_POINTS == frozenset(
        {TimingPoint.MONSTER_SUMMONED, TimingPoint.CARD_MOVED, TimingPoint.CARD_DRAWN}
    )

    #: 🔴 허용 목록이 **측정과 맞는다** — 그 시점들만 ``instance`` 를 돌려준다.
    carries = {
        TimingPoint.MONSTER_SUMMONED: summon_event(InstanceId(1)),
        TimingPoint.CARD_DRAWN: TimingEvent.from_delta(
            CardDrawn(player=MINE, card=InstanceId(1))
        ),
        TimingPoint.LIFE_CHANGED: TimingEvent.from_delta(
            LifeChanged(player=MINE, before=8000, after=7000)
        ),
    }
    for point, event in carries.items():
        has_instance = event.instance is not None
        assert has_instance is (point in SUBJECT_AWARE_POINTS), point

    for point in TimingPoint:
        if point in SUBJECT_AWARE_POINTS:
            continue
        with pytest.raises(TriggerError, match="subject"):
            TriggerSpec(
                EffectRef(1, 0),
                point,
                subject=TriggerSubject.SELF,
                **({"note": ""} if False else {}),
            )


def test_04_the_axis_rides_in_the_canonical_state_and_the_dict():
    """축이 직렬화에 **실려 나간다.** 빠지면 두 선언이 같은 값으로 보인다."""
    plain = TriggerSpec(EffectRef(1, 0), TimingPoint.CARD_DRAWN)
    mine = TriggerSpec(
        EffectRef(1, 0), TimingPoint.CARD_DRAWN, subject=TriggerSubject.SELF
    )
    anyone = TriggerSpec(
        EffectRef(1, 0), TimingPoint.CARD_DRAWN, subject=TriggerSubject.ANY
    )

    states = {s.canonical_state() for s in (plain, mine, anyone)}
    assert len(states) == 3

    assert "subject" not in plain.to_dict()
    assert mine.to_dict()["subject"] == "self"
    assert anyone.to_dict()["subject"] == "any"
    #: 정규 표현은 값 타입만 담는다 (판 복제 · 비교에 쓰인다).
    for spec in (plain, mine, anyone):
        for value in spec.canonical_state():
            assert value is None or isinstance(value, (int, str, tuple)), value


# ======================================================================
# B. 컴파일러 — 데이터에서 읽을 수 있는 것만 적는가
# ======================================================================


def test_05_the_compiler_writes_self_only_for_the_scope_it_can_read():
    """
    ``SINGLE`` → ``SELF``. ``FIELD`` → **적지 않는다.**

    🔴 컴파일러는 ``ANY`` 를 **쓰지 않는다** — Lua 등록만으로는 ``FIELD`` 가
    "어느 카드든" 인지 "이 카드" 인지 가려낼 수 없다.
    """
    assert (SELF_SCOPE_DECLARATION, ANY_SCOPE_DECLARATION) == ("SINGLE", "FIELD")

    def subject_of(types):
        result = compile_trigger_spec(
            EffectRef(1, 0),
            declared_types=types,
            event_code="EVENT_SUMMON_SUCCESS",
        )
        assert result is not None and result.is_registered
        return result.spec.subject

    assert subject_of(("SINGLE", "TRIGGER_O")) is TriggerSubject.SELF
    assert subject_of(("SINGLE", "TRIGGER_F")) is TriggerSubject.SELF
    assert subject_of(("FIELD", "TRIGGER_O")) is None
    assert subject_of(("TRIGGER_O",)) is None
    #: 둘이 함께 적힌 블록은 ``SINGLE`` 쪽을 따른다 — 측정에서 0건이지만
    #: 모양이 들어와도 **통과로 새지 않아야** 한다.
    assert subject_of(("SINGLE", "FIELD", "TRIGGER_O")) is TriggerSubject.SELF


def test_06_the_compiler_no_longer_borrows_the_condition_slot():
    """
    🔴 **Phase 6-E 는 조건 자리를 빌렸고 6-F 가 돌려준다.**

    6-E 는 "누구의 사건인가" 를 ``UnimplementedRule`` **조건**으로 실어
    보냈다. 조건은 ``ConditionEvaluator`` 가 ``GameStateView`` 를 들고 묻는
    **판 위의 사실**이고 사건의 성질이 아니므로 자리가 맞지 않았다.

    모름이 사라진 것이 아니라 **제자리로 갔다** — 아래에서 그것을 단정한다.
    """
    for types in (("SINGLE", "TRIGGER_O"), ("FIELD", "TRIGGER_O")):
        result = compile_trigger_spec(
            EffectRef(1, 0), declared_types=types, event_code="EVENT_TO_GRAVE"
        )
        assert result.spec.condition is None, types

    #: 그런데 ``FIELD`` 의 모름은 그대로 남아 있다 — 축이 말한다.
    field = compile_trigger_spec(
        EffectRef(1, 0), declared_types=("FIELD", "TRIGGER_O"), event_code="EVENT_TO_GRAVE"
    )
    moved = TimingEvent.from_delta(
        __import__("engine.effect.delta", fromlist=["ZoneMoved"]).ZoneMoved(
            movement=__import__(
                "engine.effect.operation", fromlist=["OperationKind"]
            ).OperationKind.SEND_TO_GRAVE,
            card=InstanceId(4),
            source_player=MINE,
            source_zone=Zone.MZONE,
            destination_player=MINE,
            destination_zone=Zone.GRAVE,
        )
    )
    verdict = subject_relation(field.spec, moved, InstanceId(4))
    assert verdict.missing_rule == EVENT_SUBJECT_RULE
    #: 🔴 6-E 가 지은 이름을 그대로 쓴다 — 같은 사실에 이름이 둘이면
    #: 로드맵 추적이 갈라진다.
    assert EVENT_SUBJECT_RULE == SUBJECT_MISSING_RULE


@requires_official_db
def test_07_the_corpus_splits_into_a_known_and_an_unknown_half(repository):
    """
    🔴 **전수 측정** — 지원 범위를 수치로 고정한다 (지시서 §11-1 · §11-2).

    표본이 아니다. 컴파일되는 선언 전부를 센다.
    """
    analyzer = EffectAnalyzer(repository)
    known = unknown = 0
    by_point: dict[tuple[str, str], int] = {}
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
            if result is None or not result.is_registered:
                continue
            spec = result.spec
            tag = "self" if spec.subject is TriggerSubject.SELF else "unknown"
            key = (tag, spec.point.value)
            by_point[key] = by_point.get(key, 0) + 1
            if spec.subject is TriggerSubject.SELF:
                known += 1
            else:
                unknown += 1
            #: 🔴 ``ANY`` 는 데이터에서 **절대 나오지 않는다.**
            assert spec.subject is not TriggerSubject.ANY, spec.effect_ref

    assert known == 3389, known
    assert unknown == 784, unknown
    assert known + unknown == 4173  # 6-E 의 컴파일 수와 같다 — 줄지 않았다
    assert by_point[("self", "monster_summoned")] == 2328
    assert by_point[("self", "card_moved")] == 1051
    assert by_point[("self", "card_drawn")] == 10
    assert by_point[("unknown", "monster_summoned")] == 561
    assert by_point[("unknown", "card_moved")] == 206
    assert by_point[("unknown", "card_drawn")] == 17


# ======================================================================
# C. 시나리오 A · C — 자기 사건, 그리고 같은 카드명 복수 인스턴스
# ======================================================================


@requires_official_db
def test_08_only_the_summoned_copy_is_a_candidate(repository, two_copies):
    """
    🔴 **시나리오 A + C — 이 Phase 의 중심 단정.**

    같은 카드 ID 의 사본이 여럿 보이는데 소환된 것은 하나다. 그 하나만
    후보가 되고 나머지는 **확정된 거부**다.
    """
    duel, first, second = two_copies
    registry, compiled = registry_from(repository, [SELF_SUMMON_CARD])
    assert len(compiled) == 1
    assert compiled[0].spec.subject is TriggerSubject.SELF

    view = duel.view(MINE)
    for summoned in (first, second):
        pairs = both_layers(view, registry, summon_event(summoned))
        #: 보이는 사본이 여럿이므로 후보 자리도 여럿이다.
        assert len(pairs) > 1
        passed = [
            (c, e) for c, e in pairs if c.status is TriggerStatus.ELIGIBLE
        ]
        assert len(passed) == 1, [(c.source, c.status.value) for c, _ in pairs]
        [(candidate, eligibility)] = passed
        assert candidate.source == summoned

        for other, judged in pairs:
            if other.source == summoned:
                continue
            assert other.status is TriggerStatus.INELIGIBLE
            assert other.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
            assert judged.status is TriggerStatus.INELIGIBLE
            #: 🔴 어느 쪽이 달랐는지 **이유에서 읽을 수 있다.**
            assert str(summoned) in other.reason
            assert str(other.source) in other.reason

        #: 🔴 통과한 하나도 **발동 가능이 아니다** (지시서 §16-6).
        assert eligibility.may_activate is False
        blocked = {v.gate for v in eligibility.blocking}
        assert EligibilityGate.EVENT_RELATION not in blocked
        assert EligibilityGate.ACTIVATION_ZONE in blocked
        assert eligibility.fully_checked is False


@requires_official_db
def test_09_the_two_copies_never_swap_verdicts(repository, two_copies):
    """
    사본 A 가 소환될 때와 B 가 소환될 때의 답이 **정확히 뒤바뀐다.**

    둘이 같은 답을 받으면 (둘 다 통과 · 둘 다 거부) 인스턴스를 구분하지
    못하는 것이고, 그것이 이 Phase 가 막으려는 것이다.
    """
    duel, first, second = two_copies
    registry, _ = registry_from(repository, [SELF_SUMMON_CARD])
    view = duel.view(MINE)

    def eligible_sources(summoned):
        return {
            candidate.source
            for candidate, _ in both_layers(view, registry, summon_event(summoned))
            if candidate.status is TriggerStatus.ELIGIBLE
        }

    assert eligible_sources(first) == {first}
    assert eligible_sources(second) == {second}
    assert first != second


@requires_official_db
def test_10_a_special_summon_of_the_same_instance_is_still_refused(
    repository, two_copies
):
    """
    시나리오 D — 주체가 맞아도 **소환 종류가 다르면** 거부다 (6-E 의 축).

    두 축이 서로를 가리지 않는지 확인한다: 주체만 보고 통과시키면 6-E 가
    고친 거짓 양성이 돌아온다.
    """
    duel, first, _second = two_copies
    registry, _ = registry_from(repository, [SELF_SUMMON_CARD])
    view = duel.view(MINE)

    special = summon_event(first, SummonKind.SPECIAL)
    #: 등록은 통상 소환만 보므로 이 사건에는 아예 반응하지 않는다.
    assert registry.watching(special) == ()
    assert both_layers(view, registry, special) == []

    #: 같은 인스턴스의 통상 소환에는 반응한다.
    normal = summon_event(first, SummonKind.NORMAL)
    assert len(registry.watching(normal)) == 1


# ======================================================================
# D. 시나리오 B · I — 다른 카드의 사건 (실제 Duel.apply)
# ======================================================================


@requires_official_db
def test_11_girsu_is_refused_on_a_real_summon_of_another_card(
    repository, featherman_summoned
):
    """
    🔴 **시나리오 B + I — 6-E 가 재현한 거짓 양성이 실제 사건에서 막힌다.**

    사건은 지어낸 것이 아니다. 실제 ``Duel.apply`` 가 만든 journal 기록을
    기존 ``EventPipeline`` 에 그대로 넘긴다.
    """
    registry, compiled = registry_from(repository, [GIRSU])
    assert len(compiled) == 2
    assert {c.spec.subject for c in compiled} == {TriggerSubject.SELF}

    seen = 0
    for definitions in (None, definition_registry()):
        pipeline = EventPipeline(
            featherman_summoned.view(MINE), registry, definitions
        )
        judge = TriggerEligibilityJudge(featherman_summoned.view(MINE), definitions)
        for event in featherman_summoned.journal.events:
            for observation in pipeline.collect(event, actor=event.actor):
                for candidate in observation.candidates:
                    seen += 1
                    assert candidate.status is TriggerStatus.INELIGIBLE
                    assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
                    spec = next(
                        s
                        for s in registry.watching(observation.event.timing)
                        if s.effect_ref == candidate.effect_ref
                    )
                    judged = judge.judge(candidate, spec, observation.event.timing)
                    assert judged.status is TriggerStatus.INELIGIBLE
                    assert judged.may_activate is False
    #: 두 경로(정의 있음 · 없음) 에서 각각 하나.
    assert seen == 2


@requires_official_db
def test_12_girsu_passes_the_subject_gate_on_its_own_summon(repository):
    """
    시나리오 I 의 뒷면 — **기르수 자신**의 사건에서는 주체 관문을 통과한다.

    차단만 하고 아무것도 통과시키지 못하면 축이 쓸모가 없다. 통과하는 것과
    통과하지 못하는 것이 **둘 다** 있어야 축이 일을 한다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    girsu = duel.state.create_instance(
        GIRSU, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    registry, _ = registry_from(repository, [GIRSU])
    view = duel.view(MINE)

    #: 기르수는 선언이 둘이다 (통상 · 특수). 각각 자기 종류에서만 통과한다.
    for kind, expected in (
        (SummonKind.NORMAL, 0),
        (SummonKind.SPECIAL, 1),
    ):
        pairs = both_layers(view, registry, summon_event(girsu.instance_id, kind))
        assert len(pairs) == 1
        candidate, eligibility = pairs[0]
        assert candidate.effect_ref == EffectRef(GIRSU, expected)
        assert candidate.status is TriggerStatus.ELIGIBLE
        gate = eligibility.gate(EligibilityGate.EVENT_RELATION)
        assert gate.validity is ActionValidity.VALID
        #: 🔴 그래도 발동 가능이 아니다.
        assert eligibility.may_activate is False


# ======================================================================
# E. 시나리오 G · H — 모를 때는 모른다고 한다
# ======================================================================


@requires_official_db
def test_13_an_unscoped_declaration_stays_unknown_in_both_layers(repository):
    """
    시나리오 G — ``FIELD`` 범위처럼 **주체를 적지 못한** 등록.

    통과도 거부도 아니다. 🔴 수집기와 판정기가 **둘 다** ``UNKNOWN`` 이어야
    한다 — 한쪽이 통과시키면 그것이 잘못된 TRUE 승격이다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    landed = duel.state.create_instance(
        FEATHERMAN, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    #: 실제 컴파일러가 ``FIELD`` 에서 만드는 그 모양을 손으로 다시 적지 않고
    #: 컴파일러에게 받는다.
    result = compile_trigger_spec(
        EffectRef(FEATHERMAN, 0),
        declared_types=("FIELD", "TRIGGER_O"),
        event_code="EVENT_SUMMON_SUCCESS",
    )
    assert result.spec.subject is None
    registry = TriggerRegistry((result.spec,))

    pairs = both_layers(duel.view(MINE), registry, summon_event(landed.instance_id))
    assert pairs
    for candidate, eligibility in pairs:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert candidate.is_candidate is False
        assert SUBJECT_MISSING_RULE in candidate.notes
        assert eligibility.status is TriggerStatus.UNKNOWN
        assert eligibility.may_activate is False
        gate = eligibility.gate(EligibilityGate.EVENT_RELATION)
        assert gate.validity is ActionValidity.UNKNOWN
        assert gate.result.missing_rule == SUBJECT_MISSING_RULE


@requires_official_db
def test_14_a_definite_refusal_outranks_a_missing_definition(repository, two_copies):
    """
    🔴 **확정된 거부가 모름보다 앞이다** — 순서는 ``fold`` 와 같다.

    처음 구현은 "정의 미등록" 가지를 주체보다 **먼저** 보았다. 그래서 정의
    출처를 넘기면 주체가 다르다는 **확정된 사실**이 "조건을 모른다" 에 덮여
    수집기(``UNKNOWN``) 와 판정기(``INELIGIBLE``) 의 답이 어긋났다.
    """
    duel, first, second = two_copies
    registry, _ = registry_from(repository, [SELF_SUMMON_CARD])
    view = duel.view(MINE)
    event = summon_event(first)

    #: 정의 출처가 있을 때와 없을 때의 답이 **같다.**
    def verdicts(definitions):
        return {
            (c.source, c.status, c.code)
            for c, _ in both_layers(view, registry, event, definitions)
            if c.source != first
        }

    assert verdicts(None) == verdicts(definition_registry())
    for _source, status, code in verdicts(definition_registry()):
        assert status is TriggerStatus.INELIGIBLE
        assert code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 그리고 두 계층의 답이 어긋나지 않는다.
    for candidate, eligibility in both_layers(
        view, registry, event, definition_registry()
    ):
        if candidate.source == first:
            continue
        assert candidate.status is eligibility.status


# ======================================================================
# F. 시나리오 J — 판과 기록이 바뀌지 않는가
# ======================================================================


@requires_official_db
def test_15_judging_changes_neither_the_board_nor_the_journal(
    repository, featherman_summoned
):
    """
    시나리오 J — 후보 검증이 **판도 기록도 난수도** 건드리지 않는다.

    주체 비교는 관측과 사건만 읽는다.
    """
    duel = featherman_summoned
    registry, _ = registry_from(repository, [GIRSU])

    before_hash = duel.state.state_hash()
    before_rng = repr(duel.state.rng)
    before_events = [e.canonical_state() for e in duel.journal.events]

    pipeline = EventPipeline(duel.view(MINE), registry, definition_registry())
    judge = TriggerEligibilityJudge(duel.view(MINE), definition_registry())
    for event in duel.journal.events:
        for observation in pipeline.collect(event, actor=event.actor):
            for candidate in observation.candidates:
                spec = next(
                    s
                    for s in registry.watching(observation.event.timing)
                    if s.effect_ref == candidate.effect_ref
                )
                judge.judge(candidate, spec, observation.event.timing)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng
    assert [e.canonical_state() for e in duel.journal.events] == before_events


@requires_official_db
def test_16_the_unchecked_rules_are_unchanged(repository, two_copies):
    """
    🔴 **미검증 규칙 목록이 줄지 않았다** (지시서 §11-9).

    주체를 보게 되었다고 타이밍 · 우선권 · 비용을 본 것이 아니다. 통과한
    후보도 그 여섯 가지를 **그대로 싣고** 나간다.
    """
    from engine.trigger import UNCHECKED_RULES

    assert len(UNCHECKED_RULES) == 6
    assert "timing window (놓친 타이밍 · 열린 타이밍)" in UNCHECKED_RULES
    assert "SEGOC 및 동시 트리거 순서" in UNCHECKED_RULES
    #: 주체는 **이 목록에 들어가지 않는다** — 이제 보기 때문이다.
    assert not any("주체" in rule for rule in UNCHECKED_RULES)

    duel, first, _ = two_copies
    registry, _ = registry_from(repository, [SELF_SUMMON_CARD])
    for _candidate, eligibility in both_layers(
        duel.view(MINE), registry, summon_event(first)
    ):
        assert eligibility.unchecked_rules == UNCHECKED_RULES
        assert eligibility.fully_checked is False


# ======================================================================
# G. 잘못된 TRUE 승격이 가능한 모양이 남아 있는가
# ======================================================================


def test_17_no_combination_promotes_an_unknown_subject_to_eligible():
    """
    🔴 **진리표를 전수로 돌린다** (지시서 §11-8).

    세 ``subject`` × 세 사건 모양. ``ELIGIBLE`` 이 나오는 칸은 **주체가
    확실히 맞는 칸뿐**이어야 한다.
    """
    here, elsewhere = InstanceId(7), InstanceId(9)
    events = {
        "주체=나": summon_event(here),
        "주체=남": summon_event(elsewhere),
        "주체=없음": TimingEvent.from_delta(
            LifeChanged(player=MINE, before=8000, after=7000)
        ),
    }
    table: dict[tuple[str, str], ActionValidity] = {}
    for label, subject in (
        ("None", None),
        ("SELF", TriggerSubject.SELF),
        ("ANY", TriggerSubject.ANY),
    ):
        for name, event in events.items():
            point = (
                TimingPoint.MONSTER_SUMMONED
                if event.instance is not None
                else TimingPoint.CARD_DRAWN
            )
            spec = TriggerSpec(EffectRef(1, 0), point, subject=subject)
            table[(label, name)] = subject_relation(spec, event, here).validity

    passes = {
        key for key, validity in table.items() if validity is ActionValidity.VALID
    }
    #: 🔴 통과하는 칸은 **정확히 넷**이다: ``SELF`` 가 맞은 칸, 그리고
    #: ``ANY`` 의 세 칸 전부. ``None`` 은 어느 사건에서도 통과하지 않는다.
    #:
    #: .. note::
    #:    처음에 이 단정을 **셋**으로 적었다가 이 진리표가 잡았다 — 내가
    #:    ``("ANY", "주체=없음")`` 을 빼 두었다. 따져 보니 ``ANY`` 가 옳다:
    #:    그 값은 "주체에 제약을 걸지 않는다" 는 **단정**이므로 읽을 것이
    #:    없고, ``UNKNOWN`` 으로 적으면 **알 것이 없는 자리를 모른다고**
    #:    말하는 셈이 된다. 그래서 함수가 아니라 내 기대값을 고쳤다.
    #:
    #:    그리고 그 칸은 실제 파이프라인에서 **도달 불가**다 — 아래에서
    #:    확인한다. 축을 걸 수 있는 시점이 ``SUBJECT_AWARE_POINTS`` 로
    #:    제한되고, 시점이 다른 사건은 ``matches`` 가 먼저 걸러낸다.
    assert passes == {
        ("SELF", "주체=나"),
        ("ANY", "주체=나"),
        ("ANY", "주체=남"),
        ("ANY", "주체=없음"),
    }, sorted(passes)
    assert all(
        table[("None", name)] is ActionValidity.UNKNOWN for name in events
    )

    #: 🔴 **그 칸은 파이프라인에 들어올 수 없다.** 둘 중 하나로 막힌다.
    bloodless = events["주체=없음"]
    with pytest.raises(TriggerError, match="subject"):
        TriggerSpec(
            EffectRef(1, 0), bloodless.point, subject=TriggerSubject.ANY
        )
    drawn_spec = TriggerSpec(
        EffectRef(1, 0), TimingPoint.CARD_DRAWN, subject=TriggerSubject.ANY
    )
    assert drawn_spec.matches(bloodless) is False
    #: 거부가 나오는 칸도 하나뿐이다 — 모름을 거부로 접지 않는다.
    refusals = {
        key for key, validity in table.items() if validity is ActionValidity.INVALID
    }
    assert refusals == {("SELF", "주체=남")}


def test_18_the_validity_table_covers_every_case():
    """
    판정 어휘 → 조건 어휘 변환표가 **빠진 갈래가 없다.**

    분기로 쓰면 한 갈래를 빠뜨려도 조용히 통과한다. 그래서 표로 두고, 표가
    전부를 덮는지 여기서 잠근다.
    """
    from engine.trigger import _CONDITION_OF_VALIDITY

    assert set(_CONDITION_OF_VALIDITY) == set(ActionValidity)
    #: 그리고 뜻이 섞이지 않았다.
    from engine.condition import ConditionResult

    assert _CONDITION_OF_VALIDITY[ActionValidity.VALID] is ConditionResult.TRUE
    assert _CONDITION_OF_VALIDITY[ActionValidity.INVALID] is ConditionResult.FALSE
    assert _CONDITION_OF_VALIDITY[ActionValidity.UNKNOWN] is ConditionResult.UNKNOWN


def test_19_both_layers_call_the_same_function():
    """
    🔴 **한 구현, 두 호출 자리.**

    ``TriggerEligibility.fold`` 는 관문만 보고 후보의 ``status`` 를 보지
    않으므로 두 계층이 **둘 다** 주체를 봐야 한다. 두 벌로 짜면 갈라진다 —
    그래서 같은 함수를 부르는지 구문으로 확인한다.
    """
    import ast

    source = (PROJECT_ROOT / "engine" / "trigger.py").read_text(encoding="utf-8")
    callers: dict[str, int] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hits = sum(
            1
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "subject_relation"
        )
        if hits:
            callers[node.name] = hits

    assert callers == {"_judge": 1, "_event_relation": 1}, callers
    #: 선언이 하나뿐이다 — 같은 이름의 두 구현이 생기지 않았다.
    definitions = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "subject_relation"
    ]
    assert definitions == ["subject_relation"]
