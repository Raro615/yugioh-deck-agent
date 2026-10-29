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
from engine.activation_timing import (
    ActivationStage,
    ActivationTiming,
    ActivationTimingChecker,
)
from engine.chain import Chain
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
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
    effect_kind_of,
)
from engine.summon import duel_executor
from engine.turn_progression import ProgressionStatus, TurnProgressor
from engine.validation import (
    CODE_VALIDITY,
    ActionValidity,
    ValidationCode,
    ValidationResult,
)
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
#: 🔴 **규칙이 기회를 열었는데 실행 구현이 없을 때 빠진 것** (6-AB 추가 보완).
#:
#: 판이 바뀌어도 풀리지 않고 **구현이 생겨야** 풀리므로 보류의 ``missing``
#: 에 적는다. 조용히 넘기면 읽는 쪽이 "유발이 없다" 로 읽는다 — 그것과
#: "유발이 있는데 처리할 수 없다" 는 다른 사실이다.
TRIGGER_IMPLEMENTATION_MISSING = (
    "이 유발 효과의 실행 구현 (6-AB 추가 보완 — 규칙은 기회를 열었는데 "
    "저장소에 그 효과를 실행할 코드가 없다)"
)

MANDATORY_TRIGGER_UNPLAYABLE = (
    "강제 유발의 발동 절차 (Phase 6-AB — 규칙이 요구하는데 관문이 허가하지 "
    "않아 이 진행이 규칙대로인지 보장할 수 없다)"
)

#: **판이 열린 상태(box A)에서만 할 수 있는 행동들** (Phase 6-AB 보완8).
#:
#: 근거는 공식 Fast Effect Timing 도표의 두 문장이다 — *"Many actions can
#: ONLY be performed when the game state is open (when you're in box A)."* ·
#: *"Whenever either player performs an action, the game state is no longer
#: open."* 그래서 유발 처리 기회 · 빠른 효과 기회 · 체인 응답 단계에서는
#: 이 다섯을 할 수 없다.
#:
#: 🔴 **``ACTIVATE_EFFECT`` 와 ``PASS`` 는 여기 없다.** 발동은 그 단계들에서도
#: 할 수 있고 (적법성은 스펠 스피드 관문이 정한다), ``PASS`` 는 그 기회를
#: 지나가는 수단이다.
#:
#: 🔴 **목록이 한 벌이다.** 전에는 "유발 등재 단계가 닫는 것" 을
#: :meth:`Duel._enforce_mandatory` 가 허가 목록에서 거르는 방식으로만 적었고,
#: 빠른 효과 기회 쪽은 후보를 **아예 만들지 않아** 이유가 남지 않았다
#: (실측: 보완8 §2 A5 · A6 — ``apply`` 가 "지금 허가된 행위가 아닙니다" 로
#: ``RULE_NOT_IMPLEMENTED`` 를 돌려주었다).
OPEN_STATE_ONLY_KINDS: tuple[PlayerActionKind, ...] = (
    PlayerActionKind.NORMAL_SUMMON,
    PlayerActionKind.SPECIAL_SUMMON,
    PlayerActionKind.SET_MONSTER,
    PlayerActionKind.SET_SPELL_TRAP,
    PlayerActionKind.CHANGE_POSITION,
    PlayerActionKind.ATTACK,
    PlayerActionKind.CHANGE_PHASE,
    PlayerActionKind.END_PHASE,
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

    ``code`` (Phase 6-AB 보완8)
    --------------------------
    **어느 종류의 거절인가**를 구조로 적는다. 전에는 ``missing`` 이 비었는지로
    읽는 쪽이 짐작해야 했고, 그래서 ``deck/opening.py`` 는 그 규칙을 손으로
    한 번 더 적었다. 지금은 :data:`~engine.validation.CODE_VALIDITY` 가
    코드마다 ``INVALID`` / ``UNKNOWN`` 을 말하므로 **읽는 쪽이 문장을 파싱할
    필요가 없다** (사용자 요구 ③-6).

    ``missing`` 과 **어긋나지 못한다** — 아래 ``__post_init__`` 가 둘의
    일치를 강제한다. 확정 거부에 "무엇이 없어서" 를 붙이면 규칙이 막은 것이
    미지원으로 집계되고 (보완6 이 고친 바로 그 혼동), 모름에서 그것을 빼면
    무엇을 고쳐야 하는지가 사라진다.

    🔴 **식별자는 여전히 들고 있지 않다** (Phase 3-E-41 의 invariant).
    ``source`` · ``action`` · ``instance_id`` 를 더하지 않았다 —
    ``HIDDEN_CARD`` 처럼 **가려진 것을 가리키는** 판정에서 식별자가 함께
    새어 나갈 길이 열리기 때문이다. 어느 효과인지가 필요한 자리는
    ``reason`` 안에 ``EffectRef`` 를 적는다 (``_trigger_actions`` 가 이미
    쓰는 방식이고, ``EffectRef`` 는 그 자리가 들고 있는 자기 카드의 것이다).
    """

    kind: PlayerActionKind
    reason: str
    code: ValidationCode
    missing: str | None = None
    scope: str | None = None
    """
    **이 거절이 몇 자리에 걸린 것인가** — 한 스냅샷 안에서만 뜻이 있는 메모
    (Phase 6-AB 보완8 마무리).

    예: ``"패 5장 중 5장"``. 읽는 쪽이 "한 장만 걸렸는가 전부 걸렸는가" 를
    가를 수 있게 한다 (사용자 요구 ③ — *"어느 범위의 제한인지 소비자가
    구분할 수 있게"*).

    🔴 **쌓아 모으는 목록의 열쇠에 넣지 않는다.** 이 수는 걸음마다 달라지므로
    (패가 줄어든다) 문장에 섞으면 **같은 사유가 걸음 수만큼 쌓인다** —
    실측으로 ``/combo`` 의 미지원 목록이 1건에서 5건으로 늘었고 다섯 줄이
    같은 사유였다. 그래서 자리를 따로 둔다: 한 자리의 표시에는 싣고,
    누적에는 싣지 않는다 (:meth:`line_ko`).

    🔴 **수만 적는다. 어느 카드인지는 적지 않는다** — 3-E-41 의 invariant.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.code, ValidationCode):
            raise TypeError(
                f"code 는 ValidationCode 입니다: {self.code!r}"
            )
        validity = CODE_VALIDITY[self.code]
        if validity is ActionValidity.INVALID and self.missing:
            raise ValueError(
                f"{self.code.value} 는 규칙이 금지한다는 뜻인데 없는 것이 "
                f"적혀 있습니다: {self.missing!r}. 확정 거부를 미지원으로 "
                "집계하게 됩니다."
            )
        if validity is ActionValidity.UNKNOWN and not self.missing:
            raise ValueError(
                f"{self.code.value} 는 판정하지 못했다는 뜻인데 **무엇이 "
                "없어서인지** 적지 않았습니다. 그러면 고칠 자리를 알 수 "
                "없습니다."
            )
        if validity is ActionValidity.VALID:
            raise ValueError(
                f"{self.code.value} 는 통과를 뜻하므로 보류의 이유가 될 수 "
                "없습니다."
            )

    @property
    def validity(self) -> ActionValidity:
        """이 거절이 **규칙 거절인가 모름인가.** 코드에서 파생된다."""
        return CODE_VALIDITY[self.code]

    @property
    def is_rule_refusal(self) -> bool:
        """확인된 규칙이 막았는가 (``INVALID``)."""
        return self.validity is ActionValidity.INVALID

    def line_ko(self, *, with_scope: bool = True) -> str:
        """
        읽을 수 있는 한 줄. ``with_scope=False`` 면 :attr:`scope` 를 뺀다.

        🔴 **누적 목록은 ``with_scope=False`` 로 모은다** — 그 메모가 걸음마다
        달라져서 같은 사유를 여러 줄로 만들기 때문이다 (:attr:`scope`).
        """
        line = f"{self.kind.value} [{self.missing}]: {self.reason}"
        if with_scope and self.scope:
            line += f" ({self.scope})"
        return line


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

    def unsupported(self) -> tuple[WithheldAction, ...]:
        """
        보류 가운데 **빠진 규칙의 이름이 붙은 것**들 (Phase 6-AB 최종 보완).

        🔴 "규칙이 막았다" 와 "이 저장소에 그 규칙이 없다" 를 가른다.
        ``missing`` 이 붙은 보류만 둘째다 — 그 이름이 **무엇이 없어서**
        후보가 오르지 못했는지 말한다 (``TRIGGER_IMPLEMENTATION_MISSING``
        등). 이름이 없는 보류는 규칙이 답한 것이고, 그것은 미지원이 아니다.

        읽는 쪽이 이 구분을 못 하면 "후보가 흐름뿐" 이라는 사실이 "전개가
        끝났다" 로 읽힌다 — 실제로는 **지원하지 않아 오르지 못한 후보**가
        있는 자리인데도. 그 혼동이 6-AB 최종 보완의 ④ 다.
        """
        return tuple(held for held in self.withheld if held.missing)

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
    :attr:`window_floor` 와 :meth:`_window_admits` 의 일이다. 이 바닥은
    **페이즈 경계**만 본다: 둘은 다른 축이고, 어느 한쪽으로 다른 쪽을 흉내
    내면 적법한 기회를 닫거나 지나간 기회를 연다.

    🔴 6-AA 가 이 자리를 ``BLOCKER-6AA-2`` 로 적으며 **근거 없는 일괄
    규칙**("다음 행동이면 만료") 을 만들지 않은 것은 옳았다. 그 규칙을
    세웠다면 「경우」 효과의 적법한 기회를 닫았을 것이다. 6-AB 보완이 그
    자리를 **일괄 규칙이 아닌 방식**으로 채웠고, 6-AB 추가 보완이 그 방식을
    :attr:`window_floor` 로 바꿨다 — 행동 종류를 열거하지 않고 "창이 어디서
    시작했는가" 하나로 답한다.
    """
    window_floor: int = 0
    """
    **지금 열려 있는 유발 처리 기회가 덮는 첫 기록 번호** (6-AB 추가 보완).

    이 번호보다 **앞의** 사건은 그 기회가 지나간 것이므로 발동을 열지
    않는다. 담는 것은 ``JournalEvent.sequence`` 와 같은 축이고, 새 식별자를
    만들지 않는다.

    🔴 **이 칸이 ``declined_events`` 를 대체한다.** 6-AB 보완은 "그 자리가
    적법하게 포기했다" 를 ``(사건, 효과, 개체, 자리)`` 네 짝으로 적었고
    ``_apply_board`` 가 수락될 때만 적었다. 셋이 틀렸다:

    1. **행동 종류마다 포기 코드를 붙이는 구조**였다. 그래서 효과 발동과
       ``PASS`` 는 기회를 닫지 않았고, 실측: 기르수 소환 뒤 **다른 효과**
       (어리석은 매장)를 발동해 해결까지 간 뒤에도 기르수 유발이 다시
       후보였다 (포기 기록 0 · 제안 1).
    2. **기회를 식별하는 방법이 우연에 의존했다.** 행동 **전** 후보 목록의
       ``(개체, 효과)`` 와 행동 **뒤** 제안을 맞춰 보았으므로, 같은 개체 ·
       같은 효과의 **다른 사건** 제안이 끼면 잘못 닫혔다.
    3. ``PASS`` 를 어떻게 볼지 답할 수 없었다 — 체인에 응수하지 않겠다는
       패스와 기회를 포기하는 패스가 구별되지 않았다.

    🔴 **대신 "지금 창이 어디서 시작했는가" 하나만 들고 있는다.** 창은 판이
    **open state** 로 돌아갈 때마다 새로 시작하고, 그 자리는 둘뿐이다 —
    체인을 시작하지 않는 행위 뒤, 그리고 체인이 완전히 해결된 뒤. 근거는
    공식 Fast Effect Timing 도표이고 (유발을 확인하는 자리가 그 둘이다),
    그래서 **행동 종류를 열거하지 않는다.**
    (https://www.yugioh-card.com/en/play/fast-effect-timing/)

    ``int`` 이므로 ``dataclasses.replace`` 가 값으로 가져간다 — 탐색 사본의
    창 이동이 부모를 건드리지 않는다.
    """
    window_passed: frozenset = frozenset()
    """
    **이 창에서 유발 선택을 마친 자리들** (최종 보완).

    담는 것은 ``seat`` 정수다. 공식 Fast Effect Timing 도표에서 유발 처리
    기회는 **양쪽이 다 지나가야** 닫힌다 — 턴 플레이어가 먼저 고르고, 그
    다음 상대가 고르고, 둘 다 더 할 것이 없으면 판이 **open state** 로
    돌아간다.

    🔴 **왜 필요한가 — 실측한 결함이다** (BLOCKER-F2-1). 6-AB 추가 보완의
    ``window_floor`` 는 값 **하나**여서 자리를 가르지 않았다. 그래서 내가
    세트를 하자 상대의 임의 유발 기회가 **확인되기 전에 닫혔다**:

        상대 제안 1 · 창 판정 True
        내 세트 수락 True
        🔴 상대 제안 1 · 창 판정 False · 상대 후보 False
        🔴 END_PHASE 수락 True

    🔴 **창을 자리별로 나누는 것만으로는 끝나지 않는다.** 상대가 **실제로
    고를 기회를 받아야** 하므로 :attr:`to_act` 가 그 자리를 가리키고
    (:meth:`_window_actor`), 그 자리에는 발동과 **포기**(``PASS``)가 함께
    오른다. 포기가 없으면 고를 것이 없어 멈춘다.

    🔴 **묻는 것도, 거절된 행동도 여기 적히지 않는다** — 수락된 ``PASS``
    하나만 적는다. 창이 옮겨가면 비워진다.

    ``frozenset`` 이므로 ``dataclasses.replace`` 가 값으로 가져간다 — 한
    분기의 포기가 다른 분기의 기회를 닫지 않는다.
    """
    chain_floor: int = -1
    """
    **지금 쌓이고 있는 체인이 시작된 기록 번호.** 체인이 없으면 ``-1``.

    이것이 "같은 기회의 다른 유발" 과 "체인 도중에 새로 생긴 사건" 을 가른다
    (6-AB 추가 보완):

    ==========================================  ==========================
    ``window_floor <= 사건 번호 < chain_floor``   같은 기회다 → **같은 체인에
                                                 쌓을 수 있다**
    ``사건 번호 >= chain_floor``                  체인 도중에 생겼다 →
                                                 **보존하고 기다린다**
    ==========================================  ==========================

    🔴 **실측으로 고친 결함이다.** 6-AB 보완은 ``chain.is_empty`` 하나로
    판정해서 체인이 쌓이면 **모든** 유발을 막았다. 그래서 한 사건이 유발
    둘을 일으킬 때 첫 발동 뒤 둘째가 후보에서 **사라졌다** (실측: 후보 1건
    → 발동 뒤 0건). 룰북은 그 둘을 **같은 특수 체인**에 쌓는다고 적는다
    (§*When multiple cards are activated simultaneously*).

    🔴 **체인 구성 중과 체인 해결 중을 같은 뜻으로 쓰지 않는다.** 이 칸은
    **구성 · 응답** 단계의 질문에만 답한다. 해결은 :meth:`_resolve_chain`
    안에서 한 번에 일어나고 그 사이에 ``legal_actions`` 가 불리지 않으므로,
    "해결 중의 판정" 이라는 것은 이 엔진에 없다 — 해결이 끝나면
    :attr:`window_floor` 가 이 값으로 올라간다.
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
        if duty is not None:
            return duty
        # 🔴 **임의 유발도 자리를 가리킨다** (최종 보완). 그러지 않으면
        # 상대의 기회가 아무에게도 물어지지 않고, 내 다음 행동이 그것을
        # 닫는다 (:attr:`window_passed` 의 실측).
        claimant = self._window_actor()
        return ordinary if claimant is None else claimant

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
        if self._resolving_other_window():
            # 이전 창에서 시작한 체인을 처리 중이다 — 그 체인이 먼저이고
            # (聖鳥クレイン 재정) 의무는 보존된다.
            return None
        for seat in (self.turn_player, 1 - self.turn_player):
            if self._window_group(
                seat, mandatory=True
            ) and self._window_can_act(seat):
                # 🔴 **처리할 수 있는 의무만** 가리킨다 (6-AB 보완4가
                # ``_window_can_act`` 로 좁혔다). 관문이 막은 의무로 자리를
                # 옮기면 그 자리에 고를 것이 없어 듀얼이 멈춘다 — 그 사실은
                # ``_enforce_mandatory`` 가 ``MANDATORY_TRIGGER_UNPLAYABLE``
                # 로 적고 흐름은 막지 않는다.
                return seat
        return None

    def _resolving_other_window(self) -> bool:
        """
        **이 창이 아닌 체인을 처리 중인가** (6-AB 보완4).

        유발 등재 중에는 체인이 이미 비어 있지 않다 — 첫 링크가 올라가
        있다. 그래서 "체인이 비었는가" 로 창의 생존을 물으면 **같은 기회의
        둘째 유발이 영원히 등재되지 않는다** (실측: 첫 등재 뒤
        ``_window_actor()`` 가 ``None`` 이 되고 ``to_act`` 가 상대로 넘어가
        남은 내 유발을 아무도 묻지 않았다).

        가르는 것은 :attr:`chain_floor` 다 — 0 이상이면 **이 창에서 시작한**
        체인이고, ``-1`` 인데 체인이 있으면 이전 창의 것이다.
        """
        if self.triggers is None:
            return True
        return not self.chain.is_empty and self.chain_floor < 0

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
            opened, held = self._activation_actions(seat, validator)
            allowed.extend(opened)
            withheld.extend(held)
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
            opened, held = self._activation_actions(seat, validator)
            allowed.extend(opened)
            withheld.extend(held)

        # 🔴 **판이 열려 있지 않으면 그 사실을 적는다** (보완8).
        #
        # 위 두 갈래는 열린 상태 전용 행동의 후보를 **아예 만들지 않는다** —
        # 그래서 이유도 남지 않았고, ``apply`` 는 "지금 허가된 행위가
        # 아닙니다" 에 ``RULE_NOT_IMPLEMENTED`` 를 붙여 돌려주었다. 규칙이
        # 막은 것을 **엔진 미지원**으로 적는 바로 그 혼동이다.
        withheld.extend(self._stage_closed_actions(seat))

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
                        ValidationCode.MANDATORY_TRIGGER_PENDING,
                    )
                )
            return LegalActions(seat, (), tuple(withheld))

        # 🔴 **다른 자리의 임의 유발 창도 닫히기 전에는 지나갈 수 없다**
        # (최종 보완 ②, BLOCKER-F2-1).
        #
        # 6-AB 추가 보완은 **강제만** 보았다 (위 블록). 그래서 상대가 임의
        # 유발 기회를 들고 있으면 내 다음 행동이 그것을 **확인되기 전에**
        # 닫았다. 실측::
        #
        #     상대 제안 1 · 창 판정 True
        #     내 세트 수락 True
        #     🔴 상대 제안 1 · 창 판정 False · 상대 후보 False
        #     🔴 END_PHASE 수락 True
        #
        # 근거는 공식 Fast Effect Timing 도표다 — 그 확인 자리는 **양쪽이
        # 다 지나가야** 닫히고, 그 다음에 판이 open state 로 돌아간다.
        #
        # 🔴 **내 창이 내 행동을 좁히지는 않는다.** 임의 유발은 그 controller
        # 를 강제하지 않는다 — 6-AA 가 세운 강제 · 임의의 구분이고
        # ``test_b01`` 이 그것을 센다 (*"임의 유발은 페이즈 전환을 막지
        # 않는다"*). 그 자리에서 다른 일을 고르는 것이 **그 자리의 포기**
        # 이고, 그때 창은 :attr:`window_floor` 로 옮겨 간다 (``test_b02``).
        # 이 블록을 한 번 그렇게(내 창도 내 행동을 좁히도록) 썼고, 그것이
        # 그 구분을 지웠다 — 실측으로 ``END_PHASE`` 가 임의 유발에 막혔다.
        #
        # 🔴 **그래서 남는 구멍을 적어 둔다**: 두 자리가 **같은 사건**에
        # 기회를 들고 있으면 턴 플레이어가 다른 일을 골라 상대의 기회까지
        # 함께 닫을 수 있다. 실제 데이터로는 밟을 수 없다 — 실행 등재된
        # 유발은 한 카드의 효과 하나이므로 두 자리가 같은 사건에 기회를
        # 드는 일이 없다. 보고서에 **부분 완료**로 적는다.
        #
        # 🔴 **멈추지 않는다**: 가리켜진 자리에는 발동 후보와 ``PASS`` 가
        # 함께 오르므로 (``_flow_actions``) 고를 것이 반드시 있다.
        claimant = self._window_actor()
        if claimant is not None and claimant != seat:
            for kind in sorted(
                {action.kind for action in allowed}
                or {PlayerActionKind.ACTIVATE_EFFECT},
                key=lambda kind: kind.value,
            ):
                withheld.append(
                    WithheldAction(
                        kind,
                        f"P{claimant} 의 유발 처리 기회가 아직 열려 있습니다 "
                        "— 그 자리가 발동하거나 포기하기 전에는 진행할 수 "
                        "없습니다 (공식 Fast Effect Timing — 그 기회는 양쪽이 "
                        "다 지나가야 닫힙니다).",
                        ValidationCode.STAGE_FORBIDS_ACTION,
                    )
                )
            return LegalActions(seat, (), tuple(withheld))

        if claimant == seat:
            # 🔴 **판이 열린 상태가 아니다** (6-AB 보완4, 목표 ①).
            #
            # 공식 Fast Effect Timing 도표: *"Many actions can ONLY be
            # performed when the game state is open (when you're in box
            # A)."* · *"Whenever either player performs an action, the game
            # state is no longer open."* 유발 처리 기회는 box A 가 아니므로,
            # 그 기회가 닫히기 전에는 통상 소환 · 세트 · 기동 효과 · 페이즈
            # 이동을 할 수 없다. 판이 다시 열리는 조건도 그 도표가 적는다 —
            # 턴 플레이어가 넘기고, 상대가 되돌려 넘기고, 체인이 없을 때다.
            #
            # 🔴 **최종 보완이 이 자리를 비워 두었고 그것이 BLOCKER-F3-1
            # 이었다.** 그때의 근거는 "임의 유발은 controller 를 강제하지
            # 않는다" 였는데, 그 문장은 **발동을 강제하지 않는다**는 뜻이고
            # "그 기회를 열어 둔 채 다른 일을 해도 된다"는 뜻이 아니다. 둘을
            # 섞으면 내 일반 행동 하나가 상대의 미처리 기회까지 닫는다
            # (실측: 내 세트 수락 → 상대 claims 1 → 0 → 내 END_PHASE 수락).
            #
            # 강제 · 임의의 구분은 **그대로 남는다**: 임의 묶음이면 ``PASS``
            # 가 함께 오르고 (``_flow_actions``) 한 걸음으로 포기할 수 있다.
            # 강제 묶음이면 ``PASS`` 가 오르지 않는다.
            duty_claims = self._window_group(seat, mandatory=True)
            claims = duty_claims or self._window_group(seat, mandatory=False)
            keep = [
                action
                for action in allowed
                if action.kind is PlayerActionKind.PASS
                or (
                    action.kind is PlayerActionKind.ACTIVATE_EFFECT
                    and any(
                        action.source == offer.source
                        and action.effect_ref == offer.effect_ref
                        for offer in claims
                    )
                )
            ]
            if keep:
                # 🔴 **비어 있으면 닫지 않는다** — 관문이 그 묶음을 전부
                # 막았고 ``PASS`` 도 오르지 않은 자리다. 닫으면 고를 것이
                # 없어 듀얼이 멈추므로, 아래 의무 블록이 그 사실을
                # ``MANDATORY_TRIGGER_UNPLAYABLE`` 로 적게 둔다.
                # 🔴 **막는 근거가 더 강한 쪽을 적는다.** 강제 묶음이면
                # "규칙이 요구한 처리" 가 이유이고, 임의 묶음이면 "판이
                # 열린 상태가 아니다" 가 이유다. 둘을 한 문장으로 적으면
                # 읽는 쪽이 강제와 임의를 가를 수 없다 (6-AA 의 구분).
                reason = (
                    f"강제 유발 {len(duty_claims)}건을 먼저 처리해야 "
                    "합니다 — 규칙이 요구한 처리를 넘기고 다른 것을 할 수 "
                    "없습니다."
                    if duty_claims
                    else (
                        "유발 처리 기회가 열려 있습니다 — 판이 열린 상태가 "
                        "아니므로 그 기회를 처리한 뒤에 진행합니다 (공식 "
                        "Fast Effect Timing — box A 에서만 할 수 있는 "
                        "행동입니다)."
                    )
                )
                # 🔴 **코드도 이유와 함께 갈린다** (보완8). 강제면 "규칙이
                # 요구한 처리가 남았다", 임의면 "이 단계가 금지한다" 이고,
                # 둘 다 **확정 거부**다 — 전에는 둘 다 ``missing`` 없는
                # 보류였고 ``apply`` 는 그것을 읽지 않아
                # ``RULE_NOT_IMPLEMENTED`` 로 보고했다 (실측: 보완8 §2 B2).
                code = (
                    ValidationCode.MANDATORY_TRIGGER_PENDING
                    if duty_claims
                    else ValidationCode.STAGE_FORBIDS_ACTION
                )
                # 🔴 **종류별로 하나만 적는다** (사용자 요구 ③-8). 전에는
                # 허가 목록을 돌며 후보마다 적었고, 그래서 패에 세울 카드가
                # 셋이면 같은 문장이 세 번 나왔다 (실측: 보완8 §2 B2).
                for kind in sorted(
                    {action.kind for action in allowed if action not in keep},
                    key=lambda k: k.value,
                ):
                    withheld.append(WithheldAction(kind, reason, code))
                allowed = keep

        forced = self._mandatory_offers(seat)
        if not forced:
            return LegalActions(seat, tuple(allowed), tuple(withheld))

        # 🔴 **처리할 수 없는 의무를 먼저 본다** (6-AB 보완4가 이 검사를
        # ``to_act`` 비교보다 **앞으로** 옮겼다).
        #
        # 전에는 ``to_act != seat`` 가 먼저여서, 이 자리가 처리할 수 없는
        # 의무를 들고 있으면 ``_window_actor`` 가 그 자리를 건너뛰고
        # (``_window_can_act`` 가 거짓이므로) 보류가 "지금 고르는 자리가
        # 아닙니다" 로 적혔다 — **미지원 사유가 사라졌다.** 규칙이 요구한
        # 처리를 보장할 수 없다는 사실이 가장 중요한 정보이므로 순서를
        # 바꿨다. 🔴 **자리는 그대로 하나다** — 이유를 두 곳에서 적지 않는다.
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
            #
            # 🔴 **흐름은 막지 않는다**: 막으면 양쪽 모두 고를 것이 없어
            # 듀얼이 그 자리에서 멈춘다.
            withheld.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_EFFECT,
                    f"강제 유발 {len(forced)}건이 열려 있는데 발동 관문을 "
                    "지나지 못했습니다 — 이 진행이 규칙대로인지 보장할 수 "
                    "없습니다 (흐름은 막지 않습니다: 막으면 고를 것이 없어 "
                    "듀얼이 멈춥니다).",
                    ValidationCode.RULE_NOT_IMPLEMENTED,
                    missing=MANDATORY_TRIGGER_UNPLAYABLE,
                )
            )
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
                    ValidationCode.NOT_PRIORITY_HOLDER,
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
                    ValidationCode.MANDATORY_TRIGGER_PENDING,
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
        # 🔴 **관문이 낸 판정을 버리지 않는다** (Phase 6-AB 보완8).
        #
        # 여기는 거절된 후보를 조용히 ``continue`` 했고, 그래서 호출자는 셋을
        # 가를 수 없었다 — *후보가 애초에 없었다* · *규칙이 막았다* ·
        # *판정하지 못해 빼놓았다*. 실측 (보완8 §2 A1~A3): 빠른 효과 기회의
        # 욕망의 항아리 · 어니스트 · 세트한 턴의 함정 셋 모두 ``apply`` 는
        # 정확한 코드를 돌려주는데 보류는 **0건**이었다.
        #
        # 🔴 **같은 이유를 한 번만 적는다** (사용자 요구 ③-8). 대상 조합마다
        # 적으면 같은 문장이 조합 수만큼 쌓인다. 묶는 열쇠는 (효과 · 코드 ·
        # 모자란 것) 이고, 효과 식별은 ``reason`` 안에 남는다.
        #
        # 🔴 **일부 조합만 거절된 경우를 숨기지 않는다** — 허가 목록은 그대로
        # 이므로 다른 조합은 후보로 남고, 이 보류는 "그 조합이 왜 안 되는가"
        # 로 함께 읽힌다 (``allowed`` 와 비교하면 갈린다).
        refusals: dict[tuple, WithheldAction] = {}
        for card in self._activation_sources(seat):
            for effect_ref in activatable_effects(card.card_id):
                definition = self._activator.definitions.definition_for(effect_ref)
                if definition is None:  # pragma: no cover - 목록이 보증한다
                    continue
                if definition.cost.costs:
                    # 🔴 **비용 있는 효과는 관문을 지나지 않는다** — 그래서
                    # 여기서 적을 판정이 없다. 이 자리의 한계는 보고서가
                    # 적는다 (등재된 효과 전부가 비용이 없으므로 지금은
                    # 아무것도 걸리지 않는다 — STRUCTURAL-120).
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
                    gate = self._activation_gate(
                        candidate, validator=validator, selections=selections
                    )
                    if gate.validity is not ActionValidity.VALID:
                        # ``missing`` 은 관문이 말한 것을 따른다 — 모른다고
                        # 하면 채우고, 규칙이 금지한다고 하면 비운다
                        # (``_trigger_actions`` 와 **같은 기준**이다).
                        key = (effect_ref, gate.code, gate.missing_rule)
                        refusals.setdefault(
                            key,
                            WithheldAction(
                                PlayerActionKind.ACTIVATE_EFFECT,
                                f"{effect_ref} 를 지금 발동할 수 없습니다: "
                                f"{gate.reason}",
                                gate.code,
                                missing=(
                                    gate.missing_rule
                                    if gate.validity is ActionValidity.UNKNOWN
                                    else None
                                ),
                            ),
                        )
                        continue
                    allowed.append(candidate)
        return allowed, tuple(refusals.values())

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

        🔴 ``seat`` 를 받는다 (6-AB 보완). 기회는 자리마다 따로 열리므로
        (룰북 ``TURN PLAYER'S PRIORITY``) 자리를 모르면 답할 수 없다.
        """
        if not (offer.is_optional or offer.is_mandatory):
            return False
        return self._window_admits(offer, seat) is True

    def _window_admits(self, offer, seat: int) -> "bool | None":
        """
        이 제안을 **지금 이 자리에서 발동할 수 있는가.** 모르면 ``None``.

        단계를 넷으로 가른다 (6-AB 추가 보완). 6-AB 보완은 ``chain.is_empty``
        하나로 두 단계만 보았고, 그래서 **같은 기회의 다른 유발**과 **체인
        도중에 생긴 새 사건**이 같은 답을 받았다 (:attr:`chain_floor`).

        =====================================  =============================
        단계                                     답
        =====================================  =============================
        사건이 지나간 창                        ``False`` — 그 기회는 끝났다
        체인 구성·응답 중 · 체인 도중의 사건      ``False`` — 보존하고 기다린다
        그 밖                                   :meth:`_missed_timing` 에 맡긴다
        =====================================  =============================

        🔴 **마지막 줄이 ①이 고친 자리다** (6-AB 최종 보완). 6-AB 추가
        보완은 체인이 열려 있으면 ``return sequence < self.chain_floor`` 로
        **끝냈다** — 그 식은 "이 창의 사건인가" 만 묻고 **자격을 묻지
        않는다.** 그래서 같은 창의 사건이기만 하면 어휘를 읽지 못한 제안도
        ``True`` 를 받을 수 있었다. 지금은 그 분기가 ``False`` 만 돌려주고,
        나머지는 **자격 검사로 떨어진다** — 체인이 열려 있든 없든 같은
        함수가 답한다.

        🔴 **실측: 그 구멍을 지금 데이터로는 밟을 수 없다.** 그 식이
        ``True`` 를 잘못 주는 구간은 ``floor ≤ sequence ≤ chain_floor - 2``
        인데, 이 저장소의 실제 경로에서 창은 사건 **하나**만 들고
        (``test_b04b``) ``chain_floor`` 는 언제나 그 사건 번호 + 1 이므로 그
        구간이 **비어 있다.** 즉 ①은 **구조적 결함**이고 실행 우회가
        재현된 것은 아니다 — 창이 사건 둘을 들게 되는 날 작동하는 보호다.
        그 구별을 보고서에도 그대로 적는다.

        🔴 **체인 분기가 자격보다 앞에 있는 이유.** 체인 **도중에** 생긴
        사건은 그 체인이 풀린 뒤의 창에서 처리하므로 (聖鳥クレイン 재정),
        "마지막에 일어난 일인가" 를 **지금** 묻는 것 자체가 틀린 질문이다.
        그래서 그 경우는 자격을 묻지 않고 보존한다 — 그렇게 두지 않으면
        체인 도중의 「때」 사건이 "타이밍을 놓쳤다" 로 적히고, 그것은
        :meth:`_trigger_actions` 가 적는 보존 이유와 **어긋난다.**

        🔴 **``None`` 을 ``True`` 로 접지 않는다** (리뷰 A). 6-AB 보완은
        마지막 줄이 ``return self._missed_timing(offer) is not True`` 였고,
        그래서 ``None``(판정 근거 없음)이 **``True``** 가 됐다. 실측: 어휘를
        모르는 제안이 ``_window_admits`` → ``True`` · ``event_backed`` 에
        **들어갔고**, 막는 것은 ``legal_actions`` 의 보류 하나뿐이었다 —
        내부 관문과 후보 목록의 답이 갈라진 것이다.

        🔴 **그때도 직접 ``apply`` 는 거절됐다** (후보 검사에서). 그래서
        이것은 **내부 판정 불일치**이고 실행 우회가 재현된 것은 **아니다** —
        그 구별을 보고서에도 그대로 적는다.

        지금은 ``None`` 을 그대로 돌려주고, :meth:`_offer_is_activatable` 이
        ``is True`` 만 통과시키므로 모름은 **어느 관문도 열지 않는다.**
        """
        sequence = getattr(offer, "event_sequence", -1)
        floor = max(self.timing_floor, self.window_floor)
        if sequence < floor:
            # 지나간 창의 사건이다 — 제안은 보존되지만 발동은 열리지 않는다.
            return False

        if seat in self.window_passed:
            # 🔴 **그 자리가 이 창에서 발동하지 않기로 했다** (최종 보완).
            # 포기가 후보를 실제로 닫지 않으면 ``PASS`` 는 아무 일도 하지
            # 않은 것이고, 상대의 기회를 "물었다" 고 말할 수 없다.
            # 제안은 보존된다 — 닫힌 것은 **이 창에서의 그 자리**다.
            return False

        if self.chain_floor >= 0 and not self.chain.is_empty:
            if sequence >= self.chain_floor:
                # 체인 **도중에** 생긴 사건이다 — 기회는 보존되지만 이 체인에
                # 끼워 발동하지 않는다 (聖鳥クレイン 재정). 여기서 자격을
                # 묻지 않는 이유는 위 설명의 마지막 항목이다.
                return False
            # 같은 기회의 다른 유발이다 — 같은 체인에 쌓을 수 있다 (룰북
            # §When multiple cards are activated simultaneously). 🔴 여기서
            # **끝내지 않는다** — 자격 검사로 떨어진다 (①).

        # 🔴 **① 자격은 체인 유무와 무관하게 이 한 자리가 답한다.**
        #
        # ``_missed_timing`` 의 ``True`` 는 "놓쳤다" 이고 이 함수의 ``True``
        # 는 "발동할 수 있다" 이므로 **극성을 뒤집어서** 쓴다.
        missed = self._missed_timing(offer)
        if missed is None:
            # 판정 근거가 없다 — 허가로도 금지로도 바꾸지 않는다.
            return None
        return not missed

    def _window_claims(self, seat: int) -> tuple:
        """
        이 자리가 **이 창에서 아직 고를 수 있는** 유발 제안들 (최종 보완).

        🔴 **자격이 확인된 것만**이다 (:meth:`_offer_is_activatable`) — 판정
        불가는 들어오지 않는다. 그래야 "모른다" 가 흐름을 막지 않는다.

        🔴 **이미 지나간 자리는 빈 짝**이다 (:attr:`window_passed`).
        """
        if seat in self.window_passed:
            return ()
        return tuple(
            offer
            for offer in self._trigger_offers(seat)
            if self._offer_is_activatable(offer, seat)
        )

    def _window_group(self, seat: int, *, mandatory: bool) -> tuple:
        """
        그 자리의 이 창 claims 가운데 **SEGOC 한 묶음** (6-AB 보완4).

        룰북 §*When multiple cards are activated simultaneously* 가 묶음을
        넷으로 적는다 — *"the turn player builds the Chain starting with
        their mandatory effects, in any order. Then the opponent continues
        the Chain with their mandatory effects in any order. Afterwards, the
        turn player adds their optional effects in any order, and finally
        the opponent adds their optional effects in any order."*

        이 함수는 **(자리 × 강제 여부)** 한 칸을 돌려주고, 묶음 사이의
        순서는 :meth:`_window_actor` 가 정한다. 묶음 **안**의 순서는
        고르는 쪽의 것이다 (*"in any order"*).
        """
        return tuple(
            offer
            for offer in self._window_claims(seat)
            if offer.is_mandatory is mandatory
        )

    def _window_can_act(self, seat: int) -> bool:
        """
        그 자리가 이 창에서 **실제로 고를 것이 있는가** (6-AB 보완4).

        🔴 **관문까지 본다.** :meth:`_window_claims` 는 창과 강제 · 임의만
        보므로 (``_offer_is_activatable``) 관문이 거절할 제안도 claim 으로
        센다 — 예: 그 카드를 쥐고 있지 않은 자리 (BLOCKER-F3-5). 그 자리를
        가리키면서 다른 자리를 막으면 **양쪽 다 고를 것이 없어 듀얼이
        멈춘다** (실측: 상대의 강제 claim 이 관문에 막혀 양쪽 허가가 전부
        빈 목록이 되었다).

        🔴 **임의 묶음이면 묻지 않는다** — ``PASS`` 가 함께 오르므로
        (:meth:`_flow_actions`) 고를 것이 반드시 있다. 관문을 다시 돌리는
        비용은 **강제 묶음일 때만** 치른다.

        🔴 **되돌이가 없다.** :meth:`activation_validator` ·
        :meth:`_trigger_actions` · :meth:`_activation_gate` 는 ``to_act`` 도
        ``legal_actions`` 도 부르지 않는다 (AST 로 확인했다).
        """
        mandatory = self._window_group(seat, mandatory=True)
        if not mandatory:
            return bool(self._window_group(seat, mandatory=False))
        offers = self._trigger_offers(seat)
        opened, _withheld = self._trigger_actions(
            seat,
            self.activation_validator(seat, offers),
            tuple(
                offer
                for offer in offers
                if self._offer_is_activatable(offer, seat)
            ),
        )
        return any(
            any(
                action.source == offer.source
                and action.effect_ref == offer.effect_ref
                for offer in mandatory
            )
            for action in opened
        )

    def _window_actor(self) -> "int | None":
        """
        이 유발 처리 기회의 **등재 단계에서 지금 쌓을 자리**. 없으면 ``None``.

        순서는 룰북 §*When multiple cards are activated simultaneously* 의
        **네 묶음**이다 (:meth:`_window_group` 의 인용):

        ============  =========================================
        1             턴 플레이어의 **강제** 유발
        2             상대의 **강제** 유발
        3             턴 플레이어의 **임의** 유발
        4             상대의 **임의** 유발
        ============  =========================================

        🔴 **보완4가 고친 것이 이 순서다.** 최종 보완은 자리만 보고
        (``for seat in (turn_player, 1 - turn_player)``) 강제 · 임의를 섞었고,
        체인이 열리면 아예 답하지 않았다. 그래서 둘이 틀렸다 — 턴 플레이어의
        임의가 상대의 **강제**보다 먼저 물어질 수 있었고, 첫 유발이 등재되면
        남은 유발을 아무도 묻지 않았다 (실측: 첫 등재 뒤 ``to_act`` 가
        상대로 넘어가 그 자리의 허가가 ``['pass']`` 하나였다).

        🔴 **응답 단계가 시작되면 답하지 않는다** (``priority.is_open``).
        등재가 끝난 뒤에 빠른 효과 응답이 열리고, 그 뒤에 과거 유발을 다시
        끼워 넣지 않는다 (룰북 §6 의 *"이 단계에는 다른 효과가 끼어들 수
        없다"* 의 뒷면이다 — 반대로 응답이 시작된 뒤 등재로 돌아가지도
        않는다).

        🔴 **고를 것이 있는 자리만 가리킨다.** 그 자리에는 그 묶음의 발동
        후보가 오르고, 임의 묶음이면 ``PASS`` 도 함께 오른다
        (:meth:`_flow_actions`) — 그래서 멈추지 않는다.
        """
        if self._resolving_other_window():
            return None
        if self.priority.is_open:
            return None
        for mandatory in (True, False):
            for seat in (self.turn_player, 1 - self.turn_player):
                if self._window_group(
                    seat, mandatory=mandatory
                ) and self._window_can_act(seat):
                    return seat
        return None

    def _registration_is_open(self) -> bool:
        """유발 등재 단계가 아직 열려 있는가 (6-AB 보완4)."""
        return self._window_actor() is not None

    def _activation_stage(self) -> ActivationStage:
        """
        **흐름의 어느 단계인가** (Phase 6-AB 보완6).

        이 값을 아는 것은 판을 들고 있는 이 자리다 — 관측에도 없고 체인만
        으로도 갈리지 않는다. 그래서 읽어서
        :attr:`~engine.activation_timing.ActivationTiming.stage` 로 **값으로**
        넘긴다 (``point`` · ``set_this_turn`` · ``simultaneous`` 와 같은
        자리이고 같은 이유다 — ADR-007).

        🔴 **새 사실을 만들지 않는다.** 네 갈래가 전부 이미 들고 있는
        값에서 나온다.

        ======================  ============================================
        체인이 쌓여 있다          ``CHAIN_RESPONSE``
        우선권 기회가 열려 있다    ``FAST_WINDOW`` — 보완5 가 실은 상자 B · C
        유발 claim 이 남아 있다    ``TRIGGER_REGISTRATION``
                                (:meth:`_window_claims` — 관문을 지나지 않는다)
        그 밖                    ``OPEN`` — 상자 A
        ======================  ============================================

        🔴 **등재 단계를 ``_registration_is_open`` 으로 묻지 않는다.** 그쪽은
        :meth:`_window_actor` → :meth:`_window_can_act` → 관문을 지나고, 이
        함수의 답은 **그 관문이 쓰는 값**이다. 실측으로 재귀가 났다:

            _activation_gate → _activation_stage → _registration_is_open
            → _window_actor → _window_can_act → _trigger_actions
            → _activation_gate → …
            RecursionError: maximum recursion depth exceeded

        그래서 **관문을 지나지 않는 값**으로 묻는다 —
        :meth:`_window_claims` 는 창 · 강제/임의 · 자격만 보고
        (:meth:`_offer_is_activatable`) 관문을 돌리지 않는다. 그 결과
        "관문이 거절할 claim 만 남은 자리" 도 등재 단계로 세는데, **그것이
        맞다** — 기회는 열려 있고 고를 것이 없을 뿐이다. 그 자리에서
        고를 것이 없다는 판정은 :meth:`_window_can_act` 가 따로 한다.

        🔴 **우선권 기회를 등재보다 먼저 본다.** 빠른 효과 기회가 열린 뒤에는
        상자 B · C 이고, 남은 claim 이 있더라도 그 사실이 바뀌지 않는다.
        보완5 의 :meth:`_after_window_moved` 가 **등재가 끝난 뒤에만** 그
        기회를 열므로 두 갈래가 어긋나지 않는다.

        🔴 **페이즈 전환 창은 이 자리에 오지 않는다.** 이 모듈은 그 창을
        열지 않고, ``test_priority_response_audit.test_02`` 가 그 사실을
        **이 파일의 본문에서** 센다 — 그래서 그 창의 이름을 여기 적지
        않는다. 열게 되면 상자 A 가 아니므로 그때 갈래를 따로 적어야 한다.
        """
        if not self.chain.is_empty:
            return ActivationStage.CHAIN_RESPONSE
        if self.priority.is_open:
            return ActivationStage.FAST_WINDOW
        if self._window_claims(self.turn_player) or self._window_claims(
            1 - self.turn_player
        ):
            return ActivationStage.TRIGGER_REGISTRATION
        return ActivationStage.OPEN

    def _is_simultaneous(self, action: PlayerAction) -> bool:
        """
        이 발동이 **이 체인을 연 기회**의 것인가 (최종 보완).

        룰북 §*When multiple cards are activated simultaneously* 가 그
        묶음을 하나의 특수 체인에 쌓는다. 그래서 그 묶음의 발동은 **응수가
        아니고** 스펠 스피드 제약이 걸리지 않는다
        (:attr:`~engine.activation_timing.ActivationTiming.simultaneous`).

        판정은 :attr:`chain_floor` 하나로 한다 — 그 사건이 체인이 열리기
        **전**의 것이면 같은 기회이고, 체인 **도중**의 것이면 아니다. 같은
        비교를 :meth:`_window_admits` 가 쓰므로 두 자리가 갈라지지 않는다.

        🔴 **체인이 없으면 거짓**이다 — 그때는 애초에 응수가 아니므로 이
        값이 쓰이지 않는다 (관문이 먼저 통과시킨다).

        🔴 **유발이 아닌 발동에는 거짓**이다. 동시 발동 묶음은 유발 효과의
        것이고 (룰북이 *"like Trigger Effects"* 로 적는다), 기동 효과나
        카드 발동을 이 길로 넣으면 스펠 스피드 제약을 **면제해 주는** 구멍이
        된다.
        """
        if self.chain_floor < 0 or self.chain.is_empty:
            return False
        if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
            return False
        for offer in self._trigger_offers(action.actor):
            if (
                offer.source == action.source
                and offer.effect_ref == action.effect_ref
            ):
                return getattr(offer, "event_sequence", -1) < self.chain_floor
        return False

    def _window_horizon(self) -> int:
        """
        이 창에서 **"마지막에 일어난 일"** 을 재는 기준 번호 (최종 보완).

        🔴 **체인이 쌓이는 동안은 체인이 열리기 직전으로 고정한다.**

        왜 — 체인을 쌓는 일과 그것을 해결하는 일은 **기록을 남긴다.** 그
        기록을 기준으로 재면, 같은 기회에서 **적법하게 자격을 확인한 둘째
        유발**이 "그 사건은 더 이상 마지막이 아니다" 로 **만료된다.** 첫째
        유발을 등록했다는 사실이 둘째를 지우는 것이고, 룰북은 그 둘을 **같은
        특수 체인**에 쌓는다고 적는다 (§*When multiple cards are activated
        simultaneously*).

        🔴 **관리용 기록과 규칙상 처리 순서를 같다고 가정하지 않는다** —
        그것이 이 함수가 있는 이유다. ``JournalEvent.sequence`` 는 기록의
        순번이고, 창 안에서 "무엇이 마지막으로 일어났는가" 는 **그 창이
        열릴 때** 정해진다.

        체인이 없으면 기록의 마지막 번호다 (그때는 둘이 같다).
        """
        if self.chain_floor >= 0 and not self.chain.is_empty:
            return self.chain_floor - 1
        return (len(self.journal) - 1) if self.journal is not None else -1

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
        is_last = getattr(offer, "event_sequence", -1) == self._window_horizon()
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
                    ValidationCode.RULE_NOT_IMPLEMENTED,
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
                        ValidationCode.RULE_NOT_IMPLEMENTED,
                        missing=TRIGGER_REQUIREMENT_MISSING,
                    )
                )
                continue
            # 🔴 **세 이유를 따로 적는다** (6-AB 보완). 6-AB 는 셋을 한
            # 함수(``_timing_is_current``)로 섞어서 "체인 도중" 과 "포기했다"
            # 와 "어휘를 모른다" 가 같은 답으로 나왔다.
            sequence = getattr(offer, "event_sequence", -1)
            if sequence < max(self.timing_floor, self.window_floor):
                # 그 유발 처리 기회가 **끝났다** — 그 자리에서 유발 대신 다른
                # 것을 골랐거나 (판이 open state 로 돌아갔다) 체인이 해결돼
                # 새 창이 열렸다. 빠진 규칙이 아니라 **순서**이므로
                # ``missing`` 을 비운다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        "그 사건의 유발 처리 기회는 이미 끝났습니다 — 그 "
                        "자리에서 다른 절차로 넘어갔습니다.",
                        ValidationCode.NO_RESPONSE_WINDOW,
                    )
                )
                continue
            if self.chain_floor >= 0 and not self.chain.is_empty:
                if sequence >= self.chain_floor:
                    # 체인 **도중에** 생긴 사건이다 — 기회는 **보존되지만**
                    # 이 체인에 끼워 발동하지는 않는다 (聖鳥クレイン 재정).
                    # 빠진 규칙이 아니라 **순서**이므로 ``missing`` 을 비운다.
                    withheld.append(
                        WithheldAction(
                            PlayerActionKind.ACTIVATE_EFFECT,
                            "체인이 처리 중입니다 — 이 유발의 기회는 남아 "
                            "있지만, 발동은 그 체인이 모두 해결된 뒤입니다.",
                            ValidationCode.STAGE_FORBIDS_ACTION,
                        )
                    )
                    continue
                # 같은 기회의 다른 유발이다 — 같은 체인에 쌓을 수 있다.
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
                        ValidationCode.RULE_NOT_IMPLEMENTED,
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
                        ValidationCode.TRIGGER_TIMING_MISSED,
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
            if definition is None:
                # 🔴 **규칙이 기회를 열었는데 실행 구현이 없다** (6-AB 추가
                # 보완). 6-AB 까지 이 자리는 조용히 ``continue`` 였고 (주석은
                # "제안이 보증한다" 였다), 그래서 **지원하지 않는다는 사실이
                # 어디에도 남지 않았다** — 읽는 쪽은 "유발이 없다" 로 읽는다.
                #
                # 실측으로 밟은 자리다: 한 사건이 유발 둘을 여는 합성에서
                # 둘째 효과(기르수 ②)의 정의가 등재되어 있지 않아 후보도
                # 보류도 없이 사라졌다.
                #
                # 근거가 생겨야 풀리는 자리이므로 ``missing`` 을 채운다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        f"{offer.effect_ref} 의 발동 기회가 열렸지만 이 "
                        "저장소에 그 효과의 실행 구현이 없습니다 — 이 유발을 "
                        "처리하지 못합니다.",
                        ValidationCode.RULE_NOT_IMPLEMENTED,
                        missing=TRIGGER_IMPLEMENTATION_MISSING,
                    )
                )
                continue
            try:
                selections = selections_for(definition, candidate)
            except TargetBridgeError:
                # 🔴 같은 결의 자리다 — 대상 환전이 안 되면 **처리할 수
                # 없다는 사실**을 적는다. 조용히 넘기지 않는다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        f"{offer.effect_ref} 의 대상 지정을 이 계층이 옮기지 "
                        "못했습니다 — 이 유발을 처리하지 못합니다.",
                        ValidationCode.RULE_NOT_IMPLEMENTED,
                        missing=TRIGGER_IMPLEMENTATION_MISSING,
                    )
                )
                continue
            gate = self._activation_gate(
                candidate, validator=validator, selections=selections
            )
            if gate.validity is not ActionValidity.VALID:
                # 🔴 **관문이 거절한 이유를 그대로 싣는다** (6-AB 추가 보완).
                #
                # 여기서도 조용히 ``continue`` 였다. 그러면 "규칙이 금지한다"
                # 와 "판정할 수 없다" 가 **둘 다 침묵**으로 나오고, 그 둘을
                # 가르는 것이 이 Phase 들의 규율이다.
                #
                # ``missing`` 은 관문이 말한 것을 따른다 — 관문이 모른다고
                # (``UNKNOWN``) 하면 채우고, 규칙이 금지한다고 하면 비운다.
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.ACTIVATE_EFFECT,
                        f"{offer.effect_ref} 의 발동 기회가 열렸지만 발동 "
                        f"관문을 지나지 못했습니다: {gate.reason}",
                        # 🔴 **관문의 코드를 그대로 옮긴다** (보완8). 전에는
                        # ``missing`` 만 옮겼고, 그래서 읽는 쪽이 규칙 거절과
                        # 모름을 "비었는지" 로 짐작해야 했다.
                        gate.code,
                        missing=(
                            gate.missing_rule
                            if gate.validity is ActionValidity.UNKNOWN
                            else None
                        ),
                    )
                )
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

    def _effect_kind(
        self, effect_ref: "EffectRef | None", instance: "InstanceId | None"
    ) -> "ActivationKind | None":
        """
        그 발동이 쓰려는 **효과 하나의 분류** (Phase 6-AB 보완7).

        ``None`` 은 **"모른다"** 다 — 가리킨 카드를 판에서 찾지 못했거나,
        그 ``EffectRef`` 의 정의가 등록부에 없거나, 정의가 **다른 카드의
        것**일 때다. 관문은 그것을 몬스터 효과에서 ``UNKNOWN`` 으로 받고,
        ``UNKNOWN`` 은 허가가 아니다.

        **왜 이 자리가 읽는가.** 분류는 효과 정의 등록부
        (:attr:`EffectActivator.definitions`) 에 있고 관측
        (``GameStateView``)에는 **없다**. 그래서 타이밍 관문은 스스로 알 수
        없고, 등록부를 들고 있는 이쪽이 읽어서 값으로 넘긴다 —
        :meth:`_set_this_turn` · :meth:`_activation_stage` 와 **같은 자리이고
        같은 이유**다 (ADR-007).

        🔴 **판정은 한 자리에서만 한다.** 여기서 하는 일은 "어느 효과인가" 를
        찾아 주는 것뿐이고, 그 분류가 어떤 스펠 스피드인지는
        :data:`~engine.activation_timing.KIND_SPEED` 한 벌이 정한다. 찾는
        방법도 한 벌이다 — :func:`~engine.spell_activation.effect_kind_of`
        가 효과 계층의 그 함수를 **그대로** 부른다. 이 모듈이 효과 계층을
        직접 읽지 않으므로 (``test_a_the_duel_module_still_imports_no_
        effect_layer``) 다리 쪽을 지나는 것이고, ``duel_components`` 가
        journal 객체를 그쪽에서 만드는 것과 같은 자리다. 후보 생성 ·
        ``apply`` · 거절 이유가 모두 이 메서드를 지난다.

        🔴 **읽기만 한다.** 등록부도 판도 바꾸지 않는다.
        """
        if effect_ref is None or instance is None:
            return None
        card = self.state.find_instance(instance)
        if card is None:
            return None
        return effect_kind_of(
            self._activator.definitions,
            effect_ref,
            source_card_id=card.card_id,
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
        link = self.chain.links[-1] if self.chain.links else None
        timed = ActivationTimingChecker(validator.view).check(
            ActivationTiming(
                self.chain,
                self.priority,
                set_this_turn=self._set_this_turn(action),
                # 🔴 **흐름의 단계** (보완6). 체인이 비어 있어도 판이 열려
                # 있는지는 체인으로 갈리지 않는다 (:meth:`_activation_stage`).
                stage=self._activation_stage(),
                # 🔴 **이 발동이 동시 발동 묶음의 것인가** (최종 보완).
                # 관측에 없는 사실이므로 판을 들고 있는 이 자리가 읽어서
                # 값으로 넘긴다 (``point`` · ``set_this_turn`` 과 같은 자리).
                simultaneous=self._is_simultaneous(action),
                # 🔴 **이 효과의 발동 분류** (보완7). 몬스터 효과의 스펠
                # 스피드는 카드 종류가 아니라 효과 분류가 정하고, 그 분류는
                # 이미 정의에 적혀 있다 — 관문이 관측만 받아서 보지 못하던
                # 것을 여기서 값으로 넘긴다 (``stage`` 와 같은 자리).
                activation_kind=self._effect_kind(
                    action.effect_ref, action.source
                ),
                # 응수할 링크의 효과도 같은 길로 읽는다 — 분류표를 두 벌
                # 만들지 않는다.
                responding_kind=(
                    None
                    if link is None
                    else self._effect_kind(link.effect_ref, link.source)
                ),
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
        elif self._window_actor() == seat and not self._window_group(
            seat, mandatory=True
        ):
            # 🔴 **유발 처리 기회에서의 ``PASS`` 는 "그 발동을 포기한다"** 다
            # (최종 보완). 체인 응답의 패스도, 체인을 풀기 위한 패스도 아니다 —
            # 같은 행위가 단계마다 다른 뜻이고, 그 단계는 ``priority`` 가
            # 열려 있는지와 창에 고를 것이 있는지로 갈린다.
            #
            # 이 자리가 없으면 상대의 기회를 **물을 수 없다**: 발동 말고
            # 고를 것이 없으면 그 자리에서 듀얼이 멈춘다.
            #
            # 🔴 **강제 묶음에는 올리지 않는다** (6-AB 보완4). 강제 유발은
            # 포기할 수 없으므로 (룰북 — 그 처리를 넘기고 진행할 수 없다)
            # 이 자리의 ``PASS`` 는 **임의 묶음일 때만** 뜻을 갖는다. 강제가
            # 남아 있는데 ``PASS`` 를 올리면 그것이 규칙이 요구한 처리를
            # 생략하는 길이 된다.
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
                    ValidationCode.NOT_PRIORITY_HOLDER,
                )
            )
        elif seat != self.turn_player:
            # 🔴 **보완8 이 이 자리를 모름에서 확정 거부로 옮겼다.**
            #
            # 전에는 ``missing="우선권을 여는 규칙 (Phase 2-F)"`` 였고, 그
            # 문장은 **우선권을 여는 계층이 아직 없다**는 뜻이었다 (2-F 가
            # 그것을 쓰기 전이다). 지금은 그 계층이 있고 (6-S · 6-AB 계열이
            # 창을 열고 닫는다), 비턴 플레이어가 그 창 밖에서 지나갈 것이
            # **없다는 것은 규칙이 답하는 사실**이다 — ``PASS`` 는 기회에
            # 대한 응답이고, 기회가 없으면 응답할 대상이 없다.
            #
            # 근거는 룰북 ``TURN PLAYER'S PRIORITY`` 다: *"As long as the
            # turn player has Priority, the opponent cannot activate cards
            # or effects, except for effects that activate automatically."*
            # 그 예외(유발)는 ``_trigger_actions`` 가 **따로** 본다.
            withheld.append(
                WithheldAction(
                    PlayerActionKind.PASS,
                    "지나갈 응답 기회가 열려 있지 않습니다 — 지금은 "
                    f"P{self.turn_player} 의 열린 상태이고, 비턴 플레이어가 "
                    "할 수 있는 것은 자동으로 발동하는 유발 효과뿐입니다 "
                    "(룰북 TURN PLAYER'S PRIORITY).",
                    ValidationCode.NO_RESPONSE_WINDOW,
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
                # 🔴 **진행 계층이 낸 코드를 그대로 옮긴다** (보완8). 전에는
                # 이유와 ``missing`` 만 옮기고 코드를 버렸고, 그래서 ``apply``
                # 가 같은 거절을 ``RULE_NOT_IMPLEMENTED`` 로 다시 적었다.
                unresolved = "; ".join(plan.unresolved_rules) or None
                withheld.append(
                    WithheldAction(
                        PlayerActionKind.END_PHASE,
                        plan.verdict.reason,
                        plan.verdict.code,
                        missing=unresolved,
                    )
                )
        return allowed, withheld

    def _stage_closed_actions(self, seat: int) -> "tuple[WithheldAction, ...]":
        """
        **판이 열린 상태가 아니어서 닫힌 행동들** (Phase 6-AB 보완8).

        열려 있으면 빈 묶음이다 — 그때는 이 다섯(여덟)이 후보로 오르거나
        각자의 관문이 거절하고, 어느 쪽이든 이유가 따로 남는다.

        🔴 **새 규칙을 만들지 않는다.** 어느 단계인지는
        :meth:`_activation_stage` 가 이미 답하고, 무엇이 열린 상태 전용인지는
        :data:`OPEN_STATE_ONLY_KINDS` 한 벌이 적는다. 이 함수가 하는 일은
        **그 둘을 읽어 문장으로 옮기는 것**뿐이다.

        🔴 **유발 등재 단계는 여기서 적지 않는다.** 그 단계의 거절은
        :meth:`_enforce_mandatory` 가 허가 목록을 좁히면서 **이미** 적고
        (강제인지 임의인지까지 갈라서), 여기서 또 적으면 같은 사실이 두 줄이
        된다.

        🔴 **종류마다 한 줄이다** (사용자 요구 ③-8) — 카드 수와 무관하다.
        """
        if self.priority.is_open:
            stage = self._activation_stage()
            where = (
                "체인 응답 단계"
                if stage is ActivationStage.CHAIN_RESPONSE
                else "빠른 효과 기회"
            )
            reason = (
                f"{where}이므로 판이 열린 상태가 아닙니다 — 공식 Fast "
                "Effect Timing 의 상자 A 에서만 할 수 있는 행동입니다. "
                "양쪽이 이 기회를 지나가면 판이 다시 열립니다."
            )
        elif seat != self.turn_player:
            # 🔴 **판은 열려 있는데 이 자리의 것이 아니다.** 비턴 플레이어가
            # 할 수 있는 것은 자동으로 발동하는 유발 효과뿐이다 (룰북
            # ``TURN PLAYER'S PRIORITY``), 그리고 그쪽은
            # :meth:`_trigger_actions` 가 따로 본다.
            reason = (
                f"지금은 P{self.turn_player} 의 열린 상태입니다 — 비턴 "
                "플레이어는 자동으로 발동하는 유발 효과 외에는 행동할 수 "
                "없습니다 (룰북 TURN PLAYER'S PRIORITY)."
            )
            # 🔴 **여기서는 발동도 함께 적는다** (보완8). 열린 상태의 비턴
            # 플레이어는 **자동으로 발동하는 유발 외에** 아무것도 발동할 수
            # 없고, 그 예외는 :meth:`_trigger_actions` 가 따로 열어 허가
            # 목록에 올린다. 그래서 이 줄은 "그 예외가 아닌 발동" 에 대한
            # 말이고, 허가 목록과 함께 읽으면 둘이 갈린다.
            #
            # 🔴 빠른 효과 기회 쪽에는 이 줄을 **더하지 않는다** — 그 단계의
            # 발동은 스펠 스피드 2 이상이면 적법하고, 효과별 거절은
            # :meth:`_activation_actions` 가 효과 이름과 함께 적는다.
            return tuple(
                WithheldAction(kind, reason, ValidationCode.NOT_TURN_PLAYER)
                for kind in OPEN_STATE_ONLY_KINDS
                + (PlayerActionKind.ACTIVATE_EFFECT,)
            )
        else:
            return ()
        return tuple(
            WithheldAction(kind, reason, ValidationCode.STAGE_FORBIDS_ACTION)
            for kind in OPEN_STATE_ONLY_KINDS
        )

    def _withheld_board_actions(self, seat: int, validator: ActionValidator):
        """
        **왜 마법 · 함정을 발동할 수 없는가.** 같은 이유는 한 줄로 묶는다.

        🔴 **첫 장에서 멈추지 않는다** (Phase 6-AB 보완8).

        전에는 거절 하나를 적고 ``break`` 했다. 그러면 읽는 쪽은 **그 이유가
        몇 장에 걸린 것인지** 알 수 없다 — 패가 다섯 장이고 한 장만 걸렸는지,
        다섯 장 전부가 같은 이유로 걸렸는지가 같은 한 줄로 나온다. Phase
        3-E-41 이 그 자리를 **F-2** 로 적어 두었다 (*"첫 장에서 멈춘다"*).

        지금은 패 전체를 묻고 **(코드 · 모자란 것)** 으로 묶어 묶음마다 한
        줄을 남기며, 그 줄이 **몇 장 중 몇 장**인지 적는다.

        🔴 **어느 카드인지는 적지 않는다.** 수는 세어도 식별자는 싣지 않는다
        — 뒷면 · 비공개 카드의 정체가 보류를 통해 새지 않게 하는 3-E-41 의
        invariant 그대로다. 수는 그 자리의 패 크기이고 공개 정보다.

        🔴 **읽기만 한다** — 검증기는 ``GameStateView`` 만 받는다.
        """
        hand = [card for card in self.state.player(seat).hand if card is not None]
        groups: dict[tuple, list[str]] = {}
        for card in hand:
            action = PlayerAction.activate_card(actor=seat, source=card.instance_id)
            verdict = validator.validate(action)
            if verdict.validity is ActionValidity.VALID:  # pragma: no cover
                continue
            key = (verdict.code, verdict.missing_rule)
            groups.setdefault(key, []).append(verdict.reason)
        held: list[WithheldAction] = []
        for (code, missing), reasons in groups.items():
            held.append(
                WithheldAction(
                    PlayerActionKind.ACTIVATE_CARD,
                    reasons[0],
                    code,
                    missing=missing,
                    scope=(
                        None
                        if len(hand) <= 1
                        else f"패 {len(hand)}장 중 {len(reasons)}장이 같은 이유"
                    ),
                )
            )
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
            return self._refusal(action, legal)

        if action.kind is PlayerActionKind.PASS:
            return self._apply_pass(action)
        if action.kind is PlayerActionKind.END_PHASE:
            return self._apply_end_phase(action)
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
            # **판을 바꾸는 행위와 흐름을 바꾸는 행위를 섞지 않는다**
            # (STRUCTURAL-55). 발동의 결과물은 ``StateDelta`` 만이 아니라
            # ``Chain`` 이기도 하므로 ``ActionHandler`` 에 끼울 수 없다.
            return self._apply_activation(action)
        # 🔴 **창이 어디서 시작하는지 먼저 적어 둔다** (6-AB 추가 보완).
        #
        # 판을 바꾸는 행위를 고르면 판은 **open state** 로 돌아가고 새 창이
        # 열린다 (공식 Fast Effect Timing 도표). 그 창이 덮는 것은 **이
        # 행위가 낳는 사건부터**이므로, 지금 기록 길이가 그 바닥이다.
        #
        # 수락된 뒤에만 옮긴다 — 거절된 행동은 그 자리를 떠나지 않았으므로
        # 창을 움직이지 않는다 (``test_b07`` 이 재는 성질).
        opening = len(self.journal) if self.journal is not None else 0
        step = self._apply_board(action)
        if step.accepted:
            self.window_floor = opening
            # 새 창이므로 **지나간 자리 기록을 비운다** (최종 보완).
            self.window_passed = frozenset()
            # 🔴 **그리고 다음 단계를 연다** (보완5) — 유발 등재가 있으면
            # 그 단계, 없으면 빠른 효과 기회다 (``_after_window_moved``).
            self._after_window_moved()
        return step

    def _refusal(self, action: PlayerAction, legal: LegalActions) -> DuelStep:
        """
        허가가 나지 않은 행위의 **거절 이유** (Phase 6-AB 보완6).

        🔴 **왜 이 자리가 생겼는가.** 여기는 *"{종류} 는 지금 허가된 행위가
        아닙니다"* 에 ``RULE_NOT_IMPLEMENTED`` 를 붙여 돌려주고 있었다. 그
        코드가 뜻하는 것은 **"이 저장소에 그 규칙이 없다"** 이고, 그래서
        **규칙이 분명히 막은 행동도 "엔진 미지원" 으로 보고되었다.** 실측
        (보완6 §2):

            빠른 효과 기회에서 통상 마법 발동
            → accepted=False code=RULE_NOT_IMPLEMENTED
              "activate_effect 는 지금 허가된 행위가 아닙니다."

        규칙상 불가능한 것과 판정 근거가 없는 것은 **다른 사실**이다. 섞어
        적으면 ``/combo`` 가 규칙이 막은 발동을 "엔진이 그 수단을 모른다" 로
        적고 (``deck.opening`` 의 ``unsupported`` 경로), 사람은 그것을
        고쳐야 할 공백으로 읽는다.

        🔴 **그래서 후보를 만든 그 관문에게 다시 묻는다** — 판정을 새로
        세우지 않는다. 발동이면 :meth:`_activation_gate` 가 이미 낸 판정이
        있고, 그 판정의 ``code`` · ``reason`` · ``missing_rule`` 을 그대로
        옮긴다. 후보 생성과 ``apply`` 가 **같은 판정**을 쓴다는 것이 이
        Phase 가 지키려는 것이다 (STRUCTURAL-134 와 같은 결).

        🔴 **좁히지도 넓히지도 않는다.** 돌려주는 ``accepted`` 는 여전히
        거짓이다. 바뀌는 것은 **왜 거절됐는지**뿐이다.

        🔴 **흐름 계층의 이유도 이제 읽는다** (Phase 6-AB 보완8).

        보완6 은 "관문이 아무 말도 하지 않으면 예전 문장 그대로" 로 두었고,
        그 자리가 BLOCKER-F6-2 였다. 실측 (보완8 §2 A4~A6 · B1~B3)::

            빠른 효과 기회에서 일반 소환 요청
            → RULE_NOT_IMPLEMENTED "normal_summon 는 지금 허가된 행위가 아닙니다."
            유발 등재 중 END_PHASE 요청
            → RULE_NOT_IMPLEMENTED "end_phase 는 지금 허가된 행위가 아닙니다."
               🔴 그런데 **보류 목록에는 정확한 이유가 이미 있었다** —
                  "유발 처리 기회가 열려 있습니다 … (공식 Fast Effect
                  Timing — box A 에서만 할 수 있는 행동입니다)"

        즉 규칙을 다시 구현할 필요가 없었다. **이미 판정한 계층의 말을
        옮기기만** 한다.

        판정 우선순위 — 위에서부터 먼저다
        ---------------------------------
        ================================  ==================================
        1. 발동 관문 (``_activation_gate``)  그 **행위 하나**에 대한 판정이다.
                                           발동에만 있다
        2. 규칙 검증기 (``ActionValidator``) 그 행위 하나에 대한 규칙 쪽 판정.
                                           흐름 둘(``PASS`` ·
                                           ``END_PHASE``)에는 답하지 않는다
        3. 보류 목록의 같은 종류             흐름 계층(단계 · 차례 · 필수
                                           처리)이 **종류 단위**로 낸 판정
        4. 그래도 없으면 예전 문장           남은 자리를 숨기지 않는다
        ================================  ==================================

        🔴 **행위 단위가 종류 단위보다 먼저다.** 같은 행위에 두 이유가 겹칠
        때 (예: 빠른 효과 기회에 **가려진 카드**를 가리킨 소환) 더 좁은 쪽이
        실제 이유이고, 종류 단위의 단계 설명을 앞세우면 *"부수적으로 발견한
        문제를 실제 제외 이유처럼"* 적는 일이 된다.

        🔴 **좁히지도 넓히지도 않는다.** 돌려주는 ``accepted`` 는 여전히
        거짓이다. 바뀌는 것은 **왜 거절됐는지**뿐이다.
        """
        verdict = self._refusal_verdict(action)
        if verdict is None:
            verdict = self._rule_verdict(action)
        if verdict is not None:
            return DuelStep(action, False, verdict.code, verdict.reason)

        held = self._withheld_for(action, legal)
        if held is not None:
            return DuelStep(action, False, held.code, held.reason)

        return DuelStep(
            action,
            False,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"{action.kind.value} 는 지금 허가된 행위가 아닙니다.",
        )

    def _rule_verdict(self, action: PlayerAction) -> "ValidationResult | None":
        """
        그 행위를 **규칙 검증기**가 거절했는가 (Phase 6-AB 보완8).

        발동이 아닌 종류의 거절 이유다 — 소환 · 세트 · 공격 · 위치 변경.
        검증기가 통과시키면 ``None`` 이고, 그러면 막은 것은 흐름 계층이므로
        :meth:`_withheld_for` 가 그쪽의 말을 찾는다.

        🔴 **흐름 둘은 묻지 않는다.** ``PASS`` 와 ``END_PHASE`` 는 검증기가
        답하지 않는 종류이고 (``deck/opening.py`` 의 ``_gate_code`` 도 그
        둘을 ``"FLOW"`` 로 따로 적는다), 물으면 "그 종류를 모른다" 는 답이
        실제 이유를 덮는다.

        🔴 **판을 바꾸지 않는다** — 검증기는 ``GameStateView`` 만 받는다.
        """
        if action.kind in (PlayerActionKind.PASS, PlayerActionKind.END_PHASE):
            return None
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT:
            # 그쪽은 ``_refusal_verdict`` 가 **세 관문 전부**로 답했다.
            return None
        verdict = self.activation_validator(action.actor).validate(action)
        if verdict.validity is ActionValidity.VALID:
            return None
        return verdict

    @staticmethod
    def _withheld_for(
        action: PlayerAction, legal: LegalActions
    ) -> "WithheldAction | None":
        """
        그 **종류**에 대해 보류 목록이 적어 둔 이유 (Phase 6-AB 보완8).

        🔴 **확정 거부를 먼저 고른다.** 한 종류에 여러 줄이 있을 수 있고
        (예: 단계가 닫았고 동시에 판정하지 못한 자리도 있다), 그때 *"규칙이
        금지한다"* 가 *"아직 모른다"* 보다 **더 확실한 사실**이다. 모름을
        앞세우면 규칙상 불가능한 행동이 미지원으로 집계된다.

        🔴 **지어내지 않는다.** 그 종류에 대한 줄이 없으면 ``None`` 이고,
        부르는 쪽은 예전 문장을 쓴다.
        """
        same = [held for held in legal.withheld if held.kind is action.kind]
        if not same:
            return None
        for held in same:
            if held.is_rule_refusal:
                return held
        return same[0]

    def _refusal_verdict(
        self, action: PlayerAction
    ) -> "ValidationResult | None":
        """
        그 행위를 **관문이** 거절했는가. 관문의 자리가 아니면 ``None``.

        지금 답하는 것은 효과 발동 하나다 — 그 관문
        (:meth:`_activation_gate`) 이 후보 생성과 ``apply`` 양쪽이 쓰는
        **단 하나의 관문**이기 때문이다. 다른 종류는 흐름 계층이 막으므로
        여기서 지어내지 않는다.
        """
        if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
            return None
        if action.effect_ref is None:
            return None
        definition = self._activator.definitions.definition_for(
            action.effect_ref
        )
        if definition is None:
            # 정의를 모르면 관문도 물을 수 없다 — 지어내지 않는다.
            return None
        try:
            # 🔴 **``_apply_activation`` 과 같은 환전**을 쓴다. 날 ``targets``
            # 를 관문에 넣으면 모양이 맞지 않는다 (실측: ``AttributeError``).
            selections = selections_for(definition, action)
        except TargetBridgeError as error:
            # 대상의 모양이 맞지 않는다 — 그것이 거절의 이유다.
            return ValidationResult.invalid(
                ValidationCode.TARGET_COUNT_MISMATCH, str(error)
            )
        offers = self._trigger_offers(action.actor)
        validator = self.activation_validator(action.actor, offers)
        verdict = self._activation_gate(
            action, validator=validator, selections=selections
        )
        if verdict.validity is ActionValidity.VALID:
            # 관문은 통과했는데 후보가 아니다 — 막은 것은 흐름 계층이다
            # (우선권 · 차례 · 필수 처리). 그쪽 이유를 지어내지 않는다.
            return None
        return verdict

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
        if not self.priority.is_open:
            # 🔴 **유발 처리 기회의 포기다** (최종 보완). 우선권이 열려 있지
            # 않으므로 체인 응답도 체인 해결도 아니다 — 이 자리가 이 창에서
            # 더 고르지 않겠다고 말한 것이다.
            #
            # 체인을 건드리지 않는다. 양쪽이 다 지나가면 창이 닫히고
            # (``_enforce_window``) 그때 일반 행동이 다시 오른다.
            self.window_passed = self.window_passed | {action.actor}
            if self._registration_is_open():
                return DuelStep(
                    action,
                    True,
                    ValidationCode.OK,
                    "이 유발 처리 기회에서 발동하지 않기로 했습니다 — "
                    "남은 묶음의 등재를 계속합니다.",
                )
            # 🔴 **등재가 끝났다** (6-AB 보완4, 목표 ②). 쌓인 것이 있으면
            # 이제 빠른 효과 응답 단계를 연다 — 등재 **도중**이 아니라
            # 등재가 끝난 자리다 (룰북 §동시 발동: 네 묶음을 다 쌓은 뒤에야
            # 다른 효과가 끼어들 수 있다). 쌓인 것이 없으면 아무도 발동하지
            # 않은 기회이므로 그대로 판이 열린 상태로 돌아간다.
            self.priority = self._response_priority()
            return DuelStep(
                action,
                True,
                ValidationCode.OK,
                "이 유발 처리 기회에서 발동하지 않기로 했습니다."
                + (
                    " 쌓인 체인에 대한 응답 기회가 열렸습니다."
                    if not self.chain.is_empty
                    else ""
                ),
            )

        self.priority = self.priority.passed()

        if self.chain.is_empty:
            # 🔴 **빈 체인의 빠른 효과 기회다** (보완5) — 풀 링크가 없으므로
            # ``ready_to_resolve`` 는 ``CHAIN_EMPTY`` 를 돌려준다
            # (*"풀 링크가 없습니다"*). 그 자리를 여기서 끝낸다: 양쪽이
            # 연속으로 패스하면 **기회를 닫고** 판이 다시 열린다.
            #
            # 근거는 공식 Fast Effect Timing 도표다 — 판이 열리는 조건이
            # *"the turn player … passes, the opponent passes back, and no
            # Chain is forming"* 셋이다.
            #
            # 🔴 **체인 해결 PASS 와 다른 일이다.** 여기서는 아무것도
            # 해결하지 않고, 이유 문장도 다르다. 그리고 페이즈 이동 동의도
            # 아니다 — 페이즈를 넘기는 것은 ``END_PHASE`` 가 하고, 그것은
            # 판이 열린 뒤에만 후보가 된다.
            if self.priority.both_passed:
                #: 🔴 **닫는 일은 응답 계층이 한다** — 닫는 이유를 그쪽이
                #: 들고 있다 (:data:`~engine.response.AFTER_FAST_WINDOW_RULE`).
                #: 흐름을 두 곳에서 닫으면 둘이 갈라진다.
                self.priority = self._response_loop.close_fast_window(
                    self._response_state()
                ).priority
                return DuelStep(
                    action,
                    True,
                    ValidationCode.OK,
                    "양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 "
                    "열렸습니다.",
                )
            return DuelStep(
                action,
                True,
                ValidationCode.OK,
                "빠른 효과 기회를 넘겼습니다 — 상대의 차례입니다.",
            )

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

        # 🔴 **체인이 끝났으므로 새 창이 열린다** (6-AB 추가 보완).
        #
        # 새 창이 덮는 것은 **이 체인이 시작된 번호부터**다. 그래서 둘이
        # 동시에 참이 된다:
        #
        #   · 체인을 연 기회의 사건(번호 < ``chain_floor``)은 **끝났다** —
        #     그 기회에서 쓰지 않은 임의 유발은 다시 나오지 않는다.
        #   · 체인 **도중에** 생긴 사건(번호 >= ``chain_floor``)은 **남는다** —
        #     그 체인이 모두 해결된 뒤에 발동한다 (聖鳥クレイン 재정).
        #
        # 🔴 **분기 없이 쓴다.** ``if self.chain_floor >= 0:`` 로 쓰면
        # ``_resolve_chain`` 의 분기가 둘이 되고, 이 함수는 **불발 분기
        # 하나만** 가져야 한다 (``test_s04_the_fizzle_branch_returns_
        # accepted_true_with_a_non_ok_code`` 가 AST 로 고정한다 — 돌려주는
        # 값을 가르는 자리가 하나임이 그 시험의 주장이다). ``max`` 면 체인이
        # 기록되지 않았을 때(``-1``) 창이 **뒤로 가지 않는다** — 바닥은
        # 오르기만 한다.
        self.window_floor = max(self.window_floor, self.chain_floor)
        self.chain_floor = -1
        # 새 창이므로 **지나간 자리 기록을 비운다** (최종 보완).
        self.window_passed = frozenset()
        # 🔴 **체인 해결 뒤에도 유발 확인과 빠른 효과 기회를 거친다**
        # (보완5). 공식 도표가 체인 해결 직후를 같은 두 갈래로 적는다 —
        # 유발이 있으면 box D, 없으면 box B. 해결 중에 생긴 사건이 유발을
        # 낳았으면 등재 단계가 먼저이고, 그것이 ``_after_window_moved`` 다.
        self._after_window_moved()

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
        # 🔴 페이즈가 바뀌면 창도 새로 시작한다 (6-AB 추가 보완). 둘은 다른
        # 축이지만 (페이즈 경계 · 기회 경계) 페이즈 전환은 둘 다 넘는다.
        self.window_floor = self.timing_floor
        self.chain_floor = -1
        self.window_passed = frozenset()
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

        if self.chain.is_empty and not activated.chain.is_empty:
            # 🔴 **이 체인이 여기서 시작했다** (6-AB 추가 보완). 그 번호가
            # "같은 기회의 다른 유발" 과 "체인 도중에 생긴 새 사건" 을
            # 가른다 (:attr:`chain_floor`).
            self.chain_floor = (
                len(self.journal) if self.journal is not None else 0
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

        # 🔴 **등재 단계에서는 우선권이 넘어가지 않는다** (6-AB 보완4, 목표 ②).
        #
        # 룰북 §*When multiple cards are activated simultaneously* 는 그 특수
        # 체인을 **네 묶음 순서대로 쌓는다**고 적는다 (강제 TP → 강제 NTP →
        # 임의 TP → 임의 NTP). 쌓는 도중에 응답이 열리면 남은 묶음이 등재될
        # 자리가 없어진다 — 실측: 첫 유발을 등재한 뒤 ``priority.is_open``
        # 이 참이 되고 ``to_act`` 가 상대로 넘어가 그 자리의 허가가
        # ``['pass']`` 하나였고, 남은 내 유발은 아무도 묻지 않았다.
        #
        # 그래서 **등재가 남아 있으면 우선권을 열지 않는다.** 등재가 끝난
        # 뒤에 열고, 그때 쥐는 자리는 **마지막으로 발동한 자리의 상대**다 —
        # RULE-CHAIN-001 ("the opponent is always given a chance to
        # respond") 과 같은 자리이고, 묶음이 여럿일 때도 같은 규칙이다.
        #
        # 🔴 **체인 응답 자체를 미루는 것이 아니다.** 등재는 같은 기회의
        # 유발만 쌓으므로 (``_window_actor`` 가 그 창의 claims 만 본다)
        # 등재가 끝나는 자리는 언제나 있고, 그 직후 응답이 열린다.
        if self._registration_is_open():
            return DuelStep(
                action,
                True,
                ValidationCode.OK,
                f"{activated.reason} 같은 기회의 유발 등재를 계속합니다 "
                f"(룰북 — 동시 발동은 하나의 특수 체인에 네 묶음 순서로 "
                f"쌓입니다).",
            )
        self.priority = self._response_priority()
        return DuelStep(
            action,
            True,
            ValidationCode.OK,
            f"{activated.reason} 상대의 응답을 기다립니다.",
        )

    def _response_priority(self):
        """
        등재가 끝난 뒤 **응답 단계를 여는** 우선권 (6-AB 보완4 · 보완5).

        두 경우가 있고 **둘 다 기회를 연다.**

        ==================  ==================================================
        체인이 쌓였다          쥐는 자리는 **마지막으로 발동한 자리의 상대**다 —
                            RULE-CHAIN-001 (*"the opponent is **always**
                            given a chance to respond"*). 공식 Fast Effect
                            Timing 도표의 box D 다
        체인이 비었다          쥐는 자리는 **턴 플레이어**다 — 그 도표가 적는
                            box B 이고, 거기서 *"They can also choose to
                            activate a fast effect, if they wish."*
        ==================  ==================================================

        🔴 **보완4 는 빈 체인에서 ``self.priority`` 를 그대로 돌려주었다.**
        그래서 유발을 모두 포기하면 **빠른 효과 기회를 건너뛰고** 곧바로
        열린 상태로 돌아갔다 (실측: 양쪽 포기 직후 ``END_PHASE`` 수락 True ·
        상대 허가 ``[]``). 공식 도표는 그 자리를 box B 로 적고, 판이 다시
        열리는 조건을 *"the turn player … passes, the opponent passes back,
        and no Chain is forming"* 로 적는다 — **두 번의 패스가 필요하다.**

        🔴 **체인이 없으므로 "해결" 로 이어지지 않는다.** 양쪽이 패스하면
        ``ResponseLoop.ready_to_resolve`` 가 ``CHAIN_EMPTY`` 를 돌려주고
        (*"풀 링크가 없습니다"*), :meth:`_apply_pass` 가 그때 기회를
        **닫는다.** 그 구분은 ``PriorityState.both_passed`` 의 설명이 이미
        적어 두었다 — *"체인이 있으면 체인이 끝난다는 뜻이고, 없으면 다른
        뜻이다."*
        """
        #: 🔴 **여는 자리는 하나다.** 쥘 자리와 이유만 두 경우에서 갈라지고,
        #: 기회를 여는 호출은 아래 한 곳뿐이다
        #: (``test_priority_response_audit.test_02`` 가 그 수를 센다).
        if self.chain.is_empty:
            holder = self.turn_player
            reason = "빠른 효과 기회 (공식 Fast Effect Timing — box B)"
        else:
            holder = 1 - self.chain.links[-1].actor
            reason = "발동에 응답 (RULE-CHAIN-001)"
        return ResponseLoop.opened(
            self.chain,
            holder,
            turn_player=self.state.turn.turn_player,
            phase=self.state.turn.phase,
            reason=reason,
        ).priority

    def _after_window_moved(self) -> None:
        """
        창이 옮겨 간 뒤 **다음 단계를 연다** (보완5).

        공식 Fast Effect Timing 도표의 두 갈래를 그대로 적는다.

        * 등재할 유발이 있으면 → **등재 단계**가 먼저다 (우선권은 닫힌 채로
          두고 :meth:`_window_actor` 가 자리를 가리킨다). 도표의
          *"If there is an effect that is triggered"* 쪽이다.
        * 없으면 → **빠른 효과 기회**를 연다. 도표의 *"If there is no effect
          that can be triggered."* → **Turn Player (box B)** 다.

        🔴 **부르는 자리는 둘이다** — 판을 바꾸는 행위가 수락된 뒤
        (:meth:`apply`) 와 체인이 풀린 뒤 (:meth:`_resolve_chain`). 둘 다
        "창이 옮겨 갔다" 는 같은 사건이고, 그래서 같은 함수를 부른다.

        🔴 **페이즈 전환은 부르지 않는다.** 도표가 *"This is where each Phase
        and Step starts"* 를 **box A** 로 적는다 — 새 페이즈는 열린 상태에서
        시작한다.
        """
        if self._registration_is_open():
            return
        self.priority = self._response_priority()

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
