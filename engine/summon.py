"""
소환의 **공통 절차** — 어느 자리에서 꺼내 어느 칸에 놓는가.

    PlayerAction(NORMAL_SUMMON | SPECIAL_SUMMON)
        ↓  SummonProcedure.plan()      판을 읽기만 한다
    SummonPlacement                    무엇을 · 어디에 · 어떤 표시로
        ↓  SummonProcedure.place()     **여기서만 판이 바뀐다**
    GameState  +  MonsterSummoned

일반 소환과 특수 소환이 **같은 코드를 쓴다**
--------------------------------------------
자리 찾기 · 컨트롤러 확인 · 빈 칸 찾기 · 이동 · 착지 확인은 둘이 똑같다.
복사해서 두 벌을 만들면 한쪽만 고쳐지는 날이 온다. 그래서 다른 것만
:class:`SummonProcedure` 의 **값**으로 적는다.

    =====================  ==================  ========================
                            일반 소환            특수 소환
    =====================  ==================  ========================
    ``from_zones``          ``{HAND}``          ``{HAND, GRAVE}``
    ``summon``              ``NORMAL``          ``SPECIAL``
    소환권                   **쓴다**            **쓰지 않는다**
    =====================  ==================  ========================

마지막 줄은 이 파일에 없다. 소환권을 적는 것은 일반 소환만의 일이므로
:mod:`engine.normal_summon` 이 자기 쪽에서 한다 — 공통 절차가 "쓸 수도
있고 안 쓸 수도 있는" 칸을 갖게 하면, 언젠가 특수 소환이 조용히 소환권을
먹는다.

적법성을 판정하지 않는다
------------------------
"이 카드를 소환해도 되는가" 는
:class:`~engine.action_validation.ActionValidator` 의 질문이다. 여기서
확인하는 것은 **"지시를 수행할 수 있는가"** 뿐이고, 하나라도 아니면 판에
손대기 전에 :class:`SummonError` 로 멈춘다.

효과가 아니다
-------------
소환은 규칙에 따른 플레이어의 행위이지 카드 효과의 해결이 아니다
(ADR-001). 그래서 :class:`~engine.effect.executor.EffectExecutor` 도
``OperationKind`` 어휘도 쓰지 않고, 사건은
:class:`~engine.effect.delta.MonsterSummoned` 하나로 남긴다.

체인을 만들지 않는다
--------------------
소환이 트리거를 불러오는 것은 사실이지만, 그것을 여기서 수집하지 않는다.
``MonsterSummoned`` 를 사건으로 읽고 트리거를 모으는 것은
:class:`~engine.event_pipeline.EventReader` 와 Phase 2-F 계층의 일이다 —
이 파일에는 ``TriggerCollector`` 도 ``Chain`` 도 ``ChainResolver`` 도 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor
from engine.effect.delta import MonsterSummoned, SummonKind
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Position, Zone


class SummonError(RuntimeError):
    """
    지시를 수행할 수 없다. **판에 손대기 전에** 던진다.

    적법성 위반이 아니다 — 그것은 검증기가 이미 거절했다. 여기까지 왔는데
    걸린다면 **허가와 판이 어긋났다**는 뜻이다.
    """


@dataclass(frozen=True, slots=True)
class SummonPlacement:
    """
    무엇을 어디에 놓을 것인가. **아직 아무것도 놓지 않았다.**

    계획이 만들어졌다는 것은 "이 지시를 끝까지 수행할 수 있다" 는 뜻이다 —
    칸도 정해졌으므로 적용 도중에 멈출 일이 없다.
    """

    card: InstanceId
    player: int
    """소환하는 사람. 놓인 몬스터의 컨트롤러가 된다."""
    owner: int
    """카드의 주인. **소환한다고 주인이 바뀌지 않는다** (ADR: Owner ≠ Controller)."""
    from_zone: Zone
    to_zone: Zone
    slot: int
    position: Position

    def to_delta(self, summon: SummonKind) -> MonsterSummoned:
        """
        이 배치가 만든 변화.

        **어떤 소환인가는 밖에서 온다.** 배치는 "어디서 어디로" 만 알고,
        "일반인가 특수인가" 는 절차가 말한다 — 둘을 한 값에 섞으면 같은
        배치가 두 의미를 주장하게 된다.
        """
        return MonsterSummoned(
            summon=summon,
            card=self.card,
            player=self.player,
            owner=self.owner,
            from_zone=self.from_zone,
            to_zone=self.to_zone,
            to_index=self.slot,
            position=self.position,
        )

    def canonical_state(self) -> tuple:
        return (
            self.card.value,
            self.player,
            self.owner,
            self.from_zone.value,
            self.to_zone.value,
            self.slot,
            self.position.value,
        )

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 가 {self.card} 를 {self.from_zone.value} 에서 "
            f"{self.to_zone.value}[{self.slot}] 로"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class SummonProcedure:
    """
    한 가지 소환법의 **표**. 절차가 아니라 값이다.

    ``error`` 를 받는 이유는 부르는 쪽이 자기 이름의 예외를 던지기
    위해서다 — ``NormalSummonError`` 를 잡던 코드가 그대로 동작해야 한다.
    """

    kind: PlayerActionKind
    """이 절차가 수행하는 행위."""
    summon: SummonKind
    """만들어질 :class:`~engine.effect.delta.MonsterSummoned` 의 의미."""
    from_zones: frozenset[Zone]
    """
    **지원하는** 출발 자리. 여기 없는 자리는 "규칙상 안 된다" 가 아니라
    **"아직 옮기지 못했다"** 이고, 그 구분은 검증기가 말한다.
    """
    to_zone: Zone
    position: Position
    """
    놓이는 표시 형식. **고를 수 없다** (STRUCTURAL-61).

    실제 특수 소환은 앞면 공격 · 앞면 수비를 고를 수 있지만, 표시 형식을
    고르는 계층이 아직 없다. 지금 고정한 값이 규칙이라고 주장하지 않는다.
    """
    error: type[SummonError] = SummonError

    def __post_init__(self) -> None:
        if not isinstance(self.from_zones, frozenset) or not self.from_zones:
            raise ValueError("출발 자리가 최소 하나 필요합니다 (frozenset).")
        if self.to_zone in self.from_zones:
            raise ValueError(
                f"소환은 다른 자리로 나오는 것입니다: {self.to_zone.value}"
            )

    # ==================================================================
    # 계획 — 아무것도 바꾸지 않는다
    # ==================================================================
    def plan(self, state: GameState, action: PlayerAction) -> SummonPlacement:
        """
        지시를 수행할 수 있는지 보고 배치를 정한다.

        **칸을 고르지 않는다** — 가장 작은 빈 칸을 쓴다 (STRUCTURAL-41).
        그것이 규칙이어서가 아니라 고르는 계층이 아직 없어서이고, 일반
        소환이 쓰던 방식을 그대로 쓴다.
        """
        if not isinstance(state, GameState):
            raise TypeError(
                f"{type(self).__name__} 는 GameState 를 받습니다. "
                "관측(GameStateView)은 읽기 전용이라 소환할 수 없습니다."
            )
        if action.kind is not self.kind:
            raise self.error(
                f"{action.kind.value} 는 {self.kind.value} 가 아닙니다."
            )
        if action.source is None:
            raise self.error("소환할 카드가 지목되지 않았습니다.")

        card = state.find_instance(action.source)
        if card is None:
            raise self.error(f"{action.source} 를 이 판에서 찾을 수 없습니다.")
        if card.controller != action.actor:
            raise self.error(
                f"{action.source} 는 P{card.controller} 의 카드입니다 "
                f"(P{action.actor} 가 소환하려 했습니다)."
            )

        located = state.locate(action.source)
        if located is None or located.zone not in self.from_zones:
            where = located.zone.value if located else "어디에도"
            allowed = " · ".join(sorted(z.value for z in self.from_zones))
            raise self.error(
                f"{action.source} 가 {allowed} 에 없습니다 (현재 {where})."
            )

        free = state.zone(action.actor, self.to_zone).free_slots()
        if not free:
            raise self.error(f"{self.to_zone.value} 에 빈 칸이 없습니다.")

        return SummonPlacement(
            card=action.source,
            player=action.actor,
            owner=card.owner,
            from_zone=located.zone,
            to_zone=self.to_zone,
            slot=free[0],
            position=self.position,
        )

    # ==================================================================
    # 적용 — 여기서만 판이 바뀐다
    # ==================================================================
    def place(self, state: GameState, placement: SummonPlacement) -> None:
        """배치를 그대로 옮기고 착지를 확인한다."""
        state.move(
            placement.card,
            placement.to_zone,
            to_player=placement.player,
            index=placement.slot,
            position=placement.position,
        )
        self.verify(state, placement)

    def verify(self, state: GameState, placement: SummonPlacement) -> None:
        """
        계획한 자리에 놓였는가. 어긋나면 **기록을 남기지 않고** 멈춘다.

        떠났는지도 함께 본다 — 틀린 기록은 없는 것보다 나쁘다.
        """
        landed = state.zone(placement.player, placement.to_zone)
        card = state.find_instance(placement.card)
        if card is None or landed.slot(placement.slot) is not card:
            raise self.error(
                f"{placement.card} 가 {placement.to_zone.value}"
                f"[{placement.slot}] 에 없습니다."
            )
        if card.position is not placement.position:
            raise self.error(
                f"{placement.card} 의 표시 형식이 {card.position} 입니다."
            )
        if card in state.zone(placement.player, placement.from_zone):
            raise self.error(
                f"{placement.card} 가 아직 {placement.from_zone.value} 에 "
                "남아 있습니다."
            )

    def describe_ko(self) -> str:
        allowed = " · ".join(sorted(z.value for z in self.from_zones))
        return f"{self.kind.value}: {allowed} → {self.to_zone.value}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def summon_executor() -> ActionExecutor:
    """
    일반 소환과 특수 소환을 **둘 다** 아는 실행기.

    기본 :class:`~engine.action_execution.ActionExecutor` 는 여전히 빈 채로
    둔다 (ADR-006: 등록하지 않은 것은 실행되지 않는다). 한쪽만 필요하면
    :func:`~engine.normal_summon.summoning_executor` 또는
    :func:`~engine.special_summon.special_summoning_executor` 를 쓴다.
    """
    from engine.normal_summon import NormalSummonHandler
    from engine.special_summon import SpecialSummonHandler

    return (
        ActionExecutor()
        .register(PlayerActionKind.NORMAL_SUMMON, NormalSummonHandler())
        .register(PlayerActionKind.SPECIAL_SUMMON, SpecialSummonHandler())
    )


__all__ = [
    "SummonError",
    "SummonPlacement",
    "SummonProcedure",
    "summon_executor",
]
