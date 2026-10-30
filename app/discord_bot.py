"""
갈라테아 — Discord 어댑터 (Phase 5-A).

    Discord 슬래시 명령
          ↓
    CommandTree 핸들러            ← 이 파일. discord 를 아는 유일한 자리
          ↓
    순수 응답 생성 함수            ← discord 를 모른다. 테스트가 여기를 본다
          ↓
    (앞으로) core · deck 계층      ← 아직 연결하지 않았다

🔴 **구현한 명령은 ``/ping`` 과 ``/search`` 둘이다** (Phase 5-A · 5-B).
덱 구축(`deck/`)과 전개 계획은 **연결하지 않았다** — 연결했다고 적지도
않는다. 붙이는 자리는 §확장 지점에 적어 두었다.

검색은 어떻게 재사용하는가
--------------------------
검색 로직을 다시 쓰지 않는다. :class:`~app.main.DeckAgent` 를 그대로
만들어 :meth:`~app.main.DeckAgent.search_korean` 을 부르고, 해석 설명은
``ParsedQuery.explain_ko()`` 를, 한 줄 표시는
:func:`~app.main.format_card_line` 을 쓴다 — CLI 와 **같은 문자열**이
나온다.

🔴 **무거운 초기화는 한 번만 한다.** ``CardRepository.build()`` 는 이
환경에서 **약 3초**(카드 14,127장)가 걸리고, 그것은 Discord 가 첫 응답에
주는 시간과 거의 같다. 명령마다 다시 만들면 매번 그 시간을 치른다.
그래서 :class:`SearchService` 가 ``on_ready`` 에서 **한 번** 만들어
들고 있고, 실패하면 그 사실을 기록해 사용자에게 "지금은 검색할 수
없습니다" 라고 알린다 — 조용히 빈 결과를 돌려주지 않는다.

왜 ``discord`` 를 모듈 맨 위에서 import 하지 않는가
---------------------------------------------------
이 저장소는 런타임에 **사실상 표준 라이브러리만** 쓴다 (서드파티 import 가
``pymupdf`` 한 곳뿐이고 그것도 선택적이다). 봇 때문에 그 성질을 잃으면,
``discord.py`` 가 없는 환경에서 **이 파일을 읽는 것조차** 실패한다.

그래서 ``discord`` 는 :func:`build_client` 와 :func:`main` **안에서만**
import 한다. 그 결과:

* 토큰 처리와 응답 문구는 **라이브러리 없이 테스트된다.**
* 기존 CLI(``app/main.py``)는 봇의 존재를 모른다 — 건드리지 않았다.

🔴 **파일 이름이 ``discord_bot.py`` 인 이유**: ``discord.py`` 로 두면
``import discord`` 가 라이브러리 대신 이 파일을 집는다.

토큰
----
``DISCORD_BOT_TOKEN`` 환경변수에서만 읽는다. 소스에 넣지 않고, **로그와
오류 메시지에 값을 쓰지 않는다** — 길이조차 적지 않는다. 길이는 토큰의
종류를 알려 주는 정보다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from enum import Enum

#: 🔴 **검색 파이프라인을 다시 쓰지 않는다.** CLI 와 같은 함수를 부른다.
#: ``app.main`` 은 ``discord`` 를 쓰지 않으므로 여기서 최상위 import 해도
#: "라이브러리 없이 이 모듈을 읽을 수 있다" 는 성질이 유지된다.
from app.main import format_card_line

#: 봇 표시 이름. 응답 문구와 로그가 같은 이름을 쓴다.
BOT_NAME = "갈라테아"

#: ``/ping`` 의 명령 설명. 조사가 붙으므로 f-string 으로 끼우지 않는다 —
#: ``f"{BOT_NAME} 가 …"`` 로 쓰면 "갈라테아 가" 처럼 띄어 쓰게 된다.
PING_DESCRIPTION = "갈라테아가 살아 있는지 확인합니다"
SEARCH_DESCRIPTION = "한국어로 카드를 검색합니다"
DECK_DESCRIPTION = "한국어 요청으로 덱 초안을 만들고 규격을 검증합니다"
COMBO_DESCRIPTION = ("지정한 초기 패로 전개를 봅니다 —"
                     " recipe 를 주면 실제 엔진으로 실행합니다")

#: 환경변수 이름 — 테스트와 문서가 같은 상수를 본다.
TOKEN_ENV = "DISCORD_BOT_TOKEN"
GUILD_ENV = "DISCORD_DEV_GUILD_ID"

LOGGER_NAME = "galatea"
logger = logging.getLogger(LOGGER_NAME)

#: Discord 한 메시지의 문자 상한. 넘기면 전송이 거부된다.
DISCORD_MESSAGE_LIMIT = 2000

#: ``/search`` 가 보여 주는 최대 건수. 실측으로 20건도 상한 안에 들어가지만
#: (최악 1,469자) 읽기 좋은 길이로 10건을 쓴다. 상한 보장은 길이로 한 번 더
#: 한다 (:func:`clamp_to_discord_limit`) — 건수로만 믿지 않는다.
SEARCH_RESULT_LIMIT = 10

#: 리포지토리가 준비되지 않았을 때의 안내. 🔴 빈 결과로 위장하지 않는다.
UNAVAILABLE_MESSAGE = (
    "지금은 카드 검색을 할 수 없습니다. 카드 데이터 초기화가 실패했습니다 "
    "— 봇 로그를 확인해 주세요."
)

#: 길이 때문에 잘렸을 때 덧붙이는 말. 잘린 사실을 숨기지 않는다.
TRUNCATION_NOTICE = "\n… (길이 제한으로 줄였습니다)"

#: 리포지토리가 준비되지 않았을 때 ``/deck`` 의 안내. ``/search`` 와 문구를
#: 공유하지 않는 이유: 사용자가 무엇을 못 하는지 알아야 한다.
DECK_UNAVAILABLE_MESSAGE = (
    "지금은 덱을 만들 수 없습니다. 카드 데이터 초기화가 실패했습니다 "
    "— 봇 로그를 확인해 주세요."
)

#: 덱 빌더가 예외를 던졌을 때의 안내. 🔴 **예외 내용을 사용자에게 보내지
#: 않는다** — 경로나 내부 구조가 드러난다. 그것은 로그로만 간다.
DECK_ERROR_MESSAGE = (
    "덱을 만드는 중 오류가 발생했습니다. 요청을 다르게 적어 보시고, "
    "계속 실패하면 봇 로그를 확인해 주세요."
)

#: 리포지토리가 준비되지 않았을 때 ``/combo`` 의 안내.
COMBO_UNAVAILABLE_MESSAGE = (
    "지금은 전개 계획을 세울 수 없습니다. 카드 데이터 초기화가 실패했습니다 "
    "— 봇 로그를 확인해 주세요."
)

#: 콤보 플래너가 예외를 던졌을 때의 안내. 🔴 예외 내용을 담지 않는다.
COMBO_ERROR_MESSAGE = (
    "전개 계획을 세우는 중 오류가 발생했습니다. 입력을 다르게 적어 보시고, "
    "계속 실패하면 봇 로그를 확인해 주세요."
)

#: 🔴 한 명령의 응답을 나눠 보낼 때의 최대 메시지 수. 덱 출력은 실측
#: 3,109~3,617자로 상한의 1.6~1.8배라 한 메시지에 들어가지 않는다. 잘라서
#: 덱의 뒷부분을 버리지 않고 **나눠 보낸다** — 덱은 일부만 보여 주면 되는
#: 목록이 아니다. 상한을 두는 이유는 사고로 수십 개를 쏟지 않기 위해서다.
DECK_MESSAGE_LIMIT = 4


class MissingTokenError(RuntimeError):
    """``DISCORD_BOT_TOKEN`` 이 없다. **값을 담지 않는다.**"""


class InvalidGuildError(RuntimeError):
    """개발용 서버 ID 가 정수가 아니다."""


# ===========================================================================
# 순수 응답 생성 — discord 를 모른다
# ===========================================================================
def ping_message() -> str:
    """
    ``/ping`` 의 응답.

    🔴 **문구를 핸들러 안에 쓰지 않는다.** 핸들러는 discord 의
    ``Interaction`` 을 받으므로 라이브러리 없이 부를 수 없고, 그러면 문구가
    테스트되지 않는다. 앞으로 ``/deck`` 도 같은 모양을 쓴다 — 핸들러는
    받아서 넘기고, 문구를 만드는 것은 이런 순수 함수다.
    """
    return f"Pong! {BOT_NAME} 온라인."


def clamp_to_discord_limit(text: str,
                           limit: int = DISCORD_MESSAGE_LIMIT) -> str:
    """
    한 메시지 상한을 **보장한다.** 줄 경계에서 자르고 잘린 사실을 적는다.

    🔴 건수 제한만 믿지 않는다. 카드 이름 길이는 카드마다 다르고, 해석
    설명과 경고 줄도 길이가 변한다 — 그래서 마지막에 길이로 한 번 더
    막는다. 자른 사실을 적지 않으면 사용자는 결과가 그것뿐이라고 믿는다.
    """
    if len(text) <= limit:
        return text
    budget = limit - len(TRUNCATION_NOTICE)
    cut = text[:budget]
    #: 줄 중간에서 끊으면 카드 한 줄이 반토막 난다 — 마지막 줄바꿈에서 끊는다.
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    return cut + TRUNCATION_NOTICE


def search_message(agent, query: str,
                   limit: int = SEARCH_RESULT_LIMIT) -> str:
    """
    ``/search`` 의 응답. **discord 를 모른다.**

    검색은 :meth:`~app.main.DeckAgent.search_korean` 이 하고, 이 함수는
    그 결과를 Discord 에 맞게 적는 일만 한다 — 검색 로직을 다시 쓰지
    않는다.

    🔴 **세 가지를 구분해서 적는다** (§5):

    1. 해석하지 못한 말이 있다 (``unknown_terms``) → **조건에 넣지
       않았다**고 분명히 적는다. 검색된 것처럼 보이게 하지 않는다.
    2. 결과가 0건이다 → 그 사실을 적는다. 1번과 겹치면 그것이 원인일 수
       있다고 덧붙인다.
    3. 결과가 있다 → 총 건수와 **보여 준 건수**를 함께 적는다.
    """
    parsed, result = agent.search_korean(query, limit=limit)

    lines = [f"🔎 검색: `{query}`", parsed.explain_ko()]

    if parsed.unknown_terms:
        unknown = ", ".join(f"`{term}`" for term in parsed.unknown_terms)
        lines.append(
            f"⚠️ 해석하지 못한 말: {unknown} — **조건에 넣지 않았습니다.**"
        )

    cards = list(result)[:limit]
    if result.total == 0:
        lines.append("조건에 맞는 카드가 없습니다.")
        if parsed.unknown_terms:
            lines.append(
                "해석하지 못한 말이 원인일 수 있습니다. 다른 말로 다시"
                " 물어봐 주세요."
            )
    else:
        shown = f" (상위 {len(cards)}장 표시)" if result.total > len(cards) else ""
        lines.append(f"검색 결과: {result.total}장{shown}")
        lines.extend(format_card_line(card, index)
                     for index, card in enumerate(cards, 1))

    return clamp_to_discord_limit("\n".join(lines))


#: :class:`~deck.model.ValidationOutcome` 의 표시 기호. :mod:`deck.report` 가
#: 쓰는 것과 같은 기호를 쓴다 — 두 출력에서 같은 결과가 다르게 보이면 안 된다.
#:
#: 키는 ``.value`` 문자열로 두고 조회할 때도 ``.value`` 를 쓴다. 측정해 보면
#: ``ValidationOutcome`` 은 ``str.__hash__`` 를 쓰므로 멤버를 그대로 키로
#: 넣어도 맞지만, 그것은 ``(str, Enum)`` 이라는 선언 방식에 딸린 성질이다.
#: ``.value`` 로 고정하면 그 성질에 기대지 않는다.
_OUTCOME_MARK = {
    "satisfied": "✔",
    "violated": "✗",
    "unverifiable": "?",
}


def paginate(lines: "list[str]",
             limit: int = DISCORD_MESSAGE_LIMIT,
             max_messages: int = DECK_MESSAGE_LIMIT) -> "list[str]":
    """
    줄 목록을 **상한을 넘지 않는 메시지 여러 개**로 묶는다.

    🔴 ``clamp_to_discord_limit`` 와 역할이 다르다. 저쪽은 **버리고** 버렸다고
    적는다 — 검색 결과처럼 "상위 몇 건" 이 원래 의미인 출력에 맞다. 덱은
    그렇지 않다. 40장 중 뒤 15장이 사라진 덱은 그 덱이 아니므로 **나눠
    보낸다.**

    줄을 쪼개지 않는다. 한 줄이 그 자체로 상한을 넘으면 그 줄만
    :func:`clamp_to_discord_limit` 로 줄인다 — 그때는 버린 사실이 적힌다.

    ``max_messages`` 를 넘으면 마지막 메시지에 **몇 줄을 못 보냈는지**
    적는다. 조용히 끊지 않는다.
    """
    pages: list[str] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            pages.append("\n".join(current))
            current = []
            size = 0

    for index, line in enumerate(lines):
        piece = clamp_to_discord_limit(line, limit)
        #: 줄바꿈 한 글자를 함께 센다 — 세지 않으면 이어 붙인 뒤 상한을 넘는다.
        extra = len(piece) + (1 if current else 0)
        if current and size + extra > limit:
            flush()
            if len(pages) >= max_messages:
                remaining = len(lines) - index
                notice = f"… (길이 제한으로 {remaining}줄을 보내지 못했습니다)"
                pages[-1] = clamp_to_discord_limit(
                    pages[-1] + "\n" + notice, limit)
                return pages
            extra = len(piece)
        current.append(piece)
        size += extra
    flush()
    return pages


def _deck_slot_lines(title: str, slots) -> "list[str]":
    """한 칸 한 줄. 매수·이름·카드 ID·역할만 적는다."""
    if not slots:
        return []
    count = sum(slot.copies for slot in slots)
    lines = ["", f"**[{title}]** {count}장 (종류 {len(slots)})"]
    lines.extend(
        f"  {slot.copies}x {slot.name}  [{slot.card_id}]"
        f"  · {slot.role.describe_ko()}"
        for slot in slots
    )
    return lines


def _deck_role_evidence_lines(draft) -> "list[str]":
    """
    🔴 역할의 **출처**를 역할과 따로 적는다 (Phase 5-D).

    역할만 보여 주면 "근거 없이 붙은 역할" 과 "Lua 효과 범주까지 확인한
    역할" 이 같아 보인다. Phase 5-C 의 `/deck` 이 실제로 그렇게 8종을
    "패트랩 계열" 로 보여 줬다.
    """
    grouped: dict[tuple[str, str], int] = {}
    for slot in draft.all_slots():
        key = (slot.role.describe_ko(), slot.evidence.describe_ko())
        grouped[key] = grouped.get(key, 0) + 1
    if not grouped:
        return []
    lines = ["", "**[역할의 출처]**"]
    lines.extend(f"  - {role} ← {evidence} ({kinds}종류)"
                 for (role, evidence), kinds in grouped.items())
    return lines


def _deck_reason_lines(draft) -> "list[str]":
    """
    **채택 근거**를 역할별로 한 번만 적는다.

    🔴 근거를 버리지 않는다. :class:`~deck.model.DeckSlot` 의 ``reason`` 은
    (테마, 역할) 조합으로 정해지므로 카드마다 같은 문장이 반복된다. 카드마다
    한 줄씩 적으면 덱 하나가 3,600자를 넘고, 그러면 나눠 보낼 메시지 수만
    늘어난다. 그래서 **같은 문장을 묶어 몇 종류가 그 근거로 들어왔는지**
    함께 적는다 — 요약이 아니라 같은 정보의 다른 배치다.
    """
    grouped: dict[str, int] = {}
    for slot in draft.all_slots():
        grouped[slot.reason] = grouped.get(slot.reason, 0) + 1
    if not grouped:
        return []
    lines = ["", "**[채택 근거]**"]
    lines.extend(f"  - {reason} ({kinds}종류)"
                 for reason, kinds in grouped.items())
    return lines


def _deck_validation_lines(validation) -> "list[str]":
    """규격 검증 결과. 🔴 '검증 불가' 를 '통과' 로 적지 않는다."""
    lines = ["", "**[덱 규격 검증]**"]
    for finding in validation.findings:
        mark = _OUTCOME_MARK.get(finding.outcome.value, "?")
        lines.append(f"  {mark} {finding.rule}: "
                     f"{finding.outcome.describe_ko()} — {finding.detail}")
        if finding.source:
            lines.append(f"      근거 규칙: {finding.source}")
    if validation.unverifiable:
        lines.append("  🔴 검증 불가 항목은 **통과가 아닙니다.** "
                     "사람이 확인해야 합니다.")
    return lines


def deck_messages(agent, request_text: str) -> "list[str]":
    """
    ``/deck`` 의 응답. **discord 를 모른다.** 메시지 여러 개를 돌려준다.

    기존 덱 빌더를 그대로 부른다 — 새로 만들지 않는다:
    :func:`~deck.request.parse_deck_request` →
    :meth:`~deck.builder.DeckBuilder.build` →
    :meth:`~deck.validator.DeckValidator.validate`.

    🔴 **세 가지를 구분해서 처리한다.**

    1. 요청에서 테마도 목표도 읽지 못했다 (``is_empty``) → **덱을 만들지
       않고** 어떻게 적어야 하는지 안내한다. CLI 도 같은 자리에서 멈춘다
       (``app.main.cmd_deck`` 가 ``is_empty`` 면 종료 코드 1).
    2. 테마를 하나도 카드군으로 해석하지 못했다 → **덱을 보내지 않는다.**
       빌더는 이때도 덱을 돌려주지만(실측: "존재하지않는테마 덱" → 보강
       카드 20종 40장) 그것은 요청한 테마와 **아무 관계가 없는** 덱이다.
       Discord 에서 그것을 보내면 사용자는 그 테마의 덱을 받았다고 믿는다.
       🔴 ``deck/`` 을 고치지 않고 어댑터에서 막는다 — 빌더의 계약은 그대로
       두고, 보여 줄지 말지만 여기서 정한다.
    3. 일부만 해석됐다 → 덱을 보내되 **해석 실패한 테마를 맨 앞에** 적는다.
    """
    from deck.builder import DeckBuilder
    from deck.request import parse_deck_request
    from deck.validator import DeckValidator

    request = parse_deck_request(request_text)

    header = [f"🃏 덱 요청: `{request_text}`", request.describe_ko()]

    if request.is_empty:
        return ["\n".join(header + [
            "",
            "🔴 테마도 목표도 해석하지 못해 **덱을 만들지 않았습니다.**",
            "카드군 이름을 넣어 다시 적어 주세요. 예:",
            "  `오르페골 덱 짜줘`",
            "  `오르페골 + K9으로 덱을 짜 줘. 초동 안정성을 우선하고"
            " 패트랩도 충분히`",
            "지정할 수 있는 목표: 초동 안정성 · 견제(제압) · 패트랩 비중",
        ])]

    draft = DeckBuilder(agent.repository).build(request)

    if draft.unresolved_themes and not draft.resolved_themes:
        failed = ", ".join(f"`{t}`" for t in draft.unresolved_themes)
        return ["\n".join(header + [
            "",
            f"🔴 테마를 카드군으로 해석하지 못했습니다: {failed}",
            "**그래서 덱을 보내지 않습니다.** 덱 빌더는 이 경우에도 테마"
            " 밖의 카드로 40장을 채우지만, 그것은 요청한 테마의 덱이"
            " 아닙니다.",
            "카드군 이름을 다시 확인해 주세요 — `/search` 로 카드 이름을"
            " 먼저 찾아볼 수 있습니다.",
        ])]

    validation = DeckValidator().validate(draft)

    lines = list(header)
    if draft.unresolved_themes:
        failed = ", ".join(f"`{t}`" for t in draft.unresolved_themes)
        lines.append(f"🔴 해석하지 못한 테마: {failed} — **이 테마에서"
                     f" 가져온 카드는 없습니다.**")
    lines.append("")
    lines.append(f"**메인 {draft.main_count}장** (종류 {len(draft.main)})"
                 f" · **엑스트라 {draft.extra_count}장**"
                 f" (종류 {len(draft.extra)})")
    if draft.resolved_themes:
        lines.append(f"해석된 카드군: {', '.join(draft.resolved_themes)}")

    lines.extend(_deck_slot_lines("메인 덱", draft.main))
    lines.extend(_deck_slot_lines("엑스트라 덱", draft.extra))
    lines.extend(_deck_role_evidence_lines(draft))
    lines.extend(_deck_reason_lines(draft))
    lines.extend(_deck_validation_lines(validation))
    if draft.notes:
        lines.append("")
        lines.append("**[구성 기록]**")
        lines.extend(f"  - {note}" for note in draft.notes)

    return paginate(lines)


class ComboVerdict(str, Enum):
    """
    전개 계획 하나에 대한 **표시용 판정.** Discord 출력 계층에만 있다.

    🔴 **엔진 계약을 바꾸지 않는다.** 걸음별 상태는 이미
    :class:`~deck.model.StepStatus` 가, 근거 층은
    :class:`~deck.model.StepBasis` 가 적는다. 여기 있는 것은 그 걸음들을
    **한 줄로 요약하는 표시**이고, 새 상태를 엔진이나 ``deck/`` 에
    추가하지 않았다.

    🔴 **``VERIFIED`` 와 ``PARTIALLY_VERIFIED`` 가 없는 것이 의도다.**
    :class:`~deck.planner.ComboPlanner` 는 **엔진을 실행하지 않는다** —
    ``EFFECT_LIBRARY`` 를 **읽어** 실행 구현이 등록된 카드 ID 집합(실측
    13장)을 만들고, 패의 카드마다 걸음을 **정적으로** 만든다. ``Duel`` ·
    ``GameState`` · ``ActionValidator`` 호출이 그 모듈에 하나도 없다.

    그러므로 "실행해서 검증했다" 고 말할 수 있는 전개가 **지금은 하나도
    없다.** :attr:`~deck.model.StepStatus.CONFIRMED` 조차 "엔진에 실행
    구현이 있어 **돌려볼 수 있다**" 는 뜻이고 "돌려 봤다" 가 아니다.
    그래서 가장 높은 판정이 :attr:`GROUNDED_UNEXECUTED` 다.
    """

    GROUNDED_UNEXECUTED = "grounded_unexecuted"
    """근거 있는 걸음이 있다. 🔴 **실행 검증은 하지 않았다.**"""
    UNVERIFIED = "unverified"
    """근거 있는 걸음을 찾지 못했다. 전개 후보라고도 말하지 않는다."""
    UNSUPPORTED = "unsupported"
    """필요한 절차가 엔진에 없어 계획 자체를 세우지 못했다."""

    def describe_ko(self) -> str:
        return {
            ComboVerdict.GROUNDED_UNEXECUTED:
                "근거 있음 · 🔴 실행 검증 안 됨",
            ComboVerdict.UNVERIFIED: "검증되지 않음 (근거 있는 걸음 없음)",
            ComboVerdict.UNSUPPORTED: "엔진 미지원 (계획 불가)",
        }[self]

    def detail_ko(self) -> str:
        return {
            ComboVerdict.GROUNDED_UNEXECUTED:
                "근거 있는 걸음이 있습니다. 🔴 그래도 **실제로 돌려 본"
                " 것이 아닙니다** — 이 저장소의 전개 계획은 엔진을 실행하지"
                " 않고 등록된 구현 목록을 읽어 만듭니다. 합법인지는 사람이"
                " 확인해야 합니다.",
            ComboVerdict.UNVERIFIED:
                "근거 있는 걸음을 하나도 찾지 못했습니다. 🔴 전개가"
                " 불가능하다는 뜻이 아니라, **이 저장소가 판정하지 못했다**"
                " 는 뜻입니다.",
            ComboVerdict.UNSUPPORTED:
                "이 패로 하려면 엔진에 없는 절차가 필요합니다 (아래 미지원"
                " 목록). 🔴 미구현이라는 사실이지 불가능이라는 뜻은"
                " 아닙니다.",
        }[self]


#: :class:`~deck.model.StepStatus` 의 표시 기호. :mod:`deck.report` 와 같다.
_STEP_MARK = {
    "confirmed": "✔",
    "conditional": "~",
    "unknown": "?",
    "unsupported": "✗",
}


def combo_verdict(plan) -> ComboVerdict:
    """
    계획을 **한 줄로 요약한다.** 🔴 없는 검증을 만들지 않는다.

    판정은 걸음들의 :class:`~deck.model.StepStatus` 에서만 나온다 —
    이 함수가 카드를 다시 보거나 효과를 다시 해석하지 않는다.
    """
    statuses = [step.status.value for step in plan.steps]
    if not statuses:
        #: 걸음이 없다. 패가 비었거나 저장소가 아무 근거도 찾지 못했다.
        return ComboVerdict.UNVERIFIED
    if all(status == "unsupported" for status in statuses):
        return ComboVerdict.UNSUPPORTED
    if any(status in ("confirmed", "conditional") for status in statuses):
        return ComboVerdict.GROUNDED_UNEXECUTED
    return ComboVerdict.UNVERIFIED


def _hand_activation_correction(agent, step) -> "str | None":
    """
    🔴 플래너가 **패에서 발동한다고 적은 걸음**을 효과 데이터로 되짚는다.

    ``deck/planner.py`` 의 효과 걸음은 ``card.has_effect_from("HAND")`` 로
    갈린다. 그 메서드는 ``SetRange`` 에 ``LOCATION_HAND`` 이 있는지만 보므로
    **특수 소환 절차**(``EFFECT_SPSUMMON_PROC``)에도 참이 된다 — 덱 빌더에서
    같은 신호가 8장을 "패트랩 계열" 로 만든 것과 **같은 결함**이다.

    실측: `/combo hand:펜리르` 는 "'펜리르' 의 패에서 발동하는 효과를
    씁니다" 를 **조건부**로 적는다. 그런데 펜리르의 패 범위 블록은 특수
    소환 절차 하나이고, 패에서 발동 가능한 효과는 **0개**다. 독법사 ·
    텐사우전드 드래곤도 같다.

    🔴 **플래너를 고치지 않는다.** 그것은 이번 단계의 범위 밖이고, 구조적
    TODO 를 임의로 고치지 않기로 했다. 대신 **틀린 행동을 그대로 전달하지
    않는다** — 출력 계층에서 효과 데이터로 정정한다
    (:mod:`deck.evidence` 는 이미 있는 것을 쓴다).
    """
    from deck.evidence import hand_effect_facts
    from deck.model import StepBasis

    if step.basis is not StepBasis.LUA_PARSED:
        return None
    card = agent.repository.get(step.card_id)
    if card is None or not card.has_effect_from("HAND"):
        return None
    facts = hand_effect_facts(card)
    if facts.activatable_from_hand:
        return None
    return ("🔴 **정정**: 이 카드에는 패에서 **발동 가능한 효과가"
            " 없습니다** — 패 범위 블록"
            f" {facts.hand_range_blocks}개가 전부 발동이 아닌 절차·지속"
            " 효과입니다 (특수 소환 절차 등). 위 걸음은 전개 계획이"
            " 발동 위치만 보고 적은 것이므로 **그대로 믿지 마세요.**")


def _combo_step_lines(agent, plan) -> "list[str]":
    """걸음마다 상태·근거·조건·기대를 적는다. 🔴 효과를 서술하지 않는다."""
    if not plan.steps:
        return ["", "계획된 걸음이 없습니다."]
    lines = ["", f"**[전개 걸음]** {len(plan.steps)}걸음"]
    for step in plan.steps:
        mark = _STEP_MARK.get(step.status.value, "?")
        lines.append(f"  {step.order}. {mark} {step.action}")
        lines.append(f"      상태: {step.status.describe_ko()}"
                     f"  ·  근거: {step.basis.describe_ko()}")
        for requirement in step.requires:
            lines.append(f"      필요: {requirement}")
        lines.append(f"      기대: {step.expected}")
        if step.note:
            lines.append(f"      비고: {step.note}")
        correction = _hand_activation_correction(agent, step)
        if correction is not None:
            lines.append(f"      {correction}")
    return lines


def _executed_lines(agent, recipe_text: str,
                    hand_ids: "list[int]",
                    line_text: str = "") -> "tuple[list[str], bool]":
    """
    🔴 **실제 엔진 실행 절** (Phase 6-T). 레시피가 없으면 빈 목록이 아니라
    **무엇이 부족한지** 적는다 (§5 · §15).

    돌려주는 것은 ``(줄들, 입력이 거절되었는가)`` 짝이다 (Phase 6-AA).
    둘째 값이 참이면 **이번 요청의 입력이 규칙에 어긋났다**는 뜻이고, 그때
    부르는 쪽은 정적 전개 추천을 **내지 않는다** — 거절한 입력에 대해
    "이렇게 전개하면 된다" 를 보여 주면 사용자는 자기 입력이 통과한 줄로
    읽는다 (사용자 실험 ③ 이 그것을 잡았다).

    ``deck:`` 초안을 실제 덱으로 쓰지 않는 이유가 여기에 적혀 있어야 한다 —
    출력에 없으면 사용자는 초안으로 검증했다고 믿는다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import COMBO_LINES, line_named, line_progress
    from deck.opening import build_opening, execute_opening, opening_hand_size
    from deck.recipe import parse_recipe
    from deck.report import (
        render_opening_board,
        render_opening_run,
        render_opening_setup,
    )

    expected = opening_hand_size()
    if not recipe_text or not recipe_text.strip():
        return [
            "**[실제 엔진 실행]**",
            "🔴 **하지 않았습니다** — 실제 덱 레시피가 없습니다.",
            f"선공 전개를 엔진으로 검증하려면 패 {expected}장만으로는"
            " 부족하고 **덱 레시피 전체**가 필요합니다 — 남은 덱의 장수와"
            " 카드가 효과의 발동 조건이기 때문입니다 (예: 욕망의 항아리는"
            " 자신 덱에 2장 이상이어야 해결됩니다).",
            "🔴 `deck:` 는 **자연어 요청**이고 이 저장소가 추천한 초안을"
            " 만듭니다 — 사용자가 확정한 덱이 아니므로 그것으로 실행"
            " 검증하지 않습니다.",
            "넘기는 방법 (`recipe:`):",
            "  `recipe:욕망의 항아리 x3, 11091375 x37`",
            "  또는 YDK 그대로 (`#main` 아래 패스코드 한 줄에 하나)",
        ], False

    parsed = parse_recipe(recipe_text, agent.repository)
    lines = ["**[실제 엔진 실행]**"]
    if parsed.unresolved:
        names = ", ".join(f"`{t}`" for t in parsed.unresolved[:10])
        lines.append(f"⚠️ 레시피에서 카드를 찾지 못했습니다: {names}"
                     " — **덱에 넣지 않았습니다.**")
    for note in parsed.notes:
        lines.append(f"  {note}")
    if parsed.draft is None:
        lines.append("🔴 레시피에서 카드를 하나도 읽지 못해 **실행하지"
                     " 않았습니다.**")
        #: 레시피를 읽지 못한 것은 **입력 거절이 아니다** — 규칙 위반을
        #: 판정한 것이 아니라 글자를 못 읽은 것이므로, 정적 계획은 그대로
        #: 보여 준다 (그쪽은 레시피를 쓰지 않는다).
        return lines, False

    #: 🔴 **유발 발동과 해결 시점 선택을 꽂는다** (Phase 6-Z).
    #:
    #: 꽂지 않으면 유발 효과가 ``legal_actions`` 에 오르지 않고, 올라도
    #: 해결 중에 고를 사람이 없어 거절된다. 둘 다 조립 층과 Agent 층의
    #: 것이므로 ``deck`` 이 만들지 않고 **이 자리가 값으로** 넘긴다.
    #:
    #: 🔴 **CLI 와 같은 것을 꽂는다** — ``app.main.opening_wiring`` 하나가
    #: 만든다. 어댑터가 제 손으로 만들면 ``agent`` · ``integration`` 을 직접
    #: import 하게 되고, 그 경계는 Phase 5-A 부터 지켜 온 것이다
    #: (``test_discord_bot::test_15``).
    #: 🔴 **검증용 전개 정책을 고를 수 있다** (Phase 6-AC).
    #:
    #: 이름을 주지 않으면 ``choose`` 를 넘기지 않고, 그때 동작은 6-AB 와 한
    #: 글자도 다르지 않다 (``execute_opening`` 이 ``first_meaningful`` 을
    #: 쓴다). 이름이 틀리면 **비슷한 것을 골라 주지 않고** 그 사실을 적는다 —
    #: 사용자가 요청한 경로가 아닌 것으로 검증한 결과를 보여 주면 안 된다.
    line = line_named(line_text)
    if line_text and line_text.strip() and line is None:
        names = " · ".join(f"`{name}`" for name in sorted(COMBO_LINES))
        lines.append(
            f"⚠️ `line:{line_text}` 라는 검증용 전개 경로가 없습니다 —"
            f" **기본 선택 방식(`first_meaningful`)으로 실행했습니다.**"
            f" 있는 경로: {names}"
        )
    #: 🔴 ``line`` 을 함께 넘긴다 (Phase 6-AD) — 그 경로가 **해결 시점에**
    #: 고르려는 카드를 선택 정책에 싣는 자리가 ``opening_wiring`` 하나다.
    #: CLI 와 같은 것을 꽂는다는 위 규율이 그대로 적용된다.
    chooser, triggers = opening_wiring(agent.repository, line)
    setup = build_opening(
        agent.repository,
        parsed.draft,
        hand_ids,
        chooser=chooser,
        triggers=triggers,
    )
    run = execute_opening(
        setup,
        agent.repository,
        **({"choose": line.policy()} if line is not None else {}),
    )
    #: 🔴 **한 줄 요약은 실측에서만 나온다.** 실행한 걸음 · 해결된 걸음 ·
    #: 상태가 바뀐 걸음을 각각 센다 (세 사실을 묶지 않는다 — 6-R).
    if setup.can_run:
        lines.append(
            f"✅ **엔진이 실제로 {run.executed}걸음 실행**했습니다"
            f" (효과 해결 {run.effects_resolved}걸음 · 상태 변경"
            f" {run.state_changes}걸음). 아래는 실측 기록입니다."
        )
        if line is None:
            lines.append(
                "🔴 고른 방식은 **검증용 기준점**입니다 — 행동은"
                " `first_meaningful` (판을 바꾸는 후보의 첫 번째), 해결 중의"
                " 카드 선택은 `first-permitted` (허용된 후보의 앞쪽). **최선의"
                " 전개가 아닙니다.**"
            )
        else:
            #: 🔴 **무엇으로 실행했는지 그대로 적는다** (Phase 6-AC §5).
            #: "경로를 따라갔다" 와 "최선을 찾았다" 를 섞지 않는다.
            progress = line_progress(run, line)
            lines.append(
                f"🔴 고른 방식은 **검증용 전개 정책 `{line.name}`** 입니다 —"
                f" 사람이 적어 둔 경로를 따라갔을 뿐이고 **최선 전개 탐색도,"
                f" 범용 AI 도, 엔진이 스스로 찾은 전개도 아닙니다.**"
                f" 해결 중의 카드 선택은 `first-permitted` 이고, 경로가"
                f" 적어 둔 카드가 있으면 **엔진이 낸 허용 후보 안에서** 그것을"
                f" 먼저 집습니다."
            )
            lines.append(f"  경로: {line.title_ko}")
            if line.resolution_preferences:
                #: 🔴 **해결 시점의 선택을 따로 적는다** (6-AD §6). 발동
                #: 기록의 대상이 비어 있는 것이 **정상**이므로, 그 칸만 보고
                #: "아무것도 고르지 않았다" 로 읽히지 않게 한다.
                wanted = " · ".join(
                    f"`{card_id}`" for card_id in line.resolution_preferences
                )
                lines.append(
                    f"  해결 중에 고르려는 카드: {wanted}"
                    f" (후보 밖에서 끌어오지 않습니다)"
                )
            lines.append(f"  {progress.describe_ko()}")
        #: 🔴 **미지원 사유를 요약 줄에 올린다** (Phase 6-AB 최종 보완 ④).
        #: 걸음 기록 안에만 두면 묻힌다 — 실행에 영향을 준 사실이고,
        #: 이것이 있으면 위의 "N걸음 실행" 을 "이 패로 할 수 있는 것을 다
        #: 했다" 로 읽어서는 안 된다.
        if run.unsupported:
            lines.append(
                f"🔴 **엔진이 지원하지 않아 후보가 되지 못한 것이"
                f" {len(run.unsupported)}건** 있었습니다 — 아래 `미지원"
                f" 사유` 를 보세요. 규칙이 막은 것이 아니라 **이 저장소에"
                f" 그 규칙이 없다**는 뜻이고, 그래서 위의 걸음 수를 **이"
                f" 패의 전개를 다 했다**로 읽을 수 없습니다."
            )
        if run.stopped_kind == "unsupported":
            lines.append(
                "🔴 멈춘 자리가 **미지원 때문**입니다 — 남은 후보가"
                " 흐름뿐이었지만 같은 자리에 지원하지 않아 오르지 못한"
                " 후보가 있었습니다. **정상 전개 종료가 아닙니다.**"
            )
        #: 🔴 **"더 고를 행동이 없다" 와 "끝까지 검증했다" 를 가른다**
        #: (보완8 세 항목 ①). 멈춘 자리가 깨끗해도 전개 도중에 미지원을
        #: 지나왔으면 전체를 검증한 것이 아니다 — 그 자리를 ``flow_only``
        #: 하나로 읽으면 "정상 검증 완료" 가 된다.
        elif run.stopped_kind == "flow_only" and not run.fully_supported:
            lines.append(
                "🔴 멈춘 자리에는 미지원이 없었지만, **전개 도중에 지나온"
                " 미지원이 있습니다** — 그래서 **더 고를 행동이 없다**는"
                " 것과 **전개 전체를 지원 범위 안에서 검증했다**는 것은"
                " 다릅니다. 위 `미지원 사유` 목록이 그 한계입니다."
            )
    else:
        lines.append("🔴 **실행하지 않았습니다** — 입력 검증을 통과하지"
                     " 못했습니다 (아래 참조).")
    lines.extend(render_opening_setup(setup).splitlines())
    lines.extend(render_opening_run(run).splitlines())
    lines.extend(render_opening_board(setup, agent.repository).splitlines())
    return lines, not setup.can_run


def combo_messages(agent, hand_text: str, board_text: str = "",
                   deck_text: str = "", recipe_text: str = "",
                   line_text: str = "") -> "list[str]":
    """
    ``/combo`` 의 응답. **discord 를 모른다.** 메시지 여러 개를 돌려준다.

    기존 콤보 플래너를 그대로 부른다 — 새 전개 엔진을 만들지 않는다:
    :func:`app.main._parse_card_ids` →
    :class:`~deck.hand.FixedHand` →
    :meth:`~deck.planner.ComboPlanner.plan`.

    ``deck_text`` 를 주면 :class:`~deck.builder.DeckBuilder` 로 초안을
    만들어 ``plan(draft=…)`` 에 넘긴다 — 그러면 플래너가 "이 패가 덱에서
    나올 수 있는가" 를 **실제로** 본다. 주지 않으면 플래너가 그 검증을
    하지 않았다고 적는다.

    🔴 **입력을 추측해서 해석하지 않는다.** 이름을 찾지 못한 토큰은
    버리지 않고 그대로 적는다 — 해석된 카드만으로 계획을 세우면 사용자는
    자기가 적은 카드가 들어간 계획을 봤다고 믿는다.

    ``line_text`` (Phase 6-AC) 는 **검증용 전개 정책의 이름**이다. 주면 그
    경로를 따라가고, 주지 않으면 ``first_meaningful`` 그대로다 — 사용자가
    고르지 않은 정책이 조용히 행동 선택을 바꾸지 않는다 (§5).
    """
    from app.main import _parse_card_ids
    from deck.hand import FixedHand
    from deck.planner import ComboPlanner

    hand_ids, hand_unresolved = _parse_card_ids(hand_text or "", agent)
    board_ids, board_unresolved = _parse_card_ids(board_text or "", agent)

    lines = [f"🌀 전개 요청 — 패: `{hand_text}`"]
    if board_text:
        lines.append(f"필드·묘지: `{board_text}`")

    def _named(card_ids: "list[int]") -> str:
        bits = []
        for card_id in card_ids:
            card = agent.repository.get(card_id)
            bits.append(f"{card.display_name()} [{card_id}]" if card
                        else f"🔴 저장소에 없는 ID [{card_id}]")
        return ", ".join(bits)

    if hand_ids:
        lines.append(f"해석된 패 {len(hand_ids)}장: {_named(hand_ids)}")
    if board_ids:
        lines.append(f"해석된 필드·묘지 {len(board_ids)}장: {_named(board_ids)}")

    unresolved = hand_unresolved + board_unresolved
    if unresolved:
        names = ", ".join(f"`{name}`" for name in unresolved)
        lines.append(f"⚠️ 카드를 찾지 못했습니다: {names}"
                     f" — **계획에 넣지 않았습니다.**")

    if not hand_ids:
        lines.append("")
        lines.append("🔴 초기 패를 하나도 해석하지 못해 **계획을 세우지"
                     " 않았습니다.**")
        lines.append("카드 이름이나 카드 ID 를 쉼표로 적어 주세요. 예:")
        lines.append("  `/combo hand:오르페골 디베르, 오르페골 스켈레촌`")
        lines.append("  `/combo hand:55144522`")
        lines.append("🔴 무작위 패 생성은 구현되어 있지 않습니다 — 패는"
                     " 직접 지정해야 합니다.")
        return paginate(lines)

    draft = None
    if deck_text and deck_text.strip():
        from deck.builder import DeckBuilder
        from deck.request import parse_deck_request

        request = parse_deck_request(deck_text)
        if request.is_empty:
            lines.append(f"⚠️ 덱 요청 `{deck_text}` 에서 테마도 목표도"
                         f" 읽지 못해 **덱과 맞는지는 확인하지 않았습니다.**")
        else:
            draft = DeckBuilder(agent.repository).build(request)
            lines.append(f"덱 초안과 비교: `{deck_text}`"
                         f" → 메인 {draft.main_count}장")

    #: 🔴 **실제 레시피를 주면 엔진으로 돌린다** (Phase 6-T). 자연어
    #: ``deck:`` 초안과 **가르는 것이 요점**이다 — 초안은 이 저장소가 추천한
    #: 구성이고 사용자가 확정한 덱이 아니다 (§5).
    executed_lines, input_refused = _executed_lines(
        agent, recipe_text, hand_ids, line_text
    )

    #: 🔴 **입력이 거절되면 정적 전개 추천을 내지 않는다** (Phase 6-AA —
    #: 사용자 실험 ③). 실측으로, 「기르수: 패 4장 > 덱 3장」으로 거절한
    #: 요청에 대해 아래 정적 계획이 기르수 소환과 효과를 나열하고 "확정" ·
    #: "엔진이 허가함" 으로 적었다. 그 두 문장이 한 응답 안에 같이 있으면
    #: 사용자는 입력이 통과한 줄로 읽는다.
    if input_refused:
        if executed_lines:
            lines.append("")
            lines.extend(executed_lines)
        lines.append("")
        lines.append("🔴 **정적 전개 추천은 내지 않았습니다** — 이번 요청의"
                     " 입력이 규칙 검증을 통과하지 못했습니다.")
        lines.append("거절한 입력에 대해 전개를 추천하면 그 입력이 통과한"
                     " 것으로 읽힙니다. 위에 적힌 위반을 고쳐서 다시"
                     " 보내 주세요.")
        return paginate(lines)

    plan = ComboPlanner(agent.repository).plan(FixedHand(tuple(hand_ids)),
                                               board=board_ids, draft=draft)

    verdict = combo_verdict(plan)

    #: 🔴 **실제 실행을 정적 계획보다 앞에 둔다.** 둘을 같은 목록에 섞지
    #: 않고, 먼저 "실제로 돌린 것" 을 보여 준 다음 "돌리지 않은 계획" 을
    #: 보여 준다 (§13 "사용자에게 혼동시키지 않는다").
    if executed_lines:
        lines.append("")
        lines.extend(executed_lines)

    lines.append("")
    lines.append("**[아래는 실행하지 않은 정적 계획입니다]**")
    lines.append("🔴 카드 데이터를 읽어 만든 계획이고 **엔진으로 돌린 것이"
                 " 아닙니다.**")
    #: 🔴 **``ComboVerdict`` 는 이 정적 계획의 판정이다** (Phase 6-T §13).
    #: 맨 위에 두면 위의 "실제 엔진 실행" 결과의 판정처럼 읽힌다 — 그래서
    #: 이 절 안으로 옮겼다. 판정 자체는 바꾸지 않았다 (그것은 옳다).
    lines.append(f"**정적 계획의 판정: {verdict.describe_ko()}**")
    lines.append(verdict.detail_ko())
    lines.extend(_combo_step_lines(agent, plan))

    if plan.stopped_reason:
        lines.append("")
        lines.append(f"🔴 중단: {plan.stopped_reason}")

    if plan.unsupported:
        lines.append("")
        lines.append("**[엔진이 지원하지 않아 계획에 넣지 않은 절차]**")
        lines.extend(f"  - {item}" for item in plan.unsupported)

    #: 🔴 **같은 검사를 두 번 다르게 말하지 않는다** (Phase 6-AB 보완8).
    #:
    #: 6-AA 는 플래너의 *"덱 초안을 주지 않아 검증하지 않았습니다"* 를
    #: 그대로 보여 주고 **그 아래에 해명 두 줄**을 붙였다. 그 해명은 참이지만,
    #: 사용자가 읽는 것은 **상충하는 검사 결과 두 개와 변명**이다 — 플래너가
    #: 별도 입력을 받지 않았다는 것은 **내부 사정**이고 그 자체가 검사 결과로
    #: 전달될 일이 아니다.
    #:
    #: 그래서 이미 ``recipe:`` 가 검사한 항목은 **그 목록에서 빼고**, 실제
    #: 결과를 **한 번** 적는다. 🔴 **플래너의 판정을 바꾸지 않는다** —
    #: ``plan.manual_checks`` 는 그대로이고, 바뀌는 것은 사용자에게 보여 줄
    #: 때 어느 줄이 이미 답을 받았는지 가리는 일뿐이다.
    answered_by_recipe = bool(recipe_text and recipe_text.strip())
    shown_checks = [
        item for item in plan.manual_checks
        if not (answered_by_recipe and draft is None
                and "패가 덱에서 나올 수" in item)
    ]
    hidden = len(plan.manual_checks) - len(shown_checks)

    if shown_checks:
        lines.append("")
        lines.append("**[사람이 직접 확인할 것]**")
        lines.extend(f"  - {item}" for item in shown_checks)

    if hidden:
        lines.append("")
        lines.append("🔴 **패가 덱에서 나올 수 있는지는 이 요청에서 이미"
                     " 검사했습니다** — 위쪽 `[실제 엔진 실행]` 절이"
                     " `recipe:` 로 판정했고, 그 결과가 이 응답의 판정입니다."
                     " (정적 계획은 자연어 `deck:` 초안을 받는 별도 경로여서"
                     " 그 검사를 따로 하지 않습니다.)")

    return paginate(lines)


class SearchService:
    """
    카드 데이터를 **한 번만** 만들어 들고 있는 자리.

    이름에 ``Search`` 가 남아 있지만 ``/search`` 와 ``/deck`` 이 **같은**
    :class:`~app.main.DeckAgent` 를 쓴다. 이름을 바꾸지 않은 이유: 이름만
    바꾸는 변경이 Phase 5-C 의 목적이 아니고, 이 클래스를 가리키는 기존
    테스트들을 함께 건드려야 한다. 역할은 "명령들이 공유하는 카드 데이터
    보관소" 하나다.

    왜 클래스인가: "한 번만 만들었다" 를 테스트가 확인할 수 있어야 한다.
    모듈 전역 변수로 두면 그 사실을 세어 볼 방법이 없고, 테스트가 서로의
    상태를 물려받는다.

    ``builder`` 를 주입할 수 있게 둔 이유: 테스트가 실제 3초짜리 빌드를
    돌리지 않고도 "한 번만 부른다" 와 "실패를 어떻게 다루는가" 를 확인할
    수 있어야 한다.
    """

    def __init__(self, builder=None):
        self._builder = builder
        self._agent = None
        self._error: "BaseException | None" = None
        #: 🔴 빌더를 실제로 부른 횟수. 테스트가 이것으로 "한 번만" 을 본다.
        self.build_count = 0

    def _default_builder(self):
        from app.main import DeckAgent

        return DeckAgent.build()

    @property
    def ready(self) -> bool:
        return self._agent is not None

    @property
    def error(self) -> "BaseException | None":
        return self._error

    @property
    def agent(self):
        return self._agent

    def prepare(self) -> bool:
        """
        카드 데이터를 준비한다. 성공 여부를 돌려준다.

        🔴 **이미 준비됐으면 다시 만들지 않는다.** ``on_ready`` 는 재접속
        때 다시 불릴 수 있고, 그때마다 3초를 쓰면 안 된다.

        🔴 실패를 삼키지 않는다. 예외를 기록하고 ``False`` 를 돌려주며,
        그 뒤 :meth:`search_text` 가 "지금은 검색할 수 없습니다" 를 돌려준다.
        """
        if self._agent is not None:
            return True
        builder = self._builder or self._default_builder
        self.build_count += 1
        try:
            self._agent = builder()
        except Exception as error:  # noqa: BLE001 - 어떤 실패든 기록해야 한다
            self._error = error
            self._agent = None
            logger.exception("카드 데이터 초기화에 실패했습니다.")
            return False
        self._error = None
        logger.info("카드 데이터 준비 완료 (검색 사용 가능).")
        return True

    def search_text(self, query: str,
                    limit: int = SEARCH_RESULT_LIMIT) -> str:
        """준비됐으면 검색하고, 아니면 **안내 문구**를 돌려준다."""
        if self._agent is None:
            return UNAVAILABLE_MESSAGE
        return search_message(self._agent, query, limit=limit)

    def combo_texts(self, hand_text: str, board_text: str = "",
                    deck_text: str = "", recipe_text: str = "",
                    line_text: str = "") -> "list[str]":
        """
        전개 계획을 세워 **메시지 목록**을 돌려준다.

        🔴 ``/search`` · ``/deck`` 과 **같은 카드 데이터를 쓴다.** 콤보
        플래너가 요구하는 것은 ``repository`` 하나이고 그것은 이미 여기
        있다.

        🔴 **예외를 밖으로 내보내지 않는다** (``deck_texts`` 와 같은 이유).
        """
        if self._agent is None:
            return [COMBO_UNAVAILABLE_MESSAGE]
        try:
            return combo_messages(self._agent, hand_text, board_text,
                                  deck_text, recipe_text, line_text)
        except Exception:  # noqa: BLE001 - 봇을 죽이지 않는다
            logger.exception("전개 계획 생성에 실패했습니다. 패=%r 필드=%r"
                             " 덱=%r 레시피=%r 경로=%r", hand_text, board_text,
                             deck_text, recipe_text, line_text)
            return [COMBO_ERROR_MESSAGE]

    def deck_texts(self, request_text: str) -> "list[str]":
        """
        덱 초안을 만들어 **메시지 목록**을 돌려준다.

        🔴 ``/search`` 와 **같은 카드 데이터를 쓴다.** 덱 빌더가 요구하는
        것은 :attr:`app.main.DeckAgent.repository` 하나이고 그것은 이미
        여기 있다 — 덱 때문에 리포지토리를 다시 만들지 않는다.

        🔴 **예외를 밖으로 내보내지 않는다.** 핸들러에서 터지면
        ``discord.py`` 가 그 상호작용을 실패로 끝내고 사용자는 "애플리케이션이
        응답하지 않습니다" 만 본다. 여기서 잡아 로그에 스택을 남기고
        사용자에게는 :data:`DECK_ERROR_MESSAGE` 를 돌려준다 — 예외 내용은
        **사용자에게 보내지 않는다.**
        """
        if self._agent is None:
            return [DECK_UNAVAILABLE_MESSAGE]
        try:
            return deck_messages(self._agent, request_text)
        except Exception:  # noqa: BLE001 - 봇을 죽이지 않는다
            logger.exception("덱 생성에 실패했습니다. 요청=%r", request_text)
            return [DECK_ERROR_MESSAGE]


#: 봇 하나가 쓰는 서비스 하나. ``build_client`` 가 이것을 핸들러에 묶는다.
SEARCH_SERVICE = SearchService()


# ===========================================================================
# 설정 읽기
# ===========================================================================
def load_token(env: "dict[str, str] | None" = None) -> str:
    """
    봇 토큰을 환경변수에서 읽는다.

    Raises:
        MissingTokenError: 환경변수가 없거나 공백뿐일 때. 🔴 예외 메시지에
            **값을 넣지 않는다.**
    """
    source = os.environ if env is None else env
    token = (source.get(TOKEN_ENV) or "").strip()
    if not token:
        raise MissingTokenError(
            f"{TOKEN_ENV} 환경변수가 없습니다. "
            f".env.example 를 참고해 설정하세요 "
            f"(토큰 값은 로그에 남기지 않습니다)."
        )
    return token


def load_dev_guild_id(env: "dict[str, str] | None" = None) -> "int | None":
    """
    개발용 서버 ID. **없으면 ``None``** 이고 그것은 오류가 아니다.

    있으면 그 서버에만 명령을 동기화한다 — 전역 동기화는 Discord 쪽에서
    반영이 느려서 개발 중 확인이 어렵다. 없으면 전역으로 동기화하고,
    그 사실을 로그에 적는다 (:func:`sync_commands`).

    Raises:
        InvalidGuildError: 값이 있는데 정수가 아닐 때. 조용히 무시하면
            "동기화했는데 안 보인다" 를 디버깅할 수 없다.
    """
    source = os.environ if env is None else env
    raw = (source.get(GUILD_ENV) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise InvalidGuildError(
            f"{GUILD_ENV} 는 서버 ID(정수)여야 합니다: {raw!r}"
        ) from error


def configure_logging(level: int = logging.INFO) -> None:
    """
    로그를 stderr 로 보낸다.

    이 저장소의 CLI 는 ``print`` + ``sys.stderr`` 를 쓰지만, 봇은 장시간
    돌며 라이브러리(``discord``)도 로그를 내므로 ``logging`` 을 쓴다 —
    두 쪽 출력이 한 흐름으로 섞여야 원인을 짚을 수 있다.
    """
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


# ===========================================================================
# Discord 어댑터
# ===========================================================================
def build_client(dev_guild_id: "int | None" = None, service=None):
    """
    클라이언트와 명령 트리를 만든다. **접속하지 않는다.**

    ``intents`` 는 기본값만 쓴다. 슬래시 명령은 메시지 내용을 읽지 않으므로
    ``message_content`` 특권 intent 가 **필요하지 않다** — 켜면 Discord
    쪽에서 승인이 필요해지고 얻는 것이 없다.

    ``service`` 를 주입할 수 있게 둔 이유: 테스트가 실제 3초짜리 카드
    데이터 빌드 없이 핸들러를 확인할 수 있어야 한다. 생략하면 모듈
    하나짜리 :data:`SEARCH_SERVICE` 를 쓴다.
    """
    import discord
    from discord import app_commands

    #: 🔴 이름을 ``search`` 로 두면 안 된다. 아래 ``@tree.command`` 가
    #: 데코레이트한 함수를 **같은 스코프에 같은 이름으로 다시 바인딩**해서
    #: 이 변수를 가린다 — 핸들러가 ``Command`` 객체에서 ``search_text`` 를
    #: 찾다가 ``AttributeError`` 로 죽는다. 작업 중 실제로 그렇게 깨졌다.
    search_service = service if service is not None else SEARCH_SERVICE
    #: ``/deck`` 도 **같은 서비스**를 쓴다. 카드 데이터를 두 번 만들지
    #: 않는다. 이름을 따로 두는 것은 핸들러가 읽히게 하기 위한 것뿐이다.
    deck_service = search_service
    combo_service = search_service

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.command(name="ping", description=PING_DESCRIPTION)
    async def ping(interaction: "discord.Interaction") -> None:
        #: 🔴 핸들러는 **받아서 넘기기만** 한다. 문구는 순수 함수가 만든다.
        await interaction.response.send_message(ping_message())

    @tree.command(name="search", description=SEARCH_DESCRIPTION)
    @app_commands.describe(query="예: 마법사족 몬스터 / 레벨 4 화염 속성")
    async def search_command(interaction: "discord.Interaction",
                             query: str) -> None:
        #: 🔴 **먼저 defer 한다.** Discord 는 첫 응답을 3초 안에 요구하는데
        #: 검색은 그보다 빠르지만(실측 1~99ms) 카드 데이터가 아직 준비되지
        #: 않았으면 그 자리에서 기다릴 수 있다. defer 없이는 상호작용이
        #: 만료된다.
        await interaction.response.defer()
        #: 🔴 **동기 검색을 이벤트 루프에서 돌리지 않는다.** 돌리면 그
        #: 시간 동안 봇 전체가 멈추고 ``/ping`` 도 응답하지 않는다.
        text = await asyncio.to_thread(search_service.search_text, query)
        await interaction.followup.send(text)

    @tree.command(name="deck", description=DECK_DESCRIPTION)
    @app_commands.describe(
        request="예: 오르페골 덱 짜줘 / 오르페골 + K9으로 덱을 짜 줘."
                " 초동 안정성을 우선하고 패트랩도 충분히")
    async def deck_command(interaction: "discord.Interaction",
                           request: str) -> None:
        #: 🔴 ``/search`` 와 같은 순서다. 덱 구성은 실측 0.11~0.22초지만
        #: 카드 데이터가 아직 준비되지 않았으면 그 자리에서 기다릴 수 있다.
        await interaction.response.defer()
        #: 동기 작업을 이벤트 루프에서 돌리지 않는다 — 돌리면 그 동안
        #: 봇 전체가 멈춘다.
        texts = await asyncio.to_thread(deck_service.deck_texts, request)
        #: 🔴 **첫 메시지는 ``followup.send``, 나머지도 같다.** 덱 출력은
        #: 한 메시지 상한을 넘으므로 나눠 보낸다 (:func:`paginate`).
        for text in texts:
            await interaction.followup.send(text)

    @tree.command(name="combo", description=COMBO_DESCRIPTION)
    @app_commands.describe(
        hand="초기 패 — 카드 이름이나 ID 를 쉼표로. 예: 오르페골 디베르,"
             " 오르페골 스켈레촌",
        board="(선택) 이미 필드·묘지에 있는 카드",
        deck="(선택) 덱 요청 — 주면 이 패가 덱에서 나올 수 있는지 함께 봅니다",
        recipe="(선택) 실제 덱 레시피 — 주면 엔진으로 실행 검증합니다."
               " 예: 욕망의 항아리 x3, 11091375 x37 / 또는 YDK",
        line="(선택) 검증용 전개 경로 이름 — 적어 둔 경로를 따라 실행합니다."
             " 예: orcust-girsu")
    async def combo_command(interaction: "discord.Interaction",
                            hand: str, board: str = "",
                            deck: str = "", recipe: str = "",
                            line: str = "") -> None:
        #: 🔴 ``/search`` · ``/deck`` 과 같은 순서다.
        await interaction.response.defer()
        texts = await asyncio.to_thread(
            combo_service.combo_texts, hand, board, deck, recipe, line)
        for text in texts:
            await interaction.followup.send(text)

    @client.event
    async def on_ready() -> None:
        user = client.user
        logger.info("%s 접속 완료: %s (id=%s)", BOT_NAME, user,
                    getattr(user, "id", "?"))
        #: 🔴 카드 데이터는 **여기서 한 번만** 만든다 (약 3초). 이벤트 루프를
        #: 막지 않도록 스레드로 보낸다 — 막으면 동기화와 하트비트가 멈춘다.
        if not await asyncio.to_thread(search_service.prepare):
            logger.error(
                "카드 데이터가 없어 /search 는 안내 문구만 돌려줍니다."
            )
        await sync_commands(tree, dev_guild_id)

    return client, tree


async def sync_commands(tree, dev_guild_id: "int | None") -> int:
    """
    명령을 Discord 에 동기화한다. 동기화된 명령 수를 돌려준다.

    개발용 서버 ID 가 있으면 **그 서버에만** 올린다 (반영이 즉시다).
    없으면 전역으로 올리고, 반영이 느릴 수 있다는 사실을 로그에 적는다 —
    "명령이 안 보인다" 의 가장 흔한 원인이 이것이다.
    """
    import discord

    if dev_guild_id is None:
        synced = await tree.sync()
        logger.info(
            "전역 동기화 완료: 명령 %d개. %s 가 없으면 전역 반영이라 "
            "Discord 클라이언트에 보이기까지 시간이 걸릴 수 있습니다.",
            len(synced), GUILD_ENV,
        )
        return len(synced)

    guild = discord.Object(id=dev_guild_id)
    tree.copy_global_to(guild=guild)
    synced = await tree.sync(guild=guild)
    logger.info("개발용 서버 동기화 완료: guild=%s 명령 %d개",
                dev_guild_id, len(synced))
    return len(synced)


def main(argv: "list[str] | None" = None) -> int:
    """
    봇을 띄운다.

    종료 코드: ``0`` 정상 종료 · ``2`` 설정 오류(토큰·서버 ID) ·
    ``1`` 접속 실패나 그 밖의 오류. 기존 CLI(``app/main.py``)가 설정 오류에
    ``2`` 를 쓰는 것과 같은 규칙이다.
    """
    configure_logging()

    try:
        token = load_token()
        dev_guild_id = load_dev_guild_id()
    except (MissingTokenError, InvalidGuildError) as error:
        #: 🔴 값을 찍지 않는다 — 예외 메시지에도 토큰이 없다.
        logger.error("%s", error)
        return 2

    try:
        import discord
    except ImportError:
        logger.error(
            "discord.py 가 없습니다. 설치: "
            "python3 -m pip install -r requirements-bot.txt"
        )
        return 2

    client, _tree = build_client(dev_guild_id, service=SEARCH_SERVICE)

    logger.info("%s 를 시작합니다 (개발용 서버: %s)", BOT_NAME,
                dev_guild_id if dev_guild_id is not None else "미설정(전역)")
    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        #: 🔴 토큰이 틀렸다는 사실만 적는다. 값은 적지 않는다.
        logger.error(
            "Discord 로그인 실패: %s 의 토큰이 거부되었습니다. "
            "Developer Portal 에서 토큰을 다시 확인하세요.", TOKEN_ENV,
        )
        return 1
    except KeyboardInterrupt:  # pragma: no cover - 사람이 끊는 경우
        logger.info("%s 를 종료합니다 (사용자 중단).", BOT_NAME)
        return 0
    except Exception:
        logger.exception("%s 가 예상치 못한 오류로 멈췄습니다.", BOT_NAME)
        return 1
    logger.info("%s 가 정상 종료했습니다.", BOT_NAME)
    return 0


# ===========================================================================
# 구현한 것과 구현하지 않은 것
# ===========================================================================
#: 등록된 명령은 **``/ping`` · ``/search`` · ``/deck`` · ``/combo`` 넷**이고
#: 그것이 지금 구현된 전부다. 아래는 **구현되어 있지 않다** — 지원하는
#: 것처럼 적지 않는다:
#:
#: * 🔴 **무작위 초기 패 생성.** ``deck/hand.py`` 의 구현은
#:   :class:`~deck.hand.FixedHand` 하나이고 사용자가 지정한 패를 그대로
#:   돌려준다. `/combo` 는 패를 **직접 받는다**.
#: * 🔴 **전개의 실행 검증.** :class:`~deck.planner.ComboPlanner` 는 엔진을
#:   실행하지 않는다 — ``EFFECT_LIBRARY`` 를 읽어 실행 구현이 등록된 카드
#:   ID 집합(실측 13장)을 만들고 걸음을 정적으로 만든다. 그래서
#:   :class:`ComboVerdict` 에 ``VERIFIED`` 가 없다.
#: * 🔴 **초동 확률 · 전개 성공률.** 무작위 패가 없으므로 계산할 표본이
#:   없다.
#: * 🔴 **특수 소환 · 융합 · 싱크로 · 엑시즈 · 링크 절차.** 엔진에 없고
#:   ``ComboPlan.unsupported`` 가 그 목록을 돌려준다.
#: * 🔴 **EDOPro 연동.** 이 파일에 그 코드가 없다.
#:
#: 네 명령이 공유하는 모양 (새 명령을 붙일 때 그대로 따르면 된다):
#:
#: * 순수 함수(:func:`search_message` · :func:`deck_messages` ·
#:   :func:`combo_messages`)가 문구를 만들고 핸들러는 넘기기만 한다
#: * 핸들러가 ``defer()`` 를 먼저 부르고 무거운 작업을 ``asyncio.to_thread``
#:   로 보낸다
#: * 무거운 초기화는 :class:`SearchService` 가 ``on_ready`` 에서 한 번만 한다
#: * 한 메시지에 들어가는 출력은 :func:`clamp_to_discord_limit`,
#:   들어가지 않는 출력은 :func:`paginate` 로 나눠 보낸다
#: * 서비스 메서드가 예외를 잡아 봇을 죽이지 않는다

if __name__ == "__main__":
    raise SystemExit(main())
