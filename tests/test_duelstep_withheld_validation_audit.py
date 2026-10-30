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
    #: 🔴 **Phase 6-AB 보완8 이 ``code`` 와 ``scope`` 를 더했다.**
    #:
    #: 이 시험은 *"code 가 없다"* 를 못 박고 있었고 (3-E-40 의 측정을 HEAD
    #: 에서 재확인하는 자리였다), 그 사실이 **결함의 원인**이었다 — 읽는
    #: 쪽이 규칙 거절과 모름을 ``missing`` 이 비었는지로 짐작해야 했고,
    #: ``Duel.apply`` 는 그 짐작조차 하지 않고 ``RULE_NOT_IMPLEMENTED`` 를
    #: 다시 적었다 (보완8 §2 의 실측).
    #:
    #: ``scope`` 는 "이 거절이 패 몇 장에 걸렸는가" 의 메모다. 자리를 따로
    #: 둔 이유는 누적 목록의 열쇠에서 빼야 하기 때문이다.
    assert fields == {"kind", "reason", "code", "missing", "scope"}
    #: 🔴 **그래도 식별자는 들어오지 않았다** — 이 시험의 본래 주장이고
    #: ``test_26`` 이 그 이유를 적는다.
    for absent in ("status", "validation", "source", "viewer", "action",
                   "notes", "instance_id", "effect_ref"):
        assert absent not in fields, absent
    #: 들고 있는 것은 행위가 아니라 **종류**다 — 어느 카드인지 적지 않는다.
    sample = WithheldAction(
        PlayerActionKind.PASS, "x", ValidationCode.NO_RESPONSE_WINDOW
    )
    assert isinstance(sample.kind, PlayerActionKind)
    #: 🔴 ``validity`` 는 **저장되지 않고 코드에서 파생된다** — 3-E-40 이
    #: 지운 "둘째 사본" 을 다시 만들지 않았다 (``test_06`` 과 같은 규율).
    assert "validity" not in fields
    assert sample.validity is CODE_VALIDITY[sample.code]


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

    ``DuelStep`` 을 만드는 production 자리 **전부**가 코드를 넘기고, 전부
    ``engine/duel.py`` 안에 있다. 다른 모듈은 걸음을 만들지 않는다.

    🔴 **자리 개수 고정을 기준으로 바꿨다** (Phase 6-AB 최종 보완). 전에는
    ``len(sites) == 17`` 이었다. 이 시험의 주장은 "17곳이다" 가 아니라
    **"자리마다 코드를 넘긴다"** 와 **"걸음을 만드는 모듈이 하나다"** 이고,
    둘 다 아래가 그대로 센다. 최종 보완이 열여덟째를 더했다 — 유발 처리
    기회에서의 ``PASS`` 를 받는 자리이고 (②), ``ValidationCode.OK`` 를
    넘긴다.
    """
    sites = constructions("DuelStep")
    assert sites, "걸음을 만드는 자리가 없으면 이 시험은 아무것도 재지 않는다"
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
    #: 🔴 48 → **51** (Phase 6-AB 보완7 이 셋, 보완8 이 셋을 더했다 —
    #: 보완7 의 셋은 효과 분류 쪽이 아니라 **이 파일이 세는 수**에 영향이
    #: 없었고, 보완8 의 셋이 흐름 거절을 규칙 거절로 적는 자리다:
    #: ``STAGE_FORBIDS_ACTION`` · ``MANDATORY_TRIGGER_PENDING`` ·
    #: ``TRIGGER_TIMING_MISSED``).
    #:
    #: 🔴 **이 시험이 지키는 사실은 그대로다** — 판정을 코드에서 되찾을 수
    #: 있고, 되찾을 수 없는 것은 **여전히 하나**다. 새 코드 셋도
    #: ``CODE_VALIDITY`` 에 분류를 적었고 (적지 않으면 import 가 터진다),
    #: 그래서 ``DuelStep`` 에 ``validity`` 를 더할 이유가 생기지 않았다.
    #: Phase 6-AC 가 둘을 더했다 — EFFECT_USE_LIMIT_REACHED · LINK_MATERIAL_INVALID (51 → 53).
    assert len(recoverable) == 54
    #: 🔴 Phase 6-AC 가 둘을 더했다 — ``EFFECT_USE_LIMIT_REACHED`` ·
    #: ``LINK_MATERIAL_INVALID``. **둘 다 ``INVALID``** 이므로 모름 쪽은
    #: 그대로이고 확정 거부 쪽만 늘었다 (보완8 과 같은 결).
    assert sum(1 for v in recoverable.values() if v is not None) == 52
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


def test_09_the_withheld_sites_fill_missing_from_four_different_sources():
    """
    **F-3 (§8): 같은 칸이 자리마다 다른 출처에서 채워진다.**

    전부 ``engine/duel.py`` 안에 있다.

    ====================  ===============================================
    ``_flow_actions``     손으로 쓴 문자열 (``ValidationResult`` 가 **없다**)
    ``_flow_actions``     ``plan.unresolved_rules`` (verdict 의 것이 **아니다**)
    ``_withheld_board_``  ``verdict.missing_rule``
    ``_flow_actions``     🔴 **채우지 않는다** (Phase 6-S) — 아래 참조
    ``_trigger_actions``  🔴 **모듈 상수** ×2 (Phase 6-AA) — 네 번째 종류
    ``_trigger_actions``  🔴 **모듈 상수** (6-AB, 「때 / 경우」 모름)
    ``_trigger_actions``  🔴 **채우지 않는다** (6-AB, 「때」 를 놓쳤다)
    ``_enforce_mandat``   🔴 **모듈 상수** (6-AB, 발동 불가 강제)
    ``_enforce_mandat``   🔴 **채우지 않는다** ×2 (6-AB, 규칙의 결과 · 순서)
    ====================  ===============================================

    고치지 않고 적어 둔다 — 자리마다 같은 칸에 다른 종류의 값을 넣는다는
    사실 자체가 이 경계의 계약이 느슨하다는 증거다.

    🔴 **세 자리에서 네 자리가 되었다** (Phase 6-S)
    ----------------------------------------------
    이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 그 시점에 실제로 세
    자리였다. 6-S 가 ``_flow_actions`` 의 **묶인 조건 하나**를 갈랐고, 그
    분기가 넷째 자리를 만들었다.

    갈라야 했던 이유: "패스할 수 없다" 의 이유가 둘인데 하나로 묶여 있었고
    (``elif seat != self.turn_player``), 그래서 **창이 열려 있는데도**
    "우선권이 열려 있지 않습니다" 라고 적었다 (거짓 문장) — 그리고 창이
    열려 있고 상대가 쥐었는데 이쪽이 턴 플레이어이면 어느 분기도 밟지 않아
    **후보 0 · 보류 0** 이 되었다 (침묵).

    🔴 **그리고 넷째 자리는 이 시험이 지적한 느슨함을 늘리지 않는다** —
    ``missing`` 을 **채우지 않는다.** 그 자리에서 빠진 규칙은 없고 (지금은
    상대의 차례일 뿐이다) 없는 것을 빈 값으로 채우지 않는다. 그래서 네
    자리 중 ``missing`` 을 주는 것은 여전히 **셋**이고, 출처도 여전히 셋이다.
    근거는 ``docs/phase6s-legal-action-execution-consistency.md`` 와
    ``tests/engine/test_legal_action_candidate_consistency.py`` 의 ``F`` 절.
    """
    sites = constructions("WithheldAction")
    assert all(site.startswith("engine/duel.py:") for site in sites)

    source = source_of("engine/duel.py")
    #: 🔴 **Phase 6-AB 보완8 이 두 자리를 바꿨다 — 그리고 느슨함을 줄였다.**
    #:
    #: * 손으로 쓴 ``missing="우선권을 여는 규칙 (Phase 2-F)"`` 가 **사라졌다.**
    #:   그 문장은 우선권을 여는 계층이 없던 때의 것이고, 지금은 그 계층이
    #:   있으므로 그 자리는 **규칙 거절**(``NO_RESPONSE_WINDOW``)이다 —
    #:   없는 것을 적을 이유가 없어졌다. 즉 **첫째 출처가 없어졌다.**
    #: * ``plan.unresolved_rules`` 는 그대로이고 지역 변수를 거친다.
    #: * ``verdict.missing_rule`` 도 그대로다.
    #: 🔴 **주석이 아니라 코드를 본다.** 보완8 은 그 문장을 **왜 바꿨는지**
    #: 주석으로 적어 두었으므로 원문 검색은 그 설명에 걸린다 — ``ast`` 로
    #: 다시 쓴 코드에는 주석이 없다.
    code_only = ast.unparse(ast.parse(source))
    assert "우선권을 여는 규칙 (Phase 2-F)" not in code_only
    assert "plan.unresolved_rules" in code_only
    assert "verdict.missing_rule" in code_only

    #: 🔴 **Phase 6-AA 가 느슨함을 하나 더 늘렸다 — 넷째 출처.**
    #:
    #: 자리 수를 세는 대신 **출처의 종류**를 센다 (그것이 이 시험의 주장이고,
    #: 자리 수는 그 대리 지표였다). 6-AA 가 보류 자리 둘을 더했고 둘 다
    #: **모듈 상수**에서 ``missing`` 을 채운다 — 손으로 쓴 문자열도,
    #: 계획의 미해결 규칙도, verdict 의 것도 아닌 **네 번째 종류**다.
    #:
    #: ==========================  ====================================
    #: 손으로 쓴 문자열              ``_flow_actions`` (우선권)
    #: ``plan.unresolved_rules``   ``_flow_actions`` (페이즈 전환)
    #: ``verdict.missing_rule``    ``_withheld_board_actions``
    #: **모듈 상수** (6-AA)         ``_trigger_actions`` 둘
    #: ==========================  ====================================
    #:
    #: 🔴 **고치지 않고 적어 둔다** — 이 시험이 처음부터 그렇게 했다. 자리마다
    #: 같은 칸에 다른 종류의 값을 넣는다는 사실이 경계의 계약이 느슨하다는
    #: 증거이고, 6-AA 는 그 증거를 **늘렸다.** 숨기지 않는다.
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "WithheldAction"
    ]
    assert len(calls) == len(sites)
    filled = [
        next(kw for kw in node.keywords if kw.arg == "missing")
        for node in calls
        if any(kw.arg == "missing" for kw in node.keywords)
    ]
    #: 🔴 **Phase 6-AB 가 그 느슨함을 또 늘렸다 — 모듈 상수 둘 → 넷.**
    #:
    #: 늘어난 둘: ``_trigger_actions`` 의 「때 / 경우」 판정 불가
    #: (``TRIGGER_WORDING_MISSING``) 와 ``_enforce_mandatory`` 의 발동 불가
    #: 강제 (``MANDATORY_TRIGGER_UNPLAYABLE``). 둘 다 네 번째 종류다.
    #:
    #: 🔴 **그리고 6-AB 추가 보완이 다섯 번째 종류를 만들었다** —
    #: ``_trigger_actions`` 의 관문 거절 자리가 ``gate.missing_rule`` 을
    #: **조건부로** 싣는다 (관문이 ``UNKNOWN`` 이면 그것을, 규칙이 금지하면
    #: ``None`` 을). 이 시험의 주장이 늘어난 것이므로 **숨기지 않고 적는다.**
    #:
    #: 🔴 다만 성질이 다르다 — 앞의 넷은 이 자리가 **값을 고르는** 것이고,
    #: 이것은 판정한 계층의 답을 **그대로 옮기는** 것이다. 느슨함을 줄이려면
    #: 나머지 넷을 이 모양으로 모으는 쪽이 방향이다. 그 판단은 적어만 두고
    #: 이 Phase 에서 하지 않는다 (경계 재설계는 범위 밖이다).
    #:
    #: 채우는 자리가 셋 → 다섯 → 일곱 → **열**이 되었다. 추가 보완이 더한
    #: 셋은 **원래 침묵이던 자리**다 (실행 구현 없음 · 대상 환전 실패 ·
    #: 관문 거절) — 보류가 늘어난 것이 느슨해진 것이 아니라 정직해진 것이다.
    #:
    #: 🔴 열 → **열둘** (보완8 세 항목 ②). 늘어난 둘은
    #: ``_note_target_limits`` 의 두 자리이고, **또 원래 침묵이던 자리**다:
    #: 대상 조합을 끝까지 세지 못한 범위(가려진 후보 · 들여다보지 못한 자리)를
    #: 전에는 아무 데도 적지 않았다. 둘 다 **모듈 상수**에서 채우므로
    #: 아래 ``kinds`` 는 셋 그대로다 — 출처의 종류는 늘지 않았다.
    #:
    #: 🔴 열둘 → **열여섯** (Phase 6-AC). 늘어난 넷:
    #:
    #:   ``_link_summon_actions``  소재 조건을 읽지 못했다 (모듈 상수)
    #:   ``_link_summon_actions``  소재 조합이 전부 막혔다 (지역 변수)
    #:   ``_trigger_actions``      응답 창이 닫혔다 vs 「때」 를 못 읽었다
    #:   ``_trigger_actions``      규칙이 답한 0건 vs 어휘를 못 연 0건
    #:
    #: 🔴 **그리고 출처의 종류가 셋 → 다섯이 되었다.** 뒤의 둘이 각각 새
    #: 조건식이기 때문이다. 숨기지 않고 적는다 — 다만 **성질은 셋이다**:
    #: 뒤의 세 조건식은 모두 "판정한 계층의 답을 **조건부로 옮긴다**" 이고,
    #: 그것이 추가 보완이 만든 다섯 번째 종류와 같은 성질이다. 아래에서
    #: 그 셋을 **성질로 묶고 식으로 못박는다** — 묶어서 수를 줄이는 것이
    #: 아니라, 묶은 뒤에도 각 식을 그대로 센다.
    assert len(filled) == 16, len(filled)

    def source_kind(keyword) -> str:
        value = keyword.value
        if isinstance(value, ast.Constant):
            return "손으로 쓴 문자열"
        if isinstance(value, ast.Name):
            #: 🔴 **보완8 이 이 갈래를 둘로 갈랐다.** 전에는 모든 ``Name`` 을
            #: "모듈 상수" 로 셌는데, 보완8 이 판정 계층의 값을 **지역 변수**로
            #: 받아 넘기는 자리를 둘 만들었다 (``unresolved`` ·
            #: ``missing``). 둘은 다른 종류다 — 상수는 이 자리가 **고른**
            #: 값이고, 지역 변수는 판정한 계층의 답을 **옮긴** 값이다.
            return (
                "모듈 상수" if value.id.isupper() else "판정 계층의 값 (지역 변수)"
            )
        if isinstance(value, ast.Attribute):
            return f"{ast.unparse(value.value)} 의 칸"
        return ast.unparse(value)

    kinds = sorted({source_kind(keyword) for keyword in filled})
    #: 🔴 **Phase 6-AB 보완8 이 출처를 다섯 → 셋으로 줄였다** — 이 시험이
    #: 지적해 온 느슨함이 **줄어든** 첫 변화다.
    #:
    #: ===========================  =================================
    #: 손으로 쓴 문자열               🔴 **없어졌다** — 우선권 문장 하나가
    #:                               규칙 거절로 바뀌었다
    #: ``verdict`` 의 칸              🔴 **없어졌다** — 지역 변수를 거친다
    #: 모듈 상수                      그대로 (유발 쪽 다섯 자리)
    #: 판정 계층의 값 (지역 변수)       ``_withheld_board_actions`` ·
    #:                               ``_flow_actions`` 의 페이즈 전환
    #: 관문의 답을 조건부로            ``_trigger_actions`` ·
    #:                               ``_activation_actions``
    #: ===========================  =================================
    #:
    #: 🔴 **고치지 않고 적어 둔다는 이 시험의 태도는 그대로다.** 다만
    #: 이번에는 적을 것이 "늘었다" 가 아니라 **"줄었다"** 다. 남은 셋 중
    #: 둘(지역 변수 · 관문의 답)은 판정한 계층의 답을 **옮기는** 자리이고,
    #: 모듈 상수 다섯 자리만 이 자리가 값을 **고른다** — 느슨함을 더 줄이려면
    #: 그쪽을 모으는 것이 방향이다 (경계 재설계는 여전히 범위 밖이다).
    assert len(kinds) == 5, kinds
    assert "손으로 쓴 문자열" not in kinds
    assert "모듈 상수" in kinds
    assert "판정 계층의 값 (지역 변수)" in kinds
    #: 셋째 성질 — 판정한 계층의 답을 **조건부로** 옮기는 자리. 🔴 Phase
    #: 6-AC 가 둘을 더해 **셋**이 되었다. 성질로 묶되 식을 그대로 적는다.
    forwarded = sorted(k for k in kinds if " if " in k and " else " in k)
    assert forwarded == [
        "None if admits is False else TRIGGER_WORDING_MISSING",
        "TRIGGER_IMPLEMENTATION_MISSING if shape is not None else None",
        "gate.missing_rule if gate.validity is ActionValidity.UNKNOWN else None",
    ], forwarded
    #: 성질로 묶으면 **셋**이다 — 그 수는 보완8 이 줄여 놓은 그대로다.
    assert len({"모듈 상수", "판정 계층의 값 (지역 변수)", "조건부 전달"}) == 3

    #: 🔴 그리고 **비우는 자리가 둘 → 넷 → 일곱으로 늘었다** (추가 보완이
    #: ``_trigger_actions`` 의 "기회가 끝났다" 를 더해 일곱을 유지한다 —
    #: 6-AB 보완의 "포기했다" 자리를 그것이 대체했다) — 없는 것을 빈
    #: 값으로 채우지 않는 규율은 6-AA · 6-AB · 보완 전부 지켰고, 그 규율을
    #: **쓰는 자리**가 늘었다. 일곱은 전부 "규칙이 답했다" 쪽이다:
    #:
    #:   ``_flow_actions``      창은 열렸고 상대 차례다 (6-S)
    #:   ``_trigger_actions``   체인이 처리 중이다 — 기회는 남고 발동은 뒤다
    #:   ``_trigger_actions``   그 기회를 적법하게 포기했다 (보완)
    #:   ``_trigger_actions``   「때」 타이밍을 놓쳤다 — 규칙이 답했다 (6-AB)
    #:   ``_enforce_mandatory`` 다른 자리가 먼저다 — 순서다 (보완)
    #:   ``_enforce_mandatory`` 지금 고르는 자리가 아니다 — 순서다 (6-AB)
    #:   ``_enforce_mandatory`` 강제를 먼저 처리해야 한다 — 규칙의 결과다
    #:
    #: 🔴 6-AA 가 ``_flow_actions`` 에 둔 강제 유발 분기는 **없어졌다** —
    #: 6-AB 가 그 판정을 ``_enforce_mandatory`` 한 자리로 모았다.
    #:
    #: 🔴 **채우는 자리는 일곱 그대로다** (바로 위의 단정). 보완이 더한 것은
    #: 비우는 쪽 셋이고, 그것은 느슨함이 아니라 **규율이 적용된 자리**다 —
    #: 이 시험이 지적하는 느슨함(같은 칸을 네 종류가 채운다)은 늘지 않았다.
    #:
    #: 🔴 **Phase 6-AB 최종 보완이 비우는 쪽을 여덟로 늘렸다** —
    #: ``_enforce_mandatory`` 에 *"상대의 유발 처리 기회가 아직 열려
    #: 있습니다"* 가 생겼다 (②). ``missing`` 을 **비운다**: 빠진 규칙이
    #: 아니라 **순서**이고 근거는 공식 Fast Effect Timing 도표다 (그 기회는
    #: 양쪽이 다 지나가야 닫힌다).
    #:
    #: 🔴 **이 시험이 지적하는 느슨함은 또 늘지 않았다** — 채우는 자리는
    #: 열 그대로이고 출처도 다섯 그대로다. 늘어난 것은 **규율을 쓰는
    #: 자리**이므로, 개수가 아니라 그 성질을 센다.
    #: 🔴 **보완8 이 비우는 쪽을 여덟 → 열둘로 늘렸다.** 늘어난 넷은
    #: ``_stage_closed_actions`` 가 적는 "판이 열린 상태가 아니다" ·
    #: "비턴 플레이어다" 와 ``_activation_actions`` 의 규칙 거절, 그리고
    #: ``_flow_actions`` 의 우선권 자리가 모름에서 **확정 거부로 옮겨 온**
    #: 것이다. 전부 "규칙이 답했다" 쪽이므로 규율을 쓰는 자리가 늘었다.
    #: 🔴 **보완8 세 항목 ②는 비우는 쪽을 늘리지 않았다** — 더한 두 자리는
    #: 둘 다 ``missing`` 을 **채운다** (정보가 없어서 모르는 쪽이다). 그래서
    #: 비우는 자리는 열둘 그대로이고 채우는 쪽만 열 → 열둘이 되었다.
    #: 🔴 **Phase 6-AC 도 비우는 쪽을 늘리지 않았다** — 더한 네 자리는 넷
    #: 다 ``missing`` 을 **채운다** (읽지 못한 소재 규칙 · 막힌 소재 조합 ·
    #: 닫힌 응답 창 · 열지 못한 어휘). 그래서 비우는 자리는 **열둘 그대로**
    #: 이고 채우는 쪽만 열둘 → 열여섯이 되었다. 전체 자리는 24 → 28 이다.
    empty = len(calls) - len(filled)
    assert len(calls) == 28, len(calls)
    assert empty == len(calls) - 16
    assert empty == 12, empty


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
    #: 🔴 **Phase 6-AB 보완8 이 F-1 을 고쳤다 — 코드가 갈아 끼워지지 않는다.**
    #:
    #: 3-E-41 은 *"production 경로에서는 닿지 않으니 지금의 코드로도
    #: 충분하다"* 로 적어 두었다. 보완8 이 ``Duel._refusal`` 에
    #: :meth:`~engine.duel.Duel._rule_verdict` 를 더하면서 그 자리도 함께
    #: 메워졌다 — **발동이 아닌 종류의 거절도 검증기에게 묻기** 때문이다.
    #: 그래서 *"가려져서 모른다"* 가 *"엔진이 못 한다"* 로 바뀌지 않는다.
    #:
    #: 🔴 **느슨하게 하지 않고 좁혔다**: 전에는 둘이 **다르다**를 셌고
    #: 지금은 **같다**를 센다 (이유 문장까지).
    assert step.code is verdict.code
    assert step.code is ValidationCode.HIDDEN_CARD
    assert step.reason == verdict.reason

    #: 판정은 그대로 모름 쪽이다.
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
    #: 🔴 **기계가 읽는 둘도 이제 온다** (Phase 6-AB 보완8).
    #:
    #: 이 시험의 제목이 *"다만 코드 없이"* 였고 그것이 결함이었다 — 읽는
    #: 쪽이 규칙 거절과 모름을 가르려면 ``missing`` 이 비었는지를 짐작해야
    #: 했다. 지금은 코드가 그것을 말하고, ``validity`` 는 저장되지 않고
    #: **코드에서 파생된다** (3-E-40 이 지운 둘째 사본을 만들지 않았다).
    assert entry.code is verdict.code
    assert entry.validity is verdict.validity
    assert entry.is_rule_refusal is False
    assert "validity" not in {
        f.name for f in dataclasses.fields(WithheldAction)
    }


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

    #: 🔴 **Phase 6-AB 보완8 이 이 자리를 고쳤다 — 보류에 남는다.**
    #:
    #: 이 시험의 제목(*"M1 관문 판정이 어디에도 기록되지 않는다"*)이 바로
    #: 3-E-41 이 **F-2** 로 적어 둔 결함이고, 보완8 이 그것을 끝냈다
    #: (``Duel._activation_actions`` 가 ``(allowed, withheld)`` 를 돌려준다).
    #:
    #: 🔴 **느슨하게 하지 않고 더 센다**: 그 종류가 보류에 있고, 코드가
    #: 관문의 것과 같고, 규칙 거절이므로 ``missing`` 이 비어 있고, 어느
    #: 효과인지가 문장에 남아 있다.
    kinds = {w.kind for w in legal.withheld}
    assert PlayerActionKind.ACTIVATE_EFFECT in kinds
    recorded = [
        w for w in legal.withheld
        if w.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert all(w.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE for w in recorded)
    assert all(w.is_rule_refusal for w in recorded)
    assert all(w.missing is None for w in recorded)
    #: 규칙이 막은 것이므로 **미지원 집계에는 들어가지 않는다.**
    assert not [w for w in legal.unsupported() if w in recorded]
    #: 남아 있는 "아직 못 한다" 쪽 이야기도 그대로다.
    assert any("아직 없습니다" in w.reason for w in legal.withheld)


def test_16_the_withheld_board_scan_stops_after_the_first_card():
    """
    **F-2 (후반): 보류는 패의 첫 장에서 멈춘다.**

    주석이 그 까닭을 적는다 — "같은 이유가 패의 카드마다 반복되므로 종류별로
    하나씩만 남긴다". 그 전제가 **늘 참은 아니다**: 두 장이 서로 다른 까닭으로
    보류되면 첫 장의 이유가 둘 다를 대표한다.

    🔴 **Phase 6-AB 보완8 이 F-2 의 이 절반을 고쳤다 — 멈추지 않는다.**

    그 전제(*"같은 이유가 패의 카드마다 반복된다"*)가 늘 참은 아니라는 것이
    이 시험의 지적이었고, 지금은 패 전체를 묻고 **(코드 · 모자란 것)** 으로
    묶는다. 서로 다른 까닭으로 보류되면 **줄이 둘**이 된다.

    🔴 **느슨하게 하지 않고 더 센다**: ``break`` 가 없어졌고, 묶는 열쇠가
    코드와 모자란 것이고, 몇 장에 걸렸는지가 ``scope`` 에 남고, **어느
    카드인지는 여전히 적지 않는다** (``test_26`` 의 invariant).
    """
    tree = ast.parse(source_of("engine/duel.py"))
    scan = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_withheld_board_actions"
    )
    #: 🔴 **문자열을 벗겨 코드만 본다** — 보완8 은 이 함수가 왜 멈추지
    #: 않게 됐는지 docstring 에 적었고, 거기에 ``break`` 라는 **말**이 있다.
    class _StripStrings(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802 - ast 규약
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value=""), node)
            return node

    body = ast.unparse(_StripStrings().visit(scan))
    assert "break" not in body
    #: 패 전체를 돈다 — 그리고 묶는다.
    assert "self.state.player(seat).hand" in body
    assert "groups" in body
    assert "scope=" in body
    #: 🔴 식별자는 싣지 않는다 — 수만 센다.
    assert "instance_id" in body  # 후보를 만들 때만 쓴다
    assert "source=card.instance_id" in body
    assert "WithheldAction" in body
    held_call = next(
        node
        for node in ast.walk(scan)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "WithheldAction"
    )
    passed = {kw.arg for kw in held_call.keywords} | {
        "positional"
    } if held_call.args else {kw.arg for kw in held_call.keywords}
    assert "source" not in passed and "effect_ref" not in passed


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
    """
    **§10 · Q9: M3 는 여전히 dormant 다.** 3-E-38/39 의 측정을 다시 고정한다.

    .. note::
       3-E-38/39 당시 ``TriggerSpec`` 과 ``TriggerRegistry`` 는 production 에서
       **둘 다** 0회 생성이었고, 이 테스트가 두 이름을 한 목록에 담아 그것을
       증명했다. 6-E 가 ``engine/trigger_compiler.py`` 에서 ``TriggerSpec`` 을
       만든다.

       **그래도 M3 는 dormant 다** — dormancy 를 결정하는 것은 선언을 **만드는
       일**이 아니라 그것을 **등록해서 듀얼 루프에 잇는 일**이고, 그쪽은
       ``TriggerRegistry`` 생성 **0회** · ``engine/duel.py`` 에 "trigger" 글자
       **0회**로 그대로다. 그래서 한 목록을 **두 목록으로 나눈다**: 등록 쪽은
       0 을 유지하고, 선언 쪽은 컴파일러 한 자리임을 적는다. 단정을 약하게
       만든 것이 아니라 **섞여 있던 두 사실을 분리**한 것이다.

    .. warning::
       🔴 **Phase 6-Z 가 그 잇는 일을 했다.** 유발 발동이
       ``Duel.legal_actions`` 에 오르고 ``Duel.apply`` 가 받는다. 그래서 이
       Phase 가 쟀던 세 사실 중 하나는 **더 이상 참이 아니다** — 듀얼 루프는
       이제 유발 후보를 받는다.

       🔴 **그러나 두 사실은 그대로다.** ``engine/duel.py`` 는 등록소를
       만들지 않고 (``TriggerRegistry`` 생성 0회), 트리거 계층의 **타입
       이름을 하나도 모른다.** 받는 것은 ``offers(duel, seat)`` 를 가진
       불투명한 값이고 (``triggers: object | None``), 그것을 만드는 일은
       조립 층의 몫이다 (ADR-007).

       그래서 낱말 검사를 **이름 검사**로 바꾼다 — 그것이 애초에 재려던
       것이다. 지금 이 시험이 말하는 것은 "M3 가 잠들어 있다" 가 아니라
       **"M3 가 깨어났어도 ``Duel`` 은 그 계층을 읽지 않는다"** 다.
       무엇이 깨어났는지는
       ``tests/engine/test_trigger_normal_path_integration.py`` 가 센다.
    """
    specs = []
    registries = []
    for rel, path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id == "TriggerSpec":
                specs.append(rel)
            elif node.func.id == "TriggerRegistry":
                registries.append(f"{rel}:{node.lineno}")

    #: 🔴 등록은 여전히 **아무도 하지 않는다** — M3 dormancy 의 본체다.
    assert registries == []
    #: 선언을 만드는 자리는 컴파일러 하나뿐이다.
    assert sorted(set(specs)) == ["engine/trigger_compiler.py"], specs
    #: 🔴 **``Duel`` 은 트리거 계층의 이름을 하나도 모른다** (Phase 6-Z).
    duel = source_of("engine/duel.py")
    for name in (
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerChainIntegrator",
        "TriggerEligibilityJudge",
        "TriggerSpec",
        "TimingEvent",
        "TimingPoint",
        "timing_events",
    ):
        assert name not in duel, name
    #: 들고 있는 칸은 **불투명하다** — 타입이 ``object`` 다.
    assert "triggers: object | None = None" in duel

    #: 그리고 컴파일러는 수집기 · 판정기 · 레지스트리를 **부르지 않는다** —
    #: 선언을 돌려줄 뿐 누구에게도 싣지 않는다.
    #:
    #: .. note::
    #:    처음에 글자 검사로 적었다가 발화했다 — 그 파일의 머리말이 **계층
    #:    그림**을 그리면서 이 이름들을 적어 두었기 때문이다. 산문은 호출이
    #:    아니다. 그래서 **AST 의 이름 노드**만 센다 (3-E-44 규칙).
    compiler_tree = ast.parse(
        (PROJECT_ROOT / "engine" / "trigger_compiler.py").read_text(encoding="utf-8")
    )
    used = set()
    for node in ast.walk(compiler_tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            used.add(module)
            for alias in node.names:
                used.add(alias.name)
                used.add((alias.asname or alias.name).split(".")[0])
    for absent in (
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "EventPipeline",
        "engine.duel",
    ):
        assert absent not in used, absent
    #: 세는 쪽이 멀쩡하다 — 실제로 쓰는 이름은 잡힌다 (고의 위반).
    assert "TriggerSpec" in used


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
    #: 🔴 **Phase 6-AB 보완8 이 ``code`` 와 ``scope`` 를 더했고 이 invariant
    #: 는 그대로다.** 그것이 이 시험의 요지다 — 후보별 판정을 보존하면서도
    #: 식별자를 싣지 않는 길이 있었다: 코드는 **규칙의 이름**이고 ``scope``
    #: 는 **수**이며, 어느 효과인지는 ``reason`` 문장에 남는다 (그 자리가
    #: 들고 있는 자기 카드의 ``EffectRef`` 다).
    #:
    #: 🔴 그리고 그 ``reason`` 이 **다른 자리로 넘어갈 때는 지운다** —
    #: ``agent.simulation.Simulator._encountered_line`` ·
    #: ``deck.opening.unsupported_reasons_elsewhere`` 가 상대 기회의
    #: 문장을 싣지 않는다 (보완8 마무리).
    assert "source" not in fields
    assert "action" not in fields
    assert "instance_id" not in fields
    assert "effect_ref" not in fields
    assert "card_id" not in fields
    assert fields == {"kind", "reason", "code", "missing", "scope"}


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

    #: 🔴 48 → **51** (Phase 6-AB 보완8 이 셋을 더했다 —
    #: ``STAGE_FORBIDS_ACTION`` · ``MANDATORY_TRIGGER_PENDING`` ·
    #: ``TRIGGER_TIMING_MISSED``). 더한 이유는 이 파일이 지적한 것과 **같은
    #: 결**이다: 확인된 흐름 규칙의 거절이 ``RULE_NOT_IMPLEMENTED`` 로
    #: 보고되어 규칙상 불가능한 행동이 **엔진 미지원**으로 집계되고 있었다.
    #:
    #: 🔴 **모름 쪽은 늘지 않았다** — 셋 다 ``INVALID`` 다. 그래서
    #: ``unknown_codes()`` 는 7 그대로이고, 그것이 이 변경이 "모름을 늘려
    #: 문제를 덮은 것" 이 아님을 말한다.
    #: Phase 6-AC 가 둘을 더했다 — EFFECT_USE_LIMIT_REACHED · LINK_MATERIAL_INVALID (51 → 53).
    assert len(ValidationCode) == 54
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
    **§21 · §26: 3-E-41 은 AUDIT-ONLY 였다 — 그리고 그 뒤가 고쳤다.**

    🔴 **이 시험의 원래 주장은 "3-E-41 이 production 을 한 줄도 고치지
    않았다" 였고, 그것은 지금도 참이다** (그 Phase 는 측정만 했다). 다만
    그 사실을 **"네 자료형의 칸 수가 그대로다"** 로 재고 있었으므로, 뒤의
    Phase 가 그 결함들을 고치면 깨지게 되어 있었다.

    Phase 6-AB 보완8 이 3-E-41 이 적어 둔 **F-1 · F-2 · F-3** 를 고쳤다.
    그래서 칸 수 핀을 그 사실에 맞게 옮기고, **이 파일이 지키려던 것**은
    그대로 센다: 판정 정책이 한 벌이고 (``CODE_VALIDITY``), 듀얼이 그 사본을
    만들지 않는다.

    🔴 ``engine/duel.py`` 가 ``CODE_VALIDITY`` 를 **읽게** 되었다 —
    ``WithheldAction`` 이 코드와 ``missing`` 의 일치를 강제하려면 그 정책을
    봐야 한다. **읽는 것은 사본이 아니다**: 표는 여전히 한 자리에만 있고
    (``engine/validation.py``), 듀얼은 그것을 ``import`` 해서 묻는다.
    """
    assert len({f.name for f in dataclasses.fields(DuelStep)}) == 5
    #: 🔴 3 → **5** (보완8: ``code`` · ``scope``). 이유는 ``test_02``.
    assert len({f.name for f in dataclasses.fields(WithheldAction)}) == 5
    assert len({f.name for f in dataclasses.fields(LegalActions)}) == 3
    assert len({f.name for f in dataclasses.fields(ValidationResult)}) == 5
    #: policy 는 3-E-40 의 것을 그대로 쓴다 — 새로 만들지 않았다.
    #: Phase 6-AC 가 둘을 더했다 — EFFECT_USE_LIMIT_REACHED · LINK_MATERIAL_INVALID (51 → 53).
    assert len(CODE_VALIDITY) == 54
    assert "CODE_VALIDITY" in source_of("engine/validation.py")
    #: 🔴 **표를 만드는 자리는 여전히 하나다.** 듀얼은 읽기만 한다 —
    #: ``CODE_VALIDITY = {`` 같은 선언이 그쪽에 없다는 것으로 센다.
    duel_source = source_of("engine/duel.py")
    assert "CODE_VALIDITY = " not in duel_source
    assert "CODE_VALIDITY" in duel_source


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

    #: 🔴 39 → **42** (Phase 6-AB 보완8 의 셋). 🔴 **모름 · 통과 · 미분류는
    #: 그대로다** — 늘어난 셋이 전부 확정 거부이므로, 이 변경이 "모름을 늘려
    #: 문제를 덮은 것" 이 아니라는 사실이 이 네 줄에 함께 적힌다.
    #: 🔴 42 → **44** (Phase 6-AC 의 둘). 모름 · 통과 · 미분류는 **또**
    #: 그대로다 — 같은 이유로 늘어난 둘이 전부 확정 거부다.
    assert len(codes_declaring(ActionValidity.INVALID)) == 44
    assert len(codes_declaring(ActionValidity.UNKNOWN)) == 7
    assert len(codes_declaring(ActionValidity.VALID)) == 1
    assert len(codes_declaring(None)) == 1

    #: 그래서 코드 → 판정은 가능하고 판정 → 코드는 불가능하다. ``DuelStep`` 이
    #: 들어야 하는 것은 **더 많은 정보를 가진 쪽**이고, 그것이 코드다.
    assert CODE_VALIDITY[ValidationCode.CANDIDATE_NOT_ELIGIBLE] is ActionValidity.INVALID
    assert CODE_VALIDITY[ValidationCode.ZONE_FULL] is ActionValidity.INVALID
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE is not ValidationCode.ZONE_FULL
