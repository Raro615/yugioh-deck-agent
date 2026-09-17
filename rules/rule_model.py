"""
규칙 문서 모델.

**원문과 가공물을 분리한다.**

- :class:`RuleSection.text` 는 룰북에 인쇄된 문장 그대로다. 요약도, 의역도,
  보충도 들어가지 않는다. 룰북에 없는 문장은 여기 없다.
- 구조화된 해석은 :mod:`rules.structured` 가 따로 담고, 각 항목은 자기가 어느
  원문에서 나왔는지 :class:`RuleRef` 로 가리킨다.

이 분리를 지키는 이유는 하나다. 엔진이 규칙을 구현하다 막혔을 때 **되돌아가
읽을 원문**이 있어야 하기 때문이다. 요약만 남아 있으면 그 요약이 맞는지
확인할 방법이 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

# 룰북 본문이 쓰는 합자. 검색할 때만 낱글자로 편다 (원문은 그대로 보존).
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}


def expand_ligatures(text: str) -> str:
    """``ﬁeld`` -> ``field``. 원문을 바꾸지 않고 사본을 돌려준다."""
    for ligature, letters in _LIGATURES.items():
        if ligature in text:
            text = text.replace(ligature, letters)
    return text


# 권위 순서. 숫자가 작을수록 강하다. 보조 출처는 공식 룰을 덮어쓸 수 없다.
RULE_AUTHORITY: dict[str, int] = {
    "official_rulebook": 0,
    "lua_script": 1,
    "official_card_text": 2,
    "korean_db": 3,
    "supplementary": 4,
}


class RuleCategory(str, Enum):
    """
    Rule ID 의 분류. 룰북의 장 구성을 엔진이 쓰기 좋은 주제로 다시 묶은 것이며,
    **룰북에 없는 주제를 만들지 않는다.**
    """

    GAME = "GAME"
    """게임 목적 · 승패 · 듀얼 준비"""
    DECK = "DECK"
    """덱 구성과 매수 제한"""
    ZONE = "ZONE"
    """필드와 존"""
    CARD = "CARD"
    """카드 읽는 법"""
    MONSTER = "MONSTER"
    """몬스터 카드 종류"""
    EFFECT = "EFFECT"
    """효과 분류 (지속 · 기동 · 유발즉시 · 유발 · 리버스)"""
    SUMMON = "SUMMON"
    """소환법"""
    SPELLTRAP = "SPELLTRAP"
    """마법 · 함정 카드"""
    TURN = "TURN"
    """턴과 페이즈"""
    BATTLE = "BATTLE"
    """전투와 데미지"""
    CHAIN = "CHAIN"
    """체인 · 스펠 스피드 · 우선권"""
    MISC = "MISC"
    """그 밖의 규칙"""
    TERM = "TERM"
    """용어집"""


@dataclass(frozen=True, slots=True, order=True)
class RuleRef:
    """
    규칙 하나를 가리키는 불변 참조. ``RuleRef("RULE-CHAIN-001")``.

    Duel Engine 이 "이 코드는 어느 규칙을 구현한 것인가"를 적어두는 자리다.
    문자열을 그냥 쓰지 않고 타입을 두는 이유는, 형식이 틀린 ID 가 조용히
    섞여 들어가는 것을 막기 위해서다.
    """

    rule_id: str

    def __post_init__(self) -> None:
        parts = self.rule_id.split("-")
        if len(parts) != 3 or parts[0] != "RULE":
            raise ValueError(
                f"Rule ID 형식이 아닙니다: {self.rule_id!r} (RULE-<분류>-<번호>)"
            )
        if parts[1] not in RuleCategory.__members__:
            raise ValueError(f"모르는 분류입니다: {parts[1]!r}")
        if not (parts[2].isdigit() and len(parts[2]) == 3):
            raise ValueError(f"번호는 세 자리 숫자여야 합니다: {parts[2]!r}")

    @property
    def category(self) -> RuleCategory:
        return RuleCategory(self.rule_id.split("-")[1])

    @property
    def number(self) -> int:
        return int(self.rule_id.split("-")[2])

    def __str__(self) -> str:
        return self.rule_id


@dataclass(frozen=True, slots=True)
class SourceReference:
    """이 섹션이 룰북 어디에서 왔는지."""

    document: str
    printed_pages: tuple[int, ...] = ()
    """룰북에 인쇄된 쪽번호."""
    pdf_pages: tuple[int, ...] = ()
    """PDF 상의 쪽번호. 펼침면이라 인쇄 쪽번호와 다르다."""

    def describe(self) -> str:
        pages = ", ".join(str(p) for p in self.printed_pages)
        return f"{self.document} p.{pages}" if pages else self.document


@dataclass(frozen=True, slots=True)
class RuleProvenance:
    """
    규칙 문서의 출처. **카드 provenance 와 별개다** —
    :mod:`core.provenance` 는 "이 카드의 이 필드가 어디서 왔나"를 다루고,
    여기는 "이 규칙 문서가 어느 판본의 무엇인가"를 다룬다. 갱신 주기도,
    권위 판정 방식도 다르므로 섞지 않는다.
    """

    source: str
    """발행처와 출판물. 예: Konami Digital Entertainment, Inc. — Starter Deck Rulebook"""
    version: str
    """룰북 판본. 예: "10"."""
    retrieved_at: str
    """추출 시각 (UTC, ISO 8601)."""
    document_hash: str
    """원본 PDF 의 ``sha256:...``. 같은 파일인지 확인하는 유일한 근거다."""
    language: str = "en"
    source_file: str | None = None
    extractor: str | None = None

    @property
    def authority(self) -> int:
        return RULE_AUTHORITY["official_rulebook"]


@dataclass(slots=True)
class RuleSection:
    """룰북의 한 절. ``text`` 는 원문 그대로다."""

    rule_id: str
    title: str
    category: RuleCategory
    chapter: int
    chapter_title: str
    level: int
    text: str
    source_reference: SourceReference
    anchor: str = ""
    """룰북에 인쇄된 제목 줄. 추출이 어디서 시작했는지 보여준다."""
    title_source: str = "heading"
    """``heading``: 룰북의 제목 그대로. ``editorial``: 점선/장식을 덜어낸 표시용 제목."""
    parent: str | None = None
    subsections: list[str] = field(default_factory=list)

    @property
    def ref(self) -> RuleRef:
        return RuleRef(self.rule_id)

    @property
    def normalized_text(self) -> str:
        """
        검색용 표현. **원문 ``text`` 는 그대로 둔다.**

        두 가지만 바꾼다.

        - 인쇄된 줄바꿈을 공백으로 편다. 그래야 줄에 걸친 구절도 찾을 수 있다.
        - 합자(ligature)를 낱글자로 되돌린다. 룰북 본문은 ``ﬁeld`` / ``shufﬂe``
          처럼 U+FB01 · U+FB02 를 쓰는데, 그대로 두면 "field" 나 "shuffle" 로는
          영영 검색되지 않는다. 글자를 바꾸는 것이 아니라 **같은 글자의 다른
          표기를 펴는 것**이다.
        """
        return " ".join(expand_ligatures(self.text).split())

    def __str__(self) -> str:
        return f"{self.rule_id} {self.title}"


@dataclass(slots=True)
class RuleDocument:
    """룰북 한 권."""

    doc_id: str
    title: str
    provenance: RuleProvenance
    sections: list[RuleSection] = field(default_factory=list)

    def __iter__(self) -> Iterator[RuleSection]:
        return iter(self.sections)

    def __len__(self) -> int:
        return len(self.sections)

    def top_level(self) -> list[RuleSection]:
        return [s for s in self.sections if s.parent is None]

    def __str__(self) -> str:
        return f"{self.title} v{self.provenance.version} ({len(self.sections)} sections)"
