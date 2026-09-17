"""
규칙 검색.

:mod:`core.card_search` 와 **별도 계층이다.** 카드 검색은 비트마스크 필터와
카드명 정규화를 다루고, 규칙 검색은 문서 텍스트를 다룬다. 한 엔진에 합치면
"레벨 5 기계족" 같은 카드 질의와 "체인이 어떻게 처리되는가" 같은 규칙 질의가
서로의 결과를 오염시킨다.

지원하는 축 (요구된 최소 집합)::

    rule_id   정확한 ID 로 바로 꺼내기
    title     제목에 들어간 말
    keyword   제목 + 본문 전체에서 낱말 단위로
    category  분류
    section   특정 절과 그 하위 절로 범위 제한
    text      본문 구절 (줄바꿈 무시)

**요약을 만들어 돌려주지 않는다.** 돌려주는 것은 언제나 원문 절과 그 안에서
찾은 위치다. 판단은 호출자 몫이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rules.rule_model import RuleCategory, RuleSection
from rules.rule_repository import RuleRepository

# 검색에서 걸러낼 너무 흔한 낱말. 규칙 문서에 특화된 최소한만 둔다.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "is", "are", "be", "can",
        "you", "your", "it", "this", "that", "and", "or", "if", "for", "with",
        "as", "at", "by", "from", "not", "but", "they", "their", "when",
    }
)

_TOKEN = re.compile(r"[A-Za-z0-9’'&-]+")

# 한국어 질의 -> 룰북이 실제로 쓰는 영어 낱말.
#
# **룰북을 번역한 것이 아니다.** 룰북 원문은 영어 그대로 보존되며, 이 표는
# 질의어를 룰북의 어휘로 바꿔주는 검색 보조 장치일 뿐이다
# (``core.constants`` 의 ``KO_RACE_ALIASES`` 와 같은 역할).
# 여기 없는 한국어 낱말은 그냥 걸리지 않는다 — 없는 뜻을 지어내지 않는다.
KO_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "체인": ("chain",),
    "체인링크": ("chain", "link"),
    "체인 링크": ("chain", "link"),
    "스펠스피드": ("spell", "speed"),
    "스펠 스피드": ("spell", "speed"),
    "우선권": ("priority",),
    "발동": ("activate", "activation"),
    "해결": ("resolve", "resolution"),
    "대상": ("target",),
    "코스트": ("cost",),
    "비용": ("cost",),
    "효과": ("effect",),
    "지속효과": ("continuous", "effect"),
    "기동효과": ("ignition", "effect"),
    "유발효과": ("trigger", "effect"),
    "유발즉시효과": ("quick", "effect"),
    "리버스효과": ("flip", "effect"),
    "턴": ("turn",),
    "페이즈": ("phase",),
    "드로우": ("draw",),
    "스탠바이": ("standby",),
    "메인페이즈": ("main", "phase"),
    "배틀페이즈": ("battle", "phase"),
    "데미지스텝": ("damage", "step"),
    "데미지 스텝": ("damage", "step"),
    "엔드페이즈": ("end", "phase"),
    "전투": ("battle",),
    "공격": ("attack",),
    "공격력": ("atk",),
    "수비력": ("def",),
    "소환": ("summon",),
    "일반소환": ("normal", "summon"),
    "특수소환": ("special", "summon"),
    "세트": ("set",),
    "반전소환": ("flip", "summon"),
    "어드밴스소환": ("tribute", "summon"),
    "제물소환": ("tribute", "summon"),
    "릴리스": ("tribute",),
    "융합소환": ("fusion", "summon"),
    "싱크로소환": ("synchro", "summon"),
    "엑시즈소환": ("xyz", "summon"),
    "링크소환": ("link", "summon"),
    "펜듈럼소환": ("pendulum", "summon"),
    "의식소환": ("ritual", "summon"),
    "묘지": ("graveyard",),
    "제외": ("banished",),
    "패": ("hand",),
    "덱": ("deck",),
    "엑스트라덱": ("extra", "deck"),
    "필드": ("field",),
    "존": ("zone",),
    "몬스터존": ("monster", "zone"),
    "마법함정존": ("spell", "trap", "zone"),
    "필드존": ("field", "zone"),
    "펜듈럼존": ("pendulum", "zone"),
    "앞면": ("face-up",),
    "뒷면": ("face-down",),
    "표시형식": ("battle", "position"),
    "공격표시": ("attack", "position"),
    "수비표시": ("defense", "position"),
    "컨트롤": ("control",),
    "소유자": ("possess", "owner"),
    "파괴": ("destroy",),
    "묘지로": ("send", "graveyard"),
    "버리기": ("discard",),
    "카운터": ("counter",),
    "토큰": ("token",),
    "라이프": ("lp", "life", "points"),
    "승리": ("win", "victory"),
    "패배": ("lose",),
    "무작위": ("random",),
    "공개": ("reveal", "public"),
    "서치": ("search",),
    "덱조작": ("shuffle",),
    "관통": ("piercing",),
    "장착": ("equip",),
    "동시": ("simultaneously",),
    "강제": ("mandatory",),
    "임의": ("optional",),
    "한턴에한번": ("once", "per", "turn"),
}


def tokenize(text: str) -> list[str]:
    return [t.lower().strip("'’-") for t in _TOKEN.findall(text) if t.strip("'’-")]


def expand_query(query: str) -> list[str]:
    """
    질의를 룰북의 어휘로 편다. 한국어 낱말은 :data:`KO_QUERY_TERMS` 를 거치고,
    영어는 그대로 쓴다. 매핑이 없는 한국어는 버린다 — 추측하지 않는다.
    """
    terms = list(tokenize(query))
    condensed = query.replace(" ", "")
    for korean, english in KO_QUERY_TERMS.items():
        if korean in query or korean in condensed:
            terms.extend(english)
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


@dataclass(slots=True)
class RuleHit:
    """검색 결과 한 건. 원문 절과 왜 걸렸는지."""

    section: RuleSection
    score: float
    matched_terms: list[str] = field(default_factory=list)
    excerpt: str = ""

    @property
    def rule_id(self) -> str:
        return self.section.rule_id

    def __str__(self) -> str:
        return f"{self.section.rule_id} {self.section.title} (score={self.score:.2f})"


class RuleSearch:
    """규칙 문서 검색 엔진."""

    TITLE_WEIGHT = 3.0
    BODY_WEIGHT = 1.0

    def __init__(self, repository: RuleRepository):
        self.repository = repository
        self._title_tokens: dict[str, set[str]] = {}
        self._body_counts: dict[str, dict[str, int]] = {}
        self._normalized: dict[str, str] = {}
        for section in repository:
            self._title_tokens[section.rule_id] = set(tokenize(section.title))
            counts: dict[str, int] = {}
            for token in tokenize(section.normalized_text):
                counts[token] = counts.get(token, 0) + 1
            self._body_counts[section.rule_id] = counts
            self._normalized[section.rule_id] = section.normalized_text.lower()

    # ------------------------------------------------------------------
    # 축별 검색
    # ------------------------------------------------------------------
    def by_rule_id(self, rule_id: str) -> RuleSection | None:
        return self.repository.get(rule_id.strip().upper())

    def by_title(self, fragment: str) -> list[RuleSection]:
        needle = " ".join(fragment.lower().split())
        return [s for s in self.repository if needle in s.title.lower()]

    def by_text(self, phrase: str) -> list[RuleSection]:
        """
        본문 구절 검색. 원문은 인쇄된 줄바꿈을 그대로 갖고 있으므로,
        비교할 때만 공백을 편다 — 그래야 줄에 걸쳐 있는 구절도 찾는다.
        """
        needle = " ".join(phrase.lower().split())
        return [
            s for s in self.repository if needle in self._normalized[s.rule_id]
        ]

    def by_category(self, category: RuleCategory | str) -> list[RuleSection]:
        return self.repository.by_category(category)

    def within_section(self, rule_id: str) -> list[RuleSection]:
        """그 절과 모든 하위 절 (깊이 제한 없음)."""
        root = self.repository.require(rule_id)
        collected: list[RuleSection] = [root]
        queue = list(root.subsections)
        while queue:
            section = self.repository.require(queue.pop(0))
            collected.append(section)
            queue.extend(section.subsections)
        return collected

    # ------------------------------------------------------------------
    # 낱말 검색
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        category: RuleCategory | str | None = None,
        within: str | None = None,
        limit: int | None = 10,
    ) -> list[RuleHit]:
        """
        낱말 단위 검색. 제목에서 걸리면 더 높은 점수를 준다.

        ``category`` / ``within`` 으로 범위를 좁힐 수 있다.
        """
        exact = self.by_rule_id(query)
        if exact is not None:
            return [RuleHit(exact, score=1.0, matched_terms=[exact.rule_id],
                            excerpt=self._excerpt(exact, []))]

        terms = [t for t in expand_query(query) if t not in _STOPWORDS]
        if not terms:
            return []

        pool: list[RuleSection] = list(self.repository)
        if category is not None:
            allowed = {s.rule_id for s in self.by_category(category)}
            pool = [s for s in pool if s.rule_id in allowed]
        if within is not None:
            allowed = {s.rule_id for s in self.within_section(within)}
            pool = [s for s in pool if s.rule_id in allowed]

        phrase = " ".join(terms)
        hits: list[RuleHit] = []
        for section in pool:
            titles = self._title_tokens[section.rule_id]
            counts = self._body_counts[section.rule_id]
            matched = [t for t in terms if t in titles or t in counts]
            if not matched:
                continue
            score = 0.0
            for term in terms:
                if term in titles:
                    score += self.TITLE_WEIGHT
                score += self.BODY_WEIGHT * min(counts.get(term, 0), 3)
            # 모든 낱말이 걸린 절을 우선한다.
            score *= len(matched) / len(terms)
            if phrase in self._normalized[section.rule_id]:
                score += self.TITLE_WEIGHT
            hits.append(
                RuleHit(
                    section=section,
                    score=round(score, 3),
                    matched_terms=matched,
                    excerpt=self._excerpt(section, terms),
                )
            )
        hits.sort(key=lambda h: (-h.score, h.section.rule_id))
        return hits[:limit] if limit else hits

    # ------------------------------------------------------------------
    def _excerpt(self, section: RuleSection, terms: list[str], width: int = 160) -> str:
        """원문에서 잘라낸 조각. **바꿔 쓰지 않는다** — 잘라내기만 한다."""
        text = section.normalized_text
        if not terms:
            return text[:width]
        lowered = text.lower()
        position = min(
            (lowered.find(t) for t in terms if lowered.find(t) >= 0), default=-1
        )
        if position < 0:
            return text[:width]
        start = max(0, position - width // 3)
        piece = text[start : start + width]
        return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")
