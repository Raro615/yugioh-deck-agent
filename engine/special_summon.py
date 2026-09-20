"""
특수 소환의 **실행** — 공통 mutation 경로 하나.

    PlayerAction(SPECIAL_SUMMON)
        ↓  ActionValidator            해도 되는가 (지금은 **UNKNOWN**)
        ↓  ActionExecutor             허가된 것만 넘긴다
        ↓  SpecialSummonHandler       ← 이 파일
        ↓  SummonProcedure            계획 → 적용 → 확인   (engine.summon)
    GameState 변경  +  MonsterSummoned(summon=SPECIAL)
        ↓  EventReader                (부르는 쪽이 읽는다)
    TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate

이 단계가 만든 것은 **경로**이지 규칙이 아니다
----------------------------------------------
"이 카드를 특수 소환할 수 있는가" 는 카드마다 다르고, 그 조건을 읽는
계층이 아직 없다. 그래서 :class:`~engine.action_validation.ActionValidator`
는 ``SPECIAL_SUMMON`` 에 **언제나 ``UNKNOWN``** 을 돌려준다 — 허가를 밖에서
받지 않으면 아무것도 소환되지 않는다.

**``UNKNOWN`` 을 ``VALID`` 로 바꾸지 않는다.** "조건을 모른다" 와 "특수
소환할 수 없다" 도 합치지 않는다.

일반 소환과 무엇이 다른가
-------------------------
=====================  ==================  ==========================
                        일반 소환            특수 소환
=====================  ==================  ==========================
소환권                  **쓴다**            **쓰지 않는다**
출발 자리               패                   패 · 묘지 (지금 옮긴 것)
페이즈                  메인                 여기서 정하지 않는다
검증                    ``VALID`` 가 난다    언제나 ``UNKNOWN``
=====================  ==================  ==========================

첫 줄이 중요하다. 이 파일에는 :class:`
~engine.state.rule_usage.RuleUsageRegistry` 가 **나오지 않는다** — 특수
소환이 일반 소환권을 먹는 일이 구조적으로 불가능해야 한다.

절차는 :mod:`engine.summon` 과 **같은 코드**다
----------------------------------------------
자리 찾기 · 빈 칸 찾기 · 이동 · 착지 확인은 일반 소환과 한 글자도 다르지
않다. 복사하지 않고 :class:`~engine.summon.SummonProcedure` 를 값으로
설정해서 쓴다.

여기서 하지 않는 것
-------------------
융합 · 싱크로 · 엑시즈 · 링크 · 의식 · 펜듈럼 소환, 재료 고르기, 카드별
특수 소환 조건, 표시 형식 고르기, 소환 무효, "특수 소환되었을 때" 유발
효과의 **수집**, 체인, 우선권.

특히 체인을 만들지 않는다: 이 파일에 ``TriggerCollector`` 도
``TriggerChainIntegrator`` 도 ``Chain`` 도 ``ChainResolver`` 도 없다.
소환이 일어났다는 사실은 ``MonsterSummoned`` 하나로 남기고, 그것을 사건으로
읽을지는 부르는 쪽이 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor
from engine.effect.delta import StateDelta, SummonKind
from engine.summon import SummonError, SummonPlacement, SummonProcedure
from engine.vocabulary import Position, Zone


class SpecialSummonError(SummonError):
    """지시를 수행할 수 없다. **판에 손대기 전에** 던진다."""


#: 지금 **옮긴** 출발 자리.
#:
#: 이것이 "특수 소환은 패와 묘지에서만 나온다" 는 뜻이 **아니다.** 실제
#: 특수 소환은 덱 · 제외 · 엑스트라 덱에서도 나오고, 엑스트라 덱에서 나오는
#: 것은 융합 · 싱크로 · 엑시즈 · 링크 절차의 일이다 (이번 단계 범위 밖).
#:
#: 여기 없는 자리는 **"규칙상 안 된다" 가 아니라 "아직 옮기지 못했다"** 이고,
#: 검증기가 ``RULE_NOT_IMPLEMENTED`` 로 그렇게 말한다.
SPECIAL_SUMMON_FROM_ZONES: frozenset[Zone] = frozenset({Zone.HAND, Zone.GRAVE})

#: 놓이는 자리. 엑스트라 몬스터 존은 엑스트라 덱 절차와 함께 들어온다.
SPECIAL_SUMMON_TO_ZONE: Zone = Zone.MZONE

#: 놓이는 표시 형식. **고를 수 없다** (STRUCTURAL-61).
#:
#: 실제 특수 소환은 앞면 공격 · 앞면 수비를 고를 수 있다. 고르는 계층이
#: 없어서 하나로 고정했을 뿐이고, 이것이 규칙이라고 주장하지 않는다.
SPECIAL_SUMMON_POSITION: Position = Position.FACEUP_ATTACK

#: 특수 소환 절차. 일반 소환과 **같은 클래스**의 다른 값이다.
SPECIAL_SUMMON_PROCEDURE = SummonProcedure(
    kind=PlayerActionKind.SPECIAL_SUMMON,
    summon=SummonKind.SPECIAL,
    from_zones=SPECIAL_SUMMON_FROM_ZONES,
    to_zone=SPECIAL_SUMMON_TO_ZONE,
    position=SPECIAL_SUMMON_POSITION,
    error=SpecialSummonError,
)


class SpecialSummonExecutor:
    """
    특수 소환 하나를 수행한다. **상태를 갖지 않는다.**

        executor = SpecialSummonExecutor()
        placement = executor.plan(state, action)   # 판을 바꾸지 않는다
        deltas = executor.apply(state, action)     # 여기서만 바뀐다
    """

    __slots__ = ("_procedure",)

    def __init__(self, procedure: SummonProcedure = SPECIAL_SUMMON_PROCEDURE):
        self._procedure = procedure

    @property
    def procedure(self) -> SummonProcedure:
        return self._procedure

    # ------------------------------------------------------------------
    def plan(self, state, action: PlayerAction) -> SummonPlacement:
        """지시를 수행할 수 있는지 보고 배치를 정한다. **아무것도 바꾸지 않는다.**"""
        return self._procedure.plan(state, action)

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        """
        계획을 세우고 그대로 적용한다.

        **소환권을 적지 않는다.** 특수 소환은 일반 소환권을 쓰지 않고, 그
        사실은 이 파일이 ``RuleUsageRegistry`` 를 아예 가져오지 않는 것으로
        지켜진다.
        """
        placement = self._procedure.plan(state, action)
        self._procedure.place(state, placement)
        return (placement.to_delta(self._procedure.summon),)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<SpecialSummonExecutor {self._procedure.describe_ko()}>"


@dataclass(frozen=True, slots=True)
class SpecialSummonHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    규칙도 절차도 갖지 않는다 — :class:`SpecialSummonHandler` 가 하는 일은
    넘기는 것뿐이고, 그래서 ``ActionExecutor`` 에 소환 지식이 한 줄도 들어가지
    않는다 (``NormalSummonHandler`` 와 같은 모양이다).
    """

    executor: SpecialSummonExecutor = field(default_factory=SpecialSummonExecutor)

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        return self.executor.apply(state, action)


def special_summoning_executor() -> ActionExecutor:
    """
    특수 소환을 **아는** 실행기.

    기본 ``ActionExecutor`` 는 여전히 빈 채로 둔다 (ADR-006). 둘 다 필요하면
    :func:`~engine.summon.summon_executor` 를 쓴다.
    """
    return ActionExecutor().register(
        PlayerActionKind.SPECIAL_SUMMON, SpecialSummonHandler()
    )


__all__ = [
    "SPECIAL_SUMMON_FROM_ZONES",
    "SPECIAL_SUMMON_TO_ZONE",
    "SPECIAL_SUMMON_POSITION",
    "SPECIAL_SUMMON_PROCEDURE",
    "SpecialSummonError",
    "SpecialSummonExecutor",
    "SpecialSummonHandler",
    "special_summoning_executor",
]
