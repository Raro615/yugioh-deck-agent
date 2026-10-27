"""
**선공 첫 패로 실제 Duel 을 돌리는 자리** (Phase 6-T).

이 모듈이 하는 일과 하지 않는 일
--------------------------------
하는 일: 레시피와 패 5장을 받아 ① 정합성을 검사하고 ② 선공 1턴 메인
페이즈의 ``GameState`` 를 **엔진의 절차로** 만들고 ③ 기존
``legal_actions`` → ``ActionValidator`` → ``apply`` 로 행동을 실행하고
④ 그 걸음을 기록한다.

🔴 **하지 않는 일**: 새 듀얼 엔진 · 새 체인 · 새 판정기. 이 파일에는 규칙이
한 줄도 없다 — 전부 ``engine`` 에게 묻는다. 그리고 **콤보 탐색기도 아니다**
(Phase 6-U 의 일) — 깊이와 걸음 수를 작게 묶어 두고, 고른 행동을 "최선" 이라고
말하지 않는다.

세 가지를 섞지 않는다 (Phase 6-R · 6-S 의 규율)
-----------------------------------------------
======================  ==========================================
행위 수락                ``DuelStep.accepted``
체인 등록                ``Duel.chain``
효과 해결 · 상태 변경     ``EventJournal`` 의 ``EffectEvent`` · ``GameState``
======================  ==========================================

:class:`ExecutedStep` 이 그 셋을 **따로** 들고 있다. 하나의 bool 로 묶으면
"발동했다" 와 "해결됐다" 가 같은 값이 되고, 그것이 6-R 이 고친 결함이다.

왜 ``Duel.start`` 를 쓰지 않는가
--------------------------------
:meth:`~engine.duel.Duel.start` 는 **섞고 5장씩 뽑는다.** 이 모듈의 패는
사용자가 **지정한** 것이므로 뽑을 수 없다. 그래서 ``GameState.create`` 로
덱을 놓고 패를 ``create_instance`` 로 세운다 — 그러면 패가 어디서 왔는지가
입력 그대로 남는다.

🔴 **그래서 "실제 셔플로 이 패를 뽑았다" 고 말하지 않는다.** 이 패는 분석
조건이다 (Phase 6-T §8).

🔴 그리고 **덱 순서는 알려져 있지 않다.** 사용자가 레시피와 패만 주었으므로
남은 덱의 순서는 입력에 없다. :func:`build_opening` 이 ``shuffle=False`` 로
두고 그 사실을 :attr:`OpeningSetup.unknowns` 에 적는다 — 덱 맨 위를 뽑는
효과가 돌아가면 그 결과는 **이 배열에서의** 결과이고 모든 가능한 드로우를
대표하지 않는다.

선공 1턴은 **건너뛰지 않고 걸어서** 간다
----------------------------------------
``Duel`` 을 드로우 페이즈 · :attr:`~engine.duel.TurnStep.OPEN` 으로 세우고
(선공 첫 턴은 뽑지 않는다 — 룰북), ``legal_actions`` 가 내놓는
``END_PHASE`` 를 **실제로 적용해서** DRAW → STANDBY → MAIN1 으로 간다.
페이즈를 손으로 써 넣지 않는다 (Phase 6-T §7 "필요한 게임 단계를 건너뛰어
규칙 위반 상태를 만들지 않는다").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deck.model import (
    DeckDraft,
    DeckValidation,
    RuleFinding,
    ValidationOutcome,
)

#: 선공 첫 패의 장수. 룰북의 ``OPENING_HAND`` 와 **같은 수**이지만 이 모듈은
#: ``engine`` 의 상수를 읽어서 쓴다 (아래 :func:`opening_hand_size`).
_DEFAULT_OPENING = 5

#: 🔴 이 Phase 가 실행하는 **최대 걸음 수.** 콤보 탐색이 아니므로 작게 묶는다
#: (Phase 6-T §11 "탐색 깊이와 실행 횟수를 작게 제한한다"). 유희왕의 규칙이
#: 아니라 **이 단계가 선언한 상한**이다.
MAX_EXECUTED_ACTIONS = 8

#: 체인을 푸는 패스의 상한. ``settle_chain`` 과 같은 수다.
MAX_CHAIN_PASSES = 8


def opening_hand_size() -> int:
    """룰북 상수를 ``engine`` 에서 읽는다 — 여기서 숫자를 다시 적지 않는다."""
    from engine.duel import OPENING_HAND

    return int(OPENING_HAND)


# ======================================================================
# §6 — 덱과 패의 정합성
# ======================================================================


@dataclass(slots=True)
class OpeningSetup:
    """
    선공 전개를 돌릴 **입력 한 벌**과 그 검사 결과.

    🔴 :attr:`duel` 이 ``None`` 이면 상태를 만들지 않았다는 뜻이다 — 빈 판이
    아니다. 왜 만들지 않았는지는 :attr:`blockers` 에 있다.
    """

    hand: list[int] = field(default_factory=list)
    """시작 패의 카드 ID — 사용자가 적은 순서 그대로."""
    deck_rest: list[int] = field(default_factory=list)
    """패를 뺀 메인 덱. 🔴 순서는 **알려져 있지 않다** (모듈 설명 참조)."""
    extra: list[int] = field(default_factory=list)
    validation: DeckValidation | None = None
    """``DeckValidator`` 의 결과. 레시피가 없으면 ``None``."""
    findings: list[RuleFinding] = field(default_factory=list)
    """🔴 이 모듈이 **더** 본 것 — 패가 덱에 있는가 등 (§6-3·5·6·7·8)."""
    blockers: list[str] = field(default_factory=list)
    """상태를 만들지 못한 이유. 비어 있으면 만들 수 있다."""
    unknowns: list[str] = field(default_factory=list)
    """🔴 **알 수 없는 것** — 덱 순서 · 금지 제한 등. 성공으로 읽히면 안 된다."""
    duel: object | None = None
    """만들어진 ``Duel``. 만들지 못했으면 ``None``."""
    journal: object | None = None
    """그 듀얼의 ``EventJournal``."""

    @property
    def can_run(self) -> bool:
        return self.duel is not None and not self.blockers

    @property
    def all_findings(self) -> list[RuleFinding]:
        base = list(self.validation.findings) if self.validation else []
        return [*base, *self.findings]

    @property
    def violations(self) -> list[RuleFinding]:
        return [f for f in self.all_findings
                if f.outcome is ValidationOutcome.VIOLATED]

    @property
    def unverifiable(self) -> list[RuleFinding]:
        return [f for f in self.all_findings
                if f.outcome is ValidationOutcome.UNVERIFIABLE]


def _finding(rule: str, outcome: ValidationOutcome, detail: str,
             source: str | None = None) -> RuleFinding:
    return RuleFinding(rule=rule, outcome=outcome, detail=detail, source=source)


def check_hand_against_recipe(
    hand: "list[int]", draft: DeckDraft, repository
) -> "tuple[list[RuleFinding], list[int]]":
    """
    §6-3 · 5 · 6 · 7 · 8 — **패가 이 덱에서 나올 수 있는가.**

    돌려주는 것: ``(검사 결과, 패를 뺀 메인 덱 목록)``. 위반이 있으면 남은
    덱은 **계산하지 않고** 빈 목록이다 — 틀린 덱으로 전개를 돌리지 않는다.

    🔴 ``DeckValidator`` 가 보는 것(장수 · 3장 제한 · 금지 제한 · 엑스트라
    위치)과 **겹치지 않는다.** 여기는 "패" 쪽만 본다.
    """
    findings: list[RuleFinding] = []
    main_counts: dict[int, int] = {}
    for slot in draft.main:
        main_counts[slot.card_id] = main_counts.get(slot.card_id, 0) + slot.copies
    extra_ids = {slot.card_id for slot in draft.extra}

    hand_counts: dict[int, int] = {}
    for card_id in hand:
        hand_counts[card_id] = hand_counts.get(card_id, 0) + 1

    def _name(card_id: int) -> str:
        card = repository.get(card_id)
        return f"{card.display_name()} [{card_id}]" if card else f"[{card_id}]"

    # §6-8 카드 정의를 읽을 수 있는가
    unknown_cards = [c for c in dict.fromkeys(hand) if repository.get(c) is None]
    findings.append(_finding(
        "패 카드의 정의",
        ValidationOutcome.VIOLATED if unknown_cards else ValidationOutcome.SATISFIED,
        (f"카드 데이터에 없는 ID 가 있습니다: {unknown_cards}"
         if unknown_cards else
         f"패 {len(hand)}장의 정의를 모두 읽었습니다"),
        source="data/cards.cdb",
    ))

    # §6-5 패가 메인 덱에 있는가
    missing = [c for c in hand_counts if c not in main_counts]
    findings.append(_finding(
        "패가 메인 덱에 있는가",
        ValidationOutcome.VIOLATED if missing else ValidationOutcome.SATISFIED,
        (f"레시피의 메인 덱에 없는 카드가 패에 있습니다: "
         f"{', '.join(_name(c) for c in missing)}"
         if missing else
         "패의 모든 카드가 메인 덱 레시피에 있습니다"),
    ))

    # §6-6 보유 매수를 넘지 않는가
    over = [
        (c, n, main_counts.get(c, 0))
        for c, n in hand_counts.items()
        if n > main_counts.get(c, 0)
    ]
    findings.append(_finding(
        "패의 매수가 덱 보유 매수 이내인가",
        ValidationOutcome.VIOLATED if over else ValidationOutcome.SATISFIED,
        ("; ".join(f"{_name(c)}: 패 {n}장 > 덱 {have}장" for c, n, have in over)
         if over else
         "패의 각 카드가 덱 보유 매수를 넘지 않습니다"),
    ))

    # §6-7 엑스트라 덱 카드가 패에 들어왔는가
    #: 🔴 레시피의 엑스트라 목록이 아니라 **카드 데이터**로 본다. 레시피에
    #: 안 적혀 있어도 엑스트라 덱 카드는 첫 패에 올 수 없다.
    in_hand_extra = [
        c for c in dict.fromkeys(hand)
        if (repository.get(c) and repository.get(c).is_extra_deck) or c in extra_ids
    ]
    findings.append(_finding(
        "엑스트라 덱 카드가 시작 패에 있는가",
        ValidationOutcome.VIOLATED if in_hand_extra else ValidationOutcome.SATISFIED,
        (f"엑스트라 덱 카드는 첫 패에 올 수 없습니다: "
         f"{', '.join(_name(c) for c in in_hand_extra)}"
         if in_hand_extra else
         "엑스트라 덱 카드가 시작 패에 없습니다"),
    ))

    # §6-1 패 장수 — 룰북 상수와 비교한다
    expected = opening_hand_size()
    findings.append(_finding(
        "선공 첫 패 장수",
        (ValidationOutcome.SATISFIED if len(hand) == expected
         else ValidationOutcome.VIOLATED),
        (f"{len(hand)}장 (선공 첫 패는 {expected}장입니다)"
         if len(hand) != expected else f"{expected}장"),
        source="engine.duel.OPENING_HAND",
    ))

    if any(f.outcome is ValidationOutcome.VIOLATED for f in findings):
        return findings, []

    rest: list[int] = []
    #: 🔴 **패스코드 순으로 정렬한다.** 순서를 모르는 것과 순서가 재현되지
    #: 않는 것은 다르다 — 정렬하지 않으면 배열이 ``dict`` 순회의 부산물이 되고
    #: 같은 입력이 같은 결과를 준다는 보장이 없다. 정렬된 배열은 **선언된
    #: 배열**이고, 그것이 실제 셔플 결과가 아니라는 사실은
    #: :attr:`OpeningSetup.unknowns` 가 적는다.
    for card_id in sorted(main_counts):
        copies = main_counts[card_id] - hand_counts.get(card_id, 0)
        rest.extend([card_id] * copies)
    return findings, rest


# ======================================================================
# §7 — 선공 1턴 메인 페이즈의 상태
# ======================================================================


def build_opening(
    repository,
    draft: DeckDraft,
    hand: "list[int]",
    *,
    journal=None,
    chooser=None,
    triggers=None,
) -> OpeningSetup:
    """
    레시피와 패로 **선공 1턴 메인 페이즈**를 만든다.

    🔴 위반이 하나라도 있으면 ``duel`` 을 만들지 **않는다.** 틀린 덱으로
    전개를 돌려서 나온 결과는 검증이 아니다.

    ``chooser`` · ``triggers`` 는 **그대로 ``Duel`` 에 넘긴다** (Phase 6-Z).
    여기서 만들지 않는 이유는 둘이 조립 층의 것이기 때문이다 —
    ``integration.autonomy`` 의 ``PolicyChooser`` · ``TriggerSource``. 이
    모듈이 그것을 직접 만들면 ``deck`` 이 ``integration`` 을 import 하게
    되고, 지금 그 방향의 import 는 **0곳**이다.

    🔴 **주지 않으면 6-Z 이전과 같다.** ``triggers`` 가 없으면 유발 후보가
    ``legal_actions`` 에 오르지 않고, ``chooser`` 가 없으면 해결 시점의
    선택이 그대로 거절된다. 없는 것을 기본값으로 메꾸지 않는다 (ADR-006).
    """
    from deck.validator import DeckValidator
    from engine.duel import Duel, TurnStep, duel_components
    from engine.effect.journal import EventJournal
    from engine.priority import PriorityState
    from engine.state.game_state import GameState
    from engine.vocabulary import Phase, Zone

    setup = OpeningSetup(hand=list(hand))
    setup.validation = DeckValidator().validate(draft)
    findings, rest = check_hand_against_recipe(hand, draft, repository)
    setup.findings = findings
    setup.extra = [s.card_id for s in draft.extra for _ in range(s.copies)]

    #: 🔴 **알 수 없는 것을 먼저 적는다.** 아래에서 상태를 만들더라도 이
    #: 목록은 그대로 남아야 한다.
    setup.unknowns.append(
        "남은 덱의 순서는 입력에 없습니다 — 사용자가 레시피와 패만 주었으므로"
        " 실제로 섞인 순서를 알 수 없습니다. 이 실행은 덱을 **패스코드 순으로"
        " 정렬해** 두고 섞지 않았습니다 (같은 입력이 같은 결과를 주도록)."
        " 그래서 덱 맨 위를 뽑는 효과의 결과는 **이 배열에서의** 결과이고,"
        " 모든 가능한 드로우를 대표하지 않습니다."
    )
    setup.unknowns.append(
        "이 패는 사용자가 지정한 분석 조건입니다 — 실제 셔플로 뽑은 패가"
        " 아닙니다."
    )
    for finding in setup.unverifiable:
        setup.unknowns.append(f"{finding.rule}: {finding.detail}")

    if setup.violations:
        setup.blockers.extend(
            f"{f.rule}: {f.detail}" for f in setup.violations
        )
        return setup

    #: 상대 상태 — §3-15 · §7. 비공개 정보를 지어내지 않는다. 상대 덱은
    #: **같은 장수의 자리만** 두고 그 사실을 적는다.
    opponent_deck_size = len(rest) + len(hand)
    setup.unknowns.append(
        f"상대의 덱·패·필드는 입력에 없습니다 — 상대 덱 자리 {opponent_deck_size}장만"
        " 두고 패는 비워 두었습니다 (상대의 방해가 없는 상황입니다)."
    )

    state = GameState.create(
        repository,
        decks=(list(rest), [hand[0]] * opponent_deck_size if hand else []),
        turn_player=0,
        seed=0,
        shuffle=False,  # 🔴 순서를 모르므로 섞지 않는다 — 섞으면 모른다는 사실이 숨는다
    )
    for card_id in hand:
        state.create_instance(card_id, owner=0, zone=Zone.HAND)
    for card_id in setup.extra:
        state.create_instance(card_id, owner=0, zone=Zone.EXTRA)
    state.turn.set_phase(Phase.DRAW)

    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=0, phase=Phase.DRAW),
        step=TurnStep.OPEN,  # 🔴 선공 첫 턴은 뽑지 않는다 (룰북)
        first_player=0,
        **duel_components(journal=journal or EventJournal(), chooser=chooser),
        triggers=triggers,
    )
    walked = _walk_to_main1(duel)
    if walked is not None:
        setup.blockers.append(walked)
        return setup
    setup.duel = duel
    setup.journal = duel.journal
    setup.deck_rest = list(rest)
    return setup


def _walk_to_main1(duel) -> "str | None":
    """
    드로우 페이즈에서 **메인 페이즈 1 까지 걸어서** 간다.

    🔴 페이즈를 손으로 써 넣지 않는다 — ``legal_actions`` 가 내놓는
    ``END_PHASE`` 를 실제로 적용한다. 막히면 그 이유를 돌려준다.
    """
    from engine.action import PlayerActionKind
    from engine.vocabulary import Phase

    for _ in range(6):
        if duel.state.turn.phase is Phase.MAIN1:
            return None
        duel.advance()
        legal = duel.legal_actions(0)
        ends = [a for a in legal.allowed
                if a.kind is PlayerActionKind.END_PHASE]
        if not ends:
            held = "; ".join(f"{w.kind.value}: {w.reason}" for w in legal.withheld)
            return (f"{duel.state.turn.phase.value} 에서 페이즈를 넘길 수"
                    f" 없습니다 ({held or '보류 이유 없음'})")
        step = duel.apply(ends[0])
        if not step.accepted:
            return f"페이즈 전환이 거절되었습니다: {step.reason}"
    return (f"여섯 걸음 안에 메인 페이즈 1 에 닿지 못했습니다"
            f" (현재 {duel.state.turn.phase.value})")


# ======================================================================
# §10 — 실행 기록
# ======================================================================


@dataclass(frozen=True, slots=True)
class ExecutedStep:
    """
    **실제로 실행한 행동 하나**와 그 결과.

    🔴 세 사실을 따로 들고 있다 (모듈 설명의 표). 그리고 **상태 변경을
    해시로** 들고 있으므로 "바뀌었다" 를 주장할 때 근거가 있다.
    """

    order: int
    actor: int
    kind: str
    card_id: int | None
    card_name: str
    effect_ref: str | None
    targets: tuple[str, ...]
    gate_code: str
    """``_activation_gate`` 또는 ``ActionValidator`` 의 판정 코드."""
    accepted: bool
    """🔴 **행위를 수락했는가** — "효과가 적용되었는가" 가 아니다 (6-R)."""
    step_code: str
    reason: str
    chain_links_after: int
    chain_resolved_after: int
    resolved: bool
    """체인이 끝까지 풀렸는가. 체인을 만들지 않는 행동은 ``True``."""
    state_changed: bool
    effect_events: tuple[str, ...]
    """이 걸음에서 **새로 적힌** ``EffectEvent`` 의 효과 참조."""
    next_candidates: int
    note: str = ""
    unsupported: tuple[str, ...] = ()
    """
    이 걸음 **뒤의 자리**에서 지원하지 않아 후보가 되지 못한 것들.

    ``LegalActions.unsupported()`` 가 고른다 — 빠진 규칙의 이름이 붙은
    보류만이다. 🔴 **규칙이 막은 것은 여기 없다.** 그것은 규칙의 답이고,
    이 칸이 말하는 것은 "이 저장소에 그 규칙이 없어 오르지 못했다" 다.
    """

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        mark = "✔" if self.accepted and self.resolved else (
            "~" if self.accepted else "✗")
        where = f"{self.card_name} [{self.card_id}]" if self.card_id else "—"
        return f"{mark} {self.order}. P{self.actor} {self.kind} · {where}"


@dataclass(slots=True)
class OpeningRun:
    """선공 전개를 실제로 돌린 결과."""

    setup: OpeningSetup
    steps: list[ExecutedStep] = field(default_factory=list)
    stopped_reason: str | None = None
    """왜 멈췄는가. 🔴 "더 할 수 없다" 와 "상한에 닿았다" 를 가른다."""
    stopped_kind: str = ""
    """
    멈춘 **종류** (Phase 6-AB 최종 보완 ④). 문장이 아니라 한 낱말이다.

    =================  ==============================================
    ``"not_run"``        입력 검증을 통과하지 못해 돌리지 않았다
    ``"duel_over"``      듀얼이 끝났다
    ``"no_candidates"``  허가된 후보가 **하나도** 없다
    ``"unsupported"``    판을 바꿀 후보가 없는데 **미지원 보류가 있다**
    ``"flow_only"``      남은 후보가 흐름뿐이고 미지원 보류가 없다
    ``"not_chosen"``     후보는 있는데 **검증용 선택 방식**이 고르지 않았다
    ``"rejected"``       행동이 거절되었다
    ``"limit"``          이 단계가 선언한 상한에 닿았다
    =================  ==============================================

    🔴 **"흐름뿐" 과 "미지원" 을 가르는 것이 이 칸을 만든 이유다.** 6-AB
    추가 보완까지 둘이 같은 문장으로 나왔고, 그래서 읽는 쪽이 "지원하지
    않아 오르지 못한 후보가 있다" 를 "정상 전개 종료" 로 읽을 수 있었다.
    """
    unsupported: list[str] = field(default_factory=list)
    """
    실행 중에 만난 **미지원 사유**, 처음 본 순서대로 한 번씩.

    Simulator 와 ``/combo`` 까지 가는 것이 이것이다 — 걸음별로도 남고
    (:attr:`ExecutedStep.unsupported`) 여기 모인다.
    """

    @property
    def executed(self) -> int:
        return sum(1 for s in self.steps if s.accepted)

    @property
    def resolved(self) -> int:
        """
        **해결까지 막히지 않은 걸음** 수. 🔴 효과를 해결한 걸음 수가 **아니다.**

        체인을 만들지 않는 걸음(소환 · 세트)도 "막히지 않았다" 이므로 여기
        들어온다. 그래서 이 수가 걸음 수와 같은 것이 정상이고, 그것을
        "효과를 그만큼 해결했다" 로 읽으면 틀린다 — 효과 해결은
        :attr:`effects_resolved` 가 센다 (Phase 6-AA 가 가른 자리).
        """
        return sum(1 for s in self.steps if s.accepted and s.resolved)

    @property
    def effects_resolved(self) -> int:
        """
        **실제로 효과가 해결된 걸음** 수 (Phase 6-AA).

        기록에 ``EffectEvent`` 가 남은 걸음만 센다 — 적용된 링크만 그 사건을
        남기므로 (``EventJournal``) 이 수는 주장이 아니라 **실측**이다.
        """
        return sum(1 for s in self.steps if s.accepted and s.effect_events)

    #: 🔴 **"체인에 링크가 몇 번 올랐는가" 는 여기서 셀 수 없다** (6-AA 가
    #: 한 번 그렇게 만들었다가 지웠다). ``ExecutedStep.chain_links_after``
    #: 는 **걸음이 끝난 뒤 남은** 링크 수이고, 체인이 풀리면 0 이 된다 —
    #: 그래서 그 수를 세면 "발동이 한 번도 없었다" 로 읽힌다 (실측: 유발을
    #: 발동하고 해결한 전개에서 0 이 나왔다). 발동 횟수가 필요하면 기록의
    #: ``EffectEvent`` 를 세야 하고, 그것이 :attr:`effects_resolved` 다.

    @property
    def state_changes(self) -> int:
        return sum(1 for s in self.steps if s.state_changed)


# ======================================================================
# §9 — 실제 엔진 행동 실행
# ======================================================================


def _describe_action(action, repository) -> "tuple[int | None, str, str | None, tuple]":
    card_id: int | None = None
    name = "—"
    if action.effect_ref is not None:
        card_id = action.effect_ref.card_id
    ref = str(action.effect_ref) if action.effect_ref is not None else None
    targets = tuple(str(t.instance_id) for t in action.targets)
    return card_id, name, ref, targets


def unsupported_reasons(legal) -> tuple[str, ...]:
    """
    그 자리의 보류 가운데 **미지원 사유**만, 읽을 수 있는 한 줄씩.

    🔴 **판정을 새로 하지 않는다.** ``LegalActions.unsupported()`` 가
    고른 것을 옮기기만 한다 — 어느 보류가 "규칙이 없다" 인지는 엔진이
    정한다 (``WithheldAction.missing``).
    """
    return tuple(
        f"{held.kind.value} [{held.missing}]: {held.reason}"
        for held in legal.unsupported()
    )


def _gate_code(duel, action, repository) -> str:
    """
    이 행동에 대한 **기존 판정기의 코드**. 🔴 새 판정을 하지 않는다.

    발동은 ``Duel._activation_gate`` (관문 셋) 에, 그 밖은
    ``ActionValidator`` 에 묻는다. 흐름 둘(``PASS`` · ``END_PHASE``)은
    검증기가 답하지 않으므로 (Phase 6-S §4) 그 사실을 적는다.
    """
    from engine.action import PlayerActionKind
    from engine.target_bridge import TargetBridgeError, selections_for

    if action.kind in (PlayerActionKind.PASS, PlayerActionKind.END_PHASE):
        return "FLOW"  # 흐름 계층이 답한다 — 검증기가 아니다
    #: 🔴 **듀얼이 쓰는 검증기를 그대로 받는다** (Phase 6-Z). 여기서 손으로
    #: 만들면 관측에 없는 사실을 하나 빠뜨리기 쉽고 (``event_backed``), 그러면
    #: 실제로 수락된 발동을 보고가 "규칙 계층이 없다" 로 적는다 — 실측으로
    #: 그렇게 적혔다 (유발 발동이 ``RULE_NOT_IMPLEMENTED`` 로 보였다).
    validator = duel.activation_validator(action.actor)
    if action.kind is not PlayerActionKind.ACTIVATE_EFFECT:
        return validator.validate(action).code.name
    definition = duel._activator.definitions.definition_for(action.effect_ref)
    if definition is None:
        return "NO_DEFINITION"
    try:
        selections = selections_for(definition, action)
    except TargetBridgeError:
        return "UNSUPPORTED_SELECTION"
    return duel._activation_gate(
        action, validator=validator, selections=selections
    ).code.name


def _settle_chain(duel) -> "tuple[object | None, bool]":
    """
    열린 응답 창을 **기존 절차로** 닫는다 — 양쪽이 패스한다.

    돌려주는 것: ``(해결 걸음, 끝까지 풀렸는가)``. 체인이 열리지 않았으면
    ``(None, True)`` 다.

    🔴 **마지막 걸음이 아니라 해결 걸음이다** (보완5).

    보완5 가 빈 체인의 빠른 효과 기회를 실었으므로 체인이 풀린 **뒤에도**
    양측이 지나가야 판이 열린다. 그래서 이 반복의 마지막 걸음은 *"양쪽이
    빠른 효과 기회를 지나갔습니다"* 가 되고, 그것을 돌려주면 **걸음마다의
    이유가 전부 그 한 문장으로 덮인다** — 실측으로 ``/combo`` 의 2~5 걸음이
    자기 결과 대신 그 문장을 적었다. 그리고 ``resolved`` 도 거짓이 된다:
    불발한 링크의 ``code`` 대신 패스의 ``OK`` 를 읽기 때문이다.
    """
    from engine.action import PlayerActionKind
    from engine.validation import ValidationCode

    last = None
    resolution = None
    for _ in range(MAX_CHAIN_PASSES):
        if not duel.priority.is_open:
            break
        legal = duel.legal_actions()
        passing = [a for a in legal.allowed
                   if a.kind is PlayerActionKind.PASS]
        if not passing:
            return last, False
        had_chain = not duel.chain.is_empty
        last = duel.apply(passing[0])
        if had_chain and duel.chain.is_empty:
            resolution = last
    if resolution is None:
        #: 🔴 **풀린 체인이 없으면 돌려줄 "해결 걸음" 이 없다** (보완5).
        #: 판을 바꾸는 행위(세트 · 소환)는 발동이 아니므로 체인을 세우지
        #: 않는데, 보완5 는 그 뒤에도 빠른 효과 기회를 연다. 그 기회를
        #: 지나간 걸음을 돌려주면 **그 행위의 결과 대신 절차 문장이**
        #: 보고에 적힌다 — 실측으로 ``/combo`` 의 세트 걸음 셋이 그랬다.
        #:
        #: ``None`` 을 돌려주면 부르는 쪽의 ``settled or step`` 이 그 행위의
        #: 걸음을 그대로 쓴다.
        return None, True
    #: 🔴 ``accepted`` 로 해결 여부를 읽지 않는다 (6-R). 적법한 패스는 링크가
    #: 불발되어도 수락이고, 불발은 ``code`` 가 들고 온다.
    return resolution, resolution.code is ValidationCode.OK


def execute_opening(
    setup: OpeningSetup, repository, *, choose=None,
    max_actions: int = MAX_EXECUTED_ACTIONS,
) -> OpeningRun:
    """
    선공 전개를 **실제로** 돌린다.

    ``choose`` 는 후보 목록에서 하나를 고르는 함수다. 주지 않으면
    :func:`first_meaningful` 을 쓴다.

    🔴 **고른 행동을 최선이라고 말하지 않는다.** 이 Phase 의 선택 방식은
    검증용이고 (§9 "검증용으로 명확하게 정의된 선택 방식만 사용한다"),
    전략은 Phase 6-U · 6-V 의 일이다.

    🔴 **막히면 그 자리에서 멈춘다.** 지원하지 않는 절차를 우회하지 않고,
    멈춘 이유를 :attr:`OpeningRun.stopped_reason` 에 적는다. 그리고 그것이
    "이 패로는 전개가 불가능하다" 를 뜻하지 않는다 (§11 마지막 줄).
    """
    from engine.action import PlayerActionKind

    run = OpeningRun(setup=setup)
    if not setup.can_run:
        run.stopped_kind = "not_run"
        run.stopped_reason = (
            "입력 검증을 통과하지 못해 실행하지 않았습니다"
            if setup.blockers else "듀얼을 만들지 못했습니다"
        )
        return run

    duel = setup.duel
    journal = setup.journal
    picker = choose or first_meaningful
    seen_events = len(list(journal)) if journal is not None else 0

    def note_unsupported(legal) -> "tuple[str, ...]":
        """이 자리의 미지원 사유를 걸음에 붙이고 전체 목록에도 모은다."""
        found = unsupported_reasons(legal)
        for line in found:
            if line not in run.unsupported:
                run.unsupported.append(line)
        return found

    for order in range(1, max_actions + 1):
        if duel.is_over:
            run.stopped_kind = "duel_over"
            run.stopped_reason = f"듀얼이 끝났습니다: {duel.result.reason}"
            break
        duel.advance()
        legal = duel.legal_actions(duel.to_act)
        missing_here = note_unsupported(legal)
        if not legal.allowed:
            held = "; ".join(f"{w.kind.value}: {w.reason}"
                             for w in legal.withheld)
            run.stopped_kind = "no_candidates"
            run.stopped_reason = (
                f"P{duel.to_act} 의 후보가 없습니다 ({held or '보류 이유 없음'})"
            )
            break
        action = picker(duel, legal)
        if action is None:
            kinds_now = {a.kind.value for a in legal.allowed}
            if kinds_now == {"pass"}:
                #: 🔴 **``PASS`` 하나만 남은 것은 전개의 끝이 아니다**
                #: (보완5 §5). 엔진이 그 자리에서 ``PASS`` 만 허가한 것은
                #: **거쳐야 하는 절차가 남았다**는 뜻이다 — 유발 처리 기회를
                #: 지나가는 ``PASS``, 빠른 효과 기회를 지나가는 ``PASS``,
                #: 체인을 푸는 ``PASS``. 셋 다 지나가야 판이 다시 열린다.
                #:
                #: 보완5 전까지 이 자리는 "남은 후보는 흐름뿐" 으로 읽고
                #: **멈췄다.** 그러면 필수 절차 앞에서 실행이 끝나고, 그
                #: 뒤에 올 수 있었던 전개는 아예 시도되지 않는다.
                #:
                #: 🔴 **``END_PHASE`` 는 여기에 들지 않는다.** 그것은 절차가
                #: 아니라 **전개를 끝내는 선택**이고, 이 단계가 보려는 것이
                #: 전개다 (:func:`first_meaningful` 의 설명).
                #:
                #: 🔴 **걸음으로 적는다.** 아래 기록 경로를 그대로 지나므로
                #: 보고서에 ``pass`` 걸음이 보이고, 실행 걸음 수가 늘어난다.
                #: 조용히 넘기면 "몇 걸음이었나" 가 사실과 달라진다.
                action = next(
                    a for a in legal.allowed
                    if a.kind is PlayerActionKind.PASS
                )
        if action is None:
            #: 🔴 **세 가지를 가른다** — "검증용 선택 방식이 고르지
            #: 않았다" · "남은 후보가 흐름뿐이다" · "그 자리에 지원하지
            #: 않아 오르지 못한 후보가 있다". 흐름뿐이라는 사실 하나로는
            #: 어느 것인지 말할 수 없다 (6-AB 최종 보완 ④).
            kinds = sorted({a.kind.value for a in legal.allowed})
            flow_only = {"end_phase", "pass"} >= set(kinds)
            #: 🔴 **"후보가 흐름뿐" 만으로 정상 종료라고 적지 않는다**
            #: (Phase 6-AB 최종 보완 ④). 같은 자리에 **지원하지 않아 오르지
            #: 못한 후보**가 보류로 남아 있을 수 있고, 그때의 "흐름뿐" 은
            #: 전개가 끝난 것이 아니라 **엔진이 그 수단을 모르는** 것이다.
            #: 보류를 보지 않으면 두 사실이 같은 문장으로 나온다.
            run.stopped_kind = (
                "unsupported" if flow_only and missing_here
                else "flow_only" if flow_only else "not_chosen"
            )
            run.stopped_reason = (
                f"판을 바꿀 후보가 없고 남은 후보는 흐름뿐이지만"
                f" ({kinds}), 🔴 이 자리에 **지원하지 않아 후보가 되지"
                f" 못한 것이 {len(missing_here)}건** 있습니다:"
                f" {'; '.join(missing_here)}."
                f" 그래서 이것은 전개가 끝난 것이 아니라 **엔진이 그 수단을"
                f" 모르는 자리**입니다."
                if flow_only and missing_here else
                #: 🔴 **단정하지 않는다** (Phase 6-AA — 사용자 실험 ③).
                #:
                #: 6-T 는 이 자리를 "전개가 여기서 끝났다" 로 적었다. 그
                #: 문장은 **이 저장소가 모든 전개 수단을 안다**고 가정한다 —
                #: 실행 구현이 등재된 효과는 15개이고 (``EFFECT_LIBRARY``)
                #: 유발은 하나다. 즉 끝난 것은 전개가 아니라 **이 범위에서
                #: 고를 수 있는 것**이다.
                f"판을 바꿀 후보가 더 없습니다 — 남은 후보는 흐름뿐입니다"
                f" ({kinds}). 🔴 이것은 **이 저장소의 현재 지원 범위 ·"
                f" 후보 생성 · 검증용 선택 방식에서** 더 고를 것이 없다는"
                f" 뜻입니다. 실제로 이 패의 전개가 끝났다는 뜻이 아니고,"
                f" 엔진이 막았다는 뜻도 아닙니다."
                if flow_only else
                f"검증용 선택 방식이 고를 행동을 찾지 못했습니다"
                f" (후보 {len(legal.allowed)}건: {kinds})"
            )
            break

        card_id, _name, ref, targets = _describe_action(action, repository)
        if card_id is None and action.source is not None:
            instance = duel.state.find_instance(action.source)
            card_id = instance.card_id if instance else None
        card = repository.get(card_id) if card_id else None
        gate = _gate_code(duel, action, repository)

        before_hash = duel.state.state_hash()
        step = duel.apply(action)
        settled, resolved = (None, True)
        if step.accepted and duel.priority.is_open:
            settled, resolved = _settle_chain(duel)
        after_hash = duel.state.state_hash()

        events = []
        if journal is not None:
            all_events = list(journal)
            for event in all_events[seen_events:]:
                if event.kind.name == "EFFECT":
                    events.append(str(event.effect_ref))
            seen_events = len(all_events)

        final = settled or step
        run.steps.append(ExecutedStep(
            order=order,
            actor=action.actor,
            kind=action.kind.value,
            card_id=card_id,
            card_name=card.display_name() if card else "—",
            effect_ref=ref,
            targets=targets,
            gate_code=gate,
            accepted=step.accepted,
            step_code=final.code.name,
            reason=final.reason,
            chain_links_after=len(duel.chain.links),
            chain_resolved_after=duel.chain.resolved_count,
            resolved=bool(step.accepted and resolved),
            state_changed=before_hash != after_hash,
            effect_events=tuple(events),
            next_candidates=len(duel.legal_actions(duel.to_act).allowed),
            note=("체인이 끝까지 풀리지 않았습니다" if step.accepted
                  and not resolved else ""),
            unsupported=note_unsupported(duel.legal_actions(duel.to_act)),
        ))
        if not step.accepted:
            run.stopped_kind = "rejected"
            run.stopped_reason = f"행동이 거절되었습니다: {step.reason}"
            break
    else:
        run.stopped_kind = "limit"
        run.stopped_reason = (
            f"이 단계가 선언한 상한 {max_actions}걸음에 닿았습니다"
            " (전개가 끝났다는 뜻이 아닙니다 — Phase 6-U 가 넓힙니다)"
        )
    return run


def first_meaningful(duel, legal):
    """
    **검증용 선택 방식** — 판을 바꾸는 행동을 먼저, 흐름은 마지막에.

    순서: 효과 발동 → 통상 소환 → 마법·함정 세트 → 몬스터 세트 → 그 밖 →
    ``END_PHASE`` · ``PASS``.

    🔴 **최선이 아니다.** 같은 종류의 후보가 여럿이면 **첫 번째**를 고른다 —
    그 선택에 근거가 없다는 것을 이름과 설명이 말한다. 전략적 선택은
    Phase 6-U · 6-V 의 일이다.

    🔴 그리고 ``END_PHASE`` 는 **고르지 않는다** — 고르면 전개가 끝나 버리고,
    이 단계가 보려는 것은 전개다. 판을 바꿀 것이 없으면 ``None`` 을 돌려주고
    호출자가 멈춘다.
    """
    from engine.action import PlayerActionKind

    order = (
        PlayerActionKind.ACTIVATE_EFFECT,
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SPECIAL_SUMMON,
        PlayerActionKind.CHANGE_POSITION,
        PlayerActionKind.ATTACK,
    )
    for kind in order:
        for action in legal.allowed:
            if action.kind is kind:
                return action
    return None


__all__ = [
    "MAX_CHAIN_PASSES",
    "MAX_EXECUTED_ACTIONS",
    "ExecutedStep",
    "OpeningRun",
    "OpeningSetup",
    "build_opening",
    "check_hand_against_recipe",
    "execute_opening",
    "first_meaningful",
    "opening_hand_size",
]
