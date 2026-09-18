"""
일반 소환의 **실행** — 패의 몬스터를 몬스터 존에 앞면 공격 표시로 놓는다.

    PlayerAction(NORMAL_SUMMON)
        ↓  ActionValidator          해도 되는가 (여기서 VALID 가 난다)
        ↓  ActionExecutor           허가된 것만 넘긴다
        ↓  NormalSummonHandler      ← 이 파일
        ↓  NormalSummonExecutor     계획 → 적용 → 확인
    GameState 변경  +  MonsterSummoned

공식 규칙 (RULE-SUMMON-009)
---------------------------
"Simply play a Monster Card from your hand onto the field in face-up Attack
Position." — 패에서, 앞면 공격 표시로, 1턴에 한 번.

효과가 아니다
-------------
일반 소환은 **규칙에 따른 플레이어의 행위**이지 카드 효과의 해결이 아니다
(ADR-001 의 Action ≠ Effect). 그래서 :class:`
~engine.effect.executor.EffectExecutor` 를 부르지 않고,
:class:`~engine.effect.operation.OperationKind` 어휘도 쓰지 않는다.

적법성을 다시 판정하지 않는다
------------------------------
이 실행기는 "해도 되는가" 를 묻지 않는다. 페이즈 · 턴 플레이어 · 카드
종류 · 소환권 · 제물 필요 여부는 전부
:class:`~engine.action_validation.ActionValidator` 가 이미 판정했고, 같은
판정을 두 곳에 두면 둘이 갈린다.

여기서 확인하는 것은 **"지시를 수행할 수 있는가"** 뿐이다 — 그 카드가
있는가, 패에 있는가, 놓을 칸이 있는가. 하나라도 아니면 **판에 손대기 전에**
:class:`NormalSummonError` 로 멈춘다.

여기서 하지 않는 것
-------------------
제물 소환 · 세트 · 특수 소환 · 반전 소환 · 표시 형식 선택 · 소환 무효 ·
"소환 성공 시" 유발 효과의 수집 · 체인 · 우선권. 소환이 일어났다는 사실은
:class:`~engine.effect.delta.MonsterSummoned` 하나로 남기고, 그것을 사건으로
읽을지는 부르는 쪽이 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor
from engine.effect.delta import MonsterSummoned, StateDelta, SummonKind
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.state.rule_usage import RuleActionKind, RuleUsageRegistry
from engine.vocabulary import Position, Zone

#: 일반 소환이 나오는 자리 (RULE-SUMMON-009).
SUMMON_FROM_ZONE: Zone = Zone.HAND

#: 일반 소환이 놓이는 자리. 엑스트라 몬스터 존은 특수 소환의 자리다.
SUMMON_TO_ZONE: Zone = Zone.MZONE

#: 일반 소환의 표시 형식. **고를 수 없다** — 세트는 다른 행위다.
SUMMON_POSITION: Position = Position.FACEUP_ATTACK


class NormalSummonError(RuntimeError):
    """지시를 수행할 수 없다. **판에 손대기 전에** 던진다."""


@dataclass(frozen=True, slots=True)
class NormalSummonPlan:
    """
    무엇을 어디에 놓을 것인가. **아직 아무것도 놓지 않았다.**

    계획이 만들어졌다는 것은 "이 지시를 끝까지 수행할 수 있다" 는 뜻이다 —
    칸도 정해졌고, 사용권을 적을 키도 이미 만들어 두었다. 그래서 적용
    도중에 멈출 일이 없다.
    """

    card: InstanceId
    player: int
    """소환하는 사람. 놓인 몬스터의 컨트롤러가 된다."""
    owner: int
    """카드의 주인. 소환한다고 주인이 바뀌지 않는다."""
    slot: int
    usage_key: tuple
    """사용권을 적을 자리. 미리 만들어 두면 적을 때 실패하지 않는다."""

    def to_delta(self) -> MonsterSummoned:
        return MonsterSummoned(
            summon=SummonKind.NORMAL,
            card=self.card,
            player=self.player,
            owner=self.owner,
            from_zone=SUMMON_FROM_ZONE,
            to_zone=SUMMON_TO_ZONE,
            to_index=self.slot,
            position=SUMMON_POSITION,
        )

    def describe_ko(self) -> str:
        return f"P{self.player} 가 {self.card} 를 MZONE[{self.slot}] 에 일반 소환"


class NormalSummonExecutor:
    """
    일반 소환 하나를 수행한다. **상태를 갖지 않는다.**

        executor = NormalSummonExecutor()
        plan = executor.plan(state, action)     # 판을 바꾸지 않는다
        deltas = executor.apply(state, action)  # 여기서만 바뀐다
    """

    __slots__ = ()

    # ==================================================================
    # 계획 — 아무것도 바꾸지 않는다
    # ==================================================================
    def plan(self, state: GameState, action: PlayerAction) -> NormalSummonPlan:
        """
        지시를 수행할 수 있는지 보고 계획을 만든다.

        수행할 수 없으면 :class:`NormalSummonError` 다. **적법성 판정이
        아니다** — 그것은 이미 끝났고, 여기서 걸리는 것은 허가와 판이
        어긋났다는 뜻이다.
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "NormalSummonExecutor 는 GameState 를 받습니다. "
                "관측(GameStateView)은 읽기 전용이라 소환할 수 없습니다."
            )
        if action.kind is not PlayerActionKind.NORMAL_SUMMON:
            raise NormalSummonError(
                f"{action.kind.value} 는 일반 소환이 아닙니다."
            )
        if action.source is None:
            raise NormalSummonError("소환할 카드가 지목되지 않았습니다.")

        card = state.find_instance(action.source)
        if card is None:
            raise NormalSummonError(f"{action.source} 를 이 판에서 찾을 수 없습니다.")
        if card.controller != action.actor:
            raise NormalSummonError(
                f"{action.source} 는 P{card.controller} 의 카드입니다 "
                f"(P{action.actor} 가 소환하려 했습니다)."
            )

        source_zone = state.locate(action.source)
        if source_zone is None or source_zone.zone is not SUMMON_FROM_ZONE:
            where = source_zone.zone.value if source_zone else "어디에도"
            raise NormalSummonError(
                f"{action.source} 는 패에 없습니다 ({where})."
            )

        free = state.zone(action.actor, SUMMON_TO_ZONE).free_slots()
        if not free:
            raise NormalSummonError("몬스터 존에 빈 칸이 없습니다.")

        return NormalSummonPlan(
            card=action.source,
            player=action.actor,
            owner=card.owner,
            slot=free[0],
            # 지금 만들어 둔다. 적용 중에 키가 잘못되어 멈추는 일이 없도록.
            usage_key=RuleUsageRegistry.key(
                state.turn.turn_number, action.actor, RuleActionKind.NORMAL_SUMMON
            ),
        )

    # ==================================================================
    # 적용 — 여기서만 판이 바뀐다
    # ==================================================================
    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        """
        계획을 세우고 그대로 적용한다.

        **옮긴 뒤에 소환권을 적는다.** 반대로 하면 이동이 실패했을 때
        권리만 사라진 판이 남는다. 이동은 계획이 보장하므로 실패하지 않지만,
        순서로도 막아 둔다.
        """
        plan = self.plan(state, action)

        state.move(
            plan.card,
            SUMMON_TO_ZONE,
            to_player=plan.player,
            index=plan.slot,
            position=SUMMON_POSITION,
        )
        self._verify(state, plan)
        state.rule_uses.record(
            state.turn.turn_number, plan.player, RuleActionKind.NORMAL_SUMMON
        )
        return (plan.to_delta(),)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _verify(self, state: GameState, plan: NormalSummonPlan) -> None:
        """
        계획한 자리에 놓였는가. 어긋나면 기록을 남기지 않고 멈춘다.

        같은 카드가 두 존에 동시에 있는 상태는 ``ZoneContainer`` 가 이미
        막지만 (``place`` 가 거부한다), 그래도 **떠났는지**를 함께 본다 —
        틀린 기록은 없는 것보다 나쁘다.
        """
        landed = state.zone(plan.player, SUMMON_TO_ZONE)
        card = state.find_instance(plan.card)
        if card is None or landed.slot(plan.slot) is not card:
            raise NormalSummonError(
                f"{plan.card} 가 MZONE[{plan.slot}] 에 없습니다."
            )
        if card.position is not SUMMON_POSITION:
            raise NormalSummonError(
                f"{plan.card} 의 표시 형식이 {card.position} 입니다."
            )
        if card in state.zone(plan.player, SUMMON_FROM_ZONE):
            raise NormalSummonError(f"{plan.card} 가 아직 패에 남아 있습니다.")

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<NormalSummonExecutor>"


@dataclass(frozen=True, slots=True)
class NormalSummonHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    규칙도 절차도 갖지 않는다. :class:`NormalSummonExecutor` 에게 넘기는
    것이 전부이고, 그래서 ``ActionExecutor`` 에 소환 지식이 한 줄도 들어가지
    않는다. ``SpecialSummonHandler`` · ``AttackHandler`` 도 같은 모양으로
    붙는다.
    """

    executor: NormalSummonExecutor = field(default_factory=NormalSummonExecutor)

    def apply(
        self, state: GameState, action: PlayerAction
    ) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


def summoning_executor() -> ActionExecutor:
    """
    일반 소환을 **아는** 실행기를 만든다.

    기본 :class:`~engine.action_execution.ActionExecutor` 는 여전히 빈 채로
    둔다 (ADR-006: 등록하지 않은 것은 실행되지 않는다). 소환을 실행하려는
    쪽이 이 함수를 부르거나 직접 등록한다.
    """
    return ActionExecutor().register(
        PlayerActionKind.NORMAL_SUMMON, NormalSummonHandler()
    )


__all__ = [
    "SUMMON_FROM_ZONE",
    "SUMMON_TO_ZONE",
    "SUMMON_POSITION",
    "NormalSummonError",
    "NormalSummonPlan",
    "NormalSummonExecutor",
    "NormalSummonHandler",
    "summoning_executor",
]
