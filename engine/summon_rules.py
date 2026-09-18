"""
일반 소환의 **절차 판정** — "이 카드를 지금 절차대로 소환할 수 있는가".

판을 보지 않는다. 카드 정의 하나만 보고 답한다. 그래서 검증기도
실행기도 같은 답을 쓴다 — 판정이 두 곳에 있으면 둘이 갈린다.

공식 규칙 (Rules Knowledge Layer)
---------------------------------
``data/rules/documents/sd-rulebook-en-v10.json``

- **RULE-SUMMON-009 (Normal Summon)** — "Simply play a Monster Card from
  your hand onto the field in face-up Attack Position. **All Normal
  Monsters, and most Effect Monsters (unless they have a specific
  restriction), can be Summoned in this way.**"
- **RULE-SUMMON-011 (Tribute Summon)** — "For monsters that are Level 5 or
  higher, you must Tribute at least 1 monster you control before the Normal
  Summon/Set. Monsters that are Level 5 or 6 require 1 Tribute and Monsters
  that are Level 7 or higher require 2 Tributes."

왜 통상 몬스터만 ``ORDINARY`` 인가
----------------------------------
룰북이 직접 말한다 — 통상 몬스터는 **전부** 이 방법으로 소환되지만, 효과
몬스터는 "**특정 제약이 없는 한**" 이다. 그 제약은 카드 텍스트에 있고, 이
엔진은 아직 그것을 읽지 못한다.

그래서 효과 몬스터는 ``UNDETERMINED`` 다. **``FALSE`` 가 아니다** — 대부분은
소환할 수 있다. 다만 이 엔진이 "이 한 장은 제약이 없다" 를 확인할 방법이
없을 뿐이다. 확인하지 못한 것을 허가로 바꾸지 않는다.

여기서 하지 않는 것
-------------------
제물 소환 · 세트 · 특수 소환 · 소환 조건 파싱. 제물이 필요하다는 **사실**은
:attr:`SummonAssessment.tributes_required` 로 적어 두지만, 그것을 치르는
절차는 이 단계에 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.game_state_view import CardDefinitionView

#: 제물 없이 일반 소환할 수 있는 최대 레벨 (RULE-SUMMON-011).
TRIBUTE_FREE_MAX_LEVEL = 4

#: 제물 하나로 일반 소환할 수 있는 최대 레벨. 그 위는 둘이다.
ONE_TRIBUTE_MAX_LEVEL = 6

#: 일반 소환 자체가 불가능한 카드 종류 이름 (``CardDefinitionView.type_names``).
#:
#: 엑스트라 덱 몬스터는 :attr:`~engine.game_state_view.CardDefinitionView.
#: is_extra_deck` 로 따로 본다 — 종류 이름이 아니라 파생값이 이미 있다.
NEVER_NORMAL_SUMMONABLE: frozenset[str] = frozenset({"RITUAL", "TOKEN"})

#: 절차가 확실한 종류. 룰북이 "All Normal Monsters" 라고 못박은 것뿐이다.
ORDINARY_TYPE_NAME = "NORMAL"


class SummonEligibility(str, Enum):
    """일반 소환 절차를 밟을 수 있는가."""

    ORDINARY = "ordinary"
    """제물 없이, 제약 없이 소환할 수 있다. **이것만 허가가 된다.**"""
    NEEDS_TRIBUTE = "needs_tribute"
    """레벨 5 이상이라 제물이 필요하다. 그 절차가 아직 없다 — 모른다."""
    FORBIDDEN = "forbidden"
    """일반 소환으로는 필드에 나올 수 없는 카드다. **확실히 안 된다.**"""
    UNDETERMINED = "undetermined"
    """소환 조건을 읽을 수 없다. 안 된다는 뜻이 아니다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class SummonAssessment:
    """
    한 카드의 일반 소환 절차 판정. **불변**이고, 판을 보지 않는다.

    :attr:`tributes_required` 는 **룰북이 말하는 수**를 적어 둔 것이지 이
    엔진이 그것을 치를 수 있다는 뜻이 아니다. 치르는 절차가 생기면 이
    값이 그대로 입력이 된다.
    """

    eligibility: SummonEligibility
    reason: str
    missing_rule: str | None = None
    tributes_required: int | None = None

    def __post_init__(self) -> None:
        if self.eligibility is SummonEligibility.NEEDS_TRIBUTE:
            if self.tributes_required is None:
                raise ValueError("제물이 필요하다면 몇 장인지 함께 적습니다.")
        elif self.tributes_required is not None:
            raise ValueError(
                "제물이 필요하지 않은 판정에 제물 수를 적을 수 없습니다."
            )

    @property
    def permits_procedure(self) -> bool:
        """
        절차를 밟아도 되는가. **``ORDINARY`` 일 때만 참이다.**

        ``UNDETERMINED`` 와 ``NEEDS_TRIBUTE`` 가 조용히 허가가 되는 것을
        구조적으로 막는다.
        """
        return self.eligibility is SummonEligibility.ORDINARY

    @property
    def is_refusal(self) -> bool:
        """확실히 안 되는가. ``UNDETERMINED`` 는 거절이 아니다."""
        return self.eligibility is SummonEligibility.FORBIDDEN

    def __bool__(self) -> bool:
        raise TypeError(
            "SummonAssessment 를 참/거짓으로 쓸 수 없습니다. '모른다' 가 "
            "조용히 허가가 됩니다. `assessment.permits_procedure` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.eligibility.value,
            self.reason,
            self.missing_rule,
            self.tributes_required,
        )

    def to_dict(self) -> dict:
        data: dict = {"eligibility": self.eligibility.value, "reason": self.reason}
        if self.missing_rule is not None:
            data["missing_rule"] = self.missing_rule
        if self.tributes_required is not None:
            data["tributes_required"] = self.tributes_required
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.eligibility.value}: {self.reason}"


def tributes_for_level(level: int) -> int:
    """RULE-SUMMON-011 이 말하는 제물 수. 레벨 4 이하는 0 이다."""
    if level <= TRIBUTE_FREE_MAX_LEVEL:
        return 0
    return 1 if level <= ONE_TRIBUTE_MAX_LEVEL else 2


def assess_normal_summon(
    definition: CardDefinitionView | None,
) -> SummonAssessment:
    """
    이 카드가 일반 소환 절차를 밟을 수 있는가.

    **정의가 없으면 ``UNDETERMINED``** 다 — 가려진 카드인지 저장소가 없는
    것인지는 부르는 쪽이 이미 알고 있고, 어느 쪽이든 "안 된다" 는 아니다.
    """
    if definition is None:
        return SummonAssessment(
            SummonEligibility.UNDETERMINED,
            "카드 정의를 읽을 수 없어 소환 절차를 판정할 수 없습니다.",
        )
    if not definition.is_monster:
        return SummonAssessment(
            SummonEligibility.FORBIDDEN,
            "몬스터 카드가 아닙니다.",
        )
    if definition.is_extra_deck:
        return SummonAssessment(
            SummonEligibility.FORBIDDEN,
            "엑스트라 덱 몬스터는 일반 소환으로 필드에 나오지 않습니다.",
        )
    forbidden = NEVER_NORMAL_SUMMONABLE & set(definition.type_names)
    if forbidden:
        return SummonAssessment(
            SummonEligibility.FORBIDDEN,
            f"{'·'.join(sorted(forbidden))} 몬스터는 일반 소환할 수 없습니다.",
        )

    level = definition.monster_level
    if level is None:
        return SummonAssessment(
            SummonEligibility.UNDETERMINED,
            "레벨을 읽을 수 없어 제물이 필요한지 판정할 수 없습니다.",
        )
    if level > TRIBUTE_FREE_MAX_LEVEL:
        return SummonAssessment(
            SummonEligibility.NEEDS_TRIBUTE,
            f"레벨 {level} 이라 제물이 필요합니다 (RULE-SUMMON-011). 제물을 "
            "치르는 절차가 아직 없습니다.",
            missing_rule="tribute-summon (제물 선택 · 릴리스)",
            tributes_required=tributes_for_level(level),
        )

    if ORDINARY_TYPE_NAME in definition.type_names:
        return SummonAssessment(
            SummonEligibility.ORDINARY,
            f"레벨 {level} 통상 몬스터입니다 (RULE-SUMMON-009).",
        )
    return SummonAssessment(
        SummonEligibility.UNDETERMINED,
        "효과 몬스터는 카드 자신의 제약이 있을 수 있습니다 — 룰북은 "
        '"most Effect Monsters (unless they have a specific restriction)" '
        "라고만 말합니다. 이 엔진은 그 제약을 아직 읽지 못합니다.",
        missing_rule="summoning-condition (카드 텍스트의 소환 제약)",
    )


__all__ = [
    "TRIBUTE_FREE_MAX_LEVEL",
    "ONE_TRIBUTE_MAX_LEVEL",
    "NEVER_NORMAL_SUMMONABLE",
    "ORDINARY_TYPE_NAME",
    "SummonEligibility",
    "SummonAssessment",
    "tributes_for_level",
    "assess_normal_summon",
]
