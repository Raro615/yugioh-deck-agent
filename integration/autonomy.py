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

**상대 응답과 우선권을 돌리지 않는다.** 그것은 ``Duel`` 안의 응답 순환이고,
유발 발동이 ``Duel.apply`` 를 지나게 되는 날 함께 열린다 (6-Y 보고서 §12 의
``BLOCKER-6Y-1``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from engine.chain import Chain, ChainResolver
from engine.condition import ConditionContext, ConditionResult
from engine.effect.ruling import BoardRuling, RuleQuestion
from engine.effect.semantics import declared_gate_question
from engine.effect.target import TargetSelection
from engine.effect.targeting import TargetResolver
from engine.cost import Selection
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.trigger import TimingEvent, TriggerRequirement, TriggerStatus, timing_events
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

    @property
    def requirement_known(self) -> bool:
        return self.requirement is not TriggerRequirement.UNKNOWN


@runtime_checkable
class ChoiceSelector(Protocol):
    """
    정책이 갖춰야 하는 모양. **``agent`` 를 import 하지 않으려고 구조만 적는다.**
    """

    name: str

    def activate_trigger(self, offer: TriggerOffer) -> bool:
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
    """
    if duel.journal is None:
        raise AutonomyError(
            "이 듀얼에는 EventJournal 이 없습니다. build_opening(journal=…) "
            "으로 만들어야 사건에서 유발을 꺼낼 수 있습니다."
        )
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
                    )
                )
    return tuple(offers)


def choice_offer(duel, seat: int, offer: TriggerOffer) -> "ChoiceOffer | None":
    """
    그 유발의 **해결 시점 선택**에 대해 정책에게 줄 것. 선택이 없으면 ``None``.

    :func:`choice_offer_for` 를 그대로 부른다 — 유발이든 카드 발동이든
    고르는 자리는 같은 모양이므로 세는 코드를 두 벌로 갈라 두지 않는다.
    """
    return choice_offer_for(duel.state, seat, offer.effect_ref, offer.source)


def choice_offer_for(
    state, seat: int, effect_ref: EffectRef, source: InstanceId
) -> "ChoiceOffer | None":
    """
    **해결 시점 선택** 하나에 대해 정책에게 줄 것. 선택이 없으면 ``None``.

    유발에 묶이지 않는다 — 카드 발동(어리석은 매장 등)도 같은 자리를 쓴다.

    후보는 :meth:`~engine.effect.targeting.TargetResolver.candidates` 가
    만들고, 움직일 수 있는지는 :class:`~engine.effect.ruling.BoardRuling` 이
    답한다. 둘 다 이미 있는 것을 그대로 부른다.
    """
    definition = _definition(effect_ref)
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
    question = _movement_question(definition)
    ruling = BoardRuling(granted, _rulings())
    candidates: list[ChoiceCandidate] = []
    for instance in found.eligible:
        card = granted.find(instance)
        if question is None:
            verdict, reason = ConditionResult.UNKNOWN, (
                "이 조작에 대응하는 규칙 질문이 없어 움직일 수 있는지 "
                "판정하지 않았습니다."
            )
        else:
            explained = ruling.explain(question, instance)
            verdict, reason = explained.answer, explained.reason
        candidates.append(
            ChoiceCandidate(
                instance=instance,
                card_id=card.card_id if card is not None else None,
                verdict=verdict,
                reason=reason,
            )
        )
    return ChoiceOffer(
        effect_ref=effect_ref,
        target_ref=binding.ref,
        view=granted,
        candidates=tuple(candidates),
        minimum=spec.choice.minimum,
        maximum=spec.choice.maximum,
    )


def run_trigger(
    duel, repository, seat: int, offer: TriggerOffer, selector: ChoiceSelector
) -> TriggerRun:
    """
    유발 하나를 **정책에게 묻고 엔진으로 실행한다.**

    순서가 요점이다.

    1. 정책에게 **발동할 것인가**를 묻는다 (덱을 보여 주기 전에).
    2. 발동하겠다면 규칙이 선언한 ``looked_at`` 을 열고 후보를 만든다.
    3. 정책에게 **어느 카드인가**를 묻는다.
    4. 고른 것이 후보 목록에 있는지, 장수가 맞는지 **다시 본다.**
    5. 엔진의 ``plan`` · ``extend`` · ``ChainResolver`` 로 해결한다.

    🔴 4번이 없으면 정책의 말이 허가가 된다.
    """
    wants = bool(selector.activate_trigger(offer))
    if not wants:
        return TriggerRun(
            offer=offer,
            activated=False,
            notes=("정책이 발동하지 않기로 했다",),
        )

    choice = choice_offer(duel, seat, offer)
    if choice is None:
        chosen: tuple[InstanceId, ...] = ()
        selections: tuple[TargetSelection, ...] = ()
    else:
        chosen = tuple(selector.choose_cards(choice))
        refusal = _judge_choice(choice, chosen)
        if refusal is not None:
            return TriggerRun(
                offer=offer,
                activated=True,
                choice=choice,
                chosen=chosen,
                refused=refusal,
            )
        selections = (
            TargetSelection(choice.target_ref, Selection.of(*chosen)),
        )

    view = duel.view(seat)
    build = registry_for_view(view, repository)
    integrator = _integrator(view, build.registry)
    ordering = integrator.collect_and_order(offer.event)
    plan = integrator.plan(
        Chain(), ordering, selections={offer.effect_ref: selections}
    )
    chain = integrator.extend(Chain(), plan)
    if not len(chain):
        reasons = "; ".join(entry.reason for entry in plan.entries) or "이유 없음"
        return TriggerRun(
            offer=offer,
            activated=True,
            choice=choice,
            chosen=chosen,
            refused=SelectionRefused(
                f"체인에 오르지 못했습니다: {reasons}", chosen
            ),
        )

    resolution = ChainResolver(_executor(duel.journal), _definitions()).resolve_top(
        duel.state, chain
    )
    return TriggerRun(
        offer=offer,
        activated=True,
        choice=choice,
        chosen=chosen,
        links=len(chain),
        resolution=resolution.result.status.name,
        resolution_reason=resolution.result.reason,
    )


# ======================================================================
# 내부 — 전부 이미 있는 것을 부른다
# ======================================================================
def _judge_choice(
    offer: ChoiceOffer, chosen: "tuple[InstanceId, ...]"
) -> "SelectionRefused | None":
    """정책이 고른 것을 **다시 본다.** 정책의 말은 허가가 아니다."""
    if len(set(chosen)) != len(chosen):
        return SelectionRefused("같은 카드를 두 번 골랐습니다.", chosen)
    if len(chosen) < offer.minimum:
        return SelectionRefused(
            f"{len(chosen)}장 골랐습니다 (최소 {offer.minimum}장).", chosen
        )
    if len(chosen) > offer.maximum:
        return SelectionRefused(
            f"{len(chosen)}장 골랐습니다 (최대 {offer.maximum}장).", chosen
        )
    known = {c.instance: c for c in offer.candidates}
    for instance in chosen:
        candidate = known.get(instance)
        if candidate is None:
            return SelectionRefused(
                f"{instance} 는 후보 목록에 없습니다.", chosen
            )
        if not candidate.permitted:
            return SelectionRefused(
                f"{instance} 는 고를 수 없습니다: {candidate.reason}", chosen
            )
    return None


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


def _definition(effect_ref: EffectRef):
    definition = _definitions().definition_for(effect_ref)
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
    "ChoiceSelector",
    "SelectionRefused",
    "TriggerOffer",
    "TriggerRun",
    "choice_offer",
    "choice_offer_for",
    "run_trigger",
    "trigger_offers",
]
