"""
Phase 6-J — **유발 효과를 실제로 해결할 수 있는가.** 답: 아직 아니다.

6-I 가 실제 사건에서 후보를 모으는 데까지 왔다. 6-J 는 그 다음 칸 —
"모은 후보를 실제로 해결한다" — 을 시도하고, **세 층에서 막혔다.** 이 파일은
막힌 자리를 **실제 실행으로** 고정한다. 그래야 그 층이 생기는 날 이 테스트가
먼저 깨지고, 그것이 진척의 신호가 된다.

막는 셋, 무는 순서대로
----------------------
=========================================  =============================
 **B3 발동 절차** — 모든 4,173건            ``monster-activation-timing``
   몬스터 효과를 발동할 ``PlayerAction`` 이    (기동 · 유발 · 플립 ·
   없다. ``ActionValidator`` 는 패의 통상      유발즉시 분류가 없다)
   마법만 판정한다.
 **B2 사건 생성** — ``monster_summoned``    (Phase 6-U 에서 풀렸다)
   효과 몬스터를 일반 소환할 수 없으므로
   "이 카드가 소환되었을 때" 사건이 안 났다.
   🔴 6-U 가 카드 자신의 스크립트에서 소환
   제약 상수를 세어 관문을 열었다. **사건은
   이제 난다.** 남은 막은 등재(ADR-006)다.
 **B1 해결** — ``special_summon`` 9건       소생 제한을 판정할 계층
   ``may_be_special_summoned`` 가 **언제나**
   ``UNKNOWN`` 이고, ``build_executor`` 에
   그것을 넘길 인자가 없다.
=========================================  =============================

🔴 **실행기는 병목이 아니다.** 13종 중 12종을 지원하고 (``unknown`` 하나만
빠진다), 옮겨진 연산 중 지원 밖인 것은 **0건**이다 (``test_04``). 막는 것은
실행 **위**의 층들이다.

🔴 **우회하지 않았다.** ``DeclaredSummonRuling`` 을 production 경로에 꽂거나
검증기를 넓히면 테스트는 통과하겠지만, 그것이 6-J §8 이 금지한 "미지원 조건을
우회하는 테스트용 권한" 이다. 막힌 것을 막힌 대로 적는다.
"""

import ast
import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import ActionKind
from engine.action import PlayerAction
from engine.duel import Duel
from engine.effect.executor import SUPPORTED, EffectExecutor
from engine.effect.library import (
    EFFECT_LIBRARY,
    build_executor,
    definition_registry,
    implementation_registry,
)
from engine.effect.operation import OperationKind
from engine.effect.semantics import UnknownSummonRuling
from engine.game_state_view import CardDefinitionView
from engine.ids import EffectRef, InstanceId
from engine.summon_rules import SummonEligibility, assess_normal_summon
from engine.trigger import TriggerSubject
from engine.trigger_observation import ObservationStage, TriggerObserver
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import ActivationKind, Phase, Position, Zone
from integration.execution_readiness import (
    RESOLUTION_OPERATIONS,
    UNMAPPED_ACTIONS,
    ExecutionBlocker,
    ResolutionReadiness,
    readiness_for,
)
from integration.trigger_registry import compiled_triggers, registry_for_view

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: 욕망의 항아리 — ``executable=True`` 이고 ``Duel.legal_actions`` 가 실제로
#: 발동 행동을 제시한다. **대조군**이다: 통상 마법은 발동된다.
POT_OF_GREED = 55144522

#: 수호신관 마하드 — 6-I 가 두 축을 통과시킨 그 등록. 6-J 의 측정에서
#: 비용이 ``unknown`` 으로 남는다 (공식 원문 「이 카드를 상대에게 **보여주고**
#: 발동할 수 있다」 — 보여주기가 비용인지 엔진이 모른다).
DRAWN_TRIGGER_CARD = 71703785

#: 점쟁이 마녀 안 — 「①: 이 카드를 드로우했을 때 … 이 카드를 패에서 특수
#: 소환한다」. **조건 함수가 아예 없고** 비용도 선택도 없다. 6-J 의 측정에서
#: 해결 단계가 가장 가까운 후보이고, 그래서 ``special_summon`` 의 소생 제한
#: 판정(B1)이 유일하게 남는 자리다.
WITCH = 31683874

#: 레알 제넥스 마그나 — 「①: 이 카드를 **일반 소환했을 때**에 발동할 수 있다.
#: 덱에서 레벨 2 의 "레알 제넥스" 몬스터 1장을 패에 넣는다」. 해결 동작이
#: ``to_hand`` 라서 **소생 제한이 필요 없는** 유일한 모양이지만, 사건을
#: 만들 수 없다 (B2).
MAGNA = 1533292

#: 엘리멘틀 히어로 페더맨 — 통상 몬스터. 엔진이 실제로 일반 소환한다.
FEATHERMAN = 21844576

#: 잭나이츠 오르페골 기르수 — 장기 회귀 사례 (§11).
GIRSU = 69811710


# ======================================================================
# A. 표의 정합성 — 두 어휘를 잇는 자리가 거짓말하지 않는가
# ======================================================================


def test_01_every_translated_operation_is_one_the_executor_supports():
    """
    🔴 **표가 실행기보다 넓으면 "지원한다" 가 거짓이 된다.**

    :data:`RESOLUTION_OPERATIONS` 의 모든 값이
    :data:`~engine.effect.executor.SUPPORTED` 안에 있어야 한다. 실행기가
    **스스로 세운** 집합과 맞춰 보므로, 실행기에서 핸들러가 빠지는 날 여기서
    깨진다.
    """
    assert RESOLUTION_OPERATIONS
    for action, operation in RESOLUTION_OPERATIONS.items():
        assert operation in SUPPORTED, (action, operation)

    #: 실행기가 지원하지 않는 것은 ``unknown`` 하나다 — 그리고 그것은
    #: 표에도 없다.
    assert set(OperationKind) - SUPPORTED == {OperationKind.UNKNOWN}
    assert OperationKind.UNKNOWN not in RESOLUTION_OPERATIONS.values()


def test_02_the_table_covers_every_action_kind_exactly_once():
    """
    표와 "표에 없는 것" 이 ``ActionKind`` 를 **빠짐없이 한 번씩** 가른다.

    🔴 새 ``ActionKind`` 가 생기면 여기서 깨진다. 그때 **옮길 수 있는지
    판단해야** 하고, 조용히 "표에 없음" 으로 떨어지면 그 판단이 일어나지
    않는다.
    """
    assert set(RESOLUTION_OPERATIONS) | UNMAPPED_ACTIONS == set(ActionKind)
    assert set(RESOLUTION_OPERATIONS) & UNMAPPED_ACTIONS == set()

    #: 🔴 ``NORMAL_SUMMON`` 은 **연산이 아니다** — 효과 해결 중에 수행되는
    #: 일이 아니라 플레이어가 고르는 행위다 (ADR-001). 표에 없는 것이 옳다.
    assert ActionKind.NORMAL_SUMMON in UNMAPPED_ACTIONS
    assert ActionKind.UNKNOWN in UNMAPPED_ACTIONS


def test_03_damage_and_recovery_are_the_same_engine_operation():
    """
    두 ``ActionKind`` 가 한 ``OperationKind`` 로 간다 — **engine 이 이미
    하나로 적고 있기 때문**이고 (``LifeChangeOperation.delta`` 의 부호),
    이 표가 둘을 합치는 것이 아니다.
    """
    assert RESOLUTION_OPERATIONS[ActionKind.DAMAGE] is OperationKind.CHANGE_LIFE
    assert RESOLUTION_OPERATIONS[ActionKind.RECOVER] is OperationKind.CHANGE_LIFE

    from engine.effect.operation import LifeChangeOperation

    assert LifeChangeOperation(delta=-1000, who=None).kind is OperationKind.CHANGE_LIFE
    assert LifeChangeOperation(delta=1000, who=None).kind is OperationKind.CHANGE_LIFE


# ======================================================================
# B. 실행기의 실제 지원 범위 (§4-B)
# ======================================================================


@requires_official_db
def test_04_no_translated_operation_is_outside_the_executors_reach(repository):
    """
    🔴 **실행기는 병목이 아니다** — 전수 측정.

    옮길 수 있었던 연산 중 ``OPERATION_UNSUPPORTED`` 로 막힌 것이 **0건**이다.
    막는 것은 실행 **위**의 층들이다 (모듈 머리말의 셋).
    """
    analyzer = EffectAnalyzer(repository)
    unsupported = 0
    seen = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        for readiness in readiness_for(repository, card.id, analyzer=analyzer):
            seen += 1
            if ExecutionBlocker.OPERATION_UNSUPPORTED in readiness.blockers:
                unsupported += 1
    assert seen == 4173
    assert unsupported == 0


@requires_official_db
def test_05_the_census_of_what_blocks_resolution(repository):
    """
    **§12 의 지표** — 전수로 한 번 센다.

    ==========================================  =====
     컴파일된 TRIGGER 등록                        4,173
     서로 다른 ``EffectRef`` (중복 0)              4,173
     ``EffectDefinition`` 이 있는 것                   0
     정의를 적으면 해결 단계가 통과하는 것          2,999
     그중 6-F·6-G 의 두 관문까지 통과하는 것           24
     실제 해결 성공                                    0
    ==========================================  =====

    🔴 **2,999 와 0 의 거리가 이 Phase 의 결론이다.** 해결 동작은 옮길 수
    있고 실행기도 지원하는데, 그 앞의 세 층이 없어서 **하나도 실행되지
    않는다.** 정적 분석 성공과 실제 실행 성공을 가르는 것이 §12 의 요구다.

    🔴 **Phase 6-V 가 그 0 을 1 로 만들었다** — 기르수 ① 하나를 등재했다.
    이 테스트가 틀린 가정을 갖고 있었던 것이 아니라 6-J 시점에 실제로
    0건이었다. ``definition_missing`` 도 4,173 → 4,172 로 하나 줄었다.

    🔴 **"실제 해결 성공" 은 여전히 0 이다.** 6-V 는 발동까지 갔고 해결은
    ``Card.IsAbleToGrave`` 관문에서 멈춘다 — 그 측정은
    ``tests/engine/test_summon_trigger_execution.py`` 의 F 묶음에 있다.
    """
    analyzer = EffectAnalyzer(repository)
    definitions, implementations = definition_registry(), implementation_registry()
    registered = 0
    refs = set()
    two_gate = set()
    with_definition = 0
    resolvable = set()
    blockers: dict[str, int] = {}

    for card in repository.all_cards():
        if card.script is None:
            continue
        for compilation in compiled_triggers(
            repository, card.id, analyzer=analyzer
        ).compilations:
            if not compilation.is_registered:
                continue
            registered += 1
            refs.add(compilation.spec.effect_ref)
            if (
                compilation.spec.subject is TriggerSubject.SELF
                and compilation.spec.activates_from is not None
            ):
                two_gate.add(compilation.spec.effect_ref)
        for readiness in readiness_for(
            repository,
            card.id,
            analyzer=analyzer,
            definitions=definitions,
            implementations=implementations,
        ):
            if ExecutionBlocker.DEFINITION_MISSING not in readiness.blockers:
                with_definition += 1
            for blocker in readiness.blockers:
                blockers[blocker.value] = blockers.get(blocker.value, 0) + 1
        #: 🔴 정의/구현을 **묻지 않은** 준비도 — "정의를 적으면 해결되는가".
        for readiness in readiness_for(repository, card.id, analyzer=analyzer):
            if readiness.is_resolvable:
                resolvable.add(readiness.effect_ref)

    assert registered == 4173
    assert len(refs) == 4173
    #: 🔴 6-V 가 기르수 ① 을 등재했다 (0 → 1).
    #: 🔴 6-AC 가 성유물－『성장』 ② 를 등재했다 (1 → 2). 둘 다 유발이고
    #: 둘 다 컴파일된다 — 그래서 "정의가 없다" 가 하나 더 줄었다.
    assert with_definition == 2
    assert len(two_gate) == 31
    assert len(resolvable) == 2999
    assert len(resolvable & two_gate) == 24

    assert blockers == {
        #: 🔴 6-V: 4,173 → 4,172 (기르수 ① 의 정의가 생겼다).
        #: 🔴 6-AC: 4,172 → 4,171 (성유물－『성장』 ② 의 정의가 생겼다).
        #: 나머지 네 막는 이유는 **하나도** 움직이지 않았다 — 이 Phase 가
        #: 더한 것은 정의이고 새 막는 이유가 아니다.
        "definition_missing": 4171,
        "operation_unreadable": 726,
        "cost_unpayable": 260,
        "operation_untranslatable": 222,
        "cost_unknown": 18,
    }


# ======================================================================
# C. 효과 정의 연결 (§10-C)
# ======================================================================


@requires_official_db
def test_06_a_definition_is_looked_up_by_the_exact_effect_ref(repository):
    """
    **시나리오 C** — ``TriggerSpec.effect_ref`` 로 정의를 조회한다.

    🔴 **잘못된 ordinal 연결이 차단된다**: 같은 카드의 다른 ``ordinal`` 은
    다른 키이고, 등록된 정의가 없으면 ``None`` 이다. 카드 ID 만으로 찾는
    경로가 없다는 것이 그 차단이다.
    """
    definitions = definition_registry()
    pot = EffectRef(POT_OF_GREED, 0)
    assert definitions.definition_for(pot) is not None
    #: 같은 카드의 다른 자리는 **다른 효과**다.
    assert definitions.definition_for(EffectRef(POT_OF_GREED, 1)) is None

    for compilation in compiled_triggers(repository, WITCH).compilations:
        if not compilation.is_registered:
            continue
        ref = compilation.spec.effect_ref
        assert definitions.definition_for(ref) is None
        #: 🔴 연결 실패가 **등록을 지우지 않는다** (6-J §7 의 마지막 금지).
        assert ref.card_id == WITCH


@requires_official_db
def test_07_execution_support_is_reported_as_unsupported_not_guessed(repository):
    """
    **시나리오 D** — 실행 구현이 없으면 ``UNSUPPORTED`` 로 남는다.

    6-I 의 관찰자가 ``has_definition`` · ``is_executable`` 을 둘 다 거짓으로
    보고하고, 그 상태에서 ``EXECUTION_READY`` 가 나올 수 없다.
    """
    readiness = readiness_for(
        repository,
        WITCH,
        definitions=definition_registry(),
        implementations=implementation_registry(),
    )
    assert readiness
    for item in readiness:
        assert isinstance(item, ResolutionReadiness)
        assert ExecutionBlocker.DEFINITION_MISSING in item.blockers
        assert item.is_resolvable is False


# ======================================================================
# D. 세 차단 요인을 **실제 실행으로** 고정한다
# ======================================================================


@requires_official_db
def test_08_b3_no_player_action_can_activate_a_monster_effect(repository):
    """
    🔴 **B3 — 가장 먼저 무는 차단.** 모든 4,173건에 걸린다.

    몬스터의 유발 효과를 발동하는 ``PlayerAction`` 을 규칙 계층이 판정하지
    못한다. ``UNKNOWN`` 이고, ``UNKNOWN`` 은 허가가 아니므로 후보가 되지
    않는다.

    **대조군이 중요하다** — 같은 ``activate_effect`` 가 패의 통상 마법에는
    ``VALID`` 다. 즉 "발동 자체를 못 한다" 가 아니라 **"몬스터 효과의 발동
    분류가 없다"** 이고, 그 구분이 다음 구현 단위를 가리킨다.
    """
    from engine.action_validation import ActionValidator

    duel = Duel.start(repository=repository, decks=([WITCH] * 20, [WITCH] * 20), seed=5)
    duel.state.turn.set_phase(Phase.MAIN1)
    witch = duel.state.player(MINE).hand[0]
    assert witch.card_id == WITCH

    verdict = ActionValidator(duel.view(MINE)).validate(
        PlayerAction.activate_effect(
            actor=MINE, source=witch.instance_id, effect_ref=EffectRef(WITCH, 0)
        )
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == (
        "monster-activation-timing (기동 · 유발 · 플립 · 유발즉시 분류가 없다)"
    )

    #: 대조군 — 패의 통상 마법은 같은 종류의 행동으로 발동된다.
    spell = Duel.start(
        repository=repository, decks=([POT_OF_GREED] * 20, [POT_OF_GREED] * 20), seed=5
    )
    spell.state.turn.set_phase(Phase.MAIN1)
    allowed = ActionValidator(spell.view(MINE)).validate(
        PlayerAction.activate_effect(
            actor=MINE,
            source=spell.state.player(MINE).hand[0].instance_id,
            effect_ref=EffectRef(POT_OF_GREED, 0),
        )
    )
    assert allowed.validity is ActionValidity.VALID

    #: 그리고 **실제 행동 목록에도** 몬스터 효과가 없다.
    kinds = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "activate_effect" not in kinds
    assert "activate_effect" in {
        a.kind.value for a in spell.legal_actions(MINE).allowed
    }


@requires_official_db
def test_09_b2_the_summon_that_makes_the_event_is_no_longer_blocked(repository):
    """
    🔴 **B2 가 풀렸다** — 그리고 그것이 B2 의 전부가 아니다.

    이 시험은 "``monster_summoned`` 사건을 만들 수 없다" 를 **소환 판정이
    막혀서**라고 적었다. 그 진단은 맞았지만 그 다음 문장("효과 몬스터의
    소환 제약을 읽는 층이 없다")을 **영구적 한계**로 전제한 것이 틀렸다.
    Phase 6-U 가 마그나의 스크립트를 읽어 제약 상수가 **한 건도 없음**을
    확인했고, 그래서 일반 소환이 실제로 수행된다.

    🔴 **그렇다고 B2 가 "효과가 해결된다" 가 된 것은 아니다.** 사건을 만들
    수 있게 된 것뿐이고, 등재(ADR-006)는 여전히 없다 — 아래에서 그것을
    함께 고정한다.
    """
    magna = assess_normal_summon(CardDefinitionView.of(repository.get(MAGNA)))
    assert magna.eligibility is SummonEligibility.ORDINARY
    assert magna.missing_rule is None

    #: 대조군 — 통상 몬스터는 전부터 판정이 났다.
    plain = assess_normal_summon(CardDefinitionView.of(repository.get(FEATHERMAN)))
    assert plain.eligibility is SummonEligibility.ORDINARY

    duel = Duel.start(repository=repository, decks=([MAGNA] * 20, [MAGNA] * 20), seed=5)
    duel.state.turn.set_phase(Phase.MAIN1)
    kinds = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "normal_summon" in kinds
    assert "end_phase" in kinds

    #: 그리고 실제로 소환된다 — 사건을 만들 자리가 생겼다.
    action = next(
        a for a in duel.legal_actions(MINE).allowed
        if a.kind.value == "normal_summon"
    )
    step = duel.apply(action)
    assert step.accepted is True
    placed = [c for c in duel.state.player(MINE).monster_zone if c is not None]
    assert [c.card_id for c in placed] == [MAGNA]

    #: 🔴 **그런데 효과는 해결되지 않는다.** 등재가 없다 (ADR-006).
    from engine.effect.library import entry_for

    assert entry_for(MAGNA) is None
    assert len(duel.chain) == 0


def test_10_b1_the_special_summon_gate_can_never_be_answered():
    """
    🔴 **B1 — 해결 단계의 차단.** ``special_summon`` 후보 9건에 걸린다.

    실행기의 기본 소환 판정기가 **언제나 ``UNKNOWN``** 이고 (소생 제한은
    카드가 아니라 **이력**이므로 카드 한 장을 보고 답할 수 없다),
    ``build_executor`` 에는 그것을 바꿔 넣을 **인자가 없다.**

    🔴 그래서 production 경로에서 이 관문을 통과시킬 방법이 없다. 통과시킬
    수 있는 ``DeclaredSummonRuling`` 은 존재하지만 production 어디에서도
    쓰이지 않고, 여기에 꽂는 것이 6-J §8 이 금지한 우회다.
    """
    import inspect

    executor = EffectExecutor()
    assert isinstance(executor.summoning, UnknownSummonRuling)
    for instance in (InstanceId(0), InstanceId(7), InstanceId(99)):
        assert (
            executor.summoning.may_be_special_summoned(instance).value == "unknown"
        )

    #: 🔴 production 조립 자리에 그 판정기를 넘길 칸이 없다.
    assert "summoning" not in inspect.signature(build_executor).parameters
    assert isinstance(build_executor().summoning, UnknownSummonRuling)

    #: 그리고 production 에서 ``DeclaredSummonRuling`` 을 쓰는 자리가 없다.
    users = []
    for package in ("engine", "integration", "agent", "app", "core", "analysis"):
        root = PROJECT_ROOT / package
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "DeclaredSummonRuling(" in text:
                users.append(str(path.relative_to(PROJECT_ROOT)))
    assert users == []


# ======================================================================
# E. 실제 듀얼 — 해결이 **일어나지 않는다** (§10-E · §10-F)
# ======================================================================


@pytest.fixture
def drew_a_witch(repository):
    """
    **욕망의 항아리를 실제로 발동·해결해서** 점쟁이 마녀를 뽑은 듀얼.

    사건은 ``Duel.apply`` 가 기록한 것뿐이다 (6-I 와 같은 방식).
    """
    duel = Duel.start(
        repository=repository,
        decks=([POT_OF_GREED] + [WITCH] * 20, [WITCH] * 20),
        seed=11,
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    drawn = tuple(card.instance_id for card in duel.state.player(MINE).deck[:2])
    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind.value == "activate_effect"
    )
    assert duel.apply(action).accepted
    for _ in range(6):
        passing = [
            a for a in duel.legal_actions(duel.to_act).allowed if a.kind.value == "pass"
        ]
        if not passing:
            break
        assert duel.apply(passing[0]).accepted
    return duel, drawn


@requires_official_db
def test_11_the_drawn_trigger_is_observed_but_never_resolved(repository, drew_a_witch):
    """
    **시나리오 A·B·E·F 를 한 판에서** — 사건은 실제로 나고, 후보도 나오고,
    두 축도 통과하는데, **해결은 일어나지 않는다.**

    그것이 6-J 의 결론이다: 분석과 판정은 왔고 실행은 오지 않았다.
    """
    duel, drawn = drew_a_witch
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    observer = TriggerObserver(
        view, build.registry, definition_registry(), implementation_registry()
    )
    observations = observer.observe_all(duel.journal.events)

    own = [o for o in observations if o.event.instance == o.candidate.source]
    assert {o.candidate.source for o in own} == set(drawn)

    for observation in own:
        #: 🔴 두 축은 통과한다 (6-F · 6-G).
        assert observation.stage is ObservationStage.JUDGEMENT_PENDING
        #: 🔴 그런데 정의도 구현도 없다 → 실행 가능이라고 말하지 않는다.
        assert observation.has_definition is False
        assert observation.is_executable is False
        assert observation.stage is not ObservationStage.EXECUTION_READY
        #: 🔴 그리고 미검사 규칙이 남아 있다 — 숨기지 않는다.
        assert observation.unchecked_rules


@requires_official_db
def test_12_observing_resolves_nothing_and_changes_nothing(repository, drew_a_witch):
    """
    🔴 **시나리오 I — 실행되지 않은 후보를 성공 이벤트로 남기지 않는다.**

    관찰 전후로 판 · 체인 · 우선권 · **기록**이 전부 같다. 특히 기록이
    같다는 것이 "후보를 봤다" 가 "효과가 해결됐다" 로 새지 않는다는 증거다.
    """
    duel, _drawn = drew_a_witch
    before = (
        duel.state.state_hash(),
        len(duel.chain),
        duel.priority.describe_ko(),
        duel.step,
        tuple(r.canonical_state() for r in duel.journal.events),
    )
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    observer = TriggerObserver(
        view, build.registry, definition_registry(), implementation_registry()
    )
    assert observer.observe_all(duel.journal.events)
    observer.observe_all(duel.journal.events)

    assert (
        duel.state.state_hash(),
        len(duel.chain),
        duel.priority.describe_ko(),
        duel.step,
        tuple(r.canonical_state() for r in duel.journal.events),
    ) == before

    #: 기록에 남은 것은 **실제로 일어난 일**뿐이다 — 욕망의 항아리의
    #: 발동 · 해결 · 드로우이고, 점쟁이 마녀의 효과는 하나도 없다.
    witch_refs = [
        record
        for record in duel.journal.events
        if str(getattr(record, "source", "")) == str(WITCH)
    ]
    assert witch_refs == []


# ======================================================================
# F. 같은 카드 복수 인스턴스 · 복수 듀얼 (§10-G · §10-H)
# ======================================================================


@requires_official_db
def test_13_two_instances_of_the_same_card_stay_apart(repository, drew_a_witch):
    """**시나리오 G** — 뽑힌 두 장이 각자 자기 사건에서만 후보다."""
    duel, drawn = drew_a_witch
    view = duel.view(MINE)
    build = registry_for_view(view, repository)
    observer = TriggerObserver(view, build.registry)
    by_event: dict = {}
    for observation in observer.observe_all(duel.journal.events):
        by_event.setdefault(observation.event.instance, []).append(observation)

    assert set(by_event) == set(drawn)
    for instance, group in by_event.items():
        passed = [o for o in group if o.candidate.source == instance]
        assert len(passed) == 1
        assert passed[0].stage is ObservationStage.JUDGEMENT_PENDING
        for other in group:
            if other.candidate.source != instance:
                assert other.stage is ObservationStage.REFUSED


@requires_official_db
def test_14_two_duels_do_not_share_readiness_or_registrations(repository):
    """**시나리오 H** — 서로 다른 듀얼이 섞이지 않는다."""
    duels = []
    for deck in ([WITCH] * 20, [FEATHERMAN] * 20):
        duel = Duel.start(repository=repository, decks=(list(deck), list(deck)), seed=5)
        duel.state.turn.set_phase(Phase.MAIN1)
        duels.append(duel)
    witchy, plain = duels

    rich = registry_for_view(witchy.view(MINE), repository)
    poor = registry_for_view(plain.view(MINE), repository)
    assert rich.card_ids == (WITCH,)
    assert poor.card_ids == ()
    assert rich.registry is not poor.registry
    assert rich.registered >= 1
    assert poor.registered == 0

    #: 준비도도 카드마다 따로다 — 듀얼에 매달려 있지 않다.
    assert readiness_for(repository, WITCH)
    assert readiness_for(repository, FEATHERMAN) == ()


# ======================================================================
# G. 기존 기능 회귀 (§10-J)
# ======================================================================


@requires_official_db
def test_15_the_existing_activate_effects_still_resolve(repository):
    """
    🔴 **시나리오 J — 기존 ACTIVATE 효과가 변경 전과 같이 작동한다.**

    6-J 는 production 실행 경로를 **하나도 고치지 않았다.** 그 증거로 실제
    듀얼에서 욕망의 항아리를 발동·해결해 **판이 바뀌는 것**을 본다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([POT_OF_GREED] + [FEATHERMAN] * 20, [FEATHERMAN] * 20),
        seed=11,
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    before_hand = len(duel.state.player(MINE).hand)
    before_deck = len(duel.state.player(MINE).deck)

    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind.value == "activate_effect"
    )
    assert duel.apply(action).accepted
    for _ in range(6):
        passing = [
            a for a in duel.legal_actions(duel.to_act).allowed if a.kind.value == "pass"
        ]
        if not passing:
            break
        assert duel.apply(passing[0]).accepted

    #: 🔴 **판이 실제로 바뀌었다** — 2장 뽑고 자기 카드는 묘지로.
    assert len(duel.state.player(MINE).deck) == before_deck - 2
    assert len(duel.state.player(MINE).hand) == before_hand + 1
    assert len(duel.journal.events) >= 2


def test_16_the_library_now_has_exactly_two_triggers(repository=None):
    """
    ``EFFECT_LIBRARY`` 에 **유발 효과가 없다.**

    🔴 6-J 는 정의를 **하나도 추가하지 않았다.** 추가할 수 있었던 유일한
    모양(점쟁이 마녀 ①)은 ``special_summon`` 이고, 그 관문을 통과시킬
    production 경로가 없어서 추가하면 **실행할 수 없는 정의**가 목록에
    남는다 — ADR-006 이 ``executable`` 을 따로 둔 이유가 그것이다.

    🔴 **Phase 6-K 가 한 건을 더했다 (16 → 17).** 이 테스트가 틀린 가정을
    갖고 있었던 것이 아니라, 6-J 시점에 실제로 16건이었다. 더해진 것은
    어니스트 ① 이고 ``ActivationKind.IGNITION`` 이다 — **유발 효과가 아니고**
    (이 테스트의 이름이 지키는 사실) 그것이 이 테스트의 전부다.

    🔴 **Phase 6-L 에서 그 한 건이 실행까지 된다** (13 → 14).

    🔴 **Phase 6-V 가 이 테스트의 이름을 바꿨다 (17 → 18).** 그때까지 "유발
    효과가 하나도 없다" 가 사실이었고 이 테스트가 그것을 분류로 세고
    있었다. 6-V 가 기르수 ① 을 ``ActivationKind.TRIGGER`` 로 등재했으므로
    그 사실이 끝났다 — **단언을 지우지 않고 수를 세는 쪽으로 바꿨다.**
    유발 즉시(``QUICK``)와 플립(``FLIP``)은 **여전히 0건**이고, 그것이 이
    테스트가 계속 지키는 사실이다.
    """
    #: 🔴 **Phase 6-AC 가 유발을 둘로 만들었다 (18 → 19).** 성유물－
    #: 『성장』 ② 도 ``ActivationKind.TRIGGER`` 다. 같은 성질의 고침이고,
    #: ordinal 집합도 처음으로 {0} 을 벗어났다 (등재한 것이 공식 ②다).
    assert len(EFFECT_LIBRARY) == 19
    assert {entry.effect_ref.ordinal for entry in EFFECT_LIBRARY} == {0, 1}
    #: Phase 6-AC — 성유물－『성장』 ② 가 실행 가능으로 더해졌다 (15 → 16).
    assert sum(1 for entry in EFFECT_LIBRARY if entry.executable) == 16
    #: 🔴 등재된 발동 분류 — 유발이 **정확히 둘**이고 유발 즉시 · 플립은 없다.
    kinds = [entry.definition.activation_kind for entry in EFFECT_LIBRARY]
    assert set(kinds) == {None, ActivationKind.IGNITION, ActivationKind.TRIGGER}
    assert kinds.count(ActivationKind.TRIGGER) == 2
    assert kinds.count(ActivationKind.QUICK) == 0
    assert kinds.count(ActivationKind.FLIP) == 0


# ======================================================================
# H. §11 기르수
# ======================================================================


@requires_official_db
def test_17_girsu_is_blocked_three_layers_up(repository):
    """
    **§11 기르수** — 등록은 둘, 정의는 없고, **위치도 모른다.**

    6-I 가 측정한 것이 그대로다: ``SetRange`` 가 없어서 ``activates_from``
    이 비고, 자리 관문이 ``UNKNOWN`` 이다. 그래서 기르수는 6-J 의 "두 관문
    통과 31건" 에 **들어가지도 않는다.**

    🔴 **기르수만 작동하게 하는 코드를 쓰지 않았다** (§11 의 금지). 여기서
    확인하는 것은 그 카드가 **어디서 막히는가** 뿐이다.
    """
    compilations = [
        c for c in compiled_triggers(repository, GIRSU).compilations if c.is_registered
    ]
    assert len(compilations) == 2
    for compilation in compilations:
        assert compilation.spec.subject is TriggerSubject.SELF
        assert compilation.spec.activates_from is None

    #: 🔴 **6-V 가 ``DEFINITION_MISSING`` 을 풀었다.** 그 전까지 두 등록
    #: 모두 정의가 없었고, 이제 ``e[0]`` (일반 소환) 에는 정의가 있다.
    #: ``e[1]`` (특수 소환) 은 그대로 없다 — 6-V 는 그쪽을 등재하지 않았다.
    definitions = definition_registry()
    by_ref = {
        r.effect_ref: r
        for r in readiness_for(
            repository, GIRSU, definitions=definitions,
            implementations=implementation_registry(),
        )
    }
    normal = by_ref[EffectRef(GIRSU, 0)]
    assert ExecutionBlocker.DEFINITION_MISSING not in normal.blockers
    special = by_ref[EffectRef(GIRSU, 1)]
    assert ExecutionBlocker.DEFINITION_MISSING in special.blockers
    assert special.is_resolvable is False

    #: 🔴 **막는 층이 하나 줄었다.** 이 줄은 "사건을 만들 수도 없다 (B2)"
    #: 라고 적혀 있었고, 그 근거가 소환 판정의 ``UNDETERMINED`` 였다.
    #: Phase 6-U 가 기르수의 스크립트를 읽어 제약 상수가 없음을 확인했으므로
    #: 소환은 이제 수행된다. **남은 막이 위의 둘**(자리를 모른다 ·
    #: 정의가 없다)이고, 그 둘은 이 Phase 가 고치지 않았다.
    verdict = assess_normal_summon(CardDefinitionView.of(repository.get(GIRSU)))
    assert verdict.eligibility is SummonEligibility.ORDINARY


# ======================================================================
# I. 구조 — 이 Phase 가 우회하지 않았다
# ======================================================================


def test_18_the_readiness_module_cannot_execute_anything():
    """
    🔴 **준비도를 묻는 모듈이 실행할 손을 갖고 있지 않다.**

    "해결할 수 있는가" 와 "해결한다" 를 한 모듈에 두면 전자가 후자의 허가처럼
    읽힌다. 호출이 없으면 그렇게 읽힐 경로도 없다.
    """
    source = (PROJECT_ROOT / "integration" / "execution_readiness.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = {
        "execute",
        "resolve",
        "resolve_top",
        "resolve_all",
        "apply",
        "activate",
        "place",
        "move",
        "draw",
        "EffectExecutor",
        "ChainResolver",
        "EffectActivator",
    }
    assert called & forbidden == set(), called & forbidden


def test_19_this_phase_added_no_bypass_to_the_production_path():
    """
    🔴 **§8 의 금지를 코드로 확인한다** — 미지원 조건을 우회하는 권한을
    production 에 넣지 않았다.

    셋을 본다: 소환 판정을 손으로 선언하는 자리, 발동 검증을 건너뛰는
    자리, 그리고 ``GRANTED`` 같은 고정 허가.
    """
    offenders = []
    for package in ("engine", "integration"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(PROJECT_ROOT))
            for needle in (
                "DeclaredSummonRuling(",
                "DeclaredDestructionRuling(",
            ):
                if needle in text:
                    offenders.append((rel, needle))
    assert offenders == [], offenders

    #: 발동 허가를 **손으로 만드는** 자리가 production 에 없다.
    valid_calls = []
    for package in ("engine", "integration"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "valid"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ValidationResult"
                ):
                    valid_calls.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
                    )
    #: 있는 것은 전부 **판정을 내리는 자리**이고, 새로 더하지 않았다.
    assert all(not site.startswith("integration/") for site in valid_calls), valid_calls


def test_20_the_unsupported_operation_guard_actually_guards():
    """
    🔴 **변이가 살아남은 자리를 직접 겨눈다.**

    "지원 밖 연산을 통과시킨다" 는 변이가 처음 실행에서 **살아남았다** —
    지금 데이터에서 옮겨진 연산이 전부 지원되므로 (``test_04`` 가 0건을
    센다) 그 분기에 **도달하지 않기** 때문이다. 즉 지금 데이터로는 그
    보호가 있는지 없는지 알 수 없었다.

    그래서 :func:`~integration.execution_readiness.operation_blockers` 가
    ``supported`` 집합을 주입받게 하고, **집합이 좁아진 경우**를 직접 넣는다.
    실행기에서 핸들러가 빠지는 날 그것이 조용히 "지원함" 으로 읽히지 않는다.
    """
    from analysis.effect_model import EffectAction
    from integration.execution_readiness import operation_blockers

    draw = EffectAction(kind=ActionKind.DRAW)

    #: 실제 집합으로는 막는 것이 없다.
    operations, unreadable, blockers = operation_blockers([draw])
    assert operations == (OperationKind.DRAW,)
    assert unreadable == ()
    assert blockers == set()

    #: 🔴 집합이 **좁아지면** 막힌다 — 그래도 옮긴 연산은 그대로 적는다
    #: ("못 옮겼다" 와 "옮겼는데 못 한다" 는 다른 사실이다).
    narrowed = SUPPORTED - {OperationKind.DRAW}
    operations, unreadable, blockers = operation_blockers([draw], supported=narrowed)
    assert operations == (OperationKind.DRAW,)
    assert unreadable == ()
    assert blockers == {ExecutionBlocker.OPERATION_UNSUPPORTED}

    #: 동작이 아예 없으면 **다른** 막는 것이다.
    assert operation_blockers([])[2] == {ExecutionBlocker.OPERATION_UNREADABLE}

    #: 표에 없는 동작은 **또 다른** 막는 것이고, 옮긴 연산에는 들어가지 않는다.
    operations, unreadable, blockers = operation_blockers(
        [EffectAction(kind=ActionKind.NEGATE)]
    )
    assert operations == ()
    assert unreadable == ("negate",)
    assert blockers == {ExecutionBlocker.OPERATION_UNTRANSLATABLE}
