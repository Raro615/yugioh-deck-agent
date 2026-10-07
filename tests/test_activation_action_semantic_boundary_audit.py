"""
Phase 3-F-22 — ``ACTIVATE_CARD`` ↔ ``ACTIVATE_EFFECT`` 의미 경계 감사.

이 파일이 답하는 단 하나의 질문
-------------------------------
두 ``PlayerActionKind`` 가 **서로 다른 게임 의미**를 갖는가, 그리고 그 의미가
Engine → Chain → Resolution → AI/Search 전체에서 **일관되게** 유지되는가.

🟢 둘은 **코드가 강제하는 서로 다른 것**이다
--------------------------------------------
=============================  ==========================  ==========================
                                ``ACTIVATE_CARD``           ``ACTIVATE_EFFECT``
=============================  ==========================  ==========================
``effect_ref``                  허용(선택)                   **필수** (``test_01``)
``_MISSING_RULE``               **있다** — 허가 불가          없다
``_COMPLETE_RULES``             없다                        **있다** (``test_04``)
요구 생성기                      ``_activate``               ``_activate_effect``
``EffectActivator``             **kind 로 거절**             받는다 (``test_07``)
``RESPONDABLE`` (응답 루프)       없다                        **있다**
``legal_actions``               ``withheld`` 로만            후보로 **나온다**
``Duel.apply``                  실행 경로 없음                ``_apply_activation``
ChainLink                       생기지 않는다                 생긴다 (``test_08``)
=============================  ==========================  ==========================

그리고 그 분리는 **의도된 수정**이었다 — ``_activate_effect`` docstring 이 적는다:
*"``ACTIVATE_CARD`` 와 ``ACTIVATE_EFFECT`` 는 뜻이 다른데 요구 하나를 공유하고
있었다 (STRUCTURAL-119)"*. 즉 합쳐져 있던 것을 **갈라낸** 것이다.

🔴 다만 **공식 용어와 어긋난다**
--------------------------------
저장소의 공식 룰북(`data/rules/structured/sd-rulebook-en-v10.json`)은 메인 페이즈의
행동을 **"Activate a Card or Effect"** 하나로 적고, 체인은 *"the activation of a
card or effect"* 로 설명한다 — 공식은 **한 행동**이다.

그런데 현재 등록된 16개 효과는 **전부 마법·함정**이고 **몬스터는 0장**이다
(``test_12``). 공식 용어로는 그것이 **"카드의 발동"** 인데, 엔진은 그것을
``ACTIVATE_EFFECT`` 로 처리하고, 그 이름을 가진 ``ACTIVATE_CARD`` 는 미지원이다.
엔진의 구분 기준은 공식의 카드/효과가 아니라 **"특정 효과를 지목했는가"**
(``effect_ref``)다 (``test_13``).

이 Phase 는 production 을 **한 줄도** 바꾸지 않는다 (``test_26``).
"""

import ast
import collections
import dataclasses
import inspect
import json
import pathlib
import subprocess
import textwrap

import pytest

from agent.runner import DuelRunner
from agent.search import search_policy
from agent.simulation import Simulator
from engine.action import (
    MalformedAction,
    PlayerAction,
    PlayerActionKind,
)
from engine.action_execution import ActionExecutor
from engine.action_validation import ActionValidator, ActionValidity
from engine.activation import ActivationStatus, EffectActivator
from engine.chain import Chain, ChainLink
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import EffectRef, InstanceId
from engine.response import RESPONDABLE
from engine.spell_activation import activatable_effects, duel_activator
from engine.state.game_state import GameState
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
MYSELF = "tests/test_activation_action_semantic_boundary_audit.py"

MINE, THEIRS = 0, 1

#: 실제 등록 카드 — 전부 공식 DB 에서 온다.
POT_OF_GREED = 55144522          # 마법 · executable 효과 1개
MYSTICAL_SPACE_TYPHOON = 5318639  # 마법 · 대상이 필요하다
COMPULSORY_EVACUATION = 94192409  # 함정 · executable 효과 1개
LOST = 24623598                   # 함정 · executable 효과 **0개**
LUSTER_DRAGON = 11091375          # 통상 몬스터 · 효과 없음
DIAN_KETO = 84257639              # 마법
GENEROUS_REWARD = 5915629         # 함정
FEATHERMAN = 71925487             # 채우기용 통상 몬스터

DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [GENEROUS_REWARD] * 4
SPELL_DECK = [POT_OF_GREED] * 8 + [DIAN_KETO] * 8 + [LUSTER_DRAGON] * 4

RULEBOOK = PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json"


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
    source = textwrap.dedent(inspect.getsource(func))
    return ast.parse(source.replace(f"def {func.__name__}", "def f", 1))


def kind_references(name: str, *, production_only: bool = True):
    """``PlayerActionKind.<name>`` 을 **코드로** 참조하는 자리."""
    found: list[tuple[str, int]] = []
    paths = (
        production_files()
        if production_only
        else (p for p in sorted(PROJECT_ROOT.rglob("*.py")) if "__pycache__" not in str(p))
    )
    for path in paths:
        relative = str(path.relative_to(PROJECT_ROOT))
        try:
            tree = ast.parse(code_only(relative))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == name
                and isinstance(node.value, ast.Name)
                and node.value.id == "PlayerActionKind"
            ):
                found.append((relative, node.lineno))
    return found


# ======================================================================
# 판
# ======================================================================


def hand_board(repository, passcode: int, *, owner: int = MINE):
    """``passcode`` 한 장을 **패에** 들린 판."""
    state = GameState.create(
        repository,
        decks=([passcode] * 4 + [FEATHERMAN] * 12, [FEATHERMAN] * 16),
        seed=5,
    )
    card = state.create_instance(passcode, owner=owner, zone=Zone.HAND)
    state.turn.set_phase(Phase.MAIN1)
    return state, card.instance_id


def validator_for(state, seat: int = MINE) -> ActionValidator:
    return ActionValidator(GameStateView.from_state(state, viewer=seat))


def opened_duel(repository, *, seed: int, deck=None) -> Duel:
    cards = list(DIGEST_DECK if deck is None else deck)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    while duel.advance() is not None:
        pass
    return duel


def walk_for_activation(repository, *, seed: int, deck=None, limit: int = 400):
    """발동을 **우선 고르며** 한 판을 밀고, 후보/수락을 센다."""
    cards = list(deck or SPELL_DECK)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    offered: collections.Counter = collections.Counter()
    withheld: collections.Counter = collections.Counter()
    accepted: collections.Counter = collections.Counter()
    first_activation = None
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
        pick = next(
            (a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT),
            None,
        )
        chosen = pick or legal.allowed[0]
        step = duel.apply(chosen)
        if step.accepted:
            accepted[chosen.kind] += 1
        if pick is not None and first_activation is None and step.accepted:
            first_activation = (chosen, step, len(duel.chain.links))
    return duel, {
        "offered": offered,
        "withheld": withheld,
        "accepted": accepted,
        "first_activation": first_activation,
    }


# ======================================================================
# A. §2 — 데이터 모델이 강제하는 차이
# ======================================================================


def test_01_only_activate_effect_requires_an_effect_ref():
    """
    🟢 §2 ③ — **``effect_ref`` 의 필수성이 둘을 가른다.** 이름이 아니라 **모델**이다.

    ``PlayerAction.activate_effect`` 는 ``effect_ref`` 를 **필수 위치 인자**로
    받는다. ``activate_card`` 는 **선택**이다.
    """
    #: 🔴 팩토리 시그니처가 강제한다.
    effect_sig = inspect.signature(PlayerAction.activate_effect)
    card_sig = inspect.signature(PlayerAction.activate_card)
    assert effect_sig.parameters["effect_ref"].default is inspect.Parameter.empty
    assert card_sig.parameters["effect_ref"].default is None

    #: 그래서 하나는 만들 수 없고 하나는 만들 수 있다.
    with pytest.raises(TypeError):
        PlayerAction.activate_effect(MINE, InstanceId(1))  # type: ignore[call-arg]
    without = PlayerAction.activate_card(MINE, InstanceId(1))
    assert without.effect_ref is None

    #: 그리고 그 규칙이 데이터 모델의 표에 적혀 있다.
    action_code = code_only("engine/action.py")
    assert "_NEEDS_EFFECT_REF" in action_code
    assert "_ALLOWS_EFFECT_REF" in action_code


def test_02_the_two_actions_are_different_values():
    """§2 ③ — 같은 카드·같은 효과를 가리켜도 **서로 다른 값**이다."""
    ref = EffectRef(POT_OF_GREED, 0)
    card = PlayerAction.activate_card(MINE, InstanceId(1), effect_ref=ref)
    effect = PlayerAction.activate_effect(MINE, InstanceId(1), effect_ref=ref)

    assert card != effect
    assert card.canonical_state() != effect.canonical_state()
    assert card.canonical_state()[0] == "activate_card"
    assert effect.canonical_state()[0] == "activate_effect"
    #: 직렬화에도 구분이 남는다.
    assert card.to_dict()["kind"] != effect.to_dict()["kind"]


def test_03_both_kinds_exist_and_neither_was_added_or_removed():
    """§9 — 두 enum 이 그대로 있다. 합치지도 지우지도 않았다."""
    values = [k.value for k in PlayerActionKind]
    assert "activate_card" in values and "activate_effect" in values
    assert len(values) == 11
    #: 새 activation enum 도 없다.
    for forbidden in ("ActivationAction", "ActivateKind", "ACTIVATE_ANY"):
        for path in production_files():
            relative = str(path.relative_to(PROJECT_ROOT))
            assert forbidden not in code_only(relative), (forbidden, relative)


def test_04_the_validator_puts_them_in_mutually_exclusive_registries():
    """
    🔴 §2 ⑤ · §6 — **검증기의 두 등록부가 둘을 반대쪽에 넣는다.**

    * ``_MISSING_RULE`` — "허가까지 갈 수 없다" → **``ACTIVATE_CARD``**
    * ``_COMPLETE_RULES`` — "적법성을 끝까지 볼 수 있다" → **``ACTIVATE_EFFECT``**

    그리고 모듈이 스스로 **두 집합이 겹치지 않음을 assert 한다.**
    """
    import engine.action_validation as av

    assert PlayerActionKind.ACTIVATE_CARD in av._MISSING_RULE
    assert PlayerActionKind.ACTIVATE_CARD not in av._COMPLETE_RULES
    assert PlayerActionKind.ACTIVATE_EFFECT in av._COMPLETE_RULES
    assert PlayerActionKind.ACTIVATE_EFFECT not in av._MISSING_RULE

    #: 🔴 모듈 자신이 분리를 강제한다.
    assert not (av._COMPLETE_RULES & set(av._MISSING_RULE))
    module_code = code_only("engine/action_validation.py")
    assert "_COMPLETE_RULES & set(_MISSING_RULE)" in module_code


def test_05_the_two_kinds_have_different_requirement_builders():
    """
    🟢 §2 ④ — 요구 생성기가 **다르다**: ``_activate`` vs ``_activate_effect``.

    그리고 분리의 이유가 docstring 에 적혀 있다 — 둘이 요구 하나를 **공유하던**
    것이 STRUCTURAL-119 였고, 그것을 **갈라낸** 것이다.
    """
    import engine.action_validation as av

    builders = av._REQUIREMENT_BUILDERS
    assert builders[PlayerActionKind.ACTIVATE_CARD] is av._activate
    assert builders[PlayerActionKind.ACTIVATE_EFFECT] is av._activate_effect
    assert (
        builders[PlayerActionKind.ACTIVATE_CARD]
        is not builders[PlayerActionKind.ACTIVATE_EFFECT]
    )

    doc = inspect.getdoc(av._activate_effect) or ""
    assert "STRUCTURAL-119" in doc
    assert "뜻이 다른데" in doc
    #: 그리고 발동 계층이 한쪽만 받는다는 사실도 적는다.
    assert "ACTIVATE_EFFECT" in doc


def test_06_activate_card_is_registered_as_a_missing_rule(repository):
    """
    🟢 §6 — ``activate_card`` 가 왜 허용되지 않는가: **빠진 규칙의 이름이 적혀 있다.**

    "아직 구현하지 않음" 이라는 막연한 문구가 아니라 ``activation-timing
    (Phase 2-C/2-F)`` 라는 **지목**이다.
    """
    state, source = hand_board(repository, POT_OF_GREED)
    verdict = validator_for(state).validate(PlayerAction.activate_card(MINE, source))

    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == "activation-timing (Phase 2-C/2-F)"

    #: 🔴 ``UNKNOWN`` 은 ``INVALID`` 가 아니다 — "규칙이 금지한다" 가 아니다.
    assert verdict.validity is not ActionValidity.INVALID


def test_07_the_activator_refuses_activate_card_by_kind(repository):
    """
    🔴 §2 ④ — **둘은 같은 실행 경로로 수렴하지 않는다.**

    ``EffectActivator`` 가 **종류만 보고** 거절한다 — 카드가 무엇이든, 판이
    어떻든 상관없다. 그 거절 문구가 경계를 가장 또렷하게 말한다:
    *"activate_card 는 효과 발동이 아닙니다."*
    """
    activator = duel_activator()
    for passcode in (POT_OF_GREED, MYSTICAL_SPACE_TYPHOON, LUSTER_DRAGON, LOST):
        state, source = hand_board(repository, passcode)
        outcome = activator.activate(
            state, Chain(), PlayerAction.activate_card(MINE, source)
        )
        assert outcome.status is ActivationStatus.INVALID_ACTION, passcode
        assert outcome.code is ValidationCode.RULE_NOT_IMPLEMENTED
        assert "효과 발동이 아닙니다" in outcome.reason
        #: 체인에 아무것도 쌓이지 않는다.
        assert len(outcome.chain.links) == 0

    #: 그 거절이 코드에서 **종류 비교**로 이루어진다 (문자열이 아니라 AST).
    activation_code = code_only("engine/activation.py")
    assert "PlayerActionKind.ACTIVATE_EFFECT" in activation_code
    assert "PlayerActionKind.ACTIVATE_CARD" not in activation_code


def test_08_activate_effect_builds_a_chain_link(repository):
    """🟢 §1 · §4 — ``activate_effect`` 는 **ChainLink 까지** 간다."""
    state, source = hand_board(repository, POT_OF_GREED)
    refs = activatable_effects(POT_OF_GREED)
    assert refs, "욕망의 항아리에 executable 효과가 없다"

    outcome = duel_activator().activate(
        state, Chain(), PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    )
    assert outcome.status is ActivationStatus.ACTIVATED
    assert outcome.code is ValidationCode.OK
    assert len(outcome.chain.links) == 1
    link = outcome.chain.links[0]
    assert isinstance(link, ChainLink)
    assert link.actor == MINE
    assert link.effect_ref == refs[0]
    #: 🔴 링크는 **효과**를 가리킨다 — 카드가 아니라 효과 번호까지다.
    assert link.effect_ref.card_id == POT_OF_GREED


def test_09_only_activate_effect_is_respondable():
    """§1 — 응답 루프가 다루는 종류에 ``ACTIVATE_EFFECT`` 만 있다."""
    assert RESPONDABLE == frozenset(
        {PlayerActionKind.ACTIVATE_EFFECT, PlayerActionKind.PASS}
    )
    assert PlayerActionKind.ACTIVATE_CARD not in RESPONDABLE


def test_10_neither_kind_is_registered_in_the_executor():
    """
    §1 — 🟡 **실행기에는 둘 다 없다.** 그런데 결과가 다르다.

    ``ACTIVATE_EFFECT`` 는 ``Duel._apply_activation`` 이 직접 처리하고,
    ``ACTIVATE_CARD`` 는 아무 데도 가지 않는다. 그래서 "실행기에 없다" 를
    "실행할 수 없다" 로 읽으면 틀린다 (Phase 3-F-21 §6 과 같은 함정).
    """
    supported = duel_executor().supported
    assert PlayerActionKind.ACTIVATE_CARD not in supported
    assert PlayerActionKind.ACTIVATE_EFFECT not in supported

    #: ``apply`` 의 dispatch 는 ``ACTIVATE_EFFECT`` 만 이름으로 집는다.
    dispatch = {
        node.attr
        for node in ast.walk(method_tree(Duel.apply))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    }
    assert "ACTIVATE_EFFECT" in dispatch
    assert "ACTIVATE_CARD" not in dispatch

    #: 🟡 그런데 ``UNSUPPORTED_REASON`` 은 둘에게 **같은 문구**를 준다 — 실행기
    #: 관점에서는 둘 다 미등록이라 맞는 말이지만, 한쪽은 실제로 실행된다.
    import engine.action_execution as ae

    assert (
        ae.UNSUPPORTED_REASON[PlayerActionKind.ACTIVATE_CARD]
        == ae.UNSUPPORTED_REASON[PlayerActionKind.ACTIVATE_EFFECT]
    )


# ======================================================================
# B. §3 · §4 — 실제 카드 시나리오
# ======================================================================


def test_11_five_real_cards_classified_end_to_end(repository):
    """
    §4 — **실제 등록 카드 다섯 장**을 끝까지 돌려 분류한다. 가상 카드 없음.

    ====================================  ==========================  ==============
    카드                                   ``activate_effect``         ChainLink
    ====================================  ==========================  ==============
    욕망의 항아리 (마법)                     🟢 ``VALID`` → activated    **1**
    싸이크론 (마법, 대상 필요)                🟢 ``VALID`` → 대상 미달      0
    강제 탈출 장치 (함정)                    🟡 ``UNKNOWN`` (함정 타이밍)  0
    로스트 (함정, executable 0)             후보 자체가 없다              0
    홍옥의 사령 (통상 몬스터)                 후보 자체가 없다              0
    ====================================  ==========================  ==============
    """
    activator = duel_activator()
    rows = {}
    for passcode in (
        POT_OF_GREED,
        MYSTICAL_SPACE_TYPHOON,
        COMPULSORY_EVACUATION,
        LOST,
        LUSTER_DRAGON,
    ):
        state, source = hand_board(repository, passcode)
        refs = activatable_effects(passcode)
        if not refs:
            rows[passcode] = ("후보없음", None, 0)
            continue
        action = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
        verdict = validator_for(state).validate(action)
        outcome = activator.activate(state, Chain(), action)
        rows[passcode] = (
            verdict.validity.value,
            outcome.status.value,
            len(outcome.chain.links),
        )

    assert rows[POT_OF_GREED] == ("valid", "activated", 1), rows[POT_OF_GREED]
    assert rows[MYSTICAL_SPACE_TYPHOON][0] == "valid"
    assert rows[MYSTICAL_SPACE_TYPHOON][2] == 0
    #: 🟡 함정은 **다른 빠진 규칙**으로 막힌다 — 마법과 같은 이유가 아니다.
    assert rows[COMPULSORY_EVACUATION][0] == "unknown", rows[COMPULSORY_EVACUATION]
    #: executable 이 아니면 후보가 되지 않는다 (ADR-006).
    assert rows[LOST] == ("후보없음", None, 0)
    assert rows[LUSTER_DRAGON] == ("후보없음", None, 0)


def test_12_every_registered_effect_belongs_to_a_spell_or_trap(repository):
    """
    🔴 §3 · §7 — **등록된 16개 효과는 전부 마법·함정이다. 몬스터는 0장.**

    그래서 §3 이 구분하라고 한 "Monster Effect activation" 은 **현재 도달할 수
    없다.** 없는 것을 있다고 적지 않는다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    card_ids = sorted({entry.definition.effect_ref.card_id for entry in EFFECT_LIBRARY})
    assert len(EFFECT_LIBRARY) == 16
    assert len(card_ids) == 16

    kinds = collections.Counter()
    for card_id in card_ids:
        card = repository.get(card_id)
        assert card is not None, card_id
        if card.is_monster:
            kinds["monster"] += 1
        elif card.is_spell:
            kinds["spell"] += 1
        elif card.is_trap:
            kinds["trap"] += 1
    #: 🔴 몬스터가 **없다.**
    assert kinds["monster"] == 0, dict(kinds)
    assert kinds["spell"] + kinds["trap"] == 16, dict(kinds)


def test_13_the_engine_splits_on_effect_ref_not_on_card_versus_effect(repository):
    """
    🔴 §2 ⑤ — 둘의 차이를 정하는 것은 **"특정 효과를 지목했는가"** 다.

    카드 종류도, 효과 종류도, 발동 출처도, 타이밍도, player intent 도 아니다 —
    현재 코드에서 유일하게 **강제되는** 차이는 ``effect_ref`` 다(``test_01``).
    같은 마법 한 장에 두 종류를 다 만들어 보면, 갈리는 지점이 거기임이 보인다.
    """
    state, source = hand_board(repository, POT_OF_GREED)
    refs = activatable_effects(POT_OF_GREED)
    validator = validator_for(state)

    #: 같은 카드 · 같은 자리 · 같은 판 — 종류만 다르다.
    as_effect = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    as_card = PlayerAction.activate_card(MINE, source, effect_ref=refs[0])
    assert as_effect.source == as_card.source
    assert as_effect.effect_ref == as_card.effect_ref

    #: 🔴 그런데 판정이 갈린다.
    assert validator.validate(as_effect).validity is ActionValidity.VALID
    assert validator.validate(as_card).validity is ActionValidity.UNKNOWN

    #: ``effect_ref`` 를 똑같이 들고 있어도 ``activate_card`` 는 허가되지 않는다 —
    #: 그러므로 갈림의 기준은 **종류 그 자체**이고, 그 종류의 뜻이
    #: "효과를 지목한다" 다.
    assert as_card.effect_ref is not None


def test_14_a_real_duel_offers_activate_effect_and_withholds_activate_card(repository):
    """§4 · §5 — 실제 듀얼에서 한쪽은 후보로, 한쪽은 ``withheld`` 로 나온다."""
    duel, counts = walk_for_activation(repository, seed=401)

    assert counts["offered"][PlayerActionKind.ACTIVATE_EFFECT] > 0, dict(
        counts["offered"]
    )
    assert counts["offered"][PlayerActionKind.ACTIVATE_CARD] == 0
    assert counts["withheld"][PlayerActionKind.ACTIVATE_CARD] > 0
    assert counts["withheld"][PlayerActionKind.ACTIVATE_EFFECT] == 0

    #: 그리고 고른 발동이 실제로 수락되고 체인이 쌓였다.
    assert counts["first_activation"] is not None
    action, step, links = counts["first_activation"]
    assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert step.accepted and step.code is ValidationCode.OK
    assert links == 1

    #: .. note::
    #:    🔴 원래 여기까지만 쟀다 — ``withheld`` 의 **이름표**만 보고 그 이유가
    #:    어디서 왔는지는 보지 않았다. 그래서 고의 위반 주입 6번(보류 사유를
    #:    ``activate_card`` 대신 ``activate_effect`` 를 검증해서 만들기)을
    #:    **놓쳤다** — 이름표는 코드에 박힌 리터럴이라 그대로 남기 때문이다.
    #:    이름표와 **사유의 출처**가 맞는지까지 센다.
    fresh = opened_duel(repository, seed=401, deck=SPELL_DECK)
    seat = fresh.to_act
    held = [
        w
        for w in fresh.legal_actions(seat).withheld
        if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert held, "activate_card 보류가 없다"

    hand = fresh.state.player(seat).hand
    assert hand
    expected = validator_for(fresh.state, seat).validate(
        PlayerAction.activate_card(seat, hand[0].instance_id)
    )
    #: 🔴 보류의 이유와 빠진 규칙이 **``activate_card`` 를 검증한 결과**와 같다.
    assert held[0].reason == expected.reason, (held[0].reason, expected.reason)
    assert held[0].missing == expected.missing_rule, (
        held[0].missing,
        expected.missing_rule,
    )
    assert held[0].missing == "activation-timing (Phase 2-C/2-F)"


def test_15_applying_activate_card_to_a_duel_is_refused(repository):
    """§4 4 — 듀얼에 직접 넣어도 거부된다. 판이 바뀌지 않는다."""
    duel = opened_duel(repository, seed=402, deck=SPELL_DECK)
    seat = duel.to_act
    hand = duel.state.player(seat).hand
    assert hand
    probe = PlayerAction.activate_card(seat, hand[0].instance_id)

    assert probe not in set(duel.legal_actions(seat).allowed)
    before = duel.state.state_hash()
    step = duel.apply(probe)
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert duel.state.state_hash() == before
    assert len(duel.chain.links) == 0


def test_16_a_trap_is_withheld_for_a_different_reason_than_activate_card(repository):
    """
    🟡 §2 ⑥ — **"지금 안 되는 이유" 가 종류별로 다르다.** 뭉개지 않는다.

    * ``activate_card`` → ``activation-timing (Phase 2-C/2-F)``
    * 함정의 ``activate_effect`` → ``trap-activation-timing …``

    두 이유를 하나로 적으면 "발동이 전부 안 된다" 로 읽히는데, 그것은 거짓이다.
    """
    state, source = hand_board(repository, COMPULSORY_EVACUATION)
    refs = activatable_effects(COMPULSORY_EVACUATION)
    assert refs
    validator = validator_for(state)

    trap_verdict = validator.validate(
        PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    )
    card_verdict = validator.validate(PlayerAction.activate_card(MINE, source))

    assert trap_verdict.validity is ActionValidity.UNKNOWN
    assert card_verdict.validity is ActionValidity.UNKNOWN
    #: 🔴 이유가 **다르다.**
    assert trap_verdict.missing_rule != card_verdict.missing_rule
    assert "trap-activation-timing" in (trap_verdict.missing_rule or "")
    assert card_verdict.missing_rule == "activation-timing (Phase 2-C/2-F)"


def test_17_an_activate_effect_without_a_known_effect_is_refused(repository):
    """§10 — 잘못된 입력: 등록되지 않은 ``effect_ref`` 는 거절된다."""
    state, source = hand_board(repository, POT_OF_GREED)
    bogus = EffectRef(POT_OF_GREED, 99)
    outcome = duel_activator().activate(
        state, Chain(), PlayerAction.activate_effect(MINE, source, effect_ref=bogus)
    )
    assert outcome.status is not ActivationStatus.ACTIVATED
    assert len(outcome.chain.links) == 0


# ======================================================================
# C. §5 — AI / Search 영향
# ======================================================================


def test_18_the_agent_layer_never_names_either_kind():
    """
    🟢 §5 — **AI 는 둘을 이름으로 구분하지 않는다.** 후보로 받은 것을 그대로 쓴다.

    그래서 두 종류의 구분은 **엔진 내부 계약**이고 AI 계약이 아니다.
    """
    for name in ("ACTIVATE_CARD", "ACTIVATE_EFFECT"):
        agent_refs = [
            site for site in kind_references(name) if site[0].startswith("agent/")
        ]
        assert agent_refs == [], (name, agent_refs)

    #: 그리고 ``agent/`` 가 이름으로 집는 종류는 셋뿐이다 (Phase 3-F-21 측정).
    tree = ast.parse(source_of("agent/heuristic.py"))
    named = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    }
    assert named == {"NORMAL_SUMMON", "END_PHASE", "PASS"}, named


def test_19_canonical_ordering_separates_the_two_kinds():
    """
    §5 — 정렬은 둘을 **구분한다** (``canonical_state`` 의 첫 칸이 종류다).

    그런데 ``activate_card`` 가 후보로 **한 번도 나오지 않으므로** 실제 정렬
    결과에는 영향이 없다 — 그것이 "action space 의 의미가 달라지는가" 에 대한 답이다.
    """
    ref = EffectRef(POT_OF_GREED, 0)
    card = PlayerAction.activate_card(MINE, InstanceId(1), effect_ref=ref)
    effect = PlayerAction.activate_effect(MINE, InstanceId(1), effect_ref=ref)

    ordered = sorted([effect, card], key=lambda a: a.canonical_state())
    assert ordered[0] is card and ordered[1] is effect
    assert "activate_card" < "activate_effect"


def test_20_merging_them_would_not_change_the_action_space(repository):
    """
    🟢 §5 — **합치면 action space 가 달라지는가: 아니다 (후보 기여 0).**

    ``activate_card`` 는 어떤 상태에서도 후보가 되지 않으므로 **후보 집합에
    기여하는 것이 0** 이다. 그래서 digest·tie-break·legal action count 가 그
    종류 때문에 달라지는 일은 없다.

    🔴 다만 **그것이 합쳐도 된다는 뜻은 아니다** — 합치면 ``effect_ref`` 필수성과
    검증기 분리(STRUCTURAL-119 의 수정)가 사라진다. §9 가 금지한 그대로이고,
    이 Phase 는 합치지 않는다 (``test_03``).
    """
    total_offered: collections.Counter = collections.Counter()
    for seed in (403, 404, 405):
        for deck in (DIGEST_DECK, SPELL_DECK):
            _, counts = walk_for_activation(repository, seed=seed, deck=deck)
            total_offered.update(counts["offered"])
    assert total_offered[PlayerActionKind.ACTIVATE_EFFECT] > 0
    #: 🔴 기여 0.
    assert total_offered[PlayerActionKind.ACTIVATE_CARD] == 0, dict(total_offered)


def test_21_the_simulator_carries_an_activation_through_the_fork(repository):
    """§5 — 탐색 사본도 발동을 **같은 종류로** 받아 간다."""
    duel, counts = walk_for_activation(repository, seed=406)
    assert counts["first_activation"] is not None

    fresh = opened_duel(repository, seed=406, deck=SPELL_DECK)
    guard = 0
    picked = None
    while not fresh.is_over and guard < 200:
        guard += 1
        if fresh.advance() is not None:
            continue
        legal = fresh.legal_actions(fresh.to_act)
        if not legal.allowed:
            break
        picked = next(
            (a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT),
            None,
        )
        if picked is not None:
            break
        fresh.apply(legal.allowed[0])

    assert picked is not None, "발동 후보에 닿지 못했다"
    before = fresh.state.state_hash()
    outcome = Simulator(fresh).simulate(picked, viewer=fresh.to_act)
    assert outcome.action.kind is PlayerActionKind.ACTIVATE_EFFECT
    #: 원본은 흔들리지 않는다.
    assert fresh.state.state_hash() == before


def test_22_hidden_information_and_the_board_are_untouched(repository):
    """§12 — 후보 생성·검증이 숨은 정보도 ``state_hash`` 도 RNG 도 안 건드린다."""
    duel = opened_duel(repository, seed=407, deck=SPELL_DECK)
    before_hash, before_rng = duel.state.state_hash(), repr(duel.state.rng)
    seat = duel.to_act

    validator = ActionValidator(duel.view(seat))
    hand = duel.state.player(seat).hand
    for card in hand:
        validator.validate(PlayerAction.activate_card(seat, card.instance_id))
    duel.legal_actions(seat)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng

    view = GameStateView.from_state(duel.state, viewer=seat)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(1 - seat).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_23_a_clone_resolves_the_same_activation(repository):
    """§10 — clone 독립성: 사본에서 발동해도 원본이 안 바뀐다."""
    state, source = hand_board(repository, POT_OF_GREED)
    refs = activatable_effects(POT_OF_GREED)
    action = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])

    copy = state.clone()
    assert copy.state_hash() == state.state_hash()
    before = state.state_hash()

    outcome = duel_activator().activate(copy, Chain(), action)
    assert outcome.status is ActivationStatus.ACTIVATED
    #: 원본은 그대로다.
    assert state.state_hash() == before


def test_24_the_same_seed_reproduces_the_same_activations(repository):
    """§12 — RNG 결정성: 같은 seed 는 같은 발동 횟수를 낸다."""

    def fingerprint(seed: int):
        duel, counts = walk_for_activation(repository, seed=seed)
        return (
            duel.state.state_hash(),
            counts["offered"][PlayerActionKind.ACTIVATE_EFFECT],
            counts["accepted"][PlayerActionKind.ACTIVATE_EFFECT],
        )

    for seed in (408, 409):
        assert fingerprint(seed) == fingerprint(seed), seed
    assert fingerprint(408) != fingerprint(409)


# ======================================================================
# D. §7 — 공식 용어와 프로젝트 용어
# ======================================================================


def test_25_the_official_rulebook_treats_it_as_one_action():
    """
    🔴 §7 — **공식 룰북은 "Activate a Card or Effect" 를 한 행동으로 적는다.**

    저장소에 이미 있는 공식 자료(`data/rules/structured/sd-rulebook-en-v10.json`)
    에서 읽는다 — 나무위키나 비공식 자료를 쓰지 않는다. 그래서 두 종류로 나눈 것은
    **공식 규칙의 구분이 아니라 엔진 내부의 구분**이다(``test_13``).
    """
    assert RULEBOOK.is_file(), RULEBOOK
    book = json.loads(RULEBOOK.read_text(encoding="utf-8"))

    #: 체인 설명이 "카드 **또는** 효과" 라고 적는다.
    assert "card or effect" in book["chain"]["notes"]

    #: 메인 페이즈의 행동 목록에도 하나로 들어 있다.
    phases = book["phases"]
    main1 = next(p for p in phases if p.get("engine_phase") == "MAIN1")
    assert "Activate a Card or Effect" in main1["main_actions"]

    #: 그리고 공식은 마법을 **카드**로, 몬스터 효과를 **효과**로 묶는다.
    speed1 = next(s for s in book["chain"]["spell_speeds"] if s["speed"] == 1)
    joined = " ".join(speed1["card_types"])
    assert "Spells" in joined and "Effect Monster" in joined


# ======================================================================
# E. §9 · §12 — AUDIT 범위와 불변
# ======================================================================


def test_26_this_phase_changed_no_production_file():
    """
    §9 — **AUDIT-ONLY: 이 Phase(3-F-22)는 production 을 한 줄도 바꾸지 않았다.**

    §9 의 다섯 조건 가운데 첫째("semantic contract 가 명백히 잘못되어 있다")가
    성립하지 않는다 — 계약이 코드에 적혀 있고 일관되다. 둘째("production
    consumer 가 잘못된 의미에 의존한다")도 성립하지 않는다 — AI 는 둘을 구분조차
    하지 않는다(``test_18``).

    .. note::
       **이 파일을 추가한 commit** 하나만 본다 (3-F-18 ~ 3-F-21 과 같은 방식).
       commit 전에는 base(``124fcfe``) ↔ 작업 트리로 되돌아간다.
    """
    PHASE_3F22_BASE = "124fcfe"

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
        changed = git("diff", "--stat", PHASE_3F22_BASE, "--", *PRODUCTION_ROOTS)
    assert changed.strip() == "", changed


def test_27_the_two_kinds_are_referenced_where_we_measured():
    """
    §1 — 참조 자리를 **전수**로 고정한다. 한쪽이 조용히 늘거나 줄면 깨진다.

    ``ACTIVATE_CARD`` 는 데이터 모델 · 검증기 · 실행기 표 · 후보 보류 설명에만
    나오고, **발동 계층에는 없다.**
    """
    card_files = {site[0] for site in kind_references("ACTIVATE_CARD")}
    effect_files = {site[0] for site in kind_references("ACTIVATE_EFFECT")}

    assert card_files == {
        "engine/action.py",
        "engine/action_execution.py",
        "engine/action_validation.py",
        "engine/duel.py",
    }, card_files
    assert effect_files == {
        "engine/action.py",
        "engine/action_execution.py",
        "engine/action_validation.py",
        "engine/activation.py",
        "engine/duel.py",
        "engine/response.py",
    }, effect_files

    #: 🔴 발동 계층과 응답 루프는 ``ACTIVATE_EFFECT`` 쪽에만 있다.
    assert effect_files - card_files == {
        "engine/activation.py",
        "engine/response.py",
    }
    assert card_files - effect_files == set()


def test_28_no_forbidden_restructuring_happened():
    """§9 — 금지 항목: 제거 · 병합 · 새 enum · 실행기/체인/AI 재설계 없음."""
    assert hasattr(PlayerActionKind, "ACTIVATE_CARD")
    assert hasattr(PlayerActionKind, "ACTIVATE_EFFECT")
    assert [f.name for f in dataclasses.fields(ChainLink)][:3] == [
        "sequence",
        "actor",
        "effect_ref",
    ]
    #: ``EffectActivator`` 의 입구가 그대로다.
    assert "def activate" in source_of("engine/activation.py")
    for forbidden in ("ActivationActionKind", "unify_activation", "ActivationRouter"):
        for path in production_files():
            relative = str(path.relative_to(PROJECT_ROOT))
            assert forbidden not in code_only(relative), (forbidden, relative)


def test_29_an_unregistered_kind_is_still_refused_by_the_executor(repository):
    """§10 — UNKNOWN / INVALID / FORBIDDEN 구분이 유지된다."""
    empty = ActionExecutor()
    assert empty.supported == frozenset()

    state, source = hand_board(repository, POT_OF_GREED)
    outcome = empty.execute(state, PlayerAction.activate_card(MINE, source))
    assert outcome.status.value != "executed"

    #: ``UNKNOWN`` 과 ``INVALID`` 는 다른 값이다.
    assert ActionValidity.UNKNOWN is not ActionValidity.INVALID
    #: 그리고 "금지" 는 또 다른 코드다.
    assert ValidationCode.EXECUTION_FORBIDDEN is not ValidationCode.RULE_NOT_IMPLEMENTED


def test_30_the_search_ranking_digest_is_unchanged(repository):
    """
    §12 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은 파일이
       못 박은 값을 기준으로 쓴다 (3-F-18 ~ 3-F-21 과 같은 방식).
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
