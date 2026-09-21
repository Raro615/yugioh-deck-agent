"""
관측 권한의 **값** — 누가 무엇을 더 볼 수 있는가 (Phase 2-AA).

    Effect
      → ObservationGrant      효과가 **선언**한다  (engine/observation_grant.py)
      → ObservationPolicy     지금 살아 있는 권한만 남는다 (derived)
      → GameStateView         viewer 마다 다른 것을 본다   ← **이 파일을 읽는다**

이 파일은 **값만** 담는다. 조건도 판도 읽지 않는다 — 관측 계층
(:mod:`engine.game_state_view`)이 이 파일을 읽어야 하는데, 조건 평가기는
거꾸로 관측을 읽기 때문이다. 선언과 계산은 한 계층 위
(:mod:`engine.observation_grant`)에 있다.

세 가지가 계속 다른 것이다
--------------------------
========================  ==================================================
``GameState``             엔진이 아는 **실제** 상태. 언제나 전부 안다
``GameStateView``         그 사람이 **보는** 것. viewer 마다 다르다
``ObservationPolicy``     지금 누가 무엇을 **더** 볼 수 있는가
========================  ==================================================

권한은 **저장하지 않는다**
--------------------------
플래그를 켜 두지 않는다. 권한은 언제나 **지금 판에서 다시 계산된다** —
선언을 들고 있는 카드가 아직 그 자리에 있는가, 조건이 지금 참인가.

그래서 카드가 사라지면 권한도 사라진다. 지우는 코드가 따로 있는 것이
아니라 **애초에 계산되지 않는다.** 껐다 켜는 상태가 없으면 어긋날 수도
없다.

카드 이름을 보지 않는다
-----------------------
이 파일에 카드 번호도 이름도 없다. 권한은 선언에서 나오고, 선언은 공식
스크립트를 읽어서 쓴다. ``if card.name == "..."`` 같은 것이 들어오면
그 순간 이 계층은 일반화된 경계가 아니라 특수 처리 목록이 된다.

``UNKNOWN`` 은 권한이 아니다
----------------------------
조건이 ``UNKNOWN`` 이면 권한은 **생기지 않는다.** 이 프로젝트가
``UNKNOWN`` 을 허가로 바꾸지 않는 다른 모든 자리와 같다 — 모르는데 보여
주면 숨은 정보가 새는 쪽으로 틀린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.ids import EffectRef, InstanceId


class ObservationPermission(str, Enum):
    """
    평소에는 볼 수 없는 것을 **볼 수 있게 되는** 종류.

    둘을 합치지 않는다. 상대 필드의 뒷면 카드를 확인하는 것과 상대 패가
    공개되는 것은 **다른 일**이다 — 뒷면 카드를 확인했다고 그 카드가
    모두에게 공개되지는 않는다.
    """

    REVEAL_HAND = "reveal_hand"
    """상대가 패를 공개한 채로 둔다."""
    INSPECT_FACE_DOWN = "inspect_face_down"
    """상대 필드의 뒷면 표시 카드를 확인할 수 있다."""

    def describe_ko(self) -> str:
        return {
            ObservationPermission.REVEAL_HAND: "패 공개",
            ObservationPermission.INSPECT_FACE_DOWN: "뒷면 카드 확인",
        }[self]


#: 이 권한이 공식 스크립트의 **무엇에서** 왔는가. 근거다.
#:
#: 이름을 추측하지 않았다. 저장소의 ``c*.lua`` 12,702개와
#: ``data/constants/constant.lua`` 를 읽어서 확인한 것이다.
LUA_PERMISSION_SOURCES: dict[ObservationPermission, str | None] = {
    ObservationPermission.REVEAL_HAND: "EFFECT_PUBLIC (constant.lua:492, 실제 카드 20장)",
    # **없다.** "상대의 세트 카드를 언제든 확인한다" 에 해당하는 상수가
    # 코퍼스에 없고, 그렇게 적힌 카드(마인드 스캔 34298391)에는 아예
    # 스크립트가 없다. 빈 칸으로 두는 대신 ``None`` 으로 적어 둔다 —
    # 빈 칸은 "없다" 로, 적어 둔 것은 "아직" 으로 읽힌다.
    ObservationPermission.INSPECT_FACE_DOWN: None,
}


@dataclass(frozen=True, slots=True)
class ActivePermission:
    """
    **지금 살아 있는** 권한 하나. 자리 번호가 절대 번호로 풀려 있다.

    :attr:`source` 를 들고 다니는 것이 중요하다 — 권한이 여럿일 때
    "어느 효과가 준 것인가" 를 말할 수 있어야 하나가 사라져도 나머지가
    남는다는 것을 확인할 수 있다.
    """

    permission: ObservationPermission
    viewer: int
    """보게 된 사람."""
    about: int
    """누구의 정보인가."""
    source: EffectRef
    holder: InstanceId

    def __post_init__(self) -> None:
        for name in ("viewer", "about"):
            if getattr(self, name) not in (0, 1):
                raise ValueError(f"{name} 는 0 또는 1 입니다: {getattr(self, name)}")

    def canonical_state(self) -> tuple:
        return (
            self.permission.value,
            self.viewer,
            self.about,
            (self.source.card_id, self.source.ordinal),
            self.holder.value,
        )

    def to_dict(self) -> dict:
        """
        **카드의 정체를 담지 않는다.** 누가 무엇을 볼 수 있게 되었는가만
        말한다 — 권한의 존재는 공개 정보지만 그것이 보여 주는 내용은
        아니다.
        """
        return {
            "permission": self.permission.value,
            "viewer": self.viewer,
            "about": self.about,
            "source": {
                "card_id": self.source.card_id,
                "ordinal": self.source.ordinal,
            },
        }

    def describe_ko(self) -> str:
        return (
            f"P{self.viewer} 가 P{self.about} 의 "
            f"{self.permission.describe_ko()} ({self.source})"
        )


@dataclass(frozen=True, slots=True)
class ObservationPolicy:
    """
    이 관측을 만들 때 적용되는 권한들. **불변이고 파생된 값이다.**

    저장된 상태가 아니다 — :meth:`derive` 가 지금 판에서 다시 계산한다.
    그래서 "지우는 것을 깜빡한 권한" 이 있을 수 없다.
    """

    permissions: tuple[ActivePermission, ...] = ()

    def permits(
        self,
        permission: ObservationPermission,
        viewer: int,
        about: int,
    ) -> bool:
        """
        ``viewer`` 가 ``about`` 의 그것을 볼 수 있는가.

        **자기 것을 묻지 않는다.** 자기 패를 보는 것은 권한이 아니라 기본
        공개 범위의 일이고, 여기서 참이 되면 두 계층이 같은 것을 두 번
        말하게 된다.
        """
        return any(
            active.permission is permission
            and active.viewer == viewer
            and active.about == about
            for active in self.permissions
        )

    def sources(
        self,
        permission: ObservationPermission,
        viewer: int,
        about: int,
    ) -> tuple[EffectRef, ...]:
        """
        그 권한을 주고 있는 효과들. **여럿일 수 있다.**

        순서는 선언 순서 그대로다 — 집합으로 만들면 같은 판이 다른 순서를
        낳는다.
        """
        found: list[EffectRef] = []
        for active in self.permissions:
            if (
                active.permission is permission
                and active.viewer == viewer
                and active.about == about
                and active.source not in found
            ):
                found.append(active.source)
        return tuple(found)

    @property
    def is_empty(self) -> bool:
        return not self.permissions

    def canonical_state(self) -> tuple:
        return tuple(active.canonical_state() for active in self.permissions)

    def to_dict(self) -> dict:
        return {"permissions": [active.to_dict() for active in self.permissions]}

    def describe_ko(self) -> str:
        if not self.permissions:
            return "추가로 보이는 것 없음"
        return " · ".join(active.describe_ko() for active in self.permissions)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


#: 아무 권한도 없는 정책. **기본값이고, 기본값이 맞다.**
EMPTY_POLICY = ObservationPolicy()


__all__ = [
    "ObservationPermission",
    "LUA_PERMISSION_SOURCES",
    "ActivePermission",
    "ObservationPolicy",
    "EMPTY_POLICY",
]
