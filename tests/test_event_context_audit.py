"""
Phase 3-E-23 — 사건(Event)이 ``TriggerCandidate`` 판정까지 가려면 무엇이 필요한가 (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

한 문장
-------
**사건 문맥을 전달할 곳이 끊긴 것이 아니라, 사건을 묻는 술어가 아직 없다.**
``ConditionContext`` 에 ``event`` 를 더해도 **읽을 코드가 0개**다 — 엔진의 조건
어휘 16개는 전부 "지금 판" 만 묻는다.

측정 (기존 분석기 ``PredicateAnalyzer`` 로 전 corpus 를 센다)
-------------------------------------------------------------
조건 트리가 있는 효과 블록 9,630개 · leaf 20,547개 ::

    NEEDS_CONTEXT   8,511  (41.42%)   ← 사건·체인·직전 상태가 있어야 판정된다
    EVALUABLE       6,684  (32.53%)   ← 지금 판만으로 된다
    UNKNOWN         5,352  (26.05%)   ← 안전하게 해석할 수 없다

``NEEDS_CONTEXT`` 가 요구하는 것은 **EDOPro 의 효과 콜백 서명**
``(e,tp,eg,ep,ev,re,r,rp)`` 그대로다 ::

    self          3,054   event_reason 858 · previous_location 752 · previous_controller 289
    duel          1,788   battle 892 · chain_state 771
    event_group   1,291   eg:IsExists 1,082 · eg:IsContains 209
    player          990   rp==tp 같은 비교
    chain_effect    945   re:IsTrapEffect() 류
    local           424 · chain_card 19

엔진에는 어디까지 있는가
------------------------
* ``CardInstance.previous`` (직전 위치 · 표시 형식 · 컨트롤러) 는 **production
  에서 자동으로 기록된다** (``place``/``set_position``/``set_controller`` 의
  기본값이 ``remember_previous=True``) 그리고 ``canonical_state`` 에 들어가므로
  **이미 판의 모양**이다 — 즉 "한 단계 역사" 는 이미 ``GameState`` 가 소유한다.
* 그런데 그 값을 **읽는 production 코드가 없다.**
* "왜 움직였는가"(reason) · "사건 묶음"(``eg``) · "체인 상대 효과"(``re``) 는
  상태에 **아예 없다** — ``ZoneMoved.movement`` 가 들고 있지만 그 delta 가
  전달되지 않는다 (Phase 3-E-20 · 3-E-22).

그래서 순서가 정해진다
----------------------
① 사건을 묻는 **술어**(조건 어휘)가 먼저 ② 그 술어가 읽을 **문맥**이 다음
③ 그 문맥을 채우는 **전달**이 마지막. 지금은 ③만 이야기해 왔는데, ①이 비어
있으면 ②를 만들어도 소비자가 없다.
"""

import ast
import functools
import pathlib

import pytest

from analysis.predicate_model import EvalReadiness, PredicateKind, PredicateSubject
from engine.action import PlayerAction, PlayerActionKind
from engine.condition.context import ConditionContext
from engine.condition.model import Condition
from engine.duel import Duel
from engine.game_state_view import CardView, GameStateView
from engine.state.card_instance import CardInstance, PreviousState
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
POT_OF_GREED = 55144522
FEATHERMAN = 21844576

#: 사건·체인·직전 상태를 요구하는 술어 종류 (``EvalReadiness.NEEDS_CONTEXT``).
EVENT_DEPENDENT_KINDS = {
    PredicateKind.PREVIOUS_LOCATION,
    PredicateKind.PREVIOUS_POSITION,
    PredicateKind.PREVIOUS_CONTROLLER,
    PredicateKind.EVENT_REASON,
    PredicateKind.GROUP_EXISTS,
    PredicateKind.GROUP_CONTAINS,
    PredicateKind.CHAIN_EFFECT_TYPE,
    PredicateKind.CHAIN_STATE,
    PredicateKind.BATTLE,
    PredicateKind.SUMMON_TYPE,
}


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


@functools.lru_cache(maxsize=1)
def predicate_corpus() -> tuple[tuple[str, str, str], ...]:
    """
    전 corpus 의 조건 leaf 를 ``(readiness, kind, subject)`` 로 센다.

    **기존 분석기를 그대로 쓴다** — 새 정규식을 쓰지 않는다 (``EffectAnalyzer``
    → ``PredicateAnalyzer``). 전체 12,504장이 약 11초다.
    """
    import pathlib as _pathlib

    from analysis.effect_analyzer import EffectAnalyzer
    from core.card_repository import CardRepository

    cdb = PROJECT_ROOT / "data" / "cards.cdb"
    if not cdb.is_file():  # pragma: no cover - conftest 가 이미 건너뛴다
        pytest.skip("cards.cdb 없음")
    repository = CardRepository.build(db_path=cdb, script_dir=_pathlib.Path(PROJECT_ROOT))
    analyzer = EffectAnalyzer(repository, script_dir=PROJECT_ROOT)

    rows: list[tuple[str, str, str]] = []
    for card in repository.all_cards():
        if card.script is None or not card.script.effects:
            continue
        for effect in analyzer.analyze(card).effects:
            tree = effect.activation.tree if effect.activation else None
            if tree is None:
                continue
            for leaf in tree.leaves():
                predicate = getattr(leaf, "predicate", None)
                if predicate is None:
                    continue
                rows.append(
                    (
                        predicate.readiness.value,
                        predicate.kind.value,
                        predicate.subject.value,
                    )
                )
    return tuple(rows)


# ======================================================================
# §7 — 엔진의 조건 어휘는 사건을 묻지 않는다
# ======================================================================


def test_01_the_engine_condition_vocabulary_only_asks_about_the_board():
    """
    **§7 — 사건을 묻는 술어가 하나도 없다.**

    ``engine/condition/model.py`` 의 ``Condition`` 서브클래스는 조합자와
    자리표시자를 빼면 16개이고, 전부 "지금 판" 을 묻는다. 그래서
    ``ConditionContext`` 에 ``event`` 를 더해도 **읽을 술어가 없다.**
    """
    #: 엔진 전체를 import 한 뒤에 세어야 한다 — 규칙 관문 8개가
    #: ``engine/action_validation.py`` 에 따로 있다.
    import engine.action_validation  # noqa: F401
    import engine.duel  # noqa: F401
    import engine.effect.library  # noqa: F401

    by_module: dict[str, set[str]] = {}
    for cls in Condition.__subclasses__():
        by_module.setdefault(cls.__module__, set()).add(cls.__name__)

    vocabulary = by_module["engine.condition.model"]
    combinators = {"And", "Or", "Not", "Always", "UnimplementedRule"}
    assert vocabulary == combinators | {
        "AttackAtLeast",
        "AttributeIs",
        "CardIsFaceUp",
        "CardIsInZone",
        "ControllerIs",
        "InAnyZone",
        "IsMonster",
        "IsSpellTrap",
        "IsTurnPlayer",
        "LevelAtLeast",
        "LifePointsAtLeast",
        "NotMonster",
        "PhaseIs",
        "ZoneCountAtLeast",
        "ZoneHasFreeSlot",
    }, sorted(vocabulary)
    gates = by_module["engine.action_validation"]
    assert len(gates) == 8, sorted(gates)

    #: 이름에도 사건이 없다.
    for forbidden in ("Previous", "Reason", "Event", "Chain", "Battle", "Summoned"):
        found = [n for n in vocabulary if forbidden in n]
        assert found == [], (forbidden, found)
    for forbidden in ("Previous", "Reason", "Event", "Chain", "Summoned"):
        found = [n for n in gates if forbidden in n]
        assert found == [], (forbidden, found)
    #: 관문 중 이름에 ``Battle`` 이 든 것은 하나이고, 그것은 **전투 사건**이
    #: 아니라 "선공 첫 턴에 배틀 페이즈를 할 수 있는가"(RULE-BATTLE-001)를
    #: 묻는 **진행 규칙**이다 — 턴 번호와 선공 좌석만 본다.
    assert [n for n in gates if "Battle" in n] == ["_BattlePhaseAllowedThisTurn"]

    source = (PROJECT_ROOT / "engine/condition/model.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    read_from_context = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "context"
        ):
            read_from_context.add(node.attr)
        #: ``getattr(context, "event", None)`` 같은 우회도 센다.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "context"
        ):
            name = node.args[1] if len(node.args) > 1 else None
            read_from_context.add(
                name.value if isinstance(name, ast.Constant) else "(동적)"
            )
    #: 조건들이 문맥에서 읽는 것은 넷뿐이다.
    assert read_from_context <= {"player", "source", "effect_ref", "targets"}, (
        read_from_context
    )


def test_02_no_production_caller_passes_an_event_into_the_context():
    """
    **§7 — ``ConditionContext`` 에 ``event`` 칸이 없고, 넘기는 곳도 없다.**

    production 의 생성 자리를 전부 AST 로 모아 키워드를 합집합으로 본다.
    """
    assert {f.name for f in ConditionContext.__dataclass_fields__.values()} == {
        "player",
        "source",
        "effect_ref",
        "targets",
    }

    keywords: set[str] = set()
    sites = 0
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ConditionContext"
            ):
                sites += 1
                keywords |= {kw.arg for kw in node.keywords if kw.arg}
    assert sites >= 8, sites
    assert keywords <= {"player", "source", "effect_ref", "targets"}, keywords
    assert "event" not in keywords


# ======================================================================
# §5 — 직전 상태는 어디까지 있는가
# ======================================================================


@pytest.mark.real_card
def test_03_previous_state_is_recorded_by_production_without_being_asked(repository):
    """
    **§5 — ``CardInstance.previous`` 는 실제 듀얼에서 자동으로 채워진다.**

    ``place``/``set_position``/``set_controller`` 의 기본값이
    ``remember_previous=True`` 이므로, 발동으로 카드가 움직이면 직전 위치가
    남는다. 즉 **"직전 1단계" 는 이미 production 에 있다.**
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    activations = [
        a
        for a in duel.legal_actions(seat)
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert activations
    source_id = activations[0].source
    before = duel.state.find_instance(source_id)
    assert before.zone is Zone.HAND

    assert duel.apply(activations[0]).accepted
    moved = duel.state.find_instance(source_id)
    assert moved.zone is not Zone.HAND  # 발동으로 자리를 옮겼다
    assert moved.previous.location is Zone.HAND  # **직전 위치가 남았다**
    assert isinstance(moved.previous, PreviousState)


def test_04_nothing_in_production_reads_the_previous_state():
    """
    **§5 — 기록은 되는데 읽는 곳이 없다.**

    ``engine/`` 에서 ``.previous`` 를 읽는 자리는 그것을 **쓰는** 모듈
    (``card_instance.py``) 밖에 없다. 조건 계층도 관측도 읽지 않는다.
    """
    readers = []
    for path in sorted((PROJECT_ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "previous":
                readers.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert sorted(set(readers)) == ["engine/state/card_instance.py"], sorted(set(readers))


def test_05_one_step_of_history_already_counts_as_the_board_shape():
    """
    **§11 — ownership 논의의 중요한 보강.**

    ``CardInstance.canonical_state`` 가 ``previous.as_tuple()`` 을 포함하므로
    **직전 상태는 이미 ``state_hash()`` 의 일부**다. 그러므로 "역사는 판의
    모양이 아니다" 는 **사건의 역사(journal)** 에 대한 말이고, "마지막 상태"
    는 이미 모양으로 간주되고 있다.
    """
    node = None
    tree = ast.parse((PROJECT_ROOT / "engine/state/card_instance.py").read_text(encoding="utf-8"))
    for item in ast.walk(tree):
        if isinstance(item, ast.FunctionDef) and item.name == "canonical_state":
            node = item
            break
    assert node is not None
    attrs = {inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute)}
    assert "previous" in attrs


@pytest.mark.real_card
def test_06_only_one_step_survives_and_the_reason_never_does(repository):
    """
    **§5 — 두 단계 전은 사라지고, "왜" 는 처음부터 없다.**

    ``previous`` 는 **한 칸**이므로 두 번 움직이면 첫 위치가 지워진다. 그리고
    ``CardInstance`` 에는 "왜 움직였는가"(reason)를 적는 칸이 아예 없다 —
    ADR-002 가 가른 "파괴" 와 "묘지로 보내기" 를 상태만으로 구분할 수 없다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    instance = duel.state.player(seat).hand[0]
    original = instance.zone

    instance.place(Zone.SZONE, 0, position=Position.FACEUP)
    assert instance.previous.location is original
    instance.place(Zone.GRAVE, 0)
    #: 첫 위치(HAND)는 사라지고 직전(SZONE)만 남는다.
    assert instance.previous.location is Zone.SZONE
    assert instance.previous.location is not original

    fields = set(CardInstance.__dataclass_fields__) if hasattr(
        CardInstance, "__dataclass_fields__"
    ) else set(CardInstance.__slots__)
    assert not [f for f in fields if "reason" in f], fields
    #: ``PreviousState`` 도 위치·표시형식·컨트롤러 셋뿐이다.
    assert {f.name for f in PreviousState.__dataclass_fields__.values()} == {
        "location",
        "position",
        "controller",
    }


@pytest.mark.real_card
def test_07_a_clone_carries_the_one_step_of_history(repository):
    """
    **§12 — 사본은 "직전 1단계" 를 함께 복제한다.**

    탐색이 사본에서 조건을 평가해도 그 한 단계는 일치한다. 사라지는 것은 그
    **앞**의 사건들이다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    instance = duel.state.player(seat).hand[0]
    instance.place(Zone.GRAVE, 0)

    clone = duel.state.clone()
    copied = clone.find_instance(instance.instance_id)
    assert copied is not instance
    assert copied.previous.as_tuple() == instance.previous.as_tuple()
    assert clone.state_hash() == duel.state.state_hash()


# ======================================================================
# §8 — corpus 측정 (기존 분석기로)
# ======================================================================


@pytest.mark.real_card
def test_08_most_condition_leaves_need_context_not_just_the_board():
    """
    **§8 — 조건 leaf 의 41% 가 사건·체인·직전 상태를 요구한다.**

    수는 늘 수 있으므로 **하한**으로 고정한다 (측정값: NEEDS_CONTEXT 8,511 ·
    EVALUABLE 6,684 · UNKNOWN 5,352).
    """
    rows = predicate_corpus()
    assert len(rows) >= 20_000, len(rows)
    counts: dict[str, int] = {}
    for readiness, _kind, _subject in rows:
        counts[readiness] = counts.get(readiness, 0) + 1

    assert counts[EvalReadiness.NEEDS_CONTEXT.value] >= 8_511
    assert counts[EvalReadiness.EVALUABLE.value] >= 6_684
    assert counts[EvalReadiness.UNKNOWN.value] >= 5_352
    #: 사건 문맥을 요구하는 쪽이 판만으로 되는 쪽보다 **많다**.
    assert counts[EvalReadiness.NEEDS_CONTEXT.value] > counts[EvalReadiness.EVALUABLE.value]


@pytest.mark.real_card
def test_09_previous_location_is_exactly_the_number_the_docstring_claims():
    """
    **§5 — ``previous_location`` 758건을 다시 센다.**

    ``CardInstance`` 의 설명이 적어 둔 숫자이고, 이번에 **기존 분석기로
    재현**했다 (숫자를 믿지 않고 다시 센다 — Phase 3-E-18 의 교훈).
    """
    rows = predicate_corpus()
    previous = [r for r in rows if r[1] == PredicateKind.PREVIOUS_LOCATION.value]
    assert len(previous) >= 758, len(previous)
    #: 전부 NEEDS_CONTEXT 다 — 판만으로 된다고 주장하지 않는다.
    assert {r[0] for r in previous} == {EvalReadiness.NEEDS_CONTEXT.value}

    doc = (PROJECT_ROOT / "engine/state/card_instance.py").read_text(encoding="utf-8")
    assert "758건" in doc


@pytest.mark.real_card
def test_10_the_required_context_is_the_edopro_callback_signature():
    """
    **§4 — 필요한 최소 문맥은 추측이 아니라 corpus 가 말한다.**

    ``NEEDS_CONTEXT`` leaf 의 **주체** 분포가 EDOPro 의 효과 콜백 서명
    ``(e,tp,eg,ep,ev,re,r,rp)`` 를 그대로 가리킨다 — 사건 묶음(``eg``) ·
    체인 상대 효과(``re``) · 이유와 그 주체(``r``/``rp``) · 듀얼 전체 질의.
    """
    rows = predicate_corpus()
    needs = [r for r in rows if r[0] == EvalReadiness.NEEDS_CONTEXT.value]
    subjects: dict[str, int] = {}
    for _readiness, _kind, subject in needs:
        subjects[subject] = subjects.get(subject, 0) + 1

    assert subjects[PredicateSubject.SELF.value] >= 3_000
    assert subjects[PredicateSubject.DUEL.value] >= 1_700
    assert subjects[PredicateSubject.EVENT_GROUP.value] >= 1_200
    assert subjects[PredicateSubject.CHAIN_EFFECT.value] >= 900
    assert subjects[PredicateSubject.PLAYER.value] >= 900

    #: 분석 계층은 이 어휘를 **이미** 갖고 있다 — 엔진 쪽에만 없다.
    assert PredicateSubject.EVENT_GROUP.value == "event_group"
    assert PredicateKind.EVENT_REASON.value == "event_reason"


@pytest.mark.real_card
def test_11_event_free_chain_is_not_an_event_dependent_condition():
    """
    **§9 — ``EVENT_FREE_CHAIN`` 을 유발 사건으로 취급하지 않는다.**

    등록된 효과 16개는 전부 ``EVENT_FREE_CHAIN`` 이고, 그 ``activation`` 조건은
    **판만 보는 것**(``ZoneCountAtLeast`` · ``And`` · 없음)뿐이다. 즉 지금
    실행되는 발동은 사건 문맥을 **요구하지 않는다** — 그래서 사건 전달이 없어도
    현재 실행이 틀리지 않는다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    kinds = set()
    for entry in EFFECT_LIBRARY:
        activation = entry.definition.activation
        kinds.add(type(activation).__name__ if activation is not None else "None")
    assert kinds <= {"None", "ZoneCountAtLeast", "And"}, kinds

    #: 그리고 그 조건들은 문맥에서 사건을 읽지 않는다 (test_01 이 어휘를 고정).
    for entry in EFFECT_LIBRARY:
        activation = entry.definition.activation
        if activation is None:
            continue
        assert "Previous" not in type(activation).__name__


# ======================================================================
# §13 — 숨은 정보
# ======================================================================


def test_12_the_view_does_not_expose_the_previous_state():
    """
    **§13 — 관측에 직전 상태가 없다.**

    그래서 사건 문맥을 쓰려면 ``GameStateView`` 를 넓히는 길과, 판을 들고 있는
    쪽이 **값으로** 넘기는 길(ADR-007, ``_set_this_turn`` 선례) 둘 중 하나를
    골라야 한다. 이 Phase 는 고르지 않는다 — 넓히지 않았다는 사실만 고정한다.
    """
    view_fields = set(GameStateView.__dataclass_fields__)
    card_fields = set(CardView.__dataclass_fields__)
    for forbidden in ("previous", "event", "journal", "trigger"):
        assert not [f for f in view_fields if forbidden in f], (forbidden, view_fields)
        assert not [f for f in card_fields if forbidden in f], (forbidden, card_fields)
    #: "reason" 이 들어간 유일한 필드는 **듀얼 결과**의 이유이고 사건이 아니다.
    assert [f for f in view_fields if "reason" in f] == ["result_reason"]
    assert [f for f in card_fields if "reason" in f] == []
