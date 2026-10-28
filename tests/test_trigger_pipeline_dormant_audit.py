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
import collections
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


#: production 패키지 전부. 🔴 ``engine`` 만 뒤지면 ``engine`` 밖으로 옮긴
#: 코드가 감사를 피한다 (Phase 6-I 가 ``integration`` 을 더하면서 생긴
#: 구멍이고, 그 구멍을 열어 두지 않는다).
PRODUCTION_PACKAGES = (
    "engine",
    "integration",
    "analysis",
    "agent",
    "core",
    "sources",
    "deck",
    "app",
    "rules",
    "rulings",
)


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
        #: 1,661 → **1,681** (Phase 6-B). ``TimingEvent.from_journal_event`` 에
        #: ``ActionEvent`` 분기가 생겼다 — 새 ``EventKind.ACTION`` 이 그 함수에
        #: 닿으면 ``TriggerError`` 로 **통째로 실패**하기 때문에 막은 것이다.
        #: 🔴 **활성화가 아니다.** 돌려주는 값이
        #: :meth:`TimingEvent.unimplemented` 이고, 그것은 "옮길 이름이 없다" 를
        #: 적는 자리다 (지어낸 시점 이름이 아니다). production 호출자는
        #: 여전히 0개다 — ``test_02`` 가 그것을 따로 센다.
        # 🔴 1,729 → 1999 (Phase 6-F 의 주체 축: TriggerSubject ·
        # SUBJECT_AWARE_POINTS · subject_relation · _from_relation ·
        # 네 갈래 관문). **"크다" 는 요지는 그대로다.**
        #
        # 🔴 1999 → **2059** (Phase 6-H 의 ``TriggerSubject.OTHER`` ·
        # ``GROUP_MEMBERSHIP_RULE`` · ``subject_relation`` 의 두 분기).
        # **dormant 를 깨지 않는다** — 늘어난 코드는 선언을 더 좁게 만들고
        # 거부를 하나 더 낼 뿐, 후보를 모으는 자리를 늘리지 않았다.
        # ``compile_trigger_spec`` 의 production 호출자는 여전히 0곳이고
        # (6-H 보고서 §16), ``TriggerRegistry`` 를 만드는 production 자리도
        # 여전히 0곳이다 (``test_13``).
        # 🔴 2059 → **2199** (Phase 6-V). ``summoned_zone_for`` ·
        # ``_zone_from_summon`` · ``_activation_zone`` 의 설명이다.
        # **dormant 를 깨지 않는다** — 늘어난 코드는 관문 하나를 사건이
        # 말해 준 자리에서만 열고, 후보를 모으는 자리를 늘리지 않았다.
        # ``TriggerRegistry`` 를 만드는 production 자리는 여전히 0곳이다
        # (``test_13``).
        # 🔴 2199 → **2309** (Phase 6-AB 보완5). ``graveyard_zone_for`` ·
        # ``_zone_from_grave`` · ``_activation_zone`` 의 설명이고, 6-V 와
        # **같은 결의 증가**다 (그 핀의 설명 참고).
        # **dormant 를 깨지 않는다** — 늘어난 코드는 관문 하나를 사건이
        # 말해 준 자리(묘지 도착)에서만 열고, 후보를 모으는 자리를 늘리지
        # 않았다. ``TriggerRegistry`` 를 만드는 production 자리는 여전히
        # 0곳이다 (``test_13``).
        "engine/trigger.py": 2309,
        #: 🔴 594 → **648** (Phase 6-Y). ``plan`` 이 밖에서 정해진 대상
        #: 선택을 받는 통로 하나다 (``selections=None`` 기본값).
        #:
        #: 🔴 **이번에는 dormant 가 깨졌다.** 앞의 갱신들은 전부 "늘어난
        #: 코드가 후보를 모으는 자리를 늘리지 않았다" 였는데, 6-Y 는
        #: ``integration/autonomy.py`` 에서 이 모듈을 **실제로 돌린다**
        #: (``test_trigger_connectivity_audit::test_04`` ·
        #: ``test_trigger_ownership_audit::test_10``). 그래서 이 파일의
        #: 이름이 말하는 "dormant" 는 이제 ``engine/duel.py`` 에 대해서만
        #: 참이다 — ``legal_actions`` 는 여전히 유발을 제공하지 않는다
        #: (``BLOCKER-6Y-1``).
        "engine/trigger_chain.py": 648,
        "engine/trigger_order.py": 443,
    }
    #: 2,698 → **2,718** (Phase 6-B 의 ``ActionEvent`` 가드 +20)
    #: → **2,766** (Phase 6-E 의 ``TimingEvent.summon`` · ``TriggerSpec.summons``
    #: +48). 🔴 그 48줄은 **거짓 양성을 막기 위한 칸 하나와 설명**이다 —
    #: Lua 는 일반 소환(``EVENT_SUMMON_SUCCESS``)과 특수 소환
    #: (``EVENT_SPSUMMON_SUCCESS``)을 다른 사건으로 등록하는데 엔진에는
    #: ``MONSTER_SUMMONED`` 하나뿐이어서, 구분을 적지 않으면 "일반 소환했을
    #: 때" 카드가 특수 소환에도 후보가 된다.
    #: 🔴 3,036 → **3,096** (Phase 6-H). ``engine/trigger.py`` 만 +60 이고
    #: 나머지 두 모듈은 **한 줄도 바뀌지 않았다** — 그것이 이번 변경이
    #: 축 하나에만 닿았다는 증거다.
    #: 🔴 3,096 → **3,236** (Phase 6-V). "크다" 는 요지는 그대로다.
    #: 🔴 3,236 → **3,290** (Phase 6-Y: ``trigger_chain`` +54).
    #: 🔴 3,290 → **3,400** (보완5: ``trigger.py`` +110). 나머지 두 모듈은
    #: **한 줄도 바뀌지 않았다** — 이번 변경이 축 하나(묘지 도착의 발동
    #: 자리)에만 닿았다는 증거다.
    assert sum(sizes.values()) == 3400


def test_02_the_two_assembly_modules_exist():
    """
    **§2: 조립 층이 865줄이다.**

    .. note::
       **853 → 865 → 936** (Phase 3-F-11 · 3-F-14).

       ``engine/event_pipeline.py`` 가 417 → 429 → **500** 이다.

       * 3-F-11 의 +12 는 ``EventContext.actor`` 의 docstring 뿐이고 **코드는
         한 줄도 바뀌지 않았다**.
       * 🔴 **3-F-14 의 +71 은 코드를 바꿨다** — 이 Phase 계열에서 처음이다.
         ``read``/``read_deltas``/``observe``/``collect`` 의 actor 기본값을
         보초값(``_ACTOR_OMITTED``)으로 바꾸고, ``result.action.actor`` 자동
         파생을 **지웠다**. 생략과 "없다고 말한 것" 을 가르는 계약이다
         (3-F-12 가 측정 · 3-F-13 이 판정 · 3-F-14 가 구현).

       **그래도 dormant 는 그대로다.** 이 모듈의 production importer 는 여전히
       0개이고 (``test_03`` · ``test_04``), trigger pipeline 은 켜지지 않았다 —
       바뀐 것은 **아무도 부르지 않는 입구의 입력 계약**이다.
    """
    sizes = {rel: len(source_of(rel).splitlines()) for rel in TRIGGER_ASSEMBLY}
    assert sizes == {"engine/timing.py": 436, "engine/event_pipeline.py": 500}
    assert sum(sizes.values()) == 936


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
    **§3 · §4: 조립 층을 import 하는 production 파일.**

    이것이 dormant 의 **구조적 까닭**이었다 — 부품이 있고 조립도가 있는데,
    조립도를 펴는 사람이 없었다.

    🔴 **Phase 6-I 에서 그 사람이 생겼다.** ``engine/trigger_observation.py``
    가 ``engine.event_pipeline`` 을 펴고, 실제 ``Duel`` 기록에서 후보를 모아
    기존 판정기에 넘긴다. 이 테스트가 틀린 전제를 갖고 있었던 것이 아니라 —
    6-H 까지는 실제로 0곳이었고 그것이 측정값이었다 — **그 사실이 이번
    Phase 의 산출물로 바뀌었다.**

    ``engine.timing`` 은 **여전히 0곳**이다. 그 모듈은 수집·정렬·체인 삽입을
    한 줄로 잇는 더 윗층이고, 이번 단계는 체인을 만들지 않는다 (6-I §15).
    둘을 갈라서 세는 것이 "어디까지 켜졌는가" 를 정확히 말한다.
    """
    assert importers_of("engine.timing") == []
    assert importers_of("engine.event_pipeline") == [
        "engine/trigger_observation.py"
    ]


def test_05_the_part_modules_are_reachable_only_through_the_assembly():
    """**§3: 부품은 조립 층(과 서로)만이 가져온다.**"""
    assert importers_of("engine.trigger_chain") == ["engine/timing.py"]
    assert importers_of("engine.trigger_order") == [
        "engine/timing.py",
        "engine/trigger_chain.py",
    ]
    #: ``trigger.py`` 는 예외다 — live 쪽에서도 하나를 가져간다 (``test_07``).
    #: 🔴 Phase 6-E 에서 ``engine/trigger_compiler.py`` 가 늘었다 —
    #: STRUCTURAL-7(카드 데이터에서 트리거를 뽑는 컴파일러)이 생겼기
    #: 때문이다. **휴면 모듈 넷은 그대로 휴면이다** (아래 test_06 이
    #: 고정한다) — ``trigger.py`` 를 읽는 자리가 늘었다는 것이 파이프라인이
    #: 돌기 시작했다는 뜻이 아니다.
    #: 🔴 Phase 6-I 에서 ``engine/trigger_observation.py`` 가 늘었다 — 실제
    #: 사건을 기존 수집기·판정기에 넘기는 자리다. **휴면 모듈 넷은 그대로
    #: 휴면이다** (``test_06`` 이 고정한다): 이 모듈은 ``Duel`` 의 import
    #: 폐쇄 **밖**에 있고, 듀얼이 그것을 부르지 않는다. 관찰은 듀얼이 아니라
    #: 부르는 쪽이 한다.
    assert importers_of("engine.trigger") == [
        "engine/activation_timing.py",
        "engine/event_pipeline.py",
        "engine/timing.py",
        "engine/trigger_chain.py",
        "engine/trigger_compiler.py",
        "engine/trigger_observation.py",
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
    #: 67 이다. 이 감사의 질문은 **engine 안의** 도달성이므로 58 이 기준이다.
    #:
    #: Phase 6-C 에서 57 → 58. 늘어난 하나는 ``engine.archetype`` 이고,
    #: ``engine.condition.model`` 이 그것을 import 하기 때문이다 — 조건
    #: 계층은 원래 폐쇄 안이었다. 🔴 **휴면 모듈 넷은 그대로 폐쇄 밖이다**
    #: (아래 루프가 그것을 고정한다). 즉 이 수가 는 것이 트리거 계층이
    #: 켜졌다는 뜻이 아니다.
    #: 🔴 58 → **59** (Phase 6-V)? **아니다** — 6-V 는 새 모듈을 만들지
    #: 않았다. 늘어난 하나는 ``engine.archetype_compiler`` 이고,
    #: ``engine.effect.library`` 가 기르수 ① 의 카드군 조건을 만들려고
    #: 그것을 import 하기 때문이다 (숫자를 손으로 적지 않는 쪽을 골랐다).
    #:
    #: 🔴 **휴면 모듈 넷은 그대로 폐쇄 밖이다** — 아래 루프가 그것을
    #: 고정하고, 그것이 이 감사의 질문이다. 트리거 계층이 켜진 것이 아니다.
    assert len(closure) == 59
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
    """
    **§3: ``duel.py`` 가 사건 파이프라인의 코드를 읽지 않는다.**

    🔴 **Phase 6-Z 가 재는 모양을 바꿨다.** 유발 후보를 ``Duel`` 에 **값으로**
    넣었으므로 (``triggers: object | None``) 낱말 검사가 통하지 않는다. 대신
    그 검사가 재려던 것을 센다 — 파이프라인과 트리거 계층의 **이름**을
    아는가. 모른다.

    (``test_03`` 과 같은 자리이고 같은 이유다. 이쪽은 ``event_pipeline`` 축을
    함께 센다.)
    """
    duel = source_of("engine/duel.py")
    for name in (
        "event_pipeline",
        "EventPipeline",
        "EventContext",
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerChainIntegrator",
        "TimingEvent",
        "TimingPoint",
    ):
        assert name not in duel, name
    assert "triggers: object | None = None" in duel


def test_13_only_the_compiler_builds_a_declaration_and_nobody_builds_a_registry():
    """
    🔴 **이 테스트의 계약이 Phase 6-E 에서 반쯤 뒤집혔다.**

    원래 단정은 ``TriggerSpec`` · ``TriggerRegistry`` 의 production 생성이
    **0곳**이라는 것이었고, 3-E-33 이후 여러 Phase 가 같은 사실을 쟀다.
    그 진술은 **쓰여진 시점에 맞았다** — 카드 데이터에서 트리거를 뽑는
    컴파일러가 없었기 때문이고, ``TriggerRegistry`` 의 설명이 그것을
    STRUCTURAL-7 로 적어 두었다.

    Phase 6-E 가 그 컴파일러를 만들었다. 그래서 둘을 **갈라서** 센다.

    - ``TriggerSpec`` 생성 — **1곳** (``trigger_compiler.py``). 카드
      데이터에서 선언을 만드는 자리이고, 그것이 6-E 의 산출물이다.
    - ``TriggerRegistry`` 생성 — 6-H 까지 **0곳**이었다. 🔴 **Phase 6-I 가
      그 자리를 만들었다** (``integration/trigger_registry.py``). 누가 어떤
      선언을 등록할지를 이제 production 이 정한다 — 관측에 **보이는 카드**가
      정한다.

    🔴 **이 테스트의 탐색 범위도 함께 넓혔다.** 원래 ``engine/`` 만 뒤졌고,
    그래서 등록소를 ``engine`` 밖에서 만들면 이 감사가 **조용히 참이 된다.**
    그것은 감사가 아니라 눈가림이므로 production 패키지 전체를 뒤진다.

    ``duel.py`` 는 **그대로다** — ``test_12`` 가 "trigger" 라는 말이 없음을
    여전히 고정한다. 등록소를 듀얼이 들고 있지 않고, 관찰은 부르는 쪽이
    한다 (``engine/trigger_observation.py`` 의 머리말이 그 선택과 대안을
    적는다).
    """
    built = collections.defaultdict(list)
    for package in PRODUCTION_PACKAGES:
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            rel = str(path.relative_to(PROJECT_ROOT))
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("TriggerSpec", "TriggerRegistry")
                ):
                    built[node.func.id].append(f"{rel}:{node.lineno}")

    assert [site.split(":")[0] for site in built["TriggerSpec"]] == [
        "engine/trigger_compiler.py"
    ], dict(built)
    assert [site.split(":")[0] for site in built["TriggerRegistry"]] == [
        "integration/trigger_registry.py"
    ], dict(built)


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
       ``engine/event_pipeline.py`` 는 417 → 429 (같은 Phase 의 docstring)
       → **500** (Phase 3-F-14 의 actor 입력 계약) 다. 3-E-43 자신은 한 줄도
       바꾸지 않았고, **나머지 네 모듈의 숫자가 그대로인 것**이 그 증거다.

       🔴 3-F-14 는 ``event_pipeline.py`` 의 **코드**를 바꿨다 (앞의 Phase 들과
       다르다). 그래도 이 테스트가 보는 다섯 모듈 중 넷은 그대로이고, 트리거
       파이프라인은 여전히 dormant 다 — 바뀐 것은 입구의 입력 계약뿐이다.

       ``engine/activation_timing.py`` 는 541 → **570** (Phase 3-F-26 의 모듈
       docstring) 이다.

    .. warning::
       🔴 **Phase 3-F-26 이 이 테스트의 가정을 정정했다.** 원래 이 테스트는
       *"줄 수가 그대로다"* 만으로 dormant 를 주장했는데, **줄 수는 주석과
       코드를 구분하지 못한다.** 그래서 docstring 만 고친 Phase 가 올 때마다
       숫자를 갱신해야 했고 (3-E-45 · 3-F-11 · 3-F-14 · 3-F-26), 그 갱신은
       "코드가 그대로인가" 를 **증명하지 않는다.**

       약화하지 않고 **보강**했다 — 문자열 리터럴을 벗긴(즉 **주석 · docstring
       에 둔감한**) 줄 수를 함께 못 박는다. 이 숫자는 docstring 을 고쳐도
       움직이지 않고, **실행 코드를 고치면 움직인다.** 원래의 원본 줄 수 핀은
       그대로 남겨 둔다.
    """
    sizes = {
        rel: len(source_of(rel).splitlines())
        for rel in TRIGGER_PARTS + TRIGGER_ASSEMBLY + (LIVE_TIMING,)
    }
    assert sizes == {
        #: 1,661 → **1,681** (Phase 6-B). 위 ``executable`` 핀의 설명 참고 —
        #: 늘어난 것은 ``ActionEvent`` 가드이고 활성화가 아니다.
        # 🔴 1,729 → 1999 (Phase 6-F 의 주체 축: TriggerSubject ·
        # SUBJECT_AWARE_POINTS · subject_relation · _from_relation ·
        # 네 갈래 관문). **"크다" 는 요지는 그대로다.**
        #
        # 🔴 1999 → **2059** (Phase 6-H 의 ``TriggerSubject.OTHER`` ·
        # ``GROUP_MEMBERSHIP_RULE`` · ``subject_relation`` 의 두 분기).
        # **dormant 를 깨지 않는다** — 늘어난 코드는 선언을 더 좁게 만들고
        # 거부를 하나 더 낼 뿐, 후보를 모으는 자리를 늘리지 않았다.
        # ``compile_trigger_spec`` 의 production 호출자는 여전히 0곳이고
        # (6-H 보고서 §16), ``TriggerRegistry`` 를 만드는 production 자리도
        # 여전히 0곳이다 (``test_13``).
        # 🔴 2059 → **2199** (Phase 6-V). ``summoned_zone_for`` ·
        # ``_zone_from_summon`` · ``_activation_zone`` 의 설명이다.
        # **dormant 를 깨지 않는다** — 늘어난 코드는 관문 하나를 사건이
        # 말해 준 자리에서만 열고, 후보를 모으는 자리를 늘리지 않았다.
        # ``TriggerRegistry`` 를 만드는 production 자리는 여전히 0곳이다
        # (``test_13``).
        # 🔴 2199 → **2309** (Phase 6-AB 보완5). ``graveyard_zone_for`` ·
        # ``_zone_from_grave`` · ``_activation_zone`` 의 설명이고, 6-V 와
        # **같은 결의 증가**다 (그 핀의 설명 참고).
        # **dormant 를 깨지 않는다** — 늘어난 코드는 관문 하나를 사건이
        # 말해 준 자리(묘지 도착)에서만 열고, 후보를 모으는 자리를 늘리지
        # 않았다. ``TriggerRegistry`` 를 만드는 production 자리는 여전히
        # 0곳이다 (``test_13``).
        "engine/trigger.py": 2309,
        #: 🔴 594 → **648** (Phase 6-Y). ``plan`` 이 밖에서 정해진 대상
        #: 선택을 받는 통로 하나다 (``selections=None`` 기본값).
        #:
        #: 🔴 **이번에는 dormant 가 깨졌다.** 앞의 갱신들은 전부 "늘어난
        #: 코드가 후보를 모으는 자리를 늘리지 않았다" 였는데, 6-Y 는
        #: ``integration/autonomy.py`` 에서 이 모듈을 **실제로 돌린다**
        #: (``test_trigger_connectivity_audit::test_04`` ·
        #: ``test_trigger_ownership_audit::test_10``). 그래서 이 파일의
        #: 이름이 말하는 "dormant" 는 이제 ``engine/duel.py`` 에 대해서만
        #: 참이다 — ``legal_actions`` 는 여전히 유발을 제공하지 않는다
        #: (``BLOCKER-6Y-1``).
        "engine/trigger_chain.py": 648,
        "engine/trigger_order.py": 443,
        "engine/timing.py": 436,
        "engine/event_pipeline.py": 500,
        #: 🔴 570 → **618** (Phase 6-AB 최종 보완). ``ActivationTiming`` 에
        #: ``simultaneous`` 칸과 그 타입 검사, ``ActivationTimingChecker`` 의
        #: 이른 통과 하나, 그리고 그 둘의 설명이다.
        #:
        #: 🔴 **이 모듈은 dormant 가 아니다** — ``LIVE_TIMING`` 으로 따로
        #: 둔 이유가 그것이고, ``Duel._activation_gate`` 가 실제로 쓴다.
        #: 이 핀이 재는 것은 "얼마나 바뀌었는가" 이고, 아래의 문자열에
        #: 둔감한 핀이 **실행 코드가 움직였다**는 사실을 따로 잡는다.
        #:
        #: 🔴 618 → **804** (Phase 6-AB 보완6). ``ActivationStage`` 와
        #: ``_by_stage`` 그리고 그 둘의 설명이다. 아래의 문자열에 둔감한
        #: 핀이 실행 코드 43줄을 따로 잡는다 — 나머지 143줄은 설명이다.
        "engine/activation_timing.py": 804,
    }

    #: 🔴 주석 · docstring 에 둔감한 핀 (Phase 3-F-26 이 더했다).
    class _StripStrings(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802 - ast 규약
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value=""), node)
            return node

    executable = {
        rel: len(
            ast.unparse(
                _StripStrings().visit(ast.parse(source_of(rel)))
            ).splitlines()
        )
        for rel in TRIGGER_PARTS + TRIGGER_ASSEMBLY + (LIVE_TIMING,)
    }
    assert executable == {
        #: 735 → **737** (Phase 6-B). 🔴 **이번에는 docstring 이 아니라 실행
        #: 코드가 2줄 늘었다** — ``isinstance(event, ActionEvent)`` 한 줄과
        #: ``return cls.unimplemented(...)`` 한 줄이다. 이 핀이 그 사실을
        #: 정확히 잡았고, 그것이 이 핀을 둔 이유다 (3-F-26 이 "줄 수는 주석과
        #: 코드를 구분하지 못한다" 고 적으며 더한 핀).
        #:
        #: 늘어난 2줄이 **dormant 를 깨지 않는 이유**: 그 분기는 새 사건
        #: 종류가 이 함수에 닿았을 때 **예외를 던지지 않게** 막는 가드이고,
        #: 돌려주는 것은 ``UNIMPLEMENTED`` 시점이다. 후보를 모으지도, 체인에
        #: 넣지도, 부르는 자리를 늘리지도 않았다.
        #:
        #: 737 → **748** (Phase 6-E). 🔴 **또 실행 코드다** — 11줄이고
        #: 전부 "거짓 양성을 막는 칸" 이다: ``TimingEvent.summon`` 프로퍼티,
        #: ``TriggerSpec.summons`` 칸과 그 타입·시점 검사,
        #: ``matches`` 의 한 줄, 직렬화 두 줄.
        #:
        #: 이것이 **dormant 를 깨지 않는 이유**: 늘어난 코드는 전부
        #: *선언을 더 좁게* 만드는 것이고, 후보를 모으는 자리를 늘리지
        #: 않았다. ``duel.py`` 는 여전히 "trigger" 라는 말을 쓰지 않고
        #: (``test_12``) ``TriggerRegistry`` 를 만드는 production 자리도
        #: 여전히 0곳이다 (``test_13``).
        # 🔴 748 → 806 (Phase 6-F). "크다" 는 요지는 그대로다.
        #
        # 🔴 806 → **813** (Phase 6-H). **실행 코드 7줄이다** —
        # ``TriggerSubject.OTHER`` 멤버 한 줄, ``GROUP_MEMBERSHIP_RULE``
        # 한 줄, ``subject_relation`` 의 두 분기 다섯 줄. 이 핀이 "주석이
        # 아니라 코드가 늘었다" 를 정확히 잡는 것이 핀을 둔 이유다.
        #
        # 늘어난 7줄이 **dormant 를 깨지 않는 이유**: 하나는 축의 값이고
        # 나머지는 **거부 하나와 모름 하나**를 내는 분기다. 통과를 내는
        # 자리는 하나도 늘지 않았고 (``test_15`` 가 ``OTHER`` 가 ``VALID``
        # 를 낼 수 없음을 격자로 고정한다), 후보를 모으는 자리도 그대로다.
        #: 🔴 813 → **840** (Phase 6-V). 🔴 **docstring 이 아니라 실행
        #: 코드가 27줄 늘었다** — ``summoned_zone_for`` 와
        #: ``_zone_from_summon`` 의 갈래들이다. 이 핀이 그 사실을 정확히
        #: 잡는다. 늘어난 코드가 하는 일은 **관문 하나의 답**을 바꾸는
        #: 것이고, dormant 모듈을 부르는 자리는 하나도 더하지 않았다.
        # 🔴 840 → **868** (보완5). **실행 코드 28줄이다** —
        # ``graveyard_zone_for`` 의 본문 일곱 줄, ``_zone_from_grave`` 의
        # 세 거름과 세 판정, ``_activation_zone`` 의 둘째 분기 두 줄,
        # 관문 호출의 ``moved_to=`` 한 줄, ``__all__`` 한 줄.
        #
        # **dormant 를 깨지 않는다** — 늘어난 코드는 관문 하나가 **사건이
        # 말해 준 자리**를 읽게 하는 것이고, 후보를 모으는 자리를 늘리지
        # 않았다. ``duel.py`` 는 여전히 "trigger" 라는 말을 쓰지 않고
        # (``test_12``) ``TriggerRegistry`` 를 만드는 production 자리도
        # 여전히 0곳이다 (``test_13``).
        "engine/trigger.py": 868,
        #: 🔴 257 → **268** (Phase 6-Y). 문자열을 벗긴 줄 수가 **11줄**
        #: 늘었다 — ``plan`` 의 키워드 인자와 ``decided`` 사전, ``_entry`` 의
        #: 인자 하나, ``_missing_execution_inputs`` 의 ``answered`` ·
        #: ``waiting`` 계산, 링크의 ``selections=chosen``. 나머지 43줄은
        #: docstring 이고 이 핀은 그것에 둔감하다.
        #:
        #: 🔴 **실행 코드가 움직였다는 것이 요지다.** 앞의 Phase 들은 이
        #: 핀을 움직이지 않았거나(docstring 만 고쳤다) 움직여도 dormant 를
        #: 깨지 않았는데, 6-Y 는 깼다.
        "engine/trigger_chain.py": 268,
        "engine/trigger_order.py": 194,
        "engine/timing.py": 194,
        "engine/event_pipeline.py": 227,
        #: 🔴 227 → **233** (Phase 6-AB 최종 보완). **실행 코드 6줄**이다 —
        #: ``simultaneous`` 칸 선언 한 줄, ``__post_init__`` 의 타입 검사
        #: 두 줄, ``ActivationTimingChecker`` 의 이른 통과 세 줄.
        #:
        #: 🔴 **스펠 스피드 제약을 없앤 것이 아니다.** 늘어난 분기는
        #: "같은 기회에서 동시에 쌓이는 묶음" 에만 통과를 내고, 그 사실은
        #: 판을 든 쪽(``Duel._is_simultaneous``)이 ``chain_floor`` 와 제안의
        #: 사건 번호로 답한다. 근거는 룰북 §When multiple cards are
        #: activated simultaneously 다.
        #:
        #: 🔴 233 → **276** (Phase 6-AB 보완6). **실행 코드 43줄**이다 —
        #: ``ActivationStage`` 열거(네 멤버 · ``describe_ko``)와 ``_STAGE_KO``
        #: 표, ``STAGE_MISSING`` · ``FAST_WINDOW_RULES`` 상수,
        #: ``ActivationTiming.stage`` 칸과 그 타입 검사,
        #: ``canonical_state`` · ``to_dict`` · ``describe_ko`` 의 단계 항목,
        #: 그리고 빈 체인을 단계별로 가르는 ``_by_stage`` 다.
        #:
        #: 🔴 **스펠 스피드 1 을 무조건 금지한 것이 아니다.** 늘어난 분기는
        #: ``FAST_WINDOW`` 에서만 거부를 내고, ``OPEN`` 과
        #: ``TRIGGER_REGISTRATION`` 은 그대로 통과한다. 단계를 말해 주지
        #: 않으면 ``UNKNOWN`` 이다 — 추측하지 않는다. 근거는 공식 Fast
        #: Effect Timing 의 상자 A 설명이다.
        "engine/activation_timing.py": 276,
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
