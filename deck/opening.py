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
    chooser: object | None = None
    """
    이 듀얼에 꽂은 **해결 시점에 고르는 사람** (Phase 6-AD).

    🔴 **들고만 있는다.** 이 모듈은 그것을 만들지 않고 (조립 층의 것이다 —
    :func:`build_opening` 의 설명) 쓰지도 않는다. 꽂힌 객체가 ``duel`` 안에
    들어가 버리면 **무엇을 물었고 무엇을 골랐는지**를 보고가 읽을 길이 없어
    지므로, 받은 값을 이 칸에 그대로 남긴다.

    :func:`execute_opening` 이 ``records`` 가 있으면 걸음마다 **그 걸음에서
    새로 늘어난 기록**을 읽는다 (:attr:`ExecutedStep.resolution_choices`).
    없으면 그 칸은 비어 있고, "선택이 없었다" 가 아니라 "읽을 기록이 없다"
    는 뜻이다.
    """

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
    setup.chooser = chooser
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
    이 걸음이 **끝난 뒤 그 자리**에서 지원하지 않아 후보가 되지 못한 것들.

    ``LegalActions.unsupported()`` 가 고른다 — 빠진 규칙의 이름이 붙은
    보류만이다. 🔴 **규칙이 막은 것은 여기 없다.** 그것은 규칙의 답이고,
    이 칸이 말하는 것은 "이 저장소에 그 규칙이 없어 오르지 못했다" 다.

    🔴 **이 칸은 "지금 이 자리" 하나만 말한다** (보완8 세 항목 ①). 이
    걸음의 **자동 처리 도중**(체인 해결 · 양측의 기회를 지나가는 패스)에
    만난 사유는 여기 오지 않는다 — 그쪽은 :attr:`unsupported_during` 이고,
    둘을 합치면 "지금 후보가 되지 못한 것" 과 "지나오면서 만난 것" 이 같은
    목록으로 보인다.
    """
    unsupported_during: tuple[str, ...] = ()
    """
    이 걸음의 **자동 처리 도중** 지나간 자리에서 만난 미지원 사유
    (보완8 세 항목 ①).

    :func:`_settle_chain` 이 양측의 응답 기회를 지나가면서 적은 것들 가운데
    **이 걸음에서 처음 본** 것이다. 🔴 **시점이 다르다** — 이것은 이미
    지나온 자리의 사실이고, :attr:`unsupported` 는 지금 자리의 사실이다.
    둘을 섞으면 과거의 사유가 "현재 후보가 되지 못한 것" 으로 읽힌다.

    🔴 다른 자리의 기회에서 만난 것은 **어느 카드인지 적지 않는다**
    (:func:`unsupported_reasons_elsewhere`).
    """
    resolution_choices: tuple[int, ...] = ()
    """
    이 걸음의 **해결 중에 실제로 고른** 카드들의 ID (Phase 6-AD).

    🔴 :attr:`targets` 와 **다른 시점**이다. 저쪽은 발동을 선언할 때 이미
    정해져 있던 대상이고, 이쪽은 **규칙상 효과를 해결할 때** 고른 것이다.
    해결 시점에 고르는 효과는 발동 기록의 ``targets`` 가 **정당하게 비어
    있다** — 그때는 아무것도 정해지지 않는다. 그 칸을 채우려고 선택을
    거꾸로 발동 시점에 고정하면 규칙이 틀어진다 (6-AD §6).

    어디서 왔는가: 꽂힌 :attr:`OpeningSetup.chooser` 의 ``records`` 에서
    **이 걸음이 늘린 만큼**만 읽는다. 기록이 없으면 비어 있고, 그것은
    "고르지 않았다" 가 아니라 "읽을 기록이 없다" 다.
    """
    resolution_choice_text: tuple[str, ...] = ()
    """
    위 선택을 **사람이 읽는 한 줄**로 (Phase 6-AD). 보고가 쓴다.

    카드 이름을 담는 이유는 :attr:`materials` 와 같다 — 보고를 만드는 자리에
    카드 저장소가 없다.
    """
    material_card_ids: tuple = ()
    """
    같은 소재들의 **카드 ID** (Phase 6-AD 후속).

    🔴 :attr:`materials` 와 **같은 순서 · 같은 시점**의 기록이다. 저쪽은
    보고가 읽는 이름이고 이쪽은 **경로 대조가 읽는 값**이다 — 경로는 카드
    ID 로 적혀 있으므로 (``deck.combo_policy.PlannedAction.
    material_card_ids``) 이름만으로는 "계획이 요구한 소재였는가" 를 확인할
    수 없었다.
    """
    materials: tuple[str, ...] = ()
    """
    이 걸음이 **소재로 보낸** 카드들 (Phase 6-AC). 링크 소환만 채운다.

    🔴 **``targets`` 와 다른 칸이다.** 링크 소재는 대상으로 지정되지 않으므로
    (``PlayerAction.materials`` 의 설명) 한 칸에 넣으면 보고가 "대상 2개" 로
    적힌다 — 그것은 거짓이다.

    카드 이름을 담는다. 인스턴스 번호가 아니라 **무엇을 보냈는가**가
    §7 이 요구하는 기록이고, 번호는 판마다 달라 재현에 쓸 수 없다.
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
    ``"flow_only"``      남은 후보가 흐름뿐이고 **그 자리에** 미지원 보류가
                        없다 — 🔴 전개 **전체**가 지원 범위 안에서 검증되었다는
                        뜻이 아니다 (:attr:`fully_supported` 가 그것을 말한다)
    ``"not_chosen"``     후보는 있는데 **검증용 선택 방식**이 고르지 않았다
    ``"rejected"``       행동이 거절되었다
    ``"limit"``          이 단계가 선언한 상한에 닿았다
    =================  ==============================================

    🔴 **"흐름뿐" 과 "미지원" 을 가르는 것이 이 칸을 만든 이유다.** 6-AB
    추가 보완까지 둘이 같은 문장으로 나왔고, 그래서 읽는 쪽이 "지원하지
    않아 오르지 못한 후보가 있다" 를 "정상 전개 종료" 로 읽을 수 있었다.

    🔴 **이 칸은 "왜 멈췄는가" 하나만 말한다** (보완8 세 항목 ①). 전개
    **전체**를 지원 범위 안에서 검증했는가는 :attr:`fully_supported` 가
    따로 답한다 — 두 질문이고, 하나의 낱말로 둘을 말하면 어느 쪽이든
    거짓이 된다. 실측 (이 보완 전)::

        일반 소환 1걸음 → 중간 P1 기회에서 trap-activation-event 미지원
        → 마지막 P0 패는 비어 있으므로 그 자리의 미지원은 없다
        → stopped_kind="flow_only"  🔴 그리고 멈춘 설명이 그 한계를
                                       한 글자도 말하지 않았다

    그 재현은 **합성 조건**이다 (테스트 전용 정의에서
    ``activation_waits_for_event`` 만 참으로 바꾼다). 실제 욕망의 선물이
    사건을 기다리는 카드라는 뜻이 아니다.
    """
    unsupported: list[str] = field(default_factory=list)
    """
    실행 중에 만난 **미지원 사유**, 처음 본 순서대로 한 번씩.

    Simulator 와 ``/combo`` 까지 가는 것이 이것이다 — 걸음별로도 남고
    (:attr:`ExecutedStep.unsupported`) 여기 모인다.
    """

    @property
    def fully_supported(self) -> bool:
        """
        **전개 전체를 지원 범위 안에서 검증했는가** (보완8 세 항목 ①).

        :attr:`unsupported` 가 비었을 때만 참이다 — 걸음마다의 자리든 자동
        처리 도중 지나간 자리든, 한 번이라도 "이 저장소에 그 규칙이 없어
        오르지 못한 후보" 를 만났으면 거짓이다.

        🔴 **:attr:`stopped_kind` 와 다른 질문이다.** 그 칸은 *"왜
        멈췄는가"* 이고 이 칸은 *"끝까지 검증했는가"* 다. 둘은 서로를
        덮지 않는다:

        ==========================  ==================  ==================
        상황                          ``stopped_kind``    ``fully_supported``
        ==========================  ==================  ==================
        미지원 없이 흐름만 남았다       ``flow_only``       참
        중간에 미지원을 지나왔고
        마지막 자리는 깨끗하다          ``flow_only``       **거짓**
        멈춘 자리에 미지원이 있다       ``unsupported``     거짓
        행동이 거절되었다              ``rejected``        만난 것에 따른다
        상한에 닿았다                 ``limit``           만난 것에 따른다
        ==========================  ==================  ==================

        🔴 **누적 미지원이 실제 종료 원인을 덮지 않는다** — 거절 · 상한 ·
        정책 미선택은 :attr:`stopped_kind` 가 그대로 말한다.

        🔴 이름은 ``agent.simulation.SimulationResult.fully_supported`` 와
        같다. 같은 질문이므로 같은 이름을 쓴다 — 읽는 쪽이 두 계층에서
        다른 낱말을 배우지 않게.
        """
        return not self.unsupported

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


def _material_names(duel, action, repository) -> "tuple[str, ...]":
    """
    그 행동이 소재로 보낸 카드의 **이름**들 (Phase 6-AC).

    🔴 **행동을 적용하기 전에 읽는다.** 소재는 적용과 함께 필드를 떠나므로
    (링크 절차가 먼저 묘지로 보낸다) 뒤에 읽으면 자리가 달라져 있다.

    이름을 못 읽으면 번호를 적는다 — 적지 않는 것보다 낫다.
    """
    names: list[str] = []
    for instance in getattr(action, "materials", ()):
        card = duel.state.find_instance(instance)
        definition = repository.get(card.card_id) if card is not None else None
        names.append(
            definition.display_name() if definition is not None else str(instance)
        )
    return tuple(names)


def _material_card_ids(duel, action, repository) -> "tuple[int, ...]":
    """
    그 행동이 소재로 보낸 카드의 **ID** 들 (Phase 6-AD 후속).

    🔴 :func:`_material_names` 와 **같은 시점에 같은 순서로** 읽는다 (적용
    전에). 이름은 사람이 읽는 칸이고 ID 는 **대조하는 칸**이다 — 경로가
    카드 ID 로 적혀 있으므로 (``PlannedAction.material_card_ids``) 이름만
    남기면 "계획이 요구한 소재를 확인한다" 를 실제로 할 수 없다.

    번호를 읽을 수 없는 개체는 **건너뛰지 않고** 센다 — ``None`` 을 넣으면
    대조에서 길이가 맞지 않아 드러난다.
    """
    found: list = []
    for instance in getattr(action, "materials", ()):
        card = duel.state.find_instance(instance)
        found.append(card.card_id if card is not None else None)
    return tuple(found)


def unsupported_reasons(legal, *, with_scope: bool = True) -> tuple[str, ...]:
    """
    그 자리의 보류 가운데 **미지원 사유**만, 읽을 수 있는 한 줄씩.

    🔴 **판정을 새로 하지 않는다.** ``LegalActions.unsupported()`` 가
    고른 것을 옮기기만 한다 — 어느 보류가 "규칙이 없다" 인지는 엔진이
    정한다 (``WithheldAction.missing``).
    """
    return tuple(
        held.line_ko(with_scope=with_scope) for held in legal.unsupported()
    )


def unsupported_reasons_elsewhere(legal, seat: int) -> tuple[str, ...]:
    """
    **다른 자리**의 기회에서 만난 미지원 사유 (보완8 마무리).

    ``unsupported_reasons`` 와 같은 사실을 적지만 ``reason`` 을 싣지 않는다 —
    그 문장은 ``EffectRef`` 를 담을 수 있고, 뒷면 카드의 ``EffectRef`` 는
    **그 카드의 정체**다. 전개 보고는 고른 자리의 눈으로 읽히므로 그 경계를
    넘지 않는다 (``agent.simulation.Simulator._encountered_line`` 과 같은
    기준이다).

    🔴 **지운 것이 있다는 사실을 문장에 적는다** — 읽는 쪽이 "사유가 없다"
    로 읽지 않게.
    """
    return tuple(
        f"{held.kind.value} [{held.missing}]: P{seat} 의 기회에서 만났고 "
        "어느 카드인지는 전개 보고의 관측 밖입니다."
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


def _settle_chain(duel, note=None) -> "tuple[object | None, bool]":
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
        seat = duel.to_act
        legal = duel.legal_actions(seat)
        # 🔴 **지나가는 자리의 미지원 사유를 적는다** (보완8 마무리).
        #
        # 전에는 이 반복이 조용히 패스만 했고, 부르는 쪽은 반복이 **끝난
        # 뒤**의 자리만 읽었다. 그래서 중간 기회에서 만난 구체적인 사유가
        # 보고에 남지 않았다 — ``agent.simulation`` 쪽과 **같은 결함**이고
        # 같은 방식으로 고친다.
        if note is not None:
            note(legal, seat)
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


def _resolution_choices(records, repository) -> tuple:
    """
    해결 시점 선택 기록 몇 개를 **카드 ID 와 한 줄**로 바꾼다 (Phase 6-AD).

    🔴 **판을 읽지 않는다.** 기록에 실려 온 후보 목록이 인스턴스마다 카드
    ID 를 들고 있으므로 (``ChoiceCandidate.card_id``) 그것만 쓴다 — 고른
    카드는 이미 움직였을 수 있고, 움직인 뒤의 판에서 찾으면 "그때 무엇을
    골랐는가" 가 아니라 "지금 어디 있는가" 가 된다.

    🔴 **고르지 않은 기록도 지나간다.** 아무것도 고르지 않은 요청
    (``chosen`` 이 비어 있다)은 ID 를 남기지 않지만, 물었다는 사실은 한 줄로
    적는다 — 물었는데 고르지 않은 것과 아예 묻지 않은 것은 다르다.
    """
    ids: list[int] = []
    text: list[str] = []
    for record in records:
        by_instance = {c.instance: c.card_id for c in record.offer.candidates}
        offered = len(record.offer.permitted)
        if not record.chosen:
            text.append(
                f"{record.effect_ref} · 고르지 않았습니다 (후보 {offered}장)"
            )
            continue
        names = []
        for instance in record.chosen:
            card_id = by_instance.get(instance)
            if card_id is None:
                #: 후보 목록 밖의 인스턴스는 엔진이 거절한다
                #: (``CANDIDATE_NOT_ELIGIBLE``). 기록에는 남으므로 적는다.
                names.append("후보 목록에 없던 인스턴스")
                continue
            ids.append(card_id)
            card = repository.get(card_id) if repository is not None else None
            names.append(
                f"{card.display_name()} [{card_id}]" if card is not None
                else f"[{card_id}]"
            )
        text.append(
            f"{record.effect_ref} · {' · '.join(names)} (후보 {offered}장)"
        )
    return tuple(ids), tuple(text)


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

    #: 🔴 **해결 시점의 선택을 걸음마다 읽는다** (Phase 6-AD).
    #:
    #: 꽂힌 것이 ``records`` 를 갖고 있지 않으면 ``None`` 이고, 그때 걸음의
    #: 그 칸은 비어 있다 — "고르지 않았다" 가 아니라 **읽을 기록이 없다** 는
    #: 뜻이다 (:attr:`OpeningSetup.chooser` 의 설명). 없는 것을 성공으로도
    #: 실패로도 바꾸지 않는다.
    choice_log = setup.chooser if hasattr(setup.chooser, "records") else None
    seen_choices = len(choice_log.records) if choice_log is not None else 0

    #: 전개를 고르는 자리 — 보고가 **누구의 눈으로** 읽히는가.
    actor_seat = duel.to_act

    def note_unsupported(legal, seat: "int | None" = None) -> "tuple[str, ...]":
        """
        이 자리의 미지원 사유를 걸음에 붙이고 전체 목록에도 모은다.

        ``seat`` 을 주면 그 자리가 전개를 고르는 자리와 다를 때 관측 경계를
        지켜서 적는다 (보완8 마무리) — 자동 패스가 지나가는 **상대 기회**가
        그런 자리다.
        """
        if seat is not None and seat != actor_seat:
            found = unsupported_reasons_elsewhere(legal, seat)
            keys = found
        else:
            found = unsupported_reasons(legal)
            #: 🔴 **누적에는 ``scope`` 를 싣지 않는다** — 그 메모는 걸음마다
            #: 달라지므로 (패가 줄어든다) 같은 사유가 걸음 수만큼 쌓인다
            #: (``WithheldAction.scope`` 의 실측).
            keys = unsupported_reasons(legal, with_scope=False)
        for line in keys:
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
                #: 🔴 **"더 고를 것이 없다" 와 "끝까지 검증했다" 를
                #: 가른다** (보완8 세 항목 ①). 이 자리가 깨끗해도 전개
                #: 도중에 미지원을 지나왔으면 전체를 검증한 것이 아니다.
                #: 시점을 분명히 적는다 — **이 자리의 것이 아니다.**
                + (
                    f" 🔴 그리고 이 전개 도중에 **지원하지 않아 후보가 되지"
                    f" 못한 것 {len(run.unsupported)}건**을 지나왔습니다"
                    f" (지금 이 자리가 아니라 **앞선 자리**의 사실입니다 —"
                    f" 아래 `미지원 사유` 목록). 그래서 전개 전체를 지원"
                    f" 범위 안에서 검증한 것은 아닙니다."
                    if run.unsupported else ""
                )
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
        #: 🔴 **적용 전에** 읽는다 (``_material_names`` 의 설명).
        materials = _material_names(duel, action, repository)
        material_ids = _material_card_ids(duel, action, repository)

        before_hash = duel.state.state_hash()
        #: 🔴 **자동 처리 도중 새로 만난 사유만 따로 센다** (보완8 세
        #: 항목 ①). ``run.unsupported`` 는 처음 본 순서대로 쌓이므로,
        #: 이 걸음 앞의 길이를 기억하면 **이 걸음이 더한 것**이 잘린다.
        seen_unsupported = len(run.unsupported)
        step = duel.apply(action)
        settled, resolved = (None, True)
        if step.accepted and duel.priority.is_open:
            settled, resolved = _settle_chain(duel, note_unsupported)
        during = tuple(run.unsupported[seen_unsupported:])
        after_hash = duel.state.state_hash()

        #: 🔴 **이 걸음이 늘린 기록만** 잘라 읽는다. 전체를 적으면 앞 걸음의
        #: 선택이 이 걸음의 것으로 보인다.
        picked_ids: tuple[int, ...] = ()
        picked_text: tuple[str, ...] = ()
        if choice_log is not None:
            fresh = choice_log.records[seen_choices:]
            seen_choices = len(choice_log.records)
            picked_ids, picked_text = _resolution_choices(fresh, repository)

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
            unsupported_during=during,
            resolution_choices=picked_ids,
            resolution_choice_text=picked_text,
            material_card_ids=material_ids,
            materials=materials,
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
