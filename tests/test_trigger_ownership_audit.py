"""
Phase 3-E-21 — 유발 효과의 발동은 ``PlayerAction`` 인가 (감사).

이 Phase 는 production 코드를 바꾸지 않았다. 감사 테스트만 더했다.

공식 규칙이 먼저 답한다
-----------------------
* **RULE-EFFECT-004** — "These effects are **activated** at specific times."
  유발 효과는 **발동되는** 것이다. 지속 효과(`RULE-EFFECT-001`)가
  ``has_activation: false`` 인 것과 대비된다.
* **RULE-CHAIN-010** — "the turn player **builds the Chain** starting with their
  mandatory effects, **in any order** … Afterwards, the turn player adds their
  **optional** effects in any order."
  → 체인에 올리는 주체는 **그 효과의 주인**이고, 같은 묶음 안의 순서는
  **그 사람이 고른다.** 강제 유발이라도 둘 이상이면 **선택이 남는다.**
* **RULE-CHAIN-011** — 발동이 아닌 행위(소환 · 릴리스 · 표시 형식 변경 ·
  비용 지불)에는 체인으로 응답할 수 없다. 즉 체인은 **발동**의 사슬이다.

그래서 판정은 하나로 모인다
---------------------------
유발 효과가 체인에 올라가는 사건은 공식 용어로 **발동(activation)** 이고,
이 엔진에서 발동의 입구는 이미 하나다 — ``PlayerActionKind.ACTIVATE_EFFECT``
와 ``EffectActivator.activate(…, action: PlayerAction, …)``.

**새 ActionKind 도, SystemAction 도 지금은 필요하지 않다.**

* 임의 유발(`OPTIONAL`)의 "발동한다" → 기존 ``ACTIVATE_EFFECT``.
* 임의 유발의 "발동하지 않는다" → 기존 ``PASS`` ("아무것도 하지 않겠다는 선택").
* 강제 유발이 **하나**일 때 → 고르는 일이 아니다. 엔진에는 이미 그런 일을
  처리하는 자리가 있다 — ``Duel.advance()`` ("고르지 않아도 일어나는 일",
  지금은 드로우 페이즈의 드로우).
* 강제 유발이 **둘 이상**일 때 → 순서가 선택이므로 다시 행위 공간으로 돌아온다
  (RULE-CHAIN-010). 그 공백은 이미
  ``engine/trigger_order.py`` 의 ``UNRESOLVED_ORDER_RULES`` 에 적혀 있다.

이 Phase 가 **하지 않은** 것: 그 연결을 만들지 않았다. 지금 이으면 등록된
유발 효과가 0개인 경로가 된다 (Phase 3-E-20 §16).
"""

import ast
import json
import pathlib
import re

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.activation import EffectActivator
from engine.duel import Duel, TurnStep
from engine.trigger import TriggerCandidate, TriggerRequirement
from engine.trigger_order import UNRESOLVED_ORDER_RULES
from engine.vocabulary import Phase

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
RULEBOOK_DOC = PROJECT_ROOT / "data/rules/documents/sd-rulebook-en-v10.json"
RULEBOOK_STRUCTURED = PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json"

POT_OF_GREED = 55144522
FEATHERMAN = 21844576


def rule_text(rule_id: str) -> str:
    data = json.loads(RULEBOOK_DOC.read_text(encoding="utf-8"))
    for section in data["sections"]:
        if section["rule_id"] == rule_id:
            return section["text"]
    raise AssertionError(f"{rule_id} 가 공식 문서에 없습니다")


def structured() -> dict:
    return json.loads(RULEBOOK_STRUCTURED.read_text(encoding="utf-8"))


def small_duel(repository, *, seed: int = 5) -> Duel:
    deck = [POT_OF_GREED] * 8 + [FEATHERMAN] * 8
    return Duel.start(repository, decks=(list(deck), list(deck)), seed=seed)


def at_main1(duel: Duel) -> Duel:
    while duel.state.turn.phase is not Phase.MAIN1:
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))
        duel.advance()
    return duel


# ======================================================================
# §2 — 공식 규칙 근거
# ======================================================================


def test_01_the_rulebook_says_a_trigger_effect_is_activated():
    """
    **§2-1 — 유발 효과는 "발동된다".** 지속 효과와 대비해서 확인한다.

    이 한 문장이 이 Phase 의 출발점이다 — 유발을 체인에 올리는 사건이
    **발동**이라면, 이 엔진에서 그것을 받는 입구는 이미 정해져 있다.
    """
    assert "activated at speci" in rule_text("RULE-EFFECT-004").replace("ﬁ", "fi")

    by_name = {entry["name"]: entry for entry in structured()["effect_types"]}
    assert by_name["Trigger Effect"]["has_activation"] is True
    assert by_name["Flip Effect"]["has_activation"] is True
    #: 발동이 **없는** 것과 분명히 갈린다.
    assert by_name["Continuous Effect"]["has_activation"] is False
    assert "no trigger for its activation" in by_name["Continuous Effect"]["notes"]

    #: 스펠 스피드 1 이므로 응답으로는 발동할 수 없다 (RULE-CHAIN-004).
    assert by_name["Trigger Effect"]["spell_speed"] == 1
    assert "RULE-CHAIN-004" in by_name["Trigger Effect"]["rules"]


def test_02_the_rulebook_puts_the_chain_building_in_the_controllers_hands():
    """
    **§2-7 · §6 — 강제 유발이라도 "in any order" 는 그 사람이 고른다.**

    ``RULE-CHAIN-010`` 이 네 묶음의 순서를 정하고, **묶음 안에서는 임의**라고
    말한다. 그러므로 "강제니까 엔진이 알아서" 가 아니다 — 둘 이상이면 순서가
    선택이다.
    """
    text = rule_text("RULE-CHAIN-010")
    assert "builds the Chain" in text
    assert "mandatory" in text and "optional" in text
    assert text.count("in any order") >= 3

    chain = structured()["chain"]
    assert chain["simultaneous_order"] == [
        "turn player's mandatory effects, in any order",
        "opponent's mandatory effects, in any order",
        "turn player's optional effects, in any order",
        "opponent's optional effects, in any order",
    ]
    #: 체인은 **발동**의 사슬이다 — 소환 · 비용 지불은 체인 대상이 아니다.
    assert "Summoning a monster" in chain["cannot_chain_to"]
    assert "paying costs" in chain["cannot_chain_to"]


def test_03_the_rulebook_does_not_define_missed_timing_or_may_semantics():
    """
    **§2-8 · §2-9 — 공식 자료의 한계를 분명히 적는다.**

    이 룰북(스타터 덱 룰북 v10)에는 "놓친 타이밍" 도, "may/can" 의 세부 처리도
    없다. ``mandatory``/``optional`` 이라는 낱말이 나오는 절은 **RULE-CHAIN-010
    하나**다. 그러므로 그 두 규칙을 지금 구현하면 **근거 없이 만드는 것**이다.
    """
    data = json.loads(RULEBOOK_DOC.read_text(encoding="utf-8"))
    with_words = [
        s["rule_id"]
        for s in data["sections"]
        if re.search(r"\bmandatory\b|\boptional\b", s["text"], re.I)
    ]
    assert with_words == ["RULE-CHAIN-010"], with_words

    missed = [
        s["rule_id"]
        for s in data["sections"]
        if re.search(r"missed timing", s["text"], re.I)
    ]
    assert missed == [], missed


# ======================================================================
# §3 · §6 — 현재 구조로 표현할 수 있는가
# ======================================================================


def test_04_activate_effect_already_names_a_single_effect():
    """
    **§6 — 새 ActionKind 가 필요하지 않다.** ``ACTIVATE_EFFECT`` 가 이미
    "이 카드의 **이 효과**를 발동한다" 이고, ``effect_ref`` 로 지목한다.
    """
    fields = set(PlayerAction.__dataclass_fields__)
    assert {"kind", "actor", "source", "effect_ref", "targets"} <= fields

    #: 행위 종류 목록을 **고정**한다 — 이 Phase 는 하나도 더하지 않았다.
    assert {kind.value for kind in PlayerActionKind} == {
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
    }

    #: "발동하지 않겠다" 도 이미 **선택**으로 있다.
    doc = PlayerActionKind.__doc__ or ""
    source = (PROJECT_ROOT / "engine/action.py").read_text(encoding="utf-8")
    assert "아무것도 하지 않겠다는 **선택**" in source
    assert PlayerActionKind.PASS.value == "pass"
    del doc


def test_05_the_only_production_chain_link_builder_requires_a_player_action():
    """
    **§3 — production 에서 ``ChainLink`` 를 만드는 함수는 ``PlayerAction`` 을
    인자로 받는다.**

    ``EffectActivator.activate`` 의 서명이 그렇고, 링크의 ``actor`` ·
    ``effect_ref`` · ``source`` 가 전부 그 행위에서 나온다. 즉 **발동의 주인은
    행위**다.
    """
    tree = ast.parse((PROJECT_ROOT / "engine/activation.py").read_text(encoding="utf-8"))
    owners = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        makes_link = any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "ChainLink"
            for inner in ast.walk(node)
        )
        if makes_link:
            params = [arg.arg for arg in node.args.args]
            owners.append((node.name, params))
    assert owners, "ChainLink 를 만드는 함수를 찾지 못했다"
    for name, params in owners:
        assert "action" in params, (name, params)

    #: 서명 자체도 ``PlayerAction`` 으로 적혀 있다 (``from __future__ import
    #: annotations`` 때문에 문자열로 남는다 — 그래도 계약은 그대로다).
    assert EffectActivator.activate.__annotations__["action"] == "PlayerAction"
    assert EffectActivator.can_activate.__annotations__["action"] == "PlayerAction"


@pytest.mark.real_card
def test_06_apply_refuses_anything_that_is_not_a_legal_action(repository):
    """
    **§3-2 — ``Duel.apply`` 는 허가 목록에 없는 행위를 거절한다** (Phase 3-E-13).

    그래서 "엔진이 내부에서 유발을 발동한다" 를 지금 구조에 끼워 넣으려면
    ``apply`` 를 **우회**해야 한다. 우회는 두 번째 실행 경로를 만드는 일이다.
    """
    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    #: 상대 자리의 발동을 내 턴에 밀어 넣어 본다 — 후보가 아니다.
    intruder = PlayerAction(
        kind=PlayerActionKind.ACTIVATE_EFFECT,
        actor=1 - seat,
        source=duel.state.player(1 - seat).hand[0].instance_id,
    )
    step = duel.apply(intruder)
    assert not step.accepted
    assert "허가된 행위가 아닙니다" in step.reason


@pytest.mark.real_card
def test_07_advance_is_the_existing_home_for_work_nobody_chooses(repository):
    """
    **§6 — 강제 유발이 하나뿐일 때의 선례가 이미 있다.**

    드로우 페이즈의 드로우는 ``legal_actions`` 에 **없다** — 뽑지 않겠다고 고를
    수 없기 때문이다. 그 일은 ``Duel.advance()`` 가 한다. 즉 "고르지 않는 일" 을
    담는 자리가 이미 있고, 그것이 ``PlayerAction`` 을 **요구하지 않는다.**

    그래도 보고는 행위 모양으로 나간다 (``PASS`` 를 영수증으로 쓴다) — 판을
    바꾼 일이 기록 없이 사라지지 않는다.
    """
    duel = small_duel(repository)
    #: 선공 첫 턴은 뽑지 않는다 (룰북). 다음 턴 드로우까지 간다.
    while not (duel.step is TurnStep.DRAW_PENDING):
        duel.apply(PlayerAction(kind=PlayerActionKind.END_PHASE, actor=duel.turn_player))

    seat = duel.turn_player
    assert duel.legal_actions(seat).allowed == ()  # 고를 것이 없다
    before = len(duel.state.player(seat).hand)
    step = duel.advance()
    assert step is not None and step.accepted
    assert len(duel.state.player(seat).hand) == before + 1
    #: 영수증의 행위 종류는 ``PASS`` 다 — 누가 고른 것이 아니다.
    assert step.action.kind is PlayerActionKind.PASS


# ======================================================================
# §4 · §5 — 유발 쪽에는 무엇이 있는가
# ======================================================================


def test_08_the_requirement_enum_only_stores_the_card_text():
    """
    **§5 — ``TriggerRequirement`` 는 판정하지 않고 담기만 한다.**

    ``UNKNOWN`` 이 있고, 그것을 강제/임의 중 한쪽으로 접지 않는다. 그래서 지금
    구조는 "강제인지 임의인지 모른다" 를 **말할 수 있다** — 이 Phase 가 어느
    쪽으로도 정하지 않아도 되는 이유다.
    """
    assert {r.value for r in TriggerRequirement} == {
        "mandatory",
        "optional",
        "unknown",
    }
    #: 후보의 기본값이 ``UNKNOWN`` 이다 — 적지 않은 것을 임의로 정하지 않는다.
    fields = TriggerCandidate.__dataclass_fields__
    assert fields["requirement"].default is TriggerRequirement.UNKNOWN
    assert fields["wording"].default.value == "unknown"

    source = (PROJECT_ROOT / "engine/trigger.py").read_text(encoding="utf-8")
    assert "판정하지 않고 담기만 한다" in source


def test_09_the_ordering_layer_already_records_the_choice_it_cannot_make():
    """
    **§6 — "같은 플레이어의 여러 트리거를 그 사람이 고르는 순서" 가 이미 공백으로
    적혀 있다.**

    즉 강제 유발의 순서가 선택이라는 사실을 repository 가 이미 알고 있었고,
    이번 감사는 그 공백에 **공식 근거(RULE-CHAIN-010)를 붙였을 뿐**이다.
    """
    assert "SEGOC (동시 발동 트리거의 규칙상 순서)" in UNRESOLVED_ORDER_RULES
    assert "강제 트리거와 임의 트리거의 우선순위" in UNRESOLVED_ORDER_RULES
    assert "같은 플레이어의 여러 트리거를 그 사람이 고르는 순서" in UNRESOLVED_ORDER_RULES


def test_10_the_dormant_integrator_builds_links_without_any_action():
    """
    **§4 — 잠든 계층은 ``PlayerAction`` 없이 ``ChainLink`` 를 만든다.**

    ``TriggerChainIntegrator._entry`` 의 인자에 ``action`` 이 없고, 만드는
    링크에 ``selections`` 도 ``payments`` 도 없다. 그러므로 **그대로 연결하면**
    ``legal_actions()`` 를 우회하는 두 번째 경로가 된다. 지금은 불리지 않으므로
    모순이 아니다 (Phase 3-E-20).
    """
    tree = ast.parse(
        (PROJECT_ROOT / "engine/trigger_chain.py").read_text(encoding="utf-8")
    )
    builders = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "ChainLink"
            ):
                builders[node.name] = (
                    [arg.arg for arg in node.args.args],
                    {kw.arg for kw in inner.keywords},
                )
    assert "_entry" in builders, builders
    params, kwargs = builders["_entry"]
    assert "action" not in params, params
    assert kwargs == {"sequence", "actor", "effect_ref", "source"}
    #: 비용 영수증과 선택이 빠져 있다 — 발동 경로가 채우는 바로 그 둘이다.
    assert "selections" not in kwargs and "payments" not in kwargs


# ======================================================================
# §7 — AI / Search 경계
# ======================================================================


@pytest.mark.real_card
def test_11_search_cannot_see_anything_outside_legal_actions(repository):
    """
    **§7-2 · §7-3 — 탐색은 ``legal_actions`` 밖을 보지 못한다.**

    후보 목록에 없는 행위는 ``NOT_A_CANDIDATE`` 로 돌아온다. 그러므로 유발이
    ``PlayerAction`` 으로 나오지 않으면 **탐색은 그것을 영영 못 본다.**
    """
    from agent.simulation import SimulationStatus, Simulator

    duel = at_main1(small_duel(repository))
    seat = duel.turn_player
    simulator = Simulator(duel)

    outsider = PlayerAction(
        kind=PlayerActionKind.ACTIVATE_EFFECT,
        actor=seat,
        source=duel.state.player(1 - seat).hand[0].instance_id,
    )
    result = simulator.simulate(outsider, viewer=seat)
    assert result.status is SimulationStatus.NOT_A_CANDIDATE

    #: 반대로 후보에 있는 발동은 그대로 시뮬레이션된다.
    activations = [
        a
        for a in duel.legal_actions(seat)
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert activations
    assert simulator.simulate(activations[0], viewer=seat).status is not (
        SimulationStatus.NOT_A_CANDIDATE
    )


def test_12_search_treats_a_pass_only_position_as_not_a_decision():
    """
    **§7-4 — 탐색의 "결정 지점" 규약이 이미 적혀 있다.**

    사본에서 **PASS 밖에 없는 자리**는 대신 밟고, 고를 것이 하나라도 있으면
    멈춘다. 그래서 유발이 후보로 나오면 탐색은 **고치지 않아도** 그것을 결정
    지점으로 본다. 반대로 엔진이 몰래 발동해 버리면 깊이 1 의 미래가 아무도
    고르지 않은 자리가 된다 — 그것이 이 경계를 지켜야 하는 이유다.
    """
    source = (PROJECT_ROOT / "agent/simulation.py").read_text(encoding="utf-8")
    assert "고를 것이 있다 — 그것은 결정이므로 여기서 멈춘다" in source
    assert "PlayerActionKind.PASS" in source
    #: 탐색 · 평가 · 정책은 트리거라는 낱말을 모른다 (Phase 3-E-20 이 고정).
    for name in ("agent/search.py", "agent/evaluation.py", "agent/policy.py"):
        assert "trigger" not in (PROJECT_ROOT / name).read_text(encoding="utf-8").lower()


# ======================================================================
# §12 — 이미 등록된 공백
# ======================================================================


def test_13_structural_31_already_owns_this_gap():
    """
    **§12 — 새 STRUCTURAL ID 를 만들지 않는 근거.**

    Phase 2-F-3-D 가 이미 ``STRUCTURAL-31`` 로 "대상 · 비용을 채워 줄 계층이
    없다 — 트리거 효과는 그 둘이 정해지기 전까지 체인에 들어가지 못한다" 를
    적어 두었다. 이번 감사가 찾은 소유권 질문은 **그 공백의 다른 면**이다:
    대상과 비용을 채우는 자리가 이미 있고(``PlayerAction`` → ``EffectActivator``),
    트리거가 그 자리를 쓰지 않고 있다.
    """
    doc = (PROJECT_ROOT / "docs/phase2f3d-trigger-chain.md").read_text(encoding="utf-8")
    assert "STRUCTURAL-31" in doc
    assert "대상/비용 미정" in doc
    assert "체인에 들어가지 못한다" in doc
