"""
Action 검증 — "이 행위를 할 수 있는가?"

**실행하지 않는다.** 검증은 질문이고, 답은 세 가지다.

=================  ================================================  ==========
층                  질문                                              지금 상태
=================  ================================================  ==========
구조 (structure)   이 Action 이 **말이 되는 모양인가**                구현됨
적법성 (legality)  이 행위를 지금 **해도 되는가**                     일부 구현
=================  ================================================  ==========

Phase 2-B-2 가 늘린 것은 아래쪽이다. 아직 소환 절차 · 타이밍 · 체인이 없으므로
**``VALID`` 는 아직 나오지 않는다.** 그러나 확실한 위반은 많이 잡아낸다 —
남의 카드를 소환하려 한다, 필드의 카드를 다시 소환하려 한다, 메인 페이즈에
공격을 선언한다, 몬스터 존이 꽉 찼다 …

관측만 본다
-----------
:class:`ActionValidator` 는 :class:`~engine.game_state_view.GameStateView` 를
받는다. ``GameState`` 를 받지 않는다 — 받으면 ``move()`` 가 손에 닿고, 그보다
먼저 **상대의 패와 덱이 보인다.** 판정이 "그 카드는 이 듀얼에 없다" 와
"보이지 않는다" 를 구분해 버리면, 검증을 반복하는 것만으로 상대의 손패를
탐지할 수 있다.

그래서 보이지 않는 카드는 ``UNKNOWN`` 이다. 없는 것인지 숨은 것인지 모른다.

UNKNOWN 은 허가가 아니다
------------------------
:attr:`ValidationResult.permits_execution` 은 ``VALID`` 일 때만 참이다.
``if result.validity is not INVALID:`` 로 쓰면 ``UNKNOWN`` 이 허가로 새어
나가므로, 그 대신 이 프로퍼티를 본다.

조건 계층을 쓴다
----------------
"패에 있는가" · "몬스터인가" · "몬스터 존에 빈 칸이 있는가" 는 이미
:mod:`engine.condition` 이 답할 수 있다. 검증기는 종류별 **요구 목록**을
만들고 :class:`~engine.condition.ConditionEvaluator` 가 판정한다.
``FALSE`` 는 ``INVALID`` 로, ``UNKNOWN`` 은 ``UNKNOWN`` 으로 **보존된다.**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from engine.action import (
    _ALLOWS_EFFECT_REF,
    _FORBIDS_SOURCE,
    _NEEDS_EFFECT_REF,
    _NEEDS_PHASE,
    _NEEDS_SOURCE,
    _TARGET_COUNT,
    PlayerAction,
    PlayerActionKind,
)
from engine.action_target import ActionTarget, ActionTargetKind
from engine.condition import (
    CardIsInZone,
    Condition,
    ConditionContext,
    ConditionEvaluator,
    ConditionResult,
    ControllerIs,
    InAnyZone,
    IsMonster,
    IsTurnPlayer,
    NotMonster,
    PhaseIs,
    PlayerRef,
    ZoneHasFreeSlot,
)
from engine.condition.model import _resolve_definition
from engine.game_state_view import CardDefinitionView, CardView, GameStateView
from engine.summon_rules import SummonAssessment, assess_normal_summon
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.ids import InstanceId
from engine.vocabulary import Phase, Zone

#: 몬스터가 놓이는 존. 공격 · 표시 형식 변경의 출발점이다.
MONSTER_ZONES: frozenset[Zone] = frozenset({Zone.MZONE, Zone.EMZONE})

#: 배틀 페이즈. ``TURN_PHASE_ORDER`` 는 ``BATTLE`` 하나만 담지만, 내부 스텝
#: 이름도 함께 인정한다 — Phase 1 이 ``set_phase`` 로 직접 지정할 수 있다.
#: 메인 페이즈. 소환 · 세트 · 표시 형식 변경이 여기서 일어난다
#: (룰북 RULE-TURN-004 · RULE-TURN-006: "Summon or Set a Monster").
MAIN_PHASES: tuple[Phase, ...] = (Phase.MAIN1, Phase.MAIN2)

BATTLE_PHASES: tuple[Phase, ...] = (
    Phase.BATTLE,
    Phase.BATTLE_START,
    Phase.BATTLE_STEP,
    Phase.DAMAGE,
    Phase.DAMAGE_CAL,
)


@dataclass(frozen=True, slots=True)
class Requirement:
    """
    "이것이 참이어야 한다" 하나.

    조건이 ``FALSE`` 면 :attr:`code` 로 거부하고, ``UNKNOWN`` 이면 판정을
    보류한다. **``UNKNOWN`` 을 ``FALSE`` 로 접지 않는다.**
    """

    condition: Condition
    code: ValidationCode
    detail: str


#: 종류별로 "어떤 규칙 계층이 더 있어야 **허가**까지 갈 수 있는가".
#: 전부 차 있다는 것은 지금 어떤 Action 도 VALID 가 될 수 없다는 뜻이다.
_MISSING_RULE: dict[PlayerActionKind, str] = {
    PlayerActionKind.SET_MONSTER: "summon-procedure (Phase 2-G)",
    PlayerActionKind.SET_SPELL_TRAP: "set-timing (Phase 2-G)",
    PlayerActionKind.ACTIVATE_CARD: "activation-timing (Phase 2-C/2-F)",
    PlayerActionKind.ACTIVATE_EFFECT: "activation-condition · cost · timing (Phase 2-C/2-F)",
    PlayerActionKind.CHANGE_POSITION: "position-change-legality (Phase 2-G)",
    PlayerActionKind.ATTACK: "attack-declaration (Phase 2-G)",
    PlayerActionKind.CHANGE_PHASE: "turn-progression (Phase 2-G)",
    PlayerActionKind.END_PHASE: "turn-progression (Phase 2-G)",
    PlayerActionKind.PASS: "priority (Phase 2-F)",
}

#: 요구를 **전부** 통과하면 허가가 되는 종류.
#:
#: Phase 2-I 이전에는 비어 있었다 — 어떤 Action 도 마지막 한 걸음을 확인할
#: 수 없었기 때문이다. 일반 소환만 그 걸음이 채워졌다: 페이즈 · 턴 플레이어 ·
#: 자리 · 카드 종류 · 소환권 · 절차가 모두 판정된다.
#:
#: **여기 넣는 것은 "이 종류의 적법성을 끝까지 볼 수 있다" 는 선언이다.**
#: 요구 목록이 비어 있는 종류를 넣으면 아무것도 확인하지 않고 허가가 난다.
_COMPLETE_RULES: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.NORMAL_SUMMON}
)

assert not (_COMPLETE_RULES & set(_MISSING_RULE)), (
    "한 종류가 '끝까지 본다' 와 '규칙이 없다' 를 동시에 말할 수 없습니다."
)


class ActionValidator:
    """
    Action 을 검증한다. **관측만 읽고, 아무것도 바꾸지 않는다.**

    세 진입점이 있다.

    - :meth:`validate_structure` — 판을 보지 않고 모양만. ``VALID`` / ``INVALID``.
    - :meth:`validate` — 모양 + 판 위의 사실. 지금은 ``INVALID`` / ``UNKNOWN``.
    - :meth:`requirements` — 종류별 요구 목록 (설명 · 디버깅용).
    """

    __slots__ = ("_view", "_evaluator")

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "ActionValidator 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 상대의 패와 덱이 보이고, 판정이 정보를 흘립니다 "
                "(GameStateView.from_state 로 감싸세요)."
            )
        self._view = view
        self._evaluator = ConditionEvaluator(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    # ==================================================================
    # 1층 — 모양
    # ==================================================================
    def validate_structure(self, action: PlayerAction) -> ValidationResult:
        """
        Action 의 **모양**만 본다. 판도 규칙도 보지 않는다.

        "일반 소환인데 소환할 카드가 없다" 가 여기서 걸린다.
        "이 카드를 지금 소환할 수 있는가" 는 :meth:`validate` 의 몫이다.
        """
        kind = action.kind
        if action.actor not in (0, 1):
            return ValidationResult.invalid(
                ValidationCode.ACTOR_INVALID,
                f"actor 는 0 또는 1 입니다: {action.actor}",
            )

        if kind in _NEEDS_SOURCE and action.source is None:
            return ValidationResult.invalid(
                ValidationCode.SOURCE_REQUIRED,
                f"{kind.value} 에는 source 가 필요합니다.",
            )
        if kind in _FORBIDS_SOURCE and action.source is not None:
            return ValidationResult.invalid(
                ValidationCode.SOURCE_FORBIDDEN,
                f"{kind.value} 는 source 를 가질 수 없습니다.",
            )

        if kind in _NEEDS_EFFECT_REF and action.effect_ref is None:
            return ValidationResult.invalid(
                ValidationCode.EFFECT_REF_REQUIRED,
                f"{kind.value} 에는 effect_ref 가 필요합니다. 어느 효과인지 "
                "EffectRef(card_id, ordinal) 로 지목하세요.",
            )
        if kind not in _ALLOWS_EFFECT_REF and action.effect_ref is not None:
            return ValidationResult.invalid(
                ValidationCode.EFFECT_REF_FORBIDDEN,
                f"{kind.value} 는 effect_ref 를 가질 수 없습니다.",
            )

        if kind in _NEEDS_PHASE and action.phase is None:
            return ValidationResult.invalid(
                ValidationCode.PHASE_REQUIRED,
                f"{kind.value} 에는 phase 가 필요합니다.",
            )
        if kind not in _NEEDS_PHASE and action.phase is not None:
            return ValidationResult.invalid(
                ValidationCode.PHASE_FORBIDDEN,
                f"{kind.value} 는 phase 를 가질 수 없습니다.",
            )

        expected = _TARGET_COUNT.get(kind)
        if expected is not None and len(action.targets) != expected:
            return ValidationResult.invalid(
                ValidationCode.TARGET_COUNT_MISMATCH,
                f"{kind.value} 의 대상은 {expected}개여야 합니다: "
                f"{len(action.targets)}개가 들어왔습니다.",
            )

        if kind is PlayerActionKind.ATTACK:
            target = action.targets[0]
            if target.kind not in (
                ActionTargetKind.INSTANCE,
                ActionTargetKind.PLAYER,
            ):
                return ValidationResult.invalid(
                    ValidationCode.TARGET_KIND_INVALID,
                    "공격 대상은 몬스터(instance) 또는 플레이어여야 합니다: "
                    f"{target.kind.value}",
                )

        return ValidationResult.valid("구조가 올바릅니다.")

    # ==================================================================
    # 2층 — 판 위의 사실
    # ==================================================================
    def validate(
        self, action: PlayerAction, context: ConditionContext | None = None
    ) -> ValidationResult:
        """
        모양을 본 뒤 판 위의 사실까지 본다. **아무것도 바꾸지 않는다.**

        아직 ``VALID`` 는 나오지 않는다 — 소환 절차 · 타이밍 · 체인이 없어서
        마지막 한 걸음을 확인할 수 없기 때문이다. 대신 확실한 위반은
        ``INVALID`` 로 잡고, 나머지는 **무엇이 없어서 모르는지** 밝힌다.
        """
        structural = self.validate_structure(action)
        if structural.validity is not ActionValidity.VALID:
            return structural

        if self._view.is_over:
            return ValidationResult.invalid(
                ValidationCode.DUEL_ALREADY_OVER, "이미 끝난 듀얼입니다."
            )

        ctx = context if context is not None else self.context_for(action)

        # 참조 무결성 — 가리킨 카드를 볼 수 있는가.
        unseen = self._first_unseen(action)
        if unseen is not None:
            return ValidationResult.unknown(
                ValidationCode.HIDDEN_CARD,
                f"{unseen} 가 관측에 보이지 않습니다. 이 듀얼에 없는지 "
                "가려진 존에 있는지 구분할 수 없습니다.",
            )

        # 효과 참조가 그 카드의 것인가.
        effect_check = self._check_effect_ref(action)
        if effect_check is not None:
            return effect_check

        # 종류별 요구 목록 — 조건 계층이 판정한다.
        verdict = self._check_requirements(self.requirements(action), ctx)
        if verdict is not None:
            return verdict

        # 여기까지 왔다면 확인할 수 있는 것은 전부 통과했다.
        if action.kind in _COMPLETE_RULES:
            return ValidationResult.valid(
                f"{action.kind.value} 의 요구를 전부 통과했습니다."
            )

        # 나머지는 통과해도 허가가 아니다 — 마지막 한 걸음을 볼 규칙 계층이 없다.
        return ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"{action.kind.value} 의 남은 적법성을 판정할 규칙 계층이 아직 "
            "없습니다. 확인할 수 있는 것은 전부 통과했습니다.",
            missing_rule=_MISSING_RULE[action.kind],
        )

    def context_for(self, action: PlayerAction) -> ConditionContext:
        """Action 에서 조건 문맥을 만든다. 안정적인 식별자만 담긴다."""
        return ConditionContext(
            player=action.actor,
            source=action.source,
            effect_ref=action.effect_ref,
            targets=action.instance_targets(),
        )

    # ------------------------------------------------------------------
    # 요구 목록 — 종류별 dispatch
    # ------------------------------------------------------------------
    def requirements(self, action: PlayerAction) -> tuple[Requirement, ...]:
        """이 Action 이 만족해야 하는, **지금 판정할 수 있는** 것들."""
        builder = _REQUIREMENT_BUILDERS.get(action.kind)
        return builder(self, action) if builder is not None else ()

    def _check_requirements(
        self, requirements: tuple[Requirement, ...], context: ConditionContext
    ) -> ValidationResult | None:
        """
        요구를 순서대로 판정한다. 통과하면 ``None``.

        ``FALSE`` 가 ``UNKNOWN`` 을 이긴다 — 확실한 위반이 하나라도 있으면
        나머지를 몰라도 거부다. 순서가 고정이므로 결과도 결정론적이다.
        """
        pending: list[str] = []
        missing: str | None = None
        for requirement in requirements:
            verdict = self._evaluator.evaluate(requirement.condition, context)
            if verdict.result is ConditionResult.FALSE:
                return ValidationResult.invalid(requirement.code, requirement.detail)
            if verdict.result is ConditionResult.UNKNOWN:
                # 조건 계층이 **무엇 때문에** 모르는지 이미 알고 있다.
                # 다시 추측하지 않고 그대로 전한다.
                why = "; ".join(verdict.unknown_reasons) or verdict.description
                pending.append(f"{requirement.detail} ({why})")
                # "정보가 없어서" 와 "규칙이 없어서" 는 다른 사실이다.
                # 조건 자신이 안다 — 검증기가 추측하지 않는다.
                rules = requirement.condition.missing_rules(self._view, context)
                if missing is None and rules:
                    missing = rules[0]
        if pending:
            if missing is not None:
                # 정보가 없어서가 아니라 **규칙 계층이 없어서** 모른다.
                return ValidationResult.unknown(
                    ValidationCode.RULE_NOT_IMPLEMENTED,
                    "아직 구현하지 않은 규칙이 걸려 있습니다.",
                    missing_rule=missing,
                    notes=tuple(pending),
                )
            return ValidationResult.unknown(
                ValidationCode.INFORMATION_UNAVAILABLE,
                "판정에 필요한 정보가 없습니다.",
                notes=tuple(pending),
            )
        return None

    # ------------------------------------------------------------------
    # 관측 조회
    # ------------------------------------------------------------------
    def _first_unseen(self, action: PlayerAction) -> InstanceId | None:
        """가리킨 카드 중 **관측에 없는** 첫 번째. 순서가 고정이다."""
        if action.source is not None and self._view.find(action.source) is None:
            return action.source
        for target in action.targets:
            if (
                target.kind is ActionTargetKind.INSTANCE
                and target.instance_id is not None
                and self._view.find(target.instance_id) is None
            ):
                return target.instance_id
        return None

    def _seen(self, instance: InstanceId | None) -> CardView | None:
        return self._view.find(instance) if instance is not None else None

    def _definition(self, instance: InstanceId | None) -> CardDefinitionView | None:
        card = self._seen(instance)
        return card.definition if card is not None else None

    def _check_effect_ref(self, action: PlayerAction) -> ValidationResult | None:
        """
        ``effect_ref`` 가 그 카드의 것인지 본다. 통과하면 ``None``.

        ``ordinal`` 이 범위를 벗어났는지는 **효과 목록을 믿을 수 있을 때만**
        따진다. ``effect_count`` 가 0 인 카드는 효과가 없어서인지 파서가
        못 읽어서인지 구분되지 않기 때문이다 (ADR-006, 실측 195장).
        """
        ref = action.effect_ref
        if ref is None or action.source is None:
            return None
        card = self._seen(action.source)
        if card is None or card.card_id is None:
            return None  # 위에서 이미 걸렀거나, 정체를 모른다
        if card.card_id != ref.card_id:
            return ValidationResult.invalid(
                ValidationCode.EFFECT_REF_CARD_MISMATCH,
                f"effect_ref 의 카드({ref.card_id})가 source 카드"
                f"({card.card_id})와 다릅니다.",
            )
        definition = card.definition
        if definition is None:
            return ValidationResult.unknown(
                ValidationCode.CARD_DEFINITION_UNAVAILABLE,
                f"{card.card_id} 의 카드 정의를 읽을 수 없어 효과 "
                f"{ref.ordinal} 번이 있는지 확인할 수 없습니다.",
            )
        if not definition.effects_are_addressable:
            return ValidationResult.unknown(
                ValidationCode.EFFECT_LIST_UNRELIABLE,
                f"{definition.name} 의 효과 목록이 비어 있습니다. 효과가 "
                "없어서인지 스크립트를 읽지 못해서인지 구분할 수 없습니다.",
                missing_rule="shared-library effect parsing (ADR-006)",
            )
        if ref.ordinal >= definition.effect_count:
            return ValidationResult.invalid(
                ValidationCode.EFFECT_REF_OUT_OF_RANGE,
                f"{definition.name} 의 효과는 {definition.effect_count}개입니다: "
                f"{ref.ordinal} 번은 없습니다.",
            )
        return None

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ActionValidator {self._view}>"


# ======================================================================
# 종류별 요구 목록
# ======================================================================
#
# 거대한 if/elif 를 만들지 않으려고 종류마다 작은 함수를 두고 표로 묶는다.
# 각 함수는 **지금 판정할 수 있는 것만** 담는다. 없는 규칙을 흉내내지 않는다.


def _controlled_by_actor(validator: ActionValidator, action: PlayerAction) -> Condition:
    """
    source 를 actor 가 쥐고 있는가.

    ``controller`` 는 관측에 언제나 실려 있다 (뒷면 카드도 자리는 보인다).
    그래서 정체를 몰라도 판정할 수 있다.
    """
    return ControllerIs(PlayerRef.CONTROLLER, action.source)


def _summon_like(validator: ActionValidator, action: PlayerAction) -> tuple[Requirement, ...]:
    """일반 소환 · 세트 몬스터가 공유하는 요구."""
    return (
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            "자신의 턴이 아닙니다.",
        ),
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
        ),
        Requirement(
            CardIsInZone(Zone.HAND, PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_WRONG_ZONE,
            "패에 있는 카드가 아닙니다.",
        ),
        Requirement(
            IsMonster(action.source),
            ValidationCode.SOURCE_WRONG_CARD_TYPE,
            "몬스터가 아닙니다.",
        ),
        Requirement(
            ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.MZONE),
            ValidationCode.ZONE_FULL,
            "몬스터 존에 빈 칸이 없습니다.",
        ),
    )


def _normal_summon(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    """
    일반 소환. **이 목록을 전부 통과하면 허가가 난다** (``_COMPLETE_RULES``).

    공식 규칙 (``data/rules/documents/sd-rulebook-en-v10.json``):

    - RULE-TURN-004 · RULE-TURN-006 — 소환은 메인 페이즈의 행위다.
    - RULE-SUMMON-009 — 패에서 필드로, 앞면 공격 표시로.
    - RULE-SUMMON-009 — "You can only Normal Summon OR Normal Set once per
      turn."

    세트(``SET_MONSTER``)는 아직 이 목록을 쓰지 않는다 — 세트 절차를 이번
    단계에서 구현하지 않았고, 소환권을 함께 쓰는 규칙도 세트가 실행될 수
    있을 때 이어야 한다.
    """
    return _summon_like(validator, action) + (
        Requirement(
            PhaseIs(MAIN_PHASES),
            ValidationCode.WRONG_PHASE,
            "메인 페이즈가 아닙니다.",
        ),
        Requirement(
            _NormalSummonRightAvailable(),
            ValidationCode.NORMAL_SUMMON_ALREADY_USED,
            "이번 턴의 일반 소환권을 이미 썼습니다.",
        ),
        Requirement(
            _NormalSummonProcedure(action.source),
            ValidationCode.CANNOT_NORMAL_SUMMON,
            "이 카드는 일반 소환으로 필드에 나오지 않습니다.",
        ),
    )


def _set_spell_trap(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    return (
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            "자신의 턴이 아닙니다.",
        ),
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
        ),
        Requirement(
            CardIsInZone(Zone.HAND, PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_WRONG_ZONE,
            "패에 있는 카드가 아닙니다.",
        ),
        Requirement(
            NotMonster(action.source),
            ValidationCode.SOURCE_WRONG_CARD_TYPE,
            "마법 · 함정이 아닙니다.",
        ),
        Requirement(
            ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.SZONE),
            ValidationCode.ZONE_FULL,
            "마법 & 함정 존에 빈 칸이 없습니다.",
        ),
    )


def _change_position(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    return (
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            "자신의 턴이 아닙니다.",
        ),
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
        ),
        Requirement(
            InAnyZone(MONSTER_ZONES, action.source),
            ValidationCode.SOURCE_WRONG_ZONE,
            "몬스터 존에 있는 카드가 아닙니다.",
        ),
    )


def _attack(validator: ActionValidator, action: PlayerAction) -> tuple[Requirement, ...]:
    requirements = [
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            "자신의 턴이 아닙니다.",
        ),
        Requirement(
            PhaseIs(BATTLE_PHASES),
            ValidationCode.WRONG_PHASE,
            "배틀 페이즈가 아닙니다.",
        ),
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 몬스터가 아닙니다.",
        ),
        Requirement(
            InAnyZone(MONSTER_ZONES, action.source),
            ValidationCode.SOURCE_WRONG_ZONE,
            "몬스터 존에 있는 카드가 아닙니다.",
        ),
    ]
    target = action.targets[0] if action.targets else None
    if target is not None and target.kind is ActionTargetKind.PLAYER:
        if target.player == action.actor:
            requirements.append(
                Requirement(
                    _AlwaysFalseMarker(),
                    ValidationCode.TARGET_NOT_OPPONENT,
                    "자기 자신을 공격할 수 없습니다.",
                )
            )
    elif target is not None and target.kind is ActionTargetKind.INSTANCE:
        requirements.append(
            Requirement(
                ControllerIs(PlayerRef.OPPONENT, target.instance_id),
                ValidationCode.TARGET_SELF_CONTROLLED,
                "자신의 몬스터를 공격할 수 없습니다.",
            )
        )
        requirements.append(
            Requirement(
                InAnyZone(MONSTER_ZONES, target.instance_id),
                ValidationCode.TARGET_WRONG_ZONE,
                "몬스터 존에 없는 카드는 공격 대상이 아닙니다.",
            )
        )
    return tuple(requirements)


def _activate(validator: ActionValidator, action: PlayerAction) -> tuple[Requirement, ...]:
    """
    발동. **누구 턴인지 묻지 않는다** — 상대 턴에 발동하는 함정과 퀵 효과가
    정상이기 때문이다. 타이밍과 스펠 스피드는 Phase 2-F 의 몫이다.
    """
    return (
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
        ),
    )


def _turn_progression(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    requirements = [
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            "턴 플레이어만 페이즈를 넘길 수 있습니다.",
        )
    ]
    if action.phase is not None and action.phase is validator.view.phase:
        requirements.append(
            Requirement(
                _AlwaysFalseMarker(),
                ValidationCode.PHASE_UNCHANGED,
                f"이미 {action.phase.value} 페이즈입니다.",
            )
        )
    return tuple(requirements)


#: 종류 -> 요구 목록 생성기. 없는 종류는 요구가 없다는 뜻이다.
_REQUIREMENT_BUILDERS: dict[
    PlayerActionKind, Callable[[ActionValidator, PlayerAction], tuple[Requirement, ...]]
] = {
    PlayerActionKind.NORMAL_SUMMON: _normal_summon,
    PlayerActionKind.SET_MONSTER: _summon_like,
    PlayerActionKind.SET_SPELL_TRAP: _set_spell_trap,
    PlayerActionKind.CHANGE_POSITION: _change_position,
    PlayerActionKind.ATTACK: _attack,
    PlayerActionKind.ACTIVATE_CARD: _activate,
    PlayerActionKind.ACTIVATE_EFFECT: _activate,
    PlayerActionKind.CHANGE_PHASE: _turn_progression,
    PlayerActionKind.END_PHASE: _turn_progression,
    # PASS 는 우선권 규칙이 없어 지금 판정할 수 있는 것이 없다.
}


# ======================================================================
# 검증 전용 조건
# ======================================================================
#
# 조건 계층에 있으면 좋겠지만 아직 카드 효과가 쓸 일이 없는 것들이다.
# 실제로 필요해지면 engine/condition/model.py 로 옮긴다.


@dataclass(frozen=True, slots=True)
class _NormalSummonRightAvailable(Condition):
    """
    이번 턴의 일반 소환권이 남아 있는가 (RULE-SUMMON-009).

    **관측에서 읽는다.** 소환은 공개된 자리에서 일어나므로 가려진 정보가
    아니고, 따라서 ``UNKNOWN`` 이 나오지 않는다.
    """

    def evaluate(self, view, context) -> ConditionResult:
        used = view.normal_summons_used[context.player]
        return ConditionResult.from_bool(used == 0)

    def canonical_state(self) -> tuple:
        return ("normal_summon_right_available",)

    def to_dict(self) -> dict:
        return {"kind": "normal_summon_right_available"}

    def describe_ko(self) -> str:
        return "이번 턴의 일반 소환권이 남아 있다"


@dataclass(frozen=True, slots=True)
class _NormalSummonProcedure(Condition):
    """
    이 카드가 일반 소환 **절차**를 밟을 수 있는가.

    판정은 :func:`~engine.summon_rules.assess_normal_summon` 하나가 한다 —
    검증기와 실행기가 같은 답을 쓰게 하려면 판정이 한 곳에만 있어야 한다.

    세 갈래가 그대로 보존된다.

    - ``ORDINARY`` → ``TRUE``
    - ``FORBIDDEN`` → ``FALSE`` (엑스트라 덱 · 의식 · 토큰)
    - ``NEEDS_TRIBUTE`` · ``UNDETERMINED`` → ``UNKNOWN``

    제물이 필요한 몬스터를 ``FALSE`` 로 적지 않는다. 실제 규칙에서는 제물을
    바치면 소환할 수 있고, 없는 것은 그 절차뿐이다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        assessment = self._assess(view, context)
        if assessment.permits_procedure:
            return ConditionResult.TRUE
        if assessment.is_refusal:
            return ConditionResult.FALSE
        return ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        assessment = self._assess(view, context)
        if assessment.permits_procedure or assessment.is_refusal:
            return ()
        return (assessment.reason,)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        """
        **왜 모르는가가 두 가지다.** 제물 절차가 없어서 모르는 것과, 카드
        정의를 못 읽어서 모르는 것은 다른 사실이다. 앞의 것만 규칙 이름을
        돌려준다.
        """
        rule = self._assess(view, context).missing_rule
        return (rule,) if rule else ()

    def _assess(self, view, context) -> SummonAssessment:
        definition, _ = _resolve_definition(view, context, self.instance)
        return assess_normal_summon(definition)

    def canonical_state(self) -> tuple:
        return (
            "normal_summon_procedure",
            self.instance.value if self.instance else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "normal_summon_procedure"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 일반 소환 절차를 밟을 수 있다"


@dataclass(frozen=True, slots=True)
class _AlwaysFalseMarker(Condition):
    """
    이미 확정된 위반을 요구 목록에 실어 나르기 위한 표식.

    판정은 요구를 만들 때 끝났고 (``target.player == action.actor`` 등),
    이것은 그 결과를 같은 통로로 보내기 위한 것이다.
    """

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.FALSE

    def canonical_state(self) -> tuple:
        return ("always_false_marker",)

    def to_dict(self) -> dict:
        return {"kind": "always_false_marker"}

    def describe_ko(self) -> str:
        return "이미 확정된 위반"
