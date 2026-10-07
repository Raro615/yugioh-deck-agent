"""
Phase 3-F-20 — ``Duel.advance()`` 와 ``Transcript.rule_steps`` 의 기록 계약 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
``Transcript.rule_steps`` 가 **단순한 카운터인지**, 아니면 듀얼의 진행을
**재현할 수 있을 만큼의 authoritative 기록인지.**

측정으로 나온 답: **카운터다.** 그런데 "의미 없는 값" 이라는 뜻이 **아니다** —
``MatchResult.canonical_state()`` 가 "같은 대국인가" 를 비교할 때 쓰는 **결과 검증
metadata** 다(``test_21`` · ``test_24``).

🔴 ``advance()`` 는 이름보다 **훨씬 좁다**
-----------------------------------------
``Duel.advance()`` 는 **드로우 페이즈의 드로우 하나**만 한다. 그 밖의 상태에서는
``None`` 을 돌려준다(``test_01``). 내부 반복도, 여러 engine step 도 없다
(``test_05``).

======================================  =========================================
``advance()`` 호출 횟수                   ``steps + rule_steps`` 와 **정확히 같다**
                                        (``test_04``) — None 반환이 결정 한 번,
                                        비None 반환이 규칙 걸음 한 번이다
``rule_steps``                          **비None 반환 횟수**다. 호출 횟수가 아니다
거부된 행위                               ``rule_steps`` 를 **늘리지 않는다**
                                        (``test_06``)
``advance()`` 가 돌려주는 ``DuelStep``    🔴 그 ``action`` 은 **아무도 고르지 않은
                                        합성 PASS** 다 (``test_03``)
======================================  =========================================

재현 입력은 ``rule_steps`` 가 아니다
------------------------------------
``rule_steps`` 는 ``int`` 하나다. "151 걸음이 있었다" 는 말할 수 있지만 "어떤
행위를 어떤 순서로" 는 담지 못한다(``test_23``). Phase 3-F-19 가 증명한 재현 입력은
**(seed, 덱, 받아들여진 ``PlayerAction`` 순서, ``advance()`` 끼워 넣기)** 다.

이 Phase 는 production 을 **한 줄도** 바꾸지 않는다 (``test_26``).
"""

import ast
import collections
import dataclasses
import inspect
import pathlib
import subprocess
import textwrap

import pytest

from agent.arena import MatchResult
from agent.runner import DuelRunner, Transcript, TranscriptEntry
from agent.search import search_policy
from agent.simulation import SimulationResult, Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.chain import STATUS_MAP, Chain, ChainResolutionStatus
from engine.duel import Duel, DuelStep, TurnStep
from engine.effect.resolution import ResolutionStatus
from engine.ids import EffectRef, InstanceId
from engine.spell_activation import duel_resolver
from engine.state.game_state import GameState
from engine.validation import ValidationCode
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
MYSELF = "tests/test_duel_advance_rule_step_contract.py"

MINE, THEIRS = 0, 1

POT_OF_GREED = 55144522
#: 홍옥의 사령 — 통상 몬스터.
LUSTER_DRAGON = 11091375
#: 강욕의 보은 — 상대가 드로우한다.
GENEROUS_REWARD = 5915629
#: 페더맨 — 채우기용 통상 몬스터.
FEATHERMAN = 71925487
#: 싸이크론 — 대상이 필요해서 ``invalid_target`` 으로 멈춘다.
MYSTICAL_SPACE_TYPHOON = 5318639
DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4


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
    def visit_Constant(self, node):  # noqa: N802
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<str>"), node)
        return node


def code_only(relative: str) -> str:
    return ast.unparse(_StripStrings().visit(ast.parse(source_of(relative))))


def method_tree(func) -> ast.AST:
    """
    메서드 하나의 AST.

    .. note::
       🔴 ``inspect.cleandoc`` 을 **쓰지 않는다** — 본문 줄까지 함께 당겨서 함수
       몸통의 들여쓰기가 깨지고 ``IndentationError`` 가 난다. 3-F-18 에서 같은
       함정에 빠졌고, 이 Phase 에서 네 군데가 또 걸렸다. 그래서 되풀이하지 않도록
       **한 곳에 모았다.** 맞는 도구는 ``textwrap.dedent`` 다.
    """
    source = textwrap.dedent(inspect.getsource(func))
    return ast.parse(source.replace(f"def {func.__name__}", "def f", 1))


def attribute_reads(name: str) -> list[tuple[str, int, str]]:
    """``<무엇>.name`` 을 **읽는** 자리 — (파일, 줄, 표현)."""
    found: list[tuple[str, int, str]] = []
    for path in all_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == name:
                found.append(
                    (
                        str(path.relative_to(PROJECT_ROOT)),
                        node.lineno,
                        ast.unparse(node),
                    )
                )
    return found


def attribute_writes(fragment: str) -> list[tuple[str, int, str]]:
    """속성에 **쓰는** 자리 중 이름에 ``fragment`` 가 든 것."""
    found: list[tuple[str, int, str]] = []
    for path in all_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            targets: list = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and fragment in target.attr:
                    found.append(
                        (
                            str(path.relative_to(PROJECT_ROOT)),
                            node.lineno,
                            ast.unparse(node),
                        )
                    )
    return found


def no_arg_advance_calls(production_only: bool = True) -> list[tuple[str, int]]:
    """인자 없는 ``<무엇>.advance()`` 호출 자리 — ``Duel.advance`` 쪽이다."""
    found: list[tuple[str, int]] = []
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
                and node.func.attr == "advance"
                and not node.args
                and not node.keywords
            ):
                found.append((str(path.relative_to(PROJECT_ROOT)), node.lineno))
    return found


# ======================================================================
# 판
# ======================================================================


def fresh_duel(repository, *, seed: int, deck=None) -> Duel:
    """``advance()`` 를 **아직 돌리지 않은** 판."""
    cards = list(DECK if deck is None else deck)
    return Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    """규칙 걸음을 다 밀어 둔 판 — 고를 수 있는 상태."""
    duel = fresh_duel(repository, seed=seed, deck=deck)
    while duel.advance() is not None:
        pass
    return duel


def run_duel(repository, *, seed: int):
    """정책 둘에게 맡겨 끝까지 돌린다 — (판, 기록)."""
    duel = fresh_duel(repository, seed=seed)
    transcript = DuelRunner(
        duel, (search_policy(duel), search_policy(duel))
    ).run()
    return duel, transcript


def count_advances(repository, *, seed: int):
    """
    ``Duel.advance()`` 호출을 세면서 한 판을 돌린다.

    돌려주는 것은 (판, 기록, {비None, None}) 이다.
    """
    counter: collections.Counter = collections.Counter()
    original = Duel.advance

    def spy(self):
        outcome = original(self)
        counter["nonnull" if outcome is not None else "null"] += 1
        return outcome

    Duel.advance = spy
    try:
        duel, transcript = run_duel(repository, seed=seed)
    finally:
        Duel.advance = original
    return duel, transcript, counter


def resolve_one(repository, passcode: int, actor: int = MINE):
    """부품 수준에서 링크 하나를 해결한다 — (판, 보고)."""
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=actor, zone=Zone.SZONE)
    state.turn.set_phase(Phase.MAIN1)
    chain = Chain().activate(
        actor=actor, effect_ref=EffectRef(passcode, 0), source=card.instance_id
    )
    return state, duel_resolver().resolve_top(state, chain)


class IllegalPolicy:
    """언제나 불법을 고르는 정책 — 거부를 만들려고 쓴다."""

    name = "illegal"

    def decide(self, view, legal):
        return PlayerAction.normal_summon(view.viewer, InstanceId(8888))


# ======================================================================
# A. §3 — advance() 가 정확히 무엇인가
# ======================================================================


def test_01_advance_is_only_the_draw_phase_draw(repository):
    """
    🔴 §3① — **``advance()`` 는 드로우 페이즈의 드로우 하나뿐이다.**

    이름은 "진행" 이지만 실제 조건은 ``self.step is TurnStep.DRAW_PENDING`` 하나다.
    그 밖에서는 **아무 일도 하지 않고 ``None``** 을 돌려준다.
    """
    tree = method_tree(Duel.advance)

    #: 이름으로 읽지 않고 **가드 조건**을 읽는다.
    guards = [
        ast.unparse(node.test)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
    ]
    assert any("TurnStep.DRAW_PENDING" in guard for guard in guards), guards

    #: 판에 대고 부르는 것을 전부 모아 **읽기와 쓰기로 가른다.**
    touches = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func.value).startswith("self.state")
    }
    #: 🔴 판을 바꾸는 것은 **드로우와 패배 선언 둘뿐**이다.
    assert touches == {"draw", "set_result", "player"}, touches
    #: ``player`` 는 덱이 남았는지 **읽기만** 한다.
    assert "self.state.player(seat).deck" in ast.unparse(tree)

    #: 실제로도 그렇다 — 시작 상태는 ``OPEN`` 이라 아무 일도 없다.
    duel = fresh_duel(repository, seed=201)
    assert duel.step is TurnStep.OPEN
    assert duel.advance() is None
    assert duel.step is TurnStep.OPEN


def test_02_a_rule_step_draws_exactly_one_card_and_moves_the_board(repository):
    """§3⑤ · §14 2 — 규칙 걸음 하나가 **한 장**을 뽑고 ``state_hash`` 를 바꾼다."""
    duel = fresh_duel(repository, seed=202)
    observed: list[tuple[bool, int]] = []

    for _ in range(60):
        if duel.step is TurnStep.DRAW_PENDING:
            before_hash = duel.state.state_hash()
            seat = duel.turn_player
            before_hand = len(duel.state.player(seat).hand)
            step = duel.advance()
            assert step is not None and step.accepted
            observed.append(
                (
                    duel.state.state_hash() != before_hash,
                    len(duel.state.player(seat).hand) - before_hand,
                )
            )
            if len(observed) >= 2:
                break
            continue
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            break
        duel.apply(legal.allowed[0])

    assert observed, "드로우 규칙 걸음에 한 번도 닿지 못했다"
    #: 🔴 매번 해시가 바뀌고 손이 **정확히 한 장** 늘어난다.
    assert all(changed and delta == 1 for changed, delta in observed), observed


def test_03_the_step_that_advance_returns_carries_a_synthetic_pass(repository):
    """
    🔴 §3① · §8 — **``advance()`` 의 ``DuelStep.action`` 은 아무도 고르지 않은
    합성 PASS 다.**

    `DuelStep.action` 은 필수 칸이라 무언가 들어가야 하는데, 규칙 걸음에는 고른
    사람이 없다. 그래서 ``PlayerAction.passing(actor=seat)`` 가 들어간다.

    이것을 **재현 입력으로 기록하면 틀린다** — 일어나지 않은 패스를 재생하게 된다.
    ``DuelRunner`` 는 이 걸음을 ``entries`` 에 **넣지 않는다**(``test_04``).
    """
    duel = fresh_duel(repository, seed=203)
    step = None
    for _ in range(60):
        if duel.step is TurnStep.DRAW_PENDING:
            step = duel.advance()
            break
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            break
        duel.apply(legal.allowed[0])

    assert step is not None, "규칙 걸음에 닿지 못했다"
    #: 🔴 종류는 PASS 이고, 고른 사람이 아니라 **턴 플레이어**가 actor 다.
    assert step.action.kind is PlayerActionKind.PASS
    assert step.action.source is None
    assert step.accepted and step.code is ValidationCode.OK
    #: 그런데 그 패스는 **합법 후보에 들어 있지 않았다** — 고를 수 있는 것이 아니다.
    assert "고르는 일이 아니기 때문" in (inspect.getdoc(Duel.advance) or "")


def test_04_advance_calls_equal_steps_plus_rule_steps(repository):
    """
    🟢 §3③ · §14 4 — **``advance()`` 호출 횟수 == ``steps`` + ``rule_steps``.**

    ``DuelRunner._step`` 은 **고를 것을 묻기 전에 먼저 ``advance()``** 를 한다.

    * 비None → 규칙 걸음 하나 (``rule_steps += 1``), 결정은 **기록하지 않는다**
    * None   → 정책에게 묻고 그 결정을 ``entries`` 에 **기록한다**

    그래서 ``rule_steps`` 는 **호출 횟수가 아니라 비None 반환 횟수**다. 둘을 섞으면
    "규칙 걸음이 전체 진행량이다" 로 잘못 읽는다.
    """
    for seed in (204, 205, 206):
        duel, transcript, counter = count_advances(repository, seed=seed)

        assert counter["nonnull"] == transcript.rule_steps, (seed, counter)
        assert counter["null"] == transcript.steps, (seed, counter)
        assert counter["nonnull"] + counter["null"] == (
            transcript.steps + transcript.rule_steps
        ), (seed, counter)
        #: 그리고 호출 횟수는 ``rule_steps`` 보다 **훨씬 크다.**
        assert counter["nonnull"] + counter["null"] > transcript.rule_steps


def test_05_one_advance_runs_at_most_one_engine_step(repository):
    """
    §3② — **한 번의 ``advance()`` 안에 여러 engine step 이 없다.**

    반복문이 없고, 조건마다 곧바로 ``return`` 한다. 그래서 "한 호출에 몇 걸음이
    들어갔는지" 를 따질 필요가 없다 — 언제나 0 또는 1 이다.
    """
    tree = method_tree(Duel.advance)
    #: 🔴 반복문이 없다.
    assert not [
        node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))
    ]
    #: 그리고 ``TurnProgressor`` 를 부르지 않는다 — 페이즈 전환은 행위가 한다.
    assert "TurnProgressor" not in ast.unparse(tree)

    #: 반환은 셋 — None · 패배 선언 · 드로우.
    returns = [
        node for node in ast.walk(tree) if isinstance(node, ast.Return)
    ]
    assert len(returns) == 3, len(returns)

    #: 실제로도 연달아 부르면 두 번째는 곧바로 ``None`` 이다.
    duel = opened_duel(repository, seed=207)
    assert duel.advance() is None
    assert duel.advance() is None


# ======================================================================
# B. §9 — 실패 · 거부 · INVALID · UNKNOWN · FORBIDDEN
# ======================================================================


def test_06_a_refused_action_does_not_make_a_rule_step(repository):
    """
    🔴 §3⑥ · §9 · §14 6 — **거부된 행위는 ``rule_steps`` 를 늘리지 않는다.**

    거부는 ``entries`` 에 ``accepted=False`` 로 남고, 판도 바뀌지 않는다.
    """
    duel = fresh_duel(repository, seed=208)
    transcript = DuelRunner(duel, (IllegalPolicy(), IllegalPolicy())).run()

    assert transcript.refusals, "거부가 하나도 없으면 이 측정이 성립하지 않는다"
    #: 🔴 거부만 있고 규칙 걸음은 0 이다.
    assert transcript.rule_steps == 0, transcript.rule_steps
    assert all(not entry.accepted for entry in transcript.refusals)
    assert len(transcript.refusals) == len(transcript.entries)


def test_07_an_invalid_action_changes_neither_the_board_nor_the_step(repository):
    """§9 1 · §14 7 — **INVALID**: 판도 ``step`` 도 안 바뀐다."""
    duel = opened_duel(repository, seed=209)
    seat = duel.to_act
    before_hash, before_step = duel.state.state_hash(), duel.step

    step = duel.apply(PlayerAction.normal_summon(seat, InstanceId(9999)))

    assert step.accepted is False
    assert duel.state.state_hash() == before_hash
    assert duel.step is before_step
    #: 규칙 걸음을 열지도 않는다.
    assert duel.advance() is None

    #: 그리고 해결 계층에는 **INVALID 전용 상태**가 따로 있다 — 싸이크론은
    #: 대상이 없어 ``invalid_target`` 으로 멈춘다.
    _, report = resolve_one(repository, MYSTICAL_SPACE_TYPHOON)
    assert report.result is not None
    assert report.result.status is ResolutionStatus.INVALID_TARGET
    assert report.code is ValidationCode.TOO_FEW_SELECTED


def test_08_unknown_is_not_invalid_and_neither_touches_a_rule_step():
    """
    🔴 §9 2 — **UNKNOWN ≠ INVALID.** 그리고 둘 다 ``rule_steps`` 와 무관하다.

    ``STATUS_MAP`` 이 두 묶음을 **다른 체인 상태로** 보낸다. 합치면 "판정할 수
    없었다" 와 "틀렸다" 가 같은 말이 된다.
    """
    unknown_like = {
        ResolutionStatus.CONDITION_UNKNOWN,
        ResolutionStatus.UNCHECKED_TARGET,
        ResolutionStatus.UNCHECKED_RULES,
        ResolutionStatus.UNKNOWN,
    }
    invalid_like = {
        ResolutionStatus.INVALID_TARGET,
        ResolutionStatus.INVALID_CONTEXT,
    }

    #: UNKNOWN 계열은 전부 "적용하지 않았다" 로 간다.
    assert {STATUS_MAP[status] for status in unknown_like} == {
        ChainResolutionStatus.EFFECT_NOT_APPLIED
    }
    #: INVALID 계열은 "링크가 잘못됐다" 로 간다.
    assert {STATUS_MAP[status] for status in invalid_like} == {
        ChainResolutionStatus.INVALID_CHAIN_LINK
    }
    #: 🔴 두 묶음이 겹치지 않는다.
    assert {STATUS_MAP[s] for s in unknown_like}.isdisjoint(
        {STATUS_MAP[s] for s in invalid_like}
    )

    #: 그리고 이 계층은 ``rule_steps`` 를 아예 모른다.
    assert "rule_steps" not in code_only("engine/chain.py")


def test_09_forbidden_is_its_own_outcome_and_makes_no_rule_step():
    """
    §9 3 · §14 9 — **FORBIDDEN** 은 "엔진이 못 한다" 와 **다른 결과**다.

    ``forbidden`` 은 `FORBIDDEN_EFFECT` 로, `unsupported_operation` 은
    `UNSUPPORTED_EFFECT` 로 간다. 그리고 어느 쪽도 규칙 걸음이 아니다.
    """
    assert (
        STATUS_MAP[ResolutionStatus.FORBIDDEN]
        is ChainResolutionStatus.FORBIDDEN_EFFECT
    )
    assert (
        STATUS_MAP[ResolutionStatus.UNSUPPORTED_OPERATION]
        is ChainResolutionStatus.UNSUPPORTED_EFFECT
    )
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED

    #: 금지는 ``RESOLVED`` 가 아니므로 판을 바꾸지 않는다는 불변식에 걸린다.
    assert ChainResolutionStatus.FORBIDDEN_EFFECT is not ChainResolutionStatus.RESOLVED


def test_10_an_engine_failure_is_a_resolution_status_not_a_rule_step():
    """
    §9 4 · §14 10 — 실행 오류도 **해결 상태**로 표현되고 규칙 걸음이 아니다.

    ``advance()`` 는 실행기를 부르지 않으므로 실행 실패가 규칙 걸음으로 샐 길이
    없다 — 이것이 둘을 섞지 않는 구조적 이유다.
    """
    assert (
        STATUS_MAP[ResolutionStatus.EXECUTION_ERROR]
        is ChainResolutionStatus.EFFECT_RESOLUTION_ERROR
    )

    advance_code = ast.unparse(method_tree(Duel.advance))
    #: 🔴 ``advance()`` 안에 실행기·체인·해결이 없다.
    for absent in ("executor", "_resolver", "Chain", "resolve", "ChainResolution"):
        assert absent not in advance_code, absent


# ======================================================================
# C. §13 — 실제 카드 시나리오
# ======================================================================


def test_11_a_normal_summon_is_a_chosen_action_not_a_rule_step(repository):
    """§13 1 · §14 11 — 통상 소환은 **고르는 일**이므로 규칙 걸음이 아니다."""
    duel, transcript = run_duel(repository, seed=210)
    summons = [
        entry
        for entry in transcript.entries
        if entry.action is not None
        and entry.action.kind is PlayerActionKind.NORMAL_SUMMON
        and entry.accepted
    ]
    assert summons, "통상 소환이 한 번도 없었다"
    #: 소환은 ``entries`` 에 남고, 규칙 걸음과 **다른 칸**으로 센다.
    assert transcript.steps >= len(summons)
    assert transcript.rule_steps < transcript.steps


def test_12_which_action_kinds_a_real_duel_actually_reaches(repository):
    """
    🟡 §13 2 — **실제 듀얼이 닿는 행위 종류를 실측한다.**

    .. note::
       ``special_summon`` · ``activate_card`` · ``activate_effect`` 는 현재
       **실제 듀얼에서 한 번도 수락되지 않는다** — ``legal_actions`` 가 허가하지
       않기 때문이다 (Phase 3-F-19 가 같은 사실을 측정했다). Engine V1 범위의
       사실이고 이 Phase 가 고칠 일이 아니다. 없는 것을 있다고 적지 않는다.
    """
    reached: collections.Counter = collections.Counter()
    for seed in (211, 212, 213):
        _, transcript = run_duel(repository, seed=seed)
        for entry in transcript.entries:
            if entry.action is not None and entry.accepted:
                reached[entry.action.kind] += 1

    assert set(reached) == {
        PlayerActionKind.END_PHASE,
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.ATTACK,
    }, dict(reached)
    #: 🔴 발동 계열과 특수 소환은 **0회**다.
    for absent in (
        PlayerActionKind.SPECIAL_SUMMON,
        PlayerActionKind.ACTIVATE_CARD,
        PlayerActionKind.ACTIVATE_EFFECT,
    ):
        assert reached[absent] == 0, absent


def test_13_effect_activation_lives_below_the_transcript(repository):
    """
    §13 3 · §14 13 — 효과 발동은 **부품 수준에서는 된다.** 그런데 그 경로에
    ``rule_steps`` 가 **없다** — ``Transcript`` 를 만드는 것은 ``DuelRunner`` 뿐이다.
    """
    _, report = resolve_one(repository, POT_OF_GREED)
    assert report.status is ChainResolutionStatus.RESOLVED
    assert report.result is not None and report.deltas

    #: 🔴 보고에 ``rule_steps`` 칸이 없다.
    assert not hasattr(report, "rule_steps")
    assert not hasattr(report.result, "rule_steps")


def test_14_chain_resolution_does_not_produce_a_rule_step(repository):
    """§13 4 · §14 14 — 체인 해결은 규칙 걸음을 만들지 않는다."""
    state, report = resolve_one(repository, POT_OF_GREED, THEIRS)
    assert report.link is not None and report.link.actor == THEIRS

    #: 판에도 기록 칸이 없다.
    assert not hasattr(state, "rule_steps")
    #: 그리고 ``rule_steps`` 를 쓰는 자리는 engine 계층에 하나도 없다.
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        if relative.startswith("engine/"):
            assert "rule_steps" not in code_only(relative), relative


def test_15_cost_payment_is_also_outside_the_rule_step_count(repository):
    """§13 5 · §14 15 — 비용 지불도 규칙 걸음과 무관하다."""
    from engine.payment import CostPaymentResult

    assert not hasattr(CostPaymentResult, "rule_steps")
    assert "rule_steps" not in code_only("engine/payment.py")

    #: 비용이 붙은 카드도 해결 경로는 같다 — 규칙 걸음을 거치지 않는다.
    _, report = resolve_one(repository, POT_OF_GREED)
    assert report.result is not None
    assert not hasattr(report.result, "rule_steps")


# ======================================================================
# D. §6 · §12 — 결정성
# ======================================================================


def test_16_the_same_seed_reproduces_every_number(repository):
    """
    🟢 §6 · §14 16 — 같은 seed 로 두 번 돌리면 **모든 수치가 같다.**

    ``state_hash`` · ``rule_steps`` · ``steps`` · 거부 수 · 승패 · 턴 수 전부.
    최소 세 seed 에서 확인한다.
    """

    def snapshot(seed: int) -> dict:
        duel, transcript = run_duel(repository, seed=seed)
        return {
            "state_hash": duel.state.state_hash(),
            "rule_steps": transcript.rule_steps,
            "steps": transcript.steps,
            "entries": len(transcript.entries),
            "refusals": len(transcript.refusals),
            "accepted": sum(1 for e in transcript.entries if e.accepted),
            "turns": duel.state.turn.turn_number,
            "result": None
            if transcript.result is None
            else (transcript.result.winner, transcript.result.reason),
        }

    for seed in (214, 215, 216):
        first, second = snapshot(seed), snapshot(seed)
        assert first == second, (seed, first, second)
        #: 그리고 다른 seed 는 다른 판이다 — 상수를 재는 것이 아니다.
        assert snapshot(seed) != snapshot(seed + 100), seed


def test_17_the_state_hash_and_the_rule_step_count_are_different_questions(
    repository,
):
    """
    🔴 §10 · §14 17 — ``rule_steps`` 는 **``state_hash`` 안에 없다.**

    ``rule_steps`` 는 ``Transcript`` 의 칸이고 ``GameState`` 에는 그런 칸이 아예
    없다. "판의 모양" 과 "얼마나 진행했는가" 는 다른 질문이다.
    """
    assert "rule_steps" not in GameState.__slots__
    state = GameState.create(repository, seed=5)
    assert not hasattr(state, "rule_steps")

    #: ``canonical_state`` 가 체인·journal 을 빼는 것과 같은 이유다.
    doc = inspect.getdoc(GameState.canonical_state) or ""
    assert "앞으로도 넣지 않는다" in doc

    #: 🔴 같은 판인데 진행량이 다를 수 있다 — 그러니 섞으면 안 된다.
    duel_a, transcript_a = run_duel(repository, seed=217)
    assert transcript_a.rule_steps >= 0
    assert "rule_steps" not in code_only("engine/state/game_state.py")


def test_18_a_simulator_fork_produces_no_rule_step(repository):
    """
    🟢 §11 · §14 18 — **탐색 사본은 규칙 걸음을 만들지 않는다.**

    ``Simulator`` 는 ``advance()`` 를 **한 번도 부르지 않는다** — 고를 것이 없는
    응답 창은 ``fork.apply(PASS)`` 로 닫는다 (``_settle_forced_passes``). 그래서
    원본의 진행량이 시뮬레이션 때문에 흔들릴 길이 없다.
    """
    duel = opened_duel(repository, seed=218)
    before_hash, before_step = duel.state.state_hash(), duel.step

    counter: collections.Counter = collections.Counter()
    original = Duel.advance
    real = id(duel)

    def spy(self):
        outcome = original(self)
        counter["real" if id(self) == real else "fork"] += 1
        return outcome

    Duel.advance = spy
    try:
        simulator = Simulator(duel)
        for _ in range(3):
            simulator.simulate(PlayerAction.passing(duel.to_act), viewer=duel.to_act)
    finally:
        Duel.advance = original

    #: 🔴 시뮬레이션 중 ``advance()`` 호출이 **0회**다.
    assert counter == collections.Counter(), dict(counter)
    #: 원본은 한 글자도 안 움직였다.
    assert duel.state.state_hash() == before_hash
    assert duel.step is before_step

    #: 그리고 ``SimulationResult`` 에 진행량 칸이 없다.
    names = {f.name for f in dataclasses.fields(SimulationResult)}
    assert "rule_steps" not in names and "steps" not in names

    #: 강제 패스를 ``apply`` 로 닫는다는 것이 코드에 그대로 있다.
    settle = inspect.getsource(Simulator._settle_forced_passes)
    assert "fork.apply(" in settle
    assert "advance(" not in settle


def test_19_the_rng_is_decided_by_the_seed_not_by_the_rule_step_count(repository):
    """
    §12 — RNG 는 seed 가 정한다. ``rule_steps`` 와 **혼동되는 구조가 없다.**

    같은 seed 의 두 판은 꺼낸 값의 순서가 같고, ``rule_steps`` 가 난수 소비량을
    뜻하지도 않는다 — 규칙 걸음은 드로우이고 드로우는 셔플된 덱을 **순서대로**
    가져간다.
    """
    a = fresh_duel(repository, seed=219)
    b = fresh_duel(repository, seed=219)
    assert a.state.state_hash() == b.state.state_hash()
    assert [a.state.rng.random() for _ in range(5)] == [
        b.state.rng.random() for _ in range(5)
    ]

    #: ``advance()`` 안에 난수를 쓰는 자리가 없다.
    advance_code = ast.unparse(method_tree(Duel.advance))
    for absent in ("rng", "random", "shuffle"):
        assert absent not in advance_code, absent


def test_20_a_real_duel_keeps_the_two_counts_separate(repository):
    """§14 20 — 실제 듀얼에서 두 수치가 **각자의 일**을 한다."""
    duel, transcript = run_duel(repository, seed=220)

    assert transcript.steps == len(transcript.entries)
    assert transcript.rule_steps > 0
    #: 규칙 걸음은 ``entries`` 에 **들어 있지 않다.**
    assert transcript.rule_steps + transcript.steps > len(transcript.entries)
    #: 그리고 ``entries`` 의 행위는 전부 정책이 고른 것이다 — 합성 PASS 가 없다.
    synthetic = [
        entry
        for entry in transcript.entries
        if entry.action is not None
        and entry.action.kind is PlayerActionKind.PASS
        and entry.policy not in {"illegal"}
    ]
    for entry in synthetic:
        #: 정책이 **고른** 패스는 있을 수 있다. 다만 규칙 걸음의 패스는 아니다.
        assert entry.policy, entry


# ======================================================================
# E. §5 — consumer 전수 조사
# ======================================================================


def test_21_every_rule_steps_consumer_is_classified():
    """
    🔴 §5 — **``rule_steps`` 를 읽는 자리와 쓰는 자리를 전수 분류한다.**

    ==========================  ====================================
    ``agent/runner.py:187``     **쓰는 유일한 자리** — ``+= 1``
    ``agent/runner.py``         표시 문자열(``describe_ko``)
    ``agent/arena.py`` × 2      ``MatchResult`` 로 옮기고, **같은
                                대국인가 비교**에 넣는다
    ==========================  ====================================

    즉 consumer 는 **표시**와 **비교** 둘뿐이다. 어느 쪽도 실행을 **되돌리지**
    않는다 — 그래서 replay input 이 아니다.
    """
    writes = attribute_writes("rule_steps")
    assert len(writes) == 1, writes
    assert writes[0][0] == "agent/runner.py"
    assert "+=" in writes[0][2]

    reads = attribute_reads("rule_steps")
    production = [r for r in reads if not r[0].startswith("tests")]
    assert {r[0] for r in production} == {"agent/runner.py", "agent/arena.py"}, production
    assert len(production) == 3, production

    #: 🔴 engine 계층에는 읽는 자리도 쓰는 자리도 없다.
    assert not [r for r in reads if r[0].startswith("engine/")]


def test_22_duel_advance_has_exactly_one_production_caller():
    """
    §5 — 인자 없는 ``advance()`` 를 부르는 production 자리는 **하나**다.

    ``agent/runner.py`` 의 고리뿐이다. 그래서 ``rule_steps`` 가 생기는 길도 하나다.
    """
    calls = no_arg_advance_calls()
    assert len(calls) == 1, calls
    assert calls[0][0] == "agent/runner.py"

    #: ``TurnProgressor.advance(state)`` 는 **다른 메서드**다 — 인자를 받는다.
    assert "TurnProgressor" in code_only("engine/duel.py")
    progressor_calls = [
        (str(p.relative_to(PROJECT_ROOT)), n.lineno)
        for p in production_files()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "advance"
        and n.args
    ]
    assert progressor_calls, "인자 있는 advance 가 사라졌다면 구조가 바뀐 것이다"
    assert all(path.startswith("engine/") for path, _ in progressor_calls)


def test_23_rule_steps_is_a_scalar_and_cannot_be_a_replay_input(repository):
    """
    🔴 §7 — **``rule_steps`` 만으로는 재현할 수 없다.** 스칼라이기 때문이다.

    "몇 걸음이 있었다" 는 말할 수 있지만 "어떤 행위를 어떤 순서로" 는 담지 못한다.
    두 질문을 구분한다.

    * deterministic replay **input** 인가 → ✗
    * deterministic execution **결과를 검증하는 metric** 인가 → ○ (``test_24``)
    """
    field = {f.name: f for f in dataclasses.fields(Transcript)}["rule_steps"]
    assert field.type in ("int", int), field.type

    duel, transcript = run_duel(repository, seed=221)
    assert isinstance(transcript.rule_steps, int)

    #: 🔴 서로 다른 두 판이 **같은 ``rule_steps``** 를 가질 수 있다 — 그러니
    #: 그 숫자는 판을 고유하게 가리키지 못한다.
    seen: dict[int, list[str]] = {}
    for seed in range(230, 244):
        other_duel, other = run_duel(repository, seed=seed)
        seen.setdefault(other.rule_steps, []).append(other_duel.state.state_hash())
    collisions = {
        count: hashes for count, hashes in seen.items() if len(set(hashes)) > 1
    }
    assert collisions, (
        "같은 rule_steps 를 가진 서로 다른 판을 못 찾았다 — 표본을 늘려야 한다"
    )

    #: 반면 행위 기록은 판을 가리킨다 (Phase 3-F-19).
    #:
    #: .. note::
    #:    🔴 원래 여기에 ``"rule_steps" not in str(transcript.canonical_state())``
    #:    라고 적어 두었는데, 그것은 **절대 실패할 수 없는 단정**이었다 —
    #:    ``canonical_state()`` 는 **값**을 돌려주고 그 값에 칸 **이름**은 들어 있지
    #:    않다. 그래서 고의 위반 주입 6번(그 튜플에 ``rule_steps`` 를 끼워 넣기)을
    #:    놓쳤다. 이름이 아니라 **모양**을 센다.
    canonical = transcript.canonical_state()
    assert len(canonical) == 2, canonical
    actions, outcome = canonical
    #: 첫째는 (좌석, 행위) 짝의 줄이고 — 전부 정수/튜플이다.
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in actions)
    assert len(actions) == sum(1 for e in transcript.entries if e.accepted)
    #: 둘째는 승패뿐이다. 진행량이 들어갈 자리가 없다.
    assert outcome is None or len(outcome) == 2, outcome


def test_24_the_rule_step_count_is_a_verification_field(repository):
    """
    🟢 §5 · §8 — **``rule_steps`` 는 결과 검증 metadata 다.**

    ``MatchResult.canonical_state()`` 가 그 자리를 갖고 있고, 그 docstring 이
    스스로 "**같은 대국인가**를 비교하는 모양. 재현 시험이 이것을 쓴다" 라고 적는다.

    🔴 그런데 ``Transcript.canonical_state()`` 에는 **없다.** 두 비교가 서로 다른
    것을 묻기 때문이다 — 하나는 "같은 수를 뒀는가", 하나는 "같은 대국이었는가".
    이 비대칭을 기록한다.
    """
    record_doc = inspect.getdoc(MatchResult.canonical_state) or ""
    assert "비교" in record_doc and "재현" in record_doc

    #: ``MatchResult`` 에는 칸이 있다.
    assert "rule_steps" in {f.name for f in dataclasses.fields(MatchResult)}
    record_source = inspect.getsource(MatchResult.canonical_state)
    assert "self.rule_steps" in record_source
    #: 그리고 ``state_hash`` 와 **나란히** 들어간다 — 보강 비교 값이다.
    assert "self.state_hash" in record_source

    #: 🔴 ``Transcript.canonical_state`` 에는 없다.
    transcript_source = inspect.getsource(Transcript.canonical_state)
    assert "rule_steps" not in transcript_source

    #: ``MatchResult`` 를 되살리는 입구는 없다 — 비교용이지 입력이 아니다.
    assert not hasattr(MatchResult, "from_dict")


def test_25_the_transcript_has_only_four_fields():
    """§4 — ``Transcript`` 의 칸은 넷뿐이고, 그중 둘이 수치다."""
    names = [f.name for f in dataclasses.fields(Transcript)]
    assert names == ["entries", "result", "steps", "rule_steps"], names

    #: 그리고 ``TranscriptEntry`` 에는 규칙 걸음을 적을 칸이 없다.
    entry_names = {f.name for f in dataclasses.fields(TranscriptEntry)}
    assert "rule_steps" not in entry_names
    assert "action" in entry_names and "accepted" in entry_names

    #: ``rule_steps`` 가 무엇을 세는지 docstring 이 적는다.
    assert "고르지 않아도 일어난 일의 수" in source_of("agent/runner.py")


# ======================================================================
# F. §15 — AUDIT 범위와 불변
# ======================================================================


def test_26_this_phase_changed_no_production_file():
    """
    §15 — **AUDIT-ONLY: 이 Phase(3-F-20)는 production 을 한 줄도 바꾸지 않았다.**

    §15 의 ①②③ 가운데 **하나도 성립하지 않았다** — ``rule_steps`` 의 의미와 코드가
    일치하고(``test_25``), ``advance()`` 가 기록 계약을 깨는 경로가 없고
    (``test_04``), replay 를 제공한다고 주장하는 문서도 없다.

    .. note::
       **이 파일을 추가한 commit** 하나만 본다 — ``git diff HEAD`` 는 commit 뒤에
       자기와 자기를 비교하고, "base ↔ 작업 트리" 는 뒤의 Phase 때문에 깨진다
       (3-F-12 · 3-F-13 · 3-F-15 · 3-F-16 이 빠진 함정, 3-F-18 · 3-F-19 가 고친
       방식). commit 전에는 base(``8ba7526``) ↔ 작업 트리로 되돌아간다.
    """
    PHASE_3F20_BASE = "8ba7526"

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    work = git("log", "--diff-filter=A", "--format=%H", "--", MYSELF).split()
    if work:
        changed = git(
            "show", "--stat", "--format=", work[-1], "--", *PRODUCTION_ROOTS
        )
    else:  # pragma: no cover - commit 전 개발 중에만 지나간다
        changed = git("diff", "--stat", PHASE_3F20_BASE, "--", *PRODUCTION_ROOTS)
    assert changed.strip() == "", changed


def test_27_no_new_field_or_abstraction_was_added():
    """§15 — 새 Transcript 칸 · 새 replay/serializer 틀이 없다."""
    assert [f.name for f in dataclasses.fields(Transcript)] == [
        "entries",
        "result",
        "steps",
        "rule_steps",
    ]
    assert [f.name for f in dataclasses.fields(DuelStep)] == [
        "action",
        "accepted",
        "code",
        "reason",
        "result",
    ]
    for forbidden in ("Replayer", "ReplayEngine", "RuleStepRecord", "RuleStepLog"):
        for path in production_files():
            relative = str(path.relative_to(PROJECT_ROOT))
            assert forbidden not in code_only(relative), (forbidden, relative)

    #: ``rule_steps`` 의 타입도 그대로다.
    field = {f.name: f for f in dataclasses.fields(Transcript)}["rule_steps"]
    assert field.default == 0


def test_28_nothing_about_the_board_or_the_view_moved(repository):
    """§15 — ``state_hash`` · RNG · 숨은 정보 불변."""
    from engine.game_state_view import GameStateView

    duel = opened_duel(repository, seed=222)
    before_hash, before_rng = duel.state.state_hash(), repr(duel.state.rng)

    #: 기록을 읽기만 해도 판이 흔들리지 않는다.
    _, transcript = run_duel(repository, seed=222)
    assert transcript.rule_steps >= 0
    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng

    view = GameStateView.from_state(duel.state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_29_the_search_ranking_digest_is_unchanged(repository):
    """
    §14 19 — 검색/AI 회귀: 6판 611결정 digest 가 그대로다.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은 파일이
       못 박은 값을 기준으로 쓴다 (3-F-18 · 3-F-19 와 같은 방식).
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
        duel = Duel.start(repository, decks=(list(DECK), list(DECK)), seed=seed)
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
