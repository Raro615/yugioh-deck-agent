r"""
Phase 3-F-40 — ``AnalysisStatus.LUA_VERIFIED`` 의미 및 provenance 경계 감사.

핵심 질문: **Lua 가 붙어 있다는 사실**과 **분석 결과가 Lua 원문으로
검증되었다는 사실**을 시스템이 구분하는가.

실측 답은 "구분하지 않았다" 다. ``LUA_VERIFIED`` 를 만드는 조건은
``card.script is not None`` **하나**이고, 분석을 돌려 확인한 값이 아니다.
그래서 다음이 **동시에** 성립한다.

* ``LUA_VERIFIED`` + ``HandlerBinding.MISMATCHED`` (지문 불일치)
* ``LUA_VERIFIED`` + ``HandlerBinding.UNPROVABLE`` (낡은 캐시)
* ``LUA_VERIFIED`` + ``HandlerBinding.SOURCE_MISSING`` (파일 소실)
* ``LUA_VERIFIED`` + 등록 효과 **0개** — 실제 코퍼스에 **215장**
  (183장은 효과 블록 자체가 0개)

🔴 **두 값을 하나로 합치지 않는다.** ``AnalysisStatus`` 는 근거(출처)
계층, ``HandlerBinding`` 은 증명 계층이다. ``MATCHED`` 를 보고 상태를
올리지도 않고, 결합이 어긋났다고 상태를 일괄 강등하지도 않는다. 고친 것은
**사용자에게 하는 주장**이다.

🔴 이 파일은 enum 값이나 문자열이 존재한다는 확인으로 의미 검증을
대체하지 않는다. 상태를 만드는 production 함수
(``CardRepository._record_provenance``) 와 분석기·CLI·갱신 요약을 실제로
돌리고 그 결과를 읽는다.
"""

from __future__ import annotations

import ast
import collections
import contextlib
import inspect
import io
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import app.main as main_module
import core.card_repository as repository_module
import core.provenance as provenance_module
import scripts.update_cards as update_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import HandlerBinding
from app.main import cmd_analyze
from core import constants as C
from core.card_model import Card, CardSource
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus, CardProvenance
from engine.ids import EffectRef, effect_refs
from scripts.update_cards import summarise
from sources.lua_loader import parse_lua_source
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-40 이 실측한 기준값 (테스트가 실제로 다시 산출한다) ----------
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}
CARD_TOTAL = 14127
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
#: ``LUA_VERIFIED`` 인데 등록 효과가 0개인 실제 카드
LUA_VERIFIED_NO_EFFECTS = 215
ZERO_BLOCK_CARDS = 183          # 그중 효과 블록 자체가 0개
RESOLUTION_ONLY_CARDS = 32      # 그중 블록이 전부 해결 효과
#: 효과 블록이 0개인 실제 스크립트 (융합 소재 선언만 있다)
ZERO_BLOCK_SAMPLES = [1641882, 2504891, 3627449]
ANALYZE_CARD = 32807846         # 증원


# ===========================================================================
# 공용 도구 — 상태 생성과 결합 판정을 **각각 실제 함수로** 돌린다
# ===========================================================================
TWO_BLOCKS = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_ACTIVATE)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        e1:SetOperation(s.op)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetType(EFFECT_TYPE_ACTIVATE)
        e2:SetCode(EVENT_FREE_CHAIN)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
    function s.con(e,tp) return true end
    function s.op(e,tp,eg,ep,ev,re,r,rp) Duel.Draw(tp,1,REASON_EFFECT) end
    function s.cost(e,tp,eg,ep,ev,re,r,rp,chk) if chk==0 then return true end end
"""
#: 🔴 **효과 블록이 0개인 유효한 스크립트.** 실제 코퍼스에 183장 있다.
ZERO_BLOCKS = """
    function s.initial_effect(c)
        c:EnableReviveLimit()
        Fusion.AddProcMix(c,true,true,38142739,83464209)
    end
"""


class _StubRepo:
    """``cmd_analyze`` 와 ``EffectAnalyzer`` 가 실제로 쓰는 최소 인터페이스."""

    constants = None

    def __init__(self, script_dir, card):
        self.script_dir = script_dir
        self._card = card

    def get(self, card_id):
        return self._card if card_id == self._card.id else None


def _card(*, lua: str | None = TWO_BLOCKS, on_disk: bool = True,
          break_digest: bool = False, drop_digest: bool = False,
          shift_one: bool = False, kind: str = "spell",
          desc: str = "덱에서 1장 패에 넣는다.", card_id: int = 1):
    """카드 하나를 만들고 **실제 ``_record_provenance``** 로 상태를 붙인다.

    분석기는 호출하지 않는다 — 상태가 분석과 무관하게 정해지는 것을
    보이기 위해서다. 결합 판정이 필요한 테스트는 :func:`_analyze` 를 쓴다.
    """
    directory = tempfile.mkdtemp()
    name = f"c{card_id}.lua"
    text = textwrap.dedent(lua) if lua is not None else None
    if text is not None and on_disk:
        pathlib.Path(directory, name).write_text(text, encoding="utf-8")
    card = Card(id=card_id, name=name, desc=desc)
    if kind == "spell":
        card.type_mask = C.TYPE_SPELL
    elif kind == "normal_monster":
        card.type_mask = C.TYPE_MONSTER | C.TYPE_NORMAL
    elif kind == "effect_monster":
        card.type_mask = C.TYPE_MONSTER | C.TYPE_EFFECT
    card.sources.add(CardSource.OFFICIAL_DB)
    if text is not None:
        card.script = parse_lua_source(card_id, name, text)
        if break_digest:
            card.script.source_digest = "0" * 64
        if drop_digest:
            card.script.source_digest = None
        if shift_one:
            offsets = list(card.script.effect_offsets)
            offsets[-1] += 1
            card.script.effect_offsets = offsets
    CardRepository._record_provenance({card_id: card})     # 🔴 실제 생성 자리
    return card, directory


def _analyze(**kwargs):
    """상태 + 결합 판정을 **둘 다** 실제 경로로 얻는다."""
    card, directory = _card(**kwargs)
    repo = _StubRepo(directory, card)
    return card, repo, EffectAnalyzer(repo).analyze(card)


def _run_cli(capsys, **kwargs) -> str:
    card, repo, _analysis = _analyze(**kwargs)
    agent = type("Agent", (), {"repository": repo})()
    args = type("Args", (), {"card_id": card.id})()
    assert cmd_analyze(agent, args) == 0
    return capsys.readouterr().out


def _production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if set(path.relative_to(PROJECT_ROOT).parts) & {
                "tests", "__pycache__", ".git"}:
            continue
        yield path


def _changed_files() -> set[str]:
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-40:"],
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
# A. §2 — 상태는 어디서, 어떤 조건으로 생기는가
# ===========================================================================
def test_01_the_status_is_written_in_exactly_one_place():
    r"""🔴 §2 ① — ``analysis_status`` 에 **대입하는** production 자리는 하나다.

    문자열 검색이 아니라 AST 로 "대입 대상이 ``*.analysis_status`` 인 곳"
    을 센다.
    """
    writers: list[str] = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (isinstance(target, ast.Attribute)
                        and target.attr == "analysis_status"):
                    writers.append(str(path.relative_to(PROJECT_ROOT)))
    assert writers == ["core/card_repository.py"] * 4, writers


def test_02_the_only_condition_is_whether_a_script_is_attached():
    r"""🔴 §2 ① — 조건은 ``card.script is not None`` **하나**다.

    같은 카드에서 script 만 떼었다 붙였다 하며 **실행으로** 확인한다.
    """
    with_script, _ = _card()
    assert with_script.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    without, _ = _card(lua=None)
    assert without.provenance.analysis_status is not AnalysisStatus.LUA_VERIFIED
    #: 같은 카드에서 script 를 떼고 다시 기록하면 상태가 바뀐다
    with_script.script = None
    CardRepository._record_provenance({with_script.id: with_script})
    assert with_script.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED


def test_03_the_status_is_decided_without_running_any_analysis():
    r"""🔴 §2 ① — **분석기를 한 번도 부르지 않고** 상태가 정해진다.

    ``_record_provenance`` 의 소스에 분석기가 등장하지 않는다 (AST import
    검사), 그리고 분석기를 부르지 않은 카드에 이미 상태가 붙어 있다.
    """
    source = textwrap.dedent(
        inspect.getsource(CardRepository._record_provenance))
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("effect_analyzer" in m or "analysis" in m for m in imported), \
        imported
    for token in ("EffectAnalyzer", "handler_binding", "HandlerBinding",
                  "coverage"):
        assert token not in source, token
    card, _dir = _card()
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


@pytest.mark.parametrize(
    "label,kwargs,expected",
    [
        ("script 있음", {}, AnalysisStatus.LUA_VERIFIED),
        ("통상 몬스터", {"lua": None, "kind": "normal_monster"},
         AnalysisStatus.NO_EFFECT),
        ("텍스트만", {"lua": None}, AnalysisStatus.TEXT_DERIVED),
        ("근거 없음", {"lua": None, "desc": ""}, AnalysisStatus.UNAVAILABLE),
    ],
)
def test_04_each_status_comes_from_a_different_condition(label, kwargs, expected):
    r"""🟢 §2 ② — 네 상태가 실제로 서로 다른 조건에서 나온다."""
    card, _dir = _card(**kwargs)
    assert card.provenance.analysis_status is expected, label


def test_05_availability_flags_follow_the_same_single_condition():
    r"""🔴 §2 ② — ``effect_analysis_available`` 도 같은 조건 하나를 본다.

    "분석이 가능하다" 가 아니라 "Lua 가 붙었다" 는 뜻이다.
    """
    card, _dir = _card()
    availability = card.provenance.availability
    assert availability.lua_available is True
    assert availability.effect_analysis_available is True
    assert availability.text_analysis_available is False
    #: script 가 없으면 둘 다 꺼지고 텍스트 쪽이 켜진다
    other, _dir2 = _card(lua=None)
    assert other.provenance.availability.lua_available is False
    assert other.provenance.availability.effect_analysis_available is False
    assert other.provenance.availability.text_analysis_available is True


# ===========================================================================
# B. §2 ③④ / §4 — 결합 상태와 **동시에** 성립한다
# ===========================================================================
@pytest.mark.parametrize(
    "label,kwargs,binding",
    [
        ("정상", {}, HandlerBinding.MATCHED),
        ("지문 불일치", {"break_digest": True}, HandlerBinding.MISMATCHED),
        ("지문 없음", {"drop_digest": True}, HandlerBinding.UNPROVABLE),
        ("파일 소실", {"on_disk": False}, HandlerBinding.SOURCE_MISSING),
        ("일부 어긋남", {"shift_one": True}, HandlerBinding.MISMATCHED),
    ],
)
def test_06_lua_verified_coexists_with_every_binding_state(label, kwargs, binding):
    r"""🔴 §2 ④ / §4 ①②③⑤⑥ — **다섯 사례 모두 ``LUA_VERIFIED``** 다.

    결합이 어긋나든 증명할 수 없든 파일이 사라졌든, 상태는 그대로다.
    두 값이 **다른 계층**이라는 사실이 여기서 그대로 드러난다.
    """
    card, _repo, analysis = _analyze(**kwargs)
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED, label
    assert analysis.handler_binding is binding, label


def test_07_three_failure_bindings_leave_zero_structured_effects():
    r"""🔴 §4 ②③⑥ — 세 실패 상태에서는 등록 효과가 **0개**인데도
    상태가 "Lua 에서 구조화했다" 로 남는다. 그것이 거짓 표시의 실체다."""
    for kwargs in ({"break_digest": True}, {"drop_digest": True},
                   {"on_disk": False}):
        card, _repo, analysis = _analyze(**kwargs)
        assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
        assert analysis.effects == []
        assert analysis.resolution_effects == []
        assert len(analysis.unbound_effects) == 2


def test_08_a_failed_binding_does_not_demote_the_status():
    r"""🔴 §5 금지 — 결합 실패로 상태를 **일괄 강등하지 않았다**.

    근거(Lua 가 붙어 있다)가 사라진 것은 아니기 때문이다. 강등하면 "Lua 가
    없는 카드" 와 구별되지 않는다.
    """
    broken, _repo, _a = _analyze(break_digest=True)
    missing, _dir = _card(lua=None)
    assert broken.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    assert missing.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    assert broken.provenance.analysis_status is not missing.provenance.analysis_status


def test_09_a_matched_binding_does_not_promote_the_status():
    r"""🔴 §3 금지 — ``HANDLER_MATCHED`` 로 ``LUA_VERIFIED`` 를 만들지 않았다.

    Lua 가 없는 카드는 블록이 0개라 카드 단위 결합이 ``MATCHED`` 인데
    (3-F-37 의 규정: 어긋날 자리가 없다), 상태는 ``LUA_VERIFIED`` 가
    아니다. 둘을 연결하는 코드가 없다는 뜻이다.
    """
    card, _dir = _card(lua=None)
    repo = _StubRepo(_dir, card)
    analysis = EffectAnalyzer(repo).analyze(card)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.has_script is False
    assert card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED


def test_10_no_production_code_joins_the_two_layers():
    r"""🔴 §5 금지 — 두 계층을 한 상태로 합치는 코드가 **없다**.

    ``analysis_status`` 에 대입하는 모듈에 ``HandlerBinding`` 이 등장하지
    않고, 반대로 결합을 정하는 자리에 ``AnalysisStatus`` 가 없다.
    """
    #: 🔴 **주석의 언급은 결합이 아니다.** ``card_repository.py`` 는 3-F-35
    #: 이후 주석에서 ``HandlerBinding`` 을 설명하는데, 그것은 설명이고
    #: 코드가 아니다. 그래서 문자열이 아니라 **AST 로 실행 코드만** 본다.
    def executable_names(module) -> set[str]:
        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        return names

    writer = executable_names(repository_module)
    assert "HandlerBinding" not in writer
    assert "handler_binding" not in writer
    analyzer_source = textwrap.dedent(
        inspect.getsource(EffectAnalyzer._analyze_card))
    analyzer_names: set[str] = set()
    for node in ast.walk(ast.parse(analyzer_source)):
        if isinstance(node, ast.Name):
            analyzer_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            analyzer_names.add(node.attr)
    assert "AnalysisStatus" not in analyzer_names
    assert "analysis_status" not in analyzer_names


# ===========================================================================
# C. §4 — 파싱 결과가 없어도 상태는 그대로다 (실제 코퍼스)
# ===========================================================================
def test_11_a_script_with_zero_effect_blocks_is_still_lua_verified():
    r"""🔴 §2 ② / §4 — 효과 블록이 **0개**인 스크립트도 ``LUA_VERIFIED`` 다.

    ``Fusion.AddProcMix`` · ``EnableReviveLimit`` 만 있는 융합 몬스터가
    실제로 이 모양이다 (코퍼스 183장).
    """
    card, _repo, analysis = _analyze(lua=ZERO_BLOCKS)
    assert card.script is not None
    assert list(card.script.effects) == []
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    assert analysis.effects == [] and analysis.unbound_effects == []
    #: 🟢 결합은 ``MATCHED`` 다 — 어긋날 블록이 없으니까. "증명" 이 아니다.
    assert analysis.handler_binding is HandlerBinding.MATCHED


@requires_official_db
def test_12_real_cards_are_lua_verified_with_no_registered_effect(repository):
    r"""🔴 §4 — **실제 코퍼스 215장**이 그 상태다 (가상 사례가 아니다)."""
    analyzer = EffectAnalyzer(repository)
    zero_blocks = resolution_only = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        if card.provenance.analysis_status is not AnalysisStatus.LUA_VERIFIED:
            continue
        analysis = analyzer.analyze(card)
        if analysis.effects:
            continue
        if not card.script.effects:
            zero_blocks += 1
        else:
            resolution_only += 1
    assert zero_blocks == ZERO_BLOCK_CARDS
    assert resolution_only == RESOLUTION_ONLY_CARDS
    assert zero_blocks + resolution_only == LUA_VERIFIED_NO_EFFECTS


@requires_official_db
def test_13_the_zero_block_samples_are_real_and_still_lua_verified(repository):
    r"""🟢 §4 — 보고서가 든 세 장을 실제로 확인한다."""
    for card_id in ZERO_BLOCK_SAMPLES:
        card = repository.get(card_id)
        assert card is not None, card_id
        assert card.script is not None, card_id
        assert list(card.script.effects) == [], card_id
        assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


def test_14_a_matched_binding_does_not_prove_the_meaning_is_right():
    r"""🔴 §3 — ``MATCHED`` 는 **의미의 정확성을 증명하지 않는다**.

    결합이 전부 증명된 카드에도 구조화하지 못한 호출이 남는다. 즉
    "핸들러를 올바르게 짝지었다" 와 "효과를 올바르게 이해했다" 는 다르다.
    """
    _card_obj, _repo, analysis = _analyze()
    assert analysis.handler_binding is HandlerBinding.MATCHED
    unparsed = [u for e in analysis.effects
                for u in list(e.activation.unparsed) + list(e.unparsed)]
    assert unparsed, "이 픽스처는 미구조화 호출이 남도록 만들었다"


# ===========================================================================
# D. §2 ⑤ — 텍스트 기반 보충 분석
# ===========================================================================
def test_15_text_derived_only_happens_without_a_script():
    r"""🟢 §2 ⑤ — 텍스트 상태는 Lua 가 없을 때만 붙는다. 섞이지 않는다."""
    with_script, _ = _card()
    without, _ = _card(lua=None)
    assert with_script.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    assert without.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    assert without.provenance.source_of("effect_analysis").value == "official_text"
    assert with_script.provenance.source_of("effect_analysis").value == "lua"


def test_16_the_text_analyzer_has_no_production_caller():
    r"""🔴 §2 ⑤ — ``TextEffectAnalyzer`` 는 production 호출자가 **0개**다.

    그러므로 "텍스트 유래" 는 텍스트 분석을 돌린 결과가 아니라 **근거
    표시**다. 텍스트 결과가 Lua 검증으로 승격될 경로도 없다 — 돌지 않으니까.
    """
    callers = []
    for path in _production_files():
        if path.name == "text_effect_analyzer.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "TextEffectAnalyzer(" in text:
            callers.append(str(path.relative_to(PROJECT_ROOT)))
    assert callers == [], callers


def test_17_no_code_path_upgrades_text_derived_to_lua_verified():
    r"""🔴 §2 ⑤ — 텍스트 상태를 Lua 상태로 바꾸는 코드가 없다.

    상태 대입은 네 줄뿐이고 모두 ``_record_provenance`` 의 서로 다른
    분기에 있다 (``test_01``). 재대입·승격 분기가 없음을 AST 로 본다.
    """
    source = textwrap.dedent(
        inspect.getsource(CardRepository._record_provenance))
    assigns = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and target.attr == "analysis_status"
    ]
    assert len(assigns) == 4
    #: 네 대입이 모두 **서로 다른** 상태를 쓴다 — 덮어쓰기가 아니다
    written = {ast.unparse(node.value) for node in assigns}
    assert written == {
        "AnalysisStatus.LUA_VERIFIED", "AnalysisStatus.NO_EFFECT",
        "AnalysisStatus.TEXT_DERIVED", "AnalysisStatus.UNAVAILABLE",
    }, written


# ===========================================================================
# E. §2 ⑧ — provenance 가 소비자에게 도달하는가
# ===========================================================================
def test_18_the_status_has_exactly_two_production_readers():
    r"""🔴 §2 ⑧ — 쓰는 곳은 하나, **읽는 곳은 둘**이다 (전수)."""
    readers: set[str] = set()
    for path in _production_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "analysis_status" not in line or line.lstrip().startswith("#"):
                continue
            if "analysis_status =" in line or "analysis_status:" in line:
                continue
            readers.add(str(path.relative_to(PROJECT_ROOT)))
    assert readers == {"core/provenance.py", "scripts/update_cards.py",
                       "app/main.py"}, readers


def test_19_the_rich_provenance_record_never_reaches_a_user():
    r"""🔴 §2 ⑧ — ``CardProvenance.describe_ko()`` 는 production 호출자가
    **없다**. 필드별 출처·충돌 기록은 만들어서 카드에 달아 두기만 하고 아무
    화면에도 나오지 않는다 (provenance 소실의 실체)."""
    callers = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"provenance\.describe_ko\(\)", text):
            callers.append(str(path.relative_to(PROJECT_ROOT)))
    assert callers == [], callers
    #: 그래도 기록 자체는 만들어진다 — 쓰이지 않을 뿐이다
    card, _dir = _card()
    assert isinstance(card.provenance, CardProvenance)
    assert card.provenance.fields
    assert "effect_analysis" in card.provenance.fields


def test_20_the_availability_flags_never_reach_a_user_either():
    r"""🟠 §2 ⑧ — 여섯 개 availability 플래그도 사용자 출력에 없다."""
    shown = []
    for path in _production_files():
        if path.name == "provenance.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for flag in ("lua_available", "effect_analysis_available",
                     "text_analysis_available", "official_text_available",
                     "korean_available", "cdb_available"):
            if flag in text and "print" in text:
                shown.append((str(path.relative_to(PROJECT_ROOT)), flag))
    #: 기록하는 자리(card_repository)뿐이고 출력하는 자리는 없다
    assert {p for p, _f in shown} <= {"core/card_repository.py"}, shown


# ===========================================================================
# F. §2 ⑦ — 캐시·직렬화를 지나며 상태가 잘못 유지되는가
# ===========================================================================
def test_21_the_status_is_not_serialised_anywhere():
    r"""🔴 §2 ⑦ — ``CardProvenance`` 에는 직렬화 메서드가 없고, Lua 캐시와
    source_manager 상태 파일에도 저장되지 않는다. 그래서 상태가 **낡은
    값으로 남을** 경로는 없다 — 매 ``build()`` 마다 새로 계산된다."""
    source = inspect.getsource(provenance_module)
    for token in ("def to_dict", "def from_dict", "def to_json",
                  "def from_json"):
        assert token not in source, token
    import sources.lua_loader as loader
    import sources.source_manager as manager
    for module in (loader, manager):
        text = inspect.getsource(module)
        assert "analysis_status" not in text, module.__name__


def test_22_a_stale_cache_keeps_the_status_while_the_proof_fails():
    r"""🔴 §2 ⑦ — 상태가 **승격**되지는 않지만, 낡은 캐시로 **유지**된다.

    ``card.script`` 는 캐시에서 오고 상태는 그 존재만 본다. 파일이 사라진
    뒤에도 상태는 ``LUA_VERIFIED`` 이고, 증명만 ``SOURCE_MISSING`` 이 된다.
    이것이 "캐시를 통과하며 잘못 유지되는" 경로다.
    """
    card, _repo, analysis = _analyze(on_disk=False)
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    assert analysis.handler_binding is HandlerBinding.SOURCE_MISSING
    #: 다시 기록해도 그대로다 — script 가 여전히 붙어 있으니까
    CardRepository._record_provenance({card.id: card})
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


def test_23_rebuilding_recomputes_the_status_from_the_current_card():
    r"""🟢 §2 ⑦ — 상태는 카드의 현재 모습에서 매번 새로 계산된다."""
    card, _dir = _card()
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    first = card.provenance
    CardRepository._record_provenance({card.id: card})
    assert card.provenance is not first          # 새 기록으로 교체된다
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


# ===========================================================================
# G. §2 ⑥ — 카드 단위와 블록 단위
# ===========================================================================
def test_24_card_level_and_block_level_states_mean_different_things():
    r"""🔴 §2 ⑥ — 카드 단위 결합은 **가장 심각한 값**, 블록 단위는 개별이다.

    카드가 ``MISMATCHED`` 라고 블록이 전부 어긋난 것은 아니다.
    """
    _card_obj, _repo, analysis = _analyze(shift_one=True)
    assert analysis.handler_binding is HandlerBinding.MISMATCHED
    blocks = collections.Counter(
        effect.handler_binding
        for group in (analysis.effects, analysis.resolution_effects,
                      analysis.unbound_effects)
        for effect in group
    )
    assert blocks == {HandlerBinding.MATCHED: 1, HandlerBinding.MISMATCHED: 1}


def test_25_a_blockless_card_is_matched_without_proving_anything():
    r"""🔴 §2 ⑥ — 블록이 0개인 카드의 ``MATCHED`` 는 "증명했다" 가 아니라
    "어긋날 자리가 없다" 다. 이 값을 검증으로 읽으면 안 된다."""
    for lua in (None, ZERO_BLOCKS):
        card, _repo, analysis = _analyze(lua=lua)
        assert analysis.handler_binding is HandlerBinding.MATCHED
        total = (len(analysis.effects) + len(analysis.resolution_effects)
                 + len(analysis.unbound_effects))
        assert total == 0


# ===========================================================================
# H. §6 ⑫⑬ — CLI 진단과 갱신 요약
# ===========================================================================
def test_26_the_analyze_cli_shows_the_basis_next_to_the_proof(capsys):
    r"""🔴 §3 — 한 카드에서 **근거와 증명을 나란히** 보여준다 (합치지 않는다)."""
    out = _run_cli(capsys)
    assert "분석 근거" in out and "lua_verified" in out
    assert "결합 상태" in out and "정상 연결" in out
    #: 근거 줄이 증명 줄보다 먼저 나오고, 둘이 **다른 줄**이다
    assert out.index("분석 근거") < out.index("결합 상태")


def test_27_the_cli_shows_both_when_they_disagree(capsys):
    r"""🔴 §4 ②③⑥ — 두 값이 어긋날 때 **둘 다** 보인다.

    예전에는 이 화면에 근거가 없었으므로, "증명 실패" 만 보이고 그 카드가
    여전히 ``lua_verified`` 로 집계된다는 사실은 알 수 없었다.
    """
    for kwargs in ({"break_digest": True}, {"drop_digest": True},
                   {"on_disk": False}):
        out = _run_cli(capsys, **kwargs)
        assert "분석 근거" in out and "lua_verified" in out, kwargs
        assert "🔴 결합 상태" in out, kwargs


def test_28_the_cli_survives_a_card_without_a_provenance_record(capsys):
    r"""🟢 §6 — provenance 가 없는 카드(테스트 스텁 등)에서도 터지지 않고,
    근거 줄만 빠진다. 없는 정보를 지어내지 않는다."""
    directory = tempfile.mkdtemp()
    text = textwrap.dedent(TWO_BLOCKS)
    pathlib.Path(directory, "c1.lua").write_text(text, encoding="utf-8")
    card = Card(id=1, name="c1.lua")
    card.script = parse_lua_source(1, "c1.lua", text)
    assert card.provenance is None
    agent = type("Agent", (), {"repository": _StubRepo(directory, card)})()
    args = type("Args", (), {"card_id": 1})()
    assert cmd_analyze(agent, args) == 0
    out = capsys.readouterr().out
    assert "분석 근거" not in out
    assert "결합 상태" in out


@requires_official_db
def test_29_the_update_summary_no_longer_claims_verification(capsys, repository):
    r"""🔴 §5 — 갱신 요약의 라벨이 **검증을 주장하지 않는다**.

    예전 라벨은 "Lua 검증됨" 이었고, 그 행의 조건은 script 존재 하나였다.
    """
    summarise(repository)
    out = capsys.readouterr().out
    assert "Lua 검증됨" not in out
    assert "Lua 근거 있음" in out
    assert f"{STATUS_COUNTS['lua_verified']:,}장" in out


@requires_official_db
def test_30_the_update_summary_says_what_the_table_counts(capsys, repository):
    r"""🔴 §5 — 표가 **근거만** 센다는 사실과, 증명은 다른 표가 센다는 사실을
    출력 자체가 적는다. 두 계층을 한 숫자로 합치지 않는다."""
    summarise(repository)
    out = capsys.readouterr().out
    assert "분석 근거만 셉니다" in out
    assert "결합 증명은 별도" in out
    assert "표에 없는 분석 상태" not in out
    #: 🔴 결합 표의 제목을 이 설명에 넣지 않았다 — 넣으면 "결합 표가
    #: 출력됐는가" 를 그 문구로 확인하는 기존 테스트가 거짓 양성이 된다.
    assert "효과 블록 결합 상태" not in out


@requires_official_db
def test_31_the_status_rows_still_add_up(repository):
    r"""🟢 §8 — 상태 분포가 기준과 같다 (라벨만 고쳤고 생성은 그대로)."""
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards()
    )
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CARD_TOTAL


# ===========================================================================
# I. §6 ⑭⑮ / §8 — 반복 실행과 산출물 불변
# ===========================================================================
def test_32_the_same_input_gives_the_same_status_twice():
    r"""🟢 §6 ⑭ — 같은 입력을 두 번 돌리면 상태와 결합이 같다."""
    first = _analyze(shift_one=True)
    second = _analyze(shift_one=True)
    assert (first[0].provenance.analysis_status
            is second[0].provenance.analysis_status)
    assert first[2].handler_binding is second[2].handler_binding
    assert first[2].coverage() == second[2].coverage()


@requires_official_db
def test_33_the_status_and_binding_cross_tab_is_unchanged(repository):
    r"""🔴 §8 — 상태 × 결합 교차표를 전수로 다시 센다.

    상태 생성 조건을 건드렸다면 이 표가 움직인다 — 움직이지 않았다는 것이
    "표시만 고쳤다" 의 증거다.
    """
    analyzer = EffectAnalyzer(repository)
    cross: collections.Counter = collections.Counter()
    for card in repository.all_cards():
        status = card.provenance.analysis_status.value
        if card.script is None:
            cross[(status, "<블록 없음>")] += 1
            continue
        cross[(status, analyzer.analyze(card).handler_binding.value)] += 1
    assert dict(cross) == {
        ("lua_verified", "matched"): ATTACHED_CARDS,
        ("text_derived", "<블록 없음>"): STATUS_COUNTS["text_derived"],
        ("no_effect", "<블록 없음>"): STATUS_COUNTS["no_effect"],
    }


@requires_official_db
def test_34_analysis_and_search_outputs_are_unchanged(repository):
    r"""🟢 §8 — 분석 집계·검색 결과·``EffectRef`` 가 그대로다."""
    analyzer = EffectAnalyzer(repository)
    registered = resolution = 0
    blocks: collections.Counter = collections.Counter()
    refs_total = refs_bad = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        analysis = analyzer.analyze(card)
        registered += len(analysis.effects)
        resolution += len(analysis.resolution_effects)
        for group in (analysis.effects, analysis.resolution_effects,
                      analysis.unbound_effects):
            for effect in group:
                blocks[effect.handler_binding] += 1
        refs = effect_refs(card)
        refs_total += len(refs)
        for ordinal, ref in enumerate(refs):
            if ref != EffectRef(card.id, ordinal):
                refs_bad += 1
    assert (registered, resolution) == (26352, 8283)
    assert dict(blocks) == {HandlerBinding.MATCHED: ATTACHED_BLOCKS}
    assert (refs_total, refs_bad) == (ATTACHED_BLOCKS, 0)

    engine = CardSearchEngine(repository)
    cards = [c for c in repository.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert len(categories) == 31 and len(locations) == 31
    category_total = sum(
        len(engine.search(SearchFilters(effect_categories=(name,))).cards)
        for name in categories
    )
    assert category_total == 19372
    location_total = 0
    for name in locations:
        try:
            location_total += len(engine.search(SearchFilters(
                effect_locations=(EffectLocationFilter(location=name),))).cards)
        except Exception:
            location_total += -1
    assert location_total == 10612


# ===========================================================================
# J. §7 금지 사항 · §10 범위
# ===========================================================================
def test_35_no_new_status_or_enum_was_invented():
    r"""🔴 §7 금지 — 새 공용 enum 도, 새 상태 값도 만들지 않았다."""
    assert [s.value for s in AnalysisStatus] == [
        "lua_verified", "text_derived", "no_effect", "unavailable", "unknown",
    ]
    assert [b.value for b in HandlerBinding] == [
        "matched", "mismatched", "unprovable", "source_missing",
    ]
    #: 소비자는 상태를 **읽기만** 한다
    for module in (main_module, update_module):
        source = inspect.getsource(module)
        assert "analysis_status =" not in source, module.__name__


def test_36_production_change_is_confined_to_three_files():
    r"""🟢 §10 — 상태 설명 · 갱신 라벨 · 분석 CLI. 그 밖은 없다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    allowed = {
        "core/provenance.py",
        "scripts/update_cards.py",
        "app/main.py",
        "tests/test_lua_verified_provenance_audit.py",
        "tests/test_handler_binding_diagnostics.py",
        "tests/test_update_coverage_contract_audit.py",
        "docs/phase3f40-lua-verified-provenance-audit.md",
    }
    assert changed <= allowed, changed - allowed


def test_37_no_forbidden_path_was_touched():
    r"""🔴 §7 금지 — Lua · README · engine · agent · 검색 계층 · data 미변경."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        assert not path.startswith("engine/"), path
        assert not path.startswith("agent/"), path
        assert "card_search" not in path, path
        assert not path.startswith("data/"), path


def test_38_the_status_generation_code_was_not_changed():
    r"""🔴 §5 금지 — 상태를 **만드는 코드는 한 줄도 바꾸지 않았다**.

    고친 것은 설명(docstring)과 사용자에게 보이는 라벨이다. 생성 조건을
    건드리면 기존 계약이 바뀌고, 그것은 §5 가 금지한 일괄 강등·승격이 된다.
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-40:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    base = subprocess.run(
        ["git", "rev-parse", f"{shas[-1]}^"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", base, "HEAD", "--", "core/card_repository.py"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout
    assert diff.strip() == "", diff[:400]


def test_39_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 §6 금지 — 기존 테스트 삭제·skip 추가가 없다.

    두 기존 테스트의 **assertion 을 고쳤다** — "Lua 검증됨" 이라는 라벨을
    고정하고 있었고, 그 라벨이 이 Phase 가 거짓으로 판정한 주장이다. 둘 다
    새 라벨 확인 + "검증" 주장 부재 확인으로 **강화**했다 (보고서 §7).
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-40:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    base = subprocess.run(
        ["git", "rev-parse", f"{shas[-1]}^"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()

    def counts(ref: str) -> dict[str, int]:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "tests/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        out: dict[str, int] = {}
        for name in listing:
            if not name.endswith(".py"):
                continue
            text = subprocess.run(
                ["git", "show", f"{ref}:{name}"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
            ).stdout
            out[name] = len(re.findall(r"^def test_", text, re.M))
        return out

    before, after = counts(base), counts("HEAD")
    for name, count in before.items():
        assert name in after, f"테스트 파일이 사라졌다: {name}"
        assert after[name] >= count, (name, count, after[name])
    #: 새로 추가한 skip 은 "commit 이 아직 없다" 조건부뿐이다
    for name in set(after) - set(before):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for match in re.findall(r"pytest\.skip\([^)]*\)", text):
            assert "commit 이 아직 없다" in match, (name, match)
