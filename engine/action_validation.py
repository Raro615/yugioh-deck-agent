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
    UnimplementedRule,
    ZoneHasFreeSlot,
)
from engine.condition.model import _resolve_definition
from engine.game_state_view import CardDefinitionView, CardView, GameStateView
from engine.summon_rules import SummonAssessment, assess_normal_summon
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.ids import InstanceId
from engine.vocabulary import Phase, Position, Zone

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
    PlayerActionKind.SPECIAL_SUMMON: "special-summon-condition (카드마다 다르다)",
    PlayerActionKind.ACTIVATE_CARD: "activation-timing (Phase 2-C/2-F)",
    PlayerActionKind.CHANGE_POSITION: "position-change-legality (Phase 2-G)",
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
    {
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.ATTACK,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        # Phase 3-E-3 — **통상 마법의 발동 하나**다. 넓게 푼 것이 아니라,
        # ``_NormalSpellActivation`` 이 그 밖의 모든 카드를 UNKNOWN 으로
        # 남기므로 여기 올려도 아무것도 새로 허가되지 않는다.
        PlayerActionKind.ACTIVATE_EFFECT,
    }
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


#: 특수 소환 조건을 읽는 계층이 없다는 사실. ``missing_rule`` 에 그대로 실린다.
SPECIAL_SUMMON_CONDITION_RULE = "special-summon-condition (카드마다 다르다)"


def _special_summon(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    """
    특수 소환. **이 목록을 전부 통과해도 허가가 나지 않는다.**

    "이 카드를 특수 소환할 수 있는가" 는 카드마다 다르고 (융합 · 싱크로 ·
    "패에서 특수 소환할 수 있다" · "1턴에 1번" · 소생 제한 …), 그 조건을 읽는
    계층이 아직 없다. 그래서 마지막 요구가 언제나 ``UNKNOWN`` 이다 —
    **모르는 것을 허가로 바꾸지 않는다.**

    페이즈 제약도 넣지 않았다. 특수 소환은 메인 페이즈에만 일어나는 것이
    아니고 (상대 턴의 유발즉시 효과로도 나온다), 언제 되는지는 그 효과가
    정한다. 지금 메인 페이즈로 못박으면 틀린 채로 굳는다.

    일반 소환과 달리 **소환권을 보지 않는다** — 특수 소환은 그 권리를 쓰지
    않는다.
    """
    # 순환 import 를 피하려고 여기서 읽는다: special_summon → summon →
    # action_execution → action_validation 으로 돌아온다.
    from engine.special_summon import SPECIAL_SUMMON_FROM_ZONES

    requirements = [
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
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
    ]

    # 어느 자리에서 나오는가. **여기 없는 자리는 "안 된다" 가 아니라
    # "아직 옮기지 못했다" 다** — 덱 · 제외 · 엑스트라 덱에서 나오는 특수
    # 소환은 실제로 있고, 그것을 ``INVALID`` 로 적으면 거짓이 된다.
    card = validator.view.find(action.source) if action.source is not None else None
    if card is not None and card.zone not in SPECIAL_SUMMON_FROM_ZONES:
        requirements.append(
            Requirement(
                UnimplementedRule(
                    f"special summon from {card.zone.value} (Phase 2-T 범위 밖)"
                ),
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{card.zone.value} 에서 나오는 특수 소환은 아직 옮기지 "
                "않았습니다.",
            )
        )

    requirements.append(
        Requirement(
            UnimplementedRule(SPECIAL_SUMMON_CONDITION_RULE),
            ValidationCode.RULE_NOT_IMPLEMENTED,
            "이 카드를 특수 소환할 수 있는지 판정할 규칙이 없습니다.",
        )
    )
    return tuple(requirements)


def _set_monster(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    """
    몬스터 세트. **이 목록을 전부 통과하면 허가가 난다** (``_COMPLETE_RULES``).

    공식 규칙 (``rules`` 계층):

    - RULE-TERM-021 — "For Monster Cards, playing it in face-down Defense
      Position is called a Set."
    - RULE-SUMMON-010 — "To play a Monster Card from your hand in face-down
      Defense Position is called a Normal Set... **You can do one of these
      once per turn.**"
    - RULE-SUMMON-011 — 레벨 5 이상은 제물이 필요하다. "If you Tribute
      Summon in face-down Defense Position, it is called a Tribute Set" —
      **제물 규칙은 소환과 세트에 똑같이 걸린다.**
    - RULE-TURN-004 · RULE-TURN-006 — "you can Normal Summon, **Set**, ..."
      는 메인 페이즈의 행위다.

    Phase 3-E-2 전까지 ``SET_MONSTER`` 는 :func:`_summon_like` 하나만 썼고
    (턴 플레이어 · 컨트롤러 · 패 · 몬스터 · 빈 칸) ``UNKNOWN`` 에 머물렀다.
    그래서 **페이즈 검사가 없다는 사실이 가려져 있었다** (STRUCTURAL-114).
    ``_COMPLETE_RULES`` 로 올리기 **전에** 셋을 먼저 채운다 — 올리고 나서
    채우면 그 사이에 메인 페이즈 밖 세트가 허가된다.

    소환권은 :class:`_NormalSummonRightAvailable` 을 **그대로** 쓴다. 일반
    소환과 세트가 같은 권리를 나눠 쓰므로 (RULE-SUMMON-009) 다른 조건을
    두면 한 턴에 둘 다 할 수 있게 된다.

    절차 판정도 :class:`_NormalSummonProcedure` 를 그대로 쓴다 — 제물 ·
    엑스트라 덱 · 의식 · 토큰 판정이 세트에도 똑같이 걸린다
    (RULE-SUMMON-011).
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
            "이번 턴의 일반 소환권을 이미 썼습니다 (세트와 소환은 같은 권리입니다).",
        ),
        Requirement(
            _NormalSummonProcedure(action.source),
            ValidationCode.CANNOT_NORMAL_SUMMON,
            "이 카드는 패에서 세트할 수 없습니다.",
        ),
    )


def _set_spell_trap(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    """
    마법 · 함정 세트.

    공식 규칙:

    - RULE-TERM-021 — "Playing a card face-down is called a Set."
    - RULE-TURN-004 · RULE-TURN-006 — "...and **Set Spell and Trap Cards**"
      는 메인 페이즈의 행위다.

    **소환권을 쓰지 않는다.** RULE-SUMMON-009 · 010 의 "once per turn" 은
    몬스터의 일반 소환/세트에만 걸리고, 마법 · 함정 세트는 칸이 있는 한
    몇 장이든 놓을 수 있다.

    Phase 3-E-2 에서 더한 것은 **페이즈 하나**다 (STRUCTURAL-114).
    """
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
        Requirement(
            PhaseIs(MAIN_PHASES),
            ValidationCode.WRONG_PHASE,
            "메인 페이즈가 아닙니다.",
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
    """
    공격 선언. **이 목록을 전부 통과하면 허가가 난다** (``_COMPLETE_RULES``).

    공식 규칙 (``rules`` 계층, ``sd-rulebook-en-v10``):

    - RULE-BATTLE-001 — 선공은 첫 턴에 배틀 페이즈를 진행할 수 없다.
    - RULE-BATTLE-002 — "Each face-up Attack Position monster you control is
      allowed 1 attack per turn." 공격자는 **앞면 공격 표시**여야 하고,
      **카드마다** 턴에 한 번이다.
    - RULE-BATTLE-013 — "If there are no monsters on your opponent's side of
      the field, you can attack directly." 상대 몬스터가 있으면 다이렉트
      어택을 할 수 없다.

    Phase 3-E-1-B 에서 ``_COMPLETE_RULES`` 로 옮겼다. 그 전까지는 요구를 전부
    통과해도 ``UNKNOWN`` 이었다 — 공격 가능 여부를 끝까지 볼 계층이 없었기
    때문이다. 이제 넷이 채워졌다: 표시 형식 · 공격권 · 다이렉트 조건 · 첫 턴.

    **아직 보지 않는 것**은 전투 예외 규칙이다 (공격 무효 · 공격 대상 변경 ·
    공격 횟수를 늘리는 효과 · 공격 제약을 걸는 효과). 그것들은 카드 효과가
    만드는 것이고, 지금 발동되는 효과가 없으므로 판정할 대상도 없다.
    """
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
            _BattlePhaseAllowedThisTurn(),
            ValidationCode.WRONG_PHASE,
            "선공은 첫 턴에 배틀 페이즈를 진행할 수 없습니다.",
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
        Requirement(
            _AttackPositionMonster(action.source),
            ValidationCode.SOURCE_WRONG_CARD_TYPE,
            "앞면 공격 표시 몬스터만 공격할 수 있습니다.",
        ),
        Requirement(
            _AttackAvailable(action.source),
            ValidationCode.NORMAL_SUMMON_ALREADY_USED,
            "이 몬스터는 이번 턴에 이미 공격했습니다.",
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
        else:
            requirements.append(
                Requirement(
                    _OpponentHasNoMonsters(),
                    ValidationCode.TARGET_NOT_OPPONENT,
                    "상대 필드에 몬스터가 있으면 다이렉트 어택을 할 수 없습니다.",
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


def _activate_effect(
    validator: ActionValidator, action: PlayerAction
) -> tuple[Requirement, ...]:
    """
    **효과** 발동 (Phase 3-E-3). ``_activate`` 에서 갈라 나왔다.

    왜 갈라야 했는가: ``ACTIVATE_CARD`` 와 ``ACTIVATE_EFFECT`` 는 뜻이 다른데
    (``engine/action.py`` 의 설명) 요구 하나를 공유하고 있었다
    (STRUCTURAL-119). 그리고 발동 계층(:class:`~engine.activation.
    EffectActivator`)은 ``ACTIVATE_EFFECT`` **만** 받으므로, 허가를 낼 수 있는
    쪽도 그쪽 하나다.

    요구가 **두 갈래**인 것이 이 함수의 핵심이다
    -------------------------------------------
    언제나 묻는 것은 둘뿐이다 — 자기가 쥔 카드인가, 그리고 **이번 Phase 가
    판정할 수 있는 발동인가**. 범위 안(패의 통상 마법)일 때만 좁은 요구를
    더한다.

    범위 밖에 좁은 요구를 **더하지 않는 이유**가 중요하다. 예를 들어 함정은
    상대 턴에 발동하는 것이 정상이므로 (RULE-SPELLTRAP-008), 거기에
    ``IsTurnPlayer`` 를 걸면 ``NOT_TURN_PLAYER`` 라는 ``INVALID`` 가 나온다 —
    **규칙이 금지한다**는 거짓말이다. 필드의 몬스터 효과에
    ``CardIsInZone(HAND)`` 를 거는 것도 같은 거짓말이다. 모르는 것은
    ``UNKNOWN`` 으로 남겨야 하고, 그래서 좁은 요구는 범위 안에서만 쓴다.

    범위 안에서 더하는 셋의 공식 근거:

    - RULE-SPELLTRAP-001 — "Spell Cards can normally be activated **only
      during your Main Phase**"
    - RULE-CHAIN-009 — "The turn player always starts with Priority"
    - RULE-SPELLTRAP-002 — "announce its activation ... **placing it face-up
      on the field**" → 마법 & 함정 존에 빈 칸이 필요하다

    넣지 **않은** 것: 사용 횟수. RULE-TURN-004 가 "activate ... **as many
    times as you want** during this phase" 라고 적는다.

    **체인이 비었는가는 여기서 보지 않는다.** 체인은 ``GameState`` 밖에 살고
    검증기는 관측만 읽는다 (ADR-007). 그 요구는 체인을 들고 있는
    :class:`~engine.duel.Duel` 이 본다 (RULE-CHAIN-004).
    """
    scope = _NormalSpellActivation(action.source)
    always = (
        Requirement(
            ControllerIs(PlayerRef.CONTROLLER, action.source),
            ValidationCode.SOURCE_NOT_CONTROLLED,
            "자신이 쥐고 있는 카드가 아닙니다.",
        ),
        Requirement(
            scope,
            # 이 조건은 ``FALSE`` 를 **돌려주지 않는다** (범위 밖은 전부
            # ``UNKNOWN``). 그래서 이 코드는 닿지 않지만, 닿는다면 그 이유는
            # 규칙 계층이 없는 것이므로 새 코드를 만들지 않고 이것을 쓴다.
            ValidationCode.RULE_NOT_IMPLEMENTED,
            "이 카드의 발동 타이밍을 아직 판정할 수 없습니다.",
        ),
    )
    context = validator.context_for(action)
    if _activation_out_of_scope(validator.view, context, action.source):
        return always

    quick_play = activation_is_quick_play(validator.view, context, action.source)

    # **자기 턴인가는 둘 다 묻는다.** 패에 있는 속공 마법도 상대 턴에는
    # 발동할 수 없다 — ``RULE-SPELLTRAP-007`` 이 상대 턴의 발동에 "if you
    # **Set** the card face-down first" 를 요구하므로, 패에 있는 동안은
    # 상대 턴에 쓸 수 없다. 그래서 이것은 ``UNKNOWN`` 이 아니라 **규칙이
    # 금지하는 것**이다.
    set_card = activation_is_set_card(validator.view, context, action.source)
    requirements = [
        Requirement(
            IsTurnPlayer(PlayerRef.CONTROLLER),
            ValidationCode.NOT_TURN_PLAYER,
            # **이유가 둘이다.** 패의 마법은 "세트가 앞서야 한다" 이지만,
            # 세트해 둔 통상 마법은 세트했어도 **상대 턴에 쓸 수 없다** —
            # RULE-SPELLTRAP-012 가 "Setting them does not allow you to use
            # them on your opponent's turn" 이라고 못 박는다. 같은 문장으로
            # 적으면 뒤쪽에 거짓을 말한다.
            "자신의 턴이 아닙니다 (세트한 통상 마법도 자기 메인 페이즈에만 "
            "발동합니다 — 세트는 상대 턴의 발동을 허락하지 않습니다)."
            if set_card
            else "자신의 턴이 아닙니다 (패의 마법은 자기 턴에 발동합니다 — "
            "상대 턴에 쓰려면 세트가 앞서야 합니다).",
        )
    ]

    # **페이즈는 둘이 다르다.**
    #
    #   통상 마법   RULE-SPELLTRAP-001 — "only during your Main Phase"
    #   속공 마법   RULE-SPELLTRAP-007 — "during **any Phase of your turn**,
    #               not just your Main Phase"
    #
    # 그래서 속공 마법에는 페이즈 요구를 **걸지 않는다.** 걸면 "규칙이
    # 금지한다" 는 거짓이 된다.
    if not quick_play:
        requirements.append(
            Requirement(
                PhaseIs(MAIN_PHASES),
                ValidationCode.WRONG_PHASE,
                "메인 페이즈가 아닙니다.",
            )
        )

    # 놓을 자리는 **패에서 발동할 때만** 필요하다 — 속공 마법도 마법이므로
    # 앞면으로 놓고 해결 뒤 묘지로 간다 (RULE-SPELLTRAP-002).
    #
    # **세트해 둔 마법에는 걸지 않는다** (Phase 3-E-14). 그 카드는 이미 제
    # 칸에 있고 발동은 그 자리에서 앞면으로 돌리는 것이므로 (``
    # NormalSpellPlacement.reveal``), 새 칸이 필요하지 않다. 걸어 두면 마법 &
    # 함정 존이 꽉 찬 판에서 **자기 칸에 있는 카드를** 발동할 수 없게 되고,
    # 그것은 규칙이 금지하지 않는 것을 금지한다는 거짓이다.
    if not set_card:
        requirements.append(
            Requirement(
                ZoneHasFreeSlot(PlayerRef.CONTROLLER, Zone.SZONE),
                ValidationCode.ZONE_FULL,
                "마법 & 함정 존에 빈 칸이 없습니다 (발동한 마법을 놓을 자리가 "
                "필요합니다).",
            )
        )
    return always + tuple(requirements)


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
    PlayerActionKind.SPECIAL_SUMMON: _special_summon,
    PlayerActionKind.SET_MONSTER: _set_monster,
    PlayerActionKind.SET_SPELL_TRAP: _set_spell_trap,
    PlayerActionKind.CHANGE_POSITION: _change_position,
    PlayerActionKind.ATTACK: _attack,
    PlayerActionKind.ACTIVATE_CARD: _activate,
    PlayerActionKind.ACTIVATE_EFFECT: _activate_effect,
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
class _BattlePhaseAllowedThisTurn(Condition):
    """
    이번 턴에 배틀 페이즈를 **진행할 수 있는가** (RULE-BATTLE-001).

        "Remember, the player who goes first cannot conduct a Battle Phase
         in their very first turn."

    1턴은 선공의 첫 턴이므로 공격할 수 없다. 페이즈 자체는 지나가지만
    (턴 진행 계층의 일이다) 공격 선언은 적법하지 않다.
    """

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.from_bool(view.turn_number > 1)

    def canonical_state(self) -> tuple:
        return ("battle_phase_allowed_this_turn",)

    def to_dict(self) -> dict:
        return {"kind": "battle_phase_allowed_this_turn"}

    def describe_ko(self) -> str:
        return "선공 첫 턴이 아니다 (배틀 페이즈를 진행할 수 있다)"


@dataclass(frozen=True, slots=True)
class _AttackPositionMonster(Condition):
    """
    공격할 수 있는 표시 형식인가 (RULE-BATTLE-002).

        "Each **face-up Attack Position** monster you control is allowed
         1 attack per turn."

    뒷면도, 수비 표시도 공격하지 않는다. 관측에 보이지 않으면 ``UNKNOWN``
    이다 — 자기 몬스터 존은 언제나 보이므로 실제로는 나오지 않지만,
    **보이지 않는 것을 FALSE 로 접지 않는다.**
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None or card.position is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(
            card.face_up and card.position is Position.FACEUP_ATTACK
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        card = view.find(target)
        if card is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        if card.position is None:
            return (f"{target} 의 표시 형식을 알 수 없음",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "attack_position_monster",
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "attack_position_monster"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 앞면 공격 표시"


@dataclass(frozen=True, slots=True)
class _AttackAvailable(Condition):
    """
    이 몬스터의 **이번 턴 공격권**이 남아 있는가 (RULE-BATTLE-002).

    소환권과 달리 **카드마다** 하나다. 그래서 플레이어별 기록이 아니라
    :attr:`~engine.game_state_view.GameStateView.attacks_used` 를 읽는다 —
    같은 이름의 두 몬스터가 서로 다른 공격권을 갖는다.

    공격은 공개된 자리에서 선언되므로 ``UNKNOWN`` 이 나오지 않는다. 기록이
    없으면 **아직 공격하지 않은 것**이고, 그것은 사실이지 모름이 아니다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(view.attacks_by(target) == 0)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "attack_available",
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "attack_available"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 이번 턴에 아직 공격하지 않았다"


@dataclass(frozen=True, slots=True)
class _OpponentHasNoMonsters(Condition):
    """
    상대 필드에 몬스터가 **없는가** (RULE-BATTLE-013).

        "If there are no monsters on your opponent's side of the field,
         you can attack directly."

    몬스터 존은 공개된 자리이고 **장수는 가려진 자리에서도 공개된 사실**
    이므로 ``UNKNOWN`` 이 나오지 않는다.
    """

    def evaluate(self, view, context) -> ConditionResult:
        opponent = view.player(1 - context.player)
        occupied = sum(
            opponent.zone(zone).size for zone in (Zone.MZONE, Zone.EMZONE)
        )
        return ConditionResult.from_bool(occupied == 0)

    def canonical_state(self) -> tuple:
        return ("opponent_has_no_monsters",)

    def to_dict(self) -> dict:
        return {"kind": "opponent_has_no_monsters"}

    def describe_ko(self) -> str:
        return "상대 필드에 몬스터가 없다"


#: 통상 마법이 **아니게** 만드는 종류 이름과, 그때 없는 규칙 계층.
#: 이름은 ``core.constants.TYPE_NAMES`` 에서 오는 것을 그대로 쓴다.
_OUT_OF_SCOPE_TYPES: tuple[tuple[str, str], ...] = (
    ("TRAP", "trap-activation-timing (세트가 앞서고 세트한 턴에는 못 쓴다 — RULE-SPELLTRAP-009)"),
    ("CONTINUOUS", "continuous-card-lifecycle (발동 뒤 필드에 남는다 — RULE-SPELLTRAP-004 · 010)"),
    ("EQUIP", "equip-lifecycle (장착 대상과 함께 필드에 남는다 — RULE-SPELLTRAP-005)"),
    ("FIELD", "field-zone-lifecycle (필드 존에 남는다 — RULE-SPELLTRAP-006)"),
    ("RITUAL", "ritual-summon-procedure (의식 소환이 앞선다 — RULE-SPELLTRAP-003)"),
    ("COUNTER", "counter-trap-timing (다른 발동에 응답한다 — RULE-SPELLTRAP-011)"),
)


#: 세트된 속공 마법 · 함정의 발동에 **없는** 규칙 계층.
#:
#: ``RULE-SPELLTRAP-007`` 의 두 번째 절이 요구한다 — "You can also activate
#: them during your opponent's turn **if you Set the card face-down first**,
#: but then you **cannot activate the card in the same turn you Set it**."
#:
#: 그 "세트한 턴" 을 세는 자리가 엔진에 없다 —
#: ``engine/activation_timing.py`` 의 ``UNRESOLVED_TIMING_RULES`` 가 "세트한
#: 턴의 함정 발동 제약" 을 **보지 않는다**고 적어 두었다. 세지 못하는 제약을
#: 통과시키면 "세트한 턴에 발동할 수 있다" 는 거짓이 되므로, 세트된 카드의
#: 발동은 ``UNKNOWN`` 으로 남긴다.
SET_ACTIVATION_MISSING = (
    "set-card-activation-timing (세트한 턴에는 발동할 수 없다 — "
    "RULE-SPELLTRAP-007 · 009. 세트한 턴을 세는 자리가 없다)"
)


def activation_is_quick_play(view, context, instance) -> bool:
    """
    이 발동이 **패에 있는 속공 마법**인가 (Phase 3-E-12).

    범위 안의 발동 중 속공 마법만 ``PhaseIs(MAIN_PHASES)`` 를 **지지 않는다**
    — ``RULE-SPELLTRAP-007`` 이 "can be activated during **any Phase of your
    turn**, not just your Main Phase" 라고 적기 때문이다.
    """
    definition, _ = _resolve_definition(view, context, instance)
    if definition is None or not definition.is_spell:
        return False
    return "QUICKPLAY" in set(definition.type_names)


def activation_is_set_card(view, context, instance) -> bool:
    """
    이 발동이 **세트해 둔 카드**의 발동인가 (Phase 3-E-14).

    범위 안의 발동 중 이쪽만 ``ZoneHasFreeSlot(SZONE)`` 을 **지지 않는다** —
    카드가 이미 그 존에 있기 때문이다.
    """
    definition, _ = _resolve_definition(view, context, instance)
    if definition is None:
        return False
    target = instance if instance is not None else context.source
    card = view.find(target) if target is not None else None
    return _is_set_normal_spell(card, definition, set(definition.type_names))


def _activation_out_of_scope(view, context, instance) -> tuple[tuple[str, str], ...]:
    """
    이 발동을 **이번 Phase 의 범위 밖으로** 만드는 (사실, 없는 규칙) 들.

    비어 있으면 범위 안이다 — 패에 있는 통상 마법 하나.

    왜 "패에 있는가" 까지 여기서 보는가: 필드에서의 발동(몬스터의 기동 효과 ·
    세트한 마법 · 함정)은 **실제 규칙에서 적법하다.** 그것을
    ``SOURCE_WRONG_ZONE`` 같은 ``INVALID`` 로 적으면 "규칙이 금지한다" 는
    거짓을 말하게 된다. 모르는 것은 ``UNKNOWN`` 이어야 하고, 그래서 자리도
    범위 조건 안에 둔다.
    """
    definition, why = _resolve_definition(view, context, instance)
    if definition is None:
        # "왜 못 읽었는가" 를 그대로 전한다 — 안 보인다 · 뒷면이다 · 정의가
        # 없다는 **서로 다른 사실**이고, 조건 계층이 이미 구분해 두었다.
        return ((why, ""),)
    if not definition.is_spell:
        return (
            (
                "통상 마법이 아니다",
                "non-spell-activation-timing (함정 · 몬스터 효과의 발동 타이밍)",
            ),
        )
    names = set(definition.type_names)
    out = tuple(
        (f"{name} 카드의 발동 타이밍을 아직 판정하지 않는다", rule)
        for name, rule in _OUT_OF_SCOPE_TYPES
        if name in names
    )
    if out:
        return out
    target = instance if instance is not None else context.source
    card = view.find(target) if target is not None else None
    if card is None or card.zone is not Zone.HAND:
        where = card.zone.value if card is not None else "?"
        # **세트된 속공 마법은 다른 이유로 범위 밖이다** (Phase 3-E-12).
        # 필드에서의 발동 자체를 모르는 것이 아니라, ``RULE-SPELLTRAP-007``
        # 이 요구하는 "세트한 턴" 제약을 셀 자리가 없다.
        if "QUICKPLAY" in names and card is not None and card.zone is Zone.SZONE:
            return (("세트한 속공 마법의 발동이다", SET_ACTIVATION_MISSING),)
        # **세트된 통상 마법은 범위 안이다** (Phase 3-E-14).
        #
        #     RULE-SPELLTRAP-012 — "Spell Cards can be activated during the
        #     Main Phases **even in the same turn that you Set them** (except
        #     for Quick-Play Spell Cards). Setting them does not allow you to
        #     use them on your opponent's turn; they still can only be
        #     activated during your Main Phase."
        #
        # 그래서 이쪽은 **세트한 턴을 셀 필요가 없다.** 조항이 같은 턴을 명시
        # 적으로 허락하고, 상대 턴은 명시적으로 금지한다 — 패에서 발동하는
        # 통상 마법과 **판정에 필요한 정보가 똑같다.** 속공 마법과 함정이
        # ``UNKNOWN`` 으로 남는 것은 그 둘만 "세트한 턴" 을 요구하기 때문이다
        # (RULE-SPELLTRAP-007 · 009).
        if _is_set_normal_spell(card, definition, names):
            return ()
        return (
            (
                f"패가 아니라 {where} 에서의 발동이다",
                "on-field-activation-timing (필드의 카드가 자기 효과를 "
                "발동하는 타이밍)",
            ),
        )
    return ()


#: :func:`_is_set_normal_spell` 이 **받지 않는** 아이콘들.
#:
#: ``RULE-SPELLTRAP-012`` 가 괄호로 하나를 직접 뺀다 — "(**except for
#: Quick-Play Spell Cards**)". 나머지는 발동 뒤 필드에 남거나 절차가 앞서므로
#: (RULE-SPELLTRAP-003 · 004 · 005 · 006) 해결 뒤 묘지로 가는 이 경로와 모양이
#: 다르다.
_NOT_A_SET_NORMAL_SPELL: frozenset[str] = frozenset(
    {"QUICKPLAY", "CONTINUOUS", "EQUIP", "FIELD", "RITUAL", "COUNTER", "TRAP"}
)


def _is_set_normal_spell(card, definition, names) -> bool:
    """
    **세트해 둔 통상 마법**인가 (Phase 3-E-14 · RULE-SPELLTRAP-012).

    넷을 모두 만족해야 한다. 하나라도 빠지면 **다른 조항**이 걸리는 자리다.

    - 마법 & 함정 존에 있다
    - **뒷면**이다 (앞면이면 이미 발동했거나 지속 · 필드 마법이다)
    - 마법이다
    - 아이콘이 :data:`_NOT_A_SET_NORMAL_SPELL` 에 없다

    **마지막 줄을 앞선 관문에 맡기지 않는다.** ``_activation_out_of_scope`` 가
    함정과 지속 · 장착 · 필드 · 의식을 이미 걸러내므로 여기서 다시 보는 것은
    결과를 바꾸지 않는다. 그래도 적어 두는 이유: 이 술어가 "세트된 카드" 의
    **정의**이고, 느슨해지면 ``ZoneHasFreeSlot`` 면제와 ``IsTurnPlayer``
    문장이 **엉뚱한 카드에** 붙는다. 그때 나오는 것은 틀린 이유 문장이고,
    그것은 규칙을 거짓으로 적는 것이다.

    실제로 느슨했다 — 처음 적을 때 속공 마법을 걸러내지 않아 세트된 속공
    마법에도 ``True`` 를 냈다. 앞선 관문이 가려서 어떤 테스트도 그것을 잡지
    못했고, ``test_15`` 가 이 술어를 직접 재서 잡았다.
    """
    return (
        card is not None
        and card.zone is Zone.SZONE
        and not card.face_up
        and definition is not None
        and definition.is_spell
        and not (set(names) & _NOT_A_SET_NORMAL_SPELL)
    )


@dataclass(frozen=True, slots=True)
class _NormalSpellActivation(Condition):
    """
    이 카드가 **이번 Phase 가 판정할 수 있는 발동**인가 (Phase 3-E-3).

    ``TRUE`` 는 **통상 마법 하나**다. 그 밖의 모든 카드는 ``UNKNOWN`` 이고,
    ``FALSE`` 는 **하나도 없다** — 실제 규칙에서는 전부 발동할 수 있고, 없는
    것은 그 타이밍을 볼 규칙 계층뿐이다 (``UNRESOLVED_TIMING_RULES``).

    왜 통상 마법만인가 — 공식 조항이 나머지를 **다른 타이밍**으로 적는다.

    ==========================  =============================================
    통상 마법                    RULE-SPELLTRAP-001 · 002 — 자기 메인 페이즈,
                                 앞면으로 놓고 해결 뒤 묘지. **이번 범위**
    속공 마법                    RULE-SPELLTRAP-007 — 자기 턴의 **아무 페이즈**,
                                 세트하면 상대 턴에도. 세트한 턴 제약까지 있다
    함정                         RULE-SPELLTRAP-009 — 세트가 **앞서야** 하고
                                 세트한 턴에는 발동할 수 없다
    지속 · 장착 · 필드 마법       RULE-SPELLTRAP-004 · 005 · 006 — 발동 뒤
                                 필드에 **남는다.** 해결 뒤 묘지로 가지 않는다
    의식 마법                    RULE-SPELLTRAP-003 — 의식 소환 절차가 앞선다
    몬스터 효과                  기동/유발/플립/유발즉시 분류가 이 엔진의 카드
                                 정의에 없다 (``activation_timing`` 모듈 설명)
    ==========================  =============================================

    **``FALSE`` 로 적지 않는 것이 이 조건의 핵심이다.** ``FALSE`` 는 "규칙이
    금지한다" 이고, 위 다섯 줄은 전부 "규칙은 허락하는데 우리가 모른다" 다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        out = _activation_out_of_scope(view, context, self.instance)
        return ConditionResult.TRUE if not out else ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return tuple(
            why for why, _ in _activation_out_of_scope(view, context, self.instance)
        )

    def missing_rules(self, view, context) -> tuple[str, ...]:
        return tuple(
            rule
            for _, rule in _activation_out_of_scope(view, context, self.instance)
            if rule
        )

    def canonical_state(self) -> tuple:
        return (
            "normal_spell_activation",
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "normal_spell_activation"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        return "통상 마법의 발동이다 (이번 Phase 가 판정할 수 있는 범위)"


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
