"""
특수 소환의 **실행** — 공통 mutation 경로 하나.

    PlayerAction(SPECIAL_SUMMON)
        ↓  ActionValidator            해도 되는가 (등재되지 않으면 **UNKNOWN**)
        ↓  ActionExecutor             허가된 것만 넘긴다
        ↓  SpecialSummonHandler       ← 이 파일
        ↓  SummonProcedure            계획 → 적용 → 확인   (engine.summon)
    GameState 변경  +  MonsterSummoned(summon=SPECIAL)
        ↓  EventReader                (부르는 쪽이 읽는다)
    TimingEvent(MONSTER_SUMMONED)  →  TriggerCandidate

이 단계가 만든 것은 **경로**이지 규칙이 아니다
----------------------------------------------
"이 카드를 특수 소환할 수 있는가" 는 카드마다 다르다. 그래서 조건은 카드
단위로만 적히고 (:data:`~engine.hand_summon.HAND_SUMMON_RULES`), 거기
적히지 않은 카드에는 :class:`~engine.action_validation.ActionValidator` 가
여전히 **``UNKNOWN``** 을 돌려준다 — 허가를 밖에서 받지 않으면 아무것도
소환되지 않는다.

🔴 **Phase 6-BN 에서 한 장이 등재되었다** (성유물－『성관』). 바뀐 것은
"조건을 아는 카드가 하나 생겼다" 이고, ``UNKNOWN`` 의 뜻은 그대로다.

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
검증                    ``VALID`` 가 난다    등재된 카드만 ``VALID``
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
from engine.action_target import ActionTargetKind
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
#: 🔴 **덱이 들어왔다** (Phase 6-AO). 「덱에서 … 1장을 특수 소환한다」 를
#: 실행하는 자리이고 (오르페골 디베르 ①), 옮기는 계층은 이미 있었다 —
#: :class:`~engine.summon.SummonProcedure` 는 출발 존의 목록만 본다.
SPECIAL_SUMMON_FROM_ZONES: frozenset[Zone] = frozenset(
    {Zone.HAND, Zone.GRAVE, Zone.DECK}
)

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


#: 🔴 **카드별 패 특수 소환 절차들** (Phase 6-BN).
#:
#: :data:`SPECIAL_SUMMON_PROCEDURE` 와 **같은 클래스의 다른 값**이다 —
#: 다른 것은 출발 자리 하나와 표시 형식 하나뿐이고, 둘 다
#: :data:`~engine.hand_summon.HAND_SUMMON_RULES` 가 카드마다 적어 둔 값을
#: 그대로 옮긴다. 옮기지 않고 여기서 다시 적으면 판정과 절차가 갈린다.
_HAND_SUMMON_PROCEDURES: "dict[int, SummonProcedure]" = {}


def hand_summon_procedure(card_id: int) -> "SummonProcedure | None":
    """
    그 카드의 **패 특수 소환 절차**. 등재되지 않았으면 ``None`` (ADR-006).

    🔴 표시 형식이 :data:`SPECIAL_SUMMON_POSITION` 이 아니다 — 성관은 앞면
    **수비** 표시로만 나온다 (``c27918365.lua`` 의
    ``SetTargetRange(POS_FACEUP_DEFENSE,0)``). 공통 절차의 고정값
    (STRUCTURAL-61) 은 "고르는 계층이 없다" 는 뜻이었고, **규칙이 형식을
    정하는 카드**는 그 고정값을 쓰면 안 된다.
    """
    # 여기서 읽는다 — 판정 계층은 실행 계층을 모르고, 반대 방향으로만
    # 의존한다 (ADR-007).
    from engine.hand_summon import hand_summon_rule_for

    rule = hand_summon_rule_for(card_id)
    if rule is None:
        return None
    found = _HAND_SUMMON_PROCEDURES.get(int(card_id))
    if found is None:
        found = SummonProcedure(
            kind=PlayerActionKind.SPECIAL_SUMMON,
            summon=SummonKind.SPECIAL,
            from_zones=frozenset({rule.from_zone}),
            to_zone=SPECIAL_SUMMON_TO_ZONE,
            position=rule.position,
            error=SpecialSummonError,
        )
        _HAND_SUMMON_PROCEDURES[int(card_id)] = found
    return found


def _named_slot(action: PlayerAction) -> "int | None":
    """행위가 지목한 **칸 번호**. 🔴 ``ZONE`` 대상에서만 읽는다."""
    for target in tuple(getattr(action, "targets", ()) or ()):
        if getattr(target, "kind", None) is ActionTargetKind.ZONE:
            return getattr(target, "index", None)
    return None


class HandSummonExecutor:
    """
    **패에서 자신을 특수 소환하는 카드별 절차**를 수행한다 (Phase 6-BN).

    공통 :class:`SpecialSummonExecutor` 와 다른 것이 셋이다.

    1. 절차를 **카드마다** 고른다 (:func:`hand_summon_procedure`) — 표시
       형식이 카드가 정하는 값이기 때문이다.
    2. 행위가 지목한 **칸에만** 놓는다 (``ActionTargetKind.ZONE``).
    3. **카드명당 턴 제한**을 쓴 것으로 적는다
       (:data:`~engine.hand_summon.HAND_SUMMON_USE_KIND`).

    🔴 **판정하지 않는다.** "지금 이 칸에 놓을 수 있는가" 는
    :func:`~engine.hand_summon.assess_hand_summon` 이 이미 답했고 검증기가
    그 답을 썼다. 여기서 다시 묻는다면 두 답이 갈리는 날이 온다.

    🔴 **체인을 만들지 않는다.** ``EFFECT_SPSUMMON_PROC`` 는 소환 **절차**
    이고 효과가 아니다 — 이 파일에 ``engine.chain`` 이 없는 이유다.
    """

    __slots__ = ()

    def plan(self, state, action: PlayerAction) -> SummonPlacement:
        """배치를 정한다. **아무것도 바꾸지 않는다.**"""
        procedure, slot = self._procedure_for(state, action)
        return procedure.plan(state, action, slot=slot)

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        procedure, slot = self._procedure_for(state, action)
        placement = procedure.plan(state, action, slot=slot)
        procedure.place(state, placement)
        #: 🔴 **이 턴에 그 카드명을 이 방법으로 썼다고 적는다.** 판정이
        #: 읽는 자리와 같은 이름이다 (``HAND_SUMMON_USE_KIND``) — 링크
        #: 소환 기록과 섞이지 않는다. 🔴 **판정하지 않는다**: 센다.
        from engine.hand_summon import HAND_SUMMON_USE_KIND

        summoned = state.find_instance(placement.card)
        if summoned is not None:
            state.summon_uses.record(
                state.turn.turn_number,
                placement.player,
                summoned.card_id,
                HAND_SUMMON_USE_KIND,
            )
        return (placement.to_delta(procedure.summon),)

    # ------------------------------------------------------------------
    def _procedure_for(
        self, state, action: PlayerAction
    ) -> "tuple[SummonProcedure, int | None]":
        card = (
            state.find_instance(action.source)
            if action.source is not None else None
        )
        if card is None:
            raise SpecialSummonError(
                f"{action.source} 를 이 판에서 찾을 수 없습니다."
            )
        procedure = hand_summon_procedure(card.card_id)
        if procedure is None:  # pragma: no cover - 라우팅이 막는다
            raise SpecialSummonError(
                f"{card.card_id} 의 패 특수 소환 절차가 등재되지 않았습니다."
            )
        return procedure, _named_slot(action)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<HandSummonExecutor 카드별 패 특수 소환>"


@dataclass(frozen=True, slots=True)
class SpecialSummonHandler:
    """
    :class:`~engine.action_execution.ActionHandler` 로 등록되는 껍데기.

    규칙도 절차도 갖지 않는다 — :class:`SpecialSummonHandler` 가 하는 일은
    넘기는 것뿐이고, 그래서 ``ActionExecutor`` 에 소환 지식이 한 줄도 들어가지
    않는다 (``NormalSummonHandler`` 와 같은 모양이다).
    """

    executor: SpecialSummonExecutor = field(default_factory=SpecialSummonExecutor)
    hand: HandSummonExecutor = field(default_factory=HandSummonExecutor)
    """🔴 Phase 6-BN — 카드별 패 특수 소환은 **다른 실행기**가 맡는다."""

    def apply(self, state, action: PlayerAction) -> "tuple[StateDelta, ...]":
        #: 🔴 **갈림은 등재 여부 하나로 정한다** (ADR-006). 등재된 카드가
        #: 칸을 지목했으면 카드별 절차로, 그 밖의 모든 특수 소환은 예전
        #: 그대로 공통 절차로 간다 — 효과가 부르는 길은 이 핸들러를 아예
        #: 지나지 않으므로 (``SummonProcedure.plan_for``) 영향이 없다.
        if self._is_hand_summon(state, action):
            return self.hand.apply(state, action)
        return self.executor.apply(state, action)

    @staticmethod
    def _is_hand_summon(state, action: PlayerAction) -> bool:
        if _named_slot(action) is None:
            return False
        card = (
            state.find_instance(action.source)
            if action.source is not None else None
        )
        if card is None:
            return False
        return hand_summon_procedure(card.card_id) is not None


def special_summoning_executor() -> "ActionExecutor":
    """
    특수 소환을 **아는** 실행기.

    기본 ``ActionExecutor`` 는 여전히 빈 채로 둔다 (ADR-006). 둘 다 필요하면
    :func:`~engine.summon.summon_executor` 를 쓴다.
    """
    # 여기서 읽는다 — 이 모듈을 효과 실행기가 쓰므로, 실행기 계층에
    # 의존하면 import 고리가 생긴다 (Phase 2-U).
    from engine.action_execution import ActionExecutor

    return ActionExecutor().register(
        PlayerActionKind.SPECIAL_SUMMON, SpecialSummonHandler()
    )


__all__ = [
    "HandSummonExecutor",
    "hand_summon_procedure",
    "SPECIAL_SUMMON_FROM_ZONES",
    "SPECIAL_SUMMON_TO_ZONE",
    "SPECIAL_SUMMON_POSITION",
    "SPECIAL_SUMMON_PROCEDURE",
    "SpecialSummonError",
    "SpecialSummonExecutor",
    "SpecialSummonHandler",
    "special_summoning_executor",
]
