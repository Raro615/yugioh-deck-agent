"""
증분 갱신과 실패 처리.

두 가지가 핵심이다.

- 바뀐 재정만 다시 처리한다 (``content_hash`` 비교).
- **확인에 실패했을 때는 아무 판단도 하지 않는다.** 사이트가 잠깐 죽었는데
  재정이 삭제됐다고 기록하면 데이터가 조용히 망가진다.
"""

import pytest

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    RulingAvailability,
    RulingTranslation,
    TranslationSource,
)
from rulings.update import diff_ruling_set, merge_translations
from sources.ocg_ruling_adapter import OfficialOcgRulingAdapter, RulingFetchError
from tests.rulings.conftest import fixture_html


def qa(fid: int, answer: str) -> CardRuling:
    return CardRuling(
        ruling_id=f"OCG-QA-{fid}", card_id=1, official_cid=10,
        question_original="質問", answer_original=answer,
        published_or_updated_at="2025-01-01",
    )


def ruling_set(*entries: CardRuling, **kwargs) -> CardRulingSet:
    defaults = dict(
        official_cid=10, card_id=1,
        availability=RulingAvailability.EXISTS, reported_total=len(entries),
    )
    defaults.update(kwargs)
    return CardRulingSet(rulings=list(entries), **defaults)


# ----------------------------------------------------------------------
# 변경 감지
# ----------------------------------------------------------------------
def test_first_collection_is_all_new():
    plan = diff_ruling_set(None, ruling_set(qa(1, "はい"), qa(2, "いいえ")))
    assert plan.counts() == {
        "new": 2, "changed": 0, "removed": 0, "unchanged": 0,
        "unavailable": 0, "identity_blocked": 0, "skipped": 0,
    }


def test_unchanged_pages_are_skipped():
    before = ruling_set(qa(1, "はい"))
    plan = diff_ruling_set(before, ruling_set(qa(1, "はい")))
    assert plan.unchanged == ["OCG-QA-1"]
    assert plan.is_empty


def test_changed_answer_is_detected():
    before = ruling_set(qa(1, "はい"))
    plan = diff_ruling_set(before, ruling_set(qa(1, "いいえ")))
    assert plan.changed == ["OCG-QA-1"]
    assert not plan.is_empty


def test_new_ruling_is_detected():
    before = ruling_set(qa(1, "はい"))
    plan = diff_ruling_set(before, ruling_set(qa(1, "はい"), qa(2, "追加")))
    assert plan.new == ["OCG-QA-2"]
    assert plan.unchanged == ["OCG-QA-1"]


def test_removed_ruling_is_detected():
    before = ruling_set(qa(1, "はい"), qa(2, "いいえ"))
    plan = diff_ruling_set(before, ruling_set(qa(1, "はい")))
    assert plan.removed == ["OCG-QA-2"]


def test_supplement_participates_in_the_diff():
    from rulings.ruling_model import CardRulingSupplement

    supplement = CardRulingSupplement(
        ruling_id="OCG-SUP-10", card_id=1, official_cid=10, text_original="■A"
    )
    before = ruling_set(qa(1, "はい"), supplement=supplement)
    changed = CardRulingSupplement(
        ruling_id="OCG-SUP-10", card_id=1, official_cid=10, text_original="■B"
    )
    plan = diff_ruling_set(before, ruling_set(qa(1, "はい"), supplement=changed))
    assert plan.changed == ["OCG-SUP-10"]


# ----------------------------------------------------------------------
# 실패 처리
# ----------------------------------------------------------------------
def test_failed_check_never_reports_removals():
    """
    사이트에 못 갔을 뿐인데 기존 재정이 삭제됐다고 기록하면 안 된다.
    """
    before = ruling_set(qa(1, "はい"), qa(2, "いいえ"))
    failed = CardRulingSet(
        official_cid=10, card_id=1,
        availability=RulingAvailability.SOURCE_UNAVAILABLE, error="timeout",
    )
    plan = diff_ruling_set(before, failed)
    assert plan.removed == []
    assert plan.new == [] and plan.changed == []
    assert plan.unavailable == [10]
    assert plan.is_empty


def test_confirmed_empty_result_does_report_removals():
    """정상 조회에서 사라진 것은 진짜 삭제다."""
    before = ruling_set(qa(1, "はい"))
    after = CardRulingSet(
        official_cid=10, card_id=1, availability=RulingAvailability.NOT_FOUND,
        reported_total=0,
    )
    plan = diff_ruling_set(before, after)
    assert plan.removed == ["OCG-QA-1"]


def test_previous_failure_is_not_treated_as_a_baseline():
    """
    이전에 확인 실패였다면 그때의 빈 결과를 기준으로 "새 재정"이라 말할 수는
    있어도 "삭제"를 말할 수는 없다.
    """
    before = CardRulingSet(
        official_cid=10, availability=RulingAvailability.SOURCE_UNAVAILABLE
    )
    plan = diff_ruling_set(before, ruling_set(qa(1, "はい")))
    assert plan.new == ["OCG-QA-1"]
    assert plan.removed == []


def test_plan_describes_unavailable_without_claiming_absence():
    before = ruling_set(qa(1, "はい"))
    failed = CardRulingSet(
        official_cid=10, availability=RulingAvailability.SOURCE_UNAVAILABLE
    )
    text = " ".join(diff_ruling_set(before, failed).describe())
    assert "확인 실패" in text
    assert "재정이 없다는 뜻이 아니다" in text


# ----------------------------------------------------------------------
# 재수집과 번역
# ----------------------------------------------------------------------
def test_translations_survive_a_refetch():
    before = ruling_set(qa(1, "はい"))
    before.rulings[0].add_translation(
        RulingTranslation(language="ko", source=TranslationSource.MACHINE_TRANSLATION,
                          answer="예")
    )
    after = merge_translations(before, ruling_set(qa(1, "はい")))
    assert after.rulings[0].translation("ko").answer == "예"


def test_translation_is_marked_stale_when_the_original_changed():
    before = ruling_set(qa(1, "はい"))
    before.rulings[0].add_translation(
        RulingTranslation(language="ko", source=TranslationSource.MACHINE_TRANSLATION,
                          answer="예")
    )
    after = merge_translations(before, ruling_set(qa(1, "いいえ")))
    translation = after.rulings[0].translation("ko")
    assert translation is not None
    assert translation.is_stale(after.rulings[0].content_hash)


# ----------------------------------------------------------------------
# 어댑터의 실패 경로 (네트워크 없이)
# ----------------------------------------------------------------------
def test_network_failure_yields_source_unavailable(tmp_path):
    def boom(url: str) -> str:
        raise OSError("연결 거부")

    adapter = OfficialOcgRulingAdapter(cache_dir=tmp_path, delay=0, opener=boom)
    result = adapter.fetch_ruling_set(4007, card_id=89631139)
    assert result.availability is RulingAvailability.SOURCE_UNAVAILABLE
    assert "연결 거부" in result.error
    assert result.rulings == []
    assert not result.confirmed


def test_card_with_no_qa_is_ruling_not_found(tmp_path):
    """Q&A 가 하나도 없는 정상 페이지는 '재정 없음'이다."""
    empty = (
        '<meta name="keywords" content="テストカード,Q&A">'
        '<div id="card_text">テキスト</div>'
    )
    adapter = OfficialOcgRulingAdapter(
        cache_dir=tmp_path, delay=0, opener=lambda url: empty
    )
    result = adapter.fetch_ruling_set(1)
    assert result.availability is RulingAvailability.NOT_FOUND
    assert result.confirmed
    assert result.name_ja == "テストカード"


def test_supplement_only_card_counts_as_having_rulings(tmp_path):
    page = (
        '<meta name="keywords" content="テストカード,Q&A">'
        '<div id="card_text">テキスト</div>'
        '<div class="supplement"><span class="update ">2024-01-01</span>'
        '<div id="supplement">■補足です。</div></div>'
    )
    adapter = OfficialOcgRulingAdapter(
        cache_dir=tmp_path, delay=0, opener=lambda url: page
    )
    result = adapter.fetch_ruling_set(1)
    assert result.availability is RulingAvailability.EXISTS
    assert result.rulings == []
    assert result.supplement.text_original == "■補足です。"


def test_detail_failure_marks_the_whole_card_unavailable(tmp_path):
    """
    목록은 받았는데 상세를 못 받았으면 **부분 결과를 완성품처럼 저장하지
    않는다.**
    """
    listing = fixture_html("faq_4007")

    def opener(url: str) -> str:
        if "ope=5" in url:
            return "<html>broken</html>"
        return listing

    adapter = OfficialOcgRulingAdapter(
        cache_dir=tmp_path, delay=0, opener=opener, use_cache=False
    )
    result = adapter.fetch_ruling_set(4007)
    assert result.availability is RulingAvailability.SOURCE_UNAVAILABLE
    assert "상세 실패" in result.error


def test_cache_prevents_repeat_requests(tmp_path):
    calls = []

    def opener(url: str) -> str:
        calls.append(url)
        return "<html></html>"

    adapter = OfficialOcgRulingAdapter(cache_dir=tmp_path, delay=0, opener=opener)
    adapter.fetch(adapter.list_url(1))
    adapter.fetch(adapter.list_url(1))
    assert len(calls) == 1
    assert adapter.request_count == 1


def test_fetch_error_is_raised_not_swallowed(tmp_path):
    def boom(url: str) -> str:
        raise TimeoutError("느림")

    adapter = OfficialOcgRulingAdapter(cache_dir=tmp_path, delay=0, opener=boom)
    with pytest.raises(RulingFetchError):
        adapter.fetch("https://example.invalid/")
