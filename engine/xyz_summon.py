"""
엑시즈 소환의 **실행** — 소재를 겹치고 엑스트라 덱에서 꺼낸다 (Phase 6-BO).

    PlayerAction(XYZ_SUMMON, source, materials)
        ↓  ActionValidator            해도 되는가 (engine.xyz_rules 가 답한다)
        ↓  ActionExecutor             허가된 것만 넘긴다
        ↓  XyzSummonHandler           ← 이 파일
        ↓  GameState.attach_material  소재를 그 카드 **아래로**
        ↓  SummonProcedure            계획 → 적용 → 확인  (engine.summon)
    MaterialAttached × N  +  MonsterSummoned(summon=XYZ)

링크 소환과 **무엇이 다른가**
-----------------------------
=====================  ==========================  ========================
                        링크 소환                    엑시즈 소환
=====================  ==========================  ========================
소재가 가는 곳          **묘지** (``ZoneMoved``)     **그 카드 아래**
                                                    (``MaterialAttached``)
소재의 그 뒤            판을 떠났다                   판에 남는다
토큰 소재               **소멸한다**                 소멸하지 않는다 —
                                                    아래 설명을 보라
=====================  ==========================  ========================

🔴 **토큰을 소재로 겹치는 길은 막아 둔다.** 공식 규칙이 토큰을 필드 밖에
두지 않으므로 「엑시즈 소재가 된 토큰」 의 처리는 따로 읽어야 하고, 그
근거가 없다 (:data:`~engine.token.TOKEN_AS_OVERLAY_RULE` 가 그 사실을 이미
적어 두었다). 그래서 토큰이 소재로 들어오면 **판에 손대기 전에 멈춘다** —
링크 소환이 토큰을 소멸시키는 것과 **다른 처리**이고, 모르는 것을 그쪽
처리로 흉내 내지 않는다.

순서가 규칙이다
---------------
**소재를 먼저 겹치고 그 다음 놓는다.** 대체 절차의 소재는 엑스트라 몬스터
존에 서 있으므로, 먼저 겹치지 않으면 놓을 칸이 없다. 그리고 계획은
**소재가 떠난 뒤의 칸**으로 미리 정해 둔다 (``_plan_placement``) — 적용
도중에 멈출 일이 없어야 한다.

적법성을 판정하지 않는다
------------------------
"이 소재로 이 카드를 엑시즈 소환할 수 있는가" 는
:func:`~engine.xyz_rules.assess_xyz_materials` 가 이미 답했고 검증기가 그
답을 썼다. 여기서 보는 것은 **"지시를 수행할 수 있는가"** 뿐이다.

체인을 만들지 않는다
--------------------
소환은 발동이 아니다 — 이 파일에 ``Chain`` 도 ``ChainResolver`` 도
``TriggerCollector`` 도 없다. 「엑시즈 소환했을 경우」 · 「특수 소환되었을
경우」 유발을 모으는 것은 부르는 쪽의 일이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.effect.delta import (
    MATERIAL_BY_XYZ_SUMMON,
    MaterialAttached,
    StateDelta,
    SummonKind,
)
from engine.ids import InstanceId
from engine.summon import SummonError, SummonPlacement, SummonProcedure
from engine.token import is_token
from engine.vocabulary import Zone
from engine.xyz_rules import (
    XYZ_MATERIAL_ZONES,
    XYZ_SUMMON_FROM_ZONES,
    XYZ_SUMMON_POSITION,
    XYZ_SUMMON_TO_ZONE,
)


class XyzSummonError(SummonError):
    """지시를 수행할 수 없다. **판에 손대기 전에** 던진다."""


#: 엑시즈 소환 절차. 일반 · 특수 · 링크 소환과 **같은 클래스**의 다른 값이다.
XYZ_SUMMON_PROCEDURE = SummonProcedure(
    kind=PlayerActionKind.XYZ_SUMMON,
    summon=SummonKind.XYZ,
    from_zones=XYZ_SUMMON_FROM_ZONES,
    to_zone=XYZ_SUMMON_TO_ZONE,
    position=XYZ_SUMMON_POSITION,
    error=XyzSummonError,
)


@dataclass(frozen=True, slots=True)
class XyzSummonPlan:
    """
    어느 소재를 겹치고 무엇을 어디에 놓을 것인가.
    **아직 아무것도 바꾸지 않았다.**
    """

    placement: SummonPlacement
    materials: tuple[tuple[InstanceId, int, Zone], ...]
    """
    ``(소재, 떠나는 자리의 플레이어, 떠나는 자리)`` — 기록에 쓴다.

    🔴 **주인을 들고 다니지 않는다.** 링크 소재는 **주인의 묘지**로 가므로
    그 칸이 필요했지만 (:class:`~engine.link_summon.LinkSummonPlan`), 엑시즈
    소재는 **숙주 아래**로 가고 숙주는 한 장이다 — 갈 곳이 소유권으로
    갈리지 않는다.
    """

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
        return (
            f"소재 {sent} → {self.placement.card} 아래, "
            f"{self.placement.describe_ko()}"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class XyzSummonExecutor:
    """엑시즈 소환 하나를 수행한다. **상태를 갖지 않는다.**"""

    __slots__ = ("_procedure",)

    def __init__(self, procedure: SummonProcedure = XYZ_SUMMON_PROCEDURE):
        self._procedure = procedure

    @property
    def procedure(self) -> SummonProcedure:
        return self._procedure

    # ------------------------------------------------------------------
    def plan(self, state, action: PlayerAction) -> XyzSummonPlan:
        """지시를 수행할 수 있는지 보고 두 걸음을 **함께** 정한다."""
        if action.kind is not self._procedure.kind:
            raise XyzSummonError(
                f"{action.kind.value} 는 {self._procedure.kind.value} 가 "
                "아닙니다."
            )
        if action.source is None:
            raise XyzSummonError("소환할 엑시즈 몬스터가 지목되지 않았습니다.")
        if not action.materials:
            raise XyzSummonError("소재가 없습니다.")
        if len(set(action.materials)) != len(action.materials):
            raise XyzSummonError("같은 카드를 두 번 소재로 골랐습니다.")

        leaving: list[tuple[InstanceId, int, Zone]] = []
        for instance in action.materials:
            card = state.find_instance(instance)
            if card is None:
                raise XyzSummonError(
                    f"소재 {instance} 를 이 판에서 찾을 수 없습니다."
                )
            located = state.locate(instance)
            if located is None or located.zone not in XYZ_MATERIAL_ZONES:
                where = located.zone.value if located else "어디에도"
                raise XyzSummonError(
                    f"소재 {instance} 가 필드에 없습니다 (현재 {where})."
                )
            if card.controller != action.actor:
                raise XyzSummonError(
                    f"소재 {instance} 는 P{card.controller} 의 몬스터입니다."
                )
            #: 🔴 **토큰은 겹칠 수 없다** (모듈 머리말). "토큰인지 모른다"
            #: 도 허가가 아니다 — ``is_token`` 이 ``None`` 이면 멈춘다.
            token = is_token(card)
            if token is None:
                raise XyzSummonError(
                    f"소재 {instance} 의 카드 정의를 읽을 수 없어 토큰인지 "
                    "알 수 없습니다 — 겹쳐도 되는지 정할 수 없습니다."
                )
            if token:
                raise XyzSummonError(
                    f"소재 {instance} 는 토큰이고, 토큰을 엑시즈 소재로 "
                    "겹치는 처리를 아직 읽지 않았습니다."
                )
            leaving.append((instance, card.controller, located.zone))

        placement = self._plan_placement(state, action, leaving)
        return XyzSummonPlan(placement=placement, materials=tuple(leaving))

    def _plan_placement(
        self, state, action: PlayerAction, leaving
    ) -> SummonPlacement:
        """
        **소재가 떠난 뒤의 칸**으로 배치를 정한다.

        ``plan_for`` 는 지금 판의 빈 칸을 보므로, 소재가 엑스트라 몬스터
        존에 있는 경우에 "빈 칸이 없다" 로 멈춘다
        (:meth:`~engine.link_summon.LinkSummonExecutor._plan_placement` 와
        같은 자리이고 같은 이유다).
        """
        card = state.find_instance(action.source)
        if card is None:
            raise XyzSummonError(
                f"{action.source} 를 이 판에서 찾을 수 없습니다."
            )
        located = state.locate(action.source)
        if located is None or located.zone not in self._procedure.from_zones:
            where = located.zone.value if located else "어디에도"
            allowed = " · ".join(
                sorted(z.value for z in self._procedure.from_zones)
            )
            raise XyzSummonError(
                f"{action.source} 가 {allowed} 에 없습니다 (현재 {where})."
            )
        if card.controller != action.actor:
            raise XyzSummonError(
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
            raise XyzSummonError(
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
        계획을 세우고 **소재를 먼저 겹친** 다음 놓는다.

        **소환권을 적지 않는다.** 엑시즈 소환은 일반 소환권을 쓰지 않고, 그
        사실은 이 파일이 ``RuleUsageRegistry`` 를 아예 가져오지 않는 것으로
        지켜진다.
        """
        plan = self.plan(state, action)
        deltas: list[StateDelta] = []
        for instance, from_player, from_zone in plan.materials:
            state.attach_material(plan.placement.card, instance)
            moved = state.find_instance(instance)
            if moved is None or moved.zone is not Zone.OVERLAY:
                raise XyzSummonError(
                    f"소재 {instance} 가 {Zone.OVERLAY.value} 로 가지 "
                    "않았습니다."
                )
            deltas.append(
                MaterialAttached(
                    host=plan.placement.card,
                    card=instance,
                    source_player=from_player,
                    source_zone=from_zone,
                    basis=MATERIAL_BY_XYZ_SUMMON,
                )
            )
        self._procedure.place(state, plan.placement)
        #: 🔴 **이 턴에 그 카드명을 엑시즈 소환했다고 적는다.**
        #: ``SetSPSummonOnce`` 를 판정하는 자리가 이 기록을 읽는다
        #: (:func:`~engine.xyz_rules._spsummon_once_spent`).
        #: 🔴 **판정하지 않는다** — 여기서는 세기만 한다.
        summoned = state.find_instance(plan.placement.card)
        if summoned is not None and self._procedure.summon is not None:
            state.summon_uses.record(
                state.turn.turn_number,
                plan.placement.player,
                summoned.card_id,
                self._procedure.summon.value,
            )
        deltas.append(plan.placement.to_delta(self._procedure.summon))
        return tuple(deltas)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<XyzSummonExecutor {self._procedure.describe_ko()}>"


@dataclass(frozen=True, slots=True)
class XyzSummonHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    ``LinkSummonHandler`` 와 같은 모양이다 — 넘기는 것이 전부이고, 그래서
    ``ActionExecutor`` 에 엑시즈 지식이 한 줄도 들어가지 않는다.
    """

    executor: XyzSummonExecutor = field(default_factory=XyzSummonExecutor)

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


def xyz_summoning_executor() -> "ActionExecutor":
    """엑시즈 소환을 **아는** 실행기. 기본 실행기는 비워 둔다 (ADR-006)."""
    # 여기서 읽는다 — 실행기 계층에 모듈 최상단에서 의존하면 import 고리가
    # 생긴다 (Phase 2-U).
    from engine.action_execution import ActionExecutor

    return ActionExecutor().register(
        PlayerActionKind.XYZ_SUMMON, XyzSummonHandler()
    )


__all__ = [
    "XYZ_SUMMON_PROCEDURE",
    "XyzSummonError",
    "XyzSummonExecutor",
    "XyzSummonHandler",
    "XyzSummonPlan",
    "xyz_summoning_executor",
]
