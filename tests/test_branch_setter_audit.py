"""
Phase 3-F-30 — Lua 분기 내부 설정자(``SetCategory`` / ``SetTargetRange`` /
``SetRange`` / ``SetProperty``) 의 분기 의미 감사.

판정: **D. REPRESENTATION_LIMITATION**

🔴 파서는 분기를 **아예 보지 않는다** — 설계상 그렇다
------------------------------------------------------
``sources/lua_loader.py`` 에는 Lua AST 가 **없다.** 블록 탐지와 설정자 추출이
전부 정규식(``_RE_CREATE_EFFECT`` · ``_RE_CLONE_EFFECT`` · ``_RE_SETTER``)이고,
이벤트를 **byte offset 으로 정렬해 순서대로 재생**한다. ``if`` · ``elseif`` ·
``else`` 는 토큰으로도 보지 않는다 (``test_19``).

그래서 아래 **다섯 가지 서로 다른 Lua** 가 **완전히 같은 ``EffectSpec``** 을
만든다 (``test_18``) — ``categories == ['DRAW', 'DESTROY']``::

    A  if c then e:SetCategory(DRAW) else e:SetCategory(DESTROY) end  -- 하나만 실행
    C  if c then e:SetCategory(DRAW)      e:SetCategory(DESTROY) end  -- 둘 다 실행
    E  if c then e:SetCategory(DRAW) end  e:SetCategory(DESTROY)      -- 뒤는 항상
    F  e:SetCategory(DRAW)                e:SetCategory(DESTROY)      -- 순차
    G  e:SetCategory(DRAW+DESTROY)                                    -- 한 호출

🔴 그러나 **"값을 잘못 만든다" 와 "의미를 표현할 수 없다" 는 다르다**
---------------------------------------------------------------------
지시서 §12 가 요구한 구분이고, corpus 전수 측정이 그 둘을 갈랐다.

``if`` 분기 **안**에 있는 설정자 호출은 **2,702건**이다
(``Category`` 91 · ``TargetRange`` 274 · ``Range`` 381 · ``Property`` 1,956).
그런데 그중 **2,700건은 그 블록이 같은 분기 안에서 생성된다** — 즉 블록 자체가
그 분기에서만 존재하므로, 설정자는 **그 블록에 대해 무조건**이다. 파서가 옳다.

**조건부 수정**(블록은 분기 밖에서 생성되고 설정자만 분기 안)은 corpus 전체에
**2건**뿐이고, **둘 다 읽을 수 있는 상수를 하나도 내지 않는다**
(``SetTargetRange(1,0)`` · ``(0,1)`` — 플레이어 대상 형식이라 ``LOCATION_*`` 이
없다). 그래서 **실제로 잃는 값이 없다** (``test_21``).

배타 분기에서 같은 설정자가 2회 이상 불리는 블록도 **2개**뿐이다 (``test_22``).

* ``c62784717`` ``SetTargetRange`` — 두 값 모두 상수를 못 읽어 **합쳐도 같다.**
* ``c52445243`` ``SetCategory`` — 유일하게 서로 다른 값이 합쳐지는데, 🔴 **그
  블록은 애초에 그 설정자의 블록이 아니다** (아래 참고).

🔴 별개 발견 — **가려진 재바인딩으로 인한 귀속 오류 (5건 / 3장)**
------------------------------------------------------------------
``local e1 = e:GetLabelObject()`` 처럼 **``CreateEffect`` 도 ``Clone`` 도 아닌
RHS** 로 기존 블록 변수를 다시 묶는 자리가 **25곳** 있다. 파서는 그것을
재바인딩으로 보지 않으므로, 그 뒤의 ``e1:SetX`` 가 **직전 ``create`` 블록**에
붙는다. 그렇게 잘못 귀속되는 설정자 호출은 **5건 / 3장**이다 (``test_23``).

* ``c52445243`` ``SetCategory`` 3건 — ``e:GetLabelObject()``
* ``c44887817`` ``SetCode`` 1건 — ``local e2=e1:Clone(e1)`` (``Clone()`` 의 빈
  괄호를 요구하는 정규식이 못 잡는다)
* ``c4997565`` ``SetCode`` 1건 — ``local e2=Effect.Clone(e1)`` (다른 API 형태)

이것은 **분기 문제가 아니라 3-F-28 의 블록 탐지 계열**이고, 위 ``c52445243``
의 "분기 병합" 도 실은 이 귀속 오류 위에서 일어난다.

🔴 production 영향 — **없다. 측정으로 확인했다**
------------------------------------------------
* ``engine/`` · ``agent/`` 는 네 칸을 **한 번도 읽지 않는다.** ``engine/`` 의
  ``.code`` 접근 62건은 전부 ``verdict`` · ``result`` · ``requirement`` 등
  **다른 것의 ``code``** 다 (``test_24``).
* 유일한 소비자는 ``analysis/effect_analyzer.py`` 와 ``app/main.py`` (CLI 표시),
  그리고 ``core/card_search.py`` 다.
* **검색 필터는 귀속에 영향받지 않는다** — ``Card.has_effect_category`` 가
  블록별 ``categories`` **또는** 파일 전체 ``LuaScriptInfo.categories`` 를 보고,
  corpus 전체에서 "블록에만 있고 파일 전체에는 없는 category" 가 **0건**이다
  (``test_25``).
* **검색 순위**(``card_search.py`` 의 ``sum(1 for e in card.effects if ...)``)만
  블록 수에 민감한데, 귀속이 틀린 3장 **전부** 각 category 를 **정확히 한
  블록**이 갖는다 — 올바른 귀속에서도 같다. 따라서 **점수도 바뀌지 않는다**
  (``test_26``).

그래서 지시서 §8 의 다섯 조건 중 **③ production downstream 실제 영향**이
충족되지 않는다. **production 을 수정하지 않았다** (``test_27``).
"""

import ast
import bisect
import collections
import dataclasses
import hashlib
import inspect
import itertools
import pathlib
import re
import subprocess

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from core.card_model import EffectSpec, LuaScriptInfo
from engine.duel import Duel
from engine.effect.library import EFFECT_LIBRARY
from engine.game_state_view import CardDefinitionView
from engine.ids import EffectRef, effect_refs
import sources.lua_loader as lua_loader
from sources.lua_loader import LuaScriptSource, parse_lua_source

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MYSELF = "tests/test_branch_setter_audit.py"

# ======================================================================
# 측정값 — 전부 이 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

SCRIPTS = 12702
BLOCKS = 34684                     # 🔴 Phase 3-F-32 에서 +3 — ``Clone`` 의 인자 있는 형태
# (``e1:Clone(e1)`` · ``e2:Clone(c)``)와 점 형태 (``Effect.Clone(e1)``)를
# 블록으로 인정했다. 세 스크립트에 효과 블록이 하나씩 생겼다.

#: 설정자 호출 총수 (블록 주석 제거 후, 묶인 블록에 귀속된 것만).
#: 🔴 Phase 3-F-32 에서 ``TargetRange`` 3,417 → 3,418 · ``Property``
#: 16,430 → 16,431. ``c56410769`` 의 ``e3`` 가 블록이 되어 그 두 설정자가
#: **버려지지 않고 귀속된다** (``SetCode`` 도 하나 늘지만 이 표에 없다).
CALLS = {"Category": 14254, "TargetRange": 3418, "Range": 13695, "Property": 16431}

#: 그중 ``if`` 분기 **안**에 있는 호출.
IN_IF = {"Category": 91, "TargetRange": 274, "Range": 381, "Property": 1956}

#: 🔴 그 블록이 **같은 분기 안에서 생성**된 경우 (설정자가 그 블록에 무조건).
BLOCK_IN_SAME_BRANCH = {"Category": 91, "TargetRange": 272, "Range": 381, "Property": 1956}

#: 🔴 **조건부 수정** — 블록은 분기 밖, 설정자만 분기 안.
CONDITIONAL_MODIFICATION = {"Category": 0, "TargetRange": 2, "Range": 0, "Property": 0}
#: 그중 상수를 **읽을 수 있는** 것. 전부 0 이므로 실제로 잃는 값이 없다.
CONDITIONAL_MODIFICATION_READABLE = {
    "Category": 0, "TargetRange": 0, "Range": 0, "Property": 0,
}

#: 같은 블록·같은 설정자가 2회 이상 불리는 블록 수.
BLOCKS_WITH_TWO_PLUS = {"Category": 10, "TargetRange": 1, "Range": 0, "Property": 7}
#: 그중 **배타 분기**에 걸쳐 있는 것.
EXCLUSIVE_BRANCH_BLOCKS = {"Category": 1, "TargetRange": 1, "Range": 0, "Property": 0}

#: 🔴 기존 블록 변수를 가리는 ``local`` 재바인딩과, 그로 인한 귀속 오류.
SHADOWING_REBINDS = 25
MISATTRIBUTED_SETTERS = 5
MISATTRIBUTED_BY_SETTER = {"Category": 3, "Code": 2}

#: 측정으로 확인한 실제 카드.
BRANCH_CATEGORY = 52445243         # if/elseif 안의 SetCategory 3회 + 귀속 오류
BRANCH_TARGET_RANGE = 62784717     # if/else 안의 SetTargetRange 2회 (둘 다 읽히지 않음)
CLONE_WITH_ARG = 44887817          # local e2=e1:Clone(e1) — 정규식이 못 잡는다
STATIC_CLONE = 4997565             # local e2=Effect.Clone(e1) — 다른 API 형태
CLONE_REPLACE = 324483             # 3-F-27/29 의 카드 — IGNITION -> Clone -> QUICK_O

#: digest 용 덱 — 3-F-24 이후 모든 Phase 가 같은 것을 쓴다.
LUSTER_DRAGON = 11091375
POT_OF_GREED = 55144522
GENEROUS_REWARD = 5915629
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4

FIELD_OF = {"Category": "categories", "TargetRange": "target_ranges",
            "Range": "ranges", "Property": "properties"}
REGEX_OF = {"Category": lua_loader._RE_CATEGORY, "TargetRange": lua_loader._RE_LOCATION,
            "Range": lua_loader._RE_LOCATION, "Property": lua_loader._RE_EFFECT_FLAG}


# ======================================================================
# 측정 도구 — Lua 블록 구조를 **테스트 안에서만** 추적한다
# ======================================================================
#
# 🔴 production 에는 Lua AST 가 없다 (``test_19`` 가 그 사실을 고정한다).
# 이 감사를 하려면 분기를 볼 수 있어야 하므로 여기서 토큰 단위로 추적한다.
# **production 을 바꾸지 않는다** — 측정 도구일 뿐이다.

_LONG_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_LONG_STRING = re.compile(r"\[(=*)\[.*?\]\1\]", re.S)
_DQ = re.compile(r'"(?:\\.|[^"\\\n])*"')
_SQ = re.compile(r"'(?:\\.|[^'\\\n])*'")
_BLOCK_KEYWORD = re.compile(
    r"\b(if|then|elseif|else|end|for|while|do|function|repeat|until)\b"
)


def _blank(text: str) -> str:
    """주석·문자열을 **같은 길이의 공백**으로 바꾼다 (offset 보존)."""
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


def branch_path_at(text: str):
    """
    ``위치 -> 분기 경로`` 함수.

    경로는 ``(블록 종류, 그 블록 안에서 몇 번째 분기)`` 의 튜플 열이다.
    ``for``/``while`` 뒤의 ``do`` 는 블록을 새로 열지 않는다.
    """
    body = _blank(text)
    marks: list[tuple[int, tuple]] = []
    stack: list[list] = []
    pending_do = 0
    for m in _BLOCK_KEYWORD.finditer(body):
        word = m.group(1)
        if word == "if":
            stack.append(["if", 0])
        elif word in ("elseif", "else"):
            if stack and stack[-1][0] == "if":
                stack[-1][1] += 1
        elif word in ("for", "while"):
            stack.append([word, 0])
            pending_do += 1
        elif word == "do":
            if pending_do:
                pending_do -= 1
            else:
                stack.append(["do", 0])
        elif word in ("function", "repeat"):
            stack.append([word, 0])
        elif word in ("end", "until"):
            if stack:
                stack.pop()
        marks.append((m.start(), tuple(tuple(f) for f in stack)))

    starts = [p for p, _ in marks]

    def at(position: int) -> tuple:
        index = bisect.bisect_right(starts, position) - 1
        return marks[index][1] if index >= 0 else ()

    return at


def exclusive(a: tuple, b: tuple) -> bool:
    """두 경로가 **서로 배타적인 분기**에 있는가 (둘 중 하나만 실행)."""
    for left, right in zip(a, b):
        if left != right:
            return left[0] == "if" and right[0] == "if"
    return False


def strictly_nested(a: tuple, b: tuple) -> bool:
    """한쪽이 다른 쪽의 **엄격한 접두사** 인가 (분기 밖 + 분기 안)."""
    if len(a) == len(b):
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return tuple(long_[: len(short)]) == tuple(short)


def walk(body: str, setter: str):
    """
    production 과 **같은 이벤트 흐름**으로 블록을 만들고, 각 블록의 그 설정자
    호출들을 ``(플래그, 인자, 분기 경로)`` 로 모은다.

    production 의 정규식·주석 제거·``_is_card_effect`` 를 그대로 쓴다 —
    3-F-28 에서 그룹 번호를 따로 가정했다가 조용히 깨진 전례가 있다.
    """
    at = branch_path_at(body)
    regex = REGEX_OF[setter]
    events = []
    for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
        if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
            events.append((m.start(), "create", m.group(2), None))
    for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
        if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
            events.append((m.start(), "clone", m.group(2), lua_loader._clone_source(m)))
    for m in lua_loader._RE_SETTER.finditer(body):
        if m.group(2) == setter:
            events.append((m.start(), "set", m.group(1), m.end() - 1))
    events.sort(key=lambda e: e[0])

    bindings: dict[str, dict] = {}
    blocks: list[dict] = []
    for position, kind, var, extra in events:
        if kind in ("create", "clone"):
            block = {"index": var, "parent": extra, "ordinal": len(blocks),
                     "create_path": at(position), "calls": []}
            bindings[var] = block
            blocks.append(block)
        else:
            block = bindings.get(var)
            if block is None:
                continue
            args = lua_loader._extract_call_args(body, extra).strip()
            block["calls"].append({
                "flags": tuple(lua_loader._strip_prefix(regex.findall(args))),
                "args": args,
                "path": at(position),
            })
    return blocks


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
    """``card_id -> 블록 주석을 지운 본문`` 전수."""
    out = {}
    for card_id, path in LuaScriptSource(PROJECT_ROOT).iter_script_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        out[card_id] = lua_loader._RE_BLOCK_COMMENT.sub("", text)
    return out


# ======================================================================
# A. §2 · §11-1~9 — 최소 사례
# ======================================================================


def test_01_a_single_setter_is_recorded_once():
    """🟢 §11-1 — 설정자 하나."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        c:RegisterEffect(e1)
    """)
    assert [s.categories for s in specs] == [["DRAW"]]


def test_02_the_same_setter_repeated_with_the_same_value():
    """🟢 §11-2 — 같은 값 반복. 중복이 제거되어 하나로 남는다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        e1:SetCategory(CATEGORY_DRAW)
        c:RegisterEffect(e1)
    """)
    assert specs[0].categories == ["DRAW"]


def test_03_the_same_setter_repeated_with_different_values_accumulates():
    """
    🔴 §11-3 — 다른 값 반복은 **더해진다.**

    3-F-29 가 "``Clone`` 이 물려준 값은 첫 호출이 덮어쓰고, 두 번째 이후는
    더한다" 로 고정한 그 동작이다. 이 Phase 는 그것을 바꾸지 않았다.
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        e1:SetCategory(CATEGORY_DESTROY)
        c:RegisterEffect(e1)
    """)
    assert specs[0].categories == ["DRAW", "DESTROY"]


def test_04_if_else_with_different_values_is_merged():
    """
    🔴 §2 A · §11-4 — ``if``/``else`` 의 **서로 배타적인** 두 값이 합쳐진다.

    Lua 는 둘 중 **하나만** 실행하는데 파서는 둘 다 적는다. 이것이 이 Phase 의
    핵심 현상이고, ``EffectSpec`` 에 "조건" 칸이 없어서 **표현할 수 없다.**
    """
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if cond then
            e1:SetCategory(CATEGORY_DRAW)
        else
            e1:SetCategory(CATEGORY_DESTROY)
        end
    """)
    assert specs[0].categories == ["DRAW", "DESTROY"]


def test_05_if_else_with_the_same_value_is_harmless():
    """🟢 §2 D · §11-5 — 양쪽이 같은 값이면 합쳐도 **결과가 옳다.**"""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if cond then
            e1:SetCategory(CATEGORY_DRAW)
        else
            e1:SetCategory(CATEGORY_DRAW)
        end
    """)
    assert specs[0].categories == ["DRAW"]


def test_06_two_calls_inside_one_branch():
    """🟢 §2 C · §11-6 — 한 분기 안의 2회는 **실제로 둘 다 실행된다.**"""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if cond then
            e1:SetCategory(CATEGORY_DRAW)
            e1:SetCategory(CATEGORY_DESTROY)
        end
    """)
    assert specs[0].categories == ["DRAW", "DESTROY"]


def test_07_outside_plus_inside_a_branch():
    """🔴 §2 E · §11-7 — 분기 밖 하나 + 분기 안 하나."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if cond then
            e1:SetCategory(CATEGORY_DRAW)
        end
        e1:SetCategory(CATEGORY_DESTROY)
    """)
    #: ``DESTROY`` 는 **항상**, ``DRAW`` 는 **조건부**인데 구분이 없다.
    assert specs[0].categories == ["DRAW", "DESTROY"]


def test_08_nested_if():
    """🔴 §11-8 — 중첩 ``if`` 도 같다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if a then
            if b then
                e1:SetCategory(CATEGORY_DRAW)
            else
                e1:SetCategory(CATEGORY_DESTROY)
            end
        end
    """)
    assert specs[0].categories == ["DRAW", "DESTROY"]


def test_09_elseif_with_three_branches():
    """🔴 §11-9 — ``elseif`` 3분기가 **셋 다** 합쳐진다."""
    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if a then
            e1:SetCategory(CATEGORY_DRAW)
        elseif b then
            e1:SetCategory(CATEGORY_DESTROY)
        else
            e1:SetCategory(CATEGORY_TOHAND)
        end
    """)
    assert specs[0].categories == ["DRAW", "DESTROY", "TOHAND"]


@pytest.mark.parametrize(
    "setter,field,values,expected",
    [
        ("SetCategory", "categories",
         ("CATEGORY_DRAW", "CATEGORY_DESTROY"), ["DRAW", "DESTROY"]),
        ("SetTargetRange", "target_ranges",
         ("LOCATION_MZONE,0", "LOCATION_GRAVE,0"), ["MZONE", "GRAVE"]),
        ("SetRange", "ranges",
         ("LOCATION_MZONE", "LOCATION_SZONE"), ["MZONE", "SZONE"]),
        ("SetProperty", "properties",
         ("EFFECT_FLAG_DELAY", "EFFECT_FLAG_CARD_TARGET"), ["DELAY", "CARD_TARGET"]),
    ],
)
def test_10_13_all_four_setters_behave_identically(setter, field, values, expected):
    """
    🔴 §11-10~13 — 네 설정자 **전부** 같다. 분기를 보지 않는다.

    ``SetCategory`` 와 ``SetTargetRange`` 만의 문제가 아니라 **설정자 처리
    방식 전체**의 성질이다.
    """
    specs = blocks_of(f"""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if cond then
            e1:{setter}({values[0]})
        else
            e1:{setter}({values[1]})
        end
    """)
    assert getattr(specs[0], field) == expected


def test_14_the_real_branch_category_card():
    """
    🔴 §2 · §9 — ``c52445243`` (트라이에지 마스터) 실제 사례.

    ``s.matcheck`` 안에서 ``if #g>2`` / ``elseif #g==2`` 의 **배타 분기**가
    각각 다른 category 를 적는다. 파서는 셋을 합친다.

    🔴 그런데 **그 블록은 애초에 그 설정자의 블록이 아니다** — ``s.matcheck``
    의 ``e1`` 은 ``local e1=e:GetLabelObject()`` 이고 ``initial_effect`` 의
    ``e1``(ordinal 0)을 가리킨다. 파서는 그 재바인딩을 보지 않으므로
    ``s.effop`` 에서 생성된 **ordinal 2** 에 붙인다 (``test_23``).
    """
    text = script_text(BRANCH_CATEGORY)
    #: 원문의 모양을 못 박는다.
    assert "local e1=e:GetLabelObject()" in text
    assert "e1:SetCategory(CATEGORY_DESTROY+CATEGORY_DRAW)" in text
    assert "if lv==1 then e1:SetCategory(CATEGORY_DESTROY)" in text
    assert "elseif lv==2 then e1:SetCategory(CATEGORY_DRAW) end" in text

    specs = parse_card(BRANCH_CATEGORY).effects
    assert len(specs) == 3
    #: 🔴 **Phase 3-F-31 이 그 귀속 오류를 고쳤다.** 이 docstring 이 적어 둔
    #: "그 블록은 애초에 그 설정자의 블록이 아니다" 가 바로 그것이고,
    #: 3-F-31 이 ``local e1=e:GetLabelObject()`` 에서 바인딩을 풀도록 바꿨다.
    #: 이제 **어느 블록에도** 그 category 가 붙지 않는다 — 분기 병합이
    #: 사라진 것이 아니라 **그 설정자가 더 이상 엉뚱한 블록에 가지 않는다.**
    assert specs[2].categories == []
    assert specs[0].categories == []
    assert specs[0].code == "EVENT_SPSUMMON_SUCCESS"

    #: 세 호출이 서로 배타적인 분기에 있다는 것도 측정으로 확인한다.
    body = lua_loader._RE_BLOCK_COMMENT.sub("", text)
    block = next(b for b in walk(body, "Category") if len(b["calls"]) >= 2)
    paths = [call["path"] for call in block["calls"]]
    assert len(paths) == 3
    assert all(exclusive(x, y) for x, y in itertools.combinations(paths, 2))


def test_15_the_real_branch_target_range_card():
    """
    🔴 §2 B · §9 — ``c62784717`` 실제 사례.

    ``if``/``else`` 가 ``SetTargetRange(1,0)`` / ``(0,1)`` 을 적는다. 둘 다
    **플레이어 대상 형식**이라 ``LOCATION_*`` 이 없고, 파서는 **아무 상수도
    읽지 못한다.** 그래서 합쳐도 결과가 같고 **잃는 값이 없다.**
    """
    text = script_text(BRANCH_TARGET_RANGE)
    assert "e1:SetTargetRange(1,0)" in text
    assert "e1:SetTargetRange(0,1)" in text

    body = lua_loader._RE_BLOCK_COMMENT.sub("", text)
    block = next(b for b in walk(body, "TargetRange") if len(b["calls"]) >= 2)
    assert len(block["calls"]) == 2
    #: 배타 분기이고,
    assert exclusive(block["calls"][0]["path"], block["calls"][1]["path"])
    #: 🔴 두 호출 모두 읽히는 상수가 **0개**다.
    assert all(call["flags"] == () for call in block["calls"])
    #: 그래서 그 블록의 ``target_ranges`` 는 비어 있다.
    assert parse_card(BRANCH_TARGET_RANGE).effects[block["ordinal"]].target_ranges == []


# ======================================================================
# B. §3 · §4 · §5 — 분기 vs 순차 vs 누적 · parser 경로 · 표현력
# ======================================================================


def test_16_parsing_is_stable_and_deterministic(bodies):
    """🟢 §11-16 — 같은 입력을 두 번 파싱하면 **완전히 같다**."""
    sample = sorted(bodies)[:300] + [
        BRANCH_CATEGORY, BRANCH_TARGET_RANGE, CLONE_WITH_ARG, STATIC_CLONE,
    ]
    for card_id in sample:
        body = bodies[card_id]
        first = parse_lua_source(card_id, f"c{card_id}.lua", body)
        second = parse_lua_source(card_id, f"c{card_id}.lua", body)
        assert [dataclasses.asdict(s) for s in first.effects] == [
            dataclasses.asdict(s) for s in second.effects
        ], card_id


def test_17_the_effect_spec_contract_is_unchanged():
    """🟢 §11-17 — ``EffectSpec`` 의 칸이 그대로다. 이 Phase 는 모델을 안 바꿨다."""
    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]
    #: 🔴 "조건" 을 담을 칸이 **하나도 없다** — 그것이 §5 의 결론이다.
    names = {f.name for f in dataclasses.fields(EffectSpec)}
    for banned in ("condition", "conditions", "branch", "branches", "when", "guard"):
        assert banned not in names, banned


def test_18_five_different_lua_programs_produce_one_identical_spec():
    """
    🔴 §3 · §5 — **이 Phase 의 핵심 증거.**

    분기 · 분기 내 순차 · 분기 밖+안 · 순차 · 한 호출 OR — **다섯 가지 서로
    다른 Lua 의미**가 **완전히 같은 ``EffectSpec``** 을 만든다. 파서가 셋을
    구분하지 못한다는 것을 "예상" 이 아니라 **동등성**으로 못 박는다.
    """
    forms = {
        "A 배타 분기": """
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            if cond then e1:SetCategory(CATEGORY_DRAW)
            else e1:SetCategory(CATEGORY_DESTROY) end
        """,
        "C 한 분기 안 2회": """
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            if cond then
                e1:SetCategory(CATEGORY_DRAW)
                e1:SetCategory(CATEGORY_DESTROY)
            end
        """,
        "E 분기 밖 + 분기 안": """
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            if cond then e1:SetCategory(CATEGORY_DRAW) end
            e1:SetCategory(CATEGORY_DESTROY)
        """,
        "F 순차": """
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            e1:SetCategory(CATEGORY_DRAW)
            e1:SetCategory(CATEGORY_DESTROY)
        """,
        "G 한 호출 OR": """
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            e1:SetCategory(CATEGORY_DRAW+CATEGORY_DESTROY)
        """,
    }
    produced = {
        name: [dataclasses.asdict(s) for s in blocks_of(src)]
        for name, src in forms.items()
    }
    reference = produced["A 배타 분기"]
    for name, got in produced.items():
        assert got == reference, (name, got, reference)
    assert reference[0]["categories"] == ["DRAW", "DESTROY"]

    #: 🔴 그러나 **측정 도구는 셋을 구분한다** — 정보가 Lua 원문에는 있고
    #: ``EffectSpec`` 에만 없다는 뜻이다.
    kinds = {}
    for name, src in forms.items():
        body = inspect.cleandoc(src)
        block = walk(body, "Category")[0]
        paths = [call["path"] for call in block["calls"]]
        if len(paths) < 2:
            kinds[name] = "한 호출"
        elif any(exclusive(x, y) for x, y in itertools.combinations(paths, 2)):
            kinds[name] = "배타 분기"
        elif any(strictly_nested(x, y) for x, y in itertools.combinations(paths, 2)):
            kinds[name] = "분기 밖 + 분기 안"
        else:
            kinds[name] = "같은 경로 순차"
    assert kinds == {
        "A 배타 분기": "배타 분기",
        "C 한 분기 안 2회": "같은 경로 순차",
        "E 분기 밖 + 분기 안": "분기 밖 + 분기 안",
        "F 순차": "같은 경로 순차",
        "G 한 호출 OR": "한 호출",
    }, kinds


def test_19_production_has_no_lua_ast_at_all():
    """
    🔴 §4 — 파서가 분기를 보지 **않는다는 것**을 코드로 고정한다.

    블록 탐지와 설정자 추출이 전부 정규식이고, 이벤트를 **byte offset** 으로
    정렬해 재생한다. Lua 의 ``if``/``elseif``/``else`` 를 토큰으로도 보지 않는다.
    """
    loader = (PROJECT_ROOT / "sources" / "lua_loader.py").read_text(encoding="utf-8")
    tree = ast.parse(loader)

    #: Lua 파서 라이브러리를 import 하지 않는다.
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in ("luaparser", "lupa", "slpp", "ast"):
        assert banned not in imported, banned

    #: 🔴 모듈에 정의된 정규식 이름만으로 설정자를 찾는다 — 분기용 정규식이 없다.
    assigned = {
        t.id for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert "_RE_SETTER" in assigned
    for banned in ("_RE_IF", "_RE_BRANCH", "_RE_ELSE", "_RE_BLOCK_KEYWORD"):
        assert banned not in assigned, banned

    #: 이벤트 정렬 기준이 **위치(byte offset)** 다.
    #: 🔴 Phase 3-F-31 이 같은 위치의 우선순위를 못 박으려고 두 번째 키를
    #: 넣었다 (``create``/``clone`` → ``rebind`` → ``set``). **첫 키는 여전히
    #: byte offset** 이므로 이 테스트의 주장은 그대로다.
    body = inspect.getsource(lua_loader.parse_lua_source)
    assert "events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))" in body
    assert "e[0]" in body
    #: 설정자 분기는 ``setter ==`` 비교뿐이고 분기 조건을 보지 않는다.
    assert 'setter == "Type"' in body
    for banned in ("elseif", "branch_path", "exclusive("):
        assert banned not in body, banned


def test_20_what_effect_spec_can_and_cannot_represent():
    """
    🔴 §5 — 표현력을 **항목별로** 고정한다.

    "합쳐졌으니 의미도 합쳐졌다" 고 가정하지 않는다 — 합쳐진 것과 표현할 수
    없는 것을 나눠 적는다.
    """
    #: REPRESENTABLE — 한 effect 에 category 여러 개.
    assert blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW+CATEGORY_DESTROY)
        c:RegisterEffect(e1)
    """)[0].categories == ["DRAW", "DESTROY"]

    #: NOT_REPRESENTABLE — 조건 A 면 X, 조건 B 면 Y.
    #: 두 프로그램이 **구분되지 않는다**는 것으로 증명한다.
    conditional = blocks_of("""
        local e1=Effect.CreateEffect(c)
        c:RegisterEffect(e1)
        if a then e1:SetCategory(CATEGORY_DRAW)
        else e1:SetCategory(CATEGORY_DESTROY) end
    """)
    unconditional = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW+CATEGORY_DESTROY)
        c:RegisterEffect(e1)
    """)
    assert [dataclasses.asdict(s) for s in conditional] == [
        dataclasses.asdict(s) for s in unconditional
    ]

    #: NOT_REPRESENTABLE — 순차 setter 의 **순서/횟수**. 결과만 남는다.
    once = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetProperty(EFFECT_FLAG_DELAY+EFFECT_FLAG_CARD_TARGET)
        c:RegisterEffect(e1)
    """)
    twice = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetProperty(EFFECT_FLAG_DELAY)
        e1:SetProperty(EFFECT_FLAG_CARD_TARGET)
        c:RegisterEffect(e1)
    """)
    assert once[0].properties == twice[0].properties == ["DELAY", "CARD_TARGET"]

    #: UNKNOWN — 파서가 상수를 읽지 못하는 인자. 3-F-29 가 "단정하지 않는다" 로
    #: 고정했다. 분기와 무관하게 **빈 값으로 만들지 않는다.**
    unreadable = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetTargetRange(LOCATION_MZONE,0)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        if cond then e2:SetTargetRange(0,1) end
        c:RegisterEffect(e2)
    """)
    assert unreadable[1].target_ranges == ["MZONE"]


# ======================================================================
# C. §6 · §7 — corpus 전수 측정
# ======================================================================


def test_21_corpus_in_branch_calls_are_almost_all_in_branch_created_blocks(bodies):
    """
    🔴 §6 · §7 A·B · **이 Phase 의 결정적 측정.**

    ``if`` 분기 안에 있는 설정자 호출은 **2,702건**이다. 그런데 그중
    **2,700건은 그 블록이 같은 분기 안에서 생성된다** — 블록 자체가 그 분기에만
    존재하므로 설정자는 **그 블록에 대해 무조건**이고 파서가 옳다.

    **조건부 수정**(블록은 분기 밖, 설정자만 분기 안)은 **2건**뿐이고,
    **둘 다 읽을 수 있는 상수를 하나도 내지 않는다.** 그래서 이 표현 한계로
    **실제로 잃는 값이 0** 이다.
    """
    calls = collections.Counter()
    in_if = collections.Counter()
    same_branch = collections.Counter()
    cond_mod = collections.Counter()
    cond_mod_readable = collections.Counter()
    for card_id, body in bodies.items():
        for setter in FIELD_OF:
            for block in walk(body, setter):
                for call in block["calls"]:
                    calls[setter] += 1
                    if not any(frame[0] == "if" for frame in call["path"]):
                        continue
                    in_if[setter] += 1
                    create, use = block["create_path"], call["path"]
                    if strictly_nested(create, use) and len(create) < len(use):
                        cond_mod[setter] += 1
                        if call["flags"]:
                            cond_mod_readable[setter] += 1
                    else:
                        same_branch[setter] += 1

    assert dict(calls) == CALLS, dict(calls)
    assert dict(in_if) == IN_IF, dict(in_if)
    assert {k: same_branch[k] for k in FIELD_OF} == BLOCK_IN_SAME_BRANCH
    assert {k: cond_mod[k] for k in FIELD_OF} == CONDITIONAL_MODIFICATION
    #: 🔴 조건부 수정 중 상수를 읽는 것이 **하나도 없다**.
    assert {k: cond_mod_readable[k] for k in FIELD_OF} == CONDITIONAL_MODIFICATION_READABLE
    assert sum(cond_mod_readable.values()) == 0
    assert sum(in_if.values()) == 2702
    assert sum(same_branch.values()) == 2700
    assert sum(cond_mod.values()) == 2


def test_22_only_two_blocks_merge_exclusive_branches(bodies):
    """
    🔴 §6 · §7 B — 배타 분기에 걸쳐 같은 설정자가 2회 이상 불리는 블록은
    corpus 전체에 **2개**다.

    * ``c62784717`` ``SetTargetRange`` — 두 값 모두 상수를 못 읽어 **같다.**
    * ``c52445243`` ``SetCategory`` — 유일하게 다른 값이 합쳐지는데, 그 블록은
      애초에 그 설정자의 블록이 아니다 (``test_23``).
    """
    two_plus = collections.Counter()
    exclusive_blocks = collections.Counter()
    exclusive_distinct = []
    for card_id, body in bodies.items():
        for setter in FIELD_OF:
            for block in walk(body, setter):
                if len(block["calls"]) < 2:
                    continue
                two_plus[setter] += 1
                paths = [call["path"] for call in block["calls"]]
                if not any(exclusive(x, y) for x, y in itertools.combinations(paths, 2)):
                    continue
                exclusive_blocks[setter] += 1
                if len({call["flags"] for call in block["calls"]}) > 1:
                    exclusive_distinct.append(
                        (card_id, setter, block["ordinal"],
                         [list(call["flags"]) for call in block["calls"]])
                    )

    assert {k: two_plus[k] for k in FIELD_OF} == BLOCKS_WITH_TWO_PLUS
    assert {k: exclusive_blocks[k] for k in FIELD_OF} == EXCLUSIVE_BRANCH_BLOCKS
    assert sum(exclusive_blocks.values()) == 2

    #: 🔴 값이 **서로 다른** 배타 병합은 **단 1건**이고 그 카드를 고정한다.
    assert len(exclusive_distinct) == 1, exclusive_distinct
    card_id, setter, _ordinal, flags = exclusive_distinct[0]
    assert (card_id, setter) == (BRANCH_CATEGORY, "Category")
    assert flags == [["DESTROY", "DRAW"], ["DESTROY"], ["DRAW"]], flags


def test_23_shadowing_rebinds_misattribute_five_setter_calls(bodies):
    """
    🔴 §7 C — **별개 발견.** ``CreateEffect`` 도 ``Clone`` 도 아닌 RHS 로 기존
    블록 변수를 다시 묶는 자리가 **25곳** 있고, 그 뒤 그 변수에 붙는 설정자
    **5건 / 3장**이 **직전 ``create`` 블록으로 잘못 귀속된다.**

    이것은 분기 문제가 **아니라** 3-F-28 의 블록 탐지 계열이다.
    """
    any_local = re.compile(r"\blocal\s+([A-Za-z_]\w*)\s*=\s*([^\n]*)")
    is_create = re.compile(r"^\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\(")
    #: 🔴 Phase 3-F-32 — 이 줄은 production 의 clone 규칙을 **따로 베낀 것**
    #: 이었고, 그 사이에 production 이 두 형태를 더 인정했다. 위의 ``bind``
    #: 이벤트는 production 정규식으로 만들므로, 이 복사본을 그대로 두면 같은
    #: 자리가 bind 이면서 rebind 로 동시에 세어진다. production 과 같은 세
    #: 형태를 받도록 맞춘다 (3-F-28 이 기록한 '복사본' 함정의 재발이다).
    is_clone = re.compile(
        r"^\s*(?:[A-Za-z_]\w*\s*:\s*Clone\s*\([^()\n]*\)"
        r"|Effect\s*\.\s*Clone\s*\(\s*[A-Za-z_]\w*\s*\))"
    )
    tracked = ("Category", "TargetRange", "Range", "Property", "Type", "Code", "CountLimit")

    shadowing = 0
    misattributed = collections.Counter()
    cards = set()
    for card_id, body in bodies.items():
        events = []
        for m in lua_loader._RE_CREATE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), "bind", m.group(2), None))
        for m in lua_loader._RE_CLONE_EFFECT.finditer(body):
            if lua_loader._is_card_effect(body, m.group(1), m.group(2), lua_loader._clone_source(m)):
                events.append((m.start(), "bind", m.group(2), None))
        for m in any_local.finditer(body):
            rhs = m.group(2)
            if is_create.match(rhs) or is_clone.match(rhs):
                continue
            events.append((m.start(), "rebind", m.group(1), rhs.strip()))
        for m in lua_loader._RE_SETTER.finditer(body):
            if m.group(2) in tracked:
                events.append((m.start(), "set", m.group(1), m.group(2)))
        events.sort(key=lambda e: e[0])

        bound: set[str] = set()
        shadowed: dict[str, str] = {}
        for _pos, kind, var, extra in events:
            if kind == "bind":
                bound.add(var)
                shadowed.pop(var, None)
            elif kind == "rebind":
                if var in bound:
                    shadowing += 1
                    shadowed[var] = extra
            elif var in shadowed:
                misattributed[extra] += 1
                cards.add(card_id)

    #: 🔴 Phase 3-F-32 에서 그림자 재바인딩 25 → **23**, 잘못 귀속되는 설정자
    #: 5 → **3**. 그 Phase 가 ``e1:Clone(e1)`` 과 ``Effect.Clone(e1)`` 을
    #: 블록으로 인정하면서, 그 두 자리는 더 이상 "모르는 RHS 로 다시 묶는
    #: 자리" 가 아니게 됐다. 남은 3건은 ``c52445243`` 의
    #: ``e:GetLabelObject()`` 하나이고, 그것은 정적으로 풀 수 없으므로
    #: **UNKNOWN 이 맞다** — 이 Phase 의 결론(옛 규칙은 틀린 값을 만들었다)은
    #: 그대로다.
    assert shadowing == 23, shadowing
    assert sum(misattributed.values()) == 3, dict(misattributed)
    assert dict(misattributed) == {"Category": 3}, dict(misattributed)
    assert cards == {BRANCH_CATEGORY}, cards

    #: 세 카드의 원문 모양은 그대로 못 박는다.
    assert "local e1=e:GetLabelObject()" in script_text(BRANCH_CATEGORY)
    assert "local e2=e1:Clone(e1)" in script_text(CLONE_WITH_ARG)
    assert "local e2=Effect.Clone(e1)" in script_text(STATIC_CLONE)
    #: 🔴 방향이 뒤집힌 두 줄 — 3-F-32 이후에는 **잡는다.**
    assert lua_loader._RE_CLONE_EFFECT.search("local e2=e1:Clone(e1)")
    assert lua_loader._RE_CLONE_EFFECT.search("local e2=Effect.Clone(e1)")
    #: ``e:GetLabelObject()`` 는 여전히 잡지 않는다 — Effect 가 아니다.
    assert not lua_loader._RE_CLONE_EFFECT.search("local e1=e:GetLabelObject()")


# ======================================================================
# D. §7 E · §10 — production / Engine / AI 영향
# ======================================================================


def test_24_engine_and_agent_never_read_these_fields():
    """
    🔴 §7 E · §10 — ``engine/`` · ``agent/`` 가 네 칸을 **한 번도 읽지 않는다.**

    "engine 에 같은 이름이 있다" 만으로 판단하지 않는다 — AST 로 속성 접근을
    전부 모아 **base 식별자까지** 본다. ``engine/`` 의 ``.code`` 접근은 전부
    ``verdict`` · ``result`` · ``requirement`` 등 **다른 것의 ``code``** 다.
    """
    spec_fields = {f.name for f in dataclasses.fields(EffectSpec)}
    #: 이름이 다른 클래스와 겹치지 않는 칸 — 0건이어야 한다.
    unique = ("effect_types", "target_ranges", "cloned_from", "count_limit")
    hits = collections.defaultdict(list)
    for directory in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in spec_fields:
                    hits[node.attr].append(
                        (str(path.relative_to(PROJECT_ROOT)), node.lineno,
                         ast.unparse(node.value))
                    )
    for field in unique:
        assert hits[field] == [], (field, hits[field])
    #: ``categories`` · ``properties`` · ``ranges`` 도 0건이다.
    for field in ("categories", "properties", "ranges"):
        assert hits[field] == [], (field, hits[field])

    #: 🔴 ``code`` 와 ``index`` 는 **다른 클래스에도 흔한 이름**이므로 "0건" 을
    #: 요구하면 안 된다. 3-F-28 에서 ``code`` 를 0건이라고 적었다가 틀렸고
    #: (``engine/`` 에 ``.code`` 접근이 62건 있다), 이 Phase 에서 ``index`` 로
    #: 같은 실수를 반복했다 — ``engine/action_target.py`` 의 ``self.index`` 는
    #: 존 번호다. 그래서 **base 식별자를 보고 EffectSpec 이 아님을 확인**한다.
    for field in ("code", "index"):
        bases = {base for _, _, base in hits[field]}
        assert bases, f"{field} 접근이 아예 없다면 이 테스트의 전제가 바뀐 것이다"
        for base in bases:
            #: ``spec``/``e``/``eff``/``effect`` 로 시작하는 base 가 없다 —
            #: 그것이 EffectSpec 을 가리키는 관례적 이름이다.
            assert not base.endswith("spec"), (field, base)
            assert base not in ("e", "eff", "effect", "block"), (field, base)
            assert not base.startswith("spec."), (field, base)


def test_25_search_filtering_does_not_depend_on_block_attribution(repository):
    """
    🔴 §7 E — 검색 **필터**는 블록 귀속에 영향받지 않는다.

    ``Card.has_effect_category`` 가 블록별 ``categories`` **또는** 파일 전체
    ``LuaScriptInfo.categories`` 를 본다. corpus 전체에서 "블록에만 있고 파일
    전체 목록에는 없는 category" 가 **0건**이므로, 귀속이 틀려도 필터 결과가
    바뀌지 않는다.
    """
    block_only = []
    for card in repository.all_cards():
        if card.script is None:
            continue
        filewide = set(card.script.categories)
        perblock: set[str] = set()
        for effect in card.effects:
            perblock |= set(effect.categories)
        for category in perblock - filewide:
            block_only.append((card.id, category))
    assert block_only == [], block_only[:20]

    #: 계약을 코드로도 확인한다 — ``or`` 로 파일 전체 목록을 함께 본다.
    body = inspect.getsource(type(repository.get(BRANCH_CATEGORY)).has_effect_category)
    assert "self.script.categories" in body
    assert "has_category" in body


def test_26_search_ranking_is_unchanged_for_the_misattributed_cards(repository):
    """
    🔴 §7 E — 검색 **순위**만 블록 수에 민감하다
    (``card_search.py`` 의 ``sum(1 for e in card.effects if ...)``).

    귀속이 틀린 3장 **전부** 각 category 를 **정확히 한 블록**이 갖는다 —
    올바른 귀속에서도 같으므로 **점수가 바뀌지 않는다.**
    """
    search = (PROJECT_ROOT / "core" / "card_search.py").read_text(encoding="utf-8")
    assert "sum(1 for e in card.effects if e.has_category(category))" in search

    #: 🔴 **Phase 3-F-31 정정.** 그 Phase 가 귀속 오류를 고치면서
    #: ``c52445243`` 의 블록별 category 가 **0개**가 됐다 (전에는 DESTROY 1 ·
    #: DRAW 1). 그래서 이 테스트가 적어 둔 "점수가 바뀌지 않는다" 는
    #: **그 카드에 대해서는 더 이상 참이 아니다** — 숨기지 않고 적는다.
    #:
    #: * **필터**는 그대로다 — ``has_effect_category`` 가 파일 전체 목록
    #:   (``script.categories``)도 보고 거기에는 DESTROY·DRAW 가 남아 있다.
    #: * **순위**는 그 카드에서 DESTROY/DRAW 질의 점수가 1 → 0 으로 내려간다.
    #:
    #: 그것이 **올바른 방향**이다 — 그 블록은 그 category 를 갖지 않는다.
    for card_id in (CLONE_WITH_ARG, STATIC_CLONE):
        card = repository.get(card_id)
        assert card is not None, card_id
        counts = collections.Counter()
        for effect in card.effects:
            for category in effect.categories:
                counts[category] += 1
        assert counts, card_id
        #: 🔴 어느 category 도 두 블록 이상에 걸쳐 있지 않다.
        assert set(counts.values()) == {1}, (card_id, dict(counts))

    #: 🔴 ``c52445243`` 은 블록별 category 가 0개이지만 **필터는 여전히 맞는다.**
    branched = repository.get(BRANCH_CATEGORY)
    assert sum(len(e.categories) for e in branched.effects) == 0
    assert "DESTROY" in branched.script.categories
    assert "DRAW" in branched.script.categories
    assert branched.has_effect_category("DESTROY")
    assert branched.has_effect_category("DRAW")


def test_27_this_phase_changed_no_production_code():
    """
    🔴 §8 · §10 — **production 을 수정하지 않았다.**

    지시서 §8 의 다섯 조건 중 **③ production downstream 실제 영향**이
    충족되지 않는다 (``test_24``~``test_26``). 그래서 수정하지 않는다.
    """
    changed = _changed_files()
    production = {
        path for path in changed
        if path.endswith(".py") and not path.startswith("tests/")
    }
    assert production == set(), production
    #: 문서와 테스트만 바뀐다.
    for path in changed:
        assert path.startswith(("tests/", "docs/")), path


def test_28_state_hash_and_rng_are_unchanged(repository):
    """🟢 §10 — ``state_hash`` · RNG 불변."""
    first = opened_duel(repository, seed=61)
    second = opened_duel(repository, seed=61)
    assert first.state.state_hash() == second.state.state_hash()
    assert opened_duel(repository, seed=62).state.state_hash() != first.state.state_hash()
    assert [first.state.rng.randrange(10_000) for _ in range(12)] == [
        second.state.rng.randrange(10_000) for _ in range(12)
    ]


def test_29_the_search_ranking_digest_is_unchanged(repository):
    """
    🟢 §10 — 6판 **611결정** digest 불변. 기대값을 손으로 적지 않고, 다른
    테스트 파일이 이미 고정해 둔 값을 AST 로 읽어 가장 많이 고정된 것을 쓴다.
    """
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


def test_30_hidden_information_and_the_view_are_unchanged(repository):
    """🟢 §10 — ``CardDefinitionView`` 가 블록 내용을 **내보내지 않는다.**"""
    fields = {f.name for f in dataclasses.fields(CardDefinitionView)}
    assert len(fields) == 26
    assert "effect_count" in fields
    for banned in ("categories", "properties", "ranges", "target_ranges",
                   "effect_types", "code", "effects", "script"):
        assert banned not in fields, banned
    assert not hasattr(opened_duel(repository, seed=63).view(0), "effects")


def test_31_effect_ref_ordinal_and_the_sixteen_definitions_are_unchanged(
    repository, scripts
):
    """🟢 §10 · §11-17 — ``EffectRef``/``ordinal`` 과 16개 정의 불변."""
    assert len(scripts) == SCRIPTS
    assert sum(len(info.effects) for info in scripts.values()) == BLOCKS

    assert len(EFFECT_LIBRARY) == 16
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        card = repository.get(ref.card_id)
        assert card is not None and card.script is not None, ref
        assert ref.ordinal == 0 and len(card.script.effects) == 1, ref
        resolved = ref.resolve(card)
        assert resolved is not None and resolved.code == "EVENT_FREE_CHAIN", ref
        assert effect_refs(card) == [EffectRef(ref.card_id, 0)], ref

    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]


def test_32_the_3f29_clone_result_is_not_reverted(scripts):
    """
    🟢 §11-17 — 3-F-29 의 ``Clone`` 덮어쓰기가 그대로다.

    분기 안에서도 **첫 호출은 물려받은 값을 덮어쓴다** — 이 Phase 는 그 규칙을
    건드리지 않았다.
    """
    assert parse_card(CLONE_REPLACE).effects[1].effect_types == ["QUICK_O"]

    specs = blocks_of("""
        local e1=Effect.CreateEffect(c)
        e1:SetCategory(CATEGORY_DRAW)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        if cond then
            e2:SetCategory(CATEGORY_DESTROY)
        else
            e2:SetCategory(CATEGORY_TOHAND)
        end
        c:RegisterEffect(e2)
    """)
    #: 🔴 물려받은 ``DRAW`` 는 **사라지고**, 두 분기 값만 합쳐진다.
    assert specs[1].categories == ["DESTROY", "TOHAND"]
    assert "DRAW" not in specs[1].categories

    #: corpus 총계도 3-F-29 와 같다.
    totals = collections.Counter()
    for info in scripts.values():
        for spec in info.effects:
            for field in ("effect_types", "ranges", "target_ranges",
                          "categories", "properties"):
                totals[field] += len(getattr(spec, field))
    #: 🔴 Phase 3-F-31 에서 ``categories`` 20,505 → **20,503** (−2) —
    #: ``c52445243`` 의 귀속 오류를 고치면서 그 블록의 두 category 가
    #: 사라졌다. 나머지 네 칸은 **그대로다.**
    assert dict(totals) == {
        #: 🔴 Phase 3-F-32 에서 +3 블록만큼 늘었다 (``categories`` 는 그대로).
        "effect_types": 45340, "ranges": 15064, "target_ranges": 2063,
        "categories": 20503, "properties": 23887,
    }, dict(totals)


def test_33_the_cache_still_reflects_the_current_parser(scripts, tmp_path):
    """🟢 §10 — 캐시가 지금 파서의 결과를 돌려준다. 서명은 ``v7`` 그대로."""
    cache = tmp_path / "lua_scripts.json"
    source = LuaScriptSource(PROJECT_ROOT)
    written = source.load_cached(cache)
    read_back = source.load_cached(cache)
    for table in (scripts, written, read_back):
        assert sum(len(info.effects) for info in table.values()) == BLOCKS
    #: 🔴 Phase 3-F-31 에서 ``v7`` → ``v8``. 3-F-30 은 파서를 바꾸지 않아
    #: 올리지 않았고, **3-F-31 이 바꿨으므로 올랐다** — 이 테스트의 주장
    #: ("캐시가 지금 파서의 결과를 돌려준다")은 그대로다.
    #: 🔴 Phase 3-F-32 에서 ``v8`` → **``v9``** — ``Clone`` 의 인자 있는
    #: 형태와 점 형태를 블록으로 인정했다. 캐시 서명에 파서 버전이
    #: 들어 있지 않아 **다섯 Phase 연속 수동**으로 올리고 있다 (위험 E4).
    #: 🔴 Phase 3-F-37 이 ``v9:`` -> ``v10-<shape>:`` 로 바꿨다.
    #: ``LuaScriptInfo`` 에 ``effect_offsets`` 와 ``source_digest`` 가 생겨
    #: 캐시 모양이 달라졌기 때문이다. 뒤의 ``<shape>`` 는 저장되는 칸 목록의
    #: 해시이고 **자동으로** 바뀐다 — 같은 번호 아래에서 칸이 달라지는 사고를
    #: 막는다 (3-F-37 작업 중 실제로 겪었고, 기존 테스트 103건이 그래서 한 번
    #: 깨졌다). 이 테스트의 주장은 그대로다: **파서 산출물이 달라지면 캐시
    #: 서명도 달라져야 한다.**
    assert source._signature().startswith("v10-")
    body = inspect.getsource(LuaScriptSource._signature)
    assert 'f"v10-{_CACHE_SHAPE_TAG}:{count}:{newest:.0f}"' in body
    assert 'f"v9:' not in body
    assert 'f"v8:' not in body


def _changed_files() -> set[str]:
    """
    이 Phase 의 diff 에 등장하는 파일.

    🔴 ``HEAD`` 를 기준으로 잡으면 **다음 Phase 가 production 을 건드릴 때 이
    테스트가 엉뚱하게 깨진다** (3-F-25 의 ``test_30`` 이 3-F-26 에서 그렇게
    깨졌다). 그래서 제목이 ``Phase 3-F-30:`` 으로 시작하는 commit 들을 찾아
    *가장 오래된 것의 부모 → 가장 최근 것* 을 본다. 이 Phase 는 작업과 보고서를
    나눠 커밋하므로 **파일을 추가한 commit 하나만 보면 안 된다** (3-F-28
    ``test_36`` 이 그렇게 빈 집합을 받았다).
    """
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        ).stdout

    phase = run("log", "--format=%H", "--grep=^Phase 3-F-30:", "HEAD").split()
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
