"""
발동 타이밍 — **스펠 스피드가 이 발동을 막는가**.

    ActivationTiming (체인 · 우선권 · 시점)
        ↓  ActivationTimingChecker.check(timing, action)
    ValidationResult            VALID · INVALID · UNKNOWN

여기서 답하는 질문은 **하나뿐이다**
-----------------------------------
    "스펠 스피드 규칙이 이 발동을 막는가?"

``VALID`` 는 **"발동해도 된다" 가 아니다.** 필요조건 하나를 통과했다는
뜻이다. 페이즈 제약 · 턴 1회 · 타이밍 놓침 · 체인 블록 · 데미지 스텝 ·
카드별 예외는 여기서 판정하지 않고, 무엇을 보지 않았는지는
:data:`UNRESOLVED_TIMING_RULES` 에 그대로 적혀 있다.

그래서 이 판정이 밖에서 오는 허가를 **대신하지 않는다.** 좁히기만 하고
넓히지 않는다 — :class:`~engine.response.ResponseLoop` 는 이 관문과
``authorization`` 을 **둘 다** 통과해야 발동으로 넘어간다.

규칙을 지어내지 않는다
----------------------
스펠 스피드 표는 ``data/rules/structured/sd-rulebook-en-v10.json`` 의
``chain.spell_speeds`` 에서 왔다 (공식 룰북 구조화, Phase 1-E). 여기에는
**손으로 옮긴 사본**이 있고, 원본과 어긋나면 테스트가 깨진다 —
``engine/effect/library.py`` 가 Lua 원문을 근거로 들고 다니는 것과 같은
자리다.

``engine`` 은 ``rules`` 를 import 하지 않는다. 실행 계층이 문서 계층을
읽으면 런타임이 데이터 파일에 묶이기 때문이고, 대신 **테스트가** 둘을
대조한다.

몬스터는 모른다
---------------
카드 종류만으로 정해지는 것은 마법 · 함정뿐이다. 몬스터 효과의 스펠
스피드는 그 효과가 기동/유발/플립인지 **유발즉시(퀵 이펙트)**인지에
달려 있고, 그 분류는 이 엔진의 카드 정의에 없다 (``EFFECT_TYPE_QUICK_O``
를 읽는 계층이 없다).

그래서 몬스터는 ``UNKNOWN`` 이다. **추측해서 1 로도 2 로도 만들지
않는다** — 1 로 만들면 퀵 이펙트가 영영 응수하지 못하고, 2 로 만들면
기동 효과가 상대 턴에 발동한다.

.. warning::
   🔴 **"``QUICK_O`` 를 읽으면 풀린다" 가 아니다** (Phase 3-F-26 이 측정).
   위 문장은 *읽는 계층이 없다*는 사실만 말하고, 그래서 읽기만 하면 된다고
   읽히기 쉽다. 측정하면 **입도(granularity)가 먼저 어긋난다.**

   1. :func:`classify_spell_speed` 는 **카드 하나**를 받는다
      (:class:`~engine.game_state_view.CardDefinitionView`). 그런데 공식
      분류는 **효과 하나**에 붙는다 — ``MONSTER_CLASSIFICATION_MISSING`` 의
      문장 자체가 *"monster effect classification"* 이라고 적는다.
   2. 몬스터 **856장(10.4%)** 이 공식 스펠 스피드 1 계열 블록
      (``IGNITION`` · ``TRIGGER_O`` · ``TRIGGER_F`` · ``FLIP``)과 2 계열
      블록(``QUICK_O`` · ``QUICK_F``)을 **둘 다** 가진다. ``QUICK_O`` 를
      가진 몬스터 1,338장 중 **847장(63.3%)** 이 그렇다. 그런 카드에는
      **카드 단위의 답이 존재하지 않는다.**
   3. :meth:`ActivationTimingChecker.speed_of_link` 는
      :attr:`~engine.chain.ChainLink.effect_ref` 를 **이미 들고 있는데**
      버리고 ``self.spell_speed(link.source)`` 를 부른다. 효과 단위 정보가
      거기서 사라진다.

   그리고 공식 의미도 확정되지 않았다 — ``QUICK_O`` 라는 이름은 이 저장소의
   공식 자료 **829파일 전체에서 0회**이고, ``QUICK_O`` 를 가진 카드는 공식
   스펠 스피드 **1 · 2 · 3 전부**에 걸쳐 있다 (지속/필드/장착 마법 13 ·
   함정 414 · **카운터 함정 16**). 그러므로 ``QUICK_O → 스펠 스피드 2`` 는
   카드 단위에서 성립하지 **않는다.**

   요약: ``UNKNOWN`` 의 원인은 "데이터가 없다" 가 아니라 **데이터의 입도와
   이 함수의 입도가 다르고, 공식 대응이 미확정**이라는 것이다. 읽는 계층을
   더하는 것만으로는 풀리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.action import PlayerAction
from engine.chain import Chain, ChainLink
from engine.game_state_view import CardDefinitionView, GameStateView
from engine.ids import InstanceId
from engine.priority import PriorityState
from engine.trigger import TimingPoint
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Zone


class SpellSpeed(int, Enum):
    """
    스펠 스피드 세 단계. 값은 룰북의 숫자 그대로다.

    ``UNKNOWN`` 멤버를 **두지 않는다.** 두면 ``speed >= other`` 같은 비교에
    조용히 섞여 들어가고, 모르는 것이 숫자처럼 행동하게 된다. 모른다는
    것은 :class:`SpellSpeedClassification` 이 ``speed=None`` 으로 말한다.
    """

    NORMAL = 1
    """스펠 스피드 1 — 일반 · 장착 · 지속 · 필드 · 의식 마법, 기동 · 유발 · 플립 효과."""
    FAST = 2
    """스펠 스피드 2 — 일반 · 지속 함정, 속공 마법, 유발즉시(퀵) 효과."""
    COUNTER = 3
    """스펠 스피드 3 — 카운터 함정."""

    @property
    def can_respond_to(self) -> "frozenset[SpellSpeed]":
        """이 속도로 **응수할 수 있는** 상대 속도들."""
        return RESPONSE_TABLE[self]

    def responds_to(self, other: "SpellSpeed") -> bool:
        """``other`` 가 쌓여 있을 때 이 속도로 응수할 수 있는가."""
        return other in RESPONSE_TABLE[self]

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"스펠 스피드 {self.value}"


#: 속도별로 응수할 수 있는 상대 속도. **룰북에서 옮긴 표**다.
#:
#: ``sd-rulebook-en-v10.json`` 의 ``chain.spell_speeds[*].can_respond_to``
#: 와 같아야 하고, 테스트가 그것을 대조한다. 숫자 비교(``>=``)로 대신하지
#: 않는 이유는 "스펠 스피드 1 은 **아무것에도** 응수할 수 없다" 가 비교식이
#: 아니라 별도의 규칙이기 때문이다 (RULE-CHAIN-004).
RESPONSE_TABLE: dict[SpellSpeed, frozenset[SpellSpeed]] = {
    SpellSpeed.NORMAL: frozenset(),
    SpellSpeed.FAST: frozenset({SpellSpeed.NORMAL, SpellSpeed.FAST}),
    SpellSpeed.COUNTER: frozenset(
        {SpellSpeed.NORMAL, SpellSpeed.FAST, SpellSpeed.COUNTER}
    ),
}

#: 속도를 정한 근거 규칙 번호. 문서 계층의 ``RuleRef`` 와 같은 문자열이다.
SPEED_RULES: dict[SpellSpeed, tuple[str, ...]] = {
    SpellSpeed.NORMAL: ("RULE-CHAIN-004", "RULE-CHAIN-003"),
    SpellSpeed.FAST: ("RULE-CHAIN-005", "RULE-CHAIN-003"),
    SpellSpeed.COUNTER: ("RULE-CHAIN-006", "RULE-CHAIN-003"),
}

#: 세트한 턴을 **부르는 쪽이 알려주지 않았을** 때 모자란 것.
#:
#: 이 계층은 판을 읽지 않으므로 (``GameStateView`` 만 받는다) "이 카드를 이
#: 턴에 세웠는가" 를 스스로 알 수 없다. 그 사실은 ``GameState.rule_uses`` 에
#: 있고, 그것을 들고 있는 쪽이 ``ActivationTiming.set_this_turn`` 으로 넘긴다
#: (체인과 우선권을 같은 방식으로 받는 것과 같다).
SET_TURN_MISSING = (
    "set-turn (이 카드를 이 턴에 세웠는지 — ActivationTiming.set_this_turn)"
)

#: 이 계층이 **보지 않은** 규칙들. ``VALID`` 가 "발동해도 된다" 가 아닌 이유다.
UNRESOLVED_TIMING_RULES: tuple[str, ...] = (
    "페이즈별 발동 제약 (메인 페이즈 전용 · 배틀 페이즈 등)",
    "세트한 턴 제약 — set_this_turn 을 받지 못하면 보지 못한다",
    "1턴에 1번 · 턴 1회 제약",
    "타이밍 놓침 (when/if)",
    "체인 블록 · 데미지 스텝 · 배틀 스텝 타이밍",
    "카드별 발동 예외",
)

#: 몬스터 효과의 속도를 정할 수 없는 이유.
MONSTER_CLASSIFICATION_MISSING = (
    "monster effect classification (기동 · 유발 · 플립 vs 유발즉시)"
)


@dataclass(frozen=True, slots=True)
class SpellSpeedClassification:
    """
    카드 하나의 스펠 스피드 판정과 **그 근거**.

    ``speed`` 가 ``None`` 이면 **모른다** 는 뜻이고, 그때는 ``missing`` 이
    무엇이 없어서인지 말한다. 둘 중 하나만 채우는 것은 모순이므로 거부한다.
    """

    speed: SpellSpeed | None
    basis: str
    """무엇을 보고 정했는가. 예: ``"카드 종류: SPELL / QUICKPLAY"``."""
    rules: tuple[str, ...] = ()
    missing: str | None = None

    def __post_init__(self) -> None:
        if self.speed is None and not self.missing:
            raise ValueError(
                "스펠 스피드를 모른다면 **무엇이 없어서인지** 적어야 합니다."
            )
        if self.speed is not None and self.missing:
            raise ValueError(
                f"{self.speed} 로 정해졌는데 없는 것이 적혀 있습니다: {self.missing}"
            )

    @property
    def is_known(self) -> bool:
        return self.speed is not None

    def canonical_state(self) -> tuple:
        return (
            self.speed.value if self.speed is not None else None,
            self.basis,
            self.rules,
            self.missing,
        )

    def to_dict(self) -> dict:
        data: dict = {"basis": self.basis}
        if self.speed is not None:
            data["speed"] = self.speed.value
        if self.rules:
            data["rules"] = list(self.rules)
        if self.missing is not None:
            data["missing"] = self.missing
        return data

    def describe_ko(self) -> str:
        which = str(self.speed) if self.speed is not None else "스펠 스피드 미상"
        return f"{which} ({self.basis})"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


#: 관측에 카드가 없을 때. **"없다" 가 아니라 "못 봤다" 다.**
NOT_VISIBLE = SpellSpeedClassification(
    None, "관측에 없는 카드", missing="hidden card identity"
)
#: 뒷면이라 정체를 모를 때.
FACE_DOWN = SpellSpeedClassification(
    None, "뒷면 카드", missing="face-down card identity"
)


def classify_spell_speed(
    definition: CardDefinitionView | None,
) -> SpellSpeedClassification:
    """
    카드 정의 하나의 스펠 스피드. **카드 종류만 본다.**

    마법 · 함정은 종류가 속도를 정하지만, 몬스터는 정하지 못한다 — 모듈
    설명 참고.
    """
    if definition is None:
        return NOT_VISIBLE
    kinds = set(definition.type_names)
    if definition.is_trap:
        if "COUNTER" in kinds:
            return SpellSpeedClassification(
                SpellSpeed.COUNTER,
                "카드 종류: TRAP / COUNTER",
                SPEED_RULES[SpellSpeed.COUNTER],
            )
        return SpellSpeedClassification(
            SpellSpeed.FAST, "카드 종류: TRAP", SPEED_RULES[SpellSpeed.FAST]
        )
    if definition.is_spell:
        if "QUICKPLAY" in kinds:
            return SpellSpeedClassification(
                SpellSpeed.FAST,
                "카드 종류: SPELL / QUICKPLAY",
                SPEED_RULES[SpellSpeed.FAST],
            )
        return SpellSpeedClassification(
            SpellSpeed.NORMAL, "카드 종류: SPELL", SPEED_RULES[SpellSpeed.NORMAL]
        )
    if definition.is_monster:
        # **추측하지 않는다.** 이 카드의 어느 효과인지에 따라 1 일 수도
        # 2 일 수도 있고, 그 분류가 이 엔진에 없다.
        return SpellSpeedClassification(
            None, "몬스터 효과", missing=MONSTER_CLASSIFICATION_MISSING
        )
    return SpellSpeedClassification(
        None, "분류되지 않는 카드", missing="card type classification"
    )


@dataclass(frozen=True, slots=True)
class ActivationTiming:
    """
    발동 판정에 필요한 **흐름의 위치**. 세 값을 **참조로만** 담는다.

    ``Chain`` 도 ``PriorityState`` 도 복사하지 않는다 — 복사하면 원본과
    어긋날 수 있고, 어긋난 순간 어느 쪽이 맞는지 알 수 없다. 페이즈 ·
    턴 플레이어는 관측(``GameStateView``)이 이미 들고 있으므로 여기 없다.
    """

    chain: Chain
    priority: PriorityState
    point: TimingPoint | None = None
    """지금이 어떤 시점인가. ``None`` 은 **"모른다"** 이지 "시점이 없다" 가 아니다."""
    set_this_turn: bool | None = None
    """
    발동하려는 카드를 **이 턴에 세웠는가** (Phase 3-E-15).

    ``None`` 은 **"모른다"** 이지 "세우지 않았다" 가 아니다 — ``point`` 와 같은
    자리다. 모르면 세트한 카드의 발동은 ``UNKNOWN`` 이 되고, ``UNKNOWN`` 은
    허가가 아니다.

    왜 값으로 받는가: 이 사실은 ``GameState.rule_uses`` 에 있고 관측
    (``GameStateView``) 에는 **없다.** 상대가 언제 세웠는지는 공개 정보가
    아니기 때문이다. 그래서 체인과 우선권처럼 **판을 들고 있는 쪽이** 읽어서
    넘긴다 (ADR-007).
    """

    def __post_init__(self) -> None:
        if not isinstance(self.chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(self.chain).__name__}")
        if not isinstance(self.priority, PriorityState):
            raise TypeError(
                f"PriorityState 가 필요합니다: {type(self.priority).__name__}"
            )
        if self.set_this_turn is not None and not isinstance(self.set_this_turn, bool):
            raise TypeError(
                f"set_this_turn 은 bool 또는 None 입니다: {self.set_this_turn!r}"
            )

    @property
    def chain_is_open(self) -> bool:
        """응수할 링크가 쌓여 있는가."""
        return not self.chain.is_empty and not self.chain.is_complete

    @property
    def responding_to(self) -> ChainLink | None:
        """지금 응수하려는 대상 링크. 체인이 비었으면 ``None``."""
        return self.chain.links[-1] if self.chain.links else None

    def canonical_state(self) -> tuple:
        return (
            self.chain.canonical_state(),
            self.priority.canonical_state(),
            self.point.value if self.point is not None else None,
            self.set_this_turn,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "chain": self.chain.to_dict(),
            "priority": self.priority.to_dict(),
            "chain_is_open": self.chain_is_open,
        }
        if self.point is not None:
            data["point"] = self.point.value
        if self.set_this_turn is not None:
            data["set_this_turn"] = self.set_this_turn
        return data

    def describe_ko(self) -> str:
        where = "체인 위" if self.chain_is_open else "체인 없음"
        return f"{where} · {self.priority.describe_ko()}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class ActivationTimingChecker:
    """
    스펠 스피드가 이 발동을 막는지 본다. **판을 읽지도 바꾸지도 않는다.**

    관측만 들고 있어서 바꿀 수 있는 것이 애초에 없다
    (:class:`~engine.priority.PriorityResolver` 와 같은 자리).
    """

    __slots__ = ("_view",)

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "ActivationTimingChecker 는 GameStateView 만 받습니다. "
                "GameState 를 직접 넘기면 판정이 판을 바꿀 수 있게 됩니다."
            )
        self._view = view

    @property
    def view(self) -> GameStateView:
        return self._view

    @property
    def unresolved_rules(self) -> tuple[str, ...]:
        """이 판정이 **보지 않은** 것들. ``VALID`` 를 읽을 때 함께 읽는다."""
        return UNRESOLVED_TIMING_RULES

    # ==================================================================
    # 분류
    # ==================================================================
    def spell_speed(self, instance: InstanceId | None) -> SpellSpeedClassification:
        """
        판 위의 카드 하나의 스펠 스피드.

        관측에 없으면 **"없다" 가 아니라 "못 봤다"** 이고, 뒷면이면 정체를
        모른다. 셋을 같은 답으로 접지 않는다.
        """
        if instance is None:
            return SpellSpeedClassification(
                None, "가리킨 카드가 없음", missing="activating card"
            )
        card = self._view.find(instance)
        if card is None:
            return NOT_VISIBLE
        if not card.is_identified:
            return FACE_DOWN
        return classify_spell_speed(card.definition)

    def speed_of_link(self, link: ChainLink | None) -> SpellSpeedClassification:
        """체인 링크 하나의 스펠 스피드. 발동한 카드를 보고 정한다."""
        if link is None:
            return SpellSpeedClassification(
                None, "응수할 링크가 없음", missing="chain link"
            )
        return self.spell_speed(link.source)

    # ==================================================================
    # 판정
    # ==================================================================
    def check(
        self, timing: ActivationTiming, action: PlayerAction
    ) -> ValidationResult:
        """
        **스펠 스피드가 이 발동을 막는가.**

        ``VALID`` 는 "발동해도 된다" 가 아니라 "이 관문은 통과했다" 이다.
        보지 않은 규칙은 :attr:`unresolved_rules` 에 적혀 있고, 결과의
        ``notes`` 로도 함께 나간다.
        """
        if not isinstance(timing, ActivationTiming):
            raise TypeError(
                f"ActivationTiming 이 필요합니다: {type(timing).__name__}"
            )
        if not isinstance(action, PlayerAction):
            raise TypeError(f"PlayerAction 이 필요합니다: {type(action).__name__}")

        # **세트한 턴을 먼저 본다** (Phase 3-E-15). 체인이 비어 있어도 걸리는
        # 제약이므로 아래의 이른 통과보다 앞이어야 한다.
        on_set_turn = self._set_turn_refusal(timing, action)
        if on_set_turn is not None:
            return on_set_turn

        if not timing.chain_is_open:
            # 체인이 비어 있으면 **응수가 아니다.** 스펠 스피드 1 도 체인 1
            # 이 될 수 있다 (RULE-CHAIN-004 의 "Chain Link 2 이상" 제약).
            return self._passed(
                "체인이 비어 있어 스펠 스피드 제약이 걸리지 않습니다."
            )

        mine = self.spell_speed(action.source)
        if not mine.is_known:
            return self._unknown(
                f"발동하려는 카드의 스펠 스피드를 판정할 수 없습니다 "
                f"({mine.basis}).",
                mine.missing,
            )

        theirs = self.speed_of_link(timing.responding_to)
        if not theirs.is_known:
            return self._unknown(
                f"응수할 링크의 스펠 스피드를 판정할 수 없습니다 "
                f"({theirs.basis}).",
                theirs.missing,
            )

        assert mine.speed is not None and theirs.speed is not None
        if mine.speed.responds_to(theirs.speed):
            return self._passed(
                f"{mine.speed} 로 {theirs.speed} 에 응수할 수 있습니다.",
                rules=mine.rules,
            )
        return ValidationResult.invalid(
            ValidationCode.SPELL_SPEED_TOO_LOW,
            f"{mine.speed} 로는 {theirs.speed} 에 응수할 수 없습니다 "
            + (
                "(스펠 스피드 1 은 어떤 효과에도 응수할 수 없습니다)."
                if mine.speed is SpellSpeed.NORMAL
                else "."
            ),
        )

    # ------------------------------------------------------------------
    def _set_turn_refusal(
        self, timing: ActivationTiming, action: PlayerAction
    ) -> "ValidationResult | None":
        """
        **세트한 턴에는 발동할 수 없는 카드인가** (Phase 3-E-15).

        막지 않으면 ``None``. 이 규칙의 자리가 아닌 경우에도 ``None`` 이다 —
        둘을 구분해서 적지 않는다. 막는 쪽만 결과를 만든다.

        **세 조항이 서로 다르게 적는다.**

        ==================  ==================================================
        세트한 통상 마법     RULE-SPELLTRAP-012 — "Spell Cards can be activated
                            during the Main Phases **even in the same turn that
                            you Set them** (except for Quick-Play Spell
                            Cards)." → 이 규칙이 **걸리지 않는다**
        세트한 속공 마법     RULE-SPELLTRAP-007 — "you **cannot activate the
                            card in the same turn you Set it**"
        세트한 함정          RULE-SPELLTRAP-009 — "You cannot activate a Trap in
                            the same turn that you Set it, but you can activate
                            it at any time after that—starting from the
                            beginning of the next turn."
        ==================  ==================================================

        그래서 **스펠 스피드로 가른다.** 1 은 통상 · 지속 · 장착 · 필드 · 의식
        마법이고 (RULE-SPELLTRAP-012 가 괄호로 뺀 속공 마법만 빠진다), 2 와 3
        은 속공 마법과 함정이다. 카드 이름을 보지 않는다.

        **패에서의 발동에는 걸리지 않는다.** 세트하지 않은 카드에 "세트한 턴"
        을 물으면 뜻이 없다 — 그래서 자리와 표시 형식을 먼저 본다.
        """
        if action.source is None:
            return None
        card = self._view.find(action.source)
        if card is None or card.zone is not Zone.SZONE or card.face_up:
            # 세트해 둔 카드가 아니다 — 이 규칙의 자리가 아니다.
            return None
        speed = self.spell_speed(action.source)
        if speed.speed is None or speed.speed is SpellSpeed.NORMAL:
            # 스펠 스피드를 모르면 **다른 이유로** 이미 막히거나 모른다 —
            # 여기서 두 번 말하지 않는다. 1 이면 이 규칙이 걸리지 않는다.
            return None
        if timing.set_this_turn is None:
            return self._unknown(
                "세트한 턴을 알 수 없어 발동할 수 있는지 판정할 수 없습니다 "
                f"({speed.speed} 는 세트한 턴에 발동할 수 없습니다).",
                SET_TURN_MISSING,
            )
        if timing.set_this_turn:
            return ValidationResult.invalid(
                ValidationCode.SET_THIS_TURN,
                f"세트한 턴에는 발동할 수 없습니다 ({speed.speed} — "
                "RULE-SPELLTRAP-007 · 009). 다음 턴부터 발동할 수 있습니다.",
            )
        return None

    # ------------------------------------------------------------------
    def _passed(self, reason: str, rules: tuple[str, ...] = ()) -> ValidationResult:
        """
        관문 통과. **보지 않은 규칙을 함께 들려 보낸다** — 그것을 빼면
        "발동해도 된다" 로 읽히기 때문이다.
        """
        return ValidationResult(
            ActionValidity.VALID,
            ValidationCode.OK,
            reason + " 다른 타이밍 규칙은 판정하지 않았습니다.",
            notes=rules + UNRESOLVED_TIMING_RULES,
        )

    def _unknown(self, reason: str, missing: str | None) -> ValidationResult:
        """
        판정할 수 없다. **위반으로 접지 않는다** — 모르는 것과 안 되는 것은
        다른 사실이고, 정보가 생기면 답이 달라진다.
        """
        return ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED
            if missing == MONSTER_CLASSIFICATION_MISSING
            else ValidationCode.INFORMATION_UNAVAILABLE,
            reason,
            missing_rule=missing,
            notes=UNRESOLVED_TIMING_RULES,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ActivationTimingChecker {self._view}>"


__all__ = [
    "SpellSpeed",
    "RESPONSE_TABLE",
    "SPEED_RULES",
    "UNRESOLVED_TIMING_RULES",
    "MONSTER_CLASSIFICATION_MISSING",
    "SpellSpeedClassification",
    "classify_spell_speed",
    "ActivationTiming",
    "ActivationTimingChecker",
]
