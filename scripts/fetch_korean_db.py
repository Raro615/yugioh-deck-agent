"""
공식 한국어 카드 데이터 수집기 (Yu-Gi-Oh! Neuron 카드 데이터베이스).

    python -m scripts.fetch_korean_db

수집 방식
---------
코나미 공식 DB 의 검색 결과 목록은 한 페이지에 카드 100장의
**카드명과 카드 텍스트를 함께** 담고 있다. 카드마다 상세 페이지를 여는 대신
목록을 훑으면 약 138회 요청으로 전체를 받을 수 있다.

카드 식별자 문제
----------------
코나미 DB 는 자체 카드 ID(``cid``)를 쓰고, ``cards.cdb`` 와 Lua 스크립트는
패스코드(8자리 카드 번호)를 쓴다. 둘의 연결은 YGOPRODeck 의
``misc_info.konami_id`` 로 얻는다.

하나의 ``cid`` 에 여러 패스코드가 달릴 수 있다(다른 일러스트 판본).
같은 카드이므로 한국어 카드명과 텍스트를 모든 판본에 동일하게 적용한다.

번역 정책
---------
이 스크립트는 공식 데이터를 **그대로 옮겨 적기만 한다.** 카드명이나 카드
텍스트를 자체적으로 번역하거나 다듬지 않는다.

중단과 재개
-----------
페이지 단위로 결과를 캐시하므로, 중간에 끊겨도 다시 실행하면 받지 못한
페이지부터 이어서 받는다. 요청 사이에는 기본 1초를 쉰다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KO_DIR = PROJECT_ROOT / "data" / "ko"
CACHE_DIR = KO_DIR / ".cache"
OUTPUT_PATH = KO_DIR / "ko-KR.json"
CID_MAP_PATH = CACHE_DIR / "cid_to_passcode.json"

KONAMI_BASE = "https://www.db.yugioh-card.com/yugiohdb/card_search.action"
# stype=1 + othercon=2 + 발매 시작일 = 전체 카드 열거
KONAMI_QUERY = {
    "ope": "1",
    "sess": "1",
    "stype": "1",
    "othercon": "2",
    "releaseYStart": "1999",
    "releaseMStart": "02",
    "releaseDStart": "04",
    "sort": "1",
    "rp": "100",
    "request_locale": "ko",
}
PAGE_SIZE = 100

YGOPRODECK_ALL = "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes"

USER_AGENT = "yugioh-deck-agent (card data collection; contact via repository)"

# 검색 결과 한 장에 해당하는 블록
_RE_ROW = re.compile(r'<div class="t_row[^"]*">(.*?)</div><!-- \.t_row', re.S)
_RE_CID = re.compile(r'class="cid"\s+value="(\d+)"')
_RE_CNM = re.compile(r"""class="cnm"\s+value='(.*?)'>""", re.S)
_RE_NAME_SPAN = re.compile(r'<span class="card_name">(.*?)</span>', re.S)
_RE_TEXT = re.compile(r'<dd class="box_card_text[^"]*">(.*?)</dd>', re.S)
_RE_TOTAL = re.compile(r"검색결과\s*([\d,]+)\s*건")


_RE_BR = re.compile(r"<br\s*/?>", re.I)


def _clean(raw: str) -> str:
    """
    HTML 조각에서 표시용 텍스트를 뽑는다. 원문을 바꾸지 않고 태그만 걷어낸다.

    카드 텍스트 안에는 실제 ``<br>`` 태그와, 엔티티로 이스케이프된
    ``&lt;br&gt;`` 이 섞여 있다. 후자는 언이스케이프 후에야 태그 모양이 되므로
    줄바꿈 변환을 언이스케이프 전후로 두 번 수행한다.
    언이스케이프 이후에는 ``<br>`` 만 노리고 일반 태그 제거는 하지 않는다
    (카드 텍스트에 들어 있을 수 있는 문자를 지우지 않기 위해).
    """
    text = _RE_BR.sub("\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = _RE_BR.sub("\n", text)
    # 줄 단위로 공백만 정리한다 (줄바꿈은 카드 텍스트의 의미 단위라 보존).
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def fetch(url: str, timeout: int = 60, retries: int = 4) -> str:
    """지수 백오프로 재시도하며 페이지를 받는다."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"요청 실패: {url}\n  {last_error}")


def parse_list_page(source: str) -> list[dict[str, str]]:
    """검색 결과 페이지에서 (cid, 카드명, 카드 텍스트)를 추출한다."""
    cards: list[dict[str, str]] = []
    for block in _RE_ROW.findall(source):
        cid_match = _RE_CID.search(block)
        if not cid_match:
            continue
        name_match = _RE_CNM.search(block) or _RE_NAME_SPAN.search(block)
        if not name_match:
            continue
        name = _clean(name_match.group(1))
        if not name:
            continue
        text_match = _RE_TEXT.search(block)
        cards.append(
            {
                "cid": cid_match.group(1),
                "name": name,
                "desc": _clean(text_match.group(1)) if text_match else "",
            }
        )
    return cards


def total_count(source: str) -> int | None:
    match = _RE_TOTAL.search(source)
    return int(match.group(1).replace(",", "")) if match else None


def page_url(page: int) -> str:
    query = dict(KONAMI_QUERY, page=str(page))
    return f"{KONAMI_BASE}?{urllib.parse.urlencode(query)}"


# ---------------------------------------------------------------------------
def build_cid_map(force: bool = False) -> dict[str, list[int]]:
    """
    코나미 ``cid`` -> 패스코드 목록 매핑을 만든다.

    YGOPRODeck 의 ``misc_info.konami_id`` 와 각 카드의 일러스트별 패스코드
    (``card_images[].id``)를 함께 모은다.
    """
    if CID_MAP_PATH.is_file() and not force:
        with CID_MAP_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)

    print("cid <-> 패스코드 매핑을 받는 중...")
    payload = json.loads(fetch(YGOPRODECK_ALL, timeout=180))
    mapping: dict[str, set[int]] = {}
    for card in payload.get("data", []):
        misc = (card.get("misc_info") or [{}])[0]
        konami_id = misc.get("konami_id")
        if not konami_id:
            continue
        key = str(int(konami_id))
        bucket = mapping.setdefault(key, set())
        bucket.add(int(card["id"]))
        for image in card.get("card_images", []):
            bucket.add(int(image["id"]))

    result = {key: sorted(values) for key, values in mapping.items()}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with CID_MAP_PATH.open("w", encoding="utf-8") as fh:
        json.dump(result, fh)
    print(f"  cid {len(result):,}개, 패스코드 {sum(len(v) for v in result.values()):,}개")
    return result


def collect_pages(
    max_pages: int | None = None, delay: float = 1.0, force: bool = False
) -> list[dict[str, str]]:
    """목록 페이지를 순회한다. 이미 받은 페이지는 캐시에서 읽는다."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    first_cache = CACHE_DIR / "page_001.json"
    if first_cache.is_file() and not force:
        with first_cache.open(encoding="utf-8") as fh:
            first = json.load(fh)
        total = first.get("total")
        cards = first["cards"]
    else:
        source = fetch(page_url(1))
        total = total_count(source)
        cards = parse_list_page(source)
        with first_cache.open("w", encoding="utf-8") as fh:
            json.dump({"total": total, "cards": cards}, fh, ensure_ascii=False)
        time.sleep(delay)

    if not total:
        raise RuntimeError("전체 건수를 읽지 못했습니다. 페이지 구조가 바뀌었을 수 있습니다.")

    last_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if max_pages is not None:
        last_page = min(last_page, max_pages)
    print(f"전체 {total:,}건 / {last_page:,}페이지")

    collected = list(cards)
    for page in range(2, last_page + 1):
        cache_path = CACHE_DIR / f"page_{page:03d}.json"
        if cache_path.is_file() and not force:
            with cache_path.open(encoding="utf-8") as fh:
                collected.extend(json.load(fh)["cards"])
            continue

        page_cards = parse_list_page(fetch(page_url(page)))
        if not page_cards:
            print(f"  경고: {page}페이지에서 카드를 찾지 못했습니다", file=sys.stderr)
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump({"total": total, "cards": page_cards}, fh, ensure_ascii=False)
        collected.extend(page_cards)

        if page % 10 == 0 or page == last_page:
            print(f"  {page:>3}/{last_page} 페이지  누적 {len(collected):,}장")
        time.sleep(delay)

    return collected


def join_with_passcodes(
    cards: list[dict[str, str]], cid_map: dict[str, list[int]]
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """
    수집한 한국어 카드를 패스코드 기준으로 정리한다.

    Returns:
        (패스코드별 항목, 패스코드를 찾지 못한 카드 목록)
    """
    entries: dict[str, dict[str, str]] = {}
    unmatched: list[dict[str, str]] = []
    for card in cards:
        passcodes = cid_map.get(card["cid"])
        if not passcodes:
            unmatched.append(card)
            continue
        # 같은 카드의 다른 일러스트 판본에도 동일한 한국어 표기를 적용한다.
        for passcode in passcodes:
            entries[str(passcode)] = {"name": card["name"], "desc": card["desc"]}
    return entries, unmatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공식 한국어 카드 데이터 수집")
    parser.add_argument("--pages", type=int, help="받을 페이지 수 제한 (시험용)")
    parser.add_argument(
        "--delay", type=float, default=1.0, help="요청 간격(초). 기본 1.0"
    )
    parser.add_argument("--force", action="store_true", help="캐시를 무시하고 다시 받는다")
    args = parser.parse_args(argv)

    KO_DIR.mkdir(parents=True, exist_ok=True)

    try:
        cid_map = build_cid_map(force=args.force)
        cards = collect_pages(
            max_pages=args.pages, delay=args.delay, force=args.force
        )
    except RuntimeError as exc:
        print(f"\n수집 실패: {exc}", file=sys.stderr)
        print(
            "이 환경의 네트워크 정책이 db.yugioh-card.com 또는 db.ygoprodeck.com 을"
            " 막고 있을 수 있습니다.",
            file=sys.stderr,
        )
        return 1

    entries, unmatched = join_with_passcodes(cards, cid_map)

    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=0, sort_keys=True)

    size_mb = OUTPUT_PATH.stat().st_size / 1_000_000
    print()
    print(f"수집한 한국어 카드 : {len(cards):,}장")
    print(f"패스코드 항목      : {len(entries):,}개 (일러스트 판본 포함)")
    print(f"패스코드 미매칭    : {len(unmatched):,}장")
    print(f"저장               : {OUTPUT_PATH.relative_to(PROJECT_ROOT)} ({size_mb:.1f} MB)")
    if unmatched[:3]:
        print("  미매칭 예시:", ", ".join(c["name"] for c in unmatched[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
