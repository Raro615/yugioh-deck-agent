"""
산출물을 **한국어로 적는 자리** (Phase 4-B).

표시만 한다 — 판정하지 않는다. 그래서 여기서 상태를 다시 계산하거나
합치는 일이 없다. 합치면 "검증 불가" 가 "통과" 로 보이게 된다.

🔴 **구현하지 않은 것을 지원하는 것처럼 적지 않는다.** 무작위 패 생성이
없다는 사실을 전개 출력에 그대로 적는다.
"""

from __future__ import annotations

from deck.model import (
    ComboPlan,
    DeckDraft,
    DeckValidation,
    StepStatus,
    ValidationOutcome,
)
from deck.request import DeckRequest

_OUTCOME_MARK = {
    ValidationOutcome.SATISFIED: "✔",
    ValidationOutcome.VIOLATED: "✗",
    ValidationOutcome.UNVERIFIABLE: "?",
}

_STATUS_MARK = {
    StepStatus.CONFIRMED: "✔",
    StepStatus.CONDITIONAL: "~",
    StepStatus.UNKNOWN: "?",
    StepStatus.UNSUPPORTED: "✗",
}

_RULE = "-" * 68


def render_request(request: DeckRequest) -> str:
    lines = ["요청 해석", _RULE, request.describe_ko()]
    if request.is_empty:
        lines.append(
            "🔴 테마도 목표도 해석하지 못했습니다 — 요청을 다시"
            " 적어 주세요")
    return "\n".join(lines)


def render_draft(draft: DeckDraft) -> str:
    lines = ["", "덱 구성안", _RULE]
    lines.append(f"  메인 {draft.main_count}장 (종류 {len(draft.main)})"
                 f" · 엑스트라 {draft.extra_count}장"
                 f" (종류 {len(draft.extra)})")
    if draft.resolved_themes:
        lines.append(f"  해석된 카드군: {', '.join(draft.resolved_themes)}")
    if draft.unresolved_themes:
        lines.append(f"  🔴 해석 실패 테마: "
                     f"{', '.join(draft.unresolved_themes)}")

    for title, slots in (("메인 덱", draft.main), ("엑스트라 덱", draft.extra)):
        if not slots:
            continue
        lines.append("")
        lines.append(f"  [{title}]")
        for slot in slots:
            lines.append(f"    {slot.copies}x  {slot.name}  [{slot.card_id}]")
            #: 🔴 역할과 **그 역할의 출처**를 따로 적는다. 합쳐 적으면
            #: "근거 없이 붙은 역할" 이 "측정된 역할" 처럼 보인다
            #: (Phase 5-D).
            lines.append(f"         역할: {slot.role.describe_ko()}"
                         f"  (출처: {slot.evidence.describe_ko()})")
            lines.append(f"         근거: {slot.reason}")
    if draft.notes:
        lines.append("")
        lines.append("  [구성 기록]")
        lines.extend(f"    - {note}" for note in draft.notes)
    return "\n".join(lines)


def render_validation(validation: DeckValidation) -> str:
    lines = ["", "덱 규격 검증", _RULE]
    for finding in validation.findings:
        mark = _OUTCOME_MARK[finding.outcome]
        lines.append(f"  {mark} {finding.rule}: "
                     f"{finding.outcome.describe_ko()}")
        lines.append(f"      {finding.detail}")
        if finding.source:
            lines.append(f"      근거 규칙: {finding.source}")
    lines.append("")
    lines.append(f"  요약: {validation.describe_ko()}")
    if validation.unverifiable:
        lines.append("  🔴 검증 불가 항목은 **통과가 아닙니다.** 사람이"
                     " 확인해야 합니다")
    return "\n".join(lines)


def render_plan(plan: ComboPlan) -> str:
    lines = ["", "전개 계획", _RULE]
    lines.append(f"  초기 패 {len(plan.hand)}장"
                 f" · 초기 필드·묘지 {len(plan.board)}장")
    lines.append("  (초기 패는 사용자가 지정한 것입니다 —"
                 " 무작위 패 생성은 구현되어 있지 않습니다)")
    lines.append("")
    if not plan.steps:
        lines.append("  계획된 걸음이 없습니다")
    for step in plan.steps:
        mark = _STATUS_MARK[step.status]
        lines.append(f"  {step.order}. {mark} {step.action}")
        lines.append(f"      상태: {step.status.describe_ko()}"
                     f"  ·  근거: {step.basis.describe_ko()}")
        if step.requires:
            for requirement in step.requires:
                lines.append(f"      필요: {requirement}")
        lines.append(f"      기대: {step.expected}")
        if step.note:
            lines.append(f"      비고: {step.note}")
    lines.append("")
    lines.append(f"  요약: {plan.describe_ko()}")
    if plan.stopped_reason:
        lines.append(f"  🔴 중단: {plan.stopped_reason}")
    if plan.unsupported:
        lines.append("")
        lines.append("  [엔진이 지원하지 않아 계획에 넣지 않은 절차]")
        lines.extend(f"    - {item}" for item in plan.unsupported)
    if plan.manual_checks:
        lines.append("")
        lines.append("  [사람이 직접 확인할 것]")
        lines.extend(f"    - {item}" for item in plan.manual_checks)
    return "\n".join(lines)


def render_simulator_steps(plan: ComboPlan) -> str:
    """
    Duel Simulator 에서 **사람이 재현할** 순서.

    🔴 사이트를 조작하지 않는다. 조작했다고 적지도 않는다 — 여기 있는
    것은 사람이 읽고 손으로 따라 할 안내다.
    """
    lines = ["", "Duel Simulator 에서 직접 확인하는 방법", _RULE]
    lines.append("  1. 니어런에서 내보낸 덱 이미지를 사이트에 올립니다")
    lines.append("  2. 해석 결과의 장수를 확인하고 덱에 적용합니다")
    lines.append("  3. 아래 패를 덱에서 패 영역으로 옮깁니다")
    for card_id in plan.hand:
        lines.append(f"       - [{card_id}]")
    lines.append("  4. '기록 개시' 를 누르고 아래 순서대로 조작합니다")
    usable = [s for s in plan.steps
              if s.status in (StepStatus.CONFIRMED, StepStatus.CONDITIONAL)]
    if not usable:
        lines.append("       (근거 있는 걸음이 없습니다)")
    for index, step in enumerate(usable, start=1):
        lines.append(f"       {index}) {step.action}"
                     f"  — {step.status.describe_ko()}")
    lines.append("  5. '기록 종료' 후 공유 URL 을 복사합니다")
    lines.append("")
    lines.append("  🔴 사이트는 규칙을 집행하지 않습니다 — 조작이"
                 " 된다는 것이 합법이라는 뜻은 아닙니다")
    return "\n".join(lines)

# ======================================================================
# Phase 6-T — 실제 실행 결과
# ======================================================================


def render_opening_setup(setup) -> str:
    """
    선공 상태 구성 결과. 🔴 **검증한 것과 못한 것을 같은 표에 섞지 않는다.**
    """
    lines = ["", "선공 상태 구성", _RULE]
    if setup.duel is None:
        lines.append("  🔴 상태를 만들지 않았습니다.")
    else:
        duel = setup.duel
        lines.append(f"  턴 {duel.state.turn.turn_number} ·"
                     f" {duel.state.turn.phase.value} · 선공 P0")
        lines.append(f"  시작 패 {len(setup.hand)}장 ·"
                     f" 남은 메인 덱 {len(setup.deck_rest)}장 ·"
                     f" 엑스트라 {len(setup.extra)}장")
        lines.append("  선공 첫 턴 드로우 없음 (룰북) · 일반 소환권 미사용"
                     " · 사용한 효과 없음")

    satisfied = [f for f in setup.all_findings
                 if f.outcome is ValidationOutcome.SATISFIED]
    lines.append("")
    lines.append(f"  검증 통과 {len(satisfied)}건")
    if setup.violations:
        lines.append(f"  🔴 위반 {len(setup.violations)}건")
        for finding in setup.violations:
            lines.append(f"    - {finding.rule}: {finding.detail}")
    if setup.unverifiable:
        lines.append(f"  ⚠️ 검증 불가 {len(setup.unverifiable)}건"
                     " — **문제 없음이 아닙니다**")
        for finding in setup.unverifiable:
            lines.append(f"    - {finding.rule}: {finding.detail}")
    if setup.blockers:
        lines.append("")
        lines.append("  🔴 실행하지 않은 이유")
        for blocker in setup.blockers:
            lines.append(f"    - {blocker}")
    if setup.unknowns:
        lines.append("")
        lines.append("  🔴 알 수 없는 것 (실행 결과를 읽을 때 함께 보아야 합니다)")
        for unknown in setup.unknowns:
            lines.append(f"    - {unknown}")
    return "\n".join(lines)


def render_opening_run(run) -> str:
    """
    **실제로 실행한 걸음**들. 🔴 정적 계획과 섞지 않는다.

    각 걸음이 세 사실을 따로 적는다 — 행위 수락 · 체인 등록 · 효과 해결
    (Phase 6-R · 6-T).
    """
    lines = ["", "🔴 실제 엔진 실행 (검증된 걸음)", _RULE]
    if not run.steps:
        lines.append("  실행한 걸음이 없습니다.")
    for step in run.steps:
        lines.append(f"  {step.describe_ko()}")
        bits = [f"판정 {step.gate_code}",
                f"수락 {'예' if step.accepted else '아니오'}",
                f"결과 {step.step_code}"]
        if step.chain_links_after:
            bits.append(f"체인 링크 {step.chain_links_after}"
                        f" (해결 {step.chain_resolved_after})")
        bits.append("상태 변경 " + ("있음" if step.state_changed else "없음"))
        lines.append(f"      {' · '.join(bits)}")
        if step.effect_ref:
            lines.append(f"      효과 {step.effect_ref}"
                         + (f" · 대상 {len(step.targets)}개"
                            if step.targets else ""))
        if step.effect_events:
            lines.append(f"      적용된 효과 기록: "
                         f"{', '.join(step.effect_events)}")
        lines.append(f"      이유: {step.reason}")
        if step.note:
            lines.append(f"      🔴 {step.note}")
        #: 🔴 **도중에 만난 미지원은 수와 자리만 이 줄에 붙인다** (보완8 세
        #: 항목 ①). 문장은 아래 누적 목록에 한 번만 적는다 — 걸음마다 다시
        #: 적으면 긴 전개에서 메시지 상한에 걸려 **정적 계획 절이 잘린다**
        #: (실측). 사용자 요구 ①의 *"어디서 확인할 수 있는지 연결해라"* 다.
        during = (
            f" · 🔴 **도중에** 만난 미지원 {len(step.unsupported_during)}건"
            f" (지나온 자리 · 아래 `미지원 사유`)"
            if step.unsupported_during else ""
        )
        lines.append(f"      이 뒤의 행동 후보 {step.next_candidates}건{during}")
        if step.unsupported:
            #: 🔴 **이 걸음 뒤에 "지원하지 않아 오르지 못한 후보" 가 있었다**
            #: (6-AB 최종 보완 ④). 규칙이 막은 것과 섞지 않는다 — 여기 오는
            #: 것은 빠진 규칙의 이름이 붙은 보류뿐이다.
            lines.append(f"      🔴 이 뒤 **자리**의 미지원"
                         f" {len(step.unsupported)}건 (지금 이 자리):")
            lines.extend(f"         - {item}" for item in step.unsupported)
    lines.append("")
    #: 🔴 **"해결" 의 뜻을 적는다** (Phase 6-AA — 사용자 실험 ④).
    #:
    #: ``resolved`` 는 **해결까지 막히지 않은 걸음** 수이고 효과를 해결한
    #: 걸음 수가 아니다 — 체인을 만들지 않는 소환 · 세트도 "막히지 않았다"
    #: 이므로 들어온다. 그 수만 보여 주면 "효과를 N번 해결했다" 로 읽힌다.
    #: 그래서 **효과 해결 수를 따로** 적는다 (기록에 ``EffectEvent`` 가 남은
    #: 걸음만 센 실측이다).
    lines.append(f"  실행 {run.executed}걸음 · 상태 변경 {run.state_changes}걸음")
    lines.append(f"  막히지 않고 끝난 걸음 {run.resolved} / {run.executed}"
                 f" (🔴 효과를 그만큼 해결했다는 뜻이 **아닙니다**)")
    lines.append(f"  그중 **효과가 실제로 해결된 걸음** {run.effects_resolved}걸음"
                 f" (기록에 EffectEvent 가 남은 걸음)")
    if run.stopped_reason:
        lines.append(f"  멈춘 이유: {run.stopped_reason}"
                     + (f" [{run.stopped_kind}]" if run.stopped_kind else ""))
    #: 🔴 **두 질문을 따로 적는다** (보완8 세 항목 ①). 위 줄은 *"왜
    #: 멈췄는가"* 이고, 이 줄은 *"전개 전체를 지원 범위 안에서 검증했는가"*
    #: 다. 하나만 보면 ``flow_only`` 를 "정상 검증 완료" 로 읽는다 — 중간에
    #: 미지원을 지나왔어도 마지막 자리는 깨끗할 수 있기 때문이다 (실측).
    lines.append(
        "  전체 지원 상태: ✅ 모든 자리를 지원 범위 안에서 판정했습니다"
        if run.fully_supported else
        f"  전체 지원 상태: 🔴 **끝까지 검증하지 못했습니다**"
        f" (미지원 {len(run.unsupported)}건 · 멈춘 자리와 다른 질문)"
    )
    if run.unsupported:
        #: 🔴 **실행에 영향을 준 미지원 사유를 전개 요약 안에 둔다** (6-AB
        #: 최종 보완 ④). 걸음별로 흩어 두면 읽는 쪽이 "이 전개는 끝까지
        #: 지원되었다" 로 읽는다 — 이 목록이 비어 있을 때만 그 말을 할 수
        #: 있다.
        lines.append("")
        lines.append(f"  🔴 이 전개 중에 만난 **미지원 사유**"
                     f" {len(run.unsupported)}건 — 엔진이 그 수단을 몰라"
                     f" 후보가 되지 못한 것들입니다 (규칙이 막은 것이"
                     f" 아닙니다):")
        lines.extend(f"    - {item}" for item in run.unsupported)
    else:
        lines.append("")
        lines.append("  이 전개 중에 **미지원으로 보류된 후보는 없었습니다**"
                     " (빠진 규칙 이름이 붙은 보류가 없습니다).")
    return "\n".join(lines)


def render_opening_board(setup, repository=None) -> str:
    """실행 뒤의 판 — **읽은 것만** 적는다. 이름은 저장소가 있을 때만."""
    from engine.vocabulary import Zone

    lines = ["", "현재까지의 결과 (실제 GameState)", _RULE]
    if setup.duel is None:
        lines.append("  상태가 없습니다.")
        return "\n".join(lines)
    state = setup.duel.state
    rows = (
        ("몬스터 존", Zone.MZONE), ("마법·함정 존", Zone.SZONE),
        ("패", Zone.HAND), ("묘지", Zone.GRAVE), ("제외", Zone.REMOVED),
        ("엑스트라 덱", Zone.EXTRA), ("남은 덱", Zone.DECK),
    )
    for label, zone in rows:
        cards = [c for c in state.player(0).zone(zone) if c]
        if zone is Zone.DECK:
            lines.append(f"  {label}: {len(cards)}장")
            continue
        def _label(card) -> str:
            found = repository.get(card.card_id) if repository else None
            return (f"{found.display_name()} [{card.card_id}]" if found
                    else f"[{card.card_id}]")

        names = ", ".join(_label(c) for c in cards) or "없음"
        lines.append(f"  {label}: {len(cards)}장 — {names}")
    lines.append("")
    lines.append("  🔴 집의 강도 평가는 미구현입니다 (Phase 6-V). 위에 적은"
                 " 것은 검증된 현재 자원뿐이고, 방해 수단의 수를 카드"
                 " 텍스트만 보고 세지 않았습니다.")
    return "\n".join(lines)
