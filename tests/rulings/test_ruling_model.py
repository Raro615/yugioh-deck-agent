"""
CardRuling 모델 — 원문 보존, provenance, 번역 분리, 세 가지 확인 결과.
"""

import pytest

from rulings.ruling_model import (
    CardRuling,
    CardRulingSet,
    CardRulingSupplement,
    RulingAvailability,
    RulingGame,
    RulingKind,
    RulingProvenance,
    RulingSource,
    RulingTranslation,
    TranslationSource,
    TranslationStatus,
)

JA_QUESTION = "「青眼の白龍」の効果はダメージステップに発動できますか？"
JA_ANSWER = "はい、発動できます。"


def make_ruling(**kwargs) -> CardRuling:
    defaults = dict(
        ruling_id="OCG-QA-24359",
        card_id=89631139,
        official_cid=4007,
        question_original=JA_QUESTION,
        answer_original=JA_ANSWER,
        published_or_updated_at="2026-07-05",
        ruling_category="モンスター",
    )
    defaults.update(kwargs)
    return CardRuling(**defaults)


# ----------------------------------------------------------------------
# Q&A 와 補足情報 의 구분
# ----------------------------------------------------------------------
def test_qa_and_supplement_are_different_types():
    """
    하나의 텍스트 필드로 합치면 "질문에 대한 답"인지 "카드에 대한 보충"인지
    구분할 수 없게 된다.
    """
    qa = make_ruling()
    supplement = CardRulingSupplement(
        ruling_id="OCG-SUP-4007",
        card_id=89631139,
        official_cid=4007,
        text_original="■「ブルーアイズ」モンスターです。",
        published_or_updated_at="2021-07-10",
    )
    assert qa.kind is RulingKind.QA
    assert supplement.kind is RulingKind.SUPPLEMENT
    assert type(qa) is not type(supplement)
    # 補足 에는 question/answer 자체가 없다.
    assert not hasattr(supplement, "question_original")
    assert not hasattr(supplement, "answer_original")
    # 날짜도 따로 갖는다.
    assert qa.published_or_updated_at != supplement.published_or_updated_at
    # provenance 의 data_type 도 다르다.
    assert qa.provenance.data_type == "card_ruling"
    assert supplement.provenance.data_type == "card_supplement"


def test_ruling_id_prefixes_are_distinct():
    assert make_ruling().ruling_id.startswith("OCG-QA-")
    supplement = CardRulingSupplement(
        ruling_id="OCG-SUP-4007", card_id=1, official_cid=4007
    )
    assert supplement.ruling_id.startswith("OCG-SUP-")


def test_fid_is_recoverable_from_the_ruling_id():
    assert make_ruling().fid == 24359


# ----------------------------------------------------------------------
# provenance
# ----------------------------------------------------------------------
def test_default_provenance_is_official_japanese_ocg():
    ruling = make_ruling()
    provenance = ruling.provenance
    assert provenance.source is RulingSource.KONAMI_OCG_DATABASE
    assert provenance.language == "ja"
    assert provenance.authority == "official"
    assert provenance.game is RulingGame.OCG


def test_only_the_official_database_is_a_ruling_source():
    """비공식 위키·커뮤니티 재정은 타입 자체가 존재하지 않는다."""
    assert [s.value for s in RulingSource] == ["konami_ocg_database"]


def test_ocg_and_tcg_are_separate_values():
    assert RulingGame.OCG.value == "ocg"
    assert RulingGame.TCG.value == "tcg"
    assert RulingGame.OCG is not RulingGame.TCG


# ----------------------------------------------------------------------
# 원문 보존
# ----------------------------------------------------------------------
def test_original_text_is_japanese_and_untouched():
    ruling = make_ruling()
    assert ruling.question_original == JA_QUESTION
    assert ruling.answer_original == JA_ANSWER


def test_content_hash_follows_the_text():
    first = make_ruling()
    second = make_ruling(answer_original="いいえ、発動できません。")
    assert first.content_hash != second.content_hash
    assert first.content_hash == make_ruling().content_hash
    assert first.content_hash.startswith("sha256:")


def test_content_hash_collapses_runs_of_spaces_but_never_deletes_them():
    """
    공백을 전부 지우면 안 된다. 공식 카드명에는 공백이 들어간다
    (「完全なる世界 トゥーン・ワールド」). 지우면 다른 카드명과 같아질 수 있다.
    그래서 **연속 공백을 하나로 줄이기만** 한다.
    """
    base = make_ruling(answer_original="「完全なる世界 トゥーン・ワールド」です。")
    collapsed = make_ruling(answer_original="「完全なる世界  トゥーン・ワールド」です。")
    assert collapsed.content_hash == base.content_hash          # 연속 공백은 같게

    removed = make_ruling(answer_original="「完全なる世界トゥーン・ワールド」です。")
    assert removed.content_hash != base.content_hash            # 공백 제거는 다르게

    newline = make_ruling(answer_original="はい、\n発動できます。")
    assert newline.content_hash != make_ruling().content_hash   # 줄바꿈은 의미가 있다


# ----------------------------------------------------------------------
# 번역 분리
# ----------------------------------------------------------------------
def test_translation_never_replaces_the_original():
    ruling = make_ruling()
    ruling.add_translation(
        RulingTranslation(
            language="ko",
            source=TranslationSource.MACHINE_TRANSLATION,
            question="「푸른 눈의 백룡」의 효과는 데미지 스텝에 발동할 수 있습니까?",
            answer="예, 발동할 수 있습니다.",
        )
    )
    assert ruling.question_original == JA_QUESTION  # 원문 그대로
    assert ruling.answer_original == JA_ANSWER
    assert ruling.translation("ko").answer == "예, 발동할 수 있습니다."
    assert ruling.provenance.language == "ja"


def test_translation_is_never_authoritative():
    for source in TranslationSource:
        translation = RulingTranslation(language="ko", source=source)
        assert translation.authoritative is False


def test_translation_source_cannot_be_an_official_ruling_source():
    """
    타입이 달라서 번역이 공식 출처 자리에 들어갈 수 없다.
    """
    translation_values = {s.value for s in TranslationSource}
    ruling_values = {s.value for s in RulingSource}
    assert translation_values.isdisjoint(ruling_values)
    assert "machine_translation" in translation_values


def test_translation_goes_stale_when_the_original_changes():
    ruling = make_ruling()
    ruling.add_translation(
        RulingTranslation(language="ko", source=TranslationSource.MACHINE_TRANSLATION)
    )
    translation = ruling.translation("ko")
    assert translation.source_content_hash == ruling.content_hash
    assert not translation.is_stale(ruling.content_hash)

    updated = make_ruling(answer_original="いいえ。")
    assert translation.is_stale(updated.content_hash)


def test_translation_status_is_tracked():
    translation = RulingTranslation(
        language="ko",
        source=TranslationSource.HUMAN_TRANSLATION,
        status=TranslationStatus.REVIEWED,
        translator="사람",
    )
    assert translation.status is TranslationStatus.REVIEWED


# ----------------------------------------------------------------------
# 세 가지 확인 결과
# ----------------------------------------------------------------------
def test_not_found_and_source_unavailable_are_different():
    """이 구분이 무너지면 '확인 못 했다'가 '재정이 없다'로 둔갑한다."""
    not_found = CardRulingSet(
        official_cid=1, availability=RulingAvailability.NOT_FOUND
    )
    unavailable = CardRulingSet(
        official_cid=2,
        availability=RulingAvailability.SOURCE_UNAVAILABLE,
        error="timeout",
    )
    assert not_found.availability is not unavailable.availability
    assert not_found.confirmed is True        # 정상적으로 조회했다
    assert unavailable.confirmed is False     # 아무것도 결론 내리지 않는다
    assert not not_found.has_rulings and not unavailable.has_rulings


def test_availability_has_exactly_three_states():
    assert {a.value for a in RulingAvailability} == {
        "ruling_exists",
        "ruling_not_found",
        "source_unavailable",
    }


def test_incomplete_collection_is_detectable():
    """공식이 88건이라 했는데 2건만 받았으면 완결되지 않은 것이다."""
    ruling_set = CardRulingSet(
        official_cid=4007,
        availability=RulingAvailability.EXISTS,
        reported_total=88,
        rulings=[make_ruling(), make_ruling(ruling_id="OCG-QA-2")],
    )
    assert not ruling_set.complete
    ruling_set.reported_total = 2
    assert ruling_set.complete


# ----------------------------------------------------------------------
# 직렬화
# ----------------------------------------------------------------------
def test_round_trip_preserves_everything():
    ruling = make_ruling(related_card_cids=[4041, 4798], related_card_ids=[46986414])
    ruling.add_translation(
        RulingTranslation(language="ko", source=TranslationSource.MACHINE_TRANSLATION,
                          question="q", answer="a")
    )
    supplement = CardRulingSupplement(
        ruling_id="OCG-SUP-4007", card_id=89631139, official_cid=4007,
        text_original="■テキスト", published_or_updated_at="2021-07-10",
    )
    ruling_set = CardRulingSet(
        official_cid=4007, card_id=89631139,
        availability=RulingAvailability.EXISTS,
        name_ja="青眼の白龍", card_text_ja="高い攻撃力",
        rulings=[ruling], supplement=supplement, reported_total=1,
        checked_at="2026-09-17T00:00:00Z",
    )
    restored = CardRulingSet.from_json(ruling_set.to_json())
    assert restored.to_json() == ruling_set.to_json()
    assert restored.rulings[0].question_original == JA_QUESTION
    assert restored.rulings[0].translation("ko").answer == "a"
    assert restored.supplement.text_original == "■テキスト"


def test_unknown_schema_version_is_rejected():
    with pytest.raises(ValueError, match="schema_version"):
        CardRulingSet.from_json({"schema_version": 99, "official_cid": 1,
                                 "availability": "ruling_not_found"})
