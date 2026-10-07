"""
Phase 3-F-17 — result actor provenance **복원 경로 계약 고정**.

이 파일이 고정하는 계약
-----------------------
두 result 는 행위자를 **소유하지 않는다.** 행위자는 **운반자를 통해 복원된다.**

===========================  =============================================
``EffectResult``              ``ChainResolution.link.actor``
``CostPaymentResult``         ``ActivationResult.action.actor``
===========================  =============================================

"result 가 actor 를 소유한다" 라고 **말하지 않는다.** 정확한 표현은
**"result 의 actor provenance 는 운반자를 통해 복원된다"** 다.

두 운반자의 **강도가 다르다** (§6)
---------------------------------
=====================  ==================  ====================================
운반자                   타입 수준 강제        실제 보장
=====================  ==================  ====================================
``ChainResolution``     🔴 **없다**          생성 자리 전수(6곳)가 지킨다
``ActivationResult``    🟢 **있다**          ``action`` 필수 + ``__post_init__``
=====================  ==================  ====================================

이 비대칭이 이 Phase 의 핵심 발견이고, 다음 Phase 의 유일한 판단거리다.

이 Phase 의 production 변경은 **docstring 셋**뿐이다 (``test_20``).
"""

import ast
import dataclasses
import inspect
import json
import pathlib
import subprocess

import pytest

from engine.action import PlayerAction
from engine.activation import (
    ActivationError,
    ActivationResult,
    ActivationStatus,
    EffectActivator,
)
from engine.chain import (
    Chain,
    ChainLink,
    ChainResolution,
    ChainResolutionStatus,
    ChainResolver,
)
from engine.condition import PlayerRef
from engine.cost.model import CostGroup, LifeCost
from engine.duel import Duel
from engine.effect.delta import LifeChanged
from engine.effect.executor import EffectImplementationRegistry
from engine.effect.library import definition_registry
from engine.effect.resolution import EffectResult, ResolutionContext
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPaymentResult, PaymentContext
from engine.response import ResponseResolution, ResponseResult
from engine.spell_activation import duel_resolver
from engine.state.game_state import GameState
from engine.validation import ValidationResult
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
    "engine",
    "agent",
    "app",
    "core",
    "analysis",
    "rules",
    "rulings",
    "sources",
    "scripts",
)
MINE, THEIRS = 0, 1

LUSTER_DRAGON = 11091375
FEATHERMAN = 71925487
POT_OF_GREED = 55144522
THE_GIFT_OF_GREED = 5915629
I = InstanceId


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def code_only(relative: str) -> str:
    """
    문자열 리터럴을 지운 코드.

    .. note::
       설명 속 상호 참조를 **코드로 착각하지 않으려고** 쓴다. 3-F-13 · 3-F-16 이
       같은 함정에 두 번 빠졌고, 그 뒤로는 타입 사용처를 셀 때 반드시 이것을 쓴다.
    """

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    return ast.unparse(_Strip().visit(ast.parse(source_of(relative))))


def code_holders(name: str) -> set[str]:
    """그 이름을 **코드로** 쓰는 production 파일 전수."""
    found: set[str] = set()
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            if name in code_only(relative):
                found.add(relative)
        except SyntaxError:  # pragma: no cover
            continue
    return found


def every_construction(name: str) -> list[tuple[str, int, set[str]]]:
    """저장소 전체에서 ``name(...)`` 생성 자리를 **AST 로** 모은다."""
    found: list[tuple[str, int, set[str]]] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            ):
                found.append(
                    (
                        str(path.relative_to(PROJECT_ROOT)),
                        node.lineno,
                        {k.arg for k in node.keywords if k.arg},
                    )
                )
    return found


# ======================================================================
# 판
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([LUSTER_DRAGON] * 20, [LUSTER_DRAGON] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def spell_on_field(repository, passcode: int, owner: int):
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=owner, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    return state, card.instance_id


def resolve_through_the_chain(repository, passcode: int, actor: int):
    """**production 해결기**로 체인 하나를 해결한다."""
    state, source = spell_on_field(repository, passcode, actor)
    chain = Chain().activate(
        actor=actor, effect_ref=EffectRef(passcode, 0), source=source
    )
    return state, duel_resolver().resolve_top(state, chain)


def activate_with_cost(repository, who: PlayerRef, *, actor: int = MINE):
    """
    **synthetic 비용**을 붙인 발동.

    .. note::
       실제 카드 16장 전부 비용이 비어 있다 (3-F-15). 어떤 실제 카드의 재정도
       주장하지 않는다 — 비용 계층이 사람을 어느 칸에 적는지만 본다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, actor)
    reference = EffectRef(POT_OF_GREED, 0)
    with_cost = dataclasses.replace(
        definition_registry().definition_for(reference),
        cost=CostGroup(costs=(LifeCost(amount=1000, who=who),)),
    )

    class _OneDefinition:
        def definition_for(self, ref):
            return with_cost if ref == reference else None

    action = PlayerAction.activate_effect(
        actor=actor, source=source, effect_ref=reference
    )
    result = EffectActivator(
        _OneDefinition(), EffectImplementationRegistry((reference,))
    ).activate(state, Chain(), action, authorization=ValidationResult.valid())
    return state, result, action


# ======================================================================
# A. §3 — EffectResult provenance 경로
# ======================================================================


def test_01_the_effect_result_actor_is_read_from_the_chain_resolution(repository):
    """
    §3 · §10 1 — **`EffectResult` → `ChainResolution.link.actor`.**

    이것이 이 Phase 가 고정하는 계약이다. result 가 actor 를 **소유하지
    않고**, 운반자를 통해 **복원된다.**
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)

    assert resolution.status is ChainResolutionStatus.RESOLVED
    assert isinstance(resolution.result, EffectResult)
    #: result 에는 사람 칸이 없다.
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {
        "actor",
        "controller",
        "player",
    }
    #: 운반자에서 복원한다.
    assert resolution.link is not None
    assert resolution.link.actor == THEIRS

    #: 복원한 값으로 사건을 읽으면 3-F-14 계약이 맞는다.
    observed = EventReader(GameStateView.from_state(state, viewer=THEIRS)).read(
        resolution.result, actor=resolution.link.actor
    )
    assert observed
    assert {event.context.actor for event in observed} == {THEIRS}


def test_02_every_site_that_carries_a_result_carries_the_link(repository):
    """
    §3 1 · 2 — **``result`` 를 담는 자리는 ``link`` 도 담는다.**

    저장소 **전체**(production + 테스트)의 ``ChainResolution(...)`` 생성 자리를
    AST 로 전수 조사한다. ``result`` 를 주면서 ``link`` 를 빼는 자리가 **하나도
    없다.**
    """
    sites = every_construction("ChainResolution")
    assert len(sites) == 6, sites

    violations = [
        site for site in sites if "result" in site[2] and "link" not in site[2]
    ]
    assert violations == [], violations

    #: production 쪽은 다섯이고 전부 ``engine/chain.py`` 안이다.
    production = [site for site in sites if not site[0].startswith("tests")]
    assert len(production) == 5
    assert {site[0] for site in production} == {"engine/chain.py"}

    #: ``result`` 를 주는 자리는 둘, ``link`` 만 주는 자리는 하나다.
    with_result = [site for site in sites if "result" in site[2]]
    assert len(with_result) == 3  # production 2 + 테스트 1
    link_only = [site for site in sites if "link" in site[2] and "result" not in site[2]]
    assert len(link_only) == 1


def test_02b_a_failed_resolution_also_carries_the_actor(repository):
    """
    🔴 §3 2 — **해결에 실패한 경로도 운반자를 들고 온다.**

    .. note::
       구조만 세면(``test_02``) 두 생성 자리 중 **실패 경로** 쪽이 ``link`` 를
       빼도 성공 경로 테스트는 통과해 버린다. 이 Phase 의 고의 위반 4번이 실제로
       그 자리를 건드렸고, 구조 단정이 먼저 터져 **의미 단정이 실행되지
       않았다.** 그래서 따로 떼어 냈다.

    싸이크론을 대상 없이 해결하면 ``unchecked_target`` 이 된다 — 판은 바뀌지
    않지만 ``link`` 와 ``result`` 가 **둘 다** 있어야 "누가 실패했는가" 를 말할
    수 있다.
    """
    MYSTICAL_SPACE_TYPHOON = 5318639
    state, failed = resolve_through_the_chain(
        repository, MYSTICAL_SPACE_TYPHOON, THEIRS
    )

    assert failed.status is not ChainResolutionStatus.RESOLVED, failed.status
    assert failed.result is not None, "실패 경로가 result 를 버렸다"
    assert failed.link is not None, "실패 경로가 운반자를 버렸다"
    assert failed.link.actor == THEIRS
    #: 판을 바꾸지 않았으므로 사건은 0개다 — 그래도 행위자는 말할 수 있다.
    assert failed.result.deltas == ()
    assert EventReader(GameStateView.from_state(state, viewer=THEIRS)).read(
        failed.result, actor=failed.link.actor
    ) == ()


def test_03_the_result_has_no_backreference_to_its_carrier(repository):
    """
    §3 3 — **result 만 저장/전달하면 운반자가 사라진다.**

    역참조가 하나도 없고 ``to_dict()`` 에도 사람이 남지 않는다. 이것이 §7 의
    근거다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    orphan = resolution.result
    assert orphan is not None

    for name in ("link", "chain", "context", "action", "actor", "controller", "player"):
        assert not hasattr(orphan, name), name

    payload = json.dumps(orphan.to_dict(), ensure_ascii=False, default=str)
    for word in ("actor", "controller", "payer"):
        assert word not in payload, word

    #: 반면 운반자에는 남는다 — 기록(replay)에 남겨야 하는 것이 이것이다.
    link_payload = json.dumps(resolution.link.to_dict(), ensure_ascii=False, default=str)
    assert json.loads(link_payload)["actor"] == MINE


def test_04_the_chain_link_actor_is_the_activator_not_the_card_controller(repository):
    """
    §3 · §9 5 — ``ChainLink.actor`` 는 **발동한 사람**이다.

    링크를 만든 뒤 카드의 컨트롤러를 옮겨도 ``actor`` 는 그대로다. 그래서
    ``controller`` 와 **같은 것이 아니다** — 지금은 값이 같을 뿐이다.
    """
    state, source = spell_on_field(repository, POT_OF_GREED, MINE)
    link = ChainLink(
        sequence=0, actor=MINE, effect_ref=EffectRef(POT_OF_GREED, 0), source=source
    )
    assert state.find_instance(source).controller == MINE

    state.move(state.find_instance(source), Zone.SZONE, to_player=THEIRS)
    assert state.find_instance(source).controller == THEIRS

    #: 🔴 링크는 **발동한 사람**을 기억한다.
    assert link.actor == MINE
    assert link.resolution_context().controller == MINE
    assert link.resolution_context().controller != state.find_instance(source).controller


# ======================================================================
# B. §4 — CostPaymentResult provenance 경로
# ======================================================================


def test_05_the_cost_payment_result_actor_is_read_from_the_activation(repository):
    """§4 · §10 2 — **`CostPaymentResult` → `ActivationResult.action.actor`.**"""
    state, activation, action = activate_with_cost(repository, PlayerRef.CONTROLLER)

    assert isinstance(activation.payment, CostPaymentResult)
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {
        "actor",
        "controller",
        "affected_player",
    }
    #: 운반자에서 복원한다.
    assert activation.action.actor == action.actor == MINE


def test_06_the_activation_result_enforces_its_carrier_at_the_type_level():
    """
    🟢 §4 1 · 2 · §6 — ``ActivationResult`` 는 **타입 수준에서 강제한다.**

    ``action`` 이 **필수 필드**이므로 ``payment`` 가 있으면 ``action.actor`` 가
    언제나 있다. 그리고 ``__post_init__`` 이 ``link`` 불변식을 **실제로
    검사한다** — 성공했다면서 링크가 없으면 거부한다.

    ``ChainResolution`` 쪽보다 **강하다** (``test_07`` 이 그 대비를 고정한다).
    """
    field = {f.name: f for f in dataclasses.fields(ActivationResult)}["action"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    assert str(field.type) == "PlayerAction"

    guard = inspect.getsource(ActivationResult.__post_init__)
    assert "self.link is None" in guard
    assert "ActivationError" in guard

    #: 실제로 거부한다 — 성공인데 링크가 없는 결과를 만들 수 없다.
    with pytest.raises(ActivationError):
        ActivationResult(ActivationStatus.ACTIVATED, PlayerAction.passing(MINE), Chain())

    #: 그리고 ``action.actor`` 는 필수 int 다 (0/1 검증까지 있다).
    assert PlayerAction.passing(MINE).actor == MINE
    with pytest.raises(Exception):
        PlayerAction.passing(None)


def test_07_the_chain_resolution_does_not_enforce_its_carrier(repository):
    """
    🔴 §6 — ``ChainResolution`` 은 **타입 수준에서 강제하지 않는다.**

    ``link`` · ``result`` 둘 다 기본값이 ``None`` 이고 ``__post_init__`` 은
    **둘을 보지 않는다.** 그래서 "결과는 있는데 누가 했는지 모르는" 객체를
    **만들 수는 있다** — 다만 그런 자리가 저장소에 하나도 없다 (``test_02``).

    **"현재 production 호출 경로에서는 보장된다" 와 "타입 수준에서 강제된다" 는
    다르다.** 이 테스트가 그 차이를 고정한다.
    """
    fields = {f.name: f for f in dataclasses.fields(ChainResolution)}
    assert fields["link"].default is None
    assert fields["result"].default is None

    guard = inspect.getsource(ChainResolution.__post_init__)
    assert "deltas" in guard
    #: 🔴 ``link`` · ``result`` 를 보지 않는다.
    assert "link" not in guard and "result" not in guard

    #: 그래서 actor 를 복원할 수 없는 객체를 **만들 수 있다.**
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    orphaned = dataclasses.replace(resolution, link=None)
    assert orphaned.result is not None
    assert orphaned.link is None
    #: 🔴 이 객체로는 행위자를 말할 수 없다 — 그것이 위험이다.
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    with pytest.raises(TypeError):
        reader.read(orphaned.result)


def test_08_the_cost_payment_payer_is_not_the_resource_owner(repository):
    """
    🔴 §4 5 — **"비용을 지불한 사람" 이 두 가지를 가리킨다.**

    ``LifeCost(who=OPPONENT)`` 로 재면 갈린다. actor 는 **비용을 지는 쪽**(발동한
    사람)이고, ``CostPayment.player`` 는 **자원을 낸 쪽**이다.
    """
    state, activation, action = activate_with_cost(repository, PlayerRef.OPPONENT)
    payment = activation.payment
    assert payment is not None and payment.paid

    #: actor = 발동한 사람
    assert activation.action.actor == MINE
    assert "payer=action.actor" in source_of("engine/activation.py")
    #: 자원을 낸 쪽 = 상대
    assert payment.payments[0].player == THEIRS
    assert payment.deltas[0].player == THEIRS
    assert isinstance(payment.deltas[0], LifeChanged)
    assert state.player(THEIRS).life_points == 7000
    assert state.player(MINE).life_points == 8000
    #: 둘이 갈린다.
    assert activation.action.actor != payment.payments[0].player


def test_09_the_actor_differs_from_controller_and_affected_player(repository):
    """
    §10 3 · 4 · 5 — actor ≠ controller · actor ≠ affected · cost payer ≠ 자원 주인.

    강욕의 보은: P0 이 발동하면 **P1 이 뽑는다.**
    """
    state, resolution = resolve_through_the_chain(repository, THE_GIFT_OF_GREED, MINE)
    assert resolution.link is not None

    observed = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        resolution.result, actor=resolution.link.actor
    )
    #: 행위자는 하나.
    assert {event.context.actor for event in observed} == {MINE}
    #: affected 는 상대.
    assert [event.actor for event in observed] == [THEIRS, THEIRS]
    assert all(delta.player == THEIRS for delta in resolution.result.deltas)

    #: 그리고 효과의 컨트롤러는 발동한 사람이다 — 카드의 컨트롤러가 아니다.
    assert resolution.link.resolution_context().controller == MINE


# ======================================================================
# C. §7 — standalone result 정책
# ======================================================================


def test_10_a_standalone_result_is_not_a_valid_actor_input(repository):
    """
    🔴 §7 — **정책: standalone result 를 actor 판단의 입력으로 쓰는 것은 API 계약
    위반이다** (선택지 **C**).

    사실(선택지 A)은 그 근거다 — result 안에 운반자가 남아 있지 않으므로 복원할
    수 없다 (``test_03``). 선택지 B 는 **거짓**이다.

    그리고 그 정책은 **이미 강제되어 있다** — 3-F-14 가 ``read(result)`` 를
    ``TypeError`` 로 만들었다. 이 Phase 가 새로 막을 것이 없다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    #: 🔴 운반자를 버린 호출 — 거부된다.
    with pytest.raises(TypeError) as omitted:
        reader.read(resolution.result)
    message = str(omitted.value)
    assert "부르는 쪽만 압니다" in message
    assert "결과나 delta 에서 알아낼 수 없습니다" in message

    #: 🟢 운반자를 함께 받으면 통과한다 — 올바른 모양이다.
    assert reader.read(resolution.result, actor=resolution.link.actor)


def test_11_the_missing_carrier_case_is_refused_not_guessed(repository):
    """
    §10 16 — **운반자가 없으면 추측하지 않는다.**

    ``link`` 를 뺀 운반자를 만들어도 엔진이 actor 를 지어내지 않는다. 그리고
    ``actor=None`` 으로 넘기면 "행위자가 없다" 는 **거짓 선언**이 되는데, 그것은
    막지 않는다 — 3-F-16 이 적은 대로 "틀리게 말하는 것" 은 열려 있다.
    """
    state, resolution = resolve_through_the_chain(repository, THE_GIFT_OF_GREED, MINE)
    orphaned = dataclasses.replace(resolution, link=None)
    reader = EventReader(GameStateView.from_state(state, viewer=MINE))

    with pytest.raises(TypeError):
        reader.read(orphaned.result)

    #: 🟡 거짓 선언은 통과한다 — 행위자가 P0 인데 "없다" 고 말할 수 있다.
    hidden = reader.read(orphaned.result, actor=None)
    assert [event.context.actor for event in hidden] == [None, None]
    #: 그래서 운반자를 지키는 것이 계약의 전부다.
    assert resolution.link is not None and resolution.link.actor == MINE


# ======================================================================
# D. §8 — production consumer 조사
# ======================================================================


def test_12_no_production_code_reads_an_actor_from_a_bare_result():
    """
    §8 — **result 만 가지고 actor 를 판정하는 production 코드가 없다.**

    ``.link.actor`` 를 읽는 production 파일이 **0개**다 — 읽는 곳은 테스트뿐이다.
    즉 이 계약을 지금 **쓰는** 쪽이 없고, 그래서 틀린 판정이 나오고 있지 않다.
    """
    readers = {
        relative
        for relative in (
            str(path.relative_to(PROJECT_ROOT)) for path in production_files()
        )
        if ".link.actor" in code_only(relative)
    }
    assert readers == set(), readers

    #: 두 result 를 **코드로** 쓰는 production 파일 전수.
    assert code_holders("EffectResult") == {
        "engine/chain.py",
        "engine/effect/executor.py",
        "engine/effect/resolution.py",
        "engine/effect/__init__.py",
    }
    assert code_holders("CostPaymentResult") == {
        "engine/activation.py",
        "engine/payment.py",
    }


def test_13_the_carrier_survives_all_the_way_to_the_duel_boundary(repository):
    """
    🟢 §8 — **운반자가 듀얼 경계까지 간다.**

    ``ChainResolver.resolve_all`` → ``ResponseResolution.steps`` →
    ``Duel._resolve_chain``. 중간에서 버려지지 않는다.

    🟡 ``DuelStep`` 에서 ``link`` · ``result`` 가 떨어지지만, ``DuelStep.action``
    이 남아 **행위자는 거기서도 살아 있다.** 떨어지는 것은 ``deltas`` 다 —
    3-F-5 가 찾은 그 자리이고, actor provenance 의 공백이 아니다.
    """
    #: 응답 계층이 운반자 **전체**를 들고 있다.
    steps_field = {f.name: f for f in dataclasses.fields(ResponseResolution)}["steps"]
    assert "ChainResolution" in str(steps_field.type)
    #: 발동 쪽 운반자도 그대로 들고 있다.
    activation_field = {f.name: f for f in dataclasses.fields(ResponseResult)}[
        "activation"
    ]
    assert "ActivationResult" in str(activation_field.type)

    #: 듀얼이 그것을 **읽는다**.
    resolve_chain = code_only("engine/duel.py")
    assert "resolution.steps" in resolve_chain

    #: 🟡 그러나 ``DuelStep`` 에는 ``deltas`` 칸이 없다 — actor 는 action 에 남는다.
    from engine.duel import DuelStep

    step_fields = [f.name for f in dataclasses.fields(DuelStep)]
    assert step_fields == ["action", "accepted", "code", "reason", "result"]
    assert "deltas" not in step_fields
    assert "action" in step_fields


# ======================================================================
# E. §9 — 실제 시나리오
# ======================================================================


@pytest.mark.parametrize(
    "passcode,label,expected_affected",
    [
        (POT_OF_GREED, "욕망의 항아리 — 내가 2장 뽑는다", [MINE, MINE]),
        (THE_GIFT_OF_GREED, "강욕의 보은 — **상대가** 2장 뽑는다", [THEIRS, THEIRS]),
    ],
)
def test_14_a_real_card_resolution_restores_one_actor(
    repository, passcode, label, expected_affected
):
    """
    §9 1 · 2 — **실제 카드 해결.** 운반자의 actor 하나가 affected 와 무관하게
    맞는다.
    """
    state, resolution = resolve_through_the_chain(repository, passcode, MINE)
    assert resolution.link is not None, label

    observed = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        resolution.result, actor=resolution.link.actor
    )
    assert [event.actor for event in observed] == expected_affected, label
    assert {event.context.actor for event in observed} == {MINE}, label


@pytest.mark.parametrize(
    "who,label,resource_owner",
    [
        (PlayerRef.CONTROLLER, "자기 LP 비용", MINE),
        (PlayerRef.OPPONENT, "🔴 상대 LP 비용", THEIRS),
    ],
)
def test_15_a_cost_payment_restores_the_activator(repository, who, label, resource_owner):
    """§9 3 · 4 — **비용 지불.** 자원 주인이 바뀌어도 actor 는 발동한 사람이다."""
    state, activation, action = activate_with_cost(repository, who)
    payment = activation.payment
    assert payment is not None and payment.paid, label

    #: actor 는 언제나 발동한 사람이다.
    assert activation.action.actor == MINE, label
    #: 자원을 낸 쪽은 바뀐다.
    assert payment.payments[0].player == resource_owner, label
    assert payment.deltas[0].player == resource_owner, label

    #: 사건으로 옮길 때도 운반자의 actor 를 쓴다.
    observed = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        payment, actor=activation.action.actor
    )
    assert [event.context.actor for event in observed] == [MINE], label
    assert [event.actor for event in observed] == [resource_owner], label


def test_16_a_control_change_does_not_break_the_contract_yet(repository):
    """
    🟡 §9 5 — **컨트롤 변경이 개입하는 가상 상황.**

    지금 계약(``link.actor`` = 발동한 사람)은 컨트롤이 바뀌어도 **깨지지 않는다**
    — 링크가 발동 시점을 기억하기 때문이다.

    **깨지는 것은 "해결 시점의 컨트롤러" 를 알아야 할 때**다. 그 값을 담는 칸이
    어디에도 없고, ``ChainLink`` 에 그런 칸이 없다는 것이 증거다. 컨트롤 이동이
    구현되면 **먼저 그것을 정해야** 한다.
    """
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    assert resolution.link is not None
    assert resolution.link.actor == MINE

    #: 해결 뒤 컨트롤을 옮겨도 운반자는 그대로다.
    source = resolution.link.source
    assert source is not None
    state.move(state.find_instance(source), Zone.GRAVE, to_player=THEIRS)
    assert resolution.link.actor == MINE

    #: 🔴 "해결 시점의 컨트롤러" 를 담는 칸이 없다.
    link_fields = {f.name for f in dataclasses.fields(ChainLink)}
    assert not link_fields & {
        "resolving_controller",
        "controller_at_resolution",
        "original_actor",
    }
    #: 그리고 컨트롤을 바꾸는 조작 종류가 없다.
    from engine.effect.operation import OperationKind

    assert not [kind for kind in OperationKind if "control" in kind.value]


# ======================================================================
# F. §10 9~14 — clone · replay · 불변
# ======================================================================


def test_17_the_carrier_survives_a_clone_and_is_frozen(repository):
    """§10 9 · 10 — clone 후에도 복원된다. 운반자는 frozen 값 타입이다."""
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, THEIRS)
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    observed = EventReader(GameStateView.from_state(copy, viewer=MINE)).read(
        resolution.result, actor=resolution.link.actor
    )
    assert all(event.context.actor == THEIRS for event in observed)

    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.link.actor = MINE  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.result.status = None  # type: ignore[misc]


def test_18_the_carrier_round_trips_through_serialization(repository):
    """
    §10 10 — **replay**: 운반자를 직렬화하면 actor 가 남고, 되읽을 수 있다.

    그래서 기록에 남겨야 하는 것은 **운반자**다 — result 가 아니다.
    """
    state, resolution = resolve_through_the_chain(repository, THE_GIFT_OF_GREED, MINE)
    payload = json.dumps(resolution.to_dict(), ensure_ascii=False, default=str)
    restored = json.loads(payload)

    assert "link" in restored
    assert restored["link"]["actor"] == MINE
    #: result 쪽에는 사람이 없다 — 운반자가 메운다.
    assert "actor" not in json.dumps(restored.get("result", {}), ensure_ascii=False)

    #: 정규 상태에도 사람이 남는다 (동등성이 actor 를 구분한다).
    assert MINE in resolution.link.canonical_state()


def test_19_nothing_about_the_board_or_the_search_moved(repository):
    """§12 — ``state_hash`` · RNG · hidden-information 불변."""
    state, resolution = resolve_through_the_chain(repository, POT_OF_GREED, MINE)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    for _ in range(3):
        reader.read(resolution.result, actor=resolution.link.actor)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    assert (
        live_duel(repository, seed=21).state.state_hash()
        == live_duel(repository, seed=21).state.state_hash()
    )

    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()

    #: AI 는 두 result 와 운반자를 **코드로** 모른다.
    for absent in ("EffectResult", "CostPaymentResult", "ChainResolution"):
        for path in (PROJECT_ROOT / "agent").rglob("*.py"):
            relative = str(path.relative_to(PROJECT_ROOT))
            assert absent not in code_only(relative), (absent, relative)


def test_20_this_phase_changed_only_docstrings():
    """
    §11 — **이 Phase(3-F-17)의 production 변경은 docstring 셋뿐이다.**

    문자열 리터럴을 지운 AST 가 세 파일 모두 **이 Phase 의 base 와 동일**하다 —
    실행되는 코드가 한 글자도 바뀌지 않았다. 그리고 §5 의 금지 항목이 하나도
    들어오지 않았다.

    .. note::
       **``HEAD`` 과 비교하지 않는다.** commit 한 뒤에는 ``HEAD`` 가 이 변경을
       포함하므로 "자기와 자기를 비교" 하는 꼴이 되어 **언제나 통과한다.**
       3-F-12 · 3-F-13 · 3-F-15 · 3-F-16 이 같은 함정에 빠졌고 (``git diff HEAD``),
       이 Phase 가 그 넷을 고치면서 **같은 실수를 여기서 반복하려던 것**을 잡았다.

       그래서 **고정된 base SHA** (``0227765`` — 3-F-16 보고서 commit) 와 비교한다.
       그 commit 은 변하지 않으므로 이 단정은 뒤의 어떤 Phase 에도 흔들리지 않고,
       **이 Phase 가 무엇을 바꿨는지**를 정확히 잰다.
    """
    PHASE_3F17_BASE = "0227765"

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    for relative in (
        "engine/chain.py",
        "engine/effect/resolution.py",
        "engine/payment.py",
    ):
        before = subprocess.run(
            ["git", "show", f"{PHASE_3F17_BASE}:{relative}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        after = source_of(relative)
        assert ast.dump(_Strip().visit(ast.parse(before))) == ast.dump(
            _Strip().visit(ast.parse(after))
        ), relative

    #: 🔴 §5 의 금지 항목 — 새 칸도, 새 추상도 없다.
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {"actor"}
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {"actor"}
    for forbidden in ("ActorProvenance", "ActorOrigin", "ActorRequirement"):
        for relative in ("engine/chain.py", "engine/payment.py", "engine/effect/resolution.py"):
            assert forbidden not in source_of(relative), (forbidden, relative)

    #: 그리고 세 docstring 이 복원 경로를 실제로 적는다.
    assert "resolution.link.actor" in source_of("engine/chain.py")
    assert "resolution.link.actor" in source_of("engine/effect/resolution.py")
    assert "activation.action.actor" in source_of("engine/payment.py")
    #: ``ChainResolution`` 쪽은 강제되지 않는다는 경고도 적는다.
    assert "타입이 그것을 강제하지는 않는다" in source_of("engine/chain.py")


def test_21_the_docstrings_do_not_claim_the_result_owns_the_actor():
    """
    §2 — **"result 가 actor 를 소유한다" 라고 적지 않는다.**

    정확한 표현은 "운반자를 통해 복원된다" 다. 금지된 표현이 들어오면 걸린다.
    """
    for relative in ("engine/effect/resolution.py", "engine/payment.py"):
        text = source_of(relative)
        assert "행위자(actor)를 들고 있지 않다" in text, relative
        #: 소유를 주장하는 표현이 없다.
        for forbidden in ("actor 를 소유", "자기 actor 를 가진다", "actor 칸이 있다"):
            assert forbidden not in text, (forbidden, relative)

    #: ``CostPaymentResult`` 쪽은 ``payments`` 의 사람 칸을 쓰지 말라고 적는다.
    payment_text = source_of("engine/payment.py")
    assert "actor 로 쓰지 않는다" in payment_text
    assert "자원이 줄어든 쪽" in payment_text
