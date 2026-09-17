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

이름으로 잇는다
---------------
한 효과가 대상을 여럿 가질 수 있고, 하는 일이 그중 **어느 것**을 쓰는지
말할 수 있어야 한다. "대상으로 지정한 몬스터 1장을 파괴한다" 가 그것이다.

    EffectDefinition
      targets     = (TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(...)),)
      operations  = (CardOperation.destroy(PRIMARY_TARGET),)

:class:`TargetRef` 는 **이름일 뿐**이다. 실제로 고른 카드는 정의가 아니라
:class:`~engine.effect.resolution.ResolutionContext` 에 있다 —
정의는 "무엇을 대상으로 하는가", 문맥은 "이번에 무엇이 골라졌는가" 다.
정의에 ``InstanceId`` 를 박아 넣으면 그 정의는 한 판에서 한 번밖에 못 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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




@dataclass(frozen=True, slots=True, order=True)
class TargetRef:
    """
    효과 안에서 대상을 가리키는 **이름.**

    ``InstanceId`` 가 아니다. 정의는 어느 카드가 골라질지 모르고, 알 필요도
    없다 — 같은 정의를 여러 판에서 쓰기 때문이다.

    이름은 정의 안에서만 뜻이 있다. 다른 카드의 ``"primary"`` 와 같은
    이름이어도 서로 다른 대상이다.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError(f"대상 이름이 비었거나 공백이 섞였습니다: {self.name!r}")

    def __str__(self) -> str:
        return f"@{self.name}"

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"TargetRef({self.name!r})"


#: 대상이 하나뿐인 흔한 경우의 이름.
PRIMARY_TARGET = TargetRef("primary")


@dataclass(frozen=True, slots=True)
class TargetBinding:
    """정의 안에서 이름 하나와 대상 규칙 하나를 잇는다."""

    ref: TargetRef
    spec: TargetSpec

    def __post_init__(self) -> None:
        if not self.spec.requires_selection:
            raise ValueError(
                f"{self.ref} 에 대상을 요구하지 않는 규칙이 묶였습니다. "
                "고를 것이 없는 대상은 이름을 가질 이유가 없습니다."
            )

    @classmethod
    def single(cls, spec: TargetSpec) -> tuple["TargetBinding", ...]:
        """대상이 하나뿐인 효과. :data:`PRIMARY_TARGET` 이름을 쓴다."""
        return (cls(PRIMARY_TARGET, spec),)

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.spec.canonical_state())

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "spec": self.spec.to_dict()}

    def describe_ko(self) -> str:
        return f"{self.ref}: {self.spec.describe_ko()}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TargetSelection:
    """
    **이번 해결에서** 그 이름에 무엇이 골라졌는가.

    정의가 아니라 문맥에 속한다 (:class:`~engine.effect.resolution.
    ResolutionContext`). 이름은 정의에서 오고 카드는 여기서 온다.
    """

    ref: TargetRef
    selection: Selection = field(default_factory=Selection)

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.selection.canonical_state())

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "selection": self.selection.to_dict()}

    def __len__(self) -> int:
        return len(self.selection)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.ref}={self.selection}"


__all__ = [
    "TargetRequirement",
    "TargetSpec",
    "TargetRef",
    "PRIMARY_TARGET",
    "TargetBinding",
    "TargetSelection",
]
