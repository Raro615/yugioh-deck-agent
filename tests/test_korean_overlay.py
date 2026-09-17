"""
한국어 오버레이 검증.

주의: 여기 쓰는 문자열은 공식 한국어 카드명이 아니라 파이프라인 동작 확인용
더미 값이다. 이 프로젝트는 공식 카드명/텍스트를 임의로 번역하지 않는다.
"""

import json

from core.card_model import Card, CardSource
from sources.korean_names import KoreanTextSource


def _sample_cards() -> dict[int, Card]:
    return {
        46986414: Card(
            id=46986414,
            name="Dark Magician",
            name_en="Dark Magician",
            name_ja="ブラック・マジシャン",
            desc="ORIGINAL TEXT",
        )
    }


def test_json_overlay_sets_korean_name_and_keeps_originals(tmp_path):
    path = tmp_path / "ko.json"
    path.write_text(
        json.dumps({"46986414": {"name": "표시명", "desc": "한국어 텍스트"}}),
        encoding="utf-8",
    )
    source = KoreanTextSource.load(path)
    cards = _sample_cards()
    assert source.apply(cards) == 1

    card = cards[46986414]
    assert card.name_ko == "표시명"
    assert card.display_name() == "표시명"
    # 원문은 지우지 않는다 — 검색이 세 언어를 모두 대조하기 때문이다.
    assert card.name_en == "Dark Magician"
    assert card.name_ja == "ブラック・マジシャン"
    assert CardSource.KOREAN_OVERLAY in card.sources


def test_csv_overlay(tmp_path):
    path = tmp_path / "ko.csv"
    path.write_text("id,name,desc\n46986414,표시명,본문\n", encoding="utf-8")
    cards = _sample_cards()
    assert KoreanTextSource.load(path).apply(cards) == 1
    assert cards[46986414].name_ko == "표시명"


def test_missing_directory_yields_empty_source_not_an_error(tmp_path):
    source = KoreanTextSource.autoload(tmp_path / "does-not-exist")
    assert not source
    assert source.apply(_sample_cards()) == 0


def test_display_name_falls_back_when_no_korean_data():
    card = Card(id=1, name="Some Card", name_en="Some Card")
    assert card.display_name() == "Some Card"
