"""
덱 구성과 전개 계획의 **데이터 모델** (Phase 4-B).

여기 있는 것은 전부 **읽는 쪽을 위한 기록**이다. 어떤 것도 스스로 판정하지
않는다 — 판정은 :mod:`deck.validator` 와 :mod:`deck.planner` 가 하고, 그
결과가 이 모델에 담긴다.

🔴 **세 가지 상태를 끝까지 분리한다.**

* :class:`ValidationOutcome` — 덱 규격을 **지켰는가**
* :class:`StepStatus` — 전개 한 걸음이 **확실한가**
* :class:`StepBasis` — 그 걸음의 **근거가 어디서 왔는가**

상태를 합치면 "검증 못 한 것" 이 "통과" 로 사라진다. 이 저장소가 이미
``AnalysisStatus`` (근거 계층) 와 ``HandlerBinding`` (증명 계층) 을 합치지
않기로 정한 것과 같은 이유다 (Phase 3-F-40).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CardRole(str, Enum):
    """덱에서 카드가 맡는 자리. **관측 가능한 신호로만** 분류한다."""

    THEME_CORE = "theme_core"
    """테마(공식 setcode)에 속한 카드."""
    HAND_TRAP = "hand_trap"
    """
    패에서 발동 가능한 효과에 **무효/무력화 범주가 확인된** 몬스터.

    🔴 Phase 5-D 가 기준을 좁혔다. 그 전에는 ``has_effect_from("HAND")``
    하나로 붙였고, 그것은 ``SetRange`` 에 ``LOCATION_HAND`` 이 있는지만
    보므로 **특수 소환 절차까지** 이 역할로 들어왔다 (실측: 메인 덱 몬스터
    1,795장이 해당, 그중 587장은 발동 가능한 효과가 아예 없음). 지금 기준에
    맞는 것은 **37장**이다.

    🔴 그래도 "상대를 막는다" 는 뜻이 아니다 — 무효화의 대상이 누구인지는
    Lua 범주에 없다 (:mod:`deck.evidence` 참조).
    """
    HAND_ACTIVATABLE = "hand_activatable"
    """
    패에서 **발동은 가능하지만** 무엇을 하는 효과인지 판정하지 못했다.

    🔴 :attr:`HAND_TRAP` 과 **다른 역할이다.** 합치면 Phase 5-D 가 고친
    결함이 돌아온다.
    """
    SELF_SPECIAL_SUMMON = "self_special_summon"
    """패에서 스스로 특수 소환하는 절차를 가진 몬스터."""
    GENERIC_SPELL_TRAP = "generic_spell_trap"
    """테마 밖의 마법·함정."""
    EXTRA_DECK = "extra_deck"
    """엑스트라 덱 카드 (융합·싱크로·엑시즈·링크)."""
    UNCLASSIFIED = "unclassified"
    """🔴 분류 신호가 없다. **추측해서 역할을 붙이지 않는다.**"""

    def describe_ko(self) -> str:
        return _ROLE_KO[self]


_ROLE_KO: dict[CardRole, str] = {
    CardRole.THEME_CORE: "테마 카드",
    #: 🔴 "패트랩 계열" 이라고 적지 않는다. 측정한 것은 발동 위치와 범주
    #: 이고, 그것이 곧 패트랩이라는 역할은 아니다 (Phase 5-D).
    CardRole.HAND_TRAP: "패에서 발동 · 무효/무력화 범주 확인",
    CardRole.HAND_ACTIVATABLE: "패에서 발동 가능 (효과 내용 미판정)",
    CardRole.SELF_SPECIAL_SUMMON: "패에서 자체 특수 소환",
    CardRole.GENERIC_SPELL_TRAP: "범용 마법·함정",
    CardRole.EXTRA_DECK: "엑스트라 덱",
    CardRole.UNCLASSIFIED: "분류 근거 없음",
}


class RoleEvidence(str, Enum):
    """
    역할이 **어디서 나왔는가**. 🔴 역할 자체와 분리해서 적는다.

    같은 역할이 서로 다른 근거로 붙을 수 있고, 근거가 없을 수도 있다.
    합쳐 두면 "근거 없이 붙은 역할" 과 "측정으로 붙은 역할" 이 구별되지
    않는다 — 그것이 Phase 5-D 가 고친 결함의 형태다. 이 저장소가
    :class:`~analysis.effect_model.AnalysisStatus` (근거 계층) 와
    ``HandlerBinding`` (증명 계층) 을 합치지 않기로 한 것과 같은 이유다.
    """

    OFFICIAL_SETCODE = "official_setcode"
    """공식 setcode 소속 — 카드군 판정에서 나왔다."""
    PRINTED_CARD_TYPE = "printed_card_type"
    """카드 종류(몬스터·마법·함정·엑스트라 덱)에서 나왔다."""
    LUA_EFFECT_BLOCK = "lua_effect_block"
    """Lua 효과 블록의 발동 위치·종류에서 나왔다."""
    LUA_EFFECT_CATEGORY = "lua_effect_category"
    """Lua 효과 블록의 ``CATEGORY_*`` 까지 확인했다. 가장 좁은 근거."""
    NONE = "none"
    """🔴 **근거가 없다.** 그래도 있는 것처럼 적지 않는다."""

    def describe_ko(self) -> str:
        return {
            RoleEvidence.OFFICIAL_SETCODE: "공식 카드군 소속",
            RoleEvidence.PRINTED_CARD_TYPE: "카드 종류",
            RoleEvidence.LUA_EFFECT_BLOCK: "Lua 효과 블록 (발동 위치·종류)",
            RoleEvidence.LUA_EFFECT_CATEGORY: "Lua 효과 범주",
            RoleEvidence.NONE: "근거 없음",
        }[self]


class ValidationOutcome(str, Enum):
    """덱 규격 검사 하나의 결과."""

    SATISFIED = "satisfied"
    """확인된 규칙이고 지켰다."""
    VIOLATED = "violated"
    """확인된 규칙이고 어겼다."""
    UNVERIFIABLE = "unverifiable"
    """🔴 **이 저장소에 그 규칙의 데이터가 없다.** 통과가 아니다."""

    def describe_ko(self) -> str:
        return {
            ValidationOutcome.SATISFIED: "충족",
            ValidationOutcome.VIOLATED: "위반",
            ValidationOutcome.UNVERIFIABLE: "검증 불가 (데이터 없음)",
        }[self]


class StepBasis(str, Enum):
    """전개 한 걸음의 근거가 **어디서 왔는가**."""

    ENGINE_ACTION = "engine_action"
    """
    엔진에 **이 행위 종류의 판정 계층이 있다** (일반 소환 등).

    🔴 :attr:`ENGINE_EXECUTABLE` 과 **다르다.** 이쪽은 행위 계층이고 저쪽은
    그 카드 효과의 실행 구현이다. 합치면 "엔진이 이 카드를 안다" 는 말이 두
    가지 다른 뜻을 갖게 된다 — 일반 소환이 되는 몬스터를 두고 "효과 구현이
    있다" 고 적는 것이 그 과대 진술이다.

    🔴 **"이 판에서 허가받았다" 가 아니다** (보완8 세 항목 ③). 정적 계획은
    엔진을 돌리지 않으므로 어떤 판에서도 허가를 받지 않았다. 그 허가는
    ``ExecutedStep`` 만 말할 수 있다 — 거기 ``accepted`` 가 실측이다.
    """
    ENGINE_EXECUTABLE = "engine_executable"
    """그 카드 효과의 **실행 구현이 엔진에 등록**되어 있다. 가장 강한 근거."""
    LUA_PARSED = "lua_parsed"
    """Lua 원문에서 **파싱된** 효과 블록이 있다. 실행 구현은 없다."""
    PRINTED_TYPE_ONLY = "printed_type_only"
    """카드 종류상 효과가 있다는 것만 안다. 구조화된 근거가 없다."""
    NONE = "none"
    """🔴 근거가 없다. 그래도 **효과를 지어내지 않는다.**"""

    def describe_ko(self) -> str:
        return {
            #: 🔴 **"허가함" 을 쓰지 않는다** (Phase 6-AB 보완8). 이
            #: 계획은 엔진을 **돌리지 않고** 만든다 — 그 문장은 실제 실행에서
            #: 허가를 받았다는 뜻으로 읽혔다 (사용자 보고). 뜻은 그대로이고
            #: 말만 정확히 한다: 행위 계층이 그 종류를 판정할 수 있다.
            StepBasis.ENGINE_ACTION: "엔진의 행위 계층이 판정할 수 있음 (정적 확인)",
            StepBasis.ENGINE_EXECUTABLE: "엔진에 효과 실행 구현 있음",
            StepBasis.LUA_PARSED: "Lua 파싱 근거 있음 (실행 구현 없음)",
            StepBasis.PRINTED_TYPE_ONLY: "카드 종류상 효과만 확인",
            StepBasis.NONE: "근거 없음",
        }[self]


class StepStatus(str, Enum):
    """
    전개 한 걸음이 **얼마나 확실한가**.

    🔴 ``UNKNOWN`` 을 성공으로 바꾸지 않는다. 그리고 ``CONFIRMED`` 는
    "엔진이 실행할 수 있다" 는 뜻이지 **"실제 듀얼에서 합법이다"** 가
    아니다 — 그 주장을 할 수 있는 계층이 아직 없다.
    """

    CONFIRMED = "confirmed"
    """엔진에 실행 구현이 있어 이 걸음을 **돌려볼 수 있다**."""
    CONDITIONAL = "conditional"
    """근거는 있으나 조건을 이 저장소가 판정하지 못한다."""
    UNKNOWN = "unknown"
    """근거가 부족하다. 사람이 확인해야 한다."""
    UNSUPPORTED = "unsupported"
    """🔴 엔진이 **구조적으로 지원하지 않는** 절차다 (특수 소환법 등)."""

    def describe_ko(self) -> str:
        return {
            #: 🔴 **"확정" 을 쓰지 않는다** (Phase 6-AB 보완8). 위
            #: docstring 이 적은 뜻은 *"돌려볼 수 있다"* 인데 "확정" 은
            #: **이미 됐다**로 읽혔다 (사용자 보고 — 실행하지 않은 계획의
            #: 걸음에 그 말이 붙어 있었다).
            StepStatus.CONFIRMED: "돌려볼 수 있음 (정적 확인)",
            StepStatus.CONDITIONAL: "조건부",
            StepStatus.UNKNOWN: "미확인",
            StepStatus.UNSUPPORTED: "미지원",
        }[self]


@dataclass(frozen=True, slots=True)
class DeckSlot:
    """덱 한 칸 — 카드 하나와 그 매수, 그리고 **왜 넣었는가**."""

    card_id: int
    name: str
    copies: int
    role: CardRole
    reason: str
    """채택 이유. 측정된 신호를 적는다 — 평가나 감상을 적지 않는다."""
    theme: str | None = None
    """이 카드를 끌어온 테마 이름 (카드군 상수). 테마 밖이면 ``None``."""
    evidence: RoleEvidence = RoleEvidence.NONE
    """
    🔴 :attr:`role` 의 **근거**. 역할과 따로 적는다 (:class:`RoleEvidence`).

    기본값이 :attr:`RoleEvidence.NONE` 인 것은 의도다 — 근거를 적지 않고
    만든 칸은 "근거 없음" 으로 보여야 한다. 조용히 그럴듯한 근거가 붙으면
    안 된다.
    """


@dataclass(slots=True)
class DeckDraft:
    """덱 구성안. **초안이고, 검증은 별도다** (:class:`DeckValidation`)."""

    main: list[DeckSlot] = field(default_factory=list)
    extra: list[DeckSlot] = field(default_factory=list)
    requested_themes: list[str] = field(default_factory=list)
    resolved_themes: list[str] = field(default_factory=list)
    """실제로 카드군으로 해석된 테마. 요청과 다를 수 있다."""
    unresolved_themes: list[str] = field(default_factory=list)
    """🔴 카드군으로 해석되지 않은 테마. 조용히 버리지 않는다."""
    notes: list[str] = field(default_factory=list)

    @property
    def main_count(self) -> int:
        return sum(slot.copies for slot in self.main)

    @property
    def extra_count(self) -> int:
        return sum(slot.copies for slot in self.extra)

    def all_slots(self) -> list[DeckSlot]:
        return [*self.main, *self.extra]


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """규격 검사 하나의 결과와 **그 근거 문서**."""

    rule: str
    """사람이 읽는 규칙 이름. 예: "메인 덱 장수"."""
    outcome: ValidationOutcome
    detail: str
    source: str | None = None
    """근거 출처. 룰북 데이터에서 왔으면 그 규칙 ID, 없으면 ``None``."""


@dataclass(slots=True)
class DeckValidation:
    """덱 규격 검증 결과."""

    findings: list[RuleFinding] = field(default_factory=list)

    @property
    def violations(self) -> list[RuleFinding]:
        return [f for f in self.findings
                if f.outcome is ValidationOutcome.VIOLATED]

    @property
    def unverifiable(self) -> list[RuleFinding]:
        return [f for f in self.findings
                if f.outcome is ValidationOutcome.UNVERIFIABLE]

    @property
    def has_violation(self) -> bool:
        return bool(self.violations)

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return (f"위반 {len(self.violations)}건 · "
                f"검증 불가 {len(self.unverifiable)}건 · "
                f"전체 {len(self.findings)}건")


@dataclass(frozen=True, slots=True)
class PlanStep:
    """전개 한 걸음. **근거와 상태 없이 존재할 수 없다.**"""

    order: int
    card_id: int
    card_name: str
    action: str
    """사람이 Duel Simulator 에서 재현할 수 있는 한국어 서술."""
    requires: tuple[str, ...]
    """이 걸음에 필요한 조건. 판정하지 못한 조건도 **적는다**."""
    expected: str
    """기대하는 상태 변화."""
    basis: StepBasis
    status: StepStatus
    note: str = ""


@dataclass(slots=True)
class ComboPlan:
    """
    전개 계획.

    🔴 **중단을 숨기지 않는다.** 근거가 끊긴 자리에서 멈추고
    :attr:`stopped_reason` 에 왜 멈췄는지 적는다.
    """

    hand: list[int] = field(default_factory=list)
    board: list[int] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    stopped_reason: str | None = None
    unsupported: list[str] = field(default_factory=list)
    """엔진이 구조적으로 지원하지 않아 계획에 넣지 못한 것."""
    manual_checks: list[str] = field(default_factory=list)
    """🔴 사람이 직접 확인해야 하는 항목."""

    @property
    def confirmed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status is StepStatus.CONFIRMED]

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        counts: dict[str, int] = {}
        for step in self.steps:
            counts[step.status.describe_ko()] = (
                counts.get(step.status.describe_ko(), 0) + 1)
        parts = " · ".join(f"{k} {v}" for k, v in counts.items())
        return f"{len(self.steps)}걸음 ({parts})" if parts else "0걸음"


@dataclass(slots=True)
class PlanResult:
    """
    한 요청에 대한 최종 산출물.

    덱만 요청했으면 :attr:`plan` 이 ``None`` 이고, 전개만 요청했으면
    :attr:`draft` 가 ``None`` 일 수 있다 — **빈 것을 지어내지 않는다.**
    """

    draft: DeckDraft | None = None
    validation: DeckValidation | None = None
    plan: ComboPlan | None = None
    uncertainties: list[str] = field(default_factory=list)
    """불확실한 효과 · 미지원 조건 · 검증 불가 항목을 한곳에 모은 것."""
    manual_checks: list[str] = field(default_factory=list)
