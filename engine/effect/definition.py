"""
EffectDefinition — "이 효과가 무엇을 요구하고 무엇을 하는가".

**불변**이고, 판을 읽지도 바꾸지도 않는다. 청사진이다.

    EffectDefinition
      ├ effect_ref        어느 효과인가 (card_id, ordinal)
      ├ activation        발동 조건        engine.condition
      ├ cost              비용             engine.cost
      ├ target            대상 규칙        engine.effect.target
      ├ operations        무엇을 하는가    engine.effect.operation
      └ provenance        어디서 왔는가

analysis.EffectSpec 과 다르다
-----------------------------
``core.card_model.EffectSpec`` 은 Lua 효과 블록을 **읽은 기록**이다 — 가변
dataclass 이고 ``index`` 가 Lua 변수명(``"e1"``)이며, 한 카드 안에서 중복된다
(실측 4,884장). 그것은 실행 identity 가 될 수 없다.

여기의 정의는 **실행 계약**이다. 불변이고, identity 가
:class:`~engine.ids.EffectRef` 이며, 조건 · 비용 · 대상 · 일을 실제 엔진
타입으로 들고 있다.

``analysis.EffectSpec`` → ``EffectDefinition`` 컴파일러는 **만들지 않았다.**
그 경계를 넘을 때 ``TEXT_DERIVED`` 차단을 다시 확인해야 한다
(``docs/phase2d1-effect-model.md``).

검증된 의미 ≠ 실행 가능
-----------------------
:class:`EffectProvenance` 가 "어디서 왔는가" 를, :func:`execution_availability`
가 "지금 실행할 수 있는가" 를 답한다. **둘은 다른 질문이다** (ADR-006).
공식 Lua 에서 나온 효과라도 구현이 등록되어 있지 않으면 실행할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from engine.condition import Condition
from engine.cost import CostGroup
from engine.effect.operation import Operation
from engine.effect.target import TargetSpec
from engine.ids import EffectRef


class EffectSource(str, Enum):
    """
    이 효과 정의가 **어디서 왔는가.**

    ``core.provenance.AnalysisStatus`` 와 나란한 개념이지만 같은 것이 아니다.
    그쪽은 카드 데이터의 성질이고, 이쪽은 **엔진이 들고 있는 이 정의**의
    성질이다. 사람이 손으로 쓴 구현은 카드 데이터에 없는 출처다.
    """

    OFFICIAL_LUA = "official_lua"
    """공식 카드 스크립트에서 구조화했다."""
    OFFICIAL_TEXT = "official_text"
    """
    공식 텍스트에서 유추했다 (``AnalysisStatus.TEXT_DERIVED``).
    **실행할 수 없다** (ADR-004).
    """
    HAND_WRITTEN = "hand_written"
    """사람이 작성했다. 검증 여부는 :attr:`EffectProvenance.verified` 가 따로 말한다."""
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: 실행 근거로 **절대 쓸 수 없는** 출처. ADR-004.
FORBIDDEN_SOURCES: frozenset[EffectSource] = frozenset({EffectSource.OFFICIAL_TEXT})


@dataclass(frozen=True, slots=True)
class EffectProvenance:
    """
    효과 정의의 출처 기록. **불변**이다.

    :attr:`verified` 는 "의미가 공식 근거에서 왔는가" 이지 "실행할 수 있는가"
    가 아니다. 둘을 한 값으로 합치면 ADR-006 이 무너진다.
    """

    source: EffectSource = EffectSource.UNKNOWN
    verified: bool = False
    """의미가 공식 근거(스크립트 · 텍스트 · 재정)에서 확인되었는가."""
    note: str = ""

    @property
    def is_forbidden(self) -> bool:
        """출처만으로 실행이 금지되는가. ``TEXT_DERIVED`` 가 여기다."""
        return self.source in FORBIDDEN_SOURCES

    @classmethod
    def official_lua(cls, note: str = "") -> "EffectProvenance":
        return cls(EffectSource.OFFICIAL_LUA, verified=True, note=note)

    @classmethod
    def text_derived(cls, note: str = "") -> "EffectProvenance":
        """
        공식 텍스트에서 유추했다. ``verified`` 가 참이어도 **실행은 금지**다 —
        텍스트가 실행 의미를 정하지 못하기 때문이다 (ADR-004).
        """
        return cls(EffectSource.OFFICIAL_TEXT, verified=True, note=note)

    @classmethod
    def hand_written(cls, verified: bool = False, note: str = "") -> "EffectProvenance":
        return cls(EffectSource.HAND_WRITTEN, verified=verified, note=note)

    def canonical_state(self) -> tuple:
        return (self.source.value, self.verified, self.note)

    def to_dict(self) -> dict:
        return {"source": self.source.value, "verified": self.verified, "note": self.note}

    def describe_ko(self) -> str:
        mark = "검증됨" if self.verified else "미검증"
        return f"{self.source.value}({mark})"


class EffectDefinitionError(ValueError):
    """정의의 **모양**이 틀렸다. 규칙 위반이 아니다."""


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """
    효과 하나의 불변 정의.

    ``effect_ref.card_id`` 와 :attr:`source_card_id` 는 **반드시 같다.**
    다르면 그 정의는 어느 카드의 효과인지 스스로 모순이므로 거부한다.
    """

    effect_ref: EffectRef
    source_card_id: int
    operations: tuple[Operation, ...] = ()
    activation: Condition | None = None
    """발동 조건. ``None`` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는 뜻**이다."""
    cost: CostGroup = field(default_factory=CostGroup)
    target: TargetSpec = field(default_factory=TargetSpec.none)
    provenance: EffectProvenance = field(default_factory=EffectProvenance)

    def __post_init__(self) -> None:
        if self.effect_ref.card_id != self.source_card_id:
            raise EffectDefinitionError(
                f"effect_ref 의 카드({self.effect_ref.card_id})가 "
                f"source_card_id({self.source_card_id})와 다릅니다. "
                "한 효과는 한 카드의 것입니다."
            )
        if not isinstance(self.operations, tuple):
            raise TypeError("operations 는 tuple 이어야 합니다 — 정의는 불변입니다.")

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def ordinal(self) -> int:
        """카드 안에서 몇 번째 효과인가. ``EffectSpec.index`` 가 아니다."""
        return self.effect_ref.ordinal

    @property
    def has_cost(self) -> bool:
        return not self.cost.is_free

    @property
    def requires_target(self) -> bool:
        return self.target.requires_selection

    @property
    def is_described(self) -> bool:
        """
        무엇을 하는지 하나라도 적혀 있는가.

        거짓이면 **효과가 없다는 뜻이 아니라** 아직 적지 않았다는 뜻이다.
        """
        return bool(self.operations)

    def canonical_state(self) -> tuple:
        return (
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.source_card_id,
            tuple(op.canonical_state() for op in self.operations),
            self.activation.canonical_state() if self.activation is not None else None,
            self.cost.canonical_state(),
            self.target.canonical_state(),
            self.provenance.canonical_state(),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "source_card_id": self.source_card_id,
            "operations": [op.to_dict() for op in self.operations],
            "cost": self.cost.to_dict(),
            "target": self.target.to_dict(),
            "provenance": self.provenance.to_dict(),
        }
        if self.activation is not None:
            data["activation"] = self.activation.to_dict()
        return data

    def describe_ko(self) -> str:
        parts = [str(self.effect_ref)]
        if self.has_cost:
            parts.append(f"비용: {self.cost.describe_ko()}")
        if self.activation is not None:
            parts.append(f"조건: {self.activation.describe_ko()}")
        if self.requires_target:
            parts.append(f"대상: {self.target.describe_ko()}")
        if self.operations:
            parts.append(
                "효과: " + ", ".join(op.describe_ko() for op in self.operations)
            )
        return " / ".join(parts)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 실행 가능성 — 출처와 다른 질문이다
# ======================================================================


class ExecutionAvailability(str, Enum):
    """
    **지금 이 엔진 빌드가** 이 효과를 실행할 수 있는가.

    카드 데이터에 저장하지 않는다 (ADR-006). 구현 등록 상태에 따라 달라지므로
    저장하면 반드시 낡는다.
    """

    EXECUTABLE = "executable"
    """검증된 의미 + 등록된 구현. **이때만 실행해도 된다.**"""
    NO_IMPLEMENTATION = "no_implementation"
    """의미는 검증되었으나 구현이 등록되어 있지 않다."""
    FORBIDDEN_SOURCE = "forbidden_source"
    """출처가 실행을 금지한다 (``TEXT_DERIVED``). 구현이 있어도 실행하지 않는다."""
    UNVERIFIED = "unverified"
    """의미가 공식 근거에서 확인되지 않았다."""
    UNKNOWN = "unknown"

    @property
    def permits_execution(self) -> bool:
        """
        실행해도 되는가. **``EXECUTABLE`` 일 때만 참이다.**

        ``if availability is not FORBIDDEN_SOURCE:`` 같은 코드로 나머지가
        허가로 새어 나가는 것을 막는다.
        """
        return self is ExecutionAvailability.EXECUTABLE


@runtime_checkable
class EffectImplementationLookup(Protocol):
    """
    ``EffectRef`` 로 구현을 찾을 수 있는가를 답하는 것.

    **레지스트리 자체는 이번 단계에서 만들지 않는다** (Phase 2-D-2).
    실행 가능성 판정이 무엇에 의존하는지만 계약으로 고정한다.
    """

    def has_implementation(self, effect_ref: EffectRef) -> bool:
        """이 효과의 실행 구현이 등록되어 있는가."""
        ...  # pragma: no cover - 프로토콜


class EmptyImplementationLookup:
    """
    구현이 **하나도 없는** 조회기. 지금 엔진의 실제 상태다.

    Phase 2-D-2 가 실제 레지스트리를 넣기 전까지, 어떤 효과도 실행 가능
    상태가 되지 않는다는 것을 이것이 보장한다.
    """

    __slots__ = ()

    def has_implementation(self, effect_ref: EffectRef) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<EmptyImplementationLookup>"


def execution_availability(
    definition: EffectDefinition,
    lookup: EffectImplementationLookup | None = None,
) -> ExecutionAvailability:
    """
    이 효과를 지금 실행할 수 있는가.

    순서가 중요하다. **출처 금지가 가장 먼저**다 — 구현이 등록되어 있어도
    ``TEXT_DERIVED`` 는 실행하지 않는다 (ADR-004).

    ``lookup`` 을 주지 않으면 :class:`EmptyImplementationLookup` 을 쓴다.
    "아무것도 등록되어 있지 않다" 가 지금의 사실이므로 그것이 올바른 기본값이다.
    """
    provenance = definition.provenance
    if provenance.is_forbidden:
        return ExecutionAvailability.FORBIDDEN_SOURCE
    if not provenance.verified:
        return ExecutionAvailability.UNVERIFIED
    if provenance.source is EffectSource.UNKNOWN:
        return ExecutionAvailability.UNKNOWN
    resolved = lookup if lookup is not None else EmptyImplementationLookup()
    if not resolved.has_implementation(definition.effect_ref):
        return ExecutionAvailability.NO_IMPLEMENTATION
    return ExecutionAvailability.EXECUTABLE


__all__ = [
    "EffectSource",
    "FORBIDDEN_SOURCES",
    "EffectProvenance",
    "EffectDefinitionError",
    "EffectDefinition",
    "ExecutionAvailability",
    "EffectImplementationLookup",
    "EmptyImplementationLookup",
    "execution_availability",
]
