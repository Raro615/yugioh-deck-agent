"""
트리거와 체인을 잇는 **최소 통합 계층**.

    TimingEvent
        ↓  TriggerCollector           (F-3-A)
        ↓  TriggerEligibilityJudge    (F-3-B)
        ↓  TriggerOrdering            (F-3-C)
        ↓  TriggerChainIntegrator.plan(chain, ordering)
    TriggerChainPlan                  무엇이 들어갈 수 있고 무엇이 왜 못 들어가는가
        ↓  .extend(chain, plan)
    새 Chain

여기서 규칙을 다시 만들지 않는다
--------------------------------
후보를 다시 모으지 않고, 적격성을 다시 판정하지 않고, 순서를 다시 정하지
않는다. 앞 세 계층의 결과를 **그대로** 받아서 잇기만 한다.

후보는 체인 링크가 아니다
-------------------------
=====================  ==================================================
``TriggerCandidate``    이 사건 때문에 발동 후보가 될 수 있다
``TriggerEligibility``  지금까지 본 관문을 통과했는가
``ChainLink``           **실제로 발동하기로 결정된** 효과 하나
=====================  ==================================================

셋은 다른 것이고, 가운데에서 오른쪽으로 가려면 **후보가 갖고 있지 않은
정보**가 필요하다 — 무엇을 대상으로 골랐는가, 비용으로 무엇을 냈는가.
그것이 없으면 링크를 **만들지 않는다.** 빈 선택과 빈 영수증을 채워 넣고
"발동했다" 고 적으면, 대상 없이 해결되는 효과와 비용을 안 낸 효과가
조용히 판에 들어간다.

자동 실행이 없다
----------------
``ChainResolver.resolve`` 도 ``EffectExecutor.execute`` 도 부르지 않는다.
"트리거 발생 → 체인에 넣음 → 효과 실행" 을 한 번의 호출로 만들지 않는다 —
그 사이에 우선권과 응답 기회가 있고, 그 계층은 이 모듈이 정하지 않는다.

판을 바꾸지 않는다
------------------
``GameState`` 를 아예 받지 않는다. ``Chain`` 은 불변이므로
:meth:`TriggerChainIntegrator.extend` 도 **새 체인을 돌려줄 뿐** 원래
체인을 고치지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.chain import Chain, ChainError, ChainLink
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionSource,
    EffectImplementationLookup,
    ExecutionAvailability,
    execution_availability,
)
from engine.game_state_view import GameStateView
from engine.trigger import (
    TimingEvent,
    TriggerCollector,
    TriggerEligibility,
    TriggerEligibilityJudge,
    TriggerError,
    TriggerRegistry,
    TriggerStatus,
)
from engine.trigger_order import TriggerOrderer, TriggerOrdering
from engine.validation import ValidationCode


class ChainInsertion(str, Enum):
    """
    후보 하나가 **체인에 들어갈 수 있는가.**

    세 값뿐이다. 프로젝트의 삼치 원칙 그대로이고, 구체적인 이유는
    :attr:`TriggerChainEntry.code` 와 ``reason`` 이 말한다 — 새 어휘를
    만들지 않는다.
    """

    INSERTABLE = "insertable"
    """링크를 만들 수 있고, 만들었다."""
    NOT_INSERTABLE = "not_insertable"
    """**확실히** 들어갈 수 없다 (거부 · 금지 · 필요한 정보 없음)."""
    UNKNOWN = "unknown"
    """
    들어갈 수 있는지 **판정할 수 없다.**

    ``NOT_INSERTABLE`` 과 합치지 않는다 — "안 된다" 와 "모르겠다" 는 다른
    답이고, 모른다고 해서 트리거가 없다는 뜻도 아니다.
    """

    @property
    def permits_insertion(self) -> bool:
        """**``INSERTABLE`` 일 때만 참.** ``UNKNOWN`` 이 허가로 새지 않는다."""
        return self is ChainInsertion.INSERTABLE


@dataclass(frozen=True, slots=True)
class TriggerChainEntry:
    """
    후보 하나에 대한 **삽입 판정**. 불변이다.

    :attr:`link` 는 :attr:`ChainInsertion.INSERTABLE` 일 때만 있다. 나머지
    경우에 가짜 링크를 만들어 두지 않는다 — 있으면 누군가 쓴다.
    """

    eligibility: TriggerEligibility
    insertion: ChainInsertion
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    notes: tuple[str, ...] = ()
    link: ChainLink | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.notes, tuple):
            raise TypeError("notes 는 tuple 이어야 합니다 — 판정은 불변입니다.")
        if self.insertion is ChainInsertion.INSERTABLE:
            if self.link is None:
                raise TriggerError(
                    "삽입 가능하다면서 링크가 없습니다. 만들 수 있을 때만 "
                    "INSERTABLE 입니다."
                )
        elif self.link is not None:
            raise TriggerError(
                f"{self.insertion.value} 인데 링크가 있습니다. 들어가지 못하는 "
                "후보에 링크를 만들어 두지 않습니다."
            )

    @property
    def candidate(self):
        return self.eligibility.candidate

    @property
    def identity(self) -> tuple:
        """후보의 안정적인 식별자. 삽입 여부와 무관하게 보존된다."""
        return self.candidate.identity

    @property
    def inserted(self) -> bool:
        return self.insertion.permits_insertion

    def canonical_state(self) -> tuple:
        return (
            self.eligibility.canonical_state(),
            self.insertion.value,
            self.code.value,
            self.reason,
            self.notes,
            self.link.canonical_state() if self.link is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "eligibility": self.eligibility.to_dict(),
            "insertion": self.insertion.value,
            "code": self.code.value,
            "reason": self.reason,
        }
        if self.notes:
            data["notes"] = list(self.notes)
        if self.link is not None:
            data["link"] = self.link.to_dict()
        return data

    def describe_ko(self) -> str:
        return f"{self.candidate.key} → {self.insertion.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class TriggerChainPlan:
    """
    한 사건의 트리거들을 **체인에 어떻게 넣을 것인가**. 불변이고, 아직
    아무것도 넣지 않았다.

    :attr:`entries` 는 :class:`TriggerOrdering` 이 정한 순서 그대로다 —
    다시 정렬하지 않는다. 다만 그 순서는 **규칙상의 발동 순서가 아니고**
    (:attr:`is_rule_ordered`), 아직 정하지 못한 규칙은
    :attr:`unresolved_rules` 에 그대로 실려 있다.
    """

    event: TimingEvent
    base_chain: Chain
    entries: tuple[TriggerChainEntry, ...] = ()
    """순서화된 후보들의 판정. ``ELIGIBLE`` 이었던 것만 들어온다."""
    skipped: tuple[TriggerChainEntry, ...] = ()
    """``INELIGIBLE`` · ``FORBIDDEN`` — 확실히 제외."""
    unresolved: tuple[TriggerChainEntry, ...] = ()
    """``UNKNOWN`` — **트리거가 없다는 뜻이 아니다.**"""
    is_rule_ordered: bool = False
    unresolved_rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("entries", "skipped", "unresolved", "unresolved_rules"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 계획은 불변입니다.")
        expected = len(self.base_chain)
        for entry in self.entries:
            if entry.link is None:
                continue
            if entry.link.sequence != expected:
                raise TriggerError(
                    f"링크 번호가 {entry.link.sequence} 인데 {expected} 여야 "
                    "합니다. 계획이 체인과 어긋났습니다."
                )
            expected += 1

    # ------------------------------------------------------------------
    @property
    def insertable(self) -> tuple[TriggerChainEntry, ...]:
        """실제로 링크가 만들어진 것들. 체인에 들어갈 순서 그대로다."""
        return tuple(entry for entry in self.entries if entry.inserted)

    @property
    def blocked(self) -> tuple[TriggerChainEntry, ...]:
        """
        조건은 통과했는데 **필요한 정보가 없어** 들어가지 못한 것들.

        대상 선택과 비용 영수증이 없는 경우다. 이것이 비어 있지 않다는 것은
        "다음 계층이 아직 할 일이 있다" 는 뜻이지 "트리거가 없다" 가 아니다.
        """
        return tuple(entry for entry in self.entries if not entry.inserted)

    @property
    def links(self) -> tuple[ChainLink, ...]:
        return tuple(entry.link for entry in self.insertable if entry.link is not None)

    @property
    def is_empty(self) -> bool:
        return not self.links

    @property
    def needs_decision(self) -> bool:
        """
        누군가 더 결정해야 하는가.

        판정 불가가 남아 있거나, 필요한 정보가 없어 막힌 후보가 있거나,
        순서가 규칙으로 정해지지 않았다면 참이다. **우선권과 체인 진행
        계층이 결정할 몫**이고 이 모듈은 정하지 않는다.
        """
        return bool(self.unresolved) or bool(self.blocked) or not self.is_rule_ordered

    def canonical_state(self) -> tuple:
        return (
            self.event.canonical_state(),
            self.base_chain.canonical_state(),
            tuple(e.canonical_state() for e in self.entries),
            tuple(e.canonical_state() for e in self.skipped),
            tuple(e.canonical_state() for e in self.unresolved),
            self.is_rule_ordered,
            self.unresolved_rules,
        )

    def to_dict(self) -> dict:
        return {
            "event": self.event.to_dict(),
            "base_chain": self.base_chain.to_dict(),
            "entries": [e.to_dict() for e in self.entries],
            "skipped": [e.to_dict() for e in self.skipped],
            "unresolved": [e.to_dict() for e in self.unresolved],
            "is_rule_ordered": self.is_rule_ordered,
            "unresolved_rules": list(self.unresolved_rules),
            "needs_decision": self.needs_decision,
        }

    def describe_ko(self) -> str:
        return (
            f"{self.event.point.value}: 삽입 {len(self.insertable)} · "
            f"정보 부족 {len(self.blocked)} · 판정 불가 {len(self.unresolved)} · "
            f"제외 {len(self.skipped)}"
        )

    def __len__(self) -> int:
        return len(self.links)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TriggerChainIntegrator:
    """
    트리거 계층의 결과를 체인에 **잇는다.** 규칙을 다시 만들지 않는다.

    ``GameState`` 를 아예 받지 않는다 — 관측(:class:`GameStateView`)과
    불변 ``Chain`` 만 다루므로 판을 바꿀 수단이 없다.
    """

    __slots__ = ("_view", "_registry", "_definitions", "_implementations")

    def __init__(
        self,
        view: GameStateView,
        registry: TriggerRegistry,
        definitions: EffectDefinitionSource | None = None,
        implementations: EffectImplementationLookup | None = None,
    ):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "TriggerChainIntegrator 는 GameStateView 만 받습니다. "
                "GameState 를 직접 넘기면 통합이 판을 바꿀 수 있게 됩니다."
            )
        if not isinstance(registry, TriggerRegistry):
            raise TypeError(f"TriggerRegistry 가 필요합니다: {type(registry).__name__}")
        self._view = view
        self._registry = registry
        self._definitions = definitions
        self._implementations = implementations

    @property
    def view(self) -> GameStateView:
        return self._view

    # ------------------------------------------------------------------
    def collect_and_order(self, event: TimingEvent) -> TriggerOrdering:
        """
        수집 → 판정 → 정리를 한 번에. **전부 앞 계층의 것을 그대로 부른다.**

        체인을 건드리지 않고 판도 읽기만 한다.
        """
        collection = TriggerCollector(
            self._view, self._registry, self._definitions
        ).collect(event)
        judged = TriggerEligibilityJudge(
            self._view, self._definitions, self._implementations
        ).judge_all(collection, self._registry)
        return TriggerOrderer(self._view).order(event, judged)

    def plan(self, chain: Chain, ordering: TriggerOrdering) -> TriggerChainPlan:
        """
        무엇이 체인에 들어갈 수 있는지 정한다. **아직 넣지 않는다.**

        ``ordering`` 의 순서를 **그대로** 쓴다 — 다시 정렬하지 않으므로
        입력 순서가 결과를 바꾸지 않는다 (F-3-C 가 이미 보장한다).
        """
        if not isinstance(chain, Chain):
            raise TypeError(f"Chain 이 필요합니다: {type(chain).__name__}")
        if not isinstance(ordering, TriggerOrdering):
            raise TypeError(
                f"TriggerOrdering 이 필요합니다: {type(ordering).__name__}"
            )

        started = bool(chain.resolved_count)
        sequence = len(chain)
        entries: list[TriggerChainEntry] = []
        for eligibility in ordering.canonical_sequence:
            entry = self._entry(eligibility, sequence, started)
            entries.append(entry)
            if entry.link is not None:
                sequence += 1

        return TriggerChainPlan(
            event=ordering.event,
            base_chain=chain,
            entries=tuple(entries),
            skipped=tuple(self._refused(e) for e in ordering.excluded),
            unresolved=tuple(self._undecided(e) for e in ordering.unordered),
            is_rule_ordered=ordering.is_rule_ordered,
            unresolved_rules=ordering.unresolved_rules,
        )

    def extend(self, chain: Chain, plan: TriggerChainPlan) -> Chain:
        """
        계획대로 링크를 쌓은 **새 체인**을 돌려준다.

        원래 체인은 바뀌지 않는다 (``Chain`` 이 불변이다). 효과를 해결하지
        않는다 — 그것은 ``ChainResolver`` 의 일이고, 그 사이에 우선권이 있다.
        """
        if plan.base_chain != chain:
            raise TriggerError(
                "다른 체인으로 세운 계획입니다. 계획은 그 체인에서만 "
                "유효합니다 (링크 번호가 어긋납니다)."
            )
        extended = chain
        for link in plan.links:
            extended = extended.push(link)
        return extended

    # ------------------------------------------------------------------
    def _entry(
        self, eligibility: TriggerEligibility, sequence: int, started: bool
    ) -> TriggerChainEntry:
        """``ELIGIBLE`` 후보 하나를 링크로 만들 수 있는지 본다."""
        candidate = eligibility.candidate
        if eligibility.status is not TriggerStatus.ELIGIBLE:  # pragma: no cover
            # 정리 계층이 이미 갈라 놓았다. 그래도 조용히 통과시키지 않는다.
            return self._refused(eligibility)

        if started:
            return TriggerChainEntry(
                eligibility,
                ChainInsertion.NOT_INSERTABLE,
                ValidationCode.RULE_NOT_IMPLEMENTED,
                "이미 해결이 시작된 체인에는 링크를 쌓을 수 없습니다. "
                "해결 중 발동은 타이밍 계층의 몫입니다.",
            )

        definition = (
            self._definitions.definition_for(candidate.effect_ref)
            if self._definitions is not None
            else None
        )
        if definition is None:
            return TriggerChainEntry(
                eligibility,
                ChainInsertion.UNKNOWN,
                ValidationCode.CHAIN_DEFINITION_UNAVAILABLE,
                f"{candidate.effect_ref} 의 정의가 없어 무엇이 필요한지 "
                "확인할 수 없습니다.",
                notes=("정의 미등록",),
            )

        # 실행 권위를 **여기서 다시 확인한다.** 적격성 판정이 이미 봤지만,
        # 이 지점이 효과가 실행 경로로 들어가는 마지막 문이다. ADR-004 의
        # 금지가 손으로 만든 판정 하나로 뚫리지 않게 한다.
        forbidden = self._check_authority(eligibility, definition)
        if forbidden is not None:
            return forbidden

        missing = self._missing_execution_inputs(definition)
        if missing:
            return TriggerChainEntry(
                eligibility,
                ChainInsertion.NOT_INSERTABLE,
                ValidationCode.TOO_FEW_SELECTED
                if "대상" in missing[0]
                else ValidationCode.COST_NOT_IMPLEMENTED,
                "발동에 필요한 것이 아직 정해지지 않았습니다: "
                + ", ".join(missing)
                + ". 가짜로 채워 넣지 않습니다.",
                notes=missing,
            )

        return TriggerChainEntry(
            eligibility,
            ChainInsertion.INSERTABLE,
            ValidationCode.OK,
            f"체인 {sequence + 1} 로 넣을 수 있습니다.",
            link=ChainLink(
                sequence=sequence,
                actor=candidate.controller,
                effect_ref=candidate.effect_ref,
                source=candidate.source,
            ),
        )

    def _check_authority(
        self, eligibility: TriggerEligibility, definition: EffectDefinition
    ) -> TriggerChainEntry | None:
        """
        출처와 구현이 실행을 허용하는가. **마지막 확인이다.**

        ``TEXT_DERIVED`` 는 다른 모든 것이 통과해도 링크가 되지 않는다
        (ADR-004). "검증된 의미" 와 "실행 가능" 도 여전히 다른 질문이다
        (ADR-006).
        """
        availability = execution_availability(definition, self._implementations)
        if availability is ExecutionAvailability.EXECUTABLE:
            return None
        if availability is ExecutionAvailability.FORBIDDEN_SOURCE:
            return TriggerChainEntry(
                eligibility,
                ChainInsertion.NOT_INSERTABLE,
                ValidationCode.EXECUTION_FORBIDDEN,
                "공식 텍스트에서 유추한 효과는 실행 경로에 넣지 않습니다 "
                "(ADR-004).",
            )
        return TriggerChainEntry(
            eligibility,
            ChainInsertion.UNKNOWN,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"실행할 수 있는지 확인되지 않았습니다: {availability.value}. "
            "검증된 의미만으로는 실행하지 않습니다 (ADR-006).",
            notes=(availability.value,),
        )

    def _missing_execution_inputs(
        self, definition: EffectDefinition
    ) -> tuple[str, ...]:
        """
        링크를 만들려면 있어야 하는데 **트리거 계층이 갖고 있지 않은 것**.

        대상 선택과 비용 영수증이다. 둘 다 이 계층 밖에서 정해지고, 없는
        것을 빈 값으로 채우면 대상 없이 해결되는 효과와 비용을 안 낸 효과가
        조용히 판에 들어간다.
        """
        missing: list[str] = []
        if definition.requires_target:
            missing.append(
                "대상 선택 ("
                + ", ".join(str(ref) for ref in definition.target_refs)
                + ")"
            )
        if definition.has_cost:
            missing.append(f"비용 지불 영수증 ({definition.cost.describe_ko()})")
        return tuple(missing)

    def _refused(self, eligibility: TriggerEligibility) -> TriggerChainEntry:
        """확실히 들어가지 못하는 것. **왜인지를 남긴다.**"""
        blocking = ", ".join(v.gate.value for v in eligibility.blocking) or "없음"
        if eligibility.status is TriggerStatus.FORBIDDEN:
            return TriggerChainEntry(
                eligibility,
                ChainInsertion.NOT_INSERTABLE,
                ValidationCode.EXECUTION_FORBIDDEN,
                f"출처가 실행을 금지합니다 (막힌 관문: {blocking}).",
            )
        return TriggerChainEntry(
            eligibility,
            ChainInsertion.NOT_INSERTABLE,
            ValidationCode.RULE_NOT_IMPLEMENTED,
            f"발동 조건을 만족하지 않습니다 (막힌 관문: {blocking}).",
        )

    def _undecided(self, eligibility: TriggerEligibility) -> TriggerChainEntry:
        """
        판정할 수 없는 것. **"트리거가 없다" 고 결론내지 않는다.**
        """
        blocking = ", ".join(v.gate.value for v in eligibility.blocking) or "없음"
        notes = tuple(
            note
            for verdict in eligibility.blocking
            for note in verdict.result.notes
        )
        return TriggerChainEntry(
            eligibility,
            ChainInsertion.UNKNOWN,
            ValidationCode.INFORMATION_UNAVAILABLE,
            f"발동 가능한지 판정할 수 없습니다 (막힌 관문: {blocking}). "
            "트리거가 없다는 뜻이 아닙니다.",
            notes=notes,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TriggerChainIntegrator {self._registry!r}>"


__all__ = [
    "ChainInsertion",
    "TriggerChainEntry",
    "TriggerChainPlan",
    "TriggerChainIntegrator",
]
