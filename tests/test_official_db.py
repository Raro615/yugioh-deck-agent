"""공식 DB 인코딩 해석 검증 (데이터베이스 파일 없이 동작하는 단위 테스트)."""

from sources.official_db import unpack_level, unpack_setcodes


def test_unpack_level_plain_monster():
    # Dark Magician: level 컬럼이 그대로 레벨
    assert unpack_level(7) == (7, None, None)


def test_unpack_level_pendulum_scales():
    # D/D Savant Thomas: 0x06060008 -> 레벨 8, 스케일 6/6
    assert unpack_level(0x06060008) == (8, 6, 6)
    # 최댓값 사례: 0x0D0C000C -> 레벨 12, 스케일 12/13
    assert unpack_level(0x0D0C000C) == (12, 12, 13)


def test_unpack_setcodes_single_and_multiple():
    assert unpack_setcodes(0) == []
    assert unpack_setcodes(0x17F) == [0x17F]
    # D/D Savant Thomas: 0xAF 와 0x6E 두 카드군에 속한다
    assert unpack_setcodes(0x006E00AF) == [0xAF, 0x6E]


def test_unpack_setcodes_handles_negative_from_sqlite():
    # SQLite 는 64비트 부호 있는 정수를 쓰므로 최상위 비트가 서면 음수로 읽힌다.
    packed = 0xFFFF_0000_0000_0001
    signed = packed - (1 << 64)
    assert unpack_setcodes(signed) == [0x1, 0xFFFF]
