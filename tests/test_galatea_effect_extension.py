"""
Phase 6-BF — **오르페골 갈라테아 ② 를 실제 엔진으로 해결한다.**

이 파일이 지키는 것
-------------------
1. **올바른 조건에서만 후보가 된다** — 제외된 앞면 기계족이 있어야 하고,
   바벨이 앞면으로 깔려 있으면 안 되고, 카드명 기준 1턴 1번이다.
2. **고른 것이 허용 후보 안이다** — 되돌릴 대상도, 세트할 카드도.
3. **판과 사건 기록이 실제로 바뀐다** — 덱으로 되돌아가고, 섞이고, 그
   카드에 맞는 존에 뒷면으로 놓이고, 세트한 턴이 적힌다.
4. **모르는 것을 허가로 바꾸지 않는다** — 되돌릴 수 있는지 · 세트할 수
   있는지가 등재되지 않은 카드는 거절된다.
5. **세트는 발동이 아니다** — 놓은 것으로 끝이고, 발동 가능성을 주장하지
   않는다.
6. **기존 동작이 그대로다** — 기르수 · 디베르 · 스켈레촌 · 토큰 ·
   롱기르수의 후보와 보류가 6-BF 전후로 같다.

🔴 **고정 수순을 정답으로 넣지 않는다.** 아래 구동기는 **그 자리의 허용
후보에서** 행동을 찾고, 없으면 멈춘다 — 비슷한 행동으로 메꾸지 않는다.
정답 수순을 주입하는 것이 아니라, 엔진이 실제로 그 후보를 냈는지 보는 것이
이 시험들의 전부다.
"""

import pytest

from tests.conftest import requires_official_db

pytestmark = [requires_official_db, pytest.mark.real_card]

GIRSU = 69811710
HARP_HORROR = 57835716
CYMBAL_SKELETON = 21441617
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
BABEL = 90351981
CLIMAX = 703897
ORCUST_HAND = [GIRSU, 14558127, 23434538, 10045474, 24224830]

#: 갈라테아 ② 의 ``EffectRef`` — ``script.effects`` 의 ``e2`` 가 1번이다.
GALATEA_SECOND = (GALATEA, 1)


# ======================================================================
# 구동기 — 허용 후보에서만 고른다
# ======================================================================
def _draft(repository):
    from pathlib import Path

    from deck.recipe import parse_recipe

    text = (Path(__file__).resolve().parent.parent
            / "docs" / "orcust-azamina-note.ydk").read_text(encoding="utf-8")
    return parse_recipe(text, repository).draft


def _setup(repository, prefer=()):
    """같은 입력으로 초기 상태를 만든다. ``prefer`` 는 **검증용** 선택이다.

    🔴 ``PreferredCardChoice`` 는 **받은 목록 안에서만** 집는다 — 적어 둔
    카드가 그 자리에 없으면 뒤의 정책에게 넘기고, 이 시험들은 그때
    "찾지 못했다" 로 멈춘다.
    """
    from agent.choice import FirstPermittedChoice, PreferredCardChoice
    from deck.opening import build_opening
    from integration.autonomy import PolicyChooser, TriggerSource
    from integration.trigger_registry import TriggerPreparation

    policy = FirstPermittedChoice()
    if prefer:
        policy = PreferredCardChoice(tuple(prefer), policy)
    triggers = TriggerSource(repository=repository,
                             preparation=TriggerPreparation(repository))
    return build_opening(
        repository, _draft(repository), list(ORCUST_HAND),
        chooser=PolicyChooser(policy), triggers=triggers,
    )


def _advance_to_open(duel, limit=40):
    """필수 흐름(패스)만 지나간다. 판을 바꾸는 선택은 하지 않는다."""
    from engine.action import PlayerActionKind

    for _ in range(limit):
        duel.advance()
        legal = duel.legal_actions(duel.to_act)
        if {action.kind.value for action in legal.allowed} != {"pass"}:
            return legal
        duel.apply(next(a for a in legal.allowed
                        if a.kind is PlayerActionKind.PASS))
    raise AssertionError("흐름만 도는 자리에서 벗어나지 못했습니다")


def _take(duel, want, label):
    """그 자리의 **허용 후보**에서 찾아 수행한다. 없으면 실패한다."""
    from deck.opening import _settle_chain

    legal = _advance_to_open(duel)
    hit = next((a for a in legal.allowed if want(a.canonical_state())), None)
    assert hit is not None, (
        f"{label} 를 허용 후보에서 찾지 못했습니다: "
        + "; ".join(str(a.canonical_state()) for a in legal.allowed)
        + " / 보류: "
        + "; ".join(f"{w.kind.value}: {w.reason}" for w in legal.withheld)
    )
    step = duel.apply(hit)
    if step.accepted and duel.priority.is_open:
        settled, resolved = _settle_chain(duel, lambda legal, seat=None: ())
        return step, settled, resolved
    return step, None, None


def _is(kind, **fields):
    index = {"actor": 1, "source": 2, "targets": 3, "effect": 4}

    def check(key):
        if key[0] != kind:
            return False
        return all(key[index[name]] == value for name, value in fields.items())

    return check


def _to_galatea(repository, prefer=()):
    """🔴 **네 걸음 전부 허용 후보에서 나온다.** 갈라테아가 선 판을 만든다."""
    setup = _setup(repository, prefer=(HARP_HORROR,) + tuple(prefer))
    duel = setup.duel
    assert setup.can_run, setup.refusal
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    _take(duel, _is("activate_effect", effect=(HARP_HORROR, 0)), "디베르 ①")
    _take(duel, lambda k: k[0] == "link_summon" and k[2] == 83,
          "갈라테아 링크 소환")
    return setup, duel


def _zone_ids(duel, zone, seat=0):
    from engine.vocabulary import Zone

    holder = duel.state.zone(seat, Zone[zone] if isinstance(zone, str) else zone)
    return [card.instance_id.value for card in holder.cards()]


# ======================================================================
# A. 후보 생성 — 올바른 조건에서
# ======================================================================
def test_a01_the_second_effect_becomes_a_candidate_with_a_banished_machine(
        repository):
    """
    🔴 **실제 엔진이 후보를 낸다** — 제외된 앞면 기계족 하나를 대상으로.

    대상은 디베르다: ① 의 **비용**이 자기 자신을 묘지에서 제외했고, 그
    제외는 ``Position.FACEUP`` 으로 놓인다 (6-BF 가 고친 자리 —
    ``engine.payment.COST_LANDING_POSITION``). 공식 필터가 그 자리에서
    ``c:IsFaceup()`` 을 묻는다.
    """
    _, duel = _to_galatea(repository)
    legal = _advance_to_open(duel)
    offered = [a.canonical_state() for a in legal.allowed
               if a.canonical_state()[0] == "activate_effect"
               and a.canonical_state()[4] == GALATEA_SECOND]
    assert offered, (
        "갈라테아 ② 가 후보에 없습니다. 허용: "
        + "; ".join(str(a.canonical_state()) for a in legal.allowed)
        + " / 보류: "
        + "; ".join(f"{w.kind.value}: {w.reason}" for w in legal.withheld)
    )
    #: 🔴 **대상이 발동 시점에 붙어 있다** (``EFFECT_FLAG_CARD_TARGET``).
    #: 세트할 카드는 여기 **없다** — 그쪽은 해결 중에 고른다.
    targets = offered[0][3]
    assert len(targets) == 1, targets
    from engine.ids import InstanceId

    chosen = duel.state.find_instance(InstanceId(targets[0][1]))
    assert chosen is not None and chosen.card_id == HARP_HORROR
    definition = repository.get(chosen.card_id)
    assert definition.race_name == "MACHINE", definition.race_name
    assert chosen.is_faceup, chosen.position


def test_a02_the_banished_cost_card_lands_face_up(repository):
    """
    🔴 **비용으로 제외된 카드가 앞면이다** — 6-BF 가 고친 한 자리.

    왜 사실인가: 저장소의 카드 스크립트에서 「묘지의 이 카드를 제외하고」
    를 비용으로 치르는 자리는 ``Duel.Remove(c,POS_FACEUP,REASON_COST)``
    다. 이 시험은 그 자리의 **값**을 재고, 다른 목적지(묘지 · 패 · 덱)는
    한 글자도 건드리지 않았다는 사실도 함께 잡는다.
    """
    from engine.payment import COST_LANDING_POSITION
    from engine.cost import CostSemantics
    from engine.vocabulary import Position, Zone

    setup = _setup(repository, prefer=(HARP_HORROR,))
    duel = setup.duel
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    #: 묘지에 있을 때는 **앞면이 아니다** — 덱에서 묘지로 간 카드의 표시
    #: 형식은 이 저장소에서 뜻을 갖지 않는다 (그 자리는 고치지 않았다).
    grave = duel.state.zone(0, Zone.GRAVE).cards()
    assert [c.card_id for c in grave] == [HARP_HORROR], grave
    _take(duel, _is("activate_effect", effect=(HARP_HORROR, 0)), "디베르 ①")
    banished = duel.state.zone(0, Zone.REMOVED).cards()
    assert [c.card_id for c in banished] == [HARP_HORROR]
    assert banished[0].position is Position.FACEUP
    #: 🔴 **표가 제외 하나만 적는다.** 다른 비용 의미는 표에 없고, 없으면
    #: ``GameState.move`` 가 표시 형식을 건드리지 않는다.
    assert COST_LANDING_POSITION == {CostSemantics.BANISH: Position.FACEUP}


def test_a03_babel_on_the_field_closes_the_ignition_branch(repository):
    """
    🔴 **``s.tdcon1`` 을 옮겼다** — 바벨이 앞면으로 있으면 ② 는 발동할 수
    없고, ③(유발즉시)은 등재되지 않았으므로 **어느 쪽도** 열리지 않는다.

    공식에서는 그때 ③ 이 쓰이지만 이 저장소는 그 분류를 허가하지 않는다
    (``ACTIVATION_KINDS_IN_SCOPE`` · ADR-006). 즉 **덜 허가하는 쪽**이고,
    이 시험이 그 사실을 적어 둔다.
    """
    from engine.ids import InstanceId
    from engine.vocabulary import Position, Zone

    _, duel = _to_galatea(repository)
    #: 바벨을 **앞면으로** 필드 존에 둔다 — 세트(뒷면)가 아니다.
    deck = duel.state.zone(0, Zone.DECK)
    babel = next(c for c in deck.cards() if c.card_id == BABEL)
    duel.state.move(babel, Zone.FZONE, to_player=0,
                    position=Position.FACEUP)
    legal = _advance_to_open(duel)
    allowed = [a.canonical_state() for a in legal.allowed
               if a.canonical_state()[4] == GALATEA_SECOND]
    assert allowed == [], allowed
    held = [w.reason for w in legal.withheld
            if str(GALATEA) in w.reason]
    assert held, [w.reason for w in legal.withheld]
    assert "발동 조건" in held[0], held[0]


def test_a04_the_effect_is_once_per_turn_by_card_name(repository):
    """🔴 ``e2:SetCountLimit(1,id)`` — 같은 **이름** 기준으로 1턴에 1번."""
    _, duel = _to_galatea(repository, prefer=(BABEL,))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")
    legal = _advance_to_open(duel)
    assert not [a for a in legal.allowed
                if a.canonical_state()[4] == GALATEA_SECOND]
    held = [w.reason for w in legal.withheld if str(GALATEA) in w.reason]
    assert held and "1턴에 1번" in held[0], held


# ======================================================================
# B. 고른 것이 허용 후보 안이다
# ======================================================================
def test_b01_both_orcust_spelltraps_are_offered_and_neither_is_forced(
        repository):
    """
    🔴 **갈래가 둘 다 남는다** — 바벨(필드 마법)과 클리막스(카운터 함정).

    어느 쪽도 정답이 아니다. 이 시험은 **두 장 모두 허용 후보**라는 사실만
    잡고, 어느 쪽이 더 강한지는 말하지 않는다.
    """
    from engine.condition import ConditionResult

    setups = {}
    for want in (BABEL, CLIMAX):
        setup, duel = _to_galatea(repository, prefer=(want,))
        _take(duel, _is("activate_effect", effect=GALATEA_SECOND),
              f"갈라테아 ② ({want})")
        record = next(r for r in setup.chooser.records
                      if getattr(r.target_ref, "name", "") == "set")
        permitted = sorted(c.card_id for c in record.offer.permitted)
        assert permitted == sorted((BABEL, CLIMAX)), permitted
        for candidate in record.offer.candidates:
            assert candidate.verdict is ConditionResult.TRUE, candidate
        #: 🔴 **고른 것이 그 목록 안이다.**
        picked = [duel.state.find_instance(i).card_id for i in record.chosen]
        assert picked == [want], picked
        setups[want] = duel
    #: 🔴 **놓인 자리가 다르다** — 카드가 정한다.
    assert _zone_ids(setups[BABEL], "SZONE") == []
    assert len(_zone_ids(setups[BABEL], "FZONE")) == 1
    assert len(_zone_ids(setups[CLIMAX], "SZONE")) == 1
    assert _zone_ids(setups[CLIMAX], "FZONE") == []


def test_b02_the_set_choice_happens_during_resolution(repository):
    """
    🔴 **대상 지정과 해결 중 선택을 가른다.** 되돌릴 카드는 발동 시점에
    행동의 ``targets`` 로 고정되고, 세트할 카드는 **해결 중의 선택 기록**에
    남는다 — 두 사실이 다른 자리에 적힌다.
    """
    setup, duel = _to_galatea(repository, prefer=(CLIMAX,))
    legal = _advance_to_open(duel)
    action = next(a for a in legal.allowed
                  if a.canonical_state()[4] == GALATEA_SECOND)
    assert len(action.canonical_state()[3]) == 1
    #: 발동 **전**까지 물은 선택의 수 — 그 뒤에 물은 것만 센다.
    before = len(setup.chooser.records)
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")
    asked = [r for r in setup.chooser.records[before:]]
    refs = [getattr(r.target_ref, "name", "") for r in asked]
    assert refs == ["set"], refs


# ======================================================================
# C. 판과 사건 기록
# ======================================================================
def test_c01_the_resolution_moves_the_board_and_writes_the_journal(repository):
    """🔴 **되돌리기 · 섞기 · 세트가 전부 판과 기록에 있다.**"""
    from engine.vocabulary import Position, Zone

    setup, duel = _to_galatea(repository, prefer=(BABEL,))
    before = len(list(setup.journal))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")

    #: ① 제외 자리가 비었다.
    assert _zone_ids(duel, "REMOVED") == []
    #: ② 그 카드가 **메인 덱**으로 돌아갔다 (엑스트라가 아니다).
    deck = duel.state.zone(0, Zone.DECK).cards()
    assert sum(1 for c in deck if c.card_id == HARP_HORROR) == 3
    #: ③ 바벨이 **필드 존**에 뒷면으로 놓였다.
    field = duel.state.zone(0, Zone.FZONE).cards()
    assert [c.card_id for c in field] == [BABEL]
    assert field[0].position is Position.FACEDOWN
    assert not field[0].is_faceup
    assert field[0].controller == 0

    events = list(setup.journal)[before:]
    kinds = [d.to_dict()["kind"] for ev in events
             for d in getattr(ev, "deltas", ())]
    assert kinds.count("zone_moved") >= 1
    assert "zone_shuffled" in kinds
    assert kinds.count("card_set") == 1, kinds
    set_delta = next(d.to_dict() for ev in events
                     for d in getattr(ev, "deltas", ())
                     if d.to_dict()["kind"] == "card_set")
    assert set_delta["to_zone"] == "FZONE"
    assert set_delta["position"] == "FACEDOWN"
    assert set_delta["summoned"] is False
    #: 🔴 **세트는 파괴도 송치도 아니다** — 주장할 이유가 없다.
    assert set_delta.get("reasons", []) == []


def test_c02_the_set_card_is_recorded_as_set_this_turn(repository):
    """
    🔴 **패에서 세트한 것과 같은 이름으로 적힌다**
    (``RuleActionKind.SET_SPELL_TRAP``). 그래서 카드 종류별 세트 · 발동
    제한을 보는 기존 계층이 **고치지 않고** 이 세트도 본다.
    """
    from engine.state.rule_usage import RuleActionKind
    from engine.vocabulary import Zone

    _, duel = _to_galatea(repository, prefer=(CLIMAX,))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")
    state = duel.state
    placed = state.zone(0, Zone.SZONE).cards()[0]
    turn = state.turn.turn_number
    assert state.rule_uses.used_card(
        turn, 0, placed.instance_id, RuleActionKind.SET_SPELL_TRAP)
    assert state.rule_uses.count_card(
        turn, 0, placed.instance_id, RuleActionKind.SET_SPELL_TRAP) == 1
    #: 🔴 **패의 카드에는 적히지 않았다** — 효과가 세트한 것 하나뿐이다.
    for card in state.zone(0, Zone.HAND).cards():
        assert not state.rule_uses.used_card(
            turn, 0, card.instance_id, RuleActionKind.SET_SPELL_TRAP)


def test_c03_setting_is_not_activating(repository):
    """
    🔴 **세트한 카드가 발동 후보로 올라오지 않는다.**

    이 시험은 "발동할 수 없다" 를 주장하지 않는다 — 이 저장소에
    ``activate_card`` 의 발동 타이밍 계층이 없어서 그 종류 자체가 **보류**로
    남는다는 사실을 잡는다. 둘은 다른 말이다.
    """
    _, duel = _to_galatea(repository, prefer=(CLIMAX,))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")
    legal = _advance_to_open(duel)
    assert not [a for a in legal.allowed
                if a.canonical_state()[0] == "activate_card"]
    held = [w for w in legal.withheld if w.kind.value == "activate_card"]
    assert held, [w.kind.value for w in legal.withheld]
    assert "규칙 계층" in held[0].reason, held[0].reason


# ======================================================================
# D. 모르는 것을 허가로 바꾸지 않는다
# ======================================================================
def test_d01_an_extra_deck_monster_target_is_refused_not_invented(repository):
    """
    🔴 **엑스트라 덱 몬스터는 덱으로 돌아가지 않는다** — 그 자리가 이
    저장소에 없으므로 **거절한다** (Phase 6-M 의
    ``MISSING_EXTRA_DECK_DESTINATION``).

    ``s.tdfilter`` 는 ``IsAbleToDeck`` 만 보고 메인 · 엑스트라를 가리지
    않지만, 실제 처리에서 엑스트라 덱 몬스터는 **엑스트라 덱으로** 간다.
    지어내 통과시키지 않았다는 것이 이 시험의 전부다.
    """
    from engine.vocabulary import Position, Zone

    setup, duel = _to_galatea(repository)
    #: 제외 상태에 **앞면 엑스트라 덱 기계족**을 하나 놓는다.
    extra = duel.state.zone(0, Zone.EXTRA)
    spare = next(c for c in extra.cards() if c.card_id == GALATEA)
    duel.state.move(spare, Zone.REMOVED, to_player=0,
                    position=Position.FACEUP)
    assert repository.get(GALATEA).race_name == "MACHINE"
    assert repository.get(GALATEA).is_extra_deck

    legal = _advance_to_open(duel)
    offers = [a for a in legal.allowed
              if a.canonical_state()[4] == GALATEA_SECOND]
    picked = next((a for a in offers
                   if a.canonical_state()[3][0][1] == spare.instance_id.value),
                  None)
    assert picked is not None, [a.canonical_state() for a in offers]
    before = duel.state.state_hash()
    step = duel.apply(picked)
    settled = None
    if step.accepted and duel.priority.is_open:
        from deck.opening import _settle_chain
        settled, _ = _settle_chain(duel, lambda legal, seat=None: ())
    said = (settled.reason if settled is not None else step.reason)
    #: 🔴 **거절 문장이 "지어내지 않는다" 를 말한다.** 이름
    #: (``MISSING_EXTRA_DECK_DESTINATION``) 은 결과의 ``missing`` 칸에
    #: 실리고, 체인 해결의 문장에는 그 이유가 풀어 적힌다.
    assert "엑스트라 덱 몬스터" in said, said
    assert "지어내지 않습니다" in said, said
    #: 🔴 **판이 하나도 바뀌지 않았다** — 계획 단계에서 멈췄다 (ADR-008).
    assert _zone_ids(duel, "FZONE") == []
    assert _zone_ids(duel, "SZONE") == []
    assert spare.instance_id.value in _zone_ids(duel, "REMOVED")


def test_d02_an_unregistered_set_candidate_is_not_waved_through(repository):
    """
    🔴 **``Card.IsSSetable`` 이 등재되지 않은 카드는 세트되지 않는다.**

    등재부에서 바벨 · 클리막스의 답을 **빼고** 같은 경로를 돈다. 그러면
    두 후보가 ``UNKNOWN`` 이 되고, ``UNKNOWN`` 은 허가가 아니므로 고를 수
    없다.

    🔴 **그때 효과 전체가 거절되고 판은 그대로다** — 세트만 생략되는 것이
    아니다. 생략 범위(``NoCandidateScope.TARGET_OPERATIONS``)는 **엔진이
    후보를 0장으로 센** 갈래의 것이고 (``test_d04``), 이쪽은 엔진이 후보를
    둘 세었는데 **그것을 움직일 수 있는지 모르는** 갈래다. 두 공백은 고칠
    자리가 다르므로 (앞은 덱의 내용, 뒤는 등재부) 결과도 섞지 않는다.
    """
    from engine.condition import ConditionResult
    from engine.effect import library as lib
    from engine.effect.ruling import OperationRulingRegistry
    from engine.effect.semantics import RuleQuestion

    import dataclasses

    trimmed = []
    for card_id in lib.OPERATION_RULINGS.card_ids:
        facts = lib.OPERATION_RULINGS.facts_for(card_id)
        if card_id in (BABEL, CLIMAX):
            answers = {q: f for q, f in facts.answers.items()
                       if q is not RuleQuestion.MAY_BE_SET}
            facts = dataclasses.replace(facts, answers=answers)
        trimmed.append(facts)
    narrowed = OperationRulingRegistry(tuple(trimmed))

    import integration.autonomy as autonomy
    original = autonomy._rulings
    autonomy._rulings = lambda: narrowed
    try:
        setup, duel = _to_galatea(repository, prefer=(BABEL,))
        _take(duel, _is("activate_effect", effect=GALATEA_SECOND),
              "갈라테아 ②")
        record = next(r for r in setup.chooser.records
                      if getattr(r.target_ref, "name", "") == "set")
        assert record.offer.permitted == ()
        assert all(c.verdict is ConditionResult.UNKNOWN
                   for c in record.offer.candidates)
        assert record.chosen == ()
    finally:
        autonomy._rulings = original
    #: 🔴 **판이 하나도 바뀌지 않았다** — 계획 단계에서 멈췄다 (ADR-008).
    assert _zone_ids(duel, "REMOVED") == [16]
    assert _zone_ids(duel, "FZONE") == []
    assert _zone_ids(duel, "SZONE") == []


def test_d04_an_empty_deck_of_orcust_spelltraps_skips_only_the_set(repository):
    """
    🔴 **세트할 후보가 0장이면 세트만 생략한다** — 되돌리기와 섞기는 한다.

    공식 처리의 ``if #g>0 and SelectYesNo`` 가 ``SendtoDeck`` **뒤**에
    있으므로 그 범위가 ``TARGET_OPERATIONS`` 다. 덱의 「오르페골」 마법 ·
    함정을 전부 치우고 같은 경로를 돈다.
    """
    from engine.vocabulary import Zone

    setup, duel = _to_galatea(repository)
    deck = duel.state.zone(0, Zone.DECK)
    for card in list(deck.cards()):
        if card.card_id in (BABEL, CLIMAX):
            duel.state.move(card, Zone.GRAVE, to_player=1)
    assert not [c for c in duel.state.zone(0, Zone.DECK).cards()
                if c.card_id in (BABEL, CLIMAX)]

    before = len(list(setup.journal))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")
    #: 🔴 **되돌리기와 섞기는 일어났다.**
    assert _zone_ids(duel, "REMOVED") == []
    kinds = [d.to_dict()["kind"] for ev in list(setup.journal)[before:]
             for d in getattr(ev, "deltas", ())]
    assert "zone_moved" in kinds
    assert "zone_shuffled" in kinds
    #: 🔴 **세트만 일어나지 않았다.**
    assert "card_set" not in kinds, kinds
    assert _zone_ids(duel, "FZONE") == []
    assert _zone_ids(duel, "SZONE") == []


def test_d03_the_target_gate_asks_the_right_question_per_name(repository):
    """
    🔴 **이름마다 다른 관문을 묻는다** (6-BF 가 고친 자리).

    6-BF 전의 ``_movement_question`` 은 정의의 **첫** 관문 하나를 모든
    이름에 걸었다. 갈라테아 ② 는 이름이 둘이므로 세트 후보에게 「덱으로
    되돌릴 수 있는가」 가 걸렸고, 덱에 있는 카드는 그 답이 참이 아니어서
    후보가 0장이 되었다 — 규칙이 막은 것이 아니라 **다른 질문을 물은**
    것이다.
    """
    from engine.effect.library import EFFECT_LIBRARY
    from engine.effect.semantics import RuleQuestion
    from engine.effect.target import PRIMARY_TARGET, TargetRef
    from integration.autonomy import _movement_question

    definition = next(e.definition for e in EFFECT_LIBRARY
                      if e.definition.effect_ref.card_id == GALATEA)
    assert _movement_question(definition, PRIMARY_TARGET) is \
        RuleQuestion.MAY_BE_RETURNED_TO_DECK
    assert _movement_question(definition, TargetRef("set")) is \
        RuleQuestion.MAY_BE_SET
    #: 🔴 ``ref`` 를 주지 않으면 6-BF 이전과 **똑같다** — 첫 관문이다.
    assert _movement_question(definition) is \
        RuleQuestion.MAY_BE_RETURNED_TO_DECK


# ======================================================================
# E. 재현
# ======================================================================
def test_e01_a_fresh_state_replays_to_the_same_board(repository):
    """🔴 **새 초기 상태에서 같은 경로를 다시 밟으면 같은 판이다.**"""
    boards = []
    for _ in range(2):
        _, duel = _to_galatea(repository, prefer=(BABEL,))
        _take(duel, _is("activate_effect", effect=GALATEA_SECOND),
              "갈라테아 ②")
        boards.append(duel.state.state_hash())
    assert boards[0] == boards[1]


def test_e02_the_replay_record_accounts_for_the_set(repository):
    """
    🔴 **기록만으로 계산한 각 존의 구성이 최종 판과 같다.**

    6-BF 전에는 ``card_set`` 이 ``_MOVE_KINDS`` 에 없어 세트한 카드가
    출발 자리에 남은 것으로 계산되었다. 그 공백은 패에서 세트하는 **행동**
    에도 있었고, 세트를 지나는 재생 검증이 그때까지 없었을 뿐이다.
    """
    from deck.opening import execute_opening
    from deck.replay_export import export_opening_replay
    from deck.replay_export import verify_replay

    #: 경로를 먼저 **탐색이 아니라 허용 후보로** 만들고, 그 행동 열을
    #: 그대로 다시 실행한다 — 사람이 적어 둔 수순이 아니라 방금 엔진이
    #: 허가한 것이다.
    _, duel = _to_galatea(repository, prefer=(BABEL,))
    _take(duel, _is("activate_effect", effect=GALATEA_SECOND), "갈라테아 ②")

    fresh = _setup(repository, prefer=(HARP_HORROR, BABEL))
    run = execute_opening(fresh, repository, choose=_Replayer())
    record = export_opening_replay(fresh, run, repository)
    assert verify_replay(record) == (), verify_replay(record)
    sets = [change for event in record["events"]
            for change in event["changes"]
            if change["kind"] == "card_set"]
    assert sets, "세트 사건이 기록에 없습니다"
    assert sets[0]["to_zone"] in ("FZONE", "SZONE")


class _Replayer:
    """🔴 **허용 후보에서 갈라테아 경로를 고른다.** 없으면 고르지 않는다."""

    def __init__(self):
        self.taken = []

    def __call__(self, duel, legal):
        for want in (
            _is("normal_summon", source=75),
            _is("activate_effect", effect=(GIRSU, 0)),
            _is("activate_effect", effect=(HARP_HORROR, 0)),
            lambda k: k[0] == "link_summon" and k[2] == 83,
            _is("activate_effect", effect=GALATEA_SECOND),
        ):
            for action in legal.allowed:
                key = action.canonical_state()
                if key in self.taken:
                    continue
                if want(key):
                    self.taken.append(key)
                    return action
        return None


def test_e03_the_site_converter_does_not_silently_drop_the_set(repository):
    """
    🔴 **변환기가 조용히 빠뜨리지 않는다.**

    세트 조작을 만들고, **뒷면이라는 사실은 표현하지 못한다**를
    ``unsupported`` 에 적는다. 🔴 이 시험은 외부 사이트에서 실행한 것이
    아니다 — 계획의 내용만 본다.
    """
    from deck.opening import execute_opening
    from deck.replay_export import export_opening_replay
    from deck.site_plan import build_site_plan

    fresh = _setup(repository, prefer=(HARP_HORROR, BABEL))
    run = execute_opening(fresh, repository, choose=_Replayer())
    record = export_opening_replay(fresh, run, repository)
    plan = build_site_plan(record)
    moved = [op for op in plan["operations"] if "card_set" in op.get("basis", "")]
    assert moved, plan["operations"]
    assert moved[0]["to"] in ("Field Zone", "Spell & Trap Zone1",
                              "Spell & Trap Zone2", "Spell & Trap Zone3",
                              "Spell & Trap Zone4", "Spell & Trap Zone5")
    said = [line for line in plan["unsupported"] if "card_set" in line]
    assert said and "뒷면" in said[0], plan["unsupported"]


# ======================================================================
# F. 기존 동작 유지
# ======================================================================
def test_f01_the_earlier_orcust_steps_are_unchanged(repository):
    """
    🔴 **기르수 · 디베르의 후보와 선택지가 그대로다.**

    6-BF 는 등재 효과를 하나 더하고 제외의 표시 형식을 고쳤다. 앞선 걸음의
    **허용 후보**가 달라지면 그것은 이 Phase 의 범위를 넘은 것이다.
    """
    setup = _setup(repository, prefer=(HARP_HORROR,))
    duel = setup.duel
    opening = _advance_to_open(duel)
    assert sorted(a.canonical_state() for a in opening.allowed) == sorted([
        ("normal_summon", 0, 75, (), None, None, ()),
        ("set_monster", 0, 75, (), None, None, ()),
        ("normal_summon", 0, 76, (), None, None, ()),
        ("set_monster", 0, 76, (), None, None, ()),
        ("normal_summon", 0, 77, (), None, None, ()),
        ("set_monster", 0, 77, (), None, None, ()),
        ("set_spell_trap", 0, 78, (), None, None, ()),
        ("set_spell_trap", 0, 79, (), None, None, ()),
        ("end_phase", 0, None, (), None, None, ()),
    ])
    _take(duel, _is("normal_summon", source=75), "기르수 일반 소환")
    _take(duel, _is("activate_effect", effect=(GIRSU, 0)), "기르수 ①")
    #: 기르수 ① 의 선택지가 다섯 그대로다 (스켈레촌 · 디베르 ×3 · 성장).
    dump = next(r for r in setup.chooser.records)
    assert sorted(c.card_id for c in dump.offer.permitted) == sorted(
        [CYMBAL_SKELETON, HARP_HORROR, HARP_HORROR, HARP_HORROR, 93920420])
    _take(duel, _is("activate_effect", effect=(HARP_HORROR, 0)), "디베르 ①")
    after = _advance_to_open(duel)
    #: 갈라테아 ×2 와 갈라테아i 의 링크 소환이 그대로 후보다.
    links = sorted(a.canonical_state() for a in after.allowed
                   if a.canonical_state()[0] == "link_summon")
    assert links == sorted([
        ("link_summon", 0, 83, (), None, None, (75, 7)),
        ("link_summon", 0, 84, (), None, None, (75, 7)),
        ("link_summon", 0, 87, (), None, None, (75,)),
        ("link_summon", 0, 87, (), None, None, (7,)),
    ]), links


def test_f02_longirsu_is_still_withheld_for_material_shortage(repository):
    """
    🔴 **롱기르수는 여전히 소재가 모자라다** — 6-BF 가 링크 규칙을 한
    글자도 바꾸지 않았다는 사실이다. 효과 몬스터 둘(링크 합 2)로는 링크
    3 을 만들 수 없고, 토큰은 효과 몬스터가 아니다.
    """
    from engine.link_rules import LINK_MATERIAL_RULES

    assert sorted(rule.card_id for rule in LINK_MATERIAL_RULES) == sorted(
        [GALATEA, GALATEA_I, LONGIRSU])
    _, duel = _to_galatea(repository)
    legal = _advance_to_open(duel)
    assert not [a for a in legal.allowed
                if a.canonical_state()[2] == 91]


def test_f03_the_new_operation_is_not_a_movement_system(repository):
    """
    🔴 **``MOVABLE_DESTINATIONS`` 가 한 글자도 늘지 않았다.**

    세트의 목적지는 칸이 있는 존(``SZONE`` · ``FZONE``)이고, 그 표는 칸이
    없는 순서 존만 받는다. 놓는 일은 소환과 **같은 배치 코드**가 한다.
    """
    from engine.effect.operation import MOVABLE_DESTINATIONS
    from engine.set_card import effect_set_procedure
    from engine.vocabulary import Zone

    assert MOVABLE_DESTINATIONS == frozenset(
        {Zone.GRAVE, Zone.REMOVED, Zone.HAND, Zone.DECK})
    assert effect_set_procedure(field_spell=False).to_zone is Zone.SZONE
    assert effect_set_procedure(field_spell=True).to_zone is Zone.FZONE
    for field_spell in (True, False):
        procedure = effect_set_procedure(field_spell=field_spell)
        assert procedure.summon is None, "세트는 소환이 아니다"
        assert procedure.from_zones == frozenset({Zone.DECK})


# ======================================================================
# G. 자율 탐색이 실제로 찾는가 (기본 예산)
# ======================================================================
def test_g01_the_autonomous_search_reaches_the_new_effect(repository):
    """
    🔴 **기본 예산 · 기본 입력에서 자율 탐색이 갈라테아 ② 를 지나는 후보를
    실제로 찾는다.**

    🔴 **고정 경로를 통과시킨 것이 아니다.** 이 시험은 수순을 하나도 주지
    않는다 — ``autonomous_search_opening`` 을 기본값으로 돌리고, 돌아온
    후보들 **안에** 그 효과를 쓴 경로가 있는지만 본다. 어느 카드를
    세트했는지도 요구하지 않는다 (바벨 · 클리막스 어느 쪽이든 된다).

    🔴 **재생 검증까지 본다** — 찾은 것이 새 초기 상태에서 다시 나오는지.
    """
    from app.main import (
        AUTONOMOUS_DEFAULT_CANDIDATES,
        AUTONOMOUS_DEFAULT_CANDIDATES_PER_BASELINE,
        AUTONOMOUS_DEFAULT_NODES,
        autonomous_search_opening,
    )

    _, outcome = autonomous_search_opening(
        repository, _draft(repository), list(ORCUST_HAND),
        max_results=3, actions=6,
    )
    assert outcome is not None
    #: 🔴 **기본 상한이 그대로다** — 예산을 키워 찾은 것이 아니다.
    assert outcome.budget.max_candidates == AUTONOMOUS_DEFAULT_CANDIDATES
    assert outcome.budget.max_nodes == AUTONOMOUS_DEFAULT_NODES
    assert (outcome.budget.max_candidates_per_baseline
            == AUTONOMOUS_DEFAULT_CANDIDATES_PER_BASELINE)
    assert outcome.nodes_expanded <= outcome.budget.max_nodes

    hits = [r for r in outcome.results
            if any(step.action_key[0] == "activate_effect"
                   and step.action_key[4] == GALATEA_SECOND
                   for step in r.path)]
    assert hits, (
        "갈라테아 ② 를 지나는 후보가 없습니다. 종료 이유: "
        f"{outcome.budget_hit} · 노드 {outcome.nodes_expanded} · "
        f"깊이 {outcome.deepest} · 후보 {len(outcome.results)}"
    )
    #: 🔴 **세트까지 갔다** — 그 경로의 끝 자원에 뒷면 마법 · 함정이 있다.
    placed = []
    for result in hits:
        for zone in ("SZONE", "FZONE"):
            summary = result.resources.zone(0, zone)
            if summary is not None:
                placed.extend(
                    slot.card_id for slot in summary.cards
                    if slot.card_id in (BABEL, CLIMAX)
                )
    assert placed, [str(r.resources)[:200] for r in hits]
    #: 🔴 **어느 카드를 요구하지 않는다** — 둘 중 하나면 된다.
    assert set(placed) <= {BABEL, CLIMAX}


def test_g02_a_found_galatea_path_replays_from_a_fresh_state(repository):
    """🔴 **찾은 경로가 새 초기 상태에서 다시 나온다** (기존 재생 검증)."""
    from app.main import autonomous_rerun_record, autonomous_search_opening

    _, outcome = autonomous_search_opening(
        repository, _draft(repository), list(ORCUST_HAND),
        max_results=3, actions=6,
    )
    hits = [r for r in outcome.results
            if any(step.action_key[0] == "activate_effect"
                   and step.action_key[4] == GALATEA_SECOND
                   for step in r.path)]
    assert hits
    verified = [r for r in hits if r.verified]
    assert verified, (
        "갈라테아 ② 경로가 재생 검증을 통과하지 못했습니다: "
        + "; ".join(str(r.index) for r in hits)
    )
    record, why = autonomous_rerun_record(
        repository, _draft(repository), list(ORCUST_HAND), verified[0])
    assert record is not None, why
    sets = [change for event in record["events"]
            for change in event["changes"]
            if change["kind"] == "card_set"]
    assert sets, "재생 기록에 세트 사건이 없습니다"
