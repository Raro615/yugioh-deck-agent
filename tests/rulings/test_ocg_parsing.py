"""
공식 사이트 HTML 파싱.

픽스처는 공식 사이트에서 실제로 받은 페이지 그대로다 (gzip 으로만 압축).
손으로 지어낸 HTML 로 시험하면 사이트가 바뀌어도 테스트가 계속 통과한다.
"""

import pytest

from sources.ocg_ruling_adapter import (
    OfficialOcgRulingAdapter,
    RulingFetchError,
    _to_text,
)
from tests.rulings.conftest import fixture_html

LIST_PAGE = "faq_4007"      # 青眼の白龍 Q&A 목록 (補足情報 있음)
DETAIL_PAGE = "detail_24359"  # 개별 Q&A


# ----------------------------------------------------------------------
# URL
# ----------------------------------------------------------------------
def test_urls_are_official_and_japanese():
    list_url = OfficialOcgRulingAdapter.list_url(4007)
    detail_url = OfficialOcgRulingAdapter.detail_url(24359)
    for url in (list_url, detail_url):
        assert url.startswith("https://www.db.yugioh-card.com/yugiohdb/")
        assert "request_locale=ja" in url
    assert "ope=4" in list_url and "cid=4007" in list_url
    assert "ope=5" in detail_url and "fid=24359" in detail_url


def test_list_url_carries_pagination():
    url = OfficialOcgRulingAdapter.list_url(4007, page=3, rows=100)
    assert "page=3" in url and "rp=100" in url


# ----------------------------------------------------------------------
# 목록 페이지
# ----------------------------------------------------------------------
def test_card_page_gives_japanese_name_text_and_total():
    source = fixture_html(LIST_PAGE)
    page = OfficialOcgRulingAdapter.parse_card_page(
        4007, OfficialOcgRulingAdapter.list_url(4007), source
    )
    assert page.available
    assert page.name_ja == "青眼の白龍"
    assert page.card_text_ja.startswith("高い攻撃力を誇る伝説のドラゴン")
    assert page.total == 88


def test_rows_carry_fid_category_and_date():
    rows = OfficialOcgRulingAdapter.parse_rows(fixture_html(LIST_PAGE))
    assert len(rows) == 10
    first = rows[0]
    assert first.fid == 24359
    assert first.category == "魔法"
    assert first.updated_at == "2026-07-05"
    assert first.question_title.endswith("無効化されますか？")
    assert all(row.fid > 0 for row in rows)
    assert len({row.fid for row in rows}) == len(rows)


def test_supplement_is_parsed_separately_from_qa():
    """補足情報 는 Q&A 와 다른 성격이므로 따로 뽑는다."""
    supplement = OfficialOcgRulingAdapter.parse_supplement(fixture_html(LIST_PAGE))
    assert supplement is not None
    updated_at, text = supplement
    assert updated_at == "2021-07-10"
    assert text == "■「ブルーアイズ」モンスターです。"
    # 補足 날짜는 Q&A 날짜와 다르다 — 합쳐서 하나로 만들면 안 된다.
    rows = OfficialOcgRulingAdapter.parse_rows(fixture_html(LIST_PAGE))
    assert updated_at != rows[0].updated_at


def test_missing_supplement_returns_none_not_empty_string():
    """補足情報 가 없는 카드를 '빈 補足' 으로 만들지 않는다."""
    source = fixture_html(LIST_PAGE).replace('<div class="supplement">', '<div class="x">')
    assert OfficialOcgRulingAdapter.parse_supplement(source) is None


# ----------------------------------------------------------------------
# 상세 페이지
# ----------------------------------------------------------------------
def test_detail_keeps_japanese_question_and_answer():
    detail = OfficialOcgRulingAdapter.parse_detail(24359, fixture_html(DETAIL_PAGE))
    assert detail["question"].startswith("以下のカード名を宣言し")
    assert detail["answer"].startswith("（A）無効化されます。")
    # 원문은 일본어 그대로다 — 어디서도 번역하지 않는다.
    assert "無効化" in detail["answer"]
    assert detail["ruling_category"] == "魔法"
    assert detail["updated_at"] == "2026-07-05"


def test_detail_preserves_paragraph_breaks():
    """공식 답변은 ``<br>`` 로만 문단을 나눈다. 없애면 의미가 뭉개진다."""
    detail = OfficialOcgRulingAdapter.parse_detail(24359, fixture_html(DETAIL_PAGE))
    assert "\n" in detail["answer"]
    assert "（A）無効化されます。\n\n（B）無効化されません。" in detail["answer"]


def test_detail_collects_officially_linked_related_cards():
    """관련 카드는 공식 페이지가 **직접 건 링크**만 쓴다. 추론하지 않는다."""
    detail = OfficialOcgRulingAdapter.parse_detail(24359, fixture_html(DETAIL_PAGE))
    related = detail["related_card_cids"]
    assert len(related) > 10
    assert related == sorted(set(related))
    assert 23161 in related  # 完全なる世界 トゥーン・ワールド
    assert 4798 in related   # トゥーン・ワールド


def test_detail_failure_is_loud_not_silent():
    """구조가 바뀌면 조용히 빈 재정을 만들지 않고 실패한다."""
    with pytest.raises(RulingFetchError, match="구조가 바뀌었"):
        OfficialOcgRulingAdapter.parse_detail(1, "<html><body>nothing</body></html>")


# ----------------------------------------------------------------------
# 텍스트 변환
# ----------------------------------------------------------------------
def test_to_text_unescapes_and_keeps_line_breaks():
    assert _to_text("A<br>B") == "A\nB"
    assert _to_text("&lt;tag&gt;") == "<tag>"
    assert _to_text('<a href="x">「カード名」</a>です') == "「カード名」です"
    assert _to_text("  a  \n  b  ") == "a\nb"
