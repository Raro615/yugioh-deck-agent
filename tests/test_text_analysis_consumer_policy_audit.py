r"""
Phase 3-F-42 — 텍스트 기반 분석 연결 정책 및 사용자 표시 경계 감사.

Phase 3-F-41 이 남긴 N46·N49·N50 을 실제 호출로 확인한 결과를 고정한다.
**이 Phase 는 production 을 한 줄도 바꾸지 않았다** — 세 항목 모두 "사용자에게
잘못된 정보가 표시되는 재현 사례" 가 나오지 않았기 때문이다 (`test_34`).

측정 요약:

* **N46** — ``TextEffectAnalyzer`` 는 production 호출자가 0개다. AST 뿐 아니라
  **실제 ``cmd_analyze`` 를 세 상태의 카드에 돌려 호출 횟수를 셌다 (0회)**.
  그런데 CLI 는 "구조화된 텍스트 분석은 돌지 않습니다" 라고 **스스로 적고
  있다** (3-F-41). 거짓 표시가 아니라 **설계상 미지원**이다.
* **N49** — 여섯 상태 중 **다섯 개**를 기존 모델이 구별한다
  (``has_text`` · ``skipped_reason`` · ``effect``). 편의 속성 ``is_empty`` 만
  보면 셋이 뭉치지만, 세 칸을 보면 갈린다. **오류 상태만** 담을 칸이 없고,
  그 트리거도 재현되지 않는다 (``None``·빈 입력에서 예외가 나지 않는다).
* **N50** — CLI 는 ``use_korean`` 을 넘기지 않아 **항상 오버레이가 켜지고**,
  끄는 플래그가 **없다**. ON/OFF 가 상태 분포를 바꾸지 않지만 **700/756장의
  ``desc`` 를 바꾼다** — 분석기를 연결한다면 그 차이가 그대로 결과가 된다.
  연결되지 않은 지금은 **표시되는 것이 바뀌지 않는다**.

🔴 문자열이 존재한다는 사실을 실행 증거로 쓰지 않는다. 실제 ``cmd_analyze`` ·
``print_card_detail`` · ``TextEffectAnalyzer`` · ``CardRepository.build`` 를
돌리고 그 반환값과 출력을 읽는다.
"""

from __future__ import annotations

import ast
import collections
import contextlib
import inspect
import io
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

import app.main as main_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import HandlerBinding
from analysis.text_effect_analyzer import TextAnalysis, TextEffectAnalyzer
from app.main import DeckAgent, cmd_analyze, print_card_detail
from core import constants as C
from core.card_model import Card
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, effect_refs
from engine.randomness import RandomSource
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-42 가 실측한 기준값 (테스트가 실제로 다시 산출한다) ----------
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}
CARD_TOTAL = 14127
ATTACHED_BLOCKS = 34635
#: 한국어 오버레이 ON/OFF 로 ``desc`` 가 달라지는 TEXT_DERIVED 카드
DESC_DIFFERS_WITH_OVERLAY = 700
#: 분석기를 **돌려 보면** 결과가 나오는 카드 (오버레이 ON / OFF)
WOULD_YIELD_KO_ON = 753
WOULD_YIELD_KO_OFF = 748
#: ``desc`` 가 빈 실제 카드 — 전부 Lua 가 있어 ``UNAVAILABLE`` 에 닿지 않는다
EMPTY_DESC_CARDS = 6

LUA_CARD = 32807846          # 증원
TEXT_CARD = 483              # 패러렐 텔레포트 · 마법/속공
NORMAL_CARD = 89631139       # 푸른 눈의 백룡

PRODUCTION_DIRS = (
    "analysis", "app", "core", "engine", "rules", "rulings", "scripts",
    "sources", "agent",
)


# ===========================================================================
# 공용 도구
# ===========================================================================
def _spell(desc: str, card_id: int = 1) -> Card:
    card = Card(id=card_id, name="x", desc=desc)
    card.type_mask = C.TYPE_SPELL
    return card


def _normal_monster(desc: str, card_id: int = 2) -> Card:
    card = Card(id=card_id, name="x", desc=desc)
    card.type_mask = C.TYPE_MONSTER | C.TYPE_NORMAL
    return card


def _real_cli(repository, card_id: int) -> str:
    agent = type("Agent", (), {"repository": repository})()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert cmd_analyze(agent, type("A", (), {"card_id": card_id})()) == 0
    return buffer.getvalue()


def _production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        parts = path.relative_to(PROJECT_ROOT).parts
        if set(parts) & {"tests", "__pycache__", ".git"}:
            continue
        yield path


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-42:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()


def _changed_files() -> set[str]:
    files: set[str] = set()
    for sha in _phase_shas():
        out = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout
        files.update(x for x in out.split("\n") if x.strip())
    return files


def _new_engine_state() -> GameState:
    game = GameState.create(decks=(range(1000, 1020), range(2000, 2020)))
    game.draw(0, 5)
    game.draw(1, 5)
    game.move(game.player(0).hand[0], Zone.MZONE,
              position=Position.FACEUP_ATTACK)
    game.turn.set_phase(Phase.MAIN1)
    return game


# ===========================================================================
# A. §2 A/B — Lua 존재·부재 경로와 호출 여부
# ===========================================================================
@requires_official_db
def test_01_a_lua_card_shows_basis_and_proof(repository):
    r"""🟢 §2 A — Lua 가 있는 카드는 근거와 증명을 **둘 다** 보여준다."""
    out = _real_cli(repository, LUA_CARD)
    assert "분석 근거" in out and "lua_verified" in out
    assert "결합 상태" in out and "정상 연결" in out
    assert "구조화 정도" in out
    assert out.index("분석 근거") < out.index("결합 상태")


@requires_official_db
def test_02_a_text_card_shows_basis_and_a_reason_but_no_proof(repository):
    r"""🟢 §2 B — Lua 가 없는 카드는 근거와 **이유**를 보여주고, 결합·구조화
    줄은 나오지 않는다 (없는 것을 있다고 하지 않는다)."""
    out = _real_cli(repository, TEXT_CARD)
    assert "분석 근거" in out and "text_derived" in out
    assert "스크립트가 아직 없습니다" in out
    assert "결합 상태" not in out
    assert "구조화 정도" not in out


@requires_official_db
def test_03_cmd_analyze_never_calls_the_text_analyzer(monkeypatch, repository):
    r"""🔴 §2 B / N46 — **실행으로** 확인한다. 세 상태의 카드에 실제
    ``cmd_analyze`` 를 돌리고 분석기 호출 횟수를 센다 — **0회**.

    AST 로 "호출 코드가 없다" 를 보는 것과, 돌려서 "불리지 않는다" 를 보는
    것은 다른 증거다. 둘 다 둔다.
    """
    calls: list[int | None] = []
    original = TextEffectAnalyzer.analyze

    def traced(self, card):
        calls.append(getattr(card, "id", None))
        return original(self, card)

    monkeypatch.setattr(TextEffectAnalyzer, "analyze", traced)
    for card_id in (LUA_CARD, TEXT_CARD, NORMAL_CARD):
        _real_cli(repository, card_id)
    assert calls == []


def test_04_no_production_file_calls_the_text_analyzer():
    r"""🔴 §2 B / N46 — AST 로도 production 호출자가 **0개**다."""
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
    assert hits == [], hits


@requires_official_db
def test_05_the_cli_says_out_loud_that_no_text_analysis_runs(repository):
    r"""🔴 N46 — 돌지 않는다는 사실을 **CLI 가 스스로 적는다**.

    그래서 N46 은 거짓 표시가 아니라 설계상 미지원이다.
    """
    out = _real_cli(repository, TEXT_CARD)
    assert "구조화된 텍스트 분석은 돌지 않습니다" in out


# ===========================================================================
# B. §3 — 여섯 상태를 기존 모델로 구별할 수 있는가
# ===========================================================================
def test_06_state_not_attempted_has_no_analysis_object_at_all():
    r"""🟢 §3 ① — "시도하지 않음" 은 ``TextAnalysis`` 가 **없는 것**으로
    나타난다. 모델 안의 값이 아니다 — 그래서 혼동할 값도 없다."""
    assert "card_id" in TextAnalysis.__dataclass_fields__
    #: 호출하지 않으면 객체가 생기지 않는다 — production 이 그 상태다
    assert TextAnalysis.__dataclass_fields__.keys() == {
        "card_id", "effect", "has_text", "skipped_reason"}


def test_07_state_attempted_but_no_result():
    r"""🟢 §3 ② — 시도했고 텍스트도 있는데 읽어낸 행동이 없다."""
    result = TextEffectAnalyzer().analyze(
        _spell("이 카드는 특별한 규칙이 적용된다."))
    assert result.has_text is True
    assert result.skipped_reason is None
    assert result.effect is not None
    assert result.effect.actions == []
    assert result.is_empty is True


def test_08_state_result_produced():
    r"""🟢 §3 ③ — 결과가 나온다."""
    result = TextEffectAnalyzer().analyze(_spell("덱에서 1장 드로우한다."))
    assert result.has_text is True
    assert result.skipped_reason is None
    assert result.effect is not None and result.effect.actions
    assert result.is_empty is False


def test_09_state_no_text_to_analyse():
    r"""🟢 §3 ④ — 분석할 텍스트가 없다."""
    result = TextEffectAnalyzer().analyze(_spell(""))
    assert result.has_text is False
    assert result.effect is None
    assert result.skipped_reason is None


def test_10_state_attempted_but_skipped_on_purpose():
    r"""🟢 §3 — 시도했으나 **일부러 건너뛰었다** (설정 문구).

    이것은 ②(결과 없음)와 다른 상태다. 섞으면 "없는 효과를 만들어내지
    않기 위해 건너뛴 것" 이 "읽었는데 없었다" 로 보고된다.
    """
    result = TextEffectAnalyzer().analyze(_normal_monster("전설적인 드래곤."))
    assert result.has_text is True
    assert result.skipped_reason is not None
    assert result.effect is None
    assert result.is_empty is True


def test_11_is_empty_alone_conflates_three_states():
    r"""🔴 §3 — **편의 속성 하나로는 셋이 뭉친다.** 세 칸을 봐야 갈린다.

    이것이 N49 의 실체다 — 정보가 없는 것이 아니라, 한 속성만 보면 사라진다.
    """
    analyzer = TextEffectAnalyzer()
    empty = analyzer.analyze(_spell("이 카드는 특별한 규칙이 적용된다."))
    no_text = analyzer.analyze(_spell(""))
    skipped = analyzer.analyze(_normal_monster("전설적인 드래곤."))
    assert empty.is_empty is no_text.is_empty is skipped.is_empty is True
    #: 세 칸을 보면 세 상태가 전부 다르다
    signatures = {
        (r.has_text, r.skipped_reason is not None, r.effect is not None)
        for r in (empty, no_text, skipped)
    }
    assert len(signatures) == 3, signatures


def test_12_an_analysis_error_has_no_place_to_be_recorded():
    r"""🔴 §3 ⑤ — 오류 상태는 **표현할 칸이 없다**. 전용 필드도, ``try`` 도
    없다. 다만 그 트리거도 재현되지 않는다 — ``None`` 과 빈 입력에서 예외가
    나지 않는다. 그래서 "쓰이지 않는 추상적 개선" 을 하지 않았다."""
    fields = set(TextAnalysis.__dataclass_fields__)
    assert not any("error" in f or "fail" in f for f in fields)
    source = inspect.getsource(TextEffectAnalyzer.analyze)
    assert "except" not in source
    analyzer = TextEffectAnalyzer()
    #: 예외가 아니라 빈 분석이 돌아온다
    assert analyzer.analyze(None).card_id == 0
    blank = _spell("")
    blank.desc_en = ""
    assert analyzer.analyze(blank).has_text is False


def test_13_producing_a_result_is_not_a_verification_claim():
    r"""🔴 §4 — 결과가 나왔다는 것이 **의미가 검증됐다**는 뜻이 아니다.

    모델에 검증을 뜻하는 칸이 아예 없다 — 그래서 그렇게 주장할 수단도 없다.
    """
    result = TextEffectAnalyzer().analyze(_spell("덱에서 1장 드로우한다."))
    assert result.is_empty is False
    fields = set(TextAnalysis.__dataclass_fields__)
    assert not any(
        token in f for f in fields for token in ("verified", "confirmed", "valid")
    )
    #: ``AnalysisStatus`` 쪽도 승격되지 않는다
    assert AnalysisStatus.TEXT_DERIVED is not AnalysisStatus.LUA_VERIFIED


# ===========================================================================
# C. §2 D / N50 — 한국어 오버레이
# ===========================================================================
def test_14_the_cli_never_passes_use_korean_and_the_default_is_true():
    r"""🔴 §2 D — CLI 는 ``use_korean`` 을 넘기지 않는다 → 기본 ``True``."""
    assert "use_korean" not in inspect.getsource(DeckAgent.build)
    assert inspect.signature(
        CardRepository.build).parameters["use_korean"].default is True


def test_15_the_cli_has_no_flag_to_turn_the_overlay_off():
    r"""🔴 §2 D — 오버레이를 끄는 CLI 플래그가 **없다**.

    그래서 N50 의 분기는 **CLI 사용자가 만들 수 없다** — 프로그램으로 직접
    ``use_korean=False`` 를 넘기는 호출자(지문 측정 스크립트 등)만 닿는다.
    """
    tree = ast.parse(inspect.getsource(main_module))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    flags.add(arg.value)
    assert not any("korean" in f for f in flags), flags
    assert {"--db", "--scripts", "--limit", "--no-cache"} <= flags


@requires_official_db
def test_16_the_overlay_does_not_change_the_status_distribution():
    r"""🔴 §2 D / N50 — 오버레이 ON/OFF 가 **상태 분포를 바꾸지 않는다**.

    ``TEXT_DERIVED`` 의 조건은 ``card.desc`` 가 비어 있지 않은 것이고, 원문
    텍스트가 있으므로 오버레이가 없어도 그 조건이 유지된다.
    """
    on = collections.Counter(
        c.provenance.analysis_status.value
        for c in CardRepository.build().all_cards()
    )
    off = collections.Counter(
        c.provenance.analysis_status.value
        for c in CardRepository.build(use_korean=False).all_cards()
    )
    assert dict(on) == dict(off) == STATUS_COUNTS


@requires_official_db
def test_17_the_overlay_does_change_the_analyser_input_for_700_cards():
    r"""🔴 §2 D / N50 — 그런데 **입력 텍스트는 700장에서 달라진다**.

    분석기를 연결한다면 그 차이가 그대로 결과가 된다. 지금은 연결되지
    않았으므로 표시되는 것이 달라지지 않는다 (`test_19`).
    """
    on_repo = CardRepository.build()
    off_repo = CardRepository.build(use_korean=False)
    differ = 0
    for card in on_repo.all_cards():
        if card.provenance.analysis_status is not AnalysisStatus.TEXT_DERIVED:
            continue
        other = off_repo.get(card.id)
        if other is not None and card.desc != other.desc:
            differ += 1
    assert differ == DESC_DIFFERS_WITH_OVERLAY


@requires_official_db
def test_18_that_input_difference_would_change_the_result_count():
    r"""🔴 N50 — 분석기를 돌려 보면 **753 / 748** 로 갈린다.

    두 수를 같은 측정이라고 말하지 않기 위해 둘 다 여기 고정한다.
    """
    analyzer = TextEffectAnalyzer()
    results = {}
    for label, kwargs in (("on", {}), ("off", {"use_korean": False})):
        repo = CardRepository.build(**kwargs)
        yielded = 0
        for card in repo.all_cards():
            if card.provenance.analysis_status is not AnalysisStatus.TEXT_DERIVED:
                continue
            if not analyzer.analyze(card).is_empty:
                yielded += 1
        results[label] = yielded
    assert results == {"on": WOULD_YIELD_KO_ON, "off": WOULD_YIELD_KO_OFF}
    assert results["on"] != results["off"]


@requires_official_db
def test_19_what_the_user_sees_does_not_depend_on_the_overlay():
    r"""🟢 N50 — 분석 CLI 출력에서 오버레이에 따라 달라지는 것은 **없다**.

    카드 이름은 오버레이가 바꾸지만, 근거·이유 줄은 같다.
    """
    on_out = _real_cli(CardRepository.build(), TEXT_CARD)
    off_out = _real_cli(CardRepository.build(use_korean=False), TEXT_CARD)
    for marker in ("분석 근거", "text_derived", "스크립트가 아직 없습니다",
                   "구조화된 텍스트 분석은 돌지 않습니다"):
        assert marker in on_out and marker in off_out, marker


# ===========================================================================
# D. §4 — 사용자 표시 정책
# ===========================================================================
@requires_official_db
def test_20_the_analyze_screen_never_shows_the_raw_card_text(repository):
    r"""🟢 §4 — 분석 화면은 **원문을 보여주지 않는다**. 그래서 "분석 결과"
    와 "원문" 이 섞일 자리가 없다."""
    card = repository.get(TEXT_CARD)
    out = _real_cli(repository, TEXT_CARD)
    assert card.desc[:20] not in out
    assert card.summary_ko() in out


@requires_official_db
def test_21_the_card_detail_screen_labels_the_text_language(repository):
    r"""🟢 §4 — 카드 상세는 원문을 보여주고 **언어 라벨**을 붙인다."""
    card = repository.get(TEXT_CARD)
    buffer = io.StringIO()
    agent = type("Agent", (), {"repository": repository})()
    with contextlib.redirect_stdout(buffer):
        print_card_detail(agent, card)
    out = buffer.getvalue()
    assert card.desc[:20] in out
    assert "카드 텍스트(한국어)" in out
    assert "카드 텍스트(원문)" in out          # desc_en 이 따로 있다


def test_22_that_label_is_decided_by_the_name_not_the_text():
    r"""🟠 §4 — **잠재 위험을 재현한다.** 텍스트 라벨이 ``name_ko``(이름)로
    결정된다. 이름만 한국어이고 텍스트는 원문인 카드를 만들면 라벨이
    거짓이 된다.

    ``KoreanTextSource.apply`` 가 이름과 텍스트를 **서로 독립된 조건**으로
    채우므로 구조적으로 가능하다. 실제 데이터에는 없다 (`test_23`).
    그래서 §5 의 "재현 사례가 있어야 고친다" 를 적용해 **고치지 않았다**.
    """
    source = inspect.getsource(print_card_detail)
    assert 'if card.name_ko else' in source
    card = Card(id=1, name="가짜", desc="This is English text.")
    card.name_ko = "가짜"
    card.desc_en = "This is English text."
    card.type_mask = C.TYPE_SPELL
    agent = type("Agent", (), {"repository": type("R", (), {
        "archetype_name": staticmethod(lambda c: [])})()})()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_card_detail(agent, card)
    out = buffer.getvalue()
    #: 🔴 영어 텍스트에 "한국어" 라벨이 붙는다
    assert "카드 텍스트(한국어)" in out
    assert "This is English text." in out


@requires_official_db
def test_23_no_real_card_triggers_that_mislabel(repository):
    r"""🟢 §4 / §5 — 실제 코퍼스에 그 사례가 **0장**이다.

    그래서 재현 사례가 없고, production 을 바꾸지 않았다.
    """
    mislabelled = [
        card.id for card in repository.all_cards()
        if card.desc and card.name_ko and card.desc_en
        and card.desc == card.desc_en
    ]
    assert mislabelled == []


@requires_official_db
def test_24_lua_and_text_bases_never_coexist(repository):
    r"""🔴 §4 — 둘이 동시에 존재할 수 없으므로 **우선순위 규칙이 필요 없다**."""
    overlap = [
        card.id for card in repository.all_cards()
        if card.script is not None
        and card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    ]
    assert overlap == []


@requires_official_db
def test_25_text_derived_is_never_promoted(repository):
    r"""🔴 §0 금지 — 텍스트 상태가 ``LUA_VERIFIED``·``MATCHED`` 로 올라가지
    않는다. 텍스트 카드에는 결합 판정이 아예 적용되지 않는다."""
    analyzer = EffectAnalyzer(repository)
    card = repository.get(TEXT_CARD)
    analysis = analyzer.analyze(card)
    assert card.provenance.analysis_status is AnalysisStatus.TEXT_DERIVED
    assert analysis.has_script is False
    assert analysis.effects == [] and analysis.unbound_effects == []
    #: 블록이 없어 카드 단위 결합은 기본값 ``MATCHED`` 지만 "증명" 이 아니다
    assert analysis.handler_binding is HandlerBinding.MATCHED
    out = _real_cli(repository, TEXT_CARD)
    assert "lua_verified" not in out
    assert "정상 연결" not in out


@requires_official_db
def test_26_unavailable_is_unreachable_and_empty_desc_cards_have_lua(repository):
    r"""🟢 §3 — ``UNAVAILABLE`` 은 실제 코퍼스에서 **0장**이다.

    ``desc`` 가 빈 카드 6장은 전부 Lua 가 있어 ``LUA_VERIFIED`` 가 된다.
    """
    empty_desc = [c for c in repository.all_cards() if not c.desc]
    assert len(empty_desc) == EMPTY_DESC_CARDS
    assert all(c.script is not None for c in empty_desc)
    assert all(c.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED
               for c in empty_desc)
    unavailable = [
        c.id for c in repository.all_cards()
        if c.provenance.analysis_status is AnalysisStatus.UNAVAILABLE
    ]
    assert unavailable == []


# ===========================================================================
# E. §7 — 결정성과 불변 조건
# ===========================================================================
@requires_official_db
def test_27_the_same_card_gives_the_same_output_twice(repository):
    r"""🟢 §6 — 같은 입력을 두 번 돌리면 출력이 같다."""
    assert _real_cli(repository, TEXT_CARD) == _real_cli(repository, TEXT_CARD)
    analyzer = TextEffectAnalyzer()
    card = _spell("덱에서 1장 드로우한다.")
    first = analyzer.analyze(card)
    second = analyzer.analyze(card)
    assert (first.has_text, first.is_empty, first.effect.actions) == (
        second.has_text, second.is_empty, second.effect.actions)


@requires_official_db
def test_28_corpus_status_and_card_counts_are_unchanged(repository):
    r"""🟢 §7 — 카드 수와 상태 분포가 그대로다."""
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards())
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CARD_TOTAL


@requires_official_db
def test_29_analysis_and_binding_totals_are_unchanged(repository):
    r"""🟢 §7 — 효과 블록 수·분석 집계·결합 분포가 그대로다.

    🔴 지문 리터럴(64자 hex)을 테스트에 쓰지 않는다 — 집계로 못 박는다.
    """
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
    assert registered + resolution == ATTACHED_BLOCKS
    assert dict(blocks) == {HandlerBinding.MATCHED: ATTACHED_BLOCKS}


@requires_official_db
def test_30_search_and_effect_refs_are_unchanged(repository):
    r"""🟢 §7 — 검색 카테고리·위치 결과와 ``EffectRef`` 가 그대로다."""
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


def test_31_engine_state_hash_is_deterministic():
    r"""🟢 §7 — 같은 판을 두 번 만들면 ``state_hash`` 가 같다 (Engine V1)."""
    first = _new_engine_state().state_hash()
    second = _new_engine_state().state_hash()
    assert first == second
    assert len(first) == 64


def test_32_the_same_seed_reproduces_the_same_draws():
    r"""🟢 §7 — 같은 seed 는 같은 수열이다 (RNG 재현)."""
    first = RandomSource.seeded(20251011).raw
    second = RandomSource.seeded(20251011).raw
    draws = [first.randrange(100) for _ in range(10)]
    assert draws == [second.randrange(100) for _ in range(10)]
    #: 다른 seed 는 다른 수열이어야 한다 — 같으면 seed 가 먹지 않는 것이다
    other = RandomSource.seeded(20251012).raw
    assert draws != [other.randrange(100) for _ in range(10)]


def test_33_the_hidden_information_boundary_holds():
    r"""🔴 §7 — 상대 시점에서 내 손패가 **식별되지 않는다**.

    ``occupied()`` 가 비어 있지만 ``is_empty`` 는 거짓이다 — "있다는 사실" 과
    "무엇인지" 를 분리해 둔 것이고, 장수도 노출하지 않는다.
    """
    game = _new_engine_state()
    mine = GameStateView.from_state(game, viewer=0)
    theirs = GameStateView.from_state(game, viewer=1)
    assert mine.canonical_state() != theirs.canonical_state()
    my_hand_mine = mine.player(0).hand
    my_hand_theirs = theirs.player(0).hand
    assert len(my_hand_mine.occupied()) == len(game.player(0).hand) == 4
    assert all(c.is_identified for c in my_hand_mine.occupied())
    assert my_hand_theirs.occupied() == ()
    assert my_hand_theirs.is_empty is False


# ===========================================================================
# F. §5 / §9 — 범위와 금지
# ===========================================================================
def test_34_this_phase_changed_no_production_file():
    r"""🔴 §5 — **production 을 한 줄도 바꾸지 않았다.**

    세 항목 모두 "사용자에게 잘못된 정보가 표시되는 재현 사례" 가 나오지
    않았다. N46 은 설계상 미지원이고 CLI 가 스스로 밝히며, N49 의 구분을
    필요로 하는 소비자가 없고, N50 은 CLI 로 닿을 수 없으며 표시를 바꾸지
    않는다. 그래서 감사와 기록으로 끝냈다.
    """
    shas = _phase_shas()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    base = subprocess.run(
        ["git", "rev-parse", f"{shas[-1]}^"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--", *PRODUCTION_DIRS],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    assert diff == "", diff


def test_35_only_a_test_file_and_a_report_were_added():
    r"""🟢 §9 — 변경 파일은 테스트와 보고서뿐이다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert changed == {
        "tests/test_text_analysis_consumer_policy_audit.py",
        "docs/phase3f42-text-analysis-consumer-policy-audit.md",
    }, changed


def test_36_no_forbidden_path_was_touched():
    r"""🔴 §0 금지 — Lua · README · engine · agent · core · 검색 계층 · data."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        for prefix in ("engine/", "agent/", "core/", "data/", "app/",
                       "analysis/", "scripts/", "sources/"):
            assert not path.startswith(prefix), path


def test_37_no_existing_test_was_modified_or_deleted():
    r"""🔴 §6 — 기존 테스트를 수정·삭제하지 않았다.

    이번에는 production 을 바꾸지 않았으므로 기존 테스트가 깨질 이유도 없다.
    """
    shas = _phase_shas()
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
        assert after[name] == count, (name, count, after[name])
    changed_tests = {p for p in _changed_files() if p in before}
    assert changed_tests == set(), changed_tests
