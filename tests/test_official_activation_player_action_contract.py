"""
Phase 3-F-23 — 공식 발동 용어 ↔ ``PlayerActionKind`` 대응 계약.

이 파일이 하는 일
-----------------
공식 규칙의 발동 표현과 **현재 Engine V1 의 ``PlayerActionKind``** 사이의 대응을
**계약 테스트로 고정**한다. 새 규칙을 구현하지 않는다 — 지금 무엇을 뜻하는지를
못 박는다.

🔴 대응표 (``test_01`` ~ ``test_06`` 이 각 줄을 잰다)
-----------------------------------------------------
=========================================  =====================  ==========
공식 표현                                    PlayerActionKind       실행 가능?
=========================================  =====================  ==========
"Activate a Card or Effect" (행동 **하나**)  ``ACTIVATE_EFFECT``    🟢 (마법)
"the activation of a card or effect" (체인)  ``ACTIVATE_EFFECT``    🟢
"activate a Spell/Trap Card"                🔴 ``ACTIVATE_EFFECT``  🟡 통상 마법만
"activate a monster effect"                 대응 없음               🔴 (등록 0장)
"카드 자체의 발동" (카드 수준 선언)            ``ACTIVATE_CARD``      🔴 미지원 경계
=========================================  =====================  ==========

🔴 이름이 공식과 거꾸로 보인다
------------------------------
공식 분류로 **마법 · 함정은 "카드"** 인데, 그 발동을 수행하는 것은
``ACTIVATE_EFFECT`` 다. ``ACTIVATE_CARD`` 라는 **이름**을 가진 쪽이 미지원이다.
그래서 이 Phase 는 ``ACTIVATE_CARD`` 의 docstring 을 정정했다 — 거기에
"(마법 · 함정의 발동)" 이라고 적혀 있었고, 그것이 **실제 계약과 어긋났다**
(``test_07`` · ``test_08``).

🟡 "어느 효과인지" 는 선언되어 있으나 아직 갈리지 않는다
-------------------------------------------------------
등록된 executable 효과는 **카드마다 하나**, 전부 ``ordinal=0`` 이다. 후보를
여럿으로 만드는 것은 **대상**이다 (``test_11``). 그래서 공식의 카드/효과 구분이
**아직 물리지 않는다.**

이 Phase 의 production 변경은 ``engine/action.py`` 의 **docstring 둘**뿐이다
(``test_24`` 가 AST 로 증명한다).
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
from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import ActionValidator, ActionValidity
from engine.activation import ActivationStatus
from engine.chain import Chain, ChainLink
from engine.duel import Duel
from engine.game_state_view import GameStateView
from engine.ids import EffectRef
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
MYSELF = "tests/test_official_activation_player_action_contract.py"
RULEBOOK = PROJECT_ROOT / "data/rules/structured/sd-rulebook-en-v10.json"

MINE, THEIRS = 0, 1

#: 실제 등록 카드 (공식 DB).
POT_OF_GREED = 55144522           # 통상 마법 · executable 1개
DIAN_KETO = 84257639              # 통상 마법 · executable 1개
COMPULSORY_EVACUATION = 94192409  # 함정 · executable 1개
LUSTER_DRAGON = 11091375          # 통상 몬스터 · 효과 없음
FEATHERMAN = 71925487             # 채우기용 통상 몬스터

DIGEST_DECK = [LUSTER_DRAGON] * 12 + [POT_OF_GREED] * 4 + [5915629] * 4
SPELL_DECK = [POT_OF_GREED] * 8 + [DIAN_KETO] * 8 + [LUSTER_DRAGON] * 4

#: ``Duel.apply`` 가 실행기를 거치지 않고 직접 처리하는 종류.
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
    source = textwrap.dedent(inspect.getsource(func))
    return ast.parse(source.replace(f"def {func.__name__}", "def f", 1))


def member_docstring(name: str) -> str:
    """
    enum 멤버의 docstring — **AST 로** 읽는다.

    ``Enum`` 멤버에는 ``__doc__`` 이 붙지 않으므로, 선언 바로 다음 줄의 문자열
    리터럴을 소스에서 꺼낸다.
    """
    tree = ast.parse(source_of("engine/action.py"))
    cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PlayerActionKind"
    )
    body = cls.body
    for index, node in enumerate(body):
        assigned = (
            node.targets[0].id
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            else None
        )
        if assigned != name:
            continue
        following = body[index + 1] if index + 1 < len(body) else None
        if (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ):
            return following.value.value
        return ""
    raise AssertionError(f"{name} 멤버를 찾지 못했다")


def executable_kinds() -> frozenset:
    return frozenset(duel_executor().supported) | DUEL_DIRECT_KINDS


def rulebook() -> dict:
    assert RULEBOOK.is_file(), RULEBOOK
    return json.loads(RULEBOOK.read_text(encoding="utf-8"))


# ======================================================================
# 판
# ======================================================================


def hand_board(repository, passcode: int, *, owner: int = MINE):
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
    cards = list(deck or SPELL_DECK)
    duel = Duel.start(repository, decks=(list(cards), list(cards)), seed=seed)
    offered: collections.Counter = collections.Counter()
    withheld: collections.Counter = collections.Counter()
    accepted: collections.Counter = collections.Counter()
    first = None
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
            if pick is not None and first is None:
                first = (chosen, step, len(duel.chain.links))
    return duel, {
        "offered": offered,
        "withheld": withheld,
        "accepted": accepted,
        "first": first,
    }


# ======================================================================
# A. §3 — 대응표의 각 줄
# ======================================================================


def test_01_the_official_phrase_is_one_action_but_the_engine_has_two_kinds():
    """
    🔴 대응표 1줄 — 공식은 **한 행동**, 엔진은 **두 종류**다.

    저장소의 공식 룰북에서 읽는다. 1:1 대응이 **아니라는 것**이 이 줄의 내용이다.
    """
    book = rulebook()
    main1 = next(p for p in book["phases"] if p.get("engine_phase") == "MAIN1")
    assert "Activate a Card or Effect" in main1["main_actions"]

    #: 공식 문구 하나에 엔진 종류가 둘 있다.
    engine_kinds = {PlayerActionKind.ACTIVATE_CARD, PlayerActionKind.ACTIVATE_EFFECT}
    assert len(engine_kinds) == 2
    #: 그리고 그중 **하나만** 실행 가능하다.
    assert engine_kinds & executable_kinds() == {PlayerActionKind.ACTIVATE_EFFECT}


def test_02_the_chain_is_created_only_by_activate_effect():
    """대응표 2줄 — 체인은 ``ACTIVATE_EFFECT`` 로만 쌓인다."""
    book = rulebook()
    assert "card or effect" in book["chain"]["notes"]

    assert RESPONDABLE == frozenset(
        {PlayerActionKind.ACTIVATE_EFFECT, PlayerActionKind.PASS}
    )
    assert PlayerActionKind.ACTIVATE_CARD not in RESPONDABLE

    #: ``apply`` dispatch 도 그쪽만 이름으로 집는다.
    dispatch = {
        node.attr
        for node in ast.walk(method_tree(Duel.apply))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "PlayerActionKind"
    }
    assert "ACTIVATE_EFFECT" in dispatch and "ACTIVATE_CARD" not in dispatch


def test_03_a_spell_card_activation_runs_as_activate_effect(repository):
    """
    🔴 대응표 3줄 — **공식으로 "카드의 발동" 인 것이 ``ACTIVATE_EFFECT`` 로 간다.**

    공식 룰북은 마법을 **"카드"** 로 묶는다. 그런데 엔진에서 그 발동을 수행하는
    것은 ``ACTIVATE_EFFECT`` 다. 이 한 줄이 이름이 거꾸로 보이는 이유다.
    """
    book = rulebook()
    speed1 = next(s for s in book["chain"]["spell_speeds"] if s["speed"] == 1)
    assert any("Spells" in text for text in speed1["card_types"])

    card = repository.get(POT_OF_GREED)
    assert card is not None and card.is_spell and not card.is_monster

    state, source = hand_board(repository, POT_OF_GREED)
    refs = activatable_effects(POT_OF_GREED)
    assert refs

    as_effect = PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    as_card = PlayerAction.activate_card(MINE, source)
    validator = validator_for(state)

    #: 🟢 마법 카드의 발동이 ``ACTIVATE_EFFECT`` 로 허가된다.
    assert validator.validate(as_effect).validity is ActionValidity.VALID
    #: 🔴 ``ACTIVATE_CARD`` 로는 허가되지 않는다.
    assert validator.validate(as_card).validity is ActionValidity.UNKNOWN

    outcome = duel_activator().activate(state, Chain(), as_effect)
    assert outcome.status is ActivationStatus.ACTIVATED
    assert len(outcome.chain.links) == 1


def test_04_there_is_no_monster_effect_activation_to_map(repository):
    """
    🔴 대응표 4줄 — "activate a monster effect" 에 **대응할 것이 없다.**

    공식은 몬스터 효과(Ignition · Trigger · Flip · Quick)를 "효과" 로 묶는데,
    등록된 효과 중 몬스터는 **0장**이다. 없는 것을 있다고 적지 않는다.
    """
    book = rulebook()
    names = {entry["name"] for entry in book["effect_types"]}
    #: 공식 쪽에는 네 종류가 적혀 있다.
    assert {"Ignition Effect", "Trigger Effect", "Flip Effect"} <= names

    from engine.effect.library import EFFECT_LIBRARY

    monsters = [
        entry
        for entry in EFFECT_LIBRARY
        if (repository.get(entry.definition.effect_ref.card_id) or None) is not None
        and repository.get(entry.definition.effect_ref.card_id).is_monster
    ]
    assert monsters == [], monsters

    #: 통상 몬스터는 발동 후보를 전혀 내지 않는다.
    assert activatable_effects(LUSTER_DRAGON) == ()


def test_05_activate_card_is_the_empty_seat_for_the_official_card_concept(repository):
    """
    대응표 5줄 — ``ACTIVATE_CARD`` 는 공식 개념을 가리키되 **지금 비어 있는 자리**다.

    빠진 규칙이 **이름으로 지목**되어 있다 — 막연한 "미구현" 이 아니다.
    """
    import engine.action_validation as av

    assert PlayerActionKind.ACTIVATE_CARD in av._MISSING_RULE
    assert (
        av._MISSING_RULE[PlayerActionKind.ACTIVATE_CARD]
        == "activation-timing (Phase 2-C/2-F)"
    )
    assert PlayerActionKind.ACTIVATE_CARD not in av._COMPLETE_RULES

    state, source = hand_board(repository, POT_OF_GREED)
    verdict = validator_for(state).validate(PlayerAction.activate_card(MINE, source))
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == "activation-timing (Phase 2-C/2-F)"
    #: 🔴 ``UNKNOWN`` 은 ``INVALID`` 가 아니다 — "규칙이 금지한다" 가 아니다.
    assert verdict.validity is not ActionValidity.INVALID


def test_06_one_official_term_does_not_map_to_one_kind():
    """
    §2 E — **1:1 이 아니다.** 추상이 갈리는 자리를 적는다.

    공식은 **발동되는 대상**(카드 또는 효과)을 이름으로 부르고, 엔진의 행위는
    **체인에 넣을 구체적 ``EffectRef``** 를 요구한다. 그래서 공식 "카드의 발동"
    하나가 엔진에서는 "그 카드의 효과 #0 의 발동" 이 된다 — 대상의 **정체**가
    다르다.
    """
    #: 엔진 쪽 요구: ``effect_ref`` 가 필수다.
    signature = inspect.signature(PlayerAction.activate_effect)
    assert signature.parameters["effect_ref"].default is inspect.Parameter.empty

    #: 그리고 ChainLink 가 들고 있는 것은 **효과**다 — 카드가 아니다.
    fields = [f.name for f in dataclasses.fields(ChainLink)]
    assert "effect_ref" in fields
    assert "card_id" not in fields

    #: 공식 문구 하나(行動) ↔ 엔진 종류 둘, 공식 대상(카드) ↔ 엔진 대상(효과).
    link_ref = EffectRef(POT_OF_GREED, 0)
    assert link_ref.card_id == POT_OF_GREED
    assert link_ref.ordinal == 0


# ======================================================================
# B. §6 — 정정한 docstring
# ======================================================================


def test_07_the_activate_card_docstring_no_longer_claims_spell_trap_activation():
    """
    🔴 §6 — **정정 대상이었던 문장이 사라졌다.**

    ``ACTIVATE_CARD`` 의 docstring 은 *"카드 자체를 발동한다 (마법 · 함정의
    발동)."* 이었다. 그런데 마법 · 함정의 발동을 실제로 수행하는 것은
    ``ACTIVATE_EFFECT`` 다(``test_03``). 그 문장이 남아 있으면 읽는 사람이
    **어느 종류를 넓혀야 하는지 틀리게 판단한다.**
    """
    doc = member_docstring("ACTIVATE_CARD")
    #: 🔴 어긋난 문장이 없다.
    assert "카드 자체를 발동한다 (마법 · 함정의 발동)." not in doc
    #: 그리고 실제 계약이 적혀 있다.
    assert "Engine V1" in doc
    assert "ACTIVATE_EFFECT" in doc
    assert "activation-timing (Phase 2-C/2-F)" in doc
    #: 공식 용어와 1:1 이 아니라는 사실도 적는다.
    assert "Activate a Card or Effect" in doc


def test_08_the_activate_effect_docstring_says_it_covers_card_activation():
    """§6 — ``ACTIVATE_EFFECT`` 쪽도 **지금 무엇을 맡는지** 적는다."""
    doc = member_docstring("ACTIVATE_EFFECT")
    assert "필수" in doc
    #: 마법·함정 카드의 발동까지 맡는다는 사실.
    assert "마법" in doc and "함정" in doc
    #: 그리고 "어느 효과인지" 가 아직 갈리지 않는다는 측정값.
    assert "ordinal=0" in doc


def test_09_both_docstrings_avoid_saying_the_two_are_the_same():
    """§6 — 둘을 **같은 것으로** 설명하지 않는다."""
    card_doc = member_docstring("ACTIVATE_CARD")
    effect_doc = member_docstring("ACTIVATE_EFFECT")
    assert card_doc and effect_doc
    assert card_doc != effect_doc
    for forbidden in ("같은 행위", "동일하다", "같다고 보면"):
        assert forbidden not in card_doc, forbidden
        assert forbidden not in effect_doc, forbidden
    #: 한쪽이 미지원이라는 사실이 ``ACTIVATE_CARD`` 쪽에만 있다.
    assert "유효한 행위가 아니다" in card_doc
    assert "유효한 행위가 아니다" not in effect_doc


# ======================================================================
# C. §2 — 두 종류의 현재 계약
# ======================================================================


def test_10_effect_ref_is_required_only_for_activate_effect():
    """§8 4 — ``effect_ref`` 필수 여부가 모델에서 갈린다."""
    import engine.action as action_module

    assert action_module._NEEDS_EFFECT_REF == frozenset(
        {PlayerActionKind.ACTIVATE_EFFECT}
    )
    assert PlayerActionKind.ACTIVATE_CARD in action_module._ALLOWS_EFFECT_REF
    assert PlayerActionKind.ACTIVATE_CARD not in action_module._NEEDS_EFFECT_REF

    with pytest.raises(TypeError):
        PlayerAction.activate_effect(MINE, None)  # type: ignore[call-arg]
    assert PlayerAction.activate_card(MINE, None).effect_ref is None


def test_11_the_effect_choice_never_actually_varies(repository):
    """
    🟡 §2 C — **"어느 효과인지" 는 선언되어 있으나 아직 갈리지 않는다.**

    executable 효과가 카드마다 **하나**이고 전부 ``ordinal=0`` 이다. 그래서
    현재 ``ACTIVATE_EFFECT`` 의 실질은 "카드 X 를 (대상 T 로) 발동" 이고, 후보를
    여럿으로 만드는 것은 **대상**이다.

    → 그래서 공식의 카드/효과 구분이 **아직 물리지 않는다**(``test_03`` 의 역설).
    """
    from engine.effect.library import EFFECT_LIBRARY

    per_card: collections.Counter = collections.Counter()
    ordinals: collections.Counter = collections.Counter()
    for entry in EFFECT_LIBRARY:
        if entry.executable:
            ref = entry.definition.effect_ref
            per_card[ref.card_id] += 1
            ordinals[ref.ordinal] += 1

    assert per_card, "executable 효과가 없다"
    #: 🔴 카드마다 하나씩, 전부 ordinal 0.
    assert set(per_card.values()) == {1}, dict(per_card)
    assert set(ordinals) == {0}, dict(ordinals)

    #: 그리고 후보를 여럿으로 만드는 것은 대상이다.
    duel_code = code_only("engine/duel.py")
    assert "target_combinations" in duel_code


def test_12_activate_card_reaches_neither_apply_nor_the_activator(repository):
    """§2 D · §8 6 — 후보도 아니고 ``apply`` 도 활성기도 통과하지 못한다."""
    duel = opened_duel(repository, seed=501, deck=SPELL_DECK)
    seat = duel.to_act
    hand = duel.state.player(seat).hand
    assert hand
    probe = PlayerAction.activate_card(seat, hand[0].instance_id)

    #: 후보에 없다.
    assert probe not in set(duel.legal_actions(seat).allowed)
    #: ``apply`` 가 거절하고 판이 안 바뀐다.
    before = duel.state.state_hash()
    step = duel.apply(probe)
    assert step.accepted is False
    assert step.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert duel.state.state_hash() == before

    #: 활성기도 **종류만 보고** 거절한다.
    state, source = hand_board(repository, POT_OF_GREED)
    outcome = duel_activator().activate(
        state, Chain(), PlayerAction.activate_card(MINE, source)
    )
    assert outcome.status is ActivationStatus.INVALID_ACTION
    assert "효과 발동이 아닙니다" in outcome.reason


def test_13_activate_card_appears_only_as_a_withheld_reason(repository):
    """§2 D — 이름만 있는 것이 아니라 **보류 사유로 쓰인다.**"""
    duel = opened_duel(repository, seed=502, deck=SPELL_DECK)
    seat = duel.to_act
    held = [
        w
        for w in duel.legal_actions(seat).withheld
        if w.kind is PlayerActionKind.ACTIVATE_CARD
    ]
    assert held, "activate_card 보류가 없다"
    assert held[0].reason
    assert held[0].missing == "activation-timing (Phase 2-C/2-F)"

    #: production 에서 ``PlayerAction.activate_card`` 를 만드는 자리는 한 곳이다.
    sites = []
    for path in production_files():
        relative = str(path.relative_to(PROJECT_ROOT))
        tree = ast.parse(code_only(relative))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "activate_card"
                and "PlayerAction" in ast.unparse(node.value)
            ):
                sites.append(relative)
    assert sites == ["engine/duel.py"], sites


# ======================================================================
# D. §8 — 실제 카드 사례 (둘 이상)
# ======================================================================


def test_14_two_real_spells_activate_through_the_same_kind(repository):
    """§8 — 실제 카드 **두 장**이 같은 종류로 체인까지 간다."""
    activator = duel_activator()
    for passcode in (POT_OF_GREED, DIAN_KETO):
        card = repository.get(passcode)
        assert card is not None and card.is_spell
        state, source = hand_board(repository, passcode)
        refs = activatable_effects(passcode)
        assert refs, passcode
        outcome = activator.activate(
            state,
            Chain(),
            PlayerAction.activate_effect(MINE, source, effect_ref=refs[0]),
        )
        assert outcome.status is ActivationStatus.ACTIVATED, passcode
        assert len(outcome.chain.links) == 1
        assert outcome.chain.links[0].effect_ref.card_id == passcode


def test_15_a_trap_is_withheld_by_a_deeper_missing_rule(repository):
    """
    🟡 §8 — 함정은 **더 아래 계층**의 빠진 규칙으로 막힌다.

    ``activate_card`` 의 ``activation-timing`` 과 **다른 문자열**이다 — 공식
    스크립트의 ``SetCode(EVENT_*)`` 가 ``EffectDefinition`` 에 없다는
    데이터 모델 문제를 지목한다.
    """
    card = repository.get(COMPULSORY_EVACUATION)
    assert card is not None and card.is_trap

    state, source = hand_board(repository, COMPULSORY_EVACUATION)
    refs = activatable_effects(COMPULSORY_EVACUATION)
    assert refs
    verdict = validator_for(state).validate(
        PlayerAction.activate_effect(MINE, source, effect_ref=refs[0])
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert "trap-activation-timing" in (verdict.missing_rule or "")
    assert verdict.missing_rule != "activation-timing (Phase 2-C/2-F)"


def test_16_a_real_duel_shows_the_mapping_in_action(repository):
    """§8 5 — 실제 듀얼에서 대응표가 그대로 보인다."""
    duel, counts = walk_for_activation(repository, seed=503)

    assert counts["offered"][PlayerActionKind.ACTIVATE_EFFECT] > 0
    assert counts["offered"][PlayerActionKind.ACTIVATE_CARD] == 0
    assert counts["withheld"][PlayerActionKind.ACTIVATE_CARD] > 0
    assert counts["accepted"][PlayerActionKind.ACTIVATE_EFFECT] > 0

    assert counts["first"] is not None
    action, step, links = counts["first"]
    assert action.kind is PlayerActionKind.ACTIVATE_EFFECT
    assert action.effect_ref is not None
    assert step.accepted and links == 1


# ======================================================================
# E. §7 — AI / Search 영향
# ======================================================================


def test_17_the_agent_layer_does_not_interpret_activation_terms():
    """
    🟢 §7 — AI 는 두 종류를 **이름으로 해석하지 않는다.**

    그래서 공식 용어를 잘못 읽을 자리가 production 에 없다.
    """
    for name in ("ACTIVATE_CARD", "ACTIVATE_EFFECT"):
        for path in sorted((PROJECT_ROOT / "agent").rglob("*.py")):
            relative = str(path.relative_to(PROJECT_ROOT))
            tree = ast.parse(code_only(relative))
            hits = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr == name
                and isinstance(node.value, ast.Name)
                and node.value.id == "PlayerActionKind"
            ]
            assert hits == [], (name, relative)


def test_18_the_search_never_treats_the_two_kinds_as_one():
    """
    §7 — 탐색이 **이름으로 같이 묶는** 코드가 없다. 받은 후보를 그대로 쓴다.

    ``canonical_state`` 의 첫 칸이 종류이므로, 만약 둘이 함께 나온다면 **다르게**
    정렬된다 — 같이 묶는 코드가 없다는 것이 그 보증이다.
    """
    search_code = code_only("agent/search.py")
    assert "legal.allowed" in search_code
    assert "canonical_state" in search_code

    #: .. note::
    #:    🔴 원래 ``"PlayerActionKind" not in search_code`` 로 쟀는데 **틀렸다** —
    #:    ``agent/search.py`` 는 그 enum 을 **import 한다**(형 표기용). "import
    #:    하지 않는다" 와 "멤버를 이름으로 집지 않는다" 는 다른 말이다. 측정해서
    #:    후자를 센다.
    def named_members(relative: str) -> set[str]:
        tree = ast.parse(code_only(relative))
        return {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "PlayerActionKind"
        }

    #: 🔴 탐색과 정책은 멤버를 **하나도** 집지 않는다.
    assert named_members("agent/search.py") == set()
    assert named_members("agent/policy.py") == set()
    #: 집는 곳도 발동 종류는 집지 않는다.
    assert named_members("agent/simulation.py") == {"PASS"}
    assert named_members("agent/heuristic.py") == {
        "NORMAL_SUMMON",
        "END_PHASE",
        "PASS",
    }

    #: 그리고 두 종류의 canonical 첫 칸이 다르다.
    ref = EffectRef(POT_OF_GREED, 0)
    from engine.ids import InstanceId

    card = PlayerAction.activate_card(MINE, InstanceId(1), effect_ref=ref)
    effect = PlayerAction.activate_effect(MINE, InstanceId(1), effect_ref=ref)
    assert card.canonical_state()[0] != effect.canonical_state()[0]


def test_19_the_digest_records_the_action_kind(repository):
    """§7 — digest 가 종류 이름을 그대로 담는다 — 그래서 혼동이 숨지 않는다."""
    duel = Duel.start(
        repository, decks=(list(SPELL_DECK), list(SPELL_DECK)), seed=504
    )
    transcript = DuelRunner(duel, (search_policy(duel), search_policy(duel))).run()
    kinds = {
        entry.action.kind.value
        for entry in transcript.entries
        if entry.action is not None
    }
    assert kinds, "기록이 비었다"
    #: 🔴 digest 에 들어가는 이름에 ``activate_card`` 가 없다.
    assert "activate_card" not in kinds


def test_20_the_legal_set_matches_the_documented_mapping(repository):
    """§7 — 문서의 대응과 **실제 후보 집합**이 일치한다."""
    offered: set = set()
    for seed in (505, 506):
        for deck in (DIGEST_DECK, SPELL_DECK):
            _, counts = walk_for_activation(repository, seed=seed, deck=deck)
            offered |= set(counts["offered"])

    #: 발동 쪽에서 나오는 것은 ``ACTIVATE_EFFECT`` 하나다.
    activation_kinds = offered & {
        PlayerActionKind.ACTIVATE_CARD,
        PlayerActionKind.ACTIVATE_EFFECT,
    }
    assert activation_kinds == {PlayerActionKind.ACTIVATE_EFFECT}, activation_kinds
    #: 그리고 후보로 나온 것은 전부 실행 가능하다.
    assert offered <= executable_kinds()


# ======================================================================
# F. §9 — 불변 조건
# ======================================================================


def test_21_the_board_the_rng_and_the_view_are_unchanged(repository):
    """§9 — ``state_hash`` · RNG · 숨은 정보 불변."""
    duel = opened_duel(repository, seed=507, deck=SPELL_DECK)
    before_hash, before_rng = duel.state.state_hash(), repr(duel.state.rng)
    seat = duel.to_act

    validator = ActionValidator(duel.view(seat))
    for card in duel.state.player(seat).hand:
        validator.validate(PlayerAction.activate_card(seat, card.instance_id))
    duel.legal_actions(seat)

    assert duel.state.state_hash() == before_hash
    assert repr(duel.state.rng) == before_rng

    view = GameStateView.from_state(duel.state, viewer=seat)
    for zone in (Zone.HAND, Zone.DECK):
        hidden = view.player(1 - seat).zone(zone)
        assert hidden.concealed is True and hidden.cards == ()


def test_22_the_same_seed_reproduces_the_same_activations(repository):
    """§9 — RNG 결정성."""

    def fingerprint(seed: int):
        duel, counts = walk_for_activation(repository, seed=seed)
        return (
            duel.state.state_hash(),
            counts["offered"][PlayerActionKind.ACTIVATE_EFFECT],
            counts["accepted"][PlayerActionKind.ACTIVATE_EFFECT],
        )

    for seed in (508, 509):
        assert fingerprint(seed) == fingerprint(seed), seed
    assert fingerprint(508) != fingerprint(509)


def test_23_engine_v1_was_not_widened():
    """
    §6 금지 항목 — 구현·확장·병합이 **하나도** 없다.

    enum 11개 그대로, 실행기 등록 그대로, 생성기 넷 그대로, 활성기 입구 그대로.
    """
    assert len(list(PlayerActionKind)) == 11
    assert duel_executor().supported == frozenset(
        {
            PlayerActionKind.NORMAL_SUMMON,
            PlayerActionKind.SPECIAL_SUMMON,
            PlayerActionKind.SET_MONSTER,
            PlayerActionKind.SET_SPELL_TRAP,
            PlayerActionKind.ATTACK,
        }
    )
    duel_code = code_only("engine/duel.py")
    for generator in (
        "_attack_actions",
        "_activation_actions",
        "_flow_actions",
        "_withheld_board_actions",
    ):
        assert generator in duel_code, generator
    for forbidden in (
        "_activate_card_actions",
        "ActivationTimingRule",
        "ActivationRouter",
    ):
        for path in production_files():
            relative = str(path.relative_to(PROJECT_ROOT))
            assert forbidden not in code_only(relative), (forbidden, relative)

    #: 활성기는 여전히 ``ACTIVATE_EFFECT`` 만 받는다.
    activation_code = code_only("engine/activation.py")
    assert "PlayerActionKind.ACTIVATE_EFFECT" in activation_code
    assert "PlayerActionKind.ACTIVATE_CARD" not in activation_code


def test_24_this_phase_changed_only_two_docstrings():
    """
    §6 — **production 변경은 ``engine/action.py`` 의 docstring 둘뿐이다.**

    문자열 리터럴을 지운 AST 가 base 와 **같다** — 실행되는 코드가 한 글자도
    바뀌지 않았다.

    .. note::
       **이 파일을 추가한 commit** 의 앞뒤를 비교한다 (3-F-18 ~ 3-F-22 와 같은
       방식). commit 전에는 base(``d3f70e6``) ↔ 작업 트리로 되돌아간다.
    """
    PHASE_3F23_BASE = "d3f70e6"
    CHANGED = ("engine/action.py",)

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
            before = git("show", f"{PHASE_3F23_BASE}:{relative}")
            after = source_of(relative)
        assert ast.dump(
            _StripStrings().visit(ast.parse(before))
        ) == ast.dump(_StripStrings().visit(ast.parse(after))), relative

    #: 그리고 그 파일 말고는 production 을 건드리지 않았다.
    if work:
        touched = git(
            "show", "--stat", "--format=", work[-1], "--", *PRODUCTION_ROOTS
        )
        for line in touched.splitlines():
            if "|" in line:
                assert line.split("|")[0].strip() in CHANGED, line


def test_25_the_search_ranking_digest_is_unchanged(repository):
    """
    §9 — 검색/AI digest 불변: 6판 611결정.

    .. note::
       digest 값을 베껴 적지 않는다 — 기존 pin 들을 AST 로 읽어 가장 많은 파일이
       못 박은 값을 기준으로 쓴다 (3-F-18 ~ 3-F-22 와 같은 방식).
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
