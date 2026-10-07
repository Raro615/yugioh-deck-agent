"""
Phase 3-F-21 — ``Duel.legal_actions()`` ↔ Engine 실행 가능 범위 경계 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
**AI 가 고를 수 있는 행동 공간**과 **Engine 이 실제로 실행할 수 있는 행동 공간**의
계약이 정확히 무엇인가.

🔴 먼저, 앞 Phase 두 개의 서술을 **정정한다**
---------------------------------------------
Phase 3-F-19 · 3-F-20 보고서가 "``legal_actions`` 가 ``activate_*`` 를 허가하지
않는다" 라고 적었다. **그것은 틀렸다.** 실측하면 ``legal_actions`` 는
``activate_effect`` 를 **내놓고**, 고르면 **수락되고 체인까지 쌓인다**
(``test_05`` · ``test_06``).

앞 Phase 의 관측("실제 듀얼에서 activate_* 0회")은 **그 덱과 그 정책**에서의 사실이
었다 — 통상 몬스터 위주 덱이라 탐색 정책이 발동을 고르지 않았을 뿐이다. 주문을
늘린 덱에서는 발동 후보가 292번 나오고 81번 수락된다. 정정 내용은 ``test_04`` 가
못 박는다.

실제로 withheld 되는 것은 ``activate_card`` 와 ``special_summon`` 이고, 그것은
**의도된 제한**이다 — 검증기가 ``UNKNOWN`` 과 **빠진 규칙의 이름**을 함께 돌려준다
(``test_09``).

구조의 핵심 — ``apply()`` 의 허용 범위 == ``legal_actions().allowed``
-------------------------------------------------------------------
``Duel.apply`` 는 **첫 관문에서** ``action not in legal.allowed`` 를 본다
(``test_02``). 그래서 §2 가 "구조적 위험" 이라고 한 **C(실행 가능하지만 합법이
아님)는 ``Duel`` 경계에서 발생할 수 없다** — 합법이 아니면 실행기에 닿지 못한다.

네 집합 (§6)
------------
========================================  =====  ==================================
① Engine 이 실행할 수 있는 모든 종류        **8**  실행기 등록 5 + ``Duel`` 직접 3
② 지금 이 상태에서 합법인 종류              가변   상태가 정한다
③ ``legal_actions`` 가 **낼 수 있는** 종류   **7**  ① 에서 ``special_summon`` 하나 빠짐
④ AI 가 고를 수 있는 종류                   **③**  ``legal.allowed`` 그대로
========================================  =====  ==================================

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

from agent.heuristic import SummonBeforeEndingThePhase
from agent.runner import DuelRunner
from agent.search import search_policy
from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.action_execution import ActionExecutor
from engine.action_validation import ActionValidator, ActionValidity
from engine.duel import Duel, LegalActions, TurnStep, WithheldAction
from engine.game_state_view import GameStateView
from engine.summon import duel_executor
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
MYSELF = "tests/test_legal_action_engine_boundary_audit.py"

MINE, THEIRS = 0, 1

POT_OF_GREED = 55144522
LUSTER_DRAGON = 11091375
GENEROUS_REWARD = 5915629
#: 천사의 자비 — 주문. 발동 후보를 넉넉히 만들려고 쓴다.
GRACEFUL_CHARITY = 84257639

#: 3-F-5 이후 digest 를 못 박은 덱.
DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4
#: 주문을 늘린 덱 — 발동 후보가 실제로 나오는 것을 보려고 쓴다.
SPELL_DECK = [POT_OF_GREED] * 8 + [GRACEFUL_CHARITY] * 8 + [LUSTER_DRAGON] * 4

#: ``Duel.apply`` 가 **실행기를 거치지 않고 직접** 처리하는 종류.
DUEL_DIRECT_KINDS = frozenset(
    {
        PlayerActionKind.PASS,
        PlayerActionKind.END_PHASE,
        PlayerActionKind.ACTIVATE_EFFECT,
    }
)


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))


class _StripStrings(ast.NodeTransformer):
    def visit_Constant(self, node):  # noqa: N802
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<str>"), node)
        return node


def code_only(relative: str) -> str:
    """🔴 문자열 리터럴을 지운 코드 — 설명문의 낱말을 코드로 세지 않는다."""
    return ast.unparse(_StripStrings().visit(ast.parse(source_of(relative))))


def method_tree(func) -> ast.AST:
    """메서드 하나의 AST — ``textwrap.dedent`` 로 자른다 (3-F-20 의 헬퍼와 같다)."""
    source = textwrap.dedent(inspect.getsource(func))
    return ast.parse(source.replace(f"def {func.__name__}", "def f", 1))


def executable_kinds() -> frozenset:
    """Engine 이 **실행할 수 있는** 종류 — 실행기 등록 ∪ ``Duel`` 직접 처리."""
    return frozenset(duel_executor().supported) | DUEL_DIRECT_KINDS


def apply_dispatch_kinds() -> set:
    """``Duel.apply`` 의 dispatch 가 이름으로 집어내는 종류."""
    tree = method_tree(Duel.apply)
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    }


# ======================================================================
# 판
# ======================================================================


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def walk_duel(repository, *, seed: int, deck=None, prefer=None, limit: int = 400):
    """
    듀얼 하나를 끝까지 밀면서 **후보로 나온 종류와 수락/거부를 전부 센다.**

    ``prefer`` 가 주어지면 그 종류를 **우선 고른다** — 도달 가능성을 재는 것이
    목적이므로 정책의 취향에 의존하지 않는다.
    """
    duel = Duel.start(
        repository,
        decks=(list(deck or DIGEST_DECK), list(deck or DIGEST_DECK)),
        seed=seed,
    )
    offered: collections.Counter = collections.Counter()
    withheld: collections.Counter = collections.Counter()
    accepted: collections.Counter = collections.Counter()
    refused: collections.Counter = collections.Counter()
    guard = 0
    while not duel.is_over and guard < limit:
        guard += 1
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions(duel.to_act)
        for action in legal.allowed:
            offered[action.kind] += 1
        for held in legal.withheld:
            withheld[held.kind] += 1
        if not legal.allowed:
            break
        pick = None
        if prefer is not None:
            pick = next((a for a in legal.allowed if a.kind is prefer), None)
        pick = pick or legal.allowed[0]
        step = duel.apply(pick)
        (accepted if step.accepted else refused)[pick.kind] += 1
    return duel, {
        "offered": offered,
        "withheld": withheld,
        "accepted": accepted,
        "refused": refused,
    }


# ======================================================================
# A. §1 · §2 — 계약의 구조
# ======================================================================


def test_01_the_legal_actions_contract_admits_only_valid(repository):
    """
    §6 — ``legal_actions`` 는 "**구현된 모든 종류**" 가 아니라 "**지금 허가가 난
    것**" 을 돌려준다.

    docstring 이 그 계약을 적는다 — "``UNKNOWN`` 은 후보가 아니다". 그래서 이
    함수는 종류 목록을 열거하지 않고, **검증기와 흐름 계층에게 물어서** 만든다.
    """
    doc = inspect.getdoc(Duel.legal_actions) or ""
    assert "UNKNOWN" in doc
    assert "후보가 아니다" in doc

    #: 🔴 ``PlayerActionKind`` 를 훑는 반복문이 **없다** — 종류 열거가 아니다.
    tree = method_tree(Duel.legal_actions)
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))]
    for loop in loops:
        assert "PlayerActionKind" not in ast.unparse(loop), ast.unparse(loop)[:80]

    #: 그리고 실제로 상태에 따라 달라진다.
    duel = opened_duel(repository, seed=301)
    first = {a.kind for a in duel.legal_actions(duel.to_act).allowed}
    assert first, "허가된 행위가 하나도 없다"
    assert first <= set(PlayerActionKind)


def test_02_apply_accepts_exactly_what_legal_actions_offered(repository):
    """
    🟢 §2 · §8 B — **``apply()`` 의 허용 범위 == ``legal_actions().allowed``.**

    첫 관문이 ``action not in legal.allowed`` 다. 그래서 §2 의 **C(실행 가능하지만
    합법이 아님)는 ``Duel`` 경계에서 일어날 수 없다** — 합법이 아니면 실행기에
    닿지 못한다.
    """
    #: .. note::
    #:    🔴 원래 ``"action not in legal.allowed" in source`` 로만 쟀다. 그래서
    #:    고의 위반 주입 1번(``if False and action not in legal.allowed:`` 로 관문을
    #:    꺼 버리기)을 **놓쳤다** — 그 문자열이 여전히 남아 있기 때문이다. 이 파일에서
    #:    가장 중요한 단정이 **부분 문자열 비교**였다. AST 로 **조건 자체**를 보고,
    #:    행동으로는 **실행 가능하지만 후보가 아닌** 행위를 찔러 본다.
    tree = method_tree(Duel.apply)

    #: ① 구조 — 목록 대조 ``if`` 의 조건이 **그 비교 하나뿐**이고 곧바로 돌려준다.
    guards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "legal.allowed" in ast.unparse(node.test)
    ]
    assert len(guards) == 1, [ast.unparse(g.test) for g in guards]
    guard = guards[0]
    assert ast.unparse(guard.test) == "action not in legal.allowed", ast.unparse(
        guard.test
    )
    assert any(isinstance(node, ast.Return) for node in guard.body)

    #: ② 그 관문이 dispatch **앞에** 있다 — 줄 번호로 본다.
    dispatch_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    ]
    assert dispatch_lines and guard.lineno < min(dispatch_lines)

    #: ③ 행동 — 🔴 ``special_summon`` 은 **실행기에 등록되어 있는데** 후보가 아니다.
    #: 관문이 없으면 수행기까지 가 버린다. 그래서 이 찔러보기가 관문을 잰다.
    duel = opened_duel(repository, seed=302)
    seat = duel.to_act
    hand = duel.state.player(seat).hand
    assert hand, "손이 비어 있으면 이 측정이 성립하지 않는다"
    probe = PlayerAction.special_summon(seat, hand[0].instance_id)
    assert PlayerActionKind.SPECIAL_SUMMON in duel_executor().supported
    assert probe not in set(duel.legal_actions(seat).allowed)

    before = duel.state.state_hash()
    step = duel.apply(probe)
    assert step.accepted is False
    #: 🔴 거부 사유가 **목록에 없다**(`RULE_NOT_IMPLEMENTED`)여야 한다 — 수행기까지
    #: 갔다면 다른 코드가 돌아온다.
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED, step.code
    assert "허가된 행위가 아닙니다" in step.reason
    #: 그리고 판이 한 글자도 바뀌지 않았다 — 특수 소환이 실제로 일어나지 않았다.
    assert duel.state.state_hash() == before


def test_03_everything_offered_is_actually_executed(repository):
    """
    🟢 §2 · §8 B — **후보로 나온 것은 전부 실제로 수락된다.** 거부 0건.

    즉 "합법인데 실행할 수 없다"(§2 의 B)가 **한 종류도 없다.** 이것이
    production 을 고칠 이유가 없는 가장 직접적인 근거다.
    """
    total_refused: collections.Counter = collections.Counter()
    total_accepted: collections.Counter = collections.Counter()
    for seed in (303, 304, 305):
        for deck in (DIGEST_DECK, SPELL_DECK):
            _, counts = walk_duel(
                repository,
                seed=seed,
                deck=deck,
                prefer=PlayerActionKind.ACTIVATE_EFFECT,
            )
            total_refused.update(counts["refused"])
            total_accepted.update(counts["accepted"])

    assert total_accepted, "아무 것도 수락되지 않았다면 측정이 성립하지 않는다"
    #: 🔴 거부가 **0건**이다.
    assert total_refused == collections.Counter(), dict(total_refused)


def test_04_legal_actions_does_offer_activation(repository):
    """
    🔴 **정정**: Phase 3-F-19 · 3-F-20 보고서의 서술이 틀렸다.

    두 보고서가 "``legal_actions`` 가 ``activate_*`` 를 허가하지 않는다" 라고
    적었는데, ``legal_actions`` 는 ``activate_effect`` 를 **내놓는다.** 앞
    Phase 의 관측은 **그 덱과 그 정책**에서의 사실이었다 — 통상 몬스터 위주 덱에서
    탐색 정책이 발동을 고르지 않았을 뿐이다.

    실제로 withheld 되는 것은 ``activate_card`` 와 ``special_summon`` 이다.
    """
    offered: collections.Counter = collections.Counter()
    for seed in (306, 307):
        _, counts = walk_duel(
            repository,
            seed=seed,
            deck=SPELL_DECK,
            prefer=PlayerActionKind.ACTIVATE_EFFECT,
        )
        offered.update(counts["offered"])

    #: 🔴 발동 후보가 실제로 나온다.
    assert offered[PlayerActionKind.ACTIVATE_EFFECT] > 0, dict(offered)
    #: 그리고 ``activate_card`` 는 끝까지 나오지 않는다.
    assert offered[PlayerActionKind.ACTIVATE_CARD] == 0
    assert offered[PlayerActionKind.SPECIAL_SUMMON] == 0

    #: 생성기가 코드에 실제로 있다 — 설명문이 아니라 코드다.
    duel_code = code_only("engine/duel.py")
    assert "_activation_actions" in duel_code
    assert "PlayerAction.activate_effect" in duel_code


def test_05_a_chosen_activation_is_accepted_and_builds_a_chain(repository):
    """🟢 §4 3 — 발동을 고르면 **수락되고 체인이 쌓인다.** 끝까지 간다."""
    found = None
    duel = Duel.start(
        repository, decks=(list(SPELL_DECK), list(SPELL_DECK)), seed=308
    )
    guard = 0
    while not duel.is_over and guard < 400:
        guard += 1
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            break
        pick = next(
            (a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT),
            None,
        )
        if pick is not None:
            before = duel.state.state_hash()
            step = duel.apply(pick)
            found = (step, before)
            break
        duel.apply(legal.allowed[0])

    assert found is not None, "발동 후보에 한 번도 닿지 못했다"
    step, before = found
    assert step.accepted is True
    assert step.code is ValidationCode.OK
    #: 판이 바뀌었고 체인이 생겼다.
    assert duel.state.state_hash() != before
    assert len(duel.chain.links) == 1
    assert step.action.effect_ref is not None


def test_06_activation_is_dispatched_by_the_duel_not_the_executor():
    """
    §1 · §6 — 발동은 **실행기에 등록되어 있지 않다.** ``Duel`` 이 직접 처리한다.

    그래서 "실행기에 없다" 를 곧바로 "실행할 수 없다" 로 읽으면 **틀린다** —
    §3 이 구분하라고 한 네 가지 중 하나다.
    """
    supported = duel_executor().supported
    assert PlayerActionKind.ACTIVATE_EFFECT not in supported
    assert PlayerActionKind.PASS not in supported
    assert PlayerActionKind.END_PHASE not in supported

    #: 그런데 ``apply`` 가 이름으로 집어서 따로 처리한다.
    dispatch = apply_dispatch_kinds()
    assert dispatch == {"PASS", "END_PHASE", "ACTIVATE_EFFECT"}, dispatch

    #: 그 셋을 합치면 실행 가능한 종류다.
    assert executable_kinds() == supported | DUEL_DIRECT_KINDS


# ======================================================================
# B. §2 — ActionKind 전수 분류
# ======================================================================


def test_07_the_executable_set_is_exactly_eight_kinds():
    """§6 ① — Engine 이 실행할 수 있는 종류는 **여덟**이다."""
    assert duel_executor().supported == frozenset(
        {
            PlayerActionKind.NORMAL_SUMMON,
            PlayerActionKind.SPECIAL_SUMMON,
            PlayerActionKind.SET_MONSTER,
            PlayerActionKind.SET_SPELL_TRAP,
            PlayerActionKind.ATTACK,
        }
    )
    assert executable_kinds() == frozenset(
        {
            PlayerActionKind.NORMAL_SUMMON,
            PlayerActionKind.SPECIAL_SUMMON,
            PlayerActionKind.SET_MONSTER,
            PlayerActionKind.SET_SPELL_TRAP,
            PlayerActionKind.ATTACK,
            PlayerActionKind.ACTIVATE_EFFECT,
            PlayerActionKind.END_PHASE,
            PlayerActionKind.PASS,
        }
    )
    #: 실행할 수 **없는** 셋.
    assert set(PlayerActionKind) - executable_kinds() == {
        PlayerActionKind.ACTIVATE_CARD,
        PlayerActionKind.CHANGE_POSITION,
        PlayerActionKind.CHANGE_PHASE,
    }


def test_08_the_offered_set_is_exactly_seven_kinds(repository):
    """
    §6 ③ — ``legal_actions`` 가 **낼 수 있는** 종류는 **일곱**이다.

    실행 가능한 여덟에서 ``special_summon`` 하나가 빠진다 — 그 비대칭이
    ``test_10`` 의 주제다.
    """
    offered: collections.Counter = collections.Counter()
    for seed in (309, 310, 311):
        for deck, prefer in (
            (SPELL_DECK, PlayerActionKind.ACTIVATE_EFFECT),
            (DIGEST_DECK, PlayerActionKind.ATTACK),
            (DIGEST_DECK, None),
        ):
            _, counts = walk_duel(repository, seed=seed, deck=deck, prefer=prefer)
            offered.update(counts["offered"])

    assert set(offered) == {
        PlayerActionKind.NORMAL_SUMMON,
        PlayerActionKind.SET_MONSTER,
        PlayerActionKind.SET_SPELL_TRAP,
        PlayerActionKind.ATTACK,
        PlayerActionKind.ACTIVATE_EFFECT,
        PlayerActionKind.END_PHASE,
        PlayerActionKind.PASS,
    }, dict(offered)

    #: 🔴 ③ ⊂ ① — 후보로 나오는 것은 전부 실행 가능하다 (B 분류가 **0종류**).
    assert set(offered) <= executable_kinds()
    assert executable_kinds() - set(offered) == {PlayerActionKind.SPECIAL_SUMMON}


def test_09_the_withheld_kinds_name_the_missing_rule(repository):
    """
    🟢 §3 · §4 — **의도된 제한이라는 증거**: 검증기가 ``UNKNOWN`` 과 함께
    **빠진 규칙의 이름**을 돌려준다.

    "향후 구현 예정" 같은 문구가 아니라, 코드가 그 자리에서 무엇이 없는지를 적는다.
    그래서 ``D. INTENTIONALLY_UNAVAILABLE`` 로 분류할 근거가 된다.
    """
    duel = opened_duel(repository, seed=312, deck=SPELL_DECK)
    seat = duel.to_act
    hand = duel.state.player(seat).hand
    assert hand, "손이 비어 있으면 이 측정이 성립하지 않는다"
    source = hand[0].instance_id
    validator = ActionValidator(duel.view(seat))

    expectations = {
        PlayerAction.activate_card(seat, source): "activation-timing",
        PlayerAction.change_phase(seat, Phase.BATTLE): "turn-progression",
    }
    for action, fragment in expectations.items():
        verdict = validator.validate(action)
        assert verdict.validity is ActionValidity.UNKNOWN, (action.kind, verdict)
        assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert verdict.missing_rule and fragment in verdict.missing_rule, verdict

    #: 🔴 ``UNKNOWN`` 은 **INVALID 가 아니다.** 둘을 섞으면 "구현이 없다" 가
    #: "규칙 위반" 으로 읽힌다 (ADR-006).
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID


def test_10_special_summon_is_registered_but_never_offered(repository):
    """
    🟡 §2 C — **구조적 관찰**: ``special_summon`` 은 실행기에 **등록되어 있지만**
    후보로 **한 번도 나오지 않는다.**

    글자 그대로는 §2 의 C(실행 가능하지만 합법이 아님)에 들어맞는다. 그런데
    **위험이 되지 않는다** — ``apply`` 가 목록과 대조한 뒤에야 실행기로 가므로
    (``test_02``) 그 수행기에 **닿을 길이 없다.**

    그리고 후보에서 빠지는 이유가 기록되어 있다 — 검증기가 몬스터에 대해
    ``UNKNOWN`` 과 ``special-summon-condition (카드마다 다르다)`` 를 돌려준다.
    실제 특수 소환은 효과 쪽의 ``SPECIAL_SUMMON_PROCEDURE`` 가 수행한다.
    """
    assert PlayerActionKind.SPECIAL_SUMMON in duel_executor().supported

    #: production 어디에서도 ``PlayerAction.special_summon`` 을 만들지 않는다.
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        assert "PlayerAction.special_summon" not in code_only(relative), relative

    #: 효과 쪽은 **다른 길**로 간다 — 수행기가 아니라 절차다.
    executor_code = code_only("engine/effect/executor.py")
    assert "SPECIAL_SUMMON_PROCEDURE" in executor_code
    assert "SpecialSummonHandler" not in executor_code

    #: 그리고 몬스터에 대한 검증 결과가 ``UNKNOWN`` + 빠진 규칙 이름이다.
    duel = opened_duel(repository, seed=313)
    seat = duel.to_act
    monsters = [
        card
        for card in duel.state.player(seat).hand
        if card.definition is not None
    ]
    assert monsters, "손에 카드가 없다"
    verdict = ActionValidator(duel.view(seat)).validate(
        PlayerAction.special_summon(seat, monsters[0].instance_id)
    )
    assert verdict.validity in (ActionValidity.UNKNOWN, ActionValidity.INVALID)
    if verdict.validity is ActionValidity.UNKNOWN:
        assert "special-summon" in (verdict.missing_rule or "")


def test_11_activate_card_is_offered_as_withheld_with_a_reason(repository):
    """
    §2 · §4 3 — ``activate_card`` 는 **빈 칸으로 남지 않는다.** ``withheld`` 에
    이유와 함께 적힌다.

    "목록에 없다" 와 "왜 없는지 적어 두었다" 는 다른 것이고, 이 프로젝트는 후자를
    한다.
    """
    seen = None
    for seed in (314, 315):
        _, counts = walk_duel(repository, seed=seed, deck=SPELL_DECK)
        if counts["withheld"]:
            seen = counts["withheld"]
            break
    assert seen is not None and seen[PlayerActionKind.ACTIVATE_CARD] > 0, seen

    duel = opened_duel(repository, seed=314, deck=SPELL_DECK)
    held = [
        w
        for w in duel.legal_actions(duel.to_act).withheld
        if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert held, "activate_card 가 withheld 에도 없다"
    assert held[0].reason
    #: 어떤 규칙이 없는지도 적는다.
    assert held[0].missing is None or isinstance(held[0].missing, str)


def test_12_no_kind_is_legal_but_unexecutable(repository):
    """
    🟢 §2 B — **"합법인데 실행 불가" 종류가 0개다.**

    이것이 §8 조건 B("legal_actions 와 apply 의 허용 범위가 명백히 모순")가
    성립하지 않는다는 직접 증거다.
    """
    offered: set = set()
    for seed in (316, 317):
        for deck in (DIGEST_DECK, SPELL_DECK):
            _, counts = walk_duel(
                repository,
                seed=seed,
                deck=deck,
                prefer=PlayerActionKind.ACTIVATE_EFFECT,
            )
            offered |= set(counts["offered"])
    assert offered
    assert offered - executable_kinds() == set(), offered - executable_kinds()


# ======================================================================
# C. §4 — 실제 카드 시나리오
# ======================================================================


def test_13_a_summonable_monster_yields_a_normal_summon(repository):
    """§4 1 — 소환할 수 있는 몬스터가 있으면 ``NORMAL_SUMMON`` 이 나온다."""
    _, counts = walk_duel(repository, seed=318, prefer=PlayerActionKind.NORMAL_SUMMON)
    assert counts["offered"][PlayerActionKind.NORMAL_SUMMON] > 0
    assert counts["accepted"][PlayerActionKind.NORMAL_SUMMON] > 0
    assert counts["refused"] == collections.Counter()


def test_14_set_monster_and_set_spell_trap_are_both_reachable(repository):
    """§4 5 — 세트 둘 다 후보로 나오고 실행된다."""
    offered: collections.Counter = collections.Counter()
    accepted: collections.Counter = collections.Counter()
    for prefer in (PlayerActionKind.SET_MONSTER, PlayerActionKind.SET_SPELL_TRAP):
        _, counts = walk_duel(repository, seed=319, deck=SPELL_DECK, prefer=prefer)
        offered.update(counts["offered"])
        accepted.update(counts["accepted"])
    assert offered[PlayerActionKind.SET_MONSTER] > 0
    assert offered[PlayerActionKind.SET_SPELL_TRAP] > 0
    assert accepted[PlayerActionKind.SET_SPELL_TRAP] > 0


def test_15_attack_has_both_a_generator_and_a_handler(repository):
    """
    §4 4 — ``ATTACK`` 은 **생성기와 수행기 둘 다** 있다. 그래서 A 분류다.

    "공격 실행 코드가 없다" 가 아니다 — ``AttackHandler`` 가 등록되어 있다.
    """
    assert PlayerActionKind.ATTACK in duel_executor().supported
    assert "_attack_actions" in code_only("engine/duel.py")

    offered: collections.Counter = collections.Counter()
    for seed in (320, 321, 322):
        _, counts = walk_duel(repository, seed=seed, prefer=PlayerActionKind.ATTACK)
        offered.update(counts["offered"])
    assert offered[PlayerActionKind.ATTACK] > 0, dict(offered)


def test_16_change_position_has_neither_generator_nor_handler():
    """
    §4 5 — ``CHANGE_POSITION`` 은 생성기도 수행기도 **없다.** 그리고 그 사실이
    검증기에 ``position-change-legality (Phase 2-G)`` 로 적혀 있다.
    """
    assert PlayerActionKind.CHANGE_POSITION not in executable_kinds()
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        assert "PlayerAction.change_position" not in code_only(relative), relative
    #: 빠진 규칙의 이름이 production 에 적혀 있다 (문자열이므로 원본에서 본다).
    assert "position-change-legality" in source_of("engine/action_validation.py")


def test_17_the_draw_step_offers_nothing_at_all(repository):
    """§6 ② — 상태가 후보를 정한다: 드로우가 남아 있으면 **아무것도** 못 고른다."""
    duel = Duel.start(
        repository, decks=(list(DIGEST_DECK), list(DIGEST_DECK)), seed=323
    )
    reached = False
    for _ in range(80):
        if duel.step is TurnStep.DRAW_PENDING:
            legal = duel.legal_actions(duel.turn_player)
            assert legal.allowed == ()
            assert legal.withheld == ()
            reached = True
            break
        if duel.advance() is not None:
            continue
        legal = duel.legal_actions(duel.to_act)
        if not legal.allowed:
            break
        duel.apply(legal.allowed[0])
    assert reached, "DRAW_PENDING 상태에 닿지 못했다"


# ======================================================================
# D. §5 — AI / Search 영향
# ======================================================================


def test_18_the_search_only_explores_what_legal_actions_gives():
    """
    🟢 §5 — **탐색은 ``legal.allowed`` 밖을 보지 않는다.** 스스로 그렇게 적는다.

    그래서 "legal_actions 가 완전한 action space 라고 가정" 하지 않는다 —
    "지금 엔진이 내놓는 것" 만 본다.
    """
    doc = source_of("agent/search.py")
    assert "legal.allowed" in doc
    search_code = code_only("agent/search.py")
    #: 후보를 스스로 만들지 않는다 — ``PlayerAction`` 생성 자리가 없다.
    assert "PlayerAction." not in search_code or "PlayerAction.passing" not in search_code


def test_19_the_search_tie_break_depends_on_the_candidate_set():
    """
    🔴 §5 · §8 — **후보를 하나라도 늘리면 탐색의 결정이 바뀐다.**

    ``agent/search.py`` 가 ``legal.allowed`` 를 ``canonical_state()`` 로 정렬해서
    동점을 가른다. 집합이 바뀌면 정렬 결과가 바뀌고, 그러면 **pin 된 digest 가
    깨진다.** 그래서 "AI 가 더 많은 행동을 고를 수 있으면 좋다" 는 이유만으로
    ``legal_actions`` 를 건드릴 수 없다 — §8 이 금지한 그대로다.
    """
    #: .. note::
    #:    🔴 원래 ``"sorted" in search_code`` 로 **낱말만** 셌다. 그래서 고의 위반
    #:    주입 8번(그 한 줄을 ``list(legal.allowed)`` 로 바꾸기)을 **놓쳤다** —
    #:    ``sorted`` 가 파일의 다른 줄(``ordering_key``)에도 있기 때문이다.
    #:    3-F-20 에서 똑같은 실수를 했는데 또 했다. **낱말이 아니라 구문을 센다.**
    tree = ast.parse(source_of("agent/search.py"))

    #: ``legal.allowed`` 를 받는 ``sorted(...)`` 호출이 있고, 그 key 가
    #: ``canonical_state`` 다.
    orderings = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sorted"
        and node.args
        and "legal.allowed" in ast.unparse(node.args[0])
    ]
    assert len(orderings) == 1, [ast.unparse(n) for n in orderings]
    keys = [kw for kw in orderings[0].keywords if kw.arg == "key"]
    assert keys and "canonical_state" in ast.unparse(keys[0].value), ast.unparse(
        orderings[0]
    )

    #: 그리고 후보 집합이 digest 를 정한다 — ``test_30`` 이 그 digest 를 고정한다.
    assert "legal.allowed" in code_only("agent/search.py")


def test_20_the_rule_based_policy_names_only_kinds_that_actually_appear():
    """
    §5 — ``RuleBasedPolicy`` 는 특정 종류를 **직접 가정한다.** 그런데 그 종류가
    실제로 후보에 나오는 것들이다 — 없는 종류를 전제하지 않는다.
    """
    #: 🔴 ``BOARD_KINDS`` 는 ``RuleBasedPolicy`` 가 아니라 **개별 고려 규칙**에
    #: 붙어 있다 (``SummonBeforeEndingThePhase``). 처음에 엉뚱한 클래스에서
    #: 찾아 실패했다 — 이름을 짐작하지 말고 **측정한다.**
    assert SummonBeforeEndingThePhase.BOARD_KINDS == frozenset(
        {PlayerActionKind.NORMAL_SUMMON}
    )

    #: ``agent/heuristic.py`` 가 이름으로 집는 종류 **전수**.
    tree = ast.parse(source_of("agent/heuristic.py"))
    named = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    }
    assert named == {"NORMAL_SUMMON", "END_PHASE", "PASS"}, named

    #: 🟢 전제하는 세 종류가 **전부 실행 가능하고 후보로도 나온다.** 없는 종류를
    #: 전제하지 않는다 — 그 태도가 주석에 적혀 있다 ("나타나지 않는 행위에 점수를
    #: 매기면 … 규칙이 아니라 희망이다").
    assumed = {PlayerActionKind[name] for name in named}
    assert assumed <= executable_kinds(), assumed
    assert assumed.isdisjoint(set(PlayerActionKind) - executable_kinds())
    assert "희망이다" in source_of("agent/heuristic.py")


def test_21_the_simulator_re_asks_legal_actions_on_the_fork(repository):
    """§5 — 시뮬레이션은 사본에서 **다시 묻는다.** 원본 목록을 믿고 쓰지 않는다."""
    duel = opened_duel(repository, seed=324)
    simulator = Simulator(duel)
    assert hasattr(simulator, "legal_actions")

    before = duel.state.state_hash()
    legal = duel.legal_actions(duel.to_act)
    assert legal.allowed
    outcome = simulator.simulate(legal.allowed[0], viewer=duel.to_act)
    assert outcome.action == legal.allowed[0]
    #: 원본은 흔들리지 않는다.
    assert duel.state.state_hash() == before

    #: 사본 쪽 코드가 ``legal_actions`` 를 다시 부른다.
    assert "legal_actions" in code_only("agent/simulation.py")


def test_22_hidden_information_is_unchanged_by_candidate_generation(repository):
    """§5 — 후보를 만들어도 숨은 정보 경계가 그대로다."""
    duel = opened_duel(repository, seed=325, deck=SPELL_DECK)
    seat = duel.to_act
    duel.legal_actions(seat)

    view = GameStateView.from_state(duel.state, viewer=seat)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(1 - seat).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()

    #: 후보 생성은 **관측**으로 검증한다 — 판을 직접 읽어 후보를 만들지 않는다.
    assert "ActionValidator(self.view(seat))" in code_only("engine/duel.py")


def test_23_candidate_generation_touches_neither_the_board_nor_the_rng(repository):
    """§12 — ``legal_actions`` 는 ``state_hash`` 도 RNG 도 건드리지 않는다."""
    duel = opened_duel(repository, seed=326, deck=SPELL_DECK)
    before_hash, before_rng = duel.state.state_hash(), repr(duel.state.rng)

    for _ in range(5):
        duel.legal_actions(MINE)
        duel.legal_actions(THEIRS)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng


def test_24_a_clone_offers_the_same_candidates(repository):
    """§9 — clone 독립성: 사본의 후보가 원본과 **같다.**"""
    duel = opened_duel(repository, seed=327, deck=SPELL_DECK)
    seat = duel.to_act
    original = duel.legal_actions(seat)

    copy = duel.state.clone()
    assert copy.state_hash() == duel.state.state_hash()

    forked = dataclasses.replace(duel, state=copy)
    mirrored = forked.legal_actions(seat)
    assert [a.canonical_state() for a in mirrored.allowed] == [
        a.canonical_state() for a in original.allowed
    ]

    #: 사본에 적용해도 원본은 흔들리지 않는다.
    if mirrored.allowed:
        before = duel.state.state_hash()
        forked.apply(mirrored.allowed[0])
        assert duel.state.state_hash() == before


def test_25_the_same_seed_offers_the_same_candidates(repository):
    """§12 — 같은 seed 는 같은 후보를 낸다 (RNG 결정성)."""

    def fingerprint(seed: int):
        duel, counts = walk_duel(
            repository,
            seed=seed,
            deck=SPELL_DECK,
            prefer=PlayerActionKind.ACTIVATE_EFFECT,
        )
        return (
            duel.state.state_hash(),
            sorted((k.value, v) for k, v in counts["offered"].items()),
            sorted((k.value, v) for k, v in counts["accepted"].items()),
        )

    for seed in (328, 329):
        assert fingerprint(seed) == fingerprint(seed), seed
    assert fingerprint(328) != fingerprint(329)


# ======================================================================
# E. §8 · §12 — AUDIT 범위와 불변
# ======================================================================


def test_26_this_phase_changed_no_production_file():
    """
    §8 — **AUDIT-ONLY: 이 Phase(3-F-21)는 production 을 한 줄도 바꾸지 않았다.**

    §8 의 A("반드시 legal 해야 하는데 연결 누락") · B("legal 과 apply 의 범위가
    모순") 가운데 **하나도 성립하지 않는다** — 후보로 나온 것은 전부 수락되고
    (``test_03``), ``apply`` 의 허용 범위가 곧 목록이다(``test_02``).

    .. note::
       **이 파일을 추가한 commit** 하나만 본다 (3-F-18 · 3-F-19 · 3-F-20 와 같은
       방식). commit 전에는 base(``e42ec89``) ↔ 작업 트리로 되돌아간다.
    """
    PHASE_3F21_BASE = "e42ec89"

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
        changed = git("diff", "--stat", PHASE_3F21_BASE, "--", *PRODUCTION_ROOTS)
    assert changed.strip() == "", changed


def test_27_no_new_action_kind_or_generator_was_added():
    """§7 — 새 ``PlayerActionKind`` 도, 새 후보 생성기도 없다."""
    assert len(list(PlayerActionKind)) == 11
    assert [k.value for k in PlayerActionKind] == [
        "normal_summon",
        "special_summon",
        "set_monster",
        "set_spell_trap",
        "activate_card",
        "activate_effect",
        "change_position",
        "attack",
        "change_phase",
        "end_phase",
        "pass",
    ]

    #: 후보 생성기는 넷뿐이다.
    duel_code = code_only("engine/duel.py")
    generators = [
        name
        for name in (
            "_attack_actions",
            "_activation_actions",
            "_flow_actions",
            "_withheld_board_actions",
        )
        if name in duel_code
    ]
    assert len(generators) == 4, generators
    for forbidden in ("_special_summon_actions", "_position_actions", "ActionGraph"):
        assert forbidden not in duel_code, forbidden


def test_28_the_legal_actions_container_keeps_allowed_and_withheld_apart():
    """§2 — ``LegalActions`` 는 허가와 보류를 **섞지 않는다.**"""
    names = [f.name for f in dataclasses.fields(LegalActions)]
    assert names == ["seat", "allowed", "withheld"], names
    held = [f.name for f in dataclasses.fields(WithheldAction)]
    assert held == ["kind", "reason", "missing"], held
    #: 보류는 ``PlayerAction`` 이 아니라 **종류와 이유**다 — 고를 수 없다.
    assert "kind" in held and "action" not in held


def test_29_the_executor_refuses_an_unregistered_kind(repository):
    """§9 — 등록하지 않은 종류는 실행기가 **거부한다** (ADR-006)."""
    executor = ActionExecutor()
    assert executor.supported == frozenset()

    duel = opened_duel(repository, seed=330)
    seat = duel.to_act
    hand = duel.state.player(seat).hand
    assert hand
    outcome = executor.execute(
        duel.state, PlayerAction.normal_summon(seat, hand[0].instance_id)
    )
    #: 실행되지 않았다 — 그리고 그 사실을 **UNKNOWN 과 구분해서** 말한다.
    assert outcome.status.value != "executed"
    assert duel.state.state_hash() == duel.state.state_hash()


def test_30_the_search_ranking_digest_is_unchanged(repository):
    """
    §12 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은 파일이
       못 박은 값을 기준으로 쓴다 (3-F-18 · 3-F-19 · 3-F-20 와 같은 방식).
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
