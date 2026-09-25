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

from engine.condition import PlayerRef
from engine.cost import CandidateSource, ChoiceSpec, Selection
from engine.execution import (
    ResolvedValue,
    ValueDomain,
    ValueOutcome,
    NO_EXECUTION_VALUES,
    DeclarationOutcome,
    ExecutionLookupError,
    ResultRef,
    ValueRef,
)
from engine.vocabulary import Zone


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
    RANDOM = "random"
    """
    **아무도 고르지 않는다.** 무작위가 정한다 (Phase 2-AB).

    앞의 둘과 결정적으로 다르다. ``TARGETING`` · ``CHOOSING`` 은 "누가
    고르는가" 가 있고, 그 사람은 후보를 **볼 수 있어야** 한다. 무작위
    선택에는 고르는 사람이 없으므로 아무도 볼 필요가 없다 — "상대 패에서
    무작위로 1장" 이 성립하는 이유다.

        "상대 패에서 1장을 고른다"        → CHOOSING (고르는 사람이 본다)
        "상대 패에서 무작위로 1장"        → RANDOM   (아무도 보지 않는다)

    그래서 명세도 다르다 (:class:`RandomSelectionSpec` 에는 ``chooser``
    칸이 없다).
    """


# ======================================================================
# 몇 장을 고르는가 (Phase 2-AC)
# ======================================================================
#
# **후보와 수는 다른 질문이다.**
#
#     무엇을 고를 수 있는가  →  CandidateSource · CandidateResolver
#     몇 개를 고르는가       →  SelectionCount  (여기)
#
# 둘을 한곳에 두면 "후보를 세다가 수를 정하는" 코드가 생기고, 그러면
# 확률이 어디서 정해졌는지 추적할 수 없게 된다.


class CountKind(str, Enum):
    """선택 수가 **어디서 오는가.**"""

    FIXED = "fixed"
    """정의에 적힌 숫자. 실제 카드 142건 중 130건이 여기다."""
    DERIVED = "derived"
    """
    판에서 **계산된다.** 무정의 말살의 1장과 달리, 악몽의 신기루는
    "뽑은 수만큼" 이고 멀차미는 "패 - (상대 필드 + 6)" 이다.
    """
    DECLARED = "declared"
    """
    **플레이어가 선언한다** (Phase 2-AD). 이름으로 가리키고, 그 이름의
    선언 규칙은 정의가 따로 들고 있다.

    ``DERIVED`` 와 다르다 — 저쪽은 판이 정하고 이쪽은 **사람이 정한다.**
    같은 판에서도 다른 수가 나올 수 있고, 그것이 옳다.
    """
    FROM_RESULT = "from_result"
    """
    **앞선 조작이 낸 수** (Phase 2-AD). 몇 번째 조작인지 적는다.

    "바로 앞" 이 아니다. 번호를 적지 않으면 가리킬 수 없다.
    """
    UNKNOWN = "unknown"
    """
    **계산할 수 없다.** 수가 아직 옮기지 못한 곳에서 온다.

    이것을 숫자로 바꾸지 않는다. 1 로 접으면 "1장 고른다" 는 **틀린
    규칙**이 되고, 0 으로 접으면 효과가 조용히 사라진다.
    """


@dataclass(frozen=True, slots=True)
class ZoneCountTerm:
    """
    "어느 자리에 몇 장" 하나. 계수를 곱해서 더한다.

    표현식 언어가 아니다. 실제 카드 네 장이 요구하는 모양 — 자리 장수의
    **덧셈과 뺄셈** — 딱 그만큼이다.
    """

    player: PlayerRef
    zone: Zone
    coefficient: int = 1

    def canonical_state(self) -> tuple:
        return (self.player.value, self.zone.value, self.coefficient)

    def to_dict(self) -> dict:
        return {
            "player": self.player.value,
            "zone": self.zone.value,
            "coefficient": self.coefficient,
        }

    def describe_ko(self) -> str:
        sign = "+" if self.coefficient >= 0 else "-"
        size = abs(self.coefficient)
        amount = "" if size == 1 else f"{size}x"
        return f"{sign}{amount}({self.player} {self.zone.value} 장수)"


@dataclass(frozen=True, slots=True)
class SelectionCount:
    """
    **몇 장을 고르는가** 라는 요구 (Phase 2-AC).

    ``resolve`` 는 자리 장수를 세어 주는 함수를 **받아서** 쓴다. 판을
    직접 읽지 않는 이유는, 수를 정하는 일과 판을 읽는 일을 갈라 두어야
    "수가 어디서 왔는가" 를 한곳에서 답할 수 있기 때문이다.
    """

    kind: CountKind = CountKind.FIXED
    value: "int | None" = None
    terms: "tuple[ZoneCountTerm, ...]" = ()
    constant: int = 0
    missing: str = ""
    """``UNKNOWN`` 일 때 **무엇이 없어서** 모르는가."""
    declared: "ValueRef | None" = None
    """``DECLARED`` 일 때 그 수의 이름 (Phase 2-AD)."""
    result: "ResultRef | None" = None
    """``FROM_RESULT`` 일 때 가리키는 앞선 조작 (Phase 2-AD)."""
    domain: "ValueDomain | None" = None
    """
    나온 값이 **허용되는지** 보는 규칙 (Phase 2-AF).

    수를 **정하는 것**과 그 수가 **되는지 보는 것**은 다른 일이므로 타입도
    다르다. 여기 있는 것은 그 둘을 잇는 한 칸일 뿐이고, 검사는
    :class:`~engine.execution.ValueDomain` 이 한다.

    ``None`` 이면 **검사하지 않았다는 뜻**이지 무엇이든 된다는 뜻이 아니다.
    """

    def __post_init__(self) -> None:
        # **한 갈래에는 한 가지 근거만 붙는다.** 숫자와 계산식과 이름이
        # 함께 붙어 있으면 그중 하나는 반드시 거짓말이다.
        carried = {
            "value": self.value is not None,
            "terms": bool(self.terms),
            "declared": self.declared is not None,
            "result": self.result is not None,
        }
        allowed = {
            CountKind.FIXED: "value",
            CountKind.DERIVED: "terms",
            CountKind.DECLARED: "declared",
            CountKind.FROM_RESULT: "result",
            CountKind.UNKNOWN: None,
        }[self.kind]
        for name, present in carried.items():
            if present and name != allowed:
                raise ValueError(
                    f"{self.kind.value} 수에 {name} 가 붙어 있습니다 — "
                    "둘 중 하나는 거짓말입니다."
                )
        if self.kind is CountKind.FIXED:
            if self.value is None or self.value < 1:
                raise ValueError(
                    f"고정 수는 1 이상이어야 합니다: {self.value}. "
                    "0장을 무작위로 고르는 것은 고르지 않는 것입니다."
                )
        elif self.kind is CountKind.DERIVED:
            if not self.terms and self.constant == 0:
                raise ValueError("계산식이 비어 있습니다.")
        elif self.kind is CountKind.DECLARED:
            if self.declared is None:
                raise ValueError("선언되는 수에 이름이 없습니다.")
        elif self.kind is CountKind.FROM_RESULT:
            if self.result is None:
                raise ValueError("앞선 결과를 가리키는데 번호가 없습니다.")
        else:
            if not self.missing:
                raise ValueError("무엇이 없어서 모르는지 적어야 합니다.")

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------

    @classmethod
    def fixed(cls, value: int) -> "SelectionCount":
        return cls(kind=CountKind.FIXED, value=value)

    @classmethod
    def derived(
        cls, terms: "tuple[ZoneCountTerm, ...]", constant: int = 0
    ) -> "SelectionCount":
        return cls(kind=CountKind.DERIVED, terms=tuple(terms), constant=constant)

    @classmethod
    def from_declaration(cls, ref: "ValueRef") -> "SelectionCount":
        """**플레이어가 선언한 수**를 이름으로 가리킨다 (Phase 2-AD)."""
        return cls(kind=CountKind.DECLARED, declared=ref)

    @classmethod
    def from_result(cls, result: "ResultRef") -> "SelectionCount":
        """**앞선 조작이 낸 수**를 번호로 가리킨다 (Phase 2-AD)."""
        return cls(kind=CountKind.FROM_RESULT, result=result)

    @classmethod
    def unknown(cls, missing: str) -> "SelectionCount":
        """**모른다.** 무엇이 없어서 모르는지 이름으로 남긴다."""
        return cls(kind=CountKind.UNKNOWN, missing=missing)

    @classmethod
    def of(cls, count: "int | SelectionCount") -> "SelectionCount":
        """숫자 하나는 :attr:`CountKind.FIXED` 로 읽는다."""
        if isinstance(count, SelectionCount):
            return count
        return cls.fixed(count)

    # ------------------------------------------------------------------
    # 답하기
    # ------------------------------------------------------------------

    def resolve(self, zone_size, values=NO_EXECUTION_VALUES) -> ResolvedValue:
        """
        이번 판에서 몇 장인가.

        ``zone_size`` 는 ``(PlayerRef, Zone) -> int`` 다. 판을 아는 쪽이
        건네준다 — 이 값은 **엔진의 권위 있는 장수**이지 누군가의 관측이
        아니다 (상대 패가 몇 장인지는 규칙이 아는 사실이다).

        ``values`` 는 **이번 해결 중에 생긴 값들**이다 (Phase 2-AD).
        기본값은 "아무것도 생기지 않았다" 이고, 그 상태에서 선언이나 앞선
        결과를 물으면 ``PENDING``/없음이 그대로 나온다 — 실행 밖에서
        물었다는 사실을 숫자로 덮지 않는다.
        """
        if self.kind is CountKind.DECLARED:
            assert self.declared is not None
            answer = values.declared(self.declared)
            if answer.outcome is DeclarationOutcome.RESOLVED:
                assert answer.value is not None
                if answer.value < 1:
                    return ResolvedValue(
                        ValueOutcome.INVALID,
                        reason=(
                            f"{self.declared} 로 {answer.value} 를 선언했습니다. "
                            "0장 이하를 무작위로 고르는 것은 고르지 않는 것입니다."
                        ),
                    )
                return ResolvedValue(ValueOutcome.RESOLVED, value=answer.value)
            if answer.outcome is DeclarationOutcome.PENDING:
                # **대신 정해 주지 않는다.** 아직 사람이 안 정했다는 사실이다.
                return ResolvedValue(
                    ValueOutcome.UNKNOWN,
                    reason=answer.reason,
                    missing=f"declared number {self.declared}",
                )
            return ResolvedValue(ValueOutcome.INVALID, reason=answer.reason)

        if self.kind is CountKind.FROM_RESULT:
            assert self.result is not None
            try:
                found = values.result(self.result)
            except ExecutionLookupError as error:
                # 가리킨 결과가 없다. **0 으로 때우지 않는다.**
                return ResolvedValue(
                    ValueOutcome.UNKNOWN,
                    reason=f"앞선 결과를 읽지 못했습니다: {error}",
                    missing=self.result.describe_ko(),
                )
            if found < 1:
                return ResolvedValue(
                    ValueOutcome.INVALID,
                    reason=(
                        f"{self.result.describe_ko()} 가 {found} 입니다. "
                        "0장 이하를 무작위로 고르는 것은 고르지 않는 것입니다."
                    ),
                )
            return ResolvedValue(ValueOutcome.RESOLVED, value=found)

        if self.kind is CountKind.UNKNOWN:
            return ResolvedValue(
                ValueOutcome.UNKNOWN,
                reason=f"고를 수를 계산할 수 없습니다: {self.missing}",
                missing=self.missing,
            )
        if self.kind is CountKind.FIXED:
            assert self.value is not None  # __post_init__ 이 보장한다
            return ResolvedValue(ValueOutcome.RESOLVED, value=self.value)

        total = self.constant
        for term in self.terms:
            total += term.coefficient * zone_size(term.player, term.zone)
        if total < 1:
            # **0 을 조용히 넘기지 않는다.** 실제 카드는 이 경우를 발동
            # 조건으로 막는다 (멀차미는 ``if dif>0``, 악몽의 신기루는
            # 라벨이 0 이면 발동하지 않는다). 그 조건 없이 여기까지 왔다면
            # 정의가 조건을 빠뜨린 것이지, 0장을 고르라는 뜻이 아니다.
            return ResolvedValue(
                ValueOutcome.INVALID,
                reason=(
                    f"계산된 수가 {total} 입니다. 0장 이하를 무작위로 고르는 "
                    "것은 고르지 않는 것이므로, 발동 조건이 먼저 막아야 합니다."
                ),
            )
        return ResolvedValue(ValueOutcome.RESOLVED, value=total)

    # ------------------------------------------------------------------
    # 표시
    # ------------------------------------------------------------------

    def canonical_state(self) -> tuple:
        return (
            self.kind.value,
            self.value,
            tuple(term.canonical_state() for term in self.terms),
            self.constant,
            self.missing,
            self.declared.name if self.declared is not None else None,
            self.result.canonical_state() if self.result is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": self.kind.value}
        if self.value is not None:
            data["value"] = self.value
        if self.terms:
            data["terms"] = [term.to_dict() for term in self.terms]
        if self.constant:
            data["constant"] = self.constant
        if self.missing:
            data["missing"] = self.missing
        if self.declared is not None:
            data["declared"] = self.declared.name
        if self.result is not None:
            data["result"] = self.result.to_dict()
        return data

    def describe_ko(self) -> str:
        if self.kind is CountKind.FIXED:
            return f"{self.value}장"
        if self.kind is CountKind.UNKNOWN:
            return f"몇 장인지 모름 ({self.missing})"
        if self.kind is CountKind.DECLARED:
            return f"{self.declared} 로 선언한 수만큼"
        if self.kind is CountKind.FROM_RESULT:
            assert self.result is not None
            return f"{self.result.describe_ko()} 만큼"
        parts = [term.describe_ko() for term in self.terms]
        if self.constant:
            parts.append(f"{self.constant:+d}")
        return " ".join(parts) + "장"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class Shortfall(str, Enum):
    """
    고를 수보다 후보가 **적을 때** 어떻게 하는가.

    기본은 :attr:`REFUSE` 다. 그리고 그것이 **일반 규칙이 아니라는 것**이
    이 갈래의 요점이다 — 공식 카드 텍스트 두 장이 부족할 때의 처리를
    자기 텍스트에 직접 적어 두었다.

        13959634  "Discard 2 random cards from your opponent's hand
                   (**or their entire hand, if less than 2**)"
        41482598  "Randomly discard the same number of cards you drew
                   (**or your entire hand, if you do not have enough cards**)"

    카드가 적어야 아는 것이면 카드가 말하게 한다 (Phase 2-X 에서 관문을
    카드가 선언하게 한 것과 같은 이유다).

    **"최대 N장" 과 다르다.** 실제 카드의 "up to 2 random cards" 는
    플레이어가 1 이나 2 를 **선언한 뒤** 그 수만큼 무작위로 고르는
    것이다 (``Duel.SelectOption`` · ``Duel.AnnounceNumber``). 그것은 수를
    정하는 방법의 문제이고 부족할 때의 처리가 아니다.
    """

    REFUSE = "refuse"
    """모자라면 **하지 않는다.** 판은 그대로다."""
    TAKE_ALL = "take_all"
    """모자라면 **있는 대로 전부.** 카드가 그렇게 적어 둔 경우만이다."""


@dataclass(frozen=True, slots=True)
class RandomSelectionSpec:
    """
    "후보 중 무작위로 N 개" 라는 **요구** (Phase 2-AB).

    :class:`~engine.cost.ChoiceSpec` 과 **후보 규칙(**:class:`
    ~engine.cost.CandidateSource`**)만 공유한다.** 나머지는 다르다.

    ==================  ==========================  =====================
    ..                  ``ChoiceSpec``              ``RandomSelectionSpec``
    ==================  ==========================  =====================
    누가 고르는가         ``chooser``                 **없다** (무작위)
    몇 장                 ``minimum`` ~ ``maximum``    ``count`` 하나
    후보를 봐야 하는가     그렇다                       아니다
    ==================  ==========================  =====================

    ``chooser`` 칸을 **일부러 두지 않았다.** 두면 "무작위인데 누가
    고른다" 가 되고, 그 순간 플레이어 선택과 무작위 선택의 구분이 이름만
    남는다.

    ``minimum``/``maximum`` 은 **없다** (Phase 2-AC). 처음에는
    :class:`~engine.effect.targeting.TargetResolver` 에 맞추려고 두었는데,
    무작위 선택은 그 판정기를 타지 않는다. 남겨 두면 후보를 세는 쪽이
    장수를 읽을 수 있게 되고, 그것이 바로 §4 가 갈라 놓으라고 한 두 일이
    다시 붙는 길이다. **후보를 세는 데 장수는 쓰이지 않는다.**
    """

    source: CandidateSource
    count: SelectionCount = field(default_factory=lambda: SelectionCount.fixed(1))
    """
    몇 장인가. 숫자를 그대로 적으면 :attr:`CountKind.FIXED` 로 읽는다.
    """
    replacement: bool = False
    """
    같은 카드가 두 번 뽑힐 수 있는가. **거의 언제나 거짓이다** — 한 장의
    카드를 두 번 버릴 수는 없다.
    """
    on_shortfall: Shortfall = Shortfall.REFUSE
    """후보가 모자랄 때. **카드가 적어 둔 경우만** 바꾼다."""

    def __post_init__(self) -> None:
        if not isinstance(self.count, SelectionCount):
            # 숫자 하나는 고정 수로 읽는다. 값을 바꾸는 것이 아니라 같은
            # 뜻을 제 타입으로 적는 것이다.
            object.__setattr__(self, "count", SelectionCount.of(self.count))

    def looked_at_zones(self) -> "frozenset[Zone]":
        """
        **비어 있다.** 무작위 선택에는 고르는 사람이 없으므로 아무도
        들여다보지 않는다 (Phase 2-Y 의 ``looked_at`` 은 "고르려면 봐야
        한다" 였다).

        후보를 세는 것은 **엔진**이고, 엔진이 아는 것과 플레이어가 보는
        것은 계속 다른 것이다.
        """
        return frozenset()

    def canonical_state(self) -> tuple:
        return (
            "random",
            self.source.canonical_state(),
            self.count.canonical_state(),
            self.replacement,
            self.on_shortfall.value,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "random",
            "source": self.source.to_dict(),
            "count": self.count.to_dict(),
        }
        if self.replacement:
            data["replacement"] = True
        if self.on_shortfall is not Shortfall.REFUSE:
            data["on_shortfall"] = self.on_shortfall.value
        return data

    def describe_ko(self) -> str:
        tail = " (모자라면 전부)" if self.on_shortfall is Shortfall.TAKE_ALL else ""
        return f"{self.source.describe_ko()} 중 무작위로 {self.count.describe_ko()}{tail}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """
    효과의 대상 규칙. **불변**이다.

    ``choice`` 는 ``requirement`` 가 :attr:`TargetRequirement.NONE` 이 아닐
    때만 있다. 반대로 ``NONE`` 인데 ``choice`` 가 있으면 모순이므로 거부한다.
    """

    requirement: TargetRequirement = TargetRequirement.NONE
    choice: "ChoiceSpec | RandomSelectionSpec | None" = None

    def __post_init__(self) -> None:
        if self.requirement is TargetRequirement.NONE:
            if self.choice is not None:
                raise ValueError(
                    "대상을 요구하지 않는데 선택 명세가 붙어 있습니다."
                )
            return
        if self.choice is None:
            raise ValueError(
                f"{self.requirement.value} 에는 선택 명세(ChoiceSpec)가 필요합니다."
            )
        # **명세와 요구가 어긋나지 않는다.** 무작위인데 고르는 사람이
        # 적혀 있거나, 고르기인데 고르는 사람이 없으면 둘 중 하나가 거짓말이다.
        random_spec = isinstance(self.choice, RandomSelectionSpec)
        if (self.requirement is TargetRequirement.RANDOM) is not random_spec:
            raise ValueError(
                f"{self.requirement.value} 에 "
                f"{type(self.choice).__name__} 이 붙어 있습니다. 무작위 선택은 "
                "RandomSelectionSpec 이고 (고르는 사람이 없다), 플레이어가 "
                "고르는 것은 ChoiceSpec 입니다 (고르는 사람이 있다)."
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

    @classmethod
    def at_random(cls, choice: "RandomSelectionSpec") -> "TargetSpec":
        """**아무도 고르지 않는다.** 무작위가 정한다 (Phase 2-AB)."""
        return cls(requirement=TargetRequirement.RANDOM, choice=choice)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def looked_at_zones(self) -> "frozenset[Zone]":
        """
        이 대상 규칙을 판정하려면 컨트롤러가 **자기 어느 자리를 들여다
        봐야 하는가** (Phase 2-Y).

        고를 것이 없으면 빈 집합이다.
        """
        if self.choice is None:
            return frozenset()
        return self.choice.looked_at_zones()

    @property
    def is_random(self) -> bool:
        """
        **무작위가 정하는가.** 참이면 밖에서 고른 것을 받지 않는다 —
        실행기가 난수원에서 직접 정한다.
        """
        return self.requirement is TargetRequirement.RANDOM

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

        **무작위 선택도 거짓이다** (Phase 2-AB). 기다릴 사람이 없다 —
        해결 중에 난수원이 정하므로 "아직 안 골랐다" 라는 상태가 아예
        없다.
        """
        if not self.requires_selection or self.is_random:
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
    "RandomSelectionSpec",
    "SelectionCount",
    "CountKind",
    "ValueOutcome",
    "ResolvedValue",
    "ZoneCountTerm",
    "Shortfall",
    "TargetRef",
    "PRIMARY_TARGET",
    "TargetBinding",
    "TargetSelection",
]
