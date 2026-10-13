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


class SearchService:
    """
    카드 데이터를 **한 번만** 만들어 들고 있는 자리.

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
# 확장 지점 — 앞으로 /deck · /combo 를 붙이는 자리
# ===========================================================================
#: 🔴 ``/deck`` 과 ``/combo`` 는 **아직 구현하지 않았다.** 지원하는 것처럼
#: 적지 않고, 명령으로 등록하지도 않았다.
#:
#: ``/search`` 가 이미 세운 것 (그대로 따르면 된다):
#:
#: * 순수 함수(:func:`search_message`)가 문구를 만들고 핸들러는 넘기기만 한다
#: * 핸들러가 ``defer()`` 를 먼저 부르고 무거운 작업을 ``asyncio.to_thread``
#:   로 보낸다
#: * 무거운 초기화는 :class:`SearchService` 가 ``on_ready`` 에서 한 번만 한다
#: * 출력은 :func:`clamp_to_discord_limit` 로 상한을 보장한다
#:
#: ``/deck`` 에 남은 **결정 두 가지** (그래서 이번에 하지 않았다):
#:
#: 1. 🔴 **출력이 상한을 넘는다.** 실측으로 덱 전체 출력이 3,102~3,367자이고
#:    Discord 상한의 1.6~1.7배다. 자를지, 나눠 보낼지, 파일로 붙일지를
#:    정해야 한다. :func:`clamp_to_discord_limit` 로 자르면 덱의 뒷부분이
#:    사라지는데 그것이 맞는 선택인지 결정되지 않았다.
#: 2. 🔴 **테마 해석에 실패해도 덱이 만들어진다.** 실측: "존재하지않는테마
#:    덱" 이 보강 카드 20종 40장을 돌려준다. ``notes`` 에 실패가 적히지만
#:    긴 출력에서는 묻힌다. 어댑터에서 "해석 실패면 덱을 보내지 않는다" 로
#:    막는 것이 ``deck/`` 을 건드리지 않는 방법이고, 그 정책을 정해야 한다.

if __name__ == "__main__":
    raise SystemExit(main())
