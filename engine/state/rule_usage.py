"""
규칙이 정한 **1턴 1회**의 기록.

    "이 턴에 일반 소환을 했는가"

카드 효과의 "1턴에 1번" 과 **다른 것**이다. 후자는
:class:`~engine.state.use_registry.UseRegistry` 가 세고, 그쪽 키는 카드 ·
카드명 · 효과다. 이쪽은 카드와 무관하게 **플레이어가 규칙상 가진 권리**를
센다 — 일반 소환권은 어느 카드를 소환하든 하나뿐이다.

둘을 한 곳에 넣으면 "이 카드의 1턴 1회" 와 "이 플레이어의 소환권" 이 같은
표에 들어가고, 리셋 시점도 판정 규칙도 서로 다른 둘이 뒤섞인다.

턴 번호가 키에 들어간다
-----------------------
기록은 ``(턴 번호, 플레이어, 규칙 행위)`` 로 센다. 그래서 **턴이 바뀔 때
지울 것이 없다** — 2턴의 기록을 1턴의 기록이 막지 않는다.

지우지 않는 설계를 고른 이유는 Phase 2-H 와 같다: 무엇을 언제 지우는가는
규칙이고, 규칙 없이 지우면 "지웠다" 는 사실이 판에 남아 되돌릴 수 없다.
지난 턴의 기록이 남아 있는 것은 새는 것이 아니라 **역사**다.
"""

from __future__ import annotations

from enum import Enum


class RuleActionKind(str, Enum):
    """
    규칙이 횟수를 정해 둔 행위.

    **소환권은 일반 소환과 세트가 나눠 쓴다** (RULE-SUMMON-009: "You can only
    Normal Summon OR Normal Set once per turn"). 그래서 세트가 구현되면 같은
    이름으로 기록한다 — 이름을 나누면 한 턴에 둘 다 할 수 있게 된다.
    """

    NORMAL_SUMMON = "normal_summon"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: ``(turn_number, player, action.value)``
RuleUseKey = tuple[int, int, str]


class RuleUsageRegistry:
    """
    규칙 행위의 사용 횟수. **세기만 하고 판정하지 않는다.**

    "몇 번까지 허용인가" 는 규칙이고, 그것은 검증기의 몫이다
    (:class:`~engine.state.use_registry.UseRegistry` 와 같은 태도).
    """

    __slots__ = ("counts",)

    def __init__(self, counts: "dict[RuleUseKey, int] | None" = None):
        self.counts: dict[RuleUseKey, int] = dict(counts or {})

    # ------------------------------------------------------------------
    # 키
    # ------------------------------------------------------------------
    @staticmethod
    def key(turn_number: int, player: int, action: RuleActionKind) -> RuleUseKey:
        if turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {turn_number}")
        if player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {player}")
        if not isinstance(action, RuleActionKind):
            raise TypeError(f"RuleActionKind 가 필요합니다: {action!r}")
        return (turn_number, player, action.value)

    # ------------------------------------------------------------------
    # 기록 · 조회
    # ------------------------------------------------------------------
    def record(
        self,
        turn_number: int,
        player: int,
        action: RuleActionKind,
        times: int = 1,
    ) -> int:
        """썼다고 적고 누적 횟수를 돌려준다."""
        if times < 1:
            raise ValueError(f"기록은 1 이상이어야 합니다: {times}")
        key = self.key(turn_number, player, action)
        self.counts[key] = self.counts.get(key, 0) + times
        return self.counts[key]

    def count(self, turn_number: int, player: int, action: RuleActionKind) -> int:
        return self.counts.get(self.key(turn_number, player, action), 0)

    def used(self, turn_number: int, player: int, action: RuleActionKind) -> bool:
        return self.count(turn_number, player, action) > 0

    def clear(self) -> None:
        """전부 지운다. **턴 진행이 부르지 않는다** (모듈 설명 참고)."""
        self.counts.clear()

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "RuleUsageRegistry":
        return RuleUsageRegistry(self.counts)

    def canonical_state(self) -> tuple:
        """키가 전부 값 타입이라 정렬만 하면 결정론적이다."""
        return tuple(sorted(self.counts.items()))

    def to_dict(self) -> dict:
        return {
            f"{turn}:{player}:{action}": count
            for (turn, player, action), count in sorted(self.counts.items())
        }

    def __len__(self) -> int:
        return len(self.counts)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RuleUsageRegistry)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<RuleUsageRegistry {len(self.counts)}건>"


__all__ = ["RuleActionKind", "RuleUseKey", "RuleUsageRegistry"]
