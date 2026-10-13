"""
deck — **덱을 짜고 전개를 계획하는 쪽** (Phase 4-B).

    DeckRequest          사용자가 말한 것 (테마 · 목표 · 제약)
          ↓
    DeckBuilder          후보 선정 → 최종 구성          core/card_search 재사용
          ↓  DeckDraft
    DeckValidator        규격 검증 (확인된 규칙만)      rules/ 데이터 인용
          ↓  DeckValidation
    HandProvider         초기 패를 **받는다**            이번 단계는 고정 패뿐
          ↓
    ComboPlanner         전개 계획                      analysis/ · engine/ 근거
          ↓  ComboPlan
    PlanResult           근거 · 검증 상태 · 사람이 확인할 것

여기서 하지 않는 것
-------------------
**규칙을 집행하지 않는다.** 이 꾸러미는 "무엇을 할 수 있어 보이는가" 를
근거와 함께 적을 뿐이고, 그것이 실제 듀얼에서 합법인지 판정하지 않는다.
판정은 ``engine/`` 의 일이고, Engine V1 이 실행할 수 있는 효과는 극히
일부다 (`docs/discord-duel-simulator-integration-audit.md` §4.3).

그래서 모든 산출물에 **검증 상태**가 붙는다. 상태가 없는 주장은 하지
않는다 — ``UNKNOWN`` 을 성공으로 바꾸지 않는다.

**Engine V1 을 한 줄도 바꾸지 않는다.** 엔진을 읽기만 한다.
"""

from deck.hand import FixedHand, HandProvider
from deck.model import (
    CardRole,
    ComboPlan,
    DeckDraft,
    DeckSlot,
    DeckValidation,
    PlanResult,
    PlanStep,
    RuleFinding,
    StepBasis,
    StepStatus,
    ValidationOutcome,
)
from deck.request import DeckGoal, DeckRequest, parse_deck_request

__all__ = [
    "CardRole",
    "ComboPlan",
    "DeckDraft",
    "DeckGoal",
    "DeckRequest",
    "DeckSlot",
    "DeckValidation",
    "FixedHand",
    "HandProvider",
    "PlanResult",
    "PlanStep",
    "RuleFinding",
    "StepBasis",
    "StepStatus",
    "ValidationOutcome",
    "parse_deck_request",
]
