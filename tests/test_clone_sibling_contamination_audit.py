"""
Phase 3-F-29 — ``Clone`` 형제 간 누적 감사 및 최소 수정.

판정: **C. CONFIRMED_PARSER_CLONE_ACCUMULATION**

🔴 "형제 오염" 은 **없었다** — A 도 B 도 아니다
------------------------------------------------
지시서 §2 의 최소 사례를 production 파서로 그대로 돌렸다.

======================================= =========
질문                                    실측
======================================= =========
D. ``e2`` 를 바꾸면 ``e3`` 가 영향받는가  **아니다**
E. ``e2`` 를 바꾸면 ``e1`` 이 영향받는가  **아니다**
F. ``e3`` 를 바꾸면 ``e2`` 가 영향받는가  **아니다**
======================================= =========

``clone`` 분기가 다섯 목록 칸을 **전부 ``list(parent.X)`` 로 새 객체**로 만든다.
corpus 전체 2,744 Clone 블록에서 가변 컨테이너를 공유하는 두 블록은 **0쌍**이다
(3-F-27 ``test_20`` 이 이미 전수로 고정했고 이 Phase 에서도 유지된다).
``EffectSpec`` 의 칸은 ``list[str]`` 과 스칼라뿐이라 **중첩 가변 구조 자체가
없다** (``test_10``). 그래서 **A · B 는 기각**이다.

🔴 실제 문제는 **부모 상태의 과잉 상속**이었다 — 그래서 C 다
-------------------------------------------------------------
``Clone`` 은 부모 값을 물려주고(정상), 자식이 자기 ``SetX`` 를 부르면 파서가
그것을 **물려받은 값에 더했다**::

    spec.categories = _strip_prefix(spec.categories + _RE_CATEGORY.findall(args))

``effect_types`` 는 Phase 3-F-27 이 이미 "첫 설정자는 덮어쓴다" 로 고쳤는데,
**같은 ``clone`` 분기가 물려주는 나머지 네 칸**은 그대로 더하기였다. 즉 파서가
같은 자리에서 **칸마다 다른 규칙**을 쓰고 있었다.

🔴 덮어쓰기가 맞다는 근거 — **저장소 내부 증거만** 쓴다
--------------------------------------------------------
EDOPro 의 ``SetCategory`` · ``SetProperty`` · ``SetRange`` ·
``SetTargetRange`` API 가 대입인지 OR 인지는 이 저장소에 문서화돼 있지 않다.
그래서 Lua 의미를 추측하지 않고 corpus 로만 판단했다.

1. **자식이 물려받은 플래그를 자기 호출에 다시 적는 블록이 43개다**
   (``target_ranges`` 11 · ``properties`` 23 · ``categories`` 8 · ``ranges`` 1).
   더하기라면 다시 적는 것은 **아무 효과도 없는 죽은 코드**다 — 서로 다른 43개
   스크립트가 그럴 이유가 없다. 덮어쓰기라면 **유지할 플래그를 반드시 다시
   적어야 한다.** 실제 모양이 정확히 그것이다 (``test_36``).
2. **명시적으로 비우는 스크립트가 있다** — ``c18438874`` ``e2`` 와
   ``c55262310`` ``e2`` 가 ``SetProperty(0)`` 을 부른다. 대입이 아니면 의미가
   없는 줄이다 (``test_14``).
3. **더하기는 그 카드가 쓰지 않는 조합을 만든다.** ``c93473606`` ``e2`` 는
   ATK/DEF 를 바꾸는 효과인데 더하기로는 부모의 ``TODECK+DRAW`` 가 남는다
   (``test_38``).
4. **``effect_types`` 가 같은 결론을 이미 받았다** (3-F-27).

🔴 반대 방향 증거도 측정하고 **기각했다**
-----------------------------------------
한 블록이 같은 설정자를 **순차로** 두 번 부르며 서로 다른 값을 쓰는 사례가
``properties`` 에 5건 있다 — 더하기 쪽 증거다. 그런데 그중 **4건이 같은
복사-붙여넣기 관용구**(``SetDescription(...)`` + ``SetProperty(CLIENT_HINT)``
뒤에 다른 ``SetProperty``)이고, 나머지 1건(``c76685519``)은 ``e2`` 를 쓸 자리에
``e1`` 을 쓴 **스크립트 오타**다. ``categories`` · ``ranges`` ·
``target_ranges`` 에는 그런 사례가 **0건**이다 (``test_37``).

🔴 그래서 **두 번째 이후 호출은 더하기로 남겼다.** 고친 것은 "물려받은 값을
덮어쓰는 첫 호출" 뿐이다 (``test_17``).

수정 (최소)
-----------
``sources/lua_loader.py`` 한 파일.

* ``inherited_types: dict[str, bool]`` (3-F-27) 을 ``inherited: dict[str,
  set[str]]`` 로 일반화했다 — "이 변수의 **어느 칸**이 ``Clone`` 이 물려준
  값인가".
* 네 칸의 설정자 분기를 ``_write_list`` 하나로 모았다. ``effect_types`` 의
  동작은 **글자 그대로 같다** (``test_12`` · ``test_35``).
* ``_signature`` ``v6`` → ``v7``.

새 abstraction · 새 enum · 새 public API · ``EffectSpec`` 칸 변화 — **없다.**
``EffectRef(card_id, ordinal)`` 설계 그대로이고 engine · agent 는 한 글자도
바뀌지 않았다.

영향 범위
---------
corpus 전수 비교: **59 스크립트 / 75 블록-칸 쌍**이 바뀌었고 블록 수는
**34,681 그대로**, ``ordinal`` 이 움직인 스크립트는 **0개**다. 등록된 16개
``EffectDefinition`` 은 **전부 수정 전후 동일**하고, 그 16장의 스크립트에는
``:Clone()`` 이 **하나도 없다** (``test_23``).
"""

import ast
import collections
import dataclasses
import hashlib
import inspect
import json
import pathlib
import re
import subprocess
import typing

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from core.card_model import EffectSpec, LuaScriptInfo
from engine.duel import Duel
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardDefinitionView
from engine.ids import EffectRef, effect_refs, iter_effects
import sources.lua_loader as lua_loader
from sources.lua_loader import LuaScriptSource, parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MYSELF = "tests/test_clone_sibling_contamination_audit.py"

# ======================================================================
# 측정값 — 전부 이 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

SCRIPTS = 12702
BLOCKS = 34684  # 🔴 Phase 3-F-32 에서 +3 — ``Clone`` 의 인자 있는 형태
# (``e1:Clone(e1)`` · ``e2:Clone(c)``)와 점 형태 (``Effect.Clone(e1)``)를
# 블록으로 인정했다. 세 스크립트에 효과 블록이 하나씩 생겼다.                     # 🔴 3-F-28 과 같다 — 이 Phase 는 블록을 더하지 않는다
# 🔴 Phase 3-F-32 에서 +3 — ``Clone`` 의 인자 있는 형태와 점 형태를
# 블록으로 인정했다 (c44887817 · c4997565 · c56410769).
CLONE_BLOCKS = 2747
SCRIPTS_WITH_CLONE = 2148

#: ``Clone()`` 이 물려주는 목록 칸 — 이 Phase 가 규칙을 통일한 대상.
INHERITED_LISTS = ("effect_types", "ranges", "target_ranges", "categories", "properties")

#: 같은 부모에서 Clone 이 2개 이상 나오는 묶음과 그 Clone 수 (형제 패턴).
SIBLING_GROUPS = 332
SIBLING_CLONES = 731

#: 🔴 "물려받은 값 ⊄ 자기 값" 인 Clone 블록 — 3-F-28 이 남긴 "64 blocks".
#: 현재 HEAD 에서 **다시 측정해 64 를 확인했다.**
DIVERGING = {"ranges": 12, "target_ranges": 9, "categories": 24, "properties": 19}

#: 🔴 자식이 물려받은 플래그를 자기 호출에 **다시 적는** 블록 — 덮어쓰기의 증거.
RESTATING = {"ranges": 1, "target_ranges": 11, "categories": 8, "properties": 23}

#: 한 블록이 같은 설정자를 순차로 두 번 이상 부르며 **서로 다른 값**을 쓰는 사례.
#: 🔴 ``categories`` 의 1건은 ``if``/``elseif`` **배타 분기**라서 런타임에는 한
#: 번만 실행된다 — 더하기 쪽 증거가 아니다 (``test_37`` 이 그 모양을 확인한다).
SEQUENTIAL_DISTINCT = {"ranges": 0, "target_ranges": 0, "categories": 1, "properties": 5}

#: 수정으로 바뀐 범위.
CHANGED_SCRIPTS = 59
CHANGED_PAIRS = 75                 # 블록-칸 쌍 (직접 64 + 연쇄 7 + 순서만 4)

#: 칸별 corpus 총계 — 수정 후.
TOTALS = {
    # 🔴 Phase 3-F-32 에서 ``Clone`` 의 인자 있는 형태와 점 형태를 블록으로
    # 인정해 블록 3개가 늘었다. 그 세 블록이 부모에게서 물려받거나 자기
    # 설정자로 적은 값만큼 아래 총계가 늘어난다 (``categories`` 는 세 블록
    # 모두 비어 있어 **그대로**다).
    "effect_types": 45340,         # 🔴 3-F-27 의 결과 · 3-F-32 에서 +3
    "ranges": 15064,               # 15,075 에서 −12, 3-F-32 에서 +1
    "target_ranges": 2063,         # 2,072 에서 −10, 3-F-32 에서 +1
    #: 🔴 Phase 3-F-31 에서 −2. 그 Phase 가 ``c52445243`` 의 ``local e1=e:GetLabelObject()`` 뒤 ``SetCategory`` 3건이 엉뚱한 블록에 붙던 것을 고쳤고, 그 블록의 두 category 가 사라졌다.
    "categories": 20503,           # 20,534 에서 −29, 3-F-31 에서 다시 −2
    "properties": 23887,           # 23,907 에서 −23, 3-F-32 에서 +3
}

#: 측정으로 확인한 실제 카드.
CLEAR_PROPERTY = 18438874          # e2:SetProperty(0) — 명시적으로 비운다 + 연쇄
NARROWED_TARGET = 295517           # HAND|MZONE -> MZONE 로 좁히고 e4 가 상속
CHAIN_PROPERTY = 71650854          # e3 가 좁히고 형제 e4 · e5 가 그것을 상속
FABRICATED_CATEGORY = 93473606     # TODECK+DRAW 가 ATKCHANGE+DEFCHANGE 블록에 남았다
FABRICATED_CATEGORY2 = 55262310    # POSITION+TODECK -> POSITION+LVCHANGE + SetProperty(0)
PURE_INHERITANCE = 55948544        # Clone 6개가 SetCode 만 바꾸고 나머지를 순수 상속
RESTATES_PARENT = 13708888         # CARD_TARGET+DELAY 를 다시 적고 DAMAGE_STEP 을 더한다
SEQUENTIAL_IDIOM = 73899015        # SetDescription + CLIENT_HINT 관용구 (순차 2회)
TYPO_SEQUENTIAL = 76685519         # e2 를 쓸 자리에 e1 — 스크립트 오타
BRANCHED_CATEGORY = 52445243       # if/elseif 배타 분기 안의 SetCategory 2회
SCOPE_SWAP = 63259351              # SINGLE_RANGE -> PLAYER_TARGET
RANGE_CANDIDATE = 66984907         # TOGRAVE -> TOGRAVE+TOHAND+SEARCH (재진술·확장)
CLONE_TYPE_FIX = 324483            # 3-F-27 의 IGNITION -> Clone -> QUICK_O

#: digest 용 덱 — 3-F-24 이후 모든 Phase 가 같은 것을 쓴다.
LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522
GENEROUS_REWARD = 5915629
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4

FIELD_REGEX = {
    "ranges": ("Range", lua_loader._RE_LOCATION),
    "target_ranges": ("TargetRange", lua_loader._RE_LOCATION),
    "categories": ("Category", lua_loader._RE_CATEGORY),
    "properties": ("Property", lua_loader._RE_EFFECT_FLAG),
}


# ======================================================================
# 측정 도구
# ======================================================================


def blocks_of(source: str) -> list[EffectSpec]:
    """Lua 조각 하나를 **production 파서**에 그대로 먹인다."""
    return parse_lua_source(0, "c0.lua", inspect.cleandoc(source)).effects


def script_text(card_id: int) -> str:
    return (PROJECT_ROOT / f"c{card_id}.lua").read_text(encoding="utf-8")


def parse_card(card_id: int) -> LuaScriptInfo:
    """🔴 캐시를 거치지 않고 **원문을 직접** 파싱한다 (3-E-17 의 교훈)."""
    path = PROJECT_ROOT / f"c{card_id}.lua"
    return parse_lua_source(card_id, path.name, path.read_text(encoding="utf-8"))


def opened_duel(repository, *, seed: int) -> Duel:
    duel = Duel.start(
        repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


def replay(body: str, field: str):
    """
    production 과 **같은 이벤트 흐름**을 돌면서 블록마다
    ``(상속값, 자기 호출들)`` 을 모은다.

    production 을 호출하지 않으므로 production 의 결과를 **외부에서** 검증할 수
    있다. 정규식·주석 제거·``_is_card_effect`` 는 production 것을 쓴다 —
    3-F-28 에서 그룹 번호를 따로 가정했다가 조용히 깨진 전례가 있다.
    """
    setter, regex = FIELD_REGEX[field]
    events: list[tuple[int, str, str, str | None]] = []
    for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
        if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
            events.append((m.start(), "create", m.group(2), None))
    for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
        if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
            events.append((m.start(), "clone", m.group(2), lua_loader._clone_source(m)))
    for m in lua_loader._RE_SETTER.finditer(body):
        if m.group(2) == setter:
            events.append((m.start(), "set", m.group(1), str(m.end() - 1)))
    events.sort(key=lambda e: e[0])

    bindings: dict[str, dict] = {}
    out: list[dict] = []
    for _pos, kind, var, extra in events:
        if kind in ("create", "clone"):
            parent = bindings.get(extra) if kind == "clone" else None
            inheritable = parent["final"] if parent else []
            block = {
                "index": var,
                "parent": extra,
                "ordinal": len(out),
                "inherited": list(inheritable),
                "calls": [],
                "final": list(inheritable),
            }
            bindings[var] = block
            out.append(block)
        else:
            block = bindings.get(var)
            if block is None:
                continue
            flags = lua_loader._strip_prefix(
                regex.findall(lua_loader._extract_call_args(body, int(extra)))
            )
            block["calls"].append(flags)
            #: 🔴 외부 기준 — 첫 호출은 **덮어쓰고** 이후는 더한다.
            if len(block["calls"]) == 1:
                block["final"] = list(flags)
            else:
                block["final"] = lua_loader._strip_prefix(block["final"] + flags)
    return out


@pytest.fixture(scope="module")
def scripts():
    """스크립트 전수 — 블록 통계의 기준."""
    return LuaScriptSource(PROJECT_ROOT).load()


@pytest.fixture(scope="module")
def sources():
    """``card_id -> 블록 주석을 지운 본문`` 전수."""
    out = {}
    for card_id, path in LuaScriptSource(PROJECT_ROOT).iter_script_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        out[card_id] = lua_loader._RE_BLOCK_COMMENT.sub("", text)
    return out


# ======================================================================
# A. §2 · §7 — 최소 사례: 상속 · 격리 · 형제
# ======================================================================


def test_01_a_single_clone_inherits_and_overrides():
    """🟢 §19-1 — ``Clone`` 하나. 물려받고, 자기 호출이 있는 칸만 바뀐다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        e1:SetRange(LOCATION_SZONE)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCategory(CATEGORY_TOGRAVE)
        c:RegisterEffect(e2)
    """)
    assert [s.index for s in specs] == ["e1", "e2"]
    assert [s.cloned_from for s in specs] == [None, "e1"]
    #: 🔴 자기 호출이 있는 칸은 **덮어쓴다**.
    assert specs[1].categories == ["TOGRAVE"]
    #: 자기 호출이 없는 칸은 **물려받은 그대로다**.
    assert specs[1].ranges == ["SZONE"]
    assert specs[1].code == "EVENT_FREE_CHAIN"


def test_02_several_clones_each_keep_their_own_value():
    """🔴 §19-2 · §2 A~C — 지시서의 최소 사례 그 자체."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCategory(CATEGORY_TOGRAVE)
        c:RegisterEffect(e2)
        local e3=e1:Clone()
        e3:SetCategory(CATEGORY_DESTROY)
        c:RegisterEffect(e3)
    """)
    #: A · B · C
    assert specs[0].categories == ["DRAW"]
    assert specs[1].categories == ["TOGRAVE"]
    assert specs[2].categories == ["DESTROY"]


def test_03_parent_to_clone_inheritance_is_real():
    """
    🟢 §19-3 · §3 A — 상속은 **실제로 일어나고 의존된다.**

    ``Clone`` 이 칸을 복사하지 않는다면 자기 호출이 없는 자식은 빈 칸이어야
    한다. 그렇지 않다 — ``code`` 만 바꾸는 자식이 나머지를 그대로 쓴다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_FIELD)
        e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_CLIENT_HINT)
        e1:SetRange(LOCATION_SZONE)
        e1:SetTargetRange(0,1)
        e1:SetCategory(CATEGORY_DISABLE)
        e1:SetCode(EFFECT_CANNOT_SUMMON)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCode(EFFECT_CANNOT_MSET)
        c:RegisterEffect(e2)
    """)
    parent, child = specs
    for field in INHERITED_LISTS:
        assert getattr(child, field) == getattr(parent, field), field
    #: 바뀐 것은 ``code`` 하나다.
    assert parent.code == "EFFECT_CANNOT_SUMMON"
    assert child.code == "EFFECT_CANNOT_MSET"


def test_04_a_clone_never_writes_back_to_its_parent():
    """🔴 §19-4 · §3 B · §2 E — 역오염 **없음**. 다섯 칸 전부."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        e1:SetCategory(CATEGORY_DRAW)
        e1:SetProperty(EFFECT_FLAG_DELAY)
        e1:SetRange(LOCATION_MZONE)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        e2:SetCategory(CATEGORY_DESTROY)
        e2:SetProperty(EFFECT_FLAG_CARD_TARGET)
        e2:SetRange(LOCATION_SZONE)
        e2:SetTargetRange(LOCATION_GRAVE,0)
        c:RegisterEffect(e2)
    """)
    parent = specs[0]
    assert parent.effect_types == ["IGNITION"]
    assert parent.categories == ["DRAW"]
    assert parent.properties == ["DELAY"]
    assert parent.ranges == ["MZONE"]
    assert parent.target_ranges == ["MZONE"]


def test_05_siblings_never_see_each_other():
    """
    🔴 §19-5 · §3 C · §2 D · F — **이 Phase 의 핵심 질문.**

    같은 부모에서 나온 두 Clone 이 서로의 값을 보지 않는다. 다섯 칸 전부.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        e1:SetCategory(CATEGORY_DRAW)
        e1:SetProperty(EFFECT_FLAG_DELAY)
        e1:SetRange(LOCATION_MZONE)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        e2:SetCategory(CATEGORY_DESTROY)
        e2:SetProperty(EFFECT_FLAG_CARD_TARGET)
        e2:SetRange(LOCATION_SZONE)
        e2:SetTargetRange(LOCATION_GRAVE,0)
        c:RegisterEffect(e2)
        local e3=e1:Clone()
        e3:SetType(EFFECT_TYPE_TRIGGER_O)
        e3:SetCategory(CATEGORY_TOHAND)
        e3:SetProperty(EFFECT_FLAG_PLAYER_TARGET)
        e3:SetRange(LOCATION_HAND)
        e3:SetTargetRange(LOCATION_DECK,0)
        c:RegisterEffect(e3)
    """)
    e2, e3 = specs[1], specs[2]
    assert e2.effect_types == ["QUICK_O"] and e3.effect_types == ["TRIGGER_O"]
    assert e2.categories == ["DESTROY"] and e3.categories == ["TOHAND"]
    assert e2.properties == ["CARD_TARGET"] and e3.properties == ["PLAYER_TARGET"]
    assert e2.ranges == ["SZONE"] and e3.ranges == ["HAND"]
    assert e2.target_ranges == ["GRAVE"] and e3.target_ranges == ["DECK"]
    #: 🔴 어느 칸에서도 형제의 값이 섞이지 않는다.
    for field in INHERITED_LISTS:
        assert not set(getattr(e2, field)) & set(getattr(e3, field)), field


@pytest.mark.parametrize(
    "field,setter,values",
    [
        ("categories", "SetCategory",
         ("CATEGORY_DRAW", "CATEGORY_TOGRAVE", "CATEGORY_DESTROY")),
        ("properties", "SetProperty",
         ("EFFECT_FLAG_DELAY", "EFFECT_FLAG_CARD_TARGET", "EFFECT_FLAG_PLAYER_TARGET")),
        ("target_ranges", "SetTargetRange",
         ("LOCATION_MZONE,0", "LOCATION_SZONE,0", "0,LOCATION_HAND")),
        ("ranges", "SetRange",
         ("LOCATION_MZONE", "LOCATION_SZONE", "LOCATION_HAND")),
    ],
)
def test_06_09_each_field_is_isolated_per_block(field, setter, values):
    """
    🔴 §19-6~9 — ``categories`` · ``properties`` · ``target_ranges`` ·
    ``ranges`` 네 칸 **각각** 부모·형제로부터 격리된다.
    """
    specs = blocks_of(f"""
        local e1=Effect.CreateEffect(c)
        e1:{setter}({values[0]})
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:{setter}({values[1]})
        c:RegisterEffect(e2)
        local e3=e1:Clone()
        e3:{setter}({values[2]})
        c:RegisterEffect(e3)
    """)
    got = [getattr(s, field) for s in specs]
    assert len(got) == 3
    assert all(len(v) == 1 for v in got), got
    assert len({v[0] for v in got}) == 3, got
    #: 가변 컨테이너를 공유하지 않는다.
    assert len({id(getattr(s, field)) for s in specs}) == 3


def test_10_there_is_no_nested_mutable_container_to_share():
    """
    🔴 §19-10 · §3 D — ``EffectSpec`` 에 **중첩 가변 구조가 없다.**

    지시서가 list · dict · set · tuple 내부 가변 객체 · nested structure 를
    확인하라고 했다. 전수로 보면 칸은 ``list[str]`` 다섯 개와 스칼라 넷뿐이다 —
    공유될 수 있는 중첩 구조 **자체가 존재하지 않는다.**
    """
    hints = typing.get_type_hints(EffectSpec)
    lists = {name for name, hint in hints.items() if hint == list[str]}
    assert lists == set(INHERITED_LISTS), lists
    scalars = {name for name in hints if name not in lists}
    assert scalars == {"index", "code", "count_limit", "cloned_from"}
    for name in scalars:
        assert hints[name] in (str, str | None), (name, hints[name])
    #: dict · set · 중첩 list 는 **하나도 없다**.
    for name, hint in hints.items():
        text = str(hint)
        for banned in ("dict", "set[", "tuple", "list[list", "list[dict"):
            assert banned not in text, (name, hint)

    #: 그리고 그 ``list[str]`` 안의 원소는 전부 문자열이다 (corpus 표본).
    for spec in parse_card(PURE_INHERITANCE).effects:
        for field in INHERITED_LISTS:
            assert all(isinstance(v, str) for v in getattr(spec, field))


def test_11_a_clone_chain_carries_the_corrected_value():
    """
    🔴 §19-11 — ``Clone`` 연쇄. 중간 자식이 좁히면 그 **아래로 전파된다.**

    이것이 corpus diff 에서 직접 후보 64개 말고 **7블록이 더 바뀐 이유**다
    (``test_39``).
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW+CATEGORY_TODECK)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCategory(CATEGORY_TOHAND)
        c:RegisterEffect(e2)
        local e3=e2:Clone()
        c:RegisterEffect(e3)
    """)
    assert specs[0].categories == ["DRAW", "TODECK"]
    assert specs[1].categories == ["TOHAND"]
    #: 🔴 ``e3`` 은 자기 호출이 없으므로 ``e2`` 의 **고쳐진** 값을 물려받는다.
    assert specs[2].categories == ["TOHAND"]
    assert [s.cloned_from for s in specs] == [None, "e1", "e2"]


# ======================================================================
# B. §19-12~18 — 설정자별 · 여러 호출 · initial_effect
# ======================================================================


def test_12_clone_plus_settype_keeps_the_3f27_result():
    """🔴 §19-12 · §18 — 3-F-27 의 ``SetType`` 결과가 **그대로다.**"""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        c:RegisterEffect(e2)
    """)
    assert specs[0].effect_types == ["IGNITION"]
    #: 🔴 ``['IGNITION', 'QUICK_O']`` 이 아니다 — 3-F-27 이 고친 그것.
    assert specs[1].effect_types == ["QUICK_O"]


def test_13_clone_plus_setcategory():
    """🔴 §19-13 — 물려받은 category 가 자식의 호출로 **교체된다.**"""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_TODECK+CATEGORY_DRAW)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCategory(CATEGORY_ATKCHANGE+CATEGORY_DEFCHANGE)
        c:RegisterEffect(e2)
    """)
    assert specs[1].categories == ["ATKCHANGE", "DEFCHANGE"]
    assert "TODECK" not in specs[1].categories


def test_14_clone_plus_setproperty_including_an_explicit_clear():
    """
    🔴 §19-14 — ``SetProperty(0)`` 이 **비운다.**

    대입이 아니면 의미가 없는 줄이고, corpus 에 실제로 둘 있다
    (``c18438874`` · ``c55262310``). 더하기 규칙에서는 부모의 플래그가
    그대로 남아 스크립트가 분명히 지운 것을 계속 주장했다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetProperty(0)
        c:RegisterEffect(e2)
    """)
    assert specs[0].properties == ["PLAYER_TARGET"]
    assert specs[1].properties == []

    #: 실제 카드로도 확인한다.
    real = parse_card(CLEAR_PROPERTY)
    assert "e2:SetProperty(0)" in script_text(CLEAR_PROPERTY)
    assert real.effects[1].properties == []


def test_15_clone_plus_setrange():
    """🔴 §19-15 — 물려받은 range 가 교체된다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetRange(LOCATION_SZONE)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetRange(LOCATION_MZONE)
        c:RegisterEffect(e2)
    """)
    assert specs[1].ranges == ["MZONE"]


def test_16_clone_plus_settargetrange():
    """🔴 §19-16 — 물려받은 target_range 가 교체된다 (``c295517`` 의 모양)."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetTargetRange(LOCATION_HAND|LOCATION_MZONE,LOCATION_HAND|LOCATION_MZONE)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetTargetRange(LOCATION_MZONE,LOCATION_MZONE)
        c:RegisterEffect(e2)
    """)
    assert specs[0].target_ranges == ["HAND", "MZONE"]
    assert specs[1].target_ranges == ["MZONE"]


def test_17_only_the_first_call_replaces_later_calls_still_add():
    """
    🔴 §19-17 · §8 D vs E — **고친 것은 첫 호출뿐이다.**

    한 블록이 같은 설정자를 두 번 부르면 두 번째는 **기존대로 더한다.**
    ``properties`` 에 순차 2회 사례가 5건 있어서 (``test_37``) 그 동작을
    바꾸지 않았다 — 증거가 한쪽으로 기울지 않는 것은 **그대로 둔다.**
    """
    #: Clone 자식: 첫 호출이 물려받은 값을 덮어쓰고, 두 번째가 더한다.
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetProperty(EFFECT_FLAG_CLIENT_HINT)
        e2:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)
        c:RegisterEffect(e2)
    """)
    assert specs[1].properties == ["CLIENT_HINT", "CANNOT_DISABLE"]
    assert "PLAYER_TARGET" not in specs[1].properties

    #: Clone 이 아닌 블록: 두 호출 모두 더한다 (동작 변화 없음).
    plain = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetProperty(EFFECT_FLAG_CLIENT_HINT)
        e1:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)
        c:RegisterEffect(e1)
    """)
    assert plain[0].properties == ["CLIENT_HINT", "CANNOT_DISABLE"]


def test_18_clone_inside_initial_effect_and_outside_both_work():
    """🟢 §19-18 — ``initial_effect`` 안이든 해결 함수 안이든 같다."""
    specs = blocks_of("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCategory(CATEGORY_DRAW)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetCategory(CATEGORY_TOGRAVE)
            c:RegisterEffect(e2)
        end
        function s.operation(e,tp)
            local e3=Effect.CreateEffect(c)
            e3:SetCategory(CATEGORY_DESTROY)
            c:RegisterEffect(e3)
            local e4=e3:Clone()
            e4:SetCategory(CATEGORY_REMOVE)
            c:RegisterEffect(e4)
        end
    """)
    assert [s.categories for s in specs] == [
        ["DRAW"], ["TOGRAVE"], ["DESTROY"], ["REMOVE"],
    ]
    assert [s.cloned_from for s in specs] == [None, "e1", None, "e3"]


# ======================================================================
# C. §19-19~23 — EffectRef · ordinal · 실제 corpus · 실제 카드 · 16개 정의
# ======================================================================


def test_19_effect_ref_still_points_at_the_same_block(repository):
    """
    🔴 §19-19 · §12 — ``EffectRef(card_id, ordinal)`` 이 그대로다.

    이 Phase 는 블록을 더하거나 빼지 않았으므로 **모든 ``EffectRef`` 가 전과
    같은 블록을 가리킨다.** 바뀐 것은 그 블록의 네 칸 값뿐이다.
    """
    for card_id in (CLEAR_PROPERTY, NARROWED_TARGET, CHAIN_PROPERTY, PURE_INHERITANCE):
        card = repository.get(card_id)
        assert card is not None and card.script is not None, card_id
        refs = effect_refs(card)
        assert [r.ordinal for r in refs] == list(range(len(card.script.effects)))
        for position, (ref, spec) in enumerate(iter_effects(card)):
            assert ref.ordinal == position
            assert ref.resolve(card) is spec
        assert EffectRef(card_id, len(refs)).resolve(card) is None

    #: 🔴 식별 체계를 바꾸지 않았다 — 새 ID 시스템 금지.
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    assert EffectRef.__dataclass_params__.frozen is True
    ids_source = (PROJECT_ROOT / "engine" / "ids.py").read_text(encoding="utf-8")
    for banned in ("import uuid", "uuid4", "id(self)", "EffectId"):
        assert banned not in ids_source, banned


def test_20_clone_does_not_change_the_block_count_or_order(scripts):
    """
    🔴 §19-20 · §12 — ``Clone`` 이 ``ordinal`` 을 새로 만들지 않는다.

    블록 총수가 3-F-28 과 **같고**, ``Clone`` 블록 수도 같다. 이 Phase 는
    **값만** 고쳤다.
    """
    assert len(scripts) == SCRIPTS
    blocks = sum(len(info.effects) for info in scripts.values())
    clones = sum(1 for info in scripts.values() for s in info.effects if s.cloned_from)
    with_clone = sum(
        1 for info in scripts.values() if any(s.cloned_from for s in info.effects)
    )
    assert blocks == BLOCKS
    assert clones == CLONE_BLOCKS
    assert with_clone == SCRIPTS_WITH_CLONE

    #: ``Clone`` 블록의 부모는 **항상 그 앞에** 있다 (밀림 없음).
    for card_id, info in scripts.items():
        seen: set[str] = set()
        for spec in info.effects:
            if spec.cloned_from is not None and spec.cloned_from not in seen:
                #: 3-F-28 이 고정한 유일한 예외 — 보조 함수가 만든 부모.
                assert (card_id, spec.index) == (39114494, "e4"), (card_id, spec.index)
            seen.add(spec.index)


def test_21_the_sixty_four_candidates_are_real_and_now_corrected(sources):
    """
    🔴 §19-21 · §9 · §10 — 3-F-28 이 남긴 **"64 blocks" 를 현재 HEAD 에서 다시
    측정해 64 를 확인했다.**

    칸별로 ``ranges`` 12 · ``target_ranges`` 9 · ``categories`` 24 ·
    ``properties`` 19. 숫자를 복사하지 않고 다시 셌다.

    그리고 그 64개 **전부**에서 production 이 이제 외부 기준(``replay``)과
    일치한다 — 물려받은 값이 남지 않는다.
    """
    diverging = collections.Counter()
    mismatch = []
    for card_id, body in sources.items():
        if ":Clone()" not in body:
            continue
        production = parse_lua_source(card_id, f"c{card_id}.lua", body).effects
        for field in FIELD_REGEX:
            for block in replay(body, field):
                if block["parent"] is None or not block["calls"]:
                    continue
                if block["inherited"] and not set(block["inherited"]) <= set(
                    block["calls"][0]
                ):
                    diverging[field] += 1
                if block["ordinal"] < len(production):
                    got = getattr(production[block["ordinal"]], field)
                    if got != block["final"]:
                        mismatch.append(
                            (card_id, block["ordinal"], field, got, block["final"])
                        )

    assert dict(diverging) == DIVERGING, dict(diverging)
    assert sum(diverging.values()) == 64
    #: 🔴 production 이 외부 기준과 corpus 전체에서 일치한다.
    assert mismatch == [], mismatch[:20]


def test_22_twelve_real_cards_end_to_end():
    """
    🔴 §19-22 · §11 — 실제 카드 **12장**을 Lua → 부모 → Clone → setter →
    ``EffectSpec`` 까지 비교한다.
    """
    #: 1. ``SetProperty(0)`` + 연쇄.
    spec = parse_card(CLEAR_PROPERTY).effects
    assert spec[0].categories == ["DRAW"] and spec[0].properties == ["PLAYER_TARGET"]
    assert spec[1].categories == ["TOHAND", "SEARCH"] and spec[1].properties == []
    assert spec[2].categories == ["TOHAND", "SEARCH"] and spec[2].properties == []

    #: 2. target_range 를 좁히고 자식이 상속.
    spec = parse_card(NARROWED_TARGET).effects
    assert spec[1].target_ranges == ["HAND", "MZONE"]
    assert spec[2].target_ranges == ["MZONE"]
    assert spec[3].target_ranges == ["MZONE"]

    #: 3. 중간 자식이 좁히고 **형제 둘**이 그것을 상속.
    spec = parse_card(CHAIN_PROPERTY).effects
    assert spec[1].properties == ["SET_AVAILABLE", "IGNORE_IMMUNE"]
    assert spec[2].properties == ["SET_AVAILABLE"]
    assert spec[3].properties == ["SET_AVAILABLE"]
    assert spec[4].properties == ["SET_AVAILABLE"]
    assert [s.cloned_from for s in spec[2:5]] == ["e2", "e3", "e3"]

    #: 4. 더하기가 만들던 조합이 사라졌다.
    spec = parse_card(FABRICATED_CATEGORY).effects
    assert spec[0].categories == ["TODECK", "DRAW"]
    assert spec[1].categories == ["ATKCHANGE", "DEFCHANGE"]

    #: 5. 같은 모양 + ``SetProperty(0)``.
    spec = parse_card(FABRICATED_CATEGORY2).effects
    assert spec[0].categories == ["POSITION", "TODECK"]
    assert spec[1].categories == ["POSITION", "LVCHANGE"]
    assert spec[1].properties == []

    #: 6. 순수 상속 — Clone 6개가 ``SetCode`` 만 바꾼다. **바뀌지 않아야 한다.**
    spec = parse_card(PURE_INHERITANCE).effects
    for position in range(2, 7):
        assert spec[position].properties == ["PLAYER_TARGET", "CLIENT_HINT"], position
        assert spec[position].cloned_from == "e1"
    #: 같은 카드의 ``e12`` 는 후보였다 — 좁혀진다.
    assert spec[11].target_ranges == ["SZONE"]
    assert spec[12].target_ranges == ["MZONE"]

    #: 7. 부모 플래그를 다시 적고 더하는 카드 — 결과가 **그대로다**.
    spec = parse_card(RESTATES_PARENT).effects
    assert set(spec[1].properties) == {"CARD_TARGET", "DELAY", "DAMAGE_STEP"}

    #: 8. 적용 범위 플래그가 교체된다.
    spec = parse_card(SCOPE_SWAP).effects
    assert spec[0].properties == ["SINGLE_RANGE"]
    assert spec[1].properties == ["PLAYER_TARGET"]

    #: 9. 재진술·확장 — 결과가 그대로다.
    spec = parse_card(RANGE_CANDIDATE).effects
    assert set(spec[1].categories) >= {"TOGRAVE", "TOHAND", "SEARCH"}

    #: 10. 순차 2회 관용구 — Clone 이 아니므로 **더하기 유지**.
    spec = parse_card(SEQUENTIAL_IDIOM).effects
    assert set(spec[1].properties) == {"CLIENT_HINT", "CANNOT_DISABLE", "OATH"}

    #: 11. 스크립트 오타 — 역시 Clone 이 아니므로 더하기 유지.
    spec = parse_card(TYPO_SEQUENTIAL).effects
    assert "CLIENT_HINT" in spec[2].properties

    #: 12. 3-F-27 의 카드 — ``effect_types`` 가 유지된다.
    spec = parse_card(CLONE_TYPE_FIX).effects
    assert spec[1].effect_types == ["QUICK_O"]
    assert spec[1].cloned_from == "e1"


def test_23_all_sixteen_effect_definitions_are_untouched(repository):
    """
    🔴 §19-23 · §13 — 등록된 16개 ``EffectDefinition`` 전부.

    그 16장의 스크립트에는 ``:Clone()`` 이 **하나도 없다.** 그래서 이 수정은
    ``EffectDefinition → TriggerSpec → ChainLink → activation`` 경로에
    **닿을 수가 없다.**
    """
    assert len(EFFECT_LIBRARY) == 16
    changed = _changed_cards()
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        assert card is not None and card.script is not None, ref
        assert ref.ordinal == 0, ref
        assert len(card.script.effects) == 1, (ref, len(card.script.effects))
        resolved = ref.resolve(card)
        assert resolved is not None and resolved.code == "EVENT_FREE_CHAIN", ref
        assert effect_refs(card) == [EffectRef(ref.card_id, 0)], ref
        #: 🔴 ``Clone`` 이 없다.
        assert ":Clone()" not in script_text(ref.card_id), ref
        #: 🔴 이 Phase 가 바꾼 카드 목록에 없다.
        assert ref.card_id not in changed, ref


# ======================================================================
# D. §19-24~27 — 결정성 · 캐시
# ======================================================================


def test_24_parsing_is_deterministic(sources):
    """🟢 §19-24 — 같은 입력을 두 번 파싱하면 **완전히 같다**."""
    sample = sorted(sources)[:400] + [
        CLEAR_PROPERTY, NARROWED_TARGET, CHAIN_PROPERTY, PURE_INHERITANCE,
    ]
    for card_id in sample:
        body = sources[card_id]
        first = parse_lua_source(card_id, f"c{card_id}.lua", body)
        second = parse_lua_source(card_id, f"c{card_id}.lua", body)
        assert [dataclasses.asdict(s) for s in first.effects] == [
            dataclasses.asdict(s) for s in second.effects
        ], card_id


def test_25_the_cache_round_trip_returns_the_corrected_blocks(scripts, tmp_path):
    """
    🔴 §19-25 · §14 — 캐시가 **고친 파서의 결과**를 돌려준다 (cache hit 포함).
    """
    cache = tmp_path / "lua_scripts.json"
    source = LuaScriptSource(PROJECT_ROOT)
    written = source.load_cached(cache)
    assert cache.is_file()
    read_back = source.load_cached(cache)

    for card_id in (CLEAR_PROPERTY, NARROWED_TARGET, CHAIN_PROPERTY):
        direct = [dataclasses.asdict(s) for s in scripts[card_id].effects]
        assert [dataclasses.asdict(s) for s in written[card_id].effects] == direct
        assert [dataclasses.asdict(s) for s in read_back[card_id].effects] == direct

    for table in (scripts, written, read_back):
        assert sum(len(info.effects) for info in table.values()) == BLOCKS

    blob = json.loads(cache.read_text(encoding="utf-8"))
    assert blob["signature"] == source._signature()
    #: 🔴 Phase 3-F-31 에서 ``v7`` → ``v8``.
    #: 🔴 Phase 3-F-32 에서 ``v8`` → **``v9``** — ``Clone`` 의 인자 있는
    #: 형태와 점 형태를 블록으로 인정했다. 캐시 서명에 파서 버전이
    #: 들어 있지 않아 **다섯 Phase 연속 수동**으로 올리고 있다 (위험 E4).
    assert blob["signature"].startswith("v10-")


def test_26_the_cache_signature_was_bumped():
    """
    🔴 §19-26 · §14 — ``_signature`` 접두사가 ``v6`` → ``v7`` 로 올랐다.

    3-E-18 이 설치한 ``test_setcode_provenance_audit.py::test_19`` 가
    **세 Phase 연속으로 설계대로 걸렸다** (3-F-27 · 3-F-28 · 3-F-29).
    """
    body = inspect.getsource(LuaScriptSource._signature)
    assert 'f"v10-{_CACHE_SHAPE_TAG}:{count}:{newest:.0f}"' in body
    for old in ("v9:", "v8:", "v7:", "v6:", "v5:", "v4:"):
        assert f'f"{old}' not in body, old
    assert LuaScriptSource(PROJECT_ROOT)._signature().startswith("v10-")
    #: 🔴 서명에 파서 버전·코드 해시가 **없다** — 그래서 손으로 올린다.
    for token in ("parse_lua_source", "__version__", "md5", "sha", "_write_list"):
        assert token not in body, token


def test_27_a_stale_cache_is_rejected(tmp_path):
    """🔴 §19-27 · §14 — ``v6`` 서명 캐시는 **쓰이지 않는다.**"""
    cache = tmp_path / "lua_scripts.json"
    cache.write_text(
        json.dumps({
            "signature": "v8:12702:0",
            "scripts": {str(CLEAR_PROPERTY): {"file_name": "poisoned.lua"}},
        }),
        encoding="utf-8",
    )
    source = LuaScriptSource(PROJECT_ROOT)
    assert source._signature() != "v8:12702:0"
    loaded = source.load_cached(cache)
    assert loaded[CLEAR_PROPERTY].file_name == f"c{CLEAR_PROPERTY}.lua"
    #: 🔴 고친 값이 들어 있다 — 옛 캐시의 더하기 결과가 아니다.
    assert loaded[CLEAR_PROPERTY].effects[1].properties == []
    assert json.loads(
        cache.read_text(encoding="utf-8"))["signature"].startswith("v10-")
    #: 깨진 캐시도 조용히 재파싱된다.
    cache.write_text("{ not json", encoding="utf-8")
    assert len(source.load_cached(cache)) == SCRIPTS


# ======================================================================
# E. §19-28~34 — 불변 조건 (engine · AI · Search)
# ======================================================================


def test_28_state_hash_is_unchanged(repository):
    """🟢 §19-28 — ``state_hash`` 가 같은 seed 에서 같고 다른 seed 에서 다르다."""
    first = opened_duel(repository, seed=51)
    second = opened_duel(repository, seed=51)
    assert first.state.state_hash() == second.state.state_hash()
    assert opened_duel(repository, seed=52).state.state_hash() != first.state.state_hash()


def test_29_the_rng_is_unchanged(repository):
    """🟢 §19-29 — 같은 seed 에서 난수열이 같다."""
    left = opened_duel(repository, seed=53)
    right = opened_duel(repository, seed=53)
    assert [left.state.rng.randrange(10_000) for _ in range(12)] == [
        right.state.rng.randrange(10_000) for _ in range(12)
    ]


def test_30_the_search_ranking_digest_is_unchanged(repository):
    """
    🔴 §19-30 · §16~18 — 6판 **611결정** digest 불변.

    🔴 이것이 "파서 데이터 수정이 duel 동작을 바꾸지 않는다" 의 **행동 증거**다.
    기대값을 손으로 적지 않는다 — 다른 테스트 파일이 이미 고정해 둔 값을 AST 로
    읽어 **가장 많이 고정된 것**을 쓴다.
    """
    pinned: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative == MYSELF:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(ch in "0123456789abcdef" for ch in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: collections.Counter = collections.Counter()
    for values in pinned.values():
        counts.update(values)
    expected, pins = counts.most_common(1)[0]
    #: 🔴 실측 7개 파일이 같은 값을 고정한다 (3-F-28 의 파일은 AST 로 읽으므로
    #: 리터럴을 갖지 않는다). 8 로 적었다가 틀렸고, 재측정해 7 로 고쳤다.
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
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


def test_31_hidden_information_and_the_view_are_unchanged(repository):
    """🟢 §19-31 — ``CardDefinitionView`` 가 블록 내용을 **내보내지 않는다.**"""
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert len(fields) == 26
    assert "effect_count" in fields
    for banned in (*INHERITED_LISTS, "code", "script", "effects", "cloned_from"):
        assert banned not in fields, banned
    duel = opened_duel(repository, seed=54)
    assert not hasattr(duel.view(0), "effects")


def test_32_search_was_not_touched():
    """🔴 §19-32 — 검색 계층이 diff 에 **없다.**"""
    changed = _changed_files()
    for path in (
        "core/card_search.py",
        "core/query_parser.py",
        "core/card_repository.py",
        "agent/search.py",
    ):
        assert path not in changed, (path, sorted(changed))


def test_33_the_ai_layer_was_not_touched():
    """🔴 §19-33 — ``agent/`` 전체가 diff 에 **없다.**"""
    changed = _changed_files()
    assert not [p for p in changed if p.startswith("agent/")], sorted(changed)


def test_34_engine_v1_was_not_touched():
    """
    🔴 §19-34 · §15 — ``engine/`` 전체가 diff 에 **없다.** Engine V1 freeze 유지.

    그리고 engine · agent 가 ``EffectSpec`` 고유 칸을 **0회** 읽는다. 그래서
    이 네 칸의 값이 바뀌어도 duel 동작이 바뀔 수 없다.
    """
    changed = _changed_files()
    assert not [p for p in changed if p.startswith("engine/")], sorted(changed)

    spec_only = ("effect_types", "cloned_from", "count_limit", "target_ranges")
    hits = []
    for directory in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in spec_only:
                    hits.append(f"{path.name}:{node.lineno}:{node.attr}")
    assert hits == [], hits


# ======================================================================
# F. §19-35 + 이 Phase 가 고친 것 자체 — 근거 · 범위 · 교차 검증
# ======================================================================


def test_35_the_3f27_settype_result_is_not_reverted(scripts):
    """
    🔴 §19-35 · §18 — 3-F-27 의 결과를 **되돌리지 않았다.**

    ``effect_types`` 의 corpus 총계가 그대로고, 모순 조합(적용 범위 2개 이상
    또는 발동 분류 2개 이상)을 가진 블록이 **0개**다.
    """
    scope = frozenset({"SINGLE", "FIELD", "EQUIP"})
    activation = frozenset({
        "ACTIVATE", "IGNITION", "TRIGGER_O", "QUICK_O",
        "TRIGGER_F", "QUICK_F", "CONTINUOUS",
    })
    total = 0
    offenders = []
    for card_id, info in scripts.items():
        for position, spec in enumerate(info.effects):
            total += len(spec.effect_types)
            flags = set(spec.effect_types)
            if len(flags & scope) > 1 or len(flags & activation) > 1:
                offenders.append((card_id, position, spec.effect_types))
    assert total == TOTALS["effect_types"]
    assert offenders == [], offenders[:20]

    #: 3-F-27 의 실제 카드 · Clone 연쇄 · 형제 Clone 을 다시 본다.
    assert parse_card(CLONE_TYPE_FIX).effects[1].effect_types == ["QUICK_O"]
    chained = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_IGNITION)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetType(EFFECT_TYPE_QUICK_O)
        c:RegisterEffect(e2)
        local e3=e2:Clone()
        e3:SetType(EFFECT_TYPE_TRIGGER_O)
        c:RegisterEffect(e3)
        local e4=e1:Clone()
        c:RegisterEffect(e4)
    """)
    assert [s.effect_types for s in chained] == [
        ["IGNITION"], ["QUICK_O"], ["TRIGGER_O"], ["IGNITION"],
    ]

    #: 🔴 ``_write_list`` 가 ``effect_types`` 를 **건드리지 않는다** — 그 칸은
    #: 3-F-27 의 분기가 그대로 처리한다.
    body = inspect.getsource(lua_loader.parse_lua_source)
    assert '_write_list(spec, inherited, var, "ranges"' in body
    assert '_write_list(spec, inherited, var, "effect_types"' not in body
    assert '"effect_types" in inherited.get(var, ())' in body


def test_36_the_restating_children_are_the_evidence(sources):
    """
    🔴 근거 1 — **자식이 물려받은 플래그를 자기 호출에 다시 적는 블록이 43개다.**

    더하기라면 **죽은 코드**이고, 덮어쓰기라면 **필수**다. 43개가 서로 다른
    스크립트에 흩어져 있다. 이것이 네 칸을 덮어쓰기로 바꾼 가장 강한 근거다.
    """
    restating = collections.Counter()
    shapes = collections.Counter()
    for card_id, body in sources.items():
        if ":Clone()" not in body:
            continue
        for field in FIELD_REGEX:
            for block in replay(body, field):
                if block["parent"] is None or not block["calls"]:
                    continue
                inherited, own = set(block["inherited"]), set(block["calls"][0])
                if inherited and inherited <= own:
                    restating[field] += 1
                    shapes["정확히 같음" if inherited == own else "확장"] += 1
    assert dict(restating) == RESTATING, dict(restating)
    assert sum(restating.values()) == 43
    #: 재진술의 모양 — "그대로 다시" 14 · "유지하며 확장" 29.
    assert shapes["정확히 같음"] == 14
    assert shapes["확장"] == 29

    #: 실제 카드 하나로 모양을 못 박는다.
    body = sources[RESTATES_PARENT]
    block = next(b for b in replay(body, "properties") if b["ordinal"] == 1)
    assert set(block["inherited"]) == {"CARD_TARGET", "DELAY"}
    assert set(block["calls"][0]) == {"CARD_TARGET", "DELAY", "DAMAGE_STEP"}


def test_37_the_counter_evidence_was_measured_and_weighed(sources):
    """
    🔴 반대 방향 증거 — **측정하고 기각했다.**

    한 블록이 같은 설정자를 두 번 부르며 서로 다른 값을 쓰면 더하기 쪽 증거다.
    전수로 ``properties`` 5건 · ``categories`` 1건이고 ``ranges`` ·
    ``target_ranges`` 는 **0건**이다.

    그런데 **독립 증거는 하나도 없다.**

    * ``categories`` 1건(``c52445243``)은 ``if``/``elseif`` **배타 분기**다 —
      런타임에 한 번만 실행되므로 누적과 무관하다.
    * ``properties`` 5건 중 **3건**은 ``SetDescription(...)`` +
      ``SetProperty(EFFECT_FLAG_CLIENT_HINT)`` 라는 **같은 복사-붙여넣기
      관용구**다 (``c50619462`` · ``c64867422`` · ``c73899015``).
    * 1건(``c76685519``)은 ``e2`` 를 쓸 자리에 ``e1`` 을 쓴 **오타**다.
    * 🔴 그러면 **독립 사례가 1건 남는다** — ``c49460512`` 의
      ``IGNORE_IMMUNE`` → ``EVENT_PLAYER``. 처음에 "4건이 같은 관용구" 라고
      적었는데 **틀렸다**; 재측정해서 3건으로 고쳤다.

    즉 더하기 쪽 독립 증거는 **1건**이고, 덮어쓰기 쪽은 ``test_36`` 의 **43건**
    이다. 그래서 ``Clone`` 이 물려준 값을 덮어쓰도록 고치고, **한 블록이 같은
    설정자를 두 번 부르는 경우의 더하기는 그대로 두었다** (``test_17``) —
    그 1건이 가리키는 동작을 바꾸지 않는다.

    그래서 **두 번째 이후 호출의 더하기는 그대로 두었다** (``test_17``) —
    증거가 한쪽으로 기울지 않는 것은 바꾸지 않는다.
    """
    sequential = collections.Counter()
    found: list[tuple[int, int, str]] = []
    for card_id, body in sources.items():
        for field in FIELD_REGEX:
            for block in replay(body, field):
                if len(block["calls"]) < 2:
                    continue
                sets = [frozenset(c) for c in block["calls"]]
                if all(sets) and len(set(sets)) > 1:
                    sequential[field] += 1
                    found.append((card_id, block["ordinal"], field))
    for field in FIELD_REGEX:
        assert sequential[field] == SEQUENTIAL_DISTINCT[field], (field, sequential)

    cards = {card_id for card_id, _, _ in found}
    assert cards == {
        49460512, 50619462, 64867422, SEQUENTIAL_IDIOM, TYPO_SEQUENTIAL,
        BRANCHED_CATEGORY,
    }, cards

    #: 🔴 ``categories`` 1건은 배타 분기다 — 원문 모양으로 확인한다.
    branched = script_text(BRANCHED_CATEGORY)
    assert "if lv==1 then e1:SetCategory(CATEGORY_DESTROY)" in branched
    assert "elseif lv==2 then e1:SetCategory(CATEGORY_DRAW) end" in branched
    #: 그리고 그 블록은 ``Clone`` 이 아니다 — 이 Phase 의 수정 범위 밖이다.
    assert ":Clone()" not in branched

    #: 🔴 3건이 같은 관용구다 — ``SetDescription`` 바로 뒤의 ``CLIENT_HINT``.
    idiom = [
        card_id
        for card_id in (50619462, 64867422, SEQUENTIAL_IDIOM)
        if "EFFECT_FLAG_CLIENT_HINT" in script_text(card_id)
    ]
    assert len(idiom) == 3, idiom
    #: 🔴 그리고 독립 사례가 **1건** 남는다 — 숨기지 않고 고정한다.
    independent = script_text(49460512)
    assert "e2:SetProperty(EFFECT_FLAG_IGNORE_IMMUNE)" in independent
    assert "e2:SetProperty(EFFECT_FLAG_EVENT_PLAYER)" in independent
    assert "EFFECT_FLAG_CLIENT_HINT" not in independent
    #: 그 블록도 ``Clone`` 이 아니므로 이 Phase 가 동작을 바꾸지 않았다.
    assert ":Clone()" not in independent

    #: 🔴 나머지 1건은 ``e2`` 를 쓸 자리에 ``e1`` 을 쓴 오타다.
    text = script_text(TYPO_SEQUENTIAL)
    assert "local e2=Effect.CreateEffect(c)" in text
    assert "e1:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)" in text


def test_38_appending_fabricated_combinations_no_card_writes(sources):
    """
    🔴 근거 3 — 더하기 결과가 **어떤 카드도 한 호출에 적지 않는 조합**이 된다.

    ``SetType`` 에서는 77블록 중 76블록이 그랬다 (3-F-27). 네 칸에서는 그
    비율이 훨씬 낮다 — **64 중 4** 다. 숫자를 부풀리지 않고 그대로 적는다.
    그래서 이 근거는 **보조**이고, 결정적인 것은 ``test_36`` 의 43건이다.
    """
    written = {field: set() for field in FIELD_REGEX}
    for body in sources.values():
        for m in lua_loader._RE_SETTER.finditer(body):
            for field, (setter, regex) in FIELD_REGEX.items():
                if m.group(2) != setter:
                    continue
                flags = frozenset(
                    lua_loader._strip_prefix(
                        regex.findall(lua_loader._extract_call_args(body, m.end() - 1))
                    )
                )
                if flags:
                    written[field].add(flags)

    never = []
    for card_id, body in sources.items():
        if ":Clone()" not in body:
            continue
        for field in FIELD_REGEX:
            for block in replay(body, field):
                if block["parent"] is None or not block["calls"]:
                    continue
                inherited, own = set(block["inherited"]), set(block["calls"][0])
                if not inherited or inherited <= own:
                    continue
                merged = frozenset(inherited | own)
                if not any(merged <= seen for seen in written[field]):
                    never.append((card_id, block["ordinal"], field, sorted(merged)))

    assert len(never) == 4, never
    assert {row[0] for row in never} == {
        FABRICATED_CATEGORY, FABRICATED_CATEGORY2, 55948544, 63259351,
    }, never


def test_39_the_corpus_diff_is_fifty_nine_scripts(scripts):
    """
    🔴 §17 — 바뀐 범위를 **정확히** 고정한다.

    59 스크립트 / 75 블록-칸 쌍 = 직접 후보 **64** + ``Clone`` 연쇄 전파 **7**
    + 순서만 바뀐 것 **4**. 블록 수와 ``ordinal`` 은 **그대로다.**
    """
    assert len(CHANGED_CARDS) == CHANGED_SCRIPTS
    assert CHANGED_PAIRS == 64 + 7 + 4

    #: 블록 수 · ``ordinal`` 불변.
    assert sum(len(info.effects) for info in scripts.values()) == BLOCKS

    #: 칸별 총계.
    totals = collections.Counter()
    for info in scripts.values():
        for spec in info.effects:
            for field in INHERITED_LISTS:
                totals[field] += len(getattr(spec, field))
    assert dict(totals) == TOTALS, dict(totals)

    #: 🔴 바뀐 카드는 **전부 ``Clone`` 을 쓴다** — 그러지 않으면 범위 밖이다.
    for card_id in CHANGED_CARDS:
        assert ":Clone()" in script_text(card_id), card_id

    #: 🔴 ``Clone`` 이 없는 스크립트는 하나도 바뀔 수 없다 — 다섯 칸을 쓰는
    #: 분기가 ``inherited`` 집합을 ``clone`` 에서만 채우기 때문이다.
    body = inspect.getsource(lua_loader.parse_lua_source)
    assert body.count("inherited[dst] = {") == 1
    assert "inherited[var] = set()" in body


def test_40_the_production_change_is_confined_to_one_file():
    """
    🔴 §16 — production diff 가 **``sources/lua_loader.py`` 한 파일**이다.

    새 abstraction · 새 enum · 새 public API · ``EffectSpec`` 칸 변화 — 없다.
    """
    changed = _changed_files()
    production = {
        p for p in changed
        if not p.startswith(("tests/", "docs/")) and p.endswith(".py")
    }
    assert production == {"sources/lua_loader.py"}, production

    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]
    assert len(dataclasses.fields(EffectDefinition)) == 10
    assert "effects" in {f.name for f in dataclasses.fields(LuaScriptInfo)}

    tree = ast.parse((PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8"))
    public = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    ]
    assert public == ["parse_lua_source", "LuaScriptSource"], public
    #: 새로 생긴 이름은 private 둘뿐이다.
    assert "_write_list" in [
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    ]
    assert "_CLONE_INHERITED_LISTS" in [
        t.id for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    ]
    #: 새 enum 이 없다.
    assert not [
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id.endswith("Enum") for b in node.bases)
    ]
    #: 🔴 ``Clone`` 분기가 **deepcopy 로 바뀌지 않았다** — 지시서 §16 금지 사항.
    loader = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8")
    for banned in ("deepcopy", "import copy", "copy.copy"):
        assert banned not in loader, banned
    #: 다섯 칸을 ``list(...)`` 로 복사하는 방식은 그대로다.
    assert loader.count("list(parent.") == 5


#: 🔴 이 Phase 가 ``effects`` 를 바꾼 스크립트 **전부**. 수정 전 파서 모듈과
#: 전수 비교해서 얻었다 (그 모듈은 커밋되면 사라지므로 결과를 고정한다).
CHANGED_CARDS = (
    295517, 879958, 3103067, 5772618, 8384771, 9106362, 9603252, 10239627,
    11366199, 12196873, 15758127, 17016131, 18438874, 20788863, 21984400,
    23657016, 24907044, 27104921, 29479265, 32354768, 33206889, 34472920,
    36591747, 40669071, 40945356, 43455065, 47021196, 53451824, 54423935,
    55262310, 55948544, 58707981, 60759087, 61557074, 62098216, 63259351,
    63749102, 64591429, 65681983, 66069967, 66719533, 66984907, 69792699,
    70335319, 70479321, 71650854, 71948047, 83589191, 84274024, 87997872,
    91740879, 92332424, 92377303, 92530005, 92650018, 93473606, 95440946,
    96100333, 97522863,
)


def _changed_cards() -> frozenset[int]:
    return frozenset(CHANGED_CARDS)


def _changed_files() -> set[str]:
    """
    이 Phase 의 diff 에 등장하는 파일.

    🔴 ``HEAD`` 를 기준으로 잡으면 **다음 Phase 가 production 을 건드릴 때 이
    테스트가 엉뚱하게 깨진다** (3-F-25 의 ``test_30`` 이 3-F-26 에서 그렇게
    깨졌다). 그래서 제목이 ``Phase 3-F-29:`` 으로 시작하는 commit 들을 찾아
    *가장 오래된 것의 부모 → 가장 최근 것* 을 본다. 이 Phase 는 작업 · 테스트 ·
    보고서를 나눠 커밋하므로 **파일을 추가한 commit 하나만 보면 작업 commit 의
    production 변경이 보이지 않는다** (3-F-28 ``test_36`` 이 그렇게 빈 집합을
    받았다).
    """
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        ).stdout

    phase = run("log", "--format=%H", "--grep=^Phase 3-F-29:", "HEAD").split()
    out = ""
    if phase:
        newest, oldest = phase[0], phase[-1]
        #: 🔴 Phase 3-F-31 정정 — 여기에 ``run("diff", "--name-only", newest)``
        #: (= worktree vs 그 commit) 가 있었다. 그러면 **다음 Phase 가
        #: worktree 에서 production 을 건드리는 동안** 그 변경이 이 Phase 의
        #: diff 로 새어 들어온다. 실제로 3-F-31 이 ``sources/lua_loader.py`` 를
        #: 고치자 3-F-30 의 ``test_27`` 이 그렇게 깨졌다.
        #: Phase commit 이 있으면 **commit 범위만** 본다.
        out += run("diff", "--name-only", f"{oldest}~1", newest)
    else:
        out += run("diff", "--name-only", "HEAD")
    out += run("diff", "--name-only", "--cached", "HEAD")
    return {line for line in out.splitlines() if line}


def test_41_an_explicit_zero_clears_but_an_unreadable_argument_does_not():
    """
    🔴 §8 · §16 — **읽지 못한 것을 빈 값으로 단정하지 않는다.**

    플래그를 하나도 못 읽은 호출은 두 가지다.

    * ``SetProperty(0)`` · ``SetCategory(0)`` — 스크립트가 **비운다.**
      덮어써서 ``[]`` 로 만드는 것이 맞다.
    * ``SetTargetRange(0,1)`` — 플레이어 대상 형식이라 ``LOCATION_*`` 이
      **애초에 없다.** 이것을 "대상 범위 없음" 으로 읽으면 **읽지 못한 것을
      단정**하는 것이고, 저장소의 규칙("unknown 을 임의로 처리하지 않는다")에
      어긋난다.

    Phase 3-E-18 이 :attr:`EffectSpec.code` 에서 "읽지 못한 것은 ``None``" 으로
    되돌린 것과 같은 원칙이다.
    """
    #: 명시적 0 — 비운다.
    cleared = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DESTROY)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCategory(0)
        c:RegisterEffect(e2)
    """)
    assert cleared[0].categories == ["DESTROY"]
    assert cleared[1].categories == []

    #: 🔴 읽을 수 없는 인자 — **물려받은 값을 그대로 둔다.**
    kept = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetTargetRange(0,1)
        c:RegisterEffect(e2)
    """)
    assert kept[0].target_ranges == ["MZONE"]
    assert kept[1].target_ranges == ["MZONE"], kept[1].target_ranges

    #: 그리고 **뒤에 읽을 수 있는 호출이 오면 그때 덮어쓴다** — 칸이 상속
    #: 상태로 남아 있기 때문이다.
    later = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetTargetRange(0,1)
        e2:SetTargetRange(LOCATION_GRAVE,0)
        c:RegisterEffect(e2)
    """)
    assert later[1].target_ranges == ["GRAVE"]

    #: 🔴 ``0,0`` 도 명시적 0 이다.
    both_zero = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetTargetRange(0,0)
        c:RegisterEffect(e2)
    """)
    assert both_zero[1].target_ranges == []

    #: 판정 자체도 고정한다.
    for literal in ("0", "0,0", " 0 , 0 "):
        assert lua_loader._RE_LITERAL_ZERO.match(literal.strip()), literal
    for other in ("0,1", "1,0", "1,1", "POS_FACEUP,1", "LOCATION_MZONE,0"):
        assert not lua_loader._RE_LITERAL_ZERO.match(other), other


def test_42_the_two_kinds_of_unreadable_call_are_counted(sources):
    """
    🔴 §9 — 그 두 종류를 corpus 전수로 센다. **11 대 16** 이다.

    .. note::
       🔴 현재 corpus 에서는 ``test_41`` 의 보호 분기가 **숫자를 바꾸지
       않는다** — 읽을 수 없는 16건은 전부 물려받은 값이 비어 있어서 더하기든
       덮어쓰기든 결과가 같다. 그래도 넣었다: 이 분기는 **지금의 숫자를 위한
       것이 아니라, 그런 스크립트가 들어와도 틀리지 않기 위한 것**이다.
    """
    explicit = unreadable = 0
    wiped_by_unreadable = []
    for card_id, body in sources.items():
        if ":Clone()" not in body:
            continue
        for field in FIELD_REGEX:
            for block in replay(body, field):
                if block["parent"] is None or not block["calls"] or block["calls"][0]:
                    continue
                setter, regex = FIELD_REGEX[field]
                #: 첫 호출의 원문을 다시 찾는다.
                args = None
                for m in lua_loader._RE_SETTER.finditer(body):
                    if m.group(1) == block["index"] and m.group(2) == setter:
                        args = lua_loader._extract_call_args(body, m.end() - 1).strip()
                        break
                assert args is not None, (card_id, field)
                if lua_loader._RE_LITERAL_ZERO.match(args):
                    explicit += 1
                else:
                    unreadable += 1
                    if block["inherited"]:
                        wiped_by_unreadable.append((card_id, field, args))

    assert explicit == 11, explicit
    assert unreadable == 16, unreadable
    #: 🔴 읽을 수 없는 호출로 지워지는 블록은 **0개**다.
    assert wiped_by_unreadable == [], wiped_by_unreadable

    #: 실제 카드로 두 종류를 못 박는다.
    assert "e2:SetCategory(0)" in script_text(3103067)
    assert "e2:SetProperty(0)" in script_text(CLEAR_PROPERTY)
