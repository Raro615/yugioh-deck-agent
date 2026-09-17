"""
PlayerAction — "무엇을 하려고 하는가".

ADR-001 의 구현이다. **Action 은 고르는 주체가 고르는 것**이고, Effect 는
효과 해결이 만드는 변화다. 둘은 다른 타입이고 다른 어휘를 쓴다.

Action 은 **명령서일 뿐 실행이 아니다.** 만들어도 아무 일도 일어나지 않는다.

    action = PlayerAction.normal_summon(actor=0, source=instance_id)
    # 카드는 아직 패에 있다. 소환권도 그대로다.

analysis.ActionKind 와 헷갈리지 않기
------------------------------------
``analysis.effect_model`` 에 이미 ``ActionKind`` 가 있다. 그것은 **효과가 하는
일**(``DESTROY``, ``BANISH``, ``TO_GRAVE`` …)이고 여기의 어휘와 정반대다.
실제로 ``normal_summon`` 이라는 이름이 양쪽에 있는데 뜻이 다르다.

- ``analysis.ActionKind.NORMAL_SUMMON`` — 효과 해결 중 ``Duel.Summon`` 이
  호출된다 (실측 74개 효과). 소환권을 쓸 수도, 안 쓸 수도 있다.
- ``PlayerActionKind.NORMAL_SUMMON`` — 플레이어가 이번 턴의 일반 소환권을
  **쓰기로 고른다.** 반드시 소환권을 소비한다.

그래서 :mod:`engine` 은 ``analysis`` 의 어휘를 가져오지 않는다.
``tests/engine/test_phase2_contracts.py`` 의 Contract E 가 이를 감시한다.

Phase 2-A 가 하지 않는 것
--------------------------
**적법성 판정과 실행.** ``NORMAL_SUMMON`` 을 만들 수 있다는 것과 그 소환이
가능하다는 것은 다른 이야기다. 전자만 여기 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.action_target import ActionTarget, ActionTargetKind
from engine.ids import EffectRef, InstanceId
from engine.vocabulary import Phase


class PlayerActionKind(str, Enum):
    """
    고르는 주체가 고를 수 있는 행위.

    **Destroy · Banish · Send · Discard · Release 는 여기 없다.** 그것들은
    효과 해결의 결과이지 누가 고르는 것이 아니다 (ADR-002). 넣는 순간 AI 가
    "카드 B 를 파괴한다" 를 직접 고르게 되고, 규칙 계산이 엔진에서 AI 로
    넘어간다.
    """

    NORMAL_SUMMON = "normal_summon"
    """이번 턴의 일반 소환권을 써서 앞면 공격 표시로 소환한다."""
    SET_MONSTER = "set_monster"
    """일반 소환권을 써서 뒷면 수비 표시로 세트한다."""
    SET_SPELL_TRAP = "set_spell_trap"
    ACTIVATE_CARD = "activate_card"
    """카드 자체를 발동한다 (마법 · 함정의 발동)."""
    ACTIVATE_EFFECT = "activate_effect"
    """카드가 가진 **특정 효과**를 발동한다. ``effect_ref`` 로 어느 효과인지 지목한다."""
    CHANGE_POSITION = "change_position"
    ATTACK = "attack"
    """공격 선언. 대상이 없으면 다이렉트 어택이 아니라 **구조 오류**다 —
    다이렉트 어택은 ``ActionTarget.player_target`` 으로 명시한다."""
    CHANGE_PHASE = "change_phase"
    END_PHASE = "end_phase"
    PASS = "pass"
    """우선권을 넘긴다. 아무것도 하지 않겠다는 **선택**이다."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: 종류별로 ``source`` 가 필요한가.
_NEEDS_SOURCE: frozenset[PlayerActionKind] = frozenset(
    {
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.ACTIVATE_CARD,
        PlayerActionKind.ACTIVATE_EFFECT,
        PlayerActionKind.CHANGE_POSITION,
        PlayerActionKind.ATTACK,
    }
)

#: 종류별로 ``source`` 가 있으면 **안 되는가**.
_FORBIDS_SOURCE: frozenset[PlayerActionKind] = frozenset(
    {
        PlayerActionKind.CHANGE_PHASE,
        PlayerActionKind.END_PHASE,
        PlayerActionKind.PASS,
    }
)

#: ``effect_ref`` 가 필요한 종류.
_NEEDS_EFFECT_REF: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.ACTIVATE_EFFECT}
)

#: ``effect_ref`` 를 가질 수 있는 종류 (필수는 아님).
_ALLOWS_EFFECT_REF: frozenset[PlayerActionKind] = _NEEDS_EFFECT_REF | frozenset(
    {PlayerActionKind.ACTIVATE_CARD}
)

#: ``phase`` 가 필요한 종류.
_NEEDS_PHASE: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.CHANGE_PHASE}
)

#: 대상을 **몇 개** 가져야 하는가. ``None`` 이면 제한 없음.
_TARGET_COUNT: dict[PlayerActionKind, int | None] = {
    PlayerActionKind.NORMAL_SUMMON: 0,
    PlayerActionKind.SET_MONSTER: 0,
    PlayerActionKind.SET_SPELL_TRAP: 0,
    PlayerActionKind.CHANGE_POSITION: 0,
    PlayerActionKind.ATTACK: 1,
    PlayerActionKind.CHANGE_PHASE: 0,
    PlayerActionKind.END_PHASE: 0,
    PlayerActionKind.PASS: 0,
    PlayerActionKind.ACTIVATE_CARD: None,
    PlayerActionKind.ACTIVATE_EFFECT: None,
}


class MalformedAction(ValueError):
    """
    Action 의 **모양**이 틀렸다.

    규칙 위반이 아니다. "이 소환이 가능한가" 는 아직 아무도 모르고
    (:class:`~engine.action_validation.ActionValidity.UNKNOWN`), 여기서 거부하는
    것은 "일반 소환인데 소환할 카드가 없다" 처럼 **표현 자체가 성립하지 않는**
    경우뿐이다.
    """


@dataclass(frozen=True, slots=True)
class PlayerAction:
    """
    하려는 행위 하나. **불변**이다 — 고친 Action 이 필요하면 새로 만든다.

    ``actor`` 는 **이 행위를 시도하는 플레이어**다. 카드의 ``owner`` /
    ``controller`` 와 다르다. 컨트롤을 빼앗긴 카드로 상대가 공격하는 상황은
    ``owner=0, controller=1, actor=1`` 로 표현된다 (ADR 문서 §22).
    """

    kind: PlayerActionKind
    actor: int
    source: InstanceId | None = None
    targets: tuple[ActionTarget, ...] = ()
    effect_ref: EffectRef | None = None
    phase: Phase | None = None

    def __post_init__(self) -> None:
        if self.actor not in (0, 1):
            raise MalformedAction(f"actor 는 0 또는 1 입니다: {self.actor}")
        if not isinstance(self.kind, PlayerActionKind):
            raise MalformedAction(f"알 수 없는 행위입니다: {self.kind!r}")
        if not isinstance(self.targets, tuple):
            raise MalformedAction(
                "targets 는 tuple 이어야 합니다 — Action 은 불변입니다."
            )

    # ------------------------------------------------------------------
    # 편의 생성자 — 종류마다 필요한 칸이 다르므로 이름으로 구분한다
    # ------------------------------------------------------------------
    @classmethod
    def normal_summon(cls, actor: int, source: InstanceId) -> "PlayerAction":
        return cls(kind=PlayerActionKind.NORMAL_SUMMON, actor=actor, source=source)

    @classmethod
    def set_monster(cls, actor: int, source: InstanceId) -> "PlayerAction":
        return cls(kind=PlayerActionKind.SET_MONSTER, actor=actor, source=source)

    @classmethod
    def set_spell_trap(cls, actor: int, source: InstanceId) -> "PlayerAction":
        return cls(kind=PlayerActionKind.SET_SPELL_TRAP, actor=actor, source=source)

    @classmethod
    def activate_card(
        cls,
        actor: int,
        source: InstanceId,
        *,
        targets: tuple[ActionTarget, ...] = (),
        effect_ref: EffectRef | None = None,
    ) -> "PlayerAction":
        return cls(
            kind=PlayerActionKind.ACTIVATE_CARD,
            actor=actor,
            source=source,
            targets=targets,
            effect_ref=effect_ref,
        )

    @classmethod
    def activate_effect(
        cls,
        actor: int,
        source: InstanceId,
        effect_ref: EffectRef,
        *,
        targets: tuple[ActionTarget, ...] = (),
    ) -> "PlayerAction":
        """
        카드가 가진 **특정 효과**를 발동한다.

        효과는 ``EffectRef(card_id, ordinal)`` 로 지목한다.
        ``EffectSpec.index`` 는 한 카드 안에서 중복되므로 쓰지 않는다
        (ADR-005, 실측 4,884장).
        """
        return cls(
            kind=PlayerActionKind.ACTIVATE_EFFECT,
            actor=actor,
            source=source,
            effect_ref=effect_ref,
            targets=targets,
        )

    @classmethod
    def change_position(cls, actor: int, source: InstanceId) -> "PlayerAction":
        return cls(kind=PlayerActionKind.CHANGE_POSITION, actor=actor, source=source)

    @classmethod
    def attack(
        cls, actor: int, source: InstanceId, target: ActionTarget
    ) -> "PlayerAction":
        """공격 선언. 다이렉트 어택은 ``ActionTarget.player_target(n)`` 이다."""
        return cls(
            kind=PlayerActionKind.ATTACK,
            actor=actor,
            source=source,
            targets=(target,),
        )

    @classmethod
    def attack_directly(cls, actor: int, source: InstanceId) -> "PlayerAction":
        """상대에게 직접 공격. ``attack`` 의 흔한 경우를 이름으로 드러낸다."""
        return cls.attack(
            actor=actor, source=source, target=ActionTarget.player_target(1 - actor)
        )

    @classmethod
    def change_phase(cls, actor: int, phase: Phase) -> "PlayerAction":
        return cls(kind=PlayerActionKind.CHANGE_PHASE, actor=actor, phase=phase)

    @classmethod
    def end_phase(cls, actor: int) -> "PlayerAction":
        return cls(kind=PlayerActionKind.END_PHASE, actor=actor)

    @classmethod
    def passing(cls, actor: int) -> "PlayerAction":
        return cls(kind=PlayerActionKind.PASS, actor=actor)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def opponent(self) -> int:
        return 1 - self.actor

    @property
    def target(self) -> ActionTarget | None:
        """대상이 정확히 하나일 때 그것. 아니면 ``None``."""
        return self.targets[0] if len(self.targets) == 1 else None

    def instance_targets(self) -> tuple[InstanceId, ...]:
        return tuple(
            t.instance_id
            for t in self.targets
            if t.kind is ActionTargetKind.INSTANCE and t.instance_id is not None
        )

    # ------------------------------------------------------------------
    # 직렬화 — 결정론적이어야 한다 (향후 EventJournal · replay)
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        """
        정수 · 문자열 · ``None`` 만으로 이루어진 정규 표현.

        파이썬 ``hash()`` · 객체 주소 · ``repr`` · 정렬되지 않은 집합이
        들어가지 않는다. ``targets`` 는 **순서를 유지한다** — 대상의 순서가
        의미를 갖는 효과가 있기 때문이다.
        """
        return (
            self.kind.value,
            self.actor,
            self.source.value if self.source is not None else None,
            tuple(t.canonical_state() for t in self.targets),
            (self.effect_ref.card_id, self.effect_ref.ordinal)
            if self.effect_ref is not None
            else None,
            self.phase.value if self.phase is not None else None,
        )

    def to_dict(self) -> dict:
        """JSON 으로 바로 나갈 수 있는 형태. 비어 있는 칸은 넣지 않는다."""
        data: dict = {"kind": self.kind.value, "actor": self.actor}
        if self.source is not None:
            data["source"] = self.source.value
        if self.targets:
            data["targets"] = [t.to_dict() for t in self.targets]
        if self.effect_ref is not None:
            data["effect_ref"] = {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            }
        if self.phase is not None:
            data["phase"] = self.phase.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerAction":
        source = data.get("source")
        ref = data.get("effect_ref")
        phase = data.get("phase")
        return cls(
            kind=PlayerActionKind(data["kind"]),
            actor=data["actor"],
            source=InstanceId(source) if source is not None else None,
            targets=tuple(
                ActionTarget.from_dict(t) for t in data.get("targets", ())
            ),
            effect_ref=EffectRef(ref["card_id"], ref["ordinal"])
            if ref is not None
            else None,
            phase=Phase(phase) if phase is not None else None,
        )

    def __str__(self) -> str:
        bits = [self.kind.value, f"P{self.actor}"]
        if self.source is not None:
            bits.append(str(self.source))
        if self.effect_ref is not None:
            bits.append(str(self.effect_ref))
        if self.phase is not None:
            bits.append(self.phase.value)
        if self.targets:
            bits.append("->" + ",".join(str(t) for t in self.targets))
        return " ".join(bits)
