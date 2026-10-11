r"""
Phase 3-F-43 — ``print_card_detail`` 출처 및 언어 표시 일관성 감사 (N51 + N52).

**결론부터: production 을 한 줄도 바꾸지 않았다.** 두 위험 모두 "사용자에게
**잘못된** 정보가 표시되는" 재현 사례가 나오지 않았고, §5 가 그 경우 수정을
금지했다 (`test_34`).

* **N51 — 이름 언어는 정확하고, 텍스트 라벨만 구조적으로 결합돼 있다.**
  이름은 ``한국어`` / ``공식 DB`` / ``일본어`` 세 행이 **소스별로 각각**
  찍히고 값이 있을 때만 나오므로 구조적으로 정확하다. 반면 **텍스트** 라벨은
  ``card.name_ko``(이름)로 고른다. 그 결합을 구성 사례로 재현했지만,
  실제 카드 **0장**이고 원천 데이터 **13,899항목 전부가 이름+텍스트를 함께**
  갖고 있어 데이터 파이프라인도 트리거를 만들지 않는다.
* **N52 — ``korean_available`` 은 이름에서 나온다.** 조건은
  ``if card.name_ko:`` 하나다. 그 이름이 암시하는 "한국어 데이터가 있다/
  적용됐다" 와 **정확히 같은 뜻이 아니다.** 다만 ``name_ko`` 를 쓰는
  production 자리가 ``KoreanTextSource.apply`` **한 곳**이므로
  ``korean_available ⟹ 오버레이 적용`` 은 성립하고, 실측도 1:1(13,728)이다.
  **정확한 신호는 이미 모델에 있다** — ``CardSource.KOREAN_OVERLAY`` —
  그런데 production 소비자가 0개다.

🔴 이 파일은 64자 16진수 digest 리터럴을 쓰지 않는다. 다른 감사 파일들이
"가장 많이 못 박힌 digest" 와 "핀 개수 7" 을 세고 있어서, 여기에 digest 를
적으면 그 테스트들이 깨진다 (Phase 3-F-33 의 N15, 3-F-42 가 실제로 겪은
지뢰선). 불변 조건은 **집계 수치**로 못 박는다.
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
import core.card_repository as repository_module
from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import HandlerBinding
from app.main import cmd_card, print_card_detail
from core import constants as C
from core.card_model import Card, CardSource
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus, SourceKind
from engine.ids import EffectRef, effect_refs
from sources.korean_names import KoreanTextSource
from tests.conftest import requires_official_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Phase 3-F-43 이 실측한 기준값 (테스트가 실제로 다시 산출한다) ----------
CARD_TOTAL = 14127
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}
ATTACHED_BLOCKS = 34635
#: 한국어 오버레이가 닿은 카드 — 네 신호가 **모두 같은 수**다
KOREAN_CARDS = 13728
#: 한국어가 없는 카드
NO_KOREAN_CARDS = CARD_TOTAL - KOREAN_CARDS      # 399
#: data/ko 항목 수와, 카드에 닿지 않아 조용히 버려지는 수
KO_ENTRIES = 13899
KO_ENTRIES_UNMATCHED = 171

KO_CARD = 483                 # 패러렐 텔레포트 — 한국어 이름 + 한국어 텍스트
NO_KO_CARD = 212652           # Trap of the Poisonous Scorpion — 한국어 없음
LUA_KO_CARD = 89631139        # 푸른 눈의 백룡

PRODUCTION_DIRS = (
    "analysis", "app", "core", "engine", "rules", "rulings", "scripts",
    "sources", "agent",
)

#: 🔴 데이터 유무는 **마커**로 거른다 — 함수 안에서 건너뛰기를 직접 호출하지
#: 않는다. 이 저장소의 기존 관용구가 그것이다
#: (``conftest.requires_official_db``). 여러 감사 파일이 "새로 추가한 파일이
#: 함수 안에서 호출한 건너뛰기" 를 정규식으로 세면서 commit 게이트 문구만
#: 허용하는데, 데이터 유무 게이트는 그 종류가 아니다. Phase 3-F-43 이 전체
#: 회귀에서 그 지뢰선 3개를 실제로 밟아 알게 됐다.
#:
#: 🔴 이 주석에 그 호출의 **이름을 그대로 적지 않는다.** 정규식이 주석의
#: 글자까지 세기 때문이다 (3-F-41 에서 같은 함정을 한 번 겪었다).
requires_korean_data = pytest.mark.skipif(
    not (PROJECT_ROOT / "data" / "ko").is_dir(),
    reason="data/ko 가 없습니다. python -m scripts.fetch_korean_db 로 내려받으세요.",
)


# ===========================================================================
# 공용 도구
# ===========================================================================
class _StubRepo:
    @staticmethod
    def archetype_name(card):
        return []


def _detail(card, repository=None) -> str:
    """**실제 ``print_card_detail``** 을 돌려 출력을 돌려준다."""
    agent = type("Agent", (), {
        "repository": repository if repository is not None else _StubRepo(),
    })()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_card_detail(agent, card)
    return buffer.getvalue()


def _name_rows(out: str) -> dict[str, str]:
    """출력에서 이름 행만 뽑는다 (라벨 -> 값)."""
    rows: dict[str, str] = {}
    for line in out.splitlines():
        match = re.match(r"\s{2}(한국어|공식 DB|일본어)\s*:\s*(.+)$", line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _text_label(out: str) -> str | None:
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("카드 텍스트"):
            return stripped.rstrip(":")
    return None


def _production_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if set(path.relative_to(PROJECT_ROOT).parts) & {
                "tests", "__pycache__", ".git"}:
            continue
        yield path


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-43:"],
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
# A. §2 — 실제 호출 경로
# ===========================================================================
def test_01_print_card_detail_has_exactly_one_production_caller():
    r"""🟢 §2 — ``print_card_detail`` 을 부르는 production 자리는 한 곳이다."""
    callers: list[str] = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "print_card_detail"):
                callers.append(str(path.relative_to(PROJECT_ROOT)))
    assert callers == ["app/main.py"], callers
    #: 그 한 곳이 ``cmd_card`` 다
    assert "print_card_detail(" in inspect.getsource(cmd_card)


def test_02_name_ko_is_written_in_exactly_one_place():
    r"""🔴 §2 / N52 — ``name_ko`` 에 대입하는 production 자리는 **한 곳**이다.

    그래서 ``name_ko`` 가 있으면 오버레이가 적용된 것이다 — 그 함의가
    ``korean_available`` 을 그나마 신뢰할 수 있게 만든다.
    """
    writers: list[str] = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            for target in targets:
                if (isinstance(target, ast.Attribute)
                        and target.attr == "name_ko"):
                    writers.append(str(path.relative_to(PROJECT_ROOT)))
    assert writers == ["sources/korean_names.py"], writers


def test_03_korean_available_is_decided_by_the_name():
    r"""🔴 §3 / N52 — ``korean_available`` 의 조건은 ``card.name_ko`` 하나다.

    이름이 암시하는 "한국어 데이터가 있다" 와 **같은 뜻이 아니다**. 같은
    분기에서 ``effect_text`` 의 출처까지 한국어 DB 로 기록한다 — **이름을
    근거로 텍스트 필드의 출처를 적는 것**이고, 같은 결합이 한 겹 더 깊다.
    """
    source = textwrap.dedent(inspect.getsource(
        repository_module.CardRepository._record_provenance))
    assert "if card.name_ko:" in source
    #: 그 ``if`` 블록 안에 세 줄이 **함께** 들어 있다
    block = source.split("if card.name_ko:")[1].split("elif")[0]
    assert "korean_available = True" in block
    assert 'record("card_name", SourceKind.KOREAN_DB)' in block
    #: 🔴 텍스트 출처까지 같은 조건에서 기록된다
    assert 'record("effect_text", SourceKind.KOREAN_DB)' in block
    #: AST 로도 확인한다 — 조건이 ``card.name_ko`` 단독이다
    tree = ast.parse(source)
    tests = [
        ast.unparse(node.test) for node in ast.walk(tree)
        if isinstance(node, ast.If) and "name_ko" in ast.unparse(node.test)
    ]
    assert tests == ["card.name_ko"], tests


def test_04_the_overlay_applied_signal_exists_but_has_no_consumer():
    r"""🔴 §3 / N52 — **적용 여부의 정확한 신호가 이미 있다.**

    ``KoreanTextSource.apply`` 는 이름·텍스트와 무관하게 닿은 카드마다
    ``CardSource.KOREAN_OVERLAY`` 를 더한다. 그런데 그것을 읽는 production
    소비자가 **0개**다 — 그래서 §5 의 "기존 모델로 표현할 수 있다면 새 필드를
    추가하지 말 것" 에 따라 새 필드를 만들지 않았다.
    """
    apply_source = inspect.getsource(KoreanTextSource.apply)
    assert "CardSource.KOREAN_OVERLAY" in apply_source
    #: 이름/텍스트 ``if`` 바깥에서 더해진다 — 들여쓰기로 확인한다
    lines = [l for l in apply_source.splitlines()
             if "sources.add(CardSource.KOREAN_OVERLAY)" in l]
    assert len(lines) == 1
    indent = len(lines[0]) - len(lines[0].lstrip())
    name_if = [l for l in apply_source.splitlines() if "if name:" in l][0]
    assert indent == len(name_if) - len(name_if.lstrip()), apply_source

    readers: list[str] = []
    for path in _production_files():
        if path.name in ("card_model.py", "korean_names.py"):
            continue
        if "KOREAN_OVERLAY" in path.read_text(encoding="utf-8", errors="replace"):
            readers.append(str(path.relative_to(PROJECT_ROOT)))
    assert readers == [], readers


def test_05_detail_and_search_share_the_same_display_name():
    r"""🟢 §2 — 상세와 검색이 **같은 표시 함수**를 쓴다 (`display_name`).

    둘 다 이름의 언어를 라벨하지 않는다 — 일관성이 있다는 뜻이다.
    """
    card = Card(id=1, name="영문", desc="x")
    card.name_ko = "한글"
    assert card.display_name() == "한글"
    card.name_ko = None
    assert card.display_name() == "영문"
    card.name = ""
    card.name_ja = "日本語"
    assert card.display_name() == "日本語"
    card.name_ja = ""
    assert card.display_name() == "#1"
    #: 🔴 내 예상이 틀렸다 — 검색 줄은 ``display_name`` 을 직접 부르지 않고
    #: ``summary_ko()`` 를 쓴다. 공유 지점이 한 겹 더 깊다. 그래서 상세의
    #: 머리글과 검색 줄이 **같은 문자열**이고, 일관성이 우연이 아니다.
    line_source = inspect.getsource(main_module.format_card_line)
    detail_source = inspect.getsource(print_card_detail)
    assert "summary_ko()" in line_source
    assert "summary_ko()" in detail_source
    assert "display_name" not in line_source
    #: ``summary_ko`` 가 그 안에서 ``display_name`` 을 쓴다
    assert "display_name()" in inspect.getsource(Card.summary_ko)


# ===========================================================================
# B. N51 — 이름 언어와 텍스트 언어의 독립성
# ===========================================================================
@requires_official_db
def test_06_each_name_row_is_labelled_by_its_own_source(repository):
    r"""🟢 N51 — **이름 언어는 정확하다.** 세 행이 소스별로 각각 찍힌다."""
    card = repository.get(KO_CARD)
    rows = _name_rows(_detail(card, repository))
    assert rows["한국어"] == card.name_ko
    assert rows["공식 DB"] == card.name_en
    assert rows["한국어"] != rows["공식 DB"]


@requires_official_db
def test_07_a_missing_name_row_is_simply_absent(repository):
    r"""🟢 N51 — 한국어 이름이 없으면 그 행이 **나오지 않는다**.

    없는 것을 빈 값으로 찍어 "한국어가 있다" 고 암시하지 않는다.
    """
    card = repository.get(NO_KO_CARD)
    assert card.name_ko in (None, "")
    rows = _name_rows(_detail(card, repository))
    assert "한국어" not in rows
    assert rows["공식 DB"] == card.name_en


def test_08_the_text_label_is_structurally_decided_by_the_name():
    r"""🔴 N51 — **텍스트 라벨은 이름으로 고른다** (구조적 결합)."""
    source = textwrap.dedent(inspect.getsource(print_card_detail))
    tree = ast.parse(source)
    conditionals = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.IfExp)
        and isinstance(node.test, ast.Attribute)
        and node.test.attr == "name_ko"
    ]
    assert len(conditionals) == 1, source
    #: 그 삼항식이 고르는 두 값이 텍스트 라벨이다
    chosen = {ast.literal_eval(conditionals[0].body),
              ast.literal_eval(conditionals[0].orelse)}
    assert chosen == {"카드 텍스트(한국어)", "카드 텍스트"}


def test_09_a_constructed_card_reproduces_the_mislabel():
    r"""🟠 N51 — 구성 사례로 **재현한다**: 이름만 한국어, 텍스트는 영어.

    `KoreanTextSource.apply` 가 이름과 텍스트를 **서로 독립된 조건**으로
    채우므로 구조적으로 가능하다. 🔴 **가상 카드다** — 실제 corpus 사례는
    `test_10`·`test_11` 이 0임을 확인한다.
    """
    card = Card(id=1, name="가짜", desc="This is English text.")
    card.name_ko = "가짜"
    card.desc_en = "This is English text."
    card.type_mask = C.TYPE_SPELL
    out = _detail(card)
    assert _text_label(out) == "카드 텍스트(한국어)"
    assert "This is English text." in out
    #: 원문 행은 ``desc_en != desc`` 일 때만 나오므로 여기서는 없다 —
    #: 즉 영어 텍스트가 "한국어" 라벨 **하나만** 달고 나온다
    assert "카드 텍스트(원문)" not in out


@requires_official_db
def test_10_no_real_card_reproduces_the_mislabel(repository):
    r"""🟢 N51 / §5 — 실제 카드 중 그 조건에 해당하는 것이 **0장**이다."""
    offenders = [
        card.id for card in repository.all_cards()
        if card.name_ko and card.desc and card.desc_en
        and card.desc == card.desc_en
    ]
    assert offenders == []


@requires_korean_data
def test_11_the_source_data_never_produces_the_trigger():
    r"""🔴 N51 / §5 — **원천 데이터**에도 트리거가 없다.

    `data/ko` 항목 전부가 이름과 텍스트를 함께 갖는다. 즉 수집기가 그 상태를
    만들어 본 적이 없다 — "0장" 보다 강한 근거다.
    """
    source = KoreanTextSource.autoload()
    assert source is not None
    assert len(source.entries) == KO_ENTRIES
    name_only = [
        cid for cid, entry in source.entries.items()
        if (entry.get("name") or "").strip()
        and not (entry.get("desc") or "").strip()
    ]
    desc_only = [
        cid for cid, entry in source.entries.items()
        if not (entry.get("name") or "").strip()
        and (entry.get("desc") or "").strip()
    ]
    assert name_only == []
    assert desc_only == []


@requires_official_db
def test_12_korean_name_and_replaced_text_always_coincide(repository):
    r"""🔴 N51 — 네 신호가 **같은 수**다. 그래서 라벨이 실제와 어긋나지 않는다."""
    cards = repository.all_cards()
    counts = {
        "overlay": sum(1 for c in cards
                       if CardSource.KOREAN_OVERLAY in c.sources),
        "name_ko": sum(1 for c in cards if c.name_ko),
        "korean_available": sum(
            1 for c in cards if c.provenance.availability.korean_available),
        "text_replaced": sum(1 for c in cards
                             if c.desc and c.desc_en and c.desc != c.desc_en),
    }
    assert set(counts.values()) == {KOREAN_CARDS}, counts


@requires_official_db
def test_13_the_korean_text_row_and_the_original_row_are_both_shown(repository):
    r"""🟢 N51 — 한국어 카드는 **두 텍스트 행**을 받는다. 원문이 사라지지 않는다."""
    out = _detail(repository.get(KO_CARD), repository)
    assert "카드 텍스트(한국어)" in out
    assert "카드 텍스트(원문)" in out
    card = repository.get(KO_CARD)
    assert card.desc[:15] in out and card.desc_en[:15] in out


# ===========================================================================
# C. N52 — 오버레이 적용 여부
# ===========================================================================
@requires_official_db
def test_14_korean_available_implies_the_overlay_was_applied(repository):
    r"""🟢 N52 — ``korean_available`` ⟹ 오버레이 적용. 전수로 확인한다.

    ``name_ko`` 를 쓰는 곳이 ``apply`` 하나뿐이라서 성립한다 (`test_02`).
    """
    violations = [
        card.id for card in repository.all_cards()
        if card.provenance.availability.korean_available
        and CardSource.KOREAN_OVERLAY not in card.sources
    ]
    assert violations == []


def test_15_the_converse_gap_is_structurally_possible():
    r"""🟠 N52 — **역방향은 보장되지 않는다.** 오버레이가 닿았는데
    ``korean_available`` 이 거짓인 카드가 구조적으로 가능하다 (이름 없는 항목).

    🔴 가상 사례다 — 실제 데이터에 그런 항목은 0개다 (`test_11`).
    """
    card = Card(id=7, name="원문만", desc="original")
    source = KoreanTextSource({7: {"name": "", "desc": "한국어 텍스트"}})
    applied = source.apply({7: card})
    assert applied == 1
    assert CardSource.KOREAN_OVERLAY in card.sources      # 적용됐다
    assert card.name_ko in (None, "")                     # 그런데 이름은 없다
    CardRepository._record_provenance({7: card})
    assert card.provenance.availability.korean_available is False
    #: 텍스트는 실제로 교체됐다 — 적용 사실과 플래그가 어긋난다
    assert card.desc == "한국어 텍스트"
    assert card.desc_en == "original"


def test_16_that_card_would_get_the_wrong_text_label():
    r"""🟠 N52 + N51 — 위 사례에서는 **한국어 텍스트에 "한국어" 라벨이 빠진다**.

    두 위험이 같은 자리에서 만난다. 🔴 가상 사례이고 실제 데이터에는 없다.
    """
    card = Card(id=7, name="원문만", desc="original")
    card.type_mask = C.TYPE_SPELL
    KoreanTextSource({7: {"name": "", "desc": "한국어 텍스트"}}).apply({7: card})
    out = _detail(card)
    assert _text_label(out) == "카드 텍스트"        # (한국어) 가 없다
    assert "한국어 텍스트" in out                    # 내용은 한국어다


@requires_official_db
def test_17_with_the_overlay_off_every_signal_is_zero():
    r"""🟢 N52 — 오버레이를 끄면 네 신호가 **모두 0**이다. 어긋나지 않는다."""
    cards = CardRepository.build(use_korean=False).all_cards()
    assert sum(1 for c in cards if CardSource.KOREAN_OVERLAY in c.sources) == 0
    assert sum(1 for c in cards if c.name_ko) == 0
    assert sum(1 for c in cards
               if c.provenance.availability.korean_available) == 0
    assert sum(1 for c in cards
               if c.desc and c.desc_en and c.desc != c.desc_en) == 0


@requires_official_db
def test_18_the_off_output_claims_no_language_it_cannot_prove():
    r"""🔴 N52 / §5 — 오버레이 OFF 출력은 **거짓을 말하지 않는다**.

    "카드 텍스트" 라고만 적고 언어를 주장하지 않으며, 한국어 이름 행도 없다.
    빠진 것은 "한국어 데이터가 있는데 적용되지 않았다" 는 **설명**이고,
    그것은 거짓 표시가 아니라 **미표시**다 — 그래서 고치지 않았다.
    """
    off_repo = CardRepository.build(use_korean=False)
    out = _detail(off_repo.get(KO_CARD), off_repo)
    assert _text_label(out) == "카드 텍스트"
    rows = _name_rows(out)
    assert "한국어" not in rows
    assert "한국어" not in out.replace("카드 텍스트", "")
    #: 적용 안 됐다는 사실을 말해 주지도 않는다 (미표시)
    assert "적용" not in out


def test_19_the_overlay_counts_what_it_applied():
    r"""🟢 N52 — ``apply`` 의 반환값이 **닿은 카드 수**다 (적용의 척도)."""
    cards = {1: Card(id=1, name="a"), 2: Card(id=2, name="b")}
    source = KoreanTextSource({
        1: {"name": "가", "desc": "텍스트"},
        3: {"name": "없는 카드", "desc": "텍스트"},
    })
    assert source.apply(cards) == 1
    assert CardSource.KOREAN_OVERLAY in cards[1].sources
    assert CardSource.KOREAN_OVERLAY not in cards[2].sources


@requires_official_db
@requires_korean_data
def test_20_entries_that_match_no_card_are_silently_dropped(repository):
    r"""🟠 N52 — `data/ko` 항목 중 **171개**가 카드에 닿지 않고 조용히 버려진다.

    어디에도 보고되지 않는다 — 위험으로 기록만 한다.
    """
    source = KoreanTextSource.autoload()
    assert source is not None
    present = {c.id for c in repository.all_cards()}
    unmatched = set(source.entries) - present
    assert len(source.entries) == KO_ENTRIES
    assert len(unmatched) == KO_ENTRIES_UNMATCHED
    assert len(set(source.entries) & present) == KOREAN_CARDS


# ===========================================================================
# D. §4 — 여섯 사례
# ===========================================================================
@requires_official_db
def test_21_case1_korean_name_with_korean_text(repository):
    r"""🟢 §4 ① — 실제 **13,728장**. 라벨·행이 모두 맞는다."""
    matching = [
        c for c in repository.all_cards()
        if c.name_ko and c.desc and c.desc_en and c.desc != c.desc_en
    ]
    assert len(matching) == KOREAN_CARDS
    out = _detail(matching[0], repository)
    assert _text_label(out) == "카드 텍스트(한국어)"


@requires_official_db
def test_22_case2_korean_name_with_foreign_text_does_not_exist(repository):
    r"""🟢 §4 ② — 실제 카드 **0장** (가상 사례는 `test_09`)."""
    assert [
        c.id for c in repository.all_cards()
        if c.name_ko and c.desc and c.desc_en and c.desc == c.desc_en
    ] == []


@requires_official_db
@requires_korean_data
def test_23_case3_korean_data_exists_but_was_not_applied(repository):
    r"""🔴 §4 ③ — 디스크에 한국어가 있는데 적용되지 않은 상태를 재현한다.

    CLI 플래그로는 닿을 수 없고(3-F-42), 프로그램이 ``use_korean=False`` 를
    넘길 때만 생긴다. 출력은 원문이고 **거짓 주장이 없다**.
    """
    source = KoreanTextSource.autoload()
    assert source is not None
    assert KO_CARD in source.entries            # 데이터는 디스크에 있다
    off_repo = CardRepository.build(use_korean=False)
    card = off_repo.get(KO_CARD)
    assert card.name_ko in (None, "")
    assert CardSource.KOREAN_OVERLAY not in card.sources
    out = _detail(card, off_repo)
    assert card.desc_en[:15] in out or card.desc[:15] in out
    assert _text_label(out) == "카드 텍스트"


@requires_official_db
def test_24_case4_no_korean_data_at_all(repository):
    r"""🟢 §4 ④ — 실제 **399장**. 한국어 행도 라벨도 없다."""
    matching = [c for c in repository.all_cards() if not c.name_ko]
    assert len(matching) == NO_KOREAN_CARDS
    out = _detail(matching[0], repository)
    assert "한국어" not in _name_rows(out)
    assert _text_label(out) in ("카드 텍스트", None)


@requires_official_db
def test_25_case5_undecidable_text_language_does_not_occur(repository):
    r"""🟢 §4 ⑤ — "원문과 비교할 수 없어 판단 불가" 인 카드가 **0장**이다.

    ``desc`` 가 있는데 ``desc_en`` 이 없는 카드가 없다 — ``apply`` 가 원문을
    ``desc_en`` 으로 옮겨 두기 때문이다.
    """
    undecidable = [c.id for c in repository.all_cards() if c.desc and not c.desc_en]
    assert undecidable == []


@requires_official_db
def test_26_case6_a_card_without_a_name_does_not_occur(repository):
    r"""🟢 §4 ⑥ — 이름이 아예 없는 카드가 **0장**이다.

    그래도 ``display_name`` 은 ``#id`` 로 떨어지게 되어 있다 (`test_05`).
    """
    nameless = [c.id for c in repository.all_cards()
                if not (c.name_ko or c.name or c.name_ja)]
    assert nameless == []


# ===========================================================================
# E. provenance 보존 · 결정성 · 회귀
# ===========================================================================
@requires_official_db
def test_27_the_effect_text_source_is_recorded_from_the_name(repository):
    r"""🟠 N52 — ``effect_text`` 의 출처가 **이름을 근거로** 한국어 DB 로
    적힌다. 실제 데이터에서는 맞지만 근거가 텍스트가 아니다.

    사용자에게는 보이지 않는다 (``fields{}`` 는 어떤 화면에도 안 나온다 —
    3-F-41 의 N48). 그래서 거짓 표시가 아니고, 고치지 않았다.
    """
    card = repository.get(KO_CARD)
    assert card.provenance.source_of("effect_text") is SourceKind.KOREAN_DB
    assert card.provenance.source_of("card_name") is SourceKind.KOREAN_DB
    out = _detail(card, repository)
    #: 필드별 출처는 출력에 없다
    assert "effect_text" not in out and "korean_db" not in out


@requires_official_db
def test_28_the_status_distribution_is_unchanged(repository):
    r"""🟢 §7 — ``AnalysisStatus`` 분포와 카드 수가 그대로다."""
    status = collections.Counter(
        c.provenance.analysis_status.value for c in repository.all_cards())
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CARD_TOTAL


@requires_official_db
def test_29_the_availability_flag_counts_are_unchanged(repository):
    r"""🟢 §7 — availability 플래그별 카드 수가 그대로다."""
    counts: collections.Counter = collections.Counter()
    for card in repository.all_cards():
        availability = card.provenance.availability
        for name in ("cdb_available", "official_text_available",
                     "korean_available", "lua_available",
                     "effect_analysis_available", "text_analysis_available"):
            if getattr(availability, name):
                counts[name] += 1
    assert counts["korean_available"] == KOREAN_CARDS
    assert counts["lua_available"] == counts["effect_analysis_available"] == 12687
    assert counts["text_analysis_available"] == STATUS_COUNTS["text_derived"]
    assert counts["cdb_available"] == counts["official_text_available"] == 14121


@requires_official_db
def test_30_the_detail_output_is_deterministic(repository):
    r"""🟢 §6 — 같은 카드를 두 번 찍으면 **글자 단위로** 같다."""
    for card_id in (KO_CARD, NO_KO_CARD, LUA_KO_CARD):
        card = repository.get(card_id)
        assert _detail(card, repository) == _detail(card, repository)


@requires_official_db
def test_31_detail_and_search_agree_on_the_displayed_name(repository):
    r"""🟢 §6 — 상세의 머리글과 검색 줄이 **같은 이름**을 쓴다."""
    for card_id in (KO_CARD, NO_KO_CARD, LUA_KO_CARD):
        card = repository.get(card_id)
        line = main_module.format_card_line(card)
        detail = _detail(card, repository)
        assert card.display_name() in line
        assert card.display_name() in detail.splitlines()[1]


@requires_official_db
def test_32_analysis_and_binding_totals_are_unchanged(repository):
    r"""🟢 §7 — 효과 블록 수·분석 집계·결합 분포가 그대로다.

    🔴 digest 리터럴을 쓰지 않는다 — 집계로 못 박는다 (파일 머리말 참고).
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
    assert dict(blocks) == {HandlerBinding.MATCHED: ATTACHED_BLOCKS}


@requires_official_db
def test_33_search_and_effect_refs_are_unchanged(repository):
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


# ===========================================================================
# F. §5 / §9 — 범위와 금지
# ===========================================================================
def test_34_this_phase_changed_no_production_file():
    r"""🔴 §5 — **production 을 한 줄도 바꾸지 않았다.**

    N51 의 트리거는 결과 카드 0장·원천 데이터 0항목이고, N52 는 거짓 표시가
    아니라 미표시다. 둘 다 "사용자에게 잘못된 정보" 의 재현 사례가 없다.
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
        "tests/test_card_detail_provenance_display_audit.py",
        "docs/phase3f43-card-detail-provenance-display-audit.md",
    }, changed


def test_36_no_forbidden_path_was_touched():
    r"""🔴 §1 금지 — Lua · README · engine · agent · core · data 전부 0건."""
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
    r"""🔴 §6 — 기존 테스트 **수정·삭제 0건**.

    🔴 Phase 3-F-42 는 새 테스트 파일이 기존 지뢰선을 건드려 한 건을 고쳐야
    했다. 이번에는 **작업 전에 지뢰선을 먼저 조사했다**: 64자 16진수 digest
    리터럴을 쓰지 않고(핀 개수 7을 세는 테스트가 있다),
    ``TextEffectAnalyzer`` 를 호출하지 않는다(호출자 목록을 세는 테스트가
    있다). 그래서 기존 테스트를 건드리지 않았다.
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
    assert {p for p in _changed_files() if p in before} == set()


def test_38_this_file_writes_no_digest_literal():
    r"""🔴 이 파일이 64자 16진수 리터럴을 **쓰지 않는다**는 것을 스스로 지킨다.

    다른 감사 파일들이 "가장 많이 못 박힌 digest" 와 "핀 개수" 를 세므로,
    여기 digest 를 적으면 그 테스트들이 깨진다 (3-F-42 가 겪은 종류의 사고).
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    hexes = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and len(node.value) == 64
        and all(ch in "0123456789abcdef" for ch in node.value)
    ]
    assert hexes == [], hexes
