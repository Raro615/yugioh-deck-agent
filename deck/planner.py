"""
전개 계획 — **아는 것만 적고, 모르는 자리에서 멈춘다** (Phase 4-B).

    HandProvider → 초기 패          (플래너는 패를 만들지 않는다)
    초기 상태(선택) → 필드·묘지
            ↓
    ComboPlanner.plan()
            ↓
    ComboPlan(steps, stopped_reason, unsupported, manual_checks)

🔴 **초기 패의 장수를 강제하지 않는다.** 룰북 데이터(``zones[Hand]``)가
적어 둔 상한 6 은 **"엔드 페이즈 종료 시점의 상한"** 이고, 그 파일이
"그 외 시점의 상한은 룰북에 없다" 고 명시한다. 그래서 몇 장을 받든 그대로
계획한다 — 확인되지 않은 제약을 검사하거나 거부 이유로 쓰지 않는다.

근거의 세 층 (전부 실측 기준)
-----------------------------
1. **엔진 실행 구현이 있다** — ``engine.effect.library.EFFECT_LIBRARY`` 의
   ``executable=True`` 항목. 실측 **13장**뿐이고 전부 마법·함정이다.
2. **Lua 파싱 근거가 있다** — ``card.script.effects`` 가 있고 그 효과가 패
   에서 쓸 수 있다. 실행 구현은 없다.
3. **카드 종류만 안다** — ``has_printed_effect()`` 가 참이지만 구조화된
   근거가 없다.

일반 소환과 특수 소환을 섞지 않는다
-----------------------------------
엔진에는 ``NORMAL_SUMMON`` 의 **조건 판정 계층이 있다** (그래서 돌려볼 수
있다 — 🔴 어떤 판에서 허가가 난다는 뜻이 아니다). 반면 ``SPECIAL_SUMMON`` 은
``ActionValidator`` 가 **언제나 ``UNKNOWN``** 을 돌려주고
(``UnimplementedRule("special-summon-condition")``), 융합·싱크로·엑시즈·
링크의 재료 선택 절차는 엔진에 **없다**. 그래서 특수 소환은 계획에 넣지
않고 :attr:`~deck.model.ComboPlan.unsupported` 에 적는다.

🔴 **효과를 지어내지 않는다.** 근거가 없으면 걸음을 만들지 않거나
``UNKNOWN`` 으로 적고, 사람이 확인할 항목으로 올린다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from core.card_model import Card
from deck.hand import HandProvider
from deck.model import (
    ComboPlan,
    DeckDraft,
    PlanStep,
    StepBasis,
    StepStatus,
)

_LUA_NAME = re.compile(r"^c(\d+)\.lua$")

#: 엔진이 구조적으로 지원하지 않는 절차. 계획에 넣지 않고 따로 적는다.
_UNSUPPORTED_PROCEDURES = (
    "특수 소환 (조건 판정 계층이 없어 ActionValidator 가 언제나 UNKNOWN)",
    "융합 소환 (재료 선택 절차 없음)",
    "싱크로 소환 (재료 선택 절차 없음)",
    "엑시즈 소환 (재료 선택 절차 없음)",
    "링크 소환 (재료 선택 절차 없음)",
)


def engine_executable_card_ids() -> frozenset[int]:
    """
    엔진에 **실행 구현이 등록된** 카드 ID.

    ``EFFECT_LIBRARY`` 는 손으로 쓴 목록이고, 그 사실이 그 모듈
    docstring 에 적혀 있다. 여기서는 읽기만 한다 — Engine V1 을 바꾸지
    않는다.
    """
    try:
        from engine.effect.library import EFFECT_LIBRARY
    except ImportError:  # pragma: no cover - 엔진이 없는 환경 대비
        return frozenset()
    out: set[int] = set()
    for entry in EFFECT_LIBRARY:
        if not getattr(entry, "executable", False):
            continue
        match = _LUA_NAME.match(str(getattr(entry, "lua_file", "")))
        if match:
            out.add(int(match.group(1)))
    return frozenset(out)


class ComboPlanner:
    """
    초기 패를 **받아서** 전개 계획을 만든다.

    패를 만들지 않고 난수원도 들지 않는다 — 그 둘은 :mod:`deck.hand` 의
    일이다 (그 모듈 docstring 에 이유가 있다).
    """

    def __init__(self, repository, executable_ids=None):
        self.repository = repository
        #: 주입 가능하게 둔다 — 테스트가 엔진 목록을 흉내내지 않고 실제
        #: 목록을 쓸 수 있고, 목록이 늘어나도 플래너를 고치지 않는다.
        self.executable_ids = (frozenset(executable_ids)
                               if executable_ids is not None
                               else engine_executable_card_ids())

    # ------------------------------------------------------------------
    def plan(self, hand_source: HandProvider | Sequence[int],
             board: Sequence[int] = (),
             draft: DeckDraft | None = None) -> ComboPlan:
        """
        전개 계획을 만든다.

        Args:
            hand_source: :class:`~deck.hand.HandProvider` 또는 카드 ID 목록.
                🔴 **장수를 보지 않는다.** 빈 패도 그대로 받는다.
            board: 이미 필드·묘지에 있는 카드 ID (선택). 주지 않으면 비운다 —
                **비어 있다고 추측해 채우지 않는다.**
            draft: 덱 초안 (선택). 주면 패가 덱과 맞는지 함께 본다.
                주지 않으면 그 검증은 **하지 않았다고 적는다.**
        """
        hand = list(hand_source.hand() if isinstance(hand_source, HandProvider)
                    else hand_source)
        plan = ComboPlan(hand=list(hand), board=list(board))
        plan.unsupported.extend(_UNSUPPORTED_PROCEDURES)

        self._check_hand_against_deck(plan, hand, draft)

        if not hand:
            plan.stopped_reason = (
                "초기 패가 비어 있습니다. 패를 지정하면 계획을 세웁니다 "
                "(무작위 패 생성은 구현되어 있지 않습니다)")
            return plan

        order = 0
        summon_right_used = False
        for card_id in hand:
            card = self.repository.get(card_id)
            if card is None:
                order += 1
                plan.steps.append(PlanStep(
                    order=order, card_id=card_id, card_name=f"#{card_id}",
                    action="이 카드로 할 수 있는 것을 판단하지 못했습니다",
                    requires=("카드 ID 가 저장소에 있어야 합니다",),
                    expected="(없음)",
                    basis=StepBasis.NONE, status=StepStatus.UNKNOWN,
                    note="저장소에서 이 카드 ID 를 찾지 못했습니다",
                ))
                plan.manual_checks.append(
                    f"카드 ID {card_id} 가 올바른지 확인하세요")
                continue

            steps, summon_right_used = self._steps_for(
                card, order, summon_right_used)
            for step in steps:
                order += 1
                plan.steps.append(PlanStep(
                    order=order, card_id=step.card_id,
                    card_name=step.card_name, action=step.action,
                    requires=step.requires, expected=step.expected,
                    basis=step.basis, status=step.status, note=step.note,
                ))

        self._finish(plan)
        return plan

    # ------------------------------------------------------------------
    def _steps_for(self, card: Card, order: int,
                   summon_right_used: bool) -> tuple[list[PlanStep], bool]:
        """카드 하나로 할 수 있는 걸음들. 순서 번호는 부르는 쪽이 다시 붙인다."""
        name = card.display_name()
        steps: list[PlanStep] = []

        if card.is_extra_deck:
            steps.append(PlanStep(
                order=order, card_id=card.id, card_name=name,
                action="엑스트라 덱 카드가 패에 있습니다 — 전개에 쓰지 않았습니다",
                requires=("엑스트라 덱 카드는 통상적으로 패에 오지 않습니다",),
                expected="(없음)",
                basis=StepBasis.PRINTED_TYPE_ONLY,
                status=StepStatus.UNSUPPORTED,
                note="엑스트라 덱 카드의 소환 절차가 엔진에 없습니다",
            ))
            return steps, summon_right_used

        if card.is_monster:
            if not summon_right_used:
                steps.append(PlanStep(
                    order=order, card_id=card.id, card_name=name,
                    action=f"'{name}' 을 일반 소환합니다",
                    requires=("이번 턴 일반 소환권이 남아 있어야 합니다",
                              "메인 몬스터 존에 빈 자리가 있어야 합니다"),
                    expected="성공하면 앞면 공격 표시로 몬스터 존에 놓입니다",
                    basis=StepBasis.ENGINE_ACTION,
                    status=StepStatus.CONFIRMED,
                    #: 🔴 **"허가합니다" 를 쓰지 않는다** (보완8 세 항목 ③).
                    #: 이 계획은 엔진을 돌리지 않으므로 **이 판에서 허가를
                    #: 받은 것이 아니다.** 있는 것은 *그 행동 종류의 판정
                    #: 기능*이고, 그것과 *이 판에서의 허가*는 다른 사실이다.
                    note=("일반 소환은 **판정 계층이 있는 종류**입니다"
                          " (특수 소환과 달리) — 이 판의 허가가 아닙니다"),
                ))
                summon_right_used = True
            else:
                steps.append(PlanStep(
                    order=order, card_id=card.id, card_name=name,
                    action=f"'{name}' 을 일반 소환합니다",
                    requires=("🔴 이번 턴 일반 소환권을 이미 썼습니다 —"
                              " 추가 소환 수단이 필요합니다",),
                    expected="성공하면 앞면 공격 표시로 몬스터 존에 놓입니다",
                    basis=StepBasis.ENGINE_ACTION,
                    status=StepStatus.CONDITIONAL,
                    note="소환권을 되찾는 수단을 이 계획이 찾지 못했습니다",
                ))

        effect_step = self._effect_step(card, order, name)
        if effect_step is not None:
            steps.append(effect_step)

        if not steps:
            steps.append(PlanStep(
                order=order, card_id=card.id, card_name=name,
                action=f"'{name}' 으로 할 수 있는 것을 찾지 못했습니다",
                requires=(),
                expected="(없음)",
                basis=StepBasis.NONE, status=StepStatus.UNKNOWN,
                note="패에서 쓸 수 있는 근거를 찾지 못했습니다",
            ))
        return steps, summon_right_used

    def _effect_step(self, card: Card, order: int,
                     name: str) -> PlanStep | None:
        """
        카드 효과를 쓰는 걸음. **근거의 층에 따라 상태가 달라진다.**

        🔴 효과가 무엇을 하는지 **서술하지 않는다.** 서술하려면 효과를
        해석해야 하고, 이 저장소는 그 해석을 보증하지 않는다. 대신 "발동
        한다" 와 "근거가 어디까지인가" 만 적는다.
        """
        if card.id in self.executable_ids:
            return PlanStep(
                order=order, card_id=card.id, card_name=name,
                action=f"'{name}' 의 효과를 발동합니다",
                requires=("카드에 적힌 발동 조건을 사람이 확인해야 합니다",),
                #: 🔴 **결과를 단정하지 않는다** (보완8 세 항목 ③). 이
                #: 걸음은 실행하지 않았으므로 발동이 적법한지도 모른다.
                expected="발동이 성공하면 엔진에 등록된 구현대로 상태가 바뀝니다",
                basis=StepBasis.ENGINE_EXECUTABLE,
                status=StepStatus.CONFIRMED,
                note=("엔진에 실행 구현이 등록된 카드입니다 — **돌려볼 수"
                      " 있다**는 뜻이고 이 판의 적법성이 아닙니다"),
            )

        if card.effects and card.has_effect_from("HAND"):
            return PlanStep(
                order=order, card_id=card.id, card_name=name,
                action=f"'{name}' 의 패에서 발동하는 효과를 씁니다",
                requires=("발동 조건을 이 저장소가 판정하지 못합니다",),
                expected="(효과 내용은 카드 텍스트를 확인하세요)",
                basis=StepBasis.LUA_PARSED,
                status=StepStatus.CONDITIONAL,
                note=(f"Lua 효과 블록 {len(card.effects)}개가 파싱되어"
                      f" 있으나 실행 구현은 없습니다"),
            )

        if card.is_spell or card.is_trap:
            if card.effects:
                return PlanStep(
                    order=order, card_id=card.id, card_name=name,
                    action=f"'{name}' 을 발동합니다",
                    requires=("발동 조건을 이 저장소가 판정하지 못합니다",),
                    expected="(효과 내용은 카드 텍스트를 확인하세요)",
                    basis=StepBasis.LUA_PARSED,
                    status=StepStatus.CONDITIONAL,
                    note=(f"Lua 효과 블록 {len(card.effects)}개가 파싱되어"
                          f" 있으나 실행 구현은 없습니다"),
                )
            return PlanStep(
                order=order, card_id=card.id, card_name=name,
                action=f"'{name}' 을 발동합니다",
                requires=("효과의 구조화된 근거가 없습니다",),
                expected="(없음)",
                basis=(StepBasis.PRINTED_TYPE_ONLY
                       if card.has_printed_effect else StepBasis.NONE),
                status=StepStatus.UNKNOWN,
                note="Lua 스크립트가 없어 효과를 구조적으로 알지 못합니다",
            )
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _check_hand_against_deck(plan: ComboPlan, hand: list[int],
                                 draft: DeckDraft | None) -> None:
        """
        패가 덱과 맞는지. **덱을 받지 않았으면 검증하지 않았다고 적는다.**
        """
        if draft is None:
            plan.manual_checks.append(
                "덱 초안을 함께 주지 않았으므로 '이 패가 덱에서 나올 수"
                " 있는가' 는 검증하지 않았습니다")
            return
        available: dict[int, int] = {}
        for slot in draft.all_slots():
            available[slot.card_id] = available.get(slot.card_id, 0) + slot.copies
        for card_id in set(hand):
            needed = hand.count(card_id)
            have = available.get(card_id, 0)
            if have == 0:
                plan.manual_checks.append(
                    f"카드 ID {card_id} 가 덱 초안에 없습니다")
            elif needed > have:
                plan.manual_checks.append(
                    f"카드 ID {card_id} 를 패에 {needed}장 두었으나 덱"
                    f" 초안에는 {have}장뿐입니다")

    @staticmethod
    def _finish(plan: ComboPlan) -> None:
        """계획을 닫는다 — 중단 사유와 사람이 볼 항목을 정리한다."""
        usable = [s for s in plan.steps
                  if s.status in (StepStatus.CONFIRMED,
                                  StepStatus.CONDITIONAL)]
        if not usable:
            plan.stopped_reason = (
                "패의 어느 카드에서도 근거 있는 첫 걸음을 찾지 못했습니다")
        else:
            unknown = [s for s in plan.steps
                       if s.status is StepStatus.UNKNOWN]
            if unknown:
                plan.stopped_reason = (
                    f"근거가 없는 카드 {len(unknown)}장이 있어 그 뒤의"
                    f" 전개는 계획하지 않았습니다")

        for step in plan.steps:
            if step.status in (StepStatus.UNKNOWN, StepStatus.UNSUPPORTED):
                plan.manual_checks.append(
                    f"{step.order}. '{step.card_name}' — "
                    f"{step.status.describe_ko()}: {step.note}")
        plan.manual_checks.append(
            "🔴 이 계획은 실제 듀얼에서 합법인지 검증되지 않았습니다 —"
            " Duel Simulator 에서 사람이 직접 재현해 확인해야 합니다")
