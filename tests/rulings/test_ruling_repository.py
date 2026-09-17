"""RulingRepository / RulingSearch — 조회, 검색, 무결성."""

import pytest

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    CardRulingSupplement,
    RulingAvailability,
    RulingKind,
)
from rulings.ruling_repository import RulingDataError, RulingRepository
from rulings.ruling_search import RulingSearch, normalize
from tests.rulings.conftest import requires_samples


def qa(fid: int, cid: int, card_id: int | None, question: str, answer: str,
       category: str = "モンスター", date: str = "2025-01-01",
       related: list[int] | None = None) -> CardRuling:
    return CardRuling(
        ruling_id=f"OCG-QA-{fid}", card_id=card_id, official_cid=cid,
        question_original=question, answer_original=answer,
        ruling_category=category, published_or_updated_at=date,
        related_card_ids=related or [],
    )


def build_repository() -> RulingRepository:
    first = CardRulingSet(
        official_cid=4007, card_id=89631139,
        availability=RulingAvailability.EXISTS, name_ja="青眼の白龍",
        reported_total=2,
        rulings=[
            qa(1, 4007, 89631139, "ダメージステップに発動できますか？",
               "はい、発動できます。", date="2024-05-01"),
            qa(2, 4007, 89631139, "対象を取る効果ですか？",
               "対象を取る効果です。", category="魔法", date="2026-01-01",
               related=[2511]),
        ],
        supplement=CardRulingSupplement(
            ruling_id="OCG-SUP-4007", card_id=89631139, official_cid=4007,
            text_original="■「ブルーアイズ」モンスターです。",
            published_or_updated_at="2021-07-10",
        ),
    )
    second = CardRulingSet(
        official_cid=17366, card_id=2511,
        availability=RulingAvailability.NOT_FOUND, name_ja="白銀の城の狂時計",
        reported_total=0,
    )
    third = CardRulingSet(
        official_cid=9999, card_id=777,
        availability=RulingAvailability.SOURCE_UNAVAILABLE, error="timeout",
    )
    return RulingRepository([first, second, third])


@pytest.fixture()
def repository() -> RulingRepository:
    return build_repository()


@pytest.fixture()
def search(repository) -> RulingSearch:
    return RulingSearch(repository)


# ----------------------------------------------------------------------
# 조회
# ----------------------------------------------------------------------
def test_lookup_by_card_id_and_cid(repository):
    assert repository.by_card_id(89631139).official_cid == 4007
    assert repository.by_cid(4007).card_id == 89631139
    assert repository.by_card_id(12345) is None


def test_lookup_by_ruling_id(repository):
    entry = repository.ruling("OCG-QA-1")
    assert entry is not None and entry.kind is RulingKind.QA
    assert repository.ruling("OCG-SUP-4007").kind is RulingKind.SUPPLEMENT
    assert repository.ruling("OCG-QA-999") is None


def test_card_with_several_rulings(repository):
    assert len(repository.rulings_for_card(89631139)) == 2
    assert repository.supplement_for_card(89631139) is not None


def test_card_with_no_rulings(repository):
    assert repository.rulings_for_card(2511) == []
    assert repository.supplement_for_card(2511) is None
    # 그래도 "확인했다"는 기록은 남는다.
    assert repository.availability_for_card(2511) is RulingAvailability.NOT_FOUND


def test_never_checked_card_is_not_reported_as_having_no_rulings(repository):
    """
    수집한 적 없는 카드를 "재정 없음"이라고 말하면 안 된다. 그리고
    "사이트 접근 실패"라고도 말하면 안 된다 — 시도조차 하지 않았다.
    """
    assert repository.availability_for_card(46986414) is (
        RulingAvailability.NOT_CHECKED
    )
    assert repository.availability_for_card(2511) is RulingAvailability.NOT_FOUND
    assert repository.availability_for_card(777) is (
        RulingAvailability.SOURCE_UNAVAILABLE   # 시도했다가 실패한 카드
    )
    assert repository.availability_for_cid(9999) is (
        RulingAvailability.SOURCE_UNAVAILABLE
    )
    assert repository.availability_for_cid(12345) is RulingAvailability.NOT_CHECKED


def test_referencing_finds_rulings_that_mention_a_card(repository):
    hits = repository.referencing(2511)
    assert [h.ruling_id for h in hits] == ["OCG-QA-2"]


def test_one_ruling_can_be_listed_under_several_cards():
    """
    두 카드의 상호작용을 다루는 공식 Q&A 는 **양쪽 카드 페이지에 모두** 실린다
    (실측: fid=21953 이 青眼の白龍 과 サイクロン 양쪽에 있다). 그래서
    ruling_id 는 카드가 아니라 재정의 식별자다.
    """
    shared_a = qa(21953, 4007, 89631139, "共通の質問", "共通の答え")
    shared_b = qa(21953, 4909, 5318639, "共通の質問", "共通の答え")
    repository = RulingRepository([
        CardRulingSet(official_cid=4007, card_id=89631139,
                      availability=RulingAvailability.EXISTS,
                      reported_total=1, rulings=[shared_a]),
        CardRulingSet(official_cid=4909, card_id=5318639,
                      availability=RulingAvailability.EXISTS,
                      reported_total=1, rulings=[shared_b]),
    ])
    assert len(repository) == 1                      # 재정은 하나
    assert len(repository.copies_of("OCG-QA-21953")) == 2
    assert repository.cids_for_ruling("OCG-QA-21953") == [4007, 4909]
    assert repository.card_ids_for_ruling("OCG-QA-21953") == [5318639, 89631139]
    # 양쪽 카드에서 모두 찾을 수 있다.
    assert len(repository.rulings_for_card(89631139)) == 1
    assert len(repository.rulings_for_card(5318639)) == 1
    assert repository.check_integrity() == []


def test_copies_of_one_ruling_must_agree():
    """같은 재정인데 본문이 다르면 수집이 어긋난 것이다."""
    repository = RulingRepository([
        CardRulingSet(official_cid=1, card_id=1,
                      availability=RulingAvailability.EXISTS, reported_total=1,
                      rulings=[qa(7, 1, 1, "q", "답 A")]),
        CardRulingSet(official_cid=2, card_id=2,
                      availability=RulingAvailability.EXISTS, reported_total=1,
                      rulings=[qa(7, 2, 2, "q", "답 B")]),
    ])
    assert any("사본들이 서로 다른 내용" in p for p in repository.check_integrity())


def test_integrity_catches_inconsistent_sets():
    bad = CardRulingSet(
        official_cid=1, availability=RulingAvailability.EXISTS, reported_total=5,
        rulings=[qa(1, 1, None, "q", "a")],
    )
    problems = RulingRepository([bad]).check_integrity()
    assert any("5건 중 1건" in p for p in problems)


def test_integrity_catches_tampered_content_hash():
    entry = qa(1, 1, None, "q", "a")
    entry.content_hash = "sha256:deadbeef"
    ruling_set = CardRulingSet(
        official_cid=1, availability=RulingAvailability.EXISTS,
        reported_total=1, rulings=[entry],
    )
    problems = RulingRepository([ruling_set]).check_integrity()
    assert any("content_hash" in p for p in problems)


def test_load_and_save_round_trip(tmp_path, repository):
    for ruling_set in repository.ruling_sets:
        RulingRepository.save_ruling_set(ruling_set, tmp_path)
    reloaded = RulingRepository.load(tmp_path)
    assert reloaded.stats() == repository.stats()
    assert reloaded.ruling("OCG-QA-1").answer_original == "はい、発動できます。"


def test_missing_directory_is_explicit_unless_allowed(tmp_path):
    with pytest.raises(RulingDataError, match="fetch_ocg_rulings"):
        RulingRepository.load(tmp_path / "nope")
    assert len(RulingRepository.load(tmp_path / "nope", missing_ok=True)) == 0


# ----------------------------------------------------------------------
# 검색
# ----------------------------------------------------------------------
def test_search_by_ruling_id(search):
    assert search.by_ruling_id("OCG-QA-1").ruling_id == "OCG-QA-1"
    assert search.by_ruling_id("OCG-QA-404") is None


def test_search_by_card_id_and_cid(search):
    assert len(search.by_card_id(89631139)) == 3   # Q&A 2 + 補足 1
    assert len(search.by_cid(4007)) == 3
    assert search.by_card_id(2511) == []


def test_search_by_japanese_card_name(search):
    """재정 데이터가 일본어 카드명을 들고 있으므로 그대로 찾을 수 있다."""
    assert len(search.by_card_name("青眼の白龍")) == 3
    assert search.by_card_name("存在しないカード") == []


def test_korean_card_name_needs_an_injected_resolver(repository):
    """
    한국어 이름으로 찾으려면 카드 계층의 해석기를 주입한다. 재정 계층이
    카드명 문자열을 혼자 넘겨짚지 않는다.
    """
    without = RulingSearch(repository)
    assert without.by_card_name("푸른 눈의 백룡") == []

    with_resolver = RulingSearch(
        repository,
        card_name_resolver=lambda name: [89631139] if name == "푸른 눈의 백룡" else [],
    )
    assert len(with_resolver.by_card_name("푸른 눈의 백룡")) == 3


def test_search_question_and_answer_separately(search):
    only_question = search.search("ダメージステップ", field="question")
    assert [h.ruling_id for h in only_question] == ["OCG-QA-1"]
    assert only_question[0].matched_in == ["question"]

    only_answer = search.search("ダメージステップ", field="answer")
    assert only_answer == []


def test_search_scores_question_matches_higher(search):
    hits = search.search("対象を取る効果")
    assert hits[0].ruling_id == "OCG-QA-2"
    assert set(hits[0].matched_in) == {"question", "answer"}


def test_search_covers_supplements(search):
    hits = search.search("ブルーアイズ")
    assert [h.ruling_id for h in hits] == ["OCG-SUP-4007"]
    assert hits[0].matched_in == ["supplement"]
    assert hits[0].entry.kind is RulingKind.SUPPLEMENT


def test_search_can_be_limited_to_one_kind(search):
    assert search.search("ブルーアイズ", kind=RulingKind.QA) == []
    assert len(search.search("ブルーアイズ", kind=RulingKind.SUPPLEMENT)) == 1


def test_search_filters_by_card_category_and_date(search):
    assert [h.ruling_id for h in search.search("効果", card_id=89631139)] == ["OCG-QA-2"]
    assert [h.ruling_id for h in search.search("効果", category="魔法")] == ["OCG-QA-2"]
    assert search.search("発動", since="2025-01-01") == []
    assert [h.ruling_id for h in search.search("発動", until="2025-01-01")] == ["OCG-QA-1"]


def test_by_category_and_updated_between(search):
    assert [e.ruling_id for e in search.by_category("魔法")] == ["OCG-QA-2"]
    window = search.updated_between(since="2024-01-01", until="2025-12-31")
    assert [e.ruling_id for e in window] == ["OCG-QA-1"]


def test_related_to_excludes_the_card_itself(search):
    assert [e.ruling_id for e in search.related_to(2511)] == ["OCG-QA-2"]
    assert search.related_to(89631139) == []


def test_search_normalizes_fullwidth_digits():
    """공식 재정은 「１ターンに１度」처럼 전각 숫자를 쓴다."""
    ruling_set = CardRulingSet(
        official_cid=1, card_id=1, availability=RulingAvailability.EXISTS,
        reported_total=1,
        rulings=[qa(1, 1, 1, "質問", "このカードの効果は１ターンに１度しか使用できません。")],
    )
    search = RulingSearch(RulingRepository([ruling_set]))
    assert normalize("１ターンに１度") == normalize("1ターンに1度")
    assert len(search.search("1ターンに1度")) == 1


def test_empty_query_returns_nothing(search):
    assert search.search("") == []
    assert search.search("   ") == []


def test_hits_carry_an_excerpt_cut_from_the_original(search):
    hit = search.search("ダメージステップ")[0]
    assert hit.excerpt
    assert hit.excerpt.strip("… ") in (
        hit.entry.question_original + hit.entry.answer_original
    ).replace("\n", " ")


def test_availability_is_exposed_through_search(search):
    assert search.availability(89631139) is RulingAvailability.EXISTS
    assert search.availability(2511) is RulingAvailability.NOT_FOUND
    assert search.availability(777) is RulingAvailability.SOURCE_UNAVAILABLE
    assert search.availability(46986414) is RulingAvailability.NOT_CHECKED


# ----------------------------------------------------------------------
# 실제 수집분
# ----------------------------------------------------------------------
@requires_samples
def test_collected_samples_are_consistent(ruling_repository):
    assert ruling_repository.check_integrity() == []


@requires_samples
def test_collected_samples_keep_japanese_originals(ruling_repository):
    for entry in ruling_repository:
        assert entry.provenance.language == "ja"
        assert entry.provenance.authority == "official"
        assert entry.provenance.source.value == "konami_ocg_database"
        assert entry.provenance.source_url.startswith(
            "https://www.db.yugioh-card.com/yugiohdb/"
        )
        assert entry.translations == {}   # 수집 단계에서는 번역을 만들지 않는다


@requires_samples
def test_sample_covers_the_intended_variety(ruling_repository):
    """
    표본은 성질이 다른 카드를 골라야 파싱이 어디서 깨지는지 보인다.
    """
    sets = {s.official_cid: s for s in ruling_repository.ruling_sets}
    assert len(sets) >= 9

    # Q&A 가 아주 많은 카드 / 적은 카드 / 없는 카드
    assert len(sets[4909].rulings) > 300      # サイクロン
    assert len(sets[17366].rulings) < 10      # 白銀の城の狂時計
    assert len(sets[4138].rulings) == 0       # １３人目の埋葬者

    # 補足情報 가 있는 카드와 없는 카드
    assert sets[4007].supplement is not None
    assert sets[4041].supplement is None      # ブラック・マジシャン

    # 세 가지 확인 결과 중 둘이 실제로 나타난다
    assert sets[4007].availability is RulingAvailability.EXISTS
    assert sets[4138].availability is RulingAvailability.NOT_FOUND


@requires_samples
def test_reported_total_matches_what_was_collected(ruling_repository):
    """공식이 밝힌 개수를 다 받았는지 대조한다 — 페이지네이션 누락 방지."""
    for ruling_set in ruling_repository.ruling_sets:
        assert ruling_set.complete, ruling_set.official_cid
        if ruling_set.reported_total:
            assert len(ruling_set.rulings) == ruling_set.reported_total


@requires_samples
def test_one_official_qa_is_listed_under_several_cards(ruling_repository):
    """실측: 두 카드의 상호작용을 다루는 재정은 양쪽 페이지에 모두 실린다."""
    shared = [
        rid for rid in ruling_repository.ruling_ids()
        if len(ruling_repository.cids_for_ruling(rid)) > 1
    ]
    assert shared, "공유 재정이 하나도 없다면 표본이 너무 좁은 것이다."
    for ruling_id in shared:
        copies = ruling_repository.copies_of(ruling_id)
        assert len({c.content_hash for c in copies}) == 1   # 본문은 같다
        assert len({c.official_cid for c in copies}) > 1    # 실린 카드는 다르다


@requires_samples
def test_collected_supplements_are_separate_from_qa(ruling_repository):
    supplement = ruling_repository.supplement_for_card(89631139)
    assert supplement is not None
    assert supplement.text_original == "■「ブルーアイズ」モンスターです。"
    assert supplement.published_or_updated_at == "2021-07-10"
    assert supplement.provenance.data_type == "card_supplement"
    # 같은 카드의 Q&A 는 다른 data_type 을 갖는다.
    assert ruling_repository.rulings_for_card(89631139)[0].provenance.data_type == (
        "card_ruling"
    )


@requires_samples
def test_collected_rulings_link_only_officially_linked_cards(ruling_repository):
    """관련 카드는 공식 페이지가 건 링크에서만 온다."""
    linked = [e for e in ruling_repository if e.related_card_cids]
    assert linked
    for entry in linked:
        assert entry.related_card_cids == sorted(set(entry.related_card_cids))
        # 패스코드로 옮긴 것은 매핑에 있는 cid 뿐이다 — 추측하지 않는다.
        assert len(entry.related_card_ids) <= len(entry.related_card_cids)


@requires_samples
def test_search_over_real_data_finds_damage_step_rulings(ruling_search):
    hits = ruling_search.search("ダメージステップ", limit=5)
    assert hits
    for hit in hits:
        body = (
            hit.entry.question_original + hit.entry.answer_original
            if hasattr(hit.entry, "question_original")
            else hit.entry.text_original
        )
        assert "ダメージステップ" in body


@requires_samples
def test_search_over_real_data_finds_targeting_rulings(ruling_search):
    assert ruling_search.search("対象", limit=3)
