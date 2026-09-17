"""
Card Ruling Layer — 공식 카드별 재정.

네 계층 중 세 번째다.

=========================  ===========================================
계층                        권위 있는 출처
=========================  ===========================================
General Rules              공식 룰북              (``rules/``)
Card Data / Analysis       공식 카드 텍스트 · Lua  (``core/``, ``analysis/``)
**Card Rulings**           **공식 카드별 Q&A**     (여기)
Card Implementation        Lua (authoritative)    (``analysis/``)
=========================  ===========================================

원칙 셋
-------
1. **공식 출처만.** 코나미 공식 OCG 데이터베이스 외에는 재정으로 저장하지
   않는다. 비공식 위키 · 커뮤니티 재정 · 모델의 기존 지식은 들어오지 못한다.
2. **원문이 권위를 갖는다.** 일본어 원문만 authoritative 하고, 번역은
   :class:`~rulings.ruling_model.RulingTranslation` 으로 따로 붙는다.
   타입이 달라서 원문 자리에 들어갈 수 없다.
3. **"재정 없음"과 "확인 실패"는 다르다.**
   :class:`~rulings.ruling_model.RulingAvailability` 가 셋을 구분한다.
"""

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    CardRulingSupplement,
    RulingAvailability,
    RulingGame,
    RulingKind,
    RulingProvenance,
    RulingSource,
    RulingTranslation,
    TranslationSource,
    TranslationStatus,
)
from rulings.ruling_repository import RulingRepository
from rulings.ruling_search import RulingHit, RulingSearch
from rulings.update import RulingChange, RulingUpdatePlan, diff_ruling_set

__all__ = [
    "CardRuling",
    "CardRulingSupplement",
    "CardRulingSet",
    "RulingAvailability",
    "RulingGame",
    "RulingKind",
    "RulingProvenance",
    "RulingSource",
    "RulingTranslation",
    "TranslationSource",
    "TranslationStatus",
    "RulingRepository",
    "RulingSearch",
    "RulingHit",
    "RulingChange",
    "RulingUpdatePlan",
    "diff_ruling_set",
]
