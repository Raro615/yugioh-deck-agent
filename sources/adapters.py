"""
기존 소스를 :class:`~sources.source_manager.SourceAdapter` 로 감싼다.

기존 로더(:mod:`sources.official_db`, :mod:`sources.lua_loader`,
:mod:`sources.korean_names`)는 그대로 두고 얇게 감싸기만 한다. 수집 방식이
바뀌어도 어댑터만 고치면 되고, ``core/`` 와 ``analysis/`` 는 영향을 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.provenance import SourceKind
from sources.source_manager import SourceRecord

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OfficialDatabaseAdapter:
    """``cards.cdb`` — 구조화된 기본 정보의 주요 소스."""

    kind = SourceKind.OFFICIAL_DB

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self.db_path = db_path

    def is_available(self) -> bool:
        from sources.official_db import OfficialDatabaseNotFound, find_database

        try:
            find_database([self.db_path] if self.db_path else None)
        except OfficialDatabaseNotFound:
            return False
        return True

    def load_records(self) -> dict[int, SourceRecord]:
        from sources.official_db import OfficialDatabaseSource

        records: dict[int, SourceRecord] = {}
        for card in OfficialDatabaseSource(self.db_path).iter_cards():
            records[card.id] = SourceRecord(
                card_id=card.id,
                source=self.kind,
                fields={
                    # 지문에 쓰이므로 값이 바뀌면 곧 변경으로 잡힌다.
                    "type": card.type_mask,
                    "attribute": card.attribute_mask,
                    "race": card.race_mask,
                    "level": card.level,
                    "atk": card.atk,
                    "def": card.defense,
                    "setcodes": card.setcodes,
                    "alias": card.alias,
                    "name_en": card.name_en,
                    "desc_en": card.desc_en,
                },
            )
        return records


class LuaScriptAdapter:
    """카드 스크립트 — 실제 게임 처리 로직의 주요 소스."""

    kind = SourceKind.LUA

    def __init__(self, script_dir: str | os.PathLike[str] | None = None):
        self.script_dir = Path(script_dir or PROJECT_ROOT)

    def is_available(self) -> bool:
        return self.script_dir.is_dir()

    def load_records(self) -> dict[int, SourceRecord]:
        from sources.lua_loader import LuaScriptSource

        records: dict[int, SourceRecord] = {}
        source = LuaScriptSource(self.script_dir)
        for card_id, path in source.iter_script_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            records[card_id] = SourceRecord(
                card_id=card_id,
                source=self.kind,
                # 스크립트 본문 대신 크기와 수정 시각으로 변경을 잡는다.
                # 12,000여 파일을 매번 해시하지 않기 위해서다.
                fields={"size": stat.st_size, "mtime": int(stat.st_mtime)},
            )
        return records


class KoreanDatabaseAdapter:
    """공식 한국어 카드명과 카드 텍스트."""

    kind = SourceKind.KOREAN_DB

    def __init__(self, ko_dir: str | os.PathLike[str] | None = None):
        self.ko_dir = ko_dir

    def _source(self):
        from sources.korean_names import KoreanTextSource

        return KoreanTextSource.autoload(self.ko_dir)

    def is_available(self) -> bool:
        return bool(self._source())

    def load_records(self) -> dict[int, SourceRecord]:
        entries = self._source().entries
        return {
            card_id: SourceRecord(
                card_id=card_id,
                source=self.kind,
                fields={"name": entry.get("name", ""), "desc": entry.get("desc", "")},
            )
            for card_id, entry in entries.items()
        }
