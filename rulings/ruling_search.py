"""
재정 검색.

:mod:`core.card_search` 와 **별도 계층이다.** 카드 검색은 비트마스크 필터와
카드명 정규화를 다루고, 재정 검색은 일본어 문서를 다룬다.

일본어에는 띄어쓰기가 없다
--------------------------
영어 낱말 토큰화를 그대로 쓰면 「墓地」와 「墓地へ送る」가 같은 토큰이 되거나
아예 쪼개지지 않는다. 형태소 분석기를 넣으면 사전 없이는 신뢰할 수 없고,
사전이 틀리면 **검색 결과가 조용히 비어버린다.** 그래서 부분 문자열
일치만 쓴다. 느리지만 틀리지 않고, 왜 걸렸는지 설명할 수 있다.

카드 이름으로 찾기
------------------
재정 데이터는 공식 페이지가 준 **일본어 카드명**을 들고 있으므로 일본어
이름은 그대로 찾을 수 있다. 한국어 이름으로 찾으려면 카드 계층의 이름 해석기를
주입한다 — 재정 계층이 카드 저장소를 직접 import 하지 않기 위해서다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable

from rulings.ruling_model import (
    CardRuling,
    CardRulingSupplement,
    RulingAvailability,
    RulingKind,
)
from rulings.ruling_repository import RulingRepository

CardNameResolver = Callable[[str], Iterable[int]]
"""카드 이름 -> 패스코드 목록. 카드 계층에서 주입한다."""

_RE_SPACE = re.compile(r"[\s　]+")


def normalize(text: str) -> str:
    """
    비교용 정규화. 전각/반각과 공백 차이만 없앤다.

    공식 재정 본문은 「１」 같은 전각 숫자와 「・」를 섞어 쓴다. 정규화하지
    않으면 "1ターンに1度" 로 검색했을 때 「１ターンに１度」가 걸리지 않는다.
    **원문은 바꾸지 않는다** — 비교할 때만 편다.
    """
    folded = unicodedata.normalize("NFKC", text)
    return _RE_SPACE.sub("", folded).lower()


@dataclass(slots=True)
class RulingHit:
    """검색 결과 한 건. 원문 재정과 왜 걸렸는지."""

    entry: CardRuling | CardRulingSupplement
    score: float
    matched_in: list[str] = field(default_factory=list)
    """``question`` / ``answer`` / ``supplement`` 중 어디서 걸렸는가."""
    excerpt: str = ""

    @property
    def ruling_id(self) -> str:
        return self.entry.ruling_id

    @property
    def card_id(self) -> int | None:
        return self.entry.card_id

    def __str__(self) -> str:
        return f"{self.ruling_id} (score={self.score:.1f}) {self.matched_in}"


class RulingSearch:
    """카드별 재정 검색 엔진."""

    QUESTION_WEIGHT = 2.0
    ANSWER_WEIGHT = 1.0
    SUPPLEMENT_WEIGHT = 1.5

    def __init__(
        self,
        repository: RulingRepository,
        card_name_resolver: CardNameResolver | None = None,
    ):
        self.repository = repository
        self.card_name_resolver = card_name_resolver
        self._normalized: dict[str, dict[str, str]] = {}
        for entry in repository:
            if isinstance(entry, CardRuling):
                self._normalized[entry.ruling_id] = {
                    "question": normalize(entry.question_original),
                    "answer": normalize(entry.answer_original),
                }
            else:
                self._normalized[entry.ruling_id] = {
                    "supplement": normalize(entry.text_original)
                }

    # ------------------------------------------------------------------
    # 식별자로 찾기
    # ------------------------------------------------------------------
    def by_ruling_id(self, ruling_id: str) -> CardRuling | CardRulingSupplement | None:
        return self.repository.ruling(ruling_id.strip())

    def by_card_id(self, card_id: int) -> list[CardRuling | CardRulingSupplement]:
        ruling_set = self.repository.by_card_id(card_id)
        return ruling_set.all_entries() if ruling_set else []

    def by_cid(self, cid: int) -> list[CardRuling | CardRulingSupplement]:
        ruling_set = self.repository.by_cid(cid)
        return ruling_set.all_entries() if ruling_set else []

    def availability(self, card_id: int) -> RulingAvailability:
        """**"재정 없음"과 "확인 안 함"을 구분해서** 돌려준다."""
        return self.repository.availability_for_card(card_id)

    # ------------------------------------------------------------------
    # 카드 이름으로 찾기
    # ------------------------------------------------------------------
    def by_card_name(self, name: str) -> list[CardRuling | CardRulingSupplement]:
        """
        일본어 이름은 재정 데이터로 바로 찾고, 그 밖의 언어는 주입된
        해석기로 패스코드를 구한 뒤 찾는다. 해석기가 없으면 일본어만 된다 —
        **문자열 유사도로 넘겨짚지 않는다.**
        """
        wanted = normalize(name)
        entries: list[CardRuling | CardRulingSupplement] = []
        for ruling_set in self.repository.ruling_sets:
            if ruling_set.name_ja and normalize(ruling_set.name_ja) == wanted:
                entries.extend(ruling_set.all_entries())
        if entries or self.card_name_resolver is None:
            return entries
        for card_id in self.card_name_resolver(name):
            entries.extend(self.by_card_id(card_id))
        return entries

    # ------------------------------------------------------------------
    # 속성으로 거르기
    # ------------------------------------------------------------------
    def by_category(self, category: str) -> list[CardRuling]:
        wanted = normalize(category)
        return [
            e for e in self.repository.qa_entries()
            if normalize(e.ruling_category) == wanted
        ]

    def updated_between(
        self, since: str | None = None, until: str | None = None
    ) -> list[CardRuling | CardRulingSupplement]:
        """``YYYY-MM-DD`` 문자열 비교. 날짜가 없는 재정은 포함하지 않는다."""
        out = []
        for entry in self.repository:
            date = entry.published_or_updated_at
            if not date:
                continue
            if since and date < since:
                continue
            if until and date > until:
                continue
            out.append(entry)
        return sorted(out, key=lambda e: (e.published_or_updated_at, e.ruling_id))

    def related_to(self, card_id: int) -> list[CardRuling | CardRulingSupplement]:
        """이 카드를 본문에서 언급한 **다른 카드의** 재정."""
        return [
            e for e in self.repository.referencing(card_id)
            if e.card_id != card_id
        ]

    # ------------------------------------------------------------------
    # 본문 검색
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        field: str = "any",
        card_id: int | None = None,
        category: str | None = None,
        since: str | None = None,
        until: str | None = None,
        kind: RulingKind | None = None,
        limit: int | None = 10,
    ) -> list[RulingHit]:
        """
        본문 부분 문자열 검색.

        ``field`` 는 ``any`` / ``question`` / ``answer`` / ``supplement``.
        """
        needle = normalize(query)
        if not needle:
            return []

        pool: list[CardRuling | CardRulingSupplement]
        if card_id is not None:
            pool = self.by_card_id(card_id)
        else:
            pool = list(self.repository)

        hits: list[RulingHit] = []
        for entry in pool:
            if kind is not None and entry.kind is not kind:
                continue
            if category is not None and (
                not isinstance(entry, CardRuling)
                or normalize(entry.ruling_category) != normalize(category)
            ):
                continue
            date = entry.published_or_updated_at
            if since and (not date or date < since):
                continue
            if until and (not date or date > until):
                continue

            fields = self._normalized[entry.ruling_id]
            score = 0.0
            matched: list[str] = []
            for name, weight in (
                ("question", self.QUESTION_WEIGHT),
                ("answer", self.ANSWER_WEIGHT),
                ("supplement", self.SUPPLEMENT_WEIGHT),
            ):
                if field not in ("any", name) or name not in fields:
                    continue
                occurrences = fields[name].count(needle)
                if occurrences:
                    score += weight * min(occurrences, 3)
                    matched.append(name)
            if not matched:
                continue
            hits.append(
                RulingHit(
                    entry=entry,
                    score=round(score, 2),
                    matched_in=matched,
                    excerpt=self._excerpt(entry, query),
                )
            )
        hits.sort(key=lambda h: (-h.score, h.ruling_id))
        return hits[:limit] if limit else hits

    # ------------------------------------------------------------------
    def _excerpt(
        self, entry: CardRuling | CardRulingSupplement, query: str, width: int = 120
    ) -> str:
        """원문에서 잘라낸 조각. **다시 쓰지 않는다** — 잘라내기만 한다."""
        if isinstance(entry, CardRuling):
            body = entry.answer_original or entry.question_original
        else:
            body = entry.text_original
        flat = _RE_SPACE.sub(" ", body).strip()
        position = normalize(flat).find(normalize(query))
        if position < 0:
            return flat[:width]
        # 정규화로 길이가 달라질 수 있으므로 원문에서 다시 찾는다.
        raw_position = flat.find(query)
        start = max(0, (raw_position if raw_position >= 0 else 0) - width // 3)
        piece = flat[start : start + width]
        prefix = "…" if start else ""
        suffix = "…" if start + width < len(flat) else ""
        return prefix + piece + suffix
