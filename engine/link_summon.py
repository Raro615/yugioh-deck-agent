"""
링크 소환의 **절차** — 소재를 골라 묘지로 보내고 엑스트라 덱에서 꺼낸다.

    PlayerAction(LINK_SUMMON, source=링크 몬스터, materials=(…))
        ↓  ActionValidator             해도 되는가 (소재 조건을 **읽은** 카드만)
        ↓  ActionExecutor              허가된 것만 넘긴다
        ↓  LinkSummonHandler           ← 이 파일
        ↓  ① 소재를 묘지로              ZoneMoved(send_to_grave) × N
        ↓  ② SummonProcedure           엑스트라 덱 → 엑스트라 몬스터 존
    GameState 변경  +  MonsterSummoned(summon=LINK)
        ↓  EventReader                 (부르는 쪽이 읽는다)
    TimingEvent(MONSTER_SUMMONED · CARD_MOVED) → TriggerCandidate

순서가 규칙이다
---------------
소재가 **먼저** 필드를 떠난다. 공식 절차가 그 순서로 적혀 있고
(링크 소재는 소환에 **앞서** 묘지로 보내진다), 그 순서가 아니면 소재가
차지하고 있던 메인 몬스터 존이 비지 않는다. 이 파일은 그래서 두 걸음을
**한 지시** 안에서 하고, **판에 손대기 전에** 둘 다 계획한다.

무엇을 지원하는가 — 범위를 좁게 적는다
--------------------------------------
"장수와 링크 수치만 맞으면 통과" 가 **아니다.** 통과하는 것은 아래 전부가
확인된 경우뿐이다.

1. ``source`` 가 **자신 엑스트라 덱의 링크 몬스터**다.
2. 그 카드의 소재 조건이 :data:`LINK_MATERIAL_RULES` 에 **손으로 적혀**
   있다. 적히지 않은 링크 몬스터는 ``UNKNOWN`` 이고, 그 사실을
   :data:`LINK_MATERIAL_RULE_MISSING` 이 말한다 — 모르는 것을 허가로 바꾸지
   않는다 (ADR-006).
3. 고른 소재가 **자신 필드의 앞면 몬스터**다 (``MZONE`` · ``EMZONE``).
4. 소재 **장수**가 그 규칙이 적은 수와 같다.
5. 소재 **하나하나**가 그 규칙의 ``each`` 를 만족한다.
6. 그 규칙이 ``includes`` 를 적었으면 소재 중 **적어도 하나**가 그것을
   만족한다.
7. 놓을 자리가 있다 — :data:`LINK_SUMMON_TO_ZONE` 의 빈 칸.

무엇을 지원하지 **않는가**
--------------------------
아래는 전부 ``UNKNOWN`` 으로 거절되고, 각자 자기 이름이 있다. 이름이 있어야
"규칙이 막았다" 와 "이 저장소에 그 규칙이 없다" 가 갈린다 (Phase 6-AB 보완6).

=========================================  ==================================
링크 몬스터를 소재로 쓰기                    :data:`LINK_MATERIAL_AS_LINK_RULE`
가리키는 메인 몬스터 존에 놓기               :data:`LINK_PLACEMENT_LINKED_RULE`
「링크 소재로 할 수 없다」 제약               :data:`LINK_MATERIAL_BAN_RULE`
소재 조건을 적지 않은 링크 몬스터             :data:`LINK_MATERIAL_RULE_MISSING`
=========================================  ==================================

🔴 세 번째가 **언제나** 확인되지 않는다. 지속 효과 계층이 없으므로
(STRUCTURAL-76) 「이 카드는 링크 소재로 할 수 없다」 를 읽을 자리가 판 어디에도
없다. 그래서 그것은 판정을 ``UNKNOWN`` 으로 만들지 **않고** —— 그러면 어떤
링크 소환도 못 한다 —— :attr:`LinkMaterialAssessment.unchecked` 에 **못 본
것으로** 남는다 (:meth:`~engine.effect.ruling.BoardRuling._blind_spots` 와 같은
자리). 판정을 바꾸지 않는 관찰과 판정을 막는 모름은 다른 사실이다.

적법성을 두 벌로 적지 않는다 — **다른 파일에 있다**
----------------------------------------------------
판정은 :func:`~engine.link_rules.assess_link_materials` 하나가 한다. 검증기
(:mod:`engine.action_validation`)와 후보 생성기(:mod:`engine.duel`)가 **같은
함수**를 부르고, 실행기는 판정하지 않는다 — 허가와 판이 어긋나면
:class:`LinkSummonError` 로 **판에 손대기 전에** 멈춘다.

🔴 그 함수가 :mod:`engine.link_rules` 에 있는 이유는 import 고리다 — 그
모듈의 머리말이 실측한 ``ImportError`` 를 적는다. 여기서는 그 모듈이 적어 둔
범위와 이름을 **그대로 읽어** 쓴다 (값을 다시 적지 않는다).

효과가 아니다
-------------
링크 소환은 규칙에 따른 플레이어의 행위이지 카드 효과의 해결이 아니다
(ADR-001). 그래서 :class:`~engine.effect.executor.EffectExecutor` 도
체인도 여기 없다 — ``MonsterSummoned`` 와 ``ZoneMoved`` 를 남기고, 그것을
사건으로 읽을지는 부르는 쪽이 정한다 (:mod:`engine.special_summon` 과 같은
규율).
"""

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.effect.delta import StateDelta, SummonKind, ZoneMoved
from engine.effect.operation import OperationKind
from engine.ids import InstanceId
from engine.link_rules import (
    LINK_MATERIAL_DESTINATION,
    LINK_MATERIAL_ZONES,
    LINK_SUMMON_FROM_ZONES,
    LINK_SUMMON_POSITION,
    LINK_SUMMON_TO_ZONE,
)
from engine.summon import SummonError, SummonPlacement, SummonProcedure
from engine.vocabulary import Zone


class LinkSummonError(SummonError):
    """지시를 수행할 수 없다. **판에 손대기 전에** 던진다."""


#: 소재가 묘지로 가는 **의미**. 「묘지로 보내진다」 이므로 그 어휘를 쓴다.
#:
#: 🔴 이것이 「효과로 묘지로 보냈다」 를 뜻하지 않는다. ``ZoneMoved.movement``
#: 는 **이동의 의미**를 적는 칸이고, 그 이동이 효과였는지 규칙 절차였는지는
#: 같은 기록의 다른 축이다. 중요한 것은 이 기록이 ``CARD_MOVED`` 사건을
#: 만든다는 것이다 — 「이 카드가 묘지로 보내졌을 경우」 유발이 링크 소재로
#: 보내진 것에도 발화하는 것이 **실제 규칙**이기 때문이다.
LINK_MATERIAL_MOVEMENT: OperationKind = OperationKind.SEND_TO_GRAVE


#: 링크 소환 절차. 일반 · 특수 소환과 **같은 클래스**의 다른 값이다.
LINK_SUMMON_PROCEDURE = SummonProcedure(
    kind=PlayerActionKind.LINK_SUMMON,
    summon=SummonKind.LINK,
    from_zones=LINK_SUMMON_FROM_ZONES,
    to_zone=LINK_SUMMON_TO_ZONE,
    position=LINK_SUMMON_POSITION,
    error=LinkSummonError,
)


# ======================================================================
# 실행 — 여기서만 판이 바뀐다
# ======================================================================


@dataclass(frozen=True, slots=True)
class LinkSummonPlan:
    """
    소재를 어디서 어디로 보내고 무엇을 어디에 놓을 것인가.
    **아직 아무것도 바꾸지 않았다.**
    """

    placement: SummonPlacement
    materials: tuple[tuple[InstanceId, int, Zone], ...]
    """``(소재, 떠나는 자리의 플레이어, 떠나는 자리)`` — 기록에 쓴다."""

    def canonical_state(self) -> tuple:
        return (
            self.placement.canonical_state(),
            tuple(
                (instance.value, player, zone.value)
                for instance, player, zone in self.materials
            ),
        )

    def describe_ko(self) -> str:
        sent = " · ".join(str(i) for i, _p, _z in self.materials)
        return f"소재 {sent} → {LINK_MATERIAL_DESTINATION.value}, {self.placement.describe_ko()}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class LinkSummonExecutor:
    """
    링크 소환 하나를 수행한다. **상태를 갖지 않는다.**

    적법성을 판정하지 않는다 — 그것은 :func:`assess_link_materials` 가 이미
    했다. 여기서 보는 것은 **"지시를 수행할 수 있는가"** 뿐이고, 하나라도
    아니면 판에 손대기 전에 :class:`LinkSummonError` 로 멈춘다
    (:class:`~engine.summon.SummonProcedure` 와 같은 규율).
    """

    __slots__ = ("_procedure",)

    def __init__(self, procedure: SummonProcedure = LINK_SUMMON_PROCEDURE):
        self._procedure = procedure

    @property
    def procedure(self) -> SummonProcedure:
        return self._procedure

    # ------------------------------------------------------------------
    def plan(self, state, action: PlayerAction) -> LinkSummonPlan:
        """지시를 수행할 수 있는지 보고 두 걸음을 **함께** 정한다."""
        if action.kind is not self._procedure.kind:
            raise LinkSummonError(
                f"{action.kind.value} 는 {self._procedure.kind.value} 가 "
                "아닙니다."
            )
        if action.source is None:
            raise LinkSummonError("소환할 링크 몬스터가 지목되지 않았습니다.")
        if not action.materials:
            raise LinkSummonError("소재가 없습니다.")

        leaving: list[tuple[InstanceId, int, Zone]] = []
        for instance in action.materials:
            card = state.find_instance(instance)
            if card is None:
                raise LinkSummonError(
                    f"소재 {instance} 를 이 판에서 찾을 수 없습니다."
                )
            located = state.locate(instance)
            if located is None or located.zone not in LINK_MATERIAL_ZONES:
                where = located.zone.value if located else "어디에도"
                raise LinkSummonError(
                    f"소재 {instance} 가 필드에 없습니다 (현재 {where})."
                )
            if card.controller != action.actor:
                raise LinkSummonError(
                    f"소재 {instance} 는 P{card.controller} 의 몬스터입니다."
                )
            leaving.append((instance, card.controller, located.zone))

        #: 🔴 **소재가 떠난 뒤의 칸으로 배치를 정한다.** 그래서 배치 계획을
        #: 여기서 직접 만든다 — ``plan_for`` 는 지금 판의 빈 칸을 보므로,
        #: 소재가 엑스트라 몬스터 존에 있는 경우에 "빈 칸이 없다" 로 멈춘다.
        placement = self._plan_placement(state, action, leaving)
        return LinkSummonPlan(placement=placement, materials=tuple(leaving))

    def _plan_placement(
        self, state, action: PlayerAction, leaving
    ) -> SummonPlacement:
        card = state.find_instance(action.source)
        if card is None:
            raise LinkSummonError(
                f"{action.source} 를 이 판에서 찾을 수 없습니다."
            )
        located = state.locate(action.source)
        if located is None or located.zone not in self._procedure.from_zones:
            where = located.zone.value if located else "어디에도"
            allowed = " · ".join(
                sorted(z.value for z in self._procedure.from_zones)
            )
            raise LinkSummonError(
                f"{action.source} 가 {allowed} 에 없습니다 (현재 {where})."
            )
        if card.controller != action.actor:
            raise LinkSummonError(
                f"{action.source} 는 P{card.controller} 의 카드입니다."
            )

        target = state.zone(action.actor, self._procedure.to_zone)
        departing = {instance for instance, _p, _z in leaving}
        freed = {
            index
            for index, slot in enumerate(target.slots())
            if slot is not None and slot.instance_id in departing
        }
        free = sorted(set(target.free_slots()) | freed)
        if not free:
            raise LinkSummonError(
                f"{self._procedure.to_zone.value} 에 빈 칸이 없습니다."
            )
        return SummonPlacement(
            card=action.source,
            player=action.actor,
            owner=card.owner,
            from_player=card.controller,
            from_zone=located.zone,
            to_zone=self._procedure.to_zone,
            slot=free[0],
            position=self._procedure.position,
        )

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        """
        계획을 세우고 **소재를 먼저** 보낸 다음 놓는다.

        **소환권을 적지 않는다.** 링크 소환은 그 권리를 쓰지 않고, 그 사실은
        이 파일이 ``RuleUsageRegistry`` 를 아예 가져오지 않는 것으로
        지켜진다 (:mod:`engine.special_summon` 과 같은 자리).
        """
        plan = self.plan(state, action)
        deltas: list[StateDelta] = []
        for instance, from_player, from_zone in plan.materials:
            state.move(instance, LINK_MATERIAL_DESTINATION, to_player=from_player)
            moved = state.locate(instance)
            if moved is None or moved.zone is not LINK_MATERIAL_DESTINATION:
                raise LinkSummonError(
                    f"소재 {instance} 가 "
                    f"{LINK_MATERIAL_DESTINATION.value} 에 가지 않았습니다."
                )
            deltas.append(
                ZoneMoved(
                    movement=LINK_MATERIAL_MOVEMENT,
                    card=instance,
                    source_player=from_player,
                    source_zone=from_zone,
                    destination_player=from_player,
                    destination_zone=LINK_MATERIAL_DESTINATION,
                )
            )
        self._procedure.place(state, plan.placement)
        deltas.append(plan.placement.to_delta(self._procedure.summon))
        return tuple(deltas)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<LinkSummonExecutor {self._procedure.describe_ko()}>"


@dataclass(frozen=True, slots=True)
class LinkSummonHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    ``NormalSummonHandler`` · ``SpecialSummonHandler`` 와 같은 모양이다 —
    넘기는 것이 전부이고, 그래서 ``ActionExecutor`` 에 링크 지식이 한 줄도
    들어가지 않는다.
    """

    executor: LinkSummonExecutor = field(default_factory=LinkSummonExecutor)

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


def link_summoning_executor() -> "ActionExecutor":
    """
    링크 소환을 **아는** 실행기.

    기본 ``ActionExecutor`` 는 여전히 빈 채로 둔다 (ADR-006). 듀얼 한 판을
    굴리는 쪽은 :func:`~engine.summon.duel_executor` 를 쓴다.
    """
    from engine.action_execution import ActionExecutor

    return ActionExecutor().register(
        PlayerActionKind.LINK_SUMMON, LinkSummonHandler()
    )


__all__ = [
    "LINK_MATERIAL_MOVEMENT",
    "LINK_SUMMON_PROCEDURE",
    "LinkSummonError",
    "LinkSummonExecutor",
    "LinkSummonHandler",
    "LinkSummonPlan",
    "link_summoning_executor",
]
