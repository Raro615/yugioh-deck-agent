"""
Phase 6-I — **실제 듀얼이 만든 사건을 기존 트리거 계층이 본다.**

6-H 까지 모든 연결이 시험 코드 안에서만 일어났다. 측정이 그것을 두 수로
적어 두었다 — ``TriggerRegistry(...)`` 를 만드는 production 자리 **0곳**,
``engine.event_pipeline`` 을 import 하는 production 파일 **0곳**. 부품은
전부 있고 조립도도 있는데 **펴는 사람이 없었다.**

6-I 가 그 사람을 만든다::

    Duel.start → legal_actions → apply(activate_effect)   ← 기존 실행 경로
        ↓  duel.journal.events                            ← 기존 기록 (6-B)
    integration.registry_for_view(view, repository)        ← 새 조립 자리
        ↓  TriggerRegistry
    engine.trigger_observation.TriggerObserver.observe
        ↓  EventPipeline → TriggerCollector → Judge        ← 기존 계층 그대로
    TriggerObservation — stage · 막힌 관문 · 미검사 규칙 · 정의/구현 유무

🔴 **지어낸 사건이 하나도 없다.** ``TimingEvent`` 를 손으로 만드는 자리가 이
파일에 없고 (``test_26`` 이 그것을 AST 로 고정한다), 모든 사건은
``Duel.apply`` 가 기록한 것에서 나온다. 6-I §16-6 이 요구한 그대로다.

지키는 것 여섯
--------------
1. **관찰이 판을 바꾸지 않는다** — 상태 · 체인 · 우선권 · 기록이 그대로다.
2. **없는 카드의 등록이 생기지 않는다** — 관측에 보이는 카드만 등록한다.
3. **가려진 카드의 정체가 새지 않는다** — 뒷면 카드는 등록하지 않는다.
4. **같은 카드 두 장을 구분한다** — 등록은 하나, 후보는 사본마다.
5. **거짓 승격이 없다** — 정의도 구현도 없으면 실행 가능이라고 말하지 않는다.
6. **등록을 주지 않아도 듀얼이 그대로 돈다** — 기존 호출이 한 글자도 안 바뀐다.
"""

import ast
import pathlib

import pytest

from engine.duel import Duel, TurnStep
from engine.effect.library import definition_registry, implementation_registry
from engine.ids import EffectRef
from engine.trigger import (
    EligibilityGate,
    TimingPoint,
    TriggerRegistry,
    TriggerStatus,
    TriggerSubject,
)
from engine.trigger_observation import (
    ObservationStage,
    TriggerObservation,
    TriggerObserver,
)
from engine.validation import ActionValidity
from engine.vocabulary import Phase, Position, Zone
from integration.trigger_registry import (
    CardTriggers,
    RegistryBuild,
    compiled_triggers,
    registry_for_view,
)

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: 엘리멘틀 히어로 페더맨 — **통상** 몬스터. 엔진이 실제로 일반 소환할 수
#: 있고 (``assess_normal_summon`` 이 ``ORDINARY``), Lua 스크립트가 없다.
FEATHERMAN = 21844576

#: 욕망의 항아리 — ``EFFECT_LIBRARY`` 에서 ``executable=True`` 이고
#: ``Duel.legal_actions`` 가 **실제로 발동 행동을 제시한다** (측정).
#: 그 해결이 뽑힌 장마다 ``CardDrawn`` 를 내므로, 트리거가 반응할 수 있는
#: 사건을 **합법적인 ``PlayerAction`` 으로** 만들 수 있다.
POT_OF_GREED = 55144522

#: 수호신관 마하드 — 공식 원문 「①: **이 카드를 드로우했을 때**, 이 카드를
#: 상대에게 보여주고 발동할 수 있다」. 등록이 ``SINGLE``(→ ``SELF``) ·
#: ``EVENT_DRAW``(→ ``card_drawn``) · ``SetRange(HAND)``(→ 발동 위치
#: ``HAND``) 라서 **6-F 의 주체 축과 6-G 의 위치 축이 동시에 답을 갖는다.**
DRAWN_TRIGGER_CARD = 71703785

#: DDD 질풍왕 알렉산더 — ``FIELD`` 등록이고 조건이 「이 카드 이외의」 다
#: (6-H 의 ``OTHER``). 다른 카드의 소환 사건에서 **모름**으로 남는다.
OTHER_SUMMON_CARD = 987311

#: 잭나이츠 오르페골 기르수 — 6-E 가 거짓 양성을 재현한 회귀 사례.
GIRSU = 69811710


# ======================================================================
# 도움 함수 — 전부 **실제** 듀얼을 지난다
# ======================================================================


def resolve_chain(duel: Duel) -> None:
    """
    열린 응답 창을 **합법적인 ``pass`` 행동으로** 닫아 체인을 해결한다.

    🔴 체인을 손으로 풀지 않는다. ``duel.legal_actions`` 가 내놓는 행동만
    쓰므로, 해결은 기존 ``ResponseLoop`` · ``ChainResolver`` 가 한다.
    """
    for _ in range(8):
        allowed = [
            action
            for action in duel.legal_actions(duel.to_act).allowed
            if action.kind.value == "pass"
        ]
        if not allowed:
            return
        step = duel.apply(allowed[0])
        assert step.accepted, step.reason


def observer_for(duel: Duel, repository, *, viewer: int = MINE, lookups: bool = True):
    """관측 → 등록소 → 관찰자. **보이는 카드에서** 등록을 꺼낸다."""
    view = duel.view(viewer)
    build = registry_for_view(view, repository)
    definitions = definition_registry() if lookups else None
    implementations = implementation_registry() if lookups else None
    return build, TriggerObserver(view, build.registry, definitions, implementations)


def snapshot(duel: Duel) -> tuple:
    """관찰이 바꿀 수 있는 것 전부. 바뀌면 이 튜플이 달라진다."""
    return (
        duel.state.state_hash(),
        len(duel.chain),
        duel.priority.describe_ko(),
        duel.step,
        tuple(record.canonical_state() for record in duel.journal.events),
    )


@pytest.fixture
def summoned_with_alexander(repository):
    """
    알렉산더를 필드에 두고 **페더맨을 실제로 일반 소환한** 듀얼.

    사건은 ``Duel.apply`` 가 기록한 것뿐이다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    alexander = duel.state.create_instance(
        OTHER_SUMMON_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in duel.legal_actions(MINE).allowed if a.kind.value == "normal_summon"
    )
    step = duel.apply(action)
    assert step.accepted, step.reason
    return duel, alexander.instance_id


@pytest.fixture
def drew_two_mahads(repository):
    """
    **욕망의 항아리를 실제로 발동·해결한** 듀얼. 덱 맨 위는 마하드다.

    이것이 6-I 의 수직 경로다 — 합법적인 ``PlayerAction`` 하나가 실제
    ``CardDrawn`` 사건 둘을 만든다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([POT_OF_GREED] + [DRAWN_TRIGGER_CARD] * 20, [DRAWN_TRIGGER_CARD] * 20),
        seed=11,
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    drawn = tuple(card.instance_id for card in duel.state.player(MINE).deck[:2])
    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind.value == "activate_effect"
    )
    assert action.effect_ref == EffectRef(POT_OF_GREED, 0)
    step = duel.apply(action)
    assert step.accepted, step.reason
    resolve_chain(duel)
    #: 뽑힌 두 장이 **실제로 패에 왔다.**
    hand = {card.instance_id for card in duel.state.player(MINE).hand}
    assert set(drawn) <= hand, (drawn, hand)
    return duel, drawn


# ======================================================================
# 식별 — EffectDefinition 과 TriggerSpec 이 같은 이름을 쓴다 (§5)
# ======================================================================


def test_01_both_layers_are_keyed_by_the_same_identifier():
    """
    🔴 **식별 문제가 없다는 것이 §5 의 답이다.**

    ``EffectDefinition.effect_ref`` 와 ``TriggerSpec.effect_ref`` 는 **같은
    타입**(``EffectRef(card_id, ordinal)``) 이고, 정의 저장소도 그 키로
    조회한다. 그래서 "여러 후보가 남는" 모호성 문제가 애초에 없다 — 두
    집합이 **서로소**인 것이 문제다 (``test_03``).

    카드 ID 만으로 연결하면 안 되는 이유도 같은 자리에 있다: ``ordinal``
    없이는 한 카드의 서로 다른 효과를 가릴 수 없다.
    """
    from dataclasses import fields

    from engine.effect.definition import EffectDefinition
    from engine.trigger import TriggerSpec

    definition_key = next(f for f in fields(EffectDefinition) if f.name == "effect_ref")
    spec_key = next(f for f in fields(TriggerSpec) if f.name == "effect_ref")
    assert definition_key.type == spec_key.type == "EffectRef"

    #: ``EffectRef`` 는 **두 값**으로 식별한다 — 카드 하나가 아니다.
    assert [f.name for f in fields(EffectRef)] == ["card_id", "ordinal"]
    assert EffectRef(1, 0) != EffectRef(1, 1)


@requires_official_db
def test_02_the_ordinal_is_the_place_in_the_script_not_the_enumerate_index(repository):
    """
    🔴 **순번을 세지 않고 자리를 찾는다** (§5 의 "등록 순서 추정 금지").

    ``analysis.effects`` 는 ``initial_effect`` 에서 만들어진 블록만 담으므로
    ``card.script.effects`` 보다 짧을 수 있다. 그때 ``enumerate`` 의 순번을
    ``ordinal`` 로 쓰면 **다른 블록의 선언**이 된다.

    실측: 전 corpus 12,472장에서 두 값이 어긋나는 카드는 **0장**이다 (등록
    효과가 언제나 앞에 모여 있다). 그래도 production 은 자리를 직접 찾고,
    이 테스트는 **찾은 자리가 원본의 자리와 같다**는 것을 확인한다 — 0건이
    계약이 아니라 지금 데이터의 성질이기 때문이다.
    """
    card = repository.get(DRAWN_TRIGGER_CARD)
    assert card is not None and card.script is not None
    blocks = card.script.effects
    found = compiled_triggers(repository, DRAWN_TRIGGER_CARD)
    assert isinstance(found, CardTriggers)
    assert found.unplaceable == 0

    for compilation in found.compilations:
        ordinal = compilation.spec.effect_ref.ordinal if compilation.is_registered else None
        if ordinal is None:
            continue
        assert 0 <= ordinal < len(blocks)
        #: 그 자리의 블록이 **정말 그 선언의 출처**다.
        assert blocks[ordinal].code == compilation.event_code


@requires_official_db
def test_03_no_compiled_trigger_has_a_definition_today(repository):
    """
    **§5 · §9 의 측정값** — 연결 성공 **0건**, 모호 **0건**.

    ``EFFECT_LIBRARY`` 16건은 전부 마법의 ``ACTIVATE`` 효과이고 (``ordinal``
    이 모두 0 인 **블록 하나짜리** 카드다), 트리거 등록이 하나도 없다. 그래서
    실패 이유가 "식별이 모호하다" 가 아니라 **"정의가 없다"** 다. 그 둘을
    섞으면 다음 단계가 엉뚱한 곳을 고치게 된다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    definitions = definition_registry()
    assert len(definitions) == len(EFFECT_LIBRARY) == 16
    assert {entry.effect_ref.ordinal for entry in EFFECT_LIBRARY} == {0}

    for entry in EFFECT_LIBRARY:
        found = compiled_triggers(repository, entry.card_id)
        registered = [c for c in found.compilations if c.is_registered]
        assert registered == [], (entry.card_id, registered)


# ======================================================================
# A. 실제 Duel 행동 발생 (§10-A)
# ======================================================================


@requires_official_db
def test_04_a_real_action_changes_the_board_and_leaves_a_record(repository):
    """
    **시나리오 A** — 기존 엔진이 이미 지원하는 행동을 실제로 실행한다.

    행동 승인 · 판 변경 · 사건 생성 · 기록의 기존 의미론을 **따로** 확인한다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    before_hash = duel.state.state_hash()
    before_records = len(duel.journal.events)

    action = next(
        a for a in duel.legal_actions(MINE).allowed if a.kind.value == "normal_summon"
    )
    step = duel.apply(action)

    assert step.accepted, step.reason
    assert duel.state.state_hash() != before_hash
    assert len(duel.journal.events) == before_records + 1
    record = duel.journal.events[-1]
    #: 기록의 기존 의미론 — 누가 했고 어떤 변화가 났는지 그대로 들고 있다.
    assert record.actor == MINE
    assert record.deltas
    assert record.changed_state is True


# ======================================================================
# B. 등록 조회 (§10-B)
# ======================================================================


@requires_official_db
def test_05_the_registry_comes_from_the_cards_that_are_actually_there(
    repository, summoned_with_alexander
):
    """
    **시나리오 B** — 등록은 **관측에 보이는 카드**에서만 나온다.

    페더맨은 Lua 스크립트가 없으므로 등록이 없고 (``no_script``), 덱의
    카드는 ``visible_instances`` 에 들어오지 않으므로 아예 후보가 아니다.
    """
    duel, _alexander = summoned_with_alexander
    build, _observer = observer_for(duel, repository)

    assert isinstance(build, RegistryBuild)
    assert build.card_ids == (OTHER_SUMMON_CARD,)
    assert build.registered >= 1
    assert build.no_script >= 1
    assert build.unplaceable == 0

    #: 🔴 **다른 카드의 등록이 섞이지 않는다.** 등록된 선언의 카드 ID 가
    #: 전부 보이는 카드의 것이다.
    for spec in build.registry.specs:
        assert spec.effect_ref.card_id in build.card_ids

    #: 덱에만 있는 카드는 등록되지 않는다.
    assert FEATHERMAN not in build.card_ids


@requires_official_db
def test_06_a_card_in_the_deck_alone_gets_no_registration(repository):
    """
    **§6-6** — 판에 **없는** 카드의 효과가 근거 없이 등록되지 않는다.

    마하드 20장이 덱에만 있는 판에서, 패에 온 것만 등록된다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([DRAWN_TRIGGER_CARD] * 20, [FEATHERMAN] * 20),
        seed=3,
    )
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    #: 패에 마하드가 왔으므로 등록은 생긴다 — 그러나 **덱의 20장 때문에**
    #: 등록이 20배가 되지는 않는다. 등록은 **정의별**이다.
    assert build.card_ids == (DRAWN_TRIGGER_CARD,)
    assert len({spec.effect_ref for spec in build.registry.specs}) == build.registered

    #: 상대 덱의 페더맨은 보이지 않는다.
    assert FEATHERMAN not in build.card_ids


@requires_official_db
def test_07_a_face_down_card_is_counted_but_never_registered(repository):
    """
    🔴 **§6-7 · §12 — 가려진 카드의 정체가 새지 않는다.**

    뒷면 카드의 ``CardView`` 는 ``card_id`` 를 주지 않는다 (실측: 유출
    0건). 그 카드는 ``concealed`` 로 **세고** 등록하지 않는다 — 등록하면 그
    사실만으로 상대가 무엇을 놓았는지 알려 주게 된다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=7
    )
    duel.state.create_instance(
        OTHER_SUMMON_CARD,
        owner=THEIRS,
        zone=Zone.MZONE,
        position=Position.FACEDOWN_DEFENSE,
    )
    duel.state.turn.set_phase(Phase.MAIN1)

    mine = registry_for_view(duel.view(MINE), repository)
    assert mine.concealed >= 1
    assert OTHER_SUMMON_CARD not in mine.card_ids
    assert mine.registered == 0

    #: 소유자에게는 보이고, 그래서 등록된다 — 같은 판 다른 관측이다.
    theirs = registry_for_view(duel.view(THEIRS), repository)
    assert OTHER_SUMMON_CARD in theirs.card_ids
    assert theirs.registered >= 1

    #: 🔴 관측 자체가 ``card_id`` 를 가린다는 것을 함께 고정한다.
    for instance in duel.view(MINE).visible_instances():
        card = duel.view(MINE).find(instance)
        if card is not None and not card.is_identified:
            assert card.card_id is None


# ======================================================================
# C. 후보 판정 (§10-C)
# ======================================================================


@requires_official_db
def test_08_a_real_summon_produces_a_judged_candidate(
    repository, summoned_with_alexander
):
    """
    **시나리오 C** — 실제 사건에서 후보가 나오고 기존 판정기가 판정한다.

    알렉산더는 ``OTHER`` 선언이므로 **다른 카드**의 소환에서 사건 관계가
    ``UNKNOWN`` 이다 (6-H 의 ``GROUP_MEMBERSHIP_RULE``). 위치 관문은
    통과한다 (원문 「몬스터 존에 존재하고」).
    """
    duel, alexander = summoned_with_alexander
    _build, observer = observer_for(duel, repository)
    observations = observer.observe_all(duel.journal.events)

    assert observations, "실제 사건에서 후보가 하나도 나오지 않았습니다"
    for observation in observations:
        assert isinstance(observation, TriggerObservation)
        assert observation.candidate.source == alexander
        assert observation.event.point is TimingPoint.MONSTER_SUMMONED
        relation = observation.eligibility.gate(EligibilityGate.EVENT_RELATION)
        assert relation.result.validity is ActionValidity.UNKNOWN
        zone = observation.eligibility.gate(EligibilityGate.ACTIVATION_ZONE)
        assert zone.result.validity is ActionValidity.VALID
        #: 🔴 **부분 통과는 승격이 아니다.**
        assert observation.stage is ObservationStage.EVENT_UNDECIDED
        assert observation.eligibility.status is not TriggerStatus.ELIGIBLE


@requires_official_db
def test_09_the_vertical_path_passes_both_axes_on_a_real_drawn_card(
    repository, drew_two_mahads
):
    """
    🔴 **6-I 의 수직 경로** — 합법적인 ``PlayerAction`` 하나(욕망의 항아리
    발동)가 실제 ``CardDrawn`` 사건을 만들고, 그 사건에서 **6-F 의 주체 축과
    6-G 의 위치 축이 동시에 통과한다.**

    지어낸 delta 가 없다. 발동도 해결도 ``duel.legal_actions`` 가 내놓은
    행동으로만 했다.
    """
    duel, drawn = drew_two_mahads
    _build, observer = observer_for(duel, repository)
    observations = observer.observe_all(duel.journal.events)

    drew = [o for o in observations if o.event.point is TimingPoint.CARD_DRAWN]
    assert drew, "드로우 사건이 관찰되지 않았습니다"

    #: 자기 자신이 뽑힌 사건에서의 관찰만 고른다.
    own = [o for o in drew if o.event.instance == o.candidate.source]
    assert {o.candidate.source for o in own} == set(drawn)

    for observation in own:
        gates = {
            verdict.gate: verdict.result.validity
            for verdict in observation.eligibility.gates
        }
        assert gates[EligibilityGate.EVENT_RELATION] is ActionValidity.VALID
        assert gates[EligibilityGate.ACTIVATION_ZONE] is ActionValidity.VALID
        #: 남은 셋이 **다음 단계를 가리킨다.**
        assert gates[EligibilityGate.TRIGGER_CONDITION] is ActionValidity.UNKNOWN
        assert gates[EligibilityGate.EXECUTION_AUTHORITY] is ActionValidity.UNKNOWN
        assert gates[EligibilityGate.COST_FEASIBILITY] is ActionValidity.UNKNOWN
        assert observation.stage is ObservationStage.JUDGEMENT_PENDING
        assert observation.eligibility.status is TriggerStatus.UNKNOWN
        #: 🔴 미검사 규칙을 **숨기지 않는다.**
        assert observation.unchecked_rules


# ======================================================================
# D. 같은 카드 복수 인스턴스 (§10-D)
# ======================================================================


@requires_official_db
def test_10_only_the_instance_in_the_event_is_accepted(repository, drew_two_mahads):
    """
    **시나리오 D** — 같은 카드 ID 가 여섯 장 보이는데, 각 드로우 사건에서
    **뽑힌 그 한 장만** 사건 관계를 통과한다.

    🔴 등록은 **하나**이고 (정의별), 후보는 **사본마다** 생긴다. 그 구분이
    흐려지면 등록이 복제되어 후보가 중복된다.
    """
    duel, drawn = drew_two_mahads
    build, observer = observer_for(duel, repository)

    #: 같은 카드가 여러 장 보여도 등록은 중복되지 않는다.
    refs = [spec.effect_ref for spec in build.registry.specs]
    assert len(refs) == len(set(refs))

    drew = [
        o
        for o in observer.observe_all(duel.journal.events)
        if o.event.point is TimingPoint.CARD_DRAWN
    ]
    by_event: dict = {}
    for observation in drew:
        by_event.setdefault(observation.event.instance, []).append(observation)

    assert set(by_event) == set(drawn)
    for instance, group in by_event.items():
        passed = [o for o in group if o.candidate.source == instance]
        refused = [o for o in group if o.candidate.source != instance]
        assert len(passed) == 1
        assert passed[0].stage is ObservationStage.JUDGEMENT_PENDING
        assert refused, "다른 사본이 후보로 수집되지 않았습니다"
        for other in refused:
            assert other.stage is ObservationStage.REFUSED
            assert other.candidate.status is TriggerStatus.INELIGIBLE


# ======================================================================
# E. 부적합 사건 (§10-E)
# ======================================================================


@requires_official_db
def test_11_a_different_kind_of_event_produces_no_candidate(repository):
    """
    **시나리오 E** — 마하드의 등록은 ``card_drawn`` 뿐이다. 소환 사건에서는
    후보가 **하나도** 나오지 않는다.

    🔴 "후보가 0건" 이 "등록이 0건" 때문이 아니라는 것을 함께 확인한다 —
    등록은 있고, 사건이 다르다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        seed=5,
    )
    duel.state.create_instance(
        DRAWN_TRIGGER_CARD, owner=MINE, zone=Zone.HAND
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in duel.legal_actions(MINE).allowed if a.kind.value == "normal_summon"
    )
    assert duel.apply(action).accepted

    build, observer = observer_for(duel, repository)
    assert build.registered >= 1
    points = {spec.point for spec in build.registry.specs}
    assert TimingPoint.CARD_DRAWN in points

    observations = observer.observe_all(duel.journal.events)
    assert [o for o in observations if o.event.point is TimingPoint.MONSTER_SUMMONED] == []


@requires_official_db
def test_12_girsu_is_not_promoted_by_another_cards_summon(repository):
    """
    **회귀 — 6-E 가 재현한 거짓 양성** (§11 이 유지하라고 한 사례).

    기르수는 ``SINGLE`` 등록이라 ``SELF`` 다. 페더맨의 소환에서 사건 관계가
    **확정 거부**이고, 그래서 ``REFUSED`` 다.

    🔴 기르수의 일반 소환이 ``UNDETERMINED`` 인 것을 **우회하지 않았다** —
    기르수를 소환하는 대신 필드에 두고, 소환되는 쪽은 엔진이 실제로 소환할 수
    있는 페더맨이다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    girsu = duel.state.create_instance(
        GIRSU, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in duel.legal_actions(MINE).allowed if a.kind.value == "normal_summon"
    )
    assert duel.apply(action).accepted

    _build, observer = observer_for(duel, repository)
    observations = observer.observe_all(duel.journal.events)
    assert observations
    for observation in observations:
        assert observation.candidate.source == girsu.instance_id
        assert observation.stage is ObservationStage.REFUSED
        assert observation.candidate.status is TriggerStatus.INELIGIBLE


# ======================================================================
# F. 실행 구현이 없는 효과 (§10-F · §9)
# ======================================================================


@requires_official_db
def test_13_a_candidate_without_a_definition_is_never_execution_ready(
    repository, drew_two_mahads
):
    """
    **시나리오 F** — 분석 후보는 유지하되 **실행 가능이라고 말하지 않는다.**

    정의도 구현도 없으므로 ``has_definition`` · ``is_executable`` 이 둘 다
    거짓이고, 그 상태에서는 ``EXECUTION_READY`` 가 나올 수 없다.
    """
    duel, _drawn = drew_two_mahads
    _build, observer = observer_for(duel, repository)
    observations = observer.observe_all(duel.journal.events)
    assert observations

    for observation in observations:
        assert observation.has_definition is False
        assert observation.is_executable is False
        assert observation.stage is not ObservationStage.EXECUTION_READY
        assert observation.eligibility.status is not TriggerStatus.ELIGIBLE
        #: 🔴 **후보가 사라지지도 않는다** — 연결 실패가 분석 결과를 지우지
        #: 않는다 (§5 의 마지막 금지).
        assert observation.effect_ref.card_id == DRAWN_TRIGGER_CARD


@requires_official_db
def test_14_no_observation_can_reach_execution_ready_today(
    repository, drew_two_mahads, summoned_with_alexander
):
    """
    🔴 **``EXECUTION_READY`` 는 지금 도달할 수 없다** (§8-E · §18-6).

    도달하려면 **다섯 관문 통과 + 미검사 규칙 없음 + 정의 + 구현** 이 모두
    참이어야 한다. 그중 "미검사 규칙 없음" 은 ``UNCHECKED_RULES`` 가 비어야
    참이고, 지금은 여섯 개가 들어 있다.

    도달할 수 없는 칸을 **값으로 적어 두는** 이유: 비워 두면 "실행 가능" 과
    "아직 모른다" 가 같은 값이 된다.
    """
    from engine.trigger import UNCHECKED_RULES

    assert len(UNCHECKED_RULES) == 6

    seen = 0
    for duel, _ in (drew_two_mahads, summoned_with_alexander):
        _build, observer = observer_for(duel, repository)
        for observation in observer.observe_all(duel.journal.events):
            seen += 1
            assert observation.stage is not ObservationStage.EXECUTION_READY
            assert observation.eligibility.fully_checked is False
    assert seen > 0


def test_15_the_stage_ladder_demands_every_condition_at_once():
    """
    🔴 **사다리의 마지막 칸이 **모든** 조건을 요구한다.**

    관문 결과를 그대로 두고 ``has_definition`` · ``is_executable`` 만 바꿔서
    같은 판정이 **다른 칸**으로 가는 것을 본다 — 한 조건만 빠져도
    ``EXECUTION_READY`` 가 아니다.
    """
    from engine.trigger_observation import _stage_of

    class _FakeVerdict:
        def __init__(self, gate, validity):
            self.gate = gate
            self.result = type("R", (), {"validity": validity})()
            self.passed = validity is ActionValidity.VALID

    class _FakeEligibility:
        def __init__(self, *, status, unchecked, relation=ActionValidity.VALID):
            self.status = status
            self.unchecked_rules = unchecked
            self._gates = (_FakeVerdict(EligibilityGate.EVENT_RELATION, relation),)

        @property
        def gates(self):
            return self._gates

        @property
        def fully_checked(self):
            return not self.unchecked_rules

        def gate(self, gate):
            return next((v for v in self._gates if v.gate is gate), None)

    clean = _FakeEligibility(status=TriggerStatus.ELIGIBLE, unchecked=())
    assert (
        _stage_of(clean, has_definition=True, is_executable=True)
        is ObservationStage.EXECUTION_READY
    )
    #: 구현이 없으면 아니다.
    assert (
        _stage_of(clean, has_definition=True, is_executable=False)
        is ObservationStage.RULES_SATISFIED
    )
    #: 정의가 없으면 아니다.
    assert (
        _stage_of(clean, has_definition=False, is_executable=True)
        is ObservationStage.RULES_SATISFIED
    )
    #: 미검사 규칙이 남아 있으면 아니다.
    pending = _FakeEligibility(status=TriggerStatus.ELIGIBLE, unchecked=("타이밍",))
    assert (
        _stage_of(pending, has_definition=True, is_executable=True)
        is ObservationStage.RULES_SATISFIED
    )
    #: 사건 관계부터 모르면 뒤를 보지 않는다.
    undecided = _FakeEligibility(
        status=TriggerStatus.UNKNOWN,
        unchecked=(),
        relation=ActionValidity.UNKNOWN,
    )
    assert (
        _stage_of(undecided, has_definition=True, is_executable=True)
        is ObservationStage.EVENT_UNDECIDED
    )
    #: 거부가 가장 앞이다.
    refused = _FakeEligibility(status=TriggerStatus.INELIGIBLE, unchecked=())
    assert (
        _stage_of(refused, has_definition=True, is_executable=True)
        is ObservationStage.REFUSED
    )


def test_16_an_implementation_without_a_definition_is_not_executable():
    """
    🔴 **정의 없이 "실행 가능" 이라고 말하지 않는다** (ADR-006).

    구현 목록에만 이름이 있고 정의가 없으면 **무엇을 실행할지 모르는**
    상태다. 그 상태를 실행 가능으로 적으면 §18-6 이 금지한 거짓 표시다.
    """
    from engine.effect.executor import EffectImplementationRegistry
    from engine.game_state_view import GameStateView
    from engine.state.game_state import GameState

    state = GameState.create(None, decks=([], []))
    view = GameStateView.from_state(state, viewer=MINE)
    ghost = EffectRef(1, 0)
    observer = TriggerObserver(
        view,
        TriggerRegistry(),
        definition_registry(),
        EffectImplementationRegistry((ghost,)),
    )
    assert observer._is_executable(ghost) is False
    #: 정의가 있는 쪽은 참이다 — 대조군이다.
    real = next(iter(definition_registry()._definitions))
    observer_real = TriggerObserver(
        view,
        TriggerRegistry(),
        definition_registry(),
        EffectImplementationRegistry((real,)),
    )
    assert observer_real._is_executable(real) is True


# ======================================================================
# G. 등록 정보 미제공 (§10-G)
# ======================================================================


@requires_official_db
def test_17_a_duel_that_knows_nothing_about_triggers_still_runs(repository):
    """
    **시나리오 G** — 기존 호출자가 등록 데이터를 주지 않아도 듀얼이 그대로
    돈다. ``Duel`` 의 생성자도 호출 계약도 **한 글자 바뀌지 않았다.**

    🔴 그것이 구조로 참인 이유: 등록소는 ``Duel`` 밖에 있고, 듀얼은 그것의
    존재를 모른다 (``duel.py`` 에 ``trigger`` 라는 말이 없음을
    ``test_trigger_pipeline_dormant_audit::test_12`` 가 고정한다).
    """
    plain = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    plain.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in plain.legal_actions(MINE).allowed if a.kind.value == "normal_summon"
    )
    step = plain.apply(action)
    assert step.accepted

    #: 등록소를 **만든** 쪽과 결과가 같다.
    observed = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    observed.state.turn.set_phase(Phase.MAIN1)
    same = next(
        a
        for a in observed.legal_actions(MINE).allowed
        if a.kind.value == "normal_summon"
    )
    assert observed.apply(same).accepted
    _build, observer = observer_for(observed, repository)
    observer.observe_all(observed.journal.events)

    assert plain.state.state_hash() == observed.state.state_hash()


@requires_official_db
def test_18_observing_changes_nothing_at_all(repository, drew_two_mahads):
    """
    🔴 **§17-14 · §18-7 — 관찰 전후로 아무것도 바뀌지 않는다.**

    판 · 체인 · 우선권 · 흐름의 위치 · 기록 전부를 한 튜플로 찍어 비교한다.
    하나만 봐도 다른 하나가 바뀐 것을 못 본다.
    """
    duel, _drawn = drew_two_mahads
    before = snapshot(duel)
    _build, observer = observer_for(duel, repository)
    observations = observer.observe_all(duel.journal.events)
    assert observations
    #: 두 번 관찰해도 같다 — 관찰에 누적 상태가 없다.
    observer.observe_all(duel.journal.events)
    assert snapshot(duel) == before


# ======================================================================
# H. 복수 듀얼 격리 (§10-H)
# ======================================================================


@requires_official_db
def test_19_two_duels_do_not_share_registrations_or_candidates(repository):
    """
    **시나리오 H** — 서로 다른 듀얼의 등록과 후보가 섞이지 않는다.

    한쪽에만 알렉산더를 두고 양쪽에서 같은 행동을 한다. 등록소도 관찰도
    듀얼마다 따로다.
    """
    duels = []
    for with_alexander in (True, False):
        duel = Duel.start(
            repository=repository,
            decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
            seed=5,
        )
        if with_alexander:
            duel.state.create_instance(
                OTHER_SUMMON_CARD,
                owner=MINE,
                zone=Zone.MZONE,
                position=Position.FACEUP_ATTACK,
            )
        duel.state.turn.set_phase(Phase.MAIN1)
        action = next(
            a
            for a in duel.legal_actions(MINE).allowed
            if a.kind.value == "normal_summon"
        )
        assert duel.apply(action).accepted
        duels.append(duel)

    rich, poor = duels
    rich_build, rich_observer = observer_for(rich, repository)
    poor_build, poor_observer = observer_for(poor, repository)

    assert rich_build.card_ids == (OTHER_SUMMON_CARD,)
    assert poor_build.card_ids == ()
    assert rich_build.registry is not poor_build.registry
    assert poor_build.registered == 0

    assert rich_observer.observe_all(rich.journal.events)
    assert poor_observer.observe_all(poor.journal.events) == ()


# ======================================================================
# 구조 — 이 파일이 지어낸 사건을 쓰지 않는다
# ======================================================================


def test_20_this_file_never_builds_an_event_by_hand():
    """
    🔴 **§16-6 을 이 파일 자신에 대해 고정한다.**

    ``TimingEvent`` 를 손으로 만들거나 delta 를 직접 지어내는 자리가 **없다.**
    모든 사건은 ``Duel.apply`` 가 기록한 것에서 나온다. 이 단정이 깨지면 이
    파일이 주장하는 "수직 통합" 이 더 이상 수직이 아니다.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    built = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = {
        "TimingEvent",
        "MonsterSummoned",
        "CardDrawn",
        "CardMoved",
        "LifeChanged",
        "ZoneMoved",
    }
    assert built & forbidden == set(), built & forbidden

    #: ``from_delta`` 같은 우회도 막는다.
    attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "from_delta" not in attrs
    assert "from_journal_event" not in attrs

    #: 🔴 그리고 **실제 행동**을 쓴다는 증거: ``duel.apply`` 를 부른다.
    assert "apply" in attrs
    assert "legal_actions" in attrs


def test_21_the_observer_cannot_change_the_board_by_construction():
    """
    🔴 **관찰 모듈이 판을 바꿀 손을 갖고 있지 않다.**

    ``engine/trigger_observation.py`` 가 상태를 바꾸는 이름을 **하나도**
    부르지 않는다. "바꾸지 않는다" 를 시험으로만 보이면 시험하지 않은 경로가
    남지만, 호출이 없으면 경로 자체가 없다.
    """
    source = (PROJECT_ROOT / "engine" / "trigger_observation.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    mutating = {
        "apply",
        "advance",
        "move",
        "draw",
        "create_instance",
        "register",
        "record",
        "set_phase",
        "set_result",
        "push",
        "resolve",
        "resolve_top",
        "resolve_all",
    }
    assert attrs & mutating == set(), attrs & mutating


def test_22_the_observation_module_borrows_nothing_from_analysis():
    """
    🔴 **ADR-007 을 새 모듈에 대해서도 확인한다.**

    ``engine/trigger_observation.py`` 는 ``analysis`` 를 import 하지 않는다 —
    카드 데이터의 모양을 아는 일은 ``integration`` 이 한다. 그 분리가
    이 Phase 가 ``engine`` 안에 조립 자리를 두지 않은 이유다.
    """
    source = (PROJECT_ROOT / "engine" / "trigger_observation.py").read_text(
        encoding="utf-8"
    )
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("analysis"), node.module
            assert not node.module.startswith("integration"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("analysis"), alias.name

    #: 반대로 ``integration`` 은 세 층을 전부 가져간다 — 그것이 그 층의 일이다.
    assembler = (PROJECT_ROOT / "integration" / "trigger_registry.py").read_text(
        encoding="utf-8"
    )
    modules = {
        node.module
        for node in ast.walk(ast.parse(assembler))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any(m.startswith("analysis") for m in modules)
    assert any(m.startswith("engine") for m in modules)


# ======================================================================
# 전수 — §5 의 식별 가정과 §17-8 의 교차표
# ======================================================================


@requires_official_db
def test_23_the_registered_effects_are_a_prefix_of_the_script_blocks(repository):
    """
    🔴 **전수 — ``analysis.effects`` 의 순번이 블록의 자리와 같다.**

    production 은 이 성질에 **기대지 않고** 자리를 직접 찾는다
    (``compiled_triggers``). 이 테스트는 그 성질이 **지금 참**이라는 것을
    기록한다 — 참인 동안은 6-E~6-H 의 측정값이 유효하고, 깨지는 날 그
    Phase 들의 ``ordinal`` 을 다시 봐야 한다는 신호가 된다.

    0건인 까닭: ``initial_effect`` 가 파일의 첫 함수이므로 그 안에서 만든
    블록의 offset 이 가장 작고, 등록 효과가 언제나 앞에 모인다. **규약이고
    문법이 아니다** — 그래서 핀을 둔다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    cards = mismatched = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        analysis = analyzer.analyze(card)
        if not analysis.effects:
            continue
        cards += 1
        place = {id(spec): index for index, spec in enumerate(card.script.effects)}
        for position, effect in enumerate(analysis.effects):
            if place.get(id(effect.raw)) != position:
                mismatched += 1

    assert cards == 12472
    assert mismatched == 0


@requires_official_db
def test_24_the_whole_corpus_has_no_trigger_with_an_executable_definition(repository):
    """
    **§17-8 의 교차표** — 전수로 한 번 센다.

    ======================================  =====
     컴파일된 TRIGGER 등록                   4,173
     그중 ``EffectDefinition`` 이 있는 것        0
     그중 실행 구현까지 있는 것                  0
     ``EffectDefinition`` 중 TRIGGER 인 것       0
    ======================================  =====

    🔴 **0 이 세 번 나오는데 까닭이 하나다** — 두 집합이 서로소다. 식별이
    모호한 것이 아니므로 (``test_01``) 다음 단계가 고칠 곳은 식별 체계가
    아니라 **정의 목록**이다 (§16).
    """
    from analysis.effect_analyzer import EffectAnalyzer

    analyzer = EffectAnalyzer(repository)
    definitions = definition_registry()
    implementations = implementation_registry()

    registered = 0
    with_definition = 0
    with_implementation = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        for compilation in compiled_triggers(
            repository, card.id, analyzer=analyzer
        ).compilations:
            if not compilation.is_registered:
                continue
            registered += 1
            ref = compilation.spec.effect_ref
            if definitions.definition_for(ref) is not None:
                with_definition += 1
                if implementations.has_implementation(ref):
                    with_implementation += 1

    assert registered == 4173
    assert with_definition == 0
    assert with_implementation == 0


# ======================================================================
# 식별 — 자리를 찾는 코드를 직접 겨눈다
# ======================================================================
#
# 🔴 **왜 이 두 테스트가 따로 필요했는가.**
#
# 변이 테스트에서 둘이 **살아남았다** — "블록의 자리를 ``enumerate`` 순번으로
# 추정한다" 와 "자리를 못 찾으면 0 으로 지어낸다". 둘 다 실제 카드에서는
# 티가 나지 않는다: 전 corpus 에서 등록 효과가 언제나 블록의 앞쪽에 모여
# 있고 (``test_23``) 자리를 못 찾는 경우가 0건이기 때문이다.
#
# 즉 **지금 데이터로는 그 코드가 틀렸는지 알 수 없다.** 그래서 데이터가
# 그렇지 않은 모양을 직접 만들어 함수에 넣는다. 사건을 지어내는 것이 아니라
# (§16-6 은 **사건**을 지어내지 말라는 것이다) 순수한 자리 찾기 함수에
# 입력을 주는 것이고, 입력은 실제 ``EffectSpec`` · ``LuaScriptInfo`` 다.


class _AnalyzerStub:
    """``analyze(card)`` 만 흉내 내는 최소 대역. 정해 준 효과를 그대로 준다."""

    def __init__(self, effects):
        self._effects = effects

    def analyze(self, card):
        from analysis.effect_model import CardAnalysis

        analysis = CardAnalysis(card_id=card.id, has_script=True)
        analysis.effects.extend(self._effects)
        return analysis


class _RepositoryStub:
    """``get(card_id)`` 만 흉내 내는 최소 대역."""

    def __init__(self, card):
        self._card = card

    def get(self, card_id):
        return self._card if card_id == self._card.id else None


def _three_block_card():
    """블록 **셋**인 카드 하나. 두 번째 블록만 트리거가 아니다."""
    from core.card_model import Card, EffectSpec, LuaScriptInfo

    blocks = [
        EffectSpec(
            index="e1",
            effect_types=["SINGLE", "TRIGGER_O"],
            code="EVENT_SUMMON_SUCCESS",
            ranges=["MZONE"],
        ),
        EffectSpec(index="e2", effect_types=["IGNITION"], code=None, ranges=["MZONE"]),
        EffectSpec(
            index="e3",
            effect_types=["SINGLE", "TRIGGER_O"],
            code="EVENT_SPSUMMON_SUCCESS",
            ranges=["MZONE"],
        ),
    ]
    script = LuaScriptInfo(card_id=777, file_name="c777.lua", effects=blocks)
    card = Card(
        id=777,
        name="세 블록 카드",
        name_en=None,
        name_ja=None,
        name_ko=None,
        type_mask=0,
        attribute_mask=0,
        race_mask=0,
        level=1,
        atk=0,
        defense=0,
        pendulum_scale_left=None,
        pendulum_scale_right=None,
        link_marker_mask=0,
        setcodes=[],
        category_mask=0,
        alias=0,
        ot=0,
        desc="",
        desc_en="",
        strings=[],
        script=script,
    )
    return card, blocks


def test_25_the_ordinal_follows_the_block_even_when_a_block_is_skipped():
    """
    🔴 **변이가 살아남은 자리를 직접 겨눈다** (M3).

    등록 효과가 블록 **0 과 2** 이고 블록 1 은 등록 효과가 아니다. 그러면
    두 선언의 ``ordinal`` 은 **0 과 2** 여야 한다. ``enumerate`` 순번으로
    추정하면 0 과 **1** 이 되어, 둘째 선언이 **다른 블록의 효과**를 가리키게
    된다 — §5 가 금지한 바로 그 잘못된 연결이다.
    """
    from analysis.effect_model import EffectAnalysis

    card, blocks = _three_block_card()
    effects = [
        EffectAnalysis(index=blocks[0].index, raw=blocks[0],
                       effect_types=list(blocks[0].effect_types)),
        EffectAnalysis(index=blocks[2].index, raw=blocks[2],
                       effect_types=list(blocks[2].effect_types)),
    ]
    found = compiled_triggers(
        _RepositoryStub(card), 777, analyzer=_AnalyzerStub(effects)
    )

    assert found.examined == 2
    assert found.unplaceable == 0
    ordinals = [c.spec.effect_ref.ordinal for c in found.compilations if c.is_registered]
    assert ordinals == [0, 2]
    #: 그리고 그 자리의 블록이 **정말 그 선언의 출처**다.
    codes = [c.event_code for c in found.compilations if c.is_registered]
    assert codes == [blocks[0].code, blocks[2].code]


def test_26_a_block_we_cannot_place_is_counted_and_not_registered():
    """
    🔴 **변이가 살아남은 둘째 자리** (M4).

    분석 결과의 블록이 원본 목록에 **없으면** 자리를 모른다. 그때
    ``EffectRef`` 를 지어내면 (예: 0) 그 선언은 **엉뚱한 블록**의 것이 된다.
    등록하지 않고 ``unplaceable`` 로 센다 — 세는 것과 지어내는 것은 다르다.
    """
    from analysis.effect_model import EffectAnalysis
    from core.card_model import EffectSpec

    card, blocks = _three_block_card()
    stranger = EffectSpec(
        index="e9",
        effect_types=["SINGLE", "TRIGGER_O"],
        code="EVENT_SUMMON_SUCCESS",
        ranges=["MZONE"],
    )
    effects = [
        EffectAnalysis(index=stranger.index, raw=stranger,
                       effect_types=list(stranger.effect_types)),
        EffectAnalysis(index=blocks[2].index, raw=blocks[2],
                       effect_types=list(blocks[2].effect_types)),
    ]
    found = compiled_triggers(
        _RepositoryStub(card), 777, analyzer=_AnalyzerStub(effects)
    )

    assert found.examined == 2
    assert found.unplaceable == 1
    #: 자리를 안 블록만 등록된다.
    ordinals = [c.spec.effect_ref.ordinal for c in found.compilations if c.is_registered]
    assert ordinals == [2]
