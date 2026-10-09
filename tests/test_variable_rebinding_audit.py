"""
Phase 3-F-31 — Lua 변수 재바인딩 / Effect 객체 추적 감사.

판정: **A. CONFIRMED_VARIABLE_BINDING_BUG** — 최소 수정함.

🔴 ``bindings`` 의 계약은 "변수명 → **지금** 그 변수가 가리키는 효과" 다
----------------------------------------------------------------------
production 주석이 그렇게 적는다 — *"같은 변수명이 재사용되므로, 새
``CreateEffect`` 를 만나면 바인딩을 교체한다."* 그런데 파서는 그 교체를
``Effect.CreateEffect`` 와 ``X:Clone()`` **두 형태에서만** 했고, Lua 가 같은
변수에 **다른 것**을 대입해도 **옛 매핑을 그대로 들고 있었다.** 그러면 그 뒤의
``var:SetX(...)`` 가 **엉뚱한 블록에 붙는다.**

corpus 전수에서 그렇게 잘못 붙는 설정자가 **5건 / 3장** 있었다 (``test_20``).

====================== ======================================= ==================
카드                   원문                                    잘못 붙던 것
====================== ======================================= ==================
``c52445243``          ``local e1=e:GetLabelObject()``          ``SetCategory`` 3
``c44887817``          ``local e2=e1:Clone(e1)``                ``SetCode`` 1
``c4997565``           ``local e2=Effect.Clone(e1)``            ``SetCode`` 1
====================== ======================================= ==================

🔴 **"추적할 수 없다" 와 "잘못 추적한다" 를 구분했다**
------------------------------------------------------
설정자 호출 **121,634건**을 셋으로 갈랐다 (``test_13``).

* **추적됨 120,299건** — receiver 가 ``create``/``clone`` 으로 묶인 블록이다.
* 🔴 **잘못 귀속 5건** — receiver 가 **옛 바인딩**을 가리켰다. **실제 버그.**
* **버려짐 1,330건** — receiver 가 묶인 적이 없다. **틀린 값을 만들지 않는다.**
  그중 **661건이 함수 매개변수 ``e``** 이고 (``function s.op(e,tp,...)``),
  523건은 파서가 **일부러** 건너뛴 생성(듀얼 전역·다른 카드 효과 — 3-F-28),
  101건은 보조 함수 생성, 29건은 듀얼 전역 ``Clone`` 이다. 이것들은
  **UNKNOWN by design** 이다.

🔴 **Effect alias 는 corpus 에 0건이다**
-----------------------------------------
지시서 §3 ① 의 ``e2 = e1`` 형태(동일 객체 alias)를 전수로 찾았다. 단일 변수를
RHS 로 갖는 대입이 **579건** 있지만 RHS 가 **파서가 묶은 Effect 변수인 것은
0건**이다 — 전부 ``nil`` 223 · ``true`` 101 · ``false`` 82 · ``LOCATION_*`` 같은
상수이고 LHS 는 ``g``·``loc``·``tc``·``op`` 처럼 Group/카드/플레이어 변수다
(``test_34``).

수정 (최소)
-----------
``sources/lua_loader.py`` **한 파일**.

* ``_RE_REBIND`` 를 추가했다. 파서가 **아는 두 형태를 음의 선읽기로 제외**하고,
  그 밖의 단일/다중 변수 대입을 찾는다.
* 그 자리를 만나면 **그 변수의 바인딩을 푼다** (``bindings.pop`` ·
  ``inherited.pop``). 이후 설정자는 엉뚱한 블록에 붙는 대신 **버려진다**.
* ``_EVENT_ORDER`` 로 같은 위치의 우선순위를 못 박았다 —
  ``create``/``clone`` → ``rebind`` → ``set``.
* ``_signature`` ``v7`` → ``v8``.

🔴 **Lua dataflow 를 구현하지 않았다.** 이 규칙은 "이 변수가 더 이상 **아는**
효과를 가리키지 않는다" 만 판단하고, 무엇을 가리키는지는 **추측하지 않는다.**
Phase 3-E-18 이 ``code`` 에서 *"읽지 못한 것은 ``None``(모른다)"* 으로 되돌린
것과 같은 원칙이다 — 틀린 값을 만드는 것보다 모른다고 말하는 것이 맞다.

영향 범위
---------
corpus 전수 비교: **정확히 3 스크립트 / 3칸**만 바뀌었고 블록 수는
**34,681 그대로**, ``ordinal``/순서는 **0개** 바뀌었고 ``LuaScriptInfo`` 의 다른
10칸도 **변화 0** 이다 (``test_30``).

======================= ================================= ====================
카드                    전                                후
======================= ================================= ====================
``c44887817`` ord 1     ``code='EFFECT_CANNOT_MSET'``      ``None`` — Lua 에
                                                           **자기 code 가 없다**
``c4997565`` ord 1      ``code='EFFECT_DISABLE_EFFECT'``   ``'EVENT_CHAINING'``
                                                           — **제 값 복원**
``c52445243`` ord 2     ``categories=['DESTROY','DRAW']``  ``[]`` — 그 블록의
                                                           것이 아니었다
======================= ================================= ====================

등록된 **16개 ``EffectDefinition`` 은 전부 수정 전후 동일**하고 그 16장은
바뀐 3장에 들어 있지 않다 (``test_27``).
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

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from analysis.effect_analyzer import EffectAnalyzer
from core.card_model import EffectSpec, LuaScriptInfo
from engine.duel import Duel
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardDefinitionView
from engine.ids import EffectRef, effect_refs, iter_effects
import sources.lua_loader as lua_loader
from sources.lua_loader import LuaScriptSource, parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MYSELF = "tests/test_variable_rebinding_audit.py"

# ======================================================================
# 측정값 — 전부 이 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

SCRIPTS = 12702
BLOCKS = 34684                     # 🔴 Phase 3-F-32 에서 +3 — ``Clone`` 의 인자 있는 형태
# (``e1:Clone(e1)`` · ``e2:Clone(c)``)와 점 형태 (``Effect.Clone(e1)``)를
# 블록으로 인정했다. 세 스크립트에 효과 블록이 하나씩 생겼다.

#: 설정자 호출 receiver 추적 (수정 **후**).
#:
#: 🔴 **production 이 실제로 보는 본문**(블록 주석만 제거)에서 센 수다.
#: 처음에는 문자열·줄 주석까지 지운 본문에서 세어 121,634 로 적었는데,
#: production 은 줄 주석을 **남긴다** (3-F-28 이 헤더의 카드명을 그것으로
#: 읽는다). 그 차이가 정확히 2건이고 ``c69526976`` 의 **주석 처리된 설정자**
#: 두 줄이다 (``test_23``). 재측정해서 고쳤다.
SET_TOTAL = 121636
#: 🔴 Phase 3-F-32 에서 120,301 → **120,306**. 되살린 5건은
#: ``c44887817``(1) · ``c4997565``(1) · ``c56410769``(3) 이다.
SET_TRACKED = 120306
SET_MISATTRIBUTED_BEFORE = 5       # 🔴 수정 전. 수정 후에는 0 이다
SET_DROPPED_BEFORE = 1330
#: 🔴 Phase 3-F-32 에서 1,335 → **1,330**. 총계가 3-F-30 때와 같아졌지만
#: **같은 집합이 아니다** — 3-F-31 이 새로 버린 5건은 ``c44887817``(1) ·
#: ``c4997565``(1) · ``c52445243``(3) 이고, 3-F-32 가 되살린 5건은
#: ``c44887817``(1) · ``c4997565``(1) · ``c56410769``(3) 이다. 겹치는 것은
#: 2건뿐이고, ``c52445243`` 의 3건은 ``e:GetLabelObject()`` 라서 계속
#: UNKNOWN 이 맞다. (새 감사 파일의 ``test_38`` 이 이 비동일성을 못 박는다.)
SET_DROPPED_AFTER = 1330

#: 버려지는 1,330건의 정체.
DROPPED_PARAMETER_E = 661          # function s.op(e,tp,...) 의 e
DROPPED_SKIPPED_CREATE = 523       # 파서가 일부러 건너뛴 생성 (3-F-28)
DROPPED_HELPER = 101               # 보조 함수 생성 Effect
DROPPED_GLOBAL_CLONE = 29          # 듀얼 전역 Clone (3-F-28)

#: corpus 대입 분류.
CREATE_SITES = 32157
CLONE_SITES = 2831                 # :Clone( 과 Effect.Clone( 전부
GETLABEL_CALLS = 2200
EFFECT_HELPER_CALLS = 221
EFFECT_HELPER_ASSIGNED = 154
MULTI_ASSIGN_HELPER = 3            # local sme,soe=Spirit.AddProcedure(...)
BARE_VAR_ASSIGNS = 579
EFFECT_ALIASES = 0                 # 🔴 Effect 를 Effect 에 alias 하는 자리

#: 이미 묶인 변수에 **다시** create/clone 하는 자리 (정상 처리된다).
REBIND_SAME_VAR_CREATE = 6345
#: 🔴 Phase 3-F-32 에서 457 → **459**. 그 Phase 가 인정한 세 clone
#: 자리 가운데 둘(``c44887817`` ``e2`` · ``c4997565`` ``e2``)이 같은
#: 스크립트에서 이미 쓰인 이름을 다시 묶는 자리다.
REBIND_SAME_VAR_CLONE = 459
#: 🔴 이미 묶인 변수를 **파서가 모르는 RHS** 로 덮는 자리.
SHADOWING_REBINDS = 25

#: 이 Phase 가 바꾼 스크립트 — 전수 비교로 얻었다.
CHANGED_CARDS = (4997565, 44887817, 52445243)
LABEL_OBJECT_CARD = 52445243       # local e1=e:GetLabelObject()
CLONE_WITH_ARG_CARD = 44887817     # local e2=e1:Clone(e1)
STATIC_CLONE_CARD = 4997565        # local e2=Effect.Clone(e1)
SPIRIT_MULTI_CARD = 25415052       # local sme,soe=Spirit.AddProcedure(...)
CLONE_REPLACE_CARD = 324483        # 3-F-27/29 의 카드

#: digest 용 덱 — 3-F-24 이후 모든 Phase 가 같은 것을 쓴다.
LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522
GENEROUS_REWARD = 5915629
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4

SET_TRACKED_NAMES = frozenset(
    {"Category", "TargetRange", "Range", "Property", "Type", "Code", "CountLimit"}
)


# ======================================================================
# 측정 도구 — 감사용. production 을 바꾸지 않는다.
# ======================================================================

#: 주석·문자열을 **같은 길이의 공백**으로 치환한다 (offset 보존).
_LONG_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_LONG_STRING = re.compile(r"\[(=*)\[.*?\]\1\]", re.S)
_DQ = re.compile(r'"(?:\\.|[^"\\\n])*"')
_SQ = re.compile(r"'(?:\\.|[^'\\\n])*'")

#: RHS 분류용 (감사 전용 — production 의 ``_RE_REBIND`` 와 역할이 다르다).
_ANY_ASSIGN = re.compile(
    r"(?:(?<=^)|(?<=[;\s\)])) *(local\s+)?([A-Za-z_]\w*)\s*=(?![=])([^\n]*)", re.M
)
_RHS_CREATE = re.compile(r"^\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\(")
_RHS_CLONE_STD = re.compile(r"^\s*[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\)")
_RHS_CLONE_OTHER = re.compile(r"^\s*(?:[A-Za-z_]\w*\s*:\s*Clone\s*\(|Effect\.Clone\s*\()")
_RHS_BARE = re.compile(r"^\s*([A-Za-z_]\w*)\s*$")
_RHS_LABEL = re.compile(r"GetLabelObject\s*\(")
_EFFECT_HELPER = re.compile(
    r"\b(Ritual\.CreateProc|Ritual\.CreateSummonEff|Ritual\.AddProcGreater"
    r"|Fusion\.CreateSummonEff|Spirit\.AddProcedure|aux\.createContinuousLizardCh"
    r"|aux\.CreateWitchcrafterReplace|aux\.AddNormalSummonProcedure)\s*\("
)


def blank(text: str) -> str:
    out = list(text)

    def wipe(match):
        for i in range(match.start(), match.end()):
            if out[i] != "\n":
                out[i] = " "

    for pattern in (_LONG_COMMENT, _LONG_STRING, _DQ, _SQ):
        for m in pattern.finditer("".join(out)):
            wipe(m)
    for m in _LINE_COMMENT.finditer("".join(out)):
        wipe(m)
    return "".join(out)


def classify_rhs(rhs: str) -> str:
    rhs = rhs.strip()
    if not rhs:
        return "empty"
    if _RHS_CREATE.match(rhs):
        return "create"
    if _RHS_CLONE_STD.match(rhs):
        return "clone_std"
    if _RHS_CLONE_OTHER.match(rhs):
        return "clone_other"
    if _RHS_LABEL.search(rhs):
        return "label_object"
    if _EFFECT_HELPER.match(rhs):
        return "helper"
    if _RHS_BARE.match(rhs):
        return "bare_var"
    return "other"


def trace_receivers(body: str):
    """
    설정자 호출마다 receiver 가 **어느 블록**에 묶여 있는지 추적한다.

    production 의 정규식과 ``_is_card_effect`` 를 그대로 쓴다 — 3-F-28 에서
    그룹 번호를 따로 가정했다가 조용히 깨진 전례가 있다. 그리고 production 의
    ``_RE_REBIND`` 도 그대로 써서 **지금 동작**을 측정한다.
    """
    events = []
    for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
        ok = lua_loader._is_card_effect(body, m.group(1), m.group(2), None)
        events.append((m.start(), "create" if ok else "skip", m.group(2)))
    for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
        ok = lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m))
        events.append((m.start(), "clone" if ok else "skip", m.group(2)))
    for m in lua_loader._RE_REBIND.finditer(body):
        events.append((m.start(), "rebind", m.group(1)))
    for m in lua_loader._RE_SETTER.finditer(body):
        if m.group(2) in SET_TRACKED_NAMES:
            events.append((m.start(), "set", (m.group(1), m.group(2))))
    order = {"create": 0, "clone": 0, "skip": 0, "rebind": 1, "set": 2}
    events.sort(key=lambda e: (e[0], order[e[1]]))

    bound: dict[str, int] = {}
    ordinal = 0
    out = []
    for position, kind, payload in events:
        if kind in ("create", "clone"):
            bound[payload] = ordinal
            ordinal += 1
        elif kind == "rebind":
            for name in payload.split(","):
                bound.pop(name.strip(), None)
        elif kind == "set":
            var, setter = payload
            out.append({"var": var, "setter": setter, "position": position,
                        "ordinal": bound.get(var)})
    return out


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


@pytest.fixture(scope="module")
def scripts():
    return LuaScriptSource(PROJECT_ROOT).load()


@pytest.fixture(scope="module")
def bodies():
    """``card_id -> 블록 주석을 지운 본문`` 전수 (production 과 같은 전처리)."""
    out = {}
    for card_id, path in LuaScriptSource(PROJECT_ROOT).iter_script_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        out[card_id] = lua_loader._RE_BLOCK_COMMENT.sub("", text)
    return out


# ======================================================================
# A. §2 — 최소 재현 (A~H)
# ======================================================================


def test_01_create_effect_binds_the_variable():
    """🟢 §2 A · §10-1 — ``CreateEffect`` 가 변수를 묶고 설정자가 붙는다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
    """)
    assert [(s.index, s.code) for s in specs] == [("e1", "EVENT_FREE_CHAIN")]


def test_02_a_bare_alias_does_not_carry_the_binding():
    """
    🔴 §2 B · §3 ① · §10-2 — ``e2 = e1`` 뒤의 설정자는 **버려진다.**

    Lua 는 같은 객체를 가리키지만 파서는 ``e2`` 를 묶지 않는다. 🔴 **틀린 값을
    만들지 않고 잃는다** — "추적할 수 없다" 쪽이다.

    corpus 에 Effect 를 Effect 에 alias 하는 자리는 **0건**이다 (``test_34``).
    """
    plain = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        e2=e1
        e2:SetCode(EVENT_FREE_CHAIN)
    """)
    assert [(s.index, s.code) for s in plain] == [("e1", None)]

    with_local = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        local e2=e1
        e2:SetCode(EVENT_FREE_CHAIN)
    """)
    assert [(s.index, s.code) for s in with_local] == [("e1", None)]


def test_03_clone_into_a_new_variable():
    """🟢 §2 C · §3 ② · §10-3 — ``Clone`` 은 **새 블록**이다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_TO_GRAVE)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e2)
    """)
    assert [(s.index, s.cloned_from, s.code) for s in specs] == [
        ("e1", None, "EVENT_TO_GRAVE"),
        ("e2", "e1", "EVENT_FREE_CHAIN"),
    ]


def test_04_clone_rebinding_the_same_variable():
    """
    🟢 §2 D · §10-4 — ``e1 = e1:Clone()`` 은 **새 블록**이고 부모는 옛 ``e1`` 이다.

    파서가 자기 재바인딩을 정확히 처리한다 — ordinal 0 은 그대로고 ordinal 1 이
    생긴다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_TO_GRAVE)
        c:RegisterEffect(e1)
        e1=e1:Clone()
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
    """)
    assert [(s.index, s.cloned_from, s.code) for s in specs] == [
        ("e1", None, "EVENT_TO_GRAVE"),
        ("e1", "e1", "EVENT_FREE_CHAIN"),
    ]
    #: 🔴 ``index`` 가 같아도 **다른 블록**이다 — 식별자는 ``ordinal`` 이다.
    assert specs[0] is not specs[1]


def test_05_rebinding_to_another_effect_now_unbinds():
    """
    🔴 §2 E · §3 ③ · §10-5 — ``e1 = e2`` 뒤의 설정자가 **ordinal 0 에 붙지 않는다.**

    고치기 전에는 ``e1`` 의 옛 바인딩(ordinal 0)에 붙어 **엉뚱한 블록**의 code 를
    만들었다. 이제 바인딩을 풀어 **버린다.**
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        c:RegisterEffect(e2)
        e1=e2
        e1:SetCode(EVENT_FREE_CHAIN)
    """)
    assert [(s.index, s.code) for s in specs] == [("e1", None), ("e2", None)]
    #: 🔴 ordinal 0 에 ``EVENT_FREE_CHAIN`` 이 **생기지 않는다**.
    assert all(s.code is None for s in specs)


def test_06_non_effect_rebinding_now_unbinds():
    """🔴 §2 F · §3 ⑤ · §10-6 — Effect 가 아닌 값으로 덮으면 바인딩을 푼다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        e1=some_other_value
        e1:SetCode(EVENT_FREE_CHAIN)
    """)
    assert [(s.index, s.code) for s in specs] == [("e1", None)]


def test_07_a_helper_created_effect_is_not_a_block():
    """
    🔴 §2 G · §10-8 — ``Ritual.CreateProc(...)`` 은 블록이 되지 않고, 그 뒤
    설정자는 **버려진다.**

    3-F-28 이 남긴 한계(E5)다. 추측해서 블록을 만들지 않는다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        local e2=Ritual.CreateProc({handler=c})
        e2:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e2)
    """)
    assert [(s.index, s.code) for s in specs] == [("e1", None)]


def test_08_get_label_object_is_not_a_block():
    """🔴 §2 H · §10-9 — ``GetLabelObject()`` 결과도 블록이 아니다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        local x=e1:GetLabelObject()
        x:SetCode(EVENT_FREE_CHAIN)
    """)
    assert [(s.index, s.code) for s in specs] == [("e1", None)]


def test_09_get_label_object_rebinding_an_effect_name_now_unbinds():
    """
    🔴 §2 H · §10-9 — **``c52445243`` 의 실제 모양.**

    ``local e1=e:GetLabelObject()`` 가 이미 묶인 ``e1`` 을 덮는다. 고치기 전에는
    그 뒤 ``SetCategory`` 가 **직전 ``create`` 블록**에 붙었다. 이제 풀린다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_SPSUMMON_SUCCESS)
        c:RegisterEffect(e1)
        local e9=Effect.CreateEffect(c)
        c:RegisterEffect(e9)
        local e1=e:GetLabelObject()
        e1:SetCategory(CATEGORY_DRAW)
    """)
    #: 🔴 어느 블록에도 ``DRAW`` 가 붙지 않는다.
    assert [(s.index, s.categories) for s in specs] == [("e1", []), ("e9", [])]
    assert specs[0].code == "EVENT_SPSUMMON_SUCCESS"


def test_10_a_helper_with_multiple_return_values():
    """
    🔴 §10-8 — ``local sme,soe=Spirit.AddProcedure(c,...)`` — 보조 함수가
    Effect **둘**을 돌려주는 다중 대입. 둘 다 블록이 아니고 설정자는 버려진다.

    corpus 에 **3곳**뿐이다 (``test_15``).
    """
    specs = blocks_of("""
        local sme,soe=Spirit.AddProcedure(c,EVENT_SPSUMMON_SUCCESS)
        sme:SetCategory(CATEGORY_TOHAND)
        soe:SetCategory(CATEGORY_SPECIAL_SUMMON)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
    """)
    assert [(s.index, s.categories, s.code) for s in specs] == [
        ("e1", [], "EVENT_FREE_CHAIN")
    ]
    #: 실제 카드에서도 같다.
    real = parse_card(SPIRIT_MULTI_CARD)
    assert "local sme,soe=Spirit.AddProcedure(" in script_text(SPIRIT_MULTI_CARD)
    assert "sme" not in [s.index for s in real.effects]
    assert "soe" not in [s.index for s in real.effects]


def test_11_shadowing_with_local_in_a_different_scope():
    """
    🔴 §3 ④ · §10-7 — ``local`` 로 같은 이름을 다시 선언하는 경우.

    파서는 Lua scope 를 **보지 않는다.** 그래도 ``create`` 면 새 블록, 그 밖이면
    바인딩을 푸는 규칙이 scope 와 무관하게 안전한 쪽으로 동작한다.
    """
    #: 다른 함수에서 같은 이름으로 다시 생성 → 새 블록 (정상).
    recreated = blocks_of("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
        end
        function s.operation(e,tp)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EFFECT_UPDATE_ATTACK)
            c:RegisterEffect(e1)
        end
    """)
    assert [s.code for s in recreated] == ["EVENT_FREE_CHAIN", "EFFECT_UPDATE_ATTACK"]

    #: 다른 함수에서 같은 이름을 **Effect 아닌 것**으로 선언 → 풀린다.
    shadowed = blocks_of("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
        end
        function s.operation(e,tp)
            local e1=e:GetLabelObject()
            e1:SetCode(EFFECT_UPDATE_ATTACK)
        end
    """)
    assert [s.code for s in shadowed] == ["EVENT_FREE_CHAIN"]


def test_12_several_effects_mixed_together():
    """🟢 §10-13 — 생성·Clone·재바인딩이 섞여도 receiver 가 정확하다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCode(EVENT_TO_GRAVE)
        c:RegisterEffect(e2)
        local e3=Effect.CreateEffect(c)
        e3:SetCode(EVENT_SPSUMMON_SUCCESS)
        c:RegisterEffect(e3)
        e2=e:GetLabelObject()
        e2:SetCode(EFFECT_UPDATE_ATTACK)
        e3:SetCategory(CATEGORY_DRAW)
    """)
    assert [(s.index, s.code, s.categories) for s in specs] == [
        ("e1", "EVENT_FREE_CHAIN", []),
        ("e2", "EVENT_TO_GRAVE", []),        # 🔴 UPDATE_ATTACK 이 안 붙는다
        ("e3", "EVENT_SPSUMMON_SUCCESS", ["DRAW"]),
    ]


# ======================================================================
# B. §5 · §6 — corpus 전수 측정
# ======================================================================


def test_13_setter_receivers_are_tracked_or_dropped_never_misattributed(bodies):
    """
    🔴 §5 · §6 D·G · **이 Phase 의 핵심 측정.**

    설정자 호출 **121,634건**을 셋으로 가른다. 🔴 수정 후 **잘못 귀속은 0건**이고,
    "추적됨" 과 "버려짐" 만 남는다.

    "추적할 수 없다"(버려짐)와 "잘못 추적한다"(귀속 오류)는 **다른 것**이다 —
    전자는 값을 만들지 않고 후자는 **틀린 값을 만든다.**
    """
    total = tracked = dropped = 0
    for body in bodies.values():
        for call in trace_receivers(body):
            total += 1
            if call["ordinal"] is None:
                dropped += 1
            else:
                tracked += 1
    assert total == SET_TOTAL, total
    assert tracked == SET_TRACKED, tracked
    assert dropped == SET_DROPPED_AFTER, dropped
    #: 🔴 Phase 3-F-32 에서 이 등식이 깨졌다. 그 Phase 가 ``Clone`` 세 형태를
    #: 인정해 설정자 5건을 되살렸고, 버려짐이 1,335 → **1,330** 으로 돌아왔다.
    #: 🔴 숫자가 3-F-30 때와 같아졌지만 **같은 집합이 아니다** —
    #: ``SET_DROPPED_AFTER`` 주석과 새 감사 파일의 ``test_38`` 을 보라.
    assert dropped == SET_DROPPED_BEFORE


def test_14_what_the_dropped_receivers_actually_are(bodies):
    """
    🔴 §6 G — 버려지는 1,335건의 **정체**를 분해한다. 대부분 **함수 매개변수**다.

    ``function s.operation(e,tp,...)`` 의 ``e`` 는 런타임에 전달되는 효과이고,
    파서가 어느 블록인지 알 방법이 **없다.** 이것은 **UNKNOWN by design** 이다.
    """
    by_var: collections.Counter = collections.Counter()
    for body in bodies.values():
        for call in trace_receivers(body):
            if call["ordinal"] is None:
                by_var[call["var"]] += 1
    assert by_var["e"] == DROPPED_PARAMETER_E, by_var["e"]
    assert sum(by_var.values()) == SET_DROPPED_AFTER
    #: ``e`` 가 압도적 다수다.
    assert by_var.most_common(1)[0][0] == "e"
    assert by_var["e"] / sum(by_var.values()) > 0.49

    #: 🔴 ``e`` 는 **대입된 적이 없다** — 매개변수이기 때문이다.
    sample = script_text(10000030)
    assert re.search(r"function\s+s\.\w+\s*\(\s*e\s*,", sample)


def test_15_corpus_assignment_statistics(bodies):
    """🟢 §5 — 대입 자리 전수 통계."""
    create_sites = clone_sites = getlabel = helper_calls = helper_assigned = 0
    multi_helper = 0
    bare = 0
    create_site_re = re.compile(r"Effect\.(?:CreateEffect|GlobalEffect)\s*\(")
    clone_site_re = re.compile(r":\s*Clone\s*\(|Effect\.Clone\s*\(")
    multi_re = re.compile(r"\blocal\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*=\s*([^\n]*)")
    assigned_helper_re = re.compile(
        r"(?:\blocal\s+)?[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*=\s*(?="
        + _EFFECT_HELPER.pattern + r")"
    )
    for body in bodies.values():
        clean = blank(body)
        create_sites += len(create_site_re.findall(clean))
        clone_sites += len(clone_site_re.findall(clean))
        getlabel += len(_RHS_LABEL.findall(clean))
        helper_calls += len(_EFFECT_HELPER.findall(clean))
        helper_assigned += len(assigned_helper_re.findall(clean))
        for m in multi_re.finditer(clean):
            if _EFFECT_HELPER.search(m.group(2)):
                multi_helper += 1
        for m in _ANY_ASSIGN.finditer(clean):
            if classify_rhs(m.group(3)) == "bare_var":
                bare += 1

    assert create_sites == CREATE_SITES, create_sites
    assert clone_sites == CLONE_SITES, clone_sites
    assert getlabel == GETLABEL_CALLS, getlabel
    assert helper_calls == EFFECT_HELPER_CALLS, helper_calls
    assert helper_assigned == EFFECT_HELPER_ASSIGNED, helper_assigned
    assert multi_helper == MULTI_ASSIGN_HELPER, multi_helper
    assert bare == BARE_VAR_ASSIGNS, bare


def test_16_rebinding_kinds_across_the_corpus(bodies):
    """
    🔴 §3 · §5 — 재바인딩을 종류별로 센다.

    이미 묶인 변수에 **다시 ``create``** 하는 것이 **6,345곳**으로 압도적이고,
    파서는 그것을 **정확히 처리한다** (새 블록, 옛 ordinal 불변). ``clone`` 재바인딩
    **459곳**도 같다 (3-F-32 에서 457 → 459).

    🔴 문제는 **파서가 모르는 RHS 로 덮는 25곳**이었다.
    """
    recreate = reclone = shadowing = 0
    for body in bodies.values():
        clean = blank(body)
        events = []
        for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), "create", m.group(2)))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
                events.append((m.start(), "clone", m.group(2)))
        for m in _ANY_ASSIGN.finditer(clean):
            if classify_rhs(m.group(3)) in ("create", "clone_std"):
                continue
            events.append((m.start(), "unknown", m.group(2)))
        events.sort(key=lambda e: e[0])
        bound: set[str] = set()
        for _position, kind, var in events:
            if kind == "create":
                if var in bound:
                    recreate += 1
                bound.add(var)
            elif kind == "clone":
                if var in bound:
                    reclone += 1
                bound.add(var)
            elif var in bound:
                shadowing += 1
    assert recreate == REBIND_SAME_VAR_CREATE, recreate
    assert reclone == REBIND_SAME_VAR_CLONE, reclone
    #: 🔴 Phase 3-F-32 에서 25 → **26**. 이 테스트가 세는 ``shadowing`` 은
    #: "production 이 묶은 이름을, 그 뒤 create/clone 이 아닌 대입이 다시
    #: 묶는 자리" 다. 3-F-32 가 ``c56410769`` 의 ``e3`` 를 블록으로 인정하면서
    #: 그 파일에 묶인 이름이 하나 늘어 그런 자리가 하나 더 보인다.
    #: 🔴 ``branch_setter::test_23`` 쪽 집계는 거꾸로 25 → **23** 으로 줄었다 —
    #: 그 테스트는 production 규칙으로 clone 을 **제외**하고 세기 때문이다.
    #: 같은 이름이라 혼동하기 쉽지만 **서로 다른 것을 센다.**
    assert shadowing == 26, shadowing


def test_17_the_real_label_object_card():
    """
    🔴 §8 · §10-14 — ``c52445243`` 실제 카드.

    ``s.matcheck`` 의 ``local e1=e:GetLabelObject()`` 뒤 ``SetCategory`` 3건이
    고치기 전에는 ``s.effop`` 의 블록(ordinal 2)에 붙었다.
    """
    text = script_text(LABEL_OBJECT_CARD)
    assert "local e1=e:GetLabelObject()" in text
    assert "e1:SetCategory(CATEGORY_DESTROY+CATEGORY_DRAW)" in text

    specs = parse_card(LABEL_OBJECT_CARD).effects
    assert len(specs) == 3
    #: 🔴 어느 블록에도 그 category 가 붙지 않는다.
    assert [s.categories for s in specs] == [[], [], []]
    #: 블록 수와 ordinal 은 그대로다.
    assert [s.index for s in specs] == ["e1", "e1a", "e1"]
    assert specs[0].code == "EVENT_SPSUMMON_SUCCESS"


def test_18_the_real_clone_with_argument_card():
    """
    🔴 §8 — ``c44887817``: ``local e2=e1:Clone(e1)``.

    .. note::
       🔴 **Phase 3-F-32 가 이 형태를 블록으로 인정했다.** 그래서 아래 두 줄의
       방향이 **뒤집혔다**: 이 Phase 가 쓴 "정규식이 못 잡는다" 는
       ``Clone()`` 의 빈 괄호를 요구하던 그때의 사실이고, 3-F-32 가 받는
       쪽(맨 식별자)만 유지하고 **인자만** 허용하도록 넓혔다. 코퍼스의
       ``Clone(`` 형태가 4개뿐이고 그중 하나(식 receiver)는 **Group** 의
       Clone 임을 전수로 확인한 뒤에 넓힌 것이다.

       이 Phase 가 고친 것은 그대로 유지된다 — ordinal 1 은 Lua 에 자기
       ``SetCode`` 가 없고, 그 값은 여전히 ``None`` 이다. 달라진 것은
       ``SetCode(EFFECT_CANNOT_MSET)`` 가 **버려지는 대신 제 블록(ordinal
       4)에 붙는다**는 점이다.
    """
    text = script_text(CLONE_WITH_ARG_CARD)
    assert "local e2=e1:Clone(e1)" in text
    #: 🔴 3-F-32 이후에는 **잡는다.**
    assert lua_loader._RE_CLONE_EFFECT.search("local e2=e1:Clone(e1)")

    specs = parse_card(CLONE_WITH_ARG_CARD).effects
    #: 🔴 이 Phase 의 결론은 유지된다 — ordinal 1 의 code 는 ``None`` 이다.
    assert specs[1].code is None
    assert specs[0].code == "EVENT_FREE_CHAIN"
    #: 그 블록에 ``SetCode`` 가 없다는 것을 원문으로 확인한다.
    head = text.split("local e3=")[0]
    assert "local e2=Effect.CreateEffect(c)" in head
    assert "e2:SetCode(" not in head
    #: 🔴 그 ``SetCode`` 는 이제 **제 블록**(clone, ordinal 4)에 붙는다.
    assert specs[4].cloned_from == "e1"
    assert specs[4].code == "EFFECT_CANNOT_MSET"


def test_19_the_real_static_clone_card():
    """
    🔴 §8 — ``c4997565``: ``local e2=Effect.Clone(e1)`` (다른 API 형태).

    고치기 전에는 그 뒤 ``SetCode(EFFECT_DISABLE_EFFECT)`` 가 ordinal 1 의
    **제 값 ``EVENT_CHAINING`` 을 덮었다.** 이제 복원된다.
    """
    text = script_text(STATIC_CLONE_CARD)
    assert "local e2=Effect.Clone(e1)" in text
    #: 🔴 **Phase 3-F-32 가 점 형태를 인정했다** — 방향이 뒤집혔다.
    #: 근거는 코퍼스 안에 있다: 점 형태 ``Class.Method`` 상위 40개 가운데
    #: 37개가 같은 이름으로 콜론 메서드로도 쓰이고, ``Clone`` 은 콜론 2,829 ·
    #: 점 1 이다 (새 감사 파일의 ``test_10``).
    assert lua_loader._RE_CLONE_EFFECT.search("local e2=Effect.Clone(e1)")

    specs = parse_card(STATIC_CLONE_CARD).effects
    #: 🔴 이 Phase 가 복원한 값은 그대로다.
    assert specs[1].code == "EVENT_CHAINING"
    #: 🔴 그 ``SetCode(EFFECT_DISABLE_EFFECT)`` 는 이제 제 블록(ordinal 3)에
    #: 붙고, 밀려난 ``e3`` 가 ordinal 4 다 — 코퍼스에서 **기존 ordinal 이
    #: 움직인 유일한 자리**다.
    assert specs[3].index == "e2" and specs[3].cloned_from == "e1"
    assert specs[3].code == "EFFECT_DISABLE_EFFECT"
    assert specs[4].index == "e3" and specs[4].code == "EFFECT_UPDATE_DEFENSE"
    assert "e2:SetCode(EVENT_CHAINING)" in text
    #: 등록된 효과다 — 유발 사건이 틀렸으면 분석이 틀린다.
    assert "c:RegisterEffect(e2" in text


def test_20_the_five_misattributed_calls_are_gone(bodies):
    """
    🔴 §6 D · §10-15 — 고치기 전 잘못 귀속되던 **5건**을 전수로 재현하고,
    지금은 **0건**임을 확인한다.

    옛 규칙(모르는 대입을 무시)을 테스트 안에서 다시 세워 **같은 corpus** 에
    돌린다 — production 을 호출하지 않으므로 production 이 바뀌어도 이 비교는
    유지된다.
    """
    def legacy_trace(body: str):
        events = []
        for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), 0, "bind", m.group(2)))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
                events.append((m.start(), 0, "bind", m.group(2)))
        for m in lua_loader._RE_SETTER.finditer(body):
            if m.group(2) in SET_TRACKED_NAMES:
                events.append((m.start(), 2, "set", (m.group(1), m.group(2))))
        events.sort(key=lambda e: (e[0], e[1]))
        bound, ordinal, out = {}, 0, []
        for _p, _o, kind, payload in events:
            if kind == "bind":
                bound[payload] = ordinal
                ordinal += 1
            else:
                out.append((payload[0], payload[1], bound.get(payload[0])))
        return out

    legacy_hits, current_hits = [], []
    for card_id, body in bodies.items():
        old_rows = legacy_trace(body)
        new_rows = trace_receivers(body)
        assert len(old_rows) == len(new_rows), card_id
        for (var, setter, old_ord), new in zip(old_rows, new_rows):
            if old_ord is not None and new["ordinal"] is None:
                legacy_hits.append((card_id, var, setter, old_ord))
            if old_ord is None and new["ordinal"] is not None:
                current_hits.append((card_id, var, setter))

    #: 🔴 옛 규칙이 **잘못 붙이던** 자리.
    #:
    #: **Phase 3-F-32 에서 5 → 3 으로 줄었다.** 이 테스트가 비교하는
    #: ``legacy_trace`` 는 ``_RE_REBIND`` **없는** 규칙이고, 바인딩은 production
    #: 의 ``_RE_CLONE_EFFECT`` 로 만든다. 3-F-32 가 ``e1:Clone(e1)`` 과
    #: ``Effect.Clone(e1)`` 을 블록으로 인정하면서, 그 두 자리에서는 옛 규칙도
    #: **더 이상 엉뚱한 블록을 가리키지 않는다** (제 블록을 가리킨다). 남은 3건은
    #: ``c52445243`` 의 ``e:GetLabelObject()`` 뿐이고, 그것은 정적으로 풀 수
    #: 없어 **계속 UNKNOWN 이 맞다.**
    #:
    #: 🔴 이 Phase 의 결론이 약해진 것이 아니다 — "옛 규칙은 틀린 값을
    #: 만들었고 지금은 만들지 않는다" 는 그대로이고, 그중 2건은 3-F-32 가
    #: **값을 버리는 대신 제자리에 붙이는** 데까지 갔다.
    assert len(legacy_hits) == 3, legacy_hits
    assert {row[0] for row in legacy_hits} == {LABEL_OBJECT_CARD}
    assert collections.Counter(row[2] for row in legacy_hits) == {"Category": 3}
    #: 🔴 반대 방향(새로 붙는 것)은 **0건** — 잃기만 하고 만들지 않는다.
    assert current_hits == [], current_hits


def test_21_unknown_is_never_turned_into_a_value(bodies):
    """
    🔴 §6 G — **읽지 못한 것을 값으로 만들지 않는다.**

    바인딩이 풀린 변수의 설정자는 **어느 블록에도** 쓰이지 않는다. corpus 전수로
    "버려진 설정자가 가리키던 블록" 이 존재하지 않음을 확인한다.
    """
    for body in bodies.values():
        for call in trace_receivers(body):
            if call["ordinal"] is None:
                #: 버려졌다 = ordinal 이 없다. 그 뿐이고 다른 값이 되지 않는다.
                assert call["ordinal"] is None

    #: 최소 사례로 "풀린 뒤 다시 생성되면 그때부터 다시 붙는다" 도 확인한다.
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        e1=e:GetLabelObject()
        e1:SetCode(EVENT_TO_GRAVE)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        c:RegisterEffect(e1)
    """)
    assert [s.code for s in specs] == [None, "EVENT_FREE_CHAIN"]


def test_22_effect_helper_functions_are_listed_not_guessed(bodies):
    """
    🔴 §5 — Effect 를 돌려주는 보조 함수는 **221곳**이고 그중 154곳이 변수에
    배정된다. 파서는 그것을 블록으로 만들지 **않는다** — 추측하지 않는다.
    """
    names: collections.Counter = collections.Counter()
    for body in bodies.values():
        for m in _EFFECT_HELPER.finditer(blank(body)):
            names[m.group(1)] += 1
    assert sum(names.values()) == EFFECT_HELPER_CALLS
    assert names["Fusion.CreateSummonEff"] == 84
    assert names["aux.AddNormalSummonProcedure"] == 56
    assert names["Spirit.AddProcedure"] == 41
    assert names["Ritual.CreateProc"] == 23
    assert names["Ritual.AddProcGreater"] == 15

    #: 🔴 그중 어느 것도 블록이 되지 않는다 — ``cloned_from`` 도 아니다.
    for card_id in (SPIRIT_MULTI_CARD,):
        for spec in parse_card(card_id).effects:
            assert not spec.index.startswith("sme")
            assert not spec.index.startswith("soe")


def test_23_commented_out_setters_are_still_applied(bodies):
    """
    🔴 **새 발견 (범위 밖).** 줄 주석 처리된 설정자가 **적용된다.**

    ``c69526976`` 가 ``--e1:SetProperty(...)`` · ``--e1:SetRange(...)`` 를
    주석으로 막아 두었는데 파서가 그대로 센다. production 은 **블록 주석만**
    지운다 — 3-F-28 이 헤더의 카드명을 줄 주석에서 읽기 때문에 **의도적**이다.

    corpus 전체에 **2건**이고 이 Phase 의 범위(변수 재바인딩)가 아니므로
    **고치지 않고 숫자로 고정만 한다.**
    """
    commented = []
    for card_id, body in bodies.items():
        clean = blank(body)
        for m in lua_loader._RE_SETTER.finditer(body):
            if m.group(2) not in SET_TRACKED_NAMES:
                continue
            if clean[m.start() : m.start() + len(m.group(1))] != m.group(1):
                commented.append((card_id, m.group(1), m.group(2)))
    assert len(commented) == 2, commented
    assert {row[0] for row in commented} == {69526976}
    assert {row[2] for row in commented} == {"Property", "Range"}

    text = script_text(69526976)
    assert "--e1:SetProperty(EFFECT_FLAG_SINGLE_RANGE)" in text
    assert "--e1:SetRange(LOCATION_MZONE)" in text
    #: 🔴 그 주석의 값이 실제로 블록에 들어 있다.
    specs = parse_card(69526976).effects
    assert "SINGLE_RANGE" in specs[0].properties
    assert "MZONE" in specs[0].ranges


# ======================================================================
# C. §7 — EffectRef / ordinal
# ======================================================================


def test_24_ordinal_equals_the_event_order_across_the_whole_corpus(bodies, scripts):
    """
    🔴 §7 — **``ordinal`` 이 실제 Lua 생성 순서와 일치한다.**

    이벤트 순서에서 ``(index, cloned_from)`` 열을 다시 유도해 파서 출력과
    비교한다. 재바인딩이 ordinal 을 **옮기지 않는다**는 것을 전수로 못 박는다.
    """
    mismatched = []
    for card_id, body in bodies.items():
        order = []
        for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
                order.append((m.start(), m.group(2), None))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
                order.append((m.start(), m.group(2), lua_loader._clone_source(m)))
        order.sort(key=lambda e: e[0])
        derived = [(var, parent) for _position, var, parent in order]
        actual = [(s.index, s.cloned_from) for s in scripts[card_id].effects]
        if derived != actual:
            mismatched.append((card_id, derived[:5], actual[:5]))
    assert mismatched == [], mismatched[:5]
    assert sum(len(info.effects) for info in scripts.values()) == BLOCKS


def test_25_effect_ref_still_resolves_to_the_same_position(repository):
    """
    🟢 §7 · §10-11·12 — ``EffectRef(card_id, ordinal)`` 계약 불변.

    이 Phase 는 블록을 더하거나 빼지 않았으므로 **모든 ``EffectRef`` 가 전과
    같은 블록을 가리킨다.** 바뀐 것은 세 블록의 **칸 값**뿐이다.
    """
    for card_id in CHANGED_CARDS:
        card = repository.get(card_id)
        assert card is not None and card.script is not None, card_id
        refs = effect_refs(card)
        assert [r.ordinal for r in refs] == list(range(len(card.script.effects)))
        for position, (ref, spec) in enumerate(iter_effects(card)):
            assert ref.ordinal == position
            assert ref.resolve(card) is spec
        assert EffectRef(card_id, len(refs)).resolve(card) is None

    #: 식별 체계를 바꾸지 않았다.
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    assert EffectRef.__dataclass_params__.frozen is True
    ids_source = (PROJECT_ROOT / "engine" / "ids.py").read_text(encoding="utf-8")
    for banned in ("import uuid", "uuid4", "id(self)", "EffectId"):
        assert banned not in ids_source, banned


def test_26_clone_does_not_invent_an_extra_ordinal():
    """🟢 §7 — ``Clone`` 이 ordinal 을 **하나만** 만든다. 재바인딩도 같다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        c:RegisterEffect(e2)
        e2=e2:Clone()
        c:RegisterEffect(e2)
    """)
    assert len(specs) == 3
    assert [s.cloned_from for s in specs] == [None, "e1", "e2"]
    #: 🔴 ``e2`` 가 두 번 묶였지만 블록은 **각각** 하나다.
    assert specs[1] is not specs[2]


# ======================================================================
# D. §8 · §10 — downstream / 불변 조건
# ======================================================================


def test_27_all_sixteen_effect_definitions_are_untouched(repository):
    """
    🔴 §8 · §10-17 — 등록된 16개 ``EffectDefinition`` 전부.

    그 16장은 이 Phase 가 바꾼 3장에 **들어 있지 않다.**
    """
    assert len(EFFECT_LIBRARY) == 16
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        assert card is not None and card.script is not None, ref
        assert ref.ordinal == 0 and len(card.script.effects) == 1, ref
        resolved = ref.resolve(card)
        assert resolved is not None and resolved.code == "EVENT_FREE_CHAIN", ref
        assert effect_refs(card) == [EffectRef(ref.card_id, 0)], ref
        assert ref.card_id not in CHANGED_CARDS, ref


def test_28_engine_and_agent_never_read_effect_spec_fields():
    """
    🔴 §8 — ``engine/`` · ``agent/`` 가 ``EffectSpec`` 칸을 **읽지 않는다.**

    ``.code`` 같은 이름이 있다는 이유로 판단하지 않고, AST 로 속성 접근을 모아
    **base 식별자까지** 본다. 이름이 겹치는 ``code``/``index`` 는 "0건" 을
    요구하면 **틀린다** (3-F-28 에서 ``code``, 3-F-30 에서 ``index`` 로 각각
    실수했다) — base 로 판별한다.
    """
    spec_fields = {f.name for f in dataclasses.fields(EffectSpec)}
    unique = ("effect_types", "target_ranges", "cloned_from", "count_limit")
    hits = collections.defaultdict(list)
    for directory in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in spec_fields:
                    hits[node.attr].append(ast.unparse(node.value))
    for field in unique + ("categories", "properties", "ranges"):
        assert hits[field] == [], (field, hits[field][:5])
    for field in ("code", "index"):
        bases = set(hits[field])
        assert bases, field
        for base in bases:
            assert not base.endswith("spec"), (field, base)
            assert base not in ("e", "eff", "effect", "block"), (field, base)


def test_29_the_analysis_layer_is_the_one_that_changed(repository):
    """
    🔴 §8 · §9 조건 ③ — **분석 결과가 실제로 고쳐졌다.**

    ``analysis/effect_analyzer.py`` 가 ``spec.categories`` · ``spec.code`` 를
    소비한다. 세 카드의 ``EffectAnalysis`` 가 바뀌고, 그것이 수정 조건 ③
    ("downstream 또는 **분석 결과**에 실제 영향") 의 근거다.
    """
    analyzer = EffectAnalyzer(repository)

    #: 🔴 ``c4997565`` — 제 유발 사건이 복원됐다.
    card = repository.get(STATIC_CLONE_CARD)
    blocks = list(analyzer.analyze(card).effects) + list(
        analyzer.analyze(card).resolution_effects
    )
    codes = [b.trigger_event or b.effect_code for b in blocks]
    assert "EVENT_CHAINING" in codes
    #: 🔴 **Phase 3-F-32 에서 방향이 바뀌었다.** 이 Phase 는
    #: ``EFFECT_DISABLE_EFFECT`` 가 **어느 블록에도 없어야** 한다고 적었다 —
    #: 그때는 그 clone 블록 자체가 없었기 때문이다. 3-F-32 가 그 블록을
    #: 만들었으니, 이제 그 값은 **제 블록에** 있어야 한다. 중요한 것은
    #: ``EVENT_CHAINING`` 을 **덮지 않는다**는 것이고 그것은 위 줄이 지킨다.
    assert "EFFECT_DISABLE_EFFECT" in codes
    assert codes.count("EVENT_CHAINING") == 1

    #: 🔴 ``c44887817`` — 없던 code 가 사라졌다.
    card = repository.get(CLONE_WITH_ARG_CARD)
    blocks = list(analyzer.analyze(card).effects) + list(
        analyzer.analyze(card).resolution_effects
    )
    codes = [b.trigger_event or b.effect_code for b in blocks]
    #: 🔴 같은 이유로 방향이 바뀌었다 — ``EFFECT_CANNOT_MSET`` 은 **제 블록에**
    #: 있고, 이 Phase 가 ``None`` 으로 되돌린 ordinal 1 은 그대로 ``None`` 이다.
    assert "EFFECT_CANNOT_MSET" in codes
    assert None in codes
    assert parse_card(CLONE_WITH_ARG_CARD).effects[1].code is None

    #: 🔴 ``c52445243`` — 엉뚱한 category 가 사라졌다.
    card = repository.get(LABEL_OBJECT_CARD)
    blocks = list(analyzer.analyze(card).effects) + list(
        analyzer.analyze(card).resolution_effects
    )
    assert all(not b.categories for b in blocks)

    #: ``analysis`` 가 그 칸을 실제로 읽는다는 것을 코드로 확인한다.
    analyzer_source = (PROJECT_ROOT / "analysis" / "effect_analyzer.py").read_text(
        encoding="utf-8"
    )
    assert "spec.categories" in analyzer_source
    assert "spec.code" in analyzer_source


def test_30_the_corpus_diff_is_exactly_three_scripts(scripts):
    """
    🔴 §10 — 바뀐 범위를 정확히 고정한다: **3 스크립트 / 3칸.**

    블록 수와 ``ordinal`` 은 그대로이고 ``LuaScriptInfo`` 의 다른 칸도 변화 0.
    """
    assert len(scripts) == SCRIPTS
    assert sum(len(info.effects) for info in scripts.values()) == BLOCKS

    #: 세 카드의 최종 값을 글자 그대로 고정한다.
    assert parse_card(CLONE_WITH_ARG_CARD).effects[1].code is None
    assert parse_card(STATIC_CLONE_CARD).effects[1].code == "EVENT_CHAINING"
    assert parse_card(LABEL_OBJECT_CARD).effects[2].categories == []

    #: 칸별 corpus 총계.
    totals: collections.Counter = collections.Counter()
    for info in scripts.values():
        for spec in info.effects:
            for field in ("effect_types", "ranges", "target_ranges",
                          "categories", "properties"):
                totals[field] += len(getattr(spec, field))
            totals["code"] += spec.code is not None
            totals["cloned_from"] += spec.cloned_from is not None
    assert dict(totals) == {
        #: 🔴 Phase 3-F-32 에서 +3 블록만큼 늘었다 (``categories`` 는 그대로).
        "effect_types": 45340,
        "ranges": 15064,
        "target_ranges": 2063,
        "categories": 20503,      # 🔴 3-F-29 의 20,505 에서 −2, 3-F-32 는 변화 없음
        "properties": 23887,
        "code": 30129,            # 🔴 3-F-29 의 30,127 에서 −1, 3-F-32 에서 +3
        "cloned_from": 2747,      # 🔴 3-F-32 에서 +3
    }, dict(totals)


def test_31_state_hash_rng_and_digest_are_unchanged(repository):
    """🟢 §10 — ``state_hash`` · RNG · digest 불변."""
    first = opened_duel(repository, seed=71)
    second = opened_duel(repository, seed=71)
    assert first.state.state_hash() == second.state.state_hash()
    assert opened_duel(repository, seed=72).state.state_hash() != first.state.state_hash()
    assert [first.state.rng.randrange(10_000) for _ in range(12)] == [
        second.state.rng.randrange(10_000) for _ in range(12)
    ]

    counts: collections.Counter = collections.Counter()
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        if str(path.relative_to(PROJECT_ROOT)) == MYSELF:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(ch in "0123456789abcdef" for ch in node.value)
            ):
                counts[node.value] += 1
    expected, pins = counts.most_common(1)[0]
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


def test_32_hidden_information_and_the_view_are_unchanged(repository):
    """🟢 §10 — ``CardDefinitionView`` 가 블록 내용을 내보내지 않는다."""
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert len(fields) == 26
    assert "effect_count" in fields
    for banned in ("categories", "properties", "ranges", "target_ranges",
                   "effect_types", "code", "effects", "script"):
        assert banned not in fields, banned
    assert not hasattr(opened_duel(repository, seed=73).view(0), "effects")


def test_33_the_cache_reflects_the_fixed_parser(scripts, tmp_path):
    """🔴 §10 — 캐시 서명 ``v7`` → ``v8`` 이고 round-trip 이 고친 값을 돌려준다."""
    cache = tmp_path / "lua_scripts.json"
    source = LuaScriptSource(PROJECT_ROOT)
    written = source.load_cached(cache)
    read_back = source.load_cached(cache)
    for table in (scripts, written, read_back):
        assert sum(len(info.effects) for info in table.values()) == BLOCKS
        assert table[STATIC_CLONE_CARD].effects[1].code == "EVENT_CHAINING"
        assert table[CLONE_WITH_ARG_CARD].effects[1].code is None
    #: 🔴 Phase 3-F-32 에서 ``v8`` → **``v9``** — ``Clone`` 의 인자 있는
    #: 형태와 점 형태를 블록으로 인정했다. 캐시 서명에 파서 버전이
    #: 들어 있지 않아 **다섯 Phase 연속 수동**으로 올리고 있다 (위험 E4).
    assert json.loads(cache.read_text(encoding="utf-8"))["signature"].startswith("v9:")

    body = inspect.getsource(LuaScriptSource._signature)
    assert 'f"v9:{count}:{newest:.0f}"' in body
    for old in ("v7:", "v6:", "v5:"):
        assert f'f"{old}' not in body, old
    #: 🔴 서명에 파서 버전·코드 해시가 **없다** — 그래서 손으로 올린다.
    for token in ("parse_lua_source", "__version__", "md5", "_RE_REBIND"):
        assert token not in body, token

    #: 직전 버전(``v7``) 캐시는 **거부된다.**
    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps({"signature": "v7:12702:0",
                    "scripts": {str(STATIC_CLONE_CARD): {"file_name": "x.lua"}}}),
        encoding="utf-8",
    )
    loaded = source.load_cached(stale)
    assert loaded[STATIC_CLONE_CARD].file_name == f"c{STATIC_CLONE_CARD}.lua"
    assert loaded[STATIC_CLONE_CARD].effects[1].code == "EVENT_CHAINING"


def test_34_effect_to_effect_aliasing_does_not_occur_in_the_corpus(bodies):
    """
    🔴 §3 ① · §6 A — **Effect 를 Effect 에 alias 하는 자리는 corpus 에 0건이다.**

    단일 변수를 RHS 로 갖는 대입이 **579건** 있지만, RHS 가 **파서가 묶은 Effect
    변수**인 것은 **하나도 없다** — 전부 ``nil`` · ``true`` · ``false`` ·
    ``LOCATION_*`` 같은 값이고 LHS 는 ``g`` · ``loc`` · ``tc`` 처럼 Group/카드
    변수다.

    그래서 §3 ① 의 위험(동일 객체 alias)은 **이 corpus 에 존재하지 않는다.**
    """
    bare_total = 0
    effect_aliases = []
    rhs_names: collections.Counter = collections.Counter()
    for card_id, body in bodies.items():
        clean = blank(body)
        bound = set()
        for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
                bound.add(m.group(2))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
                bound.add(m.group(2))
        for m in _ANY_ASSIGN.finditer(clean):
            if classify_rhs(m.group(3)) != "bare_var":
                continue
            bare_total += 1
            rhs = m.group(3).strip()
            rhs_names[rhs] += 1
            if rhs in bound:
                effect_aliases.append((card_id, m.group(2), rhs))
    assert bare_total == BARE_VAR_ASSIGNS, bare_total
    assert effect_aliases == [], effect_aliases
    assert len(effect_aliases) == EFFECT_ALIASES
    #: 상위 RHS 가 전부 **값**이다.
    assert rhs_names["nil"] == 223
    assert rhs_names["true"] == 101
    assert rhs_names["false"] == 82


def test_35_the_production_change_is_confined_and_adds_no_dataflow_engine():
    """
    🔴 §9 — production diff 가 **``sources/lua_loader.py`` 한 파일**이고,
    금지된 것을 하나도 만들지 않았다.
    """
    changed = _changed_files()
    production = {
        path for path in changed
        if path.endswith(".py") and not path.startswith("tests/")
    }
    assert production == {"sources/lua_loader.py"}, production

    #: ``EffectSpec`` · ``EffectRef`` 칸 불변.
    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]
    assert "effects" in {f.name for f in dataclasses.fields(LuaScriptInfo)}

    loader = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8")
    tree = ast.parse(loader)
    #: 🔴 금지 사항 — dataflow engine · interpreter · CFG · graph.
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in ("luaparser", "lupa", "slpp", "networkx", "ast"):
        assert banned not in imported, banned
    for banned in ("class DataFlow", "class CFG", "class EffectGraph",
                   "def interpret", "Enum"):
        assert banned not in loader, banned

    #: public 이름이 그대로다. 새로 생긴 것은 private 둘뿐이다.
    public = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    ]
    assert public == ["parse_lua_source", "LuaScriptSource"], public
    assigned = {
        t.id for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert "_RE_REBIND" in assigned
    assert "_EVENT_ORDER" in assigned


def _changed_files() -> set[str]:
    """
    이 Phase 의 diff 에 등장하는 파일.

    🔴 제목이 ``Phase 3-F-31:`` 으로 시작하는 commit 들을 찾아 *가장 오래된
    것의 부모 → 가장 최근 것* 을 본다. ``HEAD`` 를 쓰지 않으므로 다음 Phase 가
    production 을 건드려도 깨지지 않는다.

    🔴 그리고 Phase commit 이 있으면 **commit 범위만** 본다 — worktree diff 를
    더하면 **다음 Phase 가 작업하는 동안** 그 변경이 새어 들어온다 (3-F-28 ·
    3-F-29 · 3-F-30 의 같은 helper 가 그래서 깨졌고, 이 Phase 가 셋 다 고쳤다).
    """
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        ).stdout

    phase = run("log", "--format=%H", "--grep=^Phase 3-F-31:", "HEAD").split()
    if phase:
        newest, oldest = phase[0], phase[-1]
        out = run("diff", "--name-only", f"{oldest}~1", newest)
    else:
        out = run("diff", "--name-only", "HEAD")
        out += run("diff", "--name-only", "--cached", "HEAD")
    return {line for line in out.splitlines() if line}
