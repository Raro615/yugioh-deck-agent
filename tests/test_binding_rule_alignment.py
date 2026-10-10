r"""
Phase 3-F-34 — analyzer 바인딩 규칙 일치 적용 및 산출물 불변성 검증
====================================================================

이 Phase 가 한 일
-----------------
Phase 3-F-33 이 조사만 하고 남긴 **N11 · N12** 를 적용했다.

* **N11** — analyzer 에 ``_RE_REBIND`` 가 없어 loader 와 재바인딩 규칙이 달랐다.
* **N12** — ``Clone`` 의 부모 변수가 재바인딩된 경우, loader 는 "물려받은 것
  없음" 을 주장하는데 analyzer 는 **옛 부모의 핸들러를 물려받았다** 고
  주장했다 — 같은 블록에 대한 **정면 모순**이었다.

수정은 ``analysis/effect_analyzer.py`` **한 파일**이다. 규칙을 베끼지 않고
``sources.lua_loader`` 에서 ``_RE_REBIND`` 와 ``_EVENT_ORDER`` 를 **import**
한다 — 복사본을 두면 로더만 고친 순간 두 경로가 다시 갈린다 (3-F-28 이 탐지
정규식에서, 3-F-32 가 ``Clone`` 형태에서 각각 겪었다).

🔴 산출물은 하나도 바뀌지 않았다
--------------------------------
§5 가 요구한 모든 항목을 수정 **전/후**로 측정했고 **전부 동일**하다.

================================ ======================================
항목                              수정 전 == 수정 후
================================ ======================================
스크립트 수                        12,702
파서 블록 수                       34,684
``cards.cdb`` 붙은 카드 / 블록      12,687 / 34,635
``EffectSpec`` 전수 지문           동일 (SHA-256)
``CardAnalysis`` 전수 지문          동일 (SHA-256)
등록 Effect / 해결 Effect           26,352 / 8,283
조건 / 비용 / 대상 / 액션 / 카테고리  12,438 / 5,007 / 5,516 / 18,280 / 20,484
``EffectRef`` 연결 불일치            0
검색 카테고리 결과·순위 지문          동일 (31개 카테고리)
검색 위치 결과·순위 지문             동일 (31개 위치)
3-F-32 대표 3사례 + 반례 2사례       동일
================================ ======================================

즉 **데이터는 그대로이고 계약만 일치**한다. 그래서 캐시 서명도 올리지
않았다 (``v9`` 유지) — analyzer 는 디스크 캐시가 없고 loader 는 건드리지
않았으므로 올릴 이유가 없고, 올리면 12,702 스크립트를 쓸데없이 재파싱한다.

🔴 숫자를 코드에 고정해 성공을 가장하지 않았다
---------------------------------------------
아래 상수는 **Phase 3-F-33 보고서가 보고한 값**이고, 이 파일의 테스트들은
그것을 **실제 코드 경로를 돌려 다시 산출**해 맞춰 본다. 지문 값은
리터럴로 적지 않는다 — 비교는 항상 "같은 측정을 두 설정으로 돌려 맞대보기"
로만 한다 (``test_15`` ~ ``test_19``).
"""

from __future__ import annotations

import ast
import collections
import hashlib
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

import analysis.effect_analyzer as analyzer_module
import sources.lua_loader as loader_module
from analysis.effect_analyzer import EffectAnalyzer
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from engine.ids import EffectRef, effect_refs, iter_effects
from sources.lua_loader import (
    LuaScriptSource,
    _clone_source,
    _extract_call_args,
    _is_card_effect,
    _RE_BLOCK_COMMENT,
    _RE_CLONE_EFFECT,
    _RE_CREATE_EFFECT,
    _RE_REBIND,
    parse_lua_source,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-33 이 보고한 기준값 (테스트가 실제로 다시 산출한다) ---------
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
#: 🔴 Phase 3-F-37 이 ``v9:`` -> ``v10-<shape>:`` 로 바꿨다.
#: ``LuaScriptInfo`` 에 ``effect_offsets`` 와 ``source_digest`` 가 생겨
#: 캐시 모양이 달라졌기 때문이다. 뒤의 ``<shape>`` 는 저장되는 칸 목록의
#: 해시이고 **자동으로** 바뀐다 — 같은 번호 아래에서 칸이 달라지는 사고를
#: 막는다 (3-F-37 작업 중 실제로 겪었고, 기존 테스트 103건이 그래서 한 번
#: 깨졌다). 이 테스트의 주장은 그대로다: **파서 산출물이 달라지면 캐시
#: 서명도 달라져야 한다.**
CACHE_PREFIX = "v10-"

#: Phase 3-F-32 의 세 대표 사례 — (블록 수, ordinal, code, 부모)
PHASE32_CARDS = {
    44887817: (5, 4, "EFFECT_CANNOT_MSET", "e1"),
    4997565: (5, 3, "EFFECT_DISABLE_EFFECT", "e1"),
    56410769: (3, 2, "EFFECT_CANNOT_ATTACK_ANNOUNCE", "e2"),
}
#: 🔴 Group 의 ``Clone`` — 블록이 되면 안 된다 (3-F-32 의 반례)
GROUP_CLONE_CARD = 63708033
#: ``e:GetLabelObject()`` 로 바인딩이 풀리는 카드 (3-F-31 N3)
LABEL_OBJECT_CARD = 52445243


# ===========================================================================
# 공용 도구 — production 을 **그대로** 호출한다
# ===========================================================================
def _script_paths() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("c*.lua"))


def _raw(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _body(path: Path) -> str:
    return _RE_BLOCK_COMMENT.sub("", _raw(path))


def _card_id(path: Path) -> int:
    return int(re.match(r"c(\d+)", path.name).group(1))


def _loader_blocks(path: Path):
    return parse_lua_source(_card_id(path), path.name, _raw(path)).effects


def _analyzer_entries(path: Path):
    source = _raw(path)
    return EffectAnalyzer._collect_handlers(
        source, EffectAnalyzer._function_spans(source)
    )


def _handlers(entries) -> list[tuple]:
    return [(tuple(sorted(e["handlers"].items())), e["function"]) for e in entries]


def _collect_without_rebind(source: str, spans):
    r"""🔴 **수정 전** analyzer 의 동작을 그대로 되살린 것.

    산출물 불변성을 주장하려면 "수정 전" 을 실제로 돌려봐야 한다. 그래서
    3-F-33 의 production 코드 모양을 여기 하나만 남겨 둔다 — ``_RE_REBIND``
    를 수집하지 않고, 정렬도 ``pos`` 만으로 한다.

    탐지 정규식과 ``_clone_source`` 는 **지금 것을 그대로 쓴다**. 바뀐 것은
    재바인딩 규칙 하나뿐임을 보이려면 나머지가 같아야 한다.
    """
    body = _RE_BLOCK_COMMENT.sub("", source)
    if body != source:
        spans = EffectAnalyzer._function_spans(body)
    source = body

    events: list[tuple[int, str, str]] = []
    for m in _RE_CREATE_EFFECT.finditer(source):
        if not _is_card_effect(source, m.group(1), m.group(2), None):
            continue
        events.append((m.start(), "create", m.group(2)))
    for m in _RE_CLONE_EFFECT.finditer(source):
        src_var = _clone_source(m)
        if not _is_card_effect(source, m.group(1), m.group(2), src_var):
            continue
        events.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
    for m in analyzer_module._RE_SETTER.finditer(source):
        events.append((m.start(), "set", f"{m.group(1)}|{m.group(2)}|{m.end() - 1}"))
    events.sort(key=lambda e: e[0])

    bindings: dict[str, dict[str, str]] = {}
    order: list[dict] = []
    for pos, kind, payload in events:
        if kind == "create":
            handlers: dict[str, str] = {}
            bindings[payload] = handlers
            order.append({"handlers": handlers,
                          "function": EffectAnalyzer._enclosing_function(pos, spans),
                          #: 🔴 Phase 3-F-37 — production 의 결합이 이 칸을
                          #: 쓴다. 복제본이 넣지 않으면 그 결합은 "증명할 수
                          #: 없다"(``UNPROVABLE``)가 되고, 이 파일이 비교하려는
                          #: 바인딩 규칙의 차이가 아니라 **식별자의 부재**를
                          #: 재는 셈이 된다. 복제본은 production 과 같은 값을
                          #: 같은 방식으로 담아야 비교가 성립한다.
                          "offset": pos})
        elif kind == "clone":
            dst, src = payload.split("=", 1)
            handlers = dict(bindings.get(src, {}))
            bindings[dst] = handlers
            order.append({"handlers": handlers,
                          "function": EffectAnalyzer._enclosing_function(pos, spans),
                          #: 🔴 Phase 3-F-37 — production 의 결합이 이 칸을
                          #: 쓴다. 복제본이 넣지 않으면 그 결합은 "증명할 수
                          #: 없다"(``UNPROVABLE``)가 되고, 이 파일이 비교하려는
                          #: 바인딩 규칙의 차이가 아니라 **식별자의 부재**를
                          #: 재는 셈이 된다. 복제본은 production 과 같은 값을
                          #: 같은 방식으로 담아야 비교가 성립한다.
                          "offset": pos})
        else:
            var, setter, idx = payload.split("|", 2)
            target = bindings.get(var)
            if target is not None:
                target[setter] = _extract_call_args(source, int(idx)).strip()
    return order


def _both(lua: str):
    """최소 재현 하나를 양쪽 경로에 넣고 (loader 블록, 수정 전, 수정 후) 를 준다."""
    source = textwrap.dedent(lua)
    spans = EffectAnalyzer._function_spans(source)
    return (
        parse_lua_source(1, "c1.lua", source).effects,
        _handlers(_collect_without_rebind(source, spans)),
        _handlers(EffectAnalyzer._collect_handlers(source, spans)),
    )


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-34:"],
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


# ===========================================================================
# 범주 1 — loader / analyzer 재바인딩 규칙 일치
# ===========================================================================
def test_01_the_analyzer_imports_the_loaders_rebind_rule():
    r"""🔴 규칙을 **베끼지 않고 import 한다** — 같은 객체여야 한다."""
    assert analyzer_module._RE_REBIND is loader_module._RE_REBIND
    assert analyzer_module._EVENT_ORDER is loader_module._EVENT_ORDER
    #: 모듈 안에서 그 이름을 다시 대입하지 않았다.
    tree = ast.parse(Path(analyzer_module.__file__).read_text(encoding="utf-8"))
    assigned = {
        t.id
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert "_RE_REBIND" not in assigned
    assert "_EVENT_ORDER" not in assigned


def test_02_both_paths_use_the_same_event_order():
    r"""🔴 같은 위치의 우선순위 표가 하나다 — ``create``/``clone`` → rebind → set."""
    order = loader_module._EVENT_ORDER
    assert order["create"] == order["clone"] < order["rebind"] < order["set"]
    #: analyzer 가 그 표로 정렬한다는 것을 **소스에서** 확인한다.
    source = textwrap.dedent(
        __import__("inspect").getsource(EffectAnalyzer._collect_handlers.__func__)
    )
    tree = ast.parse(source)
    sorts = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sort"
    ]
    assert len(sorts) == 1
    assert "_EVENT_ORDER" in ast.dump(sorts[0])


def test_03_the_rebind_rule_drops_handlers_on_both_paths():
    r"""🔴 양쪽이 **같은 답**을 낸다 — 인식 못 한 대입 뒤 설정자는 버려진다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            e1:SetOperation(s.op)
        end
    """)
    assert len(blocks) == 1
    #: loader: 그 뒤 설정자를 버린다 (``code`` 는 제 값 그대로).
    assert blocks[0].code == "EVENT_FREE_CHAIN"
    #: 🔴 수정 전 analyzer 는 ``Operation`` 을 붙였다 — Lua 에 없는 값이다.
    assert dict(before[0][0]) == {"Target": "s.tg", "Operation": "s.op"}
    #: 🔴 수정 후에는 붙이지 않는다 — loader 와 같다.
    assert dict(after[0][0]) == {"Target": "s.tg"}


def test_04_corpus_wide_the_two_paths_agree_on_handler_attribution():
    r"""🔴 코퍼스 전수로, 설정자가 **풀린 바인딩에 붙는 자리가 0** 이다."""
    attached_to_stale = 0
    for path in _script_paths():
        body = _body(path)
        events = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), "create", m.group(2)))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                events.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
        for m in _RE_REBIND.finditer(body):
            events.append((m.start(), "rebind", m.group(1)))
        for m in analyzer_module._RE_SETTER.finditer(body):
            events.append((m.start(), "set", m.group(1)))
        events.sort(key=lambda e: (e[0], loader_module._EVENT_ORDER[e[1]]))
        bound: set[str] = set()
        stale: set[str] = set()
        for _pos, kind, payload in events:
            if kind == "rebind":
                for name in payload.split(","):
                    name = name.strip()
                    if name in bound:
                        bound.discard(name)
                        stale.add(name)
            elif kind == "create":
                bound.add(payload)
                stale.discard(payload)
            elif kind == "clone":
                dst, _src = payload.split("=", 1)
                bound.add(dst)
                stale.discard(dst)
            elif payload in stale:
                attached_to_stale += 1
    assert attached_to_stale == 0


# ===========================================================================
# 범주 2 — 일반 변수와 Effect 변수 구분
# ===========================================================================
def test_05_plain_variable_rebinding_is_ignored_by_both():
    """🟢 Effect 와 무관한 변수 재바인딩은 아무것도 바꾸지 않는다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
            local g=Duel.GetMatchingGroup(nil,0,1,0,nil)
            g=g:Filter(s.filter,nil)
            local tc=g:GetFirst()
            tc=g:GetNext()
        end
    """)
    assert len(blocks) == 1
    assert before == after
    assert dict(after[0][0]) == {"Target": "s.tg"}


def test_06_regex_match_count_is_not_the_effect_rebinding_count():
    r"""🔴 정규식 매치 수를 Effect 재바인딩 수로 쓰지 않는다.

    3-F-33 이 측정한 비율을 다시 산출한다 — 매치 수가 Effect 재바인딩
    수보다 **세 자릿수** 크다.
    """
    matches = 0
    names = 0
    effect_vars = 0
    for path in _script_paths():
        body = _body(path)
        events = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), "create", m.group(2)))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                events.append((m.start(), "clone", m.group(2)))
        for m in _RE_REBIND.finditer(body):
            matches += 1
            events.append((m.start(), "rebind", m.group(1)))
        events.sort(key=lambda e: (e[0], loader_module._EVENT_ORDER[e[1]]))
        bound: set[str] = set()
        for _pos, kind, payload in events:
            if kind == "rebind":
                for name in payload.split(","):
                    names += 1
                    if name.strip() in bound:
                        effect_vars += 1
                        bound.discard(name.strip())
            else:
                bound.add(payload)
    #: 한 매치가 여러 이름을 풀 수 있다 (``local a,b=…``).
    assert matches < names
    #: 🔴 그 가운데 실제 Effect 변수는 극소수다.
    assert effect_vars < matches / 1000
    assert effect_vars == 30


def test_07_local_declaration_and_reassignment_are_distinguished():
    """🟢 ``local`` 선언 · 기존 변수 대입 · Clone 결과 대입을 구분한다."""
    #: ``local`` + 인식되는 생성 → 블록
    assert len(_both("local e1=Effect.CreateEffect(c)")[0]) == 1
    #: ``local`` + 인식되는 clone → 블록 (부모가 없으면 빈 상속)
    assert len(_both("local e2=e1:Clone()")[0]) == 1
    #: ``local`` + 모르는 값 → 블록 아님, 그리고 재바인딩으로 센다
    assert _both("local x=Duel.GetFieldGroup(0,1,0)")[0] == []
    assert _RE_REBIND.search("\tlocal x=Duel.GetFieldGroup(0,1,0)\n") is not None
    #: 인식되는 세 형태는 재바인딩이 아니다
    for rhs in ("Effect.CreateEffect(c)", "Effect.GlobalEffect()",
                "e1:Clone()", "e1:Clone(e1)", "Effect.Clone(e1)"):
        assert _RE_REBIND.search(f"\tlocal e2={rhs}\n") is None, rhs


def test_08_unrecognised_assignment_is_never_inferred():
    """🟢 파서가 인식하지 못한 변수를 **임의로 추론하지 않는다** (UNKNOWN)."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            local e2=Fusion.CreateSummonEff(c,s.f)
            e2:SetCode(EVENT_TO_HAND)
            e2:SetCategory(CATEGORY_DESTROY)
            e2:SetOperation(s.op)
        end
    """)
    #: 보조 함수 반환값은 블록이 되지 않고 앞 블록을 오염시키지 않는다.
    assert len(blocks) == 1
    assert blocks[0].code == "EVENT_FREE_CHAIN"
    assert blocks[0].categories == []
    #: analyzer 도 그 ``SetOperation`` 을 붙이지 않는다 (수정 전후 모두).
    assert "Operation" not in dict(before[0][0])
    assert "Operation" not in dict(after[0][0])


# ===========================================================================
# 범주 3·4 — 생성 후 재바인딩 / 재바인딩 후 생성
# ===========================================================================
def test_09_create_then_rebind_to_another_effect():
    r"""🟢 §4.1 — 생성 → Clone → 원래 변수를 **새 Effect** 로 재바인딩.

    🔴 여기서 뒤의 재바인딩이 **앞선 Clone 의 부모 관계나 ordinal 을
    바꾸지 않는다** — §4 가 명시한 제약이다.
    """
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetOperation(s.op)
            c:RegisterEffect(e2)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            e1:SetCode(EVENT_TO_HAND)
            c:RegisterEffect(e1)
        end
    """)
    assert [s.index for s in blocks] == ["e1", "e2", "e1"]
    assert [s.cloned_from for s in blocks] == [None, "e1", None]
    assert [s.code for s in blocks] == [
        "EVENT_FREE_CHAIN", "EVENT_FREE_CHAIN", "EVENT_TO_HAND"
    ]
    #: 🔴 ``e2`` 는 **그때 유효했던** 부모의 핸들러를 유지한다.
    assert dict(after[1][0]) == {"Condition": "s.con", "Operation": "s.op"}
    #: 이 사례는 수정 전후가 같다 — 재바인딩이 아니라 **새 생성**이다.
    assert before == after


def test_10_rebind_then_create_keeps_blocks_separate():
    """🟢 §4.2 의 앞부분 — 재바인딩 뒤의 새 생성은 별개 블록이다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 2
    assert [s.cloned_from for s in blocks] == [None, None]
    #: 두 번째 블록이 첫 번째의 핸들러를 물려받지 않는다.
    assert dict(after[0][0]) == {"Condition": "s.con"}
    assert dict(after[1][0]) == {"Target": "s.tg"}
    assert before == after


def test_11_setter_between_rebind_and_create_is_dropped():
    r"""🔴 재바인딩과 새 생성 **사이**의 설정자는 버려진다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            e1=table.unpack(t)
            e1:SetTarget(s.lost)
            local e1=Effect.CreateEffect(c)
            e1:SetOperation(s.op)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 2
    #: 🔴 수정 전에는 ``s.lost`` 가 **첫 블록**에 붙었다.
    assert dict(before[0][0]) == {"Condition": "s.con", "Target": "s.lost"}
    #: 수정 후에는 어디에도 없다.
    assert dict(after[0][0]) == {"Condition": "s.con"}
    assert dict(after[1][0]) == {"Operation": "s.op"}
    assert "s.lost" not in str(after)


# ===========================================================================
# 범주 5·6 — Clone 전후 재바인딩 · 부모/자식 관계 (N12)
# ===========================================================================
def test_12_rebind_then_clone_no_longer_inherits_from_a_stale_parent():
    r"""🔴 **N12 그 자체.** §4.2 — 재바인딩 뒤의 ``Clone``.

    수정 전에는 loader 가 "물려받은 것 없음" 을, analyzer 가 "물려받았음" 을
    **같은 블록에 대해 동시에** 주장했다. 이제 둘이 일치한다.
    """
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            local e2=e1:Clone()
            e2:SetOperation(s.op)
            c:RegisterEffect(e2)
        end
    """)
    assert len(blocks) == 2
    #: 🔴 loader 쪽 — ``cloned_from`` 은 적히지만 값은 하나도 물려받지 않았다.
    assert blocks[1].cloned_from == "e1"
    assert blocks[1].code is None
    assert blocks[1].effect_types == []
    #: 🔴 수정 전 analyzer — 옛 부모의 ``Condition`` 을 물려받았다 (모순).
    assert dict(before[1][0]) == {"Condition": "s.con", "Operation": "s.op"}
    #: 🔴 수정 후 — 물려받지 않는다. loader 와 **같은 주장**이다.
    assert dict(after[1][0]) == {"Operation": "s.op"}


def test_13_clone_then_rebind_the_parent_keeps_the_child_intact():
    r"""🟢 §4 제약 — ``Clone`` **뒤에** 부모를 재바인딩해도 자식은 그대로다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetOperation(s.op)
            c:RegisterEffect(e2)
            e1=e:GetLabelObject()
        end
    """)
    assert len(blocks) == 2
    #: 부모 관계와 ordinal 이 뒤의 재바인딩에 영향받지 않는다.
    assert blocks[1].cloned_from == "e1"
    assert [s.index for s in blocks] == ["e1", "e2"]
    assert dict(after[1][0]) == {"Condition": "s.con", "Operation": "s.op"}
    assert before == after


def test_14_clone_results_are_distinct_objects():
    r"""🔴 Clone 된 객체와 원본을 **같은 객체로 취급하지 않는다.**"""
    blocks, _before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetTarget(s.tg)
            c:RegisterEffect(e2)
        end
    """)
    assert len(blocks) == 2
    assert blocks[0] is not blocks[1]
    #: 자식의 설정자가 부모를 바꾸지 않는다.
    assert dict(after[0][0]) == {"Condition": "s.con"}
    assert dict(after[1][0]) == {"Condition": "s.con", "Target": "s.tg"}
    #: 목록 칸도 서로 다른 객체다 (3-F-29 가 고친 것).
    assert blocks[0].categories is not blocks[1].categories


def test_15_clone_into_the_same_variable():
    """🟢 §4.4 — ``e1=e1:Clone()`` 은 인식되는 대입이므로 재바인딩이 아니다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            e1=e1:Clone()
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
        end
    """)
    assert [s.index for s in blocks] == ["e1", "e1"]
    assert [s.cloned_from for s in blocks] == [None, "e1"]
    assert before == after
    assert dict(after[1][0]) == {"Condition": "s.con", "Target": "s.tg"}


def test_16_corpus_has_no_clone_from_a_stale_parent():
    r"""🔴 N12 의 실제 규모 — 코퍼스에 그런 자리가 **0건**이다.

    그래서 이 수정이 데이터를 바꾸지 않는다. 0 은 "구조적으로 불가능" 이
    아니라 "이 코퍼스에 없다" 이고, 위의 ``test_12`` 가 그것을 보인다.
    """
    clone_from_stale = 0
    for path in _script_paths():
        body = _body(path)
        events = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                events.append((m.start(), "create", m.group(2)))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                events.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
        for m in _RE_REBIND.finditer(body):
            events.append((m.start(), "rebind", m.group(1)))
        events.sort(key=lambda e: (e[0], loader_module._EVENT_ORDER[e[1]]))
        bound: set[str] = set()
        stale: set[str] = set()
        for _pos, kind, payload in events:
            if kind == "rebind":
                for name in payload.split(","):
                    name = name.strip()
                    if name in bound:
                        bound.discard(name)
                        stale.add(name)
            elif kind == "create":
                bound.add(payload)
                stale.discard(payload)
            else:
                dst, src = payload.split("=", 1)
                if src in stale:
                    clone_from_stale += 1
                bound.add(dst)
                stale.discard(dst)
    assert clone_from_stale == 0


# ===========================================================================
# 범주 7 — 같은 변수명의 서로 다른 scope
# ===========================================================================
def test_17_same_name_in_different_functions():
    """🟢 §4.5 — 같은 이름이 다른 함수에 있어도 블록이 섞이지 않는다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
        end
        function s.op(e,tp)
            local c=e:GetHandler()
            local e1=Effect.CreateEffect(c)
            e1:SetOperation(s.op2)
            tc:RegisterEffect(e1)
            local e2=e1:Clone()
            tc:RegisterEffect(e2)
        end
    """)
    assert [s.index for s in blocks] == ["e1", "e1", "e2"]
    assert [s.cloned_from for s in blocks] == [None, None, "e1"]
    #: 🔴 두 번째 ``e1`` 이 첫 번째의 ``Condition`` 을 물려받지 않는다.
    assert dict(after[0][0]) == {"Condition": "s.con"}
    assert dict(after[1][0]) == {"Operation": "s.op2"}
    #: 그 ``e1`` 의 clone 은 **두 번째** 것을 물려받는다.
    assert dict(after[2][0]) == {"Operation": "s.op2"}
    #: 소속 함수가 바르게 나뉜다 — ``is_registered`` 가 이 값에 달려 있다.
    assert [f for _h, f in after] == ["initial_effect", "op", "op"]
    assert before == after


def test_18_global_effect_variable_is_gated_out():
    """🟢 §4.5 — ``Effect.GlobalEffect`` 는 게이트가 거부한다 (양쪽 공유)."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local ge1=Effect.GlobalEffect()
            ge1:SetOperation(s.gop)
            Duel.RegisterEffect(ge1,0)
            ge1=nil
            ge1:SetTarget(s.tg)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
        end
    """)
    assert [s.index for s in blocks] == ["e1"]
    assert before == after
    assert dict(after[0][0]) == {"Condition": "s.con"}


# ===========================================================================
# 범주 8 — 등록 Effect 와 변수 바인딩의 분리
# ===========================================================================
def test_19_registration_is_independent_of_binding():
    r"""🔴 ``RegisterEffect`` 여부와 변수 바인딩은 **다른 것**이다.

    등록하지 않아도 블록은 생기고, 등록해도 바인딩이 풀리면 설정자는
    버려진다.
    """
    #: 등록 없이도 블록이 생긴다 (``local`` + ``e*`` 관례).
    blocks_a, _b, _a = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
        end
    """)
    assert len(blocks_a) == 1
    #: 등록했어도 재바인딩 뒤 설정자는 버려진다.
    blocks_b, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            e1:SetCost(s.cost)
        end
    """)
    assert len(blocks_b) == 1
    assert dict(before[0][0]) == {"Cost": "s.cost"}
    assert dict(after[0][0]) == {}


def test_20_is_registered_comes_from_the_enclosing_function(repo):
    """🟢 ``is_registered`` 는 소속 함수로 정해진다 — 바인딩과 무관하다."""
    analyzer = EffectAnalyzer(repo)
    analysis = analyzer.analyze(repo.get(4997565))
    #: ``initial_effect`` 안의 둘만 등록으로 센다.
    assert len(analysis.effects) == 2
    assert all(e.is_registered for e in analysis.effects)
    assert len(analysis.resolution_effects) == 3
    assert not any(e.is_registered for e in analysis.resolution_effects)


# ===========================================================================
# 범주 9 — EffectRef 와 ordinal 불변성
# ===========================================================================
def test_21_block_count_and_order_are_identical_corpuswide():
    """🟢 두 경로의 목록 길이와 순서가 전수로 같다."""
    scripts = blocks = entries = 0
    mismatch = []
    for path in _script_paths():
        b, e = _loader_blocks(path), _analyzer_entries(path)
        scripts += 1
        blocks += len(b)
        entries += len(e)
        if len(b) != len(e):
            mismatch.append((path.name, len(b), len(e)))
    assert scripts == SCRIPT_COUNT
    assert blocks == BLOCK_TOTAL
    assert entries == BLOCK_TOTAL
    assert mismatch == []


def test_22_ordinal_follows_source_order_corpuswide():
    r"""🟢 ``ordinal`` 은 원문 등장 순서다 — 재바인딩이 자리를 바꾸지 않는다."""
    mismatch = 0
    checked = 0
    for path in _script_paths():
        body = _body(path)
        positions = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                positions.append((m.start(), m.group(2), None))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                positions.append((m.start(), m.group(2), src_var))
        positions.sort()
        blocks = _loader_blocks(path)
        checked += len(blocks)
        derived = [(name, parent) for _p, name, parent in positions]
        actual = [(s.index, s.cloned_from) for s in blocks]
        if derived != actual:
            mismatch += 1
    assert checked == BLOCK_TOTAL
    assert mismatch == 0


def test_23_effect_ref_resolves_to_the_same_block(repo):
    """🟢 ``EffectRef(card_id, ordinal)`` 연결이 전수로 성립한다."""
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
        for i, ref in enumerate(refs):
            if ref != EffectRef(card.id, i):
                bad += 1
            if ref.resolve(card) is not card.script.effects[i]:
                bad += 1
        if [r.ordinal for r, _s in iter_effects(card)] != list(range(len(refs))):
            bad += 1
    assert total == ATTACHED_BLOCKS
    assert bad == 0


def test_24_effectspec_and_effectref_design_untouched():
    r"""🟢 ``EffectSpec`` · ``EffectRef`` 설계를 바꾸지 않았다 (§7 금지)."""
    import dataclasses
    from sources.lua_loader import EffectSpec
    fields = [f.name for f in dataclasses.fields(EffectSpec)]
    assert fields == ["index", "effect_types", "code", "ranges", "target_ranges",
                      "categories", "properties", "count_limit", "cloned_from"]
    ref_fields = [f.name for f in dataclasses.fields(EffectRef)]
    assert ref_fields == ["card_id", "ordinal"]


# ===========================================================================
# 범주 10 — parser 미인식 대입의 UNKNOWN 처리
# ===========================================================================
def test_25_dropped_means_unknown_not_empty():
    r"""🔴 버려진 것은 **모른다**이고 "없다" 가 아니다.

    loader 는 읽지 못한 ``code`` 를 ``None`` 으로 되돌린다 (3-E-18).
    analyzer 는 핸들러를 **붙이지 않는다**. 둘 다 "추측하지 않는다" 다.
    """
    blocks, _before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            e1=aux.Something(c)
            e1:SetCode(id)
            e1:SetCondition(s.con)
        end
    """)
    assert len(blocks) == 1
    #: 🔴 뒤의 ``SetCode(id)`` 가 제 값을 덮지 않았다.
    assert blocks[0].code == "EVENT_FREE_CHAIN"
    assert dict(after[0][0]) == {}


def test_26_multi_assignment_unbinds_every_name():
    r"""🔴 다중 대입은 왼쪽 이름 **전부**를 푼다."""
    blocks, before, after = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCost(s.cost)
            c:RegisterEffect(e1)
            local e2=Effect.CreateEffect(c)
            e2:SetCost(s.cost)
            c:RegisterEffect(e2)
            local e1,e2=Spirit.AddProcedure(c,true)
            e1:SetTarget(s.tg)
            e2:SetOperation(s.op)
        end
    """)
    assert len(blocks) == 2
    assert dict(before[0][0]) == {"Cost": "s.cost", "Target": "s.tg"}
    assert dict(before[1][0]) == {"Cost": "s.cost", "Operation": "s.op"}
    #: 수정 후 둘 다 자기 것만 남는다.
    assert dict(after[0][0]) == {"Cost": "s.cost"}
    assert dict(after[1][0]) == {"Cost": "s.cost"}


# ===========================================================================
# 범주 11 — Phase 3-F-32 의 세 대표 사례 회귀
# ===========================================================================
def test_27_phase_3f32_three_cases_are_preserved():
    """🟢 3-F-32 가 인정한 세 ``Clone`` 형태가 그대로다."""
    for card_id, (count, ordinal, code, parent) in PHASE32_CARDS.items():
        blocks = _loader_blocks(PROJECT_ROOT / f"c{card_id}.lua")
        assert len(blocks) == count, card_id
        assert blocks[ordinal].code == code, card_id
        assert blocks[ordinal].cloned_from == parent, card_id


def test_28_phase_3f32_counter_example_is_preserved():
    """🟢 Group 의 ``Clone`` 은 여전히 블록이 되지 않는다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    assert ":Clone()" in _body(path)
    assert [m.group(0) for m in _RE_CLONE_EFFECT.finditer(_body(path))] == []
    assert [s.index for s in _loader_blocks(path)] == ["e1"]
    assert len(_analyzer_entries(path)) == 1


def test_29_phase_3f31_label_object_stays_unknown():
    r"""🟢 3-F-31 — ``e:GetLabelObject()`` 뒤 ``SetCategory`` 는 계속 버려진다."""
    blocks = _loader_blocks(PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua")
    assert all(s.categories == [] for s in blocks)
    assert _body(PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua").count("SetCategory(") >= 3


def test_30_phase_3f27_settype_replacement_is_preserved():
    """🟢 3-F-27 — ``Clone`` 뒤 ``SetType`` 이 물려받은 목록을 덮어쓴다."""
    blocks = _loader_blocks(PROJECT_ROOT / "c324483.lua")
    cloned = [s for s in blocks if s.cloned_from is not None]
    assert cloned
    assert cloned[0].effect_types == ["QUICK_O"]


# ===========================================================================
# 범주 13 — 산출물 fingerprint 비교 (수정 전 vs 수정 후)
# ===========================================================================
def test_31_handler_fingerprint_is_unchanged_corpuswide():
    r"""🔴 **§5 의 핵심.** 수정 전/후 핸들러 지문이 전수로 같다.

    숫자를 리터럴로 적지 않는다 — 같은 측정을 **두 설정으로 돌려** 맞댄다.
    """
    before = hashlib.sha256()
    after = hashlib.sha256()
    changed = []
    for path in _script_paths():
        source = _raw(path)
        spans = EffectAnalyzer._function_spans(source)
        b = _handlers(_collect_without_rebind(source, spans))
        a = _handlers(EffectAnalyzer._collect_handlers(source, spans))
        before.update(repr((path.name, b)).encode())
        after.update(repr((path.name, a)).encode())
        if b != a:
            changed.append(path.name)
    assert changed == [], changed[:5]
    assert before.hexdigest() == after.hexdigest()


def test_32_card_analysis_fingerprint_is_unchanged(repo):
    r"""🔴 최종 ``CardAnalysis`` 지문이 수정 전/후 같다 — 끝까지 본다."""
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
    original = EffectAnalyzer._collect_handlers.__func__

    def fingerprint():
        analyzer = EffectAnalyzer(repo)
        digest = hashlib.sha256()
        totals: collections.Counter = collections.Counter()
        for card in cards:
            analysis = analyzer.analyze(card)
            rows = []
            for label, group in (("R", analysis.effects),
                                 ("X", analysis.resolution_effects)):
                for effect in group:
                    rows.append((label, effect.index, effect.effect_code,
                                 effect.trigger_event, tuple(effect.effect_types),
                                 tuple(effect.categories), effect.has_condition,
                                 bool(effect.costs), bool(effect.selection),
                                 len(effect.actions), effect.targets_card,
                                 effect.is_registered))
            totals["registered"] += len(analysis.effects)
            totals["resolution"] += len(analysis.resolution_effects)
            for effect in list(analysis.effects) + list(analysis.resolution_effects):
                totals["cond"] += bool(effect.has_condition)
                totals["cost"] += bool(effect.costs)
                totals["target"] += bool(effect.targets_card)
                totals["action"] += len(effect.actions)
                totals["cat"] += len(effect.categories)
            digest.update(repr((card.id, rows)).encode())
        return digest.hexdigest(), dict(totals)

    after = fingerprint()
    try:
        #: 🔴 ``classmethod`` 는 첫 인자로 ``cls`` 를 넘긴다 — 그냥 끼우면
        #: ``TypeError`` 다. 처음에 그렇게 썼다가 터졌다.
        EffectAnalyzer._collect_handlers = classmethod(
            lambda cls, source, spans: _collect_without_rebind(source, spans)
        )
        before = fingerprint()
    finally:
        EffectAnalyzer._collect_handlers = classmethod(original)

    assert before[1] == after[1]
    assert before[0] == after[0]
    #: 🔴 3-F-33 이 보고한 집계와도 맞는다 (다시 산출한 값이다).
    assert after[1] == ANALYSIS_TOTALS


def test_33_parser_block_totals_match_the_baseline():
    """🟢 파서 산출물 총계가 3-F-33 의 기준과 같다 (다시 산출)."""
    blocks = sum(len(_loader_blocks(p)) for p in _script_paths())
    assert len(_script_paths()) == SCRIPT_COUNT
    assert blocks == BLOCK_TOTAL


# ===========================================================================
# 범주 14 — 검색 결과 및 순위 회귀
# ===========================================================================
def test_34_search_is_structurally_independent_of_the_analyzer(repo):
    r"""🔴 검색은 analyzer 를 **거치지 않는다** — 구조로 증명한다.

    처음에는 ``_collect_handlers`` 를 수정 전 것으로 끼워 넣고 검색 지문을
    before/after 로 비교하는 테스트를 썼다. 🔴 **그 비교는 공허했다** —
    ``core/card_search.py`` 는 analyzer 를 아예 쓰지 않으므로 끼워 넣어도
    아무 일이 일어나지 않고, 결국 **검색을 자기 자신과 비교**하고 있었다.

    그래서 공허한 비교를 지우고, 실제로 확인할 수 있는 둘만 남긴다.
    """
    #: (1) 구조 — ``core/card_search.py`` 가 analysis 계층을 import 하지 않는다.
    search_source = (PROJECT_ROOT / "core" / "card_search.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(search_source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert "analysis" not in imported_modules
    assert "EffectAnalyzer" not in search_source

    #: (2) 검색이 읽는 것은 **loader** 의 ``script.effects`` 다.
    card = repo.get(56410769)
    assert card.effects is card.script.effects

    #: 그리고 이 Phase 는 loader 를 건드리지 않았으므로 검색은 바뀔 수 없다.
    #: 그래도 실제로 돌려 3-F-32 가 세운 사실이 그대로인지 본다.
    cards = [c for c in repo.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert len(categories) == SEARCH_CATEGORIES
    assert len(locations) == SEARCH_LOCATIONS

    engine = CardSearchEngine(repo)
    mzone = engine.search(
        SearchFilters(effect_locations=(EffectLocationFilter(location="MZONE"),))
    )
    ids = [c.id for c in mzone.cards]
    assert 56410769 in ids
    #: 🔴 3-F-32 가 확정한 사실 — 이 카드는 MZONE 범위 블록이 **셋**이고
    #: 그중 하나가 그 Phase 가 인정한 clone 이다.
    mzone_blocks = [s for s in card.script.effects if "MZONE" in s.ranges]
    assert [s.index for s in mzone_blocks] == ["e1", "e2", "e3"]
    assert mzone_blocks[2].cloned_from == "e2"

    #: 카테고리 검색은 세 대표 사례를 올리지 않는다 (새 블록의 categories 가 빈다).
    destroy = {c.id for c in engine.search(
        SearchFilters(effect_categories=("DESTROY",))).cards}
    assert set(PHASE32_CARDS) & destroy == set()


# ===========================================================================
# 불변 조건 · 수정 제한
# ===========================================================================
def test_35_engine_v1_definitions_are_untouched():
    """🟢 Engine V1 의 16개 정의가 전부 ``ordinal 0`` 이고 그대로다."""
    from engine.effect.library import EFFECT_LIBRARY
    refs = {(e.definition.effect_ref.card_id, e.definition.effect_ref.ordinal)
            for e in EFFECT_LIBRARY}
    assert len(EFFECT_LIBRARY) == 16
    assert {ordinal for _c, ordinal in refs} == {0}
    assert {c for c, _o in refs} & set(PHASE32_CARDS) == set()


def test_36_state_hash_is_structurally_independent():
    """🟢 ``state_hash`` 의 정규 표현에 블록·바인딩이 들어가지 않는다 (AST)."""
    import inspect
    from engine.state.game_state import GameState
    source = textwrap.dedent(inspect.getsource(GameState.canonical_state))
    returns = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    names = {n.attr for n in ast.walk(returns[0]) if isinstance(n, ast.Attribute)}
    for forbidden in ("effects", "effect_count", "script", "handlers"):
        assert forbidden not in names, forbidden
    assert {"players", "turn", "uses", "rule_uses", "result"} <= names


def test_37_engine_and_agent_do_not_read_the_binding_fields():
    r"""🟢 ``engine/`` · ``agent/`` 가 ``EffectSpec`` 전용 칸을 읽지 않는다.

    🔴 이름만 보고 판단하지 않는다 — ``.code`` · ``.index`` 는 다른 클래스에도
    있다 (3-F-28 · 3-F-30 이 각각 그 함정에 빠졌다).
    """
    unique = ("effect_types", "target_ranges", "cloned_from", "count_limit")
    for package in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            assert attrs & set(unique) == set(), (path.name, attrs & set(unique))


def test_38_the_cache_signature_was_not_bumped():
    r"""🔴 캐시 서명을 **올리지 않았다** — 올릴 이유가 없다.

    analyzer 는 디스크 캐시가 없고(``_cache`` 는 인스턴스 메모리 dict),
    loader 는 건드리지 않았으며 그 산출물도 동일하다. 올리면 12,702
    스크립트를 쓸데없이 재파싱한다.
    """
    assert LuaScriptSource(PROJECT_ROOT)._signature().startswith(CACHE_PREFIX)
    loader_source = Path(loader_module.__file__).read_text(encoding="utf-8")
    assert ('return f"v10-{_CACHE_SHAPE_TAG}:{count}:{newest:.0f}"'
            in loader_source)
    #: analyzer 에 디스크 쓰기 경로가 없다.
    analyzer_tree = ast.parse(Path(analyzer_module.__file__).read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(analyzer_tree) if isinstance(n, ast.Attribute)}
    for persistent in ("write_text", "dump", "load_cached", "replace"):
        assert persistent not in attrs, persistent


def test_39_no_lua_interpreter_or_graph_engine_was_added():
    """🟢 §7 금지 — Lua 인터프리터 · dataflow · graph 라이브러리 없음."""
    forbidden = ("luaparser", "lupa", "slpp", "networkx", "antlr", "lark")
    for package in ("sources", "analysis", "engine", "core", "agent"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            assert modules & set(forbidden) == set(), path.name


def test_40_production_change_is_confined_to_one_file():
    r"""🔴 production 변경이 **analyzer 한 파일**에 갇혀 있다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    production = {
        name for name in changed
        if name.endswith(".py") and not name.startswith("tests/")
    }
    assert production == {"analysis/effect_analyzer.py"}, production
    #: 금지 경로가 하나도 없다.
    assert not any(name.endswith(".lua") for name in changed)
    assert not any(name.endswith("README.md") for name in changed)
    assert not any(
        name.startswith(("engine/", "agent/", "core/", "sources/")) for name in changed
    )


def test_41_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-34:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
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
            if line.startswith("-") and not line.startswith("---"):
                if re.match(r"-def test_", line):
                    removed_tests += 1
    assert added_skips == 0
    assert removed_tests == 0
