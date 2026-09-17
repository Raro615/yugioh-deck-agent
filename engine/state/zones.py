"""
존 컨테이너.

존은 "카드 리스트"가 아니라 **순서를 보장하는 보관소**다. 덱 순서가 흐트러지면
드로우가 결정론적이지 않게 되고, 묘지 순서가 흐트러지면 "가장 나중에 묻힌
카드" 같은 조건이 틀어진다. 그래서 모든 연산이 순서를 명시적으로 다룬다.

Phase 1 이 하지 않는 것:

- "이 존에 더 넣을 수 있는가" (메인 몬스터 존 5칸 등의 **칸 제약**)
- "옮기면 어떤 이벤트가 발생하는가"

앞의 것은 Phase 4 (LegalActionGenerator), 뒤의 것은 Phase 2 (Event) 다.
따라서 현재 ``MZONE`` / ``SZONE`` 도 빈 칸을 남기지 않는 단순 순서 컨테이너이며,
"3번 칸이 비어 있다" 는 표현은 Phase 4 에서 칸 모델과 함께 들어온다.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.vocabulary import Position, Zone


class ZoneContainer:
    """한 플레이어의 존 하나. 순서를 유지한 채 카드 인스턴스를 담는다."""

    __slots__ = ("zone", "owner", "_cards")

    def __init__(
        self,
        zone: Zone,
        owner: int,
        cards: Iterable[CardInstance] | None = None,
    ):
        self.zone = zone
        self.owner = owner
        self._cards: list[CardInstance] = []
        for card in cards or ():
            self.append(card)

    # ------------------------------------------------------------------
    # 넣기
    # ------------------------------------------------------------------
    def append(self, card: CardInstance) -> None:
        """맨 뒤에 넣는다 (덱 맨 아래, 패 맨 오른쪽, 묘지 맨 위)."""
        self._cards.append(card)
        self._sync_from(len(self._cards) - 1)

    def insert(self, index: int, card: CardInstance) -> None:
        """지정한 위치에 넣는다. ``index=0`` 이면 덱 맨 위다."""
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
        """위치로 빼낸다. 기본값은 맨 뒤."""
        if not self._cards:
            raise IndexError(f"{self.zone.value} 존이 비어 있습니다.")
        card = self._cards.pop(index)
        self._sync_from(0)
        return card

    def clear(self) -> list[CardInstance]:
        cards = self._cards
        self._cards = []
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

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "ZoneContainer":
        """카드 인스턴스까지 독립 복제한다 (카드 정의는 공유)."""
        copy = ZoneContainer(self.zone, self.owner)
        copy._cards = [card.clone() for card in self._cards]
        return copy

    def canonical_state(self) -> tuple:
        return (
            self.zone.value,
            self.owner,
            tuple(card.canonical_state() for card in self._cards),
        )

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
