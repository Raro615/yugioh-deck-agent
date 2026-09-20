"""
대상 선택 — "이 카드를 대상으로 삼아도 되는가".

    TargetSpec (규칙)
        ↓  TargetResolver.candidates()     지금 고를 수 있는 것들
    CandidateSet
        ↓  TargetResolver.validate()       고른 것이 적법한가
    TargetValidation                       LEGAL · ILLEGAL · UNKNOWN

두 질문을 나눈다
----------------
=========================  ==========================================
:meth:`~TargetResolver.candidates`  **무엇을 고를 수 있는가**
:meth:`~TargetResolver.validate`    **고른 것이 적법한가**
=========================  ==========================================

고르는 일은 여기서 하지 않는다. AI 가 무엇을 **선호하는가**는 이 계층의
질문이 아니다 — 엔진은 "이 대상이 적법한가" 만 답하고, 무엇을 고를지는
관측(``GameStateView``)을 보는 쪽이 정한다.

모르는 것을 고를 수 있다고 하지 않는다
--------------------------------------
**세 갈래를 끝까지 유지한다.**

- 상대의 뒷면 카드가 조건을 만족하는지 — **모른다** (``UNDECIDED``)
- 상대의 패·덱처럼 통째로 가려진 곳 — **못 봤다** (``unchecked``)
- 관측에 아예 없는 카드 — **없는지 숨은지 모른다** (``HIDDEN_CARD``)

셋 다 ``UNKNOWN`` 이고, ``UNKNOWN`` 은 허가가 아니다.

의미 계층과 섞지 않는다
-----------------------
이 파일에 ``DESTROY`` 도 ``SEND_TO_GRAVE`` 도 ``DISCARD`` 도 나오지 않는다.
대상 선택은 **무엇을 할 것인가와 무관한** 일반 계층이다 — 같은 대상 규칙이
파괴에도 보내기에도 쓰인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import ConditionContext
from engine.cost import CandidateResolver, CandidateSet, ChoiceSpec, Selection
from engine.effect.target import TargetRef, TargetSpec
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.validation import ValidationCode


class TargetLegality(str, Enum):
    """
    이 대상을 삼아도 되는가. **세 값이다.**

    ``UNKNOWN`` 을 ``LEGAL`` 로도 ``ILLEGAL`` 로도 접지 않는다 — 가려진
    정보 때문에 판정할 수 없는 것과 규칙상 안 되는 것은 다른 사실이다.
    """

    LEGAL = "legal"
    ILLEGAL = "illegal"
    UNKNOWN = "unknown"

    @property
    def permits_selection(self) -> bool:
        """
        대상으로 삼아도 되는가. **``LEGAL`` 일 때만 참이다.**

        ``if legality is not ILLEGAL:`` 로 쓰면 ``UNKNOWN`` 이 허가로 새어
        나간다.
        """
        return self is TargetLegality.LEGAL

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


def _combine(values) -> TargetLegality:
    """
    여러 판정을 합친다. **``ILLEGAL`` 이 ``UNKNOWN`` 을 이긴다.**

    확실한 위반이 하나라도 있으면 나머지를 몰라도 위반이다 (검증 계층이
    ``FALSE`` 를 ``UNKNOWN`` 보다 먼저 보는 것과 같은 규율).
    """
    seen = tuple(values)
    if any(value is TargetLegality.ILLEGAL for value in seen):
        return TargetLegality.ILLEGAL
    if any(value is TargetLegality.UNKNOWN for value in seen):
        return TargetLegality.UNKNOWN
    return TargetLegality.LEGAL


@dataclass(frozen=True, slots=True)
class TargetVerdict:
    """고른 카드 **한 장**에 대한 판정."""

    instance: InstanceId
    legality: TargetLegality
    code: ValidationCode = ValidationCode.OK
    reason: str = ""

    @property
    def permits_selection(self) -> bool:
        return self.legality.permits_selection

    def __bool__(self) -> bool:
        raise TypeError(
            "TargetVerdict 를 참/거짓으로 쓸 수 없습니다. UNKNOWN 이 조용히 "
            "허가가 됩니다. `verdict.permits_selection` 을 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.instance.value,
            self.legality.value,
            self.code.value,
            self.reason,
        )

    def to_dict(self) -> dict:
        return {
            "instance": self.instance.value,
            "legality": self.legality.value,
            "code": self.code.value,
            "reason": self.reason,
        }

    def describe_ko(self) -> str:
        return f"{self.instance}: {self.legality.value} ({self.reason})"


@dataclass(frozen=True, slots=True)
class TargetValidation:
    """
    대상 이름 하나에 대한 **전체 판정.** 불변이다.

    :attr:`verdicts` 는 고른 카드마다 하나씩이고, :attr:`legality` 는 그
    전부와 장수 규칙을 합친 결과다.
    """

    legality: TargetLegality
    code: ValidationCode = ValidationCode.OK
    reason: str = ""
    ref: TargetRef | None = None
    verdicts: tuple[TargetVerdict, ...] = ()
    candidates: CandidateSet | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.verdicts, tuple):
            raise TypeError("verdicts 는 tuple 이어야 합니다 — 판정은 불변입니다.")

    @property
    def permits_selection(self) -> bool:
        """**``LEGAL`` 일 때만 참이다.**"""
        return self.legality.permits_selection

    @property
    def unchecked(self) -> tuple[str, ...]:
        """후보를 찾을 때 **들여다보지 못한 곳들.**"""
        return self.candidates.unchecked if self.candidates is not None else ()

    @property
    def fully_checked(self) -> bool:
        return not self.unchecked

    def __bool__(self) -> bool:
        raise TypeError(
            "TargetValidation 을 참/거짓으로 쓸 수 없습니다. "
            "`validation.permits_selection` 을 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.legality.value,
            self.code.value,
            self.reason,
            self.ref.name if self.ref is not None else None,
            tuple(v.canonical_state() for v in self.verdicts),
            self.candidates.canonical_state() if self.candidates is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "legality": self.legality.value,
            "code": self.code.value,
            "reason": self.reason,
            "verdicts": [v.to_dict() for v in self.verdicts],
        }
        if self.ref is not None:
            data["ref"] = self.ref.name
        if self.candidates is not None:
            data["candidates"] = self.candidates.to_dict()
        return data

    def describe_ko(self) -> str:
        who = f"{self.ref} " if self.ref is not None else ""
        return f"{who}{self.legality.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TargetResolver:
    """
    대상 후보를 찾고, 고른 것을 검사한다. **판을 바꾸지 않는다.**

    관측만 들고 있어서 바꿀 수 있는 것이 애초에 없다. 후보 찾기는
    :class:`~engine.cost.CandidateResolver` 를 **그대로 쓴다** — 후보를
    세는 코드를 두 벌 만들지 않는다.
    """

    __slots__ = ("_candidates",)

    def __init__(self, view: GameStateView):
        # CandidateResolver 가 GameStateView 만 받는다 — 그 검사를 그대로 쓴다.
        self._candidates = CandidateResolver(view)

    @property
    def view(self) -> GameStateView:
        return self._candidates.view

    @property
    def candidate_resolver(self) -> CandidateResolver:
        return self._candidates

    # ==================================================================
    # 1. 무엇을 고를 수 있는가
    # ==================================================================
    def candidates(
        self, spec: TargetSpec, context: ConditionContext
    ) -> CandidateSet:
        """
        지금 고를 수 있는 것들. **대상을 요구하지 않는 규칙이면 빈 집합.**

        빈 집합이 "고를 것이 없다" 를 뜻하지 않는다 —
        :attr:`CandidateSet.unchecked` 가 비어 있지 않으면 못 본 곳이 있다.
        """
        if not spec.requires_selection:
            return CandidateSet()
        assert spec.choice is not None  # TargetSpec 이 보장한다
        return self._candidates.resolve(spec.choice, context)

    def availability(
        self, spec: TargetSpec, context: ConditionContext
    ) -> TargetValidation:
        """
        **고를 것이 충분히 있는가.** 무엇을 고를지는 아직 묻지 않는다.

        - 확실한 후보가 최소 장수 이상 → ``LEGAL``
        - 가장 좋게 봐도 모자라고 **전부 확인했다** → ``ILLEGAL``
        - 그 밖 → ``UNKNOWN`` (못 본 곳이 있거나 미확정이 있다)
        """
        if not spec.requires_selection:
            return TargetValidation(
                TargetLegality.LEGAL,
                ValidationCode.OK,
                "대상을 요구하지 않습니다.",
            )
        assert spec.choice is not None
        found = self.candidates(spec, context)
        minimum = spec.choice.minimum

        if found.certain_count >= minimum:
            return TargetValidation(
                TargetLegality.LEGAL,
                ValidationCode.OK,
                f"확실한 후보 {found.certain_count}장 (필요 {minimum}장).",
                candidates=found,
            )
        if found.possible_count < minimum and found.fully_checked:
            return TargetValidation(
                TargetLegality.ILLEGAL,
                ValidationCode.NO_CANDIDATES,
                f"후보가 {found.possible_count}장뿐입니다 (필요 {minimum}장).",
                candidates=found,
            )
        return TargetValidation(
            TargetLegality.UNKNOWN,
            ValidationCode.INFORMATION_UNAVAILABLE,
            "후보가 충분한지 판정할 수 없습니다: "
            + (
                "; ".join(found.unchecked)
                if found.unchecked
                else f"미확정 {len(found.undecided)}장"
            ),
            candidates=found,
        )

    # ==================================================================
    # 2. 고른 것이 적법한가
    # ==================================================================
    def validate(
        self,
        spec: TargetSpec,
        selection: Selection | None,
        context: ConditionContext,
        ref: TargetRef | None = None,
    ) -> TargetValidation:
        """
        이미 고른 것을 검사한다. **고르지 않는다.**

        ``selection`` 이 ``None`` 이면 "아직 고르지 않았다" 이고, 대상을
        요구하는 규칙에서는 ``ILLEGAL`` 이다 — 빈 선택과 다른 사실이지만
        둘 다 최소 장수를 채우지 못한다.
        """
        if not spec.requires_selection:
            if selection is not None and len(selection) > 0:
                return TargetValidation(
                    TargetLegality.ILLEGAL,
                    ValidationCode.TARGET_COUNT_MISMATCH,
                    "대상을 요구하지 않는데 고른 카드가 있습니다.",
                    ref=ref,
                )
            return TargetValidation(
                TargetLegality.LEGAL,
                ValidationCode.OK,
                "대상을 요구하지 않습니다.",
                ref=ref,
            )

        assert spec.choice is not None
        chosen = selection.chosen if selection is not None else ()
        found = self.candidates(spec, context)

        count = self._check_count(spec.choice, chosen, ref, found)
        if count is not None:
            return count

        verdicts = tuple(self._judge(instance, found) for instance in chosen)
        legality = _combine(verdict.legality for verdict in verdicts)
        if legality is TargetLegality.LEGAL:
            return TargetValidation(
                TargetLegality.LEGAL,
                ValidationCode.OK,
                f"{len(chosen)}장 전부 적법한 대상입니다.",
                ref=ref,
                verdicts=verdicts,
                candidates=found,
            )
        worst = next(v for v in verdicts if v.legality is legality)
        return TargetValidation(
            legality,
            worst.code,
            worst.reason,
            ref=ref,
            verdicts=verdicts,
            candidates=found,
        )

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _check_count(
        self,
        choice: ChoiceSpec,
        chosen: tuple[InstanceId, ...],
        ref: TargetRef | None,
        found: CandidateSet,
    ) -> "TargetValidation | None":
        """
        장수 규칙. 통과하면 ``None``.

        **장수는 가려진 정보와 무관하다** — 몇 장을 골랐는가는 고른 쪽이
        아는 사실이므로, 모자라거나 넘치면 확실한 위반이다.
        """
        if len(chosen) < choice.minimum:
            return TargetValidation(
                TargetLegality.ILLEGAL,
                ValidationCode.TOO_FEW_SELECTED,
                f"{len(chosen)}장 골랐습니다 (최소 {choice.minimum}장).",
                ref=ref,
                candidates=found,
            )
        if len(chosen) > choice.maximum:
            return TargetValidation(
                TargetLegality.ILLEGAL,
                ValidationCode.TOO_MANY_SELECTED,
                f"{len(chosen)}장 골랐습니다 (최대 {choice.maximum}장).",
                ref=ref,
                candidates=found,
            )
        if not choice.allow_duplicates and len(set(chosen)) != len(chosen):
            return TargetValidation(
                TargetLegality.ILLEGAL,
                ValidationCode.DUPLICATE_SELECTION,
                "같은 카드를 두 번 골랐습니다.",
                ref=ref,
                candidates=found,
            )
        return None

    def _judge(self, instance: InstanceId, found: CandidateSet) -> TargetVerdict:
        """카드 한 장의 판정. **세 갈래를 유지한다.**"""
        if found.contains(instance):
            return TargetVerdict(
                instance, TargetLegality.LEGAL, ValidationCode.OK, "후보입니다."
            )
        if instance in found.undecided:
            return TargetVerdict(
                instance,
                TargetLegality.UNKNOWN,
                ValidationCode.INFORMATION_UNAVAILABLE,
                "후보 조건을 판정할 수 없습니다 (가려진 정보).",
            )
        if self.view.find(instance) is None:
            # **없는 것과 보이지 않는 것을 구분하지 못한다.**
            return TargetVerdict(
                instance,
                TargetLegality.UNKNOWN,
                ValidationCode.HIDDEN_CARD,
                "관측에 보이지 않습니다. 이 듀얼에 없는지 가려진 곳에 있는지 "
                "구분할 수 없습니다.",
            )
        return TargetVerdict(
            instance,
            TargetLegality.ILLEGAL,
            ValidationCode.CANDIDATE_NOT_ELIGIBLE,
            "후보 조건을 만족하지 않습니다 (자리 · 주인 · 조건).",
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TargetResolver viewer=P{self.view.viewer}>"


__all__ = [
    "TargetLegality",
    "TargetVerdict",
    "TargetValidation",
    "TargetResolver",
]
