"""
EffectDefinition — "이 효과가 무엇을 요구하고 무엇을 하는가".

**불변**이고, 판을 읽지도 바꾸지도 않는다. 청사진이다.

    EffectDefinition
      ├ effect_ref        어느 효과인가 (card_id, ordinal)
      ├ activation        발동 조건        engine.condition
      ├ cost              비용             engine.cost
      ├ targets           대상 규칙 (이름별)  engine.effect.target
      ├ operations        무엇을 하는가    engine.effect.operation
      └ provenance        어디서 왔는가

하는 일이 어느 대상을 쓰는지 말한다
------------------------------------
대상 규칙과 하는 일을 따로 두면 "대상으로 지정한 몬스터 1장을 파괴한다" 를
표현할 수 없다. 그래서 대상에 **이름**을 붙이고 일이 그 이름을 가리킨다.

    targets    = (TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(...)),)
    operations = (CardOperation.destroy(PRIMARY_TARGET),)

이름이 정의에 없으면 생성 단계에서 거부한다 — 그 일은 존재하지 않는 대상을
가리키고 있으므로 해결할 수 없다.

**실제로 골라진 카드는 여기 없다.** 정의는 "무엇을 대상으로 하는가" 이고,
"이번에 무엇이 골라졌는가" 는 :class:`~engine.effect.resolution.
ResolutionContext` 다. 정의에 ``InstanceId`` 를 박으면 그 정의는 한 판에서
한 번밖에 쓸 수 없다.

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
from engine.effect.target import CountKind, TargetBinding, TargetRef
from engine.execution import DeclarationBinding, ValueRef
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


def _counts_of(operation) -> tuple:
    """
    그 조작이 들고 있는 :class:`~engine.effect.target.SelectionCount` 들.

    ``isinstance`` 사슬을 만들지 않으려고 **값이 있는지**만 본다. 새 조작이
    수를 갖게 되면 이름만 ``count`` 로 맞추면 여기 걸린다.
    """
    value = getattr(operation, "count", None)
    if hasattr(value, "kind") and hasattr(value, "resolve"):
        return (value,)
    return ()


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
    targets: tuple[TargetBinding, ...] = ()
    """이름별 대상 규칙. 하는 일이 이 이름을 가리킨다."""
    declarations: tuple[DeclarationBinding, ...] = ()
    """
    이름별 **수 선언** 규칙 (Phase 2-AD).

    ``targets`` 와 **다른 이름 공간**이다 — 저쪽은 고른 카드이고 이쪽은
    선언한 수다. 하나로 합치면 "2장" 과 "2" 가 같은 이름표를 달게 된다.
    """
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
        if not isinstance(self.targets, tuple):
            raise TypeError("targets 는 tuple 이어야 합니다 — 정의는 불변입니다.")
        if not isinstance(self.declarations, tuple):
            raise TypeError(
                "declarations 는 tuple 이어야 합니다 — 정의는 불변입니다."
            )
        self._check_target_links()
        self._check_value_links()

    def _check_target_links(self) -> None:
        """
        이름과 일이 실제로 이어지는지 본다.

        세 가지를 거부한다.

        1. 같은 이름을 두 번 선언했다 — 어느 규칙인지 정해지지 않는다.
        2. 일이 **없는 이름**을 가리킨다 — 해결할 수 없다.
        3. 선언한 대상을 **아무 일도 쓰지 않는다** — 고르게 해 놓고 쓰지
           않는 정의다. 단, 하는 일을 아직 적지 않았으면(``operations`` 가
           비었으면) 넘어간다. 그것은 "미완성" 이지 "모순" 이 아니다.
        """
        declared: set[TargetRef] = set()
        for binding in self.targets:
            if binding.ref in declared:
                raise EffectDefinitionError(
                    f"대상 이름 {binding.ref} 가 두 번 선언되었습니다."
                )
            declared.add(binding.ref)

        used: set[TargetRef] = set()
        for operation in self.operations:
            for ref in operation.target_refs:
                if ref not in declared:
                    raise EffectDefinitionError(
                        f"{operation.kind.value} 가 선언되지 않은 대상 {ref} 를 "
                        f"가리킵니다. 선언된 것: "
                        f"{sorted(r.name for r in declared) or '없음'}"
                    )
                used.add(ref)

        if self.operations:
            unused = declared - used
            if unused:
                raise EffectDefinitionError(
                    f"선언한 대상 {sorted(r.name for r in unused)} 를 아무 일도 "
                    "쓰지 않습니다. 고르게 해 놓고 쓰지 않는 정의입니다."
                )

    def _check_value_links(self) -> None:
        """
        실행 중에 생기는 **수**의 이름이 실제로 이어지는지 본다 (Phase 2-AD).

        네 가지를 거부한다.

        1. 같은 이름을 두 번 선언했다.
        2. 없는 이름의 수를 쓴다.
        3. 선언해 놓고 아무 일도 쓰지 않는다 — 사람에게 수를 묻고 버리는
           정의다.
        4. **뒤의 조작을 가리킨다.** 아직 일어나지 않은 일의 결과를 읽을
           수는 없다. 자기 자신을 가리키는 것도 같은 이유로 막는다.

        네 번째가 이 검사의 핵심이다. "바로 앞" 같은 암묵적 지시를 두지
        않는 대신, 번호가 **앞**을 가리키는지를 정의를 만들 때 못박는다.
        """
        declared: set[ValueRef] = set()
        for binding in self.declarations:
            if binding.ref in declared:
                raise EffectDefinitionError(
                    f"수 이름 {binding.ref} 가 두 번 선언되었습니다."
                )
            declared.add(binding.ref)

        used: set[ValueRef] = set()
        for index, operation in enumerate(self.operations):
            for count in self._counts_used_by(operation):
                if count.kind is CountKind.DECLARED:
                    if count.declared not in declared:
                        raise EffectDefinitionError(
                            f"{operation.kind.value} 가 선언되지 않은 수 "
                            f"{count.declared} 를 씁니다. 선언된 것: "
                            f"{sorted(r.name for r in declared) or '없음'}"
                        )
                    used.add(count.declared)
                elif count.kind is CountKind.FROM_RESULT:
                    target = count.result.operation_index
                    if target >= index:
                        raise EffectDefinitionError(
                            f"{index}번 조작이 {target}번 조작의 결과를 "
                            "가리킵니다. 앞선 일만 읽을 수 있습니다 — 아직 "
                            "일어나지 않은 일에는 결과가 없습니다."
                        )

        if self.operations:
            unused = declared - used
            if unused:
                raise EffectDefinitionError(
                    f"선언하게 한 수 {sorted(r.name for r in unused)} 를 아무 "
                    "일도 쓰지 않습니다. 묻고 버리는 정의입니다."
                )

    def _counts_used_by(self, operation) -> tuple:
        """
        그 일이 **실제로 묻게 되는** 수들.

        두 곳에서 온다. 일이 직접 들고 있는 매수(드로우)와, 일이 가리키는
        **대상 규칙**이 들고 있는 장수(무작위 선택)다. 뒤쪽을 빼먹으면
        "선언하게 해 놓고 안 쓴다" 가 거짓으로 걸린다.
        """
        found = list(_counts_of(operation))
        for ref in operation.target_refs:
            for binding in self.targets:
                if binding.ref != ref:
                    continue
                choice = getattr(binding.spec, "choice", None)
                count = getattr(choice, "count", None)
                if hasattr(count, "kind") and hasattr(count, "resolve"):
                    found.append(count)
        return tuple(found)

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
        """대상을 하나라도 선언했는가."""
        return bool(self.targets)

    @property
    def target_refs(self) -> tuple[TargetRef, ...]:
        """선언된 대상 이름들. 선언 순서 그대로다."""
        return tuple(binding.ref for binding in self.targets)

    def target_spec(self, ref: TargetRef):
        """
        그 이름의 대상 규칙. 없으면 :class:`KeyError`.

        조용히 ``None`` 을 돌려주지 않는다 — 없는 이름을 묻는 것은 정의와
        해결이 어긋났다는 뜻이고, 그것은 감춰야 할 일이 아니다.
        """
        for binding in self.targets:
            if binding.ref == ref:
                return binding.spec
        raise KeyError(f"{ref} 는 이 정의에 선언되어 있지 않습니다.")

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
            tuple(b.canonical_state() for b in self.targets),
            tuple(b.canonical_state() for b in self.declarations),
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
            "targets": [b.to_dict() for b in self.targets],
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
            parts.append(
                "대상: " + ", ".join(b.describe_ko() for b in self.targets)
            )
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


@runtime_checkable
class EffectDefinitionSource(Protocol):
    """
    ``EffectRef`` 로 **정의**를 찾을 수 있는 것.

    :class:`EffectImplementationLookup` 과 **다른 질문**이다.

    =============================  ====================================
    ``EffectDefinitionSource``      이 효과가 무엇을 하는지 적혀 있는가
    ``EffectImplementationLookup``  그것을 실행해도 되는가
    =============================  ====================================

    정의를 찾을 수 있다고 실행할 수 있는 것이 아니다 (ADR-006). 둘을 한
    인터페이스로 합치면 그 구분이 무너진다.
    """

    def definition_for(self, effect_ref: EffectRef) -> "EffectDefinition | None":
        """그 효과의 정의. **없으면 ``None``.**"""
        ...  # pragma: no cover - 프로토콜


class EffectDefinitionRegistry:
    """
    손으로 등록한 정의 목록.

    ``analysis`` → :class:`EffectDefinition` 컴파일러는 **아직 없다**
    (STRUCTURAL-7). 그 경계를 넘을 때 ``TEXT_DERIVED`` 차단을 다시 확인해야
    하므로, 그때까지 정의는 손으로 등록한다. 자동 생성이 아니라는 것이
    지금의 사실이고 이것이 그 사실을 정직하게 표현한다.

    **등록은 실행 허가가 아니다.** 실행에는 구현 등록
    (:class:`EffectImplementationLookup`) 이 따로 필요하고, 출처가
    ``TEXT_DERIVED`` 면 그마저도 소용없다.
    """

    __slots__ = ("_definitions",)

    def __init__(self, definitions: "tuple[EffectDefinition, ...] | None" = None):
        self._definitions: dict[EffectRef, EffectDefinition] = {}
        for definition in definitions or ():
            self.register(definition)

    def register(self, definition: "EffectDefinition") -> "EffectDefinitionRegistry":
        """
        정의를 등록한다. 같은 ``EffectRef`` 를 두 번 등록하면 거부한다 —
        조용히 덮어쓰면 어느 정의가 실행되는지 알 수 없게 된다.
        """
        if definition.effect_ref in self._definitions:
            raise EffectDefinitionError(
                f"{definition.effect_ref} 의 정의가 이미 등록되어 있습니다."
            )
        self._definitions[definition.effect_ref] = definition
        return self

    def definition_for(self, effect_ref: EffectRef) -> "EffectDefinition | None":
        return self._definitions.get(effect_ref)

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, effect_ref: object) -> bool:
        return effect_ref in self._definitions

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EffectDefinitionRegistry n={len(self._definitions)}>"


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
    "EffectDefinitionSource",
    "EffectDefinitionRegistry",
    "EffectImplementationLookup",
    "EmptyImplementationLookup",
    "execution_availability",
]
