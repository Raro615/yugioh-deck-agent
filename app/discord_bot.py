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
from dataclasses import dataclass, field
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

#: 🔴 ``/combo`` 기본 응답의 최대 메시지 수 (Phase 6-AE).
#:
#: 6-AD 까지는 이 네 개를 다 쓰고도 모자라서 마지막 메시지에 *"길이 제한으로
#: 10줄을 보내지 못했습니다"* 가 붙었다 (실측: 사용자가 보낸 지정 패와
#: 검증용 레시피 · ``line:orcust-girsu`` → 4메시지 7,749자 + 10줄 누락.
#: 그 입력은 ``tests/test_combo_brief_and_detail.py`` 가 들고 있다 — 🔴 이
#: 모듈은 레시피를 **상수로 들고 있지 않는다**,
#: ``test_orcust_girsu_line::test_g03`` 이 그것을 고정한다).
#:
#: 🔴 **그래서 이 수를 늘리지 않았다.** 메시지를 늘리면 읽을 수 없는 응답이
#: 길어질 뿐이다 — 고친 것은 **요약을 짧게 만들고 전체 기록을 첨부로
#: 보내는** 쪽이다 (실측: 같은 입력이 1메시지 1,815자 + 첨부 14,715바이트).
COMBO_MESSAGE_LIMIT = DECK_MESSAGE_LIMIT

#: 첨부 하나의 최대 바이트. Discord 의 기본 업로드 상한은 바뀌어 왔으므로
#: (8 MiB → 25 MB → 10 MiB) **가장 좁았던 값**을 쓴다. 넘으면 버리지 않고
#: 나눈다 (:func:`combo_attachments`).
COMBO_ATTACHMENT_LIMIT = 8 * 1024 * 1024

#: 한 메시지에 붙일 수 있는 첨부 수. Discord 의 상한이 10이다.
COMBO_ATTACHMENT_COUNT_LIMIT = 10

#: 상세 기록 첨부의 **고정 파일명**. 🔴 사용자 입력으로 만들지 않는다 —
#: 패 · 레시피 문자열이 파일명이나 경로가 되면 그 자체가 주입 경로다.
COMBO_DETAIL_FILENAME = "combo-detail.txt"

#: 전개 기록 첨부의 **고정 파일명** (Phase 6-AR). 같은 이유로 사용자 입력이
#: 들어가지 않는다.
COMBO_REPLAY_FILENAME = "combo-replay.json"

#: 🔴 **외부 재생 링크가 없다는 사실을 적는 줄** (Phase 6-AR).
#:
#: 왜 링크를 내지 않는가: 대상 사이트(Duel Simulator)는 덱 **이미지**를
#: 올려 사람이 손으로 盤面을 만들고, 그 조작을 기록해 공유 URL 을 발행하는
#: 도구다. 외부 전개 기록을 가져오는 기능 · 공개 API · 가져오기 형식이
#: 화면 · 매뉴얼 · 이용 가이드라인 · 이용 규약 어디에도 **없다**. 그래서
#: 이 저장소가 만들 수 있는 재생 링크가 없다 (조사: ``docs/
#: duel-simulator-replay-integration.md``).
#:
#: 🔴 **사이트 첫 화면 링크를 "이 전개의 재생 링크" 로 적지 않는다** — 그
#: 링크는 이 전개를 열지 못한다.
#:
#: 🔴 **엔진 실행 실패와 구분한다.** 이 줄은 외부 연동이 없다는 말뿐이고,
#: 실행 결과와 상세 기록은 위와 첨부에 그대로 있다.
COMBO_REPLAY_VIEW_UNAVAILABLE = (
    "🎞 **전개 보기: 아직 없습니다** — 외부 시뮬레이터에 이 전개의 재생"
    " 링크를 만드는 연동이 없습니다 (가져오기 기능 · 공개 API 가 없습니다)."
    " 🔴 **엔진 실행은 정상입니다** — 위 요약과 아래 첨부가 그 기록입니다."
)

#: 🔴 전개 기록을 만들지 못했을 때. 실행 결과를 지우지 않는다.
COMBO_REPLAY_FAILED_NOTICE = (
    "🔴 **전개 기록 파일을 만들지 못했습니다** — 실행 결과와 상세 기록은"
    " 그대로입니다 (외부 연동용 기록만 빠졌습니다)."
)

#: 🔴 상세 기록조차 다 담지 못한 응답에는 전개 기록을 **더 붙이지 않는다.**
#:
#: 전송 상한이 이미 모자란 자리다. 거기에 JSON 한 덩어리를 더하면 상세
#: 기록이 더 밀려나고, **먼저 지켜야 하는 것은 실행 결과를 확인할 수 있게
#: 두는 쪽**이다. 조용히 빼지 않고 그 사실을 적는다.
COMBO_REPLAY_SKIPPED_NOTICE = (
    "🧾 **전개 기록은 이번 응답에 붙이지 않았습니다** — 상세 기록도 일부만"
    " 담았기 때문입니다 (전송 상한). 실행 결과는 위 요약과 첨부에 있습니다."
)


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
             max_messages: int = DECK_MESSAGE_LIMIT,
             overflow_notice: "str | None" = None) -> "list[str]":
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

    ``overflow_notice`` (Phase 6-AE) 를 주면 그 문장을 **함께** 적는다 —
    "어디서 전체를 볼 수 있는가" 를 가리키는 자리다 (``/combo`` 는 상세
    기록 첨부를 가리킨다). 🔴 **몇 줄이 빠졌는지는 그대로 적는다** — 가리킬
    곳이 있다는 사실이 누락을 지우지 않는다.
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
                if overflow_notice:
                    notice += f" {overflow_notice}"
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


@dataclass(frozen=True, slots=True)
class OpeningReport:
    """
    ``/combo`` 의 **실제 엔진 실행 한 번**에 대한 보고 조각들 (Phase 6-AE).

    🔴 **판정을 들고 오지 않는다 — 이미 난 판정을 옮긴다.** ``refused`` 는
    실행 절이 직접 말하는 값이고 (``not setup.can_run``), 부르는 쪽은 그것을
    다시 계산하지 않는다. 두 번 판정하면 두 답이 갈라질 수 있고, 그것이 이
    저장소가 반복해서 고쳐 온 모양이다 (STRUCTURAL-134).

    ``brief`` 와 ``detail`` 은 **같은 실행 기록**에서 나온 두 표현이다 —
    엔진을 두 번 돌리지 않는다. ``ran`` 이 거짓이면 실행 자체가 없었다
    (레시피 없음 · 레시피를 읽지 못함).
    """

    brief: tuple[str, ...] = ()
    """기본 응답에 넣을 줄들. 짧다."""
    detail: tuple[str, ...] = ()
    """첨부에 넣을 줄들. **전체 기록**이다 — CLI 가 보는 것과 같다."""
    refused: bool = False
    """🔴 **이번 요청의 입력이 규칙 검증에 걸렸는가.**"""
    ran: bool = False
    """엔진을 실제로 돌렸는가 (레시피가 있었고 읽혔는가)."""
    replay: "dict | None" = None
    """
    🔴 **시각 재현용 전개 기록** (Phase 6-AR, ``deck.replay_export``).

    같은 실행에서 나온 **세 번째 표현**이다 (요약 · 상세 · 기록). 엔진을
    다시 돌리지 않으며, 만들지 못하면 ``None`` 이고 그때도 요약과 상세는
    그대로다 — 외부 연동용 기록이 없는 것과 실행이 실패한 것은 다른
    사실이다.
    """


def _run_opening(agent, recipe_text: str,
                 hand_ids: "list[int]",
                 line_text: str = "") -> OpeningReport:
    """
    🔴 **실제 엔진 실행 절** (Phase 6-T · 6-AE). 레시피가 없으면 빈 목록이
    아니라 **무엇이 부족한지** 적는다 (§5 · §15).

    돌려주는 것은 :class:`OpeningReport` 다 (6-AE). 그 안의 ``refused`` 가
    참이면 **이번 요청의 입력이 규칙에 어긋났다**는 뜻이고, 그때 부르는 쪽은
    정적 전개 추천을 **내지 않는다** — 거절한 입력에 대해 "이렇게 전개하면
    된다" 를 보여 주면 사용자는 자기 입력이 통과한 줄로 읽는다 (사용자 실험
    ③ 이 그것을 잡았다).

    🔴 **엔진을 한 번만 돌린다.** ``brief`` 와 ``detail`` 은 그 한 번의
    기록에서 만든 두 표현이고, 표시를 위해 다시 실행하거나 상태를 건드리지
    않는다 (6-AE §5).

    ``deck:`` 초안을 실제 덱으로 쓰지 않는 이유가 여기에 적혀 있어야 한다 —
    출력에 없으면 사용자는 초안으로 검증했다고 믿는다.
    """
    from app.main import opening_wiring
    from deck.combo_policy import COMBO_LINES, line_named, line_progress
    from deck.opening import build_opening, execute_opening, opening_hand_size
    from deck.recipe import parse_recipe
    from deck.replay_export import export_opening_replay
    from deck.report import (
        render_opening_board,
        render_opening_brief,
        render_opening_headline,
        render_opening_run,
        render_opening_setup,
    )

    expected = opening_hand_size()
    if not recipe_text or not recipe_text.strip():
        said = (
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
        )
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    parsed = parse_recipe(recipe_text, agent.repository)
    head = ["**[실제 엔진 실행]**"]
    if parsed.unresolved:
        names = ", ".join(f"`{t}`" for t in parsed.unresolved[:10])
        head.append(f"⚠️ 레시피에서 카드를 찾지 못했습니다: {names}"
                    " — **덱에 넣지 않았습니다.**")
    notes = [f"  {note}" for note in parsed.notes]
    if parsed.draft is None:
        head.append("🔴 레시피에서 카드를 하나도 읽지 못해 **실행하지"
                    " 않았습니다.**")
        #: 레시피를 읽지 못한 것은 **입력 거절이 아니다** — 규칙 위반을
        #: 판정한 것이 아니라 글자를 못 읽은 것이므로, 정적 계획은 그대로
        #: 보여 준다 (그쪽은 레시피를 쓰지 않는다).
        return OpeningReport(brief=tuple(head), detail=tuple(head + notes),
                             refused=False, ran=False)

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
        head.append(
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
    progress = line_progress(run, line) if line is not None else None

    #: 🔴 **요약은 공용 보고 함수가 만든다** (6-AE). Discord 가 제 손으로
    #: 문장을 만들면 CLI 와 다른 답이 나오고, 어느 쪽이 맞는지 알 수 없다.
    #: 🔴 **기본 응답은 한눈 요약뿐이다** (Phase 6-AR). 6-AE 의 긴 요약
    #: (``render_opening_brief``) 은 **지우지 않고 첨부의 첫 절로** 내렸다 —
    #: 거기 적힌 미지원 사유 · 멈춘 이유 · 검증 한계는 한 줄도 사라지지
    #: 않는다. 요약은 그 가운데 **지우면 뜻이 달라지는 것**만 남긴다.
    brief = list(head)
    brief.extend(render_opening_headline(
        setup, run, agent.repository, line=line, progress=progress
    ).splitlines())
    #: 🔴 **상세는 기존 전체 기록 그대로다** — CLI 가 보는 것과 같은 세 함수
    #: 이고, 한 줄도 줄이지 않는다 (6-AE §3).
    detail = list(head) + notes
    if not setup.can_run:
        detail.append("🔴 **실행하지 않았습니다** — 입력 검증을 통과하지"
                      " 못했습니다 (아래 참조).")
    detail.extend(render_opening_brief(
        setup, run, agent.repository, line=line, progress=progress
    ).splitlines())
    detail.extend(render_opening_setup(setup).splitlines())
    detail.extend(render_opening_run(run).splitlines())
    detail.extend(render_opening_board(setup, agent.repository).splitlines())
    #: 🔴 **전개 기록은 같은 실행에서 나온 세 번째 표현이다** (6-AR).
    #: 만들지 못해도 위의 둘은 그대로 간다 — 외부 연동용 기록이 없는 것과
    #: 실행이 실패한 것은 다른 사실이다.
    replay = None
    if setup.can_run:
        try:
            replay = export_opening_replay(
                setup, run, agent.repository, line=line, progress=progress
            )
        except Exception:  # pragma: no cover - 방어용
            replay = None
    return OpeningReport(brief=tuple(brief), detail=tuple(detail),
                         refused=not setup.can_run, ran=True, replay=replay)


def _run_bounded_search(agent, recipe_text: str, hand_ids: "list[int]",
                        search_text: str,
                        results_text: str = "",
                        followups_text: str = "") -> "OpeningReport | None":
    """
    ``/combo search:…`` — **제한 전개 탐색** (Phase 6-AH).

    ``search_text`` 가 비어 있으면 ``None`` 이다 — 사용자가 고르지 않은
    탐색을 조용히 돌리지 않는다. 그래서 ``search:`` 를 주지 않은 요청의
    동작은 6-AG 와 **한 글자도 다르지 않다**.

    🔴 **핵심 탐색은 이 파일에 없다.** 목표 이름을 카드 ID 로 바꾸는 표와
    세 계층을 잇는 자리는 ``app.main`` 하나이고 (``bounded_search_opening``),
    탐색 자체는 ``agent.bounded_search`` 다 — 이 어댑터는 ``agent`` ·
    ``integration`` 을 직접 import 하지 않는다
    (``tests/test_discord_bot.py::test_15``).

    🔴 **요약도 상세도 공용 보고 함수가 만든다** (``deck.report``) — CLI 와
    같은 문장이어야 어느 쪽이 맞는지 묻지 않게 된다.

    ``results_text`` (Phase 6-AI) 를 주면 **복수 결과 모드**로 돈다 —
    🔴 **주지 않으면 6-AH 의 단일 결과 모드 그대로다.** 사용자가 고르지
    않은 모드로 조용히 바꾸지 않는다.
    """
    from app.main import (
        bounded_search_many_opening, bounded_search_opening,
        rank_search_results, search_followup_count, search_goal_card_id,
        search_result_count,
    )
    from deck.recipe import parse_recipe
    from deck.report import (
        render_bounded_search, render_bounded_search_brief,
        render_multi_search, render_multi_search_brief,
    )

    if not search_text or not search_text.strip():
        return None

    head = ["**[제한 전개 탐색]**"]
    card_id = search_goal_card_id(search_text)
    if card_id is None:
        from app.main import SEARCH_GOALS

        names = " · ".join(f"`{name}`" for name in sorted(SEARCH_GOALS))
        said = tuple(head + [
            f"🔴 **하지 않았습니다** — `search:{search_text}` 라는 목표가"
            f" 없습니다. 있는 목표: {names}",
            "🔴 비슷한 목표를 골라 주지 않습니다 — 사용자가 고르지 않은"
            " 목표로 찾은 경로를 보여 주면 그것이 자기 목표인 줄로"
            " 읽힙니다.",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    if not recipe_text or not recipe_text.strip():
        said = tuple(head + [
            "🔴 **하지 않았습니다** — 실제 덱 레시피가 없습니다.",
            "탐색은 실제 `GameState` 에서 목표를 판정하므로 남은 덱의"
            " 장수와 카드가 필요합니다 (`recipe:` 로 넘겨 주세요).",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    extra, why_extra = search_followup_count(followups_text)
    if extra is None:
        said = tuple(head + [
            f"🔴 **탐색하지 않았습니다** — `followups:{followups_text}` 를"
            f" 후속 행동 수로 읽지 못했습니다. {why_extra}",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)
    wanted, why = search_result_count(results_text)
    if wanted is None:
        said = tuple(head + [
            f"🔴 **탐색하지 않았습니다** — `results:{results_text}` 를 결과"
            f" 수로 읽지 못했습니다. {why}",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    parsed = parse_recipe(recipe_text, agent.repository)
    if parsed.draft is None:
        said = tuple(head + [
            "🔴 레시피에서 카드를 하나도 읽지 못해 **탐색하지"
            " 않았습니다.**",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    if extra and wanted <= 1:
        #: 🔴 **조용히 켜 주지 않는다** — 후속 모드는 복수 결과 탐색의
        #: 모드이고, 무엇을 더 주어야 하는지 적는다.
        said = tuple(head + [
            "🔴 **탐색하지 않았습니다** — `followups:` 는 `results:` 2 이상과"
            " 함께 주십시오 (후속 모드는 복수 결과 탐색의 모드입니다).",
        ])
        return OpeningReport(brief=said, detail=said, refused=False, ran=False)

    if wanted > 1:
        #: 🔴 **복수 결과 모드.** 같은 ``app.main`` 자리를 지나고, 같은
        #: 탐색기를 쓴다 — 예산의 ``max_results`` 만 다르다.
        setup, many = bounded_search_many_opening(
            agent.repository, parsed.draft, hand_ids,
            card_id=card_id, max_results=wanted, followups=extra,
        )
        if many is None:
            said = tuple(head + [
                "🔴 **탐색하지 않았습니다** — 입력 검증을 통과하지"
                " 못했습니다 (위 `[실제 엔진 실행]` 절에 이유가"
                " 있습니다).",
            ])
            return OpeningReport(brief=said, detail=said,
                                 refused=not setup.can_run, ran=False)
        #: 🔴 **CLI 와 같은 자리를 쓴다** (``rank_search_results``) — 두
        #: 어댑터가 각자 평가하면 같은 입력에 다른 추천이 나온다. 어댑터는
        #: ``agent`` 를 직접 import 하지 않는다 (``test_15`` 의 경계).
        ranking = rank_search_results(many)
        brief = list(head)
        brief.extend(
            render_multi_search_brief(
                many, agent.repository, ranking
            ).splitlines()
        )
        detail = list(head)
        detail.extend(
            render_multi_search(
                many, agent.repository, setup, ranking
            ).splitlines()
        )
        return OpeningReport(brief=tuple(brief), detail=tuple(detail),
                             refused=False, ran=True)

    setup, outcome, rerun = bounded_search_opening(
        agent.repository, parsed.draft, hand_ids, card_id=card_id
    )
    if outcome is None:
        said = tuple(head + [
            "🔴 **탐색하지 않았습니다** — 입력 검증을 통과하지 못했습니다"
            " (위 `[실제 엔진 실행]` 절에 이유가 있습니다).",
        ])
        return OpeningReport(brief=said, detail=said,
                             refused=not setup.can_run, ran=False)

    brief = list(head)
    brief.extend(render_bounded_search_brief(outcome, rerun).splitlines())
    detail = list(head)
    detail.extend(
        render_bounded_search(outcome, rerun, setup).splitlines()
    )
    return OpeningReport(brief=tuple(brief), detail=tuple(detail),
                         refused=False, ran=True)


@dataclass(frozen=True, slots=True)
class ComboAttachment:
    """
    기본 응답과 함께 보내는 **상세 기록 파일 하나** (Phase 6-AE).

    🔴 **discord 를 모른다.** 이름과 UTF-8 바이트만 들고 있고, 그것을
    ``discord.File`` 로 바꾸는 일은 :func:`build_client` 안에서만 한다 —
    이 모듈의 순수 함수들은 라이브러리 없이 테스트된다 (모듈 설명).

    🔴 **파일명은 고정값에서 만든다.** 사용자 입력(패 · 레시피 · 경로
    이름)이 파일명이나 경로에 들어가지 않는다.

    🔴 **디스크를 쓰지 않는다.** 바이트를 들고 있고, 보내는 쪽이 메모리
    버퍼로 감싼다 — 임시 파일을 남기지 않는다.
    """

    filename: str
    text: str

    @property
    def data(self) -> bytes:
        return self.text.encode("utf-8")

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class ComboResponse:
    """
    ``/combo`` 한 번의 응답 — **기본 메시지들과 첨부들** (Phase 6-AE).

    🔴 **둘을 가르는 이유가 측정에서 나왔다.** 6-AD 까지 이 명령은 전체
    기록을 메시지로만 보냈고, 실측으로 네 메시지를 다 쓰고도 **10줄이
    잘렸다** (``COMBO_MESSAGE_LIMIT`` 의 설명). 메시지를 늘리는 쪽으로
    풀면 읽을 수 없는 응답이 길어질 뿐이므로, 요약을 짧게 만들고 **전체를
    첨부로** 보낸다.

    🔴 **첨부가 요약의 사본이 아니다.** 요약에서 상한 때문에 뺀 줄은 전부
    첨부에 있고, 요약은 몇 줄을 뺐는지 적는다.
    """

    messages: tuple[str, ...] = ()
    attachments: tuple[ComboAttachment, ...] = ()
    detail_notice: str = ""
    """
    🔴 **파일 안에 넣을 수 없었던 전달 상태 안내** (Phase 6-AE 보완).

    :attr:`ComboDetail.notice` 를 그대로 들고 온다. **이미
    :attr:`messages` 안에 적혀 있다** — 보내는 쪽이 다시 보내면 같은 말이
    두 번 간다. 이 칸은 "전달 상태가 이랬다" 를 **검사할 수 있게** 두는
    자리다 (상한 안에 들어간다는 보장은 ``paginate`` 가 한다).
    """

    detail_omitted: int = 0
    """담지 못한 줄 수 (:attr:`ComboDetail.omitted_lines`)."""

    @property
    def complete_detail(self) -> bool:
        """🔴 **상세 기록을 전부 첨부했는가.** 거짓이면 일부만 갔다."""
        return not self.detail_omitted

    @property
    def missing(self) -> bool:
        """🔴 **내용이 조용히 사라졌는가.** 참이면 전달 실패로 다뤄야 한다."""
        return not self.messages


@dataclass(frozen=True, slots=True)
class ComboDetail:
    """
    상세 기록을 **첨부로 나눈 결과**와 그 전달 상태 (Phase 6-AE 보완).

    🔴 **왜 튜플 하나로는 안 되는가.** 외부 검토가 찾은 오류 A 가 그 자리다 —
    상한 때문에 **일부를 담지 못할 수 있는데** 부르는 쪽이 그것을 알 길이
    없었고, 그래서 기본 메시지가 "전체 기록은 첨부에 있습니다" 로 적혔다.
    담은 것과 **담지 못한 것**을 함께 돌려준다.
    """

    attachments: tuple[ComboAttachment, ...] = ()
    omitted_lines: int = 0
    """담지 못한 줄 수. 0 이면 전부 담았다."""
    notice: str = ""
    """
    🔴 **파일 안에 넣을 수 없었던 전달 상태 안내.**

    상한이 너무 작아 안내문이 마지막 첨부에 들어가지 못하면 (그러면 그
    첨부가 상한을 넘는다) 그 문장을 여기로 내보낸다 — 부르는 쪽이 **기본
    메시지에** 적는다. 조용히 누락하지 않는다.

    파일 안에 적었으면 비어 있다 (같은 말을 두 번 하지 않는다).
    """

    @property
    def complete(self) -> bool:
        """전체 기록을 담았는가."""
        return self.omitted_lines == 0


def _positive_int(name: str, value) -> int:
    """
    🔴 **쓸 수 없는 상한을 조용히 고치지 않는다** (Phase 6-AE 보완).

    ``bool`` 을 거절하는 이유: ``True`` 는 ``1`` 로 통과해 "첨부 한 개" 가
    되는데, 그것을 적은 사람은 켜고 끄는 값을 넘긴 것이다.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 은 정수여야 합니다: {value!r}")
    if value < 1:
        raise ValueError(f"{name} 은 1 이상이어야 합니다: {value!r}")
    return value


def _detail_pieces(lines: "list[str]",
                   limit: int) -> "tuple[list[tuple[int, str]], set[int]]":
    """
    줄들을 **상한을 넘지 않는 조각들**로 자른다 (Phase 6-AE 보완).

    조각마다 **어느 줄에서 왔는지**를 함께 들고 온다 — 그래야 "몇 줄을 담지
    못했는가" 를 셀 수 있다.

    🔴 **글자 중간에서 끊지 않는다.** 바이트가 아니라 글자를 더해 가며 재므로
    UTF-8 이 깨질 수 없다. 한 글자가 그 자체로 상한을 넘으면 (아주 작은
    상한) 담을 수 없으므로 **그 줄을 손실로 적는다** — 조용히 버리지 않는다.
    """
    pieces: list[tuple[int, str]] = []
    lossy: set[int] = set()
    for index, line in enumerate(lines):
        if len(line.encode("utf-8")) <= limit:
            pieces.append((index, line))
            continue
        buffer = ""
        for char in line:
            if len(char.encode("utf-8")) > limit:
                #: 🔴 이 글자는 어떤 첨부에도 들어갈 수 없다.
                lossy.add(index)
                continue
            if len((buffer + char).encode("utf-8")) > limit:
                pieces.append((index, buffer))
                buffer = char
            else:
                buffer += char
        if buffer:
            pieces.append((index, buffer))
        elif index not in lossy:
            #: 빈 조각을 만들지 않는다 — 담을 글자가 없었다.
            lossy.add(index)
    return pieces, lossy


def _pack_pieces(pieces: "list[tuple[int, str]]", limit: int,
                 count_limit: int, reserve: int = 0,
                 ) -> "tuple[list[list[str]], int]":
    """
    조각들을 **첨부 칸에** 채운다. ``(칸들, 쓴 조각 수)`` 를 돌려준다.

    ``reserve`` 는 **마지막 칸에만** 비워 두는 바이트다 — 그 자리에 누락
    안내가 들어간다 (Phase 6-AE 보완). 🔴 비워 둘 자리가 내용보다 커서 한
    조각도 못 넣게 되면 그 칸을 **만들지 않는다** (빈 첨부를 만들지 않는다).
    """
    chunks: list[list[str]] = []
    used = 0
    while used < len(pieces) and len(chunks) < count_limit:
        capacity = limit - reserve if len(chunks) == count_limit - 1 else limit
        if capacity <= 0:
            break
        current: list[str] = []
        size = 0
        while used < len(pieces):
            piece = pieces[used][1]
            need = len(piece.encode("utf-8")) + (1 if current else 0)
            if size + need > capacity:
                break
            current.append(piece)
            size += need
            used += 1
        if not current:
            break
        chunks.append(current)
    return chunks, used


def _omitted_notice(count: int, limit: int, count_limit: int) -> str:
    """담지 못한 줄이 있다는 **한 문장**. 🔴 수와 상한을 함께 적는다."""
    return (f"🔴 상세 기록 {count}줄을 첨부 상한 ({count_limit}개 · 각"
            f" {limit}바이트) 때문에 담지 못했습니다 — CLI 의"
            f" `python3 -m app.main combo … --recipe …` 로 전체를 볼 수"
            f" 있습니다.")


def combo_attachments(text: str,
                      filename: str = COMBO_DETAIL_FILENAME,
                      limit: int = COMBO_ATTACHMENT_LIMIT,
                      count_limit: int = COMBO_ATTACHMENT_COUNT_LIMIT,
                      ) -> ComboDetail:
    """
    상세 기록을 **상한을 넘지 않는 첨부 여러 개**로 나눈다 (Phase 6-AE).

    🔴 **버리지 않는다.** 줄 단위로 나누고, 한 줄이 그 자체로 상한을 넘으면
    그 줄만 **글자 단위로** 쪼갠다 (바이트로 자르면 UTF-8 이 깨진다).

    🔴 **상한을 다시 본다** (6-AE 보완 — 외부 검토 A). 전에는 ``count_limit``
    에 닿으면 마지막 첨부에 안내문을 **덧붙이기만** 하고 크기를 다시 세지
    않았다. 실측: ``limit=100`` · ``count_limit=1`` 에서 마지막 파일이
    **277바이트**였다. 지금은 안내문이 들어갈 자리를 **미리 비워 두고**
    채우므로, 안내문 · 구분자 · 줄바꿈까지 포함한 최종 크기가 상한 안이다.

    🔴 **비워 둘 크기는 추정하지 않는다.** 안내문의 길이는 "담지 못한 줄 수"
    에 따라 달라지는데, 그 수는 채워 본 뒤에야 안다. 그래서 **전체 줄 수**
    (담지 못한 수의 상한) 로 안내문을 만들어 그 길이를 비워 둔다 — 실제
    안내문은 그보다 짧거나 같으므로 상한을 넘을 수 없다.

    안내문이 그 자리에도 들어가지 못하는 작은 상한에서는 파일 **밖**으로
    내보낸다 (:attr:`ComboDetail.notice`) — 부르는 쪽이 기본 메시지에
    적는다. 상한을 어기지도, 조용히 누락하지도 않는다.
    """
    _positive_int("limit", limit)
    _positive_int("count_limit", count_limit)

    lines = text.splitlines()
    if not lines:
        #: 🔴 담을 것이 없으면 **빈 첨부를 만들지 않는다.** 그리고 그것은
        #: 누락이 아니다 — 기록 자체가 비어 있었다.
        return ComboDetail()

    pieces, lossy = _detail_pieces(lines, limit)
    chunks, used = _pack_pieces(pieces, limit, count_limit)

    def _kept(upto: int) -> int:
        """앞 ``upto`` 조각으로 **온전히** 담긴 줄 수."""
        done = {index for index, _ in pieces[:upto]}
        left = {index for index, _ in pieces[upto:]}
        return len(done - left - lossy)

    omitted = len(lines) - _kept(used)
    notice = ""
    if omitted:
        #: 🔴 전체 줄 수로 안내문을 만들어 **그 길이를 비워 둔다.**
        budget = len(
            _omitted_notice(len(lines), limit, count_limit).encode("utf-8")
        ) + 1
        spared, spared_used = _pack_pieces(
            pieces, limit, count_limit, reserve=budget
        )
        #: 🔴 **안내가 붙을 파일의 최종 크기를 본다** (6-AE 보완2).
        #:
        #: 비워 두기는 **마지막 칸에만** 걸린다. 그 칸에 한 조각도 들어가지
        #: 못하면 :func:`_pack_pieces` 는 그 칸을 만들지 않고, 그러면 남는
        #: 것은 **비워 두지 않은 앞의 꽉 찬 칸**이다 — 전에는 "칸이 있다"
        #: 는 이유만으로 거기에 안내를 붙였고, 그래서 상한을 넘었다.
        #: 실측: ``limit=1000`` · ``count_limit=2`` · 999자 세 줄 →
        #: **1,194바이트** (방어선이 그것을 잡아 ``AssertionError``).
        #:
        #: 그래서 붙일 파일의 크기를 **직접 세어** 들어가는지 확인한다.
        inside: "tuple[list[list[str]], int, int, str] | None" = None
        if len(spared) == count_limit and spared[-1]:
            said = _omitted_notice(
                len(lines) - _kept(spared_used), limit, count_limit
            )
            body = "\n".join(spared[-1] + [said])
            if len(body.encode("utf-8")) <= limit:
                inside = (spared, spared_used,
                          len(lines) - _kept(spared_used), said)
        if inside is not None:
            spared, spared_used, omitted, said = inside
            chunks = [list(chunk) for chunk in spared]
            chunks[-1] = chunks[-1] + [said]
            used = spared_used
        else:
            #: 🔴 **파일 안에 넣을 수 없다 — 파일 밖으로 내보낸다.**
            #:
            #: 그리고 **비워 두지 않은 채움을 그대로 쓴다** (위 ``chunks`` ·
            #: ``used``). 비워 두기는 자리를 만들지 못했으니 그 때문에
            #: 내용을 더 잃을 이유가 없다.
            notice = _omitted_notice(omitted, limit, count_limit)

    stem, _, suffix = filename.rpartition(".")
    stem = stem or filename
    suffix = suffix or "txt"
    made = tuple(
        ComboAttachment(
            filename if len(chunks) == 1 else f"{stem}-{index}.{suffix}",
            "\n".join(chunk),
        )
        for index, chunk in enumerate(chunks, start=1)
    )
    #: 🔴 **만든 것을 다시 센다.** 이 단정이 오류 A 를 다시 들여보내지
    #: 않는다 — 계산이 어디서 틀려도 여기서 멈춘다.
    for item in made:
        if item.size > limit:  # pragma: no cover - 방어선
            raise AssertionError(
                f"첨부 {item.filename} 가 상한을 넘었습니다:"
                f" {item.size} > {limit}"
            )
    if len(made) > count_limit:  # pragma: no cover - 방어선
        raise AssertionError(f"첨부 {len(made)}개 > 상한 {count_limit}개")
    return ComboDetail(attachments=made, omitted_lines=omitted, notice=notice)


def _detail_pointer_lines(detail: ComboDetail,
                          with_plan: bool = True) -> "list[str]":
    """
    기본 메시지가 **첨부를 가리키는 줄** (Phase 6-AE 보완 — 외부 검토 A).

    🔴 **실제로 일부가 빠졌는데 "전체가 첨부에 있다" 고 쓰지 않는다.** 전에는
    이 줄이 언제나 "전체 기록은 첨부에 있습니다" 였고, 상한 때문에 잘렸는지는
    부르는 쪽이 알 수 없었다. 지금은 :class:`ComboDetail` 이 들고 온 전달
    상태를 그대로 읽는다.

    🔴 **파일에 없는 것을 적지 않는다.** ``with_plan`` 이 거짓이면 그 첨부에
    정적 계획이 **들어 있지 않다** — 입력을 거절한 응답이 그렇다 (6-AA 의
    계약: 거절한 입력에는 전개를 추천하지 않는다). 그때 "정적 계획" 이라는
    낱말을 적으면 그 계약이 글자로 깨진다 (``test_01`` 이 그것을 잡았다).
    """
    inside = ("걸음마다의 판정 · 해결 결과 · 미지원 사유 · 모든 검증 한계"
              + (" · 정적 계획" if with_plan else ""))
    if not detail.attachments:
        if detail.notice:
            #: 🔴 한 줄도 담지 못했다 — 그 사실을 적는다.
            return [f"📎 **상세 기록을 첨부하지 못했습니다.** {detail.notice}"]
        return []
    if detail.complete:
        return [f"📎 **전체 기록은 첨부 `{detail.attachments[0].filename}`**"
                f" 에 있습니다 ({inside})."]
    said = [
        f"📎 🔴 **상세 기록의 일부만 첨부했습니다** —"
        f" {detail.omitted_lines}줄을 담지 못했습니다"
        f" (첨부 {len(detail.attachments)}개)."
    ]
    if detail.notice:
        #: 🔴 파일 안에 넣을 수 없었던 안내를 **여기에** 적는다 — 그래야
        #: 조용한 누락이 되지 않는다 (``ComboDetail.notice`` 의 설명).
        said.append(detail.notice)
    else:
        said.append("  전체 기록은 CLI 의"
                    " `python3 -m app.main combo … --recipe …` 로 볼 수"
                    " 있습니다 (첨부 마지막 줄에도 적었습니다).")
    return said


def replay_attachment(record) -> "ComboAttachment | None":
    """
    **전개 기록 첨부 하나** (Phase 6-AR). 없거나 상한을 넘으면 ``None``.

    🔴 **나누지 않는다.** 상세 기록(텍스트)은 줄 단위로 나눌 수 있지만 이
    파일은 JSON 한 덩어리라서, 반으로 자르면 **읽을 수 없는 조각**이 된다.
    상한을 넘으면 붙이지 않고 그 사실을 적는다 (조용히 자르지 않는다).
    """
    if not record:
        return None
    from deck.replay_export import replay_json

    item = ComboAttachment(filename=COMBO_REPLAY_FILENAME,
                           text=replay_json(record))
    if item.size > COMBO_ATTACHMENT_LIMIT:
        return None
    return item


def _overflow_notice(detail: ComboDetail) -> str:
    """
    :func:`paginate` 가 메시지를 끊을 때 **어디서 전체를 볼 수 있는가**.

    🔴 첨부가 완전하지 않으면 "첨부에 전부 있다" 고 적지 않는다.
    """
    if detail.attachments and detail.complete:
        return f"빠진 줄은 첨부 `{detail.attachments[0].filename}` 에 전부 있습니다."
    return ("빠진 줄은 CLI 의 `python3 -m app.main combo … --recipe …` 로"
            " 볼 수 있습니다 (첨부도 일부만 담았습니다).")


def combo_response(agent, hand_text: str, board_text: str = "",
                   deck_text: str = "", recipe_text: str = "",
                   line_text: str = "", search_text: str = "",
                   results_text: str = "",
                   followups_text: str = "") -> ComboResponse:
    """
    ``/combo`` 의 응답. **discord 를 모른다.** 메시지들과 첨부들을 돌려준다.

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

    출력의 모양 (Phase 6-AE)
    -------------------------
    * **실제 실행이 있으면** 기본 응답은 요약뿐이고, 정적 계획은 한 줄짜리
      안내로 줄인다 — 실제 실행 뒤에 길게 붙이면 "실행 이후의 추가 행동"
      으로 읽힌다 (§3).
    * **실제 실행이 없으면** 그 사실을 먼저 적고, 정적 계획을 **"실행하지
      않은 참고 계획"** 으로 한 줄씩 적는다. 실행 걸음 수나 성공 표시를
      만들지 않는다.
    * 전체 기록은 언제나 첨부로 간다 (실행 기록 + 정적 계획을 **분리된
      절**로).
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
        return ComboResponse(messages=tuple(paginate(
            lines, max_messages=COMBO_MESSAGE_LIMIT)))

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
    executed = _run_opening(agent, recipe_text, hand_ids, line_text)
    #: 🔴 **주지 않으면 돌리지 않는다** (Phase 6-AH). ``search:`` 가 없는
    #: 요청의 동작은 6-AG 와 한 글자도 다르지 않다.
    searched = _run_bounded_search(agent, recipe_text, hand_ids, search_text,
                                   results_text, followups_text)

    #: 🔴 **입력이 거절되면 정적 전개 추천을 내지 않는다** (Phase 6-AA —
    #: 사용자 실험 ③). 실측으로, 「기르수: 패 4장 > 덱 3장」으로 거절한
    #: 요청에 대해 아래 정적 계획이 기르수 소환과 효과를 나열하고 "확정" ·
    #: "엔진이 허가함" 으로 적었다. 그 두 문장이 한 응답 안에 같이 있으면
    #: 사용자는 입력이 통과한 줄로 읽는다.
    if executed.refused:
        lines.append("")
        lines.extend(executed.brief)
        if searched is not None:
            lines.append("")
            lines.extend(searched.brief)
        lines.append("")
        lines.append("🔴 **정적 전개 추천은 내지 않았습니다** — 이번 요청의"
                     " 입력이 규칙 검증을 통과하지 못했습니다.")
        lines.append("거절한 입력에 대해 전개를 추천하면 그 입력이 통과한"
                     " 것으로 읽힙니다. 위에 적힌 위반을 고쳐서 다시"
                     " 보내 주세요.")
        detail = combo_attachments(
            _combo_detail_text(agent, executed, plan=None, verdict=None,
                               searched=searched)
        )
        lines.append("")
        #: 🔴 **이 첨부에는 정적 계획이 없다** — 거절한 입력에 전개를
        #: 추천하지 않는다는 계약이 그렇다 (위 설명). 가리키는 줄도 그
        #: 낱말을 쓰지 않는다.
        lines.extend(_detail_pointer_lines(detail, with_plan=False))
        return ComboResponse(
            messages=tuple(paginate(
                lines, max_messages=COMBO_MESSAGE_LIMIT,
                overflow_notice=_overflow_notice(detail),
            )),
            attachments=detail.attachments,
            detail_notice=detail.notice,
            detail_omitted=detail.omitted_lines,
        )

    plan = ComboPlanner(agent.repository).plan(FixedHand(tuple(hand_ids)),
                                               board=board_ids, draft=draft)

    verdict = combo_verdict(plan)

    #: 🔴 **같은 검사를 두 번 다르게 말하지 않는다** (Phase 6-AB 보완8).
    #:
    #: ``recipe:`` 가 이미 답한 줄은 플래너의 "사람이 확인할 것" 목록에서
    #: 빼고, 그 사실을 한 번 적는다. 🔴 **플래너의 판정을 바꾸지 않는다** —
    #: ``plan.manual_checks`` 는 그대로이고, 바뀌는 것은 보여 줄 때 어느
    #: 줄이 이미 답을 받았는지 가리는 일뿐이다.
    #:
    #: 🔴 **요약과 첨부가 같은 값을 쓴다** (6-AE). 두 자리에서 따로 걸러
    #: 내면 첨부가 요약과 다른 말을 하게 된다 — 실제로 6-AE 작업 중에
    #: 첨부 쪽에만 거르지 않은 목록이 들어갔고 시험이 그것을 잡았다.
    answered_by_recipe = bool(recipe_text and recipe_text.strip())
    shown_checks = [
        item for item in plan.manual_checks
        if not (answered_by_recipe and draft is None
                and "패가 덱에서 나올 수" in item)
    ]
    hidden_checks = len(plan.manual_checks) - len(shown_checks)

    #: 🔴 **실제 실행을 정적 계획보다 앞에 둔다.** 둘을 같은 목록에 섞지
    #: 않고, 먼저 "실제로 돌린 것" 을 보여 준 다음 "돌리지 않은 계획" 을
    #: 보여 준다 (§13 "사용자에게 혼동시키지 않는다").
    lines.append("")
    lines.extend(executed.brief)
    if searched is not None:
        lines.append("")
        lines.extend(searched.brief)

    lines.append("")
    if executed.ran:
        #: 🔴 **실제 실행이 있으면 정적 계획을 길게 붙이지 않는다** (6-AE
        #: §3). 실행 기록 바로 아래에 일곱 걸음짜리 계획이 붙으면 "실행
        #: 이후의 추가 행동" 으로 읽힌다 — 실측으로 그 절이 응답의 절반을
        #: 차지했고 마지막에 잘림 안내가 붙었다.
        lines.append(
            f"**[정적 계획은 첨부에 있습니다]** 🔴 엔진으로 돌린 것이"
            f" **아니고**, 위 실행의 다음 행동도 아닙니다"
            f" (판정: {verdict.describe_ko()} · {len(plan.steps)}걸음)."
        )
        if hidden_checks:
            #: 🔴 **이 한 줄은 요약에 남긴다** (보완8 이 세운 계약). 첨부로
            #: 밀면 사용자는 플래너의 "검증하지 않았습니다" 와 실행의 판정
            #: 둘 중 어느 것이 답인지 알 수 없다.
            lines.append("🔴 **패가 덱에서 나올 수 있는지는 이 요청에서 이미"
                         " 검사했습니다** — 위 `[실제 엔진 실행]` 절이"
                         " `recipe:` 로 판정했고, 그 결과가 이 응답의"
                         " 판정입니다.")
    else:
        #: 🔴 **실행이 없으면 그 사실이 먼저다** (6-AE §3). 위의
        #: ``executed.brief`` 가 *"하지 않았습니다 — 레시피가 없습니다"* 를
        #: 이미 적었고, 그 아래에 오는 계획은 **참고**다.
        #:
        #: 🔴 **이때는 줄이지 않는다.** 실제 실행이 없으면 이 계획이
        #: 응답의 내용 전부이고, 요약으로 줄이면 사용자가 아무것도 받지
        #: 못한다. 줄이는 것은 **실제 실행이 있을 때**뿐이다 (위 가지).
        lines.append("**[실행하지 않은 참고 계획]**")
        lines.append("🔴 카드 데이터를 읽어 만든 계획이고 **엔진으로 돌린"
                     " 것이 아닙니다.** 아래 걸음 수는 실행 걸음이"
                     " **아닙니다.**")
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
        if shown_checks:
            lines.append("")
            lines.append("**[사람이 직접 확인할 것]**")
            lines.extend(f"  - {item}" for item in shown_checks)
        if hidden_checks:
            lines.append("")
            lines.append("🔴 **패가 덱에서 나올 수 있는지는 이 요청에서 이미"
                         " 검사했습니다** — 위쪽 `[실제 엔진 실행]` 절이"
                         " `recipe:` 로 판정했고, 그 결과가 이 응답의"
                         " 판정입니다. (정적 계획은 자연어 `deck:` 초안을"
                         " 받는 별도 경로여서 그 검사를 따로 하지 않습니다.)")

    detail = combo_attachments(
        _combo_detail_text(agent, executed, plan=plan, verdict=verdict,
                           manual_checks=tuple(shown_checks),
                           hidden_checks=hidden_checks,
                           searched=searched)
    )

    #: 🔴 **전개 기록을 함께 붙인다** (Phase 6-AR). 상세 기록 첨부 뒤에
    #: 붙이고, 첨부 수 상한에 걸리면 **상세 기록을 밀어내지 않는다** —
    #: 어느 쪽이 더 중요한지는 "실행 결과를 확인할 수 있어야 한다" 가
    #: 정한다 (§6: 외부 연동이 없어도 실행 결과와 상세 기록은 남는다).
    attachments = list(detail.attachments)
    replay_item = replay_attachment(executed.replay) if executed.ran else None
    replay_dropped = bool(executed.ran and executed.replay and
                          replay_item is None)
    replay_skipped = False
    if replay_item is not None:
        room = len(attachments) < COMBO_ATTACHMENT_COUNT_LIMIT
        if detail.complete and room:
            attachments.append(replay_item)
        else:
            #: 🔴 상세 기록을 먼저 지킨다 (``COMBO_REPLAY_SKIPPED_NOTICE``).
            replay_item, replay_skipped = None, True

    lines.append("")
    if executed.ran:
        #: 🔴 **없는 링크를 약속하지 않는다.** 사이트 첫 화면 주소를 이
        #: 전개의 재생 링크처럼 적지 않는다 (상수의 설명).
        lines.append(COMBO_REPLAY_VIEW_UNAVAILABLE)
    lines.extend(_detail_pointer_lines(detail))
    if replay_item is not None:
        lines.append(
            f"🧾 **전개 기록은 첨부 `{replay_item.filename}`** 에 있습니다 —"
            f" 시작 판 · 걸음마다의 카드 이동 · 비용 · 대상 · 최종 판"
            f" (한 걸음씩 다시 그리는 데 쓰는 값입니다)."
        )
    elif replay_skipped:
        lines.append(COMBO_REPLAY_SKIPPED_NOTICE)
    elif replay_dropped:
        lines.append(COMBO_REPLAY_FAILED_NOTICE)

    return ComboResponse(
        messages=tuple(paginate(
            lines, max_messages=COMBO_MESSAGE_LIMIT,
            overflow_notice=_overflow_notice(detail),
        )),
        attachments=tuple(attachments),
        detail_notice=detail.notice,
        detail_omitted=detail.omitted_lines,
    )


def _combo_detail_text(agent, executed: OpeningReport,
                       plan=None, verdict=None,
                       manual_checks: "tuple[str, ...] | None" = None,
                       hidden_checks: int = 0,
                       searched: "OpeningReport | None" = None) -> str:
    """
    첨부에 담을 **전체 상세 기록** (Phase 6-AE).

    🔴 **실제 실행과 정적 계획을 명확히 분리한다.** 두 절의 머리말이 서로
    다르고, 정적 계획 절은 "돌리지 않았다" 를 제 머리말에 적는다 — 실행
    기록 뒤에 이어 붙여 "실행 이후의 행동" 으로 읽히지 않게 한다 (§3).

    🔴 **줄이지 않는다.** 실행 기록은 CLI 가 보는 세 함수의 출력 그대로이고
    (``render_opening_setup`` · ``render_opening_run`` ·
    ``render_opening_board``), 정적 계획도 전부 적는다.
    """
    lines = [
        f"{BOT_NAME} /combo 상세 기록",
        "=" * 68,
        "🔴 이 파일은 Discord 기본 응답의 요약이 가리키는 **전체 기록**"
        "입니다.",
    ]
    if plan is not None:
        lines.append("🔴 아래 두 절은 서로 다른 것입니다 — 앞은 **실제로"
                     " 돌린 것**, 뒤는 **돌리지 않은 정적 계획**입니다.")
    else:
        #: 🔴 **없는 절을 머리말이 예고하지 않는다** (6-AE 보완). 입력을
        #: 거절한 응답에는 정적 계획 절이 아예 없으므로 (6-AA 의 계약),
        #: 머리말이 그것을 적으면 파일이 제 내용을 잘못 말한다.
        lines.append("🔴 이 파일에는 **실제로 돌린 것**만 있습니다 — 정적"
                     " 전개 추천은 내지 않았습니다.")
    lines.append("")
    lines.extend(executed.detail)
    #: 🔴 **탐색 기록은 고정 경로 실행과 다른 절이다** (Phase 6-AH). 같은
    #: 목록에 섞으면 "적어 둔 경로를 따라간 것" 과 "엔진이 허가한 분기를
    #: 펼친 것" 을 구별할 수 없다.
    if searched is not None:
        lines.append("")
        lines.append("=" * 68)
        lines.append("[아래는 제한 전개 탐색입니다 — 적어 둔 경로를 따라간"
                     " 것이 아닙니다]")
        lines.append("=" * 68)
        lines.extend(searched.detail)
    if plan is not None:
        lines.append("")
        lines.append("=" * 68)
        lines.append("[아래는 실행하지 않은 정적 계획입니다]")
        lines.append("=" * 68)
        lines.append("🔴 카드 데이터를 읽어 만든 계획이고 **엔진으로 돌린"
                     " 것이 아닙니다.** 위 실행의 다음 행동도 아닙니다.")
        if verdict is not None:
            lines.append(f"정적 계획의 판정: {verdict.describe_ko()}")
            lines.append(verdict.detail_ko())
        lines.extend(_combo_step_lines(agent, plan))
        if plan.stopped_reason:
            lines.append("")
            lines.append(f"🔴 중단: {plan.stopped_reason}")
        if plan.unsupported:
            lines.append("")
            lines.append("[엔진이 지원하지 않아 계획에 넣지 않은 절차]")
            lines.extend(f"  - {item}" for item in plan.unsupported)
        #: 🔴 **요약과 같은 목록을 쓴다** — ``recipe:`` 가 이미 답한 줄은
        #: 부르는 쪽이 걸러서 넘긴다 (``combo_response`` 의 설명).
        shown = (plan.manual_checks if manual_checks is None
                 else manual_checks)
        if shown:
            lines.append("")
            lines.append("[사람이 직접 확인할 것]")
            lines.extend(f"  - {item}" for item in shown)
        if hidden_checks:
            lines.append("")
            lines.append("🔴 패가 덱에서 나올 수 있는지는 이 요청에서 이미"
                         " 검사했습니다 — 위 실행 절이 `recipe:` 로"
                         " 판정했고, 그 결과가 이 응답의 판정입니다."
                         " (정적 계획은 자연어 `deck:` 초안을 받는 별도"
                         " 경로여서 그 검사를 따로 하지 않습니다.)")
    return "\n".join(lines)


def combo_messages(agent, hand_text: str, board_text: str = "",
                   deck_text: str = "", recipe_text: str = "",
                   line_text: str = "") -> "list[str]":
    """
    ``/combo`` 의 **기본 메시지들**만. 첨부가 필요하면
    :func:`combo_response` 를 쓴다 (Phase 6-AE).

    🔴 **엔진을 다시 돌리지 않는다** — :func:`combo_response` 를 한 번 부르고
    그 메시지만 꺼낸다. 기존 호출부와 시험이 이 이름을 쓰고 있어서 남겨
    두었고, 첨부를 보내는 자리는 :class:`SearchService` 쪽이다.
    """
    return list(combo_response(agent, hand_text, board_text, deck_text,
                               recipe_text, line_text).messages)


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
        return list(self.combo_response(hand_text, board_text, deck_text,
                                        recipe_text, line_text).messages)

    def combo_response(self, hand_text: str, board_text: str = "",
                       deck_text: str = "", recipe_text: str = "",
                       line_text: str = "", search_text: str = "",
                       results_text: str = "",
                       followups_text: str = "") -> ComboResponse:
        """
        전개 계획을 세워 **메시지들과 첨부들**을 돌려준다 (Phase 6-AE).

        🔴 ``/search`` · ``/deck`` 과 **같은 카드 데이터를 쓴다.** 콤보
        플래너가 요구하는 것은 ``repository`` 하나이고 그것은 이미 여기
        있다.

        🔴 **예외를 밖으로 내보내지 않는다** (``deck_texts`` 와 같은 이유).
        실패했을 때 첨부를 붙이지 않는다 — 없는 것을 있는 것처럼 보내지
        않는다.
        """
        if self._agent is None:
            return ComboResponse(messages=(COMBO_UNAVAILABLE_MESSAGE,))
        try:
            return combo_response(self._agent, hand_text, board_text,
                                  deck_text, recipe_text, line_text,
                                  search_text, results_text, followups_text)
        except Exception:  # noqa: BLE001 - 봇을 죽이지 않는다
            logger.exception("전개 계획 생성에 실패했습니다. 패=%r 필드=%r"
                             " 덱=%r 레시피=%r 경로=%r 탐색=%r 결과수=%r"
                             " 후속=%r",
                             hand_text, board_text,
                             deck_text, recipe_text, line_text, search_text,
                             results_text, followups_text)
            return ComboResponse(messages=(COMBO_ERROR_MESSAGE,))

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
             " 예: orcust-girsu",
        search="(선택) 제한 전개 탐색의 목표 — 적어 둔 경로를 쓰지 않고"
               " 엔진이 허가한 분기를 펼칩니다. 예: galatea",
        results="(선택) 모을 서로 다른 결과 수 (2~5, 기본은 1개) — 주면"
                " 결과들의 남은 자원을 비교합니다. 강약 평가는 아닙니다",
        followups="(선택) 목표 도달 뒤 더 탐색할 비흐름 행동 수 (0~3, 기본은"
                  " 0 = 첫 도달에서 멈춤) — results 2 이상과 함께 주십시오."
                  " 최선 전개도 최종 집 완성도 아닙니다")
    async def combo_command(interaction: "discord.Interaction",
                            hand: str, board: str = "",
                            deck: str = "", recipe: str = "",
                            line: str = "", search: str = "",
                            results: str = "",
                            followups: str = "") -> None:
        #: 🔴 ``/search`` · ``/deck`` 과 같은 순서다.
        #: 🔴 **탐색은 오래 걸릴 수 있다** (실측 20~150초 — 보고서 §5).
        #: 그래서 ``defer()`` 로 먼저 응답을 열고 (3초 제한), 실제 탐색은
        #: ``asyncio.to_thread`` 로 보내 이벤트 루프를 막지 않는다 —
        #: 기존 ``/combo`` 와 **같은 구조**이고 새로 만든 것이 없다.
        await interaction.response.defer()
        response = await asyncio.to_thread(
            combo_service.combo_response, hand, board, deck, recipe, line,
            search, results, followups)
        await send_combo_response(interaction.followup, response)

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


#: 첨부 전송이 실패했을 때 사용자에게 적는 한 줄 (Phase 6-AE 보완).
#:
#: 🔴 **원인을 단정하지 않는다.** 예외는 상한 거절일 수도, 끊긴 연결일
#: 수도, 권한 문제일 수도 있다 — 그것을 "첨부가 너무 큽니다" 로 적으면
#: 사용자가 엉뚱한 것을 고치려 한다. 무엇이 일어났는지는 로그에 있다.
#:
#: 🔴 **첨부를 받았다고 오해하게 하지 않는다** — 받지 못했다고 먼저 적는다.
COMBO_ATTACHMENT_FAILED_NOTICE = (
    "🔴 **상세 기록 첨부를 보내지 못했습니다** (원인은 봇 로그에 있습니다)."
    " 위 요약 말고는 전달된 것이 없습니다 — 전체 기록은 CLI 의"
    " `python3 -m app.main combo … --recipe …` 로 볼 수 있습니다."
)


async def send_combo_response(sender, response: ComboResponse,
                              limit: int = DISCORD_MESSAGE_LIMIT) -> int:
    """
    ``/combo`` 응답을 보낸다 — **요약 메시지들과 상세 첨부** (Phase 6-AE).

    보낸 메시지 수를 돌려준다.

    🔴 **여기서만 ``discord`` 를 만진다.** :class:`ComboAttachment` 는
    이름과 바이트만 들고 있고, ``discord.File`` 로 감싸는 일이 이 함수다 —
    그래서 응답을 만드는 순수 함수들은 라이브러리 없이 테스트된다.

    🔴 **메모리 버퍼를 쓴다.** 임시 파일을 만들지 않으므로 디스크에 남는
    것이 없고, 사용자 입력이 경로가 되는 길도 없다. 버퍼는 **성공 · 실패
    양쪽에서** 닫는다 (``finally``).

    🔴 **실패 안내도 상한을 지킨다** (6-AE 보완 — 외부 검토 B). 전에는 실패한
    메시지 뒤에 안내를 **덧붙여** 다시 보내고 길이를 다시 세지 않았다. 실측:
    2,000자 + 안내 = **2,052자**, 상한을 거절하는 전송에서 재전송도 실패.
    지금은 자리가 있으면 붙이고, 없으면 **안내를 따로 한 번** 보낸다 —
    안내가 잘려 사라지지 않고, 메시지를 무제한 늘리지도 않는다 (최대 하나).

    🔴 **이미 보낸 메시지를 다시 보내지 않는다.** 되돌리는 것은 실패한 그
    한 번뿐이다.

    🔴 **fallback 까지 실패하면 성공으로 보고하지 않는다** — 오류를 로그에
    남기고 예외를 그대로 올린다.
    """
    import io

    import discord

    messages = list(response.messages)
    if not messages:
        #: 🔴 내용이 없는 응답을 성공으로 보내지 않는다.
        logger.error("/combo 응답에 메시지가 없습니다 — 보내지 않았습니다.")
        await sender.send(COMBO_ERROR_MESSAGE)
        return 1

    sent = 0
    for index, text in enumerate(messages):
        last = index == len(messages) - 1
        if not (last and response.attachments):
            await sender.send(text)
            sent += 1
            continue

        #: 🔴 버퍼를 따로 들고 있는다 — ``discord.File`` 은 **``fp.close``
        #: 를 무해한 함수로 덮어쓰고** (언제 닫을지 제가 정하려고), 제가
        #: 만든 파일만 닫는다 (``_owner``). 우리가 넘긴 ``BytesIO`` 는
        #: :func:`_close_attachment_files` 가 닫는다.
        buffers = [io.BytesIO(item.data) for item in response.attachments]
        files = [
            discord.File(buffer, filename=item.filename)
            for buffer, item in zip(buffers, response.attachments)
        ]
        try:
            await sender.send(text, files=files)
            sent += 1
        except Exception:  # noqa: BLE001 - 봇을 죽이지 않는다
            logger.exception(
                "/combo 첨부 전송에 실패했습니다 (메시지 %d/%d, 첨부 %d개)."
                " 첨부 없이 다시 보냅니다.",
                index + 1, len(messages), len(files),
            )
            sent += await _send_without_attachment(sender, text, limit)
        finally:
            _close_attachment_files(files, buffers)
    return sent


def _close_attachment_files(files, buffers) -> None:
    """
    첨부 파일과 **그 버퍼**를 닫는다 (Phase 6-AE 보완 — 외부 검토 B).

    🔴 **순서가 중요하다.** ``discord.File.__init__`` 은 ``fp.close`` 를
    아무 일도 하지 않는 함수로 **덮어쓴다** (전송 중에 닫히지 않게 하려고).
    그래서 ``BytesIO.close()`` 를 먼저 부르면 아무 일도 일어나지 않는다 —
    ``File.close()`` 가 원래 함수를 되돌려 놓은 **뒤에** 닫아야 한다.

    🔴 **정리 실패로 죽지 않는다.** 닫지 못하면 로그에 남기고 넘어간다 —
    전송 결과를 정리 실패로 뒤집지 않는다.
    """
    for item in files:
        try:
            item.close()
        except Exception:  # noqa: BLE001 - 정리 실패로 죽지 않는다
            logger.debug("첨부 파일을 닫지 못했습니다.", exc_info=True)
    for buffer in buffers:
        try:
            buffer.close()
        except Exception:  # noqa: BLE001
            logger.debug("첨부 버퍼를 닫지 못했습니다.", exc_info=True)


async def _send_without_attachment(sender, text: str, limit: int) -> int:
    """
    첨부 없이 **다시 한 번** 보낸다 (Phase 6-AE 보완 — 외부 검토 B).

    보낸 메시지 수를 돌려준다.

    🔴 **상한을 다시 센다.** 안내를 붙여도 상한 안이면 한 메시지로, 아니면
    **원문과 안내를 따로** 보낸다 — 안내를 잘라 없애지 않는다.

    🔴 **한 번만 되돌린다.** 이 전송이 또 실패하면 로그에 오류를 남기고
    예외를 올린다 — 성공으로 보고하지 않는다.
    """
    joined = f"{text}\n{COMBO_ATTACHMENT_FAILED_NOTICE}"
    plan = ([joined] if len(joined) <= limit
            else [text, COMBO_ATTACHMENT_FAILED_NOTICE])
    #: 🔴 안내 자체가 상한을 넘는 일은 없다 (상수이고 짧다). 혹시 그렇다면
    #: 그것은 코드의 잘못이므로 조용히 자르지 않고 멈춘다.
    for piece in plan:
        if len(piece) > limit:  # pragma: no cover - 방어선
            raise AssertionError(
                f"되돌린 메시지가 상한을 넘었습니다: {len(piece)} > {limit}"
            )
    sent = 0
    try:
        for piece in plan:
            await sender.send(piece)
            sent += 1
    except Exception:
        logger.error(
            "/combo 첨부 없이 다시 보내는 것도 실패했습니다 — 이 응답은"
            " 전달되지 않았습니다 (보낸 메시지 %d개).", sent, exc_info=True,
        )
        raise
    return sent


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
