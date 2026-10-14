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

그래서 :attr:`~engine.trigger.TriggerRequirement.UNKNOWN` 과
:attr:`~engine.trigger.TriggerWording.UNKNOWN` 을 그대로 둔다. 둘은
"아직 확인되지 않았다" 를 뜻하는 값이고, 그것이 지금의 사실이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from engine.effect.delta import SummonKind
from engine.ids import EffectRef
from engine.trigger import TimingPoint, TriggerSpec, TriggerSubject
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

    **하나라도 옮길 수 없으면 ``None``** 이다 — 일부만 옮기면
    ``activates_from`` 이 실제보다 **좁아지고**, 좁은 자리 선언은 그 밖에
    있는 카드를 조용히 후보에서 뺀다. 적지 않으면 관문이 ``UNKNOWN`` 이
    되므로 (``TriggerSpec.activates_from`` 의 설명) 그쪽이 안전하다.
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


def compile_trigger_spec(
    effect_ref: EffectRef,
    *,
    declared_types: Sequence[str],
    event_code: str | None,
    ranges: Sequence[str] = (),
) -> TriggerCompilation | None:
    """
    효과 블록 하나의 등록 정보를 :class:`~engine.trigger.TriggerSpec` 으로.

    **트리거 등록이 아니면 ``None``** 이다 (``declared_types`` 에
    ``TRIGGER_O`` · ``TRIGGER_F`` 가 없다). 결과 객체를 만들지 않는 이유는
    Phase 6-D 와 같다 — "트리거가 아니다" 와 "트리거인데 옮기지 못했다" 가
    같은 값이 되면 안 된다.
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
    spec = TriggerSpec(
        effect_ref=effect_ref,
        point=timing.point,
        to_zones=timing.to_zones,
        summons=timing.summons,
        subject=subject,
        activates_from=_zones_from(ranges),
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
    "SELF_SCOPE_DECLARATION",
    "FLIP_DECLARATION_TYPE",
    "TRIGGER_DECLARATION_TYPES",
    "EVENT_TIMING",
    "TriggerCompilationStatus",
    "TriggerCompilation",
    "compile_trigger_spec",
]
