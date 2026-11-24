"""
플레이어 한 명의 듀얼 상태.

라이프와 존 열 개. **그뿐이다.**

"일반 소환을 몇 번 했는가", "이번 턴에 드로우했는가" 같은 것은 **턴 진행
규칙에 속하는 상태**라서 여기 두지 않는다. 그런 값을 Phase 1 의 Player 에
넣어두면, 규칙을 구현하기도 전에 규칙의 모양을 못박게 된다. Phase 4 의 타이밍
계층이 들어올 때 함께 정한다.

사용 횟수(:class:`~engine.state.use_registry.UseRegistry`)도 여기 없다.
키가 ``(player, ...)`` 로 시작하므로 듀얼 전체에 하나만 있으면 되고,
:class:`~engine.state.game_state.GameState` 가 들고 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.state.zones import ZoneContainer
from engine.vocabulary import PLAYER_ZONES, Zone

DEFAULT_LIFE_POINTS = 8000


@dataclass(slots=True)
class PlayerState:
    """플레이어 한 명이 소유한 듀얼 상태 전부."""

    player_id: int
    life_points: int = DEFAULT_LIFE_POINTS
    zones: dict[Zone, ZoneContainer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for zone in PLAYER_ZONES:
            if zone not in self.zones:
                self.zones[zone] = ZoneContainer(zone, self.player_id)
        #: 🔴 **소재 보관함** (Phase 6-BO). ``PLAYER_ZONES`` 에는 **넣지
        #: 않는다** — 엑시즈 소재는 존에 있는 것이 아니라 숙주가 들고 있고
        #: (``engine.vocabulary.Zone.OVERLAY`` 의 설명), 「존의 카드 수」 를
        #: 묻는 조건이 소재를 세기 시작하면 규칙이 달라진다.
        #:
        #: 그런데 **객체가 살 곳은 있어야 한다.** 인스턴스는 존 컨테이너에만
        #: 살고 (:meth:`find_instance`), ``CardInstance.materials`` 는
        #: ``InstanceId`` 만 들고 있다 — 컨테이너에서 빼기만 하면 그 카드의
        #: **card_id 도 표시 형식도 어디서도 읽을 수 없게 된다** (실측:
        #: 6-BO 의 첫 판에서 ``find_instance`` 가 ``None`` 을 돌려주었다).
        #:
        #: 그래서 보관함은 **있고**, 어느 숙주 아래 몇 번째인지는 그 숙주의
        #: ``materials`` 가 적는다. 두 기록은 다른 질문에 답한다.
        if Zone.OVERLAY not in self.zones:
            self.zones[Zone.OVERLAY] = ZoneContainer(
                Zone.OVERLAY, self.player_id
            )

    # ------------------------------------------------------------------
    # 존 접근
    # ------------------------------------------------------------------
    def zone(self, zone: Zone) -> ZoneContainer:
        try:
            return self.zones[zone]
        except KeyError:
            raise KeyError(
                f"플레이어 {self.player_id} 에게 {zone.value} 존이 없습니다."
            ) from None

    def __getitem__(self, zone: Zone) -> ZoneContainer:
        return self.zone(zone)

    @property
    def deck(self) -> ZoneContainer:
        return self.zones[Zone.DECK]

    @property
    def hand(self) -> ZoneContainer:
        return self.zones[Zone.HAND]

    @property
    def extra(self) -> ZoneContainer:
        return self.zones[Zone.EXTRA]

    @property
    def grave(self) -> ZoneContainer:
        return self.zones[Zone.GRAVE]

    @property
    def removed(self) -> ZoneContainer:
        return self.zones[Zone.REMOVED]

    @property
    def monster_zone(self) -> ZoneContainer:
        return self.zones[Zone.MZONE]

    @property
    def spell_zone(self) -> ZoneContainer:
        return self.zones[Zone.SZONE]

    def find_instance(self, instance_id: InstanceId) -> CardInstance | None:
        """이 플레이어의 어느 존에 있든 찾아준다."""
        for container in self.zones.values():
            found = container.find(instance_id)
            if found is not None:
                return found
        return None

    def locate(self, instance_id: InstanceId) -> ZoneContainer | None:
        for container in self.zones.values():
            if container.find(instance_id) is not None:
                return container
        return None

    @property
    def overlay(self) -> ZoneContainer:
        """엑시즈 소재들이 **사는 곳** (Phase 6-BO · :meth:`__post_init__`)."""
        return self.zones[Zone.OVERLAY]

    def all_instances(self) -> list[CardInstance]:
        """
        이 플레이어의 카드 전부 — **소재까지** (Phase 6-BO).

        🔴 소재도 판에 있는 카드다. 빼면 "듀얼에 있는 카드 전부" 라는 말이
        거짓이 되고, 소재가 된 카드를 세는 쪽이 그것을 못 본다.
        """
        cards: list[CardInstance] = []
        for zone in (*PLAYER_ZONES, Zone.OVERLAY):
            cards.extend(self.zones[zone])
        return cards

    # ------------------------------------------------------------------
    # 라이프 · 소환 횟수
    # ------------------------------------------------------------------
    def change_life(self, delta: int) -> int:
        """라이프를 더하거나 뺀다. 0 아래로는 내려가지 않는다 (승패 판정은 별개)."""
        self.life_points = max(0, self.life_points + delta)
        return self.life_points

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "PlayerState":
        return PlayerState(
            player_id=self.player_id,
            life_points=self.life_points,
            zones={zone: container.clone() for zone, container in self.zones.items()},
        )

    def canonical_state(self, instance_key=None) -> tuple:
        return (
            self.player_id,
            self.life_points,
            tuple(
                self.zones[zone].canonical_state(instance_key)
                #: 🔴 **소재 보관함이 해시에 들어간다** (Phase 6-BO).
                #: 숙주의 ``materials`` 는 **자리 번호**만 싣는다 — 어느
                #: 카드가 소재인지(``card_id``)는 그 보관함만 안다. 빼면
                #: 스켈레촌이 붙은 판과 기르수가 붙은 판이 같은 해시를
                #: 갖고, 탐색의 중복 제거가 둘을 합친다.
                for zone in (*PLAYER_ZONES, Zone.OVERLAY)
                if zone in self.zones
            ),
        )
