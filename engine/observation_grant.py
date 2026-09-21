"""
효과가 주는 관측 권한 — **선언과 계산** (Phase 2-AA).

    Effect
      → ObservationGrant      이 파일. 효과가 무엇을 보게 하는지 **선언**한다
      → derive_policy         지금 살아 있는 것만 남긴다
      → ObservationPolicy     값 (:mod:`engine.observation`)
      → GameStateView         viewer 마다 다른 것을 본다

왜 값과 따로 있는가
-------------------
관측 계층이 권한의 **값**을 읽어야 하는데, 권한이 살아 있는지 판정하려면
**조건 평가기**가 필요하고 조건 평가기는 거꾸로 관측을 읽는다. 값을
아래에 두고 계산을 위에 두면 그 고리가 풀린다 — 새 시스템을 만든 것이
아니라 **한 파일을 두 계층으로 나눈 것**이다.

권한은 저장하지 않는다
----------------------
플래그를 켜 두지 않는다. 권한은 언제나 **지금 판에서 다시 계산된다** —
선언을 들고 있는 카드가 아직 그 자리에 있는가, 조건이 지금 참인가.

그래서 카드가 사라지면 권한도 사라진다. 지우는 코드가 따로 있는 것이
아니라 **애초에 계산되지 않는다.** 껐다 켜는 상태가 없으면 어긋날 수도
없다.

카드 이름을 보지 않는다
-----------------------
이 파일에 카드 번호도 이름도 없다. 권한은 선언에서 나오고, 선언은 공식
스크립트를 읽어서 쓴다. ``if card.name == "..."`` 같은 것이 들어오면 그
순간 이 계층은 일반화된 경계가 아니라 특수 처리 목록이 된다.

``UNKNOWN`` 은 권한이 아니다
----------------------------
조건이 ``UNKNOWN`` 이면 권한은 **생기지 않는다.** 이 프로젝트가
``UNKNOWN`` 을 허가로 바꾸지 않는 다른 모든 자리와 같다 — 모르는데 보여
주면 숨은 정보가 새는 쪽으로 틀린다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.condition import Condition, ConditionContext, ConditionResult, PlayerRef
from engine.ids import EffectRef, InstanceId
from engine.observation import (
    ActivePermission,
    ObservationPermission,
    ObservationPolicy,
)
from engine.vocabulary import Zone


@dataclass(frozen=True, slots=True)
class ObservationGrant:
    """
    "이 카드가 여기 있는 동안 누가 무엇을 볼 수 있다" 는 **선언**.

    공식 스크립트의 모양이 그대로 온다. 마인드 온 에어(66690411)를 예로
    들면::

        e1:SetType(EFFECT_TYPE_FIELD)
        e1:SetCode(EFFECT_PUBLIC)
        e1:SetRange(LOCATION_MZONE)            → active_zones={MZONE}
        e1:SetTargetRange(0, LOCATION_HAND)    → subject=OPPONENT
                                                 (앞의 0 은 자신 쪽 없음)

    :attr:`beneficiary` 와 :attr:`subject` 는 **카드의 컨트롤러 기준**이다.
    절대 번호를 적으면 같은 선언을 양쪽이 쓸 수 없다 (조건 계층의
    :class:`~engine.condition.PlayerRef` 와 같은 이유).
    """

    permission: ObservationPermission
    source: EffectRef
    """어느 효과가 주는가. **권한의 출처를 추적하는 열쇠다.**"""
    holder: InstanceId
    """그 효과를 들고 있는 카드. 이 카드가 사라지면 권한도 사라진다."""
    active_zones: frozenset[Zone]
    """
    holder 가 **어디에 있어야** 살아 있는가 (``SetRange``).

    비워 두지 않는다 — 비우면 "어디에 있든" 이 되고, 그것은 원본이 말하지
    않은 것을 주장하는 일이다.
    """
    beneficiary: PlayerRef = PlayerRef.CONTROLLER
    """누가 보게 되는가."""
    subject: PlayerRef = PlayerRef.OPPONENT
    """누구의 정보인가."""
    condition: Condition | None = None
    """
    언제 살아 있는가 (``SetCondition``).

    ``None`` 은 **"조건이 없다"** 는 뜻이다 — 원본에 ``SetCondition`` 이
    없으면 조건이 없는 것이 사실이다. 옮기지 못한 조건은 ``None`` 이
    아니라 :class:`~engine.condition.UnimplementedRule` 로 적어야
    ``UNKNOWN`` 이 되고, 그러면 권한이 생기지 않는다.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.active_zones, frozenset):
            raise TypeError("active_zones 는 frozenset 이어야 합니다 — 선언은 불변입니다.")
        if not self.active_zones:
            raise ValueError(
                "holder 가 어디에 있어야 하는지 적어야 합니다. 비워 두면 "
                "'어디에 있든' 이 되고, 그것은 원본이 말하지 않은 주장입니다."
            )
        if self.beneficiary is self.subject is None:  # pragma: no cover - 방어
            raise ValueError("받는 사람과 대상이 모두 필요합니다.")

    def canonical_state(self) -> tuple:
        return (
            self.permission.value,
            (self.source.card_id, self.source.ordinal),
            self.holder.value,
            tuple(sorted(z.value for z in self.active_zones)),
            self.beneficiary.value,
            self.subject.value,
            self.condition.canonical_state() if self.condition is not None else None,
        )

    def describe_ko(self) -> str:
        return (
            f"{self.beneficiary} 가 {self.subject} 의 "
            f"{self.permission.describe_ko()} ({self.source})"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def derive_policy(state, grants) -> ObservationPolicy:
    """
    지금 판에서 **살아 있는 권한만** 계산한다.

    세 관문을 전부 통과해야 살아 있다.

    1. holder 카드가 아직 판에 있는가.
    2. 그 카드가 :attr:`ObservationGrant.active_zones` 안에 있는가
       (``SetRange``).
    3. 조건이 **참**인가. ``UNKNOWN`` 도 ``FALSE`` 도 권한이 아니다.

    조건은 holder 의 컨트롤러 시점 **기본 관측**으로 판정한다. 권한을
    적용한 관측으로 판정하면 "권한이 있어서 조건이 참이고 조건이 참이라
    권한이 있다" 가 된다.

    ``state`` 를 **바꾸지 않는다.**
    """
    # 순환 import 를 피한다 — 관측이 이 파일을 읽지 이 파일이 관측을
    # 소유하지 않는다.
    from engine.condition.evaluator import ConditionEvaluator
    from engine.game_state_view import GameStateView

    active: list[ActivePermission] = []
    views: dict[int, GameStateView] = {}

    for grant in grants:
        card = state.find_instance(grant.holder)
        if card is None:
            continue  # 1. 판에 없다
        if card.zone not in grant.active_zones:
            continue  # 2. 그 자리에 없다

        controller = card.controller
        if grant.condition is not None:
            if controller not in views:
                views[controller] = GameStateView.from_state(state, viewer=controller)
            verdict = ConditionEvaluator(views[controller]).result(
                grant.condition,
                ConditionContext(player=controller, source=grant.holder),
            )
            if verdict is not ConditionResult.TRUE:
                continue  # 3. 거짓이거나 **모른다**

        viewer = controller if grant.beneficiary is PlayerRef.CONTROLLER else 1 - controller
        about = controller if grant.subject is PlayerRef.CONTROLLER else 1 - controller
        active.append(
            ActivePermission(
                permission=grant.permission,
                viewer=viewer,
                about=about,
                source=grant.source,
                holder=grant.holder,
            )
        )

    return ObservationPolicy(permissions=tuple(active))


__all__ = [
    "ObservationGrant",
    "derive_policy",
]
