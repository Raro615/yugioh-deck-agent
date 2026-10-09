r"""
Phase 3-F-4 — Evaluation scenario 를 위한 **Event / Trigger Condition /
Eligibility / Activation 분리** 감사.

**AUDIT-ONLY.** production 을 한 줄도 고치지 않는다. Evaluation score 도 weight 도
건드리지 않는다 (3-F-3 의 결론은 그대로 둔다).

이 Phase 가 묻는 것 하나
-----------------------
"서로 다른 실제 게임 상황을 Evaluation benchmark 로 만들 수 있는가?"

네 단계를 **하나의 boolean 으로 뭉개지 않고** 각자 재서 답한다.

=====================  =========================  ==========================
단계                    LIVE 경로                   DORMANT 경로
=====================  =========================  ==========================
**EVENT**              **없다** — 발동 열거가         ``TimingEvent`` ·
                       사건을 읽지 않는다            ``TimingPoint`` 8개
**TRIGGER CONDITION**  **없다** — ``EffectDefinition``  ``TriggerSpec.point``
                       에 사건 칸이 없다             + 필터(``CARD_MOVED`` 만)
**ELIGIBILITY**        **있다** —                   ``TriggerEligibilityJudge``
                       ``EffectDefinition.activation``  다섯 관문
                       (상태 조건)
**ACTIVATION**         **있다** — 세 관문 +           **없다** (dormant 는
                       대상 바인딩                   발동하지 않는다)
=====================  =========================  ==========================

측정으로 확정한 것
-----------------
* ``EVENT_*`` 는 **파서 계층**(``EffectSpec.code``) 에 산다 — 블록 16,381개 ·
  상수 70종. ``EffectDefinition`` 은 그 칸을 갖지 않는다 (3-E-31 재확인).
* **등재 16효과 전부 ``EVENT_FREE_CHAIN``** = "유발 조건 없음". 즉 지금 엔진에는
  **사건에 반응하는 효과가 하나도 없다** (3-E-32 · 3-E-33 재확인).
* 그래서 **"다른 EVENT → 다른 후보" 시나리오는 LIVE 로 만들 수 없다.**
* 반면 **"같은 EVENT + 다른 조건 → 다른 판정" 은 만들 수 있다** — 마법에 한해서다
  (``test_06``–``test_09``).
* **함정은 조건 차이가 보이지 않는다** — 범위 검사가 조건 평가보다 **먼저**
  걸린다 (``test_10``). 그리고 그것이 올바른 동작이다: ``INVALID`` 가 아니라
  ``UNKNOWN`` 이다.
* 특수소환 사건(증G 유형) 은 **세 계층에 걸쳐** 비어 있다 (``test_12``–``test_14``).
"""

import ast
import collections
import dataclasses
import pathlib

import pytest

from engine.action import PlayerAction
from engine.action_validation import TRAP_TRIGGER_MISSING, ActionValidator
from engine.duel import Duel
from engine.effect import EffectDefinition, OperationKind
from engine.effect.delta import MonsterSummoned, SummonKind
from engine.effect.library import EFFECT_LIBRARY
from engine.ids import EffectRef, iter_effects
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.trigger import TimingPoint, TriggerSpec
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone

from tests.conftest import requires_official_db

pytestmark = requires_official_db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MINE, THEIRS = 0, 1

#: 사례로 쓰는 **등재된 실제 카드**. 종류는 공식 DB 가 말한다 (``test_05``).
POT_OF_GREED = 55144522       # 통상 마법 · 자신 DECK 2+
RELOAD = 22589918             # 속공 마법 · 자신 HAND 에 이 카드 말고 1+
RUTHLESS_DENIAL = 73148972    # 통상 마법 · 자신 MZONE 1+ AND 상대 HAND 1+
ROBBIN_GOBLIN_BOOK = 69091732 # **함정** · 상대 HAND 5+
LUSTER_DRAGON = 11091375


def source_of(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# ======================================================================
# 판 — 조건에 걸리는 축만 인수로 받는다
# ======================================================================


def board(
    repository,
    card_id: int,
    *,
    my_deck: int = 10,
    my_hand_extra: int = 0,
    their_hand: int = 3,
    my_monsters: int = 0,
):
    """
    그 카드를 패에 쥔 판. **한 축만 바꿔 가며** 같은 입력에서 조건을 뒤집는다.
    """
    state = GameState.create(
        repository,
        decks=([LUSTER_DRAGON] * max(my_deck, 1), [LUSTER_DRAGON] * 30),
        seed=1,
    )
    #: 내 덱을 정확히 ``my_deck`` 장으로 (state 쪽 존은 ``len()`` 으로 센다).
    while len(state.player(MINE).deck) > my_deck:
        state.move(state.player(MINE).deck.top(), Zone.REMOVED, to_player=MINE)
    subject = state.create_instance(card_id, owner=MINE, zone=Zone.HAND)
    for _ in range(my_hand_extra):
        state.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
    for _ in range(my_monsters):
        monster = state.create_instance(LUSTER_DRAGON, owner=MINE, zone=Zone.HAND)
        state.move(
            monster, Zone.MZONE, to_player=MINE, position=Position.FACEUP_ATTACK
        )
    state.draw(THEIRS, their_hand)
    state.turn.turn_number = 3
    state.turn.turn_player = MINE
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=MINE, phase=state.turn.phase),
    )
    return duel, subject.instance_id


def judge(repository, card_id: int, **kwargs):
    """
    그 카드의 발동에 대한 **관문 판정**과 **후보 여부**를 함께 돌려준다.

    두 값을 따로 받는 것이 이 Phase 의 요점이다 — ELIGIBILITY 와 ACTIVATION 은
    다른 질문이고, 대상이 붙지 않은 행위는 후보가 되면서도 그 자체로는 거절될
    수 있다 (``test_09``).
    """
    duel, instance = board(repository, card_id, **kwargs)
    validator = ActionValidator(duel.view(MINE))
    action = PlayerAction.activate_effect(
        actor=MINE, source=instance, effect_ref=EffectRef(card_id, 0)
    )
    gate = duel._activation_gate(action, validator=validator, selections=())
    offered = [
        candidate
        for candidate in duel.legal_actions(MINE).allowed
        if candidate.effect_ref == EffectRef(card_id, 0)
    ]
    return {
        "validity": gate.validity,
        "code": gate.code,
        "is_candidate": bool(offered),
        "candidates": offered,
        "view": duel.view(MINE),
    }


# ======================================================================
# A. EVENT 는 어디 사는가 — EffectDefinition 이 아니다
# ======================================================================


def test_01_the_effect_definition_has_no_event_field():
    """
    **``EffectDefinition`` 에 사건 칸이 없다.** 열 칸 어디에도 없다.

    있는 것은 ``activation: Condition | None`` 하나이고, ``Condition`` 은
    **상태**에 대해 평가된다 — "무엇이 일어났는가" 가 아니라 "무엇이 참인가" 다.
    그 차이가 이 Phase 전체의 출발점이다.
    """
    names = [field.name for field in dataclasses.fields(EffectDefinition)]
    assert names == [
        "effect_ref",
        "source_card_id",
        "operations",
        "activation",
        "cost",
        "targets",
        "declarations",
        "requirements",
        "guards",
        "provenance",
    ]
    for absent in ("code", "event", "point", "trigger", "setcode", "timing"):
        assert absent not in names, absent

    #: 그 모듈에 ``EVENT`` 라는 글자도 없다.
    assert "EVENT" not in source_of("engine/effect/definition.py")


def test_02_the_trigger_spec_is_the_one_that_carries_a_point():
    """
    사건을 **등록 계층**(``TriggerSpec``) 이 들고 있다. 그래서 "정의에 없다" 는
    "잃어버렸다" 가 아니라 **"다른 칸에 있다"** 다 (3-E-31 의 결론).
    """
    names = [field.name for field in dataclasses.fields(TriggerSpec)]
    assert "point" in names
    assert names == [
        "effect_ref",
        "point",
        "requirement",
        "wording",
        "operations",
        "from_zones",
        "to_zones",
        "activates_from",
        "condition",
    ]
    #: 그런데 그 ``TriggerSpec`` 은 dormant 다 — production 이 소비하지 않는다.
    duel = source_of("engine/duel.py")
    assert "TriggerSpec" not in duel
    assert "trigger" not in duel


@pytest.mark.real_card
def test_03_event_codes_live_in_the_parser_layer(repository):
    """
    ``EVENT_*`` 는 **파서 계층**에 산다 — ``EffectSpec.code`` 다. 그리고 그 값은
    engine 에서 **닿을 수 있다** (``iter_effects``) — 읽지 않기로 한 것이다.

    실측 (3-E-31 의 숫자를 다시 센다):

    ==========================  ======
    효과 블록 전체                34,631
    그중 ``code`` 가 있는 것       30,084
    그중 ``EVENT_*`` 인 것        **16,381**
    서로 다른 ``EVENT_*`` 상수     **70**
    ==========================  ======
    """
    counts: "collections.Counter[str | None]" = collections.Counter()
    for card in repository.all_cards():
        for _ref, spec in iter_effects(card):
            counts[getattr(spec, "code", None)] += 1

    events = {name: n for name, n in counts.items()
              if name and name.startswith("EVENT_")}
    #: 🔴 Phase 3-F-28 에서 34,631 → 34,632 · 30,084 → 30,085 ·
    #: ``EVENT_*`` 16,381 → 16,382 (로더가 블록 주석 안의 효과를 세던 것을
    #: 그만두고(``c9409625`` −1), ``c:RegisterEffect`` 로 이 카드에 등록되는 ``local``
    #: 없는 / ``e`` 로 시작하지 않는 블록을 세기 시작했다(``c9839115`` · ``c74506079``
    #: +2)).
    #: ``EVENT_*`` 종류 수 70 은 그대로다.
    #: 🔴 Phase 3-F-32 에서 +3 (``cards.cdb`` 에 붙은 블록 기준).
    assert sum(counts.values()) == 34635
    #: 🔴 Phase 3-F-31 에서 30,085 → **30,084** (``c44887817`` ordinal 1 의
    #: ``code`` 가 귀속 오류로 생긴 값이었다). ``EVENT_*`` 16,382 는 그대로다.
    #: 🔴 Phase 3-F-32 에서 30,084 → **30,087** — 새 clone 블록 셋 다 자기
    #: ``SetCode`` 를 갖는다.
    assert sum(n for name, n in counts.items() if name) == 30087
    #: 🔴 Phase 3-F-31 에서 ``EVENT_*`` 16,382 → **16,383**. ``c4997565``
    #: ordinal 1 의 제 값 ``EVENT_CHAINING`` 이 복원됐다 (전에는
    #: ``local e2=Effect.Clone(e1)`` 뒤 ``SetCode(EFFECT_DISABLE_EFFECT)`` 가
    #: 덮고 있었다). ``EFFECT_*`` 쪽이 그만큼 줄고, ``code`` 있는 블록 총수는
    #: ``c44887817`` 때문에 −1 이다.
    assert sum(events.values()) == 16383
    assert len(events) == 70


@pytest.mark.real_card
def test_04_every_registered_effect_is_free_chain(repository):
    """
    **등재 16효과 전부 ``EVENT_FREE_CHAIN`` 이다** = "유발 조건 없음".

    그러므로 지금 엔진에는 **사건에 반응하는 효과가 하나도 없다.** "다른 EVENT →
    다른 후보" 시나리오를 LIVE 로 만들 수 없는 까닭이 이것이다 (``test_11``).

    ``EVENT_FREE_CHAIN`` 은 **사건이 아니다** — 발동형 효과의 분류값이다
    (3-E-32 가 확정했다). 이름이 ``EVENT_`` 로 시작한다고 사건으로 읽지 않는다.
    """
    codes = []
    for entry in EFFECT_LIBRARY:
        card = repository.get(entry.definition.source_card_id)
        for ref, spec in iter_effects(card):
            if ref == entry.definition.effect_ref:
                codes.append(getattr(spec, "code", None))
                break

    assert len(EFFECT_LIBRARY) == 16
    assert len(codes) == 16
    assert set(codes) == {"EVENT_FREE_CHAIN"}


@pytest.mark.real_card
def test_05_the_eight_activation_conditions_are_state_conditions(repository):
    """
    조건을 가진 등재 효과는 **여덟**이고, 전부 **상태**에 대한 조건이다 —
    "덱에 몇 장", "패에 몇 장", "상대 패에 몇 장". 사건을 묻는 것이 하나도 없다.

    카드 종류는 **공식 DB 가 말한다** — 추측하지 않는다.
    """
    with_condition = {}
    for entry in EFFECT_LIBRARY:
        definition = entry.definition
        if definition.activation is None:
            continue
        card = repository.get(definition.source_card_id)
        with_condition[definition.source_card_id] = {
            "name": card.name,
            "types": sorted(card.type_names),
            "condition": definition.activation.describe_ko(),
        }

    assert len(with_condition) == 8
    #: 사례로 쓰는 넷의 종류를 못박는다.
    assert with_condition[POT_OF_GREED]["types"] == ["SPELL"]
    assert with_condition[RELOAD]["types"] == ["QUICKPLAY", "SPELL"]
    assert with_condition[RUTHLESS_DENIAL]["types"] == ["SPELL"]
    assert with_condition[ROBBIN_GOBLIN_BOOK]["types"] == ["TRAP"]

    #: 조건 문구에 사건 어휘가 없다 — 전부 "어디에 몇 장" 이다.
    for row in with_condition.values():
        for event_word in ("때", "경우", "소환되었", "파괴되었", "발동했"):
            assert event_word not in row["condition"], row


# ======================================================================
# B. 같은 EVENT + 다른 조건 → **다른 판정** (LIVE 로 만들 수 있다)
# ======================================================================


@pytest.mark.real_card
def test_06_a_normal_spell_flips_on_its_own_deck_count(repository):
    """
    **사례 1 — 욕망의 항아리 (통상 마법, 자신 DECK 2+).**

    덱 2장과 1장만 다른 두 판에서 판정이 갈린다. 왜 이 판정이어야 하는가:
    조건을 **끝까지 보고 거짓을 받았으므로** 확실한 거부이고, 그래서
    ``INVALID`` / ``CANDIDATE_NOT_ELIGIBLE`` 이다 — "엔진이 못 한다" 가 아니다
    (Phase 3-E-38 이 이 자리를 그렇게 고쳤다).
    """
    satisfied = judge(repository, POT_OF_GREED, my_deck=2)
    broken = judge(repository, POT_OF_GREED, my_deck=1)

    assert satisfied["view"].me.deck.size == 2
    assert broken["view"].me.deck.size == 1

    assert (satisfied["validity"], satisfied["code"]) == (
        ActionValidity.VALID,
        ValidationCode.OK,
    )
    assert satisfied["is_candidate"] is True

    assert (broken["validity"], broken["code"]) == (
        ActionValidity.INVALID,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    )
    assert broken["is_candidate"] is False


@pytest.mark.real_card
def test_07_a_quick_play_spell_flips_on_a_self_excluding_condition(repository):
    """
    **사례 2 — 리로드 (속공 마법, 자신 HAND 에 "이 카드 말고" 1+).**

    패에 다른 카드가 있는지만 다르다. 조건이 **자기를 제외**하므로, 패에 이
    카드 하나뿐이면 거짓이다.
    """
    satisfied = judge(repository, RELOAD, my_hand_extra=1)
    broken = judge(repository, RELOAD, my_hand_extra=0)

    assert satisfied["view"].me.hand.size == 2
    assert broken["view"].me.hand.size == 1

    assert satisfied["code"] is ValidationCode.OK
    assert satisfied["is_candidate"] is True
    assert broken["code"] is ValidationCode.CANDIDATE_NOT_ELIGIBLE
    assert broken["is_candidate"] is False


@pytest.mark.real_card
def test_08_a_conjunction_can_be_broken_on_either_side(repository):
    """
    **사례 3 — 무정한 말살 (통상 마법, 자신 MZONE 1+ **그리고** 상대 HAND 1+).**

    두 조건의 AND 다. **각각 따로 깨도** 같은 코드가 나온다 — 조건 계층이
    둘을 하나로 접어서 판정하기 때문이다.

    이것이 중요한 까닭: 조건 하나하나가 **어느 쪽이 깨졌는지**는 코드에 남지
    않는다. ``reason`` 문장에만 남는다 (DEFERRED 로 기록).
    """
    both = judge(repository, RUTHLESS_DENIAL, my_monsters=1, their_hand=1)
    no_monster = judge(repository, RUTHLESS_DENIAL, my_monsters=0, their_hand=1)
    no_hand = judge(repository, RUTHLESS_DENIAL, my_monsters=1, their_hand=0)

    #: 두 조건이 다 참이면 **후보가 된다.**
    assert both["is_candidate"] is True

    #: 앞 조건만 깨도, 뒤 조건만 깨도 **같은 코드**다.
    for broken, label in ((no_monster, "내 몬스터 0"), (no_hand, "상대 패 0")):
        assert broken["code"] is ValidationCode.CANDIDATE_NOT_ELIGIBLE, label
        assert broken["validity"] is ActionValidity.INVALID, label
        assert broken["is_candidate"] is False, label


@pytest.mark.real_card
def test_09_eligibility_and_activation_are_different_questions(repository):
    """
    **ELIGIBILITY ≠ ACTIVATION** — 같은 판에서 둘이 갈린다.

    무정한 말살은 조건을 만족하므로 **후보가 된다.** 그런데 그 후보는 대상을
    **들고** 나온다. 대상 없이 만든 행위는 같은 판에서 거절된다 —
    ``TOO_FEW_SELECTED`` 이고 ``CANDIDATE_NOT_ELIGIBLE`` 이 아니다.

    코드가 다른 것이 요점이다: "자격이 없다" 와 "이 행위가 덜 적혔다" 는 다른
    사실이고, 하나의 boolean 으로 뭉개면 그 차이가 사라진다.
    """
    result = judge(repository, RUTHLESS_DENIAL, my_monsters=1, their_hand=1)

    #: ELIGIBILITY — 후보가 된다.
    assert result["is_candidate"] is True
    #: 그리고 그 후보는 **대상을 들고** 나온다.
    assert len(result["candidates"]) == 1
    assert result["candidates"][0].targets, "후보가 대상을 들고 나와야 한다"

    #: ACTIVATION — 대상 없는 같은 발동은 **다른 코드**로 거절된다.
    assert result["validity"] is ActionValidity.INVALID
    assert result["code"] is ValidationCode.TOO_FEW_SELECTED
    assert result["code"] is not ValidationCode.CANDIDATE_NOT_ELIGIBLE


@pytest.mark.real_card
def test_10_a_trap_hides_its_condition_difference_behind_unknown(repository):
    """
    **사례 4 — 의적의 입문서 (함정, 상대 HAND 5+). 조건 차이가 보이지 않는다.**

    상대 패 5장과 4장에서 **같은 답**이 나온다 — ``UNKNOWN`` /
    ``RULE_NOT_IMPLEMENTED``. 범위 검사(함정)가 조건 평가보다 **먼저** 걸리기
    때문이다.

    **그리고 그것이 올바른 동작이다** (§9). 조건이 거짓인 것이 아니라 **판정할
    규칙이 없는** 것이므로 ``INVALID`` 가 아니라 ``UNKNOWN`` 이다. 여기서
    ``CANDIDATE_NOT_ELIGIBLE`` 이 나오면 "규칙이 금지한다" 는 거짓이 된다.

    대가는 분명하다 — **함정의 조건 차이로는 benchmark 를 만들 수 없다.**
    """
    satisfied = judge(repository, ROBBIN_GOBLIN_BOOK, their_hand=5)
    broken = judge(repository, ROBBIN_GOBLIN_BOOK, their_hand=4)

    assert satisfied["view"].opponent.hand.size == 5
    assert broken["view"].opponent.hand.size == 4

    #: 조건이 참인 쪽과 거짓인 쪽이 **구분되지 않는다.**
    for result in (satisfied, broken):
        assert result["validity"] is ActionValidity.UNKNOWN
        assert result["code"] is ValidationCode.RULE_NOT_IMPLEMENTED
        assert result["is_candidate"] is False
    assert (satisfied["validity"], satisfied["code"]) == (
        broken["validity"],
        broken["code"],
    )

    #: 까닭이 이름 붙은 "없는 규칙" 으로 남아 있다.
    assert "trap-activation-timing" in TRAP_TRIGGER_MISSING
    assert "SetCode(EVENT_*)" in TRAP_TRIGGER_MISSING


@pytest.mark.real_card
def test_11_no_live_scenario_can_differ_by_event(repository):
    """
    **"다른 EVENT → 다른 후보" 는 LIVE 로 만들 수 없다.**

    까닭이 둘이고 둘 다 측정된다.

    1. 등재 16효과 전부 ``EVENT_FREE_CHAIN`` 이므로 **반응할 사건이 없다**
       (``test_04``).
    2. 발동 열거(``Duel._activation_actions``) 가 **사건을 하나도 읽지 않는다**
       (Phase 3-E-30 이 측정했고 여기서 다시 센다).
    """
    tree = ast.parse(source_of("engine/duel.py"))
    enumerator = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_activation_actions"
    )
    names = {node.id for node in ast.walk(enumerator) if isinstance(node, ast.Name)}
    for event_name in (
        "TimingEvent",
        "TimingPoint",
        "TriggerCandidate",
        "TriggerSpec",
        "TriggerRegistry",
        "JournalEvent",
    ):
        assert event_name not in names, event_name


# ======================================================================
# C. 특수소환 사건 (증G / 후와로스 유형) — 세 계층이 비어 있다
# ======================================================================


def test_12_the_summon_kind_vocabulary_exists_but_the_timing_point_does_not():
    """
    **어휘는 있고 시점은 없다.**

    ``SummonKind`` 가 ``normal`` / ``special`` 을 구분하고
    ``MonsterSummoned.summon`` 이 그것을 싣는다. 그런데 ``TimingPoint`` 에는
    ``monster_summoned`` 하나뿐이고 **특수소환 전용 시점이 없다.**
    """
    assert [kind.value for kind in SummonKind] == ["normal", "special"]
    assert "summon" in [f.name for f in dataclasses.fields(MonsterSummoned)]

    points = [point.value for point in TimingPoint]
    assert points == [
        "card_moved",
        "card_drawn",
        "life_changed",
        "effect_resolved",
        "cost_paid",
        "monster_summoned",
        "phase_changed",
        "unimplemented",
    ]
    assert not any("special" in point or "spsummon" in point for point in points)


def test_13_a_trigger_spec_cannot_filter_on_the_summon_kind():
    """
    **그래서 dormant 로도 "특수소환에 반응" 을 적을 수 없다.**

    ``TriggerSpec`` 의 필터 셋(``operations`` · ``from_zones`` · ``to_zones``)은
    ``CARD_MOVED`` 에만 걸 수 있고, ``MONSTER_SUMMONED`` 에는 **어떤 필터도**
    걸 수 없다. 그래서 일반 소환과 특수소환을 가릴 수단이 없다.
    """
    from engine.trigger import TriggerError

    #: ``MONSTER_SUMMONED`` 는 만들 수 있다 — 필터 없이.
    plain = TriggerSpec(EffectRef(1, 0), TimingPoint.MONSTER_SUMMONED)
    assert plain.point is TimingPoint.MONSTER_SUMMONED
    assert (plain.operations, plain.from_zones, plain.to_zones) == (None, None, None)

    #: 그런데 필터를 걸면 거부한다.
    for field, value in (
        ("operations", frozenset({OperationKind.SPECIAL_SUMMON})),
        ("from_zones", frozenset({Zone.HAND})),
        ("to_zones", frozenset({Zone.MZONE})),
    ):
        with pytest.raises(TriggerError, match="카드 이동이 아닌 사건"):
            TriggerSpec(
                EffectRef(1, 0), TimingPoint.MONSTER_SUMMONED, **{field: value}
            )


def test_14_no_registered_effect_can_special_summon():
    """
    **그리고 그 사건을 일으킬 효과가 하나도 없다.**

    ``OperationKind.SPECIAL_SUMMON`` 은 어휘에 **있는데** 등재 16효과 중 그것을
    쓰는 것이 **없다**. 그래서 증G 가 반응할 사건이 이 엔진에서는 애초에
    발생하지 않는다.

    세 계층이 각각 비어 있는 것이고, 어느 하나를 고쳐도 나머지가 남는다:

    ====================================  ======================
    ``OperationKind.SPECIAL_SUMMON``       어휘에 **있다**
    그것을 쓰는 등재 효과                    **0개**
    ``TimingPoint`` 의 특수소환 시점          **없다** (``test_12``)
    ``TriggerSpec`` 의 소환 종류 필터          **없다** (``test_13``)
    ====================================  ======================
    """
    assert any(kind.name == "SPECIAL_SUMMON" for kind in OperationKind)

    users = []
    present = set()
    for entry in EFFECT_LIBRARY:
        for operation in entry.definition.operations:
            kind = getattr(operation, "kind", None)
            if kind is None:
                continue
            present.add(kind.name)
            if kind.name == "SPECIAL_SUMMON":
                users.append(str(entry.definition.effect_ref))
    assert users == []

    #: **빈 목록이 엉뚱한 이유로 비지 않았다는 것까지 본다.** ``kind`` 조회가
    #: 깨지면 위 단정이 **그냥 통과**한다 — 그래서 실제로 읽힌 연산 종류를
    #: 함께 못박는다 (3-F-4 에서 그 구멍을 확인했다).
    assert present == {
        "CHANGE_LIFE",
        "DESTROY",
        "DISCARD",
        "DRAW",
        "RETURN_TO_DECK",
        "RETURN_TO_HAND",
        "SEND_TO_GRAVE",
        "SHUFFLE",
    }
    assert "SPECIAL_SUMMON" not in present


# ======================================================================
# D. ValidationCode 의 의미를 섞지 않았다
# ======================================================================


@pytest.mark.real_card
def test_15_the_three_refusal_meanings_stay_separate(repository):
    """
    **§9 의 세 갈래가 실제로 갈려 있다.** 같은 "발동할 수 없다" 가 세 코드로
    나온다.

    ==========================================  =================================
    조건을 끝까지 보고 **거짓**                      ``INVALID`` / ``CANDIDATE_NOT_ELIGIBLE``
    **판정할 규칙이 없다** (함정 범위 밖)              ``UNKNOWN`` / ``RULE_NOT_IMPLEMENTED``
    자격은 있는데 **행위가 덜 적혔다**                ``INVALID`` / ``TOO_FEW_SELECTED``
    ==========================================  =================================

    세 번째가 첫 번째와 다른 것이 요점이다 — 둘 다 ``INVALID`` 지만 **코드가
    다르고**, 그래서 "왜 안 되는가" 가 남는다.
    """
    condition_false = judge(repository, POT_OF_GREED, my_deck=1)
    rule_missing = judge(repository, ROBBIN_GOBLIN_BOOK, their_hand=5)
    under_specified = judge(
        repository, RUTHLESS_DENIAL, my_monsters=1, their_hand=1
    )

    assert (condition_false["validity"], condition_false["code"]) == (
        ActionValidity.INVALID,
        ValidationCode.CANDIDATE_NOT_ELIGIBLE,
    )
    assert (rule_missing["validity"], rule_missing["code"]) == (
        ActionValidity.UNKNOWN,
        ValidationCode.RULE_NOT_IMPLEMENTED,
    )
    assert (under_specified["validity"], under_specified["code"]) == (
        ActionValidity.INVALID,
        ValidationCode.TOO_FEW_SELECTED,
    )

    #: 셋이 서로 다른 코드다 — 하나로 뭉개지지 않았다.
    assert len({
        condition_false["code"], rule_missing["code"], under_specified["code"]
    }) == 3


def test_16_unimplemented_is_not_the_absence_of_an_event():
    """
    **``UNIMPLEMENTED`` 를 "사건이 없었다" 로 읽지 않는다** (§9 의 마지막 줄).

    ``TimingPoint.UNIMPLEMENTED`` 는 **사건이 있었는데 옮길 이름이 없다** 는
    뜻이고, 그래서 ``note`` 를 **반드시** 요구한다. 3-E-45 가 그 시점을 받으면
    ``UNKNOWN`` 으로 돌려주도록 고쳤다 — 거부가 아니다.
    """
    from engine.trigger import TimingEvent, TriggerError

    #: 이유 없이 그 시점을 쓸 수 없다.
    with pytest.raises(TriggerError):
        TimingEvent.unimplemented("")

    event = TimingEvent.unimplemented("ZoneShuffled 를 옮길 이름이 아직 없다")
    assert event.point is TimingPoint.UNIMPLEMENTED
    assert event.note
    #: 그리고 그 사건은 **delta 가 있었다** 는 뜻이다 — 없었다는 뜻이 아니다.
    assert "옮길" in event.note

    #: 3-E-45 가 고친 대로, 그 시점은 ``UNKNOWN`` 으로 돌아온다.
    trigger = source_of("engine/trigger.py")
    assert "엔진이 표현하지 못하는 사건이라" in trigger


# ======================================================================
# E. 아무것도 바꾸지 않았다
# ======================================================================


def test_17_this_phase_changed_no_production_file():
    """
    **AUDIT-ONLY.** Evaluation · Search · 발동 경로 · 가중치가 그대로다.
    3-F-3 의 결론(weight 를 붙이지 않았다) 도 그대로다.
    """
    from agent.evaluation import (
        DECK_CARD_IN_LP,
        HAND_CARD_IN_LP,
        MONSTER_IN_LP,
        StateValue,
    )
    from agent.search import SearchCandidate

    assert (DECK_CARD_IN_LP, HAND_CARD_IN_LP, MONSTER_IN_LP) == (300, 200, 500)
    assert len(dataclasses.fields(StateValue)) == 4
    assert len(dataclasses.fields(SearchCandidate)) == 4

    evaluation = source_of("agent/evaluation.py")
    for absent in ("OPPONENT_RESOURCE_IN_LP", "OPPONENT_DRAW_IN_LP", "TimingPoint"):
        assert absent not in evaluation, absent

    search = source_of("agent/search.py")
    for absent in ("TriggerSpec", "TimingEvent", "drawn_from_deck"):
        assert absent not in search, absent


def test_18_the_dormant_pipeline_was_not_connected():
    """
    **dormant pipeline 을 production 에 연결하지 않았다** (§16).

    "구조가 존재한다" 와 "지금 연결해야 한다" 를 섞지 않는다.
    """
    duel = source_of("engine/duel.py")
    for absent in ("TriggerRegistry", "TriggerCollector", "TriggerEligibilityJudge",
                   "trigger", "Trigger"):
        assert absent not in duel, absent

    #: 그리고 dormant 다섯 모듈은 그대로 dormant 다 — `agent/` 가 모르는 채다.
    for rel in ("agent/evaluation.py", "agent/search.py", "agent/heuristic.py",
                "agent/policy.py", "agent/simulation.py"):
        assert "engine.trigger" not in source_of(rel), rel
