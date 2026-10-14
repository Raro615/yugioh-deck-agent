"""
Phase 6-G — **효과를 어디에서 발동할 수 있는가.**

6-F 가 "누구의 사건인가" 를 답했고, 6-G 는 그 옆 축을 본다. 핵심은
**``SetRange`` 가 두 가지 다른 사실 중 하나라는 것**이다::

    SetRange(LOCATION_GRAVE) + FIELD 등록
        → 이 카드가 묘지에 **있어야** 효과가 산다 = 발동 위치
          (숲의 파수꾼 그린 바분: 「이 카드가 패 / 묘지에 존재하고」)

    SetRange(LOCATION_MZONE) + SINGLE 등록 + EVENT_TO_GRAVE
        → 효과는 필드에서 **등록**되지만 발동하는 순간 카드는 묘지다
          (드로우 개구리: 「필드의 앞면 표시의 이 카드가 묘지로 보내졌을 때」)
          그 Lua 가 직접 ``c:IsPreviousLocation(LOCATION_ONFIELD)`` 를 쓴다

앞쪽은 ``activates_from`` (지금 어디 있어야 하는가), 뒤쪽은 ``from_zones``
(어디에서 움직여 나왔는가) 다. 둘을 한 칸에 넣으면 뒤쪽에서 **확정 거부**가
난다 — 실제로 재현했고 이 파일이 그것을 잠근다.

지키는 것 일곱
--------------
1. **등록 범위와 발동 위치를 가른다.** ``SetRange`` 하나가 두 뜻을 갖는다.
2. **현재 영역과 직전 영역을 가른다.** 앞은 관측이, 뒤는 **사건**이 들고 있다.
3. **복수 영역을 잃지 않는다.** 두 영역 선언은 두 영역 다 통과시킨다.
4. **없는 정보를 지어내지 않는다.** ``SetRange`` 가 없으면 ``UNKNOWN`` 이고,
   "카드가 간 곳" 을 발동 위치로 적지 않는다 — 그러면 **항상 통과하는
   동어반복**이 되어 검사한 척하게 된다.
5. 🔴 **위치를 통과해도 발동 가능이 아니다.** 6-F 의 주체 축과 **둘 다**
   있어야 하고, 그래도 실행 권위 · 비용이 남는다.
6. **6-F 의 주체 판정을 훼손하지 않는다.**
7. **판과 기록이 바뀌지 않는다.**

🔴 이 파일이 쓰는 카드는 전부 **공식 원문이 위치를 직접 말하는** 것으로
골랐다 (측정으로 찾았고, 카드별 분기는 production 에 없다).
"""

import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from engine.duel import Duel
from engine.effect.delta import ZoneMoved
from engine.effect.library import definition_registry
from engine.effect.operation import OperationKind
from engine.ids import EffectRef, InstanceId
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerStatus,
    TriggerSubject,
)
from engine.trigger_compiler import PREVIOUS_ZONE_RULE, compile_trigger_spec
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: 🔴 **전부 공식 원문이 위치를 말하는 카드다.** 주석의 인용이 근거다.
#:
#: 레알 제넥스 마그나 — 「①: 이 카드를 일반 소환했을 때에 발동할 수 있다」
#: (``SELF`` · ``SetRange(MZONE)`` · 소환 성공 → 필드에 있다)
FIELD_CARD = 1533292
#: 다크 버저 — 「… 일반 소환되었을 때, 이 카드를 **묘지에서** 특수 소환할 수
#: 있다」 (``SetRange(GRAVE)``)
GRAVE_CARD = 50164989
#: 이계의 극자룡 — 「… 묘지로 보내졌을 경우, 이 카드를 **패에서** 특수 소환할
#: 수 있다」 (``SetRange(HAND)``)
HAND_CARD = 25206027
#: 환롱룡화－패파 — 「②: **이 카드가 제외 상태이고**, 몬스터가 앞면으로
#: 제외되었을 경우 …」 (``SetRange(REMOVED)``, ``e[1]``)
REMOVED_CARD, REMOVED_ORDINAL = 56499179, 1
#: 숲의 파수꾼 그린 바분 — 「①: **이 카드가 패 / 묘지에 존재하고**, …」
#: 🔴 원문이 **두 영역을 직접 적는다** — 복수 영역의 근거다.
MULTI_CARD = 46668237
#: 드로우 개구리 — 「①: **필드의 앞면 표시의** 이 카드가 **묘지로 보내졌을
#: 때**에 발동할 수 있다」. 🔴 이 Phase 가 고친 **유일한** 거짓 음성이다.
MOVED_CARD = 56840658
#: 포키 드라코 — ``SetRange`` 가 **없는** 3,358건의 대표 (6-F 가 쓴 카드).
NO_RANGE_CARD = 8175346
#: 잭나이츠 오르페골 기르수 — 6-E · 6-F 의 회귀 카드.
GIRSU = 69811710


# ======================================================================
# 도움 함수 — 전부 **실제** 컴파일러를 지난다
# ======================================================================


def specs_of(repository, card_id, *, only=None):
    """카드 데이터 → 실제 컴파일러 → 선언들. 손으로 적지 않는다."""
    analyzer = EffectAnalyzer(repository)
    card = repository.get(card_id)
    assert card is not None and card.script is not None, card_id
    out = []
    for ordinal, effect in enumerate(analyzer.analyze(card).effects):
        if only is not None and ordinal != only:
            continue
        result = compile_trigger_spec(
            EffectRef(card_id, ordinal),
            declared_types=effect.effect_types,
            event_code=effect.raw.code,
            ranges=effect.raw.ranges,
        )
        if result is not None and result.is_registered:
            out.append(result.spec)
    return out


def one_spec(repository, card_id, *, only=None):
    found = specs_of(repository, card_id, only=only)
    assert len(found) == 1, [s.effect_ref for s in found]
    return found[0]


def board(repository, card_id, zone, *, count=1, position=Position.FACEUP_ATTACK):
    """그 카드를 지정한 영역에 ``count`` 장 둔 실제 판."""
    duel = Duel.start(
        repository=repository, decks=([card_id] * 20, [card_id] * 20), seed=9
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    placed = [
        duel.state.create_instance(card_id, owner=MINE, zone=zone, position=position)
        for _ in range(count)
    ]
    return duel, [p.instance_id for p in placed]


def zone_gate(view, spec, candidate, event):
    """그 후보의 ``ACTIVATION_ZONE`` 관문 판정."""
    eligibility = TriggerEligibilityJudge(view).judge(candidate, spec, event)
    return eligibility, eligibility.gate(EligibilityGate.ACTIVATION_ZONE)


def judge_at(duel, spec, event, instance):
    """그 인스턴스의 후보 하나를 수집기와 판정기 양쪽으로 본다."""
    view = duel.view(MINE)
    registry = TriggerRegistry((spec,))
    found = [
        c
        for c in TriggerCollector(view, registry).collect(event).candidates
        if c.source == instance
    ]
    assert len(found) == 1, [c.source for c in found]
    candidate = found[0]
    eligibility, gate = zone_gate(view, spec, candidate, event)
    return candidate, eligibility, gate


def move_event(instance, source, destination, *, operation=OperationKind.SEND_TO_GRAVE):
    return TimingEvent.from_delta(
        ZoneMoved(
            movement=operation,
            card=instance,
            source_player=MINE,
            source_zone=source,
            destination_player=MINE,
            destination_zone=destination,
        )
    )


# ======================================================================
# A. 시나리오 1~4 — 한 영역에서 발동하는 효과
# ======================================================================


@requires_official_db
@pytest.mark.parametrize(
    "label, card_id, ordinal, where, elsewhere",
    [
        ("시나리오 1 · 필드", FIELD_CARD, None, Zone.MZONE, Zone.GRAVE),
        ("시나리오 2 · 묘지", GRAVE_CARD, None, Zone.GRAVE, Zone.MZONE),
        ("시나리오 3 · 패", HAND_CARD, None, Zone.HAND, Zone.MZONE),
        ("시나리오 4 · 제외", REMOVED_CARD, REMOVED_ORDINAL, Zone.REMOVED, Zone.MZONE),
    ],
)
def test_01_a_single_zone_declaration_passes_there_and_is_refused_elsewhere(
    repository, label, card_id, ordinal, where, elsewhere
):
    """
    🔴 **시나리오 1~4 — 네 영역 전부 같은 규칙으로 판정된다.**

    카드별 분기 없이 ``activates_from`` 하나로 네 가지 위치가 다 나온다.
    맞으면 통과, 다르면 **확정 거부**이고 ``UNKNOWN`` 이 아니다 — 양쪽이
    영역을 들고 있으므로 데이터 비교로 답이 확정된다.
    """
    spec = one_spec(repository, card_id, only=ordinal)
    assert spec.activates_from == frozenset({where}), spec.to_dict()

    #: 맞는 자리 — 통과한다.
    duel, [here] = board(repository, card_id, where)
    view = duel.view(MINE)
    registry = TriggerRegistry((spec,))
    event = TimingEvent.unimplemented("자리만 보는 시험")
    found = TriggerEligibilityJudge(view).judge(
        next(
            c
            for c in TriggerCollector(view, registry).collect(
                _matching_event(spec, here)
            ).candidates
            if c.source == here
        ),
        spec,
        _matching_event(spec, here),
    )
    gate = found.gate(EligibilityGate.ACTIVATION_ZONE)
    assert (gate.validity, gate.code) == (ActionValidity.VALID, ValidationCode.OK), (
        label,
        gate.result.reason,
    )
    assert where.value in gate.result.reason

    #: 다른 자리 — 확정 거부.
    other_duel, [there] = board(repository, card_id, elsewhere)
    other_view = other_duel.view(MINE)
    other = TriggerEligibilityJudge(other_view).judge(
        next(
            c
            for c in TriggerCollector(other_view, registry).collect(
                _matching_event(spec, there)
            ).candidates
            if c.source == there
        ),
        spec,
        _matching_event(spec, there),
    )
    refused = other.gate(EligibilityGate.ACTIVATION_ZONE)
    assert refused.validity is ActionValidity.INVALID, label
    assert refused.code is ValidationCode.SOURCE_WRONG_ZONE
    #: 🔴 어느 자리였고 어디를 요구했는지 **둘 다** 이유에 적힌다.
    assert elsewhere.value in refused.result.reason
    assert where.value in refused.result.reason
    assert event.point is TimingPoint.UNIMPLEMENTED  # 하네스 확인용


def _matching_event(spec, instance):
    """그 선언이 반응하는 가장 단순한 사건 하나."""
    from engine.effect.delta import CardDrawn, MonsterSummoned, SummonKind

    if spec.point is TimingPoint.MONSTER_SUMMONED:
        kinds = sorted(spec.summons or ()) or [SummonKind.NORMAL]
        return TimingEvent.from_delta(
            MonsterSummoned(
                summon=kinds[0],
                card=instance,
                player=MINE,
                owner=MINE,
                from_zone=Zone.HAND,
                to_zone=Zone.MZONE,
                to_index=0,
                position=Position.ATTACK,
            )
        )
    if spec.point is TimingPoint.CARD_DRAWN:
        return TimingEvent.from_delta(CardDrawn(player=MINE, card=instance))
    destinations = sorted(spec.to_zones or {Zone.GRAVE})
    sources = sorted(spec.from_zones or {Zone.MZONE})
    return move_event(instance, sources[0], destinations[0])


# ======================================================================
# B. 시나리오 5 — 복수 영역을 잃지 않는가
# ======================================================================


@requires_official_db
def test_02_two_declared_zones_both_pass_and_a_third_is_refused(repository):
    """
    🔴 **시나리오 5 — 공식 원문이 두 영역을 직접 적는 카드.**

    숲의 파수꾼 그린 바분: 「①: **이 카드가 패 / 묘지에 존재하고**, 자신
    필드의 앞면 표시의 야수족 몬스터가 효과로 파괴되어 묘지로 보내졌을 때
    …」 — ``SetRange(LOCATION_HAND+LOCATION_GRAVE)`` 가 그 문장이다.

    둘 중 **하나만** 남기면 다른 쪽에 있는 카드가 조용히 후보에서 빠진다.
    """
    spec = one_spec(repository, MULTI_CARD)
    assert spec.activates_from == frozenset({Zone.GRAVE, Zone.HAND}), spec.to_dict()
    #: 🔴 이 효과는 **다른 카드**의 사건에 반응한다 (``FIELD`` 범위) — 그래서
    #: 주체가 미선언이고, 그것이 6-F 의 결론과 맞는다.
    assert spec.subject is None

    for where in (Zone.GRAVE, Zone.HAND):
        duel, [here] = board(repository, MULTI_CARD, where)
        view = duel.view(MINE)
        #: 사건의 주체는 **다른 인스턴스**다 (야수족이 묘지로 갔다).
        other = duel.state.create_instance(
            MULTI_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
        )
        event = move_event(other.instance_id, Zone.MZONE, Zone.GRAVE)
        candidate = next(
            c
            for c in TriggerCollector(view, TriggerRegistry((spec,)))
            .collect(event)
            .candidates
            if c.source == here
        )
        _eligibility, gate = zone_gate(view, spec, candidate, event)
        assert gate.validity is ActionValidity.VALID, (where, gate.result.reason)

    #: 선언에 없는 영역 — 거부.
    duel, [here] = board(repository, MULTI_CARD, Zone.MZONE)
    view = duel.view(MINE)
    event = move_event(InstanceId(999), Zone.MZONE, Zone.GRAVE)
    candidate = next(
        c
        for c in TriggerCollector(view, TriggerRegistry((spec,)))
        .collect(event)
        .candidates
        if c.source == here
    )
    _eligibility, gate = zone_gate(view, spec, candidate, event)
    assert gate.validity is ActionValidity.INVALID
    assert gate.code is ValidationCode.SOURCE_WRONG_ZONE


@requires_official_db
def test_03_the_corpus_keeps_every_multi_zone_declaration_whole(repository):
    """
    🔴 **전수 — 복수 영역 선언이 하나로 줄지 않았다** (§11-5).

    ``_zones_from`` 은 **전부-아니면-없음**이다. 일부만 옮기면 범위가 실제보다
    좁아지고, 좁은 범위는 그 밖의 카드를 조용히 뺀다.
    """
    analyzer = EffectAnalyzer(repository)
    multi = []
    widths = {}
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
            declared = result.spec.activates_from or result.spec.from_zones
            if declared is None:
                continue
            #: 🔴 옮긴 영역 수가 원문 이름 수와 **같다** — 하나도 잃지 않았다.
            assert len(declared) == len(set(effect.raw.ranges)), (
                card.id,
                ordinal,
                effect.raw.ranges,
            )
            widths[len(declared)] = widths.get(len(declared), 0) + 1
            if len(declared) > 1:
                multi.append((card.id, sorted(z.value for z in declared)))

    assert widths == {1: 790, 2: 26}, widths
    assert len(multi) == 26
    #: 실측된 네 가지 조합. 세 영역 이상은 corpus 에 없다.
    shapes = {tuple(z) for _card, z in multi}
    assert shapes == {
        ("GRAVE", "HAND"),
        ("GRAVE", "MZONE"),
        ("GRAVE", "SZONE"),
        ("HAND", "MZONE"),
    }, sorted(shapes)


# ======================================================================
# C. 시나리오 7 — 현재 영역과 직전 영역
# ======================================================================


@requires_official_db
def test_04_a_registration_range_outside_the_destination_becomes_a_previous_zone(
    repository,
):
    """
    🔴 **이 Phase 의 중심 단정 — 시나리오 7.**

    드로우 개구리: ``SetRange(LOCATION_MZONE)`` · ``EVENT_TO_GRAVE`` ·
    ``SINGLE``. 발동하는 순간 카드는 **묘지**이고 ``MZONE`` 은 등록 범위다.
    그 Lua 가 직접 ``c:IsPreviousLocation(LOCATION_ONFIELD)`` 를 쓴다.

    그래서 그 범위는 ``activates_from`` (지금) 이 아니라 ``from_zones``
    (직전) 로 간다.
    """
    spec = one_spec(repository, MOVED_CARD)
    assert spec.subject is TriggerSubject.SELF
    assert spec.point is TimingPoint.CARD_MOVED
    #: 🔴 직전 자리로 들어갔다.
    assert spec.from_zones == frozenset({Zone.MZONE})
    assert spec.to_zones == frozenset({Zone.GRAVE})
    #: 🔴 그리고 발동 위치는 **적지 않았다** — 카드가 간 곳을 적으면 관문이
    #: 항상 통과하는 동어반복이 된다.
    assert spec.activates_from is None

    #: 직전 자리가 **필터로** 일한다 — 패에서 묘지로 가는 이동은 안 잡는다.
    registry = TriggerRegistry((spec,))
    assert len(registry.watching(move_event(InstanceId(1), Zone.MZONE, Zone.GRAVE))) == 1
    assert registry.watching(move_event(InstanceId(1), Zone.HAND, Zone.GRAVE)) == ()
    assert registry.watching(move_event(InstanceId(1), Zone.DECK, Zone.GRAVE)) == ()


@requires_official_db
def test_05_the_false_negative_is_gone_on_a_real_board(repository):
    """
    🔴 **재현했던 거짓 양성의 반대 — 거짓 음성이 사라졌다.**

    6-G 이전에는 이 판에서 자리 관문이 **확정 거부**를 냈다::

        ACTIVATION_ZONE = invalid/source_wrong_zone
        "GRAVE 는 발동할 수 있는 자리가 아닙니다 (MZONE)."

    효과는 실제로 발동한다. ``UNKNOWN`` 이 아니라 **잘못된 확신**이었으므로
    더 나빴다. 지금은 모름이고, 🔴 **발동 가능으로 승격되지도 않는다.**
    """
    spec = one_spec(repository, MOVED_CARD)
    duel, [here] = board(repository, MOVED_CARD, Zone.MZONE)
    #: 실제 엔진으로 옮긴다 — 직전 상태가 기록된다.
    moved = duel.state.move(duel.state.find_instance(here), Zone.GRAVE)
    assert moved.zone is Zone.GRAVE
    assert moved.previous.location is Zone.MZONE

    event = move_event(here, Zone.MZONE, Zone.GRAVE)
    candidate, eligibility, gate = judge_at(duel, spec, event, here)

    #: 6-F 의 주체 판정은 통과한다 — 이 카드가 사건의 주체다.
    relation = eligibility.gate(EligibilityGate.EVENT_RELATION)
    assert relation.validity is ActionValidity.VALID
    assert candidate.status is TriggerStatus.ELIGIBLE

    #: 🔴 자리 관문은 **거부가 아니라 모름**이다.
    assert gate.validity is ActionValidity.UNKNOWN
    assert gate.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert gate.validity is not ActionValidity.INVALID

    #: 🔴 그래도 발동 가능이 아니다.
    assert eligibility.status is TriggerStatus.UNKNOWN
    assert eligibility.may_activate is False
    assert eligibility.fully_checked is False


def test_06_the_split_only_ever_turns_a_refusal_into_a_doubt():
    """
    🔴 **이 변환은 거짓 양성을 만들 수 없다** — 진리표로 잠근다.

    ``_split_range`` 가 범위를 ``from_zones`` 로 옮기는 것은 세 조건이 **모두**
    맞을 때뿐이고, 그때 ``activates_from`` 이 비므로 자리 관문은 ``VALID`` 가
    아니라 ``UNKNOWN`` 이 된다. 즉 바뀌는 방향이 하나다: **거부 → 모름.**
    """
    from engine.trigger_compiler import _split_range

    declared = frozenset({Zone.MZONE})
    grave = frozenset({Zone.GRAVE})
    mzone = frozenset({Zone.MZONE})

    table = {}
    for subject in (None, TriggerSubject.SELF, TriggerSubject.ANY):
        for point in (TimingPoint.CARD_MOVED, TimingPoint.CARD_DRAWN):
            for to_zones in (None, grave, mzone):
                table[(subject, point, to_zones)] = _split_range(
                    declared, subject=subject, point=point, to_zones=to_zones
                )

    moved = {key for key, (prev, _now) in table.items() if prev is not None}
    #: 🔴 옮기는 칸이 **정확히 하나**다.
    assert moved == {(TriggerSubject.SELF, TimingPoint.CARD_MOVED, grave)}, moved
    #: 그 칸에서 발동 위치는 비어 있다 (= 관문이 모름).
    assert table[(TriggerSubject.SELF, TimingPoint.CARD_MOVED, grave)] == (
        declared,
        None,
    )
    #: 나머지 전부는 **지금까지와 같다** — 범위가 곧 발동 위치다.
    for key, (prev, now) in table.items():
        if key in moved:
            continue
        assert (prev, now) == (None, declared), key
    #: 범위가 없으면 둘 다 없다 — 지어내지 않는다.
    assert _split_range(
        None, subject=TriggerSubject.SELF, point=TimingPoint.CARD_MOVED, to_zones=grave
    ) == (None, None)


@requires_official_db
def test_07_only_one_registration_in_the_whole_corpus_has_that_shape(repository):
    """
    🔴 **전수 — 그 모양은 1건이다** (§11-4 · §11-7).

    "기존 선언 중 잘못된 사례" 를 세는 것이 §11-7 이고, 답은 **816건 중
    1건**이다. 그 1건이 ``from_zones`` 로 옮겨졌으므로 발동 위치 선언은
    816 → **815** 가 된다.
    """
    analyzer = EffectAnalyzer(repository)
    total = with_range = moved = declared_now = 0
    movers = []
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
            total += 1
            if effect.raw.ranges:
                with_range += 1
            if result.spec.from_zones is not None:
                moved += 1
                movers.append(card.id)
            if result.spec.activates_from is not None:
                declared_now += 1

    assert total == 4173
    assert with_range == 816
    assert declared_now == 815
    assert moved == 1
    assert movers == [MOVED_CARD], movers
    #: 🔴 하나도 사라지지 않았다 — 옮긴 것과 남은 것의 합이 원래 수다.
    assert declared_now + moved == with_range


# ======================================================================
# D. 시나리오 8 · 9 — 인스턴스와 데이터 누락
# ======================================================================


@requires_official_db
def test_08_two_instances_of_one_card_in_different_zones_are_judged_apart(repository):
    """
    🔴 **시나리오 8 — 같은 카드 ID 두 장이 서로 다른 영역에 있다.**

    그린 바분은 「패 / 묘지」 에서 발동하므로, 필드에 있는 사본은 **거부**되고
    패·묘지의 사본은 통과한다. 카드 ID 가 같다는 이유로 섞이면 안 된다.
    """
    spec = one_spec(repository, MULTI_CARD)
    duel = Duel.start(
        repository=repository, decks=([MULTI_CARD] * 20, [MULTI_CARD] * 20), seed=4
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    placed = {
        zone: duel.state.create_instance(
            MULTI_CARD, owner=MINE, zone=zone, position=Position.FACEUP_ATTACK
        ).instance_id
        for zone in (Zone.GRAVE, Zone.HAND, Zone.MZONE)
    }
    assert len(set(placed.values())) == 3

    view = duel.view(MINE)
    event = move_event(InstanceId(900), Zone.MZONE, Zone.GRAVE)
    verdicts = {}
    for candidate in (
        TriggerCollector(view, TriggerRegistry((spec,))).collect(event).candidates
    ):
        _eligibility, gate = zone_gate(view, spec, candidate, event)
        verdicts[candidate.source] = gate.validity

    assert verdicts[placed[Zone.GRAVE]] is ActionValidity.VALID
    assert verdicts[placed[Zone.HAND]] is ActionValidity.VALID
    #: 🔴 같은 카드인데 필드의 사본만 거부된다.
    assert verdicts[placed[Zone.MZONE]] is ActionValidity.INVALID


@requires_official_db
def test_09_a_registration_without_a_range_stays_unknown(repository):
    """
    🔴 **시나리오 9 — ``SetRange`` 가 없으면 모른다.**

    없다는 이유로 "필드에서 발동" 을 넣지 않는다 (지시서 §6 오류 D).
    corpus 의 **3,358건**이 이 상태이고, 그것이 이 Phase 가 넓히지 못한
    부분이다.
    """
    spec = one_spec(repository, NO_RANGE_CARD)
    assert spec.activates_from is None
    assert spec.from_zones is None
    assert spec.subject is TriggerSubject.SELF  # 6-F 는 그대로 일한다

    duel, [here] = board(repository, NO_RANGE_CARD, Zone.MZONE)
    event = _matching_event(spec, here)
    candidate, eligibility, gate = judge_at(duel, spec, event, here)

    #: 주체는 통과하고 자리는 모른다.
    assert eligibility.gate(EligibilityGate.EVENT_RELATION).validity is (
        ActionValidity.VALID
    )
    assert gate.validity is ActionValidity.UNKNOWN
    assert gate.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "선언되지 않았습니다" in gate.result.reason
    assert candidate.status is TriggerStatus.ELIGIBLE  # 수집기는 자리를 안 본다
    #: 🔴 그래도 발동 가능이 아니다 — 자리를 모르기 때문이다.
    assert eligibility.may_activate is False


@requires_official_db
def test_10_a_hidden_card_is_unknown_for_a_different_reason(repository):
    """
    같은 ``UNKNOWN`` 이지만 까닭이 다르다 — 보이지 않는 카드는 **정보가
    없어서**이고 선언이 없는 것은 **규칙이 없어서**다 (3-E-27 의 규율).
    """
    spec = one_spec(repository, GRAVE_CARD)
    duel, [here] = board(repository, GRAVE_CARD, Zone.GRAVE)
    view = duel.view(MINE)
    event = _matching_event(spec, here)
    candidate = next(
        c
        for c in TriggerCollector(view, TriggerRegistry((spec,)))
        .collect(event)
        .candidates
        if c.source == here
    )

    #: 관측에 없는 인스턴스로 바꿔 묻는다 — 자리를 확인할 수 없다.
    import dataclasses

    unseen = dataclasses.replace(candidate, source=InstanceId(4242))
    _eligibility, gate = zone_gate(view, spec, unseen, event)
    assert gate.validity is ActionValidity.UNKNOWN
    assert gate.code is ValidationCode.HIDDEN_CARD
    assert gate.code is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# E. 시나리오 6 · 10 — 소환 성공과 기르수 회귀
# ======================================================================


@requires_official_db
def test_11_a_summon_subject_must_be_in_the_declared_zone(repository):
    """
    🔴 **시나리오 6 — 소환 성공 사건의 주체가 올바른 영역에 있는가.**

    레알 제넥스 마그나: 「①: 이 카드를 일반 소환했을 때에 발동할 수 있다」 ·
    ``SetRange(MZONE)``. 소환된 그 카드는 필드에 있으므로 통과하고, 같은
    카드가 묘지에 있는 사본은 **주체에서** 먼저 걸린다.
    """
    spec = one_spec(repository, FIELD_CARD)
    assert spec.subject is TriggerSubject.SELF
    assert spec.activates_from == frozenset({Zone.MZONE})
    #: 🔴 소환 시점에는 영역 축을 걸 수 없다 (3-F-5 ②) — 그대로다.
    assert spec.from_zones is None and spec.to_zones is None

    duel, [on_field] = board(repository, FIELD_CARD, Zone.MZONE)
    in_grave = duel.state.create_instance(
        FIELD_CARD, owner=MINE, zone=Zone.GRAVE, position=Position.FACEUP_ATTACK
    ).instance_id
    event = _matching_event(spec, on_field)

    candidate, eligibility, gate = judge_at(duel, spec, event, on_field)
    assert gate.validity is ActionValidity.VALID
    assert candidate.status is TriggerStatus.ELIGIBLE
    #: 🔴 자리와 주체를 **둘 다** 통과했는데도 발동 가능이 아니다.
    assert eligibility.may_activate is False
    assert {v.gate for v in eligibility.blocking} == {
        EligibilityGate.EXECUTION_AUTHORITY,
        EligibilityGate.COST_FEASIBILITY,
    }

    #: 묘지의 사본은 **주체**에서 막힌다 (6-F) — 자리까지 가지 않는다.
    other, other_eligibility, _other_gate = judge_at(duel, spec, event, in_grave)
    assert other.status is TriggerStatus.INELIGIBLE
    assert other.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert other_eligibility.may_activate is False


@requires_official_db
def test_12_girsu_regression_keeps_the_subject_verdict_and_stays_unknown(repository):
    """
    🔴 **시나리오 10 — 기르수 회귀.** 카드별 하드코딩은 없다.

    기르수의 두 등록에는 ``SetRange`` 가 **없다.** 그래서 자리는 모름으로
    남고, 6-F 의 주체 판정은 **한 글자도 바뀌지 않는다.**
    """
    specs = specs_of(repository, GIRSU)
    assert len(specs) == 2
    for spec in specs:
        assert spec.subject is TriggerSubject.SELF
        assert spec.activates_from is None
        assert spec.from_zones is None

    #: 6-F 와 같은 판 — 기르수를 두고 페더맨을 실제로 일반 소환한다.
    featherman = 21844576
    duel = Duel.start(
        repository=repository, decks=([featherman] * 20, [featherman] * 20), seed=5
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

    from engine.event_pipeline import EventPipeline

    registry = TriggerRegistry(tuple(specs))
    seen = 0
    for definitions in (None, definition_registry()):
        pipeline = EventPipeline(duel.view(MINE), registry, definitions)
        for journal_event in duel.journal.events:
            for observation in pipeline.collect(journal_event, actor=journal_event.actor):
                for candidate in observation.candidates:
                    seen += 1
                    #: 🔴 6-F 의 결론 그대로 — 주체가 다르므로 확정 거부.
                    assert candidate.status is TriggerStatus.INELIGIBLE
                    assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert seen == 2


# ======================================================================
# F. 회귀 — 6-F · Engine V1 · EventJournal
# ======================================================================


@requires_official_db
def test_13_the_subject_axis_is_untouched_across_the_corpus(repository):
    """
    🔴 **6-F 회귀 (전수)** — 주체 축의 수가 하나도 움직이지 않았다.

    위치 작업이 주체 판정을 건드렸다면 이 수가 바뀐다.
    """
    analyzer = EffectAnalyzer(repository)
    selves = unknown = 0
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
            if result.spec.subject is TriggerSubject.SELF:
                selves += 1
            else:
                unknown += 1
    #: 6-F 가 측정한 그 수 그대로다.
    assert (selves, unknown) == (3389, 784)


@requires_official_db
def test_14_judging_a_location_changes_neither_the_board_nor_the_journal(repository):
    """자리 판정이 **판도 기록도 난수도** 건드리지 않는다 (Engine V1 보존)."""
    spec = one_spec(repository, MOVED_CARD)
    duel, [here] = board(repository, MOVED_CARD, Zone.MZONE)
    duel.state.move(duel.state.find_instance(here), Zone.GRAVE)

    before_hash = duel.state.state_hash()
    before_rng = repr(duel.state.rng)
    before_events = [e.canonical_state() for e in duel.journal.events]

    event = move_event(here, Zone.MZONE, Zone.GRAVE)
    judge_at(duel, spec, event, here)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng
    assert [e.canonical_state() for e in duel.journal.events] == before_events


def test_15_the_unchecked_rules_and_the_gate_vocabulary_are_unchanged():
    """
    🔴 **미검증 규칙이 줄지 않았고 관문도 늘지 않았다** (§14 의 금지).

    자리를 보게 되었다고 타이밍 · 우선권 · 비용을 본 것이 아니다.
    """
    from engine.trigger import UNCHECKED_RULES

    assert len(UNCHECKED_RULES) == 6
    assert not any("자리" in rule for rule in UNCHECKED_RULES)
    #: 관문은 **다섯 개 그대로**다 — 새 관문을 만들지 않았다.
    assert [g.value for g in EligibilityGate] == [
        "event_relation",
        "activation_zone",
        "trigger_condition",
        "execution_authority",
        "cost_feasibility",
    ]
    #: 그리고 규칙 이름이 6-G 에 하나 있다 — 근거를 가리키는 문자열이다.
    assert "trigger-activation-location" in PREVIOUS_ZONE_RULE
