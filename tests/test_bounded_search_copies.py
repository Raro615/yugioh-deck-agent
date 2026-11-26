"""
Phase 6-BP — **같은 카드의 사본**이 탐색을 두 배로 쓰던 것을 접는다.

이 파일이 지키는 사실
---------------------
A. 묶는 기준은 **존과 ``card_id``** 뿐이다 — 카드 이름도 효과도 보지 않고,
   엑스트라 덱 **밖**은 건드리지 않는다.
B. 접어도 **같은 판**이다 — 두 사본으로 만든 두 행동을 각각 적용하면
   ``state_hash`` 가 같다. 🔴 이것이 접기의 **근거**이고, 주장이 아니라
   측정이다 (6-BO 보고서 §70-5 가 적어 둔 한계를 다시 잰다).
C. 접히는 것은 **"어느 사본을 썼는가"** 뿐이다 — 소재 · 대상 · 비용은
   접지 않는다.
D. 사본이 없으면 **한 글자도 달라지지 않는다** (항등).
"""

import pytest

from engine.vocabulary import Zone

from tests.conftest import requires_official_db

GIRSU = 69811710
GALATEA = 30741503
GALATEA_I = 48835607
LONGIRSU = 76145142
CYMBAL_SKELETON = 21441617
DINGIRSU = 93854893

pytestmark = requires_official_db


# ======================================================================
# A. 묶는 기준
# ======================================================================
def test_a01_only_the_extra_deck_and_only_repeated_card_ids(repository):
    """엑스트라 덱의 **사본이 둘 이상인 ``card_id``** 만 묶인다."""
    from agent.bounded_search import interchangeable_copies
    from tests.test_galatea_effect_extension import _setup

    duel = _setup(repository).duel
    leaders = interchangeable_copies(duel, 0)

    counts: dict = {}
    for card in duel.state.zone(0, Zone.EXTRA):
        if card is not None:
            counts[card.card_id] = counts.get(card.card_id, 0) + 1
    repeated = {cid for cid, n in counts.items() if n > 1}
    assert repeated, "이 덱의 엑스트라 덱에는 사본이 둘인 카드가 있다"

    #: 묶인 개체는 전부 그 card_id 들의 것이다.
    by_instance = {
        card.instance_id.value: card.card_id
        for card in duel.state.zone(0, Zone.EXTRA) if card is not None
    }
    for one in leaders:
        assert by_instance[one] in repeated, one
    #: 그 card_id 의 개체는 **전부** 묶였다.
    for instance, cid in by_instance.items():
        assert (instance in leaders) is (cid in repeated), (instance, cid)


def test_a02_cards_outside_the_extra_deck_are_never_grouped(repository):
    """패 · 묘지 · 판 위의 개체는 하나도 들어가지 않는다."""
    from agent.bounded_search import interchangeable_copies
    from tests.test_galatea_effect_extension import _setup

    duel = _setup(repository).duel
    leaders = interchangeable_copies(duel, 0)
    inside = {
        card.instance_id.value
        for card in duel.state.zone(0, Zone.EXTRA) if card is not None
    }
    assert set(leaders) <= inside


def test_a03_an_extra_deck_without_copies_groups_nothing(repository):
    """🔴 **항등** — 사본이 없으면 빈 표다."""
    from agent.bounded_search import fold_interchangeable, interchangeable_copies
    from tests.test_galatea_effect_extension import _setup

    duel = _setup(repository).duel
    #: 사본 하나를 엑스트라 덱에서 **빼면** 그 묶음이 사라진다.
    extra = duel.state.player(0).zone(Zone.EXTRA)
    counts: dict = {}
    for card in list(extra):
        if card is not None:
            counts.setdefault(card.card_id, []).append(card)
    for cards in counts.values():
        while len(cards) > 1:
            extra.remove(cards.pop().instance_id)
    assert interchangeable_copies(duel, 0) == {}

    legal = duel.legal_actions(duel.to_act)
    kept = fold_interchangeable(list(legal.allowed), {})
    assert kept == list(legal.allowed)


# ======================================================================
# B. 접기의 근거 — 같은 판이 된다
# ======================================================================
def _dingirsu_actions(duel):
    from engine.action import PlayerActionKind

    return [a for a in duel.legal_actions(0).allowed
            if a.kind is PlayerActionKind.XYZ_SUMMON]


def test_b01_the_two_copies_reach_the_same_board(repository):
    """
    🔴 **접기의 근거.** 롱기르수가 선 판에서 딩기르수 **두 사본**으로 만든
    두 엑시즈 소환은 적용하면 ``state_hash`` 가 같다.
    """
    from tests.test_dingirsu_xyz_summon import _reference_longirsu_board

    duel = _reference_longirsu_board(repository)
    found = _dingirsu_actions(duel)
    sources = sorted(a.source.value for a in found)
    assert len(sources) == 2, sources

    #: 🔴 **사본에만 적용한다** — 원본 판을 밀면 뒤의 단언이 거짓이 된다
    #: (``Simulator.fork`` 가 그 자리다).
    from agent.simulation import Simulator

    hashes = []
    for action in found:
        fork = Simulator(duel).fork()
        fork.apply(action)
        hashes.append(fork.state.state_hash())
    assert hashes[0] == hashes[1], hashes
    #: 🔴 **고른 개체는 달랐다** — 같은 행동을 두 번 적용한 것이 아니다.
    assert found[0].source != found[1].source


def test_b02_the_fold_keeps_exactly_one_of_them(repository):
    """두 행동이 하나로 접히고, **접었다는 사실이 세어진다.**"""
    from agent.bounded_search import (
        _Ledger, fold_interchangeable, interchangeable_copies,
    )
    from tests.test_dingirsu_xyz_summon import _reference_longirsu_board

    duel = _reference_longirsu_board(repository)
    legal = duel.legal_actions(0)
    before = _dingirsu_actions(duel)
    assert len(before) == 2

    ledger = _Ledger()
    kept = fold_interchangeable(
        list(legal.allowed), interchangeable_copies(duel, 0), ledger,
    )
    after = [a for a in kept if a in before]
    assert len(after) == 1, after
    assert ledger.folded_copies == len(legal.allowed) - len(kept)
    assert ledger.folded_copies >= 1
    #: 🔴 **중복 제거와 다른 칸이다** (ADR-002).
    assert ledger.deduped == 0


# ======================================================================
# C. 접지 않는 것
# ======================================================================
def test_c01_materials_and_targets_are_not_folded(repository):
    """🔴 소재 · 대상 · 비용은 대표로 바꾸지 않는다 — 판 위의 자리다."""
    from agent.bounded_search import fold_interchangeable
    from tests.test_dingirsu_xyz_summon import _reference_longirsu_board

    duel = _reference_longirsu_board(repository)
    legal = duel.legal_actions(0)
    #: 억지로 만든 표 — **소재** 번호를 대표로 바꾸라고 시켜도 접히지
    #: 않아야 한다 (``source`` 만 본다).
    mats = {
        m.value: 1 for a in _dingirsu_actions(duel) for m in a.materials
    }
    kept = fold_interchangeable(list(legal.allowed), mats)
    assert len(kept) == len(legal.allowed)


def test_c02_two_different_cards_in_hand_stay_two_actions(repository):
    """같은 종류의 두 행동이라도 **다른 카드**면 접히지 않는다."""
    from engine.action import PlayerActionKind
    from agent.bounded_search import fold_interchangeable, interchangeable_copies
    from tests.test_galatea_effect_extension import _setup

    duel = _setup(repository).duel
    legal = duel.legal_actions(duel.to_act)
    summons = [a for a in legal.allowed
               if a.kind is PlayerActionKind.NORMAL_SUMMON]
    assert len(summons) >= 1
    kept = fold_interchangeable(
        list(legal.allowed), interchangeable_copies(duel, 0),
    )
    still = [a for a in kept if a.kind is PlayerActionKind.NORMAL_SUMMON]
    assert len(still) == len(summons), (still, summons)
