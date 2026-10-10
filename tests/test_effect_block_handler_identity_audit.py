r"""
Phase 3-F-36 — Effect 블록 / 핸들러 식별자 대응 감사
=====================================================

핵심 질문
---------
서로 다른 파싱 시점이나 경로에서 생성된 두 목록을, **순서나 길이에 의존하지
않고** 동일한 Effect 단위로 정확히 연결할 수 있는가?

지금 결합은 이렇게 이루어진다 (실제 HEAD ``analysis/effect_analyzer.py``).

.. code-block:: python

    entries = self._collect_handlers(source, spans)
    for position, spec in enumerate(card.script.effects):
        entry = entries[position] if position < len(entries) else {}

🔴 **위치뿐이다.** 두 목록에서 같은 ``position`` 을 갖는다는 사실은 대응
관계의 증거가 아니다 — 두 목록은 같은 파싱의 두 뷰가 아니라 **서로 다른
시점의 두 파싱**이기 때문이다 (Phase 3-F-35).

이 Phase 가 측정한 것
---------------------
1. 🟢 **식별자 후보는 하나 있다** — 블록을 만든 ``create``/``clone`` 매치의
   바이트 offset(``m.start()``). 두 경로가 **모두** 이벤트 수집 시점에
   그 값을 갖고 있고, 코퍼스 전수에서 스크립트 안 **중복 0** (34,684개)이며
   블록 목록·entries 목록과 **1:1** 로 맞는다.
2. 🔴 **두 경로가 모두 그 값을 버린다.** 로더는 ``for _pos, kind, payload in
   events:`` 에서 ``create``/``clone`` 분기가 ``_pos`` 를 읽지 않고,
   analyzer 는 ``_enclosing_function(pos, spans)`` 에만 쓴다. ``EffectSpec``
   9칸과 ``LuaScriptInfo`` 14칸에 그 값을 담는 자리가 없고, 캐시 직렬화도
   담지 않는다. ``ordinal`` 은 목록 위치 그 자체라 순환이다.
3. 🔴 **"결합 자리에서 다시 계산" 은 아무것도 잡지 못한다** — 재계산한 블록
   offset 과 entries offset 이 **같은 텍스트**에서 나오므로 정의상 일치하고,
   잡아야 할 바로 그 상황(두 텍스트가 어긋난 상황)을 놓친다 (``test_17``).
   식별자는 **파싱 시점에 저장**되어야만 쓸모가 있다 (``test_18``).
4. 🔴 **길이도 순서도 이름 순서까지 같은데 의미가 뒤바뀐 사례**를 실제
   production 경로로 구성했다 (``test_21``). 어떤 길이·index·이름 검사도
   통과하고 **offset 만 잡는다.**
5. 🟢 **정상 corpus 에서는 두 방식이 완전히 같은 결과를 낸다** — 34,635
   블록 전부가 offset 으로 짝지어지고, 고른 entry 가 위치 기반과
   **객체까지 동일**하다 (``test_34``). 그래서 지금 산출물 피해는 없다.
6. 🔴 **식별자를 쓸 수 없을 때 production 이 하는 일은 UNKNOWN 이 아니다** —
   빈 handlers 는 "조건 없음 · 비용 없음 · 처리 없음 · 미등록"을 **적극적으로
   주장**하고, 그 모양은 코퍼스에 실재하는 6,022개의 진짜 빈 블록과
   **구별되지 않는다** (``test_37``/``test_38``).

따라서 결론은 **audit-only** 다. 식별자 자체는 존재하고 유효하지만, 그것을
쓰려면 파싱 시점에 저장해야 하고, 저장 자리는 §6 이 금지한 ``EffectSpec``
API 변경이거나 ``LuaScriptInfo`` + 캐시 직렬화 + 캐시 signature 까지 건드리는
광범위한 자료구조 변경이다. §6 은 그 경우 **구현하지 말고 설계 선택지와
비용을 보고하라**고 했다.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import analysis.effect_analyzer as analyzer_module
import sources.lua_loader as loader_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import CardAnalysis, HandlerBinding
from core.card_model import Card, EffectSpec
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from engine.ids import EffectRef, effect_refs, iter_effects
from sources.lua_loader import (
    LuaScriptInfo,
    _clone_source,
    _info_from_dict,
    _info_to_dict,
    _is_card_effect,
    _RE_BLOCK_COMMENT,
    _RE_CLONE_EFFECT,
    _RE_CREATE_EFFECT,
    parse_lua_source,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-35 가 보고한 기준값 (테스트가 실제로 다시 산출한다) ---------
SCRIPT_COUNT = 12702
BLOCK_TOTAL = 34684
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
ANALYSIS_TOTALS = {
    "registered": 26352, "resolution": 8283, "cond": 12438,
    "cost": 5007, "target": 5516, "action": 18280, "cat": 20484,
}
SEARCH_CATEGORIES = 31
SEARCH_LOCATIONS = 31
#: 🔴 검색 불변성은 **64자리 지문이 아니라 개수로** 못 박는다 (``test_36`` 참고).
SEARCH_CATEGORY_NAMES = [
    "ANNOUNCE", "ATKCHANGE", "COIN", "CONTROL", "COUNTER", "DAMAGE", "DECKDES",
    "DEFCHANGE", "DESTROY", "DICE", "DISABLE", "DISABLE_SUMMON", "DRAW",
    "EQUIP", "FUSION_SUMMON", "HANDES", "LEAVE_GRAVE", "LVCHANGE", "NEGATE",
    "POSITION", "RECOVER", "RELEASE", "REMOVE", "SEARCH", "SPECIAL_SUMMON",
    "SUMMON", "TODECK", "TOEXTRA", "TOGRAVE", "TOHAND", "TOKEN",
]
SEARCH_CATEGORY_COUNTS = [
    24, 999, 56, 176, 141, 713, 163, 144, 2152, 44, 337, 51, 788, 392, 108,
    233, 358, 124, 367, 396, 237, 42, 733, 1542, 4730, 79, 671, 55, 708,
    2588, 221,
]
SEARCH_LOCATION_NAMES = [
    "ALL", "DECK", "DECKBOT", "DECKSHF", "EMZONE", "EXTRA", "FZONE", "GRAVE",
    "GRAVE_MZONE", "HAND", "HAND_DECK_EXTRA_GRAVE", "HAND_DECK_GRAVE",
    "HAND_DECK_GRAVE_EXTRA", "HAND_DECK_GRAVE_SZONE", "HAND_GRAVE_REMOVED",
    "HDEG", "HDG", "MMZONE", "MZONE", "MZONE_GRAVE_REMOVED", "ONFIELD",
    "OVERLAY", "PUBLIC", "PZONE", "REASON_CONTROL", "REASON_COUNT",
    "REASON_TOFIELD", "REMOVED", "REMOVED_HAND_DECK_GRAVE", "STZONE", "SZONE",
]
SEARCH_LOCATION_COUNTS = [
    1, 33, 0, 0, 5, 65, 304, 1603, 0, 1798, 0, 0, 0, 0, 0, 0, 0, 1, 5170, 0,
    3, 0, 0, 346, 0, 0, 0, 56, 0, 0, 1227,
]
#: 🔴 Phase 3-F-37 이 ``v9:`` -> ``v10-<shape>:`` 로 바꿨다.
#: ``LuaScriptInfo`` 에 ``effect_offsets`` 와 ``source_digest`` 가 생겨
#: 캐시 모양이 달라졌기 때문이다. 뒤의 ``<shape>`` 는 저장되는 칸 목록의
#: 해시이고 **자동으로** 바뀐다 — 같은 번호 아래에서 칸이 달라지는 사고를
#: 막는다 (3-F-37 작업 중 실제로 겪었고, 기존 테스트 103건이 그래서 한 번
#: 깨졌다). 이 테스트의 주장은 그대로다: **파서 산출물이 달라지면 캐시
#: 서명도 달라져야 한다.**
CACHE_PREFIX = "v10-"

#: Phase 3-F-36 이 측정한 값 — 테스트가 다시 산출한다
EMPTY_HANDLER_BLOCKS = 9887
EMPTY_AND_UNREGISTERED_BLOCKS = 6022

#: Phase 3-F-32~35 의 대표 회귀 사례
PHASE32_CARDS = {
    44887817: (5, 4, "EFFECT_CANNOT_MSET", "e1"),
    4997565: (5, 3, "EFFECT_DISABLE_EFFECT", "e1"),
    56410769: (3, 2, "EFFECT_CANNOT_ATTACK_ANNOUNCE", "e2"),
}
GROUP_CLONE_CARD = 63708033
LABEL_OBJECT_CARD = 52445243

#: Phase 3-F-32 가 측정한 c4997565 의 블록별 offset
C4997565_OFFSETS = [199, 542, 2703, 2911, 3516]


# ===========================================================================
# 공용 도구
# ===========================================================================
class _StubRepo:
    """analyzer 가 쓰는 최소 인터페이스."""

    constants = None


def _block_offsets(source: str) -> list[tuple[int, str, str | None]]:
    r"""로더가 블록을 만드는 **바로 그 지점**의 (offset, 변수명, 부모) 목록.

    🔴 탐지 규칙을 복사하지 않는다 — :mod:`sources.lua_loader` 의 정규식과
    ``_is_card_effect`` 를 그대로 import 해 쓴다 (Phase 3-F-28/3-F-32 가
    복사본 때문에 각각 한 번씩 어긋났다).
    """
    body = _RE_BLOCK_COMMENT.sub("", source)
    out: list[tuple[int, str, str | None]] = []
    for match in _RE_CREATE_EFFECT.finditer(body):
        if _is_card_effect(body, match.group(1), match.group(2), None):
            out.append((match.start(), match.group(2), None))
    for match in _RE_CLONE_EFFECT.finditer(body):
        src_var = _clone_source(match)
        if _is_card_effect(body, match.group(1), match.group(2), src_var):
            out.append((match.start(), match.group(2), src_var))
    out.sort()
    return out


def _analyze_with(parsed_text: str, disk_text: str, *, card_id: int = 1):
    r"""``card.script`` 과 디스크 텍스트를 **다르게** 두고 production 을 돌린다.

    인공적인 상황이 아니다 — 캐시가 낡거나 ``script_dir`` 이 어긋나면 정확히
    이 상태가 된다 (Phase 3-F-35 가 출하된 CLI 로 재현했다).
    """
    parsed_text = textwrap.dedent(parsed_text)
    disk_text = textwrap.dedent(disk_text)
    with tempfile.TemporaryDirectory() as directory:
        name = f"c{card_id}.lua"
        pathlib.Path(directory, name).write_text(disk_text, encoding="utf-8")
        card = Card(id=card_id, name=name)
        card.script = parse_lua_source(card_id, name, parsed_text)
        analyzer = EffectAnalyzer(_StubRepo(), script_dir=directory)
        source = analyzer._read_source(name)
        entries = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        return {
            "blocks": card.script.effects,
            "entries": entries,
            "analysis": analyzer.analyze(card),
            "parsed_offsets": _block_offsets(parsed_text),
            "disk_offsets": _block_offsets(source),
        }


def _rows(analysis) -> list[tuple]:
    out = []
    for registered, group in ((True, analysis.effects),
                              (False, analysis.resolution_effects)):
        for effect in group:
            out.append((registered, effect.index, effect.has_condition,
                        bool(effect.costs), len(effect.actions)))
    return out


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-36:"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        files: set[str] = set()
        for sha in shas:
            out = subprocess.run(
                ["git", "show", "--name-only", "--format=", sha],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
            ).stdout
            files.update(x for x in out.split("\n") if x.strip())
        return files
    except (OSError, subprocess.SubprocessError):
        return set()


# --- §5 가 요구한 Lua 사례 -------------------------------------------------
TWO_COND_COST = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
"""
#: 같은 두 블록인데 **원문 순서만** 뒤바뀐 것 — 길이는 같고 이름 순서가 다르다
TWO_SWAPPED = """
    function s.initial_effect(c)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: 🔴 길이도 2, **이름 순서도 ['e1','e2'] 로 같은데** 핸들러가 서로 뒤바뀐 것.
#: 앞에 주석 두 줄이 늘어 offset 이 밀렸다.
SAME_ORDER_DIFFERENT_SEMANTICS = """
    --이 카드의 효과를 다시 쓴 버전
    --줄이 늘어 offset 이 밀린다
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCost(s.cost)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCode(EVENT_TO_HAND)
        e2:SetCondition(s.con)
        c:RegisterEffect(e2)
    end
"""
ONE_COND = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: handler 가 전혀 없는 **유효한** 블록
NO_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        e1:SetValue(500)
        c:RegisterEffect(e1)
    end
"""
#: parser 가 **인식하지 못하는** 대입 뒤의 handler (Phase 3-F-31)
UNRECOGNISED_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        e1=e:GetLabelObject()
        e1:SetCost(s.lost)
    end
"""
#: 같은 handler 이름이 두 블록에
SHARED_HANDLER_NAME = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.shared)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetCondition(s.shared)
        c:RegisterEffect(e2)
    end
"""
#: Clone — 부모와 자식
CLONE_PAIR = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        local e2=e1:Clone()
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
"""
#: 같은 변수에 Clone 재대입 — 두 블록 모두 ``e1``
CLONE_SAME_NAME = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        e1=e1:Clone()
        e1:SetCost(s.cost)
        c:RegisterEffect(e1)
    end
"""
#: 보조 함수가 Effect 를 만들고 등록한다 — parser 는 블록으로 세지 않는다
HELPER_CREATES = """
    function s.initial_effect(c)
        local e0=Fusion.CreateSummonEff(c,s.ffilter)
        e0:SetOperation(s.fop)
        c:RegisterEffect(e0)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: 같은 변수명이 다른 함수에서 다시 쓰인다
SAME_NAME_TWO_FUNCTIONS = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
    function s.op(e,tp)
        local e1=Effect.CreateEffect(c)
        e1:SetCost(s.cost)
        tc:RegisterEffect(e1)
    end
"""


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


# ===========================================================================
# A. §4.1 / §4.2 — 어떤 식별 정보가 실제로 존재하고 어디까지 살아남는가
# ===========================================================================
def test_01_effect_spec_has_no_identifier_field():
    r"""🔴 ``EffectSpec`` 9칸에 offset·span·ID 를 담는 자리가 **없다**."""
    names = {f.name for f in dataclasses.fields(EffectSpec)}
    assert names == {
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    }
    assert not {n for n in names if re.search(r"offset|span|pos|uid|ident", n)}


def test_02_lua_script_info_now_has_the_identifier_field():
    r"""🟢 ``LuaScriptInfo`` 가 식별자를 담는다 (3-F-37 이 넣었다).

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 이 적어 둔 사실은 **그때는 맞았다** —
       이 Phase 의 역할은 결함을 측정하고 기록하는 것이었다. 3-F-37 이 바로
       그 결함을 고쳤으므로 **사실이 바뀌었고**, 이 테스트는 "그때 그랬다" 를
       지우지 않고 "지금은 이렇다" 로 옮겨 적는다. 가정이 틀렸던 것이 아니라
       **대상이 바뀌었다.**

       3-F-36 당시: 14칸, offset 을 담는 자리 **없음**.
       3-F-37 이후: 16칸, ``effect_offsets`` + ``source_digest``.
    """
    names = {f.name for f in dataclasses.fields(LuaScriptInfo)}
    assert len(names) == 16
    assert "effect_offsets" in names
    assert "source_digest" in names


def test_03_the_cache_round_trip_now_carries_the_identifier():
    r"""🟢 캐시 직렬화가 식별자를 함께 싣는다 (3-F-37).

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 이 적어 둔 사실은 **그때는 맞았다** —
       이 Phase 의 역할은 결함을 측정하고 기록하는 것이었다. 3-F-37 이 바로
       그 결함을 고쳤으므로 **사실이 바뀌었고**, 이 테스트는 "그때 그랬다" 를
       지우지 않고 "지금은 이렇다" 로 옮겨 적는다. 가정이 틀렸던 것이 아니라
       **대상이 바뀌었다.**

       🔴 ``EffectSpec`` 쪽 9칸은 **그대로**다 — §7 이 그 API 변경을
       금지했고, 식별자는 ``LuaScriptInfo`` 의 평행 목록으로 들어갔다.
    """
    info = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    data = _info_to_dict(info)
    assert set(data["effects"][0]) == {
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    }
    assert data["effect_offsets"] == info.effect_offsets
    assert data["source_digest"] == info.source_digest
    back = _info_from_dict(data)
    assert [s.index for s in back.effects] == [s.index for s in info.effects]
    assert back.effect_offsets == info.effect_offsets
    assert back.source_digest == info.source_digest


def test_04_the_loader_now_keeps_the_offset_it_used_to_discard():
    r"""🟢 로더가 ``m.start()`` 를 **이벤트에 넣고 블록을 만들 때 읽는다**.

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 당시 루프 변수 이름이 ``_pos`` 였고
       본문에서 **한 번도 읽지 않았다** — 식별자가 파싱 순간에 존재했다가
       그 자리에서 사라졌다는 증거였다. 3-F-37 이 그 값을
       ``LuaScriptInfo.effect_offsets`` 에 기록하도록 고쳤으므로 이름이
       ``pos`` 로 바뀌고 Load 가 생겼다.
    """
    source = inspect.getsource(loader_module)
    tree = ast.parse(source)
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "parse_lua_source"
    )
    #: 이벤트를 모을 때는 offset 을 **쓴다**
    starts = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "start"
    ]
    assert len(starts) >= 4
    #: 재생 루프의 변수 이름이 ``pos`` 다 — 쓰겠다는 선언이다
    loops = [
        node for node in ast.walk(func)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
        and len(node.target.elts) == 3
    ]
    assert len(loops) == 1
    names = {e.id for e in loops[0].target.elts if isinstance(e, ast.Name)}
    assert "pos" in names
    assert "_pos" not in names
    #: 🟢 루프 본문에서 **읽는다** — 3-F-36 때는 Load 가 0개였다
    loaded = {
        node.id for node in ast.walk(loops[0])
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert "pos" in loaded
    #: 그리고 그 값이 평행 목록에 들어간다
    assert "effect_offsets" in inspect.getsource(loader_module)


def test_05_the_analyzer_uses_the_offset_only_to_name_the_function():
    r"""🔴 analyzer 도 같은 offset 을 갖고 있지만 ``_enclosing_function`` 에만
    쓴다 — 블록과 짝지을 때는 쓰지 않는다."""
    func = next(
        node for node in ast.walk(ast.parse(inspect.getsource(analyzer_module)))
        if isinstance(node, ast.FunctionDef) and node.name == "_collect_handlers"
    )
    loops = [
        node for node in ast.walk(func)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
        and len(node.target.elts) == 3
    ]
    assert len(loops) == 1
    assert {e.id for e in loops[0].target.elts if isinstance(e, ast.Name)} == {
        "pos", "kind", "payload"
    }
    #: ``pos`` 가 인자로 들어가는 호출은 ``_enclosing_function`` 뿐이다
    users = set()
    for node in ast.walk(loops[0]):
        if isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id == "pos":
                    users.add(
                        node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", "?")
                    )
    assert users == {"_enclosing_function"}


def test_06_the_join_site_no_longer_uses_position():
    r"""🟢 결합 자리가 **식별자로** 짝짓는다 — 위치 색인이 사라졌다.

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 당시 ``entries`` 를 색인하는 구문이
       정확히 하나 있었고 그 색인이 ``position`` 이었다 — 그것이 "위치뿐"
       이라는 증거였다. 3-F-37 이 ``(source_digest, effect_offsets[i])`` 쌍
       으로 짝짓도록 고쳤으므로 그 구문 자체가 **없어졌다.**

    🔴 ``spans`` 는 지금도 식별자가 아니다 — 그것은 **함수 경계** 목록이고
    블록의 source span 이 아니다. 한 함수에 블록이 여럿이면 구별하지 못한다.
    """
    func = next(
        node for node in ast.walk(ast.parse(textwrap.dedent(
            inspect.getsource(EffectAnalyzer._analyze_card))))
        if isinstance(node, ast.FunctionDef) and node.name == "_analyze_card"
    )
    subscripts = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name) and node.value.id == "entries"
    ]
    assert subscripts == []
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    assert "position < len(entries)" not in source
    assert "entries[position]" not in source
    #: 🟢 그 자리에 식별자가 들어왔다
    for token in ("source_digest", "effect_offsets", "offset"):
        assert token in source


def test_07_ordinal_is_the_list_position_so_it_cannot_verify_the_list():
    r"""🔴 ``ordinal`` 은 목록 위치 **그 자체**다 — 그것으로 목록 대응을
    검증하는 것은 순환이다."""
    info = parse_lua_source(1, "c1.lua", textwrap.dedent(TWO_COND_COST))
    card = Card(id=1, name="c1.lua")
    card.script = info
    assert [r.ordinal for r in effect_refs(card)] == list(range(len(info.effects)))
    assert [r.ordinal for r, _s in iter_effects(card)] == [0, 1]


def test_08_effect_spec_index_is_not_unique():
    r"""🔴 ``EffectSpec.index`` 는 식별자가 아니다 — 같은 스크립트에서 같은
    이름이 여러 블록에 붙는다 (실제 카드로 확인)."""
    duplicated = 0
    for card_id, lua in (
        (4997565, (PROJECT_ROOT / "c4997565.lua")),
        (44887817, (PROJECT_ROOT / "c44887817.lua")),
    ):
        specs = parse_lua_source(
            card_id, lua.name, lua.read_text(encoding="utf-8")
        ).effects
        names = [s.index for s in specs]
        if len(set(names)) != len(names):
            duplicated += 1
    assert duplicated == 2


def test_09_no_parser_entry_id_exists_in_either_structure():
    r"""🔴 "parser entry ID" 라고 부를 만한 것이 두 자료구조에 **없다**.

    §4.2 가 물은 네 후보 중 살아남는 것은 아무것도 없다 — byte offset 은
    버려지고(``test_04``/``test_05``), source span 은 애초에 만들지 않고,
    ordinal 은 순환이고(``test_07``), entry ID 는 존재하지 않는다.
    """
    entry = EffectAnalyzer._collect_handlers(
        textwrap.dedent(TWO_COND_COST),
        EffectAnalyzer._function_spans(textwrap.dedent(TWO_COND_COST)),
    )
    #: 🟢 **Phase 3-F-37 정정** — entry 가 이제 ``offset`` 도 들고 있다.
    #: 3-F-36 당시에는 ``handlers`` 와 ``function`` 뿐이었고, 함수 이름은 한
    #: 함수에 블록이 여럿이면 구별하지 못하므로 식별자가 될 수 없었다.
    assert [sorted(e) for e in entry] == [["function", "handlers", "offset"]] * 2
    assert {e["function"] for e in entry} == {"initial_effect"}
    assert [e["offset"] for e in entry] == parse_lua_source(
        1, "c1.lua", textwrap.dedent(TWO_COND_COST)).effect_offsets


# ===========================================================================
# B. §4.2 / §4.3 — offset 은 유효한 식별자인가
# ===========================================================================
@pytest.mark.parametrize(
    "label,lua,expected_blocks",
    [
        ("정상", TWO_COND_COST, 2),
        ("handler 없는 유효 블록", NO_HANDLER, 1),
        ("인식 못한 handler", UNRECOGNISED_HANDLER, 1),
        ("같은 handler 이름", SHARED_HANDLER_NAME, 2),
        ("Clone", CLONE_PAIR, 2),
        ("같은 변수 Clone 재대입", CLONE_SAME_NAME, 2),
        ("보조 함수", HELPER_CREATES, 1),
        ("같은 이름 다른 함수", SAME_NAME_TWO_FUNCTIONS, 2),
    ],
)
def test_10_offset_is_unique_and_one_to_one_in_every_case(label, lua, expected_blocks):
    r"""🟢 §5 의 모든 사례에서 offset 이 **스크립트 안 고유**하고 블록 목록과
    **1:1** 로 맞는다 — 이름이 겹치는 사례에서도."""
    source = textwrap.dedent(lua)
    specs = parse_lua_source(1, "c1.lua", source).effects
    offsets = _block_offsets(source)
    assert len(specs) == expected_blocks, label
    assert len(offsets) == expected_blocks, label
    assert len({o for o, _v, _p in offsets}) == expected_blocks, label
    assert [v for _o, v, _p in offsets] == [s.index for s in specs], label


def test_11_offset_distinguishes_two_blocks_that_share_a_variable_name():
    r"""🟢 이름으로는 구별되지 않는 두 블록을 offset 이 구별한다."""
    source = textwrap.dedent(CLONE_SAME_NAME)
    offsets = _block_offsets(source)
    assert [v for _o, v, _p in offsets] == ["e1", "e1"]      # 이름은 같다
    assert offsets[0][0] != offsets[1][0]                     # offset 은 다르다
    assert offsets[1][2] == "e1"                              # 부모는 기록된다


def test_12_offset_is_unique_within_every_script_in_the_corpus():
    r"""🟢 전수 측정 — 12,702 스크립트 34,684 블록에서 스크립트 안 offset
    중복이 **0** 이다."""
    scripts = sorted(PROJECT_ROOT.glob("c*.lua"))
    assert len(scripts) == SCRIPT_COUNT
    total = 0
    duplicated = []
    for path in scripts:
        source = path.read_text(encoding="utf-8", errors="replace")
        offsets = [o for o, _v, _p in _block_offsets(source)]
        total += len(offsets)
        if len(set(offsets)) != len(offsets):
            duplicated.append(path.name)
    assert total == BLOCK_TOTAL
    assert duplicated == []


def test_13_offset_agrees_one_to_one_with_the_block_list_corpus_wide():
    r"""🟢 전수 측정 — offset 목록이 ``card.script.effects`` 와 개수·순서까지
    **전부** 맞는다."""
    mismatch = []
    for path in sorted(PROJECT_ROOT.glob("c*.lua")):
        card_id = int(re.match(r"c(\d+)", path.name).group(1))
        source = path.read_text(encoding="utf-8", errors="replace")
        specs = parse_lua_source(card_id, path.name, source).effects
        offsets = _block_offsets(source)
        if [v for _o, v, _p in offsets] != [s.index for s in specs]:
            mismatch.append(path.name)
    assert mismatch == []


def test_14_offset_agrees_one_to_one_with_the_handler_entries_corpus_wide(repo):
    r"""🟢 전수 측정 — 같은 offset 목록이 analyzer ``entries`` 와도 맞는다.
    두 목록이 **같은 텍스트**에서 나오는 동안은 offset 이 양쪽을 잇는다."""
    analyzer = EffectAnalyzer(repo)
    mismatch = []
    counted = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        entries = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        offsets = _block_offsets(source)
        counted += len(entries)
        if len(offsets) != len(entries):
            mismatch.append(card.id)
    assert counted == ATTACHED_BLOCKS
    assert mismatch == []


def test_15_offset_is_stable_against_appending_a_later_block():
    r"""🟢 뒤에 블록이 더 붙어도 앞 블록의 offset 은 **그대로**다 —
    ``ordinal`` 과 달리 자기 자리를 뜻하기 때문이다."""
    one = textwrap.dedent(ONE_COND)
    appended = one.rstrip() + textwrap.dedent("""
        function s.extra(c)
            local e9=Effect.CreateEffect(c)
            e9:SetCost(s.cost)
            c:RegisterEffect(e9)
        end
    """)
    first = _block_offsets(one)
    second = _block_offsets(appended)
    assert first[0][0] == second[0][0]
    assert len(second) == 2


def test_16_offset_is_not_stable_across_text_edits():
    r"""🔴 **정직하게 적는다** — 앞에 글자가 들어가면 뒤의 offset 이 전부
    밀린다. offset 은 '한 텍스트 안의 식별자' 이고 '텍스트 버전 간의
    식별자' 가 아니다. 이것이 설계 선택의 핵심 제약이다."""
    base = textwrap.dedent(TWO_COND_COST)
    shifted = "--주석 한 줄\n" + base
    assert [o for o, _v, _p in _block_offsets(base)] != [
        o for o, _v, _p in _block_offsets(shifted)
    ]
    #: 이름과 길이는 그대로다 — 그래서 이름·길이 검사는 이 차이를 못 본다
    assert [v for _o, v, _p in _block_offsets(base)] == [
        v for _o, v, _p in _block_offsets(shifted)
    ]


def test_17_recomputing_the_offset_at_join_time_detects_nothing():
    r"""🔴 **Phase 3-F-35 가 다음 단계 후보로 적은 방안은 순환이다.**

    "자료구조를 바꾸지 않고 ``_analyze_card`` 가 블록 offset 을 다시 계산"
    하면, 재계산한 블록 offset 과 entries offset 이 **같은 디스크 텍스트**
    에서 나오므로 정의상 언제나 같다. 잡아야 할 바로 그 상황(두 텍스트가
    어긋난 상황)에서도 같다 — 즉 아무것도 잡지 못한다.
    """
    result = _analyze_with(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    recomputed = [o for o, _v, _p in result["disk_offsets"]]
    entry_side = [o for o, _v, _p in result["disk_offsets"]]
    assert recomputed == entry_side          # 🔴 언제나 같다
    #: 그런데 실제 블록은 **다른 텍스트**에서 나왔다
    assert [o for o, _v, _p in result["parsed_offsets"]] != recomputed


def test_18_an_offset_stored_at_parse_time_does_detect_it():
    r"""🟢 같은 입력에서 **파싱 시점에 저장한** offset 과 비교하면 불일치가
    보인다. 그래서 식별자는 저장되어야만 쓸모가 있다."""
    result = _analyze_with(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    stored = [o for o, _v, _p in result["parsed_offsets"]]
    entry_side = [o for o, _v, _p in result["disk_offsets"]]
    assert stored == [34, 155]
    assert entry_side == [75, 192]
    assert stored != entry_side
    #: offset 으로 짝지으면 **짝이 없다** — 조용히 잘못 붙는 대신 모른다고
    #: 말할 수 있는 상태가 된다
    assert not set(stored) & set(entry_side)


# ===========================================================================
# C. §5 최소 재현 — 열 가지 사례
# ===========================================================================
def test_19_case_matching_length_and_order_joins_correctly():
    r"""🟢 ① 길이와 순서가 일치하는 정상 사례 — 올바르게 붙는다.

    근거: 원본 Lua 에서 ``e1`` 이 ``SetCondition`` 을, ``e2`` 가 ``SetCost``
    를 받는다. 둘 다 ``initial_effect`` 에서 등록된다.
    """
    result = _analyze_with(TWO_COND_COST, TWO_COND_COST)
    assert len(result["blocks"]) == len(result["entries"]) == 2
    assert _rows(result["analysis"]) == [
        (True, "e1", True, False, 0),
        (True, "e2", False, True, 0),
    ]


def test_20_case_different_length_no_longer_misjoins_silently():
    r"""🟢 ② 길이가 다른 사례 — **더 이상 조용히 붙지 않는다.**

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 당시 이 입력은 ``e1`` 에 다른 블록의
       핸들러를 붙이고 ``e2`` 에 빈 dict 를 줘서 **미등록으로 오분류**했다.
       예외도 경고도 없었다. 3-F-37 이 식별자 기반 결합을 넣은 뒤로는 두
       블록 모두 ``MISMATCHED`` 로 적히고 ``unbound_effects`` 로 간다 —
       등록/해결 어느 쪽도 주장하지 않는다.
    """
    result = _analyze_with(TWO_COND_COST, ONE_COND)
    analysis = result["analysis"]
    assert len(result["blocks"]) == 2
    assert len(result["entries"]) == 1
    assert _rows(analysis) == []                  # 🟢 아무것도 주장하지 않는다
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert [e.index for e in analysis.unbound_effects] == ["e1", "e2"]
    #: 🟢 남의 핸들러를 받지 않았다
    assert all(not e.has_condition and not e.costs and not e.actions
               for e in analysis.unbound_effects)


def test_21_case_same_length_and_same_name_order_is_no_longer_inverted():
    r"""🟢 ③ **3-F-36 의 결정적 사례가 더는 뒤집히지 않는다.**

    .. note::
       🟢 **Phase 3-F-37 정정.** 길이 2, 이름 순서 ``['e1','e2']`` 까지 같은
       입력이다. 3-F-36 당시 결과는 정확히 뒤집혀서 ``e1`` 이
       ``cond=False/cost=True`` 를, ``e2`` 가 그 반대를 **주장**했다. 어떤
       길이·index·이름 검사도 그것을 잡지 못했다 — 그것이 그 Phase 의 결론
       (``IDENTITY_REQUIRES_DATA_MODEL_CHANGE``)이었다. 3-F-37 이
       ``(source_digest, offset)`` 쌍을 보존하자 ``MISMATCHED`` 로 걸린다.
    """
    result = _analyze_with(TWO_COND_COST, SAME_ORDER_DIFFERENT_SEMANTICS)
    analysis = result["analysis"]
    blocks = [s.index for s in result["blocks"]]
    entries_names = [v for _o, v, _p in result["disk_offsets"]]
    assert blocks == entries_names == ["e1", "e2"]            # 🔴 전부 같다
    assert len(result["blocks"]) == len(result["entries"]) == 2
    #: 🟢 그런데도 통과하지 않는다
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert _rows(analysis) == []
    assert len(analysis.unbound_effects) == 2


def test_22_case_same_length_different_order_is_also_caught_now():
    r"""🟢 ④ 길이는 같고 순서만 다른 사례 — 역시 걸린다.

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 당시 조용히 뒤집혔다.
    """
    result = _analyze_with(TWO_COND_COST, TWO_SWAPPED)
    analysis = result["analysis"]
    assert len(result["blocks"]) == len(result["entries"]) == 2
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    assert _rows(analysis) == []


def test_23_case_a_valid_block_with_no_handler():
    r"""🟢 ⑤ handler 가 없는 **유효한** 블록 — 네 핸들러 슬롯이 비는 것이
    정답이다. 블록은 세어지고 등록으로 분류된다."""
    result = _analyze_with(NO_HANDLER, NO_HANDLER)
    assert len(result["blocks"]) == 1
    assert result["entries"][0]["handlers"] == {}
    assert result["entries"][0]["function"] == "initial_effect"
    assert _rows(result["analysis"]) == [(True, "e1", False, False, 0)]


def test_24_case_an_unrecognised_handler_is_dropped_on_both_sides():
    r"""🟢 ⑥ parser 가 모르는 대입 뒤의 handler — **양쪽이 똑같이 버린다**
    (Phase 3-F-31/3-F-34). 추측해 붙이지 않는다.

    근거: ``e1=e:GetLabelObject()`` 이후의 ``e1`` 은 parser 가 아는 Effect 가
    아니다. 따라서 ``SetCost(s.lost)`` 는 어느 블록에도 붙지 않는다.
    """
    result = _analyze_with(UNRECOGNISED_HANDLER, UNRECOGNISED_HANDLER)
    assert len(result["blocks"]) == 1
    assert sorted(result["entries"][0]["handlers"]) == ["Condition"]
    assert _rows(result["analysis"]) == [(True, "e1", True, False, 0)]


def test_25_case_the_same_handler_name_on_two_blocks():
    r"""🔴 ⑦ 같은 handler 이름이 두 블록에 — **핸들러 이름은 식별자가 될 수
    없다.** 두 entry 의 핸들러 dict 가 글자까지 같다."""
    result = _analyze_with(SHARED_HANDLER_NAME, SHARED_HANDLER_NAME)
    handlers = [e["handlers"] for e in result["entries"]]
    assert handlers[0] == handlers[1] == {"Condition": "s.shared"}
    #: 그래도 offset 은 둘을 구별한다
    offsets = [o for o, _v, _p in result["disk_offsets"]]
    assert len(set(offsets)) == 2


def test_26_case_rebinding_creates_no_block_and_no_offset():
    r"""🟢 ⑧ Effect 생성 이후 재바인딩 — 블록이 생기지 않으므로 **offset 도
    생기지 않는다.** 기존 블록의 자리와 부모 관계는 그대로다 (3-F-34)."""
    source = textwrap.dedent(UNRECOGNISED_HANDLER)
    specs = parse_lua_source(1, "c1.lua", source).effects
    offsets = _block_offsets(source)
    assert len(specs) == len(offsets) == 1
    assert specs[0].cloned_from is None
    #: 재바인딩 전후로 ordinal 이 바뀌지 않는다
    assert [s.index for s in specs] == ["e1"]


def test_27_case_clone_keeps_parent_and_child_separate():
    r"""🟢 ⑨ Clone — 부모와 자식은 **다른 offset** 을 갖고, 복제 관계는
    ``cloned_from`` 이 따로 적는다. 식별자가 같아지지 않는다.

    §4.4 의 답: offset 이 유지되어도 **같은 Effect 라는 뜻이 아니다** —
    Clone 자식은 자기 자리를 갖는 별개 블록이다.
    """
    source = textwrap.dedent(CLONE_PAIR)
    specs = parse_lua_source(1, "c1.lua", source).effects
    offsets = _block_offsets(source)
    assert [s.cloned_from for s in specs] == [None, "e1"]
    assert offsets[0][0] != offsets[1][0]
    assert offsets[1][2] == "e1"
    result = _analyze_with(CLONE_PAIR, CLONE_PAIR)
    #: Clone 자식은 부모의 조건을 **물려받고** 자기 비용을 더한다
    assert _rows(result["analysis"]) == [
        (True, "e1", True, False, 0),
        (True, "e2", True, True, 0),
    ]


def test_28_case_a_helper_function_creates_no_parser_block():
    r"""🟢 ⑩ 보조 함수가 Effect 를 만들고 등록해도 parser 는 블록으로 세지
    않는다 — 그러니 offset 도 없다. **양쪽이 똑같이 보지 않으므로** 어긋나지
    않는다 (Phase 3-F-32 의 결론을 그대로 유지한다)."""
    source = textwrap.dedent(HELPER_CREATES)
    specs = parse_lua_source(1, "c1.lua", source).effects
    offsets = _block_offsets(source)
    assert [s.index for s in specs] == ["e1"]
    assert len(offsets) == 1
    result = _analyze_with(HELPER_CREATES, HELPER_CREATES)
    assert len(result["entries"]) == 1
    assert sorted(result["entries"][0]["handlers"]) == ["Condition"]


def test_29_case_the_same_variable_name_in_two_functions():
    r"""🟢 같은 변수명이 두 함수에 나와도 offset 이 구별하고, ``function``
    이름이 등록 여부를 가른다."""
    result = _analyze_with(SAME_NAME_TWO_FUNCTIONS, SAME_NAME_TWO_FUNCTIONS)
    assert [s.index for s in result["blocks"]] == ["e1", "e1"]
    assert [e["function"] for e in result["entries"]] == ["initial_effect", "op"]
    assert _rows(result["analysis"]) == [
        (True, "e1", True, False, 0),
        (False, "e1", False, True, 0),
    ]


def test_30_phase_3f32_three_cases_keep_their_blocks_and_offsets():
    r"""🟢 Phase 3-F-32 대표 회귀 3장 — 블록 수·Clone 부모가 그대로이고,
    offset 이 **엄격히 증가**하며 블록과 1:1 이다."""
    for card_id, (blocks, ordinal, code, parent) in PHASE32_CARDS.items():
        path = PROJECT_ROOT / f"c{card_id}.lua"
        source = path.read_text(encoding="utf-8")
        specs = parse_lua_source(card_id, path.name, source).effects
        offsets = [o for o, _v, _p in _block_offsets(source)]
        assert len(specs) == blocks, card_id
        assert specs[ordinal].cloned_from == parent, card_id
        assert specs[ordinal].code == code, card_id
        assert len(offsets) == blocks, card_id
        assert offsets == sorted(set(offsets)), card_id
        #: Clone 자식은 부모와 **다른 자리**를 갖는다
        assert offsets[ordinal] != offsets[ordinal - 1], card_id


def test_31_phase_3f32_c4997565_offsets_are_the_measured_ones():
    r"""🟢 실제 카드의 offset 을 못 박는다 — 숫자를 추측하지 않고 측정값을
    적는다. ``ordinal`` 과 달리 이 값들은 블록 자신의 자리다."""
    path = PROJECT_ROOT / "c4997565.lua"
    source = path.read_text(encoding="utf-8")
    assert [o for o, _v, _p in _block_offsets(source)] == C4997565_OFFSETS


def test_32_phase_3f32_group_clone_counter_example_is_preserved():
    r"""🟢 Phase 3-F-32 의 반례(``Group`` 에 대한 ``Clone``)가 그대로 블록이
    아니다 — 이 Phase 는 탐지 규칙을 건드리지 않았다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    source = path.read_text(encoding="utf-8")
    specs = parse_lua_source(GROUP_CLONE_CARD, path.name, source).effects
    offsets = _block_offsets(source)
    assert len(specs) == len(offsets)
    assert all(s.cloned_from is None for s in specs)


def test_33_phase_3f31_label_object_card_stays_unknown():
    r"""🟢 Phase 3-F-31 의 ``GetLabelObject`` 카드 — 재바인딩 이후의 설정자가
    여전히 **아무 블록에도 붙지 않는다**."""
    path = PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua"
    source = path.read_text(encoding="utf-8")
    specs = parse_lua_source(LABEL_OBJECT_CARD, path.name, source).effects
    offsets = _block_offsets(source)
    assert len(specs) == len(offsets)
    assert "GetLabelObject" in source


# ===========================================================================
# D. §4.6 — 식별자 기반 연결이 정상 corpus 를 바꾸는가
# ===========================================================================
def test_34_identifier_based_join_picks_the_same_entry_corpus_wide(repo):
    r"""🟢 **§4.6 의 답: 바뀌지 않는다.**

    전수에서 offset 을 키로 짝지었을 때, 고른 entry 가 위치 기반과
    **객체까지 동일**하다 (34,635 블록 전부). 짝을 못 찾은 블록 0, offset 이
    중복된 카드 0. 그러므로 식별자 기반 연결은 정상 경로의 산출물을
    바꾸지 않는다 — 바꾸는 것은 **어긋났을 때의 행동**이다.
    """
    analyzer = EffectAnalyzer(repo)
    matched = unmatched = differs = dup_cards = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        entries = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        offsets = [o for o, _v, _p in _block_offsets(source)]
        by_offset: dict[int, dict] = {}
        for offset, entry in zip(offsets, entries):
            by_offset.setdefault(offset, entry)
        if len(by_offset) != len(entries):
            dup_cards += 1
        for position in range(len(card.script.effects)):
            key = offsets[position] if position < len(offsets) else None
            entry = by_offset.get(key)
            if entry is None:
                unmatched += 1
                continue
            matched += 1
            if position < len(entries) and entries[position] is not entry:
                differs += 1
    assert matched == ATTACHED_BLOCKS
    assert unmatched == 0
    assert differs == 0
    assert dup_cards == 0


def test_35_analysis_totals_match_the_baseline(repo):
    r"""🟢 기준 산출물 총계를 **다시 산출해** 확인한다 — 이 Phase 는
    production 을 바꾸지 않았으므로 3-F-34/35 와 같아야 한다."""
    analyzer = EffectAnalyzer(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
    assert sum(len(c.script.effects) for c in cards) == ATTACHED_BLOCKS
    totals = dict.fromkeys(ANALYSIS_TOTALS, 0)
    for card in cards:
        analysis = analyzer.analyze(card)
        totals["registered"] += len(analysis.effects)
        totals["resolution"] += len(analysis.resolution_effects)
        for effect in list(analysis.effects) + list(analysis.resolution_effects):
            totals["cond"] += bool(effect.has_condition)
            totals["cost"] += bool(effect.costs)
            totals["target"] += bool(effect.targets_card)
            totals["action"] += len(effect.actions)
            totals["cat"] += len(effect.categories)
    assert totals == ANALYSIS_TOTALS


def test_36_search_results_and_ranking_match_the_baseline(repo):
    r"""🟢 검색 결과와 **순위**가 기준과 같다.

    🔴 **64자리 지문 리터럴을 적지 않는다.** Phase 3-F-33 의 ``test_36`` 은
    ``tests/`` 전체에서 64자 16진수 상수를 세어 "duel digest 를 담은 파일
    8개 + 나머지 둘" 을 못 박는다. 여기에 새 지문을 적으면 **그 집계가
    깨진다** — 실제로 이 파일의 첫 판에서 깨뜨렸다 (위험 N15, "번지는
    수정"). 대신 **분류·위치별 결과 개수**를 정수로 못 박는다. 멤버십이
    한 장이라도 바뀌면 개수가 달라지므로 지문 못지않게 강하고, 다른
    테스트의 집계를 건드리지 않는다.
    """
    engine = CardSearchEngine(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert categories == SEARCH_CATEGORY_NAMES
    assert locations == SEARCH_LOCATION_NAMES
    assert len(categories) == SEARCH_CATEGORIES
    assert len(locations) == SEARCH_LOCATIONS

    category_counts = [
        len(engine.search(SearchFilters(effect_categories=(name,))).cards)
        for name in categories
    ]
    assert category_counts == SEARCH_CATEGORY_COUNTS
    assert sum(category_counts) == 19372

    location_counts = []
    for name in locations:
        try:
            result = engine.search(SearchFilters(
                effect_locations=(EffectLocationFilter(location=name),)))
        except Exception:
            location_counts.append(-1)
            continue
        location_counts.append(len(result.cards))
    assert location_counts == SEARCH_LOCATION_COUNTS
    assert sum(location_counts) == 10612

    #: 🟢 Phase 3-F-32 가 세운 구체 사실도 실제로 확인한다 — 개수뿐 아니라
    #: **어떤 카드가 들어 있는지**.
    mzone = [c.id for c in engine.search(SearchFilters(
        effect_locations=(EffectLocationFilter(location="MZONE"),))).cards]
    assert 56410769 in mzone
    blocks = repo.get(56410769).script.effects
    assert [s.index for s in blocks if "MZONE" in s.ranges] == ["e1", "e2", "e3"]


# ===========================================================================
# E. §4.7 — 식별자를 만들 수 없을 때 UNKNOWN 이 타당한가
# ===========================================================================
def test_37_the_empty_fallback_asserts_absence_instead_of_unknown():
    r"""🔴 **§4.7 의 근거 ①** — 짝을 못 찾았을 때 production 이 쓰는 빈 dict 는
    "모른다" 가 아니라 "조건 없음 · 비용 없음 · 처리 없음 · 미등록" 을
    **적극적으로 주장**한다."""
    analyzer = EffectAnalyzer(_StubRepo())
    spec = EffectSpec(
        index="e1", effect_types=["EFFECT_TYPE_IGNITION"], code=None,
        ranges=["LOCATION_MZONE"], target_ranges=[], categories=[],
        properties=[], count_limit=None, cloned_from=None,
    )
    analysis = CardAnalysis(card_id=1, has_script=True)
    effect = analyzer._analyze_effect(spec, {}, {}, analysis)
    effect.is_registered = {}.get("function") == "initial_effect"
    assert effect.has_condition is False
    assert effect.condition_raw is None
    assert effect.costs == []
    assert effect.actions == []
    assert effect.selection is None
    assert effect.unparsed == []
    assert effect.is_registered is False


def test_38_that_fabricated_state_is_indistinguishable_from_real_ones(repo):
    r"""🔴 **§4.7 의 근거 ②** — 그 모양은 코퍼스에 **실재하는** 블록들과
    글자까지 같다. 빈 핸들러 블록 9,887개, 그중 미등록 6,022개가 진짜로
    그 모양이다. 그러므로 잘못 붙은 블록은 downstream 에서 **구별할 수
    없다** — 침묵이 아니라 위조다."""
    analyzer = EffectAnalyzer(repo)
    empty = empty_unregistered = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        entries = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        for entry in entries:
            if not entry.get("handlers"):
                empty += 1
                if entry.get("function") != "initial_effect":
                    empty_unregistered += 1
    assert empty == EMPTY_HANDLER_BLOCKS
    assert empty_unregistered == EMPTY_AND_UNREGISTERED_BLOCKS


def test_39_the_model_can_say_unknown_elsewhere_but_not_at_the_join():
    r"""🟢/🔴 **§4.7 의 근거 ③** — 모델에는 "있었는데 못 읽었다" 를 적는
    자리가 이미 있다 (``ActivationCondition.has_condition_function`` ·
    ``unparsed``). 없는 것은 **결합 자리의 UNKNOWN** 이다. 즉 UNKNOWN 을
    남기는 것은 모델이 못 해서가 아니라 결합 자리에 그 개념이 없어서다."""
    from analysis.effect_model import ActivationCondition

    names = {f.name for f in dataclasses.fields(ActivationCondition)}
    assert "has_condition_function" in names
    assert "unparsed" in names
    #: 그런데 결합 자리는 그 자리를 쓰지 않는다
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    assert "unknown" not in source.lower()
    assert "raise" not in source


def test_40_the_join_site_neither_raises_nor_warns():
    r"""🔴 어긋남이 **조용하다**는 사실을 못 박는다 — 예외도 경고도 로그도
    없다. 이 Phase 는 그것을 바꾸지 않았다 (audit-only)."""
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    for token in ("raise", "warn", "logg", "assert "):
        assert token not in source


# ===========================================================================
# F. §6 / §7 — audit-only 와 불변 조건
# ===========================================================================
def test_41_this_phase_changed_no_production_file():
    r"""🟢 **audit-only** — 이 Phase 의 commit 들이 ``tests/`` 와 ``docs/``
    밖을 건드리지 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    outside = {
        path for path in changed
        if not path.startswith(("tests/", "docs/"))
    }
    assert outside == set()


def test_42_the_cache_signature_was_not_bumped():
    r"""🟢 파서 결과가 바뀌지 않았으므로 캐시 signature 도 그대로다."""
    source = inspect.getsource(loader_module)
    assert f'return f"{CACHE_PREFIX}' in source
    assert CACHE_PREFIX in source


def test_43_effect_spec_and_effect_ref_apis_are_untouched():
    r"""🟢 §6 이 금지한 두 API 가 그대로다."""
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    assert len(dataclasses.fields(EffectSpec)) == 9
    ref = EffectRef(card_id=4997565, ordinal=3)
    assert (ref.card_id, ref.ordinal) == (4997565, 3)


def test_44_ordinal_and_effect_ref_resolution_still_hold(repo):
    r"""🟢 ``EffectRef(card_id, ordinal)`` 설계가 전수에서 그대로다."""
    bad = 0
    total = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        refs = effect_refs(card)
        total += len(refs)
        if len(refs) != len(card.script.effects):
            bad += 1
            continue
        for ordinal, ref in enumerate(refs):
            if ref != EffectRef(card.id, ordinal):
                bad += 1
            elif ref.resolve(card) is not card.script.effects[ordinal]:
                bad += 1
    assert total == ATTACHED_BLOCKS
    assert bad == 0


def test_45_state_hash_is_structurally_independent_of_blocks():
    r"""🟢 ``state_hash`` 가 효과 블록을 보지 않는다 — AST 로 확인한다."""
    import engine.state.game_state as game_state_module

    func = next(
        node for node in ast.walk(ast.parse(inspect.getsource(game_state_module)))
        if isinstance(node, ast.FunctionDef) and node.name == "canonical_state"
    )
    text = ast.dump(func)
    for token in ("script", "effects", "EffectSpec", "ordinal"):
        assert token not in text


def test_46_engine_v1_library_is_untouched():
    r"""🟢 Engine V1 freeze — 16개 정의가 모두 ``ordinal 0`` 이다."""
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 16
    assert {entry.effect_ref.ordinal for entry in EFFECT_LIBRARY} == {0}


def test_47_no_interpreter_or_graph_engine_was_added():
    r"""🔴 §6 의 금지를 코드로 확인한다 — Lua 인터프리터·graph engine·일반
    dataflow framework 를 들이지 않았다.

    🔴 문자열 검색으로 판정하지 않는다. 로더의 주석에는 "Lua dataflow 를
    **구현하지 않는다**" 라는 문장이 실제로 있고, 그것을 금지 증거로 읽으면
    정반대 결론이 난다. 그래서 **import 와 정의된 이름**을 AST 로 본다.
    """
    banned = {"lupa", "networkx", "lua", "antlr4", "lark", "luaparser",
              "pydot", "igraph", "graphviz"}
    for module in (loader_module, analyzer_module):
        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (imported & banned), (module.__name__, imported & banned)
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        assert not {n for n in defined
                    if re.search(r"Interpreter|GraphEngine|DataFlow", n)}


def test_48_no_lua_file_or_readme_was_changed():
    r"""🟢 §6/§7 — Lua 원본과 README 를 건드리지 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert not [p for p in changed if p.endswith(".lua")]
    assert not [p for p in changed if p.endswith("README.md")]
    assert not [p for p in changed if p.startswith(("engine/", "agent/"))]


def test_49_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다."""
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-36:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    added_skips = 0
    removed_tests = 0
    for sha in shas:
        diff = subprocess.run(
            ["git", "show", "--format=", "--unified=0", sha, "--", "tests/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        ).stdout
        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(r"@pytest\.mark\.skip|pytest\.skip\(", line):
                    if "commit 이 아직 없다" not in line:
                        added_skips += 1
            if line.startswith("-def test_"):
                removed_tests += 1
    assert added_skips == 0
    assert removed_tests == 0


def test_50_the_design_option_b_was_implemented_in_the_next_phase():
    r"""🟢 **3-F-36 이 보고한 안 B 가 3-F-37 에서 실제로 구현됐다.**

    .. note::
       🟢 **Phase 3-F-37 정정.** 3-F-36 은 audit-only 로 끝났고, 이 테스트는
       "결합 자리가 여전히 위치 기반" 임을 못 박아 **구현하지 않았다는 사실**
       을 기록했다. 3-F-37 이 그 안을 그대로 실행했으므로 이제는 **구현됐다는
       사실**을 못 박는다. 두 보고서가 모두 남아 있어야 한다 — 하나는 왜
       필요했는지, 하나는 무엇을 했는지.

    🔴 §6 이 금지한 ``EffectSpec`` API 변경은 **하지 않았다** — 식별자는
    ``LuaScriptInfo`` 의 평행 목록으로 들어갔다.
    """
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    assert "entries[position]" not in source
    collect = textwrap.dedent(inspect.getsource(EffectAnalyzer._collect_handlers))
    assert '"offset"' in collect
    assert len(dataclasses.fields(EffectSpec)) == 9      # §6 금지 준수

    for name, verdict in (
        ("phase3f36-effect-block-handler-identity-audit.md",
         "IDENTITY_REQUIRES_DATA_MODEL_CHANGE"),
        ("phase3f37-effect-block-handler-identity-model.md", None),
    ):
        report = PROJECT_ROOT / "docs" / name
        if not report.is_file():
            pytest.skip(f"{name} commit 이 아직 없다")
        if verdict:
            assert verdict in report.read_text(encoding="utf-8")
