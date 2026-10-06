"""
검증 판정의 **공용 타입**.

Action 검증(:mod:`engine.action_validation`)과 비용 · 선택 검증
(:mod:`engine.cost`)이 같은 어휘로 답해야 한다. 한쪽에만 두면 다른 쪽이
그것을 가져오게 되고, 나중에 두 방향 의존이 생긴다.

세 가지 판정과 **안정적인 이유 코드**를 제공한다. 설명 문구는 사람이
읽으라고 있는 것이고, 코드는 기계가 분기하라고 있는 것이다.

UNKNOWN 은 허가가 아니다
------------------------
:attr:`ValidationResult.permits_execution` 은 ``VALID`` 일 때만 참이고,
:meth:`ValidationResult.__bool__` 은 예외를 던진다. ``if result:`` 한 줄로
"모른다" 가 "해도 된다" 가 되는 길을 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionValidity(str, Enum):
    """검증 결과 세 가지."""

    VALID = "valid"
    """처리해도 된다. **구조와 적법성이 모두 확인되었을 때만** 쓴다."""
    INVALID = "invalid"
    """구조 자체가 틀렸거나 규칙이 확실히 금지한다. 처리하지 않는다."""
    UNKNOWN = "unknown"
    """
    아직 판단할 수 없다. **거부가 아니다.**

    두 가지 원인이 있고 둘 다 정당하다 — 정보가 가려져 있거나, 판정할
    규칙이 아직 구현되지 않았다.
    """


class ValidationCode(str, Enum):
    """
    판정의 **안정적인 이유 코드.**

    문자열 설명은 사람이 읽으라고 있는 것이고, 코드는 기계가 분기하라고
    있는 것이다. 설명 문구를 다듬는다고 해서 부르는 쪽이 깨지면 안 된다.
    """

    OK = "ok"

    # --- 구조 (INVALID) ------------------------------------------------
    ACTOR_INVALID = "actor_invalid"
    SOURCE_REQUIRED = "source_required"
    SOURCE_FORBIDDEN = "source_forbidden"
    EFFECT_REF_REQUIRED = "effect_ref_required"
    EFFECT_REF_FORBIDDEN = "effect_ref_forbidden"
    EFFECT_REF_CARD_MISMATCH = "effect_ref_card_mismatch"
    EFFECT_REF_OUT_OF_RANGE = "effect_ref_out_of_range"
    PHASE_REQUIRED = "phase_required"
    PHASE_FORBIDDEN = "phase_forbidden"
    TARGET_COUNT_MISMATCH = "target_count_mismatch"
    TARGET_KIND_INVALID = "target_kind_invalid"

    # --- 판 위의 사실 (INVALID) -----------------------------------------
    DUEL_ALREADY_OVER = "duel_already_over"
    NOT_TURN_PLAYER = "not_turn_player"
    SOURCE_NOT_CONTROLLED = "source_not_controlled"
    SOURCE_WRONG_ZONE = "source_wrong_zone"
    SOURCE_WRONG_CARD_TYPE = "source_wrong_card_type"
    ZONE_FULL = "zone_full"
    WRONG_PHASE = "wrong_phase"
    SET_THIS_TURN = "set_this_turn"
    """
    **세트한 그 턴**에 발동하려 했다 (Phase 3-E-15).

    ``RULE-SPELLTRAP-007`` · ``RULE-SPELLTRAP-009`` 가 세트한 속공 마법과
    함정에만 이 제약을 둔다. 세트한 **통상** 마법은 같은 턴에 발동할 수
    있으므로 (``RULE-SPELLTRAP-012``) 이 코드가 붙지 않는다.
    """
    TARGET_NOT_OPPONENT = "target_not_opponent"
    TARGET_SELF_CONTROLLED = "target_self_controlled"
    TARGET_WRONG_ZONE = "target_wrong_zone"
    PHASE_UNCHANGED = "phase_unchanged"

    # --- 모른다 (UNKNOWN) ----------------------------------------------
    HIDDEN_CARD = "hidden_card"
    """가리킨 카드가 관측에 없다. **없다는 뜻이 아니다** — 가려진 것일 수 있다."""
    INFORMATION_UNAVAILABLE = "information_unavailable"
    """
    요구를 판정할 정보가 없다. 무엇이 없는지는 :attr:`ValidationResult.notes`
    가 조건 계층의 말 그대로 전한다 — 가려진 카드일 수도, 읽을 수 없는 카드
    정의일 수도 있다.
    """
    CARD_DEFINITION_UNAVAILABLE = "card_definition_unavailable"
    EFFECT_LIST_UNRELIABLE = "effect_list_unreliable"
    """``effect_count`` 가 0 이다. 효과가 없어서인지 못 읽어서인지 모른다."""
    RULE_NOT_IMPLEMENTED = "rule_not_implemented"
    """
    **이 엔진이 아직 못 한다.** 판이 어떻든 달라지지 않고, 코드가 생겨야 풀린다.

    ``UNKNOWN`` 쪽의 코드다 — 확실한 거부(``INVALID``)에 붙이지 않는다.
    "조건을 끝까지 보고 거짓을 받았다" 는 미구현이 아니라 거부이고, 섞어
    적으면 "엔진이 못 한 것" 을 세는 쪽이 거부를 미구현으로 읽는다.

    구분해 쓸 자리들 (Phase 3-E-24 에서 측정, 3-E-26 에서 정리):

    * 정보가 없어서 모른다 → ``INFORMATION_UNAVAILABLE`` · ``HIDDEN_CARD``
    * 출처가 실행을 금지한다 → ``EXECUTION_FORBIDDEN``
    * 후보가 조건을 만족하지 않는다 → ``CANDIDATE_NOT_ELIGIBLE``
    """

    # --- 비용 · 선택 (Phase 2-C) ---------------------------------------
    NO_CANDIDATES = "no_candidates"
    """비용을 치를 후보가 하나도 없다."""
    TOO_FEW_SELECTED = "too_few_selected"
    TOO_MANY_SELECTED = "too_many_selected"
    DUPLICATE_SELECTION = "duplicate_selection"
    CANDIDATE_NOT_FOUND = "candidate_not_found"
    """고른 카드가 관측에 없다."""
    CANDIDATE_NOT_ELIGIBLE = "candidate_not_eligible"
    """고른 카드가 후보 조건을 만족하지 않는다."""
    INSUFFICIENT_LIFE = "insufficient_life"
    COST_NOT_IMPLEMENTED = "cost_not_implemented"

    # --- 효과 실행 (Phase 2-D-2) ---------------------------------------
    INSUFFICIENT_DECK = "insufficient_deck"
    """
    요청한 만큼 뽑을 카드가 덱에 없다.

    ``RULE_NOT_IMPLEMENTED`` 와 합치지 않는다 — 전자는 "이 엔진이 못 한다",
    이것은 "지금 판에 카드가 모자라다" 로 서로 다른 사실이다. 덱이 모자랄
    때 무슨 일이 일어나는가(덱 데스)는 아직 없으므로, 모자라면 **한 장도
    뽑지 않고** 이 코드로 거절한다.
    """
    INVALID_AMOUNT = "invalid_amount"
    """수치가 의미를 갖지 못한다 (0장 드로우 · 음수 드로우 등)."""

    # --- 우선권 · 응답 기회 (Phase 2-F-1) --------------------------------
    NO_RESPONSE_WINDOW = "no_response_window"
    """지금 결정할 기회 자체가 열려 있지 않다. 누구도 행동할 차례가 아니다."""
    NOT_PRIORITY_HOLDER = "not_priority_holder"
    """기회는 열려 있지만 **이 플레이어의 차례가 아니다.**"""
    EXECUTION_FORBIDDEN = "execution_forbidden"
    """
    출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004).

    ``INVALID`` 중에서도 **따로 구분한다** — "조건이 거짓" 과 "이 근거로는
    절대 실행하지 않는다" 는 전혀 다른 말이고, 후자는 판이 바뀌어도
    달라지지 않는다.
    """
    CHAIN_EMPTY = "chain_empty"
    """체인에 쌓인 것이 없다. "다 해결했다" 와 다른 사실이다."""
    CHAIN_DEFINITION_UNAVAILABLE = "chain_definition_unavailable"
    """체인 링크가 가리키는 효과의 정의를 찾을 수 없다. 해결할 수 없다."""
    # --- 일반 소환 (Phase 2-I) -----------------------------------------
    CANNOT_NORMAL_SUMMON = "cannot_normal_summon"
    """
    이 카드는 일반 소환으로 필드에 나올 수 없다 (엑스트라 덱 · 의식 · 토큰).

    ``SOURCE_WRONG_CARD_TYPE`` 과 합치지 않는다 — 그쪽은 "몬스터가 아니다",
    이것은 "몬스터지만 이 방법으로는 나오지 않는다" 로 다른 사실이다.
    """
    NORMAL_SUMMON_ALREADY_USED = "normal_summon_already_used"
    """
    이번 턴의 소환권을 이미 썼다 (RULE-SUMMON-009).

    카드 효과의 "1턴에 1번" 과 다른 제약이다 — 그쪽은 카드마다, 이쪽은
    플레이어마다 하나다.
    """

    # --- 발동 타이밍 · 스펠 스피드 (Phase 2-S) --------------------------
    SPELL_SPEED_TOO_LOW = "spell_speed_too_low"
    """
    체인에 응수하기에 스펠 스피드가 모자라다 (RULE-CHAIN-003 · 004).

    ``NO_RESPONSE_WINDOW`` 와 합치지 않는다 — 그쪽은 "기회 자체가 없다",
    이쪽은 **기회는 있는데 이 카드로는 응수할 수 없다** 이다.
    ``WRONG_PHASE`` 와도 다르다: 페이즈가 아니라 체인의 문제다.

    스펠 스피드를 **판정할 수 없는** 경우에는 쓰지 않는다. 그때는
    ``RULE_NOT_IMPLEMENTED`` 또는 ``INFORMATION_UNAVAILABLE`` 이고, 모르는
    것을 위반으로 접지 않는다.
    """

    PRIORITY_STATE_STALE = "priority_state_stale"
    """
    우선권 상태가 지금 판과 맞지 않는다 (턴 플레이어 · 페이즈가 다르다).

    ``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다 — 어느 쪽이 낡았는지 모르는
    상태에서 "안 된다" 고 단정하지 않는다.
    """



# ======================================================================
# 어느 판정 묶음의 말인가 — UNKNOWN policy (Phase 3-E-40)
# ======================================================================

#: 각 :class:`ValidationCode` 가 **어느 판정의 말인가.**
#:
#: 왜 필요했나
#: ----------
#: 이 enum 은 묶음을 **주석**으로 적어 왔다 (``# --- 모른다 (UNKNOWN) ---``).
#: 사람은 읽지만 기계는 읽지 못하므로, 그 사실이 필요한 곳에서는 **손으로 쓴
#: 사본**을 만들어 썼다. ``agent/simulation.py`` 의 ``_UNKNOWN_CODES`` 가 그것
#: 이었고, 사본이라서 어긋났다 — Phase 3-E-39 가 ``HIDDEN_CARD`` 와
#: ``PRIORITY_STATE_STALE`` 이 빠진 것을 측정했다. 사본을 고치는 대신 **원본을
#: 기계가 읽을 수 있게** 적는다.
#:
#: 왜 ``ActionValidity`` 인가
#: -------------------------
#: "이 코드는 모름 쪽인가" 는 **새 어휘가 필요한 질문이 아니다.** 이미
#: :class:`ActionValidity` 가 세 값으로 그것을 말한다. 새 enum 을 만들면 같은
#: 구분이 저장소에 둘이 되고, 그것이 애초의 문제였다.
#:
#: ``None`` 은 무엇인가
#: -------------------
#: **"이 코드만으로는 정할 수 없다."** 임의로 한쪽에 넣지 않는다 — 모름을
#: 참/거짓으로 접지 않는 이 저장소의 규칙이 코드 분류에도 적용된다. ``None``
#: 은 "모름(UNKNOWN)" 과 다르다: 전자는 **분류를 못 한다**, 후자는 **엔진이
#: 판단을 못 한다** 이다.
#:
#: 무엇을 근거로 정했나 (Phase 3-E-40 §4 · §5 가 전수 측정)
#: -------------------------------------------------------
#: 1. production 이 ``ValidationResult`` 에 **직접 선언한** validity
#: 2. 이 enum 의 묶음 주석이 ``(INVALID)`` · ``(UNKNOWN)`` 로 적은 라벨
#: 3. 생성 자리에서 **짝지은 status** 가 말하는 것
#:
#: 셋이 어긋나는 코드는 **하나뿐**이고 (``CHAIN_DEFINITION_UNAVAILABLE``) 그것이
#: ``None`` 이다. 나머지 47개는 근거가 서로 맞는다.
#:
#: 빠뜨리면 어떻게 되나
#: -------------------
#: **import 할 때 터진다** (바로 아래의 검사). 멤버를 더하고 분류를 적지 않는
#: 길이 없다 — 사본이 조용히 낡던 바로 그 일을 막는 자리다.
CODE_VALIDITY: "dict[ValidationCode, ActionValidity | None]" = {
    ValidationCode.OK: ActionValidity.VALID,
    # --- 구조 (INVALID) — 묶음 라벨 · 생성 validity 모두 INVALID ---------
    ValidationCode.ACTOR_INVALID: ActionValidity.INVALID,
    ValidationCode.SOURCE_REQUIRED: ActionValidity.INVALID,
    ValidationCode.SOURCE_FORBIDDEN: ActionValidity.INVALID,
    ValidationCode.EFFECT_REF_REQUIRED: ActionValidity.INVALID,
    ValidationCode.EFFECT_REF_FORBIDDEN: ActionValidity.INVALID,
    ValidationCode.EFFECT_REF_CARD_MISMATCH: ActionValidity.INVALID,
    ValidationCode.EFFECT_REF_OUT_OF_RANGE: ActionValidity.INVALID,
    ValidationCode.PHASE_REQUIRED: ActionValidity.INVALID,
    ValidationCode.PHASE_FORBIDDEN: ActionValidity.INVALID,
    ValidationCode.TARGET_COUNT_MISMATCH: ActionValidity.INVALID,
    ValidationCode.TARGET_KIND_INVALID: ActionValidity.INVALID,
    # --- 판 위의 사실 (INVALID) ----------------------------------------
    ValidationCode.DUEL_ALREADY_OVER: ActionValidity.INVALID,
    ValidationCode.NOT_TURN_PLAYER: ActionValidity.INVALID,
    ValidationCode.SOURCE_NOT_CONTROLLED: ActionValidity.INVALID,
    ValidationCode.SOURCE_WRONG_ZONE: ActionValidity.INVALID,
    ValidationCode.SOURCE_WRONG_CARD_TYPE: ActionValidity.INVALID,
    ValidationCode.ZONE_FULL: ActionValidity.INVALID,
    ValidationCode.WRONG_PHASE: ActionValidity.INVALID,
    ValidationCode.SET_THIS_TURN: ActionValidity.INVALID,
    ValidationCode.TARGET_NOT_OPPONENT: ActionValidity.INVALID,
    ValidationCode.TARGET_SELF_CONTROLLED: ActionValidity.INVALID,
    ValidationCode.TARGET_WRONG_ZONE: ActionValidity.INVALID,
    ValidationCode.PHASE_UNCHANGED: ActionValidity.INVALID,
    # --- 모른다 (UNKNOWN) ----------------------------------------------
    #: 다섯 모두 ``ValidationResult.unknown`` 으로만 생산된다.
    ValidationCode.HIDDEN_CARD: ActionValidity.UNKNOWN,
    ValidationCode.INFORMATION_UNAVAILABLE: ActionValidity.UNKNOWN,
    ValidationCode.CARD_DEFINITION_UNAVAILABLE: ActionValidity.UNKNOWN,
    ValidationCode.EFFECT_LIST_UNRELIABLE: ActionValidity.UNKNOWN,
    ValidationCode.RULE_NOT_IMPLEMENTED: ActionValidity.UNKNOWN,
    # --- 비용 · 선택 (Phase 2-C) ---------------------------------------
    ValidationCode.NO_CANDIDATES: ActionValidity.INVALID,
    ValidationCode.TOO_FEW_SELECTED: ActionValidity.INVALID,
    ValidationCode.TOO_MANY_SELECTED: ActionValidity.INVALID,
    ValidationCode.DUPLICATE_SELECTION: ActionValidity.INVALID,
    #: 설명은 "관측에 없다" 고 적지만 **코드는 판 전체를 본다**
    #: (``state.find_instance(...) is None``). 즉 가려진 것이 아니라 **이 듀얼에
    #: 없는** 카드이고, 두 생성 자리 모두 확정 거부와 짝지었다
    #: (``PaymentStatus.INVALID_SELECTION`` · ``ResolutionStatus.INVALID_TARGET``).
    ValidationCode.CANDIDATE_NOT_FOUND: ActionValidity.INVALID,
    ValidationCode.CANDIDATE_NOT_ELIGIBLE: ActionValidity.INVALID,
    ValidationCode.INSUFFICIENT_LIFE: ActionValidity.INVALID,
    #: 묶음은 비용이지만 뜻은 미구현이다 — ``unknown`` 으로만 생산되고
    #: ``PaymentStatus.UNSUPPORTED_COST`` 와 짝지는다.
    ValidationCode.COST_NOT_IMPLEMENTED: ActionValidity.UNKNOWN,
    # --- 효과 실행 (Phase 2-D-2) ---------------------------------------
    ValidationCode.INSUFFICIENT_DECK: ActionValidity.INVALID,
    ValidationCode.INVALID_AMOUNT: ActionValidity.INVALID,
    # --- 우선권 · 응답 기회 (Phase 2-F-1) -------------------------------
    ValidationCode.NO_RESPONSE_WINDOW: ActionValidity.INVALID,
    ValidationCode.NOT_PRIORITY_HOLDER: ActionValidity.INVALID,
    #: ``INVALID`` 중에서 따로 구분하는 것이고 ``UNKNOWN`` 이 아니다 — 판이
    #: 바뀌어도 달라지지 않는다 (ADR-004, Phase 3-E-38).
    ValidationCode.EXECUTION_FORBIDDEN: ActionValidity.INVALID,
    ValidationCode.CHAIN_EMPTY: ActionValidity.INVALID,
    #: **정할 수 없다.** 두 생성 자리가 서로 다른 말을 한다 —
    #: ``trigger_chain.py`` 는 ``ChainInsertion.UNKNOWN`` ("확인할 수 없습니다")
    #: 와 짝짓고 ``chain.py`` 는 ``ChainResolutionStatus.INVALID_CHAIN_LINK``
    #: 와 짝짓는다. 어느 한쪽으로 접으면 다른 한쪽이 거짓이 된다. 분류를
    #: 비워 두는 것이 지금 아는 것을 정확히 적는 방법이다 (Phase 3-E-40 §7).
    ValidationCode.CHAIN_DEFINITION_UNAVAILABLE: None,
    # --- 일반 소환 (Phase 2-I) -----------------------------------------
    #: 둘 다 ``Requirement`` 로만 실린다. ``_check_requirements`` 는 조건이
    #: ``FALSE`` 일 때만 그 코드를 ``invalid()`` 로 쓰고, ``UNKNOWN`` 일 때는
    #: 코드를 모름 쪽으로 **갈아 끼운다** — 그래서 확정 거부다.
    ValidationCode.CANNOT_NORMAL_SUMMON: ActionValidity.INVALID,
    ValidationCode.NORMAL_SUMMON_ALREADY_USED: ActionValidity.INVALID,
    # --- 발동 타이밍 · 스펠 스피드 (Phase 2-S) --------------------------
    ValidationCode.SPELL_SPEED_TOO_LOW: ActionValidity.INVALID,
    #: 설명이 직접 적는다 — "``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다".
    ValidationCode.PRIORITY_STATE_STALE: ActionValidity.UNKNOWN,
}

_UNCLASSIFIED = set(ValidationCode) - set(CODE_VALIDITY)
if _UNCLASSIFIED:  # pragma: no cover - 분류를 빠뜨리면 import 가 실패한다
    raise RuntimeError(
        "CODE_VALIDITY 가 다루지 않는 ValidationCode 가 있습니다: "
        + ", ".join(sorted(code.name for code in _UNCLASSIFIED))
        + ". 새 멤버를 더하면 여기에 **어느 판정의 말인지** 함께 적습니다 — "
        "분류를 빠뜨린 채로 돌아가면 그 코드는 조용히 '모름이 아닌 것' 이 됩니다."
    )


def codes_declaring(validity: "ActionValidity | None") -> frozenset[ValidationCode]:
    """
    그 판정의 말인 코드들. :data:`CODE_VALIDITY` 에서 **파생**된다.

    사본을 만들지 않는다 — 부르는 쪽이 집합을 손으로 적으면 이 Phase 가 고친
    문제가 그대로 돌아온다.
    """
    return frozenset(
        code for code, declared in CODE_VALIDITY.items() if declared is validity
    )


def unknown_codes() -> frozenset[ValidationCode]:
    """
    **"엔진이 판단을 확정할 수 없다" 쪽의 코드들.**

    ``agent`` 계층의 시뮬레이션이 "모른다" 와 "거절했다" 를 가를 때 쓴다.
    ``None`` 으로 분류한 코드는 **들어가지 않는다** — 정하지 못한 것을 모름으로
    밀어 넣으면 분류하지 않았다는 사실이 사라진다.
    """
    return codes_declaring(ActionValidity.UNKNOWN)

@dataclass(frozen=True, slots=True)
class ValidationResult:
    """검증 결과 하나. 판정 · 안정적인 코드 · 사람이 읽을 설명."""

    validity: ActionValidity
    code: ValidationCode = ValidationCode.OK
    reason: str = ""
    missing_rule: str | None = None
    """UNKNOWN 일 때, 무엇이 없어서 모르는가. 로드맵 추적에 쓴다."""
    notes: tuple[str, ...] = ()
    """부수적으로 모인 관찰. 판정을 바꾸지 않는다."""

    @property
    def permits_execution(self) -> bool:
        """
        실행해도 되는가. **``VALID`` 일 때만 참이다.**

        ``UNKNOWN`` 을 허가로 잘못 읽는 코드를 구조적으로 막는다.
        """
        return self.validity is ActionValidity.VALID

    @property
    def is_structural_failure(self) -> bool:
        return self.validity is ActionValidity.INVALID

    def __bool__(self) -> bool:
        raise TypeError(
            "ValidationResult 를 참/거짓으로 쓸 수 없습니다. UNKNOWN 이 조용히 "
            "허가가 되는 것을 막기 위해서입니다. `result.permits_execution` 을 "
            "보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.validity.value,
            self.code.value,
            self.reason,
            self.missing_rule,
            self.notes,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "validity": self.validity.value,
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.missing_rule is not None:
            data["missing_rule"] = self.missing_rule
        if self.notes:
            data["notes"] = list(self.notes)
        return data

    # --- 생성자 -------------------------------------------------------
    @classmethod
    def valid(cls, reason: str = "") -> "ValidationResult":
        return cls(ActionValidity.VALID, ValidationCode.OK, reason)

    @classmethod
    def invalid(cls, code: ValidationCode, reason: str) -> "ValidationResult":
        return cls(ActionValidity.INVALID, code, reason)

    @classmethod
    def unknown(
        cls,
        code: ValidationCode,
        reason: str,
        missing_rule: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> "ValidationResult":
        return cls(ActionValidity.UNKNOWN, code, reason, missing_rule, notes)

    def __str__(self) -> str:
        head = f"{self.validity.value}[{self.code.value}]"
        return f"{head}: {self.reason}" if self.reason else head
