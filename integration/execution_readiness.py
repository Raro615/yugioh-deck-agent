"""
**이 트리거를 해결할 수 있는가** — 그리고 못 하면 무엇이 없어서인가 (6-J).

6-I 가 실제 사건에서 후보를 모으는 데까지 왔다. 그 다음 칸은 "모은 후보를
실제로 해결한다" 이고, 이 모듈은 **그 칸이 왜 비어 있는지를 층별로 적는다.**

    analysis 가 읽은 해결 동작      ActionKind  (effect 어휘)
        ↓  RESOLUTION_OPERATIONS    ← 이 모듈의 표. 옮길 수 없으면 비운다
    engine 의 실행 연산             OperationKind
        ↓  EffectExecutor.SUPPORTED ← 실행기가 **스스로 세운** 집합
    해결 가능 / 불가 + 막는 층

🔴 **읽기만 한다. 아무것도 실행하지 않는다.** 이 모듈에는 판을 바꾸는 손도,
효과를 해결하는 손도 없다 — "해결할 수 있는가" 에 답하는 것과 "해결한다" 는
다른 일이고, 둘을 한 모듈에 두면 전자가 후자의 허가처럼 읽힌다 (6-J §3-7).

🔴 **이 모듈이 "해결 가능" 이라고 말해도 발동할 수는 없다.**
그 앞에 **발동 절차**가 있고, 몬스터 효과에는 그 층이 없다. 실측
(``ActionValidator.validate``):

    activate_effect (패의 몬스터 유발 효과)
        → UNKNOWN / RULE_NOT_IMPLEMENTED
        → missing_rule = "monster-activation-timing
                          (기동 · 유발 · 플립 · 유발즉시 분류가 없다)"

그래서 이 모듈의 ``is_resolvable`` 은 **"해결 단계만 보면 막는 것이 없다"**
는 뜻이고 그 이상이 아니다. 이름에 ``resolution`` 이 들어 있는 것이 그
경계다 (``is_executable`` 이라고 부르면 거짓이 된다).

왜 ``engine`` 안에 둘 수 없는가
-------------------------------
``ActionKind`` 는 ``analysis`` 의 어휘이고 ``engine`` 은 그것을 **쓰지
않는다** (``tests/engine/test_phase2_contracts.py`` 의 ``test_contract_e`` 가
AST 로 고정한다 — ADR-001). 두 어휘를 잇는 표는 두 층 위에 있어야 하고,
그 자리가 6-I 가 만든 이 패키지다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import ActionKind, CostKind
from engine.effect.executor import SUPPORTED
from engine.effect.operation import OperationKind
from engine.ids import EffectRef
from integration.trigger_registry import compiled_triggers


#: **``analysis`` 의 해결 동작을 ``engine`` 의 실행 연산으로.**
#:
#: 🔴 **옮길 수 있는 것만 적는다.** 여기 없는 ``ActionKind`` 는 "지원하지
#: 않는다" 가 아니라 **"이 표가 답을 모른다"** 이고, 그 둘을 섞지 않으려고
#: 빠진 것을 빠진 대로 둔다 (:data:`UNMAPPED_ACTIONS` 가 그 목록을 센다).
#:
#: 짝이 **한눈에 자명하지 않은 셋**에만 근거를 적는다.
RESOLUTION_OPERATIONS: dict[ActionKind, OperationKind] = {
    ActionKind.DRAW: OperationKind.DRAW,
    ActionKind.DESTROY: OperationKind.DESTROY,
    ActionKind.DISCARD: OperationKind.DISCARD,
    ActionKind.BANISH: OperationKind.BANISH,
    ActionKind.RELEASE: OperationKind.RELEASE,
    ActionKind.SPECIAL_SUMMON: OperationKind.SPECIAL_SUMMON,
    #: 이름이 다르고 뜻이 같다 — ``analysis`` 는 **목적지**로 부르고
    #: ``engine`` 은 **되돌린다**로 부른다.
    ActionKind.TO_HAND: OperationKind.RETURN_TO_HAND,
    ActionKind.TO_DECK: OperationKind.RETURN_TO_DECK,
    ActionKind.TO_GRAVE: OperationKind.SEND_TO_GRAVE,
    #: 🔴 **데미지와 회복이 같은 연산**이다. ``engine`` 은 라이프 변화 하나로
    #: 적고 부호로 방향을 말한다 (``LifeChangeOperation.delta``). 두 어휘를
    #: 하나로 합치는 것이 아니라, **engine 이 이미 하나로 적고 있다.**
    ActionKind.DAMAGE: OperationKind.CHANGE_LIFE,
    ActionKind.RECOVER: OperationKind.CHANGE_LIFE,
}

#: 표에 **없는** 해결 동작들. 실측(6-J)으로 적는다 — 이 중 어느 것도
#: ``engine`` 에 대응하는 연산이 없다.
#:
#: ``NORMAL_SUMMON`` 은 특히 **연산이 아니다** — 일반 소환은 효과 해결 중에
#: 수행되는 일이 아니라 플레이어가 고르는 행위다 (ADR-001). 그래서
#: ``OperationKind`` 에 자리가 없는 것이 옳다.
UNMAPPED_ACTIONS: frozenset[ActionKind] = frozenset(
    kind for kind in ActionKind if kind not in RESOLUTION_OPERATIONS
)


class ExecutionBlocker(str, Enum):
    """
    해결을 막는 **층**. 하나의 효과가 여럿을 가질 수 있다.

    🔴 **왜 새 열거형인가** (6-J §6 의 "무조건 추가하지 않는다" 에 대한 답).
    6-I 의 :class:`~engine.trigger_observation.ObservationStage` 는 *"후보가
    어디까지 갔는가"* 를 적고, 이것은 *"무엇이 없어서 못 가는가"* 를 적는다.
    전자는 사다리(한 값)이고 후자는 **집합**이다 — 한 효과가 정의도 없고
    연산도 못 옮기는 것은 두 사실이며, 사다리로는 그 둘을 함께 말할 수 없다.
    """

    OPERATION_UNREADABLE = "operation_unreadable"
    """``analysis`` 가 해결 동작을 **하나도 읽지 못했다.** 추측하지 않는다."""
    OPERATION_UNTRANSLATABLE = "operation_untranslatable"
    """읽었지만 :data:`RESOLUTION_OPERATIONS` 에 **짝이 없다**."""
    OPERATION_UNSUPPORTED = "operation_unsupported"
    """옮겼지만 :data:`~engine.effect.executor.SUPPORTED` 밖이다."""
    COST_UNKNOWN = "cost_unknown"
    """
    비용을 **판정할 수 없다** (``CostKind.UNKNOWN``).

    비용이 **있는** 것과 다르다 — 있는 비용은 치를 수 있는지 물을 수 있고,
    모르는 비용은 물을 수조차 없다. 비용을 치른 뒤 발동이 깨지면 되돌릴
    방법이 없으므로 (ADR-008) 모르는 비용은 해결에 들어가지 않는다.
    """
    COST_UNPAYABLE = "cost_unpayable"
    """비용이 있고, 그것을 치르는 계층이 아직 없다."""
    DEFINITION_MISSING = "definition_missing"
    """``EffectDefinition`` 이 등록되지 않았다 (ADR-006 — 손으로 등록한다)."""
    IMPLEMENTATION_MISSING = "implementation_missing"
    """정의는 있는데 실행 구현이 등록되지 않았다. **등록은 허가가 아니다.**"""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class ResolutionReadiness:
    """
    효과 하나의 **해결 단계** 준비도. 발동 절차는 보지 않는다 (모듈 머리말).
    """

    effect_ref: EffectRef
    operations: tuple[OperationKind, ...] = ()
    """옮길 수 있었던 연산들. 순서는 ``analysis`` 가 읽은 순서 그대로다."""
    unreadable_actions: tuple[str, ...] = ()
    """표에 짝이 없던 ``ActionKind`` 의 값들."""
    blockers: frozenset[ExecutionBlocker] = frozenset()

    @property
    def is_resolvable(self) -> bool:
        """
        **해결 단계만 보면** 막는 것이 없는가.

        🔴 "발동할 수 있다" 가 **아니다.** 발동 절차는 이 모듈 밖이고,
        몬스터 효과에는 그 층이 없다 (모듈 머리말의 실측).
        """
        return not self.blockers

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        if self.is_resolvable:
            return (
                f"{self.effect_ref} 해결 단계 준비됨 "
                f"({'·'.join(o.value for o in self.operations)})"
            )
        return (
            f"{self.effect_ref} 막힘: "
            f"{'·'.join(sorted(b.value for b in self.blockers))}"
        )

    def to_dict(self) -> dict:
        return {
            "effect_ref": str(self.effect_ref),
            "operations": [o.value for o in self.operations],
            "unreadable_actions": list(self.unreadable_actions),
            "blockers": sorted(b.value for b in self.blockers),
            "is_resolvable": self.is_resolvable,
        }


def operation_blockers(
    actions, *, supported: "frozenset[OperationKind]" = SUPPORTED
) -> "tuple[tuple[OperationKind, ...], tuple[str, ...], set[ExecutionBlocker]]":
    """
    해결 동작들을 **연산 · 못 옮긴 것 · 막는 것** 셋으로 가른다.

    🔴 **``supported`` 를 인자로 받는다.** 기본값이 실행기의 집합이지만,
    그 집합이 **좁아지는 경우**를 시험할 수 있어야 하기 때문이다.

    왜 그래야 했는가 — 변이 테스트가 잡았다. "지원 밖 연산을 통과시킨다" 는
    변이가 **살아남았다**: 지금 데이터에서 옮겨진 연산이 전부 지원되므로
    (``test_04`` 가 0건을 센다) 그 분기가 **도달하지 않는다.** 즉 지금
    데이터로는 그 보호가 있는지 없는지 알 수 없었다. 집합을 주입할 수 있게
    하자 ``test_20`` 이 그것을 직접 겨눌 수 있게 되었다.

    ``definitions`` · ``implementations`` 를 주입받는 것과 **같은 규율**이다 —
    이 함수가 의지하는 것을 숨기지 않는다.
    """
    operations: list[OperationKind] = []
    unreadable: list[str] = []
    blockers: set[ExecutionBlocker] = set()

    if not actions:
        blockers.add(ExecutionBlocker.OPERATION_UNREADABLE)
    for action in actions:
        operation = RESOLUTION_OPERATIONS.get(action.kind)
        if operation is None:
            blockers.add(ExecutionBlocker.OPERATION_UNTRANSLATABLE)
            unreadable.append(action.kind.value)
            continue
        if operation not in supported:
            blockers.add(ExecutionBlocker.OPERATION_UNSUPPORTED)
        operations.append(operation)
    return tuple(operations), tuple(unreadable), blockers


def _cost_blockers(effect) -> set[ExecutionBlocker]:
    """비용 쪽 막는 것. **모르는 비용과 있는 비용을 가른다.**"""
    out: set[ExecutionBlocker] = set()
    for cost in effect.costs:
        if cost.kind is CostKind.UNKNOWN:
            out.add(ExecutionBlocker.COST_UNKNOWN)
        elif cost.kind is not CostKind.NONE:
            out.add(ExecutionBlocker.COST_UNPAYABLE)
    return out


def readiness_for(
    repository,
    card_id: int,
    *,
    analyzer: EffectAnalyzer | None = None,
    definitions=None,
    implementations=None,
) -> tuple[ResolutionReadiness, ...]:
    """
    그 카드의 **등록된 TRIGGER 마다** 해결 준비도 하나.

    ``definitions`` · ``implementations`` 를 주지 않으면 그 두 막는 것은
    **묻지 않는다** — 조회할 목록이 없는 것은 "없다" 가 아니다 (6-I 의
    ``TriggerObserver`` 와 같은 규율).

    🔴 ``ordinal`` 은 :func:`~integration.trigger_registry.compiled_triggers`
    가 찾아 둔 자리를 그대로 쓴다. 여기서 다시 세지 않는다 — 두 곳에서 세면
    두 답이 갈라진다 (6-I §1.1).
    """
    analyzer = analyzer or EffectAnalyzer(repository)
    card = repository.get(card_id)
    if card is None or card.script is None:
        return ()
    found = compiled_triggers(repository, card_id, analyzer=analyzer)
    if not found.compilations:
        return ()

    place = {id(spec): index for index, spec in enumerate(card.script.effects)}
    by_ordinal = {
        place[id(effect.raw)]: effect
        for effect in analyzer.analyze(card).effects
        if id(effect.raw) in place
    }

    out: list[ResolutionReadiness] = []
    for compilation in found.compilations:
        if not compilation.is_registered:
            continue
        ref = compilation.spec.effect_ref
        effect = by_ordinal.get(ref.ordinal)
        if effect is None:  # pragma: no cover - compiled_triggers 가 보증한다
            continue

        operations, unreadable, blockers = operation_blockers(effect.actions)
        blockers |= _cost_blockers(effect)

        if definitions is not None:
            if definitions.definition_for(ref) is None:
                blockers.add(ExecutionBlocker.DEFINITION_MISSING)
            elif implementations is not None and not implementations.has_implementation(
                ref
            ):
                blockers.add(ExecutionBlocker.IMPLEMENTATION_MISSING)

        out.append(
            ResolutionReadiness(
                effect_ref=ref,
                operations=operations,
                unreadable_actions=unreadable,
                blockers=frozenset(blockers),
            )
        )
    return tuple(out)


__all__ = [
    "RESOLUTION_OPERATIONS",
    "UNMAPPED_ACTIONS",
    "ExecutionBlocker",
    "ResolutionReadiness",
    "operation_blockers",
    "readiness_for",
]
