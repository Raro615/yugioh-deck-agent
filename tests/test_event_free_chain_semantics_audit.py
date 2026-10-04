"""
Phase 3-E-32 — ``EVENT_FREE_CHAIN`` 의미 감사 (등재 함정 5장).

핵심 원칙: **이름을 보고 의미를 추측하지 않는다.** ``EVENT_`` 로 시작한다고
사건(trigger event)이라고 읽지 않고, ``TRAP`` 이라고 ``EVENT_FREE_CHAIN`` 을
추론하지 않는다. 원본 Lua → 파서 → analysis → ``EffectDefinition`` →
production reachability 를 끝까지 추적한 결과만 고정한다.

측정으로 드러난 다섯 가지

1. **``EVENT_FREE_CHAIN`` 은 사건이 아니다.** 전수 측정에서 ``TRIGGER_O`` ·
   ``TRIGGER_F`` 와 **한 번도** 함께 쓰이지 않고 (유발 블록 8,052개 중 0개),
   ``ACTIVATE`` · ``QUICK_O`` · ``IGNITION`` 과만 함께 쓰인다. 그리고
   ``ACTIVATE`` 블록의 **84.6%** 가 이 값이다 — 즉 **발동형 효과의 "유발
   조건 없음" 기본값**이다.

2. **``TRAP`` 만으로 복원할 수 없다.** ``TRAP`` 블록 중 ``EVENT_FREE_CHAIN``
   은 **38.6%** 뿐이고, ``EVENT_FREE_CHAIN`` 중 ``TRAP`` 은 **37.3%** 뿐이다
   (``SPELL`` 45.2% · ``MONSTER`` 17.4%). 양방향 추론이 모두 실패한다.

3. **``EVENT_FREE_CHAIN`` ≠ "발동 조건 없음".** 5장 중 **의적의 입문서
   (69091732)** 는 ``EVENT_FREE_CHAIN`` 이면서 Lua 에 ``SetCondition`` 이
   있다 (상대 패가 5장 이상). 둘을 ``condition=None`` 하나로 합치면 틀린다.

4. **두 사실이 서로 다른 칸에 따로 보존되어 있다.** 시점 분류는
   ``EffectSpec.code``, 발동 조건은 ``ActivationCondition.has_condition_function``
   / ``tree`` / ``requirements`` 다. 그리고 조건은 손 등록된
   ``EffectDefinition.activation`` 에 **이미 옮겨져 있다.**

5. **production 의 어떤 코드도 ``EVENT_FREE_CHAIN`` 을 읽지 않는다.** 7곳
   등장하는데 전부 주석/docstring 이다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from core.constants import TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.trigger import TriggerSpec
from sources.lua_loader import EffectSpec

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 등재된 ``EVENT_FREE_CHAIN`` **함정** 5장. 이름이 아니라 저장소 데이터로
#: 골랐다 (``test_01`` 이 그 선정 자체를 다시 검증한다).
FREE_CHAIN_TRAPS = (5915629, 92595643, 94192409, 24623598, 69091732)

#: 그중 **유일하게** Lua 에 ``SetCondition`` 이 있는 카드 (의적의 입문서).
WITH_CONDITION = 69091732


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def card_kind(type_mask: int) -> str:
    if type_mask & TYPE_MONSTER:
        return "MONSTER"
    if type_mask & TYPE_TRAP:
        return "TRAP"
    if type_mask & TYPE_SPELL:
        return "SPELL"
    return "OTHER"


def all_blocks(repository):
    """``(card, EffectSpec)`` 쌍 전부. 고유 스크립트를 한 번씩 훑는다."""
    for card in repository.all_cards():
        if card.script is None:
            continue
        for block in card.script.effects:
            yield card, block


# ======================================================================
# Test 1 — 5장이 정말 같은 의미인가
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_01_the_five_are_selected_from_repository_data_not_from_names(repository):
    """
    선정 자체를 검증한다 — **이름으로 고르지 않았다.**

    등재 효과 16개를 훑어 `code == 'EVENT_FREE_CHAIN'` 이고 카드 종류가
    `TRAP` 인 것만 남기면 정확히 이 5장이 나온다.
    """
    picked = []
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        assert card is not None and card.script is not None
        block = card.script.effects[ref.ordinal]
        is_trap = bool(card.type_mask & TYPE_TRAP)
        if block.code == "EVENT_FREE_CHAIN" and is_trap:
            picked.append(ref.card_id)

    assert sorted(picked) == sorted(FREE_CHAIN_TRAPS)


@requires_official_db
@pytest.mark.real_card
def test_02_the_five_agree_on_the_timing_code_but_not_on_the_condition(repository):
    """
    **Test 1 (§14): 5장이 같은 의미인가 → 한 축에서만 같다.**

    같은 것: ``code`` 와 ``effect_types`` — 다섯 다 `EVENT_FREE_CHAIN` ·
    `['ACTIVATE']`.

    다른 것: Lua 의 ``SetCondition`` 유무. **의적의 입문서만 있다.**
    그래서 "5장은 같은 의미" 라고 뭉개면 틀린다.
    """
    codes, kinds, has_condition = set(), set(), {}
    for card_id in FREE_CHAIN_TRAPS:
        card = repository.get(card_id)
        block = card.script.effects[0]
        codes.add(block.code)
        kinds.add(tuple(block.effect_types))
        lua = source_of(f"c{card_id}.lua")
        has_condition[card_id] = "SetCondition" in lua

    #: 시점 분류는 완전히 같다.
    assert codes == {"EVENT_FREE_CHAIN"}
    assert kinds == {("ACTIVATE",)}
    #: 발동 조건은 같지 않다 — 하나뿐이다.
    assert sum(has_condition.values()) == 1
    assert has_condition[WITH_CONDITION] is True
    assert all(
        not flag for cid, flag in has_condition.items() if cid != WITH_CONDITION
    )


# ======================================================================
# Test 2 — TRAP 으로 추론할 수 있다는 가설
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_03_the_trap_type_cannot_infer_the_free_chain_code(repository):
    """
    **Test 2 (§14): "TRAP 이면 EVENT_FREE_CHAIN" 가설을 전수로 반증한다.**

    양방향 모두 실패한다. 반례를 숫자와 함께 남긴다.
    """
    trap_blocks, free_blocks = [], []
    for card, block in all_blocks(repository):
        if card_kind(card.type_mask) == "TRAP":
            trap_blocks.append(block)
        if block.code == "EVENT_FREE_CHAIN":
            free_blocks.append((card, block))

    #: Q1 — 모든 TRAP 이 EVENT_FREE_CHAIN 인가 → 아니다 (측정 38.6%).
    free_in_trap = [b for b in trap_blocks if b.code == "EVENT_FREE_CHAIN"]
    assert len(trap_blocks) >= 4_745
    ratio = len(free_in_trap) / len(trap_blocks)
    assert 0.30 < ratio < 0.50, f"TRAP 중 EVENT_FREE_CHAIN 비율 {ratio:.3f}"

    #: Q2 — EVENT_FREE_CHAIN 이면 TRAP 인가 → 아니다.
    by_kind = {}
    for card, _ in free_blocks:
        key = card_kind(card.type_mask)
        by_kind[key] = by_kind.get(key, 0) + 1
    assert by_kind["SPELL"] > by_kind["TRAP"], by_kind
    #: Q3 — 몬스터에도 있다.
    assert by_kind.get("MONSTER", 0) >= 800, by_kind


@requires_official_db
@pytest.mark.real_card
def test_04_concrete_counterexamples_exist_in_both_directions(repository):
    """
    반례를 **실제 카드로** 남긴다 — 비율만으로는 다음 사람이 확인할 수 없다.
    """
    trap_not_free, free_not_trap = [], []
    for card, block in all_blocks(repository):
        kind = card_kind(card.type_mask)
        if kind == "TRAP" and block.code and block.code != "EVENT_FREE_CHAIN":
            trap_not_free.append((card.id, block.code))
        if block.code == "EVENT_FREE_CHAIN" and kind == "MONSTER":
            free_not_trap.append(card.id)

    assert trap_not_free, "TRAP 이면서 EVENT_FREE_CHAIN 이 아닌 블록이 있어야 한다"
    assert free_not_trap, "몬스터의 EVENT_FREE_CHAIN 블록이 있어야 한다"
    #: 반례의 code 가 실제 유발 사건들이다 — 종류로 가를 수 없다는 증거.
    found = {code for _, code in trap_not_free}
    assert {"EVENT_CHAINING", "EVENT_ATTACK_ANNOUNCE"} & found, sorted(found)[:10]


# ======================================================================
# Test 3 — EVENT_FREE_CHAIN 과 activation condition 을 동일시하면 안 된다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_05_free_chain_does_not_mean_there_is_no_activation_condition(repository):
    """
    **Test 3 (§14): 둘을 합치면 안 되는 사례.**

    의적의 입문서는 ``EVENT_FREE_CHAIN`` 인데 Lua 에 ``SetCondition`` 이 있고,
    analysis 계층이 그것을 **따로 보존한다** (`has_condition_function=True` ·
    `tree` · `requirements`). 두 사실이 서로 다른 칸에 있다.
    """
    analyzer = EffectAnalyzer(repository)

    flagged, plain = [], []
    for card_id in FREE_CHAIN_TRAPS:
        card = repository.get(card_id)
        analysed = analyzer.analyze(card)
        effect = analysed.effects[0]
        #: 시점 분류는 같다.
        assert effect.trigger_event == "EVENT_FREE_CHAIN"
        (flagged if effect.activation.has_condition_function else plain).append(
            (card_id, effect.activation)
        )

    assert [cid for cid, _ in flagged] == [WITH_CONDITION]
    assert len(plain) == 4

    #: 조건이 있는 쪽은 실제로 **읽혔다** — 못 읽은 것이 아니다.
    _, condition = flagged[0]
    assert condition.tree is not None
    assert condition.requirements, "요구가 비어 있으면 보존되었다고 할 수 없다"
    assert condition.unparsed == [], f"읽지 못한 부분이 있다: {condition.unparsed}"
    assert condition.raw == "s.condition"

    #: 조건이 없는 넷은 빈 값이고, 그것이 "못 읽었다" 와 구분된다.
    for _, other in plain:
        assert other.tree is None
        assert other.requirements == []
        assert other.unparsed == []


@requires_official_db
@pytest.mark.real_card
def test_06_the_condition_is_already_carried_into_the_definition(repository):
    """
    §6 — 발동 조건은 **이미 ``EffectDefinition.activation`` 에 있다.**

    그리고 그 값이 Lua 가 적은 숫자와 맞는다 — 의적의 입문서의
    ``GetFieldGroupCount(tp,0,LOCATION_HAND)>4`` 는 "상대 패 5장 이상" 이고
    등재 정의는 `count=5` 다. 즉 옮겨지지 **않은** 것은 시점 분류뿐이다.
    """
    library = {e.definition.effect_ref.card_id: e.definition for e in EFFECT_LIBRARY}

    definition = library[WITH_CONDITION]
    assert definition.activation is not None
    assert getattr(definition.activation, "count", None) == 5
    #: Lua 원문이 그 숫자를 적는다 (`>4` = 5장 이상).
    assert "LOCATION_HAND)>4" in source_of(f"c{WITH_CONDITION}.lua")

    #: 다섯 중 조건이 등재된 것과 안 된 것이 갈린다 — 뭉개지지 않았다.
    with_activation = {
        cid for cid in FREE_CHAIN_TRAPS if library[cid].activation is not None
    }
    assert WITH_CONDITION in with_activation
    #: 조건 칸이 비어 있는 것도 있다 (대상 가용성은 `targets` 가 본다).
    assert with_activation != set(FREE_CHAIN_TRAPS)


# ======================================================================
# Test 4 — EffectDefinition 으로 표현 가능한가
# ======================================================================


def test_07_no_field_in_the_definition_can_hold_the_timing_code():
    """
    **Test 4 (§14): 현재 ``EffectDefinition`` 칸만으로 표현 가능한가.**

    ``EVENT_FREE_CHAIN`` 은 "이 효과의 시점 분류" 인데 정의의 10개 칸에 그것을
    담을 자리가 없다. ``activation`` 은 **조건**이고 분류가 아니다 —
    ``test_05`` 가 둘이 독립임을 보였다.
    """
    fields = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert len(fields) == 10
    assert fields & {"code", "trigger_event", "timing", "point", "event"} == set()

    #: ``TriggerSpec`` 에도 없다 — 3-E-31 이 측정한 그대로다.
    assert "code" not in {f.name for f in dataclasses.fields(TriggerSpec)}
    #: 가진 것은 파서뿐이다.
    assert "code" in {f.name for f in dataclasses.fields(EffectSpec)}


@requires_official_db
@pytest.mark.real_card
def test_08_the_code_carries_no_discriminating_information_here(repository):
    """
    **등재된 16개 효과가 전부 ``EVENT_FREE_CHAIN`` 이다.**

    그래서 그 값을 정의로 옮겨도 등재 코퍼스 안에서는 **아무것도 구분하지
    못한다.** "옮기면 함정을 풀 수 있다" 는 기대가 성립하지 않는 까닭이다 —
    함정을 가르는 것은 이 값이 아니라 ``effect_types`` 다 (``test_09``).
    """
    codes = set()
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        codes.add(card.script.effects[ref.ordinal].code)

    assert codes == {"EVENT_FREE_CHAIN"}, codes
    assert len(EFFECT_LIBRARY) == 16


# ======================================================================
# Test 5 — TriggerSpec 이 필요한가 / 이것은 Trigger 인가
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_09_free_chain_and_real_triggers_are_disjoint_vocabularies(repository):
    """
    **Test 5 (§14) 의 근거: ``EVENT_FREE_CHAIN`` 은 Trigger 가 아니다.**

    ``TRIGGER_O``/``TRIGGER_F`` 블록과 ``EVENT_FREE_CHAIN`` 은 **교집합이
    0** 이다. 그리고 ``EVENT_FREE_CHAIN`` 은 ``ACTIVATE`` 블록의 대부분을
    차지한다 — 발동형의 기본값이라는 뜻이다.

    구문으로는 가를 수 없다: 공식 ``constant.lua`` 에서
    ``EVENT_FREE_CHAIN = 1002`` 이고 진짜 사건들(``EVENT_DESTROY = 1010`` 등)과
    같은 번호대다. 가르는 것은 함께 쓰인 ``effect_types`` 다.
    """
    free_types, trigger_codes, activate_codes = [], [], []
    for _, block in all_blocks(repository):
        types = set(block.effect_types)
        if block.code == "EVENT_FREE_CHAIN":
            free_types.extend(types)
        if {"TRIGGER_O", "TRIGGER_F"} & types:
            trigger_codes.append(block.code)
        if "ACTIVATE" in types:
            activate_codes.append(block.code)

    #: 유발 종류와 **한 번도** 함께 쓰이지 않는다.
    assert "TRIGGER_O" not in free_types
    assert "TRIGGER_F" not in free_types
    #: 반대 방향도 0 이다.
    assert trigger_codes.count("EVENT_FREE_CHAIN") == 0
    assert len(trigger_codes) >= 8_052
    #: 발동형의 기본값이다.
    share = activate_codes.count("EVENT_FREE_CHAIN") / len(activate_codes)
    assert share > 0.80, f"ACTIVATE 중 비율 {share:.3f}"

    #: 공식 상수 번호대가 같아 구문으로 가를 수 없다.
    constants = source_of("data/constants/constant.lua")
    assert "EVENT_FREE_CHAIN           = 1002" in constants
    assert "EVENT_DESTROY              = 1010" in constants


def test_10_nothing_in_production_reads_the_free_chain_value():
    """
    §11 — ``EVENT_FREE_CHAIN`` 은 production 에서 **읽히지 않는다.**

    등장하는 자리가 전부 주석/docstring 이다. 그래서 `PlayerAction` 생성 ·
    activation timing gate · Trigger pipeline 어디에도 영향을 주지 않는다.
    """
    folders = ("engine", "core", "analysis", "sources", "agent")
    literals = []
    for folder in folders:
        root = PROJECT_ROOT / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))

            #: **홀로 선 문자열 문장은 전부 문서다.** 모듈 · 클래스 ·
            #: 함수의 첫 줄뿐 아니라 dataclass 칸 아래 붙는 설명도 그렇다
            #: (``core/card_model.py`` 가 그 모양을 쓴다). 그래서 위치가
            #: 아니라 **문장인지**로 가린다.
            documented = {
                id(stmt.value)
                for node in ast.walk(tree)
                #: ``IfExp.body`` 처럼 **문장 목록이 아닌** body 도 있다.
                for stmt in (
                    node.body if isinstance(getattr(node, "body", None), list) else []
                )
                if isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "EVENT_FREE_CHAIN" in node.value
                    and id(node) not in documented
                ):
                    literals.append((str(path.relative_to(PROJECT_ROOT)), node.lineno))

    #: docstring 이 아닌 문자열 리터럴로 쓰이는 자리가 **없다.**
    assert literals == [], f"production 이 값을 읽는다: {literals}"


def test_11_the_definition_does_not_need_a_trigger_spec_for_these_five():
    """
    §7 — 이 5장에 ``TriggerSpec`` 이 필요하지 않다.

    ``TriggerSpec`` 은 `point`(사건 시점) 를 **필수**로 받는다. 그런데
    ``EVENT_FREE_CHAIN`` 은 사건이 아니므로 (``test_09``) 넣을 시점이 없다.
    억지로 넣으면 "사건이 없는 것" 을 "어떤 사건" 으로 적게 된다.
    """
    required = [
        f.name
        for f in dataclasses.fields(TriggerSpec)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING  # type: ignore[misc]
    ]
    #: 신원과 **시점**이 필수다.
    assert "point" in required
    assert "effect_ref" in required

    #: 그리고 production 에 `TriggerSpec` 이 하나도 없다 (3-E-31 재확인).
    made = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path) or str(path.relative_to(PROJECT_ROOT)).startswith(
            "tests/"
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        if any(
            isinstance(n, ast.Call) and ast.unparse(n.func).endswith("TriggerSpec")
            for n in ast.walk(tree)
        ):
            made.append(str(path.relative_to(PROJECT_ROOT)))
    assert made == [], made


def test_12_this_audit_added_no_production_structure():
    """
    §13 — 감사가 production 구조를 늘리지 않았다.

    정의 10칸 · 선언 9칸 그대로이고, ``EVENT_FREE_CHAIN`` 을 복제한 새 enum 도
    없다.
    """
    assert len(dataclasses.fields(EffectDefinition)) == 10
    assert len(dataclasses.fields(TriggerSpec)) == 9

    #: 새 enum 이 생기지 않았다.
    #:
    #: ``dir(module)`` 만 보면 **enum 멤버를 놓친다** — ``TimingPoint.FREE_CHAIN``
    #: 을 추가해도 모듈 속성 목록에는 나타나지 않는다. 그래서 모듈의 Enum
    #: 클래스를 찾아 **멤버 이름까지** 본다 (고의 위반 F 가 이 구멍을 찾았다).
    import enum as enum_mod
    import engine.activation_timing as timing_mod
    import engine.trigger as trigger_mod

    offenders: list[str] = []
    for module in (trigger_mod, timing_mod):
        for name in dir(module):
            if "FREE_CHAIN" in name.upper():
                offenders.append(f"{module.__name__}.{name}")
            attribute = getattr(module, name, None)
            if isinstance(attribute, type) and issubclass(attribute, enum_mod.Enum):
                offenders.extend(
                    f"{module.__name__}.{name}.{member}"
                    for member in attribute.__members__
                    if "FREE_CHAIN" in member.upper()
                )
    assert offenders == [], offenders

    #: 측정값 — ``TimingPoint`` 는 8개 그대로다 (3-E-30 · 3-E-31 과 같은 값).
    from engine.trigger import TimingPoint

    assert len(list(TimingPoint)) == 8
