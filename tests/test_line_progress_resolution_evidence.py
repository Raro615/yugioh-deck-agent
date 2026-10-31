"""
Phase 6-AD 후속 ② — **전개 완료 집계가 실제 해결 결과를 반영한다.**

🔴 **이 파일은 보고 함수의 단위 시험이다.** 입력은 손으로 만든
:class:`~deck.opening.ExecutedStep` 이고, 듀얼을 돌리지 않는다. 그래서 이
파일의 통과는 **집계 함수가 올바른 입력에 올바르게 답한다**는 뜻이고 "실제
듀얼에서 그 일이 일어났다" 는 뜻이 **아니다** — 실제 엔진 경로의 결과는
``tests/test_orcust_girsu_line.py`` 와
``tests/test_summon_prohibition_and_resolution_choice.py`` 가 잰다.

무엇이 틀렸었는가
-----------------
6-AD 까지 :func:`~deck.combo_policy.line_progress` 는 ``accepted`` 만으로
걸음을 걸렀고 :func:`~deck.combo_policy._step_matches` 는 종류 · 카드 ·
효과 참조만 보았다. 그래서 **요청이 수락되었다**는 사실 하나로 단계가
세어졌다.

외부 검토자가 그것을 **합성 입력**으로 재현했다: 종류 · 카드 · 효과 ·
해결 시점 선택이 계획과 전부 맞고 **모든 걸음의 ``resolved=False``** 인
기록을 넣으면 ``completed=True`` · ``done=4`` 가 나왔다. 🔴 실제 듀얼에서
네 단계가 전부 실패하고도 완료로 적혔다는 재현이 **아니다** — 집계 함수의
반례다. 아래 ``test_l01`` 이 그것을 고정한다.
"""

from __future__ import annotations

import pytest

from deck.combo_policy import (
    ORCUST_GIRSU_LINE,
    ComboLine,
    LineProgress,
    PlannedAction,
    line_progress,
)
from deck.opening import ExecutedStep, OpeningRun, OpeningSetup

GIRSU = 69811710
WAND = 93920420
GALATEA = 30741503
P0 = 0


# ======================================================================
# 공용 — **기록을 손으로** 만든다 (듀얼을 돌리지 않는다)
# ======================================================================
def _step(
    order: int,
    kind: str,
    *,
    card_id=None,
    effect_ref=None,
    accepted: bool = True,
    resolved: bool = True,
    state_changed: bool = True,
    effect_events=(),
    resolution_choices=(),
    material_card_ids=(),
) -> ExecutedStep:
    """
    합성 걸음 하나. **기본값은 "성공한 걸음"** 이다.

    🔴 그래서 각 시험은 **한 칸만 비틀어** 그 칸이 집계에 쓰이는지를 잰다 —
    여러 칸을 함께 바꾸면 무엇이 걸렀는지 알 수 없다.
    """
    return ExecutedStep(
        order=order,
        actor=P0,
        kind=kind,
        card_id=card_id,
        card_name="(합성 기록)",
        effect_ref=effect_ref,
        targets=(),
        gate_code="OK",
        accepted=accepted,
        step_code="OK",
        reason="(합성 기록)",
        chain_links_after=0,
        chain_resolved_after=0,
        resolved=resolved,
        state_changed=state_changed,
        effect_events=tuple(effect_events),
        next_candidates=0,
        resolution_choices=tuple(resolution_choices),
        material_card_ids=tuple(material_card_ids),
    )


def _run(steps) -> OpeningRun:
    """걸음 목록만 든 실행 기록. ``setup`` 은 집계가 읽지 않는다."""
    run = OpeningRun(setup=OpeningSetup())
    run.steps = list(steps)
    return run


def _girsu_steps(overrides=None) -> list[ExecutedStep]:
    """
    :data:`ORCUST_GIRSU_LINE` 네 단계를 **성공한 모양으로** 적은 기록.

    ``overrides`` 는 ``{걸음 번호(1~4): 바꿀 칸들}`` 이다.
    """
    overrides = overrides or {}
    plan = [
        dict(order=1, kind="normal_summon", card_id=GIRSU),
        dict(
            order=2,
            kind="activate_effect",
            card_id=GIRSU,
            effect_ref=f"{GIRSU}:e[0]",
            effect_events=(f"{GIRSU}:e[0]",),
        ),
        dict(
            order=3,
            kind="activate_effect",
            card_id=WAND,
            effect_ref=f"{WAND}:e[1]",
            effect_events=(f"{WAND}:e[1]",),
            resolution_choices=(WAND,),
        ),
        dict(
            order=4,
            kind="link_summon",
            card_id=GALATEA,
            material_card_ids=(GIRSU, WAND),
        ),
    ]
    steps = []
    for spec in plan:
        spec = {**spec, **overrides.get(spec["order"], {})}
        order = spec.pop("order")
        kind = spec.pop("kind")
        steps.append(_step(order, kind, **spec))
    return steps


# ======================================================================
# L. 집계가 **무엇을** 보는가
# ======================================================================
def test_l00_a_correct_record_still_completes_the_line():
    """
    🔴 **공허하지 않다** — 올바른 기록은 여전히 4/4 다.

    이것이 없으면 아래 반례들은 "집계가 전부 거짓" 으로도 통과한다.
    """
    progress = line_progress(_run(_girsu_steps()), ORCUST_GIRSU_LINE)
    assert isinstance(progress, LineProgress)
    assert progress.completed is True
    assert progress.done == 4
    assert progress.orders == (1, 2, 3, 4)


def test_l01_the_reviewers_counter_example_no_longer_completes():
    """
    🔴 **검토자가 제시한 반례.** 종류 · 카드 · 효과 · 해결 시점 선택이 전부
    맞고 **모든 걸음의 ``resolved=False``** 인 기록이다.

    6-AD 까지: ``completed=True`` · ``done=4``.
    지금: 한 단계도 세지 않는다 — 막힌 자리는 **첫 단계**다.
    """
    steps = _girsu_steps({n: {"resolved": False} for n in (1, 2, 3, 4)})
    progress = line_progress(_run(steps), ORCUST_GIRSU_LINE)
    assert progress.completed is False
    assert progress.done == 0
    assert progress.blocked_at is ORCUST_GIRSU_LINE.steps[0]


def test_l02_an_effect_step_needs_its_own_resolution_record():
    """
    **효과 단계는 그 효과의 해결 근거를 대조한다.**

    ``resolved=True`` 이고 수락됐지만 **그 효과의 ``EffectEvent`` 가 이
    걸음에 없으면** 효과가 적용되지 않았다 — 세지 않는다.
    """
    steps = _girsu_steps({3: {"effect_events": ()}})
    progress = line_progress(_run(steps), ORCUST_GIRSU_LINE)
    assert progress.done == 2
    assert progress.blocked_at is ORCUST_GIRSU_LINE.steps[2]


def test_l03_another_effects_event_is_not_borrowed():
    """
    🔴 **다른 효과의 성공을 가져다 쓰지 않는다.**

    세 번째 걸음의 기록에 **기르수 ①** 의 사건만 적혀 있다. 전체 기록에
    사건이 있다는 이유로 『성장』 ② 가 성공으로 세어지면 안 된다.
    """
    steps = _girsu_steps({3: {"effect_events": (f"{GIRSU}:e[0]",)}})
    progress = line_progress(_run(steps), ORCUST_GIRSU_LINE)
    assert progress.done == 2


def test_l04_a_choice_without_a_summon_is_not_a_completed_step():
    """
    **선택 기록만 남고 소환은 실패한 단계**도 완료로 세지 않는다.

    해결 시점 선택은 계획과 같은데 (``resolution_choices``) 효과가 적용된
    기록이 없고 체인도 끝까지 풀리지 않았다.
    """
    steps = _girsu_steps({3: {"effect_events": (), "resolved": False}})
    progress = line_progress(_run(steps), ORCUST_GIRSU_LINE)
    assert progress.done == 2
    #: 그리고 선택 기록 자체는 그대로 남아 있다 — 지워서 통과시킨 것이 아니다.
    assert steps[2].resolution_choices == (WAND,)


def test_l05_a_summon_step_is_not_failed_for_lacking_an_effect_event():
    """
    🔴 **정상 소환 단계가 ``EffectEvent`` 부재만으로 실패 처리되지 않는다.**

    소환은 효과가 아니므로 (``ExecutedStep.resolved`` 의 설명) 그 기록이
    남지 않는다. 성공 근거는 **판이 바뀌었는가**와 **계획이 요구한 소재**다.
    """
    steps = _girsu_steps()
    assert steps[0].effect_events == ()
    assert steps[3].effect_events == ()
    assert line_progress(_run(steps), ORCUST_GIRSU_LINE).done == 4

    #: 판이 바뀌지 않은 소환은 세지 않는다.
    blocked = _girsu_steps({1: {"state_changed": False}})
    assert line_progress(_run(blocked), ORCUST_GIRSU_LINE).done == 0


def test_l06_the_planned_materials_are_actually_checked():
    """
    **계획이 요구한 소재를 실제로 확인한다.**

    6-AD 까지 기록에는 소재의 **이름**만 있었고 (``materials``) 경로는 카드
    ID 로 적혀 있어 대조할 수 없었다. 그래서 다른 소재로 링크 소환해도 그
    단계가 세어졌다.
    """
    wrong = _girsu_steps({4: {"material_card_ids": (GIRSU, GIRSU)}})
    assert line_progress(_run(wrong), ORCUST_GIRSU_LINE).done == 3

    missing = _girsu_steps({4: {"material_card_ids": ()}})
    assert line_progress(_run(missing), ORCUST_GIRSU_LINE).done == 3

    #: 순서가 달라도 같은 묶음이면 센다 (다중집합 비교다).
    swapped = _girsu_steps({4: {"material_card_ids": (WAND, GIRSU)}})
    assert line_progress(_run(swapped), ORCUST_GIRSU_LINE).done == 4


def test_l07_a_rejected_request_is_never_a_step():
    """``accepted=False`` 는 집계 바깥에서도 안에서도 걸러진다."""
    steps = _girsu_steps({2: {"accepted": False}})
    assert line_progress(_run(steps), ORCUST_GIRSU_LINE).done == 1


def test_l08_a_step_without_a_declared_choice_is_not_asked_for_one():
    """
    🔴 **적지 않은 축으로 거르지 않는다** (``PlannedAction`` 의 규율).

    ``resolution_card_ids`` 를 적지 않은 계획은 선택 기록을 요구하지 않는다 —
    그 축을 일괄 강제하면 선택이 없는 효과의 단계가 영영 세어지지 않는다.
    """
    line = ComboLine(
        name="l08",
        title_ko="선택을 적지 않은 계획",
        steps=(
            PlannedAction(kind="normal_summon", card_id=GIRSU),
            PlannedAction(
                kind="activate_effect", card_id=GIRSU, effect_ref=(GIRSU, 0)
            ),
        ),
        basis="시험용 — ORCUST_GIRSU_LINE 의 앞 두 단계와 같은 근거다.",
    )
    steps = _girsu_steps()[:2]
    assert line_progress(_run(steps), line).done == 2
