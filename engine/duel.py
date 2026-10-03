"""
Duel — **PlayerAction 하나로 듀얼을 처음부터 끝까지 굴리는 자리** (Phase 2-AO).

    Duel.start(...)            판을 만들고 5장씩 뽑는다
        ↓
    duel.legal_actions(seat)   지금 **허가가 나는** 행위들
        ↓
    duel.apply(action)         규칙 계층에게 시키고 결과를 돌려준다
        ↓
    duel.is_over               승패가 정해졌는가

흐름의 위치는 판 **밖**에 있다
------------------------------
:class:`~engine.state.game_state.GameState` 는 판의 **모양**이고, 지금 누가
우선권을 쥐었는지 · 체인이 어디까지 쌓였는지 · 무슨 일이 있었는지는 판의
모양이 아니다. 그래서 ``state_hash()`` 에도 들어가지 않는다 (Phase 1).

그 "흐름의 위치" 를 들고 있는 자리가 여태 **없었다.** 시험마다 각자
:class:`~engine.priority.PriorityState` 와 :class:`~engine.chain.Chain` 을
만들어 썼고, 그래서 듀얼 한 판을 끝까지 굴린 적이 없다. 이 클래스가 그
자리다.

**규칙을 새로 만들지 않는다.** 여기서 하는 일은 이미 있는 계층들을 부르고
그 답을 그대로 전하는 것뿐이다.

    ActionValidator      이 행위를 해도 되는가
    ActionExecutor       (소환) 실제로 적용한다
    TurnProgressor       페이즈를 옮긴다
    PriorityState        우선권을 넘긴다
    GameState            판을 바꾼다

허가가 나지 않는 것은 내놓지 않는다
-----------------------------------
:meth:`legal_actions` 는 **``VALID`` 가 나온 것만** 담는다. ``UNKNOWN`` 은
허가가 아니므로 (이 프로젝트의 모든 자리와 같다) 후보에 넣지 않고,
**왜 못 넣었는지**를 :attr:`LegalActions.withheld` 에 남긴다 — 빈 목록은
"할 것이 없다" 로 읽히고, 적어 둔 것은 "아직" 으로 읽힌다.

그래서 지금 이 듀얼에서 할 수 있는 일은 많지 않다. 일반 소환 · 페이즈
넘기기 · 패스뿐이고, 마법 · 함정 발동은 ``ActionValidator`` 가 아직
``UNKNOWN`` 을 돌려주므로 후보에 없다 (``_COMPLETE_RULES``). 그것이
**지금의 정직한 상태**이고, 그 상태로도 듀얼은 끝까지 간다 — 덱이 떨어지면
진다.

여기서 하지 않는 것
-------------------
AI 를 만들지 않는다. :meth:`legal_actions` 는 **후보만** 내놓고 무엇이
좋은지는 말하지 않는다. 고르는 것은 밖의 일이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor, ActionStatus
from engine.action_target import ActionTarget
from engine.action_validation import ActionValidator
from engine.activation_timing import ActivationTiming, ActivationTimingChecker
from engine.chain import Chain
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.response import ResponseLoop, ResponseState
from engine.state.game_state import DEFAULT_LIFE_POINTS, DuelResult, GameState
from engine.target_bridge import (
    TargetBridgeError,
    selections_for,
    target_combinations,
)
from engine.spell_activation import (
    NormalSpellPlacement,
    SpellActivationError,
    activatable_effects,
    duel_activator,
    duel_resolver,
)
from engine.summon import duel_executor
from engine.turn_progression import ProgressionStatus, TurnProgressor
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import Phase, Zone


#: 전투가 일어나는 존들. 공격자와 대상 모두 여기 있는 카드다.
BATTLE_TARGET_ZONES: tuple[Zone, ...] = (Zone.MZONE, Zone.EMZONE)


class DuelError(RuntimeError):
    """듀얼을 굴리는 방법이 틀렸을 때."""


#: 룰북이 정한 시작 패 (``sd-rulebook-en-v10``).
#:
#:     "Finally, draw 5 cards from the top of your Deck; this is your
#:      starting hand."
OPENING_HAND: int = 5

#: 룰북이 정한 패배 조건 둘.
#:
#:     "You win a Duel if: you reduce your opponent's LP to 0; if your
#:      opponent is unable to draw a card; or if a card's special effect
#:      says you win."
#:     "A player with no cards left in their Deck and unable to draw loses
#:      the Duel."
#:
#: 셋째("카드 효과가 이긴다고 적은 경우")는 **옮기지 않았다** — 그렇게 적힌
#: 카드가 등재되어 있지 않고, 없는 것을 미리 만들지 않는다.
LOSS_BY_LIFE: str = "라이프 포인트가 0 이 되었다"
LOSS_BY_DECK_OUT: str = "덱에서 뽑을 수 없다"


class TurnStep(str, Enum):
    """
    이 듀얼이 턴의 어디쯤에 있는가. **페이즈가 아니다.**

    페이즈는 :class:`~engine.state.turn.TurnState` 가 들고 있고, 이것은
    "그 페이즈 안에서 아직 무엇이 남았는가" 다. 둘을 합치면 "드로우
    페이즈에 들어왔지만 아직 안 뽑았다" 를 적을 자리가 없어진다.
    """

    DRAW_PENDING = "draw_pending"
    """드로우 페이즈에 들어왔고 **아직 뽑지 않았다.**"""
    OPEN = "open"
    """할 일을 고를 수 있다."""


@dataclass(frozen=True, slots=True)
class WithheldAction:
    """
    **후보에 넣지 못한** 행위와 그 이유.

    빈 목록은 "할 것이 없다" 로 읽힌다. 적어 두면 "아직" 으로 읽힌다 —
    이 프로젝트가 빈 칸을 남기지 않는 다른 모든 자리와 같다.
    """

    kind: PlayerActionKind
    reason: str
    missing: str | None = None


@dataclass(frozen=True, slots=True)
class LegalActions:
    """
    지금 이 자리에서 **허가가 난** 행위들과, 나지 않은 것들.

    ``allowed`` 만 보고 고르면 된다. ``withheld`` 는 읽는 쪽이 "엔진이
    무엇을 아직 못 하는가" 를 알아야 할 때 본다.
    """

    seat: int
    allowed: tuple[PlayerAction, ...] = ()
    withheld: tuple[WithheldAction, ...] = ()

    def __len__(self) -> int:
        return len(self.allowed)

    def __iter__(self):
        return iter(self.allowed)

    def kinds(self) -> frozenset[PlayerActionKind]:
        return frozenset(action.kind for action in self.allowed)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return f"P{self.seat}: 허가 {len(self.allowed)}건 · 보류 {len(self.withheld)}건"


@dataclass(frozen=True, slots=True)
class DuelStep:
    """행위 하나를 적용한 결과. **불변**이다."""

    action: PlayerAction
    accepted: bool
    code: ValidationCode
    reason: str
    result: "DuelResult | None" = None
    """이 걸음으로 듀얼이 끝났으면 그 결과."""

    def __bool__(self) -> bool:
        return self.accepted


@dataclass
class Duel:
    """
    듀얼 한 판. **판과 흐름의 위치를 함께** 들고 있다.

    :attr:`state` 는 판의 모양이고 :attr:`priority` 는 흐름의 위치다. 둘을
    한 객체에 담되 **합치지는 않는다** — ``state_hash()`` 는 여전히 판만
    본다.
    """

    state: GameState
    priority: PriorityState
    chain: Chain = field(default_factory=Chain)
    """
    지금 쌓여 있는 체인 (Phase 3-E-3).

    이 모듈의 설명이 처음부터 이 자리라고 적었는데 (``priority`` 와 나란히)
    칸이 없었다. ``Chain`` 은 **불변**이므로 사본과 공유해도 안전하다 —
    링크를 쌓으면 새 ``Chain`` 이 나오고, 그것을 받는 ``Duel`` 만 달라진다.

    ``state_hash()`` 에는 들어가지 않는다. 체인은 판의 **모양**이 아니라
    흐름의 위치다.
    """
    step: TurnStep = TurnStep.OPEN
    first_player: int = 0
    _executor: ActionExecutor = field(default_factory=duel_executor)
    _activator: object = field(default_factory=duel_activator)
    _resolver: object = field(default_factory=duel_resolver)
    _placement: NormalSpellPlacement = field(default_factory=NormalSpellPlacement)
    pending_spells: tuple = ()
    """
    **해결을 기다리는 동안 필드에 놓여 있는 마법** (Phase 3-E-11).

    발동과 해결 사이에 상대의 응답 기회가 들어가므로, 놓은 카드를 묘지로
    보낼 시점이 ``_apply_activation`` 밖으로 밀려났다. 그래서 그 사이에
    ``SpellPlaced`` 를 들고 있어야 한다 — 체인과 같은 이유로 **흐름의
    위치**이고, ``state_hash()`` 에는 들어가지 않는다.

    ``tuple`` 이므로 ``dataclasses.replace`` 로 뜬 사본이 값으로 가져간다 —
    사본의 해결이 진짜의 대기 목록을 건드리지 않는다.
    """

    @property
    def _response_loop(self) -> ResponseLoop:
        """
        **기존 응답 루프.** 상태를 들지 않으므로 칸을 차지하지 않는다 —
        쌓인 체인과 우선권은 이미 :attr:`chain` · :attr:`priority` 에 있고,
        :class:`~engine.response.ResponseState` 는 그 둘의 짝일 뿐이다.
        그래서 같은 상태를 두 군데 복사하지 않는다.
        """
        return ResponseLoop(self._activator)

    def _response_state(self) -> ResponseState:
        """지금 흐름의 위치. **읽기만 한다.**"""
        return ResponseState(self.chain, self.priority)

    # ------------------------------------------------------------------
    # 시작
    # ------------------------------------------------------------------
    @classmethod
    def start(
        cls,
        repository=None,
        *,
        decks,
        seed: int,
        first_player: int = 0,
        life_points: int = DEFAULT_LIFE_POINTS,
    ) -> "Duel":
        """
        듀얼을 시작한다 — 섞고, **5장씩** 뽑고, 선공의 드로우 페이즈에 선다.

        ``seed`` 는 **필수**다. 씨앗 없는 무작위는 재현할 수 없고, 이
        엔진은 그것을 다른 모든 자리에서 이미 거부한다 (Phase 2-Z).

        첫 드로우 페이즈는 :attr:`TurnStep.OPEN` 으로 시작한다 — 룰북이
        "The player who goes first cannot draw during the Draw Phase of
        their first turn" 이라고 말하므로 뽑을 것이 없다.
        """
        state = GameState.create(
            repository,
            decks=decks,
            life_points=life_points,
            turn_player=first_player,
            seed=seed,
            shuffle=True,
        )
        for seat in (0, 1):
            state.draw(seat, OPENING_HAND)
        state.turn.set_phase(Phase.DRAW)
        return cls(
            state=state,
            priority=PriorityState.idle(
                turn_player=first_player, phase=Phase.DRAW
            ),
            step=TurnStep.OPEN,  # 선공 첫 턴은 뽑지 않는다
            first_player=first_player,
        )

    # ------------------------------------------------------------------
    # 지금 누구 차례인가
    # ------------------------------------------------------------------
    @property
    def turn_player(self) -> int:
        return self.state.turn.turn_player

    @property
    def to_act(self) -> int:
        """
        **지금 행위를 고를 사람.**

        우선권이 열려 있으면 그것을 쥔 사람이고, 아니면 턴 플레이어다.
        """
        seat = self.priority.holder.seat
        return seat if seat is not None else self.turn_player

    @property
    def is_over(self) -> bool:
        return self.state.result is not None

    @property
    def result(self) -> "DuelResult | None":
        return self.state.result

    def view(self, seat: int) -> GameStateView:
        """그 자리에서 **보이는 만큼**의 판."""
        return GameStateView.from_state(self.state, viewer=seat)

    # ------------------------------------------------------------------
    # 후보
    # ------------------------------------------------------------------
    def legal_actions(self, seat: "int | None" = None) -> LegalActions:
        """
        지금 이 자리에서 **허가가 난** 행위들.

        ``UNKNOWN`` 은 후보가 아니다. 규칙 계층이 "모른다" 고 한 것을
        후보에 넣으면, 고르는 쪽은 그것이 합법인 줄 알게 된다.
        """
        seat = self.to_act if seat is None else seat
        if self.is_over:
            return LegalActions(seat)

        allowed: list[PlayerAction] = []
        withheld: list[WithheldAction] = []

        if self.step is TurnStep.DRAW_PENDING:
            # 드로우가 남아 있으면 그것 말고는 아무것도 고를 수 없다.
            # 드로우는 **선택이 아니라 규칙**이므로 행위 목록에 넣지 않고
            # :meth:`advance` 가 수행한다.
            return LegalActions(seat, (), ())

        validator = ActionValidator(self.view(seat))

        # **응답 창이 열려 있으면 판을 바꾸는 후보를 내지 않는다**
        # (Phase 3-E-11). 체인은 효과 발동의 사슬이고, 소환 · 세트 · 공격은
        # 발동이 아니므로 체인에 끼어들 수 없다 (RULE-CHAIN-011 —
        # "Summoning a monster, Tributing, changing a monster's battle
        # position and paying costs are not effect activations").
        #
        # 그런데 **발동은 끼어들 수 있다** (Phase 3-E-12). 그래서 창이 열려
        # 있고 이 자리가 그 창을 쥐고 있으면 발동 후보를 낸다 — 적법성은
        # ``_activation_actions`` 의 세 관문이 정하고, 그 중 하나가
        # ``ActivationTimingChecker`` 다. "창이 열렸으니 무엇이든 된다" 가
        # 아니다.
        #
        # 창이 닫혀 있으면 아래 조건이 늘 참이므로 **기존 후보가 한 건도
        # 변하지 않는다.**
        if self.priority.is_open and self.priority.holds(seat):
            allowed.extend(self._activation_actions(seat, validator))
        elif seat == self.turn_player and not self.priority.is_open:
            for card in self.state.player(seat).hand:
                # 패의 한 장이 **여러 후보**가 된다 — 소환 · 몬스터 세트 ·
                # 마법/함정 세트. 어느 것이 되는지는 검증기가 말한다
                # (여기서 카드 종류를 보고 미리 거르지 않는다 — 걸러 두면
                # 규칙이 두 곳에 적히고 둘이 갈라진다).
                for build in (
                    PlayerAction.normal_summon,
                    PlayerAction.set_monster,
                    PlayerAction.set_spell_trap,
                ):
                    candidate = build(actor=seat, source=card.instance_id)
                    if (
                        validator.validate(candidate).validity
                        is ActionValidity.VALID
                    ):
                        allowed.append(candidate)
            allowed.extend(self._attack_actions(seat, validator))
            allowed.extend(self._activation_actions(seat, validator))

        # 흐름을 움직이는 둘은 **검증기가 아니라 흐름 계층**이 답한다.
        # 검증기는 ``GameStateView`` 만 보는데, 우선권과 진행은 판 밖에
        # 살기 때문이다 (모듈 설명).
        flow, held = self._flow_actions(seat)
        allowed.extend(flow)
        withheld.extend(held)

        withheld.extend(self._withheld_board_actions(seat, validator))
        return LegalActions(seat, tuple(allowed), tuple(withheld))

    def _attack_actions(self, seat: int, validator: ActionValidator):
        """
        지금 **허가가 나는 공격들** (Phase 3-E-1-B).

        공격자 × 대상의 짝을 전부 만들어 **검증기에게 하나씩 물어본다** —
        "몬스터가 있으면 공격할 수 있다" 고 여기서 가정하지 않는다. 표시
        형식 · 공격권 · 첫 턴 · 다이렉트 조건은 전부 검증기의 몫이고, 그래야
        규칙이 한 곳에만 있다.

        대상이 없을 때만 다이렉트 어택을 만드는 것이 아니라 **언제나 만들고
        검증기가 거른다.** 조건을 두 곳에 적으면 둘이 갈라진다
        (RULE-BATTLE-013 은 ``_OpponentHasNoMonsters`` 하나가 본다).
        """
        opponent = 1 - seat
        targets = [
            card.instance_id
            for zone in BATTLE_TARGET_ZONES
            for card in self.state.player(opponent).zone(zone)
        ]

        allowed: list[PlayerAction] = []
        for zone in BATTLE_TARGET_ZONES:
            for attacker in self.state.player(seat).zone(zone):
                candidates = [
                    PlayerAction.attack(
                        actor=seat,
                        source=attacker.instance_id,
                        target=ActionTarget.instance(target),
                    )
                    for target in targets
                ]
                candidates.append(
                    PlayerAction.attack_directly(
                        actor=seat, source=attacker.instance_id
                    )
                )
                for action in candidates:
                    if (
                        validator.validate(action).validity
                        is ActionValidity.VALID
                    ):
                        allowed.append(action)
        return allowed

    def _activation_actions(self, seat: int, validator: ActionValidator):
        """
        지금 **허가가 나는 효과 발동들** (Phase 3-E-3).

        관문은 셋이고 셋 다 통과해야 후보가 된다. **그 셋을 여기서 세우지
        않는다** — :meth:`_activation_gate` 하나가 세우고, ``apply`` 도 같은
        것을 부른다 (Phase 3-E-13). 관문을 두 곳에 적었던 동안 둘이 서로 다른
        판을 읽었고, 그것이 STRUCTURAL-134 였다.

        셋을 합치지 않는 이유: 1번(``ActionValidator``)은 "규칙이 허락하는가"
        이고 3번(``can_activate``)은 "우리가 할 수 있는가" 다. 합치면 구현이
        없는 카드가 **규칙 위반**으로 읽히고, 그것은 거짓이다 (ADR-006).

        여기서 거르는 것 셋은 **이 Phase 의 범위**이고 규칙이 아니다.

        ``체인이 비어 있을 때만``
            RULE-CHAIN-004 — 스펠 스피드 1 은 "cannot be activated in
            response to any other effects". 체인은 ``GameState`` 밖에 살고
            검증기는 관측만 읽으므로 (ADR-007) 체인을 들고 있는 이쪽이 본다.
        ``비용이 없는 효과만``
            비용을 치른 뒤 발동이 깨지면 되돌릴 방법이 없다 (ADR-008 이
            일반 rollback 을 미뤄 두었다). 등록된 16개 효과 전부 비용이
            없으므로 (STRUCTURAL-120) 지금 이 관문은 아무것도 거르지
            않는다 — 비용이 생기는 날 걸리게 **먼저** 둔다.
        **대상이 필요한 효과도 후보가 된다** (Phase 3-E-4). 대상 하나하나가
        **다른 후보**다 — ``@primary=A`` 와 ``@primary=B`` 는 다른 수이고,
        하나로 뭉치면 AI 가 무엇을 고를지 말할 수 없다.

        후보 목록은 :func:`~engine.target_bridge.target_combinations` 가
        만들고, 그것도 후보를 세는 코드를 새로 쓰지 않는다 —
        ``TargetResolver.candidates`` 를 그대로 쓴다. 그 함수가 이 모듈이
        아니라 다리 쪽에 있는 이유는 후보를 세려면 ``engine.effect`` 와
        ``engine.condition`` 을 읽어야 하고, 듀얼 루프는 그것을 직접 읽지
        않기 때문이다 (``test_e_the_duel_makes_no_rules_of_its_own``).

        ``비용이 없는 효과만``
            비용을 치른 뒤 발동이 깨지면 되돌릴 방법이 없다 (ADR-008 이
            일반 rollback 을 미뤄 두었다). 등록된 16개 효과 전부 비용이
            없으므로 (STRUCTURAL-120) 지금 이 관문은 아무것도 거르지
            않는다 — 비용이 생기는 날 걸리게 **먼저** 둔다.
        """
        allowed: list[PlayerAction] = []
        for card in self._activation_sources(seat):
            for effect_ref in activatable_effects(card.card_id):
                definition = self._activator.definitions.definition_for(effect_ref)
                if definition is None:  # pragma: no cover - 목록이 보증한다
                    continue
                if definition.cost.costs:
                    continue
                for targets in target_combinations(
                    self.state, seat, definition, card.instance_id
                ):
                    candidate = PlayerAction.activate_effect(
                        actor=seat,
                        source=card.instance_id,
                        effect_ref=effect_ref,
                        targets=targets,
                    )
                    try:
                        selections = selections_for(definition, candidate)
                    except TargetBridgeError:  # pragma: no cover - 위에서 맞춰 만든다
                        continue
                    if (
                        self._activation_gate(
                            candidate, validator=validator, selections=selections
                        ).validity
                        is not ActionValidity.VALID
                    ):
                        continue
                    allowed.append(candidate)
        return allowed

    def _activation_sources(self, seat: int):
        """
        발동이 **출발할 수 있는 자리들** (Phase 3-E-14).

        패 하나였다가 둘이 되었다. 세트해 둔 마법 · 함정도 발동의 출발지이고
        (RULE-SPELLTRAP-012 · 007 · 009), 그 자리를 아예 보지 않으면 **어떤
        관문도 판정할 기회를 얻지 못한다.**

        **여기서 거르지 않는다.** 뒷면인지 · 마법인지 · 속공인지 · 함정인지는
        전부 규칙이고, 그 판정은 :meth:`_activation_gate` 의 몫이다. 여기서
        미리 걸러 두면 규칙이 두 곳에 적히고 둘이 갈라진다 — Phase 3-E-13 이
        고친 것이 바로 그것이다.

        그래서 세트된 **속공 마법과 함정도 여기서는 나온다.** 관문이 그것을
        ``UNKNOWN`` 으로 막는다 ("세트한 턴" 을 세는 자리가 아직 없다 —
        ``SET_ACTIVATION_MISSING``), 그리고 ``UNKNOWN`` 은 허가가 아니므로
        후보가 되지 않는다. **막는 이유가 기록으로 남는 것**이 "보지도 않는
        것" 과의 차이다.
        """
        player = self.state.player(seat)
        return tuple(player.hand) + tuple(
            card for card in player.zone(Zone.SZONE) if card is not None
        )

    def _activation_gate(
        self,
        action: PlayerAction,
        *,
        validator: ActionValidator,
        selections: tuple,
    ) -> ValidationResult:
        """
        발동 하나에 걸리는 **관문 셋을 한 자리에서** 본다 (Phase 3-E-13).

            1. ``ActionValidator``               규칙 쪽
            2. ``ActivationTimingChecker``       스펠 스피드 (RULE-CHAIN-003 · 004)
            3. ``EffectActivator.can_activate``  구현 쪽 — 등록 · 조건 · 대상

        **왜 한 자리여야 했는가 — STRUCTURAL-134.**
        ``legal_actions`` 와 ``apply`` 가 각자 관문을 세우고 있었고, 그 둘이
        보는 **판이 달랐다.** ``apply`` 는 카드를 필드에 놓은 **뒤에** 발동
        계층을 불렀으므로 발동한 카드가 패를 떠난 판에서 조건을 읽었고,
        그래서 ``legal_actions`` 가 허가한 발동이 ``apply`` 에서 거절되는
        자리가 생겼다 (리로드).

        이제 **같은 함수가 같은 판**을 본다. 후보 생성과 실행이 모두 배치
        **전**의 판에서 이 관문을 지난다.

        왜 배치 전인가 — 배치 뒤에는 **판정이 아예 불가능하다.** 카드가 패를
        떠나면 ``_activation_out_of_scope`` 가 "패가 아니라 … 에서의 발동이다"
        로 범위 밖을 선언하므로, ``ActionValidator`` 는 **어떤 발동에도**
        ``UNKNOWN`` 을 돌려준다 (욕망의 항아리까지 전부). 배치 뒤의 판은
        검증기가 읽을 수 있는 판이 아니다.

        그것이 Phase 3-E-3 이 ``activate`` 에 ``ValidationResult.valid(
        "legal_actions 가 허가한 발동입니다")`` 를 손으로 넣어 줘야 했던
        이유이기도 하다. 지금 그 자리에는 **실제 검증기의 판정**이 들어간다.

        **판정은 두 번 할 수 있고 실행은 한 번만 한다.** 이 함수는 판을 읽기만
        하므로 몇 번 불러도 같은 답이고, 그래서 ``legal_actions`` 와 ``apply``
        가 각각 부르는 것은 중복이 아니라 **독립 검증**이다 — ``apply`` 가
        "``legal_actions`` 를 지나왔을 것" 을 믿지 않는다는 뜻이다.
        """
        verdict = validator.validate(action)
        if verdict.validity is not ActionValidity.VALID:
            return verdict
        # 스펠 스피드는 체인을 보고, 체인은 ``GameState`` 밖에 산다 (ADR-007).
        timed = ActivationTimingChecker(validator.view).check(
            ActivationTiming(self.chain, self.priority), action
        )
        if timed.validity is not ActionValidity.VALID:
            return timed
        return self._activator.can_activate(
            self.state,
            self.chain,
            action,
            selections=selections,
            authorization=verdict,
        )

    def _flow_actions(self, seat: int):
        allowed: list[PlayerAction] = []
        withheld: list[WithheldAction] = []

        if self.priority.is_open and self.priority.holds(seat):
            allowed.append(PlayerAction.passing(actor=seat))
        elif seat != self.turn_player:
            withheld.append(
                WithheldAction(
                    PlayerActionKind.PASS,
                    "우선권이 열려 있지 않습니다.",
                    missing="우선권을 여는 규칙 (Phase 2-F)",
                )
            )

        if seat == self.turn_player and not self.priority.is_open:
            plan = TurnProgressor().plan(self.state)
            if plan.permits_transition:
                allowed.append(PlayerAction.end_phase(actor=seat))
            else:
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.END_PHASE,
                        plan.verdict.reason,
                        missing="; ".join(plan.unresolved_rules) or None,
                    )
                )
        return allowed, withheld

    def _withheld_board_actions(self, seat: int, validator: ActionValidator):
        """
        **왜 마법 · 함정을 발동할 수 없는가.** 한 번만 적는다.

        같은 이유가 패의 카드마다 반복되므로 종류별로 하나씩만 남긴다.
        """
        held: list[WithheldAction] = []
        for card in self.state.player(seat).hand:
            action = PlayerAction.activate_card(actor=seat, source=card.instance_id)
            verdict = validator.validate(action)
            if verdict.validity is ActionValidity.VALID:  # pragma: no cover
                continue
            held.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_CARD,
                    verdict.reason,
                    missing=verdict.missing_rule,
                )
            )
            break
        return held

    # ------------------------------------------------------------------
    # 적용
    # ------------------------------------------------------------------
    def apply(self, action: PlayerAction) -> DuelStep:
        """
        행위 하나를 적용한다. **허가가 난 것만 받는다.**

        허가는 :meth:`legal_actions` 와 **같은 자리**에서 다시 묻는다 —
        목록을 만든 뒤 판이 바뀌었을 수 있고, 목록을 믿고 적용하면 그
        사이의 변화를 놓친다.
        """
        if not isinstance(action, PlayerAction):
            raise TypeError(f"PlayerAction 이 필요합니다: {type(action).__name__}")
        if self.is_over:
            return DuelStep(
                action, False, ValidationCode.DUEL_ALREADY_OVER, "이미 끝난 듀얼입니다."
            )

        legal = self.legal_actions(action.actor)
        if action not in legal.allowed:
            return DuelStep(
                action,
                False,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{action.kind.value} 는 지금 허가된 행위가 아닙니다.",
            )

        if action.kind is PlayerActionKind.PASS:
            return self._apply_pass(action)
        if action.kind is PlayerActionKind.END_PHASE:
            return self._apply_end_phase(action)
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
            # **판을 바꾸는 행위와 흐름을 바꾸는 행위를 섞지 않는다**
            # (STRUCTURAL-55). 발동의 결과물은 ``StateDelta`` 만이 아니라
            # ``Chain`` 이기도 하므로 ``ActionHandler`` 에 끼울 수 없다.
            return self._apply_activation(action)
        return self._apply_board(action)

    def _apply_pass(self, action: PlayerAction) -> DuelStep:
        """
        패스 하나. **둘 다 패스했으면 체인을 푼다** (RULE-CHAIN-001).

            "Both players continue to add effects to the Chain until **they
            both wish to add nothing else**, then you resolve the outcome in
            reverse order."

        그래서 한 번의 패스로는 풀지 않는다. 한쪽이 패스하면 우선권이
        맞은편으로 가고, 거기서도 패스해야 "둘 다 그만하겠다" 가 된다.

        **``both_passed`` 는 괄호 없이 읽는다.** ``@property`` 인데 예전에는
        ``both_passed()`` 라고 불렀고, 그러면 bool 이 아니라 메서드 객체가
        참으로 평가되어 한 번의 패스로 기회가 닫혔다. 이 자리는 우선권이
        한 번도 열리지 않아 **도달 불가**였으므로 아무도 밟지 않았다
        (Phase 3-E-10 이 죽은 분기로 기록했다).
        """
        self.priority = self.priority.passed()

        loop = self._response_loop
        response = self._response_state()
        if not loop.ready_to_resolve(response).permits_execution:
            return DuelStep(
                action, True, ValidationCode.OK, "우선권을 넘겼습니다."
            )
        return self._resolve_chain(action, loop, response)

    def _resolve_chain(
        self, action: PlayerAction, loop: ResponseLoop, response: ResponseState
    ) -> DuelStep:
        """
        쌓인 체인을 푼다. **기존 해결기에 넘긴다** — 여기서 풀지 않는다.

        ``ResponseLoop.resolve`` 가 ``ChainResolver.resolve_all`` 을 부르고,
        푼 뒤 기회를 닫는다 (``AFTER_CHAIN_RULE``). 체인이 끝난 뒤 우선권이
        누구에게 가는지는 여전히 정하지 않는다 (STRUCTURAL-34 의 나머지).
        """
        resolution = loop.resolve(self.state, response, self._resolver)
        self.chain = resolution.state.chain
        self.priority = resolution.state.priority
        if self.chain.is_complete:
            # 다음 발동이 체인 1 부터 시작하도록 비운다.
            self.chain = Chain()

        # **해결됐든 아니든 놓인 마법은 필드를 떠난다** (RULE-SPELLTRAP-002).
        self._retire_pending()

        steps = resolution.steps
        if not resolution.fully_resolved:
            last = steps[-1]
            return DuelStep(action, False, last.code, last.reason)
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            steps[-1].reason,
            result=self._check_end(),
        )

    def _place_activated(self, action: PlayerAction):
        """
        발동한 카드를 앞면으로 만든다 — **출발지가 정한다** (Phase 3-E-14).

        패에서면 옮겨 놓고 (RULE-SPELLTRAP-002), 마법 & 함정 존에서면 그
        자리에서 돌린다 (RULE-SPELLTRAP-012). 둘 다 해결 뒤 묘지로 가는 길은
        같으므로 ``pending_spells`` 와 뒷정리는 하나로 쓴다.

        자리를 못 읽으면 **고르지 않는다** — ``place`` 가 그 사실을
        ``SpellActivationError`` 로 말하게 둔다.
        """
        instance = self.state.find_instance(action.source)
        if instance is not None and instance.zone is Zone.SZONE:
            return self._placement.reveal(self.state, action.source, action.actor)
        return self._placement.place(self.state, action.source, action.actor)

    def _retire_pending(self) -> None:
        """대기 중이던 마법을 전부 묘지로 보낸다. 카드를 옮기는 일은 배치 계층이 한다."""
        pending, self.pending_spells = self.pending_spells, ()
        for placed in pending:
            self._placement.retire(self.state, placed)

    def _apply_end_phase(self, action: PlayerAction) -> DuelStep:
        progressed = TurnProgressor().advance(self.state)
        if progressed.status is not ProgressionStatus.ADVANCED:
            return DuelStep(
                action,
                False,
                progressed.verdict.code,
                progressed.verdict.reason,
            )
        self.priority = PriorityState.idle(
            turn_player=self.state.turn.turn_player, phase=self.state.turn.phase
        )
        if self.state.turn.phase is Phase.DRAW:
            self.step = TurnStep.DRAW_PENDING
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            f"{self.state.turn.phase.value} 로 넘어갔습니다.",
            result=self._check_end(),
        )

    def _apply_board(self, action: PlayerAction) -> DuelStep:
        executed = self._executor.execute(
            self.state, action, authorization=ValidationResult.valid()
        )
        if executed.status is not ActionStatus.EXECUTED:
            return DuelStep(action, False, executed.code, executed.reason)
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            executed.reason,
            result=self._check_end(),
        )

    def _apply_activation(self, action: PlayerAction) -> DuelStep:
        """
        효과 발동 하나. **기존 계층만 부른다** (Phase 3-E-3).

        공식 조항이 순서를 정한다.

            RULE-SPELLTRAP-002 — "announce its activation to your opponent,
            **placing it face-up on the field**. If the activation succeeds,
            then you **resolve** the effect written on the card. After
            resolving the effect, **send the card to the Graveyard**."

        그래서 다섯 걸음이다.

            ⓪ selections_for                ActionTarget → TargetSelection
            ① _activation_gate              세 관문 — **판을 바꾸기 전에**
            ② EffectActivator.activate      비용 · 체인 링크 · 대상
            ③ NormalSpellPlacement.place    패 → 마법&함정 존 (앞면)
            ④ ChainResolver.resolve_top     효과 해결 (``_resolve_chain``)
            ⑤ NormalSpellPlacement.retire   → 묘지 (``_retire_pending``)

        ⓪이 앞에 있는 이유: 환전은 판을 읽지도 바꾸지도 않으므로, 모양이
        틀렸으면 아무것도 건드리기 전에 거절할 수 있다 (Phase 3-E-4).

        **①과 ②가 ③ 앞으로 왔다** (Phase 3-E-13 · STRUCTURAL-134)
        ---------------------------------------------------------
        Phase 3-E-3 은 ③을 먼저 두고, 깨지면 그 하나를 되돌렸다
        (``NormalSpellPlacement.restore``). 조항이 "놓고 나서 발동이 성립한다"
        고 적기 때문이었다. 그런데 **판정을 어디서 하는가는 그 조항이 정하지
        않는다.** 조항은 "발동할 수 있는 마법" 을 전제하고 시작하는 문장이고
        ("To use a Normal Spell Card, …"), 적법한가를 묻는 자리는 그 앞이다.

        그리고 배치 뒤에는 **판정이 불가능하다.** 카드가 패를 떠나면
        ``ActionValidator`` 가 모든 발동에 ``UNKNOWN`` 을 돌려준다
        (``_activation_gate`` 의 설명). 그래서 예전 순서에서는 손으로 만든
        허가를 ``activate`` 에 넣어 줄 수밖에 없었고, ``legal_actions`` 와
        ``apply`` 가 **서로 다른 판**에서 조건을 읽게 되었다 — 그것이
        STRUCTURAL-134 이었다.

        순서를 바꿔도 **조항이 말하는 순서는 지켜진다.** ③은 여전히 ④보다
        앞이다 — 카드는 해결되기 전에 앞면으로 필드에 놓이고, 상대가 응답
        기회를 받는 시점에도 이미 필드에 있다 (RULE-CHAIN-001).

        **되돌릴 자리가 사라졌다.** ①이 거절하면 판은 **한 번도** 바뀌지
        않는다. ``restore`` 가 필요했던 경우가 없어진 것이고, 이것은
        rollback 계층을 만든 것이 아니라 **만들 필요를 없앤 것**이다
        (ADR-008 은 그대로 미뤄져 있다).

        ④가 깨지면 **되돌리지 않는다.** 발동은 이미 성립했고, 해결되지 않은
        효과의 카드가 묘지로 가는 것은 규칙대로다 (불발). 다만 "해결했다" 고
        적지 않는다 — 이유를 그대로 전한다.
        """
        definition = self._activator.definitions.definition_for(action.effect_ref)
        if definition is None:
            return DuelStep(
                action,
                False,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"{action.effect_ref} 의 정의가 등록되어 있지 않습니다.",
            )
        try:
            # **판을 건드리기 전에** 환전한다. 모양이 맞지 않으면 아무것도
            # 바꾸지 않고 거절한다 (Phase 3-E-4).
            selections = selections_for(definition, action)
        except TargetBridgeError as error:
            return DuelStep(
                action, False, ValidationCode.TARGET_COUNT_MISMATCH, str(error)
            )

        # ① **판을 바꾸기 전에** 세 관문을 지난다. ``legal_actions`` 가 쓰는
        # 것과 **같은 함수**이고 **같은 판**이다 (STRUCTURAL-134).
        #
        # ``legal_actions`` 를 지나왔다고 **믿지 않는다.** ``apply`` 는 공개
        # 입구이고, 아무 ``PlayerAction`` 이나 들어올 수 있다.
        gate = self._activation_gate(
            action,
            validator=ActionValidator(self.view(action.actor)),
            selections=selections,
        )
        if gate.validity is not ActionValidity.VALID:
            return DuelStep(action, False, gate.code, gate.reason)

        # ② 비용과 체인 링크. ``gate`` 는 방금 이 판에서 세 관문이 모두 낸
        # 판정이므로 그대로 허가로 넘긴다 — 손으로 만든 "허가했다" 가 아니다.
        activated = self._activator.activate(
            self.state,
            self.chain,
            action,
            selections=selections,
            authorization=gate,
        )
        if not activated.activated:
            # 여기까지 오는 길은 ``_activation_gate`` 가 ``VALID`` 를 낸 뒤
            # ``activate`` 가 같은 판에서 다른 답을 내는 경우뿐이다. 판을
            # 바꾸지 않았으므로 **되돌릴 것이 없다.**
            return DuelStep(action, False, activated.code, activated.reason)

        # ③ 이제 앞면으로 만든다 (RULE-SPELLTRAP-002 — "placing it face-up on
        # the field"). 발동이 성립한 뒤이므로 되돌릴 자리가 아니다.
        #
        # **출발지가 둘이다** (Phase 3-E-14). 패에서 발동하면 옮겨 놓고
        # (``place``), 세트해 둔 것이면 그 자리에서 돌린다 (``reveal``,
        # RULE-SPELLTRAP-012). 어느 쪽인지는 **판이 말한다** — 여기서 카드
        # 종류를 보고 정하지 않는다.
        try:
            placed = self._place_activated(action)
        except SpellActivationError as error:
            # 관문이 통과시킨 카드가 패에 없다 — 비용이 그것을 옮겼을 때만
            # 닿는다. **비용은 이미 치러졌고 되돌리지 않는다** (ADR-008).
            # 체인은 값이므로 ``self.chain`` 에 반영하지 않는다 — 링크가
            # 남지 않는다. 숨기지 않고 이유를 그대로 전한다.
            return DuelStep(
                action,
                False,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                f"발동한 카드를 필드에 놓을 수 없습니다: {error}",
            )

        self.chain = activated.chain

        # ⑤ **여기서 해결하지 않는다** (Phase 3-E-11 · RULE-CHAIN-001).
        #
        #     "If a card's effect is activated, the opponent is **always**
        #      given a chance to respond with a card effect of their own,
        #      creating a Chain."
        #
        # 그래서 링크를 쌓은 뒤 **상대에게** 응답 기회를 연다. 기회를 여는
        # 도구는 이미 있다 — ``ResponseLoop.opened`` 가 "부르는 쪽이 값으로
        # 연다" 고 적어 두었고, 이 자리가 그 부르는 쪽이다.
        #
        # 놓인 카드는 아직 묘지로 가지 않는다. 해결이 끝나는 자리가
        # ``_resolve_chain`` 으로 밀려났으므로 ``pending_spells`` 가 그때까지
        # 들고 있는다.
        self.pending_spells = self.pending_spells + (placed,)
        self.priority = ResponseLoop.opened(
            self.chain,
            1 - action.actor,
            turn_player=self.state.turn.turn_player,
            phase=self.state.turn.phase,
            reason="발동에 응답 (RULE-CHAIN-001)",
        ).priority
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            f"{activated.reason} 상대의 응답을 기다립니다.",
        )

    # ------------------------------------------------------------------
    # 규칙이 하는 일 — 고르는 것이 아니다
    # ------------------------------------------------------------------
    def advance(self) -> "DuelStep | None":
        """
        **고르지 않아도 일어나는 일**을 한 걸음 진행한다. 없으면 ``None``.

        지금은 드로우 페이즈의 드로우 하나다. 그것을 행위 목록에 넣지 않는
        이유는 **고르는 일이 아니기 때문**이다 — 뽑지 않겠다고 고를 수 없다.
        """
        if self.is_over or self.step is not TurnStep.DRAW_PENDING:
            return None

        seat = self.turn_player
        if not self.state.player(seat).deck:
            # 룰북: "A player with no cards left in their Deck and unable to
            # draw loses the Duel."
            result = self.state.set_result(
                winner=1 - seat, reason=f"P{seat}: {LOSS_BY_DECK_OUT}"
            )
            self.step = TurnStep.OPEN
            return DuelStep(
                PlayerAction.passing(actor=seat),
                True,
                ValidationCode.OK,
                result.reason,
                result=result,
            )

        self.state.draw(seat, 1)
        self.step = TurnStep.OPEN
        return DuelStep(
            PlayerAction.passing(actor=seat),
            True,
            ValidationCode.OK,
            f"P{seat} 가 1장 뽑았습니다.",
        )

    def _check_end(self) -> "DuelResult | None":
        """
        룰북의 패배 조건을 본다. **이기는 조건이 아니라 지는 조건**이다 —
        한쪽이 지면 다른 쪽이 이긴다.
        """
        if self.state.result is not None:
            return self.state.result
        for seat in (0, 1):
            if self.state.player(seat).life_points <= 0:
                return self.state.set_result(
                    winner=1 - seat, reason=f"P{seat}: {LOSS_BY_LIFE}"
                )
        return None

    # ------------------------------------------------------------------
    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        where = f"T{self.state.turn.turn_number} P{self.turn_player} {self.state.turn.phase.value}"
        if self.is_over:
            return f"{where} — 끝: {self.result.reason}"
        return f"{where} — {self.to_act} 차례"


__all__ = [
    "Duel",
    "DuelError",
    "DuelStep",
    "LegalActions",
    "WithheldAction",
    "TurnStep",
    "OPENING_HAND",
    "LOSS_BY_LIFE",
    "LOSS_BY_DECK_OUT",
]
