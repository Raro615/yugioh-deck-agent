"""
Phase 3-E-36 — ``ValidationCode.RULE_NOT_IMPLEMENTED`` 정밀 의미 감사.

핵심 질문: **이 코드 하나가 서로 다른 의미를 담고 있는가.**

75 라는 숫자 자체를 문제로 보지 않는다. 파일에 있다는 것과 실제 게임에서
미구현으로 판정된다는 것을 구분하고, 각 자리의 **짝지은 상태**를 읽어서
의미를 정한다. 이름이나 파일명으로 분류하지 않는다.

측정으로 드러난 일곱 가지
-------------------------

1. **75 는 문자열 등장 수이고, 코드 등장은 69곳이다.** 나머지 6곳은 주석과
   docstring 이다 (`special_summon.py:77` · `trigger.py:978` ·
   `trigger_chain.py:553` · `:569` · `validation.py:129` · `:180`).

2. **69곳 중 생성이 아닌 것이 17곳이다** — enum 정의 1 · ``code`` 필드
   기본값 8 · 집합 멤버십 1 · 비교 1 · 닿지 않는 자리표시 1 · 올바르게
   가르는 ``IfExp`` 5.

3. **enum 자신이 금지선을 적어 두었다.**
   ``RULE_NOT_IMPLEMENTED`` 의 docstring 이 "``UNKNOWN`` 쪽의 코드다 —
   **확실한 거부(``INVALID``)에 붙이지 않는다**" 고 말한다.

4. **그 금지선을 어기는 자리가 결과 계층에 남아 있다.** 상태를 기계로 읽어
   가르면 **16곳**이 "모른다" 쪽이 아닌 상태와 짝지어 있다
   (``CONDITION_FALSE`` · ``FORBIDDEN`` · ``INVALID_ACTION`` ·
   ``CHAIN_REFUSED`` · ``INVALID_OPERATION`` · ``INVALID_CONTEXT`` ·
   ``EXECUTION_ERROR`` · ``REFUSED``), **16곳**은 올바르다.

5. **그중 넷은 정확한 코드가 이미 enum 에 있다.** 조건 거짓 ×2 →
   ``CANDIDATE_NOT_ELIGIBLE``, 출처 금지 ×2 → ``EXECUTION_FORBIDDEN``.
   **3-E-26 이 트리거 계층에서 고친 바로 그 두 가지**이고, 발동·해결
   계층에는 그대로 남아 있다.

6. **그런데 판정은 바뀌지 않는다.** ``.code`` 를 **판단 입력으로 읽는**
   production 자리는 넷뿐이고, 넷 다 이 오분류 때문에 다른 결론을 내지
   않는다. ``GateVerdict.forbids`` 는 트리거 계층만 보고,
   ``_undecided_code`` 는 ``UNKNOWN`` 관문만 보며,
   ``agent/simulation.py`` 는 ``UNKNOWN`` 과 ``REFUSED`` 를 **같은 순위**로
   줄 세운다.

7. **정보가 사라지지 않는다.** 정확한 사실은 **상태**가 들고 있다
   (``CONDITION_FALSE`` · ``FORBIDDEN`` · ``INVALID_CONTEXT``), 코드는 그
   옆에 붙은 거친 이름표다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import dataclasses
import pathlib

import pytest

from agent.search import SearchCandidate
from agent.simulation import SimulationResult, SimulationStatus, _UNKNOWN_CODES
from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionStatus, UNSUPPORTED_REASON
from engine.action_validation import ActionValidator
from engine.activation import ActivationStatus, _UNKNOWN_STATUSES
from engine.condition import Always, ConditionResult, IsMonster, UnimplementedRule
from engine.duel import Duel
from engine.effect import EffectProvenance
from engine.effect.resolution import ResolutionStatus, UnimplementedResolver
from engine.ids import InstanceId
from engine.trigger import (
    EligibilityGate,
    GateVerdict,
    TriggerCollector,
    TriggerRegistry,
    TriggerStatus,
)
from engine.validation import ActionValidity, ValidationCode, ValidationResult

from tests.conftest import requires_official_db

#: 발동 · 해결 계층을 **그대로** 부르는 기존 도구를 다시 쓴다.
from tests.test_validation_code_consistency import (
    activate,
    drawn_event,
    new_state,
    resolve,
    synthetic,
    watched_definition,
    watching,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE = 0


# ======================================================================
# 측정값 — 전부 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: ``engine/`` + ``agent/`` 의 **문자열** 등장 수.
#:
#: 75 → **76** (Phase 3-E-38 이 M1·M2 네 자리를 고치면서 코드 2 감소 ·
#: 까닭을 적은 주석 3 증가).
#: 🔴 79 → **80** (Phase 6-E). 늘어난 하나는
#: ``engine/trigger_compiler.py`` 의 **설명 안**이다 — "조건을 적지 않으면
#: 거짓 양성이 된다" 를 적으면서 그 코드 이름을 인용했다. **코드 자리는
#: 그대로 67개**이고, 이 파일의 ``CODE_OCCURRENCES`` 가 그것을 따로 센다.
#: 🔴 80 → **81** (Phase 6-F). 늘어난 하나는
#: :func:`~engine.trigger.subject_relation` 의 "선언이 주체를 적지 않았다"
#: 자리다. 같은 Phase 가 ``engine/trigger_compiler.py`` 에서 ``docstring``
#: 인용 하나를 **지웠고** (조건 자리를 돌려주면서) 새 자리 둘을 더했으므로
#: 합이 +1 이다.
#: (🔴 그 뒤 같은 Phase 안에서 다시 +1 — 관문의 짝을 리터럴로
#: 되돌리면서 ``RULE_NOT_IMPLEMENTED`` 자리가 하나 더 생겼다. 두 감사가
#: 계산된 값 전달을 잡아서 고친 것이고, 그 까닭은 6-F 보고서 §12 에 적었다.)
#: 🔴 82 → **84** (Phase 6-H). 코드 하나 + 산문 하나다 —
#: :func:`~engine.trigger.subject_relation` 의 ``OTHER`` 분기가
#: :data:`~engine.trigger.GROUP_MEMBERSHIP_RULE` 로 모름을 돌려주는 자리와,
#: 그 상수 위에 **왜 이 코드인지** 적은 주석이다 ("코드가 생겨야 풀리는
#: 모름이고 판이 바뀌어서 풀리는 모름이 아니다").
#: 🔴 84 → **86** (Phase 6-M). 둘 다 **코드 자리**이고 둘 다 거절이다 —
#: ``EffectExecutor._movement_refusal`` 이 (1) 엑스트라 덱 몬스터를 패 ·
#: 메인 덱으로 보내려는 이동과 (2) 이미 목적지에 있어 **일어나지 않는**
#: 이동을 멈춘다. 둘 다 ``UNSUPPORTED_OPERATION`` 과 짝지으므로
#: ``test_05`` 의 **적합** 쪽에 들어간다 (위반 13곳은 그대로다).
#: 이 테스트가 틀린 가정을 갖고 있었던 것이 아니라 그 시점에 실제로
#: 84개였다.
#: 🔴 86 → **87** (Phase 6-R). 늘어난 하나는 **산문**이다 —
#: ``Duel._resolve_chain`` 의 주석이 "불발된 체인이 남으면 발동 후보가
#: ``withheld`` 에도 남지 않고 ``apply`` 가 ``RULE_NOT_IMPLEMENTED``
#: ("허가된 행위가 아닙니다") 를 돌려준다" 를 적으면서 그 코드 이름을
#: 인용했다 (실측해서 적은 거짓 코드다). **코드 자리는 그대로**이고
#: ``CODE_OCCURRENCES`` 가 그것을 따로 센다 — 6-E 와 같은 결의 증가다.
#: 🔴 87 → **88** (Phase 6-V, Phase 6-W 가 실측해 정정). 늘어난 하나는
#: **코드 자리**다 — ``engine.trigger.TriggerEligibilityJudge`` 의
#: ``_zone_from_summon`` 이 "소환 사건이 적은 도착지와 지금 자리가 다르다"
#: 를 ``UNKNOWN`` 으로 돌려주는 관문이다. 그 사이의 이동을 이 계층이 읽지
#: 못하므로 **코드가 생겨야 풀리는 모름**이고, 그래서 ``CODE_OCCURRENCES``
#: 도 함께 72 → 73 이다 (산문 15는 그대로).
#: 🔴 88 → **89** (Phase 6-AB 보완5 가 실측해 정정). 늘어난 하나도
#: ``_zone_from_summon`` 과 **같은 결의 코드 자리**다 —
#: ``TriggerEligibilityJudge._zone_from_grave`` 가 "이동 사건은 묘지를
#: 적었는데 지금 자리가 다르다" 를 ``UNKNOWN`` 으로 돌려주는 관문이다.
#: 그 사이의 이동을 이 계층이 읽지 못하므로 **코드가 생겨야 풀리는 모름**
#: 이고, 그래서 ``CODE_OCCURRENCES`` 도 함께 73 → 74 다 (산문 15는 그대로).
#: 🔴 89 → **91** (Phase 6-AB 보완6). 🔴 **늘어난 둘은 코드가 아니라
#: 산문이다** — ``CODE_OCCURRENCES`` 는 74 그대로다. ``Duel._refusal`` ·
#: ``_refusal_verdict`` 의 설명이 **그 코드가 왜 그 자리에서 틀렸는지**를
#: 적는다 (규칙이 막은 것을 "엔진 미지원" 으로 보고하고 있었다). 즉 이
#: 코드의 **사용**이 하나 줄고 그것을 설명하는 글이 늘었다.
#: 🔴 91 → **93** (Phase 6-AB 보완7). 🔴 **늘어난 둘도 전부 산문이다** —
#: ``CODE_OCCURRENCES`` 는 74 그대로다. ``ActivationTiming.responding_kind``
#: 의 설명이 *"적법한 함정이 몬스터 효과에 응수하려 할 때 이 코드를
#: 받았다"* 는 실측을 인용하고, ``verified_activation_kind`` 의 설명이
#: *"이미 확인된 사실을 모른다고 답하고 있었다 — 어니스트 ①이 이 코드"*
#: 를 인용한다. 보완6 과 같은 결의 증가다: 이 코드의 **잘못된 사용**을
#: 고치면서 그 까닭을 적은 글이 늘어난다.
#: 🔴 93 → **110** (Phase 6-AB 보완8). 🔴 **이번에는 코드도 늘었다** —
#: 산문 11 · 코드 6 이다 (``CODE_OCCURRENCES`` 74 → 80).
#:
#: 🔴 **늘어난 코드 6은 새 거절이 아니다.** 보완8 이 ``WithheldAction`` 에
#: ``code`` 를 필수로 만들었고, 그래서 **이미 ``missing`` 을 달고 있던**
#: (즉 이미 모름이던) 보류 자리 여섯이 그 코드를 **명시**하게 되었다. 전에는
#: 그 사실이 "``missing`` 이 비어 있지 않다" 로만 암시되었다 — 읽는 쪽이
#: 짐작해야 했고 그것이 보완8 이 고친 결함이다.
#:
#: 즉 이 코드로 **거절하는 횟수는 늘지 않았고**, 그 코드를 **적는 자리**가
#: 늘었다. 그리고 보완8 은 반대 방향으로도 움직였다: 흐름 거절 넷이 이
#: 코드에서 ``STAGE_FORBIDS_ACTION`` 등으로 **빠져나갔다**.
#:
#: 🔴 110 → **111** (보완8 마무리). 늘어난 하나는 산문이다 —
#: ``Duel._refusal_sentence`` 의 설명이 *"검증기가 UNKNOWN /
#: RULE_NOT_IMPLEMENTED 로 답하면서 들고 있던 missing_rule 이 apply 경계에서
#: 사라졌다"* 는 실측을 인용한다.
STRING_OCCURRENCES = 111

#: 그중 주석 · docstring (코드가 아니다). 3-E-38 이 셋을 더했다 —
#: 왜 그 자리가 이제 다른 코드를 쓰는지 적은 주석이다.
#:
#: .. note::
#:    **``engine/trigger.py`` 네 자리가 +17 줄 밀렸다** (Phase 3-F-11).
#:
#:    978 → 995 · 1318 → 1335 · 1324 → 1341 · 1347 → 1364. 그 Phase 가
#:    ``TimingEvent.actor`` 의 docstring 을 사건군별 표로 늘렸고, 그 칸이 이
#:    네 자리보다 **위**에 있어서 아래가 전부 같은 만큼 밀렸다. 자리가 밀린
#:    것뿐이고 **산문 12 · 코드 67 · 문자열 79 는 하나도 바뀌지 않았다** —
#:    바뀐 것이 줄 번호뿐이라는 것이 그 증거다.
#: 🔴 **``engine/activation.py`` 두 자리가 +5 줄 밀렸다** (Phase 6-K).
#:
#: 634 → 639 · 672 → 677. ``EffectActivator._verdict`` 가 검증기에 정의
#: 등록소를 넘기게 되면서 그 자리에 설명 다섯 줄이 붙었고, 그 칸이 이 두
#: 자리보다 **위**에 있어서 아래가 같은 만큼 밀렸다. 자리가 밀린 것뿐이고
#: **산문 14 · 코드 70 · 문자열 84 는 하나도 바뀌지 않았다.**
#: .. note::
#:    🔴 **한 자리가 또 밀렸다** (Phase 6-M). ``engine/effect/executor.py``
#:    922 → **954**. 6-M 이 그 위에 ``movement_destination`` ·
#:    ``movement_player`` (+32줄) 를 넣어서 아래가 같은 만큼 밀렸다.
#:    **산문 14 는 하나도 바뀌지 않았다** — 6-M 이 더한 둘은 코드 자리이고
#:    (``CODE_OCCURRENCES`` 70 → 72), 그래서 문자열이 84 → 86 이다.
#: 🔴 **보완5 에서 일곱 자리가 밀렸다** — 성격도 개수(15)도 그대로이고
#: 바뀐 것이 **줄 번호뿐**이라는 것이 그 증거다.
#:
#:   ``trigger.py``  +36 (775→811 · 803→839 · 1369→1405 ·
#:                   1741→1778 · 1747→1784 · 1770→1807)
#:                   원인: ``graveyard_zone_for`` 와 ``_zone_from_grave``
#:   ``duel.py``     +38 (2300→2338)
#:                   원인: ``_apply_pass`` 의 빈 체인 가지
PROSE_OCCURRENCES = {
    # 🔴 **Phase 6-AB 보완8 이 이 표를 실측값으로 다시 적었다.**
    #
    # 전에는 Phase 마다 "어느 줄이 밀렸는가" 를 좌표로 쌓아 왔고, 그 기록이
    # 이 상수의 절반을 차지했다. 보완8 은 ``engine/duel.py`` 의 보류 생성
    # 자리 전부를 건드렸으므로 좌표가 대거 밀렸다 — 밀린 좌표를 또 한 번
    # 손으로 옮겨 적는 대신 **실측값으로 다시 적고**, 지키려는 주장을
    # ``test_02`` 의 등식에 남긴다: **문자열 - 코드 = 산문**이고, 그
    # 산문이 어느 파일의 어느 줄인지가 아래 표다.
    #
    # 🔴 **주장은 그대로다**: 이 코드의 등장 대부분이 ``UnimplementedRule``
    # 과 무관하고, 산문과 코드를 구분하지 않으면 "이 코드가 몇 번 쓰이는가"
    # 를 알 수 없다. 좌표를 적는 이유도 그것이다 — 어느 쪽이 설명이고 어느
    # 쪽이 실제 사용인지 고정한다.
    ("engine/activation.py", 732),
    ("engine/activation.py", 770),
    ("engine/activation_timing.py", 511),
    ("engine/duel.py", 175),
    ("engine/duel.py", 969),
    ("engine/duel.py", 1166),
    ("engine/duel.py", 2694),
    ("engine/duel.py", 2875),
    ("engine/duel.py", 2881),
    ("engine/duel.py", 2904),
    ("engine/duel.py", 2906),
    #: 🔴 보완8 마무리가 더한 자리 — ``_refusal_sentence`` 의 설명이다.
    ("engine/duel.py", 2972),
    ("engine/duel.py", 3213),
    ("engine/effect/definition.py", 896),
    ("engine/effect/executor.py", 1147),
    ("engine/special_summon.py", 77),
    ("engine/trigger.py", 811),
    ("engine/trigger.py", 839),
    ("engine/trigger.py", 1405),
    ("engine/trigger.py", 1778),
    ("engine/trigger.py", 1784),
    ("engine/trigger.py", 1807),
    ("engine/trigger_chain.py", 607),
    ("engine/trigger_chain.py", 623),
    ("engine/validation.py", 129),
    ("engine/validation.py", 180),
    ("engine/validation.py", 215),
    ("engine/validation.py", 231),
    ("engine/validation.py", 239),
    ("engine/validation.py", 362),
    ("engine/validation.py", 368),
}

#: 실제 코드 등장 = 79 - 12. (3-E-38 전에는 69 = 75 - 6, 3-E-38 뒤 67 = 76 - 9.)
#:
#: .. note::
#:    **3-E-45 는 이 숫자를 바꾸지 않았다** — 67 그대로다.
#:
#:    그 Phase 가 ``_event_relation`` 의 불일치 분기를
#:    ``CANDIDATE_NOT_ELIGIBLE`` 로 바꾸면서 코드 자리 하나를 **뺐고**,
#:    ``UNIMPLEMENTED`` 사건을 모름으로 돌려주는 분기에서 하나를 **더했다.**
#:    차감이 정확히 맞는다. 늘어난 3은 전부 그 까닭을 적은 **산문**이다
#:    (76 → 79).
#: 🔴 67 → **68** (Phase 6-F). 늘어난 하나는
#: :func:`~engine.trigger.subject_relation` 의 "선언이 주체를 적지 않았다"
#: 자리다 — 판이 바뀌어도 풀리지 않고 코드가 생겨야 풀리므로 이 코드가 맞다.
#: (🔴 그 뒤 같은 Phase 안에서 다시 +1 — 관문의 짝을 리터럴로
#: 되돌리면서 ``RULE_NOT_IMPLEMENTED`` 자리가 하나 더 생겼다. 두 감사가
#: 계산된 값 전달을 잡아서 고친 것이고, 그 까닭은 6-F 보고서 §12 에 적었다.)
#: 🔴 69 → **70** (Phase 6-H). ``OTHER`` 선언인데 사건의 주체가 **다른**
#: 카드인 자리다 — 그때 남는 질문("이 카드도 그 사건에 함께 포함되었는가")
#: 은 엔진의 사건이 주체 한 장만 들고 있어서 물을 데가 없다. 판이 바뀌어도
#: 풀리지 않고 **코드가 생겨야** 풀리므로 이 코드가 맞다.
#: 🔴 70 → **72** (Phase 6-M). ``EffectExecutor._movement_refusal`` 의
#: 거절 둘이다 — 엑스트라 덱 몬스터를 패 · 메인 덱으로 보내려는 이동과
#: 이미 목적지에 있어 **일어나지 않는** 이동. 둘 다 코드 자리이고 둘 다
#: ``UNSUPPORTED_OPERATION`` 과 짝지으므로 "모른다" 쪽이다.
#: 🔴 72 → **73** (Phase 6-V, Phase 6-W 가 실측해 정정).
#: ``TriggerEligibilityJudge._zone_from_summon`` 의 관문 하나다 — 소환
#: 사건이 적은 도착지와 지금 관측된 자리가 다를 때 **그 사이의 이동을
#: 읽지 못한다**고 적는다. 판이 아니라 코드가 생겨야 풀리는 모름이다.
#: 🔴 73 → **74** (보완5) — ``_zone_from_grave`` 의 관문 하나.
#: ``STRING_OCCURRENCES`` 의 설명과 같은 자리다.
#: 🔴 보완6 에서 **바뀌지 않았다** — 늘어난 둘은 산문이다.
#: 🔴 보완7 에서도 **바뀌지 않았다** — 늘어난 둘도 산문이다. 이 Phase 는
#: 이 코드를 새로 쓰지 않았고, 몬스터 효과의 거절을 이 코드에서
#: ``SPELL_SPEED_TOO_LOW`` 로 **옮겼다**.
#: 🔴 74 → **80** (Phase 6-AB 보완8). 늘어난 여섯은 전부
#: ``engine/duel.py`` 의 보류 생성 자리이고, **이미 모름이던 자리가 그
#: 코드를 명시하게 된 것**이다 (``STRING_OCCURRENCES`` 의 설명 참고).
#: 새로 이 코드로 거절하게 된 자리는 **없다** — 오히려 흐름 거절 넷이
#: 이 코드에서 빠져나갔다.
CODE_OCCURRENCES = 80

#: ``code: ValidationCode = ValidationCode.RULE_NOT_IMPLEMENTED`` 기본값 8곳.
FIELD_DEFAULT_OWNERS = {
    ("engine/action_execution.py", "ActionExecution"),
    ("engine/activation.py", "ActivationResult"),
    ("engine/chain.py", "ChainResolution"),
    ("engine/effect/resolution.py", "EffectResult"),
    ("engine/payment.py", "CostPaymentResult"),
    ("engine/response.py", "ResponseResult"),
    ("engine/trigger.py", "TriggerCandidate"),
    ("engine/trigger_chain.py", "TriggerChainEntry"),
}

#: 결과 계층에서 **"모른다" 쪽이 아닌 상태**와 짝지은 자리 (기계로 센다).
#: 줄 번호는 ``Call`` 의 첫 인자 줄이다.
#:
#: .. note::
#:    **Phase 3-E-38 이 세 자리를 지웠다** (16 → 13). 조건 거짓 ×2 는
#:    ``CANDIDATE_NOT_ELIGIBLE`` 로, 해결 계층의 출처 금지 ×1 은
#:    ``EXECUTION_FORBIDDEN`` 으로 바뀌었으므로 더 이상 이 코드를 쓰지
#:    않는다.
#:
#:    네 자리를 고쳤는데 **셋만 줄어든다** — 발동 계층의 출처 금지(M2-a)는
#:    ``_AVAILABILITY_REFUSAL`` **표 안의 튜플**이라 상태와 짝지은 결과
#:    자리로 세어지지 않았고, 애초에 이 목록에 없었다. 처음에 네 자리라고
#:    적었다가 실제 집합을 세어 고쳤다.
#:
#:    남은 13곳은 **맞는 ``ValidationCode`` 가 없어서** 그대로인
#:    것들이다 (구조 오류 · 예외 · 응답 거절).
#:
#:    이 테스트가 틀린 가정을 갖고 있던 것은 아니다 — 당시의 사실을 정확히
#:    세고 있었고, **고치면 깨지도록** 일부러 자리마다 고정했다. 그 설계가
#:    의도대로 작동해서 3-E-38 이 무엇을 바꿨는지 여기서 먼저 드러났다.
#: .. note::
#:    **두 자리가 밀렸다** (Phase 3-F-17).
#:
#:    ``engine/effect/resolution.py`` 499 → **520**, ``engine/payment.py``
#:    372 → **402**. 그 Phase 가 ``EffectResult`` · ``CostPaymentResult`` 의
#:    **class docstring** 에 actor provenance 복원 경로를 적었고, 두 docstring
#:    이 이 자리들보다 **위**에 있어서 아래가 전부 같은 만큼 밀렸다
#:    (+21 · +30).
#:
#:    **자리의 성격도, 개수도 바뀌지 않았다** — 13곳 그대로이고 짝지은 상태도
#:    그대로다. 문자열 리터럴을 지운 AST 가 전후 동일함이 그 증거다
#:    (:mod:`tests.test_result_actor_provenance_contract` 의 ``test_20``).
CONTRACT_VIOLATIONS = {
    # 🔴 Phase 6-B 가 ``ActionExecutor.__init__`` 에 ``journal`` 인자와
    # 설명(+23줄)을 더해 **그 아래가 밀렸다** (316 → 339). 거부 자리와
    # 짝지은 상태는 그대로다.
    ("engine/action_execution.py", 339, "ActionStatus.EXECUTION_ERROR"),
    # 🔴 **Phase 6-AB 보완5 에서 ``response.py`` 의 한 자리가 +9 밀렸다**
    # (476 → 485). 원인 하나다 — :data:`AFTER_FAST_WINDOW_RULE` 과 그
    # 설명(+9줄)이 이 자리보다 **위**에 들어갔다. 빈 체인의 빠른 효과
    # 기회를 닫는 이유를 응답 계층이 들고 있어야 하기 때문이다.
    #
    # **위반 13 · 적합 19 는 그대로다** — 자리의 성격도 개수도 짝지은
    # 상태도 바뀌지 않았고, 바뀐 것이 줄 번호뿐이라는 것이 그 증거다.
    # 🔴 **Phase 6-Z 에서 아홉 자리가 밀렸다** — 위반 13 · 적합 19 는
    # **그대로다.** 자리의 성격도 개수도 바뀌지 않았고, 바뀐 것이 줄
    # 번호뿐이라는 것이 그 증거다 (``PROSE_OCCURRENCES`` 의 표와 같은
    # 원인이다).
    #
    #   ``activation.py``       554 → 555 · 586 → 587 (+1 · import 한 줄)
    #   ``effect/executor.py``  520 → 576 (+56 · 프로토콜과 요청 모양)
    #                           662 → 724 · 675 → 737 · 798 → 860 (+62)
    #                           897 → 1060 · 1173 → 1336 · 1511 → 1674 (+163)
    # 🔴 **Phase 6-AB 에서 ``effect/executor.py`` 의 일곱 자리가 전부 +19
    # 밀렸다** (576 → 595 · 724 → 743 · 737 → 756 · 860 → 879 ·
    # 1060 → 1079 · 1336 → 1355 · 1674 → 1693).
    #
    # 원인 하나다 — ``EffectExecutor.chooser`` (읽기 전용 칸, +19줄) 가
    # ``journal`` 칸 바로 아래, 즉 이 자리들보다 **위**에 들어갔다. 사본이
    # 부모의 고르는 사람을 물려받으려면 그것을 꺼낼 수 있어야 한다.
    #
    # **위반 13 · 적합 19 는 그대로다** — 자리의 성격도 개수도 짝지은 상태도
    # 바뀌지 않았고, 바뀐 것이 줄 번호뿐이라는 것이 그 증거다 (3-F-17 ·
    # 6-L · 6-Z 와 같은 결).
    # 🔴 **Phase 6-AB 보완4 에서 아홉 자리가 전부 +11 밀렸다**
    # (``activation.py`` 555 → 566 · 587 → 598,
    #  ``effect/executor.py`` 595 → 606 · 743 → 754 · 756 → 767 ·
    #  879 → 890 · 1079 → 1090 · 1355 → 1366 · 1693 → 1704).
    #
    # 원인은 **읽기 전용 접근자 둘**이다 — ``EffectActivator.lookup`` 과
    # ``EffectImplementationRegistry.refs()``. 탐색 사본이 원본의 실행
    # 계약을 물려받으려면 그것을 꺼낼 수 있어야 한다 (보완4 ③).
    #
    # **위반 13 · 적합 19 는 그대로다** — 실측으로 확인했다. 자리의 성격도
    # 개수도 짝지은 상태도 바뀌지 않았고, 바뀐 것이 줄 번호뿐이다.
    # 🔴 **Phase 6-AB 보완8 마무리2 에서 그 둘이 +81 밀렸다**
    # (566 → 647 · 598 → 679). 원인 하나다 —
    # ``EffectActivator.can_activate_ignoring_targets`` 와 그 설명(+81줄)이
    # 이 자리들보다 **위**에 들어갔다. 대상과 무관한 발동 거절을 후보
    # 생성이 먼저 물을 수 있어야 하기 때문이다.
    #
    # **위반 13 · 적합 19 는 그대로다** — 자리의 성격도 개수도 짝지은
    # 상태도 바뀌지 않았고, 바뀐 것이 줄 번호뿐이다.
    ("engine/activation.py", 647, "ActivationStatus.INVALID_ACTION"),
    ("engine/activation.py", 679, "ActivationStatus.CHAIN_REFUSED"),
    ("engine/effect/executor.py", 606, "ResolutionStatus.EXECUTION_ERROR"),
    ("engine/effect/executor.py", 754, "ResolutionStatus.INVALID_OPERATION"),
    ("engine/effect/executor.py", 767, "ResolutionStatus.INVALID_OPERATION"),
    ("engine/effect/executor.py", 890, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/executor.py", 1090, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/executor.py", 1366, "ResolutionStatus.INVALID_CONTEXT"),
    # 🔴 **한 자리가 밀렸다** (Phase 6-L). ``engine/effect/executor.py``
    # 1336 → **1390**. 6-L 이 그 위에 ``_target_spec_of`` ·
    # ``_resolve_self_reference`` (+45) 와 ``_plan_card_operation`` 의
    # 자기 참조 분기 (+9) 를 넣어서 아래가 같은 만큼 밀렸다.
    #
    # **자리의 성격도, 개수도 바뀌지 않았다** — 13곳 그대로다. 6-L 이
    # 더한 거절 자리(``_resolve_self_reference``)는 이 목록에 들어오지
    # 않는다: 그쪽은 ``INFORMATION_UNAVAILABLE`` 을 쓴다 — "규칙을 아직
    # 옮기지 않았다" 가 아니라 "이 문맥에 그 카드가 없다" 이기 때문이다.
    ("engine/effect/executor.py", 1704, "ResolutionStatus.INVALID_CONTEXT"),
    ("engine/effect/resolution.py", 520, "ResolutionStatus.FORBIDDEN"),
    ("engine/payment.py", 402, "PaymentStatus.EXECUTION_ERROR"),
    # 🔴 보완6 에서 +6 밀렸다 (485 → 491) — ``act`` 가 ``stage`` 를
    # 키워드로 받게 되면서 그 자리보다 **위**에 줄이 늘었다. 위반 13 ·
    # 적합 19 는 그대로다.
    ("engine/response.py", 492, "ResponseOutcome.REFUSED"),
}

#: 같은 주사에서 **올바른** 자리 (모른다 쪽 상태와 짝지었다).
#: 🔴 17 → **19** (Phase 6-M). ``_movement_refusal`` 의 거절 둘이다.
#: **위반 쪽이 아니라 적합 쪽으로** 들어간 것이 요점이다 —
#: ``UNSUPPORTED_OPERATION`` 은 상태 enum 이 "모른다" 쪽으로 묶어 둔
#: 값이고, 두 거절은 실제로 "어디로 가는지 모른다" · "그 효과가
#: 불발되는지 모른다" 다.
CONFORMING_SITES = 19

#: 해결 계층의 "모른다" 쪽 상태 — `resolution.py` 의 docstring 을 읽어 모았다.
RESOLUTION_UNKNOWN_NAMES = {
    "UNKNOWN",
    "NOT_IMPLEMENTED",
    "CONDITION_UNKNOWN",
    "UNCHECKED_RULES",
    "UNSUPPORTED_OPERATION",
}

#: ``.code`` 를 **판단 입력**으로 읽는 production 자리 — 넷뿐이다.
CODE_READERS = {
    ("engine/trigger.py", "self.result.code is ValidationCode.EXECUTION_FORBIDDEN"),
    ("engine/trigger_chain.py", "verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED"),
    ("engine/trigger_chain.py", "verdict.code is not ValidationCode.OK"),
    ("agent/simulation.py", "step.code in _UNKNOWN_CODES"),
}


# ======================================================================
# 도구
# ======================================================================


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - 방어
        return "<?>"


def _reads_a_code(node: ast.Compare) -> bool:
    """
    이 비교가 ``.code`` 를 **``ValidationCode`` 와** 견주는가.

    문자열로 ``"ValidationCode"`` 를 찾으면 안 된다 — ``as`` 로 별명을 붙인
    import (``from engine.validation import ValidationCode as _VC``) 를
    놓친다. 실제로 그 구멍을 고의 위반으로 찾았다. 그래서 **멤버 이름**을
    ``ValidationCode.__members__`` 에 맞춰 보고, 집합 멤버십은 피연산자
    이름으로 본다.
    """
    text = _unparse(node)
    if ".code" not in text:
        return False
    members = set(ValidationCode.__members__)
    for side in [node.left, *node.comparators]:
        #: ``<무엇이든>.RULE_NOT_IMPLEMENTED`` 처럼 멤버 이름을 가리키는가.
        if isinstance(side, ast.Attribute) and side.attr in members:
            return True
        #: ``step.code in _UNKNOWN_CODES`` 처럼 코드 집합과 견주는가.
        name = (
            side.id
            if isinstance(side, ast.Name)
            else (side.attr if isinstance(side, ast.Attribute) else "")
        )
        if name.endswith("CODES"):
            return True
    return False


def production_files() -> list[pathlib.Path]:
    files = []
    for pkg in ("engine", "agent"):
        files.extend(sorted((PROJECT_ROOT / pkg).rglob("*.py")))
    return files


def mentions_code(node) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute) and inner.attr == "RULE_NOT_IMPLEMENTED":
            return True
    return False


def prose_lines(path: pathlib.Path) -> set[int]:
    """
    주석과 docstring 이 차지하는 줄 번호. AST 가 **코드로 보지 않는** 줄이다.

    주석은 ``#`` 로, docstring 은 문자열 ``Expr`` 노드의 줄 범위로 찾는다.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = {
        index + 1
        for index, line in enumerate(lines)
        if line.lstrip().startswith("#")
    }
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            end = node.end_lineno or node.lineno
            found.update(range(node.lineno, end + 1))
    return found


def code_sites() -> list[tuple[str, int, str]]:
    """
    ``RULE_NOT_IMPLEMENTED`` 가 **코드로** 등장하는 줄 전수.

    돌려주는 것은 ``(상대경로, 줄, 그 줄의 내용)``. 주석·docstring 은 뺀다.
    """
    sites = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        source = path.read_text(encoding="utf-8")
        if "RULE_NOT_IMPLEMENTED" not in source:
            continue
        prose = prose_lines(path)
        for index, line in enumerate(source.splitlines(), start=1):
            if "RULE_NOT_IMPLEMENTED" not in line:
                continue
            if index in prose:
                continue
            sites.append((rel, index, line.strip()))
    return sites


def status_paired_sites() -> tuple[list, list]:
    """
    결과 생성자의 **첫 인자(상태)** 와 ``RULE_NOT_IMPLEMENTED`` 를 짝지어,
    "모른다" 쪽인지 가른다.

    상태 enum 자신이 적어 둔 묶음을 쓴다 — 내가 새로 정하지 않는다
    (``engine.activation._UNKNOWN_STATUSES`` · ``RESOLUTION_UNKNOWN_NAMES``).
    """
    violations, conforming = [], []
    for rel in (
        "engine/activation.py",
        "engine/effect/executor.py",
        "engine/effect/resolution.py",
        "engine/response.py",
        "engine/action_execution.py",
        "engine/payment.py",
    ):
        tree = ast.parse(source_of(rel))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not any(
                isinstance(a, ast.Attribute) and a.attr == "RULE_NOT_IMPLEMENTED"
                for a in node.args
            ):
                continue
            first = node.args[0]
            if not isinstance(first, ast.Attribute):
                continue
            owner = _unparse(first.value)
            name = first.attr
            if owner == "ActivationStatus":
                unknown_side = getattr(ActivationStatus, name) in _UNKNOWN_STATUSES
            elif owner == "ResolutionStatus":
                unknown_side = name in RESOLUTION_UNKNOWN_NAMES
            elif owner == "ActionStatus" and name == "UNSUPPORTED_ACTION":
                #: "할 줄 모른다" — docstring 이 그렇게 적는다. 적합하다.
                unknown_side = True
            else:
                unknown_side = False
            row = (rel, first.lineno, f"{owner}.{name}")
            (conforming if unknown_side else violations).append(row)
    return violations, conforming


# ======================================================================
# A. enum 정의
# ======================================================================


def test_01_the_enum_itself_forbids_attaching_this_code_to_a_refusal():
    """
    **A (§20): enum 정의.**

    이 Phase 의 기준선은 내 의견이 아니라 **enum 자신의 docstring** 이다.

        "**이 엔진이 아직 못 한다.** 판이 어떻든 달라지지 않고, 코드가
        생겨야 풀린다. ``UNKNOWN`` 쪽의 코드다 — 확실한
        거부(``INVALID``)에 붙이지 않는다."

    그 문장을 고정한다. 문장이 바뀌면 이 Phase 의 판정 근거가 바뀐다.
    """
    tree = ast.parse(source_of("engine/validation.py"))
    doc = None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "ValidationCode"):
            continue
        body = node.body
        for index, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "RULE_NOT_IMPLEMENTED"
                    for t in stmt.targets
                )
            ):
                continue
            following = body[index + 1] if index + 1 < len(body) else None
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                doc = following.value.value
    assert doc is not None, "RULE_NOT_IMPLEMENTED 의 docstring 을 찾지 못했습니다."

    assert "이 엔진이 아직 못 한다" in doc
    assert "코드가 생겨야 풀린다" in doc
    #: **금지선.**
    assert "확실한 거부" in doc and "붙이지 않는다" in doc
    assert "``UNKNOWN`` 쪽의 코드다" in doc

    assert ValidationCode.RULE_NOT_IMPLEMENTED.value == "rule_not_implemented"
    #: 🔴 48 → **51** (Phase 6-AB 보완8). 흐름 거절을 규칙 거절로 적기 위해
    #: 셋을 더했다 — ``STAGE_FORBIDS_ACTION`` ·
    #: ``MANDATORY_TRIGGER_PENDING`` · ``TRIGGER_TIMING_MISSED``. 🔴 **셋 다
    #: ``INVALID``** 이므로 ``unknown_codes()`` 는 7 그대로다 — 모름을 늘려
    #: 문제를 덮은 것이 아니라 **모름이던 자리를 규칙 거절로 옮긴** 것이다.
    assert len(ValidationCode) == 51


def test_02_the_string_count_is_79_but_the_code_count_is_67():
    """
    **79 는 문자열 등장 수다.** 코드로 센 것은 67곳이고, 차이 12곳은
    주석·docstring 이다. 숫자를 그대로 믿지 않고 다시 센다.

    .. note::
       **숫자가 세 번 움직였고, 테스트 이름이 첫 숫자에 묶여 있었다.**

       75/69 (3-E-38 전) → 76/67 (3-E-38) → **79/67** (3-E-45). 함수 이름을
       숫자로 적어 둔 탓에 숫자가 변할 때마다 이름이 거짓이 된다 — 이번에
       이름도 맞췄다.

       **코드 수 67 은 3-E-45 에서 바뀌지 않았다.** 산문만 셋 늘었다
       (``CODE_OCCURRENCES`` 의 설명 참조).
    """
    strings = 0
    for path in production_files():
        strings += path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
    assert strings == STRING_OCCURRENCES

    sites = code_sites()
    assert len(sites) == CODE_OCCURRENCES
    #: 🔴 15 → **17** (보완6) — 늘어난 둘은 산문이다 (``_refusal`` ·
    #: ``_refusal_verdict`` 의 설명).
    #: 🔴 17 → **19** (보완7) — 늘어난 둘도 산문이다
    #: (``ActivationTiming.responding_kind`` · ``verified_activation_kind``
    #: 의 설명). 코드 수는 74 그대로이고, 그 차이가 이 등식이 지키는
    #: 사실이다: **문자열이 늘어도 코드가 늘지 않았다.**
    #: 🔴 19 → **30** (보완8). 늘어난 11은 전부 산문이다 — 왜 그 자리가
    #: 모름이고 왜 다른 자리가 규칙 거절인지를 적었다.
    #: 🔴 30 → **31** (보완8 마무리). 늘어난 하나도 산문이다
    #: (``_refusal_sentence`` 의 설명). 코드 수는 80 그대로다.
    assert strings - len(sites) == 31

    #: 산문 자리를 정확히 집는다 — 어디가 설명이고 어디가 코드인지 고정한다.
    prose = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        source = path.read_text(encoding="utf-8")
        if "RULE_NOT_IMPLEMENTED" not in source:
            continue
        lines = prose_lines(path)
        for index, line in enumerate(source.splitlines(), start=1):
            if "RULE_NOT_IMPLEMENTED" in line and index in lines:
                prose.add((rel, index))
    assert prose == PROSE_OCCURRENCES


# ======================================================================
# B · C. ValidationResult / missing_rule 매핑
# ======================================================================


def test_03_only_unknown_can_carry_this_code_in_validation_result():
    """
    **B (§20): ``ValidationResult`` 매핑.**

    ``ValidationResult.invalid(...)`` 에 이 코드를 넣는 production 호출이
    **0건**이다. 그리고 ``missing_rule`` 을 받는 생성자는 ``unknown`` 뿐이다
    — 구조가 금지선을 지킨다.
    """
    offenders = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"invalid", "valid"}
            ):
                continue
            if mentions_code(node):
                offenders.append(f"{rel}:{node.lineno} {_unparse(node)[:70]}")
    assert offenders == [], offenders

    tree = ast.parse(source_of("engine/validation.py"))
    takes_missing_rule = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            arg.arg == "missing_rule"
            for arg in list(node.args.args) + list(node.args.kwonlyargs)
        )
    }
    assert takes_missing_rule == {"unknown"}


def test_04_the_code_and_a_missing_rule_are_not_the_same_fact():
    """
    **C (§20): ``missing_rule`` 매핑.**

    "``missing_rule`` 이 있는 결과" 와 "코드가 ``RULE_NOT_IMPLEMENTED`` 인
    결과" 는 **같지 않다.** 양방향으로 반례를 만든다.
    """
    #: 코드는 있는데 규칙 이름이 없다 — 흔하다.
    bare = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "까닭 없이")
    assert bare.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert bare.missing_rule is None

    #: 규칙 이름은 있는데 코드가 다르다.
    other = ValidationResult.unknown(
        ValidationCode.INFORMATION_UNAVAILABLE, "정보가 없다", missing_rule="어떤 규칙"
    )
    assert other.missing_rule == "어떤 규칙"
    assert other.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 실제 production 에서도 그렇다 — "모른다" 쪽은 코드가 있고 규칙 이름이
    #: 없을 수 있다.
    #:
    #: .. note::
    #:    원래 이 자리는 **조건 거짓**으로 그것을 보였다. 3-E-38 이 조건
    #:    거짓의 코드를 ``CANDIDATE_NOT_ELIGIBLE`` 로 바로잡았으므로, 같은
    #:    사실을 보이려면 아직 ``RULE_NOT_IMPLEMENTED`` 를 쓰는 자리를
    #:    골라야 한다 — 정의 미등록이 그것이다.
    bare_rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    assert bare_rule.code is ValidationCode.RULE_NOT_IMPLEMENTED

    #: 그리고 조건 거짓은 이제 **다른 코드**다.
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert false.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert false.missing is None


# ======================================================================
# D. status / code 정합성 — **이 Phase 의 중심 측정**
# ======================================================================


def test_05_thirteen_result_sites_attach_this_code_to_a_definite_refusal():
    """
    **D (§20): status/code 정합성 — enum 의 금지선을 어기는 자리를 센다.**

    상태가 "모른다" 쪽인지는 **상태 enum 자신이 적어 둔 묶음**으로 가른다
    (``engine.activation._UNKNOWN_STATUSES``). 내가 새 기준을 만들지 않는다.

    결과: **13곳 위반 · 17곳 적합** (3-E-38 전에는 16곳이었다). 목록을
    그대로 고정한다 — 늘어나면
    여기서 깨지고, 고쳐서 줄어도 여기서 깨진다. 어느 쪽이든 신호다.
    """
    violations, conforming = status_paired_sites()
    assert set(violations) == CONTRACT_VIOLATIONS
    #: 16 → **13** (3-E-38 이 M1 ×2 와 해결 계층 M2-b ×1 을 지웠다. 발동
    #: 계층 M2-a 는 표 안의 튜플이라 이 목록에 없었고, ``resolution.py`` 의
    #: dormant 한 출처 금지 1곳은 범위 밖이라 남겼다).
    assert len(violations) == 13
    assert len(conforming) == CONFORMING_SITES

    #: 위반 쪽 상태는 **하나도** ``_UNKNOWN_STATUSES`` 에 없다.
    for _, _, status in violations:
        owner, name = status.split(".")
        if owner == "ActivationStatus":
            assert getattr(ActivationStatus, name) not in _UNKNOWN_STATUSES


def test_06_the_four_combinations_the_prompt_asks_about():
    """
    **§7 이 지목한 네 조합의 실재 여부.**

    | 조합 | 실재? |
    |---|---|
    | ``RULE_NOT_IMPLEMENTED`` + ``UNKNOWN`` | **있다** (정상) |
    | ``RULE_NOT_IMPLEMENTED`` + ``INVALID`` | **ValidationResult 에는 없다** |
    | ``RULE_NOT_IMPLEMENTED`` + ``VALID``/``ELIGIBLE`` | **없다** |
    | ``RULE_NOT_IMPLEMENTED`` + ``missing_rule=None`` | **있다** (정상) |
    """
    #: UNKNOWN + 코드 — 정상.
    unknown = ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, "")
    assert unknown.validity is ActionValidity.UNKNOWN
    assert unknown.permits_execution is False

    #: VALID 와 함께는 **만들 수 없다** — ``valid()`` 가 코드를 받지 않는다.
    assert ValidationResult.valid("되었다").code is ValidationCode.OK

    #: ELIGIBLE 과 함께도 없다 — 트리거 계층에서 적격은 ``OK`` 다.
    state = new_state()
    from engine.game_state_view import GameStateView
    from engine.effect import EffectDefinitionRegistry

    definition = watched_definition(activation=None)
    collection = TriggerCollector(
        GameStateView.from_state(state, viewer=MINE),
        TriggerRegistry((watching(None),)),
        definitions=EffectDefinitionRegistry((definition,)),
    ).collect(drawn_event())
    for candidate in collection:
        assert candidate.status is TriggerStatus.ELIGIBLE
        assert candidate.code is ValidationCode.OK
        assert candidate.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: missing_rule=None 과 함께는 흔하다 (``test_04``).
    assert unknown.missing_rule is None


def test_07_eight_dataclasses_use_this_code_as_a_conservative_default():
    """
    **생성이 아닌 자리 — ``code`` 필드의 기본값 8곳.**

    "아무도 말하지 않으면 이유는 '우리가 못 한다'" 라는 **보수적 기본값**
    이다. 판정이 아니라 자리표시이므로 금지선을 어기지 않는다.
    """
    owners = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "code"
                    and stmt.value is not None
                    and mentions_code(stmt.value)
                ):
                    owners.add((rel, node.name))
    assert owners == FIELD_DEFAULT_OWNERS
    assert len(owners) == 8

    #: 기본값이 실제로 그 값이다.
    from engine.activation import ActivationResult
    from engine.effect.resolution import EffectResult

    for cls in (ActivationResult, EffectResult):
        field = next(f for f in dataclasses.fields(cls) if f.name == "code")
        assert field.default is ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# E · F · G · H. 네 가지 구분
# ======================================================================


def test_08_unknown_and_this_code_are_different_axes():
    """
    **E (§20): ``UNKNOWN`` 과의 분리.**

    상태와 코드는 **다른 축**이다. 같은 ``CONDITION_UNKNOWN`` 상태에 두
    코드가 붙을 수 있고, 같은 코드가 여러 상태에 붙는다.
    """
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert rule.status is info.status is ActivationStatus.CONDITION_UNKNOWN
    assert rule.code is not info.code

    #: 거꾸로 — 같은 코드가 **다른 상태**에 붙는다 (바로 이것이 §5 의 질문).
    #:
    #: .. note::
    #:    원래 이 자리는 **조건 거짓**을 짝으로 썼다. 3-E-38 이 조건 거짓을
    #:    ``CANDIDATE_NOT_ELIGIBLE`` 로 바로잡았으므로, 같은 코드가 여러
    #:    상태에 붙는다는 사실은 **남아 있는** 자리로 보인다 —
    #:    ``CONDITION_UNKNOWN`` 과 ``NOT_IMPLEMENTED`` 가 그것이다.
    from engine.chain import Chain
    from engine.effect import EffectDefinitionRegistry, EffectImplementationRegistry

    unregistered = __import__(
        "engine.activation", fromlist=["EffectActivator"]
    ).EffectActivator(EffectDefinitionRegistry(()), EffectImplementationRegistry(()))
    definition = synthetic(activation=None)
    state = new_state()
    not_implemented = unregistered.activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE,
            source=state.player(MINE).monster_zone[0].instance_id,
            effect_ref=definition.effect_ref,
        ),
        authorization=ValidationResult.valid("테스트가 허가했다"),
    )
    assert not_implemented.code is rule.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert not_implemented.status is ActivationStatus.NOT_IMPLEMENTED
    assert not_implemented.status is not rule.status

    #: 그리고 조건 거짓은 이제 **다른 코드**다 (3-E-38).
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert false.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert false.code is not rule.code

    missing = activate(new_state(), synthetic(activation=None))
    assert missing.status is ActivationStatus.ACTIVATED


def test_09_information_unavailable_is_still_separate():
    """
    **F (§20): ``INFORMATION_UNAVAILABLE`` 과의 분리.**

    발동·해결·트리거·타이밍 네 자리가 모두 ``missing_rules()`` 로 가른다.
    가르는 자리를 AST 로 센다 — ``IfExp`` 다섯 곳.
    """
    splits = []
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.IfExp) and mentions_code(node):
                text = _unparse(node)
                if "INFORMATION_UNAVAILABLE" in text:
                    splits.append(rel)
    assert sorted(splits) == [
        "engine/activation.py",
        "engine/activation_timing.py",
        "engine/effect/executor.py",
        "engine/trigger.py",
        "engine/trigger.py",
    ]

    assert activate(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE
    assert resolve(
        new_state(), synthetic(activation=IsMonster(InstanceId(9999)))
    ).code is ValidationCode.INFORMATION_UNAVAILABLE


def test_10_execution_forbidden_is_now_used_by_the_effect_layers_too():
    """
    **G (§20): ``EXECUTION_FORBIDDEN`` 과의 분리 — 그리고 발견 M2.**

    출처 금지(ADR-004)는 ``EXECUTION_FORBIDDEN`` 이 정확하고, 트리거 계층은
    3-E-26 에서 그렇게 고쳤다. **발동·해결 계층은 아직 ``RULE_NOT_IMPLEMENTED``
    를 쓴다.**

    고치지 않는다 — 현재 상태를 고정해서 바뀌면 알게 한다.
    """
    assert ValidationCode.EXECUTION_FORBIDDEN is not (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )

    forbidden = synthetic(
        activation=None, provenance=EffectProvenance.text_derived("공식 텍스트에서 유추")
    )
    activated = activate(new_state(), forbidden)
    resolved = resolve(new_state(), forbidden)

    #: 상태는 정확하다.
    assert activated.status is ActivationStatus.FORBIDDEN
    assert resolved.status is ResolutionStatus.FORBIDDEN

    #: .. note::
    #:    **Phase 3-E-38 이 고쳤다 (M2).** 원래 이 테스트는 "발동·해결 계층은
    #:    아직 ``RULE_NOT_IMPLEMENTED`` 를 쓴다" 를 고정했고 "고치지 않는다 —
    #:    현재 상태를 고정해서 바뀌면 알게 한다" 고 적었다. 바로 그 설계대로
    #:    바뀌었을 때 알려 주었으므로, 이제 **고쳐진 사실**을 고정한다.
    assert activated.code is ValidationCode.EXECUTION_FORBIDDEN
    assert resolved.code is ValidationCode.EXECUTION_FORBIDDEN
    assert activated.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 이제 **세 계층이 같은 코드**를 쓴다 — 트리거 · 발동 · 해결.
    for rel in (
        "engine/trigger.py",
        "engine/activation.py",
        "engine/effect/executor.py",
    ):
        assert "ValidationCode.EXECUTION_FORBIDDEN" in source_of(rel), rel
    #: 그 코드를 **읽는** 자리는 여전히 트리거 계층에만 있다.
    assert GateVerdict.forbids.__doc__ is not None


def test_11_candidate_not_eligible_is_now_used_by_the_effect_layers_too():
    """
    **H (§20): ``CANDIDATE_NOT_ELIGIBLE`` 과의 분리 — 그리고 발견 M1.**

    조건을 끝까지 보고 **거짓**을 받은 자리는 확실한 거부다. 트리거 계층은
    3-E-26 에서 ``CANDIDATE_NOT_ELIGIBLE`` 로 고쳤고, 그 이유를 주석에
    적어 두었다. **발동·해결 계층은 아직 ``RULE_NOT_IMPLEMENTED`` 다.**
    """
    false = synthetic(activation=Always(ConditionResult.FALSE))
    activated = activate(new_state(), false)
    resolved = resolve(new_state(), false)

    assert activated.status is ActivationStatus.CONDITION_FALSE
    assert resolved.status is ResolutionStatus.CONDITION_FALSE

    #: .. note::
    #:    **Phase 3-E-38 이 고쳤다 (M1).** 원래 이 테스트는 "조건 거짓인데
    #:    '엔진이 못 한다' 고 적는다" 를 고정했다. 그 자리가 바뀌었으므로
    #:    **고쳐진 사실**을 고정한다 — 세 계층이 같은 코드를 쓴다.
    assert activated.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert resolved.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert activated.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 트리거 계층이 먼저 쓰던 코드와 **같아졌다** (3-E-26 → 3-E-38).
    trigger_source = source_of("engine/trigger.py")
    assert "code=ValidationCode.CANDIDATE_NOT_ELIGIBLE" in trigger_source
    assert "확실한 거부이고 미구현이 아니다" in trigger_source
    assert "판정과 이유가 어긋난다" in trigger_source
    #: 그리고 발동·해결 계층도 같은 말을 적는다.
    for rel in ("engine/activation.py", "engine/effect/executor.py"):
        assert "확실한 거부이고 미구현이 아니다" in source_of(rel), rel


# ======================================================================
# I · J · K · L · M. 계층별
# ======================================================================


def test_12_the_trigger_layer_uses_this_code_only_on_unknown():
    """
    **I (§20): 트리거 계층.**

    ``TriggerCollector`` 와 ``TriggerEligibilityJudge`` 는 이 코드를
    ``UNKNOWN`` 에만 쓴다. 3-E-26/27 이 세운 것이 그대로다.
    """
    from engine.game_state_view import GameStateView
    from engine.effect import EffectDefinitionRegistry

    view = GameStateView.from_state(new_state(), viewer=MINE)

    #: 조건 거짓 → ``INELIGIBLE`` + ``CANDIDATE_NOT_ELIGIBLE``.
    refused = TriggerCollector(
        view, TriggerRegistry((watching(Always(ConditionResult.FALSE)),))
    ).collect(drawn_event())
    for candidate in refused:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE

    #: 규칙 없음 → ``UNKNOWN`` + ``RULE_NOT_IMPLEMENTED``.
    undecided = TriggerCollector(
        view, TriggerRegistry((watching(UnimplementedRule("없는 규칙")),))
    ).collect(drawn_event())
    for candidate in undecided:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED

    #: 정의 미등록 → ``UNKNOWN`` + 같은 코드 (다른 까닭, 같은 쪽).
    missing = TriggerCollector(
        view,
        TriggerRegistry((watching(None),)),
        definitions=EffectDefinitionRegistry(()),
    ).collect(drawn_event())
    for candidate in missing:
        assert candidate.status is TriggerStatus.UNKNOWN
        assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED


@requires_official_db
@pytest.mark.real_card
def test_13_the_action_validator_uses_this_code_only_on_unknown(repository):
    """
    **J (§20): ``ActionValidator``.**

    종류마다 코드가 같은 뜻인지 실제 판으로 확인한다. ``UNKNOWN`` 에만
    붙고, 확실한 위반은 **다른 코드**를 받는다.
    """
    deck = [card.id for card in list(repository.all_cards())[:12]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=5)
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    validator = ActionValidator(duel.view(seat))
    source = duel.state.player(seat).hand[0].instance_id

    seen: dict[str, tuple[str, str]] = {}
    for build in (
        PlayerAction.normal_summon,
        PlayerAction.set_monster,
        PlayerAction.set_spell_trap,
        PlayerAction.activate_card,
        PlayerAction.special_summon,
    ):
        action = build(actor=seat, source=source)
        verdict = validator.validate(action)
        seen[action.kind.value] = (verdict.validity.value, verdict.code.value)
        if verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED:
            #: **금지선이 지켜진다** — 이 코드는 UNKNOWN 에만 붙는다.
            assert verdict.validity is ActionValidity.UNKNOWN
        if verdict.validity is ActionValidity.INVALID:
            assert verdict.code is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 종류마다 **다른** 답이 나온다 — 코드가 한 뜻으로 뭉개지지 않는다.
    assert len(set(seen.values())) >= 2


def test_14_the_effect_layer_mixes_two_meanings_in_one_code():
    """
    **K (§20): 효과 실행 계층 — 가장 많이 쓰는 자리 (22곳).**

    같은 코드가 세 가지에 붙는다.

    - 조작 종류 미지원 (``UNSUPPORTED_OPERATION``) → **정확**
    - 문맥 불일치 (``INVALID_CONTEXT``) → 구조 오류, 미구현이 아니다
    - 조건 거짓 (``CONDITION_FALSE``) → 확실한 거부

    세 가지가 한 코드를 공유한다는 사실을 고정한다.
    """
    violations, conforming = status_paired_sites()
    executor_violations = {
        status for rel, _, status in violations if rel == "engine/effect/executor.py"
    }
    executor_conforming = {
        status for rel, _, status in conforming if rel == "engine/effect/executor.py"
    }
    #: .. note::
    #:    3-E-38 이 ``FORBIDDEN`` 과 ``CONDITION_FALSE`` 를 지웠다. 남은 셋은
    #:    **맞는 ``ValidationCode`` 가 없어서** 그대로다.
    assert executor_violations == {
        "ResolutionStatus.EXECUTION_ERROR",
        "ResolutionStatus.INVALID_OPERATION",
        "ResolutionStatus.INVALID_CONTEXT",
    }
    assert executor_conforming == {
        "ResolutionStatus.UNCHECKED_RULES",
        "ResolutionStatus.UNSUPPORTED_OPERATION",
        "ResolutionStatus.UNKNOWN",
        "ResolutionStatus.NOT_IMPLEMENTED",
    }
    #: 두 묶음이 겹치지 않는다 — 분류가 모호하지 않다.
    assert executor_violations & executor_conforming == set()


def test_15_the_cost_layer_has_its_own_code_and_does_not_borrow_this_one():
    """
    **L (§20): 비용 계층.**

    비용은 ``COST_NOT_IMPLEMENTED`` 를 쓴다 — 이 코드를 빌리지 않는다.
    ``engine/cost/`` 에 ``RULE_NOT_IMPLEMENTED`` 가 **하나도 없다.**
    """
    for path in sorted((PROJECT_ROOT / "engine" / "cost").rglob("*.py")):
        assert "RULE_NOT_IMPLEMENTED" not in path.read_text(encoding="utf-8"), path

    assert ValidationCode.COST_NOT_IMPLEMENTED is not (
        ValidationCode.RULE_NOT_IMPLEMENTED
    )
    #: 다만 지불 **실행** 쪽(``engine/payment.py``)은 예외 처리에서 쓴다.
    assert "RULE_NOT_IMPLEMENTED" in source_of("engine/payment.py")


def test_16_the_targeting_layer_uses_candidate_codes_not_this_one():
    """
    **M (§20): 대상 계층.**

    대상 선택은 ``CANDIDATE_NOT_ELIGIBLE`` · ``TOO_FEW_SELECTED`` 같은
    자기 코드를 쓴다. ``engine/effect/targeting.py`` 에 이 코드가 **없다.**
    """
    targeting = PROJECT_ROOT / "engine" / "effect" / "targeting.py"
    if not targeting.is_file():  # pragma: no cover - 경로가 바뀌면 알려 준다
        pytest.fail("engine/effect/targeting.py 가 없습니다 — 경로를 다시 확인하세요.")
    source = targeting.read_text(encoding="utf-8")
    assert "RULE_NOT_IMPLEMENTED" not in source
    assert "CANDIDATE_NOT_ELIGIBLE" in source


# ======================================================================
# N · O. production 도달 / dormant
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_17_the_misclassified_code_reaches_the_duel_boundary(repository):
    """
    **N (§20): production 도달.**

    ``Duel.apply`` 가 발동기의 코드를 **그대로** ``DuelStep.code`` 에 넣는다.
    즉 오분류가 공개 경계까지 간다.

    🔴 **정정 (Phase 6-AB 보완8 마무리).** 이 테스트는 ``special_summon``
    거절의 문장이 *"{종류} 는 지금 허가된 행위가 아닙니다"* 라고 고정하고
    있었다 — 그것은 ``Duel._refusal`` 의 **마지막 기본 문장**이고, "목록에
    없다" 밖에 말하지 못한다. 보완8 이 ``_rule_verdict`` 를 끼운 뒤로는
    규칙 검증기가 **먼저** 답한다. 실측::

        ActionValidator.validate(special_summon)
        → UNKNOWN / RULE_NOT_IMPLEMENTED
          missing_rule="special-summon-condition (카드마다 다르다)"

    그래서 아래는 그 **더 좁은 답**을 고정한다. 코드는 여전히
    ``RULE_NOT_IMPLEMENTED`` 이고 — 특수 소환 조건이 실제로 이 저장소에
    없으므로 이번에는 **옳은 분류**다 — 바뀐 것은 "왜" 뿐이다. 느슨하게
    풀지 않고, 기본 문장이 아직 살아 있다는 것도 함께 고정한다.
    """
    duel = Duel.start(
        repository,
        decks=([card.id for card in list(repository.all_cards())[:12]],) * 2,
        seed=5,
    )
    while duel.advance() is not None:
        pass
    seat = duel.to_act
    source = duel.state.player(seat).hand[0].instance_id

    before = duel.state.state_hash()
    step = duel.apply(PlayerAction.special_summon(actor=seat, source=source))
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    #: 🔴 규칙 검증기의 말이 그대로 왔다 — 목록 멤버십 문장이 아니다.
    assert step.reason.startswith("아직 구현하지 않은 규칙이 걸려 있습니다.")
    #: 🔴 그리고 **무엇이 없어서 모르는가**가 결과까지 따라왔다.
    assert "[special-summon-condition (카드마다 다르다)]" in step.reason
    assert "허가된 행위가 아닙니다" not in step.reason
    assert duel.state.state_hash() == before

    #: 발동기의 코드가 그대로 흘러간다는 것을 소스로 확인한다.
    duel_source = source_of("engine/duel.py")
    assert "DuelStep(action, False, activated.code, activated.reason)" in duel_source
    #: 🔴 기본 문장은 **지우지 않았다** — 남은 자리를 숨기지 않기 위해서다.
    assert "는 지금 허가된 행위가 아닙니다." in duel_source


def test_18_the_unimplemented_resolver_sites_are_dormant():
    """
    **O (§20): dormant 구분.**

    ``engine/effect/resolution.py`` 의 네 자리는 ``UnimplementedResolver``
    안에 있고, 그 클래스는 **production 에서 한 번도 만들어지지 않는다.**
    (생성처 전부 ``tests/``.) 그래서 거기의 M2 패턴은 dormant 다.
    """
    production, tests = [], []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel.startswith((".venv", "build")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 방어
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "UnimplementedResolver"
            ):
                (tests if rel.startswith("tests/") else production).append(
                    f"{rel}:{node.lineno}"
                )
    assert production == []
    assert len(tests) > 10

    #: 그런데 소비자 계약은 살아 있다 — 받으면 올바른 상태를 돌려준다.
    assert issubclass(UnimplementedResolver, object)
    #: 마지막 자리는 소스 자신이 "여기까지 오는 경우는 아직 없다" 고 적는다.
    assert "여기까지 오는 경우는 아직 없다" in source_of("engine/effect/resolution.py")


def test_19_the_three_exception_handlers_are_defensive_not_normal_paths():
    """
    **O (§20): dormant 의 다른 종류 — 예외 처리.**

    세 자리(``action_execution`` · ``effect/executor`` · ``payment``)는
    ``except Exception`` 안이고 전부 ``# pragma: no cover - 일어나서는 안
    된다`` 가 붙어 있다. **예외는 미구현이 아니다** — 그러나 더 정확한
    ``ValidationCode`` 가 enum 에 없다.
    """
    for rel in (
        "engine/action_execution.py",
        "engine/effect/executor.py",
        "engine/payment.py",
    ):
        source = source_of(rel)
        assert "except Exception as error:  # pragma: no cover" in source
        assert "일어나서는 안 된다" in source

    #: 더 정확한 코드가 **없다** — 그래서 고치려면 enum 을 늘려야 한다.
    assert "EXECUTION_ERROR" not in ValidationCode.__members__
    assert "UNSUPPORTED_OPERATION" not in ValidationCode.__members__
    assert "INVALID_CONTEXT" not in ValidationCode.__members__


# ======================================================================
# P · Q · R. AI / Simulation / Hidden information
# ======================================================================


def test_20_only_four_production_sites_read_the_code_as_a_decision():
    """
    **P (§20): AI/Search 영향 — 먼저 "누가 코드를 읽는가" 를 센다.**

    ``.code`` 를 **판단 입력**으로 읽는 production 자리는 넷뿐이다. 넷을
    고정한다 — 다섯 번째가 생기면 오분류가 판정을 바꿀 수 있으므로 여기서
    깨져야 한다.
    """
    readers = set()
    for path in production_files():
        rel = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not _reads_a_code(node):
                continue
            readers.add((rel, _unparse(node)))
    assert readers == CODE_READERS
    assert len(readers) == 4


def test_21_the_ai_sees_unknown_instead_of_refused_but_ranks_them_the_same():
    """
    **Q (§20): ``SimulationStatus``.**

    오분류의 **유일한 관측 가능한 결과**가 여기다 — 확실한 거부가
    ``SimulationStatus.UNKNOWN`` 으로 읽힌다 (``REFUSED`` 가 아니다).

    그런데 **줄 세우기가 같다**: 둘 다 점수가 ``None`` 이고 같은
    ``ordering_key`` 를 낸다. 그래서 AI 의 **선택**은 바뀌지 않는다 —
    보고만 거칠어진다.
    """
    assert ValidationCode.RULE_NOT_IMPLEMENTED in _UNKNOWN_CODES
    #: 정확한 코드였다면 ``REFUSED`` 로 갔을 것이다.
    assert ValidationCode.CANDIDATE_NOT_ELIGIBLE not in _UNKNOWN_CODES
    assert ValidationCode.EXECUTION_FORBIDDEN not in _UNKNOWN_CODES

    action = PlayerAction.passing(actor=MINE)
    unknown = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    refused = SearchCandidate(action=action, status=SimulationStatus.REFUSED)
    assert unknown.value is refused.value is None
    assert unknown.ordering_key() == refused.ordering_key()
    assert unknown.ordering_key()[0] == 1

    #: 그리고 원래 코드가 보존된다 — 유실이 아니다.
    carried = SimulationResult(
        action=action,
        status=SimulationStatus.UNKNOWN,
        viewer=MINE,
        code=ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert carried.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert carried.future is None

    #: ``agent/`` 는 이 코드를 **이름으로 적지 않는다** (Phase 3-E-40).
    #:
    #: 3-E-36 이 이 줄을 쓸 때는 ``agent/simulation.py`` 의
    #: ``_UNKNOWN_CODES`` 리터럴에 한 번 적혀 있었다(=1). 3-E-40 이 그 사본을
    #: 없애고 ``engine.validation`` 의 policy 에서 파생하게 했으므로 **0** 이다.
    #: 이 테스트가 말하려던 것("에이전트가 이 코드를 거의 읽지 않는다")은
    #: 더 강하게 성립한다 — 이제 아예 적지 않는다.
    hits = sum(
        path.read_text(encoding="utf-8").count("RULE_NOT_IMPLEMENTED")
        for path in sorted((PROJECT_ROOT / "agent").rglob("*.py"))
    )
    assert hits == 0


def test_22_hidden_information_never_becomes_this_code():
    """
    **R (§20): hidden information.**

    가려진 정보는 ``HIDDEN_CARD`` · ``INFORMATION_UNAVAILABLE`` ·
    ``CARD_DEFINITION_UNAVAILABLE`` 로 가고 이 코드로 바뀌지 않는다.
    """
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE
    assert info.code is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert info.unchecked and "관측에 보이지 않음" in info.unchecked[0]

    #: 세 "정보 없음" 코드가 모두 따로 있다.
    for name in (
        "HIDDEN_CARD",
        "INFORMATION_UNAVAILABLE",
        "CARD_DEFINITION_UNAVAILABLE",
        "EFFECT_LIST_UNRELIABLE",
    ):
        assert name in ValidationCode.__members__
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED


# ======================================================================
# S. safety invariant (§19 의 열 항목)
# ======================================================================


def test_23_all_ten_safety_invariants_hold():
    """
    **S (§20) · §19: 열 가지 invariant.**

    오분류가 있어도 **안전선은 전부 지켜진다** — 그것이 이 Phase 가
    ``D. MISCLASSIFIED_PRODUCTION`` 을 고르지 않는 근거다.
    """
    #: 1 · 6 — UNKNOWN 과 FALSE 가 서로 바뀌지 않는다.
    rule = activate(new_state(), synthetic(activation=UnimplementedRule("없는 규칙")))
    false = activate(new_state(), synthetic(activation=Always(ConditionResult.FALSE)))
    assert rule.status is ActivationStatus.CONDITION_UNKNOWN
    assert false.status is ActivationStatus.CONDITION_FALSE
    assert rule.status is not false.status

    #: 2 · 3 — 까닭이 섞이지 않는다.
    info = activate(new_state(), synthetic(activation=IsMonster(InstanceId(9999))))
    assert info.code is ValidationCode.INFORMATION_UNAVAILABLE

    #: 4 · 5 — 코드가 서로 다른 멤버다.
    for name in ("EXECUTION_FORBIDDEN", "CANDIDATE_NOT_ELIGIBLE"):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 7 · 10 — 패배도 0점도 아니다.
    action = PlayerAction.passing(actor=MINE)
    candidate = SearchCandidate(action=action, status=SimulationStatus.UNKNOWN)
    assert candidate.value is None
    assert candidate.comparable is False

    #: 8 — 허가가 되지 않는다.
    assert (
        ValidationResult.unknown(
            ValidationCode.RULE_NOT_IMPLEMENTED, ""
        ).permits_execution
        is False
    )
    for result in (rule, false, info):
        assert result.status is not ActivationStatus.ACTIVATED
        assert len(result.chain) == 0

    #: 9 — 가려진 정보가 이 코드로 바뀌지 않는다 (``test_22``).
    assert ValidationCode.HIDDEN_CARD is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_24_a_misclassified_code_never_changes_the_board():
    """
    **§19-5 · §19-6 을 판으로 확인한다.** 오분류된 코드를 받은 시도는
    어느 쪽도 판을 바꾸지 않는다.
    """
    for activation in (
        Always(ConditionResult.FALSE),
        UnimplementedRule("없는 규칙"),
        IsMonster(InstanceId(9999)),
    ):
        state = new_state()
        before = state.state_hash()
        result = activate(state, synthetic(activation=activation))
        assert result.status is not ActivationStatus.ACTIVATED
        assert state.state_hash() == before
        assert result.deltas == ()


# ======================================================================
# T. 실제 corpus · regression
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_25_real_corpus_sample_of_this_code(repository):
    """
    **T (§20): 실제 corpus 사례.**

    실제 카드로 한 판을 돌리고, 받아들여진 수와 거절된 수의 코드를 모은다.

    🔴 **정정 (Phase 6-AB 보완8 마무리).** 이 테스트는 *"``WithheldAction``
    은 코드를 들고 있지 않다 — 필드가 ``kind`` · ``reason`` · ``missing``
    뿐이다"* 를 3-E-28 의 실측으로 적고 ``assert not hasattr(withheld,
    "code")`` 로 고정하고 있었다. 그 **없음이 BLOCKER-F7-1 의 내용**이었다:
    읽는 쪽이 "규칙이 막았다" 와 "판정 근거가 없다" 를 문장으로 짐작해야
    했다. 보완8 이 ``code`` 를 **필수 필드**로 만들었으므로 이제는 그 반대를
    고정한다 — 그리고 느슨하게 지우지 않고, 코드와 ``missing`` 이 **서로
    모순되지 않는다**는 더 강한 사실까지 함께 센다.

    🔴 식별자는 여전히 없다 (3-E-41 의 불변식). ``code`` 는 규칙 이름이고
    ``scope`` 는 개수다 — 어느 카드인지는 들어가지 않는다.
    """
    deck = [card.id for card in list(repository.all_cards())[:16]]
    duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=11)
    seen_codes: set[ValidationCode] = set()
    withheld_missing: set[str] = set()
    withheld_codes: set[ValidationCode] = set()

    for _ in range(80):
        if duel.is_over:
            break
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions()
        for withheld in legal.withheld:
            #: 🔴 이제 코드를 들고 있다 — 짐작할 필요가 없다.
            assert isinstance(withheld.code, ValidationCode)
            withheld_codes.add(withheld.code)
            #: 🔴 그리고 코드와 ``missing`` 이 서로 모순되지 않는다.
            if withheld.validity is ActionValidity.UNKNOWN:
                assert withheld.missing, withheld
            else:
                assert withheld.validity is ActionValidity.INVALID, withheld
                assert withheld.missing is None, withheld
            #: 🔴 식별자는 없다 (3-E-41).
            for forbidden in ("source", "action", "instance_id"):
                assert not hasattr(withheld, forbidden), forbidden
            if withheld.missing:
                withheld_missing.add(withheld.missing)
        if not legal.allowed:
            break
        #: 허가된 수 하나와 **허가되지 않은 수 하나**를 둘 다 넣어 본다.
        seen_codes.add(duel.apply(legal.allowed[0]).code)
        source = duel.state.player(duel.to_act).hand
        if source:
            rejected = duel.apply(
                PlayerAction.special_summon(
                    actor=duel.to_act, source=source[0].instance_id
                )
            )
            seen_codes.add(rejected.code)

    #: 여러 코드가 나온다 — 이 코드가 전부를 삼키지 않는다.
    assert len(seen_codes) >= 2, seen_codes
    #: 그리고 거절 쪽에서 실제로 이 코드가 나온다.
    assert ValidationCode.RULE_NOT_IMPLEMENTED in seen_codes
    assert ValidationCode.OK in seen_codes
    #: 보류 쪽은 **규칙 이름**을 들고 있다 — 그리고 이제 코드도 함께다.
    assert withheld_missing, "보류에 missing 문장이 하나도 없습니다."
    assert withheld_codes, "보류에 코드가 하나도 없습니다."


def test_26_the_distinctions_from_phase_3e24_to_3e35_still_hold():
    """
    **§21 regression — 열두 Phase 가 세운 구분이 그대로인지.**
    """
    assert ConditionResult.UNKNOWN is not ConditionResult.FALSE
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    for name in (
        "INFORMATION_UNAVAILABLE",
        "EXECUTION_FORBIDDEN",
        "CANDIDATE_NOT_ELIGIBLE",
        "COST_NOT_IMPLEMENTED",
    ):
        assert getattr(ValidationCode, name) is not ValidationCode.RULE_NOT_IMPLEMENTED
    assert ActivationStatus.CONDITION_UNKNOWN is not ActivationStatus.CONDITION_FALSE
    assert ResolutionStatus.CONDITION_UNKNOWN is not ResolutionStatus.CONDITION_FALSE

    #: enum 크기가 늘지 않았다 — 이번 Phase 가 새 코드를 만들지 않았다.
    #: 🔴 48 → **51** (Phase 6-AB 보완8). 흐름 거절을 규칙 거절로 적기 위해
    #: 셋을 더했다 — ``STAGE_FORBIDS_ACTION`` ·
    #: ``MANDATORY_TRIGGER_PENDING`` · ``TRIGGER_TIMING_MISSED``. 🔴 **셋 다
    #: ``INVALID``** 이므로 ``unknown_codes()`` 는 7 그대로다 — 모름을 늘려
    #: 문제를 덮은 것이 아니라 **모름이던 자리를 규칙 거절로 옮긴** 것이다.
    assert len(ValidationCode) == 51
    assert len(ConditionResult) == 3
    assert len(ActionValidity) == 3
    assert len(SimulationStatus) == 5
    assert len(ActionStatus) == 5

    #: 3-E-35 가 센 수가 그대로다.
    assert len(UNSUPPORTED_REASON) == len(PlayerActionKind)
