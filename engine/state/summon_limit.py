"""
이 턴에 **무엇을 특수 소환할 수 없는가** — 효과가 걸어 둔 제한 (Phase 6-AO).

    "이 효과의 발동 후, 턴 종료시까지 자신은 어둠 속성 몬스터밖에
     특수 소환할 수 없다" (오르페골 디베르 57835716 ①)

왜 기존 표로는 안 되는가
------------------------
:mod:`engine.summon_restriction` 은 **필드의 카드**를 훑는다 — 그 카드가
앞면으로 있는 동안 금지가 걸린다는 모양이고, 파슬 다이너 파키세팔로가 그
모양이다. 디베르의 제한은 **다르다**:

- 제한을 만든 카드가 그때 **필드에 없다** (비용으로 제외되었다).
- 제한이 **발동했을 때** 생기고 **턴이 끝나면** 사라진다.
- 막는 범위가 "전부" 가 아니라 **속성 하나를 뺀 전부**다.

그래서 필드를 훑어서는 이 제한을 찾을 수 없고, 상태에 **적어 두어야** 한다.
:class:`~engine.state.summon_usage.SummonUsageRegistry` 가 "무엇을
소환했는가" 를 적는 것과 같은 자리에 "무엇을 소환할 수 없는가" 를 적는다.

🔴 **판정하지 않는다.** 이 표는 적힌 것을 돌려줄 뿐이고, "그래서 이 소환이
막히는가" 는 :func:`~engine.summon_restriction.assess_special_summon_permission`
이 답한다 (다른 두 표와 같은 태도).

🔴 **지우지 않는다.** 열쇠에 턴 번호가 들어가므로 턴이 바뀔 때 지울 것이
없다 — 지난 턴의 기록이 남아 있는 것은 새는 것이 아니라 역사다.

🔴 **상태 해시에 들어간다.** 들어가지 않으면 "제한이 걸린 판" 과 "걸리지
않은 판" 이 탐색의 중복 제거에서 **같은 상태로 합쳐지고**, 한쪽에서만
합법인 소환이 다른 쪽의 경로로 보고된다 (:meth:`GameState.canonical_state`).
"""

from __future__ import annotations

from dataclasses import dataclass

#: ``(turn_number, player, attribute, source_card_id, ordinal)``
SummonLimitKey = tuple[int, int, str, int, int]


@dataclass(frozen=True, slots=True)
class AttributeOnlyLimit:
    """
    「이 속성밖에 특수 소환할 수 없다」 하나.

    :attr:`attribute` 는 **허용되는** 속성이다 (``"DARK"``). 금지 목록이
    아니라 허용 하나인 것이 공식 문장의 모양이고 (``s.splimit`` 이
    ``return not c:IsAttribute(ATTRIBUTE_DARK)`` 로 **그 밖을** 막는다),
    목록으로 바꿔 적으면 속성이 늘어날 때 뜻이 달라진다.
    """

    turn_number: int
    player: int
    attribute: str
    source_card_id: int
    ordinal: int
    basis: str

    def __post_init__(self) -> None:
        if self.turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {self.turn_number}")
        if self.player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {self.player}")
        if not self.attribute or not self.attribute.isupper():
            raise ValueError(
                f"속성 이름은 EDOPro 상수 이름(대문자)입니다: {self.attribute!r}"
            )
        if self.source_card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.source_card_id}")
        if self.ordinal < 0:
            raise ValueError(f"ordinal 은 0 이상입니다: {self.ordinal}")
        if not self.basis.strip():
            raise ValueError(
                f"{self.source_card_id}: 무엇을 읽고 이 제한을 적었는지 "
                "남겨야 합니다 — 근거 없는 제한은 검증된 규칙이 아닙니다."
            )

    @property
    def key(self) -> SummonLimitKey:
        return (
            self.turn_number,
            self.player,
            self.attribute,
            self.source_card_id,
            self.ordinal,
        )

    def permits(self, attribute: "str | None") -> "bool | None":
        """
        그 속성의 몬스터를 특수 소환할 수 있는가. 속성을 모르면 ``None``.

        🔴 **모름을 허가로 접지 않는다.** 속성을 읽지 못한 카드는 이 제한을
        지나는지 말할 수 없고, 말할 수 없는 것을 통과시키면 제한이 우회된다.
        """
        if attribute is None:
            return None
        return attribute.upper() == self.attribute

    def describe_ko(self) -> str:
        return (
            f"T{self.turn_number} P{self.player}: {self.attribute} 속성 "
            f"몬스터밖에 특수 소환할 수 없다 "
            f"([{self.source_card_id}]:e[{self.ordinal}])"
        )

    def canonical_state(self) -> tuple:
        return self.key

    def to_dict(self) -> dict:
        return {
            "turn": self.turn_number,
            "player": self.player,
            "attribute": self.attribute,
            "source_card_id": self.source_card_id,
            "ordinal": self.ordinal,
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class SummonLimitRegistry:
    """효과가 걸어 둔 특수 소환 제한. **적기만 한다.**"""

    __slots__ = ("limits",)

    def __init__(self, limits: "dict[SummonLimitKey, AttributeOnlyLimit] | None" = None):
        self.limits: dict[SummonLimitKey, AttributeOnlyLimit] = dict(limits or {})

    # ------------------------------------------------------------------
    def record(self, limit: AttributeOnlyLimit) -> AttributeOnlyLimit:
        """
        제한 하나를 적는다.

        같은 열쇠가 **두 번** 들어오면 (같은 턴 · 같은 플레이어 · 같은 효과)
        덮어쓴다 — 같은 제한을 두 번 걸어도 결과는 하나이기 때문이다. 제한의
        **횟수**가 뜻을 갖는 카드는 없다 (「…밖에 특수 소환할 수 없다」 는
        누적되지 않는다).
        """
        if not isinstance(limit, AttributeOnlyLimit):
            raise TypeError(
                f"AttributeOnlyLimit 가 필요합니다: {type(limit).__name__}"
            )
        self.limits[limit.key] = limit
        return limit

    def active(self, turn_number: int, player: int) -> tuple[AttributeOnlyLimit, ...]:
        """그 턴 · 그 플레이어에게 걸려 있는 제한 전부. 정렬되어 있다."""
        return tuple(
            limit
            for key, limit in sorted(self.limits.items())
            if key[0] == turn_number and key[1] == player
        )

    def entries(self, turn_number: int) -> tuple[AttributeOnlyLimit, ...]:
        """
        그 턴의 제한 전부 — 양쪽 플레이어를 함께.

        특수 소환 제한은 **공개된 사실**이다 (효과가 공개 해결되었다), 그래서
        :meth:`~engine.state.summon_usage.SummonUsageRegistry.entries` 와
        같은 규약으로 양쪽을 돌려준다.
        """
        return tuple(
            limit for key, limit in sorted(self.limits.items()) if key[0] == turn_number
        )

    def clear(self) -> None:
        """전부 지운다. **턴 진행이 부르지 않는다** (모듈 설명 참고)."""
        self.limits.clear()

    # ------------------------------------------------------------------
    def clone(self) -> "SummonLimitRegistry":
        """
        🔴 **사본은 따로 적는다.** 한 탐색 분기가 걸어 둔 제한이 다른 분기에
        보이면, 그 분기에서는 발동하지도 않은 효과의 제약이 소환을 막는다.
        """
        return SummonLimitRegistry(self.limits)

    def canonical_state(self) -> tuple:
        """열쇠가 전부 값 타입이라 정렬만 하면 결정론적이다."""
        return tuple(sorted(self.limits))

    def to_dict(self) -> dict:
        return {
            ":".join(str(part) for part in key): limit.to_dict()
            for key, limit in sorted(self.limits.items())
        }

    def __len__(self) -> int:
        return len(self.limits)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SummonLimitRegistry):
            return NotImplemented
        return self.limits == other.limits

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<SummonLimitRegistry {len(self.limits)}건>"


__all__ = [
    "AttributeOnlyLimit",
    "SummonLimitRegistry",
    "SummonLimitKey",
]
