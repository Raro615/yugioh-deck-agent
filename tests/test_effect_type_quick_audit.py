"""
Phase 3-F-26 — ``EFFECT_TYPE_QUICK_O`` 의 **의미** 감사: 몬스터 스펠 스피드가
``UNKNOWN`` 인 경계의 정확한 원인은 무엇인가.

**조사 전용 + docstring 정정 2건.** 실행 코드는 한 줄도 바뀌지 않는다
(``test_30`` 이 문자열을 벗긴 AST 로 증명한다).

🔴 이름부터 — ``QUICK_0`` 이 아니라 ``QUICK_O`` 다
---------------------------------------------------
상수의 실제 이름은 **문자 O** 로 끝난다. 숫자 ``0`` 을 쓴 ``EFFECT_TYPE_QUICK_0``
은 ``constant.lua`` 에도, Lua corpus 12,702개에도 **0건**이다 (``test_01``).
그리고 ``QUICK_O`` 와 짝을 이루는 ``QUICK_F`` 가 따로 있다 (16블록).

🔴 이 Phase 가 찾은 것 — 세 가지
---------------------------------
**① ``QUICK_O`` 는 몬스터 전용이 아니다.** 1,781장 중 몬스터 1,338(75.1%) ·
**함정 430** · 마법 13 이다. 특히 **카운터 함정 16장**이 가진다 (``test_05``).

**② ``IGNITION+QUICK_O`` 41블록은 카드 데이터가 아니라 파서 누적의 산물이다.**
``SetType`` 을 만날 때마다 더하고 ``Clone`` 이 부모 목록을 물려주기 때문이다.
실제 Lua 는 ``e1:SetType(IGNITION)`` → ``e2=e1:Clone()`` →
``e2:SetType(QUICK_O)`` 이다. **한 ``SetType`` 호출 안에서 그 둘을 함께 적는
카드는 corpus 전체에 0장**이고, 누적 때문에 달라지는 블록은 전체 34,680 중
**78개(0.22%)** 다 (``test_07``).

**③ ``UNKNOWN`` 의 원인은 "데이터가 없다" 가 아니라 입도(granularity) 다.**
``classify_spell_speed`` 는 **카드**를 받는데 공식 분류는 **효과**에 붙는다.
몬스터 **856장(10.4%)** 이 공식 SS1 계열과 SS2 계열 블록을 **둘 다** 가지므로
카드 단위의 답이 **존재하지 않는다**. 게다가 ``speed_of_link`` 는
``ChainLink.effect_ref`` 를 **들고 있는데 버린다** (``test_28``).

🔴 공식 대응은 확정되지 않았다
-------------------------------
``QUICK_O`` 라는 이름은 이 저장소의 공식 자료 **829파일 전체에서 0회**다
(``test_29``). 반면 공식 룰북은 Quick / Trigger / Ignition / Flip / Continuous
Effect 다섯 종류를 ``spell_speed`` 와 함께 **정의한다** (``test_13`` ~
``test_16``). 그런데 ``QUICK_O`` 를 가진 카드는 공식 스펠 스피드 **1 · 2 · 3
전부**에 걸쳐 있다 (``test_17``). 그래서 이름이 Quick 이라는 이유로 Quick
Effect 라고, 또는 스펠 스피드 2 라고 판정하지 않는다.

앞선 감사가 이미 답한 것 — 다시 쓰지 않고 **이어서** 센다
---------------------------------------------------------
* **Phase 3-F-25** — ``EVENT_FREE_CHAIN`` = ``C. LUA_INTERNAL_TAG``,
  ``EVENT_*`` 70종 전부 production 코드 0회. 이 Phase 는 그 판정을
  **유지하고**, ``QUICK_O`` 와 ``EVENT_FREE_CHAIN`` 사이에 semantic mapping 을
  **만들지 않는다** (``test_18``).
* **Phase 3-E-31** — 파서가 ``TRIGGER_O`` 와 ``TRIGGER_F`` 를 따로 적는다.
  단, 그 보고서가 붙인 *(임의)* · *(강제)* 라는 뜻풀이는 **공식 자료에 근거가
  없다** — 이 Phase 는 그것을 UNKNOWN 으로 남긴다 (``test_32``).
"""

import ast
import collections
import dataclasses
import hashlib
import inspect
import json
import pathlib
import subprocess
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from analysis.effect_model import EffectAnalysis
from core import constants as C
from core.card_model import EffectSpec
from engine.action import PlayerActionKind
from engine.activation import EffectActivator
from engine.activation_timing import (
    MONSTER_CLASSIFICATION_MISSING,
    ActivationTimingChecker,
    SpellSpeed,
    classify_spell_speed,
)
from engine.chain import Chain, ChainLink
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.game_state_view import CardDefinitionView
from engine.trigger import TriggerCandidate, TriggerSpec
from sources.lua_loader import LuaScriptSource, parse_lua_source
import sources.lua_loader as lua_loader

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
    "engine",
    "agent",
    "app",
    "core",
    "analysis",
    "rules",
    "rulings",
    "sources",
    "scripts",
)
MYSELF = "tests/test_effect_type_quick_audit.py"

Q = "QUICK_O"

#: 적용 범위 축 — 서로 공존하지 않는다.
SCOPE_FLAGS = ("SINGLE", "FIELD", "EQUIP")
#: 발동 분류 축.
ACTIVATION_FLAGS = (
    "ACTIVATE",
    "IGNITION",
    "TRIGGER_O",
    "QUICK_O",
    "TRIGGER_F",
    "QUICK_F",
    "FLIP",
    "CONTINUOUS",
)
#: 공식 룰북이 스펠 스피드 1 로 적는 효과 분류에 대응하는 Lua 플래그.
SPEED1_FAMILY = ("IGNITION", "TRIGGER_O", "TRIGGER_F", "FLIP")
#: 공식 룰북이 스펠 스피드 2 로 적는 것에 대응하는 Lua 플래그.
SPEED2_FAMILY = ("QUICK_O", "QUICK_F")

#: 측정으로 카드명을 확인한 실제 카드.
LUSTER_DRAGON = 11091375           # 사파이어 드래곤 — 통상 몬스터 (효과 없음)
POT_OF_GREED = 55144522            # 욕망의 항아리 — 통상 마법
GENEROUS_REWARD = 5915629          # 욕망의 선물 — 통상 함정
MYSTICAL_SPACE_TYPHOON = 5318639   # 싸이크론 — 속공 마법
COMPULSORY_EVACUATION = 94192409   # 강제 탈출 장치 — 통상 함정

CLONE_ARTIFACT = 324483            # IGNITION → Clone → QUICK_O
UTGARDHR = 744887                  # 허구의 제너레이드 우트가르자 — QUICK_O 단독
MAGNUM = 43227                     # 매그넘 더 릴리버 — IGNITION 블록 + QUICK_O 블록
KUKLOCK = 2511                     # 라뷰린스 쿠클락 — QUICK_O + FIELD+TRIGGER_O
ORCUST_CLIMAX = 703897             # 오르페골 클리막스 — 카운터 함정 + QUICK_O
SUPER_SOLDIER_SHIELD = 799183      # 초전사의 방패 — 카운터 함정 + QUICK_O
RAIN_SIGN = 27561302               # 비의 천후모양 — 지속 마법 + QUICK_O
BIG_SHIELD_GARDNA = 65240384       # 빅 실드 가드너 — QUICK_F (QUICK_O 아님)
HIITA_CHARMER = 759393             # 화령사 히타 — SINGLE+FLIP
PLATE_KUNAI = 114932               # 플레이트 크래셔 — IGNITION 단독

DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4


# ======================================================================
# 측정 도구
# ======================================================================


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))
    yield from sorted(PROJECT_ROOT.glob("*.py"))


class _StripStrings(ast.NodeTransformer):
    """문자열 리터럴을 비운다 — docstring 안의 이름이 '사용' 으로 세어지지 않게."""

    def visit_Constant(self, node):  # noqa: N802 - ast 규약
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=""), node)
        return node


def code_only(source: str) -> str:
    return ast.unparse(_StripStrings().visit(ast.parse(source)))


def code_of(func) -> str:
    return ast.unparse(
        _StripStrings().visit(ast.parse(textwrap.dedent(inspect.getsource(func))))
    )


def replace_rule(source: str) -> list[dict]:
    """
    ``SetType`` 을 **누적이 아니라 교체**로 처리한 결과.

    production 파서를 건드리지 않고 같은 이벤트 흐름을 다시 돌린다. 이 함수와
    production 의 차이가 곧 누적 결함의 규모다 (``test_07``).

    🔴 Phase 3-F-28 정정 — 이 함수는 production 의 정규식을 **그룹 번호로** 읽고
    있었다. 3-F-28 이 ``_RE_CREATE_EFFECT`` · ``_RE_CLONE_EFFECT`` 에 ``local``
    포획 그룹을 추가하면서 그룹 번호가 하나씩 밀려, 이 함수는 변수명 대신
    문자열 ``"local"`` 을 변수명으로 집고 있었다 (블록 0개). 그룹 번호를
    맞추고, production 과 **같은 흐름**이 되도록 블록 주석 제거와
    ``_is_card_effect`` 판정도 함께 반영한다.
    """
    events: list[tuple[int, str, str]] = []
    source = lua_loader._RE_BLOCK_COMMENT.sub("", source)
    for match in lua_loader._RE_CREATE_EFFECT.finditer(source):
        if not lua_loader._is_card_effect(source, match.group(1), match.group(2), None):
            continue
        events.append((match.start(), "create", match.group(2)))
    for match in lua_loader._RE_CLONE_EFFECT.finditer(source):
        if not lua_loader._is_card_effect(
            source, match.group(1), match.group(2), match.group(3)
        ):
            continue
        events.append((match.start(), "clone", f"{match.group(2)}={match.group(3)}"))
    for match in lua_loader._RE_SETTER.finditer(source):
        events.append(
            (match.start(), "set", f"{match.group(1)}|{match.group(2)}|{match.end() - 1}")
        )
    events.sort(key=lambda item: item[0])

    bindings: dict[str, dict] = {}
    out: list[dict] = []
    for _position, kind, payload in events:
        if kind == "create":
            current = {"index": payload, "types": [], "cloned_from": None}
            bindings[payload] = current
            out.append(current)
        elif kind == "clone":
            destination, origin = payload.split("=", 1)
            parent = bindings.get(origin)
            current = {
                "index": destination,
                "types": list(parent["types"]) if parent else [],
                "cloned_from": origin,
            }
            bindings[destination] = current
            out.append(current)
        else:
            variable, setter, index = payload.split("|", 2)
            current = bindings.get(variable)
            if current is None:
                continue
            if setter == "Type":
                arguments = lua_loader._extract_call_args(source, int(index))
                current["types"] = lua_loader._strip_prefix(
                    lua_loader._RE_EFFECT_TYPE.findall(arguments)
                )
    return out


@pytest.fixture(scope="module")
def scripts():
    """스크립트 단위 corpus — 블록 통계의 기준."""
    return LuaScriptSource(PROJECT_ROOT).load()


@pytest.fixture(scope="module")
def typed_cards(repository):
    """카드 단위 corpus — 카드 종류가 필요한 통계의 기준."""
    return [card for card in repository._cards.values() if card.script]


def flags_of(card) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for spec in card.script.effects:
        for flag in spec.effect_types:
            counter[flag] += 1
    return counter


def category(card) -> str:
    mask = card.type_mask
    if mask & C.TYPE_SPELL:
        for bit, label in (
            (C.TYPE_QUICKPLAY, "속공 마법"),
            (C.TYPE_FIELD, "필드 마법"),
            (C.TYPE_CONTINUOUS, "지속 마법"),
            (C.TYPE_EQUIP, "장착 마법"),
            (C.TYPE_RITUAL, "의식 마법"),
        ):
            if mask & bit:
                return label
        return "통상 마법"
    if mask & C.TYPE_TRAP:
        if mask & C.TYPE_COUNTER:
            return "카운터 함정"
        if mask & C.TYPE_CONTINUOUS:
            return "지속 함정"
        return "통상 함정"
    if mask & C.TYPE_MONSTER:
        return "몬스터"
    return "기타"


#: 공식 룰북 ``chain.spell_speeds`` 의 카드 종류 열거를 그대로 환원한 것.
#: 몬스터는 **카드 종류로 정해지지 않는다** — 그것이 이 Phase 의 주제다.
OFFICIAL_SPELL_SPEED = {
    "통상 마법": 1,
    "장착 마법": 1,
    "지속 마법": 1,
    "필드 마법": 1,
    "의식 마법": 1,
    "속공 마법": 2,
    "통상 함정": 2,
    "지속 함정": 2,
    "카운터 함정": 3,
}


def official_rulebook() -> dict:
    path = PROJECT_ROOT / "data" / "rules" / "structured" / "sd-rulebook-en-v10.json"
    return json.loads(path.read_text(encoding="utf-8"))


def official_effect_type(name: str) -> dict:
    return next(e for e in official_rulebook()["effect_types"] if e["name"] == name)


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


# ======================================================================
# A. §2 · §3 — 상수의 실제 이름과 corpus
# ======================================================================


def test_01_the_constant_is_spelled_with_a_letter_not_a_digit():
    """
    🔴 §2 — 이름은 ``QUICK_O`` (**문자 O**) 다. ``QUICK_0`` (숫자)은 **없다.**

    그리고 15개 ``EFFECT_TYPE_*`` 는 **독립 비트**다 — 즉 ``effect_types`` 는
    하나의 분류가 아니라 **플래그 집합**이다.
    """
    constants = PROJECT_ROOT / "data" / "constants" / "constant.lua"
    text = constants.read_text(encoding="utf-8")

    bits: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("EFFECT_TYPE_") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        bits[name.strip().removeprefix("EFFECT_TYPE_")] = int(raw.strip(), 16)

    assert "QUICK_O" in bits
    assert "QUICK_0" not in bits
    assert "EFFECT_TYPE_QUICK_0" not in text

    assert bits["QUICK_O"] == 0x100
    assert bits["QUICK_F"] == 0x400
    assert bits["TRIGGER_O"] == 0x80
    assert bits["TRIGGER_F"] == 0x200

    #: 15개가 전부 **서로 다른 한 비트**다 — 겹치지 않는다.
    assert len(bits) == 15
    assert len(set(bits.values())) == 15
    for value in bits.values():
        assert value and not (value & (value - 1)), value  # 2의 거듭제곱


def test_02_quick_o_exists_in_the_corpus(scripts, typed_cards):
    """🟢 §3 — 블록 수. 스크립트 단위와 카드 단위를 **섞지 않는다.**"""
    script_blocks = [
        spec
        for info in scripts.values()
        for spec in info.effects
        if Q in spec.effect_types
    ]
    card_blocks = [
        spec
        for card in typed_cards
        for spec in card.script.effects
        if Q in spec.effect_types
    ]

    assert len(scripts) == 12702
    assert len(script_blocks) == 1875
    assert len(card_blocks) == 1952


def test_03_quick_o_script_and_card_counts(scripts, typed_cards):
    """🟢 §3 — 고유 스크립트 1,712 / 고유 카드 1,781."""
    owners = {
        info.card_id
        for info in scripts.values()
        if any(Q in spec.effect_types for spec in info.effects)
    }
    cards = [card for card in typed_cards if flags_of(card)[Q]]

    assert len(owners) == 1712
    assert len(cards) == 1781
    #: 카드가 스크립트보다 많다 — 스크립트 하나가 여러 패스코드에 붙는다.
    assert len(cards) > len(owners)


def test_04_monster_distribution(typed_cards):
    """🟢 §3 — 몬스터 1,338 / 8,268. **대부분이지만 전부가 아니다.**"""
    monsters = [c for c in typed_cards if category(c) == "몬스터"]
    carriers = [c for c in monsters if flags_of(c)[Q]]

    assert len(monsters) == 8268
    assert len(carriers) == 1338
    assert 0.16 < len(carriers) / len(monsters) < 0.17

    #: QUICK_O 를 가진 카드 중 몬스터의 비중.
    everyone = [c for c in typed_cards if flags_of(c)[Q]]
    assert 0.75 < len(carriers) / len(everyone) < 0.76


def test_05_quick_o_is_not_monster_only(typed_cards):
    """
    🔴 §3 — **"대부분 몬스터" 와 "몬스터 전용" 은 다르다.**

    몬스터가 아닌 QUICK_O 카드가 **443장** 있다. 특히 카운터 함정 16장이다.
    """
    carriers = [c for c in typed_cards if flags_of(c)[Q]]
    by_category = collections.Counter(category(c) for c in carriers)

    assert by_category["몬스터"] == 1338
    non_monster = sum(v for k, v in by_category.items() if k != "몬스터")
    assert non_monster == 443

    assert by_category["통상 함정"] == 185
    assert by_category["지속 함정"] == 229
    assert by_category["카운터 함정"] == 16
    assert by_category["지속 마법"] == 10
    assert by_category["필드 마법"] == 2
    assert by_category["장착 마법"] == 1
    #: 통상 마법 · 속공 마법 · 의식 마법에는 **하나도 없다.**
    assert by_category["통상 마법"] == 0
    assert by_category["속공 마법"] == 0
    assert by_category["의식 마법"] == 0

    #: 실제 카드로 확인한다.
    assert flags_of(_card(typed_cards, ORCUST_CLIMAX))[Q] == 1
    assert category(_card(typed_cards, ORCUST_CLIMAX)) == "카운터 함정"
    assert flags_of(_card(typed_cards, RAIN_SIGN))[Q] == 1
    assert category(_card(typed_cards, RAIN_SIGN)) == "지속 마법"


def _card(typed_cards, passcode):
    return next(c for c in typed_cards if c.id == passcode)


# ======================================================================
# B. §5 — TRIGGER_F / IGNITION / FLIP 과의 관계
# ======================================================================


def test_06_quick_o_never_co_occurs_with_trigger_flags(typed_cards):
    """🔴 §5 — ``QUICK_O`` + ``TRIGGER_F`` · ``TRIGGER_O`` · ``QUICK_F`` = **0**."""
    pairs: collections.Counter = collections.Counter()
    for card in typed_cards:
        for spec in card.script.effects:
            if Q not in spec.effect_types:
                continue
            for other in spec.effect_types:
                if other != Q:
                    pairs[other] += 1

    assert pairs["TRIGGER_F"] == 0
    assert pairs["TRIGGER_O"] == 0
    assert pairs["QUICK_F"] == 0
    assert pairs["FLIP"] == 0
    assert pairs["CONTINUOUS"] == 0
    assert pairs["SINGLE"] == 0
    assert pairs["EQUIP"] == 0


def test_07_quick_o_plus_ignition_is_a_parser_artifact(scripts):
    """
    🔴 §5 — **이 Phase 의 핵심 발견.** ``IGNITION+QUICK_O`` 41블록과
    ``ACTIVATE+QUICK_O`` 5블록은 **카드 데이터가 아니었다.**

    .. note::
       🔴 **Phase 3-F-27 이 파서를 고쳤다.** 그래서 이 테스트는 이제 "결함이
       있다" 가 아니라 **"결함이 사라졌고 정상 조합은 보존된다"** 를 못 박는다.
       아래 서술은 고치기 전 상태의 기록이다.

    파서는 ``SetType`` 을 만날 때마다 **더하고**(``spec.effect_types +
    findall(args)``) ``Clone`` 은 부모 목록을 **물려준다**. 그래서 ``Clone`` 뒤에
    ``SetType`` 을 다시 부른 블록은 물려받은 플래그를 달고 있다.

    .. note::
       EDOPro ``SetType`` API 의 정확한 의미는 이 저장소에 문서화돼 있지 않다.
       그러므로 아래는 **저장소 내부 증거**로만 판단한다 — 한 ``SetType`` 호출
       안에서 그 둘을 함께 적는 카드가 corpus 전체에 **0장**이라는 것.
       따라서 파서의 출력은 **어떤 카드도 적지 않은 조합**을 주장한다.
    """
    accumulated: collections.Counter = collections.Counter()
    replaced: collections.Counter = collections.Counter()
    differing = 0
    differing_scripts = 0
    quick_differing = 0
    cloned = 0

    source = LuaScriptSource(PROJECT_ROOT)
    for card_id, path in source.iter_script_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        info = parse_lua_source(card_id, path.name, text)
        corrected = replace_rule(text)
        assert len(info.effects) == len(corrected), card_id

        changed = False
        for spec, fixed in zip(info.effects, corrected):
            before = tuple(sorted(spec.effect_types))
            after = tuple(sorted(fixed["types"]))
            if Q in before:
                accumulated[before] += 1
            if Q in after:
                replaced[after] += 1
            if before != after:
                differing += 1
                changed = True
                if Q in before or Q in after:
                    quick_differing += 1
                    if spec.cloned_from is not None:
                        cloned += 1
        if changed:
            differing_scripts += 1

    #: 🔴 **Phase 3-F-27 이 이 결함을 고쳤다.** production 이 이제 교체 규칙과
    #: 같은 답을 낸다 — 아래 네 줄이 그것을 못 박는다.
    assert accumulated[("IGNITION", Q)] == 0
    assert accumulated[("ACTIVATE", Q)] == 0
    assert replaced[("IGNITION", Q)] == 0
    assert replaced[("ACTIVATE", Q)] == 0

    #: 남는 실제 조합은 둘뿐이다 — 둘 다 한 호출 안의 OR 다. 보존된다.
    for table in (accumulated, replaced):
        assert table[("FIELD", Q)] == 4
        assert table[(Q, "XMATERIAL")] == 4
        assert table[(Q,)] == 1867

    #: 🔴 고친 뒤 **QUICK_O 블록에서는 두 규칙이 완전히 일치한다.**
    assert accumulated == replaced, (accumulated, replaced)

    #: 🔴 Phase 3-F-28 에서 1 → 0. 남아 있던 그 1건은 ``c9839115`` 의
    #: ``local`` 없는 ``e1=Effect.CreateEffect(c)`` 가 설정자를 흘리는
    #: **별개 버그**였고 (3-F-27 보고서 §7 · 당시 범위 밖), 3-F-28 이
    #: 그 블록을 따로 세기 시작하면서 사라졌다. 이제 누적 규칙과 교체
    #: 규칙은 corpus **전체**에서 같다 — 결론이 약해진 것이 아니라 강해졌다.
    assert differing == 0
    assert differing_scripts == 0
    assert quick_differing == 0
    assert cloned == 0

    #: QUICK_O 자체의 개수는 고치기 전에도 후에도 같다 — 더하기만 했으므로
    #: QUICK_O 가 추가되거나 사라진 블록은 **0건**이다.
    assert sum(accumulated.values()) == sum(replaced.values()) == 1875


def test_08_flip_is_the_one_that_overlaps_trigger(scripts):
    """
    🔴 §5 — ``QUICK_O`` 는 ``FLIP`` 과 0회지만, ``FLIP`` 은 ``TRIGGER_O`` ·
    ``TRIGGER_F`` 와 **공존한다** (63 · 6).

    그리고 공식 룰북이 그것을 그대로 적는다 — *"Flip effect is a part of the
    Trigger Effect."* 즉 발동 분류 축조차 **완전한 배타가 아니다.**
    """
    pairs: collections.Counter = collections.Counter()
    flip_blocks = 0
    for info in scripts.values():
        for fixed in replace_rule(
            (PROJECT_ROOT / info.file_name).read_text(encoding="utf-8", errors="replace")
        ):
            types = set(fixed["types"])
            if "FLIP" not in types:
                continue
            flip_blocks += 1
            for other in types - {"FLIP"}:
                pairs[other] += 1

    assert flip_blocks == 189
    assert pairs["TRIGGER_O"] == 63
    assert pairs["TRIGGER_F"] == 6
    assert pairs["SINGLE"] == 189
    assert pairs[Q] == 0

    #: 공식 룰북의 문장.
    flip = official_effect_type("Flip Effect")
    assert "part of the Trigger Effect" in flip["notes"]


def test_09_the_scope_axis_is_mutually_exclusive(scripts):
    """
    🔴 §5 · §11 — 적용 범위 축(``SINGLE`` · ``FIELD`` · ``EQUIP``)은 서로
    **0회** 공존한다. 발동 분류와 **다른 축**이라는 구조적 증거다.
    """
    together: collections.Counter = collections.Counter()
    alone: collections.Counter = collections.Counter()
    for info in scripts.values():
        for fixed in replace_rule(
            (PROJECT_ROOT / info.file_name).read_text(encoding="utf-8", errors="replace")
        ):
            types = set(fixed["types"])
            for flag in types:
                alone[flag] += 1
            for left in SCOPE_FLAGS:
                for right in SCOPE_FLAGS:
                    if left != right and left in types and right in types:
                        together[(left, right)] += 1

    assert sum(together.values()) == 0, dict(together)
    #: 🔴 Phase 3-F-28 에서 ``SINGLE`` 14,731 → 14,732. 새로 세는 두 블록
    #: (``c9839115`` ``e1`` · ``c74506079`` ``ae``) 이 둘 다 ``SINGLE`` 이고,
    #: 더 이상 세지 않는 ``c9409625`` 의 주석 안 블록도 ``SINGLE`` 이었다
    #: (+2 −1). ``FIELD`` · ``EQUIP`` 는 그대로다.
    assert alone["SINGLE"] == 14732
    assert alone["FIELD"] == 8881
    assert alone["EQUIP"] == 639
    #: corpus 에 **한 번도 나오지 않는** 플래그가 둘 있다.
    assert alone["TARGET"] == 0
    assert alone["ACTIONS"] == 0


def test_10_effect_definition_has_no_effect_types_field():
    """
    🔴 §2 · §11 — ``EffectDefinition.effect_types`` 는 **존재하지 않는다.**

    ``code`` 와 똑같은 모양이다 (3-F-24 · 3-F-25). 파서 계층에만 있다.
    """
    definition = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert "effect_types" not in definition
    assert "code" not in definition
    assert len(definition) == 10
    assert definition == {
        "effect_ref",
        "source_card_id",
        "operations",
        "activation",
        "cost",
        "targets",
        "declarations",
        "requirements",
        "guards",
        "provenance",
    }

    #: 있는 곳은 파서와 분석 계층뿐이다.
    assert "effect_types" in {f.name for f in dataclasses.fields(EffectSpec)}
    assert "effect_types" in {f.name for f in dataclasses.fields(EffectAnalysis)}
    assert "effect_types" not in {f.name for f in dataclasses.fields(TriggerSpec)}
    assert "effect_types" not in {f.name for f in dataclasses.fields(CardDefinitionView)}


# ======================================================================
# C. §8 · §13 — production 이 읽는가
# ======================================================================


def test_11_activation_timing_does_not_read_effect_types():
    """
    🔴 §8 A · B — ``activation_timing.py`` 가 읽는 속성을 **AST 로** 센다.

    ``classify_spell_speed`` 는 카드 종류 계열만 읽는다.
    """
    attributes = set()
    tree = _StripStrings().visit(
        ast.parse(textwrap.dedent(inspect.getsource(classify_spell_speed)))
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attributes.add(node.attr)

    assert {"type_names", "is_trap", "is_spell", "is_monster"} <= attributes
    assert not ({"effect_types", "code", "effects", "script"} & attributes)

    module = code_only(
        (PROJECT_ROOT / "engine" / "activation_timing.py").read_text(encoding="utf-8")
    )
    assert "effect_types" not in module
    assert "QUICK_O" not in module
    assert "EffectSpec" not in module


def test_12_the_missing_reason_names_an_effect_level_classification():
    """
    🔴 §8 C · §10 — ``MONSTER_CLASSIFICATION_MISSING`` 의 문장 자체가
    **효과 단위** 분류를 가리킨다.

    *"monster effect classification (기동 · 유발 · 플립 vs 유발즉시)"* —
    카드가 아니라 **효과**다. 그런데 그 값을 쓰는 함수는 카드를 받는다.
    """
    assert "monster effect classification" in MONSTER_CLASSIFICATION_MISSING
    assert "유발즉시" in MONSTER_CLASSIFICATION_MISSING

    #: 이 사유를 돌려주는 자리는 `is_monster` 분기 하나뿐이다.
    body = code_of(classify_spell_speed)
    assert body.count("MONSTER_CLASSIFICATION_MISSING") == 1
    assert "is_monster" in body

    #: 받는 인자는 **카드 정의** 하나다 — effect_ref 를 받지 않는다.
    signature = inspect.signature(classify_spell_speed)
    assert list(signature.parameters) == ["definition"]


def test_13_official_quick_effect_is_defined_as_spell_speed_two():
    """🟢 §6 — 공식 Quick Effect: ``spell_speed`` 2, 발동 시점은 **미기재**."""
    quick = official_effect_type("Quick Effect")
    assert quick["spell_speed"] == 2
    assert quick["has_activation"] is True
    assert quick["activation_timing"] is None
    assert quick["not_stated"] == ["activation_timing"]

    speeds = {r["speed"]: r for r in official_rulebook()["chain"]["spell_speeds"]}
    assert any("Quick Effect" in t for t in speeds[2]["card_types"])


def test_14_official_trigger_effect_is_spell_speed_one():
    """🟢 §6 — 공식 Trigger Effect: ``spell_speed`` **1**."""
    trigger = official_effect_type("Trigger Effect")
    assert trigger["spell_speed"] == 1
    assert trigger["has_activation"] is True
    assert "destroyed" in trigger["activation_timing"]

    speeds = {r["speed"]: r for r in official_rulebook()["chain"]["spell_speeds"]}
    assert any("Trigger" in t for t in speeds[1]["card_types"])
    assert speeds[1]["can_respond_to"] == []


def test_15_official_ignition_effect_is_spell_speed_one():
    """🟢 §6 — 공식 Ignition Effect: ``spell_speed`` 1, 자신의 메인 페이즈."""
    ignition = official_effect_type("Ignition Effect")
    assert ignition["spell_speed"] == 1
    assert ignition["has_activation"] is True
    assert ignition["activation_timing"] == "your Main Phase"


def test_16_official_flip_and_continuous_effects():
    """🟢 §6 — 공식 Flip = 1 (Trigger 의 일부) · Continuous = 발동이 **없다**."""
    flip = official_effect_type("Flip Effect")
    assert flip["spell_speed"] == 1
    assert flip["has_activation"] is True

    continuous = official_effect_type("Continuous Effect")
    assert continuous["spell_speed"] == 1
    assert continuous["has_activation"] is False
    assert continuous["activation_timing"] is None
    assert "no trigger for its activation" in continuous["notes"]

    #: 공식 분류는 **다섯 종류**다. Lua 플래그는 15개다 — 1:1 이 아니다.
    assert len(official_rulebook()["effect_types"]) == 5


def test_17_quick_o_cards_span_all_three_official_spell_speeds(typed_cards):
    """
    🔴 §7 — **``QUICK_O`` → 스펠 스피드 2 는 성립하지 않는다.**

    카드 종류로 공식 스펠 스피드가 정해지는 QUICK_O 카드는 **1 · 2 · 3 전부**에
    걸쳐 있다.
    """
    carriers = [c for c in typed_cards if flags_of(c)[Q]]
    table: collections.Counter = collections.Counter()
    for card in carriers:
        table[OFFICIAL_SPELL_SPEED.get(category(card))] += 1

    assert table[1] == 13
    assert table[2] == 414
    assert table[3] == 16
    assert table[None] == 1338  # 몬스터 — 카드 종류로 정해지지 않는다

    #: 세 등급 모두 비어 있지 않으므로 1:1 함수가 아니다.
    assert all(table[speed] for speed in (1, 2, 3))

    #: 🔴 엔진이 실제로 돌려주는 값으로도 확인한다.
    climax = classify_spell_speed(CardDefinitionView.of(_card(typed_cards, ORCUST_CLIMAX)))
    rain = classify_spell_speed(CardDefinitionView.of(_card(typed_cards, RAIN_SIGN)))
    assert climax.speed is SpellSpeed.COUNTER     # 3
    assert rain.speed is SpellSpeed.NORMAL        # 1
    #: 둘 다 QUICK_O 를 가졌는데 속도가 3 과 1 이다.
    assert flags_of(_card(typed_cards, ORCUST_CLIMAX))[Q]
    assert flags_of(_card(typed_cards, RAIN_SIGN))[Q]


def test_18_quick_o_and_event_free_chain_stay_separate(typed_cards):
    """
    🔴 §12 — 3-F-25 의 판정(``EVENT_FREE_CHAIN`` = ``LUA_INTERNAL_TAG``)을
    유지한다. 둘 사이에 **semantic mapping 을 만들지 않는다.**

    같은 카드에서 자주 함께 나타나지만 **서로를 결정하지 않는다** — 양방향 모두
    반례가 있다.
    """
    with_quick_without_chain = []
    with_chain_without_quick = []
    for card in typed_cards:
        for spec in card.script.effects:
            has_quick = Q in spec.effect_types
            has_chain = spec.code == "EVENT_FREE_CHAIN"
            if has_quick and not has_chain:
                with_quick_without_chain.append(card.id)
            if has_chain and not has_quick:
                with_chain_without_quick.append(card.id)

    #: 양방향 반례가 **둘 다 많다** — 동의어가 아니다.
    assert len(with_quick_without_chain) > 600
    assert len(with_chain_without_quick) > 3000

    #: 서로 다른 칸이다 — 하나는 `effect_types`, 하나는 `code`.
    assert "effect_types" != "code"
    fields = {f.name for f in dataclasses.fields(EffectSpec)}
    assert {"effect_types", "code"} <= fields

    #: 실제 카드: QUICK_O 인데 EVENT_FREE_CHAIN 이 아닌 블록.
    falcon = _card(typed_cards, 1287123)  # 머티리얼 팔코
    quick_blocks = [s for s in falcon.script.effects if Q in s.effect_types]
    assert quick_blocks
    assert all(s.code != "EVENT_FREE_CHAIN" for s in quick_blocks)


def test_19_legal_actions_does_not_read_it():
    """🔴 §13 — ``legal_actions`` 와 후보 생성기 전부 **DOES NOT READ**."""
    for func in (
        Duel.legal_actions,
        Duel._activation_actions,
        Duel._activation_gate,
        Duel._flow_actions,
        Duel._attack_actions,
        Duel._withheld_board_actions,
    ):
        body = code_of(func)
        assert "effect_types" not in body, func.__name__
        assert "QUICK_O" not in body, func.__name__


def test_20_effect_activator_does_not_read_it():
    """🔴 §13 — ``EffectActivator`` **DOES NOT READ**."""
    source = code_only(inspect.getsource(EffectActivator))
    assert "effect_types" not in source
    assert "QUICK_O" not in source
    assert "EffectSpec" not in source


def test_21_chain_link_and_resolver_do_not_read_it():
    """🔴 §13 — ``ChainLink`` · ``Chain`` · ``ChainResolver`` **DOES NOT READ**."""
    fields = [f.name for f in dataclasses.fields(ChainLink)]
    assert "effect_types" not in fields
    #: 🔴 그런데 **effect_ref 는 들고 있다** — test_28 이 쓰는 사실이다.
    assert "effect_ref" in fields

    module = code_only((PROJECT_ROOT / "engine" / "chain.py").read_text(encoding="utf-8"))
    assert "effect_types" not in module
    assert "QUICK_O" not in module


def test_22_apply_does_not_read_it():
    """🔴 §13 — ``apply`` 와 발동 경로 **DOES NOT READ**."""
    for func in (Duel.apply, Duel._apply_activation):
        body = code_of(func)
        assert "effect_types" not in body, func.__name__
        assert "QUICK_O" not in body, func.__name__


def test_23_search_does_not_read_it():
    """🔴 §14 — Search **DOES NOT READ**. 카드 정의를 직접 열지도 않는다."""
    for name in ("search.py", "simulation.py"):
        source = code_only(
            (PROJECT_ROOT / "agent" / name).read_text(encoding="utf-8")
        )
        assert "effect_types" not in source, name
        assert "QUICK_O" not in source, name
        assert ".script" not in source, name


def test_24_ai_does_not_read_it():
    """🔴 §14 — AI(정책 · 평가 · 휴리스틱) **DOES NOT READ**."""
    for name in ("heuristic.py", "policy.py", "evaluation.py", "runner.py", "arena.py"):
        source = code_only(
            (PROJECT_ROOT / "agent" / name).read_text(encoding="utf-8")
        )
        assert "effect_types" not in source, name
        assert "QUICK_O" not in source, name
        assert "EffectSpec" not in source, name

    #: GameStateView 가 그 값을 싣지 않으므로 AI 는 **볼 수조차 없다.**
    assert "effect_types" not in {
        f.name for f in dataclasses.fields(CardDefinitionView)
    }


def test_25_trigger_candidate_does_not_read_it():
    """🔴 §13 — ``TriggerCandidate`` 생성 **DOES NOT READ**."""
    assert "effect_types" not in {f.name for f in dataclasses.fields(TriggerCandidate)}
    module = code_only(
        (PROJECT_ROOT / "engine" / "trigger.py").read_text(encoding="utf-8")
    )
    assert "effect_types" not in module
    assert "QUICK_O" not in module


# ======================================================================
# D. §10 — UNKNOWN 의 원인 분해
# ======================================================================


def test_26_the_data_exists_but_nothing_reads_it():
    """
    🔴 §10 A · B — 원인 중 **B(있는데 안 읽는다)** 가 성립한다.

    ``effect_types`` 는 파서 계층에 실제로 있고, engine/agent 코드에서 등장이
    **0회**다. 그러므로 A(데이터가 아예 없다)는 **성립하지 않는다.**
    """
    readers = []
    for path in production_files():
        try:
            source = code_only(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        if "effect_types" in source:
            readers.append(str(path.relative_to(PROJECT_ROOT)))

    assert readers, "데이터를 쓰는 곳이 하나도 없다면 측정이 잘못됐다"
    #: engine/ 과 agent/ 에는 **없다.**
    assert not [r for r in readers if r.startswith(("engine/", "agent/"))], readers
    #: 있는 곳은 파서 · 분석 · 공식 룰 구조화 · CLI · 예제뿐이다.
    assert set(readers) == {
        "analysis/effect_analyzer.py",
        "analysis/effect_model.py",
        "app/main.py",
        "core/card_model.py",
        "lua_parser_example.py",
        "rules/structured.py",
        "sources/lua_loader.py",
    }, readers


def test_27_a_card_is_not_one_classification(typed_cards):
    """
    🔴 §10 D · §5 — ``QUICK_O`` 를 **효과의 최종 분류**로는 볼 수 있어도
    **카드의 분류**로는 볼 수 없다.

    QUICK_O 카드 1,781장 중 다른 발동 분류 블록이 **전혀 없는** 카드는 418장
    (23.5%)뿐이다. 나머지 76.5%는 섞여 있다.
    """
    carriers = [c for c in typed_cards if flags_of(c)[Q]]
    assert len(carriers) == 1781

    mixed: collections.Counter = collections.Counter()
    pure = 0
    for card in carriers:
        flags = flags_of(card)
        others = [f for f in ACTIVATION_FLAGS if f != Q and flags[f]]
        if not others:
            pure += 1
        for flag in others:
            mixed[flag] += 1

    assert pure == 418
    assert mixed["TRIGGER_O"] == 604
    assert mixed["ACTIVATE"] == 429
    assert mixed["IGNITION"] == 293
    assert mixed["CONTINUOUS"] == 254
    assert mixed["TRIGGER_F"] == 90
    assert mixed["FLIP"] == 5
    assert mixed["QUICK_F"] == 0

    #: 실제 카드: 매그넘 더 릴리버 — IGNITION 블록과 QUICK_O 블록을 **따로** 가진다.
    magnum = _card(typed_cards, MAGNUM)
    block_types = [tuple(s.effect_types) for s in magnum.script.effects]
    assert ("IGNITION",) in block_types
    assert (Q,) in block_types


def test_28_the_real_cause_is_a_granularity_mismatch(typed_cards):
    """
    🔴 §10 F — **이 Phase 의 결론.** ``UNKNOWN`` 은 "읽는 계층이 없어서" 가
    아니라 **입도가 달라서**다.

    1. 몬스터 **856장(10.4%)** 이 공식 SS1 계열과 SS2 계열 블록을 **둘 다**
       가진다. 그런 카드에는 **카드 단위의 답이 없다.**
    2. ``speed_of_link`` 는 ``ChainLink.effect_ref`` 를 **들고 있는데 버리고**
       ``spell_speed(link.source)`` 를 부른다 — 효과 단위 정보가 거기서
       사라진다.
    """
    monsters = [c for c in typed_cards if category(c) == "몬스터"]
    both = 0
    quick_with_speed1 = 0
    for card in monsters:
        flags = flags_of(card)
        has_one = any(flags[f] for f in SPEED1_FAMILY)
        has_two = any(flags[f] for f in SPEED2_FAMILY)
        if has_one and has_two:
            both += 1
        if flags[Q] and has_one:
            quick_with_speed1 += 1

    assert len(monsters) == 8268
    assert both == 856
    assert quick_with_speed1 == 847
    assert 0.10 < both / len(monsters) < 0.11
    assert quick_with_speed1 / 1338 > 0.63

    #: 🔴 ``speed_of_link`` 가 ``effect_ref`` 를 버리는 것을 **AST 로** 본다.
    body = code_of(ActivationTimingChecker.speed_of_link)
    assert "link.source" in body
    assert "effect_ref" not in body, body
    #: 그런데 ChainLink 에는 effect_ref 가 있다.
    assert "effect_ref" in {f.name for f in dataclasses.fields(ChainLink)}


def test_29_the_lua_names_are_absent_from_official_material():
    """
    🔴 §6 C · §10 C — ``QUICK_O`` 는 **공식 용어가 아니다.**

    저장소의 공식 자료 829파일 전체에서 Lua 플래그 이름이 **0회**다. 그래서
    이름이 Quick 이라는 이유로 공식 Quick Effect 라고 판정하지 않는다.
    """
    roots = [
        PROJECT_ROOT / "data" / "rules",
        PROJECT_ROOT / "data" / "rulings",
        PROJECT_ROOT / "data" / "ko",
    ]
    scanned = 0
    hits: dict[str, list[str]] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".html", ".txt"}:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in ("QUICK_O", "QUICK_F", "TRIGGER_O", "TRIGGER_F", "EFFECT_TYPE"):
                if name in text:
                    hits.setdefault(name, []).append(str(path))

    assert scanned >= 800, scanned
    assert hits == {}, hits

    #: probe 가 살아 있다 — 공식 자료가 **실제로 쓰는** 어휘는 잡힌다.
    rulebook = json.dumps(official_rulebook(), ensure_ascii=False)
    assert "Quick Effect" in rulebook
    assert "Spell Speed" in rulebook
    assert "Ignition Effect" in rulebook


# ======================================================================
# E. §15 · §17 — 변경 범위와 불변 조건
# ======================================================================


def test_30_production_change_is_documentation_only():
    """
    🔴 §15 — production 변경은 **docstring 두 건뿐**이다.

    문자열 리터럴을 벗긴 AST 가 base 와 **글자 그대로 같다**. 그리고 바꾼
    파일이 **정확히 그 둘**임을 함께 못 박는다.
    """

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    #: Phase 3-F-25 보고서 commit — 이 Phase 의 base.
    PHASE_3F26_BASE = "adcd877"

    added = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    #: commit 전에는 base ↔ 작업 트리로 되돌아간다 (**skip 하지 않는다**).
    base = f"{added[-1]}^" if added else PHASE_3F26_BASE
    #: 🔴 끝점은 **이 Phase 의 commit** 이다 — ``HEAD`` 가 아니다. ``HEAD`` 로
    #: 쓰면 뒤에 오는 Phase 의 변경이 섞여 들어와 이 테스트가 깨진다 (3-F-25 가
    #: 실제로 그렇게 깨졌고, 이 Phase 가 그 테스트도 함께 고쳤다).
    tip = [added[-1]] if added else []

    changed = git("diff", "--name-only", base, *tip, "--", *PRODUCTION_ROOTS).split()

    assert set(changed) == {
        "core/card_model.py",
        "engine/activation_timing.py",
    }, changed

    for relative in changed:
        before = git("show", f"{base}:{relative}")
        after = (
            git("show", f"{tip[0]}:{relative}")
            if tip
            else (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        )
        assert code_only(before) == code_only(after), relative


def test_31_the_two_docstrings_record_what_was_measured():
    """
    🔴 §15 — 정정한 두 docstring 이 이 Phase 의 수치를 **실제로 적는다.**

    .. warning::
       🔴 문장 단위로 센다. 파일 전체 부분 문자열 하나로 두 군데를 대신 세면,
       한쪽을 뒤집어도 다른 쪽이 통과시킨다 (3-F-25 가 주입으로 겪었다).
    """
    model = (PROJECT_ROOT / "core" / "card_model.py").read_text(encoding="utf-8")
    timing = (PROJECT_ROOT / "engine" / "activation_timing.py").read_text(
        encoding="utf-8"
    )

    #: 🔴 누적 결함을 적는다 — **Phase 3-F-27 이 고친 뒤의 서술**로 갱신됐다.
    assert model.count("Phase 3-F-26 이 찾고 3-F-27 이 고친 결함") == 1
    assert "77블록 / 74스크립트" in model
    assert "0.22%" in model
    assert "c324483" in model
    #: 고쳐졌다는 사실과 고친 뒤의 값이 함께 적혀 있다.
    assert "지금은" in model and "['QUICK_O']" in model
    #: 🔴 아직 남은 형제 칸 결함도 적혀 있다 (범위 밖이라 고치지 않았다).
    assert "같은 유형이 형제 칸에 남아 있다" in model
    assert "217곳 / 195파일" in model
    #: 축 구조를 적는다.
    assert "플래그 집합" in model
    assert "독립 비트" in model

    #: 입도 원인을 적는다.
    assert timing.count('🔴 **"``QUICK_O`` 를 읽으면 풀린다" 가 아니다**') == 1
    assert "856장(10.4%)" in timing
    assert "847장(63.3%)" in timing
    assert "829파일 전체에서 0회" in timing
    assert "speed_of_link" in timing
    #: 뒤집힌 주장이 들어오지 않았는지.
    assert "QUICK_O 를 읽으면 풀린다**" not in timing.replace(
        '🔴 **"``QUICK_O`` 를 읽으면 풀린다" 가 아니다**', ""
    )


def test_32_the_optional_forced_gloss_has_no_official_basis():
    """
    🔴 §6 — ``_O`` / ``_F`` 접미사의 뜻은 **UNKNOWN 으로 남긴다.**

    Phase 3-E-31 보고서가 ``TRIGGER_O`` 를 *(임의)*, ``TRIGGER_F`` 를 *(강제)* 로
    적었다. 그 뜻풀이는 **공식 자료에 근거가 없고**(``test_29``) production 코드
    어디에서도 **해석되지 않는다.**

    엔진에는 ``TriggerRequirement.MANDATORY`` / ``OPTIONAL`` 축이 **따로** 있고,
    그것은 ``TriggerSpec.requirement`` 에서 오며 ``effect_types`` 와 **연결되지
    않는다.**
    """
    #: 엔진의 강제/임의 축은 존재한다.
    from engine.trigger import TriggerRequirement

    assert {m.name for m in TriggerRequirement} >= {"MANDATORY", "OPTIONAL"}
    assert "requirement" in {f.name for f in dataclasses.fields(TriggerSpec)}

    #: 그런데 production 코드에서 접미사를 해석하는 자리가 **0곳**이다.
    interpreters = []
    for path in production_files():
        try:
            source = code_only(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for name in ("TRIGGER_O", "TRIGGER_F", "QUICK_O", "QUICK_F"):
            if name in source:
                interpreters.append((str(path.relative_to(PROJECT_ROOT)), name))
    assert interpreters == [], interpreters

    #: 3-E-31 이 그 뜻풀이를 적은 것은 사실이다 — 근거가 없다는 것이 요점이다.
    report = PROJECT_ROOT / "docs" / "phase3e31-effectdefinition-trigger-boundary-audit.md"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        assert "TRIGGER_O`` (임의)" in text or "(임의)" in text


def test_33_effect_types_is_a_colliding_field_name():
    """
    🔴 §11 — ``effect_types`` 라는 **같은 이름이 둘**이다.

    ======================================  ==========================
    이름                                      실제로 담는 것
    ======================================  ==========================
    ``EffectSpec.effect_types``              Lua ``EFFECT_TYPE_*`` 플래그
    ``rules.structured.…effect_types``       **공식 룰북의 효과 종류 5종**
    ======================================  ==========================

    부분 문자열로 세면 조용히 섞인다.
    """
    from rules.structured import StructuredRules

    rule_fields = {f.name for f in dataclasses.fields(StructuredRules)}
    assert "effect_types" in rule_fields

    #: 공식 쪽은 **5종**이고 이름이 공식 용어다.
    names = [e["name"] for e in official_rulebook()["effect_types"]]
    assert names == [
        "Continuous Effect",
        "Ignition Effect",
        "Quick Effect",
        "Trigger Effect",
        "Flip Effect",
    ]
    #: Lua 쪽은 **15개**이고 이름이 공식 용어가 아니다.
    assert len(ACTIVATION_FLAGS) + len(SCOPE_FLAGS) + 4 == 15


def test_34_state_hash_and_rng_are_unchanged(repository):
    """🟢 §17 — ``state_hash`` · RNG 불변."""
    first = opened_duel(repository, seed=23)
    second = opened_duel(repository, seed=23)
    assert first.state.state_hash() == second.state.state_hash()

    other = opened_duel(repository, seed=24)
    assert other.state.state_hash() != first.state.state_hash()

    left = [first.state.rng.randrange(1000) for _ in range(8)]
    right = [second.state.rng.randrange(1000) for _ in range(8)]
    assert left == right


def test_35_a_quick_o_card_still_plays_and_stays_unknown(repository):
    """
    🟢 §13 · §17 — ``QUICK_O`` 를 가진 실제 카드를 넣어도 ``legal_actions`` 가
    내놓는 것은 변하지 않고, 몬스터 스펠 스피드는 여전히 ``UNKNOWN`` 이다.

    "소비하지 않는다" 가 "버그" 라는 뜻이 아니다 — **미지원 경계**다.
    """
    deck = [POT_OF_GREED] * 6 + [MYSTICAL_SPACE_TYPHOON] * 4 + [
        COMPULSORY_EVACUATION
    ] * 4 + [LUSTER_DRAGON] * 6
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=9)
    transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()

    accepted = collections.Counter(
        entry.action.kind for entry in transcript.entries if entry.accepted
    )
    assert accepted[PlayerActionKind.ACTIVATE_EFFECT] > 0
    assert accepted[PlayerActionKind.ACTIVATE_CARD] == 0

    #: 몬스터는 여전히 UNKNOWN 이고, 사유가 그대로 그 문장이다.
    monster = classify_spell_speed(
        CardDefinitionView.of(repository._cards[LUSTER_DRAGON])
    )
    assert monster.speed is None
    assert monster.missing == MONSTER_CLASSIFICATION_MISSING


def test_36_the_search_ranking_digest_is_unchanged(repository):
    """
    🟢 §17 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은
       파일이 못 박은 값을 기준으로 쓴다 (3-F-18 ~ 3-F-25 와 같은 방식).
    """
    pinned: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative == MYSELF:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(c in "0123456789abcdef" for c in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: dict[str, int] = {}
    for values in pinned.values():
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    expected, pins = max(counts.items(), key=lambda item: item[1])
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == expected
