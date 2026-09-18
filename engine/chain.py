"""
체인 — **무엇이 쌓였고 어떤 순서로 해결하는가**.

    ChainLink (발동하기로 결정된 효과 하나)
        ↓  chain.push(link)
    Chain     [L1, L2, L3]
        ↓  ChainResolver.resolve_top(state, chain)
    L3 → L2 → L1                    (LIFO)
        ↓  EffectExecutor.execute(...)
    GameState 변경 + StateDelta + EventJournal

세 가지를 한 곳에 몰아넣지 않는다
---------------------------------
=====================  ==========================================
``PriorityState``       누가 다음 응답 기회를 갖는가        (Phase 2-F-1)
``Chain``               지금 어떤 효과들이 연결되어 있는가  여기
``ChainResolver``       연결된 효과를 어떤 순서로 해결하는가  여기
=====================  ==========================================

``PriorityState.resolve_chain()`` 같은 것은 **만들지 않는다.** 우선권은
체인을 모르고, 체인은 우선권을 모른다. 둘을 잇는 것은 이후 단계의 몫이다.

체인이 효과를 적용하지 않는다
-----------------------------
:class:`ChainResolver` 는 ``GameState`` 를 **직접 바꾸지 않는다.** 무엇을
언제 해결할지 정하고, 적용은 :class:`~engine.effect.executor.EffectExecutor`
에 넘긴다. 존 이동 · Delta · Journal 은 전부 실행기가 하던 그대로다 — 여기서
다시 구현하면 두 경로가 갈린다.

정의를 복사해 넣지 않는다
-------------------------
:class:`ChainLink` 는 ``EffectRef(card_id, ordinal)`` 만 들고 있고, 정의는
:class:`~engine.effect.definition.EffectDefinitionSource` 에서 찾는다. 링크에
정의를 박아 두면 같은 링크가 낡은 정의를 영구히 들고 다닌다.

``EffectSpec.index`` (Lua 변수명 ``"e1"``, 한 카드 안에서 중복 — 실측
4,884장) 를 실행 identity 로 쓰지 않는다는 Phase 2-D-1 의 원칙 그대로다.

비용은 이미 치러진 것으로 본다
------------------------------
:class:`ChainLink` 는 비용을 **다시 치르지 않는다.** 흐름은 한 방향이다.

    Cost → CostSelection → CostPayer.pay() → CostPayment (영수증)
                                                  ↓
                                            ChainLink 생성

링크는 영수증(:class:`~engine.cost.CostPayment`)을 참조로만 들고 있다.
``CostPaymentEvent.effect_ref`` 연결이 아직 선택적이므로 (STRUCTURAL-16),
그것을 우회하는 구조를 만들지 않고 링크가 자기 ``effect_ref`` 를 따로 갖는다.

타이밍은 여기 없다
------------------
트리거 · when/if · 임의/강제 · SEGOC · 스펠 스피드 · 발동 합법성은 전부
이후 단계다. 이 모듈은 "쌓인 것을 역순으로 해결한다" 는 구조만 갖는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.cost import CostPayment
from engine.effect.definition import EffectDefinition, EffectDefinitionSource
from engine.effect.delta import StateDelta
from engine.effect.executor import EffectExecutor
from engine.effect.resolution import EffectResult, ResolutionContext, ResolutionStatus
from engine.effect.target import TargetSelection
from engine.ids import EffectRef, InstanceId
from engine.state.game_state import GameState
from engine.validation import ValidationCode


class ChainError(ValueError):
    """
    체인의 **모양**이 틀렸다. 규칙 위반이 아니다.

    "이 효과를 지금 발동할 수 있는가" 는 발동 합법성이고 이 단계에 없다.
    여기서 거부하는 것은 "번호가 어긋난 링크를 끼워 넣는다" 처럼 구조적으로
    표현될 수 없는 것들이다.
    """


@dataclass(frozen=True, slots=True)
class ChainLink:
    """
    **이미 발동하기로 결정된 효과 하나.** 불변이다.

    발동해도 되는지는 여기서 판정하지 않는다 — 링크가 만들어졌다는 것은 그
    결정이 이미 끝났다는 뜻이다. 발동 합법성 계층은 아직 없다.

    담는 것은 전부 안정적인 식별자다. ``EffectDefinition`` 도
    ``CardInstance`` 도 ``GameState`` 도 담지 않는다.
    """

    sequence: int
    """체인 안에서 몇 번째인가. **0부터**이고, 체인 1 이 ``sequence=0`` 이다."""
    actor: int
    """이 효과를 발동한 플레이어. 카드의 주인 · 컨트롤러와 다를 수 있다."""
    effect_ref: EffectRef
    source: InstanceId | None = None
    """발동한 카드. 필드를 떠난 뒤 해결되는 효과가 있으므로 없을 수 있다."""
    selections: tuple[TargetSelection, ...] = ()
    """
    **발동 시점에 이미 골라진** 대상들. 이름별로 잇는다.

    여기서 다시 계산하지 않는다 — 후보(``CandidateSet``)와 고른 결과
    (``Selection``)는 다른 것이고, 링크가 담는 것은 결과뿐이다.
    """
    payments: tuple[CostPayment, ...] = ()
    """
    이 발동을 위해 **이미 치른** 비용의 영수증. 참조일 뿐이고, 해결 중에
    다시 치르지 않는다.
    """

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ChainError(f"체인 번호는 0 이상입니다: {self.sequence}")
        if self.actor not in (0, 1):
            raise ChainError(f"actor 는 0 또는 1 입니다: {self.actor}")
        for name in ("selections", "payments"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 는 tuple 이어야 합니다 — 링크는 불변입니다.")
        seen: set = set()
        for chosen in self.selections:
            if chosen.ref in seen:
                raise ChainError(f"대상 {chosen.ref} 에 선택이 두 번 들어왔습니다.")
            seen.add(chosen.ref)

    # ------------------------------------------------------------------
    @property
    def chain_number(self) -> int:
        """사람이 부르는 번호. "체인 1" 은 :attr:`sequence` 0 이다."""
        return self.sequence + 1

    @property
    def card_id(self) -> int:
        """발동한 효과가 어느 카드의 것인가. 정의가 아니라 식별자다."""
        return self.effect_ref.card_id

    @property
    def paid_anything(self) -> bool:
        return bool(self.payments)

    def resolution_context(self) -> ResolutionContext:
        """
        이 링크를 해결할 때의 문맥.

        ``cost_selections`` 는 비운다 — 비용은 링크가 만들어지기 **전에**
        이미 치러졌고, 무엇을 냈는지는 :attr:`payments` 에 있다. 문맥에
        다시 넣으면 실행기가 두 번 치를 길이 생긴다.

        체인 전체를 넣지 않는다. 링크 하나를 해결하는 데 다른 링크가 필요한
        규칙(체인 위의 카드 수 등)은 아직 없고, 필요해지면 안정적인 식별자만
        넘긴다.
        """
        return ResolutionContext(
            effect_ref=self.effect_ref,
            controller=self.actor,
            source=self.source,
            selections=self.selections,
        )

    def canonical_state(self) -> tuple:
        return (
            self.sequence,
            self.actor,
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.source.value if self.source is not None else None,
            tuple(s.canonical_state() for s in self.selections),
            tuple(p.canonical_state() for p in self.payments),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "sequence": self.sequence,
            "actor": self.actor,
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
        }
        if self.source is not None:
            data["source"] = self.source.value
        if self.selections:
            data["selections"] = [s.to_dict() for s in self.selections]
        if self.payments:
            data["payments"] = [p.to_dict() for p in self.payments]
        return data

    def describe_ko(self) -> str:
        chosen = (
            " 대상 " + ", ".join(str(s) for s in self.selections)
            if self.selections
            else ""
        )
        return f"체인{self.chain_number} P{self.actor} {self.effect_ref}{chosen}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class Chain:
    """
    쌓인 링크들과 **어디까지 해결했는가**. 불변이다.

    :attr:`links` 는 **발동 순서**(체인 1 이 앞)이고, 해결은 뒤에서부터
    한다 (LIFO). :attr:`resolved_count` 가 뒤에서 몇 개를 이미 해결했는지
    말한다.

    ``GameState`` 안에 살지 않는다. 체인은 판의 **모양**이 아니라 흐름의
    위치이고, ``state_hash()`` 에 섞으면 "같은 판" 의 뜻이 달라진다
    (``EventJournal`` · ``PriorityState`` 와 같은 이유).
    """

    links: tuple[ChainLink, ...] = ()
    resolved_count: int = 0
    """**뒤에서부터** 이미 해결한 링크 수."""

    def __post_init__(self) -> None:
        if not isinstance(self.links, tuple):
            raise TypeError("links 는 tuple 이어야 합니다 — 체인은 불변입니다.")
        for index, link in enumerate(self.links):
            if link.sequence != index:
                raise ChainError(
                    f"{index}번 자리에 번호 {link.sequence} 인 링크가 있습니다. "
                    "체인 번호는 자리와 같아야 합니다."
                )
        if not 0 <= self.resolved_count <= len(self.links):
            raise ChainError(
                f"해결한 수({self.resolved_count})가 링크 수"
                f"({len(self.links)})와 맞지 않습니다."
            )

    # ------------------------------------------------------------------
    # 쌓기 — 새 체인을 돌려준다
    # ------------------------------------------------------------------
    def push(self, link: ChainLink) -> "Chain":
        """
        링크를 쌓는다. **기존 체인은 바뀌지 않는다.**

        번호가 어긋나면 거부한다 — 조용히 다시 매기면 기록과 실제 발동
        순서가 달라진 것을 아무도 모르게 된다 (``EventJournal.append`` 와
        같은 태도다).

        해결이 시작된 체인에는 쌓을 수 없다. 규칙상 가능한지의 문제가
        아니라, LIFO 순서와 번호를 **구조적으로 표현할 수 없기** 때문이다.
        해결 중 발동을 다루는 것은 타이밍 계층의 몫이다.
        """
        if not isinstance(link, ChainLink):
            raise TypeError(f"ChainLink 가 필요합니다: {type(link).__name__}")
        if self.resolved_count:
            raise ChainError(
                "이미 해결이 시작된 체인에는 링크를 쌓을 수 없습니다 "
                f"({self.resolved_count}개 해결됨)."
            )
        if link.sequence != len(self.links):
            raise ChainError(
                f"다음 체인 번호는 {len(self.links)} 인데 {link.sequence} 가 "
                "들어왔습니다."
            )
        return Chain(links=self.links + (link,), resolved_count=0)

    def activate(
        self,
        actor: int,
        effect_ref: EffectRef,
        source: InstanceId | None = None,
        selections: tuple[TargetSelection, ...] = (),
        payments: tuple[CostPayment, ...] = (),
    ) -> "Chain":
        """다음 번호를 붙여 링크를 만들고 쌓는다. 부르는 쪽이 편한 쪽이다."""
        return self.push(
            ChainLink(
                sequence=len(self.links),
                actor=actor,
                effect_ref=effect_ref,
                source=source,
                selections=selections,
                payments=payments,
            )
        )

    def advanced(self) -> "Chain":
        """맨 위 링크를 해결한 것으로 표시한 새 체인. **해결하지는 않는다.**"""
        if self.is_complete:
            raise ChainError("남은 링크가 없습니다.")
        return Chain(links=self.links, resolved_count=self.resolved_count + 1)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        """쌓인 것이 하나도 없는가. **"다 해결했다" 와 다른 사실이다.**"""
        return not self.links

    @property
    def is_complete(self) -> bool:
        """남은 링크가 없는가. 빈 체인도 남은 것이 없으므로 참이다."""
        return self.resolved_count >= len(self.links)

    @property
    def pending(self) -> tuple[ChainLink, ...]:
        """아직 해결하지 않은 링크들. **발동 순서**대로다."""
        end = len(self.links) - self.resolved_count
        return self.links[:end]

    @property
    def resolved(self) -> tuple[ChainLink, ...]:
        """이미 해결한 링크들. 해결한 순서(= 발동 역순)대로다."""
        end = len(self.links) - self.resolved_count
        return tuple(reversed(self.links[end:]))

    @property
    def remaining(self) -> int:
        return len(self.links) - self.resolved_count

    @property
    def top(self) -> ChainLink | None:
        """
        **다음에 해결할** 링크. 남은 것이 없으면 ``None``.

        가장 나중에 쌓인 것이 가장 먼저 해결된다 (LIFO).
        """
        pending = self.pending
        return pending[-1] if pending else None

    @property
    def resolution_order(self) -> tuple[ChainLink, ...]:
        """해결될 순서 전체. 발동 순서의 역순이다."""
        return tuple(reversed(self.links))

    def link(self, sequence: int) -> ChainLink:
        """번호로 링크를 찾는다. 없으면 :class:`ChainError`."""
        for held in self.links:
            if held.sequence == sequence:
                return held
        raise ChainError(f"체인에 번호 {sequence} 인 링크가 없습니다.")

    def __len__(self) -> int:
        return len(self.links)

    def __iter__(self):
        return iter(self.links)

    def __getitem__(self, index: int) -> ChainLink:
        return self.links[index]

    # ------------------------------------------------------------------
    def canonical_state(self) -> tuple:
        return (
            tuple(link.canonical_state() for link in self.links),
            self.resolved_count,
        )

    def to_dict(self) -> dict:
        return {
            "links": [link.to_dict() for link in self.links],
            "resolved_count": self.resolved_count,
        }

    def describe_ko(self) -> str:
        if self.is_empty:
            return "체인 없음"
        return (
            f"체인 {len(self.links)}개 (해결 {self.resolved_count} / "
            f"남음 {self.remaining})"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class ChainResolutionStatus(str, Enum):
    """
    링크 하나를 해결하려 한 결과.

    **``RESOLVED`` 하나만 판을 바꾼다.** 나머지는 전부 "아무 일도 일어나지
    않았다" 를 뜻하고, 이유만 다르다.
    """

    RESOLVED = "resolved"
    """링크가 적용되었다. 판이 바뀌었을 수 있다."""
    EMPTY_CHAIN = "empty_chain"
    """쌓인 링크가 하나도 없다."""
    CHAIN_COMPLETE = "chain_complete"
    """
    남은 링크가 없다. :attr:`EMPTY_CHAIN` 과 **다른 사실**이다 — 하나도
    쌓이지 않은 것과 다 해결한 것은 같지 않다.
    """
    INVALID_CHAIN_LINK = "invalid_chain_link"
    """링크 자체가 해결될 수 없다 (정의를 찾을 수 없음 · 문맥 불일치 · 대상 문제)."""
    FORBIDDEN_EFFECT = "forbidden_effect"
    """
    출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004).

    ``UNSUPPORTED_EFFECT`` 와 합치지 않는다 — "이 엔진이 못 한다" 와 "이
    근거로는 절대 실행하지 않는다" 는 전혀 다른 말이다.
    """
    UNSUPPORTED_EFFECT = "unsupported_effect"
    """실행기가 이 효과(또는 그 안의 일)를 다루지 못한다."""
    EFFECT_NOT_APPLIED = "effect_not_applied"
    """
    실행기가 적용하지 않았다. 조건이 거짓이거나, 판정할 수 없거나, 구현이
    등록되어 있지 않다 — **정확한 이유는 :attr:`ChainResolution.result` 에**
    그대로 남는다.
    """
    EFFECT_RESOLUTION_ERROR = "effect_resolution_error"
    """적용 중에 오류가 났다. 판이 반쯤 바뀌어 있을 수 있다."""


#: 실행기의 결과 → 체인 계층의 분류.
#:
#: 거친 분류일 뿐이고, **정확한 이유는 언제나 ``EffectResult`` 가 들고 있다.**
#: 여기서 뭉개는 것이 있으면 ``ChainResolution.result`` 를 보면 된다.
STATUS_MAP: dict[ResolutionStatus, ChainResolutionStatus] = {
    ResolutionStatus.RESOLVED: ChainResolutionStatus.RESOLVED,
    ResolutionStatus.FORBIDDEN: ChainResolutionStatus.FORBIDDEN_EFFECT,
    ResolutionStatus.UNSUPPORTED_OPERATION: ChainResolutionStatus.UNSUPPORTED_EFFECT,
    ResolutionStatus.INVALID_OPERATION: ChainResolutionStatus.UNSUPPORTED_EFFECT,
    ResolutionStatus.INVALID_CONTEXT: ChainResolutionStatus.INVALID_CHAIN_LINK,
    ResolutionStatus.INVALID_TARGET: ChainResolutionStatus.INVALID_CHAIN_LINK,
    ResolutionStatus.EXECUTION_ERROR: ChainResolutionStatus.EFFECT_RESOLUTION_ERROR,
    ResolutionStatus.NOT_IMPLEMENTED: ChainResolutionStatus.EFFECT_NOT_APPLIED,
    ResolutionStatus.CONDITION_FALSE: ChainResolutionStatus.EFFECT_NOT_APPLIED,
    ResolutionStatus.CONDITION_UNKNOWN: ChainResolutionStatus.EFFECT_NOT_APPLIED,
    ResolutionStatus.INSUFFICIENT_CARDS: ChainResolutionStatus.EFFECT_NOT_APPLIED,
    ResolutionStatus.UNKNOWN: ChainResolutionStatus.EFFECT_NOT_APPLIED,
}


@dataclass(frozen=True, slots=True)
class ChainResolution:
    """
    링크 하나를 해결하려 한 결과. **불변**이다.

    :attr:`chain` 은 이 시도 **뒤의** 체인이다. 실패하면 들어온 것과 같다 —
    실패한 링크를 건너뛰지 않는다.
    """

    status: ChainResolutionStatus
    chain: Chain
    code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED
    reason: str = ""
    link: ChainLink | None = None
    """무엇을 해결하려 했는가. 체인이 비어 있으면 ``None``."""
    result: EffectResult | None = None
    """
    실행기의 답 그대로. 체인 계층이 뭉갠 세부 이유가 전부 여기 있다.
    실행기까지 가지 못했으면 ``None``.
    """

    def __post_init__(self) -> None:
        if self.status is not ChainResolutionStatus.RESOLVED and self.deltas:
            raise ChainError(
                f"{self.status.value} 인데 변화 기록이 있습니다. 해결되지 "
                "않은 링크는 판을 바꾸지 않습니다."
            )

    @property
    def resolved(self) -> bool:
        return self.status is ChainResolutionStatus.RESOLVED

    @property
    def deltas(self) -> tuple[StateDelta, ...]:
        """이 링크가 판을 어떻게 바꿨는가. 실행기의 기록을 그대로 내보낸다."""
        return self.result.deltas if self.result is not None else ()

    @property
    def changed_state(self) -> bool:
        return bool(self.deltas)

    def __bool__(self) -> bool:
        raise TypeError(
            "ChainResolution 을 참/거짓으로 쓸 수 없습니다. 해결되지 않은 "
            "것이 조용히 성공으로 읽히는 것을 막기 위해서입니다. "
            "`resolution.resolved` 를 보세요."
        )

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.code.value,
            self.reason,
            self.link.canonical_state() if self.link is not None else None,
            self.result.canonical_state() if self.result is not None else None,
            self.chain.canonical_state(),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "code": self.code.value,
            "reason": self.reason,
            "chain": self.chain.to_dict(),
        }
        if self.link is not None:
            data["link"] = self.link.to_dict()
        if self.result is not None:
            data["result"] = self.result.to_dict()
        return data

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"{self.status.value}[{self.code.value}]: {self.reason}"


class ChainResolver:
    """
    쌓인 링크를 **역순으로** 해결한다.

    **효과를 적용하는 방법은 여기 없다.** 그것은
    :class:`~engine.effect.executor.EffectExecutor` 의 일이고, 이 클래스는
    "무엇을 언제" 만 정한다. Delta 도 Journal 도 실행기가 하던 그대로
    만들어지므로, 체인을 거친 해결과 직접 해결이 같은 기록을 남긴다.

    실패한 링크를 **건너뛰지 않는다.** "해결할 수 없는 링크는 불발된다" 는
    유희왕 규칙이 있지만, 그것은 규칙이고 이 단계에 없다. 지어내지 않고
    멈춘 뒤 부르는 쪽에 알린다.
    """

    __slots__ = ("_executor", "_definitions")

    def __init__(self, executor: EffectExecutor, definitions: EffectDefinitionSource):
        if not isinstance(executor, EffectExecutor):
            raise TypeError(
                f"EffectExecutor 가 필요합니다: {type(executor).__name__}. "
                "체인은 효과를 스스로 적용하지 않습니다."
            )
        if not hasattr(definitions, "definition_for"):
            raise TypeError(
                "정의를 찾을 수 있는 것이 필요합니다 (definition_for). "
                "링크는 EffectRef 만 들고 있습니다."
            )
        self._executor = executor
        self._definitions = definitions

    @property
    def executor(self) -> EffectExecutor:
        return self._executor

    @property
    def definitions(self) -> EffectDefinitionSource:
        return self._definitions

    # ------------------------------------------------------------------
    def next_link(self, chain: Chain) -> ChainLink | None:
        """다음에 해결할 링크. **조회일 뿐이고 판을 건드리지 않는다.**"""
        return chain.top

    def definition_for(self, link: ChainLink) -> EffectDefinition | None:
        """그 링크가 가리키는 정의. 없으면 ``None`` — 지어내지 않는다."""
        return self._definitions.definition_for(link.effect_ref)

    def resolve_top(self, state: GameState, chain: Chain) -> ChainResolution:
        """
        맨 위 링크 하나를 해결한다.

        ``state`` 는 바뀔 수 있지만, :attr:`ChainResolutionStatus.RESOLVED`
        일 때만 그렇다. 그 밖의 결과에서는 실행기가 판을 건드리지 않았으므로
        한 글자도 바뀌지 않는다 (``EFFECT_RESOLUTION_ERROR`` 제외).
        """
        if not isinstance(state, GameState):
            raise TypeError(
                "ChainResolver 는 GameState 를 받습니다. 관측(GameStateView)은 "
                "읽기 전용이라 적용할 수 없습니다."
            )
        if chain.is_empty:
            return ChainResolution(
                ChainResolutionStatus.EMPTY_CHAIN,
                chain,
                ValidationCode.CHAIN_EMPTY,
                "쌓인 링크가 없습니다.",
            )
        if chain.is_complete:
            return ChainResolution(
                ChainResolutionStatus.CHAIN_COMPLETE,
                chain,
                ValidationCode.OK,
                f"링크 {len(chain)}개를 모두 해결했습니다.",
            )

        link = chain.top
        assert link is not None  # 위에서 비었는지 확인했다
        definition = self.definition_for(link)
        if definition is None:
            return ChainResolution(
                ChainResolutionStatus.INVALID_CHAIN_LINK,
                chain,
                ValidationCode.CHAIN_DEFINITION_UNAVAILABLE,
                f"{link.effect_ref} 의 정의가 등록되어 있지 않아 해결할 수 "
                "없습니다.",
                link=link,
            )

        result = self._executor.execute(state, definition, link.resolution_context())
        status = STATUS_MAP.get(
            result.status, ChainResolutionStatus.EFFECT_NOT_APPLIED
        )
        if status is not ChainResolutionStatus.RESOLVED:
            # 실패한 링크를 해결한 것으로 표시하지 않는다.
            return ChainResolution(
                status,
                chain,
                result.code,
                f"{link.describe_ko()} 를 해결하지 못했습니다: {result.reason}",
                link=link,
                result=result,
            )
        return ChainResolution(
            ChainResolutionStatus.RESOLVED,
            chain.advanced(),
            ValidationCode.OK,
            f"{link.describe_ko()} 를 해결했습니다.",
            link=link,
            result=result,
        )

    def resolve_all(
        self, state: GameState, chain: Chain
    ) -> tuple[ChainResolution, ...]:
        """
        남은 링크를 **역순으로** 끝까지 해결한다.

        하나라도 해결하지 못하면 **거기서 멈춘다.** 마지막 결과의
        :attr:`ChainResolution.chain` 이 그 시점의 체인이다.

        체인이 끝난 뒤 무엇을 할지(우선권을 어떻게 돌릴지, 트리거를 언제
        확인할지)는 여기서 정하지 않는다.
        """
        steps: list[ChainResolution] = []
        current = chain
        while True:
            step = self.resolve_top(state, current)
            steps.append(step)
            if not step.resolved:
                break
            current = step.chain
            if current.is_complete:
                break
        return tuple(steps)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ChainResolver {self._executor!r}>"


__all__ = [
    "ChainError",
    "ChainLink",
    "Chain",
    "ChainResolutionStatus",
    "ChainResolution",
    "ChainResolver",
    "STATUS_MAP",
]
