"""
**고르는 비용**과 ``PlayerAction`` 을 잇는 다리 (Phase 6-BI).

``engine.target_bridge`` 와 **같은 자리 · 같은 규율**이다. 저쪽은 "이 효과가
가리킬 수 있는 대상 조합" 을 만들어 행위에 싣고, 이쪽은 "이 효과의 비용으로
내놓을 수 있는 카드 조합" 을 만들어 행위에 싣는다.

왜 필요한가
-----------
6-AO 부터 ``EffectActivator.activate`` 는 ``cost_selections`` 를 **받을 수
있었고** ``CostPayer`` 도 그것을 치를 수 있었다. 🔴 **그런데 듀얼 고리가
그것을 만들지 않았다** — ``Duel.legal_actions`` 는 고를 것이 있는 비용을 만나면
후보를 만들지 않고 보류에 적었고 (``COST_SELECTION_MISSING``), 그래서 **비용으로
카드를 고르는 효과는 등재해도 발동되지 않았다.**

실측 (Phase 6-BI §1): 「오르페골 갈라테아i」 의 패 1장을 묘지로 보내는
효과가 그 자리에 걸린다.

🔴 **비용은 발동 시점에 치른다.** 그래서 고르는 자리도 **행위**다 — 해결 중의
선택(``ResolutionChooser``)이 아니다. 공식 스크립트가 그 구분을 그대로 적는다:
``e3:SetCost(s.thcost)`` 는 발동을 선언할 때 돌고, ``e3:SetOperation(s.thop)``
은 해결할 때 돈다.

지키는 것
---------
🔴 **후보를 새로 세지 않는다.** ``CandidateResolver`` 가 센 것을 조합으로
묶는 일만 한다 — 비용을 치를 수 있는지 판정하는 쪽
(:class:`~engine.cost.validation.CostValidator`) 과 **같은 호출**을 쓴다.

🔴 **``eligible`` 만 쓴다.** "후보인지 모른다"(``undecided``) 와 "저기를 못
봤다"(``unchecked``) 는 조합으로 올리지 않는다 — 올리면 ``UNKNOWN`` 이 허가가
된다.

🔴 **평소 관측에 보이는 카드만 가리킨다.** ``PlayerAction`` 은 정책에게 가는
데이터이므로, 가려진 존의 카드를 적으면 정책이 후보 목록만 읽고 그 내용을
알게 된다 (``target_bridge._candidate_pool`` 과 같은 이유). 자기 패는 자기
관측에 보이므로 패를 내놓는 비용은 그대로 열린다.

🔴 **조합을 무한히 만들지 않는다.** 모양이 "정확히 N장" 이 아니면
(``maximum`` 이 더 넓거나 비용이 둘 이상 고르게 하거나) 조합을 만들지 않고
그 사실을 이름으로 돌려준다 — 짐작해서 하나를 고르지 않는다.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from engine.condition import ConditionContext
from engine.cost import CandidateResolver, Selection
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.payment import CostSelection

__all__ = [
    "CostEnumerationLimits",
    "COST_ENUMERATION_CAP",
    "cost_choice_positions",
    "unsupported_cost_enumeration",
    "cost_card_combinations",
    "cost_selections_from",
]

#: 한 비용 자리에서 만들 **조합 수 상한** (Phase 6-BI).
#:
#: 🔴 **왜 상한이 필요한가.** 패 6장에서 3장을 고르는 비용이면 조합이 20개이고,
#: 그 각각이 후보 행위 하나가 된다. 후보 목록은 정책에게 그대로 가고 탐색은
#: 그것을 전부 펼치므로, 상한 없이 열면 **한 효과가 탐색 예산을 다 쓴다.**
#:
#: 🔴 **상한에 걸리면 조합을 만들지 않는다** — 일부만 내놓지 않는다. 일부만
#: 내놓으면 "이 카드로는 치를 수 있고 저 카드로는 못 치른다" 로 읽힌다.
COST_ENUMERATION_CAP: int = 12


@dataclass(frozen=True, slots=True)
class CostEnumerationLimits:
    """
    **왜 비용 조합을 만들지 못했는가** (Phase 6-BI).

    ``target_bridge.TargetEnumerationLimits`` 와 같은 자리다 — 조용히 빈
    목록을 돌려주지 않고 그 이유를 이름으로 들고 간다.
    """

    rule: str
    detail: str

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return f"{self.detail} ({self.rule})"


def cost_choice_positions(definition) -> "tuple[tuple[int, object], ...]":
    """
    ``(비용 자리 번호, 선택 명세)`` 들. 고를 것이 없는 비용은 들어오지 않는다.

    🔴 **자리 번호로 잇는다** — ``CostSelection`` 이 요구하는 그 번호이고,
    "고를 것이 있는 비용만 순서대로" 세지 않는다 (중간에 비용이 끼면 조용히
    다른 비용에 붙는다).
    """
    group = getattr(definition, "cost", None)
    if group is None:
        return ()
    found: list[tuple[int, object]] = []
    for index, cost in enumerate(getattr(group, "costs", ()) or ()):
        spec = cost.choice_spec()
        if spec is not None:
            found.append((index, spec))
    return tuple(found)


def unsupported_cost_enumeration(
    definition, pool_sizes: "dict[int, int] | None" = None
) -> "CostEnumerationLimits | None":
    """
    이 효과의 비용 조합을 만들 수 있는가. 만들 수 있으면 ``None``.

    🔴 **열어 둔 모양을 좁게 적는다** (ADR-006). 지금 만들 수 있는 것은
    **고르는 비용 자리가 하나이고 장수가 정확히 N장**인 모양뿐이다.
    """
    positions = cost_choice_positions(definition)
    if not positions:
        return None
    if len(positions) > 1:
        return CostEnumerationLimits(
            "cost-enumeration-multi-position",
            f"고르는 비용 자리가 {len(positions)}곳이라 조합을 만들지 "
            "않았습니다 — 자리마다 고른 것을 어떻게 묶을지 이 다리가 아직 "
            "정하지 않았습니다",
        )
    index, spec = positions[0]
    minimum = int(getattr(spec, "minimum", 0))
    maximum = int(getattr(spec, "maximum", 0))
    if minimum != maximum:
        return CostEnumerationLimits(
            "cost-enumeration-range",
            f"비용 장수가 {minimum}~{maximum}장이라 조합을 만들지 "
            "않았습니다 — 몇 장을 내놓을지 짐작하지 않습니다",
        )
    if minimum <= 0:
        return CostEnumerationLimits(
            "cost-enumeration-zero",
            "비용 장수가 0 장이라 고를 것이 없습니다",
        )
    if pool_sizes is None:
        return None
    size = int(pool_sizes.get(index, 0))
    if size < minimum:
        #: 🔴 **후보가 모자란 것은 "모양이 안 된다" 가 아니다** — 비용을
        #: 치를 수 없다는 뜻이고, 그 판정은 ``CostValidator`` 가 한다.
        #: 여기서는 조합이 0개가 되고, 보류 문장은 그쪽이 적는다.
        return None
    import math

    combos = math.comb(size, minimum)
    if combos > COST_ENUMERATION_CAP:
        return CostEnumerationLimits(
            "cost-enumeration-cap",
            f"후보 {size}장에서 {minimum}장을 고르는 조합이 {combos}개라 "
            f"상한 {COST_ENUMERATION_CAP}개를 넘었습니다 — 일부만 내놓으면 "
            "「이 카드로는 치를 수 있다」 로 읽히므로 하나도 만들지 "
            "않았습니다",
        )
    return None


def _cost_pool(state, seat: int, definition, source: InstanceId, spec):
    """
    이 비용 자리의 **후보 묶음**과, 행위가 가리킬 수 있는 것들.

    🔴 :class:`~engine.cost.validation.CostValidator` 가 쓰는 **같은 호출**
    이다 (``CandidateResolver.resolve``) — 두 벌이 되면 "후보 목록" 과
    "치를 수 있는가" 가 다른 규칙으로 갈린다.
    """
    context = ConditionContext(
        player=seat, source=source, effect_ref=definition.effect_ref
    )
    granted = GameStateView.from_state(
        state, viewer=seat, looked_at=spec.looked_at_zones()
    )
    found = CandidateResolver(granted).resolve(spec, context)
    ordinary = GameStateView.from_state(state, viewer=seat)
    pool = tuple(
        instance for instance in found.eligible
        if ordinary.find(instance) is not None
    )
    return found, pool


def cost_card_combinations(
    state, seat: int, definition, source: InstanceId
) -> "list[tuple[InstanceId, ...]]":
    """
    이 효과의 비용으로 내놓을 수 있는 **카드 조합들**.

    고를 비용이 없으면 **빈 조합 하나**다 (``[()]``) — 그러면 부르는 쪽의
    고리가 한 글자도 달라지지 않는다.

    순서는 **관측의 순서**다 (``CandidateResolver`` 가 존을 훑는 순서) 이고
    ``itertools.combinations`` 는 그 순서의 사전식이므로, 같은 판이면 같은
    목록이 나온다.
    """
    positions = cost_choice_positions(definition)
    if not positions:
        return [()]
    if unsupported_cost_enumeration(definition) is not None:
        return []
    index, spec = positions[0]
    _found, pool = _cost_pool(state, seat, definition, source, spec)
    if unsupported_cost_enumeration(definition, {index: len(pool)}) is not None:
        return []
    take = int(spec.minimum)
    return [tuple(combo) for combo in itertools.combinations(pool, take)]


def cost_selections_from(
    definition, cards: "tuple[InstanceId, ...]"
) -> "tuple[CostSelection, ...]":
    """
    행위에 적힌 카드들을 **그 비용 자리의 선택**으로 바꾼다.

    🔴 **비용이 없거나 적힌 카드가 없으면 빈 짝이다** — 없는 선택을 지어내지
    않는다. 자리 번호는 :func:`cost_choice_positions` 가 읽은 그 번호다.
    """
    if not cards:
        return ()
    positions = cost_choice_positions(definition)
    if not positions:
        return ()
    index, _spec = positions[0]
    return (CostSelection(index=index, selection=Selection(tuple(cards))),)
