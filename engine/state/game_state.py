"""
듀얼 상태 전체.

:class:`GameState` 는 **규칙을 수행하지 않는다.** 조립만 한다. 다음은 전부
이 클래스 밖(이후 Phase)의 일이다.

- 소환 가능 여부 · 효과 발동 가능 여부 · 공격 가능 여부 (Phase 4)
- 체인 생성 · 효과 해결 (Phase 5, 6)
- 이벤트 발생 (Phase 2)

여기서 제공하는 것은 상태 표현, :meth:`GameState.clone`, 그리고
:meth:`GameState.state_hash` 뿐이다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from engine.ids import InstanceId, InstanceIdAllocator
from engine.state.card_instance import CardInstance
from engine.state.player import DEFAULT_LIFE_POINTS, PlayerState
from engine.state.turn import TurnState
from engine.state.zones import ZoneContainer, move_card
from engine.vocabulary import Position, Zone

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from core.card_repository import CardRepository

PLAYER_COUNT = 2


@dataclass(frozen=True, slots=True)
class DuelResult:
    """듀얼이 끝난 이유. 승패 **판정**은 Phase 1 이 하지 않는다."""

    winner: int | None = None
    reason: str = ""

    def as_tuple(self) -> tuple[int | None, str]:
        return (self.winner, self.reason)


class GameState:
    """듀얼 한 판의 상태 컨테이너."""

    __slots__ = (
        "players",
        "turn",
        "chain",
        "pending",
        "journal",
        "result",
        "_repository",
        "_allocator",
    )

    def __init__(
        self,
        players: tuple[PlayerState, PlayerState],
        turn: TurnState | None = None,
        repository: "CardRepository | None" = None,
        allocator: InstanceIdAllocator | None = None,
        result: DuelResult | None = None,
    ):
        if len(players) != PLAYER_COUNT:
            raise ValueError(f"플레이어는 {PLAYER_COUNT} 명이어야 합니다.")
        for index, player in enumerate(players):
            if player.player_id != index:
                raise ValueError(
                    f"players[{index}] 의 player_id 가 {player.player_id} 입니다. "
                    "인덱스와 같아야 합니다."
                )
        self.players: tuple[PlayerState, PlayerState] = players
        self.turn: TurnState = turn if turn is not None else TurnState()
        self.result: DuelResult | None = result
        self._repository = repository
        self._allocator = allocator if allocator is not None else InstanceIdAllocator()

        # --- 이후 Phase 용 자리표시 --------------------------------------
        # Phase 2 에서 GameEvent / EventJournal 이, Phase 5 에서 ChainState 가
        # 들어온다. 지금은 구조만 잡아두고 아무것도 넣지 않는다.
        self.chain: Any = None
        self.pending: list[Any] = []
        self.journal: list[Any] = []

    # ------------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        repository: "CardRepository | None" = None,
        *,
        decks: Iterable[Iterable[int]] = ((), ()),
        extra_decks: Iterable[Iterable[int]] | None = None,
        life_points: int = DEFAULT_LIFE_POINTS,
        turn_player: int = 0,
    ) -> "GameState":
        """
        두 플레이어의 초기 상태를 만든다.

        ``decks`` / ``extra_decks`` 는 플레이어마다 카드 ID 목록이다. 덱 순서는
        받은 그대로 유지한다 — **셔플하지 않는다.** 무작위는 결정론을 깨므로
        필요해지면 seed 와 함께 밖에서 넣는다.

        시작 시 드로우도 하지 않는다. "5장 드로우" 는 규칙이고, 테스트는
        :meth:`move` 로 직접 옮긴다.
        """
        deck_lists = [list(d) for d in decks]
        extra_lists = [list(e) for e in (extra_decks or ((), ()))]
        while len(deck_lists) < PLAYER_COUNT:
            deck_lists.append([])
        while len(extra_lists) < PLAYER_COUNT:
            extra_lists.append([])

        allocator = InstanceIdAllocator()
        players = tuple(
            PlayerState(player_id=i, life_points=life_points)
            for i in range(PLAYER_COUNT)
        )
        state = cls(
            players=players,  # type: ignore[arg-type]
            turn=TurnState(turn_player=turn_player),
            repository=repository,
            allocator=allocator,
        )
        # 할당 순서를 고정한다: p0 덱 -> p0 엑스트라 -> p1 덱 -> p1 엑스트라.
        for player_id in range(PLAYER_COUNT):
            for card_id in deck_lists[player_id]:
                state.create_instance(card_id, owner=player_id, zone=Zone.DECK)
            for card_id in extra_lists[player_id]:
                state.create_instance(card_id, owner=player_id, zone=Zone.EXTRA)
        return state

    def create_instance(
        self,
        card_id: int,
        *,
        owner: int,
        zone: Zone,
        position: Position = Position.FACEDOWN,
        index: int | None = None,
    ) -> CardInstance:
        """
        카드 인스턴스를 만들어 존에 넣는다. 카드 **정의는 복사하지 않는다.**
        """
        instance = CardInstance(
            instance_id=self._allocator.allocate(),
            card_id=card_id,
            owner=owner,
            controller=owner,
            zone=zone,
            position=position,
        )
        if self._repository is not None:
            instance.bind(self._repository)
        container = self.players[owner].zone(zone)
        if index is None:
            container.append(instance)
        else:
            container.insert(index, instance)
        return instance

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def repository(self) -> "CardRepository | None":
        return self._repository

    @property
    def allocator(self) -> InstanceIdAllocator:
        return self._allocator

    def player(self, player_id: int) -> PlayerState:
        return self.players[player_id]

    @property
    def turn_player(self) -> PlayerState:
        return self.players[self.turn.turn_player]

    def zone(self, player_id: int, zone: Zone) -> ZoneContainer:
        return self.players[player_id].zone(zone)

    def find_instance(self, instance_id: InstanceId) -> CardInstance | None:
        for player in self.players:
            found = player.find_instance(instance_id)
            if found is not None:
                return found
        return None

    def locate(self, instance_id: InstanceId) -> ZoneContainer | None:
        for player in self.players:
            container = player.locate(instance_id)
            if container is not None:
                return container
        return None

    def all_instances(self) -> list[CardInstance]:
        cards: list[CardInstance] = []
        for player in self.players:
            cards.extend(player.all_instances())
        return cards

    def __iter__(self) -> Iterator[CardInstance]:
        return iter(self.all_instances())

    # ------------------------------------------------------------------
    # 상태 변경 (규칙 아님)
    # ------------------------------------------------------------------
    def move(
        self,
        instance: CardInstance | InstanceId,
        zone: Zone,
        *,
        to_player: int | None = None,
        index: int | None = None,
        position: Position | None = None,
    ) -> CardInstance:
        """
        카드를 존 사이로 옮긴다. **옮겨도 되는지는 판정하지 않는다.**

        옮기기 직전 상태는 ``instance.previous`` 에 남는다.
        """
        card = (
            instance
            if isinstance(instance, CardInstance)
            else self.find_instance(instance)
        )
        if card is None:
            raise KeyError(f"{instance} 를 찾을 수 없습니다.")
        source = self.locate(card.instance_id)
        owner = to_player if to_player is not None else card.controller
        destination = self.players[owner].zone(zone)
        return move_card(
            card, source, destination, index=index, position=position
        )

    def draw(self, player_id: int, count: int = 1) -> list[CardInstance]:
        """
        덱 맨 위에서 패로 옮긴다. **드로우 규칙이 아니라 존 이동일 뿐이다** —
        덱이 모자라면 있는 만큼만 옮기고 패배 판정은 하지 않는다 (Phase 2).
        """
        drawn: list[CardInstance] = []
        deck = self.players[player_id].deck
        for _ in range(count):
            if not deck:
                break
            drawn.append(self.move(deck[0], Zone.HAND, to_player=player_id))
        return drawn

    def set_result(self, winner: int | None, reason: str) -> DuelResult:
        self.result = DuelResult(winner=winner, reason=reason)
        return self.result

    # ------------------------------------------------------------------
    # 복제
    # ------------------------------------------------------------------
    def clone(self) -> "GameState":
        """
        상태 전체를 독립 복제한다.

        카드 **정의**는 복제하지 않는다. ``CardRepository`` 의 ``Card`` 는
        읽기 전용으로만 쓰이므로 원본과 사본이 같은 객체를 참조해도 안전하다.
        복제해야 하는 것은 ``PlayerState`` / ``ZoneContainer`` /
        ``CardInstance`` / counters / materials / ``UseRegistry`` / 턴 플래그다.
        """
        players = tuple(player.clone() for player in self.players)
        copy = GameState(
            players=players,  # type: ignore[arg-type]
            turn=self.turn.clone(),
            repository=self._repository,
            allocator=self._allocator.clone(),
            result=self.result,  # frozen
        )
        # Phase 2 / 5 에서 chain · pending · journal 이 실제 내용을 갖게 되면
        # 여기서도 함께 복제해야 한다.
        return copy

    # ------------------------------------------------------------------
    # 정규 해시
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        """
        해시 · 비교용 정규 표현. 파이썬 기본 ``hash()`` 나 객체 주소를
        쓰지 않는다 — 전부 값 타입(정수 · 문자열 · 불리언)으로만 이루어진다.

        ``chain`` / ``pending`` / ``journal`` 은 Phase 1 에서 항상 비어 있으므로
        포함하지 않는다. 내용이 생기는 Phase 2 · 5 에서 함께 넣는다.
        ``allocator`` 도 논리적 상태가 아니므로 제외한다.
        """
        return (
            tuple(player.canonical_state() for player in self.players),
            self.turn.canonical_state(),
            self.result.as_tuple() if self.result else None,
        )

    def state_hash(self) -> str:
        """
        정규 표현을 결정론적으로 직렬화한 뒤 SHA-256 을 취한다.

        같은 논리적 상태는 언제나 같은 값이고, 프로세스를 다시 띄워도 같다
        (``PYTHONHASHSEED`` 에 영향받지 않는다).
        """
        payload = json.dumps(
            self.canonical_state(),
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, GameState)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        counts = " ".join(
            f"p{p.player_id}(LP{p.life_points} "
            f"D{len(p.deck)}/H{len(p.hand)}/M{len(p.monster_zone)}/G{len(p.grave)})"
            for p in self.players
        )
        return f"<GameState {self.turn} {counts}>"


def _json_default(obj: object) -> object:  # pragma: no cover - 방어용
    raise TypeError(
        f"정규 표현에 직렬화할 수 없는 값이 들어 있습니다: {type(obj).__name__}"
    )
