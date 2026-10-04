"""
Phase 3-E-25 — ``LibraryEntry`` 등록 관문이 의미를 보존하는가 (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

한 문장
-------
**등록 관문은 "출처 · 근거 · 서술 · 의미" 를 엄격하게 막지만 ``activation``
조건에는 관문이 하나도 없다.** 그런데 그 때문에 지금 틀리는 것은 없다 —
등록된 16개를 원문과 전수 대조한 결과 ``activation=None`` 인 것은 **원문에도
조건이 없는 것**들이었다.

실측으로 확인한 네 경우 (욕망의 항아리 정의의 ``activation`` 만 바꿔 넣었다)
------------------------------------------------------------------------
======================= ========= ==========================================
 ``activation``          등록      ``can_activate``
======================= ========= ==========================================
 ``None``                통과      **VALID** — 발동할 수 있다
 ``UnimplementedRule``   통과      **UNKNOWN** + ``missing_rule`` 에 이름
 ``Always()``            통과      VALID
 (원래 조건)              통과      VALID
======================= ========= ==========================================

그래서 두 가지가 동시에 사실이다.

* **§11 의 설계 B(DORMANT REGISTRATION)는 오늘 이미 가능하다.** 코드를 한 줄도
  바꾸지 않고, 조건을 ``UnimplementedRule`` 로 적으면 등록은 되고 발동은
  ``UNKNOWN`` 으로 막히며 **무엇이 없는지 이름이 남는다.**
  → `REGISTRATION ≠ ACTIVATION` 이 구조로 성립한다.
* **기본값은 C(SILENT PASS)다.** ``activation=None`` 은 통과하고,
  ``EffectActivator._check_condition`` 의 설명이 그 사실을 스스로 적어 두었다 —
  "``None`` 은 **'조건이 없다' 가 아니라 '적지 않았다'** 이므로 넘어간다".

그리고 그 문장은 ``TriggerSpec.condition`` 의 설명과 **상반된다** — 저쪽은
"``None`` 이면 … 적지 않았다는 뜻이다. **적지 않은 조건을 참으로 치지 않기
위해** 정의의 ``activation`` 도 함께 본다" 고 적는다. 받침이 되어야 할 쪽이
받치지 않는다.

parser 는 이 경로에 닿지 않는다
-------------------------------
``engine/effect/library.py`` 는 ``analysis/`` 도 ``sources/`` 도 import 하지
않는다. 조건은 **손으로 쓴 리터럴**이고 ``lua_excerpt`` 가 근거로 따라붙는다
(ADR-006). 그러므로 "parser 실패가 조건 없음으로 조용히 바뀐다" 는 일은
**구조적으로 일어날 수 없다** — 바뀔 변환 자체가 없다.
"""

import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.chain import Chain
from engine.condition.model import Always, UnimplementedRule
from engine.condition.result import ConditionResult
from engine.duel import Duel
from engine.effect.definition import (
    EffectDefinitionError,
    EffectProvenance,
    EffectSource,
)
from engine.effect.library import (
    EFFECT_LIBRARY,
    LibraryEntry,
    definition_registry,
    implementation_registry,
)
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
POT_OF_GREED = 55144522
FEATHERMAN = 21844576
THIEVES_PRIMER = 69091732  # 의적의 입문서 — 등록된 16개 중 원문에 조건이 있는 유일한 카드


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


def pot_entry() -> LibraryEntry:
    return next(
        e for e in EFFECT_LIBRARY if e.definition.effect_ref.card_id == POT_OF_GREED
    )


def try_activation(duel: Duel, entry: LibraryEntry, seat: int):
    """이 엔트리 하나만 아는 발동기로 ``can_activate`` 를 물어본다."""
    activator = EffectActivator(
        definition_registry((entry,)), implementation_registry((entry,))
    )
    action = PlayerAction.activate_effect(
        actor=seat,
        source=duel.state.player(seat).hand[0].instance_id,
        effect_ref=entry.definition.effect_ref,
    )
    return activator.can_activate(duel.state, Chain(), action)


# ======================================================================
# §3 — 등록 관문이 실제로 막는 것
# ======================================================================


def test_01_the_gate_blocks_source_evidence_and_description_but_not_the_condition():
    """
    **§3 — 관문은 네 가지를 막는다. ``activation`` 은 그중에 없다.**

    막는 것: 출처 금지(ADR-004) · 미검증 · 근거 파일 없음 · 서술 없음 ·
    ``MOVE``(ADR-002) · ``executable=False`` 인데 이유 없음.
    """
    base = pot_entry()

    #: ① 실행하지 않는 효과에 이유를 적지 않으면 거부한다.
    with pytest.raises(EffectDefinitionError, match="무엇이 없어서인지"):
        dataclasses.replace(base, executable=False, note="")

    #: ② 출처가 금지하면 실행 등록을 거부한다 (ADR-004).
    forbidden = dataclasses.replace(
        base.definition,
        provenance=EffectProvenance(source=EffectSource.OFFICIAL_TEXT, verified=True),
    )
    with pytest.raises(EffectDefinitionError, match="실행을 금지"):
        dataclasses.replace(base, definition=forbidden)

    #: ③ 검증되지 않았으면 거부한다.
    unverified = dataclasses.replace(
        base.definition,
        provenance=EffectProvenance(source=EffectSource.OFFICIAL_LUA, verified=False),
    )
    with pytest.raises(EffectDefinitionError, match="검증되지 않았"):
        dataclasses.replace(base, definition=unverified)

    #: ④ 무엇을 하는지 적지 않았으면 거부한다.
    empty = dataclasses.replace(base.definition, operations=())
    with pytest.raises(EffectDefinitionError, match="적혀 있지 않은데"):
        dataclasses.replace(base, definition=empty)

    #: 그런데 **조건을 지우는 것은 아무도 막지 않는다.**
    without_condition = dataclasses.replace(base.definition, activation=None)
    entry = dataclasses.replace(base, definition=without_condition)
    assert entry.definition.activation is None  # 예외가 나지 않는다
    assert entry.executable


def test_02_the_gate_source_has_no_check_on_activation_at_all():
    """**§3 — 관문 본문에 ``activation`` 이라는 글자가 없다.**"""
    source = (PROJECT_ROOT / "engine/effect/library.py").read_text(encoding="utf-8")
    gate = source.split("def __post_init__")[1].split("\n    @property")[0]
    assert "activation" not in gate
    #: 막는 것들은 적혀 있다.
    for token in ("is_forbidden", "verified", "is_described", "OperationKind.MOVE", "note"):
        assert token in gate, token


# ======================================================================
# §5 · §6 — 네 경우를 실제로 등록하고 발동을 시도한다
# ======================================================================


@pytest.mark.real_card
def test_03_an_unimplemented_rule_registers_and_then_refuses_as_unknown(repository):
    """
    **§6 · §11-B — 등록 성공과 발동 가능성이 **이미** 분리되어 있다.**

    ``UnimplementedRule`` 을 조건으로 적으면 등록은 통과하고, 발동은
    ``UNKNOWN`` 이 되며 ``missing_rule`` 에 **무엇이 없는지** 이름이 남는다.
    코드를 바꾸지 않고도 "등록은 하되 발동은 막는다" 가 된다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    base = pot_entry()

    definition = dataclasses.replace(
        base.definition, activation=UnimplementedRule("사건 문맥 (Phase 3-E-23)")
    )
    entry = dataclasses.replace(base, definition=definition)  # 등록 통과
    verdict = try_activation(duel, entry, seat)

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule and "사건 문맥" in verdict.missing_rule
    assert "판정할 수 없습니다" in verdict.reason


@pytest.mark.real_card
def test_04_none_and_always_are_indistinguishable_at_the_verdict(repository):
    """
    **§4 · §5 — ``None`` 과 ``Always()`` 는 구조에서는 다르고 판정에서는 같다.**

    ``None``("적지 않았다" — ``_check_condition`` 의 설명)과 ``Always()``
    ("언제나 참" 이라고 **적었다**)가 **같은 VALID** 를 낸다. 구별은 표현에만
    있고 결과에는 없다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    base = pot_entry()

    results = {}
    for label, activation in (
        ("none", None),
        ("always", Always()),
        ("original", base.definition.activation),
    ):
        entry = dataclasses.replace(
            base, definition=dataclasses.replace(base.definition, activation=activation)
        )
        verdict = try_activation(duel, entry, seat)
        results[label] = (verdict.validity, verdict.code)

    assert results["none"] == (ActionValidity.VALID, ValidationCode.OK)
    assert results["always"] == results["none"] == results["original"]


def test_05_the_two_docstrings_disagree_about_what_none_means():
    """
    **§2 · §10 — 같은 ``None`` 을 두 모듈이 반대로 읽는다.**

    ``EffectActivator._check_condition`` — "``None`` 은 … '적지 않았다' 이므로
    **넘어간다**" (= 참으로 친다).
    ``TriggerSpec.condition`` — "``None`` 이면 … 적지 않았다는 뜻이다.
    **적지 않은 조건을 참으로 치지 않기 위해** 정의의 ``activation`` 도 함께
    본다" (= 참으로 치지 않겠다).

    받침이 되어야 할 쪽(정의의 ``activation``)이 ``None`` 이면 받치지 않는다.
    """
    activation_source = (PROJECT_ROOT / "engine/activation.py").read_text(encoding="utf-8")
    check = activation_source.split("def _check_condition")[1].split("\n    def ")[0]
    assert "'조건이 없다' 가 아니라 \"적지 않았다\"" in check or "적지 않았다" in check
    assert "넘어간다" in check
    assert "if definition.activation is None:\n            return None" in check

    trigger_source = (PROJECT_ROOT / "engine/trigger.py").read_text(encoding="utf-8")
    #: 문장이 줄바꿈으로 끊겨 있으므로 공백을 접어서 본다.
    flattened = " ".join(trigger_source.split())
    assert "조건이 없다는 뜻이 아니라 적지 않았다는 뜻" in flattened
    assert "적지 않은 조건을 참으로 치지 않기 위해" in flattened


def test_06_vacuous_truth_itself_is_sound():
    """
    **§4 — ``all_of([]) == TRUE`` 는 논리적으로 정상이다.**

    문제는 이 규약이 아니라 **빈 조건이 무엇을 뜻하는가**다. 규약은 그대로
    두어야 한다 — 바꾸면 "조건이 진짜 없는 효과" 가 발동할 수 없게 된다.
    """
    assert ConditionResult.all_of([]) is ConditionResult.TRUE
    assert ConditionResult.any_of([]) is ConditionResult.FALSE
    #: 그리고 ``UNKNOWN`` 이 섞이면 전체가 ``UNKNOWN`` 이다 — 빈 묶음과 다르다.
    assert (
        ConditionResult.all_of([ConditionResult.UNKNOWN]) is ConditionResult.UNKNOWN
    )


# ======================================================================
# §8 — 등록된 corpus 전수 대조
# ======================================================================


@pytest.mark.real_card
def test_07_every_registered_none_condition_matches_a_source_without_one(repository):
    """
    **§8 — 지금 등록된 것들은 일관적이다** (16개 전수 대조).

    ``activation=None`` 인 엔트리의 Lua 블록에는 ``SetCondition`` 이 **없다.**
    즉 그 ``None`` 은 "적지 않았다" 가 아니라 **"조건이 없다"** 다. 관문이
    막지 않아도 **사람이 지켰다** — 그리고 ``lua_excerpt`` 덕분에 그것을
    **대조할 수 있었다.**
    """
    mismatches = []
    none_count = 0
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        spec = ref.resolve(card) if card is not None else None
        path = PROJECT_ROOT / f"c{ref.card_id}.lua"
        source = path.read_text(encoding="utf-8") if path.is_file() else ""
        has_condition = spec is not None and f"{spec.index}:SetCondition(" in source

        if entry.definition.activation is None:
            none_count += 1
            if has_condition:
                mismatches.append((ref.card_id, ref.ordinal))

    assert none_count >= 8  # 측정: 실행 가능 5 + 실행 불가 3
    assert mismatches == [], mismatches


@pytest.mark.real_card
def test_08_the_one_card_with_a_source_condition_has_it_written_and_quoted(repository):
    """
    **§8 — 원문에 조건이 있는 유일한 등록 카드는 그것을 적어 두었다.**

    ``의적의 입문서`` 의 Lua 조건은 "상대 패가 5장 이상" 이고, 등록된
    ``activation`` 이 바로 그것이며 ``lua_excerpt`` 가 그 Lua 한 줄을 담는다.
    **``lua_excerpt`` 가 사실상 조건 대응의 감사 수단**이다.
    """
    entry = next(
        e for e in EFFECT_LIBRARY if e.definition.effect_ref.card_id == THIEVES_PRIMER
    )
    assert entry.definition.activation is not None
    assert "상대 HAND 에 5장 이상" in entry.definition.activation.describe_ko()
    assert "GetFieldGroupCount(tp,0,LOCATION_HAND)>4" in entry.lua_excerpt

    source = (PROJECT_ROOT / f"c{THIEVES_PRIMER}.lua").read_text(encoding="utf-8")
    assert "e1:SetCondition(s.condition)" in source
    assert "Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4" in source


# ======================================================================
# §9 — parser 는 이 경로에 닿지 않는다
# ======================================================================


def test_09_the_library_never_imports_the_parser_or_the_analysis_layer():
    """
    **§9 · Invariant 3 — "parser 실패 → 조건 없음" 변환은 구조적으로 없다.**

    정의는 **손으로 쓴 리터럴**이고 근거(``lua_excerpt``)가 따라붙는다
    (ADR-006). 자동 변환이 없으므로 조용히 떨어질 조건도 없다.
    """
    import ast

    tree = ast.parse((PROJECT_ROOT / "engine/effect/library.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [m for m in modules if m.startswith(("analysis", "sources", "core"))], (
        sorted(modules)
    )
    #: 조건은 ``engine.condition`` 에서 바로 가져와 손으로 세운다.
    assert "engine.condition" in modules


def test_10_the_activation_path_merges_two_unknown_reasons_into_one_code():
    """
    **🟡 기록 — ``_check_condition`` 의 UNKNOWN 코드가 하나로 묶여 있다.**

    ``ActionValidator._check_requirements`` 는 "정보가 없어서" 와 "규칙이
    없어서" 를 **다른 코드**로 가르는데, ``EffectActivator._check_condition``
    은 둘 다 ``INFORMATION_UNAVAILABLE`` 로 적는다. 다만 ``missing`` 에 이름이
    남으므로 **정보는 잃지 않는다** — 코드만 덜 정확하다
    (Phase 3-E-24 의 발견 ①과 같은 모양).
    """
    source = (PROJECT_ROOT / "engine/activation.py").read_text(encoding="utf-8")
    check = source.split("def _check_condition")[1].split("\n    def ")[0]
    assert check.count("ValidationCode.INFORMATION_UNAVAILABLE") == 1
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" in check  # 거짓일 때 쓰는 코드
    assert 'missing="; ".join(evaluated.unknown_reasons)' in check

    validator = (PROJECT_ROOT / "engine/action_validation.py").read_text(encoding="utf-8")
    requirements = validator.split("def _check_requirements")[1].split("\n    def ")[0]
    assert "ValidationCode.RULE_NOT_IMPLEMENTED" in requirements
    assert "ValidationCode.INFORMATION_UNAVAILABLE" in requirements


# ======================================================================
# §12 — Safety Invariant
# ======================================================================


@pytest.mark.real_card
def test_11_registration_success_does_not_mean_activation_success(repository):
    """**Invariant 4 — PASS.** 같은 엔트리가 등록은 되고 발동은 막힌다."""
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    base = pot_entry()

    blocked = dataclasses.replace(
        base,
        definition=dataclasses.replace(
            base.definition, activation=UnimplementedRule("감사용 미구현 규칙")
        ),
    )
    #: 등록은 예외 없이 통과한다.
    assert blocked.executable
    #: 그런데 발동은 허가되지 않는다.
    assert try_activation(duel, blocked, seat).validity is not ActionValidity.VALID


@pytest.mark.real_card
def test_12_an_unwritten_condition_is_not_promoted_to_false_either(repository):
    """
    **Invariant 2 — PASS.** 미구현을 **거짓**으로도 접지 않는다.

    ``UnimplementedRule`` 의 결과는 ``INVALID`` 가 아니라 ``UNKNOWN`` 이다 —
    "규칙이 없다" 가 "규칙 위반" 으로 바뀌지 않는다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    base = pot_entry()
    entry = dataclasses.replace(
        base,
        definition=dataclasses.replace(
            base.definition, activation=UnimplementedRule("감사용 미구현 규칙")
        ),
    )
    verdict = try_activation(duel, entry, seat)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.validity is not ActionValidity.INVALID
