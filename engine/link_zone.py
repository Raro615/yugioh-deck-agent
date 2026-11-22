"""
링크 마커가 **가리키는 내 몬스터 존** — 그리고 그 답을 확정할 수 없는 자리.

    GameStateView
        ↓  pointed_zone_verdict(view, player)      ← 이 파일
    PointedZoneVerdict      확정 가능 / 확정 불가 / 가리키는 것이 없다
        ↓  ActionValidator          (성유물－『성관』 의 소환 절차가 읽는다)
        ↓  Duel._hand_procedure_actions
    LegalActions

왜 이 계층이 따로 필요한가
--------------------------
「성유물－『성관』」 의 공식 텍스트는 **놓을 자리를 조건으로** 적는다 —
*"You can Special Summon this card (from your hand) in Defense Position to
your zone a Link Monster points to."* 공식 스크립트도 같은 자리를 값으로
돌려준다 (``c27918365.lua`` 의 ``e1``)::

    e1:SetCode(EFFECT_SPSUMMON_PROC)
    e1:SetRange(LOCATION_HAND)
    e1:SetTargetRange(POS_FACEUP_DEFENSE,0)
    e1:SetCountLimit(1,id,EFFECT_COUNT_CODE_OATH)
    e1:SetValue(function(e,c) return 0,aux.GetMMZonesPointedTo(c:GetControler()) end)

그래서 "어느 칸을 가리키는가" 를 모르면 이 카드는 **발동 여부조차** 답할 수
없다. 그 질문에 답하는 계층이 6-BK 전까지 **아예 없었다**:
:attr:`~engine.game_state_view.CardDefinitionView.link_marker_mask` 는
관측에 실려 있었지만 **읽는 쪽이 하나도 없었다** (실측: 6-BJ 시점에
``link_marker_mask`` 를 읽는 코드는 생산 코드에 0곳).

🔴 **대응표의 출처가 이 저장소에 없다**
---------------------------------------
화살표 **방향**은 vendoring 된 상수에서 읽었다
(``data/constants/constant.lua``)::

    LINK_MARKER_BOTTOM_LEFT  = 0x1     LINK_MARKER_LEFT  = 0x8
    LINK_MARKER_BOTTOM       = 0x2     LINK_MARKER_RIGHT = 0x20
    LINK_MARKER_BOTTOM_RIGHT = 0x4     ...
    ZONES_MMZ = 0x1f    -- 메인 몬스터 존은 칸 0~4
    ZONES_EMZ = 0x60    -- 엑스트라 몬스터 존은 칸 5·6

칸 **번호**도 거기서 읽었다. 그러나 **어느 화살표가 어느 번호를
가리키는가** 는 어디에도 없다:

* 룰북(``sd-rulebook-en-v10``)은 "가리키는 존" 의 **존재**와 **선택권**만
  적는다 — *"you can also Summon monsters from the Extra Deck to any of
  your Main Monster Zones that has a Link Monster's red arrow pointing to
  it"* (§16) · *"If 2 Extra Monster Zones are available, you can choose
  either one"* (§17). **어느 칸인지는 그림에만 있다.** structured 쪽도 그
  사실을 적어 둔다 — ``zones[Extra Monster Zone].not_stated`` 에
  ``ordering`` 이 있다.
* ``aux.GetMMZonesPointedTo`` 는 **호출 자리만** vendoring 되어 있고
  (``c27918365.lua`` 등) **정의가 없다**. 이 저장소에 ``utility.lua`` 가
  없다.

그래서 이 파일은 **정렬 하나를 고르지 않는다.** 가능한 정렬을
:data:`EMZ_ALIGNMENTS` 로 전부 들고 다니면서, **모든 정렬에서 같은 답이
나올 때만 확정**한다 (ADR-006 — 읽지 못한 것은 허가가 아니다).

무엇을 확정할 수 있고 무엇을 할 수 없는가 (실측)
------------------------------------------------
기르수 패의 기준 전개에서 네 시점을 재면 이렇게 갈린다:

=========================================  ===================  ========
시점                                        EMZ 왼쪽 / 오른쪽     답
=========================================  ===================  ========
성관을 가져온 직후 (갈라테아i 링크1 좌하)      칸 0 막힘 / 칸 2 빔   **확정 불가**
갈라테아 링크 소환 직후 (링크2 좌하)           칸 0 빔 / 칸 2 빔     **놓을 수 있다**
갈라테아i 소생 직후                           칸 0 막힘 / 칸 2 빔   **확정 불가**
롱기르수 링크 소환 직후 (링크3 우하)           칸 2 빔 / 칸 4 빔     **놓을 수 있다**
=========================================  ===================  ========

🔴 **확정되는 것은 "빈 칸이 있다" 이고 "어느 칸인가" 는 아니다.** 두 정렬이
서로 다른 번호를 가리키므로, 모든 정렬에서 같은 **번호**를 요구하면 둘째
줄도 거절된다. 그래서 :class:`PointedZoneVerdict` 는 **존재**를 답으로
내고, 놓을 칸은 :data:`MODELLED_ALIGNMENT` 아래에서 고른다 — 그 선택이
전개를 바꾸지 않는다는 것은 시험이 **두 정렬을 모두 돌려** 센다
(``test_c03``).

이 파일이 하지 않는 것
----------------------
상대 자리를 가리키는 화살표 (상 계열), 같은 줄의 EMZ 끼리 가리키는 것
(좌·우), 엑스트라 덱 몬스터를 가리키는 칸에 놓는 규칙 (§16 의 나머지 절반),
``EFFECT_BECOME_LINKED_ZONE`` 처럼 **마커 없이** 가리키게 만드는 효과.
전부 등재되지 않았고, 등재되지 않은 것은 범위 밖이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.constants import LINK_MARKER_KO as _LINK_MARKER_KO
from engine.effect.ruling import ConditionResult
from engine.vocabulary import Zone

__all__ = [
    "EMZ_ALIGNMENTS",
    "MODELLED_ALIGNMENT",
    "MMZ_SLOTS",
    "POINTED_ZONE_SOURCE_GAP",
    "PointedZoneVerdict",
    "pointed_zones",
    "pointed_zone_verdict",
]


#: 메인 몬스터 존의 칸 번호. ``ZONES_MMZ = 0x1f`` 가 적는 다섯 칸이다.
MMZ_SLOTS: tuple[int, ...] = (0, 1, 2, 3, 4)

#: 🔴 **엑스트라 몬스터 존이 어느 메인 몬스터 존 위에 있는가** — 출처가
#: 없으므로 **고르지 않고 둘 다 들고 간다.** 값은 "그 EMZ 칸 바로 아래의
#: 메인 몬스터 존 번호" 다. 룰북 §17 이 *"you can choose either one"* 이라고
#: 적으므로 **선택이 둘이라는 사실 자체는 룰북에서 읽었다.**
EMZ_ALIGNMENTS: dict[str, int] = {
    "EMZ 왼쪽": 1,
    "EMZ 오른쪽": 3,
}

#: 🔴 **놓을 칸을 하나 골라야 할 때만** 쓰는 정렬이다. 판정에는 쓰지 않는다
#: (판정은 :data:`EMZ_ALIGNMENTS` 전부를 본다). 이 값이 전개를 바꾸지
#: 않는다는 것은 시험이 두 정렬을 모두 돌려 센다.
MODELLED_ALIGNMENT: str = "EMZ 왼쪽"

POINTED_ZONE_SOURCE_GAP = (
    "링크 마커가 가리키는 칸의 대응표가 이 저장소에 없습니다 — 룰북은 "
    "「가리키는 존」 의 존재와 EMZ 열 선택권만 적고 (sd-rulebook §16·§17) "
    "어느 화살표가 어느 번호를 가리키는지는 적지 않으며, "
    "aux.GetMMZonesPointedTo 는 호출 자리만 vendoring 되어 있고 정의가 "
    "없습니다"
)

#: 아래 방향 화살표가 **내 메인 몬스터 존 줄**에서 움직이는 칸 수.
#: EMZ 는 그 줄 **위**에 있으므로 아래 계열만 내 칸을 가리킨다.
_BOTTOM_OFFSETS: dict[str, int] = {"좌하": -1, "하": 0, "우하": +1}

#: 같은 줄의 옆 칸. 메인 몬스터 존에 선 링크 몬스터만 쓴다.
_SIDE_OFFSETS: dict[str, int] = {"좌": -1, "우": +1}


@dataclass(frozen=True, slots=True)
class PointedZoneVerdict:
    """
    "내 메인 몬스터 존 가운데 **링크 몬스터가 가리키는 빈 칸**이 있는가."

    🔴 **존재를 답하고 번호를 답하지 않는다.** 번호는 정렬에 따라 달라지고
    그 정렬의 출처가 없다 — 모듈 머리말을 보라. 번호가 필요한 자리는
    :attr:`slots` 를 쓰고, 그 값은 :data:`MODELLED_ALIGNMENT` 아래의
    답이라는 것을 함께 읽어야 한다.
    """

    answer: ConditionResult
    """``TRUE`` 모든 정렬에서 빈 칸이 있다 · ``FALSE`` 어느 정렬에서도 없다
    · ``UNKNOWN`` 정렬에 따라 갈린다."""

    slots: tuple[int, ...]
    """:data:`MODELLED_ALIGNMENT` 아래에서 가리켜지는 **빈** 칸 번호들."""

    per_alignment: tuple[tuple[str, tuple[int, ...]], ...]
    """정렬 이름 → 그 정렬에서 가리켜지는 빈 칸 번호들. 판정의 근거다."""

    reason: str

    def describe_ko(self) -> str:
        rows = " · ".join(
            f"{name}: {list(slots) or '없다'}" for name, slots in self.per_alignment
        )
        return f"{self.reason} ({rows})"


def pointed_zones(view, player: int, alignment: str) -> dict[int, tuple[str, ...]]:
    """
    정렬 하나를 가정했을 때 **내 메인 몬스터 존 중 가리켜지는 칸들**.

    돌려주는 것은 ``칸 번호 → 그 칸을 가리키는 까닭들`` 이다. 빈 칸인지는
    **보지 않는다** — 그것은 부르는 쪽이 센다 (가리켜지는 칸과 놓을 수 있는
    칸은 다른 사실이다).

    🔴 **내 링크 몬스터만 센다.** 상대의 링크 몬스터가 내 칸을 가리키는
    경우 (상 계열) 는 등재되지 않았다 — 모듈 머리말의 "하지 않는 것".
    """
    column = EMZ_ALIGNMENTS[alignment]
    found: dict[int, list[str]] = {}

    def add(slot: int, why: str) -> None:
        if slot in MMZ_SLOTS:
            found.setdefault(slot, []).append(why)

    for zone, offsets, base in (
        (Zone.EMZONE, _BOTTOM_OFFSETS, None),
        (Zone.MZONE, _SIDE_OFFSETS, "self"),
    ):
        box = view.players[player].zone(zone)
        for sequence, card in enumerate(box.cards):
            if card is None or card.definition is None:
                continue
            if not card.definition.is_link:
                continue
            origin = column if base is None else sequence
            for marker, step in offsets.items():
                if card.definition.link_marker_mask & _MARKER_BITS[marker]:
                    add(origin + step, f"{card.name or card.card_id} {marker}")
    return {slot: tuple(why) for slot, why in sorted(found.items())}


def pointed_zone_verdict(view, player: int) -> PointedZoneVerdict:
    """
    **모든 정렬을 보고** 답한다 — 하나를 고르지 않는다.

    ``TRUE`` 는 "어느 정렬이어도 놓을 빈 칸이 있다" 이고, 그때만 허가가
    난다. 정렬에 따라 갈리면 ``UNKNOWN`` 이고, 그것은 **허가가 아니다**
    (ADR-006).
    """
    box = view.players[player].zone(Zone.MZONE)
    free = {
        sequence
        for sequence, card in enumerate(box.cards)
        if card is None and sequence in MMZ_SLOTS
    }
    per: list[tuple[str, tuple[int, ...]]] = []
    for name in EMZ_ALIGNMENTS:
        pointed = pointed_zones(view, player, name)
        per.append((name, tuple(sorted(set(pointed) & free))))

    usable = [slots for _name, slots in per]
    modelled = next(
        (slots for name, slots in per if name == MODELLED_ALIGNMENT), ()
    )
    if all(usable) and usable:
        answer = ConditionResult.TRUE
        reason = (
            "링크 몬스터가 가리키는 빈 메인 몬스터 존이 **어느 정렬에서도** "
            "있습니다"
        )
    elif not any(usable):
        answer = ConditionResult.FALSE
        reason = (
            "링크 몬스터가 가리키는 빈 메인 몬스터 존이 **어느 정렬에서도** "
            "없습니다"
        )
    else:
        answer = ConditionResult.UNKNOWN
        reason = (
            "놓을 수 있는지가 **엑스트라 몬스터 존의 열에 따라 갈립니다** — "
            + POINTED_ZONE_SOURCE_GAP
        )
    return PointedZoneVerdict(
        answer=answer,
        slots=tuple(modelled),
        per_alignment=tuple(per),
        reason=reason,
    )


#: 🔴 **비트값을 여기서 다시 적지 않는다.** ``core.constants`` 가 이미
#: ``data/constants/constant.lua`` 의 값을 들고 있고, 같은 수를 두 곳에
#: 적으면 한쪽만 고쳐지는 날이 온다 (ADR-002 — 어긋나는 출처를 조용히
#: 덮어쓰지 않는다). 방향 **이름**으로만 조회하므로, 이름이 어긋나면 위
#: 표의 조회가 ``KeyError`` 로 터진다 — 조용히 틀리지 않는다.
_MARKER_BITS: dict[str, int] = {
    name: bit for bit, name in _LINK_MARKER_KO.items()
}
