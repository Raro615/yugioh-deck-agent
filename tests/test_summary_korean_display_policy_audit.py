r"""
Phase 3-F-46 — `summarise()` 의 **한국어 데이터 표시 정책** 감사.

Phase 3-F-45 가 "갱신 요약에 한국어 계층이 없다" 를 남겼다. 이 Phase 는 그
없음이 **잘못된 언어 출력**인지 **없는 행**인지를 가린다. audit-only —
production 을 한 줄도 바꾸지 않았다 (`test_08`).

🔴 **측정 결과, 전제가 뒤집혔다.** `summarise()` 는 영어 이름·텍스트를
출력하지 않는다. **이름도 텍스트도 아예 출력하지 않는다.** 읽는 속성이
`provenance.analysis_status` · `all_cards()` · `stats()` 뿐이고
`name`/`name_ko`/`desc`/`display_name` 중 **어느 것도 건드리지 않는다.**
따라서 "적용된 한국어가 영어로 나온다" 는 사례는 존재할 수 없고, 남는
질문은 "없는 집계 행" 하나다.

🔴 **이 파일이 새로 고정하는 것** (기존 감사가 다루지 않은 것만):

1. `summarise()` 가 **언어 선택에 관여하지 않는다** (AST + 실제 출력).
   언어 표시 책임은 이름·텍스트를 고르는 소비자(`app/main.py`)에 있다.
2. `use_korean` 축을 포함한 **2 x 2 행렬**이 네 칸 모두 자기 일관적이다.
   기존 감사들은 이 축을 바꿔 본 적이 없다.
3. 세 증거(`name_ko` · `CardSource.KOREAN_OVERLAY` ·
   `provenance.availability.korean_available`)가 **카드 단위로 전부
   일치한다.** 기존 provenance 로 충분하다는 §2 질문 5 의 근거다.

🔴 **일부러 고정하지 않은 것**: `summarise()` 출력이 `use_korean` 과
무관하다는 사실. 그것이 바로 보고된 공백이고, 못 박으면 다음 단계가
그 공백을 메울 때 **이 테스트를 수정해야** 한다. 기존 테스트 수정 금지와
정면으로 부딪히므로 보고서에만 적는다.

🔴 이 파일은 64자 16진수 digest 리터럴을 쓰지 않고, 텍스트 분석기를
호출하지 않으며, 데이터 유무는 마커로 거른다 (다른 감사들의 지뢰선).
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
from pathlib import Path

import pytest

import scripts.update_cards as update_module
from core.card_model import CardSource
from core.card_repository import CardRepository
from scripts.update_cards import summarise

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"
KO_JSON = PROJECT_ROOT / "data" / "ko" / "ko-KR.json"

requires_cards_cdb = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="data/cards.cdb 가 없습니다.")
requires_korean_data = pytest.mark.skipif(
    not KO_JSON.is_file(), reason="data/ko/ko-KR.json 이 없습니다.")

#: Phase 3-F-46 이 이번 커밋에서 실측한 표본
KOREAN_CARD = 483            # 한국어 이름·텍스트가 모두 있는 카드
KOREAN_NAME = "패러렐 텔레포트"
ENGLISH_NAME = "Parallel Teleport"
ENGLISH_ONLY_CARD = 212652   # data/ko 에 항목이 없는 카드
ENGLISH_ONLY_NAME = "Trap of the Poisonous Scorpion"

#: 언어·이름·텍스트를 고르는 데 쓰이는 속성들
LANGUAGE_ATTRS = {
    "name", "name_ko", "name_en", "name_ja", "desc", "desc_en",
    "display_name", "summary_ko",
}

PRODUCTION_DIRS = (
    "analysis", "app", "core", "engine", "rules", "rulings", "scripts",
    "sources", "agent",
)


# ===========================================================================
# 공용 도구
# ===========================================================================
@pytest.fixture(scope="module")
def repo_without_korean():
    """오버레이를 끈 리포지토리. 빌드가 느리므로 모듈당 한 번만 만든다."""
    if not CARDS_CDB.is_file():
        pytest.skip("cards.cdb 없음")
    return CardRepository.build(db_path=CARDS_CDB, script_dir=PROJECT_ROOT,
                               use_korean=False)


def _detail(repository, card_id: int) -> str:
    """`print_card_detail` 을 실제 소비자와 같은 방식으로 돌린다."""
    import contextlib
    import io

    from app.main import DeckAgent, print_card_detail

    card = repository.get(card_id)
    assert card is not None, card_id
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_card_detail(DeckAgent(repository), card)
    return buffer.getvalue()


def _text_label(out: str) -> str:
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("카드 텍스트"):
            return stripped
    return "<없음>"


def _name_rows(out: str) -> str:
    """
    이름 표(한국어 / 공식 DB / 일본어) 부분만 잘라낸다.

    🔴 들여쓰기를 **실제 출력에서 확인했다.** `app/main.py` 는
    ``f"  {label:<7}: {value}"`` 로 찍으므로 앞 공백이 **2개**다. 4개로
    짚으면 한 줄도 잡히지 않고, 그러면 "한국어 행이 없다" 류의 단정이 빈
    문자열 위에서 전부 참이 되어 **거짓 양성**이 된다. 그래서 아래 두
    테스트는 표가 비어 있지 않음을 먼저 확인한다.
    """
    rows = [line for line in out.splitlines()
            if re.match(r"^ {2}(한국어|공식 DB|일본어)\s*:", line)]
    return "\n".join(rows)


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-46:"],
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


# ===========================================================================
# A. summarise() 는 언어 선택에 관여하지 않는다 (§2 질문 1·2·3)
# ===========================================================================
def test_01_summarise_reads_no_language_or_name_attribute():
    r"""🔴 §2 질문 1 — **영어로 출력할 수가 없다.** 이름·텍스트를 안 읽는다.

    AST 로 `summarise()` 가 읽는 속성을 전부 센다. 문자열 검색은 주석과
    설명 문구까지 세므로 쓰지 않는다. `name`·`name_ko`·`desc`·
    `display_name`·`summary_ko` 중 **하나도** 나타나지 않아야 한다.
    """
    tree = ast.parse(inspect.getsource(update_module))
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "summarise")
    attrs = {node.attr for node in ast.walk(func)
             if isinstance(node, ast.Attribute)}
    assert attrs & LANGUAGE_ATTRS == set(), sorted(attrs & LANGUAGE_ATTRS)
    # 실제로 읽는 것은 분석 근거와 집계뿐이다
    assert {"analysis_status", "provenance", "all_cards", "stats"} <= attrs


@requires_cards_cdb
@requires_korean_data
def test_02_summarise_output_contains_no_card_name_in_any_language(
        capsys, repository):
    r"""🔴 §2 질문 2 — 라벨만 없는 게 아니라 **이름·텍스트 자체가 없다.**

    한국어 이름과 영어 이름을 모두 실제 출력에서 찾아본다. 둘 다 없으면
    "한국어 이름은 이미 나오는데 상태 라벨만 없다" 는 전제가 틀린 것이다.
    """
    summarise(repository)
    out = capsys.readouterr().out
    for name in (KOREAN_NAME, ENGLISH_NAME, ENGLISH_ONLY_NAME):
        assert name not in out, name
    # 집계 표인 것은 맞다
    assert "카드 데이터 현황" in out


def test_03_summarise_never_calls_a_name_or_summary_helper():
    r"""🟢 §2 질문 3 — 언어를 고르는 헬퍼를 부르지 않는다.

    `display_name()` 과 `summary_ko()` 가 언어 선택 지점이다. `summarise()`
    가 둘을 부르지 않는다는 것은 **언어 표시 책임이 여기 없다**는 뜻이다.
    """
    tree = ast.parse(inspect.getsource(update_module))
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "summarise")
    called = {node.func.attr for node in ast.walk(func)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)}
    assert "display_name" not in called
    assert "summary_ko" not in called


# ===========================================================================
# B. use_korean 축을 포함한 2 x 2 행렬 (§3)
# ===========================================================================
@requires_cards_cdb
@requires_korean_data
def test_04_korean_card_with_overlay_on_is_korean_everywhere(repository):
    r"""🔴 §3 — 한국어 있음 + `use_korean=True`: 네 신호가 모두 한국어다."""
    card = repository.get(KOREAN_CARD)
    assert card.name_ko == KOREAN_NAME
    assert CardSource.KOREAN_OVERLAY in card.sources
    assert card.provenance.availability.korean_available is True

    out = _detail(repository, KOREAN_CARD)
    assert KOREAN_NAME in out.splitlines()[1]
    assert KOREAN_NAME in _name_rows(out)
    assert _text_label(out) == "카드 텍스트(한국어):"


@requires_cards_cdb
def test_05_korean_card_with_overlay_off_claims_no_korean(
        repo_without_korean):
    r"""🔴 §3 + §2 질문 4 — 같은 카드, 오버레이만 끄면 **한국어를 주장하지 않는다.**

    설정과 출력이 어긋나지 않는지가 핵심이다. 영어 데이터에 한국어 라벨이
    붙으면 그것이 `CONFIRMED_BUG` 다. 붙지 않는다.
    """
    card = repo_without_korean.get(KOREAN_CARD)
    assert card.name_ko is None
    assert CardSource.KOREAN_OVERLAY not in card.sources
    assert card.provenance.availability.korean_available is False

    out = _detail(repo_without_korean, KOREAN_CARD)
    assert ENGLISH_NAME in out.splitlines()[1]
    assert KOREAN_NAME not in out
    # 언어 수식어가 붙지 않는다 — 없는 한국어를 있다고 하지 않는다
    assert _text_label(out) == "카드 텍스트:"
    rows = _name_rows(out)
    # 🔴 표가 비어 있으면 아래 단정이 공짜로 참이 된다 — 먼저 막는다
    assert "공식 DB" in rows, rows
    assert "한국어" not in rows, rows


@requires_cards_cdb
def test_06_english_only_card_is_identical_under_both_settings(
        repository, repo_without_korean):
    r"""🟢 §3 — 입력이 없는 카드는 설정을 바꿔도 **똑같다.**

    `data/ko` 에 항목이 없는 카드는 `use_korean` 이 가리킬 대상이 없다.
    두 설정의 출력이 글자 단위로 같아야 하고, 어느 쪽도 한국어를 주장하지
    않아야 한다. 이 경우는 출력 결함이 아니다 (§3 마지막 문단).
    """
    on = _detail(repository, ENGLISH_ONLY_CARD)
    off = _detail(repo_without_korean, ENGLISH_ONLY_CARD)
    assert on == off
    assert ENGLISH_ONLY_NAME in on.splitlines()[1]
    assert _text_label(on) == "카드 텍스트:"
    rows = _name_rows(on)
    # 🔴 표가 비어 있으면 아래 단정이 공짜로 참이 된다 — 먼저 막는다
    assert "공식 DB" in rows, rows
    assert "한국어" not in rows, rows


# ===========================================================================
# C. 기존 provenance 로 충분한가 (§2 질문 5)
# ===========================================================================
@requires_cards_cdb
@requires_korean_data
def test_07_three_witnesses_agree_card_by_card_across_the_corpus(repository):
    r"""🔴 §2 질문 5 — 세 증거가 **카드 단위로 전부 일치한다.**

    `name_ko` 가 있다 · `KOREAN_OVERLAY` 가 붙었다 · `korean_available` 이
    참이다 — 셋 중 하나만 참인 카드가 하나라도 있으면 기존 provenance 가
    부족하다는 뜻이다. 전수로 확인한다. 어긋나는 카드가 0 이면 새 enum 이나
    새 필드가 필요하지 않다.
    """
    mismatched = []
    for card in repository.all_cards(include_alternates=True):
        has_name = bool(card.name_ko)
        has_flag = CardSource.KOREAN_OVERLAY in card.sources
        available = card.provenance.availability.korean_available
        if not (has_name == has_flag == available):
            mismatched.append(
                (card.id, has_name, has_flag, available))
    assert mismatched == [], mismatched[:10]


# ===========================================================================
# D. 범위와 금지
# ===========================================================================
def test_08_this_phase_changed_no_production_file():
    r"""🔴 §5 — **audit-only.** production 을 한 줄도 바꾸지 않았다."""
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


def test_09_only_a_test_file_and_a_report_were_added():
    r"""🟢 §7 — 변경 파일은 이 테스트와 보고서뿐이다. data · README 0건."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert changed == {
        "tests/test_summary_korean_display_policy_audit.py",
        "docs/phase3f46-summary-korean-display-policy-audit.md",
    }, changed
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        assert not path.startswith("data/"), path


def test_10_this_file_respects_the_repository_tripwires():
    r"""🔴 다른 감사들이 이 파일에 걸지 않는지 **스스로** 확인한다."""
    text = Path(__file__).read_text(encoding="utf-8")
    source = ast.parse(text)

    assert re.search(r"[0-9a-f]{64}", text) is None

    analyzer_calls = [
        node for node in ast.walk(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.endswith("TextEffectAnalyzer")
    ]
    assert analyzer_calls == []

    for match in re.findall(r"pytest\.skip\(([^)]*)\)", text):
        assert ("commit 이 아직 없다" in match
                or "cards.cdb 없음" in match), match
