"""
``data/identity/cid_map.json`` 을 만든다 — 패스코드 <-> 코나미 ``cid``.

입력은 ``scripts/fetch_korean_db.py`` 가 이미 받아둔
``data/ko/.cache/cid_to_passcode.json`` 이다 (없으면 그 수집기를 먼저 돌린다).
그 캐시는 ``.gitignore`` 대상이라 사라질 수 있으므로, 여기서 **커밋되는
1급 산출물**로 옮긴다. 재정 계층이 이 매핑 없이는 아무것도 못 하기 때문이다.

링크의 출처가 보조 출처라는 사실을 숨기지 않는다. 대신 ``--verify`` 로
공식 페이지의 일본어 카드명과 Lua 의 일본어 카드명을 **완전 일치** 대조해
검증 상태를 기록한다.

사용법::

    python -m scripts.build_card_identity                 # 매핑 생성
    python -m scripts.build_card_identity --verify 300    # 300장 교차 검증
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core.card_identity import (
    CardIdentity,
    CardIdentityMapping,
    LinkSource,
    LinkStatus,
    same_card_name,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CID_CACHE = PROJECT_ROOT / "data" / "ko" / ".cache" / "cid_to_passcode.json"

NOTE = (
    "cid 값은 코나미 공식 데이터베이스에서 왔다. cid 와 패스코드를 잇는 링크는 "
    "보조 출처(YGOPRODeck misc_info.konami_id)에서 온 추론이며, status=verified 인 "
    "항목만 공식 페이지의 일본어 카드명과 Lua 의 일본어 카드명이 완전 일치함을 "
    "확인한 것이다."
)


def build(cache_path: Path = CID_CACHE) -> CardIdentityMapping:
    if not cache_path.is_file():
        raise SystemExit(
            f"{cache_path} 가 없습니다.\n"
            "python -m scripts.fetch_korean_db 를 먼저 실행하세요."
        )
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    entries: list[CardIdentity] = []
    seen: set[int] = set()
    for cid, passcodes in raw.items():
        for passcode in passcodes:
            passcode = int(passcode)
            if passcode in seen:
                continue
            seen.add(passcode)
            entries.append(
                CardIdentity(
                    card_id=passcode,
                    cid=int(cid),
                    link_source=LinkSource.YGOPRODECK_KONAMI_ID,
                    status=LinkStatus.UNVERIFIED,
                )
            )
    return CardIdentityMapping(
        entries,
        built_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        note=NOTE,
    )


def verify(
    mapping: CardIdentityMapping,
    limit: int,
    delay: float = 1.2,
    only: list[int] | None = None,
) -> dict[str, int]:
    """
    공식 페이지의 일본어 카드명과 Lua 의 일본어 카드명을 대조한다.

    Lua 에 일본어 이름이 없는 카드(노멀 몬스터 등 12,968/14,520 만 보유)는
    대조할 수 없으므로 건너뛴다 — **확인 못 한 것을 확인했다고 적지 않는다.**
    """
    from core.card_repository import CardRepository
    from sources.ocg_ruling_adapter import OfficialOcgRulingAdapter

    repository = CardRepository.build(script_dir=PROJECT_ROOT)
    adapter = OfficialOcgRulingAdapter(delay=delay)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    counts = {"verified": 0, "conflict": 0, "skipped_no_lua_name": 0, "unavailable": 0}
    checked = 0
    wanted = set(only or ())
    entries = (
        [e for e in mapping if e.card_id in wanted] if wanted else list(mapping)
    )
    for entry in entries:
        if limit and checked >= limit:
            break
        if entry.status is not LinkStatus.UNVERIFIED:
            continue
        card = repository.get(entry.card_id)
        lua_name = card.script.name_ja if card and card.script else None
        if not lua_name:
            counts["skipped_no_lua_name"] += 1
            continue
        page = adapter.fetch_card_page(entry.cid)
        checked += 1
        if not page.available:
            counts["unavailable"] += 1
            continue
        entry.name_ja = page.name_ja
        entry.verified_at = now
        if same_card_name(page.name_ja, lua_name):
            entry.status = LinkStatus.VERIFIED
            counts["verified"] += 1
        else:
            entry.status = LinkStatus.CONFLICT
            entry.note = f"Lua={lua_name!r} != 공식={page.name_ja!r}"
            counts["conflict"] += 1
            print(f"  [충돌] {entry.card_id} cid={entry.cid} {entry.note}", file=sys.stderr)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="패스코드 <-> 공식 cid 매핑을 만든다.")
    parser.add_argument("--verify", type=int, default=0, metavar="N",
                        help="공식 페이지와 대조할 카드 수 (0 이면 대조하지 않음)")
    parser.add_argument("--verify-card-id", type=int, action="append", default=[],
                        metavar="PASSCODE",
                        help="이 패스코드들만 대조한다 (여러 번 지정 가능)")
    parser.add_argument("--delay", type=float, default=1.2, help="요청 간 대기 (초)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    out_path = Path(args.out) if args.out else None
    existing = CardIdentityMapping.try_load(out_path)
    mapping = existing if existing is not None else build()
    if existing is not None:
        print(f"기존 매핑을 읽었습니다: {mapping.stats()}")
    else:
        print(f"캐시에서 매핑을 만들었습니다: {mapping.stats()}")

    if args.verify or args.verify_card_id:
        target = args.verify_card_id or None
        limit = args.verify or (len(target) if target else 0)
        print(f"공식 페이지와 대조 중 (최대 {limit or '제한 없음'}장)...")
        counts = verify(mapping, limit, args.delay, only=target)
        print(f"  {counts}")

    path = mapping.save(out_path)
    print(f"{path} 에 {len(mapping):,}개 항목을 저장했습니다.")
    print(f"  {mapping.stats()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
