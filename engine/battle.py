"""
BattleExecutor — **ATTACK 하나를 실제 판 변화로 바꾸는 자리** (Phase 3-E-1-B).

    PlayerAction.attack(...)
          ↓  ActionExecutor (등록된 핸들러)
    AttackHandler → BattleExecutor
          ↓  공식 규칙으로 판정
    BattleOutcome
          ↓  기존 primitive 로 적용
    GameState.move() · PlayerState.change_life()
          ↓
    StateDelta (BattleDestruction · LifeChanged)

``action_execution`` 의 설명이 "앞으로 붙을 자리" 로 적어 둔 세 실행기 중
하나가 이것이다. 그 자리에 그대로 들어간다 — 새 실행 경로를 만들지 않는다.

완전한 전투 엔진이 **아니다**
-----------------------------
기본 전투만 한다. 관통 · 공격 무효 · 공격 대상 변경 · 공격력 변화 · 전투
데미지 대체 · 리플레이 · 데미지 스텝 체인 · 플립 효과는 **없다**. 그것들은
실제 카드 시나리오가 생길 때 단계적으로 붙인다.

여기서 하지 않는 것이 하나 더 있다 — **카드 효과를 읽지 않는다.** "이 카드가
공격할 때" 같은 것은 효과 계층과 트리거 계층의 일이고, 여기서 흉내 내면 두
경로가 갈린다.

공식 근거
---------
판정은 전부 ``rules`` 계층의 공식 룰북 조항에서 온다. 추측한 규칙이 하나도
없다는 것을 시험이 룰 ID 로 확인한다.

``RULE-BATTLE-002``   "Each face-up Attack Position monster you control is
                      allowed 1 attack per turn."
``RULE-BATTLE-010``   "If you attack an Attack Position monster, compare
                      ATK vs. ATK. If you attack a Defense Position
                      monster, compare your monster's ATK vs. the attacked
                      monster's DEF."
``RULE-BATTLE-011``   공격 표시 몬스터와의 전투 — 높으면 파괴 + 초과분 데미지,
                      같으면 **양쪽 파괴 · 데미지 없음**, 낮으면 공격자 파괴 +
                      초과분이 공격자 쪽 LP 에서.
``RULE-BATTLE-012``   수비 표시 몬스터와의 전투 — 높으면 파괴 · **데미지 없음**,
                      같거나 낮으면 **어느 쪽도 파괴되지 않음**. 낮으면 초과분이
                      공격자 쪽 LP 에서.
``RULE-BATTLE-013``   "If there are no monsters on your opponent's side of
                      the field, you can attack directly. The full amount
                      of your attacking monster's ATK is subtracted from the
                      opponent's LP as battle damage."
``RULE-BATTLE-014``   "Monsters with 0 ATK cannot destroy anything by
                      battle." 0 끼리 싸우면 어느 쪽도 파괴되지 않는다.

모르는 능력치를 숫자로 바꾸지 않는다
------------------------------------
공격력이 ``?`` 인 몬스터, 정의를 읽을 수 없는 카드가 전투에 들어오면
:class:`BattleError` 로 **멈춘다.** 0 으로 읽으면 "약하다" 가 거짓이 되고 큰
수로 읽으면 "강하다" 가 거짓이 된다 — 이 저장소가 다른 모든 자리에서 지켜
온 규칙과 같다. 멈추는 것은 숨기는 것보다 낫다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.action_target import ActionTargetKind
from engine.effect.delta import CardMovement, LifeChanged, StateDelta
from engine.effect.operation import OperationKind
from engine.ids import InstanceId
from engine.state.card_instance import CardInstance
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind
from engine.vocabulary import Position, Zone


class BattleError(RuntimeError):
    """
    전투를 진행할 수 없다. **적법성 판정이 아니다** — 그것은 이미 끝났고,
    여기서 걸리는 것은 허가와 판이 어긋났거나 **알 수 없는 능력치**라는 뜻이다.
    """


#: 파괴된 몬스터가 가는 곳. ``engine.effect.executor`` 의 파괴 목적지와 같다 —
#: "destroys the opponent's monster and **sends it to the Graveyard**"
#: (RULE-BATTLE-011).
DESTROYED_TO: Zone = Zone.GRAVE

#: 공격할 수 있는 표시 형식. "Each **face-up Attack Position** monster"
#: (RULE-BATTLE-002). 뒷면도, 수비 표시도 공격하지 않는다.
ATTACKING_POSITIONS: frozenset[Position] = frozenset({Position.FACEUP_ATTACK})

#: 전투의 상대가 **공격력으로** 싸우는 표시 형식 (RULE-BATTLE-010).
ATTACK_POSITIONS: frozenset[Position] = frozenset(
    {Position.FACEUP_ATTACK, Position.FACEDOWN_ATTACK, Position.ATTACK}
)

#: 몬스터 존들. 전투는 여기 있는 카드만 한다.
BATTLE_ZONES: tuple[Zone, ...] = (Zone.MZONE, Zone.EMZONE)


@dataclass(frozen=True, slots=True)
class BattleDestruction(CardMovement):
    """
    **전투로** 파괴되어 묘지로 갔다.

    ``ZoneMoved`` 를 쓰지 않고 따로 두는 이유는 **이유** 하나다.
    ``REASON_NAMES[DESTROY]`` 는 ``("DESTROY", "EFFECT")`` 인데, 전투 파괴는
    효과가 아니다. 그 표의 설명이 직접 적어 두었다 — "전투 · 비용으로 인한
    경우는 여기 없다 — 그것은 효과가 아니라 다른 경로이고, 그 경로가 생길 때
    함께 정한다." **이 Phase 가 그 경로다.**

    그래서 ``reason_names`` 가 ``("DESTROY", "BATTLE")`` 다. 이것을
    ``EFFECT`` 로 적으면 나중에 트리거 계층이 전투 파괴를 "효과로 파괴됐다"
    로 읽고, "효과로 파괴될 때" 를 조건으로 하는 카드가 잘못 발동한다.

    :class:`~engine.effect.delta.CardMovement` 를 상속하므로 "이번에 움직인
    카드" 를 세는 기존 코드가 **고치지 않고** 이것도 센다.
    """

    card: InstanceId
    owner: int
    source_zone: Zone
    destination_zone: Zone = DESTROYED_TO

    @property
    def kind(self) -> str:
        return "battle_destruction"

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def operation(self) -> OperationKind:
        """파괴다. **움직인 의미**는 효과 파괴와 같다 — 이유만 다르다."""
        return OperationKind.DESTROY

    @property
    def from_player(self) -> int:
        return self.owner

    @property
    def from_zone(self) -> Zone:
        return self.source_zone

    @property
    def to_player(self) -> int:
        return self.owner

    @property
    def to_zone(self) -> Zone:
        return self.destination_zone

    @property
    def reason_names(self) -> tuple[str, ...]:
        """**``EFFECT`` 가 아니다.** ``constant.lua`` 의 ``REASON_BATTLE``."""
        return ("DESTROY", "BATTLE")

    def canonical_state(self) -> tuple:
        return (
            "battle_destruction",
            self.card.value,
            self.owner,
            self.source_zone.value,
            self.destination_zone.value,
        )

    def to_dict(self) -> dict:
        return {
            "kind": "battle_destruction",
            "card": self.card.value,
            "owner": self.owner,
            "from_zone": self.source_zone.value,
            "to_zone": self.destination_zone.value,
            "reasons": list(self.reason_names),
        }

    def describe_ko(self) -> str:
        return f"{self.card} 가 전투로 파괴되어 {self.destination_zone.value} 로"


class BattleKind(str, Enum):
    """이 전투가 **무엇과의** 전투인가 (RULE-BATTLE-010)."""

    VERSUS_ATTACK = "versus_attack"
    """공격 표시 몬스터와 — 공격력끼리 견준다 (RULE-BATTLE-011)."""
    VERSUS_DEFENCE = "versus_defence"
    """수비 표시 몬스터와 — 공격력과 수비력을 견준다 (RULE-BATTLE-012)."""
    DIRECT = "direct"
    """상대 몬스터가 없다 — 공격력 전부가 LP 로 (RULE-BATTLE-013)."""


@dataclass(frozen=True, slots=True)
class BattleOutcome:
    """
    전투 하나의 **판정 결과**. 아직 아무것도 적용되지 않았다.

    판정과 적용을 나누는 이유는 이 저장소의 다른 모든 자리와 같다 —
    판정은 읽기만 하므로 시험하기 쉽고, 적용은 한 곳에 모인다.
    """

    kind: BattleKind
    rule_id: str
    """이 결과를 정한 **공식 조항**. 추측이 아니라는 증거다."""
    attacker: InstanceId
    target: "InstanceId | None"
    attacker_value: int
    target_value: int
    """상대가 싸운 수치 — 공격 표시면 공격력, 수비 표시면 수비력."""
    damage_to: "int | None" = None
    damage: int = 0
    destroy_attacker: bool = False
    destroy_target: bool = False

    def __post_init__(self) -> None:
        if self.damage < 0:
            raise BattleError(f"데미지는 음수가 될 수 없습니다: {self.damage}")
        if self.damage and self.damage_to is None:
            raise BattleError("데미지를 받을 사람이 없습니다.")
        if self.damage_to is not None and self.damage_to not in (0, 1):
            raise BattleError(f"데미지를 받는 자리는 0 또는 1 입니다: {self.damage_to}")

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        bits = [f"{self.kind.value}({self.rule_id})"]
        if self.destroy_target:
            bits.append("대상 파괴")
        if self.destroy_attacker:
            bits.append("공격자 파괴")
        if self.damage:
            bits.append(f"P{self.damage_to} 에게 {self.damage} 데미지")
        if not self.destroy_target and not self.destroy_attacker and not self.damage:
            bits.append("아무 일도 없음")
        return " · ".join(bits)


def _monster(state: GameState, instance_id: InstanceId) -> CardInstance:
    card = state.find_instance(instance_id)
    if card is None:
        raise BattleError(f"{instance_id} 를 찾을 수 없습니다.")
    if card.zone not in BATTLE_ZONES:
        raise BattleError(f"{instance_id} 는 몬스터 존에 없습니다: {card.zone.value}")
    return card


def _printed(card: CardInstance, which: str) -> int:
    """
    인쇄된 공격력 · 수비력. **모르면 멈춘다.**

    ``?`` 는 ``-2`` 로 들어온다 (공식 DB). 그것을 0 으로 읽으면 가장 약한
    몬스터가 되고 큰 수로 읽으면 가장 강한 몬스터가 된다 — 둘 다 거짓이다.
    공격력을 바꾸는 효과 계층이 생기기 전까지는 **멈추는 것이 정직하다.**
    """
    if card.repository is None:
        raise BattleError(
            f"{card.instance_id} 의 카드 정의를 읽을 수 없어 전투를 판정할 수 "
            "없습니다 (저장소 없음). 추측하지 않고 멈춥니다."
        )
    definition = card.definition
    value = getattr(definition, which)
    if value < 0:
        raise BattleError(
            f"{card.instance_id} 의 {which} 가 '?' 입니다 ({value}). 숫자로 "
            "바꾸지 않고 멈춥니다 — 공격력 변화 계층이 생길 때 다시 봅니다."
        )
    return value


class BattleExecutor:
    """
    기본 전투 하나를 판정하고 적용한다. **상태를 갖지 않는다.**

        executor = BattleExecutor()
        outcome = executor.judge(state, action)   # 판을 바꾸지 않는다
        deltas = executor.apply(state, action)    # 여기서만 바뀐다

    ``NormalSummonExecutor`` 와 같은 모양이다 (plan/apply) — 이 저장소가
    실행기를 쓰는 방식 그대로다.
    """

    __slots__ = ()

    # ==================================================================
    # 판정 — 아무것도 바꾸지 않는다
    # ==================================================================
    def judge(self, state: GameState, action: PlayerAction) -> BattleOutcome:
        """
        공식 조항대로 전투 결과를 정한다. **판을 읽기만 한다.**
        """
        if action.kind is not PlayerActionKind.ATTACK:
            raise BattleError(f"공격이 아닙니다: {action.kind.value}")
        if action.source is None:
            raise BattleError("공격자가 없습니다.")

        attacker = _monster(state, action.source)
        if attacker.position not in ATTACKING_POSITIONS:
            # 적법성은 검증기가 이미 봤다. 여기까지 왔다면 판이 어긋난 것이다.
            raise BattleError(
                f"{action.source} 는 앞면 공격 표시가 아닙니다 "
                f"({attacker.position.value}) — RULE-BATTLE-002"
            )
        attack = _printed(attacker, "atk")
        target = action.target

        # ── 다이렉트 어택 (RULE-BATTLE-013)
        if target is not None and target.kind is ActionTargetKind.PLAYER:
            return BattleOutcome(
                kind=BattleKind.DIRECT,
                rule_id="RULE-BATTLE-013",
                attacker=attacker.instance_id,
                target=None,
                attacker_value=attack,
                target_value=0,
                damage_to=target.player,
                damage=attack,
            )

        if target is None or target.kind is not ActionTargetKind.INSTANCE:
            raise BattleError(
                "공격 대상이 몬스터도 플레이어도 아닙니다 — 대상 없는 공격은 "
                "구조 오류입니다 (engine.action 설명)."
            )

        defender = _monster(state, target.instance_id)
        attacker_side = attacker.controller
        defender_side = defender.controller

        # ── 공격 표시 몬스터와 (RULE-BATTLE-011)
        if defender.position in ATTACK_POSITIONS:
            defence = _printed(defender, "atk")
            if attack > defence:
                # "Monsters with 0 ATK cannot destroy anything by battle"
                # (RULE-BATTLE-014) — 0 은 여기 올 수 없다 (0 > x 가 거짓).
                return BattleOutcome(
                    BattleKind.VERSUS_ATTACK, "RULE-BATTLE-011",
                    attacker.instance_id, defender.instance_id, attack, defence,
                    damage_to=defender_side, damage=attack - defence,
                    destroy_target=True,
                )
            if attack == defence:
                # 같으면 **양쪽 파괴, 데미지 없음.** 단 0 끼리는 아무 일도
                # 없다 (RULE-BATTLE-014).
                if attack == 0:
                    return BattleOutcome(
                        BattleKind.VERSUS_ATTACK, "RULE-BATTLE-014",
                        attacker.instance_id, defender.instance_id, 0, 0,
                    )
                return BattleOutcome(
                    BattleKind.VERSUS_ATTACK, "RULE-BATTLE-011",
                    attacker.instance_id, defender.instance_id, attack, defence,
                    destroy_attacker=True, destroy_target=True,
                )
            return BattleOutcome(
                BattleKind.VERSUS_ATTACK, "RULE-BATTLE-011",
                attacker.instance_id, defender.instance_id, attack, defence,
                damage_to=attacker_side, damage=defence - attack,
                destroy_attacker=True,
            )

        # ── 수비 표시 몬스터와 (RULE-BATTLE-012)
        defence = _printed(defender, "defense")
        if attack > defence:
            # 파괴하되 **데미지는 없다** — 관통은 구현하지 않았다 (§14).
            return BattleOutcome(
                BattleKind.VERSUS_DEFENCE, "RULE-BATTLE-012",
                attacker.instance_id, defender.instance_id, attack, defence,
                destroy_target=True,
            )
        if attack == defence:
            # "neither monster is destroyed" — 아무 일도 없다.
            return BattleOutcome(
                BattleKind.VERSUS_DEFENCE, "RULE-BATTLE-012",
                attacker.instance_id, defender.instance_id, attack, defence,
            )
        return BattleOutcome(
            BattleKind.VERSUS_DEFENCE, "RULE-BATTLE-012",
            attacker.instance_id, defender.instance_id, attack, defence,
            damage_to=attacker_side, damage=defence - attack,
        )

    # ==================================================================
    # 적용 — 여기서만 판이 바뀐다
    # ==================================================================
    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        """
        판정하고 그대로 적용한다. **기존 primitive 만 쓴다.**

        LP 는 :meth:`~engine.state.player.PlayerState.change_life`, 이동은
        :meth:`~engine.state.game_state.GameState.move` 다 — 여기서 숫자를
        직접 건드리는 지름길을 만들지 않는다.

        **공격권을 먼저 적는다.** 파괴·데미지가 중간에 멈춰도 "공격은
        선언되었다" 는 사실은 남아야 하기 때문이다 — 공격 선언은
        데미지 스텝보다 앞이다 (RULE-BATTLE-002 · 003).
        """
        outcome = self.judge(state, action)
        deltas: list[StateDelta] = []

        state.rule_uses.record_card(
            state.turn.turn_number,
            action.actor,
            outcome.attacker,
            RuleActionKind.ATTACK,
        )

        if outcome.damage and outcome.damage_to is not None:
            player = state.player(outcome.damage_to)
            before = player.life_points
            after = player.change_life(-outcome.damage)
            deltas.append(
                LifeChanged(player=outcome.damage_to, before=before, after=after)
            )

        # 파괴는 **공격자 · 대상 순서**로 적는다. 동시 파괴를 하나의 사실로
        # 묶지 않는 이유는 트리거 계층이 아직 없기 때문이다 — 순서를 정해
        # 두면 나중에 SEGOC 를 붙일 때 바꿀 자리가 분명하다.
        for destroy, instance_id in (
            (outcome.destroy_attacker, outcome.attacker),
            (outcome.destroy_target, outcome.target),
        ):
            if not destroy or instance_id is None:
                continue
            card = _monster(state, instance_id)
            source_zone = card.zone
            owner = card.controller
            state.move(card, DESTROYED_TO, to_player=owner)
            deltas.append(
                BattleDestruction(
                    card=instance_id, owner=owner, source_zone=source_zone
                )
            )
        return tuple(deltas)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<BattleExecutor>"


@dataclass(frozen=True, slots=True)
class AttackHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    규칙도 절차도 갖지 않는다 — :class:`BattleExecutor` 에게 넘기는 것이
    전부다. ``NormalSummonHandler`` 와 같은 모양이다.
    """

    executor: BattleExecutor = BattleExecutor()

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


__all__ = [
    "BattleError",
    "BattleKind",
    "BattleOutcome",
    "BattleDestruction",
    "BattleExecutor",
    "AttackHandler",
    "DESTROYED_TO",
    "ATTACKING_POSITIONS",
    "ATTACK_POSITIONS",
    "BATTLE_ZONES",
]
