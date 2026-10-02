"""
Target Selection Bridge — ``PlayerAction`` 의 대상을 효과 계층에 건네는 자리
(Phase 3-E-4).

    PlayerAction(targets=(ActionTarget.instance(#41), ...))
          ↓  selections_for(definition, action)
    (TargetSelection(@primary, Selection((#41,))), ...)
          ↓  EffectActivator.activate(selections=...)
    ChainLink(selections=...)
          ↓  ChainResolver → EffectExecutor
    GameState 변경

**이 모듈은 다리 하나다.** 대상을 고르지도, 후보를 세지도, 적법성을 판정하지도
않는다. 셋 다 이미 있다.

    후보 세기      :meth:`~engine.effect.targeting.TargetResolver.candidates`
                   (그 안에서 ``CandidateResolver`` 를 쓴다)
    적법성 판정    :meth:`~engine.effect.targeting.TargetResolver.validate`
    고르기         정책 — 엔진의 일이 아니다

없던 것은 **``ActionTarget`` 과 ``TargetSelection`` 사이의 환전**뿐이고,
그것이 STRUCTURAL-121 이었다.

왜 환전이 필요한가
------------------
둘은 **다른 질문에 답하는 다른 타입**이고, 합치면 안 된다.

======================  ====================================================
:class:`~engine.action_  행위가 **무엇을 가리키는가**. 자리 · 플레이어 · 존도
target.ActionTarget`     가리킬 수 있고, 이름이 없다 (순서만 있다)
:class:`~engine.effect.  **어느 이름의 대상**에 무엇이 골라졌는가. 이름은
target.TargetSelection`  정의에서 오고 (``@primary`` · ``@random``) 카드는
                         고른 쪽에서 온다
======================  ====================================================

그래서 환전은 **순서 → 이름**이다. ``action.targets`` 를 정의의
``targets`` 중 **고르는 사람이 있는 것들**에 정의 순서대로 짝지운다.

고르는 사람이 없는 것은 짝에서 빠진다
-------------------------------------
``TargetSpec.at_random`` 과 ``at_bulk`` 는 **발동 시점에 정하지 않는다**
(Phase 2-AB · 2-AI). 공식 스크립트도 ``s.target`` 이 아니라 ``s.activate``
에서 ``RandomSelect`` 를 부르고, :class:`~engine.activation.EffectActivator`
는 그런 이름에 밖에서 고른 결과가 들어오면 **거부한다.**

그래서 이 모듈은 그 둘을 짝짓기에서 아예 제외한다 — "무작위로 1장" 과
"플레이어가 1장" 을 같은 자리에 놓지 않는다 (§18).

여기서 하지 않는 것
-------------------
새 Target Engine · TargetGraph · TargetSearchEngine · 새 적법성 어휘 ·
새 hidden-information 체계. 대상 지정 후 변경 · 체인 상의 대상 적법성 ·
targeting 과 non-targeting 의 전체 규칙도 다루지 않는다.
"""

from __future__ import annotations

from engine.action import PlayerAction
from engine.action_target import ActionTarget, ActionTargetKind
from engine.condition import ConditionContext
from engine.cost import Selection
from engine.effect.target import TargetBinding, TargetSelection
from engine.effect.targeting import TargetResolver
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState


class TargetBridgeError(RuntimeError):
    """
    대상을 건넬 수 없다. **적법성 판정이 아니다** — 모양이 맞지 않는다는 뜻이다.

    적법성은 :class:`~engine.effect.targeting.TargetResolver` 가 보고,
    여기서 걸리는 것은 "이 행위의 대상 개수가 이 효과의 모양과 다르다" 하나다.
    """


def chosen_bindings(
    definition,
) -> "tuple[TargetBinding, ...]":
    """
    이 효과에서 **고르는 사람이 있는** 대상들. 정의 순서를 보존한다.

    ``at_random`` · ``at_bulk`` 는 빠진다 — 발동 시점에 정하지 않으므로
    ``PlayerAction`` 이 가리킬 것이 없다.
    """
    return tuple(
        binding
        for binding in definition.targets
        if not binding.spec.is_random and not binding.spec.is_bulk
    )


def required_target_count(definition) -> int:
    """
    이 효과를 발동하려면 ``PlayerAction.targets`` 에 몇 장이 있어야 하는가.

    고르는 자리마다 ``ChoiceSpec.minimum`` 을 더한다. 지금 목록의 모든
    효과가 ``minimum == maximum == 1`` 이지만, 그 사실에 기대지 않는다.
    """
    total = 0
    for binding in chosen_bindings(definition):
        choice = binding.spec.choice
        total += choice.minimum if choice is not None else 0
    return total


def selections_for(
    definition, action: PlayerAction
) -> "tuple[TargetSelection, ...]":
    """
    ``action.targets`` 를 정의의 이름들에 **순서대로** 짝지운다.

    받는 것은 ``INSTANCE`` 대상뿐이다. 자리(``ZONE``)나 플레이어(``PLAYER``)를
    효과의 대상으로 건네는 길은 만들지 않았다 — 지금 목록에 그런 효과가 없고,
    없는 것을 추측해서 만들지 않는다.

    개수가 맞지 않으면 :class:`TargetBridgeError` 다. **적법성이 아니라
    모양**이고, 적법성은 받는 쪽(``TargetResolver``)이 다시 본다 — 그래서
    이 함수가 통과시킨 것이 "적법한 대상" 을 뜻하지 않는다.
    """
    bindings = chosen_bindings(definition)
    if not bindings:
        if action.targets:
            raise TargetBridgeError(
                f"{action.effect_ref} 는 고를 대상이 없는데 "
                f"{len(action.targets)}개가 들어왔습니다."
            )
        return ()

    for target in action.targets:
        if target.kind is not ActionTargetKind.INSTANCE:
            raise TargetBridgeError(
                f"효과의 대상은 카드(instance)여야 합니다: {target.kind.value}"
            )

    wanted = required_target_count(definition)
    if len(action.targets) != wanted:
        raise TargetBridgeError(
            f"{action.effect_ref} 는 대상 {wanted}장이 필요한데 "
            f"{len(action.targets)}개가 들어왔습니다."
        )

    selections: list[TargetSelection] = []
    cursor = 0
    for binding in bindings:
        choice = binding.spec.choice
        take = choice.minimum if choice is not None else 0
        chosen = tuple(
            t.instance_id for t in action.targets[cursor : cursor + take]
        )
        cursor += take
        selections.append(
            TargetSelection(binding.ref, Selection(chosen))
        )
    return tuple(selections)


def targets_from(instances) -> "tuple[ActionTarget, ...]":
    """
    ``InstanceId`` 들을 ``PlayerAction`` 에 넣을 모양으로 바꾼다.

    후보를 만드는 쪽(:meth:`~engine.duel.Duel._activation_actions`)이 쓰는
    반대 방향의 환전이다. 순서를 보존한다 — ``set`` 으로 만들면 "어느 순서로
    골랐는가" 가 사라지고, 그것이 의미를 갖는 규칙이 생겼을 때 표현할 수
    없게 된다 (§9).
    """
    return tuple(ActionTarget.instance(instance) for instance in instances)


def target_combinations(
    state: GameState, seat: int, definition, source: InstanceId
) -> "list[tuple[ActionTarget, ...]]":
    """
    이 효과로 만들 수 있는 **대상 조합들**. 대상이 없으면 빈 조합 하나다.

    후보를 **새로 세지 않는다** — :meth:`
    ~engine.effect.targeting.TargetResolver.candidates` 가 그 일을 하고,
    그것은 안에서 ``CandidateResolver`` 를 쓴다. 이 함수가 하는 일은 그
    결과를 ``PlayerAction`` 의 모양으로 바꾸는 것뿐이다.

    **``eligible`` 만 쓴다.** ``undecided`` (이 카드가 후보인지 모른다)와
    ``unchecked`` (저기를 못 봤다)는 후보로 올리지 않는다 — 올리면
    ``UNKNOWN`` 이 허가가 된다. 그 둘은 ``can_activate`` 가 다시 보고
    ``UNKNOWN`` 으로 돌려주므로, 설령 여기서 새어 나가도 후보가 되지는
    않는다. 관문이 둘인 이유가 그것이다.

    **관측은 행위자의 것이다** (ADR-007 · Phase 2-Y). 규칙이 선언한
    ``looked_at`` 만 열고 그 시점으로 센다 — :meth:`
    ~engine.activation.EffectActivator._check_targets` 가 쓰는 것과 **같은
    호출**이다. 그래서 상대의 뒷면 카드는 ``undecided`` 로, 가려진 존은
    ``unchecked`` 로 남는다.

    순서는 **관측의 순서**다 (``CandidateResolver`` 가 존을 훑는 순서).
    ``set`` 으로 만들지 않으므로 같은 판이면 같은 순서가 나온다 (§9 · §17).

    지금은 **고르는 자리가 하나이고 한 장을 고르는** 효과까지만 조합을
    만든다. 둘 이상이거나 N장이면 조합 폭발과 순서 규칙을 함께 정해야 하고
    (§8 · §9), 그 규칙이 아직 없으므로 추측하지 않는다 — 목록에 그런 효과도
    없다. 빈 목록을 돌려주므로 **후보가 되지 않는다**(NOT_REACHED).
    """
    bindings = chosen_bindings(definition)
    if not bindings:
        return [()]
    if len(bindings) > 1:  # pragma: no cover - 목록에 아직 없다
        return []
    binding = bindings[0]
    choice = binding.spec.choice
    if choice is None or choice.minimum != 1 or choice.maximum != 1:
        return []

    context = ConditionContext(
        player=seat, source=source, effect_ref=definition.effect_ref
    )
    # 규칙이 선언한 ``looked_at`` 을 열고 센다 — 효과가 볼 수 있는 것을
    # 효과의 눈으로 본다 (``_check_targets`` 와 같은 호출).
    granted = GameStateView.from_state(
        state, viewer=seat, looked_at=binding.spec.looked_at_zones()
    )
    found = TargetResolver(granted).candidates(binding.spec, context)

    # **그리고 평소 관측으로 한 번 더 좁힌다.**
    #
    # ``PlayerAction`` 은 정책에게 가는 **데이터**다 (``legal_actions`` 가
    # 그대로 건넨다). 그래서 거기에 가려진 존의 카드를 적으면, 정책이 후보
    # 목록을 읽는 것만으로 덱 내용을 알게 된다 — ``looked_at`` 이 효과에게
    # 준 권한이 AI 에게까지 새는 길이다.
    #
    # 그 권한은 **해결 중에만** 유효하다. 그래서 다리는 평소 관측에 보이는
    # 카드만 가리킨다. 아래가 걸러내는 효과(어리석은 매장 — 덱의 몬스터를
    # 고른다)는 그래서 후보가 되지 않는다 (STRUCTURAL-125).
    #
    # ``ActionValidator`` 의 참조 무결성 검사도 같은 것을 잡지만
    # (``_first_unseen``), 거기까지 흘려보내지 않는다 — 가려진 카드를 가리키는
    # Action 을 **만들지 않는 것**이 만들고 거절하는 것보다 낫다.
    ordinary = GameStateView.from_state(state, viewer=seat)
    return [
        targets_from((instance,))
        for instance in found.eligible
        if ordinary.find(instance) is not None
    ]


__all__ = [
    "TargetBridgeError",
    "target_combinations",
    "chosen_bindings",
    "required_target_count",
    "selections_for",
    "targets_from",
]
