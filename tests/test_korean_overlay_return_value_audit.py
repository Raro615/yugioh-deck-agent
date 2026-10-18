r"""
Phase 3-F-45 — `korean_source.apply(cards)` 반환값의 **소비 및 집계 경계** 감사.

Phase 3-F-44 가 "반환값이 버려진다" 는 사실을 고정했다. 이 Phase 는 그
반환값이 **무엇인지**, 버려도 되는 것인지를 묻는다. audit-only — production
을 한 줄도 바꾸지 않았다 (`test_10`).

🔴 **이 파일이 새로 고정하는 것** (3-F-44 가 다루지 않은 것만):

1. **반환값은 상태로부터 완전히 재계산된다.** `apply()` 가 돌려주는 수는
   `CardSource.KOREAN_OVERLAY` 가 붙은 카드 수와 **항상 같다**. 즉 버려지는
   것은 파생 통계일 뿐 복구 불가능한 정보가 아니다. 이 등식이 깨지면
   "버려도 안전하다" 는 판정의 근거가 조용히 무너지므로 못 박아 둔다.
2. **공개 API 만으로 재계산된다.** `all_cards(include_alternates=True)` 와
   `CardSource.KOREAN_OVERLAY` 로 같은 수가 나온다. 새 진단 API 나 추상화가
   필요하지 않다는 §3 질문 7 의 근거다.
3. **세 계층의 수가 서로 닫힌다.** 입력 항목 수 = 적용 수 + 레코드 없음,
   적용 수 = 정본 적용 + 적용된 alias 판본, 정본 = 정본 적용 + 한국어 없음.
   같은 모집단을 비교하는 자리와 아닌 자리를 식으로 구분한다.
4. **두 production 경로의 모집단이 다르다.** 변경 감지 어댑터는 입력 항목을
   세고(`load_records()`), `apply()` 는 결합에 성공한 카드를 센다. 둘은 서로
   다른 계층의 값이며 어느 쪽도 틀린 것이 아니다.
5. **"반환값을 버리는 유일한 호출" 은 production 범위의 진술이다.** 테스트
   코드에는 반환값을 버리는 `apply()` 호출이 많다. 3-F-44 의 문장을 더 넓게
   읽지 않도록 범위를 함께 고정한다.

🔴 이 파일은 64자 16진수 digest 리터럴을 쓰지 않고, 텍스트 분석기를
호출하지 않으며, 데이터 유무는 마커로 거른다 (다른 감사들의 지뢰선).
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core.card_model import Card, CardSource
from core.card_repository import CardRepository
from sources.korean_names import KoreanTextSource

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KO_JSON = PROJECT_ROOT / "data" / "ko" / "ko-KR.json"
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"

requires_korean_data = pytest.mark.skipif(
    not KO_JSON.is_file(), reason="data/ko/ko-KR.json 이 없습니다.")
requires_cards_cdb = pytest.mark.skipif(
    not CARDS_CDB.is_file(), reason="data/cards.cdb 가 없습니다.")

#: Phase 3-F-45 가 이번 커밋에서 실측한 값
KO_ENTRIES = 13899           # data/ko 항목 수 (입력 계층)
OVERLAY_APPLIED = 13892      # apply() 반환값 = 결합 성공 카드 수
APPLIED_CANONICAL = 13728    # 그중 정본 카드
APPLIED_ALIAS = 164          # 그중 alias 판본
NO_RECORD = 7                # 대응 레코드가 아예 없는 항목
CANONICAL_CARDS = 14127
CANONICAL_WITHOUT_KOREAN = 399

#: 🔴 ``deck`` 은 Phase 6-T 가 만든 production 디렉터리다 (``deck/opening.py`` ·
#: ``deck/recipe.py``). 여기 빠져 있어서 ``test_11`` 의 **전수 분류**가
#: 깨졌다 — ``deck/opening.py`` 의 ``.apply(...)`` 세 자리가 production 도
#: tests 도 아닌 것으로 남았다 (Phase 6-W 가 고쳤다). 그 셋은 반환값을
#: 버리지 않으므로 "버리는 자리는 하나" 라는 진술 자체는 참이었고,
#: **분모가 틀렸다.**
PRODUCTION_DIRS = (
    "analysis", "app", "core", "deck", "engine", "rules", "rulings",
    "scripts", "sources", "agent",
)


# ===========================================================================
# 공용 도구
# ===========================================================================
def _sample_cards() -> dict[int, Card]:
    return {
        46986414: Card(id=46986414, name="Dark Magician",
                       name_en="Dark Magician", desc="원문 텍스트"),
        483: Card(id=483, name="Parallel Teleport",
                  name_en="Parallel Teleport", desc="원문 텍스트"),
    }


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-45:"],
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


def _apply_call_sites() -> list[tuple[str, int, bool]]:
    """
    저장소 전체에서 ``*.apply(...)`` 호출을 AST 로 센다.

    문자열 검색은 주석과 스캔용 리터럴까지 세므로 쓰지 않는다 (§1).
    돌려주는 값은 ``(상대경로, 줄번호, 반환값을_버리는가)``.
    """
    skip = {".git", "__pycache__", ".pytest_cache", "data", ".venv"}
    rows: list[tuple[str, int, bool]] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if any(part in skip for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "apply"):
                rows.append((
                    str(path.relative_to(PROJECT_ROOT)),
                    node.lineno,
                    isinstance(parents.get(node), ast.Expr),
                ))
    return rows


# ===========================================================================
# A. 반환값의 의미 — 파생 통계인가 복구 불가능한 정보인가
# ===========================================================================
def test_01_return_value_counts_the_join_not_the_input():
    r"""🔴 §2 질문 1 — 반환값은 **입력 항목 수가 아니라 결합 성공 수**다.

    항목 3개 중 2개만 카드가 있는 경우를 만들어 확인한다. 반환값이 입력
    항목 수(3)가 아니라 결합에 성공한 수(2)여야 한다. 이 구분이 §2 질문 5
    (`13,899` 대 `13,892` 가 같은 모집단인가) 의 답을 결정한다.
    """
    source = KoreanTextSource({
        46986414: {"name": "블랙 매지션", "desc": "한국어 텍스트"},
        483: {"name": "패러렐 텔레포트", "desc": "한국어 텍스트"},
        999999999: {"name": "없는 카드", "desc": "한국어 텍스트"},
    })
    cards = _sample_cards()
    assert len(source.entries) == 3
    assert source.apply(cards) == 2


def test_02_return_value_always_equals_the_overlay_source_flag_count():
    r"""🔴 §2 질문 1·3 — 반환값 == `KOREAN_OVERLAY` 가 붙은 카드 수.

    **이 등식이 "버려도 안전하다" 는 판정의 근거다.** 반환값이 상태에
    기록되지 않는 별도의 정보를 담고 있다면 버리는 것이 손실이 된다.
    담고 있지 않다는 것을 식으로 고정한다.
    """
    source = KoreanTextSource({
        46986414: {"name": "블랙 매지션", "desc": "한국어 텍스트"},
        999999999: {"name": "없는 카드", "desc": "한국어 텍스트"},
    })
    cards = _sample_cards()
    returned = source.apply(cards)
    flagged = sum(1 for c in cards.values()
                  if CardSource.KOREAN_OVERLAY in c.sources)
    assert returned == flagged == 1


def test_03_empty_source_returns_zero_and_flags_nothing():
    r"""🟢 §2 질문 4 — 데이터가 없을 때도 등식이 유지된다.

    `autoload()` 는 `data/ko` 가 없으면 **오류가 아니라 빈 소스**를
    돌려준다(모듈 docstring 의 명시적 설계). 그 경우 반환값은 0 이고
    붙은 플래그도 0 이다 — 두 값이 함께 0 이므로 반환값을 보지 않아도
    같은 사실을 알 수 있다.
    """
    source = KoreanTextSource.autoload(PROJECT_ROOT / "no-such-ko-dir")
    assert not source
    cards = _sample_cards()
    assert source.apply(cards) == 0
    assert all(CardSource.KOREAN_OVERLAY not in c.sources
               for c in cards.values())


def test_04_return_value_never_exceeds_the_input_entry_count():
    r"""🟢 §2 질문 5 — 반환값 ≤ 항목 수. 두 수는 포함 관계다."""
    entries = {46986414: {"name": "블랙 매지션", "desc": "한국어 텍스트"}}
    source = KoreanTextSource(entries)
    cards = _sample_cards()
    assert source.apply(cards) <= len(entries)


# ===========================================================================
# B. 공개 API 로 재계산되는가 (§2 질문 7)
# ===========================================================================
@requires_cards_cdb
@requires_korean_data
def test_05_discarded_value_is_reproducible_through_public_api(repository):
    r"""🔴 §2 질문 7 — **새 API 없이** 버려진 수가 그대로 나온다.

    `all_cards(include_alternates=True)` 는 공개 메서드이고
    `CardSource.KOREAN_OVERLAY` 는 공개 enum 이다. 둘로 세면 `apply()` 가
    돌려주던 수가 정확히 나온다. 그래서 이 값을 보려고 새 진단 API 나
    추상화를 만들 이유가 없다.
    """
    recomputed = sum(
        1 for card in repository.all_cards(include_alternates=True)
        if CardSource.KOREAN_OVERLAY in card.sources)
    assert recomputed == OVERLAY_APPLIED


@requires_cards_cdb
@requires_korean_data
def test_06_two_state_witnesses_agree_because_every_entry_has_both_fields(
        repository):
    r"""🔴 §2 질문 1 — `name_ko` 로 세도 같은 수가 나오는 **이유**까지 고정.

    `apply()` 는 이름이 비어 있으면 `name_ko` 를 건드리지 않고도 플래그를
    붙인다. 그래서 두 수가 같은 것은 우연일 수 있다. 실제로는 `data/ko`
    항목 **전부가 이름과 텍스트를 모두** 갖고 있어서 같다 — 우연이 아니라
    데이터의 성질이다. 그 성질을 함께 못 박는다.
    """
    source = KoreanTextSource.autoload()
    name_only = sum(1 for v in source.entries.values()
                    if v.get("name", "").strip()
                    and not v.get("desc", "").strip())
    desc_only = sum(1 for v in source.entries.values()
                    if v.get("desc", "").strip()
                    and not v.get("name", "").strip())
    assert (name_only, desc_only) == (0, 0)

    records = repository.all_cards(include_alternates=True)
    flagged = sum(1 for c in records
                  if CardSource.KOREAN_OVERLAY in c.sources)
    with_name = sum(1 for c in records if c.name_ko)
    assert flagged == with_name == OVERLAY_APPLIED


# ===========================================================================
# C. 계층별 집계가 서로 닫히는가 (§2 질문 5·6)
# ===========================================================================
@requires_cards_cdb
@requires_korean_data
def test_07_input_layer_closes_entries_equals_applied_plus_no_record(
        repository):
    r"""🔴 §2 질문 5·6 — 입력 계층: 항목 = 적용 + 레코드 없음.

    `13,899` 과 `13,892` 는 **같은 모집단이 아니다.** 앞은 오버레이 입력의
    패스코드 키, 뒤는 그 키 중 카드 레코드가 있어 결합된 수다. 둘은 포함
    관계이므로 비교가 의미 있고, 차이는 "레코드가 없는 항목" 하나로
    설명된다.
    """
    source = KoreanTextSource.autoload()
    record_ids = {c.id for c in repository.all_cards(include_alternates=True)}
    applied = len(set(source.entries) & record_ids)
    missing = len(set(source.entries) - record_ids)
    assert len(source.entries) == KO_ENTRIES
    assert applied == OVERLAY_APPLIED
    assert missing == NO_RECORD
    assert applied + missing == len(source.entries)


@requires_cards_cdb
@requires_korean_data
def test_08_canonical_layer_closes_applied_equals_canonical_plus_alias(
        repository):
    r"""🔴 §2 질문 6 — 정본 계층: 적용 = 정본 적용 + 적용된 alias 판본.

    `apply()` 는 alias 판본을 포함한 전체 레코드에 적용되고, 정본만 세는
    집계는 그중 `164` 판본을 떨어뜨린다. 이 `164` 는 Phase 3-F-43-K0 이
    "정상 적용된 alias 판본" 으로 확인한 그 수다. 손실이 아니라 **집계
    기준의 차이**임을 식으로 못 박는다.
    """
    records = repository.all_cards(include_alternates=True)
    canonical_ids = {c.id for c in repository.all_cards()}
    flagged = {c.id for c in records
               if CardSource.KOREAN_OVERLAY in c.sources}
    on_canonical = flagged & canonical_ids
    on_alias = flagged - canonical_ids

    assert len(flagged) == OVERLAY_APPLIED
    assert len(on_canonical) == APPLIED_CANONICAL
    assert len(on_alias) == APPLIED_ALIAS
    assert len(on_canonical) + len(on_alias) == len(flagged)
    # 떨어진 것이 전부 alias 판본인지 — 정본이 섞여 있으면 집계가 아니라 손실이다
    assert all(repository.get(i).is_alternate_art for i in on_alias)


@requires_cards_cdb
@requires_korean_data
def test_09_card_layer_closes_canonical_equals_with_korean_plus_without(
        repository):
    r"""🟢 §2 질문 6 — 카드 계층: 정본 = 한국어 있음 + 한국어 없음.

    사용자가 보는 카드 수(`14,127`)를 기준으로 하면 한국어가 있는 카드는
    `13,728` 이고 없는 카드가 `399` 다. 이 `399` 는 지금까지 어느 출력에도
    나오지 않은 수다 — 세 계층 중 **사용자에게 의미가 있는 유일한 계층**이
    어디인지 보여 준다.
    """
    canonical = repository.all_cards()
    with_korean = [c for c in canonical
                   if CardSource.KOREAN_OVERLAY in c.sources]
    assert len(canonical) == CANONICAL_CARDS
    assert len(with_korean) == APPLIED_CANONICAL
    assert len(canonical) - len(with_korean) == CANONICAL_WITHOUT_KOREAN


@requires_korean_data
def test_10_change_detection_adapter_counts_the_input_layer_not_the_join():
    r"""🔴 §2 질문 5 — 두 production 경로의 **모집단이 다르다.**

    변경 감지 어댑터는 `load_records()` 로 **입력 항목**을 세고, 저장소
    빌드는 `apply()` 로 **결합 성공**을 센다. 갱신 파이프라인의
    `소스별 변경 내역` 에 찍히는 수는 앞쪽(`13,899`)이다. 어느 쪽도 틀리지
    않았고, 둘을 같은 수로 맞추려 하면 한쪽 계층이 사라진다.
    """
    from sources.adapters import KoreanDatabaseAdapter

    records = KoreanDatabaseAdapter().load_records()
    source = KoreanTextSource.autoload()
    assert len(records) == len(source.entries) == KO_ENTRIES
    assert len(records) != OVERLAY_APPLIED


# ===========================================================================
# D. 3-F-44 진술의 범위
# ===========================================================================
def test_11_the_sole_discarded_apply_claim_is_scoped_to_production():
    r"""🔴 §1 — "반환값을 버리는 유일한 호출" 은 **production 범위**의 말이다.

    production 에서는 `apply()` 호출 중 반환값을 버리는 자리가 하나뿐이고
    그 자리가 `core/card_repository.py` 다. 그러나 테스트 코드에는 반환값을
    버리는 호출이 **여럿** 있다. 3-F-44 의 문장을 저장소 전체에 대한
    진술로 넓혀 읽으면 틀리므로 범위를 함께 고정한다.
    """
    rows = _apply_call_sites()
    prod = [r for r in rows if r[0].split("/")[0] in PRODUCTION_DIRS]
    tests = [r for r in rows if r[0].split("/")[0] == "tests"]
    prod_discarded = [r for r in prod if r[2]]
    tests_discarded = [r for r in tests if r[2]]

    assert len(prod_discarded) == 1, prod_discarded
    assert prod_discarded[0][0] == "core/card_repository.py"
    # 테스트에도 버리는 자리가 있다 — 그래서 "유일" 은 production 한정이다
    assert len(tests_discarded) > 1
    assert rows and len(prod) + len(tests) == len(rows)


# ===========================================================================
# E. 범위와 금지
# ===========================================================================
def test_12_this_phase_changed_no_production_file():
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


def test_13_only_a_test_file_and_a_report_were_added():
    r"""🟢 §6 — 변경 파일은 이 테스트와 보고서뿐이다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert changed == {
        "tests/test_korean_overlay_return_value_audit.py",
        "docs/phase3f45-korean-overlay-return-value-audit.md",
    }, changed


def test_14_no_forbidden_path_was_touched():
    r"""🔴 §4 금지 — Lua · README · data · production 디렉터리 0건."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        for prefix in PRODUCTION_DIRS:
            assert not path.startswith(prefix + "/"), path
        assert not path.startswith("data/"), path


def test_15_this_file_respects_the_repository_tripwires():
    r"""🔴 다른 감사들이 이 파일에 걸지 않는지 **스스로** 확인한다.

    세 지뢰선: 64자 16진수 리터럴을 세는 digest 감사, 텍스트 분석기를
    인스턴스화하는 파일 목록을 고정한 감사, 신규 테스트 파일의 skip 호출
    문구를 검사하는 감사. 앞 Phase 들에서 실제로 세 번 걸렸다.
    """
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

    # skip 호출은 commit 게이트 문구만 쓴다 (데이터 게이트는 마커로 거른다)
    for match in re.findall(r"pytest\.skip\(([^)]*)\)", text):
        assert "commit 이 아직 없다" in match, match
