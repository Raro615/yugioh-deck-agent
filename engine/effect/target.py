"""
효과의 **대상 규칙**.

Phase 2-C 의 선택과 혼동하지 않는다.

=====================  ==========================================
:class:`TargetSpec`     효과가 무엇을 대상으로 하는가 — **규칙**
``ChoiceSpec``          몇 장을 어디서 고르는가 — **요구**
``CandidateSet``        지금 고를 수 있는 것 — **관측**
``Selection``           실제로 고른 것 — **결과**
=====================  ==========================================

``TargetSpec`` 은 규칙이고, 그 안에 "어떻게 고르는가" 를 ``ChoiceSpec`` 으로
담는다. 고르는 일과 고른 것을 검사하는 일은 이미 Phase 2-C 가 한다.

대상 지정과 고르기는 다르다
---------------------------
유희왕에서 "대상으로 한다" 와 "고른다" 는 **다른 규칙**이다. 대상 지정은
발동 시점에 확정되고 무효화·회피의 대상이 되지만, 단순히 고르는 것은
해결 시점의 일이다. ``analysis`` 도 이 둘을 구분한다
(``EffectSelection`` 설명과 ``EffectAnalysis.targets_card``).

없음과 아직 안 고름을 구분한다
------------------------------
**가장 중요한 구분이다.**

- :meth:`TargetSpec.none` — 이 효과는 대상을 **요구하지 않는다**
- :meth:`TargetSpec.targeting` + 선택 없음 — **아직 고르지 않았다**

둘을 같은 상태로 만들면 "대상이 없어도 되는 효과" 와 "대상을 빠뜨린 효과"
가 구분되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.cost import ChoiceSpec, Selection


class TargetRequirement(str, Enum):
    """대상을 어떻게 요구하는가."""

    NONE = "none"
    """대상을 **요구하지 않는다.** 고를 것이 없다."""
    TARGETING = "targeting"
    """
    규칙상 **대상으로 지정**한다. 발동 시점에 확정되고, 무효화·회피의
    대상이 된다.
    """
    CHOOSING = "choosing"
    """
    고르기는 하지만 **대상 지정은 아니다.** 해결 시점에 고른다.
    "대상을 지정하지 않는 제거" 가 여기에 해당한다.
    """


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """
    효과의 대상 규칙. **불변**이다.

    ``choice`` 는 ``requirement`` 가 :attr:`TargetRequirement.NONE` 이 아닐
    때만 있다. 반대로 ``NONE`` 인데 ``choice`` 가 있으면 모순이므로 거부한다.
    """

    requirement: TargetRequirement = TargetRequirement.NONE
    choice: ChoiceSpec | None = None

    def __post_init__(self) -> None:
        if self.requirement is TargetRequirement.NONE:
            if self.choice is not None:
                raise ValueError(
                    "대상을 요구하지 않는데 선택 명세가 붙어 있습니다."
                )
        elif self.choice is None:
            raise ValueError(
                f"{self.requirement.value} 에는 선택 명세(ChoiceSpec)가 필요합니다."
            )

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------
    @classmethod
    def none(cls) -> "TargetSpec":
        """대상을 요구하지 않는 효과."""
        return cls(requirement=TargetRequirement.NONE)

    @classmethod
    def targeting(cls, choice: ChoiceSpec) -> "TargetSpec":
        """규칙상 **대상으로 지정**하는 효과."""
        return cls(requirement=TargetRequirement.TARGETING, choice=choice)

    @classmethod
    def choosing(cls, choice: ChoiceSpec) -> "TargetSpec":
        """고르지만 대상 지정은 아닌 효과."""
        return cls(requirement=TargetRequirement.CHOOSING, choice=choice)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def requires_selection(self) -> bool:
        """고를 것이 있는가. **"아직 안 골랐다" 와 다른 질문이다.**"""
        return self.requirement is not TargetRequirement.NONE

    @property
    def is_targeting(self) -> bool:
        """규칙상 대상 지정인가. 고르기와 구분된다."""
        return self.requirement is TargetRequirement.TARGETING

    def is_pending(self, selection: Selection | None) -> bool:
        """
        **아직 고르지 않았는가.**

        대상을 요구하지 않는 효과는 언제나 거짓이다 — 고를 것이 없으므로
        기다릴 것도 없다. 이것이 §11 의 구분이다.
        """
        if not self.requires_selection:
            return False
        if selection is None:
            return True
        assert self.choice is not None  # 생성자가 보장한다
        return len(selection) < self.choice.minimum

    def canonical_state(self) -> tuple:
        return (
            self.requirement.value,
            self.choice.canonical_state() if self.choice is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"requirement": self.requirement.value}
        if self.choice is not None:
            data["choice"] = self.choice.to_dict()
        return data

    def describe_ko(self) -> str:
        if self.requirement is TargetRequirement.NONE:
            return "대상 없음"
        assert self.choice is not None
        verb = "대상으로 지정" if self.is_targeting else "선택"
        return f"{self.choice.source.describe_ko()} 에서 {verb}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


__all__ = ["TargetRequirement", "TargetSpec"]
