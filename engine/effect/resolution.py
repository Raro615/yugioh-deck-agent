"""
해결 **계약** — 실행기가 지켜야 할 약속.

실행기를 만들지 않는다. "실행기가 무엇을 받고 무엇을 돌려줘야 하는가" 만
고정한다.

    EffectDefinition  +  ResolutionContext  +  GameStateView
        ↓  EffectResolver.resolve()
    EffectResult
        ↓  (Phase 2-D-2)
    StateDelta  →  GameState

마지막 화살표는 **아직 없다.** ``StateDelta`` 는 ADR-008 이 Phase 2-E 로
미뤄 두었고, 여기서도 만들지 않는다.

지금 유일한 실행기
------------------
:class:`UnimplementedResolver` 는 언제나 ``NOT_IMPLEMENTED`` 를 돌려준다.
자리표시가 아니라 **지금 엔진의 정직한 상태**다 — 등록된 구현이 하나도 없다.
이것이 있어서 "계약이 지켜지는가" 를 실제로 테스트할 수 있다.

문맥은 안정적인 식별자만 담는다
-------------------------------
``ResolutionContext`` 에 ``CardInstance`` 나 ``GameState`` 를 담지 않는다.
담으면 문맥이 특정 판에 묶이고, 직렬화도 replay 도 불가능해진다.

체인 · 트리거 · 타이밍은 **자리도 만들지 않았다.** 그 시스템이 없는데
칸을 비워 두면 모양을 미리 못박게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from engine.condition import ConditionContext
from engine.cost import Selection
from engine.effect.delta import StateDelta, canonical_deltas
from engine.effect.definition import (
    EffectDefinition,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.operation import OperationKind
from engine.effect.target import TargetRef, TargetSelection
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.validation import ValidationCode


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """
    효과 하나를 해결할 때의 문맥. **불변**이고 값 타입만 담는다.

    ``controller`` 는 효과를 발동한 플레이어다. 카드의 ``owner`` /
    ``controller`` 와 다를 수 있다 — 컨트롤을 빼앗긴 카드의 효과는
    빼앗은 쪽이 쓴다.
    """

    effect_ref: EffectRef
    controller: int
    source: InstanceId | None = None
    """효과를 발동한 카드. 필드를 떠난 뒤에도 해결되는 효과가 있으므로 없을 수 있다."""
    selections: tuple[TargetSelection, ...] = ()
    """
    **이번 해결에서** 각 대상 이름에 무엇이 골라졌는가.

    비어 있는 것은 "대상이 없다" 가 아니라 **"아직 고르지 않았다"** 다.
    대상이 없는 효과는 정의의 ``targets`` 가 비어 있는 쪽으로 표현된다.
    """
    cost_selections: tuple[Selection, ...] = ()
    """비용으로 내놓기로 한 카드들. 비용 순서대로다."""

    def __post_init__(self) -> None:
        if self.controller not in (0, 1):
            raise ValueError(f"controller 는 0 또는 1 입니다: {self.controller}")
        for name in ("selections", "cost_selections"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 은 tuple 이어야 합니다 — 문맥은 불변입니다.")
        seen: set[TargetRef] = set()
        for chosen in self.selections:
            if chosen.ref in seen:
                raise ValueError(f"대상 {chosen.ref} 에 선택이 두 번 들어왔습니다.")
            seen.add(chosen.ref)

    @property
    def opponent(self) -> int:
        return 1 - self.controller

    def selection_for(self, ref: TargetRef) -> Selection | None:
        """
        그 이름에 골라진 것. **아직 고르지 않았으면 ``None``.**

        빈 :class:`~engine.cost.Selection` 과 ``None`` 은 다르다 — 전자는
        "고른 결과가 없음", 후자는 "아직 고르지 않음" 이다.
        """
        for chosen in self.selections:
            if chosen.ref == ref:
                return chosen.selection
        return None

    @property
    def chosen_instances(self) -> tuple[InstanceId, ...]:
        """골라진 카드 전부. 대상 이름 선언 순서대로 이어 붙인다."""
        found: list[InstanceId] = []
        for chosen in self.selections:
            found.extend(chosen.selection.chosen)
        return tuple(found)

    def pending_targets(self, definition: EffectDefinition) -> tuple[TargetRef, ...]:
        """
        정의가 요구하는데 **아직 고르지 않은** 대상들.

        정의를 인자로 받는다 — 문맥은 자기가 무엇을 요구받았는지 모른다.
        요구는 정의에 있고 결과는 문맥에 있다.
        """
        waiting: list[TargetRef] = []
        for binding in definition.targets:
            if binding.spec.is_pending(self.selection_for(binding.ref)):
                waiting.append(binding.ref)
        return tuple(waiting)

    def condition_context(self) -> ConditionContext:
        """
        조건 계층으로 넘길 문맥. 같은 식별자를 그대로 옮긴다.

        조건 계층이 자기 문맥 타입을 갖고 있으므로, 여기서 변환해 준다.
        두 타입을 합치지 않는 이유는 담는 것이 다르기 때문이다 — 조건은
        비용 선택을 알 필요가 없다.
        """
        return ConditionContext(
            player=self.controller,
            source=self.source,
            effect_ref=self.effect_ref,
            targets=self.chosen_instances,
        )

    def canonical_state(self) -> tuple:
        return (
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.controller,
            self.source.value if self.source is not None else None,
            tuple(s.canonical_state() for s in self.selections),
            tuple(s.canonical_state() for s in self.cost_selections),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "controller": self.controller,
            "selections": [s.to_dict() for s in self.selections],
        }
        if self.source is not None:
            data["source"] = self.source.value
        if self.cost_selections:
            data["cost_selections"] = [s.to_dict() for s in self.cost_selections]
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"<Resolution {self.effect_ref} P{self.controller}>"


class ResolutionStatus(str, Enum):
    """
    해결 시도의 결과.

    **``RESOLVED`` 하나만 판을 바꾼다.** 나머지는 전부 "아무 일도 일어나지
    않았다" 를 뜻하고, 이유만 다르다.
    """

    RESOLVED = "resolved"
    """해결되었다. 판이 바뀌었다."""
    NOT_IMPLEMENTED = "not_implemented"
    """이 효과의 실행 구현이 등록되어 있지 않다. 판은 그대로다."""
    UNSUPPORTED_OPERATION = "unsupported_operation"
    """
    실행기가 다룰 수 없는 일이 들어 있다. 판은 그대로다.

    "구현이 없다" 와 다르다 — 효과는 등록되어 있는데 그 안의 일을 이
    실행기가 못 하는 경우다.
    """
    FORBIDDEN = "forbidden"
    """출처가 실행을 금지한다 (``TEXT_DERIVED``). 판은 그대로다."""
    INVALID_CONTEXT = "invalid_context"
    """문맥이 정의와 맞지 않는다. 판은 그대로다."""
    INVALID_TARGET = "invalid_target"
    """대상이 없거나, 고르지 않았거나, 판에 존재하지 않는다. 판은 그대로다."""
    INVALID_OPERATION = "invalid_operation"
    """
    일 자체가 의미를 갖지 못한다 (0장 드로우처럼). 판은 그대로다.

    ``UNSUPPORTED_OPERATION`` 과 다르다 — 그쪽은 "이 실행기가 못 한다" 이고,
    이쪽은 **그 일이 애초에 말이 되지 않는다** 이다.
    """
    INSUFFICIENT_CARDS = "insufficient_cards"
    """
    요청한 만큼의 카드가 판에 없다. 판은 **그대로다** — 있는 만큼만 하고
    끝내지 않는다.

    ``UNSUPPORTED_OPERATION`` 과 합치지 않는다. 실행기는 드로우를 할 줄
    알고, 다만 지금 덱이 모자랄 뿐이다. 모자랄 때의 규칙(덱 데스)이 없어서
    거절하는 것이고, 그 사실은 :attr:`EffectResult.missing` 에 남는다.
    """
    CONDITION_FALSE = "condition_false"
    """발동 조건이 **거짓**이다. 판은 그대로다."""
    CONDITION_UNKNOWN = "condition_unknown"
    """
    발동 조건을 **판정할 수 없다.** 판은 그대로다.

    ``CONDITION_FALSE`` 와 합치지 않는다 — "안 된다" 와 "모르겠다" 는
    다른 답이고, 모르는 것을 거짓으로 접으면 프로젝트 전체의 원칙이 깨진다.
    """
    EXECUTION_ERROR = "execution_error"
    """
    적용 중에 예상 못 한 오류가 났다.

    **이때만 판이 반쯤 바뀌어 있을 수 있다.** 실행기는 그 전에 모든 것을
    검사하므로 일어나서는 안 되는 경우이고, 일어났다면 결함이다.
    """
    UNKNOWN = "unknown"
    """해결할 수 있는지 판단할 수 없다. 판은 그대로다."""


@dataclass(frozen=True, slots=True)
class AppliedOperation:
    """
    실제로 적용된 일 하나의 **기록**.

    무엇이 왜 일어났는지 남긴다. 목적지가 같아도 ``kind`` 와
    ``reason_names`` 가 다르므로, 나중에 트리거 계층이 "파괴되었을 때" 와
    "묘지로 보내졌을 때" 를 구분할 수 있다 (ADR-002).

    ``StateDelta`` 가 아니다 — 되돌리는 데 쓸 수 없고, 무슨 일이 있었는지만
    말한다. 되돌리기는 ADR-008 이 Phase 2-E 로 미뤄 두었다.
    """

    kind: OperationKind
    reason_names: tuple[str, ...] = ()
    instances: tuple[InstanceId, ...] = ()
    """이 일이 건드린 카드들. 수치만 다루는 일이면 비어 있다."""
    amount: int | None = None
    """드로우 매수 · 라이프 변화량처럼 수치가 있는 일의 값."""
    player: int | None = None

    def canonical_state(self) -> tuple:
        return (
            self.kind.value,
            self.reason_names,
            tuple(i.value for i in self.instances),
            self.amount,
            self.player,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": self.kind.value, "reasons": list(self.reason_names)}
        if self.instances:
            data["instances"] = [i.value for i in self.instances]
        if self.amount is not None:
            data["amount"] = self.amount
        if self.player is not None:
            data["player"] = self.player
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.kind.value}{[i.value for i in self.instances] or self.amount}"


@dataclass(frozen=True, slots=True)
class EffectResult:
    """
    해결 시도의 결과. **불변**이다.

    :attr:`changed_state` 는 이 시도가 판을 바꿨는지 말한다. ``RESOLVED``
    가 아니면 언제나 거짓이다.

    ``StateDelta`` 는 여기 없다. :attr:`applied` 는 **무슨 일이 있었는지의
    기록**이지 되돌리기 위한 것이 아니다. 되돌리기는 ADR-008 이 Phase 2-E
    로 미뤄 두었다.
    """

    status: ResolutionStatus
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    missing: str | None = None
    """무엇이 없어서 해결하지 못했는가."""
    applied: tuple[AppliedOperation, ...] = ()
    """실제로 적용된 일들. 순서대로다. 실패하면 비어 있다."""
    deltas: tuple[StateDelta, ...] = ()
    """
    그 실행으로 판이 **어떻게 달라졌는가.** 순서대로다.

    :attr:`applied` 와 다른 것을 말한다 — 저쪽은 "무슨 일을 했는가", 이쪽은
    "판이 어떻게 달라졌는가" 다. 일 하나가 변화 여럿을 낳는다.

    **실패한 결과는 언제나 비어 있다.** 판을 바꾸지 않았으므로 적을 변화도
    없다. 반대로 비어 있다고 실패인 것은 아니다 — 하는 일이 하나도 적혀
    있지 않은 정의는 성공하고도 아무것도 바꾸지 않는다.
    """
    unchecked_rules: tuple[str, ...] = ()
    """
    이 실행이 **보지 않은 규칙들** (Phase 2-M).

    의미를 주장하는 일(파괴 · 묘지로 보내기 · 버리기)을 수행했지만 그
    의미의 규칙을 전부 옮기지는 못했을 때, 무엇을 보지 않았는지 그대로
    싣는다 (:data:`~engine.effect.semantics.UNCHECKED_SEMANTIC_RULES`).

    **비어 있다고 "규칙을 전부 봤다" 는 뜻이 아니다** — 드로우처럼 주장할
    의미가 없는 일도 비어 있다. 비어 있지 않으면 확실히 **미완성**이다.
    """

    def __post_init__(self) -> None:
        if self.status is not ResolutionStatus.RESOLVED and self.deltas:
            raise ValueError(
                f"{self.status.value} 인데 변화 기록이 있습니다. 해결되지 "
                "않은 실행은 판을 바꾸지 않습니다."
            )
        if self.unchecked_rules and not self.applied:
            raise ValueError(
                "아무 일도 하지 않았는데 '보지 않은 규칙' 이 있습니다. "
                "무엇을 보지 않았는가는 무엇을 했는가에서 나옵니다."
            )

    @property
    def changed_state(self) -> bool:
        """
        판이 실제로 달라졌는가.

        ``RESOLVED`` 인 것만으로는 부족하다 — 하는 일이 없는 정의도
        해결되기 때문이다. 변화가 있어야 달라진 것이다.
        """
        return bool(self.deltas)

    @property
    def resolved(self) -> bool:
        """해결되었는가. 판을 바꿨는지와는 다른 질문이다."""
        return self.status is ResolutionStatus.RESOLVED

    def __bool__(self) -> bool:
        raise TypeError(
            "EffectResult 를 참/거짓으로 쓸 수 없습니다. 해결되지 않은 것이 "
            "조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`result.status is ResolutionStatus.RESOLVED` 로 비교하세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.code.value,
            self.reason,
            self.missing,
            self.unchecked_rules,
            tuple(a.canonical_state() for a in self.applied),
            canonical_deltas(self.deltas),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.missing is not None:
            data["missing"] = self.missing
        if self.unchecked_rules:
            data["unchecked_rules"] = list(self.unchecked_rules)
        if self.applied:
            data["applied"] = [a.to_dict() for a in self.applied]
        if self.deltas:
            data["deltas"] = [d.to_dict() for d in self.deltas]
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.status.value}[{self.code.value}]: {self.reason}"


@runtime_checkable
class EffectResolver(Protocol):
    """
    실행기가 지켜야 할 계약.

    구현은 다음을 **반드시** 지킨다.

    1. :meth:`resolve` 는 :class:`~engine.game_state_view.GameStateView` 를
       받는다. ``GameState`` 를 받지 않는다.
    2. :func:`~engine.effect.definition.execution_availability` 가
       ``EXECUTABLE`` 이 아니면 **아무것도 하지 않고** 그 사실을 돌려준다.
    3. ``RESOLVED`` 가 아닌 결과를 돌려줄 때 판은 **바뀌지 않은 상태**여야
       한다. 반쯤 실행해 놓고 실패를 알리지 않는다.
    4. 같은 정의 · 같은 문맥 · 같은 관측이면 같은 결과를 돌려준다.
    """

    def resolve(
        self,
        definition: EffectDefinition,
        context: ResolutionContext,
        view: GameStateView,
    ) -> EffectResult:
        ...  # pragma: no cover - 프로토콜


class UnimplementedResolver:
    """
    지금 엔진의 **유일한 실행기.** 언제나 실패를 돌려주고 판을 바꾸지 않는다.

    자리표시가 아니다. 등록된 효과 구현이 하나도 없다는 것이 지금의 사실이고,
    이것이 그 사실을 정직하게 표현한다. 덕분에 계약이 지켜지는지 실제로
    테스트할 수 있다.
    """

    __slots__ = ("_lookup",)

    def __init__(self, lookup=None):
        self._lookup = lookup

    def resolve(
        self,
        definition: EffectDefinition,
        context: ResolutionContext,
        view: GameStateView,
    ) -> EffectResult:
        """
        계약대로 판정만 하고 **아무것도 바꾸지 않는다.**

        문맥이 정의와 다른 효과를 가리키면 그것부터 거부한다 — 그 상태에서
        무엇을 하든 잘못된 카드를 건드리게 된다.
        """
        if not isinstance(view, GameStateView):
            raise TypeError(
                "실행기는 GameStateView 만 받습니다. GameState 를 직접 넘기면 "
                "해결 계약이 판을 바꿀 수 있게 됩니다."
            )
        if context.effect_ref != definition.effect_ref:
            return EffectResult(
                ResolutionStatus.INVALID_CONTEXT,
                ValidationCode.EFFECT_REF_CARD_MISMATCH,
                f"문맥이 가리키는 효과({context.effect_ref})가 정의"
                f"({definition.effect_ref})와 다릅니다.",
            )
        availability = execution_availability(definition, self._lookup)
        if availability is ExecutionAvailability.FORBIDDEN_SOURCE:
            return EffectResult(
                ResolutionStatus.FORBIDDEN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "공식 텍스트에서 유추한 효과는 실행하지 않습니다 (ADR-004).",
                missing="executable implementation from official script",
            )
        if availability is ExecutionAvailability.UNVERIFIED:
            return EffectResult(
                ResolutionStatus.UNKNOWN,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "의미가 공식 근거에서 확인되지 않았습니다.",
                missing="verified semantics",
            )
        if availability is not ExecutionAvailability.EXECUTABLE:
            return EffectResult(
                ResolutionStatus.NOT_IMPLEMENTED,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{definition.effect_ref} 의 실행 구현이 등록되어 있지 "
                "않습니다.",
                missing="effect implementation registry (Phase 2-D-2)",
            )
        # 여기까지 오는 경우는 아직 없다 — 구현을 등록할 수단이 없기 때문이다.
        # 실제 실행은 Phase 2-D-2 의 실행기가 맡는다.
        return EffectResult(
            ResolutionStatus.NOT_IMPLEMENTED,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            "구현이 등록되어 있으나 이 실행기는 실행하지 않습니다 "
            "(Phase 2-D-1 은 계약만 정의합니다).",
            missing="effect executor (Phase 2-D-2)",
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<UnimplementedResolver>"


__all__ = [
    "ResolutionContext",
    "ResolutionStatus",
    "AppliedOperation",
    "EffectResult",
    "EffectResolver",
    "UnimplementedResolver",
]
