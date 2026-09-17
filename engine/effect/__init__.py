"""
효과 모델과 해결 계약 (Phase 2-D-1).

    EffectDefinition                    무엇을 요구하고 무엇을 하는가
      ├ activation   engine.condition   발동 조건
      ├ cost         engine.cost        비용
      ├ target       TargetSpec         대상 규칙
      ├ operations   Operation          무엇을 하는가
      └ provenance   EffectProvenance   어디서 왔는가
              ↓
    ResolutionContext                   누가 · 무엇을 골랐는가
              ↓  EffectResolver.resolve()  ← **계약만 있다**
    EffectResult

**아무것도 실행하지 않는다.** 지금 있는 실행기
(:class:`UnimplementedResolver`)는 언제나 실패를 돌려주고 판을 바꾸지 않는다 —
등록된 효과 구현이 하나도 없다는 사실을 그대로 표현한다.

지키는 구분
-----------
``EffectDefinition`` ≠ ``analysis.EffectSpec`` ·
``Operation`` ≠ ``PlayerAction`` · ``Cost`` ≠ ``CostPayment`` ·
검증된 의미 ≠ 실행 가능 · 파괴 ≠ 묘지로 보내기 ≠ 릴리스.

자세한 것은 ``docs/phase2d1-effect-model.md``.
"""

from engine.effect.definition import (
    FORBIDDEN_SOURCES,
    EffectDefinition,
    EffectDefinitionError,
    EffectImplementationLookup,
    EffectProvenance,
    EffectSource,
    EmptyImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.operation import (
    CARD_OPERATION_KINDS,
    REASON_NAMES,
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    Operation,
    OperationKind,
    UnimplementedOperation,
)
from engine.effect.resolution import (
    EffectResolver,
    EffectResult,
    ResolutionContext,
    ResolutionStatus,
    UnimplementedResolver,
)
from engine.effect.target import TargetRequirement, TargetSpec

__all__ = [
    # 정의
    "EffectDefinition",
    "EffectDefinitionError",
    "EffectProvenance",
    "EffectSource",
    "FORBIDDEN_SOURCES",
    # 실행 권위
    "ExecutionAvailability",
    "EffectImplementationLookup",
    "EmptyImplementationLookup",
    "execution_availability",
    # 하는 일
    "Operation",
    "OperationKind",
    "CardOperation",
    "DrawOperation",
    "LifeChangeOperation",
    "UnimplementedOperation",
    "REASON_NAMES",
    "CARD_OPERATION_KINDS",
    # 대상
    "TargetSpec",
    "TargetRequirement",
    # 해결 계약
    "ResolutionContext",
    "ResolutionStatus",
    "EffectResult",
    "EffectResolver",
    "UnimplementedResolver",
]
