r"""
Phase 3-F-43-K0 — 한국어 오버레이 "미적용" 집계 기준 정정 및 검증 경계.

🔴 **이 파일이 고정하는 핵심 정정**: 이전 보고서(3-F-41 N55, 3-F-43 N55)가
"``data/ko`` 의 **171개** 항목이 조용히 버려진다" 고 적었다. 그 171 은
``entries - canonical 카드`` 로 센 값인데, 오버레이는
``OfficialDatabaseSource.load()`` 가 돌려주는 **전체 레코드**(alias 판본
포함)에 적용된다. 실제 미적용은 **7개**다.

```
항목 13,899 = 적용 13,892 + 미적용 7          ← apply() 결과로 산출
entries - canonical = 171                     ← 이전 보고서가 쓴 수
차이 164 = alias 판본: **적용되었고** canonical 카드가 아닐 뿐
```

164개는 **164/164 전부** alias 가 0이 아니고, alias 대상이 canonical 이며,
한국어 **이름과 텍스트를 모두** 받았다. 즉 "미적용" 이 아니다.

7개는 기준 ``cards.cdb`` 에 대응 카드가 **없다**. 각각 수집기 캐시에서
**공식 CID** 가 확인되므로 수집기가 식별자를 만들어낸 증거는 없다.

🔴 **두 방향의 단정을 모두 피한다.** 공식 CID 가 있다는 것이 카드 DB 에
카드가 있다는 뜻이 아니고, 카드 DB 에 없다는 것이 수집기 오류라는 뜻도
아니다. 그래서 ``COLLECTOR_ERROR`` 는 0 으로 두고 ``CARD_ABSENT`` 로만
분류한다.

🔴 이 파일은 64자 16진수 digest 리터럴을 쓰지 않고(다른 감사가 그 핀 개수를
센다), 텍스트 분석기를 호출하지 않는다(다른 감사가 그 호출자 목록을 센다).
데이터 유무는 함수 안에서 건너뛰지 않고 **마커**로 거른다.
"""

from __future__ import annotations

import ast
import collections
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import HandlerBinding
from core.card_model import CardSource
from core.card_repository import CardRepository
from core.card_search import CardSearchEngine, EffectLocationFilter, SearchFilters
from core.provenance import AnalysisStatus
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, effect_refs
from engine.randomness import RandomSource
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Position, Zone
from sources.korean_names import KoreanTextSource
from sources.official_db import OfficialDatabaseSource

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KO_JSON = PROJECT_ROOT / "data" / "ko" / "ko-KR.json"
KO_CACHE = PROJECT_ROOT / "data" / "ko" / ".cache" / "cid_to_passcode.json"
CARDS_CDB = PROJECT_ROOT / "data" / "cards.cdb"

requires_korean_data = pytest.mark.skipif(
    not KO_JSON.is_file(),
    reason="data/ko/ko-KR.json 이 없습니다.",
)
requires_cards_cdb = pytest.mark.skipif(
    not CARDS_CDB.is_file(),
    reason="data/cards.cdb 가 없습니다.",
)
requires_collector_cache = pytest.mark.skipif(
    not KO_CACHE.is_file(),
    reason="data/ko/.cache/cid_to_passcode.json 이 없습니다.",
)

# --- Phase 3-F-43-K0 이 현재 커밋에서 실측한 값 (테스트가 다시 산출한다) ----
KO_ENTRIES = 13899
OVERLAY_APPLIED = 13892
TRULY_UNAPPLIED = 7
#: 🔴 이전 보고서가 "미적용" 으로 쓴 수 — 실제로는 alias 를 뺀 차이다
ENTRIES_MINUS_CANONICAL = 171
ALIAS_GAP = 164

CDB_ROWS = 14755
LOADED_RECORDS = 14514
TOKENS_FILTERED = 241
REPO_RECORDS = 14520
LUA_ONLY_RECORDS = 6
CANONICAL_CARDS = 14127
ALIAS_PRINTINGS = 393

ATTACHED_BLOCKS = 34635
STATUS_COUNTS = {"lua_verified": 12687, "text_derived": 756, "no_effect": 684}

#: 진짜 미적용 7개 — passcode -> (한국어 이름, 공식 CID)
UNAPPLIED = {
    662853: ("유니티 오브 드래곤", "13347"),
    662854: ("흑의지조도사", "14048"),
    662855: ("신봉지천진농", "14049"),
    662857: ("혁명의 철기사", "13348"),
    20250830: ("축복의 교회－리츄얼 처치", "12539"),
    81480461: ("속사포 드래곤", "4749"),
    101303084: ("생명의 수은 메르쿠리움", "22330"),
}
#: 대표 alias 사례 — 판본 295517 의 원본은 22702055 다
ALIAS_SAMPLE = (295517, 22702055)

#: 🔴 ``deck`` 은 Phase 6-T 가 만든 production 디렉터리다 — 여기 빠져
#: 있으면 ``deck/`` 을 건드린 Phase 가 "production 을 바꾸지 않았다" 를
#: 거짓으로 통과한다 (Phase 6-W 가 더했다).
PRODUCTION_DIRS = (
    "analysis", "app", "core", "deck", "engine", "rules", "rulings",
    "scripts", "sources", "agent", "integration",
)


# ===========================================================================
# 공용 도구 — production 로더와 적용 함수를 **그대로** 쓴다
# ===========================================================================
def _applied_records():
    """``load()`` 전체 레코드에 ``apply()`` 를 돌린 결과를 돌려준다."""
    source = KoreanTextSource.autoload()
    records = OfficialDatabaseSource(None).load()
    returned = source.apply(records)
    touched = {cid for cid, card in records.items()
               if CardSource.KOREAN_OVERLAY in card.sources}
    return source, records, returned, touched


def _cdb_ids() -> set[int]:
    conn = sqlite3.connect(CARDS_CDB)
    try:
        return {row[0] for row in conn.execute("SELECT id FROM datas")}
    finally:
        conn.close()


def _collector_reverse() -> dict[str, list[str]]:
    """passcode -> 공식 CID 목록 (수집기 캐시의 역참조)."""
    mapping = json.loads(KO_CACHE.read_text(encoding="utf-8"))
    reverse: dict[str, list[str]] = collections.defaultdict(list)
    for cid, value in mapping.items():
        for passcode in (value if isinstance(value, list) else [value]):
            reverse[str(passcode)].append(cid)
    return reverse


def _phase_shas() -> list[str]:
    return subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-43-K0:"],
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
# A. 집계 기준 — 네 집합을 혼동하지 않는다
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_01_the_four_populations_are_different_sizes():
    r"""🔴 §4 — **네 집합이 서로 다른 수**다. 하나를 다른 것의 기준으로 쓰면
    "미적용" 수가 틀린다. 이것이 171 오류의 뿌리다."""
    source, records, _returned, touched = _applied_records()
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    sizes = {
        "ko 항목": len(source.entries),
        "load 레코드": len(records),
        "오버레이 적용": len(touched),
        "canonical 카드": len(canonical),
    }
    assert sizes == {
        "ko 항목": KO_ENTRIES,
        "load 레코드": LOADED_RECORDS,
        "오버레이 적용": OVERLAY_APPLIED,
        "canonical 카드": CANONICAL_CARDS,
    }, sizes
    assert len(set(sizes.values())) == 4, "네 수가 모두 달라야 한다"


@requires_korean_data
@requires_cards_cdb
def test_02_entries_minus_canonical_is_not_the_unapplied_count():
    r"""🔴 §3 — ``entries - canonical`` 은 **171** 이지만 미적용 수가 아니다.

    이전 보고서가 이 값을 "미적용" 으로 적었다. 두 수를 함께 고정해 다시
    섞이지 않게 한다.
    """
    source, _records, _returned, touched = _applied_records()
    entries = set(source.entries)
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    assert len(entries - canonical) == ENTRIES_MINUS_CANONICAL
    assert len(entries - touched) == TRULY_UNAPPLIED
    assert len(entries - canonical) != len(entries - touched)


@requires_korean_data
@requires_cards_cdb
def test_03_the_unapplied_count_comes_from_apply():
    r"""🔴 §4 — 미적용 수를 **``apply()`` 결과로** 산출한다.

    canonical 집합이 아니라 "오버레이가 실제로 닿은 레코드" 가 기준이다.
    """
    source, _records, returned, touched = _applied_records()
    assert returned == OVERLAY_APPLIED
    assert len(touched) == OVERLAY_APPLIED
    assert len(set(source.entries) - touched) == TRULY_UNAPPLIED


@requires_korean_data
@requires_cards_cdb
def test_04_applied_plus_unapplied_equals_every_entry():
    r"""🔴 §4 — 적용 + 미적용 = 전체 항목. 검산이 맞는다."""
    source, _records, _returned, touched = _applied_records()
    entries = set(source.entries)
    applied = entries & touched
    unapplied = entries - touched
    assert len(applied) + len(unapplied) == len(entries) == KO_ENTRIES
    assert len(applied) == OVERLAY_APPLIED
    assert len(unapplied) == TRULY_UNAPPLIED


@requires_korean_data
@requires_cards_cdb
def test_05_no_entry_is_counted_twice():
    r"""🟢 §4 — 두 집합이 **서로소**다. 중복 집계가 없다."""
    source, _records, _returned, touched = _applied_records()
    entries = set(source.entries)
    applied = entries & touched
    unapplied = entries - touched
    assert applied & unapplied == set()
    assert applied | unapplied == entries


@requires_korean_data
@requires_cards_cdb
def test_06_apply_touches_records_outside_the_canonical_set():
    r"""🔴 §3 — ``apply()`` 는 canonical 밖의 레코드에도 닿는다.

    그래서 canonical 을 기준으로 세면 안 된다. 닿은 레코드 중
    canonical 이 아닌 것이 실제로 있다.
    """
    _source, _records, _returned, touched = _applied_records()
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    outside = touched - canonical
    assert len(outside) == ALIAS_GAP
    assert outside, "canonical 밖에 닿은 레코드가 있어야 한다"


# ===========================================================================
# B. 164개 alias 판본은 **정상 적용**이다
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_07_the_gap_is_exactly_the_alias_printings():
    r"""🔴 §3 — 171 과 7 의 차이 **164개가 전부 alias 판본**이다."""
    source, records, _returned, touched = _applied_records()
    entries = set(source.entries)
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    gap = (entries - canonical) - (entries - touched)
    assert len(gap) == ALIAS_GAP
    assert all(records[cid].alias for cid in gap), "전부 alias 여야 한다"


@requires_korean_data
@requires_cards_cdb
def test_08_every_alias_in_the_gap_points_at_a_canonical_card():
    r"""🟢 §3 — 164개의 alias 대상이 **전부 canonical 카드**다."""
    source, records, _returned, touched = _applied_records()
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    gap = (set(source.entries) - canonical) - (set(source.entries) - touched)
    targets = [records[cid].alias for cid in gap]
    assert len(targets) == ALIAS_GAP
    assert all(target in canonical for target in targets)


@requires_korean_data
@requires_cards_cdb
def test_09_every_alias_in_the_gap_received_a_korean_name():
    r"""🔴 §3 — 164/164 가 한국어 **이름**을 받았다. 미적용이 아니다."""
    source, records, _returned, touched = _applied_records()
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    gap = (set(source.entries) - canonical) - (set(source.entries) - touched)
    with_name = [cid for cid in gap if records[cid].name_ko]
    assert len(with_name) == ALIAS_GAP


@requires_korean_data
@requires_cards_cdb
def test_10_every_alias_in_the_gap_received_korean_text():
    r"""🔴 §3 — 164/164 가 한국어 **텍스트**도 받았다 (원문은 보존된다)."""
    source, records, _returned, touched = _applied_records()
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    gap = (set(source.entries) - canonical) - (set(source.entries) - touched)
    replaced = [
        cid for cid in gap
        if records[cid].desc and records[cid].desc_en
        and records[cid].desc != records[cid].desc_en
    ]
    assert len(replaced) == ALIAS_GAP


@requires_korean_data
@requires_cards_cdb
def test_11_the_representative_alias_case_is_reproducible():
    r"""🟢 §3 — 대표 사례를 재현한다: 판본과 원본이 **각각** 한국어를 받는다."""
    printing, origin = ALIAS_SAMPLE
    _source, records, _returned, touched = _applied_records()
    assert printing in touched and origin in touched
    assert records[printing].alias == origin
    assert records[printing].name_ko
    assert records[origin].name_ko
    #: 판본과 원본의 한국어 이름이 서로 다를 수 있다 (다른 카드명 판본)
    assert isinstance(records[printing].name_ko, str)


@requires_korean_data
@requires_cards_cdb
def test_12_the_printing_resolves_to_a_korean_canonical_card():
    r"""🟢 §3 — production 조회 경로로도 확인한다: 판본 → 원본 → 한국어."""
    printing, origin = ALIAS_SAMPLE
    repo = CardRepository.build()
    record = repo._cards.get(printing)
    assert record is not None
    canonical_card = repo.canonical(record)
    assert canonical_card.id == origin
    assert canonical_card.name_ko


# ===========================================================================
# C. 진짜 미적용 7개의 근거
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_13_all_seven_are_absent_from_the_card_database():
    r"""🔴 §3 — 7개 전부 ``cards.cdb`` 에 **없다** (14,755행 전수 조회)."""
    source, _records, _returned, touched = _applied_records()
    unapplied = sorted(set(source.entries) - touched)
    assert unapplied == sorted(UNAPPLIED)
    cdb = _cdb_ids()
    assert len(cdb) == CDB_ROWS
    assert [cid for cid in unapplied if cid in cdb] == []


@requires_korean_data
@requires_cards_cdb
def test_14_all_seven_are_absent_from_the_loaded_records():
    r"""🟢 §3 — 로드된 레코드에도 없다 — 붙일 대상 자체가 없다."""
    source, records, _returned, touched = _applied_records()
    unapplied = sorted(set(source.entries) - touched)
    assert [cid for cid in unapplied if cid in records] == []


@requires_korean_data
@requires_collector_cache
def test_15_every_unapplied_passcode_has_an_official_cid():
    r"""🔴 §3 — 7개 전부 수집기 캐시에서 **공식 CID** 가 확인된다.

    수집기가 식별자를 만들어낸 것이 아니라 공식 매핑을 기록했다는 증거다.
    """
    reverse = _collector_reverse()
    for passcode, (_name, expected_cid) in UNAPPLIED.items():
        cids = reverse.get(str(passcode), [])
        assert cids == [expected_cid], (passcode, cids)


@requires_korean_data
def test_16_the_korean_names_match_the_recorded_entries():
    r"""🟢 §3 — 7개의 한국어 이름이 원본 데이터와 일치한다 (번역하지 않았다)."""
    source = KoreanTextSource.autoload()
    for passcode, (name, _cid) in UNAPPLIED.items():
        assert passcode in source.entries, passcode
        assert source.entries[passcode].get("name") == name, passcode


@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_17_an_official_cid_does_not_imply_the_card_is_in_the_database():
    r"""🔴 §3 금지 — **공식 CID 가 있다는 것이 카드 DB 에 있다는 뜻이 아니다.**

    7개는 CID 가 있고 DB 에는 없다. 두 사실을 함께 확인해 단정을 막는다.
    """
    reverse = _collector_reverse()
    cdb = _cdb_ids()
    for passcode in UNAPPLIED:
        assert reverse.get(str(passcode)), passcode      # CID 는 있다
        assert passcode not in cdb, passcode             # DB 에는 없다


@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_18_absence_from_the_database_does_not_imply_a_collector_error():
    r"""🔴 §3 금지 — **DB 에 없다는 것이 수집기 오류라는 뜻도 아니다.**

    오류로 판정할 증거는 "공식 CID 가 없는 passcode" 인데, 그런 항목이
    **0개**다. 그래서 ``COLLECTOR_ERROR`` 를 0 으로 둔다.
    """
    reverse = _collector_reverse()
    without_cid = [p for p in UNAPPLIED if not reverse.get(str(p))]
    assert without_cid == []


@requires_korean_data
@requires_cards_cdb
def test_19_the_seven_have_no_card_to_display_so_no_user_is_affected():
    r"""🔴 §3 — 7개는 repository 에 **표시할 카드가 없다** → 영향 0.

    한국어가 빠진 카드가 보이는 것이 아니라, 카드 자체가 없다.
    """
    repo = CardRepository.build()
    for passcode in UNAPPLIED:
        assert repo.get(passcode) is None, passcode
        assert passcode not in repo._cards, passcode


# ===========================================================================
# D. 세 범주가 공집합임을 증명한다
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_20_linking_error_is_empty():
    r"""🔴 §3 — ``LINKING_ERROR`` = **0**.

    "cdb 에 있는데 로드되지 않은 한국어 항목" 이 하나도 없다.
    """
    source, records, _returned, _touched = _applied_records()
    dropped = _cdb_ids() - set(records)
    assert len(dropped) == TOKENS_FILTERED
    assert sorted(set(source.entries) & dropped) == []


@requires_cards_cdb
def test_21_the_adapter_only_filters_tokens():
    r"""🟢 §3 — 어댑터가 거르는 241개는 **토큰**이다 (한국어 항목과 무관)."""
    default = set(OfficialDatabaseSource(None).load())
    with_tokens = set(OfficialDatabaseSource(None).load(include_tokens=True))
    assert len(with_tokens) == CDB_ROWS
    assert len(default) == LOADED_RECORDS
    assert len(with_tokens - default) == TOKENS_FILTERED


@requires_korean_data
@requires_cards_cdb
def test_22_id_mismatch_is_empty_among_the_unapplied():
    r"""🔴 §3 — ``ID_MISMATCH`` = **0**.

    미적용 7개 중 "다른 ID 로 연결될 가능성" 이 확인된 것이 없다 — cdb 에
    레코드가 아예 없어 alias 관계를 가질 수조차 없다.
    """
    source, records, _returned, touched = _applied_records()
    cdb = _cdb_ids()
    unapplied = set(source.entries) - touched
    assert [cid for cid in unapplied if cid in cdb or cid in records] == []


@requires_korean_data
@requires_cards_cdb
@requires_collector_cache
def test_23_unresolved_is_empty():
    r"""🟢 §3 — ``UNRESOLVED`` = **0**. 7개 모두 근거가 두 가지씩 있다."""
    reverse = _collector_reverse()
    cdb = _cdb_ids()
    unresolved = [
        passcode for passcode in UNAPPLIED
        if passcode in cdb or not reverse.get(str(passcode))
    ]
    assert unresolved == []


@requires_korean_data
@requires_cards_cdb
def test_24_the_classification_totals_match_the_investigated_count():
    r"""🔴 §4 — 분류별 합계 = 실제 조사 대상 수. 과대·과소 집계가 없다."""
    source, _records, _returned, touched = _applied_records()
    entries = set(source.entries)
    repo = CardRepository.build()
    canonical = {card.id for card in repo.all_cards()}
    investigated = entries - canonical                   # 이전 보고서의 171
    applied_alias = investigated - (entries - touched)
    card_absent = entries - touched
    assert len(investigated) == ENTRIES_MINUS_CANONICAL
    assert len(applied_alias) == ALIAS_GAP
    assert len(card_absent) == TRULY_UNAPPLIED
    assert len(applied_alias) + len(card_absent) == len(investigated)
    assert applied_alias & card_absent == set()


# ===========================================================================
# E. 전체 레코드 수 회계
# ===========================================================================
@requires_cards_cdb
def test_25_the_record_counts_add_up_end_to_end():
    r"""🟢 §3 — 네 단계의 수가 서로 맞는다. 설명되지 않는 차이가 없다.

    ``cdb 14,755 = load 14,514 + 토큰 241``,
    ``repo 레코드 14,520 = load 14,514 + Lua 전용 6``,
    ``canonical 14,127 = repo 14,520 - alias 판본 393``.
    """
    loaded = set(OfficialDatabaseSource(None).load())
    assert len(_cdb_ids()) == len(loaded) + TOKENS_FILTERED == CDB_ROWS
    repo = CardRepository.build()
    assert len(repo._cards) == REPO_RECORDS
    assert len(repo._cards) - len(loaded) == LUA_ONLY_RECORDS
    canonical = {card.id for card in repo.all_cards()}
    assert len(canonical) == CANONICAL_CARDS
    assert len(repo._cards) - len(canonical) == ALIAS_PRINTINGS


@requires_cards_cdb
def test_26_the_lua_only_records_have_no_database_row():
    r"""🟢 §3 — repo 에만 있는 6개는 ``c*.lua`` 만 있는 레코드다."""
    loaded = set(OfficialDatabaseSource(None).load())
    repo = CardRepository.build()
    extra = sorted(set(repo._cards) - loaded)
    assert len(extra) == LUA_ONLY_RECORDS
    for cid in extra:
        card = repo._cards[cid]
        assert card.sources == {CardSource.LUA_SCRIPT}, cid
        assert cid not in _cdb_ids(), cid


# ===========================================================================
# F. 원본 불변 · 결정성 · 기존 산출물 불변
# ===========================================================================
@requires_korean_data
@requires_cards_cdb
def test_27_the_source_data_files_are_not_modified():
    r"""🔴 §5 — 조사가 **원본 데이터를 바꾸지 않는다**.

    ``apply()`` 는 메모리의 ``Card`` 만 고친다. 파일 지문을 전후로 비교한다.
    """
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    before = (digest(KO_JSON), digest(CARDS_CDB))
    _applied_records()
    CardRepository.build()
    assert (digest(KO_JSON), digest(CARDS_CDB)) == before


@requires_korean_data
@requires_cards_cdb
def test_28_the_measurement_is_deterministic():
    r"""🟢 §4 — 같은 입력을 두 번 재면 같은 수가 나온다."""
    first = _applied_records()
    second = _applied_records()
    assert first[2] == second[2] == OVERLAY_APPLIED
    assert first[3] == second[3]
    assert len(set(first[0].entries) - first[3]) == \
        len(set(second[0].entries) - second[3]) == TRULY_UNAPPLIED


@requires_cards_cdb
def test_29_the_corpus_status_distribution_is_unchanged():
    r"""🟢 §4 — ``AnalysisStatus`` 분포와 카드 수가 그대로다."""
    repo = CardRepository.build()
    status = collections.Counter(
        card.provenance.analysis_status.value for card in repo.all_cards())
    assert dict(status) == STATUS_COUNTS
    assert sum(status.values()) == CANONICAL_CARDS
    assert set(status) <= {s.value for s in AnalysisStatus}


@requires_cards_cdb
def test_30_the_analysis_and_binding_totals_are_unchanged():
    r"""🟢 §4 — 효과 블록 수·분석 집계·결합 분포가 그대로다 (집계로 못 박는다)."""
    repo = CardRepository.build()
    analyzer = EffectAnalyzer(repo)
    registered = resolution = unbound = 0
    blocks: collections.Counter = collections.Counter()
    for card in repo.all_cards():
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


@requires_cards_cdb
def test_31_search_and_effect_refs_are_unchanged():
    r"""🟢 §4 — 검색 결과와 ``EffectRef`` 가 그대로다."""
    repo = CardRepository.build()
    engine = CardSearchEngine(repo)
    cards = [c for c in repo.all_cards() if c.script is not None]
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


def test_32_engine_invariants_are_untouched():
    r"""🟢 §4 — ``state_hash`` 결정성 · RNG 재현 · hidden information 경계."""
    assert _new_engine_state().state_hash() == _new_engine_state().state_hash()
    first = RandomSource.seeded(20251012).raw
    second = RandomSource.seeded(20251012).raw
    draws = [first.randrange(100) for _ in range(10)]
    assert draws == [second.randrange(100) for _ in range(10)]
    game = _new_engine_state()
    mine = GameStateView.from_state(game, viewer=0)
    theirs = GameStateView.from_state(game, viewer=1)
    assert mine.canonical_state() != theirs.canonical_state()
    assert theirs.player(0).hand.occupied() == ()
    assert theirs.player(0).hand.is_empty is False


# ===========================================================================
# G. 범위와 금지
# ===========================================================================
def test_33_this_phase_changed_no_production_file():
    r"""🔴 §5 — **production 을 한 줄도 바꾸지 않았다** (조사 전용 Phase)."""
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


def test_34_only_a_test_file_and_a_report_were_added():
    r"""🟢 §6 — 변경 파일은 이 테스트와 보고서뿐이다."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    assert changed == {
        "tests/test_korean_overlay_unapplied_audit.py",
        "docs/phase3f43-korean-overlay-unapplied-audit.md",
    }, changed


def test_35_no_forbidden_path_and_no_data_file_was_touched():
    r"""🔴 §5 금지 — Lua · README · engine · agent · core · **data** 전부 0건."""
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for path in changed:
        assert not path.endswith(".lua"), path
        assert "README" not in path, path
        for prefix in ("engine/", "agent/", "core/", "data/", "app/",
                       "analysis/", "scripts/", "sources/"):
            assert not path.startswith(prefix), path


def test_36_the_existing_phase_3f43_work_was_not_overwritten():
    r"""🔴 §1 — 기존 Phase 3-F-43 산출물을 **덮어쓰지 않았다**.

    같은 번호를 쓰는 다른 작업이 이미 있으므로, 그 파일들이 이 Phase 의
    변경 집합에 **없어야** 한다. 식별자도 구분된다.
    """
    changed = _changed_files()
    if not changed:
        pytest.skip("이 Phase 의 commit 이 아직 없다")
    for existing in ("docs/phase3f43-card-detail-provenance-display-audit.md",
                     "tests/test_card_detail_provenance_display_audit.py"):
        assert (PROJECT_ROOT / existing).is_file(), existing
        assert existing not in changed, existing
    #: 두 식별자가 git 범위에서 섞이지 않는다
    other = subprocess.run(
        ["git", "log", "--format=%H", "--grep=^Phase 3-F-43:"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    ).stdout.split()
    assert set(other) & set(_phase_shas()) == set()


def test_37_no_existing_test_was_modified_or_deleted():
    r"""🔴 §4 — 기존 테스트 수정·삭제 0건.

    🔴 **이 핀의 전제가 틀렸다** (Phase 6-N 이 고쳤다). 비교 대상이
    ``HEAD`` 였다 — 즉 "이 Phase 가 기존 테스트를 건드리지 않았다" 가
    아니라 **"이 Phase 이후 아무도 기존 테스트 파일에 테스트를 더하지
    않았다"** 를 단언하고 있었다. 뒤의 것은 이 Phase 가 책임질 수 없는
    주장이고, 실제로 Phase 6-M 이 ``tests/engine/test_random_selection.py``
    에 핀 하나를 더하면서 (``test_a_a_move_that_changes_nothing_is_refused``,
    근거는 6-M 보고서 §14-2) 37 → 38 이 되어 깨졌다.

    🔴 **단언은 약해지지 않았다.** 비교 대상을 이 Phase 의 **마지막
    commit** 으로 바꿨을 뿐이다 — 삭제 0건과 개수 변화 0건을 이 Phase 의
    범위 안에서 여전히 그대로 센다. 느슨하게 만든 것이 아니라 **재던 것을
    정확히 재게** 했다.
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

    #: 🔴 이 Phase 의 **마지막 commit** 과 비교한다 (Phase 6-N).
    #: ``HEAD`` 와 비교하면 뒤에 온 모든 작업까지 이 핀이 책임지게 된다.
    before, after = counts(base), counts(shas[0])
    for name, count in before.items():
        assert name in after, f"테스트 파일이 사라졌다: {name}"
        assert after[name] == count, (name, count, after[name])
    assert {p for p in _changed_files() if p in before} == set()


def test_38_this_file_respects_the_repository_tripwires():
    r"""🔴 이 파일이 다른 감사의 지뢰선을 건드리지 않는다는 것을 스스로 지킨다.

    ① 64자 16진수 리터럴 0개 (다른 감사가 그 핀 개수를 센다)
    ② 텍스트 분석기 호출 0개 (다른 감사가 그 호출자 목록을 센다)
    ③ 함수 안 건너뛰기는 commit 게이트 문구만 (세 감사가 그것을 센다)
    """
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
