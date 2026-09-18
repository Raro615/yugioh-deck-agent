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
    CHAIN_EMPTY = "chain_empty"
    """체인에 쌓인 것이 없다. "다 해결했다" 와 다른 사실이다."""
    CHAIN_DEFINITION_UNAVAILABLE = "chain_definition_unavailable"
    """체인 링크가 가리키는 효과의 정의를 찾을 수 없다. 해결할 수 없다."""
    PRIORITY_STATE_STALE = "priority_state_stale"
    """
    우선권 상태가 지금 판과 맞지 않는다 (턴 플레이어 · 페이즈가 다르다).

    ``INVALID`` 가 아니라 ``UNKNOWN`` 에 쓴다 — 어느 쪽이 낡았는지 모르는
    상태에서 "안 된다" 고 단정하지 않는다.
    """


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
