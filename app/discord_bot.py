"""
갈라테아 — Discord 어댑터 (Phase 5-A).

    Discord 슬래시 명령
          ↓
    CommandTree 핸들러            ← 이 파일. discord 를 아는 유일한 자리
          ↓
    순수 응답 생성 함수            ← discord 를 모른다. 테스트가 여기를 본다
          ↓
    (앞으로) core · deck 계층      ← 아직 연결하지 않았다

🔴 **이번 단계는 ``/ping`` 하나다.** 덱 구축(`deck/`)과 전개 계획은
**연결하지 않았다** — 연결했다고 적지도 않는다. 붙이는 자리는 §확장 지점에
적어 두었다.

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

import logging
import os
import sys

#: 봇 표시 이름. 응답 문구와 로그가 같은 이름을 쓴다.
BOT_NAME = "갈라테아"

#: ``/ping`` 의 명령 설명. 조사가 붙으므로 f-string 으로 끼우지 않는다 —
#: ``f"{BOT_NAME} 가 …"`` 로 쓰면 "갈라테아 가" 처럼 띄어 쓰게 된다.
PING_DESCRIPTION = "갈라테아가 살아 있는지 확인합니다"

#: 환경변수 이름 — 테스트와 문서가 같은 상수를 본다.
TOKEN_ENV = "DISCORD_BOT_TOKEN"
GUILD_ENV = "DISCORD_DEV_GUILD_ID"

LOGGER_NAME = "galatea"
logger = logging.getLogger(LOGGER_NAME)


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
def build_client(dev_guild_id: "int | None" = None):
    """
    클라이언트와 명령 트리를 만든다. **접속하지 않는다.**

    ``intents`` 는 기본값만 쓴다. 슬래시 명령은 메시지 내용을 읽지 않으므로
    ``message_content`` 특권 intent 가 **필요하지 않다** — 켜면 Discord
    쪽에서 승인이 필요해지고 얻는 것이 없다.
    """
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.command(name="ping", description=PING_DESCRIPTION)
    async def ping(interaction: "discord.Interaction") -> None:
        #: 🔴 핸들러는 **받아서 넘기기만** 한다. 문구는 순수 함수가 만든다.
        await interaction.response.send_message(ping_message())

    @client.event
    async def on_ready() -> None:
        user = client.user
        logger.info("%s 접속 완료: %s (id=%s)", BOT_NAME, user,
                    getattr(user, "id", "?"))
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

    client, _tree = build_client(dev_guild_id)

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
#: 🔴 **아직 구현하지 않았다.** 지원하는 것처럼 적지 않는다.
#:
#: 붙이는 방법 (Phase 4-B 의 산출물을 그대로 쓴다):
#:
#: 1. :func:`ping_message` 와 같은 자리에 순수 함수를 하나 더 둔다. 예:
#:    ``def deck_message(request_text: str) -> str`` — 안에서
#:    ``deck.request.parse_deck_request`` → ``deck.builder.DeckBuilder`` →
#:    ``deck.validator.DeckValidator`` → ``deck.report.render_*`` 를 부른다.
#:    그 함수는 discord 를 모른다.
#: 2. :func:`build_client` 에 ``@tree.command(name="deck")`` 핸들러를
#:    더하고, **받아서 넘기기만** 한다.
#: 3. 덱 구축은 리포지토리 빌드(카드 14,000여 장)를 요구해 초 단위가 걸린다.
#:    Discord 는 첫 응답을 3초 안에 요구하므로 핸들러에서
#:    ``await interaction.response.defer()`` 를 먼저 부르고, 무거운 작업은
#:    ``asyncio.to_thread`` 로 이벤트 루프 밖에서 돌려야 한다 — 그렇지
#:    않으면 봇 전체가 그 시간 동안 멈춘다.
#: 4. 리포지토리는 **한 번만** 만들어 재사용한다. 명령마다 다시 만들면
#:    매번 수 초가 든다.
#:
#: 이 네 가지는 설계 메모이고, 이번 단계에서 실행하지 않았다.

if __name__ == "__main__":
    raise SystemExit(main())
