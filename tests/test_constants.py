"""비트마스크 상수와 한국어 어휘 테이블 검증."""

from core import constants as C


def test_type_bitmask_decoding_matches_real_cards():
    # Dark Magician (id 46986414) 의 type 값 17 = 0x11
    assert set(C.decode_bitmask(17, C.TYPE_NAMES)) == {"MONSTER", "NORMAL"}
    # Ten Thousand Dragon (id 10000) — 특수 소환 몬스터
    assert set(C.decode_bitmask(33554465, C.TYPE_NAMES)) == {
        "MONSTER",
        "EFFECT",
        "SPSUMMON",
    }
    # Banner of Courage (id 10012614) — 지속 마법
    assert set(C.decode_bitmask(131074, C.TYPE_NAMES)) == {"SPELL", "CONTINUOUS"}


def test_race_and_attribute_values():
    assert C.RACE_SPELLCASTER == 0x2
    assert C.RACE_MACHINE == 0x20
    assert C.RACE_DRAGON == 0x2000
    assert C.ATTRIBUTE_LIGHT == 0x10
    assert C.ATTRIBUTE_DARK == 0x20


def test_korean_vocabulary_is_complete():
    # 모든 종족/속성에 한국어 표기가 있어야 쿼리 파서가 전부 인식한다.
    assert set(C.RACE_KO) == set(C.RACE_NAMES)
    assert set(C.ATTRIBUTE_KO) == set(C.ATTRIBUTE_NAMES)
    assert set(C.RACE_TEXT_EN) == set(C.RACE_NAMES)


def test_korean_aliases_resolve_to_correct_bits():
    assert C.KO_RACE_ALIASES["기계족"] == C.RACE_MACHINE
    assert C.KO_RACE_ALIASES["마법사족"] == C.RACE_SPELLCASTER
    assert C.KO_ATTRIBUTE_ALIASES["빛속성"] == C.ATTRIBUTE_LIGHT
    assert C.KO_ATTRIBUTE_ALIASES["어둠속성"] == C.ATTRIBUTE_DARK


def test_encode_roundtrip():
    mask = C.encode_bitmask(["MONSTER", "EFFECT"], C.TYPE_NAMES)
    assert mask == C.TYPE_MONSTER | C.TYPE_EFFECT
    assert set(C.decode_bitmask(mask, C.TYPE_NAMES)) == {"MONSTER", "EFFECT"}
