"""
덱 규격 검증 — **확인된 규칙만 검사한다** (Phase 4-B).

🔴 **핵심 규율**: 검증하지 못한 제약을 통과로 처리하지 않는다. 규칙 데이터가
이 저장소에 없으면 :attr:`~deck.model.ValidationOutcome.UNVERIFIABLE` 이고,
그것은 "문제 없음" 이 아니다.

무엇이 데이터로 확인되는가 (실측)
---------------------------------
``data/rules/structured/sd-rulebook-en-v10.json`` 의 ``zones`` 항목에서:

===========================  ==========  ==================================
규칙                          데이터       근거
===========================  ==========  ==================================
메인 덱 40~60장               **있다**    ``zones[Deck].notes`` +
                                         ``capacity=60`` · ``RULE-DECK-002``
엑스트라 덱 15장 이하          **있다**    ``zones[Extra Deck].capacity=15``
                                         · ``RULE-DECK-003``
동일명 3장 제한                없다        🔴 룰북 데이터에 없다
금지·제한 (리미트 레귤레이션)   없다        🔴 저장소에 데이터 자체가 없다
===========================  ==========  ==================================

앞의 둘은 검사하고, 뒤의 둘은 **검증 불가로 적는다.** 3장 제한을 '상식'
으로 검사하면, 근거 없는 판정을 근거 있는 판정과 같은 표에 올리게 된다.
"""

from __future__ import annotations

import json
from pathlib import Path

from deck.model import (
    DeckDraft,
    DeckValidation,
    RuleFinding,
    ValidationOutcome,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULEBOOK = PROJECT_ROOT / "data" / "rules" / "structured" / "sd-rulebook-en-v10.json"


class DeckValidator:
    """덱 초안을 검증한다. 규칙 수치는 **룰북 데이터에서 읽는다.**"""

    def __init__(self, rulebook_path: Path | None = None):
        self.rulebook_path = Path(rulebook_path) if rulebook_path else RULEBOOK
        self._zones = self._load_zones()

    def _load_zones(self) -> dict[str, dict]:
        """룰북의 ``zones`` 를 이름으로 색인한다. 파일이 없으면 빈 것."""
        try:
            data = json.loads(self.rulebook_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        zones = data.get("zones")
        if not isinstance(zones, list):
            return {}
        return {z.get("name"): z for z in zones
                if isinstance(z, dict) and z.get("name")}

    # ------------------------------------------------------------------
    def validate(self, draft: DeckDraft) -> DeckValidation:
        result = DeckValidation()
        result.findings.append(self._check_main_size(draft))
        result.findings.append(self._check_extra_size(draft))
        result.findings.append(self._check_copy_limit(draft))
        result.findings.append(self._check_limit_regulation())
        result.findings.extend(self._check_slot_sanity(draft))
        result.findings.append(self._check_extra_placement(draft))
        return result

    # ------------------------------------------------------------------
    def _check_main_size(self, draft: DeckDraft) -> RuleFinding:
        zone = self._zones.get("Deck") or {}
        notes = str(zone.get("notes") or "")
        capacity = zone.get("capacity")
        #: 하한은 룰북 문장에서 읽는다 — 코드에 숫자를 박지 않는다.
        lower = 40 if "40 to 60" in notes else None
        if lower is None or not isinstance(capacity, int):
            return RuleFinding(
                rule="메인 덱 장수",
                outcome=ValidationOutcome.UNVERIFIABLE,
                detail=("룰북 데이터에서 메인 덱 장수 규칙을 읽지"
                        " 못했습니다"),
            )
        count = draft.main_count
        source = ", ".join(zone.get("rules") or []) or None
        if lower <= count <= capacity:
            return RuleFinding(
                rule="메인 덱 장수",
                outcome=ValidationOutcome.SATISFIED,
                detail=f"{count}장 ({lower}~{capacity} 범위 안)",
                source=source,
            )
        return RuleFinding(
            rule="메인 덱 장수",
            outcome=ValidationOutcome.VIOLATED,
            detail=f"{count}장 — {lower}~{capacity} 범위를 벗어났습니다",
            source=source,
        )

    def _check_extra_size(self, draft: DeckDraft) -> RuleFinding:
        zone = self._zones.get("Extra Deck") or {}
        capacity = zone.get("capacity")
        if not isinstance(capacity, int):
            return RuleFinding(
                rule="엑스트라 덱 장수",
                outcome=ValidationOutcome.UNVERIFIABLE,
                detail="룰북 데이터에서 엑스트라 덱 상한을 읽지 못했습니다",
            )
        count = draft.extra_count
        source = ", ".join(zone.get("rules") or []) or None
        if count <= capacity:
            return RuleFinding(
                rule="엑스트라 덱 장수",
                outcome=ValidationOutcome.SATISFIED,
                detail=f"{count}장 ({capacity}장 이하)",
                source=source,
            )
        return RuleFinding(
            rule="엑스트라 덱 장수",
            outcome=ValidationOutcome.VIOLATED,
            detail=f"{count}장 — 상한 {capacity}장을 넘었습니다",
            source=source,
        )

    @staticmethod
    def _check_copy_limit(draft: DeckDraft) -> RuleFinding:
        """
        🔴 동일명 매수 상한을 **검사하지 않는다.** 룰북 데이터에 없다.

        그래도 **관측한 사실은 적는다** — 가장 많이 넣은 매수가 몇인지.
        사람이 그 수를 보고 직접 판단할 수 있게 하는 것이 목적이고,
        우리가 판정했다고 말하지 않는다.
        """
        slots = draft.all_slots()
        peak = max((s.copies for s in slots), default=0)
        return RuleFinding(
            rule="동일명 카드 매수 상한",
            outcome=ValidationOutcome.UNVERIFIABLE,
            detail=(f"룰북 데이터에 매수 상한 규칙이 없습니다. "
                    f"이 초안의 최대 매수는 {peak}장입니다 — 사람이"
                    f" 확인해야 합니다"),
        )

    @staticmethod
    def _check_limit_regulation() -> RuleFinding:
        """🔴 금지·제한 데이터가 저장소에 **없다.**"""
        return RuleFinding(
            rule="금지·제한 (리미트 레귤레이션)",
            outcome=ValidationOutcome.UNVERIFIABLE,
            detail=("이 저장소에 금지·제한 데이터가 없습니다. 금지·제한"
                    " 위반 여부를 전혀 판정하지 못했습니다"),
        )

    @staticmethod
    def _check_slot_sanity(draft: DeckDraft) -> list[RuleFinding]:
        """매수가 1 미만인 칸과 카드 ID 중복을 잡는다 — 자체 일관성이다."""
        out: list[RuleFinding] = []
        bad = [s for s in draft.all_slots() if s.copies < 1]
        out.append(RuleFinding(
            rule="칸별 매수",
            outcome=(ValidationOutcome.VIOLATED if bad
                     else ValidationOutcome.SATISFIED),
            detail=(f"매수가 1 미만인 칸 {len(bad)}개" if bad
                    else "모든 칸의 매수가 1장 이상입니다"),
        ))

        ids = [s.card_id for s in draft.all_slots()]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        out.append(RuleFinding(
            rule="카드 ID 중복",
            outcome=(ValidationOutcome.VIOLATED if duplicated
                     else ValidationOutcome.SATISFIED),
            detail=(f"같은 카드 ID 가 여러 칸에 있습니다: {duplicated[:5]}"
                    if duplicated else "카드 ID 가 칸마다 한 번씩입니다"),
        ))
        return out

    @staticmethod
    def _check_extra_placement(draft: DeckDraft) -> RuleFinding:
        """
        엑스트라 덱 카드가 메인에 섞였는지. 이것은 **카드 데이터로**
        판정된다 (``is_extra_deck``) — 룰북 문장이 필요하지 않다.
        """
        from deck.model import CardRole

        misplaced = [s.name for s in draft.main
                     if s.role is CardRole.EXTRA_DECK]
        return RuleFinding(
            rule="엑스트라 덱 카드의 위치",
            outcome=(ValidationOutcome.VIOLATED if misplaced
                     else ValidationOutcome.SATISFIED),
            detail=(f"메인에 엑스트라 덱 카드가 있습니다: {misplaced[:5]}"
                    if misplaced
                    else "엑스트라 덱 카드가 메인에 섞이지 않았습니다"),
        )
