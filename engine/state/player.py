"""
플레이어 한 명의 듀얼 상태.

라이프, 존 아홉 개, 일반 소환 횟수, 턴 플래그, 그리고 발동 횟수 레지스트리.
규칙은 없다 — "일반 소환을 할 수 있는가" 는 Phase 4 의 판정이고, 여기서는
"몇 번 했는가" 만 센다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from analysis.effect_model import LimitScope
from engine.ids import EffectRef, InstanceId
from engine.state.card_instance import CardInstance
from engine.state.zones import ZoneContainer
from engine.vocabulary import PLAYER_ZONES, Zone

DEFAULT_LIFE_POINTS = 8000


@dataclass(slots=True)
class TurnFlags:
    """이번 턴에 이미 일어난 일. 턴이 바뀌면 :meth:`reset` 으로 지운다."""

    drew_for_turn: bool = False
    entered_battle_phase: bool = False

    def reset(self) -> None:
        self.drew_for_turn = False
        self.entered_battle_phase = False

    def clone(self) -> "TurnFlags":
        return TurnFlags(
            drew_for_turn=self.drew_for_turn,
            entered_battle_phase=self.entered_battle_phase,
        )

    def canonical_state(self) -> tuple:
        return (self.drew_for_turn, self.entered_battle_phase)


class UseRegistry:
    """
    "1턴에 1번" 사용 기록.

    ``analysis`` 가 구분한 :class:`~analysis.effect_model.LimitScope` 세 가지를
    **각각 따로** 저장한다. 키가 다르기 때문에 한 곳에 뭉뚱그리면 안 된다.

    ===============  ======================  =========================
    스코프            Lua                     키
    ===============  ======================  =========================
    PER_CARD         ``SetCountLimit(1)``    ``InstanceId``
    PER_CARD_NAME    ``SetCountLimit(1,id)`` ``(player, card_id)``
    PER_EFFECT       ``SetCountLimit(1,..)`` ``(player, card_id, ordinal)``
    ===============  ======================  =========================

    설계 문서는 ``set`` 세 개로 적었지만 여기서는 **횟수 카운터**로 둔다.
    실측상 ``SetCountLimit(2..4, ...)`` 를 쓰는 효과가 53건 있어서 "썼다/안 썼다"
    로는 표현되지 않는다. 판정 자체(몇 번까지 허용인가)는 Phase 4 의 일이고,
    여기서는 횟수만 기록한다.
    """

    __slots__ = ("per_card", "per_card_name", "per_effect")

    def __init__(
        self,
        per_card: dict[InstanceId, int] | None = None,
        per_card_name: dict[tuple[int, int], int] | None = None,
        per_effect: dict[tuple[int, int, int], int] | None = None,
    ):
        self.per_card: dict[InstanceId, int] = dict(per_card or {})
        self.per_card_name: dict[tuple[int, int], int] = dict(per_card_name or {})
        self.per_effect: dict[tuple[int, int, int], int] = dict(per_effect or {})

    # --- 기록 ---------------------------------------------------------
    def record_card(self, instance_id: InstanceId, times: int = 1) -> int:
        self.per_card[instance_id] = self.per_card.get(instance_id, 0) + times
        return self.per_card[instance_id]

    def record_card_name(self, player: int, card_id: int, times: int = 1) -> int:
        key = (player, card_id)
        self.per_card_name[key] = self.per_card_name.get(key, 0) + times
        return self.per_card_name[key]

    def record_effect(
        self, player: int, effect_ref: EffectRef, times: int = 1
    ) -> int:
        key = (player, effect_ref.card_id, effect_ref.ordinal)
        self.per_effect[key] = self.per_effect.get(key, 0) + times
        return self.per_effect[key]

    def record(
        self,
        scope: LimitScope,
        *,
        player: int,
        instance_id: InstanceId | None = None,
        card_id: int | None = None,
        effect_ref: EffectRef | None = None,
        times: int = 1,
    ) -> int:
        """
        스코프에 맞는 칸에 기록한다. 필요한 키가 없으면 조용히 넘어가지 않고
        ``ValueError`` 를 낸다 — 잘못된 칸에 기록되면 제한이 통째로 틀어진다.
        """
        if scope is LimitScope.PER_CARD:
            if instance_id is None:
                raise ValueError("PER_CARD 기록에는 instance_id 가 필요합니다.")
            return self.record_card(instance_id, times)
        if scope is LimitScope.PER_CARD_NAME:
            return self.record_card_name(
                player, self._card_id_of(card_id, effect_ref), times
            )
        if scope is LimitScope.PER_EFFECT:
            if effect_ref is None:
                raise ValueError("PER_EFFECT 기록에는 effect_ref 가 필요합니다.")
            return self.record_effect(player, effect_ref, times)
        raise ValueError(f"기록할 수 없는 스코프입니다: {scope}")

    # --- 조회 ---------------------------------------------------------
    def count_card(self, instance_id: InstanceId) -> int:
        return self.per_card.get(instance_id, 0)

    def count_card_name(self, player: int, card_id: int) -> int:
        return self.per_card_name.get((player, card_id), 0)

    def count_effect(self, player: int, effect_ref: EffectRef) -> int:
        return self.per_effect.get((player, effect_ref.card_id, effect_ref.ordinal), 0)

    def count(
        self,
        scope: LimitScope,
        *,
        player: int,
        instance_id: InstanceId | None = None,
        card_id: int | None = None,
        effect_ref: EffectRef | None = None,
    ) -> int:
        if scope is LimitScope.PER_CARD:
            if instance_id is None:
                raise ValueError("PER_CARD 조회에는 instance_id 가 필요합니다.")
            return self.count_card(instance_id)
        if scope is LimitScope.PER_CARD_NAME:
            return self.count_card_name(
                player, self._card_id_of(card_id, effect_ref)
            )
        if scope is LimitScope.PER_EFFECT:
            if effect_ref is None:
                raise ValueError("PER_EFFECT 조회에는 effect_ref 가 필요합니다.")
            return self.count_effect(player, effect_ref)
        raise ValueError(f"조회할 수 없는 스코프입니다: {scope}")

    def used(self, scope: LimitScope, **kwargs) -> bool:
        return self.count(scope, **kwargs) > 0

    @staticmethod
    def _card_id_of(card_id: int | None, effect_ref: EffectRef | None) -> int:
        if card_id is not None:
            return card_id
        if effect_ref is not None:
            return effect_ref.card_id
        raise ValueError(
            "PER_CARD_NAME 은 카드 ID 가 필요합니다. card_id 나 effect_ref 를 넘기세요."
        )

    # --- 초기화 · 복제 --------------------------------------------------
    def clear(self) -> None:
        """턴이 끝날 때 호출한다. **언제 호출할지는 Phase 1 이 정하지 않는다.**"""
        self.per_card.clear()
        self.per_card_name.clear()
        self.per_effect.clear()

    def clone(self) -> "UseRegistry":
        return UseRegistry(
            per_card=self.per_card,
            per_card_name=self.per_card_name,
            per_effect=self.per_effect,
        )

    def canonical_state(self) -> tuple:
        return (
            tuple(sorted((k.value, v) for k, v in self.per_card.items())),
            tuple(sorted(self.per_card_name.items())),
            tuple(sorted(self.per_effect.items())),
        )

    def __len__(self) -> int:
        return len(self.per_card) + len(self.per_card_name) + len(self.per_effect)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<UseRegistry card={len(self.per_card)} "
            f"name={len(self.per_card_name)} effect={len(self.per_effect)}>"
        )


@dataclass(slots=True)
class PlayerState:
    """플레이어 한 명이 소유한 듀얼 상태 전부."""

    player_id: int
    life_points: int = DEFAULT_LIFE_POINTS
    zones: dict[Zone, ZoneContainer] = field(default_factory=dict)
    normal_summon_used: int = 0
    normal_summon_allowed: int = 1
    turn_flags: TurnFlags = field(default_factory=TurnFlags)
    uses: UseRegistry = field(default_factory=UseRegistry)

    def __post_init__(self) -> None:
        for zone in PLAYER_ZONES:
            if zone not in self.zones:
                self.zones[zone] = ZoneContainer(zone, self.player_id)

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

    def all_instances(self) -> list[CardInstance]:
        cards: list[CardInstance] = []
        for zone in PLAYER_ZONES:
            cards.extend(self.zones[zone])
        return cards

    # ------------------------------------------------------------------
    # 라이프 · 소환 횟수
    # ------------------------------------------------------------------
    def change_life(self, delta: int) -> int:
        """라이프를 더하거나 뺀다. 0 아래로는 내려가지 않는다 (승패 판정은 별개)."""
        self.life_points = max(0, self.life_points + delta)
        return self.life_points

    def record_normal_summon(self, times: int = 1) -> int:
        """일반 소환을 했다고 기록한다. 가능한지는 판정하지 않는다."""
        self.normal_summon_used += times
        return self.normal_summon_used

    def reset_for_turn(self) -> None:
        """
        턴이 시작될 때 초기화되는 것들. **호출 시점은 호출자가 정한다** —
        Phase 1 은 턴 진행 규칙을 갖지 않는다.
        """
        self.normal_summon_used = 0
        self.turn_flags.reset()
        self.uses.clear()

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "PlayerState":
        return PlayerState(
            player_id=self.player_id,
            life_points=self.life_points,
            zones={zone: container.clone() for zone, container in self.zones.items()},
            normal_summon_used=self.normal_summon_used,
            normal_summon_allowed=self.normal_summon_allowed,
            turn_flags=self.turn_flags.clone(),
            uses=self.uses.clone(),
        )

    def canonical_state(self) -> tuple:
        return (
            self.player_id,
            self.life_points,
            tuple(
                self.zones[zone].canonical_state()
                for zone in PLAYER_ZONES
                if zone in self.zones
            ),
            self.normal_summon_used,
            self.normal_summon_allowed,
            self.turn_flags.canonical_state(),
            self.uses.canonical_state(),
        )
