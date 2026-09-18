"""
트리거 정리와 순서 — **체인에 넣기 전에 무엇을 어떤 묶음으로 넘기는가**.

    TriggerEligibility 여럿  (2-F-3-B 의 판정 결과)
        ↓  TriggerOrderer(view).order(event, eligibilities)
    TriggerOrdering
        ├ groups      컨트롤러별 묶음 (강제 / 임의 / 미확인)
        ├ unordered   판정 불가라 순서화 대상이 아닌 것
        ├ excluded    확실히 제외된 것 (거부 · 금지)
        └ unresolved_rules   **아직 순서를 정할 수 없는 규칙들**
        ↓  (다음 단계)
    ChainLink

여기서 체인에 넣지 않는다
-------------------------
``Chain.push`` 도 ``Chain.activate`` 도 부르지 않고 ``engine.chain`` 을
import 하지도 않는다. 결과는 불변 값 객체 하나이고, 그것을 ``ChainLink`` 로
바꾸는 것은 다음 단계의 일이다.

**SEGOC 를 구현하지 않았다**
----------------------------
가장 중요한 경계다. 이 모듈이 내는 순서는 :attr:`OrderingBasis.CANONICAL`
— **재현 가능한 순서일 뿐 규칙상의 발동 순서가 아니다.**

유희왕의 동시 트리거 순서(SEGOC)는 턴 플레이어 우선, 강제 우선 같은 규칙을
갖지만, 그 규칙을 지금 못박으면 틀린 채로 굳는다. 그래서

- 묶음은 **자리 번호 순**으로 낸다 (턴 플레이어 순이 아니다)
- 강제 · 임의 · 미확인을 **따로** 담되 "강제가 먼저" 라고 잇지 않는다
- 정할 수 없는 것은 :attr:`TriggerOrdering.unresolved_rules` 에 남긴다

각 묶음은 :attr:`TriggerGroup.role` 로 턴 플레이어인지 알려주므로, SEGOC 가
들어오는 날 **여기를 고치지 않고** 재정렬만 하면 된다.

컨트롤러와 턴 플레이어는 다른 것이다
------------------------------------
트리거를 가진 사람(:attr:`TriggerCandidate.controller`)과 지금 턴인 사람과
지금 우선권을 쥔 사람은 **셋 다 다른 개념**이다. 이 모듈은 앞의 둘만 보고,
우선권(:class:`~engine.priority.PriorityState`)은 건드리지도 읽지도 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.game_state_view import GameStateView
from engine.trigger import (
    TimingEvent,
    TriggerEligibility,
    TriggerError,
    TriggerRequirement,
    TriggerStatus,
)


class PlayerRole(str, Enum):
    """
    이 묶음의 주인이 **지금 턴인 사람인가.**

    ``PriorityHolder`` 와 다르다 — 그쪽은 "지금 누구 차례인가" 이고 이쪽은
    "누구 턴인가" 다. 우선권은 턴과 따로 움직인다 (Phase 2-F-1).
    """

    TURN_PLAYER = "turn_player"
    NON_TURN_PLAYER = "non_turn_player"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return "턴 플레이어" if self is PlayerRole.TURN_PLAYER else "상대"


class OrderingBasis(str, Enum):
    """
    이 순서가 **무엇에 근거하는가.**

    결과를 읽는 쪽이 "규칙대로 정렬된 것" 과 "그냥 재현 가능한 것" 을
    구분할 수 있어야 한다. 값이 하나뿐인 것이 지금의 사실이다.
    """

    CANONICAL = "canonical"
    """
    안정적인 식별자 순. **재현성만 보장한다.**

    같은 입력이면 언제나 같은 결과가 나오지만, 이 순서가 규칙상의 발동
    순서라는 뜻은 **아니다.**
    """

    @property
    def is_rule_order(self) -> bool:
        """규칙이 정한 순서인가. **지금은 언제나 거짓이다.**"""
        return False


#: 아직 **정할 수 없는** 순서 규칙들.
#:
#: 숨기지 않고 목록으로 남긴다. :attr:`TriggerOrdering.unresolved_rules` 가
#: 이것을 그대로 실어 나르므로, 순서를 받은 쪽도 "무엇이 아직 안 정해졌나"
#: 를 알 수 있다.
UNRESOLVED_ORDER_RULES: tuple[str, ...] = (
    "SEGOC (동시 발동 트리거의 규칙상 순서)",
    "턴 플레이어 / 비턴 플레이어 묶음의 순서",
    "강제 트리거와 임의 트리거의 우선순위",
    "같은 플레이어의 여러 트리거를 그 사람이 고르는 순서",
    "trigger placement (체인 어느 자리에 놓이는가)",
)


@dataclass(frozen=True, slots=True)
class TriggerGroup:
    """
    **한 플레이어가 컨트롤하는** 트리거들.

    강제 · 임의 · 미확인을 따로 담는다. 불리언 하나로 뭉개면 SEGOC 가
    들어올 때 쓸 정보가 사라진다. 다만 **"강제가 임의보다 먼저" 라고 잇지
    않는다** — 그것이 규칙이기 때문이다.
    """

    controller: int
    role: PlayerRole
    mandatory: tuple[TriggerEligibility, ...] = ()
    optional: tuple[TriggerEligibility, ...] = ()
    undetermined: tuple[TriggerEligibility, ...] = ()
    """강제인지 임의인지 확인되지 않은 것. 한쪽으로 몰지 않는다."""

    def __post_init__(self) -> None:
        if self.controller not in (0, 1):
            raise TriggerError(f"controller 는 0 또는 1 입니다: {self.controller}")
        for name in ("mandatory", "optional", "undetermined"):
            held = getattr(self, name)
            if not isinstance(held, tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 묶음은 불변입니다.")
            for eligibility in held:
                if eligibility.candidate.controller != self.controller:
                    raise TriggerError(
                        f"P{self.controller} 묶음에 P"
                        f"{eligibility.candidate.controller} 의 트리거가 "
                        "들어 있습니다."
                    )

    @property
    def canonical_sequence(self) -> tuple[TriggerEligibility, ...]:
        """
        이 묶음 전체를 한 줄로. **규칙상의 순서가 아니다.**

        강제 → 임의 → 미확인 순으로 잇는 것은 **읽기 편하라고** 정한 자리
        순서일 뿐이고, 유희왕에서 강제가 먼저라는 주장이 아니다. 규칙 순서는
        :data:`UNRESOLVED_ORDER_RULES` 에 미정으로 남아 있다.
        """
        return self.mandatory + self.optional + self.undetermined

    @property
    def size(self) -> int:
        return len(self.canonical_sequence)

    @property
    def is_empty(self) -> bool:
        return not self.size

    def canonical_state(self) -> tuple:
        return (
            self.controller,
            self.role.value,
            tuple(e.canonical_state() for e in self.mandatory),
            tuple(e.canonical_state() for e in self.optional),
            tuple(e.canonical_state() for e in self.undetermined),
        )

    def to_dict(self) -> dict:
        return {
            "controller": self.controller,
            "role": self.role.value,
            "mandatory": [e.to_dict() for e in self.mandatory],
            "optional": [e.to_dict() for e in self.optional],
            "undetermined": [e.to_dict() for e in self.undetermined],
        }

    def describe_ko(self) -> str:
        return (
            f"P{self.controller}({self.role}): 강제 {len(self.mandatory)} · "
            f"임의 {len(self.optional)} · 미확인 {len(self.undetermined)}"
        )

    def __len__(self) -> int:
        return self.size

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TriggerOrdering:
    """
    사건 하나에 대한 **정리 결과**. 불변이다.

    세 갈래로 나뉜다.

    =================  ==================================================
    :attr:`groups`      순서화 대상 — ``ELIGIBLE`` 인 것만
    :attr:`unordered`   ``UNKNOWN`` — 판정 불가라 순서화하지 않는다
    :attr:`excluded`    ``INELIGIBLE`` · ``FORBIDDEN`` — 확실히 빠진다
    =================  ==================================================

    ``UNKNOWN`` 을 :attr:`excluded` 에 넣지 않는 것이 핵심이다. 모르는 것을
    "확실히 안 된다" 와 같은 통에 담으면 그 구분이 사라진다.
    """

    event: TimingEvent
    turn_player: int
    basis: OrderingBasis = OrderingBasis.CANONICAL
    groups: tuple[TriggerGroup, ...] = ()
    unordered: tuple[TriggerEligibility, ...] = ()
    excluded: tuple[TriggerEligibility, ...] = ()
    unresolved_rules: tuple[str, ...] = UNRESOLVED_ORDER_RULES

    def __post_init__(self) -> None:
        if self.turn_player not in (0, 1):
            raise TriggerError(f"turn_player 는 0 또는 1 입니다: {self.turn_player}")
        for name in ("groups", "unordered", "excluded", "unresolved_rules"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 결과는 불변입니다.")
        seen: list[int] = []
        for group in self.groups:
            if group.controller in seen:
                raise TriggerError(
                    f"P{group.controller} 묶음이 두 번 들어왔습니다."
                )
            seen.append(group.controller)

    # ------------------------------------------------------------------
    @property
    def is_rule_ordered(self) -> bool:
        """
        규칙이 정한 순서인가. **지금은 언제나 거짓이다.**

        참이 되는 날 SEGOC 가 구현된 것이고, 그때까지 이 결과를 받는 쪽은
        "재현 가능한 순서" 이상으로 믿으면 안 된다.
        """
        return self.basis.is_rule_order and not self.unresolved_rules

    @property
    def canonical_sequence(self) -> tuple[TriggerEligibility, ...]:
        """
        순서화된 것 전체를 한 줄로. **규칙상의 순서가 아니다**
        (:attr:`is_rule_ordered` 참고).
        """
        found: list[TriggerEligibility] = []
        for group in self.groups:
            found.extend(group.canonical_sequence)
        return tuple(found)

    @property
    def identities(self) -> tuple[tuple, ...]:
        """순서화된 후보들의 안정적인 식별자. 비교와 회귀 확인에 쓴다."""
        return tuple(e.candidate.identity for e in self.canonical_sequence)

    def group_for(self, controller: int) -> TriggerGroup | None:
        for group in self.groups:
            if group.controller == controller:
                return group
        return None

    @property
    def turn_player_group(self) -> TriggerGroup | None:
        return self.group_for(self.turn_player)

    @property
    def is_empty(self) -> bool:
        return not self.canonical_sequence

    def canonical_state(self) -> tuple:
        return (
            self.event.canonical_state(),
            self.turn_player,
            self.basis.value,
            tuple(group.canonical_state() for group in self.groups),
            tuple(e.canonical_state() for e in self.unordered),
            tuple(e.canonical_state() for e in self.excluded),
            self.unresolved_rules,
        )

    def to_dict(self) -> dict:
        return {
            "event": self.event.to_dict(),
            "turn_player": self.turn_player,
            "basis": self.basis.value,
            "is_rule_ordered": self.is_rule_ordered,
            "groups": [group.to_dict() for group in self.groups],
            "unordered": [e.to_dict() for e in self.unordered],
            "excluded": [e.to_dict() for e in self.excluded],
            "unresolved_rules": list(self.unresolved_rules),
        }

    def describe_ko(self) -> str:
        groups = " / ".join(group.describe_ko() for group in self.groups) or "없음"
        return (
            f"{self.event.point.value}: {groups} | 판정 불가 "
            f"{len(self.unordered)} · 제외 {len(self.excluded)} "
            f"(미정 규칙 {len(self.unresolved_rules)}개)"
        )

    def __len__(self) -> int:
        return len(self.canonical_sequence)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TriggerOrderer:
    """
    판정된 트리거들을 **컨트롤러별로 묶고 안정적인 순서로** 정리한다.

    **판을 바꾸지 않는다.** 관측에서 턴 플레이어만 읽고, 그 밖에는 받은
    판정 결과만 본다.

    **체인에 넣지 않는다.** ``engine.chain`` 도 ``engine.priority`` 도
    import 하지 않는다.
    """

    __slots__ = ("_view",)

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "TriggerOrderer 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 정리가 판을 바꿀 수 있게 됩니다."
            )
        self._view = view

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def turn_player(self) -> int:
        return self._view.turn_player

    # ------------------------------------------------------------------
    def order(
        self, event: TimingEvent, eligibilities: "tuple[TriggerEligibility, ...]"
    ) -> TriggerOrdering:
        """
        정리한다. **입력 순서에 의존하지 않는다** — 같은 판정 묶음이면
        어떤 순서로 주어도 같은 결과가 나온다.

        ``ELIGIBLE`` 만 묶음에 들어간다. ``UNKNOWN`` 은 :attr:`
        TriggerOrdering.unordered` 로 따로 보존하고, ``INELIGIBLE`` 과
        ``FORBIDDEN`` 은 :attr:`TriggerOrdering.excluded` 로 간다.
        """
        if not isinstance(event, TimingEvent):
            raise TypeError(f"TimingEvent 가 필요합니다: {type(event).__name__}")
        judged = tuple(eligibilities)
        for eligibility in judged:
            if not isinstance(eligibility, TriggerEligibility):
                raise TypeError(
                    f"TriggerEligibility 가 필요합니다: {type(eligibility).__name__}"
                )
            if eligibility.candidate.point is not event.point:
                raise TriggerError(
                    f"{eligibility.candidate.key} 는 {event.point.value} 사건의 "
                    "판정이 아닙니다."
                )

        ordered = [e for e in judged if e.status is TriggerStatus.ELIGIBLE]
        unordered = [e for e in judged if e.status is TriggerStatus.UNKNOWN]
        excluded = [
            e
            for e in judged
            if e.status in (TriggerStatus.INELIGIBLE, TriggerStatus.FORBIDDEN)
        ]

        groups = tuple(
            group
            for controller in (0, 1)
            if not (group := self._group(controller, ordered)).is_empty
        )
        return TriggerOrdering(
            event=event,
            turn_player=self.turn_player,
            basis=OrderingBasis.CANONICAL,
            groups=groups,
            unordered=tuple(sorted(unordered, key=_sort_key)),
            excluded=tuple(sorted(excluded, key=_sort_key)),
        )

    # ------------------------------------------------------------------
    def _group(
        self, controller: int, ordered: "list[TriggerEligibility]"
    ) -> TriggerGroup:
        """
        한 플레이어의 묶음. 세 통 각각을 **식별자 순**으로 정렬한다 —
        입력 순서가 결과에 새어 나가지 않게 하기 위해서다.
        """
        mine = [e for e in ordered if e.candidate.controller == controller]
        return TriggerGroup(
            controller=controller,
            role=(
                PlayerRole.TURN_PLAYER
                if controller == self.turn_player
                else PlayerRole.NON_TURN_PLAYER
            ),
            mandatory=_bucket(mine, TriggerRequirement.MANDATORY),
            optional=_bucket(mine, TriggerRequirement.OPTIONAL),
            undetermined=_bucket(mine, TriggerRequirement.UNKNOWN),
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TriggerOrderer turn=P{self.turn_player}>"


def _bucket(
    eligibilities: "list[TriggerEligibility]", requirement: TriggerRequirement
) -> tuple[TriggerEligibility, ...]:
    return tuple(
        sorted(
            (e for e in eligibilities if e.requirement is requirement),
            key=_sort_key,
        )
    )


def _sort_key(eligibility: TriggerEligibility) -> tuple:
    """
    **안정적인 정렬 기준.**

    ``TriggerCandidate.identity`` 는 ``(시점, card_id, ordinal, 인스턴스,
    컨트롤러)`` 로 전부 정수와 문자열이다. 파이썬 기본 ``hash()`` 도 객체
    주소도 들어가지 않으므로 ``PYTHONHASHSEED`` 에 영향받지 않는다.

    ``EffectSpec.index`` (Lua 변수명 ``"e1"``, 한 카드 안에서 중복 — 실측
    4,884장) 를 쓰지 않는다. 서로 다른 카드가 같은 변수명을 가져도 ``card_id``
    가 다르므로 충돌하지 않는다.
    """
    return eligibility.candidate.identity


__all__ = [
    "PlayerRole",
    "OrderingBasis",
    "UNRESOLVED_ORDER_RULES",
    "TriggerGroup",
    "TriggerOrdering",
    "TriggerOrderer",
]
