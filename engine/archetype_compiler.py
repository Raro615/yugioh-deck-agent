"""
카드군 조건 컴파일러 — **이름을 조건으로** 옮기는 자리 (Phase 6-D).

    analysis 가 읽어 둔 이름       ["ORCUST", "WORLD_LEGACY"]
          ↓  compile_archetype_condition(names)
    엔진 조건                      IsSetCard((0x11b, 0xfe))
          ↓  CandidateSource(require=…)
    CandidateResolver              eligible / undecided / unchecked

🔴 **왜 ``CardConstraint`` 를 받지 않는가 — ADR-007**
-----------------------------------------------------
``engine`` 이 ``analysis`` 에서 가져오는 이름은 ``LimitScope`` **하나**이고,
``tests/engine/test_phase2_contracts.py`` 가 그것을 고정한다: *"이 목록이
늘어나면 분석 데이터가 실행 경로로 새어 들어오고 있다는 신호다."*

처음 구현은 이 모듈이 ``CardConstraint`` 를 ``TYPE_CHECKING`` 으로만
가져왔다. 런타임에는 아무것도 새지 않지만 **그 지뢰선이 발화했고, 그것이
옳았다.** 다리를 engine 안에 두면서 분석 타입을 받으면, 다음 사람이 같은
자리에 두 번째 타입을 들여올 명분이 생긴다.

그래서 이 함수는 **문자열과 숫자만 받는다.** 카드군 이름 목록과, 읽지 못한
호출의 원문 목록이다. ``CardConstraint`` 를 들고 있는 쪽이 두 칸을 꺼내
넘긴다 — 한 줄이고, 경계는 그대로다::

    from engine.archetype_compiler import (
        compile_archetype_condition, unread_archetype_calls,
    )

    compile_archetype_condition(
        constraint.setcodes,
        unread=unread_archetype_calls(constraint.raw_predicates),
    )

무엇을 하지 않는가
------------------
카드군 소속을 **판정하지 않는다** (:func:`~engine.archetype.matches_setcode`
가 한다). 이름을 **지어내지 않는다**. ``CardConstraint`` 의 나머지 축(종족 ·
속성 · 레벨 · 카드 종류 · 카드 ID)은 **보지 않는다** — 각자 조건이 필요하고
이번 범위가 아니다. 그래서 이 함수의 결과를 "이 필터를 전부 옮겼다" 로
읽으면 안 된다. 옮긴 것은 **카드군 한 축**이다.

세 가지 실패를 **서로 다르게** 적는다
-------------------------------------
실측 (``c*.lua`` 12,968개 · ``IsSetCard`` 호출 7,451회 · 조건 8,633개).

1. **카드군 요구가 없다** (조건 16,963개). ``None`` 을 돌려준다.
   🔴 결과 객체를 만들지 않는다 — ``Condition | None`` 칸을 하나 더 만들면
   "조건이 없다" 와 "적지 않았다" 가 같은 타입이 된다. Phase 3-E-34 가
   센 다섯 자리의 계약 불일치가 바로 그것이고, ``Requirement.condition``
   이 이미 같은 선택을 했다 — 조건이 없으면 ``Requirement`` 를 안 만든다.
2. **이름은 읽었는데 코드가 없다** (조건 47개 + 일부 해결 3개 · 이름 3개:
   ``SET_CENTURION`` · ``SET_DRAGONTAIL`` · ``SET_DIABELLESTARR``).
   상수 파일이 그 카드군보다 오래된 스냅숏이다. →
   :class:`~engine.condition.ArchetypeUnresolved`. **데이터를 갱신해야**
   풀리므로 ``missing_rules`` 가 비어 있다.
3. **이름을 아예 읽지 못했다** (조건 18개 · 카드 6장. ``IsSetCard(setcode)``
   처럼 인자가 런타임 변수다). →
   :class:`~engine.condition.UnimplementedRule`. 이쪽은 **코드가 생겨야**
   풀린다 (Lua 분석이 변수를 따라가야 한다).

🔴 **해결하지 못한 이름을 조용히 버리지 않는다.** ``IsSetCard`` 의 목록은
"하나라도 맞으면" 이므로 못 바꾼 이름을 빼면 조건이 **좁아지고**, 그 카드군의
카드가 ``FALSE`` 로 판정된다. 모르는 것을 거짓으로 접는 일이다. 그래서
``Or`` 로 묶어 3치 논리에 맡긴다::

    Or(IsSetCard((0x11b,)), ArchetypeUnresolved("CENTURION"))

    오르페골 카드   → TRUE     (맞춘 쪽이 확정이다)
    그 밖의 카드    → UNKNOWN  (센츄리온일 수도 있다)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from engine.condition import (
    ArchetypeUnresolved,
    Condition,
    IsSetCard,
    Or,
    UnimplementedRule,
)
from engine.vocabulary import EngineVocabulary, default_vocabulary

#: 읽지 못한 ``IsSetCard`` 호출이 ``CardConstraint.raw_predicates`` 에 남을
#: 때의 머리말. ``analysis/effect_analyzer.py::_record_unread`` 가 적는다.
UNREAD_PREFIX = "IsSetCard("

#: 인자를 읽지 못한 호출에 붙는 **없는 규칙**의 이름.
UNREAD_RULE = "lua-archetype-argument (IsSetCard 인자가 런타임 변수)"


def unread_archetype_calls(raw_predicates: Iterable[str]) -> tuple[str, ...]:
    """
    구조화하지 못한 조건 원문 중 **카드군 호출**만 골라낸다.

    ``raw_predicates`` 에는 다른 술어도 들어올 수 있으므로, 머리말로
    가린다. 문자열만 보고 판단하므로 ``analysis`` 를 import 하지 않는다.
    """
    return tuple(
        entry for entry in raw_predicates if entry.startswith(UNREAD_PREFIX)
    )


@dataclass(frozen=True, slots=True)
class ArchetypeCompilation:
    """
    카드군 한 축을 옮긴 결과. **불변**이고, 출처를 함께 들고 있다.

    :attr:`condition` 은 ``Optional`` 이 **아니다.** 옮길 것이 없으면
    :func:`compile_archetype_condition` 이 이 객체를 아예 만들지 않는다.
    """

    condition: Condition
    """엔진이 바로 쓸 수 있는 조건. ``require=`` 에 그대로 넣는다."""

    resolved: tuple[tuple[str, int], ...] = ()
    """``(이름, 코드)`` 짝. **어느 이름이 어느 코드가 되었는지**를 남긴다."""

    unresolved: tuple[str, ...] = ()
    """코드를 찾지 못한 이름들 (상수 표에 없다)."""

    unread: tuple[str, ...] = ()
    """이름조차 읽지 못한 호출의 원문들."""

    def __post_init__(self) -> None:
        if not isinstance(self.condition, Condition):
            raise TypeError(
                f"condition 은 Condition 이어야 합니다: {self.condition!r}"
            )
        if not (self.resolved or self.unresolved or self.unread):
            raise ValueError(
                "옮긴 것이 하나도 없는 결과는 만들지 않습니다. 카드군 요구가 "
                "없으면 compile_archetype_condition 이 None 을 돌려줍니다."
            )

    @property
    def is_complete(self) -> bool:
        """
        **이름을 하나도 남기지 않고 숫자로 바꿨는가.**

        거짓이면 조건은 쓸 수 있지만 ``UNKNOWN`` 이 섞인다. 확정이 필요한
        호출자(효과를 등재하려는 쪽)는 이 값을 보고 물러서야 한다.
        """
        return not self.unresolved and not self.unread

    def canonical_state(self) -> tuple:
        return (
            self.condition.canonical_state(),
            self.resolved,
            self.unresolved,
            self.unread,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "condition": self.condition.to_dict(),
            "resolved": [
                {"name": name, "setcode": f"0x{code:x}"}
                for name, code in self.resolved
            ],
        }
        if self.unresolved:
            data["unresolved"] = list(self.unresolved)
        if self.unread:
            data["unread"] = list(self.unread)
        return data

    def describe_ko(self) -> str:
        parts = [f"SET_{name}→0x{code:x}" for name, code in self.resolved]
        parts += [f"SET_{name}→?" for name in self.unresolved]
        if self.unread:
            parts.append(f"읽지 못한 호출 {len(self.unread)}개")
        return " · ".join(parts)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def compile_archetype_condition(
    setcode_names: Sequence[str],
    *,
    unread: Sequence[str] = (),
    vocabulary: EngineVocabulary | None = None,
) -> ArchetypeCompilation | None:
    """
    카드군 **이름 목록**을 조건으로 옮긴다.

    ``setcode_names`` 는 ``SET_`` 접두사를 뗀 이름들이다 (``["ORCUST"]``);
    접두사가 붙어 있어도 상수 표가 받아 준다. ``unread`` 는 인자를 읽지
    못한 호출의 원문들이고, :func:`unread_archetype_calls` 가 골라 준다.

    둘 다 비어 있으면 **카드군 요구가 없다**는 뜻이므로 ``None`` 이다
    (모듈 설명의 실패 1번).

    ``vocabulary`` 를 넘기지 않으면 기본 상수 표를 쓴다. 바꿔 넣을 수 있게
    열어 둔 것은 **시험이 가짜 표로 세 갈래를 다 만들 수 있어야** 하기
    때문이다.
    """
    table = vocabulary if vocabulary is not None else default_vocabulary()

    names = tuple(setcode_names)
    unread_calls = tuple(unread)
    if not names and not unread_calls:
        return None

    resolved: list[tuple[str, int]] = []
    unresolved: list[str] = []
    for given in names:
        # 🔴 **표가 돌려주는 이름으로 바꾸지 않는다.** ``ConstantGroup`` 은
        # 한 코드에 이름이 여럿이면 먼저 들어온 하나만 대표로 들고 있고,
        # 실제로 ``SET_POLYMERIZATION`` 과 ``SET_FUSION`` 이 둘 다 ``0x46``
        # 이다 (실측 1묶음). 역조회로 정규화하면 스크립트가 적은 이름이
        # 다른 이름으로 바뀐다. 접두사만 떼어 **적힌 그대로** 남긴다.
        name = given[len("SET_"):] if given.upper().startswith("SET_") else given
        code = table.archetypes.value(given)
        if code is None:
            unresolved.append(name)
        else:
            resolved.append((name, code))

    branches: list[Condition] = []
    if resolved:
        branches.append(IsSetCard(tuple(code for _, code in resolved)))
    branches.extend(ArchetypeUnresolved(name) for name in unresolved)
    if unread_calls:
        # 호출이 여러 개여도 없는 규칙은 하나다 — 같은 이름을 여러 번
        # 올리면 "모르는 이유" 가 개수만큼 불어난다.
        branches.append(UnimplementedRule(UNREAD_RULE))

    condition = branches[0] if len(branches) == 1 else Or(tuple(branches))
    return ArchetypeCompilation(
        condition=condition,
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
        unread=unread_calls,
    )


__all__ = [
    "UNREAD_PREFIX",
    "UNREAD_RULE",
    "ArchetypeCompilation",
    "compile_archetype_condition",
    "unread_archetype_calls",
]
