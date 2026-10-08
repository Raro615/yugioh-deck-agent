"""
Phase 3-E-33 — ``EffectDefinition.activation`` 출처·분리 가능성 감사.

핵심 질문: **``activation`` 이 원본 Lua 의 발동 조건을 얼마나 정확하게
보존하고 있고, ``SetCondition`` 과 ``SetTarget`` 을 서로 다른 의미로 안전하게
구분하고 있는가.**

이름을 보고 추측하지 않는다. ``SetCondition`` 이라고 조건이라 읽지 않고,
``SetTarget`` 이라고 대상 선택이라 읽지 않는다. 원본 Lua 의 함수 본문까지
읽고, 전수 측정한 결과만 고정한다.

측정으로 드러난 여섯 가지
-------------------------

1. **``SetCondition`` 과 ``SetTarget`` 은 독립이다.** 34,631개 효과 블록을
   전수 교차 집계하면 네 범주가 **모두** 비어 있지 않다 — 조건X/대상X
   11,626 · 조건X/대상O 10,568 · 조건O/대상O 8,694 · 조건O/대상X 3,743.
   "대상이 있으면 조건이 있다" 도 "조건이 있으면 대상이 필요하다" 도
   **거짓**이다.

2. **``EVENT_FREE_CHAIN`` ≠ "발동 조건 없음".** ``EVENT_FREE_CHAIN`` 블록
   4,909개 중 **1,419개**에 ``SetCondition`` 이 있다 (28.9%). 등재된 16개
   중에서도 의적의 입문서(69091732)가 그렇다.

3. **``SetTarget`` 의 ``chk==0`` 분기는 대상 선택이 아니라 발동 적법성이다.**
   욕망의 항아리는 ``s.target`` 의 ``chk==0`` 에서
   ``Duel.IsPlayerCanDraw(tp,2)`` 를 돌려주고, 대상 선택은 ``chk~=0`` 쪽에
   있다. 둘은 **같은 Lua 함수 안의 다른 분기**다.

4. **그래서 ``activation`` 은 두 출처를 섞어 들고 있다.** 등재된 16개 중
   ``activation`` 이 있는 것은 8개인데, 그중 **7개**는 ``SetCondition`` 이
   아예 없는 효과다 (``ActivationCondition.has_condition_function`` 이
   ``False``). 전부 ``s.target`` 의 ``chk==0`` 에서 옮겨 왔다. 그 사실은
   ``engine/effect/library.py`` 의 **주석 산문에만** 적혀 있고, 구조적으로
   구분할 칸이 없다.

5. **``Condition | None = None`` 의 뜻이 ``engine/`` 안에서 둘로 갈린다.**
   ``EffectDefinition.activation`` 은 "조건이 없다는 뜻이 아니라 적지
   않았다는 뜻" 이라 적고, ``ObservationGrant.condition`` 은 "``None`` 은
   '조건이 없다' 는 뜻" 이라 적는다. **같은 타입·같은 기본값·반대 계약이다.**

6. **정보는 잃지 않았다.** ``SetCondition`` · ``SetTarget`` 원문은
   ``analysis`` 계층(``ActivationCondition.raw`` ·
   ``has_condition_function``)에서 여전히 읽을 수 있다. production 이 아직
   읽지 않는 것과 데이터가 사라진 것은 다른 사실이다.

이 Phase 는 production 을 고치지 않았다. 감사다.
"""

import ast
import pathlib

import pytest

from analysis.effect_analyzer import EffectAnalyzer
from engine.activation import ActivationStatus
from engine.condition import (
    Always,
    Condition,
    ConditionResult,
    PlayerRef,
    UnimplementedRule,
    ZoneCountAtLeast,
)
from engine.effect.definition import EffectDefinition
from engine.effect.library import EFFECT_LIBRARY
from engine.effect.resolution import ResolutionStatus
from engine.observation_grant import ObservationGrant
from engine.validation import ValidationCode
from engine.vocabulary import Zone

from tests.conftest import requires_official_db

#: 발동 계층을 **그대로** 부르는 기존 도구를 다시 쓴다. 새 하네스를 만들면
#: production 이 아니라 하네스를 시험하게 된다.
from tests.test_validation_code_consistency import (
    activate,
    new_state,
    resolve,
    synthetic,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ======================================================================
# 측정값 — 전부 저장소에서 센 수다. 바뀌면 그것이 신호다.
# ======================================================================

#: 효과 블록 총합 (``EffectRef.ordinal`` 기준).
#:
#: 🔴 Phase 3-F-28 에서 34,631 → 34,632 (로더가 블록 주석 안의 효과를 세던 것을
#: 그만두고(``c9409625`` −1), ``c:RegisterEffect`` 로 이 카드에 등록되는 ``local``
#: 없는 / ``e`` 로 시작하지 않는 블록을 세기 시작했다(``c9839115`` · ``c74506079``
#: +2)). 이 테스트가 세는
#: 네 범주 중 ``(False, False)`` 하나만 +1 이고 나머지 셋과
#: ``WITH_CONDITION`` · ``WITH_TARGET`` · ``WITH_COST`` ·
#: ``FREE_CHAIN_*`` 은 **그대로다** — 새로 세는 두 블록과 더 이상 세지
#: 않는 한 블록 모두 ``SetCondition`` · ``SetTarget`` 이 없다.
TOTAL_BLOCKS = 34632

#: 네 범주 ``(SetCondition 있음, SetTarget 있음) → 블록 수``.
QUADRANTS = {
    (False, False): 11627,
    (False, True): 10568,
    (True, True): 8694,
    (True, False): 3743,
}

#: 슬롯별 블록 수.
WITH_CONDITION = 12437
WITH_TARGET = 19262
WITH_COST = 5007

#: ``EVENT_FREE_CHAIN`` 블록과 그중 ``SetCondition`` 이 있는 수.
FREE_CHAIN_BLOCKS = 4909
FREE_CHAIN_WITH_CONDITION = 1419

#: §11 여섯 사례. **이름으로 고르지 않았다** — 전수 주사에서 처음 나온
#: 두 장씩이고, ``test_02``~``test_05`` 가 그 분류 자체를 다시 검증한다.
CASE_CONDITION_ONLY = ((847915, 0), (885016, 0))
CASE_TARGET_ONLY = ((27551, 0), (35699, 2))
CASE_BOTH = ((111280, 0), (126218, 0))
CASE_NEITHER = ((2511, 0), (164710, 0))
#: ``EVENT_FREE_CHAIN`` 이 아닌 블록 — 한 카드 안에서 블록마다 다르다.
CASE_NOT_FREE_CHAIN = ((2511, 1), (2511, 2))

#: 등재된 유일한 ``SetCondition`` 보유 효과 (의적의 입문서).
GALLANTRY = 69091732
#: ``activation`` 이 있는데 Lua 에 ``SetCondition`` 이 **없는** 7개.
#: 전부 ``s.target`` 의 ``chk==0`` 에서 옮겨 왔다.
ACTIVATION_FROM_SET_TARGET = (
    55144522,  # 욕망의 항아리   — Duel.IsPlayerCanDraw(tp,2)
    5915629,  # 욕망의 선물      — Duel.IsPlayerCanDraw(1-tp,2)
    70368879,  # 갑부 고블린     — Duel.IsPlayerCanDraw(tp,1)
    92595643,  # 벌금            — IsExistingMatchingCard(... LOCATION_HAND ... 2 ...)
    81439173,  # 어리석은 매장   — IsExistingMatchingCard(... LOCATION_DECK ... 1 ...)
    73148972,  # 무정한 말살     — IsExistingTarget(...) and GetFieldGroupCount(...)>0
    22589918,  # 리로드          — IsPlayerCanDraw(tp) and IsExistingMatchingCard(... HAND ...)
)


# ======================================================================
# 도구
# ======================================================================


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


class _StripStrings(ast.NodeTransformer):
    """문자열 리터럴을 비운다 — docstring 안의 이름이 '사용' 으로 세어지지 않게."""

    def visit_Constant(self, node):  # noqa: N802 - ast 규약
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=""), node)
        return node


def code_only(path: str) -> str:
    """주석·docstring 을 걷어낸 **실행 코드만**.

    🔴 Phase 3-F-29 추가 — 원문 문자열 검색은 주석과 코드를 구분하지 못한다.
    """
    return ast.unparse(_StripStrings().visit(ast.parse(source_of(path))))


def lua_of(card_id: int) -> str:
    return (PROJECT_ROOT / f"c{card_id}.lua").read_text(
        encoding="utf-8", errors="replace"
    )


def slots_of(card_id: int) -> list[dict[str, str]]:
    """
    카드 하나의 효과 블록별 ``Set*`` 슬롯 인자.

    production 의 유일한 슬롯 독자 — ``analysis/effect_analyzer.py`` 의
    ``_collect_handlers`` — 를 **그대로** 부른다. 블록 순서는
    ``sources/lua_loader.py`` 와 같으므로 ``EffectRef.ordinal`` 로 짝짓는다.
    """
    source = lua_of(card_id)
    spans = EffectAnalyzer._function_spans(source)
    return [entry["handlers"] for entry in EffectAnalyzer._collect_handlers(source, spans)]


def slot_flags(card_id: int, ordinal: int) -> tuple[bool, bool, bool]:
    """``(SetCondition 있음, SetTarget 있음, SetCost 있음)``."""
    blocks = slots_of(card_id)
    handlers = blocks[ordinal] if ordinal < len(blocks) else {}
    return ("Condition" in handlers, "Target" in handlers, "Cost" in handlers)


def field_docstring(path: str, class_name: str, field_name: str) -> str:
    """
    dataclass **필드**의 docstring. 문자열 검색이 아니라 AST 로 읽는다 —
    주석 한 줄이 옮겨 다녀도 계약은 같은 자리에 있다.
    """
    tree = ast.parse(source_of(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        body = node.body
        for index, stmt in enumerate(body):
            if not (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == field_name
            ):
                continue
            following = body[index + 1] if index + 1 < len(body) else None
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                return following.value.value
            return ""
    raise AssertionError(f"{path}:{class_name}.{field_name} 를 찾지 못했습니다.")


@pytest.fixture(scope="module")
def corpus(repository):
    """
    ``(card_id, ordinal, code, 조건있음, 대상있음, 비용있음)`` 전부.

    한 번만 훑는다 (약 2초). **건너뛴 스크립트가 있으면 측정이 거짓이 되므로**
    0 임을 함께 검증한다.
    """
    rows: list[tuple[int, int, str | None, bool, bool, bool]] = []
    skipped = 0
    for card in repository.all_cards():
        if card.script is None:
            continue
        if not (PROJECT_ROOT / f"c{card.id}.lua").is_file():
            skipped += 1
            continue
        try:
            blocks = slots_of(card.id)
        except Exception:  # pragma: no cover - 방어: 하나도 없어야 한다
            skipped += 1
            continue
        for ordinal, block in enumerate(card.script.effects):
            handlers = blocks[ordinal] if ordinal < len(blocks) else {}
            rows.append(
                (
                    card.id,
                    ordinal,
                    block.code,
                    "Condition" in handlers,
                    "Target" in handlers,
                    "Cost" in handlers,
                )
            )
    assert skipped == 0, f"스크립트 {skipped}개를 못 읽었습니다 — 측정이 불완전합니다."
    return rows


@pytest.fixture(scope="module")
def analyses(repository):
    """등재 효과별 ``EffectAnalysis`` — ``analysis`` 공개 경로로만 얻는다."""
    analyzer = EffectAnalyzer(repository)
    result = {}
    for entry in EFFECT_LIBRARY:
        ref = entry.definition.effect_ref
        result[ref] = analyzer.analyze(repository.get(ref.card_id)).effects[ref.ordinal]
    return result


# ======================================================================
# Test 1 — Condition 과 Target 은 독립이다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_01_condition_and_target_are_independent_across_the_whole_corpus(corpus):
    """
    **Test 1 (§18): 둘이 독립적으로 존재할 수 있는가 → 네 범주가 모두 있다.**

    둘 중 하나로 다른 하나를 추론하려는 시도는 양방향 모두 실패한다. 그래서
    ``EffectDefinition`` 이 ``activation`` 과 ``targets`` 를 **다른 칸**에
    들고 있는 것은 중복이 아니라 필요다.
    """
    assert len(corpus) == TOTAL_BLOCKS

    counted: dict[tuple[bool, bool], int] = {}
    for _, _, _, has_condition, has_target, _ in corpus:
        key = (has_condition, has_target)
        counted[key] = counted.get(key, 0) + 1

    assert counted == QUADRANTS
    #: 네 범주가 **모두** 비어 있지 않다 — 이것이 독립의 증거다.
    assert all(count > 0 for count in counted.values())

    assert sum(1 for row in corpus if row[3]) == WITH_CONDITION
    assert sum(1 for row in corpus if row[4]) == WITH_TARGET
    assert sum(1 for row in corpus if row[5]) == WITH_COST

    #: 두 명제가 모두 거짓이다.
    assert QUADRANTS[(False, True)] > 0, "'대상이 있으면 조건이 있다' 는 거짓"
    assert QUADRANTS[(True, False)] > 0, "'조건이 있으면 대상이 필요하다' 는 거짓"


# ======================================================================
# Test 2~5 — 네 범주의 실제 카드
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_02_condition_without_target_exists_in_real_cards(repository):
    """
    **Test 2 (§18): ``SetCondition`` 만 있는 사례.**

    넘버즈 월은 이름 붙은 함수(``s.actcon``)로, 멀티유니버스는 인라인
    람다로 조건을 적는다 — **적는 모양이 둘이고 둘 다 조건이다.** 어느
    쪽이든 ``SetTarget`` 은 없다.
    """
    for card_id, ordinal in CASE_CONDITION_ONLY:
        card = repository.get(card_id)
        assert card is not None and card.script is not None
        has_condition, has_target, _ = slot_flags(card_id, ordinal)
        assert has_condition is True
        assert has_target is False
        assert card.script.effects[ordinal].code == "EVENT_FREE_CHAIN"

    #: 모양이 다르다는 사실 자체를 고정한다 — 하나는 참조, 하나는 본문.
    named = slots_of(847915)[0]["Condition"]
    inline = slots_of(885016)[0]["Condition"]
    assert named == "s.actcon"
    assert inline.startswith("function(")
    assert "IsExistingMatchingCard" in inline


@requires_official_db
@pytest.mark.real_card
def test_03_target_without_condition_exists_in_real_cards(repository):
    """
    **Test 3 (§18): ``SetTarget`` 만 있는 사례.**

    리미트 리버스·SPYRAL－보텍스 둘 다 ``SetCondition`` 이 없다. 여기서
    ``SetTarget`` 을 조건으로 읽으면 "조건이 없는 카드" 가 "조건이 있는
    카드" 로 바뀐다.
    """
    for card_id, ordinal in CASE_TARGET_ONLY:
        card = repository.get(card_id)
        assert card is not None and card.script is not None
        has_condition, has_target, _ = slot_flags(card_id, ordinal)
        assert has_condition is False
        assert has_target is True

    #: 같은 카드의 다른 블록은 다를 수 있으므로 ordinal 까지 고정한다.
    assert slots_of(35699)[2]["Target"] == "s.destg"
    assert "Condition" not in slots_of(35699)[2]


@requires_official_db
@pytest.mark.real_card
def test_04_condition_and_target_together_exist_in_real_cards(repository):
    """
    **Test 4 (§18): 둘 다 있는 사례.**

    매직 익스팬드는 둘 다 이름 붙은 함수고, 악마의 주사위는 조건이 인라인
    람다(``PHASE_DAMAGE`` 검사)다. 둘을 하나로 합치면 **대상이 있다는
    사실과 조건이 참이라는 사실이 같은 칸에 들어간다.**
    """
    for card_id, ordinal in CASE_BOTH:
        has_condition, has_target, _ = slot_flags(card_id, ordinal)
        assert has_condition is True
        assert has_target is True
        assert repository.get(card_id).script.effects[ordinal].code == "EVENT_FREE_CHAIN"

    dice = slots_of(126218)[0]
    assert dice["Condition"].startswith("function(")
    assert "PHASE_DAMAGE" in dice["Condition"]
    assert dice["Target"] == "s.target"


@requires_official_db
@pytest.mark.real_card
def test_05_neither_condition_nor_target_exists_in_real_cards(repository):
    """
    **Test 5 (§18): 둘 다 없는 사례.**

    그리고 **같은 카드 안에서 블록마다 다르다** — 라뷰린스 쿠클락은
    ``e[0]`` 은 둘 다 없고, ``e[1]`` · ``e[2]`` 는 둘 다 있으며 ``code`` 도
    셋이 다 다르다. 조건과 대상은 **카드가 아니라 블록**의 성질이다.
    """
    for card_id, ordinal in CASE_NEITHER:
        has_condition, has_target, _ = slot_flags(card_id, ordinal)
        assert has_condition is False
        assert has_target is False

    codes = [block.code for block in repository.get(2511).script.effects[:3]]
    assert codes == ["EVENT_FREE_CHAIN", "EVENT_TO_GRAVE", "EFFECT_TRAP_ACT_IN_SET_TURN"]
    assert len(set(codes)) == 3

    for card_id, ordinal in CASE_NOT_FREE_CHAIN:
        has_condition, has_target, _ = slot_flags(card_id, ordinal)
        assert has_condition is True
        assert has_target is True
        assert repository.get(card_id).script.effects[ordinal].code != "EVENT_FREE_CHAIN"


# ======================================================================
# Test 6 — EVENT_FREE_CHAIN + SetCondition 이 "조건 없음" 으로 접히지 않는다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_06_free_chain_with_a_condition_is_not_collapsed_to_no_condition(
    corpus, analyses, repository
):
    """
    **Test 6 (§18): ``EVENT_FREE_CHAIN`` + ``SetCondition``.**

    ``EVENT_FREE_CHAIN`` 블록 4,909개 중 1,419개에 ``SetCondition`` 이
    있다. ``EVENT_FREE_CHAIN`` 을 "조건 없음" 으로 읽으면 그 1,419개가
    전부 틀린다.

    등재된 쪽에서도 확인한다 — 의적의 입문서의 ``s.condition`` 은
    ``Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4`` 이고, 그것이
    ``ZoneCountAtLeast(OPPONENT, HAND, 5)`` 로 **실제로 옮겨져 있다.**
    """
    free_chain = [row for row in corpus if row[2] == "EVENT_FREE_CHAIN"]
    assert len(free_chain) == FREE_CHAIN_BLOCKS
    assert sum(1 for row in free_chain if row[3]) == FREE_CHAIN_WITH_CONDITION

    entry = next(
        e for e in EFFECT_LIBRARY if e.definition.effect_ref.card_id == GALLANTRY
    )
    definition = entry.definition
    assert repository.get(GALLANTRY).script.effects[0].code == "EVENT_FREE_CHAIN"
    assert slot_flags(GALLANTRY, 0)[0] is True

    #: 접히지 않았다 — ``None`` 이 아니다.
    assert definition.activation is not None
    assert definition.activation == ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 5)
    #: 원본의 ``>4`` 와 옮긴 쪽의 ``5`` 가 같은 사실임을 Lua 로 확인한다.
    assert "LOCATION_HAND)>4" in lua_of(GALLANTRY)
    #: analysis 계층도 같은 사실을 들고 있다.
    assert analyses[definition.effect_ref].activation.has_condition_function is True
    assert analyses[definition.effect_ref].activation.raw == "s.condition"


# ======================================================================
# Test 7 — UNKNOWN 은 FALSE 가 되지 않는다
# ======================================================================


def test_07_an_unknown_activation_condition_never_becomes_false():
    """
    **Test 7 (§18): ``UNKNOWN`` 조건이 ``FALSE`` 로 바뀌지 않는다.**

    발동 계층과 해결 계층을 **둘 다** 부른다. 두 계층이 다르게 읽으면 같은
    정의가 두 뜻을 갖는다. 그리고 ``UNKNOWN`` 도 ``FALSE`` 도 **판을 바꾸지
    않는다** — 모름은 허가가 아니다.
    """
    unknown_definition = synthetic(activation=UnimplementedRule("아직 없는 규칙"))
    false_definition = synthetic(activation=Always(ConditionResult.FALSE))

    for definition, activation_status, resolution_status in (
        (
            unknown_definition,
            ActivationStatus.CONDITION_UNKNOWN,
            ResolutionStatus.CONDITION_UNKNOWN,
        ),
        (
            false_definition,
            ActivationStatus.CONDITION_FALSE,
            ResolutionStatus.CONDITION_FALSE,
        ),
    ):
        state = new_state()
        before = state.state_hash()
        activated = activate(state, definition)
        assert activated.status is activation_status
        assert state.state_hash() == before
        assert len(activated.chain) == 0

        resolved = resolve(new_state(), definition)
        assert resolved.status is resolution_status

    #: 모름이 거부로 접히지 않는다 — 두 상태는 **다른 칸**이다.
    unknown = activate(new_state(), unknown_definition)
    assert unknown.status is not ActivationStatus.CONDITION_FALSE
    assert unknown.status is not ActivationStatus.ACTIVATED
    assert unknown.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert "아직 없는 규칙" in (unknown.missing or "")

    #: ``UNKNOWN`` · ``FALSE`` · "적지 않았다" 세 가지가 모두 표현 가능하고
    #: 서로 다른 결과를 낸다 (§8-7/8/9).
    silent = activate(new_state(), synthetic(activation=None))
    assert silent.status is ActivationStatus.ACTIVATED
    always = activate(new_state(), synthetic(activation=Always()))
    assert always.status is ActivationStatus.ACTIVATED


# ======================================================================
# Test 8 — 대상 요구와 발동 조건은 같은 의미가 아니다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_08_a_target_requirement_is_not_an_activation_condition():
    """
    **Test 8 (§18): 대상 요구가 발동 조건과 같은 의미로 취급되지 않는다.**

    네 가지로 확인한다.

    1. ``EffectDefinition`` 에 **다른 칸**이다 (``activation`` · ``targets``).
    2. ``canonical_state()`` 에서도 **다른 자리**다 — 합쳐지면 상태 해시가
       둘을 구별하지 못하게 된다.
    3. 발동 계층의 거부 상태가 **다른 enum 멤버**다 (조건 2개 · 대상 2개 ·
       비용 2개).
    4. 등재된 실제 데이터에서 둘이 **독립적으로** 나타난다 — 욕망의 항아리는
       조건만, 싸이크론은 대상만 있다.
    """
    fields = {f.name for f in __import__("dataclasses").fields(EffectDefinition)}
    assert {"activation", "targets"} <= fields

    #: 2. 직렬화에서도 자리가 다르다.
    with_condition = synthetic(activation=Always())
    without = synthetic(activation=None)
    assert with_condition.canonical_state() != without.canonical_state()
    assert without.canonical_state()[3] is None
    assert with_condition.canonical_state()[3] is not None
    #: ``targets`` 는 그 다음 자리이고 둘 다 비어 있다 — 섞이지 않았다.
    assert with_condition.canonical_state()[5] == without.canonical_state()[5] == ()

    #: 3. 조건·대상·비용이 각각 두 칸씩 따로 있다.
    for name in (
        "CONDITION_FALSE",
        "CONDITION_UNKNOWN",
        "INVALID_TARGET",
        "UNCHECKED_TARGET",
        "COST_UNPAYABLE",
        "COST_UNKNOWN",
    ):
        assert name in ActivationStatus.__members__
    assert (
        ActivationStatus.CONDITION_FALSE
        is not ActivationStatus.INVALID_TARGET
        is not ActivationStatus.COST_UNPAYABLE
    )

    #: 4. 실제 등재 데이터 — 한쪽만 있는 경우가 둘 다 있다.
    library = {e.definition.effect_ref.card_id: e.definition for e in EFFECT_LIBRARY}
    pot = library[55144522]
    typhoon = library[5318639]
    assert pot.activation is not None and pot.targets == ()
    assert typhoon.activation is None and len(typhoon.targets) == 1


# ======================================================================
# §8 — ``Condition | None = None`` 의 계약이 engine/ 안에서 둘로 갈린다
# ======================================================================


def test_09_the_same_type_and_default_carry_opposite_contracts_in_engine():
    """
    **이 Phase 의 중심 발견.**

    ``engine/`` 안의 두 production dataclass 가 ``Condition | None = None``
    에 **반대 뜻**을 적는다. 어느 쪽이 맞다고 주장하지 않는다 — 두 계약이
    동시에 적혀 있다는 **사실**을 고정한다. 한쪽을 고치면 여기서 깨지고,
    그때 보고서를 다시 읽게 된다.
    """
    activation_contract = field_docstring(
        "engine/effect/definition.py", "EffectDefinition", "activation"
    )
    grant_contract = field_docstring(
        "engine/observation_grant.py", "ObservationGrant", "condition"
    )

    #: 같은 타입·같은 기본값.
    import dataclasses

    activation_field = next(
        f for f in dataclasses.fields(EffectDefinition) if f.name == "activation"
    )
    grant_field = next(
        f for f in dataclasses.fields(ObservationGrant) if f.name == "condition"
    )
    assert activation_field.type == grant_field.type == "Condition | None"
    assert activation_field.default is grant_field.default is None

    #: 반대 계약.
    assert "조건이 없다는 뜻이 아니라" in activation_contract
    assert "적지 않았다는 뜻" in activation_contract
    assert "조건이 없다" in grant_contract
    assert "UnimplementedRule" in grant_contract
    assert "UnimplementedRule" not in activation_contract


def test_10_both_production_readers_skip_a_none_activation():
    """
    계약이 어떻든 **실행은 하나다** — 두 독자가 모두 ``None`` 을 넘긴다.

    즉 ``None`` 은 적힌 뜻("적지 않았다")과 달리 실행에서는 "조건이 없다"
    처럼 동작한다. 그래서 ``None`` 에 ``SetCondition`` 이 있는 효과를 넣으면
    **조건 없이 발동되는 쪽으로 틀린다.** 지금 등재된 효과 중에 그런 것은
    없다는 것이 ``test_11`` 이고, 이 시험은 그 위험이 실재함을 고정한다.
    """
    silent = synthetic(activation=None)
    assert silent.activation is None
    assert activate(new_state(), silent).status is ActivationStatus.ACTIVATED
    assert resolve(new_state(), silent).status is not ResolutionStatus.CONDITION_UNKNOWN

    #: 두 계층이 같은 문장으로 그 태도를 적는다.
    for path, marker in (
        ("engine/activation.py", 'if definition.activation is None:'),
        ("engine/effect/executor.py", 'if definition.activation is None:'),
    ):
        assert marker in source_of(path)


@requires_official_db
@pytest.mark.real_card
def test_11_no_registered_effect_drops_an_existing_set_condition(analyses):
    """
    **현재 production 에 틀린 판정은 없다** — ``SetCondition`` 이 있으면서
    ``activation`` 이 ``None`` 인 등재 효과는 **하나도 없다.**

    이것이 ``D. ACTIVATION_INFORMATION_LOSS`` 를 고르지 않는 근거다. 다만
    ``test_12`` 가 보이듯 그 보존은 **구조가 보장하는 것이 아니라 손으로
    맞춘 것**이다.
    """
    dropped = []
    for entry in EFFECT_LIBRARY:
        definition = entry.definition
        analysis = analyses[definition.effect_ref]
        if analysis.activation.has_condition_function and definition.activation is None:
            dropped.append(definition.effect_ref)

    assert dropped == []

    #: ``SetCondition`` 이 있는 등재 효과는 의적의 입문서 하나뿐이고,
    #: 그 하나는 옮겨져 있다.
    with_lua_condition = [
        entry.definition.effect_ref
        for entry in EFFECT_LIBRARY
        if analyses[entry.definition.effect_ref].activation.has_condition_function
    ]
    assert [ref.card_id for ref in with_lua_condition] == [GALLANTRY]


@requires_official_db
@pytest.mark.real_card
def test_12_most_registered_activations_come_from_set_target_not_set_condition(
    analyses,
):
    """
    **``activation`` 은 두 출처를 섞어 들고 있고, 구분할 칸이 없다.**

    등재 16개 중 ``activation`` 이 있는 것은 8개. 그중 **7개**는 Lua 에
    ``SetCondition`` 이 아예 없고, ``s.target`` 의 ``chk==0`` 분기에서
    옮겨 왔다. 그 출처는 ``library.py`` 의 **주석 산문에만** 있다.

    이것을 "틀렸다" 고 적지 않는다 — EDOPro 에서 ``chk==0`` 분기는 실제로
    **발동 적법성 검사**이므로 발동 조건 쪽으로 옮기는 것이 의미상 맞다.
    문제는 **그 사실이 데이터에 없다**는 것이다.
    """
    with_activation = [e for e in EFFECT_LIBRARY if e.definition.activation is not None]
    assert len(EFFECT_LIBRARY) == 16
    assert len(with_activation) == 8

    from_target = [
        entry.definition.effect_ref.card_id
        for entry in with_activation
        if not analyses[entry.definition.effect_ref].activation.has_condition_function
    ]
    assert sorted(from_target) == sorted(ACTIVATION_FROM_SET_TARGET)
    assert len(from_target) == 7

    #: 일곱 장 모두 ``SetTarget`` 이 있고 ``chk==0`` 분기를 가진다.
    for card_id in ACTIVATION_FROM_SET_TARGET:
        has_condition, has_target, _ = slot_flags(card_id, 0)
        assert has_condition is False
        assert has_target is True
        assert "chk==0" in lua_of(card_id)

    #: 그리고 **등재 16개 전부** ``SetTarget`` 을 가진다.
    assert all(slot_flags(e.definition.effect_ref.card_id, e.definition.effect_ref.ordinal)[1] for e in EFFECT_LIBRARY)

    #: 출처를 적을 **구조적인 칸이 없다**. 생기면 여기서 깨진다.
    import dataclasses

    names = {f.name for f in dataclasses.fields(EffectDefinition)}
    assert "activation_source" not in names
    assert "activation_provenance" not in names
    #: 산문에는 있다 — 욕망의 항아리의 주석이 ``s.target`` 을 명시한다.
    library_source = source_of("engine/effect/library.py")
    assert "``s.target`` 의 ``Duel.IsPlayerCanDraw(tp,2)``" in library_source
    assert "필요조건이지 충분조건이 아니다" in library_source


# ======================================================================
# §12 · §13 — 정보는 잃지 않았다 / 누가 읽는가
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_13_the_raw_lua_condition_text_is_still_reachable_from_production(
    analyses, repository
):
    """
    **``ACTUALLY_LOST`` 가 아니다.**

    ``SetCondition`` 원문은 ``analysis`` 계층의 공개 경로
    (``EffectAnalyzer.analyze(...).effects[n].activation``) 에서 여전히
    읽힌다. 파서가 보존하는데 실행기가 아직 읽지 않는 것은 **데이터 유실이
    아니다.**
    """
    analyzer = EffectAnalyzer(repository)
    for card_id, ordinal in CASE_CONDITION_ONLY + CASE_BOTH:
        activation = analyzer.analyze(repository.get(card_id)).effects[ordinal].activation
        assert activation.has_condition_function is True
        assert activation.raw is not None and activation.raw != ""

    for card_id, ordinal in CASE_TARGET_ONLY + CASE_NEITHER:
        activation = analyzer.analyze(repository.get(card_id)).effects[ordinal].activation
        assert activation.has_condition_function is False
        assert activation.raw is None

    #: 등재 효과도 같다 — 의적의 입문서의 원문이 남아 있다.
    gallantry = next(
        e for e in EFFECT_LIBRARY if e.definition.effect_ref.card_id == GALLANTRY
    )
    assert analyses[gallantry.definition.effect_ref].activation.raw == "s.condition"

    #: 파서(``sources/lua_loader.py``)는 네 슬롯을 **읽지 않는다** — 그 역할이
    #: ``analysis`` 에 있다는 계층 경계를 고정한다.
    #:
    #: 🔴 Phase 3-F-29 정정 — 원문 문자열 검색이었다. Phase 3-F-29 가 로더
    #: 주석에 ``SetTargetRange`` 를 적자 (``SetTarget`` 을 **부분 문자열로**
    #: 포함한다) 코드가 그대로인데 이 테스트가 깨졌다. 주석과 코드를 구분하는
    #: ``code_only`` 로 바꾼다 — 계약은 같고 **측정이 정확해졌다.**
    loader = code_only("sources/lua_loader.py")
    for slot in ("SetCondition", "SetTarget", "SetOperation"):
        assert slot not in loader, slot
    #: 🔴 그리고 ``analysis`` 는 그 네 슬롯을 **실제로 읽는다** — 경계의 반대쪽.
    #: 🔴 이 쪽은 ``code_only`` 로 볼 수 없다 — 슬롯 이름이 정규식 **문자열
    #: 리터럴** 안에 있어서 문자열을 비우면 같이 사라진다. 그래서 컴파일된
    #: 패턴을 런타임에 읽는다.
    import analysis.effect_analyzer as analyzer_module

    for slot in ("Cost", "Condition", "Target", "Operation"):
        assert slot in analyzer_module._RE_SETTER.pattern, slot


def test_14_only_the_activation_and_execution_layers_read_activation():
    """
    **§13 production reachability** — ``definition.activation`` 을 읽는
    곳은 발동기·실행기·정의 자신·트리거 계층뿐이다. AI/탐색은 읽지 않는다.

    AST 로 센다 — 주석이나 docstring 의 ``activation`` 은 세지 않는다.
    """

    def reads_activation(path: str) -> bool:
        tree = ast.parse(source_of(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "activation"
                and isinstance(node.value, ast.Name)
                and node.value.id in {"definition", "self"}
            ):
                return True
        return False

    for path in (
        "engine/activation.py",
        "engine/effect/executor.py",
        "engine/effect/definition.py",
    ):
        assert reads_activation(path), f"{path} 가 activation 을 읽어야 합니다"

    for path in (
        "engine/duel.py",
        "engine/action_validation.py",
        "engine/activation_timing.py",
        "engine/trigger_chain.py",
        "agent/search.py",
        "agent/simulation.py",
        "agent/evaluation.py",
    ):
        assert not reads_activation(path), f"{path} 는 activation 을 읽지 않습니다"


def test_15_activation_accepts_any_condition_so_nothing_forces_a_new_field():
    """
    ``activation`` 의 타입은 ``Condition`` 하나다. ``UNKNOWN`` ·
    ``FALSE`` · 복합 조건이 **모두 이미 표현 가능**하므로, 이번 발견이
    새 필드나 새 enum 을 요구하지 않는다 (§17 · §20).
    """
    for condition in (
        Always(),
        Always(ConditionResult.FALSE),
        UnimplementedRule("아직 없는 규칙"),
        ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 5),
    ):
        assert isinstance(condition, Condition)
        definition = synthetic(activation=condition)
        assert definition.activation is condition
        #: 직렬화가 왕복한다 — 새 칸 없이 그대로 담긴다.
        assert definition.to_dict()["activation"]["kind"]

    assert synthetic(activation=None).to_dict().get("activation") is None
