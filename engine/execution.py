"""
효과를 **실행하는 동안에만** 사는 값들 (Phase 2-AD).

    플레이어가 선언한 수      DeclaredNumber
    앞선 조작이 낸 결과       OperationResult
        ↓  이름으로 가리킨다
    ExecutionValues          이번 해결 한 번 동안만 산다

판이 아니다
-----------
여기 있는 값은 **어느 것도** :class:`~engine.state.game_state.GameState` 에
들어가지 않는다. "상대가 2를 선언했다" 는 판의 모양이 아니라 지금 해결의
중간 상태이고, 해결이 끝나면 남는 것은 그 선언이 **일으킨 변화**뿐이다.

그래서 ``state_hash`` 도 움직이지 않는다 — 흐름의 위치를 판에서 뺀 것과
같은 이유다 (``EventJournal`` · ``PriorityState`` · ``Chain`` · 난수원의
위치).

네 가지를 뭉개지 않는다
-----------------------
========================  ==================================================
플레이어가 고른 카드         ``ChoiceSpec`` → ``Selection``      (Phase 2-N)
무작위가 고른 카드           ``RandomSelectionSpec``             (Phase 2-AB)
플레이어가 **선언한 수**     ``DeclaredNumberSpec`` → 여기        (Phase 2-AD)
조작이 **낸 결과**           ``OperationResult``  → 여기          (Phase 2-AD)
========================  ==================================================

앞의 둘은 "무엇을" 이고 뒤의 둘은 "얼마나" 다. 뒤의 둘끼리도 다르다 —
하나는 사람이 정했고 하나는 판이 정했다.

가리키는 것은 언제나 **이름**이다
---------------------------------
"바로 앞의 조작" 같은 암묵적 지시를 만들지 않는다. 앞의 조작을 쓰려면
**몇 번째 조작인지 적어야** 하고, 정의를 만들 때 그 번호가 자기보다
앞인지 검사한다. 마지막 결과를 자동으로 집어 오면, 정의에 일을 하나 끼워
넣는 순간 조용히 다른 수가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.condition import ConditionContext, ConditionResult, PlayerRef
from engine.validation import ActionValidity
from engine.vocabulary import Zone


# ======================================================================
# 값을 물어본 결과 (Phase 2-AE)
# ======================================================================


class ValueOutcome(str, Enum):
    """
    **값을 물어본 결과.** 수에도 쓰고 도메인에도 쓴다.

    Phase 2-AC 에서 ``CountOutcome`` 이라는 이름으로 태어났는데, 그때는
    답하는 것이 "고를 장수" 뿐이었다. 지금은 드로우 매수도, 선언할 수 있는
    수의 목록도 같은 어휘로 답한다 — 그래서 이름이 넓어졌다. 어휘를 하나
    더 만들지 않은 이유가 그것이다.
    """

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    INVALID = "invalid"
    # FORBIDDEN 은 **여기 없다.** 출처가 실행을 금지하는 것
    # (``TEXT_DERIVED``) 은 값의 문제가 아니라 효과의 문제이고,
    # :class:`~engine.effect.resolution.ResolutionStatus.FORBIDDEN` 이
    # 이미 한 계층 위에서 답한다 (ADR-004). 여기 같은 이름을 하나 더 두면
    # 두 곳이 서로 다른 말을 하게 된다.


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    """
    수를 물어본 **결과**. 숫자 하나가 아니다.

    ``value`` 는 :attr:`ValueOutcome.RESOLVED` 일 때만 있다. 나머지에서는
    ``None`` 이고, **부르는 쪽이 대신 숫자를 만들어 넣지 않는다.**
    """

    outcome: ValueOutcome
    value: "int | None" = None
    reason: str = ""
    missing: "str | None" = None

    def __post_init__(self) -> None:
        if (self.outcome is ValueOutcome.RESOLVED) is not (self.value is not None):
            raise ValueError(
                "RESOLVED 일 때만 수가 있습니다. 모르는 수를 숫자로 적으면 "
                "그 숫자가 규칙이 됩니다."
            )

    def __bool__(self):  # pragma: no cover - 부르면 안 된다
        raise TypeError(
            "ResolvedValue 를 참/거짓으로 쓰지 마십시오. UNKNOWN 이 거짓이 "
            "되면 '모른다' 가 '안 된다' 로 접힙니다."
        )


@dataclass(frozen=True, slots=True)
class ValueRef:
    """
    실행 중에 생기는 **수**의 이름.

    :class:`~engine.effect.target.TargetRef` 와 **다른 타입**이다. 저쪽은
    고른 카드의 이름이고 이쪽은 선언한 수의 이름이다 — 같은 타입으로
    만들면 "2장" 과 "2" 가 한 이름 공간에 섞인다.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("값의 이름이 비어 있습니다.")

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"#{self.name}"


#: 수를 하나만 선언하는 효과가 쓰는 이름.
DECLARED_NUMBER = ValueRef("declared")


@dataclass(frozen=True, slots=True)
class NumberDomain:
    """
    선언할 수 있는 **수의 집합.**

    목록이다. 범위가 아니다 — 공식 스크립트의
    ``Duel.AnnounceNumber(tp, ...)`` 가 **고를 수 있는 수를 하나하나
    나열한다**\\ 는 사실을 그대로 옮긴 것이다.

    ::

        Duel.AnnounceNumber(p,1,2)      → {1, 2}
        Duel.AnnounceNumber(p,1,2,3)    → {1, 2, 3}
        Duel.AnnounceNumber(tp,100,200,300,400,500)

    :meth:`between` 은 연속한 수를 적는 **줄임말**이지 다른 종류가 아니다.
    범위와 목록을 다른 갈래로 두면 "1~3" 과 "{1,2,3}" 이 서로 다른 것처럼
    보이는데, 스크립트에서 둘은 같은 것이다.
    """

    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError("values 는 tuple 이어야 합니다 — 명세는 불변입니다.")
        if not self.values:
            raise ValueError(
                "선언할 수 있는 수가 하나도 없습니다. 고를 것이 없으면 "
                "선언이 아니라 조건입니다."
            )
        if len(set(self.values)) != len(self.values):
            raise ValueError(f"같은 수가 두 번 있습니다: {self.values}")
        if sorted(self.values) != list(self.values):
            raise ValueError(
                f"수는 오름차순으로 적습니다: {self.values}. 순서가 다르면 "
                "같은 집합이 여러 모양으로 적히고, 정규 표현이 흔들립니다."
            )

    @classmethod
    def exact(cls, value: int) -> "NumberDomain":
        """고를 것이 하나뿐이다. **그래도 선언이다** — 사람이 정한다."""
        return cls((value,))

    @classmethod
    def between(cls, low: int, high: int) -> "NumberDomain":
        """``low`` 부터 ``high`` 까지 연속한 수. 목록을 적는 줄임말이다."""
        if high < low:
            raise ValueError(f"끝({high})이 시작({low})보다 작습니다.")
        return cls(tuple(range(low, high + 1)))

    @classmethod
    def of(cls, *values: int) -> "NumberDomain":
        return cls(tuple(values))

    def allows(self, value: int) -> bool:
        return value in self.values

    @property
    def only(self) -> "int | None":
        """고를 것이 하나뿐이면 그 수. 아니면 ``None``."""
        return self.values[0] if len(self.values) == 1 else None

    def canonical_state(self) -> tuple:
        return self.values

    def to_dict(self) -> dict:
        return {"values": list(self.values)}

    def describe_ko(self) -> str:
        return "{" + ", ".join(str(v) for v in self.values) + "} 중 하나"

    def __contains__(self, value: int) -> bool:
        return self.allows(value)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class QuantitySource(str, Enum):
    """
    판에서 **무엇을 세는가** (Phase 2-AE).

    둘뿐이다. 실제 카드가 선언 도메인을 만들 때 쓰는 것이 이 둘이기
    때문이고 (자리 장수 · 라이프), 더 필요해지면 그때 근거를 들고 온다.
    """

    ZONE_COUNT = "zone_count"
    LIFE_POINTS = "life_points"


@dataclass(frozen=True, slots=True)
class BoardQuantity:
    """
    판에서 읽는 **양 하나.**

    이것은 **관측이 아니라 규칙이 아는 사실**이다. 상대 패가 몇 장인지,
    누가 라이프가 얼마인지는 누가 보느냐와 무관하게 정해져 있다 —
    카드의 **정체**와는 다른 정보다 (Phase 2-AC §9 와 같은 구분).
    """

    source: QuantitySource
    player: PlayerRef = PlayerRef.CONTROLLER
    zone: "Zone | None" = None

    def __post_init__(self) -> None:
        if self.source is QuantitySource.ZONE_COUNT and self.zone is None:
            raise ValueError("자리 장수를 세려면 어느 자리인지 적어야 합니다.")
        if self.source is QuantitySource.LIFE_POINTS and self.zone is not None:
            raise ValueError("라이프에는 자리가 없습니다.")

    def canonical_state(self) -> tuple:
        return (
            self.source.value,
            self.player.value,
            self.zone.value if self.zone is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"source": self.source.value, "player": self.player.value}
        if self.zone is not None:
            data["zone"] = self.zone.value
        return data

    def describe_ko(self) -> str:
        if self.source is QuantitySource.LIFE_POINTS:
            return f"{self.player} 의 라이프"
        assert self.zone is not None
        return f"{self.player} {self.zone.value} 의 장수"


class Comparison(str, Enum):
    """
    수를 **어떻게** 견주는가 (Phase 2-AG).

    둘뿐이다. 실제 카드가 조작의 결과를 조건으로 쓰는 자리 97곳을 세어
    보니 **91곳이 0 과 견준다.**

    ========  ===  ==========================================
    ``> 0``    57   하나라도 됐는가
    ``== 0``   26   하나도 안 됐는가
    ``~= 0``    8   하나라도 됐는가
    ``> 1``     2   둘 이상인가
    ``<= 0``    1   하나도 안 됐는가
    ``>= 2``    1   둘 이상인가
    ``>= 1``    1   하나라도 됐는가
    ========  ===  ==========================================

    장수는 음수가 될 수 없으므로 ``> 0`` · ``~= 0`` · ``>= 1`` 은 같은
    질문이고, ``== 0`` · ``<= 0`` 도 같은 질문이다. 그래서 이 둘이면
    96곳이 적힌다.

    ``EQUAL`` · ``NOT_EQUAL`` · ``GREATER_THAN`` · ``LESS_THAN`` 을
    **만들지 않았다.** 정확히 N 은 :attr:`AT_LEAST` 와 :attr:`AT_MOST`
    를 함께 걸면 되고, 나머지는 쓰는 카드를 못 찾았다 — 쓰지 않는
    연산자를 미리 만들면 그것이 옳은지 아무도 확인하지 않는다.
    """

    AT_LEAST = "at_least"
    """``value >= operand``"""
    AT_MOST = "at_most"
    """``value <= operand``"""


@dataclass(frozen=True, slots=True)
class NumericTest:
    """
    수 하나를 견주는 **가장 작은 조건** (Phase 2-AG).

    **값을 구하지 않는다.** 이미 나온 수를 받아 견주기만 한다 — 값을
    정하는 일(:class:`~engine.effect.target.SelectionCount`), 값이
    되는지 보는 일(:class:`ValueDomain`), 그리고 값을 견주는 일은 서로
    다른 세 가지다.

    :class:`~engine.condition.ConditionResult` 를 그대로 돌려준다.
    판정 결과를 나타내는 어휘를 하나 더 만들지 않는다.
    """

    comparison: Comparison
    operand: int

    def __post_init__(self) -> None:
        if self.operand < 0:
            raise ValueError(
                f"견줄 수는 0 이상입니다: {self.operand}. 장수는 음수가 "
                "되지 않으므로 음수와 견주는 조건은 언제나 같은 답입니다."
            )

    def test(self, value: int) -> ConditionResult:
        """
        **수가 있을 때만** 부른다. 수를 모르는 것은 이 타입의 일이 아니라
        부르는 쪽의 사실이고, 그때의 답은 ``UNKNOWN`` 이다 — 그것을
        여기서 ``FALSE`` 로 접지 않으려고 아예 받지 않는다.
        """
        if self.comparison is Comparison.AT_LEAST:
            return ConditionResult.from_bool(value >= self.operand)
        return ConditionResult.from_bool(value <= self.operand)

    def canonical_state(self) -> tuple:
        return (self.comparison.value, self.operand)

    def to_dict(self) -> dict:
        return {"comparison": self.comparison.value, "operand": self.operand}

    def describe_ko(self) -> str:
        word = "이상" if self.comparison is Comparison.AT_LEAST else "이하"
        return f"{self.operand} {word}"

    @classmethod
    def at_least(cls, operand: int) -> "NumericTest":
        return cls(Comparison.AT_LEAST, operand)

    @classmethod
    def at_most(cls, operand: int) -> "NumericTest":
        return cls(Comparison.AT_MOST, operand)

    @classmethod
    def any_at_all(cls) -> "NumericTest":
        """
        **하나라도 됐는가** — 97곳 중 66곳이 묻는 바로 그것이다.

        ``> 0`` 과 ``~= 0`` 과 ``>= 1`` 을 한 이름으로 부른다. 장수가
        음수가 될 수 없으므로 셋은 같은 질문이고, 같은 질문을 세 이름으로
        부르면 어느 것을 써야 하는지가 새 문제로 생긴다.
        """
        return cls(Comparison.AT_LEAST, 1)

    @classmethod
    def none_at_all(cls) -> "NumericTest":
        """**하나도 안 됐는가** — 27곳이 묻는다."""
        return cls(Comparison.AT_MOST, 0)


class ValueDomainKind(str, Enum):
    """값이 **어떤 조건을 만족해야 하는가** (Phase 2-AF)."""

    AT_LEAST_ONE = "at_least_one"
    """1 이상. 장수를 다루는 거의 모든 값이 여기다."""
    BOUNDED = "bounded"
    """
    판에서 읽은 양을 **넘지 않는다.**

    실제 카드가 목록을 만들 때 쓰는 모양이다 —
    ``Duel.IsPlayerCanDiscardDeckAsCost(tp, i)`` 는 "덱이 i장 이상인가" 이고
    ``Duel.CheckLPCost(tp, 1000*p)`` 는 "라이프가 1000p 이상인가" 다.
    """
    RULE_UNRESOLVED = "rule_unresolved"
    """
    **값마다 규칙 판정이 필요한데 그 규칙이 없다.**

    언제나 ``UNKNOWN`` 이다. 자리표시가 아니라 **지금 엔진의 정직한
    상태**다 — ``Duel.IsExistingMatchingCard(filter, …, i, g)`` 처럼 "그
    수에 해당하는 카드가 있는가" 를 묻는 도메인이 여기 걸리고, 그것을
    답하려면 조건 계층이 **수를 인자로** 받아야 한다.

    이 갈래가 있어서 "적을 수는 있지만 판정할 수 없다" 를 적을 수 있다.
    없으면 그런 카드는 아예 표현되지 못하거나, 더 나쁘게는 조건 없이
    통과한다.
    """


@dataclass(frozen=True, slots=True)
class DomainVerdict:
    """
    값이 도메인을 만족하는가. **값을 계산한 결과가 아니다.**

    ``ActionValidity`` 를 그대로 쓴다 (Phase 2-B 의 어휘). 판정 결과를
    나타내는 어휘를 하나 더 만들지 않는다 — 같은 질문에 같은 세 답이다.
    """

    validity: ActionValidity
    reason: str = ""
    missing: "str | None" = None

    def __bool__(self):  # pragma: no cover - 부르면 안 된다
        raise TypeError(
            "DomainVerdict 를 참/거짓으로 쓰지 마십시오. UNKNOWN 이 거짓이 "
            "되면 '모른다' 가 '안 된다' 로 접힙니다."
        )


@dataclass(frozen=True, slots=True)
class ValueDomain:
    """
    **계산된 값이 유효한가** 를 묻는 규칙 (Phase 2-AF · STRUCTURAL-89).

    :class:`NumberDomain` 과 **다른 것**이다.

    ==================  ==========================================
    ``NumberDomain``     플레이어가 **고를 수 있는** 수들 (2-AD)
    ``ValueDomain``      이미 정해진 값이 **허용되는가** (2-AF)
    ==================  ==========================================

    앞은 고르기 **전**에 쓰이고 뒤는 값이 나온 **뒤**에 쓰인다. 합치면
    "고를 수 있는 것" 과 "유효한 것" 이 한 값이 되고, 계산된 값(선언이
    아닌 값)을 검사할 자리가 사라진다.

    :class:`SelectionCount` 와도 다르다 — 저쪽은 "몇 개인가" 에 답하고
    이쪽은 "그 수가 되는가" 에 답한다. 값과 규칙은 따로 산다.
    """

    kind: ValueDomainKind = ValueDomainKind.AT_LEAST_ONE
    bound: "BoardQuantity | None" = None
    step: int = 1
    missing: str = ""

    def __post_init__(self) -> None:
        if self.kind is ValueDomainKind.BOUNDED and self.bound is None:
            raise ValueError("무엇을 넘지 않아야 하는지 적어야 합니다.")
        if self.kind is not ValueDomainKind.BOUNDED and self.bound is not None:
            raise ValueError(f"{self.kind.value} 에는 한계가 붙지 않습니다.")
        if self.kind is ValueDomainKind.RULE_UNRESOLVED and not self.missing:
            raise ValueError("무엇이 없어서 판정할 수 없는지 적어야 합니다.")
        if self.step < 1:
            raise ValueError(f"간격은 1 이상이어야 합니다: {self.step}")

    @classmethod
    def at_least_one(cls) -> "ValueDomain":
        return cls(ValueDomainKind.AT_LEAST_ONE)

    @classmethod
    def bounded_by(cls, bound: "BoardQuantity", step: int = 1) -> "ValueDomain":
        return cls(ValueDomainKind.BOUNDED, bound=bound, step=step)

    @classmethod
    def unresolved(cls, missing: str) -> "ValueDomain":
        return cls(ValueDomainKind.RULE_UNRESOLVED, missing=missing)

    def validate(self, value: int, read=None) -> DomainVerdict:
        """
        ``value`` 가 이 도메인을 만족하는가.

        **값을 계산하지 않는다.** 이미 나온 값을 받아서 판정만 한다
        (§12 의 책임 분리). ``read`` 는 판에서 양을 읽어 주는 함수이고,
        판을 봐야 하는 도메인에서만 쓴다.
        """
        if self.kind is ValueDomainKind.RULE_UNRESOLVED:
            return DomainVerdict(
                ActionValidity.UNKNOWN,
                reason=(
                    f"{value} 가 되는지 판정할 규칙이 없습니다: {self.missing}"
                ),
                missing=self.missing,
            )
        if value < 1:
            return DomainVerdict(
                ActionValidity.INVALID,
                reason=f"{value} 는 1 이상이어야 합니다.",
            )
        if self.kind is ValueDomainKind.AT_LEAST_ONE:
            return DomainVerdict(ActionValidity.VALID)

        assert self.bound is not None
        if read is None:
            # **판을 못 봤다는 사실을 숫자로 덮지 않는다.**
            return DomainVerdict(
                ActionValidity.UNKNOWN,
                reason=f"{self.bound.describe_ko()} 를 읽을 수 없습니다.",
                missing=self.bound.describe_ko(),
            )
        amount = read(self.bound)
        if amount is None:
            return DomainVerdict(
                ActionValidity.UNKNOWN,
                reason=f"{self.bound.describe_ko()} 를 읽지 못했습니다.",
                missing=self.bound.describe_ko(),
            )
        if value * self.step > amount:
            return DomainVerdict(
                ActionValidity.INVALID,
                reason=(
                    f"{value}"
                    + (f" x{self.step}" if self.step != 1 else "")
                    + f" 는 {self.bound.describe_ko()}({amount})를 넘습니다."
                ),
            )
        return DomainVerdict(ActionValidity.VALID)

    def canonical_state(self) -> tuple:
        return (
            self.kind.value,
            self.bound.canonical_state() if self.bound is not None else None,
            self.step,
            self.missing,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": self.kind.value}
        if self.bound is not None:
            data["bound"] = self.bound.to_dict()
        if self.step != 1:
            data["step"] = self.step
        if self.missing:
            data["missing"] = self.missing
        return data

    def describe_ko(self) -> str:
        if self.kind is ValueDomainKind.AT_LEAST_ONE:
            return "1 이상"
        if self.kind is ValueDomainKind.RULE_UNRESOLVED:
            return f"판정 불가 ({self.missing})"
        assert self.bound is not None
        unit = f" x{self.step}" if self.step != 1 else ""
        return f"{self.bound.describe_ko()} 이하{unit}"


@dataclass(frozen=True, slots=True)
class ResolvedDomain:
    """도메인을 물어본 결과. ``RESOLVED`` 일 때만 목록이 있다."""

    outcome: ValueOutcome
    domain: "NumberDomain | None" = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.outcome is ValueOutcome.RESOLVED) is not (self.domain is not None):
            raise ValueError(
                "RESOLVED 일 때만 목록이 있습니다. 고를 수 없는 것을 고를 수 "
                "있는 것처럼 적으면 그 목록이 규칙이 됩니다."
            )

    def __bool__(self):  # pragma: no cover - 부르면 안 된다
        raise TypeError(
            "ResolvedDomain 을 참/거짓으로 쓰지 마십시오. UNKNOWN 이 거짓이 "
            "되면 '모른다' 가 '안 된다' 로 접힙니다."
        )


@dataclass(frozen=True, slots=True)
class DerivedNumberDomain:
    """
    **판에서 만들어지는** 선언 도메인 (Phase 2-AE · STRUCTURAL-85).

    모양은 하나다 — ``step`` 의 배수를 ``bound`` 를 넘지 않을 때까지.

    ::

        for i=1,math.floor(lp/1000) do t[i]=i*1000 end   -- 광명의 벽
        → DerivedNumberDomain(BoardQuantity(LIFE_POINTS), step=1000)

        for i=1,#g do table.insert(nums,i) end
        → DerivedNumberDomain(BoardQuantity(ZONE_COUNT, ..., zone), step=1)

    **수식 언어가 아니다.** 실제 카드가 목록을 만드는 방식을 센 결과, 이
    한 모양이 계산 가능한 것의 대부분이고 나머지는 값마다 규칙 판정이
    필요하다 (그것은 ``UNKNOWN`` 으로 남는다).

    :class:`NumberDomain` 과 **다른 타입**이다. 저쪽은 정의에 적힌 목록,
    이쪽은 "판을 보고 만들어라" 는 지시다. 합치면 "목록이 적혀 있는데
    비어 있다" 와 "아직 안 만들었다" 가 같은 값이 된다.
    """

    bound: BoardQuantity
    step: int = 1

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError(f"간격은 1 이상이어야 합니다: {self.step}")

    def resolve(self, read) -> ResolvedDomain:
        """
        이번 판에서 고를 수 있는 수들.

        ``read`` 는 ``(BoardQuantity) -> int | None`` 이다. 판을 아는 쪽이
        건네준다 — 이 타입은 :class:`~engine.state.game_state.GameState` 를
        알지 못한다.
        """
        amount = read(self.bound)
        if amount is None:
            return ResolvedDomain(
                ValueOutcome.UNKNOWN,
                reason=f"{self.bound.describe_ko()} 를 읽지 못했습니다.",
            )
        count = amount // self.step
        if count < 1:
            # **비어 있는 목록을 만들지 않는다.** 고를 것이 없으면 그것은
            # 선언이 아니라 조건이고, 조건은 발동 단계가 답할 일이다.
            return ResolvedDomain(
                ValueOutcome.INVALID,
                reason=(
                    f"{self.bound.describe_ko()} 가 {amount} 라서 "
                    f"{self.step} 의 배수를 하나도 고를 수 없습니다."
                ),
            )
        return ResolvedDomain(
            ValueOutcome.RESOLVED,
            domain=NumberDomain(tuple(self.step * i for i in range(1, count + 1))),
        )

    def canonical_state(self) -> tuple:
        return ("derived", self.bound.canonical_state(), self.step)

    def to_dict(self) -> dict:
        return {"kind": "derived", "bound": self.bound.to_dict(), "step": self.step}

    def describe_ko(self) -> str:
        unit = "" if self.step == 1 else f"{self.step} 의 배수로 "
        return f"{self.bound.describe_ko()} 까지 {unit}하나"


@dataclass(frozen=True, slots=True)
class DeclaredNumberSpec:
    """
    "누가 어떤 수를 선언하는가" 라는 **요구.** 선언된 값이 아니다.

    ``chooser`` 는 기존 어휘 그대로 :class:`~engine.condition.PlayerRef`
    다 (``ChoiceSpec.chooser`` 와 같은 뜻, 같은 해석). 그래서 **효과의
    컨트롤러가 아닌 사람이 선언하는 것**을 적을 수 있다 — 부작용?
    (30922149)에서 수를 정하는 것은 뽑는 쪽, 즉 상대다.
    """

    domain: "NumberDomain | DerivedNumberDomain"
    """
    적힌 목록이거나, **판에서 만들라는 지시**다 (Phase 2-AE).
    """
    chooser: PlayerRef = PlayerRef.CONTROLLER

    @property
    def is_derived(self) -> bool:
        """도메인을 판에서 만들어야 하는가."""
        return isinstance(self.domain, DerivedNumberDomain)

    def canonical_state(self) -> tuple:
        return (self.domain.canonical_state(), self.chooser.value)

    def to_dict(self) -> dict:
        return {"domain": self.domain.to_dict(), "chooser": self.chooser.value}

    def describe_ko(self) -> str:
        return f"{self.chooser} 가 {self.domain.describe_ko()} 를 선언"


@dataclass(frozen=True, slots=True)
class DeclarationBinding:
    """이름과 선언 규칙을 잇는다 (``TargetBinding`` 과 같은 자리)."""

    ref: ValueRef
    spec: DeclaredNumberSpec

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.spec.canonical_state())

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "spec": self.spec.to_dict()}


@dataclass(frozen=True, slots=True)
class DeclaredNumber:
    """
    플레이어가 **실제로 선언한 수** (``TargetSelection`` 과 같은 자리).

    규칙이 아니라 입력이다. 그래서 정의가 아니라 문맥으로 들어온다.
    """

    ref: ValueRef
    value: int

    def canonical_state(self) -> tuple:
        return (self.ref.name, self.value)

    def to_dict(self) -> dict:
        return {"ref": self.ref.name, "value": self.value}


class DeclarationOutcome(str, Enum):
    """선언을 물어본 결과."""

    RESOLVED = "resolved"
    PENDING = "pending"
    """**아직 선언하지 않았다.** 대신 정해 주지 않는다."""
    INVALID = "invalid"
    """허용되지 않은 수를 선언했다. **가까운 수로 고쳐 주지 않는다.**"""
    # FORBIDDEN 은 여기 없다. 출처가 실행을 금지하는 것(``TEXT_DERIVED``)은
    # 선언의 문제가 아니라 효과의 문제이고, 실행기가 계획을 시작하기 전에
    # 이미 ``ResolutionStatus.FORBIDDEN`` 으로 답한다 (ADR-004).


@dataclass(frozen=True, slots=True)
class ResolvedDeclaration:
    """물어본 결과. ``RESOLVED`` 일 때만 수가 있다."""

    outcome: DeclarationOutcome
    value: "int | None" = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.outcome is DeclarationOutcome.RESOLVED) is not (
            self.value is not None
        ):
            raise ValueError(
                "RESOLVED 일 때만 수가 있습니다. 정해지지 않은 수를 숫자로 "
                "적으면 그 숫자가 규칙이 됩니다."
            )

    def __bool__(self):  # pragma: no cover - 부르면 안 된다
        raise TypeError(
            "ResolvedDeclaration 을 참/거짓으로 쓰지 마십시오. PENDING 이 "
            "거짓이 되면 '아직 안 정했다' 가 '안 된다' 로 접힙니다."
        )


class OperationOutcome(str, Enum):
    """
    조작 하나가 **규칙대로 되었는가** (Phase 2-AE).

    처리한 장수와 **다른 질문이다.** 0장을 다뤘어도 규칙대로 된 것일 수
    있고 ("최대 2장까지" 에서 0장을 고른 경우), 2장을 다뤘어도 규칙을 다
    보지 못했을 수 있다.

    ``FAILED`` 가 **없다.** 없는 이유를 적어 둔다.

        이 실행기는 계획이 전부 끝난 뒤에야 적용을 시작한다. 계획에서
        막힌 조작은 **결과를 남기지 않는다** — 효과 전체가 거절되고
        아무 일도 일어나지 않기 때문이다. 그래서 "실패한 조작의 결과"
        라는 것이 존재할 수 없다.

        실패는 조작이 아니라 **효과 단위**의 사실이고, 그것은
        :class:`~engine.effect.resolution.ResolutionStatus` 가 이미
        답한다. 같은 말을 두 어휘로 하지 않는다.

    여기 ``FAILED`` 를 두면 **언제나 거짓인 값**이 생기고, 그것을 읽은
    쪽은 규칙을 지켰다고 믿게 된다.
    """

    SUCCEEDED = "succeeded"
    """계획대로 적용되고, 그 조작이 주장한 규칙을 **전부 봤다.**"""
    NOT_APPLIED = "not_applied"
    """
    **일어나지 않았다.** 조건이 거짓이어서 건너뛴 일이다 (Phase 2-AG).

    실패가 아니다 — 규칙이 "하지 말라" 고 한 것을 그대로 따른 것이고,
    효과는 정상적으로 해결된다. 그래서 ``FAILED`` 와 **다른 값**이다
    (그리고 ``FAILED`` 는 여전히 없다).

    건너뛴 일에는 장수가 **없다.** 0 이 아니다 — "0장을 다뤘다" 와
    "하지 않았다" 는 다른 사실이고, 뒤의 일이 이것을 수로 읽으려 하면
    ``UNKNOWN`` 으로 멈춘다.
    """
    UNKNOWN = "unknown"
    """
    일어나기는 했지만 **규칙대로였는지 말할 수 없다.**

    Phase 2-M 이 적어 둔 미확인 규칙이 있는 의미가 여기다 — 묘지로
    보내면서 "묘지로 보내는 것을 막는 효과" 를 보지 않았다면, 카드는
    움직였어도 그것이 규칙대로였다고 주장할 수 없다.

    **보수적으로 잡는다.** 미확인 규칙 중에는 성패와 무관한 것도 있지만
    (예: "'파괴되었을 때' 유발 효과"), 그것을 갈라 읽으려면 규칙을
    새로 판정해야 한다. 모르는 쪽으로 기울이는 것이 이 프로젝트의
    기본값이다.
    """


class ResultField(str, Enum):
    """앞선 조작에서 **무엇을** 가져오는가."""

    ATTEMPTED_COUNT = "attempted_count"
    """
    그 조작이 **하려고 한** 수 (Phase 2-AF).

    처리된 수와 **다른 질문이다.** 셋을 고르고 둘만 처리됐다면 시도는
    3 이고 처리는 2 다. 실패한 수를 따로 저장하지 않는 이유는 그것이
    이 둘의 차이이기 때문이다 — 같은 정보를 두 번 적지 않는다.
    """
    AFFECTED_COUNT = "affected_count"
    """
    그 조작이 실제로 다룬 **수.**

    카드를 옮기는 일이면 장수, 드로우면 뽑은 장수다. 라이프 증감처럼
    "장수" 가 없는 일에는 **없다** — 없는 것을 0 으로 답하지 않는다.
    """
    SUCCEEDED = "succeeded"
    """
    그 조작이 **규칙대로 되었는가** (Phase 2-AE).

    수가 아니다. 그래서 장수를 묻는 자리에 쓸 수 없고,
    :class:`OperationRequirement` 로만 가리킨다.

    Phase 2-AD 는 이 칸을 만들지 않았다. "앞이 실패하면 뒤는 시작조차
    하지 않으므로 언제나 참" 이라고 보았기 때문이다. 그 판단은 절반만
    맞았다 — ``FAILED`` 는 정말로 생기지 않지만, **``UNKNOWN`` 은
    생긴다.** 규칙을 다 보지 못한 채 일어난 조작이 있고, 그 위에 다음
    일을 쌓아도 되는지는 다른 질문이다.
    """


@dataclass(frozen=True, slots=True)
class ResultRef:
    """
    **몇 번째 조작의 무엇**을 가져오는가.

    ``operation_index`` 는 정의의 ``operations`` 안 자리다. 새 식별자
    체계를 만들지 않은 이유는, 정의가 불변이므로 그 자리가 이미 그
    조작의 신원이기 때문이다.

    자기보다 **앞**을 가리켜야 한다는 것을
    :class:`~engine.effect.definition.EffectDefinition` 이 만들 때
    검사한다 — 뒤를 가리키면 아직 일어나지 않은 일을 읽는 셈이다.
    """

    operation_index: int
    field: ResultField = ResultField.AFFECTED_COUNT
    multiplier: int = 1
    """
    가져온 수에 곱한다. 실제 카드가 ``dr*2000`` 처럼 쓰기 때문이고
    (부작용? 30922149), 그 이상은 하지 않는다 — 수식 언어가 아니다.
    """

    def __post_init__(self) -> None:
        if self.operation_index < 0:
            raise ValueError(
                f"조작 번호는 0 이상입니다: {self.operation_index}"
            )

    def canonical_state(self) -> tuple:
        return (self.operation_index, self.field.value, self.multiplier)

    def to_dict(self) -> dict:
        data: dict = {
            "operation_index": self.operation_index,
            "field": self.field.value,
        }
        if self.multiplier != 1:
            data["multiplier"] = self.multiplier
        return data

    def describe_ko(self) -> str:
        times = f" x{self.multiplier}" if self.multiplier != 1 else ""
        return f"{self.operation_index}번 조작의 {self.field.value}{times}"


@dataclass(frozen=True, slots=True)
class OperationRequirement:
    """
    **이 조작은 저 조작이 규칙대로 되었어야 한다** (Phase 2-AE).

    실제 카드가 그렇게 적혀 있다 — ``local ct=Duel.Destroy(...)`` 뒤의
    ``if ct~=0 then <다음 일> end`` 이 corpus 에 92곳이다.

    ``operation_index`` 는 **가리키는 쪽**, ``after`` 는 **가리켜지는
    쪽**이고, 둘 다 정의의 ``operations`` 안 자리다. 가리켜지는 쪽이
    반드시 앞이어야 한다는 것을 정의가 만들어질 때 검사한다 (Phase 2-AD
    와 같은 규칙).

    **건너뛰지 않는다.** 앞이 ``UNKNOWN`` 이면 효과 전체를 거절한다 —
    이 실행기에는 부분 적용이 없고, 모르는 것 위에 다음 일을 쌓지
    않는다. 앞이 ``FAILED`` 인 경우는 애초에 오지 않는다
    (:class:`OperationOutcome` 참고).
    """

    operation_index: int
    after: "ResultRef"

    def __post_init__(self) -> None:
        if self.operation_index < 0:
            raise ValueError(f"조작 번호는 0 이상입니다: {self.operation_index}")
        if self.after.field is not ResultField.SUCCEEDED:
            raise ValueError(
                f"조건으로 쓸 수 있는 것은 성패뿐입니다: {self.after.field}. "
                "수를 조건처럼 읽는 것이 바로 이 단계가 막으려는 일입니다."
            )

    def canonical_state(self) -> tuple:
        return (self.operation_index, self.after.canonical_state())

    def to_dict(self) -> dict:
        return {
            "operation_index": self.operation_index,
            "after": self.after.to_dict(),
        }

    def describe_ko(self) -> str:
        return (
            f"{self.operation_index}번 조작은 "
            f"{self.after.operation_index}번 조작이 규칙대로 되었어야 한다"
        )


@dataclass(frozen=True, slots=True)
class OperationResult:
    """
    조작 하나가 **낸 결과.** 사건이 아니다.

    :class:`~engine.effect.delta.StateDelta` 나
    :class:`~engine.event_pipeline.ObservedEvent` 와 **다른 것**이다.

    ==================  ==============================================
    ``OperationResult``  그 일이 무엇을 얼마나 했는가 — 해결 중의 참조용
    ``StateDelta``       판의 어디가 어떻게 바뀌었는가
    ``ObservedEvent``    무슨 사건이 일어났는가 — 기록과 반응용
    ==================  ==============================================

    앞의 일을 뒤의 일이 읽어야 할 때 ``EventJournal`` 을 뒤지지 않는
    이유가 이것이다. 저널은 **역사**이고 여기는 **지금 해결의 중간
    결과**다. 역사를 뒤져서 수를 짐작하면, 같은 효과가 두 번 돌았을 때
    어느 것을 읽었는지 알 수 없다.
    """

    operation_index: int
    affected_count: "int | None" = None
    outcome: OperationOutcome = OperationOutcome.SUCCEEDED
    attempted_count: "int | None" = None
    """
    **하려고 한** 수 (Phase 2-AF). ``None`` 이면 세지 않는 종류의 일이다.

    부분 적용은 이 둘의 관계로 읽는다. 상태를 하나 더 만들지 않은 이유는
    **파생되기 때문**이다 — 저장하면 두 값이 어긋날 수 있다.
    """
    """
    규칙대로 되었는가 (Phase 2-AE). **장수와 독립이다** —
    ``affected_count == 0`` 을 실패로 읽지 않는다.
    """

    @property
    def was_applied(self) -> bool:
        """이 일이 실제로 일어났는가 (Phase 2-AG)."""
        return self.outcome is not OperationOutcome.NOT_APPLIED

    @property
    def is_complete(self) -> bool:
        """하려던 것을 **전부** 했는가."""
        return (
            self.attempted_count is not None
            and self.affected_count == self.attempted_count
        )

    @property
    def is_partial(self) -> bool:
        """
        **일부만** 했는가. 실패가 아니다 — 카드가 "가능한 만큼" 이라고
        적어 두었을 때 일어나는 **정상적인 결과**다.
        """
        return (
            self.attempted_count is not None
            and self.affected_count is not None
            and 0 < self.affected_count < self.attempted_count
        )

    @property
    def did_nothing(self) -> bool:
        """하려고 했는데 **하나도** 못 했는가."""
        return (
            self.attempted_count is not None
            and bool(self.attempted_count)
            and self.affected_count == 0
        )

    def value_of(self, field: ResultField) -> "int | None":
        if field is ResultField.ATTEMPTED_COUNT:
            return self.attempted_count
        if field is ResultField.AFFECTED_COUNT:
            return self.affected_count
        raise KeyError(
            f"{field} 는 수가 아닙니다. 성패는 OperationRequirement 로 "
            "가리킵니다."
        )

    def canonical_state(self) -> tuple:
        return (
            self.operation_index,
            self.affected_count,
            self.outcome.value,
            self.attempted_count,
        )

    def to_dict(self) -> dict:
        return {
            "operation_index": self.operation_index,
            "affected_count": self.affected_count,
            "attempted_count": self.attempted_count,
            "outcome": self.outcome.value,
        }


class ExecutionLookupError(LookupError):
    """실행 중의 값을 이름으로 찾지 못했다. **0 으로 때우지 않는다.**"""


@dataclass(frozen=True, slots=True)
class ExecutionValues:
    """
    이번 해결 **한 번** 동안의 값들.

    불변이다. 조작을 계획할 때마다 결과가 하나씩 붙은 **새 값**이 생기고,
    앞의 값은 그대로 남는다 — 누가 언제 무엇을 읽었는지가 값에 남는다.

    복제와 독립은 따로 지킬 것이 없다. 이 값은 판에 붙어 있지 않고
    :meth:`~engine.effect.executor.EffectExecutor.execute` 한 번 안에서만
    살기 때문이다.
    """

    declarations: tuple[DeclaredNumber, ...] = ()
    results: tuple[OperationResult, ...] = ()

    def with_result(self, result: OperationResult) -> "ExecutionValues":
        """결과 하나를 더한 **새** 값."""
        return ExecutionValues(self.declarations, self.results + (result,))

    def declared(
        self, ref: ValueRef, spec: "DeclaredNumberSpec | None" = None
    ) -> ResolvedDeclaration:
        """
        그 이름으로 선언된 수.

        ``spec`` 을 주면 허용된 수인지까지 본다. 주지 않으면 **검사하지
        않았다는 뜻**이지 통과했다는 뜻이 아니다.
        """
        found = [d for d in self.declarations if d.ref == ref]
        if not found:
            return ResolvedDeclaration(
                DeclarationOutcome.PENDING,
                reason=f"{ref} 를 아직 선언하지 않았습니다.",
            )
        if len(found) > 1:
            return ResolvedDeclaration(
                DeclarationOutcome.INVALID,
                reason=f"{ref} 에 수가 두 번 들어왔습니다.",
            )
        value = found[0].value
        if spec is not None and not spec.domain.allows(value):
            return ResolvedDeclaration(
                DeclarationOutcome.INVALID,
                reason=(
                    f"{ref} 에 {value} 를 선언했는데 고를 수 있는 것은 "
                    f"{spec.domain.describe_ko()} 입니다."
                ),
            )
        return ResolvedDeclaration(DeclarationOutcome.RESOLVED, value=value)

    def result(self, ref: ResultRef) -> int:
        """
        그 조작이 낸 수. 없으면 :class:`ExecutionLookupError`.

        조용히 0 을 돌려주지 않는다 — "아무것도 안 했다" 와 "그 일이
        아직 없다" 는 다른 사실이고, 전자를 후자로 읽으면 뒤의 일이
        0장을 다룬 척 지나간다.
        """
        for result in self.results:
            if result.operation_index == ref.operation_index:
                value = result.value_of(ref.field)
                if value is None:
                    raise ExecutionLookupError(
                        f"{ref.operation_index}번 조작에는 "
                        f"{ref.field.value} 가 없습니다."
                    )
                return value * ref.multiplier
        raise ExecutionLookupError(
            f"{ref.operation_index}번 조작의 결과가 아직 없습니다."
        )

    def outcome_of(self, operation_index: int) -> "OperationOutcome | None":
        """
        그 조작이 규칙대로 되었는가. 결과가 아직 없으면 ``None``.

        **수를 돌려주지 않는다.** 성패와 장수는 다른 질문이고, 한 함수가
        둘 다 답하면 부르는 쪽에서 섞인다.
        """
        for result in self.results:
            if result.operation_index == operation_index:
                return result.outcome
        return None

    def chooser_of(
        self, spec: DeclaredNumberSpec, context: ConditionContext
    ) -> int:
        """수를 선언하는 사람. 기존 ``PlayerRef`` 해석을 그대로 쓴다."""
        return spec.chooser.resolve(context)

    def canonical_state(self) -> tuple:
        return (
            tuple(d.canonical_state() for d in self.declarations),
            tuple(r.canonical_state() for r in self.results),
        )

    def to_dict(self) -> dict:
        return {
            "declarations": [d.to_dict() for d in self.declarations],
            "results": [r.to_dict() for r in self.results],
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<ExecutionValues 선언 {len(self.declarations)} "
            f"결과 {len(self.results)}>"
        )


#: 실행 중에 생긴 값이 **하나도 없는** 상태.
#:
#: ``None`` 을 쓰지 않는 이유는, 없는 것과 "모른다" 를 구별하기 위해서다 —
#: 이 값에 선언을 물으면 ``PENDING`` 이 나오고, 그것이 사실이다.
NO_EXECUTION_VALUES = ExecutionValues()


__all__ = [
    "Comparison",
    "NumericTest",
    "ValueDomain",
    "ValueDomainKind",
    "DomainVerdict",
    "ValueOutcome",
    "ResolvedValue",
    "QuantitySource",
    "BoardQuantity",
    "DerivedNumberDomain",
    "ResolvedDomain",
    "OperationOutcome",
    "OperationRequirement",
    "ValueRef",
    "DECLARED_NUMBER",
    "NumberDomain",
    "DeclaredNumberSpec",
    "DeclarationBinding",
    "DeclaredNumber",
    "DeclarationOutcome",
    "ResolvedDeclaration",
    "ResultField",
    "ResultRef",
    "OperationResult",
    "ExecutionValues",
    "ExecutionLookupError",
    "NO_EXECUTION_VALUES",
]
