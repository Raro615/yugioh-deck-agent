"""
실제 사건을 **기존** 트리거 계층에게 보여 주는 자리 (Phase 6-I).

    Duel.apply(action)                    ← 기존 실행 경로. 손대지 않는다.
        ↓  duel.journal.events            ← 기존 기록 (Phase 6-B)
    TriggerObserver.observe(record)
        ↓  EventPipeline.collect          ← 기존 조립 층
    TriggerCandidate
        ↓  TriggerEligibilityJudge.judge  ← 기존 판정 (관문 다섯)
    TriggerObservation — 후보 · 판정 근거 · 미해결 조건 · 실행 구현 유무

🔴 **이 모듈은 아무것도 바꾸지 않는다.** 판 · 체인 · 우선권 · 기록 중 어느
것도 건드리지 않고, ``GameStateView`` 와 기록만 **읽는다.** 그래서 관찰을
켜도 듀얼의 결과가 같다 — 그것이 §6-8 과 §18-7 의 요구이고, 읽기만 하는
구조가 그 요구를 **증명 가능하게** 만든다 (바꿀 수 있는 손이 없다).

왜 ``Duel`` 안에 넣지 않았는가
------------------------------
``Duel`` 이 등록소를 들고 있게 하는 길도 있었고 ``journal`` 이 그 선례다
(Phase 6-B 가 ``journal: object | None = None`` 으로 하위 호환을 지켰다).
그 길을 **고르지 않은 이유는 세 가지**다.

1. ``tests/test_trigger_pipeline_dormant_audit.py::test_12`` 가
   ``engine/duel.py`` 에 ``trigger`` 라는 **말이 없음**을 고정한다. 그 감사가
   지키는 것은 *"듀얼은 스스로 규칙을 만들지 않는다"* 이고, 이 Phase 가
   원하는 것(사건을 **관찰**한다)은 그 규칙을 바꾸지 않아도 된다.
2. 이번 단계는 자동 발동도 체인 삽입도 하지 않는다 (§15). 등록소를 듀얼이
   들고 있어야 하는 것은 듀얼이 **스스로 후보를 모을 때**이고, 그때가 오면
   그 변경이 필요한 이유도 함께 생긴다. 지금 미리 넣으면 쓰이지 않는 칸이
   계약에 남는다.
3. 밖에 두면 "관찰이 판을 바꾸지 않는다" 가 **구조로** 참이 된다.

:class:`TriggerObserver` 는 ``GameStateView`` 와 ``TriggerRegistry`` 를 받고,
등록소를 어디서 얻을지는 부르는 쪽이 정한다
(:func:`integration.trigger_registry.registry_for_view` 가 카드 데이터에서
만든다 — ``engine`` 은 카드 데이터의 모양을 모르므로 그 자리가 여기 있을 수
없다; ADR-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.effect.definition import EffectDefinitionSource
from engine.event_pipeline import EventPipeline
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.trigger import (
    EligibilityGate,
    TimingEvent,
    TriggerCandidate,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerStatus,
)
from engine.validation import ActionValidity


class ObservationStage(str, Enum):
    """
    후보 하나가 **어디까지 갔는가** (§8 의 A~E).

    🔴 **다섯 값이 한 사다리이고, 순서는 ``fold`` 와 같다** (거부 → 모름 →
    통과). 같은 사실에 두 어휘를 만들지 않는다.

    =====================  ==================================================
     ``REFUSED``            확정 거부 — 이 사건에서는 발동할 수 없다
     ``EVENT_UNDECIDED``    등록은 있는데 **사건 관계부터** 모른다 (A)
     ``JUDGEMENT_PENDING``  사건은 맞았고 **미확인 조건이 남았다** (B·C·D)
     ``RULES_SATISFIED``    관문 다섯을 전부 통과했다 — **아직 실행 가능이
                            아니다** (:attr:`TriggerEligibility.unchecked_rules`
                            가 남아 있다)
     ``EXECUTION_READY``    위 + 정의 + 실행 구현 + 미검사 규칙 없음 (E)
    =====================  ==================================================

    🔴 **``EXECUTION_READY`` 는 지금 도달할 수 없다.** 그것이 이 단계의
    사실이고, 그 사실을 값으로 **적어 두는** 것이 이 enum 의 일이다 —
    도달할 수 없는 칸을 비워 두면 "실행 가능" 과 "아직 모른다" 가 같은 값이
    된다. ``test_12`` 가 전 corpus 에서 0건임을 재고, 도달 조건이 모두
    참이어야만 이 값이 나온다는 것을 변이로 확인한다.
    """

    REFUSED = "refused"
    EVENT_UNDECIDED = "event_undecided"
    JUDGEMENT_PENDING = "judgement_pending"
    RULES_SATISFIED = "rules_satisfied"
    EXECUTION_READY = "execution_ready"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class TriggerObservation:
    """
    사건 하나 × 후보 하나에 대한 **관찰 기록**. 불변이고 아무것도 명령하지
    않는다.

    "등록이 있다" · "사건이 맞았다" · "조건을 봤다" · "미확인이 남았다" ·
    "실행할 수 있다" 를 **다섯 칸으로 따로** 들고 있는 것이 이 클래스의
    전부다. 하나로 합치면 그 중 어느 것이 참인지 물을 수 없게 된다 (§8).
    """

    event: TimingEvent
    candidate: TriggerCandidate
    eligibility: TriggerEligibility
    stage: ObservationStage
    has_definition: bool
    """``EffectDefinition`` 이 등록되어 있는가. **실행 허가가 아니다** (ADR-006)."""
    is_executable: bool
    """실행 구현까지 등록되어 있는가. 조회할 목록을 주지 않으면 거짓이다."""

    @property
    def effect_ref(self) -> EffectRef:
        return self.candidate.effect_ref

    @property
    def unchecked_rules(self) -> tuple[str, ...]:
        """아직 아무도 보지 않은 규칙들 (§8 의 D)."""
        return self.eligibility.unchecked_rules

    @property
    def blocking_gates(self) -> tuple[str, ...]:
        """통과하지 못한 관문의 이름. 순서는 검사 순서 그대로다."""
        return tuple(verdict.gate.value for verdict in self.eligibility.blocking)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return (
            f"{self.effect_ref} @{self.event.point.value} "
            f"{self.stage.value} (정의 {'있음' if self.has_definition else '없음'} · "
            f"구현 {'있음' if self.is_executable else '없음'})"
        )

    def to_dict(self) -> dict:
        return {
            "effect_ref": str(self.effect_ref),
            "point": self.event.point.value,
            "instance": None if self.event.instance is None else str(self.event.instance),
            "source": str(self.candidate.source),
            "candidate_status": self.candidate.status.value,
            "eligibility_status": self.eligibility.status.value,
            "stage": self.stage.value,
            "has_definition": self.has_definition,
            "is_executable": self.is_executable,
            "blocking_gates": list(self.blocking_gates),
            "unchecked_rules": list(self.unchecked_rules),
        }


def _stage_of(
    eligibility: TriggerEligibility, *, has_definition: bool, is_executable: bool
) -> ObservationStage:
    """
    관문 결과를 사다리 한 칸으로. **표가 아니라 순서다** — 먼저 걸리는 것이
    답이고, 그 순서는 :meth:`TriggerEligibility.fold` 와 같다.
    """
    if eligibility.status in (TriggerStatus.FORBIDDEN, TriggerStatus.INELIGIBLE):
        return ObservationStage.REFUSED
    relation = eligibility.gate(EligibilityGate.EVENT_RELATION)
    if relation is not None and relation.result.validity is ActionValidity.UNKNOWN:
        #: 🔴 **사건 관계부터 모르면 그 뒤를 "조건을 봤다" 고 말할 수 없다.**
        #: 뒤의 관문이 통과했어도 그것은 "이 사건이 이 카드의 사건이라면" 이라는
        #: 가정 아래의 통과다.
        return ObservationStage.EVENT_UNDECIDED
    if eligibility.status is not TriggerStatus.ELIGIBLE:
        return ObservationStage.JUDGEMENT_PENDING
    if not eligibility.fully_checked:
        #: 관문 다섯은 통과했지만 **아무도 보지 않은 규칙**이 남았다
        #: (타이밍 창 · WHEN/IF · spell speed · 턴 1회 · SEGOC · 체인 삽입).
        return ObservationStage.RULES_SATISFIED
    if has_definition and is_executable:
        return ObservationStage.EXECUTION_READY
    return ObservationStage.RULES_SATISFIED


class TriggerObserver:
    """
    기록 하나를 **읽어서** 후보와 판정을 돌려준다.

        observer = TriggerObserver(view, registry, definitions, implementations)
        for observation in observer.observe(record):
            observation.stage          # 어디까지 갔는가
            observation.unchecked_rules

    ``definitions`` · ``implementations`` 는 생략할 수 있다. 생략하면
    :attr:`TriggerObservation.has_definition` · ``is_executable`` 이 거짓이고,
    그것은 **"없다" 가 아니라 "조회하지 않았다"** 이므로 그 상태로
    ``EXECUTION_READY`` 가 나올 수 없다 (:func:`_stage_of` 의 마지막 조건).
    """

    __slots__ = ("_pipeline", "_judge", "_registry", "_definitions", "_implementations")

    def __init__(
        self,
        view: GameStateView,
        registry: TriggerRegistry,
        definitions: EffectDefinitionSource | None = None,
        implementations=None,
    ):
        if not isinstance(registry, TriggerRegistry):
            raise TypeError(
                f"TriggerRegistry 가 필요합니다: {type(registry).__name__}"
            )
        #: 🔴 **기존 조립 층과 기존 판정기를 그대로 쓴다.** 수집도 판정도
        #: 여기서 다시 짜지 않는다 (§3-12 · §15 의 "중복 구현 금지").
        self._pipeline = EventPipeline(view, registry, definitions)
        self._judge = TriggerEligibilityJudge(view, definitions)
        self._registry = registry
        self._definitions = definitions
        self._implementations = implementations

    @property
    def view(self) -> GameStateView:
        return self._pipeline.view

    @property
    def registry(self) -> TriggerRegistry:
        return self._registry

    # ------------------------------------------------------------------
    def observe(self, record, actor: "int | None" = None) -> tuple[TriggerObservation, ...]:
        """
        기록 하나에서 나온 **모든 사건 × 모든 후보**.

        ``actor`` 를 주지 않으면 기록이 들고 있는 것을 쓴다 — 기록에 그 칸이
        없으면 ``TriggerError`` 다. 지어내지 않는다.

        사건마다 따로 돌려주고 **합치지 않는다** (``EventPipeline`` 과 같은
        규칙). 한 행동이 사건 여러 개를 만들면 순서는 기록의 순서 그대로다.
        """
        if actor is None:
            actor = getattr(record, "actor", None)
            if actor is None:
                raise TriggerError(
                    "이 기록에는 actor 가 없습니다. 사건의 주인을 지어내지 "
                    "않으므로 actor 를 직접 주어야 합니다."
                )
        out: list[TriggerObservation] = []
        for observation in self._pipeline.collect(record, actor=actor):
            timing = observation.event.timing
            specs = {
                spec.effect_ref: spec for spec in self._registry.watching(timing)
            }
            for candidate in observation.candidates:
                spec = specs.get(candidate.effect_ref)
                if spec is None:  # pragma: no cover - 같은 사건이면 일어나지 않는다
                    raise TriggerError(
                        f"{candidate.effect_ref} 의 선언을 이 사건에서 찾을 수 "
                        "없습니다. 후보와 등록소가 어긋났습니다."
                    )
                eligibility = self._judge.judge(candidate, spec, timing)
                has_definition = self._has_definition(candidate.effect_ref)
                is_executable = self._is_executable(candidate.effect_ref)
                out.append(
                    TriggerObservation(
                        event=timing,
                        candidate=candidate,
                        eligibility=eligibility,
                        stage=_stage_of(
                            eligibility,
                            has_definition=has_definition,
                            is_executable=is_executable,
                        ),
                        has_definition=has_definition,
                        is_executable=is_executable,
                    )
                )
        return tuple(out)

    def observe_all(self, records, actor: "int | None" = None):
        """기록 여러 개를 **순서대로**. 기록의 순서가 사건의 순서다."""
        out: list[TriggerObservation] = []
        for record in records:
            out.extend(self.observe(record, actor=actor))
        return tuple(out)

    # ------------------------------------------------------------------
    def _has_definition(self, effect_ref: EffectRef) -> bool:
        if self._definitions is None:
            return False
        return self._definitions.definition_for(effect_ref) is not None

    def _is_executable(self, effect_ref: EffectRef) -> bool:
        if self._implementations is None:
            return False
        #: 🔴 **정의 없이 실행 가능이라고 말하지 않는다.** 구현 목록에만 있고
        #: 정의가 없으면 무엇을 실행할지 모르는 상태다 (ADR-006).
        if not self._has_definition(effect_ref):
            return False
        return bool(self._implementations.has_implementation(effect_ref))


__all__ = [
    "ObservationStage",
    "TriggerObservation",
    "TriggerObserver",
]
