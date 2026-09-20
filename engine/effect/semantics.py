"""
의미 계층 — **무엇을 한 것인가**를 저수준 이동과 분리해서 붙든다.

    DESTROY        파괴한다
    SEND_TO_GRAVE  묘지로 보낸다
    DISCARD        버린다
        ↓  전부 결국 묘지로 간다
    MOVE           그냥 옮긴다 (Phase 2-L, 의미 없음)

넷의 **최종 목적지가 같다.** 그래서 목적지로는 구분할 수 없고, 구분이
사라지면 "파괴되었을 때" 와 "묘지로 보내졌을 때" 를 영영 나눌 수 없다
(ADR-002). 이 파일은 그 구분을 **값으로** 들고 있는 곳이다.

여기서 하는 일은 넷뿐이다
-------------------------
1. 어떤 일이 **의미를 주장하는가** (:data:`SEMANTIC_KINDS`).
2. 그 의미가 **어디서 출발할 수 있는가** (:data:`ORIGIN_RULES`).
3. 그 의미의 규칙 중 **아직 보지 않은 것**이 무엇인가
   (:data:`UNCHECKED_SEMANTIC_RULES`).
4. 그 의미 중 **판정 없이는 실행할 수 없는 것**이 무엇인가
   (:data:`RULE_GATED`).

적어 두는 것과 막는 것은 다르다
-------------------------------
Phase 2-M 은 세 번째까지만 했다 — 파괴를 실행하면서 "내성을 보지 않았다" 고
**적어 두었다.** 그것으로 충분하지 않다.

    UNKNOWN 은 허가가 아니다.

내성을 판정할 수 없는데 파괴를 수행하면, 내성을 가진 카드가 실제로
파괴된다. 적어 둔 메모는 그것을 막지 못한다. 그래서 :data:`RULE_GATED` 에
든 의미는 **판정을 받아야만** 실행된다 (:class:`DestructionRuling`).

판정기가 없으면 어떤 파괴도 일어나지 않는다. 그것이
:class:`UnknownDestructionRuling` 이고, 지금 엔진의 기본값이다 —
``EmptyImplementationLookup`` 이 "등록된 구현이 없다" 를 기본값으로 삼은
것과 같은 자리다 (ADR-006).

여기서 하지 않는 것
-------------------
판을 바꾸지 않는다. ``GameState`` 를 가져오지도 않는다 — 실행은
:class:`~engine.effect.executor.EffectExecutor` 하나의 일이고, 이 파일은
그 실행기가 참고하는 **표**다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from engine.condition import ConditionResult
from engine.effect.operation import OperationKind
from engine.ids import InstanceId
from engine.vocabulary import Zone

#: 필드. 파괴가 일어날 수 있는 자리다.
FIELD_ZONES: frozenset[Zone] = frozenset(
    {Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.PZONE}
)

#: **의미를 주장하는** 일들. 이번 단계가 다루는 셋이다.
#:
#: ``RELEASE`` · ``BANISH`` · ``RETURN_*`` 도 의미를 주장하지만 이번 단계의
#: 범위가 아니다 — 표에 넣으면 "규칙을 봤다" 는 뜻이 되므로 넣지 않는다.
SEMANTIC_KINDS: frozenset[OperationKind] = frozenset(
    {
        OperationKind.DESTROY,
        OperationKind.SEND_TO_GRAVE,
        OperationKind.DISCARD,
    }
)

#: 의미별로 **아직 보지 않은 규칙들.**
#:
#: 실행 결과가 이것을 그대로 들고 나간다
#: (:attr:`~engine.effect.resolution.EffectResult.unchecked_rules`). 실행이
#: 성공해도 이 목록이 비어 있지 않으면 **규칙 전체를 본 것이 아니다.**
UNCHECKED_SEMANTIC_RULES: dict[OperationKind, tuple[str, ...]] = {
    OperationKind.DESTROY: (
        "파괴 내성 (이 카드는 파괴되지 않는다)",
        "파괴 대체 효과 (파괴 대신 다른 일이 일어난다)",
        "'파괴되었을 때' 유발 효과",
        "동시에 파괴될 때의 처리",
        "파괴되었지만 묘지로 가지 않는 경우",
    ),
    OperationKind.SEND_TO_GRAVE: (
        "묘지로 보내는 것을 막는 효과",
        "묘지 대신 다른 곳으로 가는 대체 효과",
        "'묘지로 보내졌을 때' 유발 효과",
    ),
    OperationKind.DISCARD: (
        "버리는 것을 막는 효과",
        "버려진 카드가 묘지 이외로 가는 대체 효과",
        "'버려졌을 때' 유발 효과",
        "무작위로 버리는 경우",
    ),
}


@dataclass(frozen=True, slots=True)
class OriginRule:
    """
    이 의미가 **어디에 있는 카드**에 일어날 수 있는가.

    :attr:`known` 이 중요하다.

    - 참이면 **규칙을 안다.** 어긋나면 확실히 틀린 것이고 거절한다.
    - 거짓이면 **이 엔진이 모른다.** 어긋나면 "못 한다" 로 거절하고
      :attr:`missing` 에 무엇이 없는지 적는다. "안 된다" 고 말하지 않는다.

    둘을 합치면 "규칙상 불가능" 과 "아직 안 옮겼다" 가 한 덩어리가 된다.
    """

    zones: frozenset[Zone]
    known: bool
    detail: str
    missing: str | None = None

    def __post_init__(self) -> None:
        if not self.known and not self.missing:
            raise ValueError(
                "모르는 것이라면 무엇이 없어서 모르는지 적어야 합니다."
            )
        if self.known and self.missing:
            raise ValueError(
                "규칙을 아는데 '없는 규칙' 을 적을 수 없습니다."
            )

    def allows(self, zone: Zone) -> bool:
        return zone in self.zones


#: 의미별 출발 자리 규칙. 적히지 않은 일은 **자리를 따지지 않는다.**
#:
#: ``SEND_TO_GRAVE`` 가 여기 없는 것은 우연이 아니다 — 묘지로 보내는 일은
#: 패 · 덱 · 필드 어디서든 일어나고, 이 엔진이 막아야 할 자리를 모른다.
#: 모르는 것을 빈 제약으로 적으면 "전부 허용" 이 규칙인 것처럼 보인다.
ORIGIN_RULES: dict[OperationKind, OriginRule] = {
    OperationKind.DISCARD: OriginRule(
        zones=frozenset({Zone.HAND}),
        known=True,
        detail="버리기는 패에서만 일어납니다",
    ),
    OperationKind.DESTROY: OriginRule(
        zones=FIELD_ZONES,
        known=False,
        detail="필드 밖의 카드를 파괴하는 규칙을 아직 옮기지 않았습니다",
        missing="off-field destruction (필드 밖 파괴 규칙)",
    ),
}


#: **판정을 받아야만 실행되는** 의미들.
#:
#: 여기 든 일은 :data:`UNCHECKED_SEMANTIC_RULES` 를 적어 두는 것으로 끝나지
#: 않는다. 실행 **전에** 판정을 받아야 하고, 받지 못하면 판을 건드리지
#: 않는다.
#:
#: ``SEND_TO_GRAVE`` 와 ``DISCARD`` 는 아직 여기 없다. 둘도 판정되지 않은
#: 규칙을 안고 실행되고 있으며 (STRUCTURAL-48), 같은 원칙이 적용되어야
#: 한다. 다만 그 둘은 Phase 2-D-2 부터의 상태이고 이번 수정의 범위가
#: 아니다 — **알면서 남겨 둔 것이지 괜찮다고 판단한 것이 아니다.**
RULE_GATED: frozenset[OperationKind] = frozenset({OperationKind.DESTROY})

#: 관문을 통과하려면 무엇이 판정되어야 하는가.
GATING_RULES: dict[OperationKind, tuple[str, ...]] = {
    OperationKind.DESTROY: (
        "이 카드가 파괴될 수 있는가 (파괴 내성)",
        "파괴 대신 다른 일이 일어나는가 (대체 효과)",
    ),
}

#: 관문을 여는 계층의 이름. 결과의 ``missing`` 에 그대로 실린다.
MISSING_GATE: dict[OperationKind, str] = {
    OperationKind.DESTROY: "destruction-legality (파괴 내성 · 대체 효과 판정)",
}


@runtime_checkable
class DestructionRuling(Protocol):
    """
    "이 카드를 파괴해도 되는가" 에 답하는 것.

    세 값을 돌려준다 — ``TRUE`` · ``FALSE`` · ``UNKNOWN``. **``UNKNOWN`` 은
    허가가 아니다**: 실행기는 ``TRUE`` 일 때만 파괴한다.
    """

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        ...  # pragma: no cover - 프로토콜


class UnknownDestructionRuling:
    """
    **아무것도 판정하지 못한다.** 지금 엔진의 실제 상태다.

    내성도 대체 효과도 읽을 수 없으므로 모든 카드에 ``UNKNOWN`` 이고,
    따라서 이 판정기로는 **어떤 파괴도 일어나지 않는다.** 그것이 결함이
    아니라 정직한 상태다 — 모르는 것을 허가로 바꾸지 않는다.
    """

    __slots__ = ()

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        return ConditionResult.UNKNOWN

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<UnknownDestructionRuling>"


@dataclass(frozen=True, slots=True)
class DeclaredDestructionRuling:
    """
    **손으로 선언한** 판정. 적히지 않은 카드는 ``UNKNOWN`` 이다.

    내성 계층을 대신하지 않는다 — "이 카드에 대해서는 사람이 확인했다" 를
    값으로 적어 두는 것뿐이고, 그래서 기본값은 여전히 "모른다" 다
    (``EffectImplementationRegistry`` 가 손 등록만 받는 것과 같다).
    """

    destructible: frozenset[InstanceId] = field(default_factory=frozenset)
    """파괴해도 된다고 **확인된** 카드들."""
    protected: frozenset[InstanceId] = field(default_factory=frozenset)
    """파괴되지 않는다고 **확인된** 카드들."""

    def __post_init__(self) -> None:
        both = self.destructible & self.protected
        if both:
            raise ValueError(
                f"같은 카드가 파괴 가능이면서 불가능일 수 없습니다: "
                f"{sorted(i.value for i in both)}"
            )

    def may_be_destroyed(self, instance: InstanceId) -> ConditionResult:
        if instance in self.protected:
            return ConditionResult.FALSE
        if instance in self.destructible:
            return ConditionResult.TRUE
        return ConditionResult.UNKNOWN


def is_rule_gated(kind: OperationKind) -> bool:
    """실행 전에 판정을 받아야 하는 의미인가."""
    return kind in RULE_GATED


def gating_rules(kind: OperationKind) -> tuple[str, ...]:
    """관문이 요구하는 판정들. 관문이 없으면 빈 튜플."""
    return GATING_RULES.get(kind, ())


def is_semantic(kind: OperationKind) -> bool:
    """이 일이 **의미를 주장하는가.** ``MOVE`` 는 거짓이다."""
    return kind in SEMANTIC_KINDS


def unchecked_rules(kind: OperationKind) -> tuple[str, ...]:
    """
    그 의미에서 **아직 보지 않은 규칙들.** 의미가 아닌 일이면 빈 튜플.

    빈 튜플이 "전부 봤다" 를 뜻하지 않는다 — ``MOVE`` 처럼 애초에 주장하는
    의미가 없는 일도 비어 있다.
    """
    return UNCHECKED_SEMANTIC_RULES.get(kind, ())


def origin_rule(kind: OperationKind) -> "OriginRule | None":
    """그 의미의 출발 자리 규칙. 적히지 않았으면 ``None``."""
    return ORIGIN_RULES.get(kind)


def collect_unchecked(kinds) -> tuple[str, ...]:
    """
    여러 일에서 나온 미확인 규칙을 **순서대로, 중복 없이** 모은다.

    순서를 보존하는 이유는 결정론이다 — 집합으로 만들면 같은 입력이 다른
    순서를 낳는다.
    """
    found: list[str] = []
    for kind in kinds:
        for rule in unchecked_rules(kind):
            if rule not in found:
                found.append(rule)
    return tuple(found)


__all__ = [
    "FIELD_ZONES",
    "RULE_GATED",
    "GATING_RULES",
    "MISSING_GATE",
    "DestructionRuling",
    "UnknownDestructionRuling",
    "DeclaredDestructionRuling",
    "is_rule_gated",
    "gating_rules",
    "SEMANTIC_KINDS",
    "UNCHECKED_SEMANTIC_RULES",
    "OriginRule",
    "ORIGIN_RULES",
    "is_semantic",
    "unchecked_rules",
    "origin_rule",
    "collect_unchecked",
]
