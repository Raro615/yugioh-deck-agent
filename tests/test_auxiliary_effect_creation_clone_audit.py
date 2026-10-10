r"""
Phase 3-F-32 — 보조 함수 생성 Effect 와 미인식 ``Clone`` 형태 감사
==================================================================

핵심 질문
---------
현재 parser 가 ``Effect.CreateEffect`` · ``Effect.GlobalEffect`` ·
``X:Clone()`` 이외의 경로로 **생성되거나 복제되는** Effect 객체를 누락해서,
실제 카드 효과의 분석 결과 또는 ``EffectRef``/``ordinal`` 연결을 잘못
만드는가?

답: **일부는 그랬다.** ``Clone`` 쪽은 실제 버그였고 고쳤다. 보조 함수 쪽은
**저장소에 구현 원문이 없어** 판정할 수 없고 UNKNOWN 으로 남긴다.

측정된 사실 (전부 이 파일의 테스트가 다시 센다)
-----------------------------------------------
``Clone(`` 토큰 2,831개를 정규화하면 서로 다른 형태가 **4개**뿐이다.

=================================== ======= ========== ==================
형태                                 호출    스크립트    판정
=================================== ======= ========== ==================
``V=V:V()``                           2,827      2,213  예전부터 인정
``V=V:V(V)``                              2          2  🔴 이 Phase 가 인정
``V=V.V(V)``                              1          1  🔴 이 Phase 가 인정
``V=V.V(0,V):V()``                        1          1  **반례 — Group clone**
=================================== ======= ========== ==================

수정의 전수 영향: 블록 34,681 → **34,684** (3개 스크립트), 기존 블록의
``ordinal`` 이 움직인 자리는 **1곳**(``c4997565`` ord3 → ord4)뿐이다.

설정자 귀속 3자 비교 (production 이 다루는 7개 설정자 121,636건):

=============== ========= ======== =========
시점             설정자    버려짐   추적
=============== ========= ======== =========
3-F-30 끝         121,636    1,330   120,306
3-F-31 끝         121,636    1,335   120,301
3-F-32 (지금)     121,636    1,330   120,306
=============== ========= ======== =========

🔴 총계가 1,330 으로 되돌아왔지만 **같은 5건이 아니다.** 3-F-31 이 새로
버린 5건은 ``c44887817``(1) · ``c4997565``(1) · ``c52445243``(3) 이고,
이 Phase 가 되살린 5건은 ``c44887817``(1) · ``c4997565``(1) ·
``c56410769``(3) 이다. ``c52445243`` 의 3건은 ``e:GetLabelObject()`` 라서
**계속 UNKNOWN 이 맞고**, ``c56410769`` 의 3건은 3-F-30 이전부터 버려지던
것이다.
"""

from __future__ import annotations

import ast
import inspect
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
    _is_card_effect,
    _RE_BLOCK_COMMENT,
    _RE_CLONE_EFFECT,
    _RE_CREATE_EFFECT,
    _RE_REBIND,
    _RE_SETTER,
    parse_lua_source,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 이 Phase 가 다루는 자리 (전부 실제 Lua 에서 확인했다)
# ---------------------------------------------------------------------------
#: ``local e2=e1:Clone(e1)`` — 인자 있는 콜론 형태
CLONE_WITH_ARG_CARD = 44887817
#: ``local e2=Effect.Clone(e1)`` — 점 형태
DOT_CLONE_CARD = 4997565
#: ``local e3=e2:Clone(c)`` — 인자 있는 콜론 형태, **initial_effect 안**
CLONE_IN_INITIAL_CARD = 56410769
#: 🔴 반례 — ``local tg=Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS):Clone()``
#: 은 **Group** 의 Clone 이다. 블록이 되면 안 된다.
GROUP_CLONE_CARD = 63708033
#: 이 Phase 가 블록을 더한 세 장
CHANGED_CARDS = (DOT_CLONE_CARD, CLONE_WITH_ARG_CARD, CLONE_IN_INITIAL_CARD)

#: production 의 ``set`` 분기가 실제로 다루는 설정자
HANDLED_SETTERS = ("Type", "Code", "Range", "TargetRange",
                   "Category", "Property", "CountLimit")

# --- 전수 측정값 (측정으로 고정한다) ---------------------------------------
SCRIPT_COUNT = 12702
BLOCK_TOTAL = 34684                 # 3-F-31 의 34,681 + 3
CLONE_TOKEN_TOTAL = 2831            # 'Clone(' 토큰
CLONE_EMPTY_PAREN = 2827            # V=V:V()
CLONE_WITH_ARG = 2                  # V=V:V(V)
CLONE_DOT_FORM = 1                  # V=V.V(V)
CLONE_EXPR_RECEIVER = 1             # V=V.V(0,V):V()  — 반례
CREATE_MATCHES, CREATE_BLOCKS, CREATE_REJECTED = 32157, 31937, 220
CLONE_MATCHES, CLONE_BLOCKS, CLONE_REJECTED = 2830, 2747, 83
SETTER_TOTAL, SETTER_TRACKED, SETTER_DROPPED = 121636, 120306, 1330
#: 🔴 Phase 3-F-37 이 ``v9:`` -> ``v10-<shape>:`` 로 바꿨다.
#: ``LuaScriptInfo`` 에 ``effect_offsets`` 와 ``source_digest`` 가 생겨
#: 캐시 모양이 달라졌기 때문이다. 뒤의 ``<shape>`` 는 저장되는 칸 목록의
#: 해시이고 **자동으로** 바뀐다 — 같은 번호 아래에서 칸이 달라지는 사고를
#: 막는다 (3-F-37 작업 중 실제로 겪었고, 기존 테스트 103건이 그래서 한 번
#: 깨졌다). 이 테스트의 주장은 그대로다: **파서 산출물이 달라지면 캐시
#: 서명도 달라져야 한다.**
CACHE_PREFIX = "v10-"


# ---------------------------------------------------------------------------
# 공용 도구
# ---------------------------------------------------------------------------
def _script_paths() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("c*.lua"))


def _body(path: Path) -> str:
    """production 과 **같은 view** — 블록 주석만 지운다."""
    return _RE_BLOCK_COMMENT.sub(
        "", path.read_text(encoding="utf-8", errors="replace")
    )


def _parse(path: Path):
    card_id = int(re.match(r"c(\d+)", path.name).group(1))
    return parse_lua_source(
        card_id, path.name, path.read_text(encoding="utf-8", errors="replace")
    )


def _parse_text(source: str, card_id: int = 1):
    return parse_lua_source(card_id, f"c{card_id}.lua", source)


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


def _events(body: str):
    """production 의 이벤트 재생을 **그 정규식 그대로** 흉내낸다."""
    ev = []
    for m in _RE_CREATE_EFFECT.finditer(body):
        if not _is_card_effect(body, m.group(1), m.group(2), None):
            continue
        ev.append((m.start(), "create", m.group(2)))
    for m in _RE_CLONE_EFFECT.finditer(body):
        src_var = _clone_source(m)
        if not _is_card_effect(body, m.group(1), m.group(2), src_var):
            continue
        ev.append((m.start(), "clone", m.group(2)))
    for m in _RE_REBIND.finditer(body):
        ev.append((m.start(), "rebind", m.group(1)))
    for m in _RE_SETTER.finditer(body):
        ev.append((m.start(), "set", f"{m.group(1)}|{m.group(2)}"))
    ev.sort(key=lambda e: (e[0], loader_module._EVENT_ORDER[e[1]]))
    return ev


def _setter_attribution():
    """(스크립트, offset) -> 귀속된 블록 ordinal(또는 None=버려짐)."""
    out: dict[tuple[str, int], int | None] = {}
    for path in _script_paths():
        body = _body(path)
        bindings: dict[str, int] = {}
        n = 0
        for pos, kind, payload in _events(body):
            if kind == "rebind":
                for name in payload.split(","):
                    bindings.pop(name.strip(), None)
            elif kind in ("create", "clone"):
                bindings[payload] = n
                n += 1
            else:
                var, setter = payload.split("|", 1)
                if setter in HANDLED_SETTERS:
                    out[(path.name, pos)] = bindings.get(var)
    return out


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일.

    🔴 **commit 범위만** 본다. worktree diff 를 섞으면 **다음 Phase 의 수정이
    이 Phase 의 diff 로 새어** 들어온다 (Phase 3-F-31 이 그렇게 3-F-30 의
    테스트를 깼다). 앵커는 SHA 가 아니라 **commit 메시지**다 — 작업 commit 과
    테스트 commit 이 따로이므로 둘 다 잡아야 한다.
    """
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-32:"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        if not shas:
            return set()
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
# 범주 1 — 기존 ``Effect.CreateEffect`` 처리 회귀
# ===========================================================================
def test_01_create_effect_counts_unchanged():
    """``Effect.CreateEffect`` 탐지는 **하나도** 건드리지 않았다."""
    match = ok = rej = 0
    for path in _script_paths():
        body = _body(path)
        for m in _RE_CREATE_EFFECT.finditer(body):
            match += 1
            if _is_card_effect(body, m.group(1), m.group(2), None):
                ok += 1
            else:
                rej += 1
    assert (match, ok, rej) == (CREATE_MATCHES, CREATE_BLOCKS, CREATE_REJECTED)


def test_02_create_effect_minimal_repro():
    """가장 단순한 생성이 그대로 동작한다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
        end
    """))
    assert len(info.effects) == 1
    assert info.effects[0].code == "EVENT_FREE_CHAIN"
    assert info.effects[0].effect_types == ["ACTIVATE"]
    assert info.effects[0].cloned_from is None


def test_03_global_effect_still_gated():
    """``Effect.GlobalEffect`` 는 **게이트가 거부한다** — 이 카드의 효과가 아니다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local ge1=Effect.GlobalEffect()
            ge1:SetType(EFFECT_TYPE_FIELD)
            Duel.RegisterEffect(ge1,0)
        end
    """))
    assert info.effects == []


# ===========================================================================
# 범주 2 — 기존 ``X:Clone()`` 처리 회귀
# ===========================================================================
def test_04_empty_paren_clone_minimal_repro():
    """빈 괄호 Clone 은 예전과 **똑같이** 부모를 물려받는다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_FIELD)
            e1:SetCode(EFFECT_UPDATE_ATTACK)
            e1:SetRange(LOCATION_MZONE)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetCode(EFFECT_UPDATE_DEFENSE)
            c:RegisterEffect(e2)
        end
    """))
    assert len(info.effects) == 2
    assert info.effects[1].cloned_from == "e1"
    assert info.effects[1].code == "EFFECT_UPDATE_DEFENSE"
    #: 🔴 ``ranges`` 는 물려받는다 (설정자가 없으므로 덮어쓰지 않는다).
    assert info.effects[1].ranges == ["MZONE"]


def test_05_empty_paren_clone_corpus_count():
    """``V=V:V()`` 형태가 코퍼스에 2,827건 그대로 있다."""
    pat = re.compile(r"[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\)")
    total = sum(len(pat.findall(_body(p))) for p in _script_paths())
    assert total == CLONE_EMPTY_PAREN


def test_06_clone_gate_rejections_unchanged():
    """🔴 게이트가 거부하는 Clone 83건은 **그대로**다 — 그게 Group clone 방어다."""
    rejected: dict[str, int] = {}
    for path in _script_paths():
        body = _body(path)
        for m in _RE_CLONE_EFFECT.finditer(body):
            if not _is_card_effect(body, m.group(1), m.group(2), _clone_source(m)):
                rejected[m.group(2)] = rejected.get(m.group(2), 0) + 1
    assert sum(rejected.values()) == CLONE_REJECTED
    #: 거부된 이름은 압도적으로 **Group 변수**다 — 이름으로 고른 게 아니라
    #: 게이트가 걸러낸 결과를 그대로 센 것이다.
    assert rejected.get("g", 0) >= 20
    assert rejected.get("rg", 0) >= 15


# ===========================================================================
# 범주 3 — ``Effect.Clone(X)`` 점 형태
# ===========================================================================
def test_07_dot_clone_minimal_repro():
    """``Effect.Clone(e1)`` 이 자식 블록을 만들고, 뒤 설정자가 **그 블록에** 붙는다."""
    info = _parse_text(textwrap.dedent("""
        function s.op(e,tp)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_SINGLE)
            e1:SetCode(EFFECT_DISABLE)
            tc:RegisterEffect(e1)
            local e2=Effect.Clone(e1)
            e2:SetCode(EFFECT_DISABLE_EFFECT)
            tc:RegisterEffect(e2)
        end
    """))
    assert len(info.effects) == 2
    assert info.effects[1].cloned_from == "e1"
    assert info.effects[1].code == "EFFECT_DISABLE_EFFECT"
    #: 부모의 code 가 남아 있으면 안 된다.
    assert info.effects[0].code == "EFFECT_DISABLE"


def test_08_clone_source_helper_reads_both_groups():
    """``_clone_source`` 가 두 형태에서 원본 변수를 올바로 돌려준다."""
    colon = _RE_CLONE_EFFECT.search("local e2=e1:Clone(e1)")
    dot = _RE_CLONE_EFFECT.search("local e2=Effect.Clone(e1)")
    plain = _RE_CLONE_EFFECT.search("local e2=e1:Clone()")
    assert _clone_source(colon) == "e1"
    assert _clone_source(dot) == "e1"
    assert _clone_source(plain) == "e1"
    #: 콜론 형태는 3번, 점 형태는 4번 그룹이다 — 번호를 직접 쓰면 틀린다.
    assert (colon.group(3), colon.group(4)) == ("e1", None)
    assert (dot.group(3), dot.group(4)) == (None, "e1")


def test_09_dot_clone_corpus_count_is_one():
    """점 형태는 코퍼스 전체에 **1건**뿐이다 (``c4997565``)."""
    pat = re.compile(r"[A-Za-z_]\w*\s*=\s*Effect\s*\.\s*Clone\s*\(")
    hits = [(p.name, len(pat.findall(_body(p))))
            for p in _script_paths() if pat.search(_body(p))]
    assert len(hits) == CLONE_DOT_FORM
    assert hits[0][0] == f"c{DOT_CLONE_CARD}.lua"


def test_10_dot_form_equals_method_form_corpus_evidence():
    r"""🔴 ``Effect.Clone(e1) == e1:Clone()`` 의 근거는 **코퍼스 안에** 있다.

    라이브러리 원문은 저장소에 없다 (``test_23`` 참고). 그래서 이름으로
    짐작하는 대신, 같은 바인딩 관례가 코퍼스에서 지켜지는지를 센다.
    """
    dot = re.compile(r"(?<![\w.])(Effect|Card|Group)\.(\w+)")
    colon = re.compile(r"[A-Za-z_]\w*\s*:\s*(\w+)\s*\(")
    dot_counts: dict[tuple[str, str], int] = {}
    colon_counts: dict[str, int] = {}
    for path in _script_paths():
        body = _body(path)
        for m in dot.finditer(body):
            key = (m.group(1), m.group(2))
            dot_counts[key] = dot_counts.get(key, 0) + 1
        for m in colon.finditer(body):
            colon_counts[m.group(1)] = colon_counts.get(m.group(1), 0) + 1
    top = sorted(dot_counts.items(), key=lambda kv: -kv[1])[:40]
    both = [k for k, _ in top if colon_counts.get(k[1], 0) > 0]
    #: 상위 40개 가운데 37개가 같은 이름으로 콜론 메서드로도 쓰인다.
    assert len(both) == 37
    #: 나머지 셋은 진짜 **정적 생성자**다 — 콜론 메서드가 0이다.
    only_static = {k[0] + "." + k[1] for k, _ in top if colon_counts.get(k[1], 0) == 0}
    assert only_static == {"Effect.CreateEffect", "Group.FromCards", "Group.CreateGroup"}
    #: ``Clone`` 은 콜론 쪽이 압도적이다 — 메서드다.
    assert colon_counts["Clone"] == 2829
    assert dot_counts[("Effect", "Clone")] == 1
    assert dot_counts.get(("Group", "Clone"), 0) == 0


# ===========================================================================
# 범주 3 — 인자 있는 ``Clone`` 형태
# ===========================================================================
def test_11_clone_with_arg_minimal_repro():
    """``e1:Clone(e1)`` — 추가 인자가 있어도 Clone 이다."""
    info = _parse_text(textwrap.dedent("""
        function s.op(e,tp)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_FIELD)
            e1:SetCode(EFFECT_CANNOT_SUMMON)
            Duel.RegisterEffect(e1,tp)
            local e2=e1:Clone(e1)
            e2:SetCode(EFFECT_CANNOT_MSET)
            Duel.RegisterEffect(e2,tp)
        end
    """))
    assert len(info.effects) == 2
    assert info.effects[1].cloned_from == "e1"
    assert info.effects[1].code == "EFFECT_CANNOT_MSET"


def test_12_clone_with_other_arg_minimal_repro():
    """``e2:Clone(c)`` — 인자가 부모와 달라도 receiver 가 부모다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e2=Effect.CreateEffect(c)
            e2:SetType(EFFECT_TYPE_FIELD)
            e2:SetCode(EFFECT_UPDATE_ATTACK)
            c:RegisterEffect(e2)
            local e3=e2:Clone(c)
            e3:SetCode(EFFECT_CANNOT_ATTACK_ANNOUNCE)
            c:RegisterEffect(e3)
        end
    """))
    assert len(info.effects) == 2
    assert info.effects[1].cloned_from == "e2"
    assert info.effects[1].code == "EFFECT_CANNOT_ATTACK_ANNOUNCE"


def test_13_clone_with_arg_corpus_sites():
    """인자 있는 콜론 형태는 코퍼스에 **2건**이다."""
    pat = re.compile(
        r"[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*[^()\n\s][^()\n]*\)"
    )
    hits = sorted(p.name for p in _script_paths() if pat.search(_body(p)))
    assert len(hits) == CLONE_WITH_ARG
    assert hits == [f"c{CLONE_WITH_ARG_CARD}.lua", f"c{CLONE_IN_INITIAL_CARD}.lua"]


def test_14_multiline_clone_is_not_matched():
    """🔴 여러 줄에 걸친 ``Clone(`` 은 받지 않는다 — 어디서 끝나는지 모른다."""
    assert _RE_CLONE_EFFECT.search("local e2=e1:Clone(\n  e1)") is None
    #: 코퍼스에 그런 자리가 없다는 것도 함께 센다.
    pat = re.compile(r"[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\n")
    assert sum(1 for p in _script_paths() if pat.search(_body(p))) == 0


def test_15_nested_paren_clone_is_not_matched():
    """🔴 중첩 괄호 인자도 받지 않는다 — 코퍼스에 없고, 받으면 범위가 흐려진다."""
    assert _RE_CLONE_EFFECT.search("local e2=e1:Clone(f(x))") is None
    assert _RE_CLONE_EFFECT.search("local e2=Effect.Clone(f(e1))") is None


# ===========================================================================
# 범주 11 — 🔴 반례: 정상적인 비-Effect Clone 을 누락으로 오판하지 않는다
# ===========================================================================
def test_16_group_clone_counter_example_makes_no_block():
    """``c63708033`` 의 ``Duel.GetChainInfo(...):Clone()`` 은 **Group** clone 이다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    body = _body(path)
    assert ":Clone()" in body
    #: 정규식이 아예 잡지 않는다 — receiver 가 **식**이기 때문이다.
    assert [m.group(0) for m in _RE_CLONE_EFFECT.finditer(body)] == []
    info = _parse(path)
    assert [s.index for s in info.effects] == ["e1"]
    assert all(s.cloned_from is None for s in info.effects)


def test_17_expression_receiver_is_excluded_by_design():
    """🔴 receiver 를 **맨 식별자**로 묶어 둔 것이 Group clone 방어다."""
    #: 식 receiver — 받지 않는다
    assert _RE_CLONE_EFFECT.search(
        "local tg=Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS):Clone()"
    ) is None
    #: 맨 식별자 receiver — 받는다 (게이트가 다시 판단한다)
    assert _RE_CLONE_EFFECT.search("local e2=e1:Clone()") is not None


def test_18_group_variable_clone_rejected_by_gate():
    """맨 식별자라도 이름이 Group 쪽이면 **게이트**가 거부한다."""
    source = textwrap.dedent("""
        function s.op(e,tp)
            local g=Duel.GetMatchingGroup(nil,tp,LOCATION_MZONE,0,nil)
            local rg=g:Clone()
            rg:SetType(EFFECT_TYPE_FIELD)
        end
    """)
    info = _parse_text(source)
    assert info.effects == []


def test_19_corpus_has_exactly_four_clone_shapes():
    """``Clone(`` 토큰 2,831개를 정규화하면 형태가 **4개**뿐이다."""
    any_clone = re.compile(
        r"[A-Za-z_][\w.]*\s*[:.]\s*Clone\s*\(|(?<![\w.])Clone\s*\("
    )
    shapes: dict[str, int] = {}
    total = 0
    for path in _script_paths():
        body = _body(path)
        for m in any_clone.finditer(body):
            total += 1
            line_start = body.rfind("\n", 0, m.start()) + 1
            i = body.index("(", m.start())
            depth = 0
            while i < len(body):
                if body[i] == "(":
                    depth += 1
                elif body[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            norm = re.sub(r"\s+", "", body[line_start:i + 1].strip())
            norm = re.sub(r"[A-Za-z_]\w*", "V", norm)
            shapes[norm] = shapes.get(norm, 0) + 1
    assert total == CLONE_TOKEN_TOTAL
    assert shapes == {
        "V=V:V()": CLONE_EMPTY_PAREN,
        "V=V:V(V)": CLONE_WITH_ARG,
        "V=V.V(V)": CLONE_DOT_FORM,
        "V=V.V(0,V):V()": CLONE_EXPR_RECEIVER,
    }


# ===========================================================================
# 범주 4·5 — 보조 함수가 만든 Effect
# ===========================================================================
def test_20_named_helper_call_census():
    """지시서 §2 가 지명한 6개 함수의 호출 수·스크립트 수 (실측).

    🔴 ``f{...}`` 는 Lua 의 **테이블 호출 설탕**이므로 호출로 센다 —
    ``f(...)`` 만 세면 ``Fusion.CreateSummonEff`` 가 5건 적게 나온다.
    """
    expected = {
        "Fusion.CreateSummonEff": (89, 89),
        "Ritual.CreateProc": (23, 23),
        "Ritual.AddProcGreater": (19, 19),
        "aux.AddNormalSummonProcedure": (56, 56),
        "Spirit.AddProcedure": (41, 41),
        "aux.CreateWitchcrafterReplace": (2, 2),
    }
    bodies = [_body(p) for p in _script_paths()]
    for name, (calls, scripts) in expected.items():
        pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"\s*[({]")
        got_calls = sum(len(pat.findall(b)) for b in bodies)
        got_scripts = sum(1 for b in bodies if pat.search(b))
        assert (got_calls, got_scripts) == (calls, scripts), name


def test_21_helper_return_value_makes_no_block():
    """보조 함수의 반환값은 블록이 **되지 않는다** — 그게 현재 계약이다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Fusion.CreateSummonEff(c,s.fusfilter)
            e1:SetCountLimit(1,id)
            c:RegisterEffect(e1)
        end
    """))
    assert info.effects == []


def test_22_helper_setters_are_dropped_not_misattributed():
    """🔴 **버려진다**(UNKNOWN) — 앞 블록에 **붙지 않는다**.

    "추적할 수 없다" 와 "잘못 추적한다" 는 다른 결과다. 보조 함수 뒤의
    설정자는 전자여야 한다.
    """
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            local e1=Ritual.CreateProc(c,s.filter)
            e1:SetCode(EVENT_TO_HAND)
            e1:SetCategory(CATEGORY_DESTROY)
            c:RegisterEffect(e1)
        end
    """))
    assert len(info.effects) == 1
    #: 보조 함수 뒤의 ``SetCode``/``SetCategory`` 가 첫 블록을 오염시키지 않았다.
    assert info.effects[0].code == "EVENT_FREE_CHAIN"
    assert info.effects[0].categories == []


def test_23_library_source_is_absent_from_repository():
    """🔴 보조 함수의 **구현 원문이 저장소에 없다** — 그래서 UNKNOWN 이다.

    저장소의 Lua 는 ``c*.lua`` 카드 스크립트뿐이고, EDOPro 의 공유
    라이브러리(``utility.lua`` · ``proc_fusion.lua`` 등)는 들어 있지 않다.
    생성 개수를 **추측하지 않는** 근거가 이것이다.
    """
    all_lua = sorted(PROJECT_ROOT.glob("*.lua"))
    assert len(all_lua) == SCRIPT_COUNT
    assert all(re.fullmatch(r"c\d+\.lua", p.name) for p in all_lua)
    #: 지명된 함수들의 **정의**가 코퍼스 어디에도 없다.
    for name in ("CreateSummonEff", "CreateProc", "AddNormalSummonProcedure",
                 "CreateWitchcrafterReplace"):
        pat = re.compile(r"function\s+\w+[.:]" + re.escape(name))
        assert not any(pat.search(_body(p)) for p in _script_paths()), name


def test_24_two_helpers_are_defined_inside_the_corpus():
    """🔴 반례 — 코퍼스 **안에** 정의된 보조 함수가 2개 있다.

    이 둘은 원문이 있으므로 생성 개수를 **확인할 수 있다**. "보조 함수는
    전부 UNKNOWN" 이라고 뭉개면 안 된다.
    """
    found = {}
    for path in _script_paths():
        body = _body(path)
        for m in re.finditer(r"(?:local\s+)?function\s+((?:s\.)?\w+)\s*\(", body):
            if m.group(1) in ("reglevel", "s.tempregister"):
                found[m.group(1)] = path.name
    assert found == {"reglevel": "c46005939.lua",
                     "s.tempregister": "c65351555.lua"}


def test_25_in_corpus_helper_creates_counted_once_at_definition():
    """``reglevel`` 은 정의 안에서 ``Effect.CreateEffect`` 를 **1번** 쓴다.

    🔴 호출은 5번(대입 4번)이지만 파서는 블록을 **1개**만 만든다. 이것은
    버그가 아니라 설계다 — ``EffectSpec`` 은 **정적 정의**이고 런타임
    인스턴스 수가 아니다.
    """
    path = PROJECT_ROOT / "c46005939.lua"
    body = _body(path)
    #: 정의는 ``local function reglevel(c,tc,lv)`` 로 시작해 ``\nend`` 로 끝난다.
    start = body.index("local function reglevel")
    definition = body[start:body.index("\nend", start)]
    calls = len(re.findall(r"(?<![\w.])reglevel\s*\(", body))
    #: 호출 5건 가운데 1건은 정의 자신의 머리글이다 → 실제 호출 4건.
    assert calls == 5
    #: 🔴 정의 안에서 Effect 를 **1개** 만든다 — 원문으로 확인할 수 있다.
    assert definition.count("Effect.CreateEffect") == 1
    assert "return e1" in definition
    #: 파일 전체에는 생성이 3곳, clone 이 1곳 → 블록 4개.
    assert body.count("Effect.CreateEffect") == 3
    info = _parse(path)
    assert [s.index for s in info.effects] == ["e1", "e1", "e1", "e2"]
    #: 🔴 **호출 자리는 블록을 하나도 더하지 않는다.** 블록 수는 원문의
    #: 생성/복제 등장 수(3+1)와 같고, 런타임 인스턴스 수(호출 4번)가 아니다.
    assert len(info.effects) == body.count("Effect.CreateEffect") + 1


def test_26_in_corpus_helper_with_two_returns():
    """``s.tempregister`` 는 정의 안에서 Effect 를 **2개** 만들고 둘을 돌려준다."""
    path = PROJECT_ROOT / "c65351555.lua"
    body = _body(path)
    #: 정의 구간을 잘라서 **원문으로** 센다.
    start = body.index("function s.tempregister")
    definition = body[start:body.index("\nend", start)]
    assert definition.count("Effect.CreateEffect") == 2
    assert re.search(r"return\s+e1\s*,\s*e2", definition)
    #: 다중 대입으로 받는 자리가 2곳이고, 둘 다 왼쪽 이름이 2개다.
    multi = re.findall(
        r"local\s+([A-Za-z_]\w*\s*,\s*[A-Za-z_]\w*)\s*=\s*s\.tempregister", body)
    assert len(multi) == 2
    info = _parse(path)
    #: 🔴 호출 자리는 블록을 더하지 않는다 — 블록 수는 원문의 생성 등장 수다.
    assert len(info.effects) == body.count("Effect.CreateEffect")
    assert [s.index for s in info.effects] == ["e1", "e2", "e1", "e3", "e1", "e2"]


def test_27_multi_assign_helper_sites_unbind_every_name():
    """🔴 다중 대입은 **왼쪽 이름 전부**를 푼다 — 하나만 풀면 나머지가 오염된다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_ACTIVATE)
            c:RegisterEffect(e1)
            local e2=Effect.CreateEffect(c)
            e2:SetType(EFFECT_TYPE_IGNITION)
            c:RegisterEffect(e2)
            local e1,e2=Spirit.AddProcedure(c,true)
            e1:SetCategory(CATEGORY_DESTROY)
            e2:SetCategory(CATEGORY_DRAW)
        end
    """))
    assert len(info.effects) == 2
    assert info.effects[0].categories == []
    assert info.effects[1].categories == []


def test_28_multi_assign_helper_census():
    """Effect 로 쓰이는 다중 대입 보조 함수 자리 수 (실측)."""
    pat = re.compile(
        r"(?:(?<=^)|(?<=[;\s\)])) *(?:local\s+)?"
        r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*=(?!=)\s*"
        r"((?:Spirit\.AddProcedure|aux\.AddKaijuProcedure"
        r"|Effect\.CreateMysteruneQPEffect|s\.tempregister))\s*[({]",
        re.M)
    counts: dict[str, int] = {}
    for path in _script_paths():
        for m in pat.finditer(_body(path)):
            counts[m.group(2)] = counts.get(m.group(2), 0) + 1
    assert counts == {
        "Spirit.AddProcedure": 3,
        "aux.AddKaijuProcedure": 7,
        "Effect.CreateMysteruneQPEffect": 1,
        "s.tempregister": 2,
    }
    assert sum(counts.values()) == 13


def test_29_table_call_sugar_is_a_call():
    """``Fusion.CreateSummonEff{...}`` 도 호출이다 — 5곳에서 쓰인다."""
    pat = re.compile(r"(?<![\w.])Fusion\.CreateSummonEff\s*\{")
    hits = sorted(p.name for p in _script_paths() if pat.search(_body(p)))
    assert len(hits) == 5
    #: 그 자리에서도 반환값은 블록이 되지 않고, 설정자는 버려진다.
    info = _parse_text("local e1=Fusion.CreateSummonEff{handler=c}\ne1:SetCode(EVENT_FREE_CHAIN)")
    assert info.effects == []


# ===========================================================================
# 범주 7 — 변수 재바인딩 이후의 참조
# ===========================================================================
def test_30_rebind_lookahead_matches_clone_regex():
    """🔴 ``_RE_REBIND`` 와 ``_RE_CLONE_EFFECT`` 의 Clone 형태가 **같아야** 한다.

    한쪽만 넓히면 블록은 생기지만 설정자가 계속 버려져서, 파서가 **부모의
    값을 자식의 값처럼 주장**한다 — 블록이 아예 없는 것보다 나쁘다.
    """
    rb = _RE_REBIND.pattern
    for form in (r"Clone\s*\([^()\n]*\)", r"Effect\s*\.\s*Clone\s*\(\s*[A-Za-z_]\w*\s*\)"):
        assert form in rb, form
    #: 실제 동작으로도 확인한다 — 세 형태 전부에서 바인딩이 풀리지 않는다.
    for rhs in ("e1:Clone()", "e1:Clone(e1)", "Effect.Clone(e1)"):
        assert _RE_REBIND.search(f"\tlocal e2={rhs}\n") is None, rhs
    #: 반면 모르는 대입은 **푼다**.
    assert _RE_REBIND.search("\tlocal e2=e:GetLabelObject()\n") is not None


def test_31_rebind_after_clone_still_drops():
    """Clone 뒤에 **모르는 대입**이 오면 그 뒤 설정자는 다시 버려진다."""
    info = _parse_text(textwrap.dedent("""
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            local e2=e1:Clone(e1)
            e2:SetCode(EFFECT_CANNOT_MSET)
            c:RegisterEffect(e2)
            e2=e:GetLabelObject()
            e2:SetCode(EFFECT_UPDATE_ATTACK)
        end
    """))
    assert len(info.effects) == 2
    #: 마지막 ``SetCode`` 가 clone 블록을 덮어쓰지 않았다.
    assert info.effects[1].code == "EFFECT_CANNOT_MSET"


# ===========================================================================
# 범주 8·9 — 생성 순서 · ordinal · EffectRef
# ===========================================================================
def test_32_block_total_and_changed_scripts():
    """전수 블록 수와 **달라진 스크립트가 정확히 3개**임을 다시 센다."""
    total = 0
    per: dict[str, int] = {}
    for path in _script_paths():
        n = len(_parse(path).effects)
        total += n
        per[path.name] = n
    assert total == BLOCK_TOTAL
    assert per[f"c{CLONE_WITH_ARG_CARD}.lua"] == 5
    assert per[f"c{DOT_CLONE_CARD}.lua"] == 5
    assert per[f"c{CLONE_IN_INITIAL_CARD}.lua"] == 3


def test_33_ordinal_follows_source_order_corpus_wide():
    """🔴 3-F-28 의 불변식: ``ordinal`` 은 **원문 등장 순서**다 — 전수 0 불일치."""
    mismatch = 0
    blocks = 0
    for path in _script_paths():
        body = _body(path)
        order = [payload for _pos, kind, payload in _events(body)
                 if kind in ("create", "clone")]
        info = _parse(path)
        blocks += len(info.effects)
        if [s.index for s in info.effects] != order:
            mismatch += 1
    assert blocks == BLOCK_TOTAL
    assert mismatch == 0


def test_34_only_one_existing_ordinal_moved():
    """🔴 기존 블록의 ``ordinal`` 이 움직인 자리는 ``c4997565`` **한 곳**이다.

    새 블록이 **원문 순서**로 끼어들기 때문에, 그 뒤에 생성이 더 있으면
    ``ordinal`` 이 밀린다. 세 장 가운데 그런 장이 하나다.
    """
    info = _parse(PROJECT_ROOT / f"c{DOT_CLONE_CARD}.lua")
    codes = [s.code for s in info.effects]
    #: ord3 이 clone(``e2``), ord4 가 밀려난 ``e3``.
    assert info.effects[3].index == "e2"
    assert info.effects[3].cloned_from == "e1"
    assert codes[3] == "EFFECT_DISABLE_EFFECT"
    assert info.effects[4].index == "e3"
    assert codes[4] == "EFFECT_UPDATE_DEFENSE"
    #: 다른 두 장은 **맨 끝에** 붙어서 기존 ordinal 을 밀지 않았다.
    for cid, last_index in ((CLONE_WITH_ARG_CARD, "e2"), (CLONE_IN_INITIAL_CARD, "e3")):
        eff = _parse(PROJECT_ROOT / f"c{cid}.lua").effects
        assert eff[-1].index == last_index
        assert eff[-1].cloned_from is not None


def test_35_effect_ref_resolves_to_the_block_at_that_ordinal(repo):
    """``EffectRef(card_id, ordinal)`` 이 **그 자리의** spec 을 돌려준다."""
    for cid in CHANGED_CARDS:
        card = repo.get(cid)
        refs = effect_refs(card)
        assert len(refs) == len(card.script.effects)
        for i, ref in enumerate(refs):
            assert ref == EffectRef(cid, i)
            assert ref.resolve(card) is card.script.effects[i]
        pairs = list(iter_effects(card))
        assert [r.ordinal for r, _ in pairs] == list(range(len(refs)))


def test_36_new_block_values_match_the_real_lua():
    """🔴 새 블록의 값이 **실제 Lua 원문**과 한 줄씩 맞는지 확인한다."""
    eff = _parse(PROJECT_ROOT / f"c{CLONE_IN_INITIAL_CARD}.lua").effects[2]
    body = _body(PROJECT_ROOT / f"c{CLONE_IN_INITIAL_CARD}.lua")
    #: 원문에 그 설정자들이 실제로 있다.
    assert "e3:SetProperty(EFFECT_FLAG_IGNORE_IMMUNE)" in body
    assert "e3:SetCode(EFFECT_CANNOT_ATTACK_ANNOUNCE)" in body
    assert "e3:SetTargetRange(0,LOCATION_MZONE)" in body
    assert eff.code == "EFFECT_CANNOT_ATTACK_ANNOUNCE"
    assert eff.properties == ["IGNORE_IMMUNE"]
    assert eff.target_ranges == ["MZONE"]
    assert eff.effect_types == ["FIELD"]      # 부모에게서 물려받았다
    assert eff.cloned_from == "e2"


# ===========================================================================
# 범주 10·12 — UNKNOWN 처리 · 집계 재현성
# ===========================================================================
def test_37_setter_attribution_three_way():
    """🔴 설정자 귀속 전수 집계와, **되살린 5건이 어디인지**."""
    attribution = _setter_attribution()
    dropped = {k for k, v in attribution.items() if v is None}
    assert len(attribution) == SETTER_TOTAL
    assert len(dropped) == SETTER_DROPPED
    assert len(attribution) - len(dropped) == SETTER_TRACKED
    #: 되살린 5건의 스크립트가 **더 이상 버려진 쪽에 없다**.
    restored = {f"c{CLONE_WITH_ARG_CARD}.lua", f"c{DOT_CLONE_CARD}.lua",
                f"c{CLONE_IN_INITIAL_CARD}.lua"}
    assert {name for name, _ in dropped} & restored == set()
    #: 🔴 반면 ``c52445243`` 의 3건은 **계속 버려진다** — ``e:GetLabelObject()``
    #: 는 정적으로 풀 수 없고, UNKNOWN 이 맞다 (3-F-31 N3).
    assert sum(1 for name, _ in dropped if name == "c52445243.lua") == 3


def test_38_dropped_total_returned_by_coincidence_not_identity():
    """🔴 버려짐 총계가 1,330 으로 되돌아온 것은 **우연**이다.

    3-F-31 이 새로 버린 5건과 이 Phase 가 되살린 5건은 **다른 집합**이다
    (겹치는 것은 2건). 숫자가 같다고 "원상 복구" 라고 적으면 거짓이 된다.
    """
    old_clone = re.compile(
        r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*:\s*Clone\s*\(\s*\)")
    old_rebind = re.compile(
        r"(?:(?<=^)|(?<=[;\s\)])) *(?:local\s+)?"
        r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*=(?!=)"
        r"(?!\s*(?:Effect\.(?:CreateEffect|GlobalEffect)\s*\("
        r"|[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\)))", re.M)

    def attribution(clone_re, rebind_re, src_of):
        out = {}
        for path in _script_paths():
            body = _body(path)
            ev = []
            for m in _RE_CREATE_EFFECT.finditer(body):
                if not _is_card_effect(body, m.group(1), m.group(2), None):
                    continue
                ev.append((m.start(), "create", m.group(2)))
            for m in clone_re.finditer(body):
                sv = src_of(m)
                if not _is_card_effect(body, m.group(1), m.group(2), sv):
                    continue
                ev.append((m.start(), "clone", m.group(2)))
            if rebind_re is not None:
                for m in rebind_re.finditer(body):
                    ev.append((m.start(), "rebind", m.group(1)))
            for m in _RE_SETTER.finditer(body):
                ev.append((m.start(), "set", f"{m.group(1)}|{m.group(2)}"))
            ev.sort(key=lambda e: (e[0], loader_module._EVENT_ORDER[e[1]]))
            bindings, n = {}, 0
            for pos, kind, payload in ev:
                if kind == "rebind":
                    for nm in payload.split(","):
                        bindings.pop(nm.strip(), None)
                elif kind in ("create", "clone"):
                    bindings[payload] = n
                    n += 1
                else:
                    var, st = payload.split("|", 1)
                    if st in HANDLED_SETTERS:
                        out[(path.name, pos)] = bindings.get(var)
        return {k for k, v in out.items() if v is None}

    at_30 = attribution(old_clone, None, lambda m: m.group(3))
    at_31 = attribution(old_clone, old_rebind, lambda m: m.group(3))
    at_32 = attribution(_RE_CLONE_EFFECT, _RE_REBIND, _clone_source)
    assert (len(at_30), len(at_31), len(at_32)) == (1330, 1335, 1330)
    newly_dropped_by_31 = at_31 - at_30
    restored_by_32 = at_31 - at_32
    assert len(newly_dropped_by_31) == 5
    assert len(restored_by_32) == 5
    #: 🔴 같은 집합이 아니다.
    assert newly_dropped_by_31 != restored_by_32
    assert len(newly_dropped_by_31 & restored_by_32) == 2
    assert {n for n, _ in newly_dropped_by_31} == {
        f"c{CLONE_WITH_ARG_CARD}.lua", f"c{DOT_CLONE_CARD}.lua", "c52445243.lua"}
    assert {n for n, _ in restored_by_32} == {
        f"c{CLONE_WITH_ARG_CARD}.lua", f"c{DOT_CLONE_CARD}.lua",
        f"c{CLONE_IN_INITIAL_CARD}.lua"}


def test_39_helper_dropped_setters_remain_unknown():
    """보조 함수 뒤의 설정자는 **여전히** 버려진다 — 이 Phase 가 고치지 않았다."""
    attribution = _setter_attribution()
    dropped = {k for k, v in attribution.items() if v is None}
    #: ``Ritual.CreateProc`` 을 쓰는 스크립트 가운데 버려진 설정자가 있는 것.
    pat = re.compile(r"(?<![\w.])Ritual\.CreateProc\s*[({]")
    users = {p.name for p in _script_paths() if pat.search(_body(p))}
    assert len(users) == 23
    assert len({n for n, _ in dropped} & users) >= 15


# ===========================================================================
# 범주 13 — Engine V1 · AI/Search 불변성
# ===========================================================================
def test_40_engine_v1_definitions_untouched():
    """🔴 Engine V1 의 16개 정의는 전부 ``ordinal 0`` 이고, 세 장이 들어 있지 않다."""
    from engine.effect.library import EFFECT_LIBRARY
    refs = {(e.definition.effect_ref.card_id, e.definition.effect_ref.ordinal)
            for e in EFFECT_LIBRARY}
    assert len(EFFECT_LIBRARY) == 16
    assert {o for _c, o in refs} == {0}
    assert {c for c, _o in refs} & set(CHANGED_CARDS) == set()


def test_41_state_hash_excludes_block_count():
    """``state_hash`` 의 정규 표현에 **블록 수가 들어가지 않는다** (구조로 확인)."""
    source = textwrap.dedent(inspect.getsource(
        __import__("engine.state.game_state", fromlist=["GameState"]).GameState
        .canonical_state))
    tree = ast.parse(source)
    returned = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert len(returned) == 1
    names = {n.attr for n in ast.walk(returned[0]) if isinstance(n, ast.Attribute)}
    assert "effect_count" not in names
    assert "effects" not in names
    assert "script" not in names
    #: 실제로 넣는 것은 이 다섯 가지다.
    assert {"players", "turn", "uses", "rule_uses", "result"} <= names


def test_42_search_digest_pins_unchanged():
    """결정 digest 핀 7개가 **그대로**다 — 이 수정은 duel 에 닿지 않는다."""
    digest = "30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175"
    pins = []
    for path in sorted(Path(PROJECT_ROOT / "tests").glob("test_*.py")):
        #: 🔴 **이 파일은 센지 않는다** — 위의 digest 문자열 자체가 잡혀서
        #: 핀을 하나 더 세게 된다 (처음 7 로 썼다가 8 이 나왔다).
        if path.name == Path(__file__).name:
            continue
        if digest in path.read_text(encoding="utf-8"):
            pins.append(path.name)
    assert len(pins) == 7, pins


def test_43_category_search_is_unaffected(repo):
    """🔴 카테고리 검색은 **완전히** 그대로다 — 새 블록 셋 다 ``categories`` 가 비었다."""
    for cid in CHANGED_CARDS:
        card = repo.get(cid)
        new_blocks = [s for s in card.script.effects if s.cloned_from is not None]
        assert new_blocks, cid
        for spec in new_blocks:
            assert spec.categories == [], (cid, spec.index)
    #: 블록 단위 ``categories`` 를 가진 블록 수가 파일 단위 집계를 바꾸지 않는다.
    engine = CardSearchEngine(repo)
    res = engine.search(SearchFilters(effect_categories=("DESTROY",)))
    ids = {c.id for c in res.cards}
    assert set(CHANGED_CARDS) & ids == set()


def test_44_location_search_set_unchanged_only_ranking_improves(repo):
    """🔴 MZONE 검색의 **결과 집합은 그대로**이고, 한 장의 순위만 올라간다.

    ``c56410769`` 는 실제로 MZONE 범위 효과가 **둘**이다 (``e2`` 와 그 clone
    ``e3``). 그래서 순위가 오르는 것은 **더 정확해진 것**이다.
    """
    engine = CardSearchEngine(repo)
    res = engine.search(
        SearchFilters(effect_locations=(EffectLocationFilter(location="MZONE"),)))
    ids = [c.id for c in res.cards]
    assert CLONE_IN_INITIAL_CARD in ids
    card = repo.get(CLONE_IN_INITIAL_CARD)
    #: 🔴 세 블록 **전부** ``ranges`` 에 MZONE 이 있다 (``e1`` 은 원문
    #: 15줄의 ``SetRange(LOCATION_MZONE)``, ``e3`` 는 ``e2`` 에게서 물려받음).
    #: 처음 2 로 적었다가 3 이 나왔다 — 세어 보지 않고 쓰면 틀린다.
    mzone_blocks = [s for s in card.script.effects if "MZONE" in s.ranges]
    assert [s.index for s in mzone_blocks] == ["e1", "e2", "e3"]
    #: 늘어난 한 개가 clone 이고, 그래서 점수가 2 → 3 으로 올라 순위가 오른다.
    assert mzone_blocks[2].cloned_from == "e2"
    assert sum(1 for s in card.script.effects if s.cloned_from is not None) == 1


def test_45_analyzer_entry_count_matches_block_count(repo):
    """🔴 분석기의 ``entries`` 길이가 블록 수와 **전수 일치**한다.

    어긋나면 ``entries[position]`` 이 **다른 블록의 핸들러를 붙인다**
    (3-F-28 이 겪은 실패). 두 모듈이 ``_RE_CLONE_EFFECT`` 와
    ``_clone_source`` 를 **공유**하기 때문에 자동으로 맞는다.
    """
    analyzer = EffectAnalyzer(repo)
    mismatch = []
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        entries = analyzer._collect_handlers(source, analyzer._function_spans(source))
        if len(entries) != len(card.script.effects):
            mismatch.append(card.id)
    assert mismatch == []


def test_46_analyzer_shares_the_detection_regexes_no_copy():
    """🔴 분석기가 탐지 정규식과 ``_clone_source`` 를 **import** 한다 (복사본 금지)."""
    assert analyzer_module._RE_CLONE_EFFECT is loader_module._RE_CLONE_EFFECT
    assert analyzer_module._RE_CREATE_EFFECT is loader_module._RE_CREATE_EFFECT
    assert analyzer_module._clone_source is loader_module._clone_source
    #: 자기 복사본을 만들지 않았는지 AST 로 확인한다.
    tree = ast.parse(Path(analyzer_module.__file__).read_text(encoding="utf-8"))
    assigned = {
        t.id
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert "_RE_CLONE_EFFECT" not in assigned
    assert "_RE_CREATE_EFFECT" not in assigned


def test_47_analyzer_recovers_a_registered_effect(repo):
    """🔴 실제 분석 결과가 좋아진다 — ``c56410769`` 의 등록 효과가 2 → 3.

    원문의 세 번째 효과("상대는 공격 선언을 할 수 없다")가 그 전에는
    **분석 결과에 아예 없었다.**
    """
    analyzer = EffectAnalyzer(repo)
    analysis = analyzer.analyze(repo.get(CLONE_IN_INITIAL_CARD))
    assert len(analysis.effects) == 3
    assert analysis.effects[2].index == "e3"
    assert analysis.effects[2].effect_code == "EFFECT_CANNOT_ATTACK_ANNOUNCE"
    assert analysis.effects[2].is_registered is True
    #: 🔴 해결 중 생성 효과 쪽에서도 두 장이 한 개씩 늘었고, 늘어난 항목이
    #: 원문의 그 clone 이다.
    #: 🔴 자리 번호는 ``resolution_effects`` 안의 위치다 — ``ordinal`` 이
    #: 아니다. ``c4997565`` 는 ord2·3·4 가 해결 중 생성이므로 clone(``e2``)이
    #: **1번**이다 (2번으로 적었다가 틀렸다).
    expected = {
        DOT_CLONE_CARD: (1, "e2", "EFFECT_DISABLE_EFFECT"),
        CLONE_WITH_ARG_CARD: (1, "e2", "EFFECT_CANNOT_MSET"),
    }
    for cid, (pos, index, code) in expected.items():
        res = analyzer.analyze(repo.get(cid)).resolution_effects
        assert res[pos].index == index, cid
        assert res[pos].effect_code == code, cid
        assert res[pos].is_registered is False, cid


def test_48_engine_and_agent_do_not_read_the_list_fields():
    """``engine/`` · ``agent/`` 가 ``EffectSpec`` 의 목록 칸을 읽지 않는다.

    🔴 이름만 보고 판단하지 않는다 — ``.code`` 나 ``.index`` 는 **다른
    클래스**에도 있다 (3-F-28·3-F-30 이 그 함정에 빠졌다). 그래서
    ``EffectSpec`` 에만 있는 칸으로 본다.
    """
    unique = ("effect_types", "target_ranges", "cloned_from", "count_limit")
    for pkg in ("engine", "agent"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            assert attrs & set(unique) == set(), (path.name, attrs & set(unique))


# ===========================================================================
# 계약 · 계측
# ===========================================================================
def test_49_cache_signature_bumped():
    """🔴 캐시 서명을 올렸다 — 올리지 않으면 **고친 파서가 옛 캐시를 읽는다**."""
    sig = LuaScriptSource(PROJECT_ROOT)._signature()
    assert sig.startswith(CACHE_PREFIX)
    body = Path(loader_module.__file__).read_text(encoding="utf-8")
    assert 'return f"v10-{_CACHE_SHAPE_TAG}:{count}:{newest:.0f}"' in body
    assert 'return f"v9:' not in body
    assert 'return f"v8:' not in body


def test_50_no_lua_ast_library_in_production():
    """🔴 Lua 인터프리터·AST 라이브러리를 들이지 않았다."""
    forbidden = ("luaparser", "lupa", "slpp", "lua_ast", "antlr")
    for pkg in ("sources", "analysis", "engine", "core", "agent"):
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
            assert mods & set(forbidden) == set(), path.name


def test_51_production_change_is_confined_to_two_files():
    """🔴 production 변경이 **두 파일**에 갇혀 있다 — Lua 파일도 README 도 아니다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    prod = {f for f in changed
            if f.endswith(".py") and not f.startswith("tests/")}
    assert prod == {"sources/lua_loader.py", "analysis/effect_analyzer.py"}
    #: 금지 경로가 하나도 없다.
    assert not any(f.endswith(".lua") for f in changed)
    assert not any(f.endswith("README.md") for f in changed)
    assert not any(f.startswith(("engine/", "agent/", "core/")) for f in changed)


def test_52_no_test_was_deleted_or_skipped():
    """🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    out = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-32:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30).stdout.split()
    added_skips = 0
    for sha in out:
        diff = subprocess.run(
            ["git", "show", "--format=", "--unified=0", sha, "--", "tests/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60).stdout
        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(r"@pytest\.mark\.skip|pytest\.skip\(", line):
                    #: 이 파일의 ``_changed_files`` 가 비었을 때 쓰는 guard 는 제외
                    if "commit 이 아직 없다" not in line:
                        added_skips += 1
    assert added_skips == 0
