"""
StateDelta — **무슨 변화가 일어났는가**의 구조적 기록.

    EffectExecutor
        ↓  GameState mutation        ← 실제 변경은 여전히 여기서 일어난다
        ↓  StateDelta                ← 그 변경을 값으로 적어 둔다
        ↓  EventJournal

Delta 는 판을 바꾸지 않는다
---------------------------
**가장 중요한 성질이다.** :class:`StateDelta` 에 ``apply(state)`` 도
``undo(state)`` 도 없다. 지금 단계에서 Delta 는 *계획*이 아니라 *기록*이고,
기록이 판을 바꿀 수 있게 되는 순간 "무슨 일이 있었는가" 와 "무슨 일을
하겠다" 가 한 타입에 섞인다.

되돌리기(rollback)와 재생(replay)은 여기서 만들지 않는다 (ADR-008). 다만
그것들이 필요로 할 정보 — 어느 카드가 · 어디에서 · 어디로 · **무슨
의미로** 움직였는가 — 는 지금부터 빠짐없이 남긴다. 나중에 추가할 수 없는
것은 그때 사라진 정보뿐이다.

AppliedOperation 과 다르다
--------------------------
=========================  ================================================
``AppliedOperation``        어떤 **효과의 일**을 실행했는가
``StateDelta``              그 실행으로 **판이 어떻게 달라졌는가**
=========================  ================================================

하나의 ``AppliedOperation`` 이 여러 :class:`StateDelta` 를 낳는다. "몬스터
2장을 제외한다" 는 일 하나 · 변화 둘이다.

목적지가 같아도 같은 사건이 아니다
----------------------------------
파괴 · 묘지로 보내기 · 릴리스 · 버리기는 **전부 묘지로 간다.** Delta 가
목적지만 적으면 그 넷이 하나로 뭉개지고, 트리거 계층은 "파괴되었을 때" 를
영영 구분할 수 없다. 그래서 :class:`ZoneMoved` 는 ``operation`` 을 함께
들고 있다 (ADR-002).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.effect.operation import REASON_NAMES, OperationKind
from engine.ids import InstanceId
from engine.vocabulary import Phase, Position, Zone


@dataclass(frozen=True, slots=True)
class StateDelta:
    """
    상태 변화 하나. **불변**이고, 값 타입만 담는다.

    ``canonical_state()`` 는 결정론적이어야 한다 — 객체 주소도, 파이썬
    기본 ``hash()`` 도, ``repr`` 도 들어가지 않는다. 같은 변화는 프로세스를
    다시 띄워도 같은 표현이다.
    """

    @property
    def kind(self) -> str:
        """Delta 의 종류 이름. 직렬화에서 타입을 가려내는 데 쓴다."""
        raise NotImplementedError  # pragma: no cover - 추상

    def canonical_state(self) -> tuple:
        raise NotImplementedError  # pragma: no cover - 추상

    def to_dict(self) -> dict:
        raise NotImplementedError  # pragma: no cover - 추상

    def describe_ko(self) -> str:
        raise NotImplementedError  # pragma: no cover - 추상

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class CardMovement(StateDelta):
    """
    **카드가 움직인** 변화의 공통 기반.

    트리거 계층이 "이번에 움직인 카드" 를 물을 때 종류를 하나하나 세지
    않아도 되도록 둔다.

        for delta in result.deltas:
            if isinstance(delta, CardMovement):
                ...

    필드를 여기에 두지 않는다 — 드로우는 ``player`` 하나로 충분하고
    나머지는 출발·도착의 주인이 다를 수 있어서, 같은 모양이 아니다.
    """

    @property
    def instance(self) -> InstanceId:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def operation(self) -> OperationKind:
        """**무슨 의미로** 움직였는가. 목적지로는 알 수 없다."""
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def from_player(self) -> int:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def from_zone(self) -> Zone:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def to_player(self) -> int:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def to_zone(self) -> Zone:
        raise NotImplementedError  # pragma: no cover - 추상

    @property
    def reason_names(self) -> tuple[str, ...]:
        """``REASON_*`` 상수 **이름들.** 값은 ``constant.lua`` 에서 읽는다."""
        return REASON_NAMES[self.operation]

    @property
    def changed_side(self) -> bool:
        """카드가 **반대쪽 플레이어의** 존으로 넘어갔는가."""
        return self.from_player != self.to_player


@dataclass(frozen=True, slots=True)
class ZoneMoved(CardMovement):
    """
    카드 한 장이 존을 옮겼다.

    ``operation`` 이 ``DRAW`` 인 경우는 **거부한다.** 드로우는
    :class:`CardDrawn` 하나로만 표현한다 — 같은 사실을 두 모양으로 적을 수
    있으면 세는 쪽이 반드시 두 번 센다.
    """

    movement: OperationKind
    card: InstanceId
    source_player: int
    source_zone: Zone
    destination_player: int
    destination_zone: Zone

    def __post_init__(self) -> None:
        if self.movement is OperationKind.DRAW:
            raise ValueError(
                "드로우는 CardDrawn 으로 적습니다. 한 사실을 두 모양으로 "
                "적으면 세는 쪽이 두 번 셉니다."
            )
        if self.movement is OperationKind.CHANGE_LIFE:
            raise ValueError("라이프 변화는 카드 이동이 아닙니다.")
        for name in ("source_player", "destination_player"):
            if getattr(self, name) not in (0, 1):
                raise ValueError(f"{name} 는 0 또는 1 입니다: {getattr(self, name)}")

    # --- CardMovement ------------------------------------------------
    @property
    def kind(self) -> str:
        return "zone_moved"

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def operation(self) -> OperationKind:
        return self.movement

    @property
    def from_player(self) -> int:
        return self.source_player

    @property
    def from_zone(self) -> Zone:
        return self.source_zone

    @property
    def to_player(self) -> int:
        return self.destination_player

    @property
    def to_zone(self) -> Zone:
        return self.destination_zone

    def canonical_state(self) -> tuple:
        return (
            "zone_moved",
            self.movement.value,
            self.card.value,
            self.source_player,
            self.source_zone.value,
            self.destination_player,
            self.destination_zone.value,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "zone_moved",
            "operation": self.movement.value,
            "reasons": list(self.reason_names),
            "instance": self.card.value,
            "from": {"player": self.source_player, "zone": self.source_zone.value},
            "to": {
                "player": self.destination_player,
                "zone": self.destination_zone.value,
            },
        }

    def describe_ko(self) -> str:
        return (
            f"{self.card} P{self.source_player}/{self.source_zone.value} → "
            f"P{self.destination_player}/{self.destination_zone.value} "
            f"({self.movement.value})"
        )


@dataclass(frozen=True, slots=True)
class CardDrawn(CardMovement):
    """
    카드 한 장을 뽑았다. 덱 맨 위에서 **뽑은 사람의** 패로 간다.

    존 이동이기도 하지만 따로 둔다 — 드로우는 그 자체가 규칙상 별개의
    사건이고 ("드로우했을 때" 트리거가 따로 있다), 출발·도착이 언제나
    같은 플레이어라서 모양도 다르다.
    """

    player: int
    card: InstanceId

    def __post_init__(self) -> None:
        if self.player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {self.player}")

    # --- CardMovement ------------------------------------------------
    @property
    def kind(self) -> str:
        return "card_drawn"

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def operation(self) -> OperationKind:
        return OperationKind.DRAW

    @property
    def from_player(self) -> int:
        return self.player

    @property
    def from_zone(self) -> Zone:
        return Zone.DECK

    @property
    def to_player(self) -> int:
        return self.player

    @property
    def to_zone(self) -> Zone:
        return Zone.HAND

    def canonical_state(self) -> tuple:
        return ("card_drawn", self.player, self.card.value)

    def to_dict(self) -> dict:
        return {
            "kind": "card_drawn",
            "operation": OperationKind.DRAW.value,
            "reasons": list(self.reason_names),
            "instance": self.card.value,
            "from": {"player": self.player, "zone": Zone.DECK.value},
            "to": {"player": self.player, "zone": Zone.HAND.value},
        }

    def describe_ko(self) -> str:
        return f"P{self.player} 가 {self.card} 를 드로우"


@dataclass(frozen=True, slots=True)
class LifeChanged(StateDelta):
    """
    라이프가 바뀌었다.

    **요청한 변화량이 아니라 실제로 달라진 값**을 적는다.
    ``PlayerState.change_life`` 는 0 아래로 내려가지 않으므로, 1000 남은
    플레이어에게 -3000 을 걸면 실제 변화는 -1000 이다. 요청한 값은
    ``AppliedOperation.amount`` 에 그대로 남아 있고, 둘의 차이가 곧
    "얼마가 막혔는가" 다.
    """

    player: int
    before: int
    after: int

    def __post_init__(self) -> None:
        if self.player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {self.player}")
        if self.before < 0 or self.after < 0:
            raise ValueError("라이프는 음수가 될 수 없습니다.")

    @property
    def kind(self) -> str:
        return "life_changed"

    @property
    def amount(self) -> int:
        """실제 변화량. 줄었으면 음수다."""
        return self.after - self.before

    @property
    def is_loss(self) -> bool:
        return self.after < self.before

    def canonical_state(self) -> tuple:
        return ("life_changed", self.player, self.before, self.after)

    def to_dict(self) -> dict:
        return {
            "kind": "life_changed",
            "player": self.player,
            "before": self.before,
            "after": self.after,
            "amount": self.amount,
        }

    def describe_ko(self) -> str:
        return f"P{self.player} 라이프 {self.before} → {self.after}"


@dataclass(frozen=True, slots=True)
class PhaseChanged(StateDelta):
    """
    게임의 시간이 움직였다 — 페이즈가, 때로는 턴까지 바뀌었다.

    **턴 바뀜을 따로 만들지 않는다.** 턴이 넘어가는 것은 언제나 엔드
    페이즈에서 다음 턴의 드로우 페이즈로 가는 *한 번의* 이동이고, 그것을
    ``PhaseChanged`` 와 ``TurnChanged`` 두 장으로 적으면 세는 쪽이 한 사건을
    두 번 센다 (``ZoneMoved`` 와 ``CardDrawn`` 을 갈라놓은 이유와 정반대의
    이유다 — 저쪽은 두 사건이고 이쪽은 한 사건이다). 턴이 함께 바뀌었는지는
    :attr:`changes_turn` 이 말한다.

    카드가 움직이지 않으므로 :class:`CardMovement` 가 아니다.
    """

    from_turn: int
    from_player: int
    from_phase: Phase
    to_turn: int
    to_player: int
    to_phase: Phase

    def __post_init__(self) -> None:
        for name in ("from_player", "to_player"):
            if getattr(self, name) not in (0, 1):
                raise ValueError(f"{name} 는 0 또는 1 입니다: {getattr(self, name)}")
        for name in ("from_turn", "to_turn"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} 은 1 이상이어야 합니다: {getattr(self, name)}")
        if self.to_turn < self.from_turn:
            raise ValueError(
                f"턴은 되감기지 않습니다: {self.from_turn} → {self.to_turn}"
            )
        if self.canonical_state()[1:4] == self.canonical_state()[4:]:
            raise ValueError(
                "달라진 것이 없는데 변화로 적을 수 없습니다. 아무 일도 "
                "일어나지 않았다면 Delta 를 만들지 않습니다."
            )

    @property
    def kind(self) -> str:
        return "phase_changed"

    @property
    def changes_turn(self) -> bool:
        """턴까지 넘어갔는가. 턴 번호가 곧 사실이다."""
        return self.to_turn != self.from_turn

    @property
    def changes_turn_player(self) -> bool:
        return self.to_player != self.from_player

    def canonical_state(self) -> tuple:
        return (
            "phase_changed",
            self.from_turn,
            self.from_player,
            self.from_phase.value,
            self.to_turn,
            self.to_player,
            self.to_phase.value,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "phase_changed",
            "from": {
                "turn": self.from_turn,
                "player": self.from_player,
                "phase": self.from_phase.value,
            },
            "to": {
                "turn": self.to_turn,
                "player": self.to_player,
                "phase": self.to_phase.value,
            },
            "changes_turn": self.changes_turn,
        }

    def describe_ko(self) -> str:
        return (
            f"T{self.from_turn} P{self.from_player} {self.from_phase.value} → "
            f"T{self.to_turn} P{self.to_player} {self.to_phase.value}"
        )


class SummonKind(str, Enum):
    """
    어떤 소환인가. **지금 있는 것은 일반 소환뿐이다.**

    특수 소환 · 반전 소환 · 제물 소환은 그 절차가 생길 때 함께 들어온다.
    계층이 없는 이름을 미리 못박으면 나중에 실제 모양과 어긋난다
    (:class:`~engine.trigger.TimingPoint` 가 전투 · 데미지를 아직 넣지 않은
    이유와 같다 — 소환은 이 절차가 생긴 뒤에야 그쪽에도 이름이 생겼다).
    """

    NORMAL = "normal"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class MonsterSummoned(StateDelta):
    """
    몬스터가 **소환되었다.**

    왜 :class:`CardMovement` 가 아닌가
    ----------------------------------
    카드가 패에서 몬스터 존으로 움직인 것은 맞다. 그런데
    :attr:`CardMovement.operation` 은 :class:`
    ~engine.effect.operation.OperationKind` — **효과가 하는 일**의 어휘다
    (``REASON_NAMES`` 가 전부 ``EFFECT`` 를 달고 있다). 소환은 효과가 아니라
    규칙에 따른 플레이어의 행위이므로, 그 어휘에 끼워 넣으면 "효과로
    묘지에 보내졌다" 와 "일반 소환되었다" 가 같은 표를 쓰게 된다.

    그래서 움직임의 정보(:attr:`from_zone` · :attr:`to_zone` ·
    :attr:`to_index`)는 그대로 들고, 의미는 :attr:`summon` 이 말한다.

    제물은 여기 없다
    ----------------
    제물을 바치는 것은 **다른 카드들이 필드를 떠나는** 별개의 변화다. 빈
    ``tributes`` 칸을 미리 만들어 두면 그 칸이 "이 소환이 제물을 소유한다"
    고 말하게 된다. 제물 절차가 생기면 그때 자기 변화를 따로 적는다.
    """

    summon: SummonKind
    card: InstanceId
    player: int
    """소환한 사람. 소환된 몬스터의 컨트롤러다."""
    owner: int
    """카드의 주인. 컨트롤러와 **다를 수 있다** (ADR: Owner ≠ Controller)."""
    from_zone: Zone
    to_zone: Zone
    to_index: int
    """놓인 칸 번호. 몬스터 존은 칸이 밀리지 않으므로 자리가 곧 사실이다."""
    position: Position

    def __post_init__(self) -> None:
        for name in ("player", "owner"):
            if getattr(self, name) not in (0, 1):
                raise ValueError(f"{name} 는 0 또는 1 입니다: {getattr(self, name)}")
        if self.to_index < 0:
            raise ValueError(f"칸 번호는 음수일 수 없습니다: {self.to_index}")
        if self.from_zone is self.to_zone:
            raise ValueError(
                "소환은 다른 존으로 나오는 것입니다: "
                f"{self.from_zone.value} → {self.to_zone.value}"
            )

    @property
    def kind(self) -> str:
        return "monster_summoned"

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def changed_side(self) -> bool:
        """주인이 아닌 쪽이 소환했는가. 지금은 언제나 거짓이다."""
        return self.owner != self.player

    def canonical_state(self) -> tuple:
        return (
            "monster_summoned",
            self.summon.value,
            self.card.value,
            self.player,
            self.owner,
            self.from_zone.value,
            self.to_zone.value,
            self.to_index,
            self.position.value,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "monster_summoned",
            "summon": self.summon.value,
            "instance": self.card.value,
            "player": self.player,
            "owner": self.owner,
            "from": {"zone": self.from_zone.value},
            "to": {
                "zone": self.to_zone.value,
                "index": self.to_index,
                "position": self.position.value,
            },
        }

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 가 {self.card} 를 {self.from_zone.value} 에서 "
            f"{self.to_zone.value}[{self.to_index}] 로 "
            f"{self.summon.value} 소환 ({self.position.value})"
        )


def canonical_deltas(deltas) -> tuple:
    """변화 묶음의 정규 표현. **순서를 지킨다** — 순서가 곧 사실이다."""
    return tuple(delta.canonical_state() for delta in deltas)


__all__ = [
    "StateDelta",
    "CardMovement",
    "ZoneMoved",
    "CardDrawn",
    "LifeChanged",
    "PhaseChanged",
    "SummonKind",
    "MonsterSummoned",
    "canonical_deltas",
]
