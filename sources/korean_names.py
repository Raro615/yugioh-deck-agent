"""
한국어 카드명 / 카드 텍스트 오버레이.

공식 한국어 데이터가 확보되면 이 소스가 :class:`~core.card_model.Card` 의
``name_ko`` 와 ``desc`` 를 채운다. 검색과 필터는 언어와 무관한 수치·효과 필드
위에서 동작하므로, 한국어 데이터가 없어도 한국어 질의 자체는 정상 동작한다.
한국어 데이터는 **표시**에만 영향을 준다.

정책
----
공식 카드명과 카드 텍스트는 임의로 번역하지 않는다. 이 모듈은 외부에서 받은
공식 한국어 데이터를 그대로 싣기만 하며, 자체적으로 번역을 생성하지 않는다.

지원 형식
---------
``ko-KR.cdb``
    공식 DB 와 같은 SQLite 스키마(``texts(id, name, desc, ...)``).
``*.json``
    ``{"46986414": {"name": "...", "desc": "..."}}`` 또는
    ``[{"id": 46986414, "name": "...", "desc": "..."}]``
``*.csv``
    ``id,name,desc`` 헤더를 가진 CSV.

현재 상태
---------
이 세션의 아웃바운드 네트워크 정책이 공식 한국어 데이터베이스
(``db.yugioh-card.com``)와 보조 API 를 차단하고 있어, 실제 한국어 데이터는
아직 이 저장소에 포함되어 있지 않다. 데이터 파일을 확보하면
``data/ko/`` 에 두고 그대로 사용할 수 있다.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

from core.card_model import Card, CardSource

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KO_DIR = PROJECT_ROOT / "data" / "ko"


class KoreanTextSource:
    """한국어 카드명/텍스트를 카드 집합에 덧씌운다."""

    def __init__(self, entries: dict[int, dict[str, str]] | None = None):
        self.entries: dict[int, dict[str, str]] = entries or {}

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> KoreanTextSource:
        """파일 확장자를 보고 알맞은 형식으로 읽어들인다."""
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"한국어 데이터 파일을 찾을 수 없습니다: {file_path}")
        suffix = file_path.suffix.lower()
        if suffix in (".cdb", ".db", ".sqlite"):
            return cls(cls._read_cdb(file_path))
        if suffix == ".json":
            return cls(cls._read_json(file_path))
        if suffix == ".csv":
            return cls(cls._read_csv(file_path))
        raise ValueError(f"지원하지 않는 형식입니다: {file_path.suffix}")

    @classmethod
    def autoload(
        cls, directory: str | os.PathLike[str] | None = None
    ) -> KoreanTextSource:
        """
        ``data/ko/`` 안의 한국어 데이터 파일을 자동으로 찾는다.
        없으면 비어 있는 소스를 돌려준다(오류가 아니다).
        """
        ko_dir = Path(directory or DEFAULT_KO_DIR)
        if not ko_dir.is_dir():
            return cls()
        for pattern in ("*.cdb", "*.json", "*.csv"):
            for candidate in sorted(ko_dir.glob(pattern)):
                try:
                    return cls.load(candidate)
                except (ValueError, sqlite3.Error, OSError, json.JSONDecodeError):
                    continue
        return cls()

    # ------------------------------------------------------------------
    @staticmethod
    def _read_cdb(path: Path) -> dict[int, dict[str, str]]:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT id, name, desc FROM texts").fetchall()
        finally:
            conn.close()
        return {
            int(cid): {"name": name or "", "desc": desc or ""}
            for cid, name, desc in rows
            if name
        }

    @staticmethod
    def _read_json(path: Path) -> dict[int, dict[str, str]]:
        with path.open(encoding="utf-8") as fh:
            blob = json.load(fh)
        entries: dict[int, dict[str, str]] = {}
        if isinstance(blob, dict):
            for key, value in blob.items():
                entries[int(key)] = {
                    "name": value.get("name", ""),
                    "desc": value.get("desc", ""),
                }
        else:
            for item in blob:
                entries[int(item["id"])] = {
                    "name": item.get("name", ""),
                    "desc": item.get("desc", ""),
                }
        return {k: v for k, v in entries.items() if v["name"]}

    @staticmethod
    def _read_csv(path: Path) -> dict[int, dict[str, str]]:
        entries: dict[int, dict[str, str]] = {}
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if not row.get("id") or not row.get("name"):
                    continue
                entries[int(row["id"])] = {
                    "name": row["name"],
                    "desc": row.get("desc", ""),
                }
        return entries

    # ------------------------------------------------------------------
    def apply(self, cards: dict[int, Card]) -> int:
        """
        카드 집합에 한국어 데이터를 덧씌운다. 적용된 카드 수를 돌려준다.

        원문 이름(``name_en``/``name_ja``)은 지우지 않고 그대로 둔다.
        검색은 한국어·영어·일본어 이름을 모두 대조하기 때문이다.
        """
        applied = 0
        for card_id, entry in self.entries.items():
            card = cards.get(card_id)
            if card is None:
                continue
            name = entry.get("name", "").strip()
            if name:
                card.name_ko = name
                card.name = name
            desc = entry.get("desc", "").strip()
            if desc:
                card.desc = desc
            card.sources.add(CardSource.KOREAN_OVERLAY)
            applied += 1
        return applied
