"""
효과 모델과 해결 계약 (Phase 2-D-1).

    EffectDefinition                    무엇을 요구하고 무엇을 하는가
      ├ activation   engine.condition   발동 조건
      ├ cost         engine.cost        비용
      ├ targets      TargetBinding      대상 규칙 (이름별)
      ├ operations   Operation          무엇을 하는가
      └ provenance   EffectProvenance   어디서 왔는가
              ↓
    ResolutionContext                   누가 · 무엇을 골랐는가
              ↓  EffectResolver.resolve()  ← **계약만 있다**
    EffectResult

**실행은 :class:`EffectExecutor` 하나만 한다** (Phase 2-D-2). 그것도
등록된 구현이 있고, 조건이 참이고, 대상이 다 풀렸을 때만이다.
:class:`UnimplementedResolver` 는 계약을 보여주는 쪽으로 남아 있다.

실행이 판을 바꾸면 그 변화를 :class:`StateDelta` 로 남기고, 받아 둔
:class:`EventJournal` 에 사건으로 적는다 (Phase 2-D-3). 기록은 판을 바꾸지
않는다 — 되돌리기도 재생도 여기 없다 (ADR-008).

지키는 구분
-----------
``EffectDefinition`` ≠ ``analysis.EffectSpec`` ·
``Operation`` ≠ ``PlayerAction`` · ``Cost`` ≠ ``CostPayment`` ·
검증된 의미 ≠ 실행 가능 · 파괴 ≠ 묘지로 보내기 ≠ 릴리스.

자세한 것은 ``docs/phase2d1-effect-model.md``.
"""

from engine.effect.delta import (
    CardDrawn,
    CardMovement,
    LifeChanged,
    PhaseChanged,
    StateDelta,
    ZoneMoved,
    canonical_deltas,
)
from engine.effect.definition import (
    FORBIDDEN_SOURCES,
    EffectDefinition,
    EffectDefinitionError,
    EffectDefinitionRegistry,
    EffectDefinitionSource,
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
from engine.effect.journal import (
    CostPaymentEvent,
    EffectEvent,
    EventJournal,
    EventKind,
    JournalError,
    JournalEvent,
)
from engine.effect.executor import (
    DESTINATION,
    DESTINATION_OWNER,
    SUPPORTED,
    UNSUPPORTED_REASON,
    DestinationOwner,
    EffectExecutionError,
    EffectExecutor,
    EffectImplementationRegistry,
    destination_player,
)
from engine.effect.resolution import (
    AppliedOperation,
    EffectResolver,
    EffectResult,
    ResolutionContext,
    ResolutionStatus,
    UnimplementedResolver,
)
from engine.effect.target import (
    PRIMARY_TARGET,
    TargetBinding,
    TargetRef,
    TargetRequirement,
    TargetSelection,
    TargetSpec,
)

__all__ = [
    # 정의
    "EffectDefinition",
    "EffectDefinitionError",
    "EffectProvenance",
    "EffectSource",
    "FORBIDDEN_SOURCES",
    # 실행 권위
    "ExecutionAvailability",
    "EffectDefinitionSource",
    "EffectDefinitionRegistry",
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
    "TargetRef",
    "PRIMARY_TARGET",
    "TargetBinding",
    "TargetSelection",
    # 해결 계약
    "ResolutionContext",
    "ResolutionStatus",
    "AppliedOperation",
    "EffectResult",
    "EffectResolver",
    "UnimplementedResolver",
    # 실행
    "EffectExecutor",
    "EffectExecutionError",
    "EffectImplementationRegistry",
    "DESTINATION",
    "SUPPORTED",
    "UNSUPPORTED_REASON",
    # 목적지의 주인
    "DestinationOwner",
    "DESTINATION_OWNER",
    "destination_player",
    # 상태 변화 (Phase 2-D-3)
    "StateDelta",
    "CardMovement",
    "ZoneMoved",
    "CardDrawn",
    "LifeChanged",
    "PhaseChanged",
    "canonical_deltas",
    # 기록 (Phase 2-D-3 · 2-E)
    "EventKind",
    "JournalEvent",
    "EffectEvent",
    "CostPaymentEvent",
    "EventJournal",
    "JournalError",
]
