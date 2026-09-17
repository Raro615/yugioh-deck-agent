"""
Rules Knowledge — 공식 룰북에서 온 **게임 자체의 규칙**.

카드 계층과 완전히 분리된 세 번째 지식 원천이다.

======================  ==========================================
계층                     무엇을 말해 주는가
======================  ==========================================
Card Data               카드가 무엇인가 (이름 · 수치 · 텍스트)
Card Analysis           그 카드의 효과가 어떻게 생겼는가 (Lua)
**Rules Knowledge**     **게임이 어떻게 굴러가는가** (룰북)
======================  ==========================================

Rules Knowledge 는 카드의 효과를 **대체하지 않는다.** 룰북은 "체인이 어떻게
쌓이고 어떤 순서로 해결되는가"를 말해 주지만, "이 카드가 무엇을 하는가"는
언제나 Lua / 공식 카드 텍스트가 정한다.

권위 순서 (위가 강하다)::

    게임 규칙        Official Rulebook      <- 이 패키지
    카드의 실제 처리  Lua (authoritative)
    카드 공식 문구    Official card text
    한국어 표시       Korean DB
    보조 정보         Supplementary sources

어떤 보조 출처도 공식 룰을 덮어쓰지 못한다
(:data:`~rules.rule_model.RULE_AUTHORITY`).
"""

from rules.rule_model import (
    RULE_AUTHORITY,
    RuleCategory,
    RuleDocument,
    RuleProvenance,
    RuleRef,
    RuleSection,
)
from rules.rule_repository import RuleRepository
from rules.rule_search import RuleHit, RuleSearch
from rules.structured import StructuredRules, load_all as load_structured_rules

__all__ = [
    "RULE_AUTHORITY",
    "RuleCategory",
    "RuleDocument",
    "RuleProvenance",
    "RuleRef",
    "RuleSection",
    "RuleRepository",
    "RuleSearch",
    "RuleHit",
    "StructuredRules",
    "load_structured_rules",
]
