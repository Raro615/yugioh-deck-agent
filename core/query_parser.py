"""
한국어 자연어 질의 파서.

"4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드" 같은 문장을
:class:`~core.card_search.SearchFilters` 구조로 바꾼다.

한국어는 교착어라 조사가 붙어 어절 경계가 흔들리므로, 공백을 모두 제거한
압축 문자열 위에서 구체적인 표현부터 순서대로 매칭한다
(예: '장착마법' 을 '장착'/'마법' 보다 먼저 본다).

이 모듈이 다루는 것은 **게임 용어**뿐이다.
공식 카드명과 카드 텍스트는 번역하지 않으며, 이름 검색은 원문을 그대로 대조한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core import constants as C
from core.card_search import EffectLocationFilter, SearchFilters

# ---------------------------------------------------------------------------
# 어휘 테이블
# ---------------------------------------------------------------------------

# 효과 분류 (Lua CATEGORY_*). 실제 스크립트에 등장하는 분류만 싣는다.
EFFECT_CATEGORY_KO: dict[str, str] = {
    "특수소환": "SPECIAL_SUMMON",
    "특소": "SPECIAL_SUMMON",
    "소생": "SPECIAL_SUMMON",
    "일반소환": "SUMMON",
    "서치": "SEARCH",
    "검색": "SEARCH",
    "드로우": "DRAW",
    "파괴": "DESTROY",
    "제외": "REMOVE",
    "패로": "TOHAND",
    "회수": "TOHAND",
    "바운스": "TOHAND",
    "묘지로": "TOGRAVE",
    "덤핑": "TOGRAVE",
    "덤프": "TOGRAVE",
    "덱으로": "TODECK",
    "무효화": "NEGATE",
    "무효": "NEGATE",
    "효과무효": "DISABLE",
    "데미지": "DAMAGE",
    "번딜": "DAMAGE",
    "회복": "RECOVER",
    "라이프회복": "RECOVER",
    "핸드데스": "HANDES",
    "패털기": "HANDES",
    "덱파괴": "DECKDES",
    "컨트롤탈취": "CONTROL",
    "컨트롤변경": "CONTROL",
    "토큰생성": "TOKEN",
    "공격력변경": "ATKCHANGE",
    "공격력증가": "ATKCHANGE",
    "타점상승": "ATKCHANGE",
    "수비력변경": "DEFCHANGE",
    "표시형식변경": "POSITION",
    "레벨변경": "LVCHANGE",
    "카운터제거": "COUNTER",
    "동전던지기": "COIN",
    "묘지에서벗어": "LEAVE_GRAVE",
}

# 효과를 발동/적용하는 위치 (Lua LOCATION_*)
LOCATION_KO: dict[str, str] = {
    "패": "HAND",
    "손패": "HAND",
    "묘지": "GRAVE",
    "덱": "DECK",
    "필드": "MZONE",
    "몬스터존": "MZONE",
    "마법함정존": "SZONE",
    "제외존": "REMOVED",
    "제외된곳": "REMOVED",
    "엑스트라덱": "EXTRA",
    "엑덱": "EXTRA",
    "펜듈럼존": "PZONE",
    "필드존": "FZONE",
}

# 카드 종류. 구체적인 복합어를 먼저 확인한다.
CARD_TYPE_KO: list[tuple[str, int]] = [
    ("효과몬스터", C.TYPE_MONSTER | C.TYPE_EFFECT),
    ("일반몬스터", C.TYPE_MONSTER | C.TYPE_NORMAL),
    ("의식몬스터", C.TYPE_MONSTER | C.TYPE_RITUAL),
    ("융합몬스터", C.TYPE_MONSTER | C.TYPE_FUSION),
    ("싱크로몬스터", C.TYPE_MONSTER | C.TYPE_SYNCHRO),
    ("엑시즈몬스터", C.TYPE_MONSTER | C.TYPE_XYZ),
    ("링크몬스터", C.TYPE_MONSTER | C.TYPE_LINK),
    ("펜듈럼몬스터", C.TYPE_MONSTER | C.TYPE_PENDULUM),
    ("튜너몬스터", C.TYPE_MONSTER | C.TYPE_TUNER),
    ("리버스몬스터", C.TYPE_MONSTER | C.TYPE_FLIP),
    ("속공마법", C.TYPE_SPELL | C.TYPE_QUICKPLAY),
    ("지속마법", C.TYPE_SPELL | C.TYPE_CONTINUOUS),
    ("장착마법", C.TYPE_SPELL | C.TYPE_EQUIP),
    ("필드마법", C.TYPE_SPELL | C.TYPE_FIELD),
    ("의식마법", C.TYPE_SPELL | C.TYPE_RITUAL),
    ("일반마법", C.TYPE_SPELL | C.TYPE_NORMAL),
    ("카운터함정", C.TYPE_TRAP | C.TYPE_COUNTER),
    ("지속함정", C.TYPE_TRAP | C.TYPE_CONTINUOUS),
    ("일반함정", C.TYPE_TRAP | C.TYPE_NORMAL),
    ("마법카드", C.TYPE_SPELL),
    ("함정카드", C.TYPE_TRAP),
    ("융합", C.TYPE_MONSTER | C.TYPE_FUSION),
    ("싱크로", C.TYPE_MONSTER | C.TYPE_SYNCHRO),
    ("엑시즈", C.TYPE_MONSTER | C.TYPE_XYZ),
    ("펜듈럼", C.TYPE_MONSTER | C.TYPE_PENDULUM),
    ("튜너", C.TYPE_MONSTER | C.TYPE_TUNER),
    ("스피릿", C.TYPE_MONSTER | C.TYPE_SPIRIT),
    ("유니온", C.TYPE_MONSTER | C.TYPE_UNION),
    ("듀얼", C.TYPE_MONSTER | C.TYPE_GEMINI),
    ("툰", C.TYPE_MONSTER | C.TYPE_TOON),
    ("의식", C.TYPE_RITUAL),
    ("몬스터", C.TYPE_MONSTER),
    ("마법", C.TYPE_SPELL),
    ("함정", C.TYPE_TRAP),
]

# 서포트 질의를 나타내는 꼬리표: "마법사족에 좋은", "기계족 덱", "드래곤족용"
_SUPPORT_SUFFIX = r"(?:에좋은|에어울리는|서포트|덱용|덱에|덱|용)"

# 결과 해석에 쓰이지 않는 조사/군더더기
_STOPWORDS = {
    "카드", "중", "있는", "가능한", "가능", "하는", "되는", "그리고", "또는",
    "좋은", "추천", "찾아줘", "알려줘", "보여줘", "검색", "리스트", "목록",
    "인", "의", "를", "을", "이", "가", "은", "는", "와", "과", "랑", "에",
    "에서", "으로", "로", "들", "것", "거", "좀", "다", "해줘", "줘", "효과",
    "발동", "사용", "쓰는", "가진", "포함", "관련", "위한", "쓸", "수",
}


@dataclass(slots=True)
class ParsedQuery:
    """파싱 결과. 어떻게 해석했는지 사용자에게 돌려주기 위한 정보도 담는다."""

    filters: SearchFilters
    original: str
    matched_terms: list[str] = field(default_factory=list)
    unknown_terms: list[str] = field(default_factory=list)

    def explain_ko(self) -> str:
        text = f"해석: {self.filters.describe_ko()}"
        if self.unknown_terms:
            text += f"\n인식하지 못한 표현: {', '.join(self.unknown_terms)}"
        return text


class KoreanQueryParser:
    """한국어 질의를 :class:`SearchFilters` 로 바꾼다."""

    def __init__(self, default_limit: int | None = 20):
        self.default_limit = default_limit

    # ------------------------------------------------------------------
    def parse(self, text: str) -> ParsedQuery:
        filters = SearchFilters(limit=self.default_limit)
        matched: list[str] = []

        quoted_names = self._extract_quoted(text)
        compact = re.sub(r"\s+", "", text)
        # 인용된 이름은 압축 문자열에서 제거해 다른 규칙이 건드리지 않게 한다.
        for name in quoted_names:
            compact = compact.replace(re.sub(r"\s+", "", name), "")

        consumed: list[tuple[int, int]] = []

        def take(match: re.Match[str], label: str) -> None:
            consumed.append((match.start(), match.end()))
            matched.append(label)

        # 순서가 중요하다: 구체적인 표현 -> 일반적인 표현
        self._parse_numbers(compact, filters, consumed, take)
        self._parse_support_race(compact, filters, consumed, take)
        self._parse_races(compact, filters, consumed, take)
        self._parse_attributes(compact, filters, consumed, take)
        self._parse_card_types(compact, filters, consumed, take)
        self._parse_deck_zone(compact, filters, consumed, take)
        locations = self._parse_locations(compact, consumed, take)
        categories = self._parse_categories(compact, consumed, take)
        self._combine_effect_conditions(compact, filters, locations, categories)

        if quoted_names:
            filters.name = quoted_names[0]
            matched.append(f"이름 '{quoted_names[0]}'")

        # 조건이 하나도 없으면 문장 전체를 이름 검색으로 취급한다.
        leftovers = self._leftovers(compact, consumed)
        if filters.is_empty():
            fallback = text.strip()
            if fallback:
                filters.name = fallback
                matched.append(f"이름 '{fallback}'")
                leftovers = []

        return ParsedQuery(
            filters=filters,
            original=text,
            matched_terms=matched,
            unknown_terms=leftovers,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_quoted(text: str) -> list[str]:
        """따옴표/괄호로 묶인 카드명·카드군 이름을 꺼낸다."""
        names: list[str] = []
        for pattern in (r'"([^"]+)"', r"'([^']+)'", r"「([^」]+)」", r"《([^》]+)》"):
            names.extend(m.strip() for m in re.findall(pattern, text) if m.strip())
        return names

    # ------------------------------------------------------------------
    def _parse_numbers(self, compact, filters, consumed, take) -> None:
        # 공격력 / 수비력 (이상·이하)
        for stat, lo_attr, hi_attr in (
            ("공격력", "atk_min", "atk_max"),
            ("공", "atk_min", "atk_max"),
            ("수비력", "def_min", "def_max"),
        ):
            pattern = re.compile(rf"{stat}\s*(\d+)\s*(이상|이하|초과|미만)?")
            for m in pattern.finditer(compact):
                if self._overlaps(m, consumed):
                    continue
                value = int(m.group(1))
                bound = m.group(2)
                if bound in ("이하", "미만"):
                    setattr(filters, hi_attr, value - 1 if bound == "미만" else value)
                elif bound == "초과":
                    setattr(filters, lo_attr, value + 1)
                else:  # 이상 또는 단독 표기
                    setattr(filters, lo_attr, value)
                take(m, f"{stat}{value}{bound or ''}")

        # 랭크 / 링크 (카드 종류까지 결정된다)
        for word, type_bit in (("랭크", C.TYPE_XYZ), ("링크", C.TYPE_LINK)):
            pattern = re.compile(rf"(?:(\d+){word}|{word}\s*(\d+))")
            for m in pattern.finditer(compact):
                if self._overlaps(m, consumed):
                    continue
                value = int(m.group(1) or m.group(2))
                filters.levels.append(value)
                filters.required_types |= C.TYPE_MONSTER | type_bit
                take(m, f"{word}{value}")

        # 레벨 (범위 포함)
        pattern = re.compile(r"(?:(\d+)레벨|레벨\s*(\d+))\s*(이상|이하)?")
        for m in pattern.finditer(compact):
            if self._overlaps(m, consumed):
                continue
            value = int(m.group(1) or m.group(2))
            bound = m.group(3)
            if bound == "이상":
                filters.level_min = value
            elif bound == "이하":
                filters.level_max = value
            else:
                filters.levels.append(value)
            filters.required_types |= C.TYPE_MONSTER
            take(m, f"레벨{value}{bound or ''}")

    # ------------------------------------------------------------------
    def _parse_support_race(self, compact, filters, consumed, take) -> None:
        """'마법사족에 좋은', '기계족 덱' 처럼 서포트 대상을 가리키는 표현."""
        for term, bit in self._race_terms():
            pattern = re.compile(re.escape(term) + _SUPPORT_SUFFIX)
            for m in pattern.finditer(compact):
                if self._overlaps(m, consumed):
                    continue
                if bit not in filters.support_races:
                    filters.support_races.append(bit)
                take(m, m.group(0))

    def _parse_races(self, compact, filters, consumed, take) -> None:
        for term, bit in self._race_terms():
            for m in re.finditer(re.escape(term), compact):
                if self._overlaps(m, consumed):
                    continue
                if bit not in filters.races and bit not in filters.support_races:
                    filters.races.append(bit)
                    filters.required_types |= C.TYPE_MONSTER
                take(m, term)

    @staticmethod
    def _race_terms() -> list[tuple[str, int]]:
        """긴 표현이 먼저 오도록 정렬된 종족 용어 목록."""
        terms = dict(C.KO_RACE_ALIASES)
        for bit, ko in C.RACE_KO.items():
            terms.setdefault(f"{ko}족", bit)
        return sorted(terms.items(), key=lambda kv: -len(kv[0]))

    def _parse_attributes(self, compact, filters, consumed, take) -> None:
        terms = dict(C.KO_ATTRIBUTE_ALIASES)
        for bit, ko in C.ATTRIBUTE_KO.items():
            terms.setdefault(f"{ko}속성", bit)
        for term, bit in sorted(terms.items(), key=lambda kv: -len(kv[0])):
            for m in re.finditer(re.escape(term), compact):
                if self._overlaps(m, consumed):
                    continue
                if bit not in filters.attributes:
                    filters.attributes.append(bit)
                take(m, term)

    def _parse_card_types(self, compact, filters, consumed, take) -> None:
        for term, mask in CARD_TYPE_KO:
            for m in re.finditer(re.escape(term), compact):
                if self._overlaps(m, consumed):
                    continue
                filters.required_types |= mask
                take(m, term)

    def _parse_deck_zone(self, compact, filters, consumed, take) -> None:
        for m in re.finditer("메인덱", compact):
            if not self._overlaps(m, consumed):
                filters.main_deck_only = True
                take(m, "메인덱")

    # ------------------------------------------------------------------
    def _parse_locations(self, compact, consumed, take) -> list[str]:
        """효과 발동 위치 표현을 찾는다. '패에서', '묘지의' 처럼 조사가 붙는다."""
        found: list[str] = []
        ordered = sorted(LOCATION_KO.items(), key=lambda kv: -len(kv[0]))
        for term, location in ordered:
            pattern = re.compile(re.escape(term) + r"(?:에서|에|의|로부터)")
            for m in pattern.finditer(compact):
                if self._overlaps(m, consumed):
                    continue
                if location not in found:
                    found.append(location)
                take(m, m.group(0))
        return found

    def _parse_categories(self, compact, consumed, take) -> list[str]:
        found: list[str] = []
        ordered = sorted(EFFECT_CATEGORY_KO.items(), key=lambda kv: -len(kv[0]))
        for term, category in ordered:
            for m in re.finditer(re.escape(term), compact):
                if self._overlaps(m, consumed):
                    continue
                if category not in found:
                    found.append(category)
                take(m, term)
        return found

    @staticmethod
    def _combine_effect_conditions(compact, filters, locations, categories) -> None:
        """
        위치와 효과 분류를 결합한다.

        - 위치 + 분류가 함께 있으면 '그 위치에서 그 일을 하는 효과' 조건이 된다.
        - '패 + 특수 소환' 은 자체 특수 소환 절차까지 포함하도록 넓게 본다
          (EFFECT_SPSUMMON_PROC 은 CATEGORY 를 달지 않기 때문).
        - 위치만 있으면 '그 위치에서 발동하는 효과' 조건이 된다.
        """
        if "HAND" in locations and "SPECIAL_SUMMON" in categories:
            filters.special_summon_from_hand = True
            locations = [loc for loc in locations if loc != "HAND"]
            categories = [c for c in categories if c != "SPECIAL_SUMMON"]

        if locations and categories:
            for location in locations:
                for category in categories:
                    filters.effect_locations.append(
                        EffectLocationFilter(location=location, category=category)
                    )
            return

        for location in locations:
            filters.effect_locations.append(EffectLocationFilter(location=location))
        filters.effect_categories.extend(categories)

    # ------------------------------------------------------------------
    @staticmethod
    def _overlaps(match: re.Match[str], consumed: list[tuple[int, int]]) -> bool:
        return any(match.start() < end and start < match.end() for start, end in consumed)

    @staticmethod
    def _leftovers(compact: str, consumed: list[tuple[int, int]]) -> list[str]:
        """인식하지 못한 조각을 추려낸다 (사용자 피드백용)."""
        marks = [False] * len(compact)
        for start, end in consumed:
            for i in range(start, min(end, len(compact))):
                marks[i] = True
        runs: list[str] = []
        current: list[str] = []
        for ch, used in zip(compact, marks):
            if used:
                if current:
                    runs.append("".join(current))
                    current = []
            else:
                current.append(ch)
        if current:
            runs.append("".join(current))

        ordered_stopwords = sorted(_STOPWORDS, key=len, reverse=True)
        out: list[str] = []
        for run in runs:
            cleaned = run.strip()
            # 조사와 군더더기를 걷어내고 남는 것이 있는지 본다.
            # "효과가있는카드" 처럼 붙어 있는 조각도 여기서 걸러진다.
            residue = cleaned
            for word in ordered_stopwords:
                residue = residue.replace(word, "")
            residue = residue.strip()
            if len(residue) <= 1:
                continue
            out.append(cleaned)
        return out
