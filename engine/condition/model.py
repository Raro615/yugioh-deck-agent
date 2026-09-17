"""
엔진 조건 — 표현과 평가.

``GameStateView`` 를 읽고 ``TRUE`` / ``FALSE`` / ``UNKNOWN`` 을 돌려준다.
**상태를 바꾸지 않는다.** 조건은 질문이지 명령이 아니다.

analysis 의 조건 트리와 무엇이 다른가
--------------------------------------
``analysis.effect_model.ConditionNode`` 도 AND/OR/NOT 트리를 담지만, 그것은
**Lua 스크립트를 읽은 기록**이다. 가변 dataclass 이고 ``raw`` 원문과
``predicate`` 분류를 들고 있으며, 평가 메서드가 없다 (실제로 ``analysis``
전체에 평가기가 없다).

여기의 조건은 **실행용**이다. 불변이고, 원문을 들고 있지 않고, 관측을 받아
값을 돌려준다. 둘을 한 타입으로 합치면 "스크립트가 무엇이라고 적혀 있는가"
와 "지금 판에서 그것이 참인가" 가 섞인다.

그래서 ``analysis`` 에서 아무것도 가져오지 않는다. ``analysis.BoolOp`` 에는
``LEAF`` 멤버가 있는데, 그것은 ``ConditionNode`` 하나가 가지와 잎을 겸하기
때문이다. 엔진에서는 가지와 잎이 서로 다른 클래스이므로 그 멤버가 필요 없다.

Phase 2-B-2 에서 ``ConditionNode`` → :class:`Condition` 컴파일러를 만들 수
있다. 그때도 방향은 한쪽이다 — 분석이 실행을 낳지, 실행이 분석을 바꾸지
않는다.

없는 규칙을 지어내지 않는다
---------------------------
체인 · 트리거 · 타이밍 · 소환 절차가 아직 없다. 그런 정보가 필요한 조건은
:class:`UnimplementedRule` 로 ``UNKNOWN`` 을 돌려주고 **무엇이 없어서
모르는지**를 함께 남긴다. "모르지만 아마 참" 은 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.condition.context import ConditionContext, PlayerRef
from engine.condition.result import ConditionResult
from engine.ids import InstanceId
from engine.vocabulary import Phase, Zone

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from engine.game_state_view import GameStateView


@dataclass(frozen=True, slots=True)
class Condition:
    """
    조건 하나. **불변**이고, 관측을 읽어 결과를 돌려준다.

    하위 클래스는 :meth:`evaluate` 와 :meth:`canonical_state` 를 채운다.
    """

    def evaluate(
        self, view: "GameStateView", context: ConditionContext
    ) -> ConditionResult:
        raise NotImplementedError  # pragma: no cover - 추상

    def canonical_state(self) -> tuple:
        raise NotImplementedError  # pragma: no cover - 추상

    def describe_ko(self) -> str:
        raise NotImplementedError  # pragma: no cover - 추상

    # ------------------------------------------------------------------
    # 왜 모르는가
    # ------------------------------------------------------------------
    def unknown_reasons(
        self, view: "GameStateView", context: ConditionContext
    ) -> tuple[str, ...]:
        """
        이 조건이 ``UNKNOWN`` 인 **이유**들. 확정된 조건이면 빈 튜플.

        가지 노드는 자식 중 실제로 결과를 좌우한 쪽만 모은다. ``FALSE AND
        UNKNOWN`` 은 이미 ``FALSE`` 이므로 이유가 없다.
        """
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        return (self.describe_ko(),)

    def to_dict(self) -> dict:
        """JSON 으로 바로 나갈 수 있는 형태."""
        raise NotImplementedError  # pragma: no cover - 추상

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 상수
# ======================================================================


@dataclass(frozen=True, slots=True)
class Always(Condition):
    """
    언제나 같은 값을 돌려준다. 테스트와 자리표시에 쓴다.

    ``UNKNOWN`` 을 넣을 수도 있지만, 그럴 때는 대개
    :class:`UnimplementedRule` 이 더 정확하다 — 이유를 함께 남기기 때문이다.
    """

    value: ConditionResult = ConditionResult.TRUE

    def evaluate(self, view, context) -> ConditionResult:
        return self.value

    def canonical_state(self) -> tuple:
        return ("always", self.value.value)

    def to_dict(self) -> dict:
        return {"kind": "always", "value": self.value.value}

    def describe_ko(self) -> str:
        return {"true": "항상 참", "false": "항상 거짓", "unknown": "항상 모름"}[
            self.value.value
        ]


@dataclass(frozen=True, slots=True)
class UnimplementedRule(Condition):
    """
    **아직 판정할 규칙이 없다.** 언제나 ``UNKNOWN`` 이다.

    체인 · 트리거 · 타이밍 · 소환 절차처럼 시스템 자체가 없는 조건을
    솔직하게 표현한다. ``rule`` 에 무엇이 없는지 적어서, 나중에 어느 단계가
    이 조건을 살릴 수 있는지 추적할 수 있게 한다.
    """

    rule: str
    """없는 규칙 계층의 이름. 예: ``"chain (Phase 2-F)"``."""

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return (f"규칙 미구현: {self.rule}",)

    def canonical_state(self) -> tuple:
        return ("unimplemented", self.rule)

    def to_dict(self) -> dict:
        return {"kind": "unimplemented", "rule": self.rule}

    def describe_ko(self) -> str:
        return f"판정 불가({self.rule})"


# ======================================================================
# 논리 결합
# ======================================================================


@dataclass(frozen=True, slots=True)
class And(Condition):
    """
    전부 참인가. 자식이 없으면 ``TRUE`` (막을 것이 없다).

    ``FALSE`` 가 하나라도 있으면 나머지를 몰라도 ``FALSE`` 다.
    """

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.children, "And")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.all_of(
            child.evaluate(view, context) for child in self.children
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        reasons: list[str] = []
        for child in self.children:
            reasons.extend(child.unknown_reasons(view, context))
        return tuple(reasons)

    def canonical_state(self) -> tuple:
        return ("and", tuple(c.canonical_state() for c in self.children))

    def to_dict(self) -> dict:
        return {"kind": "and", "children": [c.to_dict() for c in self.children]}

    def describe_ko(self) -> str:
        if not self.children:
            return "(조건 없음)"
        return "(" + " 그리고 ".join(c.describe_ko() for c in self.children) + ")"


@dataclass(frozen=True, slots=True)
class Or(Condition):
    """
    하나라도 참인가. 자식이 없으면 ``FALSE`` (참인 선택지가 없다).

    **단락 평가가 ``UNKNOWN`` 을 구제한다.** 하나가 확실히 참이면 나머지를
    몰라도 전체가 참이다. 이것이 없으면 조건 하나만 미해석이어도 트리 전체가
    ``UNKNOWN`` 이 된다.
    """

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.children, "Or")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.any_of(
            child.evaluate(view, context) for child in self.children
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        reasons: list[str] = []
        for child in self.children:
            reasons.extend(child.unknown_reasons(view, context))
        return tuple(reasons)

    def canonical_state(self) -> tuple:
        return ("or", tuple(c.canonical_state() for c in self.children))

    def to_dict(self) -> dict:
        return {"kind": "or", "children": [c.to_dict() for c in self.children]}

    def describe_ko(self) -> str:
        if not self.children:
            return "(선택지 없음)"
        return "(" + " 또는 ".join(c.describe_ko() for c in self.children) + ")"


@dataclass(frozen=True, slots=True)
class Not(Condition):
    """부정. ``UNKNOWN`` 은 부정해도 ``UNKNOWN`` 이다."""

    child: Condition

    def evaluate(self, view, context) -> ConditionResult:
        return self.child.evaluate(view, context).logical_not()

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return self.child.unknown_reasons(view, context)

    def canonical_state(self) -> tuple:
        return ("not", self.child.canonical_state())

    def to_dict(self) -> dict:
        return {"kind": "not", "child": self.child.to_dict()}

    def describe_ko(self) -> str:
        return f"아님({self.child.describe_ko()})"


def _require_tuple(children: object, name: str) -> None:
    if not isinstance(children, tuple):
        raise TypeError(
            f"{name}.children 은 tuple 이어야 합니다 — 조건은 불변입니다."
        )


# ======================================================================
# 상태 술어 — GameStateView 만 읽는다
# ======================================================================


@dataclass(frozen=True, slots=True)
class PhaseIs(Condition):
    """지금 페이즈가 이 중 하나인가. 페이즈는 언제나 공개다."""

    phases: tuple[Phase, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.phases, "PhaseIs")
        if not self.phases:
            raise ValueError("PhaseIs 에는 페이즈가 최소 하나 필요합니다.")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.from_bool(view.phase in self.phases)

    def canonical_state(self) -> tuple:
        return ("phase_is", tuple(p.value for p in self.phases))

    def to_dict(self) -> dict:
        return {"kind": "phase_is", "phases": [p.value for p in self.phases]}

    def describe_ko(self) -> str:
        return f"페이즈가 {'/'.join(p.value for p in self.phases)}"


@dataclass(frozen=True, slots=True)
class IsTurnPlayer(Condition):
    """이 사람의 턴인가. 턴 플레이어는 언제나 공개다."""

    who: PlayerRef = PlayerRef.CONTROLLER

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.from_bool(view.turn_player == self.who.resolve(context))

    def canonical_state(self) -> tuple:
        return ("is_turn_player", self.who.value)

    def to_dict(self) -> dict:
        return {"kind": "is_turn_player", "who": self.who.value}

    def describe_ko(self) -> str:
        return f"{self.who} 턴"


@dataclass(frozen=True, slots=True)
class LifePointsAtLeast(Condition):
    """라이프가 이 값 이상인가. 양쪽 라이프는 언제나 공개다."""

    who: PlayerRef
    amount: int

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"라이프는 음수일 수 없습니다: {self.amount}")

    def evaluate(self, view, context) -> ConditionResult:
        player = view.player(self.who.resolve(context))
        return ConditionResult.from_bool(player.life_points >= self.amount)

    def canonical_state(self) -> tuple:
        return ("life_points_at_least", self.who.value, self.amount)

    def to_dict(self) -> dict:
        return {
            "kind": "life_points_at_least",
            "who": self.who.value,
            "amount": self.amount,
        }

    def describe_ko(self) -> str:
        return f"{self.who} LP {self.amount} 이상"


@dataclass(frozen=True, slots=True)
class ZoneCountAtLeast(Condition):
    """
    그 존에 카드가 이 수 이상 있는가.

    **가려진 존에서도 확정할 수 있다.** 장수는 상대 패에서도 공개이기
    때문이다 (``ZoneView.size`` 는 언제나 정확하다). 알 수 없는 것은
    *무엇이* 있는가이지 *몇 장*이 아니다.
    """

    who: PlayerRef
    zone: Zone
    count: int = 1

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"장수는 음수일 수 없습니다: {self.count}")

    def evaluate(self, view, context) -> ConditionResult:
        player = view.player(self.who.resolve(context))
        return ConditionResult.from_bool(player.zone(self.zone).size >= self.count)

    def canonical_state(self) -> tuple:
        return ("zone_count_at_least", self.who.value, self.zone.value, self.count)

    def to_dict(self) -> dict:
        return {
            "kind": "zone_count_at_least",
            "who": self.who.value,
            "zone": self.zone.value,
            "count": self.count,
        }

    def describe_ko(self) -> str:
        return f"{self.who} {self.zone.value} 에 {self.count}장 이상"


@dataclass(frozen=True, slots=True)
class ZoneHasFreeSlot(Condition):
    """칸 방식 존에 빈 칸이 있는가. 필드는 공개이므로 확정된다."""

    who: PlayerRef
    zone: Zone

    def evaluate(self, view, context) -> ConditionResult:
        zone_view = view.player(self.who.resolve(context)).zone(self.zone)
        capacity = zone_view.capacity
        if capacity is None:
            # 칸 수가 없는 존은 언제나 자리가 있다.
            return ConditionResult.TRUE
        return ConditionResult.from_bool(zone_view.size < capacity)

    def canonical_state(self) -> tuple:
        return ("zone_has_free_slot", self.who.value, self.zone.value)

    def to_dict(self) -> dict:
        return {
            "kind": "zone_has_free_slot",
            "who": self.who.value,
            "zone": self.zone.value,
        }

    def describe_ko(self) -> str:
        return f"{self.who} {self.zone.value} 에 빈 칸"


@dataclass(frozen=True, slots=True)
class CardIsInZone(Condition):
    """
    그 카드가 이 존에 있는가.

    ``instance`` 가 ``None`` 이면 문맥의 ``source`` 를 본다. 문맥에 그것도
    없으면 **``UNKNOWN``** 이다 — 예외를 던지지도, 거짓으로 접지도 않는다.

    보이지 않는 카드도 ``UNKNOWN`` 이다. **"안 보인다" 와 "없다" 는 다르다.**
    상대 패에 있는 카드를 두고 "묘지에 없다" 고 단정할 수는 없다.
    """

    zone: Zone
    who: PlayerRef = PlayerRef.CONTROLLER
    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            # 관측에 없다. 다른 존에 숨어 있을 수도, 아예 없을 수도 있다.
            return ConditionResult.UNKNOWN
        owner = self.who.resolve(context)
        return ConditionResult.from_bool(
            card.zone is self.zone and card.controller == owner
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "card_is_in_zone",
            self.zone.value,
            self.who.value,
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "card_is_in_zone",
            "zone": self.zone.value,
            "who": self.who.value,
        }
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 {self.who} {self.zone.value} 에 있음"


@dataclass(frozen=True, slots=True)
class CardIsFaceUp(Condition):
    """
    그 카드가 앞면인가.

    보이지 않으면 ``UNKNOWN`` 이다. 상대의 세트 카드는 자리는 보여도
    앞면/뒷면 판정은 할 수 있지만 (``CardView.face_up``), 애초에 관측에
    없는 카드는 판정할 수 없다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(card.face_up)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "card_is_face_up",
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "card_is_face_up"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 앞면"
