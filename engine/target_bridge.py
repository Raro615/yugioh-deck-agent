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

정확히 N장 (Phase 6-P)
----------------------
:func:`target_combinations` 는 처음에 **한 장짜리 효과**만 열거했고, 그래서
벌금(92595643, "자신은 패를 2장 버린다") 은 조합이 **0개**여서
``legal_actions`` 에 오르지 못했다. 막고 있던 것은 대상 모델도 실행기도
아니라 **이 다리의 열거 한 줄**이었다 — 손으로 2장을 지정하면 그때도
``can_activate`` 는 ``VALID`` 였고 해결까지 갔다 (실측: 패 5 → 3, 묘지 0 → 3).

그래서 넓힌 것은 **장수가 고정인 한 자리**까지다. 그 밖의 모양
(자리가 둘 이상 · 최소≠최대 · 중복 허용 · 상한 초과)은
:func:`unsupported_enumeration` 이 **이유의 이름을 대고** 빈 목록이 된다.

여기서 하지 않는 것
-------------------
새 Target Engine · TargetGraph · TargetSearchEngine · 새 적법성 어휘 ·
새 hidden-information 체계. 대상 지정 후 변경 · 체인 상의 대상 적법성 ·
targeting 과 non-targeting 의 전체 규칙도 다루지 않는다.

**해결 시 선택을 발동 시 지정과 가르는 일도 하지 않는다.** 모델은 둘을
구분하고 있지만 (``TargetRequirement.TARGETING`` vs ``CHOOSING``,
``TargetSpec.is_targeting``) 실행 경로는 아직 양쪽을 같은 자리에서 받는다.
그것을 가르려면 체인 해결 절차가 새로 필요하고 (Phase 6-P §9 가 금지한다),
벌금은 ``CHOOSING`` 이므로 이 Phase 가 넓힌 것은 **그 기존 계약 안**이다.
"""

from __future__ import annotations

import itertools
import math

from engine.action import PlayerAction
from engine.action_target import ActionTarget, ActionTargetKind
from engine.condition import ConditionContext
from engine.cost import Selection
from engine.effect.target import TargetBinding, TargetSelection
from engine.effect.targeting import TargetResolver
from engine.game_state_view import GameStateView
from engine.ids import InstanceId
from engine.state.game_state import GameState
from engine.vocabulary import Zone


#: 열거할 대상 조합 수의 **상한** (Phase 6-P).
#:
#: 🔴 **유희왕 규칙이 아니라 선언한 공학적 상한이다.** 규칙에는 "조합이
#: 몇 가지까지 적법한가" 라는 것이 없다. 이 수를 두는 이유는 열거 결과가
#: 그대로 :class:`~engine.action.PlayerAction` 이 되어 정책에게 가기
#: 때문이고, 조합 수는 후보 수에 대해 지수적으로 늘기 때문이다
#: (덱에서 5장을 고르는 효과라면 ``C(40,5) = 658,008``).
#:
#: 넘으면 **자르지 않고 열거를 포기한다.** 잘라서 돌려주면 "legal_actions
#: 에 오른 것이 전부다" 가 거짓이 되고, 정책은 자기가 못 본 수가 있다는
#: 사실조차 모른다. 포기하면 지금과 똑같이 빈 목록이므로 (NOT_REACHED)
#: **없던 허가가 생기지 않는다** — 안전한 쪽으로 틀린다.
#:
#: 값의 근거: 등재된 유일한 다중 선택(벌금, 패에서 정확히 2장)에서 실측
#: ``C(5,2) = 10`` 이고, 룰북이 적은 패 상한 6장이면 ``C(6,2) = 15`` 다
#: (``sd-rulebook-en-v10.json`` 의 ``zones``). 256 은 2장 선택을 패 23장까지
#: 덮고, 폭발하는 모양은 거부한다.
MAX_TARGET_COMBINATIONS: int = 256

#: 고르는 자리가 둘 이상일 때 **없는 규칙의 이름** (Phase 6-P).
UNSUPPORTED_MULTIPLE_BINDINGS = (
    "multiple-chosen-bindings (서로 다른 조건의 대상을 각각 고르는 효과의 "
    "조합 순서 규칙 — 어느 자리를 먼저 고르는가가 적법성을 바꾸는지)"
)

#: 장수가 **고정이 아닐 때** 없는 규칙의 이름 (Phase 6-P).
UNSUPPORTED_VARIABLE_COUNT = (
    "variable-selection-count (최소와 최대가 다른 효과에서 실제로 몇 장을 "
    "고를 수 있는지 — 후보가 부족할 때 줄여도 되는지)"
)

#: 같은 카드를 두 번 고를 수 있다고 적힌 효과 (Phase 6-P).
UNSUPPORTED_DUPLICATE_CHOICE = (
    "duplicate-selection (같은 카드를 두 번 고르는 효과의 조합 열거 — "
    "등재된 효과에 하나도 없다)"
)

#: 조합이 :data:`MAX_TARGET_COMBINATIONS` 를 넘었다 (Phase 6-P).
UNSUPPORTED_COMBINATION_COUNT = (
    "combination-ceiling (선언한 조합 상한을 넘는 효과 — 자르지 않고 "
    "열거를 포기한다)"
)


def unsupported_enumeration(definition, pool_size: "int | None" = None) -> "str | None":
    """
    이 효과의 대상 조합을 **열거할 수 없다면 그 이유의 이름**, 열거할 수
    있으면 ``None`` (Phase 6-P).

    ``pool_size`` 를 주면 조합 수 상한까지 함께 본다. 주지 않으면 **모양만**
    본다 — 후보를 세기 전에 모양으로 거를 수 있는지 먼저 묻기 위한 것이다.

    🔴 **이것은 적법성 판정이 아니다.** "이 효과를 발동할 수 없다" 가 아니라
    "이 다리가 후보를 열거할 줄 모른다" 다. 그래서 이름이 ``MISSING_*``
    계열(:mod:`engine.effect.semantics`)과 같은 모양이다 — 없는 것은 규칙이
    아니라 **열거 절차**이지만, 둘 다 "모른다" 를 허가로 바꾸지 않는다.
    """
    bindings = chosen_bindings(definition)
    if len(bindings) > 1:
        return UNSUPPORTED_MULTIPLE_BINDINGS
    if not bindings:
        return None
    choice = bindings[0].spec.choice
    if choice is None:  # pragma: no cover - TargetSpec 이 이미 막는다
        return None
    minimum = getattr(choice, "minimum", None)
    maximum = getattr(choice, "maximum", None)
    if minimum is None or maximum is None:  # pragma: no cover - 무작위 · 전부는 위에서 빠진다
        return None
    if minimum != maximum or minimum < 1:
        #: ``minimum == maximum == 0`` 도 여기다 — 고를 것이 있다면서 0장을
        #: 고르라는 명세는 모순이고, 추측해서 빈 선택을 만들지 않는다.
        return UNSUPPORTED_VARIABLE_COUNT
    if getattr(choice, "allow_duplicates", False):
        return UNSUPPORTED_DUPLICATE_CHOICE
    if pool_size is not None and math.comb(pool_size, minimum) > MAX_TARGET_COMBINATIONS:
        return UNSUPPORTED_COMBINATION_COUNT
    return None


class TargetBridgeError(RuntimeError):
    """
    대상을 건넬 수 없다. **적법성 판정이 아니다** — 모양이 맞지 않는다는 뜻이다.

    적법성은 :class:`~engine.effect.targeting.TargetResolver` 가 보고,
    여기서 걸리는 것은 "이 행위의 대상 개수가 이 효과의 모양과 다르다" 하나다.
    """


#: **평소 관측이 가리는 자리들** (Phase 6-Z).
#:
#: 이 자리의 카드는 ``PlayerAction`` 이 가리킬 수 없다 — 적으면 정책이 후보
#: 목록을 읽는 것만으로 그 내용을 알게 된다 (``STRUCTURAL-125``). 그래서
#: 거기서 고르는 효과는 **해결 시점**에 고른다.
#:
#: 🔴 **패는 여기 없다.** 자기 패는 평소 관측에 보이므로 (``CandidateSource``
#: 의 주인이 ``CONTROLLER`` 다) 발동 시점에 가리킬 수 있고, 실제로 그렇게
#: 하고 있는 효과가 있다 (벌금 92595643 — 패 2장). 그 동작을 바꾸지 않는다.
CONCEALED_ZONES: frozenset[Zone] = frozenset({Zone.DECK, Zone.EXTRA})


def decided_at_resolution(spec) -> bool:
    """
    이 선택이 **해결 시점**에 정해지는가.

    둘을 **함께** 본다.

    1. 규칙상 **대상 지정이 아니다** (``CHOOSING``). 대상 지정은 발동 시점에
       선언하는 것이고 (``EFFECT_FLAG_CARD_TARGET``), 고르기는 해결 중에
       일어난다 — 공식 스크립트가 그 둘을 다른 자리에 적는다
       (``SetTarget`` 대 ``SetOperation``).
    2. 고르는 자리가 **평소 관측에 가려져 있다** (:data:`CONCEALED_ZONES`).

    왜 둘 다인가 — 1번만 보면 벌금(패 2장)의 발동 시점 열거가 사라진다. 그
    효과는 자기 패에서 고르므로 발동 시점에 가리킬 수 있고, 그 동작을
    바꾸는 것은 이 Phase 의 범위가 아니다. 2번만 보면 대상 지정인데 덱을
    보는 효과가 조용히 미뤄진다 (등재된 효과에 그런 모양은 **0건**이지만
    조건을 적어 둔다).

    🔴 **이것은 규칙 판정이 아니라 전달 방식의 결정이다.** 미뤄진 선택도
    같은 ``TargetResolver`` 가 같은 ``looked_at`` 으로 세고 같은 규칙으로
    검증한다 — 바뀌는 것은 **언제 묻는가**뿐이다.
    """
    if spec.is_targeting or spec.is_random or spec.is_bulk:
        return False
    if spec.choice is None:
        return False
    return bool(spec.looked_at_zones() & CONCEALED_ZONES)


def chosen_bindings(
    definition,
) -> "tuple[TargetBinding, ...]":
    """
    이 효과에서 **고르는 사람이 있는** 대상들. 정의 순서를 보존한다.

    ``at_random`` · ``at_bulk`` 는 빠진다 — 발동 시점에 정하지 않으므로
    ``PlayerAction`` 이 가리킬 것이 없다.

    🔴 **해결 시점에 정해지는 고르기도 빠진다** (Phase 6-Z,
    :func:`decided_at_resolution`). 같은 이유다 — 가려진 자리의 카드를
    ``PlayerAction`` 이 가리킬 수 없으므로, 발동 시점에 짝지울 것이 없다.
    """
    return tuple(
        binding
        for binding in definition.targets
        if not binding.spec.is_random
        and not binding.spec.is_bulk
        and not decided_at_resolution(binding.spec)
    )


def required_target_count(definition) -> int:
    """
    이 효과를 발동하려면 ``PlayerAction.targets`` 에 몇 장이 있어야 하는가.

    고르는 자리마다 ``ChoiceSpec.minimum`` 을 더한다.

    🔴 **"모든 효과가 1장" 은 더 이상 참이 아니다** (Phase 6-P). 벌금
    (92595643) 이 ``minimum == maximum == 2`` 이고, 공식 텍스트가 "자신은
    패를 2장 버린다" 다. 그래서 이 함수는 2를 돌려준다 — 처음부터 합으로
    적어 둔 덕분에 고칠 것이 없었다.

    ``minimum`` 을 더하는 것이 옳은 것은 **장수가 고정일 때**다. 최소와
    최대가 다른 효과에서는 이 수가 "몇 장을 건네야 하는가" 에 답하지
    못하고, 그래서 :func:`selections_for` 가 그 모양을 거부한다
    (:data:`UNSUPPORTED_VARIABLE_COUNT`). 등재된 효과에 그런 모양은
    **0건**이다.
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

    #: 🔴 **가변 장수를 조용히 최소값으로 깎지 않는다** (Phase 6-P).
    #:
    #: 아래 ``take = choice.minimum`` 은 ``minimum == maximum`` 일 때만
    #: 참이다. "최대 2장" 효과라면 이 환전은 1장만 집어 들고 나머지를
    #: 버리는데, 그러면 플레이어가 2장을 골랐다는 사실이 **말없이**
    #: 사라진다. 등재된 효과에 그런 모양이 하나도 없으므로(실측 0건)
    #: 지금 고칠 규칙이 없고, 대신 **거부한다** — 미지원 절차를 자동
    #: 성공으로 처리하지 않는다.
    shape = unsupported_enumeration(definition)
    if shape is not None and shape != UNSUPPORTED_MULTIPLE_BINDINGS:
        raise TargetBridgeError(
            f"{action.effect_ref} 의 선택 장수를 이 다리가 다루지 못합니다: {shape}"
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

    **고르는 자리가 하나이고 장수가 고정인** 효과까지 조합을 만든다
    (Phase 6-P 에서 "한 장" 에서 "정확히 N장" 으로 넓혔다). 그 밖의 모양은
    :func:`unsupported_enumeration` 이 이름을 대고 빈 목록이 되므로
    **후보가 되지 않는다** (NOT_REACHED).

    정확히 N장을 어떻게 세는가
    --------------------------
    후보를 거른 **뒤에** ``itertools.combinations`` 로 묶는다. 순서가
    이것으로 결정된다 — ``eligible`` 은 관측 순서이고 ``combinations`` 는
    그 순서의 사전식이므로, 같은 판이면 같은 목록이 나온다 (§9).

    같은 카드가 한 조합에 두 번 들어가는 일은 **구조적으로** 없다 —
    ``combinations`` 는 서로 다른 자리를 고르고, 후보 목록에 같은
    ``InstanceId`` 가 두 번 들어 있지 않다. 그래서 중복 방지를 위한 검사를
    따로 쓰지 않는다 (쓰면 두 곳이 같은 규칙을 갖게 된다). 그럼에도
    ``TargetResolver._check_count`` 가 ``DUPLICATE_SELECTION`` 을 다시
    보므로 관문은 둘이다.

    **카드 ID 가 같아도 조합은 다르다.** 묶는 것은 ``InstanceId`` 이므로
    같은 이름 카드 2장은 서로 다른 두 후보이고, 그 둘을 함께 고른 조합이
    하나 나온다 (§8-1).
    """
    bindings = chosen_bindings(definition)
    if not bindings:
        return [()]
    shape = unsupported_enumeration(definition)
    if shape is not None:
        return []
    binding = bindings[0]
    choice = binding.spec.choice
    assert choice is not None  # unsupported_enumeration 이 보증한다
    take = choice.minimum

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
    pool = tuple(
        instance
        for instance in found.eligible
        if ordinary.find(instance) is not None
    )

    #: 상한은 **거른 뒤의** 후보 수로 본다 — 가려진 카드를 세어서 상한을
    #: 넘겼다고 하면, 못 쓸 후보 때문에 쓸 수 있는 효과가 막힌다.
    if unsupported_enumeration(definition, len(pool)) is not None:
        return []
    return [targets_from(combo) for combo in itertools.combinations(pool, take)]


__all__ = [
    "MAX_TARGET_COMBINATIONS",
    "UNSUPPORTED_COMBINATION_COUNT",
    "UNSUPPORTED_DUPLICATE_CHOICE",
    "UNSUPPORTED_MULTIPLE_BINDINGS",
    "UNSUPPORTED_VARIABLE_COUNT",
    "TargetBridgeError",
    "unsupported_enumeration",
    "target_combinations",
    "chosen_bindings",
    "CONCEALED_ZONES",
    "decided_at_resolution",
    "required_target_count",
    "selections_for",
    "targets_from",
]
