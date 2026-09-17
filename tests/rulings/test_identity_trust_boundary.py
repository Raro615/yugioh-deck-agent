"""
식별자 신뢰 경계.

9bf690a 에는 이런 경로가 있었다::

    UNVERIFIED -> trusted=True -> cid_for() -> 공식 사이트에 재정 요청

검증되지 않은 ``cid`` 로 공식 사이트에 물으면 **다른 카드의 공식 재정이
이 카드의 것으로 저장된다.** 이 파일은 그 경로가 막혔는지 검사한다.

두 원칙을 동시에 지켜야 한다.

- ``UNVERIFIED`` 는 authoritative lookup 에 쓰이지 않는다.
- 그렇다고 ``UNVERIFIED`` 데이터를 지우거나 ``VERIFIED`` 로 위장하지 않는다.
"""

import pytest

from core.card_identity import (
    CardIdentity,
    CardIdentityMapping,
    LinkSource,
    LinkStatus,
)
from rulings.ruling_model import RulingAvailability
from sources.ocg_ruling_adapter import OfficialOcgRulingAdapter
from tests.rulings.conftest import requires_identity, requires_samples

VERIFIED_CARD = 111
UNVERIFIED_CARD = 222
CONFLICT_CARD = 333


def mapping() -> CardIdentityMapping:
    return CardIdentityMapping([
        CardIdentity(
            card_id=VERIFIED_CARD, cid=1001,
            status=LinkStatus.VERIFIED, name_ja="検証済みカード",
            verified_at="2026-01-01T00:00:00Z",
        ),
        CardIdentity(card_id=UNVERIFIED_CARD, cid=1002, status=LinkStatus.UNVERIFIED),
        CardIdentity(
            card_id=CONFLICT_CARD, cid=1003, status=LinkStatus.CONFLICT,
            note="Lua='A' != 공식='B'",
        ),
    ])


class RecordingOpener:
    """공식 사이트 요청이 실제로 나갔는지 세는 가짜 HTTP 계층."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        return (
            '<meta name="keywords" content="テストカード,Q&A">'
            '<div id="card_text">テキスト</div>'
        )


def adapter(opener, tmp_path):
    return OfficialOcgRulingAdapter(
        cache_dir=tmp_path, delay=0, use_cache=False, opener=opener
    )


# ----------------------------------------------------------------------
# Test 1~3 — trusted 의 의미
# ----------------------------------------------------------------------
def test_unverified_identity_is_not_trusted():
    entry = mapping().identity(UNVERIFIED_CARD)
    assert entry.status is LinkStatus.UNVERIFIED
    assert entry.trusted is False
    # 그러나 후보로는 남아 있다 — 지우지 않는다.
    assert entry.is_candidate is True


def test_conflict_identity_is_not_trusted():
    entry = mapping().identity(CONFLICT_CARD)
    assert entry.trusted is False
    assert entry.is_candidate is False       # 틀린 것으로 판명났다


def test_verified_identity_is_trusted():
    entry = mapping().identity(VERIFIED_CARD)
    assert entry.trusted is True
    assert entry.is_candidate is True


def test_trusted_means_verified_not_merely_not_conflict():
    """
    9bf690a 의 버그가 정확히 이것이었다: ``trusted = not CONFLICT``.
    """
    identity = mapping()
    not_conflict = [
        e for e in identity if e.status is not LinkStatus.CONFLICT
    ]
    trusted = [e for e in identity if e.trusted]
    assert len(not_conflict) == 2            # verified + unverified
    assert len(trusted) == 1                 # verified 만
    assert trusted[0].status is LinkStatus.VERIFIED


# ----------------------------------------------------------------------
# Test 4 — 두 질문에 다른 답
# ----------------------------------------------------------------------
def test_candidate_lookup_and_authoritative_lookup_answer_differently():
    """
    Q1 "cid 후보가 존재하는가?"        -> UNVERIFIED 도 YES
    Q2 "공식 조회에 써도 되는가?"       -> UNVERIFIED 는 NO
    """
    identity = mapping()

    assert identity.cid_for(UNVERIFIED_CARD) == 1002          # Q1: 후보 있음
    assert identity.verified_cid_for(UNVERIFIED_CARD) is None  # Q2: 쓰면 안 됨

    assert identity.cid_for(VERIFIED_CARD) == 1001
    assert identity.verified_cid_for(VERIFIED_CARD) == 1001

    # 충돌은 후보로도 돌려주지 않는다.
    assert identity.cid_for(CONFLICT_CARD) is None
    assert identity.verified_cid_for(CONFLICT_CARD) is None

    assert identity.verified_card_ids() == [VERIFIED_CARD]


def test_status_is_queryable_without_guessing():
    identity = mapping()
    assert identity.status_for(VERIFIED_CARD) is LinkStatus.VERIFIED
    assert identity.status_for(UNVERIFIED_CARD) is LinkStatus.UNVERIFIED
    assert identity.status_for(CONFLICT_CARD) is LinkStatus.CONFLICT
    assert identity.status_for(999999) is None


# ----------------------------------------------------------------------
# Test 5~7 — fetch 경계에서 실제 요청이 나가는가
# ----------------------------------------------------------------------
def test_unverified_identity_sends_no_official_request(tmp_path):
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=mapping()
    )
    assert opener.urls == [], "검증되지 않은 식별자로 공식 사이트에 요청했습니다."
    assert result.availability is RulingAvailability.IDENTITY_UNVERIFIED
    assert result.identity_status == "unverified"
    assert result.authoritative is False
    assert result.rulings == []


def test_conflict_identity_sends_no_official_request(tmp_path):
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1003, card_id=CONFLICT_CARD, identity=mapping()
    )
    assert opener.urls == []
    assert result.availability is RulingAvailability.IDENTITY_CONFLICT
    assert result.identity_status == "conflict"
    assert result.authoritative is False


def test_verified_identity_reaches_the_official_lookup(tmp_path):
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1001, card_id=VERIFIED_CARD, identity=mapping()
    )
    assert opener.urls, "검증된 식별자인데 조회가 이루어지지 않았습니다."
    assert "cid=1001" in opener.urls[0]
    assert result.availability is RulingAvailability.NOT_FOUND
    assert result.identity_status == "verified"
    assert result.confirmed and result.attempted


# ----------------------------------------------------------------------
# Test 8 — 검증을 거치면 그때부터 조회 가능
# ----------------------------------------------------------------------
def test_lookup_becomes_possible_once_the_identity_is_verified(tmp_path):
    identity = mapping()
    entry = identity.identity(UNVERIFIED_CARD)

    opener = RecordingOpener()
    first = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=identity
    )
    assert first.availability is RulingAvailability.IDENTITY_UNVERIFIED
    assert opener.urls == []

    # 실제 대조 과정을 거쳤다고 가정한다 (자동 승격이 아니다).
    entry.status = LinkStatus.VERIFIED
    entry.name_ja = "テストカード"
    entry.verified_at = "2026-01-02T00:00:00Z"

    opener = RecordingOpener()
    second = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=identity
    )
    assert opener.urls, "검증 후에도 조회가 막혀 있습니다."
    assert second.availability is RulingAvailability.NOT_FOUND
    assert second.identity_status == "verified"


# ----------------------------------------------------------------------
# 상태 의미를 섞지 않는다
# ----------------------------------------------------------------------
def test_identity_problems_are_not_disguised_as_ruling_results(tmp_path):
    """
    UNVERIFIED -> RULING_NOT_FOUND 나 SOURCE_UNAVAILABLE 로 바꾸면,
    "이 카드에는 재정이 없다" 또는 "사이트가 죽었다" 는 거짓말이 된다.
    """
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=mapping()
    )
    assert result.availability is not RulingAvailability.NOT_FOUND
    assert result.availability is not RulingAvailability.SOURCE_UNAVAILABLE
    assert result.availability is not RulingAvailability.NOT_CHECKED
    assert result.blocked_by_identity
    assert result.attempted is False         # 네트워크를 타지 않았다


def test_identity_block_is_not_counted_as_a_fetch_failure():
    from rulings.ruling_model import CardRulingSet
    from rulings.update import diff_ruling_set

    blocked = CardRulingSet(
        official_cid=1002, card_id=UNVERIFIED_CARD,
        availability=RulingAvailability.IDENTITY_UNVERIFIED,
    )
    plan = diff_ruling_set(None, blocked)
    assert plan.identity_blocked == [1002]
    assert plan.unavailable == []
    assert plan.removed == [] and plan.new == []
    text = " ".join(plan.describe())
    assert "식별자 미검증" in text
    assert "재정이 없다는 뜻도, 조회에 실패했다는 뜻도 아니다" in text


def test_blocked_result_is_not_saved_as_a_collected_record(tmp_path):
    """
    막힌 결과를 수집물처럼 저장하면 "확인했는데 없더라" 로 읽힌다.
    """
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=mapping()
    )
    assert not result.confirmed        # 수집기는 confirmed 일 때만 저장한다


# ----------------------------------------------------------------------
# 데이터를 지우지도, 위장하지도 않는다
# ----------------------------------------------------------------------
@requires_identity
def test_unverified_entries_are_kept_not_deleted(identity):
    stats = identity.stats()
    assert stats["unverified"] > 10_000, "미검증 항목이 사라졌습니다."
    assert stats["verified"] + stats["unverified"] + stats["conflict"] == len(identity)


@requires_identity
def test_unverified_is_never_auto_promoted(identity):
    """
    승격은 실제 대조를 거쳐야 한다. 대조한 적 없는 항목이 VERIFIED 로
    올라가 있으면 안 된다.
    """
    for entry in identity.by_status(LinkStatus.VERIFIED):
        assert entry.name_ja, entry.card_id       # 공식 페이지에서 읽은 이름
        assert entry.verified_at, entry.card_id   # 대조한 시각
    for entry in identity.by_status(LinkStatus.UNVERIFIED):
        assert entry.name_ja is None
        assert entry.verified_at is None


@requires_identity
def test_alias_derived_links_are_not_verified(identity):
    """
    alias 로 만들어진 링크는 추론이다. "아마 맞다" 를 VERIFIED 로 만들지 않는다.
    """
    alias_entries = [e for e in identity if e.link_source is LinkSource.CARD_ALIAS]
    assert alias_entries
    for entry in alias_entries:
        assert entry.status is LinkStatus.UNVERIFIED
        assert entry.trusted is False


# ----------------------------------------------------------------------
# 기존 수집 데이터
# ----------------------------------------------------------------------
@requires_samples
def test_existing_records_are_preserved_and_honestly_labelled(ruling_repository):
    """
    식별자가 검증되지 않은 채 수집된 기존 데이터를 지우지 않는다.
    대신 authoritative 가 거짓이 되어 사실이 드러난다.
    """
    sets = {s.official_cid: s for s in ruling_repository.ruling_sets}
    assert len(sets) == 9

    unverified = [s for s in sets.values() if s.identity_status != "verified"]
    assert unverified, "식별자 상태가 기록되지 않았습니다."
    for ruling_set in unverified:
        assert ruling_set.authoritative is False
        assert ruling_set.rulings or ruling_set.availability is (
            RulingAvailability.NOT_FOUND
        )

    # 그래도 데이터는 그대로 남아 있다.
    assert len(sets[4007].rulings) == 88
    assert sets[4007].identity_status == "unverified"
    assert sets[4007].authoritative is False

    verified = [s for s in sets.values() if s.identity_status == "verified"]
    assert verified
    for ruling_set in verified:
        assert ruling_set.authoritative is True


@requires_samples
def test_search_exposes_authoritativeness(ruling_search):
    assert ruling_search.is_authoritative(5318639) is True    # サイクロン
    assert ruling_search.is_authoritative(89631139) is False  # 식별자 미검증
    assert ruling_search.is_authoritative(99999999) is False  # 수집한 적 없음
    # 데이터는 여전히 조회된다 — 감춰지지 않는다.
    assert len(ruling_search.by_card_id(89631139)) == 89


@requires_samples
def test_original_japanese_text_survived_this_change(ruling_repository):
    entry = ruling_repository.ruling("OCG-QA-21330")
    assert f"魔弾の射手　カスパール" in entry.answer_original
    for e in ruling_repository:
        assert e.provenance.language == "ja"


# ----------------------------------------------------------------------
# 명시적 예외 경로
# ----------------------------------------------------------------------
def test_unverified_fetch_requires_an_explicit_opt_in(tmp_path):
    """
    검증 전 데이터를 다루는 도구는 명시적으로 허용해야 하고, 그때도
    결과에 사실이 남는다.
    """
    opener = RecordingOpener()
    result = adapter(opener, tmp_path).fetch_ruling_set(
        1002, card_id=UNVERIFIED_CARD, identity=mapping(),
        allow_unverified_identity=True,
    )
    assert opener.urls                                  # 이번에는 조회한다
    assert result.identity_status == "unverified"       # 사실은 남는다
    assert result.authoritative is False                # authoritative 는 아니다
