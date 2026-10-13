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
            lines.append(f"         역할: {slot.role.describe_ko()}")
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
