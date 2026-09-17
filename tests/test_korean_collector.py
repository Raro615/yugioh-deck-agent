"""공식 한국어 DB 수집기의 파싱 로직 검증 (네트워크 없이 동작)."""

import pytest

from scripts.fetch_korean_db import (
    _clean,
    join_with_passcodes,
    parse_list_page,
    total_count,
)

SAMPLE_ROW = """
<div class="t_row c_normal open">
  <dl class="flex_1">
    <dd class="box_card_name flex_1 top_set">
      <span class="card_name">&quot;A&quot; 세포 배양 장치</span>
    </dd>
    <dd class="box_card_text c_text flex_1 text_linebreak">
      어둠 속성 튜너 ＋ 튜너 이외의 몬스터 1장 이상&lt;br&gt;①: 발동할 수 있다.
    </dd>
  </dl>
  <input type="hidden" class="cid" value="7315">
  <input type="hidden" class="cnm" value='&quot;A&quot; 세포 배양 장치'>
</div><!-- .t_row c_normal -->
"""


def test_clean_unescapes_and_strips_tags():
    assert _clean("<span>&quot;A&quot; 세포</span>") == '"A" 세포'


def test_clean_converts_escaped_br_to_newline():
    """
    카드 텍스트에는 엔티티로 이스케이프된 <br> 이 들어 있다.
    언이스케이프 후에야 태그 모양이 되므로 양쪽에서 처리해야 한다.
    """
    result = _clean("소재 1장 이상&lt;br&gt;①: 효과")
    assert result.split("\n") == ["소재 1장 이상", "①: 효과"]


def test_clean_converts_real_br_to_newline():
    assert _clean("첫 줄<br>둘째 줄").split("\n") == ["첫 줄", "둘째 줄"]


def test_parse_list_page_extracts_cid_name_and_text():
    cards = parse_list_page(SAMPLE_ROW)
    assert len(cards) == 1
    card = cards[0]
    assert card["cid"] == "7315"
    assert card["name"] == '"A" 세포 배양 장치'
    assert card["desc"].startswith("어둠 속성 튜너")
    assert "\n①: 발동할 수 있다." in card["desc"]


def test_total_count_reads_result_header():
    assert total_count("검색결과 13,772건 중 1～100건을 표시") == 13772
    assert total_count("관련 없는 문자열") is None


def test_join_applies_korean_text_to_every_printing():
    """하나의 cid 에 달린 모든 패스코드(다른 일러스트)에 같은 표기를 적용한다."""
    cards = [{"cid": "4041", "name": "블랙 매지션", "desc": "최고의 공격력과 수비력을 자랑하는 마술사."}]
    cid_map = {"4041": [46986414, 46986420]}
    entries, unmatched = join_with_passcodes(cards, cid_map)
    assert unmatched == []
    assert set(entries) == {"46986414", "46986420"}
    assert entries["46986420"]["name"] == "블랙 매지션"


def test_join_reports_cards_without_a_passcode():
    cards = [{"cid": "999999", "name": "미매칭 카드", "desc": ""}]
    entries, unmatched = join_with_passcodes(cards, {})
    assert entries == {}
    assert len(unmatched) == 1
    assert unmatched[0]["name"] == "미매칭 카드"


def test_parse_real_cached_page_if_available():
    """실제로 받아둔 페이지가 있으면 100장이 온전히 파싱되는지 확인한다."""
    from pathlib import Path

    from scripts.fetch_korean_db import CACHE_DIR

    import json

    cached = CACHE_DIR / "page_001.json"
    if not cached.is_file():
        pytest.skip("수집 캐시 없음")
    cards = json.loads(cached.read_text(encoding="utf-8"))["cards"]
    assert len(cards) == 100
    assert all(c["cid"].isdigit() for c in cards)
    assert all(c["name"] for c in cards)
    # 카드 텍스트에 태그 잔재가 남아 있으면 안 된다.
    assert not any("<br" in c["desc"] or "&lt;" in c["desc"] for c in cards)
