"""
Phase 3-E-31 — ``EffectDefinition`` / Trigger 등록 **경계 감사**.

가장 중요한 불변식: **``EVENT_*`` 가 ``EffectDefinition`` 에 없다는 사실 자체를
버그로 취급하지 않는다.** 이 파일이 가리는 것은 "사건 의미가 등록 계층
(``TriggerSpec``) 의 것인가, 아니면 실제로 잃어버린 것인가" 다.

측정으로 드러난 답 — **등록 계층의 것이고, 잃어버리지 않았다.**

1. ``SetCode()`` 인자는 **파서 계층의 ``EffectSpec.code`` 가 들고 있다**
   (``EVENT_*`` 16,381 블록 · 상수 70종). ``EffectDefinition`` 에도
   ``TriggerSpec`` 에도 ``code`` 칸은 **없다** — 셋 중 ``EffectSpec`` 만 갖는다.

2. ``engine`` 안에 그 값에 닿는 **production 함수가 이미 있다** —
   ``engine.ids.iter_effects(card)`` 가 ``(EffectRef, EffectSpec)`` 을 돌려주고
   ``EffectSpec.code`` 가 ``'EVENT_FREE_CHAIN'`` 을 그대로 싣는다. 즉 값은
   **닿을 수 있는 곳에 있고**, 엔진이 **쓰지 않기로** 한 것이다 (ADR-006 ·
   STRUCTURAL-7: 손으로 등록한다).

3. ``TriggerSpec.point`` 는 ``EVENT_*`` 의 사본이 **아니다.**
   ``TimingPoint`` 는 8개뿐이고 ``StateDelta``/``JournalEvent`` 에서 나온다 —
   Lua 의 70종과 **다른 어휘**다. 그래서 둘 사이에 1:1 사상이 없다.

4. 강제/임의도 파서 계층에 보존되어 있다 (``TRIGGER_O`` 6,083 ·
   ``TRIGGER_F`` 1,969 블록). ``EffectDefinition`` 에는 칸이 없고
   ``TriggerSpec.requirement`` 가 등록 시점에 받는다.

5. 등재된 함정 5장은 **전부 ``EVENT_FREE_CHAIN``** (= 유발 조건 없음) 이다.
   엔진이 종류 단위로 막는 것은 데이터가 없어서가 아니라 **옮기지 않아서**다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator, TRAP_TRIGGER_MISSING
from engine.effect.definition import EffectDefinition, EffectDefinitionRegistry
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardView, GameStateView
from engine.ids import EffectRef, iter_effects
from engine.state.game_state import GameState
from engine.trigger import (
    TimingPoint,
    TriggerError,
    TriggerRegistry,
    TriggerRequirement,
    TriggerSpec,
    TriggerWording,
)
from engine.vocabulary import Phase, Position, Zone
from sources.lua_loader import EffectSpec

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

MINE, THEIRS = 0, 1

#: 등재된 함정 5장 (Phase 3-E-30 이 공식 DB ``type_mask`` 로 측정했다).
#: **이 카드들의 규칙을 추측하지 않는다** — ``code`` 를 코퍼스에서 읽는다.
REGISTERED_TRAPS = (5915629, 92595643, 94192409, 24623598, 69091732)

POT_OF_GREED = 55144522
"""통상 마법. 대상도 비용도 없다."""


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for folder in ("engine", "core", "analysis", "sources", "agent"):
        for path in sorted((PROJECT_ROOT / folder).rglob("*.py")):
            if "__pycache__" not in str(path):
                yield path


def call_sites(symbol: str):
    """``symbol(...)`` 호출 자리를 (production, test) 로 나눠 센다."""
    production: list[str] = []
    tests: list[str] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 저장소에 없다
            continue
        hits = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func).split(".")[-1] == symbol
        )
        if not hits:
            continue
        rel = str(path.relative_to(PROJECT_ROOT))
        (tests if rel.startswith("tests/") else production).append(rel)
    return production, tests


# ======================================================================
# A. 어느 계층이 무엇을 소유하는가
# ======================================================================


def test_01_only_the_parser_layer_owns_the_setcode_argument():
    """
    **``code`` 를 가진 것은 셋 중 하나뿐이다.**

    ``EffectDefinition`` 에 없다는 것이 "아키텍처에 없다" 는 뜻이 아니다 —
    파서 계층(``EffectSpec``)이 들고 있다.
    """
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    spec = {f.name for f in dataclasses.fields(TriggerSpec)}
    parsed = {f.name for f in dataclasses.fields(EffectSpec)}

    assert "code" in parsed
    assert "code" not in definition
    assert "code" not in spec
    #: 파서는 효과 종류(강제/임의의 근거)도 함께 들고 있다.
    assert "effect_types" in parsed


def test_02_the_definition_and_the_trigger_spec_share_only_identity():
    """
    §5 — 두 구조가 **겹치는 것은 신원뿐**이다. 나머지는 각자의 것이다.

    그래서 ``TriggerSpec`` 은 ``EffectDefinition`` 을 고치지 않고도 사건 ·
    시점 · 강제/임의 · 발동 자리를 적을 수 있다.
    """
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    spec = {f.name for f in dataclasses.fields(TriggerSpec)}

    assert definition & spec == {"effect_ref", "operations"}
    #: 사건 · 시점 · 강제/임의 · 문구 · 자리는 **등록 계층의 것**이다.
    assert {
        "point",
        "condition",
        "requirement",
        "wording",
        "activates_from",
        "from_zones",
        "to_zones",
    } <= spec - definition
    #: 조작 · 비용 · 대상 · 선언 · 출처는 **정의의 것**이다.
    assert {
        "cost",
        "targets",
        "declarations",
        "guards",
        "requirements",
        "provenance",
    } <= definition - spec


def test_03_the_timing_point_vocabulary_is_not_a_copy_of_lua_events():
    """
    ``TriggerSpec.point`` 를 "``EVENT_*`` 를 옮긴 칸" 으로 읽으면 틀린다.

    ``TimingPoint`` 는 **8개**뿐이고 ``TimingEvent.from_delta`` /
    ``from_journal_event`` 가 만든다 — 즉 **엔진이 관측한 변화**에서 나온다.
    Lua 의 ``EVENT_*`` 는 70종이다. 둘은 다른 어휘이므로 1:1 사상이 없고,
    "옮기지 않았다" 가 아니라 **옮길 수 있는 모양이 아니다.**
    """
    assert len(list(TimingPoint)) == 8
    #: 어느 값도 Lua 상수 이름을 쓰지 않는다.
    for point in TimingPoint:
        assert not point.value.startswith("event_")
        assert point.name not in {"EVENT_FREE_CHAIN", "EVENT_PHASE"}

    #: 만드는 입구가 사건 기록 쪽이다.
    trigger_src = source_of("engine/trigger.py")
    assert "def from_delta" in trigger_src
    assert "def from_journal_event" in trigger_src


# ======================================================================
# B. 값이 살아 있는가 — 실제 코퍼스로 확인한다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_04_the_event_setcode_is_preserved_in_the_corpus(repository):
    """
    §3 — **``EVENT_*`` 는 아키텍처에 살아 있다.** 없다고 말하면 거짓이다.

    측정값은 고유 스크립트 12,687개에 걸친 블록 34,631개 기준이다
    (``(card_id, index)`` 는 고유 키가 **아니다** — ``test_12`` 가 그 까닭을
    따로 고정한다).
    """
    scripts = [card.script for card in repository.all_cards() if card.script]
    blocks = [block for script in scripts for block in script.effects]

    events = [b for b in blocks if b.code and b.code.startswith("EVENT_")]
    free = [b for b in events if b.code == "EVENT_FREE_CHAIN"]

    #: 바닥값으로 고정한다 — 데이터 갱신이 숫자를 늘려도 깨지지 않는다.
    assert len(blocks) >= 34_631
    assert len(events) >= 16_381
    assert len({b.code for b in events}) >= 70
    assert len(free) >= 4_909


@requires_official_db
@pytest.mark.real_card
def test_05_the_registered_traps_all_declare_no_trigger_condition(repository):
    """
    §6 — 엔진이 함정을 막는 까닭을 코퍼스로 검증한다.

    ``engine/action_validation.py`` 의 주석은 "등재된 함정 5장은 전부
    ``EVENT_FREE_CHAIN`` (유발 조건 없음)" 이라고 적는다. **주석을 믿지 않고
    읽는다.**

    이것이 중요한 이유: 막는 까닭이 "데이터가 없어서" 가 아니라 **"옮기지
    않아서"** 임을 보인다. 값은 있다.
    """
    for card_id in REGISTERED_TRAPS:
        card = repository.get(card_id)
        assert card is not None, f"{card_id} 가 공식 DB 에 없다"
        assert card.script is not None
        codes = [block.code for block in card.script.effects]
        assert codes, f"{card_id} 에 효과 블록이 없다"
        assert set(codes) == {"EVENT_FREE_CHAIN"}, f"{card_id}: {codes}"


@requires_official_db
@pytest.mark.real_card
def test_06_the_engine_can_already_reach_the_event_value(repository):
    """
    §9 — **ACTUALLY_LOST 가 아니다.**

    ``engine.ids.iter_effects`` 는 ``engine`` 안의 production 함수이고
    ``(EffectRef, EffectSpec)`` 을 돌려준다. ``EffectSpec.code`` 가 사건 값을
    그대로 싣는다 — 즉 값은 **닿을 수 있는 곳에 있다.**

    엔진이 그것을 쓰지 않는 것은 설계다 (ADR-006 · STRUCTURAL-7 — 손으로
    등록한다). 그래서 ``INTENTIONALLY_DROPPED`` 이고 데이터 손실이 아니다.
    """
    card = repository.get(92595643)
    pairs = list(iter_effects(card))

    assert pairs, "효과가 하나도 없으면 이 시험이 흐려진다"
    for effect_ref, spec in pairs:
        assert isinstance(effect_ref, EffectRef)
        assert isinstance(spec, EffectSpec)
    assert {spec.code for _, spec in pairs} == {"EVENT_FREE_CHAIN"}

    #: 이 다리는 production 코드에 **있다** (engine/ids.py).
    assert "def iter_effects" in source_of("engine/ids.py")


@requires_official_db
@pytest.mark.real_card
def test_07_optional_and_mandatory_are_not_silently_collapsed(repository):
    """
    §8 — 강제/임의가 **뭉개지지 않았다.**

    파서가 ``TRIGGER_O`` (임의) 와 ``TRIGGER_F`` (강제) 를 따로 적는다.
    ``EffectDefinition`` 에는 그 칸이 없고 ``TriggerSpec.requirement`` 가
    등록 시점에 받는다 — 즉 **옮길 곳이 있고 값도 있다.**

    (파서는 ``EFFECT_TYPE_`` 접두어를 떼어 놓는다. 접두어를 붙여 세면 0 이
    나오므로 이름을 가정하지 않고 실제 값을 쓴다.)
    """
    kinds = [
        kind
        for card in repository.all_cards()
        if card.script
        for block in card.script.effects
        for kind in block.effect_types
    ]
    optional = kinds.count("TRIGGER_O")
    mandatory = kinds.count("TRIGGER_F")

    assert optional >= 6_083
    assert mandatory >= 1_969
    #: 접두어가 붙은 형태는 저장되지 않는다 — 이름 가정을 막는다.
    assert "EFFECT_TYPE_TRIGGER_O" not in kinds

    #: 받을 칸이 등록 계층에 있다.
    assert {r.name for r in TriggerRequirement} == {"MANDATORY", "OPTIONAL", "UNKNOWN"}
    assert {w.name for w in TriggerWording} == {"WHEN", "IF", "UNKNOWN"}
    #: 정의에는 없다.
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert definition & {"requirement", "wording", "mandatory", "optional"} == set()


@requires_official_db
@pytest.mark.real_card
def test_08_free_chain_never_coexists_with_a_trigger_type(repository):
    """
    ``EVENT_FREE_CHAIN`` 이 "유발 조건이 없다" 를 뜻한다는 전수 측정을
    HEAD 에서 **다시** 확인한다 (``core/card_model.py`` 가 적은 주장).

    이 사실이 깨지면 ``test_05`` 의 해석도 흔들린다.
    """
    clashes = [
        (card.id, block.index, block.effect_types)
        for card in repository.all_cards()
        if card.script
        for block in card.script.effects
        if block.code == "EVENT_FREE_CHAIN"
        and {"TRIGGER_O", "TRIGGER_F"} & set(block.effect_types)
    ]
    assert clashes == [], f"EVENT_FREE_CHAIN 이 유발 종류와 함께 쓰였다: {clashes[:5]}"


# ======================================================================
# C. Cardinality
# ======================================================================


def test_09_one_definition_maps_to_zero_or_many_trigger_specs():
    """
    §7 — **1 : 0..N 이고 N : 1 은 불가능하다.**

    ``TriggerSpec`` 은 ``effect_ref`` 하나를 가리키므로 여러 효과를 한 선언이
    덮을 수 없다. 반대로 같은 효과에 서로 다른 시점의 선언을 여러 개 붙일 수
    있다 — 그래서 ``TriggerSpec`` 은 **정의의 등록 시점 투영**이다.
    """
    ref = EffectRef(1000, 0)
    drawn = TriggerSpec(ref, TimingPoint.CARD_DRAWN)
    moved = TriggerSpec(ref, TimingPoint.CARD_MOVED)

    #: 같은 효과, 다른 시점 → 둘 다 등록된다 (1:N).
    assert len(TriggerRegistry((drawn, moved))) == 2
    #: 똑같은 선언 두 번 → 거부된다 (중복은 사실이 아니다).
    with pytest.raises(TriggerError):
        TriggerRegistry((drawn, drawn))

    #: 한 선언이 여러 효과를 가리키는 칸은 없다 (N:1 불가).
    fields = {f.name for f in dataclasses.fields(TriggerSpec)}
    assert "effect_ref" in fields
    assert not {f for f in fields if f.endswith("refs") or f == "effect_refs"}


def test_10_the_registered_definitions_have_no_trigger_specs_today():
    """
    지금의 사실 — 등재된 정의 16개에 대응하는 ``TriggerSpec`` 이 **하나도
    없다** (1 : 0). 그것이 "트리거 계층이 잠들어 있다" 의 데이터 쪽 모습이다.
    """
    registry = EffectDefinitionRegistry(
        tuple(entry.definition for entry in EFFECT_LIBRARY)
    )
    assert len(EFFECT_LIBRARY) == 16
    assert registry is not None

    #: production 에 ``TriggerSpec`` 을 만드는 자리가 없다.
    production, tests = call_sites("TriggerSpec")
    assert production == [], f"production 이 TriggerSpec 을 만든다: {production}"
    assert tests, "테스트에서도 안 만들면 측정이 잘못된 것이다"


# ======================================================================
# D. 경계가 그대로인가
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_11_ordinary_activation_needs_no_event(repository):
    """
    §5(프롬프트) — 보통의 발동은 사건을 요구하지 않는다. 3-E-30 의 결론이
    HEAD 에서도 성립함을 **동작으로** 확인한다. 그리고 판을 바꾸지 않고 RNG 도
    쓰지 않는다.
    """
    state = GameState.create(
        repository, decks=([POT_OF_GREED] * 6, [POT_OF_GREED] * 6), seed=1
    )
    state.draw(MINE, 2)
    state.draw(THEIRS, 2)
    instance = state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    state.turn.turn_number = 2
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)

    before_hash = state.state_hash()
    before_rng = state.rng.getstate()

    validator = ActionValidator(GameStateView.from_state(state, viewer=MINE))
    action = PlayerAction.activate_effect(
        actor=MINE, source=instance.instance_id, effect_ref=EffectRef(POT_OF_GREED, 0)
    )
    verdict = validator.validate(action)

    assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert verdict.permits_execution, f"{verdict.code}: {verdict.reason}"
    #: §11 — 감사가 판도 RNG 도 건드리지 않는다.
    assert state.state_hash() == before_hash
    assert state.rng.getstate() == before_rng


def test_12_the_card_view_exposes_the_definition_not_the_parsed_script():
    """
    §11 — 관측 경계가 그대로다.

    ``CardView`` 는 **손으로 등록한 ``definition``** 만 노출하고 파서가 읽은
    ``script`` 를 노출하지 않는다. 그래서 "트리거로 등록되었다" 는 사실
    하나로 상대 카드의 정체가 새지 않는다.

    그리고 ``(card_id, index)`` 가 고유 키가 아닌 까닭도 여기서 적어 둔다 —
    한 스크립트 안에서 같은 Lua 변수명(``e1``)이 여러 함수에 다시 나오므로,
    고유 단위는 **블록의 등장 순서**(``EffectRef.ordinal``)다.
    """
    fields = {f.name for f in dataclasses.fields(CardView)}
    assert "definition" in fields
    assert "script" not in fields
    assert not {f for f in fields if "effect_types" in f or f == "code"}

    #: ``ordinal`` 이 등장 순서라는 계약이 원본에 적혀 있다.
    ids_src = source_of("engine/ids.py")
    assert "card.script.effects`` 안에서의 0-기반 위치" in ids_src


def test_13_the_trigger_pipeline_is_still_not_production_reachable():
    """
    §10 — 트리거 파이프라인이 production 에서 닿지 않는다 (HEAD 에서 재측정).

    ``engine/trigger.py`` 는 전이 폐쇄에 들어오지만 그것은
    ``activation_timing`` 이 ``TimingPoint`` 를 **열거형으로만** 쓰기
    때문이다 (3-E-30 이 측정). 파이프라인을 **만드는** 모듈은 닿지 않는다.
    """

    def imported(path: str) -> set[str]:
        tree = ast.parse(source_of(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return {name for name in names if name.startswith("engine")}

    reached: set[str] = set()
    stack = ["engine/duel.py"]
    while stack:
        current = stack.pop()
        if current in reached:
            continue
        reached.add(current)
        for module in imported(current):
            base = module.replace(".", "/")
            for candidate in (base + ".py", base + "/__init__.py"):
                if (PROJECT_ROOT / candidate).exists() and candidate not in reached:
                    stack.append(candidate)

    for dormant in (
        "engine/trigger_chain.py",
        "engine/trigger_order.py",
        "engine/timing.py",
        "engine/event_pipeline.py",
    ):
        assert dormant not in reached


def test_14_the_engine_never_reads_the_setcode_argument_today():
    """
    §10 — ``EffectSpec.code`` 를 읽는 production 자리는 **``engine`` 밖**에만
    있다 (``analysis`` · ``sources``).

    이것이 "값은 있지만 엔진이 쓰지 않는다" 의 증거다. 숫자가 늘면 경계가
    움직인 것이므로 그때 이 Phase 의 결론을 다시 봐야 한다.
    """
    readers: dict[str, list[int]] = {}
    for path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        lines = sorted(
            {
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr == "code"
                and "spec" in ast.unparse(node.value)
            }
        )
        if lines:
            readers[str(path.relative_to(PROJECT_ROOT))] = lines

    assert set(readers) == {
        "analysis/effect_analyzer.py",
        "sources/lua_loader.py",
    }, readers
    assert not [name for name in readers if name.startswith("engine/")]


def test_15_the_missing_rule_points_at_the_registration_boundary():
    """
    엔진이 **스스로** 경계를 적어 두었다 — 모자란 것은 데이터가 아니라
    **옮기는 일**이다. 그 문장이 ``core`` 와 ``EffectDefinition`` 을 둘 다
    이름으로 부른다.
    """
    assert "SetCode(EVENT_*)" in TRAP_TRIGGER_MISSING
    assert "EffectDefinition" in TRAP_TRIGGER_MISSING

    #: 그리고 그 까닭이 기존 TODO 로 이미 적혀 있다 (새 ID 가 필요 없는 근거).
    for module in (
        "engine/trigger.py",
        "engine/effect/definition.py",
        "engine/effect/library.py",
    ):
        assert "STRUCTURAL-7" in source_of(module)


def test_16_this_audit_changed_no_production_file():
    """
    §1 — production diff 가 0 임을 **구조로** 확인한다.

    이 Phase 가 손댈 수 있었던 곳에 트리거 관련 새 칸이 생기지 않았다.
    """
    #: ``EffectDefinition`` 의 칸이 그대로다 (측정값 10개).
    assert len(dataclasses.fields(EffectDefinition)) == 10
    #: ``TriggerSpec`` 의 칸도 그대로다 (9개).
    assert len(dataclasses.fields(TriggerSpec)) == 9
    #: 사건을 적는 칸이 정의 쪽에 생기지 않았다.
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert definition & {"code", "point", "event", "trigger", "timing"} == set()
    #: 새 ActionKind 도 없다 (3-E-30 측정값 11개).
    assert len(list(PlayerActionKind)) == 11
