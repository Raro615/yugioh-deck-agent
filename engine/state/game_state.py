"""
듀얼 상태 전체.

:class:`GameState` 는 **규칙을 수행하지 않는다.** 조립만 한다. 다음은 전부
이 클래스 밖(이후 Phase)의 일이다.

- 소환 가능 여부 · 효과 발동 가능 여부 · 공격 가능 여부 (Phase 4)
- 체인 생성 · 효과 해결 (Phase 5, 6)
- 이벤트 발생 (Phase 2)

여기서 제공하는 것은 상태 표현, :meth:`GameState.clone`, 그리고
:meth:`GameState.state_hash` 뿐이다.

무작위
------
셔플은 **주입된 seed 로만** 일어난다. ``seed`` 없이 셔플을 요청하면 거부한다.
전역 :mod:`random` 은 쓰지 않는다 — 다른 코드가 전역 상태를 건드리면 재현이
깨지기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator

from engine.ids import InstanceId, InstanceIdAllocator
from engine.state.card_instance import CardInstance
from engine.state.player import DEFAULT_LIFE_POINTS, PlayerState
from engine.state.turn import TurnState
from engine.state.use_registry import UseRegistry
from engine.state.zones import ZoneContainer, move_card
from engine.vocabulary import PLAYER_ZONES, Position, Zone

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
        "uses",
        "chain",
        "pending",
        "journal",
        "result",
        "_repository",
        "_allocator",
        "_seed",
        "_rng",
    )

    def __init__(
        self,
        players: tuple[PlayerState, PlayerState],
        turn: TurnState | None = None,
        repository: "CardRepository | None" = None,
        allocator: InstanceIdAllocator | None = None,
        result: DuelResult | None = None,
        uses: UseRegistry | None = None,
        seed: int | None = None,
        rng: random.Random | None = None,
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

        # 사용 횟수는 듀얼 전체에 하나다. 키가 ``(player, ...)`` 로 시작하므로
        # 플레이어마다 따로 둘 이유가 없고, 따로 두면 "상대 카드명 제약" 같은
        # 것을 표현할 때 두 곳을 봐야 한다.
        self.uses: UseRegistry = uses if uses is not None else UseRegistry()

        # 무작위는 주입된 seed 에서만 나온다. seed 가 없으면 rng 도 없고,
        # 셔플을 요청하면 거부한다 (:meth:`create`).
        self._seed = seed
        self._rng = rng

        # --- 이후 Phase 용 자리표시 --------------------------------------
        # Phase 5 에서 ChainState 가 들어온다. 지금은 구조만 잡아두고
        # 아무것도 넣지 않는다.
        #
        # ``journal`` 과 ``chain`` 은 **채우지 않는다.**
        # :class:`~engine.effect.journal.EventJournal` (Phase 2-D-3) ·
        # :class:`~engine.priority.PriorityState` (2-F-1) ·
        # :class:`~engine.chain.Chain` (2-F-2) 은 전부 판이 소유하지 않고
        # 실행기·해결기가 받아 둔다 — 여기에 넣으면 :meth:`state_hash` 가
        # "판이 어떤 모양인가" 가 아니라 "어떤 경로로 왔는가" 를 뜻하게 되고,
        # "같은 판은 만들어진 경로와 무관하게 같은 해시" 가 깨진다.
        # 판의 해시와 흐름의 위치는 다른 질문이므로 따로 둔다.
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
        seed: int | None = None,
        shuffle: bool = False,
    ) -> "GameState":
        """
        두 플레이어의 초기 상태를 만든다.

        ``decks`` / ``extra_decks`` 는 플레이어마다 카드 ID 목록이다. 기본값은
        받은 순서를 그대로 쓴다 — **셔플하지 않는다.**

        ``shuffle=True`` 면 ``seed`` 로 만든 :class:`random.Random` 으로만
        섞는다. ``seed`` 없이 셔플을 요청하면 :class:`ValueError` 다. 전역
        :mod:`random` 을 쓰지 않으므로 같은 seed 는 언제나 같은 배치를 만든다.
        엑스트라 덱은 순서가 의미를 갖지 않지만, 인스턴스 ID 할당 순서를
        흔들지 않기 위해 섞지 않는다.

        시작 시 드로우는 하지 않는다. "5장 드로우" 는 규칙이고, 테스트는
        :meth:`move` 로 직접 옮긴다.
        """
        if shuffle and seed is None:
            raise ValueError(
                "shuffle=True 에는 seed 가 필요합니다. seed 없는 무작위는 "
                "재현할 수 없으므로 거부합니다."
            )
        deck_lists = [list(d) for d in decks]
        extra_lists = [list(e) for e in (extra_decks or ((), ()))]
        while len(deck_lists) < PLAYER_COUNT:
            deck_lists.append([])
        while len(extra_lists) < PLAYER_COUNT:
            extra_lists.append([])

        rng = random.Random(seed) if seed is not None else None
        if shuffle:
            assert rng is not None  # 위에서 이미 거부했다
            for deck in deck_lists:
                rng.shuffle(deck)

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
            seed=seed,
            rng=rng,
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

    @property
    def seed(self) -> int | None:
        """이 상태를 만든 seed. 없으면 무작위를 쓰지 않았다는 뜻이다."""
        return self._seed

    @property
    def rng(self) -> random.Random:
        """
        이 듀얼 전용 난수원.

        seed 없이 만든 상태에서 무작위를 꺼내려 하면 거부한다. 조용히 전역
        난수로 넘어가면 재현 불가능한 상태가 만들어지기 때문이다.
        """
        if self._rng is None:
            raise RuntimeError(
                "이 GameState 는 seed 없이 만들어져 난수원이 없습니다. "
                "GameState.create(seed=...) 로 만드세요."
            )
        return self._rng

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
        ``CardInstance`` / counters / materials / ``UseRegistry`` / 난수원이다.

        ``instance_id`` 값은 **바꾸지 않는다.** 사본은 같은 세계의 사본이므로
        같은 카드가 같은 번호여야 하고, 그래야 사본으로 수를 읽어본 뒤 원본에
        같은 ``InstanceId`` 로 지시할 수 있다. 할당기도 함께 복제해서 두 갈래가
        같은 다음 번호에서 이어간다 — 갈라진 세계선끼리 번호가 겹치는 것은
        충돌이 아니다.

        난수원도 상태째 복제한다. 사본에서 셔플해도 원본의 다음 난수는
        변하지 않는다.
        """
        players = tuple(player.clone() for player in self.players)
        rng = None
        if self._rng is not None:
            rng = random.Random()
            rng.setstate(self._rng.getstate())
        copy = GameState(
            players=players,  # type: ignore[arg-type]
            turn=self.turn.clone(),
            repository=self._repository,
            allocator=self._allocator.clone(),
            result=self.result,  # frozen
            uses=self.uses.clone(),
            seed=self._seed,
            rng=rng,
        )
        # ``chain`` · ``pending`` · ``journal`` 은 판이 소유하지 않으므로
        # 복제 대상이 아니다 (Phase 2-D-3 · 2-F-1 · 2-F-2).
        return copy

    # ------------------------------------------------------------------
    # 정규 해시
    # ------------------------------------------------------------------
    def instance_numbering(self) -> Callable[[InstanceId], int]:
        """
        ``InstanceId`` 를 **자리 번호**로 바꾸는 함수를 만든다.

        ``InstanceId`` 는 만들어진 순서를 담고 있다. 그 값을 그대로 해시에
        넣으면 "같은 판이지만 카드를 다른 순서로 놓아 만든 상태" 가 다른
        해시를 갖는다. 그래서 해시 직전에 **정해진 순회 순서대로 0 부터 다시
        번호를 매긴다**: 플레이어 → :data:`PLAYER_ZONES` 순 → 존 안의 순서
        (칸 방식 존이면 칸 번호, 빈 칸은 건너뛴다) → 그 카드의 소재.

        원본 ``instance_id`` 는 손대지 않는다. 이 번호는 해시 계산에만 쓴다.
        """
        numbering: dict[InstanceId, int] = {}

        def assign(instance_id: InstanceId) -> None:
            if instance_id not in numbering:
                numbering[instance_id] = len(numbering)

        for player in self.players:
            for zone in PLAYER_ZONES:
                container = player.zones.get(zone)
                if container is None:
                    continue
                for card in container:
                    assign(card.instance_id)
                    for material in card.materials:
                        assign(material)

        def key(instance_id: InstanceId) -> int:
            # 존에 없는 ID (아직 어디에도 놓이지 않은 인스턴스 등) 도 순회
            # 순서대로 번호를 받는다. 순회 순서가 결정론적이므로 이 지연
            # 할당도 결정론적이다.
            assign(instance_id)
            return numbering[instance_id]

        return key

    def canonical_state(self) -> tuple:
        """
        해시 · 비교용 정규 표현. 파이썬 기본 ``hash()`` 나 객체 주소를
        쓰지 않는다 — 전부 값 타입(정수 · 문자열 · 불리언)으로만 이루어진다.

        ``instance_id`` 는 :meth:`instance_numbering` 으로 자리 번호로 바꿔서
        넣는다. 덕분에 "같은 판" 은 만들어진 경로와 무관하게 같은 해시를
        갖는다.

        ``chain`` / ``pending`` / ``journal`` 은 항상 비어 있으므로 포함하지
        않고, **앞으로도 넣지 않는다** — 역사도 체인도 우선권도 판의 모양이
        아니고, 넣으면 같은 판이 경로에 따라 다른 해시를 갖게 된다
        (Phase 2-D-3 · 2-F-1 · 2-F-2).
        ``allocator`` 와 난수원도 논리적 판 상태가 아니므로 제외한다 — 같은
        판이면 어떤 seed 로 도달했든 같은 해시다.
        """
        key = self.instance_numbering()
        return (
            tuple(player.canonical_state(key) for player in self.players),
            self.turn.canonical_state(),
            self.uses.canonical_state(key),
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
