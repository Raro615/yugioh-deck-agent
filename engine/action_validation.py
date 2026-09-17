"""
Action 검증 **인터페이스**.

Phase 2-A 는 유희왕 규칙을 구현하지 않는다. 여기서 보는 것은 두 층 중
**아래층 하나**뿐이다.

=================  ================================================  ==========
층                  질문                                              지금 상태
=================  ================================================  ==========
구조 (structure)   이 Action 이 **말이 되는 모양인가**                구현됨
적법성 (legality)  이 행위를 지금 **해도 되는가**                     Phase 2-B~
=================  ================================================  ==========

"일반 소환인데 소환할 카드가 없다" 는 구조 오류다. "이 카드를 지금 일반
소환할 수 있는가" 는 적법성이고, 아직 아무도 모른다.

UNKNOWN 은 허가가 아니다
------------------------
프로젝트 전체에서 지켜 온 원칙이다 — ``unknown`` 을 임의로 참/거짓으로
바꾸지 않는다. Phase 3 의 ``TriValue`` 와 같은 태도이고, 여기서는 특히
**UNKNOWN 을 INVALID 로도, VALID 로도 바꾸지 않는다.**

실수를 구조로 막기 위해 :attr:`ValidationResult.permits_execution` 은
``VALID`` 일 때만 참이다. ``if result.validity is not INVALID:`` 같은 코드를
쓰면 UNKNOWN 이 허가로 새어 나가므로, 그 대신 이 프로퍼티를 본다.

상태를 바꾸지 않는다
--------------------
:meth:`ActionValidator.validate` 는 ``GameState`` 를 **읽기만** 한다.
카드 이동 · LP 변경 · ``UseRegistry`` 기록이 검증 중에 일어나면 안 된다.
``tests/engine/test_action_validation.py`` 가 ``state_hash()`` 로 이를 확인한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from engine.action import (
    _ALLOWS_EFFECT_REF,
    _FORBIDS_SOURCE,
    _NEEDS_EFFECT_REF,
    _NEEDS_PHASE,
    _NEEDS_SOURCE,
    _TARGET_COUNT,
    PlayerAction,
    PlayerActionKind,
)
from engine.action_target import ActionTargetKind

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from engine.state.game_state import GameState


class ActionValidity(str, Enum):
    """검증 결과 세 가지."""

    VALID = "valid"
    """처리해도 된다. **구조와 적법성이 모두 확인되었을 때만** 쓴다."""
    INVALID = "invalid"
    """구조 자체가 틀렸거나 규칙이 확실히 금지한다. 처리하지 않는다."""
    UNKNOWN = "unknown"
    """
    아직 판단할 수 없다. **거부가 아니다.**

    Phase 2-A 에서는 구조가 멀쩡한 Action 이 전부 여기로 온다 — 적법성
    계층이 없기 때문이다. 시간이 지나 규칙이 구현되면 VALID 나 INVALID 로
    갈린다.
    """


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """검증 결과 하나. 판정과 **그 이유**를 함께 낸다."""

    validity: ActionValidity
    reason: str = ""
    missing_rule: str | None = None
    """UNKNOWN 일 때, 무엇이 없어서 모르는가. AI 설명과 로드맵 추적에 쓴다."""

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

    def canonical_state(self) -> tuple:
        return (self.validity.value, self.reason, self.missing_rule)

    # --- 생성자 -------------------------------------------------------
    @classmethod
    def valid(cls, reason: str = "") -> "ValidationResult":
        return cls(ActionValidity.VALID, reason)

    @classmethod
    def invalid(cls, reason: str) -> "ValidationResult":
        return cls(ActionValidity.INVALID, reason)

    @classmethod
    def unknown(cls, reason: str, missing_rule: str) -> "ValidationResult":
        return cls(ActionValidity.UNKNOWN, reason, missing_rule)

    def __str__(self) -> str:
        return f"{self.validity.value}: {self.reason}" if self.reason else self.validity.value


#: 종류별로 "어떤 규칙 계층이 있어야 판정할 수 있는가".
#: Phase 2-A 는 이 계층을 하나도 갖고 있지 않다.
_MISSING_RULE: dict[PlayerActionKind, str] = {
    PlayerActionKind.NORMAL_SUMMON: "summon-legality (Phase 2-G)",
    PlayerActionKind.SET_MONSTER: "summon-legality (Phase 2-G)",
    PlayerActionKind.SET_SPELL_TRAP: "zone-legality (Phase 2-G)",
    PlayerActionKind.ACTIVATE_CARD: "activation-condition (Phase 2-B)",
    PlayerActionKind.ACTIVATE_EFFECT: "activation-condition (Phase 2-B)",
    PlayerActionKind.CHANGE_POSITION: "position-change-legality (Phase 2-G)",
    PlayerActionKind.ATTACK: "battle-legality (Phase 2-G)",
    PlayerActionKind.CHANGE_PHASE: "turn-progression (Phase 2-G)",
    PlayerActionKind.END_PHASE: "turn-progression (Phase 2-G)",
    PlayerActionKind.PASS: "priority (Phase 2-F)",
}


class ActionValidator:
    """
    Action 을 검증한다. **상태를 바꾸지 않는다.**

    두 진입점이 있다.

    - :meth:`validate_structure` — 모양만 본다. ``VALID`` / ``INVALID``.
    - :meth:`validate` — 모양을 본 뒤 적법성까지 본다. Phase 2-A 에서는
      적법성 계층이 없으므로 ``INVALID`` / ``UNKNOWN`` 만 나온다.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    # 구조 검사
    # ------------------------------------------------------------------
    def validate_structure(
        self, state: "GameState | None", action: PlayerAction
    ) -> ValidationResult:
        """
        Action 의 **모양**을 본다. 규칙은 보지 않는다.

        ``state`` 가 있으면 "가리킨 인스턴스가 실제로 존재하는가" 까지 본다.
        존재 확인은 규칙이 아니라 **참조 무결성**이다 — 없는 카드를 가리키는
        Action 은 어떤 규칙을 붙여도 처리할 수 없다.
        """
        kind = action.kind

        # --- source ---------------------------------------------------
        if kind in _NEEDS_SOURCE and action.source is None:
            return ValidationResult.invalid(f"{kind.value} 에는 source 가 필요합니다.")
        if kind in _FORBIDS_SOURCE and action.source is not None:
            return ValidationResult.invalid(
                f"{kind.value} 는 source 를 가질 수 없습니다."
            )

        # --- effect_ref -----------------------------------------------
        if kind in _NEEDS_EFFECT_REF and action.effect_ref is None:
            return ValidationResult.invalid(
                f"{kind.value} 에는 effect_ref 가 필요합니다. "
                "어느 효과인지 EffectRef(card_id, ordinal) 로 지목하세요."
            )
        if kind not in _ALLOWS_EFFECT_REF and action.effect_ref is not None:
            return ValidationResult.invalid(
                f"{kind.value} 는 effect_ref 를 가질 수 없습니다."
            )

        # --- phase ----------------------------------------------------
        if kind in _NEEDS_PHASE and action.phase is None:
            return ValidationResult.invalid(f"{kind.value} 에는 phase 가 필요합니다.")
        if kind not in _NEEDS_PHASE and action.phase is not None:
            return ValidationResult.invalid(f"{kind.value} 는 phase 를 가질 수 없습니다.")

        # --- 대상 개수 -------------------------------------------------
        expected = _TARGET_COUNT.get(kind)
        if expected is not None and len(action.targets) != expected:
            return ValidationResult.invalid(
                f"{kind.value} 의 대상은 {expected}개여야 합니다: "
                f"{len(action.targets)}개가 들어왔습니다."
            )

        if kind is PlayerActionKind.ATTACK:
            target = action.targets[0]
            if target.kind not in (
                ActionTargetKind.INSTANCE,
                ActionTargetKind.PLAYER,
            ):
                return ValidationResult.invalid(
                    "공격 대상은 몬스터(instance) 또는 플레이어여야 합니다: "
                    f"{target.kind.value}"
                )

        # --- 참조 무결성 -----------------------------------------------
        if state is not None:
            missing = self._missing_reference(state, action)
            if missing is not None:
                return ValidationResult.invalid(missing)

        return ValidationResult.valid("구조가 올바릅니다.")

    def _missing_reference(
        self, state: "GameState", action: PlayerAction
    ) -> str | None:
        """가리킨 대상이 실제로 있는지 본다. 없으면 이유를, 있으면 ``None``."""
        if action.source is not None and state.find_instance(action.source) is None:
            return f"source {action.source} 가 이 듀얼에 없습니다."
        for target in action.targets:
            if (
                target.kind is ActionTargetKind.INSTANCE
                and target.instance_id is not None
                and state.find_instance(target.instance_id) is None
            ):
                return f"대상 {target.instance_id} 가 이 듀얼에 없습니다."
        if action.effect_ref is not None and action.source is not None:
            card = state.find_instance(action.source)
            if card is not None and card.card_id != action.effect_ref.card_id:
                return (
                    f"effect_ref 의 카드({action.effect_ref.card_id})가 "
                    f"source 카드({card.card_id})와 다릅니다."
                )
        return None

    # ------------------------------------------------------------------
    # 전체 검사
    # ------------------------------------------------------------------
    def validate(
        self, state: "GameState | None", action: PlayerAction
    ) -> ValidationResult:
        """
        구조와 적법성을 함께 본다. **``GameState`` 를 바꾸지 않는다.**

        Phase 2-A 에는 적법성 계층이 없으므로, 구조가 멀쩡한 Action 은 전부
        ``UNKNOWN`` 이다. **이것은 거부가 아니다** — 아직 모른다는 뜻이고,
        :attr:`ValidationResult.permits_execution` 은 거짓이므로 실행으로
        이어지지도 않는다.
        """
        structural = self.validate_structure(state, action)
        if structural.validity is not ActionValidity.VALID:
            return structural
        return ValidationResult.unknown(
            f"{action.kind.value} 의 적법성을 판정할 규칙 계층이 아직 없습니다. "
            "구조는 올바릅니다.",
            missing_rule=_MISSING_RULE[action.kind],
        )
