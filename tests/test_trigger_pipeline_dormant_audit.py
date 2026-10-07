r"""
Phase 3-E-43 — Trigger pipeline dormant 구조 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다. 이 파일은 감사의 결론을
**재현 가능한 형태로 고정**하기만 한다 (상태 · 난수 · 순위 · 관측 경계를 건드리는
테스트가 하나도 없다).

측정한 구조 (요지)
-----------------
세 층으로 갈린다.

``LIVE``
    ``engine/activation_timing.py`` — ``duel.py`` · ``response.py`` 가 쓴다.
    16판 1,359행동에서 **86,439회** 호출된다.
``DORMANT-ASSEMBLY``
    ``engine/timing.py`` · ``engine/event_pipeline.py`` — 파이프라인을 **조립**하는
    층이고 **production importer 가 0곳**이다 (테스트만 쓴다).
``DORMANT-PARTS``
    ``engine/trigger.py`` · ``trigger_chain.py`` · ``trigger_order.py`` —
    2,602줄. 조립층을 통해서만 닿는다.

그리고 **``engine/trigger.py`` 의 live 기여는 타입 주석 하나다**:
``activation_timing.py`` 가 가져가는 이름이 ``TimingPoint`` 하나뿐이고, 그것이
``ActivationTiming.point`` 의 **타입**으로만 쓰이며 production 은 그 칸을
**채우지 않는다**.

찾은 구조적 위험 둘 (고치지 않고 기록한다)
----------------------------------------
* **R-1** ``CHAIN_DEFINITION_UNAVAILABLE`` 의 두 carrier 가 **live ↔ dormant** 로
  갈라져 서로 다른 말을 한다 (``test_17``). Phase 3-E-40 이 그 코드를 policy 에서
  ``None`` 으로 둔 **유일한 까닭**이 이 쌍이다 — 즉 dormant 구조가 live policy 의
  한 칸을 묶어 두고 있다.
* **R-2** dormant 판정기의 다섯 관문 중 **넷**이 live 세 관문과 **같은 질문**을
  묻는다 (``test_19``). 남은 하나(``EVENT_RELATION``)만 live 대응이 없고, 그 자리가
  M3 의 어긋남을 들고 있다.
"""

import ast
import pathlib

import pytest

from engine.validation import CODE_VALIDITY, ActionValidity, ValidationCode

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 파이프라인의 **부품** 층.
TRIGGER_PARTS = ("engine/trigger.py", "engine/trigger_chain.py", "engine/trigger_order.py")
#: 파이프라인을 **조립**하는 층.
TRIGGER_ASSEMBLY = ("engine/timing.py", "engine/event_pipeline.py")
#: 실제 듀얼이 쓰는 층.
LIVE_TIMING = "engine/activation_timing.py"

DECK = (
    [11091375] * 3
    + [5053103] * 3
    + [1184620] * 3
    + [32864] * 3
    + [3557275] * 3
    + [55144522] * 5
)


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def module_path(module: str) -> "pathlib.Path | None":
    direct = PROJECT_ROOT / (module.replace(".", "/") + ".py")
    if direct.is_file():
        return direct
    package = PROJECT_ROOT / module.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def engine_imports(path: pathlib.Path) -> set[str]:
    """
    그 파일이 **실행 시점에** 끌어오는 ``engine`` 모듈.

    docstring 의 ``:class:`~engine.x.Y``` 언급은 import 가 아니므로 들어오지
    않는다 — 문자열로 세면 그것까지 걸린다 (이 감사에서 실제로 구분이 필요했다).
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return {name for name in found if name.split(".")[0] == "engine"}


def duel_closure() -> set[str]:
    """``engine.duel`` 에서 import 로 **닿는** 모듈 전체."""
    seen: set[str] = set()
    frontier = ["engine.duel"]
    while frontier:
        module = frontier.pop()
        if module in seen:
            continue
        seen.add(module)
        path = module_path(module)
        if path is None:
            continue
        frontier.extend(dep for dep in engine_imports(path) if dep not in seen)
    return seen


def production_engine_files():
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        yield str(path.relative_to(PROJECT_ROOT)), path


def importers_of(module: str) -> list[str]:
    """그 모듈을 **실제로 import 하는** production 파일."""
    out = []
    for rel, path in production_engine_files():
        if rel == module.replace(".", "/") + ".py":
            continue
        try:
            if module in engine_imports(path):
                out.append(rel)
        except SyntaxError:  # pragma: no cover - 방어
            continue
    return sorted(out)


def top_level_names(rel: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.parse(source_of(rel)).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            names[node.name] = f"{rel}:{node.lineno}"
    return names


# ======================================================================
# 1 ~ 5 — 구조 목록과 세 층
# ======================================================================


def test_01_the_three_part_modules_exist_and_are_large():
    """
    **§2: 부품 층이 2,698줄이다.** 사라진 것이 없는지부터 센다.

    .. note::
       **숫자가 2,602 → 2,681 → 2,698 로 늘었다** (Phase 3-E-45 · 3-F-11).

       ``engine/trigger.py`` 가 1,565 → 1,644 (3-E-45: ``_event_relation`` 의
       판정 조합 수정과 그 까닭을 적은 docstring) → **1,661** (3-F-11) 이 되었다.

       3-F-11 의 +17 은 **전부 docstring 이다.** ``TimingEvent.actor`` 의 설명이
       "이 사건을 일으킨 플레이어" 라고 거짓을 적고 있었고 (Phase 3-F-9 가
       측정한 사건군별 polysemy 와 어긋난다), 그 자리를 사건군별 표로 바꿨다.
       **dormant 구조를 활성화하거나 늘린 것이 아니다** — 모든 문자열 리터럴을
       지운 AST 가 전후 동일함이 그 증거다 (:mod:`tests.test_actor_semantic_contract`
       의 ``test_13`` · ``test_14``).
    """
    sizes = {rel: len(source_of(rel).splitlines()) for rel in TRIGGER_PARTS}
    assert sizes == {
        "engine/trigger.py": 1661,
        "engine/trigger_chain.py": 594,
        "engine/trigger_order.py": 443,
    }
    assert sum(sizes.values()) == 2698


def test_02_the_two_assembly_modules_exist():
    """
    **§2: 조립 층이 865줄이다.**

    .. note::
       **853 → 865** (Phase 3-F-11). ``engine/event_pipeline.py`` 가 417 → 429
       다. ``EventContext.actor`` 의 docstring 에 "부르는 쪽이 선언한다 ·
       ``None`` 인 까닭이 둘이다 · delta 와 맞춰 보지 않는다" 를 적은 +12
       줄이고, **코드는 한 줄도 바뀌지 않았다** (``test_01`` 의 note 가 가리키는
       AST 증거와 같다).
    """
    sizes = {rel: len(source_of(rel).splitlines()) for rel in TRIGGER_ASSEMBLY}
    assert sizes == {"engine/timing.py": 436, "engine/event_pipeline.py": 429}
    assert sum(sizes.values()) == 865


def test_03_the_part_modules_declare_thirty_two_top_level_names():
    """
    **§2: 부품 층의 공개 이름 전수.**

    "구조가 존재한다" 를 먼저 세어 둔다 — 그 다음에 "실행되는가" 를 묻는다.
    """
    names: dict[str, str] = {}
    for rel in TRIGGER_PARTS:
        names.update(top_level_names(rel))
    for expected in (
        "TriggerSpec",
        "TriggerRegistry",
        "TriggerCandidate",
        "TriggerCollector",
        "TriggerCollection",
        "TriggerEligibility",
        "TriggerEligibilityJudge",
        "GateVerdict",
        "EligibilityGate",
        "TriggerChainIntegrator",
        "TriggerChainPlan",
        "TriggerChainEntry",
        "TriggerOrderer",
        "TriggerOrdering",
        "TimingEvent",
        "TimingPoint",
    ):
        assert expected in names, expected
    assert len(names) >= 25


def test_04_the_assembly_modules_have_no_production_importer():
    """
    **§3 · §4: 조립 층을 import 하는 production 파일이 0곳이다.**

    이것이 dormant 의 **구조적 까닭**이다 — 부품이 있고 조립도가 있는데,
    조립도를 펴는 사람이 없다.
    """
    for module in ("engine.timing", "engine.event_pipeline"):
        assert importers_of(module) == [], module


def test_05_the_part_modules_are_reachable_only_through_the_assembly():
    """**§3: 부품은 조립 층(과 서로)만이 가져온다.**"""
    assert importers_of("engine.trigger_chain") == ["engine/timing.py"]
    assert importers_of("engine.trigger_order") == [
        "engine/timing.py",
        "engine/trigger_chain.py",
    ]
    #: ``trigger.py`` 는 예외다 — live 쪽에서도 하나를 가져간다 (``test_07``).
    assert importers_of("engine.trigger") == [
        "engine/activation_timing.py",
        "engine/event_pipeline.py",
        "engine/timing.py",
        "engine/trigger_chain.py",
        "engine/trigger_order.py",
    ]


# ======================================================================
# 6 ~ 9 — Duel 의 import 폐쇄
# ======================================================================


def test_06_the_duel_closure_excludes_the_assembly_and_two_part_modules():
    """
    **§3 · §4: ``Duel`` 에서 import 로 닿지 않는 모듈 넷.**

    ``trigger_chain`` · ``trigger_order`` · ``timing`` · ``event_pipeline`` 이
    폐쇄 밖이다.
    """
    closure = duel_closure()
    #: ``engine`` 만 센다 — ``core`` · ``analysis`` · ``sources`` 를 함께 세면
    #: 66 이다. 이 감사의 질문은 **engine 안의** 도달성이므로 57 이 기준이다.
    assert len(closure) == 57
    for module in (
        "engine.trigger_chain",
        "engine.trigger_order",
        "engine.timing",
        "engine.event_pipeline",
    ):
        assert module not in closure, module


def test_07_only_one_name_crosses_from_trigger_into_the_live_path():
    """
    **§3 · §5: live 로 넘어오는 이름은 ``TimingPoint`` 하나다.**

    ``engine/trigger.py`` 는 1,565줄인데, 실제 듀얼이 쓰는 모듈이 거기서
    가져가는 것은 **enum 하나**다.
    """
    closure = duel_closure()
    assert "engine.trigger" in closure
    assert "engine.activation_timing" in closure

    imported: list[str] = []
    for node in ast.walk(ast.parse(source_of(LIVE_TIMING))):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "engine.trigger"
        ):
            imported.extend(alias.name for alias in node.names)
    assert imported == ["TimingPoint"]


def test_08_that_one_name_is_used_only_as_a_type_annotation():
    """
    **§5 · §9: 그 하나조차 값으로 쓰이지 않는다.**

    ``TimingPoint`` 는 ``ActivationTiming.point`` 의 **타입**으로만 나타나고,
    그 모듈에서 멤버를 읽는 자리가 없다.
    """
    uses = [
        (node.lineno, ast.unparse(node))
        for node in ast.walk(ast.parse(source_of(LIVE_TIMING)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "TimingPoint"
    ]
    assert uses == []
    #: 주석으로는 쓰인다.
    assert "point: TimingPoint | None = None" in source_of(LIVE_TIMING)


def test_09_production_never_fills_that_field():
    """
    **§5: 그 칸은 production 에서 늘 ``None`` 이다 — "모른다" 가 기본값이다.**

    ``duel.py`` · ``response.py`` 의 ``ActivationTiming(...)`` 생성 두 자리가
    ``point=`` 를 넘기지 않는다.
    """
    sites = []
    for rel in ("engine/duel.py", "engine/response.py"):
        for node in ast.walk(ast.parse(source_of(rel))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ActivationTiming"
            ):
                sites.append((rel, node.lineno, sorted(k.arg for k in node.keywords)))
    assert len(sites) == 2
    for _rel, _lineno, kwargs in sites:
        assert "point" not in kwargs


# ======================================================================
# 10 ~ 13 — 실행되는가 (런타임)
# ======================================================================


@requires_official_db
def test_10_a_real_duel_never_calls_into_the_part_modules(repository):
    """
    **§3 · §4 의 가장 강한 증거: 실제 듀얼에서 호출이 0회다.**

    세 부품 모듈의 클래스 메서드와 최상위 함수를 **이 테스트 안에서만** 감싸
    세고, 한 판을 끝까지 돌린다. production 을 고치지 않는다.
    """
    import collections
    import inspect
    import types

    import engine.trigger as trigger
    import engine.trigger_chain as trigger_chain
    import engine.trigger_order as trigger_order
    from agent.arena import make_first_legal, make_search, run_match

    calls: collections.Counter = collections.Counter()
    restore: list[tuple[object, str, object]] = []

    def wrap(container, name, fn, label):
        def probe(*args, **kwargs):
            calls[label] += 1
            return fn(*args, **kwargs)

        restore.append((container, name, fn))
        setattr(container, name, probe)

    for module, label in (
        (trigger, "trigger"),
        (trigger_chain, "trigger_chain"),
        (trigger_order, "trigger_order"),
    ):
        for name, obj in list(vars(module).items()):
            if isinstance(obj, types.FunctionType) and obj.__module__ == module.__name__:
                wrap(module, name, obj, f"{label}.{name}")
            elif inspect.isclass(obj) and getattr(obj, "__module__", "") == module.__name__:
                for method_name, method in list(vars(obj).items()):
                    if isinstance(method, types.FunctionType) and not method_name.startswith("__"):
                        try:
                            wrap(obj, method_name, method, f"{label}.{obj.__name__}.{method_name}")
                        except (AttributeError, TypeError):  # pragma: no cover - 방어
                            pass
    try:
        match = run_match(
            repository,
            decks=(list(DECK), list(DECK)),
            seed=3,
            factories=(make_search(), make_first_legal()),
        )
    finally:
        for container, name, original in restore:
            setattr(container, name, original)

    assert match.outcome.value == "completed"
    assert match.actions > 0
    assert dict(calls) == {}


@requires_official_db
def test_11_the_live_timing_layer_is_called_constantly(repository):
    """
    **§3: 대비 — live 층은 쉬지 않고 불린다.**

    dormant 를 "쓰이지 않는다" 로 말하려면 **쓰이는 것**이 어떻게 보이는지도
    같이 재야 한다.
    """
    import collections
    import types

    import engine.activation_timing as activation_timing
    from agent.arena import make_first_legal, make_search, run_match

    calls: collections.Counter = collections.Counter()
    checker = activation_timing.ActivationTimingChecker
    original = checker.check

    def probe(self, *args, **kwargs):
        calls["check"] += 1
        return original(self, *args, **kwargs)

    assert isinstance(original, types.FunctionType)
    checker.check = probe
    try:
        match = run_match(
            repository,
            decks=(list(DECK), list(DECK)),
            seed=3,
            factories=(make_search(), make_first_legal()),
        )
    finally:
        checker.check = original

    assert match.outcome.value == "completed"
    assert calls["check"] > 100


def test_12_the_duel_module_never_mentions_the_pipeline():
    """**§3: ``duel.py`` 가 "trigger" 라는 말을 한 번도 쓰지 않는다.**"""
    duel = source_of("engine/duel.py")
    assert "trigger" not in duel
    assert "Trigger" not in duel


def test_13_the_two_entry_structures_are_never_constructed_in_production():
    """
    **§4: ``TriggerSpec`` · ``TriggerRegistry`` production 생성이 0곳이다.**

    3-E-33 이후 여러 Phase 가 같은 사실을 쟀다. 여기서 다시 고정한다.
    """
    built = []
    for rel, path in production_engine_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("TriggerSpec", "TriggerRegistry")
            ):
                built.append(f"{rel}:{node.lineno}")
    assert built == []


# ======================================================================
# 14 ~ 16 — M3 재검증
# ======================================================================


def test_14_m3_was_fixed_by_3e45_and_the_policy_now_agrees():
    """
    **§6: M3 가 고쳐졌다** (Phase 3-E-45).

    .. note::
       **이 테스트의 원래 계약이 뒤집혔다** (3-E-45).

       원래는 "``_event_relation`` 이 ``INVALID`` 에 ``RULE_NOT_IMPLEMENTED``
       를 붙인다 — 3-E-38 이 일부러 남겼다" 를 고정했다. 그것은 **그 시점의
       사실 기록**이었고 지켜야 할 계약이 아니었다. 3-E-44 가 R-3 로
       측정하고 3-E-45 가 고쳤다.

    이제 거부에는 거부의 코드(``CANDIDATE_NOT_ELIGIBLE``) 가 붙고, 모름에는
    모름의 코드가 붙는다. 그래서 그 자리의 짝이 policy 와 **맞는다.**
    """
    #: **문자열 창이 아니라 함수 본문을 읽는다** (3-E-45). 창 크기로 재면
    #: 분기가 늘어날 때 조용히 엉뚱한 자리를 보게 된다.
    gate = next(
        node
        for node in ast.walk(ast.parse(source_of("engine/trigger.py")))
        if isinstance(node, ast.FunctionDef) and node.name == "_event_relation"
    )
    codes = {
        node.attr
        for node in ast.walk(gate)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ValidationCode"
    }
    assert "CANDIDATE_NOT_ELIGIBLE" in codes
    #: 모름은 모름 쪽 코드로 남는다 — 두 까닭을 가른 그대로다.
    assert "INFORMATION_UNAVAILABLE" in codes
    assert "RULE_NOT_IMPLEMENTED" in codes
    #: policy 는 그 코드를 **모름**이라고 한다 — 이제 거부에 붙지 않는다.
    assert (
        CODE_VALIDITY[ValidationCode.RULE_NOT_IMPLEMENTED] is ActionValidity.UNKNOWN
    )
    assert (
        CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    )


def test_15_the_event_relation_gate_lives_in_a_dormant_module():
    """
    **§6: 그 어긋남이 production 판정을 만들 수 없다.**

    ``_event_relation`` 은 ``trigger.py`` 안이고, 그 모듈의 메서드는 실제 듀얼에서
    **한 번도 실행되지 않는다** (``test_10``). 그리고 그것을 부르는 ``judge`` 는
    조립 층을 통해서만 닿는다.
    """
    assert "_event_relation" in source_of("engine/trigger.py")
    for rel in ("engine/duel.py", "engine/response.py", "engine/chain.py"):
        assert "_event_relation" not in source_of(rel), rel
    #: ``judge_all`` 을 부르는 production 자리가 **부품 층 밖에 없다.**
    #: (처음에 ``timing.py`` 를 호출자로 적었는데, 그 모듈은 ``judge_all`` 을
    #: 부르지 않고 ``TriggerCollector`` · ``TriggerChainIntegrator`` 를 **만들기만**
    #: 한다 — 소스를 읽어 고쳤다.)
    callers = [
        rel
        for rel, path in production_engine_files()
        if "judge_all(" in path.read_text(encoding="utf-8")
        and rel not in TRIGGER_PARTS
    ]
    assert callers == []

    #: 조립 층이 **만드는** 것은 수집기와 통합기다.
    timing_builds = {
        node.func.id
        for node in ast.walk(ast.parse(source_of("engine/timing.py")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith("Trigger")
    }
    assert timing_builds == {"TriggerChainIntegrator", "TriggerCollector", "TriggerError"}


def test_16_the_refusal_code_default_would_have_been_right():
    """
    **§6: M3 가 자기 방어 장치를 스스로 무력화한다** (3-E-38 이 기록).

    ``trigger_chain`` 의 ``_refusal_code`` 기본값이
    ``CANDIDATE_NOT_ELIGIBLE`` 이다 — gate 가 코드를 적지 않았다면 저절로 맞는
    답이 나왔을 자리다.
    """
    chain_source = source_of("engine/trigger_chain.py")
    assert "return ValidationCode.CANDIDATE_NOT_ELIGIBLE" in chain_source
    assert (
        CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    )


# ======================================================================
# 17 ~ 19 — R-1 / R-2 (구조적 위험)
# ======================================================================


def test_17_one_code_has_a_live_and_a_dormant_carrier_that_disagree():
    """
    **R-1 (§7): ``CHAIN_DEFINITION_UNAVAILABLE`` 의 두 carrier 가 갈라진다.**

    ``engine/chain.py`` (**live**) 는 ``ChainResolutionStatus.INVALID_CHAIN_LINK``
    와 짝짓고, ``engine/trigger_chain.py`` (**dormant**) 는
    ``ChainInsertion.UNKNOWN`` 과 짝짓는다. 확정 거부 ↔ 모름이므로 어느 한쪽으로
    접으면 다른 쪽이 거짓이 된다.

    **그래서 Phase 3-E-40 이 그 코드만 policy 에서 ``None`` 으로 두었다.** 즉
    dormant 구조가 live policy 의 한 칸을 묶어 두고 있다 — 이것이 이번 Phase 가
    찾은 가장 분명한 구조적 위험이다 (동작 영향은 없다, ``test_20``).
    """
    closure = duel_closure()
    assert "engine.chain" in closure
    assert "engine.trigger_chain" not in closure

    live = source_of("engine/chain.py")
    dormant = source_of("engine/trigger_chain.py")
    assert "ValidationCode.CHAIN_DEFINITION_UNAVAILABLE" in live
    assert "ValidationCode.CHAIN_DEFINITION_UNAVAILABLE" in dormant
    assert "ChainResolutionStatus.INVALID_CHAIN_LINK" in live
    assert "ChainInsertion.UNKNOWN" in dormant

    #: 그리고 policy 가 그 하나만 비워 두었다.
    undecided = [
        name
        for name in ValidationCode.__members__
        if CODE_VALIDITY[ValidationCode[name]] is None
    ]
    assert undecided == ["CHAIN_DEFINITION_UNAVAILABLE"]


def test_18_only_four_codes_have_a_dormant_carrier_at_all():
    """
    **§5 · §7: dormant carrier 를 가진 코드가 넷뿐이다.**

    나머지 44개는 dormant 층과 아무 관계가 없다 — 위험의 **범위**가 좁다는
    뜻이고, 그래서 이 Phase 가 "구조 전체가 위험하다" 고 적지 않는다.
    """
    members = set(ValidationCode.__members__)
    dormant_rels = set(TRIGGER_PARTS)
    with_dormant = set()
    for rel in sorted(dormant_rels):
        for node in ast.walk(ast.parse(source_of(rel))):
            if not isinstance(node, ast.Call):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, ast.Attribute) and arg.attr in members:
                    with_dormant.add(arg.attr)
    #: 여덟이다. 처음에 넷으로 적었는데, 그 넷은 **같은 호출에서 status 와 짝지은**
    #: 것만 센 결과였다 — 더 좁은 모양이다. 전체는 (3-E-43 당시) 일곱이었고,
    #: 그중 live 쪽과 **status 가 어긋나는 것이 하나** 있었다 (``test_17``).
    #:
    #: **3-E-45 가 ``INFORMATION_UNAVAILABLE`` 을 더해 여덟이 되었다.**
    #: ``_event_relation`` 이 "필터를 읽을 수 없다" 를 그 코드로 돌려주기
    #: 때문이다 — 새 코드를 만든 것이 아니라 **이미 있던 코드를 모름 쪽에
    #: 쓴 것**이고, 그래서 어긋남은 이제 **0개**다.
    assert with_dormant == {
        "OK",
        "RULE_NOT_IMPLEMENTED",
        "EXECUTION_FORBIDDEN",
        "CHAIN_DEFINITION_UNAVAILABLE",
        "CANDIDATE_NOT_ELIGIBLE",
        "HIDDEN_CARD",
        "SOURCE_WRONG_ZONE",
        "INFORMATION_UNAVAILABLE",
    }
    #: 40개는 dormant 층과 아무 관계가 없다 — 위험의 범위가 좁다.
    assert len(members - with_dormant) == 40


def test_19_four_of_the_five_dormant_gates_duplicate_a_live_question():
    """
    **R-2 (§9): 중복이 실재한다 — 다섯 관문 중 넷.**

    dormant 판정기 ``TriggerEligibilityJudge.judge`` 의 다섯 관문과 live
    ``Duel._activation_gate`` 의 세 관문을 나란히 놓으면:

    ==================== ===========================================
    ``EVENT_RELATION``     **live 대응 없음** — live 경로에는 사건이 없다
    ``ACTIVATION_ZONE``    ``ActionValidator`` 의 존 요구
    ``TRIGGER_CONDITION``  ``EffectActivator.can_activate`` 의 조건
    ``EXECUTION_AUTHORITY`` ``_check_authority`` (ADR-004 출처 금지)
    ``COST_FEASIBILITY``   ``_activation_actions`` 의 ``definition.cost.costs``
    ==================== ===========================================

    같은 질문을 두 구현이 따로 답한다. 지금은 한쪽이 돌지 않으므로 해가 없지만,
    연결하는 순간 **둘이 같은 답을 내는지**가 먼저 증명되어야 한다.
    """
    trigger_source = source_of("engine/trigger.py")
    gates = [
        name
        for name in (
            "EVENT_RELATION",
            "ACTIVATION_ZONE",
            "TRIGGER_CONDITION",
            "EXECUTION_AUTHORITY",
            "COST_FEASIBILITY",
        )
        if f"{name} = " in trigger_source
    ]
    assert len(gates) == 5

    #: live 쪽 세 관문이 한 자리에 모여 있다 (STRUCTURAL-134).
    duel_source = source_of("engine/duel.py")
    assert "def _activation_gate" in duel_source
    assert "ActionValidator" in duel_source
    assert "ActivationTimingChecker" in duel_source
    assert "can_activate" in duel_source
    #: 비용 관문은 후보 생성 쪽에 있다.
    assert "definition.cost.costs" in duel_source


# ======================================================================
# 20 ~ 26 — 영향 없음 (불변식)
# ======================================================================


@requires_official_db
def test_20_the_dormant_structure_changes_no_duel_outcome(repository):
    """**§8: Engine V1 동작에 영향이 없다 — 네 정책 조합이 전부 완주한다.**"""
    from agent.arena import (
        make_first_legal,
        make_random,
        make_rule_based,
        make_search,
        run_match,
    )

    for factories in (
        (make_search(), make_search()),
        (make_search(), make_rule_based()),
        (make_search(), make_random(500)),
        (make_search(), make_first_legal()),
    ):
        match = run_match(
            repository, decks=(list(DECK), list(DECK)), seed=2, factories=factories
        )
        assert match.outcome.value == "completed"
        assert match.refusals == 0
        assert len(match.state_hash) == 64


def test_21_no_ai_or_search_module_knows_the_pipeline():
    """**§9: AI/Search 가 trigger 구조를 직접 참조하지 않는다.**"""
    for rel in (
        "agent/search.py",
        "agent/simulation.py",
        "agent/evaluation.py",
        "agent/policy.py",
        "agent/heuristic.py",
        "agent/arena.py",
        "agent/runner.py",
    ):
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for name in ("Trigger", "trigger", "TimingEvent", "event_pipeline"):
            assert name not in source, (rel, name)


@requires_official_db
def test_22_reading_and_playing_leaves_the_board_and_randomness_alone(repository):
    """**§10: ``state_hash`` · RNG 불변 — 이 감사가 아무것도 건드리지 않았다.**"""
    from engine.duel import Duel

    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=11)
    while duel.advance() is not None:
        pass
    before_hash = duel.state.state_hash()
    before_draws = duel.state.randomness.draws

    for seat in (0, 1):
        duel.legal_actions(seat)
    assert duel.state.state_hash() == before_hash
    assert duel.state.randomness.draws == before_draws


@requires_official_db
def test_23_the_hidden_information_boundary_is_untouched(repository):
    """**§10: 관측 경계 그대로.** 상대 패가 가려져 있다."""
    from engine.duel import Duel

    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=11)
    while duel.advance() is not None:
        pass
    view = duel.view(0)
    assert view.player(1).hand.concealed is True
    assert view.player(1).hand.cards == ()
    assert view.player(0).hand.concealed is False


def test_24_the_validation_vocabulary_is_unchanged():
    """**§10 · 전제: 어휘가 그대로다.**"""
    from agent.simulation import SimulationStatus
    from engine.validation import unknown_codes

    assert len(ValidationCode) == 48
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5
    assert len(unknown_codes()) == 7
    assert len(CODE_VALIDITY) == 48


def test_25_this_phase_changed_no_production_file():
    """
    **AUDIT-ONLY: 다섯 모듈의 줄 수가 그대로다.**

    .. note::
       ``engine/trigger.py`` 는 1,565 → 1,644 (Phase 3-E-45 의
       ``_event_relation`` 판정 수정) → 1,661 (Phase 3-F-11 의 docstring) 이고,
       ``engine/event_pipeline.py`` 는 417 → 429 (같은 Phase 의 docstring) 다.
       3-E-43 자신은 한 줄도 바꾸지 않았고, **나머지 네 모듈의 숫자가 그대로인
       것**이 그 증거다. 움직인 두 모듈도 문자열 리터럴을 지운 AST 가 전후
       동일하므로 production behavior 는 바뀌지 않았다.
    """
    sizes = {
        rel: len(source_of(rel).splitlines())
        for rel in TRIGGER_PARTS + TRIGGER_ASSEMBLY + (LIVE_TIMING,)
    }
    assert sizes == {
        "engine/trigger.py": 1661,
        "engine/trigger_chain.py": 594,
        "engine/trigger_order.py": 443,
        "engine/timing.py": 436,
        "engine/event_pipeline.py": 429,
        "engine/activation_timing.py": 541,
    }


def test_26_no_event_bus_or_new_graph_was_introduced():
    """
    **금지 목록 확인: 새 EventBus · graph architecture 를 만들지 않았다.**

    .. note::
       ``engine/event_pipeline.py`` 에 ``EventBus`` 라는 **말**이 한 번 나온다 —
       "EventBus 도, 구독 · 발행 프레임워크도 **만들지 않는다**" 라는 설명이다.
       즉 그 모듈이 스스로 그것을 피했다고 적어 둔 자리이고, 구현이 아니다.
       처음에 문자열로 세어 그 문장을 걸렀고, 구문으로 세도록 고쳤다.
    """
    for forbidden in ("EventBus", "EventGraph", "TriggerBus", "EventDispatcher"):
        for rel, path in production_engine_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            defined = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            }
            used = {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            }
            assert forbidden not in defined, (rel, forbidden)
            assert forbidden not in used, (rel, forbidden)

    #: 그리고 그 설명이 실제로 거기 있다 — 회피가 기록되어 있다.
    assert "EventBus 도, 구독 · 발행 프레임워크도 만들지 않는다" in source_of(
        "engine/event_pipeline.py"
    )
