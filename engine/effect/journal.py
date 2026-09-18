"""
EventJournal — 실행된 효과와 그 변화를 **순서대로** 적어 두는 append-only 기록.

    executor.execute()
        ↓  GameState mutation
        ↓  StateDelta
        ↓  journal.record(...)      ← 여기

Journal 은 판을 소유하지도 바꾸지도 않는다
------------------------------------------
**기록이 상태를 건드리면 기록이 아니다.** :class:`EventJournal` 은
``GameState`` 를 참조조차 하지 않는다. 실행기가 판을 바꾸고, 그 결과로 만든
Delta 를 journal 에 적는다. 방향은 한 쪽뿐이다.

같은 이유로 journal 은 ``GameState`` 안에 살지 않는다. 안에 넣으면
``state_hash()`` 가 "판의 모양" 이 아니라 "어떤 경로로 왔는가" 를 뜻하게
되고, Phase 1 이 세운 "같은 판은 경로와 무관하게 같은 해시" 가 깨진다.
판의 해시와 역사의 해시는 **다른 질문**이므로 따로 둔다.

덧붙이기만 한다
---------------
:meth:`EventJournal.append` 와 :meth:`EventJournal.record` 뿐이다. 지우기 ·
고치기 · 바꿔치기는 **만들지 않는다.** 이미 적은 것을 고칠 수 있으면
재생(replay)과 디버깅의 근거가 사라진다.

결정론
------
:attr:`EffectEvent.sequence` 가 identity 다. 무작위 UUID 도, 시각도, 객체
주소도 쓰지 않는다 — 같은 입력이면 같은 번호, 같은 순서, 같은
``canonical_state()`` 여야 한다.

재생은 아직 하지 않는다
-----------------------
journal 로 판을 되살리는 것은 이 단계의 일이 아니다 (ADR-008). 여기서는
**적는 데까지**만 한다. 다만 나중에 되살리는 데 필요한 것 — 어느 효과가 ·
누가 · 무엇을 했고 · 판이 어떻게 달라졌는가 — 를 빠짐없이 적어 둔다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterator

from engine.effect.delta import StateDelta, canonical_deltas
from engine.effect.resolution import AppliedOperation
from engine.ids import EffectRef, InstanceId


class JournalError(RuntimeError):
    """기록이 순서를 잃었다. 고치는 것이 아니라 멈추는 쪽이 맞다."""


@dataclass(frozen=True, slots=True)
class EffectEvent:
    """
    효과 하나가 해결되어 판이 달라진 **사건 하나.** 불변이다.

    ``sequence`` 가 identity 다. 무작위 식별자를 쓰지 않는 이유는 단순하다 —
    같은 듀얼을 같은 입력으로 다시 돌렸을 때 기록이 달라지면 그 기록으로는
    아무것도 증명할 수 없다.

    ``effect_ref`` 는 언제나 :class:`~engine.ids.EffectRef` 다.
    ``EffectSpec.index`` (Lua 변수명 ``"e1"``, 한 카드 안에서 중복됨) 를
    실행 identity 로 쓰지 않는다는 Phase 2-D-1 의 원칙 그대로다.
    """

    sequence: int
    effect_ref: EffectRef
    actor: int
    """효과를 발동한 플레이어. 카드의 주인 · 컨트롤러와 다를 수 있다."""
    applied: tuple[AppliedOperation, ...] = ()
    """어떤 **일**을 실행했는가."""
    deltas: tuple[StateDelta, ...] = ()
    """그 실행으로 판이 **어떻게 달라졌는가.** 순서가 곧 사실이다."""
    source: InstanceId | None = None
    """효과를 발동한 카드. 필드를 떠난 뒤 해결되는 효과가 있으므로 없을 수 있다."""

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError(f"sequence 는 0 이상입니다: {self.sequence}")
        if self.actor not in (0, 1):
            raise ValueError(f"actor 는 0 또는 1 입니다: {self.actor}")
        for name in ("applied", "deltas"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 사건은 불변입니다.")

    @property
    def changed_state(self) -> bool:
        """이 사건이 판을 바꿨는가."""
        return bool(self.deltas)

    @property
    def instances(self) -> tuple[InstanceId, ...]:
        """이 사건이 건드린 카드들. 변화 순서대로, 중복 없이."""
        seen: list[InstanceId] = []
        for delta in self.deltas:
            instance = getattr(delta, "instance", None)
            if isinstance(instance, InstanceId) and instance not in seen:
                seen.append(instance)
        return tuple(seen)

    def canonical_state(self) -> tuple:
        return (
            self.sequence,
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.actor,
            self.source.value if self.source is not None else None,
            tuple(a.canonical_state() for a in self.applied),
            canonical_deltas(self.deltas),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "sequence": self.sequence,
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "actor": self.actor,
            "applied": [a.to_dict() for a in self.applied],
            "deltas": [d.to_dict() for d in self.deltas],
        }
        if self.source is not None:
            data["source"] = self.source.value
        return data

    def describe_ko(self) -> str:
        changes = ", ".join(delta.describe_ko() for delta in self.deltas) or "변화 없음"
        return f"#{self.sequence} {self.effect_ref} P{self.actor}: {changes}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class EventJournal:
    """
    사건을 **덧붙이기만** 하는 기록.

    ``GameState`` 를 들고 있지 않고, 어떤 메서드도 판을 바꾸지 않는다.
    파일 · 데이터베이스 · 네트워크도 없다 — 메모리에 순서대로 쌓는 것이
    이 단계에 필요한 전부다.
    """

    __slots__ = ("_events",)

    def __init__(self, events: "tuple[EffectEvent, ...] | None" = None):
        self._events: list[EffectEvent] = []
        for event in events or ():
            self.append(event)

    # ------------------------------------------------------------------
    # 덧붙이기 — 이것뿐이다
    # ------------------------------------------------------------------
    def append(self, event: EffectEvent) -> EffectEvent:
        """
        이미 만들어진 사건을 덧붙인다.

        번호가 어긋나면 **거부한다.** 조용히 다시 매기지 않는다 — 번호를
        고쳐 주면 기록과 실제 실행 순서가 달라진 것을 아무도 모르게 된다.
        """
        if not isinstance(event, EffectEvent):
            raise TypeError(f"EffectEvent 가 필요합니다: {type(event).__name__}")
        if event.sequence != len(self._events):
            raise JournalError(
                f"다음 번호는 {len(self._events)} 인데 {event.sequence} 가 "
                "들어왔습니다. 기록은 순서를 지킵니다."
            )
        self._events.append(event)
        return event

    def record(
        self,
        effect_ref: EffectRef,
        actor: int,
        applied: "tuple[AppliedOperation, ...]" = (),
        deltas: "tuple[StateDelta, ...]" = (),
        source: InstanceId | None = None,
    ) -> EffectEvent:
        """다음 번호를 붙여 사건을 만들고 덧붙인다. 실행기가 쓰는 쪽이다."""
        return self.append(
            EffectEvent(
                sequence=len(self._events),
                effect_ref=effect_ref,
                actor=actor,
                applied=applied,
                deltas=deltas,
                source=source,
            )
        )

    # ------------------------------------------------------------------
    # 읽기
    # ------------------------------------------------------------------
    @property
    def events(self) -> tuple[EffectEvent, ...]:
        """기록 전체. **tuple 이다** — 밖에서 덧붙이거나 지울 수 없다."""
        return tuple(self._events)

    @property
    def next_sequence(self) -> int:
        return len(self._events)

    def deltas(self) -> tuple[StateDelta, ...]:
        """모든 사건의 변화를 순서대로 이어 붙인다."""
        found: list[StateDelta] = []
        for event in self._events:
            found.extend(event.deltas)
        return tuple(found)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[EffectEvent]:
        return iter(self._events)

    def __getitem__(self, index: int) -> EffectEvent:
        return self._events[index]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, EventJournal)
            and other.canonical_state() == self.canonical_state()
        )

    # ------------------------------------------------------------------
    # 결정론적 표현
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        """같은 사건 순서면 언제나 같은 값. 객체 주소도 시각도 들어가지 않는다."""
        return tuple(event.canonical_state() for event in self._events)

    def journal_hash(self) -> str:
        """
        기록 전체의 SHA-256. ``GameState.state_hash()`` 와 **다른 질문**이다 —
        저쪽은 "판이 어떤 모양인가", 이쪽은 "어떤 역사를 지나왔는가".
        """
        payload = json.dumps(
            self.canonical_state(), ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {"events": [event.to_dict() for event in self._events]}

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EventJournal {len(self._events)}건>"


__all__ = ["EffectEvent", "EventJournal", "JournalError"]
