"""
Phase 6-H — **조건 함수가 말하는 사건 주체 관계.**

Phase 6-F 는 등록 범위 ``SINGLE`` 에서 "이 카드의 사건이어야 한다" 를 읽었고,
``FIELD`` 등록 784건은 **주체를 모르는 채로** 남겼다. 6-H 는 그 784건의
**조건 함수**를 보고, 구문으로 확정할 수 있는 관계 하나를 읽는다::

    Lua       function s.condition(e,tp,eg,ep,ev,re,r,rp)
                  return not eg:IsContains(e:GetHandler()) and …
              ↓  analysis (EffectAnalysis.event_subject_claim)
    주장      EventSubjectClaim.NOT_HANDLER       "not_handler"
              ↓  compile_trigger_spec(event_subject_claim=…)   ← 원시 문자열
    선언      TriggerSpec(subject=TriggerSubject.OTHER)
              ↓  subject_relation
    주체 = 이 카드   →  INVALID / CANDIDATE_NOT_ELIGIBLE   (확정된 거부)
    주체 ≠ 이 카드   →  UNKNOWN / RULE_NOT_IMPLEMENTED     (그룹을 모른다)
    VALID            →  **없다**

🔴 이 축은 **거부만 하고 통과시키지 못한다**
--------------------------------------------
근거가 되는 Lua 는 "사건 그룹 ``eg`` 에 이 카드가 들어 있는가" 를 묻는데,
엔진의 사건은 주체 **한 장**만 들고 있다 (``TimingEvent.instance``). 주체가
이 카드면 그룹에 들어 있는 것이 확정되니 「이 카드 이외」 가 **거짓으로
확정**되지만, 주체가 다른 카드일 때 "이 카드도 그 사건에 함께 포함되었는가"
는 물을 데가 없다. 그래서 그쪽은 ``UNKNOWN`` 이고, 거기서 ``VALID`` 를
내면 그것이 바로 §16-6 이 금지한 **거짓 ELIGIBLE 승격**이다.

지키는 것 다섯
--------------
1. **구문 자리로 판정한다.** 호출이 있다는 사실만으로는 뜻이 정해지지 않는다
   (같은 호출이 조기 반환으로 뜻을 뒤집는다).
2. **긍정 자리는 주장하지 않는다.** 실측 4건이 전부 ``#eg==N`` 그룹 크기
   단정과 함께 나오고, 엔진은 그룹 크기를 들고 있지 않다.
3. **선언을 덮지 않는다.** ``SINGLE`` 이 이미 ``SELF`` 를 말한 자리는 조건이
   이기지 못한다 (실측 겹침 0건).
4. 🔴 **수집기와 판정기가 같은 답을 낸다** (6-F 의 규율 그대로 —
   ``fold`` 는 후보의 ``status`` 를 보지 않는다).
5. **6-G 의 위치 축이 그대로다.** 주장이 없는 등록은 글자 그대로 같은 결과다.

대표 사례는 **공식 원문이 그 관계를 말하는** 카드로 골랐다 (측정으로 선택,
카드별 분기는 production 코드에 없다).
"""

import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from analysis.effect_model import EventSubjectClaim
from engine.duel import Duel
from engine.effect.delta import MonsterSummoned, SummonKind
from engine.event_pipeline import EventPipeline
from engine.ids import EffectRef, InstanceId
from engine.trigger import (
    GROUP_MEMBERSHIP_RULE,
    SUBJECT_MISSING_RULE,
    EligibilityGate,
    TimingEvent,
    TimingPoint,
    TriggerCollector,
    TriggerEligibilityJudge,
    TriggerRegistry,
    TriggerSpec,
    TriggerStatus,
    TriggerSubject,
    subject_relation,
)
from engine.trigger_compiler import NOT_HANDLER_CLAIM, compile_trigger_spec
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: DDD 질풍왕 알렉산더 — 공식 원문이 **두 관계를 다 말한다**: 「이 카드가
#: 몬스터 존에 존재하고 자신 필드에 **이 카드 이외의** "DD" 몬스터가 일반
#: 소환 / 특수 소환되었을 경우」. 한 문장(①)이 등록 **두 개**(``EVENT_
#: SUMMON_SUCCESS`` · ``EVENT_SPSUMMON_SUCCESS``) 로 나뉘어 있어서 원문과
#: 등록의 귀속이 흔들리지 않는다.
OTHER_SUMMON_CARD = 987311

#: 토폴로직 폭탄 드래곤 — 같은 호출을 **조기 반환**으로 쓴다
#: (``if eg:IsContains(e:GetHandler()) then return false end``). 공식 원문도
#: 「이 카드가 이미 몬스터 존에 존재하는 상태에서, **이 카드 이외의** 몬스터가
#: … 특수 소환되었을 경우」 다.
EARLY_RETURN_CARD = 5821478

#: 초고대 티라노 — 등록 효과가 **하나**뿐이라 원문 ①과 1:1 이다. 공식 원문은
#: 「이 카드가 몬스터 존에 존재하고, **자신 묘지에서** 공룡족 몬스터가 특수
#: 소환되었을 때」 — 주체가 이 카드가 아니라는 것이 "이 카드 이외" 라는 말
#: 없이도 **자리**로 드러나는 사례다.
SINGLE_BLOCK_OTHER_CARD = 6849042

#: 요위 — 같은 호출이 **긍정 자리**에 있고 ``#eg==1`` 이 함께 있다. 공식
#: 원문은 「**이 카드 1장만이** 일반 소환 / 반전 소환 / 특수 소환에 성공했을
#: 경우」. 주장하지 않는 쪽의 대표다.
GROUP_SIZE_CARD = 33393090

#: 엘리멘틀 히어로 페더맨 — **통상** 몬스터라서 엔진이 실제로 일반 소환할 수
#: 있고 (``assess_normal_summon`` 이 ``VALID``), 트리거는 하나도 없다. 6-F 가
#: 같은 이유로 쓴 카드다.
FEATHERMAN = 21844576


# ======================================================================
# 도움 함수 — 전부 **실제** 분석기와 컴파일러를 지난다
# ======================================================================


def compile_card(repository, card_id):
    """카드 하나의 등록 효과를 **분석기의 주장까지 들고** 컴파일한다."""
    analyzer = EffectAnalyzer(repository)
    card = repository.get(card_id)
    assert card is not None and card.script is not None, card_id
    analysis = analyzer.analyze(card)
    out = []
    for ordinal, effect in enumerate(analysis.effects):
        result = compile_trigger_spec(
            EffectRef(card_id, ordinal),
            declared_types=effect.effect_types,
            event_code=effect.raw.code,
            ranges=effect.raw.ranges,
            event_subject_claim=effect.event_subject_claim,
        )
        out.append((effect, result))
    return card, out


def registry_from(repository, card_ids):
    """카드 데이터 → 실제 컴파일러 → 등록소. 손으로 선언을 적지 않는다."""
    registry = TriggerRegistry()
    for card_id in card_ids:
        for _, result in compile_card(repository, card_id)[1]:
            if result is not None and result.is_registered:
                registry.register(result.spec)
    return registry


def summon_event(instance: InstanceId, kind: SummonKind = SummonKind.NORMAL):
    """실제 인스턴스를 주체로 하는 소환 사건. 시점을 손으로 적지 않는다."""
    return TimingEvent.from_delta(
        MonsterSummoned(
            summon=kind,
            card=instance,
            player=MINE,
            owner=MINE,
            from_zone=Zone.HAND,
            to_zone=Zone.MZONE,
            to_index=0,
            position=Position.ATTACK,
        )
    )


def both_layers(view, registry, event, definitions=None):
    """
    🔴 **수집기와 판정기를 같은 사건에 둘 다 돌린다** (6-F 의 도움 함수와
    같은 이유 — ``fold`` 는 관문만 보고 후보의 ``status`` 를 보지 않는다).
    """
    collector = TriggerCollector(view, registry, definitions)
    judge = TriggerEligibilityJudge(view, definitions)
    out = []
    for candidate in collector.collect(event).candidates:
        spec = next(
            s for s in registry.watching(event) if s.effect_ref == candidate.effect_ref
        )
        out.append((candidate, judge.judge(candidate, spec, event)))
    return out


def claim_of(source: str):
    """조건 인자 하나를 **프로덕션 분류기**에 그대로 물린다."""
    return EffectAnalyzer._event_subject_claim(source, {})


# ======================================================================
# A. 분석 계층이 조건에서 무엇을 읽는가
# ======================================================================


def test_01_the_two_vocabularies_cannot_drift_apart():
    """
    🔴 **ADR-007 의 대가.** ``engine`` 은 ``analysis`` 의 이름을 가져오지
    않으므로 두 쪽이 **문자열 하나**로만 만난다. 그 문자열이 갈라지면 주장이
    조용히 무시되고, 무시된 주장은 "읽지 못했다" 와 구별되지 않는다.

    6-F 가 ``EVENT_SUBJECT_RULE == SUBJECT_MISSING_RULE`` 로 같은 일을 했다.
    """
    assert NOT_HANDLER_CLAIM == EventSubjectClaim.NOT_HANDLER.value

    #: 🔴 **주장의 방향이 하나뿐이다.** "주체가 이 카드다" 를 말하는 값을
    #: 두지 않은 것이 설계이고 (``EventSubjectClaim`` 의 설명), 값이 늘면
    #: 통과 경로가 생기므로 여기서 잠근다.
    assert [m.value for m in EventSubjectClaim] == ["not_handler"]


@requires_official_db
def test_02_the_official_text_says_other_than_this_card(repository):
    """
    대표 사례 — 공식 원문이 **「이 카드 이외의」** 를 적어 둔 등록.

    한 문장(①)이 등록 둘로 나뉘어 있으므로 **두 등록 모두** 같은 주장을
    들고 있어야 한다. 하나만 읽으면 일반 소환에는 반응하고 특수 소환에는
    반응하지 않는 **비대칭**이 생긴다.
    """
    card, blocks = compile_card(repository, OTHER_SUMMON_CARD)
    assert "이 카드 이외의" in card.desc

    codes = []
    for effect, result in blocks:
        assert effect.event_subject_claim is EventSubjectClaim.NOT_HANDLER
        assert result is not None and result.is_registered
        assert result.spec.subject is TriggerSubject.OTHER
        #: 6-G 의 위치 축은 **그대로다** — 원문 「몬스터 존에 존재하고」.
        assert result.spec.activates_from == frozenset({Zone.MZONE})
        codes.append(result.event_code)
    assert codes == ["EVENT_SUMMON_SUCCESS", "EVENT_SPSUMMON_SUCCESS"]


@requires_official_db
def test_03_an_early_return_means_the_same_thing_as_a_negation(repository):
    """
    🔴 **같은 호출이 뜻을 뒤집어 쓰인다.** ``if … then return false end`` 는
    ``not`` 과 같은 뜻이고, 부정 여부만 보는 분류기는 이것을 **긍정**으로
    읽는다 — 실측에서 실제로 그렇게 틀렸다 (2건).

    공식 원문: 「이 카드가 이미 몬스터 존에 존재하는 상태에서, **이 카드
    이외의** 몬스터가 … 특수 소환되었을 경우」.
    """
    card, blocks = compile_card(repository, EARLY_RETURN_CARD)
    assert "이 카드 이외의 몬스터가" in card.desc

    effect, result = blocks[0]
    assert effect.event_subject_claim is EventSubjectClaim.NOT_HANDLER
    assert result.spec.subject is TriggerSubject.OTHER
    #: 🔴 본문이 ``s.condition`` **이름**으로 걸려 있는지 확인한다 — 이름을
    #: 못 찾으면 본문도 못 읽고, 그러면 주장이 "없다" 가 된다.
    assert effect.condition_raw is not None
    assert not effect.condition_raw.startswith("function")


@requires_official_db
def test_04_a_positive_position_is_measured_but_not_claimed(repository):
    """
    🔴 **읽지 못한 것과 읽고도 주장하지 않는 것을 구분한다.**

    요위의 조건은 ``#eg==1 and eg:IsContains(e:GetHandler())`` 다. 호출은
    거기에 **있고** 본문도 읽혔는데 주장은 ``None`` 이다 — ``#eg==1`` 은
    그룹 크기 단정이고 엔진의 사건은 그룹 크기를 들고 있지 않다. 공식
    원문도 「**이 카드 1장만이** …」 로 **크기**를 말한다.

    주장했다면 ``SELF`` 가 되어 **새 통과 경로**가 생겼을 자리다. 그것이
    §16-7 이 금지한 복수 카드 사건의 거짓 양성이다.
    """
    card, blocks = compile_card(repository, GROUP_SIZE_CARD)
    assert "이 카드 1장만이" in card.desc

    seen = 0
    for effect, result in blocks:
        if effect.condition_raw is None:
            continue
        body = EffectAnalyzer._condition_body(
            effect.condition_raw,
            EffectAnalyzer._collect_functions(
                (PROJECT_ROOT / card.script.file_name).read_text(encoding="utf-8")
            ),
        )
        if body is None or "eg:IsContains(e:GetHandler())" not in body:
            continue
        seen += 1
        assert "#eg==1" in " ".join(body.split())
        assert effect.event_subject_claim is None
        if result is not None and result.is_registered:
            assert result.spec.subject is None
    assert seen >= 1


def test_05_a_call_inside_an_or_is_not_a_necessary_condition():
    """
    ``or`` 안에 있으면 그 호출이 거짓이어도 조건 전체가 참일 수 있다.
    필요조건이 아닌 것을 필요조건으로 읽으면 **거부가 거짓**이 된다.

    실측: 전 corpus 에서 이 모양은 **0건**이다. 0건이라서 구현을 뺀 것이
    아니라, 0건이어도 **들어오면 막아야** 하므로 합성 입력으로 잠근다.
    """
    necessary = (
        "function(e,tp,eg,ep,ev,re,r,rp) "
        "return not eg:IsContains(e:GetHandler()) and Duel.GetTurnPlayer()==tp end"
    )
    assert claim_of(necessary) is EventSubjectClaim.NOT_HANDLER

    optional = (
        "function(e,tp,eg,ep,ev,re,r,rp) "
        "return not eg:IsContains(e:GetHandler()) or Duel.GetTurnPlayer()==tp end"
    )
    assert claim_of(optional) is None


def test_06_two_occurrences_cannot_be_read_by_position():
    """
    같은 호출이 두 번 나오면 **어느 쪽이 답을 정하는지** 구문만으로 알 수
    없다. 앞의 것만 보고 결정하면 뒤의 것이 뜻을 뒤집는 경우를 놓친다.

    🔴 **입력은 앞의 것만 보면 속는 모양이어야 한다.** 처음에 쓴 입력은
    앞의 것이 ``if … then return true`` 라서 어느 보호가 막았는지 구별되지
    않았고, "둘 이상이면 포기한다" 를 지운 변이가 **살아남았다** (내 변이
    테스트가 내 테스트를 잡았다). 아래 입력은 앞의 것만 보면
    ``not`` 이 붙어 있어 ``NOT_HANDLER`` 로 읽히지만, 그 문장은 ``if not …
    then return false`` 이므로 실제 뜻은 **그 반대**(그룹에 이 카드가 있어야
    한다) 다.
    """
    inverted = (
        "function(e,tp,eg,ep,ev,re,r,rp) "
        "if not eg:IsContains(e:GetHandler()) then return false end "
        "return eg:IsContains(e:GetHandler()) end"
    )
    #: 앞의 것만 보면 ``not`` 이 붙어 있다 — 그래서 수를 세는 보호가 필요하다.
    assert "not eg:IsContains(e:GetHandler())" in inverted
    assert claim_of(inverted) is None


def test_07_the_pattern_is_the_whole_call_and_not_a_loose_name():
    """
    🔴 **실측으로 잡은 오류의 회귀 핀.** 탐사용으로 ``eg`` 만 찾았을 때
    함수 **선언부**의 매개변수 목록 ``(e,tp,eg,ep,ev,re,r,rp)`` 이 걸려
    **449건**이 거짓으로 일치했다.

    production 은 선언부를 떼는 전처리 대신 **호출 전체**를 패턴으로 쓴다.
    전처리는 이 패턴에서 죽은 코드였고 (어떤 변이도 잡히지 않아 드러났다)
    지웠다. 그래서 그 자리를 지키는 것은 **패턴의 엄격함**이고, 이 테스트가
    그것을 정적으로 고정한다 — 느슨해지면 여기서 먼저 깨진다.
    """
    from analysis.effect_analyzer import _RE_EVENT_GROUP_HAS_HANDLER as PATTERN

    assert PATTERN.search("eg:IsContains(e:GetHandler())") is not None
    assert PATTERN.search("eg:IsContains( e:GetHandler() )") is not None

    #: 느슨해지면 걸릴 것들 — 전부 **다른 뜻**이다.
    for loose in (
        "function(e,tp,eg,ep,ev,re,r,rp)",
        "eg",
        "eg:IsContains(tc)",
        "eg:IsExists(s.cfilter,1,e:GetHandler(),tp)",
        "eg:GetFirst()",
        "g:IsContains(e:GetHandler())",
    ):
        assert PATTERN.search(loose) is None, loose

    declaration_only = "function(e,tp,eg,ep,ev,re,r,rp) return true end"
    assert claim_of(declaration_only) is None

    named = "function s.cond(e,tp,eg,ep,ev,re,r,rp) return true end"
    assert EffectAnalyzer._event_subject_claim("s.cond", {"cond": named}) is None


def test_08_a_body_we_cannot_read_is_not_a_claim():
    """
    ``aux.*`` 처럼 **다른 파일의 함수**는 본문을 얻을 수 없다. 이름만으로
    뜻을 추측하지 않는다 — 정보가 없으면 ``None`` 이고, ``None`` 은
    "관계 없음" 이 아니라 "읽지 못했다" 다.
    """
    assert EffectAnalyzer._condition_body("aux.exccon", {}) is None
    assert claim_of("aux.exccon") is None
    assert claim_of("") is None
    assert claim_of("1==1") is None


# ======================================================================
# B. 컴파일러 — 주장을 선언으로 옮긴다
# ======================================================================


def test_09_the_claim_becomes_the_subject_axis_and_nothing_else():
    """
    주장이 ``OTHER`` 를 적고, **다른 칸은 건드리지 않는다.** 같은 입력을
    주장만 빼고 컴파일하면 ``subject`` 한 칸만 달라야 한다.
    """
    base = dict(
        declared_types=["FIELD", "TRIGGER_O"],
        event_code="EVENT_SPSUMMON_SUCCESS",
        ranges=["MZONE"],
    )
    without = compile_trigger_spec(EffectRef(1, 0), **base)
    with_claim = compile_trigger_spec(
        EffectRef(1, 0), event_subject_claim=NOT_HANDLER_CLAIM, **base
    )
    assert without.spec.subject is None
    assert with_claim.spec.subject is TriggerSubject.OTHER

    left, right = without.spec.to_dict(), with_claim.spec.to_dict()
    assert right.pop("subject") == "other"
    assert "subject" not in left
    assert left == right


def test_10_a_declared_subject_is_not_overwritten_by_a_condition():
    """
    🔴 ``SINGLE`` 이 이미 ``SELF`` 를 말한 자리는 조건이 **이기지 못한다.**

    둘이 어긋나면 그것은 분류기가 틀렸다는 신호다. 그때 조건이 선언을 이기게
    만들면 **틀린 쪽이 조용히 이긴다** — 데이터가 어긋났다는 사실이 사라지는
    것이 더 나쁘다. 실측으로 이 겹침은 전 corpus 0건이다 (``test_21``).
    """
    result = compile_trigger_spec(
        EffectRef(1, 0),
        declared_types=["SINGLE", "TRIGGER_O"],
        event_code="EVENT_SUMMON_SUCCESS",
        ranges=["MZONE"],
        event_subject_claim=NOT_HANDLER_CLAIM,
    )
    assert result.spec.subject is TriggerSubject.SELF


def test_11_an_unknown_claim_value_changes_nothing():
    """
    모르는 주장 문자열은 **아무 일도 하지 않는다.** 분석 계층이 나중에 값을
    더해도 엔진이 그것을 **추측해서** 쓰지 않는다 — 읽을 수 있는 값만 읽고,
    나머지는 ``None`` 과 같다.
    """
    base = dict(
        declared_types=["FIELD", "TRIGGER_O"],
        event_code="EVENT_SPSUMMON_SUCCESS",
        ranges=["MZONE"],
    )
    for value in (None, "", "handler", "not_handler_maybe", "self"):
        result = compile_trigger_spec(
            EffectRef(1, 0), event_subject_claim=value, **base
        )
        assert result.spec.subject is None, value


def test_12_a_block_that_is_not_a_trigger_stays_not_a_trigger():
    """
    주장이 붙어 있어도 **트리거 등록이 아니면 등록되지 않는다.** 실측: 주장이
    붙은 블록 134건 중 **54건**이 트리거 등록이 아니다 (``IGNITION`` 등).
    """
    assert (
        compile_trigger_spec(
            EffectRef(1, 0),
            declared_types=["FIELD"],
            event_code=None,
            ranges=["MZONE"],
            event_subject_claim=NOT_HANDLER_CLAIM,
        )
        is None
    )


# ======================================================================
# C. subject_relation — 거부만, 통과 없음
# ======================================================================


def _other(point=TimingPoint.MONSTER_SUMMONED):
    return TriggerSpec(EffectRef(1, 0), point, subject=TriggerSubject.OTHER)


def test_13_the_subject_being_this_card_is_a_settled_refusal():
    """
    주체가 **이 카드**면 「이 카드 이외」 는 거짓이다. 그룹의 나머지를 몰라도
    확정된다 — 사건의 주체는 그 사건에 포함된 카드이기 때문이다.

    확정된 거부는 **미구현이 아니다** (``missing_rule`` 이 없다).
    """
    here = InstanceId(7)
    verdict = subject_relation(_other(), summon_event(here), here)
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert verdict.missing_rule is None
    assert verdict.permits_execution is False


def test_14_the_subject_being_another_card_is_a_different_unknown():
    """
    🔴 **두 모름을 가른다** (3-E-27 의 규율). "선언이 주체를 적지 않았다" 와
    "사건이 그룹을 들고 있지 않다" 는 **다른 사실**이고, 다른 코드가 생겨야
    풀린다. 같은 이름을 쓰면 로드맵 추적이 갈라진다.
    """
    verdict = subject_relation(_other(), summon_event(InstanceId(9)), InstanceId(7))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == GROUP_MEMBERSHIP_RULE
    assert GROUP_MEMBERSHIP_RULE != SUBJECT_MISSING_RULE
    assert "trigger-event-group-membership" in GROUP_MEMBERSHIP_RULE
    assert GROUP_MEMBERSHIP_RULE in verdict.notes


def test_15_other_can_never_return_valid_for_any_input():
    """
    🔴 **전수 진리표.** 이 축이 통과시킬 수 있는 입력이 하나라도 있으면
    §16-6 이 금지한 거짓 승격의 문이 열린다. 그래서 "통과가 없다" 를
    사례로 보이지 않고 **격자 전체**로 보인다.

    축: 사건이 카드를 가리키는가 × 후보의 인스턴스를 아는가 × 같은가.
    """
    here, elsewhere = InstanceId(7), InstanceId(9)
    from engine.effect.delta import LifeChanged

    bloodless = TimingEvent.from_delta(
        LifeChanged(player=MINE, before=8000, after=7000)
    )
    assert bloodless.instance is None

    grid = {}
    for event_name, event in (
        ("주체=이 카드", summon_event(here)),
        ("주체=다른 카드", summon_event(elsewhere)),
        ("주체 없음", bloodless),
    ):
        for source_name, source in (("후보=이 카드", here), ("후보 없음", None)):
            verdict = subject_relation(_other(), event, source)
            assert verdict.validity is not ActionValidity.VALID
            assert verdict.permits_execution is False
            grid[(event_name, source_name)] = (
                verdict.validity.value,
                verdict.code.value,
            )

    #: 🔴 **값까지 적어 둔다.** "VALID 가 없다" 만 보면 모든 칸이
    #: ``UNKNOWN`` 으로 뭉개져도 통과한다 — 확정된 거부가 모름으로 바뀌는
    #: 것은 거짓 양성은 아니지만 **거짓 음성 쪽의 손실**이고, 그것도 회귀다.
    assert grid == {
        ("주체=이 카드", "후보=이 카드"): ("invalid", "candidate_not_eligible"),
        ("주체=이 카드", "후보 없음"): ("unknown", "information_unavailable"),
        ("주체=다른 카드", "후보=이 카드"): ("unknown", "rule_not_implemented"),
        ("주체=다른 카드", "후보 없음"): ("unknown", "information_unavailable"),
        ("주체 없음", "후보=이 카드"): ("unknown", "information_unavailable"),
        ("주체 없음", "후보 없음"): ("unknown", "information_unavailable"),
    }


def test_16_self_is_untouched_by_the_new_branch():
    """
    같은 함수의 ``SELF`` 경로가 **글자 그대로** 6-F 그대로다. 새 분기를
    끼워 넣으면서 기존 세 답이 흔들리지 않았는지 같은 격자로 확인한다.
    """
    here, elsewhere = InstanceId(7), InstanceId(9)
    mine = TriggerSpec(
        EffectRef(1, 0), TimingPoint.MONSTER_SUMMONED, subject=TriggerSubject.SELF
    )
    assert subject_relation(mine, summon_event(here), here).permits_execution is True
    refusal = subject_relation(mine, summon_event(elsewhere), here)
    assert refusal.validity is ActionValidity.INVALID
    assert refusal.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert refusal.missing_rule is None

    unscoped = TriggerSpec(EffectRef(1, 0), TimingPoint.MONSTER_SUMMONED)
    missing = subject_relation(unscoped, summon_event(here), here)
    assert missing.missing_rule == SUBJECT_MISSING_RULE


# ======================================================================
# D. 두 계층이 같은 답을 낸다 — 실제 판에서
# ======================================================================


@pytest.fixture
def alexander_and_featherman(repository):
    """
    알렉산더를 필드에 두고 **페더맨을 실제로 일반 소환한** 판.

    사건은 전부 실제 ``Duel.apply`` 가 만든 기록에서 나온다 — 소환을
    지어내지 않는다.
    """
    duel = Duel.start(
        repository=repository, decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20), seed=5
    )
    alexander = duel.state.create_instance(
        OTHER_SUMMON_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    action = next(
        a for a in duel.legal_actions(MINE) if a.kind.value == "normal_summon"
    )
    step = duel.apply(action)
    assert step.accepted, step.reason
    return duel, alexander.instance_id


@requires_official_db
def test_17_another_cards_summon_leaves_both_layers_at_unknown(
    repository, alexander_and_featherman
):
    """
    **실제 사건** — 다른 카드(페더맨)가 소환되었다. 「이 카드 이외」 는
    만족될 수도 있지만, 이 카드도 그 사건에 함께 포함되었는지를 알 길이
    없으므로 **모름**이다.

    🔴 수집기와 판정기가 **둘 다** 모름이어야 한다. 한쪽만 보면 다른 쪽이
    조용히 승격시키는 것을 못 본다.
    """
    duel, alexander = alexander_and_featherman
    registry = registry_from(repository, [OTHER_SUMMON_CARD])
    view = duel.view(MINE)
    #: 🔴 **실제 생산 경로를 지난다** — journal 기록을 ``EventPipeline`` 에
    #: 그대로 넘긴다 (6-F 의 ``test_11`` 과 같은 방식). 사건을 손으로
    #: 만들지 않는다.
    pipeline = EventPipeline(view, registry, None)
    judge = TriggerEligibilityJudge(view, None)

    seen = 0
    for record in duel.journal.events:
        for observation in pipeline.collect(record, actor=record.actor):
            timing = observation.event.timing
            if timing.point is not TimingPoint.MONSTER_SUMMONED:
                continue
            for candidate in observation.candidates:
                if candidate.source != alexander:
                    continue
                seen += 1
                assert candidate.status is TriggerStatus.UNKNOWN
                assert candidate.code is ValidationCode.RULE_NOT_IMPLEMENTED
                spec = next(
                    s
                    for s in registry.watching(timing)
                    if s.effect_ref == candidate.effect_ref
                )
                eligibility = judge.judge(candidate, spec, timing)
                gate = eligibility.gate(EligibilityGate.EVENT_RELATION)
                assert gate.result.validity is ActionValidity.UNKNOWN
                assert gate.result.missing_rule == GROUP_MEMBERSHIP_RULE
                #: 🔴 **모름은 통과가 아니다.**
                assert eligibility.status is not TriggerStatus.ELIGIBLE
    assert seen >= 1, "알렉산더가 실제 사건에서 후보로 수집되지 않았습니다"


@requires_official_db
def test_18_its_own_summon_is_refused_by_both_layers(repository):
    """
    **실제 인스턴스**가 주체인 사건 — 알렉산더 자신이 소환되었다. 그러면
    「이 카드 이외」 가 거짓으로 확정되고, 두 계층이 **같은 거부**를 낸다.

    🔴 6-F 가 적어 둔 차단 요인이 여기에도 있다 — ``SINGLE`` 트리거를 가진
    효과 몬스터는 엔진이 실제로 소환해 주지 않으므로 (``assess_normal_summon``
    이 ``UNDETERMINED``), 지어낸 것은 **그 delta 를 만든 행동 하나**뿐이고
    인스턴스 · 관측 · 수집기 · 판정기는 전부 실제다.
    """
    duel = Duel.start(
        repository=repository,
        decks=([OTHER_SUMMON_CARD] * 20, [FEATHERMAN] * 20),
        seed=7,
    )
    duel.state.turn.set_phase(Phase.MAIN1)
    alexander = duel.state.create_instance(
        OTHER_SUMMON_CARD, owner=MINE, zone=Zone.MZONE, position=Position.FACEUP_ATTACK
    )
    registry = registry_from(repository, [OTHER_SUMMON_CARD])
    event = summon_event(alexander.instance_id)

    pairs = [
        pair
        for pair in both_layers(duel.view(MINE), registry, event)
        if pair[0].source == alexander.instance_id
    ]
    assert pairs
    for candidate, eligibility in pairs:
        assert candidate.status is TriggerStatus.INELIGIBLE
        assert candidate.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
        gate = eligibility.gate(EligibilityGate.EVENT_RELATION)
        assert gate.result.validity is ActionValidity.INVALID
        assert gate.result.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE
        assert eligibility.status is TriggerStatus.INELIGIBLE


@requires_official_db
def test_19_no_input_promotes_an_other_registration_to_eligible(
    repository, alexander_and_featherman
):
    """
    🔴 **§16-6 의 직접 검증.** 실제 판의 **모든 사건**에 대해, ``OTHER``
    등록이 ``ELIGIBLE`` 이 되는 경우가 하나도 없어야 한다.

    사례 하나가 아니라 그 판이 만든 기록 전부를 돈다 — 승격 경로는 보통
    "생각하지 않은 사건" 에서 열린다.
    """
    duel, alexander = alexander_and_featherman
    registry = registry_from(repository, [OTHER_SUMMON_CARD])
    view = duel.view(MINE)
    pipeline = EventPipeline(view, registry, None)
    judge = TriggerEligibilityJudge(view, None)

    seen = 0
    for record in duel.journal.events:
        for observation in pipeline.collect(record, actor=record.actor):
            timing = observation.event.timing
            for candidate in observation.candidates:
                if candidate.source != alexander:
                    continue
                seen += 1
                spec = next(
                    s
                    for s in registry.watching(timing)
                    if s.effect_ref == candidate.effect_ref
                )
                eligibility = judge.judge(candidate, spec, timing)
                assert candidate.status is not TriggerStatus.ELIGIBLE
                assert eligibility.status is not TriggerStatus.ELIGIBLE
                assert eligibility.may_activate is False
    assert seen >= 1, "OTHER 등록이 한 번도 후보가 되지 않았습니다"


# ======================================================================
# E. 복수 카드 사건 — 왜 통과시킬 수 없는가 (STRUCTURAL-35)
# ======================================================================


def test_20_the_engine_event_carries_one_subject_not_a_group():
    """
    🔴 **구조 핀.** 이 축이 거부만 하는 이유가 여기에 있다 — 사건이 주체
    **한 장**만 들고 있어서 "그룹에 이 카드도 있는가" 를 물을 데가 없다.

    나중에 사건이 그룹을 들게 되면 이 테스트가 먼저 깨지고, 그때 ``OTHER``
    의 모름이 답으로 바뀔 수 있다. 그 전에는 바꿀 근거가 없다.
    """
    event = summon_event(InstanceId(7))
    assert event.instance == InstanceId(7)
    #: 사건이 **여러 장**을 담을 칸이 없다.
    assert not [
        name
        for name in dir(event)
        if name in {"instances", "group", "subjects", "cards"}
    ]


# ======================================================================
# F. 전후 지표 — 전수
# ======================================================================


@requires_official_db
def test_21_the_census_moved_only_where_it_was_supposed_to(repository):
    """
    전수 조사 한 번으로 §11 의 지표를 전부 센다. 같은 corpus 를 두 번 돌지
    않는다 (분석기 호출이 비싸다).

    확인하는 것 넷:

    1. 주체 축: ``None`` **784 → 704**, ``OTHER`` **80**, ``SELF`` 불변.
    2. 선언(``SELF``) 과 주장이 **겹치는 등록 0건**.
    3. 6-G 의 영역 축이 **816 그대로**다.
    4. 주장이 붙은 블록 중 트리거가 아닌 것 **54건** (등록되지 않는다).
    """
    analyzer = EffectAnalyzer(repository)
    subjects_before = {"self": 0, "other": 0, "none": 0}
    subjects_after = dict(subjects_before)
    zones_before = zones_after = 0
    clash = 0
    claimed_not_a_trigger = 0
    other_cards = set()

    for card in repository.all_cards():
        if card.script is None:
            continue
        for ordinal, effect in enumerate(analyzer.analyze(card).effects):
            shared = dict(
                declared_types=effect.effect_types,
                event_code=effect.raw.code,
                ranges=effect.raw.ranges,
            )
            before = compile_trigger_spec(EffectRef(card.id, ordinal), **shared)
            after = compile_trigger_spec(
                EffectRef(card.id, ordinal),
                event_subject_claim=effect.event_subject_claim,
                **shared,
            )
            registered = before is not None and before.is_registered
            if effect.event_subject_claim is not None and not registered:
                claimed_not_a_trigger += 1
            if not registered:
                continue
            subjects_before[
                before.spec.subject.value if before.spec.subject else "none"
            ] += 1
            subjects_after[
                after.spec.subject.value if after.spec.subject else "none"
            ] += 1
            if (
                before.spec.subject is TriggerSubject.SELF
                and effect.event_subject_claim is not None
            ):
                clash += 1
            if after.spec.subject is TriggerSubject.OTHER:
                other_cards.add(card.id)
            zones_before += bool(
                before.spec.activates_from or before.spec.from_zones
            )
            zones_after += bool(after.spec.activates_from or after.spec.from_zones)

    assert subjects_before == {"self": 3389, "other": 0, "none": 784}
    assert subjects_after == {"self": 3389, "other": 80, "none": 704}
    assert len(other_cards) == 64
    #: 🔴 선언과 조건이 어긋나는 등록이 **없다.** 하나라도 생기면
    #: ``test_10`` 이 지키는 우선순위가 실제로 쓰이기 시작하는 것이고,
    #: 그때는 분류기를 다시 봐야 한다.
    assert clash == 0
    assert zones_before == 816
    assert zones_after == 816
    assert claimed_not_a_trigger == 54


# ======================================================================
# G. §10 — 실제 실행으로 이어지는 최소 수직 시나리오
# ======================================================================

#: 욕망의 항아리 — ``EFFECT_LIBRARY`` 에서 ``executable=True`` 이고 **드로우
#: 사건을 실제로 만든다** (``EffectExecutor`` 가 뽑힌 장마다 ``CardDrawn``
#: 를 낸다). 엔진이 만들 수 있는 사건 중 트리거가 반응할 수 있는 것을 찾는
#: 측정에서 나왔다.
POT_OF_GREED = 55144522

#: 수호신관 마하드 — 공식 원문 「①: **이 카드를 드로우했을 때**, 이 카드를
#: 상대에게 보여주고 발동할 수 있다」. 등록이 ``SINGLE``(→ ``SELF``) ·
#: ``EVENT_DRAW``(→ ``card_drawn``) · ``SetRange(HAND)``(→ 발동 위치 ``HAND``)
#: 라서 **6-F 의 주체 축과 6-G 의 위치 축이 동시에 답을 갖는** 등록이다.
DRAWN_TRIGGER_CARD = 71703785


@requires_official_db
def test_22_a_real_draw_passes_both_axes_and_names_what_is_left(repository):
    """
    🔴 **§10 — 최소 수직 시나리오가 실제로 존재한다.**

    지어낸 delta 가 하나도 없다. 실제 ``GameState`` 에서 실제 ``EffectActivator``
    → ``Chain`` → ``ChainResolver`` → ``EffectExecutor`` 를 지나 욕망의 항아리를
    해결하고, 그것이 낸 **실제 ``CardDrawn``** 을 ``EventReader`` 가 읽어
    수집기와 판정기에 넘긴다::

        GameState (덱 맨 위 = 마하드)
            ↓  욕망의 항아리 발동 · 해결   ← 실제 실행 구현 (executable=True)
        CardDrawn(card=#0) · CardDrawn(card=#1)
            ↓  EventReader → TriggerCollector
        TriggerCandidate(effect_ref=마하드 e[0], source=#0)
            ↓  TriggerEligibilityJudge
        event_relation  VALID     ← 6-F 의 주체 축
        activation_zone VALID     ← 6-G 의 위치 축
        나머지 셋       UNKNOWN   ← 여기가 다음 단계다

    그리고 **다른 사본은 거부된다** — 같은 카드 ID 의 사본 #1 은 #0 의 드로우
    사건에서 후보가 아니다. 이것이 6-F 가 세운 인스턴스 구분이 실제 사건에서
    작동한다는 증거다.
    """
    from engine.action import PlayerAction
    from engine.activation import ActivationStatus, EffectActivator
    from engine.chain import Chain, ChainResolutionStatus, ChainResolver
    from engine.effect.library import (
        build_executor,
        definition_registry,
        implementation_registry,
    )
    from engine.event_pipeline import EventReader
    from engine.game_state_view import GameStateView
    from engine.state.game_state import GameState
    from engine.validation import ValidationResult

    state = GameState.create(
        repository, decks=([DRAWN_TRIGGER_CARD] * 10 + [POT_OF_GREED],
                           [DRAWN_TRIGGER_CARD] * 10)
    )
    state.turn.set_phase(Phase.MAIN1)
    #: 세트 · 발동 타이밍은 이 단계의 관심이 아니다 — 카드를 발동할 수 있는
    #: 자리에 놓는 방식은 ``test_real_card_execution`` 의 ``source_of`` 와 같다.
    pot = next(
        c.instance_id for c in state.player(MINE).deck if c.card_id == POT_OF_GREED
    )
    state.move(pot, Zone.SZONE, to_player=MINE, position=Position.FACEUP)
    top = [c.instance_id for c in state.player(MINE).deck[:2]]

    registry = registry_from(repository, [DRAWN_TRIGGER_CARD])
    drawn_specs = [
        s for s in registry.specs if s.point is TimingPoint.CARD_DRAWN
    ]
    assert len(drawn_specs) == 1
    assert drawn_specs[0].subject is TriggerSubject.SELF
    assert drawn_specs[0].activates_from == frozenset({Zone.HAND})

    definitions = definition_registry()
    activated = EffectActivator(definitions, implementation_registry()).activate(
        state,
        Chain(),
        PlayerAction.activate_effect(
            actor=MINE, source=pot, effect_ref=EffectRef(POT_OF_GREED, 0)
        ),
        (),
        authorization=ValidationResult.valid(),
    )
    assert activated.status is ActivationStatus.ACTIVATED
    resolution = ChainResolver(build_executor(None), definitions).resolve_top(
        state, activated.chain
    )
    assert resolution.status is ChainResolutionStatus.RESOLVED

    #: 실제로 **그 두 장이 패에 왔다.**
    assert [c.instance_id for c in state.player(MINE).hand] == top

    view = GameStateView.from_state(state, viewer=MINE)
    events = EventReader(view).read(resolution, actor=MINE)
    assert [e.timing.point for e in events] == [
        TimingPoint.CARD_DRAWN,
        TimingPoint.CARD_DRAWN,
    ]
    assert [e.timing.instance for e in events] == top

    verdicts = {}
    for event in events:
        for candidate, eligibility in both_layers(
            view, registry, event.timing, definitions
        ):
            verdicts[(event.timing.instance, candidate.source)] = (
                candidate.status,
                {g.gate: g.result.validity for g in eligibility.gates},
                eligibility.status,
            )

    #: 🔴 **자기 자신의 드로우에서 두 축이 모두 통과한다.**
    for instance in top:
        status, gates, overall = verdicts[(instance, instance)]
        assert gates[EligibilityGate.EVENT_RELATION] is ActionValidity.VALID
        assert gates[EligibilityGate.ACTIVATION_ZONE] is ActionValidity.VALID
        #: 그리고 **남은 셋이 다음 단계를 가리킨다.** 통과한 둘이 전체를
        #: 승격시키지 않는다 — 부분 통과는 ``ELIGIBLE`` 이 아니다 (§8).
        assert gates[EligibilityGate.TRIGGER_CONDITION] is ActionValidity.UNKNOWN
        assert gates[EligibilityGate.EXECUTION_AUTHORITY] is ActionValidity.UNKNOWN
        assert gates[EligibilityGate.COST_FEASIBILITY] is ActionValidity.UNKNOWN
        assert status is TriggerStatus.UNKNOWN
        assert overall is TriggerStatus.UNKNOWN

    #: 🔴 **다른 사본은 확정 거부다** — 인스턴스 구분이 실제 사건에서 산다.
    first, second = top
    for drawn, other in ((first, second), (second, first)):
        status, gates, overall = verdicts[(drawn, other)]
        assert gates[EligibilityGate.EVENT_RELATION] is ActionValidity.INVALID
        assert status is TriggerStatus.INELIGIBLE
        assert overall is TriggerStatus.INELIGIBLE
