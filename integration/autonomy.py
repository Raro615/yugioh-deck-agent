"""
자율 실행 배선 — **엔진이 만든 후보를 정책에게 주고, 정책의 결정을 엔진에게
되돌린다** (Phase 6-Y).

    Duel.apply (일반 소환)            엔진 — Agent 가 legal_actions 에서 골랐다
          ↓  EventJournal
    timing_events → registry_for_view 조립 층
          ↓  TriggerChainIntegrator.collect_and_order
    TriggerOffer                      "이 유발을 발동할 수 있다"
          ↓  정책이 고른다 (발동할 것인가)
    ChoiceOffer                       "이 카드들 중에서 고를 수 있다"
          ↓  정책이 고른다 (어느 인스턴스인가)
    plan(selections=…) → extend → ChainResolver   엔진이 다시 판정하고 해결한다

왜 이 자리인가
--------------
``agent`` 는 ``engine`` 만 import 한다 (실측: ``core`` · ``analysis`` ·
``integration`` **0곳**). 그 경계가 지키는 것은 **"AI 는 카드 데이터의 모양을
모른다"** 이고 (ADR-007 · ``tests/test_binding_rule_alignment.py`` 의
``test_37``), 유발 후보를 만들려면 등록 정보를 읽어야 하므로 그 일을
``agent`` 에 두면 경계가 깨진다.

그래서 **조립 층이 후보를 만들고 정책은 그것을 고른다.** 이 모듈은
``agent`` 를 import 하지 않는다 — 정책은 :class:`ChoiceSelector` 모양이면
무엇이든 받는다 (``DuelRunner`` 가 ``Policy`` 를 그렇게 받는 것과 같다).

책임을 가른다
-------------
🔴 **합법성은 엔진이, 선택은 정책이.** 이 모듈이 하는 일은 전달이다.

* 후보를 **새로 세지 않는다** — ``TriggerCollector`` ·
  ``TriggerEligibilityJudge`` · ``TargetResolver`` · ``BoardRuling`` 이
  이미 하는 일을 그대로 부른다.
* 정책이 고른 것을 **그대로 적용하지 않는다** — 후보 목록에 있는지 다시
  보고, 없으면 거절한다 (:class:`SelectionRefused`).
* 정책이 고르지 않으면 **발동하지 않는다.** 강제 유발과 임의 유발을 가르는
  지식이 이 엔진에 없으므로 (``TriggerRequirement.UNKNOWN``), 근거 없이
  강제로 발동시키지 않는다.

여기서 하지 않는 것
-------------------
**듀얼을 돌리지 않는다.** 일반 행동의 순환은 :class:`~agent.runner.DuelRunner`
의 일이고 이 모듈은 그것을 대신하지 않는다. 하는 일은 그 순환이 만든 **사건
하나**에서 유발을 꺼내 정책에게 묻고, 결정을 엔진에 돌려주는 것이다.

6-Z 가 연 것 — **정상 경로로 들어갔다**
----------------------------------------
6-Y 의 ``run_trigger`` 는 ``plan`` · ``extend`` · ``ChainResolver`` 를 직접
불러 **``legal_actions`` 를 지나지 않는 둘째 길**을 만들었다 (보고서 §12 의
``BLOCKER-6Y-1`` — Phase 3-E-20 이 미리 경고해 둔 자리다). 6-Z 가 그 길을
닫았다::

    TriggerSource.offers      Duel.triggers 가 읽는다 → legal_actions 에
          ↓                   유발 후보가 오른다 (사건이 있을 때만)
    Duel.apply                같은 관문으로 재검증하고 체인에 올린다
          ↓                   상대에게 응답 기회가 열린다 (RULE-CHAIN-001)
    상대의 PASS → 내 PASS       둘 다 그만하겠다고 해야 풀린다
          ↓                   (RULE-CHAIN-001)
    ChainResolver → EffectExecutor
          ↓  PolicyChooser.choose   **해결 중에** 비로소 묻는다
    정책이 고른다 → 엔진이 다시 본다

그래서 이 모듈은 이제 체인을 **쌓지 않는다.** 쌓는 자리는 ``Duel`` 하나다.

**상대 응답과 우선권도 ``Duel`` 이 돌린다.** 이 모듈은 그 순환에 행위를
넣고 결과를 읽기만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from engine.condition import ConditionContext, ConditionResult
from engine.effect.ruling import BoardRuling, RuleQuestion
from engine.effect.semantics import declared_gate_question
from engine.effect.targeting import TargetResolver
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.trigger import (
    TimingEvent,
    TriggerRequirement,
    TriggerStatus,
    TriggerWording,
    timing_events,
)
from engine.validation import ValidationCode
from engine.trigger_chain import TriggerChainIntegrator

from integration.trigger_registry import registry_for_view


class AutonomyError(RuntimeError):
    """배선을 쓰는 방법이 틀렸을 때."""


# ======================================================================
# 정책이 보는 것
# ======================================================================
@dataclass(frozen=True, slots=True)
class ChoiceCandidate:
    """
    해결 시점에 고를 수 있는 카드 하나.

    ``verdict`` 는 그 카드를 그 조작으로 움직일 수 있는지에 대한
    :class:`~engine.effect.ruling.BoardRuling` 의 답이다. ``TRUE`` 가 아닌
    후보도 **목록에 남긴다** — 왜 못 고르는지가 정책에게도 보여야 한다.
    """

    instance: InstanceId
    card_id: "int | None"
    verdict: ConditionResult
    reason: str

    @property
    def permitted(self) -> bool:
        """🔴 ``TRUE`` 만 참이다. ``UNKNOWN`` 은 허가가 아니다."""
        return self.verdict is ConditionResult.TRUE


@dataclass(frozen=True, slots=True)
class ChoiceOffer:
    """
    **해결 시점의 선택 하나**에 대해 정책에게 주는 것.

    ``view`` 는 규칙이 선언한 ``looked_at`` 을 연 관측이다 — 룰북이 그것을
    licensing 한다: *"Whenever an effect instructs you to add a card from
    your Deck to your hand … you can pick up your Deck and search through
    it."* 평소 관측으로는 덱이 보이지 않는다.

    🔴 **발동을 정한 뒤에야 열린다.** 고르기 전에 덱을 보여 주면 "덱을 보고
    발동할지 정한다" 가 되고, 그것은 규칙이 허락한 범위가 아니다.
    """

    effect_ref: EffectRef
    target_ref: object
    view: GameStateView
    candidates: tuple[ChoiceCandidate, ...]
    minimum: int
    maximum: int

    @property
    def permitted(self) -> tuple[ChoiceCandidate, ...]:
        """고를 수 있는 것만. 정책이 보통 쓰는 목록이다."""
        return tuple(c for c in self.candidates if c.permitted)

    def __len__(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True, slots=True)
class TriggerOffer:
    """
    **발동할 수 있는 유발 하나.** 발동 여부는 정책이 정한다.

    ``requirement`` 가 :attr:`~engine.trigger.TriggerRequirement.UNKNOWN`
    이면 강제인지 임의인지 **모른다**. 그때 이 배선은 발동을 강제하지
    않는다 — 모르는 것을 강제로 바꾸면 임의 효과가 억지로 발동된다.
    """

    event: TimingEvent
    effect_ref: EffectRef
    source: InstanceId
    controller: int
    requirement: TriggerRequirement
    reason: str
    wording: TriggerWording = TriggerWording.UNKNOWN
    """
    발동 시점의 어휘 — 「때」인가 「경우」인가 (Phase 6-AB).

    놓친 타이밍이 **있는 쪽과 없는 쪽**이 다르므로, 기회가 언제 닫히는가를
    가르는 데 쓴다. 판정은 ``Duel`` 이 한다 — 이 계층은 옮기기만 한다.
    """
    event_sequence: int = -1
    """
    이 사건이 기록된 **번호** (Phase 6-AA). ``EventJournal`` 이 identity 로
    쓰는 값 그대로다 (``JournalEvent.sequence``).

    🔴 **흐름 위의 자리를 가리킨다.** 사건이 지나간 시점의 것인지 판정하는
    데 쓰고, 그 판정은 ``Duel`` 이 한다 — 이 계층은 번호를 **옮기기만**
    한다. ``-1`` 은 번호를 모른다는 뜻이고, 그때 ``Duel`` 은 그 제안을
    **내놓지 않는다** (모르는 것을 지금 것으로 읽지 않는다).
    """

    @property
    def requirement_known(self) -> bool:
        return self.requirement is not TriggerRequirement.UNKNOWN

    @property
    def is_optional(self) -> bool:
        """근거 있는 **임의** 유발인가 (Phase 6-AA)."""
        return self.requirement is TriggerRequirement.OPTIONAL

    @property
    def is_mandatory(self) -> bool:
        """근거 있는 **강제** 유발인가 (Phase 6-AA)."""
        return self.requirement is TriggerRequirement.MANDATORY

    @property
    def misses_timing(self) -> "bool | None":
        """
        이 유발이 **타이밍을 놓칠 수 있는가** (Phase 6-AB). 모르면 ``None``.

        ========  ==========================================================
        ``True``    「때」 — 그 사건이 **마지막에 일어난 일**이어야 한다
        ``False``   「경우」 — 사이에 다른 일이 와도 기회가 남는다
        ``None``    어휘를 판정할 수 없다. 🔴 **어느 쪽으로도 바꾸지 않는다**
        ========  ==========================================================

        🔴 **``None`` 을 ``False`` 로 접지 말 것.** 접으면 「때」 효과가
        지나간 뒤에도 발동 후보가 되고, 그것은 모름을 허가로 바꾸는 일이다.
        읽는 쪽은 ``is True`` · ``is False`` · ``is None`` 셋을 따로 본다.
        """
        if self.wording is TriggerWording.WHEN:
            return True
        if self.wording is TriggerWording.IF:
            return False
        return None

    @property
    def event_key(self) -> TimingEvent:
        """
        **그 사건을 가리키는 값** (Phase 6-Z). ``Duel.consumed_events`` 가
        이것으로 같은 사건의 중복 발동을 막는다.

        🔴 **사건 자체다** — 새 식별자를 만들지 않는다. ``TimingEvent`` 는
        불변이고 값 동치이므로 (``frozen=True``), 같은 기록을 다시 펼치면
        **같은 값**이 나온다. 그것이 요구 조건이다: 후보를 두 번 물으면
        같은 열쇠가 나와야 하고, 다른 소환은 다른 열쇠여야 한다.

        따로 번호를 붙이면 그 번호를 **어디에 적어 두어야** 하고, 적어 둔
        곳이 ``Duel`` 밖이면 두 기록이 갈라진다.
        """
        return self.event


@runtime_checkable
class ChoiceSelector(Protocol):
    """
    정책이 갖춰야 하는 모양. **``agent`` 를 import 하지 않으려고 구조만 적는다.**
    """

    name: str

    def accept_offer(self, offer: TriggerOffer) -> bool:
        ...  # pragma: no cover - 프로토콜

    def choose_cards(self, offer: ChoiceOffer) -> "tuple[InstanceId, ...]":
        ...  # pragma: no cover - 프로토콜


# ======================================================================
# 결과
# ======================================================================
@dataclass(frozen=True, slots=True)
class SelectionRefused:
    """정책이 고른 것이 **거절된** 이유."""

    reason: str
    chosen: "tuple[InstanceId, ...]" = ()


@dataclass(frozen=True, slots=True)
class TriggerRun:
    """
    유발 하나를 정책에게 묻고 엔진에 돌려준 **결과 전부**.

    🔴 **정책이 결정한 것과 엔진이 판정한 것을 따로 적는다.** 그 구분이
    없으면 "AI 가 했다" 와 "시험이 넣어 주었다" 를 구별할 수 없다.
    """

    offer: TriggerOffer
    #: 정책이 발동하겠다고 했는가.
    activated: bool
    #: 정책에게 보여 준 선택지 (발동하겠다고 한 경우에만).
    choice: "ChoiceOffer | None" = None
    #: 정책이 고른 인스턴스들.
    chosen: "tuple[InstanceId, ...]" = ()
    #: 엔진이 거절했으면 그 이유.
    refused: "SelectionRefused | None" = None
    #: 체인에 오른 링크 수.
    links: int = 0
    #: 해결 결과 이름 (``RESOLVED`` 등). 해결까지 가지 않으면 ``None``.
    resolution: "str | None" = None
    #: 해결이 남긴 설명.
    resolution_reason: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.resolution == "RESOLVED"


# ======================================================================
# 배선
# ======================================================================
def trigger_offers(duel, repository, seat: int) -> tuple[TriggerOffer, ...]:
    """
    이 듀얼의 **기록된 사건들**에서 나온, 지금 발동할 수 있는 유발 전부.

    후보를 세는 일은 전부 앞 계층이 한다 — :func:`~engine.trigger.timing_events`
    가 사건을 시점으로 펼치고, :func:`~integration.trigger_registry.
    registry_for_view` 가 **관측에 보이는 카드**의 선언만 등록하고,
    ``TriggerCollector`` · ``TriggerEligibilityJudge`` 가 다섯 관문으로
    판정한다.

    🔴 **``ELIGIBLE`` 만 돌려준다.** ``UNDETERMINED`` 는 "발동할 수 있는지
    모른다" 이고, 모르는 것을 후보로 올리면 ``UNKNOWN`` 이 허가가 된다.

    🔴 **기록이 없으면 빈 짝이다** (Phase 6-AA). 사건에서 유발을 꺼내는
    일이므로 사건 기록이 없으면 꺼낼 것이 없다 — 그것은 오류가 아니라
    사실이다.

    6-Z 는 이 자리에서 :class:`AutonomyError` 를 던졌고, 그래서 **기록
    없는 사본의 ``legal_actions`` 가 터졌다** (``agent.simulation`` 의
    ``_fork`` 가 ``journal=False`` 로 한 벌을 바꿔 끼운다). 후보를 묻는
    일이 예외를 던지면 그 사본으로는 **아무 행동도 평가할 수 없다** —
    실측으로 ``Simulator.simulate`` 가 모든 행동에 ``ERROR`` 를 돌려주었다.
    빈 짝을 돌려주고, "판정하지 못했다" 는 사실은 ``Duel`` 이 보류 목록에
    적는다 (보고서 §4).
    """
    if duel.journal is None:
        return ()
    view = duel.view(seat)
    build = registry_for_view(view, repository)
    integrator = _integrator(view, build.registry)

    offers: list[TriggerOffer] = []
    for recorded in duel.journal:
        for event in timing_events(recorded):
            ordering = integrator.collect_and_order(event)
            for eligibility in ordering.canonical_sequence:
                candidate = eligibility.candidate
                if eligibility.status is not TriggerStatus.ELIGIBLE:
                    continue
                if candidate.controller != seat:
                    continue
                offers.append(
                    TriggerOffer(
                        event=event,
                        effect_ref=candidate.effect_ref,
                        source=candidate.source,
                        controller=candidate.controller,
                        requirement=candidate.requirement,
                        reason=_gate_summary(eligibility),
                        wording=candidate.wording,
                        event_sequence=recorded.sequence,
                    )
                )
    return tuple(offers)


def choice_offer(
    duel, seat: int, offer: TriggerOffer, definitions=None
) -> "ChoiceOffer | None":
    """
    그 유발의 **해결 시점 선택**에 대해 정책에게 줄 것. 선택이 없으면 ``None``.

    :func:`choice_offer_for` 를 그대로 부른다 — 유발이든 카드 발동이든
    고르는 자리는 같은 모양이므로 세는 코드를 두 벌로 갈라 두지 않는다.
    """
    return choice_offer_for(
        duel.state, seat, offer.effect_ref, offer.source, definitions
    )


def choice_offer_for(
    state, seat: int, effect_ref: EffectRef, source: InstanceId, definitions=None
) -> "ChoiceOffer | None":
    """
    **해결 시점 선택** 하나에 대해 정책에게 줄 것. 선택이 없으면 ``None``.

    유발에 묶이지 않는다 — 카드 발동(어리석은 매장 등)도 같은 자리를 쓴다.

    후보는 :meth:`~engine.effect.targeting.TargetResolver.candidates` 가
    만들고, 움직일 수 있는지는 :class:`~engine.effect.ruling.BoardRuling` 이
    답한다. 둘 다 이미 있는 것을 그대로 부른다.
    """
    definition = _definition(effect_ref, definitions)
    if not definition.targets:
        return None
    binding = definition.targets[0]
    spec = binding.spec
    if spec.choice is None:
        return None

    granted = GameStateView.from_state(
        state, viewer=seat, looked_at=spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(
        spec,
        ConditionContext(player=seat, source=source, effect_ref=effect_ref),
    )
    return ChoiceOffer(
        effect_ref=effect_ref,
        target_ref=binding.ref,
        view=granted,
        candidates=_judged_candidates(
            granted, found.eligible, _movement_question(definition)
        ),
        minimum=spec.choice.minimum,
        maximum=spec.choice.maximum,
    )


def choice_offer_from_request(request, definitions=None) -> ChoiceOffer:
    """
    **엔진이 해결 중에 보낸 요청**을 정책이 읽는 모양으로 옮긴다 (Phase 6-Z).

    ``request`` 는 :class:`~engine.effect.executor.ResolutionChoice` 다 —
    효과 · 대상 칸 · 규칙이 열어 준 관측 · 후보 · 장수. 엔진이 이미 다
    세어 두었으므로 **여기서 후보를 다시 세지 않는다.**

    :func:`choice_offer_for` 와 **같은 모양**을 만든다 — 정책은 두 길을
    구별하지 않는다. 다른 것은 후보를 누가 세었는가 하나다.

    ==================  ===========================================
    ``choice_offer_for``  조립 층이 ``TargetResolver`` 를 불러 센다.
                          발동 **전에** 미리 보여 줄 때 쓴다
    이 함수                엔진이 해결 중에 세어 보내 준 것을 옮긴다.
                          그것이 **실제 해결 시점**이다
    ==================  ===========================================
    """
    definition = _definition(request.effect_ref, definitions)
    return ChoiceOffer(
        effect_ref=request.effect_ref,
        target_ref=request.target_ref,
        view=request.view,
        candidates=_judged_candidates(
            request.view, request.candidates, _movement_question(definition)
        ),
        minimum=request.minimum,
        maximum=request.maximum,
    )


@dataclass(frozen=True, slots=True)
class ChoiceRecord:
    """
    **해결 중에 실제로 일어난 선택 하나**의 기록 (Phase 6-Z).

    재현에 필요한 것만 담는다 — 무엇을 물었고(``offer``) 무엇을 골랐는가
    (``chosen``). 같은 판 · 같은 정책이면 같은 기록이 나온다.

    🔴 **이 기록은 AI 의 관측이 아니다.** ``offer.view`` 는 규칙이 그 효과에
    열어 준 관측이고 (``looked_at``), 그 안에는 덱이 보인다. 그래서 이
    기록은 **보고와 재현을 위해 조립 층이** 들고 있는 것이고, 어느 정책에도
    되돌려주지 않는다. 정책이 보는 것은 그때 그 요청 하나뿐이다.
    """

    effect_ref: EffectRef
    target_ref: object
    offer: ChoiceOffer
    chosen: "tuple[InstanceId, ...]"


class PolicyChooser:
    """
    엔진의 **해결 시점 요청**을 정책에게 옮기는 것 (Phase 6-Z).

    :class:`~engine.effect.executor.ResolutionChooser` 모양이다 —
    ``choose(request) -> (InstanceId, …)`` 하나. 그 요청은 ``EffectExecutor``
    가 **계획 중에** 보내므로, 이 자리가 불리는 때가 곧 해결 시점이다.

    🔴 **옮기기만 한다.** 고른 것을 다시 보지 않는다 — 그것은 엔진의 일이고
    엔진이 **이미 한다**: 후보 목록 밖은 ``CANDIDATE_NOT_ELIGIBLE``, 장수와
    중복은 ``TargetResolver.validate`` 의 ``_check_count``, 움직일 수 있는지는
    해결 중의 ``BoardRuling`` 관문 (6-X). 이쪽에서 한 번 더 걸러 버리면 엔진이
    무엇을 거절하는지가 가려진다.

    🔴 **판을 받지 않는다.** 요청에 실린 관측만 정책에게 준다. 그래서 정책은
    ``GameState`` 도 ``Duel`` 도 만질 수 없다.

    물은 것과 고른 것은 :attr:`records` 에 남는다 — 그것이 "선택이 **해결
    중에** 일어났다" 는 증거이고, 재현의 좌표다.
    """

    __slots__ = ("selector", "definitions", "_records")

    def __init__(self, selector: ChoiceSelector, definitions=None):
        if not hasattr(selector, "choose_cards"):
            raise AutonomyError(
                "choose_cards(offer) 를 가진 정책이 필요합니다: "
                f"{type(selector).__name__}"
            )
        self.selector = selector
        self.definitions = definitions
        self._records: list[ChoiceRecord] = []

    @property
    def records(self) -> tuple[ChoiceRecord, ...]:
        """물은 것과 고른 것, 순서대로."""
        return tuple(self._records)

    def choose(self, request) -> "tuple[InstanceId, ...]":
        offer = choice_offer_from_request(request, self.definitions)
        chosen = tuple(self.selector.choose_cards(offer))
        self._records.append(
            ChoiceRecord(
                effect_ref=request.effect_ref,
                target_ref=request.target_ref,
                offer=offer,
                chosen=chosen,
            )
        )
        return chosen

    def forked(self) -> "PolicyChooser | None":
        """
        사본용 — **같은 정책 · 빈 기록.** 못 만들면 ``None`` (6-AB 보완).

        탐색 사본은 해결 시점 선택을 **해야** 한다 — 그러지 않으면 사본이
        원본보다 못 해결하고, 미래의 값이 규칙이 아니라 배선 때문에 달라진다
        (``EffectExecutor.chooser`` 의 설명).

        🔴 **기록은 물려주지 않는다.** 사본의 선택이 :attr:`records` 에 섞이면
        그 목록은 더 이상 "실제 듀얼에서 **해결 중에** 무엇을 물었는가" 의
        증거가 아니다 — 일어나지 않은 선택이 섞인다.

        🔴 **정책을 그냥 공유하지 않는다** (6-AB 가 그렇게 했고 그것이
        결함이었다). 정책이 상태를 들고 있으면 (``RandomChoice`` 의 난수원)
        사본의 물음이 **진짜 듀얼의 정책을 앞으로 민다** — 실측: 상태 있는
        정책으로 ``simulate`` 한 번에 부모의 호출 수가 0 → 1.

        그래서 정책에게 묻는다 (:class:`~agent.choice.ForkablePolicy`):

        - ``forked()`` 가 있으면 그것이 준 정책을 쓴다. 무상태 정책은
          ``self`` 를 주고, 상태 있는 정책은 사본용 사본을 준다.
        - **없으면 ``None`` 을 돌려준다.** 그러면 사본에 고르는 사람이 없고,
          아직 정해지지 않은 선택은 사본 안에서 **거절된다.** 조용히
          공유하는 것보다 이것이 낫다 — 거절은 보이고, 오염은 보이지 않는다.
        """
        split = getattr(self.selector, "forked", None)
        if not callable(split):
            return None
        return PolicyChooser(split(), self.definitions)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        name = getattr(self.selector, "name", type(self.selector).__name__)
        return f"<PolicyChooser {name} asked={len(self._records)}>"


@dataclass(frozen=True, slots=True)
class TriggerSource:
    """
    ``Duel.triggers`` 가 기대하는 모양 — ``offers(duel, seat)`` (Phase 6-Z).

    🔴 **이것이 유발을 정상 경로에 올리는 전부다.** ``Duel`` 은 등록 정보를
    읽지 못하므로 (``engine`` 은 ``core`` 를 import 하지 않는다 — ADR-007),
    사건에서 유발을 꺼내는 일을 조립 층에 맡기고 **값으로** 받는다. 이 칸이
    비어 있으면 유발 후보가 아예 오르지 않는다 (6-Z 이전과 같다).

    🔴 **묻는 것만으로 아무것도 바뀌지 않는다.** :func:`trigger_offers` 는
    사건 기록을 읽기만 하고, 같은 사건을 두 번 쓰지 않게 막는 것은 ``Duel``
    의 ``consumed_events`` 다 — 이쪽이 상태를 들고 있지 않다.
    """

    repository: object

    def offers(self, duel, seat: int) -> tuple[TriggerOffer, ...]:
        return trigger_offers(duel, self.repository, seat)


def run_trigger(
    duel, repository, seat: int, offer: TriggerOffer, selector: ChoiceSelector, *,
    chooser: "PolicyChooser | None" = None,
) -> TriggerRun:
    """
    유발 하나를 **정상 Duel 경로로** 발동한다 (Phase 6-Z).

    순서가 요점이고, **6-Y 와 달라진 것이 그 순서다.**

    1. 정책에게 **발동할 것인가**를 묻는다 (덱을 보여 주기 **전에**).
    2. ``duel.legal_actions(seat)`` 에 그 발동이 올라 있는지 본다 — 사건이
       없거나 이미 쓴 사건이면 올라 있지 않다.
    3. ``duel.apply`` 로 발동한다. 같은 관문이 **다시** 판정하고, 체인에
       링크가 오르고, **상대에게 응답 기회가 열린다** (RULE-CHAIN-001).
    4. 응답 기회를 지난다 — 둘 다 **패스**해야 체인이 풀린다
       (RULE-CHAIN-001). 🔴 패스도 ``legal_actions`` 를 지나 ``apply`` 로
       넣는다 — 손으로 우선권을 돌리지 않는다. 상대가 실제로 응답하는
       경로는 이 함수가 돌리지 않는다 (그것은 ``DuelRunner`` 의 일이다).
    5. 체인이 풀리는 **그 안에서** ``EffectExecutor`` 가 선택을 묻고
       (``PolicyChooser``), 고른 것을 엔진이 다시 본다.

    🔴 **3번이 6-Y 와 다른 전부다.** 6-Y 는 ``plan`` · ``extend`` ·
    ``ChainResolver`` 를 직접 불러 ``legal_actions`` 를 **지나지 않는 둘째
    길**을 만들었다 (Phase 3-E-20 이 경고한 자리). 지금은 체인을 쌓는 자리가
    ``Duel`` 하나다.

    🔴 **5번이 6-Y 와 다른 나머지다.** 6-Y 는 체인을 쌓기 **전에** 골랐으므로
    그것은 해결 시점의 선택이 아니었다. 지금은 해결 중에 묻는다 — 그 증거가
    ``chooser.records`` 이고, 후보는 **그때의 판**에서 세어진다.

    ``chooser`` 는 이 듀얼에 꽂아 둔 :class:`PolicyChooser` 다. 주면 무엇을
    묻고 무엇을 골랐는지 결과에 적는다. 주지 않으면 그 칸이 빈다 — **듀얼의
    동작은 달라지지 않는다** (선택을 받는 쪽은 듀얼 안의 실행기다).
    """
    from engine.action import PlayerAction

    wants = bool(selector.accept_offer(offer))
    if not wants:
        return TriggerRun(
            offer=offer,
            activated=False,
            notes=("정책이 발동하지 않기로 했다",),
        )

    action = PlayerAction.activate_effect(
        actor=seat, source=offer.source, effect_ref=offer.effect_ref
    )
    legal = duel.legal_actions(seat)
    if action not in legal.allowed:
        return TriggerRun(
            offer=offer,
            activated=True,
            refused=SelectionRefused(
                "이 발동은 지금 허가된 행위가 아닙니다 (사건이 없거나 이미 "
                f"쓴 사건입니다). 허가된 행위 {len(legal.allowed)}건."
            ),
            notes=("legal_actions 에 오르지 않았다",),
        )

    step = duel.apply(action)
    if not step.accepted:
        return TriggerRun(
            offer=offer,
            activated=True,
            refused=SelectionRefused(f"{step.code.value}: {step.reason}"),
            notes=("Duel.apply 가 거절했다",),
        )

    notes = [f"legal_actions → apply 로 발동했다 (후보 {len(legal.allowed)}건)"]
    links = len(duel.chain)

    # ④ **응답 기회를 지난다.** 둘 다 패스해야 풀린다 (RULE-CHAIN-001).
    #    패스도 ``legal_actions`` 를 지나 ``apply`` 로 넣는다 — 손으로
    #    우선권을 돌리지 않는다.
    last = step
    passes = 0
    while duel.priority.is_open and passes < 4:
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        if passing not in duel.legal_actions(holder).allowed:  # pragma: no cover
            notes.append(f"P{holder} 의 패스가 허가되지 않았다")
            break
        last = duel.apply(passing)
        passes += 1
        notes.append(f"P{holder} 가 패스했다")
        if not last.accepted:  # pragma: no cover
            break

    record = None if chooser is None else next(
        (r for r in reversed(chooser.records) if r.effect_ref == offer.effect_ref),
        None,
    )
    chosen = () if record is None else record.chosen

    # 🔴 **해결이 거절된 이유를 엔진에게서 받는다.** 배선이 따로 판정하지
    # 않으므로 (``PolicyChooser`` 가 옮기기만 한다), 거절 문장은 엔진이 쓴
    # 것이다 — ``TargetResolver._check_count`` · ``BoardRuling`` 관문 ·
    # ``_ask_for_choice`` 의 후보 검사.
    resolved = bool(passes) and last.code is ValidationCode.OK
    return TriggerRun(
        offer=offer,
        activated=True,
        choice=None if record is None else record.offer,
        chosen=chosen,
        links=links,
        resolution="RESOLVED" if resolved else None,
        resolution_reason=last.reason,
        refused=(
            None if resolved else SelectionRefused(f"{last.code.value}: {last.reason}", chosen)
        ),
        notes=tuple(notes),
    )


# ======================================================================
# 내부 — 전부 이미 있는 것을 부른다
# ======================================================================
def _judged_candidates(
    view: GameStateView, instances, question: "RuleQuestion | None"
) -> tuple[ChoiceCandidate, ...]:
    """
    후보마다 **움직일 수 있는가**를 붙인다. 판정은 ``BoardRuling`` 이 한다.

    🔴 ``TRUE`` 가 아닌 후보도 **목록에 남긴다** — 왜 못 고르는지가
    정책에게도 보여야 하고, 지워 버리면 "후보가 없다" 와 "후보는 있는데
    규칙이 막는다" 를 가를 수 없다.

    질문이 없으면 ``UNKNOWN`` 이다 — 그 조작에 대응하는 규칙 질문이 이
    엔진에 없다는 뜻이고, **없는 것을 허가로 바꾸지 않는다.**
    """
    ruling = BoardRuling(view, _rulings())
    judged: list[ChoiceCandidate] = []
    for instance in instances:
        card = view.find(instance)
        if question is None:
            verdict, reason = ConditionResult.UNKNOWN, (
                "이 조작에 대응하는 규칙 질문이 없어 움직일 수 있는지 "
                "판정하지 않았습니다."
            )
        else:
            explained = ruling.explain(question, instance)
            verdict, reason = explained.answer, explained.reason
        judged.append(
            ChoiceCandidate(
                instance=instance,
                card_id=card.card_id if card is not None else None,
                verdict=verdict,
                reason=reason,
            )
        )
    return tuple(judged)


def _movement_question(definition) -> "RuleQuestion | None":
    """그 효과의 **관문이 걸린** 조작에 대응하는 규칙 질문. 없으면 ``None``."""
    for operation in definition.operations:
        question = declared_gate_question(operation)
        if question is not None:
            return question
    return None


def _gate_summary(eligibility) -> str:
    return "; ".join(
        f"{verdict.gate.value}={verdict.result.validity.value}"
        for verdict in eligibility.gates
    )


def _integrator(view, registry) -> TriggerChainIntegrator:
    return TriggerChainIntegrator(view, registry, _definitions(), _implementations())


def _definitions():
    from engine.effect.library import definition_registry

    return definition_registry()


def _implementations():
    from engine.effect.library import implementation_registry

    return implementation_registry()


def _rulings():
    from engine.effect.library import OPERATION_RULINGS

    return OPERATION_RULINGS


def _definition(effect_ref: EffectRef, definitions=None):
    """
    그 효과의 정의. ``definitions`` 를 주면 **그 등록부**에서 찾는다.

    🔴 기본값은 프로덕션 등록부다 — 평소에는 아무것도 달라지지 않는다.
    인자는 **듀얼이 자기 등록부를 들고 있는 경우**를 위한 것이다
    (``Duel._activator`` · ``_resolver`` 에 다른 등록부를 꽂은 판).
    그 판의 해결 시점 선택을 프로덕션 등록부로 되묻으면 "정의가 없습니다"
    로 끝난다 — 엔진은 그 효과를 **이미 해결하는 중**인데.
    """
    registry = _definitions() if definitions is None else definitions
    definition = registry.definition_for(effect_ref)
    if definition is None:
        raise AutonomyError(f"{effect_ref} 의 정의가 없습니다.")
    return definition


def _executor(journal):
    from engine.effect.library import build_executor

    return build_executor(journal, rulings=_rulings())


__all__ = [
    "AutonomyError",
    "ChoiceCandidate",
    "ChoiceOffer",
    "ChoiceRecord",
    "ChoiceSelector",
    "PolicyChooser",
    "SelectionRefused",
    "TriggerOffer",
    "TriggerRun",
    "TriggerSource",
    "choice_offer",
    "choice_offer_for",
    "choice_offer_from_request",
    "run_trigger",
    "trigger_offers",
]
