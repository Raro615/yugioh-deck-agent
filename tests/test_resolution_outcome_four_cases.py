"""
Phase 6-AD 후속2 — **네 가지 결과를 서로 섞지 않는다.**

이 묶음이 고정하는 구분 (요청 §2)::

    A  해결되고 조작도 수행되었다
    B  정상 해결 · **확인된 사유**로 조작이 없었다
    C  규칙 · 정보가 없어 확정할 수 없다 (UNKNOWN)
    D  정책의 잘못된 응답 · 실행 오류

🔴 **B 는 선언이 있는 자리에서만 나온다.** 『성장』 ② 의 정의가
:class:`~engine.effect.definition.ResolutionSkip` 으로 **근거와 함께**
선언한 조건에서만이고, 그 근거는 공식 스크립트 ``c93920420.lua`` 의
``s.spop1`` 이다. 아래 ``test_n05`` · ``test_n06`` 이 "선언이 없으면 예전처럼
거절한다" 를 고정한다 — 그래서 이 보완은 ``too_few_selected`` 를 **일괄**
성공으로 바꾼 것이 아니다.

🔴 **C 와 D 는 B 로 바뀌지 않는다.** 모르는 후보가 하나라도 남으면 C 이고
(``test_n04``), 합법 후보가 있는데 정책이 잘못 답하면 D 다
(``test_n01``~``test_n03``).

무엇이 실제인가
---------------
=====================================  =======================
기르수 ① · 『성장』 ② · 『성건』         🔴 **실제 카드 등재**
발동 관문 · 체인 · 해결 · 선택 · 실행    🔴 **실제 공용 경로**
``test_n01``~``test_n03`` 의 **정책**    **시험 전용** (아래)
``test_n05`` 의 효과 **정의**            **합성** (아래)
=====================================  =======================

🔴 D 를 재려면 **잘못 답하는 정책**이 필요하다 — 실제 정책
(:class:`~agent.choice.FirstPermittedChoice`) 은 잘못 답하지 않으므로, 그
자리만 시험이 대신한다. 판정 · 해결 · 실행은 손대지 않는다.
"""

from __future__ import annotations

import pytest

from engine.ids import EffectRef
from engine.validation import CODE_VALIDITY, ActionValidity, ValidationCode
from tests.conftest import requires_official_db

GIRSU = 69811710
WAND = 93920420
SWORD = 40441990
"""「성유물－『성건』」 — 「성유물」 몬스터인데 **특수 소환 가능 여부가
등재되지 않은** 카드. 그래서 후보 자격이 ``UNKNOWN`` 이다 (6-AD 후속)."""

CLIMAX = 703897
KEY = 2930675
AWAKENING = 12989604
WAND_REF = EffectRef(WAND, 1)

pytestmark = requires_official_db


# ======================================================================
# 공용 — 발표한 레시피로 **세 단계**를 돌린다
# ======================================================================
def _wand_line():
    """『성장』 ② 까지 가는 세 단계 (링크 소환을 넣지 않는다)."""
    from deck.combo_policy import ComboLine, PlannedAction

    return ComboLine(
        name="orcust-girsu-wand-only",
        title_ko="기르수 → 『성장』 묘지행 → 패에서 「성유물」 몬스터 특수 소환",
        steps=(
            PlannedAction(kind="normal_summon", card_id=GIRSU),
            PlannedAction(
                kind="activate_effect", card_id=GIRSU, effect_ref=(GIRSU, 0)
            ),
            PlannedAction(
                kind="activate_effect",
                card_id=WAND,
                effect_ref=(WAND, 1),
                resolution_card_ids=(WAND,),
            ),
        ),
        basis=(
            "ORCUST_GIRSU_LINE 의 앞 세 단계와 같은 근거이고 (그쪽 basis), "
            "링크 소환 한 단계만 뺐다 — 특수 소환된 카드를 필드에서 읽기 "
            "위한 시험용 경로다 (test_summon_prohibition_… 의 _wand_line 과 "
            "같은 모양)."
        ),
    )


def _run(repository, hand, *, selector=None, preferred=(WAND,)):
    """
    ``/combo`` 와 **같은 배선**으로 돌린다. ``selector`` 만 바꿔 끼운다.

    🔴 선택 정책 하나만 갈아 끼우고, 유발 · 판정 · 해결 · 실행은
    프로덕션 것을 그대로 쓴다 (``app.main.opening_wiring``).
    """
    from agent.choice import FirstPermittedChoice, PreferredCardChoice
    from app.main import opening_wiring
    from deck.combo_policy import ORCUST_VERIFICATION_RECIPE
    from deck.opening import build_opening, execute_opening
    from deck.recipe import parse_recipe
    from integration.autonomy import PolicyChooser

    draft = parse_recipe(ORCUST_VERIFICATION_RECIPE, repository).draft
    assert draft is not None
    plan = _wand_line()

    class _Wanted:
        resolution_preferences = tuple(preferred)

    chooser, triggers = opening_wiring(repository, _Wanted())
    if selector is not None:
        inner = FirstPermittedChoice()
        if preferred:
            inner = PreferredCardChoice(tuple(preferred), inner)
        chooser = PolicyChooser(selector(inner))
    setup = build_opening(
        repository, draft, list(hand), chooser=chooser, triggers=triggers
    )
    assert setup.can_run, setup.blockers
    run = execute_opening(setup, repository, choose=plan.policy())
    return setup, run, chooser, plan


def _wand_step(run):
    """실행 기록에서 『성장』 ② 의 걸음 (수락된 것). 없으면 ``None``."""
    return next(
        (
            step
            for step in run.steps
            if step.accepted and step.effect_ref == f"{WAND}:e[1]"
        ),
        None,
    )


class _Misanswering:
    """
    🔴 **시험 전용 정책** — 『성장』 ② 의 자리에서만 잘못 답한다.

    다른 효과의 선택은 뒤의 실제 정책에게 그대로 넘긴다. 그래서 이 묶음이
    재는 것은 "엔진이 잘못된 응답을 어떻게 처리하는가" 한 축이다.
    """

    def __init__(self, inner, how):
        self.inner = inner
        self.how = how

    def choose_cards(self, offer):
        if offer.effect_ref != WAND_REF:
            return self.inner.choose_cards(offer)
        return self.how(offer)


# ======================================================================
# N. 네 결과
# ======================================================================
@pytest.mark.real_card
def test_n00_the_normal_path_is_case_a_resolved_and_applied(repository):
    """
    **A** — 조작이 실제로 수행된 해결. 🔴 B 의 칸은 꺼져 있다.
    """
    _setup, run, chooser, _plan = _run(
        repository, [GIRSU, CLIMAX, KEY, AWAKENING, WAND]
    )
    step = _wand_step(run)
    assert step is not None
    #: ① 해결되었고 **조작도** 수행되었다.
    assert step.resolved is True
    assert step.state_changed is True
    assert step.effect_events == (f"{WAND}:e[1]",)
    #: ② 🔴 **B 가 아니다** — 조작 없음 칸이 꺼져 있다.
    assert step.resolved_without_operation is False
    #: ③ 집계도 A 로 센다 — 조작이 수행된 걸음 둘 (기르수 ① · 『성장』 ②)
    #: 이고, **조작 없이 해결된 걸음은 없다**.
    assert run.effects_resolved == 2
    assert run.effects_resolved_without_operation == 0
    #: ④ 실제로 골랐다.
    record = next(r for r in chooser.records if r.effect_ref == WAND_REF)
    assert len(record.chosen) == 1


@pytest.mark.real_card
def test_n01_an_empty_answer_with_a_legal_candidate_stays_a_refusal(
    repository,
):
    """
    **D** — 합법 후보가 있는데 정책이 **빈 선택**을 반환한다 → 거절 유지.

    🔴 **이것이 B 와 갈라지는 자리다.** B 는 *"고를 수 있는 후보가 없다"*
    이고, 여기는 *"후보가 있는데 고르지 않았다"* 다. 선언이 있어도 후자를
    정상 해결로 바꾸지 않는다 — 요청 §2 의 "후보가 실제로 없는 경우와,
    합법 후보가 있는데 정책이 빈 선택을 반환한 경우를 구분한다".
    """
    _setup, run, chooser, plan = _run(
        repository,
        [GIRSU, CLIMAX, KEY, AWAKENING, WAND],
        selector=lambda inner: _Misanswering(inner, lambda offer: ()),
    )
    from deck.combo_policy import line_progress
    from engine.vocabulary import Zone

    record = next(r for r in chooser.records if r.effect_ref == WAND_REF)
    #: ① **후보가 있었다** — 그러므로 B 의 전제가 성립하지 않는다.
    assert len(record.offer.permitted) >= record.offer.minimum >= 1
    assert record.chosen == ()
    #: ② 🔴 **거절이다.** 코드가 그대로 남는다.
    step = _wand_step(run)
    assert step is not None
    assert step.resolved is False
    assert step.step_code == ValidationCode.TOO_FEW_SELECTED.name
    #: ③ 정상 불발로 **위장되지 않았다**.
    assert step.resolved_without_operation is False
    assert run.effects_resolved_without_operation == 0
    assert "일을 하지 않았습니다" not in step.reason
    #: ④ 소환도 없고 전개도 완료가 아니다.
    state = _setup.duel.state
    assert [c.card_id for c in state.zone(0, Zone.MZONE)] == [GIRSU]
    assert line_progress(run, plan).completed is False


@pytest.mark.real_card
def test_n02_a_card_outside_the_offer_is_still_refused(repository):
    """
    **D** — 엉뚱한 개체를 반환한다 → ``CANDIDATE_NOT_ELIGIBLE``.

    필드의 기르수(후보 목록 밖)를 돌려준다. 패의 「성유물」 몬스터가 아니다.
    """
    def _field_monster(offer):
        occupied = offer.view.me.monster_zone.occupied()
        assert occupied, "필드에 기르수가 서 있어야 한다"
        return (occupied[0].instance_id,)

    _setup, run, _chooser, plan = _run(
        repository,
        [GIRSU, CLIMAX, KEY, AWAKENING, WAND],
        selector=lambda inner: _Misanswering(inner, _field_monster),
    )
    from deck.combo_policy import line_progress

    step = _wand_step(run)
    assert step is not None
    assert step.resolved is False
    assert step.step_code == ValidationCode.CANDIDATE_NOT_ELIGIBLE.name
    assert step.resolved_without_operation is False
    assert line_progress(run, plan).completed is False


@pytest.mark.real_card
def test_n03_too_many_cards_are_still_refused(repository):
    """
    **D** — 허용 장수를 넘겨 반환한다 → ``TOO_MANY_SELECTED``.

    패에 「성유물」 몬스터 **둘**(『성장』 · 『성건』)을 두고 둘 다 돌려준다.
    ``s.spop1`` 의 ``SelectMatchingCard(...,1,1,...)`` 은 한 장이다.
    """
    _setup, run, chooser, plan = _run(
        repository,
        [GIRSU, CLIMAX, KEY, WAND, SWORD],
        selector=lambda inner: _Misanswering(
            inner, lambda offer: tuple(c.instance for c in offer.candidates)
        ),
    )
    from deck.combo_policy import line_progress

    record = next(r for r in chooser.records if r.effect_ref == WAND_REF)
    assert len(record.chosen) > record.offer.maximum
    step = _wand_step(run)
    assert step is not None
    assert step.resolved is False
    assert step.step_code == ValidationCode.TOO_MANY_SELECTED.name
    assert step.resolved_without_operation is False
    assert line_progress(run, plan).completed is False


@pytest.mark.real_card
def test_n04_a_duplicate_answer_is_still_refused(repository):
    """**D** — 같은 개체를 두 번 반환한다 → 거절 (중복 또는 장수)."""
    _setup, run, _chooser, _plan = _run(
        repository,
        [GIRSU, CLIMAX, KEY, AWAKENING, WAND],
        selector=lambda inner: _Misanswering(
            inner,
            lambda offer: (
                offer.permitted[0].instance,
                offer.permitted[0].instance,
            ),
        ),
    )
    step = _wand_step(run)
    assert step is not None
    assert step.resolved is False
    assert step.step_code in {
        ValidationCode.DUPLICATE_SELECTION.name,
        ValidationCode.TOO_MANY_SELECTED.name,
    }
    assert step.resolved_without_operation is False
    assert CODE_VALIDITY[
        ValidationCode[step.step_code]
    ] is ActionValidity.INVALID


# ======================================================================
# N5. **선언이 없으면 예전처럼 거절한다**
# ======================================================================
def test_n05_only_the_declared_effect_can_resolve_without_an_operation():
    """
    🔴 **일괄 완화가 아니다** — 등재 목록에서 선언한 정의를 센다.

    실측(이 판): :data:`~engine.effect.library.EFFECT_LIBRARY` 에서
    ``resolution_skip`` 을 선언한 정의는 **『성장』 ② 하나**이고, 그 근거는
    공식 스크립트 ``c93920420.lua`` 의 ``s.spop1`` 을 가리킨다.
    """
    from engine.effect.library import definition_registry

    declared = [
        definition
        for definition in definition_registry().definitions()
        if definition.resolution_skip is not None
    ]
    #: 🔴 **Phase 6-AF 에서 둘이 되었다** — 기르수 ③ 도 해결 시점의 생략을
    #: 선언한다 (``s.tkop`` 이 ``s.tktg`` 와 같은 다섯 가지를 재검사하고,
    #: 거짓이면 아무 일도 하지 않고 끝낸다). 일괄 완화가 아니라 **카드마다
    #: 그 카드의 해결 함수에서 읽은 선언**이라는 것이 이 시험의 사실이고,
    #: 그래서 둘을 각각 근거까지 센다.
    #: 🔴 **Phase 6-AO 에서 셋이 되었다** — 「오르페골 디베르」 ① 도 해결
    #: 시점의 생략을 선언한다. ``c57835716.lua`` 의 ``s.spop1`` 이
    #: ``Duel.GetLocationCount(tp,LOCATION_MZONE)<=0`` 이면 그대로 끝내고,
    #: ``Duel.SelectMatchingCard`` 가 0장이면 ``Duel.SpecialSummon`` 을
    #: 부르지 않는다 — 조건 거짓과 후보 없음 **둘 다**다.
    #:
    #: 🔴 **이전 수가 틀렸던 것이 아니다** — 그때 그 효과는 등재되지 않았다
    #: (ADR-006). 재는 것은 "**일괄 완화가 아니라 카드마다 그 카드의 해결
    #: 함수에서 읽은 선언**" 이고, 그래서 셋을 각각 근거까지 센다.
    from engine.effect.library import GIRSU, HARP_HORROR

    girsu_ref = EffectRef(GIRSU, 2)
    harp_ref = EffectRef(HARP_HORROR, 0)
    assert sorted(str(d.effect_ref) for d in declared) == sorted(
        [str(girsu_ref), str(WAND_REF), str(harp_ref)]
    ), [str(d.effect_ref) for d in declared]
    by_ref = {d.effect_ref: d for d in declared}
    girsu_skip = by_ref[girsu_ref].resolution_skip
    #: 기르수 ③ — 조건이 거짓이면 생략하고, **후보 고르기는 없다.**
    assert girsu_skip.when_condition_false is True
    assert girsu_skip.when_no_candidate is False
    assert "c69811710.lua" in girsu_skip.basis
    assert "s.tkop" in girsu_skip.basis
    skip = by_ref[WAND_REF].resolution_skip
    assert skip.when_condition_false is True
    assert skip.when_no_candidate is True
    #: 🔴 **근거가 스크립트를 가리킨다** — 문구만 바꾼 것이 아니다.
    assert "c93920420.lua" in skip.basis
    assert "s.spop1" in skip.basis
    #: 디베르 ① — 조건 거짓과 후보 없음 **둘 다** 생략이고, 근거가 그
    #: 카드의 스크립트를 가리킨다.
    harp_skip = by_ref[harp_ref].resolution_skip
    assert harp_skip.when_condition_false is True
    assert harp_skip.when_no_candidate is True
    assert "c57835716.lua" in harp_skip.basis
    assert "s.spop" in harp_skip.basis


def test_n06_a_declaration_without_a_basis_is_rejected():
    """🔴 **근거 없는 선언을 만들 수 없다** — 생략은 공짜가 아니다."""
    from engine.effect.definition import ResolutionSkip

    with pytest.raises(ValueError):
        ResolutionSkip(when_no_candidate=True, basis="   ")
    with pytest.raises(ValueError):
        ResolutionSkip(basis="근거는 있지만 생략 조건이 없다")
    #: 둘 다 적으면 만들어진다.
    made = ResolutionSkip(when_no_candidate=True, basis="시험용 근거")
    #: 🔴 **Phase 6-AO 후속에서 칸이 셋이 되었다** — 생략의 **범위**가
    #: 더해졌다 (``no_candidate_scope``). 기본값은
    #: ``whole_effect`` 이고 그것이 6-AO 까지의 유일한 동작이므로, 적지
    #: 않은 선언의 **뜻은 한 글자도 달라지지 않았다**. 정규 표현에 범위를
    #: 넣는 이유는 범위만 다른 두 선언이 **다른 선언**이기 때문이다 —
    #: 빼면 같은 것으로 읽힌다. **이전 기대값이 틀렸던 것이 아니라** 그때는
    #: 칸이 둘이었다.
    assert made.canonical_state() == (False, True, "whole_effect")
    assert "고를 후보가 없음" in made.describe_ko()
    #: 범위를 좁힌 선언은 **다른 정규 표현**이고, 설명도 다르다.
    from engine.effect.definition import NoCandidateScope

    narrowed = ResolutionSkip(
        when_no_candidate=True,
        no_candidate_scope=NoCandidateScope.TARGET_OPERATIONS,
        basis="시험용 근거",
    )
    assert narrowed.canonical_state() == (False, True, "target_operations")
    assert "그 대상을 쓰는 일만 생략" in narrowed.describe_ko()
    #: 🔴 **범위만 적고 조건을 적지 않을 수 없다.**
    with pytest.raises(ValueError):
        ResolutionSkip(
            when_condition_false=True,
            no_candidate_scope=NoCandidateScope.TARGET_OPERATIONS,
            basis="시험용 근거",
        )


def test_n07_the_resolved_statuses_are_exactly_two():
    """
    🔴 **"해결이 끝났다" 는 두 가지뿐이다** — 그 집합을 고정한다.

    이 집합이 넓어지면 ``EffectResult.resolved`` 가 실패까지 해결로
    세기 시작한다. 그래서 숫자가 아니라 **이름**으로 적는다.
    """
    from engine.effect.resolution import _RESOLVED_STATUSES, ResolutionStatus

    assert {s.value for s in _RESOLVED_STATUSES} == {
        "resolved",
        "resolved_without_effect",
    }
    #: 🔴 ``RESOLVED_WITHOUT_EFFECT`` 는 **실패 코드가 아니다**.
    assert ResolutionStatus.RESOLVED_WITHOUT_EFFECT in _RESOLVED_STATUSES
    assert ResolutionStatus.CONDITION_FALSE not in _RESOLVED_STATUSES
    assert ResolutionStatus.UNCHECKED_RULES not in _RESOLVED_STATUSES
