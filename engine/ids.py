"""
듀얼 안에서 쓰는 식별자.

두 가지를 구분한다.

- :class:`InstanceId` — **카드 한 장**. 같은 카드명 3장을 서로 구분한다.
- :class:`EffectRef` — **효과 하나**. 체인 링크가 "어느 효과인가"를 가리킨다.

``EffectSpec.index`` (Lua 변수명 ``e1``, ``e2``) 를 효과 식별자로 쓸 수 없다.
실측으로 스크립트 12,968장 중 **4,883장**이 한 카드 안에서 같은 ``index`` 를
서로 다른 내용의 효과에 재사용한다::

    라뷰린스 쿠클락 (2511)  ->  ['e1', 'e2', 'e1']

``for i=1,3 do local e1=... end`` 처럼 루프 안에서 같은 변수명을 다시 쓰기
때문이다. 그래서 식별자를 ``(card_id, ordinal)`` 로 잡는다. ``ordinal`` 은
``card.script.effects`` 안에서의 위치이고, 이 위치는 파서가 원문 등장 순서를
유지하므로 같은 스크립트에 대해 항상 같다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from core.card_model import Card, EffectSpec


@dataclass(frozen=True, slots=True, order=True)
class InstanceId:
    """
    듀얼 한 판 안에서 카드 인스턴스를 유일하게 가리키는 값.

    단조 증가하는 정수 하나다. 할당 순서가 결정론적이므로
    같은 초기 상태 + 같은 조작 순서는 항상 같은 ``InstanceId`` 를 만든다.
    한 번 쓴 번호는 재사용하지 않는다 (카드가 존을 옮겨도 번호는 그대로).
    """

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"InstanceId 는 음수일 수 없습니다: {self.value}")

    def __str__(self) -> str:
        return f"#{self.value}"

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"InstanceId({self.value})"


class InstanceIdAllocator:
    """
    ``InstanceId`` 발급기. 상태는 "다음 번호" 하나뿐이라 복제가 자명하다.
    """

    __slots__ = ("_next",)

    def __init__(self, start: int = 0):
        if start < 0:
            raise ValueError(f"시작 번호는 음수일 수 없습니다: {start}")
        self._next = start

    @property
    def next_value(self) -> int:
        return self._next

    def allocate(self) -> InstanceId:
        instance_id = InstanceId(self._next)
        self._next += 1
        return instance_id

    def clone(self) -> InstanceIdAllocator:
        return InstanceIdAllocator(self._next)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, InstanceIdAllocator) and other._next == self._next
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"InstanceIdAllocator(next={self._next})"


@dataclass(frozen=True, slots=True, order=True)
class EffectRef:
    """
    카드의 효과 하나를 가리키는 불변 식별자.

    ``ordinal`` 은 ``card.script.effects`` 안에서의 0-기반 위치다.
    ``EffectSpec.index`` 를 쓰지 않는 이유는 모듈 설명 참고.
    """

    card_id: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError(f"ordinal 은 음수일 수 없습니다: {self.ordinal}")

    def resolve(self, card: "Card") -> "EffectSpec | None":
        """
        이 참조가 가리키는 :class:`~core.card_model.EffectSpec` 을 돌려준다.
        카드가 다르거나 스크립트가 없거나 범위를 벗어나면 ``None``.

        카드 정의를 **읽기만** 한다.
        """
        if card.id != self.card_id or card.script is None:
            return None
        effects = card.script.effects
        if self.ordinal >= len(effects):
            return None
        return effects[self.ordinal]

    def __str__(self) -> str:
        return f"{self.card_id}:e[{self.ordinal}]"

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"EffectRef(card_id={self.card_id}, ordinal={self.ordinal})"


def effect_refs(card: "Card") -> list[EffectRef]:
    """카드의 모든 효과에 대한 :class:`EffectRef` 목록 (원문 순서)."""
    if card.script is None:
        return []
    return [EffectRef(card.id, i) for i in range(len(card.script.effects))]


def iter_effects(card: "Card") -> Iterator[tuple[EffectRef, "EffectSpec"]]:
    """``(EffectRef, EffectSpec)`` 쌍을 원문 순서로 훑는다."""
    if card.script is None:
        return
    for i, spec in enumerate(card.script.effects):
        yield EffectRef(card.id, i), spec
