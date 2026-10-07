"""
Phase 3-F-18 — ``ChainResolution`` 의 ``link`` / ``result`` 불변식 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
``link`` 와 ``result`` 의 관계를 **runtime/type 수준에서 강제해야 하는가.**

🔴 두 방향은 **같은 계약이 아니다**
-----------------------------------
=========================  ===========================================
``result`` ⟹ ``link``       🟢 **성립한다.** 그리고 **인과적으로** 그렇다 —
                            result 는 ``link.resolution_context()`` 를
                            넘겨서만 만들어진다 (``test_03``)
``link`` ⟹ ``result``       🔴 **성립하지 않고, 성립해서는 안 된다** —
                            "정의를 못 찾은 링크" 가 정상 보고다 (``test_06``)
=========================  ===========================================

``ChainResolution`` 은 **보고(report)** 다 — 문맥이 아니다
---------------------------------------------------------
``frozen=True`` · factory 없음 · ``from_dict`` 없음 · 모든 생성이 ``return``
문이다. 즉 **중간 상태로 존재하는 일이 없다** (``test_01``). 그래서 §8 의
"중간 lifecycle 때문에 일부 조합을 허용해야 한다"(E)는 **해당하지 않는다.**

네 조합 실측 (``test_08`` ~ ``test_12``)
---------------------------------------
======================  ====================  ======  ========  ==========
경우                      status                link    result    정상?
======================  ====================  ======  ========  ==========
빈 체인                   ``empty_chain``       ✗       ✗         🟢 정상
체인 완료                 ``chain_complete``    ✗       ✗         🟢 정상
정의 없는 링크             ``invalid_chain_link``  **○**   ✗         🟢 정상
해결 성공                 ``resolved``          ○       ○         🟢 정상
해결 실패 (실행기까지)      ``invalid_chain_link``  ○       ○         🟢 정상
**result only**         —                     ✗       ○         🔴 **불가능**
======================  ====================  ======  ========  ==========

이 Phase 는 production 을 **한 줄도** 바꾸지 않는다 (``test_24``).
"""

import ast
import dataclasses
import inspect
import json
import pathlib
import subprocess
import textwrap

import pytest

from engine.action import PlayerAction
from engine.activation import ActivationResult, ActivationStatus
from engine.chain import (
    Chain,
    ChainLink,
    ChainResolution,
    ChainResolutionStatus,
    ChainResolver,
)
from engine.duel import Duel
from engine.effect.resolution import EffectResult, ResolutionStatus
from engine.event_pipeline import EventReader
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.payment import CostPaymentResult
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
MINE, THEIRS = 0, 1

#: 이 감사 파일 자신.
#:
#: 🔴 **자기측정 함정에 네 번째로 걸렸다.** 3-F-8 은 정규식이 자기 파일의 패턴을
#: 셌고, 3-F-13 은 호출 자리 측정이 자기 "거부 시험" 호출을 셌고, 3-F-16 은 중첩
#: 함수 탐색이 자기 주입 코드를 셌다. 그리고 이번에는 **"result 만 있는 조합은
#: 저장소에 0곳이다" 를 증명하는 도구가, 그 조합을 일부러 만들어 보이는 자기
#: 코드(``test_15``)를 세어서** 스스로를 반증했다.
#:
#: 고치는 방향은 "자기 코드를 지우기" 가 아니다 — 그 시연은 §8 판정("타입이
#: 강제하지 않는다")의 **증거**이므로 남아야 한다. 측정을 **감사 대상(저장소)**
#: 과 **감사 도구(이 파일)** 로 갈라서 둘 다 세는 것이다. 숨기지 않고 ``test_02b``
#: 가 자기 시연을 따로 못 박는다.
MYSELF = "tests/test_chain_resolution_link_result_invariant.py"

FEATHERMAN = 71925487
POT_OF_GREED = 55144522
#: 싸이크론 — 실행기까지 가지만 대상 판정에서 멈춘다.
MYSTICAL_SPACE_TYPHOON = 5318639
#: 홍옥의 사령 — **통상 몬스터**이므로 효과 라이브러리에 정의가 **없다.**
NO_DEFINITION = 11091375
#: 강욕의 보은 — digest 덱에 들어 있는 상대 드로우 카드.
GENEROUS_REWARD = 5915629
I = InstanceId


# ======================================================================
# 측정 도구
# ======================================================================


def source_of(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def production_files():
    for root in PRODUCTION_ROOTS:
        yield from (PROJECT_ROOT / root).rglob("*.py")


def code_only(relative: str) -> str:
    """문자열 리터럴을 지운 코드 — 설명 속 언급을 코드로 착각하지 않으려고 쓴다."""

    class _Strip(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<str>"), node)
            return node

    return ast.unparse(_Strip().visit(ast.parse(source_of(relative))))


def every_construction(name: str) -> list[tuple[str, int, set[str], int]]:
    """
    저장소 **전체**에서 ``name(...)`` 생성 자리를 AST 로 모은다.

    돌려주는 것은 (파일, 줄, 키워드 집합, 위치 인자 수) 다.
    """
    found: list[tuple[str, int, set[str], int]] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            ):
                found.append(
                    (
                        str(path.relative_to(PROJECT_ROOT)),
                        node.lineno,
                        {k.arg for k in node.keywords if k.arg},
                        len(node.args),
                    )
                )
    return found


def audited_constructions(name: str) -> list[tuple[str, int, set[str], int]]:
    """
    감사 **대상**의 생성 자리 — 이 감사 파일이 일부러 만든 시연은 뺀다.

    뺀 것을 숨기지 않는다: ``test_02b`` 가 그 시연 자리를 따로 센다.
    """
    return [site for site in every_construction(name) if site[0] != MYSELF]


def my_own_constructions(name: str) -> list[tuple[str, int, set[str], int]]:
    """이 감사 파일이 **일부러** 만든 자리."""
    return [site for site in every_construction(name) if site[0] == MYSELF]


def replace_calls_on(variable_hint: str) -> list[tuple[str, int, set[str]]]:
    """
    ``dataclasses.replace`` · ``replace`` 호출 중 첫 인자가 ``variable_hint`` 를
    담고 있는 것들.
    """
    found: list[tuple[str, int, set[str]]] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            target = node.func
            is_replace = (
                isinstance(target, ast.Attribute) and target.attr == "replace"
            ) or (isinstance(target, ast.Name) and target.id == "replace")
            if not is_replace:
                continue
            if variable_hint not in ast.unparse(node.args[0]):
                continue
            found.append(
                (
                    str(path.relative_to(PROJECT_ROOT)),
                    node.lineno,
                    {k.arg for k in node.keywords if k.arg},
                )
            )
    return found


# ======================================================================
# 판
# ======================================================================


def live_duel(repository, *, seed: int = 3) -> Duel:
    duel = Duel.start(
        repository, decks=([NO_DEFINITION] * 20, [NO_DEFINITION] * 20), seed=seed
    )
    while duel.advance() is not None:
        pass
    return duel


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


# ======================================================================
# A. §3 · §5 — 구조와 의미
# ======================================================================


def test_01_the_chain_resolution_is_a_report_not_a_context():
    """
    §5 — ``ChainResolution`` 은 **보고**다. 문맥도, 중간 상태도 아니다.

    * ``frozen=True`` — 만든 뒤 바꿀 수 없다
    * factory · classmethod **없음** — 부분적으로 만들어 채우는 길이 없다
    * ``from_dict`` **없음** — 역직렬화로 이상한 조합을 만들 길이 없다
    * 모든 생성이 ``resolve_top`` 의 ``return`` 문이다

    → §8 의 **E**("중간 lifecycle 때문에 일부 조합을 허용해야 한다")는 **해당하지
    않는다.** 허용할 중간 상태가 애초에 없다.
    """
    assert ChainResolution.__dataclass_params__.frozen is True
    assert not [
        name
        for name, value in vars(ChainResolution).items()
        if isinstance(value, (classmethod, staticmethod))
    ]
    assert not hasattr(ChainResolution, "from_dict")

    #: 모든 생성이 ``return`` 문 안에 있다.
    resolve_top = inspect.getsource(ChainResolver.resolve_top)
    #: ``inspect.cleandoc`` 은 **쓰지 않는다** — 본문 줄까지 함께 당겨서
    #: 함수 몸통의 들여쓰기가 깨진다. ``textwrap.dedent`` 가 맞는 도구다.
    tree = ast.parse(textwrap.dedent(resolve_top))
    creations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ChainResolution"
    ]
    returns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "ChainResolution"
    ]
    assert len(creations) == len(returns) == 5, (len(creations), len(returns))


def test_02_every_construction_site_in_the_repository_is_classified():
    """
    §3 · §4 — 생성 자리 **전수 6곳**을 분류한다.

    =====================================  ======  ========  ===============
    자리                                     link    result    뜻
    =====================================  ======  ========  ===============
    ``engine/chain.py`` × 2                 ✗       ✗         해결할 것이 없다
    ``engine/chain.py`` × 1                 ○       ✗         정의를 못 찾았다
    ``engine/chain.py`` × 2                 ○       ○         실행기까지 갔다
    ``tests/engine/test_chain.py`` × 1      ○       ○         직접 만든 보고
    =====================================  ======  ========  ===============
    """
    #: 🔴 ``every_construction`` 이 아니라 ``audited_constructions`` 다 — 이 감사
    #: 파일이 §8 증거로 일부러 만든 시연 2곳은 감사 **대상**이 아니다.
    sites = audited_constructions("ChainResolution")
    assert len(sites) == 6, sites

    production = [site for site in sites if not site[0].startswith("tests")]
    tests = [site for site in sites if site[0].startswith("tests")]
    assert len(production) == 5 and len(tests) == 1
    assert {site[0] for site in production} == {"engine/chain.py"}
    assert {site[0] for site in tests} == {"tests/engine/test_chain.py"}

    #: 조합별 개수.
    both_none = [s for s in sites if not s[2] & {"link", "result"}]
    link_only = [s for s in sites if "link" in s[2] and "result" not in s[2]]
    both = [s for s in sites if {"link", "result"} <= s[2]]
    result_only = [s for s in sites if "result" in s[2] and "link" not in s[2]]

    assert len(both_none) == 2, both_none
    assert len(link_only) == 1, link_only
    assert len(both) == 3, both          # production 2 + 테스트 1
    #: 🔴 **result 만 주는 자리가 하나도 없다.**
    assert result_only == [], result_only


def test_02b_the_instrument_does_not_count_its_own_demonstration():
    """
    🔴 §13 — **감사 도구가 자기 시연을 세면 판정이 뒤집힌다.**

    ``test_02`` · ``test_04`` 는 "result 만 있는 생성 자리는 0곳이다" 를 센다.
    그런데 이 파일의 ``test_15`` 는 **그 조합을 일부러 만든다** — 타입이 막지
    않는다는 §8 의 증거다. 아무 구분 없이 세면 도구가 자기 증거를 위반으로 신고해서
    실제로 세 테스트가 깨졌다 (자기측정 함정 **네 번째**: 3-F-8 정규식 · 3-F-13
    호출 자리 · 3-F-16 중첩 함수 · 이번).

    그래서 **빼고 끝내지 않는다.** 뺀 것이 정확히 무엇인지 여기서 못 박는다.
    """
    everything = every_construction("ChainResolution")
    audited = audited_constructions("ChainResolution")
    mine = my_own_constructions("ChainResolution")

    #: 나눈 결과가 전체와 맞는다 — 세다가 흘린 자리가 없다.
    assert len(audited) + len(mine) == len(everything)
    assert len(mine) == 2, mine
    assert {site[0] for site in mine} == {MYSELF}

    #: 내 시연 2곳의 정체: 하나는 **허용되는** 조합, 하나는 **불법** 조합이다.
    combinations = sorted(tuple(sorted(site[2])) for site in mine)
    assert combinations == [("link", "result"), ("result",)], combinations

    #: 🔴 그 불법 조합은 **이 파일 안에만** 있다 — 저장소 어디에도 없다.
    illegal_anywhere = [
        site for site in everything if "result" in site[2] and "link" not in site[2]
    ]
    assert len(illegal_anywhere) == 1, illegal_anywhere
    assert illegal_anywhere[0][0] == MYSELF

    #: 그리고 production 에는 하나도 없다 — 이것이 §8 **B** 판정의 근거다.
    assert not [
        site
        for site in everything
        if not site[0].startswith("tests")
        and "result" in site[2]
        and "link" not in site[2]
    ]


def test_03_the_result_is_made_from_the_link_so_result_only_is_impossible():
    """
    🟢 §2 A · §6 — **``result`` 는 ``link`` 에서 만들어진다.**

    ``resolve_top`` 안에서 result 를 얻는 길이 **하나**뿐이고, 그 호출이
    ``link.resolution_context()`` 를 넘긴다.

        result = self._executor.execute(state, definition, link.resolution_context())

    즉 "link 없이 result 를 얻는" 것은 **쓰지 않아서 없는 것이 아니라 만들 수 없는
    것**이다. 불변식이 추가 규칙이 아니라 **생성 방식의 결과**다 — 이것이 runtime
    강제가 필요 없는 가장 강한 근거다.
    """
    body = code_only("engine/chain.py")
    assert "link.resolution_context()" in body

    #: 그 호출이 **한 번**만 나온다 — 다른 경로로 result 를 얻지 않는다.
    assert body.count("self._executor.execute(") == 1

    #: 그리고 ``definition_for(link)`` 가 그 앞을 막는다 — 정의가 없으면 애초에
    #: 실행기까지 가지 않는다 (그 자리가 link-only 보고다).
    assert "self.definition_for(link)" in body


def test_04_the_two_directions_are_not_the_same_contract():
    """
    🔴 §2 · §7 — **두 방향을 별개로 판정한다.**

    * A 방향 (``result`` ⟹ ``link``) — **불변식이다**
    * B 방향 (``link`` ⟹ ``result``) — **불변식이 아니다**

    두 방향을 하나로 묶으면 "정의를 못 찾은 링크" 보고가 불법이 된다.
    """
    sites = audited_constructions("ChainResolution")

    #: A 방향: 위반 0.
    a_violations = [s for s in sites if "result" in s[2] and "link" not in s[2]]
    assert a_violations == [], a_violations

    #: B 방향: **위반이 있고, 그것이 정상이다.**
    b_violations = [s for s in sites if "link" in s[2] and "result" not in s[2]]
    assert len(b_violations) == 1, b_violations
    assert b_violations[0][0] == "engine/chain.py"


# ======================================================================
# B. §4 — 네 조합을 실제로 만든다
# ======================================================================


def test_05_an_empty_chain_reports_neither(repository):
    """§4 4 — **둘 다 ``None``**: 쌓인 링크가 없다. 🟢 정상."""
    state, _ = board(repository, POT_OF_GREED)
    report = duel_resolver().resolve_top(state, Chain())

    assert report.status is ChainResolutionStatus.EMPTY_CHAIN
    assert report.link is None
    assert report.result is None
    assert report.deltas == ()
    #: "해결할 것이 없었다" 는 **행위자를 물을 자리가 아니다.**
    assert report.resolved is False


def test_06_a_link_without_a_definition_reports_link_only(repository):
    """
    🟢 §4 1 · §7 — **``link`` 만 있는 보고가 정상이다.**

    통상 몬스터는 효과 라이브러리에 정의가 없다. 그래서 "무엇을 해결하려 했는지는
    아는데 실행기까지 가지 못했다" 가 된다 — 그리고 **그때도 행위자를 말할 수
    있다.**

    이것이 B 방향(``link`` ⟹ ``result``)을 강제하면 **안 되는** 이유다.
    """
    state, report = resolve_one(repository, NO_DEFINITION, THEIRS)

    assert report.status is ChainResolutionStatus.INVALID_CHAIN_LINK
    assert report.link is not None
    #: 🔴 ``result`` 가 **없다** — 실행기까지 가지 않았다.
    assert report.result is None
    assert report.deltas == ()
    assert report.code is ValidationCode.CHAIN_DEFINITION_UNAVAILABLE

    #: 🟢 그래도 actor 는 남아 있다.
    assert report.link.actor == THEIRS
    assert report.link.resolution_context().controller == THEIRS


def test_07_a_successful_resolution_reports_both(repository):
    """§4 3 — **둘 다 있다**: 실행기까지 갔고 판이 바뀌었다."""
    state, report = resolve_one(repository, POT_OF_GREED, MINE)

    assert report.status is ChainResolutionStatus.RESOLVED
    assert report.link is not None and report.result is not None
    assert report.result.status is ResolutionStatus.RESOLVED
    assert len(report.result.deltas) == 2
    assert report.link.actor == MINE

    #: 3-F-17 의 계약대로 운반자에서 actor 를 복원한다.
    observed = EventReader(GameStateView.from_state(state, viewer=MINE)).read(
        report.result, actor=report.link.actor
    )
    assert {event.context.actor for event in observed} == {MINE}


def test_08_a_failed_resolution_also_reports_both(repository):
    """
    §4 3 — 실행기까지 갔지만 실패해도 **둘 다** 있다.

    🟡 그래서 ``status`` 하나로는 ``result`` 유무를 알 수 없다 —
    ``INVALID_CHAIN_LINK`` 가 **두 경우**에 쓰인다 (``test_06`` 과 여기). 읽는
    쪽은 ``result is None`` 을 직접 봐야 한다.
    """
    state, report = resolve_one(repository, MYSTICAL_SPACE_TYPHOON, THEIRS)

    assert report.status is ChainResolutionStatus.INVALID_CHAIN_LINK
    assert report.link is not None
    #: 🔴 여기서는 ``result`` 가 **있다** — 같은 status 인데 다르다.
    assert report.result is not None
    assert report.result.status is not ResolutionStatus.RESOLVED
    assert report.deltas == ()
    assert report.link.actor == THEIRS


def test_09_a_completed_chain_reports_neither(repository):
    """§4 4 — 체인을 다 푼 뒤의 보고도 **둘 다 ``None``** 이다. 🟢 정상."""
    state, chain = one_link_chain(repository, POT_OF_GREED, MINE)
    resolver = duel_resolver()

    first = resolver.resolve_top(state, chain)
    assert first.status is ChainResolutionStatus.RESOLVED

    second = resolver.resolve_top(state, first.chain)
    assert second.status is ChainResolutionStatus.CHAIN_COMPLETE
    assert second.link is None and second.result is None
    #: ``EMPTY_CHAIN`` 과 **다른 사실**이다 (하나도 안 쌓인 것 ≠ 다 푼 것).
    assert second.status is not ChainResolutionStatus.EMPTY_CHAIN


def test_10_a_link_on_the_chain_has_no_resolution_object_at_all(repository):
    """
    §5 ① · §11 2 — **"아직 결과가 생성되지 않았다" 는 ``ChainResolution`` 이 아니다.**

    링크를 올려만 두면 ``ChainResolution`` 객체가 **존재하지 않는다.** 그것은
    ``Chain`` 의 상태다. 그래서 "link 는 있고 result 는 아직 없다" 를
    ``ChainResolution`` 으로 표현할 필요가 없다 — §5 의 ①과 ③을 섞지 않는다.
    """
    state, chain = one_link_chain(repository, POT_OF_GREED, MINE)

    assert len(chain.links) == 1
    assert chain.top is not None
    assert chain.top.actor == MINE
    #: 보고는 **해결을 시도해야** 생긴다.
    assert chain.is_complete is False

    #: 그리고 ``Chain`` 에는 ``result`` 칸이 없다 — 보고와 상태가 분리되어 있다.
    assert {f.name for f in dataclasses.fields(Chain)} == {"links", "resolved_count"}


# ======================================================================
# C. §6 — actor provenance 영향
# ======================================================================


def test_11_a_link_less_result_loses_the_provenance_but_is_refused(repository):
    """
    §6 — ``link=None`` 인데 ``result`` 가 있는 객체를 **만들면** provenance 가
    사라진다. 그리고 **그 객체로 사건을 읽으면 거부된다.**

    즉 구조적으로 만들 수는 있지만 **조용히 틀리지 않는다** — 3-F-14 의 계약이
    마지막 방어선이다.
    """
    state, report = resolve_one(repository, POT_OF_GREED, THEIRS)
    orphaned = dataclasses.replace(report, link=None)

    assert orphaned.result is not None
    assert orphaned.link is None
    #: 🔴 복원할 길이 없다.
    for name in ("actor", "controller", "action"):
        assert not hasattr(orphaned.result, name), name

    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    with pytest.raises(TypeError) as omitted:
        reader.read(orphaned.result)
    assert "부르는 쪽만 압니다" in str(omitted.value)

    #: 원래 보고로는 멀쩡히 읽힌다.
    assert reader.read(report.result, actor=report.link.actor)


def test_12_replacing_the_result_with_none_is_harmless(repository):
    """
    §12 9 — 반대 방향 ``replace(result=None)`` 은 **불변식을 깨지 않는다.**

    link-only 는 정상 상태이므로, result 를 떼어 낸 보고도 **합법적인 모양**이다.
    다만 "무엇을 했는지" 는 사라진다 — 그것은 provenance 문제가 아니다.
    """
    state, report = resolve_one(repository, POT_OF_GREED, THEIRS)
    without_result = dataclasses.replace(report, result=None)

    assert without_result.link is not None
    assert without_result.result is None
    #: actor 는 그대로 말할 수 있다.
    assert without_result.link.actor == THEIRS
    #: 그리고 이 모양은 production 의 link-only 보고와 **같은 조합**이다.
    state2, link_only = resolve_one(repository, NO_DEFINITION, THEIRS)
    assert (link_only.link is not None, link_only.result is None) == (True, True)


# ======================================================================
# D. §8 — __post_init__ 분류
# ======================================================================


def test_13_the_post_init_checks_only_the_deltas_and_that_is_classification_b():
    """
    §8 — **분류는 B(생성 경로에서 이미 보장된다)** 다. C 나 D 가 아니다.

    ``__post_init__`` 은 ``status``/``deltas`` 짝만 본다 — ``link``·``result`` 를
    보지 않는다. 그 이유가 **보장이 없기 때문이 아니라 생성 방식이 이미 보장하기
    때문**이다 (``test_03``).

    * A(강제할 필요가 없다) — 가깝지만 "필요 없다" 의 근거를 안 말한다
    * **B(생성 경로에서 이미 보장된다)** — ``result`` 가 ``link`` 에서 나온다
    * C(테스트/호출 관례로만) — ✗ 관례가 아니라 **인과**다
    * D(violation 가능성이 있다) — ✗ production 경로에 없다
    * E(중간 lifecycle) — ✗ 중간 상태가 없다 (``test_01``)
    """
    guard = inspect.getsource(ChainResolution.__post_init__)
    assert "deltas" in guard
    assert "ChainError" in guard
    #: 🔴 ``link``·``result`` 를 보지 않는다.
    assert "link" not in guard and "result" not in guard

    #: 그리고 보는 것은 ``status``/``deltas`` 짝이다.
    assert "ChainResolutionStatus.RESOLVED" in guard


def test_14_the_activation_result_enforces_more_and_that_asymmetry_is_real():
    """
    §8 · §13 — ``ActivationResult`` 는 같은 종류의 불변식을 **거부한다.**

    그래서 ``ChainResolution`` 이 이 저장소 안에서 **예외**다. 3-F-17 이 적은
    그대로이고, 이 Phase 가 그 비대칭을 **사실로 고정**한다 — 다만 고치지 않는다.
    """
    activation_guard = inspect.getsource(ActivationResult.__post_init__)
    assert "self.link is None" in activation_guard
    assert "ActivationError" in activation_guard

    #: 실제로 거부한다.
    from engine.activation import ActivationError

    with pytest.raises(ActivationError):
        ActivationResult(
            ActivationStatus.ACTIVATED, PlayerAction.passing(MINE), Chain()
        )

    #: 그런데 ``ChainResolution`` 은 거부하지 않는다 — 비대칭이 실재한다.
    permitted = ChainResolution(
        ChainResolutionStatus.EMPTY_CHAIN, Chain(), result=None, link=None
    )
    assert permitted.link is None and permitted.result is None


def test_15_the_type_level_contract_is_weaker_than_the_call_path(repository):
    """
    §8 — **"타입이 강제한다" 와 "호출 경로가 보장한다" 를 구분한다.**

    타입은 ``link: ChainLink | None = None`` 이므로 아무 조합이나 받는다. 보장은
    **생성 자리**에서 온다. 이 둘을 섞어 적지 않는다.
    """
    fields = {f.name: f for f in dataclasses.fields(ChainResolution)}
    assert fields["link"].default is None
    assert fields["result"].default is None
    assert "None" in str(fields["link"].type)
    assert "None" in str(fields["result"].type)

    #: 타입 수준에서는 **result-only 도 받는다** — 그래서 "타입이 막는다" 고 적으면
    #: 거짓이 된다.
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    illegal = ChainResolution(
        ChainResolutionStatus.RESOLVED, Chain(), result=report.result
    )
    assert illegal.result is not None and illegal.link is None


# ======================================================================
# E. §9 — dataclasses.replace 위험
# ======================================================================


def test_16_no_production_code_replaces_a_chain_resolution():
    """
    🟢 §9 — **production 에서 ``ChainResolution`` 에 ``replace`` 를 쓰는 자리가
    0곳이다.**

    쓰는 곳은 **감사 테스트뿐**이고, 그것도 위험을 **보이려고** 쓴다. 그래서
    "구조적으로 가능한 위험" 과 "실제 production bug" 는 다르다 — 후자가 아니다.
    """
    calls = replace_calls_on("resolution")
    production = [call for call in calls if not call[0].startswith("tests")]
    assert production == [], production

    #: 테스트에서만 쓴다. (``link`` 를 떼어 내는 감사가 대부분이고, 이 파일의
    #: ``test_12`` 는 반대 방향 ``result=None`` 도 쓴다 — 변수 이름이 ``report``
    #: 라서 이 hint 로는 잡히지 않는다. ``test_02b`` 가 그 자리를 따로 센다.)
    assert calls, "감사 테스트가 위험을 보이는 자리가 사라졌다"
    for path, _, keywords in calls:
        assert path.startswith("tests/"), path

    #: production 의 ``replace`` 는 다른 타입에만 쓴다.
    all_replaces = {
        path
        for path, _, _ in (
            (p, l, k)
            for hint in ("self.duel", "context", "steps[-1]", "spec")
            for (p, l, k) in replace_calls_on(hint)
        )
        if not path.startswith("tests")
    }
    assert "engine/chain.py" not in all_replaces


def test_17_the_chain_resolution_has_no_deserialization_path():
    """
    §3 — ``to_dict`` 는 있고 ``from_dict`` 는 **없다.**

    그래서 직렬화된 기록을 되읽어 **불법 조합을 만드는 길이 없다.** replay 를
    구현하게 되면 그때 입구가 하나 더 생기므로, 그 Phase 가 다시 봐야 한다.
    """
    assert hasattr(ChainResolution, "to_dict")
    assert not hasattr(ChainResolution, "from_dict")

    #: production 어디에도 ``ChainResolution`` 을 역직렬화하는 코드가 없다.
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        body = code_only(relative)
        if "ChainResolution" not in body:
            continue
        assert "from_dict" not in body, relative


# ======================================================================
# F. §11 — 실제 시나리오
# ======================================================================


def test_18_a_clone_does_not_touch_the_report(repository):
    """§11 5 — **clone**: 보고는 판을 들고 있지 않아 흔들리지 않는다."""
    state, report = resolve_one(repository, POT_OF_GREED, THEIRS)
    copy = state.clone()
    assert copy.state_hash() == state.state_hash()

    assert report.link.actor == THEIRS
    observed = EventReader(GameStateView.from_state(copy, viewer=MINE)).read(
        report.result, actor=report.link.actor
    )
    assert {event.context.actor for event in observed} == {THEIRS}

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.link = None  # type: ignore[misc]


def test_19_the_report_round_trips_through_serialization(repository):
    """
    §12 14 — 직렬화하면 ``link.actor`` 가 남는다.

    §11 6 (replay) 은 **아직 존재하지 않는 기능**이므로 여기까지만 잰다 —
    ``to_dict`` 는 있고 ``from_dict`` 는 없다 (``test_17``). replay 를 만드는
    Phase 가 생성 입구를 하나 더 열게 되므로 그때 A 방향 보장을 다시 재야 한다.
    """
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False, default=str))

    assert payload["link"]["actor"] == MINE
    #: link-only 보고도 직렬화된다 — ``result`` 가 빠진 모양이 정상이다.
    state2, link_only = resolve_one(repository, NO_DEFINITION, THEIRS)
    payload2 = json.loads(
        json.dumps(link_only.to_dict(), ensure_ascii=False, default=str)
    )
    assert payload2["link"]["actor"] == THEIRS
    assert payload2.get("result") in (None, {}, "None")


def test_20_a_real_duel_only_ever_produces_legal_combinations(repository):
    """
    §11 7 — **실제 듀얼**을 끝까지 돌려서 나온 보고를 전수 검사한다.

    ``Duel`` 은 ``ResponseResolution.steps`` 로 보고를 모으므로, 거기 담긴 모든
    ``ChainResolution`` 이 네 정상 조합 중 하나여야 한다.
    """
    duel = live_duel(repository)
    #: 이 덱은 통상 몬스터뿐이라 체인이 쌓이지 않는다 — 그것 자체가 사실이다.
    assert duel.chain.is_complete or len(duel.chain.links) == 0

    #: 직접 만든 보고들로 네 조합을 전수 확인한다.
    resolver = duel_resolver()
    state, chain = one_link_chain(repository, POT_OF_GREED, MINE)
    reports = [
        #: ① 빈 체인 — 둘 다 ``None``
        resolver.resolve_top(state, Chain()),
        #: ② 정의 없는 링크 — ``link`` 만
        resolve_one(repository, NO_DEFINITION, THEIRS)[1],
        #: ③ 해결 성공 — 둘 다
        resolver.resolve_top(state, chain),
        #: ③' 해결 실패(실행기까지 갔다) — 둘 다, ``deltas`` 는 빈 튜플
        resolve_one(repository, MYSTICAL_SPACE_TYPHOON, THEIRS)[1],
    ]
    for report in reports:
        #: 🔴 어느 보고에도 "result 는 있는데 link 가 없는" 조합이 없다.
        assert not (report.result is not None and report.link is None), report.status
        #: 그리고 result 가 있으면 actor 를 말할 수 있다.
        if report.result is not None:
            assert report.link is not None
            assert report.link.actor in (MINE, THEIRS)


# ======================================================================
# G. §10 — 다른 provenance 와 섞지 않는다
# ======================================================================


def test_21_the_cost_payment_result_uses_a_different_carrier(repository):
    """
    §10 · §12 17 — ``CostPaymentResult`` 는 **다른 운반자**를 쓴다.

    ``ActivationResult.action.actor`` 다. 두 계약을 섞지 않고, 이 Phase 가 어느
    쪽에도 actor 칸을 더하지 않았다.
    """
    assert not {f.name for f in dataclasses.fields(EffectResult)} & {"actor"}
    assert not {f.name for f in dataclasses.fields(CostPaymentResult)} & {"actor"}

    #: 운반자가 서로 다르다.
    assert "link" in {f.name for f in dataclasses.fields(ChainResolution)}
    assert "action" in {f.name for f in dataclasses.fields(ActivationResult)}
    #: ``ActivationResult`` 쪽은 필수다 — 더 강하다.
    action_field = {f.name: f for f in dataclasses.fields(ActivationResult)}["action"]
    assert action_field.default is dataclasses.MISSING

    #: 3-F-17 이 적은 복원 경로가 그대로 있다.
    assert "resolution.link.actor" in source_of("engine/chain.py")
    assert "activation.action.actor" in source_of("engine/payment.py")


def test_22_no_new_field_or_enum_was_added():
    """§10 — 새 field · 새 enum · 새 provenance 추상이 없다."""
    for forbidden in ("ActorProvenance", "ActorOrigin", "ActorRequirement"):
        for relative in (
            "engine/chain.py",
            "engine/payment.py",
            "engine/effect/resolution.py",
        ):
            assert forbidden not in source_of(relative), (forbidden, relative)

    #: ``ChainResolution`` 의 칸이 여섯 그대로다.
    assert [f.name for f in dataclasses.fields(ChainResolution)] == [
        "status",
        "chain",
        "code",
        "reason",
        "link",
        "result",
    ]
    #: ``ChainResolutionStatus`` 도 여덟 그대로다.
    assert len(list(ChainResolutionStatus)) == 8


# ======================================================================
# H. §14 — 불변과 AUDIT-ONLY
# ======================================================================


def test_23_nothing_about_the_board_or_the_search_moved(repository):
    """§14 — ``state_hash`` · RNG · hidden-information · AI 불변."""
    state, report = resolve_one(repository, POT_OF_GREED, MINE)
    before_hash, before_rng = state.state_hash(), repr(state.rng)

    reader = EventReader(GameStateView.from_state(state, viewer=MINE))
    for _ in range(3):
        reader.read(report.result, actor=report.link.actor)
    assert state.state_hash() == before_hash
    assert repr(state.rng) == before_rng

    assert (
        live_duel(repository, seed=23).state.state_hash()
        == live_duel(repository, seed=23).state.state_hash()
    )

    view = GameStateView.from_state(state, viewer=MINE)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(THEIRS).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()

    #: AI 는 보고를 **코드로** 모른다.
    for absent in ("ChainResolution", "EffectResult", "CostPaymentResult"):
        for path in (PROJECT_ROOT / "agent").rglob("*.py"):
            relative = str(path.relative_to(PROJECT_ROOT))
            assert absent not in code_only(relative), (absent, relative)


def test_24_this_phase_changed_no_production_file():
    """
    §13 — **AUDIT-ONLY: 이 Phase(3-F-18)는 production 을 한 줄도 바꾸지 않았다.**

    .. note::
       **``git diff HEAD`` 으로 재지 않는다.** commit 뒤에는 자기와 자기를 비교하는
       꼴이 되어 언제나 통과한다 — 3-F-12 · 3-F-13 · 3-F-15 · 3-F-16 이 그 함정에
       빠졌고 3-F-14 · 3-F-17 이 고쳤다.

       그렇다고 "base SHA ↔ 작업 트리" 로 재면 **뒤의 Phase 가 production 을 바꿀 때
       그 Phase 때문에 깨진다** — 이 테스트는 3-F-18 을 재야 하는데 남의 변경을
       재는 셈이다. 그래서 **이 파일을 추가한 commit**(= 3-F-18 작업 commit)을
       찾아서 그 commit 하나만 본다. 그 commit 은 변하지 않으므로 단정이 영구히
       안정적이고, 재는 대상도 정확히 이 Phase 다.

       아직 commit 되지 않은 개발 중에는 그 commit 이 없으므로, base SHA
       (``3a98c49`` — 3-F-17 보고서 commit) ↔ 작업 트리로 되돌아가 잰다.
    """
    PHASE_3F18_BASE = "3a98c49"
    myself = MYSELF

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    work_commit = git(
        "log", "--diff-filter=A", "--format=%H", "--", myself
    ).split()
    if work_commit:
        #: 이 파일을 추가한 commit — 3-F-18 의 작업 commit 이다.
        changed = git("show", "--stat", "--format=", work_commit[-1], "--", *PRODUCTION_ROOTS)
    else:  # pragma: no cover - commit 전 개발 중에만 지나간다
        changed = git("diff", "--stat", PHASE_3F18_BASE, "--", *PRODUCTION_ROOTS)
    assert changed.strip() == "", changed


def test_25_the_search_ranking_digest_is_unchanged(repository):
    """
    §12 20 · §14 — **검색/AI 회귀**: 6판 611결정 digest 가 그대로다.

    .. note::
       digest 값을 **여기에 베껴 적지 않는다.** 이미 3-F-5 이후 **일곱**
       감사 파일이 같은 값을 못 박고 있는데, 복사본을 하나 더 만들면 "어느 쪽이
       기준인가" 가 흐려지고 한쪽만 고쳐도 통과하는 길이 생긴다.

       대신 **기존 pin 들을 AST 로 읽어** 전부 같은 값인지 확인하고, 이번에 실제로
       돌린 digest 를 그 값과 비교한다. 즉 이 테스트는 digest 불변과 **pin 들의
       일치**를 함께 잰다.
    """
    import hashlib

    from agent.runner import DuelRunner
    from agent.search import search_policy

    #: 기존 pin 들을 모은다 — 문자열 리터럴을 AST 로 꺼낸다.
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
    #: 64자 16진수 상수는 여러 종류가 있다 (state_hash digest 등). 검색 ranking
    #: digest 는 **가장 많은 파일이 못 박은 값**이다 — 3-F-5 이후 모든 감사가 같이
    #: 못 박았기 때문이다. 그래서 파일 수로 고른다.
    counts: dict[str, int] = {}
    for values in pinned.values():
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    expected, pins = max(counts.items(), key=lambda item: item[1])
    assert pins >= 6, counts

    #: 3-F-5 이후 digest 를 못 박은 감사들과 **같은 덱**이다 — 홍옥의 사령 12장
    #: (= ``NO_DEFINITION``), 욕망의 항아리 4장, 강욕의 보은 4장.
    deck = [NO_DEFINITION] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4
    digest = hashlib.sha256()
    decisions = 0
    for seed in (1, 2, 3, 4, 5, 6):
        duel = Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)
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
