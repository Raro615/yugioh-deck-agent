"""
존 컨테이너.

존은 "카드 리스트"가 아니라 **순서를 보장하는 보관소**다. 덱 순서가 흐트러지면
드로우가 결정론적이지 않게 되고, 묘지 순서가 흐트러지면 "가장 나중에 묻힌
카드" 같은 조건이 틀어진다. 그래서 모든 연산이 순서를 명시적으로 다룬다.

존은 두 종류다 (:class:`~engine.vocabulary.ZoneKind`).

``ORDERED``
    덱 · 패 · 묘지 · 제외. 순서가 의미를 갖고 칸 번호가 없다.

``SLOTTED``
    몬스터 존 · 마법함정 존 · 필드 존 · 펜듈럼 존 · **엑스트라 몬스터 존**.
    칸이 고정되어 있어 **가운데가 비어도 양옆이 밀려나지 않는다.**

Phase 1 이 하지 않는 것:

- "이 존에 더 놓아도 되는가" 같은 **규칙 판정** (Phase 4)
- "옮기면 어떤 이벤트가 발생하는가" (Phase 2)

칸 수(:func:`~engine.vocabulary.zone_capacity`)는 **표현**을 위해 쓴다.
넘치면 :class:`ZoneFull` 로 거부하는데, 이는 규칙 판정이 아니라
**표현할 수 없는 상태를 만들지 않기 위한 자료구조 제약**이다.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.vocabulary import (
    Position,
    Zone,
    ZoneKind,
    ZoneVisibility,
    zone_capacity,
    zone_kind,
    zone_visibility,
)


class ZoneFull(RuntimeError):
    """
    칸이 없는 존에 더 넣으려 했다.

    **규칙 위반이 아니라 표현 불가**를 알리는 오류다. "소환해도 되는가" 는
    Phase 4 가 판정하고, 여기서는 존재할 수 없는 상태가 조용히 만들어지는
    것만 막는다.
    """


class ZoneContainer:
    """한 플레이어의 존 하나. 순서를 유지한 채 카드 인스턴스를 담는다."""

    __slots__ = ("zone", "owner", "_cards", "_slots")

    def __init__(
        self,
        zone: Zone,
        owner: int,
        cards: Iterable[CardInstance] | None = None,
    ):
        self.zone = zone
        self.owner = owner
        self._cards: list[CardInstance] = []
        # 칸 방식 존은 빈 칸을 그대로 들고 있어야 한다.
        self._slots: list[CardInstance | None] | None = (
            [None] * (zone_capacity(zone) or 0)
            if zone_kind(zone) is ZoneKind.SLOTTED
            else None
        )
        for card in cards or ():
            self.append(card)

    # ------------------------------------------------------------------
    # 존의 성질
    # ------------------------------------------------------------------
    @property
    def kind(self) -> ZoneKind:
        return zone_kind(self.zone)

    @property
    def capacity(self) -> int | None:
        """칸 수. ``None`` 이면 제한 없음."""
        return zone_capacity(self.zone)

    @property
    def visibility(self) -> ZoneVisibility:
        """존 자체의 공개 범위. 개별 카드의 앞면/뒷면과는 별개다."""
        return zone_visibility(self.zone)

    @property
    def is_slotted(self) -> bool:
        return self._slots is not None

    @property
    def is_full(self) -> bool:
        return self.capacity is not None and len(self._cards) >= self.capacity

    def free_slots(self) -> list[int]:
        """빈 칸 번호. 순서 존이면 빈 목록."""
        if self._slots is None:
            return []
        return [i for i, card in enumerate(self._slots) if card is None]

    def slot(self, index: int) -> CardInstance | None:
        """칸 번호로 본다. 순서 존에서는 ``TypeError``."""
        if self._slots is None:
            raise TypeError(f"{self.zone.value} 는 칸 방식 존이 아닙니다.")
        return self._slots[index]

    def slots(self) -> list[CardInstance | None]:
        if self._slots is None:
            raise TypeError(f"{self.zone.value} 는 칸 방식 존이 아닙니다.")
        return list(self._slots)

    # ------------------------------------------------------------------
    # 넣기
    # ------------------------------------------------------------------
    def append(self, card: CardInstance) -> None:
        """
        맨 뒤에 넣는다 (덱 맨 아래, 패 맨 오른쪽, 묘지 맨 위).

        칸 방식 존이면 **가장 작은 빈 칸**에 놓는다.
        """
        if self._slots is not None:
            free = self.free_slots()
            if not free:
                raise ZoneFull(
                    f"{self.zone.value} 존에 빈 칸이 없습니다 (칸 {self.capacity}개)."
                )
            self.place(free[0], card)
            return
        self._cards.append(card)
        self._sync_from(len(self._cards) - 1)

    def place(self, index: int, card: CardInstance) -> None:
        """칸 방식 존의 지정한 칸에 놓는다."""
        if self._slots is None:
            raise TypeError(f"{self.zone.value} 는 칸 방식 존이 아닙니다.")
        if not 0 <= index < len(self._slots):
            raise IndexError(
                f"{self.zone.value} 의 칸은 0..{len(self._slots) - 1} 입니다: {index}"
            )
        if self._slots[index] is not None:
            raise ZoneFull(f"{self.zone.value} 의 {index}번 칸이 이미 찼습니다.")
        if card in self:
            # 같은 카드가 두 칸을 동시에 차지하는 상태는 표현할 수 없다.
            # 옮기려면 먼저 빼야 한다 (``move_card`` 가 그렇게 한다).
            raise ZoneFull(
                f"{card.instance_id} 는 이미 {self.zone.value} 존의 "
                f"{self.index(card)}번 칸에 있습니다. 옮기려면 먼저 빼세요."
            )
        self._slots[index] = card
        self._rebuild_from_slots()

    def insert(self, index: int, card: CardInstance) -> None:
        """
        지정한 위치에 넣는다. ``index=0`` 이면 덱 맨 위다.

        칸 방식 존에서는 :meth:`place` 와 같은 뜻이다 — 칸은 밀리지 않는다.
        """
        if self._slots is not None:
            self.place(index, card)
            return
        if self.is_full:
            raise ZoneFull(f"{self.zone.value} 존이 가득 찼습니다 ({self.capacity}장).")
        self._cards.insert(index, card)
        self._sync_from(min(index, len(self._cards) - 1))

    def extend(self, cards: Iterable[CardInstance]) -> None:
        for card in cards:
            self.append(card)

    # ------------------------------------------------------------------
    # 빼기
    # ------------------------------------------------------------------
    def remove(self, card: CardInstance | InstanceId) -> CardInstance:
        """카드를 빼서 돌려준다. 없으면 ``KeyError``."""
        index = self.index(card)
        return self.pop(index)

    def pop(self, index: int = -1) -> CardInstance:
        """
        위치로 빼낸다. 기본값은 맨 뒤.

        칸 방식 존에서는 그 카드가 있던 칸이 **빈 칸으로 남는다** — 뒤의 카드가
        당겨지지 않는다.
        """
        if not self._cards:
            raise IndexError(f"{self.zone.value} 존이 비어 있습니다.")
        card = self._cards[index]
        if self._slots is not None:
            self._slots[self._slots.index(card)] = None
            self._rebuild_from_slots()
            return card
        self._cards.pop(index)
        self._sync_from(0)
        return card

    def clear(self) -> list[CardInstance]:
        cards = self._cards
        self._cards = []
        if self._slots is not None:
            self._slots = [None] * len(self._slots)
        return cards

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def index(self, card: CardInstance | InstanceId) -> int:
        instance_id = card.instance_id if isinstance(card, CardInstance) else card
        for i, held in enumerate(self._cards):
            if held.instance_id == instance_id:
                return i
        raise KeyError(f"{instance_id} 가 {self.zone.value} 존에 없습니다.")

    def find(self, instance_id: InstanceId) -> CardInstance | None:
        for held in self._cards:
            if held.instance_id == instance_id:
                return held
        return None

    def cards(self) -> list[CardInstance]:
        """현재 내용의 얕은 복사본 (순회 중 변경해도 안전하게)."""
        return list(self._cards)

    def card_ids(self) -> list[int]:
        return [held.card_id for held in self._cards]

    def top(self) -> CardInstance | None:
        """덱 맨 위 (= 0번)."""
        return self._cards[0] if self._cards else None

    def __contains__(self, card: object) -> bool:
        if isinstance(card, CardInstance):
            card = card.instance_id
        if not isinstance(card, InstanceId):
            return False
        return any(held.instance_id == card for held in self._cards)

    def __iter__(self) -> Iterator[CardInstance]:
        return iter(self._cards)

    def __len__(self) -> int:
        return len(self._cards)

    def __getitem__(self, index: int) -> CardInstance:
        return self._cards[index]

    def __bool__(self) -> bool:
        return bool(self._cards)

    # ------------------------------------------------------------------
    # 내부 정합성
    # ------------------------------------------------------------------
    def _sync_from(self, start: int) -> None:
        """
        담긴 카드의 ``zone`` / ``sequence`` / ``controller`` 를 컨테이너와 맞춘다.
        존과 인스턴스가 서로 다른 말을 하는 상태를 만들지 않기 위한 것이다.
        """
        for i in range(max(0, start), len(self._cards)):
            card = self._cards[i]
            card.zone = self.zone
            card.sequence = i
            card.controller = self.owner

    def _rebuild_from_slots(self) -> None:
        """칸 배열을 기준으로 목록을 다시 만든다. ``sequence`` 는 **칸 번호**다."""
        assert self._slots is not None
        self._cards = [card for card in self._slots if card is not None]
        for index, card in enumerate(self._slots):
            if card is not None:
                card.zone = self.zone
                card.sequence = index
                card.controller = self.owner

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "ZoneContainer":
        """카드 인스턴스까지 독립 복제한다 (카드 정의는 공유). 빈 칸도 그대로."""
        copy = ZoneContainer(self.zone, self.owner)
        if self._slots is not None:
            cloned = {id(c): c.clone() for c in self._cards}
            copy._slots = [
                None if card is None else cloned[id(card)] for card in self._slots
            ]
            copy._rebuild_from_slots()
        else:
            copy._cards = [card.clone() for card in self._cards]
        return copy

    def canonical_state(self, instance_key=None) -> tuple:
        """
        해시용 정규 표현.

        칸 방식 존은 **빈 칸까지** 표현한다. 0번과 2번에 몬스터가 있는 상태와
        0번과 1번에 있는 상태는 서로 다른 상태다.
        """
        if self._slots is not None:
            contents = tuple(
                None if card is None else card.canonical_state(instance_key)
                for card in self._slots
            )
        else:
            contents = tuple(
                card.canonical_state(instance_key) for card in self._cards
            )
        return (self.zone.value, self.owner, contents)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ZoneContainer p{self.owner}/{self.zone.value} n={len(self._cards)}>"


def move_card(
    card: CardInstance,
    source: ZoneContainer | None,
    destination: ZoneContainer,
    *,
    index: int | None = None,
    position: Position | None = None,
) -> CardInstance:
    """
    카드를 존 사이로 옮긴다.

    옮기기 **직전** 상태를 :class:`~engine.state.card_instance.PreviousState`
    로 남긴다. ``previous_location`` 류 조건이 이 기록에 의존한다.

    규칙 판정은 없다. 옮길 수 있는지, 옮긴 결과 무엇이 발생하는지는
    이후 Phase 의 일이다.
    """
    card.snapshot_previous()
    if source is not None:
        source.remove(card)
    if index is None:
        destination.append(card)
    else:
        destination.insert(index, card)
    if position is not None:
        card.set_position(position, remember_previous=False)
    return card
