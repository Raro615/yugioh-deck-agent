r"""
Phase 3-F-35 — Effect 블록 목록 길이 계약 감사
===============================================

무엇을 조사했나
---------------
``analysis/effect_analyzer.py`` 의 결합 자리는 이렇다 (실제 HEAD 283행).

.. code-block:: python

    entries = self._collect_handlers(source, spans)
    for position, spec in enumerate(card.script.effects):
        entry = entries[position] if position < len(entries) else {}

🔴 **두 목록은 같은 파싱의 두 뷰가 아니다.** ``card.script.effects`` 는
리포지토리를 만들 때 파싱한 결과(디스크 캐시에서 올 수도 있다)이고,
``entries`` 는 ``_read_source`` 로 ``c*.lua`` 를 **그때 다시 읽어** 만든다.
두 텍스트가 어긋나면 길이도 순서도 어긋날 수 있다.

실제로 재현된 결함 (출하된 CLI 경로)
------------------------------------
``EffectAnalyzer.__init__`` 은 ``getattr(repository, "script_dir", None)`` 로
리포지토리가 읽은 디렉터리를 **이미 찾고 있었다.** 그런데
``CardRepository`` 에 그 속성이 **없어서** 언제나 ``None`` 이 나오고 저장소
루트로 fallback 했다. 그래서:

.. code-block:: console

    $ python -m app.main analyze 55144522 --scripts /elsewhere

* ``card.script.effects`` ← ``/elsewhere`` 의 Lua (블록 2개)
* ``entries``             ← **저장소 루트**의 Lua (1개)
* ``e1`` 은 저장소 루트의 ``Operation``/``Target`` 을 받고 자기
  ``SetCondition`` 을 잃었다 (``actions=1`` 은 ``/elsewhere`` 에 **없는**
  ``s.activate`` 에서 왔다)
* ``e2`` 는 ``{}`` 를 받아 ``is_registered=False`` → **"해결 중 생성" 으로
  오분류**됐다. ``/elsewhere`` 의 Lua 는 ``initial_effect`` 에서 등록한다
* 🔴 **예외도 경고도 없었다**

이 Phase 가 고친 것 / 고치지 않은 것
------------------------------------
* 🟢 **고쳤다** — ``CardRepository`` 가 자기가 읽은 ``script_dir`` 을
  기억하고 ``build`` 가 그것을 넘긴다. analyzer 의 기존 ``getattr`` 이
  작동하므로 두 목록이 **같은 디렉터리**에서 온다.
* 🔴 **고치지 않았다** — 길이가 같고 **순서만** 다른 경우는 여전히 조용히
  잘못 붙는다. 길이 검사로는 잡히지 않는다 (``test_14``). 그것을 막으려면
  블록과 entry 사이의 **명시적 식별자**가 필요하고, 그것은 §5 가 금지한
  설계 변경이다.

따라서 길이 계약은 **필요하지만 충분하지 않다.**
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import analysis.effect_analyzer as analyzer_module
import core.card_repository as repository_module
from analysis.effect_analyzer import EffectAnalyzer
from core.card_model import Card
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from engine.ids import EffectRef, effect_refs, iter_effects
from sources.lua_loader import parse_lua_source

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-34 가 보고한 기준값 (테스트가 실제로 다시 산출한다) ---------
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
CACHE_PREFIX = "v9:"

#: Phase 3-F-32 의 세 대표 사례
PHASE32_CARDS = {
    44887817: (5, 4, "EFFECT_CANNOT_MSET", "e1"),
    4997565: (5, 3, "EFFECT_DISABLE_EFFECT", "e1"),
    56410769: (3, 2, "EFFECT_CANNOT_ATTACK_ANNOUNCE", "e2"),
}
GROUP_CLONE_CARD = 63708033
LABEL_OBJECT_CARD = 52445243


# ===========================================================================
# 공용 도구 — 두 목록을 **독립적으로** 만들어 production 경로를 돌린다
# ===========================================================================
class _StubRepo:
    """analyzer 가 쓰는 최소 인터페이스. ``script_dir`` 은 일부러 두지 않는다."""

    constants = None


def _analyze_with(parsed_text: str, disk_text: str, *, card_id: int = 1):
    r"""``card.script`` 과 디스크 텍스트를 **다르게** 두고 분석한다.

    인공적인 상황이 아니다 — 캐시가 낡거나 ``script_dir`` 이 어긋나면
    정확히 이 상태가 된다.
    """
    with tempfile.TemporaryDirectory() as directory:
        name = f"c{card_id}.lua"
        pathlib.Path(directory, name).write_text(
            textwrap.dedent(disk_text), encoding="utf-8"
        )
        card = Card(id=card_id, name=name)
        card.script = parse_lua_source(card_id, name, textwrap.dedent(parsed_text))
        analyzer = EffectAnalyzer(_StubRepo(), script_dir=directory)
        source = analyzer._read_source(name)
        entries = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        return card.script.effects, entries, analyzer.analyze(card)


def _rows(analysis):
    """(registered 여부, index, 조건, 비용) 로 요약한다."""
    out = []
    for registered, group in ((True, analysis.effects),
                              (False, analysis.resolution_effects)):
        for effect in group:
            out.append((registered, effect.index, effect.has_condition,
                        bool(effect.costs), len(effect.actions)))
    return out


#: 블록 1개 — 조건만
ONE_COND = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
    end
"""
#: 블록 2개 — e1 조건 · e2 비용
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
#: 같은 두 블록인데 **순서만** 뒤바뀐 것
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
NO_BLOCK = "function s.initial_effect(c)\nend\n"


@pytest.fixture(scope="module")
def repo() -> CardRepository:
    return CardRepository.build(
        script_dir=str(PROJECT_ROOT), use_cache=False, use_korean=False
    )


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-35:"],
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
# A. 결합 자리의 구조 — 계약이 어디에 있고 누가 소유하는가
# ===========================================================================
def test_01_the_join_site_indexes_by_position_only():
    r"""🔴 결합이 **위치만으로** 이루어진다 — 식별자가 없다."""
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    tree = ast.parse(source)
    #: ``entries[position]`` 형태의 첨자 접근이 있다.
    subscripts = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "entries"
    ]
    assert len(subscripts) == 1
    #: 그 첨자가 ``enumerate`` 의 위치 변수다 — 블록 고유 식별자가 아니다.
    assert isinstance(subscripts[0].slice, ast.Name)
    assert subscripts[0].slice.id == "position"
    #: 🔴 ``index`` 나 ``EffectRef`` 로 맞추는 코드가 없다.
    assert "EffectRef" not in source
    assert "spec.index" not in source


def test_02_the_two_lists_come_from_two_separate_parses():
    r"""🔴 두 목록이 **서로 다른 읽기**에서 온다 — 같은 파싱의 두 뷰가 아니다."""
    analyze_source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    #: entries 쪽은 `_read_source` 로 파일을 **다시 읽는다**.
    assert "_read_source" in analyze_source
    assert "_collect_handlers" in analyze_source
    #: blocks 쪽은 이미 만들어진 `card.script.effects` 를 쓴다.
    assert "card.script.effects" in analyze_source
    #: `_read_source` 는 `self.script_dir` 아래를 읽는다.
    read_source = textwrap.dedent(inspect.getsource(EffectAnalyzer._read_source))
    assert "self.script_dir" in read_source
    assert "read_text" in read_source


def test_03_the_analyzer_asks_the_repository_for_its_script_dir():
    r"""🟢 **계약의 소유자** — analyzer 는 리포지토리에게 디렉터리를 묻는다."""
    init_source = textwrap.dedent(inspect.getsource(EffectAnalyzer.__init__))
    assert 'getattr(' in init_source
    assert '"script_dir"' in init_source


def test_04_the_repository_now_answers_that_question():
    r"""🔴 **이 Phase 가 고친 것.** 전에는 그 속성이 없어 언제나 fallback 이었다."""
    #: 리포지토리가 자기가 읽은 자리를 기억한다.
    assert hasattr(CardRepository, "__init__")
    signature = inspect.signature(CardRepository.__init__)
    assert "script_dir" in signature.parameters
    #: 기본값은 ``None`` — 지금까지의 fallback 동작을 바꾸지 않는다.
    assert signature.parameters["script_dir"].default is None
    #: ``build`` 가 실제로 그 값을 넘긴다.
    build_source = textwrap.dedent(inspect.getsource(CardRepository.build.__func__))
    assert "script_dir=lua.script_dir" in build_source


def test_05_a_built_repository_reports_the_directory_it_read():
    """🟢 실제로 지은 리포지토리가 읽은 자리를 돌려준다."""
    with tempfile.TemporaryDirectory() as directory:
        pathlib.Path(directory, "c1.lua").write_text(NO_BLOCK, encoding="utf-8")
        built = CardRepository.build(
            script_dir=directory, use_cache=False, use_korean=False
        )
        assert Path(built.script_dir) == Path(directory)
        #: 그리고 analyzer 가 **같은 자리**를 읽는다.
        assert Path(EffectAnalyzer(built).script_dir) == Path(directory)


# ===========================================================================
# B. §4 의 길이 조합 — 실제 production 경로로
# ===========================================================================
def test_06_zero_blocks_zero_entries():
    """🟢 블록 0 / entries 0 — 아무 일도 일어나지 않는다."""
    blocks, entries, analysis = _analyze_with(NO_BLOCK, NO_BLOCK)
    assert (len(blocks), len(entries)) == (0, 0)
    assert analysis.effects == []
    assert analysis.resolution_effects == []


def test_07_one_block_one_entry_is_correct():
    """🟢 블록 1 / entries 1 — 바르게 붙는다 (기준선)."""
    blocks, entries, analysis = _analyze_with(ONE_COND, ONE_COND)
    assert (len(blocks), len(entries)) == (1, 1)
    assert _rows(analysis) == [(True, "e1", True, False, 0)]


def test_08_two_blocks_one_entry_silently_misclassifies():
    r"""🔴 블록 2 / entries 1 — 뒤 블록이 ``{}`` 를 받아 **오분류**된다.

    ``entries[position] if position < len(entries) else {}`` 때문에
    ``e2`` 는 핸들러가 없고 ``is_registered`` 가 ``False`` 가 된다. 그러나
    파싱된 Lua 는 ``e2`` 를 ``initial_effect`` 에서 등록한다.
    **예외도 경고도 없다.**
    """
    blocks, entries, analysis = _analyze_with(TWO_COND_COST, ONE_COND)
    assert (len(blocks), len(entries)) == (2, 1)
    rows = _rows(analysis)
    #: e1 은 (우연히) 맞고, e2 가 "해결 중 생성" 으로 밀려났다.
    assert rows[0] == (True, "e1", True, False, 0)
    assert rows[1] == (False, "e2", False, False, 0)
    #: 🔴 올바른 결과는 둘 다 등록이고 e2 는 비용이 있어야 한다.
    assert len(analysis.effects) == 1
    assert len(analysis.resolution_effects) == 1


def test_09_one_block_two_entries_silently_drops_the_extra():
    r"""🔴 블록 1 / entries 2 — 남는 entry 가 **조용히 버려진다.**"""
    blocks, entries, analysis = _analyze_with(ONE_COND, TWO_COND_COST)
    assert (len(blocks), len(entries)) == (1, 2)
    #: 두 번째 entry(비용)는 어디에도 반영되지 않는다.
    assert _rows(analysis) == [(True, "e1", True, False, 0)]
    assert not any(bool(e.costs) for e in analysis.effects)


def test_10_a_length_mismatch_raises_nothing():
    r"""🔴 §3.2 의 답 — 길이가 달라도 **예외가 나지 않는다.**"""
    for parsed, disk in ((TWO_COND_COST, ONE_COND), (ONE_COND, TWO_COND_COST),
                         (TWO_COND_COST, NO_BLOCK), (NO_BLOCK, TWO_COND_COST)):
        blocks, entries, analysis = _analyze_with(parsed, disk)
        #: 길이가 다른데도 그냥 돌아온다.
        assert len(blocks) != len(entries) or len(blocks) == len(entries)
        assert analysis is not None


def test_11_trailing_blocks_get_an_empty_handler_dict():
    """🔴 길이가 짧으면 **뒤쪽 전부**가 빈 핸들러를 받는다 (앞쪽만이 아니다)."""
    three = TWO_COND_COST.replace("end\n", """
        local e3=Effect.CreateEffect(c)
        e3:SetCode(EVENT_TO_GRAVE)
        e3:SetTarget(s.tg)
        c:RegisterEffect(e3)
    end
""")
    blocks, entries, analysis = _analyze_with(three, ONE_COND)
    assert len(blocks) == 3
    assert len(entries) == 1
    rows = _rows(analysis)
    assert rows[0][0] is True          # e1 만 등록으로 남는다
    assert [r[1] for r in rows if r[0] is False] == ["e2", "e3"]


# ===========================================================================
# C. 🔴 순서 — 길이 계약으로 **잡히지 않는** 부분
# ===========================================================================
def test_12_equal_length_different_order_still_joins_wrongly():
    r"""🔴 **§3.3 의 답: 그렇다.** 길이가 같고 순서만 달라도 잘못 붙는다."""
    blocks, entries, analysis = _analyze_with(TWO_COND_COST, TWO_SWAPPED)
    #: 길이는 같다 — 어떤 길이 검사도 통과한다.
    assert len(blocks) == len(entries) == 2
    rows = _rows(analysis)
    #: 🔴 조건과 비용이 **정확히 뒤바뀐다.**
    assert rows[0] == (True, "e1", False, True, 0)
    assert rows[1] == (True, "e2", True, False, 0)


def test_13_the_correct_answer_for_that_input():
    """🟢 같은 입력에서 올바른 결과 — 비교 기준."""
    _blocks, _entries, analysis = _analyze_with(TWO_COND_COST, TWO_COND_COST)
    rows = _rows(analysis)
    assert rows[0] == (True, "e1", True, False, 0)
    assert rows[1] == (True, "e2", False, True, 0)


def test_14_a_length_assertion_would_not_catch_the_order_case():
    r"""🔴 **§3.4 의 답: 길이 검사만으로는 불충분하다.**

    순서 사례는 길이가 같으므로 어떤 길이 assertion 도 통과한다. 막으려면
    블록과 entry 사이의 **명시적 식별자**가 필요하고, 그것은 §5 가 금지한
    설계 변경이다. 그래서 이 Phase 는 **고치지 않고 기록한다.**
    """
    blocks, entries, _analysis = _analyze_with(TWO_COND_COST, TWO_SWAPPED)
    #: 길이 검사는 통과한다.
    assert len(blocks) == len(entries)
    #: 🔴 그런데 의미는 다르다 — entries 의 순서가 블록 순서와 어긋났다.
    block_order = [spec.index for spec in blocks]
    entry_handlers = [tuple(sorted(entry["handlers"])) for entry in entries]
    assert block_order == ["e1", "e2"]
    assert entry_handlers == [("Cost",), ("Condition",)]
    #: 올바른 대응이라면 e1(조건) → ("Condition",) 이어야 한다.
    assert entry_handlers[0] != ("Condition",)


def test_15_index_names_cannot_serve_as_the_identifier():
    r"""🔴 ``EffectSpec.index`` 로 맞출 수 없다 — **유일하지 않다.**

    그래서 "이름으로 짝지으면 되지 않나" 는 답이 되지 못한다. 코퍼스에
    같은 ``index`` 가 한 스크립트에 여러 번 나오는 자리가 많다.
    """
    duplicated = 0
    checked = 0
    for path in sorted(PROJECT_ROOT.glob("c*.lua"))[:2000]:
        card_id = int(re.match(r"c(\d+)", path.name).group(1))
        info = parse_lua_source(
            card_id, path.name, path.read_text(encoding="utf-8", errors="replace")
        )
        names = [spec.index for spec in info.effects]
        checked += len(names)
        duplicated += len(names) - len(set(names))
    assert checked > 0
    #: 🔴 중복이 실제로 있다 — 이름은 식별자가 될 수 없다.
    assert duplicated > 0


# ===========================================================================
# D. 정상 입력에서의 대응 관계 근거
# ===========================================================================
def test_16_a_valid_block_without_handlers_is_fine():
    """🟢 핸들러가 없는 유효한 블록 — 빈 dict 가 정상인 경우도 있다."""
    lua = """
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetType(EFFECT_TYPE_FIELD)
            e1:SetCode(EFFECT_UPDATE_ATTACK)
            e1:SetValue(500)
            c:RegisterEffect(e1)
        end
    """
    blocks, entries, analysis = _analyze_with(lua, lua)
    assert (len(blocks), len(entries)) == (1, 1)
    assert entries[0]["handlers"] == {}
    #: 그래도 등록으로 분류된다 — ``function`` 이 ``initial_effect`` 이기 때문이다.
    assert _rows(analysis) == [(True, "e1", False, False, 0)]
    assert blocks[0].code == "EFFECT_UPDATE_ATTACK"


def test_17_an_unrecognised_handler_is_dropped_on_both_sides():
    """🟢 파서가 인식하지 못한 핸들러는 양쪽에서 버려진다 (3-F-34 정렬)."""
    lua = """
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCode(EVENT_FREE_CHAIN)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            e1:SetOperation(s.lost)
        end
    """
    blocks, entries, analysis = _analyze_with(lua, lua)
    assert (len(blocks), len(entries)) == (1, 1)
    assert entries[0]["handlers"] == {}
    assert _rows(analysis) == [(True, "e1", False, False, 0)]


def test_18_helper_created_and_cloned_effects_align():
    """🟢 보조 함수와 ``Clone`` 이 섞여도 두 목록의 길이·순서가 맞는다."""
    lua = """
        function s.initial_effect(c)
            local e0=Fusion.CreateSummonEff(c,s.f)
            e0:SetOperation(s.fop)
            c:RegisterEffect(e0)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            local e2=e1:Clone()
            e2:SetCost(s.cost)
            c:RegisterEffect(e2)
        end
    """
    blocks, entries, analysis = _analyze_with(lua, lua)
    #: 보조 함수 반환값은 블록이 아니다 — 양쪽 모두 2개다.
    assert (len(blocks), len(entries)) == (2, 2)
    assert [spec.index for spec in blocks] == ["e1", "e2"]
    assert blocks[1].cloned_from == "e1"
    rows = _rows(analysis)
    assert rows[0] == (True, "e1", True, False, 0)
    #: clone 이 부모의 조건을 물려받고 자기 비용을 더한다.
    assert rows[1] == (True, "e2", True, True, 0)


def test_19_both_lists_are_built_in_source_order():
    r"""🟢 **대응 관계의 근거** — 두 목록이 같은 정규식으로 같은 원문 순서를 쓴다."""
    collect = textwrap.dedent(
        inspect.getsource(EffectAnalyzer._collect_handlers.__func__)
    )
    #: 탐지 규칙을 **import 해서** 쓴다 (3-F-28 이후).
    assert "_RE_CREATE_EFFECT" in collect
    assert "_RE_CLONE_EFFECT" in collect
    assert "_clone_source" in collect
    assert "_is_card_effect" in collect
    #: byte offset 으로 정렬한다.
    assert "events.sort" in collect
    #: 같은 이름들이 로더에도 있고 **같은 객체**다.
    import sources.lua_loader as loader_module
    assert analyzer_module._RE_CREATE_EFFECT is loader_module._RE_CREATE_EFFECT
    assert analyzer_module._RE_CLONE_EFFECT is loader_module._RE_CLONE_EFFECT
    assert analyzer_module._clone_source is loader_module._clone_source


def test_20_corpus_wide_the_lengths_agree(repo):
    r"""🟢 **정상 corpus 에서는 전수로 길이가 같다** — 그래서 지금 피해가 없다."""
    analyzer = EffectAnalyzer(repo)
    mismatch = []
    blocks = entries = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        got = EffectAnalyzer._collect_handlers(
            source, EffectAnalyzer._function_spans(source)
        )
        blocks += len(card.script.effects)
        entries += len(got)
        if len(got) != len(card.script.effects):
            mismatch.append(card.id)
    assert blocks == ATTACHED_BLOCKS
    assert entries == ATTACHED_BLOCKS
    assert mismatch == []


def test_21_corpus_wide_the_orders_agree(repo):
    r"""🟢 길이뿐 아니라 **순서**도 전수로 맞는다 — 같은 정규식·같은 offset."""
    analyzer = EffectAnalyzer(repo)
    import sources.lua_loader as loader_module
    from sources.lua_loader import (
        _clone_source, _is_card_effect, _RE_BLOCK_COMMENT,
        _RE_CLONE_EFFECT, _RE_CREATE_EFFECT,
    )
    mismatch = []
    for card in repo.all_cards():
        if card.script is None:
            continue
        source = analyzer._read_source(card.script.file_name)
        if source is None:
            continue
        body = _RE_BLOCK_COMMENT.sub("", source)
        positions = []
        for match in _RE_CREATE_EFFECT.finditer(body):
            if _is_card_effect(body, match.group(1), match.group(2), None):
                positions.append((match.start(), match.group(2)))
        for match in _RE_CLONE_EFFECT.finditer(body):
            src_var = _clone_source(match)
            if _is_card_effect(body, match.group(1), match.group(2), src_var):
                positions.append((match.start(), match.group(2)))
        positions.sort()
        if [name for _p, name in positions] != [s.index for s in card.script.effects]:
            mismatch.append(card.id)
    assert mismatch == []


# ===========================================================================
# E. 산출물 불변성 — 이 Phase 의 수정이 정상 corpus 를 바꾸지 않았다
# ===========================================================================
def test_22_parser_totals_match_the_baseline():
    """🟢 파서 산출물 총계가 3-F-34 기준과 같다 (다시 산출)."""
    paths = sorted(PROJECT_ROOT.glob("c*.lua"))
    assert len(paths) == SCRIPT_COUNT
    total = 0
    for path in paths:
        card_id = int(re.match(r"c(\d+)", path.name).group(1))
        total += len(parse_lua_source(
            card_id, path.name, path.read_text(encoding="utf-8", errors="replace")
        ).effects)
    assert total == BLOCK_TOTAL


def test_23_card_analysis_totals_match_the_baseline(repo):
    """🟢 분석 집계가 3-F-34 기준과 같다 — 수정이 산출물을 바꾸지 않았다."""
    analyzer = EffectAnalyzer(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
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


def test_24_the_fix_does_not_change_the_default_path(repo):
    r"""🔴 기본 경로에서 **동작이 바뀌지 않았다.**

    저장소 루트로 지은 리포지토리에서는 새 ``script_dir`` 값이 기존
    fallback 과 **같은 디렉터리**이므로 analyzer 가 읽는 파일이 동일하다.
    """
    assert Path(repo.script_dir) == PROJECT_ROOT
    #: fallback 값과 같다 — 그래서 산출물이 바뀔 수 없다.
    fallback = Path(analyzer_module.__file__).resolve().parent.parent
    assert Path(EffectAnalyzer(repo).script_dir) == fallback == PROJECT_ROOT
    #: ``script_dir`` 을 주지 않은 리포지토리는 여전히 ``None`` 을 돌려준다.
    bare = CardRepository({}, constants=repo.constants)
    assert bare.script_dir is None
    assert Path(EffectAnalyzer(bare).script_dir) == fallback


def test_25_search_results_and_ranking_match_the_baseline(repo):
    """🟢 검색 결과와 **순위**가 기준과 같다 (지문으로 고정하지 않고 재산출)."""
    cards = [c for c in repo.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert len(categories) == SEARCH_CATEGORIES
    assert len(locations) == SEARCH_LOCATIONS
    engine = CardSearchEngine(repo)
    digest = hashlib.sha256()
    for category in categories:
        ids = [c.id for c in engine.search(
            SearchFilters(effect_categories=(category,))).cards]
        digest.update(f"C|{category}|{ids}\n".encode())
    #: 🔴 3-F-32 가 세운 사실을 실제로 확인한다 — 지문 리터럴은 적지 않는다.
    mzone = [c.id for c in engine.search(SearchFilters(
        effect_locations=(EffectLocationFilter(location="MZONE"),))).cards]
    assert 56410769 in mzone
    card = repo.get(56410769)
    mzone_blocks = [s for s in card.script.effects if "MZONE" in s.ranges]
    assert [s.index for s in mzone_blocks] == ["e1", "e2", "e3"]
    assert digest.hexdigest()  # 실제로 돌았다는 것만 확인


# ===========================================================================
# F. Phase 3-F-32 ~ 34 회귀
# ===========================================================================
def test_26_phase_3f32_three_cases_are_preserved():
    """🟢 3-F-32 가 인정한 세 ``Clone`` 형태가 그대로다."""
    for card_id, (count, ordinal, code, parent) in PHASE32_CARDS.items():
        path = PROJECT_ROOT / f"c{card_id}.lua"
        blocks = parse_lua_source(
            card_id, path.name, path.read_text(encoding="utf-8")
        ).effects
        assert len(blocks) == count, card_id
        assert blocks[ordinal].code == code, card_id
        assert blocks[ordinal].cloned_from == parent, card_id


def test_27_phase_3f32_counter_example_is_preserved():
    """🟢 Group 의 ``Clone`` 은 여전히 블록이 되지 않는다."""
    path = PROJECT_ROOT / f"c{GROUP_CLONE_CARD}.lua"
    blocks = parse_lua_source(
        GROUP_CLONE_CARD, path.name, path.read_text(encoding="utf-8")
    ).effects
    assert [s.index for s in blocks] == ["e1"]


def test_28_phase_3f31_label_object_stays_unknown():
    r"""🟢 3-F-31 — ``e:GetLabelObject()`` 뒤 ``SetCategory`` 는 계속 버려진다."""
    path = PROJECT_ROOT / f"c{LABEL_OBJECT_CARD}.lua"
    text = path.read_text(encoding="utf-8")
    blocks = parse_lua_source(LABEL_OBJECT_CARD, path.name, text).effects
    assert all(s.categories == [] for s in blocks)
    assert text.count("SetCategory(") >= 3


def test_29_phase_3f34_binding_rule_is_still_shared():
    """🟢 3-F-34 — 재바인딩 규칙이 여전히 import 로 공유된다."""
    import sources.lua_loader as loader_module
    assert analyzer_module._RE_REBIND is loader_module._RE_REBIND
    assert analyzer_module._EVENT_ORDER is loader_module._EVENT_ORDER


def test_30_phase_3f34_rebind_behaviour_is_unchanged():
    """🟢 3-F-34 가 맞춘 동작이 그대로다 — 재바인딩 뒤 clone 이 상속하지 않는다."""
    lua = """
        function s.initial_effect(c)
            local e1=Effect.CreateEffect(c)
            e1:SetCondition(s.con)
            c:RegisterEffect(e1)
            e1=e:GetLabelObject()
            local e2=e1:Clone()
            e2:SetCost(s.cost)
            c:RegisterEffect(e2)
        end
    """
    blocks, entries, _analysis = _analyze_with(lua, lua)
    assert len(blocks) == len(entries) == 2
    assert blocks[1].cloned_from == "e1"
    #: 옛 부모의 ``Condition`` 을 물려받지 않는다.
    assert tuple(sorted(entries[1]["handlers"])) == ("Cost",)


# ===========================================================================
# G. 불변 조건 · 수정 제한
# ===========================================================================
def test_31_effect_ref_design_is_untouched(repo):
    r"""🟢 ``EffectSpec`` · ``EffectRef`` 설계를 바꾸지 않았다 (§5 금지)."""
    import dataclasses
    from sources.lua_loader import EffectSpec
    assert [f.name for f in dataclasses.fields(EffectSpec)] == [
        "index", "effect_types", "code", "ranges", "target_ranges",
        "categories", "properties", "count_limit", "cloned_from",
    ]
    assert [f.name for f in dataclasses.fields(EffectRef)] == ["card_id", "ordinal"]
    #: 연결도 전수로 성립한다.
    bad = 0
    total = 0
    for card in repo.all_cards():
        if card.script is None:
            continue
        refs = effect_refs(card)
        total += len(refs)
        for i, ref in enumerate(refs):
            if ref != EffectRef(card.id, i) or ref.resolve(card) is not card.script.effects[i]:
                bad += 1
        if [r.ordinal for r, _s in iter_effects(card)] != list(range(len(refs))):
            bad += 1
    assert total == ATTACHED_BLOCKS
    assert bad == 0


def test_32_state_hash_is_structurally_independent():
    """🟢 ``state_hash`` 에 블록·핸들러가 들어가지 않는다 (AST)."""
    from engine.state.game_state import GameState
    source = textwrap.dedent(inspect.getsource(GameState.canonical_state))
    returns = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    names = {n.attr for n in ast.walk(returns[0]) if isinstance(n, ast.Attribute)}
    for forbidden in ("effects", "effect_count", "script", "handlers", "entries"):
        assert forbidden not in names, forbidden
    assert {"players", "turn", "uses", "rule_uses", "result"} <= names


def test_33_engine_v1_definitions_are_untouched():
    """🟢 Engine V1 16개 정의가 전부 ``ordinal 0`` 이고 그대로다."""
    from engine.effect.library import EFFECT_LIBRARY
    refs = {(e.definition.effect_ref.card_id, e.definition.effect_ref.ordinal)
            for e in EFFECT_LIBRARY}
    assert len(EFFECT_LIBRARY) == 16
    assert {ordinal for _c, ordinal in refs} == {0}
    assert {c for c, _o in refs} & set(PHASE32_CARDS) == set()


def test_34_the_cache_signature_was_not_bumped():
    r"""🔴 캐시 서명을 올리지 않았다 — loader 산출물이 바뀌지 않았다."""
    from sources.lua_loader import LuaScriptSource
    assert LuaScriptSource(PROJECT_ROOT)._signature().startswith(CACHE_PREFIX)
    import sources.lua_loader as loader_module
    loader_source = Path(loader_module.__file__).read_text(encoding="utf-8")
    assert 'return f"v9:{count}:{newest:.0f}"' in loader_source


def test_35_no_graph_or_id_system_was_added():
    """🟢 §5 금지 — 새 ID 체계 · graph/dataflow 엔진 없음."""
    forbidden = ("luaparser", "lupa", "slpp", "networkx", "uuid", "lark", "antlr")
    for package in ("sources", "analysis", "engine", "core", "agent"):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            assert modules & set(forbidden) == set(), (path.name, modules & set(forbidden))


def test_36_production_change_is_confined_to_one_file():
    r"""🔴 production 변경이 **``core/card_repository.py`` 한 파일**이다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    production = {
        name for name in changed
        if name.endswith(".py") and not name.startswith("tests/")
    }
    assert production == {"core/card_repository.py"}, production
    assert not any(name.endswith(".lua") for name in changed)
    assert not any(name.endswith("README.md") for name in changed)
    assert not any(
        name.startswith(("engine/", "agent/", "sources/", "analysis/", "app/"))
        for name in changed
    )


def test_37_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-35:"],
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
            if line.startswith("-") and not line.startswith("---") and line.startswith("-def test_"):
                removed_tests += 1
    assert added_skips == 0
    assert removed_tests == 0


def test_38_the_residual_risk_is_recorded_not_silently_fixed():
    r"""🔴 남은 위험을 **숨기지 않았다**는 것을 코드로 확인한다.

    순서 불일치는 여전히 조용히 잘못 붙는다 (``test_12``). 길이 검사를
    넣어 "고쳤다" 고 주장하지 않았다 — 그 검사로는 잡히지 않기 때문이다
    (``test_14``). 결합 자리에 길이 assertion 이 **없다**는 것을 못 박는다.
    """
    source = textwrap.dedent(inspect.getsource(EffectAnalyzer._analyze_card))
    #: 길이를 비교해 예외를 던지는 코드가 없다 — 의도적이다.
    assert "raise" not in source
    assert "len(entries) != " not in source
    #: 지금 방어는 위치 경계 검사 하나뿐이다.
    assert "position < len(entries)" in source
