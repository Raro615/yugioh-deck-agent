"""
사용자가 말한 것을 **구조로 바꾸는 자리** (Phase 4-B).

    "오르페골 + K9으로 덱을 짜 줘. 초동 안정성을 우선하고 패트랩도 충분히"
            ↓  parse_deck_request
    DeckRequest(themes=['오르페골', 'K9'],
                goals=[OPENING_STABILITY, HAND_TRAP_WEIGHT], …)

🔴 **해석하지 못한 것을 채우지 않는다.** 테마를 못 찾았으면 빈 목록을
돌려주고, 목표를 못 찾았으면 목표 없이 돌려준다. 기본 목표를 몰래 끼워
넣으면 사용자가 지정하지 않은 기준으로 덱이 짜인다.

왜 ``core.query_parser`` 를 쓰지 않는가
---------------------------------------
:class:`~core.query_parser.KoreanQueryParser` 는 **카드를 찾는** 질의를
:class:`~core.card_search.SearchFilters` 로 바꾼다. 이쪽은 **덱을 짜는**
요청이고 산출물이 다르다. 같은 함수에 두 일을 시키면 "마법사족 카드 찾아
줘" 와 "마법사족 덱 짜 줘" 가 한 경로로 들어와 섞인다.

그래서 **파서는 둘로 두고, 테마 해석은 둘 다 같은 저장소 API**
(:meth:`~core.card_repository.CardRepository.resolve_archetype`) 에 맡긴다 —
카드군 판정 규칙이 두 벌로 갈리지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class DeckGoal(str, Enum):
    """사용자가 지정할 수 있는 구성 목표."""

    OPENING_STABILITY = "opening_stability"
    """초동 안정성 우선."""
    BOARD_DISRUPTION = "board_disruption"
    """최종 필드 견제력 우선."""
    HAND_TRAP_WEIGHT = "hand_trap_weight"
    """패에서 발동하는 카드 비중 우선."""

    def describe_ko(self) -> str:
        return {
            DeckGoal.OPENING_STABILITY: "초동 안정성 우선",
            DeckGoal.BOARD_DISRUPTION: "최종 필드 견제력 우선",
            DeckGoal.HAND_TRAP_WEIGHT: "패에서 발동하는 카드 비중 우선",
        }[self]


#: 목표를 가리키는 한국어 낱말. 공백을 지운 질의에 대고 찾는다.
_GOAL_WORDS: tuple[tuple[str, DeckGoal], ...] = (
    ("초동안정", DeckGoal.OPENING_STABILITY),
    ("초동", DeckGoal.OPENING_STABILITY),
    ("안정성", DeckGoal.OPENING_STABILITY),
    ("견제", DeckGoal.BOARD_DISRUPTION),
    ("제압", DeckGoal.BOARD_DISRUPTION),
    ("최종필드", DeckGoal.BOARD_DISRUPTION),
    ("패트랩", DeckGoal.HAND_TRAP_WEIGHT),
    ("핸드트랩", DeckGoal.HAND_TRAP_WEIGHT),
)

#: 덱 요청임을 알리는 낱말 — 테마 후보에서 걷어낸다.
_REQUEST_NOISE = (
    "으로", "로", "덱을", "덱", "짜줘", "짜", "줘", "구성해줘", "구성",
    "만들어줘", "만들어", "해줘", "부탁", "우선하고", "우선", "충분히",
    "넣어줘", "넣어", "그리고", "또", "좀", "제외하고", "제외",
)

#: 🔴 제외 지시는 **구절 단위**로 읽는다. 공백 없는 한 낱말만 잡으면
#: "오르페골 클리막스 제외" 에서 '클리막스' 만 잡혀 카드명이 깨진다
#: (Phase 4-B 작업 중 테스트가 실제로 이 버그를 잡았다).
_EXCLUDE_TAIL = re.compile(r"\s*(?:은|는|을|를)?\s*제외(?:하고|해줘|해 줘|할래)?\s*$")


@dataclass(slots=True)
class DeckRequest:
    """
    구조화된 덱 요청.

    :attr:`raw` 를 남기는 이유: 파서가 놓친 것이 있을 때 사람이 원문을
    다시 읽을 수 있어야 한다. 해석 결과만 남기면 무엇을 버렸는지 알 수
    없다.
    """

    raw: str = ""
    themes: list[str] = field(default_factory=list)
    goals: list[DeckGoal] = field(default_factory=list)
    excluded_names: list[str] = field(default_factory=list)
    language: str = "ko"

    @property
    def is_empty(self) -> bool:
        return not self.themes and not self.goals

    def describe_ko(self) -> str:
        bits: list[str] = []
        bits.append("테마: " + (" + ".join(self.themes) if self.themes
                                else "해석하지 못했습니다"))
        if self.goals:
            bits.append("목표: " + " · ".join(g.describe_ko()
                                             for g in self.goals))
        else:
            bits.append("목표: 지정되지 않았습니다")
        if self.excluded_names:
            bits.append("제외: " + ", ".join(self.excluded_names))
        return "\n".join(bits)


def _strip_noise(token: str) -> str:
    """테마 후보에서 요청 낱말을 걷어낸다. 어미가 붙어 있어도 떼어낸다."""
    cleaned = token.strip().strip(",.!?·")
    for noise in _REQUEST_NOISE:
        if cleaned == noise:
            return ""
        if len(cleaned) > len(noise) and cleaned.endswith(noise):
            cleaned = cleaned[: -len(noise)]
    return cleaned.strip()


def parse_deck_request(text: str, language: str = "ko") -> DeckRequest:
    """
    한국어 덱 요청을 :class:`DeckRequest` 로 바꾼다.

    🔴 **테마가 실제 카드군인지 여기서 판정하지 않는다.** 이 함수는 낱말만
    고르고, 카드군 해석은 :class:`~deck.builder.DeckBuilder` 가 저장소에
    물어본다. 파서가 카드 데이터를 읽으면 "해석" 과 "조회" 가 한 자리에
    섞인다.
    """
    request = DeckRequest(raw=text, language=language)
    if not text or not text.strip():
        return request

    compact = text.replace(" ", "")
    for word, goal in _GOAL_WORDS:
        if word in compact and goal not in request.goals:
            request.goals.append(goal)

    #: 쉼표·문장부호로 끊고, '…제외' 로 끝나는 조각을 **구절째로** 떼어낸다.
    #: 떼어낸 조각은 테마 후보에서도 빠진다 — 빼지 않으면 제외하려던 카드의
    #: 낱말 일부가 테마로 들어온다.
    segments = [s for s in re.split(r"[,、.!?\n]|。", text) if s.strip()]
    kept: list[str] = []
    for segment in segments:
        if _EXCLUDE_TAIL.search(segment):
            name = _strip_noise(_EXCLUDE_TAIL.sub("", segment))
            if name and name not in request.excluded_names:
                request.excluded_names.append(name)
            continue
        kept.append(segment)

    #: 테마 후보: 첫 조각만 본다. 뒤 문장은 목표·부탁 말이 대부분이다.
    goal_words = {word for word, _ in _GOAL_WORDS}
    head = kept[0] if kept else ""
    for chunk in re.split(r"[+·/]|그리고|와|과", head):
        for token in chunk.split():
            candidate = _strip_noise(token)
            if not candidate or len(candidate) < 2:
                continue
            if candidate.replace(" ", "") in goal_words:
                continue
            #: 🔴 **정확히 같은 것만** 걷어낸다. 부분 문자열로 걸렀더니
            #: "오르페골 클리막스 제외" 가 테마 '오르페골' 까지 지웠다
            #: (작업 중 실제로 그렇게 깨졌다). 제외 구절은 위에서 이미
            #: 테마 후보에서 빠졌으므로 여기서 더 넓게 볼 이유가 없다.
            if candidate in request.excluded_names:
                continue
            if candidate not in request.themes:
                request.themes.append(candidate)
    return request
