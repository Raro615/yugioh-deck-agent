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
from engine.state.rule_usage import RuleActionKind
from engine.target_bridge import (
    TargetBridgeError,
    selections_for,
    target_combinations,
)
from engine.spell_activation import (
    PLACEMENT_SOURCE_ZONES,
    NormalSpellPlacement,
    SpellActivationError,
    activatable_effects,
    duel_activator,
    duel_components,
    duel_resolver,
)
from engine.summon import duel_executor
from engine.turn_progression import ProgressionStatus, TurnProgressor
from engine.validation import ActionValidity, ValidationCode, ValidationResult
from engine.vocabulary import ActivationKind, Phase, Zone


#: 🔴 **강제 · 임의를 판정할 수 없을 때 빠진 것** (Phase 6-AA).
#:
#: 무엇이 모자란지 적는다 — 공식 규칙에 이 구분이 없고 (룰북의
#: ``effect_types`` 가 유발 효과의 발동 시점만 적는다), 카드 텍스트로도
#: 답이 하나로 모이지 않은 경우다. 판이 바뀌어도 풀리지 않고 **근거가
#: 생겨야** 풀리므로 보류의 ``missing`` 에 적는다.
TRIGGER_REQUIREMENT_MISSING = (
    "유발의 강제 · 임의 판정 근거 (Phase 6-AA — 룰북에 그 구분이 없고 "
    "카드 텍스트도 한쪽으로 모이지 않았다)"
)

#: 🔴 **듀얼이 사건 기록을 들고 있지 않을 때 빠진 것** (Phase 6-AA · 6-AB).
#:
#: 유발 후보는 **기록된 사건**에서 나오므로 (Phase 6-Z) 기록이 없으면 꺼낼
#: 것이 없다. 그런데 그것을 조용히 "유발 0건" 으로 두면 읽는 쪽이 "유발이
#: 없다" 로 읽는다 — 둘은 다른 사실이다.
#:
#: 🔴 **6-AA 가 이것을 ``BLOCKER-6AA-1`` 로 적은 자리는 6-AB 가 닫았다.**
#: 그때는 ``agent.simulation`` 의 ``_fork`` 가 기록하지 않는 한 벌로 바꿔
#: 끼웠고 (``journal=False``), 그래서 **모든 사본**이 이 자리를 밟았다.
#: 6-AB 는 사본에 부모의 사건을 씨앗으로 받은 **새 ``EventJournal``** 을
#: 준다 (``_forked_journal``) — 사본의 전개가 진짜 기록에 남지 않는다는
#: 6-B 의 요구는 그대로 지키면서 역사는 물려받는다.
#:
#: 그래서 이 보류가 남는 자리는 **처음부터 기록 없이 만든 듀얼** 하나다.
#: 없는 역사를 지어내지 않으므로 그 사본도 기록이 없고, 그 사실을 적는다.
TRIGGER_HISTORY_MISSING = (
    "이 듀얼의 사건 기록 (Phase 6-Z — 유발 후보는 기록된 사건에서 나온다)"
)

#: 🔴 **「때 / 경우」 를 판정할 수 없을 때 빠진 것** (Phase 6-AB).
#:
#: 공식 재정이 둘을 다르게 다루는데 (「때」 는 놓친 타이밍이 있고 「경우」 는
#: 없다) 카드 텍스트로 어느 쪽인지 모이지 않은 경우다. 판이 바뀌어도 풀리지
#: 않고 **근거가 생겨야** 풀리므로 보류의 ``missing`` 에 적는다.
TRIGGER_WORDING_MISSING = (
    "유발의 「때 / 경우」 판정 근거 (Phase 6-AB — 룰북에 그 구분이 없고 "
    "카드 텍스트도 한쪽으로 모이지 않았다)"
)

#: 🔴 **강제 유발을 발동할 수 없을 때 빠진 것** (Phase 6-AB).
#:
#: 규칙이 그 처리를 요구하는데 관문이 그 발동을 허가하지 않는다 (조건 ·
#: 비용 · 구현 중 하나). 그때 흐름을 막으면 **영구 대기**가 되므로 막지
#: 않고, 진행의 합법성을 보장하지 못한다는 사실을 적는다.
MANDATORY_TRIGGER_UNPLAYABLE = (
    "강제 유발의 발동 절차 (Phase 6-AB — 규칙이 요구하는데 관문이 허가하지 "
    "않아 이 진행이 규칙대로인지 보장할 수 없다)"
)

#: 전투가 일어나는 존들. 공격자와 대상 모두 여기 있는 카드다.
BATTLE_TARGET_ZONES: tuple[Zone, ...] = (Zone.MZONE, Zone.EMZONE)

#: 패 **밖에서** 발동이 출발할 수 있는 자리들 (Phase 3-E-14 · 6-K).
#:
#: 패는 :meth:`Duel._activation_sources` 가 따로 읽는다 (``player.hand`` 는
#: 존 컨테이너가 아니다). **여기서 거르지 않는다** — 뒷면인지 · 어느 종류인지 ·
#: 그 자리에서 발동할 수 있는지는 전부 규칙이고, 관문이 판정한다.
ACTIVATION_SOURCE_ZONES: tuple[Zone, ...] = (
    Zone.SZONE,
    Zone.MZONE,
    Zone.EMZONE,
)


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
    """
    🔴 **이 행위를 수락했는가** — "원하는 결과가 나왔는가" 가 아니다
    (Phase 6-R 이 이 칸의 뜻을 글로 적었다. 그때까지 설명이 없었고,
    그 공백이 바로 아래의 혼동을 만들었다).

    세 가지가 **서로 다른 사실**이고, 이 칸은 **첫째만** 말한다.

    ====================  ==================================================
    행위 수락              이 칸. ``False`` 는 "그 행위를 하지 않았다" 다 —
                          판이 그 행위로 바뀌지 않았다는 뜻이다
    체인 등록              :attr:`Duel.chain` 이 말한다 (링크가 쌓였는가)
    효과 해결 · 상태 변경   ``EventJournal`` 과 ``GameState`` 가 말한다.
                          적용된 것만 ``EffectEvent`` 로 남는다
    ====================  ==================================================

    그래서 **적법한 ``PASS`` 는 언제나 ``accepted=True``** 다. 그 패스가 푼
    체인 안에서 어떤 링크가 불발되었더라도 — 불발은 **링크의 결과**이고
    패스라는 행위는 분명히 일어났다. 그 경우 :attr:`code` 와 :attr:`reason`
    이 불발 사유를 그대로 들고 온다 (Phase 6-R, :meth:`Duel._resolve_chain`).

    🔴 **``accepted=True`` 가 "효과가 적용되었다" 를 뜻하지 않는다.** 무엇이
    적용되었는지는 ``EventJournal`` 에만 있다 — 거기에 ``EffectEvent`` 가
    없으면 아무것도 적용되지 않은 것이다.
    """
    code: ValidationCode
    """
    이 걸음의 **이유 코드**.

    ``accepted`` 가 거짓이면 "왜 거절했는가" 다. 참이면 보통
    :attr:`~engine.validation.ValidationCode.OK` 이지만, 체인을 푼 패스에서
    **링크가 불발되었으면 그 사유 코드**가 온다 — 행위는 수락되었고 링크가
    적용되지 않았다는 두 사실을 함께 전하는 자리다 (Phase 6-R).
    """
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
    journal: object | None = None
    """
    이 듀얼의 **사건 기록** (Phase 6-B). ``EventJournal`` 또는 ``None``.

    🔴 **주석이 ``object | None`` 인 것은 의도다.** :mod:`engine.duel` 은
    ``engine.effect`` 를 import 하지 않고
    (``test_e_the_duel_makes_no_rules_of_its_own`` 이 AST 로 고정한다),
    ``EventJournal`` 은 ``engine/effect/journal.py`` 에 산다. 그래서 타입을
    이름으로 적지 않고 **값으로만** 들고 있는다 — 만드는 일은
    :func:`engine.spell_activation.duel_components` 가 한다.

    🔴 **기록은 관찰 계층이고, 진실의 원천은 여전히 :attr:`state` 다.**
    이 칸은 ``state_hash()`` 에 들어가지 않는다 (``chain`` · ``priority``
    와 같은 이유 — 역사는 판의 모양이 아니다).

    기본값이 ``None`` 인 이유: ``Duel(state=…, priority=…)`` 로 직접 만드는
    기존 호출이 **한 글자도 바뀌지 않아야** 한다. 그때는 기록되지 않고,
    동작은 예전과 같다. :meth:`start` 로 만들면 기록이 켜진다.
    """
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

    triggers: object | None = None
    """
    **사건에서 유발 후보를 만드는 것** (Phase 6-Z). 또는 ``None``.

    생략하면 유발 발동이 ``legal_actions`` 에 오르지 않는다 — 6-Z 이전과
    같은 동작이다. 🔴 **없는 것을 기본값으로 메꾸지 않는다** (ADR-006 과
    같은 규율).

    기대하는 모양은 하나다::

        offers(duel, seat) -> 제안들

    돌려주는 것마다 ``effect_ref`` · ``source`` · ``event_key`` 가 있어야
    한다 (그 셋이 이 칸이 아는 전부다 — 타입 이름은 모른다). ``event_key`` 는 **그 사건을 가리키는 값**이고, 같은 사건으로 두
    번 발동하는 것을 막는 데 쓴다 (:attr:`consumed_events`).

    🔴 **타입을 이름으로 적지 않는다.** :mod:`engine.duel` 은
    ``engine.effect`` 도 ``integration`` 도 import 하지 않는다 (ADR-007 ·
    ``test_e_the_duel_makes_no_rules_of_its_own``). 그래서 이 칸은
    ``journal`` 과 같이 **값으로만** 들고 있는다.

    후보를 **묻는 것만으로는 아무것도 바뀌지 않는다** — 이 칸을 읽는
    :meth:`_trigger_actions` 는 판도 사건도 소비하지 않는다.
    """
    timing_floor: int = 0
    """
    **이번 페이즈가 시작될 때의 기록 번호** (Phase 6-AA).

    이 번호보다 **앞의** 사건은 지나간 시점의 것이므로 유발 후보를 열지
    않는다. 담는 것은 ``JournalEvent.sequence`` 와 같은 축의 값이다 — 기록이
    identity 로 쓰는 번호 그대로이고 (``EventJournal`` 의 설명), 새 식별자를
    만들지 않는다.

    🔴 **근거는 룰북의 페이즈 구조다.** *"After a card's activation, and at
    the end of each phase or step, Priority passes to the opponent"*
    (TURN PLAYER'S PRIORITY). 메인 페이즈 1 에 일어난 사건의 유발을 배틀
    페이즈에 발동하는 것은 그 사건의 시점이 아니다.

    🔴 **실측으로 고친 결함이다.** 6-Z 까지 이 칸이 없었고,
    :meth:`_trigger_offers` 가 기록 **전체**를 매번 다시 펼쳤다. 그래서
    메인 페이즈 1 의 일반 소환 유발이 같은 턴의 BATTLE · MAIN2 · END 에서,
    그리고 다음 턴의 DRAW · STANDBY 에서까지 관문을 **통과했다**
    (``gate=valid/ok``, 보고서 §4 의 실측).

    🔴 **페이즈 안에서의 만료는 이것으로 판정하지 않는다** — 그것이
    :attr:`declined_events` 와 :meth:`_window_admits` 의 일이다. 이 바닥은
    **페이즈 경계**만 본다: 둘은 다른 축이고, 어느 한쪽으로 다른 쪽을 흉내
    내면 적법한 기회를 닫거나 지나간 기회를 연다.

    🔴 6-AA 가 이 자리를 ``BLOCKER-6AA-2`` 로 적으며 **근거 없는 일괄
    규칙**("다음 행동이면 만료") 을 만들지 않은 것은 옳았다. 그 규칙을
    세웠다면 「경우」 효과의 적법한 기회를 닫았을 것이다. 6-AB 보완이 그
    자리를 **일괄 규칙이 아닌 방식**으로 채웠다 — :attr:`declined_events` 는
    그 자리가 **실제로 기회를 받고 다른 것을 한** 경우만 닫는다.
    """
    declined_events: frozenset = frozenset()
    """
    **그 자리가 적법하게 포기한 기회들** (Phase 6-AB 보완).

    담는 것은 ``(event_key, effect_ref, source, seat)`` **네 짝**이다 —
    :meth:`_consumption_key` 의 세 짝에 자리를 더한 것이다.

    🔴 **왜 세 짝으로는 모자라는가.** 처음에는 ``(event_key, seat)`` 두
    짝으로 적었고, 그러면 한 효과를 포기한 것이 **같은 사건의 다른 효과 ·
    다른 개체**의 기회까지 닫았다 (실측: 임의 유발을 포기한 뒤 같은 사건의
    합성 강제 유발이 "포기했습니다" 로 보류됐다). 6-AA 가 ``consumed_events``
    에서 같은 결함을 고쳤고 (``EffectRef`` 는 개체를 가르지 않는다), 같은
    근거가 여기에도 그대로 적용된다.

    🔴 **자리가 들어간 이유.** 기회는 자리마다 따로 열리므로 (룰북
    ``TURN PLAYER'S PRIORITY``) 한 자리의 포기가 다른 자리의 기회를 닫지
    않는다.

    🔴 **왜 필요한가 — 실측한 결함이다.** 6-AB 까지 「경우」 유발은 같은
    페이즈 안에서 **영원히** 후보였다. 실측: 기르수 소환 뒤 일반 행동을 세
    걸음 하고도 그 유발이 후보에 남았다 (``_timing_is_current`` → ``True``).
    그런데 *"타이밍을 놓치지 않는다"* 는 *"같은 페이즈에서 나중에 마음대로
    발동할 수 있다"* 는 뜻이 **아니다.**

    🔴 **근거.** 공식 Fast Effect Timing 도표는 유발을 **두 자리에서만**
    확인한다 — 체인을 시작하지 않는 행위 뒤, 그리고 체인이 해결된 뒤. 그
    확인 자리에서 양쪽이 패스하면 판은 **open state** 로 돌아가고, 그때
    열려 있던 창은 닫힌다. 그 자리에서 유발을 집는 대신 **다른 일을 했다면**
    그 자리의 기회는 지나간 것이다.
    (https://www.yugioh-card.com/en/play/fast-effect-timing/)

    🔴 **"다음 행동이면 무조건 만료" 가 아니다.** 셋이 모두 참일 때만 적는다:

    1. 그 자리가 그 사건의 유발을 **실제로 후보로 받았고** (받지 못한
       기회를 포기했다고 적으면 거짓이다),
    2. 그 유발이 **임의**이고 (강제는 포기할 수 없다 — 규칙이 처리를
       요구한다),
    3. 그 자리가 **그 자리에서** 유발이 아닌 다른 행위를 골랐다.

    🔴 **묻는 것은 포기가 아니다.** :meth:`legal_actions` 를 몇 번 불러도
    이 칸은 변하지 않는다. 거절된 불법 행동도 적지 않는다 — 고른 것이
    받아들여지지 않았으면 그 자리는 아직 그 자리다.

    ``frozenset`` 이므로 ``dataclasses.replace`` 가 값으로 가져간다 —
    탐색 사본의 포기가 부모의 목록을 늘리지 않는다.
    """
    consumed_events: frozenset = frozenset()
    """
    **이미 유발 발동에 쓴 기회들** (Phase 6-Z · 6-AA 가 단위를 고쳤다).

    담는 것은 ``(event_key, effect_ref, source)`` **세 짝**이다.

    🔴 **``source`` 가 6-AA 에서 들어왔다.** 6-Z 는 ``(event_key,
    effect_ref)`` 둘만 담았고, 그러면 **한 사건이 같은 이름의 카드 두 장을
    함께 유발시킬 때** 한 장이 발동하면 다른 장의 적법한 기회까지 함께
    닫힌다 — ``EffectRef`` 는 ``(card_id, ordinal)`` 이므로 **개체를 가르지
    않는다** (``engine/ids.py``).

    🔴 **카드명 단위 횟수 제한과 다른 축이다.** 「이 카드명의 ①의 효과는
    1턴에 1번」 같은 제약은 개체가 아니라 **이름**에 걸리고, 그것을 세는
    자리는 ``GameState.rule_uses`` 다. 이 칸은 **한 사건이 한 기회를 두 번
    열지 않는다** 만 말한다 (RULE-EFFECT-004 — 시점을 정하는 것은 사건이다).

    흐름의 위치이고 판의 모양이 아니므로 ``state_hash()`` 에 들어가지
    않는다 (:attr:`chain` · :attr:`priority` 와 같은 자리). ``frozenset``
    이므로 ``dataclasses.replace`` 로 뜬 사본이 **값으로** 가져간다 —
    사본의 발동이 진짜의 소비 목록을 건드리지 않는다.
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
        journal: object | None = None,
        chooser: object | None = None,
        triggers: object | None = None,
    ) -> "Duel":
        """
        듀얼을 시작한다 — 섞고, **5장씩** 뽑고, 선공의 드로우 페이즈에 선다.

        ``seed`` 는 **필수**다. 씨앗 없는 무작위는 재현할 수 없고, 이
        엔진은 그것을 다른 모든 자리에서 이미 거부한다 (Phase 2-Z).

        첫 드로우 페이즈는 :attr:`TurnStep.OPEN` 으로 시작한다 — 룰북이
        "The player who goes first cannot draw during the Draw Phase of
        their first turn" 이라고 말하므로 뽑을 것이 없다.

        ``journal`` (Phase 6-B):

        * 생략하면 **새 기록을 만들어 켠다.** 판을 바꾼 행위가 적힌다.
        * 기존 기록을 주면 그것에 이어 적는다.
        * 🔴 ``False`` 를 주면 **적지 않는다.** 탐색 사본처럼 역사가 필요
          없는 쪽이 쓴다. ``None`` ("안 줬다") 과 ``False`` ("끄겠다") 는
          다른 뜻이므로 가른다.

        어느 쪽이든 **행동은 같다.** 기록이 행동을 바꾸면 기록이 아니다.

        ``chooser`` (Phase 6-Z):

        * **해결 중에 고르는 사람.** 해결기를 통해 실행기까지 내려간다.
        * 생략하면 아직 정해지지 않은 선택이 **거절**된다 — 엔진이 대신
          고르지 않는다.

        ``triggers`` (Phase 6-Z):

        * **사건에서 유발 후보를 만드는 것.** 생략하면 유발 발동이
          ``legal_actions`` 에 오르지 않는다 (6-Z 이전과 같다).
        * 🔴 이 모듈은 그 객체의 타입을 **이름으로 적지 않는다** —
          ``journal`` 과 같은 이유다. 만드는 일은 조립 층이 한다.
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
            #: 🔴 **듀얼 하나에 기록 하나.** 판을 바꾸는 세 자리(행위 실행 ·
            #: 비용 지불 · 효과 해결)가 **같은** journal 을 공유해야 순서가
            #: 사실이 된다. 한 벌로 묶어 만드는 것이 그 공유를 보장하는
            #: 유일한 방법이다 (Phase 6-B).
            **duel_components(journal=journal, chooser=chooser),
            triggers=triggers,
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

        🔴 **강제 유발의 처리가 열려 있으면 그 자리다** (6-AB 보완).

        근거는 룰북의 ``TURN PLAYER'S PRIORITY`` 다: *"As long as the turn
        player has Priority, the opponent cannot activate cards or effects,
        **except for effects that activate automatically, like Trigger or
        Flip effects.**"* 유발 효과는 턴 플레이어 우선권의 **명시된 예외**
        이므로, 상대가 강제 유발을 들고 있으면 내 턴이라도 그 처리가 먼저다.

        🔴 **왜 이 자리에서 고치는가 — 실측한 결함이다.** 6-AB 는
        :meth:`_enforce_mandatory` 가 **자기 자리만** 보았고, 부르는 쪽
        (``DuelRunner`` · ``Simulator``)은 이 칸을 보고 누구에게 물을지
        정한다. 그래서 상대의 강제 의무가 **아무에게도 안 물어지고**
        ``END_PHASE`` 가 수락되어 ``timing_floor`` 가 그것을 지웠다 (실측:
        상대 의무 1 → 페이즈 이동 뒤 0).

        순서는 룰북 §*When multiple cards are activated simultaneously* 다 —
        **턴 플레이어의 강제 효과부터.** 그래서 양쪽이 의무를 들고 있으면
        턴 플레이어를 먼저 돌려준다.

        🔴 **고를 것이 없는 자리를 가리키지 않는다.** 그 자리의 의무가
        관문을 지나지 못하면 (조건 · 비용 · 구현) 그 자리를 가리켜도
        고를 것이 없고, 그러면 듀얼이 멈춘다. 그때는 가리키지 않고
        :meth:`_enforce_mandatory` 가 미지원으로 적는다.
        """
        seat = self.priority.holder.seat
        ordinary = seat if seat is not None else self.turn_player
        duty = self._duty_seat()
        return ordinary if duty is None else duty

    def _duty_seat(self) -> "int | None":
        """
        **강제 유발을 지금 발동할 수 있는 자리** (6-AB 보완). 없으면 ``None``.

        턴 플레이어를 먼저 본다 (룰북 §*When multiple cards are activated
        simultaneously* — 특수 체인을 턴 플레이어의 강제 효과부터 쌓는다).

        🔴 **읽기만 한다.** :meth:`_mandatory_offers` 와
        :meth:`_offer_is_activatable` 둘 다 조회이고, :meth:`legal_actions`
        를 부르지 않는다 — 부르면 그쪽이 이 칸을 읽으므로 되돌이가 된다.

        🔴 **발동할 수 있는 의무만** 센다. 관문을 지나지 못하는 의무로 자리를
        옮기면 그 자리에 고를 것이 없어 듀얼이 멈춘다.
        """
        if self.triggers is None or not self.chain.is_empty:
            # 체인 처리 중에는 그 체인이 먼저다 (聖鳥クレイン 재정) — 의무는
            # 보존되고, 체인이 비면 이 자리가 다시 답한다.
            return None
        for seat in (self.turn_player, 1 - self.turn_player):
            for offer in self._mandatory_offers(seat):
                if self._offer_is_activatable(offer, seat):
                    return seat
        return None

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

        # 정의 등록소를 함께 넘긴다 (Phase 6-K) — 효과의 발동 분류는
        # 관측에 없고 정의에 있다. 발동기가 쓰는 것과 **같은 등록소**다.
        #
        # 사건 목록도 함께 넘긴다 (Phase 6-Z) — "이 효과를 지금 발동할
        # 사건이 있는가" 도 관측에 없다. 그 판정을 들고 있는 것은
        # :attr:`triggers` 이고, 이 자리가 그것을 읽어 **값으로** 준다
        # (``ActivationTiming.set_this_turn`` 과 같은 자리다).
        #
        # 🔴 **묻기만 한다.** ``_trigger_offers`` 는 판도 사건도 바꾸지
        # 않는다 — 소비는 ``apply`` 가 수락한 뒤에만 적는다.
        offers = self._trigger_offers(seat)
        validator = self.activation_validator(seat, offers)

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
        # 🔴 **유발은 두 갈래 밖에서 본다** (6-AB 보완).
        #
        # 6-AB 까지 유발 후보는 아래 두 갈래 **안에** 있었다 — 창을 쥔
        # 자리이거나, 창이 닫혀 있고 턴 플레이어인 자리. 그래서 **턴
        # 플레이어가 아니고 창도 쥐지 않은 자리의 유발은 아무 데도 오르지
        # 않았다** (후보에도, 보류에도). 실측: 상대 자리에 제안이 1건
        # 있는데 ``legal_actions(상대)`` 의 보류가 우선권 이야기 하나뿐이었다.
        #
        # 근거는 룰북 ``TURN PLAYER'S PRIORITY`` 다: *"As long as the turn
        # player has Priority, the opponent cannot activate cards or
        # effects, **except for effects that activate automatically, like
        # Trigger or Flip effects.**"* 유발 효과는 턴 플레이어 우선권의
        # **명시된 예외**이므로, 우선권을 쥐었는지와 **따로** 본다.
        #
        # 체인이 쌓여 있는 동안은 ``_window_admits`` 가 발동을 열지 않으므로
        # (聖鳥クレイン 재정) 이 자리를 밖으로 옮겨도 체인 도중에 끼어드는
        # 후보가 생기지 않는다 — 대신 "기회는 남았고 발동은 체인 뒤" 가
        # 보류에 적힌다.
        opened, held = self._trigger_actions(seat, validator, offers)
        allowed.extend(opened)
        withheld.extend(held)

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

        # 🔴 **강제 유발이 열려 있으면 그 발동 말고는 고를 수 없다**
        # (Phase 6-AB). 6-AA 는 ``END_PHASE`` 하나만 막았고, 그래서 세트 ·
        # 소환 · 공격 · 패스로 필수 처리를 **미룰 수 있었다** (실측: 세트가
        # 허용되고, 세트 뒤에도 강제 기회가 그대로 열려 있었다).
        #
        # 규칙이 요구한 처리를 "다른 것을 먼저 하겠다" 로 넘기는 길을 막는
        # 것이 강제가 임의와 다른 전부다.
        return self._enforce_mandatory(seat, allowed, withheld)

    def _enforce_mandatory(
        self,
        seat: int,
        allowed: "list[PlayerAction]",
        withheld: "list[WithheldAction]",
    ) -> LegalActions:
        """
        **강제 유발이 열려 있으면 그 발동만 남긴다** (Phase 6-AB).

        🔴 **대신 발동해 주지는 않는다.** 엔진이 대신 고르면 해결 중의
        선택(어느 카드인가)까지 엔진이 정하게 되고, 그것은 6-Z 가 세운
        경계를 무너뜨린다. 그래서 **다른 길을 닫고 후보를 남긴다** — 고르는
        쪽에게 남은 길은 그 발동을 집는 것이고, 그 안의 선택은 여전히
        고르는 쪽의 것이다 (``ResolutionChooser``).

        🔴 **영구 대기를 만들지 않는다.** 강제 기회가 있는데 그 발동이
        후보에 **하나도 없으면** (조건 · 비용 · 구현이 막았다) 닫지 않는다 —
        닫으면 고를 것이 없어 듀얼이 그 자리에서 멈춘다. 대신 진행의
        합법성을 보장하지 못한다는 사실을 보류에 적는다
        (:data:`MANDATORY_TRIGGER_UNPLAYABLE`). 그것이 "완료 · 정상 종료" 와
        구별되는 **미지원 결과**다.

        🔴 **양쪽의 의무를 본다** (6-AB 보완이 고친 자리). 6-AB 는 **자기
        자리만** 보았고, 그래서 상대가 강제 의무를 들고 있는데 내
        ``END_PHASE`` 가 수락되었다 — 그리고 ``timing_floor`` 가 그 의무를
        지웠다 (실측: 상대 의무 1 → 페이즈 이동 뒤 0). 그때 적은 근거는
        "막으면 상대가 처리할 수 없는 기회로 내 턴이 멈춘다" 였는데, **멈추지
        않는다**: :attr:`to_act` 가 이제 의무를 든 자리를 가리키므로 그 자리가
        물어진다 (룰북 ``TURN PLAYER'S PRIORITY`` — 유발 효과는 턴 플레이어
        우선권의 명시된 예외다).

        🔴 **그래도 영구 대기는 만들지 않는다.** 막는 조건을
        :meth:`_duty_seat` 에 묶었고, 그 함수는 **발동할 수 있는** 의무만
        가리킨다. 관문을 지나지 못하는 의무로는 아무 자리도 막히지 않고,
        대신 그 자리에 :data:`MANDATORY_TRIGGER_UNPLAYABLE` 이 붙는다.

        🔴 **막는 쪽의 ``missing`` 은 비운다** — 빠진 규칙이 아니라
        **순서**이기 때문이다 (6-S 의 규율).
        """
        duty_seat = self._duty_seat()
        if duty_seat is not None and duty_seat != seat:
            # 🔴 **다른 자리가 먼저 처리해야 한다.** 그 자리는 실제로 그
            # 발동을 고를 수 있으므로 (``_duty_seat`` 이 보증한다) 여기서
            # 막아도 듀얼이 멈추지 않는다.
            # 🔴 **한 줄은 언제나 적는다.** 허가가 이미 비어 있을 수도
            # 있는데 (턴 플레이어도 아니고 창도 쥐지 않은 자리), 그때
            # 아무것도 적지 않으면 "왜 비었는가" 가 우선권 이야기 하나로만
            # 남아 **의무가 보이지 않는다** — 그것이 6-AB 의 결함이었다.
            kinds = {action.kind for action in allowed} or {
                PlayerActionKind.ACTIVATE_EFFECT
            }
            for kind in sorted(kinds, key=lambda k: k.value):
                withheld.append(
                    WithheldAction(
                        kind,
                        f"P{duty_seat} 의 강제 유발 처리가 먼저입니다 — "
                        "유발 효과는 턴 플레이어 우선권의 예외이므로 "
                        "(룰북 TURN PLAYER'S PRIORITY) 그 처리를 넘기고 "
                        "진행할 수 없습니다.",
                    )
                )
            return LegalActions(seat, (), tuple(withheld))

        forced = self._mandatory_offers(seat)
        if not forced:
            return LegalActions(seat, tuple(allowed), tuple(withheld))

        if self.to_act != seat:
            # 의무는 열려 있지만 **지금 고르는 자리가 아니다.** 빠진 규칙이
            # 아니라 순서이므로 ``missing`` 을 비운다.
            withheld.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_EFFECT,
                    f"강제 유발 {len(forced)}건이 이 자리에 열려 있지만 지금 "
                    "행동을 고르는 자리가 아닙니다 — 차례가 오면 그 처리가 "
                    "먼저입니다.",
                )
            )
            return LegalActions(seat, tuple(allowed), tuple(withheld))

        duties = [
            action
            for action in allowed
            if action.kind is PlayerActionKind.ACTIVATE_EFFECT
            and any(
                action.source == offer.source
                and action.effect_ref == offer.effect_ref
                for offer in forced
            )
        ]
        if not duties:
            # 규칙이 요구하는데 발동할 수 없다 — **막지 않고 적는다.**
            withheld.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_EFFECT,
                    f"강제 유발 {len(forced)}건이 열려 있는데 발동 관문을 "
                    "지나지 못했습니다 — 이 진행이 규칙대로인지 보장할 수 "
                    "없습니다 (흐름은 막지 않습니다: 막으면 고를 것이 없어 "
                    "듀얼이 멈춥니다).",
                    missing=MANDATORY_TRIGGER_UNPLAYABLE,
                )
            )
            return LegalActions(seat, tuple(allowed), tuple(withheld))

        for action in allowed:
            if action in duties:
                continue
            withheld.append(
                WithheldAction(
                    action.kind,
                    f"강제 유발 {len(forced)}건을 먼저 처리해야 합니다 — "
                    "규칙이 요구한 처리를 넘기고 다른 것을 할 수 없습니다.",
                )
            )
        return LegalActions(seat, tuple(duties), tuple(withheld))

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
                if definition.activation_kind is ActivationKind.TRIGGER:
                    # **유발은 판에서 만들지 않는다** (Phase 6-Z).
                    #
                    # 이 함수는 판에 있는 카드에서 후보를 만들고, 유발
                    # 효과의 시점은 판이 아니라 **사건**이 정한다
                    # (RULE-EFFECT-004). 사건에서 만드는 자리는
                    # :meth:`_trigger_actions` 하나다.
                    #
                    # 🔴 **두 길이 같은 후보를 내지 않게 하는 줄이다.**
                    # 6-Z 전까지 여기서 만든 유발 후보는 관문이 전부
                    # 거절했으므로 (``MONSTER_ACTIVATION_MISSING_BY_KIND``)
                    # 이 줄이 없어도 결과가 같았다. 사건이 관문을 열게 된
                    # 지금은, 없으면 같은 발동이 **목록에 두 번** 오른다.
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

    def activation_validator(self, seat: int, offers=None) -> ActionValidator:
        """
        이 자리에서 **발동을 판정하는 검증기** (Phase 6-Z).

        🔴 **만드는 자리를 하나로 둔다.** 검증기는 관측에 없는 사실을 둘
        받는다 — 효과의 발동 분류(``definitions``, Phase 6-K)와 지금 사건이
        뒷받침하는 발동들(``event_backed``, 6-Z). 둘 다 "주지 않으면 더 좁은
        답" 이므로, 한 자리라도 빠뜨리면 **오류 없이 조용히** 후보 생성과
        재검증이 갈라진다. 그것이 STRUCTURAL-134 가 고친 어긋남이다.

        세 곳이 이것을 부른다 — :meth:`legal_actions` (후보 생성),
        :meth:`_apply_activation` (적용 직전 재검증), 그리고 보고 계층
        (``deck/opening.py`` 의 ``_gate_code``). 셋이 **같은 함수**를 쓰므로
        같은 판에서 같은 답이 나온다.

        ``offers`` 를 주면 그것을 쓰고, 주지 않으면 :meth:`_trigger_offers`
        로 읽는다 — 같은 걸음에서 두 번 읽지 않으려는 것이고, 읽기만 하므로
        답은 같다.
        """
        if offers is None:
            offers = self._trigger_offers(seat)
        return ActionValidator(
            self.view(seat),
            definitions=self._activator.definitions,
            #: 🔴 **내놓을 수 있는 제안만 관문을 연다** (Phase 6-AB).
            #:
            #: 6-AA 는 제안 **전부**로 이 집합을 만들고, 모름 · 지나간 기회를
            #: ``legal_actions`` 에서만 걸렀다. 그래서 관문 자신은
            #: ``valid/ok`` 를 돌려주었고 (실측), 막는 것은 ``apply`` 앞의
            #: "후보 목록에 있는가" 검사 **하나뿐**이었다 — 후보 목록에
            #: 없다는 이유만으로 안전한 구조였다.
            #:
            #: 지금은 **같은 판정이 관문 안에 있다.** 후보 생성과 직접 실행이
            #: 이 함수를 함께 쓰므로 (``legal_actions`` · ``_apply_activation``
            #: · 보고 계층) 세 자리가 같은 답을 본다.
            event_backed=frozenset(
                (offer.source, offer.effect_ref)
                for offer in offers
                if self._offer_is_activatable(offer, seat)
            ),
        )

    def _offer_is_activatable(self, offer, seat: int) -> bool:
        """
        이 제안을 **지금 발동할 수 있는 기회로 열어도 되는가** (Phase 6-AB).

        🔴 **후보 생성과 직접 실행이 공유하는 판정이다.**
        :meth:`activation_validator` 가 이것으로 ``event_backed`` 를 만들고,
        그 검증기를 ``legal_actions`` 와 :meth:`_apply_activation` 이 함께
        쓴다. 그래서 "목록에 없으니 안전하다" 에 기대지 않는다.

        둘을 본다.

        1. **근거 있는 강제 또는 임의인가.** 모름은 열지 않는다 (6-AA) —
           모름을 열면 정책의 거절과 규칙이 허락한 포기가 구별되지 않는다.
        2. **이 창이 그 발동을 받아들이는가** (:meth:`_window_admits`) —
           체인이 쌓여 있지 않고, 그 자리가 포기하지 않았고, 타이밍을 놓치지
           않았는가. 모르면 열지 않는다 — 모름을 허가로 바꾸지 않는다.

        지나간 페이즈와 이미 쓴 기회는 :meth:`_trigger_offers` 가 **앞에서**
        걸러 내므로 여기 오지 않는다.

        🔴 ``seat`` 를 받는다 (6-AB 보완). 포기는 자리마다 따로이므로
        (:attr:`declined_events`) 자리를 모르면 답할 수 없다.
        """
        if not (offer.is_optional or offer.is_mandatory):
            return False
        return self._window_admits(offer, seat) is True

    def _window_admits(self, offer, seat: int) -> "bool | None":
        """
        이 제안을 **지금 이 자리에서 발동할 수 있는가.** 모르면 ``None``.

        🔴 **6-AB 의 ``_timing_is_current`` 를 대체한다.** 그 함수는 세 질문을
        하나로 섞었고, 그래서 셋 다 틀렸다 (6-AB 보완 §2 가 실측을 적는다):

        ======================================  =============================
        섞여 있던 질문                            지금 어디서 답하는가
        ======================================  =============================
        이 사건의 기회가 아직 남아 있는가           :meth:`_opportunity_is_open`
        지금 이 자리에서 발동해도 되는가            여기
        어휘를 판정할 수 있는가                    여기 (``None``)
        ======================================  =============================

        여기서 보는 것은 **둘**이다.

        ① **체인이 쌓여 있으면 발동을 열지 않는다.**

        공식 재정 (OCG 카드 데이터베이스, 聖鳥クレイン cid=5883 의 2021-07-01
        보충): *특수 소환이 체인 처리 중에 행해진 경우 등, 특수 소환 직후에
        다른 처리가 행해지는 경우에는 **그 체인이 모두 해결된 후에**
        발동한다.* 즉 체인 도중의 사건은 **보존**되지만 그 체인에 끼워
        발동되지는 **않는다.**

        🔴 6-AB 는 이것을 거꾸로 했다 — 체인이 비어 있지 않으면 ``True`` 를
        돌려주어 **체인 도중에 발동을 허가했다** (실측:
        ``_offer_is_activatable`` → ``True``). 보존해야 한다는 사실을 지금
        발동해도 된다는 뜻으로 읽은 것이고, 그 둘은 다른 질문이다. 보존은
        :meth:`_opportunity_is_open` 이 맡는다 (체인은 ``timing_floor`` 를
        올리지 않으므로 기회는 그대로 남는다).

        ② **그 자리가 그 기회를 아직 안 썼고 포기하지도 않았는가.**

        포기는 :attr:`declined_events` 가 적는다. 이것이 *"타이밍을 놓치지
        않는다"* 와 *"같은 페이즈에서 나중에 마음대로"* 를 가르는 자리다.

        🔴 **어휘는 여기서 쓰지 않는다.** 「때 / 경우」 는 **포기 없이 지나간**
        기회를 어떻게 볼지의 문제이고, 그것은 :meth:`_missed_timing` 이
        따로 답한다 — 거기서만 강제 · 임의를 함께 본다.
        """
        if not self.chain.is_empty:
            # 체인이 쌓여 있다 — 보존하되 **열지 않는다** (위 ① 의 재정).
            return False
        if self._decline_key(offer, seat) in self.declined_events:
            return False
        return self._missed_timing(offer) is not True

    def _missed_timing(self, offer) -> "bool | None":
        """
        이 유발이 **타이밍을 놓쳤는가.** 모르면 ``None`` (6-AB 보완).

        어휘만으로 답하지 않는다 — **강제 · 임의를 함께** 본다.

        ====================  ========  =====================================
        어휘                   허가       답
        ====================  ========  =====================================
        「경우」                어느 쪽    **놓치지 않는다** (``False``)
        「때」                  임의       그 사건이 마지막이 아니면 놓쳤다
        「때」                  **강제**   🔴 **모른다** (``None``) — 아래
        모름                   어느 쪽    사건이 마지막이면 ``False``, 아니면
                                        모른다 (``None``)
        ====================  ========  =====================================

        🔴 **강제 「때」 를 어휘만으로 만료시키지 않는다.** 6-AB 는 그렇게
        했고 (실측: ``MANDATORY`` + ``WHEN`` + 사건이 마지막 아님 →
        ``_mandatory_offers`` 가 **0**), 그러면 규칙이 처리를 요구하는 효과가
        **조용히 사라진다.**

        근거의 상태를 정직하게 적는다:

        - 룰북(``data/rules/``)에 「때 / 경우」 구분이 **없다.** 따라서
          "강제는 타이밍을 놓치지 않는다" 를 **공식 문서로 확인하지
          못했다.**
        - 저장소의 공식 자료 중 가장 가까운 것은 룰북 §*When multiple cards
          are activated simultaneously* 다: 특수 체인을 **턴 플레이어의 강제
          효과부터** 쌓는다. 규칙이 강제 효과를 "먼저 처리해야 하는 것" 으로
          다루는 것은 보이지만, 그것이 곧 "놓치지 않는다" 는 아니다.
        - 2차 자료(팬 위키 · 해설 글)는 "강제 효과는 타이밍을 놓치지
          않는다" 로 일치하지만 **공식 재정이 아니므로 근거로 쓰지 않는다.**

        그래서 ``None`` 이다 — 모름을 ``False``(아직 유효)로도 ``True``(만료)로도
        바꾸지 않는다. 받는 쪽은 그 모름을 **보류로** 적고 (무엇을 모르는지
        함께), 흐름은 막지 않는다.
        """
        misses = getattr(offer, "misses_timing", None)
        if misses is False:
            return False
        if misses is True and getattr(offer, "is_mandatory", False):
            # 🔴 강제 「때」 — 어휘로는 만료인데 그것을 적용할 공식 근거가
            # 없다. 모름으로 둔다 (위 설명).
            return None
        last = (len(self.journal) - 1) if self.journal is not None else -1
        is_last = getattr(offer, "event_sequence", -1) == last
        if is_last:
            # 사건이 아직 마지막이다 — 어느 어휘든 놓치지 않았다.
            return False
        if misses is True:
            return True
        # 어휘를 모르고 사건도 마지막이 아니다 — 말할 수 없다.
        return None

    def _trigger_offers(self, seat: int):
        """
        **지금 이 자리에 사건이 열어 준 제안들** (Phase 6-Z).

        :attr:`triggers` 가 없으면 빈 짝이다. 있으면 그것에 물어보고, **셋을
        걸러 낸다**:

        1. **지나간 시점** — :attr:`timing_floor` 보다 앞의 기록에서 나온
           제안 (Phase 6-AA). 번호를 **모르는** 제안(``-1``)도 여기서 빠진다
           — 지금 것인지 말할 수 없으면 내놓지 않는다.
        2. **이미 쓴 기회** — :attr:`consumed_events` 에 든 ``(event_key,
           effect_ref, source)`` 세 짝.
        3. (내놓을지 말지는 :meth:`_trigger_actions` 가 근거에 따라 가른다 —
           여기서는 제안을 그대로 들고 온다.)

        🔴 **읽기만 한다.** 판도 사건 기록도 :attr:`consumed_events` 도
        건드리지 않으므로, 몇 번 불러도 같은 답이고 **후보를 묻는 것만으로
        사건이 소비되지 않는다.** 소비는 :meth:`_apply_activation` 이 발동을
        수락한 뒤에만 적는다.

        두 곳이 이것을 부른다 — :meth:`legal_actions` (후보를 만들려고) 와
        :meth:`_apply_activation` (수락한 발동이 어느 사건의 것인지 알려고).
        둘이 **같은 함수**를 부르므로 목록과 적용이 갈라지지 않는다
        (STRUCTURAL-134 와 같은 규율).
        """
        if self.triggers is None:
            return ()
        return tuple(
            offer
            for offer in self.triggers.offers(self, seat)
            if self._opportunity_is_open(offer)
        )

    def _mandatory_offers(self, seat: int) -> tuple:
        """
        이 자리에 **근거 있는 강제 유발**이 열려 있는가 (Phase 6-AA · 6-AB).

        🔴 **읽기만 한다** — :meth:`_trigger_offers` 와 같은 함수를 부르므로
        후보 목록과 흐름 판정이 **같은 답**을 본다. 모름(``UNKNOWN``)은 여기
        들어오지 않는다: 모르는 것을 강제로 바꾸면 흐름이 영영 막힌다.

        🔴 **놓친 것이 확실한 것만 뺀다** (:meth:`_missed_timing` 이 ``True``).
        6-AB 는 어휘가 「때」 이면 강제까지 빼 버렸고 (실측: ``MANDATORY`` +
        ``WHEN`` → 의무 **0**), 그러면 규칙이 처리를 요구하는 효과가 **조용히
        사라진다.** 지금은 강제 「때」 가 ``None``(모름)으로 와서 **의무로
        남고**, 발동할 수 없으면 :data:`MANDATORY_TRIGGER_UNPLAYABLE` 이
        붙는다 — 그것이 "모른다" 의 정직한 결과다.

        🔴 **체인이 쌓여 있어도 의무는 남는다.** 체인 도중에는 발동을 열지
        않지만 (:meth:`_window_admits`) 그 의무가 **사라지는 것은 아니다** —
        체인이 해결된 뒤에 처리해야 한다 (聖鳥クレイン 재정). 그래서 여기서
        체인을 보지 않는다.

        🔴 **포기도 보지 않는다.** 강제는 포기할 수 없다.
        """
        return tuple(
            offer
            for offer in self._trigger_offers(seat)
            if offer.is_mandatory and self._missed_timing(offer) is not True
        )

    def _opportunity_is_open(self, offer) -> bool:
        """
        이 제안이 **지금의 기회**인가 (Phase 6-AA). 읽기만 한다.

        둘을 본다 — 사건이 이번 페이즈의 것인가 (:attr:`timing_floor`), 그
        기회를 이미 썼는가 (:attr:`consumed_events`).
        """
        sequence = getattr(offer, "event_sequence", -1)
        if sequence < self.timing_floor:
            # 지나간 페이즈의 사건이거나 (``sequence`` 가 바닥보다 앞),
            # 번호를 모른다 (``-1`` 은 ``timing_floor >= 0`` 보다 늘 작다).
            return False
        return self._consumption_key(offer) not in self.consumed_events

    @staticmethod
    def _consumption_key(offer) -> tuple:
        """
        이 기회를 가리키는 **세 짝** — 사건 · 효과 · 카드 개체 (Phase 6-AA).

        🔴 세 번째가 ``source`` 다. 빼면 한 사건이 같은 이름의 카드 두 장을
        함께 유발시킬 때 한 장의 발동이 다른 장의 기회까지 닫는다
        (:attr:`consumed_events` 의 설명).
        """
        return (offer.event_key, offer.effect_ref, offer.source)

    def _trigger_actions(self, seat: int, validator: ActionValidator, offers=()):
        """
        **사건이 열어 준 유발 발동 후보들** (Phase 6-Z).

        후보의 재료는 :meth:`_trigger_offers` 가 읽어 온 제안들이고, 이
        함수는 그것을 **행위로 환전하고 관문에 태우기만** 한다. 제안이
        없으면 (``triggers`` 가 없거나 사건이 없거나) **빈 목록**이다 —
        6-Z 이전과 같다. 없는 것을 기본값으로 메꾸지 않는다 (ADR-006).

        왜 ``_activation_actions`` 와 따로인가
        --------------------------------------
        그쪽은 **판에 있는 카드**에서 후보를 만든다 (자리 · 분류 · 조건).
        유발은 **사건**에서 나온다 — 같은 카드가 같은 자리에 있어도 사건이
        없으면 후보가 아니다. 출처가 다르므로 함수를 가른다.

        무엇을 지키는가
        ---------------
        1. **사건이 있어야 한다.** 후보는 :attr:`triggers` 가 기록된 사건에서
           만든 것만이고, 이 함수는 사건을 만들지 않는다.
        2. **같은 사건으로 두 번 발동하지 않는다.**
           :attr:`consumed_events` 에 든 ``(event_key, effect_ref)`` 짝은
           :meth:`_trigger_offers` 가 이미 걸러 냈다.
        3. **묻는 것만으로 아무것도 바뀌지 않는다.** 이 함수는 판도
           :attr:`consumed_events` 도 건드리지 않는다 — 소비는 :meth:`apply`
           가 발동을 **수락한 뒤에만** 적는다.
        4. **관문은 같다.** 만든 후보를 ``_activation_gate`` 에 그대로 태운다
           — ``legal_actions`` 와 ``apply`` 가 같은 함수 · 같은 판을 본다
           (STRUCTURAL-134).

        🔴 **강제 · 임의 · 모름을 가른다** (Phase 6-AA). 6-Z 는 셋을 한
        덩어리로 내놓고 발동 여부를 전부 고르는 쪽에 맡겼는데, 그것은
        **모름을 임의로 승격**시키는 일이었다 — 고르는 쪽이 거절한 것과
        규칙이 거절을 허락한 것이 구별되지 않았다.

        ======================  ==========================================
        근거 있는 **임의**        후보로 올린다. 발동도 포기도 고르는 쪽의 것
        근거 있는 **강제**        후보로 올린다. 그리고 **흐름을 막는다** —
                                이 기회가 열려 있는 동안 페이즈를 넘길 수
                                없다 (:meth:`_flow_actions`). 규칙이 요구한
                                처리를 임의 거절로 생략하지 않는다
        **모름**                 후보로 올리지 **않는다.** 보류 목록에 무엇을
                                모르는지 적는다 — 조용히 넘어가지 않는다
        ======================  ==========================================

        돌려주는 것은 ``(허가, 보류)`` 짝이다.
        """
        allowed: list[PlayerAction] = []
        withheld: list[WithheldAction] = []
        if self.triggers is not None and self.journal is None:
            # 🔴 **사건 기록이 없는 사본이다** (Phase 6-AA). 유발은 사건에서
            # 나오므로 기록이 없으면 꺼낼 것이 없다 — 그런데 그것을 조용히
            # "후보 0건" 으로 두면 읽는 쪽이 "유발이 없다" 로 읽는다. 둘은
            # 다른 사실이므로 **보류에 적는다.**
            #
            # 이 자리를 밟는 것은 ``agent.simulation`` 의 ``_fork`` 다 —
            # 기록하지 않는 한 벌로 바꿔 끼우기 때문이다 (Phase 6-B).
            withheld.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_EFFECT,
                    "사건 기록이 없는 사본에서는 유발 후보를 판정할 수 "
                    "없습니다 (유발은 기록된 사건에서 나옵니다).",
                    missing=TRIGGER_HISTORY_MISSING,
                )
            )
        for offer in offers:
            if not (offer.is_optional or offer.is_mandatory):
                # 🔴 **모름은 후보가 아니다.** 무엇을 모르는지 적는다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "이 유발이 강제인지 임의인지 판정할 수 없어 발동 "
                        "여부를 고르는 쪽에 맡기지 않았습니다 — 모름을 "
                        "임의로 바꾸면 규칙이 요구한 처리가 조용히 생략될 "
                        "수 있습니다.",
                        missing=TRIGGER_REQUIREMENT_MISSING,
                    )
                )
                continue
            # 🔴 **세 이유를 따로 적는다** (6-AB 보완). 6-AB 는 셋을 한
            # 함수(``_timing_is_current``)로 섞어서 "체인 도중" 과 "포기했다"
            # 와 "어휘를 모른다" 가 같은 답으로 나왔다.
            if not self.chain.is_empty:
                # 체인이 쌓여 있다 — 기회는 **보존되지만** 이 체인에 끼워
                # 발동하지는 않는다 (聖鳥クレイン 재정 · ``_window_admits``).
                # 빠진 규칙이 아니라 **순서**이므로 ``missing`` 을 비운다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "체인이 처리 중입니다 — 이 유발의 기회는 남아 "
                        "있지만, 발동은 그 체인이 모두 해결된 뒤입니다.",
                    )
                )
                continue
            if self._decline_key(offer, seat) in self.declined_events:
                # 그 자리가 이 기회를 **적법하게 포기했다.** 빠진 규칙이
                # 없다 — 규칙이 그렇게 정했으므로 ``missing`` 을 비운다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "그 사건의 유발 처리 기회에서 다른 행동을 골라 이 "
                        "발동을 포기했습니다 — 그 기회는 끝났습니다.",
                    )
                )
                continue
            missed = self._missed_timing(offer)
            if missed is None:
                # 🔴 **판정 근거가 없다.** 무엇을 모르는지 적는다 — 모름을
                # 허가로도 만료로도 바꾸지 않는다 (``_missed_timing``).
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "이 사건 뒤에 다른 일이 일어났고, 이 유발이 "
                        "타이밍을 놓쳤는지 판정할 근거가 없습니다 "
                        f"(강제={offer.is_mandatory} · 어휘 판정="
                        f"{offer.misses_timing}).",
                        missing=TRIGGER_WORDING_MISSING,
                    )
                )
                continue
            if missed is True:
                # 🔴 **놓쳤다** — 임의 「때」 이고 그 사건이 더 이상 마지막에
                # 일어난 일이 아니다. 규칙이 그렇게 정했으므로 ``missing``
                # 을 비운다 (6-S 의 규율).
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "그 사건 뒤에 다른 일이 일어나 「때」 유발의 타이밍을 "
                        "놓쳤습니다.",
                    )
                )
                continue
            candidate = PlayerAction.activate_effect(
                actor=seat,
                source=offer.source,
                effect_ref=offer.effect_ref,
            )
            definition = self._activator.definitions.definition_for(
                offer.effect_ref
            )
            if definition is None:  # pragma: no cover - 제안이 보증한다
                continue
            try:
                selections = selections_for(definition, candidate)
            except TargetBridgeError:  # pragma: no cover
                continue
            if (
                self._activation_gate(
                    candidate, validator=validator, selections=selections
                ).validity
                is not ActionValidity.VALID
            ):
                continue
            allowed.append(candidate)
        return allowed, withheld

    def _set_this_turn(self, action: PlayerAction) -> "bool | None":
        """
        발동하려는 카드를 **이 턴에 세웠는가** (Phase 3-E-15).

        ``None`` 은 **"모른다"** 다 — 가리킨 카드를 판에서 찾지 못했을 때다.
        관문은 그것을 ``UNKNOWN`` 으로 받고, ``UNKNOWN`` 은 허가가 아니다.

        **왜 이 자리가 읽는가.** 이 사실은 ``GameState.rule_uses`` 에 있고
        관측(``GameStateView``)에는 **없다** — 상대가 언제 세웠는지는 공개
        정보가 아니기 때문이다 (Phase 3-E-15 §12). 그래서 검증기도 타이밍
        관문도 스스로 알 수 없고, **판을 들고 있는 이쪽**이 읽어서 값으로
        넘긴다. 체인과 우선권을 같은 방식으로 넘기는 것과 같은 자리다
        (ADR-007).

        **읽기만 한다.** 후보 생성도 타이밍 판정도 기록을 바꾸지 않는다 —
        쓰는 곳은 ``SetExecutor.apply`` 하나다.
        """
        if action.source is None:
            return None
        instance = self.state.find_instance(action.source)
        if instance is None:
            return None
        return self.state.rule_uses.used_card(
            self.state.turn.turn_number,
            instance.controller,
            action.source,
            RuleActionKind.SET_SPELL_TRAP,
        )

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

        🔴 **몬스터 존이 셋째 · 넷째로 들어왔다** (Phase 6-K). 몬스터의 기동
        효과는 필드에서 발동하고 (``SetRange(LOCATION_MZONE)``), 그 자리를
        보지 않으면 **어떤 관문도 판정할 기회를 얻지 못한다** — 위 문단과
        정확히 같은 이유다. 엑스트라 몬스터 존도 함께 본다: 거르지 않고
        내보내고, 범위 밖이면 관문이 이유를 적는다
        (``IGNITION_LOCATION_MISSING``).

        **여기서 넓어지는 것은 없다.** 다음 줄에서 ``activatable_effects`` 가
        실행 구현이 등록된 효과만 돌려주고, 등재된 몬스터 효과는 하나뿐이며
        그것은 ``executable=False`` 다 (ADR-006).
        """
        player = self.state.player(seat)
        return (
            tuple(player.hand)
            + tuple(
                card
                for zone in ACTIVATION_SOURCE_ZONES
                for card in player.zone(zone)
                if card is not None
            )
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
            ActivationTiming(
                self.chain,
                self.priority,
                set_this_turn=self._set_this_turn(action),
            ),
            action,
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
        """
        흐름을 움직이는 둘 — ``PASS`` 와 ``END_PHASE``.

        🔴 **"패스할 수 없다" 의 이유가 둘이고, 그 둘은 다른 사실이다**
        (Phase 6-S). 룰북이 그 둘을 따로 적는다 (``TURN PLAYER'S
        PRIORITY``)::

            As long as the turn player has Priority, the opponent cannot
            activate cards or effects …
            After a card's activation, and at the end of each phase or
            step, Priority passes to the opponent.

        ====================================  ==============================
        **창이 닫혀 있다**                      우선권을 쥔 사람이 아직 넘기지
                                              않았다. 🔴 넘기는 쪽 규칙이
                                              **빠져 있다** — 엔진은 발동
                                              뒤에만 창을 열고, 페이즈 · 스텝
                                              의 끝에서는 열지 않는다
        **창이 열려 있고 상대가 쥐었다**          빠진 규칙이 **없다.** 지금은
                                              상대의 차례이고, 그 차례가
                                              끝나면 이쪽으로 온다
        ====================================  ==============================

        6-S 전까지 이 둘이 ``elif seat != self.turn_player`` 하나에 묶여
        있었고, 그래서 두 가지가 틀렸다 (실측).

        * 창이 **열려 있는데** 상대가 쥔 자리에서 "우선권이 열려 있지
          않습니다" 라고 적었다 — **거짓 문장**이다.
        * 창이 열려 있고 상대가 쥐었는데 **이쪽이 턴 플레이어이면** 어느
          분기도 밟지 않아 **후보 0 · 보류 0** 이 되었다. 읽는 쪽은 "할 것이
          없다" 와 "상대를 기다린다" 와 "듀얼이 끝났다" 를 가를 수 없었다.
        """
        allowed: list[PlayerAction] = []
        withheld: list[WithheldAction] = []

        if self.priority.is_open and self.priority.holds(seat):
            allowed.append(PlayerAction.passing(actor=seat))
        elif self.priority.is_open:
            # 🔴 **창은 열려 있다** — 다만 상대가 쥐고 있다. ``missing`` 을
            # 비운다: 빠진 규칙이 아니라 **순서**다. (6-S 가 이 자리를 세울
            # 때는 그런 자리가 여기 하나뿐이었다. 지금은 같은 이유로 비우는
            # 자리가 `_enforce_mandatory` 와 `_trigger_actions` 에도 있다 —
            # 기준이 같고, `test_i03` 이 자리마다 그 기준을 센다.)
            holder = self.priority.holder.seat
            withheld.append(
                WithheldAction(
                    PlayerActionKind.PASS,
                    f"응답 기회가 열려 있지만 지금은 P{holder} 의 차례입니다.",
                )
            )
        elif seat != self.turn_player:
            withheld.append(
                WithheldAction(
                    PlayerActionKind.PASS,
                    "우선권이 열려 있지 않습니다.",
                    missing="우선권을 여는 규칙 (Phase 2-F)",
                )
            )

        if seat == self.turn_player and not self.priority.is_open:
            # 🔴 **강제 유발은 여기서 보지 않는다** (Phase 6-AB 가 옮겼다).
            #
            # 6-AA 는 이 자리에서 ``END_PHASE`` 하나를 막았고, 그래서 세트 ·
            # 소환 · 공격 · 패스로 필수 처리를 미룰 수 있었다 (실측). 막아야
            # 하는 것은 **그 자리의 모든 다른 행동**이므로, 판정을 후보
            # 목록이 다 만들어진 뒤로 옮겼다 (:meth:`_enforce_mandatory`).
            # 한 자리에서 보면 ``END_PHASE`` 도 함께 닫힌다.
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
        step = self._apply_board(action)
        if step.accepted:
            # 🔴 **판을 바꾸는 행위를 골랐다 — 열려 있던 임의 유발 기회는
            # 그 자리에서 포기한 것이다** (6-AB 보완 · ``declined_events``).
            #
            # 수락된 뒤에만 적는다: 거절된 행동은 그 자리를 떠나지 않았으므로
            # 기회를 쓰지 않는다 (``test_b07`` 이 재는 것이고, 그 성질을
            # 지키려고 이 자리가 ``accepted`` 안에 있다).
            self._decline_open_offers(action.actor, legal)
        return step

    def _decline_open_offers(self, seat: int, legal: LegalActions) -> None:
        """
        그 자리가 **받았던** 임의 유발 기회를 포기로 적는다 (6-AB 보완).

        🔴 **"다음 행동이면 무조건 만료" 가 아니다.** 적는 대상은 방금 그
        자리의 ``legal_actions`` 에 **실제로 올라 있던** 발동들이다 — 받지
        못한 기회를 포기했다고 적으면 거짓이고, 그러면 나중에 적법하게 열릴
        기회까지 닫힌다. 그래서 ``legal`` 을 인자로 받는다: 같은 걸음에서
        이미 만든 그 목록이고, 다시 묻지 않는다 (다시 물으면 판이 바뀐 뒤의
        답이 온다).

        🔴 **강제는 적지 않는다.** 규칙이 처리를 요구하는 것을 "포기" 로
        적을 수는 없다. 강제가 열려 있으면 애초에 다른 행동이 허가되지
        않는다 (:meth:`_enforce_mandatory`) — 그래서 이 자리에 오는 강제는
        발동할 수 없는 것뿐이고, 그것은 포기가 아니라 미지원이다.

        근거: 공식 Fast Effect Timing 도표는 유발을 체인을 시작하지 않는
        행위 뒤와 체인 해결 뒤에 확인한다. 그 확인 자리에서 유발이 아닌
        것을 골랐으면 판은 **open state** 로 돌아가고, 그 창은 닫힌다.
        """
        offered = {
            (action.source, action.effect_ref)
            for action in legal.allowed
            if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        }
        if not offered:
            return
        giving_up = {
            self._decline_key(offer, seat)
            for offer in self._trigger_offers(seat)
            if offer.is_optional
            and (offer.source, offer.effect_ref) in offered
        }
        if giving_up:
            self.declined_events = self.declined_events | giving_up

    @staticmethod
    def _decline_key(offer, seat: int) -> tuple:
        """
        포기한 기회를 가리키는 **네 짝** — 사건 · 효과 · 개체 · 자리.

        :meth:`_consumption_key` 와 **같은 축**에 자리를 더한 것이다. 둘이
        같은 축이어야 "썼다" 와 "포기했다" 가 같은 단위로 세어진다.
        """
        return (offer.event_key, offer.effect_ref, offer.source, seat)

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

        🔴 **적법한 패스는 언제나 수락이다** (Phase 6-R).

        이 함수가 돌려주는 ``DuelStep`` 의 ``accepted`` 는 두 길 모두 참이다 —
        기회를 넘기기만 했을 때도, 체인을 풀었을 때도. 그 체인 안에서 링크가
        불발되었더라도 **패스는 일어났다.** 불발 사유는 ``code`` 와 ``reason``
        이 들고 가고, 무엇이 실제로 적용되었는지는 ``EventJournal`` 이 말한다
        (:attr:`DuelStep.accepted` 의 설명 참고).
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
        self.priority = resolution.state.priority

        # 🔴 **이 체인은 끝났다** (Phase 6-R). 링크가 전부 적용되었든 하나가
        # 불발되었든, ``ResponseLoop.resolve`` 가 기회를 닫았으므로
        # (``AFTER_CHAIN_RULE``) **다시 풀릴 수 없다** — 체인을 푸는 자리는
        # ``_apply_pass`` 하나이고 그것은 열린 기회를 요구한다.
        #
        # 예전에는 ``if self.chain.is_complete:`` 일 때만 비웠다. 그러면 링크
        # 하나가 불발된 체인이 **영구히 남고**, 남은 체인이
        # ``ActivationTiming.chain_is_open`` 을 참으로 고정한다. 그 뒤로
        # :meth:`_activation_gate` 의 둘째 관문이 **모든 스펠 스피드 1 발동**
        # 에 ``SPELL_SPEED_TOO_LOW`` 를 돌려준다 — "스펠 스피드 1 은 어떤
        # 효과에도 응수할 수 없습니다". 실측 (seed 303 · DIGEST 덱):
        #
        #     불발 뒤 links=3 resolved=2 is_complete=False
        #     chain_is_open=True → 관문2 = SPELL_SPEED_TOO_LOW
        #     남은 네 턴(5→8) 동안 발동 후보 **0건**, 체인은 끝까지 남는다
        #
        # 그리고 그 거절은 **보류 목록에도 남지 않는다** — 후보 생성이
        # 관문에서 걸린 것을 버리므로, 호출자가 ``apply`` 로 직접 넣으면
        # ``RULE_NOT_IMPLEMENTED`` ("허가된 행위가 아닙니다") 를 받는다.
        # 규칙이 금지하지 않는 것을 금지하고, 그 이유조차 말하지 않았다.
        #
        # 비우는 것이 "해결했다" 는 뜻이 **아니다.** 무엇이 적용되었는지는
        # ``EventJournal`` 에만 있다 (적용된 링크만 ``EffectEvent`` 를 남긴다).
        self.chain = Chain()

        # **해결됐든 아니든 놓인 마법은 필드를 떠난다** (RULE-SPELLTRAP-002).
        self._retire_pending()

        steps = resolution.steps
        last = steps[-1]
        if not resolution.fully_resolved:
            # 🔴 **패스는 수락이다** (Phase 6-R).
            #
            # 예전에는 여기서 ``accepted=False`` 를 돌려주었다. 그런데 돌아간
            # 행위는 **패스**이고, 그 패스는 분명히 일어났다 — 우선권이
            # 넘어갔고, 적용된 링크가 판을 바꾸었고, 놓인 카드가 묘지로 갔다.
            # 불발은 **링크의 결과**이지 패스의 적법성이 아니다.
            #
            # 그 거짓 실패를 네 호출자가 그대로 믿었다 — ``DuelRunner.run`` 은
            # **듀얼을 중단**하고, ``Simulator.simulate`` 는 적법한 수를
            # ``REFUSED`` 로 분류하고, ``fork_after`` 는 ``None`` 을 돌려주고,
            # ``_settle_forced_passes`` 는 정산을 멈춘다.
            #
            # 그래서 ``accepted`` 는 참이고, **불발 사유는 버리지 않는다** —
            # ``code`` 와 ``reason`` 이 그대로 들고 간다. "해결했다" 고 적지
            # 않는 규율은 그 둘이 지킨다 (``ValidationCode.OK`` 가 아니다).
            return DuelStep(
                action, True, last.code, last.reason, result=self._check_end()
            )
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            last.reason,
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
        if instance is not None and instance.zone not in PLACEMENT_SOURCE_ZONES:
            # **배치가 없는 발동이다** (Phase 6-K). 몬스터의 기동 효과는
            # 카드를 움직이지 않는다 — RULE-SPELLTRAP-002 의 "placing it
            # face-up on the field" 는 마법 · 함정의 절차이고, 이 카드는
            # 이미 필드에 앞면으로 있다.
            #
            # 묻는 자리가 **여기**인 이유: 비용과 체인 링크는 이미 지나갔고
            # (``activate``), 거기서 ``place`` 가 "패에 없다" 로 실패하면
            # 되돌릴 방법이 없다 (ADR-008). 카드 종류를 보지 않고 **자리**를
            # 본다 — 어느 자리에 배치가 있는가는 배치 계층이 적어 둔다.
            return None
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
        # 🔴 **페이즈가 바뀌었다 — 앞의 사건은 지나간 시점이다**
        # (Phase 6-AA, :attr:`timing_floor` 의 설명이 근거를 적는다).
        #
        # 여기가 페이즈를 바꾸는 **유일한 자리**이므로 (``TurnProgressor.
        # advance`` 를 부르는 production 호출 하나) 바닥을 올리는 자리도
        # 하나다. 올리지 않으면 지나간 유발이 영영 열려 있다.
        self.timing_floor = len(self.journal) if self.journal is not None else 0
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

        🔴 **④는 이 함수의 걸음이 아니다** (Phase 3-E-11 이 옮겼고 6-R 이
        그 결과를 정리했다). 해결은 ``_resolve_chain`` 에서 일어나고, 그
        함수가 돌려주는 ``DuelStep`` 의 행위는 **패스**다. 그래서 "해결했다고
        적지 않는다" 를 ``accepted=False`` 로 적으면 **패스를 거절한 것**이
        되어 버린다 — 6-R 이 그 자리를 ``code`` 와 ``reason`` 으로 옮겼다.
        이 함수가 돌려주는 걸음은 여전히 **발동의 수락**만 말한다.
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

        # 🔴 **사건은 여기서 다시 읽는다** (Phase 6-Z). ``legal_actions``
        # 가 만든 목록을 믿지 않는 것과 같은 이유다 — 목록을 만든 뒤 판과
        # 사건 기록이 바뀌었을 수 있다. 같은 함수를 다시 부르므로
        # **만료되거나 이미 소비된 사건은 여기서 사라진다.**
        offers = self._trigger_offers(action.actor)
        consuming = next(
            (
                offer
                for offer in offers
                if offer.source == action.source
                and offer.effect_ref == action.effect_ref
            ),
            None,
        )

        # ① **판을 바꾸기 전에** 세 관문을 지난다. ``legal_actions`` 가 쓰는
        # 것과 **같은 함수**이고 **같은 판**이다 (STRUCTURAL-134).
        #
        # ``legal_actions`` 를 지나왔다고 **믿지 않는다.** ``apply`` 는 공개
        # 입구이고, 아무 ``PlayerAction`` 이나 들어올 수 있다.
        gate = self._activation_gate(
            action,
            validator=self.activation_validator(action.actor, offers),
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

        # ④ **사건을 소비한다** (Phase 6-Z). 발동이 성립한 **뒤**다 —
        # 거절된 발동은 사건을 쓰지 않았으므로, 거절 뒤에 다시 시도할 수
        # 있어야 한다 (후보를 묻는 것만으로도 소비되지 않는 것과 같은
        # 이유다).
        #
        # ``None`` 은 **사건에서 온 발동이 아니다** — 기동 효과 · 마법 ·
        # 함정의 발동이고, 그 길은 사건을 쓰지 않으므로 적을 것이 없다.
        if consuming is not None:
            self.consumed_events = self.consumed_events | {
                self._consumption_key(consuming)
            }

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
        # **놓인 것이 없으면 치울 것도 없다** (Phase 6-K). ``None`` 은
        # 배치가 없는 발동이고, 그 카드는 해결 뒤 묘지로 가지 않는다.
        if placed is not None:
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
