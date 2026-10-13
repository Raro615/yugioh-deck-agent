r"""
Phase 5-A — 갈라테아 Discord 봇의 **연결 전** 계약.

🔴 **실제 Discord 에 접속하지 않는다.** 유효한 토큰이 필요한 것은 전부
사용자의 로컬 환경에서 확인할 일이고, 토큰을 테스트에 적지 않는다.

여기서 고정하는 것:

1. 모듈이 **``discord.py`` 없이도 import 된다.** 토큰 처리와 응답 문구가
   라이브러리에 묶이면 어느 환경에서도 검증할 수 없다.
2. 토큰이 없으면 **안전하게 종료**한다 (종료 코드 2, 예외 누출 없음).
3. 🔴 **토큰 값이 로그·예외 메시지에 새지 않는다.**
4. ``/ping`` 의 응답 문구.
5. 개발용 서버 ID 가 없을 때의 동작이 정해져 있다.
6. 기존 CLI(`app/main.py`)와 충돌하지 않는다.
"""

from __future__ import annotations

import ast
import importlib
import logging
from pathlib import Path

import pytest

import app.discord_bot as bot

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRET = "SuPerSecret.Token.Value-DO-NOT-LEAK-1234567890"


# ===========================================================================
# A. import 와 모듈 성질
# ===========================================================================
def test_01_module_imports_without_the_discord_library():
    r"""🔴 §5-1 — ``discord`` 를 **모듈 맨 위에서 import 하지 않는다.**

    이 저장소는 런타임에 사실상 표준 라이브러리만 쓴다. 봇이 그 성질을
    깨면 라이브러리가 없는 환경에서 이 파일을 **읽는 것조차** 실패하고,
    그러면 토큰 처리와 문구를 어디서도 검증할 수 없다.
    """
    tree = ast.parse(Path(bot.__file__).read_text(encoding="utf-8"))
    top_level: list[str] = []
    for node in tree.body:               # 🔴 **모듈 최상위만** 본다
        if isinstance(node, ast.Import):
            top_level += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.append(node.module.split(".")[0])
    assert "discord" not in top_level, top_level
    #: 그리고 실제로 import 되어 있다 (이 파일 맨 위가 그 증거다)
    assert importlib.import_module("app.discord_bot") is bot


def test_02_the_module_file_is_not_named_discord_py():
    r"""🔴 §3.1 — 파일 이름이 ``discord.py`` 면 라이브러리를 가린다."""
    assert Path(bot.__file__).name == "discord_bot.py"
    assert not (PROJECT_ROOT / "app" / "discord.py").exists()
    assert not (PROJECT_ROOT / "discord.py").exists()


# ===========================================================================
# B. /ping 응답
# ===========================================================================
def test_03_ping_message_is_the_agreed_text():
    r"""🟢 §3.2 — ``/ping`` 응답 문구."""
    assert bot.ping_message() == "Pong! 갈라테아 온라인."
    assert bot.BOT_NAME == "갈라테아"


def test_04_the_handler_only_forwards_the_pure_function():
    r"""🔴 §3.4 — 핸들러가 문구를 **직접 쓰지 않는다.**

    핸들러 안에 문구를 적으면 discord 의 ``Interaction`` 없이 부를 수
    없어 테스트되지 않는다. 앞으로 ``/deck`` 도 같은 모양을 써야 한다.
    """
    source = Path(bot.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "ping"
    )
    body = ast.unparse(handler)
    assert "ping_message()" in body, body
    #: 문구 자체가 핸들러 안에 없다
    assert "Pong!" not in body, body


# ===========================================================================
# C. 토큰 — 없을 때 안전하게 종료하고, 값이 새지 않는다
# ===========================================================================
@pytest.mark.parametrize("value", [None, "", "   ", "\n"])
def test_05_missing_or_blank_token_raises_without_the_value(value):
    r"""🟢 §3.3 — 없거나 공백뿐이면 거부한다."""
    env = {} if value is None else {bot.TOKEN_ENV: value}
    with pytest.raises(bot.MissingTokenError) as caught:
        bot.load_token(env=env)
    message = str(caught.value)
    assert bot.TOKEN_ENV in message
    assert ".env.example" in message


def test_06_a_present_token_is_returned_stripped():
    r"""🟢 §3.3 — 공백을 떼고 그대로 돌려준다."""
    assert bot.load_token(env={bot.TOKEN_ENV: f"  {SECRET}  "}) == SECRET


def test_07_main_exits_safely_with_code_2_when_the_token_is_missing(
        monkeypatch, caplog):
    r"""🔴 §3.3 / §5-2 — 토큰이 없으면 **예외 없이 종료 코드 2.**"""
    monkeypatch.delenv(bot.TOKEN_ENV, raising=False)
    monkeypatch.delenv(bot.GUILD_ENV, raising=False)
    with caplog.at_level(logging.ERROR, logger=bot.LOGGER_NAME):
        code = bot.main()
    assert code == 2
    assert bot.TOKEN_ENV in caplog.text


def test_08_the_token_value_never_reaches_the_log(monkeypatch, caplog):
    r"""🔴 §3.3 / §5-3 — **토큰 값이 로그에 새지 않는다.**

    토큰을 넣고 접속 직전까지 간 뒤, 남은 로그 전체에서 값을 찾는다.
    접속은 하지 않는다 — ``client.run`` 을 가로채 호출만 기록한다.
    """
    monkeypatch.setenv(bot.TOKEN_ENV, SECRET)
    monkeypatch.delenv(bot.GUILD_ENV, raising=False)

    called: dict[str, object] = {}

    class _FakeClient:
        def run(self, token, **kwargs):
            called["token"] = token
            called["kwargs"] = kwargs

    monkeypatch.setattr(bot, "build_client",
                        lambda guild: (_FakeClient(), object()))
    with caplog.at_level(logging.DEBUG, logger=bot.LOGGER_NAME):
        code = bot.main()

    assert code == 0
    #: 토큰은 run 에 전달됐다 — 기능은 살아 있다
    assert called["token"] == SECRET
    #: 🔴 그런데 로그 어디에도 값이 없다
    assert SECRET not in caplog.text
    for record in caplog.records:
        assert SECRET not in record.getMessage()


def test_09_no_source_file_contains_a_hardcoded_token_or_real_env_value():
    r"""🔴 §3.3 — 소스에 토큰을 넣지 않았고, ``.env.example`` 은 비어 있다."""
    source = Path(bot.__file__).read_text(encoding="utf-8")
    #: 환경변수 이름만 등장하고 값은 없다
    assert bot.TOKEN_ENV in source
    for suspicious in ("MTA", "Bot ", "token=\"", "token='"):
        assert suspicious not in source, suspicious

    example = PROJECT_ROOT / ".env.example"
    assert example.is_file(), ".env.example 이 있어야 한다"
    for line in example.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{bot.TOKEN_ENV}="):
            assert line.strip() == f"{bot.TOKEN_ENV}=", line
        if line.startswith(f"{bot.GUILD_ENV}="):
            assert line.strip() == f"{bot.GUILD_ENV}=", line


def test_10_dotenv_is_ignored_by_git_but_the_example_is_not():
    r"""🔴 §3.3 — ``.env`` 는 무시되고 ``.env.example`` 은 커밋된다."""
    ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in ignore.splitlines()]
    assert ".env" in lines, lines[-8:]
    assert "!.env.example" in lines, lines[-8:]


# ===========================================================================
# D. 개발용 서버 ID — 없을 때의 동작이 정해져 있다
# ===========================================================================
def test_11_dev_guild_is_optional_and_absence_is_not_an_error():
    r"""🟢 §3.2 — 설정이 없으면 ``None`` 이고 오류가 아니다."""
    assert bot.load_dev_guild_id(env={}) is None
    assert bot.load_dev_guild_id(env={bot.GUILD_ENV: ""}) is None
    assert bot.load_dev_guild_id(env={bot.GUILD_ENV: "  "}) is None


def test_12_dev_guild_is_parsed_as_an_integer():
    r"""🟢 §3.2 — 서버 ID 는 정수다. 코드에 하드코딩하지 않는다."""
    assert bot.load_dev_guild_id(env={bot.GUILD_ENV: " 1234567890 "}) == 1234567890
    source = Path(bot.__file__).read_text(encoding="utf-8")
    #: 17~20자리 숫자 리터럴(=실제 서버 ID 모양)이 소스에 없다
    import re
    assert re.search(r"\b\d{17,20}\b", source) is None


def test_13_an_unparsable_dev_guild_is_refused_not_ignored():
    r"""🔴 §3.2 — 조용히 무시하면 "동기화했는데 안 보인다" 를 못 짚는다."""
    with pytest.raises(bot.InvalidGuildError) as caught:
        bot.load_dev_guild_id(env={bot.GUILD_ENV: "my-server"})
    assert bot.GUILD_ENV in str(caught.value)


def test_14_main_exits_with_code_2_on_a_bad_dev_guild(monkeypatch, caplog):
    r"""🟢 §3.2 — 설정 오류도 안전하게 종료한다 (코드 2)."""
    monkeypatch.setenv(bot.TOKEN_ENV, SECRET)
    monkeypatch.setenv(bot.GUILD_ENV, "not-a-number")
    with caplog.at_level(logging.ERROR, logger=bot.LOGGER_NAME):
        code = bot.main()
    assert code == 2
    assert SECRET not in caplog.text


# ===========================================================================
# E. 기존 프로젝트와의 관계
# ===========================================================================
def test_15_the_bot_does_not_touch_the_existing_cli_or_card_layers():
    r"""🔴 §3.4 — 어댑터는 아직 **아무 계층도 부르지 않는다.**

    이번 단계는 ``/ping`` 하나다. 덱 구축을 연결했다고 적지 않으려면,
    연결하지 않았다는 사실을 코드로 확인해 두어야 한다.
    """
    tree = ast.parse(Path(bot.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for layer in ("deck", "core", "engine", "agent", "analysis", "app"):
        assert layer not in imported, (layer, sorted(imported))


def test_16_the_existing_cli_still_builds_its_parser():
    r"""🟢 §5-5 — 기존 진입점이 봇 추가로 깨지지 않는다."""
    from app.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["card", "483"])
    assert args.command == "card"
    #: Phase 4-B 의 명령도 그대로다
    assert parser.parse_args(["deck", "오르페골 덱"]).command == "deck"


def test_17_the_bot_requirements_file_declares_discord_py():
    r"""🟢 §3.1 — 의존성을 선언해 두었다."""
    path = PROJECT_ROOT / "requirements-bot.txt"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "discord.py" in text
    #: 기존 dev 의존성 파일은 건드리지 않았다
    dev = (PROJECT_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "discord" not in dev


def test_18_future_commands_are_marked_unimplemented_not_claimed():
    r"""🔴 §6 — 아직 없는 기능을 **있는 것처럼 적지 않는다.**"""
    source = Path(bot.__file__).read_text(encoding="utf-8")
    assert "아직 구현하지 않았다" in source
    #: /deck · /combo 가 실제 명령으로 등록되어 있지 않다
    tree = ast.parse(source)
    registered = {
        kw.value.value
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "name" and isinstance(kw.value, ast.Constant)
    }
    assert registered == {"ping"}, registered

def test_19_the_real_command_tree_registers_ping_and_sends_the_text():
    r"""🟢 §5-4 — **실제 ``app_commands`` 핸들러**를 거쳐 문구를 확인한다.

    접속하지 않는다. ``discord`` 가 없는 환경에서는 이 한 테스트만 건너
    뛰고(``importorskip``) 나머지는 그대로 돈다 — 그게 모듈 맨 위에서
    discord 를 import 하지 않은 이유다 (`test_01`).
    """
    import asyncio

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    client, tree = bot.build_client(dev_guild_id=None)
    commands = tree.get_commands()
    assert [c.name for c in commands] == ["ping"]
    assert commands[0].description == bot.PING_DESCRIPTION

    #: 슬래시 명령은 메시지 내용을 읽지 않는다 — 특권 intent 를 켜지 않았다
    assert client.intents.message_content is False

    sent: list[str] = []

    class _Response:
        async def send_message(self, content, **kwargs):
            sent.append(content)

    class _Interaction:
        response = _Response()

    asyncio.run(commands[0].callback(_Interaction()))
    assert sent == [bot.ping_message()] == ["Pong! 갈라테아 온라인."]
