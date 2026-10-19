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
import re
from pathlib import Path

import pytest

import app.discord_bot as bot
from tests.conftest import requires_official_db

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

    #: 🔴 ``build_client`` 는 Phase 5-B 에서 ``service`` 인자를 받게 됐다.
    #: 가짜 구현도 같은 서명을 받아야 한다 — 서명을 안 맞추면 이 테스트는
    #: "토큰이 안 샌다" 가 아니라 ``TypeError`` 를 보게 된다. 의미는 그대로다.
    monkeypatch.setattr(bot, "build_client",
                        lambda guild, service=None: (_FakeClient(), object()))
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
def test_15_the_bot_reuses_app_main_and_touches_no_other_layer():
    r"""🔴 §1 / §2 — 어댑터가 **``app.main`` 만** 쓴다.

    🔴 **이 테스트의 범위를 Phase 5-B 와 5-C 가 두 번 정정했다.**

    * Phase 5-A: ``/ping`` 하나뿐이어서 "어떤 계층도 import 하지 않는다"
      가 사실이었다.
    * Phase 5-B: ``/search`` 가 ``app.main`` 의 ``format_card_line`` 과
      ``DeckAgent`` 를 쓰게 됐다 — 검색 로직을 다시 쓰지 않으려면 그래야
      한다. 허용 목록에 ``app`` 이 들어왔다.
    * Phase 5-C: ``/deck`` 이 ``deck.request`` · ``deck.builder`` ·
      ``deck.validator`` 를 부른다. ``app.main.cmd_deck`` 는 결과를
      ``print`` 하고 argparse 의 ``args`` 를 받으므로 Discord 에서 다시 쓸
      수 없다 — 그래서 **덱 계층을 직접** 부르는 것이 "복사하지 않는다" 를
      지키는 방법이다. 허용 목록에 ``deck`` 이 들어왔다.

    **단정을 약하게 바꾼 것이 아니다.** 지키려던 것은 "어댑터가 카드·엔진
    계층을 직접 만지지 않는다" 이고 그것은 그대로다: ``core`` · ``engine``
    · ``agent`` · ``analysis`` · ``rules`` · ``rulings`` · ``sources`` 는
    **여전히 하나도 import 하지 않는다.** 그리고 재사용하는 함수 이름을
    아래에서 함께 고정하므로, 어댑터가 ``deck`` 을 import 할 수 있게 된
    대신 **무엇을 부르는지**가 더 좁게 묶였다.
    """
    tree = ast.parse(Path(bot.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    #: 재사용하는 두 계층 — 둘 다 이 저장소의 기존 진입점이다
    assert "app" in imported, sorted(imported)
    assert "deck" in imported, sorted(imported)
    #: 🔴 카드·엔진 계층은 직접 만지지 않는다 (Phase 5-A 와 같다)
    for layer in ("core", "engine", "agent", "analysis", "rules",
                  "rulings", "sources"):
        assert layer not in imported, (layer, sorted(imported))

    #: 그리고 검색·덱 로직을 다시 쓰지 않았다 — 기존 함수를 부른다
    source = Path(bot.__file__).read_text(encoding="utf-8")
    #: 🔴 **Phase 6-Z 가 하나를 더했다** — ``opening_wiring(``.
    #:
    #: 6-Z 는 유발 발동과 해결 시점 선택을 전개 실행에 꽂았다. 그 둘은
    #: ``agent`` 와 ``integration`` 의 것이므로 어댑터가 직접 만들면 위의
    #: 금지 목록을 어긴다. 그래서 공용 자리 하나(``app.main.opening_wiring``)
    #: 가 만들고 CLI 와 어댑터가 **같은 것**을 받는다 — 경계도 지키고 둘이
    #: 갈라지지도 않는다.
    for reused in ("search_korean(", "format_card_line(",
                   "parse_deck_request(", "DeckBuilder(", "DeckValidator(",
                   "_parse_card_ids(", "FixedHand(", "ComboPlanner(",
                   "hand_effect_facts(", "opening_wiring("):
        assert reused in source, reused
    #: 직접 필터·검색 엔진을 세우거나, 덱 구성·검증을 다시 구현하지 않는다.
    #: 🔴 ``resolve_archetype`` 은 카드군 해석이고 ``DeckBuilder`` 가 한다 —
    #: 어댑터가 직접 부르면 같은 판정이 두 자리에 생긴다.
    for duplicated in ("SearchFilters(", "CardSearchEngine(",
                       "KoreanQueryParser(", "resolve_archetype(",
                       "CardRole.", "ValidationOutcome.", "RuleFinding("):
        assert duplicated not in source, duplicated


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
    #: 🔴 Phase 5-D 가 ``/combo`` 를 구현해 확장 지점이 비었다. 그래도
    #: "구현하지 않은 것을 적지 않는다" 는 계약은 **미구현 항목 목록**으로
    #: 계속 지킨다 — 무작위 패 생성과 실행 검증이 그것이다.
    assert "구현되어 있지 않습니다" in source
    #: /deck · /combo 가 실제 명령으로 등록되어 있지 않다
    tree = ast.parse(source)
    registered = {
        kw.value.value
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "name" and isinstance(kw.value, ast.Constant)
    }
    #: 🔴 Phase 5-B 가 ``search``, 5-C 가 ``deck``, 5-D 가 ``combo`` 를
    #: 더했다. 집합을 **정확히** 고정하므로 구현 없는 명령이 등록되면
    #: 이 테스트가 실패한다. 네 개가 지금 구현된 전부다.
    assert registered == {"ping", "search", "deck", "combo"}, registered

def test_19_the_real_command_tree_registers_ping_and_sends_the_text():
    r"""🟢 §5-4 — **실제 ``app_commands`` 핸들러**를 거쳐 문구를 확인한다.

    접속하지 않는다. ``discord`` 가 없는 환경에서는 이 한 테스트만 건너
    뛰고(``importorskip``) 나머지는 그대로 돈다 — 그게 모듈 맨 위에서
    discord 를 import 하지 않은 이유다 (`test_01`).
    """
    import asyncio

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    client, tree = bot.build_client(dev_guild_id=None)
    commands = {command.name: command for command in tree.get_commands()}
    #: 🔴 Phase 5-A 에서는 ``["ping"]`` 하나였다. 5-B 가 ``/search``,
    #: 5-C 가 ``/deck``, 5-D 가 ``/combo`` 를 실제로 등록했으므로 사실이
    #: 세 번 바뀌었다 — 목록을 이름 집합으로 고정하고 ``/ping`` 을 이름으로
    #: 꺼낸다. 느슨해진 게 아니라 등록 집합을 여전히 정확히 고정한다.
    assert set(commands) == {"ping", "search", "deck", "combo"}
    ping = commands["ping"]
    assert ping.description == bot.PING_DESCRIPTION

    #: 슬래시 명령은 메시지 내용을 읽지 않는다 — 특권 intent 를 켜지 않았다
    assert client.intents.message_content is False

    sent: list[str] = []

    class _Response:
        async def send_message(self, content, **kwargs):
            sent.append(content)

    class _Interaction:
        response = _Response()

    asyncio.run(ping.callback(_Interaction()))
    assert sent == [bot.ping_message()] == ["Pong! 갈라테아 온라인."]


# ===========================================================================
# Phase 5-B — ``/search``
# ===========================================================================
#: 🔴 가짜 카드·가짜 검색 결과. 검색 **파이프라인**을 흉내 내는 것이 아니라
#: :func:`app.discord_bot.search_message` 가 세 상황(정상 / 0건 / 해석 실패)을
#: 어떻게 **적는지**만 본다. 실제 데이터로 도는 확인은 ``test_29`` 가 한다.
class _FakeCard:
    def __init__(self, card_id: int, name: str):
        self.id = card_id
        self._name = name

    def summary_ko(self) -> str:
        return self._name


class _FakeParsed:
    def __init__(self, explain: str = "조건: 몬스터",
                 unknown_terms: tuple[str, ...] = ()):
        self._explain = explain
        self.unknown_terms = tuple(unknown_terms)

    def explain_ko(self) -> str:
        return self._explain


class _FakeResult:
    def __init__(self, cards, total: int | None = None):
        self._cards = list(cards)
        self.total = len(self._cards) if total is None else total

    def __iter__(self):
        return iter(self._cards)

    def __len__(self) -> int:
        return len(self._cards)


class _FakeAgent:
    """``search_korean`` 하나만 가진 가짜 에이전트. 호출 인자를 기록한다."""

    def __init__(self, parsed: _FakeParsed, result: _FakeResult):
        self._parsed = parsed
        self._result = result
        self.calls: list[tuple[str, object]] = []

    def search_korean(self, query, limit=None):
        self.calls.append((query, limit))
        return self._parsed, self._result


def test_20_the_length_guard_never_exceeds_the_discord_limit():
    r"""🔴 §4 — **2,000자를 넘지 않는다**, 그리고 자른 사실을 적는다.

    건수 제한(상위 10건)만으로는 보장되지 않는다 — 카드 이름 길이는
    카드마다 다르다. 그래서 길이로 한 번 더 막는 것을 여기서 고정한다.
    """
    assert bot.DISCORD_MESSAGE_LIMIT == 2000

    #: 한계 이하는 **손대지 않는다** (안내 문구를 괜히 붙이지 않는다)
    short = "\n".join(f"줄 {index}" for index in range(5))
    assert bot.clamp_to_discord_limit(short) == short
    assert bot.TRUNCATION_NOTICE not in bot.clamp_to_discord_limit(short)

    #: 경계: 정확히 한계 길이면 그대로다
    exact = "가" * bot.DISCORD_MESSAGE_LIMIT
    assert bot.clamp_to_discord_limit(exact) == exact

    #: 한계를 넘으면 잘리고, 결과는 **반드시** 한계 이하이며 사실을 적는다
    long_text = "\n".join("가" * 80 for _ in range(100))
    assert len(long_text) > bot.DISCORD_MESSAGE_LIMIT
    clamped = bot.clamp_to_discord_limit(long_text)
    assert len(clamped) <= bot.DISCORD_MESSAGE_LIMIT
    assert clamped.endswith(bot.TRUNCATION_NOTICE)
    #: 줄 중간에서 끊어 카드 한 줄을 반토막 내지 않는다
    body = clamped[: -len(bot.TRUNCATION_NOTICE)]
    assert body in long_text
    assert long_text[len(body)] == "\n"


def test_21_a_normal_search_reports_the_total_and_the_shown_count():
    r"""🟢 §2 / §4 — 정상 검색. CLI 와 **같은 줄**(``format_card_line``)로 적는다."""
    from app.main import format_card_line

    cards = [_FakeCard(1000 + index, f"카드{index}") for index in range(10)]
    agent = _FakeAgent(_FakeParsed("조건: 마법사족 몬스터"),
                       _FakeResult(cards, total=137))
    text = bot.search_message(agent, "마법사족 몬스터")

    #: 검색은 기존 파이프라인이 한다 — 이 함수는 limit 을 그대로 넘긴다
    assert agent.calls == [("마법사족 몬스터", bot.SEARCH_RESULT_LIMIT)]

    assert "🔎 검색: `마법사족 몬스터`" in text
    assert "조건: 마법사족 몬스터" in text
    #: 🔴 총 건수와 **보여 준 건수**를 함께 적는다 — 137장이 전부라고
    #: 믿게 두지 않는다
    assert "검색 결과: 137장 (상위 10장 표시)" in text
    for index, card in enumerate(cards, 1):
        assert format_card_line(card, index) in text
    #: 해석하지 못한 말이 없으면 경고 줄을 붙이지 않는다
    assert "⚠️" not in text
    assert len(text) <= bot.DISCORD_MESSAGE_LIMIT


def test_22_a_search_shorter_than_the_limit_does_not_claim_truncation():
    r"""🟢 §4 — 결과가 상한보다 적으면 "상위 N장 표시" 를 **적지 않는다**."""
    cards = [_FakeCard(1, "카드하나"), _FakeCard(2, "카드둘")]
    agent = _FakeAgent(_FakeParsed(), _FakeResult(cards))
    text = bot.search_message(agent, "아무거나")

    assert "검색 결과: 2장" in text
    assert "상위" not in text


def test_23_zero_results_say_so_and_list_no_card():
    r"""🔴 §5 — **결과 0건**을 그 사실대로 적는다. 카드 줄이 없다."""
    agent = _FakeAgent(_FakeParsed("조건: 레벨 13 몬스터"), _FakeResult([]))
    text = bot.search_message(agent, "레벨 13 몬스터")

    assert "조건에 맞는 카드가 없습니다." in text
    assert "검색 결과:" not in text
    #: 카드 줄(``  1. 이름  [id]``)이 하나도 없다
    assert not [line for line in text.splitlines()
                if re.match(r"^\s*\d+\. ", line)]
    #: 해석은 성공했으므로 해석 실패 안내를 섞지 않는다
    assert "⚠️" not in text
    assert "해석하지 못한" not in text


def test_24_unparsed_terms_are_named_and_marked_as_not_applied():
    r"""🔴 §5 — **해석 실패를 정상 검색처럼 보이게 하지 않는다.**

    ``unknown_terms`` 가 있으면 그 말을 **그대로 적고**, 조건에 넣지
    않았다는 사실을 적는다. 결과가 있어도 마찬가지다 — 결과가 나왔다는
    이유로 해석에 성공한 것처럼 적으면 사용자는 다른 질문의 답을 본다.
    """
    cards = [_FakeCard(7, "카드하나")]
    agent = _FakeAgent(
        _FakeParsed("조건: 마법사족", unknown_terms=("이상한말", "또다른말")),
        _FakeResult(cards, total=40),
    )
    text = bot.search_message(agent, "마법사족 이상한말 또다른말")

    assert "⚠️ 해석하지 못한 말: `이상한말`, `또다른말`" in text
    assert "조건에 넣지 않았습니다" in text
    #: 결과는 결과대로 적는다 — 숨기지 않는다
    assert "검색 결과: 40장" in text


def test_25_zero_results_and_unparsed_terms_are_distinguished():
    r"""🔴 §5 — 두 상황을 **구분**해서 안내한다.

    0건이면서 해석 실패도 있으면, 그것이 원인일 수 있다고 덧붙인다.
    해석은 됐는데 0건인 경우(`test_23`)에는 그 문장이 **없다** — 원인을
    잘못 짚게 만들지 않는다.
    """
    agent = _FakeAgent(_FakeParsed("조건: (없음)", unknown_terms=("알수없는말",)),
                       _FakeResult([]))
    text = bot.search_message(agent, "알수없는말")

    assert "⚠️ 해석하지 못한 말: `알수없는말`" in text
    assert "조건에 맞는 카드가 없습니다." in text
    assert "해석하지 못한 말이 원인일 수 있습니다." in text

    #: 해석이 된 0건에는 그 문장이 없다 — 두 안내가 같지 않다
    plain = bot.search_message(_FakeAgent(_FakeParsed(), _FakeResult([])), "x")
    assert "조건에 맞는 카드가 없습니다." in plain
    assert "원인일 수 있습니다" not in plain
    assert text != plain


def test_26_long_card_names_are_still_clamped_by_the_handler_path():
    r"""🔴 §4 — 건수 제한을 지켜도 길이를 넘을 수 있다. 그때도 보장된다."""
    #: 한 줄 약 251자 × 10줄 — 건수는 상한을 지켰는데 길이가 넘는다
    cards = [_FakeCard(index, "이름" * 120) for index in range(10)]
    service = bot.SearchService(
        builder=lambda: _FakeAgent(_FakeParsed(), _FakeResult(cards, total=99))
    )
    assert service.prepare() is True
    text = service.search_text("아무거나")

    #: 10건만 넣었는데도 2,000자를 넘는 상황이다 — 그래서 길이 보장이 있다
    assert len("\n".join(bot.format_card_line(card, index)
                         for index, card in enumerate(cards, 1))) > 2000
    assert len(text) <= bot.DISCORD_MESSAGE_LIMIT
    assert text.endswith(bot.TRUNCATION_NOTICE)


def test_27_the_repository_is_built_once_and_reused():
    r"""🔴 §3 — **무거운 초기화는 한 번만** 한다.

    ``CardRepository.build()`` 는 이 환경에서 약 3초가 걸리고, 그것은
    Discord 가 첫 응답에 주는 3초와 거의 같다. 명령마다 다시 만들면 매번
    그 값을 치른다. ``on_ready`` 가 재접속으로 다시 불려도 같다.
    """
    built: list[int] = []

    def builder():
        built.append(1)
        return _FakeAgent(_FakeParsed(), _FakeResult([_FakeCard(1, "카드")]))

    service = bot.SearchService(builder=builder)
    assert service.ready is False
    assert service.build_count == 0

    assert service.prepare() is True
    #: on_ready 가 다시 불린 상황
    assert service.prepare() is True
    assert service.prepare() is True
    for _ in range(5):
        service.search_text("카드")

    assert service.build_count == 1
    assert built == [1]
    assert service.ready is True
    assert service.error is None


def test_28_a_failed_initialisation_tells_the_user_instead_of_lying(caplog):
    r"""🔴 §3 — 초기화 실패를 **기록하고 안내한다.** 조용히 0건이 아니다.

    실패했는데 "검색 결과가 없습니다" 를 돌려주면 사용자는 그 카드가
    존재하지 않는다고 믿는다. 그래서 둘을 다른 문구로 분리한다.
    """
    boom = RuntimeError("cards.cdb 를 열 수 없습니다")

    def builder():
        raise boom

    service = bot.SearchService(builder=builder)
    with caplog.at_level(logging.ERROR, logger=bot.LOGGER_NAME):
        assert service.prepare() is False

    #: 예외를 삼키지 않는다 — 기록하고 들고 있는다
    assert service.ready is False
    assert service.error is boom
    assert any("초기화에 실패" in record.getMessage()
               for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)

    #: 사용자에게는 "지금은 할 수 없다" 고 말한다 — 0건과 다른 문구다
    text = service.search_text("마법사족 몬스터")
    assert text == bot.UNAVAILABLE_MESSAGE
    assert "조건에 맞는 카드가 없습니다." not in text
    assert "검색 결과:" not in text

    #: 🔴 실패를 매 명령마다 3초씩 다시 시도하지 않는다
    service.search_text("또 다른 질의")
    assert service.build_count == 1


def test_29_the_search_handler_defers_first_and_runs_off_the_event_loop():
    r"""🔴 §4 — **``defer()`` 가 먼저**, 동기 검색은 ``asyncio.to_thread``.

    두 가지를 실제 핸들러로 확인한다.

    1. ``defer`` 가 검색보다 **먼저** 불린다 — 아니면 3초 제한에 걸려
       상호작용이 만료된다.
    2. 검색이 **이벤트 루프 스레드가 아닌 곳**에서 돈다 — 루프에서 돌리면
       그 시간 동안 ``/ping`` 조차 응답하지 않는다.
    """
    import asyncio
    import threading

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    order: list[str] = []
    sent: list[str] = []
    search_thread: list[int] = []

    class _SlowService:
        def search_text(self, query, limit=bot.SEARCH_RESULT_LIMIT):
            order.append("search")
            search_thread.append(threading.get_ident())
            return f"결과: {query}"

        def prepare(self):  # pragma: no cover - on_ready 전용
            return True

    class _Response:
        def __init__(self):
            self._done = False

        async def defer(self, **kwargs):
            order.append("defer")
            self._done = True

        async def send_message(self, content, **kwargs):  # pragma: no cover
            raise AssertionError("defer 한 뒤에는 followup 으로 보낸다")

    class _Followup:
        async def send(self, content, **kwargs):
            order.append("followup")
            sent.append(content)

    class _Interaction:
        def __init__(self):
            self.response = _Response()
            self.followup = _Followup()

    _client, tree = bot.build_client(dev_guild_id=None, service=_SlowService())
    commands = {command.name: command for command in tree.get_commands()}
    search = commands["search"]
    #: 명령은 ``query`` 하나를 받는다
    assert [parameter.name for parameter in search.parameters] == ["query"]
    assert search.description == bot.SEARCH_DESCRIPTION

    async def run():
        loop_thread = threading.get_ident()
        await search.callback(_Interaction(), "마법사족 몬스터")
        return loop_thread

    loop_thread = asyncio.run(run())

    assert order == ["defer", "search", "followup"]
    assert sent == ["결과: 마법사족 몬스터"]
    #: 🔴 검색은 이벤트 루프에서 돌지 않았다
    assert search_thread and search_thread[0] != loop_thread


def test_30_on_ready_prepares_the_cards_in_a_thread_and_then_syncs():
    r"""🔴 §3 — ``on_ready`` 가 카드 데이터를 **한 번** 준비한 뒤 동기화한다.

    준비가 실패해도 ``on_ready`` 는 죽지 않고 동기화를 계속한다 — 죽으면
    ``/ping`` 까지 등록되지 않는다.
    """
    import asyncio
    import threading

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    calls: list[str] = []
    prepare_thread: list[int] = []

    class _FailingService:
        build_count = 0

        def prepare(self):
            calls.append("prepare")
            prepare_thread.append(threading.get_ident())
            return False

        def search_text(self, query, limit=bot.SEARCH_RESULT_LIMIT):
            return bot.UNAVAILABLE_MESSAGE

    synced: list[object] = []

    async def fake_sync(tree, dev_guild_id):
        calls.append("sync")
        synced.append(dev_guild_id)
        return 2

    client, _tree = bot.build_client(dev_guild_id=None,
                                     service=_FailingService())

    original = bot.sync_commands
    bot.sync_commands = fake_sync
    try:
        handler = client.on_ready

        async def run():
            loop_thread = threading.get_ident()
            await handler()
            return loop_thread

        loop_thread = asyncio.run(run())
    finally:
        bot.sync_commands = original

    assert calls == ["prepare", "sync"]
    assert synced == [None]
    #: 🔴 3초짜리 준비를 이벤트 루프에서 하지 않았다 — 하면 하트비트가 멈춘다
    assert prepare_thread and prepare_thread[0] != loop_thread


@requires_official_db
def test_31_a_real_search_stays_inside_the_discord_limits():
    r"""🟢 §2 / §4 — **실제 데이터**로 돌려 건수·길이 보장을 확인한다.

    가짜 결과로는 "우리가 적은 문구가 2,000자 안에 든다" 만 알 수 있고
    "실제 카드 이름으로도 그런가" 는 알 수 없다. 여기서는 실제
    :class:`~app.main.DeckAgent` 를 만들어(약 3초) 확인한다.
    """
    service = bot.SearchService()
    assert service.prepare() is True
    assert service.build_count == 1

    for query in ("마법사족 몬스터", "레벨 4 화염 속성", "링크 2 몬스터",
                  "오르페골"):
        text = service.search_text(query)
        assert text != bot.UNAVAILABLE_MESSAGE, query
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT, (query, len(text))
        card_lines = [line for line in text.splitlines()
                      if line.strip().startswith(tuple("0123456789"))
                      and line.strip()[0].isdigit() and ". " in line]
        assert card_lines, query
        assert len(card_lines) <= bot.SEARCH_RESULT_LIMIT, (query,
                                                            len(card_lines))

    #: 명령을 여러 번 돌려도 데이터는 한 번만 만들었다
    assert service.build_count == 1


# ===========================================================================
# Phase 5-C — ``/deck``
# ===========================================================================
def _draft(main_slots=1, extra_slots=1, *, resolved=("ORCUST",),
           unresolved=(), notes=("기록 한 줄",)):
    """
    **실제** :mod:`deck.model` 타입으로 초안을 만든다.

    🔴 가짜 모델을 만들지 않는다. 어댑터가 읽는 속성(``copies`` ·
    ``role.describe_ko()`` 등)이 진짜와 다르면 테스트가 통과해도 봇은
    깨진다.
    """
    from deck.model import CardRole, DeckDraft, DeckSlot

    draft = DeckDraft(
        requested_themes=list(resolved) + list(unresolved),
        resolved_themes=list(resolved),
        unresolved_themes=list(unresolved),
        notes=list(notes),
    )
    for index in range(main_slots):
        draft.main.append(DeckSlot(
            card_id=1000 + index, name=f"메인카드{index}", copies=2,
            role=CardRole.THEME_CORE, reason="ORCUST 카드군의 몬스터입니다",
            theme="ORCUST"))
    for index in range(extra_slots):
        draft.extra.append(DeckSlot(
            card_id=2000 + index, name=f"엑스트라카드{index}", copies=1,
            role=CardRole.EXTRA_DECK,
            reason="ORCUST 카드군이고 엑스트라 덱 카드입니다", theme="ORCUST"))
    return draft


class _SpyBuilder:
    """``DeckBuilder`` 자리에 끼워 **무엇이 전달됐는지** 본다."""

    seen: list = []

    def __init__(self, repository, search_engine=None):
        type(self).seen.append(("init", repository))

    def build(self, request):
        type(self).seen.append(("build", request))
        return _draft()


class _StubAgent:
    """
    ``repository`` 와 ``search_korean`` 을 가진 가짜 에이전트.

    덱 빌더가 요구하는 것은 ``repository`` 하나이고, ``/search`` 는
    ``search_korean`` 을 부른다 — **에이전트 하나가 두 명령을 다 받는다**
    는 사실을 ``test_42`` 가 이것으로 확인한다.
    """

    def __init__(self):
        self.repository = object()

    def search_korean(self, query, limit=None):
        return (_FakeParsed(), _FakeResult([_FakeCard(1, "카드하나")]))


def test_32_the_deck_command_is_registered_with_one_request_argument():
    r"""🟢 §6-1 — ``/deck`` 이 실제 트리에 등록되고 인자가 하나다.

    인자를 ``request`` 문자열 하나로 둔 이유는
    :func:`~deck.request.parse_deck_request` 가 테마·목표·제외를 **그 문장
    하나에서** 읽기 때문이다. 별도 인자를 만들면 파서를 우회하는 두 번째
    입력 경로가 생긴다.
    """
    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    _client, tree = bot.build_client(dev_guild_id=None, service=object())
    commands = {command.name: command for command in tree.get_commands()}
    assert set(commands) == {"ping", "search", "deck", "combo"}

    deck = commands["deck"]
    assert deck.description == bot.DECK_DESCRIPTION
    assert [parameter.name for parameter in deck.parameters] == ["request"]
    #: 🔴 비워 둘 수 없다 — 빈 요청으로 덱을 만들지 않는다
    assert [parameter.required for parameter in deck.parameters] == [True]


def test_33_a_valid_request_reaches_the_existing_deck_builder(monkeypatch):
    r"""🔴 §6-2 — 파싱된 요청이 **기존 빌더에 그대로** 전달된다.

    새로 만들지 않고 기존 것을 부르는지 확인한다: 어댑터가 받은 문장이
    :func:`~deck.request.parse_deck_request` 를 거쳐
    :meth:`~deck.builder.DeckBuilder.build` 에 도달하고, 저장소는 에이전트의
    것 그대로여야 한다.
    """
    import deck.builder

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _SpyBuilder)

    agent = _StubAgent()
    texts = bot.deck_messages(
        agent, "오르페골 + K9으로 덱을 짜 줘. 초동 안정성을 우선하고 패트랩도 충분히")

    kinds = [kind for kind, _ in _SpyBuilder.seen]
    assert kinds == ["init", "build"], kinds
    #: 🔴 저장소를 새로 만들지 않고 에이전트의 것을 넘긴다
    assert _SpyBuilder.seen[0][1] is agent.repository

    request = _SpyBuilder.seen[1][1]
    from deck.request import DeckGoal, DeckRequest

    assert isinstance(request, DeckRequest)
    assert request.themes == ["오르페골", "K9"], request.themes
    assert DeckGoal.OPENING_STABILITY in request.goals
    assert DeckGoal.HAND_TRAP_WEIGHT in request.goals
    assert texts and all(len(text) <= bot.DISCORD_MESSAGE_LIMIT
                         for text in texts)


def test_34_the_draft_becomes_a_readable_discord_answer(monkeypatch):
    r"""🟢 §6-3 — 초안이 **빌더가 준 정보만으로** 메시지가 된다."""
    import deck.builder

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _SpyBuilder)

    text = "\n".join(bot.deck_messages(_StubAgent(), "오르페골 덱 짜줘"))

    assert "🃏 덱 요청: `오르페골 덱 짜줘`" in text
    #: 장수와 종류를 함께 적는다
    assert "**메인 2장** (종류 1)" in text
    assert "**엑스트라 1장** (종류 1)" in text
    assert "해석된 카드군: ORCUST" in text
    #: 카드별 매수·이름·ID·역할
    assert "2x 메인카드0  [1000]  · 테마 카드" in text
    assert "1x 엑스트라카드0  [2000]  · 엑스트라 덱" in text
    #: 🔴 빌더가 적은 채택 근거를 버리지 않는다
    assert "ORCUST 카드군의 몬스터입니다 (1종류)" in text
    #: 🔴 구성 기록도 버리지 않는다
    assert "기록 한 줄" in text
    #: 검증 결과와 '검증 불가 ≠ 통과' 경고
    assert "**[덱 규격 검증]**" in text
    assert "검증 불가 항목은 **통과가 아닙니다.**" in text
    assert "금지·제한" in text

    #: 🔴 초안이 커지면 **나눠 보내고 버리지 않는다.** 한 메시지에 억지로
    #: 담으면 뒤쪽 카드가 사라지는데, 그것은 그 덱이 아니다.
    class _BigBuilder(_SpyBuilder):
        def build(self, request):
            return _draft(main_slots=30, extra_slots=15)

    monkeypatch.setattr(deck.builder, "DeckBuilder", _BigBuilder)
    texts = bot.deck_messages(_StubAgent(), "오르페골 덱 짜줘")
    assert len(texts) > 1, len(texts)
    for message in texts:
        assert len(message) <= bot.DISCORD_MESSAGE_LIMIT, len(message)
    big = "\n".join(texts)
    assert bot.TRUNCATION_NOTICE.strip() not in big
    assert "보내지 못했습니다" not in big
    #: 카드 45종류가 하나도 빠지지 않았다
    for index in range(30):
        assert f"메인카드{index}  [{1000 + index}]" in big, index
    for index in range(15):
        assert f"엑스트라카드{index}  [{2000 + index}]" in big, index


def test_35_an_unreadable_request_builds_no_deck_and_explains_how(monkeypatch):
    r"""🔴 §6-4 — 테마도 목표도 못 읽으면 **덱을 만들지 않는다.**

    CLI 도 같은 자리에서 멈춘다 (``cmd_deck`` 이 ``is_empty`` 에 종료 코드
    1). 빌더를 부르지 않는 것까지 확인한다 — 부르면 쓸모없는 덱이 나온다.
    """
    import deck.builder

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _SpyBuilder)

    for bad in ("덱", "", "   "):
        texts = bot.deck_messages(_StubAgent(), bad)
        assert len(texts) == 1, (bad, len(texts))
        text = texts[0]
        assert "덱을 만들지 않았습니다" in text, bad
        assert "해석하지 못했습니다" in text, bad
        #: 어떻게 적어야 하는지 알려 준다
        assert "오르페골 덱 짜줘" in text, bad
        assert "초동 안정성" in text, bad
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT

    #: 🔴 빌더를 아예 부르지 않았다
    assert _SpyBuilder.seen == []


def test_36_a_theme_that_resolves_to_nothing_sends_no_deck(monkeypatch):
    r"""🔴 §6-4 — 카드군으로 **하나도** 해석되지 않으면 덱을 보내지 않는다.

    빌더는 이때도 덱을 돌려준다. 실측: "존재하지않는테마 덱" 이 테마 밖
    보강 카드 20종 40장을 낸다. 그것은 요청한 테마와 아무 관계가 없는
    덱이고, Discord 에서 보내면 사용자는 그 테마의 덱을 받았다고 믿는다.

    🔴 ``deck/`` 을 고쳐서 막지 않는다 — 빌더의 계약은 그대로 두고, 보여
    줄지만 어댑터에서 정한다.
    """
    import deck.builder

    class _UnresolvedBuilder(_SpyBuilder):
        def build(self, request):
            type(self).seen.append(("build", request))
            return _draft(main_slots=20, resolved=(),
                          unresolved=("존재하지않는테마",))

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _UnresolvedBuilder)

    texts = bot.deck_messages(_StubAgent(), "존재하지않는테마 덱")
    assert len(texts) == 1
    text = texts[0]
    assert "해석하지 못했습니다: `존재하지않는테마`" in text
    assert "덱을 보내지 않습니다" in text
    #: 🔴 덱 목록이 하나도 없다
    assert "**[메인 덱]**" not in text
    assert "메인카드0" not in text
    #: 빌더는 불렀다 — 해석 실패를 알아내려면 불러야 한다
    assert [kind for kind, _ in _SpyBuilder.seen] == ["init", "build"]


def test_37_a_partly_resolved_theme_warns_first_and_still_sends(monkeypatch):
    r"""🟢 §6-4 — 일부만 해석되면 **실패한 테마를 앞에 적고** 덱은 보낸다.

    해석된 테마가 하나라도 있으면 그 덱은 요청과 관계가 있다. 그래서
    보내되, 빠진 테마를 묻히지 않게 맨 앞에 적는다.
    """
    import deck.builder

    class _PartialBuilder(_SpyBuilder):
        def build(self, request):
            type(self).seen.append(("build", request))
            return _draft(main_slots=3, resolved=("ORCUST",),
                          unresolved=("존재하지않는테마",))

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _PartialBuilder)

    texts = bot.deck_messages(_StubAgent(), "오르페골 + 존재하지않는테마 덱")
    text = "\n".join(texts)
    assert "해석하지 못한 테마: `존재하지않는테마`" in text
    assert "이 테마에서 가져온 카드는 없습니다" in text
    #: 덱은 보낸다
    assert "**[메인 덱]**" in text
    assert "해석된 카드군: ORCUST" in text
    #: 경고가 덱 목록보다 앞이다
    assert texts[0].index("해석하지 못한 테마") < texts[0].index("**[메인 덱]**")


def test_38_a_builder_crash_does_not_take_the_bot_down(monkeypatch, caplog):
    r"""🔴 §6-5 — 빌더가 예외를 던져도 **봇이 죽지 않는다.**

    핸들러에서 예외가 올라가면 discord.py 가 그 상호작용을 실패로 끝내고
    사용자는 "애플리케이션이 응답하지 않습니다" 만 본다. 그리고 🔴 **예외
    내용을 사용자에게 보내지 않는다** — 경로와 내부 구조가 드러난다.
    """
    import deck.builder

    boom = RuntimeError("내부 경로 /home/secret/cards.cdb 가 깨졌습니다")

    class _ExplodingBuilder(_SpyBuilder):
        def build(self, request):
            raise boom

    monkeypatch.setattr(deck.builder, "DeckBuilder", _ExplodingBuilder)

    service = bot.SearchService(builder=lambda: _StubAgent())
    assert service.prepare() is True
    with caplog.at_level(logging.ERROR, logger=bot.LOGGER_NAME):
        texts = service.deck_texts("오르페골 덱 짜줘")

    assert texts == [bot.DECK_ERROR_MESSAGE]
    #: 스택은 로그에 남는다
    assert any(record.exc_info for record in caplog.records)
    assert any("덱 생성에 실패" in record.getMessage()
               for record in caplog.records)
    #: 🔴 내부 경로가 사용자 응답에 없다
    assert "/home/secret" not in texts[0]
    assert str(boom) not in texts[0]


def test_39_deck_is_unavailable_but_explained_before_the_cards_are_ready():
    r"""🔴 §6-5 — 카드 데이터가 없으면 ``/deck`` 도 **안내 문구**를 돌려준다.

    ``/search`` 와 **다른 문구**를 쓴다. 사용자가 무엇을 못 하는지 알아야
    한다.
    """
    service = bot.SearchService(builder=lambda: (_ for _ in ()).throw(
        RuntimeError("초기화 실패")))
    assert service.prepare() is False

    texts = service.deck_texts("오르페골 덱 짜줘")
    assert texts == [bot.DECK_UNAVAILABLE_MESSAGE]
    assert texts[0] != bot.UNAVAILABLE_MESSAGE
    assert "덱을 만들 수 없습니다" in texts[0]
    #: 🔴 실패를 요청마다 다시 빌드하지 않는다
    service.deck_texts("또 다른 요청")
    assert service.build_count == 1


def test_40_pagination_splits_instead_of_dropping_the_rest_of_the_deck():
    r"""🔴 §6-6 — 긴 덱은 **나눠 보낸다.** 각 메시지가 상한 이하다.

    ``clamp_to_discord_limit`` 와 역할이 다르다. 검색 결과는 "상위 몇 건" 이
    원래 의미라 잘라도 되지만, 40장 중 뒤 15장이 사라진 덱은 그 덱이
    아니다.
    """
    #: 한 줄짜리는 그대로 한 메시지
    assert bot.paginate(["짧은 줄"]) == ["짧은 줄"]
    assert bot.paginate([]) == []

    lines = [f"  2x 카드{index:03d}  [{100000 + index}]  · 테마 카드"
             for index in range(200)]
    pages = bot.paginate(lines)

    assert len(pages) > 1
    for page in pages:
        assert len(page) <= bot.DISCORD_MESSAGE_LIMIT, len(page)
    #: 🔴 어느 줄도 쪼개지지 않았고, 하나도 사라지지 않았다
    rebuilt = "\n".join(pages).splitlines()
    assert rebuilt == lines, (len(rebuilt), len(lines))

    #: 메시지 수 상한에 걸리면 **몇 줄을 못 보냈는지 적는다** — 조용히 끊지 않는다
    many = [f"줄 {index}: " + "가" * 180 for index in range(300)]
    capped = bot.paginate(many, max_messages=2)
    assert len(capped) == 2
    for page in capped:
        assert len(page) <= bot.DISCORD_MESSAGE_LIMIT
    assert "보내지 못했습니다" in capped[-1]

    #: 한 줄이 그 자체로 상한을 넘으면 그 줄만 줄이고, 줄인 사실을 적는다
    huge = bot.paginate(["나" * 5000])
    assert len(huge) == 1
    assert len(huge[0]) <= bot.DISCORD_MESSAGE_LIMIT
    assert huge[0].endswith(bot.TRUNCATION_NOTICE)


def test_41_the_deck_handler_defers_first_and_sends_every_message():
    r"""🔴 §5 — ``defer()`` 가 먼저, 동기 작업은 스레드, 메시지는 **전부** 전송."""
    import asyncio
    import threading

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    order: list[str] = []
    sent: list[str] = []
    worker: list[int] = []

    class _Service:
        def deck_texts(self, request_text):
            order.append("deck")
            worker.append(threading.get_ident())
            return ["첫 번째", "두 번째", "세 번째"]

        def prepare(self):  # pragma: no cover - on_ready 전용
            return True

    class _Response:
        async def defer(self, **kwargs):
            order.append("defer")

        async def send_message(self, content, **kwargs):  # pragma: no cover
            raise AssertionError("defer 한 뒤에는 followup 으로 보낸다")

    class _Followup:
        async def send(self, content, **kwargs):
            order.append("send")
            sent.append(content)

    class _Interaction:
        def __init__(self):
            self.response = _Response()
            self.followup = _Followup()

    _client, tree = bot.build_client(dev_guild_id=None, service=_Service())
    deck = {c.name: c for c in tree.get_commands()}["deck"]

    async def run():
        loop_thread = threading.get_ident()
        await deck.callback(_Interaction(), "오르페골 덱 짜줘")
        return loop_thread

    loop_thread = asyncio.run(run())

    assert order == ["defer", "deck", "send", "send", "send"]
    #: 🔴 세 메시지를 다 보냈다 — 한 개만 보내고 나머지를 버리지 않는다
    assert sent == ["첫 번째", "두 번째", "세 번째"]
    assert worker and worker[0] != loop_thread


def test_42_search_and_deck_share_one_card_repository(monkeypatch):
    r"""🔴 §5 — ``/search`` 와 ``/deck`` 이 **같은 카드 데이터**를 쓴다.

    덱 때문에 3~4초짜리 초기화를 한 번 더 하면 두 명령이 서로를 느리게
    만든다.
    """
    import deck.builder

    _SpyBuilder.seen = []
    monkeypatch.setattr(deck.builder, "DeckBuilder", _SpyBuilder)

    built: list[int] = []

    def builder():
        built.append(1)
        return _StubAgent()

    service = bot.SearchService(builder=builder)
    assert service.prepare() is True

    #: 두 명령을 번갈아 돌린다
    assert "검색 결과" in service.search_text("마법사족")
    assert "**[메인 덱]**" in "\n".join(
        service.deck_texts("오르페골 덱 짜줘"))
    assert "검색 결과" in service.search_text("레벨 4")

    #: 🔴 카드 데이터는 한 번만 만들었고, 덱 빌더는 그 저장소를 받았다
    assert service.build_count == 1
    assert built == [1]
    assert _SpyBuilder.seen[0][1] is service.agent.repository


@requires_official_db
def test_43_a_real_deck_request_stays_inside_the_discord_limits():
    r"""🟢 §6-6 — **실제 카드 데이터**로 돌려 길이와 내용을 확인한다.

    가짜 초안으로는 "우리가 적은 틀이 상한에 든다" 만 알 수 있다. 실제
    카드 이름과 실제 카드군 크기로도 그런지는 여기서만 확인된다.
    """
    service = bot.SearchService()
    assert service.prepare() is True

    texts = service.deck_texts("오르페골 덱 짜줘")
    assert 1 <= len(texts) <= bot.DECK_MESSAGE_LIMIT, len(texts)
    for text in texts:
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT, len(text)

    joined = "\n".join(texts)
    #: 🔴 **Phase 5-D 가 이 단정을 고쳤다.** 전에는 ``"**메인 40장**"`` 을
    #: 고정했다. 그 40장은 테마 카드 24장 + ``has_effect_from("HAND")`` 만
    #: 보고 카드 ID 순서로 넣은 16장이었고, 그 16장의 근거가 신뢰할 수
    #: 없다는 것이 Phase 5-D 가 고친 결함이다. 목표를 주지 않은 요청은
    #: 이제 보강하지 않으므로 24장이고, 그 사실과 장수 위반이 응답에
    #: 적힌다 — **약화가 아니라 더 좁은 고정이다**: 아래에서 "보강하지
    #: 않았다" 와 "위반" 을 함께 확인한다.
    assert "**메인 24장**" in joined, joined[:400]
    assert "해석된 카드군: ORCUST" in joined
    assert "오르페골" in joined
    assert "보강하지 않았습니다" in joined
    assert "메인 덱 장수: 위반" in joined
    #: 🔴 근거 없이 넣은 카드를 "패트랩 계열" 로 적지 않는다
    assert "패트랩 계열" not in joined
    #: 역할의 출처를 역할과 따로 적는다
    assert "**[역할의 출처]**" in joined
    #: 🔴 잘렸다는 말이 없다 — 나눠 보냈으므로 버린 것이 없다
    assert bot.TRUNCATION_NOTICE.strip() not in joined
    assert "보내지 못했습니다" not in joined

    #: 해석 실패만 있는 요청은 덱을 보내지 않는다 (실제 데이터로도)
    failed = service.deck_texts("존재하지않는카드군이름 덱")
    assert len(failed) == 1
    assert "덱을 보내지 않습니다" in failed[0]

    #: 덱을 만들어도 카드 데이터는 한 번만 만들었다
    assert service.build_count == 1


# ===========================================================================
# Phase 5-D — ``/combo``
# ===========================================================================
class _SpyPlanner:
    """``ComboPlanner`` 자리에 끼워 **무엇이 전달됐는지** 본다."""

    seen: list = []
    plan_factory = None

    def __init__(self, repository, executable_ids=None):
        type(self).seen.append(("init", repository))

    def plan(self, hand_source, board=(), draft=None):
        type(self).seen.append(("plan", hand_source, list(board), draft))
        factory = type(self).plan_factory
        return factory() if factory else _plan()


def _plan(statuses=("confirmed",), *, stopped=None, unsupported=("절차 하나",),
          manual=("사람이 확인할 것 하나",), hand=(1000,)):
    """
    **실제** :mod:`deck.model` 타입으로 계획을 만든다.

    🔴 가짜 모델을 만들지 않는다. 어댑터가 읽는 속성이 진짜와 다르면
    테스트가 통과해도 봇은 깨진다.
    """
    from deck.model import ComboPlan, PlanStep, StepBasis, StepStatus

    basis_for = {
        "confirmed": StepBasis.ENGINE_EXECUTABLE,
        "conditional": StepBasis.ENGINE_ACTION,
        "unknown": StepBasis.NONE,
        "unsupported": StepBasis.PRINTED_TYPE_ONLY,
    }
    plan = ComboPlan(hand=list(hand), board=[])
    for index, status in enumerate(statuses, start=1):
        plan.steps.append(PlanStep(
            order=index, card_id=1000 + index, card_name=f"카드{index}",
            action=f"걸음 {index} 을 합니다",
            requires=(f"조건 {index}",), expected=f"기대 {index}",
            basis=basis_for[status], status=StepStatus(status),
            note=f"비고 {index}"))
    plan.stopped_reason = stopped
    plan.unsupported.extend(unsupported)
    plan.manual_checks.extend(manual)
    return plan


class _ComboAgent:
    """``repository`` 하나만 가진 가짜 에이전트 — 플래너가 요구하는 전부다."""

    def __init__(self, cards=None):
        self.repository = _ComboRepository(cards or {})


class _ComboRepository:
    def __init__(self, cards):
        self._cards = cards

    def get(self, card_id):
        return self._cards.get(card_id)

    def find_by_exact_name(self, name):
        return [card for card in self._cards.values()
                if card.display_name() == name]


class _ComboCard:
    """``_parse_card_ids`` 와 어댑터가 읽는 속성만 가진 가짜 카드."""

    def __init__(self, card_id, name, hand_ranges=0, activatable=0):
        self.id = card_id
        self._name = name
        self._hand_ranges = hand_ranges
        self._activatable = activatable

    def display_name(self):
        return self._name

    def has_effect_from(self, location, category=None):
        return location.upper() == "HAND" and self._hand_ranges > 0

    @property
    def effects(self):
        from core.card_model import EffectSpec

        blocks = []
        for index in range(self._hand_ranges):
            activatable = index < self._activatable
            blocks.append(EffectSpec(
                index=f"e{index}",
                effect_types=["QUICK_O"] if activatable else ["FIELD"],
                code=None if activatable else "EFFECT_SPSUMMON_PROC",
                ranges=["HAND"]))
        return blocks


def test_44_the_combo_command_is_registered_with_its_four_arguments():
    r"""🟢 §8-1 — ``/combo`` 가 실제 트리에 등록되고 인자가 맞다.

    앞의 셋은 :meth:`~deck.planner.ComboPlanner.plan` 이 **실제로 받는
    것**이다 (``hand_source`` · ``board`` · ``draft``). 플래너가 받지 않는
    입력은 만들지 않았다.

    .. note::
       🔴 **넷째 인자 ``recipe`` 가 Phase 6-T 에서 붙었다** (이름도 맞췄다 —
       숫자를 이름에 적어 두면 숫자가 변할 때 이름이 거짓이 된다).

       이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 그때는 셋이었다.
       6-T 가 **실제 덱 레시피**를 받는 길을 더했고, 그것은 플래너가 아니라
       :func:`~deck.opening.build_opening` 이 받는다.

       🔴 ``deck`` 과 **가르는 것이 요점**이다: ``deck`` 은 자연어 요청이고
       ``DeckBuilder`` 의 **초안**을 만든다 (사용자가 확정한 덱이 아니다).
       그 초안으로 실행 검증하면 "사용자의 덱으로 전개를 검증했다" 가
       거짓이 된다 (6-T §5). 그래서 레시피를 받는 자리를 따로 두었다.

       **하위 호환**: ``recipe`` 는 **마지막 선택 인자**이므로 기존 호출이
       그대로 돈다 (``test_45`` 가 그 경로를 그대로 센다).
    """
    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    _client, tree = bot.build_client(dev_guild_id=None, service=object())
    commands = {command.name: command for command in tree.get_commands()}
    assert set(commands) == {"ping", "search", "deck", "combo"}

    combo = commands["combo"]
    assert combo.description == bot.COMBO_DESCRIPTION
    assert [p.name for p in combo.parameters] == ["hand", "board", "deck",
                                                  "recipe"]
    #: 패는 필수, 나머지는 선택 — 무작위 패 생성이 없으므로 패는 받아야 한다
    assert [p.required for p in combo.parameters] == [True, False, False,
                                                      False]


def test_45_a_valid_hand_reaches_the_existing_combo_planner(monkeypatch):
    r"""🔴 §8-2 · §8-3 — 패가 **기존 플래너에 그대로** 전달된다.

    새 전개 엔진을 만들지 않고 기존 것을 부르는지 확인한다:
    :func:`app.main._parse_card_ids` → :class:`~deck.hand.FixedHand` →
    :meth:`~deck.planner.ComboPlanner.plan`.
    """
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = None
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({
        57835716: _ComboCard(57835716, "오르페골 디베르"),
        21441617: _ComboCard(21441617, "오르페골 스켈레촌"),
    })
    texts = bot.combo_messages(agent, "오르페골 디베르, 21441617")

    kinds = [row[0] for row in _SpyPlanner.seen]
    assert kinds == ["init", "plan"], kinds
    #: 🔴 저장소를 새로 만들지 않고 에이전트의 것을 넘긴다
    assert _SpyPlanner.seen[0][1] is agent.repository

    _kind, hand_source, board, draft = _SpyPlanner.seen[1]
    from deck.hand import FixedHand, HandProvider

    #: 🔴 기존 ``HandProvider`` 경계를 쓴다 — 패를 날 목록으로 넘기지 않는다
    assert isinstance(hand_source, FixedHand), hand_source
    assert isinstance(hand_source, HandProvider)
    #: 이름과 ID 가 섞여도 둘 다 해석된다
    assert hand_source.hand() == [57835716, 21441617]
    assert board == []
    assert draft is None

    assert texts and all(len(text) <= bot.DISCORD_MESSAGE_LIMIT
                         for text in texts)


def test_46_the_plan_becomes_a_discord_answer_with_every_field(monkeypatch):
    r"""🟢 §8-4 — 계획이 **플래너가 준 정보만으로** 메시지가 된다."""
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = lambda: _plan(
        statuses=("confirmed", "conditional", "unknown"),
        stopped="여기서 멈췄습니다",
        unsupported=("특수 소환 (조건 판정 계층 없음)",),
        manual=("사람이 직접 확인할 항목",))
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    text = "\n".join(bot.combo_messages(agent, "1"))

    assert "🌀 전개 요청 — 패: `1`" in text
    assert "해석된 패 1장: 카드하나 [1]" in text
    #: 걸음마다 상태·근거·조건·기대·비고
    assert "**[전개 걸음]** 3걸음" in text
    assert "1. ✔ 걸음 1 을 합니다" in text
    assert "2. ~ 걸음 2 을 합니다" in text
    assert "3. ? 걸음 3 을 합니다" in text
    assert "상태: 확정  ·  근거: 엔진에 효과 실행 구현 있음" in text
    assert "필요: 조건 1" in text
    assert "기대: 기대 1" in text
    assert "비고: 비고 1" in text
    #: 중단 사유 · 미지원 절차 · 사람이 확인할 것
    assert "🔴 중단: 여기서 멈췄습니다" in text
    assert "특수 소환 (조건 판정 계층 없음)" in text
    assert "사람이 직접 확인할 항목" in text


def test_47_no_plan_is_ever_called_verified():
    r"""🔴 §5 — **검증 근거가 없는 전개를 ``VERIFIED`` 로 적지 않는다.**

    :class:`~deck.planner.ComboPlanner` 는 엔진을 실행하지 않는다 — 그
    모듈에 ``Duel`` · ``GameState`` · ``ActionValidator`` 호출이 없고
    ``EFFECT_LIBRARY`` 를 **읽기만** 한다. 그러므로 "실행해서 검증했다" 고
    말할 수 있는 전개가 지금은 하나도 없다.
    """
    import deck.planner

    #: 🔴 플래너가 엔진을 실행하지 않는다는 사실을 AST 로 고정한다
    source = Path(deck.planner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for engine_entry in ("Duel", "GameState", "ActionValidator",
                         "DuelRunner"):
        assert engine_entry not in called, engine_entry

    #: 그래서 판정에 VERIFIED 가 없다
    values = {verdict.value for verdict in bot.ComboVerdict}
    assert "verified" not in values, values
    assert "partially_verified" not in values, values
    assert values == {"grounded_unexecuted", "unverified", "unsupported"}

    #: 가장 높은 판정조차 "실행 검증 안 됨" 을 적는다
    best = bot.ComboVerdict.GROUNDED_UNEXECUTED
    assert "실행 검증 안 됨" in best.describe_ko()
    assert "실제로 돌려 본 것이 아닙니다" in best.detail_ko()


def test_48_the_verdict_follows_the_step_statuses_only():
    r"""🔴 §5 — 판정이 **걸음 상태에서만** 나온다. 카드를 다시 보지 않는다."""
    verdict = bot.combo_verdict

    #: 근거 있는 걸음이 하나라도 있으면 "근거 있음 · 미실행"
    assert verdict(_plan(("confirmed",))) is (
        bot.ComboVerdict.GROUNDED_UNEXECUTED)
    assert verdict(_plan(("unknown", "conditional"))) is (
        bot.ComboVerdict.GROUNDED_UNEXECUTED)

    #: 전부 미확인이면 검증되지 않음 — "전개 후보" 라고도 적지 않는다
    assert verdict(_plan(("unknown",))) is bot.ComboVerdict.UNVERIFIED
    assert verdict(_plan(("unknown", "unknown"))) is (
        bot.ComboVerdict.UNVERIFIED)

    #: 걸음이 없으면 검증되지 않음
    assert verdict(_plan(())) is bot.ComboVerdict.UNVERIFIED

    #: 전부 미지원이면 엔진 미지원
    assert verdict(_plan(("unsupported",))) is bot.ComboVerdict.UNSUPPORTED
    assert verdict(_plan(("unsupported", "unsupported"))) is (
        bot.ComboVerdict.UNSUPPORTED)

    #: 🔴 미지원이 섞였어도 근거 있는 걸음이 있으면 그쪽이 이긴다
    assert verdict(_plan(("unsupported", "confirmed"))) is (
        bot.ComboVerdict.GROUNDED_UNEXECUTED)

    #: 불확실을 숨기지 않는다 — 세 판정 모두 그 사실을 적는다
    for value in bot.ComboVerdict:
        assert "🔴" in value.detail_ko(), value


def test_49_an_unreadable_hand_plans_nothing_and_says_how(monkeypatch):
    r"""🔴 §8-5 · §8-6 — 패를 해석하지 못하면 **계획을 세우지 않는다.**

    플래너를 부르지 않는 것까지 확인한다 — 부르면 빈 패로 쓸모없는 계획이
    나온다. 그리고 🔴 무작위 패 생성이 없다는 사실을 적는다.
    """
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = None
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    for bad in ("", "   ", ",,,"):
        texts = bot.combo_messages(agent, bad)
        assert len(texts) == 1, (bad, len(texts))
        text = texts[0]
        assert "계획을 세우지 않았습니다" in text, bad
        assert "무작위 패 생성은 구현되어 있지 않습니다" in text, bad
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT

    #: 🔴 플래너를 아예 부르지 않았다
    assert _SpyPlanner.seen == []


def test_50_unresolved_card_names_are_named_and_excluded(monkeypatch):
    r"""🔴 §7-1 — 해석하지 못한 입력을 **들어간 것처럼 보이게 하지 않는다.**"""
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = None
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    text = "\n".join(bot.combo_messages(agent, "카드하나, 없는카드"))

    assert "⚠️ 카드를 찾지 못했습니다: `없는카드`" in text
    assert "계획에 넣지 않았습니다" in text
    #: 해석된 카드로는 계획을 세웠다 — 입력 전체를 버리지 않는다
    _kind, hand_source, _board, _draft = _SpyPlanner.seen[1]
    assert hand_source.hand() == [1]

    #: 저장소에 없는 ID 는 그 사실을 적는다 (조용히 빼지 않는다)
    text = "\n".join(bot.combo_messages(agent, "999999999"))
    assert "🔴 저장소에 없는 ID [999999999]" in text


def test_51_an_unsupported_only_plan_is_not_called_a_candidate(monkeypatch):
    r"""🔴 §8-7 — 미구현 규칙뿐이면 **전개 후보라고 적지 않는다.**

    🔴 그리고 "미구현" 과 "불가능" 을 구분한다.

    .. note::
       🔴 **판정 줄의 이름과 자리가 움직였다** (Phase 6-T).

       ``**판정: …**`` → ``**정적 계획의 판정: …**`` 이고, 맨 위가 아니라
       **정적 계획 절 안**에 있다.

       이 시험이 틀린 가정을 갖고 있었던 것이 아니다 — 그때는 ``/combo``
       출력에 정적 계획뿐이었으므로 맨 위의 "판정" 이 그 계획의 판정이었다.
       6-T 가 **실제 엔진 실행 절**을 그 위에 더했고, 그러면 같은 줄이
       "방금 실행한 결과의 판정" 처럼 읽힌다 (6-T §13 "기존 /combo 의
       '확정' 표현이 실제 실행 검증을 의미하는 것처럼 보인다면 출력의
       의미를 바로잡는다").

       ``ComboVerdict`` 자체는 **바꾸지 않았다** — 그것은 옳다. 바꾼 것은
       그 판정이 무엇에 대한 판정인지 이름으로 적은 것이다. 이 시험이
       지키는 사실("미구현뿐이면 후보라고 적지 않는다")은 그대로다.
    """
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = lambda: _plan(
        statuses=("unsupported",),
        unsupported=("특수 소환 (조건 판정 계층이 없어 언제나 UNKNOWN)",
                     "융합 소환 (재료 선택 절차 없음)"))
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    text = "\n".join(bot.combo_messages(agent, "1"))

    assert "**정적 계획의 판정: 엔진 미지원 (계획 불가)**" in text
    assert "미구현이라는 사실이지 불가능이라는 뜻은 아닙니다" in text
    assert "융합 소환 (재료 선택 절차 없음)" in text
    #: 성공으로 보이게 하는 표시가 없다
    assert "✔" not in text
    #: 🔴 그리고 그 판정이 **정적 계획 절 안**에 있다 — 맨 위가 아니다.
    assert text.index("**[아래는 실행하지 않은 정적 계획입니다]**") < text.index(
        "**정적 계획의 판정:")
    #: 🔴 레시피를 주지 않았으므로 실행했다고 적지 않는다.
    assert "엔진이 실제로" not in text


def test_52_a_long_plan_is_split_not_truncated(monkeypatch):
    r"""🔴 §8-8 — 긴 계획은 **나눠 보낸다.** Phase 5-C 의 유틸을 그대로 쓴다."""
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = lambda: _plan(
        statuses=("conditional",) * 40,
        manual=tuple(f"확인할 항목 {index}" for index in range(20)))
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    texts = bot.combo_messages(agent, "1")

    assert len(texts) > 1, len(texts)
    for text in texts:
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT, len(text)
    joined = "\n".join(texts)
    #: 🔴 버린 것이 없다
    assert bot.TRUNCATION_NOTICE.strip() not in joined
    assert "보내지 못했습니다" not in joined
    for index in range(1, 41):
        assert f"{index}. ~ 걸음 {index} 을 합니다" in joined, index


def test_53_a_planner_crash_does_not_take_the_bot_down(monkeypatch, caplog):
    r"""🔴 §8-9 — 플래너가 예외를 던져도 **봇이 죽지 않는다.**

    🔴 예외 내용을 사용자에게 보내지 않는다 — 경로가 드러난다.
    """
    import deck.planner

    boom = RuntimeError("내부 경로 /home/secret/cards.cdb 가 깨졌습니다")

    class _Exploding(_SpyPlanner):
        def plan(self, hand_source, board=(), draft=None):
            raise boom

    monkeypatch.setattr(deck.planner, "ComboPlanner", _Exploding)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    service = bot.SearchService(builder=lambda: agent)
    assert service.prepare() is True
    with caplog.at_level(logging.ERROR, logger=bot.LOGGER_NAME):
        texts = service.combo_texts("1")

    assert texts == [bot.COMBO_ERROR_MESSAGE]
    assert any(record.exc_info for record in caplog.records)
    assert any("전개 계획 생성에 실패" in record.getMessage()
               for record in caplog.records)
    assert "/home/secret" not in texts[0]
    assert str(boom) not in texts[0]


def test_54_combo_is_unavailable_but_explained_before_the_cards_are_ready():
    r"""🔴 §8-9 — 카드 데이터가 없으면 **전용 안내 문구**를 돌려준다."""
    service = bot.SearchService(builder=lambda: (_ for _ in ()).throw(
        RuntimeError("초기화 실패")))
    assert service.prepare() is False

    texts = service.combo_texts("오르페골 디베르")
    assert texts == [bot.COMBO_UNAVAILABLE_MESSAGE]
    #: 세 명령의 안내가 서로 다르다 — 무엇을 못 하는지 알아야 한다
    assert texts[0] != bot.UNAVAILABLE_MESSAGE
    assert texts[0] != bot.DECK_UNAVAILABLE_MESSAGE
    assert "전개 계획을 세울 수 없습니다" in texts[0]
    service.combo_texts("또 다른 패")
    assert service.build_count == 1


def test_55_a_hand_activation_step_is_corrected_from_the_effect_data():
    r"""🔴 §7-1 · §7-3 — 플래너의 **과대 진술을 그대로 전달하지 않는다.**

    ``deck/planner.py`` 의 효과 걸음은 ``has_effect_from("HAND")`` 로
    갈린다. 그 신호는 ``SetRange`` 만 보므로 **특수 소환 절차**에도
    참이 된다 — 실측으로 `/combo hand:펜리르` 가 "패에서 발동하는 효과를
    씁니다" 를 조건부로 적는데, 펜리르의 패 범위 블록은 절차 하나이고
    발동 가능한 효과는 0개다.

    🔴 **플래너를 고치지 않는다** (범위 밖, 구조적 TODO). 대신 출력
    계층이 효과 데이터로 정정한다.
    """
    from deck.model import PlanStep, StepBasis, StepStatus

    def _step(card_id, basis=StepBasis.LUA_PARSED):
        return PlanStep(
            order=1, card_id=card_id, card_name="x",
            action="패에서 발동하는 효과를 씁니다", requires=(),
            expected="(없음)", basis=basis, status=StepStatus.CONDITIONAL)

    #: 패 범위 블록은 있는데 발동 가능한 것이 없다 → 정정한다
    procedure_only = _ComboCard(1, "절차만", hand_ranges=1, activatable=0)
    agent = _ComboAgent({1: procedure_only})
    correction = bot._hand_activation_correction(agent, _step(1))
    assert correction is not None
    assert "발동 가능한 효과가 없습니다" in correction
    assert "그대로 믿지 마세요" in correction

    #: 발동 가능한 블록이 있으면 정정하지 않는다 — 참인 걸음을 깎지 않는다
    real = _ComboCard(2, "발동 가능", hand_ranges=1, activatable=1)
    agent = _ComboAgent({2: real})
    assert bot._hand_activation_correction(agent, _step(2)) is None

    #: 다른 근거 층의 걸음은 건드리지 않는다
    agent = _ComboAgent({1: procedure_only})
    assert bot._hand_activation_correction(
        agent, _step(1, StepBasis.ENGINE_EXECUTABLE)) is None
    #: 저장소에 없는 카드도 건드리지 않는다
    assert bot._hand_activation_correction(agent, _step(99)) is None


def test_56_the_deck_option_actually_runs_the_hand_against_deck_check(
        monkeypatch):
    r"""🟢 §4 — ``deck`` 인자를 주면 플래너가 **그 검증을 실제로** 한다.

    주지 않으면 플래너가 "검증하지 않았습니다" 를 적는다 — 이 저장소가
    이미 그렇게 구분한다. 어댑터는 그 구분을 바꾸지 않고 전달한다.
    """
    import deck.builder
    import deck.planner

    _SpyPlanner.seen = []
    _SpyPlanner.plan_factory = None
    monkeypatch.setattr(deck.planner, "ComboPlanner", _SpyPlanner)

    sentinel = _draft()

    class _Builder:
        def __init__(self, repository, search_engine=None):
            pass

        def build(self, request):
            return sentinel

    monkeypatch.setattr(deck.builder, "DeckBuilder", _Builder)

    agent = _ComboAgent({1: _ComboCard(1, "카드하나")})
    text = "\n".join(bot.combo_messages(agent, "1", "", "오르페골 덱"))

    _kind, _hand, _board, draft = _SpyPlanner.seen[1]
    #: 🔴 덱 초안이 플래너에 **실제로** 전달됐다
    assert draft is sentinel
    assert "덱 초안과 비교: `오르페골 덱`" in text

    #: 덱 요청을 해석하지 못하면 확인하지 않았다고 적고 초안을 넘기지 않는다
    _SpyPlanner.seen = []
    text = "\n".join(bot.combo_messages(agent, "1", "", "덱"))
    _kind, _hand, _board, draft = _SpyPlanner.seen[1]
    assert draft is None
    assert "덱과 맞는지는 확인하지 않았습니다" in text


@requires_official_db
def test_57_a_real_combo_request_shows_only_measured_information():
    r"""🟢 §8 — **실제 카드·실제 엔진 목록**으로 돌려 확인한다.

    가짜 계획으로는 "우리가 적은 틀" 만 알 수 있다. 실제 엔진에 실행
    구현이 등록된 카드가 13장이라는 사실이 출력에 어떻게 드러나는지는
    여기서만 확인된다.
    """
    service = bot.SearchService()
    assert service.prepare() is True

    #: 엔진에 실행 구현이 있는 카드 (욕망의 항아리)
    texts = service.combo_texts("55144522")
    joined = "\n".join(texts)
    assert 1 <= len(texts) <= bot.DECK_MESSAGE_LIMIT
    for text in texts:
        assert len(text) <= bot.DISCORD_MESSAGE_LIMIT, len(text)
    assert "엔진에 효과 실행 구현 있음" in joined
    #: 🔴 그래도 실행 검증은 아니라고 적는다
    assert "실행 검증 안 됨" in joined
    assert "실제로 돌려 본 것이 아닙니다" in joined
    #: 엔진이 지원하지 않는 절차를 그대로 적는다
    assert "특수 소환" in joined
    assert "융합 소환" in joined

    #: 엑스트라 덱 카드만 있는 패 → 미지원
    extra = "\n".join(service.combo_texts("오르페골 갈라테아"))
    assert "엔진 미지원 (계획 불가)" in extra

    #: 저장소에 없는 ID → 검증되지 않음, 그리고 그 사실을 적는다
    unknown = "\n".join(service.combo_texts("999999999"))
    assert "검증되지 않음" in unknown
    assert "저장소에 없는 ID" in unknown

    #: 🔴 실제 데이터에서도 정정이 걸린다 (펜리르 = 특수 소환 절차만)
    fenrir = "\n".join(service.combo_texts("펜리르"))
    assert "🔴 **정정**" in fenrir
    assert "발동 가능한 효과가 없습니다" in fenrir

    #: 명령을 여러 번 돌려도 카드 데이터는 한 번만 만들었다
    assert service.build_count == 1


def test_58_the_combo_handler_defers_first_and_sends_every_message():
    r"""🔴 §6 — ``defer()`` 가 먼저, 동기 작업은 스레드, 메시지는 **전부** 전송.

    🔴 **이 테스트가 처음에는 없었다.** `/deck` 에는 같은 테스트(``test_41``)
    가 있었는데 `/combo` 에는 빼먹었고, 돌연변이 검사에서 ``defer()`` 를
    지우고 ``to_thread`` 를 직접 호출로 바꿨을 때 **60개가 모두 통과**해서
    그 사실이 드러났다. 그래서 추가했다.
    """
    import asyncio
    import threading

    pytest.importorskip("discord", reason="봇 전용 의존성 (requirements-bot.txt)")

    order: list[str] = []
    sent: list[str] = []
    worker: list[int] = []
    received: list[tuple] = []

    class _Service:
        #: 🔴 ``recipe_text`` 가 Phase 6-T 에서 붙었다 — 가짜 구현도 같은
        #: 서명을 받아야 한다. 서명을 안 맞추면 이 시험은 "defer 가 먼저"
        #: 가 아니라 ``TypeError`` 를 본다 (``test_08`` 의 주석과 같은 결).
        def combo_texts(self, hand_text, board_text="", deck_text="",
                        recipe_text=""):
            order.append("combo")
            worker.append(threading.get_ident())
            received.append((hand_text, board_text, deck_text, recipe_text))
            return ["첫 번째", "두 번째", "세 번째"]

        def prepare(self):  # pragma: no cover - on_ready 전용
            return True

    class _Response:
        async def defer(self, **kwargs):
            order.append("defer")

        async def send_message(self, content, **kwargs):  # pragma: no cover
            raise AssertionError("defer 한 뒤에는 followup 으로 보낸다")

    class _Followup:
        async def send(self, content, **kwargs):
            order.append("send")
            sent.append(content)

    class _Interaction:
        def __init__(self):
            self.response = _Response()
            self.followup = _Followup()

    _client, tree = bot.build_client(dev_guild_id=None, service=_Service())
    combo = {c.name: c for c in tree.get_commands()}["combo"]

    async def run():
        loop_thread = threading.get_ident()
        await combo.callback(_Interaction(), "오르페골 디베르",
                             "오르페골 코어", "오르페골 덱")
        return loop_thread

    loop_thread = asyncio.run(run())

    assert order == ["defer", "combo", "send", "send", "send"]
    #: 🔴 세 메시지를 다 보냈다
    assert sent == ["첫 번째", "두 번째", "세 번째"]
    #: 🔴 세 인자가 그대로 전달됐다
    #: 🔴 넷째 칸은 ``recipe`` 이고, 이 호출은 주지 않았으므로 **빈 문자열**
    #: 이다 — "주지 않았다" 가 그대로 전달된다 (Phase 6-T).
    assert received == [("오르페골 디베르", "오르페골 코어", "오르페골 덱", "")]
    #: 🔴 동기 작업이 이벤트 루프 밖에서 돌았다
    assert worker and worker[0] != loop_thread
