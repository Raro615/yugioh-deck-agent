"""
공식 카드 데이터베이스와 스크립트 상수 파일을 내려받는다.

이 파일들은 상류 저장소에서 계속 갱신되므로 이 저장소에 커밋하지 않고
``data/`` 아래에 내려받아 쓴다 (``.gitignore`` 처리되어 있다).

    python -m scripts.fetch_official_db

내려받는 것:

- ``cards.cdb``                       (Project Ignis BabelCDB)
  카드의 레벨/속성/종족/공수/카드 종류/카드 텍스트. Lua 에는 없는 정보다.
- ``card_counter_constants.lua``      (Project Ignis CardScripts)
  ``CARD_*`` 카드 ID 상수. ``listed_names`` 해석에 쓴다.
- ``archetype_setcode_constants.lua`` (Project Ignis CardScripts)
  ``SET_*`` 카드군 코드. 공식 DB 의 setcode 와 같은 체계다.
- ``constant.lua``                    (Project Ignis CardScripts)
  엔진 상수.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONSTANT_DIR = DATA_DIR / "constants"

BABEL_CDB = "https://raw.githubusercontent.com/ProjectIgnis/BabelCDB/master"
CARD_SCRIPTS = "https://raw.githubusercontent.com/ProjectIgnis/CardScripts/master"

DOWNLOADS: tuple[tuple[str, Path], ...] = (
    (f"{BABEL_CDB}/cards.cdb", DATA_DIR / "cards.cdb"),
    (
        f"{CARD_SCRIPTS}/card_counter_constants.lua",
        CONSTANT_DIR / "card_counter_constants.lua",
    ),
    (
        f"{CARD_SCRIPTS}/archetype_setcode_constants.lua",
        CONSTANT_DIR / "archetype_setcode_constants.lua",
    ),
    (f"{CARD_SCRIPTS}/constant.lua", CONSTANT_DIR / "constant.lua"),
)


def download(url: str, destination: Path, timeout: int = 180) -> int:
    """하나의 파일을 받아 임시 파일에 쓴 뒤 교체한다 (중간 실패 시 원본 보존)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "yugioh-deck-agent"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    tmp.write_bytes(data)
    tmp.replace(destination)
    return len(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공식 카드 데이터 내려받기")
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 있는 파일도 다시 내려받는다",
    )
    args = parser.parse_args(argv)

    failures = 0
    for url, destination in DOWNLOADS:
        relative = destination.relative_to(PROJECT_ROOT)
        if destination.exists() and not args.force:
            print(f"건너뜀 (이미 있음): {relative}  --force 로 갱신")
            continue
        try:
            size = download(url, destination)
        except (urllib.error.URLError, OSError) as exc:
            failures += 1
            print(f"실패: {relative}\n      {url}\n      {exc}", file=sys.stderr)
            continue
        print(f"받음: {relative}  ({size:,} bytes)")

    if failures:
        print(
            f"\n{failures}개 파일을 받지 못했습니다.\n"
            "이 환경의 아웃바운드 네트워크 정책이 해당 호스트를 막고 있을 수 있습니다.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
