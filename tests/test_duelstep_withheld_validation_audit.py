r"""
Phase 3-E-41 — ``DuelStep`` / ``WithheldAction`` validation information 경계 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다.

이 Phase 의 질문
---------------
"``ValidationResult`` 에서 얻은 판정 정보 중 ``DuelStep`` 과
``WithheldAction`` 이 **반드시** 보존해야 하는 것은 무엇인가?"

측정한 결론 (요지)
-----------------
1. ``DuelStep`` 은 ``code`` 를 **보존한다** (필수 필드다). 잃는 것은
   ``validity`` · ``missing_rule`` · ``notes`` 다.
2. 그런데 **``validity`` 는 ``code`` 에서 복원된다** — Phase 3-E-40 이
   ``CODE_VALIDITY`` 를 만들었기 때문이다 (48개 중 47개). 즉 3-E-39 가
   "뿌리 원인" 으로 지목한 손실은 **앞 Phase 가 이미 닫았다.**
3. ``WithheldAction`` 에는 ``code`` 가 없다. 그러나 ``LegalActions.withheld``
   를 읽는 production 소비자가 **0곳**이고, 그 자료형의 계약은 "엔진이
   무엇을 **아직** 못 하는가" 다 — 확실한 거부는 "아직" 이 아니다.
4. 거절된 ``DuelStep`` 은 실제 플레이에서 **나오지 않는다** (32판 11,609걸음
   중 0건). 나오게 만들면 ``DuelRunner`` 가 **정책의 결함**으로 보고 판을
   멈춘다 — 역사(history)가 아니라 진단(diagnostic)이다.

찾은 결함 셋 (고치지 않고 기록한다)
----------------------------------
* **F-1** ``duel.py:683`` 이 코드를 **갈아 끼운다** — ``HIDDEN_CARD`` 판정이
  ``DuelStep`` 에서 ``RULE_NOT_IMPLEMENTED`` 가 된다 (``test_12`` 가 실행으로
  보인다). 둘 다 ``UNKNOWN`` 이라 validity 는 살지만 **이유가 틀린다.**
* **F-2** ``_withheld_board_actions`` 가 **첫 장에서 멈추고**, 발동 후보별
  게이트 판정(M1·M2)은 **아예 기록되지 않는다** (``test_15`` · ``test_16``).
* **F-3** 세 ``WithheldAction`` 생성 자리가 ``missing`` 을 서로 다른 출처에서
  가져온다 (``test_09``).
"""

import ast
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator
from engine.duel import Duel, DuelStep, LegalActions, WithheldAction
from engine.ids import InstanceId
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
    unknown_codes,
)
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROD_PREFIXES = ("engine/", "agent/", "core/", "analysis/", "sources/", "app/")

DECK = (
    [11091375] * 3
    + [5053103] * 3
    + [1184620] * 3
    + [32864] * 3
    + [3557275] * 3
    + [55144522] * 5
)
POT_OF_GREED = 55144522


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith(PROD_PREFIXES):
            yield rel, path


def attribute_reads(attr: str) -> list[str]:
    """production 전체에서 ``<무엇>.<attr>`` 을 읽는 자리."""
    hits = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == attr:
                hits.append(f"{rel}:{node.lineno} ({ast.unparse(node)})")
    return hits


def constructions(name: str) -> list[str]:
    hits = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            ):
                hits.append(f"{rel}:{node.lineno}")
    return hits


def started(repository, seed: int = 11, phase: "Phase | None" = None) -> Duel:
    duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
    while duel.advance() is not None:
        pass
    if phase is not None:
        for _ in range(20):
            while duel.advance() is not None:
                pass
            if duel.state.turn.phase is phase:
                break
            legal = duel.legal_actions(duel.to_act)
            ends = [a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE]
            if not ends:
                break
            duel.apply(ends[0])
    return duel


# ======================================================================
# 1 ~ 3 — 세 자료형의 실제 필드 (추측하지 않는다)
# ======================================================================


def test_01_duelstep_field_inventory():
    """
    **§24-1 · §5: ``DuelStep`` 의 필드는 다섯이다.**

    프롬프트가 든 ``status`` · ``viewer`` · ``validation`` · ``state_hash`` ·
    ``future`` 는 **없다.** 있다고 추측하지 않고 센다.
    """
    fields = {f.name: f.type for f in dataclasses.fields(DuelStep)}
    assert set(fields) == {"action", "accepted", "code", "reason", "result"}
    #: ``code`` 는 **선택이 아니다** — 모든 걸음이 코드를 들고 있다.
    assert "ValidationCode" in str(fields["code"])
    assert "None" not in str(fields["code"])
    for absent in ("status", "viewer", "validation", "state_hash", "future",
                   "validity", "missing_rule", "notes"):
        assert absent not in fields, absent


def test_02_withheld_action_field_inventory():
    """
    **§24-2 · §6: ``WithheldAction`` 의 필드는 셋이다.**

    3-E-40 이 "code 가 없다" 고 적었다. **실제 HEAD 에서 다시 확인한다.**
    그리고 ``action`` 자체도 없다 — 들고 있는 것은 **종류**(`kind`)뿐이다.
    """
    fields = {f.name for f in dataclasses.fields(WithheldAction)}
    assert fields == {"kind", "reason", "missing"}
    for absent in ("code", "status", "validation", "source", "viewer", "action",
                   "validity", "notes"):
        assert absent not in fields, absent
    #: 들고 있는 것은 행위가 아니라 **종류**다 — 어느 카드인지 적지 않는다.
    assert isinstance(WithheldAction(PlayerActionKind.PASS, "x").kind, PlayerActionKind)


def test_03_validation_result_field_inventory():
    """**§24-3: ``ValidationResult`` 의 필드는 다섯이다.** 비교의 기준점이다."""
    fields = {f.name for f in dataclasses.fields(ValidationResult)}
    assert fields == {"validity", "code", "reason", "missing_rule", "notes"}
    #: 프롬프트가 든 ``status`` 는 **이 자료형에 없다** — 상태는 계층마다
    #: 따로 있다 (``ActivationStatus`` · ``ResolutionStatus`` …).
    assert "status" not in fields


def test_04_legal_actions_field_inventory():
    """**§6: 보류가 사는 곳.**"""
    assert {f.name for f in dataclasses.fields(LegalActions)} == {
        "seat",
        "allowed",
        "withheld",
    }


# ======================================================================
# 5 ~ 8 — 정보 흐름: 보존 · 변환 · 탈락 · 파생
# ======================================================================


def test_05_the_code_is_preserved_across_the_duelstep_boundary():
    """
    **§7: ``code`` 는 PRESERVED 다.**

    ``DuelStep`` 을 만드는 production 자리 전부가 코드를 넘긴다 — 17곳이고
    **모두 ``engine/duel.py`` 안에 있다.** 다른 모듈은 걸음을 만들지 않는다.
    """
    sites = constructions("DuelStep")
    assert len(sites) == 17
    assert all(site.startswith("engine/duel.py:") for site in sites)

    tree = ast.parse(source_of("engine/duel.py"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DuelStep"
        ):
            #: 세 번째 인자(또는 ``code=``)가 늘 있다.
            positional = len(node.args) >= 3
            keyword = any(k.arg == "code" for k in node.keywords)
            assert positional or keyword, node.lineno


def test_06_the_validity_is_not_stored_but_is_derivable_from_the_code():
    """
    **§7 · Q1: ``validity`` 는 DROPPED 가 아니라 DERIVED 다.**

    이것이 이 Phase 의 가장 중요한 측정이다. 3-E-39 는 "``DuelStep`` 이
    ``validity`` 를 버린다" 를 뿌리 원인으로 지목했다. 그런데 Phase 3-E-40 이
    ``CODE_VALIDITY`` 를 만든 뒤로는 **코드에서 판정을 되찾을 수 있다** —
    48개 중 **47개**다. 되찾을 수 없는 하나는 3-E-40 이 일부러 ``None`` 으로
    둔 ``CHAIN_DEFINITION_UNAVAILABLE`` 이다.

    즉 ``DuelStep`` 에 ``validity`` 필드를 더하면 **같은 사실의 둘째 사본**이
    생기고, 그것은 3-E-40 이 지운 바로 그 모양이다.
    """
    assert not hasattr(DuelStep, "validity")
    recoverable = {
        name: CODE_VALIDITY[ValidationCode[name]] for name in ValidationCode.__members__
    }
    assert len(recoverable) == 48
    assert sum(1 for v in recoverable.values() if v is not None) == 47
    assert [n for n, v in recoverable.items() if v is None] == [
        "CHAIN_DEFINITION_UNAVAILABLE"
    ]


def test_07_missing_rule_and_notes_are_dropped_at_both_boundaries():
    """
    **§7 · §8 · Q3 · Q4: ``missing_rule`` 과 ``notes`` 는 DROPPED 다.**

    ``DuelStep`` 에는 둘 다 없고, ``WithheldAction`` 에는 ``missing`` 하나가
    **비슷한 것**으로 있다 — 이름이 다르고 출처도 자리마다 다르다
    (``test_09``).
    """
    step_fields = {f.name for f in dataclasses.fields(DuelStep)}
    assert "missing_rule" not in step_fields
    assert "notes" not in step_fields

    held_fields = {f.name for f in dataclasses.fields(WithheldAction)}
    assert "missing" in held_fields
    assert "notes" not in held_fields

    #: 그런데 둘 다 **기계가 읽는 값이 아니다** — 사람이 읽는 로드맵 문자열이다.
    sample = ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED,
        "모른다",
        missing_rule="turn-progression (Phase 2-G)",
        notes=("관찰 1", "관찰 2"),
    )
    assert isinstance(sample.missing_rule, str)
    assert all(isinstance(note, str) for note in sample.notes)


def test_08_the_accepted_flag_compresses_three_validities_into_two_values():
    """
    **§9: ``accepted`` 하나로는 네 가지를 가를 수 없다.**

    ``ActionValidity`` 는 세 값이고 ``accepted`` 는 둘이다. 그래서 거부와
    모름이 같은 ``False`` 가 된다 — **코드를 함께 보지 않으면** 구분할 수 없다.
    """
    assert len(ActionValidity) == 3
    step_type = {f.name: f.type for f in dataclasses.fields(DuelStep)}["accepted"]
    assert "bool" in str(step_type)

    #: 그러나 코드를 함께 보면 갈라진다 — 그것이 ``code`` 가 필수 필드인 까닭이다.
    for name in ("CANDIDATE_NOT_ELIGIBLE", "EXECUTION_FORBIDDEN"):
        assert CODE_VALIDITY[ValidationCode[name]] is ActionValidity.INVALID
    for name in ("RULE_NOT_IMPLEMENTED", "HIDDEN_CARD"):
        assert CODE_VALIDITY[ValidationCode[name]] is ActionValidity.UNKNOWN


def test_09_the_three_withheld_sites_fill_missing_from_three_different_sources():
    """
    **F-3 (§8): 같은 칸이 자리마다 다른 출처에서 채워진다.**

    세 자리뿐이고 전부 ``engine/duel.py`` 안에 있다.

    ====================  ===============================================
    ``duel.py:620``       손으로 쓴 문자열 (``ValidationResult`` 가 **없다**)
    ``duel.py:633``       ``plan.unresolved_rules`` (verdict 의 것이 **아니다**)
    ``duel.py:654``       ``verdict.missing_rule``
    ====================  ===============================================

    고치지 않고 적어 둔다 — 세 자리가 같은 칸에 다른 종류의 값을 넣는다는
    사실 자체가 이 경계의 계약이 느슨하다는 증거다.
    """
    sites = constructions("WithheldAction")
    assert len(sites) == 3
    assert all(site.startswith("engine/duel.py:") for site in sites)

    source = source_of("engine/duel.py")
    assert 'missing="우선권을 여는 규칙 (Phase 2-F)"' in source
    assert 'missing="; ".join(plan.unresolved_rules) or None' in source
    assert "missing=verdict.missing_rule" in source


# ======================================================================
# 9 ~ 13 — 실제 시나리오 (§19)
# ======================================================================


@requires_official_db
def test_10_a_valid_action_carries_ok_and_the_validator_is_not_the_authority(repository):
    """
    **§19-A: 받아들여진 걸음.**

    그리고 중요한 뉘앙스: ``end_phase`` 는 ``ActionValidator`` 가 ``UNKNOWN``
    이라고 하는데도 **허가되고 받아들여진다.** 흐름 행위의 적법성은 검증기가
    아니라 **흐름 계층**(``TurnProgressor``)이 정한다. 그래서 "그 행위의
    ``ValidationResult``" 가 곧 그 걸음의 판정은 **아니다.**
    """
    duel = started(repository)
    seat = duel.to_act
    legal = duel.legal_actions(seat)
    action = next(a for a in legal.allowed if a.kind is PlayerActionKind.END_PHASE)

    verdict = ActionValidator(duel.view(seat)).validate(action)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED

    step = duel.apply(action)
    assert step.accepted is True
    assert step.code is ValidationCode.OK
    assert CODE_VALIDITY[step.code] is ActionValidity.VALID


@requires_official_db
def test_11_an_accepted_step_always_carries_ok_in_a_real_duel(repository):
    """
    **§19-A · Q6: 받아들여진 걸음의 코드는 늘 ``OK`` 다.**

    즉 ``accepted=True`` 쪽에서는 압축이 **정보를 잃지 않는다** —
    ``accepted`` 와 ``code`` 와 policy 가 모두 같은 말을 한다.
    """
    duel = started(repository, seed=5)
    seen = set()
    for _ in range(40):
        while duel.advance() is not None:
            pass
        if duel.is_over:
            break
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            break
        step = duel.apply(legal.allowed[0])
        seen.add((step.accepted, step.code))
        if not step.accepted:
            break
    assert seen == {(True, ValidationCode.OK)}
    for accepted, code in seen:
        assert CODE_VALIDITY[code] is ActionValidity.VALID


@requires_official_db
def test_12_the_duelstep_substitutes_the_code_for_a_non_candidate(repository):
    """
    **F-1 (§19-B · G): 코드가 TRANSFORMED 된다 — 그리고 틀린다.**

    가려진 카드를 가리키는 수를 ``apply`` 에 직접 주면:

    * ``ActionValidator`` → ``UNKNOWN`` · ``HIDDEN_CARD``
      ("이 듀얼에 없는지 가려진 존에 있는지 구분할 수 없습니다")
    * ``DuelStep``        → ``RULE_NOT_IMPLEMENTED``
      ("지금 허가된 행위가 아닙니다")

    **이유가 갈아 끼워졌다.** 둘 다 policy 상 ``UNKNOWN`` 이라 판정은 살지만,
    "가려져서 모른다" 가 "엔진이 못 한다" 로 바뀐다.

    .. note::
       production 경로에서는 닿지 않는다 — ``Simulator.simulate`` 와
       ``DuelRunner._judge`` 가 후보 여부를 **먼저** 본다. 즉 이 자리는
       **부르는 쪽의 잘못**을 알리는 진단이고, 그것을 알리는 데에는 지금의
       코드로도 충분하다. 고치지 않고 기록한다.
    """
    duel = started(repository)
    seat = duel.to_act
    ghost = PlayerAction.normal_summon(actor=seat, source=InstanceId(9999))

    verdict = ActionValidator(duel.view(seat)).validate(ghost)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.HIDDEN_CARD

    step = duel.apply(ghost)
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert step.code is not verdict.code

    #: 판정은 살아남는다 — 둘 다 모름 쪽이다.
    assert CODE_VALIDITY[verdict.code] is ActionValidity.UNKNOWN
    assert CODE_VALIDITY[step.code] is ActionValidity.UNKNOWN
    assert step.code in unknown_codes()


@requires_official_db
def test_13_a_rejected_step_never_touches_the_board(repository):
    """**§19-B: 거절은 판을 바꾸지 않는다.** 압축과 무관하게 지켜지는 성질이다."""
    duel = started(repository)
    before = duel.state.state_hash()
    draws = duel.state.randomness.draws
    duel.apply(
        PlayerAction.normal_summon(actor=duel.to_act, source=InstanceId(9999))
    )
    assert duel.state.state_hash() == before
    assert duel.state.randomness.draws == draws


@requires_official_db
def test_14_the_unknown_validation_of_a_withheld_card_reaches_the_consumer(repository):
    """
    **§19-C: 모름은 ``withheld`` 로 전달된다 — 다만 코드 없이.**

    ``activate_card`` 는 ``ActionValidator`` 가 ``UNKNOWN`` ·
    ``RULE_NOT_IMPLEMENTED`` 로 판정하고, 그 ``reason`` 과 ``missing_rule`` 이
    보류 항목에 그대로 실린다. **잃는 것은 ``code`` 와 ``validity`` 다.**
    """
    duel = started(repository, phase=Phase.MAIN1)
    seat = duel.to_act
    legal = duel.legal_actions(seat)
    held = [w for w in legal.withheld if w.kind is PlayerActionKind.ACTIVATE_CARD]
    assert held, "보류가 없는 판이면 이 측정이 무의미하다"

    validator = ActionValidator(duel.view(seat))
    first = duel.state.player(seat).hand[0]
    verdict = validator.validate(
        PlayerAction.activate_card(actor=seat, source=first.instance_id)
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED

    entry = held[0]
    #: 사람이 읽는 두 칸은 **그대로 온다.**
    assert entry.reason == verdict.reason
    assert entry.missing == verdict.missing_rule
    #: 기계가 읽는 두 칸은 **오지 않는다.**
    assert not hasattr(entry, "code")
    assert not hasattr(entry, "validity")


@requires_official_db
def test_15_the_m1_gate_verdict_is_never_recorded_anywhere(repository):
    """
    **F-2 · §10 · §19-D: M1 은 어디에도 남지 않는다.**

    덱을 1장으로 만들면 욕망의 항아리의 발동 조건("자신 DECK 에 2장 이상")이
    **확실히 거짓**이 된다. 그때:

    * 게이트    → ``INVALID`` · ``CANDIDATE_NOT_ELIGIBLE`` ("발동 조건이 거짓")
    * ``allowed``  → 발동 후보 **0건**
    * ``withheld`` → ``ACTIVATE_CARD`` 한 건, 이유는 **"아직 못 한다"**

    즉 소비자가 보는 유일한 기록이 **다른 행위 종류의 다른 이유**다. 게이트의
    판정은 ``WithheldAction`` 으로도 ``DuelStep`` 으로도 남지 않는다 —
    ``_activation_actions`` 가 ``continue`` 로 넘어가기 때문이다.
    """
    duel = started(repository, phase=Phase.MAIN1)
    seat = duel.to_act
    player = duel.state.player(seat)
    assert any(card.card_id == POT_OF_GREED for card in player.hand)
    while len(player.deck) > 1:
        player.deck.pop()

    legal = duel.legal_actions(seat)
    activations = [
        a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert activations == []

    #: 게이트에 직접 물으면 **확실한 거부**가 나온다.
    from engine.spell_activation import activatable_effects
    from engine.target_bridge import selections_for

    verdicts = []
    for card in player.hand:
        for ref in activatable_effects(card.card_id):
            definition = duel._activator.definitions.definition_for(ref)
            if definition is None:  # pragma: no cover - 목록이 보증한다
                continue
            candidate = PlayerAction.activate_effect(
                actor=seat, source=card.instance_id, effect_ref=ref
            )
            verdicts.append(
                duel._activation_gate(
                    candidate,
                    validator=ActionValidator(duel.view(seat)),
                    selections=selections_for(definition, candidate),
                )
            )
    assert verdicts, "발동 가능한 정의가 하나는 있어야 이 측정이 성립한다"
    assert all(v.validity is ActionValidity.INVALID for v in verdicts)
    assert all(v.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE for v in verdicts)

    #: 그런데 보류 목록에는 **그 코드도, 그 종류도** 없다.
    kinds = {w.kind for w in legal.withheld}
    assert PlayerActionKind.ACTIVATE_EFFECT not in kinds
    assert all(not hasattr(w, "code") for w in legal.withheld)
    #: 남아 있는 것은 "아직 못 한다" 쪽 이야기다.
    assert any("아직 없습니다" in w.reason for w in legal.withheld)


def test_16_the_withheld_board_scan_stops_after_the_first_card():
    """
    **F-2 (후반): 보류는 패의 첫 장에서 멈춘다.**

    주석이 그 까닭을 적는다 — "같은 이유가 패의 카드마다 반복되므로 종류별로
    하나씩만 남긴다". 그 전제가 **늘 참은 아니다**: 두 장이 서로 다른 까닭으로
    보류되면 첫 장의 이유가 둘 다를 대표한다.

    구문으로 확인한다 — 함수 안에 ``break`` 가 있다.
    """
    tree = ast.parse(source_of("engine/duel.py"))
    scan = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_withheld_board_actions"
    )
    body = ast.unparse(scan)
    assert "break" in body
    assert "종류별로 하나씩만" in source_of("engine/duel.py")


@requires_official_db
def test_17_the_m2_path_never_becomes_a_candidate_so_it_has_nothing_to_lose(repository):
    """
    **§10 · §19-E: M2 는 후보가 되기 **전에** 걸러진다.**

    ``activatable_effects`` 가 ``executable`` 인 효과만 돌려주므로, 출처가
    실행을 금지하는 효과(그리고 구현이 등록되지 않은 효과)는 **후보 목록에
    오르지 않는다.** 그래서 ``DuelStep`` 도 ``WithheldAction`` 도 그 코드를
    볼 기회가 없다 — 잃을 정보가 애초에 그 경계에 도달하지 않는다.
    """
    from engine.effect.library import EFFECT_LIBRARY
    from engine.spell_activation import activatable_effects

    non_executable = [e for e in EFFECT_LIBRARY if not e.executable]
    assert non_executable, "이 측정은 실행 불가 항목이 하나는 있어야 성립한다"
    for entry in non_executable:
        card_id = entry.definition.effect_ref.card_id
        assert entry.definition.effect_ref not in activatable_effects(card_id)


def test_18_m3_is_still_dormant_and_cannot_reach_either_boundary():
    """**§10 · Q9: M3 는 여전히 dormant 다.** 3-E-38/39 의 측정을 다시 고정한다."""
    built = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("TriggerSpec", "TriggerRegistry")
            ):
                built.append(f"{rel}:{node.lineno}")
    assert built == []
    assert "trigger" not in source_of("engine/duel.py")


def test_19_priority_state_stale_is_produced_by_a_method_nobody_calls():
    """
    **§19-H: ``PRIORITY_STATE_STALE`` 은 UNREACHABLE IN CURRENT PRODUCTION.**

    생성 자리는 ``PriorityState`` 쪽의 ``_staleness()`` 하나이고, 그것을 부르는
    것은 ``may_respond()`` 뿐이며, **``may_respond`` 를 부르는 production 자리가
    0곳**이다. 그래서 이 코드는 어느 경계에도 도달하지 않는다.

    (3-E-40 이 이 코드를 ``UNKNOWN`` 으로 분류한 것은 **뜻**에 대한 판단이고,
    도달성과는 다른 사실이다 — 섞지 않는다.)
    """
    callers = [
        hit
        for hit in attribute_reads("may_respond")
        if not hit.startswith("engine/priority.py")
    ]
    assert callers == []
    source = source_of("engine/priority.py")
    assert "PRIORITY_STATE_STALE" in source
    assert "def _staleness" in source
    #: 그 자리는 ``missing_rule`` 과 ``notes`` 를 **둘 다** 채운다 — 두 칸이
    #: 실제로 내용을 갖는 드문 예이고, 그래서 손실을 이야기할 때 쓰인다.
    index = source.index("PRIORITY_STATE_STALE")
    window = source[index : index + 400]
    assert "missing_rule=" in window
    assert "notes=" in window


# ======================================================================
# 14 ~ 18 — 소비자 · 역사 · 직렬화
# ======================================================================


def test_20_nobody_in_production_reads_the_withheld_list():
    """
    **§14 · Q5 · §20-1: ``withheld`` 를 읽는 production 소비자가 0곳이다.**

    "``code`` 가 없다" 가 문제가 되려면 그것을 필요로 하는 쪽이 있어야 한다.
    측정 결과 **읽는 쪽이 없다** — 정책도, 탐색도, 평가도, 기록도.
    """
    readers = [
        hit
        for hit in attribute_reads("withheld")
        if not hit.startswith("engine/duel.py")
    ]
    assert readers == []


def test_21_only_one_consumer_reads_the_step_code():
    """
    **§14 · Q13: ``DuelStep.code`` 를 읽는 자리는 시뮬레이터 하나다.**

    그리고 그 자리가 쓰는 것은 "모름인가" 하나이며, 그 답은 Phase 3-E-40 의
    policy 에서 온다.
    """
    readers = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "code"
                and "step" in ast.unparse(node.value)
            ):
                readers.append(f"{rel}:{node.lineno}")
    outside = [hit for hit in readers if not hit.startswith("engine/duel.py")]
    assert outside, "시뮬레이터가 읽는 자리는 있어야 한다"
    assert all(hit.startswith("agent/simulation.py:") for hit in outside), outside


def test_22_the_history_entry_keeps_accepted_and_reason_but_not_the_code():
    """
    **§13 · §24-20: 역사(history)는 코드를 적지 않는다.**

    ``TranscriptEntry`` 의 아홉 칸에 ``code`` 가 없다. 그리고 재현 동일성을
    재는 ``canonical_state()`` 는 **받아들여진 걸음의 (자리, 행위)** 와 결과만
    본다 — 이유도 코드도 보지 않는다.
    """
    from agent.runner import Transcript, TranscriptEntry

    fields = {f.name for f in dataclasses.fields(TranscriptEntry)}
    assert fields == {
        "index",
        "seat",
        "policy",
        "action",
        "accepted",
        "reason",
        "turn_number",
        "phase",
        "legal_count",
    }
    assert "code" not in fields

    body = ast.unparse(
        next(
            node
            for node in ast.walk(ast.parse(source_of("agent/runner.py")))
            if isinstance(node, ast.FunctionDef) and node.name == "canonical_state"
        )
    )
    assert "entry.accepted" in body
    assert "canonical_state" in body
    assert "code" not in body
    assert hasattr(Transcript, "canonical_state")


def test_23_a_refusal_halts_the_run_because_it_is_a_policy_defect():
    """
    **§13 · §20-5: 거절은 역사가 아니라 정책의 결함으로 다룬다.**

    ``DuelRunner.run`` 은 거절이 나오면 **멈춘다.** ``Transcript.refusals`` 의
    설명이 그것을 "듀얼의 사실이 아니라 정책의 결함" 이라고 적는다. 그래서
    정상적인 기록에는 거절된 걸음이 **없다** — 거절 코드를 역사에 보존해야
    한다는 요구가 계약에서 나오지 않는 까닭이다.
    """
    source = source_of("agent/runner.py")
    assert "듀얼의 사실이 아니라" in source
    assert "**거절이 나오면 멈춘다.**" in source
    body = ast.unparse(
        next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
    )
    assert "not entry.accepted" in body
    assert "break" in body


def test_24_none_of_these_types_is_serialised_anywhere():
    """
    **§17: 직렬화 · 저장되는 재현 형식이 **없다**.**

    ``DuelStep`` · ``WithheldAction`` · ``LegalActions`` · ``TranscriptEntry``
    에 ``to_dict`` 도 ``from_dict`` 도 없다. 그래서 "필드를 더하면 예전 재현을
    읽을 수 있는가" 라는 질문에 **대상이 없다.**
    """
    from agent.arena import DecisionRecord, MatchResult
    from agent.runner import Transcript, TranscriptEntry

    for cls in (DuelStep, WithheldAction, LegalActions, TranscriptEntry, DecisionRecord):
        for method in ("to_dict", "from_dict", "to_json"):
            assert not hasattr(cls, method), (cls.__name__, method)
    #: 비교용 요약만 있다 — 그것도 코드를 보지 않는다.
    assert hasattr(Transcript, "canonical_state")
    assert hasattr(MatchResult, "canonical_state")


def test_25_the_ai_consumers_do_not_depend_on_any_validation_field():
    """
    **§14 · 필수 표 3: 정책들은 validation 칸을 읽지 않는다.**

    ``RuleBasedPolicy`` · ``RandomPolicy`` · ``FirstLegalPolicy`` ·
    ``SearchPolicy`` · ``Evaluation`` 가 ``DuelStep`` 을 import 하지도 않는다.
    """
    for rel in (
        "agent/heuristic.py",
        "agent/policy.py",
        "agent/search.py",
        "agent/evaluation.py",
    ):
        source = source_of(rel)
        assert "DuelStep" not in source, rel
        assert "WithheldAction" not in source, rel
    #: 시뮬레이터만 ``DuelStep`` 을 안다.
    assert "DuelStep" in source_of("agent/simulation.py")


# ======================================================================
# 19 ~ 24 — 경계 · 불변식
# ======================================================================


def test_26_the_withheld_entry_names_a_kind_not_a_card():
    """
    **§13 · Q11: 보류가 가려진 정보를 흘리지 않는다.**

    보류 항목은 **종류**만 적고 어느 카드인지 적지 않는다. 후보별로 코드를
    남기려면 instance 를 가리켜야 하고, 그러면 ``HIDDEN_CARD`` 처럼 **가려진
    것을 가리키는** 판정에서 식별자가 함께 새어 나갈 길이 열린다.

    "정보 보존이 가려진 정보 누출이 되어서는 안 된다" 는 이 Phase 의
    invariant 를 자료형이 **구조적으로** 지키고 있다.
    """
    fields = {f.name for f in dataclasses.fields(WithheldAction)}
    assert "source" not in fields
    assert "action" not in fields
    assert "instance_id" not in fields
    assert fields == {"kind", "reason", "missing"}


@requires_official_db
def test_27_the_withheld_list_is_per_seat_and_reads_only_that_seats_hand(repository):
    """
    **§13 · Q11: 보류 훑기가 자기 패만 본다.**

    ``_withheld_board_actions`` 는 ``state.player(seat).hand`` 를 돈다 —
    상대 패를 보지 않는다.
    """
    body = ast.unparse(
        next(
            node
            for node in ast.walk(ast.parse(source_of("engine/duel.py")))
            if isinstance(node, ast.FunctionDef)
            and node.name == "_withheld_board_actions"
        )
    )
    assert "self.state.player(seat).hand" in body
    assert "1 - seat" not in body

    duel = started(repository, phase=Phase.MAIN1)
    mine = duel.legal_actions(0)
    theirs = duel.legal_actions(1)
    assert mine.seat == 0 and theirs.seat == 1


@requires_official_db
def test_28_reading_legal_actions_and_applying_never_moves_the_board(repository):
    """**§16 · §33-12~15: ``state_hash`` · RNG · clone 불변.**"""
    duel = started(repository)
    before_hash = duel.state.state_hash()
    before_draws = duel.state.randomness.draws

    for seat in (0, 1):
        duel.legal_actions(seat)
    assert duel.state.state_hash() == before_hash
    assert duel.state.randomness.draws == before_draws

    #: 사본은 독립이다 — 사본을 바꿔도 원본이 그대로다.
    clone = duel.state.clone()
    clone.player(0).hand.pop()
    assert duel.state.state_hash() == before_hash


def test_29_the_validation_vocabulary_is_unchanged():
    """**§33-1 ~ 7: 어휘가 그대로다.** 이 Phase 는 AUDIT-ONLY 다."""
    from agent.simulation import SimulationStatus

    assert len(ValidationCode) == 48
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5
    assert len(unknown_codes()) == 7
    #: 3-E-38 의 두 구분이 그대로다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_30_unknown_is_still_neither_false_nor_invalid_nor_a_loss():
    """**§33-2 ~ 5.**"""
    unknown = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "모른다")
    assert unknown.permits_execution is False
    assert unknown.is_structural_failure is False
    with pytest.raises(TypeError):
        bool(unknown)
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    #: 패배를 만드는 칸이 없다.
    assert not hasattr(DuelStep, "winner")
    assert "result" in {f.name for f in dataclasses.fields(DuelStep)}


def test_31_this_phase_changed_no_production_file():
    """
    **§21 · §26: AUDIT-ONLY — 네 자료형이 3-E-40 이 남긴 모양 그대로다.**
    """
    assert len({f.name for f in dataclasses.fields(DuelStep)}) == 5
    assert len({f.name for f in dataclasses.fields(WithheldAction)}) == 3
    assert len({f.name for f in dataclasses.fields(LegalActions)}) == 3
    assert len({f.name for f in dataclasses.fields(ValidationResult)}) == 5
    #: policy 는 3-E-40 의 것을 그대로 쓴다 — 새로 만들지 않았다.
    assert len(CODE_VALIDITY) == 48
    assert "CODE_VALIDITY" in source_of("engine/validation.py")
    assert "CODE_VALIDITY" not in source_of("engine/duel.py")


def test_32_adding_validity_to_the_step_would_recreate_the_copy_3e40_removed():
    """
    **Q1 · Q16 의 근거를 테스트로 적어 둔다.**

    ``DuelStep`` 에 ``validity`` 를 더하면 "어느 코드가 어느 판정인가" 를 적는
    자리가 **둘**이 된다 — 하나는 ``CODE_VALIDITY``, 하나는 걸음을 만드는 17개
    자리. 그 둘은 어긋날 수 있고, **어긋나는 것이 3-E-39 가 찾은 문제였다.**

    지금은 어긋날 수 없다: 걸음이 코드만 들고, 판정은 거기서 **파생**된다.
    """
    #: 파생이 전단사는 아니다 — 여러 코드가 같은 판정을 가리킨다.
    from engine.validation import codes_declaring

    assert len(codes_declaring(ActionValidity.INVALID)) == 39
    assert len(codes_declaring(ActionValidity.UNKNOWN)) == 7
    assert len(codes_declaring(ActionValidity.VALID)) == 1
    assert len(codes_declaring(None)) == 1

    #: 그래서 코드 → 판정은 가능하고 판정 → 코드는 불가능하다. ``DuelStep`` 이
    #: 들어야 하는 것은 **더 많은 정보를 가진 쪽**이고, 그것이 코드다.
    assert CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    assert CODE_VALIDITY[ValidationCode.ZONE_FULL] is ActionValidity.INVALID
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.ZONE_FULL
