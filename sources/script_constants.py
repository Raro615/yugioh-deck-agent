"""
EDOPro 카드 스크립트 상수 해석기.

카드 스크립트는 카드 ID 와 카드군 코드를 숫자 대신 명명 상수로 참조한다::

    s.listed_names={CARD_DARK_MAGICIAN}     -- 46986414
    s.listed_series={SET_LABRYNTH}          -- 0x17f

이 상수 정의는 Project Ignis CardScripts 저장소의 다음 파일들에 있다.

- ``card_counter_constants.lua``      : ``CARD_*`` (카드 ID), ``COUNTER_*``
- ``archetype_setcode_constants.lua`` : ``SET_*`` (카드군 setcode)
- ``constant.lua``                    : 엔진 상수

``SET_*`` 값은 공식 데이터베이스 ``datas.setcode`` 와 같은 체계이므로,
이 매핑이 있으면 Lua 쪽 카드군 정보와 공식 DB 쪽 카드군 정보를 연결할 수 있다.
(실측 확인: ``SET_LABRYNTH = 0x17f`` = Labrynth Cooclock 의 setcode)

상수 파일이 없으면 해석만 생략되고 나머지 기능은 그대로 동작한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONSTANT_DIR = PROJECT_ROOT / "data" / "constants"

CONSTANT_FILES = (
    "card_counter_constants.lua",
    "archetype_setcode_constants.lua",
    "constant.lua",
)

# 예: ``SET_LABRYNTH                      = 0x17f``
_RE_ASSIGN = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*(?:--.*)?$",
    re.MULTILINE,
)


class ScriptConstants:
    """``CARD_*`` / ``SET_*`` / ``COUNTER_*`` 상수 조회 테이블."""

    def __init__(
        self,
        card_ids: dict[str, int] | None = None,
        setcodes: dict[str, int] | None = None,
        others: dict[str, int] | None = None,
    ):
        self.card_ids: dict[str, int] = card_ids or {}
        self.setcodes: dict[str, int] = setcodes or {}
        self.others: dict[str, int] = others or {}
        self._setcode_to_name: dict[int, str] = {
            v: k for k, v in self.setcodes.items()
        }

    def __bool__(self) -> bool:
        return bool(self.card_ids or self.setcodes)

    # --- 조회 ---------------------------------------------------------
    def card_id(self, name: str) -> int | None:
        """``CARD_DARK_MAGICIAN`` -> 46986414"""
        return self.card_ids.get(name.upper())

    def setcode(self, name: str) -> int | None:
        """``SET_LABRYNTH`` 또는 ``LABRYNTH`` -> 0x17f"""
        key = name.upper()
        if not key.startswith("SET_"):
            key = f"SET_{key}"
        return self.setcodes.get(key)

    def setcode_name(self, code: int) -> str | None:
        """0x17f -> ``SET_LABRYNTH``"""
        return self._setcode_to_name.get(code)

    # --- 적재 ---------------------------------------------------------
    @classmethod
    def load(
        cls, constant_dir: str | os.PathLike[str] | None = None
    ) -> ScriptConstants:
        """
        상수 파일들을 읽어들인다. 파일이 없으면 비어 있는 테이블을 돌려준다
        (기능 저하만 있을 뿐 오류는 아니다).
        """
        directory = Path(constant_dir or DEFAULT_CONSTANT_DIR)
        card_ids: dict[str, int] = {}
        setcodes: dict[str, int] = {}
        others: dict[str, int] = {}

        for file_name in CONSTANT_FILES:
            path = directory / file_name
            if not path.is_file():
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name, raw in _RE_ASSIGN.findall(source):
                value = int(raw, 16) if raw.lower().startswith("0x") else int(raw)
                if name.startswith("CARD_"):
                    card_ids[name] = value
                elif name.startswith("SET_"):
                    setcodes[name] = value
                else:
                    others[name] = value

        return cls(card_ids=card_ids, setcodes=setcodes, others=others)
