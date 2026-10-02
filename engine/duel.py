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
from engine.chain import Chain, ChainResolutionStatus
from engine.game_state_view import GameStateView
from engine.priority import PriorityState
from engine.state.game_state import DEFAULT_LIFE_POINTS, DuelResult, GameState
from engine.spell_activation import (
    NormalSpellPlacement,
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

        if seat == self.turn_player:
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

        관문이 **둘**이고, 둘 다 통과해야 후보가 된다.

        1. :class:`~engine.action_validation.ActionValidator` — 규칙 쪽.
           턴 플레이어 · 컨트롤러 · 패 · 메인 페이즈 · 빈 칸 · 통상 마법인가.
        2. :meth:`~engine.activation.EffectActivator.can_activate` — 구현 쪽.
           구현이 등록되어 있는가 (``EXECUTABLE``) · 발동 조건이 참인가 ·
           대상이 쓸 수 있는가. **판을 읽기만 한다.**

        둘을 합치지 않는 이유: 1번은 "규칙이 허락하는가" 이고 2번은 "우리가
        할 수 있는가" 다. 합치면 구현이 없는 카드가 **규칙 위반**으로
        읽히고, 그것은 거짓이다 (ADR-006).

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
        ``대상이 없는 효과만``
            ``PlayerAction`` 에서 :class:`
            ~engine.effect.target.TargetSelection` 으로 가는 길이 없다
            (STRUCTURAL-121). 길이 없는 것을 추측해서 만들지 않는다.
        """
        if not self.chain.is_empty:
            # RULE-CHAIN-004 — 지금 범위(통상 마법)는 체인에 얹지 못한다.
            return []

        allowed: list[PlayerAction] = []
        for card in self.state.player(seat).hand:
            for effect_ref in activatable_effects(card.card_id):
                definition = self._activator.definitions.definition_for(effect_ref)
                if definition is None:  # pragma: no cover - 목록이 보증한다
                    continue
                if definition.cost.costs or definition.targets:
                    continue
                candidate = PlayerAction.activate_effect(
                    actor=seat, source=card.instance_id, effect_ref=effect_ref
                )
                verdict = validator.validate(candidate)
                if verdict.validity is not ActionValidity.VALID:
                    continue
                if (
                    self._activator.can_activate(
                        self.state, self.chain, candidate, authorization=verdict
                    ).validity
                    is not ActionValidity.VALID
                ):
                    continue
                allowed.append(candidate)
        return allowed

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
        self.priority = self.priority.passed()
        if self.priority.both_passed():
            self.priority = self.priority.closed("양쪽이 패스했다")
        return DuelStep(action, True, ValidationCode.OK, "우선권을 넘겼습니다.")

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

        그래서 네 걸음이다.

            ① NormalSpellPlacement.place    패 → 마법&함정 존 (앞면)
            ② EffectActivator.activate      비용 · 체인 링크
            ③ ChainResolver.resolve_top     효과 해결
            ④ NormalSpellPlacement.retire   → 묘지

        **되돌릴 수 있는 자리를 하나로 줄였다.** ①은 판을 바꾸므로, ②가
        깨지면 ①의 역 하나만 하면 된다 (:meth:`
        ~engine.spell_activation.NormalSpellPlacement.restore`). ②를 ① 앞에
        두지 않은 이유는 조항이 "놓고 나서 발동이 성립한다" 고 적기 때문이다.

        ③이 깨지면 **되돌리지 않는다.** 발동은 이미 성립했고, 해결되지 않은
        효과의 카드가 묘지로 가는 것은 규칙대로다 (불발). 다만 "해결했다" 고
        적지 않는다 — 이유를 그대로 전한다.
        """
        placed = self._placement.place(self.state, action.source, action.actor)

        activated = self._activator.activate(
            self.state,
            self.chain,
            action,
            authorization=ValidationResult.valid(
                "legal_actions 가 허가한 발동입니다."
            ),
        )
        if not activated.activated:
            # ①의 역 **하나**. 일반 rollback 이 아니다.
            self._placement.restore(self.state, placed)
            return DuelStep(action, False, activated.code, activated.reason)

        self.chain = activated.chain
        resolved = self._resolver.resolve_top(self.state, self.chain)
        self.chain = resolved.chain

        # 해결됐든 아니든 카드는 필드를 떠난다 (RULE-SPELLTRAP-002).
        self._placement.retire(self.state, placed)
        if self.chain.is_complete:
            # 체인이 끝났다. 다음 발동이 체인 1 부터 시작하도록 비운다 —
            # "체인이 끝난 뒤 우선권이 누구에게 가는가" 는 정하지 않는다
            # (STRUCTURAL-34).
            self.chain = Chain()

        if resolved.status is not ChainResolutionStatus.RESOLVED:
            return DuelStep(action, False, resolved.code, resolved.reason)
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            resolved.reason,
            result=self._check_end(),
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
