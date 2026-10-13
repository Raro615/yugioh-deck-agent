r"""
Phase 3-F-44 — 한국어 오버레이 미적용 항목의 **사용자 표시 경계** 감사.

Phase 3-F-43-K0 이 "미적용 7개" 를 확정했다. 이 Phase 는 그 7개가 **사용자
눈에 닿을 수 있는가**를 묻는다. audit-only — production 을 한 줄도 바꾸지
않았다 (`test_18`).

🔴 **새로 확인한 세 가지** (3-F-43-K0 이 다루지 않은 것만 고정한다):

1. **정상 CLI 흐름에 들어올 수 없다.** `card`·`analyze`·`related`·
   `relations` 네 명령 전부가 7개 패스코드에서 `카드를 찾을 수 없습니다` 를
   내고 **종료 코드 1** 이다. 경계는 오버레이가 아니라 **카드 조회**다 —
   `repository.get()` 이 `None` 을 돌려주는 지점에서 멈춘다.
2. **7개가 3 + 4 로 갈린다.**
   * **3개** (20250830 · 81480461 · 101303084): 같은 **공식 CID** 의 다른
     패스코드가 저장소에 있고 **한국어 이름·텍스트를 이미 받았다.** 두
     항목의 이름과 텍스트가 **완전히 동일**하므로 정보 손실이 **0** 이고,
     사용자는 그 한국어 이름으로 카드를 찾을 수 있다.
   * **4개** (662853 · 662854 · 662855 · 662857): 그 CID 에 다른 패스코드가
     없고 카드 자체가 없다. 표시할 대상이 없다.
3. **진단 수치가 만들어지고 버려진다.** `apply()` 는 docstring 대로 "적용된
   카드 수" 를 돌려주는데(13,892), `CardRepository.build()` 가 그 반환값을
   **버린다** — 저장소 전체에서 `*.apply(...)` 의 반환값을 버리는 **유일한**
   자리다.

🔴 이 파일은 64자 16진수 digest 리터럴을 쓰지 않고, 텍스트 분석기를
호출하지 않으며, 데이터 유무는 마커로 거른다 (다른 감사들의 지뢰선).
"""

from __future__ import annotations

import ast
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import core.card_repository as repository_module
from core.card_repository import CardRepository
from core.provenance import AnalysisStatus
from sources.korean_names import KoreanTextSource

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KO_JSON = PROJECT_ROOT / "data" / "ko" / "ko-KR.json"
KO_CACHE = PROJECT_ROOT / "data" / "ko" / ".cache" / "cid_to_passcode.json"
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"

requires_korean_data = pytest.mark.skipif(
    not KO_JSON.is_file(), reason="data/ko/ko-KR.json 이 없습니다.")
requires_cards_cdb = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="data/cards.cdb 가 없습니다.")
requires_collector_cache = pytest.mark.skipif(
    not KO_CACHE.is_file(), reason="수집기 캐시가 없습니다.")

# --- Phase 3-F-44 가 현재 커밋에서 실측한 값 ------------------------------
UNAPPLIED = [662853, 662854, 662855, 662857, 20250830, 81480461, 101303084]
#: 같은 공식 CID 의 형제 패스코드가 저장소에 있고 한국어를 받은 경우
COVERED = {
    20250830: (95658967, "12539"),
    81480461: (81480460, "4749"),
    101303084: (22984000, "22330"),
}
#: 형제가 없고 카드 자체가 없는 경우
ORPHANED = [662853, 662854, 662855, 662857]
CARD_ID_COMMANDS = ("card", "analyze", "related", "relations")
NOT_FOUND = "카드를 찾을 수 없습니다"
OVERLAY_APPLIED = 13892
KO_ENTRIES = 13899
CANONICAL_CARDS = 14127
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}

PRODUCTION_DIRS = (
    "analysis", "app", "core", "engine", "rules", "rulings", "scripts",
    "sources", "agent",
)


# ===========================================================================
# 공용 도구
# ===========================================================================
def _run_cli(*args) -> tuple[int, str]:
    """**실제 CLI** 를 하위 프로세스로 돌린다 (종료 코드까지 본다)."""
    proc = subprocess.run(
        [sys.executable, "-m", "app.main", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _collector_reverse() -> dict[str, list[str]]:
    mapping = json.loads(KO_CACHE.read_text(encoding="utf-8"))
    reverse: dict[str, list[str]] = collections.defaultdict(list)
    for cid, value in mapping.items():
        for passcode in (value if isinstance(value, list) else [value]):
            reverse[str(passcode)].append(cid)
    return reverse


def _official_cid_of(passcode: int) -> str | None:
    for cid, value in json.loads(
            KO_CACHE.read_text(encoding="utf-8")).items():
        if passcode in (value if isinstance(value, list) else [value]):
            return cid
    return None


def _siblings_of(passcode: int) -> list[int]:
    cid = _official_cid_of(passcode)
    if cid is None:
        return []
    mapping = json.loads(KO_CACHE.read_text(encoding="utf-8"))
    value = mapping[cid]
    return [p for p in (value if isinstance(value, list) else [value])]


def _production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if set(path.relative_to(PROJECT_ROOT).parts) & {
                "tests", "__pycache__", ".git"}:
            continue
        yield path


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-44:"],
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
# A. 정상 CLI 흐름에 들어올 수 있는가
# ===========================================================================
@requires_cards_cdb
@pytest.mark.parametrize("command", CARD_ID_COMMANDS)
def test_01_every_card_id_command_reports_not_found(command):
    r"""🔴 §3 — 네 명령 전부가 **카드를 찾을 수 없다**고 답하고 종료 코드 1이다.

    오버레이 이야기는 나오지 않는다 — 카드가 없으니 그 앞에서 멈춘다.
    """
    code, out = _run_cli(command, str(UNAPPLIED[0]))
    assert code == 1, (command, code, out)
    assert NOT_FOUND in out, out
    for token in ("한국어", "오버레이", "KOREAN_OVERLAY"):
        assert token not in out, (command, token)


@requires_cards_cdb
def test_02_all_seven_are_unreachable_by_passcode():
    r"""🔴 §3 — 7개 전부 ID 로 도달 **0/7**. 실제 CLI 로 확인한다."""
    reachable = []
    for passcode in UNAPPLIED:
        code, out = _run_cli("card", str(passcode))
        if code == 0 or NOT_FOUND not in out:
            reachable.append(passcode)
    assert reachable == []


@requires_cards_cdb
def test_03_the_boundary_is_the_card_lookup_not_the_overlay():
    r"""🔴 §3 — 경계가 **카드 조회**다. ``get()`` 이 ``None`` 을 돌려준다.

    오버레이·provenance 로직은 실행될 기회가 없다.
    """
    repo = CardRepository.build()
    assert [p for p in UNAPPLIED if repo.get(p) is not None] == []
    assert [p for p in UNAPPLIED if p in repo._cards] == []


@requires_cards_cdb
def test_04_analysis_never_starts_for_a_missing_card(monkeypatch):
    r"""🔴 §3 — 분석이 **시작조차 하지 않는다**.

    ``cmd_analyze`` 는 카드가 없으면 분석기를 만들기 전에 돌아간다.
    """
    import app.main as main_module
    from analysis.effect_analyzer import EffectAnalyzer

    calls: list[int] = []
    original = EffectAnalyzer.analyze

    def traced(self, card):
        calls.append(getattr(card, "id", -1))
        return original(self, card)

    monkeypatch.setattr(EffectAnalyzer, "analyze", traced)
    repo = CardRepository.build()
    agent = type("Agent", (), {"repository": repo})()
    for passcode in UNAPPLIED:
        args = type("A", (), {"card_id": passcode})()
        assert main_module.cmd_analyze(agent, args) == 1
    assert calls == []


# ===========================================================================
# B. 7개가 3 + 4 로 갈린다
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_05_three_have_an_applied_sibling_passcode():
    r"""🔴 §2 — **3개는 같은 공식 CID 의 형제 패스코드가 한국어를 받았다.**

    저장소에 그 카드가 있고 ``name_ko`` 가 채워져 있다.
    """
    repo = CardRepository.build()
    for passcode, (sibling, cid) in COVERED.items():
        assert _official_cid_of(passcode) == cid, passcode
        assert sibling in _siblings_of(passcode), passcode
        card = repo.get(sibling)
        assert card is not None, sibling
        assert card.name_ko, sibling


@requires_korean_data
@requires_collector_cache
def test_06_the_sibling_carries_identical_korean_data():
    r"""🔴 §3 — 두 항목의 이름과 텍스트가 **완전히 같다** → 정보 손실 0."""
    source = KoreanTextSource.autoload()
    for passcode, (sibling, _cid) in COVERED.items():
        assert sibling in source.entries, sibling
        mine = source.entries[passcode]
        theirs = source.entries[sibling]
        assert mine.get("name") == theirs.get("name"), passcode
        assert mine.get("desc") == theirs.get("desc"), passcode


@requires_korean_data
@requires_cards_cdb
def test_07_those_three_are_reachable_by_their_korean_name():
    r"""🟢 §3 — 사용자는 그 **한국어 이름으로 카드를 찾을 수 있다**.

    CLI 가 쓰는 ``resolve_exact_name`` 경로로 확인한다.
    """
    repo = CardRepository.build()
    source = KoreanTextSource.autoload()
    for passcode, (sibling, _cid) in COVERED.items():
        name = source.entries[passcode].get("name", "")
        records = repo.find_by_exact_name(name)
        assert records, name
        assert sibling in {card.id for card in records}, (name, sibling)
        assert repo.resolve_exact_name(name) is not None, name


@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_08_four_have_no_sibling_and_no_card_at_all():
    r"""🔴 §2 — **4개는 형제가 없고 이름으로도 0장**이다. 표시 대상이 없다."""
    repo = CardRepository.build()
    source = KoreanTextSource.autoload()
    for passcode in ORPHANED:
        siblings = [p for p in _siblings_of(passcode) if p != passcode]
        assert siblings == [], passcode
        name = source.entries[passcode].get("name", "")
        assert repo.find_by_exact_name(name) == [], name
        assert repo.resolve_exact_name(name) is None, name
        partial = [c for c in repo.all_cards() if name in (c.name_ko or "")]
        assert partial == [], name


@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_09_the_two_groups_account_for_all_seven():
    r"""🟢 §2 — 3 + 4 = 7. 겹치지 않고 빠지지 않는다."""
    assert set(COVERED) | set(ORPHANED) == set(UNAPPLIED)
    assert set(COVERED) & set(ORPHANED) == set()
    assert len(COVERED) + len(ORPHANED) == len(UNAPPLIED) == 7


# ===========================================================================
# C. 다섯 상태가 하나의 메시지로 합쳐지지 않는다
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_10_an_applied_card_shows_its_korean_rows():
    r"""🟢 §2 ① — 정상 적용 카드는 한국어 이름 행과 한국어 텍스트 라벨을 받는다."""
    code, out = _run_cli("card", "483")
    assert code == 0, out
    assert "한국어" in out
    assert "카드 텍스트(한국어)" in out


@requires_cards_cdb
def test_11_a_missing_card_is_not_reported_as_a_korean_data_problem():
    r"""🔴 §2 ② — 카드 부재는 **오버레이 문제로 보고되지 않는다**.

    서로 다른 상태를 같은 메시지로 합치지 않는다는 뜻이기도 하다.
    """
    code, out = _run_cli("card", str(ORPHANED[0]))
    assert code == 1
    assert NOT_FOUND in out
    assert "한국어" not in out
    assert "카드 텍스트" not in out


@requires_cards_cdb
def test_12_a_card_without_korean_input_looks_different_again():
    r"""🟢 §2 ③ — 한국어 입력이 없는 카드는 **또 다른 출력**이다.

    한국어 이름 행이 없고 텍스트 라벨에 언어 표시가 없다. 세 상태(①②③)의
    출력이 서로 다르다.
    """
    code, out = _run_cli("card", "212652")      # 한국어 데이터 없는 실제 카드
    assert code == 0, out
    assert "카드 텍스트" in out
    assert "카드 텍스트(한국어)" not in out
    assert NOT_FOUND not in out


@requires_korean_data
@requires_cards_cdb
def test_13_the_undecidable_and_mismatch_states_remain_empty():
    r"""🟢 §2 ④⑤ — "판단 불가" 와 "ID 불일치" 는 실제 데이터에서 공집합이다.

    Phase 3-F-43-K0 의 결론을 이 커밋에서 재확인한다.
    """
    repo = CardRepository.build()
    undecidable = [c.id for c in repo.all_cards() if c.desc and not c.desc_en]
    assert undecidable == []
    source = KoreanTextSource.autoload()
    #: 미적용 항목 중 저장소 레코드를 가진 것이 없다 → 연결 실패가 아니다
    assert [p for p in UNAPPLIED if p in repo._cards] == []
    assert len(source.entries) == KO_ENTRIES


@requires_cards_cdb
def test_14_the_three_outcomes_produce_three_different_messages():
    r"""🔴 §2 — 세 상태의 출력이 **서로 다르다**. 하나로 합쳐지지 않았다."""
    applied = _run_cli("card", "483")[1]
    missing = _run_cli("card", str(ORPHANED[0]))[1]
    no_korean = _run_cli("card", "212652")[1]
    assert len({applied, missing, no_korean}) == 3
    assert "카드 텍스트(한국어)" in applied
    assert NOT_FOUND in missing
    assert "카드 텍스트(한국어)" not in no_korean and NOT_FOUND not in no_korean


# ===========================================================================
# D. 진단 수치가 만들어지고 버려지는 경계
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_15_apply_returns_the_applied_count_as_documented():
    r"""🟢 §3 — ``apply()`` 는 계약대로 적용된 카드 수를 돌려준다."""
    from sources.official_db import OfficialDatabaseSource

    source = KoreanTextSource.autoload()
    records = OfficialDatabaseSource(None).load()
    assert source.apply(records) == OVERLAY_APPLIED
    assert "적용된 카드 수를 돌려준다" in (KoreanTextSource.apply.__doc__ or "")


def test_16_build_discards_that_return_value():
    r"""🔴 §3 — **그 수를 버린다.** 저장소에서 ``apply`` 반환값을 버리는
    유일한 자리다 (AST 전수).

    진단 정보가 끊기는 경계가 정확히 여기다.
    """
    discarded: list[str] = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        bare = {
            id(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "apply"
                    and id(node) in bare):
                discarded.append(f"{path.relative_to(PROJECT_ROOT)}: "
                                 f"{ast.unparse(node)}")
    assert discarded == ["core/card_repository.py: korean_source.apply(cards)"], \
        discarded


def test_17_no_production_consumer_reads_the_applied_count():
    r"""🔴 §3 — 그 수를 읽는 production 소비자가 **0개**다.

    그래서 "표시되지 않는다" 의 원인이 출력 문구가 아니라 **값의 폐기**다.
    """
    source = ast.parse(
        (PROJECT_ROOT / "core" / "card_repository.py").read_text(
            encoding="utf-8"))
    assigns = [
        node for node in ast.walk(source)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "apply"
    ]
    assert assigns == []
    text = (PROJECT_ROOT / "core" / "card_repository.py").read_text(
        encoding="utf-8")
    assert "korean_source.apply(cards)" in text
    assert "applied" not in text.split("korean_source.apply(cards)")[1][:200]


# ===========================================================================
# E. 범위와 금지
# ===========================================================================
def test_18_this_phase_changed_no_production_file():
    r"""🔴 §4 — **audit-only.** production 을 한 줄도 바꾸지 않았다."""
    shas = _phase_shas()
    if not shas:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    #: 🔴 **commit 범위가 아니라 이 Phase 의 commit 들 자체를 본다**
    #: (Phase 4-B 가 두 번에 걸쳐 정정했다).
    #:
    #: 처음 이 단정은 ``git diff <base> HEAD`` 였다. 그러면 뜻이 "이 Phase
    #: 가 production 을 바꾸지 않았다" 에서 "이 Phase **이후** 아무도
    #: 바꾸지 않았다" 로 바뀐다 — 뒤에 오는 Phase 가 production 을
    #: 건드리는 순간 과거 audit 단계가 깨졌다.
    #:
    #: 그래서 끝점을 ``shas[0]`` 으로 바꿨는데 **그것도 틀렸다.** 범위
    #: 비교는 그 Phase 의 commit 이 히스토리 끝에 **연속**이라고 가정한다.
    #: 이 Phase 의 회귀 기록 commit 이 다른 Phase 의 작업 **뒤에** 붙는
    #: 순간 범위가 남의 commit 을 삼킨다 (실제로 그렇게 깨졌다).
    #:
    #: 범위가 아니라 **commit 하나하나가 건드린 파일**을 보면 순서와
    #: 무관하다. ``_changed_files()`` 가 이미 그렇게 센다.
    touched = sorted(
        path for path in _changed_files()
        if path.split("/")[0] in PRODUCTION_DIRS
    )
    assert touched == [], touched


def test_19_only_a_test_file_and_a_report_were_added():
    r"""🟢 §6 — 변경 파일은 이 테스트와 보고서뿐이다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert changed == {
        "tests/test_korean_overlay_display_boundary_audit.py",
        "docs/phase3f44-korean-overlay-display-boundary-audit.md",
    }, changed


def test_20_no_forbidden_path_and_no_data_file_was_touched():
    r"""🔴 §4 금지 — Lua · README · engine · agent · core · **data** 0건."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        for prefix in ("engine/", "agent/", "core/", "data/", "app/",
                       "analysis/", "scripts/", "sources/"):
            assert not path.startswith(prefix), path


def test_21_no_existing_test_was_modified_or_deleted():
    r"""🔴 §4 — 기존 테스트 수정·삭제 0건."""
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
    assert {p for p in _changed_files() if p in before} == set()


@requires_cards_cdb
def test_22_the_corpus_statistics_are_unchanged():
    r"""🟢 §5 — 카드 수와 상태 분포가 그대로다 (조사가 데이터를 바꾸지 않았다)."""
    repo = CardRepository.build()
    status = collections.Counter(
        card.provenance.analysis_status.value for card in repo.all_cards())
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CANONICAL_CARDS
    assert set(status) <= {s.value for s in AnalysisStatus}
    assert repository_module.CardRepository is CardRepository


def test_23_this_file_respects_the_repository_tripwires():
    r"""🔴 다른 감사의 지뢰선을 건드리지 않는다는 것을 스스로 지킨다."""
    text = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    hexes = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and len(node.value) == 64
        and all(ch in "0123456789abcdef" for ch in node.value)
    ]
    assert hexes == [], hexes
    analyzer_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "TextEffectAnalyzer"
    ]
    assert analyzer_calls == []
    for match in re.findall(r"pytest\.skip\([^)]*\)", text):
        assert "commit 이 아직 없다" in match, match
