"""
Phase 6-K — **몬스터 효과의 발동 절차**. B3 하나만 다룬다.

    PlayerAction(ACTIVATE_EFFECT, effect_ref=EffectRef(37742478, 0))
        ↓  ActionValidator.validate(definitions=…)      ← 이번 Phase
    VALID
        ↓  ActivationTimingChecker.check                체인이 비면 통과
    VALID
        ↓  EffectActivator.can_activate
    UNKNOWN — "실행 구현이 등록되어 있지 않습니다" (ADR-006)

이 파일이 지키는 것
-------------------
**막는 것이 "규칙이 없다" 에서 "구현이 없다" 로 바뀌었다.** 그 둘은 다른
사실이고 (ADR-006), 바뀐 것은 전자뿐이다. 실제 효과 해결은 여전히 되지
않으며 이 파일은 그것을 **숨기지 않고 센다** (§L).

**카드 종류로 허가하지 않는다.** 몬스터라는 이유로 통과하는 길이 없고
(§C · §E), 분류를 적지 않은 효과는 Phase 6-K 이전과 **똑같이** 범위 밖이다.

**카드 ID 로 분기하지 않는다.** §O 가 production 경로를 AST 로 훑는다.

**기르수를 억지로 실행시키지 않았다** (§M). 그 카드의 ③ 은 실제로 기동
효과이지만 정의를 등록하지 않았고, 그래서 여전히 범위 밖이다.
"""

import ast
import json
import pathlib

import pytest

from engine.action import PlayerAction, PlayerActionKind
from engine.action_validation import (
    ACTIVATION_KINDS_IN_SCOPE,
    FACEDOWN_EFFECT_MISSING,
    IGNITION_ACTIVATION_ZONES,
    IGNITION_LOCATION_MISSING,
    MONSTER_ACTIVATION_MISSING,
    MONSTER_ACTIVATION_MISSING_BY_KIND,
    ActionValidator,
    ActionValidity,
    ValidationCode,
    activation_is_monster_ignition,
)
from engine.activation import ActivationStatus
from engine.activation_timing import (
    ActivationTiming,
    ActivationTimingChecker,
    classify_spell_speed,
)
from engine.chain import Chain, ChainLink
from engine.duel import ACTIVATION_SOURCE_ZONES, Duel
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectDefinitionRegistry,
    EffectProvenance,
)
from engine.effect.library import (
    EFFECT_LIBRARY,
    HONEST,
    POT_OF_GREED,
    definition_registry,
)
from engine.ids import EffectRef
from engine.priority import PriorityState
from engine.spell_activation import PLACEMENT_SOURCE_ZONES
from engine.state.game_state import GameState
from engine.vocabulary import ActivationKind, Phase, Position, Zone

from tests.conftest import requires_official_db, settle_chain

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MINE, THEIRS = 0, 1

#: 어니스트 — 등재된 **첫 몬스터 효과**. ① 이 기동 효과다.
HONEST_REF = EffectRef(HONEST, 0)
#: 잭나이츠 오르페골 기르수 — §11 의 카드. ③(``e[2]``) 이 기동 효과다.
GIRSU = 69811710
GIRSU_IGNITION_ORDINAL = 2
#: 엘리멘틀 히어로 페더맨 — 통상 몬스터. 효과가 없다.
FEATHERMAN = 21844576
#: 볼캐닉 에지 — 스크립트가 있는 효과 몬스터. **등재되지 않았다.**
VOLCANIC_SHELL = 17415895
LUSTER_DRAGON = 11091375


# ======================================================================
# 판 만들기
# ======================================================================


def board(
    repository,
    card_id: int = HONEST,
    *,
    zone: Zone = Zone.MZONE,
    position: Position = Position.FACEUP,
    phase: Phase = Phase.MAIN1,
    turn_player: int = MINE,
    fill_szone: int = 0,
):
    """몬스터 한 장이 놓인 판. 배치는 전부 실제 엔진이 한다."""
    deck = [LUSTER_DRAGON] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    instance = state.create_instance(
        card_id, owner=MINE, zone=zone, position=position
    )
    for _ in range(fill_szone):
        state.create_instance(
            POT_OF_GREED, owner=MINE, zone=Zone.SZONE, position=Position.FACEUP
        )
    state.turn.set_phase(phase)
    while state.turn.turn_player != turn_player:
        state.turn.begin_next_turn()
    state.turn.set_phase(phase)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(
            turn_player=state.turn.turn_player, phase=phase
        ),
    )
    return duel, instance


def ignition_action(instance, *, card_id: int = HONEST, ordinal: int = 0):
    return PlayerAction.activate_effect(
        actor=MINE,
        source=instance.instance_id,
        effect_ref=EffectRef(card_id, ordinal),
    )


def judged(duel, action, *, definitions):
    return ActionValidator(duel.view(MINE), definitions=definitions).validate(action)


def registry_declaring(kind, *, card_id: int = HONEST, ordinal: int = 0):
    """
    그 카드의 그 효과를 **손으로** 어떤 분류라고 선언한 등록소.

    실제 목록에는 ``IGNITION`` 하나뿐이므로, 나머지 다섯 분류의 거부 이유를
    확인하려면 선언을 만들어야 한다. **production 을 건드리지 않는다** —
    이 등록소는 이 테스트 안에서만 산다.
    """
    return EffectDefinitionRegistry(
        (
            EffectDefinition(
                effect_ref=EffectRef(card_id, ordinal),
                source_card_id=card_id,
                activation_kind=kind,
                provenance=EffectProvenance(note="시험용 선언"),
            ),
        )
    )


# ======================================================================
# A. 어휘 축 — 지어낸 이름이 없다
# ======================================================================


def test_a01_the_axis_is_exactly_the_rulebook_classifications():
    """
    축이 **넷**이고 룰북의 효과 분류 그대로다.

    **이름을 지어내지 않았다**는 것이 여기서 증명된다 — 룰북 구조화 데이터의
    ``effect_types`` 행 이름과 1:1 로 맞춘다.
    """
    assert [kind.value for kind in ActivationKind] == [
        "IGNITION", "TRIGGER", "FLIP", "QUICK"
    ]
    rulebook = json.loads(
        (
            PROJECT_ROOT / "data" / "rules" / "structured" / "sd-rulebook-en-v10.json"
        ).read_text(encoding="utf-8")
    )
    by_name = {row["name"]: row for row in rulebook["effect_types"]}
    expected = {
        ActivationKind.IGNITION: "Ignition Effect",
        ActivationKind.TRIGGER: "Trigger Effect",
        ActivationKind.FLIP: "Flip Effect",
        ActivationKind.QUICK: "Quick Effect",
    }
    assert set(expected) == set(ActivationKind)
    for kind, name in expected.items():
        assert name in by_name, name
        #: 룰북이 그 분류를 **발동하는 것**으로 적는다.
        assert by_name[name]["has_activation"] is True, name


def test_a02_the_axis_excludes_what_the_rulebook_excludes():
    """
    지속 효과와 마법 · 함정의 발동이 축에 **없다.**

    지속 효과는 룰북이 ``has_activation: false`` 라고 적고
    (RULE-EFFECT-001), 마법 · 함정의 발동은 카드 종류로 이미 판정된다.
    """
    values = {kind.value for kind in ActivationKind}
    assert "CONTINUOUS" not in values
    assert "ACTIVATE" not in values

    rulebook = json.loads(
        (
            PROJECT_ROOT / "data" / "rules" / "structured" / "sd-rulebook-en-v10.json"
        ).read_text(encoding="utf-8")
    )
    continuous = next(
        row for row in rulebook["effect_types"] if row["name"] == "Continuous Effect"
    )
    assert continuous["has_activation"] is False
    #: 룰북의 다섯 분류 중 발동하는 **넷**이 축이다.
    activating = {
        row["name"] for row in rulebook["effect_types"] if row["has_activation"]
    }
    assert len(activating) == len(ActivationKind) == 4


def test_a02b_the_edopro_suffix_split_is_not_in_the_axis():
    """
    🔴 **``_O`` / ``_F`` 접미사를 축에 넣지 않았다.**

    그 접미사의 뜻은 이 저장소의 공식 자료에 근거가 없다
    (``tests/test_effect_type_quick_audit.py`` 의 ``test_29`` · ``test_32``).
    근거 없는 구분을 축에 넣으면 그 뜻풀이가 엔진의 규칙처럼 굳는다.

    강제 · 임의 축은 ``TriggerRequirement`` 에 **따로** 있고, 그쪽은
    ``TriggerSpec`` 이 근거를 들고 온다 — 두 축을 섞지 않는다.
    """
    for value in (kind.value for kind in ActivationKind):
        assert not value.endswith(("_O", "_F")), value

    from engine.trigger import TriggerRequirement

    assert {member.name for member in TriggerRequirement} >= {
        "MANDATORY", "OPTIONAL"
    }
    #: 두 축이 **같은 열거형이 아니다.**
    assert {k.value for k in ActivationKind} & {
        m.value for m in TriggerRequirement
    } == set()


def test_a03_the_engine_table_agrees_with_the_rulebook_without_importing_it():
    """
    🔴 **``engine`` 이 ``rules`` 를 import 하지 않는다. 테스트가 대조한다.**

    ``engine/activation_timing.py`` 가 스펠 스피드 표에 대해 적어 둔 약속과
    같은 자리다. 여기서 대조하는 것은 둘이다 — 룰북이 기동 효과의 시점을
    **문장으로 확정했는가**, 그리고 유발 즉시 효과의 시점을 **적지 않았는가**.
    """
    for package in ("engine",):
        for path in sorted((PROJECT_ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(
                        not alias.name.split(".")[0] == "rules"
                        for alias in node.names
                    ), path.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] != "rules", path.name

    rulebook = json.loads(
        (
            PROJECT_ROOT / "data" / "rules" / "structured" / "sd-rulebook-en-v10.json"
        ).read_text(encoding="utf-8")
    )
    by_name = {row["name"]: row for row in rulebook["effect_types"]}

    ignition = by_name["Ignition Effect"]
    assert ignition["activation_timing"] == "your Main Phase"
    assert ignition["has_activation"] is True
    assert ignition["spell_speed"] == 1
    assert "RULE-EFFECT-002" in ignition["rules"]
    #: 엔진이 범위에 넣은 것이 **그 하나**다.
    assert ACTIVATION_KINDS_IN_SCOPE == frozenset({ActivationKind.IGNITION})

    quick = by_name["Quick Effect"]
    assert quick["activation_timing"] is None
    assert "activation_timing" in quick["not_stated"]
    #: 적히지 않은 것을 범위에 넣지 않았고, 거부 이유가 그 사실을 말한다.
    quick = MONSTER_ACTIVATION_MISSING_BY_KIND[ActivationKind.QUICK]
    assert "not_stated" in quick and "RULE-EFFECT-003" in quick

    #: 유발 · 플립도 근거 번호를 들고 있다.
    assert "RULE-EFFECT-004" in MONSTER_ACTIVATION_MISSING_BY_KIND[
        ActivationKind.TRIGGER
    ]
    assert "RULE-EFFECT-005" in MONSTER_ACTIVATION_MISSING_BY_KIND[
        ActivationKind.FLIP
    ]


def test_a04_every_kind_is_either_in_scope_or_has_a_reason():
    """
    분류 중 **어느 쪽에도 적히지 않은 것**이 없다.

    적지 않으면 그 분류는 조용히 범위 밖이 되고, 왜 막혔는지 아무도 모른다.
    모듈 적재 시점의 ``assert`` 가 이미 지키지만, 그 단언이 지워지면 이
    테스트가 잡는다.
    """
    covered = ACTIVATION_KINDS_IN_SCOPE | set(MONSTER_ACTIVATION_MISSING_BY_KIND)
    assert covered == set(ActivationKind)
    assert not (
        ACTIVATION_KINDS_IN_SCOPE & set(MONSTER_ACTIVATION_MISSING_BY_KIND)
    )


# ======================================================================
# B. 운반칸 — EffectDefinition 이 분류를 들고 다닌다
# ======================================================================


def test_b01_the_definition_carries_the_kind_and_refuses_a_string():
    """
    ``activation_kind`` 는 열거형이거나 ``None`` 이다. 문자열은 **거부**다.

    문자열을 받으면 오타가 조용히 "분류를 적지 않았다" 로 읽히고, 그러면
    범위 밖이 되는 이유가 거짓이 된다.
    """
    definition = EffectDefinition(
        effect_ref=EffectRef(1, 0),
        source_card_id=1,
        activation_kind=ActivationKind.IGNITION,
    )
    assert definition.activation_kind is ActivationKind.IGNITION
    assert definition.to_dict()["activation_kind"] == "IGNITION"

    with pytest.raises(EffectDefinitionError, match="ActivationKind"):
        EffectDefinition(
            effect_ref=EffectRef(1, 0), source_card_id=1, activation_kind="IGNITION"
        )


def test_b02_not_declared_is_not_a_classification():
    """
    ``None`` 은 **"적지 않았다"** 이고 ``to_dict`` 에 나타나지 않는다.

    ``activation`` 이 ``None`` 인 것과 같은 태도다 (정의 모듈의 설명).
    """
    definition = EffectDefinition(effect_ref=EffectRef(1, 0), source_card_id=1)
    assert definition.activation_kind is None
    assert "activation_kind" not in definition.to_dict()


def test_b03_the_kind_is_part_of_the_canonical_state():
    """
    판정을 바꾸는 값이므로 정규 표현에 **들어간다.**

    빠뜨리면 같은 카드의 서로 다른 효과가 같은 정의로 읽힌다.
    """
    plain = EffectDefinition(effect_ref=EffectRef(1, 0), source_card_id=1)
    ignition = EffectDefinition(
        effect_ref=EffectRef(1, 0),
        source_card_id=1,
        activation_kind=ActivationKind.IGNITION,
    )
    assert plain.canonical_state() != ignition.canonical_state()
    assert ActivationKind.IGNITION.value in ignition.canonical_state()


def test_b04_the_library_declares_the_kind_by_hand_for_exactly_one_effect():
    """
    등재 중 분류를 적은 것은 **둘**이고, 둘 다 **손으로** 적었다 (ADR-006).

    자동 변환이 **없다**는 사실이 여기서 고정된다 — 코퍼스의 4,106개 기동
    효과 중 등재된 것은 하나뿐이고, 4,173개 유발 등록 중 등재된 것도
    하나뿐이다.

    🔴 **Phase 6-V 에서 하나가 둘이 됐다** (어니스트 기동 + 기르수 유발).
    이 시험이 틀린 가정을 갖고 있었던 것이 아니라 6-K 시점에 실제로
    하나였다. 지키는 사실은 "**자동 변환이 없다**" 이고, 수가 아니라
    ``EffectSpec.effect_types`` 에서 자동으로 옮기지 않는다는 것이 요지다.
    """
    declared = {
        entry.definition.effect_ref: entry.definition.activation_kind
        for entry in EFFECT_LIBRARY
        if entry.definition.activation_kind is not None
    }
    assert declared == {
        HONEST_REF: ActivationKind.IGNITION,
        EffectRef(GIRSU, 0): ActivationKind.TRIGGER,
    }
    entry = next(e for e in EFFECT_LIBRARY if e.definition.effect_ref == HONEST_REF)
    #: 🔴 **Phase 6-L 에서 실행된다.** 6-K 시점에는 ``executable=False`` ·
    #: ``operations=()`` 였고 그것이 참이었다 — 막던 것은 "정의가 '이 효과의
    #: 카드' 를 가리킬 이름이 없다" 였고, 6-L 이 ``SELF_TARGET`` 으로 그
    #: 이름을 만들었다.
    #:
    #: 이 테스트가 지키는 사실은 **분류를 손으로 하나만 적었다**는 것이고
    #: (위 ``declared``), 그것은 그대로다.
    assert entry.executable is True
    assert len(entry.definition.operations) == 1
    assert entry.lua_file == "c37742478.lua"
    assert "EFFECT_TYPE_IGNITION" in entry.lua_excerpt


# ======================================================================
# C. 등록소를 주지 않으면 **아무것도 넓어지지 않는다**
# ======================================================================


def test_c01_without_a_definition_source_a_monster_is_still_out_of_scope(repository):
    """
    🔴 **Phase 6-K 이전과 글자 하나까지 같은 답**이다.

    ``ActionValidator(view)`` 는 기본값이 ``definitions=None`` 이고, 그러면
    분류를 읽을 길이 없다. 그때 몬스터는 ``MONSTER_ACTIVATION_MISSING`` 으로
    범위 밖이다 — 이것이 기존 동작이고, 바뀌지 않았다.
    """
    duel, instance = board(repository)
    verdict = judged(duel, ignition_action(instance), definitions=None)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.code is ValidationCode.RULE_NOT_IMPLEMENTED
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING


def test_c02_an_unregistered_effect_monster_is_out_of_scope(repository):
    """
    등록소를 줘도 **그 효과의 정의가 없으면** 범위 밖이다.

    "모른다" 로 가는 길 셋이 전부 같은 답으로 접힌다 — 등록소 없음 · 정의
    없음 · 분류 미기재. 접은 결과가 **넓어지지 않는다**는 것이 핵심이다.
    """
    duel, instance = board(repository, VOLCANIC_SHELL)
    verdict = judged(
        duel,
        ignition_action(instance, card_id=VOLCANIC_SHELL),
        definitions=definition_registry(),
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING


def test_c02b_a_normal_monster_is_refused_even_earlier(repository):
    """
    🔴 **통상 몬스터는 더 앞에서 막힌다** — 그리고 이유가 다르다.

    페더맨은 스크립트가 없어 ``effect_count == 0`` 이고, 그러면 "몇 번째
    효과" 라는 질문에 답할 수 없다 (``CardDefinitionView.
    effects_are_addressable``). 그 거부는 Phase 6-K 이전부터 있던 것이고
    **분류 축과 무관하다** — 측정해서 구분해 둔다.
    """
    duel, instance = board(repository, FEATHERMAN)
    verdict = judged(
        duel,
        ignition_action(instance, card_id=FEATHERMAN),
        definitions=definition_registry(),
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule != MONSTER_ACTIVATION_MISSING
    assert "shared-library" in verdict.missing_rule
    card = duel.view(MINE).find(instance.instance_id)
    assert card.definition.effect_count == 0


def test_c03_a_definition_without_a_kind_is_not_read_as_ignition(repository):
    """
    분류를 **적지 않은** 정의가 기동 효과로 읽히지 않는다.

    적지 않은 것을 어느 분류로도 읽지 않는다 — 그러면 12,702장이 조용히
    기동 효과가 된다.
    """
    duel, instance = board(repository)
    registry = EffectDefinitionRegistry(
        (EffectDefinition(effect_ref=HONEST_REF, source_card_id=HONEST),)
    )
    verdict = judged(duel, ignition_action(instance), definitions=registry)
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING


# ======================================================================
# D. 기동 효과 — 범위 안이고, 요구가 둘이다
# ======================================================================


@pytest.mark.real_card
def test_d01_the_ignition_effect_of_a_face_up_monster_is_valid(repository):
    """
    **이 Phase 의 중심 측정값** — 어니스트 ① 이 ``VALID`` 를 받는다.

    공식 텍스트: 「①: 자신 메인 페이즈에 발동할 수 있다. 필드의 앞면 표시의
    이 카드를 패로 되돌린다.」 요구가 그 문장 그대로다 (RULE-EFFECT-002).
    """
    duel, instance = board(repository)
    action = ignition_action(instance)
    verdict = judged(duel, action, definitions=definition_registry())
    assert verdict.validity is ActionValidity.VALID
    assert verdict.code is ValidationCode.OK
    #: 🔴 ``VALID`` 는 "구현이 있다" 가 아니다 (ADR-006). §L 이 그것을 센다.


@pytest.mark.real_card
def test_d02_the_predicate_needs_both_the_card_type_and_the_effect_kind(repository):
    """
    ``activation_is_monster_ignition`` 이 **둘 다** 본다.

    분류만 보면 마법 정의에 잘못 적힌 ``IGNITION`` 이 몬스터 경로로 들어오고,
    카드 종류만 보면 "몬스터라서 허가" 가 된다 (§3-6 금지).
    """
    duel, instance = board(repository)
    validator = ActionValidator(duel.view(MINE), definitions=definition_registry())
    context = validator.context_for(ignition_action(instance))

    assert activation_is_monster_ignition(
        validator.view, context, instance.instance_id, ActivationKind.IGNITION
    )
    #: 분류가 없으면 거짓 — 몬스터인 것만으로는 되지 않는다.
    assert not activation_is_monster_ignition(
        validator.view, context, instance.instance_id, None
    )
    for kind in ActivationKind:
        if kind is not ActivationKind.IGNITION:
            assert not activation_is_monster_ignition(
                validator.view, context, instance.instance_id, kind
            ), kind


@pytest.mark.real_card
def test_d03_a_spell_declared_ignition_does_not_take_the_monster_path(repository):
    """
    마법 정의에 ``IGNITION`` 이 적혀 있어도 **마법 경로**로 간다.

    같은 질문에 답하는 자리가 둘이 되지 않게 하는 것이 ``is_monster`` 검사다.
    """
    deck = [LUSTER_DRAGON] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    spell = state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
    )
    action = PlayerAction.activate_effect(
        actor=MINE, source=spell.instance_id, effect_ref=EffectRef(POT_OF_GREED, 0)
    )
    validator = ActionValidator(
        duel.view(MINE),
        definitions=registry_declaring(
            ActivationKind.IGNITION, card_id=POT_OF_GREED
        ),
    )
    context = validator.context_for(action)
    assert not activation_is_monster_ignition(
        validator.view, context, spell.instance_id, ActivationKind.IGNITION
    )
    #: 마법 경로는 그대로 통과한다 — 패의 통상 마법이다.
    assert validator.validate(action).validity is ActionValidity.VALID


# ======================================================================
# E. 분류별로 이유가 다르다
# ======================================================================


@pytest.mark.parametrize(
    "kind",
    [k for k in ActivationKind if k not in ACTIVATION_KINDS_IN_SCOPE],
)
def test_e01_each_other_kind_is_refused_with_its_own_reason(repository, kind):
    """
    기동이 아닌 네 분류(여섯 중 다섯)가 **각자의 이유**로 범위 밖이다.

    한 문장으로 묶으면 어느 쪽을 고쳐야 하는지 알 수 없고, 그것이
    ``MONSTER_ACTIVATION_MISSING`` 한 줄이 안고 있던 문제였다.
    """
    duel, instance = board(repository)
    verdict = judged(
        duel, ignition_action(instance), definitions=registry_declaring(kind)
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING_BY_KIND[kind]
    assert verdict.missing_rule != MONSTER_ACTIVATION_MISSING
    assert kind.value in verdict.notes[0]


def test_e02_the_reasons_are_all_different_strings():
    """
    이유 문장이 **분류끼리 하나도 겹치지 않는다** — 셋이고 셋 다 다르다.

    겹치면 "어느 쪽을 고쳐야 하는가" 를 다시 알 수 없게 된다.
    """
    reasons = MONSTER_ACTIVATION_MISSING_BY_KIND
    assert len(reasons) == 3
    assert len(set(reasons.values())) == 3
    for reason in reasons.values():
        assert reason != MONSTER_ACTIVATION_MISSING


# ======================================================================
# F. 자리와 표시 형식 — ``FALSE`` 가 아니라 ``UNKNOWN``
# ======================================================================


@pytest.mark.real_card
@pytest.mark.parametrize("zone", [Zone.GRAVE, Zone.EMZONE, Zone.HAND])
def test_f01_an_ignition_effect_elsewhere_is_unknown_not_forbidden(repository, zone):
    """
    메인 몬스터 존이 아니면 ``UNKNOWN`` 이다. **금지가 아니다.**

    실제 규칙에는 묘지나 패에서 발동하는 기동 효과가 있고, 없는 것은 효과마다
    발동 위치를 적는 칸이다 (``SetRange(LOCATION_*)``).
    """
    duel, instance = board(repository, zone=zone, position=Position.FACEUP)
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == IGNITION_LOCATION_MISSING
    assert zone.value in verdict.notes[0]


def test_f02_the_extra_monster_zone_is_deliberately_not_in_scope():
    """
    🔴 EMZ 를 범위에 **넣지 않은** 것이 선택이고, 그 선택이 적혀 있다.

    공식 상수 ``LOCATION_MZONE`` 이 EMZ 를 포함하는지 이 저장소에서 확인된
    바가 없고, ``Zone`` 은 둘을 다른 존으로 가른다. 확인되지 않은 대응을
    선언하면 그것이 규칙처럼 굳는다.
    """
    assert IGNITION_ACTIVATION_ZONES == frozenset({Zone.MZONE})
    assert Zone.EMZONE not in IGNITION_ACTIVATION_ZONES
    #: 그래도 **후보 출발지에서는 빼지 않는다** — 막는 이유가 기록으로 남는다.
    assert Zone.EMZONE in ACTIVATION_SOURCE_ZONES


@pytest.mark.real_card
def test_f03_a_face_down_monster_is_unknown_with_its_own_reason(repository):
    """
    뒷면이면 ``UNKNOWN`` 이고 이유가 **자리 문제와 다르다.**

    뒷면 몬스터의 효과가 왜 유효하지 않은지를 적은 계층이 이 엔진에 없다.
    """
    duel, instance = board(
        repository, position=Position.FACEDOWN_DEFENSE
    )
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == FACEDOWN_EFFECT_MISSING
    assert verdict.missing_rule != IGNITION_LOCATION_MISSING


# ======================================================================
# G. 규칙이 **금지**하는 것은 INVALID 다
# ======================================================================


@pytest.mark.real_card
def test_g01_the_opponents_turn_is_a_refusal_not_an_unknown(repository):
    """
    상대 턴의 기동 효과는 ``INVALID`` 다 — 룰북이 "**your** Main Phase"
    라고 적는다 (RULE-EFFECT-002).
    """
    duel, instance = board(repository, turn_player=THEIRS)
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.NOT_TURN_PLAYER
    assert "RULE-EFFECT-002" in verdict.reason


@pytest.mark.real_card
@pytest.mark.parametrize("phase", [Phase.BATTLE, Phase.END, Phase.STANDBY])
def test_g02_outside_the_main_phase_is_a_refusal(repository, phase):
    """메인 페이즈가 아니면 ``INVALID`` 다 (RULE-EFFECT-002)."""
    duel, instance = board(repository, phase=phase)
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.INVALID
    assert verdict.code is ValidationCode.WRONG_PHASE


@pytest.mark.real_card
def test_g03_main_phase_two_is_also_the_main_phase(repository):
    """메인 페이즈 2 도 메인 페이즈다 — 조항이 "Main Phase" 라고만 적는다."""
    duel, instance = board(repository, phase=Phase.MAIN2)
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.VALID


# ======================================================================
# H. 마법 · 함정 경로가 **변하지 않았다**
# ======================================================================


@pytest.mark.real_card
def test_h01_the_normal_spell_still_runs_end_to_end(repository):
    """
    욕망의 항아리가 그대로 발동되고 해결된다 — 2장 드로우.

    이 Phase 가 마법 경로를 **건드리지 않았다**는 것이 여기서 증명된다.
    """
    deck = [LUSTER_DRAGON] * 20
    state = GameState.create(repository, decks=(list(deck), list(deck)), seed=1)
    spell = state.create_instance(POT_OF_GREED, owner=MINE, zone=Zone.HAND)
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=Phase.MAIN1),
    )
    before_deck = len(duel.state.player(MINE).deck)
    candidates = [
        action
        for action in duel.legal_actions(MINE).allowed
        if action.kind is PlayerActionKind.ACTIVATE_EFFECT
        and action.effect_ref == EffectRef(POT_OF_GREED, 0)
    ]
    assert len(candidates) == 1
    assert duel.apply(candidates[0]).accepted
    settle_chain(duel)
    assert len(duel.state.player(MINE).deck) == before_deck - 2
    assert duel.state.find_instance(spell.instance_id).zone is Zone.GRAVE


# ======================================================================
# I. 놓을 자리를 요구하지 **않는다**
# ======================================================================


@pytest.mark.real_card
def test_i01_a_full_spell_trap_zone_does_not_block_a_monster_effect(repository):
    """
    마법 & 함정 존이 꽉 차 있어도 기동 효과는 ``VALID`` 다.

    기동 효과의 발동은 카드를 어디에도 놓지 않는다 — RULE-SPELLTRAP-002 의
    "placing it face-up on the field" 는 마법 · 함정의 절차다. 빈 칸을
    요구하면 규칙이 금지하지 않는 것을 금지한다는 거짓이 된다.
    """
    duel, instance = board(repository, fill_szone=5)
    assert len(
        [c for c in duel.state.player(MINE).zone(Zone.SZONE) if c is not None]
    ) == 5
    verdict = judged(
        duel, ignition_action(instance), definitions=definition_registry()
    )
    assert verdict.validity is ActionValidity.VALID


def test_i02_the_placement_zones_do_not_include_the_monster_zones():
    """
    발동 배치가 있는 자리는 **패와 마법 & 함정 존 둘**이다.

    몬스터 존이 거기 있으면 ``place`` 가 "패에 없다" 로 실패하고, 그때는
    비용과 체인 링크가 이미 지나간 뒤여서 되돌릴 수 없다 (ADR-008).
    """
    assert PLACEMENT_SOURCE_ZONES == frozenset({Zone.HAND, Zone.SZONE})
    for zone in (Zone.MZONE, Zone.EMZONE, Zone.GRAVE):
        assert zone not in PLACEMENT_SOURCE_ZONES


@pytest.mark.real_card
def test_i03_an_activation_from_the_monster_zone_places_nothing(repository):
    """
    ``_place_activated`` 가 몬스터 존의 발동에 ``None`` 을 돌려준다.

    카드 종류를 보지 않고 **자리**를 본다 — 어느 자리에 배치가 있는가는
    배치 계층이 적어 둔다.
    """
    duel, instance = board(repository)
    assert duel._place_activated(ignition_action(instance)) is None
    #: 판이 **바뀌지 않았다** — 묻기만 했다.
    assert duel.state.find_instance(instance.instance_id).zone is Zone.MZONE
    assert duel.pending_spells == ()


# ======================================================================
# J. 체인이 열려 있으면 **여전히 막힌다**
# ======================================================================


@pytest.mark.real_card
def test_j01_the_spell_speed_gate_is_untouched(repository):
    """
    🔴 이 Phase 는 스펠 스피드를 **건드리지 않았다.**

    체인이 비어 있으면 그 관문이 애초에 걸리지 않고 (그것이 B3 의 이유
    문장이 체인 1 에 적용되지 않는다는 실측이다), 체인이 열려 있으면
    몬스터는 여전히 ``UNKNOWN`` 이다. 그래서 새 경로는 **체인 1 전용**이다.
    """
    duel, instance = board(repository)
    action = ignition_action(instance)
    checker = ActivationTimingChecker(duel.view(MINE))

    empty = checker.check(
        ActivationTiming(Chain(), duel.priority, set_this_turn=None), action
    )
    assert empty.validity is ActionValidity.VALID
    assert "체인이 비어 있어" in empty.reason

    opened = Chain().push(
        ChainLink(sequence=0, actor=THEIRS, effect_ref=EffectRef(POT_OF_GREED, 0))
    )
    responding = checker.check(
        ActivationTiming(opened, duel.priority, set_this_turn=None), action
    )
    assert responding.validity is ActionValidity.UNKNOWN
    assert "스펠 스피드" in responding.reason

    #: 카드 수준 분류는 **여전히 모른다** — 그 입도 문제는 풀지 않았다.
    card = duel.view(MINE).find(instance.instance_id)
    assert classify_spell_speed(card.definition).speed is None


# ======================================================================
# K. 후보가 생기지 않는다 — 등록은 실행 허가가 아니다
# ======================================================================


@pytest.mark.real_card
def test_k01_the_monster_zone_is_now_an_activation_source(repository):
    """
    몬스터 존이 발동 출발지에 들어왔다. **거르지 않고 내보낸다.**

    보지 않으면 어떤 관문도 판정할 기회를 얻지 못한다 — 세트된 함정을
    출발지에 남겨 둔 것과 같은 이유다 (Phase 3-E-14).
    """
    duel, instance = board(repository)
    sources = duel._activation_sources(MINE)
    assert instance.instance_id in {card.instance_id for card in sources}


@pytest.mark.real_card
def test_k02_the_candidate_appears_once_the_implementation_exists(repository):
    """
    🔴 **Phase 6-L 에서 후보가 생긴다.**

    6-K 시점에는 ``activatable_effects`` 가 ``executable`` 만 돌려주고
    어니스트 ① 이 거짓이어서 후보가 **0건**이었다. 그것이 ADR-006 의
    구분("규칙이 허락한다" ≠ "우리가 할 수 있다")이 실제로 걸린 자리였고,
    6-L 이 구현 쪽을 채웠다.

    🔴 **그 구분이 없어진 것이 아니다** — 등재되지 않은 몬스터 효과는
    여전히 후보가 아니다 (``test_m02`` 의 기르수).
    """
    duel, instance = board(repository)
    allowed = duel.legal_actions(MINE).allowed
    candidates = [a for a in allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT]
    assert len(candidates) == 1
    assert candidates[0].source == instance.instance_id
    assert candidates[0].effect_ref == HONEST_REF
    #: **대상이 없다** — 자기 참조는 대상 지정이 아니다 (Phase 6-L).
    assert candidates[0].targets == ()
    #: 적법성은 6-K 가 열었고, 그대로다.
    assert judged(
        duel, ignition_action(instance), definitions=definition_registry()
    ).validity is ActionValidity.VALID


# ======================================================================
# L. 막는 것이 구현으로 옮겨졌고 (6-K), 그 구현이 생겼다 (6-L)
# ======================================================================


@pytest.mark.real_card
def test_l01_all_three_gates_now_open(repository):
    """
    🔴 **6-K 의 측정값이 6-L 에서 다시 움직였다.**

    6-K 에서는 세 관문 중 앞의 둘이 열리고 셋째(``can_activate``)가
    ``registered effect implementation`` 으로 막았다. 그것이 그 Phase 의
    측정값이었고 참이었다.

    6-L 이 그 구현을 채웠으므로 (``SELF_TARGET`` — 정의가 "이 효과의 카드"
    를 가리킬 이름) **셋이 전부 열린다.** 두 사실을 한 자리에서 적는다:
    막던 이유가 규칙이 아니었고 (6-K), 구현도 아니게 되었다 (6-L).
    """
    duel, instance = board(repository)
    action = ignition_action(instance)
    gate = duel._activation_gate(
        action,
        validator=ActionValidator(
            duel.view(MINE), definitions=duel._activator.definitions
        ),
        selections=(),
    )
    assert gate.validity is ActionValidity.VALID, gate.reason
    #: 🔴 그래도 ``MONSTER_ACTIVATION_MISSING`` 은 **여전히 쓰인다** —
    #: 분류를 적지 않은 몬스터 효과에. 6-K 가 만든 구분이 살아 있다.
    assert MONSTER_ACTIVATION_MISSING
    other_duel, other = board(repository, VOLCANIC_SHELL)
    unregistered = judged(
        other_duel,
        ignition_action(other, card_id=VOLCANIC_SHELL),
        definitions=definition_registry(),
    )
    assert unregistered.missing_rule == MONSTER_ACTIVATION_MISSING


@pytest.mark.real_card
def test_l02_activation_puts_a_link_on_the_chain_and_changes_nothing_else(
    repository,
):
    """
    🔴 **발동과 해결은 다른 일이다** (6-K 가 ``UNAUTHORIZED`` 로 멈췄던 자리).

    ``activate`` 가 성공하면 체인 링크가 하나 생기고, **판은 그대로다** —
    카드가 패로 돌아가는 것은 해결의 일이다 (RULE-CHAIN-001 이 그 사이에
    상대의 응답 기회를 둔다).
    """
    duel, instance = board(repository)
    action = ignition_action(instance)
    before_hand = len(duel.state.player(MINE).hand)

    result = duel._activator.activate(duel.state, Chain(), action, selections=())
    assert result.activated, result.reason
    assert result.status is ActivationStatus.ACTIVATED
    assert result.code is ValidationCode.OK
    assert len(result.chain) == 1
    assert result.link is not None
    assert result.link.effect_ref == HONEST_REF
    #: 허가는 발동기가 스스로 검증기에 물어서 받았다 (등록소가 넘어간다).
    assert result.authorization.validity is ActionValidity.VALID

    #: 🔴 **발동만으로는 판이 바뀌지 않는다.**
    assert duel.state.find_instance(instance.instance_id).zone is Zone.MZONE
    assert len(duel.state.player(MINE).hand) == before_hand
    #: 비용이 없으므로 지불 델타도 없다.
    assert result.deltas == ()


@pytest.mark.real_card
def test_l03_apply_accepts_and_opens_the_response_window(repository):
    """
    ``Duel.apply`` 가 받는다 — 그리고 **거기서 끝나지 않는다.**

    6-K 에서는 같은 호출이 거절되었다. 지금은 체인 1 이 쌓이고 상대의
    응답 창이 열린다 (RULE-CHAIN-001). 해결은 ``settle_chain`` 이 한다.
    """
    duel, instance = board(repository)
    step = duel.apply(ignition_action(instance))
    assert step.accepted, step.reason
    assert len(duel.chain) == 1
    assert duel.priority.is_open
    assert duel.state.find_instance(instance.instance_id).zone is Zone.MZONE


@pytest.mark.real_card
def test_l04_the_activation_places_nothing_with_real_data(repository):
    """
    🔴 **배치 없는 발동이 실제 데이터로 끝까지 간다.**

    6-K 는 이 자리를 확인하려고 테스트 안에서만 사는 구현 등록소를 만들어야
    했다 — ``_apply_activation`` 의 ``if placed is not None`` 관문이 실제
    데이터로는 닿지 않았기 때문이다 (``executable=False``). 6-L 에서 그
    관문이 **진짜로 닿는다.** 시험용 권한은 더 이상 필요하지 않고, 그래서
    쓰지 않는다.
    """
    duel, instance = board(repository)
    action = next(
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    step = duel.apply(action)
    assert step.accepted, step.reason

    #: ② 체인 링크가 **하나** 생겼다.
    assert len(duel.chain) == 1
    assert duel.chain.links[0].effect_ref == HONEST_REF
    #: ③ **아무것도 놓이지 않았다** — 치울 것도 없다.
    assert duel.pending_spells == ()
    assert duel.state.find_instance(instance.instance_id).zone is Zone.MZONE
    #: 마법 & 함정 존에 아무것도 들어가지 않았다.
    assert [
        card for card in duel.state.player(MINE).zone(Zone.SZONE) if card is not None
    ] == []
    #: ⑤ 상대의 응답 창이 열렸다.
    assert duel.priority.is_open

    #: ④ 해결 뒤에도 **묘지로 가지 않는다** — 마법이 아니다. 패로 간다.
    settle_chain(duel)
    assert duel.state.find_instance(instance.instance_id).zone is Zone.HAND


@pytest.mark.real_card
def test_l05_the_candidate_list_and_the_activator_read_the_same_list(repository):
    """
    🔴 6-K 가 적어 둔 사실을 **정정한다.**

    6-K 의 ``test_l04`` 주석은 "``legal_actions`` 가 주입된 발동기의
    ``lookup`` 을 보지 않는다" 고 적었다. **절반만 맞다.**

    ========================================  ==========================
    ``activatable_effects`` (모듈 수준 목록)    후보를 **좁힌다**
    주입된 발동기의 ``lookup``                 ``_activation_gate`` 의 셋째
                                              관문에서 다시 **좁힌다**
    ========================================  ==========================

    그래서 둘 중 어느 쪽도 후보를 **넓히지 못한다** — 모듈 목록에 없는
    효과는 주입으로 켤 수 없고, 주입한 발동기에 구현이 없으면 모듈 목록에
    있어도 후보가 되지 않는다. 아래가 그 뒤쪽을 실측한다.

    6-K 가 그 사실을 반만 적은 탓에 ``test_l04`` 가 ``_apply_activation``
    을 직접 불러야 했다. 6-L 에서는 실제 데이터로 ``apply`` 가 지나므로
    그 우회가 없어졌다.
    """
    from engine.activation import EffectActivator
    from engine.effect.executor import EffectImplementationRegistry
    from engine.effect.library import definition_registry as library_definitions

    duel, instance = board(repository)
    before = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(before) == 1

    #: 구현을 **하나도** 등록하지 않은 발동기를 주입한다.
    duel._activator = EffectActivator(
        library_definitions(), EffectImplementationRegistry()
    )
    after = [
        a
        for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    #: 🔴 후보가 **사라진다** — 셋째 관문이 주입된 목록을 읽는다.
    assert after == []
    #: 손으로 만들어 넣어도 거절된다.
    assert not duel.apply(before[0]).accepted


# ======================================================================
# M. 기르수 — 억지로 실행시키지 않는다
# ======================================================================


@requires_official_db
@pytest.mark.real_card
def test_m01_girsu_really_has_an_ignition_effect_in_the_monster_zone(repository):
    """
    **§11 기르수.** ③(``e[2]``) 이 실제로 ``EFFECT_TYPE_IGNITION`` 이고
    ``SetRange(LOCATION_MZONE)`` 이다 — 즉 이 Phase 의 범위 **모양**이다.
    """
    from analysis.effect_analyzer import EffectAnalyzer

    card = repository.get(GIRSU)
    assert card is not None and card.is_monster
    blocks = card.script.effects
    assert blocks[GIRSU_IGNITION_ORDINAL].effect_types == ["IGNITION"]
    assert list(blocks[GIRSU_IGNITION_ORDINAL].ranges) == ["MZONE"]

    #: 그런데 하는 일이 ``special_summon`` 이고 토큰이다 — 6-J 의 B2 다.
    analysis = EffectAnalyzer(repository).analyze(card)
    ordinal_of = {id(spec): index for index, spec in enumerate(blocks)}
    ignition = next(
        effect
        for effect in analysis.effects
        if ordinal_of.get(id(effect.raw)) == GIRSU_IGNITION_ORDINAL
    )
    assert {action.kind.value for action in ignition.actions} == {"special_summon"}
    #: 그리고 "1턴에 1번" 이 붙어 있다 — 세는 자리가 효과마다 없다.
    assert blocks[GIRSU_IGNITION_ORDINAL].count_limit


@requires_official_db
@pytest.mark.real_card
def test_m02_girsu_is_not_forced_to_work(repository):
    """
    🔴 **기르수를 억지로 실행시키지 않았다** (§11 금지).

    🔴 **Phase 6-V 가 기르수 ①(``e[0]``, 유발)을 등재했다.** 그런데 이
    시험이 묻는 것은 ③(``e[2]``, **기동**)이고 6-V 는 그것을 등재하지
    않았다. 그래서 기동 쪽 답은 그대로 "분류를 적지 않았다" 다.

    두 ordinal 을 **구분해서** 잰다 — 하나를 등재했다고 나머지가 열리지
    않는다는 것이 이 시험이 지키는 사실이다.
    """
    duel, instance = board(repository, GIRSU)
    verdict = judged(
        duel,
        ignition_action(instance, card_id=GIRSU, ordinal=GIRSU_IGNITION_ORDINAL),
        definitions=definition_registry(),
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == MONSTER_ACTIVATION_MISSING

    #: 🔴 목록에는 들어왔지만 **그 ordinal 이 아니다.**
    refs = {
        entry.effect_ref for entry in EFFECT_LIBRARY
        if entry.effect_ref.card_id == GIRSU
    }
    assert refs == {EffectRef(GIRSU, 0)}, refs
    assert EffectRef(GIRSU, GIRSU_IGNITION_ORDINAL) not in refs


# ======================================================================
# N. 금지 사항 — AST 로 센다
# ======================================================================


def _production_files():
    for package in ("engine", "agent", "integration", "app", "core"):
        yield from sorted((PROJECT_ROOT / package).rglob("*.py"))


def test_n01_no_card_id_branch_was_added_to_the_activation_path():
    """
    🔴 **카드 ID · 이름으로 분기하지 않는다** (§3-5).

    어니스트의 번호가 production 에 나타나는 자리는 ``library.py`` 의
    **선언 한 곳**뿐이다 — 등재 목록이고 분기가 아니다.

    🔴 **Phase 6-V 에서 기르수도 같은 자리에 들어왔다.** 그 전까지는
    production 에 하나도 없었고 이 시험이 그것을 지켰다. 6-V 가 기르수 ①
    을 등재했으므로 어니스트와 **똑같이** ``library.py`` 한 곳이 된다 —
    늘어난 것은 분기가 아니라 **선언**이고, 그 구분이 이 시험의 요지다.
    """
    honest_code, girsu_code = [], []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        numbers = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        relative = str(path.relative_to(PROJECT_ROOT))
        if HONEST in numbers:
            honest_code.append(relative)
        if GIRSU in numbers:
            girsu_code.append(relative)
    assert honest_code == ["engine/effect/library.py"], honest_code
    #: 🔴 **이 줄이 Phase 6-V 에서 뒤집혔다.** 그때까지 "기르수의 번호는
    #: production 코드에 하나도 없다" 였고 참이었다 — 6-V 가 기르수 ① 을
    #: 등재했으므로 어니스트와 **같은 한 자리**가 된다. ``engine/condition/
    #: model.py`` 의 docstring 이 그 카드를 예로 드는 것은 설명이고 분기가
    #: 아니며, 그 사실도 그대로다 (아래 AST 검사가 **비교가 아님**을 센다).
    assert girsu_code == ["engine/effect/library.py"], girsu_code

    #: 그 한 자리도 **비교**가 아니라 상수 선언이다.
    tree = ast.parse(
        (PROJECT_ROOT / "engine" / "effect" / "library.py").read_text(
            encoding="utf-8"
        )
    )
    comparisons = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(operand, ast.Constant) and operand.value == HONEST
            for operand in [node.left, *node.comparators]
        )
    ]
    assert comparisons == []


def test_n02_the_validator_does_not_permit_by_card_type_alone():
    """
    🔴 **몬스터라는 이유만으로 허가하지 않는다** (§3-6).

    범위 함수의 몬스터 분기가 ``activation_kind`` 를 보는지 AST 로 센다.
    분류를 보지 않는 몬스터 분기가 생기면 이 테스트가 깨진다.
    """
    source = (PROJECT_ROOT / "engine" / "action_validation.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_monster_activation_out_of_scope"
    )
    names = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
    assert "activation_kind" in names
    #: 첫 분기가 "적지 않았으면 범위 밖" 이다.
    first = function.body[1] if len(function.body) > 1 else function.body[0]
    assert isinstance(first, ast.If)
    assert "activation_kind is None" in ast.unparse(first.test)


def test_n03_the_definition_source_is_optional_everywhere():
    """
    등록소를 주지 않는 기존 호출이 **깨지지 않는다.**

    ``ActionValidator(view)`` 한 인자 호출이 production 과 테스트 양쪽에
    남아 있고, 그때의 답은 Phase 6-K 이전과 같다 (§C).
    """
    import inspect

    signature = inspect.signature(ActionValidator.__init__)
    parameter = signature.parameters["definitions"]
    assert parameter.default is None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_n05_both_production_call_sites_pass_the_definition_source():
    """
    🔴 **배선이 끊기면 조용히 좁아진다** — 그래서 두 자리를 못박는다.

    등록소를 넘기지 않으면 검증기는 몬스터 효과를 "분류를 적지 않았다" 로
    범위 밖에 둔다. 그것은 **오류가 아니라 더 좁은 답**이므로 어떤 거부도
    일어나지 않고, 후보가 0건인 지금은 **동작으로도 보이지 않는다.**

    세 자리가 검증기를 만든다.

    ===========================================  ========================
    ``Duel.legal_actions``                        후보 생성
    ``Duel._apply_activation``                    적용 직전 재검증
    ``EffectActivator._verdict``                  허가를 받지 못했을 때
    ===========================================  ========================

    셋 다 등록소를 넘겨야 **같은 판에서 같은 답**이 나온다 (STRUCTURAL-134
    가 고친 것이 바로 그 어긋남이다).
    """
    duel_source = (PROJECT_ROOT / "engine" / "duel.py").read_text(encoding="utf-8")
    tree = ast.parse(duel_source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ActionValidator"
    ]
    #: 🔴 **만드는 자리를 하나로 묶었다** (Phase 6-Z). 6-Z 가 관측에 없는
    #: 둘째 사실(``event_backed``)을 더하면서, 자리마다 손으로 넘기던 모양이
    #: 위험해졌다 — 한 자리라도 빠뜨리면 **오류 없이 조용히** 후보 생성과
    #: 재검증이 갈라지고, 그것이 STRUCTURAL-134 가 고친 어긋남이다.
    #:
    #: 그래서 ``Duel.activation_validator`` 하나가 만들고, 쓰는 자리는 그것을
    #: 부른다. 이 시험은 **그 자리가 하나임**과 **둘을 다 넘김**을 센다.
    assert len(calls) == 1, [ast.unparse(call) for call in calls]
    assert sorted(kw.arg for kw in calls[0].keywords) == [
        "definitions",
        "event_backed",
    ], ast.unparse(calls[0])

    #: 그리고 **쓰는 자리는 모두 그 공장을 부른다** — 후보 생성 · 재검증 ·
    #: 보고, 그리고 6-AB 보완4 가 더한 창 판정.
    #:
    #: 🔴 **열거를 기준으로 바꿨다** (보완4). 전에는
    #: ``== ["_apply_activation", "legal_actions"]`` 였다. 이 시험의 주장은
    #: "두 자리다" 가 아니라 **"검증기를 만드는 자리가 하나이고, 쓰는 자리는
    #: 모두 그것을 부른다"** 이고 (바로 위의 ``len(calls) == 1``), 그 주장은
    #: 부르는 자리가 늘어도 그대로다. 보완4 가 ``_window_can_act`` 를
    #: 더했다 — 그 자리가 **관문까지** 보아야 "처리할 수 있는 의무" 를 가릴
    #: 수 있고, 손으로 검증기를 만들면 바로 그 어긋남이 생긴다.
    factory_users = sorted(
        {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(inner, ast.Attribute)
                and inner.attr == "activation_validator"
                for inner in ast.walk(node)
            )
        }
    )
    assert {"_apply_activation", "legal_actions"} <= set(factory_users)
    #: 🔴 부르는 자리는 **그 하나의 공장**을 쓴다 — 제 검증기를 만들지
    #: 않는다 (위의 ``len(calls) == 1`` 이 그것을 센다).
    assert "activation_validator" in duel_source
    reporting = (PROJECT_ROOT / "deck" / "opening.py").read_text(encoding="utf-8")
    assert "duel.activation_validator(" in reporting
    assert "ActionValidator(" not in reporting, "보고가 제 검증기를 만들면 갈라진다"

    activation_source = (PROJECT_ROOT / "engine" / "activation.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(activation_source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ActionValidator"
    ]
    assert len(calls) == 1, len(calls)
    assert [kw.arg for kw in calls[0].keywords] == ["definitions"]


def test_n04_the_validator_refuses_a_source_that_cannot_look_definitions_up():
    """
    등록소 자리에 아무 객체나 받지 않는다 — 모양을 먼저 본다.

    조용히 받아 두면 ``definition_for`` 가 없는 객체가 런타임에 터지고,
    그 터지는 자리는 판정 중간이다.
    """
    deck = [LUSTER_DRAGON] * 20
    with pytest.raises(TypeError, match="definition_for"):
        ActionValidator(
            __import__("engine.game_state_view", fromlist=["GameStateView"])
            .GameStateView.from_state(
                GameState.create(None, decks=(list(deck), list(deck))), viewer=MINE
            ),
            definitions=object(),
        )
