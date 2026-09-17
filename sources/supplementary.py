"""
보조 자료 어댑터.

나무위키 같은 외부 자료를 붙이기 위한 자리다. 공식 데이터와 **같은 신뢰도로
취급하지 않는다**. 이 소스에서 온 값은 항상
:attr:`~core.provenance.FieldStatus.SUPPLEMENTARY` 로 기록되며, 카드의 기본
정보나 공식 문구를 덮어쓰지 못한다 (우선순위상 가장 낮다).

**저장하지 않는 것**: 사용자 평가, 추천, 티어 의견, 주관적 서술.
규칙이나 확정된 카드 데이터가 아니기 때문이다. 이 어댑터는 카드군 관계,
수록 정보 같은 사실 항목만 받아들이고 나머지는 버린다.

지금은 로컬 파일만 읽는다. 외부 사이트에서 긁어오는 수집기를 붙이더라도
이 어댑터의 인터페이스만 지키면 ``core/`` 와 ``analysis/`` 는 그대로다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.provenance import SourceKind
from sources.source_manager import SourceRecord

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUPPLEMENTARY_DIR = PROJECT_ROOT / "data" / "supplementary"

#: 받아들이는 사실 항목. 여기 없는 키는 무시한다.
ALLOWED_FIELDS = frozenset(
    {
        "archetypes",
        "related_cards",
        "sets",
        "release_date",
        "notes",
    }
)

#: 명시적으로 거부하는 항목. 주관적 평가는 저장하지 않는다.
REJECTED_FIELDS = frozenset(
    {"rating", "tier", "score", "review", "recommendation", "opinion", "평가", "추천"}
)


class SupplementaryAdapter:
    """``data/supplementary/*.json`` 을 읽는 보조 소스."""

    kind = SourceKind.SUPPLEMENTARY

    def __init__(self, directory: str | os.PathLike[str] | None = None):
        self.directory = Path(directory or DEFAULT_SUPPLEMENTARY_DIR)

    def is_available(self) -> bool:
        return self.directory.is_dir() and any(self.directory.glob("*.json"))

    def load_records(self) -> dict[int, SourceRecord]:
        records: dict[int, SourceRecord] = {}
        if not self.directory.is_dir():
            return records
        for path in sorted(self.directory.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as fh:
                    blob = json.load(fh)
            except (OSError, ValueError):
                continue
            for key, entry in (blob or {}).items():
                try:
                    card_id = int(key)
                except (TypeError, ValueError):
                    continue
                fields = self._filter(entry)
                if not fields:
                    continue
                fields["_origin"] = path.name
                records[card_id] = SourceRecord(
                    card_id=card_id, source=self.kind, fields=fields
                )
        return records

    @staticmethod
    def _filter(entry) -> dict[str, object]:
        """사실 항목만 남기고 주관적 서술은 버린다."""
        if not isinstance(entry, dict):
            return {}
        kept: dict[str, object] = {}
        for key, value in entry.items():
            lowered = str(key).lower()
            if lowered in REJECTED_FIELDS or lowered not in ALLOWED_FIELDS:
                continue
            kept[lowered] = value
        return kept
