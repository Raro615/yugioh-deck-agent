"""
통상 마법의 **발동 배치** — 패에서 필드로, 해결 뒤 묘지로 (Phase 3-E-3).

    PlayerAction(ACTIVATE_EFFECT)
          ↓  NormalSpellPlacement.place()      패 → 마법&함정 존 (앞면)
    SpellPlaced
          ↓  EffectActivator.activate()        체인 링크
          ↓  ChainResolver.resolve_top()       효과 해결
          ↓  NormalSpellPlacement.retire()     마법&함정 존 → 묘지
    SpellRetired

왜 이 모듈이 필요한가
---------------------
공식 규칙이 발동을 **배치**로 정의한다.

    RULE-SPELLTRAP-002 — "To use a Normal Spell Card, announce its activation
    to your opponent, **placing it face-up on the field.** If the activation
    succeeds, then you resolve the effect written on the card. **After
    resolving the effect, send the card to the Graveyard.**"

Phase 3-E-3 전까지 이 배치를 하는 자리가 **없었다.** :mod:`engine.activation`
은 비용과 체인 링크만 만들고 카드를 움직이지 않으며, :class:`
~engine.chain.ChainResolver` 도 효과만 해결한다. 그래서 손으로 발동시키면
카드가 **패에 그대로 남았다** — 규칙 위반이고, 그보다 먼저 **끝나지 않는
듀얼**이 된다: 욕망의 항아리가 패에 남아 있으면 덱이 마를 때까지 같은 턴에
계속 발동된다.

효과가 아니다
-------------
이 이동은 **규칙**이지 효과가 아니다. 그래서 ``OperationKind.SEND_TO_GRAVE``
도 ``CardOperation.send_to_grave`` 도 쓰지 않는다 — 그것은 효과의 어휘이고,
거기에 얹으면 "효과로 묘지에 갔다" 가 되어 "효과로 묘지로 보내졌을 때" 를
조건으로 하는 카드가 잘못 반응한다. :class:`~engine.set_card.CardSet` 이
``reason_names`` 를 비워 둔 것과 같은 자리다.

여기서 하지 않는 것
-------------------
- **적법성을 판정하지 않는다.** 그것은 :class:`
  ~engine.action_validation.ActionValidator` 와 :class:`
  ~engine.activation.EffectActivator` 의 일이고, 이 모듈은 허가가 난 뒤에만
  불린다.
- 지속 마법 · 장착 마법 · 필드 마법 · 함정을 다루지 않는다. 그 셋은 발동 뒤
  **필드에 남고** (RULE-SPELLTRAP-004 · 005 · 006), 함정은 세트가 앞선다
  (RULE-SPELLTRAP-009). 모양이 다르므로 같은 코드로 덮지 않는다.
- 되돌리기 계층을 만들지 않는다. :meth:`NormalSpellPlacement.restore` 는
  **자기가 방금 한 이동 하나**의 역이고 그 이상이 아니다 (ADR-008 이 일반
  rollback 을 미뤄 두었다).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.effect.delta import CardMovement
from engine.effect.operation import OperationKind
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Position, Zone


class SpellActivationError(RuntimeError):
    """발동 배치를 진행할 수 없다. **적법성 판정이 아니다.**"""


#: 발동하는 마법이 출발하는 자리. 이번 범위는 패에서의 발동 하나다.
ACTIVATE_FROM_ZONE: Zone = Zone.HAND

#: 발동한 마법이 놓이는 자리 (RULE-SPELLTRAP-002: "on the field").
ACTIVATION_ZONE: Zone = Zone.SZONE

#: 발동한 마법의 표시 형식 (RULE-SPELLTRAP-002: "face-up").
ACTIVATION_POSITION: Position = Position.FACEUP

#: 해결 뒤 가는 자리 (RULE-SPELLTRAP-002: "send the card to the Graveyard").
AFTER_RESOLUTION_ZONE: Zone = Zone.GRAVE


@dataclass(frozen=True, slots=True)
class _SpellMovement(CardMovement):
    """
    발동 배치로 움직인 카드 하나. **이유를 주장하지 않는다.**

    :attr:`operation` 이 ``MOVE`` 인 이유와 :attr:`reason_names` 가 비어 있는
    이유가 같다 — 이 이동은 규칙이고 효과가 아니므로, 효과의 어휘로 적으면
    거짓이 된다. 무슨 일인지는 **이 델타의 타입**이 말한다.
    """

    card: InstanceId
    player: int
    """컨트롤러. 발동으로 컨트롤러가 바뀌지 않는다."""
    owner: int
    """카드의 주인 (ADR: Owner ≠ Controller)."""
    source_player: int
    """
    출발 자리의 주인.

    이름이 ``from_player`` 가 아닌 이유: :class:`CardMovement` 가 그 이름을
    프로퍼티로 쓰고 있어서 같은 이름의 필드를 선언하면 dataclass 가 프로퍼티
    객체를 기본값으로 읽는다 (``CardSet`` · ``BattleDestruction`` 과 같다).
    """
    source_zone: Zone
    destination_zone: Zone
    position: "Position | None" = None

    @property
    def instance(self) -> InstanceId:
        return self.card

    @property
    def operation(self) -> OperationKind:
        return OperationKind.MOVE

    @property
    def from_zone(self) -> Zone:
        return self.source_zone

    @property
    def from_player(self) -> int:
        return self.source_player

    @property
    def to_player(self) -> int:
        return self.player

    @property
    def to_zone(self) -> Zone:
        return self.destination_zone

    @property
    def reason_names(self) -> tuple[str, ...]:
        """**비어 있는 것이 사실이다.** 발동 배치는 효과가 아니다."""
        return ()

    def canonical_state(self) -> tuple:
        return (
            self.kind,
            self.card.value,
            self.player,
            self.owner,
            self.source_player,
            self.source_zone.value,
            self.destination_zone.value,
            self.position.value if self.position is not None else None,
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "card": self.card.value,
            "player": self.player,
            "owner": self.owner,
            "from_player": self.source_player,
            "from_zone": self.source_zone.value,
            "to_zone": self.destination_zone.value,
            "position": self.position.value if self.position is not None else None,
            "by_effect": False,
        }


@dataclass(frozen=True, slots=True)
class SpellPlaced(_SpellMovement):
    """
    발동을 선언하며 마법을 **앞면으로 필드에 놓았다** (RULE-SPELLTRAP-002).

    아직 효과는 해결되지 않았다. 놓는 것과 해결하는 것은 다른 사건이고, 그
    사이가 체인이 존재하는 이유다.
    """

    @property
    def kind(self) -> str:
        return "spell_placed"

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 가 {self.card} 를 발동 선언하며 "
            f"{self.destination_zone.value} 에 앞면으로 놓았다 (해결 전)"
        )


@dataclass(frozen=True, slots=True)
class SpellRetired(_SpellMovement):
    """
    해결을 마친 통상 마법을 **묘지로 보냈다** (RULE-SPELLTRAP-002).

    **효과로 보낸 것이 아니다.** 규칙이 보낸 것이므로 ``reason_names`` 가
    비어 있다.
    """

    @property
    def kind(self) -> str:
        return "spell_retired"

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 의 {self.card} 가 해결을 마치고 "
            f"{self.destination_zone.value} 로 갔다 (효과가 아니라 규칙)"
        )


@dataclass(frozen=True, slots=True)
class SpellRestored(_SpellMovement):
    """
    놓았던 마법을 **패로 되돌렸다** — 발동이 성립하지 않았을 때.

    일반 rollback 계층이 아니다. :class:`SpellPlaced` 가 한 이동 **하나**의
    역이고, 그래서 되돌릴 자리와 카드가 정확히 하나로 정해진다.
    """

    @property
    def kind(self) -> str:
        return "spell_restored"

    def describe_ko(self) -> str:
        return (
            f"P{self.player} 의 {self.card} 가 발동이 성립하지 않아 "
            f"{self.destination_zone.value} 로 되돌아갔다"
        )


class NormalSpellPlacement:
    """
    통상 마법 한 장의 **자리**를 옮긴다. **상태를 갖지 않는다.**

        placement = NormalSpellPlacement()
        placed = placement.place(state, card, player)      # 패 → 필드 (앞면)
        ...                                                 # 발동 · 해결
        retired = placement.retire(state, placed)           # 필드 → 묘지

    배치는 전부 :meth:`~engine.state.game_state.GameState.move` 하나로
    한다 — 여기서 새 이동 경로를 만들지 않는다.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    def place(
        self, state: GameState, card: InstanceId, player: int
    ) -> SpellPlaced:
        """
        발동을 선언하며 앞면으로 놓는다 (RULE-SPELLTRAP-002).

        **적법성을 다시 보지 않는다.** 자리가 비었는지 · 패에 있는지는 허가를
        낸 쪽이 이미 확인했고, 여기서 다시 보면 규칙이 두 곳에 적힌다.
        """
        instance = state.find_instance(card)
        if instance is None:
            raise SpellActivationError(f"{card} 를 찾을 수 없습니다.")
        if instance.zone is not ACTIVATE_FROM_ZONE:
            raise SpellActivationError(
                f"{card} 는 {instance.zone.value} 에 있습니다 — 이번 범위의 "
                f"발동은 {ACTIVATE_FROM_ZONE.value} 에서만 합니다."
            )
        owner, source_zone = instance.owner, instance.zone
        source_player = instance.controller
        state.move(
            instance,
            ACTIVATION_ZONE,
            to_player=player,
            position=ACTIVATION_POSITION,
        )
        return SpellPlaced(
            card=card,
            player=player,
            owner=owner,
            source_player=source_player,
            source_zone=source_zone,
            destination_zone=ACTIVATION_ZONE,
            position=ACTIVATION_POSITION,
        )

    # ------------------------------------------------------------------
    def retire(self, state: GameState, placed: SpellPlaced) -> SpellRetired:
        """해결을 마친 마법을 묘지로 보낸다 (RULE-SPELLTRAP-002)."""
        return self._move_back(
            state, placed, AFTER_RESOLUTION_ZONE, SpellRetired, position=None
        )

    def restore(self, state: GameState, placed: SpellPlaced) -> SpellRestored:
        """
        놓았던 마법을 패로 되돌린다 — 발동이 성립하지 않았을 때.

        :meth:`place` 의 역 **하나**다. 표시 형식은 패의 것으로 돌아간다.
        """
        return self._move_back(
            state, placed, placed.source_zone, SpellRestored, position=None
        )

    # ------------------------------------------------------------------
    def _move_back(self, state, placed, zone, delta_type, *, position):
        instance = state.find_instance(placed.card)
        if instance is None:
            raise SpellActivationError(f"{placed.card} 를 찾을 수 없습니다.")
        state.move(
            instance, zone, to_player=placed.source_player, position=position
        )
        return delta_type(
            card=placed.card,
            player=placed.source_player,
            owner=placed.owner,
            source_player=placed.player,
            source_zone=placed.destination_zone,
            destination_zone=zone,
            position=position,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<NormalSpellPlacement>"


# ======================================================================
# 이 듀얼이 발동할 수 있는 것 — 등록은 손으로 한다 (ADR-006)
# ======================================================================
#
# 이 셋이 :mod:`engine.duel` 이 아니라 여기 있는 이유: "어떤 효과를 발동할 수
# 있는가" 는 **발동 계층의 지식**이고, 듀얼 루프는 그것을 부르기만 해야 한다.
# ``engine/duel.py`` 가 ``engine.effect`` 를 직접 읽으면 그 경계가 사라지고,
# ``test_e_the_duel_makes_no_rules_of_its_own`` 이 지키는 불변식이 깨진다.


def duel_activator():
    """
    듀얼이 쓰는 **발동기**. ``EFFECT_LIBRARY`` 의 구현 목록을 그대로 쓴다.

    ``duel_executor`` 와 같은 모양이고 이유도 같다 — 등록은 **손으로** 한다
    (ADR-006). 목록에 없는 효과는 발동되지 않고, 그것이 기본 상태다.

    ``engine.effect.library`` 를 **함수 안에서** 읽는다. 모듈 위에서 읽으면
    효과 계층이 이 모듈을 쓸 때 import 고리가 생긴다 (``duel_executor`` 가
    ``engine.normal_summon`` 을 그렇게 읽는 것과 같은 자리다).
    """
    from engine.activation import EffectActivator
    from engine.effect.library import definition_registry, implementation_registry

    return EffectActivator(definition_registry(), implementation_registry())


def duel_resolver():
    """듀얼이 쓰는 **해결기**. 기존 ``ChainResolver`` 를 그대로 쓴다."""
    from engine.chain import ChainResolver
    from engine.effect.library import build_executor, definition_registry

    return ChainResolver(build_executor(), definition_registry())


def activatable_effects(card_id: int):
    """
    그 카드에서 **실행 구현이 등록된** 효과들 (``EffectRef``).

    ``EFFECT_LIBRARY`` 에 있다는 것만으로는 후보가 되지 않는다 —
    ``executable`` 인 것만 돌려준다 (ADR-006). 발동 조건 · 대상 · 비용은
    :class:`~engine.activation.EffectActivator` 가 따로 본다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    return tuple(
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if entry.executable and entry.definition.effect_ref.card_id == card_id
    )


__all__ = [
    "duel_activator",
    "duel_resolver",
    "activatable_effects",
    "SpellActivationError",
    "SpellPlaced",
    "SpellRetired",
    "SpellRestored",
    "NormalSpellPlacement",
    "ACTIVATE_FROM_ZONE",
    "ACTIVATION_ZONE",
    "ACTIVATION_POSITION",
    "AFTER_RESOLUTION_ZONE",
]
