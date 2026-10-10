r"""
Phase 3-F-38 — ``HandlerBinding`` 사용자 노출 및 카드 갱신 복구 안내
=====================================================================

무엇이 문제였나
---------------
Phase 3-F-37 은 블록과 핸들러의 대응을 ``(소스 지문, 블록 offset)`` 쌍으로
증명하고, 증명하지 못한 블록을 ``CardAnalysis.unbound_effects`` 로 보내며
``handler_binding`` 에 네 상태 중 하나를 적었다. 🔴 **그런데 그 값을 읽는
곳이 없었다.**

* ``app/main.py`` 의 ``cmd_analyze`` 는 ``effects``/``resolution_effects`` 만
  출력했다. 증명되지 않은 블록은 두 목록 어디에도 없으므로, 사용자 눈에는
  **그냥 효과가 적게 보였다** — 왜 적은지는 어디에도 적히지 않았다.
* ``scripts/update_cards.py`` 는 ``analyzer.analyze(card)`` 를 부르고
  **반환값을 버렸다** (건수만 셌다).
* 🔴 그리고 ``summarise()`` 의 상태 표에 ``NO_EFFECT`` 행이 **빠져 있어**
  실측 684장이 요약에서 사라졌다 (12,687 + 756 = 13,443 ≠ 14,127).

이 Phase 가 한 일
-----------------
1. 네 상태의 **이름과 복구 안내**를 :data:`analysis.effect_model._BINDING_GUIDANCE_KO`
   한 곳에 두고, 두 소비자가 **import 한다** — 복사하지 않는다.
2. ``cmd_analyze`` 가 블록 건수를 **실제 필드에서 세어** 출력한다.
3. ``update_cards`` 가 분석 결과를 들고 있다가 상태별 건수와 안내를 적는다.
4. ``summarise()`` 의 누락된 행을 채우고, 표에 없는 상태가 생기면 드러낸다.

🔴 **갱신의 성공·실패 판정은 바꾸지 않았다.** ``validate()`` 의 계약은 "데이터가
덜 모였다는 이유로 카드가 사라지지 않는다" 이고 그것은 카드 레코드의 온전함에
관한 것이다. 결합 상태는 **효과 분석의 증명 여부**라서 같은 축이 아니다.
"""

from __future__ import annotations

import ast
import collections
import inspect
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import app.main as main_module
import scripts.update_cards as update_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import _BINDING_GUIDANCE_KO, HandlerBinding
from app.main import cmd_analyze
from core.card_model import Card
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus
from engine.ids import EffectRef, effect_refs
from scripts.update_cards import report_bindings, summarise
from sources.lua_loader import parse_lua_source
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-37 이 보고한 기준값 (테스트가 실제로 다시 산출한다) ---------
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
ANALYSIS_TOTALS = {
    "registered": 26352, "resolution": 8283, "cond": 12438,
    "cost": 5007, "target": 5516, "action": 18280, "cat": 20484,
}
#: Phase 3-F-38 이 실측한 분석 상태 분포
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}
CARD_TOTAL = 14127

ANALYZE_CARD = 32807846          # 증원 — 블록 1개, 전부 증명됨


# ===========================================================================
# 공용 도구 — 실제 parser/analyzer/CLI 경로만 쓴다
# ===========================================================================
TWO_BLOCKS = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_ACTIVATE)
        e1:SetCode(EVENT_FREE_CHAIN)
        e1:SetCondition(s.con)
        c:RegisterEffect(e1)
        local e2=Effect.CreateEffect(c)
        e2:SetType(EFFECT_TYPE_ACTIVATE)
        e2:SetCost(s.cost)
        c:RegisterEffect(e2)
    end
"""
#: 앞에 주석 두 줄이 늘어 블록 offset 이 밀린다 — 지문도 달라진다
SHIFTED = "--줄이 두\n--늘었다\n" + TWO_BLOCKS
#: 핸들러가 하나도 없는 **유효한** 블록
NO_HANDLER = """
    function s.initial_effect(c)
        local e1=Effect.CreateEffect(c)
        e1:SetType(EFFECT_TYPE_SINGLE)
        e1:SetCode(EFFECT_UPDATE_ATTACK)
        e1:SetValue(500)
        c:RegisterEffect(e1)
    end
"""
NO_BLOCK = "function s.initial_effect(c)\nend\n"


class _StubRepo:
    """``cmd_analyze`` 와 ``EffectAnalyzer`` 가 실제로 쓰는 최소 인터페이스."""

    constants = None

    def __init__(self, script_dir, card):
        self.script_dir = script_dir
        self._card = card

    def get(self, card_id):
        return self._card if card_id == self._card.id else None


def _analyze(parsed_text: str, disk_text: str, *, card_id: int = 1,
             drop_offsets: bool = False, drop_digest: bool = False,
             delete_file: bool = False):
    """``card.script`` 과 디스크 텍스트를 따로 두고 **실제 분석기**를 돌린다."""
    parsed_text = textwrap.dedent(parsed_text)
    disk_text = textwrap.dedent(disk_text)
    directory = tempfile.mkdtemp()
    name = f"c{card_id}.lua"
    path = pathlib.Path(directory, name)
    path.write_text(disk_text, encoding="utf-8")
    card = Card(id=card_id, name=name)
    card.script = parse_lua_source(card_id, name, parsed_text)
    if drop_offsets:
        card.script.effect_offsets = []
    if drop_digest:
        card.script.source_digest = None
    if delete_file:
        path.unlink()
    repo = _StubRepo(directory, card)
    return card, repo, EffectAnalyzer(repo).analyze(card)


def _run_cli(parsed_text: str, disk_text: str, capsys, **kwargs) -> str:
    """**실제 ``cmd_analyze``** 를 돌려 출력 문자열을 돌려준다."""
    card, repo, _analysis = _analyze(parsed_text, disk_text, **kwargs)
    agent = type("Agent", (), {"repository": repo})()
    args = type("Args", (), {"card_id": card.id})()
    code = cmd_analyze(agent, args)
    assert code == 0
    return capsys.readouterr().out


def _block_counts(analysis) -> dict[HandlerBinding, int]:
    """세 목록 **전부**에서 실제 필드를 읽어 센다."""
    counts: collections.Counter = collections.Counter()
    for group in (analysis.effects, analysis.resolution_effects,
                  analysis.unbound_effects):
        for effect in group:
            counts[effect.handler_binding] += 1
    return dict(counts)


def _changed_files() -> set[str]:
    """이 Phase 의 commit 들이 건드린 파일 — **commit 범위만** 본다."""
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-38:"],
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
# A. 안내 표 — 한 곳에 있고 네 상태가 서로 다르다
# ===========================================================================
def test_01_every_binding_state_has_a_name_and_guidance():
    r"""🟢 네 상태 **전부**가 표에 있다 — 빠진 상태가 생기면 터진다."""
    assert set(_BINDING_GUIDANCE_KO) == set(HandlerBinding)
    for binding, (name, hint) in _BINDING_GUIDANCE_KO.items():
        assert name.strip(), binding
        if binding is not HandlerBinding.MATCHED:
            assert hint.strip(), binding


def test_02_the_three_failure_states_give_different_guidance():
    r"""🔴 §4 — ``UNPROVABLE`` 이 ``MISMATCHED`` 와 **같은 문장을 쓰지 않는다**.

    "틀렸다" 와 "모른다" 는 복구 방법이 다르다 — 앞은 소스 확인, 뒤는 캐시
    재생성이다. 같은 메시지를 쓰면 사용자가 어느 쪽인지 알 수 없다.
    """
    hints = {
        binding: _BINDING_GUIDANCE_KO[binding][1]
        for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE,
                        HandlerBinding.SOURCE_MISSING)
    }
    assert len(set(hints.values())) == 3
    names = {_BINDING_GUIDANCE_KO[b][0] for b in HandlerBinding}
    assert len(names) == 4
    #: 각 안내가 서로 다른 복구 수단을 지목한다
    assert "--scripts" in hints[HandlerBinding.MISMATCHED]
    assert "캐시" in hints[HandlerBinding.UNPROVABLE]
    assert "읽지 못했습니다" in hints[HandlerBinding.SOURCE_MISSING]


def test_03_the_guidance_does_not_assert_an_unproven_cause():
    r"""🔴 §4 — "증거가 없는 원인을 확정적으로 단정하지 않는다".

    어긋났다는 것은 측정된 사실이지만 *왜* 어긋났는지는 이 자료만으로 알 수
    없다 (캐시 노후 · ``--scripts`` 경로 · 소스 편집이 같은 모양을 만든다).
    """
    for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE):
        hint = _BINDING_GUIDANCE_KO[binding][1]
        #: 원인을 단정하는 어미가 없다
        assert "캐시가 낡았습니다" not in hint
        assert "때문입니다" not in hint
        #: 확인을 요청하거나 가능성으로 적는다
        assert ("확인하세요" in hint) or ("수 있습니다" in hint)


def test_04_both_consumers_import_the_one_table_instead_of_copying():
    r"""🔴 **복사본을 두지 않는다.** 한쪽만 고친 순간 두 경로가 갈린다
    (Phase 3-F-28 이 탐지 정규식에서, 3-F-32 가 ``Clone`` 형태에서 겪었다)."""
    for module in (main_module, update_module):
        source = inspect.getsource(module)
        assert "_BINDING_GUIDANCE_KO" in source, module.__name__
        #: 라벨 문자열을 **직접 적어 둔 곳이 없다**
        for literal in ("대응 불일치 확인", "대응 관계 증명 불가", "입력 소스 없음"):
            assert literal not in source, (module.__name__, literal)


def test_05_no_new_public_api_or_enum_was_added():
    r"""🟢 §4 금지 — 새 공용 enum·진단 프레임워크·공개 API 를 만들지 않았다."""
    import analysis.effect_model as model

    enums = {
        node.name for node in ast.walk(ast.parse(inspect.getsource(model)))
        if isinstance(node, ast.ClassDef)
        and any(getattr(b, "id", "") == "Enum" or getattr(b, "attr", "") == "Enum"
                for b in node.bases)
    }
    #: ``HandlerBinding`` 은 3-F-37 것이고, 이 Phase 는 enum 을 더하지 않았다
    assert "HandlerBinding" in enums
    assert _BINDING_GUIDANCE_KO.__class__ is dict
    #: 이름이 ``_`` 로 시작한다 — 공개 API 가 아니다
    assert not hasattr(model, "BINDING_GUIDANCE_KO")


# ===========================================================================
# B. §6 ①②③④⑤ — CLI 가 네 상태를 구분해 보여준다
# ===========================================================================
def test_06_matched_is_reported_as_normal(capsys):
    r"""🟢 §6 ① — 전부 증명된 경우도 **출력된다** (침묵하지 않는다)."""
    out = _run_cli(TWO_BLOCKS, TWO_BLOCKS, capsys)
    assert "결합 상태" in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MATCHED][0] in out
    assert "블록 2개 전부 증명됨" in out
    assert "🔴" not in out


def test_07_a_valid_block_with_no_handler_is_not_an_error(capsys):
    r"""🟢 §6 ② — **핸들러가 비어 있다는 이유로 오류를 내지 않는다.**

    "핸들러 없는 유효 블록" 은 정상이고 코퍼스에 9,887개 있다 (3-F-37).
    증명된 것은 **대응 관계**이지 핸들러의 존재가 아니다.
    """
    card, _repo, analysis = _analyze(NO_HANDLER, NO_HANDLER)
    assert analysis.handler_binding is HandlerBinding.MATCHED
    assert analysis.unbound_effects == []
    assert len(analysis.effects) == 1
    assert analysis.effects[0].costs == [] and not analysis.effects[0].has_condition

    out = _run_cli(NO_HANDLER, NO_HANDLER, capsys)
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MATCHED][0] in out
    assert "🔴" not in out
    for literal in ("대응 불일치 확인", "대응 관계 증명 불가", "입력 소스 없음"):
        assert literal not in out


def test_08_mismatched_is_shown_clearly_with_its_blocks(capsys):
    r"""🔴 §6 ③ — 불일치가 **명확히** 표시되고 어느 블록인지도 적힌다."""
    out = _run_cli(TWO_BLOCKS, SHIFTED, capsys)
    assert "🔴 결합 상태" in out
    assert "증명된 블록 0/2" in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][0] in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][1] in out
    assert "[e1, e2]" in out
    #: 🟢 왜 효과 목록이 비었는지도 적는다
    assert "어느 쪽이라고 주장할 근거가 없기 때문" in out


def test_09_unprovable_is_not_shown_as_mismatched(capsys):
    r"""🔴 §6 ④ — ``UNPROVABLE`` 을 ``MISMATCHED`` 로 **잘못 표시하지 않는다**."""
    out = _run_cli(TWO_BLOCKS, TWO_BLOCKS, capsys, drop_digest=True)
    assert _BINDING_GUIDANCE_KO[HandlerBinding.UNPROVABLE][0] in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.UNPROVABLE][1] in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][0] not in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][1] not in out


def test_10_missing_offsets_also_report_unprovable(capsys):
    r"""🟠 평행 목록이 비어 있어도 "모른다" 로 적는다 (낡은 캐시 모양)."""
    out = _run_cli(TWO_BLOCKS, TWO_BLOCKS, capsys, drop_offsets=True)
    assert _BINDING_GUIDANCE_KO[HandlerBinding.UNPROVABLE][0] in out
    assert "캐시" in out


def test_11_source_missing_is_shown_separately(capsys):
    r"""🔴 §6 ⑤ — 소스 누락이 **별도 상태**로 표시된다."""
    out = _run_cli(TWO_BLOCKS, TWO_BLOCKS, capsys, delete_file=True)
    assert _BINDING_GUIDANCE_KO[HandlerBinding.SOURCE_MISSING][0] in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.SOURCE_MISSING][1] in out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][0] not in out


def test_12_source_missing_and_mismatched_guidance_differ_in_output(capsys):
    r"""🔴 §6 ⑨ — 두 경우의 **안내가 실제 출력에서 구분된다**."""
    missing = _run_cli(TWO_BLOCKS, TWO_BLOCKS, capsys, delete_file=True)
    mismatch = _run_cli(TWO_BLOCKS, SHIFTED, capsys)
    assert missing != mismatch
    missing_hint = _BINDING_GUIDANCE_KO[HandlerBinding.SOURCE_MISSING][1]
    mismatch_hint = _BINDING_GUIDANCE_KO[HandlerBinding.MISMATCHED][1]
    assert missing_hint in missing and missing_hint not in mismatch
    assert mismatch_hint in mismatch and mismatch_hint not in missing


# ===========================================================================
# C. §6 ⑥⑦⑩⑪ — 건수·전달·호환·식별자
# ===========================================================================
@pytest.mark.parametrize(
    "label,kwargs,expected",
    [
        ("정상", {}, HandlerBinding.MATCHED),
        ("불일치", {"disk": SHIFTED}, HandlerBinding.MISMATCHED),
        ("증명 불가(지문)", {"drop_digest": True}, HandlerBinding.UNPROVABLE),
        ("증명 불가(offset)", {"drop_offsets": True}, HandlerBinding.UNPROVABLE),
        ("소스 없음", {"delete_file": True}, HandlerBinding.SOURCE_MISSING),
    ],
)
def test_13_state_counts_sum_to_the_block_total(label, kwargs, expected):
    r"""🔴 §6 ⑥ — **상태별 건수의 합이 입력 블록 수와 같다.**

    어느 블록도 집계에서 사라지지 않는다는 것이 요약의 최소 조건이다.
    """
    disk = kwargs.pop("disk", TWO_BLOCKS)
    card, _repo, analysis = _analyze(TWO_BLOCKS, disk, **kwargs)
    counts = _block_counts(analysis)
    assert sum(counts.values()) == len(card.script.effects) == 2, label
    assert analysis.handler_binding is expected, label


def test_14_the_cli_counts_come_from_the_field_not_from_the_list(capsys):
    r"""🔴 출력이 "``effects`` 에 있으면 ``MATCHED``" 를 **가정하지 않는다**.

    가정이 깨지는 날 조용히 틀린 요약을 내게 된다. 세 목록 전부에서 실제
    필드를 읽는지 AST 로 확인한다.
    """
    func = next(
        node for node in ast.walk(ast.parse(textwrap.dedent(
            inspect.getsource(main_module.cmd_analyze))))
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_analyze"
    )
    reads = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Attribute) and node.attr == "handler_binding"
    ]
    assert len(reads) >= 1
    source = textwrap.dedent(inspect.getsource(main_module.cmd_analyze))
    for name in ("analysis.effects", "analysis.resolution_effects",
                 "analysis.unbound_effects"):
        assert name in source


def test_15_the_cli_total_matches_the_parsed_block_count(capsys):
    r"""🟢 §6 ⑥ — 출력에 적힌 분모가 **실제 블록 수**다."""
    out = _run_cli(TWO_BLOCKS, SHIFTED, capsys)
    match = re.search(r"증명된 블록 (\d+)/(\d+)", out)
    assert match is not None
    matched, total = int(match.group(1)), int(match.group(2))
    card, _repo, analysis = _analyze(TWO_BLOCKS, SHIFTED)
    assert total == len(card.script.effects) == 2
    assert matched == _block_counts(analysis).get(HandlerBinding.MATCHED, 0)


def test_16_a_card_with_no_blocks_prints_no_binding_line(capsys):
    r"""🟢 §6 ⑩ — 블록이 없으면 결합 줄을 **내지 않는다** (기존 동작 유지).

    어긋날 자리가 없는데 상태를 적으면 소음이다.
    """
    out = _run_cli(NO_BLOCK, NO_BLOCK, capsys)
    assert "결합 상태" not in out


@requires_official_db
def test_17_a_card_without_a_script_keeps_the_old_output(capsys, repository):
    r"""🟢 §6 ⑩ — Lua 가 없는 카드의 출력이 **그대로**다."""
    card = repository.get(89631139)          # 푸른 눈의 백룡
    assert card is not None and card.script is None
    agent = type("Agent", (), {"repository": repository})()
    args = type("Args", (), {"card_id": card.id})()
    assert cmd_analyze(agent, args) == 0
    out = capsys.readouterr().out
    assert "Lua 스크립트가 없습니다" in out
    assert "결합 상태" not in out


def test_18_the_output_does_not_alter_card_id_or_ordinals(capsys):
    r"""🔴 §6 ⑪ — 출력 과정에서 카드 ID · ``EffectRef`` · ordinal 이 바뀌지
    않는다. 진단을 찍는 코드가 데이터를 건드리면 안 된다."""
    card, repo, _analysis = _analyze(TWO_BLOCKS, SHIFTED)
    before_id = card.id
    before_refs = [(r.card_id, r.ordinal) for r in effect_refs(card)]
    before_offsets = list(card.script.effect_offsets)
    before_digest = card.script.source_digest

    agent = type("Agent", (), {"repository": repo})()
    args = type("Args", (), {"card_id": card.id})()
    assert cmd_analyze(agent, args) == 0
    capsys.readouterr()

    assert card.id == before_id
    assert [(r.card_id, r.ordinal) for r in effect_refs(card)] == before_refs
    assert before_refs == [(before_id, 0), (before_id, 1)]
    assert card.script.effect_offsets == before_offsets
    assert card.script.source_digest == before_digest


# ===========================================================================
# D. §5 / §6 ⑧ — 카드 갱신 경로
# ===========================================================================
def test_19_update_keeps_the_analysis_result_instead_of_discarding_it():
    r"""🔴 §6 ⑧ — ``update_cards`` 가 ``analyze()`` 의 **반환값을 쓴다**.

    3-F-37 까지는 호출만 하고 버렸다 (``analyzer.analyze(card)`` 한 줄).
    """
    source = inspect.getsource(update_module.main)
    assert "analysis = analyzer.analyze(card)" in source
    assert "bindings[analysis.handler_binding] += 1" in source
    assert "report_bindings(" in source
    #: 🔴 버리는 호출이 남아 있지 않다
    assert re.search(r"^\s*analyzer\.analyze\(card\)\s*$", source, re.M) is None


def test_20_update_summary_reports_each_state_separately(capsys):
    r"""🔴 §6 ⑧ — 상태별 건수와 안내가 갱신 요약에 **따로** 적힌다."""
    counts = collections.Counter({
        HandlerBinding.MATCHED: 10,
        HandlerBinding.MISMATCHED: 2,
        HandlerBinding.UNPROVABLE: 1,
        HandlerBinding.SOURCE_MISSING: 1,
    })
    report_bindings(counts, 14, 7, [2511, 32807846])
    out = capsys.readouterr().out
    for binding in HandlerBinding:
        assert _BINDING_GUIDANCE_KO[binding][0] in out, binding
    for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE,
                    HandlerBinding.SOURCE_MISSING):
        assert _BINDING_GUIDANCE_KO[binding][1] in out, binding
    assert "증명되지 않은 블록 7개" in out
    assert "2511" in out


def test_21_update_summary_states_are_not_collapsed_into_one_flag(capsys):
    r"""🔴 §7 금지 — 상태를 하나의 Boolean 으로 축약하지 않는다.

    세 실패 상태를 각각 넣었을 때 **세 번 모두 다른 문장**이 나온다.
    """
    seen = []
    for binding in (HandlerBinding.MISMATCHED, HandlerBinding.UNPROVABLE,
                    HandlerBinding.SOURCE_MISSING):
        report_bindings(collections.Counter({binding: 1}), 1, 1, [1])
        seen.append(capsys.readouterr().out)
    assert len(set(seen)) == 3
    for text, binding in zip(seen, (HandlerBinding.MISMATCHED,
                                    HandlerBinding.UNPROVABLE,
                                    HandlerBinding.SOURCE_MISSING)):
        assert _BINDING_GUIDANCE_KO[binding][1] in text


def test_22_update_summary_flags_a_count_mismatch(capsys):
    r"""🔴 §6 ⑥ — 합이 맞지 않으면 **요약 자체가 그것을 드러낸다**."""
    report_bindings(collections.Counter({HandlerBinding.MATCHED: 3}), 5, 0, [])
    out = capsys.readouterr().out
    assert "상태 합계" in out and "!=" in out
    #: 합이 맞으면 그 줄이 없다
    report_bindings(collections.Counter({HandlerBinding.MATCHED: 5}), 5, 0, [])
    assert "상태 합계" not in capsys.readouterr().out


def test_23_update_summary_is_silent_when_nothing_was_analysed(capsys):
    r"""🟢 분석한 카드가 없으면 아무것도 적지 않는다 (소음 금지)."""
    report_bindings(collections.Counter(), 0, 0, [])
    assert capsys.readouterr().out == ""


def test_24_update_does_not_change_the_success_or_failure_verdict():
    r"""🔴 §5 ③ — 갱신의 성공·실패 판정을 **무단으로 바꾸지 않았다**.

    ``validate()`` 의 계약은 "데이터가 덜 모였다는 이유로 카드가 사라지지
    않는다" 이고 그것은 카드 레코드의 온전함에 관한 것이다. 결합 상태는
    효과 분석의 증명 여부라서 같은 축이 아니다. 그래서 ``report_bindings``
    는 **보고만** 하고 ``problems`` 에 손대지 않는다.
    """
    validate_source = inspect.getsource(update_module.validate)
    for token in ("handler_binding", "unbound_effects", "HandlerBinding"):
        assert token not in validate_source, token
    report_source = inspect.getsource(update_module.report_bindings)
    for token in ("problems", "return 1", "sys.exit", "raise"):
        assert token not in report_source, token
    #: 반환값도 없다 — 판정에 끼어들 수 없다.
    #: 🔴 ``from __future__ import annotations`` 때문에 주석은 **문자열**로
    #: 들어온다 (``'None'``). 객체 ``None`` 과 비교하면 늘 실패한다.
    annotation = inspect.signature(update_module.report_bindings).return_annotation
    assert annotation in (None, "None"), annotation
    returns = [
        node for node in ast.walk(ast.parse(textwrap.dedent(report_source)))
        if isinstance(node, ast.Return) and node.value is not None
    ]
    assert returns == []


@requires_official_db
def test_25_the_status_summary_rows_now_add_up(capsys, repository):
    r"""🔴 **누락된 행을 채웠다.** ``NO_EFFECT`` 684장이 요약에서 사라졌었다.

    3-F-38 이전 라벨 표에는 ``LUA_VERIFIED``·``TEXT_DERIVED``·``UNAVAILABLE``
    셋만 있었고, 출력된 행의 합이 카드 총수와 맞지 않았다
    (12,687 + 756 = 13,443 ≠ 14,127).
    """
    summarise(repository)
    out = capsys.readouterr().out
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards()
    )
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CARD_TOTAL
    #: 네 라벨이 모두 출력에 있다
    assert "Lua 검증됨" in out and "텍스트 유래" in out
    assert "효과 없음" in out and "분석 근거 없음" in out
    #: 실제로 존재하는 세 상태의 건수가 전부 찍혔다
    for value in STATUS_COUNTS.values():
        assert f"{value:,}장" in out
    #: 🟢 표에 없는 상태가 생기면 드러난다 — 지금은 없다
    assert "표에 없는 분석 상태" not in out


def test_26_the_status_label_table_covers_every_enum_value():
    r"""🟢 라벨 표가 ``AnalysisStatus`` 를 전부 덮는가 — 빠진 값을 센다.

    ``UNKNOWN`` 은 "아직 아무것도 모른다" 의 기본값이고 실측 0장이다.
    표에 없는 상태가 실제로 나타나면 ``summarise`` 가 그 사실을 출력한다
    (``test_25`` 가 그 줄의 부재를 확인한다).
    """
    source = inspect.getsource(update_module.summarise)
    for member in ("LUA_VERIFIED", "TEXT_DERIVED", "NO_EFFECT", "UNAVAILABLE"):
        assert f"AnalysisStatus.{member}.value" in source, member
    assert "표에 없는 분석 상태" in source
    #: 열거되지 않은 값은 ``UNKNOWN`` 하나뿐이다
    listed = {"lua_verified", "text_derived", "no_effect", "unavailable"}
    assert {s.value for s in AnalysisStatus} - listed == {"unknown"}


# ===========================================================================
# E. §8 — 산출물·검색 불변성
# ===========================================================================
@requires_official_db
def test_27_corpus_binding_distribution_is_unchanged(repository):
    r"""🟢 §6 ⑫ — 정상 코퍼스는 전부 증명된 상태 그대로다."""
    analyzer = EffectAnalyzer(repository)
    cards = [c for c in repository.all_cards() if c.script is not None]
    assert len(cards) == ATTACHED_CARDS
    blocks = 0
    unbound = 0
    for card in cards:
        analysis = analyzer.analyze(card)
        assert analysis.handler_binding is HandlerBinding.MATCHED, card.id
        unbound += len(analysis.unbound_effects)
        counts = _block_counts(analysis)
        assert set(counts) <= {HandlerBinding.MATCHED}, card.id
        blocks += sum(counts.values())
    assert blocks == ATTACHED_BLOCKS
    assert unbound == 0


@requires_official_db
def test_28_analysis_totals_match_the_baseline(repository):
    r"""🟢 §8 — 등록·해결 효과 수와 다섯 집계가 3-F-37 기준 그대로다."""
    analyzer = EffectAnalyzer(repository)
    totals = dict.fromkeys(ANALYSIS_TOTALS, 0)
    for card in repository.all_cards():
        if card.script is None:
            continue
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


@requires_official_db
def test_29_search_results_and_ranking_are_unchanged(repository):
    r"""🟢 §7 — 검색 계층이 그대로다 (개수로 못 박는다; 지문 리터럴 금지)."""
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


@requires_official_db
def test_30_effect_ref_resolution_is_unchanged(repository):
    r"""🟢 §7 — ``EffectRef(card_id, ordinal)`` 과 append-only ordinal 불변."""
    bad = 0
    total = 0
    for card in repository.all_cards():
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


@requires_official_db
def test_31_a_real_card_reports_matched_through_the_cli(capsys, repository):
    r"""🟢 §6 ⑦ — **실제 카드**가 실제 CLI 를 통과해 결합 상태를 보인다."""
    agent = type("Agent", (), {"repository": repository})()
    args = type("Args", (), {"card_id": ANALYZE_CARD})()
    assert cmd_analyze(agent, args) == 0
    out = capsys.readouterr().out
    assert _BINDING_GUIDANCE_KO[HandlerBinding.MATCHED][0] in out
    assert "전부 증명됨" in out
    assert "🔴" not in out


# ===========================================================================
# F. §7 — 금지 사항과 변경 범위
# ===========================================================================
def test_32_no_new_binding_state_is_invented():
    r"""🔴 §7 금지 — ``HandlerBinding`` 을 임의로 새로 만들지 않았다."""
    assert [b.value for b in HandlerBinding] == [
        "matched", "mismatched", "unprovable", "source_missing",
    ]
    for module in (main_module, update_module):
        source = inspect.getsource(module)
        #: 소비자가 상태를 **만들지** 않는다 — 읽기만 한다
        assert "HandlerBinding." in source
        assert "handler_binding =" not in source, module.__name__


def test_33_no_uncertain_binding_is_promoted_to_normal():
    r"""🔴 §7 금지 — 불확실한 연결을 정상으로 바꾸지 않았다.

    분석기의 결합 자리를 건드리지 않았으므로, 3-F-37 의 판정이 그대로다.
    """
    analyzer_source = inspect.getsource(EffectAnalyzer._analyze_card)
    assert "entries[position]" not in analyzer_source
    assert "source_digest" in analyzer_source
    for kwargs, expected in (
        ({"drop_digest": True}, HandlerBinding.UNPROVABLE),
        ({"delete_file": True}, HandlerBinding.SOURCE_MISSING),
    ):
        _card, _repo, analysis = _analyze(TWO_BLOCKS, TWO_BLOCKS, **kwargs)
        assert analysis.handler_binding is expected
        assert analysis.effects == []
        assert analysis.resolution_effects == []


def test_34_production_change_is_confined_to_three_files():
    r"""🟢 §10 — CLI 출력 · 갱신 요약 · 안내 표. 그 밖은 건드리지 않았다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    production = {p for p in changed if not p.startswith(("tests/", "docs/"))}
    assert production <= {
        "app/main.py",
        "scripts/update_cards.py",
        "analysis/effect_model.py",
    }, production


def test_35_no_forbidden_path_was_touched():
    r"""🟢 §7 — Engine V1 · ``engine/`` · ``agent/`` · 검색 · Lua · README 불변."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert not [p for p in changed if p.endswith(".lua")]
    assert not [p for p in changed if p.endswith("README.md")]
    assert not [p for p in changed
                if p.startswith(("engine/", "agent/", "core/card_search.py"))]
    from engine.effect.library import EFFECT_LIBRARY

    assert len(EFFECT_LIBRARY) == 16
    assert {entry.effect_ref.ordinal for entry in EFFECT_LIBRARY} == {0}


def test_36_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 기존 테스트를 지우지도, skip 을 더하지도 않았다.

    이름 변경을 삭제로 세지 않도록 **파일별 테스트 개수**를 부모 커밋과
    비교한다 (Phase 3-F-37 이 그 함정을 겪었다).
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--reverse", "--grep=^Phase 3-F-38:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    added_skips = 0
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
    assert added_skips == 0

    base = f"{shas[0]}^"
    changed = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--", "tests/"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()

    def count_tests(text: str) -> int:
        return sum(
            1 for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )

    shrunk = []
    for path in changed:
        before = subprocess.run(
            ["git", "show", f"{base}:{path}"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        )
        if before.returncode != 0:
            continue
        after = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout
        if count_tests(after) < count_tests(before.stdout):
            shrunk.append(path)
    assert shrunk == []
