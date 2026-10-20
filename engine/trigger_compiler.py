"""
트리거 선언 컴파일러 — **Lua 의 사건 이름을 엔진의 시점으로** (Phase 6-E).

    analysis 가 읽어 둔 등록 정보
        declared_types = ["SINGLE", "TRIGGER_O"]
        code         = "EVENT_SUMMON_SUCCESS"
        ranges       = []
          ↓  compile_trigger_spec(effect_ref, …)
    TriggerSpec(point=MONSTER_SUMMONED, summons={NORMAL})
          ↓  TriggerRegistry.register
    TriggerCollector.collect(event) → TriggerCandidate
          ↓  TriggerEligibilityJudge
    TriggerEligibility (관문 5개 + unchecked_rules)

🔴 **이것이 STRUCTURAL-7 이다.** :class:`~engine.trigger.TriggerRegistry` 의
설명이 적어 두었다 — *"카드 데이터에서 트리거를 뽑아내는 컴파일러는 아직
없고 (STRUCTURAL-7), 등록되지 않은 카드는 후보가 나오지 않는 것이 지금의
사실이다."* 없던 것은 그 컴파일러 하나이고, 아래 계층은 전부 이미 있다.

왜 ``EffectSpec`` 을 받지 않는가 — ADR-007
------------------------------------------
``engine`` 이 ``analysis`` 에서 가져오는 이름은 ``LimitScope`` **하나**이고
``tests/engine/test_phase2_contracts.py`` 가 그것을 고정한다. Phase 6-D 의
카드군 컴파일러가 같은 지뢰선을 밟고 같은 결론에 이르렀으므로, 이 함수도
**문자열과 숫자만** 받는다. ``EffectSpec`` 을 들고 있는 쪽이 세 칸을 꺼내
넘긴다::

    compile_trigger_spec(
        EffectRef(card.id, ordinal),
        declared_types=spec.effect_types,   # ["SINGLE", "TRIGGER_O"]
        event_code=spec.code,               # "EVENT_SUMMON_SUCCESS"
        ranges=spec.ranges,                 # ["MZONE"]
        event_subject_claim=effect.event_subject_claim,   # "not_handler" | None
    )

🔴 **칸 이름까지 빌리지 않는다.** 처음에는 인자 이름을 ``effect_types`` 로
두었고, 여덟 개 감사가 발화했다 — 여러 Phase 가 *"엔진은 ``EffectSpec`` 의
칸을 읽지 않는다"* 를 **이름으로** 고정해 두었기 때문이다
(``test_settype_clone_contamination_audit`` 의 ``test_27`` ·
``test_variable_rebinding_audit`` 의 ``test_28`` 등). 그 감사들이 지키려는
것이 바로 이 모듈이 지키려는 것이므로, 감사에 예외를 파는 대신 **이름을
바꿨다.** 바꾸고 나니 호출부가 더 정직해졌다 — 변환은 **부르는 쪽**이 한다는
것이 한 줄에 드러난다.

두 어휘는 **크기가 다르다**
---------------------------
Phase 3-E-31 이 적어 둔 그대로다 — ``EffectSpec.code`` 는 ``EVENT_*``
**70종**이고 :class:`~engine.trigger.TimingPoint` 는 **8종**이다. 후자는
Lua 의 사본이 아니라 ``StateDelta`` / ``JournalEvent`` 에서 파생된 어휘이고,
**엔진이 실제로 만들어 내는 변화만** 이름을 갖는다.

그래서 옮길 수 있는 코드가 적다. 실측 (TRIGGER 블록 **7,868**개):

    옮길 수 있다   4,173 (53.0%)   카드 3,191장
    옮길 수 없다   3,695 (47.0%)   코드 40종

:data:`EVENT_TIMING` 이 그 전부이고, **일곱 줄뿐이다.** 한 줄 한 줄이
"엔진이 그 변화를 실제로 만들어 낸다" 는 측정에 근거한다 (아래 주석).

🔴 옮기지 않는 것들 — 가장 큰 넷
--------------------------------
- ``EVENT_PHASE`` (722블록) — **파서가 한정자를 버린다.** Phase 3-E-18 이
  측정했다: ``EVENT_PHASE`` 는 단독으로 쓰인 블록이 **0개**이고
  (1,326블록 전부 ``+PHASE_END`` 같은 한정자가 붙는다) 파서는 첫 이름만
  남긴다. 즉 ``code == "EVENT_PHASE"`` 는 **"어느 페이즈인지 모른다"** 다.
  :attr:`~engine.trigger.TimingPoint.PHASE_CHANGED` 로 옮기면 엔드 페이즈
  카드가 **모든 페이즈 전환**에서 후보가 된다.
- ``EVENT_DESTROYED`` (539) · 전투 관련 (716) — 그 계층이 아예 없다.
- ``EVENT_LEAVE_FIELD`` (151) — "필드를 떠났다" 는 도착지로 판정할 수 없다
  (ADR-002 가 파괴와 묘지로 보내기를 가른 것과 같은 이유).

강제 / 임의를 **채우지 않는다**
-------------------------------
🔴 ``TRIGGER_O`` 를 임의, ``TRIGGER_F`` 를 강제로 옮기고 싶어진다. **하지
않는다.** Phase 3-F-26 이 그 뜻풀이를 **근거 없음**으로 기록했다 — 공식
자료에 그 이름이 0회이고, production 에서 접미사를 해석하는 자리가 0곳이다.

이번 Phase 가 공식 한국어 원문으로 다시 재 봤고, 결과가 그 판정을
**뒤집지 못했다**::

    TRIGGER_O   임의 표기만 3,625   강제 표기만    4
    TRIGGER_F   강제 표기만   394   임의 표기만   45   ← 10%가 어긋난다

그래서 접미사만으로는 채우지 않는다.

🔴 **Phase 6-AA 가 근거를 하나 더 들고 왔다 — 카드 자신의 텍스트.**
「발동**할 수 있다**」는 허가의 진술이고 「발동**한다**」는 수행의 진술이다.
그것은 접미사의 **이름 풀이가 아니라 카드가 적어 둔 문장**이므로 3-F-26 이
근거 없음으로 적은 것과 다른 종류의 증거다
(``core.card_model.Card.activation_permission_text`` 가 그 값을 만든다).

그 두 근거를 **이렇게** 쓴다 (:func:`requirement_from`):

====================  =============  ==========================
텍스트                 접미사          판정
====================  =============  ==========================
「…할 수 있다」만       ``TRIGGER_O``   ``OPTIONAL``
「…한다」만            ``TRIGGER_F``   ``MANDATORY``
둘이 **어긋난다**       —              ``UNKNOWN`` ← 3-F-26 의 반례들
텍스트가 섞였다/없다    —              ``UNKNOWN``
====================  =============  ==========================

🔴 **접미사는 혼자 답을 만들지 못한다.** 위 표에서 접미사의 역할은 텍스트와
어긋날 때 **판정을 거두는 것**뿐이다. 그래서 접미사의 뜻풀이가 틀렸더라도 이
판정은 틀린 쪽으로 넓어지지 않는다 — 좁아질 뿐이다. 3-F-26 의 결론
("접미사의 뜻은 근거가 없다") 을 **뒤집지 않고 그대로 쓴다.**

실측 (유발 선언 블록 8,052개 · 카드 5,857장)::

    OPTIONAL    5,176 (64.3%)   텍스트=임의만 × TRIGGER_O
    MANDATORY     514 ( 6.4%)   텍스트=강제만 × TRIGGER_F
    UNKNOWN     2,362 (29.3%)
       ├ 텍스트 미기재  1,517   ← 「발동…」 문장이 아예 없다
       ├ 텍스트 혼재      766   ← 붙이는 방법에 따라 답이 달라진다
       └ 둘이 어긋남       79   ← 3-F-26 이 센 반례 그대로

🔴 **Phase 6-AB 가 「때 / 경우」 축도 채운다** (:func:`wording_from`). 6-AA
가 그 축을 "타이밍 윈도우가 있어야 쓸 수 있다" 며 비워 두었는데, **그 판단이
틀렸다** — 윈도우 계층 없이도 공식 재정이 말하는 것을 그대로 물을 수 있다:
*그 사건이 마지막에 일어난 일인가.* 기록(``EventJournal``)이 그 질문에
답한다.

    「…했을 **때**에 발동」   놓친 타이밍이 **있다** — 사건이 마지막이어야 한다
    「…했을 **경우**에 발동」  놓친 타이밍이 **없다** — 사이에 다른 일이 와도 된다

출처 (룰북에 없어 밖에서 확인했다):
``core.card_model.Card.activation_wording_text`` 의 설명이 링크를 적는다.

실측 (같은 8,052 블록)::

    if        3,192   때/경우 중 「경우」만
    when        688   「때」만
    unknown   4,172   둘 다 없거나 둘 다 있다 (조건의 「경우」와 섞인 것 포함)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from engine.effect.delta import SummonKind
from engine.ids import EffectRef
from engine.trigger import (
    TimingPoint,
    TriggerRequirement,
    TriggerSpec,
    TriggerSubject,
    TriggerWording,
)
from engine.vocabulary import Zone

#: ``EffectSpec.declared_types`` 에서 **트리거 등록**을 뜻하는 이름들.
#:
#: Phase 3-F-26 의 결론대로 접미사의 뜻(강제/임의)은 쓰지 않는다. 쓰는 것은
#: "이 블록이 사건에 반응하는 등록이다" 라는 **분류**뿐이고, 그 분류는 같은
#: 감사가 **지지한다** ("단순히 데이터 분류일 가능성이 있는가 → 그렇다").
TRIGGER_DECLARATION_TYPES: frozenset[str] = frozenset({"TRIGGER_O", "TRIGGER_F"})

#: 🔴 **``FLIP`` 은 그 자체가 유발 시점이다** — ``SetCode`` 를 부르지 않는다.
#:
#: 실측: 사건 코드가 ``None`` 인 트리거 블록 **71개** 중 **69개**가 ``FLIP``
#: 을 달고 있고, 그중 **57개는 ``SetCode`` 를 아예 부르지 않는다** (섀도르
#: 비스트 3717252 의 ``e1`` 이 그 모양이다:
#: ``SetType(SINGLE+FLIP+TRIGGER_O)`` 뒤에 ``SetCode`` 가 없다).
#: 나머지 12개는 ``SetCode`` 를 불렀지만 인자를 읽지 못했다 — 두 까닭이
#: 겹친 블록이고, 어느 쪽이든 옮길 수 없다.
#:
#: 그래서 그 69개를 **"못 읽었다" 가 아니라 "뒤집기 계층이 없다"** 로 적는다.
#: 둘을 합치면 "파서를 고치면 풀린다" 로 읽히는데, 실제로는 뒤집기 소환
#: 계층이 생겨야 풀린다. ``FLIP`` 과 옮길 수 있는 코드를 **함께** 가진
#: 블록은 **0개**이므로 이 분기가 멀쩡한 선언을 가로채지 않는다.
FLIP_DECLARATION_TYPE = "FLIP"

#: 접미사가 **임의** 쪽을 가리키는 선언. 🔴 혼자서는 아무것도 결정하지 않는다.
OPTIONAL_DECLARATION_TYPE = "TRIGGER_O"

#: 접미사가 **강제** 쪽을 가리키는 선언. 🔴 같은 규율이다.
MANDATORY_DECLARATION_TYPE = "TRIGGER_F"

#: 카드 텍스트가 말하는 두 값 (``core.card_model.activation_permission_text``).
#:
#: 🔴 **문자열로 받는다.** 이 모듈은 ``core`` 를 import 하지 않는다
#: (``tests/test_trigger_compiler.py`` 의
#: ``test_h_the_compiler_borrows_nothing_from_analysis``) — 문자열과 숫자만
#: 받는 것이 그 경계를 지키는 방법이고, 6-D 부터의 규율이다.
TEXT_OPTIONAL = "optional"
TEXT_MANDATORY = "mandatory"

#: 카드 텍스트가 말하는 발동 시점의 어휘
#: (``core.card_model.activation_wording_text``). 같은 이유로 문자열이다.
TEXT_WHEN = "when"
TEXT_IF = "if"


def wording_from(text_wording: "str | None") -> TriggerWording:
    """
    이 블록의 발동 시점이 「때」인가 「경우」인가 (Phase 6-AB). 모르면
    ``UNKNOWN``.

    🔴 **근거가 하나뿐이다 — 카드 텍스트.** 강제 · 임의와 달리 Lua 선언에
    이 축이 **없다** (``TRIGGER_O`` · ``TRIGGER_F`` 는 강제/임의 쪽 이름이고,
    어휘를 적는 선언은 어디에도 없다). 그래서 어긋남을 볼 상대가 없고,
    텍스트가 한쪽만 말할 때 그대로 받는다.

    🔴 **그래서 ``UNKNOWN`` 이 더 많다** (4,172 / 8,052). 섞였거나 없으면
    판정하지 않고, 받는 쪽은 그 모름을 **허가로 바꾸지 않는다**
    (``Duel._trigger_actions`` 가 보류로 돌린다).
    """
    if text_wording == TEXT_WHEN:
        return TriggerWording.WHEN
    if text_wording == TEXT_IF:
        return TriggerWording.IF
    return TriggerWording.UNKNOWN


def requirement_from(
    declared_types: Sequence[str], text_permission: "str | None"
) -> TriggerRequirement:
    """
    이 블록의 발동이 **강제인가 임의인가** (Phase 6-AA). 모르면 ``UNKNOWN``.

    두 근거가 **같은 쪽을 말할 때만** 판정한다 (모듈 머리말의 표).

    - 근거 1 **카드 텍스트** — ``text_permission``. 카드가 제 입으로 적은
      허가/수행의 진술이고, 이것이 **답을 만드는 쪽**이다.
    - 근거 2 **Lua 접미사** — ``declared_types``. 어긋날 때 **판정을 거두는
      데만** 쓴다 (3-F-26: 접미사의 뜻풀이는 근거가 없다).

    🔴 **발동 가능성과 섞지 않는다.** 이 값은 "규칙이 발동을 요구하는가" 이고,
    조건이 참인가 · 비용을 낼 수 있는가 · 지금이 그 시점인가는 전부 다른
    질문이며 다른 계층이 답한다 (``TriggerEligibilityJudge`` 의 다섯 관문).
    강제 효과도 조건이 거짓이면 발동하지 않는다.
    """
    kinds = set(declared_types)
    says_optional = OPTIONAL_DECLARATION_TYPE in kinds
    says_mandatory = MANDATORY_DECLARATION_TYPE in kinds
    if says_optional and says_mandatory:
        # 한 블록이 둘을 함께 선언했다 — 접미사가 자기 안에서 어긋난다.
        return TriggerRequirement.UNKNOWN
    if text_permission == TEXT_OPTIONAL and says_optional:
        return TriggerRequirement.OPTIONAL
    if text_permission == TEXT_MANDATORY and says_mandatory:
        return TriggerRequirement.MANDATORY
    return TriggerRequirement.UNKNOWN


@dataclass(frozen=True, slots=True)
class _Timing:
    """한 사건 코드가 어떤 시점으로 옮겨지는가."""

    point: TimingPoint
    to_zones: frozenset[Zone] | None = None
    summons: frozenset[SummonKind] | None = None


#: 🔴 **아직 판정할 수 없는 것 — "이 사건이 이 카드의 사건인가".**
#:
#: Lua 는 ``EFFECT_TYPE_SINGLE`` (5,255 트리거 블록) 과
#: ``EFFECT_TYPE_FIELD`` (2,611) 로 적용 범위를 가르지만, 엔진의
#: :class:`~engine.trigger.TimingEvent` 에는 "누구의 사건인가" 를 거는 칸이
#: 없고 :class:`~engine.trigger.TriggerCollector` 는 **그 카드의 보이는
#: 사본마다** 후보를 만든다. 즉 선언이 ``MONSTER_SUMMONED`` 를 보고 있으면
#: **다른 몬스터가 소환돼도** 후보가 된다.
#:
#: 접미사로 메울 수 있을 것처럼 보이지만, 공식 원문으로 재 보니 근거가
#: 한쪽뿐이다::
#:
#:     SINGLE   "이 카드가" 표기 있음 2,259 · 없음  69   (97.0%)
#:     FIELD                     있음   273 · 없음 288   (48.7%)
#:
#: ``FIELD`` 는 **동전 던지기**다. Phase 3-F-26 이 ``_O``/``_F`` 접미사를
#: 같은 이유로 "근거 없음" 으로 기록했으므로 여기서도 메우지 않는다.
#:
#: 🔴 **Phase 6-F 가 이 수치를 다시 쟀고, 위의 97.0% 는 범위가 틀렸다.**
#: 그 측정은 트리거 블록 **전부**(8,052)를 셌는데, 주체가 문제가 되는 것은
#: **옮길 수 있는 사건 코드를 가진 블록**뿐이다 (:data:`EVENT_TIMING` 의
#: 일곱 줄). 그 4,201개로 다시 세면::
#:
#:     SINGLE   "이 카드" 표기 있음 3,402 · 없음   8   (99.8%)
#:     FIELD                    있음   710 · 없음  81   (89.8%)
#:
#: 그리고 **그 8건을 한 장씩 읽었다 — 진짜 반례는 0건이다.** 넷은 한국어
#: 원문이 없어 영문만 있는 카드이고 ("When **this card** has been sent to
#: the Graveyard" — Cockroach Knight 33413638), 하나는 「**이 몬스터가**
#: 일반 소환…」 (다크 제로이드 90980792), 하나는 「**이 방법으로** 특수
#: 소환에 성공했을 경우」 (심판자－볼테니스 20951752), 둘은 주체를 생략한다
#: (질풍조인 죠 81896370). 전부 **자기 자신**이고, 표기 문자열이 달랐을
#: 뿐이다.
#:
#: 🔴 **텍스트와 독립적인 구조 근거도 같은 방향이다.** ``FIELD`` 트리거는
#: 사건 묶음 ``eg`` 에서 "어느 카드의 사건인가" 를 스크립트가 직접 골라야
#: 한다. 트리거 범위가 한 종류뿐인 카드로 재면::
#:
#:     SINGLE  2,570장 중  72장 (2.8%) 이 eg 로 사건 카드를 고른다
#:     FIELD     528장 중 205장 (38.8%) — 14배
#:
#: 근거 두 줄이 모두 "``SINGLE`` 은 핸들러가 곧 주체" 를 가리키므로, 6-F 는
#: ``SINGLE`` 만 :attr:`~engine.trigger.TriggerSubject.SELF` 로 적는다.
#: ``FIELD`` 는 그대로 **적지 않는다** (``subject=None`` → ``UNKNOWN``).
#:
#: 🔴 그리고 **틀렸을 때의 방향이 안전하다.** ``SINGLE`` 의 뜻이 어디선가
#: 다르면 멀쩡한 후보가 ``INELIGIBLE`` 로 빠진다 — 거짓 음성이고, 지시서
#: §11 이 둘 중 받아들이기로 한 쪽이다 ("발동 후보가 많이 생성되는 것보다
#: 잘못된 후보가 생성되지 않는 것이 우선"). 반대 방향(거짓 양성)은 이 축이
#: 만들어 낼 수 없다 — ``None`` 을 통과로 읽지 않기 때문이다.
EVENT_SUBJECT_RULE = "trigger-event-subject (이 사건이 이 카드의 사건인가)"

#: 🔴 **``declared_types`` 중 적용 범위를 뜻하는 이름.**
#:
#: 접미사의 뜻을 쓰지 않는 것과 **다른 종류의 판단**이다. 강제/임의는 이름
#: 말고는 근거가 없었지만 (3-F-26), 범위는 위의 두 측정이 받쳐 준다.
SELF_SCOPE_DECLARATION = "SINGLE"
ANY_SCOPE_DECLARATION = "FIELD"

#: 🔴 **옮길 수 있는 사건 코드 전부.** 일곱 줄이고, 늘리려면 "엔진이 그
#: 변화를 실제로 만들어 낸다" 를 먼저 측정해야 한다.
#:
#: 근거는 실제 듀얼을 돌려 재었다 (59수 · journal 52사건):
#: ``monster_summoned`` · ``card_drawn`` · ``effect_resolved`` 가 나왔고,
#: ``card_moved`` 는 어리석은 매장을 해결해 확인했다
#: (``ZoneMoved(send_to_grave, DECK→GRAVE)``).
EVENT_TIMING: dict[str, _Timing] = {
    # 소환 — 둘을 **반드시** 가른다 (``TriggerSpec.summons`` 의 설명).
    "EVENT_SUMMON_SUCCESS": _Timing(
        TimingPoint.MONSTER_SUMMONED, summons=frozenset({SummonKind.NORMAL})
    ),
    "EVENT_SPSUMMON_SUCCESS": _Timing(
        TimingPoint.MONSTER_SUMMONED, summons=frozenset({SummonKind.SPECIAL})
    ),
    # 어디에 **도착했는가** — ``ZoneMoved`` 가 그대로 말해 준다.
    #
    # 🔴 의미(``operations``)로 거르지 않는다. Lua 의 ``EVENT_TO_GRAVE`` 는
    # 파괴로 갔든 효과로 보내졌든 **묘지에 도착하면** 발화한다. 의미를 걸면
    # 그 범위가 좁아진다.
    "EVENT_TO_GRAVE": _Timing(
        TimingPoint.CARD_MOVED, to_zones=frozenset({Zone.GRAVE})
    ),
    "EVENT_TO_HAND": _Timing(
        TimingPoint.CARD_MOVED, to_zones=frozenset({Zone.HAND})
    ),
    "EVENT_TO_DECK": _Timing(
        TimingPoint.CARD_MOVED, to_zones=frozenset({Zone.DECK})
    ),
    "EVENT_REMOVE": _Timing(
        TimingPoint.CARD_MOVED, to_zones=frozenset({Zone.REMOVED})
    ),
    # 드로우는 존 이동과 **다른 사건**이다 — ``ZoneMoved`` 가 ``DRAW`` 를
    # 아예 거부하므로 위의 ``EVENT_TO_HAND`` 와 겹치지 않는다.
    "EVENT_DRAW": _Timing(TimingPoint.CARD_DRAWN),
}


class TriggerCompilationStatus(str, Enum):
    """
    등록 정보를 시점으로 옮긴 결과.

    :class:`~engine.summon_rules.SummonEligibility` 와 **같은 모양**이다 —
    "되었다 / 확실히 안 된다 / 모른다" 를 한 불리언으로 뭉개지 않는다.
    """

    COMPILED = "compiled"
    """시점으로 옮겼다. :attr:`TriggerCompilation.spec` 이 있다."""
    EVENT_UNSUPPORTED = "event_unsupported"
    """
    사건 코드는 읽었는데 **옮길 시점 이름이 없다** (실측 3,695블록 · 40종).

    "그 카드에 트리거가 없다" 가 **아니다.** 등록은 분명히 있고, 엔진이 그
    사건을 만들어 내지 못한다.
    """
    EVENT_UNREAD = "event_unread"
    """
    **사건 코드 자체를 읽지 못했다** (실측 **2**블록).

    🔴 ``code is None`` 인 블록은 71개인데 이 상태는 2개뿐이다 — 나머지
    69개는 ``FLIP`` 이고, 그쪽은 코드가 없는 것이 **정상**이므로
    :attr:`EVENT_UNSUPPORTED` 로 간다 (:data:`FLIP_DECLARATION_TYPE`).

    Phase 3-E-18 이 "틀린 값을 남기는 것보다 모른다고 말하는 것이 맞다" 며
    읽지 못한 인자를 ``None`` 으로 되돌렸고, 그 ``None`` 이 여기 도착한다.
    """

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


@dataclass(frozen=True, slots=True)
class TriggerCompilation:
    """
    트리거 등록 하나를 옮긴 결과. **불변**이고 출처를 함께 들고 있다.

    :attr:`spec` 은 :attr:`TriggerCompilationStatus.COMPILED` 일 때만 있고,
    :meth:`__post_init__` 이 그것을 강제한다 — ``SummonAssessment`` 가
    제물 수를 ``NEEDS_TRIBUTE`` 에만 붙이게 하는 것과 같은 규율이다.
    """

    status: TriggerCompilationStatus
    reason: str
    declared_types: tuple[str, ...]
    """읽은 그대로의 효과 타입 이름들. 출처 보존용."""
    event_code: str | None = None
    """읽은 그대로의 Lua 사건 코드. 읽지 못했으면 ``None``."""
    spec: TriggerSpec | None = None

    def __post_init__(self) -> None:
        if self.status is TriggerCompilationStatus.COMPILED:
            if self.spec is None:
                raise ValueError(
                    "옮겼다고 적으면서 선언이 없을 수 없습니다."
                )
        elif self.spec is not None:
            raise ValueError(
                f"{self.status.value} 인데 선언이 붙어 있습니다. 옮기지 못한 "
                "등록에 선언을 달면 그 선언이 후보를 만듭니다."
            )
        if self.status is TriggerCompilationStatus.EVENT_UNREAD and self.event_code:
            raise ValueError(
                "사건 코드를 읽지 못했다면 코드를 적을 수 없습니다."
            )

    @property
    def is_registered(self) -> bool:
        """
        후보 수집에 **등록할 수 있는가.** ``COMPILED`` 일 때만 참이다.

        ``if status is not EVENT_UNREAD:`` 같은 코드로 옮기지 못한 등록이
        레지스트리에 새어 들어가는 것을 막는다
        (:attr:`~engine.trigger.TriggerStatus.is_candidate` 와 같은 이유).
        """
        return self.status is TriggerCompilationStatus.COMPILED

    def canonical_state(self) -> tuple:
        return (
            self.status.value,
            self.reason,
            self.declared_types,
            self.event_code,
            self.spec.canonical_state() if self.spec is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "status": self.status.value,
            "reason": self.reason,
            "declared_types": list(self.declared_types),
        }
        if self.event_code is not None:
            data["event_code"] = self.event_code
        if self.spec is not None:
            data["spec"] = self.spec.to_dict()
        return data

    def describe_ko(self) -> str:
        return f"{self.status.value}: {self.reason}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


def _zones_from(ranges: Sequence[str]) -> frozenset[Zone] | None:
    """
    ``SetRange(LOCATION_MZONE)`` 의 이름들을 :class:`Zone` 으로.

    **하나라도 옮길 수 없으면 ``None``** 이다 — 일부만 옮기면 범위가
    실제보다 **좁아지고**, 좁은 범위는 그 밖에 있는 카드를 조용히 후보에서
    뺀다. 적지 않으면 관문이 ``UNKNOWN`` 이 되므로 (``activates_from`` 의
    설명) 그쪽이 안전하다.

    .. note::
       🔴 Phase 6-G 가 전수로 확인했다 — 컴파일되는 트리거 등록 4,173건의
       ``ranges`` 에 나타나는 ``LOCATION_*`` 이름은 **여덟 가지뿐**이고
       (``MZONE`` 298 · ``SZONE`` 166 · ``HAND`` 155 · ``GRAVE`` 123 ·
       ``FZONE`` 72 · ``PZONE`` 20 · ``REMOVED`` 6 · ``EXTRA`` 2) 전부
       :class:`Zone` 멤버다. 즉 **못 옮겨서 ``None`` 이 되는 경우는 0건**
       이고, ``LOCATION_ONFIELD`` 같은 **합성 상수는 한 번도 쓰이지 않는다**
       (corpus 전체에 그런 ``SetRange`` 는 4개 파일뿐이고 그중 트리거 등록은
       없다). 복수 영역은 26건이고 전부 2개다.
    """
    if not ranges:
        return None
    found = []
    for name in ranges:
        try:
            found.append(Zone(name))
        except ValueError:
            return None
    return frozenset(found)


#: 🔴 **``SetRange`` 는 "등록 범위" 이고 "발동 위치" 가 아니다** (Phase 6-G).
#:
#: 두 사실이 **대부분 같지만 항상 같지는 않다.** 효과가 등록되어 있는 범위는
#: "이 효과가 살아 있으려면 카드가 어디 있어야 하는가" 이고, 발동 위치는
#: "효과가 발동하는 순간 카드가 어디 있는가" 다. 카드 **자신**이 그 사건으로
#: 움직이면 둘이 갈라진다.
#:
#: 실측 증거가 corpus 안에 있다 — 드로우 개구리(56840658) 의 Lua::
#:
#:     e2:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
#:     e2:SetRange(LOCATION_MZONE)
#:     e2:SetCode(EVENT_TO_GRAVE)
#:     e2:SetCondition(s.condition)
#:     -- s.condition: c:IsPreviousLocation(LOCATION_ONFIELD)
#:
#: 🔴 **스크립트 자신이 ``IsPreviousLocation`` 을 쓴다.** 발동하는 순간 그
#: 카드는 **묘지**에 있고 ``LOCATION_MZONE`` 은 등록 범위다. 공식 원문도
#: 「**필드의 앞면 표시의** 이 카드가 **묘지로 보내졌을 때**」 다.
#:
#: 그래서 그 범위를 ``activates_from`` (= 지금 어디 있어야 하는가) 에 넣으면
#: 자리 관문이 **확정 거부**를 낸다 — 실제로 재현했다 ("GRAVE 는 발동할 수
#: 있는 자리가 아닙니다 (MZONE)"). 거짓 음성이고, ``UNKNOWN`` 이 아니라
#: **잘못된 확신**이라서 더 나쁘다.
#:
#: 🔴 **새 칸을 만들지 않았다.** 그 뜻을 가진 칸이 이미 있다 —
#: :attr:`~engine.trigger.TriggerSpec.from_zones` ("어떤 이동에만 반응하는가")
#: 를 ``matches`` 가 ``event.from_zone`` 과 비교한다. 즉 이동 **전** 자리는
#: 사건 쪽이 들고 있고, 그것이 Lua 의 ``IsPreviousLocation`` 과 같은 질문이다.
#:
#: 적용 조건은 **데이터만 본다** (카드별 분기 없음):
#:
#: * 주체가 ``SELF`` 다 — 그때만 "이 카드" 가 곧 사건의 주체이므로 사건의
#:   도착지가 곧 발동 시점의 이 카드 위치다. ``FIELD`` 등록에서는 도착지가
#:   **다른 카드**의 것이므로 이 추론이 성립하지 않는다 (실측: 그렇게
#:   어긋나 보이는 ``FIELD`` 사례가 174건이고 전부 정상이다).
#: * 시점이 ``CARD_MOVED`` 다 — ``from_zones`` 를 걸 수 있는 유일한 시점이고,
#:   소환 시점에는 영역 축이 금지되어 있다 (3-F-5 ②).
#: * 사건의 도착지가 범위 **밖**이다 — 안이면 범위가 곧 발동 위치다.
#:
#: 🔴 **이 변환은 거짓 양성을 만들 수 없다.** 바꾸는 방향이 "확정 거부 →
#: 모름" 하나뿐이고 (``activates_from`` 을 비우므로 자리 관문이 ``UNKNOWN``),
#: 동시에 ``from_zones`` 라는 **새 필터를 더하므로** 반응하는 사건이 오히려
#: 줄어든다. 실측: 이 모양은 전 corpus 에서 **1건**이다.
#: 🔴 **조건 함수가 말하는 주체 관계** (Phase 6-H).
#:
#: ``analysis`` 가 조건 함수의 구문 자리를 보고 적어 둔 주장이고, 이 모듈은
#: 그것을 **원시 문자열로** 받는다 — ``EffectSpec`` 을 받지 않는 것과 같은
#: 이유다 (ADR-007, 이 모듈 머리말). 값이 갈라지지 않도록
#: ``test_6h_...::test_02`` 가 :class:`analysis.effect_model.EventSubjectClaim`
#: 의 값과 이 상수를 맞춰 고정한다.
#:
#: 왜 ``FIELD`` 등록만 이 주장을 쓰는가 — ``SINGLE`` 등록은 이미
#: :attr:`~engine.trigger.TriggerSubject.SELF` 이고, 실측에서 **그 둘이
#: 겹치는 등록은 0건**이다. 겹치면 선언을 덮지 않고 선언을 남긴다 (아래
#: :func:`compile_trigger_spec`).
#:
#: 실측 (전체 등록 4,173건): 이 주장이 붙는 ``FIELD`` 등록 **80건** ·
#: 카드 **64장** · 사건은 ``monster_summoned`` 58 · ``card_moved`` 22.
NOT_HANDLER_CLAIM = "not_handler"

PREVIOUS_ZONE_RULE = "trigger-activation-location (등록 범위가 이동 전 자리다)"


def _split_range(
    declared: frozenset[Zone] | None,
    *,
    subject: TriggerSubject | None,
    point: TimingPoint,
    to_zones: frozenset[Zone] | None,
) -> tuple[frozenset[Zone] | None, frozenset[Zone] | None]:
    """
    ``SetRange`` 하나를 **(이동 전 필터, 발동 위치)** 로 가른다.

    조건과 근거는 :data:`PREVIOUS_ZONE_RULE` 의 주석에 있다. 범위가 없으면
    둘 다 ``None`` 이고, 가를 근거가 없으면 **지금까지와 같이** 발동 위치로
    둔다 — 근거 없이 뜻을 바꾸지 않는다.
    """
    if declared is None:
        return None, None
    if (
        subject is TriggerSubject.SELF
        and point is TimingPoint.CARD_MOVED
        and to_zones is not None
        and not (to_zones & declared)
    ):
        #: 도착지가 범위 밖이다 → 그 범위는 **이동 전** 자리다. 발동 위치는
        #: 적지 않는다 (모른다) — 카드가 간 곳이 곧 발동 위치라고 적으면
        #: 자리 관문이 **항상 통과하는 동어반복**이 되어 검사한 척하게 된다.
        return declared, None
    return None, declared


def compile_trigger_spec(
    effect_ref: EffectRef,
    *,
    declared_types: Sequence[str],
    event_code: str | None,
    ranges: Sequence[str] = (),
    event_subject_claim: str | None = None,
    text_permission: "str | None" = None,
    text_wording: "str | None" = None,
) -> TriggerCompilation | None:
    """
    효과 블록 하나의 등록 정보를 :class:`~engine.trigger.TriggerSpec` 으로.

    **트리거 등록이 아니면 ``None``** 이다 (``declared_types`` 에
    ``TRIGGER_O`` · ``TRIGGER_F`` 가 없다). 결과 객체를 만들지 않는 이유는
    Phase 6-D 와 같다 — "트리거가 아니다" 와 "트리거인데 옮기지 못했다" 가
    같은 값이 되면 안 된다.

    ``text_permission`` (Phase 6-AA) 은 **카드 텍스트가 말하는 허가/수행**
    이다 (``core.card_model.Card.activation_permission_text``).
    ``text_wording`` (Phase 6-AB) 은 **발동 시점의 어휘**다
    (``…activation_wording_text``). 둘 다 주지 않으면 각각 ``UNKNOWN`` 이고,
    그것이 그 Phase 이전의 동작 그대로다 — 없는 것을 기본값으로 메꾸지
    않는다 (ADR-006).
    """
    if not isinstance(effect_ref, EffectRef):
        raise TypeError(f"EffectRef 가 필요합니다: {type(effect_ref).__name__}")
    kinds = tuple(declared_types)
    if not TRIGGER_DECLARATION_TYPES & set(kinds):
        return None

    if event_code is None:
        if FLIP_DECLARATION_TYPE in kinds:
            # 사건이 **타입 플래그로** 적혀 있다 — 코드가 없는 것이 정상이다.
            return TriggerCompilation(
                status=TriggerCompilationStatus.EVENT_UNSUPPORTED,
                reason=(
                    "뒤집혔을 때가 유발 시점입니다 (FLIP). 사건 코드가 "
                    "없는 것이 정상이고, 엔진에 뒤집기 계층이 없어 옮길 "
                    "시점 이름이 없습니다."
                ),
                declared_types=kinds,
            )
        return TriggerCompilation(
            status=TriggerCompilationStatus.EVENT_UNREAD,
            reason=(
                "사건 코드를 읽지 못했습니다 (SetCode 의 인자를 이름으로 "
                "옮길 수 없었습니다). 어떤 일에 반응하는지 모르므로 "
                "등록하지 않습니다."
            ),
            declared_types=kinds,
        )

    timing = EVENT_TIMING.get(event_code)
    if timing is None:
        return TriggerCompilation(
            status=TriggerCompilationStatus.EVENT_UNSUPPORTED,
            reason=(
                f"{event_code} 를 옮길 시점 이름이 없습니다. 등록은 있지만 "
                "엔진이 그 사건을 만들어 내지 못합니다."
            ),
            declared_types=kinds,
            event_code=event_code,
        )

    # 🔴 **주체를 축으로 적는다** (Phase 6-F).
    #
    # Phase 6-E 는 같은 불확실성을 ``condition=UnimplementedRule(...)`` 으로
    # 실어 보냈다. 그것은 **자리를 빌린 것**이었다 — 조건은 판 위의 사실을
    # 묻는 것이고 (``ConditionEvaluator`` 가 ``GameStateView`` 를 들고
    # 평가한다) "누구의 사건인가" 는 판이 아니라 **사건**의 성질이다. 6-F 가
    # :func:`~engine.trigger.subject_relation` 로 자리를 옮겼으므로 여기서
    # 조건을 만들지 않는다. 모름이 사라진 것이 아니라 **제자리로 갔다.**
    subject = (
        TriggerSubject.SELF if SELF_SCOPE_DECLARATION in kinds else None
    )
    if subject is None and event_subject_claim == NOT_HANDLER_CLAIM:
        # 🔴 **조건 함수가 적어 둔 것만 읽는다** (Phase 6-H 의
        # :data:`NOT_HANDLER_CLAIM` 주석이 근거와 실측을 적는다).
        #
        # 등록 범위가 ``FIELD`` 라서 주체를 모르던 자리에 조건 함수가
        # 「이 카드 이외」 를 적어 두었다. 선언이 이미 주체를 말한 자리
        # (``SELF``) 는 **덮지 않는다** — 둘이 어긋나면 그것은 분류기가
        # 틀렸다는 신호이고, 그때 조건이 선언을 이기게 만들면 틀린 쪽이
        # 조용히 이긴다. 실측으로 그 겹침은 0건이다.
        subject = TriggerSubject.OTHER
    # 🔴 **등록 범위를 발동 위치로 오인하지 않는다** (Phase 6-G 의
    # :data:`PREVIOUS_ZONE_RULE` 주석이 근거와 조건을 적는다).
    declared = _zones_from(ranges)
    from_zones, activates_from = _split_range(
        declared, subject=subject, point=timing.point, to_zones=timing.to_zones
    )
    spec = TriggerSpec(
        effect_ref=effect_ref,
        point=timing.point,
        from_zones=from_zones,
        to_zones=timing.to_zones,
        summons=timing.summons,
        subject=subject,
        activates_from=activates_from,
        requirement=requirement_from(kinds, text_permission),
        wording=wording_from(text_wording),
    )
    return TriggerCompilation(
        status=TriggerCompilationStatus.COMPILED,
        reason=f"{event_code} → {timing.point.value}",
        declared_types=kinds,
        event_code=event_code,
        spec=spec,
    )


__all__ = [
    "ANY_SCOPE_DECLARATION",
    "EVENT_SUBJECT_RULE",
    "NOT_HANDLER_CLAIM",
    "SELF_SCOPE_DECLARATION",
    "FLIP_DECLARATION_TYPE",
    "MANDATORY_DECLARATION_TYPE",
    "OPTIONAL_DECLARATION_TYPE",
    "TEXT_IF",
    "TEXT_MANDATORY",
    "TEXT_OPTIONAL",
    "TEXT_WHEN",
    "TRIGGER_DECLARATION_TYPES",
    "requirement_from",
    "wording_from",
    "EVENT_TIMING",
    "TriggerCompilationStatus",
    "TriggerCompilation",
    "compile_trigger_spec",
]
