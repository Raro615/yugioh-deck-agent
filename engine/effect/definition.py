"""
EffectDefinition — "이 효과가 무엇을 요구하고 무엇을 하는가".

**불변**이고, 판을 읽지도 바꾸지도 않는다. 청사진이다.

    EffectDefinition
      ├ effect_ref        어느 효과인가 (card_id, ordinal)
      ├ activation        발동 조건        engine.condition
      ├ cost              비용             engine.cost
      ├ targets           대상 규칙 (이름별)  engine.effect.target
      ├ operations        무엇을 하는가    engine.effect.operation
      └ provenance        어디서 왔는가

하는 일이 어느 대상을 쓰는지 말한다
------------------------------------
대상 규칙과 하는 일을 따로 두면 "대상으로 지정한 몬스터 1장을 파괴한다" 를
표현할 수 없다. 그래서 대상에 **이름**을 붙이고 일이 그 이름을 가리킨다.

    targets    = (TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(...)),)
    operations = (CardOperation.destroy(PRIMARY_TARGET),)

이름이 정의에 없으면 생성 단계에서 거부한다 — 그 일은 존재하지 않는 대상을
가리키고 있으므로 해결할 수 없다.

**실제로 골라진 카드는 여기 없다.** 정의는 "무엇을 대상으로 하는가" 이고,
"이번에 무엇이 골라졌는가" 는 :class:`~engine.effect.resolution.
ResolutionContext` 다. 정의에 ``InstanceId`` 를 박으면 그 정의는 한 판에서
한 번밖에 쓸 수 없다.

analysis.EffectSpec 과 다르다
-----------------------------
``core.card_model.EffectSpec`` 은 Lua 효과 블록을 **읽은 기록**이다 — 가변
dataclass 이고 ``index`` 가 Lua 변수명(``"e1"``)이며, 한 카드 안에서 중복된다
(실측 4,884장). 그것은 실행 identity 가 될 수 없다.

여기의 정의는 **실행 계약**이다. 불변이고, identity 가
:class:`~engine.ids.EffectRef` 이며, 조건 · 비용 · 대상 · 일을 실제 엔진
타입으로 들고 있다.

``analysis.EffectSpec`` → ``EffectDefinition`` 컴파일러는 **만들지 않았다.**
그 경계를 넘을 때 ``TEXT_DERIVED`` 차단을 다시 확인해야 한다
(``docs/phase2d1-effect-model.md``).

검증된 의미 ≠ 실행 가능
-----------------------
:class:`EffectProvenance` 가 "어디서 왔는가" 를, :func:`execution_availability`
가 "지금 실행할 수 있는가" 를 답한다. **둘은 다른 질문이다** (ADR-006).
공식 Lua 에서 나온 효과라도 구현이 등록되어 있지 않으면 실행할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from engine.condition import Condition
from engine.cost import CostGroup
from engine.effect.operation import COUNTING_KINDS, Operation
from engine.effect.target import SELF_TARGET, CountKind, TargetBinding, TargetRef
from engine.effect.target import SelectionCount
from engine.execution import (
    DeclarationBinding,
    NumericTest,
    OperationRequirement,
    ValueRef,
)
from engine.ids import EffectRef
from engine.vocabulary import ActivationKind


class EffectSource(str, Enum):
    """
    이 효과 정의가 **어디서 왔는가.**

    ``core.provenance.AnalysisStatus`` 와 나란한 개념이지만 같은 것이 아니다.
    그쪽은 카드 데이터의 성질이고, 이쪽은 **엔진이 들고 있는 이 정의**의
    성질이다. 사람이 손으로 쓴 구현은 카드 데이터에 없는 출처다.
    """

    OFFICIAL_LUA = "official_lua"
    """공식 카드 스크립트에서 구조화했다."""
    OFFICIAL_TEXT = "official_text"
    """
    공식 텍스트에서 유추했다 (``AnalysisStatus.TEXT_DERIVED``).
    **실행할 수 없다** (ADR-004).
    """
    HAND_WRITTEN = "hand_written"
    """사람이 작성했다. 검증 여부는 :attr:`EffectProvenance.verified` 가 따로 말한다."""
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


#: 실행 근거로 **절대 쓸 수 없는** 출처. ADR-004.
FORBIDDEN_SOURCES: frozenset[EffectSource] = frozenset({EffectSource.OFFICIAL_TEXT})


@dataclass(frozen=True, slots=True)
class EffectProvenance:
    """
    효과 정의의 출처 기록. **불변**이다.

    :attr:`verified` 는 "의미가 공식 근거에서 왔는가" 이지 "실행할 수 있는가"
    가 아니다. 둘을 한 값으로 합치면 ADR-006 이 무너진다.
    """

    source: EffectSource = EffectSource.UNKNOWN
    verified: bool = False
    """의미가 공식 근거(스크립트 · 텍스트 · 재정)에서 확인되었는가."""
    note: str = ""

    @property
    def is_forbidden(self) -> bool:
        """출처만으로 실행이 금지되는가. ``TEXT_DERIVED`` 가 여기다."""
        return self.source in FORBIDDEN_SOURCES

    @classmethod
    def official_lua(cls, note: str = "") -> "EffectProvenance":
        return cls(EffectSource.OFFICIAL_LUA, verified=True, note=note)

    @classmethod
    def text_derived(cls, note: str = "") -> "EffectProvenance":
        """
        공식 텍스트에서 유추했다. ``verified`` 가 참이어도 **실행은 금지**다 —
        텍스트가 실행 의미를 정하지 못하기 때문이다 (ADR-004).
        """
        return cls(EffectSource.OFFICIAL_TEXT, verified=True, note=note)

    @classmethod
    def hand_written(cls, verified: bool = False, note: str = "") -> "EffectProvenance":
        return cls(EffectSource.HAND_WRITTEN, verified=verified, note=note)

    def canonical_state(self) -> tuple:
        return (self.source.value, self.verified, self.note)

    def to_dict(self) -> dict:
        return {"source": self.source.value, "verified": self.verified, "note": self.note}

    def describe_ko(self) -> str:
        mark = "검증됨" if self.verified else "미검증"
        return f"{self.source.value}({mark})"


def _counts_of(operation) -> tuple:
    """
    그 조작이 들고 있는 :class:`~engine.effect.target.SelectionCount` 들.

    ``isinstance`` 사슬을 만들지 않으려고 **값이 있는지**만 본다. 새 조작이
    수를 갖게 되면 이름만 ``count`` 로 맞추면 여기 걸린다.
    """
    value = getattr(operation, "count", None)
    if hasattr(value, "kind") and hasattr(value, "resolve"):
        return (value,)
    return ()


class EffectDefinitionError(ValueError):
    """정의의 **모양**이 틀렸다. 규칙 위반이 아니다."""


@dataclass(frozen=True, slots=True)
class OperationGuard:
    """
    **이 조작은 이 수가 이러할 때만 한다** (Phase 2-AG · STRUCTURAL-91).

    실제 카드가 그렇게 적혀 있다.

    ::

        local ct=Duel.Destroy(g,REASON_EFFECT)
        if ct>0 then <다음 일> end            -- 66곳
        if ct==0 then return end              -- 27곳

    조건이 **거짓이면 그 일을 건너뛴다.** 효과는 정상적으로 해결되고,
    건너뛴 것은 실패가 아니다 (``OperationOutcome.NOT_APPLIED``).

    조건을 **판정할 수 없으면 건너뛰지 않는다.** 효과 전체를 거절한다 —
    건너뛰는 것도 결정이고, 모르는 채로 결정하면 그 결정을 엔진이 지어낸
    것이 된다.

    ``tests`` 가 여럿이면 **전부** 만족해야 한다. 불 대수를 새로 만들지
    않은 이유다 — "정확히 N" 은 ``at_least(N)`` 과 ``at_most(N)`` 을 함께
    걸면 되고, 실제 카드가 요구하는 것은 거기까지다.

    Phase 2-AE 의 :class:`~engine.execution.OperationRequirement` 와
    **다른 것**이다.

    ==========================  ==========================================
    ``OperationRequirement``     앞이 **규칙대로 되었는가** — 아니면 거절
    ``OperationGuard``           앞의 **수가 조건을 만족하는가** — 아니면 건너뜀
    ==========================  ==========================================

    2-AE 가 성패를 수로 읽는 길을 막아 둔 것은 지금도 유효하다. 여기서
    수를 읽는 것은 **수를 수로 읽는 것**이고, 견주는 방법을 명시적으로
    적는다.
    """

    operation_index: int
    value: SelectionCount
    tests: tuple[NumericTest, ...] = ()

    def __post_init__(self) -> None:
        if self.operation_index < 0:
            raise ValueError(f"조작 번호는 0 이상입니다: {self.operation_index}")
        if not isinstance(self.tests, tuple):
            raise TypeError("tests 는 tuple 이어야 합니다 — 정의는 불변입니다.")
        if not self.tests:
            raise ValueError(
                "견줄 조건이 하나도 없습니다. 조건 없는 조건문은 조건이 "
                "아니라 언제나 참이고, 그것을 적을 이유가 없습니다."
            )

    def canonical_state(self) -> tuple:
        return (
            self.operation_index,
            self.value.canonical_state(),
            tuple(test.canonical_state() for test in self.tests),
        )

    def to_dict(self) -> dict:
        return {
            "operation_index": self.operation_index,
            "value": self.value.to_dict(),
            "tests": [test.to_dict() for test in self.tests],
        }

    def describe_ko(self) -> str:
        what = " 그리고 ".join(test.describe_ko() for test in self.tests)
        # 수의 설명은 "…만큼" 으로 끝나는데, 조건에서는 그 수 자체를
        # 가리키므로 꼬리를 뗀다.
        measured = self.value.describe_ko().removesuffix(" 만큼")
        return (
            f"{self.operation_index}번 조작은 {measured} 가 {what} 일 때만 한다"
        )


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """
    효과 하나의 불변 정의.

    ``effect_ref.card_id`` 와 :attr:`source_card_id` 는 **반드시 같다.**
    다르면 그 정의는 어느 카드의 효과인지 스스로 모순이므로 거부한다.
    """

    effect_ref: EffectRef
    source_card_id: int
    operations: tuple[Operation, ...] = ()
    activation: Condition | None = None
    """발동 조건. ``None`` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는 뜻**이다."""
    cost: CostGroup = field(default_factory=CostGroup)
    targets: tuple[TargetBinding, ...] = ()
    """이름별 대상 규칙. 하는 일이 이 이름을 가리킨다."""
    declarations: tuple[DeclarationBinding, ...] = ()
    """
    이름별 **수 선언** 규칙 (Phase 2-AD).

    ``targets`` 와 **다른 이름 공간**이다 — 저쪽은 고른 카드이고 이쪽은
    선언한 수다. 하나로 합치면 "2장" 과 "2" 가 같은 이름표를 달게 된다.
    """
    requirements: tuple[OperationRequirement, ...] = ()
    """
    **어느 조작이 어느 조작의 성패에 기대는가** (Phase 2-AE).

    조작 자체에 붙이지 않은 이유가 있다. 이것은 조작이 *하는 일*이 아니라
    조작들 **사이의 순서 관계**이고, 정의가 그 순서를 들고 있기 때문이다.
    조작에 붙이면 같은 조작을 다른 정의에서 다시 쓸 때 남의 번호를 들고
    다니게 된다.
    """
    guards: tuple[OperationGuard, ...] = ()
    """
    **어느 조작이 어떤 수를 보고 실행 여부를 정하는가** (Phase 2-AG).

    ``requirements`` 와 나란히 있고 하는 일이 다르다 — 저쪽은 못 하면
    거절이고 이쪽은 안 하면 건너뜀이다.
    """
    activation_kind: ActivationKind | None = None
    """
    이 효과가 **어떻게 발동하는가** — 기동 · 유발 · 플립 · 유발즉시
    (Phase 6-K, :class:`~engine.vocabulary.ActivationKind`).

    ``activation`` 과 **다른 질문이다.** 저쪽은 "발동 조건이 참인가" 이고
    이쪽은 "이 효과가 어느 절차로 발동하는가" 다. 하나로 합치면 "자신
    메인 페이즈에 선언한다" 와 "덱이 2장 이상이다" 가 같은 칸에 들어간다.

    ``None`` 은 **"분류가 없다" 가 아니라 "적지 않았다"** 다 —
    ``activation`` 과 같은 태도이고, 적지 않은 것을 어느 분류로도 읽지
    않는다. 등재된 마법 · 함정 16개가 ``None`` 인 이유는 그 발동이 카드
    종류로 이미 판정되기 때문이다 (``EFFECT_TYPE_ACTIVATE`` 를 이 축에
    넣지 않은 이유와 같다).

    **손으로 적는다** (ADR-006). ``EffectSpec.effect_types`` 에서 자동으로
    옮기지 않는다 — 그 변환은 12,702장을 한꺼번에 분류로 바꾸는 일이고,
    적는 것과 **실행을 허가하는 것**은 다른 결정이다.
    """
    activation_waits_for_event: "bool | None" = None
    """
    이 **카드 발동**이 특정 사건을 기다리는가 (Phase 6-Q).

    ``activation_kind`` 와 **다른 축이다.** 저쪽은 몬스터 효과의 분류
    (기동 · 유발 · 플립 · 유발즉시)이고, 이쪽은 마법 · 함정의 **카드
    발동**(``EFFECT_TYPE_ACTIVATE``)이 사건을 기다리는지다. 한 축에 넣지
    않은 이유는 :class:`~engine.vocabulary.ActivationKind` 가 스스로
    적어 둔 그대로다 — *"마법 · 함정의 발동도 여기 없다"*.

    세 값을 **구분해서 쓴다** (``ActivationTiming.set_this_turn`` 과 같은
    모양이다 — 새 열거형을 만들지 않았다).

    ==========  ==================================================
    ``None``    **적지 않았다.** "사건을 기다리지 않는다" 가 아니다
    ``True``    특정 사건이 와야 발동한다. 엔진은 그 사건을 만들어
                내지 못하므로 **범위 밖**이다
    ``False``   사건을 기다리지 않는다. 세트 · 세트한 턴 · 타이밍 ·
                우선권 · 카드별 조건은 **그대로 다 본다**
    ==========  ==================================================

    🔴 ``False`` 는 **발동 허가가 아니다.** "이 카드의 발동 시점을 판정할
    수 있다" 는 뜻이고, 판정 자체는 뒤의 관문들이 한다
    (:func:`~engine.action_validation.validate` ·
    :class:`~engine.activation_timing.ActivationTimingChecker` ·
    :meth:`~engine.activation.EffectActivator.can_activate`).

    왜 Lua 의 태그 이름을 그대로 싣지 않는가
    ----------------------------------------
    🔴 공식 스크립트가 "특정 사건을 요구하지 않는다" 를 적는 **내부 태그**는
    공식 규칙의 개념이 **아니다** — 이 저장소의 공식 자료 전체에서 그 영어
    표현은 **0회** 나오고, 공식 스펠 스피드와도 **끝에서 뒤집힌다** (필드
    마법은 312/312 = 100%, 카운터 함정은 220블록 중 3건 = 1.4%). 측정과 경고는
    ``core.card_model.EffectSpec.code`` 에 있다 (Phase 3-F-25).

    🔴 **그래서 이 모듈은 그 태그의 이름을 아예 쓰지 않는다** — 쓰면 Lua 의
    어휘가 정의 계층의 어휘가 되고, 그 경계를
    ``tests/test_trigger_condition_separation_audit.py`` 가 지킨다. 옮긴 것은
    **그 태그가 답하는 질문 하나**다 — "이 발동이 사건을 기다리는가".
    스펠 스피드는 여전히 카드 종류에서 나온다
    (``engine/activation_timing.py``).

    **손으로 적는다** (ADR-006). ``EffectSpec.code`` 에서 자동으로 옮기지
    않는다 — 그 변환은 카드 발동 블록 4,297개를 한꺼번에 판정으로 바꾸는
    일이고, 적는 것과 **발동을 판정하는 것**은 다른 결정이다.
    """
    provenance: EffectProvenance = field(default_factory=EffectProvenance)

    def __post_init__(self) -> None:
        if self.activation_kind is not None and not isinstance(
            self.activation_kind, ActivationKind
        ):
            raise EffectDefinitionError(
                "activation_kind 는 ActivationKind 이거나 None 입니다: "
                f"{self.activation_kind!r}. 문자열을 그대로 넣으면 오타가 "
                "조용히 '분류를 적지 않았다' 로 읽힙니다."
            )
        if self.effect_ref.card_id != self.source_card_id:
            raise EffectDefinitionError(
                f"effect_ref 의 카드({self.effect_ref.card_id})가 "
                f"source_card_id({self.source_card_id})와 다릅니다. "
                "한 효과는 한 카드의 것입니다."
            )
        if not isinstance(self.operations, tuple):
            raise TypeError("operations 는 tuple 이어야 합니다 — 정의는 불변입니다.")
        if not isinstance(self.targets, tuple):
            raise TypeError("targets 는 tuple 이어야 합니다 — 정의는 불변입니다.")
        if not isinstance(self.declarations, tuple):
            raise TypeError(
                "declarations 는 tuple 이어야 합니다 — 정의는 불변입니다."
            )
        if not isinstance(self.requirements, tuple):
            raise TypeError(
                "requirements 는 tuple 이어야 합니다 — 정의는 불변입니다."
            )
        self._check_target_links()
        self._check_value_links()
        self._check_requirements()
        self._check_guards()

    def _check_target_links(self) -> None:
        """
        이름과 일이 실제로 이어지는지 본다.

        세 가지를 거부한다.

        1. 같은 이름을 두 번 선언했다 — 어느 규칙인지 정해지지 않는다.
        2. 일이 **없는 이름**을 가리킨다 — 해결할 수 없다.
        3. 선언한 대상을 **아무 일도 쓰지 않는다** — 고르게 해 놓고 쓰지
           않는 정의다. 단, 하는 일을 아직 적지 않았으면(``operations`` 가
           비었으면) 넘어간다. 그것은 "미완성" 이지 "모순" 이 아니다.

        🔴 :data:`~engine.effect.target.SELF_TARGET` 은 **선언 없이도
        이어진다** (Phase 6-L). 그 이름이 가리키는 카드는 정의가 아니라
        문맥이 말하고 (``ResolutionContext.source``), 고를 것이 없으므로
        선언할 규칙도 없다. ``TargetBinding`` 이 그 이름을 거부하므로
        ``declared`` 에 들어올 길도 없다 — 즉 2번 검사에서만 예외이고,
        1번 · 3번은 애초에 닿지 않는다.
        """
        declared: set[TargetRef] = set()
        for binding in self.targets:
            if binding.ref in declared:
                raise EffectDefinitionError(
                    f"대상 이름 {binding.ref} 가 두 번 선언되었습니다."
                )
            declared.add(binding.ref)

        used: set[TargetRef] = set()
        for operation in self.operations:
            for ref in operation.target_refs:
                if ref == SELF_TARGET:
                    # **자기 참조는 선언하지 않는다** (Phase 6-L). 가리키는
                    # 카드를 정의가 모르기 때문이다 — 같은 정의가 여러 판에서
                    # 쓰이고, 그때마다 다른 인스턴스가 발동한다.
                    continue
                if ref not in declared:
                    raise EffectDefinitionError(
                        f"{operation.kind.value} 가 선언되지 않은 대상 {ref} 를 "
                        f"가리킵니다. 선언된 것: "
                        f"{sorted(r.name for r in declared) or '없음'}"
                    )
                used.add(ref)

        if self.operations:
            unused = declared - used
            if unused:
                raise EffectDefinitionError(
                    f"선언한 대상 {sorted(r.name for r in unused)} 를 아무 일도 "
                    "쓰지 않습니다. 고르게 해 놓고 쓰지 않는 정의입니다."
                )

    def _check_value_links(self) -> None:
        """
        실행 중에 생기는 **수**의 이름이 실제로 이어지는지 본다 (Phase 2-AD).

        네 가지를 거부한다.

        1. 같은 이름을 두 번 선언했다.
        2. 없는 이름의 수를 쓴다.
        3. 선언해 놓고 아무 일도 쓰지 않는다 — 사람에게 수를 묻고 버리는
           정의다.
        4. **뒤의 조작을 가리킨다.** 아직 일어나지 않은 일의 결과를 읽을
           수는 없다. 자기 자신을 가리키는 것도 같은 이유로 막는다.

        네 번째가 이 검사의 핵심이다. "바로 앞" 같은 암묵적 지시를 두지
        않는 대신, 번호가 **앞**을 가리키는지를 정의를 만들 때 못박는다.
        """
        declared: set[ValueRef] = set()
        for binding in self.declarations:
            if binding.ref in declared:
                raise EffectDefinitionError(
                    f"수 이름 {binding.ref} 가 두 번 선언되었습니다."
                )
            declared.add(binding.ref)

        used: set[ValueRef] = set()
        for index, operation in enumerate(self.operations):
            for count in self._counts_used_by(operation):
                if count.kind is CountKind.DECLARED:
                    if count.declared not in declared:
                        raise EffectDefinitionError(
                            f"{operation.kind.value} 가 선언되지 않은 수 "
                            f"{count.declared} 를 씁니다. 선언된 것: "
                            f"{sorted(r.name for r in declared) or '없음'}"
                        )
                    used.add(count.declared)
                elif count.kind is CountKind.FROM_RESULT:
                    self._check_result_ref(count.result, index)

        # **조건이 읽는 수도 쓰는 것이다** (Phase 2-AG). 빼먹으면
        # "묻고 버린다" 가 거짓으로 걸린다.
        for guard in self.guards:
            if guard.value.kind is CountKind.DECLARED:
                used.add(guard.value.declared)

        if self.operations:
            unused = declared - used
            if unused:
                raise EffectDefinitionError(
                    f"선언하게 한 수 {sorted(r.name for r in unused)} 를 아무 "
                    "일도 쓰지 않습니다. 묻고 버리는 정의입니다."
                )

    def _check_result_ref(self, ref, index: int) -> None:
        """
        앞선 일의 수를 가리키는 것이 **말이 되는가** (2-AD · 2-AH).

        둘을 본다.

        1. **앞선 일인가.** 아직 일어나지 않은 일에는 수가 없다. 이
           검사가 있어서 A→B, B→A 같은 고리는 **만들어질 수조차
           없다** — 고리를 푸는 장치를 따로 두지 않는 이유다.
        2. **그 일이 그 수를 내는가.** 라이프 증감에는 장수가 없다.
           실행해 봐야 아는 거짓말이 아니라 **적는 순간 아는 거짓말**
           이므로 여기서 막는다 (Phase 2-AH).
        """
        target = ref.operation_index
        if target >= index:
            raise EffectDefinitionError(
                f"{index}번 조작이 {target}번 조작의 결과를 가리킵니다. "
                "앞선 일만 읽을 수 있습니다 — 아직 일어나지 않은 일에는 "
                "결과가 없습니다."
            )
        kind = self.operations[target].kind
        if kind not in COUNTING_KINDS:
            raise EffectDefinitionError(
                f"{index}번 조작이 {target}번 조작({kind.value})의 "
                f"{ref.field.value} 를 읽습니다. 그 일은 장수를 내지 "
                "않습니다."
            )

    def _check_requirements(self) -> None:
        """
        성패에 기대는 순서가 실제로 성립하는지 본다 (Phase 2-AE).

        결과를 수로 읽을 때와 **같은 규칙**이다 — 가리켜지는 쪽이 반드시
        앞이어야 한다. 아직 일어나지 않은 일에는 성패가 없다.
        """
        for requirement in self.requirements:
            for index in (requirement.operation_index, requirement.after.operation_index):
                if index >= len(self.operations):
                    raise EffectDefinitionError(
                        f"{index}번 조작이 없습니다 "
                        f"({len(self.operations)}개뿐입니다)."
                    )
            if requirement.after.operation_index >= requirement.operation_index:
                raise EffectDefinitionError(
                    f"{requirement.operation_index}번 조작이 "
                    f"{requirement.after.operation_index}번 조작의 성패에 "
                    "기댑니다. 앞선 일만 읽을 수 있습니다 — 아직 일어나지 "
                    "않은 일에는 성패가 없습니다."
                )

    def requirements_for(self, index: int) -> tuple:
        """그 조작이 기대고 있는 앞선 일들. 선언 순서 그대로다."""
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.operation_index == index
        )

    def _check_guards(self) -> None:
        """
        조건이 **앞선 일만** 본다는 것을 정의를 만들 때 못박는다 (2-AG).

        수를 읽을 때와 성패를 읽을 때와 **같은 규칙**이다. 아직 일어나지
        않은 일의 수를 보고 실행 여부를 정할 수는 없다.
        """
        for guard in self.guards:
            if guard.operation_index >= len(self.operations):
                raise EffectDefinitionError(
                    f"{guard.operation_index}번 조작이 없습니다 "
                    f"({len(self.operations)}개뿐입니다)."
                )
            result = guard.value.result
            if result is None:
                continue
            self._check_result_ref(result, guard.operation_index)

    def guards_for(self, index: int) -> tuple:
        """그 조작에 걸린 조건들. 선언 순서 그대로다."""
        return tuple(
            guard for guard in self.guards if guard.operation_index == index
        )

    def _counts_used_by(self, operation) -> tuple:
        """
        그 일이 **실제로 묻게 되는** 수들.

        두 곳에서 온다. 일이 직접 들고 있는 매수(드로우)와, 일이 가리키는
        **대상 규칙**이 들고 있는 장수(무작위 선택)다. 뒤쪽을 빼먹으면
        "선언하게 해 놓고 안 쓴다" 가 거짓으로 걸린다.
        """
        found = list(_counts_of(operation))
        for ref in operation.target_refs:
            for binding in self.targets:
                if binding.ref != ref:
                    continue
                choice = getattr(binding.spec, "choice", None)
                count = getattr(choice, "count", None)
                if hasattr(count, "kind") and hasattr(count, "resolve"):
                    found.append(count)
        return tuple(found)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    @property
    def ordinal(self) -> int:
        """카드 안에서 몇 번째 효과인가. ``EffectSpec.index`` 가 아니다."""
        return self.effect_ref.ordinal

    @property
    def has_cost(self) -> bool:
        return not self.cost.is_free

    @property
    def requires_target(self) -> bool:
        """
        대상을 하나라도 선언했는가.

        🔴 **자기 참조는 여기 세지 않는다** (Phase 6-L). 자기 자신을 패로
        되돌리는 효과는 대상을 지정하지 않으므로 (「대상으로 하고」 가 공식
        텍스트에 없다) 이 값이 거짓이어야 하고, 그래서 ``target_bridge`` 도
        ``PlayerAction.targets`` 에 아무것도 요구하지 않는다.
        """
        return bool(self.targets)

    @property
    def references_self(self) -> bool:
        """
        하는 일 중 하나라도 **이 효과의 카드 자신**을 가리키는가 (Phase 6-L).

        :attr:`requires_target` 과 **다른 질문이다.** 저쪽은 "고를 것이
        있는가" 이고 이쪽은 "발동한 카드를 가리키는가" 다. 둘 다 참인
        효과도, 둘 다 거짓인 효과도 있다.
        """
        return any(
            SELF_TARGET in operation.target_refs for operation in self.operations
        )

    @property
    def target_refs(self) -> tuple[TargetRef, ...]:
        """선언된 대상 이름들. 선언 순서 그대로다."""
        return tuple(binding.ref for binding in self.targets)

    def target_spec(self, ref: TargetRef):
        """
        그 이름의 대상 규칙. 없으면 :class:`KeyError`.

        조용히 ``None`` 을 돌려주지 않는다 — 없는 이름을 묻는 것은 정의와
        해결이 어긋났다는 뜻이고, 그것은 감춰야 할 일이 아니다.

        🔴 :data:`~engine.effect.target.SELF_TARGET` 도 :class:`KeyError`
        다 (Phase 6-L), 그리고 **그것이 맞다** — 자기 참조에는 고르는
        규칙이 없다. 부르는 쪽이 그 이름을 먼저 갈라 본다
        (``EffectExecutor._target_spec_of``).
        """
        for binding in self.targets:
            if binding.ref == ref:
                return binding.spec
        raise KeyError(f"{ref} 는 이 정의에 선언되어 있지 않습니다.")

    @property
    def is_described(self) -> bool:
        """
        무엇을 하는지 하나라도 적혀 있는가.

        거짓이면 **효과가 없다는 뜻이 아니라** 아직 적지 않았다는 뜻이다.
        """
        return bool(self.operations)

    def canonical_state(self) -> tuple:
        return (
            (self.effect_ref.card_id, self.effect_ref.ordinal),
            self.source_card_id,
            tuple(op.canonical_state() for op in self.operations),
            self.activation.canonical_state() if self.activation is not None else None,
            self.cost.canonical_state(),
            tuple(b.canonical_state() for b in self.targets),
            tuple(b.canonical_state() for b in self.declarations),
            tuple(r.canonical_state() for r in self.requirements),
            tuple(g.canonical_state() for g in self.guards),
            self.activation_kind.value if self.activation_kind is not None else None,
            self.provenance.canonical_state(),
        )

    def to_dict(self) -> dict:
        data: dict = {
            "effect_ref": {
                "card_id": self.effect_ref.card_id,
                "ordinal": self.effect_ref.ordinal,
            },
            "source_card_id": self.source_card_id,
            "operations": [op.to_dict() for op in self.operations],
            "cost": self.cost.to_dict(),
            "targets": [b.to_dict() for b in self.targets],
            "provenance": self.provenance.to_dict(),
        }
        if self.activation is not None:
            data["activation"] = self.activation.to_dict()
        if self.activation_kind is not None:
            data["activation_kind"] = self.activation_kind.value
        return data

    def describe_ko(self) -> str:
        parts = [str(self.effect_ref)]
        if self.has_cost:
            parts.append(f"비용: {self.cost.describe_ko()}")
        if self.activation is not None:
            parts.append(f"조건: {self.activation.describe_ko()}")
        if self.requires_target:
            parts.append(
                "대상: " + ", ".join(b.describe_ko() for b in self.targets)
            )
        if self.operations:
            parts.append(
                "효과: " + ", ".join(op.describe_ko() for op in self.operations)
            )
        return " / ".join(parts)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 실행 가능성 — 출처와 다른 질문이다
# ======================================================================


class ExecutionAvailability(str, Enum):
    """
    **지금 이 엔진 빌드가** 이 효과를 실행할 수 있는가.

    카드 데이터에 저장하지 않는다 (ADR-006). 구현 등록 상태에 따라 달라지므로
    저장하면 반드시 낡는다.
    """

    EXECUTABLE = "executable"
    """검증된 의미 + 등록된 구현. **이때만 실행해도 된다.**"""
    NO_IMPLEMENTATION = "no_implementation"
    """의미는 검증되었으나 구현이 등록되어 있지 않다."""
    FORBIDDEN_SOURCE = "forbidden_source"
    """출처가 실행을 금지한다 (``TEXT_DERIVED``). 구현이 있어도 실행하지 않는다."""
    UNVERIFIED = "unverified"
    """의미가 공식 근거에서 확인되지 않았다."""
    UNKNOWN = "unknown"

    @property
    def permits_execution(self) -> bool:
        """
        실행해도 되는가. **``EXECUTABLE`` 일 때만 참이다.**

        ``if availability is not FORBIDDEN_SOURCE:`` 같은 코드로 나머지가
        허가로 새어 나가는 것을 막는다.
        """
        return self is ExecutionAvailability.EXECUTABLE


@runtime_checkable
class EffectImplementationLookup(Protocol):
    """
    ``EffectRef`` 로 구현을 찾을 수 있는가를 답하는 것.

    **레지스트리 자체는 이번 단계에서 만들지 않는다** (Phase 2-D-2).
    실행 가능성 판정이 무엇에 의존하는지만 계약으로 고정한다.
    """

    def has_implementation(self, effect_ref: EffectRef) -> bool:
        """이 효과의 실행 구현이 등록되어 있는가."""
        ...  # pragma: no cover - 프로토콜


class EmptyImplementationLookup:
    """
    구현이 **하나도 없는** 조회기. 지금 엔진의 실제 상태다.

    Phase 2-D-2 가 실제 레지스트리를 넣기 전까지, 어떤 효과도 실행 가능
    상태가 되지 않는다는 것을 이것이 보장한다.
    """

    __slots__ = ()

    def has_implementation(self, effect_ref: EffectRef) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return "<EmptyImplementationLookup>"


@runtime_checkable
class EffectDefinitionSource(Protocol):
    """
    ``EffectRef`` 로 **정의**를 찾을 수 있는 것.

    :class:`EffectImplementationLookup` 과 **다른 질문**이다.

    =============================  ====================================
    ``EffectDefinitionSource``      이 효과가 무엇을 하는지 적혀 있는가
    ``EffectImplementationLookup``  그것을 실행해도 되는가
    =============================  ====================================

    정의를 찾을 수 있다고 실행할 수 있는 것이 아니다 (ADR-006). 둘을 한
    인터페이스로 합치면 그 구분이 무너진다.
    """

    def definition_for(self, effect_ref: EffectRef) -> "EffectDefinition | None":
        """그 효과의 정의. **없으면 ``None``.**"""
        ...  # pragma: no cover - 프로토콜


class EffectDefinitionRegistry:
    """
    손으로 등록한 정의 목록.

    ``analysis`` → :class:`EffectDefinition` 컴파일러는 **아직 없다**
    (STRUCTURAL-7). 그 경계를 넘을 때 ``TEXT_DERIVED`` 차단을 다시 확인해야
    하므로, 그때까지 정의는 손으로 등록한다. 자동 생성이 아니라는 것이
    지금의 사실이고 이것이 그 사실을 정직하게 표현한다.

    **등록은 실행 허가가 아니다.** 실행에는 구현 등록
    (:class:`EffectImplementationLookup`) 이 따로 필요하고, 출처가
    ``TEXT_DERIVED`` 면 그마저도 소용없다.
    """

    __slots__ = ("_definitions",)

    def __init__(self, definitions: "tuple[EffectDefinition, ...] | None" = None):
        self._definitions: dict[EffectRef, EffectDefinition] = {}
        for definition in definitions or ():
            self.register(definition)

    def register(self, definition: "EffectDefinition") -> "EffectDefinitionRegistry":
        """
        정의를 등록한다. 같은 ``EffectRef`` 를 두 번 등록하면 거부한다 —
        조용히 덮어쓰면 어느 정의가 실행되는지 알 수 없게 된다.
        """
        if definition.effect_ref in self._definitions:
            raise EffectDefinitionError(
                f"{definition.effect_ref} 의 정의가 이미 등록되어 있습니다."
            )
        self._definitions[definition.effect_ref] = definition
        return self

    def definition_for(self, effect_ref: EffectRef) -> "EffectDefinition | None":
        return self._definitions.get(effect_ref)

    def definitions(self) -> "tuple[EffectDefinition, ...]":
        """
        등록된 정의 전부, ``EffectRef`` 순으로 (Phase 6-AB 보완4).

        🔴 **사본을 만들 수 있게 하려고 둔다.** 이 등록부는
        :meth:`register` 를 가진 **변경 가능한** 것이므로 탐색 사본과
        그대로 공유하면 한쪽의 등록이 다른 쪽에 보인다. 사본을 만드는
        자리(``engine.spell_activation.duel_components``)가 이 목록을 읽어
        **새 등록부**를 만든다.

        돌려주는 것은 불변 묶음이고, :class:`EffectDefinition` 자신은
        frozen 이므로 **정의 객체는 공유해도 안전하다** — 격리해야 하는
        것은 "무엇이 등록되어 있는가" 라는 목록이다.
        """
        return tuple(
            self._definitions[ref] for ref in sorted(self._definitions, key=str)
        )

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, effect_ref: object) -> bool:
        return effect_ref in self._definitions

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<EffectDefinitionRegistry n={len(self._definitions)}>"


def execution_availability(
    definition: EffectDefinition,
    lookup: EffectImplementationLookup | None = None,
) -> ExecutionAvailability:
    """
    이 효과를 지금 실행할 수 있는가.

    순서가 중요하다. **출처 금지가 가장 먼저**다 — 구현이 등록되어 있어도
    ``TEXT_DERIVED`` 는 실행하지 않는다 (ADR-004).

    ``lookup`` 을 주지 않으면 :class:`EmptyImplementationLookup` 을 쓴다.
    "아무것도 등록되어 있지 않다" 가 지금의 사실이므로 그것이 올바른 기본값이다.
    """
    provenance = definition.provenance
    if provenance.is_forbidden:
        return ExecutionAvailability.FORBIDDEN_SOURCE
    if not provenance.verified:
        return ExecutionAvailability.UNVERIFIED
    if provenance.source is EffectSource.UNKNOWN:
        return ExecutionAvailability.UNKNOWN
    resolved = lookup if lookup is not None else EmptyImplementationLookup()
    if not resolved.has_implementation(definition.effect_ref):
        return ExecutionAvailability.NO_IMPLEMENTATION
    return ExecutionAvailability.EXECUTABLE


def verified_activation_kind(
    definitions: "EffectDefinitionSource | None",
    effect_ref: "EffectRef | None",
    *,
    source_card_id: int | None,
) -> "ActivationKind | None":
    """
    **그 효과의 발동 분류** — 등록부에서 찾아 카드까지 맞춰 본 것만
    (Phase 6-AB 보완7).

    왜 이 함수가 있는가
    -------------------
    몬스터 효과의 스펠 스피드는 **효과 분류**가 정하고
    (:data:`~engine.activation_timing.KIND_SPEED`), 그 분류는 이미
    :attr:`EffectDefinition.activation_kind` 에 손으로 적혀 있다 (ADR-006).
    그런데 타이밍 관문은 관측(``GameStateView``)만 받으므로 등록부를 볼 수
    없었고, 그래서 **이미 확인된 사실을 모른다고 답하고 있었다** (보완7 §2 의
    실측: 어니스트 ①이 ``RULE_NOT_IMPLEMENTED``).

    이 함수가 그 **한 자리**다. 관문과 보고 계층이 각자 등록부를 뒤지면
    분류표가 두 벌이 되므로, 두 자리 모두 이것을 부른다
    (:meth:`~engine.duel.Duel._effect_kind` ·
    :class:`~engine.response.ResponseLoop`).

    무엇을 ``None`` 으로 돌려주는가 — **넷 다 "모른다" 다**
    ------------------------------------------------------
    ========================================  ==========================
    등록부가 없다                              판정할 근거가 없다
    ``effect_ref`` 가 없다                     어느 효과인지 모른다
    그 ``effect_ref`` 의 정의가 없다            적힌 것이 없다
    정의의 카드와 발동하려는 카드가 다르다       **남의 분류를 빌리지 않는다**
    ========================================  ==========================

    🔴 마지막 줄이 이 함수의 안전장치다. ``source`` 와 ``effect_ref`` 가
    어긋난 요청은 검증기가 ``EFFECT_REF_CARD_MISMATCH`` 로 따로 거절하지만,
    이 함수는 **그 거절을 기다리지 않고** 분류 자체를 주지 않는다 — 순서가
    바뀌어도 다른 카드의 분류가 새어 들어오지 않게.

    🔴 **분류를 안다는 것이 실행 지원이 아니다.** 돌려주는 것은 "이 효과가
    어느 절차로 발동하는가" 하나이고, 조건 · 비용 · 대상 · 구현 등록 ·
    출처 금지는 :func:`execution_availability` 와 발동기가 그대로 본다.
    """
    if definitions is None or effect_ref is None:
        return None
    definition = definitions.definition_for(effect_ref)
    if definition is None:
        return None
    if source_card_id is not None and definition.source_card_id != source_card_id:
        return None
    return definition.activation_kind


__all__ = [
    "EffectSource",
    "FORBIDDEN_SOURCES",
    "EffectProvenance",
    "EffectDefinitionError",
    "EffectDefinition",
    "ExecutionAvailability",
    "EffectDefinitionSource",
    "EffectDefinitionRegistry",
    "EffectImplementationLookup",
    "EmptyImplementationLookup",
    "execution_availability",
    "verified_activation_kind",
]
