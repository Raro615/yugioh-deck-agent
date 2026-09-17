"""
공식 OCG 카드 데이터베이스 재정 어댑터.

**이 파일만 공식 사이트의 HTML 구조를 안다.** ``core/`` · ``analysis/`` ·
``rules/`` · ``rulings/`` 는 어느 태그에 무엇이 들어 있는지 알지 못하고,
정규화된 :mod:`rulings.ruling_model` 만 받는다. 사이트 개편이 오면 고칠 곳이
여기 하나다.

조사한 URL 구조 (2026-09 기준, ``request_locale=ja``)
-----------------------------------------------------

카드별 Q&A 목록::

    /yugiohdb/faq_search.action?ope=4&cid=<cid>&request_locale=ja&page=<n>&rp=<n>

    - ``全N件中 a～b件を表示``          -> 전체 Q&A 수
    - ``div.t_row``                    -> Q&A 한 건
        ``span.name``                  -> 질문 제목
        ``div.tag_name span``          -> 공식 분류 태그
        ``div.date``                   -> 更新日
        ``input.link_value``           -> ``ope=5&fid=<fid>``
    - ``meta[name=keywords]`` 첫 항목  -> 일본어 카드명
    - ``div#card_text``                -> 일본어 카드 텍스트
    - ``div.supplement``               -> 補足情報 (**있는 카드만**)
        ``span.update``                -> 補足 갱신일
        ``div#supplement``             -> 補足 본문

Q&A 상세::

    /yugiohdb/faq_search.action?ope=5&fid=<fid>&request_locale=ja

    - ``h1``                           -> 질문 제목
    - ``div#question_text``            -> 질문 본문
    - ``div#answer_text``              -> 답변 본문
    - ``div#tag_update .tag .btn``     -> 태그
    - ``div#tag_update .date``         -> 更新日
    - 본문 안의 ``a[href*="ope=4&cid="]`` -> 공식이 직접 건 관련 카드 링크

수집 정책
---------
- 요청 사이에 기본 1.2초 대기. 목록은 ``rp=100`` 으로 받아 요청 수를 줄인다.
- 받은 HTML 은 캐시에 두고 재파싱 시 다시 받지 않는다.
- 실패는 **조용히 빈 결과가 되지 않는다.** ``SOURCE_UNAVAILABLE`` 로 표시한다.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    CardRulingSupplement,
    RulingAvailability,
    RulingGame,
    RulingProvenance,
    RulingSource,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "rulings" / ".cache"

BASE = "https://www.db.yugioh-card.com/yugiohdb"
USER_AGENT = (
    "Mozilla/5.0 (compatible; yugioh-deck-agent/1.0; "
    "+https://github.com/Raro615/yugioh-deck-agent)"
)
DEFAULT_ROWS_PER_PAGE = 100
MAX_PAGES = 50

# --- HTML 패턴 (이 파일 밖으로 새어 나가지 않는다) -------------------------
_RE_TOTAL = re.compile(r"全([\d,]+)件中")
_RE_ROW = re.compile(r'<div class="t_row">(.*?)</div>\s*</div>\s*<input', re.S)
_RE_ROW_BLOCK = re.compile(r'<div class="t_row">(.*?)<input[^>]*class="link_value"[^>]*value="([^"]*)"', re.S)
_RE_ROW_NAME = re.compile(r'<span class="name">(.*?)</span>', re.S)
_RE_ROW_TAG = re.compile(r'<div class="tag_name\s*"><span>(.*?)</span>', re.S)
_RE_ROW_DATE = re.compile(r'<div class="div date">.*?更新日:\s*</span>\s*([\d-]+)', re.S)
_RE_FID = re.compile(r"ope=5&(?:amp;)?fid=(\d+)")
_RE_KEYWORDS = re.compile(r'<meta name="keywords" content="([^"]*)"')
_RE_CARD_TEXT = re.compile(r'<div id="card_text"[^>]*>(.*?)</div>', re.S)
_RE_SUPPLEMENT = re.compile(
    r'<div class="supplement">.*?<span class="update\s*">([\d-]*)</span>.*?'
    r'<div id="supplement"[^>]*>(.*?)</div>',
    re.S,
)
_RE_Q_TITLE = re.compile(r'<h1[^>]*class="[^"]*keyword[^"]*"[^>]*>(.*?)</h1>', re.S)
_RE_QUESTION = re.compile(r'<div id="question_text"[^>]*>(.*?)</div>', re.S)
_RE_ANSWER = re.compile(r'<div id="answer_text"[^>]*>(.*?)</div>', re.S)
# ``#tag_update`` 안에는 태그 버튼용 ``div`` 가 한 겹 더 있고 그 **뒤에** 날짜가
# 온다. 가장 가까운 ``</div></div>`` 에서 끊으면 날짜를 잃는다.
_RE_TAG_UPDATE = re.compile(
    r'<div id="tag_update">(.*?)(?:<!--#qa_box-->|</article>)', re.S
)
_RE_TAG_BTN = re.compile(r'class="btn[^"]*">\s*(.*?)\s*</a>', re.S)
_RE_DATE_SPAN = re.compile(r'<span class="date">([\d-]+)</span>')
_RE_RELATED_CID = re.compile(r'href="[^"]*ope=4&(?:amp;)?cid=(\d+)"')
_RE_TAG = re.compile(r"<[^>]+>")
_RE_BR = re.compile(r"<br\s*/?>", re.I)


# HTML 이 접어주는 공백. **전각 공백(U+3000)은 여기 없다** — HTML 표준의
# white space 집합은 space·tab·LF·CR·FF 뿐이라 브라우저도 U+3000 을 접지 않는다.
_HTML_SPACE = " \t\r\f"
_RE_HTML_SPACE = re.compile(f"[{_HTML_SPACE}]+")


def _to_text(fragment: str) -> str:
    """
    HTML 조각을 **브라우저가 보여주는 그대로**의 평문으로 바꾼다.

    두 가지만 한다.

    - ``<br>`` 를 줄바꿈으로. 공식 답변이 문단을 나누는 유일한 수단이라
      없애면 (A)/(B) 같은 구분이 통째로 뭉개진다.
    - HTML 이 어차피 접어버리는 공백(space·tab·CR·FF)만 접는다.

    **전각 공백 U+3000 은 건드리지 않는다.** 공식 카드명에 들어가기 때문이다::

        魔弾の射手　カスパール

    이것을 반각 공백으로 바꾸면 공식 원문이 아니라 우리가 고쳐 쓴 문자열이
    되고, 카드명 대조도 어긋난다. ``str.strip()`` 은 U+3000 도 지우므로
    쓰지 않고 :data:`_HTML_SPACE` 만 지정해 벗겨낸다.
    """
    text = _RE_BR.sub("\n", fragment)
    text = _RE_TAG.sub("", text)
    text = html.unescape(text)
    text = _RE_HTML_SPACE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip(_HTML_SPACE) for line in text.split("\n")]
    return "\n".join(lines).strip(_HTML_SPACE + "\n")


class RulingFetchError(RuntimeError):
    """공식 사이트에서 가져오지 못했다. 재정이 없다는 뜻이 **아니다.**"""


@dataclass(slots=True)
class CardPage:
    """카드 Q&A 목록 페이지에서 읽은 것 (파싱 전 원재료)."""

    cid: int
    available: bool
    url: str
    name_ja: str | None = None
    card_text_ja: str = ""
    total: int | None = None
    error: str = ""


@dataclass(slots=True)
class RowSummary:
    """목록 한 줄. 상세를 받기 전 최소 정보."""

    fid: int
    question_title: str
    category: str
    updated_at: str


class OfficialOcgRulingAdapter:
    """공식 OCG 데이터베이스에서 카드별 재정을 가져온다."""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] | None = None,
        delay: float = 1.2,
        timeout: float = 30.0,
        use_cache: bool = True,
        opener=None,
    ):
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.delay = delay
        self.timeout = timeout
        self.use_cache = use_cache
        self._opener = opener or self._urlopen
        self._last_request = 0.0
        self.request_count = 0

    # ------------------------------------------------------------------
    # 네트워크 (캐시 · 속도 제한)
    # ------------------------------------------------------------------
    def _urlopen(self, url: str) -> str:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{key}.html"

    def fetch(self, url: str) -> str:
        """캐시 -> 없으면 요청. 요청 사이에는 반드시 쉰다."""
        return self.fetch_with_time(url)[0]

    def fetch_with_time(self, url: str) -> tuple[str, str]:
        """
        ``(본문, 가져온 시각)``.

        캐시에서 읽었다면 **캐시 파일의 시각**을 돌려준다. 다시 파싱한 시각을
        ``retrieved_at`` 으로 적으면 "공식 사이트에서 그때 확인했다" 는 거짓
        기록이 된다 — 실제로는 그때 네트워크를 타지 않았다.
        """
        path = self._cache_path(url)
        if self.use_cache and path.is_file():
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            return path.read_text(encoding="utf-8"), stamp.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            source = self._opener(url)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise RulingFetchError(f"{url} 요청 실패: {error}") from error
        finally:
            self._last_request = time.monotonic()
        self.request_count += 1

        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return source, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------
    @staticmethod
    def list_url(cid: int, page: int = 1, rows: int = DEFAULT_ROWS_PER_PAGE) -> str:
        query = urllib.parse.urlencode(
            {"ope": 4, "cid": cid, "request_locale": "ja", "page": page, "rp": rows}
        )
        return f"{BASE}/faq_search.action?{query}"

    @staticmethod
    def detail_url(fid: int) -> str:
        query = urllib.parse.urlencode({"ope": 5, "fid": fid, "request_locale": "ja"})
        return f"{BASE}/faq_search.action?{query}"

    # ------------------------------------------------------------------
    # 파싱 (순수 함수 — 네트워크를 타지 않는다)
    # ------------------------------------------------------------------
    @staticmethod
    def parse_card_page(cid: int, url: str, source: str) -> CardPage:
        keywords = _RE_KEYWORDS.search(source)
        name_ja = None
        if keywords:
            first = html.unescape(keywords.group(1)).split(",")[0].strip()
            name_ja = first or None
        text = _RE_CARD_TEXT.search(source)
        total = _RE_TOTAL.search(source)
        return CardPage(
            cid=cid,
            available=True,
            url=url,
            name_ja=name_ja,
            card_text_ja=_to_text(text.group(1)) if text else "",
            total=int(total.group(1).replace(",", "")) if total else None,
        )

    @staticmethod
    def parse_rows(source: str) -> list[RowSummary]:
        rows: list[RowSummary] = []
        for block, link in _RE_ROW_BLOCK.findall(source):
            fid_match = _RE_FID.search(link)
            if not fid_match:
                continue
            name = _RE_ROW_NAME.search(block)
            tag = _RE_ROW_TAG.search(block)
            date = _RE_ROW_DATE.search(block)
            rows.append(
                RowSummary(
                    fid=int(fid_match.group(1)),
                    question_title=_to_text(name.group(1)) if name else "",
                    category=_to_text(tag.group(1)) if tag else "",
                    updated_at=date.group(1) if date else "",
                )
            )
        return rows

    @staticmethod
    def parse_supplement(source: str) -> tuple[str, str] | None:
        """``(갱신일, 본문)``. 補足情報 가 없는 카드는 ``None``."""
        match = _RE_SUPPLEMENT.search(source)
        if not match:
            return None
        text = _to_text(match.group(2))
        return (match.group(1), text) if text else None

    @staticmethod
    def parse_detail(fid: int, source: str) -> dict:
        question_body = _RE_QUESTION.search(source)
        answer_body = _RE_ANSWER.search(source)
        if question_body is None or answer_body is None:
            raise RulingFetchError(
                f"fid={fid} 상세 페이지에서 질문/답변을 찾지 못했습니다. "
                "사이트 구조가 바뀌었을 수 있습니다."
            )
        title = _RE_Q_TITLE.search(source)
        tag_block = _RE_TAG_UPDATE.search(source)
        category = ""
        updated_at = ""
        if tag_block:
            tags = [_to_text(t) for t in _RE_TAG_BTN.findall(tag_block.group(1))]
            category = next((t for t in tags if t), "")
            date = _RE_DATE_SPAN.search(tag_block.group(1))
            updated_at = date.group(1) if date else ""
        related = sorted(
            {
                int(c)
                for c in _RE_RELATED_CID.findall(
                    question_body.group(1) + answer_body.group(1)
                )
            }
        )
        return {
            "question_title": _to_text(title.group(1)) if title else "",
            "question": _to_text(question_body.group(1)),
            "answer": _to_text(answer_body.group(1)),
            "ruling_category": category,
            "updated_at": updated_at,
            "related_card_cids": related,
        }

    # ------------------------------------------------------------------
    # 수집
    # ------------------------------------------------------------------
    def fetch_card_page(self, cid: int) -> CardPage:
        url = self.list_url(cid)
        try:
            source = self.fetch(url)
        except RulingFetchError as error:
            return CardPage(cid=cid, available=False, url=url, error=str(error))
        return self.parse_card_page(cid, url, source)

    def fetch_ruling_set(
        self,
        cid: int,
        card_id: int | None = None,
        rows_per_page: int = DEFAULT_ROWS_PER_PAGE,
        identity=None,
        allow_unverified_identity: bool = False,
    ) -> CardRulingSet:
        """
        카드 하나의 재정 전부를 가져온다.

        **식별자 방어선.** ``card_id`` 와 ``identity`` 가 둘 다 주어지면,
        그 링크가 검증된 경우에만 공식 사이트에 요청한다. 검증되지 않았거나
        충돌이면 **네트워크를 타지 않고** ``IDENTITY_UNVERIFIED`` /
        ``IDENTITY_CONFLICT`` 를 돌려준다.

        검증되지 않은 ``cid`` 로 물으면 다른 카드의 공식 재정이 이 카드의
        것으로 저장된다. 식별자 계층에서 한 번 막고 여기서 또 막는 이유는,
        이 경계가 **공식 출처에 실제로 요청이 나가는 유일한 지점**이기
        때문이다.

        ``allow_unverified_identity`` 는 의도적으로 검증 전 데이터를 다루는
        도구(캐시 재파싱 등)를 위한 것이고, 그때도 결과의
        ``identity_status`` 에 사실이 남아 ``authoritative`` 가 거짓이 된다.

        실패해도 빈 결과를 돌려주지 않는다. ``availability`` 가 여섯 가지를
        구분한다 — 재정 있음 / 없음 / 조회 실패 / 미조회 / 식별자 미검증 /
        식별자 충돌.
        """
        list_url = self.list_url(cid, page=1, rows=rows_per_page)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        identity_status = _identity_status(identity, card_id)
        result = CardRulingSet(
            official_cid=cid,
            card_id=card_id,
            checked_at=now,
            source_url=list_url,
            identity_status=identity_status,
        )

        if identity is not None and card_id is not None and identity_status != "verified":
            if not allow_unverified_identity:
                result.availability = (
                    RulingAvailability.IDENTITY_CONFLICT
                    if identity_status == "conflict"
                    else RulingAvailability.IDENTITY_UNVERIFIED
                )
                result.error = (
                    f"card_id={card_id} 와 cid={cid} 의 연결이 "
                    f"{identity_status} 입니다. 공식 사이트에 묻지 않았습니다."
                )
                return result

        try:
            first, list_retrieved_at = self.fetch_with_time(list_url)
        except RulingFetchError as error:
            result.availability = RulingAvailability.SOURCE_UNAVAILABLE
            result.error = str(error)
            return result

        page = self.parse_card_page(cid, list_url, first)
        result.name_ja = page.name_ja
        result.card_text_ja = page.card_text_ja
        result.reported_total = page.total

        supplement = self.parse_supplement(first)
        if supplement is not None:
            updated_at, text = supplement
            result.supplement = CardRulingSupplement(
                ruling_id=f"OCG-SUP-{cid}",
                card_id=card_id,
                official_cid=cid,
                text_original=text,
                published_or_updated_at=updated_at,
                provenance=RulingProvenance(
                    source=RulingSource.KONAMI_OCG_DATABASE,
                    language="ja",
                    authority="official",
                    data_type="card_supplement",
                    game=RulingGame.OCG,
                    source_url=list_url,
                    retrieved_at=list_retrieved_at,
                ),
            )

        rows = self.parse_rows(first)
        total = page.total or len(rows)
        fetched_pages = 1
        while len(rows) < total and fetched_pages < MAX_PAGES:
            fetched_pages += 1
            next_url = self.list_url(cid, page=fetched_pages, rows=rows_per_page)
            try:
                more = self.parse_rows(self.fetch(next_url))
            except RulingFetchError as error:
                result.availability = RulingAvailability.SOURCE_UNAVAILABLE
                result.error = f"{fetched_pages}쪽 목록 실패: {error}"
                return result
            if not more:
                break
            rows.extend(more)

        for row in rows:
            detail_url = self.detail_url(row.fid)
            try:
                page_source, detail_retrieved_at = self.fetch_with_time(detail_url)
                detail = self.parse_detail(row.fid, page_source)
            except RulingFetchError as error:
                result.availability = RulingAvailability.SOURCE_UNAVAILABLE
                result.error = f"fid={row.fid} 상세 실패: {error}"
                return result
            related_cids = detail["related_card_cids"]
            result.rulings.append(
                CardRuling(
                    ruling_id=f"OCG-QA-{row.fid}",
                    card_id=card_id,
                    official_cid=cid,
                    question_original=detail["question"],
                    answer_original=detail["answer"],
                    published_or_updated_at=detail["updated_at"] or row.updated_at,
                    ruling_category=detail["ruling_category"] or row.category,
                    related_card_cids=related_cids,
                    related_card_ids=_map_related(related_cids, identity),
                    provenance=RulingProvenance(
                        source=RulingSource.KONAMI_OCG_DATABASE,
                        language="ja",
                        authority="official",
                        data_type="card_ruling",
                        game=RulingGame.OCG,
                        source_url=detail_url,
                        retrieved_at=detail_retrieved_at,
                    ),
                )
            )

        if result.supplement is not None:
            result.supplement.related_card_ids = _map_related(
                result.supplement.related_card_cids, identity
            )
        result.checked_at = list_retrieved_at
        result.availability = (
            RulingAvailability.EXISTS
            if result.has_rulings
            else RulingAvailability.NOT_FOUND
        )
        return result


def _identity_status(identity, card_id: int | None) -> str:
    """
    이 패스코드의 링크 검증 상태를 문자열로. 재정 계층이 식별자 계층을
    import 하지 않으므로 값만 옮긴다.
    """
    if identity is None or card_id is None:
        return "unknown"
    status = identity.status_for(card_id)
    return status.value if status is not None else "unknown"


def _map_related(cids: list[int], identity) -> list[int]:
    """관련 ``cid`` 를 패스코드로 옮긴다. 매핑이 없으면 빈 목록 — 추측하지 않는다."""
    if identity is None:
        return []
    out: list[int] = []
    for cid in cids:
        card_id = identity.primary_card_id(cid)
        if card_id is not None:
            out.append(card_id)
    return sorted(set(out))
