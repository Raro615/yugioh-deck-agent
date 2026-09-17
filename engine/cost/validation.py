"""
비용과 선택의 검증.

**치르지 않는다. 고르지 않는다.** 두 가지만 답한다.

- :class:`CostValidator` — 이 비용을 지금 치를 수 있는가
- :class:`SelectionValidator` — 이 선택이 그 요구에 맞는가

판정은 :class:`~engine.validation.ValidationResult` 로, Action 검증과 같은
어휘를 쓴다. ``bool`` 하나를 돌려주지 않는다 — 그러면 "모른다" 를 담을 자리가
없어진다.

검증 중에 일어나지 않는 것
--------------------------
릴리스 · 묘지로 보내기 · 라이프 감소 · 카운터 제거 · ``UseRegistry`` 기록.
``state_hash()`` 가 그대로인지 테스트가 확인한다.
"""

from __future__ import annotations

from engine.condition import ConditionContext
from engine.cost.choice import CandidateSet, ChoiceSpec, Selection
from engine.cost.model import CardCost, Cost, CostGroup, LifeCost, UnimplementedCost
from engine.cost.resolver import CandidateResolver
from engine.game_state_view import GameStateView
from engine.validation import ActionValidity, ValidationCode, ValidationResult


class CostValidator:
    """
    비용을 치를 수 있는지 본다. **구체적으로 무엇을 낼지는 고르지 않는다** —
    그것은 :class:`~engine.cost.choice.ChoiceSpec` 과 선택의 몫이다.
    """

    __slots__ = ("_view", "_resolver")

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "CostValidator 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 검증이 판을 바꿀 수 있게 됩니다."
            )
        self._view = view
        self._resolver = CandidateResolver(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def resolver(self) -> CandidateResolver:
        return self._resolver

    # ------------------------------------------------------------------
    def validate(self, cost: Cost, context: ConditionContext) -> ValidationResult:
        """비용 하나. ``VALID`` / ``INVALID`` / ``UNKNOWN``."""
        if isinstance(cost, UnimplementedCost):
            return ValidationResult.unknown(
                ValidationCode.COST_NOT_IMPLEMENTED,
                f"이 비용을 표현할 수 없습니다: {cost.rule}",
                missing_rule=cost.rule,
            )
        if isinstance(cost, LifeCost):
            return self._validate_life(cost, context)
        if isinstance(cost, CardCost):
            return self._validate_card(cost, context)
        return ValidationResult.unknown(
            ValidationCode.COST_NOT_IMPLEMENTED,
            f"알 수 없는 비용 종류입니다: {type(cost).__name__}",
        )

    def validate_group(
        self, group: CostGroup, context: ConditionContext
    ) -> ValidationResult:
        """
        묶음 전체. **AND 관계**이므로 하나라도 못 치르면 못 치른다.

        ``INVALID`` 가 ``UNKNOWN`` 을 이긴다 — 하나가 확실히 불가능하면
        나머지를 몰라도 전체가 불가능하다. 조건 계층의 삼치 논리와 같은
        태도다.
        """
        if group.is_free:
            return ValidationResult.valid("치를 비용이 없습니다.")
        pending: list[ValidationResult] = []
        for cost in group.costs:
            result = self.validate(cost, context)
            if result.validity is ActionValidity.INVALID:
                return result
            if result.validity is ActionValidity.UNKNOWN:
                pending.append(result)
        if pending:
            first = pending[0]
            return ValidationResult.unknown(
                first.code,
                first.reason,
                missing_rule=first.missing_rule,
                notes=tuple(r.reason for r in pending),
            )
        return ValidationResult.valid("모든 비용을 치를 수 있습니다.")

    # ------------------------------------------------------------------
    def _validate_life(
        self, cost: LifeCost, context: ConditionContext
    ) -> ValidationResult:
        """
        라이프는 양쪽 모두 공개다. 그래서 언제나 확정된다.

        **깎지 않는다.** 남은 값과 비교만 한다.
        """
        player = self._view.player(cost.who.resolve(context))
        if player.life_points < cost.amount:
            return ValidationResult.invalid(
                ValidationCode.INSUFFICIENT_LIFE,
                f"라이프가 {player.life_points} 뿐이라 {cost.amount} 를 "
                "지불할 수 없습니다.",
            )
        return ValidationResult.valid(
            f"라이프 {player.life_points} 중 {cost.amount} 를 지불할 수 있습니다."
        )

    def _validate_card(
        self, cost: CardCost, context: ConditionContext
    ) -> ValidationResult:
        spec = cost.choice_spec()
        candidates = self._resolver.resolve(spec, context)
        return self._judge_candidates(spec, candidates, cost.describe_ko())

    def _judge_candidates(
        self, spec: ChoiceSpec, candidates: CandidateSet, what: str
    ) -> ValidationResult:
        """
        후보 수로 판정한다.

        확실한 후보만으로 최소 수량을 채울 수 있으면 ``VALID``.
        미확정까지 다 세어도 모자라면 ``INVALID`` — 미확정이 전부 후보라고
        쳐도 안 되므로 확실하다.
        그 사이면 ``UNKNOWN``.
        """
        if spec.minimum == 0:
            return ValidationResult.valid(f"{what}: 고르지 않아도 됩니다.")
        if candidates.certain_count >= spec.minimum:
            return ValidationResult.valid(
                f"{what}: 후보 {candidates.certain_count}장으로 충분합니다."
            )
        if candidates.possible_count < spec.minimum:
            return ValidationResult.invalid(
                ValidationCode.NO_CANDIDATES,
                f"{what}: 후보가 {candidates.possible_count}장뿐이라 "
                f"{spec.minimum}장을 채울 수 없습니다.",
            )
        return ValidationResult.unknown(
            ValidationCode.INFORMATION_UNAVAILABLE,
            f"{what}: 확실한 후보가 {candidates.certain_count}장이고 "
            f"{len(candidates.undecided)}장은 판정할 수 없습니다.",
            notes=candidates.reasons,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<CostValidator {self._view}>"


class SelectionValidator:
    """
    고른 것이 요구에 맞는지 본다. **고르지 않는다.**

    수량 · 중복 · 후보 소속만 본다. "이 카드가 효과 텍스트상 대상이 될 수
    있는가" 는 대상 지정 규칙이고, 그 계층은 아직 없다.
    """

    __slots__ = ("_view", "_resolver")

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError("SelectionValidator 는 GameStateView 만 받습니다.")
        self._view = view
        self._resolver = CandidateResolver(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    def validate(
        self,
        spec: ChoiceSpec,
        selection: Selection,
        context: ConditionContext,
        candidates: CandidateSet | None = None,
    ) -> ValidationResult:
        """
        ``candidates`` 를 주면 그것을 쓰고, 없으면 관측에서 다시 찾는다.
        같은 관측이면 두 결과가 같다.
        """
        chosen = selection.chosen

        # --- 수량 -----------------------------------------------------
        if len(chosen) < spec.minimum:
            return ValidationResult.invalid(
                ValidationCode.TOO_FEW_SELECTED,
                f"{spec.minimum}장을 골라야 하는데 {len(chosen)}장을 골랐습니다.",
            )
        if len(chosen) > spec.maximum:
            return ValidationResult.invalid(
                ValidationCode.TOO_MANY_SELECTED,
                f"최대 {spec.maximum}장인데 {len(chosen)}장을 골랐습니다.",
            )

        # --- 중복 -----------------------------------------------------
        if not spec.allow_duplicates and selection.has_duplicates:
            return ValidationResult.invalid(
                ValidationCode.DUPLICATE_SELECTION,
                "같은 카드를 두 번 골랐습니다.",
            )

        if not chosen:
            return ValidationResult.valid("고른 것이 없고, 그래도 됩니다.")

        # --- 후보 소속 -------------------------------------------------
        pool = (
            candidates
            if candidates is not None
            else self._resolver.resolve(spec, context)
        )
        for instance in chosen:
            if instance in pool.eligible:
                continue
            if instance in pool.undecided:
                return ValidationResult.unknown(
                    ValidationCode.INFORMATION_UNAVAILABLE,
                    f"{instance} 가 후보 조건을 만족하는지 판정할 수 없습니다.",
                    notes=pool.reasons,
                )
            if self._view.find(instance) is None:
                return ValidationResult.unknown(
                    ValidationCode.HIDDEN_CARD,
                    f"{instance} 가 관측에 보이지 않습니다. 이 듀얼에 없는지 "
                    "가려진 존에 있는지 구분할 수 없습니다.",
                )
            return ValidationResult.invalid(
                ValidationCode.CANDIDATE_NOT_ELIGIBLE,
                f"{instance} 는 후보가 아닙니다: {spec.source.describe_ko()}",
            )

        return ValidationResult.valid(
            f"{len(chosen)}장 모두 후보에 있습니다. "
            "다만 대상 지정 규칙은 아직 검사하지 않습니다."
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<SelectionValidator {self._view}>"


__all__ = ["CostValidator", "SelectionValidator"]
