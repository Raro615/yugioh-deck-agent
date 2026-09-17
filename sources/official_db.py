"""
공식 카드 데이터베이스(``cards.cdb``) 어댑터.

``cards.cdb`` 는 EDOPro 가 사용하는 SQLite 파일로, Project Ignis 의 BabelCDB
저장소에서 배포된다. 카드의 레벨/랭크/링크, 속성, 종족, 공격력/수비력,
카드 종류, 카드 텍스트가 모두 이 파일에 들어 있다.
(Lua 스크립트에는 이 정보가 전혀 없으므로 수치 기반 필터에 반드시 필요하다.)

스키마::

    datas(id, ot, alias, setcode, type, atk, def, level, race, attribute, category)
    texts(id, name, desc, str1 .. str16)

인코딩 규칙(실제 데이터로 검증됨):

- ``level`` 하위 바이트 = 레벨/랭크/링크 값
- ``level`` 16~23 비트 = 펜듈럼 왼쪽 스케일, 24~31 비트 = 오른쪽 스케일
  (예: D/D Savant Thomas = 0x06060008 -> 레벨 8, 스케일 6/6)
- 링크 몬스터는 ``def`` 컬럼에 수비력이 아니라 **링크 마커 비트마스크**가 들어간다
- ``atk``/``def`` 가 -2 이면 물음표(?) 수치
- ``setcode`` 는 16비트 카드군 코드 4개를 하나의 정수에 패킹한 값
- ``alias`` 가 0 이 아니면 다른 일러스트/에라타 판본이다

카드명과 카드 텍스트는 원문 그대로 보존하며 번역하지 않는다.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from core import constants as C
from core.card_model import Card, CardSource

DEFAULT_DB_FILENAMES = ("cards.cdb", "cards-unofficial.cdb")

_SELECT = """
SELECT d.id, d.ot, d.alias, d.setcode, d.type, d.atk, d.def, d.level,
       d.race, d.attribute, d.category,
       t.name, t.desc,
       t.str1, t.str2, t.str3, t.str4, t.str5, t.str6, t.str7, t.str8,
       t.str9, t.str10, t.str11, t.str12, t.str13, t.str14, t.str15, t.str16
FROM datas d
LEFT JOIN texts t ON t.id = d.id
"""


class OfficialDatabaseNotFound(FileNotFoundError):
    """``cards.cdb`` 를 찾지 못했을 때 발생한다."""


def unpack_level(raw: int) -> tuple[int, int | None, int | None]:
    """
    ``datas.level`` 원본 값에서 (레벨, 왼쪽 스케일, 오른쪽 스케일) 을 분리한다.
    펜듈럼이 아니면 스케일은 ``None`` 이다.
    """
    level = raw & 0xFF
    left = (raw >> 16) & 0xFF
    right = (raw >> 24) & 0xFF
    if raw >> 16:
        return level, left, right
    return level, None, None


def unpack_setcodes(raw: int) -> list[int]:
    """``datas.setcode`` 에 패킹된 16비트 카드군 코드들을 풀어낸다."""
    if not raw:
        return []
    # SQLite 는 64비트 부호 있는 정수를 쓰므로 음수로 읽힐 수 있다.
    value = raw & 0xFFFFFFFFFFFFFFFF
    codes: list[int] = []
    for shift in (0, 16, 32, 48):
        code = (value >> shift) & 0xFFFF
        if code:
            codes.append(code)
    return codes


def find_database(search_paths: list[str | os.PathLike[str]] | None = None) -> Path:
    """
    ``cards.cdb`` 를 찾는다.

    탐색 순서:
    1. ``YGO_CARDS_CDB`` 환경 변수
    2. 호출자가 넘긴 경로들
    3. 프로젝트 ``data/`` 디렉터리
    """
    env = os.environ.get("YGO_CARDS_CDB")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    for p in search_paths or []:
        candidates.append(Path(p))
    project_data = Path(__file__).resolve().parent.parent / "data"
    for name in DEFAULT_DB_FILENAMES:
        candidates.append(project_data / name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise OfficialDatabaseNotFound(
        "공식 카드 데이터베이스(cards.cdb)를 찾을 수 없습니다.\n"
        "  python -m scripts.fetch_official_db\n"
        "를 실행해 내려받거나, YGO_CARDS_CDB 환경 변수로 경로를 지정하세요."
    )


class OfficialDatabaseSource:
    """``cards.cdb`` 를 :class:`Card` 로 정규화해 읽어들이는 소스."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self.db_path = Path(db_path) if db_path else find_database()

    def iter_cards(self, include_tokens: bool = False) -> Iterator[Card]:
        """데이터베이스의 카드를 하나씩 내보낸다."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(_SELECT):
                card = self._row_to_card(row)
                if not include_tokens and card.type_mask & C.TYPE_TOKEN:
                    continue
                yield card
        finally:
            conn.close()

    def load(self, include_tokens: bool = False) -> dict[int, Card]:
        return {c.id: c for c in self.iter_cards(include_tokens=include_tokens)}

    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> Card:
        type_mask = row["type"] or 0
        raw_level = row["level"] or 0
        level, lscale, rscale = unpack_level(raw_level)

        raw_def = row["def"] if row["def"] is not None else C.STAT_NONE
        link_markers = 0
        defense = raw_def
        if type_mask & C.TYPE_LINK:
            # 링크 몬스터는 def 컬럼이 링크 마커다. 수비력은 존재하지 않는다.
            link_markers = raw_def if raw_def > 0 else 0
            defense = C.STAT_NONE

        strings = [
            row[f"str{i}"]
            for i in range(1, 17)
            if row[f"str{i}"] not in (None, "")
        ]

        name = row["name"] or ""
        return Card(
            id=row["id"],
            name=name,
            name_en=name or None,
            type_mask=type_mask,
            attribute_mask=row["attribute"] or 0,
            race_mask=row["race"] or 0,
            level=level,
            atk=row["atk"] if row["atk"] is not None else C.STAT_NONE,
            defense=defense,
            pendulum_scale_left=lscale,
            pendulum_scale_right=rscale,
            link_marker_mask=link_markers,
            setcodes=unpack_setcodes(row["setcode"] or 0),
            category_mask=row["category"] or 0,
            alias=row["alias"] or 0,
            ot=row["ot"] or 0,
            desc=row["desc"] or "",
            strings=strings,
            sources={CardSource.OFFICIAL_DB},
        )
