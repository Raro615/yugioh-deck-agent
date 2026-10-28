"""
Phase 6-Z — **유발 발동의 정상 Duel 경로와 실제 해결 시점 선택.**

6-Y 가 남긴 것이 둘이었다 (그 보고서 §12).

    BLOCKER-6Y-1   유발 발동이 ``legal_actions`` 에 오르지 않는다. 배선이
                   ``plan`` · ``extend`` · ``ChainResolver`` 를 직접 불러
                   **둘째 길**을 만들었다 (Phase 3-E-20 이 경고한 자리)
    BLOCKER-6Y-2   상대 응답과 우선권이 돌지 않는다 — 체인을 배선이 세우고
                   바로 해결했으므로 그 사이에 상대가 끼어들 자리가 없었다

그리고 하나 더, 6-Y 가 스스로 적어 둔 것:

    ``choose_cards`` 를 **체인을 쌓기 전에** 불렀으므로 그것은 해결 시점의
    선택이 아니었다.

이 파일이 재는 것은 그 셋이 닫혔는가다. 세 군으로 나눈다.

================  ==================================================
A. 수직 경로        ``legal_actions`` → ``Duel.apply`` → 상대 응답 →
                  해결 시점 선택 → Deck → Graveyard
B. 시점과 경계      언제 묻고 언제 묻지 않는가, 무엇을 거절하는가
C. 구조            AI 가 판을 만지지 못하는가, 둘째 길이 없는가
================  ==================================================

🔴 **무엇이 바뀌지 않았는지도 센다.** 사건으로 관문을 열었고 **분류 집합을
넓히지 않았다** (``ACTIVATION_KINDS_IN_SCOPE``). 규칙 등록소도 그대로다
(``OPERATION_RULINGS`` 19줄). 넓히지 않았다는 사실이 "사건이 시점을 정한다"
를 지키는 전부다.
"""

from __future__ import annotations

import inspect
import io
import pathlib

import pytest

from agent.choice import DeclineChoice, FirstPermittedChoice, RandomChoice
from agent.policy import FirstLegalPolicy, RandomPolicy
from agent.runner import DuelRunner
from agent.heuristic import rule_based_policy
from engine.action import PlayerAction, PlayerActionKind
from engine.condition import ConditionResult
from engine.effect.journal import EventJournal
from engine.ids import EffectRef
from engine.priority import ResponseWindow
from engine.validation import ValidationCode
from engine.vocabulary import ActivationKind, Zone

from integration.autonomy import (
    ChoiceRecord,
    PolicyChooser,
    TriggerSource,
    run_trigger,
    trigger_offers,
)

from deck.opening import build_opening
from deck.recipe import parse_recipe
from tests.conftest import requires_official_db

MINE, THEIRS = 0, 1
#: 기르수 — 이 저장소에 등재된 **유일한 유발 효과**다 (실측: ``test_c09``).
GIRSU = 69811710
#: 성유물－『성장』 — 6-X 가 묘지 이동 근거를 찾은 카드.
GROWTH = 93920420
#: 어리석은 매장 — **같은 해결 시점 선택을 쓰는 다른 효과** (카드 발동이다).
BURIAL = 81439173
#: 벌금 — 발동 시점에 패 2장을 받는 효과. **미뤄지지 않는다.**
FINE = 92595643
PROJECT = pathlib.Path(__file__).resolve().parents[2]


# ======================================================================
# 공용 도구 — 시험이 행동을 지정하지 않는다
# ======================================================================
def _orcust_pool(repository):
    from tests.engine.test_deck_to_grave_blocker import _orcust_pool as pool

    return pool(repository)


def _board(
    repository,
    *,
    selector=None,
    triggers: bool = True,
    extra_hand: "tuple[int, ...]" = (),
    girsu_copies: int = 1,
    growth_copies: int = 1,
):
    """
    기르수가 패에 있고 증거 카드가 **덱에 남는** 선공 판.

    ``selector`` 를 주면 :class:`PolicyChooser` 를 꽂는다. 주지 않으면 **해결
    시점에 고를 사람이 없는** 판이고, 그것도 재는 대상이다 (``test_b03``).

    ``triggers=False`` 는 **6-Z 이전의 배선**이다 — 사건 원천이 없으면 유발
    후보가 오르지 않는다. 그 사실을 ``test_c10`` 이 센다.
    """
    others = [cid for cid in _orcust_pool(repository) if cid != GROWTH]
    #: 앞쪽 넷은 패로 뽑힌다 — 증거 카드를 덱에 남기려면 그 뒤에 둔다.
    pool = others[:4] + [GROWTH] * growth_copies + others[4:]
    lines = [f"{GIRSU} x{girsu_copies}"] + [
        f"{cid} x1" for cid in pool[: 40 - girsu_copies]
    ]
    for card_id in extra_hand:
        lines.append(f"{card_id} x1")
    #: 🔴 **선공 첫 패는 5장이다** — 늘리지 않는다. 보고 싶은 카드를 앞에
    #: 두어 그 다섯 안에 들게 한다.
    hand = (
        [GIRSU] * girsu_copies
        + list(extra_hand)
        + [cid for cid in pool if cid != GIRSU]
    )[:5]
    chooser = None if selector is None else PolicyChooser(selector)
    setup = build_opening(
        repository,
        parse_recipe("\n".join(lines), repository).draft,
        hand,
        journal=EventJournal(),
        chooser=chooser,
        triggers=TriggerSource(repository) if triggers else None,
    )
    assert setup.duel is not None, setup.blockers
    return setup, chooser


def _summon(duel, *, seat: int = MINE):
    """🔴 **정책이 고른다.** 시험이 어느 카드를 소환할지 지정하지 않는다."""
    runner = DuelRunner(
        duel,
        (rule_based_policy(name="rb-p0"), rule_based_policy(name="rb-p1")),
    )
    entry = runner.step()
    while entry is None or entry.action is None:
        entry = runner.step()
    assert entry.action.kind is PlayerActionKind.NORMAL_SUMMON, entry.action
    return entry


def _trigger_action(duel, *, seat: int = MINE, card_id: int = GIRSU):
    """
    후보 목록에서 **그 카드의 효과 발동 하나**를 꺼낸다. 없으면 ``None``.

    카드를 지목하는 이유: 패에 다른 발동 가능한 카드가 있으면 후보 목록에
    둘 이상이 오르고, 그때 "첫 번째" 를 집으면 무엇을 쟀는지 알 수 없다.
    """
    return next(
        (
            a
            for a in duel.legal_actions(seat).allowed
            if a.kind is PlayerActionKind.ACTIVATE_EFFECT
            and a.effect_ref is not None
            and a.effect_ref.card_id == card_id
        ),
        None,
    )


class _Steps(list):
    """
    패스로 지난 걸음들. ``resolution`` 은 **체인을 푼** 걸음이다.

    🔴 **마지막 걸음이 해결 걸음이 아니다** (보완5). 보완5 가 빈 체인의 빠른
    효과 기회를 실었으므로, 체인이 풀린 뒤에도 양측이 지나가야 판이 열린다.
    그래서 ``[-1]`` 은 *"양쪽이 빠른 효과 기회를 지나갔습니다"* 가 되고,
    그것은 **절차를 지났다는 말이고 결과가 아니다.**

    그 구분을 호출자가 매번 다시 하지 않도록 여기서 들고 있는다. 체인이
    서지 않았으면 ``None`` 이다.
    """

    resolution = None


def _settle(duel):
    """
    응답 창과 **빠른 효과 기회**를 패스로 지난다. 패스도 ``legal_actions``
    를 지난다.

    돌려주는 것은 :class:`_Steps` 다 — 걸음 목록이면서 ``resolution`` 을
    따로 들고 있다.
    """
    steps = _Steps()
    #: 🔴 상한을 2 에서 6 으로 올렸다 (보완5) — 1 링크 체인도 네 걸음이
    #: 필요하다 (응답 둘 + 빠른 효과 기회 둘). 2 로 두면 빠른 효과 기회가
    #: 열린 채 남아 호출자가 **체인 도중인지 기회 중인지** 알 수 없다.
    while duel.priority.is_open and len(steps) < 6:
        holder = duel.priority.holder.seat
        passing = PlayerAction.passing(actor=holder)
        assert passing in duel.legal_actions(holder).allowed
        had_chain = not duel.chain.is_empty
        steps.append(duel.apply(passing))
        if had_chain and duel.chain.is_empty:
            steps.resolution = steps[-1]
    return steps


def _source(path: str) -> str:
    return io.open(PROJECT / path, encoding="utf-8").read()


class _Cheater:
    """후보 목록에 있으나 **규칙이 허락하지 않은** 것을 고른다."""

    name = "cheater"

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        blocked = [c.instance for c in offer.candidates if not c.permitted]
        return (blocked[0],) if blocked else ()


class _Outsider:
    """**후보 목록 밖**을 고른다. 엔진이 걸러야 한다."""

    name = "outsider"

    def __init__(self, instance):
        self.instance = instance

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        return (self.instance,)


class _Empty:
    """아무것도 고르지 않는다. 장수로 걸려야 한다."""

    name = "empty"

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        return ()


class _TooMany:
    """허용된 것을 **전부** 고른다. 장수로 걸려야 한다."""

    name = "too-many"

    def accept_offer(self, offer) -> bool:
        return True

    def choose_cards(self, offer):
        return tuple(c.instance for c in offer.permitted)


# ======================================================================
# A. 수직 경로 — 한 번에 끝까지
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_a01_the_event_makes_the_candidate_not_the_board(repository):
    """
    🔴 **사건이 후보를 만든다.** 같은 카드 · 같은 효과인데 사건이 없으면
    후보가 아니다 (RULE-EFFECT-004 — 유발의 시점은 사건이 정한다).
    """
    setup, _ = _board(repository)
    duel = setup.duel

    #: ① 소환 전 — 기르수는 패에 있고 사건이 없다.
    assert _trigger_action(duel) is None
    assert trigger_offers(duel, repository, MINE) == ()

    #: ② 소환 뒤 — 같은 효과가 **정확히 하나** 오른다.
    entry = _summon(duel)
    offers = trigger_offers(duel, repository, MINE)
    assert len(offers) == 1, offers
    assert offers[0].effect_ref == EffectRef(GIRSU, 0)
    assert offers[0].source == entry.action.source

    action = _trigger_action(duel)
    assert action is not None
    assert action.effect_ref == EffectRef(GIRSU, 0)
    assert action.source == entry.action.source
    #: 🔴 덱 인스턴스가 행위에 실리지 않는다 (STRUCTURAL-125).
    assert action.targets == ()


@pytest.mark.real_card
@requires_official_db
def test_a02_apply_accepts_what_legal_actions_offered(repository):
    """
    ``Duel.apply`` 가 **같은 관문으로 다시 판정하고** 받는다.

    목록을 지나왔다고 믿지 않는다 — ``apply`` 는 공개 입구이고, 그래서
    ``legal_actions`` 를 **한 번 더** 돌린다 (STRUCTURAL-134).
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)

    step = duel.apply(action)
    assert step.accepted is True, step.reason
    #: 체인에 링크가 하나 올랐다.
    assert len(duel.chain) == 1
    link = duel.chain.links[0]
    assert link.effect_ref == EffectRef(GIRSU, 0)
    assert link.actor == MINE


@pytest.mark.real_card
@requires_official_db
def test_a03_the_opponent_gets_the_response_window(repository):
    """
    발동 뒤 **상대에게** 응답 기회가 열리고, **둘 다** 패스해야 풀린다.

        RULE-CHAIN-001 — "the opponent is **always** given a chance to
        respond … until **they both wish to add nothing else**"
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))

    assert duel.priority.is_open is True
    assert duel.priority.holder.seat == THEIRS

    #: ① 상대가 패스한다 — **아직 풀리지 않는다.**
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True
    assert len(duel.chain) == 1
    assert chooser.records == ()
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0

    #: ② 내가 패스한다 — 그때 풀린다.
    final = duel.apply(PlayerAction.passing(actor=MINE))
    assert final.accepted is True
    assert final.code is ValidationCode.OK, final.reason
    assert len(duel.chain) == 0
    #: 🔴 **해결 뒤에도 기회가 하나 남는다** (보완5 정정). 보완5 전까지 이
    #: 줄은 해결 **직후** 우선권이 닫힐 것을 요구했다. 공식 Fast Effect
    #: Timing 도표는 체인 해결 뒤에도 유발 확인과 빠른 효과 기회를 거치게
    #: 하고, 판이 다시 열리려면 양측이 지나가야 한다.
    assert duel.priority.is_open is True
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.seat == duel.turn_player
    #: 양측이 지나가면 닫힌다.
    duel.apply(PlayerAction.passing(actor=MINE))
    duel.apply(PlayerAction.passing(actor=THEIRS))
    assert duel.priority.is_open is False


@pytest.mark.real_card
@requires_official_db
def test_a04_the_choice_happens_inside_the_resolution(repository):
    """
    🔴 **선택이 해결 중에 일어난다.** 6-Y 는 체인을 쌓기 **전에** 물었다.

    ``PolicyChooser`` 가 불린 때가 곧 해결 시점이다 — ``EffectExecutor`` 가
    계획 중에 부르므로, 체인이 풀리는 그 안이 아니면 불릴 자리가 없다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)

    #: ① 후보를 물어보기만 해도 묻지 않는다.
    assert _trigger_action(duel) is not None
    assert chooser.records == ()

    #: ② 발동해도 묻지 않는다 — 응답 창이 열려 있다.
    duel.apply(_trigger_action(duel))
    assert chooser.records == ()

    #: ③ 체인이 풀릴 때 **비로소** 묻는다.
    _settle(duel)
    assert len(chooser.records) == 1
    record = chooser.records[0]
    assert isinstance(record, ChoiceRecord)
    assert record.effect_ref == EffectRef(GIRSU, 0)
    assert len(record.chosen) == 1


@pytest.mark.real_card
@requires_official_db
def test_a05_the_card_actually_moves_from_deck_to_grave(repository):
    """
    🔴 **수준 3.** 외부 행동 지정 없이 Deck → Graveyard 가 일어난다.

    정책이 결정한 것: ① 일반 소환 ② 유발 발동 ③ 어느 카드.
    시험이 준 것: 덱 레시피 · 선공 패 · 정책.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    deck_before = len(duel.state.player(MINE).zone(Zone.DECK))
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0

    _summon(duel)
    duel.apply(_trigger_action(duel))
    _settle(duel)

    assert len(duel.state.player(MINE).zone(Zone.DECK)) == deck_before - 1
    grave = duel.state.player(MINE).zone(Zone.GRAVE)
    assert len(grave) == 1
    moved = duel.state.find_instance(grave[0].instance_id)
    #: 🔴 움직인 것이 **정책이 고른 그 인스턴스**다.
    assert moved.instance_id == chooser.records[0].chosen[0]
    #: 그리고 그것이 6-X 가 근거를 찾은 카드다.
    assert moved.card_id == GROWTH
    assert moved.zone is Zone.GRAVE


@pytest.mark.real_card
@requires_official_db
def test_a06_the_journal_records_the_movement(repository):
    """기록이 **무엇이 실제로 일어났는지** 말한다 — 주장이 아니라 사건이다."""
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    _settle(duel)

    entries = [str(e) for e in duel.journal]
    joined = " ".join(entries)
    assert "send_to_grave" in joined, entries
    assert "DECK" in joined and "GRAVE" in joined, entries
    #: 덱에서 꺼낸 뒤 섞는다 — 남은 순서를 알 수 없게 된다.
    assert "섞었다" in joined, entries
    #: 소환 기록이 **앞에** 있다 — 그것이 이 유발의 사건이다.
    assert any("summon" in e.lower() for e in entries), entries


@pytest.mark.real_card
@requires_official_db
def test_a07_the_duel_goes_on_after_the_resolution(repository):
    """
    해결 뒤 **후속 상태가 정상이다** — 체인이 비고 후보가 다시 만들어진다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    _settle(duel)

    assert len(duel.chain) == 0
    assert duel.priority.is_open is False
    assert duel.is_over is False
    legal = duel.legal_actions(duel.to_act)
    assert legal.allowed, legal.withheld
    kinds = {a.kind.value for a in legal.allowed}
    assert "end_phase" in kinds, kinds
    #: 🔴 같은 사건으로 다시 발동할 수는 없다.
    assert "activate_effect" not in kinds, kinds


@pytest.mark.real_card
@requires_official_db
def test_a08_run_trigger_walks_the_same_path(repository):
    """
    ``run_trigger`` 가 **그 길을 그대로** 지난다 — 제 체인을 세우지 않는다.

    기록이 순서를 적는다: 후보 목록 → 발동 → 상대 패스 → 내 패스.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    offers = trigger_offers(duel, repository, MINE)
    run = run_trigger(
        duel, repository, MINE, offers[0], FirstPermittedChoice(), chooser=chooser
    )

    assert run.activated is True
    assert run.refused is None, run.refused
    assert run.links == 1
    assert run.resolved is True, run.resolution_reason
    assert run.chosen == chooser.records[0].chosen
    #: 🔴 상대와 내가 각각 패스했다는 사실이 기록에 남는다.
    assert any("legal_actions" in note for note in run.notes), run.notes
    assert f"P{THEIRS} 가 패스했다" in run.notes, run.notes
    assert f"P{MINE} 가 패스했다" in run.notes, run.notes
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1


# ======================================================================
# B. 시점과 경계
# ======================================================================


@pytest.mark.real_card
@requires_official_db
def test_b01_declining_never_opens_the_deck(repository):
    """
    🔴 **순서가 규칙이다.** 발동하지 않기로 하면 덱을 **보여 주지 않는다.**

    룰북이 덱을 보는 것을 licensing 하는 자리는 "효과가 그렇게 지시할 때"
    다. 고르기 전에 보여 주면 "덱을 보고 발동할지 정한다" 가 된다.
    """
    setup, chooser = _board(repository, selector=DeclineChoice())
    duel = setup.duel
    _summon(duel)
    offers = trigger_offers(duel, repository, MINE)
    run = run_trigger(
        duel, repository, MINE, offers[0], DeclineChoice(), chooser=chooser
    )

    assert run.activated is False
    assert run.choice is None
    assert run.chosen == ()
    #: 🔴 묻지도 않았다 — 후보를 만들지 않았다.
    assert chooser.records == ()
    #: 판은 그대로다.
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    assert len(duel.chain) == 0
    assert not any("send_to_grave" in str(e) for e in duel.journal)


@pytest.mark.real_card
@requires_official_db
def test_b02_asking_for_candidates_changes_nothing(repository):
    """
    🔴 **묻는 것만으로 판도 사건도 바뀌지 않는다.** 여러 번 물어도 같다.
    """
    setup, _ = _board(repository)
    duel = setup.duel
    _summon(duel)

    before = duel.state.state_hash()
    events_before = len(list(duel.journal))
    for _ in range(5):
        assert len(trigger_offers(duel, repository, MINE)) == 1
        assert _trigger_action(duel) is not None

    assert duel.state.state_hash() == before
    assert len(list(duel.journal)) == events_before
    #: 🔴 **사건이 소비되지 않았다** — 소비는 발동을 수락한 뒤에만 적는다.
    assert duel.consumed_events == frozenset()


@pytest.mark.real_card
@requires_official_db
def test_b03_without_a_chooser_the_resolution_is_refused(repository):
    """
    🔴 **고를 사람이 없으면 거절한다** — 6-Z 이전과 같은 자리 · 같은 문장.

    열린 것은 "있을 때 묻는다" 하나다. 없는 것을 엔진이 대신 고르지 않는다.
    """
    setup, chooser = _board(repository, selector=None)
    assert chooser is None
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    steps = _settle(duel)

    #: 🔴 **마지막 걸음이 아니라 해결 걸음을 읽는다** (보완5 정정). 보완5
    #: 전까지 이 줄은 ``steps[-1]`` 을 읽었고, 지금 그 자리는 빠른 효과
    #: 기회를 닫는 PASS 다 — *"양쪽이 빠른 효과 기회를 지나갔습니다"* 는
    #: 절차를 지났다는 말이고 **링크의 결과가 아니다.**
    last = steps.resolution
    assert last is not None, [st.reason for st in steps]
    #: 패스는 일어났다 (Phase 6-R) — 불발은 **링크의 결과**다.
    assert last.accepted is True
    assert last.code is ValidationCode.TOO_FEW_SELECTED, last.code
    assert "아직 고르지 않은 대상이 있습니다" in last.reason, last.reason
    #: 판은 그대로다.
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    assert not any("send_to_grave" in str(e) for e in duel.journal)


@pytest.mark.real_card
@requires_official_db
def test_b04_choosing_outside_the_candidate_list_is_refused(repository):
    """
    🔴 **정책의 말은 허가가 아니다.** 후보 목록 **밖**은 엔진이 거른다.

    고른 것이 자기 패의 카드라도 — 그 효과의 후보가 아니면 거절된다.
    """
    setup, _ = _board(repository)
    duel = setup.duel
    entry = _summon(duel)
    outsider = duel.state.player(MINE).zone(Zone.HAND)[0].instance_id

    setup2, chooser = _board(repository, selector=_Outsider(outsider))
    duel2 = setup2.duel
    _summon(duel2)
    duel2.apply(_trigger_action(duel2))
    steps = _settle(duel2)

    #: 🔴 해결 걸음을 읽는다 (보완5 정정 — ``test_b03`` 의 설명과 같다).
    last = steps.resolution
    assert last is not None, [st.reason for st in steps]
    assert last.code is ValidationCode.CANDIDATE_NOT_ELIGIBLE, last.code
    assert "후보가 아닌 카드가 들어왔습니다" in last.reason, last.reason
    assert len(duel2.state.player(MINE).zone(Zone.GRAVE)) == 0
    #: 🔴 엔진이 **고르지 않았다** — 가까운 후보로 고쳐 주지 않는다.
    assert len(chooser.records) == 1
    assert chooser.records[0].chosen == (outsider,)
    del entry


@pytest.mark.real_card
@requires_official_db
def test_b05_choosing_too_few_is_refused(repository):
    """장수가 모자라면 거절된다 — ``TargetResolver._check_count`` 가 센다."""
    setup, _ = _board(repository, selector=_Empty())
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    last = _settle(duel).resolution

    assert last.code is ValidationCode.TOO_FEW_SELECTED, last.code
    assert "최소 1장" in last.reason, last.reason
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0


@pytest.mark.real_card
@requires_official_db
def test_b06_choosing_too_many_is_refused(repository):
    """장수가 넘치면 거절된다. 같은 자리 · 다른 부호다."""
    setup, _ = _board(repository, selector=_TooMany(), growth_copies=3)
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    last = _settle(duel).resolution

    assert last.code is ValidationCode.TOO_MANY_SELECTED, last.code
    assert "최대 1장" in last.reason, last.reason
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0


@pytest.mark.real_card
@requires_official_db
def test_b07_an_unknown_candidate_is_refused_by_the_ruling_gate(repository):
    """
    🔴 ``UNKNOWN`` 을 고르면 **6-X 의 관문**이 막는다.

    후보 목록에는 있다 (``TargetResolver`` 가 적법한 대상으로 센다). 막는
    것은 그 **뒤**의 질문이다 — "이 카드를 묘지로 보낼 수 있는가". 모르는
    것을 허가로 바꾸지 않는다.
    """
    setup, chooser = _board(repository, selector=_Cheater())
    duel = setup.duel
    _summon(duel)
    duel.apply(_trigger_action(duel))
    last = _settle(duel).resolution

    assert "판정할 수 없는 것을 허가로 바꾸지 않습니다" in last.reason, last.reason
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 0
    #: 고른 후보가 실제로 ``UNKNOWN`` 이었다.
    record = chooser.records[0]
    chosen = record.chosen[0]
    verdict = next(c for c in record.offer.candidates if c.instance == chosen)
    assert verdict.verdict is ConditionResult.UNKNOWN
    assert verdict.permitted is False


@pytest.mark.real_card
@requires_official_db
def test_b08_an_activation_without_an_event_is_refused(repository):
    """
    🔴 **사건 없는 발동을 막는다.** ``TRIGGER`` 를 허용 목록에 넣어 끝낸
    것이 아니다 — 사건이 뒷받침하는 짝에만 관문이 열린다.
    """
    setup, _ = _board(repository)
    duel = setup.duel
    hand = duel.state.player(MINE).zone(Zone.HAND)
    girsu = next(
        c.instance_id
        for c in hand
        if duel.state.find_instance(c.instance_id).card_id == GIRSU
    )

    #: ① 소환 전 — 사건이 없다.
    step = duel.apply(
        PlayerAction.activate_effect(
            actor=MINE, source=girsu, effect_ref=EffectRef(GIRSU, 0)
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
    assert step.accepted is False
    assert "구현하지 않은 규칙" in step.reason, step.reason
    assert len(duel.chain) == 0

    #: ② **다른 인스턴스로는 열리지 않는다.** 사건은 짝으로 묻는다.
    entry = _summon(duel)
    assert entry.action.source == girsu
    other = next(
        c.instance_id for c in duel.state.player(MINE).zone(Zone.HAND)
    )
    wrong = duel.apply(
        PlayerAction.activate_effect(
            actor=MINE, source=other, effect_ref=EffectRef(GIRSU, 0)
        )
    )
    assert wrong.accepted is False
    #: 🔴 **정정 (보완6): 거절이 무엇이 틀렸는지 말한다.** 전에는 *"지금
    #: 허가된 행위가 아닙니다"* 였고, 지금은 관문의 말이 그대로 나온다 —
    #: 이 시험이 재려는 **바로 그 사실**이다.
    assert "다릅니다" in wrong.reason, wrong.reason
    assert str(GIRSU) in wrong.reason


@pytest.mark.real_card
@requires_official_db
def test_b09_the_same_event_cannot_be_used_twice(repository):
    """
    🔴 **같은 사건으로 두 번 발동하지 않는다.** 소비는 수락한 뒤에 적는다.
    """
    setup, _ = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)
    action = _trigger_action(duel)
    assert duel.consumed_events == frozenset()

    assert duel.apply(action).accepted is True
    #: 🔴 **수락 직후** 적힌다 — 해결을 기다리지 않는다.
    assert len(duel.consumed_events) == 1
    key = next(iter(duel.consumed_events))
    assert key[1] == EffectRef(GIRSU, 0)

    _settle(duel)
    #: 후보에서 사라졌다.
    assert _trigger_action(duel) is None
    assert trigger_offers(duel, repository, MINE)
    #: 그리고 직접 넣어도 받지 않는다.
    assert duel.apply(action).accepted is False
    assert len(duel.state.player(MINE).zone(Zone.GRAVE)) == 1


@pytest.mark.real_card
@requires_official_db
def test_b10_a_refused_activation_does_not_consume_the_event(repository):
    """
    거절된 발동은 사건을 쓰지 않았다 — 다시 시도할 수 있어야 한다.

    여기서 거절되는 것은 **해결**이고 발동은 수락되었으므로 사건은 쓰였다.
    그 둘을 가른다: 발동이 거절되면(사건 없는 짝) 소비가 **없다.**
    """
    setup, _ = _board(repository)
    duel = setup.duel
    hand = duel.state.player(MINE).zone(Zone.HAND)
    wrong = hand[-1].instance_id
    duel.apply(
        PlayerAction.activate_effect(
            actor=MINE, source=wrong, effect_ref=EffectRef(GIRSU, 0)
        )
    )
    assert duel.consumed_events == frozenset()
    #: 그 뒤에도 정상 발동이 가능하다.
    _summon(duel)
    assert _trigger_action(duel) is not None


@pytest.mark.real_card
@requires_official_db
def test_b11_the_candidates_are_counted_at_resolution_time(repository):
    """
    🔴 **후보는 해결 시점의 판에서 세어진다** — 발동 시점의 판이 아니다.

    같은 효과를 한 턴에 두 번 해결하고 후보 수를 견준다. 첫 해결이 덱에서 한
    장을 꺼내므로, **둘째 해결의 후보가 하나 적다.** 발동 시점에 세어 두었다면
    둘이 같아야 한다.

    어리석은 매장으로 센다 — 기르수는 한 턴에 한 번만 일반 소환할 수 있으므로
    (규칙) 같은 턴에 두 번 유발시킬 수 없다. 재는 것은 **해결 시점 선택 경로**
    이고 그 경로는 두 효과가 공유한다 (``test_b13``).
    """
    setup, chooser = _board(
        repository, selector=FirstPermittedChoice(), extra_hand=(BURIAL, BURIAL)
    )
    duel = setup.duel

    for _ in range(2):
        burial = next(
            c.instance_id
            for c in duel.state.player(MINE).zone(Zone.HAND)
            if duel.state.find_instance(c.instance_id).card_id == BURIAL
        )
        action = PlayerAction.activate_effect(
            actor=MINE, source=burial, effect_ref=EffectRef(BURIAL, 0)
        )
        assert action in duel.legal_actions(MINE).allowed
        assert duel.apply(action).accepted is True
        _settle(duel)

    assert len(chooser.records) == 2
    counts = [len(r.offer.candidates) for r in chooser.records]
    #: 🔴 둘째가 **하나 적다** — 첫째가 덱에서 한 장을 꺼냈기 때문이다.
    assert counts[1] == counts[0] - 1, counts

    #: 🔴 **판정도 해결 시점의 판을 본다.** 첫째가 보낸 카드가 묘지에 생겼고,
    #: 6-X 의 간섭 규칙이 그 자리를 보수적으로 읽는다 (``INTERFERENCE_ZONES``
    #: 에 ``GRAVE`` 가 있다). 그래서 둘째의 허용 후보가 줄어든다 — 발동
    #: 시점에 굳혀 두었다면 이 변화가 보이지 않는다.
    permitted = [len(r.offer.permitted) for r in chooser.records]
    assert permitted[0] > 0, permitted
    assert permitted[1] < permitted[0], permitted


@pytest.mark.real_card
@requires_official_db
def test_b12_activation_time_targeting_is_untouched(repository):
    """
    🔴 **발동 시점 대상 지정이 그대로다.** 미뤄지는 것은 **가려진 존**의
    고르기 하나다 (:data:`~engine.target_bridge.CONCEALED_ZONES`).

    실측: 실행 등재된 효과 15개 중 미뤄진 것은 **둘**이고 (기르수 · 어리석은
    매장) 둘 다 덱을 본다. 나머지 열셋은 한 글자도 달라지지 않는다.
    """
    from engine.effect.library import EFFECT_LIBRARY
    from engine.target_bridge import (
        CONCEALED_ZONES,
        chosen_bindings,
        decided_at_resolution,
    )

    assert CONCEALED_ZONES == frozenset({Zone.DECK, Zone.EXTRA})

    deferred, kept = [], []
    for entry in EFFECT_LIBRARY:
        if not entry.executable:
            continue
        definition = entry.definition
        if any(decided_at_resolution(b.spec) for b in definition.targets):
            deferred.append(definition.effect_ref.card_id)
        else:
            kept.append(definition.effect_ref.card_id)

    assert sorted(deferred) == sorted([GIRSU, BURIAL]), deferred
    assert len(kept) == 13, kept
    #: 🔴 미뤄진 둘은 **덱을 본다** — 그것이 미루는 유일한 이유다.
    for card_id in deferred:
        definition = next(
            e.definition
            for e in EFFECT_LIBRARY
            if e.definition.effect_ref.card_id == card_id
        )
        looked = set()
        for binding in definition.targets:
            looked |= binding.spec.looked_at_zones()
        assert looked & CONCEALED_ZONES, (card_id, looked)

    #: 벌금은 패를 본다 — 발동 시점에 2장을 그대로 받는다.
    from engine.effect.library import definition_registry

    fine = definition_registry().definition_for(EffectRef(FINE, 0))
    assert [decided_at_resolution(b.spec) for b in fine.targets] == [False]
    assert len(chosen_bindings(fine)) == 1
    assert (
        fine.targets[0].spec.choice.minimum,
        fine.targets[0].spec.choice.maximum,
    ) == (2, 2)


@pytest.mark.real_card
@requires_official_db
def test_b13_a_different_effect_uses_the_same_resolution_choice(repository):
    """
    🔴 **기르수 전용이 아니다.** 어리석은 매장도 같은 해결 시점 선택을 쓴다.

    그쪽은 **카드 발동**이다 (유발이 아니다) — 그래서 이 시험이 보이는 것은
    "유발 경로" 가 아니라 **해결 시점 선택 경로**가 효과 종류와 무관하다는
    것이다.

    🔴 **유발 효과는 이 저장소에 하나뿐이다** (``test_c09`` 가 센다). 그래서
    "다른 유발로도 돈다" 는 **아직 측정할 수 없고**, 그 사실을 숨기지 않는다.
    """
    setup, chooser = _board(
        repository, selector=FirstPermittedChoice(), extra_hand=(BURIAL,)
    )
    duel = setup.duel
    burial = next(
        c.instance_id
        for c in duel.state.player(MINE).zone(Zone.HAND)
        if duel.state.find_instance(c.instance_id).card_id == BURIAL
    )
    action = PlayerAction.activate_effect(
        actor=MINE, source=burial, effect_ref=EffectRef(BURIAL, 0)
    )
    legal = duel.legal_actions(MINE)
    assert action in legal.allowed, [str(a) for a in legal.allowed]
    #: 🔴 **대상이 비어 있다** — 덱의 카드는 행위에 실리지 않는다.
    assert action.targets == ()

    assert duel.apply(action).accepted is True
    assert chooser.records == ()  # 아직 묻지 않았다
    _settle(duel)

    assert len(chooser.records) == 1
    assert chooser.records[0].effect_ref == EffectRef(BURIAL, 0)
    grave = duel.state.player(MINE).zone(Zone.GRAVE)
    #: 어리석은 매장 자신도 해결 뒤 묘지로 간다 (RULE-SPELLTRAP-002).
    ids = {duel.state.find_instance(c.instance_id).card_id for c in grave}
    assert BURIAL in ids, ids
    assert chooser.records[0].chosen[0] in {c.instance_id for c in grave}


@pytest.mark.real_card
@requires_official_db
def test_b14_different_policies_give_different_results(repository):
    """
    🔴 **정책이 달라지면 전개도 달라진다** — 고정된 결과가 아니다. 그리고
    같은 씨앗이면 같은 결과다 (재현).
    """
    def drive(selector):
        setup, chooser = _board(
            repository, selector=selector, growth_copies=3
        )
        duel = setup.duel
        _summon(duel)
        action = _trigger_action(duel)
        if action is not None and selector.accept_offer_for_test:
            duel.apply(action)
            _settle(duel)
        return (
            len(duel.state.player(MINE).zone(Zone.GRAVE)),
            tuple(r.chosen for r in chooser.records),
        )

    class _Wrap:
        def __init__(self, inner, accept):
            self._inner = inner
            self.name = inner.name
            self.accept_offer_for_test = accept

        def accept_offer(self, offer):
            return self._inner.accept_offer(offer)

        def choose_cards(self, offer):
            return self._inner.choose_cards(offer)

    #: 받아들이는 정책은 카드를 옮기고, 거절하는 정책은 옮기지 않는다.
    assert drive(_Wrap(FirstPermittedChoice(), True))[0] == 1
    assert drive(_Wrap(DeclineChoice(), False))[0] == 0

    #: 씨앗이 같으면 같은 선택이다.
    first = drive(_Wrap(RandomChoice(5), True))
    again = drive(_Wrap(RandomChoice(5), True))
    assert first == again

    #: 씨앗이 다르면 선택이 갈린다.
    seen = {drive(_Wrap(RandomChoice(s), True))[1] for s in (1, 2, 5, 11, 23)}
    assert len(seen) >= 2, seen


# ======================================================================
# C. 구조 — 무엇을 주지 않았고 무엇을 넓히지 않았는가
# ======================================================================


def test_c01_the_request_carries_no_mutable_board():
    """
    🔴 **AI 에 ``GameState`` 도 ``Duel`` 도 주지 않는다.**

    요청에 실리는 것은 관측(``GameStateView``) 하나다. 그 모양을 필드로
    센다 — 이름만 읽어서는 무엇이 실려 있는지 알 수 없다.
    """
    import dataclasses

    from engine.effect.executor import ResolutionChoice

    fields = {f.name for f in dataclasses.fields(ResolutionChoice)}
    assert fields == {
        "effect_ref",
        "target_ref",
        "view",
        "candidates",
        "minimum",
        "maximum",
    }, fields
    #: 🔴 판을 가리키는 이름이 하나도 없다.
    for forbidden in ("state", "duel", "board", "chain", "journal", "executor"):
        assert forbidden not in fields, forbidden


def test_c02_the_chooser_protocol_takes_only_the_request():
    """
    선택을 받는 통로는 **하나의 질문**이다 — ``choose(request)``.

    판을 넘기는 자리가 없으므로, 정책이 판을 만질 길이 없다.
    """
    from engine.effect.executor import ResolutionChooser

    signature = inspect.signature(ResolutionChooser.choose)
    assert list(signature.parameters) == ["self", "request"]


@pytest.mark.real_card
@requires_official_db
def test_c03_the_ordinary_view_still_hides_the_deck(repository):
    """
    🔴 **경계가 그대로다.** 평소 관측으로는 덱이 보이지 않는다 — 열리는
    것은 규칙이 선언한 ``looked_at`` 뿐이고, 발동을 정한 뒤에만 열린다.
    """
    from engine.game_state_view import GameStateView

    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    duel = setup.duel
    _summon(duel)

    ordinary = GameStateView.from_state(duel.state, viewer=MINE)
    #: 🔴 **목록을 먼저 떠 둔다** — 존 용기는 살아 있으므로 해결 뒤에 읽으면
    #: 이미 줄어든 덱을 보게 되고, 그러면 아무것도 재지 못한다.
    deck = [c.instance_id for c in duel.state.player(MINE).zone(Zone.DECK)]
    assert deck, "덱이 비면 이 시험은 아무것도 재지 않는다"
    assert all(ordinary.find(i) is None for i in deck)

    #: 해결 중의 관측은 **그 효과에만** 열린다.
    duel.apply(_trigger_action(duel))
    _settle(duel)
    granted = chooser.records[0].offer.view
    #: 🔴 **그 관측에는 덱 전체가 보인다** — 규칙이 그 효과에 열어 준 것이다.
    assert all(granted.find(i) is not None for i in deck), "덱이 열리지 않았다"
    #: 🔴 **열린 것은 내 덱뿐이다.** 상대의 덱은 여전히 보이지 않는다.
    theirs = duel.state.player(THEIRS).zone(Zone.DECK)
    assert theirs, "상대 덱이 비면 이 시험은 절반만 잰다"
    assert all(granted.find(c.instance_id) is None for c in theirs), "상대 덱"
    #: 그 관측도 **읽기 전용**이다 — 판을 바꾸는 이름이 없다.
    assert not hasattr(granted, "create_instance")
    assert not hasattr(granted, "move")
    assert not hasattr(granted, "project")


def test_c04_the_duel_still_knows_no_effect_layer():
    """
    🔴 ``engine.duel`` 이 ``engine.effect`` 도 ``integration`` 도 import
    하지 않는다 (ADR-007). 유발 원천과 선택자는 **값으로** 받는다.
    """
    source = _source("engine/duel.py")
    for forbidden in (
        "from engine.effect",
        "import engine.effect",
        "from integration",
        "import integration",
        "from core",
        "from analysis",
    ):
        assert forbidden not in source, forbidden


def test_c05_the_second_execution_path_is_gone():
    """
    🔴 **``BLOCKER-6Y-1`` 이 닫혔다.** 배선이 체인을 **쌓지 않는다.**

    6-Y 의 ``run_trigger`` 는 ``plan`` · ``extend`` · ``ChainResolver`` 를
    직접 불러 ``legal_actions`` 를 지나지 않는 둘째 길을 만들었다. 그 호출이
    남아 있으면 그 길도 남아 있다.
    """
    source = _source("integration/autonomy.py")
    for forbidden in (
        "ChainResolver(",
        "integrator.plan(",
        "integrator.extend(",
        "resolve_top(",
        "resolve_all(",
    ):
        assert forbidden not in source, forbidden
    #: 대신 정상 경로를 부른다.
    assert "duel.legal_actions(" in source
    assert "duel.apply(" in source


def test_c06_the_activation_kinds_in_scope_were_not_widened():
    """
    🔴 **분류 집합을 넓히지 않았다.** 사건으로 열었다.

    넓히면 사건 없이도 유발이 발동되고, 그것은 룰북이 적지 않은 허가다
    (RULE-EFFECT-004 — 유발의 시점은 사건이 정한다).
    """
    from engine.action_validation import (
        ACTIVATION_KINDS_IN_SCOPE,
        MONSTER_ACTIVATION_MISSING_BY_KIND,
    )

    assert ACTIVATION_KINDS_IN_SCOPE == frozenset({ActivationKind.IGNITION})
    #: 🔴 유발의 "없는 이유" 가 **그대로 적혀 있다** — 사건이 없을 때 쓴다.
    assert ActivationKind.TRIGGER in MONSTER_ACTIVATION_MISSING_BY_KIND
    assert "사건이 시점을 정한다" in MONSTER_ACTIVATION_MISSING_BY_KIND[
        ActivationKind.TRIGGER
    ]


def test_c07_the_ruling_registry_was_not_widened():
    """🔴 **허가를 넓히지 않았다.** 6-X 의 등록소가 그대로다."""
    from engine.effect.library import OPERATION_RULINGS

    assert len(OPERATION_RULINGS) == 19


def test_c08_the_defaults_are_the_old_behaviour():
    """
    🔴 **주지 않으면 6-Z 이전과 같다.** 세 자리의 기본값을 센다.

    없는 것을 기본값으로 메꾸지 않는다 (ADR-006).
    """
    from engine.action_validation import ActionValidator
    from engine.duel import Duel
    from engine.effect.executor import EffectExecutor
    from engine.effect.library import build_executor

    assert (
        inspect.signature(ActionValidator.__init__)
        .parameters["event_backed"]
        .default
        == ()
    )
    assert (
        inspect.signature(EffectExecutor.__init__).parameters["chooser"].default
        is None
    )
    assert (
        inspect.signature(build_executor).parameters["chooser"].default is None
    )
    assert inspect.signature(Duel.start).parameters["chooser"].default is None
    assert inspect.signature(Duel.start).parameters["triggers"].default is None
    #: 그리고 ``Duel`` 의 칸 자체도 기본이 비어 있다.
    assert Duel.triggers is None
    assert Duel.consumed_events == frozenset()


def test_c09_girsu_is_the_only_registered_trigger_effect():
    """
    🔴 **측정해 두는 사실.** 실행 등재된 유발 효과가 **하나**다.

    그래서 "다른 유발 효과로도 같은 경로가 돈다" 는 아직 측정할 수 없다
    (``test_b13`` 이 그 한계를 적는다). 이 수가 늘면 이 시험이 먼저 깨지고,
    그때 공통성을 **실제로** 측정해야 한다.
    """
    from engine.effect.library import EFFECT_LIBRARY

    triggers = sorted(
        entry.definition.effect_ref.card_id
        for entry in EFFECT_LIBRARY
        if entry.executable
        and entry.definition.activation_kind is ActivationKind.TRIGGER
    )
    assert triggers == [GIRSU], triggers


@pytest.mark.real_card
@requires_official_db
def test_c10_without_a_trigger_source_nothing_changes(repository):
    """
    🔴 **배선이 없으면 6-Z 이전 그대로다.** 유발 후보가 아예 오르지 않는다.

    그 사실이 중요한 이유: 이 Phase 가 연 것은 **배선 하나**이고, 규칙
    판정을 바꾼 것이 아니다.
    """
    setup, _ = _board(repository, triggers=False)
    duel = setup.duel
    assert duel.triggers is None
    _summon(duel)
    assert _trigger_action(duel) is None
    #: 사건은 있다 — 없는 것은 그것을 읽는 배선이다.
    assert len(trigger_offers(duel, repository, MINE)) == 1


def test_c11_the_agent_layer_imports_no_assembly_layer():
    """
    🔴 ``agent`` 는 ``engine`` 만 읽는다. 조립 층도 코어도 읽지 않는다.

    그 경계가 지키는 것은 "AI 는 카드 데이터의 모양을 모른다" 다 (ADR-007).
    """
    #: 🔴 **import 줄만 본다** — 설명문에 층 이름이 나오는 것은 경계 위반이
    #: 아니다 (그 경계를 적어 두는 것이 설명문의 일이다).
    imports = [
        line.strip()
        for line in _source("agent/choice.py").splitlines()
        if line.startswith(("import ", "from "))
        or line.strip().startswith(("import ", "from "))
    ]
    assert imports, "import 줄이 하나도 없으면 이 시험은 아무것도 재지 않는다"
    for line in imports:
        for forbidden in ("integration", "core", "analysis", "deck", "app"):
            assert forbidden not in line, (line, forbidden)
    #: 거꾸로 조립 층도 ``agent`` 를 읽지 않는다 — 오리 타이핑으로 잇는다.
    wiring = [
        line.strip()
        for line in _source("integration/autonomy.py").splitlines()
        if line.startswith(("import ", "from "))
        or line.strip().startswith(("import ", "from "))
    ]
    assert wiring
    for line in wiring:
        assert "agent" not in line, line


def test_c12_the_discord_and_cli_paths_share_the_same_wiring():
    """
    🔴 **사용자에게 보이는 두 경로가 같은 것을 꽂는다** (Phase 6-Z).

    ``/combo`` (Discord) 와 CLI 가 각각 ``build_opening`` 을 부른다. 한쪽만
    꽂으면 한쪽에서는 유발이 돌고 다른 쪽에서는 돌지 않는다 — 같은 입력에
    다른 답이 나오고, 어느 쪽이 맞는지 알 수 없게 된다.

    그리고 **꽂는 것을 ``deck`` 이 만들지 않는다** — ``build_opening`` 은
    받아서 넘기기만 한다 (``deck`` 이 ``integration`` 을 읽지 않는다).
    """
    #: 🔴 **만드는 자리는 하나다** — ``app.main.opening_wiring``.
    #:
    #: 어댑터가 제 손으로 만들면 ``agent`` · ``integration`` 을 직접 import
    #: 하게 되고, 그 경계는 Phase 5-A 부터 지켜 온 것이다
    #: (``tests/test_discord_bot.py::test_15``). 그래서 공용 자리 하나가
    #: 만들고 둘이 그것을 부른다.
    factory = _source("app/main.py")
    assert "def opening_wiring(" in factory
    assert "PolicyChooser(FirstPermittedChoice())" in factory
    assert "TriggerSource(repository)" in factory
    #: 🔴 **기준점임을 그 자리가 말한다** — 최선이라고 적지 않는다.
    assert "기준점" in factory

    for path in ("app/discord_bot.py", "app/main.py"):
        source = _source(path)
        assert "opening_wiring(" in source, path
        assert "chooser=chooser" in source, path
        assert "triggers=triggers" in source, path

    #: 🔴 어댑터는 그 둘의 계층을 **직접 읽지 않는다.**
    bot_imports = [
        line.strip()
        for line in _source("app/discord_bot.py").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    for line in bot_imports:
        for forbidden in ("agent", "integration", "engine", "core"):
            assert forbidden not in line, (line, forbidden)

    #: 🔴 **사용자에게 보이는 출력이 기준점임을 말한다.**
    assert "기준점" in _source("app/discord_bot.py")

    #: ``deck`` 은 조립 층을 읽지 않는다 — 받아서 넘기기만 한다.
    opening = _source("deck/opening.py")
    imports = [
        line.strip()
        for line in opening.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    for line in imports:
        assert "integration" not in line, line
        assert "agent" not in line, line
    assert "chooser=chooser" in opening
    assert "triggers=triggers" in opening


def test_c13_the_policy_answer_is_revalidated_by_the_engine():
    """
    🔴 **정책의 말은 허가가 아니다.** 배선은 옮기기만 하고, 엔진이 본다.

    ``PolicyChooser.choose`` 가 고른 것을 **거르지 않는다** — 거르면 엔진이
    무엇을 거절하는지가 가려진다. 거절하는 자리는 실행기 안이다.
    """
    source = _source("engine/effect/executor.py")
    #: 후보 목록 밖 · 장수 · 중복을 **엔진이** 본다.
    assert "CANDIDATE_NOT_ELIGIBLE" in source
    assert "resolver.validate(" in source
    wiring = _source("integration/autonomy.py")
    #: 배선의 ``choose`` 는 판정 부호를 쓰지 않는다.
    body = wiring[wiring.index("    def choose(self, request)") :]
    body = body[: body.index("\n    def __repr__")]
    for forbidden in ("ValidationCode", "permitted", "minimum", "maximum"):
        assert forbidden not in body, forbidden
