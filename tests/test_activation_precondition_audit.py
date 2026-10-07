"""
Phase 3-F-24 — 발동 **선행 정보** 감사: `EffectDefinition` · `SetCode(EVENT_*)` ·
activation-timing 이 "언제/어떻게 발동 가능한가" 를 어디까지 들고 있는가.

**AUDIT-ONLY.** production 을 한 줄도 바꾸지 않는다 (`test_25`).

🔴 먼저, 내 앞 Phase 의 틀을 **정정한다**
-----------------------------------------
Phase 3-F-23 보고서가 다음 Phase 후보를 *"`EffectDefinition` 의 유발 조건
(`SetCode(EVENT_*)`) **누락** 범위 감사"* 라고 적었다. **"누락" 이 부정확하다.**

측정하면 그 값은 **잃어버린 것이 아니다** — 파서 계층 `EffectSpec.code` 가
들고 있고(`EVENT_*` 16,727 블록 · `EFFECT_*` 14,044 블록 · 상수 298종),
`engine.ids.iter_effects` 로 **닿을 수도 있다.** 다만 `EffectDefinition` 으로
**옮기지 않는다**. 즉 **누락이 아니라 건너지 않은 경계**이고, 그 선택은
ADR-006("등록하지 않은 것은 실행되지 않는다")과 같은 태도다 (`test_05` · `test_06`).

앞선 감사가 이미 답한 것 — 다시 쓰지 않고 **이어서** 센다
---------------------------------------------------------
* **Phase 3-E-31** (`tests/test_effectdefinition_trigger_boundary_audit.py`) —
  `code` 칸이 `EffectSpec` 에만 있고 `TriggerSpec.point` 는 `EVENT_*` 의 사본이
  아니라는 것.
* **Phase 3-F-4** (`tests/test_trigger_condition_separation_audit.py`) —
  EVENT / TRIGGER CONDITION / ELIGIBILITY / ACTIVATION 네 단계의 LIVE·DORMANT 표.

이 파일이 **새로 재는** 것은 셋이다.

1. `EffectSpec.code` 한 칸에 **두 어휘가 섞여 있다** — `EVENT_*` 와 `EFFECT_*`
   (`test_04`). 이름만 보고 "유발 조건" 이라고 단정할 수 없다는 §3 의 경고가
   데이터로 확인된다.
2. `iter_effects` 는 **production 호출자가 0 이다** (`test_06`). "닿을 수 있다" 와
   "닿고 있다" 는 다른 말이다.
3. 함정 corpus 186종 vs **등재된 함정 5장은 전부 `EVENT_FREE_CHAIN`**
   (`test_08` · `test_09`) — 그래서 `TRAP_TRIGGER_MISSING` 이라는 문장은
   **corpus 전체에는 성립하지만 등재된 다섯 장에는 물리지 않는다.**

세 개념이 **서로 다른 계층**에 있다 (§6)
-----------------------------------------
=========================  ===========================================
유발 조건                   `TriggerSpec.point` · `condition` (DORMANT 등록 계층)
발동 가능 조건               `EffectDefinition.activation: Condition | None`
activation timing           `engine/activation_timing.py` —
                            `SpellSpeed` 는 **카드 종류**에서 나온다
=========================  ===========================================

하나의 필드로 뭉쳐 있지 않다 (`test_10` ~ `test_12`).
"""

import ast
import collections
import dataclasses
import inspect
import pathlib
import subprocess
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from core.card_model import EffectSpec
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    MONSTER_ACTIVATION_MISSING,
    TRAP_TRIGGER_MISSING,
    ActionValidator,
    ActionValidity,
)
from engine.activation import ActivationStatus
from engine.activation_timing import (
    ActivationTiming,
    ActivationTimingChecker,
    SpellSpeed,
)
from engine.chain import Chain, ChainLink
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, iter_effects
from engine.spell_activation import activatable_effects, duel_activator
from engine.state.game_state import GameState
from engine.trigger import TimingPoint, TriggerSpec
from engine.validation import ValidationCode
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
MYSELF = "tests/test_activation_precondition_audit.py"

MINE, THEIRS = 0, 1

#: 등재된 실제 카드 (공식 DB).
POT_OF_GREED = 55144522            # 통상 마법
DIAN_KETO = 84257639               # 통상 마법
MYSTICAL_SPACE_TYPHOON = 5318639   # 통상 마법 (대상 필요)
COMPULSORY_EVACUATION = 94192409   # 함정
GENEROUS_REWARD = 5915629          # 함정
PENALTY = 92595643                 # 함정
LOST = 24623598                    # 함정 (executable=0)
LUSTER_DRAGON = 11091375           # 통상 몬스터 (효과 없음)
FEATHERMAN = 71925487              # 채우기용 통상 몬스터

DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4
SPELL_DECK = [POT_OF_GREED] * 8 + [DIAN_KETO] * 8 + [LUSTER_DRAGON] * 4


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))


class _StripStrings(ast.NodeTransformer):
    def visit_Constant(self, node):  # noqa: N802
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<str>"), node)
        return node


def code_only(relative: str) -> str:
    """🔴 문자열 리터럴을 지운 코드 — 설명문의 낱말을 코드로 세지 않는다."""
    return ast.unparse(_StripStrings().visit(ast.parse(source_of(relative))))


def method_tree(func) -> ast.AST:
    source = textwrap.dedent(inspect.getsource(func))
    return ast.parse(source.replace(f"def {func.__name__}", "def f", 1))


def attribute_reads(name: str, *, receiver_hints=()) -> list[tuple[str, int, str]]:
    """``<무엇>.name`` 을 **코드로** 읽는 production 자리."""
    found: list[tuple[str, int, str]] = []
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            tree = ast.parse(code_only(relative))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == name:
                receiver = ast.unparse(node.value)
                if receiver_hints and not any(h in receiver for h in receiver_hints):
                    continue
                found.append((relative, node.lineno, receiver))
    return found


def call_sites(name: str, *, production_only: bool = True) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    paths = (
        production_files()
        if production_only
        else (p for p in sorted(PROJECT_ROOT.rglob("*.py")) if "__pycache__" not in str(p))
    )
    for path in paths:
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            tree = ast.parse(code_only(relative))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            ):
                found.append((relative, node.lineno))
    return found


def registered_rows(repository):
    """등재된 16개 정의의 선행 정보를 한 줄씩."""
    rows = []
    for entry in sorted(EFFECT_LIBRARY, key=lambda e: e.definition.effect_ref.card_id):
        definition = entry.definition
        card_id = definition.effect_ref.card_id
        card = repository.get(card_id)
        kind = (
            "monster"
            if card.is_monster
            else ("spell" if card.is_spell else ("trap" if card.is_trap else "?"))
        )
        codes = tuple(
            spec.code for spec in (card.effects or ()) if getattr(spec, "code", None)
        )
        rows.append(
            {
                "card_id": card_id,
                "ordinal": definition.effect_ref.ordinal,
                "kind": kind,
                "executable": entry.executable,
                "activation": definition.activation,
                "has_cost": bool(definition.cost.costs),
                "targets": len(definition.targets),
                "codes": codes,
            }
        )
    return rows


# ======================================================================
# 판
# ======================================================================


def hand_board(repository, passcode: int, *, owner: int = MINE):
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=owner, zone=Zone.HAND)
    state.turn.set_phase(Phase.MAIN1)
    return state, card.instance_id


def validator_for(state, seat: int = MINE) -> ActionValidator:
    return ActionValidator(GameStateView.from_state(state, viewer=seat))


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


# ======================================================================
# A. §2 — EffectDefinition 은 무엇을 알고 있는가
# ======================================================================


def test_01_the_three_layers_hold_different_fields():
    """
    🟢 §2 — **세 계층의 칸이 다르다.** "필드가 있다" 와 "엔진이 쓴다" 를 가른다.

    ``code`` 칸은 **``EffectSpec`` 에만** 있다 (Phase 3-E-31 의 측정을 재확인).
    """
    spec_fields = {f.name for f in dataclasses.fields(EffectSpec)}
    definition_fields = {f.name for f in dataclasses.fields(EffectDefinition)}
    trigger_fields = {f.name for f in dataclasses.fields(TriggerSpec)}

    assert "code" in spec_fields
    assert "code" not in definition_fields
    assert "code" not in trigger_fields

    #: 각 계층이 실제로 가진 칸.
    assert spec_fields == {
        "index",
        "effect_types",
        "code",
        "ranges",
        "target_ranges",
        "categories",
        "properties",
        "count_limit",
        "cloned_from",
    }, spec_fields
    assert definition_fields == {
        "effect_ref",
        "source_card_id",
        "operations",
        "activation",
        "cost",
        "targets",
        "declarations",
        "requirements",
        "guards",
        "provenance",
    }, definition_fields
    #: 🔴 ``EffectDefinition`` 에 **사건 칸이 없다** — 유발 조건을 적을 자리가 없다.
    for absent in ("code", "event", "trigger", "timing", "card_type", "spell_speed"):
        assert absent not in definition_fields, absent


def test_02_the_activation_field_is_a_condition_not_a_timing():
    """
    🔴 §6 — ``EffectDefinition.activation`` 은 **상태 조건**이다. timing 이 아니다.

    이름이 "activation" 이라서 타이밍으로 읽기 쉽다. 타입은 ``Condition | None``
    이고, 타이밍은 **다른 모듈**(``engine/activation_timing.py``)에 있다.
    """
    field = {f.name: f for f in dataclasses.fields(EffectDefinition)}["activation"]
    assert "Condition" in str(field.type)
    assert field.default is None

    #: 그리고 그 모듈은 ``EffectSpec.code`` 를 **전혀 읽지 않는다.**
    timing_code = code_only("engine/activation_timing.py")
    for absent in ("EffectSpec", "iter_effects", "EVENT_"):
        assert absent not in timing_code, absent


def test_03_each_precondition_item_is_classified(repository):
    """
    §2 — 요구한 항목을 **A~F 로 분류**한다. 측정값만 쓴다.

    =============================  ==========================================
    항목                            판정
    =============================  ==========================================
    효과의 종류                      A/C — ``EffectSpec.effect_types`` (파서·분석)
    발동 조건                        **D** — ``EffectDefinition.activation``
    유발 조건                        **E** (``EffectDefinition`` 에 칸 없음) /
                                    DORMANT 등록 계층에는 ``TriggerSpec``
    activation timing               **D** — 단 **카드 종류**에서 파생된다
    카드가 Spell/Trap/Monster        **D** — ``CardDefinition.type_names``
    effect_ref / ordinal            **D**
    SetCode(EVENT_*)                **B** — 파서가 뽑지만 engine 이 안 쓴다
    발동 비용                        **D** — ``EffectDefinition.cost`` (전부 빈 값)
    =============================  ==========================================
    """
    rows = registered_rows(repository)
    assert len(rows) == 16

    #: 발동 조건 — 실제로 들어 있다 (D).
    assert sum(1 for r in rows if r["activation"] is not None) == 8, [
        r["card_id"] for r in rows if r["activation"] is not None
    ]
    #: 비용 — 칸은 있고 값은 **전부 비어 있다** (STRUCTURAL-120).
    assert all(not r["has_cost"] for r in rows)
    #: effect_ref/ordinal — 있다. 전부 0 이다.
    assert {r["ordinal"] for r in rows} == {0}
    #: 카드 종류 — 등재된 것은 마법 11 · 함정 5 · 몬스터 0.
    assert collections.Counter(r["kind"] for r in rows) == {"spell": 11, "trap": 5}


# ======================================================================
# B. §3 — SetCode(EVENT_*) 조사
# ======================================================================


def test_04_the_code_field_mixes_two_vocabularies(repository):
    """
    🔴 §3 — **``EffectSpec.code`` 한 칸에 두 어휘가 섞여 있다.**

    ``EVENT_*`` 와 ``EFFECT_*`` 다. 즉 이 칸은 "유발 사건" 이 아니라 "블록의 첫
    ``SetCode`` 류 상수" 다. **이름만 보고 유발 조건이라고 단정할 수 없다** —
    §3 이 경고한 그대로이고, 데이터가 그것을 보여 준다.
    """
    prefixes: collections.Counter = collections.Counter()
    constants: set[str] = set()
    blocks = 0
    for card in repository:
        for spec in card.effects or ():
            code = getattr(spec, "code", None)
            if code:
                blocks += 1
                constants.add(code)
                prefixes[code.split("_")[0]] += 1

    assert blocks > 30000, blocks
    #: 🔴 두 어휘가 **둘 다 많다** — 한쪽을 무시할 수 없다.
    assert set(prefixes) == {"EVENT", "EFFECT"}, dict(prefixes)
    assert prefixes["EVENT"] > 10000 and prefixes["EFFECT"] > 10000, dict(prefixes)
    #: 상수가 수백 종이다 — "효과마다 구분" 이 실제 문제라는 뜻이다.
    assert len(constants) > 200, len(constants)


def test_05_no_engine_file_reads_the_code_field():
    """
    🔴 §3 · §8 A — **engine production 이 ``EffectSpec.code`` 를 읽지 않는다.**

    읽는 곳은 파서(`sources/lua_loader.py`)와 분석(`analysis/effect_analyzer.py`)
    **둘뿐**이다. 그래서 그 값은 **B 분류**(파서가 뽑지만 execution 이 안 쓴다)다.
    """
    #: .. note::
    #:    🔴 처음에 받는 쪽을 ``("spec", "block", "entry")`` 라는 **부분 문자열**로
    #:    골랐더니 ``engine/activation.py`` 의 ``blocked.code`` 가 걸렸다 —
    #:    ``"block"`` 이 ``"blocked"`` 의 부분 문자열이기 때문이다. 그런데 그
    #:    ``blocked`` 는 ``EffectActivator._check`` 가 돌려준 **``ActivationResult``**
    #:    이고 그 ``.code`` 는 ``ValidationCode`` 다 — ``EffectSpec.code`` 와 **전혀
    #:    다른 것**이다. 그래서 받는 쪽 이름을 **정확히** 센다.
    reads = attribute_reads("code")
    by_receiver: dict[str, set[str]] = {}
    for relative, _, receiver in reads:
        by_receiver.setdefault(receiver, set()).add(relative)

    #: ``spec.code`` — 이것만이 ``EffectSpec.code`` 다.
    assert by_receiver.get("spec") == {
        "sources/lua_loader.py",
        "analysis/effect_analyzer.py",
    }, by_receiver.get("spec")

    #: 🔴 engine 계층에서 ``spec.code`` 를 읽는 자리는 **없다.**
    assert not [f for f in by_receiver.get("spec", set()) if f.startswith("engine/")]

    #: 그리고 engine 쪽의 ``.code`` 읽기는 **다른 타입**이다 — 증거로 반환 주석을
    #: 본다.
    assert by_receiver.get("blocked") == {"engine/activation.py"}, by_receiver.get(
        "blocked"
    )
    from engine.activation import EffectActivator

    assert "ActivationResult" in str(
        inspect.signature(EffectActivator._check).return_annotation
    )

    #: 그리고 engine 전체에 ``EVENT_`` 리터럴을 **코드로** 쓰는 자리도 없다.
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        if not relative.startswith("engine/"):
            continue
        body = code_only(relative)
        assert "EVENT_FREE_CHAIN" not in body, relative


def test_06_iter_effects_is_reachable_but_never_called_in_production():
    """
    🔴 §3 — **"닿을 수 있다" 와 "닿고 있다" 는 다른 말이다.**

    Phase 3-E-31 이 ``engine.ids.iter_effects`` 로 그 값에 닿을 수 있다고 적었다.
    맞다 — 그런데 **production 호출자가 0 이다.** 부르는 것은 감사 테스트뿐이다.
    """
    assert "def iter_effects" in source_of("engine/ids.py")

    production = call_sites("iter_effects")
    assert production == [], production

    everywhere = call_sites("iter_effects", production_only=False)
    assert everywhere, "감사 테스트조차 부르지 않으면 측정이 성립하지 않는다"
    assert all(relative.startswith("tests/") for relative, _ in everywhere), everywhere


def test_07_the_trigger_vocabulary_is_not_the_lua_vocabulary():
    """§3 — ``TimingPoint`` 8종 ≠ Lua 상수 수백종. 1:1 사상이 없다 (3-E-31 재확인)."""
    points = [p.name for p in TimingPoint]
    assert len(points) == 8, points
    assert "UNIMPLEMENTED" in points
    #: 🔴 Lua 이름이 하나도 없다.
    for name in points:
        assert not name.startswith("EVENT_"), name


def test_08_traps_in_the_corpus_use_186_distinct_codes(repository):
    """
    🔴 §3 · §5 — **corpus 전체에서는 함정의 유발 조건이 실제로 갈린다.**

    그래서 ``TRAP_TRIGGER_MISSING`` 의 "효과마다 구분할 수 없다" 는 **corpus
    차원에서 성립하는 문장**이다 — 빈말이 아니다.
    """
    trap_codes: collections.Counter = collections.Counter()
    trap_cards = 0
    for card in repository:
        if not card.is_trap:
            continue
        trap_cards += 1
        for spec in card.effects or ():
            code = getattr(spec, "code", None)
            if code:
                trap_codes[code] += 1

    assert trap_cards > 2000, trap_cards
    #: 🔴 상수가 100종을 넘는다.
    assert len(trap_codes) > 100, len(trap_codes)
    #: 가장 많은 것이 ``EVENT_FREE_CHAIN`` 이지만 **과반이 아니다.**
    top, count = trap_codes.most_common(1)[0]
    assert top == "EVENT_FREE_CHAIN", top
    assert count < sum(trap_codes.values()) * 0.6, (count, sum(trap_codes.values()))


def test_09_but_every_registered_trap_is_free_chain(repository):
    """
    🔴 §5 — **등재된 함정 다섯 장은 전부 ``EVENT_FREE_CHAIN`` 이다.**

    그래서 ``TRAP_TRIGGER_MISSING`` 이라는 이유는 **corpus 에는 물리지만 등재된
    다섯 장에는 물리지 않는다** — 이 다섯 장에는 구분할 유발 조건이 애초에 없다.
    이 비대칭이 이 Phase 의 핵심 측정이다 (3-E-31 의 5번을 다시 확인).
    """
    rows = [r for r in registered_rows(repository) if r["kind"] == "trap"]
    assert len(rows) == 5, rows
    for row in rows:
        assert row["codes"] == ("EVENT_FREE_CHAIN",), row
    #: 등재 전체로 넓혀도 마찬가지다.
    everything = registered_rows(repository)
    assert {r["codes"] for r in everything} == {("EVENT_FREE_CHAIN",)}


# ======================================================================
# C. §6 — 세 개념의 분리
# ======================================================================


def test_10_the_trigger_condition_lives_in_the_dormant_registry():
    """§6 — 유발 조건은 ``TriggerSpec`` 쪽에 있다. ``EffectDefinition`` 이 아니다."""
    trigger_fields = {f.name for f in dataclasses.fields(TriggerSpec)}
    #: 사건과 조건을 적을 칸이 있다.
    assert {"point", "condition", "requirement", "activates_from"} <= trigger_fields
    #: 그런데 ``EffectDefinition`` 에는 그 넷이 하나도 없다.
    definition_fields = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert not ({"point", "condition", "requirement", "activates_from"} & definition_fields)


def test_11_the_can_activate_condition_lives_in_the_definition(repository):
    """§6 — 발동 가능 조건은 ``EffectDefinition.activation`` 이다 (8/16 에 있다)."""
    rows = registered_rows(repository)
    with_condition = [r for r in rows if r["activation"] is not None]
    assert len(with_condition) == 8, [r["card_id"] for r in with_condition]

    #: 그 조건은 **판을 읽는다** — 사건이 아니라 상태다.
    sample = next(
        entry.definition
        for entry in EFFECT_LIBRARY
        if entry.definition.effect_ref.card_id == POT_OF_GREED
    )
    assert sample.activation is not None
    assert hasattr(sample.activation, "evaluate")


def test_12_the_timing_lives_in_its_own_module_and_comes_from_card_type():
    """
    🔴 §6 — activation timing 은 **세 번째 계층**이고, **카드 종류**에서 나온다.

    ``SpellSpeed`` 가 Lua 사건이 아니라 카드 종류에서 파생된다는 것이 핵심이다 —
    그래서 세 개념이 하나로 뭉쳐 있지 않다.
    """
    assert [s.name for s in SpellSpeed]
    checker_doc = inspect.getdoc(ActivationTimingChecker) or ""
    assert checker_doc

    timing_fields = {f.name for f in dataclasses.fields(ActivationTiming)}
    #: 체인 · 우선권 · 세트한 턴 — 전부 **판 바깥의 흐름 정보**다.
    assert "set_this_turn" in timing_fields, timing_fields

    #: 그리고 종류 분류가 없는 몬스터는 **속도조차 정할 수 없다**고 적혀 있다.
    assert "MONSTER_CLASSIFICATION_MISSING" in code_only("engine/activation_timing.py")


# ======================================================================
# D. §5 — 실제 카드 corpus
# ======================================================================


def test_13_sixteen_registered_definitions_are_tabulated(repository):
    """§5 — 표본 **16개** 전수. 데이터가 불완전한 칸을 억지로 채우지 않는다."""
    rows = registered_rows(repository)
    assert len(rows) == 16

    #: 모든 줄이 같은 모양으로 채워진다.
    for row in rows:
        assert row["kind"] in {"spell", "trap"}
        assert isinstance(row["executable"], bool)
        assert row["codes"] == ("EVENT_FREE_CHAIN",)
        assert row["ordinal"] == 0
        assert row["has_cost"] is False

    #: executable 은 13개다 (나머지 셋은 ADR-006 으로 후보가 되지 않는다).
    assert sum(1 for r in rows if r["executable"]) == 13


def test_14_three_real_traps_are_withheld_with_the_trap_reason(repository):
    """§11 8 — 실제 함정 **세 장**이 같은 이유로 보류된다."""
    for passcode in (COMPULSORY_EVACUATION, GENEROUS_REWARD, PENALTY):
        card = repository.get(passcode)
        assert card is not None and card.is_trap, passcode
        refs = activatable_effects(passcode)
        assert refs, passcode
        state, source = hand_board(repository, passcode)
        verdict = validator_for(state).validate(
            PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
        )
        assert verdict.validity is ActionValidity.UNKNOWN, passcode
        assert verdict.missing_rule == TRAP_TRIGGER_MISSING, (passcode, verdict)


def test_15_two_real_spells_pass_every_precondition(repository):
    """§11 9 — 실제 마법 **두 장**은 선행 정보가 충분해서 체인까지 간다."""
    activator = duel_activator()
    for passcode in (POT_OF_GREED, DIAN_KETO):
        card = repository.get(passcode)
        assert card is not None and card.is_spell
        refs = activatable_effects(passcode)
        state, source = hand_board(repository, passcode)
        action = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
        assert validator_for(state).validate(action).validity is ActionValidity.VALID
        outcome = activator.activate(state, Chain(), action)
        assert outcome.status is ActivationStatus.ACTIVATED, passcode
        assert len(outcome.chain.links) == 1


def test_16_monster_effects_are_blocked_for_a_different_reason(repository):
    """
    §11 10 — 몬스터 쪽은 **함정과 다른 이유**로 막힌다.

    등재된 몬스터 효과가 **0장**이라 발동 경로로는 표본이 없다. 그래서 이유
    문자열이 **따로 있다**는 사실과, 통상 몬스터가 후보를 내지 않는다는 사실을
    잰다 — 없는 것을 있다고 적지 않는다.
    """
    assert MONSTER_ACTIVATION_MISSING != TRAP_TRIGGER_MISSING
    assert "기동" in MONSTER_ACTIVATION_MISSING or "분류" in MONSTER_ACTIVATION_MISSING

    #: 등재된 몬스터 효과가 없다.
    rows = registered_rows(repository)
    assert not [r for r in rows if r["kind"] == "monster"]
    #: 통상 몬스터는 후보를 내지 않는다.
    assert activatable_effects(LUSTER_DRAGON) == ()
    card = repository.get(LUSTER_DRAGON)
    assert card is not None and card.is_monster


# ======================================================================
# E. §4 · §8 — 실제 production call path
# ======================================================================


def test_17_the_timing_checker_is_gate_two_of_the_activation_gate():
    """
    🟢 §8 B · C — **activation-timing 은 ``legal_actions`` 와 ``apply`` 가 둘 다
    같은 자리에서 쓴다.**

    ``Duel._activation_gate`` 가 세 관문을 한 함수에 모아 두고, 후보 생성과 실행이
    **같은 함수**를 부른다 (STRUCTURAL-134 의 수정).
    """
    gate = code_only("engine/duel.py")
    assert "ActivationTimingChecker" in gate
    assert "_activation_gate" in gate

    #: .. note::
    #:    🔴 원래 ``"ActivationTimingChecker" in body`` 로만 쟀다. 그래서 고의 위반
    #:    주입 8번(``timed = None if True else ActivationTimingChecker(...)`` 로
    #:    관문을 꺼 버리기)을 **놓쳤다** — 이름이 꺼진 가지 안에 그대로 남기
    #:    때문이다. 3-F-21 · 3-F-22 에서 같은 함정을 겪었다. **이름이 아니라
    #:    구문을 센다**: ``timed`` 에 대입되는 것이 **그 호출 자체**여야 한다.
    tree = method_tree(Duel._activation_gate)

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "timed" for t in node.targets
        )
    ]
    assert len(assignments) == 1, [ast.unparse(a) for a in assignments]
    value = assignments[0].value
    #: 🔴 조건식이나 상수가 아니라 **호출**이다.
    assert isinstance(value, ast.Call), ast.unparse(value)
    assert "ActivationTimingChecker" in ast.unparse(value.func), ast.unparse(value)

    #: 나머지 두 관문도 구문으로 센다.
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "validator.validate" in calls, sorted(calls)
    assert any("can_activate" in name for name in calls), sorted(calls)

    #: 후보 생성과 실행 **양쪽**이 그 함수를 부른다.
    callers = [
        site
        for site in call_sites("_activation_gate")
        if site[0] == "engine/duel.py"
    ]
    assert len(callers) >= 2, callers


def test_18_the_definition_trigger_condition_is_not_used_for_candidates():
    """
    🔴 §8 D — **``EffectDefinition`` 의 유발 조건이 후보 생성에 쓰이지 않는다.**

    쓸 칸이 아예 없기 때문이다(``test_01``). 후보를 만드는 것은 등재 목록 ·
    대상 조합 · 세 관문이다.
    """
    duel_code = code_only("engine/duel.py")
    assert "activatable_effects" in duel_code
    assert "target_combinations" in duel_code
    #: 🔴 사건/유발 어휘가 후보 생성 경로에 없다.
    for absent in ("TriggerSpec", "TimingPoint", "EffectSpec", "iter_effects"):
        assert absent not in duel_code, absent


def test_19_the_card_type_changes_permission_not_the_action_kind(repository):
    """
    🔴 §8 E — **카드 종류는 "어느 종류의 행위인가" 를 바꾸지 않는다.**

    후보 생성기는 언제나 ``activate_effect`` 를 만든다. 카드 종류는 **허가
    여부**(그리고 보류 사유)만 바꾼다.
    """
    duel_code = code_only("engine/duel.py")
    assert "PlayerAction.activate_effect" in duel_code

    #: 마법과 함정에 **같은 종류**를 만들어 물어본다 — 판정만 갈린다.
    verdicts = {}
    for passcode in (POT_OF_GREED, COMPULSORY_EVACUATION):
        refs = activatable_effects(passcode)
        state, source = hand_board(repository, passcode)
        action = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
        assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
        verdicts[passcode] = validator_for(state).validate(action)

    assert verdicts[POT_OF_GREED].validity is ActionValidity.VALID
    assert verdicts[COMPULSORY_EVACUATION].validity is ActionValidity.UNKNOWN


def test_20_legal_actions_can_express_a_trap_only_as_withheld(repository):
    """
    §8 F · G — 함정의 발동 가능성을 **표현은 한다**(`withheld`). **허가는 못 한다.**
    그리고 끝까지 실행할 수 없다.
    """
    duel = opened_duel(repository, seed=601, deck=SPELL_DECK)
    seat = duel.to_act
    legal = duel.legal_actions(seat)

    #: 보류에는 이유가 남는다.
    assert legal.withheld
    #: 그런데 허가 목록에 함정 발동이 들어오는 일은 없다 — 등재된 함정이
    #: 손에 있어도 검증기가 UNKNOWN 을 준다(``test_14``).
    state, source = hand_board(repository, COMPULSORY_EVACUATION)
    refs = activatable_effects(COMPULSORY_EVACUATION)
    outcome = duel_activator().activate(
        state, Chain(), PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    )
    #: 🔴 발동 계층까지 가도 **인가되지 않는다.**
    assert outcome.status is not ActivationStatus.ACTIVATED
    assert len(outcome.chain.links) == 0


def test_21_the_chain_link_carries_no_precondition_information(repository):
    """§11 14 — ``ChainLink`` 는 선행 정보를 **싣지 않는다.** 발동 사실만 싣는다."""
    fields = {f.name for f in dataclasses.fields(ChainLink)}
    assert {"sequence", "actor", "effect_ref"} <= fields
    for absent in ("code", "event", "timing", "spell_speed", "card_type", "condition"):
        assert absent not in fields, absent

    refs = activatable_effects(POT_OF_GREED)
    state, source = hand_board(repository, POT_OF_GREED)
    outcome = duel_activator().activate(
        state, Chain(), PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    )
    link = outcome.chain.links[0]
    assert link.effect_ref == refs[0]
    assert not hasattr(link, "code")


# ======================================================================
# F. §9 — AI / Search 영향
# ======================================================================


def test_22_the_agent_layer_invents_no_activation(repository):
    """
    🟢 §9 — **AI 는 발동을 발명하지 않는다.** 선행 정보를 스스로 추론하지도 않는다.

    ``agent/`` 가 `EffectSpec` · `iter_effects` · `EVENT_*` · 타이밍 모듈을 **전혀
    읽지 않는다.** 그래서 숨은 정보로 발동 조건을 추론할 자리가 없다.
    """
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        body = code_only(relative)
        for absent in (
            "EffectSpec",
            "iter_effects",
            "EVENT_FREE_CHAIN",
            "ActivationTimingChecker",
            "TriggerSpec",
            "EffectDefinition",
        ):
            assert absent not in body, (absent, relative)

    #: 그리고 AI 가 만드는 ``PlayerAction`` 생성 자리가 없다 — 받은 후보만 쓴다.
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(code_only(relative))
        built = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and "PlayerAction" in ast.unparse(node.func.value)
            and node.func.attr.startswith("activate")
        ]
        assert built == [], (relative, built)


def test_23_hidden_information_and_the_board_are_untouched(repository):
    """§12 — ``state_hash`` · RNG · 숨은 정보 불변."""
    duel = opened_duel(repository, seed=602, deck=SPELL_DECK)
    before_hash, before_rng = duel.state.state_hash(), repr(duel.state.rng)
    seat = duel.to_act

    validator = ActionValidator(duel.view(seat))
    for card in duel.state.player(seat).hand:
        validator.validate(PlayerAction.activate_card(seat, card.instance_id))
    duel.legal_actions(seat)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng

    view = GameStateView.from_state(duel.state, viewer=seat)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(1 - seat).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_24_engine_v1_was_not_widened():
    """§10 금지 항목 — 구현·확장이 하나도 없다."""
    assert len(list(PlayerActionKind)) == 11
    #: 새 trigger engine · event bus · timing engine · Condition DSL 없음.
    for forbidden in (
        "EventBus",
        "TriggerEngine",
        "ActivationTimingEngine",
        "ConditionDSL",
        "TrapActivationRule",
    ):
        for path in production_files():
            relative = str(path.relative_to(PROJECT_ROOT))
            assert forbidden not in code_only(relative), (forbidden, relative)

    #: ``EffectDefinition`` 에 새 칸이 생기지 않았다.
    assert len(dataclasses.fields(EffectDefinition)) == 10
    #: ``TimingPoint`` 도 8개 그대로다.
    assert len(list(TimingPoint)) == 8


def test_25_this_phase_changed_no_production_file():
    """
    §10 — **AUDIT-ONLY: production 을 한 줄도 바꾸지 않았다.**

    §10 의 네 조건 가운데 **하나도 성립하지 않는다** — 특히
    ``TRAP_TRIGGER_MISSING`` 은 ``EffectDefinition`` 에 ``code`` 칸이 없다는
    **사실을 정확히** 적고 있고(``test_01``), corpus 차원에서 구분이 실제로
    필요하다(``test_08``). 등재된 다섯 장에 물리지 않는다는 것은 **그 문장이
    틀렸다는 뜻이 아니다.**

    .. note::
       **이 파일을 추가한 commit** 하나만 본다 (3-F-18 ~ 3-F-23 과 같은 방식).
       commit 전에는 base(``f49b186``) ↔ 작업 트리로 되돌아간다.
    """
    PHASE_3F24_BASE = "f49b186"

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    work = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    if work:
        changed = git(
            "show", "--stat", "--format=", work[-1], "--", *PRODUCTION_ROOTS
        )
    else:  # pragma: no cover - commit 전 개발 중에만 지나간다
        changed = git("diff", "--stat", PHASE_3F24_BASE, "--", *PRODUCTION_ROOTS)
    assert changed.strip() == "", changed


def test_26_the_search_ranking_digest_is_unchanged(repository):
    """
    §12 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은 파일이
       못 박은 값을 기준으로 쓴다 (3-F-18 ~ 3-F-23 과 같은 방식).
    """
    import hashlib

    pinned: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative == MYSELF:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(c in "0123456789abcdef" for c in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: dict[str, int] = {}
    for values in pinned.values():
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    expected, pins = max(counts.items(), key=lambda item: item[1])
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == expected
