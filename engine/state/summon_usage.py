"""
이 턴에 **어떤 카드명을 어떤 소환법으로** 소환했는가 (Phase 6-AF).

    "이 턴에 「오르페골 갈라테아i」 를 링크 소환했는가"

왜 기존 표 둘로는 안 되는가
---------------------------
=============================  ===============================================
:class:`~engine.state.rule_usage.RuleUsageRegistry`   **규칙이** 턴 단위로
                                                      주는 권리 (소환권 ·
                                                      공격권). 카드와 무관
                                                      하고, 카드별 칸의 열쇠는
                                                      ``instance_id`` 다.
:class:`~engine.state.use_registry.UseRegistry`        **효과의** "1턴에
                                                      1번". 열쇠가
                                                      ``(player, card_id)``
                                                      또는 ``(player,
                                                      card_id, ordinal)`` 다.
=============================  ===============================================

필요한 사실은 둘 중 어느 것도 아니다. **소환 자체**를 카드명 단위로 세는
것이고, 그 제약은 효과의 발동 횟수가 아니다. 실측으로 섞을 수 없다:
``c48835607.lua`` 의 ``e3`` (덱에서 서치) 이 ``SetCountLimit(1,id)`` 이므로
``UseRegistry`` 의 ``(player, 48835607)`` 칸을 **이미 쓴다** — 같은 칸에
링크 소환 기록을 적으면 ① 을 발동한 것이 그 카드의 재소환을 막고 그 반대도
일어난다. 🔴 그래서 **표를 따로 둔다.**

그리고 ``instance_id`` 로 셀 수도 없다. 제약이 걸리는 단위가 **카드명**이기
때문이다 — 엑스트라 덱에 같은 이름이 두 장 있으면 ``instance_id`` 로는 둘째
장이 조용히 통과한다.

무엇을 하지 않는가
------------------
🔴 **판정하지 않는다.** "몇 번까지 허용인가" 는 규칙이고, 그것을 읽는 자리는
:data:`~engine.link_rules.LINK_SUMMON_ONCE_PER_TURN` 과
:func:`~engine.link_rules.assess_link_materials` 다 (``RuleUsageRegistry`` ·
``UseRegistry`` 와 같은 태도).

🔴 **지우지 않는다.** 열쇠에 턴 번호가 들어가므로 턴이 바뀔 때 지울 것이
없다 — 지난 턴의 기록이 남아 있는 것은 새는 것이 아니라 역사다
(:mod:`engine.state.rule_usage` 와 같은 설계).
"""

from __future__ import annotations

#: ``(turn_number, player, card_id, summon_kind)``
SummonNameKey = tuple[int, int, int, str]


class SummonUsageRegistry:
    """카드명 단위 소환 기록. **세기만 한다.**"""

    __slots__ = ("counts",)

    def __init__(self, counts: "dict[SummonNameKey, int] | None" = None):
        self.counts: dict[SummonNameKey, int] = dict(counts or {})

    # ------------------------------------------------------------------
    @staticmethod
    def key(
        turn_number: int, player: int, card_id: int, summon: str
    ) -> SummonNameKey:
        if turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {turn_number}")
        if player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {player}")
        if card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {card_id}")
        name = getattr(summon, "value", summon)
        if not isinstance(name, str) or not name:
            raise TypeError(f"소환법 이름이 필요합니다: {summon!r}")
        return (turn_number, player, card_id, name)

    # ------------------------------------------------------------------
    def record(
        self,
        turn_number: int,
        player: int,
        card_id: int,
        summon: str,
        times: int = 1,
    ) -> int:
        """그 카드명을 그 소환법으로 소환했다고 적고 누적 횟수를 돌려준다."""
        if times < 1:
            raise ValueError(f"기록은 1 이상이어야 합니다: {times}")
        found = self.key(turn_number, player, card_id, summon)
        self.counts[found] = self.counts.get(found, 0) + times
        return self.counts[found]

    def count(
        self, turn_number: int, player: int, card_id: int, summon: str
    ) -> int:
        return self.counts.get(self.key(turn_number, player, card_id, summon), 0)

    def used(
        self, turn_number: int, player: int, card_id: int, summon: str
    ) -> bool:
        return self.count(turn_number, player, card_id, summon) > 0

    def entries(self, turn_number: int) -> "tuple[tuple[int, int, str, int], ...]":
        """
        그 턴의 기록 전부 — ``(player, card_id, 소환법, 횟수)``.

        양쪽 플레이어를 함께 돌려준다. 소환은 **공개된 자리**에서 일어나므로
        누가 무엇을 소환했는지는 양쪽이 아는 사실이다
        (:meth:`~engine.state.rule_usage.RuleUsageRegistry.cards_used` 와
        같은 이유).
        """
        return tuple(
            sorted(
                (player, card_id, summon, count)
                for (turn, player, card_id, summon), count in self.counts.items()
                if turn == turn_number
            )
        )

    def clear(self) -> None:
        """전부 지운다. **턴 진행이 부르지 않는다** (모듈 설명 참고)."""
        self.counts.clear()

    # ------------------------------------------------------------------
    def clone(self) -> "SummonUsageRegistry":
        return SummonUsageRegistry(self.counts)

    def canonical_state(self) -> tuple:
        """열쇠가 전부 값 타입이라 정렬만 하면 결정론적이다."""
        return tuple(sorted(self.counts.items()))

    def to_dict(self) -> dict:
        return {
            f"{turn}:{player}:{card_id}:{summon}": count
            for (turn, player, card_id, summon), count in sorted(
                self.counts.items()
            )
        }

    def __len__(self) -> int:
        return len(self.counts)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SummonUsageRegistry)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<SummonUsageRegistry {len(self.counts)}건>"


__all__ = ["SummonNameKey", "SummonUsageRegistry"]
