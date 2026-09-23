"""
효과를 **실행하는 동안에만** 사는 값들 (Phase 2-AD).

    플레이어가 선언한 수      DeclaredNumber
    앞선 조작이 낸 결과       OperationResult
        ↓  이름으로 가리킨다
    ExecutionValues          이번 해결 한 번 동안만 산다

판이 아니다
-----------
여기 있는 값은 **어느 것도** :class:`~engine.state.game_state.GameState` 에
들어가지 않는다. "상대가 2를 선언했다" 는 판의 모양이 아니라 지금 해결의
중간 상태이고, 해결이 끝나면 남는 것은 그 선언이 **일으킨 변화**뿐이다.

그래서 ``state_hash`` 도 움직이지 않는다 — 흐름의 위치를 판에서 뺀 것과
같은 이유다 (``EventJournal`` · ``PriorityState`` · ``Chain`` · 난수원의
위치).

네 가지를 뭉개지 않는다
-----------------------
========================  ==================================================
플레이어가 고른 카드         ``ChoiceSpec`` → ``Selection``      (Phase 2-N)
무작위가 고른 카드           ``RandomSelectionSpec``             (Phase 2-AB)
플레이어가 **선언한 수**     ``DeclaredNumberSpec`` → 여기        (Phase 2-AD)
조작이 **낸 결과**           ``OperationResult``  → 여기          (Phase 2-AD)
========================  ==================================================

앞의 둘은 "무엇을" 이고 뒤의 둘은 "얼마나" 다. 뒤의 둘끼리도 다르다 —
하나는 사람이 정했고 하나는 판이 정했다.

가리키는 것은 언제나 **이름**이다
---------------------------------
"바로 앞의 조작" 같은 암묵적 지시를 만들지 않는다. 앞의 조작을 쓰려면
**몇 번째 조작인지 적어야** 하고, 정의를 만들 때 그 번호가 자기보다
앞인지 검사한다. 마지막 결과를 자동으로 집어 오면, 정의에 일을 하나 끼워
넣는 순간 조용히 다른 수가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import ConditionContext, PlayerRef


@dataclass(frozen=True, slots=True)
class ValueRef:
    """
    실행 중에 생기는 **수**의 이름.

    :class:`~engine.effect.target.TargetRef` 와 **다른 타입**이다. 저쪽은
    고른 카드의 이름이고 이쪽은 선언한 수의 이름이다 — 같은 타입으로
    만들면 "2장" 과 "2" 가 한 이름 공간에 섞인다.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("값의 이름이 비어 있습니다.")

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"#{self.name}"


#: 수를 하나만 선언하는 효과가 쓰는 이름.
DECLARED_NUMBER = ValueRef("declared")


@dataclass(frozen=True, slots=True)
class NumberDomain:
    """
    선언할 수 있는 **수의 집합.**

    목록이다. 범위가 아니다 — 공식 스크립트의
    ``Duel.AnnounceNumber(tp, ...)`` 가 **고를 수 있는 수를 하나하나
    나열한다**\\ 는 사실을 그대로 옮긴 것이다.

    ::

        Duel.AnnounceNumber(p,1,2)      → {1, 2}
        Duel.AnnounceNumber(p,1,2,3)    → {1, 2, 3}
        Duel.AnnounceNumber(tp,100,200,300,400,500)

    :meth:`between` 은 연속한 수를 적는 **줄임말**이지 다른 종류가 아니다.
    범위와 목록을 다른 갈래로 두면 "1~3" 과 "{1,2,3}" 이 서로 다른 것처럼
    보이는데, 스크립트에서 둘은 같은 것이다.
    """

    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError("values 는 tuple 이어야 합니다 — 명세는 불변입니다.")
        if not self.values:
            raise ValueError(
                "선언할 수 있는 수가 하나도 없습니다. 고를 것이 없으면 "
                "선언이 아니라 조건입니다."
            )
        if len(set(self.values)) != len(self.values):
            raise ValueError(f"같은 수가 두 번 있습니다: {self.values}")
        if sorted(self.values) != list(self.values):
            raise ValueError(
                f"수는 오름차순으로 적습니다: {self.values}. 순서가 다르면 "
                "같은 집합이 여러 모양으로 적히고, 정규 표현이 흔들립니다."
            )

    @classmethod
    def exact(cls, value: int) -> "NumberDomain":
        """고를 것이 하나뿐이다. **그래도 선언이다** — 사람이 정한다."""
        return cls((value,))

    @classmethod
    def between(cls, low: int, high: int) -> "NumberDomain":
        """``low`` 부터 ``high`` 까지 연속한 수. 목록을 적는 줄임말이다."""
        if high < low:
            raise ValueError(f"끝({high})이 시작({low})보다 작습니다.")
        return cls(tuple(range(low, high + 1)))

    @classmethod
    def of(cls, *values: int) -> "NumberDomain":
        return cls(tuple(values))

    def allows(self, value: int) -> bool:
        return value in self.values

    @property
    def only(self) -> "int | None":
        """고를 것이 하나뿐이면 그 수. 아니면 ``None``."""
        return self.values[0] if len(self.values) == 1 else None

    def canonical_state(self) -> tuple:
        return self.values

    def to_dict(self) -> dict:
        return {"values": list(self.values)}

    def describe_ko(self) -> str:
        return "{" + ", ".join(str(v) for v in self.values) + "} 중 하나"

    def __contains__(self, value: int) -> bool:
        return self.allows(value)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class DeclaredNumberSpec:
    """
    "누가 어떤 수를 선언하는가" 라는 **요구.** 선언된 값이 아니다.

    ``chooser`` 는 기존 어휘 그대로 :class:`~engine.condition.PlayerRef`
    다 (``ChoiceSpec.chooser`` 와 같은 뜻, 같은 해석). 그래서 **효과의
    컨트롤러가 아닌 사람이 선언하는 것**을 적을 수 있다 — 부작용?
    (30922149)에서 수를 정하는 것은 뽑는 쪽, 즉 상대다.
    """

    domain: NumberDomain
    chooser: PlayerRef = PlayerRef.CONTROLLER

    def canonical_state(self) -> tuple:
        return (self.domain.canonical_state(), self.chooser.value)

    def to_dict(self) -> dict:
        return {"domain": self.domain.to_dict(), "chooser": self.chooser.value}

    def describe_ko(self) -> str:
        return f"{self.chooser} 가 {self.domain.describe_ko()} 를 선언"


@dataclass(frozen=True, slots=True)
class DeclarationBinding:
    """이름과 선언 규칙을 잇는다 (``TargetBinding`` 과 같은 자리)."""

    ref: ValueRef
    spec: DeclaredNumberSpec

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.spec.canonical_state())

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "spec": self.spec.to_dict()}


@dataclass(frozen=True, slots=True)
class DeclaredNumber:
    """
    플레이어가 **실제로 선언한 수** (``TargetSelection`` 과 같은 자리).

    규칙이 아니라 입력이다. 그래서 정의가 아니라 문맥으로 들어온다.
    """

    ref: ValueRef
    value: int

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.value)

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "value": self.value}


class DeclarationOutcome(str, Enum):
    """선언을 물어본 결과."""

    RESOLVED = "resolved"
    PENDING = "pending"
    """**아직 선언하지 않았다.** 대신 정해 주지 않는다."""
    INVALID = "invalid"
    """허용되지 않은 수를 선언했다. **가까운 수로 고쳐 주지 않는다.**"""
    # FORBIDDEN 은 여기 없다. 출처가 실행을 금지하는 것(``TEXT_DERIVED``)은
    # 선언의 문제가 아니라 효과의 문제이고, 실행기가 계획을 시작하기 전에
    # 이미 ``ResolutionStatus.FORBIDDEN`` 으로 답한다 (ADR-004).


@dataclass(frozen=True, slots=True)
class ResolvedDeclaration:
    """물어본 결과. ``RESOLVED`` 일 때만 수가 있다."""

    outcome: DeclarationOutcome
    value: "int | None" = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.outcome is DeclarationOutcome.RESOLVED) is not (
            self.value is not None
        ):
            raise ValueError(
                "RESOLVED 일 때만 수가 있습니다. 정해지지 않은 수를 숫자로 "
                "적으면 그 숫자가 규칙이 됩니다."
            )

    def __bool__(self):  # pragma: no cover - 부르면 안 된다
        raise TypeError(
            "ResolvedDeclaration 을 참/거짓으로 쓰지 마십시오. PENDING 이 "
            "거짓이 되면 '아직 안 정했다' 가 '안 된다' 로 접힙니다."
        )


class ResultField(str, Enum):
    """앞선 조작에서 **무엇을** 가져오는가."""

    AFFECTED_COUNT = "affected_count"
    """
    그 조작이 실제로 다룬 **수.**

    카드를 옮기는 일이면 장수, 드로우면 뽑은 장수다. 라이프 증감처럼
    "장수" 가 없는 일에는 **없다** — 없는 것을 0 으로 답하지 않는다.
    """
    # SUCCEEDED 를 **일부러 만들지 않았다.** 이 실행기는 계획이 전부
    # 끝난 뒤에야 적용을 시작하므로, 앞의 조작이 실패하면 뒤의 조작은
    # 아예 시작되지 않는다. "앞이 성공했는가" 를 뒤에서 물을 수 있는
    # 순간이 존재하지 않는다. 있지도 않은 질문에 칸을 만들면, 언제나
    # 참인 값을 읽고 규칙을 지켰다고 믿게 된다.


@dataclass(frozen=True, slots=True)
class ResultRef:
    """
    **몇 번째 조작의 무엇**을 가져오는가.

    ``operation_index`` 는 정의의 ``operations`` 안 자리다. 새 식별자
    체계를 만들지 않은 이유는, 정의가 불변이므로 그 자리가 이미 그
    조작의 신원이기 때문이다.

    자기보다 **앞**을 가리켜야 한다는 것을
    :class:`~engine.effect.definition.EffectDefinition` 이 만들 때
    검사한다 — 뒤를 가리키면 아직 일어나지 않은 일을 읽는 셈이다.
    """

    operation_index: int
    field: ResultField = ResultField.AFFECTED_COUNT
    multiplier: int = 1
    """
    가져온 수에 곱한다. 실제 카드가 ``dr*2000`` 처럼 쓰기 때문이고
    (부작용? 30922149), 그 이상은 하지 않는다 — 수식 언어가 아니다.
    """

    def __post_init__(self) -> None:
        if self.operation_index < 0:
            raise ValueError(
                f"조작 번호는 0 이상입니다: {self.operation_index}"
            )

    def canonical_state(self) -> tuple:
        return (self.operation_index, self.field.value, self.multiplier)

    def to_dict(self) -> dict:
        data: dict = {
            "operation_index": self.operation_index,
            "field": self.field.value,
        }
        if self.multiplier != 1:
            data["multiplier"] = self.multiplier
        return data

    def describe_ko(self) -> str:
        times = f" x{self.multiplier}" if self.multiplier != 1 else ""
        return f"{self.operation_index}번 조작의 {self.field.value}{times}"


@dataclass(frozen=True, slots=True)
class OperationResult:
    """
    조작 하나가 **낸 결과.** 사건이 아니다.

    :class:`~engine.effect.delta.StateDelta` 나
    :class:`~engine.event_pipeline.ObservedEvent` 와 **다른 것**이다.

    ==================  ==============================================
    ``OperationResult``  그 일이 무엇을 얼마나 했는가 — 해결 중의 참조용
    ``StateDelta``       판의 어디가 어떻게 바뀌었는가
    ``ObservedEvent``    무슨 사건이 일어났는가 — 기록과 반응용
    ==================  ==============================================

    앞의 일을 뒤의 일이 읽어야 할 때 ``EventJournal`` 을 뒤지지 않는
    이유가 이것이다. 저널은 **역사**이고 여기는 **지금 해결의 중간
    결과**다. 역사를 뒤져서 수를 짐작하면, 같은 효과가 두 번 돌았을 때
    어느 것을 읽었는지 알 수 없다.
    """

    operation_index: int
    affected_count: "int | None" = None

    def value_of(self, field: ResultField) -> "int | None":
        if field is ResultField.AFFECTED_COUNT:
            return self.affected_count
        raise KeyError(f"{field} 는 결과에 없는 칸입니다.")  # pragma: no cover

    def canonical_state(self) -> tuple:
        return (self.operation_index, self.affected_count)

    def to_dict(self) -> dict:
        return {
            "operation_index": self.operation_index,
            "affected_count": self.affected_count,
        }


class ExecutionLookupError(LookupError):
    """실행 중의 값을 이름으로 찾지 못했다. **0 으로 때우지 않는다.**"""


@dataclass(frozen=True, slots=True)
class ExecutionValues:
    """
    이번 해결 **한 번** 동안의 값들.

    불변이다. 조작을 계획할 때마다 결과가 하나씩 붙은 **새 값**이 생기고,
    앞의 값은 그대로 남는다 — 누가 언제 무엇을 읽었는지가 값에 남는다.

    복제와 독립은 따로 지킬 것이 없다. 이 값은 판에 붙어 있지 않고
    :meth:`~engine.effect.executor.EffectExecutor.execute` 한 번 안에서만
    살기 때문이다.
    """

    declarations: tuple[DeclaredNumber, ...] = ()
    results: tuple[OperationResult, ...] = ()

    def with_result(self, result: OperationResult) -> "ExecutionValues":
        """결과 하나를 더한 **새** 값."""
        return ExecutionValues(self.declarations, self.results + (result,))

    def declared(
        self, ref: ValueRef, spec: "DeclaredNumberSpec | None" = None
    ) -> ResolvedDeclaration:
        """
        그 이름으로 선언된 수.

        ``spec`` 을 주면 허용된 수인지까지 본다. 주지 않으면 **검사하지
        않았다는 뜻**이지 통과했다는 뜻이 아니다.
        """
        found = [d for d in self.declarations if d.ref == ref]
        if not found:
            return ResolvedDeclaration(
                DeclarationOutcome.PENDING,
                reason=f"{ref} 를 아직 선언하지 않았습니다.",
            )
        if len(found) > 1:
            return ResolvedDeclaration(
                DeclarationOutcome.INVALID,
                reason=f"{ref} 에 수가 두 번 들어왔습니다.",
            )
        value = found[0].value
        if spec is not None and not spec.domain.allows(value):
            return ResolvedDeclaration(
                DeclarationOutcome.INVALID,
                reason=(
                    f"{ref} 에 {value} 를 선언했는데 고를 수 있는 것은 "
                    f"{spec.domain.describe_ko()} 입니다."
                ),
            )
        return ResolvedDeclaration(DeclarationOutcome.RESOLVED, value=value)

    def result(self, ref: ResultRef) -> int:
        """
        그 조작이 낸 수. 없으면 :class:`ExecutionLookupError`.

        조용히 0 을 돌려주지 않는다 — "아무것도 안 했다" 와 "그 일이
        아직 없다" 는 다른 사실이고, 전자를 후자로 읽으면 뒤의 일이
        0장을 다룬 척 지나간다.
        """
        for result in self.results:
            if result.operation_index == ref.operation_index:
                value = result.value_of(ref.field)
                if value is None:
                    raise ExecutionLookupError(
                        f"{ref.operation_index}번 조작에는 "
                        f"{ref.field.value} 가 없습니다."
                    )
                return value * ref.multiplier
        raise ExecutionLookupError(
            f"{ref.operation_index}번 조작의 결과가 아직 없습니다."
        )

    def chooser_of(
        self, spec: DeclaredNumberSpec, context: ConditionContext
    ) -> int:
        """수를 선언하는 사람. 기존 ``PlayerRef`` 해석을 그대로 쓴다."""
        return spec.chooser.resolve(context)

    def canonical_state(self) -> tuple:
        return (
            tuple(d.canonical_state() for d in self.declarations),
            tuple(r.canonical_state() for r in self.results),
        )

    def to_dict(self) -> dict:
        return {
            "declarations": [d.to_dict() for d in self.declarations],
            "results": [r.to_dict() for r in self.results],
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<ExecutionValues 선언 {len(self.declarations)} "
            f"결과 {len(self.results)}>"
        )


#: 실행 중에 생긴 값이 **하나도 없는** 상태.
#:
#: ``None`` 을 쓰지 않는 이유는, 없는 것과 "모른다" 를 구별하기 위해서다 —
#: 이 값에 선언을 물으면 ``PENDING`` 이 나오고, 그것이 사실이다.
NO_EXECUTION_VALUES = ExecutionValues()


__all__ = [
    "ValueRef",
    "DECLARED_NUMBER",
    "NumberDomain",
    "DeclaredNumberSpec",
    "DeclarationBinding",
    "DeclaredNumber",
    "DeclarationOutcome",
    "ResolvedDeclaration",
    "ResultField",
    "ResultRef",
    "OperationResult",
    "ExecutionValues",
    "ExecutionLookupError",
    "NO_EXECUTION_VALUES",
]
