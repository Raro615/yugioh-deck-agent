"""
GameStateView — AI 에게 넘기는 **읽기 전용 스냅숏**.

AI 는 ``GameState`` 를 직접 받지 않는다. 받으면 ``move()`` · ``change_life()``
· ``draw()`` 가 그대로 노출되고, 실수 한 줄로 ADR-007 의 경계가 사라진다.

스냅숏인 이유
-------------
살아 있는 읽기 전용 프록시 대신 **만드는 순간 값을 복사한다.**

- 안전이 구조로 보장된다. 프록시는 감싸는 것을 하나라도 빠뜨리면 새지만,
  스냅숏은 새어 나갈 원본 참조 자체가 없다.
- AI 가 보는 관측이 고정된다. MCTS 가 한 노드를 평가하는 동안 원본이 바뀌어도
  관측이 흔들리지 않는다.
- 전부 frozen dataclass 와 tuple 이라 ``view.hand`` 에 ``append`` 할 수 없다.

숨겨진 정보
-----------
**"보이지만 잠겨 있다" 가 아니라 "값이 아예 없다" 로 숨긴다.** 숨긴 값을
들고 있으면서 플래그로 가리면, 그 플래그를 보지 않는 코드 한 줄이 곧 유출이다.

===================  ==========================================================
존                    보는 사람에게 무엇이 보이는가
===================  ==========================================================
덱 (``HIDDEN``)      **장수만.** 카드 목록이 비어 있다 (자기 덱도 마찬가지)
패 · 엑스트라         자기 것이면 전부. 상대 것이면 **장수만**
공개 존               앞면 카드는 전부. 뒷면 카드는 **컨트롤러에게만** 정체가 보임
===================  ==========================================================

뒷면 카드는 정체(``card_id``)만 가리고 ``instance_id`` 는 남긴다. 상대의 세트
카드를 "저 자리의 그것" 으로 지목해서 공격하거나 파괴할 수 있어야 하기
때문이다. 반대로 상대의 **패**는 ``instance_id`` 도 주지 않는다 — 주면 "3턴에
드로우한 그 카드가 아직 손에 있다" 는 정보가 새고, 그것은 실제 대전에서
알 수 없는 사실이다.

카드 정의
---------
조건이 "레벨 4 이상인가" 를 묻으려면 카드 정의가 필요하다. 그렇다고
``ConditionEvaluator`` 가 ``CardRepository`` 를 들면 관측 경계가 무너진다 —
저장소는 **전체 카드**를 알고 있으므로, 그것을 쥔 코드는 상대의 뒷면 카드도
조회할 수 있게 된다.

그래서 정의도 관측을 통해 온다. :class:`CardDefinitionView` 가 그 스냅숏이고,
**정체가 공개된 카드에만 붙는다.** 가려진 카드는 ``card_id`` 자체가 없으므로
정의를 붙일 대상이 없다.

Phase 2-A 가 내보내지 않는 것
------------------------------
``UseRegistry`` · ``EffectRegistry`` · raw Lua · provenance · 파서 상태.
AI 가 알 필요가 없고, 엔진 내부 구현을 관측에 묶으면 나중에 바꿀 수 없다.
"이 효과를 이번 턴에 썼는가" 는 정당한 공개 정보지만, 그것을 **질의로**
노출하는 것은 Condition 계층(Phase 2-B)이 모양을 정한 뒤에 한다.

Phase 2-I 가 하나를 열었다: :attr:`GameStateView.normal_summons_used`.
카드 효과의 사용 횟수가 아니라 **규칙이 정한 소환권**이고, 소환은 공개된
자리에서 일어나므로 양쪽 다 보는 사실이다. 효과 쪽 ``UseRegistry`` 는
여전히 내보내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.ids import InstanceId
from engine.state.rule_usage import RuleActionKind
from engine.vocabulary import (
    PLAYER_ZONES,
    Phase,
    Position,
    Zone,
    ZoneKind,
    ZoneVisibility,
    zone_capacity,
    zone_kind,
    zone_visibility,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from core.card_model import Card
    from engine.state.card_instance import CardInstance
    from engine.state.game_state import GameState
    from engine.state.zones import ZoneContainer


#: ATK/DEF 에 **수치가 없다**. 링크 몬스터의 수비력이 이 값이다.
#: ``core.constants.STAT_NONE`` 과 같은 값이어야 한다
#: (``tests/engine/test_card_definition_view.py`` 가 확인한다).
#: 런타임에 ``core`` 를 가져오지 않으려고 여기에 다시 적는다 — 관측 계층은
#: 상태 계층 위에만 서 있어야 한다.
STAT_NONE = -1

#: ATK/DEF 가 **물음표(?)** 다. 실측 90장이 ``?`` 공격력을 갖는다.
#: 수치가 없는 것(:data:`STAT_NONE`)과 **다르다** — 값이 정해지지 않았을
#: 뿐이므로 "2000 이상인가" 는 참도 거짓도 아니다.
#: 근거: ``sources/official_db.py`` ("``atk``/``def`` 가 -2 이면 물음표(?) 수치").
STAT_QUESTION = -2


@dataclass(frozen=True, slots=True)
class CardDefinitionView:
    """
    카드 **정의**의 읽기 전용 스냅숏.

    ``core.card_model.Card`` 는 가변 dataclass 이고 저장소가 같은 객체를 계속
    돌려준다. 그것을 관측에 그대로 실으면 조건 코드가 전역 카드 정의를
    고칠 수 있게 되므로, 필요한 값만 뽑아 얼려서 싣는다.

    **없는 값을 지어내지 않는다.** 여기 있는 것은 전부 ``Card`` 에 실제로
    있는 값이거나 ``Card`` 가 이미 계산해 주는 파생값이다.

    수치 없음과 물음표
    ------------------
    ``atk`` / ``defense`` 에는 두 가지 특별한 값이 들어올 수 있다.

    - :data:`STAT_NONE` (-1) — **수치 자체가 없다.** 링크 몬스터의 수비력.
    - :data:`STAT_QUESTION` (-2) — **물음표.** 값이 정해져 있지 않다.

    둘을 합치면 "?" 공격력 몬스터가 공격력 0 으로 둔갑한다. 그래서
    :attr:`atk_is_question` 과 :attr:`has_atk` 를 따로 둔다.
    """

    card_id: int
    name: str

    # --- 원본 비트마스크 ---------------------------------------------
    type_mask: int
    attribute_mask: int
    race_mask: int
    link_marker_mask: int

    # --- 수치 ---------------------------------------------------------
    level: int
    """``cards.cdb`` 의 ``level`` 칸 그대로. 엑시즈면 랭크, 링크면 링크 수다."""
    atk: int
    defense: int
    pendulum_scale_left: int | None
    pendulum_scale_right: int | None

    # --- Card 가 이미 계산해 주는 파생값 ------------------------------
    is_monster: bool
    is_spell: bool
    is_trap: bool
    is_xyz: bool
    is_link: bool
    is_pendulum: bool
    is_extra_deck: bool
    monster_level: int | None
    """엑시즈 · 링크 · 비몬스터는 **레벨이 없다** (``None``)."""
    rank: int | None
    link_rating: int | None
    attribute_name: str | None
    """``EARTH`` · ``DARK`` 등. 몬스터가 아니면 ``None``."""
    race_name: str | None
    type_names: tuple[str, ...]
    setcodes: tuple[int, ...]
    effect_count: int = 0
    """
    ``EffectRef`` 로 **지목할 수 있는** 효과의 개수.

    스크립트 내용을 내보내지 않고 개수만 싣는다. ``EffectRef(card_id, n)``
    의 ``n`` 이 범위를 벗어나는지 판정하는 데 쓴다.

    **0 은 "효과가 없다" 를 뜻하지 않는다.** 통상 몬스터도 0 이지만,
    공유 라이브러리 팩토리(``Fusion.CreateSummonEff`` 등)로 효과를 만드는
    카드 195장도 0 이다 (ADR-006). 둘을 구분할 수 없으므로, 0 일 때는
    "이 효과가 존재하는가" 를 **모른다**고 답해야 한다.
    """

    # ------------------------------------------------------------------
    # 수치의 세 상태
    # ------------------------------------------------------------------
    @property
    def has_atk(self) -> bool:
        """공격력이 **수치로** 정해져 있는가. ``?`` 와 '없음' 은 거짓이다."""
        return self.atk >= 0

    @property
    def has_defense(self) -> bool:
        return self.defense >= 0

    @property
    def atk_is_question(self) -> bool:
        """공격력이 ``?`` 인가. 수치가 없는 것과 다르다."""
        return self.atk == STAT_QUESTION

    @property
    def effects_are_addressable(self) -> bool:
        """
        이 카드의 효과 목록을 믿을 수 있는가.

        거짓이면 "몇 번째 효과" 라는 질문에 답할 수 없다 — 효과가 없어서인지
        파서가 못 읽어서인지 구분되지 않기 때문이다.
        """
        return self.effect_count > 0

    @property
    def defense_is_question(self) -> bool:
        return self.defense == STAT_QUESTION

    # ------------------------------------------------------------------
    # 만들기
    # ------------------------------------------------------------------
    @classmethod
    def of(cls, card: "Card") -> "CardDefinitionView":
        """``Card`` 에서 값을 **복사한다.** 원본을 참조로 들고 있지 않는다."""
        return cls(
            card_id=card.id,
            name=card.name,
            type_mask=card.type_mask,
            attribute_mask=card.attribute_mask,
            race_mask=card.race_mask,
            link_marker_mask=card.link_marker_mask,
            level=card.level,
            atk=card.atk,
            defense=card.defense,
            pendulum_scale_left=card.pendulum_scale_left,
            pendulum_scale_right=card.pendulum_scale_right,
            is_monster=card.is_monster,
            is_spell=card.is_spell,
            is_trap=card.is_trap,
            is_xyz=card.is_xyz,
            is_link=card.is_link,
            is_pendulum=card.is_pendulum,
            is_extra_deck=card.is_extra_deck,
            monster_level=card.monster_level,
            rank=card.rank,
            link_rating=card.link_rating,
            attribute_name=card.attribute_name,
            race_name=card.race_name,
            type_names=tuple(card.type_names),
            setcodes=tuple(card.setcodes),
            effect_count=len(card.script.effects) if card.script is not None else 0,
        )

    def canonical_state(self) -> tuple:
        return (
            self.card_id,
            self.name,
            self.type_mask,
            self.attribute_mask,
            self.race_mask,
            self.link_marker_mask,
            self.level,
            self.atk,
            self.defense,
            self.pendulum_scale_left,
            self.pendulum_scale_right,
            self.monster_level,
            self.rank,
            self.link_rating,
            self.attribute_name,
            self.race_name,
            self.type_names,
            self.setcodes,
            self.effect_count,
        )

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "type_mask": self.type_mask,
            "attribute_mask": self.attribute_mask,
            "race_mask": self.race_mask,
            "link_marker_mask": self.link_marker_mask,
            "level": self.level,
            "atk": self.atk,
            "defense": self.defense,
            "pendulum_scale_left": self.pendulum_scale_left,
            "pendulum_scale_right": self.pendulum_scale_right,
            "is_monster": self.is_monster,
            "is_spell": self.is_spell,
            "is_trap": self.is_trap,
            "is_xyz": self.is_xyz,
            "is_link": self.is_link,
            "is_pendulum": self.is_pendulum,
            "is_extra_deck": self.is_extra_deck,
            "monster_level": self.monster_level,
            "rank": self.rank,
            "link_rating": self.link_rating,
            "attribute_name": self.attribute_name,
            "race_name": self.race_name,
            "type_names": list(self.type_names),
            "setcodes": list(self.setcodes),
            "effect_count": self.effect_count,
        }

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.name}({self.card_id})"


@dataclass(frozen=True, slots=True)
class CardView:
    """
    보는 사람에게 **보이는 만큼**의 카드 한 장.

    ``card_id`` 가 ``None`` 이면 정체를 모른다는 뜻이다. 숨긴 값을 들고
    있다가 가리는 것이 아니라, 처음부터 넣지 않는다.
    """

    instance_id: InstanceId | None
    """지목할 수 있으면 번호, 아니면 ``None`` (상대의 패 등)."""
    card_id: int | None
    """정체를 알면 카드 ID, 모르면 ``None``."""
    zone: Zone
    sequence: int
    """칸 방식 존에서는 **칸 번호**, 순서 존에서는 위치."""
    controller: int
    face_up: bool
    position: Position | None = None
    owner: int | None = None
    """정체를 모르면 소유자도 모른다 (패 · 덱)."""
    counters: tuple[tuple[str, int], ...] = ()
    name: str | None = None
    """표시용 이름. 정체를 모르면 ``None``."""
    definition: CardDefinitionView | None = None
    """
    카드 정의 스냅숏. **정체가 공개된 카드에만 붙는다.**

    ``None`` 인 경우가 둘이고, 조건 계층은 둘 다 ``UNKNOWN`` 으로 다루되
    이유는 구분한다.

    1. 카드가 가려져 있다 (``card_id`` 도 ``None``).
    2. 정체는 아는데 카드 저장소가 없어 정의를 조회하지 못했다.
    """

    @property
    def is_identified(self) -> bool:
        """정체를 아는가. ``False`` 면 ``card_id`` 를 기대하지 말 것."""
        return self.card_id is not None

    @property
    def has_definition(self) -> bool:
        """카드 정의를 읽을 수 있는가."""
        return self.definition is not None

    @property
    def is_targetable(self) -> bool:
        """이 카드를 Action 의 대상으로 지목할 수 있는가 (구조적으로)."""
        return self.instance_id is not None

    # --- 만들기 -------------------------------------------------------
    @classmethod
    def revealed(cls, card: "CardInstance") -> "CardView":
        """
        정체까지 보이는 카드. 카드 정의 스냅숏도 함께 싣는다.

        저장소가 연결되어 있지 않으면 ``definition`` 이 ``None`` 이다.
        지어내지 않고 비워 둔다.
        """
        return cls(
            instance_id=card.instance_id,
            card_id=card.card_id,
            zone=card.zone,
            sequence=card.sequence,
            controller=card.controller,
            face_up=card.is_faceup,
            position=card.position,
            owner=card.owner,
            counters=tuple(sorted(card.counters.items())),
            name=card.name,
            definition=_definition_of(card),
        )

    @classmethod
    def concealed(cls, card: "CardInstance") -> "CardView":
        """
        자리와 표시 형식은 보이지만 **정체는 모르는** 카드.

        상대 필드의 뒷면 카드가 이 모양이다. 지목은 할 수 있어야 하므로
        ``instance_id`` 는 남긴다.
        """
        # definition 을 **넘기지 않는다.** 가려진 카드에 정의를 실으면
        # card_id 를 숨기는 의미가 없어진다 — 레벨·속성·공격력만 보고도
        # 어느 카드인지 거의 특정할 수 있기 때문이다.
        return cls(
            instance_id=card.instance_id,
            card_id=None,
            zone=card.zone,
            sequence=card.sequence,
            controller=card.controller,
            face_up=False,
            position=card.position,
            owner=None,
            counters=tuple(sorted(card.counters.items())),
            name=None,
        )

    def canonical_state(self) -> tuple:
        return (
            self.instance_id.value if self.instance_id is not None else None,
            self.card_id,
            self.zone.value,
            self.sequence,
            self.controller,
            self.face_up,
            self.position.value if self.position is not None else None,
            self.owner,
            self.counters,
            self.definition.canonical_state() if self.definition is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "zone": self.zone.value,
            "sequence": self.sequence,
            "controller": self.controller,
            "face_up": self.face_up,
        }
        if self.instance_id is not None:
            data["instance_id"] = self.instance_id.value
        if self.card_id is not None:
            data["card_id"] = self.card_id
        if self.position is not None:
            data["position"] = self.position.value
        if self.owner is not None:
            data["owner"] = self.owner
        if self.counters:
            data["counters"] = [list(c) for c in self.counters]
        if self.definition is not None:
            data["definition"] = self.definition.to_dict()
        return data

    def __str__(self) -> str:
        who = self.name or ("???" if not self.is_identified else str(self.card_id))
        return f"{who}({self.zone.value}[{self.sequence}])"


@dataclass(frozen=True, slots=True)
class ZoneView:
    """
    존 하나의 스냅숏.

    ``size`` 는 **언제나 정확하다** — 장수는 숨겨진 존에서도 공개다.
    ``cards`` 는 보이는 만큼만 담는다. 숨겨진 존이면 비어 있고, 그때
    :attr:`concealed` 가 참이다 — "빈 덱" 과 "안 보이는 덱" 을 구분하기
    위해서다.
    """

    zone: Zone
    owner: int
    visibility: ZoneVisibility
    kind: ZoneKind
    capacity: int | None
    size: int
    """실제 장수. 숨겨져 있어도 정확하다."""
    cards: tuple[CardView | None, ...] = ()
    """
    칸 방식 존이면 길이가 칸 수이고 빈 칸이 ``None`` 이다.
    순서 존이면 길이가 ``size`` 다. 내용이 숨겨져 있으면 비어 있다.
    """
    concealed: bool = False
    """내용이 통째로 가려졌는가. 참이면 ``cards`` 가 비어 있다."""

    @property
    def is_empty(self) -> bool:
        return self.size == 0

    def occupied(self) -> tuple[CardView, ...]:
        """빈 칸을 걷어낸 카드들."""
        return tuple(card for card in self.cards if card is not None)

    def free_slots(self) -> tuple[int, ...]:
        """빈 칸 번호. 순서 존이면 빈 튜플."""
        if self.kind is not ZoneKind.SLOTTED:
            return ()
        return tuple(i for i, card in enumerate(self.cards) if card is None)

    def canonical_state(self) -> tuple:
        return (
            self.zone.value,
            self.owner,
            self.visibility.value,
            self.kind.value,
            self.capacity,
            self.size,
            self.concealed,
            tuple(None if c is None else c.canonical_state() for c in self.cards),
        )

    def to_dict(self) -> dict:
        return {
            "zone": self.zone.value,
            "owner": self.owner,
            "visibility": self.visibility.value,
            "kind": self.kind.value,
            "capacity": self.capacity,
            "size": self.size,
            "concealed": self.concealed,
            "cards": [None if c is None else c.to_dict() for c in self.cards],
        }

    def __len__(self) -> int:
        return self.size

    def __str__(self) -> str:
        return f"<{self.zone.value} p{self.owner} n={self.size}>"


@dataclass(frozen=True, slots=True)
class PlayerView:
    """플레이어 한 명의 스냅숏. 보는 사람에 따라 내용이 달라진다."""

    player_id: int
    life_points: int
    zones: tuple[ZoneView, ...]

    def zone(self, zone: Zone) -> ZoneView:
        for view in self.zones:
            if view.zone is zone:
                return view
        raise KeyError(f"플레이어 {self.player_id} 에게 {zone.value} 존이 없습니다.")

    # 자주 쓰는 존은 이름으로도 꺼낸다.
    @property
    def deck(self) -> ZoneView:
        return self.zone(Zone.DECK)

    @property
    def hand(self) -> ZoneView:
        return self.zone(Zone.HAND)

    @property
    def extra(self) -> ZoneView:
        return self.zone(Zone.EXTRA)

    @property
    def grave(self) -> ZoneView:
        return self.zone(Zone.GRAVE)

    @property
    def removed(self) -> ZoneView:
        return self.zone(Zone.REMOVED)

    @property
    def monster_zone(self) -> ZoneView:
        return self.zone(Zone.MZONE)

    @property
    def extra_monster_zone(self) -> ZoneView:
        """엑스트라 몬스터 존. 메인 몬스터 존과 **다른 존**이다 (칸 1개)."""
        return self.zone(Zone.EMZONE)

    @property
    def spell_zone(self) -> ZoneView:
        return self.zone(Zone.SZONE)

    @property
    def field_zone(self) -> ZoneView:
        return self.zone(Zone.FZONE)

    @property
    def pendulum_zone(self) -> ZoneView:
        return self.zone(Zone.PZONE)

    def canonical_state(self) -> tuple:
        return (
            self.player_id,
            self.life_points,
            tuple(z.canonical_state() for z in self.zones),
        )

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "life_points": self.life_points,
            "zones": [z.to_dict() for z in self.zones],
        }


@dataclass(frozen=True, slots=True)
class GameStateView:
    """
    한 플레이어가 보는 판. :meth:`from_state` 로 만든다.

    만들어진 뒤에는 원본 ``GameState`` 와 아무 객체도 공유하지 않는다.
    원본이 바뀌어도 이 스냅숏은 그대로다.
    """

    viewer: int
    """이 관측의 주인. ``me`` 가 가리키는 플레이어다."""
    turn_number: int
    turn_player: int
    phase: Phase
    step: int
    players: tuple[PlayerView, PlayerView]
    winner: int | None = None
    result_reason: str = ""
    normal_summons_used: tuple[int, int] = (0, 0)
    """
    **이번 턴에** 각 플레이어가 일반 소환권을 쓴 횟수.

    가릴 것이 없는 정보다 — 소환은 공개된 자리에서 일어나고, 상대가 이번
    턴에 소환을 했는지는 양쪽 다 본다. 지난 턴의 기록은 싣지 않는다.
    """

    # ------------------------------------------------------------------
    # 만들기
    # ------------------------------------------------------------------
    @classmethod
    def from_state(cls, state: "GameState", viewer: int) -> "GameStateView":
        """
        ``viewer`` 가 보는 만큼만 담은 스냅숏을 만든다.

        **``state`` 를 바꾸지 않는다.** 읽기만 한다.
        """
        if viewer not in (0, 1):
            raise ValueError(f"viewer 는 0 또는 1 입니다: {viewer}")
        return cls(
            viewer=viewer,
            turn_number=state.turn.turn_number,
            turn_player=state.turn.turn_player,
            phase=state.turn.phase,
            step=state.turn.step,
            players=(
                _player_view(state, 0, viewer),
                _player_view(state, 1, viewer),
            ),
            winner=state.result.winner if state.result is not None else None,
            result_reason=state.result.reason if state.result is not None else "",
            normal_summons_used=(
                state.rule_uses.count(
                    state.turn.turn_number, 0, RuleActionKind.NORMAL_SUMMON
                ),
                state.rule_uses.count(
                    state.turn.turn_number, 1, RuleActionKind.NORMAL_SUMMON
                ),
            ),
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def me(self) -> PlayerView:
        return self.players[self.viewer]

    @property
    def opponent(self) -> PlayerView:
        return self.players[1 - self.viewer]

    @property
    def opponent_id(self) -> int:
        return 1 - self.viewer

    def player(self, player_id: int) -> PlayerView:
        return self.players[player_id]

    @property
    def is_my_turn(self) -> bool:
        return self.turn_player == self.viewer

    @property
    def is_over(self) -> bool:
        return self.winner is not None or bool(self.result_reason)

    def find(self, instance_id: InstanceId) -> CardView | None:
        """보이는 카드 중에서 찾는다. 안 보이면 ``None``."""
        for player in self.players:
            for zone in player.zones:
                for card in zone.cards:
                    if card is not None and card.instance_id == instance_id:
                        return card
        return None

    def visible_instances(self) -> tuple[InstanceId, ...]:
        """지목할 수 있는 카드 전부. Action 대상 후보의 상한이다."""
        found: list[InstanceId] = []
        for player in self.players:
            for zone in player.zones:
                for card in zone.cards:
                    if card is not None and card.instance_id is not None:
                        found.append(card.instance_id)
        return tuple(found)

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        return (
            self.viewer,
            self.turn_number,
            self.turn_player,
            self.phase.value,
            self.step,
            tuple(p.canonical_state() for p in self.players),
            self.winner,
            self.result_reason,
            self.normal_summons_used,
        )

    def to_dict(self) -> dict:
        return {
            "viewer": self.viewer,
            "turn_number": self.turn_number,
            "turn_player": self.turn_player,
            "phase": self.phase.value,
            "step": self.step,
            "players": [p.to_dict() for p in self.players],
            "winner": self.winner,
            "result_reason": self.result_reason,
            "normal_summons_used": list(self.normal_summons_used),
        }

    def __str__(self) -> str:
        return (
            f"<GameStateView p{self.viewer} T{self.turn_number} "
            f"{self.phase.value} me:LP{self.me.life_points} "
            f"opp:LP{self.opponent.life_points}>"
        )


# ----------------------------------------------------------------------
# 내부 — 공개 범위 판정
# ----------------------------------------------------------------------
def _player_view(state: "GameState", player_id: int, viewer: int) -> PlayerView:
    player = state.player(player_id)
    return PlayerView(
        player_id=player_id,
        life_points=player.life_points,
        zones=tuple(
            _zone_view(player.zones[zone], viewer)
            for zone in PLAYER_ZONES
            if zone in player.zones
        ),
    )


def _zone_view(container: "ZoneContainer", viewer: int) -> ZoneView:
    zone = container.zone
    visibility = zone_visibility(zone)
    kind = zone_kind(zone)
    size = len(container)

    base = dict(
        zone=zone,
        owner=container.owner,
        visibility=visibility,
        kind=kind,
        capacity=zone_capacity(zone),
        size=size,
    )

    # 덱은 아무도 내용을 모른다. 자기 덱도 마찬가지다 — 그것이 규칙이다.
    if visibility is ZoneVisibility.HIDDEN:
        return ZoneView(**base, cards=(), concealed=True)

    # 패 · 엑스트라 덱은 소유자만 안다.
    if visibility is ZoneVisibility.OWNER_ONLY and container.owner != viewer:
        return ZoneView(**base, cards=(), concealed=True)

    if kind is ZoneKind.SLOTTED:
        cards: tuple[CardView | None, ...] = tuple(
            None if card is None else _card_view(card, viewer)
            for card in container.slots()
        )
    else:
        cards = tuple(_card_view(card, viewer) for card in container)
    return ZoneView(**base, cards=cards, concealed=False)


#: 카드의 **앞뒷면이 공개 여부를 좌우하는** 존.
#:
#: 묘지는 여기 없다. 묘지에 뒷면은 없고 내용은 언제나 공개이기 때문이다.
#: 그런데 ``move_card`` 는 표시 형식을 건드리지 않으므로, 덱에서 묘지로 간
#: 카드는 ``position`` 이 ``FACEDOWN`` 인 채로 남는다 — 앞뒷면만 보고
#: 판단하면 **상대 묘지가 통째로 가려진다.** 존을 먼저 봐야 하는 이유다.
#:
#: 제외 존은 여기 들어 있다. 뒷면 제외가 실제로 존재하고, 그 카드는
#: 제외한 플레이어만 안다.
_FACE_SENSITIVE_ZONES: frozenset[Zone] = frozenset(
    {Zone.MZONE, Zone.EMZONE, Zone.SZONE, Zone.FZONE, Zone.PZONE, Zone.REMOVED}
)


def _definition_of(card: "CardInstance") -> CardDefinitionView | None:
    """
    카드 정의를 스냅숏으로 뜬다. 저장소가 없거나 정의를 못 찾으면 ``None``.

    **예외를 밖으로 내보내지 않는다.** 관측을 만드는 중에 정의 하나가
    없다고 판 전체를 못 보게 되면 안 되고, 없으면 조건이 ``UNKNOWN`` 으로
    답하면 되기 때문이다.
    """
    repository = card.repository
    if repository is None:
        return None
    definition = repository.get(card.card_id)
    if definition is None:
        return None
    return CardDefinitionView.of(definition)


def _card_view(card: "CardInstance", viewer: int) -> CardView:
    """
    공개 존의 카드 한 장이 얼마나 보이는가.

    앞뒷면이 의미를 갖는 존에서만 뒷면을 가린다. 그 경우에도 **컨트롤러는
    안다** — 자기가 세트한 카드가 무엇인지는 당연히 알기 때문이다.
    """
    if card.zone not in _FACE_SENSITIVE_ZONES:
        return CardView.revealed(card)
    if card.is_faceup or card.controller == viewer:
        return CardView.revealed(card)
    return CardView.concealed(card)
