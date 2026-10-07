"""
Phase 3-F-19 — ``ChainResolution`` 직렬화 ↔ replay 입력 경계 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
``ChainResolution`` 을 **직렬화해서 replay 입력으로 되살려야 하는 실제 요구가
있는가.**

측정으로 나온 답: **없다.** 그리고 "쓰이지 않아서 없다" 가 아니라 **되살리지
않고도 판이 똑같이 재현된다**는 것을 실제로 돌려서 확인했다 (``test_24``).

🔴 재현 기록의 정체 — 세 겹을 구분한다
--------------------------------------
======================================  =========================================
``PlayerAction``                        🟢 **왕복한다.** 저장소에서 ``from_dict``
                                        를 가진 클래스는 이것과 그 안의
                                        ``ActionTarget`` **둘뿐**이다 (``test_05``)
``EventJournal``                        🟡 **미래의 재생 기록**으로 지정되어
                                        있다 (ADR-008). 다만 production 에서는
                                        **한 번도 켜지지 않는다** (``test_10``)
``ChainResolution``                     🔴 **runtime transient.** 만들어진 자리
                                        에서 ``code``/``reason`` 만 뽑히고
                                        **버려진다** (``test_01``)
======================================  =========================================

``to_dict`` 는 **읽는 쪽이 없다**
---------------------------------
production 에 ``to_dict`` 호출은 116곳이지만 ``from_dict`` 를 **정의한** 클래스는
둘, **부르는** 자리는 ``PlayerAction`` 안의 중첩 한 곳뿐이다. 즉 ``to_dict`` 나무
전체가 **한 방향 진단 출력**이고 역방향 입구가 없다 (``test_09``).

실제 재실행 구조는 이미 있다
----------------------------
``Simulator._fork()`` → ``GameState.clone()`` → ``fork.apply(action)`` 이 탐색에서
수없이 돌아간다. 그리고 seed + 행위 기록만으로 ``state_hash`` 가 그대로 재현된다.
그 과정에서 ``ChainResolution`` 은 **한 개도 복원되지 않는다.**

🔴 다만 재현에는 **문서화되지 않은 조건**이 하나 있다
-----------------------------------------------------
행위 기록만 순서대로 다시 적용하면 **재현되지 않는다.** 규칙이 스스로 하는 일
(``Duel.advance()`` — 드로우 · 페이즈 전환)을 **행위 사이에 똑같이 끼워 넣어야**
한다. 이 감사도 처음에 그 함정에 빠졌다 (90걸음 중 8걸음만 받아들여졌다).
그 조건이 어디에도 적혀 있지 않다 — 이것이 이 Phase 가 문서를 고치는 이유다.

이 Phase 는 production 의 **docstring 둘**만 바꾼다. 실행되는 코드는 한 글자도
바뀌지 않는다 (``test_27`` 이 AST 로 증명한다).
"""

import ast
import dataclasses
import inspect
import json
import pathlib
import subprocess

import pytest

from agent.runner import DuelRunner, Transcript, TranscriptEntry
from agent.search import search_policy
from agent.simulation import SimulationResult, Simulator
from engine.action import PlayerAction
from engine.action_target import ActionTarget
from engine.chain import Chain, ChainResolution, ChainResolutionStatus, ChainResolver
from engine.duel import Duel, DuelStep
from engine.effect.journal import EventJournal
from engine.effect.resolution import EffectResult
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
from engine.payment import CostPaymentResult
from engine.response import ResponseResolution
from engine.spell_activation import duel_resolver
from engine.state.game_state import GameState
from engine.vocabulary import Phase, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_ROOTS = (
    "engine",
    "agent",
    "app",
    "core",
    "analysis",
    "rules",
    "rulings",
    "sources",
    "scripts",
)
#: 이 감사 파일 자신. 3-F-18 §13 에서 배운 것 — 감사 도구는 자기를 세지 않는다.
MYSELF = "tests/test_chain_resolution_replay_boundary_audit.py"

MINE, THEIRS = 0, 1

POT_OF_GREED = 55144522
#: 홍옥의 사령 — 통상 몬스터라 효과 정의가 **없다** (link-only 보고를 만든다).
NO_DEFINITION = 11091375
#: 강욕의 보은 — 상대가 드로우한다.
GENEROUS_REWARD = 5915629
#: 페더맨 — 채우기용 통상 몬스터.
FEATHERMAN = 71925487
DIGEST_DECK = [NO_DEFINITION] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))


def all_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" not in str(path):
            yield path


class _StripStrings(ast.NodeTransformer):
    """문자열 리터럴을 지운다 — 설명 속 낱말을 코드로 착각하지 않으려고."""

    def visit_Constant(self, node):  # noqa: N802
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<str>"), node)
        return node


def code_only(relative: str) -> str:
    return ast.unparse(_StripStrings().visit(ast.parse(source_of(relative))))


def defined_methods(name: str) -> list[tuple[str, str]]:
    """저장소 전체에서 ``name`` 메서드를 **정의한** (파일, 클래스) 목록."""
    found: list[tuple[str, str]] = []
    for path in all_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    found.append((str(path.relative_to(PROJECT_ROOT)), cls.name))
    return found


def method_calls(name: str, *, production_only: bool = True) -> list[tuple[str, int, str]]:
    """``<무엇>.name(...)`` 호출 자리 — (파일, 줄, 받는 쪽 표현)."""
    found: list[tuple[str, int, str]] = []
    paths = production_files() if production_only else all_files()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == name
            ):
                found.append(
                    (
                        str(path.relative_to(PROJECT_ROOT)),
                        node.lineno,
                        ast.unparse(node.func.value),
                    )
                )
    return found


def word_in_production_code(word: str) -> dict[str, int]:
    """문자열 리터럴을 지운 production 코드에서 ``word`` 가 나오는 파일별 횟수."""
    hits: dict[str, int] = {}
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            count = code_only(relative).count(word)
        except SyntaxError:  # pragma: no cover
            continue
        if count:
            hits[relative] = count
    return hits


# ======================================================================
# 판
# ======================================================================


def live_duel(repository, *, seed: int = 19, deck=None) -> Duel:
    """실제 듀얼 하나 — 규칙이 스스로 하는 일까지 다 밀어 둔다."""
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def fresh_duel(repository, *, seed: int, deck=None) -> Duel:
    """``advance()`` 를 **아직 돌리지 않은** 판 — 재실행의 출발점이다."""
    cards = list(DIGEST_DECK if deck is None else deck)
    return Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)


def board(repository, passcode: int, owner: int = MINE):
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=owner, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    return state, card.instance_id


def one_link_chain(repository, passcode: int, actor: int):
    """링크 하나를 **올려만** 둔다 — 아직 해결하지 않는다."""
    state, source = board(repository, passcode, actor)
    chain = Chain().activate(
        actor=actor, effect_ref=EffectRef(passcode, 0), source=source
    )
    return state, chain


def resolve_one(repository, passcode: int, actor: int):
    """**production 해결기**로 링크 하나를 해결한다."""
    state, chain = one_link_chain(repository, passcode, actor)
    return state, duel_resolver().resolve_top(state, chain)


def replay_from_actions(repository, actions, *, seed: int, deck=None):
    """
    🔴 **행위 기록만으로 다시 돌린다.**

    규칙이 스스로 하는 일(``advance``)을 **행위 사이에 끼워 넣는다** —
    ``DuelRunner._step`` 과 같은 순서다. 이것을 빼면 재현되지 않는다.
    ``ChainResolution`` 은 하나도 복원하지 않는다.
    """
    duel = fresh_duel(repository, seed=seed, deck=deck)
    index = rule_steps = applied = refused = 0
    while not duel.is_over and index < len(actions):
        if duel.advance() is not None:
            rule_steps += 1
            continue
        step = duel.apply(actions[index])
        index += 1
        if step.accepted:
            applied += 1
        else:
            refused += 1
    while duel.advance() is not None:
        rule_steps += 1
    return duel, {"applied": applied, "refused": refused, "rule_steps": rule_steps}


# ======================================================================
# A. §4 — ChainResolution 의 lifecycle
# ======================================================================


def test_01_the_report_is_consumed_where_it_is_made_and_then_discarded():
    """
    🔴 §4 — **``ChainResolution`` 은 만들어진 자리에서 소비되고 버려진다.**

    ``Duel._resolve_chain`` 이 ``resolution.steps`` 에서 꺼내 쓰는 것은
    ``code`` 와 ``reason`` **둘뿐**이다. 그 다음 만드는 ``DuelStep`` 에는
    ``ChainResolution`` 을 담는 칸이 **없다.**

    그래서 이 객체는 **기록에 남지 않는다** — 직렬화 질문 자체가 여기서 끝난다.
    """
    body = inspect.getsource(Duel._resolve_chain)
    tree = ast.parse(
        inspect.cleandoc(body.lstrip()).replace("def _resolve_chain", "def f")
    )
    reads: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            reads.setdefault(ast.unparse(node.value), set()).add(node.attr)

    #: 보고 **전체**에서 읽는 것은 셋뿐이다.
    assert reads["resolution"] == {"state", "steps", "fully_resolved"}, reads["resolution"]

    #: 🔴 그리고 걸음 하나에서 읽는 것은 ``code`` 와 ``reason`` — **문자열과
    #: 열거값뿐**이다. ``link`` 도 ``result`` 도 ``deltas`` 도 읽지 않는다.
    per_step = reads.get("steps[-1]", set()) | reads.get("last", set())
    assert per_step == {"code", "reason"}, per_step
    for never in ("link", "result", "deltas", "to_dict", "canonical_state"):
        assert never not in per_step, never

    #: 🔴 ``DuelStep`` 도 ``Duel`` 도 보고를 담지 않는다.
    for holder in (DuelStep, Duel):
        assert not [
            f for f in dataclasses.fields(holder) if "ChainResolution" in str(f.type)
        ], holder.__name__


def test_02_a_link_only_lifecycle_leaves_nothing_behind(repository):
    """§4 · §12 3 — 정의를 못 찾은 링크도 **보고만** 만들고 아무 데도 남지 않는다."""
    state, report = resolve_one(repository, NO_DEFINITION, THEIRS)

    assert report.status is ChainResolutionStatus.INVALID_CHAIN_LINK
    assert report.link is not None and report.result is None
    #: 판에는 흔적이 없다 — 기록 칸이 애초에 없다.
    assert state.journal == []
    assert not hasattr(state, "resolutions")


def test_03_the_result_exists_only_while_the_report_does(repository):
    """§4 · §12 4 — result 는 보고와 **같은 수명**이다. 더 오래 살 자리가 없다."""
    state, report = resolve_one(repository, POT_OF_GREED, MINE)

    assert isinstance(report.result, EffectResult)
    assert report.result.deltas
    #: 판은 그 result 를 들고 있지 않다.
    assert state.journal == []
    #: 그리고 result 로 보고로 돌아올 역참조가 없다.
    for name in ("resolution", "link", "report", "chain"):
        assert not hasattr(report.result, name), name


def test_04_the_actor_provenance_is_only_reachable_through_the_live_report(repository):
    """
    §4 · §12 1 — actor provenance 는 **살아 있는 보고**를 통해서만 읽는다.

    보고가 버려진 뒤에 남는 사람 정보는 ``PlayerAction.actor`` 다 — 그리고 그것은
    **왕복 가능한** 유일한 기록이다 (``test_05``).
    """
    state, report = resolve_one(repository, POT_OF_GREED, THEIRS)
    assert report.link.actor == THEIRS

    #: 직렬화한 보고에는 사람이 남지만, 그것을 **되읽을 입구가 없다**.
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False, default=str))
    assert payload["link"]["actor"] == THEIRS
    assert not hasattr(ChainResolution, "from_dict")

    #: 반면 행위 기록은 왕복한다.
    action = PlayerAction.activate_card(THEIRS, report.link.source)
    assert PlayerAction.from_dict(action.to_dict()) == action
    assert PlayerAction.from_dict(action.to_dict()).actor == THEIRS


# ======================================================================
# B. §3 · §5 — 직렬화/재생 호출 그래프
# ======================================================================


def test_05_the_repository_defines_exactly_two_from_dict():
    """
    🔴 §3 · §5 — **저장소 전체에서 ``from_dict`` 를 정의한 클래스는 둘뿐이다.**

    ``PlayerAction`` 과 그 안에 들어가는 ``ActionTarget`` 이다. 즉 이 프로젝트에서
    **직렬화 입력으로 되살아날 수 있는 것은 행위뿐**이다.
    """
    defined = defined_methods("from_dict")
    assert sorted(defined) == [
        ("engine/action.py", "PlayerAction"),
        ("engine/action_target.py", "ActionTarget"),
    ], defined

    #: 실제로 왕복한다.
    action = PlayerAction.passing(MINE)
    assert PlayerAction.from_dict(action.to_dict()) == action


def test_06_production_calls_from_dict_only_inside_player_action():
    """
    §3 · §5 — production 의 ``from_dict`` 호출은 **한 곳**이고, 그것도
    ``PlayerAction.from_dict`` 가 자기 안의 ``ActionTarget`` 을 되살리는 자리다.

    즉 **역직렬화 입구가 행위 하나로 모여 있다.**
    """
    calls = method_calls("from_dict")
    assert len(calls) == 1, calls
    path, _, receiver = calls[0]
    assert path == "engine/action.py"
    assert receiver == "ActionTarget"

    #: ``PlayerAction.from_dict`` 를 부르는 쪽은 production 에 없다 — 아직
    #: 되살릴 일이 production 에 없다는 뜻이다. 시험만 왕복을 확인한다.
    outside = [
        call
        for call in method_calls("from_dict", production_only=False)
        if "PlayerAction" in call[2]
    ]
    assert outside and all(p.startswith("tests/") for p, _, _ in outside), outside


def test_07_no_production_code_mentions_replay():
    """
    🔴 §3 · §10 — **production 코드에 ``replay`` 라는 이름이 하나도 없다.**

    문자열 리터럴을 지우고 센다 — 설명문에 적힌 "재생(replay)" 을 코드로 세지
    않는다. 그래서 "replay 구현이 잘못됐다" 가 아니라 **replay 구현이 없다** 다.
    §10 이 요구한 구분 그대로다.
    """
    for word in ("replay", "Replay", "Replayer"):
        assert word_in_production_code(word) == {}, (word, word_in_production_code(word))


def test_08_no_production_serializer_framework_exists():
    """§3 · §14 — serializer/deserializer/asdict 가 production 코드에 **0곳**이다."""
    for word in ("serialize", "deserialize", "serialization", "asdict"):
        assert word_in_production_code(word) == {}, word

    #: pickle 관련 특수 메서드도 저장소 production 에 없다.
    for special in ("__getstate__", "__setstate__", "__reduce__", "__deepcopy__"):
        assert defined_methods(special) == [] or all(
            path.startswith("tests/") for path, _ in defined_methods(special)
        ), (special, defined_methods(special))


def test_09_the_to_dict_tree_is_write_only():
    """
    🔴 §6 — **``to_dict`` 는 쓰기 전용이다.** 읽는 쪽이 없다.

    production 의 ``to_dict`` 호출은 100곳이 넘는데 되읽는 입구는 행위 하나뿐이다
    (``test_06``). 그래서 §6 의 ①("기술적으로 serialize 할 수 있다")은 참이지만
    ③("replay 를 위해 반드시 serialize 해야 한다")은 **거짓**이다.
    """
    writes = method_calls("to_dict")
    reads = method_calls("from_dict")
    assert len(writes) > 100, len(writes)
    assert len(reads) == 1, reads

    #: 🔴 ``ChainResolution.to_dict()`` 를 부르는 production 자리는 **없다.**
    callers = [
        call
        for call in writes
        if any(k in call[2] for k in ("resolution", "report"))
        and not call[2].startswith("self.")
    ]
    assert callers == [], callers

    #: ``ResponseResolution.to_dict`` 안에서 ``step.to_dict()`` 로 중첩되기는 한다.
    #: 그런데 ``ResponseResolution.to_dict`` 자체를 부르는 production 자리도 없다.
    nested = [call for call in writes if call[0] == "engine/response.py"]
    assert any(call[2] == "step" for call in nested), nested
    assert all(call[2].startswith("self.") or call[2] == "step" for call in nested)


def test_10_the_designated_replay_record_is_the_journal_not_the_report():
    """
    🟡 §5 · §7 — **미래의 재생 기록으로 지정된 것은 ``EventJournal`` 이다.**

    ``engine/effect/journal.py`` 가 ADR-008 로 그렇게 적어 두었다 — "적는
    데까지만 한다", "나중에 되살리는 데 필요한 것을 빠짐없이 적어 둔다".

    그런데 production 에서 journal 은 **한 번도 켜지지 않는다** (Phase 3-F-16).
    그래서 "지정되어 있다" 와 "쓰이고 있다" 를 섞지 않는다.
    """
    journal_doc = inspect.getdoc(
        __import__("engine.effect.journal", fromlist=["x"])
    ) or ""
    assert "ADR-008" in journal_doc
    assert "되살리는" in journal_doc

    #: journal 은 ``GameState`` 안에 살지 않는다고 스스로 적는다.
    assert "GameState" in journal_doc

    #: 그리고 판의 journal 칸은 비어 있다.
    assert "journal" in GameState.__slots__
    #: 🔴 ``EventJournal`` 에도 ``from_dict`` 가 없다 — 적기만 한다.
    assert hasattr(EventJournal, "journal_hash")
    assert not hasattr(EventJournal, "from_dict")


# ======================================================================
# C. §7 — DuelStep 과의 관계
# ======================================================================


def test_11_the_duel_step_carries_the_action_not_the_report(repository):
    """§7 · §12 5 — ``DuelStep`` 에 남는 것은 **행위**다."""
    names = {f.name for f in dataclasses.fields(DuelStep)}
    assert names == {"action", "accepted", "code", "reason", "result"}

    duel = live_duel(repository)
    duel.advance()
    step = duel.apply(PlayerAction.passing(duel.to_act))
    assert isinstance(step.action, PlayerAction)
    #: 🔴 보고로 가는 길이 없다.
    for name in ("resolution", "link", "steps", "chain_resolution"):
        assert not hasattr(step, name), name


def test_12_the_duel_step_result_is_the_duel_outcome_not_an_effect_result(repository):
    """
    🔴 §7 — ``DuelStep.result`` 는 **듀얼의 승패**이고 ``EffectResult`` 가 아니다.

    이름이 같아서 섞기 쉽다. 섞으면 "걸음마다 효과 결과가 기록된다" 고 잘못
    읽는다 — 기록되는 것은 **끝났을 때의 결과**뿐이다.
    """
    field = {f.name: f for f in dataclasses.fields(DuelStep)}["result"]
    assert "DuelResult" in str(field.type)
    assert "EffectResult" not in str(field.type)

    duel = live_duel(repository)
    duel.advance()
    step = duel.apply(PlayerAction.passing(duel.to_act))
    assert step.result is None or not isinstance(step.result, EffectResult)


# ======================================================================
# D. §8 — state_hash 와의 관계
# ======================================================================


def test_13_the_state_hash_excludes_the_chain_and_the_journal(repository):
    """
    🟢 §8 — ``state_hash`` 는 체인도 journal 도 **보지 않는다.**

    ``canonical_state`` 가 그렇게 적어 두었고 ("앞으로도 넣지 않는다"), 실제로
    체인을 바꿔도 해시가 흔들리지 않는다. 그래서 ``ChainResolution`` 의 직렬화
    여부는 **해시와 아무 관계가 없다.**
    """
    doc = inspect.getdoc(GameState.canonical_state) or ""
    assert "chain" in doc and "journal" in doc
    assert "앞으로도 넣지 않는다" in doc

    duel = live_duel(repository)
    before = duel.state.state_hash()
    #: 체인을 비워도 · 바꿔도 판의 해시는 그대로다.
    state2, chain = one_link_chain(repository, POT_OF_GREED, MINE)
    duel.chain = chain
    assert duel.state.state_hash() == before


def test_14_each_object_is_classified_inside_or_outside_the_state_hash(repository):
    """
    §8 — 요구한 객체들을 **해시 안/밖**으로 분류한다.

    ====================  ==========================================
    ``GameState``         🟢 **안** — 해시 그 자체다
    ``ChainResolution``   🔴 **밖** — 판이 소유하지 않는다
    ``ChainLink``         🔴 **밖** — 체인은 ``Duel`` 에 있다
    ``EffectResult``      🔴 **밖** — 보고 안에만 있다
    ``CostPaymentResult`` 🔴 **밖** — 같은 이유
    ``DuelStep``          🔴 **밖** — 걸음은 기록이고 판이 아니다
    ====================  ==========================================
    """
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    canonical = state.canonical_state()
    flat = json.dumps(canonical, ensure_ascii=False, default=str)

    #: 🔴 보고·링크·결과의 이름이 정규 표현에 하나도 들어 있지 않다.
    for absent in ("ChainResolution", "ChainLink", "EffectResult", "DuelStep"):
        assert absent not in flat, absent

    #: 판을 소유하는 쪽은 ``GameState`` 뿐이다 — 보고는 판을 들고 있지 않다.
    assert isinstance(report.chain, Chain)
    assert not hasattr(report, "state")


# ======================================================================
# E. §9 — clone / deepcopy / snapshot / restore
# ======================================================================


def test_15_the_report_and_its_parts_have_no_clone():
    """§9 — ``clone`` 은 **판 계층에만** 있다. 보고에는 없다."""
    defined = {cls for _, cls in defined_methods("clone")}
    assert "GameState" in defined
    for absent in ("ChainResolution", "ChainLink", "Chain", "EffectResult", "DuelStep"):
        assert absent not in defined, absent


def test_16_production_never_deep_copies_the_report():
    """
    §9 — production 의 ``deepcopy`` 호출은 **한 곳**이고 보고와 무관하다.

    ``analysis/condition_parser.py`` 가 조건 트리를 복제하는 자리다.
    """
    calls = [
        call
        for call in method_calls("deepcopy")
        + [
            (str(p.relative_to(PROJECT_ROOT)), n.lineno, ast.unparse(n.func))
            for p in production_files()
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "deepcopy"
        ]
    ]
    assert len(calls) == 1, calls
    assert calls[0][0] == "analysis/condition_parser.py"


def test_17_production_replace_on_the_report_is_still_zero():
    """§9 — 3-F-18 의 측정을 **다시** 확인한다: production ``replace`` 호출 0곳."""
    found: list[tuple[str, int, str]] = []
    for path in production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            target = node.func
            is_replace = (
                isinstance(target, ast.Attribute) and target.attr == "replace"
            ) or (isinstance(target, ast.Name) and target.id == "replace")
            if is_replace and any(
                key in ast.unparse(node.args[0]) for key in ("resolution", "report")
            ):
                found.append(
                    (str(path.relative_to(PROJECT_ROOT)), node.lineno, ast.unparse(node))
                )
    assert found == [], found


def test_18_there_is_no_snapshot_or_restore_path_for_the_report():
    """
    §9 — ``snapshot`` · ``restore`` 가 production 에 있기는 하지만 **다른 것**이다.

    * ``snapshot`` — ``sources/source_manager.py`` 의 데이터 수집 스냅숏과
      ``CardInstance``/``zones`` 의 이전 상태. 보고와 무관하다.
    * ``restore`` — ``NormalSpellPlacement.restore`` 로, **놓은 마법을 되돌리는**
      것이다. 판 복원도, 기록 복원도 아니다.
    """
    snapshot = word_in_production_code("snapshot")
    assert "engine/chain.py" not in snapshot, snapshot

    restore = word_in_production_code("restore")
    assert set(restore) == {"engine/spell_activation.py"}, restore
    #: 그 ``restore`` 는 마법 되돌리기다.
    from engine.spell_activation import NormalSpellPlacement

    doc = inspect.getdoc(NormalSpellPlacement.restore) or ""
    assert "ChainResolution" not in doc


# ======================================================================
# F. §11 — hidden information · AI · RNG · Search
# ======================================================================


def test_19_the_report_never_reaches_the_agent_layer():
    """
    🟢 §11 — ``agent/`` 코드에 보고가 **한 번도 나오지 않는다.**

    그래서 직렬화가 AI 쪽으로 정보를 새게 할 경로가 **없다** — 가능성이 아니라
    연결 자체가 없다.
    """
    for absent in ("ChainResolution", "EffectResult", "CostPaymentResult", "EventJournal"):
        for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
            relative = str(path.relative_to(PROJECT_ROOT))
            assert absent not in code_only(relative), (absent, relative)


def test_20_the_search_fork_re_executes_without_any_report(repository):
    """
    🟢 §5 · §11 — **재실행 구조는 이미 있고, 보고를 쓰지 않는다.**

    ``Simulator`` 는 판을 ``clone()`` 해서 행위를 다시 적용한다. 돌려주는
    ``SimulationResult`` 에는 ``action``/``status``/``future`` 만 있다.
    """
    duel = live_duel(repository)
    duel.advance()
    simulator = Simulator(duel)
    outcome = simulator.simulate(PlayerAction.passing(duel.to_act), viewer=duel.to_act)

    assert isinstance(outcome, SimulationResult)
    names = {f.name for f in dataclasses.fields(SimulationResult)}
    assert names == {"action", "status", "viewer", "reason", "code", "future"}
    #: 🔴 보고로 가는 칸이 없다.
    for absent in ("resolution", "result", "steps", "link"):
        assert absent not in names, absent

    #: 그리고 원본 판은 흔들리지 않는다.
    assert isinstance(outcome.action, PlayerAction)


def test_21_serialization_does_not_widen_hidden_information(repository):
    """
    §11 — 보고를 직렬화하면 카드 신원이 나오지만, **읽는 쪽이 없다.**

    그래서 숨은 정보 경계는 그대로다 — 관측은 여전히 ``GameStateView`` 가 가린다.
    가능성을 결함으로 과장하지 않고, **연결이 없다는 사실**을 적는다.
    """
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, default=str)
    #: 직렬화에는 링크의 발동 정보가 들어 있다 (진단 목적).
    assert "link" in payload

    #: 그런데 관측은 여전히 상대 손·덱을 가린다.
    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()

    #: 그리고 그 직렬화를 production 에서 부르는 자리가 없다 (``test_09``).
    assert not hasattr(ChainResolution, "from_dict")


def test_22_the_same_seed_reproduces_the_same_board(repository):
    """§11 · §12 6 — RNG 는 seed 로 완전히 결정된다 — 보고와 무관하다."""
    a = live_duel(repository, seed=22)
    b = live_duel(repository, seed=22)
    assert a.state.state_hash() == b.state.state_hash()

    #: .. note::
    #:    ``repr(state.rng)`` 로 **두 판을 비교하지 않는다** — 객체 주소가
    #:    들어가서 같은 seed 여도 다르게 나온다. 비교할 수 있는 것은 **꺼낸
    #:    값의 순서**다. (``repr`` 비교는 *같은* 판의 전후에만 쓸 수 있다 —
    #:    ``test_29`` 가 그렇게 쓴다.)
    draws_a = [a.state.rng.random() for _ in range(5)]
    draws_b = [b.state.rng.random() for _ in range(5)]
    assert draws_a == draws_b

    c = live_duel(repository, seed=23)
    assert c.state.state_hash() != a.state.state_hash()


# ======================================================================
# G. §12 — 실제 듀얼과 실제 재실행
# ======================================================================


def test_23_a_real_duel_records_only_player_actions(repository):
    """§12 5 — 한 판의 기록(``Transcript``)에 남는 것은 **행위**뿐이다."""
    duel = live_duel(repository, seed=23)
    transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()

    assert transcript.entries
    names = {f.name for f in dataclasses.fields(TranscriptEntry)}
    assert "action" in names
    for absent in ("resolution", "result", "steps", "link", "deltas"):
        assert absent not in names, absent

    #: 그리고 기록 전체에 보고가 하나도 없다.
    for entry in transcript.entries:
        assert entry.action is None or isinstance(entry.action, PlayerAction)

    #: ``Transcript.canonical_state`` 도 행위만 쓴다.
    canonical = json.dumps(transcript.canonical_state(), ensure_ascii=False, default=str)
    for absent in ("ChainResolution", "EffectResult"):
        assert absent not in canonical, absent


def test_23b_nothing_writes_the_report_into_the_board(repository):
    """
    🔴 §4 · §8 — **보고를 판에 쌓는 코드가 없다.** 구조와 행동을 **둘 다** 잰다.

    .. note::
       이 테스트는 **고의 위반 주입 4번을 놓쳐서** 추가했고, 처음 쓴 모양은
       **여전히 놓쳤다.** 그 과정에서 사실 하나를 측정했다.

       주입은 ``Duel._resolve_chain`` 에 ``self.state.journal.extend(steps)`` 를
       심는다. 그런데 실제 듀얼을 끝까지 돌려도 판의 journal 이 비어 있었다.
       이유를 재 보니 ``_resolve_chain`` 호출 67번이 **전부 탐색이 복제한
       판(fork)에서** 일어났다 — 실제 판에서는 **한 번도** 일어나지 않았다.
       현재 ``Duel.legal_actions`` 가 ``activate_card`` 를 허가하지 않아서
       (``rule_not_implemented``) 실제 듀얼에서 체인이 쌓이지 않기 때문이다.

       그래서 **행동만으로는 잡을 수 없다.** 닿지 않는 경로는 돌려도 안 보인다.
       대신 **구조로 잡는다** — ``_resolve_chain`` 이 ``self.state`` 에 **쓰지
       않는다**는 것을 AST 로 단정한다. 이것이 주입을 결정론적으로 잡는다.

       이 사실("실제 듀얼은 아직 체인을 해결하지 않는다")은 Engine V1 범위의
       측정값이고, 이 Phase 가 고칠 일이 아니다 — 보고서에 그대로 적는다.
    """
    #: ① 구조 — ``_resolve_chain`` 이 판에 **쓰는** 자리가 없다.
    tree = ast.parse(
        inspect.cleandoc(inspect.getsource(Duel._resolve_chain).lstrip()).replace(
            "def _resolve_chain", "def f"
        )
    )
    written: set[str] = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                written.add(ast.unparse(target))
    #: 바꾸는 것은 ``Duel`` 자신의 칸 둘뿐이다 — 판도 journal 도 아니다.
    assert written == {"self.chain", "self.priority"}, written

    #: 그리고 ``self.state`` 에 **메서드를 불러 쓰는** 자리도 없다.
    mutations = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func.value).startswith("self.state")
    ]
    assert mutations == [], mutations

    #: ② 행동 — 실제 듀얼을 끝까지 돌려도 판의 journal 이 비어 있다.
    duel = live_duel(repository, seed=231)
    transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
    assert transcript.entries
    assert duel.state.journal == [], duel.state.journal
    assert duel.chain.is_complete or len(duel.chain.links) == 0

    #: ③ 그리고 ``canonical_state`` 에 보고의 흔적이 없다.
    flat = json.dumps(duel.state.canonical_state(), ensure_ascii=False, default=str)
    for absent in ("ChainResolution", "EffectResult", "invalid_chain_link"):
        assert absent not in flat, absent


def test_24_a_serialized_action_log_reproduces_the_board_with_no_report(repository):
    """
    🟢🔴 §5 · §7 · §12 6 — **이 Phase 의 결정적 측정.**

    한 판을 끝까지 돌린 뒤, **행위 기록만** ``to_dict`` → JSON → ``from_dict`` 로
    왕복시키고 같은 seed 의 새 판에 다시 적용한다. ``ChainResolution`` 은 **한
    개도 복원하지 않는다.** 그런데 ``state_hash`` 가 **같다.**

    → 그러므로 "``ChainResolution`` 을 직렬화해야 replay 가 된다" 는 **거짓**이다.
    "쓰이지 않아서 필요 없다" 가 아니라 **없이도 재현된다**는 실측이다.

    .. note::
       🔴 **처음에 이 측정을 틀렸다.** 행위만 순서대로 적용했더니 90걸음 중
       8걸음만 받아들여지고 해시가 달랐다. 원인은 엔진이 아니라 측정이었다 —
       규칙이 스스로 하는 일(``Duel.advance()``: 드로우 · 페이즈 전환)을
       끼워 넣지 않았기 때문이다. ``DuelRunner._step`` 은 **행위를 묻기 전에
       먼저 ``advance()``** 를 한다.

       즉 재현 입력 계약은 "행위 기록" 만이 아니라
       **(seed, 덱, 받아들여진 행위 순서, advance 끼워 넣기)** 다. 그 마지막
       조건이 어디에도 적혀 있지 않았다 — 이 Phase 가 문서를 고치는 이유다.
    """
    for seed in (11, 12):
        duel = live_duel(repository, seed=seed)
        transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
        live_hash = duel.state.state_hash()
        accepted = [
            entry.action
            for entry in transcript.entries
            if entry.accepted and entry.action is not None
        ]
        assert accepted

        #: 🔴 행위 기록만 직렬화해서 되읽는다.
        wire = json.dumps([action.to_dict() for action in accepted], ensure_ascii=False)
        restored = [PlayerAction.from_dict(data) for data in json.loads(wire)]
        assert restored == accepted

        replayed, counts = replay_from_actions(repository, restored, seed=seed)

        #: 거부 0 · 규칙 걸음 수까지 같다.
        assert counts["refused"] == 0, (seed, counts)
        assert counts["applied"] == len(restored), (seed, counts)
        assert counts["rule_steps"] == transcript.rule_steps, (seed, counts)
        #: 🟢 그리고 판이 같다 — 보고를 하나도 복원하지 않고.
        assert replayed.state.state_hash() == live_hash, seed


def test_25_omitting_the_rule_steps_breaks_the_replay(repository):
    """
    🔴 §5 — **``advance()`` 를 빼면 재현되지 않는다.** 이것이 숨은 계약이다.

    이 테스트는 ``test_24`` 가 지키는 조건이 **진짜로 필요한지**를 확인한다.
    빼면 대부분의 행위가 거부되고 해시가 달라진다 — 그래서 문서에 적어야 한다.
    """
    seed = 11
    duel = live_duel(repository, seed=seed)
    transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
    live_hash = duel.state.state_hash()
    accepted = [
        entry.action
        for entry in transcript.entries
        if entry.accepted and entry.action is not None
    ]

    #: ``advance()`` 없이 행위만 들이붓는다.
    naive = live_duel(repository, seed=seed)
    applied = refused = 0
    for action in accepted:
        if naive.is_over:
            break
        step = naive.apply(action)
        if step.accepted:
            applied += 1
        else:
            refused += 1

    assert refused > 0, "advance 를 빼도 전부 받아들여졌다면 계약이 바뀐 것이다"
    assert applied < len(accepted)
    assert naive.state.state_hash() != live_hash


def test_26_the_cost_payment_boundary_is_unchanged(repository):
    """§12 2 · §10 — 비용 결과 쪽 계약은 **건드리지 않았다.**"""
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {"actor"}
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {"actor"}
    assert not hasattr(CostPaymentResult, "from_dict")
    assert not hasattr(EffectResult, "from_dict")

    #: 3-F-17 이 적은 두 복원 경로가 그대로 있다.
    assert "resolution.link.actor" in source_of("engine/chain.py")
    assert "activation.action.actor" in source_of("engine/payment.py")


# ======================================================================
# H. §14 — AUDIT 범위와 불변
# ======================================================================


def test_27_this_phase_changed_only_docstrings():
    """
    §14 — **이 Phase 의 production 변경은 docstring 둘뿐이다.**

    문자열 리터럴을 지운 AST 가 두 파일 모두 이 Phase 의 base 와 **같다** —
    실행되는 코드가 한 글자도 바뀌지 않았다.

    .. note::
       **``git diff HEAD`` 으로 재지 않는다** — commit 뒤에는 자기와 자기를
       비교하게 되어 언제나 통과한다 (3-F-12 · 3-F-13 · 3-F-15 · 3-F-16 이 빠진
       함정). 그렇다고 "base SHA ↔ 작업 트리" 로 재면 **뒤의 Phase 가 이 두
       파일의 코드를 바꿀 때 그 Phase 때문에 깨진다** — 3-F-17 의 같은 단정이
       그 모양이었다.

       그래서 **이 파일을 추가한 commit**(= 3-F-19 작업 commit)의 **앞뒤**를
       비교한다. 그 commit 은 변하지 않으므로 단정이 영구히 안정적이고, 재는
       대상도 정확히 이 Phase 다. commit 전 개발 중에는 base
       (``a881834`` — 3-F-18 보고서 commit) ↔ 작업 트리로 되돌아가 잰다.
    """
    PHASE_3F19_BASE = "a881834"
    CHANGED = ("engine/chain.py", "agent/runner.py")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    work = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    for relative in CHANGED:
        if work:
            commit = work[-1]
            before = git("show", f"{commit}^:{relative}")
            after = git("show", f"{commit}:{relative}")
        else:  # pragma: no cover - commit 전 개발 중에만 지나간다
            before = git("show", f"{PHASE_3F19_BASE}:{relative}")
            after = source_of(relative)
        assert ast.dump(_StripStrings().visit(ast.parse(before))) == ast.dump(
            _StripStrings().visit(ast.parse(after))
        ), relative

    #: 그리고 이 Phase 가 **그 둘 말고는** production 을 건드리지 않았다.
    if work:
        touched = git(
            "show", "--stat", "--format=", work[-1], "--", *PRODUCTION_ROOTS
        )
        for line in touched.splitlines():
            if "|" in line:
                assert line.split("|")[0].strip() in CHANGED, line

    #: 🔴 §14 의 금지 항목 — 새 입구도, 새 틀도 없다.
    assert not hasattr(ChainResolution, "from_dict")
    assert not hasattr(ResponseResolution, "from_dict")
    assert sorted(defined_methods("from_dict")) == [
        ("engine/action.py", "PlayerAction"),
        ("engine/action_target.py", "ActionTarget"),
    ]
    for forbidden in ("Serializer", "Replayer", "ReplayEngine", "Snapshotter"):
        assert word_in_production_code(forbidden) == {}, forbidden


def test_28_the_two_docstrings_say_the_measured_thing():
    """
    §14 · §16 — 고친 docstring 둘이 **측정한 사실**을 적는다.

    * ``engine/chain.py`` — 보고는 runtime transient 이고, 재생 기록이 아니다
    * ``agent/runner.py`` — 재현 입력 계약에 ``advance()`` 끼워 넣기가 포함된다
    """
    chain_doc = inspect.getdoc(ChainResolution) or ""
    #: 🔴 "기록(replay)에 남겨야 하는 것은 이 객체다" 라고 **적지 않는다.**
    assert "기록(replay)에 남겨야 하는 것은 **이 객체**다" not in chain_doc
    assert "runtime" in chain_doc or "버려진다" in chain_doc
    #: 그리고 재생 기록이 어디인지 가리킨다.
    assert "PlayerAction" in chain_doc

    #: .. note::
    #:    🔴 원래는 ``"advance" in transcript_doc`` 으로만 쟀다. 그래서 고의
    #:    위반 주입 8번(네 번째 항목을 지워 ``advance()`` 끼워 넣기 조건을
    #:    없앤다)을 **놓쳤다** — 그 낱말이 설명의 다른 줄에도 나오기 때문이다.
    #:    **낱말이 아니라 계약을 센다.**
    transcript_doc = inspect.getdoc(Transcript) or ""

    #: 재현 입력 네 가지가 번호와 함께 다 적혀 있다.
    for item in ("1. ``seed``", "2. ", "3. ", "4. "):
        assert item in transcript_doc, item
    #: 🔴 네 번째가 **``advance()`` 끼워 넣기**라고 적혀 있다.
    fourth = transcript_doc.split("4. ", 1)[1].split("\n", 1)[0]
    assert "advance()" in fourth, fourth
    #: 그리고 빼면 재현되지 않는다는 경고가 함께 있다.
    assert "네 번째를 빼면" in transcript_doc
    #: 결과 객체는 필요 없다는 사실도 적는다.
    assert "ChainResolution" in transcript_doc and "필요하지 않다" in transcript_doc


def test_29_nothing_about_the_board_or_the_view_moved(repository):
    """§11 — ``state_hash`` · RNG · 숨은 정보 · AI 불변."""
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    json.dumps(report.to_dict(), ensure_ascii=False, default=str)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    assert (
        live_duel(repository, seed=29).state.state_hash()
        == live_duel(repository, seed=29).state.state_hash()
    )


def test_30_the_search_ranking_digest_is_unchanged(repository):
    """
    §11 · §14 — 검색/AI 회귀: 6판 611결정 digest 가 그대로다.

    .. note::
       digest 값을 여기에 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은
       파일이 못 박은 값을 기준으로 쓴다 (3-F-18 ``test_25`` 와 같은 방식).
    """
    import hashlib

    pinned: dict[str, set[str]] = {}
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative == MYSELF:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 64
                and all(c in "0123456789abcdef" for c in node.value)
            ):
                pinned.setdefault(relative, set()).add(node.value)
    counts: dict[str, int] = {}
    for values in pinned.values():
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    expected, pins = max(counts.items(), key=lambda item: item[1])
    assert pins >= 7, counts

    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(
            repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=seed
        )
        transcript = DuelRunner(
            duel, (search_policy(duel), search_policy(duel))
        ).run()
        decisions += len(transcript.entries)
        digest.update(
            repr(
                [
                    (
                        entry.seat,
                        entry.policy,
                        entry.action.kind.value if entry.action is not None else None,
                        entry.action.source.value
                        if entry.action is not None and entry.action.source is not None
                        else None,
                        entry.accepted,
                    )
                    for entry in transcript.entries
                ]
            ).encode()
        )

    assert decisions == 611
    assert digest.hexdigest() == expected
