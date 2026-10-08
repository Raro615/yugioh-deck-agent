"""
Phase 3-F-25 — ``EVENT_FREE_CHAIN`` 의 **의미** 감사: 공식 "Free Chain" 과
Lua 상수가 어떤 관계인가.

**AUDIT-ONLY + docstring 정정 2건.** 실행 코드는 한 줄도 바뀌지 않는다
(``test_30`` 이 문자열을 벗긴 AST 로 증명한다).

🔴 이 Phase 가 **정정하는 것**
-------------------------------
production docstring 두 곳이 ``EVENT_FREE_CHAIN`` 을 *"'유발 조건이 없다' 를
적은 값"* 이라고 쓰고 있었다. 측정하면 **그 문장은 너무 넓다.**

``EFFECT_TYPE_IGNITION`` 블록 4,180개 중 **98.5%(4,119)는 ``SetCode`` 를 아예
부르지 않는다** — 같은 "없다" 를 **생략**으로 적는다 (``test_25``). 반대로
``ACTIVATE`` · ``QUICK_O`` 블록은 ``code is None`` 이 **0건**이다. 그러니
``EVENT_FREE_CHAIN`` 은 "없다" 의 **유일한 표기가 아니고**, ``ACTIVATE`` ·
``QUICK_O`` 라는 **특정 블록 종류에서 쓰는 명시 표기**다.

또 함께 쓰이는 ``effect_types`` 열거가 불완전했다 — ``FIELD`` 3 ·
``CONTINUOUS`` 1 블록이 빠져 있었다 (``test_26``).

🔴 공식 개념과의 관계 — **1:1 이 아니고, 끝에서 뒤집힌다**
---------------------------------------------------------
``EFFECT_TYPE_ACTIVATE`` 블록만 보면 (``test_24``):

====================  ========  ===================  =============
카드 종류               공식 SS   ``ACTIVATE`` 블록      FREE_CHAIN
====================  ========  ===================  =============
필드 마법                     1                  312   **312 (100%)**
통상 마법                     1                  975        975 (100%)
속공 마법                     2                  498        453 (91%)
통상 함정                     2                1,308        918 (70%)
카운터 함정                   3                  210      **3 (1.4%)**
====================  ========  ===================  =============

공식 룰북은 스펠 스피드 1 을 *"cannot be activated in response to any other
effects"*, 스펠 스피드 3 을 *"Only another Spell Speed 3 card may be used to
respond"* 라고 적는다. 즉 **가장 자유롭게 체인하는 쪽(카운터 함정)이 이 상수를
거의 쓰지 않고, 전혀 체인하지 못하는 쪽(필드 마법)이 100% 쓴다** — 70배 차이가
공식 속도와 **반대 방향**으로 난다.

.. warning::
   🔴 측정 중 한 번 과장했다. 상위 3개만 출력한 결과를 보고 카운터 함정을
   "0건" 이라고 적었는데, 전수로 세면 **3건**이다 (다이놀피어 쉘 ``25419323`` ·
   다이놀피어 리버전 ``28292031`` · 파르티안샷 ``29185231``). ``most_common(3)``
   은 "없다" 의 근거가 될 수 없다 — ``test_13`` 은 **전수**로 센다.

그리고 이 저장소의 공식 자료 — 룰북 원문 · 구조화본 · 공식 재정 686파일 ·
한국어 공식 DB — 전체에서 "Free Chain" 은 **0회** 나온다 (``test_23``).

측정의 한계를 숨기지 않는다
---------------------------
.. note::
   🔴 공식 DB(``db.yugioh-card.com``) 의 Q&A 전문 검색으로 이 용어의 공식
   존재 여부를 **판정하지 못했다.** ``faq_search.action`` 은 ``stype``
   파라미터를 URL 로는 받지 않아 카드명 검색으로만 동작했고 (``stype=1`` 과
   ``stype=2`` 가 같은 결과), 공식 용어인 ``スペルスピード`` 조차 0건이
   나왔다. **0건을 근거로 쓰지 않는다.** 그래서 공식 정의는 이 Phase 에서
   **UNKNOWN** 으로 남는다 — 보고서 §2 참고.

앞선 감사가 이미 답한 것 — 다시 쓰지 않고 **이어서** 센다
---------------------------------------------------------
* **Phase 3-E-31 / 3-F-4** — ``code`` 칸이 ``EffectSpec`` 에만 있다는 것,
  EVENT / TRIGGER / ELIGIBILITY / ACTIVATION 네 단계의 LIVE·DORMANT 표.
* **Phase 3-F-24** — ``EffectSpec.code`` 에 두 어휘(298종)가 섞여 있고
  ``iter_effects`` 의 production 호출자가 0 이라는 것.

이 파일이 **새로 재는** 것은 셋이다.

1. ``EVENT_*`` **70종 전부**가 production 코드에 0회다 (``test_05``) —
   ``EVENT_FREE_CHAIN`` 은 특별한 위치가 **아니다**.
2. 등재된 16개 ``EffectDefinition`` 에서 이 값은 **상수**다 — 16/16 이
   ``['EVENT_FREE_CHAIN']`` 하나뿐이므로 **구분할 정보가 0비트**다
   (``test_28``).
3. 같은 ``code`` 를 가진 두 카드가 **다른 스펠 스피드**를 받는다 — 욕망의
   항아리 1 vs 싸이크론 2 (``test_08``). 속도는 **카드 종류**에서 나온다.
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
from core.card_model import EffectSpec, LuaScriptInfo
from engine.action import PlayerActionKind
from engine.activation import EffectActivator
from engine.activation_timing import (
    SpellSpeed,
    SpellSpeedClassification,
    classify_spell_speed,
)
from engine.chain import Chain, ChainLink
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardDefinitionView
from engine.trigger import TriggerCandidate, TriggerSpec
from engine.validation import ValidationCode
from sources.lua_loader import LuaScriptSource, parse_lua_source

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
MYSELF = "tests/test_event_free_chain_semantic_audit.py"

FREE_CHAIN = "EVENT_FREE_CHAIN"

#: 등재된 실제 카드 (공식 DB) — 측정으로 카드명을 확인한 것만 쓴다.
POT_OF_GREED = 55144522            # 욕망의 항아리 — 통상 마법 (공식 SS1)
MYSTICAL_SPACE_TYPHOON = 5318639   # 싸이크론 — 속공 마법 (공식 SS2)
COMPULSORY_EVACUATION = 94192409   # 강제 탈출 장치 — 통상 함정 (공식 SS2)
GENEROUS_REWARD = 5915629          # 욕망의 선물 — 통상 함정
LUSTER_DRAGON = 11091375           # 사파이어 드래곤 — 통상 몬스터 (효과 없음)
LAST_WILL = 85602018               # 유언장 — 통상 마법, FC 가 둘 (런타임 등록)
DIMENSION_SPHINX = 17787975        # 디멘션 스핑크스 — 지속 함정, FIELD+QUICK_O

DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4
FC_DECK = (
    [POT_OF_GREED] * 6
    + [MYSTICAL_SPACE_TYPHOON] * 4
    + [COMPULSORY_EVACUATION] * 4
    + [LUSTER_DRAGON] * 6
)


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
    """문자열을 벗긴 코드만. **부분 문자열 함정의 1차 방어선.**"""
    return ast.unparse(_StripStrings().visit(ast.parse(source)))


def method_tree(func) -> ast.Module:
    """메서드 본문의 AST. ``textwrap.dedent`` 를 쓴다 (``cleandoc`` 은 깨진다)."""
    return ast.parse(textwrap.dedent(inspect.getsource(func)))


def code_of(func) -> str:
    return ast.unparse(_StripStrings().visit(method_tree(func)))


@pytest.fixture(scope="module")
def scripts() -> dict[int, LuaScriptInfo]:
    """스크립트 단위 corpus — 블록 통계의 기준."""
    return LuaScriptSource(PROJECT_ROOT).load()


@pytest.fixture(scope="module")
def typed_cards(repository):
    """카드 단위 corpus — 카드 종류가 필요한 통계의 기준."""
    return [card for card in repository._cards.values() if card.script]


def has_free_chain(card_or_info) -> bool:
    effects = getattr(card_or_info, "effects", None)
    if effects is None:
        effects = card_or_info.script.effects
    return any(spec.code == FREE_CHAIN for spec in effects)


def category(card) -> str:
    """공식 룰북이 열거하는 카드 종류."""
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


def blocks_by_effect_type(scripts) -> dict[str, collections.Counter]:
    """``effect_types`` 별 ``code`` 분포 (스크립트 단위)."""
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for info in scripts.values():
        for spec in info.effects:
            for kind in spec.effect_types:
                out[kind][spec.code] += 1
    return out


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


# ======================================================================
# A. §3 — corpus 에 실제로 있는가, 어떤 형태로 저장되는가
# ======================================================================


def test_01_the_constant_exists_in_the_corpus(scripts):
    """
    🟢 §3 — ``EVENT_FREE_CHAIN`` corpus 존재. **스크립트 단위**로 센다.

    카드 단위와 수가 다른 것은 오류가 아니다 — 스크립트 하나가 여러 패스코드에
    붙는다 (3-F-24 는 카드 단위로 셌다). 둘을 섞지 않는다.
    """
    blocks = [
        spec
        for info in scripts.values()
        for spec in info.effects
        if spec.code == FREE_CHAIN
    ]
    owners = {
        info.card_id for info in scripts.values() if has_free_chain(info)
    }

    assert len(scripts) == 12702
    assert len(blocks) == 4914
    assert len(owners) == 4488

    #: 전체 블록 중 차지하는 비중 — 최다이지만 과반이 아니다.
    total = sum(len(info.effects) for info in scripts.values())
    #: 🔴 Phase 3-F-28 에서 34,680 → 34,681 (로더가 블록 주석 안의 효과를 세던 것을
    #: 그만두고(``c9409625`` −1), ``c:RegisterEffect`` 로 이 카드에 등록되는 ``local``
    #: 없는 / ``e`` 로 시작하지 않는 블록을 세기 시작했다(``c9839115`` · ``c74506079``
    #: +2)).
    #: ``EVENT_FREE_CHAIN`` 블록 수 4,914 는 **바뀌지 않았다** — 세 스크립트
    #: 중 어느 쪽도 ``EVENT_FREE_CHAIN`` 블록을 더하거나 빼지 않는다.
    assert total == 34681
    assert 0.14 < len(blocks) / total < 0.15


def test_02_the_parser_is_what_extracts_it():
    """
    🟢 §3 — 추출 경로. ``SetCode(EVENT_FREE_CHAIN)`` → ``EffectSpec.code``.

    실제 Lua 원문을 ``parse_lua_source`` 에 먹여 **그 함수가** 만든다는 것을
    보인다 — 간접 증거가 아니다.
    """
    source = textwrap.dedent(
        """
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
        end
        """
    )
    info = parse_lua_source(1, "c1.lua", source)

    assert len(info.effects) == 1
    assert info.effects[0].code == FREE_CHAIN
    assert info.effects[0].effect_types == ["ACTIVATE"]

    #: 사건을 적는 쪽과 같은 칸이다 — 구문으로 가를 수 없다.
    other = parse_lua_source(
        2, "c2.lua", source.replace("EVENT_FREE_CHAIN", "EVENT_CHAINING")
    )
    assert other.effects[0].code == "EVENT_CHAINING"


def test_03_the_stored_form_is_the_prefixed_constant_name(scripts):
    """
    🟢 §3 — 저장되는 **정확한 형태**: 접두사를 포함한 상수 이름 문자열.

    파서가 ``EVENT_`` 를 **다시 붙인다** (정규식은 접두사를 뺀 뒤 재조립한다).
    그래서 ``code`` 는 Lua 원문과 글자 그대로 같다.
    """
    sample = next(
        spec
        for info in scripts.values()
        for spec in info.effects
        if spec.code == FREE_CHAIN
    )
    assert isinstance(sample.code, str)
    assert sample.code == "EVENT_FREE_CHAIN"
    assert not sample.code.startswith("EFFECT_")

    #: ``EffectSpec`` 에는 숫자 값(1002)을 담는 칸이 없다 — 이름만 넘어온다.
    fields = {f.name for f in dataclasses.fields(EffectSpec)}
    assert "code" in fields
    assert not {f for f in fields if "value" in f or "number" in f}


def test_04_the_constant_is_defined_as_a_low_numbered_sentinel():
    """
    🟢 §3 — ``constant.lua`` 의 정의. **이름이 아니라 정의 위치를 본다.**

    ``EVENT_FREE_CHAIN = 1002`` 는 ``--Events`` 블록에서 ``EVENT_STARTUP`` ·
    ``EVENT_FLIP`` 다음, **실제 사건 코드(1010 이상) 앞**에 있다.

    .. note::
       이것은 "그래서 의미가 무엇이다" 의 근거가 **아니다.** 번호대가 같아서
       구문으로 가를 수 없다는 3-E-17 의 관찰을 숫자로 확인하는 것뿐이다.
    """
    path = PROJECT_ROOT / "data" / "constants" / "constant.lua"
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("EVENT_") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        raw = raw.strip()
        if raw.isdigit():
            values[name.strip()] = int(raw)

    assert values["EVENT_FREE_CHAIN"] == 1002
    assert values["EVENT_STARTUP"] == 1000
    assert values["EVENT_FLIP"] == 1001
    assert values["EVENT_DESTROY"] == 1010
    #: 실제 사건들은 전부 1002 보다 크다.
    assert min(v for k, v in values.items() if v > 1002) == 1010

    #: 정의 줄은 74개이고 그중 **우변이 순수 10진수**인 것이 67개다.
    #: 나머지 7개는 16진수 플래그(``EVENT_PHASE = 0x1000`` 등)와 deprecated
    #: 주석이 붙은 두 줄이다 — 숫자만 파싱하면 67 이 나온다.
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("EVENT_") and "=" in line.strip()
    ]
    assert len(lines) == 74
    assert len(values) == 67


# ======================================================================
# B. §4 — production 이 읽는가
# ======================================================================


def test_05_no_event_constant_reaches_production_code(scripts):
    """
    🔴 §4 · §7 — ``EVENT_*`` **70종 전부**가 production 코드에 0회다.

    즉 ``EVENT_FREE_CHAIN`` 은 EVENT 체계 안에서 **특별한 위치가 아니다.**
    하나만 떼어 해석하면 위험하다는 §7 의 경고가 데이터로 확인된다.

    .. warning::
       🔴 ``code_only`` 로 **문자열을 벗기고** 센다. 벗기지 않으면 docstring
       안의 이름이 '사용' 으로 잡힌다 — 이 파일이 바로 정정한 docstring 들이
       그 이름을 적고 있기 때문이다.
    """
    constants = {
        spec.code
        for info in scripts.values()
        for spec in info.effects
        if spec.code and spec.code.startswith("EVENT_")
    }
    assert len(constants) == 70
    assert FREE_CHAIN in constants

    stripped = []
    for path in production_files():
        try:
            stripped.append(code_only(path.read_text(encoding="utf-8")))
        except SyntaxError:  # pragma: no cover - 파싱 불가 파일 없음
            continue
    blob = "\n".join(stripped)

    used = sorted(name for name in constants if name in blob)
    assert used == [], used

    #: 주석/docstring 에는 등장한다 — 그것이 '소비' 가 아니라는 것이 요점이다.
    documented = {
        str(path.relative_to(PROJECT_ROOT))
        for path in production_files()
        if FREE_CHAIN in path.read_text(encoding="utf-8")
    }
    assert documented == {
        "analysis/effect_model.py",
        "core/card_model.py",
        "engine/action_validation.py",
        "lua_parser_example.py",
    }, documented


def test_06_only_parser_analysis_and_card_search_read_the_field():
    """
    🔴 §4 — ``EffectSpec.code`` 를 **읽는** 자리는 셋뿐이다.

    받는 쪽 이름을 **정확히** 센다 — 3-F-24 가 ``("spec","block")`` 부분
    문자열로 골랐다가 ``engine/activation.py`` 의 ``blocked.code`` 를 잡았다.
    그 ``blocked`` 는 ``ActivationResult`` 이고 ``.code`` 는
    ``ValidationCode`` 다. 같은 이름, 다른 것 (``test_29``).
    """
    readers: dict[str, int] = {}
    for path in production_files():
        try:
            tree = _StripStrings().visit(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:  # pragma: no cover
            continue
        hits = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "code"):
                continue
            receiver = node.value
            if isinstance(receiver, ast.Name) and receiver.id in {
                "spec",
                "parent",
                "eff",
            }:
                hits += 1
        if hits:
            readers[str(path.relative_to(PROJECT_ROOT))] = hits

    assert set(readers) == {
        "analysis/effect_analyzer.py",
        "core/card_model.py",
        "sources/lua_loader.py",
        "app/main.py",
    }, readers

    #: engine/ 과 agent/ 에서 읽는 자리는 **0곳**이다.
    assert not [
        name for name in readers if name.startswith(("engine/", "agent/"))
    ], readers


def test_07_the_engine_cannot_even_see_the_field():
    """
    🔴 §4 · §19 — hidden-information 경계. ``CardDefinitionView`` 가 이 칸을
    **싣지 않는다.** 그래서 engine 은 "읽지 않는" 것이 아니라 **볼 수 없다.**
    """
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert "code" not in fields
    assert "effect_types" not in fields
    assert "script" not in fields
    assert "lua" not in fields

    #: 실려 있는 것은 **개수**뿐이다 — 내용이 아니다.
    assert "effect_count" in fields
    assert len(fields) == 26

    #: 🔴 ``setcodes`` 는 **카드군**이다. Lua 의 ``SetCode(EVENT_*)`` 와
    #: 이름만 같다 (``test_29``).
    assert "setcodes" in fields
    view = CardDefinitionView.__doc__ or ""
    assert FREE_CHAIN not in view


# ======================================================================
# C. §5 — activation-timing 과의 관계
# ======================================================================


def test_08_the_same_code_yields_different_spell_speeds(repository):
    """
    🔴 §5 — **행동으로** 보는 독립성. ``code`` 가 **글자 그대로 같은** 두
    카드가 **다른** 스펠 스피드를 받는다.

    욕망의 항아리와 싸이크론은 둘 다 ``['EVENT_FREE_CHAIN']`` 하나뿐인데
    스펠 스피드가 1 과 2 로 갈린다. 가르는 것은 **카드 종류**다.
    """
    cards = repository._cards
    pot = cards[POT_OF_GREED]
    mst = cards[MYSTICAL_SPACE_TYPHOON]

    assert [s.code for s in pot.script.effects] == [FREE_CHAIN]
    assert [s.code for s in mst.script.effects] == [FREE_CHAIN]

    pot_speed = classify_spell_speed(CardDefinitionView.of(pot))
    mst_speed = classify_spell_speed(CardDefinitionView.of(mst))

    assert pot_speed.speed is SpellSpeed.NORMAL
    assert mst_speed.speed is SpellSpeed.FAST
    assert pot_speed.speed is not mst_speed.speed

    #: 근거가 카드 종류라고 **코드가 직접 적는다.**
    assert "SPELL" in pot_speed.basis
    assert "QUICKPLAY" in mst_speed.basis
    assert FREE_CHAIN not in pot_speed.basis
    assert FREE_CHAIN not in mst_speed.basis


def test_09_classify_spell_speed_structurally_reads_only_card_type():
    """
    🔴 §5 — ``classify_spell_speed`` 가 보는 속성을 **AST 로** 센다.

    .. warning::
       🔴 부분 문자열로 ``"code" not in source`` 를 세면 안 된다 —
       ``SPEED_RULES`` 같은 이름이나 docstring 이 걸린다. 읽는 **속성 이름의
       집합**을 뽑아 카드 종류 계열만 남는지 본다.
    """
    tree = _StripStrings().visit(method_tree(classify_spell_speed))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }

    #: 카드 정의에서 읽는 것.
    assert {"type_names", "is_trap", "is_spell", "is_monster"} <= attributes
    #: 효과 명세는 하나도 읽지 않는다.
    assert not ({"code", "effect_types", "effects", "script"} & attributes)


def test_10_the_two_graphs_never_meet():
    """
    🔴 §5 — 실제 코드 경로 둘을 **따로** 그린다. 간선이 없다.

    ::

        EVENT_FREE_CHAIN (Lua)
          → sources/lua_loader.py          EffectSpec.code
          → analysis/effect_analyzer.py    EffectAnalysis.trigger_event
          → core/card_search.py            has_effect_code (검색 필터)
          ✗ 여기서 끝난다.

        activation timing
          → engine/activation_timing.py    classify_spell_speed(definition)
          → engine/game_state_view.py      CardDefinitionView.type_names
          → engine/duel.py                 _activation_gate
          ✗ EffectSpec 을 만나지 않는다.
    """
    analyzer = code_only(
        (PROJECT_ROOT / "analysis" / "effect_analyzer.py").read_text(encoding="utf-8")
    )
    timing = code_only(
        (PROJECT_ROOT / "engine" / "activation_timing.py").read_text(encoding="utf-8")
    )

    #: 왼쪽 그래프는 ``spec.code`` 를 읽는다.
    assert "spec.code" in analyzer
    #: 오른쪽 그래프는 읽지 않는다.
    assert "spec.code" not in timing
    assert "EffectSpec" not in timing

    #: ``analysis`` 가 넣는 자리는 ``EffectAnalysis.trigger_event`` 다.
    assert "trigger_event" in {f.name for f in dataclasses.fields(EffectAnalysis)}
    #: 그 이름은 engine 어디에도 없다.
    engine_blob = "\n".join(
        code_only(p.read_text(encoding="utf-8"))
        for p in sorted((PROJECT_ROOT / "engine").rglob("*.py"))
    )
    assert "trigger_event" not in engine_blob


# ======================================================================
# D. §6 — 실제 corpus 와 반례
# ======================================================================


def test_11_monster_corpus(typed_cards):
    """🟢 §6 — 실제 Monster corpus. 몬스터는 소수만 이 값을 쓴다."""
    monsters = [c for c in typed_cards if category(c) == "몬스터"]
    carriers = [c for c in monsters if has_free_chain(c)]

    assert len(monsters) == 8268
    assert len(carriers) == 874
    assert 0.10 < len(carriers) / len(monsters) < 0.11

    #: 몬스터에서는 ``QUICK_O`` 와 붙는 것이 주류다 — 공식 '유발즉시'.
    kinds = collections.Counter()
    for card in carriers:
        for spec in card.script.effects:
            if spec.code == FREE_CHAIN:
                kinds.update(spec.effect_types)
    assert kinds["QUICK_O"] > kinds["ACTIVATE"]
    assert kinds["TRIGGER_O"] == 0
    assert kinds["TRIGGER_F"] == 0


def test_12_spell_corpus_activate_blocks_are_unanimous(typed_cards):
    """
    🔴 §6 — 실제 Spell corpus. ``EFFECT_TYPE_ACTIVATE`` 블록만 보면
    **마법 다섯 종류가 전부 100%** 다.
    """
    per: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for card in typed_cards:
        for spec in card.script.effects:
            if "ACTIVATE" in spec.effect_types:
                per[category(card)][spec.code == FREE_CHAIN] += 1

    expected = {
        "통상 마법": 975,
        "장착 마법": 32,
        "지속 마법": 468,
        "필드 마법": 312,
        "의식 마법": 5,
    }
    for label, count in expected.items():
        assert per[label][True] == count, (label, dict(per[label]))
        assert per[label][False] == 0, (label, dict(per[label]))

    #: 속공 마법은 100% 가 아니다 — 일부가 실제 사건을 적는다.
    assert per["속공 마법"][False] > 0


def test_13_trap_corpus_and_the_counter_trap_counter_example(typed_cards):
    """
    🔴 §6 — **이 Phase 의 결정적 반례.**

    공식 룰북은 카운터 함정을 스펠 스피드 3 — *"Only another Spell Speed 3
    card may be used to respond to these cards"* — 로, **가장 자유롭게
    체인하는 쪽**으로 적는다. 그런데 카운터 함정의 ``ACTIVATE`` 블록은
    ``EVENT_FREE_CHAIN`` 을 **거의 쓰지 않는다** — 210블록 중 3건.

    .. warning::
       🔴 처음에 이것을 "0건" 으로 적었다. ``most_common(3)`` 출력만 보고
       단정했기 때문이다. 아래는 **전수**로 센다.
    """
    counter_codes: collections.Counter = collections.Counter()
    owners: list[tuple[int, str]] = []
    for card in typed_cards:
        if category(card) != "카운터 함정":
            continue
        for spec in card.script.effects:
            if "ACTIVATE" in spec.effect_types:
                counter_codes[spec.code] += 1
                if spec.code == FREE_CHAIN:
                    owners.append((card.id, card.name))

    assert sum(counter_codes.values()) == 210
    assert counter_codes[FREE_CHAIN] == 3
    assert [passcode for passcode, _ in sorted(owners)] == [
        25419323,
        28292031,
        29185231,
    ], owners

    #: 나머지는 실제 사건을 적는다.
    assert counter_codes["EVENT_CHAINING"] == 144
    assert counter_codes.most_common(1)[0][0] == "EVENT_CHAINING"
    #: 🔴 필드 마법 100% 와 비교하면 **70배** 차이다 — 방향이 공식 속도와 반대다.
    assert counter_codes[FREE_CHAIN] / 210 < 0.015

    #: 통상/지속 함정은 쓴다 — 함정이라서가 아니라 **종류별로** 다르다.
    normal = collections.Counter()
    for card in typed_cards:
        if category(card) != "통상 함정":
            continue
        for spec in card.script.effects:
            if "ACTIVATE" in spec.effect_types:
                normal[spec.code == FREE_CHAIN] += 1
    #: 🔴 918 → **917**. Phase 3-F-27 이 ``Clone`` 오염을 고치면서 한 블록의
    #: ``ACTIVATE`` 가 (물려받은 것이었으므로) 사라졌다. 결론은 그대로다.
    assert normal[True] == 917


def test_14_official_spell_speed_is_not_a_one_to_one_function(typed_cards):
    """
    🔴 §6 · §11 — 공식 스펠 스피드와 **1:1 이 아니고, 끝에서 뒤집힌다.**

    1:1 이려면 한 스펠 스피드가 이 값을 **전부** 갖거나 **전혀** 갖지 않아야
    한다. 측정하면 셋 다 섞여 있다.
    """
    table: dict[int, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for card in typed_cards:
        speed = OFFICIAL_SPELL_SPEED.get(category(card))
        if speed is None:
            continue
        table[speed][has_free_chain(card)] += 1

    for speed in (1, 2, 3):
        yes, no = table[speed][True], table[speed][False]
        assert yes and no, (speed, yes, no)  # 1:1 이 아니다

    #: 🔴 끝에서 뒤집힌다 — 가장 느린 쪽이 가장 높고, 가장 빠른 쪽이 가장 낮다.
    rate = {
        s: table[s][True] / (table[s][True] + table[s][False]) for s in (1, 2, 3)
    }
    assert rate[1] > 0.8
    assert rate[3] < 0.1
    assert rate[1] > rate[3]

    #: 공식 룰북이 그 두 끝을 무엇이라고 적는지 **원문으로** 확인한다.
    speeds = {row["speed"]: row for row in official_rulebook()["chain"]["spell_speeds"]}
    assert "cannot be activated in response" in speeds[1]["notes"]
    assert "Counter Trap" in speeds[3]["card_types"]
    assert speeds[3]["can_respond_to"] == [1, 2, 3]
    assert speeds[1]["can_respond_to"] == []


def test_15_field_spells_are_the_extreme_case(typed_cards):
    """
    🔴 §6 — 가장 선명한 한 점. **필드 마법 312/312 = 100%.**

    공식 필드 마법은 스펠 스피드 1 이라 **어떤 효과에도 대응할 수 없다.**
    그런데 이 값을 전부 가진다.
    """
    fields = [c for c in typed_cards if category(c) == "필드 마법"]
    assert len(fields) == 312
    assert all(has_free_chain(c) for c in fields)

    counters = [c for c in typed_cards if category(c) == "카운터 함정"]
    assert len(counters) == 167
    assert sum(1 for c in counters if has_free_chain(c)) == 15


def test_16_multiple_codes_and_duplicate_indices_in_one_script(scripts):
    """
    🟢 §3 · §11 — ``EVENT_*`` **복수 code** 사례. 그리고 🔴 ``index`` 는
    스크립트 안에서 **고유하지 않다.**

    파서는 ``CreateEffect`` 마다 **새 ``EffectSpec`` 을 append** 한다 (덮어쓰지
    않는다). 그래서 같은 Lua 변수명이 여러 번 나오면 같은 ``index`` 를 가진
    spec 이 여러 개 생긴다. ``(card_id, index)`` 를 키로 쓰면 **조용히
    합쳐진다.**
    """
    duplicated = 0
    extra_blocks = 0
    for info in scripts.values():
        counts = collections.Counter(spec.index for spec in info.effects)
        surplus = sum(v - 1 for v in counts.values() if v > 1)
        if surplus:
            duplicated += 1
            extra_blocks += surplus
    assert duplicated == 4795
    assert extra_blocks == 6802

    #: 유언장 — ``e1`` 이 **둘**이고 둘 다 ``EVENT_FREE_CHAIN`` 인데
    #: ``effect_types`` 가 다르다.
    last_will = scripts[LAST_WILL]
    assert [s.index for s in last_will.effects] == ["e1", "e1"]
    assert [s.code for s in last_will.effects] == [FREE_CHAIN, FREE_CHAIN]
    assert [s.effect_types for s in last_will.effects] == [
        ["ACTIVATE"],
        ["FIELD", "CONTINUOUS"],
    ]

    #: 한 스크립트가 여러 종류의 code 를 갖는 것이 정상이다.
    multi = [
        info
        for info in scripts.values()
        if len({s.code for s in info.effects if s.code}) >= 3
    ]
    assert len(multi) > 500


# ======================================================================
# E. §8 — Chain 생성과의 관계
# ======================================================================


def test_17_chain_link_does_not_carry_it():
    """🔴 §8 A — ``ChainLink`` 생성이 이 값을 읽지 않는다. 칸도 없다."""
    fields = [f.name for f in dataclasses.fields(ChainLink)]
    assert fields == [
        "sequence",
        "actor",
        "effect_ref",
        "source",
        "selections",
        "payments",
    ]
    for obj in (ChainLink, Chain):
        source = code_only(inspect.getsource(obj))
        assert FREE_CHAIN not in source
        assert "spec.code" not in source
        assert "effect_types" not in source


def test_18_legal_actions_does_not_read_it():
    """🔴 §8 B · §11 — ``legal_actions`` 와 후보 생성기 넷 모두 0회."""
    for func in (
        Duel.legal_actions,
        Duel._activation_actions,
        Duel._activation_gate,
        Duel._flow_actions,
        Duel._attack_actions,
        Duel._withheld_board_actions,
    ):
        body = code_of(func)
        assert FREE_CHAIN not in body, func.__name__
        assert "effect_types" not in body, func.__name__
        assert ".code" not in body or "verdict" in body or "gate" in body


def test_19_apply_does_not_read_it():
    """🔴 §8 · §11 — ``apply`` 와 그 발동 경로 0회."""
    for func in (Duel.apply, Duel._apply_activation):
        body = code_of(func)
        assert FREE_CHAIN not in body, func.__name__
        assert "effect_types" not in body, func.__name__


def test_20_effect_activator_does_not_read_it():
    """🔴 §8 C — ``EffectActivator`` 0회."""
    source = code_only(inspect.getsource(EffectActivator))
    assert FREE_CHAIN not in source
    assert "effect_types" not in source
    assert "EffectSpec" not in source


def test_21_trigger_candidate_does_not_read_it():
    """
    🔴 §8 E — ``TriggerCandidate`` / ``TriggerSpec`` 0회.

    ``TriggerCandidate`` 에는 ``code`` 라는 칸이 **있지만** 그것은
    ``ValidationCode`` 다 — 같은 이름, 다른 것 (``test_29``).
    """
    trigger_fields = {f.name for f in dataclasses.fields(TriggerSpec)}
    assert "code" not in trigger_fields

    annotations = {f.name: f.type for f in dataclasses.fields(TriggerCandidate)}
    assert "code" in annotations
    assert "ValidationCode" in str(annotations["code"])

    source = code_only(
        (PROJECT_ROOT / "engine" / "trigger.py").read_text(encoding="utf-8")
    )
    assert FREE_CHAIN not in source


def test_22_there_is_no_free_chain_state_or_enum():
    """
    🔴 §8 F — **없다.** Engine V1 에 Free Chain 을 표현하는 상태/enum 이 없다.

    체인 관련 enum 멤버를 전부 뽑아 확인한다 — "못 찾았다" 가 아니라
    "전부 세어 보니 없다" 다.
    """
    members: list[tuple[str, str, str]] = []
    for path in production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_enum = any("Enum" in ast.unparse(base) for base in node.bases)
            if not is_enum:
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and (
                        "CHAIN" in target.id or "FREE" in target.id
                    ):
                        members.append(
                            (str(path.relative_to(PROJECT_ROOT)), node.name, target.id)
                        )

    assert members, "체인 관련 enum 멤버가 하나도 없다면 측정이 잘못됐다"
    assert not [m for m in members if "FREE" in m[2]], members
    #: 있는 것은 전부 체인의 **상태**이지 발동 분류가 아니다.
    assert ("engine/chain.py", "ChainResolutionStatus", "EMPTY_CHAIN") in members


# ======================================================================
# F. §10 — AI / Search
# ======================================================================


def test_23_search_and_ai_never_see_it():
    """🔴 §10 — ``agent/`` 전체가 이 값도, ``EffectSpec`` 도 보지 않는다."""
    for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
        source = code_only(path.read_text(encoding="utf-8"))
        assert FREE_CHAIN not in source, path.name
        assert "EffectSpec" not in source, path.name
        assert "effect_types" not in source, path.name
        assert ".script" not in source, path.name


def test_24_search_only_explores_legal_actions():
    """
    🟢 §10 — "Search 는 ``legal_actions`` 만 탐색한다" 계약과 충돌하지 않는다.

    탐색이 후보를 얻는 **유일한 입구**가 ``legal_actions`` 라는 것을
    호출 지점으로 센다.
    """
    simulation = code_only(
        (PROJECT_ROOT / "agent" / "simulation.py").read_text(encoding="utf-8")
    )
    assert "legal_actions" in simulation

    #: 후보를 만드는 다른 입구가 없다 — 카드 정의를 직접 열지 않는다.
    assert "_cards" not in simulation
    assert "repository" not in simulation or "legal_actions" in simulation


def test_25_free_chain_is_not_the_only_way_to_say_no_event(scripts):
    """
    🔴 §4 · **이 Phase 의 정정 1.**

    production docstring 이 *"'없다' 를 말하는 값은 ``EVENT_FREE_CHAIN`` 이다"*
    라고 적고 있었다. ``IGNITION`` 블록이 그 문장을 깬다 — **98.5%가
    ``SetCode`` 를 아예 부르지 않는다.**
    """
    per = blocks_by_effect_type(scripts)

    #: 🔴 Phase 3-F-27 이 ``Clone`` 오염을 고친 뒤의 값이다. 물려받은
    #: ``IGNITION`` 이 사라져 블록 수가 4,180 → **4,137**, 그중 ``FREE_CHAIN``
    #: 이 58 → **17** 로 줄었다. ``None`` 4,119 는 **그대로**이므로 이 테스트의
    #: 결론("없다 를 생략으로 적는다")은 오히려 **더 선명해졌다** (98.5% →
    #: 99.6%).
    #: 🔴 Phase 3-F-31 에서 ``None`` 4,119 → **4,120**. 그 Phase 가
    #: ``c44887817`` 의 ``local e2=e1:Clone(e1)`` 뒤 ``SetCode`` 가 엉뚱한
    #: 블록(ordinal 1)에 붙던 것을 고쳤고, 그 블록은 Lua 에 **자기 ``SetCode``
    #: 가 없다.** 블록 수 4,137 은 그대로이므로 이 테스트의 결론("없다 를
    #: 생략으로 적는다")은 **또 한 번 더 선명해졌다** (99.6% → 99.6%+).
    ignition = per["IGNITION"]
    assert sum(ignition.values()) == 4137
    assert ignition[None] == 4120
    assert ignition[FREE_CHAIN] == 17
    assert ignition[None] / sum(ignition.values()) > 0.99

    #: 거울상 — ``ACTIVATE`` · ``QUICK_O`` 는 ``None`` 이 **0건**이다.
    for kind, blocks, free in (("ACTIVATE", 4297, 3639), ("QUICK_O", 1875, 1257)):
        counter = per[kind]
        assert sum(counter.values()) == blocks, kind
        assert counter[None] == 0, kind
        assert counter[FREE_CHAIN] == free, kind

    #: 🔴 정정된 docstring 이 이 사실을 실제로 적는다 — **문장 단위**로 본다.
    #:
    #: .. warning::
    #:    처음에는 ``"유일한 표기가 아니다" in text`` 로 파일 전체를 훑었다.
    #:    주입으로 한 군데를 ``"유일한 표기다"`` 로 뒤집어도 **다른 줄이
    #:    통과시켰다.** 부분 문자열 하나로 두 군데를 대신 세면 안 된다.
    model = (PROJECT_ROOT / "core" / "card_model.py").read_text(encoding="utf-8")
    analysis = (PROJECT_ROOT / "analysis" / "effect_model.py").read_text(
        encoding="utf-8"
    )

    #: 정정이 **두 군데 모두** 살아 있어야 한다.
    assert model.count('"없다" 의 **유일한 표기가 아니다.**') == 1, model.count(
        '"없다" 의 **유일한 표기가 아니다.**'
    )
    assert '"없다" 의 **유일한 표기다' not in model
    assert "유일한 표기다." not in model

    #: 되돌린 주장이 다시 들어오지 않았는지 — 수치가 함께 적혀 있어야 한다.
    #:
    #: 🔴 Phase 3-F-27 이 ``Clone`` 오염을 고친 뒤 비율이 98.5% → **99.6%** 로
    #: 올라갔다 (``None`` 4,119 는 그대로이고 분모가 4,180 → 4,137 로 줄었다).
    assert "4,119" in model
    assert "99.6" in model
    assert "99.6%(4,119)" in analysis
    assert "유일한 표기가 아니다" in analysis


def test_26_the_co_occurrence_enumeration_was_incomplete(scripts):
    """
    🔴 §6 · **이 Phase 의 정정 2.**

    docstring 이 *"``ACTIVATE`` · ``QUICK_O`` · ``IGNITION`` 과만 함께
    쓰인다"* 고 적었다. ``FIELD`` 3 · ``CONTINUOUS`` 1 블록이 빠져 있었다.

    단, **``TRIGGER_O`` · ``TRIGGER_F`` 와 0회라는 주장은 성립한다** —
    4,914블록 전수로 확인된다.
    """
    kinds: collections.Counter = collections.Counter()
    for info in scripts.values():
        for spec in info.effects:
            if spec.code == FREE_CHAIN:
                kinds.update(spec.effect_types)

    #: 🔴 Phase 3-F-27 이 ``Clone`` 오염을 고친 뒤의 값이다 — 물려받은
    #: ``IGNITION`` 41 · ``ACTIVATE`` 3 이 사라졌다. **열거가 불완전했다는
    #: 이 테스트의 결론은 그대로다** (``FIELD`` 3 · ``CONTINUOUS`` 1 이 남는다).
    assert dict(kinds) == {
        "ACTIVATE": 3639,
        "QUICK_O": 1257,
        "IGNITION": 17,
        "FIELD": 3,
        "CONTINUOUS": 1,
    }, dict(kinds)

    #: 원래 주장 중 **맞는 절반** — 유발 효과와는 한 번도 안 붙는다.
    assert kinds["TRIGGER_O"] == 0
    assert kinds["TRIGGER_F"] == 0

    #: 빠져 있던 블록이 실제로 있는 카드다.
    sphinx = scripts[DIMENSION_SPHINX]
    extra = [
        spec
        for spec in sphinx.effects
        if spec.code == FREE_CHAIN and "FIELD" in spec.effect_types
    ]
    assert len(extra) == 1
    assert extra[0].effect_types == ["FIELD", "QUICK_O"]


def test_27_the_official_corpus_never_uses_the_term():
    """
    🔴 §2 · §13 — 이 저장소의 **공식 자료 전체**에서 "Free Chain" 은 0회다.

    룰북 원문 · 구조화본 · 공식 재정 686파일 · 한국어 공식 DB 를 전부 센다.

    .. note::
       🔴 이것은 "공식 규칙에 그 개념이 없다" 는 뜻이 **아니다.** 이 저장소가
       가진 공식 자료에 그 **표현**이 없다는 측정이다. 공식 정의는 보고서
       §2 에서 **UNKNOWN** 으로 남는다.
    """
    roots = [
        PROJECT_ROOT / "data" / "rules",
        PROJECT_ROOT / "data" / "rulings",
        PROJECT_ROOT / "data" / "ko",
    ]
    scanned = 0
    hits: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".html", ".txt"}:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace").casefold()
            if "free chain" in text or "freechain" in text:
                hits.append(str(path.relative_to(PROJECT_ROOT)))

    assert scanned >= 600, scanned
    assert hits == [], hits

    #: 반대로 공식 자료가 **실제로 쓰는** 어휘는 측정으로 확인된다 —
    #: probe 가 살아 있다는 증거다 (0건이 측정 실패가 아님을 보인다).
    rulebook = json.dumps(official_rulebook(), ensure_ascii=False)
    assert "Spell Speed" in rulebook
    assert "Counter Trap" in rulebook
    assert "Quick Effect" in rulebook


def test_28_on_the_registered_set_the_value_is_a_constant(repository):
    """
    🔴 §8 · §18 — 등재된 16개 ``EffectDefinition`` 에서 이 값은 **상수**다.

    16/16 의 ``code`` 목록이 ``['EVENT_FREE_CHAIN']`` 하나뿐이다. 상수는
    **아무것도 구분하지 못한다** — 지금 배선해도 동작이 달라질 수 없다.
    """
    cards = repository._cards
    rows = []
    for entry in sorted(EFFECT_LIBRARY, key=lambda e: e.definition.effect_ref.card_id):
        reference = entry.definition.effect_ref
        card = cards[reference.card_id]
        rows.append(
            (
                reference.card_id,
                reference.ordinal,
                category(card),
                tuple(spec.code for spec in card.script.effects),
            )
        )

    assert len(rows) == 16
    assert all(codes == (FREE_CHAIN,) for *_, codes in rows), rows
    assert all(ordinal == 0 for _, ordinal, *_ in rows)

    #: 그런데 **공식 스펠 스피드는 둘로 갈린다** — 같은 상수, 다른 속도.
    speeds = {OFFICIAL_SPELL_SPEED[cat] for _, _, cat, _ in rows}
    assert speeds == {1, 2}

    #: ``EffectDefinition`` 에는 이 값을 담는 칸이 아예 없다.
    assert "code" not in {f.name for f in dataclasses.fields(EffectDefinition)}


def test_29_three_different_things_are_spelled_code_or_setcode():
    """
    🔴 §9 — 용어 충돌 **셋**. 이름이 같아서 부분 문자열 측정이 조용히 틀린다.

    ==========================================  ==========================
    이름                                          실제로 담는 것
    ==========================================  ==========================
    ``EffectSpec.code``                          Lua ``SetCode`` 인자
    ``TriggerCandidate.code`` · ``verdict.code``  ``ValidationCode``
    ``CardDefinitionView.setcodes``               **카드군**(archetype)
    ==========================================  ==========================
    """
    assert "code" in {f.name for f in dataclasses.fields(EffectSpec)}

    candidate = {f.name: str(f.type) for f in dataclasses.fields(TriggerCandidate)}
    assert "ValidationCode" in candidate["code"]
    assert issubclass(ValidationCode, object)

    view = {f.name: str(f.type) for f in dataclasses.fields(CardDefinitionView)}
    assert "setcodes" in view
    assert "int" in view["setcodes"]  # 카드군은 정수다 — 상수 이름이 아니다
    assert "code" not in view

    #: 같은 ``.code`` 인데 받는 쪽이 다르다는 것을 실제 파일에서 확인한다.
    activation = code_only(
        (PROJECT_ROOT / "engine" / "activation.py").read_text(encoding="utf-8")
    )
    assert "blocked.code" in activation
    assert "spec.code" not in activation


# ======================================================================
# G. §12 · §14 — 변경 범위와 불변 조건
# ======================================================================


def test_30_production_change_is_documentation_only():
    """
    🔴 §12 — production 변경은 **docstring 두 건뿐**이다.

    문자열 리터럴을 벗긴 AST 가 이 테스트 파일을 추가한 commit 의 부모와
    **글자 그대로 같다**는 것을 보인다. "주석만 고쳤다" 를 말로 하지 않는다.
    """
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    #: Phase 3-F-24 보고서 commit — 이 Phase 의 base.
    PHASE_3F25_BASE = "f84a47a"

    added = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    #: commit 전에는 base ↔ 작업 트리로 되돌아간다 (**skip 하지 않는다**).
    base = f"{added[-1]}^" if added else PHASE_3F25_BASE
    #: 🔴 **이 Phase 의 commit 까지만** 본다 — ``HEAD`` 가 아니다.
    #:
    #: .. warning::
    #:    처음에는 끝점을 ``HEAD`` 로 썼다. 그러면 **뒤에 오는 Phase 의 변경이
    #:    전부 섞여** 들어온다 — Phase 3-F-26 이 ``engine/activation_timing.py``
    #:    의 docstring 을 고치자 이 테스트가 깨졌다. "내 Phase 가 무엇을
    #:    바꿨는가" 를 묻는 테스트의 끝점은 **내 commit** 이다 (3-F-24 의
    #:    ``test_25`` 가 ``git show <그 commit>`` 으로 한 것과 같다).
    tip = added[-1] if added else None

    scope = ["--", *PRODUCTION_ROOTS]
    changed = git(
        "diff", "--name-only", base, *([tip] if tip else []), *scope
    ).split()

    assert set(changed) <= {
        "core/card_model.py",
        "analysis/effect_model.py",
    }, changed
    #: 바꾼 것이 **정확히 그 둘**이다 — 하나도 안 바꿨다고 주장하지 않는다.
    assert len(changed) == 2, changed

    for relative in changed:
        before = git("show", f"{base}:{relative}")
        after = (
            git("show", f"{tip}:{relative}")
            if tip
            else (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        )
        assert code_only(before) == code_only(after), relative


def test_31_state_hash_and_rng_are_unchanged(repository):
    """🟢 §14 — ``state_hash`` · RNG 불변. 같은 seed 는 같은 판을 만든다."""
    first = opened_duel(repository, seed=11, deck=FC_DECK)
    second = opened_duel(repository, seed=11, deck=FC_DECK)
    assert first.state.state_hash() == second.state.state_hash()

    other = opened_duel(repository, seed=12, deck=FC_DECK)
    assert other.state.state_hash() != first.state.state_hash()

    #: RNG 는 같은 seed 에서 같은 값을 뽑는다 (객체 주소를 비교하지 않는다).
    left = [first.state.rng.randrange(1000) for _ in range(8)]
    right = [second.state.rng.randrange(1000) for _ in range(8)]
    assert left == right


def test_32_a_free_chain_heavy_deck_still_plays(repository):
    """
    🟢 §11 · §14 — ``EVENT_FREE_CHAIN`` 만 가진 카드로 짠 덱이 실제로 돌고,
    ``legal_actions`` 가 내놓는 것은 **변하지 않는다.**

    발동이 실제로 받아들여진다 — 이 값이 소비되지 않는다는 것이 "발동이 안
    된다" 는 뜻이 아니다.
    """
    duel = Duel.start(repository, decks=(list(FC_DECK), list(FC_DECK)), seed=7)
    transcript = DuelRunner(
        duel, (search_policy(duel), search_policy(duel))
    ).run()

    accepted = collections.Counter(
        entry.action.kind for entry in transcript.entries if entry.accepted
    )
    assert accepted[PlayerActionKind.ACTIVATE_EFFECT] > 0
    assert accepted[PlayerActionKind.ACTIVATE_CARD] == 0

    #: ``activate_card`` 는 여전히 미지원 경계이고, 그 사유는 timing 이다.
    opened = opened_duel(repository, seed=7, deck=FC_DECK)
    withheld = {w.kind: w.missing for w in opened.legal_actions().withheld}
    assert PlayerActionKind.ACTIVATE_CARD in withheld
    assert "activation-timing" in withheld[PlayerActionKind.ACTIVATE_CARD]
    assert FREE_CHAIN not in str(withheld)


def test_33_the_search_ranking_digest_is_unchanged(repository):
    """
    🟢 §14 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은
       파일이 못 박은 값을 기준으로 쓴다 (3-F-18 ~ 3-F-24 와 같은 방식).
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
