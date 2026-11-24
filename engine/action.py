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
from engine.vocabulary import Phase, Zone


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
    SPECIAL_SUMMON = "special_summon"
    """
    특수 소환한다. **일반 소환권을 쓰지 않는다.**

    ``NORMAL_SUMMON`` 과 합치지 않는다 — 소환권 · 페이즈 · 절차가 전부
    다르고, 합치면 "1턴에 한 번" 이 특수 소환까지 묶어 버린다.

    **어떤 특수 소환법인가는 여기서 말하지 않는다.** 융합 · 싱크로 · 엑시즈 ·
    링크는 각자 재료를 고르는 절차가 있고, 그 절차가 생길 때 어떻게
    표현할지 정한다.
    """
    LINK_SUMMON = "link_summon"
    """
    **링크 소환한다** (Phase 6-AC). 엑스트라 덱의 링크 몬스터 하나와
    :attr:`PlayerAction.materials` 가 필요하다.

    ``SPECIAL_SUMMON`` 과 가르는 이유
    ---------------------------------
    위의 ``SPECIAL_SUMMON`` docstring 이 "어떤 특수 소환법인가는 여기서
    말하지 않는다 … 그 절차가 생길 때 어떻게 표현할지 정한다" 고 적어
    두었다. **그 절차가 생겼고, 이것이 그 표현이다.**

    =====================  =====================  =======================
                            ``SPECIAL_SUMMON``     ``LINK_SUMMON``
    =====================  =====================  =======================
    출발 자리               패 · 묘지               **엑스트라 덱**
    놓이는 자리             몬스터 존               **엑스트라 몬스터 존**
    소재                    없다                    **반드시 있다**
    검증                    언제나 ``UNKNOWN``      소재 조건을 **읽은**
                                                    카드만 ``VALID``
    =====================  =====================  =======================

    🔴 **``SPECIAL_SUMMON`` 의 ``UNKNOWN`` 을 이 종류가 풀어 주지 않는다.**
    플레이어가 직접 선언하는 특수 소환은 그대로 ``UNKNOWN`` 이다 — 여기서
    허가가 나는 것은 **소재 조건을 손으로 확인한 링크 몬스터**뿐이고, 그
    목록은 :data:`~engine.link_summon.LINK_MATERIAL_RULES` 다.
    """
    XYZ_SUMMON = "xyz_summon"
    """
    **엑시즈 소환한다** (Phase 6-BO). 엑스트라 덱의 엑시즈 몬스터 하나와
    :attr:`PlayerAction.materials` 가 필요하다.

    ``LINK_SUMMON`` 과 가르는 이유
    -----------------------------
    =====================  =====================  =======================
                            ``LINK_SUMMON``        ``XYZ_SUMMON``
    =====================  =====================  =======================
    소재가 가는 곳          **묘지**                **그 카드 아래**
    소재의 그 뒤            판을 떠났다              판에 남아 꺼내 쓴다
    소재를 세는 축          링크 수치                레벨 · 랭크
    =====================  =====================  =======================

    첫 줄이 가르는 이유 전부다. 소재가 묘지로 가는 절차와 **겹쳐 두는**
    절차를 한 종류로 적으면, 「엑시즈 소재를 제거하고」 류의 비용이 어디서
    카드를 꺼내야 하는지 영영 말할 수 없다.

    🔴 **``SPECIAL_SUMMON`` 의 ``UNKNOWN`` 을 이 종류가 풀어 주지 않는다** —
    ``LINK_SUMMON`` 과 같다. 허가가 나는 것은 소재 조건을 손으로 확인한
    카드뿐이고, 그 목록은 :data:`~engine.xyz_rules.XYZ_MATERIAL_RULES` 다.
    """
    SET_MONSTER = "set_monster"
    """일반 소환권을 써서 뒷면 수비 표시로 세트한다."""
    SET_SPELL_TRAP = "set_spell_trap"
    ACTIVATE_CARD = "activate_card"
    """
    **카드 수준**의 발동 선언 — 어느 효과인지 지목하지 않는다.

    .. warning::
       **Engine V1 에서는 유효한 행위가 아니다** (Phase 3-F-21 · 3-F-22 · 3-F-23).
       후보로 나오지 않고(``withheld`` 에 이유만 적힌다), ``Duel.apply`` 가 거절
       하고, :class:`~engine.activation.EffectActivator` 가 **종류만 보고** 거절
       한다 ("activate_card 는 효과 발동이 아닙니다"). 빠진 규칙은
       ``activation-timing (Phase 2-C/2-F)`` 로 지목되어 있다
       (:data:`~engine.action_validation._MISSING_RULE`).

    🔴 **마법 · 함정의 발동을 이 종류로 적지 않는다.** 이 docstring 은 한동안
    "카드 자체를 발동한다 (마법 · 함정의 발동)" 이라고 적고 있었는데, 그것은
    **실제 계약과 어긋났다** — Engine V1 에서 마법 · 함정의 발동을 수행하는 것은
    :attr:`ACTIVATE_EFFECT` 다 (Phase 3-F-23 이 정정했다). 등록된 효과 전부가
    마법 · 함정이고, 그 발동이 ``ACTIVATE_EFFECT`` 로 체인까지 간다.

    공식 룰북은 메인 페이즈의 행동을 "Activate a Card or Effect" **하나**로 적고
    마법 · 함정을 "카드" 로 분류한다. 그래서 이 이름은 **공식 개념**을 가리키되
    **현재 엔진에서는 비어 있는 자리**다 — 공식 용어와 엔진 종류가 1:1 이 아니다.
    """
    ACTIVATE_EFFECT = "activate_effect"
    """
    ``effect_ref`` 로 **지목한 효과**를 발동한다. ``effect_ref`` 는 **필수**다.

    **Engine V1 에서 유효한 발동 행위는 이것 하나다.** 그리고 지금은 마법 · 함정
    카드의 발동까지 **이 종류가 맡는다** — 엔진은 모든 발동을 "카드 X 의 효과
    #N" 으로 모델링하고 ``effect_ref`` 가 그 지목 수단이기 때문이다. 공식 용어로
    "카드의 발동" 인 것도 여기로 들어온다 (Phase 3-F-23 의 대응표).

    .. note::
       지금 등록된 효과는 **카드마다 하나씩**이고 전부 ``ordinal=0`` 이다. 즉
       "어느 효과인지" 의 선택지가 실제로 갈리는 카드가 아직 없고, 후보를 여럿으로
       만드는 것은 **대상**(``target_combinations``)이다. 지목이라는 의미는
       **선언되어 있으나 아직 쓰이지 않는다** — 몬스터 효과나 복수 효과 카드가
       등록되는 날 비로소 갈린다.
    """
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
        PlayerActionKind.SPECIAL_SUMMON,
        PlayerActionKind.LINK_SUMMON,
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

#: 소재를 **가질 수 있는** 종류.
#:
#: 🔴 하나뿐이고, 그것이 사실이다. 융합 · 싱크로 · 엑시즈는 소재를 쓰지만
#: 그 절차가 아직 없으므로 (``PlayerActionKind`` 에 종류도 없다) 여기 적지
#: 않는다 — 미리 적어 두면 "소재를 받을 수 있는 행위" 가 절차 없이 생긴다.
_ALLOWS_MATERIALS: frozenset[PlayerActionKind] = frozenset(
    #: 🔴 **둘이 되었다** (Phase 6-BO). 엑시즈 소환도 소재를 고른다 —
    #: 다른 것은 소재가 **가는 곳**이고 (묘지 / 그 카드 아래) 그 차이는
    #: 절차가 들고 있다.
    {PlayerActionKind.LINK_SUMMON, PlayerActionKind.XYZ_SUMMON}
)

#: 소재가 **반드시 있어야 하는** 종류.
#:
#: 링크 소환은 소재가 0장일 수 없다 (공식 절차 — 링크 수치만큼의 몬스터를
#: 소재로 한다). 그래서 :data:`_ALLOWS_MATERIALS` 와 같은 내용이지만 **다른
#: 질문**이고, 두 표가 갈리는 날 (소재가 선택인 절차가 들어오는 날) 한쪽만
#: 고치면 된다.
_NEEDS_MATERIALS: frozenset[PlayerActionKind] = frozenset(
    #: 엑시즈 소환도 소재가 0장일 수 없다 (공식 절차).
    {PlayerActionKind.LINK_SUMMON, PlayerActionKind.XYZ_SUMMON}
)

#: ``phase`` 가 필요한 종류.
_NEEDS_PHASE: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.CHANGE_PHASE}
)

#: 대상을 **몇 개** 가져야 하는가. ``None`` 이면 제한 없음.
#:
#: 🔴 값이 **tuple 이면 허용되는 수들**이다 (Phase 6-BN). 하나의 수로는
#: "칸을 지목해도 되고 안 해도 된다" 를 적을 수 없고, ``None`` 으로 적으면
#: 제한이 사라진다 — 둘 다 사실이 아니다.
_TARGET_COUNT: dict[PlayerActionKind, "int | tuple[int, ...] | None"] = {
    PlayerActionKind.NORMAL_SUMMON: 0,
    #: 🔴 **0 또는 1** (Phase 6-BN). 1 개일 때 그 하나는 놓을 칸을 지목하는
    #: ``ZONE`` 대상이고 (``PlayerAction.special_summon`` 의 ``slot``),
    #: 모양은 검증기가 다시 확인한다. 「대상」 이라는 규칙 용어와 다르다 —
    #: 칸을 가리키는 것은 효과의 대상 지정이 아니다.
    PlayerActionKind.SPECIAL_SUMMON: (0, 1),
    #: 🔴 **소재는 대상이 아니다** — 링크 소재는 ``materials`` 에 들어가고
    #: 이 칸은 ``0`` 이다 (``PlayerAction.materials`` 의 설명).
    PlayerActionKind.LINK_SUMMON: 0,
    #: 🔴 엑시즈 소재도 ``materials`` 에 들어간다 — 이 칸은 ``0`` 이다.
    PlayerActionKind.XYZ_SUMMON: 0,
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
    materials: tuple[InstanceId, ...] = ()
    """
    **소재로 보낼 카드들** (Phase 6-AC). 링크 소환만 쓴다.

    🔴 **``targets`` 에 넣지 않는다.** 「대상」 은 유희왕의 규칙 용어이고
    (``EFFECT_FLAG_CARD_TARGET`` · 「대상으로 지정할 수 없다」 내성), 링크
    소재는 **대상으로 지정되지 않는다.** 같은 칸에 넣으면 "대상 내성을 가진
    몬스터는 링크 소재가 될 수 없다" 가 되고, 그것은 규칙이 아니다.

    ``source`` 와도 다르다 — ``source`` 는 **소환되는** 링크 몬스터이고
    여기 든 것은 **필드를 떠나는** 몬스터들이다. 한 칸에 섞으면 "무엇이
    소환되는가" 를 잃는다.

    순서를 유지한다. 소재의 순서가 규칙을 바꾸지는 않지만, 기록이
    재현되어야 하므로 (``canonical_state``) 받은 순서를 그대로 들고 있는다.
    """
    cost_cards: tuple[InstanceId, ...] = ()
    """
    **비용으로 내놓을 카드들** (Phase 6-BI). 효과 발동만 쓴다.

    🔴 **비용은 발동 시점에 치른다.** 그래서 무엇을 내놓을지는 **행위에
    적힌다** — 해결 중의 선택이 아니다. 공식 스크립트가 그 구분을 그대로
    적는다: ``SetCost`` 는 발동을 선언할 때 돌고 ``SetOperation`` 은 해결할
    때 돈다.

    🔴 **``targets`` 도 ``materials`` 도 아니다.** 「대상」 은 규칙 용어이고
    (``EFFECT_FLAG_CARD_TARGET``) 비용으로 내놓는 카드는 대상으로 지정되지
    않는다. 소재도 아니다 — 소재는 소환되는 몬스터의 재료이고, 이쪽은
    발동의 값이다. 한 칸에 섞으면 그 구분이 영영 사라진다 (ADR-002 가
    파괴와 묘지로 보내기를 가른 것과 같은 이유).

    🔴 **어느 비용 자리의 것인지는 여기 적지 않는다.** 그 번호는 정의가
    들고 있고 (:func:`~engine.cost_bridge.cost_selections_from` 이 읽는다),
    행위는 **카드만** 적는다 — 행위가 정의의 내부 번호를 들고 다니면 정의가
    바뀔 때 기록이 조용히 다른 비용을 가리킨다.

    순서를 유지한다 (``materials`` 와 같은 이유 — 기록이 재현되어야 한다).
    """

    def __post_init__(self) -> None:
        if self.actor not in (0, 1):
            raise MalformedAction(f"actor 는 0 또는 1 입니다: {self.actor}")
        if not isinstance(self.kind, PlayerActionKind):
            raise MalformedAction(f"알 수 없는 행위입니다: {self.kind!r}")
        if not isinstance(self.targets, tuple):
            raise MalformedAction(
                "targets 는 tuple 이어야 합니다 — Action 은 불변입니다."
            )
        if not isinstance(self.materials, tuple):
            raise MalformedAction(
                "materials 는 tuple 이어야 합니다 — Action 은 불변입니다."
            )
        if not isinstance(self.cost_cards, tuple):
            raise MalformedAction(
                "cost_cards 는 tuple 이어야 합니다 — Action 은 불변입니다."
            )
        if self.cost_cards and self.kind is not PlayerActionKind.ACTIVATE_EFFECT:
            #: 🔴 **비용은 효과 발동의 것이다.** 다른 행위에 적히면 그
            #: 행위가 비용을 치르는 것처럼 읽힌다.
            raise MalformedAction(
                f"{self.kind.value} 에는 비용으로 내놓을 카드를 적을 수 "
                "없습니다 — 비용은 효과 발동이 치릅니다."
            )
        if len(set(self.cost_cards)) != len(self.cost_cards):
            raise MalformedAction(
                f"같은 카드를 비용으로 두 번 낼 수 없습니다: {self.cost_cards}"
            )
        if self.materials and self.kind not in _ALLOWS_MATERIALS:
            raise MalformedAction(
                f"{self.kind.value} 에는 소재가 없습니다 — 소재를 쓰는 "
                "행위는 "
                + " · ".join(sorted(k.value for k in _ALLOWS_MATERIALS))
                + " 뿐입니다."
            )
        if self.kind in _NEEDS_MATERIALS and not self.materials:
            raise MalformedAction(
                f"{self.kind.value} 에는 소재가 필요합니다 — 소재 없는 "
                "링크 소환은 표현 자체가 성립하지 않습니다."
            )
        if len(set(self.materials)) != len(self.materials):
            raise MalformedAction(
                f"같은 카드를 소재로 두 번 쓸 수 없습니다: {self.materials}"
            )
        if self.source is not None and self.source in self.materials:
            raise MalformedAction(
                "소환되는 카드가 자기 소재가 될 수 없습니다: "
                f"{self.source}"
            )

    # ------------------------------------------------------------------
    # 편의 생성자 — 종류마다 필요한 칸이 다르므로 이름으로 구분한다
    # ------------------------------------------------------------------
    @classmethod
    def normal_summon(cls, actor: int, source: InstanceId) -> "PlayerAction":
        return cls(kind=PlayerActionKind.NORMAL_SUMMON, actor=actor, source=source)

    @classmethod
    def special_summon(
        cls,
        actor: int,
        source: InstanceId,
        slot: "int | None" = None,
    ) -> "PlayerAction":
        """
        그 카드를 특수 소환한다. **고수준 의도**다.

        어떤 표시 형식으로 놓을지는 여기서 말하지 않는다 — 고르는 계층이
        아직 없고, 지금 적으면 그것이 규칙처럼 굳는다 (STRUCTURAL-61).

        🔴 **칸은 Phase 6-BN 에서 말할 수 있게 되었다.** ``slot`` 을 주면
        ``ZONE`` 대상 하나가 붙고, 그 칸이 후보 생성 · 검증 · 절차 ·
        리플레이를 통과하는 **같은 한 칸**이 된다. 놓을 칸이 규칙으로
        정해진 카드가 있기 때문이다 (성유물－『성관』: 링크 마커가 가리키는
        메인 몬스터 존). ``None`` 이면 예전과 한 글자도 다르지 않다 —
        칸을 고르지 않는다 (STRUCTURAL-41).
        """
        targets = ()
        if slot is not None:
            targets = (
                ActionTarget.zone_target(
                    player=actor, zone=Zone.MZONE, index=int(slot)
                ),
            )
        return cls(
            kind=PlayerActionKind.SPECIAL_SUMMON,
            actor=actor,
            source=source,
            targets=targets,
        )

    @classmethod
    def link_summon(
        cls,
        actor: int,
        source: InstanceId,
        materials: "tuple[InstanceId, ...]",
    ) -> "PlayerAction":
        """
        엑스트라 덱의 링크 몬스터를 **고른 소재로** 링크 소환한다.

        어느 칸에 놓이는지는 여기서 말하지 않는다 —
        :data:`~engine.link_summon.LINK_SUMMON_PROCEDURE` 가 정하고, 그
        범위가 어디까지인지는 그 모듈이 적는다.
        """
        return cls(
            kind=PlayerActionKind.LINK_SUMMON,
            actor=actor,
            source=source,
            materials=tuple(materials),
        )

    @classmethod
    def xyz_summon(
        cls,
        actor: int,
        source: InstanceId,
        materials: "tuple[InstanceId, ...]",
    ) -> "PlayerAction":
        """
        엑스트라 덱의 엑시즈 몬스터를 **고른 소재로** 엑시즈 소환한다.

        어느 칸에 놓이는지는 여기서 말하지 않는다 —
        :data:`~engine.xyz_summon.XYZ_SUMMON_PROCEDURE` 가 정하고, 그
        범위가 어디까지인지는 그 모듈이 적는다.

        🔴 **소재가 어디로 가는지도 여기서 말하지 않는다.** 엑시즈 소재는
        묘지로 가지 않고 그 카드 아래에 겹쳐지며, 그 일을 하는 자리는
        :meth:`~engine.state.game_state.GameState.attach_material` 하나다.
        """
        return cls(
            kind=PlayerActionKind.XYZ_SUMMON,
            actor=actor,
            source=source,
            materials=tuple(materials),
        )

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
        cost_cards: tuple[InstanceId, ...] = (),
    ) -> "PlayerAction":
        """
        카드가 가진 **특정 효과**를 발동한다.

        효과는 ``EffectRef(card_id, ordinal)`` 로 지목한다.
        ``EffectSpec.index`` 는 한 카드 안에서 중복되므로 쓰지 않는다
        (ADR-005, 실측 4,884장).

        ``cost_cards`` 는 **비용으로 내놓을 카드들**이다 (Phase 6-BI).
        기본값이 빈 짝이므로 비용을 고르지 않는 효과의 호출은 한 글자도
        달라지지 않는다.
        """
        return cls(
            kind=PlayerActionKind.ACTIVATE_EFFECT,
            actor=actor,
            source=source,
            effect_ref=effect_ref,
            targets=targets,
            cost_cards=cost_cards,
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
            #: 🔴 **순서를 유지한다** — ``targets`` 와 같은 이유이고, 재현에
            #: 쓰이는 값이므로 정렬해 버리면 기록이 입력과 달라진다.
            tuple(m.value for m in self.materials),
            #: 🔴 **순서를 유지한다** — ``materials`` 와 같은 이유다
            #: (Phase 6-BI). 비용으로 무엇을 냈는지가 다르면 **다른
            #: 행위**이고, 그래서 탐색이 두 갈래로 센다.
            tuple(c.value for c in self.cost_cards),
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
        if self.materials:
            data["materials"] = [m.value for m in self.materials]
        if self.cost_cards:
            data["cost_cards"] = [c.value for c in self.cost_cards]
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
            cost_cards=tuple(
                InstanceId(c) for c in data.get("cost_cards", ())
            ),
            materials=tuple(
                InstanceId(m) for m in data.get("materials", ())
            ),
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
        if self.materials:
            bits.append("소재=" + ",".join(str(m) for m in self.materials))
        if self.cost_cards:
            bits.append("비용=" + ",".join(str(c) for c in self.cost_cards))
        return " ".join(bits)
