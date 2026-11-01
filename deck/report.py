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
            #: 🔴 **네 가지를 가른다** (Phase 6-AD 후속2). "효과 … " 한 줄만
            #: 적으면 해결 + 조작 수행 · 해결 + 조작 없음 · 미지원 · 잘못된
            #: 선택이 같은 모양으로 보인다.
            outcome = (
                "조작 수행"
                if step.effect_ref in step.effect_events
                else "🔴 해결됐지만 조작 없음 (확인된 사유 — 아래 `이유`)"
                if step.resolved_without_operation
                else "🔴 해결되지 않음 (아래 `결과` 코드와 `이유`)"
            )
            lines.append(f"      효과 {step.effect_ref} · {outcome}"
                         + (f" · 대상 {len(step.targets)}개"
                            if step.targets else ""))
        #: 🔴 **소재를 이름으로 적는다** (Phase 6-AC). 대상과 **다른 줄**이다 —
        #: 링크 소재는 대상으로 지정되지 않으므로 "대상 2개" 로 적으면 거짓이다.
        #: 🔴 **해결 시점의 선택을 따로 적는다** (Phase 6-AD).
        #:
        #: 위의 "대상 N개" 는 **발동을 선언할 때** 정해져 있던 것이고, 규칙상
        #: 해결 중에 고르는 효과는 그 칸이 **정당하게 비어 있다.** 두 줄을
        #: 합치면 "대상을 지정하지 않는 효과" 가 대상을 지정한 것으로 읽히고,
        #: 저 칸을 채우려고 선택을 발동 시점으로 당기면 규칙이 틀어진다.
        if step.resolution_choice_text:
            lines.append(f"      해결 중 선택 {len(step.resolution_choices)}장:")
            lines.extend(
                f"         - {item}" for item in step.resolution_choice_text
            )
        if step.materials:
            lines.append(f"      소재 {len(step.materials)}장: "
                         f"{' · '.join(step.materials)}")
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
    #: 🔴 **"해결된 효과 수" 와 "실제 조작이 수행된 수" 를 섞지 않는다**
    #: (Phase 6-AD 후속2). 효과가 **해결됐지만 일을 하지 않는** 경우가 규칙에
    #: 있고 (``s.spop1`` 의 조기 return), 그것을 앞 수에 더하면 "소환이
    #: N번 일어났다" 로 읽힌다. 두 줄로 적는다.
    lines.append(f"  그중 **효과의 조작이 실제로 수행된 걸음**"
                 f" {run.effects_resolved}걸음"
                 f" (기록에 EffectEvent 가 남은 걸음)")
    if run.effects_resolved_without_operation:
        lines.append(
            f"  그리고 **해결됐지만 조작이 없었던 걸음**"
            f" {run.effects_resolved_without_operation}걸음"
            f" — 🔴 미지원도 오류도 아닙니다 (규칙대로 해결되고 할 일이"
            f" 없었습니다). 사유는 각 걸음의 `이유` 줄에 있습니다"
        )
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
    #: 🔴 **엑스트라 몬스터 존을 적는다** (Phase 6-AC). 그 전까지 이 표에
    #: 그 자리가 없었고, 링크 소환이 실행되기 전에는 언제나 비어 있었으므로
    #: 빠진 것이 보이지 않았다. 6-AC 가 링크 소환을 실행하게 만든 뒤
    #: 실측하니 **갈라테아가 보고에서 사라졌다** — 몬스터 존 0장으로 적히고
    #: 엑스트라 덱만 한 장 줄어 있어서, 읽는 쪽이 카드가 어디로 갔는지 알
    #: 수 없었다. 판에 있는 자리를 적지 않는 것은 보고의 결함이다.
    rows = (
        ("몬스터 존", Zone.MZONE),
        ("엑스트라 몬스터 존", Zone.EMZONE),
        ("마법·함정 존", Zone.SZONE),
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


# ===========================================================================
# Phase 6-AE — **기본 응답용 짧은 요약**
# ===========================================================================
#: 요약에 적는 걸음 수의 상한. 넘으면 **뒤를 버리지 않고** 몇 걸음을 요약에서
#: 뺐는지 적고, 전부는 상세 기록에 있다고 가리킨다.
BRIEF_STEP_LIMIT = 12

#: 요약에 적는 미지원 사유의 상한. 같은 이유다.
BRIEF_UNSUPPORTED_LIMIT = 6

#: 한 구역에 이름을 몇 장까지 적는가. 넘으면 수를 적고 이름은 상세로 보낸다.
BRIEF_ZONE_NAME_LIMIT = 8

#: 걸음의 결과를 요약 한 줄에 적을 때의 낱말. ``ExecutedStep.outcome`` 의
#: 다섯 낱말을 그대로 받는다 — 요약이 **새 분류를 만들지 않는다.**
_OUTCOME_KO = {
    "operated": "조작 수행",
    "idle": "🔴 해결됐지만 조작 없음",
    "unknown": "🔴 해결 미확정 (모름)",
    "refused": "🔴 거절",
    "flow": "",
}

#: 행동 종류를 사람이 읽는 낱말로. 🔴 **없는 종류는 그대로 적는다** —
#: 모르는 낱말을 비슷한 것으로 바꾸면 읽는 쪽이 다른 행동으로 읽는다.
_KIND_KO = {
    "normal_summon": "일반 소환",
    "special_summon": "특수 소환",
    "link_summon": "링크 소환",
    "activate_effect": "효과 발동",
    "activate_card": "카드 발동",
    "set_spell_trap": "마법·함정 세트",
    "pass": "우선권 넘김",
    "end_phase": "턴 종료",
}

#: 멈춘 종류를 **뜻으로** 적는다. 🔴 원문만 보여 주지 않는다 (6-AE §2-④).
#: ``not_chosen`` 은 경로 완료 여부에 따라 달라지므로 여기 두지 않는다 —
#: :func:`_stopped_lines` 가 그 둘을 가른다.
_STOPPED_KO = {
    "duel_over": "듀얼이 끝났습니다.",
    "no_candidates": "그 자리에 허가된 후보가 하나도 없었습니다.",
    "unsupported": "🔴 남은 후보가 흐름뿐인데 **그 자리에 엔진이 지원하지"
                   " 않아 오르지 못한 후보**가 있었습니다 — 정상 전개"
                   " 종료가 아닙니다.",
    "flow_only": "판을 바꿀 후보가 더 없었고 남은 후보는 흐름뿐이었습니다"
                 " — 이 저장소의 **현재 지원 범위와 선택 방식에서** 더"
                 " 고를 것이 없다는 뜻입니다.",
    "rejected": "🔴 행동이 거절되었습니다.",
    "limit": "이 단계가 선언한 걸음 상한에 닿았습니다.",
    "not_run": "🔴 입력 검증을 통과하지 못해 실행하지 않았습니다.",
}


def _kind_ko(kind: str) -> str:
    return _KIND_KO.get(kind, kind)


def _brief_step_line(step, repository=None) -> str:
    """
    걸음 하나를 **한 줄로**.

    🔴 **핵심을 지우지 않는다** (6-AE §2-②) — 어느 효과인가
    (:attr:`~deck.opening.ExecutedStep.effect_ref`) · 링크 소재 · 해결 중에
    **무엇을 골랐는가**를 남긴다. 고른 카드의 이름은 저장소가 있을 때만
    적고, 없으면 ID 로 적는다 (없는 이름을 만들지 않는다).
    """
    mark = "✔" if step.accepted and step.resolved else (
        "~" if step.accepted else "✗")
    where = f" — {step.card_name}" if step.card_name and step.card_id else ""
    ref = f" `{step.effect_ref}`" if step.effect_ref else ""
    bits = [f"  {mark} {step.order}. {_kind_ko(step.kind)}{where}{ref}"]
    outcome = _OUTCOME_KO.get(step.outcome, step.outcome)
    if outcome:
        bits.append(f" · {outcome}")
    if step.materials:
        bits.append(f" · 소재: {' · '.join(step.materials)}")
    if step.resolution_choices:
        picked = []
        for card_id in step.resolution_choices:
            found = repository.get(card_id) if repository else None
            picked.append(found.display_name() if found else f"[{card_id}]")
        bits.append(f" · 해결 중 선택: {' · '.join(picked)}")
    return "".join(bits)


def _brief_steps(run, repository=None) -> "list[str]":
    """
    **실제로 실행한 주요 행동.** 🔴 흐름 행동은 묶고, 나머지는 남긴다.

    묶는 것은 ``pass`` · ``end_phase`` 처럼 판을 바꾸지 않는 절차뿐이고,
    그것도 **연속한 것만** 묶는다 — 묶어 버리면 "몇 걸음이었나" 가 사실과
    달라지므로 수를 적는다.

    🔴 **실패하거나 정상 불발한 걸음은 묶지 않고 이유를 함께 적는다**
    (6-AE §2-②).
    """
    lines: list[str] = []
    flow_run: list = []

    def flush_flow() -> None:
        if not flow_run:
            return
        kinds = " · ".join(sorted({_kind_ko(s.kind) for s in flow_run}))
        orders = f"{flow_run[0].order}" if len(flow_run) == 1 else \
            f"{flow_run[0].order}~{flow_run[-1].order}"
        lines.append(f"  — {orders}. 흐름 {len(flow_run)}걸음 ({kinds})")
        flow_run.clear()

    for step in run.steps:
        #: 흐름이면서 **아무 문제가 없는** 걸음만 묶는다.
        if (step.kind in {"pass", "end_phase"} and step.accepted
                and step.resolved and not step.note):
            flow_run.append(step)
            continue
        flush_flow()
        lines.append(_brief_step_line(step, repository))
        #: 🔴 **이유를 생략하지 않는다** — 수행되지 않은 걸음만 적는다
        #: (성공한 걸음의 이유까지 적으면 요약이 상세가 된다).
        if step.outcome in {"idle", "unknown", "refused"} or not step.accepted:
            lines.append(f"      이유: {step.reason}")
        if step.note:
            lines.append(f"      🔴 {step.note}")
    flush_flow()

    if len(lines) > BRIEF_STEP_LIMIT:
        kept = lines[:BRIEF_STEP_LIMIT]
        kept.append(f"  … 걸음 요약 {len(lines) - BRIEF_STEP_LIMIT}줄은"
                    f" **상세 기록**에 있습니다 (버리지 않았습니다).")
        return kept
    return lines


def _brief_board(setup, repository=None) -> "list[str]":
    """
    **최종 상태.** 🔴 필드의 카드 이름은 요약에서 보이게 한다 (6-AE §2-③).

    :func:`render_opening_board` 와 **같은 자리를 읽는다** — 이름이 다른
    표를 만들지 않는다. 다른 것은 긴 구역(패 · 묘지)의 이름을 상한까지만
    적고 수를 함께 적는다는 점뿐이다.
    """
    from engine.vocabulary import Zone

    if setup.duel is None:
        return ["  상태가 없습니다."]
    state = setup.duel.state

    def _names(cards) -> str:
        def label(card) -> str:
            found = repository.get(card.card_id) if repository else None
            return (f"{found.display_name()}" if found
                    else f"[{card.card_id}]")

        if not cards:
            return "없음"
        if len(cards) > BRIEF_ZONE_NAME_LIMIT:
            head = ", ".join(label(c) for c in cards[:BRIEF_ZONE_NAME_LIMIT])
            return f"{head} … (이름 전체는 상세 기록)"
        return ", ".join(label(c) for c in cards)

    lines: list[str] = []
    #: 🔴 **몬스터 존과 엑스트라 몬스터 존을 가른다** (Phase 6-AC 의 실측 —
    #: 합치면 링크 몬스터가 보고에서 사라진다).
    for label_ko, zone in (("몬스터 존", Zone.MZONE),
                           ("엑스트라 몬스터 존", Zone.EMZONE),
                           ("마법·함정 존", Zone.SZONE)):
        cards = [c for c in state.player(0).zone(zone) if c]
        lines.append(f"  {label_ko}: {_names(cards)}")
    for label_ko, zone in (("패", Zone.HAND), ("묘지", Zone.GRAVE)):
        cards = [c for c in state.player(0).zone(zone) if c]
        lines.append(f"  {label_ko} {len(cards)}장: {_names(cards)}")
    #: 🔴 **제외는 비었을 때도 적는다** — 수를 적지 않으면 읽는 쪽이 "거기에
    #: 무엇이 있는가" 를 알 수 없다. 다만 이름까지 필요한 자리가 아니므로
    #: 덱 · 엑스트라와 한 줄로 묶어 **수만** 적는다 (이름은 상세 기록).
    removed = [c for c in state.player(0).zone(Zone.REMOVED) if c]
    deck = [c for c in state.player(0).zone(Zone.DECK) if c]
    extra = [c for c in state.player(0).zone(Zone.EXTRA) if c]
    lines.append(f"  제외 {len(removed)}장 · 남은 덱 {len(deck)}장"
                 f" · 엑스트라 덱 {len(extra)}장")
    if removed:
        lines.append(f"  제외: {_names(removed)}")
    return lines


def _stopped_lines(run, progress=None) -> "list[str]":
    """
    **멈춘 이유를 뜻으로 적는다** (6-AE §2-④).

    🔴 ``not_chosen`` 하나를 두 가지로 가른다 — 경로를 끝까지 실행한 뒤
    "그 경로에 다음 행동이 적혀 있지 않다" 인 경우와, 경로가 중간에 멈춘
    경우다. 앞의 것을 **경로 미완료처럼** 적으면 성공한 실행이 실패로
    읽히고, 뒤의 것을 **완료처럼** 적으면 거짓이 된다.
    """
    if not run.stopped_kind:
        return []
    left = (f" (남은 후보: {' · '.join(_kind_ko(k) for k in run.stopped_candidates)})"
            if run.stopped_candidates else "")
    if run.stopped_kind == "not_chosen":
        if progress is not None and progress.completed:
            return [
                f"  ✅ **지정 경로를 완료했습니다.** 이후 행동은 이 검증"
                f" 경로에 지정되지 않았습니다{left}.",
                "  🔴 이것은 **이 경로를 끝까지 실행했다**는 뜻이고, 이 패로"
                " 가능한 전개를 다 보았다는 뜻이 아닙니다.",
            ]
        if progress is not None:
            return [
                f"  🔴 **경로가 {progress.done}/{len(progress.line.steps)}"
                f"단계에서 멈췄습니다** — 검증용 선택 방식이 다음 단계의"
                f" 행동을 고르지 못했습니다{left}.",
            ]
        return [
            f"  🔴 검증용 선택 방식이 고를 행동을 찾지 못했습니다{left}."
        ]
    said = _STOPPED_KO.get(run.stopped_kind)
    if said is None:
        #: 🔴 모르는 낱말을 뜻으로 바꾸지 않는다 — 원문을 그대로 적는다.
        return [f"  멈춘 종류: `{run.stopped_kind}` · {run.stopped_reason}"]
    return [f"  {said}{left}"]


def _support_lines(run) -> "list[str]":
    """
    **지원 범위.** 🔴 "경로 완료" 와 "전개 전체를 검증했다" 를 가른다.

    미지원 사유는 :attr:`~deck.opening.OpeningRun.unsupported` 를 그대로
    쓴다 — 그 목록은 ``note_unsupported`` 가 **자리 메모를 뺀 열쇠로** 이미
    한 번씩만 모아 둔 것이다 (``WithheldAction.scope`` 의 설명). 그래서 여기서
    문장을 다시 묶거나 쪼개지 않는다: 종류 · 빠진 규칙의 이름 · 사유가
    다르면 다른 줄로 남는다.

    🔴 **세 사실을 함께 적는다** (6-AE §2-④).

    1. 몇 건을 지나왔는가, 그리고 **어디서** 만났는가 (걸음이 끝난 자리와
       자동 처리 도중을 가른다 — 같은 사유라도 시점이 다르다).
    2. 그것이 **규칙 거절이 아니다** — 이 저장소에 그 규칙이 없는 것이다.
    3. 그래서 위의 걸음 수를 **"이 패의 전개를 다 했다"** 로 읽을 수 없다.

    🔴 **"더 고를 행동이 없다" 와 "끝까지 검증했다" 는 다른 질문이다**
    (보완8 세 항목 ①). 멈춘 자리가 깨끗해도 도중에 미지원을 지나왔으면
    전체를 검증한 것이 아니므로, 그 경우를 한 줄로 더 적는다.
    """
    if run.fully_supported:
        return ["  ✅ 이 실행 중에 **미지원으로 보류된 후보는 없었습니다.**"]

    at_place = sum(1 for s in run.steps if s.unsupported)
    during = sum(1 for s in run.steps if s.unsupported_during)
    where = []
    if at_place:
        where.append(f"걸음이 끝난 자리 {at_place}곳")
    if during:
        where.append(f"자동 처리 도중 {during}걸음")
    lines = [
        f"  🔴 **엔진이 지원하지 않아 후보가 되지 못한 것이"
        f" {len(run.unsupported)}건** 있었습니다"
        + (f" ({' · '.join(where)})" if where else "")
        + " — 규칙이 막은 것이 아니라 **이 저장소에 그 규칙이 없다**는"
        " 뜻입니다. 그래서 위의 걸음 수를 **이 패의 전개를 다 했다**로"
        " 읽을 수 없습니다."
    ]
    #: 🔴 멈춘 자리는 깨끗했는데 도중에 지나온 것이 있다 — 그 구분을 적는다.
    if run.stopped_kind == "flow_only":
        lines.append(
            "  🔴 멈춘 자리에는 미지원이 없었지만 **전개 도중에 지나온"
            " 미지원이 있습니다** — 그래서 **더 고를 행동이 없다**는 것과"
            " **전개 전체를 지원 범위 안에서 검증했다**는 것은 다릅니다."
        )
    lines.append(f"  미지원 사유 (같은 사유는 한 번씩만 적었습니다):")
    shown = run.unsupported[:BRIEF_UNSUPPORTED_LIMIT]
    lines.extend(f"    - {item}" for item in shown)
    rest = len(run.unsupported) - len(shown)
    if rest > 0:
        lines.append(f"    … 남은 {rest}건은 **상세 기록**에 있습니다"
                     f" (버리지 않았습니다).")
    return lines


def render_opening_brief(setup, run, repository=None, *,
                         line=None, progress=None) -> str:
    """
    **기본 응답용 짧은 요약** (Phase 6-AE).

    🔴 **판정하지 않는다.** 이미 기록된 :class:`~deck.opening.OpeningRun` ·
    :class:`~deck.opening.OpeningSetup` 만 읽고, 엔진을 다시 돌리지도
    상태를 건드리지도 않는다. ``line`` · ``progress`` 는 부르는 쪽이 이미
    만든 값을 넘기는 자리다 — 여기서 다시 계산하면 두 계층의 답이 달라질 수
    있다.

    🔴 **짧게 적는 것과 숨기는 것은 다르다.** 상한에 걸려 뺀 줄은 **몇
    줄인지 적고** 상세 기록을 가리킨다 (:func:`_brief_steps` ·
    :func:`_support_lines`). 그리고 "검증 불가" 를 "검증 통과" 로 바꾸지
    않는다 — 수와 규칙 이름을 그대로 적고 자세한 설명만 상세로 보낸다.

    전체 기록은 :func:`render_opening_setup` · :func:`render_opening_run` ·
    :func:`render_opening_board` 가 그대로 들고 있다 (CLI 와 첨부가 그것을
    쓴다). 이 함수는 **그 기록을 대신하지 않는다.**
    """
    lines = ["", "전개 실행 요약", _RULE]
    if not setup.can_run:
        lines.append("  🔴 **실행하지 않았습니다** — 입력 검증을 통과하지"
                     " 못했습니다.")
        for blocker in setup.blockers:
            lines.append(f"    - {blocker}")
        for finding in setup.violations:
            lines.append(f"    - 🔴 {finding.rule}: {finding.detail}")
        lines.append("  🔴 실행하지 않았으므로 **걸음 수도 성공 표시도"
                     " 없습니다.** 전체 검증 결과는 상세 기록에 있습니다.")
        return "\n".join(lines)

    #: ① 실행 결과 요약
    if line is not None and progress is not None:
        lines.append(f"  검증용 전개 경로 `{line.name}` — {progress.describe_ko()}")
        lines.append(f"  경로: {line.title_ko}")
    elif line is not None:
        lines.append(f"  검증용 전개 경로 `{line.name}` 으로 실행했습니다.")
    else:
        lines.append("  검증용 기준점 `first_meaningful` 으로 실행했습니다"
                     " (사람이 적어 둔 경로를 쓰지 않았습니다) —"
                     " 판을 바꾸는 후보의 첫 번째를 집습니다.")
    if line is not None and line.resolution_preferences:
        #: 🔴 **해결 시점의 선택을 따로 적는다** (6-AD §6). 발동 기록의
        #: 대상이 비어 있는 것이 **정상**이므로, 그 칸만 보고 "아무것도
        #: 고르지 않았다" 로 읽히지 않게 한다.
        wanted = " · ".join(
            f"`{card_id}`" for card_id in line.resolution_preferences
        )
        lines.append(f"  경로가 해결 중에 고르려는 카드: {wanted}"
                     f" (엔진이 낸 허용 후보 밖에서 끌어오지 않습니다)")
    #: 🔴 **이 설명은 한 번만 적는다** (6-AE §2-①). 그래서 한 줄에
    #: 두 사실을 함께 적는다 — **무엇이 아닌가**(최선 전개 · 자율 탐색 ·
    #: 범용 AI) 와 **해결 중의 선택을 어떻게 했는가**(`first-permitted`).
    lines.append("  🔴 사람이 적어 둔 경로를 따라갔을 뿐이고 **최선 전개"
                 " 탐색도, 자율 탐색도, 범용 AI 도 아닙니다** — **최선의"
                 " 전개가 아닙니다.** 해결 중의 카드 선택은"
                 " `first-permitted` (허용된 후보의 앞쪽) 입니다.")
    lines.append(f"  실행 {run.executed}걸음 · 상태 변경"
                 f" {run.state_changes}걸음 · **효과의 조작 수행"
                 f" {run.effects_resolved}걸음**")
    if run.effects_resolved_without_operation:
        lines.append(
            f"  🔴 **해결됐지만 조작이 없었던 걸음"
            f" {run.effects_resolved_without_operation}걸음** —"
            f" 미지원도 오류도 아닙니다 (규칙대로 해결되고 할 일이"
            f" 없었습니다). 사유는 아래 걸음 줄에 있습니다."
        )

    #: ② 실제 실행한 주요 행동
    lines.append("")
    lines.append("  실행한 행동")
    lines.extend(_brief_steps(run, repository)
                 or ["  실행한 걸음이 없습니다."])

    #: ③ 최종 상태
    lines.append("")
    lines.append("  최종 상태 (실제 GameState)")
    lines.extend(_brief_board(setup, repository))

    #: ④ 멈춘 이유와 지원 범위
    stopped = _stopped_lines(run, progress)
    if stopped:
        lines.append("")
        lines.append("  멈춘 이유")
        lines.extend(stopped)
    lines.append("")
    lines.append("  지원 범위")
    lines.extend(_support_lines(run))

    #: ⑤ 검증의 한계 — 🔴 **짧게 적지만 "검증 불가" 를 지우지 않는다.**
    if setup.unverifiable:
        lines.append("")
        lines.append(f"  ⚠️ 검증 불가 {len(setup.unverifiable)}건"
                     " — **문제 없음이 아닙니다**: "
                     + " · ".join(f.rule for f in setup.unverifiable))
    return "\n".join(lines)
