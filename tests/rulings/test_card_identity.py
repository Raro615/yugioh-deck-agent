"""
카드 식별자 매핑 — 한국어 카드 데이터와 일본어 공식 DB 를 잇는 고리.

카드명 문자열로 잇지 않는다는 것이 핵심이다.
"""

import json

import pytest

from core.card_identity import (
    CardIdentity,
    CardIdentityMapping,
    IdentityError,
    LinkSource,
    LinkStatus,
)
from tests.rulings.conftest import IDENTITY_PATH, requires_identity


def make(card_id: int, cid: int, **kwargs) -> CardIdentity:
    return CardIdentity(card_id=card_id, cid=cid, **kwargs)


# ----------------------------------------------------------------------
# 기본 매핑
# ----------------------------------------------------------------------
def test_maps_both_directions():
    mapping = CardIdentityMapping([make(89631139, 4007), make(2511, 17366)])
    assert mapping.cid_for(89631139) == 4007
    assert mapping.card_ids_for(4007) == [89631139]
    assert mapping.cid_for(2511) == 17366
    assert mapping.cid_for(99999999) is None
    assert mapping.card_ids_for(99999) == []


def test_one_cid_can_have_several_passcodes():
    """같은 카드의 다른 일러스트 판본은 패스코드가 다르지만 cid 는 하나다."""
    mapping = CardIdentityMapping([make(111, 4007), make(222, 4007)])
    assert mapping.card_ids_for(4007) == [111, 222]
    assert mapping.primary_card_id(4007) == 111  # 가장 작은 값으로 고정
    assert mapping.cid_for(111) == mapping.cid_for(222) == 4007


def test_duplicate_mapping_with_conflicting_cid_is_rejected():
    with pytest.raises(IdentityError, match="cid 가 둘"):
        CardIdentityMapping([make(89631139, 4007), make(89631139, 9999)])


def test_duplicate_mapping_with_same_cid_is_idempotent():
    mapping = CardIdentityMapping([make(89631139, 4007), make(89631139, 4007)])
    assert len(mapping) == 1


def test_conflicting_link_is_never_returned():
    """
    대조해서 이름이 달랐던 링크는 **쓰면 안 된다.** 조회에서 빠진다.
    """
    entry = make(
        89631139, 4007,
        status=LinkStatus.CONFLICT,
        note="Lua='X' != 공식='Y'",
    )
    mapping = CardIdentityMapping([entry])
    assert mapping.cid_for(89631139) is None
    assert mapping.card_ids_for(4007) == []
    assert mapping.identity(89631139) is entry   # 기록 자체는 남는다
    assert not entry.trusted


def test_unverified_is_not_the_same_as_conflict():
    """확인하지 않은 것과 확인해서 틀린 것은 다르다."""
    unverified = make(1, 10)
    assert unverified.status is LinkStatus.UNVERIFIED
    assert unverified.trusted
    assert CardIdentityMapping([unverified]).cid_for(1) == 10


def test_round_trip_json():
    entry = make(
        2511, 17366,
        status=LinkStatus.VERIFIED,
        name_ja="白銀の城の狂時計",
        verified_at="2026-09-17T00:00:00Z",
    )
    mapping = CardIdentityMapping([entry], built_at="2026-09-17T00:00:00Z", note="n")
    restored = CardIdentityMapping(
        [CardIdentity.from_json(e) for e in mapping.to_json()["entries"]]
    )
    assert restored.cid_for(2511) == 17366
    assert restored.identity(2511).name_ja == "白銀の城の狂時計"
    assert restored.identity(2511).status is LinkStatus.VERIFIED


def test_save_and_load(tmp_path):
    path = tmp_path / "cid_map.json"
    CardIdentityMapping([make(1, 2)]).save(path)
    assert CardIdentityMapping.load(path).cid_for(1) == 2


def test_missing_file_is_an_explicit_error(tmp_path):
    with pytest.raises(IdentityError, match="build_card_identity"):
        CardIdentityMapping.load(tmp_path / "nope.json")
    assert CardIdentityMapping.try_load(tmp_path / "nope.json") is None


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "cid_map.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": []}), encoding="utf-8")
    with pytest.raises(IdentityError, match="schema_version"):
        CardIdentityMapping.load(path)


def test_link_source_is_recorded_as_supplementary_not_official():
    """
    cid 와 패스코드를 잇는 링크는 보조 출처에서 온 추론이다. 그 사실을
    데이터가 숨기지 않아야 한다.
    """
    entry = make(1, 2)
    assert entry.link_source is LinkSource.YGOPRODECK_KONAMI_ID
    assert entry.to_json()["link_source"] == "ygoprodeck_konami_id"


# ----------------------------------------------------------------------
# 실제 매핑
# ----------------------------------------------------------------------
@requires_identity
def test_real_mapping_covers_the_repository(identity):
    assert len(identity) > 14_000
    assert len(identity.cids) > 14_000
    assert identity.by_status(LinkStatus.CONFLICT) == []


@requires_identity
def test_real_mapping_resolves_known_cards(identity):
    assert identity.cid_for(89631139) == 4007      # 青眼の白龍
    assert identity.cid_for(2511) == 17366         # 白銀の城の狂時計 / 라뷰린스 쿠클락
    assert identity.cid_for(14558127) == 12950     # 灰流うらら


@requires_identity
def test_korean_and_japanese_names_differ_so_names_cannot_be_the_key(identity):
    """
    매핑이 필요한 이유 자체를 확인한다. 이 두 이름은 어떤 문자열 유사도로도
    이어지지 않는다.
    """
    korean = json.loads(
        (IDENTITY_PATH.parent.parent / "ko" / "ko-KR.json").read_text(encoding="utf-8")
    )
    assert korean["2511"]["name"] == "라뷰린스 쿠클락"
    entry = identity.identity(2511)
    assert entry is not None and entry.cid == 17366
    # 일본어 이름은 Lua 쪽에서 온다.
    from core.card_repository import CardRepository

    repository = CardRepository.build(script_dir=IDENTITY_PATH.parent.parent.parent)
    card = repository.get(2511)
    assert card.script.name_ja == "白銀の城の狂時計"
    assert card.name == "라뷰린스 쿠클락"
    assert not set(card.name) & set(card.script.name_ja)  # 공통 글자가 하나도 없다
def test_name_comparison_folds_only_unicode_width_not_similarity():
    """
    실측: Lua 주석은 전각 라틴을, 공식 페이지는 반각을 쓰는 카드가 있다
    (ＳＰＹＲＡＬ－ボルテックス / SPYRAL－ボルテックス). 그냥 ``==`` 로 비교하면
    멀쩡한 링크가 충돌로 찍혀 조회에서 빠진다.
    """
    from core.card_identity import same_card_name

    assert same_card_name("ＳＰＹＲＡＬ－ボルテックス", "SPYRAL－ボルテックス")
    assert same_card_name("灰流うらら", "灰流うらら")
    # 정규형이 같을 때만 참이다 — 비슷하다고 참이 되지 않는다.
    assert not same_card_name("灰流うらら", "灰流うらら２")
    assert not same_card_name("青眼の白龍", "青眼の亜白龍")
    assert not same_card_name("", "灰流うらら")
    assert not same_card_name(None, "灰流うらら")


@requires_identity
def test_verified_entries_carry_the_official_japanese_name(identity):
    verified = identity.by_status(LinkStatus.VERIFIED)
    assert verified, "대조한 항목이 하나도 없습니다."
    for entry in verified:
        assert entry.name_ja
        assert entry.verified_at
    # 표본 카드들은 대조를 마쳤어야 한다.
    blue_eyes = identity.identity(89631139)
    assert blue_eyes.status is LinkStatus.UNVERIFIED  # Lua 일본어명이 없는 카드
    ash = identity.identity(14558127)
    assert ash.status is LinkStatus.VERIFIED
    assert ash.name_ja == "灰流うらら"


@requires_identity
def test_no_conflicts_remain(identity):
    conflicts = [(e.card_id, e.note) for e in identity.by_status(LinkStatus.CONFLICT)]
    assert conflicts == []
