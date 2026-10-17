"""
**사용자가 적은 실제 덱 레시피**를 읽는 자리 (Phase 6-T).

왜 이 모듈이 필요했는가
-----------------------
``/combo`` 의 ``deck:`` 는 **자연어 요청**이다 —
:func:`~deck.request.parse_deck_request` 가 테마와 목표를 읽고
:class:`~deck.builder.DeckBuilder` 가 **초안**을 만든다. 초안은 이 저장소가
추천한 구성이고 사용자가 확정한 덱이 아니다. 그것을 실제 덱으로 쓰면
"사용자의 덱으로 전개를 검증했다" 가 거짓이 된다 (Phase 6-T §5).

그래서 **확정된 레시피를 받는 길**을 따로 둔다. 이 모듈이 하는 일은 그
문자열을 :class:`~deck.model.DeckDraft` 로 바꾸는 것뿐이다.

🔴 **새 모델을 만들지 않는다.** ``DeckDraft`` 는 이미
``(card_id, copies)`` 와 메인 · 엑스트라 구분을 들고 있으므로 레시피를
담을 수 있다. 새 타입을 만들면 검증기
(:class:`~deck.validator.DeckValidator`) 와 보고서
(:mod:`deck.report`) 를 둘 다 고쳐야 한다.

🔴 **역할을 추측하지 않는다.** 초안의 :class:`~deck.model.CardRole` 은
"이 저장소가 왜 이 카드를 골랐는가" 를 적는 칸이다. 레시피는 사용자가 고른
것이므로 고를 이유가 **없다** — 엑스트라 덱 여부만 카드 종류로 판정하고
(:attr:`~deck.model.RoleEvidence.PRINTED_CARD_TYPE`) 나머지는
:attr:`~deck.model.CardRole.UNCLASSIFIED` · 근거 없음이다.

받는 두 모양
------------
**① YDK** — ``#main`` / ``#extra`` / ``!side`` 구역과 한 줄에 패스코드
하나. 같은 패스코드가 여러 줄이면 그 수가 매수다. EDOPro · YGOPRODeck 이
내보내는 모양 그대로다::

    #main
    55144522
    55144522
    11091375
    #extra
    #!side

**② 목록** — 쉼표나 줄바꿈으로 나눈 ``<이름 또는 ID>`` 와 선택적
``x<매수>``. 구역을 바꾸려면 ``엑스트라:`` 또는 ``extra:`` 를 적는다::

    욕망의 항아리 x3, 11091375 x12, 엑스트라: 11091375 x1

🔴 **모양을 추측하지 않는다.** ``#main`` · ``#extra`` 가 보이면 ①이고,
아니면 ②다. 둘을 섞은 입력은 ②로 읽고 ``#`` 줄을 해석하지 못한 토큰으로
남긴다 — 조용히 버리지 않는다.

🔴 **해석하지 못한 토큰을 버리지 않는다.** 이름을 못 찾았으면
:attr:`RecipeParse.unresolved` 에 그대로 담는다. 해석된 것만으로 덱을
만들면 사용자는 자기가 적은 카드가 들어간 덱으로 검증했다고 믿는다
(``/combo`` 의 패 해석과 같은 규율).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from deck.model import CardRole, DeckDraft, DeckSlot, RoleEvidence

#: 레시피 한 칸의 매수 표기. ``x3`` · ``X3`` · ``*3`` · ``3장`` 을 받는다.
_COPIES = re.compile(r"(?:[xX*]\s*(\d+)|(\d+)\s*장)\s*$")

#: YDK 구역 표시. 내보내는 도구마다 사이드 표시가 ``!side`` · ``#!side``
#: · ``#side`` 로 갈리므로 **세 모양 전부** 받는다 (실측에서 ``#!side``
#: 가 구역으로 읽히지 않아 그 아래 줄이 엑스트라로 세어졌다).
_YDK_MARKERS = ("#main", "#extra", "!side", "#side")
_SIDE_MARKERS = ("!side", "#!side", "#side")

#: 목록 모양에서 엑스트라 구역으로 넘어가는 표시.
_EXTRA_MARKERS = ("엑스트라:", "엑스트라덱:", "extra:", "extra deck:")

#: 목록 모양에서 메인 구역으로 돌아오는 표시.
_MAIN_MARKERS = ("메인:", "메인덱:", "main:", "main deck:")

#: 레시피를 적지 않았다는 뜻. 빈 문자열과 가르기 위해 상수로 둔다.
EMPTY_RECIPE = "레시피를 적지 않았습니다"


@dataclass(slots=True)
class RecipeParse:
    """
    레시피 하나를 읽은 결과.

    🔴 **빈 초안과 "적지 않았다" 를 가른다.** :attr:`draft` 가 ``None`` 이면
    읽을 것이 없었다는 뜻이고, 빈 ``DeckDraft`` 가 아니다 — 빈 덱으로
    전개를 검증하면 덱 장수를 조건으로 보는 효과가 거짓으로 통과한다
    (Phase 6-S §16-B 가 실측으로 경고한 자리).
    """

    draft: DeckDraft | None = None
    unresolved: list[str] = field(default_factory=list)
    """🔴 카드로 해석하지 못한 토큰. 조용히 버리지 않는다."""
    notes: list[str] = field(default_factory=list)
    """읽는 과정에서 알아 둘 것 — 모양 판정, 무시한 구역 등."""

    @property
    def is_empty(self) -> bool:
        return self.draft is None

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        if self.draft is None:
            return EMPTY_RECIPE
        return (f"메인 {self.draft.main_count}장 · "
                f"엑스트라 {self.draft.extra_count}장"
                + (f" · 해석 못한 토큰 {len(self.unresolved)}개"
                   if self.unresolved else ""))


def looks_like_ydk(text: str) -> bool:
    """
    이 문자열이 **YDK 모양인가.** 구역 표시가 있으면 그렇다.

    🔴 패스코드만 나열한 문자열은 YDK 가 아니라 ②로 읽는다 — 구역 표시가
    없으면 메인인지 엑스트라인지 알 수 없고, 추측하면 엑스트라 덱 카드가
    메인으로 들어간다.
    """
    lowered = text.lower()
    return any(marker in lowered for marker in (*_YDK_MARKERS, *_SIDE_MARKERS))


def _split_copies(token: str) -> "tuple[str, int]":
    """``"욕망의 항아리 x3"`` → ``("욕망의 항아리", 3)``. 없으면 1장."""
    match = _COPIES.search(token)
    if not match:
        return token.strip(), 1
    count = int(match.group(1) or match.group(2))
    return token[: match.start()].strip(), count


def _resolve(token: str, repository) -> "tuple[int, object] | None":
    """토큰 하나를 카드로. 숫자는 ID, 그 밖은 **정확한 이름**이다."""
    if token.isdigit():
        card = repository.get(int(token))
        return (int(token), card) if card else None
    found = repository.find_by_exact_name(token)
    return (found[0].id, found[0]) if found else None


def _add(counts: "dict[int, int]", card_id: int, copies: int) -> None:
    counts[card_id] = counts.get(card_id, 0) + copies


def _parse_ydk(text: str, repository) -> RecipeParse:
    """
    ① YDK — 구역 표시와 한 줄에 패스코드 하나.

    ``!side`` · ``#side`` 는 **읽고 버린다** (사이드 덱은 선공 전개에
    들어오지 않는다). 버린 사실을 :attr:`RecipeParse.notes` 에 적는다.
    """
    result = RecipeParse(notes=["레시피 모양: YDK (#main · #extra 구역)"])
    main: dict[int, int] = {}
    extra: dict[int, int] = {}
    side = 0
    section = "main"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("#created"):
            continue
        if lowered.startswith("#main"):
            section = "main"
            continue
        if lowered.startswith("#extra"):
            section = "extra"
            continue
        if lowered.startswith(_SIDE_MARKERS):
            section = "side"
            continue
        if line.startswith("#"):
            result.unresolved.append(line)
            continue
        if section == "side":
            #: 🔴 **사이드 줄은 카드로 찾아보지도 않는다.** 선공 전개에
            #: 들어오지 않으므로 해석할 이유가 없고, 해석하면 사이드의
            #: 오타가 "카드를 못 찾았다" 로 올라와 메인 레시피의 문제처럼
            #: 보인다.
            side += 1
            continue
        resolved = _resolve(line, repository)
        if resolved is None:
            result.unresolved.append(line)
            continue
        card_id, card = resolved
        #: 🔴 구역 표시보다 **카드 데이터**를 믿는다. YDK 의 ``#main`` 아래에
        #: 엑스트라 덱 카드가 적혀 있으면 그것은 입력의 오류이고, 그 오류를
        #: 그대로 옮기면 검증기가 "메인에 엑스트라가 섞였다" 를 잡는다.
        #: 그래서 **옮기지 않고 적어 둔다** — 검증기가 보게 둔다.
        _add(extra if section == "extra" else main, card_id, 1)
    if side:
        result.notes.append(f"사이드 덱 {side}장은 읽고 버렸습니다"
                            " (선공 전개에 들어오지 않습니다)")
    if not main and not extra:
        return RecipeParse(unresolved=result.unresolved,
                           notes=[*result.notes, "YDK 구역에서 카드를"
                                  " 하나도 읽지 못했습니다"])
    result.draft = _build_draft(main, extra, repository)
    return result


def _parse_list(text: str, repository) -> RecipeParse:
    """② 목록 — 쉼표·줄바꿈으로 나눈 ``이름 또는 ID [x매수]``."""
    result = RecipeParse(notes=["레시피 모양: 목록 (이름 또는 ID · x매수)"])
    main: dict[int, int] = {}
    extra: dict[int, int] = {}
    section = "main"
    tokens = [t for line in text.splitlines() for t in line.split(",")]
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        lowered = token.lower()
        marker_hit = False
        for marker in _EXTRA_MARKERS:
            if lowered.startswith(marker):
                section, token, marker_hit = "extra", token[len(marker):].strip(), True
                break
        if not marker_hit:
            for marker in _MAIN_MARKERS:
                if lowered.startswith(marker):
                    section, token, marker_hit = "main", token[len(marker):].strip(), True
                    break
        if not token:
            continue
        name, copies = _split_copies(token)
        if not name:
            result.unresolved.append(raw.strip())
            continue
        resolved = _resolve(name, repository)
        if resolved is None:
            result.unresolved.append(name)
            continue
        card_id, _card = resolved
        _add(extra if section == "extra" else main, card_id, copies)
    if not main and not extra:
        return RecipeParse(unresolved=result.unresolved,
                           notes=[*result.notes,
                                  "목록에서 카드를 하나도 읽지 못했습니다"])
    result.draft = _build_draft(main, extra, repository)
    return result


def _build_draft(main: "dict[int, int]", extra: "dict[int, int]",
                 repository) -> DeckDraft:
    """
    센 매수를 :class:`~deck.model.DeckDraft` 로.

    🔴 **역할을 추측하지 않는다.** 엑스트라 덱 여부만 카드 종류로 판정하고
    (근거: ``PRINTED_CARD_TYPE``), 나머지는 ``UNCLASSIFIED`` · 근거 없음이다
    — 사용자가 고른 것이므로 이 저장소가 고를 이유를 적을 수 없다.
    """
    draft = DeckDraft(notes=["사용자가 적은 레시피입니다 (이 저장소가"
                             " 추천한 초안이 아닙니다)"])
    #: 🔴 **사용자가 적은 구역을 옮기지 않는다.** 엑스트라 구역에 메인 덱
    #: 카드가 적혀 있으면 그것은 입력의 오류이고, 조용히 메인으로 옮기면
    #: 사용자는 자기가 적은 것과 다른 덱으로 검증한 결과를 본다. 그대로
    #: 두고 **적어 둔다** — 장수 검사는 검증기가 그 상태로 본다.
    stray = [
        card_id for card_id in extra
        if not (repository.get(card_id) and repository.get(card_id).is_extra_deck)
    ]
    if stray:
        names = ", ".join(
            (repository.get(c).display_name() if repository.get(c) else f"[{c}]")
            for c in sorted(stray)
        )
        draft.notes.append(
            f"⚠️ 엑스트라 구역에 메인 덱 카드가 적혀 있습니다: {names}"
            " — 적은 자리를 그대로 두었습니다 (옮기지 않았습니다)"
        )
    for bucket, slots in ((main, draft.main), (extra, draft.extra)):
        for card_id, copies in sorted(bucket.items()):
            card = repository.get(card_id)
            is_extra = bool(card and card.is_extra_deck)
            slots.append(DeckSlot(
                card_id=card_id,
                name=card.display_name() if card else f"[{card_id}]",
                copies=copies,
                role=CardRole.EXTRA_DECK if is_extra else CardRole.UNCLASSIFIED,
                reason="사용자가 레시피에 적었습니다",
                evidence=(RoleEvidence.PRINTED_CARD_TYPE if is_extra
                          else RoleEvidence.NONE),
            ))
    return draft


def parse_recipe(text: str, repository) -> RecipeParse:
    """
    레시피 문자열 하나를 읽는다. **모양은 입력이 정한다.**

    빈 문자열이면 :attr:`RecipeParse.draft` 가 ``None`` 이다 — "빈 덱" 이
    아니라 "적지 않았다" 다.
    """
    if not text or not text.strip():
        return RecipeParse(notes=[EMPTY_RECIPE])
    if looks_like_ydk(text):
        return _parse_ydk(text, repository)
    return _parse_list(text, repository)


__all__ = [
    "EMPTY_RECIPE",
    "RecipeParse",
    "looks_like_ydk",
    "parse_recipe",
]
