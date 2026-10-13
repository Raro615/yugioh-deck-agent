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

    🔴 **이 테스트의 범위를 Phase 5-B 가 정정했다.** Phase 5-A 때는
    ``/ping`` 하나뿐이어서 "어떤 계층도 import 하지 않는다" 가 사실이었고
    그렇게 단정했다. ``/search`` 를 붙이면서 ``app.main`` 의
    ``format_card_line`` 과 ``DeckAgent`` 를 쓰게 됐다 — 검색 로직을
    다시 쓰지 않으려면 그래야 한다.

    **단정을 약하게 바꾼 것이 아니다.** 지키려던 것은 "어댑터가 카드
    계층을 직접 만지지 않는다" 이고, 그것은 그대로다: ``deck`` · ``engine``
    · ``agent`` · ``analysis`` · ``core`` 는 **여전히 하나도 import 하지
    않는다.** 바뀐 것은 허용 목록에 ``app`` 하나가 들어온 것뿐이고, 그것이
    "기존 진입점을 재사용한다" 는 §2 의 요구다.
    """
    tree = ast.parse(Path(bot.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    #: 재사용하는 유일한 계층
    assert "app" in imported, sorted(imported)
    #: 🔴 카드·덱·엔진 계층은 직접 만지지 않는다 (Phase 5-A 와 같다)
    for layer in ("deck", "core", "engine", "agent", "analysis", "rules",
                  "rulings", "sources"):
        assert layer not in imported, (layer, sorted(imported))

    #: 그리고 검색 로직을 다시 쓰지 않았다 — 기존 함수를 부른다
    source = Path(bot.__file__).read_text(encoding="utf-8")
    assert "search_korean(" in source
    assert "format_card_line(" in source
    #: 직접 필터를 만들거나 검색 엔진을 세우지 않는다
    for duplicated in ("SearchFilters(", "CardSearchEngine(",
                       "KoreanQueryParser("):
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
    assert "아직 구현하지 않았다" in source
    #: /deck · /combo 가 실제 명령으로 등록되어 있지 않다
    tree = ast.parse(source)
    registered = {
        kw.value.value
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "name" and isinstance(kw.value, ast.Constant)
    }
    #: 🔴 Phase 5-B 가 ``search`` 를 더했다. ``deck`` · ``combo`` 는
    #: **여전히 등록되지 않았다** — 구현하지 않은 것을 등록하지 않는다.
    assert registered == {"ping", "search"}, registered
    assert "deck" not in registered and "combo" not in registered

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
    #: 🔴 Phase 5-A 에서는 ``["ping"]`` 하나였다. Phase 5-B 가 ``/search`` 를
    #: 실제로 등록했으므로 사실이 바뀌었다 — 목록을 이름 집합으로 고정하고
    #: ``/ping`` 을 이름으로 꺼낸다. 느슨해진 게 아니라 등록 집합을 여전히
    #: 정확히 고정한다 (``/deck``·``/combo`` 가 끼면 실패한다).
    assert set(commands) == {"ping", "search"}
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
