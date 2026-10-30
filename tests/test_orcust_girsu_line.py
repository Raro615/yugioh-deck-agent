"""
Phase 6-AC — **기르수에서 시작하는 오르페골 전개 한 경로가 끝까지 도는가.**

이 파일이 재는 것
-----------------
``deck.combo_policy.ORCUST_GIRSU_LINE`` 의 네 단계가 **실제 엔진 행동으로**
수행되는지, 그리고 그 네 단계를 가능하게 한 세 계약(링크 소환 절차 · 효과에
의한 특수 소환 권한 · 1턴 1회 제한)이 **범위 밖에서는 열리지 않는지**.

    1  「잭나이츠 오르페골 기르수」 일반 소환
    2  기르수 ① — 덱의 「성유물－『성장』」 을 묘지로
    3  묘지의 『성장』 ② — **패의** 『성장』 을 특수 소환
    4  기르수 + 『성장』 → 「오르페골 갈라테아」 링크 소환

성공은 테스트 통과가 아니라 **동작**이다. 그래서 A 묶음은 걸음마다 수락 ·
해결 · 상태 변경 · 카드 이동을 따로 세고, 전후 카드 수를 대조한다.

실제와 합성
-----------
====================================================  ==================
``69811710`` · ``93920420`` · ``30741503`` 경로 전체    🔴 실제 카드
``48835607`` (소재 조건 미등록 링크 몬스터)              🔴 실제 카드
``21844576`` 엘리멘틀 히어로 페더맨 (통상 몬스터 소재)    🔴 실제 카드
초기 판 구성 (필드 · 엑스트라 덱에 카드 놓기)            **테스트의 구성**
====================================================  ==================

🔴 **초기 판 구성 뒤의 변화는 전부 ``Duel.apply`` 가 만든다.** 이 파일에
``state.move`` 로 전개를 재현하는 자리는 없다 — B · C · D 묶음의 판도 **시작
상태**를 만들 뿐이고, 재는 것은 그 뒤 엔진이 한 일이다.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from deck.combo_policy import (
    COMBO_LINES,
    ORCUST_GIRSU_LINE,
    ORCUST_VERIFICATION_HAND,
    ORCUST_VERIFICATION_RECIPE,
    PlannedAction,
    VerificationLinePolicy,
    line_named,
    line_progress,
)
from deck.opening import build_opening, execute_opening, first_meaningful
from deck.recipe import parse_recipe
from engine.action import MalformedAction, PlayerAction, PlayerActionKind
from engine.duel import Duel, duel_components
from engine.link_rules import (
    LINK_MATERIAL_AS_LINK_RULE,
    LINK_MATERIAL_RULE_MISSING,
    LINK_MATERIAL_RULES,
    LINK_PLACEMENT_LINKED_RULE,
    LinkMaterialEligibility,
    assess_link_materials,
    material_rule_for,
)
from engine.priority import PriorityState
from engine.state.game_state import GameState
from engine.validation import ActionValidity, ValidationCode
from engine.vocabulary import Phase, Position, Zone
from tests.conftest import requires_official_db

GIRSU = 69811710
WAND = 93920420
GALATEA = 30741503
GALATEA_I = 48835607
FEATHERMAN = 21844576
CRESCENDO = 703897
P0, P1 = 0, 1

pytestmark = requires_official_db


# ======================================================================
# 공용 — 경로를 실제로 돌린다
# ======================================================================
def _run_line(repository, *, hand=None, choose=None):
    """
    발표한 레시피와 패로 선공 전개를 돌린다. ``/combo`` 와 **같은 배선**이다.

    🔴 ``opening_wiring`` 을 쓰지 않으면 유발이 ``legal_actions`` 에 오르지
    않아 2 단계부터 막힌다 — 이 파일이 재려는 것이 그 경로다.
    """
    from app.main import opening_wiring

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    assert draft is not None
    chooser, triggers = opening_wiring(repository)
    setup = build_opening(
        repository,
        draft,
        list(hand if hand is not None else ORCUST_VERIFICATION_HAND),
        chooser=chooser,
        triggers=triggers,
    )
    assert setup.can_run, setup.blockers
    policy = ORCUST_GIRSU_LINE.policy() if choose is None else choose
    return setup, execute_opening(setup, repository, choose=policy)


def _is_plain(value) -> bool:
    """정수 · 문자열 · ``None`` · 그 둘로만 이루어진 tuple 인가."""
    if value is None or isinstance(value, (int, str)):
        return True
    if isinstance(value, tuple):
        return all(_is_plain(item) for item in value)
    return False


def _zone_ids(state, zone, seat=P0):
    return [card.card_id for card in state.zone(seat, zone)]


def _census(state, seat=P0):
    """그 자리의 **모든** 카드를 자리별로 센다."""
    return {
        zone.value: len(state.zone(seat, zone))
        for zone in (
            Zone.DECK,
            Zone.HAND,
            Zone.MZONE,
            Zone.EMZONE,
            Zone.SZONE,
            Zone.GRAVE,
            Zone.REMOVED,
            Zone.EXTRA,
            Zone.FZONE,
            Zone.PZONE,
        )
    }


def _instances(state, seat=P0):
    """``instance_id -> (card_id, zone)`` — 개체를 하나하나 따라간다."""
    found: dict[int, tuple[int, str]] = {}
    for zone in Zone:
        try:
            container = state.zone(seat, zone)
        except Exception:  # pragma: no cover - 없는 자리
            continue
        for card in container:
            found[card.instance_id.value] = (card.card_id, zone.value)
    return found


# ======================================================================
# A. 경로 실행 — 네 단계가 실제로 돈다
# ======================================================================
@pytest.mark.real_card
def test_a01_the_published_recipe_and_hand_run_the_whole_line(repository):
    """
    🔴 **이 Phase 의 본문.** 발표한 레시피와 **사용자가 지정한 패**로 네
    단계가 전부 수행된다.

    패에 없는 카드를 보태지 않았다 — 2 단계가 덱에서 『성장』 을 꺼내 온다.
    """
    assert tuple(ORCUST_VERIFICATION_HAND) == (
        69811710,
        703897,
        2930675,
        12989604,
        93920420,
    )

    _setup, run = _run_line(repository)
    progress = line_progress(run, ORCUST_GIRSU_LINE)

    assert progress.completed, progress.describe_ko()
    assert progress.done == 4
    assert progress.blocked_at is None

    kinds = [step.kind for step in run.steps if step.accepted]
    assert kinds[:4] == [
        "normal_summon",
        "activate_effect",
        "activate_effect",
        "link_summon",
    ], kinds


@pytest.mark.real_card
def test_a02_every_step_records_its_choice_cost_and_resolution(repository):
    """
    걸음마다 **무엇을 골랐고 어떻게 해결됐는가**가 기록에 남는다.

    🔴 **비용이 없다는 것도 사실이다.** 이 경로의 네 단계 중 비용을 치르는
    것은 없고 (기르수 ① · 『성장』 ② 둘 다 ``cost`` 가 비어 있다), 소재는
    비용이 아니라 **소환 절차**다. 그 구분을 수로 적는다.
    """
    from engine.effect.library import definition_registry

    _setup, run = _run_line(repository)
    steps = [step for step in run.steps if step.accepted]

    #: ① 일반 소환 — 대상도 소재도 없다.
    assert steps[0].card_id == GIRSU
    assert steps[0].targets == ()
    assert steps[0].state_changed is True

    #: ② 기르수 ① — 대상은 **해결 중에** 고른다 (덱은 가려진 자리다).
    assert steps[1].effect_ref == f"{GIRSU}:e[0]"
    assert steps[1].targets == ()
    assert steps[1].effect_events == (f"{GIRSU}:e[0]",)
    assert steps[1].resolved is True

    #: ③ 『성장』 ② — 대상은 **발동 시점에** 고른다 (자기 패는 보인다).
    assert steps[2].effect_ref == f"{WAND}:e[1]"
    assert len(steps[2].targets) == 1
    assert steps[2].effect_events == (f"{WAND}:e[1]",)
    assert steps[2].resolved is True

    #: ④ 링크 소환 — 소재 둘과 배치 하나, 기록 세 건.
    assert steps[3].card_id == GALATEA
    assert "(3건)" in steps[3].reason
    #: 🔴 **소재가 기록에 이름으로 남는다** — ``targets`` 가 아니다.
    assert steps[3].targets == ()
    assert len(steps[3].materials) == 2
    assert "잭나이츠 오르페골 기르수" in steps[3].materials
    assert "성유물－『성장』" in steps[3].materials
    #: 소환이 아닌 걸음에는 소재가 없다.
    assert all(step.materials == () for step in steps[:3])

    #: 🔴 **비용은 없다.** 두 효과의 정의가 그렇게 적는다.
    definitions = definition_registry()
    for ref in (f"{GIRSU}:e[0]", f"{WAND}:e[1]"):
        card_id, ordinal = ref.split(":e[")
        from engine.ids import EffectRef

        definition = definitions.definition_for(
            EffectRef(int(card_id), int(ordinal.rstrip("]")))
        )
        assert definition.cost.costs == ()


@pytest.mark.real_card
def test_a03_the_final_board_is_what_the_line_promised(repository):
    """
    🔴 **최종 필드 · 패 · 묘지 · 제외 · 덱 · 엑스트라 덱.**

    경로가 약속한 결과는 하나다 — **엑스트라 몬스터 존의 갈라테아**와 묘지의
    석 장(덱에서 간 『성장』 · 소재가 된 기르수 · 소재가 된 『성장』).
    """
    setup, run = _run_line(repository)
    state = setup.duel.state

    assert _zone_ids(state, Zone.EMZONE) == [GALATEA]
    assert _zone_ids(state, Zone.MZONE) == []
    #: 묘지는 **간 순서**다 — 덱에서 먼저, 그 다음 소재 둘.
    assert _zone_ids(state, Zone.GRAVE) == [WAND, GIRSU, WAND]
    assert _zone_ids(state, Zone.REMOVED) == []
    #: 패에는 경로가 쓰지 않은 석 장이 남는다.
    assert sorted(_zone_ids(state, Zone.HAND)) == sorted(
        [703897, 2930675, 12989604]
    )
    #: 갈라테아가 엑스트라 덱을 떠났다.
    assert GALATEA not in _zone_ids(state, Zone.EXTRA)
    assert len(state.zone(P0, Zone.EXTRA)) == 5
    #: 덱에서 한 장(『성장』)만 나갔다 — 선공 첫 턴은 뽑지 않는다.
    assert len(state.zone(P0, Zone.DECK)) == 34

    assert run.state_changes == 4


@pytest.mark.real_card
def test_a04_no_card_is_duplicated_or_lost(repository):
    """
    🔴 **전개 전후의 카드 수와 개체 이동을 대조한다** (§7).

    세 가지를 함께 본다.

    1. **총 장수**가 그대로다 (메인 40 + 엑스트라 6).
    2. **개체 번호**의 묶음이 그대로다 — 새로 생기거나 사라진 번호가 없다.
    3. 움직인 개체마다 **어디서 어디로** 갔는지 말할 수 있다.
    """
    from app.main import opening_wiring

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    chooser, triggers = opening_wiring(repository)
    setup = build_opening(
        repository,
        draft,
        list(ORCUST_VERIFICATION_HAND),
        chooser=chooser,
        triggers=triggers,
    )
    before = _census(setup.duel.state)
    before_instances = _instances(setup.duel.state)
    assert sum(before.values()) == 46, before

    run = execute_opening(
        setup, repository, choose=ORCUST_GIRSU_LINE.policy()
    )
    assert line_progress(run, ORCUST_GIRSU_LINE).completed

    after = _census(setup.duel.state)
    after_instances = _instances(setup.duel.state)

    #: ① 총 장수가 그대로다.
    assert sum(after.values()) == sum(before.values()) == 46

    #: ② 개체 묶음이 그대로다 — **복제도 소실도 없다.**
    assert set(after_instances) == set(before_instances)
    #: 카드 정체도 바뀌지 않았다.
    assert {i: v[0] for i, v in after_instances.items()} == {
        i: v[0] for i, v in before_instances.items()
    }

    #: ③ 움직인 개체마다 자리의 변화를 말할 수 있다.
    moved = {
        instance: (before_instances[instance][1], after_instances[instance][1])
        for instance in before_instances
        if before_instances[instance][1] != after_instances[instance][1]
    }
    #: 넷이 움직였다 — 기르수(패→필드→묘지) · 덱의 『성장』(덱→묘지) ·
    #: 패의 『성장』(패→필드→묘지) · 갈라테아(엑스트라→엑스트라 몬스터 존).
    assert len(moved) == 4, moved
    assert sorted(
        (before_instances[i][0], src, dst) for i, (src, dst) in moved.items()
    ) == sorted(
        [
            (GIRSU, "HAND", "GRAVE"),
            (WAND, "DECK", "GRAVE"),
            (WAND, "HAND", "GRAVE"),
            (GALATEA, "EXTRA", "EMZONE"),
        ]
    )


@pytest.mark.real_card
def test_a05_the_same_input_and_the_same_policy_reproduce_the_same_board(
    repository,
):
    """
    🔴 **같은 조건 · 같은 선택이면 같은 결과다** (§8).

    정책이 상태를 갖지 않으므로 (``VerificationLinePolicy``) 두 번째 실행이
    첫 번째의 메모를 물려받지 않는다 — 그래도 같은 판이 나와야 한다.
    """
    first_setup, first = _run_line(repository)
    second_setup, second = _run_line(repository)

    assert first_setup.duel.state.state_hash() == (
        second_setup.duel.state.state_hash()
    )
    def fingerprint(run):
        return [
            (
                step.order,
                step.kind,
                step.card_id,
                step.effect_ref,
                step.targets,
                step.accepted,
                step.step_code,
                step.resolved,
                step.state_changed,
                step.effect_events,
            )
            for step in run.steps
        ]

    assert fingerprint(first) == fingerprint(second)
    assert first.stopped_kind == second.stopped_kind


@pytest.mark.real_card
def test_a06_a_fork_offers_and_executes_the_same_link_summon(repository):
    """
    🔴 **사본이 원본과 같은 후보를 내고 같은 결과를 만든다** (§5 · §8).

    사본에서 고른 것이 **원본을 오염시키지 않는다** — 그것까지 확인해야
    "사본에서 재현할 수 있다" 가 참이다.
    """
    from agent.simulation import Simulator

    setup, run = _run_line(repository)
    #: 경로가 끝난 자리에서 **다시** 링크 소환 후보를 묻는다 — 갈라테아는
    #: 이미 나왔으므로 남은 엑스트라 덱 카드의 소재 조건이 미등록이다.
    duel = setup.duel
    before = duel.state.state_hash()
    probe = Simulator(duel=duel)._fork()

    original = duel.legal_actions(P0)
    copied = probe.legal_actions(P0)
    assert [a.canonical_state() for a in original.allowed] == [
        a.canonical_state() for a in copied.allowed
    ]
    assert [w.line_ko() for w in original.withheld] == [
        w.line_ko() for w in copied.withheld
    ]

    #: 사본에서 한 걸음 적용해도 원본은 그대로다.
    flow = [a for a in copied.allowed if a.kind is PlayerActionKind.END_PHASE]
    if flow:
        assert probe.apply(flow[0]).accepted is True
    assert duel.state.state_hash() == before
    assert line_progress(run, ORCUST_GIRSU_LINE).completed


# ======================================================================
# B. 링크 소환 — 범위 밖은 열리지 않는다
# ======================================================================
def _link_board(repository, field, extra, emzone=()):
    """
    필드 · 엑스트라 몬스터 존 · 엑스트라 덱을 **시작 상태**로 만든다.

    🔴 이 뒤의 변화는 전부 ``Duel.apply`` 가 만든다.
    """
    state = GameState.create(
        repository,
        decks=([FEATHERMAN] * 20, [FEATHERMAN] * 20),
        turn_player=P0,
        seed=1,
        shuffle=False,
    )
    field_ids = []
    for index, card_id in enumerate(field):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.MZONE)
        state.move(
            instance,
            Zone.MZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field_ids.append(instance.instance_id)
    for index, card_id in enumerate(emzone):
        instance = state.create_instance(card_id, owner=P0, zone=Zone.EMZONE)
        state.move(
            instance,
            Zone.EMZONE,
            to_player=P0,
            index=index,
            position=Position.FACEUP_ATTACK,
        )
        field_ids.append(instance.instance_id)
    extra_ids = [
        state.create_instance(card_id, owner=P0, zone=Zone.EXTRA).instance_id
        for card_id in extra
    ]
    state.turn.turn_number = 3
    state.turn.set_phase(Phase.MAIN1)
    duel = Duel(
        state=state,
        priority=PriorityState.idle(turn_player=P0, phase=Phase.MAIN1),
        **duel_components(),
    )
    return duel, field_ids, extra_ids


def _links(duel, seat=P0):
    legal = duel.legal_actions(seat)
    return (
        [a for a in legal.allowed if a.kind is PlayerActionKind.LINK_SUMMON],
        [w for w in legal.withheld if w.kind is PlayerActionKind.LINK_SUMMON],
    )


@pytest.mark.real_card
def test_b01_a_normal_monster_is_not_a_legal_material(repository):
    """소재 조건 위반 — **규칙이 막은 것**이고 미지원이 아니다."""
    duel, field, extra = _link_board(
        repository, [GIRSU, FEATHERMAN], [GALATEA]
    )
    allowed, held = _links(duel)
    assert allowed == []
    assert [w.code for w in held] == [ValidationCode.LINK_MATERIAL_INVALID]
    assert held[0].missing is None
    assert held[0].is_rule_refusal is True
    assert "효과 몬스터가 아닙니다" in held[0].reason

    #: 직접 적용해도 거절되고 **판은 그대로다.**
    before = duel.state.state_hash()
    step = duel.apply(PlayerAction.link_summon(P0, extra[0], tuple(field)))
    assert step.accepted is False
    assert step.code is ValidationCode.LINK_MATERIAL_INVALID
    assert duel.state.state_hash() == before


@pytest.mark.real_card
def test_b02_the_group_requirement_is_checked_not_only_the_count(repository):
    """
    🔴 **장수와 링크 수치만 맞춰 통과시키지 않는다** (§4).

    『성장』 두 장은 효과 몬스터 둘이고 장수도 맞지만 「오르페골」 몬스터가
    없다 — 갈라테아의 소재 조건이 그것을 요구한다.
    """
    duel, field, extra = _link_board(repository, [WAND, WAND], [GALATEA])
    allowed, held = _links(duel)
    assert allowed == []
    assert [w.code for w in held] == [ValidationCode.LINK_MATERIAL_INVALID]
    assert "카드군 0x11b" in held[0].reason

    verdict = assess_link_materials(
        duel.view(P0), P0, extra[0], tuple(field)
    )
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert verdict.missing_rule is None


@pytest.mark.real_card
def test_b03_too_few_monsters_on_the_field_is_reported(repository):
    """
    조합이 **0가지**인 것도 사실이다 — 조용히 사라지면 읽는 쪽은 "링크
    소환을 묻지도 않았다" 로 읽는다.
    """
    duel, _field, _extra = _link_board(repository, [GIRSU], [GALATEA])
    allowed, held = _links(duel)
    assert allowed == []
    assert [w.code for w in held] == [ValidationCode.LINK_MATERIAL_INVALID]
    assert "소재 2장을 고를 수 없습니다" in held[0].reason


@pytest.mark.real_card
def test_b04_an_unread_link_monster_is_unknown_not_invalid(repository):
    """
    🔴 **소재 조건을 읽지 않은 링크 몬스터는 ``UNKNOWN``** 이다 (ADR-006).

    「오르페골 갈라테아i」(48835607) 는 LINK-1 이고 소재 조건이
    :data:`~engine.link_rules.LINK_MATERIAL_RULES` 에 없다 — 필드에 적격한
    몬스터가 있어도 후보가 되지 않는다.
    """
    duel, _field, _extra = _link_board(repository, [GIRSU, WAND], [GALATEA_I])
    allowed, held = _links(duel)
    assert allowed == []
    assert [w.code for w in held] == [ValidationCode.RULE_NOT_IMPLEMENTED]
    assert held[0].missing == LINK_MATERIAL_RULE_MISSING
    assert held[0].validity is ActionValidity.UNKNOWN
    assert held[0].is_rule_refusal is False
    assert material_rule_for(GALATEA_I) is None


@pytest.mark.real_card
def test_b05_a_legal_combination_is_not_hidden_by_an_unread_neighbour(
    repository,
):
    """읽은 카드와 읽지 않은 카드가 함께 있어도 **읽은 쪽은 후보가 된다.**"""
    duel, _field, _extra = _link_board(
        repository, [GIRSU, WAND], [GALATEA, GALATEA_I]
    )
    allowed, held = _links(duel)
    assert len(allowed) == 1
    assert [w.code for w in held] == [ValidationCode.RULE_NOT_IMPLEMENTED]
    assert "엑스트라 덱 2장 중 1장이 같은 이유" in held[0].line_ko(
        with_scope=True
    )


@pytest.mark.real_card
def test_b06_a_full_extra_monster_zone_splits_into_two_answers(repository):
    """
    🔴 **놓을 자리가 없을 때 두 갈래로 갈린다** (§4).

    링크 몬스터가 없으면 가리키는 칸도 없으므로 **규칙이** 막는다. 있으면
    마커의 칸 기하를 옮기지 못해 **모른다** — 섞어 적으면 규칙 거절이 엔진
    미지원으로 집계된다.
    """
    #: ① 엑스트라 몬스터 존이 통상 몬스터로 찼다 → 규칙이 막는다.
    duel, _field, extra = _link_board(
        repository, [GIRSU, WAND], [GALATEA], emzone=(FEATHERMAN,)
    )
    allowed, held = _links(duel)
    assert allowed == []
    assert [w.code for w in held] == [ValidationCode.LINK_MATERIAL_INVALID]

    #: 소재를 기르수 + 『성장』 으로 **직접** 물으면 그 이유가 나온다.
    mine = duel.view(P0).player(P0)
    materials = tuple(
        card.instance_id
        for card in mine.zone(Zone.MZONE).occupied()
    )
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "링크 몬스터가 없습니다" in verdict.reason

    #: ② 같은 자리를 **링크 몬스터**가 차지하면 모른다.
    duel2, _f2, extra2 = _link_board(
        repository, [GIRSU, WAND], [GALATEA], emzone=(GALATEA_I,)
    )
    mine2 = duel2.view(P0).player(P0)
    materials2 = tuple(
        card.instance_id for card in mine2.zone(Zone.MZONE).occupied()
    )
    verdict2 = assess_link_materials(
        duel2.view(P0), P0, extra2[0], materials2
    )
    assert verdict2.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert verdict2.missing_rule == LINK_PLACEMENT_LINKED_RULE


@pytest.mark.real_card
def test_b07_a_link_monster_as_material_is_unknown(repository):
    """
    링크 몬스터를 소재로 쓰면 **링크 수치만큼 센다** — 그 규칙이 없으므로
    장수 계산을 할 수 없고, ``UNKNOWN`` 으로 거절한다.
    """
    duel, _field, extra = _link_board(
        repository, [GIRSU], [GALATEA], emzone=(GALATEA_I,)
    )
    mine = duel.view(P0).player(P0)
    materials = tuple(
        card.instance_id
        for zone in (Zone.MZONE, Zone.EMZONE)
        for card in mine.zone(zone).occupied()
    )
    assert len(materials) == 2
    verdict = assess_link_materials(duel.view(P0), P0, extra[0], materials)
    assert verdict.eligibility is LinkMaterialEligibility.UNDETERMINED
    assert verdict.missing_rule == LINK_MATERIAL_AS_LINK_RULE


@pytest.mark.real_card
def test_b08_the_summoned_card_must_be_a_link_monster_in_the_extra_deck(
    repository,
):
    """엑스트라 덱의 링크 몬스터가 아니면 **규칙이** 막는다."""
    duel, field, _extra = _link_board(repository, [GIRSU, WAND], [GALATEA])
    #: 필드의 몬스터를 링크 소환하려 한다.
    verdict = assess_link_materials(
        duel.view(P0), P0, field[0], (field[1],)
    )
    assert verdict.eligibility is LinkMaterialEligibility.ILLEGAL
    assert "링크 몬스터가 아닙니다" in verdict.reason


def test_b09_materials_are_not_targets_and_the_shape_is_checked():
    """
    🔴 **소재는 대상이 아니다** — 칸이 다르고, 모양 검사도 다르다.
    """
    from engine.ids import InstanceId

    action = PlayerAction.link_summon(
        P0, InstanceId(9), (InstanceId(1), InstanceId(2))
    )
    assert action.targets == ()
    assert action.materials == (InstanceId(1), InstanceId(2))

    #: 소재 없는 링크 소환 · 중복 소재 · 자기 소재는 **표현이 성립하지 않는다.**
    with pytest.raises(MalformedAction):
        PlayerAction.link_summon(P0, InstanceId(9), ())
    with pytest.raises(MalformedAction):
        PlayerAction.link_summon(P0, InstanceId(9), (InstanceId(1),) * 2)
    with pytest.raises(MalformedAction):
        PlayerAction.link_summon(P0, InstanceId(1), (InstanceId(1),))
    #: 소재를 받을 수 있는 종류는 링크 소환 하나다.
    with pytest.raises(MalformedAction):
        PlayerAction(
            kind=PlayerActionKind.NORMAL_SUMMON,
            actor=P0,
            source=InstanceId(1),
            materials=(InstanceId(2),),
        )


def test_b10_only_read_link_monsters_are_registered():
    """
    🔴 **등록은 하나이고 근거를 들고 있다.** 늘어나면 이 단언이 깨지고,
    그때 그 카드의 소재 조건을 **읽었는지** 사람이 확인해야 한다.
    """
    assert [rule.card_id for rule in LINK_MATERIAL_RULES] == [GALATEA]
    rule = LINK_MATERIAL_RULES[0]
    assert rule.count == 2
    assert rule.link_rating == 2
    assert rule.lua_file == "c30741503.lua"
    assert "Link.AddProcedure" in rule.lua_excerpt
    assert "matcheck" in rule.lua_excerpt
    assert rule.text_ko == "효과 몬스터 2장 (「오르페골」 몬스터를 포함)"


# ======================================================================
# C. 효과에 의한 특수 소환 — 권한이 넓어지지 않았다
# ======================================================================
@pytest.mark.real_card
def test_c01_the_player_declared_special_summon_is_still_unknown(repository):
    """
    🔴 **이 Phase 가 열지 **않은** 것.** 플레이어가 직접 선언하는 특수
    소환은 여전히 언제나 ``UNKNOWN`` 이다 — 효과에 의한 특수 소환과 다른
    절차이고, 구현한 절차에만 권한이 간다 (§4).
    """
    from engine.action_validation import (
        SPECIAL_SUMMON_CONDITION_RULE,
        ActionValidator,
    )

    duel, _field, _extra = _link_board(repository, [], [GALATEA])
    state = duel.state
    held = state.create_instance(WAND, owner=P0, zone=Zone.HAND)
    validator = ActionValidator(duel.view(P0))
    verdict = validator.validate(
        PlayerAction.special_summon(P0, held.instance_id)
    )
    assert verdict.validity is ActionValidity.UNKNOWN
    assert verdict.missing_rule == SPECIAL_SUMMON_CONDITION_RULE


@pytest.mark.real_card
def test_c02_a_card_in_the_graveyard_is_not_authorised(repository):
    """
    🔴 **소생 제한은 카드가 아니라 이력이다.** 묘지에서 나오는 특수 소환은
    확인된 카드여도 ``UNKNOWN`` 이다 — 소환 이력을 적는 자리가 없다.
    """
    from engine.condition import ConditionResult
    from engine.effect.library import OPERATION_RULINGS
    from engine.effect.ruling import (
        SUMMON_HISTORY_RULE,
        BoardRuling,
    )
    from engine.game_state_view import GameStateView

    duel, _field, _extra = _link_board(repository, [], [GALATEA])
    state = duel.state
    in_hand = state.create_instance(WAND, owner=P0, zone=Zone.HAND)
    in_grave = state.create_instance(WAND, owner=P0, zone=Zone.GRAVE)

    def ruling(instance, zone):
        view = GameStateView.from_state(
            state, viewer=P0, looked_at=frozenset({zone})
        )
        return BoardRuling(view, OPERATION_RULINGS)

    #: 패에서는 확인된 답이 나온다.
    told = ruling(in_hand.instance_id, Zone.HAND).explain_special_summon(
        in_hand.instance_id
    )
    assert told.answer is ConditionResult.TRUE

    #: 묘지에서는 모른다 — 그리고 **그 이유에 이름이 있다.**
    buried = ruling(in_grave.instance_id, Zone.GRAVE).explain_special_summon(
        in_grave.instance_id
    )
    assert buried.answer is ConditionResult.UNKNOWN
    assert SUMMON_HISTORY_RULE in buried.reason


@pytest.mark.real_card
def test_c03_an_unregistered_card_is_not_authorised(repository):
    """등록되지 않은 카드는 패에 있어도 ``UNKNOWN`` 이다 (ADR-006)."""
    from engine.condition import ConditionResult
    from engine.effect.library import OPERATION_RULINGS
    from engine.effect.ruling import BoardRuling
    from engine.game_state_view import GameStateView

    duel, _field, _extra = _link_board(repository, [], [GALATEA])
    state = duel.state
    #: 「오르페골 클리막스」 는 함정이고 ``MAY_BE_SPECIAL_SUMMONED`` 가
    #: 등록되어 있지 않다.
    held = state.create_instance(CRESCENDO, owner=P0, zone=Zone.HAND)
    view = GameStateView.from_state(
        state, viewer=P0, looked_at=frozenset({Zone.HAND})
    )
    told = BoardRuling(view, OPERATION_RULINGS).explain_special_summon(
        held.instance_id
    )
    assert told.answer is ConditionResult.UNKNOWN


@pytest.mark.real_card
def test_c04_a_full_monster_zone_makes_the_trigger_condition_false(
    repository,
):
    """
    🔴 **발동 조건이 거짓인 것과 판정할 수 없는 것은 다르다.**

    『성장』 ② 의 발동 조건은 「자신 몬스터 존에 빈 칸이 있다」 이고, 그것은
    **규칙이 답하는** 질문이다 — 몬스터 존을 다 채우면 거짓이 된다.
    """
    from engine.condition import ConditionContext, ConditionEvaluator
    from engine.effect.library import definition_registry
    from engine.ids import EffectRef

    duel, _field, _extra = _link_board(
        repository, [FEATHERMAN] * 5, [GALATEA]
    )
    definition = definition_registry().definition_for(EffectRef(WAND, 1))
    assert definition is not None
    verdict = ConditionEvaluator(duel.view(P0)).evaluate(
        definition.activation, ConditionContext(player=P0)
    )
    from engine.condition import ConditionResult

    assert verdict.result is ConditionResult.FALSE


# ======================================================================
# D. 1턴 1회 — 확인된 제한에만 쓴다
# ======================================================================
@pytest.mark.real_card
def test_d01_the_same_effect_cannot_be_activated_twice_in_a_turn(repository):
    """
    🔴 **제한을 **쓴 뒤**에 막는다** — 발동 시점에 세고, 둘째 발동을
    ``EFFECT_USE_LIMIT_REACHED`` 로 거절한다. 판은 그대로다.
    """
    from engine.ids import EffectRef

    setup, run = _run_line(repository)
    assert line_progress(run, ORCUST_GIRSU_LINE).completed
    duel = setup.duel
    state = duel.state

    #: 경로가 두 효과를 한 번씩 썼다 — 기록이 말한다.
    from analysis.effect_model import LimitScope

    assert state.uses.count(
        LimitScope.PER_CARD_NAME, (P0, GIRSU)
    ) == 1
    assert state.uses.count(LimitScope.PER_CARD_NAME, (P0, WAND)) == 1

    #: 묘지의 『성장』 에게 같은 효과를 다시 발동시켜 본다.
    buried = next(
        card for card in state.zone(P0, Zone.GRAVE) if card.card_id == WAND
    )
    before = state.state_hash()

    #: 🔴 **세 번째 관문만 떼어 본다.** 첫 관문(``ActionValidator``)은 이
    #: 자리에서 "사건이 뒷받침하지 않는다" 로 먼저 막으므로, 그것을 통과한
    #: 것으로 두고 **사용 제한 관문**에 묻는다. 그 허가를 손으로 만드는 것은
    #: 이 시험이 재려는 축이 아니기 때문이고, 통합 경로의 답은 아래
    #: ``test_d02`` 와 위의 ``state.uses`` 수가 잰다.
    from engine.validation import ValidationResult

    result = duel._activator.can_activate(
        state,
        duel.chain,
        PlayerAction.activate_effect(
            actor=P0,
            source=buried.instance_id,
            effect_ref=EffectRef(WAND, 1),
        ),
        authorization=ValidationResult.valid("시험이 첫 관문을 대신한다"),
    )
    assert result.code is ValidationCode.EFFECT_USE_LIMIT_REACHED
    assert result.validity is ActionValidity.INVALID
    assert "1턴에 1번" in result.reason
    assert state.state_hash() == before


@pytest.mark.real_card
def test_d02_the_limit_is_cleared_when_the_turn_changes(repository):
    """
    🔴 **리셋 시점도 이 Phase 가 들고 왔다.** 제한을 판정하기 시작한 쪽이
    비우는 자리도 함께 적는다 — 비우지 않으면 다음 턴에도 영원히 막힌다.
    """
    from analysis.effect_model import LimitScope
    from engine.turn_progression import TurnProgressor

    setup, _run = _run_line(repository)
    state = setup.duel.state
    assert state.uses.count(LimitScope.PER_CARD_NAME, (P0, GIRSU)) == 1

    before_turn = state.turn.turn_number
    #: 턴을 넘기는 자리를 **그 모듈에게** 맡긴다 — 손으로 비우지 않는다.
    progressor = TurnProgressor()
    for _ in range(8):
        if state.turn.turn_number != before_turn:
            break
        result = progressor.advance(state)
        assert result.advanced, result.describe_ko()
    assert state.turn.turn_number == before_turn + 1
    assert state.uses.count(LimitScope.PER_CARD_NAME, (P0, GIRSU)) == 0
    assert state.uses.count(LimitScope.PER_CARD_NAME, (P0, WAND)) == 0


def test_d03_an_effect_without_a_recorded_limit_is_untouched():
    """
    🔴 **읽지 않은 제한은 없는 것처럼 동작한다** (ADR-006). 그것이 지금
    사실이고, 어느 효과가 제한을 들고 있는지 수로 고정한다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    limited = {
        str(entry.effect_ref)
        for entry in EFFECT_LIBRARY
        if entry.definition.use_limit is not None
    }
    assert limited == {f"{GIRSU}:e[0]", f"{WAND}:e[1]"}, limited


# ======================================================================
# E. 보완8 회귀 — 고쳐 둔 구분이 그대로다
# ======================================================================
@pytest.mark.real_card
def test_e01_a_rule_refusal_is_not_counted_as_unsupported(repository):
    """
    🔴 **규칙이 막은 것은 미지원이 아니다** (보완6 · 보완8).

    소재 조건 위반은 ``missing`` 이 비어 있고, 소재 조건 미등록은 채워져
    있다 — 그 구분이 ``/combo`` 의 `미지원 사유` 목록을 가른다.
    """
    from deck.opening import unsupported_reasons

    illegal, _f1, _e1 = _link_board(
        repository, [GIRSU, FEATHERMAN], [GALATEA]
    )
    unread, _f2, _e2 = _link_board(repository, [GIRSU, WAND], [GALATEA_I])

    #: ① 소재 조건 위반은 **미지원 목록에 오르지 않는다.**
    illegal_lines = unsupported_reasons(illegal.legal_actions(P0))
    assert not any("link_summon" in line for line in illegal_lines), (
        illegal_lines
    )
    #: ② 소재 조건 미등록은 **오른다** — 근거가 생겨야 풀리는 자리다.
    unread_lines = unsupported_reasons(unread.legal_actions(P0))
    assert any(LINK_MATERIAL_RULE_MISSING in line for line in unread_lines)


@pytest.mark.real_card
def test_e02_the_run_separates_path_success_from_candidate_support(
    repository,
):
    """
    🔴 **경로를 끝까지 실행한 것과 후보 공간 전체를 지원하는 것은 다른
    질문이다** (§7).

    이 실행은 경로를 끝냈고(``completed``) 동시에 지원 범위의 한계를
    남긴다(``fully_supported is False``) — 둘을 한 값으로 뭉치면 둘 중
    하나가 거짓이 된다.
    """
    _setup, run = _run_line(repository)
    progress = line_progress(run, ORCUST_GIRSU_LINE)

    assert progress.completed is True
    assert run.fully_supported is False
    assert run.unsupported
    #: 남은 한계는 **소재 조건 미등록**과 ``activate_card`` 의 발동 타이밍이다.
    assert any(LINK_MATERIAL_RULE_MISSING in line for line in run.unsupported)


@pytest.mark.real_card
def test_e03_the_combo_answer_marks_the_execution_as_a_verification_policy(
    repository,
):
    """
    🔴 **검증용 정책으로 실행한 것을 자율 전략 AI 로 적지 않는다** (§5 · §9).

    🔴 **토큰 없는 응답 생성 검사다** — ``combo_messages`` 의 문자열을 센다.
    """
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repository):
            self.repository = repository

    blob = "\n".join(
        bot.combo_messages(
            _Agent(repository),
            ORCUST_GIRSU_LINE.hand_text(),
            recipe_text=ORCUST_VERIFICATION_RECIPE,
            line_text=ORCUST_GIRSU_LINE.name,
        )
    )
    assert "검증용 전개 정책" in blob
    assert "최선 전개 탐색도" in blob
    assert "엔진이 스스로 찾은 전개도 아닙니다" in blob
    assert "경로를 끝까지 실행했습니다 (4/4단계)" in blob
    #: 🔴 소재가 **이름으로** 보고에 남는다 (§7 — 무엇을 보냈는가).
    assert "소재 2장: 잭나이츠 오르페골 기르수 · 성유물－『성장』" in blob
    #: 🔴 **링크 몬스터가 보고의 판에 보인다** (Phase 6-AC 가 고친 결함).
    #: 실측: 그 전까지 이 표에 엑스트라 몬스터 존이 없어서 갈라테아가
    #: **보고에서 사라졌다** — 몬스터 존 0장으로 적히고 엑스트라 덱만 한 장
    #: 줄어 있어서, 읽는 쪽이 카드가 어디로 갔는지 알 수 없었다. 링크
    #: 소환이 실행되기 전에는 그 자리가 언제나 비어 있어 결함이 보이지
    #: 않았다.
    assert "엑스트라 몬스터 존: 1장 — 오르페골 갈라테아 [30741503]" in blob
    assert "몬스터 존: 0장 — 없음" in blob
    #: 🔴 실제 실행과 정적 계획이 갈린다 — 그 경계 문장도 그대로다.
    assert "아래는 실행하지 않은 정적 계획입니다" in blob


@pytest.mark.real_card
def test_e04_an_unknown_line_name_is_not_silently_replaced(repository):
    """
    🔴 **비슷한 것을 골라 주지 않는다.** 요청한 경로가 아닌 것으로 검증한
    결과를 보여 주면 사용자는 그 경로가 돌았다고 읽는다.
    """
    import app.discord_bot as bot

    class _Agent:
        def __init__(self, repository):
            self.repository = repository

    blob = "\n".join(
        bot.combo_messages(
            _Agent(repository),
            ORCUST_GIRSU_LINE.hand_text(),
            recipe_text=ORCUST_VERIFICATION_RECIPE,
            line_text="orcust",
        )
    )
    assert "라는 검증용 전개 경로가 없습니다" in blob
    assert "기본 선택 방식" in blob
    assert "검증용 전개 정책 `orcust-girsu`" not in blob
    assert line_named("orcust") is None
    assert line_named(ORCUST_GIRSU_LINE.name) is ORCUST_GIRSU_LINE


# ======================================================================
# F. 정책 — 엔진을 우회하지 않는다
# ======================================================================
def test_f01_the_policy_never_builds_an_action():
    """
    🔴 **AST 로 센다.** 정책 모듈이 ``PlayerAction`` 을 **만들지 않는다** —
    만들 수 있으면 엔진이 허가하지 않은 행동을 고를 길이 생긴다.
    """
    source = pathlib.Path("deck/combo_policy.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlayerAction"
    ]
    assert built == []
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    #: ``PlayerAction`` 의 편의 생성자 이름도 쓰지 않는다.
    assert not attribute_calls & {
        "link_summon",
        "normal_summon",
        "special_summon",
        "activate_effect",
        "set_spell_trap",
        "set_monster",
    }
    #: 판을 바꾸는 이름도 없다.
    assert "state.move" not in source
    assert "duel.apply" not in source


def test_f02_the_policy_has_no_state_so_a_fork_cannot_be_polluted():
    """
    🔴 **상태가 없다.** cursor 도 trace 도 없으므로 사본에 같은 정책을 그대로
    써도 원본과 서로 간섭하지 않는다 (§5).
    """
    assert dataclasses.is_dataclass(VerificationLinePolicy)
    params = VerificationLinePolicy.__dataclass_params__
    assert params.frozen is True
    fields = {f.name for f in dataclasses.fields(VerificationLinePolicy)}
    assert fields == {"line", "then"}
    assert not {"cursor", "index", "done", "trace", "history"} & fields


@pytest.mark.real_card
def test_f03_the_policy_stops_when_the_expected_action_is_absent(repository):
    """
    🔴 **기대한 행동이 후보에 없으면 조용히 다른 것을 고르지 않는다** —
    ``None`` 을 돌려주고 호출자가 멈추며, 그 자리가 기록에 남는다.
    """
    #: 패에 기르수가 없으면 1 단계부터 고를 것이 없다.
    hand = [703897, 2930675, 12989604, 93920420, 93920420]
    _setup, run = _run_line(repository, hand=hand)
    progress = line_progress(run, ORCUST_GIRSU_LINE)

    assert progress.completed is False
    assert progress.done == 0
    assert progress.blocked_at is ORCUST_GIRSU_LINE.steps[0]
    assert run.stopped_kind == "not_chosen"
    assert "검증용 선택 방식이 고를 행동을 찾지 못했습니다" in run.stopped_reason


@pytest.mark.real_card
def test_f04_first_meaningful_is_unchanged_and_still_the_default(repository):
    """
    🔴 **다른 요청의 행동 선택을 조용히 바꾸지 않았다** (§5).

    ``choose`` 를 주지 않으면 ``first_meaningful`` 이 쓰이고, 그 함수의
    순서에는 ``link_summon`` 이 **없다** — 이 Phase 가 그것을 넣지 않았다.
    """
    import inspect

    source = inspect.getsource(first_meaningful)
    assert "LINK_SUMMON" not in source
    assert "검증용 선택 방식" in source

    #: 기본값으로 돌리면 경로의 넷째 단계까지 가지 않는다.
    _setup, run = _run_line(repository, choose=first_meaningful)
    progress = line_progress(run, ORCUST_GIRSU_LINE)
    assert progress.completed is False
    assert progress.done == 3
    assert progress.blocked_at is ORCUST_GIRSU_LINE.steps[3]


def test_f05_the_planned_step_compares_card_ids_not_instances():
    """
    🔴 **인스턴스 번호로 경로를 적지 않는다** — 판을 만들 때마다 달라지므로
    같은 레시피로도 재현되지 않는다.
    """
    for step in ORCUST_GIRSU_LINE.steps:
        #: 🔴 정규 표현에 **정수 · 문자열 · ``None`` 만** 들어간다 — 객체
        #: 참조가 들어가면 같은 경로가 판마다 다른 값이 된다.
        for value in step.canonical_state():
            assert _is_plain(value), (step.kind, value)
        assert step.kind in {kind.value for kind in PlayerActionKind}
    source = pathlib.Path("deck/combo_policy.py").read_text(encoding="utf-8")
    assert "InstanceId(" not in source
    #: 단계마다 **사람이 읽는 줄**이 있다.
    assert all(step.label for step in ORCUST_GIRSU_LINE.steps)
    #: 경로는 근거를 들고 있다.
    assert "c69811710.lua" in ORCUST_GIRSU_LINE.basis
    assert "c93920420.lua" in ORCUST_GIRSU_LINE.basis
    assert "c30741503.lua" in ORCUST_GIRSU_LINE.basis


def test_f06_a_planned_step_with_no_filter_is_still_expressible():
    """
    ``PlannedAction`` 의 빈 칸은 "그 축으로 거르지 않는다" 이고, 알 수 없는
    종류 이름은 **만들 때** 거절한다.
    """
    loose = PlannedAction(kind="end_phase")
    assert loose.describe_ko() == "end_phase"
    with pytest.raises(ValueError):
        PlannedAction(kind="link-summon")
    with pytest.raises(ValueError):
        PlannedAction(kind="activate_effect", effect_ref=(1,))


# ======================================================================
# G. 레시피 — 명시적으로 제공하는 검증 자료다
# ======================================================================
@pytest.mark.real_card
def test_g01_the_recipe_is_a_normal_deck_with_no_filler(repository):
    """
    🔴 **정상 범위 · 매수 3 이하 · 한 카드 메우기 없음** (§6).
    """
    parsed = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository)
    assert parsed.unresolved == []
    draft = parsed.draft
    assert draft is not None

    main = {slot.card_id: slot.copies for slot in draft.main}
    extra = {slot.card_id: slot.copies for slot in draft.extra}
    assert sum(main.values()) == 40
    assert sum(extra.values()) == 6
    #: 🔴 **한 카드를 25장 넣은 메우기가 없다.**
    assert max(main.values()) <= 3
    assert max(extra.values()) <= 3
    #: 서로 다른 카드가 충분히 많다 — 메우기면 이 수가 작아진다.
    assert len(main) >= 12

    #: 경로가 쓰는 카드가 다 있다.
    assert main[GIRSU] >= 1
    assert main[WAND] >= 2  # 하나는 패에, 하나는 덱에 있어야 한다
    assert extra[GALATEA] == 1


@pytest.mark.real_card
def test_g02_the_specified_hand_fits_inside_the_recipe(repository):
    """지정한 패가 레시피의 매수 안에 든다 — 그 검사를 엔진이 한다."""
    from deck.opening import check_hand_against_recipe

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    findings, rest = check_hand_against_recipe(
        list(ORCUST_VERIFICATION_HAND), draft, repository
    )
    violations = [f for f in findings if f.outcome.name == "VIOLATION"]
    assert violations == [], [f.detail for f in violations]
    assert len(rest) == 35


def test_g03_the_recipe_is_not_used_unless_the_user_sends_one():
    """
    🔴 **레시피를 생략했을 때 자동으로 쓰이지 않는다** (§6).

    경로가 재현 입력을 **들고 있는** 것과 그것이 **자동으로 쓰이는** 것은
    다르다. 전달 경로에 그 상수의 이름이 없다는 사실로 고정한다.
    """
    for path in ("app/discord_bot.py", "app/main.py", "deck/opening.py"):
        source = pathlib.Path(path).read_text(encoding="utf-8")
        assert "ORCUST_VERIFICATION_RECIPE" not in source, path
        assert "ORCUST_VERIFICATION_HAND" not in source, path


def test_g04_no_format_legality_is_claimed():
    """
    🔴 **금제를 확인하지 않았으므로 "대회 합법 덱" 이라고 부르지 않는다**
    (§3 · §6).
    """
    source = pathlib.Path("deck/combo_policy.py").read_text(encoding="utf-8")
    #: 🔴 **확인하지 않았다는 사실을 적는다.**
    assert "금제를 확인하지 않았다" in source
    assert "금제 · 포맷 적법성을 주장하지 않는다" in source
    #: 🔴 **주장하는 문장이 없다.** "대회 합법" 이라는 낱말이 나오는 자리는
    #: 전부 **부정문**이어야 한다 — 그 낱말을 금지하면 부정문도 쓸 수 없다.
    for line in source.splitlines():
        if "대회 합법" in line:
            assert "않는다" in line or "않았다" in line, line
    assert "검증용" in ORCUST_GIRSU_LINE.note
    assert ORCUST_GIRSU_LINE.reproduction_ready is True
    assert set(COMBO_LINES) == {"orcust-girsu"}
