"""
Phase 3-E-19 — ``EVENT_PHASE`` 의 수정자(어느 페이즈인가)가 어디까지 가는가 (감사).

이 Phase 는 **아무 것도 바꾸지 않았다.** 감사 테스트만 더했다.

세 가지가 측정으로 확정되었다
-----------------------------
1. **수정자는 이름의 장식이 아니라 사건 번호의 일부다.** 공식 상수
   (``data/constants/constant.lua``) 에서 ``EVENT_PHASE = 0x1000`` ·
   ``PHASE_END = 0x200`` 이므로 ``EVENT_PHASE+PHASE_END`` 는 **0x1200** 이라는
   별개의 사건 번호다. 서로 다른 **9개 사건 번호**가 모델에서는 이름 **2개**
   (``"EVENT_PHASE"`` · ``"EVENT_PHASE_START"``) 로 합쳐진다.
2. **``EVENT_PHASE`` 단독은 원문에 0건이다.** 1,336개 호출 전부 페이즈 비트를
   달고 있다. 즉 모델의 ``code == "EVENT_PHASE"`` 는 "모든 페이즈" 가 아니라
   **"어느 페이즈인지 적지 못했다"** 를 뜻한다.
3. **그런데 지금 그 값을 읽는 production 경로가 없다.** ``engine/`` · ``agent/``
   어디에도 ``EVENT_PHASE`` · ``PHASE_END`` · ``trigger_events`` 가 없고,
   ``TriggerSpec`` 은 애초에 "어느 페이즈" 를 적을 자리가 없으며, 등록된
   ``TriggerSpec`` 자체가 production 에 **하나도 없다**.

따라서 이 감사의 결론은 **AUDIT ONLY** 다. 수정자 소실은 실재하지만 지금
실행되는 듀얼을 틀리게 만들지 않는다 — 읽는 쪽이 없기 때문이다.

계층을 섞지 않는다
------------------
::

    SetCode(EVENT_PHASE+PHASE_END)     ← 사건 **정체** (스크립트 metadata)
        ↓
    TriggerSpec/TimingPoint            ← 어떤 사건에 반응하는가 (선언)
        ↓
    TriggerCandidate                   ← 후보가 되었는가
        ↓
    ActivationTimingChecker            ← 지금 발동할 수 있는가 (체인 · 우선권)
        ↓
    Chain                              ← 실제 발동

``PhaseChanged`` delta 는 ``from_phase``/``to_phase`` 를 **갖고 있다** — 사건
쪽에는 페이즈가 있다. 없는 것은 **선언 쪽**이다 (``TriggerSpec`` 에 페이즈
필터가 없다). 그래서 이것은 "파서가 정보를 버린다" 하나의 문제가 아니라
**양쪽이 아직 그 질문을 하지 않는다** 는 하나의 사실이다.
"""

import functools
import pathlib
import re

import pytest

import sources.lua_loader as lua_loader
from engine.effect.delta import PhaseChanged
from engine.ids import EffectRef
from engine.trigger import TimingEvent, TimingPoint, TriggerError, TriggerSpec
from engine.vocabulary import Phase
from sources.lua_loader import parse_lua_source

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONSTANTS = PROJECT_ROOT / "data" / "constants" / "constant.lua"

#: 대표 사례 (측정으로 고른 것).
END_PHASE_CARD = 10000000  # e6: EVENT_PHASE+PHASE_END
TWO_PHASES_CARD = 23846921  # e1: +PHASE_END · e2: |PHASE_DRAW — 한 카드 안에 둘
PHASE_START_CARD = 10960419  # e1: EVENT_PHASE_START+PHASE_DRAW · e2: |PHASE_STANDBY

#: 공식 상수에서 실제로 쓰이는 페이즈 비트 이름.
PHASE_BITS = (
    "PHASE_DRAW",
    "PHASE_STANDBY",
    "PHASE_MAIN1",
    "PHASE_BATTLE_START",
    "PHASE_BATTLE_STEP",
    "PHASE_DAMAGE",
    "PHASE_DAMAGE_CAL",
    "PHASE_BATTLE",
    "PHASE_MAIN2",
    "PHASE_END",
)

#: 측정으로 확인된 인자 모양 12개 (Phase 3-E-19 기준). 스크립트가 늘면 **더
#: 생길 수는 있어도 사라지지는 않는다** — 그래서 테스트는 부분집합으로 본다.
MEASURED_SHAPES = frozenset(
    {
        "EVENT_PHASE+PHASE_END",
        "EVENT_PHASE|PHASE_STANDBY",
        "EVENT_PHASE|PHASE_BATTLE",
        "EVENT_PHASE|PHASE_BATTLE_START",
        "EVENT_PHASE+PHASE_BATTLE",
        "EVENT_PHASE+PHASE_STANDBY",
        "EVENT_PHASE|PHASE_DRAW",
        "EVENT_PHASE_START|PHASE_DRAW",
        "EVENT_PHASE_START|PHASE_STANDBY",
        "EVENT_PHASE_START|PHASE_MAIN1",
        "EVENT_PHASE_START+PHASE_DRAW",
        "EVENT_PHASE_START|PHASE_BATTLE_START",
    }
)

SKELETON = """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_F)
\te1:SetCode({arg})
\tc:RegisterEffect(e1)
end
"""


def parsed_code(arg: str) -> str | None:
    """``SetCode(<arg>)`` 하나를 **캐시를 거치지 않고** 파싱한 결과."""
    info = parse_lua_source(1, "c1.lua", SKELETON.format(arg=arg))
    return info.effects[0].code


def script_files() -> list[pathlib.Path]:
    files = sorted(PROJECT_ROOT.glob("c*.lua"))
    if not files:
        pytest.skip("공식 Lua 스크립트가 없습니다")
    return files


@functools.lru_cache(maxsize=1)
def phase_setcode_calls() -> tuple[tuple[str, str, str], ...]:
    """
    전 corpus 에서 **묶인 효과 블록에 붙은** ``SetCode(... EVENT_PHASE ...)``
    호출 전부. ``(파일, 변수, 인자 원문)``.

    파서의 이벤트 루프를 그대로 재현한다 — 파일 전체를 정규식으로 긁으면
    묶이지 않은 변수와 함수마다 재사용되는 ``e1`` 때문에 수가 틀린다
    (Phase 3-E-18 이 E-17 의 숫자를 바로잡은 이유).

    🔴 Phase 3-F-28 정정 — 이 함수도 production 정규식을 **그룹 번호로** 읽고
    있었다. 3-F-28 이 ``local`` 포획 그룹을 추가해 번호가 밀렸으므로 맞추고,
    production 과 같은 흐름이 되도록 블록 주석 제거와 ``_is_card_effect``
    판정을 함께 반영한다.
    """
    out: list[tuple[str, str, str]] = []
    for path in script_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        if "EVENT_PHASE" not in source:
            continue
        source = lua_loader._RE_BLOCK_COMMENT.sub("", source)
        events: list[tuple[int, str, str]] = []
        for m in lua_loader._RE_CREATE_EFFECT.finditer(source):
            if not lua_loader._is_card_effect(source, m.group(1), m.group(2), None):
                continue
            events.append((m.start(), "bind", m.group(2)))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(source):
            if not lua_loader._is_card_effect(
                source, m.group(1), m.group(2), lua_loader._clone_source(m)
            ):
                continue
            events.append((m.start(), "bind", m.group(2)))
        for m in lua_loader._RE_SETTER.finditer(source):
            events.append((m.start(), "set", f"{m.group(1)}|{m.group(2)}|{m.end() - 1}"))
        events.sort(key=lambda e: e[0])
        bound: set[str] = set()
        for _pos, kind, payload in events:
            if kind == "bind":
                bound.add(payload)
                continue
            var, setter, idx = payload.split("|", 2)
            if setter != "Code" or var not in bound:
                continue
            args = lua_loader._extract_call_args(source, int(idx)).strip()
            if "EVENT_PHASE" in args:
                out.append((path.name, var, args))
    #: 같은 전수 순회를 테스트마다 반복하지 않는다 (12,702개 × 4회 → 1회).
    return tuple(out)


# ======================================================================
# §4 — 수정자는 무엇인가 (공식 상수)
# ======================================================================


def test_01_the_modifier_is_part_of_the_event_number_not_a_label():
    """
    **§4 — ``EVENT_PHASE+PHASE_END`` 는 "EVENT_PHASE 에 꼬리말이 붙은 것" 이
    아니라 다른 숫자다.**

    공식 상수 파일이 그렇게 말한다. 이름에서 추측한 것이 아니다.
    """
    text = CONSTANTS.read_text(encoding="utf-8")

    def value_of(name: str) -> int:
        m = re.search(rf"^{name}\s*=\s*(0x[0-9a-fA-F]+|\d+)", text, re.M)
        assert m, name
        return int(m.group(1), 0)

    assert value_of("EVENT_PHASE") == 0x1000
    assert value_of("EVENT_PHASE_START") == 0x2000
    assert value_of("PHASE_END") == 0x200
    assert value_of("PHASE_STANDBY") == 0x2

    #: 더해진 값은 서로 다르다 — 즉 **다른 사건**이다.
    assert value_of("EVENT_PHASE") + value_of("PHASE_END") == 0x1200
    assert value_of("EVENT_PHASE") + value_of("PHASE_STANDBY") == 0x1002
    assert 0x1200 != 0x1002 != value_of("EVENT_PHASE")

    #: ``EVENT_PHASE_START`` 는 "EVENT_PHASE + PHASE_START" 가 아니다 —
    #: **독립된 사건 상수**이고, ``PHASE_START`` 라는 상수는 존재하지 않는다.
    assert not re.search(r"^PHASE_START\s*=", text, re.M)
    assert value_of("EVENT_PHASE_START") != value_of("EVENT_PHASE")


def test_02_the_official_rulebook_treats_each_phase_as_a_distinct_timing():
    """
    **§4 — 규칙 계층에서도 엔드 페이즈와 스탠바이 페이즈는 다른 시점이다.**

    공식 룰북(구조화)이 페이즈마다 별개 항목과 별개 규칙 ID 를 갖는다.
    카드 이름이나 빈도로 추측한 것이 아니다.
    """
    import json

    data = json.loads(
        (PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json").read_text(
            encoding="utf-8"
        )
    )
    by_phase = {p["engine_phase"]: p for p in data["phases"]}
    assert "END" in by_phase and "STANDBY" in by_phase
    assert by_phase["END"]["order"] != by_phase["STANDBY"]["order"]
    assert by_phase["END"]["rules"] != by_phase["STANDBY"]["rules"]
    #: 두 페이즈 모두 "이 페이즈에 발동/해결하는 효과" 를 자기 항목에 적는다.
    assert any("effect" in a.lower() for a in by_phase["END"]["main_actions"])
    assert any("effect" in a.lower() for a in by_phase["STANDBY"]["main_actions"])


# ======================================================================
# §5 — 파서가 무엇을 적는가
# ======================================================================


def test_03_the_parser_keeps_only_the_first_identifier():
    """**§5 — 원인은 ``_RE_EVENT`` 가 첫 이름만 찾는다는 것이다.**"""
    assert parsed_code("EVENT_PHASE+PHASE_END") == "EVENT_PHASE"
    assert parsed_code("EVENT_PHASE|PHASE_STANDBY") == "EVENT_PHASE"
    assert parsed_code("EVENT_PHASE|PHASE_BATTLE") == "EVENT_PHASE"
    #: ``+`` 와 ``|`` 를 구분하지 않는다 — 비트가 겹치지 않으므로 Lua 에서도 같다.
    assert parsed_code("EVENT_PHASE+PHASE_STANDBY") == parsed_code(
        "EVENT_PHASE|PHASE_STANDBY"
    )
    #: ``EVENT_PHASE_START`` 는 이름이 더 길어서 **온전히** 읽힌다.
    assert parsed_code("EVENT_PHASE_START|PHASE_DRAW") == "EVENT_PHASE_START"
    #: 그래도 어느 페이즈인지는 역시 사라진다.
    assert parsed_code("EVENT_PHASE_START|PHASE_DRAW") == parsed_code(
        "EVENT_PHASE_START|PHASE_MAIN1"
    )


def test_04_the_modifier_survives_nowhere_in_the_model():
    """
    **§8 — 수정자가 모델의 다른 필드에 남는지 전부 확인한다 — 남지 않는다.**

    ``trigger_events`` 도 ``EVENT_*`` 이름만 긁으므로 같은 손실을 그대로 갖고,
    게다가 **중복을 지운다** (``_strip_prefix``) — 한 카드가 엔드와 드로우에
    각각 유발해도 목록에는 ``"EVENT_PHASE"`` 하나만 남는다.
    """
    source = SKELETON.format(arg="EVENT_PHASE+PHASE_END")
    info = parse_lua_source(1, "c1.lua", source)
    spec = info.effects[0]

    collected = (
        tuple(info.trigger_events)
        + tuple(info.effect_codes)
        + tuple(info.locations)
        + tuple(info.categories)
        + tuple(spec.effect_types)
        + tuple(spec.ranges)
        + tuple(spec.target_ranges)
        + tuple(spec.categories)
        + tuple(spec.properties)
        + (spec.code or "", spec.count_limit or "")
    )
    assert not [x for x in collected if x.startswith("PHASE_")], collected
    assert info.trigger_events == ["EVENT_PHASE"]

    #: 원문에는 남아 있다 — **정보가 파괴된 것이 아니라 모델에 올라오지 않는다.**
    assert "PHASE_END" in source


def test_05_the_same_token_is_also_used_for_something_that_is_not_a_trigger():
    """
    **§3-F — ``PHASE_*`` 는 유발 타이밍 전용 토큰이 아니다.**

    ``SetReset(RESET_PHASE|PHASE_END)`` 는 "엔드 페이즈까지 지속" 이라는
    **리셋 시점**이고 유발이 아니다. 전 corpus 에서 ``SetCode`` 보다
    ``SetReset`` 쪽이 훨씬 많다 (측정: Reset 4,269 · Condition 55 ·
    Operation 7 · Code 1,336). 그래서 "PHASE 가 보이니 페이즈 유발" 로 읽으면
    틀린다.
    """
    info = parse_lua_source(
        1,
        "c1.lua",
        """
local s,id=GetID()
function s.initial_effect(c)
\tlocal e1=Effect.CreateEffect(c)
\te1:SetType(EFFECT_TYPE_SINGLE)
\te1:SetCode(EFFECT_UPDATE_ATTACK)
\te1:SetReset(RESET_EVENT|RESETS_STANDARD|RESET_PHASE|PHASE_END)
\tc:RegisterEffect(e1)
end
""",
    )
    spec = info.effects[0]
    #: 리셋 시점은 ``code`` 와 아무 상관이 없고, 모델에 아예 담기지 않는다.
    assert spec.code == "EFFECT_UPDATE_ATTACK"
    assert "PHASE" not in str(spec.ranges) + str(spec.properties)
    assert info.trigger_events == []


# ======================================================================
# §6 — corpus 전수 측정
# ======================================================================


@pytest.mark.real_card
def test_06_bare_event_phase_never_appears_in_the_official_scripts():
    """
    **§6 — ``EVENT_PHASE`` 단독 사용은 0건이다 (전수).**

    그러므로 모델의 ``"EVENT_PHASE"`` 는 **원문에 없는 값**이다. 이 값을
    "모든 페이즈에 유발" 로 읽으면, 원문이 한 번도 말하지 않은 것을 말하는
    셈이 된다.
    """
    calls = phase_setcode_calls()
    assert calls, "측정 대상이 사라졌다"

    bare = [c for c in calls if c[2] in ("EVENT_PHASE", "EVENT_PHASE_START")]
    assert bare == [], bare[:5]

    #: 호출 전부가 페이즈 비트를 하나 이상 달고 있다.
    without_bit = [
        c for c in calls if not any(re.search(rf"\b{b}\b", c[2]) for b in PHASE_BITS)
    ]
    assert without_bit == [], without_bit[:5]


@pytest.mark.real_card
def test_07_nine_distinct_event_numbers_collapse_into_two_names():
    """
    **§6 — 인자 모양은 12개, 사건 번호는 9개, 모델의 이름은 2개다.**

    (``+`` 와 ``|`` 는 같은 값이므로 모양 12개가 번호 9개가 된다.)
    """
    calls = phase_setcode_calls()
    shapes = {c[2] for c in calls}
    assert MEASURED_SHAPES <= shapes, sorted(MEASURED_SHAPES - shapes)

    def number(shape: str) -> tuple[str, frozenset[str]]:
        base = "EVENT_PHASE_START" if "EVENT_PHASE_START" in shape else "EVENT_PHASE"
        bits = frozenset(b for b in PHASE_BITS if re.search(rf"\b{b}\b", shape))
        return base, bits

    assert len({number(s) for s in shapes}) >= 9

    #: **어느 모양이 들어와도** 모델의 이름은 둘뿐이다 — 이것이 collapse 다.
    codes = {parsed_code(s) for s in shapes}
    assert codes == {"EVENT_PHASE", "EVENT_PHASE_START"}, codes


@pytest.mark.real_card
def test_08_the_corpus_counts_are_what_the_report_says():
    """
    **§6 — 보고서에 적은 수를 테스트가 다시 센다.** (고정이 아니라 재현이다.)
    """
    calls = phase_setcode_calls()
    assert len(calls) >= 1336, len(calls)

    counts: dict[str, int] = {}
    for _file, _var, shape in calls:
        counts[shape] = counts.get(shape, 0) + 1
    assert counts["EVENT_PHASE+PHASE_END"] >= 751
    assert counts["EVENT_PHASE|PHASE_STANDBY"] >= 394
    assert counts["EVENT_PHASE|PHASE_BATTLE"] >= 131

    #: ``EVENT_PHASE_START`` 계열은 드물다 (측정 10건).
    start = [c for c in calls if "EVENT_PHASE_START" in c[2]]
    assert len(start) >= 10
    assert len(start) * 50 < len(calls), "희귀하다는 전제가 깨졌다"


@pytest.mark.real_card
def test_09_one_card_can_hold_two_phase_triggers_that_become_identical():
    """
    **§7-E — 수정자가 "이론적으로" 문제가 되는 자리는 여기다.**

    같은 카드가 서로 다른 페이즈에 유발하는 효과를 둘 갖고 있으면, 모델에서
    두 ``code`` 가 **글자까지 같아진다.** 전 corpus 에서 그런 카드가 55장이다.
    """
    cards: dict[str, set[str]] = {}
    for file_name, _var, shape in phase_setcode_calls():
        cards.setdefault(file_name, set()).add(shape)
    mixed = {f: s for f, s in cards.items() if len(s) > 1}
    assert len(mixed) >= 55, len(mixed)
    assert f"c{TWO_PHASES_CARD}.lua" in mixed

    source = (PROJECT_ROOT / f"c{TWO_PHASES_CARD}.lua").read_text(encoding="utf-8")
    assert "EVENT_PHASE+PHASE_END" in source
    assert "EVENT_PHASE|PHASE_DRAW" in source

    info = parse_lua_source(TWO_PHASES_CARD, f"c{TWO_PHASES_CARD}.lua", source)
    phase_specs = [s for s in info.effects if s.code == "EVENT_PHASE"]
    assert len(phase_specs) == 2
    #: 서로 다른 시점인데 값이 같다. 구분하려면 **ordinal 밖의 정보**가 필요하다.
    assert phase_specs[0].code == phase_specs[1].code
    #: 파일 단위 목록은 중복까지 지운다.
    assert info.trigger_events.count("EVENT_PHASE") == 1


# ======================================================================
# §8 · §10 — production Engine 이 이 값을 읽는가
# ======================================================================

PRODUCTION_DIRS = ("engine", "agent")


def production_sources() -> list[tuple[pathlib.Path, str]]:
    out = []
    for name in PRODUCTION_DIRS:
        for path in sorted((PROJECT_ROOT / name).rglob("*.py")):
            out.append((path, path.read_text(encoding="utf-8")))
    return out


#: 6-E 가 설명 안에서 이 이름을 **인용**하는 유일한 파일.
#:
#: .. note::
#:    3-E-19 당시에는 ``engine/`` · ``agent/`` 어디에도 이 이름이 **글자로도**
#:    없었고, 그 사실을 그대로 단정했다. 6-E 가 사건 코드 → 시점 컴파일러를
#:    만들면서 ``EVENT_PHASE`` 를 **의도적으로 번역하지 않는다**는 결정을
#:    내렸고, 그 까닭(한정자가 파서에서 사라지므로 어느 페이즈인지 알 수 없다)
#:    을 그 파일 docstring 에 적었다.
#:
#:    즉 이 감사가 금지하려던 것("그 값을 읽는 코드" · "나중에 쓰려고 적어 둔
#:    자리") 은 여전히 0 이고, 늘어난 것은 **거부 이유를 적은 산문**뿐이다.
#:    ``declared_types`` 때(6-E §5) 와 달리 **이름을 바꿀 수 없다** — 공식 상수
#:    자신의 이름이기 때문이다. 그래서 설명을 지우는 대신 이 감사가 산문과
#:    코드를 구분하게 고쳤다 (3-E-44 가 세운 규칙: 글자가 아니라 AST 를 센다).
#:    구분이 없으면 "거부했다고 적은 것" 과 "읽는다" 가 같은 위반으로 보인다.
PROSE_ONLY_MENTION = "engine/trigger_compiler.py"


def code_mentions(path: pathlib.Path, text: str, token: str) -> list[int]:
    """
    `token` 이 **코드로** 등장하는 줄 번호. 주석과 docstring 은 세지 않는다.

    식별자(NAME) 와 **docstring 이 아닌** 문자열 리터럴만 코드로 본다 —
    ``EVENT_TIMING["EVENT_PHASE"]`` 같은 조회도 잡힌다.
    """
    import ast
    import io
    import tokenize

    tree = ast.parse(text)
    docstrings: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                docstrings.add((first.value.lineno, first.value.col_offset))

    hits: list[int] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start in docstrings:
            continue
        if tok.type not in (tokenize.NAME, tokenize.STRING):
            continue
        if token in tok.string:
            hits.append(tok.start[0])
    return hits


def test_10_no_production_module_mentions_event_phase_or_its_modifiers():
    """
    **§8 — ``engine/`` · ``agent/`` 어디에도 그 이름을 읽는 코드가 없다.**

    읽는 코드가 없을 뿐 아니라 "나중에 쓰려고 적어 둔 자리" 도 없다. 단
    ``engine/trigger_compiler.py`` 의 **거부 이유 산문**은 예외다
    (``PROSE_ONLY_MENTION`` 주석 참조) — 그 파일에서도 **코드 자리는 0** 임을
    아래에서 따로 확인한다.
    """
    tokens = ("EVENT_PHASE", "PHASE_END", "PHASE_START", "trigger_events")
    prose_only_seen = False
    for path, text in production_sources():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        for token in tokens:
            if token not in text:
                continue
            assert relative == PROSE_ONLY_MENTION, (relative, token)
            prose_only_seen = True
            #: 산문일 뿐 코드가 아니다 — 읽지도, 자리를 비워 두지도 않았다.
            assert code_mentions(path, text, token) == [], (relative, token)

    #: 예외가 **실재**하는지도 단정한다. 산문이 사라졌다면 이 핀의 설명이
    #: 낡은 것이므로 그때도 발화해야 한다.
    assert prose_only_seen

    #: 세는 쪽이 멀쩡한지 확인한다 — 코드 자리를 실제로 집어낼 수 있어야
    #: "코드 0" 이 의미를 갖는다 (고의 위반).
    probe = pathlib.Path("probe.py")
    assert code_mentions(probe, 'x = EVENT_PHASE\n', "EVENT_PHASE") == [1]
    assert code_mentions(probe, 'x = T["EVENT_PHASE"]\n', "EVENT_PHASE") == [1]
    assert code_mentions(probe, '# EVENT_PHASE\n', "EVENT_PHASE") == []
    assert code_mentions(probe, '"""EVENT_PHASE"""\n', "EVENT_PHASE") == []


def test_11_trigger_spec_cannot_express_which_phase():
    """
    **§8 — 선언 쪽에 페이즈를 적을 자리가 없다.**

    ``TriggerSpec`` 의 필터는 ``operations`` · ``from_zones`` · ``to_zones``
    뿐이고, 그 셋은 ``CARD_MOVED`` 전용이다 (``__post_init__`` 가 막는다).
    그래서 ``PHASE_CHANGED`` 선언은 **모든 페이즈 전이에 반응한다.**

    즉 파서가 수정자를 보존했어도 **지금은 넣을 곳이 없다.** 이것이 이 감사가
    "파서 버그" 라고 부르지 않는 이유다.
    """
    fields = set(TriggerSpec.__dataclass_fields__)
    assert "point" in fields
    assert not [f for f in fields if "phase" in f.lower()]

    spec = TriggerSpec(effect_ref=EffectRef(1, 0), point=TimingPoint.PHASE_CHANGED)

    def changed(to_phase: Phase) -> TimingEvent:
        return TimingEvent.from_delta(
            PhaseChanged(
                from_turn=1,
                from_player=0,
                from_phase=Phase.MAIN1,
                to_turn=1,
                to_player=0,
                to_phase=to_phase,
            )
        )

    #: 사건 쪽에는 페이즈가 **있다**.
    assert changed(Phase.END).delta.to_phase is Phase.END
    #: 그런데 선언은 둘을 구분하지 못한다.
    assert spec.matches(changed(Phase.END))
    assert spec.matches(changed(Phase.STANDBY))

    #: 카드 이동용 필터를 페이즈 사건에 걸려고 하면 거부한다 — 우회로도 없다.
    with pytest.raises(TriggerError):
        TriggerSpec(
            effect_ref=EffectRef(1, 0),
            point=TimingPoint.PHASE_CHANGED,
            to_zones=frozenset(),
        )


def test_12_no_trigger_spec_is_registered_in_production():
    """
    **§8 — 등록된 선언이 production 에 하나도 없다** (ADR-006: 손으로 등록).

    그러므로 ``PHASE_CHANGED`` 후보가 지금 만들어질 수 있는 경로가 없다.

    .. note::
       3-E-19 당시 production 에는 ``TriggerSpec(`` 생성 자리가 **하나도**
       없었다 (ADR-006: 손으로 등록). 6-E 가 ``engine/trigger_compiler.py``
       하나를 만들었다. **그래도 이 감사의 결론은 바뀌지 않는다** — 그
       컴파일러가 선언을 만드는 것은 ``EVENT_TIMING`` 표에 있는 사건 코드
       뿐이고, ``EVENT_PHASE`` 는 그 표에 없다. 그러므로
       ``PHASE_CHANGED`` 선언이 만들어지는 경로는 여전히 **없다** — 아래에서
       표와 실제 호출 양쪽으로 확인한다.
    """
    constructors = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path, text in production_sources()
        if re.search(r"\bTriggerSpec\s*\(", text)
        and path.name != "trigger.py"  # 정의 자신
    ]
    assert constructors == ["engine/trigger_compiler.py"], constructors

    from engine.trigger_compiler import (
        EVENT_TIMING,
        TriggerCompilationStatus,
        compile_trigger_spec,
    )

    #: 표에 페이즈 사건이 없다.
    assert not [name for name in EVENT_TIMING if "PHASE" in name]
    #: 그래서 어떤 시점도 ``PHASE_CHANGED`` 가 아니다.
    assert TimingPoint.PHASE_CHANGED not in {t.point for t in EVENT_TIMING.values()}

    #: 실제로 넣어 봐도 선언이 나오지 않는다.
    result = compile_trigger_spec(
        EffectRef(1, 0), declared_types=("TRIGGER_O",), event_code="EVENT_PHASE"
    )
    assert result is not None
    assert result.status is TriggerCompilationStatus.EVENT_UNSUPPORTED
    assert result.spec is None
    assert result.is_registered is False


def test_13_the_duel_loop_does_not_collect_triggers_at_all():
    """
    **§8 — 트리거→체인 통합 계층이 듀얼 루프에 연결되어 있지 않다.**

    ``engine/timing.py`` (``TimingCoordinator``) 를 import 하는 production
    모듈은 ``engine/__init__.py`` (설명 문서) 뿐이고, ``engine/duel.py`` 는
    트리거 계층의 코드를 읽지 않는다.

    .. warning::
       🔴 **Phase 6-Z 가 듀얼 루프를 이었다.** 유발 발동이
       ``Duel.legal_actions`` 에 오르고 ``Duel.apply`` 가 받는다. 그래서
       ``engine/duel.py`` 에 ``triggers`` 라는 **칸**이 생겼고, "trigger
       라는 글자가 없다" 는 낱말 검사가 더 이상 통하지 않는다.

       낱말 대신 **그 검사가 애초에 재려던 것**을 센다 — ``Duel`` 이 트리거
       계층의 코드를 읽는가. 읽지 않는다: 그 계층의 타입 이름을 하나도
       모르고 (아래 목록), import 도 하지 않으며, 들고 있는 칸은
       ``triggers: object | None`` 으로 **불투명하다**. 받는 것은
       ``offers(duel, seat)`` 를 가진 아무 물건이고, 그것을 만드는 일은
       조립 층의 몫이다 (ADR-007).

       예전 검사보다 약하지 않다 — 트리거 계층의 이름이 하나라도 들어오면
       여전히 깨진다. 무엇이 실제로 이어졌는지는
       ``tests/engine/test_trigger_normal_path_integration.py`` 가 센다.
    """
    duel = (PROJECT_ROOT / "engine/duel.py").read_text(encoding="utf-8")
    for absent in (
        "TriggerRegistry",
        "TriggerCollector",
        "TriggerEligibilityJudge",
        "TriggerChainIntegrator",
        "TriggerSpec",
        "TimingEvent",
        "TimingPoint",
        "TimingCoordinator",
        "timing_events",
    ):
        assert absent not in duel, absent
    #: 들고 있는 칸은 **불투명하다** — 타입이 ``object`` 다.
    assert "triggers: object | None = None" in duel

    importers = [
        path.as_posix()
        for path, text in production_sources()
        if ("engine.timing" in text or "TimingCoordinator" in text)
        and path.name not in ("timing.py", "__init__.py")
    ]
    assert importers == [], importers


def test_14_phase_progression_deliberately_leaves_the_event_unread():
    """
    **§4 — 어느 계층이 무엇을 갖는지는 이미 코드에 적혀 있다.**

    ``TurnProgressor`` 는 ``PhaseChanged`` 만 남기고 ``TimingEvent`` 를 만들지
    않는다고 자기 문서에 적어 두었고, 실제로 ``engine.trigger`` 를 import 하지
    않는다. ``TimingPoint.PHASE_CHANGED`` 의 설명도 "타이밍 규칙은 여기 없다"
    고 적어 두었다.
    """
    import ast

    progression = (PROJECT_ROOT / "engine/turn_progression.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(progression)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    #: 설명에서는 트리거를 **이야기하지만** import 하지 않는다 (경계가 글이 아니라 코드다).
    assert "engine.trigger" not in imported, sorted(imported)
    assert "engine.effect.delta" in imported
    assert "PhaseChanged" in progression

    trigger = (PROJECT_ROOT / "engine/trigger.py").read_text(encoding="utf-8")
    assert "PHASE_CHANGED" in trigger
    #: 이 문장이 지워지면 경계가 옮겨간 것이므로 감사를 다시 해야 한다.
    assert "타이밍 규칙은 여기 없다" in trigger


# ======================================================================
# §10 · §11 — 관측 · 평가 경계
# ======================================================================


def test_15_the_view_exposes_the_current_phase_but_no_trigger_metadata():
    """
    **§10 — 관측에는 "지금 어느 페이즈인가" 만 있다.**

    그것은 공개 정보다 (양 플레이어가 본다). 카드의 유발 사건 정체는 관측에
    나가지 않으므로 수정자 소실은 hidden information 과 무관하다.
    """
    view = (PROJECT_ROOT / "engine/game_state_view.py").read_text(encoding="utf-8")
    assert "phase: Phase" in view
    assert "phase=state.turn.phase" in view
    for token in ("EVENT_", "trigger", "TriggerSpec"):
        assert token not in view, token


def test_16_evaluation_and_search_do_not_look_at_phase_events():
    """**§11 — 평가 · 탐색 · 정책 · 시뮬레이션에 없다.**"""
    for name in (
        "agent/evaluation.py",
        "agent/search.py",
        "agent/policy.py",
        "agent/simulation.py",
        "agent/heuristic.py",
    ):
        path = PROJECT_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("EVENT_PHASE", "PHASE_END", "trigger_events", "EffectSpec"):
            assert token not in text, (name, token)


# ======================================================================
# §14 — 경계 테스트: 없는 정보를 있다고 읽지 않는다
# ======================================================================


def test_17_missing_modifier_must_not_be_read_as_every_phase():
    """
    **UNKNOWN ≠ ALL.** ``code == "EVENT_PHASE"`` 에서 페이즈를 되찾는 변환이
    repository 어디에도 없어야 한다. 있다면 **원문에 없는 값을 지어낸 것**이다.

    (``EVENT_PHASE`` → ``Phase.END`` 같은 매핑, 또는 ``TURN_PHASE_ORDER`` 전체를
    돌려주는 변환.)

    .. note::
       이 단정도 3-E-19 에서는 글자 검사였다. 6-E 가 **거부 이유를 산문으로**
       적었으므로 (``PROSE_ONLY_MENTION``) 코드 자리를 센다. 금지 대상은
       "페이즈를 되찾는 변환" 이고, "되찾지 않는다고 적은 설명" 은 그 반대다.
    """
    for path, text in production_sources():
        assert code_mentions(path, text, "EVENT_PHASE") == [], path.as_posix()

    #: ``TURN_PHASE_ORDER`` 자체는 금지 대상이 아니다 — 턴 진행이 쓰는 정당한
    #: 상수다 (``engine/state/turn.py`` 5자리). 처음에 그 이름도 금지로 적었다가
    #: 발화했다: 금지해야 하는 것은 **그 목록을 사건 코드에서 되돌려 주는 변환**
    #: 이고, 사건 코드 자체가 코드 자리에 0회 등장하므로 (바로 위) 그런 변환은
    #: 존재할 수 없다.

    #: 변환을 **실행해서도** 확인한다 — 페이즈가 섞여 나오지 않는다.
    from engine.trigger_compiler import TriggerCompilationStatus, compile_trigger_spec

    for code in ("EVENT_PHASE", "EVENT_PHASE_START"):
        result = compile_trigger_spec(
            EffectRef(1, 0), declared_types=("TRIGGER_O",), event_code=code
        )
        assert result is not None
        assert result.status is TriggerCompilationStatus.EVENT_UNSUPPORTED
        assert result.spec is None
        assert "Phase" not in (result.reason or "")

    #: 모델 쪽에도 그런 매핑이 없다.
    for name in ("core/card_model.py", "analysis/effect_model.py", "analysis/effect_analyzer.py"):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"EVENT_PHASE\s*[:=]\s*(Phase|PHASE_)", text), name


def test_18_missing_modifier_must_not_be_read_as_no_trigger_either():
    """
    **UNKNOWN ≠ NONE.** ``"EVENT_PHASE"`` 는 "유발이 없다" 가 아니다 — 1,336개
    호출은 전부 실제 유발 선언이고, 효과 종류도 그것을 뒷받침한다
    (``TRIGGER_F`` · ``TRIGGER_O`` · ``CONTINUOUS``).
    """
    source = (PROJECT_ROOT / f"c{END_PHASE_CARD}.lua").read_text(encoding="utf-8")
    info = parse_lua_source(END_PHASE_CARD, f"c{END_PHASE_CARD}.lua", source)
    phase_specs = [s for s in info.effects if s.code == "EVENT_PHASE"]
    assert len(phase_specs) == 1
    assert "TRIGGER_F" in phase_specs[0].effect_types
    #: 값이 있으므로 "SetCode 가 없다"(=``None``) 와도 구분된다.
    assert phase_specs[0].code is not None
