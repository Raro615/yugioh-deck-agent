r"""
Phase 3-F-41 — Provenance 기록 및 텍스트 분석 상태의 소비자 경로 감사.

핵심 질문: 시스템이 기록한 출처·신뢰도 정보가 **실제 사용자에게 전달되며**,
전달되는 표현이 **확보된 근거의 수준을 정확히 반영**하는가.

실측 답:

* **N41 — 요약 표는 맞고, 카드 단위 CLI 가 틀렸다.** 갱신 요약의
  "텍스트 유래 (Lua 없음)" 는 근거의 이름이라 과장이 아니다. 그런데 분석
  CLI 는 Lua 가 없는 **1,440장 전부**에게
  ``"Lua 스크립트가 없습니다 (일반 몬스터 등)."`` 하나를 찍었고, 그 안에
  효과가 분명히 있는 **756장**(``text_derived``)이 섞여 있었다 — 실측 예:
  「패러렐 텔레포트 · 마법/속공」. 게다가 Phase 3-F-40 이 넣은 "분석 근거"
  줄은 이 반환 **뒤**에 있어서 그 1,440장은 근거를 한 번도 못 봤다.
* **N42 — ``describe_ko()`` 는 호출자가 0개이고, 그 자체가 필드를
  빠뜨리고 있었다.** ``DataAvailability`` 의 여섯 칸 중 다섯 칸만 요약해,
  Lua 없는 카드에서 **유일하게 켜지는** ``text_analysis_available`` 이
  요약에 나타나지 않았다.
* **``TextEffectAnalyzer`` 는 production 호출자가 0개다** (AST 전수).
  돌려 보면 756장 중 **753장(99.6%)** 에서 결과가 나오지만, 그것을
  production 에 연결하는 것은 새 분석 경로이고 이번 범위가 아니다.

🔴 이 파일은 문자열 존재 확인으로 의미 검증을 대체하지 않는다. 실제
``cmd_analyze`` · ``summarise`` · ``_record_provenance`` ·
``TextEffectAnalyzer`` 를 돌리고 그 출력과 반환값을 읽는다.
"""

from __future__ import annotations

import ast
import collections
import inspect
import io
import contextlib
import pathlib
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

import app.main as main_module
import core.provenance as provenance_module
import scripts.update_cards as update_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import HandlerBinding
from analysis.text_effect_analyzer import TextAnalysis, TextEffectAnalyzer
from app.main import cmd_analyze
from core import constants as C
from core.card_model import Card, CardSource
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus, CardProvenance, DataAvailability
from engine.ids import EffectRef, effect_refs
from scripts.update_cards import summarise
from sources.lua_loader import parse_lua_source
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-41 이 실측한 기준값 (테스트가 실제로 다시 산출한다) ----------
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}
CARD_TOTAL = 14127
NO_LUA_CARDS = 756 + 684          # 분석 CLI 가 이른 반환하는 카드 수
ATTACHED_CARDS = 12687
ATTACHED_BLOCKS = 34635
#: 텍스트 분석기를 **돌려 보면** 결과가 나오는 카드 (production 에서는 안 돈다)
TEXT_WOULD_YIELD = 753
TEXT_WOULD_BE_EMPTY = 3
#: 실측 사례 — 속공 마법인데 "일반 몬스터 등" 이라고 들었다
TEXT_DERIVED_SAMPLE = 483         # 패러렐 텔레포트 · 마법/속공
NO_EFFECT_SAMPLE = 89631139       # 푸른 눈의 백룡
LUA_SAMPLE = 32807846             # 증원


# ===========================================================================
# 공용 도구
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


class _StubRepo:
    constants = None

    def __init__(self, script_dir, card):
        self.script_dir = script_dir
        self._card = card

    def get(self, card_id):
        return self._card if card_id == self._card.id else None


def _card(*, lua: str | None = TWO_BLOCKS, on_disk: bool = True,
          break_digest: bool = False, shift_one: bool = False,
          kind: str = "spell", desc: str = "덱에서 1장 패에 넣는다.",
          record: bool = True, card_id: int = 1):
    """카드를 만들고 **실제 ``_record_provenance``** 로 출처를 붙인다."""
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
    card.sources.add(CardSource.OFFICIAL_DB)
    if text is not None:
        card.script = parse_lua_source(card_id, name, text)
        if break_digest:
            card.script.source_digest = "0" * 64
        if shift_one:
            offsets = list(card.script.effect_offsets)
            offsets[-1] += 1
            card.script.effect_offsets = offsets
    if record:
        CardRepository._record_provenance({card_id: card})
    return card, directory


def _run_cli(capsys, **kwargs) -> str:
    card, directory = _card(**kwargs)
    repo = _StubRepo(directory, card)
    agent = type("Agent", (), {"repository": repo})()
    args = type("Args", (), {"card_id": card.id})()
    assert cmd_analyze(agent, args) == 0
    return capsys.readouterr().out


def _real_cli(repository, card_id: int) -> str:
    agent = type("Agent", (), {"repository": repository})()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert cmd_analyze(agent, type("A", (), {"card_id": card_id})()) == 0
    return buffer.getvalue()


def _production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if set(path.relative_to(PROJECT_ROOT).parts) & {
                "tests", "__pycache__", ".git"}:
            continue
        yield path


def _changed_files() -> set[str]:
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "--grep=^Phase 3-F-41:"],
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
# A. §2 — 텍스트 분석기는 언제 실행되는가
# ===========================================================================
def test_01_the_text_analyzer_is_never_called_in_production():
    r"""🔴 §2 ① — production 호출자가 **0개**다 (AST 전수).

    import 도, 이름 참조도, 속성 접근도 없다. ``analysis/__init__`` 가
    내보내지도 않는다.
    """
    names = {"TextEffectAnalyzer", "TextAnalysis", "TextDerivedEffect"}
    hits: list[str] = []
    for path in _production_files():
        if path.name == "text_effect_analyzer.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module
                    and "text_effect_analyzer" in node.module):
                hits.append(f"{path.name}:import")
            elif isinstance(node, ast.Name) and node.id in names:
                hits.append(f"{path.name}:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in names:
                hits.append(f"{path.name}:{node.attr}")
    assert hits == [], hits
    init = (PROJECT_ROOT / "analysis" / "__init__.py").read_text(encoding="utf-8")
    assert "TextEffectAnalyzer" not in init


def test_02_only_one_test_calls_it_and_that_is_the_whole_story():
    r"""🟢 §2 ① — 호출자는 **테스트뿐**이다. CLI·갱신 경로와 구분한다.

    .. note:: 🟢 **Phase 3-F-42 에서 목록이 하나 늘었다.** 이 assertion 은
       "production 은 부르지 않고 테스트만 부른다" 를 지키는 **의도적
       지뢰선**이라서, 호출자가 생기면 반드시 누군가 알아차리게 되어 있다.
       3-F-42 가 텍스트 분석기를 실제로 돌려 상태 여섯 개를 구성하는 감사
       파일을 추가했고, 그것이 세 번째 호출자다. **production 호출자는
       여전히 0개**이며 그 사실은 ``test_01`` 이 따로 지킨다. 목록을 느슨한
       조건("tests/ 아래면 통과")으로 바꾸지 않고 **정확한 집합을 유지**해
       지뢰선을 그대로 둔다.
    """
    #: 🔴 문자열 검색으로는 **"실제 호출" 과 "스캔용 리터럴" 을 가를 수
    #: 없다.** 이 파일과 3-F-40 의 감사 파일은 둘 다 ``"TextEffectAnalyzer("``
    #: 라는 **문자열**을 자기 검사에 쓴다 — 그것은 호출이 아니다. AST 로
    #: 실제 ``Call`` 노드만 센다.
    callers = []
    for path in sorted((PROJECT_ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "TextEffectAnalyzer"):
                callers.append(path.name)
    assert sorted(set(callers)) == [
        "test_provenance_consumer_audit.py",
        "test_text_analysis_consumer_policy_audit.py",   # Phase 3-F-42
        "test_update_pipeline.py",
    ], callers


@requires_official_db
def test_03_running_it_would_yield_results_for_almost_every_card(repository):
    r"""🔴 §2 ① — **돌지 않는다는 사실이 "쓸모 없다" 는 뜻이 아니다.**

    756장에 돌려 보면 753장(99.6%)에서 행동이 나온다. 그래도 production 에
    연결하지 않았다 — 새 분석 경로이고 §5 가 금지한 "소비자가 없다는 이유로
    소비자를 추가" 에 해당한다. 수치만 기록한다.
    """
    analyzer = TextEffectAnalyzer()
    yielded = empty = 0
    for card in repository.all_cards():
        if card.provenance.analysis_status is not AnalysisStatus.TEXT_DERIVED:
            continue
        result = analyzer.analyze(card)
        if result.is_empty:
            empty += 1
        else:
            yielded += 1
    assert yielded == TEXT_WOULD_YIELD
    assert empty == TEXT_WOULD_BE_EMPTY
    assert yielded + empty == STATUS_COUNTS["text_derived"]


def test_04_the_model_separates_not_attempted_from_no_result():
    r"""🔴 §2 ⑥ — ``TextAnalysis`` 는 "시도하지 않음" 과 "결과 없음" 을
    **모델 수준에서 구분한다** (``skipped_reason`` vs ``is_empty``)."""
    analyzer = TextEffectAnalyzer()
    normal = Card(id=1, name="통상", desc="전설적인 드래곤.")
    normal.type_mask = C.TYPE_MONSTER | C.TYPE_NORMAL
    skipped = analyzer.analyze(normal)
    assert skipped.skipped_reason is not None
    assert skipped.has_text is True
    assert skipped.is_empty is True            # 결과는 없다
    blank = Card(id=2, name="빈 텍스트", desc="")
    blank.type_mask = C.TYPE_SPELL
    nothing = analyzer.analyze(blank)
    assert nothing.has_text is False
    assert nothing.skipped_reason is None      # 시도하지 않은 것이 아니다
    assert nothing.is_empty is True
    #: 🔴 두 경우가 ``is_empty`` 로는 **같아 보인다** — 구분은 다른 두 칸이 한다
    assert skipped.is_empty == nothing.is_empty


@requires_official_db
def test_05_that_distinction_is_unreachable_for_the_real_population(repository):
    r"""🔴 §2 ⑥ — 그런데 ``TEXT_DERIVED`` 756장에서는 ``skipped_reason`` 이
    **한 번도 생기지 않는다**.

    그 상태의 조건(``has_printed_effect`` 가 참이고 ``desc`` 가 있다)과
    ``_is_flavor_text_only`` 의 조건이 서로 배타적이기 때문이다. 즉 모델의
    구분이 이 집단에는 적용될 자리가 없다.
    """
    analyzer = TextEffectAnalyzer()
    skipped = 0
    for card in repository.all_cards():
        if card.provenance.analysis_status is not AnalysisStatus.TEXT_DERIVED:
            continue
        if analyzer.analyze(card).skipped_reason is not None:
            skipped += 1
    assert skipped == 0


# ===========================================================================
# B. §2 ③④⑤⑦⑧ — 사용자 출력이 근거 수준을 반영하는가
# ===========================================================================
@requires_official_db
def test_06_a_text_derived_card_is_no_longer_called_a_normal_monster(repository):
    r"""🔴 §2 ③⑦ — **N41 의 실체.** 속공 마법에게 "일반 몬스터 등" 이라고
    말하고 있었다.

    「패러렐 텔레포트 · 마법/속공」은 ``has_printed_effect`` 가 참이고
    ``text_derived`` 다. 통상 몬스터가 아니다.
    """
    card = repository.get(TEXT_DERIVED_SAMPLE)
    assert card is not None
    assert card.script is None and card.has_printed_effect is True
    assert card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    out = _real_cli(repository, TEXT_DERIVED_SAMPLE)
    assert "일반 몬스터" not in out
    assert "Lua 스크립트가 없습니다" in out
    assert "스크립트가 아직 없습니다" in out


@requires_official_db
def test_07_the_basis_line_now_reaches_the_cards_that_need_it(repository):
    r"""🔴 §2 ⑧ — Lua 가 없는 카드도 **근거를 본다**.

    Phase 3-F-40 이 넣은 줄은 ``has_script`` 이른 반환 **뒤**에 있어서
    1,440장에게 한 번도 보이지 않았다. 이 Phase 가 위로 올렸다.
    """
    for card_id, expected in ((TEXT_DERIVED_SAMPLE, "text_derived"),
                              (NO_EFFECT_SAMPLE, "no_effect"),
                              (LUA_SAMPLE, "lua_verified")):
        out = _real_cli(repository, card_id)
        assert "분석 근거" in out, card_id
        assert expected in out, card_id


@requires_official_db
def test_08_the_two_no_lua_statuses_get_different_reasons(repository):
    r"""🔴 §2 ⑦ — ``NO_EFFECT`` 와 ``TEXT_DERIVED`` 가 **다른 문장**을 받는다.

    예전에는 1,440장이 같은 한 문장을 받았다.
    """
    text_out = _real_cli(repository, TEXT_DERIVED_SAMPLE)
    none_out = _real_cli(repository, NO_EFFECT_SAMPLE)
    assert "효과가 있는 카드인데" in text_out
    assert "효과 없는 카드로 분류합니다" in none_out
    #: 두 문장이 실제로 다르다
    text_reason = text_out.split("Lua 스크립트가 없습니다 — ")[1].splitlines()[0]
    none_reason = none_out.split("Lua 스크립트가 없습니다 — ")[1].splitlines()[0]
    assert text_reason != none_reason


@requires_official_db
def test_09_the_cli_does_not_claim_a_text_analysis_ran(repository):
    r"""🔴 §5 금지 — 돌지 않은 분석을 돌았다고 말하지 않는다.

    ``TextEffectAnalyzer`` 가 production 에서 호출되지 않으므로 (``test_01``),
    문구는 "텍스트만이 근거" 이고 "텍스트에서 분석했다" 가 아니다.
    """
    out = _real_cli(repository, TEXT_DERIVED_SAMPLE)
    assert "구조화된 텍스트 분석은 돌지 않습니다" in out
    for claim in ("텍스트에서 분석했", "텍스트 분석 완료", "분석했습니다"):
        assert claim not in out, claim


def test_10_an_unknown_status_gets_an_honest_fallback(capsys):
    r"""🔴 §5 금지 — 상태를 모르면 **이유를 지어내지 않는다**.

    라벨 표에 없는 상태(``UNKNOWN``)에서는 "판단할 수 없습니다" 로 적는다.
    """
    card, directory = _card(lua=None, record=True)
    card.provenance.analysis_status = AnalysisStatus.UNKNOWN
    agent = type("Agent", (), {"repository": _StubRepo(directory, card)})()
    assert cmd_analyze(agent, type("A", (), {"card_id": card.id})()) == 0
    out = capsys.readouterr().out
    assert "판단할 수 없습니다" in out
    assert "일반 몬스터" not in out


def test_11_a_card_without_provenance_still_prints_no_invented_reason(capsys):
    r"""🟢 §6 ⑯ — provenance 가 아예 없으면 근거 줄을 생략하고, 이유도
    지어내지 않는다."""
    card, directory = _card(lua=None, record=False)
    assert card.provenance is None
    agent = type("Agent", (), {"repository": _StubRepo(directory, card)})()
    assert cmd_analyze(agent, type("A", (), {"card_id": card.id})()) == 0
    out = capsys.readouterr().out
    #: 🔴 ``"분석 근거"`` 를 그냥 찾으면 안 된다 — fallback 문장
    #: ("이 카드의 분석 근거를 판단할 수 없습니다") 안에도 그 낱말이 있다.
    #: 없어야 하는 것은 **근거 줄**(``  분석 근거  : <상태>``)이다.
    assert re.search(r"^\s*분석 근거\s*:", out, re.M) is None, out
    assert "판단할 수 없습니다" in out
    assert "일반 몬스터" not in out


def test_12_text_derived_is_never_shown_as_lua_or_verified(capsys):
    r"""🔴 §2 ④ — 텍스트 상태가 Lua 분석·검증 완료처럼 보이지 않는다."""
    out = _run_cli(capsys, lua=None)
    assert "text_derived" in out
    for claim in ("lua_verified", "검증됨", "결합 상태", "구조화 정도"):
        assert claim not in out, claim


# ===========================================================================
# C. §2 ⑤ — 카드 일부만 텍스트 분석된 경우
# ===========================================================================
@requires_official_db
def test_13_a_card_can_never_be_both_lua_and_text_based(repository):
    r"""🔴 §2 ⑤ — "일부 효과만 텍스트 분석" 은 **발생할 수 없다**.

    ``TEXT_DERIVED`` 는 ``card.script is None`` 일 때만 붙으므로 Lua 와
    배타적이다. 전수로 확인한다 — 그래서 카드 전체 상태와 효과별 상태를
    구분할 필요가 아직 없다 (필요가 생기면 그때 설계할 일이다).
    """
    overlap = [
        card.id for card in repository.all_cards()
        if card.script is not None
        and card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    ]
    assert overlap == []
    text_cards = [
        card for card in repository.all_cards()
        if card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    ]
    assert len(text_cards) == STATUS_COUNTS["text_derived"]
    assert all(card.script is None for card in text_cards)


@requires_official_db
def test_14_a_zero_effect_lua_card_still_reports_its_basis(repository):
    r"""🟢 §4 ⑦ — 등록 효과가 0개인 Lua 카드도 근거와 증명을 **둘 다** 본다.

    Phase 3-F-40 이 센 183장 중 한 장으로 확인한다.
    """
    card = repository.get(1641882)                  # 퓨저니스트
    assert card is not None and card.script is not None
    assert list(card.script.effects) == []
    out = _real_cli(repository, 1641882)
    assert "분석 근거" in out and "lua_verified" in out
    assert "Lua 스크립트가 없습니다" not in out


def test_15_an_unbound_block_card_reports_basis_and_failed_proof(capsys):
    r"""🔴 §4 ②⑥ — 미인식 블록이 있는 카드에서 근거와 증명이 **함께** 보인다."""
    out = _run_cli(capsys, break_digest=True)
    assert "분석 근거" in out and "lua_verified" in out
    assert "🔴 결합 상태" in out
    assert out.index("분석 근거") < out.index("결합 상태")


def test_16_matched_binding_is_not_shown_as_semantic_verification(capsys):
    r"""🔴 §5 금지 — ``MATCHED`` 를 의미적 검증 완료로 취급하지 않는다."""
    out = _run_cli(capsys)
    assert "정상 연결" in out
    for claim in ("검증 완료", "의미 검증", "검증됨"):
        assert claim not in out, claim


# ===========================================================================
# D. §3 — CardProvenance 의 생성·전달·소비
# ===========================================================================
def test_17_provenance_is_created_with_fields_and_availability():
    r"""🟢 §3 ③ — 기록은 카드마다 **실제로 만들어진다**."""
    card, _dir = _card()
    record = card.provenance
    assert isinstance(record, CardProvenance)
    assert isinstance(record.availability, DataAvailability)
    assert record.card_id == card.id
    assert set(record.fields) >= {"basic_info", "card_name", "effect_analysis"}
    assert record.source_of("effect_analysis").value == "lua"


def test_18_describe_ko_has_no_production_caller():
    r"""🔴 §3 ①② — ``CardProvenance.describe_ko()`` 는 호출자가 **0개**다.

    유일한 ``describe_ko`` 호출은 ``provenance.py`` 안에서 자기
    ``availability`` 를 부르는 한 줄이다. 밖에서 부르는 곳이 없다.
    """
    external: list[str] = []
    internal = 0
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "describe_ko"):
                continue
            owner = ast.unparse(node.func.value)
            if "provenance" in owner or "availability" in owner:
                if path.name == "provenance.py":
                    internal += 1
                else:
                    external.append(f"{path.name}: {owner}")
    assert external == [], external
    assert internal == 1


def test_19_missing_has_no_caller_at_all():
    r"""🔴 §3 ①② — ``DataAvailability.missing()`` 은 production 에도
    테스트에도 호출자가 없다 (이 파일이 처음 부른다)."""
    callers: list[str] = []
    for path in list(_production_files()) + sorted(
            (PROJECT_ROOT / "tests").rglob("*.py")):
        if path.name == "test_provenance_consumer_audit.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "missing"):
                callers.append(path.name)
    assert callers == [], callers


def test_20_the_availability_summary_covers_all_six_fields():
    r"""🔴 §3 ⑦ — **여섯 칸 중 다섯 칸만 요약하고 있었다** (N42 의 실체).

    ``text_analysis_available`` 이 ``missing()`` 과 ``describe_ko()`` 양쪽에서
    빠져 있었다. Lua 가 없는 카드에서 유일하게 켜지는 플래그가 바로 그것이다.
    """
    fields = {f for f in DataAvailability.__dataclass_fields__}
    assert len(fields) == 6
    everything = DataAvailability(**{name: True for name in fields})
    assert everything.missing() == []
    nothing = DataAvailability()
    assert len(nothing.missing()) == 6
    assert "text_analysis" in nothing.missing()
    #: 요약 문구에도 여섯 칸이 모두 나온다
    marks = everything.describe_ko()
    assert marks.count("✓") == 6
    assert "텍스트근거" in marks


def test_21_a_text_based_card_shows_its_one_positive_flag():
    r"""🔴 §3 ⑦ — Lua 없는 카드의 요약이 **켜진 칸을 떨어뜨리지 않는다**.

    예전에는 ``✗Lua ✗효과분석`` 만 보이고 "텍스트가 근거다" 는 사라졌다.
    """
    card, _dir = _card(lua=None)
    availability = card.provenance.availability
    assert availability.text_analysis_available is True
    assert availability.effect_analysis_available is False
    marks = availability.describe_ko()
    assert "✓텍스트근거" in marks
    assert "✗효과분석" in marks
    assert "text_analysis" not in availability.missing()


def test_22_the_status_is_still_read_in_exactly_three_places():
    r"""🔴 §3 ④⑤ — ``analysis_status`` 를 읽는 production 자리를 전수로 센다.

    🔴 AST 속성 탐색만으로는 **놓친다** — ``app/main.py`` 는
    ``getattr(record, "analysis_status", None)`` 으로 읽어서 속성 노드가
    아니다. 문자열 인수까지 함께 본다.
    """
    readers: set[str] = set()
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            hit = (isinstance(node, ast.Attribute)
                   and node.attr == "analysis_status")
            if (isinstance(node, ast.Constant)
                    and node.value == "analysis_status"):
                hit = True
            if hit:
                readers.add(str(path.relative_to(PROJECT_ROOT)))
    assert readers == {
        "core/card_repository.py",      # 쓰는 곳
        "core/provenance.py",           # describe_ko (호출자 0개)
        "scripts/update_cards.py",      # 갱신 요약
        "app/main.py",                  # 분석 CLI (getattr)
    }, readers


@requires_official_db
def test_23_the_update_summary_still_carries_the_basis(capsys, repository):
    r"""🟢 §3 ⑥ — 갱신 요약이 상태별 건수를 그대로 전달한다."""
    summarise(repository)
    out = capsys.readouterr().out
    assert "텍스트 유래 (Lua 없음)" in out
    assert f"{STATUS_COUNTS['text_derived']:,}장" in out
    assert "분석 근거만 셉니다" in out
    assert "표에 없는 분석 상태" not in out


def test_24_the_summary_label_names_the_basis_not_a_conclusion():
    r"""🟢 §2 ③ / §5 — 요약 라벨은 **근거의 이름**이라 과장이 아니다.

    "텍스트 유래 (Lua 없음)" 는 "어디서 왔나" 를 말하고 "검증했다" 를 말하지
    않는다. 그래서 이 라벨은 **고치지 않았다** (3-F-40 이 "Lua 검증됨" 을
    고친 것과 다르다 — 그쪽은 검증을 주장했다).
    """
    source = inspect.getsource(update_module.summarise)
    assert '"텍스트 유래 (Lua 없음)"' in source
    for claim in ("텍스트 검증", "텍스트 분석됨", "분석 완료"):
        assert claim not in source, claim


# ===========================================================================
# E. §4 — provenance 가 부분적으로만 있는 경우 · 갱신 후 갱신
# ===========================================================================
def test_25_provenance_survives_a_rebuild_and_follows_the_card():
    r"""🟢 §6 ⑱ — 카드가 Lua 를 얻으면 출처가 **따라 바뀐다**."""
    card, _dir = _card(lua=None)
    assert card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    assert card.provenance.availability.text_analysis_available is True
    text = textwrap.dedent(TWO_BLOCKS)
    card.script = parse_lua_source(card.id, card.name, text)
    CardRepository._record_provenance({card.id: card})
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
    assert card.provenance.availability.lua_available is True
    assert card.provenance.availability.text_analysis_available is False


def test_26_a_partial_record_does_not_crash_the_summary():
    r"""🟢 §6 ⑮ — 플래그가 일부만 켜진 기록도 요약이 돈다."""
    partial = DataAvailability(cdb_available=True, text_analysis_available=True)
    marks = partial.describe_ko()
    assert marks.count("✓") == 2
    assert set(partial.missing()) == {
        "official_text", "korean", "lua", "effect_analysis"}


def test_27_field_conflicts_are_kept_rather_than_overwritten():
    r"""🟢 §3 ③ — 낮은 우선순위 소스가 **충돌로 남는다** (기록은 정확하다)."""
    from core.provenance import SourceKind

    record = CardProvenance(card_id=1)
    record.record("card_name", SourceKind.OFFICIAL_DB)
    record.record("card_name", SourceKind.KOREAN_DB)
    entry = record.fields["card_name"]
    assert entry.source is SourceKind.KOREAN_DB
    assert entry.conflicts == ["official_db"]
    assert record.has_conflict() is True


def test_28_the_full_record_can_still_be_rendered_when_someone_wants_it():
    r"""🟢 §3 ② — 호출자가 없다고 함수가 깨진 것은 아니다. 실제로 돌려 본다.

    그래서 §5 가 말한 "소비자가 없다는 이유만으로 소비자를 추가" 를 하지
    않았다 — 필요한 쪽이 생기면 그때 부르면 된다.
    """
    card, _dir = _card(lua=None)
    text = card.provenance.describe_ko()
    assert f"카드 {card.id}" in text
    assert "효과 분석: text_derived" in text
    assert "✓텍스트근거" in text
    assert "effect_analysis: official_text" in text


# ===========================================================================
# F. §6 ⑲~㉕ — 통합·반복·회귀
# ===========================================================================
@requires_official_db
def test_29_every_status_gets_a_user_visible_basis(repository):
    r"""🔴 §6 ⑳㉕ — **모든 카드**가 근거를 본다. 전수로 다섯 장씩 확인한다."""
    by_status: dict[str, list[int]] = collections.defaultdict(list)
    for card in repository.all_cards():
        by_status[card.provenance.analysis_status.value].append(card.id)
    assert set(by_status) == set(STATUS_COUNTS)
    for status, ids in by_status.items():
        for card_id in ids[:5]:
            out = _real_cli(repository, card_id)
            assert "분석 근거" in out, (status, card_id)
            assert status in out, (status, card_id)
            assert "일반 몬스터 등" not in out, (status, card_id)


def test_30_the_same_card_gives_the_same_output_twice(capsys):
    r"""🟢 §6 ㉑ — 같은 입력을 두 번 돌리면 출력이 같다."""
    first = _run_cli(capsys, lua=None)
    second = _run_cli(capsys, lua=None)
    assert first == second


@requires_official_db
def test_31_existing_cli_callers_still_get_zero_and_the_old_anchors(repository):
    r"""🟢 §6 ㉒ — 기존 호출자 호환: 반환값 0, 기존 문구의 앞부분 유지."""
    out = _real_cli(repository, NO_EFFECT_SAMPLE)
    assert "Lua 스크립트가 없습니다" in out        # 기존 테스트가 잡는 앞부분
    assert "결합 상태" not in out
    assert "=" * 72 in out


@requires_official_db
def test_32_corpus_status_distribution_is_unchanged(repository):
    r"""🔴 §8 — 상태 분포가 그대로다. **표현만 고쳤다**는 증거다."""
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards()
    )
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CARD_TOTAL
    assert STATUS_COUNTS["text_derived"] + STATUS_COUNTS["no_effect"] == NO_LUA_CARDS


@requires_official_db
def test_33_analysis_and_binding_outputs_are_unchanged(repository):
    r"""🟢 §8 — 분석 집계와 결합 분포가 그대로다."""
    analyzer = EffectAnalyzer(repository)
    registered = resolution = unbound = 0
    blocks: collections.Counter = collections.Counter()
    for card in repository.all_cards():
        if card.script is None:
            continue
        analysis = analyzer.analyze(card)
        registered += len(analysis.effects)
        resolution += len(analysis.resolution_effects)
        unbound += len(analysis.unbound_effects)
        for group in (analysis.effects, analysis.resolution_effects,
                      analysis.unbound_effects):
            for effect in group:
                blocks[effect.handler_binding] += 1
    assert (registered, resolution, unbound) == (26352, 8283, 0)
    assert dict(blocks) == {HandlerBinding.MATCHED: ATTACHED_BLOCKS}


@requires_official_db
def test_34_search_and_effect_refs_are_unchanged(repository):
    r"""🟢 §8 — 검색 결과와 ``EffectRef`` 가 그대로다."""
    engine = CardSearchEngine(repository)
    cards = [c for c in repository.all_cards() if c.script is not None]
    categories = sorted({x for c in cards for x in c.script.categories})
    locations = sorted({x for c in cards for x in c.script.locations})
    assert len(categories) == 31 and len(locations) == 31
    assert sum(
        len(engine.search(SearchFilters(effect_categories=(name,))).cards)
        for name in categories
    ) == 19372
    location_total = 0
    for name in locations:
        try:
            location_total += len(engine.search(SearchFilters(
                effect_locations=(EffectLocationFilter(location=name),))).cards)
        except Exception:
            location_total += -1
    assert location_total == 10612
    total = bad = 0
    for card in cards:
        refs = effect_refs(card)
        total += len(refs)
        for ordinal, ref in enumerate(refs):
            if ref != EffectRef(card.id, ordinal):
                bad += 1
    assert (total, bad) == (ATTACHED_BLOCKS, 0)


# ===========================================================================
# G. §7 금지 사항 · §10 범위
# ===========================================================================
def test_35_no_new_enum_or_diagnostic_framework_was_added():
    r"""🔴 §7 금지 — 새 공용 enum·프레임워크 없음, 상태 모델 그대로."""
    assert [s.value for s in AnalysisStatus] == [
        "lua_verified", "text_derived", "no_effect", "unavailable", "unknown",
    ]
    assert [b.value for b in HandlerBinding] == [
        "matched", "mismatched", "unprovable", "source_missing",
    ]
    assert len(DataAvailability.__dataclass_fields__) == 6
    #: 소비자는 상태를 **읽기만** 한다
    for module in (main_module, update_module):
        assert "analysis_status =" not in inspect.getsource(module)


def test_36_the_text_analyzer_was_not_wired_into_production():
    r"""🔴 §5 금지 — "소비자가 없다" 를 이유로 소비자를 만들지 않았다.

    ``test_01`` 이 호출자 0개를 확인하고, 여기서는 **이 Phase 가 그것을
    바꾸지 않았다**는 사실을 diff 로 확인한다.
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-41:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    base = subprocess.run(
        ["git", "rev-parse", f"{shas[-1]}^"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", base, "HEAD", "--",
         "analysis/text_effect_analyzer.py", "analysis/__init__.py",
         "core/card_repository.py"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout
    assert diff.strip() == "", diff[:400]


def test_37_production_change_is_confined_to_two_files():
    r"""🟢 §10 — 분석 CLI 와 출처 요약. 그 밖은 없다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    allowed = {
        "app/main.py",
        "core/provenance.py",
        "tests/test_provenance_consumer_audit.py",
        "docs/phase3f41-provenance-consumer-audit.md",
    }
    assert changed <= allowed, changed - allowed


def test_38_no_forbidden_path_was_touched():
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


def test_39_no_test_was_deleted_and_no_skip_was_added():
    r"""🔴 §6 금지 — 기존 테스트 삭제·skip 추가·수정이 없다.

    이번에는 기존 테스트를 **한 줄도 고치지 않았다** — 바꾼 문구
    ("일반 몬스터 등")를 고정한 테스트가 없었기 때문이다 (작업 전 전수 grep).
    """
    shas = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-41:"],
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
    #: 기존 파일의 내용이 하나도 바뀌지 않았다
    changed = _changed_files()
    touched_existing = {
        p for p in changed
        if p.startswith("tests/") and p in before
    }
    assert touched_existing == set(), touched_existing
    for name in set(after) - set(before):
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for match in re.findall(r"pytest\.skip\([^)]*\)", text):
            assert "commit 이 아직 없다" in match, (name, match)
