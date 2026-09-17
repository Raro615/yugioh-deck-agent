"""
GameStateView — AI 에게 넘기는 **읽기 전용 스냅숏**.

AI 는 ``GameState`` 를 직접 받지 않는다. 받으면 ``move()`` · ``change_life()``
· ``draw()`` 가 그대로 노출되고, 실수 한 줄로 ADR-007 의 경계가 사라진다.

스냅숏인 이유
-------------
살아 있는 읽기 전용 프록시 대신 **만드는 순간 값을 복사한다.**

- 안전이 구조로 보장된다. 프록시는 감싸는 것을 하나라도 빠뜨리면 새지만,
  스냅숏은 새어 나갈 원본 참조 자체가 없다.
- AI 가 보는 관측이 고정된다. MCTS 가 한 노드를 평가하는 동안 원본이 바뀌어도
  관측이 흔들리지 않는다.
- 전부 frozen dataclass 와 tuple 이라 ``view.hand`` 에 ``append`` 할 수 없다.

숨겨진 정보
-----------
**"보이지만 잠겨 있다" 가 아니라 "값이 아예 없다" 로 숨긴다.** 숨긴 값을
들고 있으면서 플래그로 가리면, 그 플래그를 보지 않는 코드 한 줄이 곧 유출이다.

===================  ==========================================================
존                    보는 사람에게 무엇이 보이는가
===================  ==========================================================
덱 (``HIDDEN``)      **장수만.** 카드 목록이 비어 있다 (자기 덱도 마찬가지)
패 · 엑스트라         자기 것이면 전부. 상대 것이면 **장수만**
공개 존               앞면 카드는 전부. 뒷면 카드는 **컨트롤러에게만** 정체가 보임
===================  ==========================================================

뒷면 카드는 정체(``card_id``)만 가리고 ``instance_id`` 는 남긴다. 상대의 세트
카드를 "저 자리의 그것" 으로 지목해서 공격하거나 파괴할 수 있어야 하기
때문이다. 반대로 상대의 **패**는 ``instance_id`` 도 주지 않는다 — 주면 "3턴에
드로우한 그 카드가 아직 손에 있다" 는 정보가 새고, 그것은 실제 대전에서
알 수 없는 사실이다.

Phase 2-A 가 내보내지 않는 것
------------------------------
``UseRegistry`` · ``EffectRegistry`` · raw Lua · provenance · 파서 상태.
AI 가 알 필요가 없고, 엔진 내부 구현을 관측에 묶으면 나중에 바꿀 수 없다.
"이 효과를 이번 턴에 썼는가" 는 정당한 공개 정보지만, 그것을 **질의로**
노출하는 것은 Condition 계층(Phase 2-B)이 모양을 정한 뒤에 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.ids import InstanceId
from engine.vocabulary import (
    PLAYER_ZONES,
    Phase,
    Position,
    Zone,
    ZoneKind,
    ZoneVisibility,
    zone_capacity,
    zone_kind,
    zone_visibility,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from engine.state.card_instance import CardInstance
    from engine.state.game_state import GameState
    from engine.state.zones import ZoneContainer


@dataclass(frozen=True, slots=True)
class CardView:
    """
    보는 사람에게 **보이는 만큼**의 카드 한 장.

    ``card_id`` 가 ``None`` 이면 정체를 모른다는 뜻이다. 숨긴 값을 들고
    있다가 가리는 것이 아니라, 처음부터 넣지 않는다.
    """

    instance_id: InstanceId | None
    """지목할 수 있으면 번호, 아니면 ``None`` (상대의 패 등)."""
    card_id: int | None
    """정체를 알면 카드 ID, 모르면 ``None``."""
    zone: Zone
    sequence: int
    """칸 방식 존에서는 **칸 번호**, 순서 존에서는 위치."""
    controller: int
    face_up: bool
    position: Position | None = None
    owner: int | None = None
    """정체를 모르면 소유자도 모른다 (패 · 덱)."""
    counters: tuple[tuple[str, int], ...] = ()
    name: str | None = None
    """표시용 이름. 정체를 모르면 ``None``."""

    @property
    def is_identified(self) -> bool:
        """정체를 아는가. ``False`` 면 ``card_id`` 를 기대하지 말 것."""
        return self.card_id is not None

    @property
    def is_targetable(self) -> bool:
        """이 카드를 Action 의 대상으로 지목할 수 있는가 (구조적으로)."""
        return self.instance_id is not None

    # --- 만들기 -------------------------------------------------------
    @classmethod
    def revealed(cls, card: "CardInstance") -> "CardView":
        """정체까지 보이는 카드."""
        return cls(
            instance_id=card.instance_id,
            card_id=card.card_id,
            zone=card.zone,
            sequence=card.sequence,
            controller=card.controller,
            face_up=card.is_faceup,
            position=card.position,
            owner=card.owner,
            counters=tuple(sorted(card.counters.items())),
            name=card.name,
        )

    @classmethod
    def concealed(cls, card: "CardInstance") -> "CardView":
        """
        자리와 표시 형식은 보이지만 **정체는 모르는** 카드.

        상대 필드의 뒷면 카드가 이 모양이다. 지목은 할 수 있어야 하므로
        ``instance_id`` 는 남긴다.
        """
        return cls(
            instance_id=card.instance_id,
            card_id=None,
            zone=card.zone,
            sequence=card.sequence,
            controller=card.controller,
            face_up=False,
            position=card.position,
            owner=None,
            counters=tuple(sorted(card.counters.items())),
            name=None,
        )

    def canonical_state(self) -> tuple:
        return (
            self.instance_id.value if self.instance_id is not None else None,
            self.card_id,
            self.zone.value,
            self.sequence,
            self.controller,
            self.face_up,
            self.position.value if self.position is not None else None,
            self.owner,
            self.counters,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "zone": self.zone.value,
            "sequence": self.sequence,
            "controller": self.controller,
            "face_up": self.face_up,
        }
        if self.instance_id is not None:
            data["instance_id"] = self.instance_id.value
        if self.card_id is not None:
            data["card_id"] = self.card_id
        if self.position is not None:
            data["position"] = self.position.value
        if self.owner is not None:
            data["owner"] = self.owner
        if self.counters:
            data["counters"] = [list(c) for c in self.counters]
        return data

    def __str__(self) -> str:
        who = self.name or ("???" if not self.is_identified else str(self.card_id))
        return f"{who}({self.zone.value}[{self.sequence}])"


@dataclass(frozen=True, slots=True)
class ZoneView:
    """
    존 하나의 스냅숏.

    ``size`` 는 **언제나 정확하다** — 장수는 숨겨진 존에서도 공개다.
    ``cards`` 는 보이는 만큼만 담는다. 숨겨진 존이면 비어 있고, 그때
    :attr:`concealed` 가 참이다 — "빈 덱" 과 "안 보이는 덱" 을 구분하기
    위해서다.
    """

    zone: Zone
    owner: int
    visibility: ZoneVisibility
    kind: ZoneKind
    capacity: int | None
    size: int
    """실제 장수. 숨겨져 있어도 정확하다."""
    cards: tuple[CardView | None, ...] = ()
    """
    칸 방식 존이면 길이가 칸 수이고 빈 칸이 ``None`` 이다.
    순서 존이면 길이가 ``size`` 다. 내용이 숨겨져 있으면 비어 있다.
    """
    concealed: bool = False
    """내용이 통째로 가려졌는가. 참이면 ``cards`` 가 비어 있다."""

    @property
    def is_empty(self) -> bool:
        return self.size == 0

    def occupied(self) -> tuple[CardView, ...]:
        """빈 칸을 걷어낸 카드들."""
        return tuple(card for card in self.cards if card is not None)

    def free_slots(self) -> tuple[int, ...]:
        """빈 칸 번호. 순서 존이면 빈 튜플."""
        if self.kind is not ZoneKind.SLOTTED:
            return ()
        return tuple(i for i, card in enumerate(self.cards) if card is None)

    def canonical_state(self) -> tuple:
        return (
            self.zone.value,
            self.owner,
            self.visibility.value,
            self.kind.value,
            self.capacity,
            self.size,
            self.concealed,
            tuple(None if c is None else c.canonical_state() for c in self.cards),
        )

    def to_dict(self) -> dict:
        return {
            "zone": self.zone.value,
            "owner": self.owner,
            "visibility": self.visibility.value,
            "kind": self.kind.value,
            "capacity": self.capacity,
            "size": self.size,
            "concealed": self.concealed,
            "cards": [None if c is None else c.to_dict() for c in self.cards],
        }

    def __len__(self) -> int:
        return self.size

    def __str__(self) -> str:
        return f"<{self.zone.value} p{self.owner} n={self.size}>"


@dataclass(frozen=True, slots=True)
class PlayerView:
    """플레이어 한 명의 스냅숏. 보는 사람에 따라 내용이 달라진다."""

    player_id: int
    life_points: int
    zones: tuple[ZoneView, ...]

    def zone(self, zone: Zone) -> ZoneView:
        for view in self.zones:
            if view.zone is zone:
                return view
        raise KeyError(f"플레이어 {self.player_id} 에게 {zone.value} 존이 없습니다.")

    # 자주 쓰는 존은 이름으로도 꺼낸다.
    @property
    def deck(self) -> ZoneView:
        return self.zone(Zone.DECK)

    @property
    def hand(self) -> ZoneView:
        return self.zone(Zone.HAND)

    @property
    def extra(self) -> ZoneView:
        return self.zone(Zone.EXTRA)

    @property
    def grave(self) -> ZoneView:
        return self.zone(Zone.GRAVE)

    @property
    def removed(self) -> ZoneView:
        return self.zone(Zone.REMOVED)

    @property
    def monster_zone(self) -> ZoneView:
        return self.zone(Zone.MZONE)

    @property
    def extra_monster_zone(self) -> ZoneView:
        """엑스트라 몬스터 존. 메인 몬스터 존과 **다른 존**이다 (칸 1개)."""
        return self.zone(Zone.EMZONE)

    @property
    def spell_zone(self) -> ZoneView:
        return self.zone(Zone.SZONE)

    @property
    def field_zone(self) -> ZoneView:
        return self.zone(Zone.FZONE)

    @property
    def pendulum_zone(self) -> ZoneView:
        return self.zone(Zone.PZONE)

    def canonical_state(self) -> tuple:
        return (
            self.player_id,
            self.life_points,
            tuple(z.canonical_state() for z in self.zones),
        )

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "life_points": self.life_points,
            "zones": [z.to_dict() for z in self.zones],
        }


@dataclass(frozen=True, slots=True)
class GameStateView:
    """
    한 플레이어가 보는 판. :meth:`from_state` 로 만든다.

    만들어진 뒤에는 원본 ``GameState`` 와 아무 객체도 공유하지 않는다.
    원본이 바뀌어도 이 스냅숏은 그대로다.
    """

    viewer: int
    """이 관측의 주인. ``me`` 가 가리키는 플레이어다."""
    turn_number: int
    turn_player: int
    phase: Phase
    step: int
    players: tuple[PlayerView, PlayerView]
    winner: int | None = None
    result_reason: str = ""

    # ------------------------------------------------------------------
    # 만들기
    # ------------------------------------------------------------------
    @classmethod
    def from_state(cls, state: "GameState", viewer: int) -> "GameStateView":
        """
        ``viewer`` 가 보는 만큼만 담은 스냅숏을 만든다.

        **``state`` 를 바꾸지 않는다.** 읽기만 한다.
        """
        if viewer not in (0, 1):
            raise ValueError(f"viewer 는 0 또는 1 입니다: {viewer}")
        return cls(
            viewer=viewer,
            turn_number=state.turn.turn_number,
            turn_player=state.turn.turn_player,
            phase=state.turn.phase,
            step=state.turn.step,
            players=(
                _player_view(state, 0, viewer),
                _player_view(state, 1, viewer),
            ),
            winner=state.result.winner if state.result is not None else None,
            result_reason=state.result.reason if state.result is not None else "",
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def me(self) -> PlayerView:
        return self.players[self.viewer]

    @property
    def opponent(self) -> PlayerView:
        return self.players[1 - self.viewer]

    @property
    def opponent_id(self) -> int:
        return 1 - self.viewer

    def player(self, player_id: int) -> PlayerView:
        return self.players[player_id]

    @property
    def is_my_turn(self) -> bool:
        return self.turn_player == self.viewer

    @property
    def is_over(self) -> bool:
        return self.winner is not None or bool(self.result_reason)

    def find(self, instance_id: InstanceId) -> CardView | None:
        """보이는 카드 중에서 찾는다. 안 보이면 ``None``."""
        for player in self.players:
            for zone in player.zones:
                for card in zone.cards:
                    if card is not None and card.instance_id == instance_id:
                        return card
        return None

    def visible_instances(self) -> tuple[InstanceId, ...]:
        """지목할 수 있는 카드 전부. Action 대상 후보의 상한이다."""
        found: list[InstanceId] = []
        for player in self.players:
            for zone in player.zones:
                for card in zone.cards:
                    if card is not None and card.instance_id is not None:
                        found.append(card.instance_id)
        return tuple(found)

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        return (
            self.viewer,
            self.turn_number,
            self.turn_player,
            self.phase.value,
            self.step,
            tuple(p.canonical_state() for p in self.players),
            self.winner,
            self.result_reason,
        )

    def to_dict(self) -> dict:
        return {
            "viewer": self.viewer,
            "turn_number": self.turn_number,
            "turn_player": self.turn_player,
            "phase": self.phase.value,
            "step": self.step,
            "players": [p.to_dict() for p in self.players],
            "winner": self.winner,
            "result_reason": self.result_reason,
        }

    def __str__(self) -> str:
        return (
            f"<GameStateView p{self.viewer} T{self.turn_number} "
            f"{self.phase.value} me:LP{self.me.life_points} "
            f"opp:LP{self.opponent.life_points}>"
        )


# ----------------------------------------------------------------------
# 내부 — 공개 범위 판정
# ----------------------------------------------------------------------
def _player_view(state: "GameState", player_id: int, viewer: int) -> PlayerView:
    player = state.player(player_id)
    return PlayerView(
        player_id=player_id,
        life_points=player.life_points,
        zones=tuple(
            _zone_view(player.zones[zone], viewer)
            for zone in PLAYER_ZONES
            if zone in player.zones
        ),
    )


def _zone_view(container: "ZoneContainer", viewer: int) -> ZoneView:
    zone = container.zone
    visibility = zone_visibility(zone)
    kind = zone_kind(zone)
    size = len(container)

    base = dict(
        zone=zone,
        owner=container.owner,
        visibility=visibility,
        kind=kind,
        capacity=zone_capacity(zone),
        size=size,
    )

    # 덱은 아무도 내용을 모른다. 자기 덱도 마찬가지다 — 그것이 규칙이다.
    if visibility is ZoneVisibility.HIDDEN:
        return ZoneView(**base, cards=(), concealed=True)

    # 패 · 엑스트라 덱은 소유자만 안다.
    if visibility is ZoneVisibility.OWNER_ONLY and container.owner != viewer:
        return ZoneView(**base, cards=(), concealed=True)

    if kind is ZoneKind.SLOTTED:
        cards: tuple[CardView | None, ...] = tuple(
            None if card is None else _card_view(card, viewer)
            for card in container.slots()
        )
    else:
        cards = tuple(_card_view(card, viewer) for card in container)
    return ZoneView(**base, cards=cards, concealed=False)


#: 카드의 **앞뒷면이 공개 여부를 좌우하는** 존.
#:
#: 묘지는 여기 없다. 묘지에 뒷면은 없고 내용은 언제나 공개이기 때문이다.
#: 그런데 ``move_card`` 는 표시 형식을 건드리지 않으므로, 덱에서 묘지로 간
#: 카드는 ``position`` 이 ``FACEDOWN`` 인 채로 남는다 — 앞뒷면만 보고
#: 판단하면 **상대 묘지가 통째로 가려진다.** 존을 먼저 봐야 하는 이유다.
#:
#: 제외 존은 여기 들어 있다. 뒷면 제외가 실제로 존재하고, 그 카드는
#: 제외한 플레이어만 안다.
_FACE_SENSITIVE_ZONES: frozenset[Zone] = frozenset(
    {Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.PZONE, Zone.REMOVED}
)


def _card_view(card: "CardInstance", viewer: int) -> CardView:
    """
    공개 존의 카드 한 장이 얼마나 보이는가.

    앞뒷면이 의미를 갖는 존에서만 뒷면을 가린다. 그 경우에도 **컨트롤러는
    안다** — 자기가 세트한 카드가 무엇인지는 당연히 알기 때문이다.
    """
    if card.zone not in _FACE_SENSITIVE_ZONES:
        return CardView.revealed(card)
    if card.is_faceup or card.controller == viewer:
        return CardView.revealed(card)
    return CardView.concealed(card)
