"""
카드 데이터 업데이트 파이프라인 검증.

가장 중요한 규칙: **데이터가 덜 모였다는 이유로 카드가 검색에서 사라지지 않는다.**
Lua 가 없는 신규 카드도 온전히 등록되고, 효과 분석만 상태가 달라진다.

실제 카드 데이터를 기준으로 검증하며, 신규/변경 시나리오는 실제 소스를
건드리지 않도록 임시 디렉터리에서 재현한다.
"""

import json

import pytest

from core.provenance import (
    AnalysisStatus,
    CardProvenance,
    FieldStatus,
    SourceKind,
)
from sources.source_manager import ChangeKind, SourceRecord, SourceSnapshot
from tests.conftest import requires_official_db

pytestmark = requires_official_db

COMPLETE_CARD = 2511  # 라뷰린스 쿠클락 — CDB + 한국어 + 텍스트 + Lua
NORMAL_MONSTER = 89631139  # 푸른 눈의 백룡 — Lua 없음


# ===================================================================
# 1~3. 데이터 확보 정도가 다른 카드들
# ===================================================================


def test_complete_card_has_every_source(repository):
    """시나리오 1: CDB + 한국어 + 공식 텍스트 + Lua 가 모두 있는 카드."""
    card = repository.get(COMPLETE_CARD)
    availability = card.provenance.availability
    assert availability.cdb_available
    assert availability.korean_available
    assert availability.official_text_available
    assert availability.lua_available
    assert card.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


def test_card_without_lua_is_still_registered(repository):
    """
    시나리오 2: Lua 가 없는 카드도 기본 정보와 검색이 정상이어야 한다.
    Lua 가 없다는 이유로 카드가 사라지면 안 된다.
    """
    card = repository.get(NORMAL_MONSTER)
    assert card.script is None
    assert card.provenance.availability.lua_available is False
    # 카드로서는 온전하다
    assert card.name
    assert card.type_mask != 0
    assert card.level == 8
    # 검색으로도 찾힌다
    assert repository.find_by_exact_name(card.display_name())


def test_lua_less_cards_are_not_dropped_anywhere(repository):
    """Lua 없는 카드 전체가 기본 정보를 갖추고 있는지 본다."""
    lua_less = [c for c in repository.all_cards() if c.script is None]
    assert len(lua_less) > 1000
    for card in lua_less:
        assert card.name, card.id
        assert card.provenance is not None


def test_card_without_korean_still_has_a_name(repository):
    """시나리오 3: 한국어 데이터가 없는 카드는 원문 이름으로 표시된다."""
    without_korean = [
        c for c in repository.all_cards() if not c.name_ko and c.name_en
    ]
    assert without_korean
    for card in without_korean[:50]:
        assert card.display_name() == card.name_en
        assert card.provenance.availability.korean_available is False


# ===================================================================
# 4. Lua 가 나중에 추가되는 경우
# ===================================================================


def test_analysis_status_switches_when_lua_appears(repository):
    """
    시나리오 4: 처음에는 텍스트 유래 분석뿐이다가 Lua 가 생기면
    Lua 검증 상태로 바뀌어야 한다.
    """
    card = repository.get(NORMAL_MONSTER)
    assert card.provenance.analysis_status is not AnalysisStatus.LUA_VERIFIED

    # Lua 가 나중에 추가된 상황을 재현한다 (원본 카드는 건드리지 않는다).
    donor = repository.get(COMPLETE_CARD)
    import copy

    clone = copy.deepcopy(card)
    clone.script = donor.script

    from core.card_repository import CardRepository

    CardRepository._record_provenance({clone.id: clone})
    assert clone.provenance.availability.lua_available is True
    assert clone.provenance.analysis_status is AnalysisStatus.LUA_VERIFIED


def test_text_derived_is_never_confused_with_lua_verified(repository):
    """텍스트 유래 분석을 Lua 분석과 같게 취급하면 안 된다."""
    statuses = {c.provenance.analysis_status for c in repository.all_cards()}
    assert AnalysisStatus.LUA_VERIFIED in statuses
    assert AnalysisStatus.TEXT_DERIVED in statuses
    for card in repository.all_cards():
        if card.script is None:
            assert card.provenance.analysis_status is not AnalysisStatus.LUA_VERIFIED


# ===================================================================
# 5~7. 변경 감지
# ===================================================================


def test_unchanged_cards_are_detected_as_unchanged():
    """시나리오 6: 바뀌지 않은 카드는 다시 처리하지 않는다."""
    records = {
        1: SourceRecord(1, SourceKind.OFFICIAL_DB, {"name": "A"}),
        2: SourceRecord(2, SourceKind.OFFICIAL_DB, {"name": "B"}),
    }
    snapshot = SourceSnapshot(source="official_db")
    snapshot.update(records)
    diff = snapshot.diff(records)
    assert diff[ChangeKind.UNCHANGED] == [1, 2]
    assert diff[ChangeKind.NEW] == []
    assert diff[ChangeKind.CHANGED] == []


def test_changed_card_is_detected():
    """시나리오 5: 기존 카드의 값이 바뀌면 변경으로 잡힌다."""
    snapshot = SourceSnapshot(source="official_db")
    snapshot.update({1: SourceRecord(1, SourceKind.OFFICIAL_DB, {"atk": 1000})})
    diff = snapshot.diff({1: SourceRecord(1, SourceKind.OFFICIAL_DB, {"atk": 2000})})
    assert diff[ChangeKind.CHANGED] == [1]


def test_new_and_removed_cards_are_detected():
    """시나리오 7: 신규 카드 추가와 삭제를 구분한다."""
    snapshot = SourceSnapshot(source="official_db")
    snapshot.update({1: SourceRecord(1, SourceKind.OFFICIAL_DB, {"n": "A"})})
    diff = snapshot.diff({2: SourceRecord(2, SourceKind.OFFICIAL_DB, {"n": "B"})})
    assert diff[ChangeKind.NEW] == [2]
    assert diff[ChangeKind.REMOVED] == [1]


def test_only_changed_cards_need_reprocessing():
    """증분 처리: 전체가 아니라 바뀐 카드만 다시 본다."""
    from sources.source_manager import UpdatePlan

    plan = UpdatePlan(
        per_source={
            "official_db": {
                ChangeKind.NEW: [10],
                ChangeKind.CHANGED: [20],
                ChangeKind.REMOVED: [30],
                ChangeKind.UNCHANGED: list(range(1000, 9000)),
            }
        }
    )
    assert plan.changed_card_ids() == {10, 20, 30}
    assert not plan.is_empty()


# ===================================================================
# 8. 소스 충돌
# ===================================================================


def test_higher_priority_source_wins_and_conflict_is_kept():
    """시나리오 8: 값이 다르면 조용히 덮어쓰지 않고 충돌을 남긴다."""
    provenance = CardProvenance(card_id=1)
    provenance.record("card_name", SourceKind.OFFICIAL_DB)
    provenance.record("card_name", SourceKind.KOREAN_DB)
    entry = provenance.fields["card_name"]
    assert entry.source is SourceKind.KOREAN_DB  # 표시명은 한국어가 우선
    assert "official_db" in entry.conflicts
    assert provenance.has_conflict()


def test_supplementary_never_overrides_official():
    """보조 자료는 공식 데이터를 덮어쓰지 못한다."""
    provenance = CardProvenance(card_id=1)
    provenance.record("basic_info", SourceKind.OFFICIAL_DB)
    provenance.record("basic_info", SourceKind.SUPPLEMENTARY)
    assert provenance.source_of("basic_info") is SourceKind.OFFICIAL_DB
    assert "supplementary" in provenance.fields["basic_info"].conflicts


def test_lua_wins_for_effect_analysis():
    """효과 분석은 Lua 가 공식 텍스트보다 우선한다."""
    provenance = CardProvenance(card_id=1)
    provenance.record("effect_analysis", SourceKind.OFFICIAL_TEXT)
    provenance.record("effect_analysis", SourceKind.LUA)
    assert provenance.source_of("effect_analysis") is SourceKind.LUA


def test_supplementary_rejects_subjective_fields(tmp_path):
    """보조 자료의 주관적 평가는 저장하지 않는다."""
    from sources.supplementary import SupplementaryAdapter

    (tmp_path / "x.json").write_text(
        json.dumps(
            {
                "2511": {
                    "archetypes": ["LABRYNTH"],
                    "rating": "티어1",
                    "추천": "꼭 넣으세요",
                }
            }
        ),
        encoding="utf-8",
    )
    records = SupplementaryAdapter(tmp_path).load_records()
    fields = records[2511].fields
    assert "archetypes" in fields
    assert "rating" not in fields
    assert "추천" not in fields


# ===================================================================
# 9~10. 판본 관계와 검색 인덱스
# ===================================================================


def test_printing_relationship_is_unchanged(repository):
    """시나리오 9: 카드 ID 와 판본(패스코드) 관계가 그대로 유지된다."""
    match = repository.resolve_exact_name("푸른 눈의 백룡")
    assert match is not None
    assert match.card_count == 1
    assert match.printing_count == 8


def test_search_index_still_works_after_provenance(repository):
    """시나리오 10: 출처 기록을 붙여도 검색 인덱스는 그대로 동작한다."""
    from core import constants as C
    from core.card_search import CardSearchEngine, SearchFilters

    engine = CardSearchEngine(repository)
    result = engine.search(
        SearchFilters(levels=[4], races=[C.RACE_WARRIOR], required_types=C.TYPE_MONSTER)
    )
    assert result.total > 300
    for card in result.cards[:30]:
        assert card.monster_level == 4
        assert card.provenance is not None


def test_lua_less_cards_appear_in_search_results(repository):
    """Lua 없는 카드가 검색 결과에 실제로 들어 있어야 한다."""
    from core import constants as C
    from core.card_search import CardSearchEngine, SearchFilters

    engine = CardSearchEngine(repository)
    result = engine.search(
        SearchFilters(races=[C.RACE_DRAGON], required_types=C.TYPE_MONSTER)
    )
    assert any(c.script is None for c in result.cards)


# ===================================================================
# 파이프라인 전체
# ===================================================================


def test_state_round_trip(tmp_path):
    """상태 파일을 쓰고 다시 읽으면 변경이 없어야 한다."""
    from sources.source_manager import SourceManager

    class Stub:
        kind = SourceKind.SUPPLEMENTARY

        def is_available(self):
            return True

        def load_records(self):
            return {7: SourceRecord(7, SourceKind.SUPPLEMENTARY, {"a": 1})}

    state = tmp_path / "state.json"
    manager = SourceManager(adapters=[Stub()], state_path=state)
    first = manager.commit()
    assert first.per_source["supplementary"][ChangeKind.NEW] == [7]

    again = SourceManager(adapters=[Stub()], state_path=state).plan()
    assert again.per_source["supplementary"][ChangeKind.UNCHANGED] == [7]
    assert again.is_empty()


def test_validation_catches_missing_cards(repository):
    from scripts.update_cards import validate

    assert validate(repository) == []


def test_text_analysis_marks_its_own_limits(repository):
    """텍스트 분석은 설정 문구를 효과로 읽지 않는다."""
    from analysis.text_effect_analyzer import TextEffectAnalyzer

    analyzer = TextEffectAnalyzer()
    analysis = analyzer.analyze(repository.get(NORMAL_MONSTER))
    assert analysis.skipped_reason is not None
    assert analysis.effect is None
