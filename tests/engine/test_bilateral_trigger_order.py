"""
Phase 6-AB 보완4 — **양측 유발 등재 순서 · 응답 단계 분리 · 사본 정의 보존.**

최종 보완(`a60d944`)이 남긴 셋을 재는 파일이다.

    A  양측이 **같은 사건**의 유발 기회를 가질 때, 턴 플레이어가 일반 행동을
       골라 **상대 기회까지 닫을** 수 있었다 (BLOCKER-F3-1). 실측::

           내 claims 1 · 상대 claims 1
           🔴 내 세트 수락 True → 상대 claims 0 → 내 END_PHASE 수락 True

    B  **유발 등재**와 **빠른 효과 응답**이 갈라져 있지 않았다. 첫 유발을
       등재하면 우선권이 곧 열려 (``priority.is_open``) 남은 묶음을 아무도
       묻지 않았다. 실측::

           첫 등재 뒤 priority.is_open=True · 보유=1 · to_act=1
           🔴 그 자리의 허가 ['pass'] — 남은 내 유발은 등재되지 못했다

    C  탐색 사본이 프로덕션 등록부를 **다시 만들어** 원본의 효과 정의를
       잃었다 (``test_trigger_window_completion::test_e04`` · ``test_e05`` 가
       그쪽에서 센다).

공식 근거
---------
🔴 **네 묶음의 순서는 룰북이 적는다** — §*When multiple cards are activated
simultaneously*: *"the turn player builds the Chain starting with their
mandatory effects, in any order. Then the opponent continues the Chain with
their mandatory effects in any order. Afterwards, the turn player adds their
optional effects in any order, and finally the opponent adds their optional
effects in any order."* (`data/rules/documents/sd-rulebook-en-v10.json`)

🔴 **"판이 열린 상태" 는 공식 Fast Effect Timing 도표가 적는다** —
*"Many actions can ONLY be performed when the game state is open (when you're
in box A)."* · *"Whenever either player performs an action, the game state is
no longer open."* 판이 다시 열리는 조건도 같은 자리다: 턴 플레이어가 넘기고,
상대가 되돌려 넘기고, 체인이 없을 때.
(<https://www.yugioh-card.com/en/play/fast-effect-timing/>)

🔴 **체인 도중에 생긴 사건은 그 체인이 끝난 뒤의 기회에서 처리한다** — OCG
카드 데이터베이스 cid=5883 「聖鳥クレイン」 2021-07-01 보충.

구현 권위의 관찰 (Project Ignis / EDOPro 카드 스크립트)
-------------------------------------------------------
🔴 **네 묶음의 축이 구현에도 **일급 플래그**로 있다.** 이 저장소의
``c*.lua`` 전수에서 센 파일 수 (실측)::

    EFFECT_TYPE_TRIGGER_O (임의 유발)        4,471
    EFFECT_TYPE_TRIGGER_F (강제 유발)        1,661
    EFFECT_TYPE_QUICK_O   (임의 유발 즉시)   1,718
    EFFECT_TYPE_QUICK_F   (강제 유발 즉시)      19
    EFFECT_FLAG_DELAY                         2,733

즉 "강제 · 임의" 와 "유발 · 유발 즉시" 가 **네 상수로 갈려 있고**, 룰북이
적는 묶음과 같은 축이다. 기르수 ①의 스크립트가 그 축의 값을 그대로 보인다 —
``EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O`` · ``EFFECT_FLAG_DELAY`` (임의
유발 · 「경우」). 🔴 **이것은 구현 관찰이고 공식 재정이 아니다.**

🔴 **비공식 정리본은 근거로 쓰지 않았다.** 첨부된 나무위키 기반 문서는
쟁점과 카드 사례를 찾는 데 썼고, 이 파일이 단정하는 것은 위의 공식 두
문서와 위의 구현 관찰뿐이다. 그 문서가 제안하는 새 아키텍처(이벤트 버스 ·
``process_seq`` 등)는 **도입하지 않았다** — 기존 ``Duel`` · ``chain`` ·
``priority`` 계층을 그대로 쓴다.

합성과 실제 카드
----------------
🔴 **양측 시나리오는 합성이다.** 실행 구현이 등재된 유발 효과는 기르수 ①
하나이고, **상대의 카드가 내 소환 사건에 유발하는 실제 카드가 이 저장소에
없다.** 그래서 합성하는 것은 둘이다.

    1. **보드 배치** — 상대 덱의 기르수 한 장을 상대 몬스터 존으로 옮긴다.
       그러면 발동 관문이 *"자신이 쥐고 있는 카드가 아닙니다"* 로 거절하지
       않는다 (그 거절이 최종 보완까지 이 자리를 가렸다).
    2. **제안의 자리 · 필수 여부 · 효과 칸** — ``controller`` ·
       ``source`` · ``requirement`` · ``effect_ref`` 를 바꿔 끼운다.

🔴 **허가 · 체인 링크 · 소비 기록 · 최종 상태는 주입하지 않는다** — 전부
``legal_actions`` → ``Duel.apply`` → ``ChainResolver`` 가 만든다.
**실제 카드 지원이 완료되었다는 뜻이 아니다.**
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.choice import FirstPermittedChoice
from agent.simulation import Simulator
from engine.action import PlayerAction, PlayerActionKind
from engine.effect.journal import EffectEvent
from engine.ids import EffectRef
from engine.priority import ResponseWindow
from engine.trigger import TriggerRequirement
from engine.vocabulary import Position, Zone

from integration.autonomy import TriggerSource
from tests.conftest import requires_official_db
from tests.engine.test_trigger_normal_path_integration import (
    GIRSU,
    MINE,
    THEIRS,
    _board,
    _settle,
    _settle_registration,
    _summon,
)
from tests.engine.test_trigger_window_completion import (
    REAL_REF,
    SYNTH_REF,
    _activations,
    _offer_for,
    _wired_pair,
)


# ======================================================================
# 공용 도구
# ======================================================================
def _bilateral(
    repository,
    *,
    mine: TriggerRequirement = TriggerRequirement.OPTIONAL,
    theirs: TriggerRequirement = TriggerRequirement.OPTIONAL,
    give_theirs: bool = True,
):
    """
    🔴 **합성 — 같은 사건에 두 자리의 기회가 열린 판** (파일 머리말의 둘).

    내 쪽은 **실제 기르수 ①** 이고 (덱 → 묘지), 상대 쪽은 같은 기회의 합성
    드로우 효과다 (``SYNTH_REF`` — 대상 선택이 없으므로 상대 덱의 내용에
    기대지 않는다. 상대 덱은 ``build_opening`` 이 채우는 채움 덱이다).

    ``give_theirs=False`` 면 상대에게 제안을 주지 않는다 — "한쪽만 기회를
    가질 때 불필요한 대기가 없는가" 를 재는 쪽이다.
    """
    setup, chooser = _board(repository, selector=FirstPermittedChoice())
    _summon(setup.duel)
    duel = setup.duel
    card = next(
        instance
        for instance in duel.state.player(THEIRS).zone(Zone.DECK)
        if instance is not None and instance.card_id == GIRSU
    )
    duel.state.move(
        card, Zone.MZONE, to_player=THEIRS, position=Position.FACEUP_ATTACK
    )

    class _Bilateral:
        """실제 제안을 받아 **자리별로** 바꿔 끼운다."""

        def __init__(self) -> None:
            self._inner = TriggerSource(repository)

        def offers(self, state, seat: int):
            out = []
            for offer in self._inner.offers(state, MINE):
                if seat == MINE:
                    out.append(dataclasses.replace(offer, requirement=mine))
                elif give_theirs:
                    out.append(
                        dataclasses.replace(
                            offer,
                            controller=THEIRS,
                            source=card.instance_id,
                            effect_ref=SYNTH_REF,
                            requirement=theirs,
                        )
                    )
            return tuple(out)

    wired = _wired_pair(duel, chooser, repository)
    return dataclasses.replace(wired, triggers=_Bilateral()), chooser


def _kinds(duel, seat: int):
    return sorted({action.kind.value for action in duel.legal_actions(seat).allowed})


def _snapshot(duel, seat: int):
    player = duel.state.player(seat)
    return tuple(
        len([card for card in player.zone(zone) if card])
        for zone in (Zone.GRAVE, Zone.DECK, Zone.HAND)
    )


def _state_fingerprint(duel):
    return (
        duel.state.state_hash(),
        len(duel.chain),
        duel.window_floor,
        duel.chain_floor,
        duel.window_passed,
        frozenset(duel.consumed_events),
        duel.priority.is_open,
    )


# ======================================================================
# A. 양측 기회 종료 보장
# ======================================================================


@requires_official_db
def test_a01_my_decline_does_not_close_the_opponents_chance(repository):
    """
    🔴 **내 포기가 상대의 미처리 기회를 없애지 않는다** (A · 목표 ①).

    그리고 내 **일반 행동**이 그 기회를 지나갈 수도 없다 — 유발 처리 기회는
    공식 도표의 box A 가 아니므로, 그 자리의 허가는 그 묶음의 발동과
    ``PASS`` 뿐이다.
    """
    duel, _ = _bilateral(repository)
    assert len(duel._window_claims(MINE)) == 1
    assert len(duel._window_claims(THEIRS)) == 1

    #: 🔴 순서는 룰북의 묶음 순서다 — 임의끼리면 턴 플레이어가 먼저.
    assert duel._window_actor() == MINE
    assert duel.to_act == MINE

    #: 🔴 **일반 행동이 후보에 없다.** 세트도 페이즈 이동도 오르지 않는다.
    assert _kinds(duel, MINE) == ["activate_effect", "pass"]
    #: 🔴 상대는 아직 차례가 아니다.
    assert duel.legal_actions(THEIRS).allowed == ()

    #: 🔴 직접 넣어도 거절된다 — 후보 목록에 없다는 이유에 기대지 않는다.
    before = _state_fingerprint(duel)
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is False
    assert _state_fingerprint(duel) == before

    #: 🔴 내가 포기한다 — 상대의 기회는 **남는다.**
    step = duel.apply(PlayerAction.passing(actor=MINE))
    assert step.accepted is True
    assert MINE in duel.window_passed
    assert len(duel._window_claims(THEIRS)) == 1
    assert duel._window_actor() == THEIRS
    assert duel.to_act == THEIRS

    #: 🔴 그리고 상대가 **실제로 발동할 수 있다.**
    theirs = _activations(duel, THEIRS)
    assert [action.effect_ref for action in theirs] == [SYNTH_REF]
    assert duel.apply(theirs[0]).accepted is True
    assert len(duel.chain) == 1


@requires_official_db
def test_a02_both_decline_and_the_flow_comes_back(repository):
    """
    🔴 **양쪽이 지나가면 판이 다시 열린다** (A · 목표 ①).

    근거는 공식 Fast Effect Timing 도표다 — 턴 플레이어가 넘기고 상대가
    되돌려 넘기고 체인이 없으면 *"the game state is open again."*
    """
    duel, _ = _bilateral(repository)
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True

    assert duel.window_passed == frozenset({MINE, THEIRS})
    assert duel._window_actor() is None
    assert duel.chain.is_empty

    #: 🔴 **정정 (보완5).** 보완4 는 이 자리에 두 줄을 적었다 —
    #:
    #:     assert duel.priority.is_open is False   # "체인이 없으므로 …"
    #:     assert "end_phase" in _kinds(duel, MINE)
    #:
    #: 그래서 **유발 포기가 곧 판이 열린 상태**라고 적혀 있었다. 같은 도표를
    #: 근거로 들면서 그 도표의 가운데를 건너뛴 것이다:
    #:
    #: * *"If there is no effect that can be triggered."* → 턴 플레이어는
    #:   **상자 B** 로 간다 (열린 상태가 아니다).
    #: * *"If the Turn Player passes."* → 상대가 **상자 C** 로 간다.
    #: * 다시 열리는 조건은 **셋**이다 — 턴 플레이어가 넘기고, 상대가
    #:   되돌려 넘기고, 체인이 없다.
    #:
    #: 즉 "체인이 없다" 는 셋 중 **하나**이고, 유발 기회를 지난 것은 그
    #: 셋에 들지 않는다. 지금은 빠른 효과 기회가 열려 있다.
    assert duel.priority.is_open is True
    assert duel.priority.window is ResponseWindow.RESPONSE
    assert duel.priority.holder.seat == duel.turn_player
    assert _kinds(duel, MINE) == ["pass"]
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is False

    #: 🔴 **양쪽이 그 기회를 지나가면** 비로소 판이 열린다.
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert duel.priority.holder.seat == THEIRS
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True
    assert duel.priority.is_open is False

    #: 🔴 이제 판이 열려 있다 — 통상 행동과 페이즈 이동이 돌아온다.
    assert duel.to_act == MINE
    kinds = _kinds(duel, MINE)
    assert "end_phase" in kinds
    assert "activate_effect" not in kinds
    before = duel.state.turn.phase
    assert duel.apply(PlayerAction.end_phase(actor=MINE)).accepted is True
    assert duel.state.turn.phase is not before


@requires_official_db
def test_a03_one_sided_chance_needs_no_waiting(repository):
    """
    🔴 **한쪽만 기회를 가지면 불필요한 대기가 없다** (A).

    상대에게 claim 이 없으면 내 포기 하나로 창이 닫힌다 — 상대에게 묻지
    않는다 (물을 것이 없다).
    """
    duel, _ = _bilateral(repository, give_theirs=False)
    assert len(duel._window_claims(MINE)) == 1
    assert duel._window_claims(THEIRS) == ()

    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    #: 🔴 **유발 기회**는 한 걸음으로 끝났다 — 그 사실은 그대로다.
    assert duel._window_actor() is None
    assert duel.window_passed == frozenset({MINE})

    #: 🔴 **정정 (보완5).** 보완4 는 여기서 곧바로 ``end_phase`` 를
    #: 요구했고, 그래서 *"한쪽만 기회를 가지면 … 상대에게 묻지 않는다"* 가
    #: **빠른 효과 기회까지** 묻지 않는다는 뜻으로 적혀 있었다.
    #:
    #: 묻지 않는 것은 **유발 쪽**이다 (상대에게 claim 이 없으므로 물을 것이
    #: 없다). 빠른 효과는 다른 질문이고, 그쪽은 상대에게도 기회가 있다 —
    #: 유발할 효과가 없어도 함정과 속공 마법은 발동할 수 있기 때문이다.
    #: 유발 포기를 빠른 효과 포기로 간주하지 않는다 (보완5 §2).
    assert duel.to_act == MINE
    assert _kinds(duel, MINE) == ["pass"]
    assert duel.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert duel.to_act == THEIRS
    assert _kinds(duel, THEIRS) == ["pass"]
    assert duel.apply(PlayerAction.passing(actor=THEIRS)).accepted is True

    assert duel.to_act == MINE
    assert "end_phase" in _kinds(duel, MINE)


# ======================================================================
# B. 등재 순서와 응답 단계의 분리
# ======================================================================


@requires_official_db
def test_b01_registration_does_not_pass_priority(repository):
    """
    🔴 **등재 도중에는 우선권이 넘어가지 않는다** (B · 목표 ②).

    룰북 §동시 발동이 그 특수 체인을 **네 묶음 순서대로 쌓는다**고 적는다.
    쌓는 도중에 응답이 열리면 남은 묶음이 등재될 자리가 없다 — 실측으로
    최종 보완에서 그렇게 되었다 (파일 머리말의 B).
    """
    duel, _ = _bilateral(repository)
    assert duel.priority.is_open is False

    mine = _activations(duel, MINE)
    assert [action.effect_ref for action in mine] == [REAL_REF]
    assert duel.apply(mine[0]).accepted is True

    #: 🔴 링크는 올라갔는데 **응답은 열리지 않았다.**
    assert len(duel.chain) == 1
    assert duel.priority.is_open is False
    #: 🔴 그리고 **다음 묶음의 자리**를 가리킨다.
    assert duel._window_actor() == THEIRS
    assert duel.to_act == THEIRS
    assert [a.effect_ref for a in _activations(duel, THEIRS)] == [SYNTH_REF]


@requires_official_db
def test_b02_the_response_stage_opens_only_after_registration(repository):
    """
    🔴 **등재가 끝난 뒤에 응답 단계가 열린다** (B · 목표 ②).

    그리고 쥐는 자리는 **마지막으로 발동한 자리의 상대**다 —
    RULE-CHAIN-001 (*"the opponent is **always** given a chance to
    respond"*) 이 그 자리를 정한다.
    """
    duel, _ = _bilateral(repository)
    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    assert duel.priority.is_open is False

    theirs = _activations(duel, THEIRS)[0]
    assert duel.apply(theirs).accepted is True

    #: 🔴 등재가 끝났다 — 두 자리 모두 더 쌓을 것이 없다.
    assert duel._window_actor() is None
    #: 🔴 이제 응답이 열렸고, 마지막 발동자(P1)의 상대가 쥐었다.
    assert duel.priority.is_open is True
    assert duel.priority.holder.seat == MINE
    assert [link.actor for link in duel.chain] == [MINE, THEIRS]


@requires_official_db
def test_b03_a_past_trigger_cannot_rejoin_after_the_response_stage(repository):
    """
    🔴 **응답 단계로 넘어간 뒤 과거 유발을 다시 끼워 넣지 않는다** (B).

    두 길을 센다 — 후보 목록에 없고, **직접** ``apply`` 해도 거절된다.
    """
    duel, _ = _bilateral(repository)
    mine_offer = _offer_for(duel, REAL_REF, MINE)
    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    assert duel.apply(_activations(duel, THEIRS)[0]).accepted is True
    assert duel.priority.is_open is True

    #: 🔴 아무도 더 등재할 수 없다.
    assert _activations(duel, MINE) == []
    assert _activations(duel, THEIRS) == []
    assert duel._window_actor() is None

    #: 🔴 직접 넣어도 링크가 늘지 않는다.
    links = len(duel.chain)
    fingerprint = _state_fingerprint(duel)
    replay = PlayerAction.activate_effect(
        actor=MINE, source=mine_offer.source, effect_ref=REAL_REF
    )
    assert duel.apply(replay).accepted is False
    assert len(duel.chain) == links
    assert _state_fingerprint(duel) == fingerprint


@requires_official_db
def test_b04_the_registered_chain_resolves_in_reverse(repository):
    """
    🔴 **등재가 끝난 체인이 역순으로 풀리고 결과가 양쪽에 남는다** (B).

    내 쪽은 실제 기르수 ① (덱 → 묘지), 상대 쪽은 합성 드로우다. 그래서
    **두 자리의 판이 각각** 바뀐다 — 한 자리만 보면 역순을 확인할 수 없다.
    """
    duel, chooser = _bilateral(repository)
    before_mine, before_theirs = _snapshot(duel, MINE), _snapshot(duel, THEIRS)

    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    assert duel.apply(_activations(duel, THEIRS)[0]).accepted is True
    settled = _settle(duel)
    assert settled and all(step.accepted for step in settled)
    #: 🔴 **Phase 6-AC 가 해결 뒤에 한 단계를 끼웠다.** 기르수 ① 이 묘지로
    #: 보낸 카드가 성유물－『성장』 이고 그 ② 가 등재 기회를 연다 (box D).
    #: 역순 해결은 그 기회와 **무관하게** 이미 끝났고 (바로 아래 journal 이
    #: 그것을 센다), 판이 다시 열리는 것은 기회를 지난 뒤다.
    #: 🔴 새 창이 열렸다는 사실은 **기회를 지나기 전에** 센다 — 지나간
    #: 자리 기록이 비어 있는 것이 "새 창" 의 뜻이다.
    assert duel.window_passed == frozenset()
    registration = _settle_registration(duel)
    assert all(step.accepted for step in registration)
    _settle(duel)

    #: 🔴 나중에 쌓인 링크(상대)가 먼저 적용되었다.
    applied = [
        event.effect_ref for event in duel.journal if isinstance(event, EffectEvent)
    ]
    assert applied == [SYNTH_REF, REAL_REF]

    #: 🔴 ``GameState`` 가 같은 말을 한다.
    mine_after, theirs_after = _snapshot(duel, MINE), _snapshot(duel, THEIRS)
    assert mine_after == (before_mine[0] + 1, before_mine[1] - 1, before_mine[2])
    assert theirs_after == (
        before_theirs[0],
        before_theirs[1] - 1,
        before_theirs[2] + 1,
    )
    #: 🔴 해결 시점 선택은 **대상이 있는 효과 하나에만** 물었다.
    assert [record.effect_ref for record in chooser.records] == [REAL_REF]

    #: 🔴 그리고 판이 다시 열렸다.
    assert duel.chain.is_empty
    #: 🔴 이 자리의 ``window_passed`` 는 이제 **양쪽이 지나갔다**를 말한다
    #: (Phase 6-AC) — 그 두 걸음이 바로 위에서 일어났기 때문이다. 창이
    #: 새로 열렸는지는 위에서 이미 셌다.
    assert duel.window_passed == frozenset({MINE, THEIRS})
    assert "end_phase" in _kinds(duel, duel.to_act)


@requires_official_db
def test_b05_the_mandatory_group_goes_before_the_optional_one(repository):
    """
    🔴 **강제 묶음이 임의 묶음보다 먼저다 — 자리를 넘어서** (B · 목표 ②).

    룰북 §동시 발동의 순서가 (턴 플레이어 강제 → 상대 강제 → 턴 플레이어
    임의 → 상대 임의) 이므로, **상대의 강제**가 **내 임의**보다 먼저다.
    최종 보완은 자리만 보고 (턴 플레이어 먼저) 강제 · 임의를 섞었다.

    🔴 **구현한 것은 그 네 묶음이다.** 묶음 **안**의 순서는 고르는 쪽의
    것이고 (*"in any order"*), 그 뒤의 7순위(비공개 유발 · 임의 유발 즉시
    등)는 이 엔진에 **없다** — 등재된 효과가 공개 영역 유발 하나뿐이다.
    없는 것을 임의 순서로 실행하지 않는다 (§미지원).
    """
    duel, _ = _bilateral(repository, theirs=TriggerRequirement.MANDATORY)
    assert len(duel._window_group(THEIRS, mandatory=True)) == 1
    assert len(duel._window_group(MINE, mandatory=False)) == 1

    #: 🔴 상대의 강제가 먼저다 — 내 턴인데도.
    assert duel._duty_seat() == THEIRS
    assert duel._window_actor() == THEIRS
    assert duel.to_act == THEIRS
    assert duel.turn_player == MINE

    #: 🔴 강제는 포기할 수 없다 — 그 자리에 ``PASS`` 가 오르지 않는다.
    assert _kinds(duel, THEIRS) == ["activate_effect"]
    #: 🔴 내 자리는 아직 막혀 있고, 이유는 **강제**다.
    mine = duel.legal_actions(MINE)
    assert mine.allowed == ()
    assert [w for w in mine.withheld if "강제 유발" in w.reason]

    #: 🔴 상대가 처리하면 **내 임의 묶음**이 열린다.
    assert duel.apply(_activations(duel, THEIRS)[0]).accepted is True
    assert duel._window_actor() == MINE
    assert duel.priority.is_open is False
    assert _kinds(duel, MINE) == ["activate_effect", "pass"]

    #: 🔴 내가 쌓으면 등재가 끝나고 응답이 열린다.
    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    assert [link.actor for link in duel.chain] == [THEIRS, MINE]
    assert duel.priority.is_open is True


@requires_official_db
def test_b06_one_seat_may_order_its_own_group_and_cannot_repeat(repository):
    """
    🔴 **같은 자리의 여러 유발: 순서는 그 자리가 고르고 중복은 막힌다** (B).

    룰북이 묶음 **안**의 순서를 *"in any order"* 로 둔다. 그래서 내 묶음에
    둘이 있으면 **둘 다 후보**이고, 어느 것을 먼저 쌓아도 된다 — 그리고
    쌓은 것은 같은 사건으로 다시 쌓을 수 없다.

    🔴 **합성이다** — 둘째 효과는 같은 카드 개체의 둘째 칸에 붙인 공통
    연산 하나다 (``test_trigger_window_completion`` 의 ``SYNTH_DEFINITION``).
    """
    from tests.engine.test_trigger_window_completion import _paired_board

    duel, _ = _paired_board(repository)
    assert {a.effect_ref for a in _activations(duel, MINE)} == {
        SYNTH_REF,
        REAL_REF,
    }

    #: ① 둘 중 **뒤쪽**을 먼저 쌓는다 — 순서는 고르는 쪽의 것이다.
    first = next(a for a in _activations(duel, MINE) if a.effect_ref == REAL_REF)
    assert duel.apply(first).accepted is True
    #: 🔴 아직 내 묶음이다 — 우선권이 넘어가지 않았다.
    assert duel.priority.is_open is False
    assert duel._window_actor() == MINE

    #: ② 같은 것을 다시 쌓을 수 없다.
    assert [a.effect_ref for a in _activations(duel, MINE)] == [SYNTH_REF]
    links = len(duel.chain)
    assert duel.apply(first).accepted is False
    assert len(duel.chain) == links

    #: ③ 남은 하나를 쌓으면 등재가 끝난다.
    second = next(
        a for a in _activations(duel, MINE) if a.effect_ref == SYNTH_REF
    )
    assert duel.apply(second).accepted is True
    assert duel._window_actor() is None
    assert duel.priority.is_open is True
    assert [link.effect_ref for link in duel.chain] == [REAL_REF, SYNTH_REF]


# ======================================================================
# C. 보존 — 이번 변경이 깨뜨리지 않은 것
# ======================================================================


@requires_official_db
def test_c01_an_event_born_during_the_chain_waits(repository):
    """
    🔴 **체인 도중에 생긴 사건은 그 체인에 끼지 않는다** (보존).

    근거는 OCG 카드 데이터베이스 cid=5883 「聖鳥クレイン」 2021-07-01 보충.
    등재 단계와 응답 단계를 가른 뒤에도 그 보존이 그대로인지 센다.
    """
    duel, _ = _bilateral(repository)
    base = _offer_for(duel, REAL_REF, MINE)
    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    floor = duel.chain_floor
    assert floor >= 0

    later = dataclasses.replace(base, event_sequence=floor + 2)
    #: 🔴 등재 중에도 **이 체인에는** 들어오지 않는다.
    assert duel._window_admits(later, MINE) is False

    assert duel.apply(_activations(duel, THEIRS)[0]).accepted is True
    for step in _settle(duel):
        assert step.accepted is True

    #: 🔴 체인이 풀린 뒤 새 창이 그 사건을 받는다.
    assert duel.window_floor == floor
    assert duel._window_admits(later, MINE) is True


@requires_official_db
def test_c02_an_unknown_offer_is_still_blocked_in_both_stages(repository):
    """
    🔴 **``UNKNOWN`` 차단이 등재 단계와 응답 단계 모두에서 유지된다** (보존).

    최종 보완의 ① 가 세운 것이고, 등재 · 응답을 가른 뒤에도 그대로여야 한다.
    """
    duel, _ = _bilateral(repository)
    unknown = dataclasses.replace(
        _offer_for(duel, REAL_REF, MINE), wording=None, event_sequence=1
    )
    assert duel._window_admits(unknown, MINE) is None
    assert duel._offer_is_activatable(unknown, MINE) is False

    #: 등재가 진행된 뒤에도.
    assert duel.apply(_activations(duel, MINE)[0]).accepted is True
    assert duel._window_admits(unknown, MINE) is not True
    #: 응답 단계로 넘어간 뒤에도.
    assert duel.apply(_activations(duel, THEIRS)[0]).accepted is True
    assert duel.priority.is_open is True
    assert duel._window_admits(unknown, MINE) is not True


@requires_official_db
def test_c03_asking_again_or_illegally_changes_nothing(repository):
    """
    🔴 **반복 조회와 불법 행동 거절이 기회와 상태를 바꾸지 않는다** (보존).
    """
    duel, _ = _bilateral(repository)
    before = _state_fingerprint(duel)
    seen = set()
    for _ in range(4):
        seen.add(
            (
                duel.to_act,
                duel._window_actor(),
                tuple(sorted(str(a) for a in duel.legal_actions(MINE).allowed)),
                tuple(sorted(str(a) for a in duel.legal_actions(THEIRS).allowed)),
            )
        )
    assert len(seen) == 1
    assert _state_fingerprint(duel) == before

    #: 차례가 아닌 자리의 발동.
    offer = _offer_for(duel, SYNTH_REF, THEIRS)
    illegal = PlayerAction.activate_effect(
        actor=THEIRS, source=offer.source, effect_ref=SYNTH_REF
    )
    assert duel.apply(illegal).accepted is False
    assert _state_fingerprint(duel) == before


@requires_official_db
def test_c04_a_fork_sees_the_same_bilateral_window(repository):
    """
    🔴 **사본이 같은 양측 창을 본다** (C · 목표 ③).

    그리고 한 분기의 포기가 부모와 형제를 닫지 않는다.
    """
    duel, _ = _bilateral(repository)
    simulator = Simulator(duel=duel)
    left, right = simulator._fork(), simulator._fork()

    for fork in (left, right):
        assert fork._window_actor() == duel._window_actor()
        assert len(fork._window_claims(MINE)) == 1
        assert len(fork._window_claims(THEIRS)) == 1
        assert {a.effect_ref for a in _activations(fork, MINE)} == {REAL_REF}

    assert left.apply(PlayerAction.passing(actor=MINE)).accepted is True
    assert left.window_passed == frozenset({MINE})
    assert right.window_passed == frozenset()
    assert duel.window_passed == frozenset()
    assert right._window_actor() == MINE
    assert duel._window_actor() == MINE


def test_c05_the_group_order_lives_in_one_place():
    """
    🔴 **묶음 순서를 정하는 자리가 하나다** (구조).

    두 자리가 순서를 정하면 둘이 갈라진다. ``_window_actor`` 하나가
    (강제 → 임의) × (턴 플레이어 → 상대) 를 돌고, ``_duty_seat`` 는 그
    가운데 **강제 묶음**만 보는 좁은 질문이다.
    """
    import inspect

    from engine.duel import Duel

    source = inspect.getsource(Duel._window_actor)

    #: 🔴 순서를 돌리는 루프가 이 함수 안에 있다.
    assert "for mandatory in (True, False)" in source
    assert "for seat in (self.turn_player, 1 - self.turn_player)" in source

    #: 🔴 그리고 다른 자리는 그 함수를 **부른다** — 제 순서를 만들지 않는다.
    duel_source = inspect.getsource(
        __import__("engine.duel", fromlist=["duel"])
    )
    for name in ("to_act", "_flow_actions", "_enforce_mandatory"):
        body = duel_source[duel_source.index(f"    def {name}") :]
        body = body[: body.index("\n    def ", 10)]
        assert "_window_actor()" in body, name
        assert "for mandatory in (True, False)" not in body, name
