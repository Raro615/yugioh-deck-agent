"""
Phase 6-Y — **AI 가 스스로 고르는가.**

6-X 가 기르수 효과를 끝까지 해결했지만, 행동과 선택을 **시험이 넣어
주었다.** 6-Y 는 그 둘을 정책에게 옮긴다.

    legal_actions → Policy.decide        발동 시점 (A) — 이미 되고 있었다
    사건 → TriggerOffer → accept_offer  발동 여부 (§5) — 6-Y 가 열었다
    looked_at → ChoiceOffer → choose_cards  해결 시점 (B) — 6-Y 가 열었다

🔴 **두 시점의 정보가 다르다.** 발동 시점에는 덱이 보이지 않고, 해결 시점에는
규칙이 선언한 ``looked_at`` 만 열린다. 그래서 한 프로토콜로 합치지 않았다 —
합치면 "덱을 보고 발동할지 정한다" 가 된다.

이 파일의 묶음
--------------
``A`` 발동 시점은 이미 자율이다 · ``B`` 유발 제안의 출처와 모름 ·
``C`` 해결 시점 선택 · ``D`` 정책의 말은 허가가 아니다 · ``E`` 재현과
무한 반복 · ``F`` 공통성 (다른 카드) · ``G`` 🔴 아직 안 되는 것.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import (
    ChoiceError,
    ChoicePolicy,
    DeclineChoice,
    FirstPermittedChoice,
    RandomChoice,
)
from agent.heuristic import rule_based_policy
from agent.policy import FirstLegalPolicy, Policy, RandomPolicy
from agent.runner import DuelRunner

from engine.action import PlayerActionKind
from engine.condition import ConditionResult
from engine.effect.journal import EventJournal
from engine.ids import EffectRef, InstanceId
from engine.trigger import TriggerRequirement
from engine.vocabulary import Zone

from integration.autonomy import (
    AutonomyError,
    ChoiceOffer,
    PolicyChooser,
    SelectionRefused,
    TriggerSource,
    choice_offer,
    choice_offer_for,
    run_trigger,
    trigger_offers,
)

from deck.opening import build_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
GIRSU = 69811710
#: 성유물－『성장』 — 6-X 가 묘지 이동을 허가한 카드.
GROWTH = 93920420
#: 어리석은 매장 — 같은 선택 구조를 쓰는 **다른 카드** (카드 발동이다).
BURIAL = 81439173
#: 텐사우전드 드래곤 — 증거 없는 효과 몬스터.
NO_EVIDENCE_MONSTER = 10000


# ======================================================================
# 공용 도구
# ======================================================================
def _orcust_pool(repository):
    from tests.engine.test_deck_to_grave_blocker import _orcust_pool as pool

    return pool(repository)


def _opening(repository, *, growth_copies: int = 1):
    """
    기르수가 패에 있고 증거 카드가 **덱에 남는** 선공 판.

    🔴 **6-Z 부터 유발 원천과 선택자를 꽂는다.** 꽂지 않으면 유발이
    ``legal_actions`` 에 오르지 않고 (``triggers``), 해결 시점의 선택이
    그대로 거절된다 (``chooser``) — 그것이 6-Z 이전의 동작이고, 그 사실은
    ``test_b01`` 과 ``test_b04`` 가 따로 센다.

    🔴 **선택자는 꽂지 않는다** — 이 판은 "고를 사람이 없으면 어떻게 되는가"
    를 보는 데도 쓰인다. 꽂은 판은 :func:`_opening_with_chooser` 다.
    """
    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    #: 앞쪽 넷은 패로 뽑힌다 — 증거 카드를 덱에 남기려면 그 뒤에 둔다.
    pool = others[:4] + [GROWTH] * growth_copies + others[4:]
    lines = [f"{GIRSU} x1"] + [f"{cid} x1" for cid in pool[:39]]
    hand = [GIRSU] + [cid for cid in pool if cid != GIRSU][:4]
    journal = EventJournal()
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        hand[:5],
        journal=journal,
        triggers=TriggerSource(repository),
    )
    assert setup.duel is not None, setup.blockers
    return setup


def _opening_with_chooser(repository, *, growth_copies: int = 1, selector):
    """
    :func:`_opening` 과 같되 꽂아 둔 :class:`PolicyChooser` 를 **함께**
    돌려준다 — 시험이 "무엇을 물었고 무엇을 골랐는가" 를 읽는 데 쓴다.
    """
    chooser = PolicyChooser(selector)
    journal = EventJournal()
    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    pool = others[:4] + [GROWTH] * growth_copies + others[4:]
    lines = [f"{GIRSU} x1"] + [f"{cid} x1" for cid in pool[:39]]
    hand = [GIRSU] + [cid for cid in pool if cid != GIRSU][:4]
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        hand[:5],
        journal=journal,
        chooser=chooser,
        triggers=TriggerSource(repository),
    )
    assert setup.duel is not None, setup.blockers
    return setup, chooser


def _agent_summons(duel, *, seat: int = MINE, policy_name: str = "rb"):
    """
    🔴 **정책이 고른다.** 시험이 행동을 지정하지 않는다.

    돌려주는 것은 정책이 실제로 고른 기록이다.
    """
    runner = DuelRunner(
        duel,
        (
            rule_based_policy(name=f"{policy_name}-p0"),
            rule_based_policy(name=f"{policy_name}-p1"),
        ),
    )
    entry = runner.step()
    while entry is None or entry.action is None:
        entry = runner.step()
    return entry


def _drive(repository, chooser, *, growth_copies: int = 1):
    """
    소환은 ``Policy`` 가, 발동과 선택은 ``chooser`` 가 결정한다.

    🔴 **6-Z 부터 정상 경로다** — ``run_trigger`` 가 ``legal_actions`` →
    ``Duel.apply`` → 상대 응답 → 체인 해결을 지난다. 그래서 같은 정책을
    두 자리에 꽂는다: 발동 여부를 묻는 자리(``run_trigger``)와 해결 중에
    카드를 묻는 자리(``PolicyChooser``).
    """
    setup, wired = _opening_with_chooser(
        repository, growth_copies=growth_copies, selector=chooser
    )
    duel = setup.duel
    entry = _agent_summons(duel)
    offers = trigger_offers(duel, repository, MINE)
    runs = tuple(
        run_trigger(duel, repository, MINE, o, chooser, chooser=wired)
        for o in offers
    )
    return duel, entry, offers, runs


class _Cheater:
    """후보 목록 **밖**을 고르는 정책. 거절되어야 한다."""

    name = "cheater"

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        blocked = [c.instance for c in offer.candidates if not c.permitted]
        return (blocked[0],) if blocked else ()


class _TooMany:
    """허용된 것을 **전부** 고르는 정책. 장수로 거절되어야 한다."""

    name = "too-many"

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        return tuple(c.instance for c in offer.permitted)


# ======================================================================
# A. 발동 시점은 **이미** 자율이었다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_a01_the_policy_already_chooses_the_normal_summon(repository):
    """
    🔴 **6-Y 가 만든 것이 아니다.** 기존 ``Policy`` + ``DuelRunner`` 로
    기르수 일반 소환이 이미 자율로 일어난다. 6-Y 는 그것을 **측정**한다.
    """
    duel = _opening(repository).duel
    entry = _agent_summons(duel)
    assert entry.action is not None
    assert entry.action.kind is PlayerActionKind.NORMAL_SUMMON
    assert entry.accepted is True
    #: 그 행동으로 움직인 카드가 기르수다.
    placed = [c for c in duel.state.player(MINE).monster_zone if c is not None]
    assert [duel.state.find_instance(c.instance_id).card_id for c in placed] == [GIRSU]
    #: 🔴 **정책의 이름이 기록에 남는다** — 누가 골랐는지가 증거다.
    assert entry.policy.startswith("rb-p0")


@pytest.mark.real_card
@requires_official_db
def test_a02_three_different_policies_all_reach_the_summon(repository):
    """
    기준점 정책 셋이 **전부** 기르수를 필드에 올린다 — 한 정책에 맞춰 둔
    결과가 아니다.
    """
    for make in (
        lambda seat: rule_based_policy(name=f"rb-p{seat}"),
        lambda seat: FirstLegalPolicy(f"fl-p{seat}"),
        lambda seat: RandomPolicy(7 + seat, f"rnd-p{seat}"),
    ):
        duel = _opening(repository).duel
        runner = DuelRunner(duel, (make(0), make(1)))
        for _ in range(8):
            runner.step()
        placed = [c for c in duel.state.player(MINE).monster_zone if c is not None]
        ids = [duel.state.find_instance(c.instance_id).card_id for c in placed]
        assert GIRSU in ids, ids


@requires_official_db
def test_a03_the_runner_still_refuses_what_is_not_offered(repository):
    """
    🔴 **정책의 말은 허가가 아니다** — 6-Y 가 그 관문을 약화시키지 않았다.
    """

    class OutOfList:
        name = "out-of-list"

        def decide(self, view, legal):
            from engine.action import PlayerAction

            return PlayerAction.end_phase(actor=1 - MINE)

    duel = _opening(repository).duel
    runner = DuelRunner(duel, (OutOfList(), OutOfList()))
    entry = runner.step()
    while entry is None:
        entry = runner.step()
    assert entry.accepted is False
    assert "P0 의 차례인데" in entry.reason or "허가된 후보가 아닙니다" in entry.reason


# ======================================================================
# B. 유발 제안 — 엔진이 만들고, 모름은 모름으로 남는다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_b01_the_offer_comes_from_the_summon_event(repository):
    """
    §5 — 제안은 **그 사건에서** 나온다. 후보를 새로 세지 않는다.

    ``EventJournal`` 에 남은 소환 기록 → ``timing_events`` →
    ``registry_for_view`` → 다섯 관문. 전부 앞 계층의 것이다.
    """
    duel, entry, offers, _ = _drive(repository, DeclineChoice())
    assert len(offers) == 1, offers
    offer = offers[0]
    assert offer.effect_ref == EffectRef(GIRSU, 0)
    #: 사건의 주체가 방금 소환된 그 인스턴스다.
    assert offer.source == entry.action.source
    assert offer.controller == MINE
    assert offer.event.point.value == "monster_summoned"
    #: 다섯 관문이 전부 통과했다는 것이 이유에 남는다.
    assert "event_relation=valid" in offer.reason
    assert "activation_zone=valid" in offer.reason


@pytest.mark.real_card
@requires_official_db
def test_b02_the_forced_or_optional_distinction_now_has_evidence(repository):
    """
    🔴 §5 의 요구 — **강제와 임의를 가를 수 없으면 그것을 적는다.**

    🔴 **Phase 6-AA 가 근거를 들고 왔다.** 6-Y 때 이 자리는
    ``TriggerRequirement.UNKNOWN`` 이었고, 그것이 그때의 사실이었다. 지금은
    카드 자신의 텍스트가 「발동**할 수 있다**」로 적었고 (허가의 진술) Lua
    선언도 어긋나지 않으므로 **임의**로 판정된다.

    🔴 **그래서 §5 의 요구가 사라진 것이 아니다** — 근거가 모이지 않는
    효과는 여전히 ``UNKNOWN`` 이고, 그때 배선은 발동 여부를 정책에게
    **맡기지 않는다** (``Duel`` 이 보류로 돌린다). 이 시험이 그 둘을 함께
    센다: 근거가 있는 쪽과 없는 쪽.
    """
    _, _, offers, _ = _drive(repository, DeclineChoice())
    offer = offers[0]
    #: ① 근거가 있다 — 임의다.
    assert offer.requirement is TriggerRequirement.OPTIONAL
    assert offer.requirement_known is True
    assert offer.is_optional is True
    assert offer.is_mandatory is False

    #: ② 🔴 **근거는 카드 텍스트다** — 카드 ID 가 아니다.
    card = repository.get(GIRSU)
    assert card.activation_permission_text == "optional"
    assert "발동할 수 있다" in card.desc
    assert "발동한다" not in card.desc

    #: ③ 근거가 모이지 않으면 여전히 ``UNKNOWN`` 이다. 🔴 그런 카드가
    #:    실제로 있다는 것을 corpus 에서 확인한다 — 없으면 이 단정이
    #:    아무것도 재지 않는다.
    from engine.trigger_compiler import requirement_from

    assert (
        requirement_from(["SINGLE", "TRIGGER_O"], None)
        is TriggerRequirement.UNKNOWN
    )
    assert (
        requirement_from(["SINGLE", "TRIGGER_F"], "optional")
        is TriggerRequirement.UNKNOWN
    ), "텍스트와 선언이 어긋나면 판정을 거둔다"


@pytest.mark.real_card
@requires_official_db
def test_b03_an_unrelated_event_offers_nothing(repository):
    """
    §8-4 — **잘못된 사건에서 후보가 생기지 않는다.**

    소환 전에는 기록에 소환 사건이 없으므로 제안이 0건이다.
    """
    duel = _opening(repository).duel
    assert trigger_offers(duel, repository, MINE) == ()


@pytest.mark.real_card
@requires_official_db
def test_b04_the_opponent_is_offered_nothing(repository):
    """제안은 **그 자리의 것**만. 상대 자리로는 나오지 않는다."""
    duel = _opening(repository).duel
    _agent_summons(duel)
    assert trigger_offers(duel, repository, MINE)
    assert trigger_offers(duel, repository, THEIRS) == ()


@requires_official_db
def test_b05_a_duel_without_a_journal_says_so_instead_of_guessing(repository):
    """
    기록이 없으면 사건을 꺼낼 수 없다 — **조용히 0건으로 넘기지 않는다.**

    🔴 **내가 한 번 틀렸다.** 처음 이 시험은 ``build_opening`` 에
    ``journal`` 을 주지 않으면 기록이 없다고 가정했는데, 그 함수는
    ``journal or EventJournal()`` 로 **항상 켜 준다.** 그래서 두 사실을
    따로 적는다 — 흔한 경로는 잊을 수 없다는 것과, 그래도 가드가 있다는 것.

    🔴 **Phase 6-AA 가 가드의 자리를 옮겼다.** 6-Y 는 배선이
    :class:`AutonomyError` 를 던졌고, 그러면 **후보를 묻는 일이 터진다** —
    실측으로 기록 없는 사본(``agent.simulation`` 의 ``_fork``)의
    ``Simulator.simulate`` 가 모든 행동에 ``ERROR`` 를 돌려주었다.

    그래서 배선은 빈 짝을 돌려주고, **"판정하지 못했다" 는 ``Duel`` 의 보류
    목록이 말한다.** 조용히 넘기지 않는다는 요구는 그대로이고, 말하는 자리가
    바뀐 것이다 — 이 시험이 그 자리를 센다.
    """
    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    lines = [f"{GIRSU} x1"] + [f"{cid} x1" for cid in others[:39]]
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        [GIRSU] + others[:4],
    )
    #: ① 흔한 경로는 기록을 **항상** 켠다.
    assert setup.duel.journal is not None

    #: ② 끈 듀얼에서는 배선이 소리를 낸다 (``journal=False`` 가 "적지 않겠다").
    from engine.duel import Duel

    silent = Duel.start(
        repository,
        decks=([GIRSU] + others[:19], others[:20]),
        seed=5,
        journal=False,
    )
    assert silent.journal is None
    #: ② 기록이 없으면 꺼낼 것이 없다 — 빈 짝이다 (터지지 않는다).
    assert trigger_offers(silent, repository, MINE) == ()

    #: ③ 🔴 **그래도 조용하지 않다.** 유발 원천을 꽂은 듀얼이라면
    #:    ``legal_actions`` 가 "판정하지 못했다" 를 보류에 적는다.
    from engine.duel import TRIGGER_HISTORY_MISSING
    from integration.autonomy import TriggerSource

    wired = dataclasses.replace(silent, triggers=TriggerSource(repository))
    legal = wired.legal_actions(MINE)
    held = [w for w in legal.withheld if w.missing == TRIGGER_HISTORY_MISSING]
    assert len(held) == 1, [(w.kind.value, w.reason) for w in legal.withheld]
    assert "사건 기록이 없는 사본" in held[0].reason
    #: 그리고 유발 후보는 오르지 않았다 — 지어내지 않는다.
    assert not [
        a for a in legal.allowed if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]


# ======================================================================
# C. 해결 시점 선택 — 발동을 정한 뒤에 열린다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_c01_the_deck_is_only_opened_after_the_activation_choice(repository):
    """
    🔴 **순서가 규칙이다.** 발동하지 않기로 하면 덱을 **보여 주지 않는다.**

    룰북이 덱을 보는 것을 licensing 하는 자리는 "효과가 그렇게 지시할 때"
    다. 고르기 전에 보여 주면 "덱을 보고 발동할지 정한다" 가 된다.
    """
    _, _, _, declined = _drive(repository, DeclineChoice())
    assert declined[0].activated is False
    #: 🔴 선택지를 만들지도 않았다.
    assert declined[0].choice is None
    assert declined[0].chosen == ()

    _, _, _, taken = _drive(repository, FirstPermittedChoice())
    assert taken[0].activated is True
    assert taken[0].choice is not None


@pytest.mark.real_card
@requires_official_db
def test_c02_the_offer_carries_the_rulings_not_just_the_candidates(repository):
    """
    §6-3 — 후보마다 **묘지 이동 가능 여부**가 함께 온다.

    ``TRUE`` 가 아닌 후보도 목록에 남는다 — 왜 못 고르는지가 정책에게도
    보여야 한다. 🔴 그러나 ``permitted`` 는 ``TRUE`` 만 센다.
    """
    _, _, _, runs = _drive(repository, FirstPermittedChoice())
    choice = runs[0].choice
    assert isinstance(choice, ChoiceOffer)
    assert len(choice) == 35, len(choice)
    assert len(choice.permitted) == 1, [c.card_id for c in choice.permitted]
    #: 허용된 하나가 6-X 가 근거를 찾은 그 카드다.
    assert choice.permitted[0].card_id == GROWTH
    assert choice.permitted[0].verdict is ConditionResult.TRUE
    #: 나머지는 ``UNKNOWN`` 이고, 이유가 비어 있지 않다.
    blocked = [c for c in choice.candidates if not c.permitted]
    assert len(blocked) == 34
    assert all(c.verdict is ConditionResult.UNKNOWN for c in blocked)
    assert all(c.reason for c in blocked)
    #: 장수가 정의에서 온다.
    assert (choice.minimum, choice.maximum) == (1, 1)


@pytest.mark.real_card
@requires_official_db
def test_c03_the_agent_chooses_among_several_permitted_instances(repository):
    """
    §6-4 — 같은 ID 여러 장이 **서로 다른 후보**다. 정책이 그중 하나를 고른다.
    """
    duel, _, _, runs = _drive(repository, FirstPermittedChoice(), growth_copies=3)
    choice = runs[0].choice
    assert len(choice.permitted) == 3
    #: 같은 카드인데 인스턴스가 다르다.
    assert {c.card_id for c in choice.permitted} == {GROWTH}
    assert len({c.instance for c in choice.permitted}) == 3
    #: 정확히 한 장만 골랐고, 그것이 움직였다.
    assert len(runs[0].chosen) == 1
    moved = duel.state.find_instance(runs[0].chosen[0])
    assert moved.zone is Zone.GRAVE
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1


@pytest.mark.real_card
@requires_official_db
def test_c04_the_agent_run_moves_the_card_and_records_it(repository):
    """
    🔴 **수준 3.** 외부 행동 지정 없이 Deck → Graveyard 가 일어난다.

    정책이 결정한 것: ① 일반 소환 ② 발동 여부 ③ 어느 카드.
    시험이 준 것: 덱 레시피 · 선공 패 · 정책.
    """
    duel, entry, offers, runs = _drive(repository, FirstPermittedChoice())
    run = runs[0]

    assert entry.action.kind is PlayerActionKind.NORMAL_SUMMON  # ① 정책
    assert run.activated is True  # ② 정책
    assert run.chosen  # ③ 정책
    assert run.refused is None
    assert run.links == 1
    assert run.resolved is True, run.resolution_reason

    assert len(duel.state.player(MINE).zone(Zone.DECK)) == 34
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1
    moved = duel.state.find_instance(run.chosen[0])
    assert moved.zone is Zone.GRAVE
    assert moved.card_id == GROWTH

    #: 기록이 이동과 셔플을 적는다.
    entries = [str(e) for e in duel.journal]
    joined = " ".join(entries)
    assert "send_to_grave" in joined, entries
    assert "DECK" in joined and "GRAVE" in joined, entries
    assert "섞었다" in joined, entries


@pytest.mark.real_card
@requires_official_db
def test_c05_declining_leaves_the_board_untouched(repository):
    """
    🔴 **이동이 정책의 결정임을 대조군으로 보인다.**

    같은 판 · 같은 소환인데 발동하지 않으면 **아무것도 움직이지 않는다.**
    """
    duel, _, _, runs = _drive(repository, DeclineChoice())
    assert runs[0].activated is False
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == 35
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    #: 소환 기록 하나뿐 — 효과 기록이 없다.
    assert not any("send_to_grave" in str(e) for e in duel.journal)


@pytest.mark.real_card
@requires_official_db
def test_c06_an_empty_deck_offers_nothing_and_invents_nothing(repository):
    """§8-10 — 덱에 적법한 후보가 없으면 허용 후보가 0건이고 멈춘다."""
    plain = sorted(
        card.id
        for card in repository.all_cards()
        if not card.is_extra_deck and not card.setcodes
    )[:39]
    journal = EventJournal()
    lines = [f"{GIRSU} x1"] + [f"{cid} x1" for cid in plain[:39]]
    chooser = PolicyChooser(FirstPermittedChoice())
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        [GIRSU] + plain[:4],
        journal=journal,
        chooser=chooser,
        triggers=TriggerSource(repository),
    )
    duel = setup.duel
    _agent_summons(duel)
    #: 🔴 **제안은 생긴다** — 발동 조건은 덱 장수만 보므로 카드군 카드가
    #: 없어도 적법하다. 막히는 자리는 그 **뒤**다.
    offers = trigger_offers(duel, repository, MINE)
    assert len(offers) == 1, offers

    run = run_trigger(
        duel, repository, MINE, offers[0], FirstPermittedChoice(), chooser=chooser
    )
    #: 🔴 **발동은 정상 경로로 일어난다** — 막히는 자리는 해결 중이다.
    assert run.activated is True
    assert run.links == 1
    #: 후보가 0건이므로 고를 것이 없고, 장수로 거절된다.
    assert run.choice is not None
    assert run.choice.permitted == ()
    assert run.chosen == ()
    assert run.refused is not None
    assert "최소 1장" in run.refused.reason, run.refused.reason
    #: 🔴 **그 거절은 엔진이 쓴 문장이다** — 배선이 미리 걸러 낸 것이
    #: 아니라 ``TargetResolver._check_count`` 가 해결 중에 낸 것이다.
    assert "too_few_selected" in run.refused.reason, run.refused.reason
    #: 🔴 **카드를 만들지 않았다.**
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == 35


# ======================================================================
# D. 정책의 말은 허가가 아니다
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_d01_choosing_outside_the_permitted_list_is_refused(repository):
    """
    🔴 §8-11 — ``UNKNOWN`` 후보를 고르면 **거절된다.** 판은 그대로다.

    🔴 **6-Z 가 거절하는 자리를 옮겼다.** 6-Y 는 배선이 미리 걸렀고
    ("고를 수 없습니다"), 지금은 엔진이 해결 중에 거른다 — 6-X 가 연
    ``BoardRuling`` 관문이다. 거절이 **엔진의 것**이라는 사실이 더 강한
    증거다: 배선을 지나지 않는 길로 와도 같은 자리에서 막힌다.
    """
    duel, _, _, runs = _drive(repository, _Cheater())
    refused = runs[0].refused
    assert isinstance(refused, SelectionRefused)
    #: 엔진이 쓴 문장이다 — 6-X 의 관문 설명이 그대로 들어 있다.
    assert "판정할 수 없는 것을 허가로 바꾸지 않습니다" in refused.reason, (
        refused.reason
    )
    assert "묘지로 보낼 수 있는지" in refused.reason, refused.reason
    #: 🔴 **고른 것은 정책의 것이고, 그것이 기록에 남는다.**
    assert len(refused.chosen) == 1
    assert not runs[0].choice.candidates[0].permitted
    #: 판은 그대로다.
    assert len(duel.state.player(MINE).zone(Zone.DECK)) == 35
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    #: 🔴 체인에는 올랐다 (발동은 적법했다) — 막힌 것은 **해결**이다.
    assert runs[0].links == 1
    assert runs[0].resolution is None


@pytest.mark.real_card
@requires_official_db
def test_d02_choosing_too_many_is_refused(repository):
    """§6-5 — **정확한 장수만.** 많이 고르면 거절된다."""
    duel, _, _, runs = _drive(repository, _TooMany(), growth_copies=3)
    refused = runs[0].refused
    assert refused is not None
    assert "최대 1장" in refused.reason
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0


@pytest.mark.real_card
@requires_official_db
def test_d03_choosing_the_same_card_twice_is_refused(repository):
    """같은 인스턴스를 두 번 고르면 거절된다."""

    class Doubler:
        name = "doubler"

        def accept_offer(self, offer) -> bool:
            return True

        def choose_cards(self, offer):
            first = offer.permitted[0].instance
            return (first, first)

    duel, _, _, runs = _drive(repository, Doubler(), growth_copies=3)
    assert runs[0].refused is not None
    #: 🔴 **같은 장을 두 번 건넨 것이 거절된다.** 기르수의 선택은 1장이
    #: 상한이므로 엔진은 **장수**로 먼저 막는다 — 중복 검사보다 앞이다
    #: (``TargetResolver._check_count`` 의 순서). 어느 쪽이든 판은
    #: 움직이지 않는다.
    assert "최대 1장" in runs[0].refused.reason, runs[0].refused.reason
    assert runs[0].chosen[0] == runs[0].chosen[1]
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0

    #: 🔴 **중복 규칙 자체가 살아 있는지 따로 센다.** 위에서 장수가 먼저
    #: 막으므로, 장수가 맞는 자리에서 중복만 틀린 선택을 엔진에게 직접
    #: 물어본다 (벌금 — 최소 · 최대가 둘 다 2장이다).
    from engine.cost import Selection
    from engine.effect.library import definition_registry
    from engine.effect.targeting import TargetResolver
    from engine.condition import ConditionContext
    from engine.game_state_view import GameStateView
    from engine.validation import ValidationCode

    fine = definition_registry().definition_for(EffectRef(92595643, 0))
    binding = fine.targets[0]
    assert (binding.spec.choice.minimum, binding.spec.choice.maximum) == (2, 2)
    hand = duel.state.player(MINE).zone(Zone.HAND)
    view = GameStateView.from_state(duel.state, viewer=MINE)
    twice = TargetResolver(view).validate(
        binding.spec,
        Selection((hand[0].instance_id, hand[0].instance_id)),
        ConditionContext(player=MINE, source=hand[0].instance_id,
                         effect_ref=EffectRef(92595643, 0)),
        binding.ref,
    )
    assert twice.code is ValidationCode.DUPLICATE_SELECTION, twice.reason
    assert "두 번" in twice.reason


@pytest.mark.real_card
@requires_official_db
def test_d04_the_engine_gate_is_not_bypassed(repository):
    """
    🔴 **관문이 둘이다.** 배선이 거절하지 않더라도 엔진이 다시 본다.

    ``plan`` 에 선택을 넘기는 것은 "정해졌는가" 를 말할 뿐이고, 적법성은
    ``ChainResolver`` 가 ``BoardRuling`` 으로 다시 판정한다. 그 증거로
    6-X 가 연 관문이 여전히 같은 자리에 있다.
    """
    from engine.effect.library import OPERATION_RULINGS
    from engine.effect.ruling import RuleQuestion

    #: 등록소는 6-X 그대로다 — 6-Y 가 허가를 넓히지 않았다.
    #: Phase 6-AC 가 둘을 더했다 — 성유물－『성장』 · 오르페골 갈라테아 (19 → 21).
    assert len(OPERATION_RULINGS) == 21
    _, _, _, runs = _drive(repository, FirstPermittedChoice())
    choice = runs[0].choice
    #: 제안이 들고 온 판정이 ``BoardRuling`` 의 것과 같은 질문이다.
    assert RuleQuestion.MAY_BE_SENT_TO_GRAVE.value == "may_be_sent_to_grave"
    assert choice.permitted[0].verdict is ConditionResult.TRUE


# ======================================================================
# E. 재현과 무한 반복
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_e01_the_same_seed_makes_the_same_choice(repository):
    """§4-3 · §8-15 — **같은 입력이면 같은 결정.**"""
    first = _drive(repository, RandomChoice(5), growth_copies=3)[3][0]
    again = _drive(repository, RandomChoice(5), growth_copies=3)[3][0]
    assert (first.activated, first.chosen) == (again.activated, again.chosen)


@pytest.mark.real_card
@requires_official_db
def test_e02_different_seeds_make_different_choices(repository):
    """
    🔴 **정책이 달라지면 전개도 달라진다** — 고정된 결과가 아니라는 증거다.
    """
    seen = set()
    for seed in (1, 2, 5, 11, 23):
        run = _drive(repository, RandomChoice(seed), growth_copies=3)[3][0]
        seen.add((run.activated, run.chosen))
    assert len(seen) >= 2, seen


def test_e03_a_choice_policy_needs_a_seed():
    """씨앗 없는 무작위는 재현할 수 없다 (``RandomPolicy`` 와 같은 규율)."""
    with pytest.raises(ChoiceError):
        RandomChoice("5")  # type: ignore[arg-type]


@pytest.mark.real_card
@requires_official_db
def test_e04_running_the_same_offer_twice_does_not_move_twice(repository):
    """
    §8-14 — **중복 해결 방지.** 같은 제안을 다시 돌려도 카드가 두 장
    움직이지 않는다 — 두 번째는 후보가 이미 묘지에 있어 거절된다.
    """
    duel, _, offers, runs = _drive(repository, FirstPermittedChoice())
    assert runs[0].resolved is True
    grave_after_first = len(duel.state.player(MINE).zone(Zone.GRAVE))

    again = run_trigger(
        duel, repository, MINE, offers[0], FirstPermittedChoice()
    )
    assert again.resolved is False
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == grave_after_first


def test_e05_the_protocols_are_separate():
    """
    🔴 **두 시점을 한 프로토콜로 합치지 않았다.**

    ``Policy`` 는 발동 시점, ``ChoicePolicy`` 는 해결 시점이다. 기준점
    정책들이 서로의 프로토콜을 만족하지 **않는다**.
    """
    assert isinstance(FirstPermittedChoice(), ChoicePolicy)
    assert not isinstance(FirstPermittedChoice(), Policy)
    assert isinstance(FirstLegalPolicy(), Policy)
    assert not isinstance(FirstLegalPolicy(), ChoicePolicy)


# ======================================================================
# F. 공통성 — 같은 선택 구조를 쓰는 다른 카드
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_f01_foolish_burial_uses_the_same_choice_offer(repository):
    """
    §8-16 — **기르수 전용이 아니다.** 어리석은 매장은 **카드 발동**인데
    같은 ``choice_offer_for`` 로 같은 모양의 선택지가 나온다.
    """
    from engine.state.game_state import GameState

    game = GameState.create(
        repository,
        decks=(
            [BURIAL] + [GROWTH] * 3 + [NO_EVIDENCE_MONSTER] * 36,
            [NO_EVIDENCE_MONSTER] * 20,
        ),
        seed=11,
    )
    game.draw(MINE, 1)
    source = game.player(MINE).hand[0].instance_id
    assert game.find_instance(source).card_id == BURIAL

    offer = choice_offer_for(game, MINE, EffectRef(BURIAL, 0), source)
    assert offer is not None
    #: 같은 모양이다 — 후보마다 판정이 붙고, 장수가 정의에서 온다.
    assert (offer.minimum, offer.maximum) == (1, 1)
    assert len(offer.permitted) == 3
    assert {c.card_id for c in offer.permitted} == {GROWTH}
    #: 증거 없는 몬스터는 허용되지 않는다.
    assert all(c.card_id == GROWTH for c in offer.permitted)

    #: 그리고 같은 선택 정책이 그 선택지를 읽는다.
    chosen = FirstPermittedChoice().choose_cards(offer)
    assert len(chosen) == 1
    assert chosen[0] in {c.instance for c in offer.permitted}


@requires_official_db
def test_f02_an_effect_without_a_choice_offers_nothing(repository):
    """고를 자리가 없는 효과는 ``None`` 이다 — 빈 목록과 다르다."""
    from engine.state.game_state import GameState

    game = GameState.create(repository, decks=([BURIAL] * 10, [BURIAL] * 10), seed=1)
    game.draw(MINE, 1)
    source = game.player(MINE).hand[0].instance_id
    #: 싸이크론(5318639)은 등록소에 있지만 이 판에 없다 — 정의가 없는 효과를
    #: 물으면 배선이 소리를 낸다.
    with pytest.raises(AutonomyError):
        choice_offer_for(game, MINE, EffectRef(1, 0), source)


# ======================================================================
# G. 🔴 6-Y 가 "아직 안 된다" 고 고정해 둔 것들
#
#    Phase 6-Z 가 그중 둘을 열었다 (``BLOCKER-6Y-1`` · ``-2``). 이 군은
#    **지워지지 않는다** — 열렸다는 사실과 **무엇이 그대로인가**를 같은
#    자리에서 센다. 열렸다고 적으려면 열린 것을 실제로 보여야 하고,
#    그대로인 것은 그대로임을 보여야 한다.
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_g01_the_duel_loop_now_offers_the_trigger_but_only_with_an_event(
    repository,
):
    """
    🔴 **``BLOCKER-6Y-1`` 이 닫혔다** (Phase 6-Z). 유발 발동이
    ``legal_actions`` 에 오르고 ``Duel.apply`` 가 받는다.

    🔴 **열린 방식이 요점이다.** 6-Y 가 적어 둔 이유는 분류였다 —
    ``ACTIVATION_KINDS_IN_SCOPE`` 가 기동 효과 하나이고, 룰북이 발동 시점을
    문장으로 적어 둔 분류가 그것뿐이기 때문이다 (RULE-EFFECT-002). 유발의
    시점은 **사건**이다.

    그래서 6-Z 는 **그 집합을 넓히지 않았다.** 넓히면 사건 없이도 유발이
    발동되고, 그것은 룰북이 적지 않은 허가다. 대신 **사건을 들고 왔다** —
    사건이 뒷받침하는 짝에만 관문이 열린다. 이 시험이 그 둘을 함께 센다:
    집합은 그대로이고, 사건이 없으면 여전히 거절된다.
    """
    from engine.action import PlayerAction
    from engine.action_validation import ACTIVATION_KINDS_IN_SCOPE
    from engine.effect.library import definition_registry
    from engine.vocabulary import ActivationKind

    #: 🔴 **그대로다** — 6-Z 는 분류 집합을 넓히지 않았다.
    assert ACTIVATION_KINDS_IN_SCOPE == frozenset({ActivationKind.IGNITION})
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))
    assert definition.activation_kind is ActivationKind.TRIGGER

    duel = _opening(repository).duel

    #: ① **사건이 없을 때.** 기르수는 아직 패에 있고 소환되지 않았다.
    hand = duel.state.player(MINE).zone(Zone.HAND)
    in_hand = next(
        c.instance_id for c in hand
        if duel.state.find_instance(c.instance_id).card_id == GIRSU
    )
    before = {a.kind.value for a in duel.legal_actions(MINE).allowed}
    assert "activate_effect" not in before, before
    #: 직접 넣어도 받지 않는다 — **사건 없는 발동은 막힌다.**
    refused = duel.apply(
        PlayerAction.activate_effect(
            actor=MINE, source=in_hand, effect_ref=EffectRef(GIRSU, 0)
        )
    )
    #: 🔴 **정정 (보완6).** 전에는 거절 문장이 *"activate_effect 는 지금
    #: 허가된 행위가 아닙니다"* 였다. 보완6 은 후보를 만든 **그 관문**의
    #: 판정을 그대로 옮기므로 (규칙이 막은 것을 "엔진 미지원" 으로 적지
    #: 않기 위해서다), 지금은 관문의 말이 나온다.
    #:
    #: 🔴 그 말이 *"아직 구현하지 않은 규칙이 걸려 있습니다"* 인 것은
    #: **좋지 않다** — 사건 없는 발동은 **아는 규칙**이 막는 것이다. 다만
    #: 그 문장은 보완6 이 만든 것이 아니라 검증기가 전부터 쓰던 것이고,
    #: 고치는 일은 이 Phase 의 범위가 아니다 (보고서 BLOCKER-F6-2).
    #:
    #: 이 시험이 지키는 것("사건 없는 발동은 거절된다")은 ``accepted`` 가
    #: 그대로 센다.
    assert refused.accepted is False
    assert "구현하지 않은 규칙" in refused.reason, refused.reason

    #: ② **사건이 생긴 뒤.** 같은 효과 · 같은 카드인데 이번에는 오른다.
    entry = _agent_summons(duel)
    offered = [
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    ]
    assert len(offered) == 1, offered
    assert offered[0].effect_ref == EffectRef(GIRSU, 0)
    assert offered[0].source == entry.action.source
    #: 🔴 **덱 인스턴스가 행위에 실리지 않는다** (STRUCTURAL-125).
    assert offered[0].targets == ()

    #: ③ ``Duel.apply`` 가 그것을 받는다 — 같은 관문이 다시 판정한다.
    step = duel.apply(offered[0])
    assert step.accepted is True, step.reason
    assert len(duel.chain) == 1


@pytest.mark.real_card
@requires_official_db
def test_g02_the_opponent_response_loop_is_now_exercised(repository):
    """
    🔴 **``BLOCKER-6Y-2`` 가 닫혔다** (Phase 6-Z). 발동 뒤 **상대에게**
    응답 기회가 열리고, 둘 다 패스해야 체인이 풀린다.

        RULE-CHAIN-001 — "If a card's effect is activated, the opponent is
        **always** given a chance to respond … Both players continue to add
        effects to the Chain until **they both wish to add nothing else**."

    6-Y 는 이 자리를 돌리지 않았고 (배선이 체인을 세우고 바로 해결했다),
    그래서 "돌았다고 적지 않는다" 가 그때의 정직한 기록이었다. 지금은
    실제로 돈다 — 이 시험이 **한 번의 패스로는 풀리지 않는다**는 것까지
    센다.
    """
    setup, wired = _opening_with_chooser(
        repository, selector=FirstPermittedChoice()
    )
    duel = setup.duel
    _agent_summons(duel)
    action = next(
        a for a in duel.legal_actions(MINE).allowed
        if a.kind is PlayerActionKind.ACTIVATE_EFFECT
    )
    assert duel.apply(action).accepted is True

    #: ① 발동 직후 — **상대가** 우선권을 쥔다.
    assert duel.priority.is_open is True
    assert duel.priority.holder.seat == THEIRS
    #: 🔴 아직 아무것도 묻지 않았다 — 해결 전이다.
    assert wired.records == ()
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0

    #: ② 상대가 패스한다. **한 번으로는 풀리지 않는다.**
    from engine.action import PlayerAction

    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True
    assert len(duel.chain) == 1
    assert wired.records == ()
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0

    #: ③ 내가 패스한다 — 그때 풀리고, **그 안에서** 선택을 묻는다.
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert len(wired.records) == 1
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1


@pytest.mark.real_card
@requires_official_db
def test_g03_no_deck_instance_ever_reaches_the_action(repository):
    """
    🔴 ``STRUCTURAL-125`` 가 지키려던 것은 그대로다 — **덱 인스턴스가
    ``PlayerAction`` 에 실리지 않는다.**

    6-Y 에서 그 사실은 "다리가 빈 목록을 돌려준다" 로 나타났다 (조합 0건 →
    발동 후보 0건). 6-Z 는 그 자리를 **고르기를 해결 시점으로 옮겨** 바꿨고,
    그래서 조합은 **빈 조합 하나**다 — "대상 없이 발동한다" 는 뜻이다.

    두 모양이 지키는 것은 같고, 새 모양이 **더 강하다**: 발동은 되고, 그
    행위에 덱 인스턴스는 한 장도 없다. 이 시험이 그 둘을 함께 센다.
    """
    from engine.effect.library import definition_registry
    from engine.target_bridge import (
        chosen_bindings,
        decided_at_resolution,
        target_combinations,
    )

    duel = _opening(repository).duel
    entry = _agent_summons(duel)
    definition = definition_registry().definition_for(EffectRef(GIRSU, 0))

    #: ① 고르기는 해결 시점으로 미뤄졌다 — 그래서 발동 시점에 짝지울
    #:    자리가 없다.
    assert [decided_at_resolution(b.spec) for b in definition.targets] == [True]
    assert chosen_bindings(definition) == ()

    #: ② 조합은 **빈 조합 하나**다 — 발동은 되고, 대상은 비어 있다.
    combinations = list(
        target_combinations(duel.state, MINE, definition, entry.action.source)
    )
    assert combinations == [()]

    #: ③ 🔴 **후보 목록의 어느 행위에도 덱 인스턴스가 없다.**
    deck = {c.instance_id for c in duel.state.player(MINE).zone(Zone.DECK)}
    assert deck
    for action in duel.legal_actions(MINE).allowed:
        for target in action.targets:
            assert getattr(target, "instance", None) not in deck, action
        assert action.source not in deck, action


def test_g04_plan_without_selections_still_refuses():
    """
    🔴 **6-Y 의 엔진 변경이 기본 동작을 바꾸지 않았다.**

    ``selections`` 를 주지 않으면 ``plan`` 은 6-Y 이전과 **같은 거절**을
    돌려준다. 열린 것은 "정해졌을 때 받을 통로" 하나다.
    """
    import inspect

    from engine.trigger_chain import TriggerChainIntegrator

    signature = inspect.signature(TriggerChainIntegrator.plan)
    assert signature.parameters["selections"].default is None
    assert signature.parameters["selections"].kind is inspect.Parameter.KEYWORD_ONLY
