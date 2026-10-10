r"""
Phase 3-F-33 — loader / analyzer 바인딩 규칙 일관성 감사
========================================================

핵심 질문 둘
------------
1. ``sources/lua_loader.py`` 의 ``_RE_REBIND`` 를
   ``analysis/effect_analyzer.py`` 에도 적용하면 실제 Effect 수 · ``ordinal`` ·
   분석 결과가 달라지는가?
   → **달라지지 않는다.** 코퍼스 전수로 0 스크립트 / 0 블록, 최종
   ``CardAnalysis`` 지문까지 동일하다.

2. 한쪽에서만 변수를 재바인딩하는 경우가 발생하는가?
   → **규칙은 실제로 다르다.** analyzer 에는 ``_RE_REBIND`` 가 **없다.**
   §3.A 의 9가지 상황 가운데 **2가지**(4번·9번 — 둘 다 "파서가 인식하지 못하는
   대입")에서 **다른 결과를 재현**했다. 그 2가지가 코퍼스에는 **0건**이다.

두 경로의 구조 차이 (실측)
--------------------------
=== ============================ ======================== =========================
 #  차이                          loader                   analyzer
=== ============================ ======================== =========================
 D1 ``_RE_REBIND``                적용한다                 🔴 **없다**
 D2 이벤트 정렬                    ``(pos, _EVENT_ORDER)``  ``pos`` 만
 D3 소비하는 설정자                 값 7개                   함수 슬롯 4개
 D4 블록 탐지                      공유 (import)            공유 (import)
 D5 전처리                         ``_RE_BLOCK_COMMENT``    같음
=== ============================ ======================== =========================

* **D2 는 지금 한 번도 발동하지 않는다** — 같은 byte offset 에 두 종류
  이벤트가 겹치는 자리가 코퍼스 전체에 **0건**이다 (``_EVENT_ORDER`` 는
  방어적 장치다).
* **D3 의 두 집합은 완전히 분리되어 있다** — 교집합이 없다. 그래서 두 경로가
  갈릴 수 있는 자리는 "Effect 변수가 풀린 뒤 **네 핸들러 설정자**가 오는
  자리" 뿐이고, 그것이 **0건**이다.

``_RE_REBIND`` 를 §4 의 범주로 나눈 결과
----------------------------------------
======================================================= ========
항목                                                       수
======================================================= ========
정규식에 일치하는 원문                                     67,226
그 원문이 있는 고유 스크립트                               12,701
그중 ``local`` 선언                                        63,753
🔴 이름 단위 unbind 이벤트 (다중 대입 때문에 더 많다)        81,688
🔴 그중 **실제 Effect 변수**를 푸는 자리                        30
Effect 와 무관한 일반 변수 재바인딩                        81,658
🔴 analyzer 가 옛 바인딩에 핸들러를 붙이는 자리                  0
🔴 풀린 변수를 부모로 쓰는 ``Clone``                             0
======================================================= ========

🔴 **정규식 매치 수(67,226)를 Effect 재바인딩 수(30)로 쓰면 2,240배 틀린다.**
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
from engine.ids import EffectRef, effect_refs, iter_effects
from sources.lua_loader import (
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

# --- 전수 측정값 (측정으로 고정한다) ---------------------------------------
SCRIPT_COUNT = 12702
BLOCK_TOTAL = 34684
#: ``cards.cdb`` 에 있는 카드에 붙은 블록 (전체보다 적다)
ATTACHED_BLOCKS = 34635
ATTACHED_CARDS = 12687

REBIND_MATCHES = 67226
REBIND_SCRIPTS = 12701
REBIND_LOCAL_DECL = 63753
UNBIND_EVENTS = 81688
UNBIND_EFFECT_VARS = 30
UNBIND_PLAIN_VARS = 81658
DIVERGENT_HANDLER_SITES = 0
DIVERGENT_CLONE_PARENTS = 0
EVENT_POSITION_TIES = 0

#: analyzer 가 소비하는 네 설정자의 호출 수
ANALYZER_SETTER_CALLS = {"Condition": 11928, "Operation": 19480,
                         "Target": 17977, "Cost": 4899}
ANALYZER_SETTER_TOTAL = 54284
#: loader 가 소비하는 일곱 설정자의 호출 수 (3-F-31 이 고정한 값)
LOADER_SETTER_TOTAL = 121636

LOADER_HANDLED = frozenset(
    {"Type", "Code", "Range", "TargetRange", "Category", "Property", "CountLimit"}
)
ANALYZER_HANDLED = frozenset({"Cost", "Condition", "Target", "Operation"})

#: Phase 3-F-32 가 블록을 더한 세 장 (ordinal, code, 부모)
PHASE32_CARDS = {
    44887817: (5, 4, "EFFECT_CANNOT_MSET", "e1"),
    4997565: (5, 3, "EFFECT_DISABLE_EFFECT", "e1"),
    56410769: (3, 2, "EFFECT_CANNOT_ATTACK_ANNOUNCE", "e2"),
}
#: 🔴 Group 의 ``Clone`` — 블록이 되면 안 된다
GROUP_CLONE_CARD = 63708033
#: ``e:GetLabelObject()`` 로 바인딩이 풀리는 카드 (3-F-31 N3)
LABEL_OBJECT_CARD = 52445243

#: 🔴 Phase 3-F-37 이 ``v9:`` -> ``v10-<shape>:`` 로 바꿨다.
#: ``LuaScriptInfo`` 에 ``effect_offsets`` 와 ``source_digest`` 가 생겨
#: 캐시 모양이 달라졌기 때문이다. 뒤의 ``<shape>`` 는 저장되는 칸 목록의
#: 해시이고 **자동으로** 바뀐다 — 같은 번호 아래에서 칸이 달라지는 사고를
#: 막는다 (3-F-37 작업 중 실제로 겪었고, 기존 테스트 103건이 그래서 한 번
#: 깨졌다). 이 테스트의 주장은 그대로다: **파서 산출물이 달라지면 캐시
#: 서명도 달라져야 한다.**
CACHE_PREFIX = "v10-"


# ===========================================================================
# 공용 도구 — production 경로를 **그대로** 돌린다
# ===========================================================================
def _script_paths() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("c*.lua"))


def _raw(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _body(path: Path) -> str:
    """두 경로가 **똑같이** 쓰는 전처리 결과."""
    return _RE_BLOCK_COMMENT.sub("", _raw(path))


def _card_id(path: Path) -> int:
    return int(re.match(r"c(\d+)", path.name).group(1))


def _loader_blocks(path: Path):
    """loader 경로의 산출물."""
    return parse_lua_source(_card_id(path), path.name, _raw(path)).effects


def _analyzer_entries(path: Path):
    """analyzer 경로의 산출물 — **production 메서드를 그대로 부른다.**"""
    source = _raw(path)
    return EffectAnalyzer._collect_handlers(
        source, EffectAnalyzer._function_spans(source)
    )


#: 같은 위치의 이벤트 우선순위 — loader 와 같은 표를 쓴다.
_ORDER = dict(loader_module._EVENT_ORDER)


def _collect(source: str, spans, *, with_rebind: bool, loader_order: bool):
    r"""
    analyzer 의 ``_collect_handlers`` 와 **같은 흐름** + 두 개의 스위치.

    🔴 이 함수는 ``test_01`` 이 **스위치를 끈 상태에서 production 과 글자
    그대로 같은 결과**를 내는지 먼저 확인한다. 그 확인을 통과하지 못하면
    이 함수로 얻은 어떤 숫자도 쓰지 않는다 — 3-F-28·3-F-32 가 '복제본의
    버그를 측정' 하는 실수를 각각 한 번씩 했다.
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
    if with_rebind:
        for m in _RE_REBIND.finditer(source):
            events.append((m.start(), "rebind", m.group(1)))
    for m in analyzer_module._RE_SETTER.finditer(source):
        events.append((m.start(), "set", f"{m.group(1)}|{m.group(2)}|{m.end() - 1}"))

    if loader_order:
        events.sort(key=lambda e: (e[0], _ORDER[e[1]]))
    else:
        events.sort(key=lambda e: e[0])

    bindings: dict[str, dict[str, str]] = {}
    order: list[dict] = []
    for pos, kind, payload in events:
        if kind == "rebind":
            for name in payload.split(","):
                bindings.pop(name.strip(), None)
        elif kind == "create":
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


def _shape(order) -> list[tuple]:
    """비교용 — 핸들러와 소속 함수를 값으로 고정한다."""
    return [(tuple(sorted(e["handlers"].items())), e["function"]) for e in order]


def _both(lua: str):
    """최소 재현 하나를 **양쪽 경로**에 넣고 (loader 블록, production, +rebind) 를 돌려준다."""
    source = textwrap.dedent(lua)
    blocks = parse_lua_source(1, "c1.lua", source).effects
    spans = EffectAnalyzer._function_spans(source)
    production = _shape(_collect(source, spans, with_rebind=False, loader_order=False))
    unified = _shape(_collect(source, spans, with_rebind=True, loader_order=True))
    return blocks, production, unified


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일.

    🔴 **commit 범위만** 본다. worktree diff 를 섞으면 다음 Phase 의 수정이
    이 Phase 의 diff 로 새어 들어온다 (3-F-31 이 그렇게 3-F-30 을 깼다).
    """
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-33:"],
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
# 0. 계측 신뢰성 — 이것이 먼저다
# ===========================================================================
def test_01_the_variant_reproduces_production_exactly():
    r"""🔴 ``_collect`` 가 production 과 **전수로 같아야** 한다.

    이 테스트가 깨지면 아래 모든 측정이 무의미하다.

    .. note::
       🔴 **Phase 3-F-34 에서 비교 대상이 바뀌었다.** 이 Phase(3-F-33)가
       쓸 때 production analyzer 는 ``_RE_REBIND`` 가 **없었으므로**
       스위치를 **끈** 쪽이 production 이었다. 3-F-34 가 규칙을 맞췄으니
       이제 스위치를 **켠** 쪽이 production 이다.

       🔴 재미있게도 **양쪽 다 통과한다** — 이 코퍼스가 그 스위치에
       무감하다는 것이 바로 이 Phase 가 측정한 사실(``test_03``)이기
       때문이다. 그래도 "무엇이 production 인가" 를 틀리게 적어 두면
       계측 검증이라는 이 테스트의 목적이 사라지므로 바로잡는다.
       끈 쪽도 같다는 것은 아래에서 **따로** 확인한다.
    """
    bad_on = []
    bad_off = []
    for path in _script_paths():
        source = _raw(path)
        spans = EffectAnalyzer._function_spans(source)
        production = _shape(_analyzer_entries(path))
        #: 🔴 production 과 같은 설정 — 계측 신뢰성의 근거다.
        if production != _shape(
            _collect(source, spans, with_rebind=True, loader_order=True)
        ):
            bad_on.append(path.name)
        #: 끈 쪽도 이 코퍼스에서는 같다 (``test_03`` 과 같은 사실).
        if production != _shape(
            _collect(source, spans, with_rebind=False, loader_order=False)
        ):
            bad_off.append(path.name)
    assert bad_on == [], bad_on[:5]
    assert bad_off == [], bad_off[:5]


# ===========================================================================
# 1. 범주 10 — loader / analyzer 결과 일치 (전수)
# ===========================================================================
def test_02_both_paths_see_the_same_number_of_blocks():
    """두 경로의 목록 **길이**가 전수로 같다 — 어긋나면 핸들러가 밀린다."""
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
    assert mismatch == [], mismatch[:5]


def test_03_adding_rebind_to_the_analyzer_changes_nothing_corpuswide():
    r"""🔴 **핵심 질문 1 의 답.** ``_RE_REBIND`` 스위치가 전수 산출물을 바꾸지 않는다.

    .. note::
       🔴 **Phase 3-F-34 이후에는 방향이 반대로 읽힌다.** 그 Phase 가
       규칙을 적용했으므로, 지금 이 0 은 "넣어도 안 바뀐다" 가 아니라
       **"빼도 안 바뀐다"** 를 뜻한다. 어느 쪽으로 읽어도 같은 사실
       (코퍼스가 이 스위치에 무감하다)이고, 어서션은 그대로다.
    """
    changed_scripts = 0
    changed_blocks = 0
    total = 0
    for path in _script_paths():
        source = _raw(path)
        spans = EffectAnalyzer._function_spans(source)
        before = _shape(_collect(source, spans, with_rebind=False, loader_order=False))
        after = _shape(_collect(source, spans, with_rebind=True, loader_order=True))
        total += len(after)
        if before != after:
            changed_scripts += 1
            changed_blocks += sum(
                1 for i in range(max(len(before), len(after)))
                if (before[i] if i < len(before) else None)
                != (after[i] if i < len(after) else None)
            )
    assert total == BLOCK_TOTAL
    assert changed_scripts == 0
    assert changed_blocks == 0


def test_04_each_difference_measured_separately():
    r"""🔴 D1 과 D2 를 **따로** 켜도 각각 전수 변화 0 이다.

    둘을 한꺼번에 켜서 0 이 나오면 서로 상쇄한 것일 수도 있다. 분리해서 센다.
    """
    counts = {}
    for label, kw in (
        ("D1", dict(with_rebind=True, loader_order=False)),
        ("D2", dict(with_rebind=False, loader_order=True)),
    ):
        changed = 0
        for path in _script_paths():
            source = _raw(path)
            spans = EffectAnalyzer._function_spans(source)
            base = _shape(_collect(source, spans, with_rebind=False, loader_order=False))
            alt = _shape(_collect(source, spans, **kw))
            if base != alt:
                changed += 1
        counts[label] = changed
    assert counts == {"D1": 0, "D2": 0}


def test_05_end_to_end_card_analysis_is_identical(repo):
    r"""🔴 ``_collect_handlers`` 가 아니라 **최종 ``CardAnalysis``** 를 비교한다.

    `_collect_handlers` 가 같아도 그 아래에서 갈릴 수 있으므로 끝까지 본다.
    """
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS

    original = EffectAnalyzer._collect_handlers.__func__

    def fingerprint():
        analyzer = EffectAnalyzer(repo)
        digest = hashlib.sha256()
        totals = collections.Counter()
        for card in cards:
            analysis = analyzer.analyze(card)
            rows = []
            for label, blocks in (("R", analysis.effects),
                                  ("X", analysis.resolution_effects)):
                for effect in blocks:
                    rows.append((label, effect.index, effect.effect_code,
                                 effect.trigger_event, tuple(effect.effect_types),
                                 tuple(effect.categories), effect.has_condition,
                                 bool(effect.costs), bool(effect.selection),
                                 len(effect.actions), effect.targets_card,
                                 effect.is_registered))
            totals["registered"] += len(analysis.effects)
            totals["resolution"] += len(analysis.resolution_effects)
            digest.update(repr((card.id, rows)).encode())
        return digest.hexdigest(), dict(totals)

    before = fingerprint()
    try:
        EffectAnalyzer._collect_handlers = classmethod(
            lambda cls, source, spans: _collect(
                source, spans, with_rebind=True, loader_order=True
            )
        )
        after = fingerprint()
    finally:
        EffectAnalyzer._collect_handlers = classmethod(original)

    assert before[1] == after[1]
    assert before[0] == after[0]


# ===========================================================================
# 2. 범주 1·2·7 — 일반 변수 / Effect 변수 / 구분
# ===========================================================================
def test_06_plain_variable_rebinding_is_identical():
    """🟢 범주 1 — Effect 와 무관한 변수 재바인딩은 두 경로가 같다."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
            local g=Duel.GetMatchingGroup(nil,0,1,0,nil)
            g=g:Filter(s.filter,nil)
        end
    """)
    assert len(blocks) == 1
    assert production == unified
    assert production[0][0] == (("Target", "s.tg"),)


def test_07_effect_variable_rebinding_diverges():
    r"""🔴 범주 2 — **핵심 질문 2 의 답.** 같은 Lua, 다른 결과.

    ``e1=e:GetLabelObject()`` 뒤의 ``SetOperation`` 을 loader 는 **버리고**,
    analyzer 는 **옛 블록에 붙인다.** Lua 원문에서 그 블록은 ``SetOperation``
    을 갖지 않는다 — analyzer 쪽이 **없는 값을 만든다.**
    """
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            e1:SetOperation(s.op)
        end
    """)
    assert len(blocks) == 1
    assert production != unified
    #: production 은 Operation 을 붙인다 (틀렸다).
    assert dict(production[0][0]) == {"Target": "s.tg", "Operation": "s.op"}
    #: 재바인딩을 반영하면 붙이지 않는다 (맞다).
    assert dict(unified[0][0]) == {"Target": "s.tg"}


def test_08_distinguishes_value_assignment_from_effect_assignment():
    """🟢 범주 7 — ``nil``/상수 대입과 Effect 대입을 구분한다."""
    #: Effect 대입 — 두 경로 모두 새 블록
    blocks, _production, _unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 2
    #: 일반 값 대입 — 블록이 생기지 않는다
    blocks2, _p2, _u2 = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
            e1=nil
            e1=true
            e1=0
        end
    """)
    assert len(blocks2) == 1


def test_09_rebind_regex_classifies_recognised_forms_as_bindings():
    r"""``_RE_REBIND`` 는 파서가 **아는** 세 형태를 선읽기로 제외한다."""
    for rhs in ("Effect.CreateEffect(c)", "Effect.GlobalEffect()",
                "e1:Clone()", "e1:Clone(e1)", "Effect.Clone(e1)"):
        assert _RE_REBIND.search(f"\tlocal e2={rhs}\n") is None, rhs
    for rhs in ("e:GetLabelObject()", "nil", "Fusion.CreateSummonEff(c)",
                "table.unpack(t)", "e1"):
        assert _RE_REBIND.search(f"\tlocal e2={rhs}\n") is not None, rhs


# ===========================================================================
# 3. 범주 3·4 — Clone 이후 재바인딩 / 연속 대입
# ===========================================================================
def test_10_clone_to_a_new_variable_is_identical():
    """🟢 범주 3 — 보통의 ``Clone`` 은 두 경로가 같다."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetOperation(s.op)
            c:RegisterEffect(e2)
        end
    """)
    assert len(blocks) == 2
    assert blocks[1].cloned_from == "e1"
    assert production == unified
    #: 자식이 부모의 핸들러를 물려받고 자기 것을 더한다.
    assert dict(unified[1][0]) == {"Condition": "s.con", "Operation": "s.op"}


def test_11_clone_into_the_same_variable_is_identical():
    """🟢 범주 3 — ``e1=e1:Clone()`` 은 **인식되는** 대입이라 재바인딩이 아니다."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            e1=e1:Clone()
            e1:SetOperation(s.op)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 2
    assert blocks[1].cloned_from == "e1"
    assert production == unified


def test_12_clone_from_an_unbound_parent_diverges():
    r"""🔴 범주 3 — 부모가 풀린 뒤의 ``Clone``. 두 경로가 **정면으로 모순**한다.

    loader 는 ``parent=None`` 이라 **여섯 칸을 하나도 물려주지 않는다.**
    analyzer 는 옛 부모의 핸들러를 **그대로 물려준다.** 같은 블록에 대해
    "물려받은 것이 없다" 와 "둘을 물려받았다" 가 동시에 주장된다.
    """
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            e1:SetOperation(s.op)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            local e2=e1:Clone()
            c:RegisterEffect(e2)
        end
    """)
    assert len(blocks) == 2
    #: 🔴 loader 쪽: ``cloned_from`` 은 적히지만 값은 하나도 물려받지 않았다.
    assert blocks[1].cloned_from == "e1"
    assert blocks[1].effect_types == []
    assert blocks[1].code is None
    #: 🔴 analyzer 쪽: 핸들러 둘을 물려받았다 — 모순이다.
    assert production != unified
    assert dict(production[1][0]) == {"Target": "s.tg", "Operation": "s.op"}
    assert dict(unified[1][0]) == {}


def test_13_consecutive_assignments_to_the_same_variable():
    """🟢 범주 4 — 같은 변수에 연속으로 Effect 를 대입하면 블록이 그만큼 생긴다."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.t1)
            c:RegisterEffect(e1)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.t2)
            c:RegisterEffect(e1)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.t3)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 3
    assert production == unified
    assert [dict(h)["Target"] for h, _f in unified] == ["s.t1", "s.t2", "s.t3"]


def test_14_multi_assignment_unbinds_every_name():
    r"""🔴 다중 대입이 Effect 이름 **둘**을 푼다 — 둘 다 결과가 갈린다."""
    blocks, production, unified = _both("""
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
    assert production != unified
    assert dict(production[0][0]) == {"Cost": "s.cost", "Target": "s.tg"}
    assert dict(production[1][0]) == {"Cost": "s.cost", "Operation": "s.op"}
    #: 재바인딩을 반영하면 둘 다 자기 것만 남는다.
    assert dict(unified[0][0]) == {"Cost": "s.cost"}
    assert dict(unified[1][0]) == {"Cost": "s.cost"}


# ===========================================================================
# 4. 범주 5·6 — 지역/전역 · scope
# ===========================================================================
def test_15_global_effect_is_gated_out_on_both_paths():
    """🟢 범주 5 — ``Effect.GlobalEffect`` 는 게이트가 거부한다 (양쪽 공유)."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local ge1=Effect.GlobalEffect()
            ge1:SetOperation(s.gop)
            Duel.RegisterEffect(ge1,0)
            local e1=Effect.CreateEffect(c)
            e1:SetOperation(s.op)
            c:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 1
    assert blocks[0].index == "e1"
    assert production == unified
    assert dict(unified[0][0]) == {"Operation": "s.op"}


def test_16_global_effect_rebinding_is_identical():
    """🟢 범주 5 — 전역 효과 변수의 재바인딩도 두 경로가 같다 (블록이 없다)."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local ge1=Effect.GlobalEffect()
            ge1:SetOperation(s.gop)
            Duel.RegisterEffect(ge1,0)
            ge1=nil
            ge1:SetTarget(s.tg)
        end
    """)
    assert blocks == []
    assert production == unified == []


def test_17_same_name_in_different_functions_is_identical():
    """🟢 범주 6 — 같은 이름이 다른 함수에 있어도 두 경로가 같다."""
    blocks, production, unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetTarget(s.tg)
            c:RegisterEffect(e1)
        end
        function s.op(e,tp)
            local c=e:GetHandler()
            local e1=Effect.CreateEffect(c)
            e1:SetOperation(s.op2)
            tc:RegisterEffect(e1)
        end
    """)
    assert len(blocks) == 2
    assert production == unified
    #: 🔴 두 번째 블록이 첫 번째의 ``Target`` 을 물려받지 않는다.
    assert dict(unified[0][0]) == {"Target": "s.tg"}
    assert dict(unified[1][0]) == {"Operation": "s.op2"}
    #: 소속 함수도 바르게 나뉜다 — ``is_registered`` 가 이 값에 달려 있다.
    assert [f for _h, f in unified] == ["initial_effect", "op"]


def test_18_variable_name_identity_is_not_object_identity():
    r"""🔴 이름이 같다고 객체가 같다고 보지 않는다 — ``index`` 는 유일하지 않다."""
    blocks, _production, _unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            c:RegisterEffect(e1)
        end
        function s.op(e,tp)
            local e1=Effect.CreateEffect(c)
            tc:RegisterEffect(e1)
        end
    """)
    assert [s.index for s in blocks] == ["e1", "e1"]
    assert blocks[0] is not blocks[1]
    #: 식별자는 ``index`` 가 아니라 ``ordinal`` 이다.
    assert EffectRef(1, 0) != EffectRef(1, 1)


# ===========================================================================
# 5. 범주 8·9 — 생성 순서 · EffectRef
# ===========================================================================
def test_19_block_order_follows_source_order_on_both_paths():
    """🟢 범주 8 — 두 경로가 **같은 원문 순서**로 블록을 쌓는다 (전수)."""
    mismatch = 0
    checked = 0
    for path in _script_paths():
        body = _body(path)
        positions = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                positions.append((m.start(), m.group(2)))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                positions.append((m.start(), m.group(2)))
        positions.sort()
        blocks = _loader_blocks(path)
        checked += len(blocks)
        if [name for _p, name in positions] != [s.index for s in blocks]:
            mismatch += 1
    assert checked == BLOCK_TOTAL
    assert mismatch == 0


def test_20_effect_ref_resolves_to_the_same_block_on_both_paths(repo):
    """🟢 범주 9 — ``EffectRef(card_id, ordinal)`` 이 양쪽에서 같은 자리를 가리킨다."""
    for card_id in PHASE32_CARDS:
        card = repo.get(card_id)
        refs = effect_refs(card)
        entries = _analyzer_entries(PROJECT_ROOT / f"c{card_id}.lua")
        assert len(refs) == len(card.script.effects) == len(entries)
        for i, ref in enumerate(refs):
            assert ref == EffectRef(card_id, i)
            assert ref.resolve(card) is card.script.effects[i]
        assert [r.ordinal for r, _s in iter_effects(card)] == list(range(len(refs)))


def test_21_append_only_design_is_preserved(repo):
    """🟢 ``ordinal`` 은 **append-only** 다 — 재바인딩이 자리를 바꾸지 않는다."""
    moved = 0
    for path in _script_paths():
        blocks = _loader_blocks(path)
        body = _body(path)
        starts = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                starts.append(m.start())
        for m in _RE_CLONE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), _clone_source(m)):
                starts.append(m.start())
        starts.sort()
        if len(starts) != len(blocks) or starts != sorted(starts):
            moved += 1
    assert moved == 0


# ===========================================================================
# 6. 범주 12 — 전수 집계와 UNKNOWN 처리
# ===========================================================================
def test_22_rebind_match_census_by_category():
    r"""🔴 §4 전수 집계 — **정규식 매치 수를 Effect 재바인딩 수로 쓰지 않는다.**

    67,226 매치 → 81,688 이름 → 그중 Effect 변수는 **30**. 2,240배 차이다.
    """
    matches = 0
    scripts = set()
    local_decl = 0
    for path in _script_paths():
        body = _body(path)
        found = list(_RE_REBIND.finditer(body))
        if found:
            scripts.add(path.name)
        matches += len(found)
        for m in found:
            if re.match(r"\s*local\b", body[m.start():m.start() + 10]):
                local_decl += 1
    assert matches == REBIND_MATCHES
    assert len(scripts) == REBIND_SCRIPTS
    assert local_decl == REBIND_LOCAL_DECL
    #: 🔴 매치 하나가 이름 여럿을 풀 수 있다 (다중 대입).
    assert matches < UNBIND_EVENTS


def test_23_only_thirty_sites_unbind_an_effect_variable():
    r"""🔴 이름 단위 unbind 81,688건 가운데 **Effect 변수**를 푸는 것은 30건."""
    events = 0
    effect_vars = 0
    plain_vars = 0
    by_rhs: collections.Counter = collections.Counter()
    for path in _script_paths():
        body = _body(path)
        ev = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                ev.append((m.start(), "create", m.group(2), None))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                ev.append((m.start(), "clone", m.group(2), None))
        for m in _RE_REBIND.finditer(body):
            ev.append((m.start(), "rebind", m.group(1), m.end()))
        ev.sort(key=lambda e: (e[0], _ORDER[e[1]]))
        bound: set[str] = set()
        for _pos, kind, payload, end in ev:
            if kind == "rebind":
                for name in payload.split(","):
                    name = name.strip()
                    events += 1
                    if name in bound:
                        effect_vars += 1
                        bound.discard(name)
                        tail = body[end:end + 80].strip()
                        head = re.match(r"([A-Za-z_][\w.]*(?:\s*:\s*\w+)?)\s*[({]", tail)
                        by_rhs[head.group(1) if head else "<기타>"] += 1
                    else:
                        plain_vars += 1
            else:
                bound.add(payload)
    assert events == UNBIND_EVENTS
    assert effect_vars == UNBIND_EFFECT_VARS
    assert plain_vars == UNBIND_PLAIN_VARS
    #: 그 30건의 RHS 는 전부 **보조 함수나 런타임 조회**다 — Effect alias 가 아니다.
    assert set(by_rhs) <= {
        "aux.createContinuousLizardCheck", "table.unpack", "e:GetLabelObject",
        "reglevel", "Duel.IsPlayerAffectedByEffect", "aux.AddNormalSummonProcedure",
        "s.tempregister", "aux.CreateWitchcrafterReplace", "e1:GetLabelObject",
    }, dict(by_rhs)
    assert sum(by_rhs.values()) == UNBIND_EFFECT_VARS


def test_24_no_corpus_site_actually_diverges():
    r"""🔴 **0 의 이유.** 두 경로가 갈릴 수 있는 두 자리가 코퍼스에 0건이다.

    (a) 풀린 변수에 analyzer 의 네 핸들러 설정자가 오는 자리
    (b) 풀린 변수를 부모로 쓰는 ``Clone``
    """
    handler_after_unbind = 0
    clone_from_unbound = 0
    for path in _script_paths():
        body = _body(path)
        ev = []
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                ev.append((m.start(), "create", m.group(2)))
        for m in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(m)
            if _is_card_effect(body, m.group(1), m.group(2), src_var):
                ev.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
        for m in _RE_REBIND.finditer(body):
            ev.append((m.start(), "rebind", m.group(1)))
        for m in analyzer_module._RE_SETTER.finditer(body):
            ev.append((m.start(), "set", m.group(1)))
        ev.sort(key=lambda e: (e[0], _ORDER[e[1]]))
        bound: set[str] = set()
        stale: set[str] = set()
        for _pos, kind, payload in ev:
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
                dst, src = payload.split("=", 1)
                if src in stale:
                    clone_from_unbound += 1
                bound.add(dst)
                stale.discard(dst)
            elif payload in stale:
                handler_after_unbind += 1
    assert handler_after_unbind == DIVERGENT_HANDLER_SITES
    assert clone_from_unbound == DIVERGENT_CLONE_PARENTS


def test_25_unknown_assignments_are_not_inferred():
    r"""🟢 범주 12 — 알 수 없는 대입을 **추론하지 않는다.**

    loader 는 설정자를 **버린다** (값을 만들지 않는다). "추적할 수 없다" 와
    "잘못 추적한다" 는 다른 결과이고, 전자여야 한다.
    """
    blocks, _production, _unified = _both("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            local e2=Fusion.CreateSummonEff(c,s.f)
            e2:SetCode(EVENT_TO_HAND)
            e2:SetCategory(CATEGORY_DESTROY)
        end
    """)
    #: 보조 함수의 반환값은 블록이 되지 않고, 그 설정자는 앞 블록을 오염시키지 않는다.
    assert len(blocks) == 1
    assert blocks[0].code == "EVENT_FREE_CHAIN"
    assert blocks[0].categories == []


# ===========================================================================
# 7. 남은 구조 차이 — D2 · D3
# ===========================================================================
def test_26_no_event_position_ties_exist_today():
    r"""🔴 D2 — ``_EVENT_ORDER`` 는 지금 **한 번도 발동하지 않는다.**

    같은 byte offset 에 두 종류 이벤트가 겹치는 자리가 코퍼스에 0건이므로,
    analyzer 의 단순 정렬이 **결과상 같다.** 방어적 장치로서는 유지한다.
    """
    ties = 0
    for path in _script_paths():
        body = _body(path)
        at: dict[int, set] = collections.defaultdict(set)
        for m in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), None):
                at[m.start()].add("create")
        for m in _RE_CLONE_EFFECT.finditer(body):
            if _is_card_effect(body, m.group(1), m.group(2), _clone_source(m)):
                at[m.start()].add("clone")
        for m in _RE_REBIND.finditer(body):
            at[m.start()].add("rebind")
        for m in loader_module._RE_SETTER.finditer(body):
            at[m.start()].add("set")
        ties += sum(1 for kinds in at.values() if len(kinds) > 1)
    assert ties == EVENT_POSITION_TIES


def test_27_the_two_setter_sets_are_disjoint():
    r"""🔴 D3 — 두 경로가 소비하는 설정자 집합이 **겹치지 않는다.**

    그래서 갈릴 수 있는 자리가 "핸들러 설정자가 풀린 변수에 오는 자리" 하나로
    좁혀진다. ``SetTargetRange`` 가 ``Set(Target)`` 에 걸리지 않는 것도 확인한다.
    """
    assert LOADER_HANDLED & ANALYZER_HANDLED == frozenset()
    #: ``SetTargetRange(`` 는 analyzer 의 정규식에 걸리지 않는다.
    assert analyzer_module._RE_SETTER.search("e1:SetTargetRange(0,1)") is None
    assert analyzer_module._RE_SETTER.search("e1:SetTarget(s.tg)") is not None
    #: 전수 호출 수
    counts: collections.Counter = collections.Counter()
    for path in _script_paths():
        for m in analyzer_module._RE_SETTER.finditer(_body(path)):
            counts[m.group(2)] += 1
    assert dict(counts) == ANALYZER_SETTER_CALLS
    assert sum(counts.values()) == ANALYZER_SETTER_TOTAL


def test_28_variable_name_scope_is_shared_between_the_paths():
    r"""🟢 변수명 범위는 두 경로가 **같아야** 한다 (3-F-28 의 계약)."""
    loader_var = loader_module._RE_SETTER.pattern.split(r"\s*:\s*")[0]
    analyzer_var = analyzer_module._RE_SETTER.pattern.split(r"\s*:\s*")[0]
    assert loader_var == analyzer_var == r"\b([A-Za-z_]\w*)"


# ===========================================================================
# 8. 범주 11 — Phase 3-F-27 ~ 32 회귀
# ===========================================================================
def test_29_phase_3f32_clone_forms_are_preserved():
    """🟢 3-F-32 가 인정한 세 ``Clone`` 형태가 그대로다."""
    for card_id, (count, ordinal, code, parent) in PHASE32_CARDS.items():
        blocks = _loader_blocks(PROJECT_ROOT / f"c{card_id}.lua")
        assert len(blocks) == count, card_id
        assert blocks[ordinal].code == code, card_id
        assert blocks[ordinal].cloned_from == parent, card_id
    #: 세 형태 전부 정규식이 받는다.
    for rhs in ("e1:Clone()", "e1:Clone(e1)", "Effect.Clone(e1)"):
        assert _RE_CLONE_EFFECT.search(f"local e2={rhs}") is not None, rhs


def test_30_the_group_clone_counter_example_is_preserved():
    """🟢 3-F-32 의 반례 — Group 의 ``Clone`` 은 블록이 되지 않는다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    body = _body(path)
    assert ":Clone()" in body
    assert [m.group(0) for m in _RE_CLONE_EFFECT.finditer(body)] == []
    blocks = _loader_blocks(path)
    assert [s.index for s in blocks] == ["e1"]
    #: analyzer 쪽 목록도 같다.
    assert len(_analyzer_entries(path)) == 1


def test_31_phase_3f31_label_object_stays_unknown():
    r"""🟢 3-F-31 — ``e:GetLabelObject()`` 뒤 설정자는 **계속 버려진다.**"""
    blocks = _loader_blocks(PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua")
    #: 그 세 ``SetCategory`` 가 어느 블록에도 붙지 않았다.
    assert all(spec.categories == [] for spec in blocks), [
        (s.index, s.categories) for s in blocks
    ]
    body = _body(PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua")
    assert body.count("SetCategory(") >= 3


def test_32_phase_3f27_settype_replacement_is_preserved():
    """🟢 3-F-27 — ``Clone`` 뒤 ``SetType`` 은 물려받은 목록을 **덮어쓴다.**"""
    blocks = _loader_blocks(PROJECT_ROOT / "c324483.lua")
    cloned = [s for s in blocks if s.cloned_from is not None]
    assert cloned
    assert cloned[0].effect_types == ["QUICK_O"]
    assert "IGNITION" not in cloned[0].effect_types


def test_33_the_corpus_totals_match_the_phase_3f32_baseline():
    """🟢 기준 수치가 그대로다 — 이 Phase 는 production 을 바꾸지 않았다."""
    blocks = sum(len(_loader_blocks(p)) for p in _script_paths())
    assert len(_script_paths()) == SCRIPT_COUNT
    assert blocks == BLOCK_TOTAL


# ===========================================================================
# 9. 범주 13 — Engine V1 · AI/Search 불변성
# ===========================================================================
def test_34_engine_v1_definitions_are_untouched():
    """🟢 Engine V1 의 16개 정의가 전부 ``ordinal 0`` 이고 그대로다."""
    from engine.effect.library import EFFECT_LIBRARY
    refs = {(e.definition.effect_ref.card_id, e.definition.effect_ref.ordinal)
            for e in EFFECT_LIBRARY}
    assert len(EFFECT_LIBRARY) == 16
    assert {ordinal for _c, ordinal in refs} == {0}
    assert {c for c, _o in refs} & set(PHASE32_CARDS) == set()


def test_35_state_hash_is_structurally_independent_of_binding():
    """🟢 ``state_hash`` 의 정규 표현에 블록·바인딩이 들어가지 않는다 (AST)."""
    from engine.state.game_state import GameState
    import inspect
    source = textwrap.dedent(inspect.getsource(GameState.canonical_state))
    tree = ast.parse(source)
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    names = {n.attr for n in ast.walk(returns[0]) if isinstance(n, ast.Attribute)}
    for forbidden in ("effects", "effect_count", "script", "handlers"):
        assert forbidden not in names, forbidden
    assert {"players", "turn", "uses", "rule_uses", "result"} <= names


def test_36_search_digest_pins_are_unchanged():
    r"""🟢 결정 digest 가 그대로다 — 이 Phase 는 duel 에 닿지 않는다.

    🔴 **이 파일은 digest 문자열을 담지 않는다.** 처음에는 리터럴을 적고
    "그것을 담은 파일 수" 를 셌는데, 그러면 **이 파일이 다른 테스트의
    집계를 부풀린다** — 실제로 Phase 3-F-32 의 ``test_42`` ("핀 7개")가
    8 을 보고 깨졌다. 리터럴을 적는 파일이 하나 늘 때마다 그 숫자를 올리는
    것은 **번지는 수정**이므로, 대신 **기존 핀에서 AST 로 읽는다.**

    (3-F-32 는 같은 함정을 자기 파일에서 겪고 주석으로 남겼는데, 한 Phase
    만에 **반대 방향**으로 재발했다. 위험 N15.)
    """
    pin_files = []
    digests: set[str] = set()
    counts: collections.Counter = collections.Counter()
    for path in sorted(Path(PROJECT_ROOT / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"[0-9a-f]{64}", node.value)
        }
        if found:
            pin_files.append(path.name)
            digests |= found
            for value in found:
                counts[value] += 1

    #: 🔴 "핀이 하나뿐" 이라고 썼다가 틀렸다 — 64자 16진수 상수가 **3종**이다.
    #: duel 결정 digest 하나와 ``test_validation_code_*`` 의 서로 다른 핀 둘.
    #: 그래서 **여러 파일이 공유하는 쪽**을 duel digest 로 골라낸다.
    shared = [d for d in digests if counts[d] >= 7]
    assert len(shared) == 1, {d[:16]: counts[d] for d in digests}
    digest = shared[0]
    #: 🔴 그 핀을 담은 파일이 **8개**다 — 원래 핀 7개 + Phase 3-F-32 가
    #: 자기 파일 제외 검사를 넣은 파일 1개.
    assert counts[digest] == 8, counts[digest]
    assert len(digest) == 64
    #: 나머지 둘은 duel digest 가 아니다 — 각각 한 파일에만 있다.
    assert sorted(counts[d] for d in digests if d != digest) == [1, 1]


def test_37_engine_and_agent_never_read_the_binding_fields():
    r"""🟢 ``engine/`` · ``agent/`` 가 바인딩 산출물을 읽지 않는다.

    🔴 이름만 보고 판단하지 않는다 — ``.code`` · ``.index`` 는 다른 클래스에도
    있다 (3-F-28·3-F-30 이 그 함정에 각각 빠졌다). ``EffectSpec`` **에만**
    있는 칸으로 본다.
    """
    unique = ("effect_types", "target_ranges", "cloned_from", "count_limit")
    for package in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            assert attrs & set(unique) == set(), (path.name, attrs & set(unique))


def test_38_the_analyzer_result_is_not_persisted_to_disk():
    r"""🔴 analyzer 산출물은 **디스크에 캐시되지 않는다.**

    그래서 analyzer 를 고쳐도 ``LuaScriptSource._signature()`` 를 올릴 필요가
    없다 — ``_cache`` 는 인스턴스 안의 메모리 dict 하나다.
    """
    tree = ast.parse(Path(analyzer_module.__file__).read_text(encoding="utf-8"))
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            calls.add(node.attr)
    for persistent in ("write_text", "dump", "load_cached", "replace"):
        assert persistent not in calls, persistent
    #: 캐시 서명은 loader 쪽에만 있고 이 Phase 가 올리지 않았다.
    from sources.lua_loader import LuaScriptSource
    assert LuaScriptSource(PROJECT_ROOT)._signature().startswith(CACHE_PREFIX)


# ===========================================================================
# 10. 계약 — 이 Phase 가 production 을 바꾸지 않았다
# ===========================================================================
def test_39_this_phase_changed_no_production_file():
    r"""🔴 §5 — 두 경로가 같은 결과를 내므로 **production 을 바꾸지 않았다.**"""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    production = {
        name for name in changed
        if name.endswith(".py") and not name.startswith("tests/")
    }
    assert production == set(), production
    assert not any(name.endswith(".lua") for name in changed)
    assert not any(name.endswith("README.md") for name in changed)
    assert not any(
        name.startswith(("engine/", "agent/", "core/", "sources/", "analysis/"))
        for name in changed
    )


def test_40_the_rebind_rule_still_lives_only_in_the_loader():
    r"""🔴 **의도적으로 뒤집힌 테스트.**

    이 Phase(3-F-33)는 "analyzer 에 ``_RE_REBIND`` 가 **없다**" 를 못 박았고,
    그 docstring 에 이렇게 적었다 — *"이 테스트는 '없는 것이 옳다' 는 주장이
    아니다. 지금 상태가 무엇인지를 못 박아, 다음 Phase 가 넣을 때
    **의도적으로** 이 줄을 바꾸게 만든다."*

    🔴 **Phase 3-F-34 가 넣었고, 그래서 이 테스트가 뒤집혔다.** 장치가
    설계대로 작동했다 — 조용히 통과하지 않고 **정확히 한 줄**에서 멈춰
    세웠다 (40개 중 이것 하나만 깨졌다).

    이제 못 박는 것은 "규칙이 **한 곳에 정의되고 양쪽이 import 한다**" 다.
    복사본을 만들면 이 테스트가 다시 깨진다.
    """
    analyzer_source = Path(analyzer_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(analyzer_source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sources.lua_loader":
            imported |= {a.name for a in node.names}
    #: 탐지 규칙과 바인딩 규칙을 **전부** 로더에서 가져온다.
    for name in ("_RE_CREATE_EFFECT", "_RE_CLONE_EFFECT", "_clone_source",
                 "_RE_REBIND", "_EVENT_ORDER"):
        assert name in imported, name
    #: 🔴 그리고 **자기 복사본을 만들지 않는다** — 같은 객체여야 한다.
    assert analyzer_module._RE_REBIND is loader_module._RE_REBIND
    assert analyzer_module._EVENT_ORDER is loader_module._EVENT_ORDER
    assert analyzer_module._RE_CLONE_EFFECT is loader_module._RE_CLONE_EFFECT
    assert analyzer_module._RE_CREATE_EFFECT is loader_module._RE_CREATE_EFFECT
    #: 모듈 안에서 그 이름을 **다시 대입**하지 않았는지 AST 로 본다.
    assigned = {
        t.id
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    for name in ("_RE_REBIND", "_EVENT_ORDER", "_RE_CLONE_EFFECT",
                 "_RE_CREATE_EFFECT"):
        assert name not in assigned, name
