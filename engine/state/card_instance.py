"""
듀얼 중 카드 한 장의 상태.

**카드 정의와 카드 인스턴스를 분리한다.** 설계 문서 "결함 2" 의 해법이다.

``CardRepository`` 는 같은 ``Card`` 객체를 계속 돌려주고 (``r.get(2511) is
r.get(2511)`` -> ``True``), ``Card`` 는 가변 dataclass 다. 듀얼 상태가 ``Card``
를 직접 고치면 **전역 카드 정의가 오염되어** 검색 결과까지 틀어진다.

그래서 :class:`CardInstance` 는 ``card_id`` 만 들고, 정의는 프로퍼티로 매번
리포지토리에서 읽는다. 정의를 **복사하지도, 상속하지도, 변경하지도 않는다.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.ids import EffectRef, InstanceId
from engine.vocabulary import Position, Zone

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from core.card_model import Card
    from core.card_repository import CardRepository


@dataclass(frozen=True, slots=True)
class PreviousState:
    """
    직전 위치 / 표시 형식 / 컨트롤러.

    장식이 아니다. 조건 술어 ``previous_location`` 758건과
    ``previous_position`` / ``previous_controller`` 가 이 값 없이는 평가되지
    않는다. 판정 자체는 Phase 3 의 ConditionEvaluator 몫이고, 여기서는
    **기록만** 한다.
    """

    location: Zone | None = None
    position: Position | None = None
    controller: int | None = None

    def as_tuple(self) -> tuple[str | None, str | None, int | None]:
        return (
            self.location.value if self.location else None,
            self.position.value if self.position else None,
            self.controller,
        )


@dataclass(frozen=True, slots=True)
class AppliedEffect:
    """
    이 카드에 걸려 있는 일시 효과의 **자리표시 데이터**.

    Phase 1 은 효과를 실행하지 않으므로 해석하지 않고 보관만 한다.
    실제 적용 · 소멸 판정은 Phase 8 (지속 / 치환 효과) 이다.
    """

    effect_ref: EffectRef
    source: InstanceId | None = None
    reset_label: str | None = None
    """``RESET_*`` 상수 이름. Phase 8 에서 해석한다."""

    def as_tuple(self) -> tuple[int, int, int | None, str | None]:
        return (
            self.effect_ref.card_id,
            self.effect_ref.ordinal,
            self.source.value if self.source else None,
            self.reset_label,
        )


@dataclass(slots=True)
class CardInstance:
    """듀얼 한 판 안의 카드 한 장. 정의가 아니라 **상태**를 소유한다."""

    instance_id: InstanceId
    card_id: int
    owner: int
    controller: int
    zone: Zone
    sequence: int = 0
    position: Position = Position.FACEDOWN_ATTACK
    previous: PreviousState = field(default_factory=PreviousState)
    counters: dict[str, int] = field(default_factory=dict)
    """``COUNTER_*`` 이름 -> 개수."""
    equipped_to: InstanceId | None = None
    materials: list[InstanceId] = field(default_factory=list)
    """엑시즈 소재 등, 이 카드가 들고 있는 카드들."""
    temporary_effects: list[AppliedEffect] = field(default_factory=list)
    status_flags: int = 0
    """``STATUS_*`` 비트마스크. 값은 ``EngineVocabulary.statuses`` 에서 읽는다."""

    _repository: Any = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # 카드 정의 (읽기 전용)
    # ------------------------------------------------------------------
    @property
    def definition(self) -> "Card":
        """
        ``CardRepository`` 가 소유한 카드 정의. **절대 수정하지 않는다.**
        """
        if self._repository is None:
            raise RuntimeError(
                f"{self} 에 리포지토리가 연결되어 있지 않아 카드 정의를 읽을 수 없습니다."
            )
        card = self._repository.get(self.card_id)
        if card is None:
            raise KeyError(f"카드 정의를 찾을 수 없습니다: {self.card_id}")
        return card

    @property
    def repository(self) -> "CardRepository | None":
        return self._repository

    def bind(self, repository: "CardRepository") -> "CardInstance":
        """리포지토리를 연결한다 (정의를 복사하지 않는다)."""
        self._repository = repository
        return self

    @property
    def name(self) -> str:
        """표시용 이름. 정의가 없으면 카드 ID 로 대신한다."""
        if self._repository is None:
            return str(self.card_id)
        card = self._repository.get(self.card_id)
        return card.name if card is not None else str(self.card_id)

    # ------------------------------------------------------------------
    # 위치 · 표시 형식 · 컨트롤러
    # ------------------------------------------------------------------
    def snapshot_previous(self) -> None:
        """현재 위치 / 표시 형식 / 컨트롤러를 ``previous`` 로 넘긴다."""
        self.previous = PreviousState(
            location=self.zone,
            position=self.position,
            controller=self.controller,
        )

    def place(
        self,
        zone: Zone,
        sequence: int = 0,
        *,
        position: Position | None = None,
        controller: int | None = None,
        remember_previous: bool = True,
    ) -> None:
        """
        카드를 새 위치에 둔다. 규칙 판정은 하지 않는다 —
        "옮길 수 있는가" 는 Phase 4, "옮기면 무엇이 일어나는가" 는 Phase 2 다.
        """
        if remember_previous:
            self.snapshot_previous()
        self.zone = zone
        self.sequence = sequence
        if position is not None:
            self.position = position
        if controller is not None:
            self.controller = controller

    def set_position(self, position: Position, *, remember_previous: bool = True) -> None:
        if remember_previous:
            self.snapshot_previous()
        self.position = position

    def set_controller(self, controller: int, *, remember_previous: bool = True) -> None:
        if remember_previous:
            self.snapshot_previous()
        self.controller = controller

    @property
    def is_faceup(self) -> bool:
        return self.position in (
            Position.FACEUP,
            Position.FACEUP_ATTACK,
            Position.FACEUP_DEFENSE,
        )

    # ------------------------------------------------------------------
    # 카운터
    # ------------------------------------------------------------------
    def add_counter(self, name: str, amount: int = 1) -> int:
        if amount < 0:
            raise ValueError("음수는 remove_counter 로 제거하세요.")
        key = name.upper()
        self.counters[key] = self.counters.get(key, 0) + amount
        return self.counters[key]

    def remove_counter(self, name: str, amount: int = 1) -> int:
        key = name.upper()
        remaining = self.counters.get(key, 0) - amount
        if remaining > 0:
            self.counters[key] = remaining
        else:
            self.counters.pop(key, None)
            remaining = 0
        return remaining

    def counter(self, name: str) -> int:
        return self.counters.get(name.upper(), 0)

    # ------------------------------------------------------------------
    # 상태 플래그
    # ------------------------------------------------------------------
    def set_status(self, mask: int) -> None:
        self.status_flags |= mask

    def clear_status(self, mask: int) -> None:
        self.status_flags &= ~mask

    def has_status(self, mask: int) -> bool:
        return bool(self.status_flags & mask)

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "CardInstance":
        """
        상태만 독립적으로 복제한다. 카드 정의는 불변 참조이므로 공유해도 된다.
        """
        return CardInstance(
            instance_id=self.instance_id,
            card_id=self.card_id,
            owner=self.owner,
            controller=self.controller,
            zone=self.zone,
            sequence=self.sequence,
            position=self.position,
            previous=self.previous,  # frozen
            counters=dict(self.counters),
            equipped_to=self.equipped_to,  # frozen
            materials=list(self.materials),  # 원소는 frozen
            temporary_effects=list(self.temporary_effects),  # 원소는 frozen
            status_flags=self.status_flags,
            _repository=self._repository,  # 읽기 전용 공유
        )

    def canonical_state(self) -> tuple:
        """
        해시용 정규 표현. 파이썬 객체 주소나 기본 ``hash()`` 를 쓰지 않는다.
        """
        return (
            self.instance_id.value,
            self.card_id,
            self.owner,
            self.controller,
            self.zone.value,
            self.sequence,
            self.position.value,
            self.previous.as_tuple(),
            tuple(sorted(self.counters.items())),
            self.equipped_to.value if self.equipped_to else None,
            tuple(m.value for m in self.materials),
            tuple(e.as_tuple() for e in self.temporary_effects),
            self.status_flags,
        )

    def __str__(self) -> str:
        return f"{self.instance_id} {self.name} ({self.zone.value})"
