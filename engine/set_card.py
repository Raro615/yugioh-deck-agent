"""
SetExecutor — **카드를 뒷면으로 놓는 자리** (Phase 3-E-2).

    PlayerAction.set_monster(...) / set_spell_trap(...)
          ↓  ActionExecutor (등록된 핸들러)
    SetMonsterHandler / SetSpellTrapHandler → SetExecutor
          ↓  기존 배치 절차를 그대로 쓴다
    SummonProcedure.plan() · place() · verify()
          ↓
    CardSet delta

세트는 소환이 아니다
--------------------
이 모듈이 존재하는 이유의 절반이 이 문장이다.

    RULE-SUMMON-010 — "To play a Monster Card from your hand in face-down
    Defense Position is called a Normal Set. **A monster Normal Set on the
    field is NOT considered Summoned.** It has been Normal Set, and can be
    Summoned with a Flip Summon..."

그래서 :class:`~engine.effect.delta.MonsterSummoned` 를 만들지 **않는다.**
그것을 만들면 "소환했을 때" 를 조건으로 하는 카드가 세트에 반응하게 되고,
그것은 규칙 위반이다. ``SummonKind`` 에 ``SET`` 을 더하는 길도 택하지
않았다 — 그 열거형의 이름이 "어떤 **소환**인가" 이므로 같은 범주 오류다.

대신 :class:`CardSet` 을 만든다. 세 가지가 **서로 다른 사실**로 남는다.

    MonsterSummoned(NORMAL)    일반 소환
    MonsterSummoned(SPECIAL)   특수 소환
    CardSet                    세트 — 소환이 아니다

배치는 새로 만들지 않았다
-------------------------
:class:`~engine.summon.SummonProcedure` 가 **표시 형식으로 매개화**되어
있으므로 ``position=FACEDOWN_DEFENSE`` 로 그대로 쓴다. 빈 칸 고르기 ·
컨트롤러 확인 · 착지 확인 · "떠났는가" 확인이 전부 거기 있다. 그 절차의
``summon`` 칸만 ``None`` 으로 비워 "이 배치는 소환이 아니다" 를 적는다.

소환권도 새로 만들지 않았다
---------------------------
``RuleActionKind`` 의 설명이 이미 적어 두었다 — *"소환권은 일반 소환과
세트가 나눠 쓴다 (RULE-SUMMON-009) ... 세트가 구현되면 **같은 이름으로
기록한다** — 이름을 나누면 한 턴에 둘 다 할 수 있게 된다."* 그대로 따른다.

여기서 하지 않는 것
-------------------
세트한 카드를 **발동하지 않는다.** 뒤집지도 않는다 (Flip Summon,
RULE-SUMMON-012). 마법 · 함정의 발동 타이밍도 보지 않는다. 이 모듈이 하는
일은 "패에서 뒷면으로 놓는 것" 하나다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.effect.delta import CardMovement, StateDelta
from engine.effect.operation import OperationKind
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.summon import SummonError, SummonPlacement, SummonProcedure
from engine.vocabulary import Position, Zone


class SetError(SummonError):
    """
    세트를 진행할 수 없다. **적법성 판정이 아니다** — 그것은 이미 끝났고,
    여기서 걸리는 것은 허가와 판이 어긋났다는 뜻이다.

    :class:`~engine.summon.SummonError` 를 물려받는 이유는 배치 절차가
    자기 예외 타입을 던지도록 만들어져 있기 때문이다.
    """


#: 세트의 출발 자리. 패에서만 놓는다 (RULE-SUMMON-010 · RULE-TURN-004).
SET_FROM_ZONE: Zone = Zone.HAND

#: 몬스터 세트의 표시 형식. **고를 수 없다** — "playing it in face-down
#: Defense Position **is** called a Set" (RULE-TERM-021).
SET_MONSTER_POSITION: Position = Position.FACEDOWN_DEFENSE

#: 마법 · 함정 세트의 표시 형식. 수비 · 공격이라는 개념이 없다.
SET_SPELL_TRAP_POSITION: Position = Position.FACEDOWN


@dataclass(frozen=True, slots=True)
class CardSet(CardMovement):
    """
    카드 한 장을 **뒷면으로 놓았다.** 소환이 아니다.

    ``MonsterSummoned`` 를 쓰지 않는 이유가 이 클래스의 전부다
    (RULE-SUMMON-010). :class:`~engine.effect.delta.CardMovement` 를
    물려받으므로 "이번에 움직인 카드" 를 세는 기존 코드가 **고치지 않고**
    이것도 센다.

    :attr:`operation` 이 ``MOVE`` 인 이유: ``OperationKind`` 는 **효과**의
    어휘이고 (``engine.effect.operation``) 세트는 효과가 아니다. 거기에
    ``DESTROY`` 나 ``SEND_TO_GRAVE`` 처럼 의미를 주장하는 값을 고르면 거짓이
    되고, ``MOVE`` 는 "목적지만 말하고 무슨 일인지는 말하지 않는다" 를 뜻한다
    — 무슨 일인지는 이 **델타의 타입**이 말한다.

    그래서 :attr:`reason_names` 도 비어 있다. 세트는 아무것도 파괴하지 않고
    아무것도 묘지로 보내지 않으므로, 주장할 이유가 없는 것이 사실이다.
    """

    card: InstanceId
    player: int
    """놓는 사람. 놓인 카드의 컨트롤러가 된다."""
    owner: int
    """카드의 주인. **놓는다고 주인이 바뀌지 않는다** (ADR: Owner ≠ Controller)."""
    source_player: int
    """
    카드가 **어느 쪽의** 자리에서 나왔는가.

    이름이 ``from_player`` 가 아닌 이유: :class:`CardMovement` 가 그 이름을
    **프로퍼티로** 이미 쓰고 있어서, 같은 이름의 필드를 선언하면 dataclass 가
    프로퍼티 객체를 기본값으로 읽는다. ``BattleDestruction`` 도 같은 이유로
    ``source_zone`` 을 쓴다.
    """
    source_zone: Zone
    destination_zone: Zone
    destination_index: int
    position: Position

    def __post_init__(self) -> None:
        if self.position.value not in ("FACEDOWN", "FACEDOWN_DEFENSE"):
            raise SetError(
                f"세트는 뒷면입니다: {self.position.value} (RULE-TERM-021)"
            )

    @property
    def kind(self) -> str:
        return "card_set"

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def operation(self) -> OperationKind:
        """**의미를 주장하지 않는다.** 무슨 일인지는 이 델타의 타입이 말한다."""
        return OperationKind.MOVE

    @property
    def from_zone(self) -> Zone:
        return self.source_zone

    @property
    def from_player(self) -> int:
        return self.source_player

    @property
    def to_player(self) -> int:
        return self.player

    @property
    def to_zone(self) -> Zone:
        return self.destination_zone

    @property
    def reason_names(self) -> tuple[str, ...]:
        """
        **비어 있는 것이 사실이다.** 세트는 파괴도 송치도 아니다.

        여기에 ``EFFECT`` 를 적으면 트리거 계층이 세트를 "효과로 움직였다"
        로 읽는다 (``BattleDestruction`` 이 ``EFFECT`` 를 거부한 것과 같은
        자리다).
        """
        return ()

    @property
    def is_monster_set(self) -> bool:
        """몬스터를 뒷면 수비 표시로 놓았는가."""
        return self.position is Position.FACEDOWN_DEFENSE

    def canonical_state(self) -> tuple:
        return (
            "card_set",
            self.card.value,
            self.player,
            self.owner,
            self.source_player,
            self.source_zone.value,
            self.destination_zone.value,
            self.destination_index,
            self.position.value,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "card_set",
            "card": self.card.value,
            "player": self.player,
            "owner": self.owner,
            "from_player": self.source_player,
            "from_zone": self.source_zone.value,
            "to_zone": self.destination_zone.value,
            "to_index": self.destination_index,
            "position": self.position.value,
            "summoned": False,
        }

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 가 {self.card} 를 "
            f"{self.destination_zone.value}[{self.destination_index}] 에 "
            f"{self.position.value} 로 세트 (소환이 아니다)"
        )


#: 몬스터 세트 절차. 일반 소환과 **같은 배치 코드**를 표시 형식만 바꿔 쓴다.
#: ``summon=None`` 이 "이 배치는 소환이 아니다" 를 적는다 (RULE-SUMMON-010).
SET_MONSTER_PROCEDURE = SummonProcedure(
    kind=PlayerActionKind.SET_MONSTER,
    summon=None,
    from_zones=frozenset({SET_FROM_ZONE}),
    to_zone=Zone.MZONE,
    position=SET_MONSTER_POSITION,
    error=SetError,
)

#: 마법 · 함정 세트 절차. 가는 자리와 표시 형식만 다르다.
SET_SPELL_TRAP_PROCEDURE = SummonProcedure(
    kind=PlayerActionKind.SET_SPELL_TRAP,
    summon=None,
    from_zones=frozenset({SET_FROM_ZONE}),
    to_zone=Zone.SZONE,
    position=SET_SPELL_TRAP_POSITION,
    error=SetError,
)

#: 종류별 절차. **소환권을 쓰는 것은 몬스터 세트뿐이다** (RULE-SUMMON-009:
#: "You can only Normal Summon OR Normal Set once per turn" — 마법 · 함정
#: 세트는 이 제한에 들어가지 않는다).
_PROCEDURES: "dict[PlayerActionKind, tuple[SummonProcedure, bool]]" = {
    PlayerActionKind.SET_MONSTER: (SET_MONSTER_PROCEDURE, True),
    PlayerActionKind.SET_SPELL_TRAP: (SET_SPELL_TRAP_PROCEDURE, False),
}


class SetExecutor:
    """
    세트 하나를 수행한다. **상태를 갖지 않는다.**

        executor = SetExecutor()
        placement = executor.plan(state, action)   # 판을 바꾸지 않는다
        deltas = executor.apply(state, action)     # 여기서만 바뀐다

    ``NormalSummonExecutor`` · ``BattleExecutor`` 와 같은 모양이다 (plan/apply).
    """

    __slots__ = ()

    # ==================================================================
    # 계획 — 아무것도 바꾸지 않는다
    # ==================================================================
    def procedure(self, action: PlayerAction) -> SummonProcedure:
        entry = _PROCEDURES.get(action.kind)
        if entry is None:
            raise SetError(f"세트가 아닙니다: {action.kind.value}")
        return entry[0]

    def spends_summon_right(self, action: PlayerAction) -> bool:
        """
        이 세트가 **일반 소환권을 쓰는가** (RULE-SUMMON-009).

        몬스터 세트만 쓴다. 마법 · 함정 세트는 횟수 제한이 없다.
        """
        entry = _PROCEDURES.get(action.kind)
        if entry is None:
            raise SetError(f"세트가 아닙니다: {action.kind.value}")
        return entry[1]

    def plan(self, state: GameState, action: PlayerAction) -> SummonPlacement:
        """놓을 자리를 정한다. **판을 읽기만 한다.**"""
        return self.procedure(action).plan(state, action)

    # ==================================================================
    # 적용 — 여기서만 판이 바뀐다
    # ==================================================================
    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        """
        계획을 세우고 그대로 놓는다.

        **놓은 뒤에 소환권을 적는다.** 반대로 하면 배치가 실패했을 때 권리만
        사라진 판이 남는다 (``NormalSummonExecutor`` 와 같은 순서다).

        ``MonsterSummoned`` 를 만들지 않는다 (RULE-SUMMON-010).
        """
        procedure = self.procedure(action)
        placement = procedure.plan(state, action)

        procedure.place(state, placement)

        if self.spends_summon_right(action):
            # **같은 이름으로** 적는다 — 이름을 나누면 한 턴에 소환과 세트를
            # 둘 다 할 수 있게 된다 (RuleActionKind 의 기존 결정).
            state.rule_uses.record(
                state.turn.turn_number,
                placement.player,
                RuleActionKind.NORMAL_SUMMON,
            )
        elif action.kind is PlayerActionKind.SET_SPELL_TRAP:
            # **언제 세웠는가를 적는다** (Phase 3-E-15).
            #
            # 횟수를 세는 것이 아니다 — 마법 · 함정 세트에는 횟수 제한이
            # 없다. 적는 이유는 규칙이 **턴**을 묻기 때문이다.
            #
            #     RULE-SPELLTRAP-009 — "You cannot activate a Trap in the same
            #     turn that you Set it, but you can activate it at any time
            #     after that—starting from the beginning of the next turn."
            #     RULE-SPELLTRAP-007 — 세트한 속공 마법도 같다.
            #
            # **카드마다** 적는다. 플레이어별로 적으면 같은 턴에 두 장을 세운
            # 뒤 한 장만 발동한 상황에서 남은 장이 언제 세워졌는지 말할 수
            # 없다 (``RuleActionKind.SET_SPELL_TRAP`` 의 설명).
            #
            # 놓은 **뒤에** 적는 것은 위와 같은 이유다 — 배치가 실패하면
            # 기록만 남은 판이 된다.
            state.rule_uses.record_card(
                state.turn.turn_number,
                placement.player,
                placement.card,
                RuleActionKind.SET_SPELL_TRAP,
            )

        return (
            CardSet(
                card=placement.card,
                player=placement.player,
                owner=placement.owner,
                source_player=placement.from_player,
                source_zone=placement.from_zone,
                destination_zone=placement.to_zone,
                destination_index=placement.slot,
                position=placement.position,
            ),
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<SetExecutor>"


@dataclass(frozen=True, slots=True)
class SetMonsterHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    규칙도 절차도 갖지 않는다 — :class:`SetExecutor` 에게 넘기는 것이
    전부다 (``NormalSummonHandler`` · ``AttackHandler`` 와 같은 모양).
    """

    executor: SetExecutor = field(default_factory=SetExecutor)

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


@dataclass(frozen=True, slots=True)
class SetSpellTrapHandler:
    """마법 · 함정 세트의 껍데기. 같은 실행기를 쓴다."""

    executor: SetExecutor = field(default_factory=SetExecutor)

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


__all__ = [
    "SetError",
    "CardSet",
    "SetExecutor",
    "SetMonsterHandler",
    "SetSpellTrapHandler",
    "SET_FROM_ZONE",
    "SET_MONSTER_POSITION",
    "SET_SPELL_TRAP_POSITION",
    "SET_MONSTER_PROCEDURE",
    "SET_SPELL_TRAP_PROCEDURE",
]
