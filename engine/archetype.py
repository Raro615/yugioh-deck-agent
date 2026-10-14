"""
카드군(아키타입) 소속 판정 — **데이터 형식의 사실 한 가지**만 담는다.

``cards.cdb`` 의 ``datas.setcode`` 는 16비트 카드군 코드 **4개**를 한 정수에
담는다 (``sources/official_db.py::unpack_setcodes``). 풀어낸 코드 하나는 다시
두 조각이다.

    0x3008  =  base 0x008 (하위 12비트)  +  subtype 0x3 (상위 4비트)
               └ "히어로" 라는 큰 묶음      └ "엘리멘틀" 이라는 작은 묶음

그래서 "이 카드가 「히어로」 카드인가" 와 "이 카드가 「엘리멘틀 히어로」
카드인가" 가 **한 체계 안에서** 표현된다. 둘을 따로 묻는 카드가 실제로
있으므로 그 구분이 필요하다.

왜 하위 12비트는 **같아야** 하고 상위 4비트는 **포함**이면 되는가
-----------------------------------------------------------------
이 저장소의 데이터로 재서 정했다. 추측이 아니다.

1. ``data/constants/archetype_setcode_constants.lua`` 의 ``SET_*`` 상수
   **615개** 중 **136개**가 상위 4비트를 쓴다. base 를 **78개**의 서로 다른
   상수들이 공유하고, 공유하는 쪽에서 더 좁은 이름이 상위 비트를 갖는다::

       SET_HERO            0x008      6장
       SET_ELEMENTAL_HERO  0x3008    82장
       SET_VISION_HERO     0x5008    10장
       SET_EVIL_HERO       0x6008    19장
       SET_MASKED_HERO     0xa008    13장
       SET_DESTINY_HERO    0xc008    29장

2. **공식 카드 텍스트가 포함 관계를 직접 말한다.** 엘리멘틀 히어로 에어맨
   (40044918) 의 공식 한국어 원문은 「덱에서 "히어로" 몬스터 1장을 패에
   넣는다」 이고, 그 스크립트는 ``IsSetCard(SET_HERO)`` = ``0x008`` 로
   묻는다. 그런데 엘리멘틀 히어로 카드들이 들고 있는 코드는 ``0x3008``
   이다. 질의한 subtype(``0``)이 카드의 subtype(``0x3``)에 **포함**되면
   참이라고 읽지 않으면, 이 카드의 공식 효과가 엘리멘틀 히어로를 **한 장도**
   찾지 못한다. 반대 방향은 성립하지 않아야 한다 — ``0x3008`` 로 물었을 때
   ``0x008`` 만 가진 카드(엑스트라 히어로 원더 드라이버)가 걸리면 그것은
   「엘리멘틀 히어로」 가 아닌 카드를 그렇다고 말하는 것이다.

여기서 하지 않는 것
-------------------
**효과로 카드군이 더해지는 경우를 보지 않는다.** 「이 카드명은 룰상 "X"
카드로도 취급한다」 가 카드 자신에 적혀 있는 경우는 ``cards.cdb`` 가 이미
코드로 넣어 두었다 (미라클 엑스클루더 30875635 → ``0x3008``). 그러나 **다른
카드의 지속 효과**가 카드군을 더하는 경우는 이 저장소의 엔진에 지속 효과
계층이 아예 없어서 (STRUCTURAL-76) 표현되지 않는다. 그 계층이 생기는 날
:func:`matches_setcode` 를 부르는 쪽이 더해진 코드까지 넘겨야 한다 —
이 함수는 받은 코드 목록만 본다.
"""

from __future__ import annotations

from typing import Iterable

#: 카드군의 **큰 묶음** 이 들어 있는 자리 (하위 12비트).
SETCODE_BASE_MASK = 0xFFF

#: 카드군의 **작은 묶음** 이 들어 있는 자리 (상위 4비트).
SETCODE_SUBTYPE_MASK = 0xF000

#: 코드 하나가 들어가는 크기. ``datas.setcode`` 가 16비트씩 4개를 담는다.
SETCODE_MAX = 0xFFFF


def validate_setcode(code: object) -> int:
    """
    카드군 코드 하나가 **코드일 수 있는 값**인지 본다. 아니면 ``ValueError``.

    실측 근거: 이 저장소의 ``SET_*`` 상수 615개 중 base 가 0 인 것이 **0개**,
    ``0xFFFF`` 를 넘는 것이 **0개**다. 카드 14,127장이 들고 있는 코드에도
    base 가 0 인 것이 **0개**다. 그래서 둘 다 "있을 수 없는 값" 이고, 조용히
    통과시키면 **아무 카드와도 맞지 않는 조건**이 만들어진다.
    """
    if isinstance(code, bool) or not isinstance(code, int):
        raise TypeError(f"카드군 코드는 정수입니다: {code!r}")
    if not 0 < code <= SETCODE_MAX:
        raise ValueError(
            f"카드군 코드는 1 이상 0x{SETCODE_MAX:x} 이하입니다: 0x{code:x}"
        )
    if not code & SETCODE_BASE_MASK:
        raise ValueError(
            f"하위 12비트가 0 인 카드군 코드는 없습니다: 0x{code:x}. "
            "상위 4비트는 큰 묶음 안의 작은 묶음을 가리키므로 혼자 쓸 수 "
            "없습니다."
        )
    return code


def matches_setcode(card_setcodes: Iterable[int], query: int) -> bool:
    """
    ``card_setcodes`` 를 가진 카드가 ``query`` 카드군에 **속하는가**.

    하위 12비트는 같아야 하고, 질의한 상위 4비트는 카드가 가진 상위 4비트에
    **포함**되어야 한다 (모듈 설명의 근거 2). 카드가 코드를 하나도 갖고
    있지 않으면 거짓이다 — 카드 14,127장 중 **6,221장(44.0%)** 이 그렇고,
    그것은 "모른다" 가 아니라 "어느 카드군에도 속하지 않는다" 다.
    """
    base = query & SETCODE_BASE_MASK
    subtype = query & SETCODE_SUBTYPE_MASK
    for code in card_setcodes:
        if code & SETCODE_BASE_MASK != base:
            continue
        if code & SETCODE_SUBTYPE_MASK & subtype == subtype:
            return True
    return False


__all__ = [
    "SETCODE_BASE_MASK",
    "SETCODE_SUBTYPE_MASK",
    "SETCODE_MAX",
    "validate_setcode",
    "matches_setcode",
]
