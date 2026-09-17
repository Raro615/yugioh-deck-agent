"""
Action 이 무엇을 가리키는가.

**파이썬 객체 참조를 저장하지 않는다.** ``CardInstance`` 를 그대로 담으면
Action 이 특정 ``GameState`` 에 묶이고, 직렬화도 replay 도 불가능해진다.
저장하는 것은 전부 Phase 1 이 이미 정의한 **안정적인 식별자**다.

=================  =========================  =================================
대상                담는 값                     예
=================  =========================  =================================
``INSTANCE``       :class:`InstanceId`        "저 몬스터"
``PLAYER``         ``int``                    "상대에게 직접 공격"
``ZONE``           ``(player, Zone, index?)`` "내 몬스터 존 3번 칸"
``NONE``           없음                        대상이 없는 행위
=================  =========================  =================================

``index`` 가 ``None`` 인 ``ZONE`` 은 "그 존 전체"를 뜻하고, 숫자가 있으면
**칸 하나**를 뜻한다. 순서 존(덱 · 패 · 묘지)에는 칸이 없으므로 숫자를 붙이면
거부한다 — 존재하지 않는 자리를 가리키는 Action 이 만들어지지 않게 한다.

Phase 2-A 가 하지 않는 것: **그 대상이 적법한가**. "저 몬스터를 정말 공격할
수 있는가" 는 규칙이고 Phase 2-B 이후의 몫이다. 여기서는 *가리킬 수 있는
모양인가*만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.ids import InstanceId
from engine.vocabulary import Zone, ZoneKind, zone_capacity, zone_kind


class ActionTargetKind(str, Enum):
    """대상의 종류."""

    NONE = "none"
    INSTANCE = "instance"
    PLAYER = "player"
    ZONE = "zone"


@dataclass(frozen=True, slots=True)
class ActionTarget:
    """
    Action 이 가리키는 대상 하나. **불변**이고 값 타입만 담는다.

    직접 만들기보다 :meth:`instance` · :meth:`player` · :meth:`zone` ·
    :meth:`none` 을 쓴다. 종류별로 채워야 하는 칸이 다르고, 생성자가
    그것을 검사한다.
    """

    kind: ActionTargetKind
    instance_id: InstanceId | None = None
    player: int | None = None
    zone: Zone | None = None
    index: int | None = None
    """칸 번호. ``None`` 이면 존 전체."""

    def __post_init__(self) -> None:
        checker = {
            ActionTargetKind.NONE: self._check_none,
            ActionTargetKind.INSTANCE: self._check_instance,
            ActionTargetKind.PLAYER: self._check_player,
            ActionTargetKind.ZONE: self._check_zone,
        }.get(self.kind)
        if checker is None:
            raise ValueError(f"알 수 없는 대상 종류입니다: {self.kind!r}")
        checker()

    # ------------------------------------------------------------------
    # 종류별 구조 검사 — 규칙이 아니라 **모양**만 본다
    # ------------------------------------------------------------------
    def _filled(self) -> set[str]:
        names = ("instance_id", "player", "zone", "index")
        return {name for name in names if getattr(self, name) is not None}

    def _require_only(self, *allowed: str) -> None:
        extra = self._filled() - set(allowed)
        if extra:
            raise ValueError(
                f"{self.kind.value} 대상에는 {sorted(extra)} 를 채울 수 없습니다."
            )

    def _check_none(self) -> None:
        self._require_only()

    def _check_instance(self) -> None:
        self._require_only("instance_id")
        if self.instance_id is None:
            raise ValueError("instance 대상에는 instance_id 가 필요합니다.")

    def _check_player(self) -> None:
        self._require_only("player")
        if self.player is None:
            raise ValueError("player 대상에는 player 가 필요합니다.")
        if self.player not in (0, 1):
            raise ValueError(f"플레이어 번호는 0 또는 1 입니다: {self.player}")

    def _check_zone(self) -> None:
        self._require_only("player", "zone", "index")
        if self.player is None or self.zone is None:
            raise ValueError("zone 대상에는 player 와 zone 이 필요합니다.")
        if self.player not in (0, 1):
            raise ValueError(f"플레이어 번호는 0 또는 1 입니다: {self.player}")
        if self.index is None:
            return
        if zone_kind(self.zone) is not ZoneKind.SLOTTED:
            raise ValueError(
                f"{self.zone.value} 는 칸이 없는 존이라 칸 번호를 가리킬 수 "
                "없습니다. 존 전체를 가리키려면 index 를 비우세요."
            )
        capacity = zone_capacity(self.zone)
        assert capacity is not None  # SLOTTED 존은 항상 칸 수가 있다
        if not 0 <= self.index < capacity:
            raise ValueError(
                f"{self.zone.value} 의 칸은 0..{capacity - 1} 입니다: {self.index}"
            )

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------
    @classmethod
    def none(cls) -> "ActionTarget":
        return cls(kind=ActionTargetKind.NONE)

    @classmethod
    def instance(cls, instance_id: InstanceId) -> "ActionTarget":
        return cls(kind=ActionTargetKind.INSTANCE, instance_id=instance_id)

    @classmethod
    def player_target(cls, player: int) -> "ActionTarget":
        """플레이어 자신을 가리킨다 (직접 공격 등)."""
        return cls(kind=ActionTargetKind.PLAYER, player=player)

    @classmethod
    def zone_target(
        cls, player: int, zone: Zone, index: int | None = None
    ) -> "ActionTarget":
        return cls(kind=ActionTargetKind.ZONE, player=player, zone=zone, index=index)

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        """정수 · 문자열 · ``None`` 만으로 이루어진 정규 표현."""
        return (
            self.kind.value,
            self.instance_id.value if self.instance_id is not None else None,
            self.player,
            self.zone.value if self.zone is not None else None,
            self.index,
        )

    def to_dict(self) -> dict:
        """JSON 으로 바로 나갈 수 있는 형태. 빈 칸은 넣지 않는다."""
        data: dict = {"kind": self.kind.value}
        if self.instance_id is not None:
            data["instance_id"] = self.instance_id.value
        if self.player is not None:
            data["player"] = self.player
        if self.zone is not None:
            data["zone"] = self.zone.value
        if self.index is not None:
            data["index"] = self.index
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ActionTarget":
        instance_id = data.get("instance_id")
        zone = data.get("zone")
        return cls(
            kind=ActionTargetKind(data["kind"]),
            instance_id=InstanceId(instance_id) if instance_id is not None else None,
            player=data.get("player"),
            zone=Zone(zone) if zone is not None else None,
            index=data.get("index"),
        )

    def __str__(self) -> str:
        if self.kind is ActionTargetKind.NONE:
            return "-"
        if self.kind is ActionTargetKind.INSTANCE:
            return str(self.instance_id)
        if self.kind is ActionTargetKind.PLAYER:
            return f"P{self.player}"
        slot = "" if self.index is None else f"[{self.index}]"
        assert self.zone is not None
        return f"P{self.player}/{self.zone.value}{slot}"
