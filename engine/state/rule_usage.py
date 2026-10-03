"""
규칙이 **턴 단위로 묻는** 것의 기록.

    "이 턴에 일반 소환을 했는가"
    "이 카드를 이 턴에 세웠는가"            (Phase 3-E-15)

카드 효과의 "1턴에 1번" 과 **다른 것**이다. 후자는
:class:`~engine.state.use_registry.UseRegistry` 가 세고, 그쪽 키는 카드 ·
카드명 · 효과다. 이쪽은 카드와 무관하게 **플레이어가 규칙상 가진 권리**를
센다 — 일반 소환권은 어느 카드를 소환하든 하나뿐이다.

둘을 한 곳에 넣으면 "이 카드의 1턴 1회" 와 "이 플레이어의 소환권" 이 같은
표에 들어가고, 리셋 시점도 판정 규칙도 서로 다른 둘이 뒤섞인다.

플레이어의 권리와 **카드의 권리**를 따로 센다
---------------------------------------------
규칙이 정한 1턴 1회에는 두 모양이 있다.

``NORMAL_SUMMON``   **플레이어**가 턴에 하나 갖는다. 어느 카드를 소환하든
                    같은 권리를 쓴다 (RULE-SUMMON-009).
``ATTACK``          **카드마다** 하나씩 갖는다 — "Each face-up Attack
                    Position monster you control is allowed 1 attack per
                    turn" (RULE-BATTLE-002).
``SET_SPELL_TRAP``  **횟수가 아니라 턴**을 묻는다. 세트는 몇 번이든 할 수
                    있지만, 세트한 **그 턴**에는 발동할 수 없는 카드가 있다
                    (RULE-SPELLTRAP-007 · 009). 카드마다 센다.

그래서 표가 둘이다. 하나로 합치면 몬스터 하나가 공격한 것이 **다른
몬스터의 공격권까지** 쓴 것이 된다. 같은 이름의 두 장도 서로 다른 권리를
가지므로 키는 카드 **이름이 아니라 ``instance_id``** 다.

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
    규칙이 **턴 단위로 묻는** 행위.

    **소환권은 일반 소환과 세트가 나눠 쓴다** (RULE-SUMMON-009: "You can only
    Normal Summon OR Normal Set once per turn"). 그래서 세트가 구현되면 같은
    이름으로 기록한다 — 이름을 나누면 한 턴에 둘 다 할 수 있게 된다.

    **"횟수를 정해 둔" 에서 "턴 단위로 묻는" 으로 넓혔다** (Phase 3-E-15)
    -----------------------------------------------------------------
    처음 둘(``NORMAL_SUMMON`` · ``ATTACK``)은 규칙이 **횟수를 1 로 정해 둔**
    권리였다. 셋째(``SET_SPELL_TRAP``)는 다르다 — 마법 · 함정 세트는 **횟수
    제한이 없다** (칸이 있는 만큼 할 수 있다). 그런데도 같은 표에 적는 이유는
    규칙이 그 행위에 대해 **턴을 묻기** 때문이다.

        RULE-SPELLTRAP-009 — "You cannot activate a Trap in the same turn that
        you Set it, but you can activate it at any time after that—starting
        from the beginning of the next turn."

    즉 세는 것은 **횟수가 아니라 턴**이다. 이 표의 키가 이미
    ``(턴 번호, …)`` 이므로 담을 자리가 정확히 여기다. 이 구분을 적어 두지
    않으면 "세트는 1턴 1회다" 라는 거짓이 이 enum 의 이름에서 읽힌다.
    """

    NORMAL_SUMMON = "normal_summon"
    ATTACK = "attack"
    """
    공격 선언. **카드마다 하나씩**이므로 :meth:`RuleUsageRegistry.card_key`
    로 센다 (RULE-BATTLE-002).

    플레이어별 표에 넣지 않는다 — 넣으면 한 몬스터가 공격한 것이 다른
    몬스터의 공격권까지 쓴 것이 된다.
    """
    SET_SPELL_TRAP = "set_spell_trap"
    """
    마법 · 함정을 세트했다 (Phase 3-E-15).

    **횟수를 세기 위한 것이 아니다** — "언제 세웠는가" 를 알기 위한 것이다.
    세트한 턴에는 발동할 수 없는 카드가 있고 (RULE-SPELLTRAP-007 · 009),
    그 턴을 적어 둔 자리가 엔진에 없었다 (``SET_ACTIVATION_MISSING``).

    **카드마다** 센다. 플레이어별 표에 넣으면 "이 플레이어가 이번 턴에 무언가
    세웠다" 까지만 알 수 있고, 같은 턴에 두 장을 세운 뒤 한 장만 발동한
    상황에서 남은 장이 언제 세워졌는지 말할 수 없다. 같은 이름의 두 장도
    서로 다른 턴에 세워질 수 있으므로 키는 ``instance_id`` 다
    (``ATTACK`` 과 같은 이유).

    **몬스터 세트는 여기 적지 않는다.** 그쪽은 소환권을 쓰므로
    ``NORMAL_SUMMON`` 으로 적히고 (RULE-SUMMON-009), 뒷면 수비 표시 몬스터의
    발동에는 "세트한 턴" 제약이 없다 — 뒤집기는 발동이 아니다.
    """

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: 카드마다 세는 행위들. :meth:`RuleUsageRegistry.record` 가 이것을 거부한다.
PER_CARD_ACTIONS: frozenset[RuleActionKind] = frozenset(
    {RuleActionKind.ATTACK, RuleActionKind.SET_SPELL_TRAP}
)

#: ``(turn_number, player, action.value)``
RuleUseKey = tuple[int, int, str]

#: ``(turn_number, player, instance_id.value, action.value)``
RuleCardUseKey = tuple[int, int, int, str]


class RuleUsageRegistry:
    """
    규칙 행위의 사용 횟수. **세기만 하고 판정하지 않는다.**

    "몇 번까지 허용인가" 는 규칙이고, 그것은 검증기의 몫이다
    (:class:`~engine.state.use_registry.UseRegistry` 와 같은 태도).
    """

    __slots__ = ("counts", "card_counts")

    def __init__(
        self,
        counts: "dict[RuleUseKey, int] | None" = None,
        card_counts: "dict[RuleCardUseKey, int] | None" = None,
    ):
        self.counts: dict[RuleUseKey, int] = dict(counts or {})
        self.card_counts: dict[RuleCardUseKey, int] = dict(card_counts or {})

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
        if action in PER_CARD_ACTIONS:
            raise ValueError(
                f"{action.value} 는 카드마다 세는 행위입니다 — card_key 를 쓰세요."
            )
        return (turn_number, player, action.value)

    @staticmethod
    def card_key(
        turn_number: int,
        player: int,
        instance_id,
        action: RuleActionKind,
    ) -> RuleCardUseKey:
        """
        **카드 하나**의 권리를 가리키는 키.

        ``instance_id`` 로 센다 — 같은 이름의 두 몬스터는 서로 다른 공격권을
        갖기 때문이다 (RULE-BATTLE-002).
        """
        if turn_number < 1:
            raise ValueError(f"턴 번호는 1 이상이어야 합니다: {turn_number}")
        if player not in (0, 1):
            raise ValueError(f"player 는 0 또는 1 입니다: {player}")
        if not isinstance(action, RuleActionKind):
            raise TypeError(f"RuleActionKind 가 필요합니다: {action!r}")
        if action not in PER_CARD_ACTIONS:
            raise ValueError(
                f"{action.value} 는 플레이어마다 세는 행위입니다 — key 를 쓰세요."
            )
        value = getattr(instance_id, "value", instance_id)
        if not isinstance(value, int):
            raise TypeError(f"InstanceId 가 필요합니다: {instance_id!r}")
        return (turn_number, player, value, action.value)

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

    # ------------------------------------------------------------------
    # 카드별 기록 · 조회
    # ------------------------------------------------------------------
    def record_card(
        self,
        turn_number: int,
        player: int,
        instance_id,
        action: RuleActionKind,
        times: int = 1,
    ) -> int:
        """그 **카드가** 썼다고 적고 누적 횟수를 돌려준다."""
        if times < 1:
            raise ValueError(f"기록은 1 이상이어야 합니다: {times}")
        key = self.card_key(turn_number, player, instance_id, action)
        self.card_counts[key] = self.card_counts.get(key, 0) + times
        return self.card_counts[key]

    def count_card(
        self, turn_number: int, player: int, instance_id, action: RuleActionKind
    ) -> int:
        return self.card_counts.get(
            self.card_key(turn_number, player, instance_id, action), 0
        )

    def used_card(
        self, turn_number: int, player: int, instance_id, action: RuleActionKind
    ) -> bool:
        return self.count_card(turn_number, player, instance_id, action) > 0

    def cards_used(
        self, turn_number: int, action: RuleActionKind
    ) -> "tuple[tuple[int, int], ...]":
        """
        그 턴에 그 행위를 쓴 **카드들과 횟수**. ``(instance_id 값, 횟수)``.

        양쪽 플레이어를 함께 돌려준다 — 공격은 공개된 자리에서 일어나므로
        누가 공격했는지는 양쪽이 아는 사실이다.
        """
        if action not in PER_CARD_ACTIONS:
            raise ValueError(f"{action.value} 는 카드마다 세는 행위가 아닙니다.")
        return tuple(
            sorted(
                (instance, count)
                for (turn, _player, instance, name), count in self.card_counts.items()
                if turn == turn_number and name == action.value
            )
        )

    def clear(self) -> None:
        """전부 지운다. **턴 진행이 부르지 않는다** (모듈 설명 참고)."""
        self.counts.clear()
        self.card_counts.clear()

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "RuleUsageRegistry":
        return RuleUsageRegistry(self.counts, self.card_counts)

    def canonical_state(self) -> tuple:
        """
        키가 전부 값 타입이라 정렬만 하면 결정론적이다.

        **카드별 표를 빈 경우에도 함께 넣는다.** 비었을 때만 빼면 같은 판이
        두 가지 표현을 갖게 되고, 해시가 "무엇을 세었는가" 에 따라 달라진다.
        """
        return (
            tuple(sorted(self.counts.items())),
            tuple(sorted(self.card_counts.items())),
        )

    def to_dict(self) -> dict:
        data = {
            f"{turn}:{player}:{action}": count
            for (turn, player, action), count in sorted(self.counts.items())
        }
        data.update(
            {
                f"{turn}:{player}:#{instance}:{action}": count
                for (turn, player, instance, action), count in sorted(
                    self.card_counts.items()
                )
            }
        )
        return data

    def __len__(self) -> int:
        return len(self.counts) + len(self.card_counts)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RuleUsageRegistry)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<RuleUsageRegistry 플레이어 {len(self.counts)}건 "
            f"카드 {len(self.card_counts)}건>"
        )


__all__ = [
    "RuleActionKind",
    "RuleUseKey",
    "RuleCardUseKey",
    "RuleUsageRegistry",
    "PER_CARD_ACTIONS",
]
