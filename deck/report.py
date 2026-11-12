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
#: 추천 절의 얇은 구분선 (Phase 6-AK).
_RULE_THIN = "  " + "·" * 60
#: 🔴 **이번 평가의 범위** — 요약과 상세에 **둘 다** 적는다. 길이 제한
#: 때문에 이 줄이 잘리면 "최강 전개를 골랐다" 로 읽힌다.
_RANKING_SCOPE = (
    "🔴 **탐색에서 발견하고 재생 검증한 후보 사이의 비교**입니다 —"
    " 자원 보존 중심의 제한적 휴리스틱이고, **실전 최강·승률 평가가"
    " 아닙니다**. 상대의 방해 대응력도 계산하지 않았습니다."
)
#: 🔴 **언제의 자원인가** — 처음 도달한 시점이다.
_RANKING_WHEN = (
    "🔴 **목표 카드에 처음 도달한 시점**의 후보 비교입니다 — 탐색이"
    " 목표에 닿은 분기를 더 펼치지 않으므로, 전개를 끝까지 수행한"
    " 최종 집의 평가가 아닙니다."
)


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

    #: 🔴 **효과가 걸어 둔 특수 소환 제한을 적는다** (Phase 6-AO).
    #:
    #: 존만 적으면 읽는 쪽이 **뒤에 무엇을 할 수 있는지**를 알 수 없다 —
    #: 「어둠 속성밖에 특수 소환할 수 없다」 가 걸린 판과 걸리지 않은 판은
    #: 같은 존 목록을 갖지만 다음 걸음이 다르다. 엑스트라 몬스터 존이
    #: 6-AC 에서 추가된 것과 **같은 이유**다: 판에 있는 것을 적지 않는 것은
    #: 보고의 결함이다.
    #:
    #: 🔴 **안내문이 아니라 판정에 쓰이는 그 기록이다** —
    #: :mod:`engine.state.summon_limit` 의 표를 그대로 읽는다.
    limits = getattr(state, "summon_limits", None)
    active = (
        limits.entries(state.turn.turn_number) if limits is not None else ()
    )
    if active:
        lines.append("")
        lines.append("  🔴 이 턴에 걸린 특수 소환 제한 (효과가 건 것):")
        for limit in active:
            who = "자신" if limit.player == 0 else "상대"
            found = (
                repository.get(limit.source_card_id) if repository else None
            )
            source = (
                f"{found.display_name()} [{limit.source_card_id}]"
                if found
                else f"[{limit.source_card_id}]"
            )
            lines.append(
                f"    - {who}: {limit.attribute} 속성 몬스터밖에 특수 "
                f"소환할 수 없습니다 — {source} 의 "
                f"e[{limit.ordinal}] 가 걸었습니다 (턴 종료까지)"
            )

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


#: 요약 한 줄에 적는 전개 걸음의 상한. 넘으면 **버리지 않고** 몇 걸음을
#: 뺐는지 적는다 (6-AE 와 같은 규율).
_HEADLINE_STEPS = 8

#: 효과 번호를 ①②③ 으로. 없는 번호는 그대로 적는다 (지어내지 않는다).
_ORDINALS = "①②③④⑤⑥⑦⑧⑨"


def _attribute_ko(name: str) -> str:
    """
    ``"DARK"`` → ``"어둠"``. 🔴 **모르는 이름은 그대로 둔다** — 없는 번역을
    지어내지 않는다. 표는 ``core.constants`` 의 것을 그대로 쓴다 (사본을
    만들면 둘이 갈라진다).
    """
    from core.constants import ATTRIBUTE_KO, ATTRIBUTE_NAMES

    for value, english in ATTRIBUTE_NAMES.items():
        if english == name:
            return ATTRIBUTE_KO.get(value, name)
    return name


def _short_name(name: str) -> str:
    """
    **표시용으로만** 짧게 — 「잭나이츠 오르페골 기르수」 → 「기르수」.

    🔴 **이름을 바꾸는 것이 아니다.** 한 줄 요약이 읽히게 하려고 마지막
    낱말만 쓰고, 전체 이름은 상세 기록과 전개 기록에 그대로 남는다
    (:func:`render_opening_run` · ``deck.replay_export``). 낱말이 하나뿐이면
    그대로 둔다.
    """
    parts = [part for part in str(name).split() if part]
    if len(parts) >= 2 and len(parts[-1]) >= 2:
        return parts[-1]
    return str(name)


def _headline_flow(run, limit: int = _HEADLINE_STEPS) -> str:
    """
    **핵심 전개 한 줄** — 실행 기록에서 뽑는다 (Phase 6-AR).

    🔴 **사람이 적어 둔 경로의 제목을 베끼지 않는다.** 경로가 무엇을
    하려 했는가가 아니라 **무엇이 실제로 수락되었는가**를 적는다 — 둘은
    경로가 중간에 막히면 갈라진다.

    🔴 **수락된 걸음만** 넣는다. 거절된 걸음은 이 줄에 오지 않고, 그
    사실은 결과 줄과 상세 기록이 말한다.
    """
    bits: list[str] = []
    for step in run.steps:
        if not step.accepted:
            continue
        name = _short_name(step.card_name) if step.card_name != "—" else ""
        kind = step.kind
        if kind == "normal_summon":
            bits.append(f"{name} 일반소환")
        elif kind == "link_summon":
            bits.append(f"{name} 링크")
        elif kind == "special_summon":
            bits.append(f"{name} 특수소환")
        elif kind == "activate_effect":
            mark = ""
            ref = step.effect_ref or ""
            if ref.endswith("]") and ":e[" in ref:
                try:
                    index = int(ref.rsplit("[", 1)[1][:-1])
                except ValueError:
                    index = -1
                if 0 <= index < len(_ORDINALS):
                    mark = _ORDINALS[index]
            bits.append(f"{name}{mark or ' 효과'}")
        elif kind in ("pass", "end_phase"):
            continue
        else:
            bits.append(f"{name} {kind}".strip())
    if not bits:
        return ""
    hidden = len(bits) - limit
    if hidden > 0:
        bits = bits[:limit] + [f"… {hidden}걸음 더"]
    return " → ".join(bits)


def _headline_field(setup, repository=None) -> "list[str]":
    """
    **최종 필드와 주요 잔여 자원** 두 줄. 🔴 판에서 읽는다 — 경로가 바라던
    결과가 아니라 ``GameState`` 에 있는 것이다.
    """
    from engine.vocabulary import Zone

    if setup.duel is None:
        return ["  최종 필드: 상태가 없습니다."]
    state = setup.duel.state

    def _names(zone) -> "list[str]":
        out = []
        for card in state.player(0).zone(zone):
            if not card:
                continue
            found = repository.get(card.card_id) if repository else None
            out.append(_short_name(found.display_name()) if found
                       else f"[{card.card_id}]")
        return out

    def _count(zone) -> int:
        return len([card for card in state.player(0).zone(zone) if card])

    field_bits = []
    for label, zone in (("EM존", Zone.EMZONE), ("몬스터존", Zone.MZONE),
                        ("마법함정존", Zone.SZONE)):
        names = _names(zone)
        if names:
            field_bits.append(f"{label} {' · '.join(names)}")
    lines = [
        "  최종 필드: " + (" / ".join(field_bits) or "비어 있습니다")
    ]
    lines.append(
        f"  잔여: 패 {_count(Zone.HAND)} · 묘지 {_count(Zone.GRAVE)}"
        f" · 제외 {_count(Zone.REMOVED)} · 덱 {_count(Zone.DECK)}"
        f" · 엑스트라 {_count(Zone.EXTRA)}"
    )

    #: 🔴 **뒤에 할 수 있는 일을 바꾸는 기록은 요약에 남긴다** (6-AO).
    limits = getattr(state, "summon_limits", None)
    if limits is not None:
        active = list(limits.active(state.turn.turn_number, 0))
        if active:
            sources = []
            for limit in active:
                found = (repository.get(limit.source_card_id)
                         if repository else None)
                sources.append(_short_name(found.display_name()) if found
                               else str(limit.source_card_id))
            attributes = " · ".join(
                sorted({_attribute_ko(limit.attribute) for limit in active})
            )
            lines.append(
                f"  특수 소환 제한: {attributes} 속성만"
                f" ({len(active)}건 — {' · '.join(sources)})"
            )
    return lines


def render_opening_headline(setup, run, repository=None, *,
                            line=None, progress=None) -> str:
    """
    **기본 응답용 한눈 요약** (Phase 6-AR).

    🔴 **판정하지 않는다** — 이미 기록된 ``setup`` · ``run`` 만 읽는다
    (:func:`render_opening_brief` 와 같은 규율). 엔진을 다시 돌리지도
    상태를 건드리지도 않는다.

    🔴 **짧게 적는 것과 숨기는 것은 다르다.** 여기서 줄인 것은 전부 상세
    기록에 그대로 있고 (:func:`render_opening_brief` 가 첨부의 첫 절이
    되었다), 이 함수는 **지우면 뜻이 달라지는 네 가지**를 반드시 남긴다.

    1. 실행 방식 — 고정 경로인가 자율 실행인가
    2. 결과 — 완료 · 중단 · 실행 안 함
    3. 실제로 수락된 전개와 최종 판
    4. 🔴 "완료" 가 **최선 전개도, 이 패로 가능한 전개 전부도 아니라는 것**
       과 미지원 건수

    🔴 **전개 보기 링크는 여기서 만들지 않는다.** 외부 재생 링크가 있는지는
    표시 계층이 아는 사실이고, 보고 계층이 "있다" 고 적으면 없는 링크를
    약속하게 된다.
    """
    if not setup.can_run:
        lines = ["❌ **실행하지 않았습니다** — 입력 검증을 통과하지 못했습니다."]
        for blocker in setup.blockers:
            lines.append(f"  - {blocker}")
        for finding in setup.violations:
            lines.append(f"  - 🔴 {finding.rule}: {finding.detail}")
        lines.append("  🔴 실행하지 않았으므로 걸음 수도 성공 표시도 없습니다.")
        return "\n".join(lines)

    if line is not None:
        total = len(line.steps)
        if progress is not None and progress.completed:
            head = (f"✅ **전개 완료** · 고정 경로 `{line.name}`"
                    f" ({progress.done}/{total}단계)")
        elif progress is not None:
            head = (f"⏹ **중단** · 고정 경로 `{line.name}`"
                    f" ({progress.done}/{total}단계)")
        else:
            head = f"▶ 고정 경로 `{line.name}` 으로 실행했습니다."
    elif run.stopped_kind == "rejected":
        #: 🔴 자율 실행이 **거절로 멈춘** 자리. 완료도 중단 경로도 아니다.
        head = ("⏹ **중단** · 자율 실행 (기준점 `first_meaningful`) —"
                " 행동이 거절되어 멈췄습니다.")
    else:
        head = ("▶ **자율 실행** (기준점 `first_meaningful`) —"
                " 사람이 적어 둔 경로를 쓰지 않았습니다.")

    lines = [head]
    flow = _headline_flow(run)
    if flow:
        lines.append(f"  전개: {flow}")
    else:
        lines.append("  전개: 수락된 걸음이 없습니다.")
    lines.extend(_headline_field(setup, repository))

    #: 🔴 **막힌 자리는 요약에 남긴다** — 중단을 완료처럼 읽히게 두지 않는다.
    if progress is not None and not progress.completed:
        if progress.blocked_at is not None:
            lines.append(f"  🔴 막힌 단계: {progress.blocked_at.describe_ko()}")
        if progress.reason:
            lines.append(f"  🔴 사유: {progress.reason}")
    elif run.stopped_kind == "rejected" and run.stopped_reason:
        lines.append(f"  🔴 중단: {run.stopped_reason}")

    #: 🔴 **이 두 줄은 줄이지 않는다** (6-AE §2-④ 가 세운 계약).
    if run.unsupported:
        lines.append(
            f"  🔴 미지원 {len(run.unsupported)}건 — 규칙이 막은 것이 아니라"
            f" **이 저장소에 그 규칙이 없다**는 뜻입니다 (사유는 상세 기록)."
        )
    #: 🔴 **실행 방식과 결과마다 다른 문장이다** (Phase 6-AS).
    #:
    #: 전에는 ``line`` 이 있으면 ``progress.completed`` 와 무관하게 "경로를
    #: 끝까지 밟았다" 를 붙였다 — **중단된 결과에 완료를 암시하는 문장이
    #: 붙었다.** 세 갈래를 실제 결과에서 가른다.
    if line is not None and progress is not None and not progress.completed:
        lines.append("  🔴 **경로를 끝까지 밟지 못했습니다** — 위 걸음까지가"
                     " 실행된 전부입니다.")
    elif line is not None:
        lines.append("  🔴 사람이 적어 둔 경로를 끝까지 밟았다는 뜻이고,"
                     " **최선 전개도 이 패로 가능한 전개 전부도"
                     " 아닙니다.**")
    else:
        lines.append("  🔴 기준점(`first_meaningful`)이 집은 수를 따라갔을"
                     " 뿐이고, **최선 전개도 이 패로 가능한 전개 전부도"
                     " 아닙니다.**")
    if setup.unverifiable:
        lines.append(f"  ⚠️ 검증 불가 {len(setup.unverifiable)}건"
                     " — **문제 없음이 아닙니다** (상세 기록에 목록).")
    return "\n".join(lines)


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
    #: 🔴 **무엇을 따라갔는지 사실대로 적는다** (6-BC 정정). 경로를 주지
    #: 않은 실행은 사람이 적어 둔 경로를 따라간 것이 **아니라**
    #: ``first_meaningful`` 기준점으로 고른 것이다 — 둘을 한 문장으로
    #: 뭉치면 "고정 경로를 쓰지 않았다" 는 설명과 같은 출력에서 부딪힌다.
    lines.append(
        ("  🔴 사람이 적어 둔 경로를 따라갔을 뿐이고" if line is not None
         else "  🔴 검증용 기준점 `first_meaningful` 이 고른 것이고")
        + " **최선 전개 탐색도, 자율 탐색도, 범용 AI 도 아닙니다** —"
        " **최선의 전개가 아닙니다.** 해결 중의 카드 선택은"
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


# ======================================================================
# 제한 탐색 (Phase 6-AH)
# ======================================================================
#: 요약에 적는 걸음·메모의 상한. 넘으면 **버리지 않고** 몇 줄을 뺐는지
#: 적고 전부는 상세 기록에 있다고 가리킨다 (6-AE 와 같은 규율).
_SEARCH_BRIEF_STEPS = 8
_SEARCH_BRIEF_NOTES = 3

#: 🔴 **이 설명은 요약에도 상세에도 들어간다.** 빼면 "엔진이 규칙을 다
#: 안다" 로 읽힌다.
_SEARCH_DISCLAIMER = (
    "🔴 **제한 탐색입니다** — 사람이 적어 둔 경로를 호출하지 않고 엔진이"
    " 허가한 후보와 해결 중 선택만 펼쳤습니다. **전체 규칙 지원을 뜻하지"
    " 않습니다**: **엔진이 허가했다는 것은 이 엔진 안에서의 판정**이고"
    " 공식 규칙 전체를 검증한 것이 아니며 (6-BC), 지원하지 않아 후보가"
    " 되지 못한 수는 아래 `지원 범위` 에 적혀 있습니다. 그리고"
    " **최선 전개도 승률 평가도 아닙니다** — 🔴 **실전 강도·승률 평가는"
    " 하지 않습니다** (6-BC 정정: 추천을 고르는 휴리스틱은 있고, 그"
    " 기준과 한계는 추천 절이 적습니다)."
)

#: 종료 사유를 **뜻으로** 적는다. 🔴 미발견을 "불가능" 으로 바꾸지 않는다.
_TERMINATION_KO = {
    "goal_reached": "목표 도달",
    "exhausted": "지정된 탐색 범위를 모두 펼쳤고 그 안에 목표가 없었습니다"
                 " (**이 패로 불가능하다는 뜻이 아닙니다**)",
    "budget_exceeded": "예산 초과로 멈췄습니다 (**못 찾았다는 뜻이"
                       " 아닙니다**)",
    "error": "🔴 실행 중 오류가 났습니다",
}


def _search_notes(label: str, notes, limit: int) -> "list[str]":
    """메모 묶음 한 구역. 상한에 걸리면 **몇 줄을 뺐는지** 적는다."""
    if not notes:
        return []
    lines = [f"  {label} {len(notes)}건"]
    for note in notes[:limit]:
        lines.append(f"    - {note}")
    hidden = len(notes) - limit
    if hidden > 0:
        lines.append(f"    - … {hidden}건은 요약에서 뺐습니다"
                     " (상세 기록에 전부 있습니다)")
    return lines


def render_bounded_search_brief(outcome, rerun=None) -> str:
    """
    **제한 탐색의 기본 응답용 요약** (Phase 6-AH).

    🔴 **판정하지 않는다.** 이미 끝난 탐색 결과만 읽고, 엔진을 다시 돌리지
    않는다 — ``outcome`` 과 ``rerun`` 은 부르는 쪽이 만든 값이다.

    🔴 **다섯 가지를 반드시 적는다** (§6): 실행 방식이 제한 탐색이라는 것 ·
    목표 도달 여부 · 행동 수와 탐색 노드 수 · 예산 종료 여부 · 전체 규칙
    지원을 뜻하지 않는다는 설명.

    ``agent`` 를 import 하지 않는다 — 결과의 **모양만** 읽는다
    (``deck`` → ``agent`` 방향의 import 는 이 저장소에 0곳이다).
    """
    lines = ["", "제한 전개 탐색 요약", _RULE]
    lines.append(f"  목표: {outcome.goal.describe_ko()}")
    mark = "✔ 도달" if outcome.reached else "✗ 미도달"
    lines.append(
        f"  {mark} — {_TERMINATION_KO.get(outcome.termination.value, outcome.termination.value)}"
    )
    lines.append(f"  행동 {outcome.action_count}걸음 · 해결 중 선택"
                 f" {outcome.choice_count}회 · 펼친 노드"
                 f" {outcome.nodes_expanded}개 · 최대 깊이"
                 f" {outcome.deepest} · {outcome.elapsed_seconds:.2f}초")
    #: 🔴 **선택을 생략했으면 목표 도달과 함께 적는다** (6-AH 보완 B).
    #: "경로를 찾았다" 는 맞고 "선택을 다 봤다" 는 틀린 경우가 있다.
    if outcome.skipped_choices:
        lines.append(f"  ⚠️ **해결 중 선택을 다 보지 않았습니다** —"
                     f" 확인하지 않은 대안이 남은 물음"
                     f" {outcome.choice_offers_truncated}곳 (아래 `지원 범위`"
                     f" 에 어느 자리인지 적혀 있습니다)")
    lines.append(f"  예산: {outcome.budget.describe_ko()}")
    if outcome.budget_hit and outcome.reached:
        #: 🔴 **목표는 찾았지만 일부 가지가 예산에 걸렸다** — 두 사실을
        #: 한 문장으로 적으면 "예산 때문에 실패했다" 로 읽힌다.
        lines.append("  ⚠️ 목표는 찾았지만 **일부 분기가 예산에"
                     " 걸렸습니다**: " + " · ".join(outcome.budget_hit)
                     + " (더 넓게 보면 다른 경로도 있을 수 있습니다)")
    elif outcome.budget_hit:
        lines.append("  🔴 **예산에 걸렸습니다**: "
                     + " · ".join(outcome.budget_hit)
                     + " — **못 찾았다는 뜻이 아닙니다.**")
    else:
        lines.append("  예산에 걸리지 않았습니다.")
    lines.append(f"  {_SEARCH_DISCLAIMER}")

    lines.append("")
    lines.append("  찾은 경로")
    if not outcome.path:
        lines.append("  경로가 없습니다.")
    for step in outcome.path[:_SEARCH_BRIEF_STEPS]:
        picked = " · ".join(
            f"[{card_id}]"
            for ask in step.choices
            for card_id in ask.chosen_card_ids
        )
        tail = f" (해결 중 선택 {picked})" if picked else ""
        lines.append(f"    {step.order}. {_kind_ko(step.kind)}{tail}")
    hidden = len(outcome.path) - _SEARCH_BRIEF_STEPS
    if hidden > 0:
        lines.append(f"    … {hidden}걸음은 요약에서 뺐습니다"
                     " (상세 기록에 전부 있습니다)")

    lines.append("")
    lines.append("  최종 자신 필드 (실제 GameState)")
    if not outcome.final_field:
        lines.append("    비어 있습니다.")
    for zone, card_id, face_up in outcome.final_field:
        face = "앞면" if face_up else "뒷면"
        lines.append(f"    {zone} [{card_id}] {face}")

    if rerun is not None:
        lines.append("")
        state = "✔ 성공" if rerun.ok else "🔴 실패"
        lines.append(f"  경로 재생 (새 초기 상태에서 다시 실행): {state}")
        lines.append(f"    {rerun.reason}")
        if not rerun.ok:
            lines.append("    🔴 **재생이 실패했으므로 성공 결과로 읽지"
                         " 마십시오.**")

    lines.append("")
    lines.append("  지원 범위")
    body = (
        _search_notes("범위 밖으로 둔 분기", outcome.out_of_scope,
                      _SEARCH_BRIEF_NOTES)
        + _search_notes("지원하지 않아 후보가 되지 못한 수",
                        outcome.unsupported, _SEARCH_BRIEF_NOTES)
        + _search_notes("상대 자리에서 무방해 정책이 넘긴 수",
                        outcome.opponent_declined, _SEARCH_BRIEF_NOTES)
        + _search_notes("상대 자리에 고를 것이 남아 멈춘 노드",
                        outcome.opponent_blocked, _SEARCH_BRIEF_NOTES)
        + _search_notes("🔴 오류", outcome.errors, _SEARCH_BRIEF_NOTES)
    )
    lines.extend(body or ["  적을 것이 없습니다 — 🔴 **그래도 전체 규칙"
                          " 지원을 뜻하지 않습니다.**"])
    return "\n".join(lines)


def render_bounded_search(outcome, rerun=None, setup=None) -> str:
    """
    **제한 탐색의 전체 기록** — 첨부와 CLI 가 보는 것 (Phase 6-AH).

    🔴 **한 줄도 줄이지 않는다.** 걸음마다 행동 열쇠와 그 걸음에서 한 해결
    중 선택 전부, 지나간 필수 걸음을 그대로 적는다 — 그것이 "같은 초기
    상태에서 재생할 수 있다" 의 근거다.

    ``setup`` 을 주면 **입력 조건**을 함께 적는다 (§5 가 요구하는 항목이다).
    🔴 **알 수 없는 것을 지우지 않는다** — 남은 덱의 순서를 모른다는 사실이
    그 목록에 그대로 있다.
    """
    lines = ["", "제한 전개 탐색 — 전체 기록", _RULE]
    lines.append(f"  목표: {outcome.goal.describe_ko()}")
    if setup is not None:
        lines.append("  입력 조건")
        lines.append("    시작 패: "
                     + " · ".join(f"[{card_id}]" for card_id in setup.hand))
        lines.append(f"    남은 메인 덱 {len(setup.deck_rest)}장 ·"
                     f" 엑스트라 {len(setup.extra)}장")
        for note in setup.unknowns:
            lines.append(f"    ⚠️ 알 수 없음: {note}")
    lines.append(f"  종료: {outcome.termination.value} — "
                 + _TERMINATION_KO.get(outcome.termination.value,
                                       outcome.termination.value))
    lines.append(f"  목표 판정: {outcome.goal_reason}")
    lines.append(f"  예산: {outcome.budget.describe_ko()}")
    lines.append("  예산에 걸린 칸: "
                 + (" · ".join(outcome.budget_hit) or "없음"))
    lines.append(f"  펼친 노드 {outcome.nodes_expanded} · 최대 깊이"
                 f" {outcome.deepest} · {outcome.elapsed_seconds:.3f}초")
    #: 🔴 **세 수치를 가른다** (6-AH 보완 B): 대기에 넣은 대안 각본 ·
    #: 실제로 돌린 대안 각본 · 확인하지 못한 대안이 남은 물음.
    lines.append(f"  해결 중 선택 — 대기에 넣은 대안 각본"
                 f" {outcome.choice_branches}개 · 실제로 돌린 각본"
                 f" {outcome.choice_plans}개 · 확인하지 못한 대안이 남은 물음"
                 f" {outcome.choice_offers_truncated}곳")
    #: 🔴 **중복 제거의 세 수치도 가른다** (6-AH 보완 A): 버린 노드 ·
    #: 더 얕게 닿아 다시 펼친 노드 · 대기 중에 밀려난 노드.
    lines.append(f"  중복 제거 — 버린 노드 {outcome.deduped}개 · 더 얕게"
                 f" 닿아 다시 펼친 노드 {outcome.revisited}개 · 대기 중에"
                 f" 밀려난 노드 {outcome.stale}개")
    lines.append(f"  최종 판 해시: {outcome.final_state_hash}")
    lines.append(f"  {_SEARCH_DISCLAIMER}")

    lines.append("")
    lines.append("  경로 (행동과 해결 중 선택)")
    if not outcome.path:
        lines.append("    경로가 없습니다.")
    for step in outcome.path:
        lines.append(f"    {step.order}. {step.kind} {step.action_key}")
        if step.reason:
            lines.append(f"       → {step.reason}")
        for ask in step.choices:
            lines.append(f"       선택 {ask.describe_ko()}")
            offered = " · ".join(
                f"#{instance}[{card_id}]" for instance, card_id in ask.offered
            )
            lines.append(f"         그 자리의 허용 후보: {offered or '없음'}")
        for note in step.forced:
            lines.append(f"       필수 {note}")

    lines.append("")
    lines.append("  최종 자신 필드 (실제 GameState)")
    if not outcome.final_field:
        lines.append("    비어 있습니다.")
    for zone, card_id, face_up in outcome.final_field:
        lines.append(f"    {zone} [{card_id}] "
                     + ("앞면" if face_up else "뒷면"))

    if rerun is not None:
        lines.append("")
        lines.append("  경로 재생 (새 초기 상태에서 다시 실행)")
        lines.append(f"    결과: {'성공' if rerun.ok else '🔴 실패'}")
        lines.append(f"    걸음 {rerun.steps} · 목표 도달"
                     f" {rerun.goal_reached} · 탐색 결과와 일치"
                     f" {rerun.matches_search}")
        lines.append(f"    {rerun.reason}")
        lines.append(f"    재생 최종 해시: {rerun.final_state_hash}")

    for label, notes in (
        ("범위 밖으로 둔 분기", outcome.out_of_scope),
        ("지원하지 않아 후보가 되지 못한 수", outcome.unsupported),
        ("상대 자리에서 무방해 정책이 넘긴 수", outcome.opponent_declined),
        ("상대 자리에 고를 것이 남아 멈춘 노드", outcome.opponent_blocked),
        ("🔴 오류", outcome.errors),
    ):
        lines.append("")
        lines.append(f"  {label} ({len(notes)}건)")
        if not notes:
            lines.append("    없음")
        for note in notes:
            lines.append(f"    - {note}")
    return "\n".join(lines)


# ======================================================================
# 복수 전개 결과의 자원 비교 (Phase 6-AI)
# ======================================================================
#: 🔴 **이 줄을 빼면 비교표가 강약표로 읽힌다.**
_MULTI_DISCLAIMER = (
    "🔴 **아직 강약 평가가 아닙니다** — 아래는 같은 초기 상태에서 나온"
    " 서로 다른 결과의 **남은 자원을 그대로 늘어놓은 것**이고, 어느 쪽이"
    " 더 좋은지 고르지 않았습니다. 점수도 총점도 순위도 없습니다"
    " — 🔴 **실전 강도·승률 평가는 하지 않습니다** (6-BC 정정: 이 자리는"
    " 비교표일 뿐이고, 추천을 고르는 휴리스틱은 따로 있습니다)."
    " 방해 수와 다음 턴의 전개는 **세지 않았습니다**."
)

#: 비교표에 적는 존의 한국어 이름.
_ZONE_KO = {
    "HAND": "패", "MZONE": "몬스터 존", "EMZONE": "엑스트라 몬스터 존",
    "SZONE": "마법·함정 존", "FZONE": "필드 존", "PZONE": "펜듈럼 존",
    "GRAVE": "묘지", "REMOVED": "제외", "DECK": "남은 메인 덱",
    "EXTRA": "남은 엑스트라 덱", "OVERLAY": "엑시즈 소재",
}


def _zone_ko(zone: str) -> str:
    return _ZONE_KO.get(zone, zone)


def _card_ko(card_id, repository=None) -> str:
    """
    카드 한 장을 **이름 + ID** 로. 🔴 없는 이름을 만들지 않는다.

    ``card_id`` 가 ``None`` 이면 그 자리는 **가려져 있다** — 상대 필드의
    뒷면 카드다. "없다" 로 적지 않는다.

    🔴 **한국어 이름은 이 층에서 붙인다.** ``agent`` 의 요약은 ID 만 들고
    있고 (표시 경계 감사: ``agent/`` 는 이름을 만들지 않는다), 저장소가
    없으면 ID 만 적는다.
    """
    if card_id is None:
        return "가려진 카드(정체 모름)"
    found = repository.get(card_id) if repository else None
    name = found.display_name() if found else None
    return f"{name} [{card_id}]" if name else f"[{card_id}]"


def _slot_ko(slot, repository=None) -> str:
    """필드 한 칸. 앞뒷면과 표시 형식을 **지우지 않는다**."""
    face = "앞면" if slot.face_up else "뒷면"
    return f"{_card_ko(slot.card_id, repository)} {face}/{slot.position}"


def _counts_ko(card_ids, repository=None) -> str:
    """
    카드 목록을 **같은 이름끼리 묶어** 적는다 (``×2`` 처럼).

    🔴 **같은 이름 여러 장을 한 장으로 줄이지 않는다** — 장수를 함께 적는다.
    """
    order: list = []
    counted: dict = {}
    for card_id in card_ids:
        if card_id not in counted:
            order.append(card_id)
            counted[card_id] = 0
        counted[card_id] += 1
    if not order:
        return "없음"
    bits = []
    for card_id in order:
        count = counted[card_id]
        label = _card_ko(card_id, repository)
        bits.append(label if count == 1 else f"{label} ×{count}")
    return " · ".join(bits)


def _use_lines(result) -> "list[str]":
    """그 결과에 **기록된** 사용 제한들."""
    out = []
    for record in result.resources.uses:
        seat = "" if record.seat is None else f"P{record.seat} "
        out.append(f"{seat}{record.kind} {record.label} ×{record.count}")
    return out


def _their_tokens(result) -> "tuple":
    """
    상대 자리에 **남긴 토큰** 칸들.

    🔴 **토큰을 "상대에게 준 손해" 로 읽지 않는다** — 그 칸이 무엇을 막고
    무엇을 돕는지는 이 단계에서 세지 않는다. 몇 칸이 어디에 있는지만 적는다.
    """
    return tuple(
        slot for slot in result.resources.their_field
        if slot.card_id is not None and slot.position
    )


#: 재생 상태 → 사람이 읽는 말 (Phase 6-AJ §C). 🔴 **여섯 가지를 한 칸으로
#: 뭉치지 않는다** — "검증되지 않았다" 하나로 적으면 왜 그런지가 사라진다.
#: ``agent`` 를 import 하지 않으므로 ``RerunState`` 의 **값 문자열**로 받는다
#: (ADR-007).
_RERUN_STATE_KO: dict = {
    "verified": "✔ 새 초기 상태에서 같은 판에 닿았습니다",
    "mismatched": "🔴 재생이 어긋났습니다 (행동·선택·최종 판·자원 요약 중"
                  " 하나) — 검증된 비교에 쓰지 않습니다",
    "errored": "🔴 재생이 **일반 실행 예외**로 멈췄습니다 — 이 결과만"
               " 실패이고, 다른 결과는 그대로 남습니다",
    "timed_out": "⏱️ 재생을 **시작했지만** 공유 재생 마감을 넘겨 멈췄습니다"
                 " — 🔴 검증 성공으로 세지 않습니다",
    "not_started": "⏱️ 재생을 **시작하지 못했습니다** (공유 재생 마감을 이미"
                   " 넘겼습니다) — 경로는 그대로 남습니다",
    "disabled": "⚪ 재생을 **끄고** 돌렸습니다 (rerun=False) — 검증되지"
                " 않았습니다",
    #: 🔴 **고른 적이 없어서 돌리지 않은 것**이다 (Phase 6-BB · 6-BC 정정).
    #: 6-BC 전에는 이 상태가 표에 없어 "재생 상태를 알 수 없습니다" 로
    #: 떨어졌고, 그러면 **평가가 보지도 않은 후보가 실패한 것처럼** 읽혔다.
    "not_selected": "➖ **상위 선택에서 제외되어 재실행하지 않았습니다** —"
                    " 🔴 재실행 실패가 아니고, 경로는 그대로 남습니다",
}


def _rerun_state_ko(result) -> str:
    """그 결과의 재생 상태를 사람이 읽는 말로."""
    state = getattr(result, "rerun_state", None)
    key = getattr(state, "value", state)
    return _RERUN_STATE_KO.get(
        key, "⚠️ 재생 상태를 알 수 없습니다 — 🔴 검증된 것으로 세지 않습니다"
    )


def _result_rows(result, repository=None) -> "list[tuple[str, str]]":
    """비교표 한 칸(결과 하나)의 항목들 — ``(항목, 값)``."""
    res = result.resources
    their = res.zone(1 - res.seat, "MZONE")
    their_cards = their.cards if their is not None else ()
    return [
        ("행동 수", f"{result.action_count}걸음"
                  f" (해결 중 선택 {result.choice_count}회)"),
        ("남은 패", f"{res.size(res.seat, 'HAND')}장 — "
                  + _counts_ko(res.card_ids(res.seat, "HAND"), repository)),
        ("자신 필드", " · ".join(
            _slot_ko(slot, repository) for slot in res.own_field) or "없음"),
        ("자신 마법·함정 존", " · ".join(
            _slot_ko(slot, repository)
            for slot in (res.zone(res.seat, "SZONE").cards
                         if res.zone(res.seat, "SZONE") is not None
                         else ())) or "없음"),
        ("상대 필드에 남긴 칸", " · ".join(
            _slot_ko(slot, repository) for slot in their_cards) or "없음"),
        ("자신 묘지", f"{res.size(res.seat, 'GRAVE')}장 — "
                   + _counts_ko(res.card_ids(res.seat, "GRAVE"), repository)),
        ("자신 제외", f"{res.size(res.seat, 'REMOVED')}장 — "
                   + _counts_ko(res.card_ids(res.seat, "REMOVED"), repository)),
        ("남은 덱", f"메인 {res.size(res.seat, 'DECK')}장 ·"
                 f" 엑스트라 {res.size(res.seat, 'EXTRA')}장"),
        ("일반 소환권", "이 턴에 썼습니다" if res.normal_summon_used
                    else "이 턴에 쓰지 않았습니다 (🔴 **지금 쓸 수 있다는"
                         " 뜻이 아닙니다**)"),
        ("기록된 사용 제한", " · ".join(_use_lines(result)) or "없음"),
        ("재생 검증", _rerun_state_ko(result)),
    ]


def _compare_lines(results, repository=None) -> "list[str]":
    """
    결과들의 **차이만** 짚는 문장들 (§4).

    🔴 **총점을 만들지 않는다.** 패와 필드의 장수를 더해 "자원 N" 으로
    적지 않고, 묘지·제외에 간 카드를 손실로 세지 않으며, 행동 수가 적은
    쪽을 센 전개로 적지 않는다.

    🔴 **차이가 없으면 없다고 적는다** — 억지로 차이를 만들지 않는다.
    """
    if len(results) < 2:
        return ["  비교할 다른 결과가 없습니다 (결과 1개)."]
    lines: list[str] = []
    base = results[0]
    for other in results[1:]:
        head = f"  결과 {base.index} 대비 결과 {other.index}"
        bits: list[str] = []
        if other.action_count != base.action_count:
            bits.append(f"행동이 {base.action_count}걸음 →"
                        f" {other.action_count}걸음 (🔴 적은 쪽이 센"
                        " 전개라는 뜻이 아닙니다)")
        mine, theirs = base.resources, other.resources
        for zone in ("HAND", "GRAVE", "REMOVED"):
            a = _counts_ko(mine.card_ids(mine.seat, zone), repository)
            b = _counts_ko(theirs.card_ids(theirs.seat, zone), repository)
            if a != b:
                bits.append(f"{_zone_ko(zone)}가 다릅니다 — {a} → {b}")
        a_field = tuple(_slot_ko(s, repository) for s in mine.own_field)
        b_field = tuple(_slot_ko(s, repository) for s in theirs.own_field)
        if a_field != b_field:
            bits.append("자신 필드가 다릅니다 — "
                        + (" · ".join(a_field) or "없음") + " → "
                        + (" · ".join(b_field) or "없음"))
        def _szone(summary):
            found = summary.zone(summary.seat, "SZONE")
            return tuple(
                _slot_ko(slot, repository)
                for slot in (found.cards if found is not None else ())
            )
        a_szone, b_szone = _szone(mine), _szone(theirs)
        if a_szone != b_szone:
            bits.append("자신 마법·함정 존이 다릅니다 — "
                        + (" · ".join(a_szone) or "없음") + " → "
                        + (" · ".join(b_szone) or "없음"))
        a_token = len(_their_tokens(base))
        b_token = len(_their_tokens(other))
        if a_token != b_token:
            bits.append(f"상대 필드에 남긴 칸이 {a_token}칸 → {b_token}칸"
                        " (🔴 그 칸이 상대에게 이득인지 손해인지는 이"
                        " 단계에서 세지 않습니다)")
        a_uses = set(_use_lines(base))
        b_uses = set(_use_lines(other))
        if a_uses != b_uses:
            only_a = " · ".join(sorted(a_uses - b_uses)) or "없음"
            only_b = " · ".join(sorted(b_uses - a_uses)) or "없음"
            bits.append(f"기록된 사용 제한이 다릅니다 — 결과"
                        f" {base.index} 에만 있는 것: {only_a} / 결과"
                        f" {other.index} 에만 있는 것: {only_b}")
        if mine.normal_summon_used != theirs.normal_summon_used:
            bits.append("일반 소환권 사용이 다릅니다")
        if not bits:
            #: 🔴 **요약에 담기지 않는 차이가 있을 수 있다.** 두 결과는
            #: 서로 다른 상태(:func:`agent.bounded_search.outcome_key`)이므로
            #: "같다" 고 적지 않는다.
            lines.append(f"{head}: 위 항목에서는 차이를 찾지 못했습니다 —"
                         " 🔴 **두 결과는 엔진 상태가 다릅니다**(그래서"
                         " 따로 셌습니다). 차이가 이 요약 항목에 담기지"
                         " 않았다는 뜻이므로, 아래 전체 기록의 상태 해시와"
                         " 존 목록을 보십시오.")
            continue
        lines.append(head + ":")
        lines.extend(f"    - {bit}" for bit in bits)
    return lines


def _multi_head(outcome) -> "list[str]":
    """결과 수 · 목표 · 조건 · 종료 사유 — 요약과 상세가 함께 쓴다."""
    lines = [f"  목표: {outcome.goal.describe_ko()}"]
    lines.append("  조건: **선공 · 상대 방해 없음**(명시적 정책) ·"
                 " **이번 턴만** — 🔴 상대가 움직이는 판이 아닙니다.")
    tally = outcome.tally
    lines.append(f"  검증된 서로 다른 결과 {tally.verified}개"
                 f" (모은 결과 {outcome.found}개 — {tally.describe_ko()})")
    #: 🔴 **경로를 찾은 사실과 검증을 마친 사실을 가른다** (§C).
    if tally.verified != outcome.found:
        lines.append(f"  🔴 **찾은 경로 {outcome.found}개는 그대로 남아"
                     f" 있습니다** — 재생 검증을 마친 것이"
                     f" {tally.verified}개라는 뜻입니다 (경로가 사라진 것이"
                     " 아닙니다).")
    if tally.timed_out or tally.not_started:
        lines.append(f"  ⏱️ 재생 시간이 끊은 결과 — 도중에 멈춘 것"
                     f" {tally.timed_out}개 · 시작조차 못 한 것"
                     f" {tally.not_started}개 (🔴 서로 다른 사실입니다)")
    if tally.errored:
        lines.append(f"  🔴 일반 실행 예외로 멈춘 결과 {tally.errored}개 —"
                     " 시간 초과와 **다른 이유**입니다. 상세 기록의 결과별"
                     " 사유를 보십시오.")
    if outcome.duplicate_results:
        lines.append(f"  같은 결과에 닿아 **대표로 합친** 경로"
                     f" {outcome.duplicate_results}개 — 🔴 이 수는 서로"
                     " 다른 결과 수를 늘리지 않습니다.")
    lines.append("  종료: "
                 + _TERMINATION_KO.get(outcome.termination.value,
                                       outcome.termination.value))
    if outcome.hit_result_cap:
        lines.append(f"  ⚠️ **결과 수 상한에 닿아 멈췄습니다**"
                     f" (max_results={outcome.budget.max_results}) — 더"
                     " 있을 수 있습니다.")
    #: 🔴 **탐색 예산과 재생 예산의 사유를 섞지 않는다** (§A-9).
    lines.append("  탐색 예산에 걸린 칸: "
                 + (" · ".join(outcome.budget_hit) or "없음"))
    lines.append("  재생 예산에 걸린 칸: "
                 + (" · ".join(getattr(outcome, "rerun_budget_hit", ()))
                    or "없음"))
    #: 🔴 **"찾았다" 와 "끝까지 봤다" 를 가른다.**
    lines.append("  지정된 범위를 끝까지 펼쳤는가: "
                 + ("예" if outcome.search_exhausted else
                    "아니오 — 🔴 **돌려준 결과가 가능한 모든 전개가"
                    " 아닙니다**"))
    if outcome.skipped_choices:
        lines.append(f"  ⚠️ **해결 중 선택을 다 보지 않았습니다** —"
                     f" 확인하지 않은 대안이 남은 물음"
                     f" {outcome.choice_offers_truncated}곳")
    lines.append(f"  탐색 {outcome.search_seconds:.2f}초 · 재생"
                 f" {outcome.rerun_seconds:.2f}초"
                 f" (🔴 따로 적습니다) · 펼친 노드"
                 f" {outcome.nodes_expanded}개 · 최대 깊이 {outcome.deepest}")
    return lines


#: 후속 전개 모드의 **멈춘 이유**를 사람이 읽는 말로 (Phase 6-AL).
#: 🔴 ``agent`` 를 import 하지 않으므로 값 문자열로 받는다 (ADR-007).
_STOP_KO: dict = {
    "open": "🔴 **더 갈 수 있는 자리입니다** — 전개 완료가 아니고, 예산이"
            " 끊겨 여기까지만 보았습니다",
    "action_cap": "후속 행동 상한에 닿았습니다",
    "depth_cap": "깊이 상한에 닿았습니다 (🔴 후속 상한과 다른 상한입니다)",
    "no_legal": "이 턴 범위에서 엔진이 허가한 수가 없습니다",
    "unsupported_left": "🔴 허가된 수가 없지만 **지원하지 않아 후보가 되지"
                        " 못한 수가 남아 있습니다** — 규칙상 더 할 수 없다는"
                        " 뜻이 아닙니다",
    "budget": "전체 예산이 끊어 끝까지 보지 못했습니다",
}

#: 🔴 **후속 모드의 범위.**
_FOLLOWUP_SCOPE = (
    "🔴 **목표에 처음 도달한 뒤 같은 턴 메인 페이즈 안에서** 엔진이 허가한"
    " 행동을 **제한된 수만큼** 더 펼친 것입니다 — **최선 전개도, 최종 집"
    " 완성도, 실전 강도 검증도 아닙니다**. 전투 · 턴 종료 · 다음 턴은 범위"
    " 밖이고, 상대는 언제나 패스합니다(명시적 정책)."
)

#: 🔴 **후속 모드에 추천을 연결하지 않는다** (6-AL §5).
_FOLLOWUP_NO_RANKING = (
    "🔴 **이 모드에는 자원 보존 추천(resource-preservation v1)을 연결하지"
    " 않았습니다** — 그 기준은 패를 쓰는 행동을 불리하게 보므로, 후속 전개의"
    " 가지치기나 확장 우선순위로 쓰면 후속 전개를 찾지 못합니다. 아래는"
    " **기준점 대비 실제 자원 변화**이고 실전 강도 순서가 아닙니다."
)


def _choice_key(ask) -> tuple:
    """
    해결 중 선택 **하나**의 식별값 (Phase 6-AM §2).

    🔴 **경로 재현에 필요한 것만, 값으로** 센다 — 몇 번째 물음인가
    (``index``), 어느 **인스턴스**를 골랐나 (``chosen``), 그것이 어느
    카드였나 (``chosen_card_ids``). 재생이 각본으로 쓰는 것이 바로
    ``chosen`` 이므로, 이 셋이 같으면 같은 선택을 다시 한 것이다.

    🔴 **표시 문구나 ``repr`` 에 기대지 않는다** — ``label`` 과
    ``describe_ko()`` 는 사람이 읽는 말이고 판정에 쓰지 않는다.
    """
    return (
        getattr(ask, "index", -1),
        tuple(getattr(ask, "chosen", ()) or ()),
        tuple(getattr(ask, "chosen_card_ids", ()) or ()),
    )


def _path_key(path) -> tuple:
    """
    경로 하나의 식별값 — **행동과 해결 중 선택을 함께** (Phase 6-AM §2).

    🔴 **행동 열쇠만으로는 모자란다.** 같은 효과 발동이라도 해결 중 고른
    카드가 다르면 **다른 자리에 도달**하므로, 선택을 빼고 맞추면 후속
    후보가 **엉뚱한 기준점**에 이어지고 자원 변화가 다른 경로를 기준으로
    계산된다 (6-AL 의 결함).
    """
    return tuple(
        (
            getattr(step, "order", index + 1),
            getattr(step, "kind", ""),
            tuple(getattr(step, "action_key", ()) or ()),
            tuple(_choice_key(ask) for ask in getattr(step, "choices", ())),
        )
        for index, step in enumerate(path)
    )


def _baseline_of(outcome, candidate):
    """
    그 후속 후보가 **어느 기준점에서 출발했는가.**

    🔴 **경로의 앞부분으로 맞춘다** — 최초 도달 걸음까지의 **행동과 해결 중
    선택**이 같은 기준점이 그것이다 (:func:`_path_key`).

    🔴 **못 찾으면 ``None``** 이고, 그때는 비교하지 않는다 — 임의의 첫
    기준점으로 대체하지 않는다(그러면 틀린 자원 변화가 표시된다). 후속
    경로 자체는 그대로 남는다.

    🔴 **결과 순서에 기대지 않는다** — 값으로 맞추므로 정렬 · 대표 교체 ·
    중복 병합 뒤에도 연결이 바뀌지 않는다.
    """
    reached = getattr(candidate.meta, "reached_at", 0)
    if not reached:
        return None
    head = _path_key(candidate.path[:reached])
    for one in outcome.baselines:
        if _path_key(one.path) == head:
            return one
    return None


def _followup_actions_ko(outcome, candidate, repository=None) -> str:
    """기준점 **뒤에** 실제로 한 행동들."""
    reached = getattr(candidate.meta, "reached_at", 0)
    bits = []
    for step in candidate.path[reached:]:
        picked = " · ".join(
            _card_ko(card_id, repository)
            for ask in step.choices
            for card_id in ask.chosen_card_ids
        )
        bits.append(_kind_ko(step.kind) + (f"({picked})" if picked else ""))
    return " → ".join(bits) or "없음"


def _followup_brief(outcome, repository=None) -> "list[str]":
    """
    **후속 전개 요약** — 기본 응답에 들어가는 몇 줄 (Phase 6-AL §6).

    🔴 ``agent`` 를 import 하지 않는다 — 결과의 **모양만** 읽는다.
    """
    if not getattr(outcome, "continues", False):
        return []
    lines = ["", "  후속 전개 — 목표에 도달한 뒤 더 간 것", _RULE_THIN]
    lines.append("    최초 목표 도달: "
                 + ("예 — 기준점 "
                    f"{len(outcome.baselines)}개" if outcome.baselines
                    else "🔴 **아니오** — 기준점을 찾지 못했습니다"))
    verified = outcome.verified_continued
    lines.append(f"    재생 검증된 후속 후보 {len(verified)}개"
                 f" (모은 후속 후보 {len(outcome.continued_results)}개)")
    if not outcome.continued_results:
        lines.append("    🔴 **후속 후보를 찾지 못했습니다** — 아래 `후속"
                     " 전개 메모` 와 `지원 범위` 를 보십시오. 최초 도달"
                     " 결과는 그대로 남아 있습니다.")
    for one in verified:
        base = _baseline_of(outcome, one)
        lines.append("")
        lines.append(f"    [결과 {one.index}] 기준점 걸음"
                     f" {one.meta.reached_at} 뒤에 더 한 것:"
                     f" {_followup_actions_ko(outcome, one, repository)}")
        lines.append(f"      비흐름 후속 행동 {one.meta.followup_actions}회"
                     f" (흐름 {one.meta.followup_flow}회는 세지 않았습니다)"
                     f" · 멈춘 이유: "
                     + _STOP_KO.get(one.meta.stop.value, one.meta.stop.value))
        lines.append("      최종 상태에 목표 카드: "
                     + ("남아 있습니다" if one.goal_kept else
                        "🔴 **남아 있지 않습니다** (후속 전개에서 소재나"
                        " 비용으로 썼습니다) — 최초 도달 기록은 그대로입니다"))
        if base is None:
            lines.append("      ⚠️ 기준점을 찾지 못해 자원 변화를 비교하지"
                         " 않았습니다.")
            continue
        lines.append(f"      기준점(결과 {base.index}) 대비 자원 변화")
        for line in _compare_lines((base, one), repository):
            lines.append("    " + line)
    lines.append("")
    lines.append(f"    {_FOLLOWUP_SCOPE}")
    lines.append(f"    {_FOLLOWUP_NO_RANKING}")
    if outcome.followup_notes:
        lines.append(f"    후속 전개에서 멈춘 자리 {len(outcome.followup_notes)}건"
                     " — 상세 기록에 그대로 있습니다.")
    return lines


def _followup_detail(outcome, repository=None) -> "list[str]":
    """**후속 전개 상세** — 기준점 · 전체 경로 · 예산 · 검증 한계."""
    if not getattr(outcome, "continues", False):
        return []
    budget = outcome.budget
    lines = ["", "  후속 전개 (기준점과 전체 경로)", _RULE_THIN]
    lines.append(f"    {_FOLLOWUP_SCOPE}")
    lines.append(f"    {_FOLLOWUP_NO_RANKING}")
    lines.append(f"    쓴 예산 — 후속 비흐름 행동 상한"
                 f" {budget.max_followup_actions}회 · 기준점 상한"
                 f" {budget.max_baselines}개 · 후속 후보 상한"
                 f" {budget.max_results}개 · 깊이 {budget.max_depth} · 노드"
                 f" {budget.max_nodes} · {budget.max_seconds:g}초 · 재생"
                 f" {budget.max_rerun_seconds:g}초")
    lines.append("    🔴 **기준점 보관과 후속 후보 보관은 역할이 다릅니다** —"
                 " 기준점을 모으는 것이 후속 후보의 상한을 먹지 않습니다.")
    lines.append("    🔴 **예산은 기준점마다 새로 시작하지 않습니다** — 깊이"
                 " 우선이므로 한 기준점에서 예산이 소진될 수 있고, 그때"
                 " 돌려준 후보는 가능한 전부가 아닙니다.")

    for one in outcome.results:
        lines.append("")
        role = "기준점 (최초 목표 도달)" if one.is_baseline else "후속 후보"
        lines.append(f"    [결과 {one.index}] {role}")
        lines.append(f"      최초 도달 걸음: {one.meta.reached_at or '알 수 없음'}")
        if one.meta.merged_arrivals:
            lines.append("      🔴 같은 최종 상태로 합쳐진 다른 경로의 최초"
                         " 도달 걸음: "
                         + " · ".join(str(i)
                                      for i in one.meta.merged_arrivals)
                         + " (대표는 걸음 수 → 행동 열쇠 → 선택 순서로"
                           " 골랐고, 합쳐진 도달 이력은 지우지 않았습니다)")
        lines.append(f"      비흐름 후속 행동 {one.meta.followup_actions}회 ·"
                     f" 흐름 {one.meta.followup_flow}회 (세지 않음)")
        lines.append("      멈춘 이유: "
                     + _STOP_KO.get(one.meta.stop.value, one.meta.stop.value))
        lines.append("      최종 상태에 목표 카드: "
                     + ("남아 있습니다" if one.goal_kept
                        else "🔴 남아 있지 않습니다"))
        lines.append("      전체 경로 (기준점 앞 | 기준점 뒤)")
        reached = one.meta.reached_at
        for step in one.path:
            where = "기준점 앞" if step.order <= reached else "기준점 뒤"
            lines.append(f"        {step.order}. [{where}] {step.kind}"
                         f" {step.action_key}")
            for ask in step.choices:
                lines.append(f"           선택 {ask.describe_ko()}")
        if one.rerun is None:
            lines.append("      재생: ⚠️ 돌리지 못했습니다 — 🔴 검증되지"
                         " 않았습니다.")
        else:
            lines.append(
                f"      재생: {_rerun_state_ko(one)}"
                f"\n        최초 도달 확인"
                f" {one.rerun.first_arrival_confirmed}"
                f" (걸음 {one.rerun.first_arrival_at or reached}) · 최종 판"
                f" 일치 {one.rerun.matches_search} · 자원 요약 일치"
                f" {one.resources_match} · 최종 목표 유지"
                f" {one.rerun.goal_kept}"
            )
    lines.append("")
    lines.append("    🔴 검증 한계")
    lines.append("      - 돌려준 후속 후보가 **가능한 전부가 아닙니다** —"
                 " 후속 행동 상한 · 기준점 상한 · 후속 후보 상한 · 깊이 ·"
                 " 노드 · 시간 · 선택 조합이 모두 남은 길을 가립니다.")
    lines.append("      - **지원하지 않아 후보가 되지 못한 수**가 있으면"
                 " `지원 범위` 에 적혀 있습니다 — 그 수가 가능했다면 다른"
                 " 후속이 있었을 수 있습니다.")
    lines.append("      - 후속 모드의 중복 제거는 **목표 도달 이력과 남은"
                 " 후속 예산**을 열쇠에 넣습니다 (같은 상태라도 더 갈 수"
                 " 있는 쪽을 버리지 않기 위해서). 그 대가로 중복 제거가"
                 " 약해져 같은 판이 여러 노드로 남습니다.")
    lines.append("      - 재생 실패 · 예외 · 시간 초과 후보는 **검증 성공으로"
                 " 세지 않습니다** (위 상태 칸을 보십시오).")
    return lines


def _ranking_brief(ranking) -> "list[str]":
    """
    **추천 요약** — 기본 응답에 들어가는 몇 줄 (Phase 6-AK §4).

    🔴 ``agent`` 를 import 하지 않는다 — 넘어온 평가 결과의 **모양만** 읽는다
    (ADR-007).

    🔴 **판정하지 않는다.** 여기서 수치를 다시 세거나 순위를 만들지 않고,
    평가 단계가 적어 둔 것을 그대로 옮긴다.
    """
    if ranking is None:
        return []
    verified = len(getattr(ranking, "verified_candidates", ()))
    lines = ["", "  추천 — 어느 후보를 먼저 볼까", _RULE_THIN]
    lines.append(f"    평가 정책: {getattr(ranking, 'policy_label', '?')}"
                 " (자원 보존 중심의 제한적 휴리스틱)")
    lines.append(f"    검증된 후보 {verified}개")
    note = getattr(ranking, "note", "")
    if note:
        lines.append(f"    {note}")
    picked = getattr(ranking, "recommended", ())
    if not picked:
        lines.append("    🔴 **추천 후보가 없습니다** — 아래 `추천 대상에서"
                     " 제외` 를 보십시오. 🔴 이 패로 불가능하다는 뜻이"
                     " 아닙니다.")
    else:
        ids = " · ".join(f"결과 {one.index}" for one in picked)
        head = ("공동 후보" if getattr(ranking, "tied", False)
                else "추천 후보")
        lines.append(f"    {head}: {ids}"
                     + ("  — 🔴 **둘 이상입니다**: 장단점이 갈리거나 동률이고,"
                        " 억지로 하나로 줄이지 않았습니다."
                        if getattr(ranking, "tied", False) else ""))
        for one in picked:
            lines.append(f"    [결과 {one.index}]"
                         f" {ranking.reason_ko(one.index)}")
    #: 🔴 **범위와 한계를 요약에서 잘라 내지 않는다.**
    lines.append(f"    {_RANKING_SCOPE}")
    lines.append(f"    {_RANKING_WHEN}")
    return lines


def _ranking_detail(ranking) -> "list[str]":
    """**추천 상세** — 후보별 값 · 선정 이유 · 제외 사유 · 평가 못 한 것."""
    if ranking is None:
        return []
    lines = ["", "  추천 (평가 정책과 후보별 값)", _RULE_THIN]
    lines.append(f"    정책 이름: {getattr(ranking, 'policy', '?')}")
    lines.append(f"    정책 판: {getattr(ranking, 'version', '?')}")
    lines.append(f"    {_RANKING_SCOPE}")
    lines.append(f"    {_RANKING_WHEN}")
    lines.append("")
    lines.append("    쓴 기준")
    for criterion in getattr(ranking, "criteria", ()):
        lines.append(f"      - {criterion.label_ko} (`{criterion.key}`)"
                     f" — {criterion.reads_ko}")
        lines.append(f"        쓰임: {criterion.role_ko}")
        lines.append(f"        {criterion.limit_ko}")
    lines.append("    🔴 **임의의 가중치 합계나 전개 점수를 만들지 않았습니다**"
                 " — 위 세 수치와 그 제한만 적습니다.")

    lines.append("")
    lines.append("    후보별 평가 항목과 값")
    for one in getattr(ranking, "candidates", ()):
        measures = getattr(one, "measures", None)
        if measures is None:
            lines.append(f"      [결과 {one.index}] 평가하지 못했습니다 —"
                         f" {ranking.reason_ko(one.index)}")
            continue
        mark = "✔ 추천" if one.recommended else "— 비추천"
        lines.append(f"      [결과 {one.index}] {mark}"
                     f" · 표시 순서 {one.order or '-'}"
                     f" · 남은 패 {measures.hand_left}장"
                     f" · 일반 소환권 "
                     + ("사용" if measures.normal_summon_used else "미사용")
                     + f" · 비흐름 행동 {measures.spend_actions}회"
                     f" (흐름 {measures.flow_actions}회는 비용에서 제외)")
        lines.append(f"        {ranking.reason_ko(one.index)}")

    lines.append("")
    lines.append("    비지배 후보 선정")
    lines.append("      두 보존 축(남은 패 · 일반 소환권)에서 **두 축 모두"
                 " 나쁘지 않고 최소 한 축이 더 나은** 후보가 있으면 밀린다.")
    lines.append("      서로 장단점이 있으면 **둘 다 남긴다**. 비지배 후보"
                 " 안에서는 비흐름 행동이 적은 쪽을 먼저 적고, 같으면 공동"
                 " 후보로 둔다.")
    lines.append("      🔴 **게임 전체에서의 우월성이나 안전한 가지치기 근거가"
                 " 아니다** — 밀린 후보가 필드 구성이나 세트한 카드 때문에"
                 " 실제로 더 좋을 수 있고, 이번 기준은 그것을 보지 못한다.")
    lines.append("      🔴 결과 ID 는 **표시 순서를 가르는 데만** 썼고 우열"
                 " 근거로 쓰지 않았다.")

    excluded = getattr(ranking, "excluded", ())
    lines.append("")
    lines.append(f"    추천 대상에서 제외 ({len(excluded)}건)")
    if not excluded:
        lines.append("      없음")
    for one in excluded:
        lines.append(f"      - [결과 {one.index}] 재생 상태"
                     f" {one.rerun_state} · {ranking.reason_ko(one.index)}")
    lines.append("      🔴 제외된 결과의 **경로와 자원은 위에 그대로**"
                 " 있습니다 — 평가 때문에 사라지지 않습니다.")

    lines.append("")
    lines.append("    🔴 이번 기준이 유불리를 판단하지 **못한** 차이")
    for note in getattr(ranking, "unjudged", ()):
        lines.append(f"      - {note}")
    lines.append("      이 차이들은 위 `결과들의 차이` 와 각 결과의 자원"
                 " 칸에 **그대로 남아 있습니다** — 보여 주기만 하고 점수로"
                 " 바꾸지 않았습니다.")
    return lines


def render_multi_search_brief(outcome, repository=None, ranking=None) -> str:
    """
    **복수 결과 탐색의 기본 응답용 요약** (Phase 6-AI §6).

    🔴 **판정하지 않는다.** 이미 끝난 탐색 결과만 읽고 엔진을 다시 돌리지
    않는다. ``agent`` 를 import 하지 않고 결과의 **모양만** 읽는다.

    🔴 **다섯 가지를 반드시 적는다**: 검증된 결과 수 · 목표와 무방해 조건 ·
    자원 비교 요약 · 탐색 종료 사유와 생략 여부 · 아직 강약 평가가 아니라는
    설명.
    """
    lines = ["", "제한 전개 탐색 — 서로 다른 결과 비교", _RULE]
    lines.extend(_multi_head(outcome))
    lines.append(f"  {_SEARCH_DISCLAIMER}")
    lines.append(f"  {_MULTI_DISCLAIMER}")

    #: 🔴 **추천은 탐색·재생이 끝난 뒤의 독립 단계다** (6-AK). 주지 않으면
    #: 6-AJ 와 한 글자도 다르지 않다.
    lines.extend(_ranking_brief(ranking))
    #: 🔴 **후속 모드의 절** (6-AL). 후속 모드가 아니면 한 줄도 붙지 않는다.
    lines.extend(_followup_brief(outcome, repository))

    shown = outcome.verified_results or outcome.results
    lines.append("")
    if not outcome.results:
        lines.append("  찾은 결과가 없습니다 — 🔴 **이 패로 불가능하다는"
                     " 뜻이 아닙니다.**")
        return "\n".join(lines)
    if not outcome.verified_results:
        lines.append("  🔴 **검증된 결과가 없습니다** — 아래는 재생으로"
                     " 뒷받침되지 않은 결과입니다.")
    elif len(shown) == 1:
        lines.append("  검증된 결과가 **하나**입니다 — 🔴 결과 수를 채우려고"
                     " 중복 경로를 끼워 넣지 않았습니다.")

    for result in shown:
        lines.append("")
        lines.append(f"  [결과 {result.index}]"
                     + (f" (같은 결과에 닿은 다른 경로"
                        f" {result.duplicates}개)" if result.duplicates
                        else ""))
        for step in result.path:
            picked = " · ".join(
                _card_ko(card_id, repository)
                for ask in step.choices
                for card_id in ask.chosen_card_ids
            )
            tail = f" (해결 중 선택 {picked})" if picked else ""
            lines.append(f"    {step.order}. {_kind_ko(step.kind)}{tail}")
        for label, value in _result_rows(result, repository):
            lines.append(f"    {label}: {value}")

    lines.append("")
    #: 🔴 **검증된 비교에는 검증 성공 결과만 넣는다** — 검증된 것이 없어
    #: 아래에 적을 수밖에 없을 때는 제목에서 그 사실을 밝힌다 (§C).
    lines.append("  결과들의 차이" if outcome.verified_results
                 else "  결과들의 차이 (🔴 검증되지 않은 결과입니다)")
    lines.extend(_compare_lines(shown, repository))
    if len(shown) >= 2:
        lines.append("    🔴 **어느 쪽이 더 좋은지 고르지 않았습니다** —"
                     " 서로 주고받는 차이(한쪽은 패가 남고 다른 쪽은 묘지가"
                     " 쌓이는 식)는 양쪽을 그대로 적었습니다.")
    return "\n".join(lines)


def render_multi_search(outcome, repository=None, setup=None,
                        ranking=None) -> str:
    """
    **복수 결과 탐색의 전체 기록** — 첨부와 CLI 가 보는 것 (6-AI §6).

    🔴 **한 줄도 줄이지 않는다.** 결과마다 걸음의 행동 열쇠와 해결 중 선택
    전부 · 모든 존의 자원 · 기록된 사용 제한 · 재생 결과를 적고, 미지원 ·
    예산 · 생략의 상세를 그대로 적는다.
    """
    lines = ["", "제한 전개 탐색 (복수 결과) — 전체 기록", _RULE]
    lines.extend(_multi_head(outcome))
    if setup is not None:
        lines.append("  입력 조건")
        lines.append("    시작 패: " + " · ".join(
            _card_ko(card_id, repository) for card_id in setup.hand))
        lines.append(f"    남은 메인 덱 {len(setup.deck_rest)}장 ·"
                     f" 엑스트라 {len(setup.extra)}장")
        for note in setup.unknowns:
            lines.append(f"    ⚠️ 알 수 없음: {note}")
    lines.append(f"  예산: {outcome.budget.describe_ko()}")
    lines.append(f"  해결 중 선택 — 대기에 넣은 대안 각본"
                 f" {outcome.choice_branches}개 · 실제로 돌린 각본"
                 f" {outcome.choice_plans}개 · 확인하지 못한 대안이 남은 물음"
                 f" {outcome.choice_offers_truncated}곳")
    lines.append(f"  중복 제거 — 버린 노드 {outcome.deduped}개 · 더 얕게"
                 f" 닿아 다시 펼친 노드 {outcome.revisited}개 · 대기 중에"
                 f" 밀려난 노드 {outcome.stale}개")
    lines.append(f"  {_SEARCH_DISCLAIMER}")
    lines.append(f"  {_MULTI_DISCLAIMER}")

    for result in outcome.results:
        lines.append("")
        lines.append(f"  [결과 {result.index}] 목표 판정:"
                     f" {result.goal_reason}")
        lines.append(f"    같은 결과에 닿은 다른 경로 {result.duplicates}개"
                     " (🔴 결과 수를 늘리지 않습니다)")
        lines.append("    경로 (행동과 해결 중 선택)")
        for step in result.path:
            lines.append(f"      {step.order}. {step.kind} {step.action_key}")
            if step.reason:
                lines.append(f"         → {step.reason}")
            for ask in step.choices:
                lines.append(f"         선택 {ask.describe_ko()}")
                offered = " · ".join(
                    f"#{instance}[{card_id}]"
                    for instance, card_id in ask.offered
                )
                lines.append(f"           그 자리의 허용 후보:"
                             f" {offered or '없음'}")
            for note in step.forced:
                lines.append(f"         필수 {note}")
        lines.append("    최종 자원 (실제 GameState)")
        res = result.resources
        lines.append(f"      T{res.turn_number} {res.phase} · 상태 해시"
                     f" {res.state_hash}")
        for zone in res.zones:
            who = "자신" if zone.seat == res.seat else "상대"
            if zone.counted_only:
                lines.append(f"      {who} {_zone_ko(zone.zone)}"
                             f" {zone.size}장 (장수만)")
                continue
            inside = " · ".join(
                _slot_ko(slot, repository) for slot in zone.cards) or "없음"
            lines.append(f"      {who} {_zone_ko(zone.zone)}"
                         f" {zone.size}장: {inside}")
        lines.append("      기록된 사용 제한: "
                     + (" · ".join(_use_lines(result)) or "없음")
                     + " — 🔴 **쓰지 않았다는 기록을 지금 쓸 수 있다는"
                       " 뜻으로 읽지 마십시오.**")
        lines.append("      일반 소환권: "
                     + ("이 턴에 썼습니다" if res.normal_summon_used
                        else "이 턴에 쓰지 않았습니다"))
        lines.append("    재생 (새 초기 상태에서 다시 실행)")
        #: 🔴 **결과별 사유를 상세 기록에 적는다** (§C) — 기본 응답은 짧게
        #: 두고, 왜 검증되지 않았는지는 여기서 되돌릴 수 있게 둔다.
        lines.append(f"      상태: {_rerun_state_ko(result)}")
        if result.rerun is None:
            lines.append("      아래 `재생 메모` 를 보십시오. 🔴 이 결과는"
                         " 검증되지 않았지만 **경로는 그대로 남아 있습니다.**")
        else:
            state = "✔ 성공" if result.rerun.ok else "🔴 실패"
            lines.append(f"      {state} — 걸음 {result.rerun.steps}개 ·"
                         f" 목표 {result.rerun.goal_reached} · 최종 판 일치"
                         f" {result.rerun.matches_search} · 자원 요약 일치"
                         f" {result.resources_match}")
            stage = getattr(result.rerun, "stage", "")
            error_type = getattr(result.rerun, "error_type", "")
            if error_type:
                lines.append(f"      🔴 예외 {error_type} · 단계"
                             f" {stage or '알 수 없음'} — 조용히 삼키지 않고"
                             " 이 결과의 실패로 적었습니다.")
            elif getattr(result.rerun, "timed_out", False):
                lines.append(f"      ⏱️ 공유 재생 마감을 넘긴 자리: "
                             f"{stage or '알 수 없음'} — 🔴 협력적 제한이므로"
                             " 돌고 있던 엔진 호출 하나는 끊지 않았습니다.")
            lines.append(f"      {result.rerun.reason}")
            if not result.verified:
                lines.append("      🔴 **검증된 비교에 쓰지 않습니다.**")

    lines.append("")
    lines.append("  결과들의 차이 (검증된 것만)")
    lines.extend(_compare_lines(outcome.verified_results, repository))
    lines.extend(_ranking_detail(ranking))
    lines.extend(_followup_detail(outcome, repository))

    for label, notes in (
        ("범위 밖으로 둔 분기", outcome.out_of_scope),
        ("지원하지 않아 후보가 되지 못한 수", outcome.unsupported),
        ("상대 자리에서 무방해 정책이 넘긴 수", outcome.opponent_declined),
        ("상대 자리에 고를 것이 남아 멈춘 노드", outcome.opponent_blocked),
        ("재생 메모", outcome.rerun_notes),
        ("🔴 오류", outcome.errors),
    ):
        lines.append("")
        lines.append(f"  {label} ({len(notes)}건)")
        if not notes:
            lines.append("    없음")
        for note in notes:
            lines.append(f"    - {note}")
    return "\n".join(lines)


# ======================================================================
# 자율 전개 탐색 — 목표 카드를 지정하지 않은 결과 (Phase 6-BB)
# ======================================================================
#: 🔴 **자율 탐색임을 제목이 말한다.** 사람이 적어 둔 고정 경로를 돌린
#: 결과와 한눈에 갈려야 한다 (§7).
OPEN_SEARCH_TITLE: str = "자율 전개 탐색 — 🔴 목표 카드를 지정하지 않았습니다"

_OPEN_DISCLAIMER: str = (
    "🔴 **전역 최적 전개가 아닙니다** — 예산(깊이 · 노드 · 시간 · 선택 분기 ·"
    " 후보 수) 안에서 찾은 것들의 비교이고, 고정 경로도 영상 수순도 쓰지"
    " 않았습니다."
)

_OPEN_FIXED_NOTE: str = (
    "🔴 **아직 고정되어 있는 것**: 해결 중 선택은 탐색이 분기하지만"
    " (`max_choice_branches`), 분기 상한을 넘는 대안은 **첫 허용 후보**로"
    " 고정됩니다 — 그 자리가 남아 있으면 위의 '해결 중 선택' 줄이 몇 곳인지"
    " 적습니다."
)


def _open_ranking_lines(ranking, repository=None) -> "list[str]":
    """
    자율 탐색의 **추천 절**. ``ranking`` 이 없으면 한 줄도 붙지 않는다.

    🔴 **점수 하나로 합치지 않는다** — 축마다 센 값과 그 값이 증명하지
    않는 것을 함께 적는다.
    """
    if ranking is None:
        return []
    lines = ["", f"  추천 (평가 {ranking.policy_label})"]
    lines.append(f"    {_OPEN_DISCLAIMER}")
    if ranking.note:
        lines.append(f"    {ranking.note}")
    best = ranking.recommended
    if not best:
        lines.append("    🔴 **추천할 후보가 없습니다** — 검증된 결과가"
                     " 없거나 평가에 필요한 값을 읽지 못했습니다.")
    for one in best:
        lines.append(f"    ★ 결과 {one.index} — {ranking.reason_ko(one.index)}")
    if len(best) >= 2:
        lines.append("    🔴 **공동 추천입니다** — 세 축이 서로 주고받아"
                     " 하나로 줄이지 않았습니다.")
    others = [one for one in ranking.candidates
              if one.eligible and not one.recommended]
    for one in sorted(others, key=lambda c: (c.order, c.index))[:4]:
        lines.append(f"    · 결과 {one.index} — {ranking.reason_ko(one.index)}")
    skipped = [one for one in ranking.candidates if not one.eligible]
    if skipped:
        lines.append(f"    비교에서 빠진 결과 {len(skipped)}개 — 🔴 **경로는"
                     " 그대로 남아 있습니다** (상세 기록에 사유가 있습니다).")
    lines.append("    이 평가가 판정하지 않는 것:")
    for note in ranking.unjudged:
        lines.append(f"      · {note}")
    return lines


def render_open_search_brief(outcome, repository=None, ranking=None) -> str:
    """
    **자율 탐색의 기본 응답용 요약** (Phase 6-BB).

    🔴 **판정하지 않는다** — 이미 끝난 탐색 결과만 읽고 엔진을 다시 돌리지
    않는다. ``agent`` 를 import 하지 않고 결과의 **모양만** 읽는다.
    """
    lines = ["", OPEN_SEARCH_TITLE, _RULE]
    lines.extend(_multi_head(outcome))
    lines.append(f"  {_SEARCH_DISCLAIMER}")
    lines.extend(_open_ranking_lines(ranking, repository))
    shown = outcome.verified_results or outcome.results
    lines.append("")
    if not outcome.results:
        lines.append("  찾은 결과가 없습니다 — 🔴 **이 패로 불가능하다는"
                     " 뜻이 아닙니다.**")
        return "\n".join(lines)
    if not outcome.verified_results:
        lines.append("  🔴 **검증된 결과가 없습니다** — 아래는 재생으로"
                     " 뒷받침되지 않은 결과입니다.")
    for result in shown:
        lines.append("")
        lines.append(f"  [결과 {result.index}]"
                     + (f" (같은 결과에 닿은 다른 경로"
                        f" {result.duplicates}개)" if result.duplicates
                        else ""))
        for step in result.path:
            picked = " · ".join(
                _card_ko(card_id, repository)
                for ask in step.choices
                for card_id in ask.chosen_card_ids
            )
            tail = f" (해결 중 선택 {picked})" if picked else ""
            lines.append(f"    {step.order}. {_kind_ko(step.kind)}{tail}")
        for label, value in _result_rows(result, repository):
            lines.append(f"    {label}: {value}")
    lines.append("")
    lines.append(f"  {_OPEN_FIXED_NOTE}")
    return "\n".join(lines)


def render_open_search(outcome, repository=None, setup=None,
                       ranking=None) -> str:
    """
    **자율 탐색의 상세 기록** — 후보 전부와 빠진 사유까지 (Phase 6-BB).
    """
    lines = ["", OPEN_SEARCH_TITLE + " (상세)", _RULE]
    lines.extend(_multi_head(outcome))
    if setup is not None:
        lines.append("  입력 — 지정 패: " + " · ".join(
            _card_ko(card_id, repository) for card_id in setup.hand))
        lines.append(f"    남은 메인 덱 {len(setup.deck_rest)}장 ·"
                     f" 엑스트라 {len(setup.extra)}장")
        for note in setup.unknowns:
            lines.append(f"    🔴 {note}")
    lines.append(f"  예산: {outcome.budget.describe_ko()}")
    lines.append(f"  해결 중 선택 — 만든 분기 {outcome.choice_branches}개 ·"
                 f" 실제로 돌린 각본 {outcome.choice_plans}개 · 확인하지 못한"
                 f" 대안이 남은 물음 {outcome.choice_offers_truncated}곳")
    lines.append(f"  {_SEARCH_DISCLAIMER}")
    lines.extend(_open_ranking_lines(ranking, repository))

    lines.append("")
    lines.append("  모은 후보 전부")
    for result in outcome.results:
        state = getattr(result.rerun_state, "value", str(result.rerun_state))
        lines.append("")
        lines.append(f"  [결과 {result.index}] 재생 {state}"
                     + (f" · 같은 결과에 닿은 다른 경로 {result.duplicates}개"
                        if result.duplicates else ""))
        for step in result.path:
            picked = " · ".join(
                _card_ko(card_id, repository)
                for ask in step.choices
                for card_id in ask.chosen_card_ids
            )
            tail = f" (해결 중 선택 {picked})" if picked else ""
            lines.append(f"    {step.order}. {_kind_ko(step.kind)}{tail}")
        for label, value in _result_rows(result, repository):
            lines.append(f"    {label}: {value}")
        if ranking is not None:
            lines.append(f"    평가: {ranking.reason_ko(result.index)}")

    if outcome.unsupported:
        lines.append("")
        lines.append("  지원하지 않아 **후보가 되지 못한 수** (🔴 규칙상"
                     " 불가능하다는 뜻이 아닙니다)")
        for line in outcome.unsupported:
            lines.append(f"    · {line}")
    for label, rows in (
        ("이번 범위 밖이라 펼치지 않은 수", outcome.out_of_scope),
        ("상대 자리 때문에 더 펼치지 않은 자리", outcome.opponent_blocked),
        ("실행 중 난 예외", outcome.errors),
    ):
        if not rows:
            continue
        lines.append("")
        lines.append(f"  {label}")
        for line in rows:
            lines.append(f"    · {line}")
    if getattr(outcome, "followup_notes", ()):
        lines.append("")
        lines.append("  후속 탐색이 멈춘 자리")
        for line in outcome.followup_notes:
            lines.append(f"    · {line}")
    if getattr(outcome, "rerun_notes", ()):
        lines.append("")
        lines.append("  재생 기록")
        for line in outcome.rerun_notes:
            lines.append(f"    · {line}")
    lines.append("")
    lines.append(f"  {_OPEN_FIXED_NOTE}")
    return "\n".join(lines)
